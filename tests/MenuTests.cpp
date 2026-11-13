// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

#include "core/Menu.h"

#include <catch2/catch_test_macros.hpp>

#include <algorithm>
#include <format>
#include <map>
#include <set>

using namespace aim;

namespace
{
	using Strings = std::vector<std::string>;

	Item MakeItem(std::uint32_t a_formID, std::string a_name, ItemType a_type = ItemType::kMisc)
	{
		return Item{ a_formID, std::move(a_name), a_type };
	}

	// Plugins in load order. Skyrim.esm has item-type children; B.esp is split into parts;
	// Excluded.esp is hidden; Empty.esp has nothing to show.
	Catalog SampleCatalog()
	{
		Catalog catalog;
		catalog.plugins = {
			{ "Skyrim.esm",
				{
					MakeItem(0x01, "Iron Sword", ItemType::kWeapon),
					MakeItem(0x02, "Daedric Sword", ItemType::kWeapon),
					MakeItem(0x03, "Steel Sword", ItemType::kWeapon),
					MakeItem(0x10, "Iron Helmet", ItemType::kArmor),
					MakeItem(0x20, "A Book", ItemType::kBook),
				} },
			{ "Update.esm", { MakeItem(0x100, "Gold") } },
			{ "Empty.esp", {} },
			{ "B.esp", { MakeItem(0x300, "Bucket"), MakeItem(0x301, "Apple"), MakeItem(0x302, "Cup") } },
			{ "Excluded.esp", { MakeItem(0x400, "Excluded Sword", ItemType::kWeapon) } },
			{ "a.esp", { MakeItem(0x500, "Zebra Sword", ItemType::kWeapon) } },
		};
		return catalog;
	}

	Settings SampleSettings()
	{
		Settings settings;
		settings.containerSize = 2;
		settings.itemTypeMenuPlugins = { "skyrim.ESM" };
		settings.exclusionPlugins = { "Excluded.esp" };
		return settings;
	}

	const MenuLabels kLabels{ .part = "Part {PART_NUMBER} : {PART_FIRSTITEM_CHAR} - {PART_LASTITEM_CHAR}", .search = "[Find]" };

	struct Entry
	{
		std::string  label;
		std::int32_t parent;
		std::int32_t id;
		std::int32_t callback;
		bool         hasChildren;
	};

	Entry Split(const std::string& a_entry)
	{
		std::vector<std::string> fields;
		std::size_t              from = 0;
		for (auto at = a_entry.find(";;"); at != std::string::npos; at = a_entry.find(";;", from)) {
			fields.push_back(a_entry.substr(from, at - from));
			from = at + 2;
		}
		fields.push_back(a_entry.substr(from));
		REQUIRE(fields.size() == 5);
		return { fields[0], std::stoi(fields[1]), std::stoi(fields[2]), std::stoi(fields[3]), fields[4] == "1" };
	}

	// Each leaf's path of labels ("Skyrim.esm/$AIM_WEAPON/Part 1 : D - I") with its id.
	std::map<std::string, std::int32_t> LeafIds(const Strings& a_entries)
	{
		std::map<std::int32_t, std::string> paths;  // by id, for the parents
		std::map<std::string, std::int32_t> leaves;
		for (const auto& text : a_entries) {
			const auto entry = Split(text);
			const auto path = (entry.parent == -1 ? std::string{} : paths.at(entry.parent) + "/") + entry.label;
			if (entry.hasChildren) {
				paths[entry.id] = path;
			} else {
				leaves[path] = entry.id;
			}
		}
		return leaves;
	}

	Strings Names(const std::vector<const Item*>& a_items)
	{
		Strings names;
		for (const auto* item : a_items) {
			names.push_back(item->name);
		}
		return names;
	}
}

TEST_CASE("The entries in load order")
{
	const auto catalog = SampleCatalog();
	const Menu menu(catalog, SampleSettings(), kLabels);

	CHECK(menu.PluginCount() == 4);
	CHECK(menu.LeafCount() == 8);
	CHECK(menu.Entries(0, "") == Strings{
									 "Skyrim.esm;;-1;;9;;0;;1",
									 "$AIM_WEAPON;;9;;10;;0;;1",
									 "Part 1 : D - I;;10;;1;;0;;0",
									 "Part 2 : S - S;;10;;2;;0;;0",
									 "$AIM_ARMOR;;9;;3;;0;;0",
									 "$AIM_BOOK;;9;;4;;0;;0",
									 "Update.esm;;-1;;5;;0;;0",
									 "B.esp;;-1;;11;;0;;1",
									 "Part 1 : A - B;;11;;6;;0;;0",
									 "Part 2 : C - C;;11;;7;;0;;0",
									 "a.esp;;-1;;8;;0;;0",
								 });
}

TEST_CASE("Sort orders reorder the plugins only")
{
	const auto catalog = SampleCatalog();
	const Menu menu(catalog, SampleSettings(), kLabels);

	const auto tops = [&](std::int32_t a_mode) {
		Strings names;
		for (const auto& text : menu.Entries(a_mode, "")) {
			if (const auto entry = Split(text); entry.parent == -1) {
				names.push_back(entry.label);
			}
		}
		return names;
	};
	CHECK(tops(0) == Strings{ "Skyrim.esm", "Update.esm", "B.esp", "a.esp" });
	CHECK(tops(1) == Strings{ "a.esp", "B.esp", "Update.esm", "Skyrim.esm" });
	// Names compare byte by byte, so upper case sorts before lower case, as in the original DLL.
	CHECK(tops(2) == Strings{ "B.esp", "Skyrim.esm", "Update.esm", "a.esp" });
	CHECK(tops(3) == Strings{ "a.esp", "Update.esm", "Skyrim.esm", "B.esp" });
	CHECK(tops(4) == tops(0));
	CHECK(tops(-1) == tops(0));

	CHECK(menu.Entries(1, "") == Strings{
									 "a.esp;;-1;;8;;0;;0",
									 "B.esp;;-1;;9;;0;;1",
									 "Part 1 : A - B;;9;;6;;0;;0",
									 "Part 2 : C - C;;9;;7;;0;;0",
									 "Update.esm;;-1;;5;;0;;0",
									 "Skyrim.esm;;-1;;10;;0;;1",
									 "$AIM_WEAPON;;10;;11;;0;;1",
									 "Part 1 : D - I;;11;;1;;0;;0",
									 "Part 2 : S - S;;11;;2;;0;;0",
									 "$AIM_ARMOR;;10;;3;;0;;0",
									 "$AIM_BOOK;;10;;4;;0;;0",
								 });
}

TEST_CASE("A leaf keeps its id in every sort order and search; parents follow the leaves")
{
	const auto catalog = SampleCatalog();
	const Menu menu(catalog, SampleSettings(), kLabels);

	const auto reference = LeafIds(menu.Entries(0, ""));
	for (const std::int32_t mode : { 1, 2, 3 }) {
		CHECK(LeafIds(menu.Entries(mode, "")) == reference);
	}
	for (const auto& [path, id] : LeafIds(menu.Entries(0, "esp"))) {
		if (id != kSearchEntryId) {
			CHECK(reference.at(path) == id);
		}
	}

	for (const std::int32_t mode : { 0, 1, 2, 3 }) {
		std::int32_t expected = 9;
		for (const auto& text : menu.Entries(mode, "")) {
			if (const auto entry = Split(text); entry.hasChildren) {
				CHECK(entry.id == expected++);
			}
			CHECK(Split(text).callback == 0);
		}
	}
}

TEST_CASE("A search keeps the matching plugins and adds the search entry")
{
	const auto catalog = SampleCatalog();
	auto       settings = SampleSettings();

	SECTION("Last by default; parents numbered in the order shown")
	{
		const Menu menu(catalog, settings, kLabels);
		CHECK(menu.Entries(0, "ESP") == Strings{
											"B.esp;;-1;;9;;0;;1",
											"Part 1 : A - B;;9;;6;;0;;0",
											"Part 2 : C - C;;9;;7;;0;;0",
											"a.esp;;-1;;8;;0;;0",
											"[Find];;-1;;999;;0;;0",
										});
		CHECK(menu.Entries(0, "Update") == Strings{ "Update.esm;;-1;;5;;0;;0", "[Find];;-1;;999;;0;;0" });
		// Plugin names only: an item name doesn't count, nor does an excluded plugin.
		CHECK(menu.Entries(0, "Sword") == Strings{ "[Find];;-1;;999;;0;;0" });
		CHECK(menu.Entries(0, "Excluded") == Strings{ "[Find];;-1;;999;;0;;0" });
	}
	SECTION("First with SearchItemOnTop")
	{
		settings.searchItemOnTop = true;
		const Menu menu(catalog, settings, kLabels);
		CHECK(menu.Entries(2, "update") == Strings{ "[Find];;-1;;999;;0;;0", "Update.esm;;-1;;5;;0;;0" });
		CHECK(menu.Entries(0, "").front() == "Skyrim.esm;;-1;;9;;0;;1");
	}
	SECTION("Built-in labels without a translation file")
	{
		const Menu menu(catalog, settings, MenuLabels{});
		const auto entries = menu.Entries(0, "B.esp");
		CHECK(entries == Strings{
							 "B.esp;;-1;;9;;0;;1",
							 "Part 1;;9;;6;;0;;0",
							 "Part 2;;9;;7;;0;;0",
							 "[Search Item];;-1;;999;;0;;0",
						 });
	}
}

TEST_CASE("The items behind an entry")
{
	const auto catalog = SampleCatalog();
	const Menu menu(catalog, SampleSettings(), kLabels);

	CHECK(Names(menu.Items(1, "")) == Strings{ "Daedric Sword", "Iron Sword" });
	CHECK(Names(menu.Items(2, "")) == Strings{ "Steel Sword" });
	CHECK(Names(menu.Items(3, "")) == Strings{ "Iron Helmet" });
	CHECK(menu.Items(3, "")[0]->type == ItemType::kArmor);
	CHECK(Names(menu.Items(5, "")) == Strings{ "Gold" });
	CHECK(Names(menu.Items(6, "")) == Strings{ "Apple", "Bucket" });
	CHECK(Names(menu.Items(8, "")) == Strings{ "Zebra Sword" });
	// The search text only matters for the search entry.
	CHECK(Names(menu.Items(8, "ignored")) == Strings{ "Zebra Sword" });

	for (const std::int32_t id : { 0, -1, 9, 10, 11, 100, 998, 1000 }) {
		CHECK(menu.Items(id, "").empty());
	}
}

TEST_CASE("The search entry finds items by name in every plugin")
{
	const auto catalog = SampleCatalog();
	const Menu menu(catalog, SampleSettings(), kLabels);

	// Excluded plugins are searched too, and the results aren't limited by ContainerSize.
	CHECK(Names(menu.Items(kSearchEntryId, "SWORD")) == Strings{ "Iron Sword", "Daedric Sword", "Steel Sword", "Excluded Sword", "Zebra Sword" });
	CHECK(Names(menu.Items(kSearchEntryId, "on sw")) == Strings{ "Iron Sword" });
	CHECK(menu.Items(kSearchEntryId, "").empty());
	CHECK(menu.Items(kSearchEntryId, "nothing like it").empty());
}

TEST_CASE("Parts hold ContainerSize items each, with nothing empty or repeated")
{
	Catalog catalog;
	catalog.plugins = { { "Four.esp", { MakeItem(1, "d"), MakeItem(2, "c"), MakeItem(3, "b"), MakeItem(4, "a") } } };
	Settings settings;
	settings.containerSize = 2;
	const Menu menu(catalog, settings, kLabels);

	CHECK(menu.Entries(0, "") == Strings{
									 "Four.esp;;-1;;3;;0;;1",
									 "Part 1 : a - b;;3;;1;;0;;0",
									 "Part 2 : c - d;;3;;2;;0;;0",
								 });
	CHECK(Names(menu.Items(1, "")) == Strings{ "a", "b" });
	CHECK(Names(menu.Items(2, "")) == Strings{ "c", "d" });

	settings.containerSize = 4;
	const Menu whole(catalog, settings, kLabels);
	CHECK(whole.Entries(0, "") == Strings{ "Four.esp;;-1;;1;;0;;0" });
	CHECK(Names(whole.Items(1, "")) == Strings{ "a", "b", "c", "d" });
}

TEST_CASE("Items sort by name, ignoring case and leading spaces, then by descending form ID")
{
	Catalog catalog;
	catalog.plugins = { { "Sort.esp",
		{
			MakeItem(0x10, "Same"),
			MakeItem(0x30, "same"),
			MakeItem(0x20, "Same"),
			MakeItem(0x40, " Zahkrii Do Dovahkiin"),
			MakeItem(0x50, "Virtuous Stalhrim Warhammer"),
			MakeItem(0x60, "apple"),
		} } };
	Settings settings;
	settings.containerSize = 3;
	const MenuLabels labels{ .part = "{PART_FIRSTITEM_FULL}|{PART_LASTITEM_FULL}|{PART_FIRSTITEM_CHAR}{PART_LASTITEM_CHAR}" };
	const Menu menu(catalog, settings, labels);

	CHECK(menu.Entries(0, "") == Strings{
									 "Sort.esp;;-1;;3;;0;;1",
									 "apple|Same|aS;;3;;1;;0;;0",
									 "Same| Zahkrii Do Dovahkiin|S_;;3;;2;;0;;0",
								 });
	std::vector<std::uint32_t> ids;
	for (const std::int32_t leaf : { 1, 2 }) {
		for (const auto* item : menu.Items(leaf, "")) {
			ids.push_back(item->formID);
		}
	}
	CHECK(ids == std::vector<std::uint32_t>{ 0x60, 0x30, 0x20, 0x10, 0x50, 0x40 });
}

TEST_CASE("Id 999 is never given to an entry other than the search entry")
{
	Catalog catalog;
	auto&   big = catalog.plugins.emplace_back(Plugin{ "Big.esp", {} });
	for (std::uint32_t i = 0; i < 1500; ++i) {
		big.items.push_back(MakeItem(i + 1, std::format("Item {:04}", i)));
	}
	catalog.plugins.push_back({ "Small.esp", { MakeItem(5000, "Small") } });
	Settings settings;
	settings.containerSize = 1;
	const Menu menu(catalog, settings, kLabels);

	CHECK(menu.LeafCount() == 1501);
	std::set<std::int32_t> ids;
	for (const auto& text : menu.Entries(0, "")) {
		const auto entry = Split(text);
		CHECK(entry.id != kSearchEntryId);
		CHECK(ids.insert(entry.id).second);
	}
	// 1501 leaves take the ids 1-1502 except 999, and Big.esp, the only parent, gets 1503.
	CHECK(ids.size() == 1502);
	CHECK(*ids.rbegin() == 1503);

	CHECK(Names(menu.Items(998, "")) == Strings{ "Item 0997" });
	CHECK(Names(menu.Items(1000, "")) == Strings{ "Item 0998" });
	CHECK(Names(menu.Items(1502, "")) == Strings{ "Small" });
	CHECK(menu.Items(kSearchEntryId, "").empty());
	CHECK(menu.Items(kSearchEntryId, "Item 0998").size() == 1);
}

TEST_CASE("Every plugin gets type children with AllPluginUseItemTypeMenu")
{
	Catalog catalog;
	catalog.plugins = { { "Mod.esp", { MakeItem(1, "Ore", ItemType::kIngot), MakeItem(2, "Bow", ItemType::kWeapon) } } };
	Settings settings;
	settings.allPluginUseItemTypeMenu = true;
	const Menu menu(catalog, settings, kLabels);

	// Types appear in list order, whatever the item order.
	CHECK(menu.Entries(0, "") == Strings{
									 "Mod.esp;;-1;;3;;0;;1",
									 "$AIM_WEAPON;;3;;1;;0;;0",
									 "$AIM_INGOT;;3;;2;;0;;0",
								 });
}

TEST_CASE("An empty catalog gives no entries")
{
	const Catalog catalog;
	const Menu    menu(catalog, Settings{}, kLabels);
	CHECK(menu.Entries(0, "").empty());
	CHECK(menu.Entries(0, "x") == Strings{ "[Find];;-1;;999;;0;;0" });
	CHECK(menu.Items(1, "").empty());
}
