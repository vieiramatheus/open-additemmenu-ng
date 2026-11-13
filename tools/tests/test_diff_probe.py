# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for diff_probe.py, with small made-up probe runs; no game is needed."""

import io
import json
import re
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import diff_probe  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def entry(label, parent, entry_id, children=False):
    return f"{label};;{parent};;{entry_id};;0;;{1 if children else 0}"


def lists(*items):
    """16 lists from (list index, plugin, form ID, name) items."""
    result = [[] for _ in range(16)]
    for index, plugin, form_id, name in items:
        result[index].append({"file": plugin, "id": form_id, "type": "MISC", "name": name, "playable": True})
    return result


def get_items(phase, index, found, text="", ret=None):
    return (phase, "AIM_GetItems", [index, "<AIM_00..AIM_15>", text],
            bool(sum(map(len, found))) if ret is None else ret, {"lists": found})


def entries(mode, search, ret, phase="entries"):
    return (phase, "AIM_GetEntries", [mode, search], ret, {})


APPLE = (13, "A.esp", "000801", "Apple")
BOWL = (13, "A.esp", "000802", "Bowl")
CUP = (13, "A.esp", "000803", "Cup")
SWORD = (0, "B.esp", "000801", "Sword")


class DiffTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="diff-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, calls, plan=3, done=True, setup=None, ini=None, variant="default"):
        folder = self.tmp / name / variant
        folder.mkdir(parents=True)
        lines = [json.dumps({"probe": "AIMProbe", "plan": plan, "skyrim": "1.5.97.0", "plugins": [{"name": "A.esp"}]})]
        for seq, (phase, fn, args, ret, extra) in enumerate(calls, 1):
            lines.append(json.dumps({"seq": seq, "calling": fn, "args": args}))
            lines.append(json.dumps({"seq": seq, "phase": phase, "fn": fn, "args": args, "ret": ret, "ms": 16.0, **extra},
                                    ensure_ascii=False))
        if done:
            lines.append(json.dumps({"done": "done", "calls": len(calls)}))
        (folder / "probe.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        if ini is not None:
            (folder / "AddItemMenuSE.ini").write_text(ini, encoding="utf-8")
        if setup is not None:
            (self.tmp / name / "runs.json").write_text(json.dumps({variant: {"setup": setup}}), encoding="utf-8")
        return self.tmp / name

    def compare(self, ref_calls, cand_calls, extra=(), **kwargs):
        ref = self.write("ref", ref_calls, **kwargs.pop("ref", {}))
        cand = self.write("cand", cand_calls, **kwargs.pop("cand", {}))
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = diff_probe.main([str(ref), str(cand), "--json", str(self.tmp / "report.json"), "-v", *extra])
        report = json.loads((self.tmp / "report.json").read_text(encoding="utf-8")) if code != 2 else None
        return code, report, out.getvalue()

    @staticmethod
    def known(report):
        return sorted({f["known"] for f in report[0]["findings"] if f["known"]})

    @staticmethod
    def unknown(report):
        return [f for f in report[0]["findings"] if not f["known"]]

    # A run: two plugins, A.esp split into two parts, B.esp a single entry.
    def basic(self, ids=(1, 2, 3, 4), part_size=2):
        part1, part2, b, a = ids
        tree = [entry("A.esp", -1, a, True), entry("Part 1", a, part1), entry("Part 2", a, part2), entry("B.esp", -1, b)]
        return [
            ("getters", "AIM_GetOrderListSize", [], 1, {}),
            entries(0, "", tree),
            get_items("items", part1, lists(APPLE, BOWL)),
            get_items("items", part2, lists(CUP)),
            get_items("items", b, lists(SWORD)),
            get_items("search", 999, lists(SWORD), text="sword"),
        ]

    def test_identical_runs(self):
        code, report, _ = self.compare(self.basic(), self.basic())
        self.assertEqual(code, 0)
        self.assertEqual(report[0]["findings"], [])

    def test_ids_dont_matter(self):
        code, report, _ = self.compare(self.basic(ids=(1, 2, 3, 4)), self.basic(ids=(7, 8, 5, 9)))
        self.assertEqual(code, 0, report)

    def test_a_different_item_is_unknown(self):
        cand = self.basic()
        cand[4] = get_items("items", 3, lists(SWORD, (0, "B.esp", "000802", "Axe")))
        code, report, out = self.compare(self.basic(), cand)
        self.assertEqual(code, 1)
        self.assertIn("only in the candidate: B.esp 000802 Axe", self.unknown(report)[0]["detail"])
        self.assertIn("UNKNOWN", out)

    def test_items_the_game_data_changed_are_expected(self):
        cand = self.basic()
        cand[4] = get_items("items", 3, lists(SWORD, (0, "B.esp", "000802", "Axe")))
        changes = self.tmp / "changes.json"
        changes.write_text(json.dumps({"items": [{"plugin": "B.esp", "id": "000802", "why": "added by a newer master"}]}),
                           encoding="utf-8")
        code, report, out = self.compare(self.basic(), cand, extra=["--data-changes", str(changes)])
        self.assertEqual(code, 0, report)
        self.assertEqual(self.known(report), ["game-data"])
        self.assertIn("expected `game-data`", out)

    def test_a_different_value_is_unknown(self):
        cand = self.basic()
        cand[0] = ("getters", "AIM_GetOrderListSize", [], 2, {})
        code, report, _ = self.compare(self.basic(), cand)
        self.assertEqual(code, 1)
        self.assertEqual(self.unknown(report)[0]["detail"], "1 | 2")

    def test_parts_cut_differently(self):
        # The reference: an item in two parts and an empty extra part, as the original DLL does.
        tree = [entry("A.esp", -1, 4, True), entry("Part 1", 4, 1), entry("Part 2", 4, 2), entry("Part 3", 4, 5),
                entry("B.esp", -1, 3)]
        ref = self.basic()
        ref[1] = entries(0, "", tree)
        ref[3] = get_items("items", 2, lists(BOWL, CUP))
        ref.insert(4, get_items("items", 5, lists(), ret=False))
        code, report, _ = self.compare(ref, self.basic())
        self.assertEqual(code, 0, report)
        self.assertEqual(self.known(report), ["parts"])

    def test_parts_with_other_items_are_unknown(self):
        ref = self.basic()
        ref[3] = get_items("items", 2, lists(CUP, (13, "A.esp", "000804", "Dish")))
        code, report, _ = self.compare(ref, self.basic())
        self.assertEqual(code, 1)
        self.assertIn("only in the reference: A.esp 000804 Dish", self.unknown(report)[0]["detail"])

    def test_candidate_parts_must_be_valid(self):
        cand = self.basic()
        cand[2] = get_items("items", 1, lists(APPLE, BOWL, CUP))  # three items, ContainerSize 2
        cand[3] = get_items("items", 2, lists(CUP))
        code, report, _ = self.compare(self.basic(), cand, cand={"ini": "[GeneralSettings]\nContainerSize=2\n"})
        self.assertEqual(code, 1)
        problems = {f["detail"] for f in self.unknown(report)}
        self.assertIn("holds 3 items, more than 2", problems)
        self.assertIn("repeats items of an earlier part", problems)

    def test_sort_orders_are_paired_by_their_result(self):
        load_order = [entry("A.esp", -1, 1), entry("B.esp", -1, 2)]
        reverse = [entry("B.esp", -1, 2), entry("A.esp", -1, 1)]
        ref = [entries(0, "", load_order), entries(1, "", load_order), entries(2, "", reverse)]
        cand = [entries(0, "", load_order), entries(1, "", reverse), entries(2, "", load_order)]
        code, report, _ = self.compare(ref, cand)
        self.assertEqual(code, 0, report)
        self.assertEqual(self.known(report), ["sort-order"])

    def test_clipboard_text_kept_as_written(self):
        def clipboard(after_set, external):
            return [
                ("clipboard", "AIM_SetClipboardText", ["Меч"], True, {"clipboardNow": after_set}),
                ("clipboard", "AIM_GetClipboardText", [], "Меч", {}),
                ("clipboard", "AIM_GetClipboardText", [], external, {"clipboardSetTo": "Меч"}),
            ]
        code, report, _ = self.compare(clipboard("ÐœÐµÑ‡", "???"), clipboard("Меч", "Меч"))
        self.assertEqual(code, 0, report)
        self.assertEqual(self.known(report), ["clipboard"])
        self.assertEqual(len(report[0]["findings"]), 2)

    def test_repeated_calls_are_matched_in_order(self):
        def reads(second):
            return [("clipboard", "AIM_GetClipboardText", [], "same", {}),
                    ("clipboard", "AIM_GetClipboardText", [], second, {})]
        code, report, _ = self.compare(reads("one"), reads("two"))
        self.assertEqual(code, 1)
        self.assertEqual(self.unknown(report)[0]["detail"], "one | two")

    def test_lists_emptied_for_an_unknown_id(self):
        ref = [get_items("risky", -1, lists(SWORD), ret=False)]
        cand = [get_items("risky", -1, lists(), ret=False)]
        code, report, _ = self.compare(ref, cand)
        self.assertEqual(code, 0, report)
        self.assertEqual(self.known(report), ["empty-lists"])

    def test_type_menu_for_all(self):
        typed = [entry("A.esp", -1, 3, True), entry("$AIM_MISC", 3, 1), entry("B.esp", -1, 4, True),
                 entry("$AIM_WEAPON", 4, 2)]
        cand = [entries(0, "", typed), get_items("items", 1, lists(APPLE, BOWL, CUP)), get_items("items", 2, lists(SWORD))]
        ref = self.basic()[1:5]
        ini = "[GeneralSettings]\nAllPluginUseItemTypeMenu=1\n"
        code, report, _ = self.compare(ref, cand, ref={"ini": ini}, cand={"ini": ini})
        self.assertEqual(code, 0, report)
        self.assertEqual(self.known(report), ["type-menu-for-all"])
        # Without the setting the same difference is unknown.
        shutil.rmtree(self.tmp / "ref")
        shutil.rmtree(self.tmp / "cand")
        code, _, _ = self.compare(ref, cand)
        self.assertEqual(code, 1)

    def test_accumulating_lists_are_caught(self):
        def run(second):
            return self.basic() + [get_items("accumulate", 1, lists(APPLE, BOWL)), get_items("accumulate", 2, second)]
        code, _, _ = self.compare(run(lists(CUP)), run(lists(CUP)))
        self.assertEqual(code, 0)
        shutil.rmtree(self.tmp / "ref")
        shutil.rmtree(self.tmp / "cand")
        code, report, _ = self.compare(run(lists(CUP)), run(lists(APPLE, BOWL, CUP)))
        self.assertEqual(code, 1)
        self.assertIn("kept items", self.unknown(report)[0]["detail"])

    def test_text_that_isnt_utf8(self):
        value = {"hex": "e9", "cp1252": "é"}
        code, report, _ = self.compare([("translation", "AIM_GetTranslation", ["$X"], value, {})],
                                       [("translation", "AIM_GetTranslation", ["$X"], "é", {})])
        self.assertEqual(code, 1, "bytes E9 and the UTF-8 text é are different strings")

    def test_runs_of_different_plans_are_refused(self):
        code, _, _ = self.compare(self.basic(), self.basic(), ref={"plan": 2})
        self.assertEqual(code, 2)

    def test_runs_with_different_test_plugins_are_refused(self):
        code, _, _ = self.compare(self.basic(), self.basic(), ref={"setup": {"testPlugins": {"AIMTest_Edge.esp": "aa"}}},
                                  cand={"setup": {"testPlugins": {"AIMTest_Edge.esp": "bb"}}})
        self.assertEqual(code, 2)

    def test_an_unfinished_run_is_unknown(self):
        code, report, _ = self.compare(self.basic(), self.basic(), cand={"done": False})
        self.assertEqual(code, 1)
        self.assertIn("didn't finish", self.unknown(report)[0]["detail"])

    def test_every_known_difference_is_documented(self):
        doc = (REPO / "tests" / "known-differences.md").read_text(encoding="utf-8")
        documented = set(re.findall(r"^## .*\(`([a-z-]+)`\)\s*$", doc, flags=re.MULTILINE))
        self.assertEqual(documented, set(diff_probe.KNOWN))


if __name__ == "__main__":
    unittest.main()
