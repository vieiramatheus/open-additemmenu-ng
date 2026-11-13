// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

#include "core/Text.h"

#include <algorithm>

namespace aim::text
{
	char LowerAscii(char a_char)
	{
		return a_char >= 'A' && a_char <= 'Z' ? static_cast<char>(a_char - 'A' + 'a') : a_char;
	}

	bool EqualsIgnoreCase(std::string_view a_left, std::string_view a_right)
	{
		return a_left.size() == a_right.size() &&
		       std::ranges::equal(a_left, a_right, [](char a, char b) { return LowerAscii(a) == LowerAscii(b); });
	}

	bool StartsWithIgnoreCase(std::string_view a_text, std::string_view a_prefix)
	{
		return a_text.size() >= a_prefix.size() && EqualsIgnoreCase(a_text.substr(0, a_prefix.size()), a_prefix);
	}

	bool ContainsIgnoreCase(std::string_view a_text, std::string_view a_part)
	{
		if (a_part.empty()) {
			return true;
		}
		const auto found = std::ranges::search(a_text, a_part, [](char a, char b) { return LowerAscii(a) == LowerAscii(b); });
		return !found.empty();
	}

	std::string_view Trim(std::string_view a_text)
	{
		const auto first = a_text.find_first_not_of(" \t\r\n");
		if (first == std::string_view::npos) {
			return {};
		}
		const auto last = a_text.find_last_not_of(" \t\r\n");
		return a_text.substr(first, last - first + 1);
	}

	std::optional<std::int32_t> ParseInt(std::string_view a_text)
	{
		std::size_t at = 0;
		while (at < a_text.size() && (a_text[at] == ' ' || a_text[at] == '\t')) {
			++at;
		}
		bool negative = false;
		if (at < a_text.size() && (a_text[at] == '-' || a_text[at] == '+')) {
			negative = a_text[at] == '-';
			++at;
		}
		const auto digits = at;
		std::int64_t value = 0;
		for (; at < a_text.size() && a_text[at] >= '0' && a_text[at] <= '9'; ++at) {
			if (value <= INT32_MAX) {
				value = value * 10 + (a_text[at] - '0');
			}
		}
		if (at == digits) {
			return std::nullopt;
		}
		value = negative ? -value : value;
		return static_cast<std::int32_t>(std::clamp<std::int64_t>(value, INT32_MIN, INT32_MAX));
	}

	std::optional<bool> ParseBool(std::string_view a_text)
	{
		const auto text = Trim(a_text);
		if (EqualsIgnoreCase(text, "true")) {
			return true;
		}
		if (EqualsIgnoreCase(text, "false")) {
			return false;
		}
		const auto number = ParseInt(text);
		return number ? std::optional(*number != 0) : std::nullopt;
	}

	std::string DecodeFile(std::string_view a_bytes)
	{
		const auto utf16 = [&](bool a_bigEndian) {
			std::u16string units;
			units.reserve(a_bytes.size() / 2);
			for (std::size_t i = 2; i + 1 < a_bytes.size(); i += 2) {
				const auto first = static_cast<unsigned char>(a_bytes[i]);
				const auto second = static_cast<unsigned char>(a_bytes[i + 1]);
				units += static_cast<char16_t>(a_bigEndian ? (first << 8) | second : (second << 8) | first);
			}
			return Utf16ToUtf8(units);
		};
		if (a_bytes.starts_with("\xFF\xFE")) {
			return utf16(false);
		}
		if (a_bytes.starts_with("\xFE\xFF")) {
			return utf16(true);
		}
		if (a_bytes.starts_with("\xEF\xBB\xBF")) {
			return std::string(a_bytes.substr(3));
		}
		return std::string(a_bytes);
	}

	std::string FormatTemplate(std::string_view a_template, TemplateValues a_values)
	{
		std::string result;
		result.reserve(a_template.size());
		std::size_t at = 0;
		while (at < a_template.size()) {
			const auto open = a_template.find('{', at);
			if (open == std::string_view::npos) {
				break;
			}
			const auto close = a_template.find('}', open + 1);
			if (close == std::string_view::npos) {
				break;
			}
			result.append(a_template.substr(at, open - at));
			const auto name = a_template.substr(open + 1, close - open - 1);
			const auto* const value = std::ranges::find(a_values, name, &std::pair<std::string_view, std::string_view>::first);
			if (value != a_values.end()) {
				result.append(value->second);
				at = close + 1;
			} else {
				// Not a placeholder we know: keep the brace and look for the next one after it.
				result += '{';
				at = open + 1;
			}
		}
		result.append(a_template.substr(at));
		return result;
	}

	int CompareNames(std::string_view a_left, std::string_view a_right)
	{
		const auto skip = [](std::string_view a_text) {
			const auto first = a_text.find_first_not_of(' ');
			return first == std::string_view::npos ? std::string_view{} : a_text.substr(first);
		};
		const auto left = skip(a_left);
		const auto right = skip(a_right);
		const auto length = std::min(left.size(), right.size());
		for (std::size_t i = 0; i < length; ++i) {
			const auto a = static_cast<unsigned char>(LowerAscii(left[i]));
			const auto b = static_cast<unsigned char>(LowerAscii(right[i]));
			if (a != b) {
				return a < b ? -1 : 1;
			}
		}
		return left.size() == right.size() ? 0 : (left.size() < right.size() ? -1 : 1);
	}

	std::string FirstChar(std::string_view a_name)
	{
		if (a_name.empty()) {
			return {};
		}
		const auto lead = static_cast<unsigned char>(a_name[0]);
		if (lead == ' ') {
			return "_";
		}
		std::size_t length = 1;
		if ((lead & 0xE0) == 0xC0) {
			length = 2;
		} else if ((lead & 0xF0) == 0xE0) {
			length = 3;
		} else if ((lead & 0xF8) == 0xF0) {
			length = 4;
		}
		return std::string(a_name.substr(0, std::min(length, a_name.size())));
	}

	std::string Replace(std::string_view a_text, std::string_view a_target, std::string_view a_with)
	{
		if (a_target.empty()) {
			return {};
		}
		auto at = a_text.find(a_target);
		if (at == std::string_view::npos) {
			return {};
		}
		std::string result;
		std::size_t from = 0;
		while (at != std::string_view::npos) {
			result.append(a_text.substr(from, at - from));
			result.append(a_with);
			from = at + a_target.size();
			at = a_text.find(a_target, from);
		}
		result.append(a_text.substr(from));
		return result;
	}

	std::string ReplaceArray(std::string_view a_text, const std::vector<std::string>& a_targets, const std::vector<std::string>& a_with)
	{
		if (a_targets.size() != a_with.size()) {
			return {};
		}
		std::string result(a_text);
		for (std::size_t i = 0; i < a_targets.size(); ++i) {
			result = Replace(result, a_targets[i], a_with[i]);
		}
		return result;
	}

	std::string RemoveLineBreaks(std::string_view a_text)
	{
		std::string result;
		result.reserve(a_text.size());
		for (const char c : a_text) {
			if (c != '\r' && c != '\n') {
				result += c;
			}
		}
		return result;
	}

	std::string Utf16ToUtf8(std::u16string_view a_text)
	{
		std::string result;
		result.reserve(a_text.size());
		for (std::size_t i = 0; i < a_text.size(); ++i) {
			std::uint32_t code = a_text[i];
			if (code >= 0xD800 && code <= 0xDBFF && i + 1 < a_text.size() && a_text[i + 1] >= 0xDC00 && a_text[i + 1] <= 0xDFFF) {
				code = 0x10000 + ((code - 0xD800) << 10) + (a_text[i + 1] - 0xDC00);
				++i;
			} else if (code >= 0xD800 && code <= 0xDFFF) {
				code = 0xFFFD;
			}
			if (code < 0x80) {
				result += static_cast<char>(code);
			} else if (code < 0x800) {
				result += static_cast<char>(0xC0 | (code >> 6));
				result += static_cast<char>(0x80 | (code & 0x3F));
			} else if (code < 0x10000) {
				result += static_cast<char>(0xE0 | (code >> 12));
				result += static_cast<char>(0x80 | ((code >> 6) & 0x3F));
				result += static_cast<char>(0x80 | (code & 0x3F));
			} else {
				result += static_cast<char>(0xF0 | (code >> 18));
				result += static_cast<char>(0x80 | ((code >> 12) & 0x3F));
				result += static_cast<char>(0x80 | ((code >> 6) & 0x3F));
				result += static_cast<char>(0x80 | (code & 0x3F));
			}
		}
		return result;
	}

	bool LessIgnoreCase::operator()(std::string_view a_left, std::string_view a_right) const
	{
		return std::ranges::lexicographical_compare(a_left, a_right, [](char a, char b) {
			return static_cast<unsigned char>(LowerAscii(a)) < static_cast<unsigned char>(LowerAscii(b));
		});
	}
}
