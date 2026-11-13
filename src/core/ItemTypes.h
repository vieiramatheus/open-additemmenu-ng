// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <string_view>

namespace aim
{
	// The item types, in the order of the 16 lists AIM_GetItems fills: a type goes into the list
	// whose index is its value, as in the original DLL. Lists 14 and 15 stay empty.
	enum class ItemType : std::uint8_t
	{
		kWeapon,
		kArmor,
		kAmmo,
		kPotion,
		kIngredient,
		kScroll,
		kBook,
		kSpellTome,
		kNote,
		kKey,
		kLight,
		kSoulGem,
		kIngot,
		kMisc,
	};

	inline constexpr std::size_t kItemTypeCount = 14;
	inline constexpr std::size_t kListCount = 16;

	struct ItemTypeInfo
	{
		std::string_view quantityKey;      // its key in [QuantitySettings]
		std::string_view labelKey;         // its translation key, shown as the entry's label
		std::int32_t     defaultQuantity;  // used when the INI doesn't set one
	};

	inline constexpr std::array<ItemTypeInfo, kItemTypeCount> kItemTypes{ {
		{ "Weapon", "$AIM_WEAPON", 1 },
		{ "Armor", "$AIM_ARMOR", 1 },
		{ "Ammo", "$AIM_AMMO", 50 },
		{ "Potion", "$AIM_POTION", 20 },  // the original's built-in value; its INI ships 10
		{ "Ingredient", "$AIM_INGREDIENT", 100 },
		{ "Scroll", "$AIM_SCROLL", 10 },
		{ "Book", "$AIM_BOOK", 1 },
		{ "SpellTome", "$AIM_SPELLTOME", 1 },
		{ "Note", "$AIM_NOTE", 1 },
		{ "Key", "$AIM_KEY", 1 },
		{ "Light", "$AIM_LIGHT", 10 },
		{ "SoulGem", "$AIM_SOULGEM", 10 },
		{ "Ingot", "$AIM_INGOT", 100 },
		{ "Misc", "$AIM_MISC", 1 },
	} };

	constexpr const ItemTypeInfo& Info(ItemType a_type) { return kItemTypes[static_cast<std::size_t>(a_type)]; }

	constexpr std::size_t ListIndex(ItemType a_type) { return static_cast<std::size_t>(a_type); }

	// The type stored in a list; nothing for lists 14 and 15 and for indices out of range.
	constexpr std::optional<ItemType> TypeOfList(std::int32_t a_index)
	{
		if (a_index < 0 || a_index >= static_cast<std::int32_t>(kItemTypeCount)) {
			return std::nullopt;
		}
		return static_cast<ItemType>(a_index);
	}
}
