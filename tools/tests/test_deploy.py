"""Tests for deploy.py. They work in temporary folders; no game is needed."""

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import deploy  # noqa: E402


class DeployTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="deploy-test-"))
        self.game = self.tmp / "game"
        (self.game / "Data").mkdir(parents=True)
        self.mygames = self.tmp / "mygames"
        self.mygames.mkdir()
        self.appdata = self.tmp / "appdata"
        self.appdata.mkdir()
        self.state = self.tmp / "state"
        self.cli("init", "--game", str(self.game), "--mygames", str(self.mygames), "--appdata", str(self.appdata))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cli(self, *args, ok=True):
        lines = []
        code = deploy.main(["--state", str(self.state), *args], out=lines.append)
        text = "\n".join(lines)
        if ok:
            self.assertEqual(code, 0, text)
        else:
            self.assertNotEqual(code, 0, text)
        return text

    def source(self, rel, content, folder="src"):
        path = self.tmp.joinpath(folder, *rel.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
        return path

    def manifest(self):
        return json.loads((self.state / "manifest.json").read_text(encoding="utf-8"))

    # -- files

    def test_install_and_uninstall_new_files(self):
        self.source("a.esp", "A")
        self.source("Scripts/x.pex", "X")
        self.cli("install", "pkg", "--from", str(self.tmp / "src"))
        self.assertEqual((self.game / "Data/a.esp").read_bytes(), b"A")
        self.assertEqual((self.game / "Data/Scripts/x.pex").read_bytes(), b"X")
        self.cli("uninstall", "pkg")
        self.assertFalse((self.game / "Data/a.esp").exists())
        self.assertFalse((self.game / "Data/Scripts").exists(), "a folder the tool created is removed")
        self.assertTrue((self.game / "Data").is_dir(), "a folder that was already there stays")
        record = self.manifest()
        self.assertEqual((record["packages"], record["paths"], record["created_dirs"]), ([], {}, []))

    def test_a_replaced_file_comes_back(self):
        target = self.game / "Data/Test.txt"
        target.write_bytes(b"vanilla\r\n")
        self.source("Test.txt", "modded")
        self.cli("install", "pkg", "--from", str(self.tmp / "src"))
        self.assertEqual(target.read_bytes(), b"modded")
        self.assertEqual((self.state / "originals/game/Data/Test.txt").read_bytes(), b"vanilla\r\n")
        self.cli("uninstall", "pkg")
        self.assertEqual(target.read_bytes(), b"vanilla\r\n")

    def test_the_later_package_wins_and_uninstalling_unwinds_in_order(self):
        target = self.game / "Data/a.dll"
        target.write_bytes(b"original")
        self.source("a.dll", "A")
        self.cli("install", "first", "--from", str(self.tmp / "src"))
        build = self.source("b.dll", "B", folder="build")
        self.cli("swap", "second", "--file", str(build), "game:Data/a.dll")
        self.assertEqual(target.read_bytes(), b"B")
        self.cli("uninstall", "second")
        self.assertEqual(target.read_bytes(), b"A")
        self.cli("uninstall", "first")
        self.assertEqual(target.read_bytes(), b"original")

    def test_removing_a_covered_package_leaves_the_top_one(self):
        target = self.game / "Data/a.dll"
        target.write_bytes(b"original")
        self.source("a.dll", "A")
        self.cli("install", "first", "--from", str(self.tmp / "src"))
        build = self.source("b.dll", "B", folder="build")
        self.cli("swap", "second", "--file", str(build), "game:Data/a.dll")
        self.cli("uninstall", "first")
        self.assertEqual(target.read_bytes(), b"B")
        self.cli("uninstall", "second")
        self.assertEqual(target.read_bytes(), b"original")

    def test_reinstall_replaces_the_file_list_and_add_extends_it(self):
        self.source("x.txt", "x")
        self.source("y.txt", "y")
        self.cli("install", "pkg", "--from", str(self.tmp / "src"))
        (self.tmp / "src/y.txt").unlink()
        self.cli("install", "pkg", "--from", str(self.tmp / "src"))
        self.assertTrue((self.game / "Data/x.txt").exists())
        self.assertFalse((self.game / "Data/y.txt").exists())
        self.source("z.txt", "z", folder="more")
        self.cli("install", "pkg", "--add", "--from", str(self.tmp / "more"))
        self.assertTrue((self.game / "Data/x.txt").exists())
        self.assertTrue((self.game / "Data/z.txt").exists())

    def test_reinstall_keeps_its_place_below_later_packages(self):
        self.source("f.txt", "A1")
        self.cli("install", "low", "--from", str(self.tmp / "src"))
        top = self.source("t.txt", "T", folder="top")
        self.cli("swap", "high", "--file", str(top), "game:Data/f.txt")
        self.source("f.txt", "A2")
        self.cli("install", "low", "--from", str(self.tmp / "src"))
        self.assertEqual((self.game / "Data/f.txt").read_bytes(), b"T")
        self.cli("uninstall", "high")
        self.assertEqual((self.game / "Data/f.txt").read_bytes(), b"A2")

    def test_swap_delete_hides_a_file_until_uninstalled(self):
        ccc = self.game / "Skyrim.ccc"
        ccc.write_bytes(b"list")
        self.cli("swap", "hide", "--delete", "game:Skyrim.ccc")
        self.assertFalse(ccc.exists())
        self.cli("uninstall", "hide")
        self.assertEqual(ccc.read_bytes(), b"list")

    def test_include_and_exclude_patterns(self):
        for rel in ("a.dll", "b.exe", "readme.txt", "src/c.dll", "Data/Scripts/x.pex", "Data/Scripts/Source/x.psc"):
            self.source(rel, rel)
        self.cli("install", "tool", "--from", str(self.tmp / "src"), "--to", "game:",
                 "--include", "*.dll", "--include", "*.EXE")
        self.cli("install", "tool", "--add", "--from", str(self.tmp / "src/Data"), "--to", "game:Data",
                 "--include", "Scripts/*.pex")
        present = sorted(p.relative_to(self.game).as_posix() for p in self.game.rglob("*") if p.is_file())
        self.assertEqual(present, ["Data/Scripts/x.pex", "a.dll", "b.exe"])

    def test_paths_ignore_case(self):
        self.source("Interface/translations/A.txt", "a")
        self.cli("install", "low", "--from", str(self.tmp / "src"))
        other = self.source("a.txt", "b", folder="other")
        self.cli("swap", "high", "--file", str(other), "game:data/INTERFACE/Translations/a.TXT")
        self.assertEqual(len(self.manifest()["paths"]), 1)
        target = self.game / "Data/Interface/translations/A.txt"
        self.assertEqual(target.read_bytes(), b"b")
        self.cli("uninstall", "high")
        self.assertEqual(target.read_bytes(), b"a")

    def test_paths_must_stay_inside_their_root(self):
        file = self.source("f.txt", "x")
        self.cli("install", "pkg", "--from", str(self.tmp / "src"), "--to", "game:../outside", ok=False)
        self.cli("install", "pkg", "--from", str(self.tmp / "src"), "--to", "elsewhere:Data", ok=False)
        self.cli("swap", "pkg", "--file", str(file), "game:C:/Windows/x", ok=False)
        self.assertFalse((self.tmp / "outside").exists())

    # -- Plugins.txt and INI files

    def test_plugins_txt_entries_follow_their_packages(self):
        plugins = self.appdata / "Plugins.txt"
        original = b"# header line\n# second line\n"
        plugins.write_bytes(original)
        self.source("UI.esp", "ui", folder="ui")
        self.source("AIM.esp", "aim", folder="aim")
        self.cli("install", "ui", "--from", str(self.tmp / "ui"), "--plugin", "UI.esp")
        self.cli("install", "aim", "--from", str(self.tmp / "aim"), "--plugin", "AIM.esp")
        self.assertEqual(plugins.read_bytes(), original + b"*UI.esp\n*AIM.esp\n")
        self.cli("uninstall", "ui")
        self.assertEqual(plugins.read_bytes(), original + b"*AIM.esp\n")
        self.cli("uninstall", "aim")
        self.assertEqual(plugins.read_bytes(), original)

    def test_plugins_txt_is_created_and_removed_when_it_was_absent(self):
        self.source("A.esp", "a")
        self.cli("install", "a", "--from", str(self.tmp / "src"), "--plugin", "A.esp")
        self.assertEqual((self.appdata / "Plugins.txt").read_bytes(), b"*A.esp\r\n")
        self.cli("uninstall", "a")
        self.assertFalse((self.appdata / "Plugins.txt").exists())

    def test_a_plugin_must_exist(self):
        self.source("A.esp", "a")
        self.cli("install", "a", "--from", str(self.tmp / "src"), "--plugin", "B.esp", ok=False)
        self.assertFalse((self.game / "Data/A.esp").exists())

    def test_ini_settings_and_exact_restore(self):
        ini = self.mygames / "Skyrim.ini"
        original = b"[General]\r\nsLanguage=ENGLISH\r\n\r\n[Display]\r\nfoo=1\r\n"
        ini.write_bytes(original)
        self.cli("ini", "test",
                 "--set", "mygames:Skyrim.ini", "General", "sLanguage", "RUSSIAN",
                 "--set", "mygames:Skyrim.ini", "Papyrus", "bEnableLogging", "1",
                 "--set", "mygames:Skyrim.ini", "display", "bar", "2")
        self.assertEqual(ini.read_bytes(), b"[General]\r\nsLanguage=RUSSIAN\r\n\r\n[Display]\r\nfoo=1\r\nbar=2\r\n"
                                           b"\r\n[Papyrus]\r\nbEnableLogging=1\r\n")
        self.cli("uninstall", "test")
        self.assertEqual(ini.read_bytes(), original)

    def test_an_ini_file_is_created_and_removed_when_it_was_absent(self):
        self.cli("ini", "c", "--set", "mygames:SkyrimCustom.ini", "Papyrus", "bEnableLogging", "1")
        self.assertEqual((self.mygames / "SkyrimCustom.ini").read_bytes(), b"[Papyrus]\r\nbEnableLogging=1\r\n")
        self.cli("uninstall", "c")
        self.assertFalse((self.mygames / "SkyrimCustom.ini").exists())

    def test_ini_edit_on_top_of_an_installed_file(self):
        self.source("SKSE/Plugins/Mod.ini", "[General]\nSize=512 ;comment\n")
        self.cli("install", "mod", "--from", str(self.tmp / "src"))
        self.cli("ini", "variant", "--set", "game:Data/SKSE/Plugins/Mod.ini", "General", "Size", "50")
        target = self.game / "Data/SKSE/Plugins/Mod.ini"
        self.assertEqual(target.read_bytes(), b"[General]\nSize=50\n")
        self.cli("uninstall", "variant")
        self.assertEqual(target.read_bytes(), b"[General]\nSize=512 ;comment\n")

    # -- safety

    def test_files_changed_by_something_else_block_until_forced(self):
        self.source("f.txt", "one")
        self.cli("install", "pkg", "--from", str(self.tmp / "src"))
        (self.game / "Data/f.txt").write_bytes(b"edited by hand")
        self.source("f.txt", "two")
        out = self.cli("install", "pkg", "--from", str(self.tmp / "src"), ok=False)
        self.assertIn("game:Data/f.txt", out)
        self.assertEqual((self.game / "Data/f.txt").read_bytes(), b"edited by hand")
        self.cli("--force", "install", "pkg", "--from", str(self.tmp / "src"))
        self.assertEqual((self.game / "Data/f.txt").read_bytes(), b"two")
        kept = self.state / "store" / hashlib.sha256(b"edited by hand").hexdigest()
        self.assertEqual(kept.read_bytes(), b"edited by hand")

    def test_dry_run_changes_nothing(self):
        self.source("f.txt", "x")
        out = self.cli("--dry-run", "install", "pkg", "--from", str(self.tmp / "src"))
        self.assertIn("(dry run)", out)
        self.assertFalse((self.game / "Data/f.txt").exists())
        self.assertFalse((self.state / "manifest.json").exists())
        self.assertFalse((self.state / "store").exists())

    def test_an_interrupted_run_is_finished_by_sync(self):
        for name in ("a.txt", "b.txt", "c.txt"):
            self.source(name, name)
        real_write = deploy.Deployer.write
        calls = []

        def failing_write(this, *args):
            calls.append(1)
            if len(calls) == 2:
                raise OSError("disk full")
            return real_write(this, *args)

        with mock.patch.object(deploy.Deployer, "write", failing_write):
            self.assertIn("sync", self.cli("install", "pkg", "--from", str(self.tmp / "src"), ok=False))
        self.assertTrue(self.manifest()["pending"])
        self.cli("install", "other", "--from", str(self.tmp / "src"), ok=False)
        self.cli("sync")
        self.assertEqual(self.manifest()["pending"], [])
        for name in ("a.txt", "b.txt", "c.txt"):
            self.assertEqual((self.game / "Data" / name).read_bytes(), name.encode())
        self.assertFalse((self.state / "deploy.lock").exists())

    def test_status_verify_reports_changed_files(self):
        self.source("f.txt", "x")
        self.cli("install", "pkg", "--from", str(self.tmp / "src"))
        self.assertIn("matches", self.cli("status", "--verify"))
        (self.game / "Data/f.txt").write_bytes(b"changed")
        self.assertIn("game:Data/f.txt", self.cli("status", "--verify", ok=False))

    def test_every_change_is_logged(self):
        self.source("f.txt", "x")
        self.cli("install", "pkg", "--from", str(self.tmp / "src"))
        self.cli("uninstall", "pkg")
        log = (self.state / "deploy.log").read_text(encoding="utf-8").splitlines()
        self.assertEqual([line.split("\t")[1:4] for line in log],
                         [["install pkg", "added", "game:Data/f.txt"], ["uninstall pkg", "removed", "game:Data/f.txt"]])


class EditTest(unittest.TestCase):
    def test_plugins_moves_an_existing_line_to_the_end_and_activates_it(self):
        self.assertEqual(deploy.edit_plugins(b"# c\nUI.esp\n*Other.esp\n", ["UI.esp"]),
                         b"# c\n*Other.esp\n*UI.esp\n")

    def test_ini_keeps_the_bom_comments_and_key_spelling(self):
        bom = "\ufeff".encode("utf-8")
        data = bom + b"; comment\n[General]\nSLanguage=ENGLISH\n"
        self.assertEqual(deploy.edit_ini(data, [["general", "slanguage", "RUSSIAN"]]),
                         bom + b"; comment\n[General]\nSLanguage=RUSSIAN\n")

    def test_star_stays_in_one_folder(self):
        self.assertTrue(deploy.glob_regex("Scripts/*.pex").fullmatch("scripts/A.PEX"))
        self.assertFalse(deploy.glob_regex("Scripts/*.pex").fullmatch("Scripts/Source/A.pex"))
        self.assertTrue(deploy.glob_regex("**/*.pex").fullmatch("Scripts/Source/A.pex"))
        self.assertTrue(deploy.glob_regex("**/*.pex").fullmatch("A.pex"))


if __name__ == "__main__":
    unittest.main()
