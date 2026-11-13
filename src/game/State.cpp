// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

#include "game/State.h"

#include "game/Index.h"

namespace aim::game
{
	namespace
	{
		// Paths are relative to the game folder, the game's working directory.
		constexpr auto kSettingsFile = "Data/SKSE/Plugins/AddItemMenuSE.ini"sv;

		std::string Language()
		{
			if (auto* const ini = RE::INISettingCollection::GetSingleton()) {
				if (auto* const setting = ini->GetSetting("sLanguage:General")) {
					if (const char* value = setting->GetString(); value && *value) {
						return value;
					}
				}
			}
			return "ENGLISH";
		}
	}

	State& State::Get()
	{
		static State state;
		return state;
	}

	void State::OnDataLoaded()
	{
		LoadFiles();
		if (_settings.createItemDataBeforeMainMenu) {
			BuildMenu();
		}
	}

	const Settings& State::GetSettings()
	{
		LoadFiles();
		return _settings;
	}

	const Translations& State::GetTranslations()
	{
		LoadFiles();
		return _translations;
	}

	const Menu& State::GetMenu()
	{
		BuildMenu();
		return *_menu;
	}

	void State::LoadFiles()
	{
		std::call_once(_filesOnce, [this] {
			bool found = false;
			_settings = Settings::Load(std::filesystem::path(kSettingsFile), &found);
			if (found) {
				SKSE::log::info("Settings read from {}", kSettingsFile);
			} else {
				SKSE::log::info("No {}; using the default settings", kSettingsFile);
			}

			const auto language = Language();
			const auto path = std::format("Data/Interface/Translations/AddItemMenuSE_{}.txt", language);
			_translations = Translations::Load(std::filesystem::path(path), &found);
			if (found) {
				SKSE::log::info("Translations ({}): {} keys read from {}", language, _translations.size(), path);
			} else {
				SKSE::log::warn("Translations ({}): no {}; the menu shows untranslated labels", language, path);
			}
		});
	}

	void State::BuildMenu()
	{
		std::call_once(_menuOnce, [this] {
			LoadFiles();
			const auto start = std::chrono::steady_clock::now();

			IndexStats stats;
			_catalog = std::make_unique<const Catalog>(BuildCatalog(_settings, stats));
			const MenuLabels labels{
				.part = _translations.Get("$AIM_PART"),
				.search = _translations.Get("$AIM_SEARCHITEM"),
			};
			_menu = std::make_unique<const Menu>(*_catalog, _settings, labels);

			const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - start);
			SKSE::log::info(
				"Item index: {} items from {} plugins in {} entries, built in {} ms "
				"({} item records, {} model files looked up, {} items left out for a missing model)",
				_catalog->ItemCount(), _menu->PluginCount(), _menu->LeafCount(), elapsed.count(),
				stats.forms, stats.modelLookups, stats.missingModels);
		});
	}
}
