// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

#pragma once

#include <filesystem>
#include <optional>
#include <set>
#include <string>

namespace probe
{
	struct Config
	{
		std::filesystem::path output;                      // the JSON Lines file to write
		std::string           cell{ "Aim" };               // where 'coc' starts the game
		bool                  quit{ true };                // quit the game when done
		bool                  clipboard{ true };           // run the clipboard calls
		// Empty the 16 lists before each AIM_GetItems call. Off by default: AIM_GetItems empties them
		// itself, and the original DLL crashes the game when they are emptied behind its back.
		bool                  clearLists{ false };
		std::set<std::int32_t> skipItems;                  // AIM_GetItems indices not to call
		std::string           listPlugin{ "AddItemMenuSE.esp" };
		RE::FormID            firstList{ 0x00387E };       // AIM_00; the 16 lists are consecutive
	};

	// Reads Data/SKSE/Plugins/AIMProbe.ini. Without a file or without Output, the probe stays idle.
	std::optional<Config> LoadConfig(const std::filesystem::path& a_file);

	// Runs a console command, as if typed into the console.
	void RunConsole(std::string_view a_command);

	// Calls AddItemMenuSE's functions and writes the results. Call on the main thread, in game.
	void Start(const Config& a_config);
}
