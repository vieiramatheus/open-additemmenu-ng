// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

// The few Windows calls the probe needs, kept apart so that <Windows.h> never meets the
// CommonLibSSE-NG headers.

#pragma once

#include <optional>
#include <string>
#include <string_view>

namespace probe::win32
{
	// The clipboard's Unicode text as UTF-8, or nullopt when it holds no text.
	std::optional<std::string> ReadClipboard();

	// Replaces the clipboard's contents with UTF-8 text, stored as Unicode text.
	bool WriteClipboard(std::string_view a_utf8);

	// Empties the clipboard.
	bool ClearClipboard();

	// Windows-1252 bytes, converted to UTF-8.
	std::string Cp1252ToUtf8(std::string_view a_bytes);
}
