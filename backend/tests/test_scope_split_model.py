"""Splitting a bid's sheets into separate proposals, in the model: B.splitOut (scope groups, tier A1).

RJ, 2026-10-24: Breakroom (polish), Lab 1 (epoxy) and Lab 2 (epoxy) built as sheets of one estimate, then "Split into
separate proposals": each sheet becomes a one-sheet bid with itself as the base. tests/js/scope-split-harness.js executes
the real js/bid-model.js and prints one line of JSON; this file asserts on it.

THE PROMISE THAT MATTERS: WHAT EACH SHEET IS PRICED AT DOES NOT MOVE. The harness prices every sheet before the split
(the carrier with the job's Lodging and Per Diem, an option with its own crew's nights) and every child after it, and
the two must agree to the dollar. That is also the travel hazard the audit found, held from the other side: Breakroom's
Lodging is TYPED at 10 nights, and it must reach Breakroom's proposal and no other.
"""
import pathlib

import pytest

from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
FRONTEND = TESTS.parents[1] / "frontend"
HARNESS = TESTS / "js" / "scope-split-harness.js"


@pytest.fixture(scope="module")
def ran():
    require_node()
    proc = run_node(HARNESS, FRONTEND)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.mark.parametrize("section", ["clean", "refusals", "ownDrive"])
def test_no_section_of_the_harness_failed(ran, section):
    assert "error" not in ran[section], ran[section].get("error")


# ── a clean three-sheet split ───────────────────────────────────────────────
def test_every_sheet_of_the_bid_is_offered(ran):
    assert ran["clean"]["tabs"] == ["Polish", "Epoxy", "Copy1"]
    assert ran["clean"]["blockers"] is None


@pytest.mark.parametrize("tab,job,label", [("Polish", "polish", "Breakroom"), ("Epoxy", "epoxy", "Lab 1"),
                                           ("Copy1", "epoxy", "Lab 2")])
def test_each_child_is_its_own_one_base_bid(ran, tab, job, label):
    k = ran["clean"]["kids"][tab]
    assert k["base"] == {"ids": [tab], "jobType": job}
    assert k["live"] == [[tab, "base"]], "another sheet is still part of this proposal"
    assert k["carrier"] == tab, "the child's own crew must carry its travel"
    assert k["label"] == label
    assert k["patch"]["work_type"] == job and k["patch"]["base_tab_id"] == tab
    # every other sheet under `tabs` is gone, and the root is off unless it IS the sheet
    assert k["tabsLeft"] == ([] if tab == "Polish" else [tab])
    assert k["rootKind"] == ("base" if tab == "Polish" else "off")
    assert "Polish" not in (k["patch"].get("tab_opts") or {}) or tab == "Polish"


@pytest.mark.parametrize("tab", ["Polish", "Epoxy", "Copy1"])
def test_no_sheet_is_priced_differently_for_being_split(ran, tab):
    before, after = ran["clean"]["before"][tab], ran["clean"]["kids"][tab]
    assert after["travel"] == before["travel"]
    assert after["price"] == before["price"]


def test_the_split_does_not_touch_the_model_it_was_handed(ran):
    assert ran["clean"]["untouched"] is True


# ── the typed-travel hazard ─────────────────────────────────────────────────
def test_the_carriers_typed_nights_stay_on_its_own_proposal(ran):
    kids = ran["clean"]["kids"]
    lodging = kids["Polish"]["lodging"]
    assert (lodging["qty_auto"], lodging["qty"], lodging.get("qty_typed")) == (False, 10, True)
    assert kids["Polish"]["wasCarrier"] is True


@pytest.mark.parametrize("tab", ["Epoxy", "Copy1"])
def test_the_typed_nights_do_not_appear_on_any_other_scope(ran, tab):
    k = ran["clean"]["kids"][tab]
    for line in (k["lodging"], k["perDiem"]):
        assert line["qty_auto"] is True and line["qty_follow"] == "labor" and "qty_typed" not in line, line
        assert line["qty"] != 10
    assert k["wasCarrier"] is False
    # its own crew's nights, the figure it was charged as an option
    assert k["travel"]["lodging"] == ran["clean"]["before"][tab]["travel"]["lodging"]


def test_an_option_with_no_drive_is_given_none_of_the_carriers(ran):
    kids = ran["clean"]["kids"]
    assert kids["Polish"]["driveRows"] == [{"guys": 2, "days": 4}]
    assert kids["Epoxy"]["driveRows"] == [] and kids["Copy1"]["driveRows"] == []


def test_a_sheet_with_a_drive_of_its_own_keeps_it(ran):
    assert ran["ownDrive"]["driveRows"] == [{"guys": 4, "days": 3}]


# ── refusals ────────────────────────────────────────────────────────────────
def test_an_option_only_sheet_refuses_the_split(ran):
    r = ran["refusals"]["seal"]
    assert r["blockers"] and "Seal" in r["blockers"] and r["tabs"] == []
    assert r["threw"] == r["blockers"]


def test_a_combined_base_refuses_the_split(ran):
    r = ran["refusals"]["combined"]
    assert r["base"] == ["Polish", "Epoxy"]
    assert r["blockers"] and "priced together" in r["blockers"]
    assert r["threw"] == r["blockers"]


def test_one_sheet_refuses_the_split(ran):
    r = ran["refusals"]["one"]
    assert r["blockers"] and r["tabs"] == [] and r["threw"] == r["blockers"]


def test_a_sheet_that_is_off_is_not_a_proposal(ran):
    r = ran["refusals"]["offSheet"]
    assert r["tabs"] == ["Polish", "Epoxy"]
    assert r["threw"] and "not part of this bid" in r["threw"]


def test_bad_input_throws(ran):
    assert "Nope" in ran["refusals"]["unknown"]
    assert ran["refusals"]["notAModel"]
