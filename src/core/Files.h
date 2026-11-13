// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

#pragma once

#include <filesystem>
#include <optional>
#include <string>

namespace aim::files
{
	// The whole file as bytes; nothing when it can't be opened or read.
	std::optional<std::string> ReadAll(const std::filesystem::path& a_path);
}
