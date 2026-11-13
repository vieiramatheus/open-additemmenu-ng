// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

#pragma once

#include <string>
#include <string_view>

namespace probe::json
{
	// True when the bytes are well-formed UTF-8.
	bool IsUtf8(std::string_view a_bytes);

	// A JSON string literal for text that is already UTF-8.
	std::string Quote(std::string_view a_utf8);

	// A JSON value for a string from the game, keeping every byte: a plain JSON string when the
	// bytes are UTF-8 (ASCII included), otherwise {"hex": "...", "cp1252": "..."}.
	std::string GameString(std::string_view a_bytes);
}
