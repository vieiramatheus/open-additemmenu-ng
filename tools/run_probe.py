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
            result = self.play(output)
        finally:
            self.collect_logs(folder)
            self.clean_up()
        result.update(self.summarize(output))
        result["variant"] = name
        result["setup"] = setup
        return result

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

    def play(self, output: Path, no_output_after: float = 240, give_up_after: float = 600) -> dict:
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
    args = parser.parse_args(argv)
    if args.list:
        for name, variant in VARIANTS.items():
            print(f"{name:30} {json.dumps(variant)}")
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
