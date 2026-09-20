#!/usr/bin/env python3
"""
Autoporter Configuration and Path Resolution
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = PROJECT_ROOT / "bin"
PROJECTS_DIR = PROJECT_ROOT / "project"
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


class DynamicPath:
    """
    Dynamic Path proxy that resolves lazily to the active project's directories.
    Allows transparent path manipulation (/, str, glob, exists, open, etc.)
    that instantly adapts whenever the active project is switched.
    """

    def __init__(self, getter_func):
        self._getter = getter_func

    @property
    def _path(self) -> Path:
        p = self._getter()
        p.mkdir(parents=True, exist_ok=True)
        return p

    def __truediv__(self, other):
        return self._path / other

    def __rtruediv__(self, other):
        return Path(other) / self._path

    def __str__(self):
        return str(self._path)

    def __fspath__(self):
        return str(self._path)

    def __repr__(self):
        return repr(self._path)

    def __eq__(self, other):
        return str(self._path) == str(other)

    def __hash__(self):
        return hash(self._path)

    def __getattr__(self, item):
        return getattr(self._path, item)


def _get_active_or_default():
    from core.project import require_active_project
    return require_active_project()


# Dynamic project-based directory proxies
INPUT_DIR = DynamicPath(lambda: _get_active_or_default().input_dir)
IMAGES_DIR = DynamicPath(lambda: _get_active_or_default().images_dir)
CAULDRON_DIR = DynamicPath(lambda: _get_active_or_default().cauldron_dir)
FINALIZED_DIR = DynamicPath(lambda: _get_active_or_default().finalized_dir)
OUTPUT_DIR = DynamicPath(lambda: _get_active_or_default().output_dir)

# Required binaries mapping
BINARIES = {
    "payload-dumper-go": BIN_DIR / "payload-dumper-go",
    "imgkit": BIN_DIR / "imgkit",
    "lpmake": BIN_DIR / "lpmake",
    "lpunpack": BIN_DIR / "lpunpack",
    "mkfs.erofs": BIN_DIR / "mkfs.erofs",
    "extract.erofs": BIN_DIR / "extract.erofs",
    "fsck.erofs": BIN_DIR / "fsck.erofs",
    "mke2fs": BIN_DIR / "mke2fs",
    "e2fsdroid": BIN_DIR / "e2fsdroid",
    "make_ext4fs": BIN_DIR / "make_ext4fs",
    "magiskboot": BIN_DIR / "magiskboot",
    "simg2img": BIN_DIR / "simg2img",
    "img2simg": BIN_DIR / "img2simg",
    "cpio": BIN_DIR / "cpio",
    "brotli": BIN_DIR / "brotli",
    "zstd": BIN_DIR / "zstd",
    "delta_generator": BIN_DIR / "delta_generator",
}


def get_binary(name: str) -> str:
    """
    Resolves the executable path for a given tool.
    Prioritizes the self-contained bin/ directory within Autoporter,
    falling back to system PATH if necessary.
    """
    bin_path = BINARIES.get(name)
    if bin_path and bin_path.is_file():
        if not os.access(bin_path, os.X_OK):
            os.chmod(bin_path, 0o755)
        return str(bin_path)

    system_bin = shutil.which(name)
    if system_bin:
        return system_bin

    raise FileNotFoundError(f"Required binary '{name}' was not found in {BIN_DIR} or system PATH.")


def parse_size_bytes(size_str: str) -> int:
    """
    Parse a human-readable size string into accurate binary system bytes.
    Examples:
      - '8.5 GB' or '8.5G' or '8.5GiB' -> 8.5 * 1024^3 = 9126805504 bytes
      - '9G' -> 9 * 1024^3 = 9663676416 bytes
      - '500M' -> 500 * 1024^2 = 524288000 bytes
      - '9126805504' -> 9126805504 bytes
    """
    clean = size_str.strip().upper()
    if clean.isdigit():
        return int(clean)

    units = {
        "B": 1,
        "K": 1024,
        "KB": 1024,
        "KIB": 1024,
        "M": 1024**2,
        "MB": 1024**2,
        "MIB": 1024**2,
        "G": 1024**3,
        "GB": 1024**3,
        "GIB": 1024**3,
        "T": 1024**4,
        "TB": 1024**4,
        "TIB": 1024**4,
    }

    # Extract numeric part and unit
    num_part = ""
    unit_part = ""
    for i, char in enumerate(clean):
        if char.isdigit() or char == ".":
            num_part += char
        else:
            unit_part = clean[i:].strip()
            break

    if not num_part:
        raise ValueError(f"Invalid size string: '{size_str}'")

    val = float(num_part)
    multiplier = units.get(unit_part, 1024**3)  # default to GB if unspecified letter
    return int(val * multiplier)


def format_size(size_bytes: int) -> str:
    """Format bytes into readable binary unit representation."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024**2:
        return f"{size_bytes / 1024:.2f} KiB"
    elif size_bytes < 1024**3:
        return f"{size_bytes / (1024**2):.2f} MiB"
    else:
        return f"{size_bytes / (1024**3):.2f} GiB"


def detect_file_type(file_path: Path) -> str:
    """
    Detects the file type of an Android image or archive.
    Returns: 'sparse', 'erofs', 'ext4', 'boot', 'super', 'payload', 'zip', or 'unknown'
    """
    if not file_path.is_file():
        return "unknown"

    name_lower = file_path.name.lower()
    if name_lower.endswith(".zip"):
        return "zip"
    if name_lower == "payload.bin" or name_lower.endswith(".bin"):
        # Check payload magic 'CrAU'
        try:
            with open(file_path, "rb") as f:
                magic = f.read(4)
                if magic == b"CrAU":
                    return "payload"
        except Exception:
            pass

    # Read first 4096 bytes to inspect magic
    try:
        with open(file_path, "rb") as f:
            header = f.read(4096)
    except Exception:
        return "unknown"

    if len(header) < 4:
        return "unknown"

    # Check Android sparse image magic 0xED26FF3A
    if header[:4] == b"\x3a\xff\x26\xed":
        return "sparse"

    # Check Super image header magic (LP_METADATA_GEOMETRY_MAGIC: 0x616c4467 / "gDla")
    if b"gDla" in header:
        return "super"

    # Check Android boot image magic: 'ANDROID!'
    if header[:8] == b"ANDROID!":
        return "boot"

    # Check EROFS magic: 0xE0F5E1E2 at offset 1024
    if len(header) >= 1028:
        if header[1024:1028] == b"\xe2\xe1\xf5\xe0":
            return "erofs"

    # Check EXT4 superblock magic: 0xEF53 at offset 1080 (1024 + 0x38)
    if len(header) >= 1082:
        if header[1080:1082] == b"\x53\xef":
            return "ext4"

    # Boot partition naming fallback
    stem = file_path.stem.lower()
    if any(b_name in stem for b_name in ["boot", "vendor_boot", "init_boot", "recovery"]):
        return "boot"

    return "unknown"
