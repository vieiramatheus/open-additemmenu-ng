// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

#include "game/Papyrus.h"

#include "core/Text.h"
#include "game/Clipboard.h"
#include "game/State.h"

// The Windows headers some of the library's dependencies include define AddForm as AddFormA
// (a printing function), which would rename BGSListForm::AddForm below.
#ifdef AddForm
#	undef AddForm
#endif

// The functions are registered as usual, not as callable from tasklets, so the game runs them in
// step with its main thread: GetItems changes form lists and CloseContainerMenu the interface.

namespace aim::game::papyrus
{
	namespace
	{
		constexpr auto kScript = "AddItemMenuSE"sv;

		// Empties a list completely. No script ever empties the 16 lists, so without this they
		// would pile up.
		//
		// The game's AddForm appends to `forms` and counts the forms added that way in
		// scriptAddedFormCount, which saving and reverting rely on. AddItemMenuSE.esp's lists have
		// no entries of their own, so everything in them was added and the count goes back to 0
		// with them; a count larger than the array would point past its end.
		void ClearList(RE::BGSListForm& a_list)
		{
			a_list.forms.clear();
			a_list.scriptAddedFormCount = 0;
			if (a_list.scriptAddedTempForms) {
				a_list.scriptAddedTempForms->clear();
			}
		}

		std::vector<std::string> GetEntries(RE::StaticFunctionTag*, std::int32_t a_mode, std::string a_search)
		{
			return State::Get().GetMenu().Entries(a_mode, a_search);
		}

		bool GetItems(RE::StaticFunctionTag*, std::int32_t a_entry, std::vector<RE::BGSListForm*> a_lists, std::string a_search)
		{
			const auto start = std::chrono::steady_clock::now();
			const auto& menu = State::Get().GetMenu();

			for (auto* const list : a_lists) {
				if (list) {
					ClearList(*list);
				}
			}

			std::size_t added = 0;
			for (const auto* item : menu.Items(a_entry, a_search)) {
				const auto index = ListIndex(item->type);
				auto* const list = index < a_lists.size() ? a_lists[index] : nullptr;
				auto* const form = list ? RE::TESForm::LookupByID(item->formID) : nullptr;
				if (form) {
					list->AddForm(form);
					++added;
				}
			}

			const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - start);
			SKSE::log::info("AIM_GetItems({}): {} items in {} ms", a_entry, added, elapsed.count());
			return added > 0;
		}

		std::int32_t GetQuantity(RE::StaticFunctionTag*, std::int32_t a_list)
		{
			return State::Get().GetSettings().QuantityForList(a_list);
		}

		std::int32_t GetOrderListSize(RE::StaticFunctionTag*)
		{
			return static_cast<std::int32_t>(State::Get().GetSettings().sortOrders.size());
		}

		std::int32_t GetClipboardKeyCode(RE::StaticFunctionTag*)
		{
			return State::Get().GetSettings().clipboardKey;
		}

		std::int32_t GetQuantityChangeKeyCode(RE::StaticFunctionTag*)
		{
			return State::Get().GetSettings().quantityChangeKey;
		}

		std::int32_t GetNameSearchKeyCode(RE::StaticFunctionTag*)
		{
			return State::Get().GetSettings().nameSearchKey;
		}

		std::int32_t GetSortOrderKeyCode(RE::StaticFunctionTag*)
		{
			return State::Get().GetSettings().sortOrderKey;
		}

		std::string GetClipboardText(RE::StaticFunctionTag*)
		{
			return text::RemoveLineBreaks(clipboard::GetText().value_or(std::string{}));
		}

		bool SetClipboardText(RE::StaticFunctionTag*, std::string a_text)
		{
			const bool done = clipboard::SetText(a_text);
			if (!done) {
				SKSE::log::warn("AIM_SetClipboardText: the clipboard could not be written");
			}
			return done;
		}

		std::string GetTranslation(RE::StaticFunctionTag*, std::string a_key)
		{
			return State::Get().GetTranslations().Get(a_key);
		}

		std::string Replace(RE::StaticFunctionTag*, std::string a_text, std::string a_target, std::string a_with)
		{
			return text::Replace(a_text, a_target, a_with);
		}

		std::string ReplaceArray(RE::StaticFunctionTag*, std::string a_text, std::vector<std::string> a_targets, std::vector<std::string> a_with)
		{
			return text::ReplaceArray(a_text, a_targets, a_with);
		}

		void CloseContainerMenu(RE::StaticFunctionTag*)
		{
			auto* const ui = RE::UI::GetSingleton();
			auto* const queue = RE::UIMessageQueue::GetSingleton();
			if (ui && queue && ui->IsMenuOpen(RE::ContainerMenu::MENU_NAME)) {
				queue->AddMessage(RE::ContainerMenu::MENU_NAME, RE::UI_MESSAGE_TYPE::kHide, nullptr);
			}
		}
	}

	bool Register(RE::BSScript::IVirtualMachine* a_vm)
	{
		if (!a_vm) {
			return false;
		}
		a_vm->RegisterFunction("AIM_GetEntries"sv, kScript, GetEntries);
		a_vm->RegisterFunction("AIM_GetItems"sv, kScript, GetItems);
		a_vm->RegisterFunction("AIM_GetQuantity"sv, kScript, GetQuantity);
		a_vm->RegisterFunction("AIM_GetOrderListSize"sv, kScript, GetOrderListSize);
		a_vm->RegisterFunction("AIM_GetClipboardKeyCode"sv, kScript, GetClipboardKeyCode);
		a_vm->RegisterFunction("AIM_GetQuantityChangeKeyCode"sv, kScript, GetQuantityChangeKeyCode);
		a_vm->RegisterFunction("AIM_GetNameSearchKeyCode"sv, kScript, GetNameSearchKeyCode);
		a_vm->RegisterFunction("AIM_GetSortOrderKeyCode"sv, kScript, GetSortOrderKeyCode);
		a_vm->RegisterFunction("AIM_GetClipboardText"sv, kScript, GetClipboardText);
		a_vm->RegisterFunction("AIM_SetClipboardText"sv, kScript, SetClipboardText);
		a_vm->RegisterFunction("AIM_GetTranslation"sv, kScript, GetTranslation);
		a_vm->RegisterFunction("AIM_Replace"sv, kScript, Replace);
		a_vm->RegisterFunction("AIM_ReplaceArray"sv, kScript, ReplaceArray);
		a_vm->RegisterFunction("AIM_CloseContainerMenu"sv, kScript, CloseContainerMenu);
		SKSE::log::info("Registered the native functions of {}", kScript);
		return true;
	}
}
