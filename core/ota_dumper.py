#!/usr/bin/env python3
"""
Autoporter OTA Dumper Module:
Extracts payload.bin, OTA ROM Archives, and ROM.zip / Fastboot images
with granular partition selection and automated super.img unpacking.
"""

import os
import sys
import re
import zipfile
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Dict

from core.config import get_binary, IMAGES_DIR, INPUT_DIR, CAULDRON_DIR, format_size
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
from core.partition_unpacker import unpack_super_image, unpack_filesystem_image, unpack_boot_image, unpack_image


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
    raw images (ROM.zip/images/*.img), or is a standalone payload.bin / image.
    """
    info = {
        "path": archive_path,
        "type": "unknown",
        "size": archive_path.stat().st_size,
        "partitions": [],
        "image_entries": [],
        "has_super": False,
    }

    if archive_path.name.lower().endswith(".bin") or archive_path.name == "payload.bin":
        info["type"] = "payload"
        details = list_payload_partition_details(archive_path)
        info["partition_details"] = details
        info["partitions"] = [d["name"] for d in details]
        return info

    if archive_path.name.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                namelist = zf.namelist()
                if "payload.bin" in namelist or any(n.endswith("/payload.bin") for n in namelist):
                    info["type"] = "ota_zip_payload"
                    details = list_payload_partition_details(archive_path)
                    info["partition_details"] = details
                    info["partitions"] = [d["name"] for d in details]
                else:
                    # Scan for .img files anywhere inside the zip (e.g. images/*.img or root)
                    img_members = [
                        m for m in zf.infolist()
                        if not m.is_dir() and m.filename.lower().endswith(".img")
                    ]
                    if img_members:
                        info["type"] = "zip_images"
                        entries = []
                        partitions = []
                        has_super = False
                        for m in img_members:
                            p_stem = Path(m.filename).stem
                            partitions.append(p_stem)
                            if "super" in p_stem.lower():
                                has_super = True
                            entries.append({
                                "member": m,
                                "internal_path": m.filename,
                                "partition_name": p_stem,
                                "filename": Path(m.filename).name,
                                "file_size": m.file_size,
                                "compress_size": m.compress_size,
                            })
                        info["image_entries"] = sorted(entries, key=lambda x: x["partition_name"])
                        info["partitions"] = sorted(list(set(partitions)))
                        info["has_super"] = has_super
                    else:
                        info["type"] = "zip_generic"
        except Exception as e:
            info["error"] = str(e)
        return info

    if archive_path.name.lower().endswith(".img"):
        info["type"] = "raw_image"
        return info

    return info


def list_payload_partition_details(archive_or_bin: Path) -> List[Dict[str, str]]:
    """Uses payload-dumper-go to query partition names and sizes from payload."""
    tool = get_binary("payload-dumper-go")
    cmd = [tool, "-l", str(archive_or_bin)]
    details = []
    seen = set()
    ignore_tokens = {"payload.bin", "payload", "found", "partitions", "version", "manifest", "length", "signature"}
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
        match = re.search(r"Found partitions:\s*(.*)", res.stdout, re.IGNORECASE | re.DOTALL)
        if match:
            content = match.group(1)
            pairs = re.findall(r"([a-zA-Z0-9_\-]+)\s*(?:\(([^)]+)\))?", content)
            for name, sz in pairs:
                name_clean = name.strip()
                if name_clean and name_clean.lower() not in ignore_tokens and name_clean not in seen:
                    seen.add(name_clean)
                    details.append({"name": name_clean, "size": sz.strip() if sz else "-"})
        else:
            for line in res.stdout.splitlines():
                line = line.strip()
                if not line or line.lower().startswith(("payload", "version", "manifest", "found")):
                    continue
                for token in line.split(","):
                    p = token.split()[0].replace(":", "").strip()
                    if p and p.lower() not in ignore_tokens and p not in seen:
                        seen.add(p)
                        details.append({"name": p, "size": "-"})
    except Exception:
        pass
    return details


def list_payload_partitions(archive_or_bin: Path) -> List[str]:
    """Uses payload-dumper-go to query partition names from payload."""
    details = list_payload_partition_details(archive_or_bin)
    return [d["name"] for d in details]


def extract_payload(
    archive_or_bin: Path,
    selected_partitions: Optional[List[str]] = None,
    output_dir: Path = IMAGES_DIR,
) -> bool:
    """Extracts partitions using payload-dumper-go into output_dir."""
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
        for line in proc.stdout:
            line_s = line.strip()
            if "dumping" in line_s.lower() or "extracted" in line_s.lower():
                sp.update_message(f"Dumping: {line_s[:50]}")
        proc.wait()

    if proc.returncode != 0:
        print_error(f"Payload extraction exited with status {proc.returncode}")
        return False

    extracted_imgs = list(output_dir.glob("*.img"))
    print_success(f"Extracted {len(extracted_imgs)} partition image(s) to {output_dir}")
    return True


def extract_zip_selected_images(
    zip_path: Path,
    selected_entries: List[Dict[str, any]],
    output_dir: Path = IMAGES_DIR,
) -> List[Path]:
    """
    Extracts selected .img entries from a ROM zip archive into output_dir.
    Flattens any nested directory structure (e.g. images/super.img -> images/super.img).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    extracted_paths = []
    total = len(selected_entries)

    print_info(f"Extracting {total} partition image(s) from {Colors.BOLD}{zip_path.name}{Colors.RESET}...")

    with zipfile.ZipFile(zip_path, "r") as zf:
        for i, entry in enumerate(selected_entries):
            member = entry["member"]
            dest_filename = entry["filename"]
            target_file = output_dir / dest_filename
            p_name = entry["partition_name"]
            sz_str = format_size(entry["file_size"])

            progress_bar(i, total, prefix="Extracting", suffix=f"{p_name} ({sz_str})")

            with zf.open(member) as source, open(target_file, "wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)

            extracted_paths.append(target_file)

        progress_bar(total, total, prefix="Extracting", suffix="Completed!")

    print_success(f"Extracted {len(extracted_paths)} partition image(s) to {output_dir}")
    return extracted_paths


def handle_super_unpack_workflow(super_img_path: Path, output_dir: Path = IMAGES_DIR):
    """
    Guides the user through automatically unpacking super.img into its logical partitions
    and optionally unpacking them to 'cauldron' or deleting raw super.img to save disk space.
    """
    print_section("Super Image Unpack Assistant")
    print_info(f"Detected: {Colors.BOLD}{super_img_path.name}{Colors.RESET} ({format_size(super_img_path.stat().st_size)})")

    if not ask_confirm("Unpack super.img into its logical partitions (system, vendor, product, etc.)?", default=True):
        return

    unpacked_logical = unpack_super_image(super_img_path, output_dir=output_dir)
    if not unpacked_logical:
        print_warning("No logical partitions could be extracted from super.img.")
        return

    # Display extracted logical partitions
    headers = ["#", "Logical Partition", "Image File", "Size"]
    rows = []
    for idx, lp in enumerate(unpacked_logical):
        rows.append([str(idx + 1), lp.stem, lp.name, format_size(lp.stat().st_size)])
    print_table(headers, rows)

    # Option to unpack to cauldron/
    if ask_confirm(f"Unpack these {len(unpacked_logical)} logical partition(s) into 'cauldron/' now for editing?", default=True):
        print_info(f"Unpacking logical partitions to {CAULDRON_DIR}...")
        for lp in unpacked_logical:
            unpack_filesystem_image(lp, cauldron_dir=CAULDRON_DIR)
        print_success(f"All logical partitions are ready for modification in {CAULDRON_DIR}")

    # Option to delete raw super.img to save space
    if ask_confirm(f"Delete the large {super_img_path.name} to save disk space? ({format_size(super_img_path.stat().st_size)})", default=False):
        super_img_path.unlink(missing_ok=True)
        print_info(f"Removed {super_img_path.name} to conserve disk space.")


def run_ota_dumper_menu():
    """Interactive CLI menu for Unpacking OTA ROM / Payload / ROM.zip."""
    print_section("Unpack OTA ROM / Payload / ROM.zip")

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

    # Case 1: Payload / OTA ZIP with payload.bin
    if info["type"] in ["ota_zip_payload", "payload"]:
        partitions = info["partitions"]
        details = info.get("partition_details", [])
        if partitions:
            print_info(f"Found {len(partitions)} partitions in payload.")
            if details:
                p_headers = ["#", "Partition Name", "Size"]
                p_rows = [[str(i + 1), d["name"], d["size"]] for i, d in enumerate(details)]
            else:
                p_headers = ["#", "Partition Name"]
                p_rows = [[str(i + 1), p] for i, p in enumerate(partitions)]
            print_table(p_headers, p_rows)

            sub_opts = [
                "Dump ALL partitions (full dump)",
                "Dump core dynamic + boot partitions (system, vendor, product, system_ext, odm, boot, vendor_boot)",
                "Select custom partitions or ranges (e.g. 1-15, 18-20 or names)",
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
                sel_str = ask_text(f"Enter partition numbers/ranges (e.g. 1-15, 18-20) or names (e.g. boot, super) [1-{len(partitions)}]")
                indices = parse_range_selection(sel_str, len(partitions), partitions)
                chosen = [partitions[i] for i in indices]
                if chosen:
                    extract_payload(target_path, chosen, IMAGES_DIR)
                else:
                    print_warning("No valid partitions selected.")
            else:
                return
        else:
            extract_payload(target_path, None, IMAGES_DIR)

    # Case 2: ROM.zip with images/ (Fastboot ROM / Image ZIP)
    elif info["type"] == "zip_images":
        entries = info["image_entries"]
        has_super = info["has_super"]
        print_info(f"Found {len(entries)} partition image(s) inside {target_path.name}")

        # Show partitions table
        headers = ["#", "Partition", "Internal Path", "Uncompressed Size", "Compressed Size"]
        rows = []
        for i, entry in enumerate(entries):
            p_color = Colors.BRIGHT_GREEN if "super" in entry["partition_name"].lower() else (
                Colors.CYAN if any(b in entry["partition_name"].lower() for b in ["boot", "kernel"]) else ""
            )
            rows.append([
                str(i + 1),
                f"{p_color}{entry['partition_name']}{Colors.RESET}",
                entry["internal_path"],
                format_size(entry["file_size"]),
                format_size(entry["compress_size"]),
            ])
        print_table(headers, rows)

        # Menu options
        menu_opts = [f"Extract ALL ({len(entries)} partitions)"]
        if has_super:
            menu_opts.append("Extract super.img AND automatically unpack its logical partitions (system, vendor...)")
        menu_opts.extend([
            "Extract core partitions (boot, vendor_boot, init_boot, super, vbmeta, dtbo)",
            "Select custom partitions or ranges (e.g. 1-15, 18-20 or names)",
            "Cancel",
        ])

        choice = ask_choice("Choose extraction mode:", menu_opts, default_idx=0)
        selected_to_extract = []
        auto_unpack_super = False

        if choice == 0:
            selected_to_extract = entries
        elif has_super and choice == 1:
            # Extract super.img + boot images
            selected_to_extract = [e for e in entries if "super" in e["partition_name"].lower()]
            auto_unpack_super = True
        elif (has_super and choice == 2) or (not has_super and choice == 1):
            core_keywords = ["boot", "vendor_boot", "init_boot", "super", "vbmeta", "dtbo", "recovery"]
            selected_to_extract = [e for e in entries if any(k in e["partition_name"].lower() for k in core_keywords)]
        elif (has_super and choice == 3) or (not has_super and choice == 2):
            selection_input = ask_text(f"Enter partition numbers/ranges (e.g. 1-15, 18-20) or names (e.g. boot, super) [1-{len(entries)}]")
            if not selection_input:
                return
            indices = parse_range_selection(selection_input, len(entries), [e["partition_name"] for e in entries])
            selected_to_extract = [entries[i] for i in indices]
        else:
            return

        if not selected_to_extract:
            print_warning("No partitions selected for extraction.")
            return

        # Perform extraction
        extracted_paths = extract_zip_selected_images(target_path, selected_to_extract, IMAGES_DIR)

        # Check for super.img in extracted images
        super_path = IMAGES_DIR / "super.img"
        if not super_path.exists():
            # Check if any extracted path has 'super' in stem
            for p in extracted_paths:
                if "super" in p.stem.lower():
                    super_path = p
                    break

        if super_path.exists():
            if auto_unpack_super:
                handle_super_unpack_workflow(super_path, IMAGES_DIR)
            else:
                handle_super_unpack_workflow(super_path, IMAGES_DIR)
        else:
            # Prompt to unpack other extracted images to cauldron
            if ask_confirm(f"Unpack {len(extracted_paths)} extracted image(s) to 'cauldron/' now?", default=False):
                for p in extracted_paths:
                    unpack_image(p)

    # Case 3: Raw image file
    elif info["type"] == "raw_image":
        dest = IMAGES_DIR / target_path.name
        if target_path.resolve() != dest.resolve():
            print_info(f"Copying {target_path.name} to images/ directory...")
            shutil.copy2(target_path, dest)
            print_success(f"Copied {target_path.name} to {IMAGES_DIR}")
        else:
            print_info(f"Image {target_path.name} is already in {IMAGES_DIR}")

        if "super" in target_path.stem.lower():
            handle_super_unpack_workflow(dest, IMAGES_DIR)

    else:
        print_warning(f"Unrecognized archive type for {target_path.name}")
