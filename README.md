# open-additemmenu-ng

An open-source replacement for `AddItemMenuSE.dll`, the SKSE plugin of towawot's **AddItemMenu - Ultimate Mod Explorer 1.14**, so that the original mod works again on current Skyrim: Special Edition 1.5.97 and Anniversary Edition 1.6 and 1.7. VR support may follow.

**Status: beta (1.0.0-beta-release).** All 14 functions the mod's scripts call are in place, and one DLL passes the comparison runs on Skyrim SE 1.5.97 and AE 1.6.1170 and 1.7.104. GOG builds and VR should work through the same mechanism but are untested; reports are welcome in the issues.

## How it will work

You keep the original AddItemMenu 1.14 installed, with its plugin, scripts, translations and settings file, and install this mod after it. It replaces only `SKSE/Plugins/AddItemMenuSE.dll`, and reads the same `AddItemMenuSE.ini` settings, so your existing setup keeps working. The original mod's files are not included here and are never redistributed.

It behaves like the original DLL except for a few deliberate differences, listed in [tests/known-differences.md](tests/known-differences.md).

As with the original, the key that copies an item's name in the container (F1 by default) needs SkyUI, because the mod's script reads SkyUI's container menu. Everything else works with or without SkyUI.

## Building

You need:

- **Build Tools for Visual Studio 2022**, with the *Desktop development with C++* workload, including *C++ CMake tools for Windows* and the *vcpkg package manager*;
- **Git**, which vcpkg uses to fetch its package list;
- **Python 3**, for the deploy script.

From Developer PowerShell for VS 2022, in the repository folder:

```
cmake --preset release
cmake --build --preset release
```

Or, from any PowerShell, `tools\build.ps1`, which loads the developer environment first.

The output is `build/release/AddItemMenuSE.dll`, with its PDB. The first build downloads [CommonLibSSE-NG](https://github.com/alandtse/CommonLibSSE-NG) (pinned to one release) and the openvr files it needs, about 100 MB, and compiles it, which takes a few minutes once per build folder. vcpkg installs the libraries listed in `vcpkg.json`. If your MSVC version is the one that built the release's prebuilt library, `-DAIM_COMMONLIB_PREBUILT=ON` links that instead (see `cmake/commonlib.cmake`).

The source is in two parts:

- `src/core/` holds what doesn't need the game: the settings file, the translation files, the text functions, and the list menu's entries and items.
- `src/game/` connects that to Skyrim: the item index, the 14 native functions and the clipboard.

### Release archive

The release name lives in two places that must agree: `project(VERSION ...)` with `AIM_RELEASE_LABEL` in `CMakeLists.txt`, and `version-semver` in `vcpkg.json`. The first gives the DLL its version (SKSE sees the numbers; the file properties show the full name).

After a build, `tools/package.py` makes the archive players install:

```
python -B tools/package.py --build build/release --out <a folder outside the repository>
```

It refuses to pack a DLL whose version differs from `vcpkg.json`. The archive has a FOMOD installer (`packaging/fomod`): the DLL is always installed, and its PDB is an option, for readable crash logs. The archive also holds `packaging/README.txt`, the license files and the known differences. `packaging/nexus-description.bbcode` is the text of the Nexus page.

### Unit tests

`tests/` holds unit tests for `src/core/`, written with [Catch2](https://github.com/catchorg/Catch2), which vcpkg installs through the manifest's `tests` feature. They build by default; `-DAIM_BUILD_TESTS=OFF` leaves them out. After a build:

```
ctest --preset release
```

Or `tools\build.ps1 -Test`.

The presets pin MSVC (`cl`), so `CC` and `CXX` environment variables pointing at other compilers don't affect the build.

### Your own build settings

To build somewhere else or to deploy to a test game, add a `CMakeUserPresets.json` next to `CMakePresets.json`. It's personal and is not committed. A preset in it can inherit `release` and set:

- `binaryDir`: where the build goes;
- `FETCHCONTENT_BASE_DIR`: where CommonLibSSE-NG and openvr are downloaded and unpacked (about 300 MB);
- `AIM_DEPLOY_STATE`: a deploy state folder (see below), which adds a `deploy` target.

## Testing in the game

`tools/deploy.py` installs files into a Skyrim installation and records every change, with backups, so all of it can be undone; `tools/deploy.py --help` explains it. With `AIM_DEPLOY_STATE` set, `cmake --build --preset <yours> --target deploy` builds the DLL and puts it into the game on top of the installed `AddItemMenuSE.dll`; `deploy.py uninstall additemmenu-ng` brings the previous one back.

To compare this DLL with the original, AIMProbe (`probe/`) calls every function in several settings variants and records the answers; `tools/run_probe.py` runs it once per variant. Run it with the original DLL installed, then with this one, and compare the two runs:

```
python -B tools/diff_probe.py <original run> <this DLL's run>
```

It accepts the differences in `tests/known-differences.md` and reports anything else. The original DLL only runs on 1.5.97, so runs on other game versions are compared with 1.5.97 results. There the game's own data may differ, and `--data-changes <file>` names the items a newer version's masters changed.

The tests of these Python tools run without the game:

```
python -B -m unittest discover -s tools/tests -t tools/tests
```

## License

GPL-3.0-or-later (see [LICENSE](LICENSE)), with an additional permission to combine this code with Skyrim, SKSE and Windows (see [EXCEPTIONS.md](EXCEPTIONS.md)). It builds on CommonLibSSE-NG, which is licensed the same way.

AddItemMenu itself is towawot's work and is not part of this repository.
