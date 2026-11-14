OPEN ADDITEMMENU NG - (Open DLL for SSE - AE and VR)
Version @VERSION@
https://github.com/vieiramatheus/open-additemmenu-ng

A new, open-source AddItemMenuSE.dll for towawot's AddItemMenu - Ultimate Mod
Explorer 1.14, so the original mod works again on current Skyrim. It replaces
only the DLL. The original mod's plugin, scripts, translations and settings file
stay as they are, and this package contains none of them.

This is a separate project, not AddItemMenu NG by DarkMatterValkyrie, and it
shares no code with it or with the original DLL.


REQUIREMENTS
- AddItemMenu - Ultimate Mod Explorer 1.14 by towawot, installed.
- SKSE for your game version, and the Address Library for SKSE Plugins
  (VR: SKSEVR and the VR Address Library for SKSEVR).
- UIExtensions, which AddItemMenu itself requires.
- SkyUI is recommended: the key that copies an item's name in the container
  (F1 by default) only works with SkyUI, as with the original.


INSTALLING
Install with a mod manager (the archive has a FOMOD installer) and let this mod
overwrite AddItemMenu, so its AddItemMenuSE.dll replaces the original's. The
installer offers the debug symbols as an option, for readable crash logs.
By hand: copy SKSE\Plugins\AddItemMenuSE.dll into Data\SKSE\Plugins and replace
the existing file.


GAME VERSIONS
Tested in game:           1.5.97, 1.6.1170 and 1.7.104 (Steam).
Should work, untested:    GOG 1.6.1179, and other AE versions the Address Library
                          covers.
Experimental, untested:   VR 1.4.15. AddItemMenu's menus come from UIExtensions,
                          whose behavior in VR is unknown.
Reports for the untested versions are very welcome (see below).


DIFFERENCES FROM THE ORIGINAL DLL
It behaves like the original except for these deliberate changes, explained in
KNOWN-DIFFERENCES.md:
- Parts hold exactly ContainerSize items: no empty part, no item in two parts.
- The sort key cycles the orders in [OrderSettings] in their numbered order.
- Copying and pasting names keeps text that isn't English.
- The item lists are always emptied before the menu fills them.
- AllPluginUseItemTypeMenu=1 gives every plugin item-type entries, as its name
  says (the original ignored it).
It reads your AddItemMenuSE.ini and never changes it.


PROBLEMS
Report them at https://github.com/vieiramatheus/open-additemmenu-ng/issues with:
your game version, Documents\My Games\Skyrim Special Edition\SKSE\AddItemMenuSE.log
and skse64.log, and a crash log if the game crashed.


LICENSE
GPL-3.0-or-later (LICENSE.txt), with an additional permission to combine this code
with Skyrim, SKSE and Windows (EXCEPTIONS.md). The source code is at the address
above.
