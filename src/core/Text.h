// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

// Text helpers. Game strings are UTF-8. Comparisons that ignore case fold the ASCII letters only
// and compare every other byte as it is.

#pragma once

#include <cstdint>
#include <initializer_list>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace aim::text
{
	char LowerAscii(char a_char);

	bool EqualsIgnoreCase(std::string_view a_left, std::string_view a_right);

	bool StartsWithIgnoreCase(std::string_view a_text, std::string_view a_prefix);

	bool ContainsIgnoreCase(std::string_view a_text, std::string_view a_part);

	std::string_view Trim(std::string_view a_text);

	// An integer the way INI readers take one: leading blanks, an optional sign, then digits up to
	// the first other character ("57 ;Spacebar" is 57). Nothing when there are no digits; values
	// beyond the 32-bit range are clamped.
	std::optional<std::int32_t> ParseInt(std::string_view a_text);

	// "true" and "false" in any case, or an integer, where anything but 0 is true.
	std::optional<bool> ParseBool(std::string_view a_text);

	// Decodes a text file's bytes to UTF-8: UTF-16 LE or BE when the file starts with that byte-order
	// mark, otherwise the bytes as they are, minus a UTF-8 byte-order mark.
	std::string DecodeFile(std::string_view a_bytes);

	// Fills in "{NAME}" placeholders in one pass, so text that is put in is never scanned again.
	// Unknown placeholders stay as they are.
	using TemplateValues = std::initializer_list<std::pair<std::string_view, std::string_view>>;
	std::string FormatTemplate(std::string_view a_template, TemplateValues a_values);

	// The order of item names: leading spaces don't count, and case doesn't matter.
	// Returns a negative number, zero or a positive number, like strcmp.
	int CompareNames(std::string_view a_left, std::string_view a_right);

	// The first character of a name (a whole UTF-8 sequence) for a part's label. A space shows
	// as '_', as in the original DLL.
	std::string FirstChar(std::string_view a_name);

	// AIM_Replace: every occurrence, left to right, case-sensitive, without rescanning what was put
	// in. Like the original DLL, the result is "" when the target is empty or doesn't occur.
	std::string Replace(std::string_view a_text, std::string_view a_target, std::string_view a_with);

	// AIM_ReplaceArray: Replace for each pair, in order, on the text so far. "" when the arrays
	// differ in length or a target doesn't occur; the text unchanged when both are empty.
	std::string ReplaceArray(std::string_view a_text, const std::vector<std::string>& a_targets, const std::vector<std::string>& a_with);

	// Removes every carriage return and line feed.
	std::string RemoveLineBreaks(std::string_view a_text);

	// UTF-16 to UTF-8. An unpaired surrogate becomes U+FFFD.
	std::string Utf16ToUtf8(std::u16string_view a_text);

	struct LessIgnoreCase
	{
		using is_transparent = void;
		bool operator()(std::string_view a_left, std::string_view a_right) const;
	};
}
