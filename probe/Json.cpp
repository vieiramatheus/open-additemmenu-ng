// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

// Compiled without the precompiled header (see CMakeLists.txt).

#include "Json.h"

#include "Win32.h"

#include <cstdint>
#include <format>

namespace probe::json
{
	bool IsUtf8(std::string_view a_bytes)
	{
		std::size_t i = 0;
		while (i < a_bytes.size()) {
			const auto lead = static_cast<unsigned char>(a_bytes[i]);
			std::size_t    extra = 0;
			std::uint32_t  minimum = 0;
			std::uint32_t  code = 0;
			if (lead < 0x80) {
				++i;
				continue;
			} else if ((lead & 0xE0) == 0xC0) {
				extra = 1, minimum = 0x80, code = lead & 0x1Fu;
			} else if ((lead & 0xF0) == 0xE0) {
				extra = 2, minimum = 0x800, code = lead & 0x0Fu;
			} else if ((lead & 0xF8) == 0xF0) {
				extra = 3, minimum = 0x10000, code = lead & 0x07u;
			} else {
				return false;
			}
			if (i + extra >= a_bytes.size()) {
				return false;  // truncated sequence
			}
			for (std::size_t k = 1; k <= extra; ++k) {
				const auto next = static_cast<unsigned char>(a_bytes[i + k]);
				if ((next & 0xC0) != 0x80) {
					return false;
				}
				code = (code << 6) | (next & 0x3Fu);
			}
			if (code < minimum || code > 0x10FFFF || (code >= 0xD800 && code <= 0xDFFF)) {
				return false;
			}
			i += extra + 1;
		}
		return true;
	}

	std::string Quote(std::string_view a_utf8)
	{
		std::string out;
		out.reserve(a_utf8.size() + 2);
		out += '"';
		for (const char c : a_utf8) {
			switch (c) {
			case '"':
				out += "\\\"";
				break;
			case '\\':
				out += "\\\\";
				break;
			case '\n':
				out += "\\n";
				break;
			case '\r':
				out += "\\r";
				break;
			case '\t':
				out += "\\t";
				break;
			default:
				if (static_cast<unsigned char>(c) < 0x20) {
					out += std::format("\\u{:04x}", static_cast<unsigned char>(c));
				} else {
					out += c;
				}
			}
		}
		out += '"';
		return out;
	}

	std::string GameString(std::string_view a_bytes)
	{
		if (IsUtf8(a_bytes)) {
			return Quote(a_bytes);
		}
		std::string hex;
		hex.reserve(a_bytes.size() * 2);
		for (const char c : a_bytes) {
			hex += std::format("{:02x}", static_cast<unsigned char>(c));
		}
		return std::format(R"({{"hex":"{}","cp1252":{}}})", hex, Quote(win32::Cp1252ToUtf8(a_bytes)));
	}
}
