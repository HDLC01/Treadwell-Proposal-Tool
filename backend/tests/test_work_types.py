"""Phase 7 of the v2 estimating program: ONE vocabulary of work types and job conditions.

frontend/js/work-types.js holds what a job is (epoxy, polish, combo, gyp), what a workbook tab is (polish,
seal, epoxy, leveling, gyp; seal and leveling are options on a bid and never a job type), which quantities a
job asks for, and ONE table of job conditions: what each is called, who is asked, what a new job answers, and
which workbook cells each answer is written to. Until now that was written down ten-odd times, in different
shapes, each kept equal to the others by hand, and the copies had drifted: the live intake wrote the Taxable
answer to four cells and the v2 model to one, so a tax-exempt Leveling or Gypsum option on a v2 bid kept
charging 9.475%.

Everything below EXECUTES. tests/js/work-types-harness.js runs the real module, the real bid-model.js that
derives from it, and the copies the table has to stay equal to (the live intake's CONDITIONS and scope map,
the estimate screen's role sets), lifted out of the page files and evaluated. What it cannot see by itself is
checked here: the workbook template, the pages' script order, the HTML the intake and the Defaults tab draw.

THE LIVE INTAKE KEEPS ITS OWN LITERALS until Phase 9 moves it onto the shared modules, so the comparison
with them is a test and not a derivation. When Phase 9 deletes them, the comparison goes with them.

RED WITHOUT THE CHANGE. Every assertion is a plain function of the harness's answer, and BREAKS at the bottom
breaks one line of work-types.js or bid-model.js in a scratch copy, runs the harness against it, and requires
the named assertion to fail on that answer. A check no break turns red proves nothing, so the last test
requires every check to appear in the table.

Python is pinned to the same file by test_work_types_python_pin.py.

Run under node; a missing node FAILS under CI (tests/_node.py).
"""
from __future__ import annotations

import html.parser
import pathlib
import re
import warnings

import pytest

from _golden_support import FRONTEND, break_source
from _node import last_json_line, require_node, run_node
from _page_scripts import local_scripts

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parents[1]
HARNESS = TESTS / "js" / "work-types-harness.js"
BOOT = TESTS / "js" / "core-boot-harness.js"
TEMPLATE = ROOT / "backend" / "templates" / "estimate_sheet_5.7.xlsx"

JOB_TYPES = ["epoxy", "polish", "combo", "gyp"]
TABS = ["polish", "seal", "epoxy", "leveling", "gyp"]


def _run(frontend: pathlib.Path = FRONTEND) -> dict:
    require_node()
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    return _run()


def row(ran, key):
    return next(c for c in ran["data"]["CONDITIONS"] if c["key"] == key)


def live_rows(ran):
    return ran["live"]["conditions"]


# ══ 1. what the table says ═══════════════════════════════════════════════════════════════════════════
def test_the_four_job_types_and_the_five_tabs_are_the_ones_the_tool_has(ran):
    """The live intake's four radios, in its order, and markup.TABS' five, in its order. Only polish is ready:
    Estimating Tool v2 prices nothing else yet."""
    data = ran["data"]
    assert ran["keys"] == {"jobTypes": JOB_TYPES, "tabs": TABS}
    ready = {j["key"]: j["ready"] for j in data["JOB_TYPES"]}
    assert ready == {"epoxy": False, "polish": True, "combo": False, "gyp": False}
    assert {j["key"]: j["tabs"] for j in data["JOB_TYPES"]} == {
        "epoxy": ["epoxy"], "polish": ["polish"], "combo": ["epoxy", "polish"], "gyp": ["gyp"]}


def test_seal_and_leveling_are_options_on_a_bid_and_never_a_job_type(ran):
    """Hanz, 2026-10-07: Seal and Leveling are options, not job types. So they are tabs flagged optionOnly,
    and no job type is priced on either of them."""
    data = ran["data"]
    assert {t["key"] for t in data["TABS"] if t["optionOnly"]} == {"seal", "leveling"}
    assert not {"seal", "leveling"} & {j["key"] for j in data["JOB_TYPES"]}
    assert not {"seal", "leveling"} & {t for j in data["JOB_TYPES"] for t in j["tabs"]}


def test_every_tab_carries_the_sheets_of_the_workbook_and_every_sheet_has_one_tab(ran):
    data = ran["data"]
    sheets = [s for t in data["TABS"] for s in t["sheets"]]
    assert len(sheets) == len(set(sheets)), "a sheet is filed under two tabs"
    assert sorted(sheets) == sorted([
        "Polish", "Seal", "Seal (+Jnts)", "Epoxy", "Epoxy blank", "Leveling", 'Gyp (USG 1-8")',
        "Gyp (USG N12ULTRA)", 'Gyp (USG N25 1-4")', "Gyp (GWorx SC190)", "Gyp (FR)"])
    for t in data["TABS"]:
        assert t["role"] == t["key"] and t["markupLayout"] == t["key"], t["key"]


def test_every_reference_in_the_table_points_at_a_row_of_it(ran):
    data = ran["data"]
    fields = [f["name"] for f in data["FIELDS"]]
    assert len(fields) == len(set(fields))
    tabs = {t["key"] for t in data["TABS"]}
    for j in data["JOB_TYPES"]:
        assert set(j["tabs"]) <= tabs, j["key"]
        assert set(j["fields"]) <= set(fields), j["key"]
        assert j["fields"] == [f for f in fields if f in j["fields"]], "%s lists its fields out of order" % j["key"]
    for t in data["TABS"]:
        assert set(t["area"]) | set(t["cove"]) <= set(fields), t["key"]
    keys = [c["key"] for c in data["CONDITIONS"]]
    assert len(keys) == len(set(keys))
    for c in data["CONDITIONS"]:
        assert c["scope"] and set(c["scope"]) <= set(JOB_TYPES), c["key"]
        assert c["needs"] is None or c["needs"] in keys, c["key"]
        if c["needs"]:
            assert row(ran, c["needs"])["scope"] == c["scope"], "%s needs a condition it is not asked with" % c["key"]
    item_ids = [c["item_id"] for c in data["CONDITIONS"] if c["item_id"]]
    assert len(item_ids) == len(set(item_ids))
    assert set(item_ids) == {c["item_id"] for c in data["CONDITIONS"] if c["asked_on"]["v2Takeoff"]}, (
        "a reserved library row belongs to exactly the conditions the Takeoff step carries")


def test_each_screens_questions_are_a_clean_run_of_positions(ran):
    """`asked_on` says where on a screen a question sits, 0 when the screen does not ask it. A gap or a
    repeat would make that screen's order depend on the sort, so each screen's positions are exactly 1..k."""
    data = ran["data"]
    for surface in data["SURFACES"]:
        positions = sorted(c["asked_on"][surface] for c in data["CONDITIONS"] if c["asked_on"][surface])
        assert positions == list(range(1, len(positions) + 1)), (surface, positions)
    assert {s: sum(1 for c in data["CONDITIONS"] if c["asked_on"][s]) for s in data["SURFACES"]} == {
        "live": 9, "v2Intake": 4, "v2Takeoff": 3}


CELL = re.compile(r"^(?P<sheet>[^!]+)!(?P<cell>[A-Z]{1,3}[0-9]{1,5})$")


def test_every_cell_is_a_sheet_and_an_address_with_both_literals_written(ran):
    data = ran["data"]
    sheets = {s for t in data["TABS"] for s in t["sheets"]}
    for c in data["CONDITIONS"]:
        for address in c["cells"]:
            m = CELL.match(address)
            assert m and m["sheet"] in sheets, (c["key"], address)
        assert len(c["cells"]) == len(set(c["cells"])), c["key"]
        if c["cells"]:
            assert isinstance(c["on"], str) and isinstance(c["off"], str) and c["on"] != c["off"], c["key"]
        else:
            assert c["on"] is None and c["off"] is None, "%s has literals and nowhere to write them" % c["key"]
        assert isinstance(c["default"], bool) and isinstance(c["model"], bool), c["key"]


BLANK_IN_THE_TEMPLATE = {"Epoxy!B10", "Polish!B10"}


def test_every_cell_the_table_writes_is_a_literal_in_kyles_template(ran):
    """THE EXACT WORKBOOK CELLS. Each one holds, in Kyle's template, either a literal that is one of the two
    the table writes, or (the two Renovation cells only) nothing. A formula there would be a live reference
    replaced by a literal, which is how Polish!B6, D5 and D6 (they are =Epoxy!...) stay out of the table."""
    import openpyxl
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        book = openpyxl.load_workbook(TEMPLATE)
    for c in ran["data"]["CONDITIONS"]:
        for address in c["cells"]:
            sheet, cell = address.rsplit("!", 1)
            value = book[sheet][cell].value
            assert not (isinstance(value, str) and value.startswith("=")), "%s is a formula" % address
            if address in BLANK_IN_THE_TEMPLATE:
                assert value is None, "%s is no longer blank in the template: %r" % (address, value)
            else:
                assert value in (c["on"], c["off"]), "%s holds %r, not %r or %r" % (address, value, c["on"], c["off"])


def test_no_hard_bid_cell_is_in_the_table(ran):
    """Hanz, 2026-10-03: nothing may write Epoxy!B5 or Polish!B5 (estimate_writer HARD_BID_FLAG_CELLS)."""
    written = {a for c in ran["data"]["CONDITIONS"] for a in c["cells"]}
    assert not written & {"Epoxy!B5", "Polish!B5", "Seal!B5", "Leveling!B5"}


def test_taxable_is_four_cells_and_epoxy_b6_is_the_first(ran):
    assert row(ran, "taxable")["cells"] == ["Epoxy!B6", "Leveling!B6", 'Gyp (USG 1-8")!B8', "Gyp (FR)!B8"]


# ══ 2. what the readers do ═══════════════════════════════════════════════════════════════════════════
def test_a_combo_job_is_priced_on_epoxy_and_polish_and_the_answer_is_a_copy(ran):
    assert ran["tabsFor"] == {"epoxy": ["epoxy"], "polish": ["polish"], "combo": ["epoxy", "polish"], "gyp": ["gyp"]}
    assert ran["tabsForIsACopy"] == ["epoxy", "polish"], "a caller that edited the answer edited the next one's"


def test_tabsfor_refuses_everything_that_is_not_a_job_type_and_says_what_it_was_given(ran):
    """A TAB is not a job type, and there is no default: a missing argument used to mean Polish."""
    for case in ran["tabsForRefused"]:
        assert "threw" in case["r"], "tabsFor(%s) answered %r" % (case["asked"], case["r"])
        assert "tabsFor() was asked about" in case["r"]["threw"], case
    seal = next(c for c in ran["tabsForRefused"] if c["asked"] == "seal")
    assert "it is a tab, and a tab is not a job type" in seal["r"]["threw"]


def test_appliesto_reads_an_empty_list_as_every_tab_and_a_list_as_those_tabs(ran):
    table = ran["appliesTo"]
    for name in ("undefined", "null", "empty", "aString", "anObject", "aNumber"):
        assert all(table[name].values()), "%s must apply to every tab: %r" % (name, table[name])
    assert table["polish"] == {"polish": True, "seal": False, "epoxy": False, "leveling": False, "gyp": False}
    assert table["sealPolish"] == {"polish": True, "seal": True, "epoxy": False, "leveling": False, "gyp": False}
    assert table["all"] == dict.fromkeys(TABS, True)
    # a list that names only something that is no tab applies to none of them
    assert table["comboOnly"] == dict.fromkeys(TABS, False)


def test_appliesto_throws_on_a_job_type_and_on_anything_that_is_not_a_tab(ran):
    """"combo" is the case it exists for: a combo job has no tab of its own, so a default filed under it could
    never be read. It throws whatever the list is, empty included, or an empty list would hide the bug until a
    list that names a tab finally arrived. Names an object carries (constructor, __proto__) are no tab either."""
    for case in ran["appliesToRefused"]:
        assert "threw" in case["r"], "appliesTo(%s, %r) answered %r" % (case["list"], case["layout"], case["r"])
        assert "appliesTo() was asked about" in case["r"]["threw"], case
    combo = next(c for c in ran["appliesToRefused"] if c["layout"] == "combo" and c["list"] == "empty")
    assert "resolve it with tabsFor() first" in combo["r"]["threw"]
    assert {c["layout"] for c in ran["appliesToRefused"]} >= {"combo", "constructor", "__proto__", "toString"}


def test_every_other_reader_refuses_what_it_does_not_know_by_name(ran):
    for name, r in ran["refusals"].items():
        assert "threw" in r, "%s answered %r" % (name, r)
        assert "work-types.js:" in r["threw"], (name, r)
    assert ran["lookups"]["isJobType"] == [True, True, False, False, False]
    assert ran["lookups"]["isTab"] == [True, False, True, False, False]


def test_a_sheet_belongs_to_one_tab_and_a_lookalike_belongs_to_none(ran):
    got = ran["lookups"]["tabOfSheet"]
    assert got["Seal (+Jnts)"] == "seal" and got["Epoxy blank"] == "epoxy" and got["Leveling"] == "leveling"
    assert {k: v for k, v in got.items() if k.startswith("Gyp")} == dict.fromkeys(
        ['Gyp (USG 1-8")', "Gyp (USG N12ULTRA)", 'Gyp (USG N25 1-4")', "Gyp (GWorx SC190)", "Gyp (FR)"], "gyp")
    for not_a_sheet in ("Takeoff", "Stnd Alts", "constructor", "__proto__", ""):
        assert got[not_a_sheet] is None, not_a_sheet


def test_the_table_cannot_be_edited_by_a_reader_and_the_readers_hand_out_copies(ran):
    for name, r in ran["frozen"].items():
        assert "threw" in r, "the table accepted an edit: %s" % name
    assert ran["copies"]["cells"]["cells"] == ["Epoxy!B4", "Polish!B4"] and ran["copies"]["cells"]["on"] == "Yes"
    assert ran["copies"]["row"] == "Local job" and ran["copies"]["rows"] == 8
    assert ran["copies"]["local"] is True and ran["copies"]["reserved"] == "dye"


def test_each_screen_gets_its_questions_in_its_own_order_and_its_own_words(ran):
    """The three screens list the same conditions in three orders, and the v2 intake words one of them
    differently (its county box is not "below"). Both are data in the table, read through conditionsFor."""
    polish = ran["views"]["jobTypes"]["polish"]
    assert polish["asked"]["live"] == ["local", "prevailing_wage", "taxable", "remodel_tax", "reno", "dye",
                                       "joint_filler", "remove_existing_jf"]
    assert polish["asked"]["v2Intake"] == ["prevailing_wage", "taxable", "remodel_tax", "bond"]
    assert polish["asked"]["v2Takeoff"] == ["joint_filler", "remove_existing_jf", "dye"]
    assert polish["why"]["v2Intake"][2] == "Occupied remodel. Adds the county remodel rate on top."
    live_remodel = polish["why"]["live"][3]
    assert live_remodel.startswith("Occupied remodel. Taxed at the county rate") and live_remodel.endswith(
        "pick the county below.")
    assert ran["views"]["jobTypes"]["gyp"]["asked"]["live"] == ["local", "prevailing_wage", "taxable", "remodel_tax"]
    assert ran["views"]["jobTypes"]["epoxy"]["asked"]["live"] == [
        "local", "prevailing_wage", "taxable", "remodel_tax", "reno", "bulk_discount"]
    assert ran["views"]["jobTypes"]["combo"]["asked"]["v2Takeoff"] == ["joint_filler", "remove_existing_jf", "dye"]
    assert ran["views"]["jobTypes"]["epoxy"]["asked"]["v2Takeoff"] == []


# ══ 3. a job type is asked, and writes, what the live intake does ════════════════════════════════════
def test_the_live_intakes_conditions_are_the_tables_live_rows(ran):
    """THE EXECUTING PARITY TEST for the literal js/index.js keeps until Phase 9. Its nine rows, in its order,
    equal the table's rows asked on the live screen: key, label, who is asked, the default (its `def`), the
    cells, the two literals, and what it needs. Mutation: change a cell, a literal, a scope or a sentence on
    either side."""
    live = live_rows(ran)
    table = sorted((c for c in ran["data"]["CONDITIONS"] if c["asked_on"]["live"]), key=lambda c: c["asked_on"]["live"])
    assert [c["key"] for c in live] == [c["key"] for c in table]
    for mine, theirs in zip(table, live):
        assert theirs["key"] == mine["key"]
        assert theirs["label"] == mine["label"], mine["key"]
        assert theirs["why"] == mine["why"], mine["key"]
        assert theirs["scope"] == mine["scope"], mine["key"]
        assert theirs["def"] == mine["default"], mine["key"]
        assert theirs["cells"] == mine["cells"], mine["key"]
        assert (theirs["on"], theirs["off"]) == (mine["on"], mine["off"]), mine["key"]
        assert (theirs.get("needs") or None) == mine["needs"], mine["key"]


@pytest.mark.parametrize("job", JOB_TYPES)
def test_each_job_type_is_asked_the_conditions_the_live_intake_asks_it(ran, job):
    asked_live = [c["key"] for c in live_rows(ran) if job in c["scope"]]
    assert ran["views"]["jobTypes"][job]["asked"]["live"] == asked_live


@pytest.mark.parametrize("job", JOB_TYPES)
def test_each_job_type_writes_exactly_the_cells_the_live_intake_writes_for_it(ran, job):
    """Cell parity, by construction: the cells a job type writes are the cells of the live rows whose scope
    holds it. For a polish job that is eight conditions and every cell of the live intake bar the bulk
    discount; the Leveling and Gypsum Taxable cells are in there, which is what v2 used to leave out."""
    expected = [(c["key"], c["cells"], c["on"], c["off"]) for c in live_rows(ran) if job in c["scope"]]
    got = [(c["key"], c["cells"], c["on"], c["off"]) for c in ran["views"]["jobTypes"][job]["cells"]]
    assert got == expected


def test_the_live_intakes_scope_map_and_field_names_are_the_tables(ran):
    """SCOPE_BY_WORK_TYPE (which quantity fields each work type shows) and systemFieldNames (their names) are
    the intake's own literals until Phase 9. The table's job types derive both."""
    for job in JOB_TYPES:
        assert sorted(ran["live"]["scopeByWorkType"][job]) == sorted(ran["views"]["jobTypes"][job]["scopes"]), job
    by = {1: {}, 2: {}}
    for f in ran["data"]["FIELDS"]:
        if f["system"]:
            by[f["system"]][f["scope"]] = f["name"]
    assert {int(k): v for k, v in ran["live"]["systemFieldNames"].items()} == by


@pytest.mark.parametrize("job", JOB_TYPES)
def test_a_job_types_fields_are_the_ones_its_scope_shows(ran, job):
    scopes = set(ran["live"]["scopeByWorkType"][job])
    shown = [f["name"] for f in ran["data"]["FIELDS"] if f["scope"] in scopes and f["scope"] != "gyp"]
    gyp = [f["name"] for f in ran["data"]["FIELDS"] if f["scope"] == "gyp"] if job == "gyp" else []
    assert ran["views"]["jobTypes"][job]["fields"] == shown + gyp


class _Inputs(html.parser.HTMLParser):
    """Every <input name=...> of a page and, for radios, its value and the words beside it."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.names, self.radios, self._pending, self._text = [], [], None, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "input" and a.get("name"):
            self.names.append(a["name"])
            if a.get("type") == "radio":
                self._pending = {"name": a["name"], "value": a.get("value")}
                self._text = []

    def handle_data(self, data):
        if self._pending is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "label" and self._pending is not None:
            self._pending["label"] = " ".join("".join(self._text).split())
            self.radios.append(self._pending)
            self._pending = None


def _inputs(page: str) -> _Inputs:
    p = _Inputs()
    p.feed((FRONTEND / page).read_text(encoding="utf-8"))
    p.close()
    return p


def test_the_live_intakes_work_type_radios_are_the_tables_job_types(ran):
    data = ran["data"]
    page = _inputs("index.html")
    radios = [r for r in page.radios if r["name"] == "work_type"]
    assert [(r["value"], r["label"]) for r in radios] == [(j["key"], j["label"]) for j in data["JOB_TYPES"]]
    audiences = [r["value"] for r in page.radios if r["name"] == "audience"]
    assert audiences == ["Direct", "GC"]
    assert {a for j in data["JOB_TYPES"] for a in j["audiences"] if a} == set(audiences)


def test_the_live_intakes_gypsum_boxes_are_the_tables_gyp_fields(ran):
    names = set(_inputs("index.html").names)
    assert {f["name"] for f in ran["data"]["FIELDS"] if f["scope"] == "gyp"} <= names


class _Strip(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.buttons, self._open = [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "button" and a.get("data-work-type"):
            self._open = [a["data-work-type"], ""]

    def handle_data(self, d):
        if self._open:
            self._open[1] += d

    def handle_endtag(self, tag):
        if tag == "button" and self._open:
            self.buttons.append((self._open[0], self._open[1].strip()))
            self._open = None


def test_the_defaults_tabs_strip_is_the_tables_tabs(ran):
    """library.html draws the five work-type buttons as markup, a copy of the tab list in HTML."""
    s = _Strip()
    s.feed((FRONTEND / "library.html").read_text(encoding="utf-8"))
    # Global is the first pill and is not a work type: it holds the global values and the defaults
    # that name no work type. The five after it are the table's tabs, in the table's order.
    assert s.buttons == [("global", "Global")] + [(t["key"], t["label"]) for t in ran["data"]["TABS"]]


def test_the_estimate_screens_sheet_map_roles_and_area_keys_are_the_tables(ran):
    """js/estimate-review.js keeps its own sheet-to-layout map, role map, area cells and role sets until the
    pages are moved onto the table. What it says is held equal here, and where it DIFFERS on purpose the
    difference is pinned, so nobody closes it (or widens it) without meaning to."""
    data, review = ran["data"], ran["review"]
    sheets = {s: t["key"] for t in data["TABS"] for s in t["sheets"]}
    layout_of = {t["key"]: t["markupLayout"] for t in data["TABS"]}
    assert review["MARKUP_LAYOUT_OF"] == {s: layout_of[k] for s, k in sheets.items()}
    # the sheets the spreadsheet gives a role to agree with the table; two it leaves as "other"
    role_of = {t["key"]: t["role"] for t in data["TABS"]}
    for sheet, role in review["BASE_ROLE"].items():
        assert role_of[sheets[sheet]] == role, sheet
    assert sorted(set(sheets) - set(review["BASE_ROLE"])) == ["Epoxy blank", "Leveling"]
    # the area snapshot keys of each layout
    tab = {t["key"]: t for t in data["TABS"]}
    snap = {f["name"]: f["snapshot"] for f in data["FIELDS"]}
    assert sorted(review["AREA_SF_CELLS"]["Epoxy"]) == sorted(snap[n] for n in tab["epoxy"]["area"] + tab["epoxy"]["cove"])
    assert sorted(review["AREA_SF_CELLS"]["Polish"]) == sorted(snap[n] for n in tab["polish"]["area"])
    assert sorted(review["GYP_SF_CELLS"]) == sorted(tab["gyp"]["area"])
    # the role sets: a combo job's base tabs are exactly the combined ones
    combo = next(j for j in data["JOB_TYPES"] if j["key"] == "combo")
    assert sorted(review["COMBINED_BASE_ROLES"]) == sorted(role_of[t] for t in combo["tabs"])
    assert sorted(review["PRICED_ROLES"]) == sorted(set(review["BASE_ROLE"].values()))
    # THE ONE DIFFERENCE, on purpose: the spreadsheet calls Leveling "other", so it is not an option-only
    # ROLE there; the table calls it an option-only TAB. Computing OPTION_ONLY_ROLES from the table would
    # change what the spreadsheet does with a Leveling tab, and is its own change.
    assert review["OPTION_ONLY_ROLES"] == ["seal"]
    assert sorted(t["role"] for t in data["TABS"] if t["optionOnly"]) == ["leveling", "seal"]


# ══ 4. bid-model.js reads the table ══════════════════════════════════════════════════════════════════
def test_condition_cells_is_the_table_cut_for_polish_and_the_carried_one_is_renovation(ran):
    polish = [c for c in ran["data"]["CONDITIONS"] if "polish" in c["scope"] and c["cells"]]
    model = {c["key"]: {"cells": c["cells"], "on": c["on"], "off": c["off"]} for c in polish if c["model"]}
    assert ran["bid"]["conditionCells"] == model
    assert list(ran["bid"]["conditionCells"]) == ["local", "prevailing_wage", "taxable", "remodel_tax", "dye",
                                                  "joint_filler", "remove_existing_jf"]
    assert ran["bid"]["carried"] == [{"key": "reno", "cells": ["Epoxy!B10", "Polish!B10"], "on": "Reno",
                                      "off": "New", "default": False}]


def test_a_polish_save_writes_exactly_the_cells_the_live_intake_writes_for_polish(ran):
    live = {cell for c in live_rows(ran) if "polish" in c["scope"] for cell in c["cells"]}
    for state in ("allOff", "allOn"):
        assert set(ran["cellWrites"][state]) == live, state
    # and not the bulk discount, which the live intake asks of epoxy and combo only
    assert "Epoxy!D41" not in ran["cellWrites"]["allOn"]


def test_taxable_reaches_every_sheet_that_holds_its_own_flag(ran):
    """THE BUG THIS PHASE FIXES BY CONSTRUCTION. Leveling!B6 and the two Gyp B8 cells are independent literals
    that nothing on a v2 save wrote, so a tax-exempt option kept charging 9.475%."""
    cells = ["Epoxy!B6", "Leveling!B6", 'Gyp (USG 1-8")!B8', "Gyp (FR)!B8"]
    assert [ran["cellWrites"]["allOff"].get(c) for c in cells] == ["No"] * 4
    assert [ran["cellWrites"]["allOn"].get(c) for c in cells] == ["Yes"] * 4
    assert "Polish!B6" not in ran["cellWrites"]["allOn"], "Polish!B6 is =Epoxy!B6 and stays a formula"


def test_renovation_is_carried_through_and_a_blank_is_new_never_blank(ran):
    """The model has no renovation answer (Hanz took the toggle off its intake, 2026-09-23). The live intake
    writes it for every polish job, so a save carries what is there and fills a blank with the default: a
    blank Polish!B10 is not "New" to IF(B10="New",0.05,0.15), it takes the Reno branch and triples the patch
    material rate. The first cell THAT HOLDS AN ANSWER decides (Phase 7b), and it is written to both.

    PHASE 7b CHANGED ONE ANSWER HERE, ON PURPOSE: `renoOnlyOnPolish`, a "Reno" in Polish!B10 with Epoxy!B10
    blank, used to save as "New" in both cells (the first cell was blank, so the default applied) and now
    saves as "Reno" in both. The first cell still wins when it holds an answer (`renoNew`)."""
    w = ran["cellWrites"]

    def both(name):
        return (w[name].get("Epoxy!B10"), w[name].get("Polish!B10"))   # absent reads as None, never a KeyError
    assert both("allOff") == ("New", "New"), "a blank takes the default"
    assert both("allOn") == ("New", "New"), "the model's answers are not reno's"
    assert both("renoYes") == ("Reno", "Reno"), "a Reno survives a save"
    assert both("renoSpaced") == ("Reno", "Reno")
    assert both("renoNew") == ("New", "New"), "the first cell that holds an answer decides"
    assert both("renoOnlyOnPolish") == ("Reno", "Reno"), "a Reno in the second cell alone flipped to New"
    assert both("renoNumber") == ("New", "New"), "0 is not Reno"
    assert both("renoAskedByTheModelIsIgnored") == ("New", "New")
    assert w["keepsOtherCells"]["Epoxy!B1"] == "Nearman" and w["keepsOtherCells"]["Epoxy!D41"] == "BULK Discount ON"
    assert "reno" not in ran["fromCells"]["reno"], "the model carries no renovation answer to read back into"


def test_the_read_back_reads_the_first_cell_that_holds_an_answer(ran):
    """A condition with several cells (Local is two, Taxable is four) is read back from the FIRST ONE THAT
    HOLDS AN ANSWER. It used to be read from the first cell alone ("Leveling and Gypsum are written, never
    read"), so a blank Epoxy!B6 with an answer after it took the default and the next save wrote that default
    over the real answer in every cell of the row. PHASE 7b CHANGED THIS ON PURPOSE, for every multi-cell
    condition and not only Renovation. The first cell still wins when it holds an answer."""
    assert ran["fromCells"]["taxableOnly"] == {"taxable": False}, "a Leveling answer was dropped for a blank first cell"
    assert ran["fromCells"]["taxable"] == {"taxable": False}, "the first cell no longer wins"
    assert ran["fromCells"]["localSecondOnly"] == {"local": False}
    assert ran["fromCells"]["localFirstWins"] == {"local": True}


def test_a_fresh_models_answers_are_the_tables_defaults_and_the_live_intakes(ran):
    fresh = ran["bid"]["freshConditions"]
    assert fresh == {c["key"]: c["default"] for c in ran["data"]["CONDITIONS"] if c["model"]}
    assert list(fresh) == ["local", "prevailing_wage", "taxable", "remodel_tax", "bond", "dye", "joint_filler",
                           "remove_existing_jf"]
    # what the live intake starts the same questions on: kept in step by hand until now
    for c in live_rows(ran):
        if c["key"] in fresh:
            assert fresh[c["key"]] == c["def"], c["key"]


def test_a_default_applies_to_a_bid_when_it_applies_to_any_tab_of_the_job(ran):
    """THE COMBO FIX. A default's work types are tabs, and a combo job is priced on two of them, so it reads
    the Epoxy list AND the Polish list. It used to read neither, because nothing is filed under "combo"."""
    a = ran["bid"]["applies"]
    assert a["epoxy"] == {"polish": False, "epoxy": True, "combo": True, "gyp": False, "undefined": False}
    assert a["polish"] == {"polish": True, "epoxy": False, "combo": True, "gyp": False, "undefined": True}
    assert a["epoxyPolish"] == {"polish": True, "epoxy": True, "combo": True, "gyp": False, "undefined": True}
    assert a["gyp"] == {"polish": False, "epoxy": False, "combo": False, "gyp": True, "undefined": False}
    # Seal is an option on a bid, not part of any job's tabs: a default for Seal alone is no job's default
    assert a["seal"] == dict.fromkeys(["polish", "epoxy", "combo", "gyp", "undefined"], False)
    assert a["sealLeveling"] == dict.fromkeys(["polish", "epoxy", "combo", "gyp", "undefined"], False)
    # no list, an empty one, or something that is not a list: every tab, so every job
    for name in ("none", "empty", "aString"):
        assert all(a[name].values()), name


def test_workTypeApplies_refuses_what_is_not_a_job_type(ran):
    for j, r in ran["bid"]["appliesRefused"].items():
        assert "threw" in r and "tabsFor() was asked about" in r["threw"], (j, r)


def test_a_combo_job_opens_with_the_epoxy_and_the_polish_defaults(ran):
    """seedDefaultTakeoff, per job type. 'a' is filed under no tab (every tab), 'p' under polish, 'e' under
    epoxy, 'g' under gyp, 's' under seal. The reserved dye item is never seeded here."""
    t = ran["bid"]["takeoff"]
    assert t["polish"] == ["p", "a", "ip"]
    assert t["undefined"] == t["polish"], "a caller that says nothing gets Polish, as every caller did"
    assert t["epoxy"] == ["e", "a", "ie"]
    assert t["combo"] == ["p", "e", "a", "ip", "ie"], "combo reads both lists"
    assert t["gyp"] == ["g", "a"]
    assert "threw" in ran["bid"]["takeoffRefused"], "Seal is not a job type"


def test_a_combo_job_opens_with_the_epoxy_and_the_polish_labor_lines(ran):
    """seedLibraryLabor and the Travel gate, per job type. The Travel row is filed under epoxy alone, so it
    is on an epoxy bid and a combo bid and off a polish bid or a gyp one."""
    labor = ran["bid"]["labor"]
    assert labor["polish"] == ["polishing", "lp", "la"]
    assert labor["epoxy"] == ["polishing", "travel", "le", "la"]
    assert labor["combo"] == ["polishing", "travel", "lp", "le", "la"]
    assert labor["gyp"] == ["polishing", "lg", "la"]
    for j, r in ran["bid"]["travel"].items():
        assert r["epoxyOnly"] is (j in ("epoxy", "combo")), j
        assert r["declined"] is (j not in ("epoxy", "combo")), j


# ══ 5. loading, and where the pages load it ══════════════════════════════════════════════════════════
def _boot(*scripts):
    require_node()
    proc = run_node(BOOT, FRONTEND, *scripts)
    assert proc.returncode == 0, proc.stderr
    return last_json_line(proc.stdout)["scripts"]


def test_the_vocabulary_loads_alone_as_a_script_tag_and_publishes_one_global():
    (types,) = _boot("js/work-types.js")
    assert types["threw"] is None, types["threw"]
    assert types["published"] == ["TWWorkTypes"]
    # the boot harness lists the FUNCTION members of a global; the tables are checked by the harness itself
    assert {"appliesTo", "tabsFor", "conditionsFor", "cellsFor", "copyableCells", "modelDefaults",
            "reservedItems", "itemIdOf", "tabOfSheet", "fieldsFor", "scopesFor"} <= set(types["members"]["TWWorkTypes"])


def test_the_model_without_the_vocabulary_throws_an_error_that_names_the_file():
    leaf, model = _boot("js/excel-math.js", "js/bid-model.js")
    assert leaf["threw"] is None
    assert model["published"] == [], "a model that threw must not leave a half-built global behind"
    assert model["threw"] == "bid-model.js needs work-types.js loaded before it", model["threw"]


NAMED_ERROR = (
    "const vm = require('vm'), fs = require('fs');"
    "try { vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'),"
    " { window: {}, document: { getElementById: () => null }, console });"
    " console.log(JSON.stringify({ threw: null })); }"
    " catch (e) { console.log(JSON.stringify({ threw: String(e && e.message) })); }")


@pytest.mark.parametrize("script, message", [
    ("js/library.js", "library.js needs work-types.js loaded before it"),
    ("js/polish-sandbox.js", "polish-sandbox.js needs work-types.js loaded before it"),
    ("js/index.js", "index.js needs work-types.js loaded before it"),
])
def test_a_page_script_that_reads_the_vocabulary_says_so_by_name_when_it_is_missing(script, message):
    require_node()
    proc = run_node("-e", NAMED_ERROR, FRONTEND / script)
    assert proc.returncode == 0, proc.stderr
    assert last_json_line(proc.stdout) == {"threw": message}


def readers_of_the_vocabulary(frontend: pathlib.Path = FRONTEND):
    """Every script that reads window.TWWorkTypes, bar the vocabulary itself and the model (whose header
    declares it, and test_core_boot_order.py checks every page against that)."""
    return [("js/" + p.name) for p in sorted((frontend / "js").glob("*.js"))
            if p.name not in ("work-types.js", "bid-model.js") and "TWWorkTypes" in p.read_text(encoding="utf-8")]


def test_every_page_that_loads_a_reader_of_the_vocabulary_loads_the_vocabulary_first():
    """PHASE 7b ADDED THE LIVE INTAKE to the readers (js/index.js, for the split rule only): index.html now
    loads the vocabulary ahead of the page script, and the page throws by name when the tag is missing."""
    readers = readers_of_the_vocabulary()
    assert readers == ["js/index.js", "js/library.js", "js/polish-estimate.js", "js/polish-intake.js",
                       "js/polish-sandbox.js"]
    for page in sorted(FRONTEND.glob("*.html")):
        order = local_scripts(page.read_text(encoding="utf-8"))
        for reader in readers:
            if reader in order:
                assert "js/work-types.js" in order and order.index("js/work-types.js") < order.index(reader), (
                    "%s runs %s before the vocabulary it reads as it parses" % (page.name, reader))
    loads = {page.name for page in FRONTEND.glob("*.html") if "js/work-types.js" in local_scripts(page.read_text(encoding="utf-8"))}
    assert loads == {"index.html", "library.html", "polish-estimate.html", "polish-intake.html"}, (
        "only the pages that load the model, and the live intake for the split rule, load the vocabulary: %r"
        % sorted(loads))


# ══ 6. the copies are gone from the pages ════════════════════════════════════════════════════════════
GONE = [
    ("js/library.js", 'var WORK_TYPES = ["polish"'),
    ("js/library.js", '"joint-filler-kit": "joint_filler"'),
    ("js/library.js", 'item_id: "joint-filler-kit", label'),
    ("js/library.js", '"remove-existing-jf"'),
    ("js/library.js", '"joint-filler-kit"'),
    ("js/polish-estimate.js", '"joint-filler-kit"'),
    ("js/polish-estimate.js", '"remove-existing-jf"'),
    ("js/polish-intake.js", '{ key: "prevailing_wage", label: "Prevailing wage",'),
    ("js/polish-estimate.js", 'cell: "Polish!E29"'),
    ("js/polish-estimate.js", 'item_id: "remove-existing-jf"'),
    ("js/polish-estimate.js", 'item_id: "dye"'),
    ("js/bid-model.js", 'cells: ["Polish!E25"]'),
    ("js/bid-model.js", 'taxable:         { cells:'),
    ("js/polish-sandbox.js", '"Epoxy!B4", "Polish!B4",'),
    # PHASE 7b: the split rule has one home. The live intake's own job-type ladder for the base sheets, its own
    # address pattern, and the v2 intake's own loop that read a condition back off its first cell.
    ("js/index.js", 'wt === "combo" ? ["Epoxy", "Polish"]'),
    ("js/index.js", "[A-Z]{1,3}[0-9]{1,5}$/"),
    ("js/polish-intake.js", "for (var ck in CONDITION_CELLS)"),
]


@pytest.mark.parametrize("rel, needle", GONE, ids=lambda v: v if v.startswith("js/") else v[:30])
def test_the_replaced_copy_is_not_in_the_page_any_more(rel, needle):
    """REPLACE, DO NOT RUN IN PARALLEL (docs/v2-architecture.md, rule 1). Each literal below was a second
    home for a fact the table now owns. A plain text search for what only the literal said, so a copy typed
    back in beside the table fails here by name."""
    assert needle not in (FRONTEND / rel).read_text(encoding="utf-8"), "%s has its own copy again: %s" % (rel, needle)


# ══ 7. red without the change ════════════════════════════════════════════════════════════════════════
TYPES = "js/work-types.js"
MODEL = "js/bid-model.js"


def _each_job(check):
    return lambda r: [check(r, job) for job in JOB_TYPES]


# name -> (file, the line, what it becomes, files that must come along, the check that must go red)
BREAKS = {
    "appliesTo stops refusing a job type": (
        TYPES, "    if (!isTab(layout)) {", "    if (false) {", [MODEL],
        test_appliesto_throws_on_a_job_type_and_on_anything_that_is_not_a_tab),
    "appliesTo reads an empty list as none": (
        TYPES, "    if (!Array.isArray(defaultWorkTypes) || !defaultWorkTypes.length) return true;",
        "    if (!Array.isArray(defaultWorkTypes)) return true;", [MODEL],
        test_appliesto_reads_an_empty_list_as_every_tab_and_a_list_as_those_tabs),
    "a combo job loses its polish tab": (
        TYPES, '    { key: "combo",  label: "Combo (Epoxy + Polish)", tabs: ["epoxy", "polish"], ready: false,',
        '    { key: "combo",  label: "Combo (Epoxy + Polish)", tabs: ["epoxy"], ready: false,', [MODEL],
        test_the_four_job_types_and_the_five_tabs_are_the_ones_the_tool_has),
    "Taxable goes back to one cell": (
        TYPES, """      default: true, cells: ["Epoxy!B6", "Leveling!B6", 'Gyp (USG 1-8")!B8', "Gyp (FR)!B8"],""",
        '      default: true, cells: ["Epoxy!B6"],', [MODEL],
        test_the_live_intakes_conditions_are_the_tables_live_rows),
    "the model stops writing the Leveling and Gypsum Taxable cells": (
        TYPES, """      default: true, cells: ["Epoxy!B6", "Leveling!B6", 'Gyp (USG 1-8")!B8', "Gyp (FR)!B8"],""",
        '      default: true, cells: ["Epoxy!B6"],', [MODEL],
        test_taxable_reaches_every_sheet_that_holds_its_own_flag),
    "joint filler ships on again": (
        TYPES, '      default: false, cells: ["Polish!E29"], on: "Yes", off: "No", needs: null,',
        '      default: true, cells: ["Polish!E29"], on: "Yes", off: "No", needs: null,', [MODEL],
        test_a_fresh_models_answers_are_the_tables_defaults_and_the_live_intakes),
    "dye is no longer asked of a combo job": (
        TYPES, '    { key: "dye", label: "Dye", scope: ["polish", "combo"],',
        '    { key: "dye", label: "Dye", scope: ["polish"],', [MODEL],
        _each_job(test_each_job_type_writes_exactly_the_cells_the_live_intake_writes_for_it)),
    "the v2 intake loses its own wording": (
        TYPES, '    if (c.wording && typeof c.wording[surface] === "string") row.why = c.wording[surface];',
        "    void 0;", [MODEL],
        test_each_screen_gets_its_questions_in_its_own_order_and_its_own_words),
    "a screen loses its order": (
        TYPES, "      .sort(function (a, b) { return a.asked_on[surface] - b.asked_on[surface]; })",
        "      .sort(function (a, b) { return 0; })", [MODEL],
        test_each_screen_gets_its_questions_in_its_own_order_and_its_own_words),
    "a screen is asked everything": (
        TYPES, "      .filter(function (c) { return c.asked_on[surface] > 0; })",
        "      .filter(function (c) { return true; })", [MODEL],
        test_each_screen_gets_its_questions_in_its_own_order_and_its_own_words),
    "the table can be edited by a reader": (
        TYPES, "  deepFreeze(CONDITIONS);", "  void 0;", [MODEL],
        test_the_table_cannot_be_edited_by_a_reader_and_the_readers_hand_out_copies),
    "the model reads the wrong job type's rows": (
        MODEL, '  var POLISH_CELLS = types.cellsFor("polish");', '  var POLISH_CELLS = types.cellsFor("epoxy");', [],
        test_condition_cells_is_the_table_cut_for_polish_and_the_carried_one_is_renovation),
    "workTypeApplies goes back to reading one name": (
        MODEL, '    return types.tabsFor(workType || "polish").some(function (tab) { return types.appliesTo(list, tab); });',
        '    return !(list instanceof Array) || !list.length || list.indexOf(workType || "polish") !== -1;', [],
        test_a_default_applies_to_a_bid_when_it_applies_to_any_tab_of_the_job),
    "the default takeoff is Polish's again": (
        MODEL, "    var applies = function (r) { return workTypeApplies(r, workType); };",
        '    var applies = function (r) { return workTypeApplies(r, "polish"); };', [],
        test_a_combo_job_opens_with_the_epoxy_and_the_polish_defaults),
    "a save stops carrying renovation": (
        MODEL, "    CARRIED_CELLS.forEach(function (carried) {", "    [].forEach(function (carried) {", [],
        test_renovation_is_carried_through_and_a_blank_is_new_never_blank),
    "a fresh model forgets a default": (
        MODEL, "      conditions: types.modelDefaults(),",
        "      conditions: Object.assign(types.modelDefaults(), { local: false }),", [],
        test_a_fresh_models_answers_are_the_tables_defaults_and_the_live_intakes),
    # PHASE 7b: a condition with several cells is answered by the first cell that holds an answer.
    "the read-back goes back to the first cell": (
        MODEL, "      var cell = firstFilled(types.writeCellsFor(key, MODEL_JOB, !!split), cv, unanswered);",
        "      var cell = firstFilled(types.writeCellsFor(key, MODEL_JOB, !!split).slice(0, 1), cv, unanswered);", [],
        test_the_read_back_reads_the_first_cell_that_holds_an_answer),
    "a save reads only the first renovation cell": (
        MODEL, "      var first = firstFilled(carried.cells, out, isBlank);",
        "      var first = firstFilled(carried.cells.slice(0, 1), out, isBlank);", [],
        test_renovation_is_carried_through_and_a_blank_is_new_never_blank),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_checks_go_red_when_the_code_changes(tmp_path, name):
    """One line of one file is broken in a scratch copy, the harness runs against it, and the named check
    has to fail on what it answers. The harness is run OUTSIDE the try, so a mutation that merely crashes it
    is an error and not a pass."""
    require_node()
    rel, old, new, also, check = BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new, also=also)
    broken = _run(frontend)
    with pytest.raises(AssertionError):
        check(broken)


def test_the_unbroken_answer_passes_every_check_the_table_names():
    """The other half: the same functions, called the same way, are green on the real code."""
    real = _run()
    for rel, old, new, also, check in BREAKS.values():
        check(real)


def test_every_check_a_break_names_is_a_real_test_and_each_group_of_checks_has_a_break():
    named = {check for *_, check in BREAKS.values()}
    assert len(named) >= 9, "the table of breaks lost most of its checks"
    for must in (test_appliesto_throws_on_a_job_type_and_on_anything_that_is_not_a_tab,
                 test_the_live_intakes_conditions_are_the_tables_live_rows,
                 test_taxable_reaches_every_sheet_that_holds_its_own_flag,
                 test_renovation_is_carried_through_and_a_blank_is_new_never_blank,
                 test_a_default_applies_to_a_bid_when_it_applies_to_any_tab_of_the_job,
                 test_a_combo_job_opens_with_the_epoxy_and_the_polish_defaults):
        assert must in named, "no break turns %s red" % must.__name__
