# Known differences from the original AddItemMenuSE.dll

This DLL replaces the one in AddItemMenu 1.14. Wherever the tests can see, it behaves like the original, except for the differences below, which are all deliberate. The comparison tool, `tools/diff_probe.py`, accepts these and nothing else. Each one's name in backticks is the name the tool reports it under.

## Parts hold exactly ContainerSize items (`parts`)

When a plugin or an item type has more items than `ContainerSize`, the menu splits it into parts. The original sometimes:

- adds an empty last part, with its label's placeholders left unfilled, when the number of items is an exact multiple of `ContainerSize`;
- shows the same item in two neighbouring parts;
- counts every spell tome and note twice in a plugin shown without item-type entries, so that plugin's parts hold fewer items than `ContainerSize`.

Here every part holds exactly `ContainerSize` items, except the last, which holds the rest. No part is empty and no item appears in two parts. So in those groups the part boundaries can differ from the original's, and so can the first and last letters in the part labels.

## Sort orders follow the settings file (`sort-order`)

The sort key cycles through `[OrderSettings]` in its numbered order. With the shipped file that is load order, reverse load order, plugin names A to Z, then Z to A. The original cycles the four default orders in another sequence: load order, names Z to A, reverse load order, names A to Z. With only two entries it follows the file too.

## The clipboard keeps text that isn't English (`clipboard`)

Copying an item's name, and pasting into the search box, go through Unicode. So names in Russian or Japanese, or with accented letters, copy as they are. The original converted through the Windows ANSI code page, which turned such text into question marks or garbled letters. Line breaks are still removed from pasted text.

## AIM_GetItems always empties the lists (`empty-lists`)

Every call empties the 16 form lists before filling them, whatever the id. The original left the previous contents in place for id -1. The mod's own scripts never ask for that id, so this only matters to other mods that call the function directly.

## AllPluginUseItemTypeMenu works (`type-menu-for-all`)

With `AllPluginUseItemTypeMenu=1` in `AddItemMenuSE.ini`, every plugin gets one entry per item type, as the setting's name says. The original ignores the setting. The shipped file sets 0, which behaves the same in both.

## How this is checked

A test plugin, AIMProbe, calls every function with many inputs and in several settings variants, and records the answers. That is done once with the original DLL and once with this one, on the same game, load order and test plugins. `tools/diff_probe.py` then compares the two runs by what the menu shows, not by internal numbers.
