// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

// Calls the 14 native functions of the script AddItemMenuSE through the Papyrus virtual
// machine, the way AddItemMenu's own scripts do, and writes one JSON line per call.
//
// Calls run one at a time, in a fixed order, so that runs against different DLLs compare line
// by line. The order goes from safe to risky: calls that might crash or hang a careless
// implementation (negative or huge indices, replacements that contain their target) come last,
// so a crash costs as little as possible, and every line is flushed as soon as it's written.

#include "Probe.h"

#include "Json.h"
#include "Win32.h"

#include <atomic>
#include <chrono>
#include <deque>
#include <filesystem>
#include <format>
#include <fstream>
#include <functional>
#include <map>
#include <mutex>
#include <optional>
#include <stop_token>
#include <string>
#include <thread>
#include <vector>

namespace probe
{
	namespace
	{
		using Clock = std::chrono::steady_clock;
		using Variable = RE::BSScript::Variable;
		using Args = std::unique_ptr<RE::BSScript::IFunctionArguments>;
		using Strings = std::vector<std::string>;

		constexpr std::string_view kScript = "AddItemMenuSE";
		// Raise whenever the calls or their inputs change: runs compare only within one plan.
		constexpr int              kPlanVersion = 2;
		constexpr std::size_t      kListCount = 16;
		constexpr auto             kCallTimeout = 30s;

		// Papyrus stores strings case-insensitively and keeps the first casing the game created, so
		// a casing test only works with text the game doesn't already know: "IRON" would reach the
		// DLL as "iron". "Iron Swo", "ron Sword" and "rON sWO" tell prefix from substring matching
		// and case-sensitive from case-insensitive matching.
		const Strings kSearchTexts{
			"", "iron", "Iron Sword", "Iron Swo", "ron Sword", "rON sWO", "a", "zzqx", "Dawnguard",
			"aWNgUA",  // part of "Dawnguard.esm" in a casing nothing else uses
			"Skyrim.esm", "AIMTest", " ",
			"Тестовый",  // the start of the Cyrillic item's name in AIMTest_Edge.esp
			"鉄",        // "iron", Japanese
		};

		const Strings kTranslationKeys{
			"$AIM_NOT_FOUND", "$AIM_SKSE_Required", "$AIM_WEAPON", "$AIM_ARMOR", "$AIM_AMMO",
			"$AIM_POTION", "$AIM_INGREDIENT", "$AIM_MISC", "$AIM_SOULGEM", "$AIM_SCROLL", "$AIM_BOOK",
			"$AIM_SPELLTOME", "$AIM_NOTE", "$AIM_KEY", "$AIM_INGOT", "$AIM_LIGHT",
			"$AIM_SEARCHCHEST_NAME", "$AIM_COPYNAME", "$AIM_SEARCHITEM", "$AIM_PART",
			"$AIM_NO_SUCH_KEY", "", "AIM_WEAPON", "$aim_weapon",
		};

		const Strings kClipboardTexts{
			"Iron Sword", "Железный меч", "鉄の剣", "line one\nline two", "line one\r\nline two", "",
		};

		std::string StringsJson(const Strings& a_strings)
		{
			std::string out = "[";
			for (std::size_t i = 0; i < a_strings.size(); ++i) {
				out += (i ? "," : "") + json::Quote(a_strings[i]);
			}
			return out + "]";
		}

		std::vector<RE::BSFixedString> Fixed(const Strings& a_strings)
		{
			return { a_strings.begin(), a_strings.end() };
		}

		std::string ValueJson(const Variable& a_value)
		{
			if (a_value.IsBool()) {
				return a_value.GetBool() ? "true" : "false";
			}
			if (a_value.IsInt()) {
				return std::to_string(a_value.GetSInt());
			}
			if (a_value.IsFloat()) {
				return std::format("{}", a_value.GetFloat());
			}
			if (a_value.IsString()) {
				return json::GameString(a_value.GetString());
			}
			if (a_value.IsArray()) {
				const auto array = a_value.GetArray();
				if (!array) {
					return "null";
				}
				std::string out = "[";
				bool        first = true;
				for (const auto& element : *array) {
					out += (first ? "" : ",") + ValueJson(element);
					first = false;
				}
				return out + "]";
			}
			if (a_value.IsObject()) {
				return R"("<object>")";
			}
			return "null";
		}

		std::string FormJson(const RE::TESForm* a_form)
		{
			const auto* file = a_form->GetFile(0);
			const auto* name = a_form->GetName();
			return std::format(
				R"({{"file":{},"id":"{:06X}","type":"{}","name":{},"playable":{}}})",
				file ? json::GameString(file->GetFilename()) : "null",
				a_form->GetLocalFormID(),
				RE::FormTypeToString(a_form->GetFormType()),
				json::GameString(name ? name : ""),
				a_form->GetPlayable());
		}

		std::int64_t NowMs()
		{
			return std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now().time_since_epoch()).count();
		}

		// Receives a call's result from the virtual machine and hands it to the main thread.
		class Callback final : public RE::BSScript::IStackCallbackFunctor
		{
		public:
			explicit Callback(std::function<void(Variable)> a_onResult) :
				_onResult(std::move(a_onResult))
			{}

			void operator()(Variable a_result) override { _onResult(std::move(a_result)); }
			void SetObject(const RE::BSTSmartPointer<RE::BSScript::Object>&) override {}

		private:
			std::function<void(Variable)> _onResult;
		};

		struct Step
		{
			std::string                                         phase;
			std::string                                         fn;  // empty: no call, only 'before' and 'after'
			std::function<Args()>                               args;
			std::string                                         argsJson{ "[]" };
			std::function<void()>                               before;
			std::function<void(const Variable&, std::string&)>  after;  // may add JSON fields and steps
		};

		class Runner
		{
		public:
			explicit Runner(Config a_config) :
				_config(std::move(a_config))
			{}

			void Start()
			{
				std::error_code error;
				std::filesystem::create_directories(_config.output.parent_path(), error);
				_out.open(_config.output, std::ios::binary | std::ios::trunc);
				if (!_out) {
					SKSE::log::error("Could not open the output file {}", _config.output.string());
					Quit();
					return;
				}
				FindLists();
				WriteHeader();
				_watchdog = std::jthread([this](std::stop_token a_stop) { Watch(a_stop); });

				PlanGetters();
				PlanTranslations();
				PlanReplace();
				Marker("entries", [this] { PlanEntries(); });
				Next();
			}

		private:
			// -- the plan

			void PlanGetters()
			{
				Add({ "getters", "AIM_GetOrderListSize", {}, "[]", {}, [this](const Variable& a_ret, std::string&) {
						 _orderSize = a_ret.IsInt() ? a_ret.GetSInt() : 0;
					 } });
				for (const auto* fn : { "AIM_GetNameSearchKeyCode", "AIM_GetQuantityChangeKeyCode",
						 "AIM_GetSortOrderKeyCode", "AIM_GetClipboardKeyCode" }) {
					Add({ "getters", fn });
				}
				for (std::int32_t type = 0; type < static_cast<std::int32_t>(kListCount); ++type) {
					AddQuantity("getters", type);
				}
			}

			void PlanTranslations()
			{
				for (const auto& key : kTranslationKeys) {
					Add({ "translation", "AIM_GetTranslation",
						[key] { return Args{ RE::MakeFunctionArguments(RE::BSFixedString(key)) }; },
						StringsJson({ key }) });
				}
			}

			void AddReplace(const std::string& a_phase, const std::string& a_text, const std::string& a_target, const std::string& a_with)
			{
				Add({ a_phase, "AIM_Replace",
					[=] { return Args{ RE::MakeFunctionArguments(RE::BSFixedString(a_text), RE::BSFixedString(a_target), RE::BSFixedString(a_with)) }; },
					StringsJson({ a_text, a_target, a_with }) });
			}

			void AddReplaceArray(const std::string& a_phase, const std::string& a_text, const Strings& a_targets, const Strings& a_with)
			{
				Add({ a_phase, "AIM_ReplaceArray",
					[=] { return Args{ RE::MakeFunctionArguments(RE::BSFixedString(a_text), Fixed(a_targets), Fixed(a_with)) }; },
					std::format("[{},{},{}]", json::Quote(a_text), StringsJson(a_targets), StringsJson(a_with)) });
			}

			// Made-up words, none of them in the game and none sharing a word in another casing with
			// another test, so that every string reaches the DLL exactly as written here.
			void PlanReplace()
			{
				AddReplace("replace", "Zork and Zork again", "Zork", "Bork");          // several occurrences
				AddReplace("replace", "plimsoll", "xyzzyq", "vvqq");                   // target not found
				AddReplace("replace", "plimsoll", "", "vvqq");                         // empty target
				AddReplace("replace", "Qwyzz qwyzz QWYZZ", "qwyzz", "Mx7");            // case differences
				AddReplace("replace", "", "xyzzyq", "vvqq");                           // empty text
				AddReplace("replace", "qqqq", "qq", "w7");                             // overlapping
				AddReplace("replace", "plimsoll", "lim", "");                          // empty replacement
				AddReplace("replace", "plimsoll", "plimsoll", "zorkmid");              // the whole text
				AddReplace("replace", "{NAME} copied", "{NAME}", "Iron Sword");        // as ContainerScript uses it
				AddReplace("replace", "Search: {SEARCH_STRING}", "{SEARCH_STRING}", "zorkmid");

				AddReplaceArray("replace", "plugh-frob-gnusto", { "plugh", "frob" }, { "P1", "F2" });  // pairs
				AddReplaceArray("replace", "plimsoll", {}, {});                                        // empty arrays
				AddReplaceArray("replace", "plugh-frob", { "plugh", "frob" }, { "P1" });               // more targets
				AddReplaceArray("replace", "plugh-frob", { "plugh" }, { "P1", "F2" });                 // more replacements
				AddReplaceArray("replace", "plugh-frob", { "plugh", "P1" }, { "P1", "F2" });           // order matters
				AddReplaceArray("replace", "plugh-frob", { "plugh", "xyzzyq" }, { "P1", "F2" });       // one target missing
				AddReplaceArray("replace", "Wumpus WUMPUS", { "wumpus" }, { "W9" });                   // case differences
			}

			void PlanEntries()
			{
				const std::int32_t modes = _orderSize > 0 && _orderSize <= 64 ? _orderSize : 1;
				for (std::int32_t mode = 0; mode <= modes; ++mode) {  // the last one is out of range
					for (const auto& text : kSearchTexts) {
						auto after = mode == 0 && text.empty() ?
						                 std::function([this](const Variable& a_ret, std::string&) { CollectLeaves(a_ret); }) :
						                 std::function<void(const Variable&, std::string&)>{};
						Add({ "entries", "AIM_GetEntries",
							[mode, text] { return Args{ RE::MakeFunctionArguments(std::int32_t{ mode }, RE::BSFixedString(text)) }; },
							std::format("[{},{}]", mode, json::Quote(text)), {}, std::move(after) });
					}
				}
				Marker("items", [this] { PlanItems(); });
			}

			// Leaf entries ("name;;parent;;id;;callback;;hasChildren" with hasChildren 0): AIM_GetItems
			// is called with both their id and their callback, since either may be what a pick reports.
			void CollectLeaves(const Variable& a_entries)
			{
				const auto array = a_entries.IsArray() ? a_entries.GetArray() : nullptr;
				if (!array) {
					return;
				}
				for (const auto& element : *array) {
					if (!element.IsString()) {
						continue;
					}
					const std::string entry(element.GetString());
					Strings           fields;
					for (std::size_t start = 0;;) {
						const auto end = entry.find(";;", start);
						fields.push_back(entry.substr(start, end - start));
						if (end == std::string::npos) {
							break;
						}
						start = end + 2;
					}
					if (fields.size() != 5 || fields[4] != "0") {
						continue;
					}
					for (const auto [field, label] : { std::pair{ 2, "id" }, std::pair{ 3, "callback" } }) {
						try {
							const auto value = std::stoi(fields[field]);
							_leafSources[value].push_back(std::format("{}:{}", label, fields[0]));
						} catch (const std::exception&) {
						}
					}
				}
			}

			void AddItems(const std::string& a_phase, std::int32_t a_index, const std::string& a_text, bool a_clearFirst, const std::string& a_note)
			{
				a_clearFirst = a_clearFirst && _config.clearLists;
				if (_config.skipItems.contains(a_index)) {
					Marker(a_phase, [this, a_index, a_note] {
						Write(std::format(R"({{"skipped":"AIM_GetItems","index":{},"note":{}}})", a_index, json::GameString(a_note)));
					});
					return;
				}
				Add({ a_phase, "AIM_GetItems",
					[this, a_index, a_text] { return Args{ RE::MakeFunctionArguments(std::int32_t{ a_index }, std::vector<RE::BGSListForm*>(_lists), RE::BSFixedString(a_text)) }; },
					std::format(R"([{},"<AIM_00..AIM_15>",{}])", a_index, json::Quote(a_text)),
					a_clearFirst ? std::function([this] { ClearLists(); }) : std::function<void()>{},
					[this, a_note](const Variable&, std::string& a_extra) {
						if (!a_note.empty()) {
							a_extra += R"(,"note":)" + json::GameString(a_note);
						}
						a_extra += R"(,"lists":)" + ListsJson();
					} });
			}

			void PlanItems()
			{
				if (!_leafSources.contains(0)) {
					_leafSources[0].push_back("extra:not a leaf id");
				}
				std::vector<std::int32_t> ids;  // indices that are some leaf's id
				for (const auto& [index, sources] : _leafSources) {
					std::map<std::string, std::vector<std::string>> byField;
					for (const auto& source : sources) {
						const auto colon = source.find(':');
						byField[source.substr(0, colon)].push_back(source.substr(colon + 1));
					}
					std::string note;
					for (const auto& [field, names] : byField) {
						std::string part = names.size() > 3 ? std::format("{} of {} entries", field, names.size()) : field + ":";
						if (names.size() <= 3) {
							for (std::size_t i = 0; i < names.size(); ++i) {
								part += (i ? ", " : " ") + names[i];
							}
						}
						note += (note.empty() ? "" : " | ") + part;
					}
					if (byField.contains("id")) {
						ids.push_back(index);
					}
					AddItems("items", index, "", true, note);
				}
				for (const auto& text : kSearchTexts) {
					AddItems("search", 999, text, true, "");
				}
				// Does AIM_GetItems empty the lists itself? The second call runs without clearing.
				if (ids.size() >= 2) {
					AddItems("accumulate", ids[0], "", true, "first of two");
					AddItems("accumulate", ids[1], "", false, "second of two, lists not cleared in between");
				}
				Marker("clipboard", [this] {
					if (_config.clipboard) {
						PlanClipboard();
					}
					PlanRisky();
				});
			}

			void PlanClipboard()
			{
				Marker("clipboard", [this] {
					_savedClipboard = win32::ReadClipboard();
					Write(std::format(R"({{"note":"clipboard saved","hadText":{}}})", _savedClipboard.has_value()));
				});
				for (const auto& text : kClipboardTexts) {
					Add({ "clipboard", "AIM_SetClipboardText",
						[text] { return Args{ RE::MakeFunctionArguments(RE::BSFixedString(text)) }; },
						StringsJson({ text }), {},
						[](const Variable&, std::string& a_extra) {
							const auto now = win32::ReadClipboard();
							a_extra += R"(,"clipboardNow":)" + (now ? json::Quote(*now) : std::string("null"));
						} });
					Add({ "clipboard", "AIM_GetClipboardText" });
				}
				// Text put on the clipboard by another program, as a player would copy it.
				for (const auto& text : kClipboardTexts) {
					Add({ "clipboard", "AIM_GetClipboardText", {}, "[]",
						[text] { win32::WriteClipboard(text); },
						[text](const Variable&, std::string& a_extra) { a_extra += R"(,"clipboardSetTo":)" + json::Quote(text); } });
				}
				Marker("clipboard", [this] {
					const bool restored = _savedClipboard ? win32::WriteClipboard(*_savedClipboard) : win32::ClearClipboard();
					Write(std::format(R"({{"note":"clipboard restored","ok":{}}})", restored));
				});
			}

			void AddQuantity(const std::string& a_phase, std::int32_t a_type)
			{
				Add({ a_phase, "AIM_GetQuantity",
					[a_type] { return Args{ RE::MakeFunctionArguments(std::int32_t{ a_type }) }; },
					std::format("[{}]", a_type) });
			}

			void PlanRisky()
			{
				for (const std::int32_t type : { -1, 16, 999 }) {
					AddQuantity("risky", type);
				}
				Add({ "risky", "AIM_GetEntries",
					[] { return Args{ RE::MakeFunctionArguments(std::int32_t{ -1 }, RE::BSFixedString("")) }; },
					R"([-1,""])" });
				for (const std::int32_t index : { -1, 100000 }) {
					AddItems("risky", index, "", true, "");
				}
				AddReplace("risky", "grue grue", "grue", "grue grue");      // replacement contains the target
				AddReplaceArray("risky", "grue", { "grue" }, { "grue grue" });
				Add({ "risky", "AIM_CloseContainerMenu" });                 // with no container open
			}

			// -- running

			void Add(Step a_step) { _steps.push_back(std::move(a_step)); }

			void Marker(const std::string& a_phase, std::function<void()> a_action)
			{
				Add({ a_phase, "", {}, "[]", {}, [action = std::move(a_action)](const Variable&, std::string&) { action(); } });
			}

			void Next()
			{
				while (!_finished && !_steps.empty()) {
					Step step = std::move(_steps.front());
					_steps.pop_front();
					if (step.before) {
						step.before();
					}
					if (step.fn.empty()) {
						std::string unused;
						if (step.after) {
							step.after(Variable{}, unused);
						}
						continue;
					}
					_current = std::move(step);
					++_seq;
					// Written before the call: if the game dies inside it, this is the last line.
					Write(std::format(R"({{"seq":{},"calling":"{}","args":{}}})", _seq, _current->fn, _current->argsJson));
					Dispatch();
					return;
				}
				Finish("done");
			}

			void Dispatch()
			{
				auto* const vm = RE::BSScript::Internal::VirtualMachine::GetSingleton();
				const Args  args = _current->args ? _current->args() : Args{ RE::MakeFunctionArguments() };
				const auto  seq = _seq;
				RE::BSTSmartPointer<RE::BSScript::IStackCallbackFunctor> callback{ new Callback([this, seq](Variable a_result) {
					SKSE::GetTaskInterface()->AddTask([this, seq, result = std::move(a_result)] { OnResult(seq, result); });
				}) };
				_dispatched = Clock::now();
				_pendingSince = NowMs();
				_pendingSeq = seq;
				if (!vm || !vm->DispatchStaticCall(RE::BSFixedString(kScript), RE::BSFixedString(_current->fn), args.get(), callback)) {
					_pendingSeq = 0;
					Write(std::format(R"({{"seq":{},"fn":"{}","error":"could not dispatch the call"}})", seq, _current->fn));
					_current.reset();
					SKSE::GetTaskInterface()->AddTask([this] { Next(); });
				}
			}

			void OnResult(std::uint32_t a_seq, const Variable& a_result)
			{
				if (_finished || !_current || a_seq != _seq) {
					return;  // late, after a timeout
				}
				_pendingSeq = 0;
				const double ms = std::chrono::duration<double, std::milli>(Clock::now() - _dispatched).count();
				std::string  extra;
				if (_current->after) {
					_current->after(a_result, extra);
				}
				Write(std::format(R"({{"seq":{},"phase":"{}","fn":"{}","args":{},"ret":{},"ms":{:.1f}{}}})",
					_seq, _current->phase, _current->fn, _current->argsJson, ValueJson(a_result), ms, extra));
				_current.reset();
				Next();
			}

			// Runs on its own thread. A call that never returns may mean the game is stuck inside it,
			// so the line is written from here; the main thread may never run again.
			void Watch(std::stop_token a_stop)
			{
				while (!a_stop.stop_requested()) {
					std::this_thread::sleep_for(1s);
					const auto seq = _pendingSeq.load();
					if (seq != 0 && NowMs() - _pendingSince.load() > std::chrono::milliseconds(kCallTimeout).count()) {
						Write(std::format(R"({{"seq":{},"error":"no result after {} seconds"}})", seq, kCallTimeout.count()));
						_pendingSeq = 0;
						SKSE::GetTaskInterface()->AddTask([this] { Finish("timeout"); });
						return;
					}
				}
			}

			void Finish(std::string_view a_how)
			{
				if (_finished) {
					return;
				}
				_finished = true;
				_watchdog.request_stop();
				Write(std::format(R"({{"done":{},"calls":{}}})", json::Quote(a_how), _seq));
				{
					std::scoped_lock lock(_writeLock);
					_out.close();
				}
				SKSE::log::info("Probe finished ({}) after {} calls", a_how, _seq);
				Quit();
			}

			void Quit() const
			{
				if (_config.quit) {
					RunConsole("qqq");
				}
			}

			// -- output

			void Write(std::string_view a_line)
			{
				std::scoped_lock lock(_writeLock);
				if (_out.is_open()) {
					_out << a_line << '\n';
					_out.flush();
				}
			}

			void FindLists()
			{
				auto* const data = RE::TESDataHandler::GetSingleton();
				for (std::uint32_t i = 0; i < kListCount; ++i) {
					_lists.push_back(data ? data->LookupForm<RE::BGSListForm>(_config.firstList + i, _config.listPlugin) : nullptr);
				}
			}

			void ClearLists()
			{
				for (auto* const list : _lists) {
					if (list) {
						list->forms.clear();
						if (list->scriptAddedTempForms) {
							list->scriptAddedTempForms->clear();
						}
					}
				}
			}

			std::string ListsJson() const
			{
				std::string out = "[";
				for (std::size_t i = 0; i < _lists.size(); ++i) {
					out += i ? ",[" : "[";
					bool first = true;
					if (_lists[i]) {
						_lists[i]->ForEachForm([&](RE::TESForm* a_form) {
							out += (first ? "" : ",") + FormJson(a_form);
							first = false;
							return RE::BSContainer::ForEachResult::kContinue;
						});
					}
					out += "]";
				}
				return out + "]";
			}

			void WriteHeader()
			{
				std::string plugins;
				if (auto* const data = RE::TESDataHandler::GetSingleton()) {
					for (const auto* file : data->files) {
						if (file && file->GetCompileIndex() != 0xFF) {
							plugins += std::format(R"({}{{"name":{},"light":{}}})", plugins.empty() ? "" : ",",
								json::GameString(file->GetFilename()), file->IsLight());
						}
					}
				}
				std::string lists;
				for (std::size_t i = 0; i < _lists.size(); ++i) {
					std::size_t count = 0;
					if (_lists[i]) {
						_lists[i]->ForEachForm([&](RE::TESForm*) { ++count; return RE::BSContainer::ForEachResult::kContinue; });
					}
					lists += std::format(R"({}{{"index":{},"id":"{:06X}","found":{},"forms":{}}})", i ? "," : "",
						i, _config.firstList + static_cast<RE::FormID>(i), _lists[i] != nullptr, count);
				}
				Write(std::format(
					R"({{"probe":"AIMProbe","version":"{}","plan":{},"skyrim":"{}","started":"{:%FT%TZ}","cell":{},"clipboard":{},"listPlugin":{},"lists":[{}],"plugins":[{}]}})",
					SKSE::GetPluginVersion().string("."), kPlanVersion, REL::Module::get().version().string("."),
					std::chrono::floor<std::chrono::seconds>(std::chrono::system_clock::now()),
					json::Quote(_config.cell), _config.clipboard, json::Quote(_config.listPlugin), lists, plugins));
			}

			Config                                                _config;
			std::ofstream                                         _out;
			std::mutex                                            _writeLock;
			std::deque<Step>                                      _steps;
			std::optional<Step>                                   _current;
			Clock::time_point                                     _dispatched;
			std::uint32_t                                         _seq{ 0 };
			std::int32_t                                          _orderSize{ 0 };
			std::vector<RE::BGSListForm*>                         _lists;
			std::map<std::int32_t, Strings>                       _leafSources;
			std::optional<std::string>                            _savedClipboard;
			bool                                                  _finished{ false };
			std::atomic<std::uint32_t>                            _pendingSeq{ 0 };
			std::atomic<std::int64_t>                             _pendingSince{ 0 };
			std::jthread                                          _watchdog;
		};

		std::unique_ptr<Runner> g_runner;

		std::string Trim(std::string_view a_text)
		{
			const auto first = a_text.find_first_not_of(" \t\r\n");
			const auto last = a_text.find_last_not_of(" \t\r\n");
			return first == std::string_view::npos ? std::string{} : std::string(a_text.substr(first, last - first + 1));
		}
	}

	std::optional<Config> LoadConfig(const std::filesystem::path& a_file)
	{
		std::ifstream in(a_file, std::ios::binary);
		if (!in) {
			return std::nullopt;
		}
		Config      config;
		std::string section;
		std::string line;
		while (std::getline(in, line)) {
			line = Trim(line);
			if (line.empty() || line[0] == ';' || line[0] == '#') {
				continue;
			}
			if (line.front() == '[' && line.back() == ']') {
				section = Trim(std::string_view(line).substr(1, line.size() - 2));
				continue;
			}
			const auto equals = line.find('=');
			if (section != "Probe" || equals == std::string::npos) {
				continue;
			}
			const auto key = Trim(std::string_view(line).substr(0, equals));
			const auto value = Trim(std::string_view(line).substr(equals + 1));
			try {
				if (key == "Output") {
					config.output = std::filesystem::path(std::u8string(value.begin(), value.end()));
				} else if (key == "Cell") {
					config.cell = value;
				} else if (key == "Quit") {
					config.quit = value != "0";
				} else if (key == "Clipboard") {
					config.clipboard = value != "0";
				} else if (key == "ClearLists") {
					config.clearLists = value != "0";
				} else if (key == "SkipItems") {
					for (std::size_t start = 0; start < value.size();) {
						const auto comma = value.find(',', start);
						const auto item = Trim(std::string_view(value).substr(start, comma == std::string::npos ? std::string::npos : comma - start));
						if (!item.empty()) {
							config.skipItems.insert(std::stoi(item));
						}
						start = comma == std::string::npos ? value.size() : comma + 1;
					}
				} else if (key == "ListPlugin") {
					config.listPlugin = value;
				} else if (key == "FirstList") {
					config.firstList = static_cast<RE::FormID>(std::stoul(value, nullptr, 0));
				}
			} catch (const std::exception&) {
				SKSE::log::warn("Ignoring {}={} in {}", key, value, a_file.string());
			}
		}
		if (config.output.empty()) {
			return std::nullopt;
		}
		if (!config.output.is_absolute()) {
			// The game's working folder is the game folder; a relative path would write there.
			SKSE::log::error("Output in {} must be an absolute path, not {}", a_file.string(), config.output.string());
			return std::nullopt;
		}
		return config;
	}

	void RunConsole(std::string_view a_command)
	{
		const auto factory = RE::IFormFactory::GetConcreteFormFactoryByType<RE::Script>();
		auto* const script = factory ? factory->Create() : nullptr;
		if (!script) {
			SKSE::log::error("Could not create a console script for '{}'", a_command);
			return;
		}
		SKSE::log::info("Console: {}", a_command);
		script->SetCommand(a_command);
		script->CompileAndRun(nullptr);
		delete script;
	}

	void Start(const Config& a_config)
	{
		if (g_runner) {
			return;
		}
		SKSE::log::info("Probe starting, writing {}", a_config.output.string());
		g_runner = std::make_unique<Runner>(a_config);
		g_runner->Start();
	}
}
