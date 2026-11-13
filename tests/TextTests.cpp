// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

#include "core/Text.h"

#include <catch2/catch_test_macros.hpp>

#include <climits>

using namespace aim;

TEST_CASE("Case-insensitive comparisons fold ASCII letters only")
{
	CHECK(text::EqualsIgnoreCase("Skyrim.esm", "SKYRIM.ESM"));
	CHECK_FALSE(text::EqualsIgnoreCase("Skyrim.esm", "Skyrim.es"));
	CHECK(text::StartsWithIgnoreCase("Meshes\\Weapons\\a.nif", "meshes\\"));
	CHECK_FALSE(text::StartsWithIgnoreCase("mesh", "meshes\\"));

	CHECK(text::ContainsIgnoreCase("Iron Sword", "rON sWO"));
	CHECK(text::ContainsIgnoreCase("Dawnguard.esm", "aWNgUA"));
	CHECK(text::ContainsIgnoreCase("anything", ""));
	CHECK_FALSE(text::ContainsIgnoreCase("Iron Sword", "Steel"));
	// Other bytes compare as they are: UTF-8 text matches byte for byte, without case folding.
	CHECK(text::ContainsIgnoreCase("Тестовый предмет", "Тестовый"));
	CHECK_FALSE(text::ContainsIgnoreCase("Тестовый предмет", "тестовый"));

	text::LessIgnoreCase less;
	CHECK(less("apple", "BANANA"));
	CHECK_FALSE(less("APPLE", "apple"));
	CHECK_FALSE(less("apple", "APPLE"));
}

TEST_CASE("Trim removes blanks and line ends at both ends")
{
	CHECK(text::Trim("  a b \t\r\n") == "a b");
	CHECK(text::Trim(" \t ").empty());
	CHECK(text::Trim("").empty());
}

TEST_CASE("Integers are read the way INI readers read them")
{
	CHECK(text::ParseInt("57") == 57);
	CHECK(text::ParseInt("57 ;57:Spacebar") == 57);
	CHECK(text::ParseInt("  -3") == -3);
	CHECK(text::ParseInt("+7") == 7);
	CHECK(text::ParseInt("12abc") == 12);
	CHECK(text::ParseInt("99999999999") == INT_MAX);
	CHECK(text::ParseInt("-99999999999") == INT_MIN);
	CHECK_FALSE(text::ParseInt("abc").has_value());
	CHECK_FALSE(text::ParseInt("").has_value());
	CHECK_FALSE(text::ParseInt("-").has_value());
}

TEST_CASE("Booleans are true, false or a number")
{
	CHECK(text::ParseBool("1") == true);
	CHECK(text::ParseBool("0") == false);
	CHECK(text::ParseBool("2") == true);
	CHECK(text::ParseBool(" True ") == true);
	CHECK(text::ParseBool("FALSE") == false);
	CHECK_FALSE(text::ParseBool("yes").has_value());
	CHECK_FALSE(text::ParseBool("").has_value());
}

TEST_CASE("Text files are decoded to UTF-8")
{
	SECTION("UTF-16 LE with a byte-order mark")
	{
		const std::string bytes("\xFF\xFE" "A\0\t\0\x22\x04\x35\x04", 10);  // "A\tТе"
		CHECK(text::DecodeFile(bytes) == "A\tТе");
	}
	SECTION("UTF-16 BE with a byte-order mark")
	{
		const std::string bytes("\xFE\xFF" "\0A\0B", 6);
		CHECK(text::DecodeFile(bytes) == "AB");
	}
	SECTION("A surrogate pair, and an unpaired surrogate")
	{
		const std::string bytes("\xFF\xFE" "\x3D\xD8\x00\xDE" "\x3D\xD8" "A\0", 10);
		CHECK(text::DecodeFile(bytes) == "\xF0\x9F\x98\x80\xEF\xBF\xBD" "A");
	}
	SECTION("An odd last byte is dropped")
	{
		const std::string bytes("\xFF\xFE" "A\0B", 5);
		CHECK(text::DecodeFile(bytes) == "A");
	}
	SECTION("UTF-8 with and without a byte-order mark")
	{
		CHECK(text::DecodeFile("\xEF\xBB\xBFkey\tvalue") == "key\tvalue");
		CHECK(text::DecodeFile("key\tvalue") == "key\tvalue");
		CHECK(text::DecodeFile("").empty());
	}
}

TEST_CASE("Templates are filled in one pass")
{
	CHECK(text::FormatTemplate("Part {N} : {A} - {B}", { { "N", "2" }, { "A", "D" }, { "B", "E" } }) == "Part 2 : D - E");
	CHECK(text::FormatTemplate("{UNKNOWN} {N}", { { "N", "1" } }) == "{UNKNOWN} 1");
	// What is put in is not scanned again.
	CHECK(text::FormatTemplate("{A}{B}", { { "A", "{B}" }, { "B", "x" } }) == "{B}x");
	CHECK(text::FormatTemplate("open { brace", { { "N", "1" } }) == "open { brace");
	CHECK(text::FormatTemplate("{{N}}", { { "N", "1" } }) == "{1}");
	CHECK(text::FormatTemplate("", { { "N", "1" } }).empty());
}

TEST_CASE("Names sort by text, ignoring case and leading spaces")
{
	CHECK(text::CompareNames("apple", "Banana") < 0);
	CHECK(text::CompareNames("IRON SWORD", "iron sword") == 0);
	CHECK(text::CompareNames("Iron", "Iron Sword") < 0);
	CHECK(text::CompareNames(" Zahkrii Do Dovahkiin", "Virtuous Stalhrim Warhammer") > 0);
	CHECK(text::CompareNames("   ", "") == 0);
	// Bytes above ASCII sort after it, by value.
	CHECK(text::CompareNames("Zebra", "Тест") < 0);
}

TEST_CASE("A part label takes a name's first character")
{
	CHECK(text::FirstChar("Iron Sword") == "I");
	CHECK(text::FirstChar("16 Accords") == "1");
	CHECK(text::FirstChar(" Zahkrii") == "_");
	CHECK(text::FirstChar("Тест") == "Т");
	CHECK(text::FirstChar("鉄の剣") == "鉄");
	CHECK(text::FirstChar("").empty());
	// A sequence cut short is taken as far as it goes.
	CHECK(text::FirstChar("\xE9\x89") == "\xE9\x89");
}

TEST_CASE("AIM_Replace replaces every occurrence, or returns \"\"")
{
	CHECK(text::Replace("grue grue", "grue", "grue grue") == "grue grue grue grue");
	CHECK(text::Replace("Found {SEARCH_STRING}!", "{SEARCH_STRING}", "iron") == "Found iron!");
	CHECK(text::Replace("aaa", "aa", "b") == "ba");
	CHECK(text::Replace("abc", "b", "") == "ac");
	// The original DLL returns "" whenever there is nothing to replace.
	CHECK(text::Replace("abc", "x", "y").empty());
	CHECK(text::Replace("abc", "B", "y").empty());
	CHECK(text::Replace("abc", "", "y").empty());
	CHECK(text::Replace("", "a", "y").empty());
}

TEST_CASE("AIM_ReplaceArray applies its pairs in order")
{
	using strings = std::vector<std::string>;
	CHECK(text::ReplaceArray("plugh-frob", strings{ "plugh", "P1" }, strings{ "P1", "F2" }) == "F2-frob");
	CHECK(text::ReplaceArray("a-b", strings{ "a", "b" }, strings{ "1", "2" }) == "1-2");
	CHECK(text::ReplaceArray("text", strings{}, strings{}) == "text");
	CHECK(text::ReplaceArray("a-b", strings{ "a", "x" }, strings{ "1", "2" }).empty());
	CHECK(text::ReplaceArray("a-b", strings{ "a" }, strings{ "1", "2" }).empty());
}

TEST_CASE("Line breaks are removed")
{
	CHECK(text::RemoveLineBreaks("line one\nline two") == "line oneline two");
	CHECK(text::RemoveLineBreaks("a\r\nb\rc") == "abc");
	CHECK(text::RemoveLineBreaks("") == "");
}

TEST_CASE("UTF-16 converts to UTF-8")
{
	CHECK(text::Utf16ToUtf8(u"Iron") == "Iron");
	CHECK(text::Utf16ToUtf8(u"Тест") == "Тест");
	CHECK(text::Utf16ToUtf8(u"鉄") == "鉄");
	CHECK(text::Utf16ToUtf8(u"\U0001F600") == "\xF0\x9F\x98\x80");
	const char16_t lone[] = { 0xDC00, u'a', 0 };
	CHECK(text::Utf16ToUtf8(lone) == "\xEF\xBF\xBD" "a");
}
