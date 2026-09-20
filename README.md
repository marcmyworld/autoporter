# Autoporter ◈ Android ROM Kitchen & Partition Transmutation Engine

Autoporter is a complete, scriptable, and interactive terminal environment designed to streamline Android ROM porting, multi-project ROM kitchens (like an advanced CLI alternative to MIO Kitchen), OTA payload unpacking, filesystem modification, and repacking across all Linux distributions.

---

## ⚡ Key Capabilities

1. **Multi-Project Workspace Architecture (`project/<kebab-name>/`)**
   - Work on multiple ROM ports simultaneously with 100% directory and partition isolation.
   - Each project is isolated in `project/<project-name-in-kebab-case>/` with its own `input/`, `images/`, `cauldron/`, `finalized/`, and `output/` folders.
   - Switch active projects dynamically from the interactive CLI or with `-P / --project <name>`.
   - Store metadata in `project.json` (device codename, Android version, display name, notes).

2. **OTA ROM, Payload & ROM.zip Unpacking**
   - Direct extraction of `payload.bin` from OTA ZIPs or standalone payload files using high-performance `payload-dumper-go`.
   - Flexible partition range selection (e.g. `1-15, 18-20` or by name `system,vendor,boot`) or full multi-threaded extraction.
   - **Fastboot ROM.zip with `images/` support**: Scans images embedded inside ROM archives (`images/super.img`, `images/boot.img`, etc.) with interactive partition selection.
   - **Automated `super.img` Unpacking**: When `super.img` is present or extracted, Autoporter detects it and offers 1-click unpacking into its logical partitions (`system`, `vendor`, `product`, etc.), with optional direct extraction into `cauldron/` and disk-saving cleanup.

3. **Image Unpacking to `cauldron/`**
   - **Filesystems**: EROFS, EXT4, and F2FS images automatically unsparsed and unpacked.
   - **Kernel & Boot Images**: `boot.img`, `vendor_boot.img`, `init_boot.img`, and `recovery.img` unpacked via `magiskboot`.
   - **Ramdisk Extraction**: Automatically unpacks `ramdisk.cpio` into an editable `ramdisk/` directory.
   - **Super Partition**: `super.img` unpacks into its constituent dynamic partitions using `lpunpack`.

4. **SELinux Contexts & Permissions Preservation**
   - Preserves `fs_config` (UID, GID, file mode, capabilities) and `file_contexts` (SELinux security contexts).
   - **Intelligent Context Synchronizer**: When new files, scripts, or apps are added into `cauldron/<partition>/`, Autoporter automatically synthesizes valid Android permissions and SELinux labels so repacked images boot cleanly without SELinux denials.

5. **Customizable Repacking to `finalized/`**
   - **EROFS**: Choose compression algorithm (`lz4hc`, `lz4`, `lzma`, `deflate`, `zstd`, or uncompressed) and configure fine-grained compression levels (e.g. `lz4hc` 0-12, `lzma` 0-9, `zstd` 0-22).
   - **EXT4**: Configurable sizing with headroom buffers, sparse or raw generation.
   - **Boot Images**: Ramdisk repacked from `ramdisk/` and combined with modified kernel, DTB, and header using `magiskboot`.

6. **Super Image Repacking (`super.img`)**
   - **Binary System Size Computation**: Accurately computes exact byte values from human inputs:
     - `8.5 GB` = `9,126,805,504` bytes (Qualcomm SM8635 / Xiaomi 14 Civi / POCO F6 standard)
     - `9.0 GB` = `9,663,676,416` bytes
     - `9.5 GB` = `10,200,547,328` bytes
     - `10.0 GB` = `10,737,418,240` bytes
     - `auto` = auto-fit to content size + buffer
   - Dynamic partition groups (`qti_dynamic_partitions`, `main`, `google_dynamic_partitions`).
   - Virtual A/B metadata flag and sparse image output for fastboot flashing.

7. **Flashable Package Generation**
   - **Recovery Flashable ZIP**: Standard TWRP / OrangeFox / AOSP recovery installer with slot-aware `update-binary` shell script.
   - **Fastboot Flashable ROM**: Complete flash package containing `flash_all.sh` (Linux/macOS), `flash_all.bat` (Windows), and `flash_all_except_data`.
   - **Payload OTA ZIP**: Official AOSP/Pixel format `payload.bin` generated via `delta_generator`.

8. **Workspace & Inspection Tools**
   - `build.prop` inspector: displays Android OS version, security patch, device codename, and brand.
   - Multi-project storage breakdown: view size and item counts per directory across projects.
   - Cleanup manager: clear individual working directories or reset the active project.

---

## 📁 Directory Layout

```text
/mnt/android-kitchen/autoporter/
├── autoport.py                      # Main executable entrypoint (chmod +x)
├── core/                            # Modular python backend
│   ├── config.py                    # Binary resolver, DynamicPath proxy & size parser
│   ├── project.py                   # Multi-project manager (kebab-case naming)
│   ├── ui.py                        # Terminal UI, spinners, progress bars, tables
│   ├── ota_dumper.py                # Payload & OTA ZIP extraction
│   ├── partition_unpacker.py        # Super, EROFS, EXT4, and Boot unpacker
│   ├── partition_repacker.py        # EROFS / EXT4 / Boot repacker
│   ├── super_builder.py             # Super.img builder with binary byte math
│   ├── ota_builder.py               # Recovery ZIP, Fastboot ROM & Payload builder
│   ├── context_sync.py              # SELinux and fs_config synchronizer
│   └── workspace.py                 # Status inspector & cleanup manager
├── bin/                             # Portable prebuilt binaries (Linux x86_64)
│   ├── payload-dumper-go, imgkit, lpmake, lpunpack, mkfs.erofs, extract.erofs,
│   ├── fsck.erofs, mke2fs, e2fsdroid, magiskboot, simg2img, img2simg, cpio, delta_generator...
└── project/                         # Multi-project directory
    └── <project-name-in-kebab-case>/
        ├── project.json             # Project metadata (device, android version, notes)
        ├── input/                   # Place incoming OTA ZIPs, payload.bin, or raw images
        ├── images/                  # Extracted partition images (.img)
        ├── cauldron/                # Unpacked working filesystem trees for editing
        │   └── config/              # Extracted & synthesized fs_config & file_contexts
        ├── finalized/               # Repacked partition images ready for packaging
        └── output/                  # Output super.img, recovery ZIPs, and fastboot ROMs
```

---

## 🚀 Quickstart

### Launch Interactive CLI
Execute directly from the project directory:
```bash
cd /mnt/android-kitchen/autoporter
./autoport.py
```

### Scripting & Project Management CLI
Autoporter supports direct command-line commands and multi-project targeting:
```bash
# List all ROM projects
./autoport.py project --list

# Switch or create a project
./autoport.py project hyperos-chenfeng
./autoport.py project lineage-21 --create

# View workspace status for the active project
./autoport.py status

# Run commands targeting a specific project with -P / --project
./autoport.py -P hyperos-chenfeng status
./autoport.py -P hyperos-chenfeng unpack-ota input/miui_update.zip
./autoport.py -P hyperos-chenfeng build-super --size 8.5GB --group qti_dynamic_partitions
```

---

## 🔒 Context & Symlink Integrity

Autoporter guarantees non-root portability on standard Linux systems:
1. Filesystem unpacking extracts the original `fs_config` (UID, GID, mode, capabilities) and `file_contexts` (SELinux labels) into `project/<name>/cauldron/config/`.
2. When repacking, `imgkit` / `mkfs.erofs` / `e2fsdroid` applies the exact permissions and labels to the newly built image.
3. Newly added files are detected by `context_sync.py` and given appropriate Android contexts and permissions automatically, avoiding bootloops.

