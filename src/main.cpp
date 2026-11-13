// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

namespace
{
	void OnSKSEMessage(SKSE::MessagingInterface::Message* a_message)
	{
		if (a_message->type == SKSE::MessagingInterface::kDataLoaded) {
			SKSE::log::info("Game data loaded");
		}
	}
}

SKSEPluginLoad(const SKSE::LoadInterface* a_skse)
{
	// Also opens the log: My Games/Skyrim Special Edition/SKSE/AddItemMenuSE.log.
	SKSE::Init(a_skse, { .logPattern = "[%Y-%m-%d %H:%M:%S.%e] [%l] %v" });

	SKSE::log::info(
		"{} {} loaded on Skyrim {}",
		SKSE::GetPluginName(),
		SKSE::GetPluginVersion().string("."),
		REL::Module::get().version().string("."));

	if (!SKSE::GetMessagingInterface()->RegisterListener(OnSKSEMessage)) {
		SKSE::log::error("Could not register for SKSE messages");
	}
	return true;
}
