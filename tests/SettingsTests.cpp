// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

#include "core/Settings.h"

#include <catch2/catch_test_macros.hpp>

#include <filesystem>
#include <fstream>

using namespace aim;

namespace
{
	constexpr auto kSample =
		"; Settings for the tests\r\n"
		"[GeneralSettings]\r\n"
		"ContainerSize=100\r\n"
		"AllPluginUseItemTypeMenu=1\r\n"
		"CreateItemDataBeforeMainMenu=0\r\n"
		"CheckResourceFiles=3 ; the strictest\r\n"
		"SearchItemOnTop=true\r\n"
		"\r\n"
		"[Hotkeys]\r\n"
		"NameSearchKey=58 ;58:Caps Lock\r\n"
		"QuantityChangeKey=0\r\n"
		"SortOrderKey = 49\r\n"
		"ClipboardKey=60\r\n"
		"\r\n"
		"[QuantitySettings]\r\n"
		"Potion=5\r\n"
		"Ingot=250\r\n"
		"Weapon=many\r\n"
		"\r\n"
		"[ItemTypeMenuPlugins]\r\n"
		";Commented Out.esp=1\r\n"
		"MyMod.esp=1\r\n"
		"Someone's Patch.esp = 1\r\n"
		"\r\n"
		"[ExclusionPlugins]\r\n"
		"Hidden.esp=1\r\n"
		"Shown.esp=0\r\n"
		"Hidden Too.esp=TRUE\r\n"
		"\r\n"
		"[IgnoreCheckResourcePlugins]\r\n"
		"Someone's Armory.esp=1\r\n"
		"\r\n"
		"[OrderSettings]\r\n"
		"2=PluginNameDesc\r\n"
		"1=LoadOrderDesc\r\n"
		"3=NoSuchOrder\r\n";
}

TEST_CASE("Without a settings file, the original DLL's defaults apply")
{
	const Settings settings;
	CHECK(settings.containerSize == 512);
	CHECK_FALSE(settings.allPluginUseItemTypeMenu);
	CHECK(settings.createItemDataBeforeMainMenu);
	CHECK(settings.checkResourceFiles == 2);
	CHECK_FALSE(settings.searchItemOnTop);
	CHECK(settings.nameSearchKey == 57);
	CHECK(settings.quantityChangeKey == 29);
	CHECK(settings.sortOrderKey == 48);
	CHECK(settings.clipboardKey == 59);

	// Lists 0-13 hold one type each; Potion's built-in default is 20.
	const std::int32_t expected[] = { 1, 1, 50, 20, 100, 10, 1, 1, 1, 1, 10, 10, 100, 1 };
	for (std::int32_t list = 0; list < 14; ++list) {
		CHECK(settings.QuantityForList(list) == expected[list]);
	}
	for (const std::int32_t list : { 14, 15, 16, -1, 999 }) {
		CHECK(settings.QuantityForList(list) == 0);
	}

	CHECK(settings.itemTypeMenuPlugins.empty());
	CHECK(settings.exclusionPlugins.empty());
	CHECK(settings.ignoreCheckResourcePlugins.empty());
	CHECK_FALSE(settings.UsesItemTypeMenu("Skyrim.esm"));
	CHECK_FALSE(settings.IsExcluded("AddItemMenuSE.esp"));

	REQUIRE(settings.sortOrders.size() == 4);
	CHECK(settings.SortOrderForMode(0) == SortOrder::kLoadOrderAsc);
	CHECK(settings.SortOrderForMode(1) == SortOrder::kLoadOrderDesc);
	CHECK(settings.SortOrderForMode(2) == SortOrder::kPluginNameAsc);
	CHECK(settings.SortOrderForMode(3) == SortOrder::kPluginNameDesc);
	CHECK(settings.SortOrderForMode(4) == SortOrder::kLoadOrderAsc);
	CHECK(settings.SortOrderForMode(-1) == SortOrder::kLoadOrderAsc);

	CHECK(Settings::Parse("").containerSize == 512);
}

TEST_CASE("A settings file is read")
{
	const auto settings = Settings::Parse(kSample);

	CHECK(settings.containerSize == 100);
	CHECK(settings.allPluginUseItemTypeMenu);
	CHECK_FALSE(settings.createItemDataBeforeMainMenu);
	CHECK(settings.checkResourceFiles == 3);
	CHECK(settings.searchItemOnTop);

	CHECK(settings.nameSearchKey == 58);
	CHECK(settings.quantityChangeKey == 0);
	CHECK(settings.sortOrderKey == 49);
	CHECK(settings.clipboardKey == 60);

	const auto quantity = [&](ItemType a_type) { return settings.QuantityForList(static_cast<std::int32_t>(ListIndex(a_type))); };
	CHECK(quantity(ItemType::kPotion) == 5);
	CHECK(quantity(ItemType::kIngot) == 250);
	CHECK(quantity(ItemType::kWeapon) == 1);  // unreadable: the default
	CHECK(quantity(ItemType::kAmmo) == 50);   // missing: the default

	CHECK(settings.itemTypeMenuPlugins == PluginSet{ "MyMod.esp", "Someone's Patch.esp" });
	CHECK(settings.UsesItemTypeMenu("mymod.ESP"));
	CHECK(settings.UsesItemTypeMenu("Anything.esp"));  // AllPluginUseItemTypeMenu=1

	CHECK(settings.IsExcluded("Hidden.esp"));
	CHECK(settings.IsExcluded("HIDDEN TOO.ESP"));
	CHECK_FALSE(settings.IsExcluded("Shown.esp"));
	CHECK(settings.SkipsResourceCheck("someone's armory.esp"));

	REQUIRE(settings.sortOrders.size() == 2);
	CHECK(settings.SortOrderForMode(0) == SortOrder::kLoadOrderDesc);
	CHECK(settings.SortOrderForMode(1) == SortOrder::kPluginNameDesc);
	CHECK(settings.SortOrderForMode(2) == SortOrder::kLoadOrderDesc);
}

TEST_CASE("Settings parsing rules")
{
	SECTION("Section names and keys ignore case")
	{
		const auto settings = Settings::Parse("[generalsettings]\ncontainersize=64\n[HOTKEYS]\nnamesearchkey=1\n");
		CHECK(settings.containerSize == 64);
		CHECK(settings.nameSearchKey == 1);
	}
	SECTION("A later line for the same plugin wins")
	{
		const auto settings = Settings::Parse("[ExclusionPlugins]\nA.esp=1\na.ESP=0\nB.esp=0\nB.esp=1\n");
		CHECK_FALSE(settings.IsExcluded("A.esp"));
		CHECK(settings.IsExcluded("B.esp"));
	}
	SECTION("Values out of range are corrected")
	{
		CHECK(Settings::Parse("[GeneralSettings]\nContainerSize=0\n").containerSize == 512);
		CHECK(Settings::Parse("[GeneralSettings]\nContainerSize=-5\n").containerSize == 512);
		CHECK(Settings::Parse("[GeneralSettings]\nCheckResourceFiles=7\n").checkResourceFiles == 3);
		CHECK(Settings::Parse("[GeneralSettings]\nCheckResourceFiles=-1\n").checkResourceFiles == 0);
	}
	SECTION("Keys outside their section are ignored")
	{
		const auto settings = Settings::Parse("ContainerSize=64\n[Hotkeys]\nContainerSize=32\n");
		CHECK(settings.containerSize == 512);
	}
	SECTION("Lines without '=' and keys without a name are ignored")
	{
		const auto settings = Settings::Parse("[ExclusionPlugins]\nnot a setting\n=1\nA.esp=1\n");
		CHECK(settings.exclusionPlugins == PluginSet{ "A.esp" });
	}
	SECTION("Sort orders follow their numbers, whatever the file order")
	{
		const auto settings = Settings::Parse("[OrderSettings]\n10=PluginNameAsc\n2=pluginnamedesc\nx=LoadOrderDesc\n");
		REQUIRE(settings.sortOrders.size() == 2);
		CHECK(settings.sortOrders[0] == SortOrder::kPluginNameDesc);
		CHECK(settings.sortOrders[1] == SortOrder::kPluginNameAsc);
	}
	SECTION("An order section with nothing usable leaves load order only")
	{
		for (const auto* text : { "[OrderSettings]\n", "[OrderSettings]\n1=Random\n; 2=LoadOrderDesc\n" }) {
			const auto settings = Settings::Parse(text);
			REQUIRE(settings.sortOrders.size() == 1);
			CHECK(settings.sortOrders[0] == SortOrder::kLoadOrderAsc);
		}
	}
	SECTION("A file without an order section keeps all four orders")
	{
		CHECK(Settings::Parse("[GeneralSettings]\nContainerSize=64\n").sortOrders.size() == 4);
	}
}

TEST_CASE("Settings files are loaded from disk")
{
	const auto path = std::filesystem::temp_directory_path() / "aim_tests_settings.ini";
	{
		std::ofstream file(path, std::ios::binary);
		file << "\xEF\xBB\xBF[GeneralSettings]\r\nContainerSize=77\r\n";
	}
	bool found = false;
	CHECK(Settings::Load(path, &found).containerSize == 77);
	CHECK(found);
	std::filesystem::remove(path);

	CHECK(Settings::Load(path, &found).containerSize == 512);
	CHECK_FALSE(found);
}
