#!/usr/bin/env python3
"""
Autoporter Super Image Builder Module:
Packs finalized or extracted dynamic partitions into 'super.img' using lpmake / imgkit.
Features binary system size calculations (e.g., 8.5 GB = 9126805504 bytes),
group allocation, sparse generation, and Virtual A/B support.
"""

import os
import sys
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from core.config import (
    get_binary,
    FINALIZED_DIR,
    IMAGES_DIR,
    OUTPUT_DIR,
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
)


def get_candidate_super_partitions() -> List[Dict[str, any]]:
    """
    Finds partition images available for super.img.
    Prioritizes finalized/ over images/.
    Excludes boot images (boot, vendor_boot, dtbo, etc.) from super partitions.
    """
    non_super_names = ["boot", "vendor_boot", "init_boot", "dtbo", "vbmeta", "recovery"]
    candidates = {}

    # Check finalized/
    if FINALIZED_DIR.exists():
        for p in FINALIZED_DIR.glob("*.img"):
            stem = p.stem.lower()
            if not any(stem.startswith(x) for x in non_super_names):
                candidates[p.stem] = {"path": p, "source": "finalized", "size": p.stat().st_size}

    # Check images/ for partitions not in finalized
    if IMAGES_DIR.exists():
        for p in IMAGES_DIR.glob("*.img"):
            stem = p.stem.lower()
            if stem not in candidates and not any(stem.startswith(x) for x in non_super_names) and stem != "super":
                candidates[p.stem] = {"path": p, "source": "images", "size": p.stat().st_size}

    return sorted(candidates.values(), key=lambda x: x["path"].stem)


def compute_super_size(user_input: str, total_partition_bytes: int) -> int:
    """
    Computes exact binary system bytes from user input or preset.
    Examples:
      - '8.5 GB' -> 8.5 * (1024^3) = 9126805504 bytes
      - 'auto' -> total_partition_bytes + 128MB overhead rounded to 4MB
    """
    clean = user_input.strip().lower()
    if clean == "auto":
        # Sum of partition sizes + 128 MB buffer, aligned to 4MB (4194304)
        raw = total_partition_bytes + (128 * 1024 * 1024)
        alignment = 4 * 1024 * 1024
        return ((raw + alignment - 1) // alignment) * alignment

    return parse_size_bytes(user_input)


def build_super_image(
    partitions: List[Dict[str, any]],
    device_size: int,
    group_name: str = "qti_dynamic_partitions",
    is_sparse: bool = True,
    is_vab: bool = True,
    output_path: Optional[Path] = None,
) -> bool:
    """
    Builds super.img using lpmake with imgkit pack fallback.
    """
    if not output_path:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = OUTPUT_DIR / "super.img"

    # Total size of included partitions
    total_parts_size = sum(p["size"] for p in partitions)
    print_info(f"Target super.img: {output_path}")
    print_info(f"Configured Super Device Size: {Colors.BRIGHT_GREEN}{device_size} bytes{Colors.RESET} ({format_size(device_size)})")
    print_info(f"Sum of Partition Images:      {format_size(total_parts_size)}")

    if total_parts_size > device_size:
        print_error(f"Partitions total ({format_size(total_parts_size)}) exceeds Super device size ({format_size(device_size)})!")
        return False

    # Reserve 4MB for metadata copies
    group_size = device_size - (4 * 1024 * 1024)
    lpmake_tool = get_binary("lpmake")

    cmd = [
        lpmake_tool,
        f"--device-size={device_size}",
        "--metadata-size=65536",
        "--metadata-slots=2",
        f"-o={output_path}",
    ]

    if group_name and group_name.lower() != "default":
        cmd.append(f"--group={group_name}:{group_size}")

    for p in partitions:
        part_name = p["path"].stem
        part_size = p["size"]
        grp = group_name if (group_name and group_name.lower() != "default") else "default"
        cmd.append(f"--partition={part_name}:readonly:{part_size}:{grp}")
        cmd.append(f"--image={part_name}={p['path']}")

    if is_sparse:
        cmd.append("--sparse")
    if is_vab:
        cmd.append("--virtual-ab")

    print_info(f"Building Super Image with {len(partitions)} partition(s) via lpmake...")
    with Spinner("Generating logical super.img...") as sp:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if res.returncode != 0 or not output_path.exists():
        print_warning(f"lpmake exited with code {res.returncode}. Trying imgkit super pack fallback...")
        imgkit_tool = get_binary("imgkit")
        imgkit_cmd = [
            imgkit_tool,
            "pack",
            "--type", "super",
            "-o", str(output_path),
            "-d", str(device_size),
        ]
        if group_name and group_name.lower() != "default":
            imgkit_cmd.extend(["-g", f"{group_name}:{group_size}"])
        for p in partitions:
            part_name = p["path"].stem
            part_size = p["size"]
            grp = group_name if (group_name and group_name.lower() != "default") else "default"
            imgkit_cmd.extend(["-p", f"{part_name}:readonly:{part_size}:{grp}"])
            imgkit_cmd.extend(["-i", f"{part_name}={p['path']}"])
        if is_sparse:
            imgkit_cmd.append("-S")
        if is_vab:
            imgkit_cmd.append("--virtual-ab")

        with Spinner("Packing super image via imgkit..."):
            res = subprocess.run(imgkit_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if not output_path.exists() or output_path.stat().st_size == 0:
        print_error(f"Super image generation failed: {res.stderr or res.stdout}")
        return False

    print_success(f"Super image built successfully!")
    print_info(f"Output File: {Colors.BOLD}{output_path}{Colors.RESET}")
    print_info(f"File Size:   {format_size(output_path.stat().st_size)}")
    return True


def run_super_builder_menu():
    """Interactive CLI menu for Super Image Repacking."""
    print_section("Repack Dynamic Partitions into super.img")

    candidates = get_candidate_super_partitions()
    if not candidates:
        print_warning(f"No dynamic partition images found in {FINALIZED_DIR} or {IMAGES_DIR}.")
        print_info("Unpack and repack some partitions first.")
        return

    # Display available partitions
    headers = ["#", "Partition", "Source Folder", "Size"]
    rows = []
    total_bytes = 0
    for i, p in enumerate(candidates):
        src_color = Colors.GREEN if p["source"] == "finalized" else Colors.YELLOW
        rows.append([
            str(i + 1),
            p["path"].stem,
            f"{src_color}{p['source']}{Colors.RESET}",
            format_size(p["size"]),
        ])
        total_bytes += p["size"]
    print_table(headers, rows)
    print_info(f"Total partitions raw data: {format_size(total_bytes)}")

    # Prompt user for partition selection
    include_all = ask_confirm(f"Include all {len(candidates)} partitions in super.img?", default=True)
    if include_all:
        selected_parts = candidates
    else:
        indices_str = ask_text(f"Enter partition numbers to include (e.g. 1, 2, 3) [1-{len(candidates)}]")
        try:
            chosen = [int(x.strip()) - 1 for x in indices_str.split(",") if x.strip()]
            selected_parts = [candidates[i] for i in chosen if 0 <= i < len(candidates)]
        except Exception:
            print_error("Invalid selection.")
            return

    if not selected_parts:
        print_warning("No partitions selected.")
        return

    # Super Size Selection & Binary Calculations
    print_section("Super Partition Size Configuration (Binary Calculation)")
    print_info("Common device dynamic partition sizes:")
    print("  • 8.5 GB  = 9,126,805,504 bytes  (Qualcomm SM8635 / Xiaomi 14 Civi / POCO F6)")
    print("  • 9.0 GB  = 9,663,676,416 bytes")
    print("  • 9.5 GB  = 10,200,547,328 bytes")
    print("  • 10.0 GB = 10,737,418,240 bytes")

    size_presets = [
        "8.5 GB (9126805504 bytes - standard Qualcomm/Xiaomi)",
        "9.0 GB (9663676416 bytes)",
        "9.5 GB (10200547328 bytes)",
        "10.0 GB (10737418240 bytes)",
        f"Auto-fit ({format_size(total_bytes + (128*1024*1024))} based on contents)",
        "Custom size (e.g. 8.5G, 9G, 9126805504)",
    ]

    s_choice = ask_choice("Select Super Image Capacity:", size_presets, default_idx=0)
    device_size = 9126805504  # default 8.5GB
    if s_choice == 0:
        device_size = 9126805504
    elif s_choice == 1:
        device_size = 9663676416
    elif s_choice == 2:
        device_size = 10200547328
    elif s_choice == 3:
        device_size = 10737418240
    elif s_choice == 4:
        device_size = compute_super_size("auto", total_bytes)
    elif s_choice == 5:
        custom_input = ask_text("Enter size (e.g. 8.5GB, 9G, 9126805504)", default="8.5GB")
        try:
            device_size = compute_super_size(custom_input, total_bytes)
        except Exception as e:
            print_error(f"Invalid size format: {e}. Defaulting to 8.5 GB.")
            device_size = 9126805504

    # Group Name
    group_options = [
        "qti_dynamic_partitions (Qualcomm devices: Xiaomi, OnePlus, Motorola, etc.)",
        "main (AOSP / Generic devices)",
        "google_dynamic_partitions (Pixel devices)",
        "Custom group name...",
    ]
    g_choice = ask_choice("Select Dynamic Partition Group:", group_options, default_idx=0)
    if g_choice == 0:
        group_name = "qti_dynamic_partitions"
    elif g_choice == 1:
        group_name = "main"
    elif g_choice == 2:
        group_name = "google_dynamic_partitions"
    else:
        group_name = ask_text("Enter custom dynamic partition group name", default="qti_dynamic_partitions")

    # Image Format
    is_sparse = ask_confirm("Generate Sparse super.img? (Recommended for fastboot flash)", default=True)
    is_vab = ask_confirm("Enable Virtual A/B metadata flag?", default=True)

    # Build
    build_super_image(
        partitions=selected_parts,
        device_size=device_size,
        group_name=group_name,
        is_sparse=is_sparse,
        is_vab=is_vab,
    )
