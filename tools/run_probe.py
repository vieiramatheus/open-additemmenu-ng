#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run AIMProbe in a test installation, once per settings variant.

For each variant this script:
  1. writes the variant's AddItemMenuSE.ini, starting from the one installed, and keeps a copy
     with the results;
  2. puts it in place with deploy.py (package 'probe-variant'; language changes go in
     'probe-variant-skyrim-ini'), together with AIMProbe.ini (package 'aimprobe-config');
  3. starts the game through skse64_loader.exe and waits for the probe to quit it, closing the
     game if it hangs;
  4. copies the probe's output and the game's logs into <out>/<variant>/;
  5. uninstalls the variant again.
After each variant it updates <out>/runs.json, one entry per variant, with the SHA-256 of the
AddItemMenuSE.dll that answered and of the test plugins (AIMTest_*.esp) installed.

Before starting a Skyrim 1.6 game it deletes %LOCALAPPDATA%/Skyrim Special Edition/ContentCatalog.txt
if Skyrim 1.7 wrote it: 1.6 crashes at startup reading that format. The file is only the game's
cache of Creations, rebuilt when the Creations menu opens; a copy goes into the variant's folder.

AIMProbe.dll (package 'aimprobe', see the deploy-probe build target) must already be installed.
The game must not be running, and the deploy record must be in order.

  run_probe.py --state testdata/deploy/skyrim-1.5.97 --out testdata/golden/1.5.97-original
  run_probe.py --state ... --out ... --variant default --variant no-ini
  run_probe.py --list
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import deploy  # noqa: E402

AIM_INI = "game:Data/SKSE/Plugins/AddItemMenuSE.ini"
PROBE_INI = "game:Data/SKSE/Plugins/AIMProbe.ini"
VARIANT_PACKAGE = "probe-variant"
SKYRIM_INI_PACKAGE = "probe-variant-skyrim-ini"
CONFIG_PACKAGE = "aimprobe-config"

# The settings and language variants. 'set' and 'remove' edit AddItemMenuSE.ini; 'delete' hides
# files; 'skyrim_ini' sets values in the global Skyrim.ini.
VARIANTS: dict[str, dict] = {
    "default": {},
    "itemtypes-parts50-searchtop": {"set": [["GeneralSettings", "AllPluginUseItemTypeMenu", "1"],
                                            ["GeneralSettings", "ContainerSize", "50"],
                                            ["GeneralSettings", "SearchItemOnTop", "1"]]},
    "checkresources-0": {"set": [["GeneralSettings", "CheckResourceFiles", "0"]]},
    "checkresources-3": {"set": [["GeneralSettings", "CheckResourceFiles", "3"]]},
    "checkresources-1": {"set": [["GeneralSettings", "CheckResourceFiles", "1"]]},
    "checkresources-3-ignore-missingmodel": {"set": [["GeneralSettings", "CheckResourceFiles", "3"],
                                                     ["IgnoreCheckResourcePlugins", "AIMTest_MissingModel.esp", "1"]]},
    "exclude-edge-plugin": {"set": [["ExclusionPlugins", "AIMTest_Edge.esp", "1"]]},
    "lazy-index": {"set": [["GeneralSettings", "CreateItemDataBeforeMainMenu", "0"]]},
    "two-orders": {"remove": [["OrderSettings", "3"], ["OrderSettings", "4"]]},
    "no-ini": {"delete": [AIM_INI]},
    "russian": {"skyrim_ini": [["General", "sLanguage", "RUSSIAN"]]},
    "no-translation": {"delete": ["game:Data/Interface/translations/AddItemMenuSE_english.txt"]},
    # Item names with accented letters from the game's own string files. AddItemMenu ships no
    # French translation, so its labels stay untranslated.
    "french": {"skyrim_ini": [["General", "sLanguage", "FRENCH"]]},
}


class RunError(Exception):
    pass


def remove_ini_key(data: bytes, section: str, key: str) -> bytes:
    """The INI text without the 'key=...' lines of one section."""
    lines, newline, bom = deploy.split_lines(data)
    out, current = [], None
    for line in lines:
        match = deploy.SECTION.match(line)
        if match:
            current = match.group(1).strip().lower()
        elif current == section.lower() and "=" in line and not line.strip().startswith((";", "#")):
            if line.split("=", 1)[0].strip().lower() == key.lower():
                continue
        out.append(line)
    return deploy.join_lines(out, newline, bom)


def variant_ini(original: bytes, variant: dict) -> bytes:
    data = original
    if variant.get("set"):
        data = deploy.edit_ini(data, variant["set"])
    for section, key in variant.get("remove", []):
        data = remove_ini_key(data, section, key)
    return data


def file_sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def exe_version(path: Path) -> tuple[int, int, int, int] | None:
    """An executable's file version, such as (1, 6, 1170, 0); None when it can't be read."""
    if sys.platform != "win32" or not path.is_file():
        return None
    import ctypes
    from ctypes import wintypes

    api = ctypes.WinDLL("version")
    api.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, wintypes.LPDWORD]
    api.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    api.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
                                   ctypes.POINTER(wintypes.UINT)]
    size = api.GetFileVersionInfoSizeW(str(path), None)
    buffer = ctypes.create_string_buffer(size) if size else None
    if not buffer or not api.GetFileVersionInfoW(str(path), 0, size, buffer):
        return None
    info, length = ctypes.c_void_p(), wintypes.UINT()
    if not api.VerQueryValueW(buffer, "\\", ctypes.byref(info), ctypes.byref(length)) or length.value < 16:
        return None
    # VS_FIXEDFILEINFO starts with its signature, its structure version, then the file version.
    fields = ctypes.cast(info, ctypes.POINTER(ctypes.c_uint32 * 4)).contents
    high, low = fields[2], fields[3]
    return (high >> 16, high & 0xFFFF, low >> 16, low & 0xFFFF)


# Creations catalog entries as Skyrim 1.7 writes them ("CSV2_" plus a GUID). Skyrim 1.6 can't read
# that catalog and crashes at startup (it parses some versions as numbers, and 1.7 writes
# placeholders there); 1.5.97 doesn't read the file at all.
NEW_CATALOG = re.compile(rb'"CSV2_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"\s*:', re.I)


def remove_incompatible_catalog(appdata: Path, version: tuple | None, keep: Path | None = None) -> bool:
    """Before a Skyrim 1.6 game starts, deletes a ContentCatalog.txt that 1.7 wrote. The file is only
    the game's cache of Creations and Creation Club content, rebuilt when the Creations menu opens.
    A copy goes to `keep`. True if the file was deleted."""
    if not version or version[:2] != (1, 6):
        return False
    catalog = appdata / "ContentCatalog.txt"
    try:
        data = catalog.read_bytes()
    except FileNotFoundError:
        return False
    if not NEW_CATALOG.search(data):
        return False
    if keep is not None:
        keep.parent.mkdir(parents=True, exist_ok=True)
        keep.write_bytes(data)
    catalog.unlink()
    return True


def probe_ini(output: Path) -> str:
    # The probe runs inside the game, whose working folder is the game folder: a relative path
    # would put the results there, outside the deploy record.
    if not output.is_absolute():
        raise RunError(f"the probe's output path must be absolute: {output}")
    return "\n".join([
        "; Written by run_probe.py for one run.",
        "[Probe]",
        f"Output={output.as_posix()}",
        "Cell=Aim",
        "Quit=1",
        "Clipboard=1",
        "",
    ])


class Runner:
    def __init__(self, state: Path, out: Path, out_print=print):
        self.state = state.resolve()
        self.out = out.resolve()
        self.print = out_print
        self.record = deploy.Deployer(state)
        self.game = self.record.roots["game"]
        self.mygames = self.record.roots["mygames"]

    def deploy(self, *args: str) -> None:
        lines: list[str] = []
        code = deploy.main(["--state", str(self.state), *args], out=lines.append)
        if code != 0:
            raise RunError("deploy.py " + " ".join(args) + " failed:\n" + "\n".join(lines))

    def installed(self) -> set[str]:
        return {p["name"] for p in deploy.Deployer(self.state).m["packages"]}

    def check_ready(self) -> None:
        if deploy.process_ids_under(self.game):
            raise RunError("the game is running; close it first")
        packages = self.installed()
        if "aimprobe" not in packages:
            raise RunError("AIMProbe.dll isn't installed (build the deploy-probe target)")
        leftovers = packages & {VARIANT_PACKAGE, SKYRIM_INI_PACKAGE, CONFIG_PACKAGE}
        if leftovers:
            raise RunError("packages left from an earlier run: " + ", ".join(sorted(leftovers)) +
                           " (uninstall them with deploy.py first)")

    def clean_up(self) -> None:
        for package in (CONFIG_PACKAGE, SKYRIM_INI_PACKAGE, VARIANT_PACKAGE):
            if package in self.installed():
                self.deploy("uninstall", package)

    def run(self, name: str, variant: dict) -> dict:
        folder = self.out / name
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        output = folder / "probe.jsonl"
        try:
            self.apply(name, variant, folder)
            (folder / "AIMProbe.ini").write_text(probe_ini(output), encoding="utf-8")
            self.deploy("swap", CONFIG_PACKAGE, "--file", str(folder / "AIMProbe.ini"), PROBE_INI,
                        "--note", f"probe run: {name}")
            setup = self.setup()
            catalog_removed = self.clean_catalog(folder / "ContentCatalog.removed.txt")
            result = self.play(output)
        finally:
            self.collect_logs(folder)
            self.clean_up()
        result.update(self.summarize(output))
        result["variant"] = name
        result["setup"] = setup
        if catalog_removed:
            result["catalogRemoved"] = True
        return result

    def clean_catalog(self, keep: Path) -> bool:
        removed = remove_incompatible_catalog(self.record.roots["appdata"], exe_version(self.game / "SkyrimSE.exe"), keep)
        if removed:
            self.print(f"           removed ContentCatalog.txt, which Skyrim 1.6 can't read (copy: {keep})")
        return removed

    def setup(self) -> dict:
        """What a run's results depend on besides its settings: the AddItemMenuSE.dll that answered
        and the test plugins. Results compare only when the test plugins are the same."""
        data = self.game / "Data"
        return {
            "dll": file_sha256(data / "SKSE" / "Plugins" / "AddItemMenuSE.dll"),
            "testPlugins": {path.name: file_sha256(path) for path in sorted(data.glob("AIMTest_*.esp"))},
        }

    def apply(self, name: str, variant: dict, folder: Path) -> None:
        files = []
        if variant.get("set") or variant.get("remove"):
            installed = self.record.disk_path(AIM_INI)
            if not installed.is_file():
                raise RunError(f"{installed} isn't installed")
            (folder / "AddItemMenuSE.ini").write_bytes(variant_ini(installed.read_bytes(), variant))
            files = ["--file", str(folder / "AddItemMenuSE.ini"), AIM_INI]
        deletes = [arg for target in variant.get("delete", []) for arg in ("--delete", target)]
        if files or deletes:
            self.deploy("swap", VARIANT_PACKAGE, *files, *deletes, "--note", f"probe variant: {name}")
        settings = [arg for s, k, v in variant.get("skyrim_ini", []) for arg in ("--set", "mygames:Skyrim.ini", s, k, v)]
        if settings:
            self.deploy("ini", SKYRIM_INI_PACKAGE, *settings, "--note", f"probe variant: {name}")

    # A cold start of an AE copy (caches still empty) took over four minutes before the probe wrote
    # anything, so the limits are generous; a warm start takes about half a minute.
    def play(self, output: Path, no_output_after: float = 480, give_up_after: float = 900) -> dict:
        started = time.monotonic()
        subprocess.Popen([str(self.game / "skse64_loader.exe")], cwd=self.game)
        while not deploy.process_ids_under(self.game):
            if time.monotonic() - started > 120:
                return {"outcome": "the game never started", "seconds": round(time.monotonic() - started)}
            time.sleep(1)
        outcome = "quit by the probe"
        while deploy.process_ids_under(self.game):
            elapsed = time.monotonic() - started
            if not output.exists() and elapsed > no_output_after:
                outcome = "closed: no probe output"
                self.close_game()
                break
            if elapsed > give_up_after:
                outcome = "closed: still running"
                self.close_game()
                break
            time.sleep(1)
        return {"outcome": outcome, "seconds": round(time.monotonic() - started)}

    def close_game(self) -> None:
        for force in (False, True):
            for pid, _ in deploy.process_ids_under(self.game):
                subprocess.run(["taskkill", *(["/F"] if force else []), "/PID", str(pid)],
                               capture_output=True, check=False)
            deadline = time.monotonic() + 30
            while deploy.process_ids_under(self.game) and time.monotonic() < deadline:
                time.sleep(1)
            if not deploy.process_ids_under(self.game):
                return

    def collect_logs(self, folder: Path) -> None:
        # Only these two folders of My Games: other tools keep their own folders there.
        for sub, pattern in (("SKSE", "*.log"), ("Logs/Script", "Papyrus.0.log")):
            for log in (self.mygames / sub).glob(pattern):
                shutil.copy2(log, folder / log.name)

    @staticmethod
    def summarize(output: Path) -> dict:
        if not output.exists():
            return {"lines": 0, "done": None, "calls": 0}
        lines = output.read_text(encoding="utf-8").splitlines()
        last = json.loads(lines[-1]) if lines else {}
        calls = sum(1 for line in lines if '"ret":' in line)
        return {"lines": len(lines), "done": last.get("done"), "calls": calls}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state", type=Path, help="deploy.py state folder of the test installation")
    parser.add_argument("--out", type=Path, help="folder for the results, one subfolder per variant")
    parser.add_argument("--variant", action="append", default=[], help="run only these variants (repeatable)")
    parser.add_argument("--list", action="store_true", help="list the variants and exit")
    parser.add_argument("--clean-catalog", action="store_true",
                        help="only delete a ContentCatalog.txt the installed game can't read, then exit "
                             "(before starting a Skyrim 1.6 game by hand; a copy goes to <state>/removed/)")
    args = parser.parse_args(argv)
    if args.list:
        for name, variant in VARIANTS.items():
            print(f"{name:30} {json.dumps(variant)}")
        return 0
    if args.clean_catalog:
        if not args.state:
            parser.error("--clean-catalog needs --state")
        try:
            record = deploy.Deployer(args.state)
        except deploy.DeployError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        keep = args.state.resolve() / "removed" / f"ContentCatalog-{datetime.datetime.now():%Y%m%d-%H%M%S}.txt"
        version = exe_version(record.roots["game"] / "SkyrimSE.exe")
        removed = remove_incompatible_catalog(record.roots["appdata"], version, keep)
        print(f"removed ContentCatalog.txt (copy: {keep})" if removed else "nothing to remove")
        return 0
    if not args.state or not args.out:
        parser.error("--state and --out are required")
    names = args.variant or list(VARIANTS)
    unknown = [n for n in names if n not in VARIANTS]
    if unknown:
        parser.error("unknown variants: " + ", ".join(unknown))
    try:
        args.out = args.out.resolve()
        runner = Runner(args.state, args.out)
        runner.check_ready()
        args.out.mkdir(parents=True, exist_ok=True)
        results = []
        for name in names:
            print(f"{datetime.datetime.now():%H:%M:%S} {name} ...", flush=True)
            result = runner.run(name, VARIANTS[name])
            results.append(result)
            print(f"           {result['outcome']}, {result['seconds']} s, {result['calls']} calls, "
                  f"done={result['done']}, dll {str(result['setup']['dll'])[:12]}", flush=True)
            summary = args.out / "runs.json"
            previous = json.loads(summary.read_text(encoding="utf-8")) if summary.exists() else {}
            previous[name] = {**result, "finished": f"{datetime.datetime.now():%Y-%m-%dT%H:%M:%S}"}
            summary.write_text(json.dumps(previous, indent=1), encoding="utf-8")
    except (RunError, deploy.DeployError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0 if all(r["done"] == "done" for r in results) else 3


if __name__ == "__main__":
    raise SystemExit(main())
