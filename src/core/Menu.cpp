// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

#include "core/Menu.h"

#include "core/Text.h"

#include <algorithm>
#include <array>
#include <format>
#include <utility>

namespace aim
{
	namespace
	{
		// The next free id, never the search entry's.
		std::int32_t TakeId(std::int32_t& a_next)
		{
			if (a_next == kSearchEntryId) {
				++a_next;
			}
			return a_next++;
		}

		std::string Entry(std::string_view a_label, std::int32_t a_parent, std::int32_t a_id, bool a_hasChildren)
		{
			return std::format("{};;{};;{};;0;;{}", a_label, a_parent, a_id, a_hasChildren ? 1 : 0);
		}
	}

	std::size_t Catalog::ItemCount() const
	{
		std::size_t count = 0;
		for (const auto& plugin : plugins) {
			count += plugin.items.size();
		}
		return count;
	}

	bool ItemLess(const Item& a_left, const Item& a_right)
	{
		const auto order = text::CompareNames(a_left.name, a_right.name);
		return order != 0 ? order < 0 : a_left.formID > a_right.formID;
	}

	Menu::Menu(const Catalog& a_catalog, const Settings& a_settings, const MenuLabels& a_labels) :
		_catalog(a_catalog),
		_settings(a_settings),
		_searchLabel(a_labels.search.empty() ? "[Search Item]" : a_labels.search)
	{
		const std::string partTemplate = a_labels.part.empty() ? "Part {PART_NUMBER}" : a_labels.part;

		for (const auto& plugin : _catalog.plugins) {
			if (plugin.items.empty() || _settings.IsExcluded(plugin.fileName)) {
				continue;
			}
			Top top{ &plugin, Node{ plugin.fileName } };
			if (_settings.UsesItemTypeMenu(plugin.fileName)) {
				std::array<std::vector<const Item*>, kItemTypeCount> byType;
				for (const auto& item : plugin.items) {
					byType[ListIndex(item.type)].push_back(&item);
				}
				for (std::size_t type = 0; type < kItemTypeCount; ++type) {
					if (!byType[type].empty()) {
						Node child{ std::string(kItemTypes[type].labelKey) };
						Fill(child, std::move(byType[type]), partTemplate);
						top.node.children.push_back(std::move(child));
					}
				}
			} else {
				std::vector<const Item*> items;
				items.reserve(plugin.items.size());
				for (const auto& item : plugin.items) {
					items.push_back(&item);
				}
				Fill(top.node, std::move(items), partTemplate);
			}
			_tops.push_back(std::move(top));
		}

		std::int32_t next = 1;
		for (auto& top : _tops) {
			Number(top.node, next);
		}
		if (next == kSearchEntryId) {
			++next;
		}
		_firstParentId = next;
	}

	void Menu::Fill(Node& a_node, std::vector<const Item*> a_items, std::string_view a_partTemplate) const
	{
		std::ranges::sort(a_items, [](const Item* a, const Item* b) { return ItemLess(*a, *b); });

		const auto size = static_cast<std::size_t>(std::max(_settings.containerSize, 1));
		if (a_items.size() <= size) {
			a_node.items = std::move(a_items);
			return;
		}
		// Parts of exactly `size` items, the last one with the rest: no empty part and no item in
		// two parts (the original DLL has both problems at the boundaries).
		for (std::size_t first = 0, number = 1; first < a_items.size(); first += size, ++number) {
			const auto last = std::min(first + size, a_items.size());
			const auto& firstName = a_items[first]->name;
			const auto& lastName = a_items[last - 1]->name;
			const auto partNumber = std::to_string(number);
			const auto firstChar = text::FirstChar(firstName);
			const auto lastChar = text::FirstChar(lastName);

			Node part;
			part.label = text::FormatTemplate(a_partTemplate, {
				{ "PART_NUMBER", partNumber },
				{ "PART_FIRSTITEM_FULL", firstName },
				{ "PART_LASTITEM_FULL", lastName },
				{ "PART_FIRSTITEM_CHAR", firstChar },
				{ "PART_LASTITEM_CHAR", lastChar },
			});
			const auto begin = a_items.begin();
			part.items.assign(begin + static_cast<std::ptrdiff_t>(first), begin + static_cast<std::ptrdiff_t>(last));
			a_node.children.push_back(std::move(part));
		}
	}

	void Menu::Number(Node& a_node, std::int32_t& a_next)
	{
		if (!a_node.children.empty()) {
			for (auto& child : a_node.children) {
				Number(child, a_next);
			}
			return;
		}
		a_node.leafId = TakeId(a_next);
		if (_leafItems.size() <= static_cast<std::size_t>(a_node.leafId)) {
			_leafItems.resize(static_cast<std::size_t>(a_node.leafId) + 1);
		}
		_leafItems[static_cast<std::size_t>(a_node.leafId)] = std::move(a_node.items);
		a_node.items.clear();
		++_leafCount;
	}

	std::vector<std::string> Menu::Entries(std::int32_t a_mode, std::string_view a_search) const
	{
		std::vector<const Top*> shown;
		for (const auto& top : _tops) {
			if (a_search.empty() || text::ContainsIgnoreCase(top.plugin->fileName, a_search)) {
				shown.push_back(&top);
			}
		}

		// Plugin names compare byte by byte, so case matters, as in the original DLL.
		switch (_settings.SortOrderForMode(a_mode)) {
		case SortOrder::kLoadOrderAsc:
			break;
		case SortOrder::kLoadOrderDesc:
			std::ranges::reverse(shown);
			break;
		case SortOrder::kPluginNameAsc:
			std::ranges::stable_sort(shown, [](const Top* a, const Top* b) { return a->plugin->fileName < b->plugin->fileName; });
			break;
		case SortOrder::kPluginNameDesc:
			std::ranges::stable_sort(shown, [](const Top* a, const Top* b) { return a->plugin->fileName > b->plugin->fileName; });
			break;
		}

		std::vector<std::string> entries;
		const auto searchEntry = [&] { entries.push_back(Entry(_searchLabel, -1, kSearchEntryId, false)); };
		if (!a_search.empty() && _settings.searchItemOnTop) {
			searchEntry();
		}

		std::int32_t nextParent = _firstParentId;
		const auto add = [&](this const auto& a_self, const Node& a_node, std::int32_t a_parent) -> void {
			if (a_node.children.empty()) {
				entries.push_back(Entry(a_node.label, a_parent, a_node.leafId, false));
				return;
			}
			const auto id = TakeId(nextParent);
			entries.push_back(Entry(a_node.label, a_parent, id, true));
			for (const auto& child : a_node.children) {
				a_self(child, id);
			}
		};
		for (const auto* top : shown) {
			add(top->node, -1);
		}

		if (!a_search.empty() && !_settings.searchItemOnTop) {
			searchEntry();
		}
		return entries;
	}

	std::vector<const Item*> Menu::Items(std::int32_t a_id, std::string_view a_search) const
	{
		if (a_id == kSearchEntryId) {
			std::vector<const Item*> found;
			if (a_search.empty()) {
				return found;
			}
			for (const auto& plugin : _catalog.plugins) {
				for (const auto& item : plugin.items) {
					if (text::ContainsIgnoreCase(item.name, a_search)) {
						found.push_back(&item);
					}
				}
			}
			return found;
		}
		if (a_id <= 0 || static_cast<std::size_t>(a_id) >= _leafItems.size()) {
			return {};
		}
		return _leafItems[static_cast<std::size_t>(a_id)];
	}
}
