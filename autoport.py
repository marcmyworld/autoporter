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
    print_motd,
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
from core.project import (
    Project,
    ProjectManager,
    get_active_project,
    display_projects_table,
    select_project_dialog,
    create_project_dialog,
    delete_project_dialog,
    edit_project_dialog,
    run_project_manager_menu,
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


def pause():
    input(f"\n {Colors.DIM}Press Enter to return...{Colors.RESET}")


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


def menu_unpack_extract():
    """Category 1: Unpack & Extract sub-menu."""
    while True:
        clear_screen()
        print_section("Unpack & Extract")
        options = [
            "Unpack OTA ROM / Payload (OTA zips, payload.bin, ROM.zip)",
            "Unpack Image to Cauldron (Super, EROFS, EXT4, Boot, Kernel)",
            "Back to Project Menu",
        ]
        choice = ask_choice("Choose Action:", options, default_idx=0)
        if choice == 0:
            run_ota_dumper_menu()
            pause()
        elif choice == 1:
            run_partition_unpacker_menu()
            pause()
        else:
            break


def menu_contexts_inspection():
    """Category 2: Contexts & Inspection sub-menu."""
    while True:
        clear_screen()
        print_section("Contexts & Inspection")
        options = [
            "Sync Permissions & SELinux Contexts (fs_config & file_contexts)",
            "Inspect build.prop Properties (OS version, device, codename)",
            "Back to Project Menu",
        ]
        choice = ask_choice("Choose Action:", options, default_idx=0)
        if choice == 0:
            run_context_sync_menu()
            pause()
        elif choice == 1:
            inspect_build_prop()
            pause()
        else:
            break


def menu_repack_build():
    """Category 3: Repack & Build sub-menu."""
    while True:
        clear_screen()
        print_section("Repack & Build")
        options = [
            "Repack Modified Partitions (EROFS, EXT4, Boot image)",
            "Repack into super.img (Binary sizing, dynamic groups)",
            "Build Flashable Package (Recovery ZIP, Fastboot ROM, Payload OTA)",
            "Back to Project Menu",
        ]
        choice = ask_choice("Choose Action:", options, default_idx=0)
        if choice == 0:
            run_partition_repacker_menu()
            pause()
        elif choice == 1:
            run_super_builder_menu()
            pause()
        elif choice == 2:
            run_ota_builder_menu()
            pause()
        else:
            break


def menu_workspace_tools(project: Project):
    """Category 4: Workspace & Tools sub-menu."""
    while True:
        clear_screen()
        print_section(f"Workspace Tools [{project.name}]")
        options = [
            "Clean Working Directories (cauldron, finalized, output, images)",
            "Edit Project Details (Display name, device, Android version)",
            "Back to Project Menu",
        ]
        choice = ask_choice("Choose Action:", options, default_idx=0)
        if choice == 0:
            clean_workspace_menu()
            pause()
        elif choice == 1:
            edit_project_dialog(project)
            pause()
        else:
            break


def run_project_homepage(project: Project):
    """Project-specific homepage: displays status & categorized actions."""
    ProjectManager.set_active_project(project)
    while True:
        clear_screen()
        meta = project.get_meta()
        disp_name = meta.get("display_name", project.name)
        device = meta.get("device", "generic")
        android_ver = meta.get("android_version", "unknown")

        print(f"\n {Colors.BOLD}◈ Autoporter ◈ Project:{Colors.RESET} {Colors.BRIGHT_GREEN}{project.name}{Colors.RESET} ({disp_name})")
        print(f" {Colors.DIM}Device: {device} | Android {android_ver} | Path: project/{project.name}/{Colors.RESET}\n")

        display_workspace_status()

        categories = [
            f"📂 {Colors.BOLD}Unpack & Extract{Colors.RESET}        (OTA ROM, Payload, Images, Boot)",
            f"⚙️  {Colors.BOLD}Contexts & Inspection{Colors.RESET}   (SELinux, fs_config, build.prop)",
            f"📦 {Colors.BOLD}Repack & Build{Colors.RESET}          (Partitions, super.img, Flashable ROMs)",
            f"🧹 {Colors.BOLD}Workspace & Tools{Colors.RESET}       (Cleanup, Edit project details)",
            f"🔄 {Colors.CYAN}Switch Project{Colors.RESET}          (Back to Project Hub)",
            f"🚪 {Colors.RED}Exit Autoporter{Colors.RESET}",
        ]

        choice = ask_choice(f"Project [{project.name}] Menu:", categories, default_idx=0)

        if choice == 0:
            menu_unpack_extract()
        elif choice == 1:
            menu_contexts_inspection()
        elif choice == 2:
            menu_repack_build()
        elif choice == 3:
            menu_workspace_tools(project)
        elif choice == 4:
            break
        elif choice == 5:
            print(f"\n {Colors.BRIGHT_CYAN}Happy ROM cooking! Goodbye.{Colors.RESET}\n")
            sys.exit(0)


def run_homescreen():
    """Initial welcoming homescreen: MOTD and Project Hub."""
    while True:
        clear_screen()
        banner()
        print_motd()

        all_projs = ProjectManager.list_projects()
        active = ProjectManager.get_active_project()

        print_section("Project Hub")
        display_projects_table()

        if all_projs:
            if active and active.exists():
                options = [
                    f"{Colors.BOLD}Open Active: {Colors.BRIGHT_GREEN}{active.name}{Colors.RESET}",
                    "Select / Switch Project",
                    "Create New Project",
                    "Delete a Project",
                    f"{Colors.RED}Exit{Colors.RESET}",
                ]
            else:
                options = [
                    "Select a Project",
                    "Create New Project",
                    "Delete a Project",
                    f"{Colors.RED}Exit{Colors.RESET}",
                ]
        else:
            options = [
                "Create New Project",
                f"{Colors.RED}Exit{Colors.RESET}",
            ]

        choice = ask_choice("Project Hub Actions:", options, default_idx=0)

        if all_projs and active and active.exists():
            if choice == 0:
                run_project_homepage(active)
            elif choice == 1:
                p = select_project_dialog()
                if p:
                    run_project_homepage(p)
            elif choice == 2:
                p = create_project_dialog()
                if p:
                    run_project_homepage(p)
            elif choice == 3:
                delete_project_dialog()
            elif choice == 4:
                print(f"\n {Colors.BRIGHT_CYAN}Happy ROM cooking! Goodbye.{Colors.RESET}\n")
                sys.exit(0)
        elif all_projs:
            if choice == 0:
                p = select_project_dialog()
                if p:
                    run_project_homepage(p)
            elif choice == 1:
                p = create_project_dialog()
                if p:
                    run_project_homepage(p)
            elif choice == 2:
                delete_project_dialog()
            elif choice == 3:
                print(f"\n {Colors.BRIGHT_CYAN}Happy ROM cooking! Goodbye.{Colors.RESET}\n")
                sys.exit(0)
        else:
            if choice == 0:
                p = create_project_dialog()
                if p:
                    run_project_homepage(p)
            elif choice == 1:
                print(f"\n {Colors.BRIGHT_CYAN}Happy ROM cooking! Goodbye.{Colors.RESET}\n")
                sys.exit(0)


def main_menu():
    """Alias for welcoming homescreen."""
    run_homescreen()


def parse_args():
    """Handles CLI arguments for non-interactive or scripted execution."""
    parser = argparse.ArgumentParser(
        description="Autoporter - Android ROM Kitchen & Partition Transmutation Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-P", "--project", type=str, default=None, help="Target project name in kebab-case")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # project
    p_proj = subparsers.add_parser("project", help="Manage or switch projects")
    p_proj.add_argument("name", nargs="?", default="", help="Project name to switch to or inspect")
    p_proj.add_argument("--create", action="store_true", help="Create project if it does not exist")
    p_proj.add_argument("--list", action="store_true", help="List all projects")

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

            if args.project:
                ProjectManager.set_active_project(args.project)
                print_info(f"Target project switched to: {Colors.BOLD}{args.project}{Colors.RESET}")

            if args.command == "project":
                if args.list:
                    from core.config import format_size
                    from core.ui import print_table
                    projs = ProjectManager.list_projects()
                    act = ProjectManager.get_active_project()
                    headers = ["#", "Project (Kebab)", "Display Name", "Device", "Total Size", "Status"]
                    rows = []
                    for idx, p in enumerate(projs):
                        ov = p.get_overview()
                        is_act = (act and act.name == p.name)
                        st = f"{Colors.BRIGHT_GREEN}● ACTIVE{Colors.RESET}" if is_act else f"{Colors.DIM}idle{Colors.RESET}"
                        rows.append([
                            str(idx + 1),
                            p.name,
                            ov["meta"].get("display_name", p.name),
                            ov["meta"].get("device", "-"),
                            format_size(ov["total_size"]),
                            st,
                        ])
                    print_table(headers, rows)
                elif args.name:
                    if args.create:
                        p = ProjectManager.create_project(args.name)
                        print_success(f"Created project/{p.name}/ and set to active.")
                    else:
                        p = ProjectManager.set_active_project(args.name)
                        print_success(f"Active project set to: {p.name}")
                else:
                    run_project_manager_menu()
            elif args.command == "status":
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
