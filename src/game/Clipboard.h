// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

// The Windows clipboard, kept apart so that <Windows.h> never meets the CommonLibSSE-NG headers.

#pragma once

#include <optional>
#include <string>
#include <string_view>

namespace aim::clipboard
{
	// The clipboard's Unicode text as UTF-8; nothing when it holds no text or can't be opened.
	std::optional<std::string> GetText();

	// Replaces the clipboard's contents with the text, stored as Unicode text. The text is read
	// as UTF-8, or in the ANSI code page when it isn't valid UTF-8 (plugins that store names in
	// Windows-1252). True on success.
	bool SetText(std::string_view a_text);
}
