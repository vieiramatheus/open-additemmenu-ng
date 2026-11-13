#!/usr/bin/env python3
"""Install, swap and uninstall files in a Skyrim test installation, keeping a full record.

Everything this tool knows lives in a state folder outside the game (--state):

  target.json    the folders this state manages
  manifest.json  the installed packages, and every path they touch
  originals/     untouched copies of files as they were before their first change
  store/         the content of every installed file, named by its SHA-256
  deploy.log     one line per change, appended

Files are installed in named packages, kept in install order. When two packages touch the
same path, the later one wins; uninstalling it brings back what was below it, down to the
original file. Plugins.txt entries and INI settings are recorded the same way, as edits, so
uninstalling the last package that touches a file restores that file byte for byte.

Paths are written ROOT:relative/path, with these roots:
  game     the game folder (SkyrimSE.exe, Data)
  mygames  Documents/My Games/Skyrim Special Edition (INI files, saves, SKSE logs)
  appdata  %LOCALAPPDATA%/Skyrim Special Edition (Plugins.txt)

Patterns for --include and --exclude match paths relative to --from, ignoring case.
'*' and '?' stay inside one folder; '**' crosses folders.

Examples:
  deploy.py --state S init --game "D:/Games/Skyrim Special Edition"
  deploy.py --state S install skse --from stage/skse --to game: --include "*.dll" --include "*.exe"
  deploy.py --state S install skse --add --from stage/skse/Data --to game:Data --include "Scripts/*.pex"
  deploy.py --state S install uiextensions --from stage/uiextensions --plugin UIExtensions.esp
  deploy.py --state S swap my-build --file build/MyPlugin.dll game:Data/SKSE/Plugins/MyPlugin.dll
  deploy.py --state S swap no-ccc --delete game:Skyrim.ccc
  deploy.py --state S ini papyrus-log --set mygames:Skyrim.ini Papyrus bEnableLogging 1
  deploy.py --state S uninstall my-build
  deploy.py --state S status --verify
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import stat
from collections import Counter
from pathlib import Path

FORMAT = 1
ROOTS = ("game", "mygames", "appdata")
FOLDER_NAME = "Skyrim Special Edition"
PLUGINS_FILE = "appdata:Plugins.txt"
PLUGIN_SUFFIXES = (".esp", ".esm", ".esl")
NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
NEWLINE = re.compile(r"\r\n|\n|\r")
SECTION = re.compile(r"\s*\[([^\]]*)\]")
BOM = "\xef\xbb\xbf"  # a UTF-8 byte-order mark, as latin-1 decodes it
CHUNK = 1 << 20


class DeployError(Exception):
    """A problem to fix before trying again."""


def now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------------------
# Paths, patterns and hashes


def parse_target(spec: str) -> tuple[str, str]:
    """Split 'root:relative/path' into the root and a clean relative path."""
    if ":" not in spec:
        raise DeployError(f"'{spec}' must start with a root: " + ", ".join(r + ":" for r in ROOTS))
    root, rel = spec.split(":", 1)
    root = root.strip().lower()
    if root not in ROOTS:
        raise DeployError(f"'{spec}' has an unknown root '{root}'; use " + ", ".join(ROOTS))
    parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
    if any(p == ".." or ":" in p for p in parts):
        raise DeployError(f"'{spec}' must stay inside its root")
    return root, "/".join(parts)


def file_target(spec: str) -> str:
    """A 'root:path' naming a file, in clean form."""
    root, rel = parse_target(spec)
    if not rel:
        raise DeployError(f"'{spec}' names a root folder, not a file")
    return f"{root}:{rel}"


def key_of(display: str) -> str:
    """Windows ignores case in paths, so the record does too."""
    return display.lower()


def glob_regex(pattern: str) -> re.Pattern[str]:
    parts = []
    p = pattern.replace("\\", "/").strip("/")
    i = 0
    while i < len(p):
        if p.startswith("**/", i):
            parts.append("(?:.*/)?")
            i += 3
        elif p.startswith("**", i):
            parts.append(".*")
            i += 2
        elif p[i] == "*":
            parts.append("[^/]*")
            i += 1
        elif p[i] == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(p[i]))
            i += 1
    return re.compile("".join(parts), re.IGNORECASE | re.DOTALL)


def collect(src: Path, include: list[str], exclude: list[str]) -> list[str]:
    """Relative paths of the files under src that pass the patterns, sorted."""
    wanted = [glob_regex(g) for g in include]
    skipped = [glob_regex(g) for g in exclude]
    found = []
    for folder, subfolders, files in os.walk(src):
        subfolders.sort()
        for name in sorted(files):
            rel = Path(folder, name).relative_to(src).as_posix()
            if wanted and not any(r.fullmatch(rel) for r in wanted):
                continue
            if any(r.fullmatch(rel) for r in skipped):
                continue
            found.append(rel)
    return found


def hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def brief(state: dict) -> dict:
    return {"exists": True, "sha256": state["sha256"]} if state["exists"] else {"exists": False}


def same(a: dict, b: dict) -> bool:
    if a["exists"] != b["exists"]:
        return False
    return not a["exists"] or a["sha256"] == b["sha256"]


def make_writable(path: Path) -> None:
    try:
        mode = path.stat().st_mode
        if not mode & stat.S_IWRITE:
            os.chmod(path, mode | stat.S_IWRITE)
    except FileNotFoundError:
        pass


def merge_names(old: list[str], new: list[str]) -> list[str]:
    merged = list(old)
    seen = {name.lower() for name in merged}
    for name in new:
        if name.lower() not in seen:
            merged.append(name)
            seen.add(name.lower())
    return merged


def merge_settings(old: list[list[str]], new: list[list[str]]) -> list[list[str]]:
    merged: dict[tuple[str, str], list[str]] = {}
    for section, key, value in list(old) + list(new):
        merged[(section.lower(), key.lower())] = [section, key, value]
    return list(merged.values())


# ---------------------------------------------------------------------------------------
# Edits to text files. latin-1 maps every byte to one character, so whatever is not
# edited is written back exactly as it was read.


def split_lines(data: bytes | None) -> tuple[list[str], str, str]:
    """The lines of a text file, its newline style and its byte-order mark."""
    text = (data or b"").decode("latin-1")
    bom = BOM if text.startswith(BOM) else ""
    text = text[len(bom):]
    found = NEWLINE.search(text)
    newline = found.group(0) if found else "\r\n"
    lines = NEWLINE.split(text)
    if lines and lines[-1] == "":
        lines.pop()
    return lines, newline, bom


def join_lines(lines: list[str], newline: str, bom: str) -> bytes:
    return (bom + "".join(line + newline for line in lines)).encode("latin-1")


def edit_plugins(data: bytes | None, enable: list[str]) -> bytes:
    """Plugins.txt with each plugin active ('*name'), at the end and in the given order."""
    lines, newline, bom = split_lines(data)
    for name in enable:
        wanted = name.lower()
        lines = [line for line in lines
                 if line.lstrip().startswith("#") or line.strip().lstrip("*").strip().lower() != wanted]
        lines.append("*" + name)
    return join_lines(lines, newline, bom)


def edit_ini(data: bytes | None, settings: list[list[str]]) -> bytes:
    """An INI file with each [section] key=value set and everything else left alone."""
    lines, newline, bom = split_lines(data)
    for section, key, value in settings:
        start = next((i for i, line in enumerate(lines)
                      if (m := SECTION.match(line)) and m.group(1).strip().lower() == section.lower()), None)
        if start is None:
            if lines and lines[-1].strip():
                lines.append("")
            lines += [f"[{section}]", f"{key}={value}"]
            continue
        end = next((i for i in range(start + 1, len(lines)) if SECTION.match(lines[i])), len(lines))
        for i in range(start + 1, end):
            body = lines[i].strip()
            if not body or body[0] in ";#" or "=" not in body:
                continue
            name = lines[i].split("=", 1)[0]
            if name.strip().lower() == key.lower():
                lines[i] = f"{name}={value}"
                break
        else:
            at = end
            while at > start + 1 and not lines[at - 1].strip():
                at -= 1
            lines.insert(at, f"{key}={value}")
    return join_lines(lines, newline, bom)


# ---------------------------------------------------------------------------------------
# Windows helpers


def documents_folder() -> Path:
    """The user's Documents folder, wherever Windows has it."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

            documents = GUID(0xFDD39AD0, 0x238F, 0x46AF,
                             (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
            result = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(documents), 0, None,
                                                          ctypes.byref(result)) == 0:
                try:
                    return Path(result.value)
                finally:
                    ctypes.windll.ole32.CoTaskMemFree(result)
        except (OSError, AttributeError):
            pass
    return Path.home() / "Documents"


def processes_under(folder: Path) -> list[str]:
    """Running programs whose executable lives inside folder, described for a message."""
    return [f"{path} (process {pid})" for pid, path in process_ids_under(folder)]


def process_ids_under(folder: Path) -> list[tuple[int, str]]:
    """(process ID, executable path) of the running programs whose executable lives inside folder."""
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        psapi = ctypes.WinDLL("psapi")
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        pids = (wintypes.DWORD * 8192)()
        needed = wintypes.DWORD()
        if not psapi.EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(needed)):
            return []
        base = os.path.normcase(os.path.abspath(folder)) + os.sep
        found = []
        for pid in pids[: needed.value // ctypes.sizeof(wintypes.DWORD)]:
            handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                continue
            try:
                name = ctypes.create_unicode_buffer(32768)
                size = wintypes.DWORD(len(name))
                if kernel32.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)):
                    if os.path.normcase(name.value).startswith(base):
                        found.append((int(pid), name.value))
            finally:
                kernel32.CloseHandle(handle)
        return found
    except (OSError, AttributeError):
        return []


# ---------------------------------------------------------------------------------------
# The record


class Deployer:
    """The record for one game installation, and the operations that change it."""

    def __init__(self, state, *, dry_run=False, force=False, verbose=False, out=print, command=""):
        self.dir = Path(state)
        self.dry_run = dry_run
        self.force = force
        self.verbose = verbose
        self.out = out
        self.command = command
        self.events: list[tuple[str, str, str]] = []
        self.sources: dict[str, Path] = {}
        self.locked = False
        target_file = self.dir / "target.json"
        if not target_file.is_file():
            raise DeployError(f"{self.dir} is not set up; run 'init' first")
        roots = json.loads(target_file.read_text(encoding="utf-8"))["roots"]
        self.roots = {root: Path(roots[root]) for root in ROOTS}
        manifest = self.dir / "manifest.json"
        if manifest.is_file():
            self.m = json.loads(manifest.read_text(encoding="utf-8"))
            if self.m.get("format") != FORMAT:
                raise DeployError(f"{manifest} was written by an unknown version of this tool")
        else:
            self.m = {"format": FORMAT, "packages": [], "paths": {}, "created_dirs": [], "pending": []}

    def __enter__(self):
        if not self.dry_run:
            lock = self.dir / "deploy.lock"
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                raise DeployError(f"{lock} exists: another run is going on, or one crashed "
                                  "(then delete the file)") from None
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            self.locked = True
        return self

    def __exit__(self, *exc):
        if self.locked:
            (self.dir / "deploy.lock").unlink(missing_ok=True)
            self.locked = False
        return False

    # -- lookups

    def package(self, name: str) -> dict | None:
        return next((p for p in self.m["packages"] if p["name"] == name), None)

    def stack(self, key: str) -> list[dict]:
        """The packages touching a path, lowest first; the last one wins."""
        return [p for p in self.m["packages"] if key in p["files"]]

    def disk_path(self, display: str) -> Path:
        root, rel = display.split(":", 1)
        base = self.roots[root]
        return base.joinpath(*rel.split("/")) if rel else base

    def to_display(self, path: Path) -> str:
        full = os.path.abspath(path)
        for root in ROOTS:
            base = os.path.abspath(self.roots[root])
            if os.path.normcase(full) == os.path.normcase(base):
                return f"{root}:"
            if os.path.normcase(full).startswith(os.path.normcase(base) + os.sep):
                return f"{root}:{Path(os.path.relpath(full, base)).as_posix()}"
        raise DeployError(f"{path} is outside the managed folders")

    def disk_state(self, display: str) -> dict:
        path = self.disk_path(display)
        if path.is_dir():
            raise DeployError(f"{display} is a folder; only files can be managed")
        if not path.exists():
            return {"exists": False}
        sha, size = hash_file(path)
        return {"exists": True, "sha256": sha, "size": size}

    # -- stored content

    def store_file(self, src: Path) -> tuple[str, int]:
        sha, size = hash_file(src)
        self.sources.setdefault(sha, Path(src))
        if not self.dry_run:
            blob = self.dir / "store" / sha
            if not blob.exists():
                blob.parent.mkdir(parents=True, exist_ok=True)
                temp = blob.with_name(sha + ".tmp")
                shutil.copyfile(src, temp)
                if hash_file(temp)[0] != sha:
                    temp.unlink()
                    raise DeployError(f"{src} changed while it was being copied")
                os.replace(temp, blob)
        return sha, size

    def blob_path(self, sha: str) -> Path:
        blob = self.dir / "store" / sha
        if blob.exists():
            return blob
        if sha in self.sources:
            return self.sources[sha]
        raise DeployError(f"stored content {sha} is missing from {self.dir / 'store'}")

    def capture(self, key: str, display: str) -> None:
        """Start managing a path: keep what is there now as its original."""
        path = self.disk_path(display)
        if path.is_dir():
            raise DeployError(f"{display} is a folder; only files can be managed")
        if path.exists():
            sha, size = self.store_file(path)
            copy = "originals/" + display.replace(":", "/", 1)
            if not self.dry_run:
                dest = self.dir.joinpath(*copy.split("/"))
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.blob_path(sha), dest)
            original = {"exists": True, "sha256": sha, "size": size, "copy": copy}
        else:
            original = {"exists": False}
        self.m["paths"][key] = {"display": display, "original": original, "expected": brief(original)}

    # -- changing the package list

    def set_package(self, name: str, ops: dict[str, dict], *, add: bool, note: str | None) -> set[str]:
        if not NAME_PATTERN.fullmatch(name):
            raise DeployError(f"'{name}' is not a usable package name (letters, digits, '.', '_', '-')")
        pkg = self.package(name)
        affected = set(ops)
        if pkg is None:
            pkg = {"name": name, "created": now(), "updated": now(), "files": {}}
            self.m["packages"].append(pkg)
        elif not add:
            affected |= set(pkg["files"])
            pkg["files"] = {}
        for key, op in ops.items():
            old = pkg["files"].get(key)
            if old and old["op"] == op["op"] == "plugins":
                op = dict(op, enable=merge_names(old["enable"], op["enable"]))
            elif old and old["op"] == op["op"] == "ini":
                op = dict(op, set=merge_settings(old["set"], op["set"]))
            pkg["files"][key] = op
            if key not in self.m["paths"]:
                self.capture(key, op["display"])
        pkg["updated"] = now()
        if note is not None:
            pkg["note"] = note
        if not pkg["files"]:
            self.m["packages"].remove(pkg)
        return affected

    def remove_packages(self, names: list[str]) -> set[str]:
        affected: set[str] = set()
        for name in names:
            pkg = self.package(name)
            if pkg is None:
                raise DeployError(f"no package named '{name}'")
            affected |= set(pkg["files"])
            self.m["packages"].remove(pkg)
        return affected

    # -- bringing the disk in line with the record

    def target(self, key: str) -> tuple[dict, bytes | None]:
        """What a path should hold now, and the bytes when an edit produced them."""
        state = dict(self.m["paths"][key]["original"])
        data = None
        for pkg in self.stack(key):
            op = pkg["files"][key]
            kind = op["op"]
            if kind == "put":
                state, data = {"exists": True, "sha256": op["sha256"], "size": op["size"]}, None
            elif kind == "delete":
                state, data = {"exists": False}, None
            elif kind in ("plugins", "ini"):
                if data is None and state["exists"]:
                    data = self.blob_path(state["sha256"]).read_bytes()
                data = edit_plugins(data, op["enable"]) if kind == "plugins" else edit_ini(data, op["set"])
                state = {"exists": True, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
            else:
                raise DeployError(f"package '{pkg['name']}' has an unknown operation '{kind}'")
        return state, data

    def check_changed(self, keys: set[str]) -> None:
        """Stop if something else changed a managed file since this tool last wrote it."""
        changed = []
        for key in sorted(keys):
            entry = self.m["paths"].get(key)
            if entry is None:
                continue
            have = self.disk_state(entry["display"])
            if same(have, entry["expected"]):
                continue
            want, _ = self.target(key)
            if same(have, want):  # written by a run that stopped before saving its record
                entry["expected"] = brief(want)
                continue
            changed.append((entry["display"], have))
        if not changed:
            return
        names = "\n  ".join(display for display, _ in changed)
        if not self.force:
            raise DeployError("changed by something else since they were deployed:\n  " + names +
                              "\nLook at them first; --force overwrites them, keeping a copy in the store.")
        for display, have in changed:
            if have["exists"]:
                self.store_file(self.disk_path(display))
            self.event("overwrote", display, have)

    def make_dirs(self, folder: Path) -> None:
        missing = []
        while not folder.exists():
            missing.append(folder)
            folder = folder.parent
        for path in reversed(missing):
            path.mkdir()
            self.m["created_dirs"].append(self.to_display(path))

    def prune_dirs(self, folder: Path) -> None:
        """Remove folders this tool created, once they are empty."""
        while True:
            try:
                display = self.to_display(folder)
            except DeployError:
                return
            created = next((d for d in self.m["created_dirs"] if d.lower() == display.lower()), None)
            if created is None or not folder.is_dir() or any(folder.iterdir()):
                return
            folder.rmdir()
            self.m["created_dirs"].remove(created)
            folder = folder.parent

    def write(self, display: str, state: dict, data: bytes | None) -> None:
        path = self.disk_path(display)
        if not state["exists"]:
            if path.exists():
                make_writable(path)
                path.unlink()
            self.prune_dirs(path.parent)
            return
        self.make_dirs(path.parent)
        temp = path.with_name(path.name + ".deploy-tmp")
        if data is not None:
            temp.write_bytes(data)
        else:
            shutil.copyfile(self.blob_path(state["sha256"]), temp)
        make_writable(path)
        os.replace(temp, path)

    def apply(self, key: str) -> None:
        entry = self.m["paths"][key]
        display = entry["display"]
        want, data = self.target(key)
        have = self.disk_state(display)
        released = not self.stack(key)
        if not same(have, want):
            if released:
                action = "restored" if want["exists"] else "removed"
            elif not have["exists"]:
                action = "added"
            elif not want["exists"]:
                action = "removed"
            else:
                action = "replaced"
            if not self.dry_run:
                self.write(display, want, data)
            self.event(action, display, want)
        if released:
            del self.m["paths"][key]
        else:
            entry["expected"] = brief(want)

    def commit(self, keys: set[str], what: str) -> None:
        running = processes_under(self.roots["game"])
        if running:
            if not self.dry_run:
                raise DeployError("close the game first; running from its folder:\n  " + "\n  ".join(running))
            self.out("warning: the game is running")
        self.check_changed(keys)
        self.m["pending"] = sorted(keys)
        self.save()
        try:
            for key in sorted(keys):
                if key in self.m["paths"]:
                    self.apply(key)
                self.m["pending"].remove(key)
                self.save()
        except OSError as error:
            raise DeployError(f"{error}\nThe run stopped part way. Fix the cause, then run 'sync'.") from error
        self.report(what)

    # -- output

    def event(self, action: str, display: str, state: dict) -> None:
        detail = f"sha256 {state['sha256']}, {state.get('size', '?')} bytes" if state["exists"] else "absent"
        self.events.append((action, display, detail))
        if not self.dry_run:
            with open(self.dir / "deploy.log", "a", encoding="utf-8") as log:
                log.write(f"{now()}\t{self.command}\t{action}\t{display}\t{detail}\n")

    def report(self, what: str) -> None:
        prefix = "(dry run) " if self.dry_run else ""
        if not self.events:
            self.out(f"{prefix}{what}: nothing to change")
            return
        counts = Counter(action for action, _, _ in self.events)
        self.out(f"{prefix}{what}: " + ", ".join(f"{n} {action}" for action, n in counts.items()))
        listed = self.events
        if not self.verbose and len(self.events) > 20:
            listed = [e for e in self.events if e[0] != "added"]
        for action, display, _ in listed:
            self.out(f"  {action:<9} {display}")
        if len(listed) < len(self.events):
            self.out(f"  ({plural(len(self.events) - len(listed), 'added file')} not listed; "
                     "-v lists them, deploy.log has every change)")

    def save(self) -> None:
        if self.dry_run:
            return
        temp = self.dir / "manifest.json.tmp"
        temp.write_text(json.dumps(self.m, indent=1), encoding="utf-8")
        os.replace(temp, self.dir / "manifest.json")


# ---------------------------------------------------------------------------------------
# Commands


def open_record(args, out, command: str) -> Deployer:
    d = Deployer(args.state, dry_run=args.dry_run, force=args.force, verbose=args.verbose,
                 out=out, command=command)
    if d.m.get("pending") and command != "sync":
        raise DeployError("an earlier run stopped part way; run 'sync' to finish it first")
    return d


def put_op(d: Deployer, source: Path, display: str) -> dict:
    sha, size = d.store_file(source)
    return {"op": "put", "display": display, "sha256": sha, "size": size, "source": str(source)}


def check_plugin(d: Deployer, plugin: str, ops: dict[str, dict]) -> None:
    if any(c in plugin for c in "/\\:") or not plugin.isascii() or not plugin.lower().endswith(PLUGIN_SUFFIXES):
        raise DeployError(f"'{plugin}' is not a plugin file name")
    display = f"game:Data/{plugin}"
    if key_of(display) not in ops and not d.disk_path(display).is_file() and not d.force:
        raise DeployError(f"{plugin} is neither in this package nor in the game's Data folder "
                          "(--force skips this check)")


def cmd_init(args, out) -> int:
    state = Path(args.state)
    game = Path(args.game).absolute()
    if not (game / "Data").is_dir():
        raise DeployError(f"{game} has no Data folder")
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    roots = {
        "game": str(game),
        "mygames": str(Path(args.mygames).absolute() if args.mygames
                       else documents_folder() / "My Games" / FOLDER_NAME),
        "appdata": str(Path(args.appdata).absolute() if args.appdata else local / FOLDER_NAME),
    }
    target_file = state / "target.json"
    if target_file.exists():
        if json.loads(target_file.read_text(encoding="utf-8"))["roots"] == roots:
            out(f"{state} is already set up for these folders")
            return 0
        raise DeployError(f"{target_file} already exists for other folders; use another state folder")
    if args.dry_run:
        out(f"(dry run) would set up {state}")
    else:
        state.mkdir(parents=True, exist_ok=True)
        target_file.write_text(json.dumps({"format": FORMAT, "roots": roots}, indent=1), encoding="utf-8")
        out(f"set up {state}")
    for root in ROOTS:
        note = "" if Path(roots[root]).is_dir() else "  (does not exist yet)"
        out(f"  {root + ':':<9} {roots[root]}{note}")
    return 0


def cmd_install(args, out) -> int:
    root, base = parse_target(args.to)
    if not args.src and not args.plugin:
        raise DeployError("give --from, --plugin, or both")
    files: list[str] = []
    src = Path(args.src) if args.src else None
    if src is not None:
        if not src.is_dir():
            raise DeployError(f"{src} is not a folder")
        files = collect(src, args.include, args.exclude)
        if not files:
            raise DeployError(f"no file in {src} matches")
    with open_record(args, out, f"install {args.name}") as d:
        ops = {}
        for rel in files:
            display = f"{root}:{base}/{rel}" if base else f"{root}:{rel}"
            ops[key_of(display)] = put_op(d, src.joinpath(*rel.split("/")), display)
        for plugin in args.plugin:
            check_plugin(d, plugin, ops)
        if args.plugin:
            ops[key_of(PLUGINS_FILE)] = {"op": "plugins", "display": PLUGINS_FILE,
                                         "enable": merge_names([], args.plugin)}
        d.commit(d.set_package(args.name, ops, add=args.add, note=args.note), d.command)
    return 0


def cmd_swap(args, out) -> int:
    if not args.file and not args.delete:
        raise DeployError("give --file, --delete, or both")
    with open_record(args, out, f"swap {args.name}") as d:
        ops = {}
        for source, target in args.file:
            display = file_target(target)
            if not Path(source).is_file():
                raise DeployError(f"{source} is not a file")
            ops[key_of(display)] = put_op(d, Path(source), display)
        for target in args.delete:
            display = file_target(target)
            ops[key_of(display)] = {"op": "delete", "display": display}
        d.commit(d.set_package(args.name, ops, add=args.add, note=args.note), d.command)
    return 0


def cmd_ini(args, out) -> int:
    ops: dict[str, dict] = {}
    for target, section, key, value in args.set:
        display = file_target(target)
        for text in (section, key, value):
            if not text.isascii() or "\n" in text or "\r" in text:
                raise DeployError(f"'{text}': INI text must be plain ASCII on one line")
        if not section.strip() or "]" in section or not key.strip() or "=" in key:
            raise DeployError(f"[{section}] {key}: not a usable section and key")
        op = ops.setdefault(key_of(display), {"op": "ini", "display": display, "set": []})
        op["set"] = merge_settings(op["set"], [[section.strip(), key.strip(), value]])
    with open_record(args, out, f"ini {args.name}") as d:
        d.commit(d.set_package(args.name, ops, add=args.add, note=args.note), d.command)
    return 0


def cmd_uninstall(args, out) -> int:
    with open_record(args, out, "uninstall") as d:
        names = [p["name"] for p in reversed(d.m["packages"])] if args.all else args.names
        if not names:
            if args.all:
                out("nothing is installed")
                return 0
            raise DeployError("name the packages to uninstall, or use --all")
        d.command = "uninstall " + " ".join(names)
        d.commit(d.remove_packages(names), d.command)
    return 0


def cmd_sync(args, out) -> int:
    with open_record(args, out, "sync") as d:
        d.commit(set(d.m["paths"]) | set(d.m.get("pending", [])), "sync")
    return 0


def cmd_status(args, out) -> int:
    d = Deployer(args.state, out=out)
    out(f"state folder: {d.dir}")
    for root in ROOTS:
        out(f"  {root + ':':<9} {d.roots[root]}")
    if d.m.get("pending"):
        out(f"An earlier run stopped part way ({len(d.m['pending'])} paths left); run 'sync'.")
    if not d.m["packages"]:
        out("No packages installed.")
    else:
        out("Packages, lowest first (a later package wins where two touch the same file):")
        for number, pkg in enumerate(d.m["packages"], 1):
            kinds = Counter(op["op"] for op in pkg["files"].values())
            edits = kinds["plugins"] + kinds["ini"]
            parts = [plural(kinds["put"], "file") if kinds["put"] else "",
                     f"{kinds['delete']} hidden" if kinds["delete"] else "",
                     plural(edits, "edit") if edits else ""]
            what = ", ".join(p for p in parts if p)
            note = f"  {pkg['note']}" if pkg.get("note") else ""
            out(f"  {number:>2}. {pkg['name']:<20} {what:<24} {pkg['updated'].replace('T', ' ')}{note}")
    out(f"Managed paths: {len(d.m['paths'])}; folders created: {len(d.m['created_dirs'])}")
    if not args.verify:
        return 0
    changed = [entry["display"] for _, entry in sorted(d.m["paths"].items())
               if not same(d.disk_state(entry["display"]), entry["expected"])]
    if changed:
        out("Changed by something else:\n  " + "\n  ".join(changed))
        return 1
    out("Every managed path matches the record.")
    return 0


def cmd_show(args, out) -> int:
    d = Deployer(args.state, out=out)
    pkg = d.package(args.name)
    if pkg is None:
        raise DeployError(f"no package named '{args.name}'")
    out(f"{pkg['name']}: installed {pkg['created'].replace('T', ' ')}, updated {pkg['updated'].replace('T', ' ')}")
    if pkg.get("note"):
        out(f"  note: {pkg['note']}")
    for key, op in sorted(pkg["files"].items(), key=lambda item: item[1]["display"].lower()):
        if op["op"] == "put":
            detail = f"{op['size']} bytes, sha256 {op['sha256'][:16]}"
        elif op["op"] == "delete":
            detail = "hidden"
        elif op["op"] == "plugins":
            detail = "activates " + ", ".join(op["enable"])
        else:
            detail = "; ".join(f"[{s}] {k}={v}" for s, k, v in op["set"])
        top = d.stack(key)[-1]["name"]
        under = "" if top == pkg["name"] else f"  (under {top})"
        out(f"  {op['op']:<7} {op['display']}  {detail}{under}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="deploy.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state", default=os.environ.get("DEPLOY_STATE"),
                        help="state folder of one game installation (default: $DEPLOY_STATE)")
    parser.add_argument("--dry-run", action="store_true", help="show what would change, change nothing")
    parser.add_argument("--force", action="store_true",
                        help="go ahead even where something else changed a managed file")
    parser.add_argument("-v", "--verbose", action="store_true", help="list every file that changes")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p = sub.add_parser("init", help="set up a state folder for one game installation")
    p.add_argument("--game", required=True, help="the game folder, the one holding Data")
    p.add_argument("--mygames", help=f"default: Documents/My Games/{FOLDER_NAME}")
    p.add_argument("--appdata", help=f"default: %%LOCALAPPDATA%%/{FOLDER_NAME}")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("install", help="copy a folder's files into place as one package")
    p.add_argument("name")
    p.add_argument("--from", dest="src", help="the folder to copy from")
    p.add_argument("--to", default="game:Data", help="where its files go (default: game:Data)")
    p.add_argument("--include", action="append", default=[], metavar="GLOB",
                   help="copy only matching files (repeatable)")
    p.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                   help="skip matching files (repeatable)")
    p.add_argument("--plugin", action="append", default=[], metavar="FILE",
                   help="also activate this plugin in Plugins.txt (repeatable)")
    p.add_argument("--add", action="store_true", help="add to the package instead of replacing its files")
    p.add_argument("--note", help="a note kept with the package, such as its version and source")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("swap", help="put single files in place of others, or hide files, as one package")
    p.add_argument("name")
    p.add_argument("--file", nargs=2, action="append", default=[], metavar=("SOURCE", "TARGET"),
                   help="put SOURCE at TARGET (repeatable)")
    p.add_argument("--delete", action="append", default=[], metavar="TARGET",
                   help="hide TARGET until the package is uninstalled (repeatable)")
    p.add_argument("--add", action="store_true", help="add to the package instead of replacing it")
    p.add_argument("--note", help="a note kept with the package")
    p.set_defaults(func=cmd_swap)

    p = sub.add_parser("ini", help="set INI values as one package")
    p.add_argument("name")
    p.add_argument("--set", nargs=4, action="append", required=True,
                   metavar=("FILE", "SECTION", "KEY", "VALUE"), help="repeatable")
    p.add_argument("--add", action="store_true", help="add to the package instead of replacing it")
    p.add_argument("--note", help="a note kept with the package")
    p.set_defaults(func=cmd_ini)

    p = sub.add_parser("uninstall", help="remove packages and bring back what they replaced")
    p.add_argument("names", nargs="*")
    p.add_argument("--all", action="store_true", help="remove every package, newest first")
    p.set_defaults(func=cmd_uninstall)

    p = sub.add_parser("status", help="list the packages; --verify also checks the files")
    p.add_argument("--verify", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("show", help="list one package's files")
    p.add_argument("name")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("sync", help="finish a run that stopped part way")
    p.set_defaults(func=cmd_sync)
    return parser


def main(argv: list[str] | None = None, out=print) -> int:
    args = build_parser().parse_args(argv)
    if not args.state:
        out("error: give --state or set DEPLOY_STATE")
        return 2
    try:
        return args.func(args, out) or 0
    except (DeployError, OSError) as error:
        out(f"error: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
