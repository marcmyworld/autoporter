#!/usr/bin/env python3
"""
Autoporter Partition Unpacker Module:
Unpacks Super, EROFS, EXT4, F2FS, and Boot/Vendor_boot/Kernel images into 'cauldron'.
Preserves file_contexts, fs_config, permissions, and image metadata.
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
    IMAGES_DIR,
    CAULDRON_DIR,
    detect_file_type,
    format_size,
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


def list_available_images() -> List[Dict[str, any]]:
    """Lists all available images in the images/ directory."""
    images = []
    if not IMAGES_DIR.exists():
        return images

    for img_path in sorted(IMAGES_DIR.glob("*.img")):
        if img_path.is_file():
            ftype = detect_file_type(img_path)
            images.append({
                "path": img_path,
                "name": img_path.stem,
                "filename": img_path.name,
                "size": img_path.stat().st_size,
                "type": ftype,
            })
    return images


def unsparse_image_if_needed(img_path: Path) -> Path:
    """If image is Android sparse image format, converts it to raw image using simg2img."""
    ftype = detect_file_type(img_path)
    if ftype != "sparse":
        return img_path

    raw_path = img_path.parent / f"{img_path.stem}_raw.img"
    print_info(f"Detected Android sparse image format for {img_path.name}. Converting to raw image...")
    simg2img_tool = get_binary("simg2img")

    with Spinner(f"Unsparsing {img_path.name} -> {raw_path.name}..."):
        res = subprocess.run([simg2img_tool, str(img_path), str(raw_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if res.returncode == 0 and raw_path.exists():
        # Replace original with raw or keep raw
        shutil.move(str(raw_path), str(img_path))
        print_success(f"Unsparsed {img_path.name} ({format_size(img_path.stat().st_size)})")
        return img_path
    else:
        print_error(f"Failed to unsparse {img_path.name}: {res.stderr}")
        return img_path


def unpack_super_image(super_path: Path, output_dir: Path = IMAGES_DIR) -> List[Path]:
    """Unpacks a super.img into individual partition images using lpunpack."""
    print_info(f"Unpacking Super Image: {super_path.name} ({format_size(super_path.stat().st_size)})")
    unsparse_image_if_needed(super_path)

    output_dir.mkdir(parents=True, exist_ok=True)
    before_imgs = {p.resolve() for p in output_dir.glob("*.img")}

    lpunpack_tool = get_binary("lpunpack")

    with Spinner(f"Extracting logical partitions from {super_path.name}..."):
        res = subprocess.run([lpunpack_tool, str(super_path), str(output_dir)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if res.returncode != 0:
        # Fallback to imgkit unpack
        print_warning(f"lpunpack exited with code {res.returncode}. Trying imgkit unpack fallback...")
        imgkit_tool = get_binary("imgkit")
        with Spinner("Extracting super with imgkit..."):
            res = subprocess.run([imgkit_tool, "unpack", "-i", str(super_path), "-o", str(output_dir)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    after_imgs = {p.resolve() for p in output_dir.glob("*.img")}
    new_imgs = [p for p in sorted(list(after_imgs - before_imgs), key=lambda x: x.name) if p.name != super_path.name]
    print_success(f"Super image unpacked. Extracted {len(new_imgs)} logical partition image(s) to {output_dir}")
    return new_imgs



def unpack_boot_image(boot_path: Path, cauldron_dir: Path = CAULDRON_DIR) -> bool:
    """
    Unpacks boot.img, vendor_boot.img, init_boot.img, or recovery.img
    using magiskboot unpack into cauldron/<partition_name>/
    and extracts ramdisk.cpio if present.
    """
    part_name = boot_path.stem
    target_dir = cauldron_dir / part_name
    target_dir.mkdir(parents=True, exist_ok=True)

    # Keep a copy of original image in cauldron partition directory for repacking reference
    orig_copy = target_dir / boot_path.name
    shutil.copy2(boot_path, orig_copy)

    magiskboot_tool = get_binary("magiskboot")
    print_info(f"Unpacking boot/kernel image: {boot_path.name} into cauldron/{part_name}/")

    with Spinner(f"Unpacking {part_name} via magiskboot..."):
        res = subprocess.run(
            [magiskboot_tool, "unpack", "-h", str(orig_copy)],
            cwd=str(target_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    if res.returncode not in [0, 2]:  # 0: valid, 2: chromeos
        print_error(f"magiskboot failed to unpack {boot_path.name}: {res.stderr}")
        return False

    # Check for ramdisk.cpio and extract it into a ramdisk/ subdirectory for user editing
    ramdisk_cpio = target_dir / "ramdisk.cpio"
    has_ramdisk = False
    if ramdisk_cpio.exists() and ramdisk_cpio.stat().st_size > 0:
        has_ramdisk = True
        ramdisk_dir = target_dir / "ramdisk"
        ramdisk_dir.mkdir(parents=True, exist_ok=True)
        # Backup original cpio
        shutil.copy2(ramdisk_cpio, target_dir / "ramdisk.cpio.orig")
        with Spinner(f"Extracting {part_name} ramdisk.cpio..."):
            subprocess.run(
                [magiskboot_tool, "cpio", str(ramdisk_cpio), "extract"],
                cwd=str(ramdisk_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

    # Save partition metadata
    meta = {
        "partition_name": part_name,
        "type": "boot_image",
        "original_file": str(boot_path),
        "original_size": boot_path.stat().st_size,
        "has_ramdisk": has_ramdisk,
        "has_kernel": (target_dir / "kernel").exists(),
        "has_dtb": (target_dir / "dtb").exists(),
        "header_exists": (target_dir / "header").exists(),
    }
    with open(target_dir / f"{part_name}.meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    print_success(f"Boot image '{part_name}' unpacked into cauldron/{part_name}/")
    return True


def unpack_filesystem_image(img_path: Path, cauldron_dir: Path = CAULDRON_DIR) -> bool:
    """
    Unpacks filesystem image (EROFS, EXT4, F2FS) into cauldron/<partition_name>/
    and preserves fs_config and file_contexts in cauldron/config/.
    """
    unsparse_image_if_needed(img_path)
    part_name = img_path.stem
    ftype = detect_file_type(img_path)
    imgkit_tool = get_binary("imgkit")

    print_info(f"Unpacking {Colors.BOLD}{part_name}{Colors.RESET} ({ftype.upper()} - {format_size(img_path.stat().st_size)})")

    with Spinner(f"Extracting {part_name} files and security contexts with imgkit..."):
        res = subprocess.run(
            [imgkit_tool, "unpack", "-i", str(img_path), "-o", str(cauldron_dir)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    # Check if target folder was created
    part_dir = cauldron_dir / part_name
    if not part_dir.exists():
        # Sometimes imgkit creates folder with stripped slot suffix, check
        alt_dirs = [d for d in cauldron_dir.iterdir() if d.is_dir() and d.name.startswith(part_name)]
        if alt_dirs:
            part_dir = alt_dirs[0]

    if not part_dir.exists():
        print_error(f"Failed to extract {part_name}: {res.stderr or res.stdout}")
        return False

    config_dir = cauldron_dir / "config"
    fs_config = config_dir / f"{part_name}_fs_config"
    file_contexts = config_dir / f"{part_name}_file_contexts"

    # Save partition metadata
    meta = {
        "partition_name": part_name,
        "type": ftype,
        "original_file": str(img_path),
        "original_size": img_path.stat().st_size,
        "mount_point": f"/{part_name}",
        "label": part_name,
        "fs_config": str(fs_config) if fs_config.exists() else None,
        "file_contexts": str(file_contexts) if file_contexts.exists() else None,
    }
    with open(cauldron_dir / f"{part_name}.meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    print_success(f"Extracted '{part_name}' to cauldron/{part_name}/")
    if fs_config.exists() and file_contexts.exists():
        print_info(f"Preserved SELinux contexts ({file_contexts.name}) and permissions ({fs_config.name})")
    return True


def unpack_image(img_path: Path) -> bool:
    """Dispatches unpacking based on detected image type."""
    ftype = detect_file_type(img_path)
    if ftype == "sparse":
        unsparse_image_if_needed(img_path)
        ftype = detect_file_type(img_path)

    if ftype == "super":
        return unpack_super_image(img_path)
    elif ftype == "boot":
        return unpack_boot_image(img_path)
    elif ftype in ["erofs", "ext4"]:
        return unpack_filesystem_image(img_path)
    else:
        # Check stem name for boot or fallback to filesystem unpack
        stem = img_path.stem.lower()
        if any(b_name in stem for b_name in ["boot", "vendor_boot", "init_boot", "recovery"]):
            return unpack_boot_image(img_path)
        return unpack_filesystem_image(img_path)


def run_partition_unpacker_menu():
    """Interactive CLI menu for Partition Image Unpacking."""
    print_section("Unpack Partition Images to Cauldron")

    available = list_available_images()
    if not available:
        print_warning(f"No partition images found in {IMAGES_DIR}.")
        print_info("You can dump an OTA ROM first (Option 1) or place .img files into 'images/' or 'input/'.")
        custom = ask_text("Enter path to an image file (or Enter to cancel)")
        if not custom or not Path(custom).exists():
            return
        unpack_image(Path(custom).resolve())
        return

    # Display available images table
    headers = ["#", "Partition", "Type", "Size", "Filename"]
    rows = []
    for i, img in enumerate(available):
        type_color = Colors.GREEN if img["type"] == "erofs" else (Colors.CYAN if img["type"] == "ext4" else Colors.YELLOW)
        rows.append([
            str(i + 1),
            img["name"],
            f"{type_color}{img['type'].upper()}{Colors.RESET}",
            format_size(img["size"]),
            img["filename"],
        ])
    print_table(headers, rows)

    options = [f"Unpack ALL ({len(available)} images)", "Select specific image(s) or ranges (e.g. 1-15, 18-20, or names)", "Cancel"]
    choice = ask_choice("Choose unpacking mode:", options, default_idx=0)

    if choice == 0:
        total = len(available)
        for i, img in enumerate(available):
            progress_bar(i, total, prefix="Batch Unpacking", suffix=img["name"])
            unpack_image(img["path"])
        progress_bar(total, total, prefix="Batch Unpacking", suffix="Completed!")
        print_success("All images unpacked into cauldron/")
    elif choice == 1:
        indices_str = ask_text(f"Enter image numbers/ranges to unpack (e.g. 1-15, 18-20, or boot, super) [1-{len(available)}]")
        if not indices_str:
            return
        indices = parse_range_selection(indices_str, len(available), [img["name"] for img in available])
        if not indices:
            print_warning("No valid images selected.")
            return
        total = len(indices)
        for i, idx in enumerate(indices):
            img = available[idx]
            progress_bar(i, total, prefix="Unpacking", suffix=img["name"])
            unpack_image(img["path"])
        progress_bar(total, total, prefix="Unpacking", suffix="Completed!")
        print_success(f"Unpacked {total} selected partition(s) into cauldron/")
    else:
        return
