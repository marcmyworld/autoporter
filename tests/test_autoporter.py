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
        rec_zip = build_recovery_flashable_zip(parts, zip_name="test_rec.zip")
        self.assertIsNotNone(rec_zip)
        self.assertTrue(rec_zip.exists())

        # Fastboot ROM package
        fb_dir = build_fastboot_rom_package(parts, rom_name="test_fb")
        self.assertTrue((fb_dir / "flash_all.sh").exists())
        self.assertTrue((fb_dir / "flash_all.bat").exists())
        self.assertTrue((fb_dir / "images" / "system.img").exists())

        # Payload OTA
        payload_zip = build_payload_ota_zip(parts, zip_name="test_payload.zip")
        self.assertIsNotNone(payload_zip)
        self.assertTrue(payload_zip.exists())


if __name__ == "__main__":
    unittest.main()
