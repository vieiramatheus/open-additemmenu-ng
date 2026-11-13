// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

// The mod's translation file, Interface/Translations/AddItemMenuSE_<language>.txt: one
// "key<TAB>value" per line, normally UTF-16 LE with a byte-order mark. The DLL reads it itself,
// as the original does, for AIM_GetTranslation and for its own labels.

#pragma once

#include "core/Text.h"

#include <cstddef>
#include <filesystem>
#include <map>
#include <optional>
#include <string>
#include <string_view>

namespace aim
{
	class Translations
	{
	public:
		// Reads the text of a translation file, already decoded to UTF-8. Lines without a tab are
		// skipped; the first line with a key wins.
		static Translations Parse(std::string_view a_text);

		// Reads the file; no translations when it can't be read.
		static Translations Load(const std::filesystem::path& a_path, bool* a_found = nullptr);

		// The value for a key, its leading '$' included. Keys are matched without regard to case,
		// because Papyrus may hand over a key in another casing than the script's.
		std::optional<std::string_view> Find(std::string_view a_key) const;

		// The value, or "" when there is none.
		std::string Get(std::string_view a_key) const;

		std::size_t size() const { return _entries.size(); }

	private:
		std::map<std::string, std::string, text::LessIgnoreCase> _entries;
	};
}
