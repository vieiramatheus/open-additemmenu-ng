# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for make_test_plugins.py. They use a small fake Skyrim.esm; no game is needed."""

import json
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import make_test_plugins as mtp  # noqa: E402

LSTRING = struct.pack("<I", 0x1234)  # a string-table ID, as Skyrim.esm stores names


def rec(rtype, form_id, edid, *subs, flags=0):
    return mtp.Record(rtype, form_id, flags, [("EDID", mtp.zstring(edid))] + list(subs))


def light_data(flags):
    data = bytearray(48)
    struct.pack_into("<I", data, 12, flags)
    return bytes(data)


def book(form_id, edid, flags, btype, model="Clutter\\Books\\Book.nif", keywords=(mtp.KEYWORD_BOOK,)):
    return rec("BOOK", form_id, edid, ("FULL", LSTRING), ("MODL", mtp.zstring(model)), ("DESC", LSTRING),
               ("KSIZ", struct.pack("<I", len(keywords))), ("KWDA", struct.pack(f"<{len(keywords)}I", *keywords)),
               ("DATA", bytes([flags, btype]) + bytes(14)), ("CNAM", LSTRING))


def fake_templates():
    keywords = lambda *ids: [("KSIZ", struct.pack("<I", len(ids))), ("KWDA", struct.pack(f"<{len(ids)}I", *ids))]
    return [
        rec("WEAP", 0x12EB7, "IronSword", ("VMAD", b"script"), ("FULL", LSTRING), ("MODL", mtp.zstring("Weapons\\Iron\\LongSword.nif")),
            ("MODT", b"hashes"), ("DESC", LSTRING), ("DATA", bytes(10)), ("DNAM", bytes(100))),
        rec("WEAP", 0x12EB8, "EnchIronSwordFire01", ("FULL", LSTRING), ("MODL", mtp.zstring("Weapons\\Iron\\LongSword.nif")),
            ("EITM", struct.pack("<I", 0x4605A)), ("EAMT", struct.pack("<H", 500)), ("DATA", bytes(10))),
        rec("ARMO", 0x12E49, "ArmorIronCuirass", ("FULL", LSTRING), ("MOD2", mtp.zstring("Armor\\Iron\\Cuirass_GO.nif")),
            ("MO2T", b"hashes"), ("MOD4", mtp.zstring("Armor\\Iron\\F\\Cuirass_GO.nif")), ("MODL", struct.pack("<I", 0x12E4A)),
            ("DATA", bytes(8)), ("DNAM", bytes(4))),
        rec("AMMO", 0x1397D, "IronArrow", ("FULL", LSTRING), ("MODL", mtp.zstring("Weapons\\Iron\\IronArrow.nif")),
            ("DESC", LSTRING), ("DATA", bytes(20)), ("ONAM", LSTRING)),
        rec("ALCH", 0x3EADD, "RestoreHealth01", ("FULL", LSTRING), ("MODL", mtp.zstring("Clutter\\Potion.nif")), ("DATA", bytes(4))),
        rec("INGR", 0x4B0BA, "Wheat01", ("FULL", LSTRING), ("MODL", mtp.zstring("Plants\\Wheat.nif")), ("DATA", bytes(8))),
        rec("MISC", 0x0000F, "Gold001", ("FULL", LSTRING), ("MODL", mtp.zstring("Clutter\\Gold.nif")), ("DATA", bytes(8))),
        rec("MISC", 0x31941, "BasicWoodenBowl01", ("VMAD", b"script"), ("FULL", LSTRING),
            ("MODL", mtp.zstring("Clutter\\Bowl.nif")), ("DATA", bytes(8))),
        rec("MISC", 0x5ACE4, "IngotIron", ("FULL", LSTRING), ("MODL", mtp.zstring("Clutter\\Ingot.nif")),
            *keywords(mtp.KEYWORD_ORE_INGOT, 0x8F95A), ("DATA", bytes(8))),
        rec("MISC", 0x71CF3, "OreIron", ("FULL", LSTRING), ("MODL", mtp.zstring("Clutter\\Ore.nif")),
            *keywords(mtp.KEYWORD_ORE_INGOT), ("DATA", bytes(8))),
        rec("SLGM", 0x2E4E2, "SoulGemPetty", ("FULL", LSTRING), ("MODL", mtp.zstring("Clutter\\SoulGem.nif")), ("DATA", bytes(8))),
        rec("SCRL", 0x9C46E, "FireballScroll", ("FULL", LSTRING), ("MODL", mtp.zstring("Clutter\\Scroll.nif")), ("DESC", LSTRING)),
        book(0xED617, "BookCommon", 0, 0),
        book(0x9E2A7, "SpellTomeFlames", 0x04, 0, keywords=(mtp.KEYWORD_BOOK, mtp.KEYWORD_SPELL_TOME)),
        book(0xE3D9B, "NoteSomething", 0, 0, model="Clutter\\Common\\Note01.nif"),  # notes look like this in Skyrim.esm
        rec("KEYM", 0x2BCF5, "SomeKey", ("FULL", LSTRING), ("MODL", mtp.zstring("Clutter\\Key.nif")), ("DATA", bytes(8))),
        rec("LIGH", 0x1D4EC, "Torch01", ("MODL", mtp.zstring("Clutter\\Torch.nif")), ("FULL", LSTRING), ("DATA", light_data(0x2))),
        # Like Skyrim.esm's QA books: no keywords, string ID 0 for the texts, nothing taught, no value.
        rec("BOOK", 0xED08F, "QAbookFrench", ("OBND", bytes(12)), ("FULL", LSTRING),
            ("MODL", mtp.zstring("Clutter\\Books\\BasicBook04.nif")), ("DESC", struct.pack("<I", 0)),
            ("DATA", mtp.BOOK_DATA.pack(0, 0, 0, 0, 0, 0.0)), ("INAM", struct.pack("<I", 0x153F0)), ("CNAM", struct.pack("<I", 0))),
    ]


def write_fake_esm(path: Path) -> None:
    """Like write_plugin, plus what real masters have: one compressed record and a nested group."""
    mtp.write_plugin(path, [], fake_templates(), "fake master")
    raw = bytearray(path.read_bytes())
    # A compressed copy of a record in its own top-level group, as Skyrim.esm compresses many.
    weapon = rec("WEAP", 0x99999, "CompressedSword", ("FULL", LSTRING), ("MODL", mtp.zstring("x.nif")), ("DATA", bytes(10)))
    body = weapon.to_bytes()[mtp.RECORD.size:]
    packed = struct.pack("<I", len(body)) + zlib.compress(body)
    record = mtp.RECORD.pack(b"WEAP", len(packed), mtp.FLAG_COMPRESSED, 0x99999, 0, 0, 44, 0) + packed
    raw += mtp.GROUP.pack(b"GRUP", mtp.GROUP.size + len(record), b"WEAP", 0, 0, 0, 0) + record
    # A CELL group with a nested group, which the reader must skip without getting lost.
    cell = mtp.Record("CELL", 0x3C, 0, [("EDID", mtp.zstring("Cell"))]).to_bytes()
    nested = mtp.GROUP.pack(b"GRUP", mtp.GROUP.size + len(cell), struct.pack("<I", 0x3C), 6, 0, 0, 0) + cell
    raw += mtp.GROUP.pack(b"GRUP", mtp.GROUP.size + len(nested), b"CELL", 0, 0, 0, 0) + nested
    path.write_bytes(bytes(raw))


class GeneratorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="plugins-test-"))
        cls.esm = cls.tmp / "Skyrim.esm"
        write_fake_esm(cls.esm)
        cls.out = cls.tmp / "out"
        cls.manifest = mtp.generate(cls.esm, cls.out)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def plugin(self, name):
        return mtp.read_plugin(self.out / name)

    def by_edid(self, name):
        return {r.edid(): r for r in self.plugin(name)[1]}

    def test_reader_finds_compressed_records_and_skips_nested_groups(self):
        _, records = mtp.read_plugin(self.esm)
        names = [r.edid() for r in records]
        self.assertIn("CompressedSword", names)
        self.assertIn("Cell", names)
        compressed = next(r for r in records if r.edid() == "CompressedSword")
        self.assertEqual(compressed.get("MODL"), mtp.zstring("x.nif"))
        _, items = mtp.read_plugin(self.esm, {"WEAP"})
        self.assertEqual({r.type for r in items}, {"WEAP"})

    def test_big_subrecords_round_trip(self):
        big = mtp.Record("BOOK", 0x01000800, 0, [("EDID", mtp.zstring("Big")), ("DESC", b"x" * 70000), ("DATA", bytes(16))])
        path = self.tmp / "big.esp"
        mtp.write_plugin(path, ["Skyrim.esm"], [big], "big")
        _, records = mtp.read_plugin(path)
        self.assertEqual(records[0].get("DESC"), b"x" * 70000)
        self.assertEqual(records[0].get("DATA"), bytes(16))

    def test_every_plugin_and_the_manifest_are_written(self):
        for name in ("AIMTest_Big.esp", "AIMTest_Light.esp", "AIMTest_MissingModel.esp", "AIMTest_Edge.esp", "AIMTest_Empty.esp"):
            header, _ = self.plugin(name)
            self.assertEqual(header.type, "TES4")
            masters = [d.rstrip(b"\0").decode() for s, d in header.subs if s == "MAST"]
            self.assertEqual(masters, ["Skyrim.esm"])
        manifest = json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest, json.loads(json.dumps(self.manifest)))
        self.assertEqual(len(self.plugin("AIMTest_Empty.esp")[1]), 0)

    def test_big_has_600_misc_items_from_a_to_z(self):
        header, records = self.plugin("AIMTest_Big.esp")
        self.assertEqual(len(records), 600)
        self.assertEqual({r.type for r in records}, {"MISC"})
        names = [r.get("FULL").rstrip(b"\0").decode() for r in records]
        self.assertTrue(names[0].startswith("A ") and names[-1].startswith("Z "))
        self.assertEqual(names, sorted(names))
        self.assertEqual(records[0].form_id, 0x01000800)
        version, count, next_id = struct.unpack("<fiI", header.get("HEDR"))
        self.assertAlmostEqual(version, 1.7, places=5)
        self.assertEqual((count, next_id), (601, 0x800 + 600))
        self.assertEqual(records[0].get("MODL"), mtp.zstring("Clutter\\Bowl.nif"))  # plain misc, not gold

    def test_light_plugin_is_esl_flagged_with_one_item_per_type(self):
        header, records = self.plugin("AIMTest_Light.esp")
        self.assertTrue(header.flags & mtp.FLAG_ESL)
        self.assertEqual(len(records), len(mtp.ROLE_TAGS))
        self.assertTrue(all(0x800 <= r.form_id & 0xFFFFFF <= 0xFFF for r in records))

    def test_texts_become_inline_and_scripts_go(self):
        for name in ("AIMTest_Light.esp", "AIMTest_Edge.esp", "AIMTest_MissingModel.esp"):
            for r in self.plugin(name)[1]:
                self.assertFalse(r.has("VMAD"), r.edid())
                for sig in mtp.LOCALIZED:
                    data = r.get(sig)
                    if data is not None and not (r.type == "ARMO" and sig == "ONAM"):
                        # Inline text, not a 4-byte string ID; the QA copies keep their texts empty.
                        self.assertTrue(data.endswith(b"\0") and (len(data) > 4 or data == b"\0"), f"{r.edid()} {sig}")

    def test_missing_models(self):
        items = self.by_edid("AIMTest_MissingModel.esp")
        armor = items["AIMTest_Missing_Armor"]
        self.assertEqual(armor.get("MOD2"), mtp.zstring("AIMTest\\Missing\\AIMTest_Missing_Armor.nif"))
        self.assertEqual(armor.get("MOD4"), mtp.zstring("AIMTest\\Missing\\AIMTest_Missing_Armor.nif"))
        self.assertEqual(armor.get("MODL"), struct.pack("<I", 0x12E4A), "the armor addon reference stays")
        self.assertFalse(armor.has("MO2T"))
        weapon = items["AIMTest_Missing_Weapon"]
        self.assertTrue(weapon.get("MODL").startswith(b"AIMTest\\Missing\\"))
        self.assertFalse(weapon.has("MODT"))

    def test_edge_cases(self):
        items = self.by_edid("AIMTest_Edge.esp")
        self.assertFalse(items["AIMTest_Edge_Nameless"].has("FULL"))
        self.assertFalse(items["AIMTest_Edge_Armor"].flags & mtp.FLAG_NONPLAYABLE)
        self.assertTrue(items["AIMTest_Edge_NonPlayableArmor"].flags & mtp.FLAG_NONPLAYABLE)
        self.assertEqual(items["AIMTest_Edge_Cyrillic"].get("FULL"), "Тестовый предмет".encode("utf-8") + b"\0")
        self.assertEqual(mtp.book_data(items["AIMTest_Edge_SpellTome"])[0] & 0x04, 0x04)
        self.assertEqual(items["AIMTest_Edge_Note"].get("MODL"), mtp.zstring("Clutter\\Common\\Note01.nif"))
        self.assertEqual(mtp.book_data(items["AIMTest_Edge_NoteType"]), (0, 0xFF))
        self.assertEqual(mtp.book_data(items["AIMTest_Edge_Book"]), (0, 0))
        self.assertIn(mtp.KEYWORD_ORE_INGOT, items["AIMTest_Edge_Ingot"].keywords())
        no_keyword = items["AIMTest_Edge_IngotNoKeyword"]
        self.assertEqual(no_keyword.keywords(), [0x8F95A])
        self.assertEqual(no_keyword.get("KSIZ"), struct.pack("<I", 1))
        self.assertTrue(mtp.light_flags(items["AIMTest_Edge_Light"]) & 0x2)
        self.assertFalse(mtp.light_flags(items["AIMTest_Edge_FixedLight"]) & 0x2)
        self.assertTrue(items["AIMTest_Edge_EnchWeapon"].has("EITM"))
        self.assertFalse(items["AIMTest_Edge_Weapon"].has("EITM"))
        self.assertEqual(items["AIMTest_Edge_Recipe"].keywords(), [mtp.KEYWORD_RECIPE])
        self.assertEqual(items["AIMTest_Edge_BookAndRecipe"].keywords(), [mtp.KEYWORD_BOOK, mtp.KEYWORD_RECIPE])
        self.assertEqual(items["AIMTest_Edge_TomeNoKeyword"].keywords(), [mtp.KEYWORD_BOOK])
        self.assertEqual(mtp.book_data(items["AIMTest_Edge_TomeNoKeyword"])[0] & 0x04, 0x04)
        self.assertEqual(items["AIMTest_Edge_BookTomeKeyword"].keywords(), [mtp.KEYWORD_BOOK, mtp.KEYWORD_SPELL_TOME])
        subs = [s for s, _ in items["AIMTest_Edge_Recipe"].subs]
        self.assertLess(subs.index("KWDA"), subs.index("DATA"), "keywords stay before DATA")

    def test_qa_book_copies(self):
        items = self.by_edid("AIMTest_Edge.esp")
        qa_name = "à â é è ê ë ù û ü î ï ô ç".encode("utf-8") + b"\0"
        clone = items["AIMTest_Edge_QAClone"]
        self.assertEqual(clone.get("FULL"), qa_name)
        self.assertEqual((clone.get("DESC"), clone.get("CNAM")), (b"\0", b"\0"))
        self.assertEqual(clone.keywords(), [])
        self.assertEqual(mtp.BOOK_DATA.unpack(clone.get("DATA"))[3:], (0, 0, 0.0))
        self.assertEqual(clone.get("INAM"), struct.pack("<I", 0x153F0))
        plain = items["AIMTest_Edge_QACloneAscii"]
        self.assertEqual(plain.get("FULL"), mtp.zstring("AIMTest QA Clone"))
        self.assertEqual(plain.get("DESC"), b"\0")
        # Each of the other copies changes one thing.
        self.assertTrue(items["AIMTest_Edge_QACloneText"].get("DESC").startswith(b"AIMTest QA Clone Text"))
        self.assertEqual(mtp.BOOK_DATA.unpack(items["AIMTest_Edge_QACloneValue"].get("DATA"))[4:], (5, 1.0))
        self.assertEqual(mtp.BOOK_DATA.unpack(items["AIMTest_Edge_QACloneTeaches"].get("DATA"))[3], 0xFFFFFFFF)
        self.assertEqual(items["AIMTest_Edge_QACloneKeyword"].keywords(), [mtp.KEYWORD_BOOK])
        self.assertEqual(items["AIMTest_Edge_AccentBook"].get("FULL"), qa_name)
        self.assertEqual(items["AIMTest_Edge_AccentBook"].keywords(), [mtp.KEYWORD_BOOK])
        self.assertEqual(items["AIMTest_Edge_AccentMisc"].get("FULL"), qa_name)
        self.assertEqual(items["AIMTest_Edge_Japanese"].get("FULL"), "鉄の剣 AIMTest".encode("utf-8") + b"\0")

    def test_existing_items_keep_their_ids(self):
        # New edge items go at the end, so the form IDs of older ones never change.
        items = self.by_edid("AIMTest_Edge.esp")
        self.assertEqual(items["AIMTest_Edge_Nameless"].form_id, 0x01000800)
        self.assertEqual(items["AIMTest_Edge_EnchWeapon"].form_id, 0x01000812)
        self.assertEqual(items["AIMTest_Edge_QAClone"].form_id, 0x01000813)

    def test_set_keywords_adds_and_removes_the_subrecords(self):
        r = mtp.Record("BOOK", 1, 0, [("EDID", b"x\0"), ("DATA", bytes(16))])
        r.set_keywords([5, 6])
        self.assertEqual([s for s, _ in r.subs], ["EDID", "KSIZ", "KWDA", "DATA"])
        r.set_keywords([])
        self.assertEqual([s for s, _ in r.subs], ["EDID", "DATA"])

    def test_output_is_deterministic(self):
        again = self.tmp / "again"
        mtp.generate(self.esm, again)
        for path in self.out.iterdir():
            self.assertEqual(path.read_bytes(), (again / path.name).read_bytes(), path.name)


if __name__ == "__main__":
    unittest.main()
