#!/usr/bin/env python3
"""
Autoporter Context Synchronizer:
Ensures permissions (fs_config), SELinux security contexts (file_contexts),
and symlinks are preserved and accurately synthesized for any new or modified files.
"""

import os
from pathlib import Path
from typing import Set, Dict, Tuple

from core.ui import print_info, print_success, print_warning


def load_fs_config_entries(fs_config_path: Path) -> Dict[str, str]:
    """Loads existing fs_config into a dictionary mapping relative_path -> full_entry_line."""
    entries = {}
    if not fs_config_path.is_file():
        return entries

    with open(fs_config_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line_s = line.strip()
            if not line_s or line_s.startswith("#"):
                continue
            parts = line_s.split()
            if parts:
                rel_path = parts[0].lstrip("/")
                entries[rel_path] = line_s
    return entries


def load_file_contexts_entries(file_contexts_path: Path) -> Dict[str, str]:
    """Loads existing file_contexts into a dictionary mapping path_pattern -> context."""
    entries = {}
    if not file_contexts_path.is_file():
        return entries

    with open(file_contexts_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line_s = line.strip()
            if not line_s or line_s.startswith("#"):
                continue
            parts = line_s.split()
            if len(parts) >= 2:
                entries[parts[0]] = parts[1]
    return entries


def infer_fs_config_for_path(partition_name: str, rel_path: str, is_dir: bool, is_symlink: bool) -> str:
    """Infers appropriate Android UID, GID, and permissions mode for a newly added file or directory."""
    full_android_path = f"{partition_name}/{rel_path}" if rel_path else partition_name

    if is_dir:
        return f"{full_android_path} 0 0 0755"
    if is_symlink:
        return f"{full_android_path} 0 0 0777"

    lower_path = rel_path.lower()
    # Executable binaries
    if "/bin/" in lower_path or lower_path.startswith("bin/") or "/xbin/" in lower_path:
        return f"{full_android_path} 0 2000 0755 capabilities=0x0"
    # Shell scripts
    if lower_path.endswith(".sh"):
        return f"{full_android_path} 0 2000 0755 capabilities=0x0"
    # Standard configuration, libraries, framework, apks
    return f"{full_android_path} 0 0 0644"


def infer_file_context_for_path(partition_name: str, rel_path: str) -> str:
    """Infers standard Android SELinux context for an unlisted file or folder."""
    mount_prefix = f"/{partition_name}"
    android_path = f"{mount_prefix}/{rel_path}" if rel_path else mount_prefix
    escaped_path = android_path.replace("+", r"\+")

    # Match typical subsystem contexts
    if "bin/" in rel_path:
        return f"{escaped_path} u:object_r:system_file:s0"
    elif "vendor/" in partition_name:
        return f"{escaped_path} u:object_r:vendor_file:s0"
    else:
        return f"{escaped_path} u:object_r:system_file:s0"


def sync_partition_contexts(partition_name: str, partition_dir: Path, config_dir: Path) -> Tuple[int, int]:
    """
    Synchronizes fs_config and file_contexts for the partition.
    Scans the filesystem tree in partition_dir and appends missing entries.
    Returns: (added_fs_config_count, added_file_contexts_count)
    """
    fs_config_file = config_dir / f"{partition_name}_fs_config"
    file_contexts_file = config_dir / f"{partition_name}_file_contexts"

    existing_fs_config = load_fs_config_entries(fs_config_file)
    existing_contexts = load_file_contexts_entries(file_contexts_file)

    new_fs_entries = []
    new_context_entries = []

    # Traverse all files and directories in partition_dir
    for root, dirs, files in os.walk(partition_dir):
        rel_root = os.path.relpath(root, partition_dir)
        if rel_root == ".":
            rel_root = ""

        # Check directories
        for d in dirs:
            dir_rel = os.path.normpath(os.path.join(rel_root, d))
            fs_key = f"{partition_name}/{dir_rel}"
            if fs_key not in existing_fs_config and dir_rel not in existing_fs_config:
                new_fs_entries.append(infer_fs_config_for_path(partition_name, dir_rel, is_dir=True, is_symlink=False))
            ctx_key = f"/{partition_name}/{dir_rel}"
            if ctx_key not in existing_contexts:
                new_context_entries.append(infer_file_context_for_path(partition_name, dir_rel))

        # Check files and symlinks
        for f in files:
            file_rel = os.path.normpath(os.path.join(rel_root, f))
            full_f_path = Path(root) / f
            is_symlink = full_f_path.is_symlink()
            fs_key = f"{partition_name}/{file_rel}"
            if fs_key not in existing_fs_config and file_rel not in existing_fs_config:
                new_fs_entries.append(infer_fs_config_for_path(partition_name, file_rel, is_dir=False, is_symlink=is_symlink))
            ctx_key = f"/{partition_name}/{file_rel}"
            if ctx_key not in existing_contexts:
                new_context_entries.append(infer_file_context_for_path(partition_name, file_rel))

    # Append new entries to fs_config
    if new_fs_entries:
        with open(fs_config_file, "a", encoding="utf-8") as f:
            for entry in new_fs_entries:
                f.write(f"{entry}\n")

    # Append new entries to file_contexts
    if new_context_entries:
        with open(file_contexts_file, "a", encoding="utf-8") as f:
            for entry in new_context_entries:
                f.write(f"{entry}\n")

    return len(new_fs_entries), len(new_context_entries)
