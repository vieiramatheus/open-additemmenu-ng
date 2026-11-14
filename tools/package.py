#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the release archive: a FOMOD installer with AddItemMenuSE.dll and, as an option, its PDB.

  package.py --build D:/Builds/open-additemmenu-ng/release --out D:/Builds/open-additemmenu-ng/dist

The release name comes from vcpkg.json ("version-semver", such as 1.0.0-beta-release). Before
anything is packed, the built DLL's file properties must carry the same name (CMakeLists.txt puts
it there), so an archive never holds an older DLL under a newer name.

Archive layout:
  fomod/info.xml, fomod/ModuleConfig.xml   the installer, from packaging/fomod, version filled in
  SKSE/Plugins/AddItemMenuSE.dll           always installed
  Optional/SKSE/Plugins/AddItemMenuSE.pdb  installed when the player picks the debug symbols
  README.txt, LICENSE.txt, EXCEPTIONS.md, KNOWN-DIFFERENCES.md
                                           to read in the archive; the installer leaves them out

The archive is a .7z when 7-Zip is installed, otherwise a .zip.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ARCHIVE_STEM = "OpenAddItemMenuNG"
SEVEN_ZIP = (Path(r"C:\Program Files\7-Zip\7z.exe"), Path(r"C:\Program Files (x86)\7-Zip\7z.exe"))


class PackageError(Exception):
    pass


def release_name(repo: Path = REPO) -> str:
    """The release's name, such as 1.0.0-beta-release, from vcpkg.json."""
    manifest = json.loads((repo / "vcpkg.json").read_text(encoding="utf-8"))
    name = manifest.get("version-semver", "")
    if not re.fullmatch(r"\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?", name):
        raise PackageError(f"vcpkg.json has no usable version-semver: {name!r}")
    return name


def numeric_version(name: str) -> str:
    """1.0.0-beta-release -> 1.0.0"""
    return name.split("-", 1)[0]


def product_version(path: Path) -> str | None:
    """The ProductVersion string of a Windows executable's version resource; None if it has none."""
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
    # The first language and code page the resource lists, then that block's ProductVersion.
    table, length = ctypes.c_void_p(), wintypes.UINT()
    if not api.VerQueryValueW(buffer, r"\VarFileInfo\Translation", ctypes.byref(table), ctypes.byref(length)) or length.value < 4:
        return None
    language, codepage = ctypes.cast(table, ctypes.POINTER(ctypes.c_uint16 * 2)).contents
    value = ctypes.c_void_p()
    key = rf"\StringFileInfo\{language:04X}{codepage:04X}\ProductVersion"
    if not api.VerQueryValueW(buffer, key, ctypes.byref(value), ctypes.byref(length)) or not length.value:
        return None
    return ctypes.wstring_at(value, length.value).rstrip("\0")


def fill(template: Path, target: Path, name: str) -> None:
    text = template.read_text(encoding="utf-8")
    text = text.replace("@VERSION@", name).replace("@MACHINE_VERSION@", numeric_version(name))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def stage(build: Path, folder: Path, name: str, repo: Path = REPO) -> None:
    """Puts every file of the archive in place under `folder`."""
    if folder.exists():
        shutil.rmtree(folder)
    packaging = repo / "packaging"
    fill(packaging / "fomod" / "info.xml", folder / "fomod" / "info.xml", name)
    fill(packaging / "fomod" / "ModuleConfig.xml", folder / "fomod" / "ModuleConfig.xml", name)
    fill(packaging / "README.txt", folder / "README.txt", name)
    copies = {
        build / "AddItemMenuSE.dll": folder / "SKSE" / "Plugins" / "AddItemMenuSE.dll",
        build / "AddItemMenuSE.pdb": folder / "Optional" / "SKSE" / "Plugins" / "AddItemMenuSE.pdb",
        repo / "LICENSE": folder / "LICENSE.txt",
        repo / "EXCEPTIONS.md": folder / "EXCEPTIONS.md",
        repo / "tests" / "known-differences.md": folder / "KNOWN-DIFFERENCES.md",
    }
    for source, target in copies.items():
        if not source.is_file():
            raise PackageError(f"missing: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def check_fomod(folder: Path) -> list[str]:
    """Every file the installer names must be in the archive. Returns those files."""
    ElementTree.parse(folder / "fomod" / "info.xml")
    config = ElementTree.parse(folder / "fomod" / "ModuleConfig.xml").getroot()
    sources = [element.get("source", "") for element in config.iter() if element.tag in ("file", "folder")]
    if not sources:
        raise PackageError("ModuleConfig.xml installs nothing")
    missing = [source for source in sources if not (folder / source.replace("\\", "/")).exists()]
    if missing:
        raise PackageError("ModuleConfig.xml names files the archive lacks: " + ", ".join(missing))
    return sources


def make_archive(folder: Path, target_stem: Path, seven_zip: Path | None) -> Path:
    # Not with_suffix(): in "...-1.0.0-beta-release" it would take ".0-beta-release" for an extension.
    files = sorted(path for path in folder.rglob("*") if path.is_file())
    if seven_zip:
        target = target_stem.parent / (target_stem.name + ".7z")
        target.unlink(missing_ok=True)
        relative = [str(path.relative_to(folder)) for path in files]
        subprocess.run([str(seven_zip), "a", "-t7z", "-mx=9", "-bso0", "-bsp0", str(target), *relative],
                       cwd=folder, check=True)
        return target
    target = target_stem.parent / (target_stem.name + ".zip")
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, path.relative_to(folder).as_posix())
    return target


def find_seven_zip() -> Path | None:
    found = shutil.which("7z")
    if found:
        return Path(found)
    return next((path for path in SEVEN_ZIP if path.is_file()), None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--build", required=True, type=Path, help="the build folder holding AddItemMenuSE.dll and .pdb")
    parser.add_argument("--out", required=True, type=Path, help="where to write the archive (outside the repository)")
    parser.add_argument("--zip", action="store_true", help="write a .zip even when 7-Zip is installed")
    args = parser.parse_args(argv)
    try:
        name = release_name()
        built = product_version(args.build / "AddItemMenuSE.dll")
        if built != name:
            raise PackageError(f"AddItemMenuSE.dll says {built!r}, vcpkg.json says {name!r}: "
                               "rebuild, or make CMakeLists.txt and vcpkg.json agree")
        folder = args.out.resolve() / f"{ARCHIVE_STEM}-{name}"
        stage(args.build, folder, name)
        installed = check_fomod(folder)
        archive = make_archive(folder, args.out.resolve() / f"{ARCHIVE_STEM}-{name}",
                               None if args.zip else find_seven_zip())
    except (PackageError, OSError, ElementTree.ParseError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    print(f"{archive}\n  {archive.stat().st_size:,} bytes, sha256 {digest}")
    print("  installs: " + ", ".join(installed))
    print(f"  staged in {folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
