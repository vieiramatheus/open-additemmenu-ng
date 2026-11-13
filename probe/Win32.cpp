// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

// Compiled without the precompiled header (see CMakeLists.txt).

#include "Win32.h"

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>

#include <algorithm>

namespace probe::win32
{
	namespace
	{
		std::wstring Widen(std::string_view a_text, UINT a_codePage)
		{
			if (a_text.empty()) {
				return {};
			}
			const auto size = static_cast<int>(a_text.size());
			const int  length = ::MultiByteToWideChar(a_codePage, 0, a_text.data(), size, nullptr, 0);
			std::wstring wide(static_cast<std::size_t>(length), L'\0');
			::MultiByteToWideChar(a_codePage, 0, a_text.data(), size, wide.data(), length);
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

		// Another program may hold the clipboard for a moment.
		bool OpenClipboardWithRetry()
		{
			for (int attempt = 0; attempt < 20; ++attempt) {
				if (::OpenClipboard(nullptr)) {
					return true;
				}
				::Sleep(25);
			}
			return false;
		}
	}

	std::optional<std::string> ReadClipboard()
	{
		if (!OpenClipboardWithRetry()) {
			return std::nullopt;
		}
		std::optional<std::string> text;
		if (const HANDLE data = ::GetClipboardData(CF_UNICODETEXT)) {
			if (const auto* chars = static_cast<const wchar_t*>(::GlobalLock(data))) {
				text = Narrow(chars);
				::GlobalUnlock(data);
			}
		}
		::CloseClipboard();
		return text;
	}

	bool WriteClipboard(std::string_view a_utf8)
	{
		const std::wstring wide = Widen(a_utf8, CP_UTF8);
		if (!OpenClipboardWithRetry()) {
			return false;
		}
		bool written = false;
		if (::EmptyClipboard()) {
			if (const HGLOBAL memory = ::GlobalAlloc(GMEM_MOVEABLE, (wide.size() + 1) * sizeof(wchar_t))) {
				if (auto* chars = static_cast<wchar_t*>(::GlobalLock(memory))) {
					std::ranges::copy(wide, chars);
					chars[wide.size()] = L'\0';
					::GlobalUnlock(memory);
					written = ::SetClipboardData(CF_UNICODETEXT, memory) != nullptr;
				}
				if (!written) {
					::GlobalFree(memory);
				}
			}
		}
		::CloseClipboard();
		return written;
	}

	bool ClearClipboard()
	{
		if (!OpenClipboardWithRetry()) {
			return false;
		}
		const bool emptied = ::EmptyClipboard() != FALSE;
		::CloseClipboard();
		return emptied;
	}

	std::string Cp1252ToUtf8(std::string_view a_bytes)
	{
		return Narrow(Widen(a_bytes, 1252));
	}
}
