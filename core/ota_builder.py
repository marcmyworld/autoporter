#!/usr/bin/env python3
"""
Autoporter OTA ROM Builder Module:
Builds flashable packages from finalized partitions:
  1. Payload-based OTA ZIP (using delta_generator)
  2. Recovery Flashable ZIP (TWRP / OrangeFox compatible updater-script)
  3. Fastboot Flashable ROM package (with flash_all.sh & flash_all.bat)
"""

import os
import sys
import time
import zipfile
import shutil
import hashlib
import subprocess
from pathlib import Path
from typing import List, Dict, Optional

from core.config import (
    get_binary,
    FINALIZED_DIR,
    IMAGES_DIR,
    OUTPUT_DIR,
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


def get_available_partitions_for_rom() -> List[Dict[str, any]]:
    """Gathers all available finalized partition images, falling back to images/."""
    partitions = {}

    if FINALIZED_DIR.exists():
        for p in FINALIZED_DIR.glob("*.img"):
            partitions[p.stem] = {"path": p, "source": "finalized", "size": p.stat().st_size}

    if IMAGES_DIR.exists():
        for p in IMAGES_DIR.glob("*.img"):
            if p.stem not in partitions and p.stem != "super":
                partitions[p.stem] = {"path": p, "source": "images", "size": p.stat().st_size}

    return sorted(partitions.values(), key=lambda x: x["path"].stem)


def compute_sha256(file_path: Path) -> str:
    """Calculates SHA256 checksum of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def build_payload_ota_zip(partitions: List[Dict[str, any]], zip_name: str = "ota_update.zip") -> Optional[Path]:
    """Generates an official payload.bin using delta_generator and packages it into an OTA zip."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_zip_path = OUTPUT_DIR / zip_name
    temp_dir = OUTPUT_DIR / f"temp_ota_{int(time.time())}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    delta_tool = get_binary("delta_generator")
    payload_bin = temp_dir / "payload.bin"

    part_names = ":".join(p["path"].stem for p in partitions)
    part_paths = ":".join(str(p["path"]) for p in partitions)

    cmd = [
        delta_tool,
        "--major_version=2",
        f"--partition_names={part_names}",
        f"--new_partitions={part_paths}",
        f"--out_file={payload_bin}",
    ]

    print_info(f"Generating payload.bin with {len(partitions)} partition(s)...")
    with Spinner("Generating payload via delta_generator...") as sp:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if res.returncode != 0 or not payload_bin.exists():
        print_error(f"delta_generator failed: {res.stderr}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None

    # Write payload_properties.txt
    payload_size = payload_bin.stat().st_size
    payload_hash = compute_sha256(payload_bin)
    props = (
        f"FILE_HASH={payload_hash}\n"
        f"FILE_SIZE={payload_size}\n"
        f"METADATA_HASH={payload_hash}\n"
        f"METADATA_SIZE={payload_size}\n"
    )
    with open(temp_dir / "payload_properties.txt", "w") as f:
        f.write(props)

    # Package into OTA zip
    print_info(f"Packaging into {out_zip_path.name}...")
    with zipfile.ZipFile(out_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(payload_bin, "payload.bin")
        zf.write(temp_dir / "payload_properties.txt", "payload_properties.txt")

    shutil.rmtree(temp_dir, ignore_errors=True)
    print_success(f"Payload OTA ZIP created: {out_zip_path} ({format_size(out_zip_path.stat().st_size)})")
    return out_zip_path


def build_recovery_flashable_zip(partitions: List[Dict[str, any]], zip_name: str = "flashable_rom.zip") -> Optional[Path]:
    """
    Creates a recovery flashable zip with update-binary shell installer,
    compatible with TWRP, OrangeFox, and standard AOSP recoveries.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_zip_path = OUTPUT_DIR / zip_name
    temp_dir = OUTPUT_DIR / f"temp_rec_{int(time.time())}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    meta_inf = temp_dir / "META-INF" / "com" / "google" / "android"
    meta_inf.mkdir(parents=True, exist_ok=True)

    # Build updater-script (dummy comment for Android installer)
    with open(meta_inf / "updater-script", "w") as f:
        f.write("# Autoporter Recovery Flashable Package\n")

    # Build robust update-binary shell installer script
    updater_sh = """#!/sbin/sh
# Autoporter Recovery Flash Script
OUTFD=$2
ui_print() {
  if [ -n "$OUTFD" ]; then
    echo "ui_print $1" > /proc/self/fd/$OUTFD
    echo "ui_print" > /proc/self/fd/$OUTFD
  else
    echo "$1"
  fi
}

ui_print "=========================================="
ui_print "       Autoporter ROM Installer           "
ui_print "=========================================="

SLOT=$(getprop ro.boot.slot_suffix 2>/dev/null)
if [ -z "$SLOT" ]; then
  SLOT=$(grep -o 'androidboot.slot_suffix=[^ ]*' /proc/cmdline | cut -d= -f2)
fi
if [ -n "$SLOT" ]; then
  ui_print "Target Slot: $SLOT"
fi

ZIP="$3"
DIR="/tmp/autoporter_install"
mkdir -p "$DIR"

"""

    for p in partitions:
        part_name = p["path"].stem
        updater_sh += f"""
ui_print "Flashing partition: {part_name}..."
BLOCK_DEV=""
for path in /dev/block/bootdevice/by-name/{part_name}$SLOT /dev/block/mapper/{part_name}$SLOT /dev/block/by-name/{part_name} /dev/block/mapper/{part_name}; do
  if [ -b "$path" ]; then
    BLOCK_DEV="$path"
    break
  fi
done

if [ -n "$BLOCK_DEV" ]; then
  unzip -p "$ZIP" "images/{part_name}.img" > "$BLOCK_DEV"
  ui_print "  -> Successfully flashed {part_name} to $BLOCK_DEV"
else
  ui_print "  [!] Block device for {part_name} not found, skipping."
fi
"""

    updater_sh += """
ui_print "=========================================="
ui_print "    Flashing complete! Rebooting...       "
ui_print "=========================================="
exit 0
"""

    update_bin_path = meta_inf / "update-binary"
    with open(update_bin_path, "w", newline="\n") as f:
        f.write(updater_sh)
    os.chmod(update_bin_path, 0o755)

    # Package files into ZIP
    print_info(f"Packaging {len(partitions)} partition(s) into Recovery ZIP...")
    with zipfile.ZipFile(out_zip_path, "w", zipfile.ZIP_STORED) as zf:
        zf.write(update_bin_path, "META-INF/com/google/android/update-binary")
        zf.write(meta_inf / "updater-script", "META-INF/com/google/android/updater-script")
        for i, p in enumerate(partitions):
            part_name = p["path"].name
            progress_bar(i + 1, len(partitions), prefix="Archiving", suffix=part_name)
            zf.write(p["path"], f"images/{part_name}")

    shutil.rmtree(temp_dir, ignore_errors=True)
    print_success(f"Recovery flashable ZIP created: {out_zip_path} ({format_size(out_zip_path.stat().st_size)})")
    return out_zip_path


def build_fastboot_rom_package(partitions: List[Dict[str, any]], rom_name: str = "Autoporter-Fastboot-ROM") -> Path:
    """
    Creates a fastboot-flashable ROM folder and archive with flash_all.sh & flash_all.bat scripts.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pkg_dir = OUTPUT_DIR / f"{rom_name}_{int(time.time())}"
    images_dir = pkg_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    # Check if super.img exists in output/ or finalized/
    super_img = OUTPUT_DIR / "super.img"
    has_super = super_img.is_file()

    print_info(f"Preparing Fastboot ROM package at {pkg_dir}...")
    for p in partitions:
        shutil.copy2(p["path"], images_dir / p["path"].name)

    if has_super:
        shutil.copy2(super_img, images_dir / "super.img")

    # Generate flash_all.sh (Linux/macOS)
    flash_sh = """#!/bin/bash
set -e
echo "===================================================="
echo "          Autoporter Fastboot ROM Flasher           "
echo "===================================================="

fastboot devices | grep fastboot || (echo "No fastboot device detected. Exiting."; exit 1)

echo "Detecting current slot..."
CURRENT_SLOT=$(fastboot getvar current-slot 2>&1 | grep "current-slot:" | awk '{print $2}')
echo "Active slot: ${CURRENT_SLOT}"

echo "Flashing boot and core partitions..."
"""
    for p in partitions:
        name = p["path"].stem
        if name != "super":
            flash_sh += f"[ -f images/{name}.img ] && fastboot flash {name} images/{name}.img\n"

    if has_super:
        flash_sh += """
echo "Flashing logical super.img..."
fastboot flash super images/super.img
"""

    flash_sh += """
echo "Wiping userdata and cache..."
fastboot erase userdata || true
fastboot erase metadata || true

echo "Rebooting device to system..."
fastboot reboot
echo "Flashing complete!"
"""

    with open(pkg_dir / "flash_all.sh", "w", newline="\n") as f:
        f.write(flash_sh)
    os.chmod(pkg_dir / "flash_all.sh", 0o755)

    # Generate flash_all.bat (Windows)
    flash_bat = """@echo off
echo ====================================================
echo           Autoporter Fastboot ROM Flasher           
echo ====================================================

fastboot devices
echo Flashing boot and core partitions...
"""
    for p in partitions:
        name = p["path"].stem
        if name != "super":
            flash_bat += f"if exist images\\{name}.img fastboot flash {name} images\\{name}.img\n"

    if has_super:
        flash_bat += """
echo Flashing super.img...
if exist images\\super.img fastboot flash super images\\super.img
"""

    flash_bat += """
echo Wiping userdata...
fastboot erase userdata
fastboot erase metadata
echo Rebooting...
fastboot reboot
pause
"""
    with open(pkg_dir / "flash_all.bat", "w", newline="\r\n") as f:
        f.write(flash_bat)

    print_success(f"Fastboot ROM package assembled in: {pkg_dir}")
    return pkg_dir


def run_ota_builder_menu():
    """Interactive CLI menu for OTA ROM / Flashable Package Creation."""
    print_section("Repack Partitions into Flashable OTA / ROM")

    available = get_available_partitions_for_rom()
    if not available:
        print_warning(f"No partition images found in {FINALIZED_DIR} or {IMAGES_DIR}.")
        print_info("Unpack and repack partitions first.")
        return

    headers = ["#", "Partition", "Source Folder", "Size"]
    rows = []
    for i, p in enumerate(available):
        src_color = Colors.GREEN if p["source"] == "finalized" else Colors.YELLOW
        rows.append([
            str(i + 1),
            p["path"].stem,
            f"{src_color}{p['source']}{Colors.RESET}",
            format_size(p["size"]),
        ])
    print_table(headers, rows)

    # Allow custom partition selection
    if not ask_confirm(f"Include all {len(available)} available partitions in ROM package?", default=True):
        sel_str = ask_text(f"Enter partition numbers/ranges to include (e.g. 1-15, 18-20, or names) [1-{len(available)}]")
        if not sel_str:
            return
        indices = parse_range_selection(sel_str, len(available), [p["path"].stem for p in available])
        if not indices:
            print_warning("No valid partitions selected.")
            return
        target_partitions = [available[i] for i in indices]
    else:
        target_partitions = available

    options = [
        "Recovery Flashable ZIP (TWRP / OrangeFox / Sideload installer)",
        "Fastboot Flashable ROM Package (with flash_all.sh and flash_all.bat)",
        "Official Payload OTA ZIP (payload.bin generated via delta_generator)",
        "Cancel",
    ]
    choice = ask_choice("Select ROM distribution format:", options, default_idx=0)

    if choice == 0:
        fname = ask_text("Enter ZIP filename", default="Autoporter-Recovery-ROM.zip")
        build_recovery_flashable_zip(target_partitions, zip_name=fname)
    elif choice == 1:
        pname = ask_text("Enter Fastboot ROM folder name", default="Autoporter-Fastboot-ROM")
        build_fastboot_rom_package(target_partitions, rom_name=pname)
    elif choice == 2:
        fname = ask_text("Enter Payload OTA ZIP filename", default="Autoporter-Payload-OTA.zip")
        build_payload_ota_zip(target_partitions, zip_name=fname)
    else:
        return
