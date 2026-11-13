// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

#include "core/Translations.h"

#include "core/Files.h"

namespace aim
{
	Translations Translations::Parse(std::string_view a_text)
	{
		Translations result;
		while (!a_text.empty()) {
			const auto end = a_text.find('\n');
			auto line = a_text.substr(0, end);
			a_text = end == std::string_view::npos ? std::string_view{} : a_text.substr(end + 1);

			if (line.ends_with('\r')) {
				line.remove_suffix(1);
			}
			const auto tab = line.find('\t');
			if (tab == std::string_view::npos) {
				continue;
			}
			const auto key = text::Trim(line.substr(0, tab));
			if (!key.empty()) {
				result._entries.emplace(key, line.substr(tab + 1));
			}
		}
		return result;
	}

	Translations Translations::Load(const std::filesystem::path& a_path, bool* a_found)
	{
		const auto bytes = files::ReadAll(a_path);
		if (a_found) {
			*a_found = bytes.has_value();
		}
		return bytes ? Parse(text::DecodeFile(*bytes)) : Translations{};
	}

	std::optional<std::string_view> Translations::Find(std::string_view a_key) const
	{
		const auto found = _entries.find(a_key);
		if (found == _entries.end()) {
			return std::nullopt;
		}
		return found->second;
	}

	std::string Translations::Get(std::string_view a_key) const
	{
		return std::string(Find(a_key).value_or(std::string_view{}));
	}
}
