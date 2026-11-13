// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

// The list menu's entries (AIM_GetEntries) and the items behind each one (AIM_GetItems), built
// from the catalog of items without touching the game.
//
// Each entry is "label;;parent;;id;;0;;hasChildren", the layout UIExtensions' list menu reads.
// The top level has one entry per plugin with items. A plugin set up for item-type menus gets one
// child per item type it has; a group (a type, or a plugin without type children) larger than
// ContainerSize gets one child per part of at most ContainerSize items, sorted by name.
//
// Ids: entries without children (the leaves) are numbered 1..n once, in load order, and keep
// their id in every sort order and search, because AIM_GetItems receives only the id. Entries
// with children are numbered after the leaves, in the order they are shown. 999 is the search
// entry and is never given to anything else.

#pragma once

#include "core/ItemTypes.h"
#include "core/Settings.h"

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace aim
{
	struct Item
	{
		std::uint32_t formID = 0;
		std::string   name;  // UTF-8, never empty
		ItemType      type = ItemType::kMisc;
	};

	struct Plugin
	{
		std::string       fileName;
		std::vector<Item> items;  // the items it defines that may be shown, in any order
	};

	// Every item that may be shown, by plugin, with the plugins in load order.
	struct Catalog
	{
		std::vector<Plugin> plugins;

		std::size_t ItemCount() const;
	};

	// The labels the DLL writes itself, taken from the translation file.
	struct MenuLabels
	{
		std::string part;    // $AIM_PART; "" gives "Part {PART_NUMBER}"
		std::string search;  // $AIM_SEARCHITEM; "" gives "[Search Item]"
	};

	inline constexpr std::int32_t kSearchEntryId = 999;

	class Menu
	{
	public:
		// The catalog must outlive the menu.
		Menu(const Catalog& a_catalog, const Settings& a_settings, const MenuLabels& a_labels);

		// AIM_GetEntries. A non-empty search keeps the plugins whose file names contain it,
		// ignoring case, and adds the search entry, last or (SearchItemOnTop) first.
		std::vector<std::string> Entries(std::int32_t a_mode, std::string_view a_search) const;

		// AIM_GetItems: a leaf's items; for the search entry, every item whose name contains the
		// search text, ignoring case, in all plugins, excluded ones included; nothing otherwise.
		std::vector<const Item*> Items(std::int32_t a_id, std::string_view a_search) const;

		std::size_t PluginCount() const { return _tops.size(); }
		std::size_t LeafCount() const { return _leafCount; }

	private:
		struct Node
		{
			std::string              label;
			std::int32_t             leafId = 0;  // leaves only
			std::vector<Node>        children;
			std::vector<const Item*> items;  // a leaf's items, until Number() moves them to _leafItems
		};

		struct Top
		{
			const Plugin* plugin = nullptr;
			Node          node;
		};

		void Fill(Node& a_node, std::vector<const Item*> a_items, std::string_view a_partTemplate) const;
		void Number(Node& a_node, std::int32_t& a_next);

		const Catalog&                        _catalog;
		Settings                              _settings;
		std::string                           _searchLabel;
		std::vector<Top>                      _tops;       // in load order
		std::vector<std::vector<const Item*>> _leafItems;  // by leaf id
		std::size_t                           _leafCount = 0;
		std::int32_t                          _firstParentId = 1;
	};

	// The order of items within a group: by name (see text::CompareNames), then by descending
	// form ID, which is how the original DLL mostly orders items with the same name.
	bool ItemLess(const Item& a_left, const Item& a_right);
}
