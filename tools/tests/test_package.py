# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for package.py, with a made-up build folder; no compiler or game is needed."""

import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import package  # noqa: E402


class PackageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="package-test-"))
        self.build = self.tmp / "build"
        self.build.mkdir()
        (self.build / "AddItemMenuSE.dll").write_bytes(b"dll")
        (self.build / "AddItemMenuSE.pdb").write_bytes(b"pdb")
        self.folder = self.tmp / "out" / "staged"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_release_name_and_numbers(self):
        name = package.release_name()
        self.assertRegex(name, r"^\d+\.\d+\.\d+")
        self.assertEqual(package.numeric_version("1.0.0-beta-release"), "1.0.0")
        self.assertEqual(package.numeric_version("2.3.4"), "2.3.4")

    def test_staged_layout(self):
        package.stage(self.build, self.folder, "1.2.3-test")
        for path in ("fomod/info.xml", "fomod/ModuleConfig.xml", "SKSE/Plugins/AddItemMenuSE.dll",
                     "Optional/SKSE/Plugins/AddItemMenuSE.pdb", "README.txt", "LICENSE.txt", "EXCEPTIONS.md",
                     "KNOWN-DIFFERENCES.md"):
            self.assertTrue((self.folder / path).is_file(), path)
        info = ElementTree.parse(self.folder / "fomod" / "info.xml").getroot()
        version = info.find("Version")
        self.assertEqual((version.text, version.get("MachineVersion")), ("1.2.3-test", "1.2.3"))
        self.assertIn("Version 1.2.3-test", (self.folder / "README.txt").read_text(encoding="utf-8"))
        self.assertNotIn("@", (self.folder / "fomod" / "ModuleConfig.xml").read_text(encoding="utf-8"))

    def test_the_installer_names_only_files_the_archive_has(self):
        package.stage(self.build, self.folder, "1.2.3-test")
        installed = package.check_fomod(self.folder)
        self.assertIn(r"SKSE\Plugins\AddItemMenuSE.dll", installed)
        (self.folder / "Optional" / "SKSE" / "Plugins" / "AddItemMenuSE.pdb").unlink()
        with self.assertRaises(package.PackageError):
            package.check_fomod(self.folder)

    def test_a_missing_build_file_stops_packaging(self):
        (self.build / "AddItemMenuSE.pdb").unlink()
        with self.assertRaises(package.PackageError):
            package.stage(self.build, self.folder, "1.2.3-test")

    def test_zip_archive(self):
        package.stage(self.build, self.folder, "1.2.3-test")
        archive = package.make_archive(self.folder, self.tmp / "out" / "Test-1.2.3-beta-release", seven_zip=None)
        self.assertEqual(archive.name, "Test-1.2.3-beta-release.zip")
        with zipfile.ZipFile(archive) as opened:
            names = set(opened.namelist())
        self.assertIn("SKSE/Plugins/AddItemMenuSE.dll", names)
        self.assertIn("fomod/ModuleConfig.xml", names)

    @unittest.skipUnless(sys.platform == "win32", "reads Windows version resources")
    def test_product_version(self):
        self.assertIsNone(package.product_version(self.build / "AddItemMenuSE.dll"), "no version resource")
        self.assertIsNone(package.product_version(self.build / "missing.dll"))
        version = package.product_version(Path(sys.executable))
        self.assertTrue(version is None or isinstance(version, str))


if __name__ == "__main__":
    unittest.main()
