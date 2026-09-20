#!/usr/bin/env python3
"""
Autoporter - Android ROM Kitchen & Partition Transmutation Engine
Direct execution entry point: ./autoport.py
"""

import os
import sys
import argparse
from pathlib import Path

# Add project root to sys.path
PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from core.ui import (
    Colors,
    banner,
    clear_screen,
    print_info,
    print_success,
    print_warning,
    print_error,
    print_section,
    ask_choice,
    ask_text,
    ask_confirm,
)
from core.workspace import (
    display_workspace_status,
    inspect_build_prop,
    clean_workspace_menu,
)
from core.ota_dumper import run_ota_dumper_menu
from core.partition_unpacker import run_partition_unpacker_menu
from core.partition_repacker import run_partition_repacker_menu
from core.super_builder import run_super_builder_menu
from core.ota_builder import run_ota_builder_menu
from core.context_sync import sync_partition_contexts
from core.config import CAULDRON_DIR, FINALIZED_DIR, IMAGES_DIR, OUTPUT_DIR


def run_context_sync_menu():
    """Manual context synchronization tool."""
    print_section("Synchronize SELinux Contexts & Permissions")
    unpacked_dirs = [d for d in CAULDRON_DIR.iterdir() if d.is_dir() and d.name not in ["config", ".meta", "unpacked_super"]] if CAULDRON_DIR.exists() else []
    if not unpacked_dirs:
        print_warning("No unpacked partitions found in cauldron/.")
        return

    config_dir = CAULDRON_DIR / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    for p in unpacked_dirs:
        added_fs, added_ctx = sync_partition_contexts(p.name, p, config_dir)
        print_info(f"Partition '{p.name}': +{added_fs} permissions (fs_config), +{added_ctx} SELinux labels (file_contexts)")
    print_success("Context synchronization complete across all active partitions.")


def main_menu():
    """Main interactive loop."""
    while True:
        banner()
        display_workspace_status()

        menu_options = [
            f"{Colors.BOLD}Unpack OTA ROM / Payload{Colors.RESET} (payload-dumper-go / OTA zips)",
            f"{Colors.BOLD}Unpack Images to 'cauldron'{Colors.RESET} (Super, EROFS, EXT4, Boot, Kernel)",
            f"{Colors.BOLD}Synchronize Permissions & SELinux Contexts{Colors.RESET} (fs_config & file_contexts)",
            f"{Colors.BOLD}Repack Modified Partitions{Colors.RESET} (Customize EROFS/EXT4 compression & levels)",
            f"{Colors.BOLD}Repack into super.img{Colors.RESET} (Binary size computation, groups, sparse/raw)",
            f"{Colors.BOLD}Repack into Flashable OTA / ROM{Colors.RESET} (Recovery ZIP, Fastboot ROM, Payload OTA)",
            f"{Colors.BOLD}Android build.prop Inspector{Colors.RESET} (View OS version, model, codename)",
            f"{Colors.BOLD}Workspace Cleanup Manager{Colors.RESET} (Purge temp directories, reset kitchen)",
            f"{Colors.RED}Exit Autoporter{Colors.RESET}",
        ]

        choice = ask_choice("Main Menu Actions:", menu_options, default_idx=0)

        if choice == 0:
            run_ota_dumper_menu()
        elif choice == 1:
            run_partition_unpacker_menu()
        elif choice == 2:
            run_context_sync_menu()
        elif choice == 3:
            run_partition_repacker_menu()
        elif choice == 4:
            run_super_builder_menu()
        elif choice == 5:
            run_ota_builder_menu()
        elif choice == 6:
            inspect_build_prop()
        elif choice == 7:
            clean_workspace_menu()
        elif choice == 8:
            print(f"\n {Colors.BRIGHT_CYAN}Thank you for using Autoporter. Happy ROM cooking!{Colors.RESET}\n")
            sys.exit(0)

        input(f"\n {Colors.DIM}Press Enter to return to main menu...{Colors.RESET}")
        clear_screen()


def parse_args():
    """Handles CLI arguments for non-interactive or scripted execution."""
    parser = argparse.ArgumentParser(
        description="Autoporter - Android ROM Kitchen & Partition Transmutation Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # unpack-ota
    p_ota = subparsers.add_parser("unpack-ota", help="Unpack an OTA zip, payload.bin, or ROM.zip with images/")
    p_ota.add_argument("archive", type=str, help="Path to OTA ZIP, payload.bin, or ROM.zip")
    p_ota.add_argument("-p", "--partitions", type=str, default="", help="Comma-separated partition names (e.g. boot,super)")
    p_ota.add_argument("--unpack-super", action="store_true", help="Automatically unpack super.img into logical partitions")
    p_ota.add_argument("--to-cauldron", action="store_true", help="Unpack extracted partitions directly into cauldron/")

    # unpack-image
    p_img = subparsers.add_parser("unpack-image", help="Unpack partition image into cauldron")
    p_img.add_argument("image", type=str, help="Path to .img file")

    # super
    p_super = subparsers.add_parser("build-super", help="Build super.img")
    p_super.add_argument("--size", type=str, default="8.5GB", help="Super size (e.g. 8.5GB, 9G, 9126805504)")
    p_super.add_argument("--group", type=str, default="qti_dynamic_partitions", help="Partition group name")

    # status
    subparsers.add_parser("status", help="Show workspace overview")

    return parser.parse_args()


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1:
            args = parse_args()
            if args.command == "status":
                banner()
                display_workspace_status()
            elif args.command == "unpack-ota":
                from core.ota_dumper import inspect_archive, extract_payload, extract_zip_selected_images, handle_super_unpack_workflow
                from core.partition_unpacker import unpack_image
                from core.ui import parse_range_selection
                archive_path = Path(args.archive).resolve()
                info = inspect_archive(archive_path)

                if info["type"] in ["ota_zip_payload", "payload"]:
                    if args.partitions:
                        indices = parse_range_selection(args.partitions, len(info["partitions"]), info["partitions"])
                        selected_parts = [info["partitions"][i] for i in indices]
                    else:
                        selected_parts = None
                    extract_payload(archive_path, selected_partitions=selected_parts)
                elif info["type"] == "zip_images":
                    entries = info["image_entries"]
                    if args.partitions:
                        indices = parse_range_selection(args.partitions, len(entries), [e["partition_name"] for e in entries])
                        chosen_entries = [entries[i] for i in indices]
                    else:
                        chosen_entries = entries
                    extracted = extract_zip_selected_images(archive_path, chosen_entries, IMAGES_DIR)

                    super_path = IMAGES_DIR / "super.img"
                    if (args.unpack_super or (selected_parts and "super" in [p.lower() for p in selected_parts])) and super_path.exists():
                        handle_super_unpack_workflow(super_path, IMAGES_DIR)

                    if args.to_cauldron:
                        for p in extracted:
                            if p.exists() and p.stem != "super":
                                unpack_image(p)
                else:
                    print_warning(f"Unrecognized archive type: {info['type']}")
            elif args.command == "unpack-image":
                from core.partition_unpacker import unpack_image
                unpack_image(Path(args.image).resolve())
            elif args.command == "build-super":
                from core.super_builder import get_candidate_super_partitions, compute_super_size, build_super_image
                parts = get_candidate_super_partitions()
                total_sz = sum(p["size"] for p in parts)
                dev_sz = compute_super_size(args.size, total_sz)
                build_super_image(parts, device_size=dev_sz, group_name=args.group)
        else:
            main_menu()
    except KeyboardInterrupt:
        print(f"\n\n {Colors.BRIGHT_YELLOW}Operation aborted by user.{Colors.RESET}\n")
        sys.exit(130)
