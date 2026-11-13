// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

// Builds the catalog of items from the game's loaded data.

#pragma once

#include "core/Menu.h"
#include "core/Settings.h"

#include <cstddef>

namespace aim::game
{
	struct IndexStats
	{
		std::size_t forms = 0;          // item records looked at
		std::size_t modelLookups = 0;   // distinct model files looked up
		std::size_t missingModels = 0;  // items left out because their model file is missing
	};

	// Every item that may be shown, by the plugin that defines it, in load order. Left out: items
	// without a name, items that aren't playable, lights that can't be carried, and items whose
	// model file is missing when CheckResourceFiles asks for the check.
	Catalog BuildCatalog(const Settings& a_settings, IndexStats& a_stats);
}
