// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

#include "core/Text.h"
#include "core/Translations.h"

#include <catch2/catch_test_macros.hpp>

#include <filesystem>
#include <fstream>

using namespace aim;

namespace
{
	// A translation file as the game expects it: UTF-16 LE with a byte-order mark.
	std::string Utf16File(std::u16string_view a_text)
	{
		std::string bytes = "\xFF\xFE";
		for (const char16_t unit : a_text) {
			bytes += static_cast<char>(unit & 0xFF);
			bytes += static_cast<char>(unit >> 8);
		}
		return bytes;
	}
}

TEST_CASE("Translation lines are key, tab, value")
{
	const auto translations = Translations::Parse(
		"$AIM_WEAPON\tWeapons\r\n"
		"// a comment line\r\n"
		"//{PART_NUMBER}\r\n"
		"$AIM_PART\tPart {PART_NUMBER} : {PART_FIRSTITEM_CHAR} - {PART_LASTITEM_CHAR}\r\n"
		"$AIM_SPACED\t  two spaces  \r\n"
		"$AIM_WEAPON\tSecond value\r\n"
		"no tab here\n"
		"\tvalue without a key\n"
		"$AIM_EMPTY\t\n"
		"$AIM_LAST\tno line end");

	CHECK(translations.Get("$AIM_WEAPON") == "Weapons");  // the first line for a key wins
	CHECK(translations.Get("$aim_weapon") == "Weapons");  // keys ignore case
	CHECK(translations.Get("$AIM_PART") == "Part {PART_NUMBER} : {PART_FIRSTITEM_CHAR} - {PART_LASTITEM_CHAR}");
	CHECK(translations.Get("$AIM_SPACED") == "  two spaces  ");
	CHECK(translations.Get("$AIM_LAST") == "no line end");
	CHECK(translations.Find("$AIM_EMPTY") == std::string_view{});
	CHECK(translations.Get("$AIM_MISSING").empty());
	CHECK_FALSE(translations.Find("$AIM_MISSING").has_value());
	CHECK(translations.size() == 5);
}

TEST_CASE("A UTF-16 translation file gives UTF-8 values")
{
	const auto translations = Translations::Parse(text::DecodeFile(Utf16File(u"$AIM_WEAPON\tОружие\r\n$AIM_SEARCHITEM\t[Поиск]\r\n")));
	CHECK(translations.Get("$AIM_WEAPON") == "Оружие");
	CHECK(translations.Get("$AIM_SEARCHITEM") == "[Поиск]");
}

TEST_CASE("Translation files are loaded from disk")
{
	const auto path = std::filesystem::temp_directory_path() / "aim_tests_translations.txt";
	{
		std::ofstream file(path, std::ios::binary);
		file << Utf16File(u"$AIM_NOTE\tNotes\r\n");
	}
	bool found = false;
	CHECK(Translations::Load(path, &found).Get("$AIM_NOTE") == "Notes");
	CHECK(found);
	std::filesystem::remove(path);

	// Without a file every key gives "", as in the original DLL.
	const auto none = Translations::Load(path, &found);
	CHECK_FALSE(found);
	CHECK(none.size() == 0);
	CHECK(none.Get("$AIM_NOTE").empty());
}
