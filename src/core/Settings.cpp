// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

#include "core/Settings.h"

#include "core/Files.h"

#include <algorithm>
#include <map>
#include <utility>

namespace aim
{
	std::optional<SortOrder> ParseSortOrder(std::string_view a_text)
	{
		static constexpr std::pair<std::string_view, SortOrder> kNames[]{
			{ "LoadOrderAsc", SortOrder::kLoadOrderAsc },
			{ "LoadOrderDesc", SortOrder::kLoadOrderDesc },
			{ "PluginNameAsc", SortOrder::kPluginNameAsc },
			{ "PluginNameDesc", SortOrder::kPluginNameDesc },
		};
		const auto text = text::Trim(a_text);
		for (const auto& [name, order] : kNames) {
			if (text::EqualsIgnoreCase(text, name)) {
				return order;
			}
		}
		return std::nullopt;
	}

	bool Settings::UsesItemTypeMenu(std::string_view a_plugin) const
	{
		return allPluginUseItemTypeMenu || itemTypeMenuPlugins.contains(a_plugin);
	}

	bool Settings::IsExcluded(std::string_view a_plugin) const
	{
		return exclusionPlugins.contains(a_plugin);
	}

	bool Settings::SkipsResourceCheck(std::string_view a_plugin) const
	{
		return ignoreCheckResourcePlugins.contains(a_plugin);
	}

	std::int32_t Settings::QuantityForList(std::int32_t a_list) const
	{
		const auto type = TypeOfList(a_list);
		return type ? quantities[static_cast<std::size_t>(*type)] : 0;
	}

	SortOrder Settings::SortOrderForMode(std::int32_t a_mode) const
	{
		if (sortOrders.empty()) {
			return SortOrder::kLoadOrderAsc;
		}
		if (a_mode < 0 || static_cast<std::size_t>(a_mode) >= sortOrders.size()) {
			a_mode = 0;
		}
		return sortOrders[static_cast<std::size_t>(a_mode)];
	}

	namespace
	{
		void SetInt(std::int32_t& a_target, std::string_view a_value)
		{
			if (const auto value = text::ParseInt(a_value)) {
				a_target = *value;
			}
		}

		void SetBool(bool& a_target, std::string_view a_value)
		{
			if (const auto value = text::ParseBool(a_value)) {
				a_target = *value;
			}
		}

		void SetPlugin(PluginSet& a_set, std::string_view a_plugin, std::string_view a_value)
		{
			const auto value = text::ParseBool(a_value);
			if (!value) {
				return;
			}
			if (*value) {
				a_set.emplace(a_plugin);
			} else if (const auto found = a_set.find(a_plugin); found != a_set.end()) {
				a_set.erase(found);
			}
		}
	}

	Settings Settings::Parse(std::string_view a_text)
	{
		Settings settings;
		std::string section;
		bool sawOrderSettings = false;
		std::map<std::int32_t, SortOrder> orders;

		while (!a_text.empty()) {
			const auto end = a_text.find('\n');
			auto line = a_text.substr(0, end);
			a_text = end == std::string_view::npos ? std::string_view{} : a_text.substr(end + 1);

			// Everything from the first ';' is a comment, including after a value
			// ("NameSearchKey=57 ;57:Spacebar").
			line = text::Trim(line.substr(0, line.find(';')));
			if (line.empty()) {
				continue;
			}
			if (line.front() == '[') {
				const auto close = line.find(']');
				section = text::Trim(line.substr(1, close == std::string_view::npos ? std::string_view::npos : close - 1));
				if (text::EqualsIgnoreCase(section, "OrderSettings")) {
					sawOrderSettings = true;
				}
				continue;
			}
			const auto equals = line.find('=');
			if (equals == std::string_view::npos) {
				continue;
			}
			const auto key = text::Trim(line.substr(0, equals));
			const auto value = text::Trim(line.substr(equals + 1));
			if (key.empty()) {
				continue;
			}

			const auto in = [&](std::string_view a_section) { return text::EqualsIgnoreCase(section, a_section); };
			const auto is = [&](std::string_view a_key) { return text::EqualsIgnoreCase(key, a_key); };

			if (in("GeneralSettings")) {
				if (is("ContainerSize")) {
					SetInt(settings.containerSize, value);
				} else if (is("AllPluginUseItemTypeMenu")) {
					SetBool(settings.allPluginUseItemTypeMenu, value);
				} else if (is("CreateItemDataBeforeMainMenu")) {
					SetBool(settings.createItemDataBeforeMainMenu, value);
				} else if (is("CheckResourceFiles")) {
					SetInt(settings.checkResourceFiles, value);
				} else if (is("SearchItemOnTop")) {
					SetBool(settings.searchItemOnTop, value);
				}
			} else if (in("Hotkeys")) {
				if (is("NameSearchKey")) {
					SetInt(settings.nameSearchKey, value);
				} else if (is("QuantityChangeKey")) {
					SetInt(settings.quantityChangeKey, value);
				} else if (is("SortOrderKey")) {
					SetInt(settings.sortOrderKey, value);
				} else if (is("ClipboardKey")) {
					SetInt(settings.clipboardKey, value);
				}
			} else if (in("QuantitySettings")) {
				for (std::size_t i = 0; i < kItemTypeCount; ++i) {
					if (is(kItemTypes[i].quantityKey)) {
						SetInt(settings.quantities[i], value);
					}
				}
			} else if (in("ItemTypeMenuPlugins")) {
				SetPlugin(settings.itemTypeMenuPlugins, key, value);
			} else if (in("ExclusionPlugins")) {
				SetPlugin(settings.exclusionPlugins, key, value);
			} else if (in("IgnoreCheckResourcePlugins")) {
				SetPlugin(settings.ignoreCheckResourcePlugins, key, value);
			} else if (in("OrderSettings")) {
				const auto number = text::ParseInt(key);
				const auto order = ParseSortOrder(value);
				if (number && order) {
					orders[*number] = *order;
				}
			}
		}

		if (settings.containerSize < 1) {
			settings.containerSize = 512;
		}
		settings.checkResourceFiles = std::clamp(settings.checkResourceFiles, 0, 3);
		if (sawOrderSettings) {
			settings.sortOrders.clear();
			for (const auto& [number, order] : orders) {
				settings.sortOrders.push_back(order);
			}
			if (settings.sortOrders.empty()) {
				settings.sortOrders.push_back(SortOrder::kLoadOrderAsc);
			}
		}
		return settings;
	}

	Settings Settings::Load(const std::filesystem::path& a_path, bool* a_found)
	{
		const auto bytes = files::ReadAll(a_path);
		if (a_found) {
			*a_found = bytes.has_value();
		}
		return bytes ? Parse(text::DecodeFile(*bytes)) : Settings{};
	}
}
