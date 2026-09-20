#!/usr/bin/env python3
"""
Autoporter Workspace Manager:
Manages directories, inspects partition states, build.prop properties,
installed packages, and handles cleanup operations.
"""

import os
import sys
import shutil
from pathlib import Path
from typing import List, Dict, Optional

from core.config import (
    INPUT_DIR,
    IMAGES_DIR,
    CAULDRON_DIR,
    FINALIZED_DIR,
    OUTPUT_DIR,
    format_size,
)
from core.ui import (
    Colors,
    print_info,
    print_success,
    print_warning,
    print_error,
    print_section,
    print_table,
    ask_choice,
    ask_text,
    ask_confirm,
)


def get_workspace_overview() -> Dict[str, any]:
    """Summarizes contents and sizes across all Autoporter directories."""
    def count_dir(d: Path):
        if not d.exists():
            return 0, 0
        files = [f for f in d.iterdir() if f.is_file() and f.name != ".gitkeep"]
        size = sum(f.stat().st_size for f in files)
        return len(files), size

    in_cnt, in_sz = count_dir(INPUT_DIR)
    img_cnt, img_sz = count_dir(IMAGES_DIR)
    fin_cnt, fin_sz = count_dir(FINALIZED_DIR)
    out_cnt, out_sz = count_dir(OUTPUT_DIR)

    cauldron_parts = [p.name for p in CAULDRON_DIR.iterdir() if p.is_dir() and p.name not in ["config", ".meta", "unpacked_super"]] if CAULDRON_DIR.exists() else []

    return {
        "input": {"count": in_cnt, "size": in_sz},
        "images": {"count": img_cnt, "size": img_sz},
        "cauldron": {"count": len(cauldron_parts), "partitions": cauldron_parts},
        "finalized": {"count": fin_cnt, "size": fin_sz},
        "output": {"count": out_cnt, "size": out_sz},
    }


def display_workspace_status():
    """Prints a styled overview of the kitchen workspace."""
    ov = get_workspace_overview()
    headers = ["Directory", "Role", "Item Count", "Total Size"]
    rows = [
        ["input/", "Incoming ROM archives & payloads", str(ov["input"]["count"]), format_size(ov["input"]["size"])],
        ["images/", "Extracted partition images (.img)", str(ov["images"]["count"]), format_size(ov["images"]["size"])],
        ["cauldron/", "Unpacked working filesystem trees", str(ov["cauldron"]["count"]), f"{', '.join(ov['cauldron']['partitions'][:5]) or '(none)'}"],
        ["finalized/", "Repacked partition images", str(ov["finalized"]["count"]), format_size(ov["finalized"]["size"])],
        ["output/", "Final super.img & OTA packages", str(ov["output"]["count"]), format_size(ov["output"]["size"])],
    ]
    print_table(headers, rows)


def inspect_build_prop():
    """Finds and displays system build.prop properties for unpacked partitions."""
    print_section("Android build.prop Inspector")
    candidates = []

    # Search for build.prop in cauldron/
    if CAULDRON_DIR.exists():
        for bp in CAULDRON_DIR.rglob("build.prop"):
            if bp.is_file():
                candidates.append(bp)

    if not candidates:
        print_warning("No build.prop files found in cauldron/.")
        return

    options = [f"{p.relative_to(CAULDRON_DIR)}" for p in candidates]
    options.append("Cancel")
    c = ask_choice("Select build.prop to inspect:", options)
    if c == len(options) - 1:
        return

    chosen_prop = candidates[c]
    interesting_keys = [
        "ro.build.version.release",
        "ro.build.version.security_patch",
        "ro.product.model",
        "ro.product.device",
        "ro.product.brand",
        "ro.product.name",
        "ro.build.date",
        "ro.build.flavor",
        "ro.build.type",
    ]

    props = {}
    with open(chosen_prop, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line_s = line.strip()
            if "=" in line_s and not line_s.startswith("#"):
                k, v = line_s.split("=", 1)
                props[k.strip()] = v.strip()

    rows = []
    for k in interesting_keys:
        if k in props:
            rows.append([k, props[k]])

    if rows:
        print_table(["Property", "Value"], rows)
    else:
        print_info(f"Loaded {len(props)} properties from {chosen_prop.name}.")


def clean_workspace_menu():
    """Menu to clean specific or all working directories."""
    print_section("Workspace Cleanup Manager")
    options = [
        "Clean 'cauldron/' (Unpacked work trees)",
        "Clean 'finalized/' (Repacked partition images)",
        "Clean 'images/' (Extracted image files)",
        "Clean 'output/' (Generated super.img and OTA zips)",
        "RESET EVERYTHING (Clear all working directories)",
        "Cancel",
    ]
    c = ask_choice("Choose directory to clean:", options, default_idx=len(options) - 1)

    def wipe_dir(d: Path):
        for item in d.iterdir():
            if item.name == ".gitkeep":
                continue
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)

    if c == 0:
        if ask_confirm("Are you sure you want to clean cauldron/?"):
            wipe_dir(CAULDRON_DIR)
            print_success("cauldron/ cleaned.")
    elif c == 1:
        if ask_confirm("Are you sure you want to clean finalized/?"):
            wipe_dir(FINALIZED_DIR)
            print_success("finalized/ cleaned.")
    elif c == 2:
        if ask_confirm("Are you sure you want to clean images/?"):
            wipe_dir(IMAGES_DIR)
            print_success("images/ cleaned.")
    elif c == 3:
        if ask_confirm("Are you sure you want to clean output/?"):
            wipe_dir(OUTPUT_DIR)
            print_success("output/ cleaned.")
    elif c == 4:
        if ask_confirm("WARNING: This will delete all images, cauldron, finalized, and output! Proceed?", default=False):
            for d in [CAULDRON_DIR, FINALIZED_DIR, IMAGES_DIR, OUTPUT_DIR]:
                wipe_dir(d)
            print_success("All working directories reset.")
    else:
        return
