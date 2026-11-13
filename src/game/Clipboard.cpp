// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

// Compiled without the precompiled header (see CMakeLists.txt).

#include "game/Clipboard.h"

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>

#include <algorithm>
#include <cwchar>

namespace aim::clipboard
{
	namespace
	{
		// Opens the clipboard for one operation. Another program may hold it for a moment, so it
		// tries a few times, briefly: this runs on the game's main thread.
		class Session
		{
		public:
			Session()
			{
				for (int attempt = 0; attempt < 10 && !_open; ++attempt) {
					_open = ::OpenClipboard(nullptr) != FALSE;
					if (!_open) {
						::Sleep(10);
					}
				}
			}

			~Session()
			{
				if (_open) {
					::CloseClipboard();
				}
			}

			Session(const Session&) = delete;
			Session& operator=(const Session&) = delete;

			explicit operator bool() const { return _open; }

		private:
			bool _open = false;
		};

		std::wstring Widen(std::string_view a_text)
		{
			if (a_text.empty()) {
				return {};
			}
			const auto size = static_cast<int>(a_text.size());
			UINT       codePage = CP_UTF8;
			DWORD      flags = MB_ERR_INVALID_CHARS;
			int        length = ::MultiByteToWideChar(codePage, flags, a_text.data(), size, nullptr, 0);
			if (length == 0) {
				codePage = CP_ACP;
				flags = 0;
				length = ::MultiByteToWideChar(codePage, flags, a_text.data(), size, nullptr, 0);
			}
			std::wstring wide(static_cast<std::size_t>(length), L'\0');
			::MultiByteToWideChar(codePage, flags, a_text.data(), size, wide.data(), length);
			return wide;
		}

		std::string Narrow(std::wstring_view a_text)
		{
			if (a_text.empty()) {
				return {};
			}
			const auto size = static_cast<int>(a_text.size());
			const int  length = ::WideCharToMultiByte(CP_UTF8, 0, a_text.data(), size, nullptr, 0, nullptr, nullptr);
			std::string narrow(static_cast<std::size_t>(length), '\0');
			::WideCharToMultiByte(CP_UTF8, 0, a_text.data(), size, narrow.data(), length, nullptr, nullptr);
			return narrow;
		}
	}

	std::optional<std::string> GetText()
	{
		const Session session;
		if (!session) {
			return std::nullopt;
		}
		const HANDLE data = ::GetClipboardData(CF_UNICODETEXT);
		if (!data) {
			return std::nullopt;
		}
		const auto* chars = static_cast<const wchar_t*>(::GlobalLock(data));
		if (!chars) {
			return std::nullopt;
		}
		// Stop at the first null character, but never read past the memory block.
		const auto capacity = ::GlobalSize(data) / sizeof(wchar_t);
		std::string text = Narrow({ chars, ::wcsnlen(chars, capacity) });
		::GlobalUnlock(data);
		return text;
	}

	bool SetText(std::string_view a_text)
	{
		const std::wstring wide = Widen(a_text);
		const HGLOBAL      memory = ::GlobalAlloc(GMEM_MOVEABLE, (wide.size() + 1) * sizeof(wchar_t));
		if (!memory) {
			return false;
		}
		auto* chars = static_cast<wchar_t*>(::GlobalLock(memory));
		if (!chars) {
			::GlobalFree(memory);
			return false;
		}
		std::ranges::copy(wide, chars);
		chars[wide.size()] = L'\0';
		::GlobalUnlock(memory);

		const Session session;
		if (!session || !::EmptyClipboard() || !::SetClipboardData(CF_UNICODETEXT, memory)) {
			// The clipboard owns the memory only once SetClipboardData succeeds.
			::GlobalFree(memory);
			return false;
		}
		return true;
	}
}
