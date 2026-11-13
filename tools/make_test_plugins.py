#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate the plugins used by the in-game tests.

  AIMTest_Big.esp           600 misc items named A to Z, for splitting groups into parts
  AIMTest_Light.esp         a light (ESL-flagged) plugin with one item of each type
  AIMTest_MissingModel.esp  items whose model files don't exist, for CheckResourceFiles
  AIMTest_Edge.esp          inclusion and type edge cases (see EDGE_ITEMS)
  AIMTest_Empty.esp         no records at all

Items are copies of records from Skyrim.esm, so every record type keeps a layout the game
accepts. Only what a test needs changes: the editor ID, the name and other texts (Skyrim.esm
stores those in string tables, these plugins store them inline), model paths, and a few flags or
keywords. Scripts attached to the originals are dropped. A manifest.json next to the plugins
lists every item with what it is meant to test.

  make_test_plugins.py --skyrim "D:/Games/Skyrim Special Edition/Data/Skyrim.esm" --out testplugins

The output depends only on Skyrim.esm, so the same Skyrim.esm always gives the same plugins.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from pathlib import Path

RECORD = struct.Struct("<4sIIIHHHH")  # type, data size, flags, form ID, timestamp, VC info, form version, unknown
GROUP = struct.Struct("<4sI4siHHI")   # "GRUP", size with header, label, group type, timestamp, VC info, unknown
SUB = struct.Struct("<4sH")

FLAG_COMPRESSED = 0x00040000
FLAG_NONPLAYABLE = 0x00000004  # on ARMO records
FLAG_ESL = 0x00000200          # on the TES4 header
FORM_VERSION = 44
FIRST_OBJECT_ID = 0x800

KEYWORD_ORE_INGOT = 0x000914EC  # VendorItemOreIngot
FORM_GOLD = 0x0000000F
FORM_LOCKPICK = 0x0000000A

ITEM_TYPES = ("SCRL", "ARMO", "BOOK", "INGR", "LIGH", "MISC", "KEYM", "ALCH", "SLGM", "WEAP", "AMMO")
# Subrecords that hold string-table IDs in a localized plugin such as Skyrim.esm.
LOCALIZED = {"FULL", "DESC", "CNAM", "ONAM"}


class PluginError(Exception):
    pass


def zstring(text: str) -> bytes:
    return text.encode("utf-8") + b"\0"


class Record:
    def __init__(self, rtype, form_id, flags=0, subs=None, version=FORM_VERSION, stamp=0, vc=0, unknown=0):
        self.type = rtype
        self.form_id = form_id
        self.flags = flags
        self.subs = list(subs or [])
        self.version, self.stamp, self.vc, self.unknown = version, stamp, vc, unknown

    def copy(self) -> "Record":
        return Record(self.type, self.form_id, self.flags, self.subs, self.version, self.stamp, self.vc, self.unknown)

    def get(self, sig: str) -> bytes | None:
        return next((data for s, data in self.subs if s == sig), None)

    def has(self, sig: str) -> bool:
        return any(s == sig for s, _ in self.subs)

    def set(self, sig: str, data: bytes) -> None:
        """Replaces the first subrecord with this signature; there must be one."""
        for i, (s, _) in enumerate(self.subs):
            if s == sig:
                self.subs[i] = (sig, data)
                return
        raise PluginError(f"{self.edid()} has no {sig} to replace")

    def remove(self, *sigs: str) -> None:
        self.subs = [(s, d) for s, d in self.subs if s not in sigs]

    def edid(self) -> str:
        data = self.get("EDID")
        return data.rstrip(b"\0").decode("cp1252") if data else f"{self.form_id:08X}"

    def keywords(self) -> list[int]:
        data = self.get("KWDA") or b""
        return list(struct.unpack(f"<{len(data) // 4}I", data))

    def set_keywords(self, keywords: list[int]) -> None:
        self.set("KSIZ", struct.pack("<I", len(keywords)))
        self.set("KWDA", struct.pack(f"<{len(keywords)}I", *keywords))

    def to_bytes(self) -> bytes:
        body = bytearray()
        for sig, data in self.subs:
            if len(data) > 0xFFFF:
                body += SUB.pack(b"XXXX", 4) + struct.pack("<I", len(data)) + SUB.pack(sig.encode(), 0)
            else:
                body += SUB.pack(sig.encode(), len(data))
            body += data
        flags = self.flags & ~FLAG_COMPRESSED
        return RECORD.pack(self.type.encode(), len(body), flags, self.form_id, self.stamp, self.vc,
                           self.version, self.unknown) + bytes(body)


def parse_subrecords(data: bytes) -> list[tuple[str, bytes]]:
    subs, i, big = [], 0, None
    while i < len(data):
        sig, size = SUB.unpack_from(data, i)
        i += SUB.size
        if big is not None:
            size, big = big, None
        payload = data[i:i + size]
        i += size
        if sig == b"XXXX":
            big = struct.unpack("<I", payload)[0]
            continue
        subs.append((sig.decode("ascii"), payload))
    return subs


def read_plugin(path: Path, types: set[str] | None = None) -> tuple[Record, list[Record]]:
    """The TES4 header and the records of the given top-level groups (all groups if None)."""
    raw = Path(path).read_bytes()
    header, records = None, []

    def record_at(pos: int) -> tuple[Record, int]:
        rtype, size, flags, form_id, stamp, vc, version, unknown = RECORD.unpack_from(raw, pos)
        data = raw[pos + RECORD.size:pos + RECORD.size + size]
        if flags & FLAG_COMPRESSED:
            data = zlib.decompress(data[4:])
        rec = Record(rtype.decode("ascii"), form_id, flags & ~FLAG_COMPRESSED, parse_subrecords(data),
                     version, stamp, vc, unknown)
        return rec, pos + RECORD.size + size

    def walk(start: int, end: int, keep: bool) -> None:
        pos = start
        while pos < end:
            if raw[pos:pos + 4] == b"GRUP":
                _, size, label, gtype, *_ = GROUP.unpack_from(raw, pos)
                inner = keep if gtype != 0 else (types is None or label.decode("ascii", "replace") in types)
                if inner:
                    walk(pos + GROUP.size, pos + size, True)
                pos += size
            else:
                rec, pos = record_at(pos)
                if keep:
                    records.append(rec)

    if raw[:4] != b"TES4":
        raise PluginError(f"{path} is not a plugin")
    header, pos = record_at(0)
    walk(pos, len(raw), False)
    return header, records


def write_plugin(path: Path, masters: list[str], records: list[Record], description: str, light: bool = False) -> None:
    groups = {}
    for rec in records:
        groups.setdefault(rec.type, []).append(rec)
    body = bytearray()
    for rtype in [t for t in ITEM_TYPES if t in groups] + [t for t in groups if t not in ITEM_TYPES]:
        content = b"".join(rec.to_bytes() for rec in groups[rtype])
        body += GROUP.pack(b"GRUP", GROUP.size + len(content), rtype.encode(), 0, 0, 0, 0) + content
    next_id = max([FIRST_OBJECT_ID - 1] + [rec.form_id & 0xFFFFFF for rec in records]) + 1
    subs = [("HEDR", struct.pack("<fiI", 1.7, len(records) + len(groups), next_id)),
            ("CNAM", zstring("open-additemmenu-ng test generator")),
            ("SNAM", zstring(description))]
    for master in masters:
        subs += [("MAST", zstring(master)), ("DATA", struct.pack("<Q", 0))]
    header = Record("TES4", 0, FLAG_ESL if light else 0, subs)
    Path(path).write_bytes(header.to_bytes() + bytes(body))


# ---------------------------------------------------------------------------------------
# Templates from Skyrim.esm


def book_data(rec: Record) -> tuple[int, int]:
    data = rec.get("DATA") or b"\0\0"
    return data[0], data[1]  # flags, type


def light_flags(rec: Record) -> int:
    data = rec.get("DATA") or b""
    return struct.unpack_from("<I", data, 12)[0] if len(data) >= 16 else 0


class Templates:
    def __init__(self, records: list[Record]):
        self.by_type: dict[str, list[Record]] = {}
        self.by_edid: dict[str, Record] = {}
        for rec in records:
            self.by_type.setdefault(rec.type, []).append(rec)
            self.by_edid[rec.edid().lower()] = rec

    def pick(self, rtype: str, edid: str | None = None, test=lambda rec: True, named: bool = True) -> Record:
        if edid and edid.lower() in self.by_edid and self.by_edid[edid.lower()].type == rtype:
            return self.by_edid[edid.lower()]
        for rec in self.by_type.get(rtype, []):
            if (not named or rec.has("FULL")) and test(rec):
                return rec
        raise PluginError(f"Skyrim.esm has no {rtype} template ({edid or 'by property'})")

    def all(self) -> dict[str, Record]:
        """One template per test role."""
        # Mundane, playable items by editor ID; the tests after them are the fallback when a
        # Skyrim.esm lacks that editor ID.
        model = lambda rec: (rec.get("MODL") or b"").lower()
        plain_misc = lambda rec: (rec.form_id not in (FORM_GOLD, FORM_LOCKPICK) and rec.has("MODL")
                                  and KEYWORD_ORE_INGOT not in rec.keywords())
        return {
            "weapon": self.pick("WEAP", "IronSword"),
            "enchanted weapon": self.pick("WEAP", "EnchDraugrSwordHonedFrost02",
                                          test=lambda rec: rec.has("EITM") and rec.edid().startswith("Ench")),
            "armor": self.pick("ARMO", "ArmorIronCuirass"),
            "ammo": self.pick("AMMO", "IronArrow"),
            "potion": self.pick("ALCH", "RestoreHealth01"),
            "ingredient": self.pick("INGR", "MoonSugar"),
            "misc": self.pick("MISC", "GlazedBowl01Nordic", test=plain_misc),
            "ingot": self.pick("MISC", "IngotIron", test=lambda rec: KEYWORD_ORE_INGOT in rec.keywords()),
            "ore": self.pick("MISC", "OreIron", test=lambda rec: KEYWORD_ORE_INGOT in rec.keywords()
                             and rec.edid().lower().startswith("ore")),
            "soul gem": self.pick("SLGM", "SoulGemPetty"),
            "scroll": self.pick("SCRL", "CureWoundsScroll"),
            "book": self.pick("BOOK", "Book3ValuableDragonborn",
                              test=lambda rec: book_data(rec) == (0, 0) and b"books\\" in model(rec) and b"note" not in model(rec)),
            "spell tome": self.pick("BOOK", test=lambda rec: book_data(rec)[0] & 0x04),
            # Skyrim.esm's notes have the ordinary book type; what marks them is a note model.
            "note": self.pick("BOOK", test=lambda rec: b"note" in model(rec)),
            "key": self.pick("KEYM"),
            "light": self.pick("LIGH", "Torch01", test=lambda rec: light_flags(rec) & 0x2),
        }


# ---------------------------------------------------------------------------------------
# Building the test items


class PluginBuilder:
    def __init__(self, name: str, masters: list[str]):
        self.name = name
        self.masters = masters
        self.records: list[Record] = []
        self.items: list[dict] = []

    def add(self, template: Record, edid: str, name: str | None, intent: str, change=None) -> Record:
        rec = template.copy()
        rec.form_id = (len(self.masters) << 24) | (FIRST_OBJECT_ID + len(self.records))
        rec.remove("VMAD")
        rec.set("EDID", zstring(edid))
        if name is None:
            rec.remove("FULL")
        else:
            rec.set("FULL", zstring(name))
        for sig in LOCALIZED - {"FULL"}:
            if rec.has(sig):
                rec.set(sig, zstring(f"{name or edid} ({sig})"))
        if change:
            change(rec)
        self.records.append(rec)
        self.items.append({"edid": edid, "id": f"{rec.form_id & 0xFFFFFF:06X}", "type": rec.type,
                           "name": name, "template": template.edid(), "tests": intent})
        return rec


def missing_model(rec: Record) -> None:
    path = zstring(f"AIMTest\\Missing\\{rec.edid()}.nif")
    if rec.type == "ARMO":  # its MODL entries point at armor addons; the world models are MOD2 and MOD4
        for sig in ("MOD2", "MOD4"):
            if rec.has(sig):
                rec.set(sig, path)
        rec.remove("MO2T", "MO2S", "MO4T", "MO4S")
    else:
        rec.set("MODL", path)
        rec.remove("MODT", "MODS")


def non_playable(rec: Record) -> None:
    rec.flags |= FLAG_NONPLAYABLE


def not_carryable(rec: Record) -> None:
    data = bytearray(rec.get("DATA"))
    struct.pack_into("<I", data, 12, struct.unpack_from("<I", data, 12)[0] & ~0x2)
    rec.set("DATA", bytes(data))


def note_type(rec: Record) -> None:
    data = bytearray(rec.get("DATA"))
    data[1] = 0xFF  # the "note or scroll" book type
    rec.set("DATA", bytes(data))


def without_ore_keyword(rec: Record) -> None:
    rec.set_keywords([k for k in rec.keywords() if k != KEYWORD_ORE_INGOT])


ROLE_TAGS = {
    "weapon": "Weapon", "enchanted weapon": "EnchWeapon", "armor": "Armor", "ammo": "Ammo",
    "potion": "Potion", "ingredient": "Ingredient", "misc": "Misc", "ingot": "Ingot", "ore": "Ore",
    "soul gem": "SoulGem", "scroll": "Scroll", "book": "Book", "spell tome": "SpellTome",
    "note": "Note", "key": "Key", "light": "Light",
}


def build_all(templates: dict[str, Record]) -> list[tuple[PluginBuilder, str, bool]]:
    masters = ["Skyrim.esm"]

    big = PluginBuilder("AIMTest_Big.esp", masters)
    for i in range(600):
        letter = chr(ord("A") + i * 26 // 600)
        big.add(templates["misc"], f"AIMTest_Big_{i:03d}", f"{letter} Test Item {i:03d}",
                "600 items named A to Z: parts and their CHAR placeholders")

    light = PluginBuilder("AIMTest_Light.esp", masters)
    for role, tag in ROLE_TAGS.items():
        light.add(templates[role], f"AIMTest_Light_{tag}", f"AIMTest Light {role.title()}",
                  f"a {role} in a light (ESL) plugin")

    missing = PluginBuilder("AIMTest_MissingModel.esp", masters)
    for role in ("weapon", "armor", "ammo", "potion", "ingredient", "misc", "soul gem", "scroll", "book", "key"):
        tag = ROLE_TAGS[role]
        missing.add(templates[role], f"AIMTest_Missing_{tag}", f"AIMTest Missing {role.title()}",
                    f"a {role} whose model file doesn't exist", missing_model)

    edge = PluginBuilder("AIMTest_Edge.esp", masters)
    edge.add(templates["misc"], "AIMTest_Edge_Nameless", None, "an item without a name")
    edge.add(templates["armor"], "AIMTest_Edge_Armor", "AIMTest Playable Armor", "playable armor, to compare with the next")
    edge.add(templates["armor"], "AIMTest_Edge_NonPlayableArmor", "AIMTest Non-Playable Armor",
             "the same armor, flagged non-playable", non_playable)
    edge.add(templates["misc"], "AIMTest_Edge_Cyrillic", "Тестовый предмет", "a name in Cyrillic (UTF-8 in the plugin)")
    edge.add(templates["book"], "AIMTest_Edge_Book", "AIMTest Book", "an ordinary book")
    edge.add(templates["spell tome"], "AIMTest_Edge_SpellTome", "AIMTest Spell Tome", "a book that teaches a spell")
    edge.add(templates["note"], "AIMTest_Edge_Note", "AIMTest Note", "a note: a book with a note model")
    edge.add(templates["book"], "AIMTest_Edge_NoteType", "AIMTest Note Type Book",
             "an ordinary book with the 'note or scroll' type byte (0xFF)", note_type)
    edge.add(templates["ingot"], "AIMTest_Edge_Ingot", "AIMTest Ingot", "an ingot (VendorItemOreIngot keyword)")
    edge.add(templates["ore"], "AIMTest_Edge_Ore", "AIMTest Ore", "an ore (VendorItemOreIngot keyword)")
    edge.add(templates["ingot"], "AIMTest_Edge_IngotNoKeyword", "AIMTest Ingot Without Keyword",
             "the same ingot without the VendorItemOreIngot keyword", without_ore_keyword)
    edge.add(templates["light"], "AIMTest_Edge_Light", "AIMTest Carryable Light", "a light that can be carried")
    edge.add(templates["light"], "AIMTest_Edge_FixedLight", "AIMTest Fixed Light",
             "the same light, not carryable", not_carryable)
    edge.add(templates["weapon"], "AIMTest_Edge_Weapon", "AIMTest Weapon", "a weapon without an enchantment")
    edge.add(templates["enchanted weapon"], "AIMTest_Edge_EnchWeapon", "AIMTest Enchanted Weapon", "an enchanted weapon")

    empty = PluginBuilder("AIMTest_Empty.esp", masters)

    return [
        (big, "AddItemMenu tests: 600 misc items named A to Z", False),
        (light, "AddItemMenu tests: one item of each type in a light plugin", True),
        (missing, "AddItemMenu tests: items whose model files don't exist", False),
        (edge, "AddItemMenu tests: inclusion and type edge cases", False),
        (empty, "AddItemMenu tests: no records", False),
    ]


def generate(skyrim_esm: Path, out_dir: Path) -> dict:
    _, records = read_plugin(skyrim_esm, set(ITEM_TYPES))
    templates = Templates(records).all()
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"source": skyrim_esm.name, "templates": {role: rec.edid() for role, rec in templates.items()}, "plugins": {}}
    for builder, description, light in build_all(templates):
        write_plugin(out_dir / builder.name, builder.masters, builder.records, description, light)
        manifest["plugins"][builder.name] = {"light": light, "masters": builder.masters, "items": builder.items}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skyrim", required=True, type=Path, help="Skyrim.esm, the source of the item templates")
    parser.add_argument("--out", required=True, type=Path, help="the folder to write the plugins to")
    args = parser.parse_args(argv)
    try:
        manifest = generate(args.skyrim, args.out)
    except (PluginError, OSError, struct.error, zlib.error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    for name, plugin in manifest["plugins"].items():
        print(f"{name}: {len(plugin['items'])} items{' (light)' if plugin['light'] else ''}")
    print("templates: " + ", ".join(f"{role}={edid}" for role, edid in manifest["templates"].items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
