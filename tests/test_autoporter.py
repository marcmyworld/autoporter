#!/usr/bin/env python3
"""
Autoporter End-to-End Test Suite:
Validates binary size calculations, EROFS unpack/repack with contexts,
EXT4 unpack/repack, boot.img unpack/repack, super.img generation, and OTA packages.
"""

import sys
import shutil
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from core.config import parse_size_bytes, format_size, detect_file_type, get_binary
from core.partition_unpacker import unpack_filesystem_image, unpack_boot_image
from core.partition_repacker import repack_filesystem_partition, repack_boot_partition
from core.super_builder import build_super_image, compute_super_size
from core.ota_builder import build_payload_ota_zip, build_recovery_flashable_zip, build_fastboot_rom_package
from core.context_sync import sync_partition_contexts


class TestAutoporter(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path("/tmp/autoporter_test_env")
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.cauldron = self.test_dir / "cauldron"
        self.finalized = self.test_dir / "finalized"
        self.output = self.test_dir / "output"
        self.cauldron.mkdir(parents=True, exist_ok=True)
        self.finalized.mkdir(parents=True, exist_ok=True)
        self.output.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_binary_size_calculations(self):
        """Test exact binary system calculation: 8.5 GB = 9126805504 bytes."""
        expected_8_5gb = int(8.5 * (1024 ** 3))
        self.assertEqual(expected_8_5gb, 9126805504)
        self.assertEqual(parse_size_bytes("8.5 GB"), 9126805504)
        self.assertEqual(parse_size_bytes("8.5GB"), 9126805504)
        self.assertEqual(parse_size_bytes("8.5G"), 9126805504)
        self.assertEqual(parse_size_bytes("8.5GiB"), 9126805504)
        self.assertEqual(parse_size_bytes("9G"), 9663676416)
        self.assertEqual(parse_size_bytes("500MB"), 524288000)
        self.assertEqual(parse_size_bytes("9126805504"), 9126805504)

    def test_range_selection_parsing(self):
        """Test 1-15,18-20 range selection, mixed numbers, and names."""
        from core.ui import parse_range_selection
        dummy_names = [f"part_{i}" for i in range(1, 26)]  # 25 partitions

        # Test 1-15, 18-20
        indices = parse_range_selection("1-15, 18-20", len(dummy_names), dummy_names)
        expected = list(range(0, 15)) + [17, 18, 19]
        self.assertEqual(indices, expected)

        # Test 1, 3, 5-8
        indices_mixed = parse_range_selection("1, 3, 5-8", len(dummy_names), dummy_names)
        self.assertEqual(indices_mixed, [0, 2, 4, 5, 6, 7])

        # Test names and mixed ranges
        indices_named = parse_range_selection("1-2, part_5, part_10", len(dummy_names), dummy_names)
        self.assertEqual(indices_named, [0, 1, 4, 9])

        # Test 'all'
        self.assertEqual(len(parse_range_selection("all", len(dummy_names))), 25)

    def test_erofs_unpack_repack_with_contexts(self):
        """Test end-to-end EROFS creation, unpacking to cauldron, context sync, and repacking."""
        # 1. Create a dummy filesystem structure
        source_dir = self.test_dir / "system_tree"
        (source_dir / "bin").mkdir(parents=True, exist_ok=True)
        (source_dir / "etc").mkdir(parents=True, exist_ok=True)
        (source_dir / "bin" / "sh").write_text("#!/bin/sh\necho test\n")
        (source_dir / "etc" / "sample.conf").write_text("setting=true\n")

        # 2. Pack initial erofs image
        imgkit_tool = get_binary("imgkit")
        initial_img = self.test_dir / "system.img"
        import subprocess
        res = subprocess.run([
            imgkit_tool, "pack", "--type", "erofs",
            "-s", str(source_dir),
            "-o", str(initial_img),
            "-m", "/system",
            "--label", "system"
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertTrue(initial_img.exists())

        # 3. Unpack into cauldron
        success = unpack_filesystem_image(initial_img, cauldron_dir=self.cauldron)
        self.assertTrue(success)
        self.assertTrue((self.cauldron / "system").is_dir())
        self.assertTrue((self.cauldron / "system" / "bin" / "sh").is_file())

        # 4. Modify files and add new file
        (self.cauldron / "system" / "bin" / "my_custom_script.sh").write_text("#!/bin/sh\necho modded\n")

        # 5. Repack partition
        part_info = {
            "name": "system",
            "path": self.cauldron / "system",
            "type": "erofs",
            "meta": {"original_size": initial_img.stat().st_size},
            "dir_size": 4096,
        }
        repack_success = repack_filesystem_partition(
            part_info,
            fs_type="erofs",
            compress_algo="lz4hc",
            compress_level=9,
            output_dir=self.finalized,
        )
        self.assertTrue(repack_success)
        final_img = self.finalized / "system.img"
        self.assertTrue(final_img.exists())
        self.assertGreater(final_img.stat().st_size, 0)

    def test_ext4_repack(self):
        """Test EXT4 packing with customized size."""
        source_dir = self.test_dir / "vendor_tree"
        (source_dir / "etc").mkdir(parents=True, exist_ok=True)
        (source_dir / "etc" / "vendor.conf").write_text("vendor=test\n")

        part_info = {
            "name": "vendor",
            "path": source_dir,
            "type": "ext4",
            "meta": {"original_size": 10485760},
            "dir_size": 2048,
        }
        repack_success = repack_filesystem_partition(
            part_info,
            fs_type="ext4",
            custom_size_bytes=33554432,  # 32MB
            output_dir=self.finalized,
        )
        self.assertTrue(repack_success)
        vendor_img = self.finalized / "vendor.img"
        self.assertTrue(vendor_img.exists())
        self.assertEqual(vendor_img.stat().st_size, 33554432)

    def test_boot_image_unpack_repack(self):
        """Test boot.img unpacking with magiskboot and repacking."""
        real_boot = Path("/mnt/android-kitchen/lunaris/out/target/product/chenfeng/boot.img")
        if not real_boot.exists():
            return
        
        # Copy to test env
        test_boot = self.test_dir / "boot.img"
        shutil.copy2(real_boot, test_boot)

        # Unpack to cauldron
        success = unpack_boot_image(test_boot, cauldron_dir=self.cauldron)
        self.assertTrue(success)
        self.assertTrue((self.cauldron / "boot" / "kernel").exists())
        self.assertTrue((self.cauldron / "boot" / "header").exists())

        # Repack
        part_info = {
            "name": "boot",
            "path": self.cauldron / "boot",
            "type": "boot_image",
            "meta": {"original_file": str(test_boot), "original_size": test_boot.stat().st_size},
            "dir_size": 1024,
        }
        repack_success = repack_boot_partition(part_info, output_dir=self.finalized)
        self.assertTrue(repack_success)
        self.assertTrue((self.finalized / "boot.img").exists())
        self.assertGreater((self.finalized / "boot.img").stat().st_size, 0)

    def test_super_builder(self):
        """Test super.img generation with binary size 9126805504 bytes."""
        # Create dummy partition images
        p1 = self.finalized / "system.img"
        p2 = self.finalized / "vendor.img"
        if not p1.exists():
            with open(p1, "wb") as f:
                f.write(b"\x00" * (10 * 1024 * 1024))
        if not p2.exists():
            with open(p2, "wb") as f:
                f.write(b"\x00" * (5 * 1024 * 1024))

        parts = [
            {"path": p1, "size": p1.stat().st_size},
            {"path": p2, "size": p2.stat().st_size},
        ]

        super_out = self.output / "super.img"
        success = build_super_image(
            partitions=parts,
            device_size=9126805504,  # 8.5 GB
            group_name="qti_dynamic_partitions",
            is_sparse=True,
            is_vab=True,
            output_path=super_out,
        )
        self.assertTrue(success)
        self.assertTrue(super_out.exists())
        self.assertGreater(super_out.stat().st_size, 0)

    def test_ota_and_fastboot_builders(self):
        """Test Fastboot ROM generation, Recovery ZIP, and Payload OTA."""
        p1 = self.finalized / "boot.img"
        p2 = self.finalized / "system.img"
        if not p1.exists():
            with open(p1, "wb") as f:
                f.write(b"\x00" * (2 * 1024 * 1024))
        if not p2.exists():
            with open(p2, "wb") as f:
                f.write(b"\x00" * (2 * 1024 * 1024))

        parts = [
            {"path": p1, "size": p1.stat().st_size},
            {"path": p2, "size": p2.stat().st_size},
        ]

        # Recovery ZIP
        rec_zip = build_recovery_flashable_zip(parts, zip_name="test_rec.zip", output_dir=self.output)
        self.assertIsNotNone(rec_zip)
        self.assertTrue(rec_zip.exists())

        # Fastboot ROM package
        fb_dir = build_fastboot_rom_package(parts, rom_name="test_fb", output_dir=self.output)
        self.assertTrue((fb_dir / "flash_all.sh").exists())
        self.assertTrue((fb_dir / "flash_all.bat").exists())
        self.assertTrue((fb_dir / "images" / "system.img").exists())

        # Payload OTA
        payload_zip = build_payload_ota_zip(parts, zip_name="test_payload.zip", output_dir=self.output)
        self.assertIsNotNone(payload_zip)
        self.assertTrue(payload_zip.exists())

    def test_rom_zip_partition_selection_and_super_unpack(self):
        """Test ROM.zip containing images/ with selective extraction and automated super.img unpacking."""
        import zipfile
        from core.ota_dumper import inspect_archive, extract_zip_selected_images
        from core.partition_unpacker import unpack_super_image

        # 1. Create a minimal valid super.img
        super_parts_dir = self.test_dir / "super_parts"
        super_parts_dir.mkdir(parents=True, exist_ok=True)
        sys_img = super_parts_dir / "system.img"
        ven_img = super_parts_dir / "vendor.img"
        with open(sys_img, "wb") as f:
            f.write(b"\x00" * (5 * 1024 * 1024))
        with open(ven_img, "wb") as f:
            f.write(b"\x00" * (5 * 1024 * 1024))

        super_file = self.test_dir / "super.img"
        build_super_image(
            partitions=[{"path": sys_img, "size": sys_img.stat().st_size}, {"path": ven_img, "size": ven_img.stat().st_size}],
            device_size=33554432,  # 32MB
            group_name="qti_dynamic_partitions",
            is_sparse=False,
            is_vab=False,
            output_path=super_file,
        )
        self.assertTrue(super_file.exists())

        # 2. Package into a fastboot ROM.zip with images/ structure
        rom_zip = self.test_dir / "fastboot_rom.zip"
        with zipfile.ZipFile(rom_zip, "w") as zf:
            zf.writestr("images/boot.img", b"BOOT_DUMMY_DATA")
            zf.writestr("images/vbmeta.img", b"VBMETA_DUMMY_DATA")
            zf.write(super_file, "images/super.img")

        # 3. Inspect archive
        info = inspect_archive(rom_zip)
        self.assertEqual(info["type"], "zip_images")
        self.assertTrue(info["has_super"])
        self.assertIn("boot", info["partitions"])
        self.assertIn("super", info["partitions"])
        self.assertIn("vbmeta", info["partitions"])

        # 4. Selective extraction (extract only super and boot)
        entries_to_extract = [e for e in info["image_entries"] if e["partition_name"] in ["super", "boot"]]
        self.assertEqual(len(entries_to_extract), 2)

        out_img_dir = self.test_dir / "extracted_images"
        out_img_dir.mkdir(parents=True, exist_ok=True)
        extracted = extract_zip_selected_images(rom_zip, entries_to_extract, output_dir=out_img_dir)
        self.assertEqual(len(extracted), 2)
        self.assertTrue((out_img_dir / "super.img").exists())
        self.assertTrue((out_img_dir / "boot.img").exists())
        self.assertFalse((out_img_dir / "vbmeta.img").exists())  # was not selected

        # 5. Unpack extracted super.img
        unpacked_logical = unpack_super_image(out_img_dir / "super.img", output_dir=out_img_dir)
        self.assertGreater(len(unpacked_logical), 0)
        logical_names = [p.stem for p in unpacked_logical]
        self.assertIn("system", logical_names)
        self.assertIn("vendor", logical_names)
        self.assertTrue((out_img_dir / "system.img").exists())
        self.assertTrue((out_img_dir / "vendor.img").exists())

    def test_kebab_case_conversion(self):
        """Test conversion of arbitrary project names to clean kebab-case."""
        from core.project import to_kebab_case
        self.assertEqual(to_kebab_case("HyperOS Chenfeng"), "hyperos-chenfeng")
        self.assertEqual(to_kebab_case("Xiaomi 14 Civi (SM8635)"), "xiaomi-14-civi-sm8635")
        self.assertEqual(to_kebab_case("My_Awesome_ROM"), "my-awesome-rom")
        self.assertEqual(to_kebab_case("LineageOS-21.0!"), "lineageos-21-0")
        self.assertEqual(to_kebab_case("   Spaces Around   "), "spaces-around")
        self.assertEqual(to_kebab_case(""), "unnamed-project")

    def test_project_manager_and_dynamic_paths(self):
        """Test multi-project isolation, switching, and DynamicPath lazy resolution."""
        from core.project import ProjectManager, get_active_project
        from core.config import IMAGES_DIR, CAULDRON_DIR, FINALIZED_DIR, OUTPUT_DIR, INPUT_DIR

        orig_active = get_active_project()
        test_p1_name = "test-kitchen-alpha"
        test_p2_name = "test-kitchen-beta"

        try:
            # Create project 1
            p1 = ProjectManager.create_project(test_p1_name, display_name="Test Kitchen Alpha", device="alpha_dev")
            self.assertTrue(p1.exists())
            self.assertTrue(p1.input_dir.exists())
            self.assertTrue(p1.images_dir.exists())
            self.assertTrue(p1.cauldron_dir.exists())
            self.assertTrue(p1.config_dir.exists())
            self.assertTrue(p1.finalized_dir.exists())
            self.assertTrue(p1.output_dir.exists())
            self.assertTrue(p1.meta_file.exists())
            self.assertEqual(p1.get_meta()["device"], "alpha_dev")

            # Check DynamicPath points to p1
            self.assertEqual(str(IMAGES_DIR), str(p1.images_dir))
            self.assertEqual(str(CAULDRON_DIR), str(p1.cauldron_dir))

            # Create project 2
            p2 = ProjectManager.create_project(test_p2_name, display_name="Test Kitchen Beta", device="beta_dev")
            self.assertTrue(p2.exists())

            # Active project should now be p2
            self.assertEqual(ProjectManager.get_active_project().name, test_p2_name)
            self.assertEqual(str(IMAGES_DIR), str(p2.images_dir))
            self.assertEqual(str(OUTPUT_DIR), str(p2.output_dir))

            # Switch back to p1
            ProjectManager.set_active_project(p1)
            self.assertEqual(ProjectManager.get_active_project().name, test_p1_name)
            self.assertEqual(str(IMAGES_DIR), str(p1.images_dir))

            # Test overview
            ov = p1.get_overview()
            self.assertEqual(ov["name"], test_p1_name)
            self.assertIn("total_size", ov)

        finally:
            # Clean up test projects
            ProjectManager.delete_project(test_p1_name)
            ProjectManager.delete_project(test_p2_name)
            if orig_active:
                ProjectManager.set_active_project(orig_active)

    def test_parted_image_matching_and_recombination(self):
        """Test detection, numerical sorting, and recombination of parted image chunks."""
        from core.partition_unpacker import match_parted_image, merge_parted_chunks

        # 1. Test pattern matching
        self.assertEqual(match_parted_image("super.img.0"), ("super", 0))
        self.assertEqual(match_parted_image("super.img.13"), ("super", 13))
        self.assertEqual(match_parted_image("images/super.img.9"), ("super", 9))
        self.assertEqual(match_parted_image("super.img.sparsechunk.1"), ("super", 1))
        self.assertEqual(match_parted_image("system.img_sparsechunk.0"), ("system", 0))
        self.assertEqual(match_parted_image("super_sparsechunk.2"), ("super", 2))
        self.assertEqual(match_parted_image("super_sparsechunk3"), ("super", 3))
        self.assertEqual(match_parted_image("super_0.img"), ("super", 0))
        self.assertEqual(match_parted_image("super-1.img"), ("super", 1))
        self.assertEqual(match_parted_image("super.0"), ("super", 0))

        # Test non-parted images rejection
        self.assertIsNone(match_parted_image("boot.img"))
        self.assertIsNone(match_parted_image("vendor_boot.img"))
        self.assertIsNone(match_parted_image("system.img"))
        self.assertIsNone(match_parted_image("payload.bin"))
        self.assertIsNone(match_parted_image("firmware.txt"))

        # 2. Test multi-chunk numerical sorting and binary recombination
        chunk_dir = self.test_dir / "test_chunks"
        chunk_dir.mkdir(parents=True, exist_ok=True)
        chunk_files = []
        expected_content = b""

        # Create chunks 0 to 12
        for idx in range(13):
            cf = chunk_dir / f"super.img.{idx}"
            chunk_data = f"CHUNK_{idx:02d}_DATA_".encode("ascii") * 100
            cf.write_bytes(chunk_data)
            chunk_files.append(cf)
            expected_content += chunk_data

        # Pass chunks in reverse order to ensure numeric sorting takes precedence
        reversed_chunks = list(reversed(chunk_files))
        merged_output = self.test_dir / "merged_super.img"
        res = merge_parted_chunks(reversed_chunks, merged_output)

        self.assertIsNotNone(res)
        self.assertTrue(merged_output.exists())
        self.assertEqual(merged_output.read_bytes(), expected_content)
        self.assertEqual(merged_output.stat().st_size, len(expected_content))

    def test_parted_super_rom_zip_inspection_and_extraction(self):
        """Test inspect_archive and extract_zip_selected_images with parted super ROM zip."""
        import zipfile
        from core.ota_dumper import inspect_archive, extract_zip_selected_images

        # Create mock ROM.zip with parted super chunks: super.img.0 ... super.img.4 and boot.img
        zip_path = self.test_dir / "parted_rom.zip"
        expected_super_data = b""

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("images/boot.img", b"BOOT_PARTITION_DATA" * 50)
            zf.writestr("images/vendor_boot.img", b"VENDOR_BOOT_DATA" * 50)
            for i in range(5):
                c_data = f"PARTED_SUPER_CHUNK_{i}_".encode("ascii") * 100
                expected_super_data += c_data
                zf.writestr(f"images/super.img.{i}", c_data)

        # 1. Test inspect_archive
        info = inspect_archive(zip_path)
        self.assertEqual(info["type"], "zip_images")
        self.assertTrue(info["has_super"])
        self.assertIn("super", info["partitions"])
        self.assertIn("boot", info["partitions"])
        self.assertIn("vendor_boot", info["partitions"])

        # Super should be unified into a single entry with is_parted=True
        super_entry = next((e for e in info["image_entries"] if e["partition_name"] == "super"), None)
        self.assertIsNotNone(super_entry)
        self.assertTrue(super_entry["is_parted"])
        self.assertEqual(len(super_entry["chunks"]), 5)
        self.assertEqual(super_entry["file_size"], len(expected_super_data))

        # 2. Test extraction of parted super + boot
        out_images = self.test_dir / "extracted_parted"
        extracted = extract_zip_selected_images(zip_path, [super_entry], output_dir=out_images)

        self.assertEqual(len(extracted), 1)
        merged_super = out_images / "super.img"
        self.assertTrue(merged_super.exists())
        self.assertEqual(merged_super.read_bytes(), expected_super_data)


if __name__ == "__main__":
    unittest.main()


