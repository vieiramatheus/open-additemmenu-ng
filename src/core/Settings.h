// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

// AddItemMenuSE.ini, the settings file the original mod ships. Same sections and keys; this DLL
// only reads it.

#pragma once

#include "core/ItemTypes.h"
#include "core/Text.h"

#include <array>
#include <cstdint>
#include <filesystem>
#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <vector>

namespace aim
{
	enum class SortOrder : std::uint8_t
	{
		kLoadOrderAsc,
		kLoadOrderDesc,
		kPluginNameAsc,
		kPluginNameDesc,
	};

	std::optional<SortOrder> ParseSortOrder(std::string_view a_text);

	// Plugin file names, compared without regard to case.
	using PluginSet = std::set<std::string, text::LessIgnoreCase>;

	struct Settings
	{
		// [GeneralSettings]
		std::int32_t containerSize = 512;  // values below 1 fall back to 512
		bool         allPluginUseItemTypeMenu = false;
		bool         createItemDataBeforeMainMenu = true;
		std::int32_t checkResourceFiles = 2;  // clamped to 0..3
		bool         searchItemOnTop = false;

		// [Hotkeys]: DirectInput scan codes; 0 turns a key off.
		std::int32_t nameSearchKey = 57;      // Space
		std::int32_t quantityChangeKey = 29;  // Left Ctrl
		std::int32_t sortOrderKey = 48;       // B
		std::int32_t clipboardKey = 59;       // F1

		// [QuantitySettings], by item type.
		std::array<std::int32_t, kItemTypeCount> quantities = DefaultQuantities();

		// [ItemTypeMenuPlugins], [ExclusionPlugins], [IgnoreCheckResourcePlugins]: the plugins set
		// to a value other than 0. None by default, as in the original DLL without a settings file.
		PluginSet itemTypeMenuPlugins;
		PluginSet exclusionPlugins;
		PluginSet ignoreCheckResourcePlugins;

		// [OrderSettings], in the order of their numeric keys. Without the section, the four
		// orders below; with the section but nothing usable in it, load order only.
		std::vector<SortOrder> sortOrders{
			SortOrder::kLoadOrderAsc,
			SortOrder::kLoadOrderDesc,
			SortOrder::kPluginNameAsc,
			SortOrder::kPluginNameDesc,
		};

		bool UsesItemTypeMenu(std::string_view a_plugin) const;
		bool IsExcluded(std::string_view a_plugin) const;
		bool SkipsResourceCheck(std::string_view a_plugin) const;

		// AIM_GetQuantity: the quantity for the type stored in a list; 0 for the lists that hold no
		// type and for indices out of range, as in the original DLL.
		std::int32_t QuantityForList(std::int32_t a_list) const;

		// The sort order of a mode from the list script; a mode out of range acts as mode 0.
		SortOrder SortOrderForMode(std::int32_t a_mode) const;

		static constexpr std::array<std::int32_t, kItemTypeCount> DefaultQuantities()
		{
			std::array<std::int32_t, kItemTypeCount> result{};
			for (std::size_t i = 0; i < kItemTypeCount; ++i) {
				result[i] = kItemTypes[i].defaultQuantity;
			}
			return result;
		}

		// Reads settings from the text of an INI file. Keys that are missing or unreadable keep
		// their defaults.
		static Settings Parse(std::string_view a_text);

		// Reads the file; the defaults when it can't be read.
		static Settings Load(const std::filesystem::path& a_path, bool* a_found = nullptr);
	};
}
