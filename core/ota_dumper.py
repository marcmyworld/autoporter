#!/usr/bin/env python3
"""
Autoporter OTA Dumper Module: Extracts payload.bin & OTA ROM Archives
"""

import os
import sys
import zipfile
import subprocess
from pathlib import Path
from typing import List, Optional, Dict

from core.config import get_binary, IMAGES_DIR, INPUT_DIR, format_size
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


def find_rom_archives() -> List[Path]:
    """Finds all potential ROM archives in the input/ folder and parent directory."""
    archives = []
    scan_dirs = [INPUT_DIR, Path.cwd()]
    for s_dir in scan_dirs:
        if not s_dir.exists():
            continue
        for ext in ["*.zip", "*.bin", "*.img"]:
            for file_path in s_dir.glob(ext):
                if file_path.is_file() and file_path not in archives:
                    archives.append(file_path)
    return sorted(archives, key=lambda p: p.stat().st_mtime, reverse=True)


def inspect_archive(archive_path: Path) -> Dict[str, any]:
    """
    Inspects an archive to determine whether it contains payload.bin,
    raw images, or is a standalone payload.bin / image.
    """
    info = {
        "path": archive_path,
        "type": "unknown",
        "size": archive_path.stat().st_size,
        "partitions": [],
        "img_files": [],
    }

    if archive_path.name.lower().endswith(".bin") or archive_path.name == "payload.bin":
        info["type"] = "payload"
        info["partitions"] = list_payload_partitions(archive_path)
        return info

    if archive_path.name.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                namelist = zf.namelist()
                if "payload.bin" in namelist or any(n.endswith("/payload.bin") for n in namelist):
                    info["type"] = "ota_zip_payload"
                    info["partitions"] = list_payload_partitions(archive_path)
                else:
                    imgs = [n for n in namelist if n.lower().endswith(".img")]
                    if imgs:
                        info["type"] = "zip_images"
                        info["img_files"] = imgs
                    else:
                        info["type"] = "zip_generic"
        except Exception as e:
            info["error"] = str(e)
        return info

    if archive_path.name.lower().endswith(".img"):
        info["type"] = "raw_image"
        return info

    return info


def list_payload_partitions(archive_or_bin: Path) -> List[str]:
    """Uses payload-dumper-go to query partition names from payload."""
    tool = get_binary("payload-dumper-go")
    cmd = [tool, "-l", str(archive_or_bin)]
    partitions = []
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
        for line in res.stdout.splitlines():
            line = line.strip()
            # typical format: "boot (128 MB)" or "system"
            if line and not line.startswith("Payload") and not line.startswith("Version"):
                part_name = line.split()[0].replace(":", "")
                if part_name and part_name not in partitions:
                    partitions.append(part_name)
    except Exception:
        pass
    return partitions


def extract_payload(
    archive_or_bin: Path,
    selected_partitions: Optional[List[str]] = None,
    output_dir: Path = IMAGES_DIR,
) -> bool:
    """
    Extracts partitions using payload-dumper-go into output_dir.
    """
    tool = get_binary("payload-dumper-go")
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [tool, "-o", str(output_dir), "-c", "8"]
    if selected_partitions:
        cmd.extend(["-p", ",".join(selected_partitions)])
    cmd.append(str(archive_or_bin))

    print_info(f"Target archive: {Colors.BOLD}{archive_or_bin.name}{Colors.RESET} ({format_size(archive_or_bin.stat().st_size)})")
    print_info(f"Output folder:  {output_dir}")
    if selected_partitions:
        print_info(f"Extracting partitions: {', '.join(selected_partitions)}")
    else:
        print_info("Extracting ALL partitions from payload")

    with Spinner("Extracting payload partitions via payload-dumper-go...") as sp:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        extracted = []
        for line in proc.stdout:
            line_s = line.strip()
            if "dumping" in line_s.lower() or "extracted" in line_s.lower():
                sp.update_message(f"Dumping: {line_s[:50]}")
            if ".img" in line_s:
                extracted.append(line_s)
        proc.wait()

    if proc.returncode != 0:
        print_error(f"Payload extraction exited with status {proc.returncode}")
        return False

    # Check extracted images
    extracted_imgs = list(output_dir.glob("*.img"))
    print_success(f"Extracted {len(extracted_imgs)} partition image(s) to {output_dir}")
    return True


def extract_zip_raw_images(zip_path: Path, output_dir: Path = IMAGES_DIR) -> bool:
    """Extracts raw .img files found in a generic or fastboot zip."""
    output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        img_members = [m for m in zf.infolist() if m.filename.lower().endswith(".img")]
        total = len(img_members)
        if total == 0:
            print_warning("No .img files found in the archive.")
            return False

        print_info(f"Extracting {total} image(s) from {zip_path.name}...")
        for i, member in enumerate(img_members):
            dest_name = Path(member.filename).name
            progress_bar(i + 1, total, prefix="Extracting", suffix=dest_name)
            with zf.open(member) as source, open(output_dir / dest_name, "wb") as target:
                shutil.copyfileobj(source, target)
        print()
    print_success(f"Extracted {total} image(s) to {output_dir}")
    return True


def run_ota_dumper_menu():
    """Interactive CLI menu for Unpacking OTA ROM / Payload."""
    print_section("Unpack OTA ROM / Payload Dumper")

    archives = find_rom_archives()
    if not archives:
        print_warning(f"No ROM archives or .img files found in {INPUT_DIR} or current directory.")
        custom = ask_text("Enter full path to OTA ZIP, payload.bin, or image file (or Enter to cancel)")
        if not custom or not Path(custom).exists():
            return
        target_path = Path(custom).resolve()
    else:
        options = [f"{a.name} ({format_size(a.stat().st_size)}) - [{a.parent.name}]" for a in archives]
        options.append("Specify custom path manually...")
        options.append("Back to main menu")

        choice = ask_choice("Select ROM file to unpack:", options, default_idx=0)
        if choice == len(options) - 1:
            return
        elif choice == len(options) - 2:
            custom = ask_text("Enter path to file")
            if not custom or not Path(custom).exists():
                print_error("File does not exist.")
                return
            target_path = Path(custom).resolve()
        else:
            target_path = archives[choice]

    # Inspect the selected target
    info = inspect_archive(target_path)
    print_info(f"File Type Detected: {Colors.BRIGHT_CYAN}{info['type']}{Colors.RESET}")

    if info["type"] in ["ota_zip_payload", "payload"]:
        partitions = info["partitions"]
        if partitions:
            print_info(f"Found {len(partitions)} partitions: {', '.join(partitions[:10])}{'...' if len(partitions) > 10 else ''}")
            sub_opts = [
                "Dump ALL partitions (full dump)",
                "Dump core dynamic + boot partitions (system, vendor, product, system_ext, odm, boot, vendor_boot)",
                "Select custom partitions to dump",
                "Cancel",
            ]
            sub_choice = ask_choice("Choose dump mode:", sub_opts, default_idx=0)
            if sub_choice == 0:
                extract_payload(target_path, None, IMAGES_DIR)
            elif sub_choice == 1:
                core_names = ["system", "vendor", "product", "system_ext", "odm", "mi_ext", "boot", "vendor_boot", "init_boot"]
                selected = [p for p in partitions if p in core_names]
                extract_payload(target_path, selected, IMAGES_DIR)
            elif sub_choice == 2:
                names = ask_text("Enter comma-separated partition names (e.g. system,vendor,boot)")
                chosen = [n.strip() for n in names.split(",") if n.strip()]
                if chosen:
                    extract_payload(target_path, chosen, IMAGES_DIR)
                else:
                    print_warning("No partitions specified.")
            else:
                return
        else:
            # list failed or couldn't parse, do full dump
            extract_payload(target_path, None, IMAGES_DIR)

    elif info["type"] == "zip_images":
        print_info(f"Zip contains {len(info['img_files'])} .img file(s).")
        if ask_confirm("Extract all .img files to images/ directory?"):
            extract_zip_raw_images(target_path, IMAGES_DIR)

    elif info["type"] == "raw_image":
        dest = IMAGES_DIR / target_path.name
        if target_path.resolve() != dest.resolve():
            print_info(f"Copying {target_path.name} to images/ directory...")
            shutil.copy2(target_path, dest)
            print_success(f"Copied {target_path.name} to {IMAGES_DIR}")
        else:
            print_info(f"Image {target_path.name} is already in {IMAGES_DIR}")

    else:
        print_warning(f"Unrecognized archive type for {target_path.name}")
