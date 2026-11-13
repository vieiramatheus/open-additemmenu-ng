// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

// AIMProbe: a test plugin. With Data/SKSE/Plugins/AIMProbe.ini in place it starts a new game in
// a small cell as soon as the main menu opens, calls AddItemMenuSE's functions, writes the
// results to the file named in the INI, and quits the game. Without the INI it does nothing.

#include "Probe.h"

#include <atomic>
#include <chrono>
#include <filesystem>
#include <functional>
#include <optional>
#include <thread>

namespace
{
	std::optional<probe::Config> g_config;
	std::atomic_bool             g_enteredGame{ false };  // 'coc' scheduled
	std::atomic_bool             g_cocRun{ false };       // 'coc' sent to the console
	std::atomic_bool             g_loading{ false };      // the loading screen that follows 'coc' opened
	std::atomic_bool             g_started{ false };

	void RunLater(std::chrono::milliseconds a_delay, std::function<void()> a_task)
	{
		std::thread([a_delay, task = std::move(a_task)]() mutable {
			std::this_thread::sleep_for(a_delay);
			SKSE::GetTaskInterface()->AddTask(std::move(task));
		}).detach();
	}

	void EnterGame()
	{
		if (!g_enteredGame.exchange(true)) {
			RunLater(1s, [] {
				g_cocRun = true;
				probe::RunConsole("coc " + g_config->cell);
			});
		}
	}

	// Starts the probe once the player stands in a loaded cell, checking once a second.
	// Starting while the new game still loads would race the game resetting the lists.
	void StartWhenInGame(int a_triesLeft)
	{
		RunLater(1s, [a_triesLeft] {
			auto* const player = RE::PlayerCharacter::GetSingleton();
			auto* const ui = RE::UI::GetSingleton();
			const bool  ready = player && player->GetParentCell() && player->Is3DLoaded() &&
			                   !ui->IsMenuOpen(RE::LoadingMenu::MENU_NAME);
			if (ready) {
				probe::Start(*g_config);
			} else if (a_triesLeft > 0) {
				StartWhenInGame(a_triesLeft - 1);
			} else {
				SKSE::log::error("The game never finished loading; the probe gives up");
				probe::RunConsole("qqq");
			}
		});
	}

	class MenuWatcher final : public RE::BSTEventSink<RE::MenuOpenCloseEvent>
	{
	public:
		RE::BSEventNotifyControl ProcessEvent(const RE::MenuOpenCloseEvent* a_event, RE::BSTEventSource<RE::MenuOpenCloseEvent>*) override
		{
			if (!a_event) {
				return RE::BSEventNotifyControl::kContinue;
			}
			if (a_event->menuName == RE::MainMenu::MENU_NAME && a_event->opening) {
				EnterGame();
			} else if (a_event->menuName == RE::LoadingMenu::MENU_NAME) {
				// Only the loading screen that 'coc' brings up counts, not the one at startup.
				if (a_event->opening && g_cocRun) {
					g_loading = true;
				} else if (!a_event->opening && g_loading && !g_started.exchange(true)) {
					// Give the game's own scripts a few seconds to settle after loading.
					RunLater(2s, [] { StartWhenInGame(60); });
				}
			}
			return RE::BSEventNotifyControl::kContinue;
		}
	};

	MenuWatcher g_menuWatcher;

	void OnSKSEMessage(SKSE::MessagingInterface::Message* a_message)
	{
		if (a_message->type != SKSE::MessagingInterface::kDataLoaded || !g_config) {
			return;
		}
		auto* const ui = RE::UI::GetSingleton();
		ui->AddEventSink<RE::MenuOpenCloseEvent>(&g_menuWatcher);
		if (ui->IsMenuOpen(RE::MainMenu::MENU_NAME)) {
			EnterGame();
		}
	}
}

SKSEPluginLoad(const SKSE::LoadInterface* a_skse)
{
	SKSE::Init(a_skse, { .logPattern = "[%Y-%m-%d %H:%M:%S.%e] [%l] %v" });

	const std::filesystem::path configFile = "Data/SKSE/Plugins/AIMProbe.ini";
	g_config = probe::LoadConfig(configFile);
	if (!g_config) {
		SKSE::log::info("No {} with an Output setting; the probe stays idle", configFile.string());
		return true;
	}
	SKSE::log::info("Probe armed: will start a game in '{}' and write {}", g_config->cell, g_config->output.string());
	SKSE::GetMessagingInterface()->RegisterListener(OnSKSEMessage);
	return true;
}
