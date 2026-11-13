// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 open-additemmenu-ng contributors. See LICENSE and EXCEPTIONS.md.

#include "game/Index.h"

#include "core/Text.h"

namespace aim::game
{
	namespace
	{
		// Keywords from Skyrim.esm that decide an item's type.
		constexpr RE::FormID kVendorItemSpellTome = 0x000937A5;
		constexpr RE::FormID kVendorItemRecipe = 0x000F5CB0;
		constexpr RE::FormID kVendorItemOreIngot = 0x000914EC;

		// CheckResourceFiles=1 skips these.
		constexpr std::array kOfficialPlugins{ "Skyrim.esm"sv, "Update.esm"sv, "Dawnguard.esm"sv, "HearthFires.esm"sv, "Dragonborn.esm"sv };

		bool IsOfficial(std::string_view a_plugin)
		{
			return std::ranges::any_of(kOfficialPlugins, [&](std::string_view a_name) { return text::EqualsIgnoreCase(a_name, a_plugin); });
		}

		ItemType BookType(const RE::TESObjectBOOK& a_book)
		{
			if (a_book.HasKeywordID(kVendorItemSpellTome)) {
				return ItemType::kSpellTome;
			}
			// Recipes are the notes, even when they also carry VendorItemBook.
			return a_book.HasKeywordID(kVendorItemRecipe) ? ItemType::kNote : ItemType::kBook;
		}

		std::string_view PathOf(const RE::TESModel& a_model)
		{
			const char* path = a_model.GetModel();
			return path ? std::string_view(path) : std::string_view{};
		}

		class Indexer
		{
		public:
			Indexer(const Settings& a_settings, IndexStats& a_stats) :
				_settings(a_settings),
				_stats(a_stats)
			{}

			Catalog Run(RE::TESDataHandler& a_data)
			{
				for (const auto* file : a_data.files) {
					if (file && file->GetCompileIndex() != 0xFF) {
						_plugins.emplace(file, _catalog.plugins.size());
						_catalog.plugins.push_back(Plugin{ std::string(file->GetFilename()), {} });
					}
				}

				const auto fixed = [](ItemType a_type) { return [a_type](const auto&) { return std::optional(a_type); }; };
				Scan<RE::TESObjectWEAP>(a_data, fixed(ItemType::kWeapon));
				Scan<RE::TESObjectARMO>(a_data, fixed(ItemType::kArmor));
				Scan<RE::TESAmmo>(a_data, fixed(ItemType::kAmmo));
				Scan<RE::AlchemyItem>(a_data, fixed(ItemType::kPotion));
				Scan<RE::IngredientItem>(a_data, fixed(ItemType::kIngredient));
				Scan<RE::ScrollItem>(a_data, fixed(ItemType::kScroll));
				Scan<RE::TESObjectBOOK>(a_data, [](const RE::TESObjectBOOK& a_book) { return std::optional(BookType(a_book)); });
				Scan<RE::TESKey>(a_data, fixed(ItemType::kKey));
				Scan<RE::TESObjectLIGH>(a_data, [](const RE::TESObjectLIGH& a_light) {
					return a_light.CanBeCarried() ? std::optional(ItemType::kLight) : std::nullopt;
				});
				Scan<RE::TESSoulGem>(a_data, fixed(ItemType::kSoulGem));
				// Gold and lockpicks are misc items like any other.
				Scan<RE::TESObjectMISC>(a_data, [](const RE::TESObjectMISC& a_misc) {
					return std::optional(a_misc.HasKeywordID(kVendorItemOreIngot) ? ItemType::kIngot : ItemType::kMisc);
				});
				return std::move(_catalog);
			}

		private:
			template <class T, class TypeOf>
			void Scan(RE::TESDataHandler& a_data, TypeOf a_typeOf)
			{
				for (const auto* form : a_data.GetFormArray<T>()) {
					if (form) {
						if (const auto type = a_typeOf(*form)) {
							Add(*form, *type);
						}
					}
				}
			}

			void Add(const RE::TESForm& a_form, ItemType a_type)
			{
				++_stats.forms;
				const auto* file = a_form.GetFile(0);
				const auto  plugin = file ? _plugins.find(file) : _plugins.end();
				if (plugin == _plugins.end()) {
					return;
				}
				const char* name = a_form.GetName();
				if (!name || !*name || !a_form.GetPlayable()) {
					return;
				}
				auto& target = _catalog.plugins[plugin->second];
				if (MustCheckModel(target.fileName, a_type) && !HasModels(a_form, a_type)) {
					++_stats.missingModels;
					return;
				}
				target.items.push_back(Item{ a_form.GetFormID(), name, a_type });
			}

			// Whether an item's model files exist, by the original DLL's rules. Armor is checked by
			// its world models (the ones shown on the ground), each one it has, and armor without
			// any passes (Dawnguard's SkinNakedSnowElf). Other items are checked by their model,
			// and an item without a model path fails (Skyrim.esm 0001F6, Dragonborn's Tel Mithryn
			// keys).
			bool HasModels(const RE::TESForm& a_form, ItemType a_type)
			{
				if (a_type == ItemType::kArmor) {
					for (const auto& model : static_cast<const RE::TESObjectARMO&>(a_form).worldModels) {
						const auto path = PathOf(model);
						if (!path.empty() && !ModelExists(path)) {
							return false;
						}
					}
					return true;
				}
				const auto* model = a_form.As<RE::TESModel>();
				return model && ModelExists(PathOf(*model));
			}

			// CheckResourceFiles: 0 checks nothing; 1 every plugin but the official ones; 2 every
			// plugin, official ones included, but not armor; 3 everything. Books and scrolls are
			// never checked, nor are the plugins in [IgnoreCheckResourcePlugins].
			bool MustCheckModel(std::string_view a_plugin, ItemType a_type) const
			{
				switch (a_type) {
				case ItemType::kScroll:
				case ItemType::kBook:
				case ItemType::kSpellTome:
				case ItemType::kNote:
					return false;
				default:
					break;
				}
				if (_settings.SkipsResourceCheck(a_plugin)) {
					return false;
				}
				switch (_settings.checkResourceFiles) {
				case 0:
					return false;
				case 1:
					return !IsOfficial(a_plugin);
				case 2:
					return a_type != ItemType::kArmor;
				default:
					return true;
				}
			}

			// Whether the model is a loose file or inside a loaded archive, through the game's own
			// file system. Many items share a model, so each path is looked up once.
			bool ModelExists(std::string_view a_model)
			{
				if (a_model.empty()) {
					return false;
				}
				std::string path;
				if (!text::StartsWithIgnoreCase(a_model, "meshes\\") && !text::StartsWithIgnoreCase(a_model, "meshes/")) {
					path = "meshes\\";
				}
				path += a_model;

				std::string key = path;
				std::ranges::transform(key, key.begin(), [](char c) { return c == '/' ? '\\' : text::LowerAscii(c); });
				if (const auto found = _models.find(key); found != _models.end()) {
					return found->second;
				}
				++_stats.modelLookups;
				const RE::BSResourceNiBinaryStream stream(path);
				const bool exists = stream.good();
				_models.emplace(std::move(key), exists);
				return exists;
			}

			const Settings&                                        _settings;
			IndexStats&                                            _stats;
			Catalog                                                _catalog;
			std::unordered_map<const RE::TESFile*, std::size_t>    _plugins;  // into _catalog.plugins
			std::unordered_map<std::string, bool>                  _models;   // by lowercase path
		};
	}

	Catalog BuildCatalog(const Settings& a_settings, IndexStats& a_stats)
	{
		auto* const data = RE::TESDataHandler::GetSingleton();
		if (!data) {
			return {};
		}
		return Indexer(a_settings, a_stats).Run(*data);
	}
}
