"""Every cell of the oracle's cell maps, pinned to Kyle's template.

frontend/js/bid-profiles.js names, for each of the eleven priced tabs, the cells at the edges of the
markup chain (flags, inputs, rates, fixed rates, outputs) and what the template holds in each today:
the formula text, or the constant. The oracle writes into some of those cells and reads others, so a
map that points at the wrong cell, or at a cell whose formula Kyle has since changed, would make the
recorded answers a record of something else. This module is the check, and it is generated from the
maps: one test case per entry, close to 600 of them, so the failure names the tab and the cell.

THE FAMILY CHECKS. Some tabs are one layout copied: the five Gyp tabs, Seal (+Jnts) off Seal, Seal off
Polish. The maps say, in `families`, which cells of a copy differ from the tab it copies and why
(it reads the original's answer, or holds something else). Those lists are checked against the
TEMPLATE, not against the maps: for every cell of the original's map, the copy's cell must be identical
unless the list says otherwise, a cell the list names must really differ, and a "mirror" must be exactly
a reference to the original tab's same cell. A difference nobody wrote down fails, and so does a written
one that is not there.

Reads the template through backend/estimate_writer.read_sheet_grid, the reader the Estimate Review page
itself is served by (via _oracle_support). The maps are loaded by node.
"""
import functools
import shutil

import pytest

import _oracle_support as S
from _node import require_node

GROUPS = ["flags", "inputs", "rates", "fixed", "outputs"]


def _maps():
    """The maps, or None where there is no node to load them (the guard test below says so loudly)."""
    return S.profiles() if shutil.which("node") else None


PROFILES = _maps()


def _cases():
    if PROFILES is None:
        return []
    out = []
    for tab in PROFILES["priced"]:
        m = PROFILES["sheets"][tab]
        for group in GROUPS:
            for name, entry in m[group].items():
                out.append(pytest.param(tab, group, name, entry, id="%s::%s.%s" % (tab, group, name)))
    return out


@functools.lru_cache(maxsize=None)
def _index(tab):
    out = {}
    for c in S._grid(tab, S.TEMPLATE_PATH)["cells"]:
        if c.get("isFormula"):
            out[c["addr"]] = ("formula", c["formula"])
        elif c.get("value") is not None:
            out[c["addr"]] = ("value", c["value"])
    return out


def _content(tab, addr):
    """What the template holds at `addr`: ("formula", text), ("value", constant) or ("empty", None)."""
    return _index(tab).get(addr, ("empty", None))


@pytest.fixture(scope="module")
def profiles():
    require_node()
    return S.profiles()


def test_the_maps_load_and_cover_the_eleven_priced_tabs(profiles):
    assert PROFILES is not None
    priced = profiles["priced"]
    assert priced == ["Epoxy", "Polish", "Seal", "Seal (+Jnts)", "Epoxy blank", "Leveling",
                      'Gyp (USG 1-8")', "Gyp (USG N12ULTRA)", 'Gyp (USG N25 1-4")', "Gyp (GWorx SC190)", "Gyp (FR)"]
    assert set(S.sheet_names()) >= set(priced)
    assert len(_cases()) >= 570, "close to 600 entries across eleven maps"


def pin_problem(tab, group, name, entry):
    """What is wrong between one map entry and the template, or None."""
    kind, got = _content(tab, entry["addr"])
    where = "%s!%s (%s.%s)" % (tab, entry["addr"], group, name)
    if "formula" in entry:
        if (kind, got) != ("formula", entry["formula"]):
            return (where + ": the template holds %s %r, not that formula. If Kyle changed it, update bid-profiles.js "
                    "and re-run the oracle" % (kind, got))
    elif entry["value"] is None:
        if kind != "empty":
            return where + ": the map says empty, the template holds %r" % (got,)
    elif not (kind == "value" and got == entry["value"] and type(got) is not bool):
        return where + ": the map says the constant %r, the template holds %s %r" % (entry["value"], kind, got)
    return None


@pytest.mark.parametrize("tab, group, name, entry", _cases())
def test_the_template_holds_what_the_map_says(tab, group, name, entry):
    assert pin_problem(tab, group, name, entry) is None


def test_the_pin_notices_every_way_a_map_entry_can_be_wrong():
    """The same check, on entries that have been falsified, must say so each time."""
    right_formula = {"addr": "D31", "formula": "=ROUNDUP(SUM(D17:D30),0)"}
    assert pin_problem("Polish", "inputs", "material", right_formula) is None
    wrong = [
        ("a formula with one character changed", "Polish", {"addr": "D31", "formula": "=ROUNDUP(SUM(D17:D30),1)"}),
        ("a formula written where the template holds a constant", "Polish", {"addr": "B32", "formula": "=0.02"}),
        ("a constant where the template holds a formula", "Polish", {"addr": "D31", "value": 0}),
        ("the wrong constant", "Polish", {"addr": "B32", "value": 0.03}),
        ("a number where the template holds text", "Polish", {"addr": "B4", "value": 1}),
        ("a cell that is empty in the template", "Polish", {"addr": "Z99", "formula": "=A1"}),
        ("empty where the template holds a constant", "Polish", {"addr": "B32", "value": None}),
        ("the cell one row off", "Epoxy", {"addr": "D41", "formula": "=ROUNDUP(SUM(D18:D39),0)"}),
    ]
    for label, tab, entry in wrong:
        assert pin_problem(tab, "inputs", "x", entry), label


def test_no_two_names_in_one_map_share_a_cell(profiles):
    for tab in profiles["priced"]:
        seen = {}
        for group in GROUPS:
            for name, entry in profiles["sheets"][tab][group].items():
                assert entry["addr"] not in seen, "%s: %s.%s and %s are the same cell %s" % (
                    tab, group, name, seen.get(entry["addr"]), entry["addr"])
                seen[entry["addr"]] = group + "." + name


def test_tabs_of_one_layout_name_the_same_cells(profiles):
    """The family of a tab says which layout it is. Every tab of a family carries the same names at the same
    addresses; only what the cells hold may differ (the family checks below are about that)."""
    by_family = {}
    for tab in profiles["priced"]:
        by_family.setdefault(profiles["sheets"][tab]["family"], []).append(tab)
    assert {k: len(v) for k, v in by_family.items()} == {"polish": 3, "epoxy": 1, "epoxy-blank": 1, "leveling": 1, "gyp": 5}
    for family, tabs in by_family.items():
        first = profiles["sheets"][tabs[0]]
        for tab in tabs[1:]:
            for group in GROUPS:
                assert {n: e["addr"] for n, e in profiles["sheets"][tab][group].items()} == \
                       {n: e["addr"] for n, e in first[group].items()}, (family, tab, group)


def test_the_ladders_point_at_real_cells(profiles):
    for tab in profiles["priced"]:
        m = profiles["sheets"][tab]
        assert m["ladders"], tab
        for ladder in m["ladders"]:
            assert "formula" in m["outputs"][ladder["cell"]], (tab, ladder, "a ladder lives in a formula")
            assert ladder["on"] in m["inputs"] or ladder["on"] in m["outputs"], (tab, ladder)
            if "needs" in ladder:
                assert ladder["needs"] in m["flags"], (tab, ladder)


# ── the families ─────────────────────────────────────────────────────────────
def _mirror_of(base_tab, addr):
    quoted = "'" + base_tab.replace("'", "''") + "'" if any(ch in base_tab for ch in " ()+\"-") else base_tab
    return "=%s!%s" % (quoted, addr)


def _family_cases():
    if PROFILES is None:
        return []
    return [pytest.param(name, id=name) for name in PROFILES["families"]]


def family_problems(profiles, family, deltas=None):
    """What is wrong between a copy and the tab it copies, against the TEMPLATE. `deltas` overrides the listed
    differences, for the test below that lists the wrong ones on purpose."""
    fam = profiles["families"][family]
    deltas = fam["deltas"] if deltas is None else deltas
    base_map = profiles["sheets"][fam["base"]]
    problems, listed = [], {}                     # (member, "group.name") -> delta
    for delta in deltas:
        for sheet in delta["sheets"]:
            if sheet not in fam["members"]:
                problems.append((family, sheet, "a delta names a tab that is not a member"))
            for cell in delta["cells"]:
                if (sheet, cell) in listed:
                    problems.append((family, sheet, cell, "listed twice"))
                listed[(sheet, cell)] = delta
    if not all(d["why"].strip() and d["kind"] in ("mirror", "differs") for d in deltas):
        problems.append((family, "every delta needs a reason and a kind"))
    differing = set()
    for member in fam["members"]:
        member_map = profiles["sheets"][member]
        for group in GROUPS:
            for name, entry in base_map[group].items():
                addr = entry["addr"]
                if member_map[group][name]["addr"] != addr:
                    problems.append((member, group, name, "a copy keeps its cells where they are"))
                here, there = _content(fam["base"], addr), _content(member, addr)
                cell = group + "." + name
                if (member, cell) in listed:
                    differing.add((member, cell))
                    if here == there:
                        problems.append((family, member, cell, "listed as different but identical to " + fam["base"]))
                    elif listed[(member, cell)]["kind"] == "mirror" and there != ("formula", _mirror_of(fam["base"], addr)):
                        problems.append((family, member, cell, "listed as a mirror of %s!%s but holds %r" % (fam["base"], addr, there)))
                elif here != there:
                    problems.append((family, member, cell, "differs from %s and nobody said so: %r vs %r" % (fam["base"], here, there)))
    if differing != set(listed):
        problems.append((family, "listed but not found", sorted(set(listed) - differing)))
    return problems


@pytest.mark.parametrize("family", _family_cases())
def test_a_copy_differs_from_the_tab_it_copies_exactly_where_the_list_says(profiles, family):
    assert family_problems(profiles, family) == []


def test_the_family_check_notices_a_list_that_is_wrong_in_either_direction(profiles):
    deltas = profiles["families"]["gyp"]["deltas"]
    # a difference nobody wrote down: drop the line that explains the Gyp (FR) gross profit formula
    fewer = [d for d in deltas if d["cells"] != ["outputs.gp"]]
    assert any("nobody said so" in str(p) for p in family_problems(profiles, "gyp", fewer))
    # a difference written down that is not there: claim the first copy's Local answer differs from the base
    extra = deltas + [{"sheets": ["Gyp (FR)"], "cells": ["flags.local"], "kind": "differs", "why": "claimed, not true"}]
    assert any("identical" in str(p) for p in family_problems(profiles, "gyp", extra))
    # a mirror that is not a mirror: FR's Local answer is typed, not read from the first tab
    fake = deltas + [{"sheets": ["Gyp (FR)"], "cells": ["fixed.truckload"], "kind": "mirror", "why": "claimed a mirror"}]
    assert family_problems(profiles, "gyp", fake), "a delta already listed, and not a mirror"
