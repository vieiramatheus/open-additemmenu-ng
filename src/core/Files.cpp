// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

#include "core/Files.h"

#include <fstream>
#include <iterator>
#include <system_error>

namespace aim::files
{
	std::optional<std::string> ReadAll(const std::filesystem::path& a_path)
	{
		std::error_code error;
		if (!std::filesystem::is_regular_file(a_path, error)) {
			return std::nullopt;
		}
		std::ifstream file(a_path, std::ios::binary);
		if (!file) {
			return std::nullopt;
		}
		std::string bytes{ std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>() };
		if (file.bad()) {
			return std::nullopt;
		}
		return bytes;
	}
}
