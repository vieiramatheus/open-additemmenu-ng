# open-additemmenu-ng

An open-source replacement for `AddItemMenuSE.dll`, the SKSE plugin of towawot's **AddItemMenu - Ultimate Mod Explorer 1.14**, so that the original mod works again on current Skyrim: Special Edition 1.5.97 and Anniversary Edition 1.6 and 1.7. VR support may follow.

**Status: early development.** All 14 functions the mod's scripts call are in place and pass the comparison runs on Skyrim 1.5.97. Testing on AE continues, and there is no release to install yet.

## How it will work

You keep the original AddItemMenu 1.14 installed, with its plugin, scripts, translations and settings file, and install this mod after it. It replaces only `SKSE/Plugins/AddItemMenuSE.dll`, and reads the same `AddItemMenuSE.ini` settings, so your existing setup keeps working. The original mod's files are not included here and are never redistributed.

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

The deploy script's tests run without the game:

```
python -B -m unittest discover -s tools/tests -t tools/tests
```

## License

GPL-3.0-or-later (see [LICENSE](LICENSE)), with an additional permission to combine this code with Skyrim, SKSE and Windows (see [EXCEPTIONS.md](EXCEPTIONS.md)). It builds on CommonLibSSE-NG, which is licensed the same way.

AddItemMenu itself is towawot's work and is not part of this repository.
