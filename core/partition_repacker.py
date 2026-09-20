#!/usr/bin/env python3
"""
Autoporter Partition Repacker Module:
Repacks modified partitions from 'cauldron' into 'finalized'.
Preserves original metadata, SELinux contexts, and permissions,
with full customization for EROFS / EXT4 compression algorithms and levels.
"""

import os
import sys
import json
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Optional

from core.config import (
    get_binary,
    CAULDRON_DIR,
    FINALIZED_DIR,
    format_size,
    parse_size_bytes,
)
from core.ui import (
    Colors,
    Spinner,
    print_info,
    print_success,
    print_warning,
    print_error,
    print_section,
    print_table,
    progress_bar,
    ask_choice,
    ask_text,
    ask_confirm,
    parse_range_selection,
)
from core.context_sync import sync_partition_contexts


def get_unpacked_partitions() -> List[Dict[str, any]]:
    """Discovers all unpacked partitions in cauldron/."""
    partitions = []
    if not CAULDRON_DIR.exists():
        return partitions

    for item in sorted(CAULDRON_DIR.iterdir()):
        if not item.is_dir() or item.name in ["config", ".meta", "unpacked_super"]:
            continue

        meta_file = CAULDRON_DIR / f"{item.name}.meta.json"
        meta_data = {}
        if meta_file.exists():
            try:
                with open(meta_file, "r") as f:
                    meta_data = json.load(f)
            except Exception:
                pass

        # Check if boot image
        is_boot = meta_data.get("type") == "boot_image" or (item / "kernel").exists() or (item / "header").exists()
        fs_type = "boot_image" if is_boot else meta_data.get("type", "erofs")

        # Calculate current directory size
        dir_size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())

        partitions.append({
            "name": item.name,
            "path": item,
            "type": fs_type,
            "meta": meta_data,
            "dir_size": dir_size,
            "orig_size": meta_data.get("original_size", dir_size),
        })
    return partitions


def repack_boot_partition(part_info: Dict[str, any], output_dir: Path = FINALIZED_DIR) -> bool:
    """Repacks a boot/kernel partition using magiskboot repack."""
    part_name = part_info["name"]
    part_dir = part_info["path"]
    output_dir.mkdir(parents=True, exist_ok=True)
    out_img = output_dir / f"{part_name}.img"

    magiskboot_tool = get_binary("magiskboot")
    cpio_tool = get_binary("cpio")

    # Step 1: If ramdisk directory exists and was modified, repack it into ramdisk.cpio
    ramdisk_dir = part_dir / "ramdisk"
    ramdisk_cpio = part_dir / "ramdisk.cpio"
    if ramdisk_dir.exists() and ramdisk_dir.is_dir():
        with Spinner(f"Repacking ramdisk for {part_name}..."):
            # Using find . | cpio -H newc -o > ../ramdisk.cpio
            find_proc = subprocess.Popen(["find", "."], cwd=str(ramdisk_dir), stdout=subprocess.PIPE)
            with open(ramdisk_cpio, "wb") as f_out:
                cpio_proc = subprocess.run([cpio_tool, "-H", "newc", "-o"], cwd=str(ramdisk_dir), stdin=find_proc.stdout, stdout=f_out, stderr=subprocess.PIPE)
                find_proc.wait()

    # Step 2: Locate original image used for unpacking
    orig_img = part_dir / f"{part_name}.img"
    if not orig_img.exists():
        # Look in metadata
        orig_from_meta = part_info["meta"].get("original_file")
        if orig_from_meta and Path(orig_from_meta).exists():
            orig_img = Path(orig_from_meta)

    if not orig_img.exists():
        print_error(f"Original boot image reference not found for {part_name}.")
        return False

    temp_out = part_dir / "new-boot.img"
    if temp_out.exists():
        temp_out.unlink()

    print_info(f"Repacking boot image {part_name} via magiskboot...")
    with Spinner(f"Compiling {part_name}.img with kernel & ramdisk..."):
        res = subprocess.run(
            [magiskboot_tool, "repack", str(orig_img), str(temp_out)],
            cwd=str(part_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    if res.returncode != 0 or not temp_out.exists():
        print_error(f"magiskboot repack failed: {res.stderr}")
        return False

    shutil.move(str(temp_out), str(out_img))
    print_success(f"Repacked {part_name}.img -> {out_img} ({format_size(out_img.stat().st_size)})")
    return True


def repack_filesystem_partition(
    part_info: Dict[str, any],
    fs_type: str = "erofs",
    compress_algo: str = "lz4hc",
    compress_level: int = 9,
    custom_size_bytes: Optional[int] = None,
    output_dir: Path = FINALIZED_DIR,
) -> bool:
    """
    Repacks an EROFS or EXT4 partition with security contexts and permissions.
    """
    part_name = part_info["name"]
    part_dir = part_info["path"]
    config_dir = CAULDRON_DIR / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    out_img = output_dir / f"{part_name}.img"

    # Step 1: Synchronize permissions and contexts
    print_info(f"Synchronizing permissions and SELinux contexts for {part_name}...")
    added_fs, added_ctx = sync_partition_contexts(part_name, part_dir, config_dir)
    if added_fs > 0 or added_ctx > 0:
        print_info(f"Synthesized security contexts: +{added_fs} permissions, +{added_ctx} SELinux labels")

    fs_config = config_dir / f"{part_name}_fs_config"
    file_contexts = config_dir / f"{part_name}_file_contexts"

    imgkit_tool = get_binary("imgkit")

    if fs_type.lower() == "erofs":
        print_info(f"Repacking {part_name} as EROFS [Algo: {compress_algo.upper()}, Level: {compress_level}]...")
        cmd = [
            imgkit_tool,
            "pack",
            "--type", "erofs",
            "-s", str(part_dir),
            "-o", str(out_img),
            "-m", f"/{part_name}",
            "--label", part_name,
        ]
        if compress_algo != "none":
            cmd.extend(["--compress", compress_algo])
            if compress_algo in ["lz4hc", "lzma", "deflate", "zstd"]:
                cmd.extend(["--compress-level", str(compress_level)])

        if file_contexts.is_file():
            cmd.extend(["--file-contexts", str(file_contexts)])
        if fs_config.is_file():
            cmd.extend(["--fs-config", str(fs_config)])

        with Spinner(f"Packing EROFS image {part_name}.img..."):
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if res.returncode != 0 or not out_img.exists():
            # Fallback to mkfs.erofs
            print_warning("imgkit erofs pack fallback to mkfs.erofs...")
            mkfs_tool = get_binary("mkfs.erofs")
            mkfs_cmd = [mkfs_tool]
            if compress_algo != "none":
                mkfs_cmd.append(f"-z{compress_algo},level={compress_level}")
            if file_contexts.is_file():
                mkfs_cmd.append(f"--file-contexts={file_contexts}")
            if fs_config.is_file():
                mkfs_cmd.append(f"--fs-config-file={fs_config}")
            mkfs_cmd.extend([f"--mount-point=/{part_name}", str(out_img), str(part_dir)])

            with Spinner(f"Building with mkfs.erofs..."):
                res = subprocess.run(mkfs_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    else:  # EXT4
        # Calculate image size
        if custom_size_bytes:
            target_size = custom_size_bytes
        else:
            # Current dir size + 64MB buffer for filesystem overhead and metadata
            content_size = part_info["dir_size"]
            headroom = 64 * 1024 * 1024
            target_size = content_size + headroom
            # Round up to 4096 alignment
            target_size = ((target_size + 4095) // 4096) * 4096

        print_info(f"Repacking {part_name} as EXT4 [Target Size: {format_size(target_size)}]...")
        cmd = [
            imgkit_tool,
            "pack",
            "--type", "ext4",
            "-s", str(part_dir),
            "-o", str(out_img),
            "-z", str(target_size),
            "-m", f"/{part_name}",
            "--label", part_name,
        ]
        if file_contexts.is_file():
            cmd.extend(["--file-contexts", str(file_contexts)])
        if fs_config.is_file():
            cmd.extend(["--fs-config", str(fs_config)])

        with Spinner(f"Packing EXT4 image {part_name}.img..."):
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if not out_img.exists() or out_img.stat().st_size == 0:
        print_error(f"Failed to repack {part_name}: {res.stderr or res.stdout}")
        return False

    orig_sz = part_info.get("orig_size", 0)
    new_sz = out_img.stat().st_size
    diff_pct = f"({(new_sz - orig_sz) / orig_sz * 100:+.1f}%)" if orig_sz > 0 else ""
    print_success(f"Finalized {out_img.name}: {format_size(new_sz)} {diff_pct}")
    return True


def customize_repack_options(part_info: Dict[str, any]) -> Dict[str, any]:
    """Prompts user to customize filesystem type and compression algorithms/levels."""
    orig_fs = part_info.get("type", "erofs")

    print_section(f"Repack Options for: {part_info['name']}")
    fs_options = ["EROFS (Enhanced Read-Only Filesystem - Standard Android)", "EXT4 (Standard Linux Filesystem)"]
    def_fs_idx = 0 if orig_fs == "erofs" else 1
    fs_choice = ask_choice("Select Target Filesystem Type:", fs_options, default_idx=def_fs_idx)
    target_fs = "erofs" if fs_choice == 0 else "ext4"

    if target_fs == "erofs":
        algo_options = [
            "lz4hc (High Compression LZ4 - Xiaomi/AOSP Default) [Level 0-12]",
            "lz4 (Standard Fast LZ4) [No level]",
            "lzma (Extreme Compression - Smallest Size) [Level 0-9]",
            "deflate (Standard Deflate / Zip) [Level 0-9]",
            "zstd (Modern Zstandard Compression) [Level 0-22]",
            "none (Uncompressed)",
        ]
        algo_choice = ask_choice("Select EROFS Compression Algorithm:", algo_options, default_idx=0)
        algo_map = ["lz4hc", "lz4", "lzma", "deflate", "zstd", "none"]
        chosen_algo = algo_map[algo_choice]

        level = 9
        if chosen_algo == "lz4hc":
            lvl_str = ask_text("Enter lz4hc compression level [0-12]", default="9")
            level = int(lvl_str) if lvl_str.isdigit() else 9
        elif chosen_algo == "lzma":
            lvl_str = ask_text("Enter lzma compression level [0-9]", default="6")
            level = int(lvl_str) if lvl_str.isdigit() else 6
        elif chosen_algo == "deflate":
            lvl_str = ask_text("Enter deflate compression level [0-9]", default="1")
            level = int(lvl_str) if lvl_str.isdigit() else 1
        elif chosen_algo == "zstd":
            lvl_str = ask_text("Enter zstd compression level [0-22]", default="3")
            level = int(lvl_str) if lvl_str.isdigit() else 3

        return {"fs_type": "erofs", "compress_algo": chosen_algo, "compress_level": level, "custom_size": None}

    else:
        print_info(f"Current contents size: {format_size(part_info['dir_size'])}")
        size_opts = [
            "Auto (Content Size + 64 MB overhead buffer)",
            "Auto + 128 MB headroom",
            "Auto + 256 MB headroom",
            "Custom size (e.g. 2.5G, 3000M, 3221225472)",
        ]
        s_choice = ask_choice("Choose EXT4 image sizing:", size_opts, default_idx=0)
        custom_size = None
        if s_choice == 1:
            custom_size = part_info["dir_size"] + (128 * 1024 * 1024)
        elif s_choice == 2:
            custom_size = part_info["dir_size"] + (256 * 1024 * 1024)
        elif s_choice == 3:
            s_input = ask_text("Enter desired image size (e.g. 2.5G, 3000MB)")
            try:
                custom_size = parse_size_bytes(s_input)
            except Exception as e:
                print_warning(f"Failed to parse size: {e}. Falling back to Auto.")
                custom_size = None

        return {"fs_type": "ext4", "compress_algo": "none", "compress_level": 0, "custom_size": custom_size}


def run_partition_repacker_menu():
    """Interactive CLI menu for Partition Repacking."""
    print_section("Repack Modified Partitions to Finalized")

    unpacked = get_unpacked_partitions()
    if not unpacked:
        print_warning(f"No unpacked partitions found in {CAULDRON_DIR}.")
        print_info("Unpack some images first using Option 2.")
        return

    # Display status table
    headers = ["#", "Partition", "Type", "Content Size", "Original Image Size"]
    rows = []
    for i, p in enumerate(unpacked):
        rows.append([
            str(i + 1),
            p["name"],
            f"{Colors.CYAN}{p['type'].upper()}{Colors.RESET}",
            format_size(p["dir_size"]),
            format_size(p["orig_size"]),
        ])
    print_table(headers, rows)

    options = [
        f"Repack ALL partitions using original metadata defaults ({len(unpacked)} partitions)",
        "Select specific partition(s) or ranges (e.g. 1-15, 18-20, or single to customize)",
        "Cancel",
    ]
    choice = ask_choice("Choose repacking action:", options, default_idx=0)

    if choice == 0:
        total = len(unpacked)
        for i, p in enumerate(unpacked):
            progress_bar(i, total, prefix="Batch Repacking", suffix=p["name"])
            if p["type"] == "boot_image":
                repack_boot_partition(p)
            else:
                repack_filesystem_partition(p, fs_type=p.get("type", "erofs"))
        progress_bar(total, total, prefix="Batch Repacking", suffix="Done!")
        print_success(f"All partitions repacked into {FINALIZED_DIR}")

    elif choice == 1:
        sel_str = ask_text(f"Enter partition numbers/ranges to repack (e.g. 1-15, 18-20, or names) [1-{len(unpacked)}]")
        if not sel_str:
            return
        indices = parse_range_selection(sel_str, len(unpacked), [p["name"] for p in unpacked])
        if not indices:
            print_warning("No valid partitions selected.")
            return

        if len(indices) == 1:
            target_p = unpacked[indices[0]]
            if target_p["type"] == "boot_image":
                repack_boot_partition(target_p)
            else:
                opts = customize_repack_options(target_p)
                repack_filesystem_partition(
                    target_p,
                    fs_type=opts["fs_type"],
                    compress_algo=opts["compress_algo"],
                    compress_level=opts["compress_level"],
                    custom_size_bytes=opts["custom_size"],
                )
        else:
            total = len(indices)
            for i, idx in enumerate(indices):
                target_p = unpacked[idx]
                progress_bar(i, total, prefix="Repacking", suffix=target_p["name"])
                if target_p["type"] == "boot_image":
                    repack_boot_partition(target_p)
                else:
                    repack_filesystem_partition(target_p, fs_type=target_p.get("type", "erofs"))
            progress_bar(total, total, prefix="Repacking", suffix="Completed!")
            print_success(f"Repacked {total} selected partition(s) into {FINALIZED_DIR}")
    else:
        return
