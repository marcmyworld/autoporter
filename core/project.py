#!/usr/bin/env python3
"""
Autoporter Project Management Module:
Provides multi-project architecture where each project is isolated in:
  project/<project-name-in-kebab-case>/
    ├── project.json
    ├── input/
    ├── images/
    ├── cauldron/
    │   └── config/
    ├── finalized/
    └── output/
"""

import os
import re
import sys
import json
import time
import shutil
from pathlib import Path
from typing import List, Dict, Optional, Any

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

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECTS_DIR = PROJECT_ROOT / "project"
ACTIVE_FILE = PROJECTS_DIR / ".active_project"


def to_kebab_case(name: str) -> str:
    """
    Converts any arbitrary project name into clean, filesystem-safe kebab-case.
    Examples:
      - 'HyperOS Chenfeng'       -> 'hyperos-chenfeng'
      - 'Xiaomi 14 Civi (SM8635)' -> 'xiaomi-14-civi-sm8635'
      - 'My_Project_123'         -> 'my-project-123'
      - 'LineageOS-21.0'         -> 'lineageos-21-0'
    """
    s = name.strip()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s)
    s = s.lower().strip("-")
    return s or "unnamed-project"


class Project:
    """Represents a single Autoporter ROM project."""

    def __init__(self, name: str):
        self.name = to_kebab_case(name)
        self.root = PROJECTS_DIR / self.name
        self.input_dir = self.root / "input"
        self.images_dir = self.root / "images"
        self.cauldron_dir = self.root / "cauldron"
        self.config_dir = self.cauldron_dir / "config"
        self.finalized_dir = self.root / "finalized"
        self.output_dir = self.root / "output"
        self.meta_file = self.root / "project.json"

    def exists(self) -> bool:
        return self.root.is_dir() and self.meta_file.is_file()

    def create(self, display_name: str = "", device: str = "", android_version: str = "", notes: str = ""):
        """Initializes all project directories and creates project.json."""
        for d in [self.input_dir, self.images_dir, self.cauldron_dir, self.config_dir, self.finalized_dir, self.output_dir]:
            d.mkdir(parents=True, exist_ok=True)
            keep_file = d / ".gitkeep"
            if not keep_file.exists():
                keep_file.touch()

        meta = {
            "name": self.name,
            "display_name": display_name or self.name,
            "device": device or "generic",
            "android_version": android_version or "unknown",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "notes": notes,
        }
        with open(self.meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    def get_meta(self) -> Dict[str, Any]:
        if self.meta_file.is_file():
            try:
                with open(self.meta_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"name": self.name, "display_name": self.name, "device": "unknown"}

    def save_meta(self, meta: Dict[str, Any]):
        meta["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(self.meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    def get_overview(self) -> Dict[str, Any]:
        """Calculates item counts and sizes for this project."""
        def count_dir(d: Path):
            if not d.exists():
                return 0, 0
            files = [f for f in d.iterdir() if f.is_file() and f.name != ".gitkeep"]
            size = sum(f.stat().st_size for f in files)
            return len(files), size

        in_cnt, in_sz = count_dir(self.input_dir)
        img_cnt, img_sz = count_dir(self.images_dir)
        fin_cnt, fin_sz = count_dir(self.finalized_dir)
        out_cnt, out_sz = count_dir(self.output_dir)

        cauldron_parts = [
            p.name for p in self.cauldron_dir.iterdir()
            if p.is_dir() and p.name not in ["config", ".meta", "unpacked_super"]
        ] if self.cauldron_dir.exists() else []

        total_sz = in_sz + img_sz + fin_sz + out_sz
        return {
            "name": self.name,
            "meta": self.get_meta(),
            "input": {"count": in_cnt, "size": in_sz},
            "images": {"count": img_cnt, "size": img_sz},
            "cauldron": {"count": len(cauldron_parts), "partitions": cauldron_parts},
            "finalized": {"count": fin_cnt, "size": fin_sz},
            "output": {"count": out_cnt, "size": out_sz},
            "total_size": total_sz,
        }

    def delete(self):
        """Deletes the entire project directory."""
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)


class ProjectManager:
    """Manages project workspaces and active project state."""

    _active_project: Optional[Project] = None

    @classmethod
    def ensure_projects_dir(cls):
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def list_projects(cls) -> List[Project]:
        cls.ensure_projects_dir()
        projects = []
        for d in sorted(PROJECTS_DIR.iterdir()):
            if d.is_dir() and (d / "project.json").is_file():
                projects.append(Project(d.name))
        return projects

    @classmethod
    def get_project(cls, name: str) -> Optional[Project]:
        kebab = to_kebab_case(name)
        p = Project(kebab)
        return p if p.exists() else None

    @classmethod
    def create_project(cls, name: str, display_name: str = "", device: str = "", android_version: str = "", notes: str = "") -> Project:
        cls.ensure_projects_dir()
        kebab = to_kebab_case(name)
        p = Project(kebab)
        p.create(display_name=display_name or name, device=device, android_version=android_version, notes=notes)
        cls.set_active_project(p)
        return p

    @classmethod
    def delete_project(cls, name: str) -> bool:
        p = cls.get_project(name)
        if not p:
            return False
        # If deleting active project, clear active
        if cls._active_project and cls._active_project.name == p.name:
            cls._active_project = None
            if ACTIVE_FILE.exists():
                ACTIVE_FILE.unlink()
        p.delete()
        return True

    @classmethod
    def get_active_project(cls) -> Optional[Project]:
        if cls._active_project and cls._active_project.exists():
            return cls._active_project

        cls.ensure_projects_dir()
        if ACTIVE_FILE.is_file():
            try:
                saved_name = ACTIVE_FILE.read_text().strip()
                p = Project(saved_name)
                if p.exists():
                    cls._active_project = p
                    return p
            except Exception:
                pass

        # Fallback to first existing project
        all_projs = cls.list_projects()
        if all_projs:
            cls.set_active_project(all_projs[0])
            return all_projs[0]

        return None

    @classmethod
    def set_active_project(cls, project_or_name) -> Project:
        if isinstance(project_or_name, Project):
            p = project_or_name
        else:
            kebab = to_kebab_case(str(project_or_name))
            p = Project(kebab)
            if not p.exists():
                p.create()

        cls._active_project = p
        cls.ensure_projects_dir()
        try:
            ACTIVE_FILE.write_text(p.name)
        except Exception:
            pass
        return p

    @classmethod
    def migrate_legacy_workspace(cls, target_name: str = "chenfeng") -> Optional[Project]:
        """
        Migrates any legacy files sitting in root images/ or cauldron/
        into a dedicated project directory (e.g. project/chenfeng/).
        """
        legacy_images = PROJECT_ROOT / "images"
        legacy_cauldron = PROJECT_ROOT / "cauldron"
        legacy_input = PROJECT_ROOT / "input"
        legacy_finalized = PROJECT_ROOT / "finalized"
        legacy_output = PROJECT_ROOT / "output"

        has_legacy_data = False
        for d in [legacy_images, legacy_cauldron, legacy_input, legacy_finalized, legacy_output]:
            if d.exists() and any(f.name != ".gitkeep" for f in d.iterdir()):
                has_legacy_data = True
                break

        if not has_legacy_data:
            return None

        print_info(f"Migrating existing workspace files into project '{target_name}'...")
        project = cls.get_project(target_name) or cls.create_project(
            name=target_name,
            display_name="Xiaomi 14 Civi (Chenfeng)",
            device="chenfeng",
            android_version="16",
            notes="Migrated from initial workspace",
        )

        def move_contents(src: Path, dst: Path):
            if not src.exists():
                return
            dst.mkdir(parents=True, exist_ok=True)
            for item in list(src.iterdir()):
                if item.name == ".gitkeep":
                    continue
                target = dst / item.name
                if target.exists():
                    if target.is_dir():
                        shutil.rmtree(target, ignore_errors=True)
                    else:
                        target.unlink()
                shutil.move(str(item), str(target))

        move_contents(legacy_images, project.images_dir)
        move_contents(legacy_cauldron, project.cauldron_dir)
        move_contents(legacy_input, project.input_dir)
        move_contents(legacy_finalized, project.finalized_dir)
        move_contents(legacy_output, project.output_dir)

        cls.set_active_project(project)
        print_success(f"Workspace migrated into project/{project.name}/")
        return project


def get_active_project() -> Optional[Project]:
    return ProjectManager.get_active_project()


def require_active_project() -> Project:
    p = ProjectManager.get_active_project()
    if not p:
        # Prompt to create default
        p = ProjectManager.create_project("chenfeng", display_name="Default Project")
    return p


def display_projects_table():
    """Prints a concise summary table of all projects."""
    all_projs = ProjectManager.list_projects()
    active = ProjectManager.get_active_project()

    if not all_projs:
        print_info("No projects found yet. Create one to get started!\n")
        return

    from core.config import format_size
    headers = ["#", "Project", "Device", "Android", "Size", "Status"]
    rows = []
    for i, p in enumerate(all_projs):
        ov = p.get_overview()
        is_act = (active and active.name == p.name)
        status = f"{Colors.BRIGHT_GREEN}● ACTIVE{Colors.RESET}" if is_act else f"{Colors.DIM}idle{Colors.RESET}"
        rows.append([
            str(i + 1),
            p.name,
            ov["meta"].get("device", "-"),
            f"Android {ov['meta'].get('android_version', '?')}",
            format_size(ov["total_size"]),
            status,
        ])
    print_table(headers, rows)


def select_project_dialog() -> Optional[Project]:
    """Interactive dialog to select an existing project."""
    all_projs = ProjectManager.list_projects()
    if not all_projs:
        print_warning("No projects exist yet. Please create one.")
        return None
    active = ProjectManager.get_active_project()
    p_names = []
    for p in all_projs:
        disp = p.get_meta().get("display_name", "")
        suffix = f" ({disp})" if disp and disp != p.name else ""
        star = f" {Colors.BRIGHT_GREEN}★{Colors.RESET}" if (active and active.name == p.name) else ""
        p_names.append(f"{p.name}{suffix}{star}")

    p_idx = ask_choice("Select project:", p_names)
    chosen = all_projs[p_idx]
    ProjectManager.set_active_project(chosen)
    return chosen


def create_project_dialog() -> Optional[Project]:
    """Interactive dialog to create a new project."""
    raw_name = ask_text("Project name (e.g. HyperOS Chenfeng, Lineage 21)")
    if not raw_name:
        return None
    kebab = to_kebab_case(raw_name)
    if ProjectManager.get_project(kebab):
        print_warning(f"Project '{kebab}' already exists.")
        return ProjectManager.get_project(kebab)

    device = ask_text("Device codename (e.g. chenfeng)", default="generic")
    ver = ask_text("Android version (e.g. 15, 16)", default="16")
    notes = ask_text("Notes (optional)", default="")

    new_proj = ProjectManager.create_project(
        name=kebab,
        display_name=raw_name,
        device=device,
        android_version=ver,
        notes=notes,
    )
    print_success(f"Created project/{new_proj.name}/")
    return new_proj


def delete_project_dialog() -> bool:
    """Interactive dialog to delete a project."""
    all_projs = ProjectManager.list_projects()
    if not all_projs:
        print_warning("No projects found.")
        return False
    p_names = [p.name for p in all_projs]
    p_idx = ask_choice("Select project to delete:", p_names)
    p = all_projs[p_idx]
    if ask_confirm(f"{Colors.RED}DANGER: Delete project/{p.name}/ and all its files?{Colors.RESET}", default=False):
        ProjectManager.delete_project(p.name)
        print_success(f"Deleted project/{p.name}/")
        return True
    return False


def edit_project_dialog(project: Optional[Project] = None) -> bool:
    """Interactive dialog to edit project metadata."""
    p = project or ProjectManager.get_active_project()
    if not p:
        print_warning("No project selected.")
        return False
    meta = p.get_meta()
    disp = ask_text("Display Name", default=meta.get("display_name", p.name))
    dev = ask_text("Device Codename", default=meta.get("device", "generic"))
    ver = ask_text("Android Version", default=meta.get("android_version", "16"))
    notes = ask_text("Notes", default=meta.get("notes", ""))
    meta["display_name"] = disp
    meta["device"] = dev
    meta["android_version"] = ver
    meta["notes"] = notes
    p.save_meta(meta)
    print_success(f"Updated metadata for project/{p.name}/")
    return True


def run_project_manager_menu():
    """Interactive CLI menu for project management."""
    print_section("Project Manager")
    display_projects_table()

    options = [
        "Select / Switch Project",
        "Create New Project",
        "Edit Project Info",
        "Delete a Project",
        "Back",
    ]
    choice = ask_choice("Choose Action:", options, default_idx=0)

    if choice == 0:
        select_project_dialog()
    elif choice == 1:
        create_project_dialog()
    elif choice == 2:
        edit_project_dialog()
    elif choice == 3:
        delete_project_dialog()
    else:
        return

