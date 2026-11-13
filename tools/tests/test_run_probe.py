# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the parts of run_probe.py that don't need the game."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run_probe  # noqa: E402

ORIGINAL = (b"[GeneralSettings]\r\nContainerSize=512 ;comment\r\nSearchItemOnTop=0\r\n\r\n"
            b"[OrderSettings]\r\n1=LoadOrderAsc\r\n2=LoadOrderDesc\r\n3=PluginNameAsc\r\n4=PluginNameDesc\r\n"
            b";3=commented out\r\n\r\n[ExclusionPlugins]\r\nAddItemMenuSE.esp=1\r\n")


class VariantIniTest(unittest.TestCase):
    def test_default_variant_keeps_the_file_byte_for_byte(self):
        self.assertEqual(run_probe.variant_ini(ORIGINAL, {}), ORIGINAL)

    def test_set_replaces_values_and_adds_keys(self):
        data = run_probe.variant_ini(ORIGINAL, {"set": [["GeneralSettings", "ContainerSize", "50"],
                                                         ["ExclusionPlugins", "AIMTest_Edge.esp", "1"]]})
        self.assertIn(b"ContainerSize=50\r\n", data)
        self.assertIn(b"AddItemMenuSE.esp=1\r\nAIMTest_Edge.esp=1\r\n", data)
        self.assertIn(b"SearchItemOnTop=0\r\n", data)

    def test_remove_drops_only_that_section_s_keys(self):
        data = run_probe.variant_ini(ORIGINAL, run_probe.VARIANTS["two-orders"])
        self.assertIn(b"1=LoadOrderAsc\r\n2=LoadOrderDesc\r\n;3=commented out\r\n", data)
        self.assertNotIn(b"3=PluginNameAsc", data)
        self.assertNotIn(b"4=PluginNameDesc", data)

    def test_every_variant_is_well_formed(self):
        for name, variant in run_probe.VARIANTS.items():
            self.assertLessEqual(set(variant), {"set", "remove", "delete", "skyrim_ini"}, name)
            run_probe.variant_ini(ORIGINAL, variant)

    def test_probe_ini_names_the_output(self):
        text = run_probe.probe_ini(Path("D:/runs/x/probe.jsonl"))
        self.assertIn("[Probe]\nOutput=D:/runs/x/probe.jsonl\n", text)
        self.assertIn("Quit=1", text)

    def test_probe_ini_refuses_a_relative_output(self):
        # The game would resolve it against its own folder.
        with self.assertRaises(run_probe.RunError):
            run_probe.probe_ini(Path("testdata/runs/x/probe.jsonl"))

    def test_file_sha256(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "AIMTest_Edge.esp"
            path.write_bytes(b"abc")
            self.assertEqual(run_probe.file_sha256(path),
                             "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
            self.assertIsNone(run_probe.file_sha256(Path(folder) / "missing.esp"))


if __name__ == "__main__":
    unittest.main()
