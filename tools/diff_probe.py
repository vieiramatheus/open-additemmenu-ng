#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compare two AIMProbe runs, a reference (the original DLL) and a candidate (this project's DLL),
and sort every difference into a known difference or an unknown one.

  diff_probe.py testdata/golden/1.5.97-original-v2 testdata/runs/<run>     every variant in both
  diff_probe.py REF CAND --variant default --variant no-ini
  diff_probe.py REF/default/probe.jsonl CAND/default/probe.jsonl           two single runs
  diff_probe.py REF CAND --json report.json                                 also a full report

How results are compared:
- Both runs must come from the same probe plan. When runs.json records the test plugins
  (run_probe.py does), they must be the same files too.
- Entries are compared by their labels and their parents' labels, never by id, as an ordered list
  for each sort mode and search text.
- AIM_GetItems results are compared as sets of (plugin, form ID, list) items. Calls for entries
  are matched by the entry their id belongs to in each run.
- Calls repeated with the same arguments are matched in order.

The known differences are described in tests/known-differences.md, each under its name in
backticks; the rules that recognize them are in this file. Anything else is an unknown
difference, and the exit code is 1. Exit code 2 means the runs can't be compared.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

KNOWN = {
    "parts": "parts hold exactly ContainerSize items, with no empty part and no item in two parts",
    "sort-order": "the sort orders follow [OrderSettings] in its numbered order",
    "clipboard": "the clipboard keeps text that isn't English",
    "empty-lists": "AIM_GetItems empties the lists for every id",
    "type-menu-for-all": "AllPluginUseItemTypeMenu=1 gives every plugin item-type entries",
}

Item = tuple  # (plugin file, local form ID, list index)


class CompareError(Exception):
    pass


# ---------------------------------------------------------------------------------------
# Reading runs


def text(value) -> str:
    """A probe string as text. Game bytes that aren't UTF-8 come as {"hex": ..., "cp1252": ...};
    their bytes are kept through surrogate escapes, so equal bytes give equal strings."""
    if isinstance(value, dict) and "hex" in value:
        return bytes.fromhex(value["hex"]).decode("utf-8", "surrogateescape")
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def show(value, limit: int = 70) -> str:
    out = text(value).encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    return out if len(out) <= limit else out[: limit - 3] + "..."


@dataclass
class Call:
    seq: int
    phase: str
    fn: str
    args: list
    ret: object
    extra: dict


@dataclass
class Run:
    name: str
    header: dict
    calls: list[Call]
    done: bool
    setup: dict | None = None
    settings: dict = field(default_factory=dict)  # from the variant's AddItemMenuSE.ini, if saved


def parse_ini(data: str) -> dict:
    settings: dict[str, dict[str, str]] = {}
    section = ""
    for line in data.splitlines():
        line = line.split(";", 1)[0].strip()
        if line.startswith("["):
            section = line.strip("[]").strip().lower()
        elif "=" in line:
            key, value = line.split("=", 1)
            settings.setdefault(section, {})[key.strip().lower()] = value.strip()
    return settings


def load_run(probe: Path, name: str = "", setup: dict | None = None) -> Run:
    header: dict = {}
    calls: list[Call] = []
    done = False
    with probe.open(encoding="utf-8") as lines:
        for line in lines:
            if not line.strip():
                continue
            record = json.loads(line)
            if "probe" in record:
                header = record
            elif "fn" in record and "ret" in record:
                extra = {k: v for k, v in record.items() if k not in ("seq", "phase", "fn", "args", "ret", "ms")}
                calls.append(Call(record["seq"], record["phase"], record["fn"], record["args"], record["ret"], extra))
            elif record.get("done") == "done":
                done = True
    ini = probe.parent / "AddItemMenuSE.ini"
    settings = parse_ini(ini.read_text(encoding="utf-8", errors="replace")) if ini.is_file() else {}
    return Run(name or probe.parent.name, header, calls, done, setup, settings)


def load_runs(path: Path) -> dict[str, Run]:
    """A run folder (runs.json and one folder per variant), a variant folder, or a probe.jsonl."""
    if path.is_file():
        return {path.parent.name: load_run(path)}
    if (path / "probe.jsonl").is_file():
        return {path.name: load_run(path / "probe.jsonl")}
    runs_json = path / "runs.json"
    info = json.loads(runs_json.read_text(encoding="utf-8")) if runs_json.is_file() else {}
    runs = {}
    for folder in sorted(p for p in path.iterdir() if (p / "probe.jsonl").is_file()):
        runs[folder.name] = load_run(folder / "probe.jsonl", folder.name, info.get(folder.name, {}).get("setup"))
    if not runs:
        raise CompareError(f"no probe runs in {path}")
    return runs


# ---------------------------------------------------------------------------------------
# Entries


@dataclass(frozen=True)
class Node:
    path: tuple
    id: int
    has_children: bool
    part: bool  # a slice of a group: a leaf under an item type, or a leaf under a plugin that isn't a type


def tree(entries) -> list[Node]:
    nodes: list[Node] = []
    parents: dict[int, Node] = {}
    for raw in entries if isinstance(entries, list) else []:
        entry = text(raw)
        fields = entry.split(";;")
        try:
            label, parent_id, entry_id, has_children = fields[0], int(fields[1]), int(fields[2]), fields[4] == "1"
        except (IndexError, ValueError):
            nodes.append(Node((entry,), -1, False, False))
            continue
        parent = parents.get(parent_id)
        path = (parent.path if parent else ()) + (label,)
        part = (not has_children and parent is not None
                and (parent.path[-1].startswith("$AIM_") or (len(parent.path) == 1 and not label.startswith("$AIM_"))))
        node = Node(path, entry_id, has_children, part)
        if has_children:
            parents[entry_id] = node
        nodes.append(node)
    return nodes


def shape(nodes: list[Node], level: int) -> list:
    """Level 0: every entry. Level 1: each group's parts folded away, so a group of items compares
    the same whether it is split or not. Level 2: the top-level entries only."""
    if level == 0:
        return [(n.path, n.has_children) for n in nodes]
    holders = {n.path[:-1] for n in nodes if n.part}
    if level == 1:
        return [(n.path, "items" if not n.has_children or n.path in holders else "entries") for n in nodes if not n.part]
    return [n.path for n in nodes if len(n.path) == 1]


def first_difference(left: list, right: list) -> str:
    for i, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return f"entry {i + 1}: {show(' / '.join(a[0]))} | {show(' / '.join(b[0]))}"
    return f"{len(left)} entries | {len(right)} entries"


# ---------------------------------------------------------------------------------------
# Comparing


@dataclass
class Finding:
    known: str | None  # a key of KNOWN, or None for an unknown difference
    where: str
    detail: str = ""


@dataclass
class Report:
    variant: str
    same: int = 0
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, known: str | None, where: str, detail: str = "") -> None:
        self.findings.append(Finding(known, where, detail))

    @property
    def unknown(self) -> list[Finding]:
        return [f for f in self.findings if f.known is None]


def items_of(call: Call) -> frozenset:
    return frozenset((text(f.get("file")), f.get("id"), index)
                     for index, lst in enumerate(call.extra.get("lists") or []) for f in lst)


def describe_items(items, names: dict, limit: int = 4) -> str:
    shown = sorted(items)[:limit]
    words = [f"{plugin} {form_id} {show(names.get((plugin, form_id), ''), 40)}" for plugin, form_id, _ in shown]
    more = f" and {len(items) - limit} more" if len(items) > limit else ""
    return ", ".join(words) + more


class Comparison:
    def __init__(self, ref: Run, cand: Run):
        self.ref, self.cand = ref, cand
        self.report = Report(cand.name)
        self.names: dict = {}
        for run in (ref, cand):
            for call in run.calls:
                for lst in call.extra.get("lists") or []:
                    for f in lst:
                        self.names.setdefault((text(f.get("file")), f.get("id")), text(f.get("name", "")))
        general = cand.settings.get("generalsettings", {})
        size = general.get("containersize", "")
        self.container_size = int(size) if size.isdigit() and int(size) > 0 else 512
        self.type_menu_for_all = general.get("allpluginuseitemtypemenu", "0") not in ("", "0")

    # -- checks before comparing

    def check(self) -> None:
        plans = (self.ref.header.get("plan"), self.cand.header.get("plan"))
        if plans[0] != plans[1]:
            raise CompareError(f"{self.cand.name}: probe plans differ ({plans[0]} and {plans[1]}); compare runs of one plan")
        ref_plugins = (self.ref.setup or {}).get("testPlugins")
        cand_plugins = (self.cand.setup or {}).get("testPlugins")
        if ref_plugins is not None and cand_plugins is not None and ref_plugins != cand_plugins:
            raise CompareError(f"{self.cand.name}: the runs used different test plugins")
        if ref_plugins is None or cand_plugins is None:
            self.report.notes.append("runs.json doesn't record the test plugins of both runs; make sure they are the same")
        if self.ref.header.get("plugins") != self.cand.header.get("plugins"):
            self.report.notes.append("the load orders differ")
        if self.ref.header.get("skyrim") != self.cand.header.get("skyrim"):
            self.report.notes.append(f"game versions: {self.ref.header.get('skyrim')} and {self.cand.header.get('skyrim')}")
        if not self.cand.done:
            self.report.add(None, "run", "the candidate run didn't finish")

    # -- the whole comparison

    def run(self) -> Report:
        self.check()
        self.ref_nodes = tree(self.entries_call(self.ref))
        self.cand_nodes = tree(self.entries_call(self.cand))
        self.mode_pairs = self.pair_modes()
        self.compare_entries()
        self.compare_entry_items()
        self.compare_keyed()
        self.check_accumulate()
        return self.report

    @staticmethod
    def entries_call(run: Run):
        for call in run.calls:
            if call.fn == "AIM_GetEntries" and call.phase == "entries" and call.args == [0, ""]:
                return call.ret
        return []

    def pair_modes(self) -> dict[int, int]:
        """Each candidate sort mode with the reference mode that orders the plugins the same way."""
        def orders(run: Run) -> dict[int, list]:
            return {c.args[0]: shape(tree(c.ret), 2) for c in run.calls
                    if c.fn == "AIM_GetEntries" and c.phase == "entries" and c.args[1] == ""}
        ref, cand = orders(self.ref), orders(self.cand)
        pairs = {}
        for mode, order in cand.items():
            if ref.get(mode) == order:
                pairs[mode] = mode
            else:
                pairs[mode] = next((m for m in sorted(ref) if ref[m] == order), mode)
        return pairs

    def compare_entries(self) -> None:
        ref = {(c.phase, c.args[0], text(c.args[1])): c for c in self.ref.calls if c.fn == "AIM_GetEntries"}
        for call in self.cand.calls:
            if call.fn != "AIM_GetEntries":
                continue
            mode, search = call.args[0], text(call.args[1])
            paired = self.mode_pairs.get(mode, mode) if call.phase == "entries" else mode
            where = f"AIM_GetEntries({mode}, {show(repr(search))})"
            other = ref.get((call.phase, paired, search))
            if other is None:
                self.report.add(None, where, "the reference has no such call")
                continue
            if paired != mode:
                self.report.add("sort-order", where, f"compared with the reference's mode {paired}")
            self.compare_entry_lists(where, tree(other.ret), tree(call.ret))

    def compare_entry_lists(self, where: str, ref: list[Node], cand: list[Node]) -> None:
        if shape(ref, 0) == shape(cand, 0):
            self.report.same += 1
        elif shape(ref, 1) == shape(cand, 1):
            self.report.add("parts", where, "only the parts differ; their items are checked with AIM_GetItems")
        elif self.type_menu_for_all and shape(ref, 2) == shape(cand, 2):
            self.report.add("type-menu-for-all", where, "the plugins' entries are arranged differently")
        else:
            self.report.add(None, where, first_difference(shape(ref, 1), shape(cand, 1)))

    # -- AIM_GetItems for entries, compared through the entries' structure

    @staticmethod
    def leaf_items(run: Run, nodes: list[Node]) -> dict:
        by_id = {n.id: n for n in nodes if not n.has_children}
        found = {}
        for call in run.calls:
            if call.fn == "AIM_GetItems" and call.phase == "items" and call.args[0] in by_id:
                found[by_id[call.args[0]].path] = items_of(call)
        return found

    def holders(self, nodes: list[Node], leaves: dict) -> dict:
        """Path -> items, for every group of items: a non-part leaf, or a group split into parts."""
        result: dict[tuple, set] = {}
        for node in nodes:
            if node.has_children or node.path not in leaves:
                continue
            key = node.path[:-1] if node.part else node.path
            result.setdefault(key, set()).update(leaves[node.path])
        return {k: frozenset(v) for k, v in result.items()}

    def compare_entry_items(self) -> None:
        ref_leaves = self.leaf_items(self.ref, self.ref_nodes)
        cand_leaves = self.leaf_items(self.cand, self.cand_nodes)
        ref_holders = self.holders(self.ref_nodes, ref_leaves)
        cand_holders = self.holders(self.cand_nodes, cand_leaves)
        parts = lambda nodes, holder: [n.path for n in nodes if n.part and n.path[:-1] == holder]

        plugins = list(dict.fromkeys([p[:1] for p in ref_holders] + [p[:1] for p in cand_holders]))
        for plugin in plugins:
            ref_sub = {p: s for p, s in ref_holders.items() if p[:1] == plugin}
            cand_sub = {p: s for p, s in cand_holders.items() if p[:1] == plugin}
            where = f"AIM_GetItems for {show(plugin[0])}"
            if set(ref_sub) == set(cand_sub):
                for path in sorted(ref_sub):
                    label = f"AIM_GetItems for {show(' / '.join(path))}"
                    if ref_sub[path] != cand_sub[path]:
                        self.item_difference(label, ref_sub[path], cand_sub[path])
                    elif parts(self.ref_nodes, path) != parts(self.cand_nodes, path):
                        self.report.add("parts", label, "same items, cut into parts differently")
                    else:
                        self.report.same += 1
            elif self.type_menu_for_all and frozenset().union(*ref_sub.values()) == frozenset().union(*cand_sub.values()):
                self.report.add("type-menu-for-all", where, "same items, arranged by item type")
            else:
                self.item_difference(where, frozenset().union(*ref_sub.values()), frozenset().union(*cand_sub.values()),
                                     "the entries differ too")
        self.check_parts(cand_leaves)

    def item_difference(self, where: str, ref: frozenset, cand: frozenset, note: str = "") -> None:
        detail = []
        if ref - cand:
            detail.append("only in the reference: " + describe_items(ref - cand, self.names))
        if cand - ref:
            detail.append("only in the candidate: " + describe_items(cand - ref, self.names))
        if not detail:
            detail.append("same items in different lists")
        self.report.add(None, where, "; ".join(detail + ([note] if note else [])))

    def check_parts(self, leaves: dict) -> None:
        """The candidate's parts: none empty, none larger than ContainerSize, no item in two."""
        groups: dict[tuple, list[tuple]] = defaultdict(list)
        for node in self.cand_nodes:
            if node.part:
                groups[node.path[:-1]].append(node.path)
        for group, paths in groups.items():
            seen: set = set()
            for path in paths:
                items = {(p, f) for p, f, _ in leaves.get(path, frozenset())}
                problem = ("is empty" if not items else
                           f"holds {len(items)} items, more than {self.container_size}" if len(items) > self.container_size else
                           "repeats items of an earlier part" if items & seen else "")
                if problem:
                    self.report.add(None, f"part {show(' / '.join(path))}", problem)
                seen |= items

    # -- every other call, matched by phase, function and arguments

    def key(self, run: Run, nodes: list[Node], call: Call):
        if call.fn == "AIM_GetEntries" or (call.fn == "AIM_GetItems" and call.phase in ("items", "accumulate")
                                           and any(n.id == call.args[0] and not n.has_children for n in nodes)):
            return None  # compared above
        if call.fn == "AIM_GetItems" and call.phase == "parents":
            node = next((n for n in nodes if n.id == call.args[0] and n.has_children), None)
            return (call.phase, call.fn, " / ".join(node.path) if node else f"id {call.args[0]}")
        return (call.phase, call.fn, json.dumps(call.args, ensure_ascii=False))

    def compare_keyed(self) -> None:
        def grouped(run: Run, nodes: list[Node]) -> dict:
            calls = defaultdict(list)
            for call in run.calls:
                k = self.key(run, nodes, call)
                if k is not None:
                    calls[k].append(call)
            return calls

        ref, cand = grouped(self.ref, self.ref_nodes), grouped(self.cand, self.cand_nodes)
        for k in list(dict.fromkeys(list(cand) + list(ref))):
            ref_calls, cand_calls = ref.get(k, []), cand.get(k, [])
            where = f"{k[1]} {k[2]} ({k[0]})"
            for i in range(max(len(ref_calls), len(cand_calls))):
                if i >= len(ref_calls) or i >= len(cand_calls):
                    self.unmatched(where, k, "only in the " + ("candidate" if i >= len(ref_calls) else "reference"))
                    continue
                self.compare_call(where, ref_calls[i], cand_calls[i])

    def unmatched(self, where: str, k, side: str) -> None:
        if k[0] == "parents" and self.type_menu_for_all:
            self.report.add("type-menu-for-all", where, side)
        elif k[0] == "parents" and any(" / ".join(n.path[:-1]) == k[2] for n in self.ref_nodes if n.part):
            self.report.add("parts", where, side + "; a group the reference splits into parts")
        else:
            self.report.add(None, where, side)

    def compare_call(self, where: str, ref: Call, cand: Call) -> None:
        if cand.fn == "AIM_GetItems":
            ref_items, cand_items = items_of(ref), items_of(cand)
            if ref_items == cand_items and ref.ret == cand.ret:
                self.report.same += 1
            elif ref.phase == "risky" and ref.ret == cand.ret is False and not cand_items:
                self.report.add("empty-lists", where, f"the reference left {len(ref_items)} items in the lists")
            else:
                self.item_difference(where, ref_items, cand_items, f"returned {ref.ret} and {cand.ret}")
            return
        if cand.phase == "clipboard":
            self.compare_clipboard(where, ref, cand)
            return
        if text(ref.ret) == text(cand.ret):
            self.report.same += 1
        else:
            self.report.add(None, where, f"{show(ref.ret)} | {show(cand.ret)}")

    def compare_clipboard(self, where: str, ref: Call, cand: Call) -> None:
        if cand.fn == "AIM_SetClipboardText":
            expected = text(cand.args[0])
            ref_value, cand_value = text(ref.extra.get("clipboardNow")), text(cand.extra.get("clipboardNow"))
        else:
            expected = text(cand.extra.get("clipboardSetTo", self.last_set(cand))).replace("\r", "").replace("\n", "")
            ref_value, cand_value = text(ref.ret), text(cand.ret)
        if ref.ret == cand.ret and ref_value == cand_value:
            self.report.same += 1
        elif cand_value == expected and ref_value != expected:
            self.report.add("clipboard", where, f"{show(ref_value)} | {show(cand_value)}")
        else:
            self.report.add(None, where, f"{show(ref_value)} | {show(cand_value)}")

    def last_set(self, call: Call) -> str:
        """The text the candidate itself put on the clipboard just before this call."""
        earlier = [c for c in self.cand.calls if c.fn == "AIM_SetClipboardText" and c.seq < call.seq]
        return text(earlier[-1].args[0]) if earlier else ""

    def check_accumulate(self) -> None:
        """The second of two calls without emptying the lists in between must hold only its own items."""
        def holds_only_its_own(run: Run) -> bool | None:
            calls = [c for c in run.calls if c.fn == "AIM_GetItems" and c.phase == "accumulate"]
            if len(calls) < 2:
                return None
            alone = next((c for c in run.calls if c.fn == "AIM_GetItems" and c.phase == "items"
                          and c.args[0] == calls[1].args[0]), None)
            return alone is not None and items_of(calls[1]) == items_of(alone)

        result = holds_only_its_own(self.cand)
        if result is None:
            return
        if result:
            self.report.same += 1
        else:
            self.report.add(None, "AIM_GetItems twice (accumulate)", "the lists kept items from the first call")


# ---------------------------------------------------------------------------------------
# Output


def print_report(report: Report, verbose: bool, out=print) -> None:
    known = defaultdict(list)
    for finding in report.findings:
        if finding.known:
            known[finding.known].append(finding)
    status = "OK" if not report.unknown else f"{len(report.unknown)} UNKNOWN"
    out(f"== {report.variant}: {status}; {report.same} the same, {sum(map(len, known.values()))} known differences")
    for note in report.notes:
        out(f"   note: {note}")
    for name, findings in known.items():
        out(f"   known `{name}` ({KNOWN[name]}): {len(findings)}")
        for finding in findings if verbose else []:
            out(f"      {finding.where}: {finding.detail}")
    for finding in report.unknown:
        out(f"   UNKNOWN {finding.where}: {finding.detail}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("reference", type=Path, help="the reference run (folder or probe.jsonl)")
    parser.add_argument("candidate", type=Path, help="the candidate run (folder or probe.jsonl)")
    parser.add_argument("--variant", action="append", default=[], help="compare only these variants (repeatable)")
    parser.add_argument("--json", type=Path, help="also write every finding to this file")
    parser.add_argument("-v", "--verbose", action="store_true", help="list every known difference too")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        ref, cand = load_runs(args.reference), load_runs(args.candidate)
        names = args.variant or [n for n in cand if n in ref]
        missing = [n for n in names if n not in ref or n not in cand]
        if missing or not names:
            raise CompareError("no variant to compare" if not names else "not in both runs: " + ", ".join(missing))
        reports = [Comparison(ref[name], cand[name]).run() for name in names]
    except (CompareError, OSError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    for report in reports:
        print_report(report, args.verbose)
    if args.json:
        args.json.write_text(json.dumps([{
            "variant": r.variant, "same": r.same, "notes": r.notes,
            "findings": [{"known": f.known, "where": f.where, "detail": f.detail} for f in r.findings],
        } for r in reports], indent=1, ensure_ascii=False), encoding="utf-8")
    unknown = sum(len(r.unknown) for r in reports)
    print(f"{len(reports)} variants, {unknown} unknown differences")
    return 1 if unknown else 0


if __name__ == "__main__":
    raise SystemExit(main())
