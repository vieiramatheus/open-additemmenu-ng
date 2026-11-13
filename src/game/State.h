// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

// What the native functions work from: the settings, the translations and the menu. Each part is
// prepared once, when the game has loaded its data or at first use, whichever comes first.

#pragma once

#include "core/Menu.h"
#include "core/Settings.h"
#include "core/Translations.h"

#include <memory>
#include <mutex>

namespace aim::game
{
	class State
	{
	public:
		static State& Get();

		// SKSE's kDataLoaded: reads the settings and translations, and builds the item index
		// unless CreateItemDataBeforeMainMenu=0 says to wait for the first use.
		void OnDataLoaded();

		const Settings&     GetSettings();
		const Translations& GetTranslations();
		const Menu&         GetMenu();

	private:
		State() = default;

		void LoadFiles();
		void BuildMenu();

		std::once_flag                _filesOnce;
		std::once_flag                _menuOnce;
		Settings                      _settings;
		Translations                  _translations;
		std::unique_ptr<const Catalog> _catalog;
		std::unique_ptr<const Menu>    _menu;
	};
}
