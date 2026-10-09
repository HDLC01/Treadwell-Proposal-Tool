"""The Python half of the vocabulary is pinned to frontend/js/work-types.js by ONE executing test.

Python is not generated from JavaScript: the server keeps its own lists because it has to work when no
browser has loaded anything. What it must not do is disagree. Before Phase 7 these were seven places that
each said which work types exist, kept equal by hand:

    markup.TABS, library.WORK_TYPES                  the five workbook tabs (library's is markup's)
    leads._WORK_TYPES, leads._QUANTITY_KEYS          the four job types, and every intake quantity field
    proposal_writer.TEMPLATE_PICKER                  (work type, audience) -> proposal template
    cover_letter_writer.TEMPLATE_PICKER              the same for the cover letter
    info_sheet_writer._SF_KEYS, _LF_KEYS, _COVE_ROLES which saved keys make up a tab's area
    condition_defaults.KEYS                          the three conditions the Takeoff step carries
    library.RESERVED_ITEM_IDS                        the three library rows that price them
    main.detect_work_type                            Epoxy and Polish square feet -> epoxy, polish or combo

The test RUNS NODE, dumps the vocabulary the way a page sees it (tests/js/work-types-harness.js) and compares.
`drift()` is the whole comparison and returns every difference as a sentence, so the test asserts it is empty
and the checks below it prove it is not empty when a list drifts: a pin that cannot fail pins nothing.

Run under node; a missing node FAILS under CI (tests/_node.py).
"""
from __future__ import annotations

import copy
import importlib
import pathlib

import pytest

from _golden_support import FRONTEND
from _node import last_json_line, require_node, run_node

HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "work-types-harness.js"

# Proposal documents that are not a job type: a GC sealer proposal and a Direct budget-pricing sheet. They are
# the only keys of proposal_writer.TEMPLATE_PICKER the vocabulary does not own, named here so that a new
# template appearing in Python fails the pin until somebody decides what it is.
NOT_A_JOB_TYPE = {("sealer", "GC"), ("budget", "Direct")}


@pytest.fixture(scope="module")
def table():
    require_node()
    proc = run_node(HARNESS, FRONTEND)
    assert proc.returncode == 0, proc.stderr
    return last_json_line(proc.stdout)["data"]


def server():
    """The server's own lists, copied so a check can drift one without touching the module."""
    markup, library = importlib.import_module("markup"), importlib.import_module("library")
    leads, pw = importlib.import_module("leads"), importlib.import_module("proposal_writer")
    cl, isw = importlib.import_module("cover_letter_writer"), importlib.import_module("info_sheet_writer")
    cd, main = importlib.import_module("condition_defaults"), importlib.import_module("main")
    return {
        "markup_TABS": tuple(markup.TABS),
        "library_WORK_TYPES": tuple(library.WORK_TYPES),
        "leads_WORK_TYPES": tuple(leads._WORK_TYPES),
        "leads_QUANTITY_KEYS": tuple(leads._QUANTITY_KEYS),
        "proposal_templates": set(pw.TEMPLATE_PICKER),
        "cover_letter_templates": set(cl.TEMPLATE_PICKER),
        "sf_keys": copy.deepcopy(isw._SF_KEYS),
        "lf_keys": tuple(isw._LF_KEYS),
        "cove_roles": set(isw._COVE_ROLES),
        "condition_keys": tuple(cd.KEYS),
        "reserved_item_ids": tuple(library.RESERVED_ITEM_IDS),
        "detect_work_type": main.detect_work_type,
    }


def drift(table: dict, py: dict) -> list[str]:
    """Every way the server's lists differ from the table, as sentences. Empty means pinned."""
    problems: list[str] = []

    def same(label, got, want):
        if got != want:
            problems.append("%s is %r, the vocabulary says %r" % (label, got, want))

    tabs = [t["key"] for t in table["TABS"]]
    jobs = table["JOB_TYPES"]
    fields = table["FIELDS"]
    snapshot = {f["name"]: f["snapshot"] for f in fields}

    same("markup.TABS", py["markup_TABS"], tuple(tabs))
    same("library.WORK_TYPES", py["library_WORK_TYPES"], tuple(tabs))
    same("leads._WORK_TYPES", py["leads_WORK_TYPES"], tuple(j["key"] for j in jobs))
    same("leads._QUANTITY_KEYS", py["leads_QUANTITY_KEYS"], tuple(f["name"] for f in fields))

    templates = {(j["proposalKey"], a) for j in jobs for a in j["audiences"]}
    same("proposal_writer.TEMPLATE_PICKER keys", py["proposal_templates"], templates | NOT_A_JOB_TYPE)
    same("cover_letter_writer.TEMPLATE_PICKER keys", py["cover_letter_templates"], templates)

    area = {t["key"]: t for t in table["TABS"] if t["area"]}
    same("info_sheet_writer._SF_KEYS roles", set(py["sf_keys"]), set(area))
    for key, tab in area.items():
        want = (tuple(snapshot[n] for n in tab["area"]), tuple(tab["area"]))
        same("info_sheet_writer._SF_KEYS[%r]" % key, tuple(map(tuple, py["sf_keys"].get(key, ()))), want)
    epoxy = next(t for t in table["TABS"] if t["key"] == "epoxy")
    same("info_sheet_writer._LF_KEYS", tuple(map(tuple, py["lf_keys"])),
         (tuple(snapshot[n] for n in epoxy["cove"]), tuple(epoxy["cove"])))
    cove = {f["name"] for f in fields if f["scope"] == "cove"}
    same("info_sheet_writer._COVE_ROLES", py["cove_roles"], {j["key"] for j in jobs if cove & set(j["fields"])})

    takeoff = sorted((c for c in table["CONDITIONS"] if c["asked_on"]["v2Takeoff"]),
                     key=lambda c: c["asked_on"]["v2Takeoff"])
    same("condition_defaults.KEYS", py["condition_keys"], tuple(c["key"] for c in takeoff))
    same("library.RESERVED_ITEM_IDS", set(py["reserved_item_ids"]), {c["item_id"] for c in table["CONDITIONS"] if c["item_id"]})

    # detect_work_type turns Epoxy and Polish square feet into a job type: a job type priced on exactly the
    # epoxy tab, exactly the polish tab, or both. (Gyp is picked, never detected.)
    for j in jobs:
        if set(j["tabs"]) <= {"epoxy", "polish"}:
            e = 1 if "epoxy" in j["tabs"] else 0
            p = 1 if "polish" in j["tabs"] else 0
            same("detect_work_type(%d, %d)" % (e, p), py["detect_work_type"](e, p), j["key"])
    return problems


def test_the_server_agrees_with_the_one_vocabulary(table):
    assert drift(table, server()) == []


# ── the pin can fail ─────────────────────────────────────────────────────────────────────────────────
def mutated(**changes):
    py = server()
    py.update(changes)
    return py


def test_a_tab_added_or_dropped_on_the_server_is_noticed(table):
    py = mutated(markup_TABS=("polish", "seal", "epoxy", "leveling", "gyp", "terrazzo"))
    assert any("markup.TABS" in p for p in drift(table, py))
    py = mutated(library_WORK_TYPES=("polish", "seal", "epoxy", "gyp"))
    assert any("library.WORK_TYPES" in p for p in drift(table, py))


def test_a_job_type_or_a_quantity_key_added_on_the_server_is_noticed(table):
    assert any("leads._WORK_TYPES" in p for p in drift(table, mutated(leads_WORK_TYPES=("epoxy", "polish", "combo", "gyp", "seal"))))
    assert any("leads._QUANTITY_KEYS" in p for p in drift(table, mutated(leads_QUANTITY_KEYS=("system_1_sf",))))


def test_a_template_added_or_dropped_on_the_server_is_noticed(table):
    py = server()
    assert any("proposal_writer" in p for p in drift(table, mutated(proposal_templates=py["proposal_templates"] | {("seal", "GC")})))
    assert any("proposal_writer" in p for p in drift(table, mutated(proposal_templates=py["proposal_templates"] - {("gyp", None)})))
    assert any("cover_letter_writer" in p for p in drift(table, mutated(cover_letter_templates=py["cover_letter_templates"] | {("polish", None)})))


def test_a_changed_area_key_is_noticed(table):
    py = server()
    sf = copy.deepcopy(py["sf_keys"])
    sf["seal"] = (("epoxy_sf", "epoxy_sf_2"), ("system_1_sf", "system_2_sf"))     # the hazard the comment records
    assert any("_SF_KEYS['seal']" in p for p in drift(table, mutated(sf_keys=sf)))
    sf = copy.deepcopy(py["sf_keys"])
    sf.pop("gyp")
    assert any("_SF_KEYS roles" in p for p in drift(table, mutated(sf_keys=sf)))
    assert any("_LF_KEYS" in p for p in drift(table, mutated(lf_keys=(("cove_lf",), ("cove_1_lf",)))))
    assert any("_COVE_ROLES" in p for p in drift(table, mutated(cove_roles={"epoxy", "combo", "polish"})))


def test_a_changed_condition_key_or_reserved_row_is_noticed(table):
    assert any("condition_defaults.KEYS" in p for p in drift(table, mutated(condition_keys=("joint_filler", "remove_existing_jf", "dye", "bond"))))
    assert any("condition_defaults.KEYS" in p for p in drift(table, mutated(condition_keys=("dye", "joint_filler", "remove_existing_jf"))))
    assert any("RESERVED_ITEM_IDS" in p for p in drift(table, mutated(reserved_item_ids=("dye", "joint-filler-kit"))))


def test_a_changed_detection_rule_is_noticed(table):
    assert any("detect_work_type" in p for p in drift(table, mutated(detect_work_type=lambda e, p: "epoxy")))
