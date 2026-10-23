""""Split into separate proposals" on the REAL estimate page, and the race the audit found (scope groups, tier A1).

tests/js/scope-split-page-harness.js runs js/polish-estimate.js whole over the real js/bid-model.js, on a bid of three sheets
(Breakroom polish, the base; Lab 1 and Lab 2 epoxy options), with an edit PENDING when Split is pressed. One line of JSON out.

THE RACE. After the server rewrites the parent as its first scope, this page still holds the three-sheet copy, and its own
autosave (or a second tab) could PUT it straight back over the split. Held here from the page's side: what it typed is saved and
flushed BEFORE the split is asked, the split is asked of the version it then read, the server's copy is adopted BEFORE the reload,
and nothing it does afterwards (the pending timer, a keystroke, the page closing) saves the old copy. test_scope_groups.py holds
the server's side: a save of the pre-split copy is refused with 409 split_since.
"""
import pathlib

import pytest

from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
FRONTEND = TESTS.parents[1] / "frontend"
HARNESS = TESTS / "js" / "scope-split-page-harness.js"


@pytest.fixture(scope="module")
def ran():
    require_node()
    proc = run_node(HARNESS, FRONTEND)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.mark.parametrize("section", ["race", "refused", "blocked", "rename"])
def test_no_section_of_the_harness_failed(ran, section):
    assert "error" not in ran[section], ran[section].get("error")


def test_a_bid_of_several_sheets_is_offered_the_split(ran):
    r = ran["race"]
    assert r["offered"]["hidden"] is False and "Split into separate proposals" in r["offered"]["text"]
    assert "Split into 3 separate proposals" in r["asked"] and "Breakroom stays on this page" in r["asked"]


def test_the_split_waits_for_the_pending_edit_and_asks_of_the_copy_it_read(ran):
    r = ran["race"]
    assert r["armedBefore"] >= 1, "the scenario never had a save pending, so it proves nothing about the race"
    assert r["editSaved"] == "20000", "the edit typed just before Split never reached the save"
    assert r["order"][:3] == ["flush:1", "read", "split:1"], r["order"]
    assert r["version"] == "v-read"


def test_the_servers_copy_is_adopted_before_the_page_reloads(ran):
    r = ran["race"]
    assert r["order"][3:] == ["adopt", "reload"], r["order"]
    assert (r["adopted"], r["reloads"]) == (1, 1)


def test_nothing_saves_the_old_copy_after_the_split(ran):
    """The pending timer fired, a keystroke, the page closing: not one of them may write the three-sheet model."""
    assert ran["race"]["savesAfterSplit"] == 0


def test_each_scope_is_sent_as_a_one_sheet_bid_priced_as_the_sheet_was(ran):
    r = ran["race"]
    kids = r["children"]
    assert [(k["tab"], k["label"], k["work_type"], k["base"]) for k in kids] == [
        ("Polish", "Breakroom", "polish", "Polish"), ("Epoxy", "Lab 1", "epoxy", "Epoxy"), ("Copy1", "Lab 2", "epoxy", "Copy1")]
    for k in kids:
        assert k["live"] == [[k["tab"], "base"]]
        assert k["lump"] == k["proposalLump"] == r["sheetPrices"][k["tab"]], (
            "%s is sent at %s but the page priced the sheet at %s" % (k["label"], k["lump"], r["sheetPrices"][k["tab"]]))


def test_a_refused_split_gives_the_page_back(ran):
    r = ran["refused"]
    assert "Not split: Nothing changed." in r["note"]
    assert (r["adopted"], r["reloads"]) == (0, 0)
    assert r["savesAgain"] >= 1, "after a refusal the page stopped saving what is typed"


def test_a_bid_that_cannot_be_split_says_why_and_offers_no_button(ran):
    r = ran["blocked"]
    assert r["button"] is False and "Seal" in r["text"]
    assert r["oneSheetHidden"] is True and r["oneSheetText"] == ""


def test_a_scope_shows_its_name_and_renames_through_the_server(ran):
    r = ran["rename"]
    assert "One scope of this project: Breakroom" in r["shown"]
    assert r["body"] == {"label": "Break room", "rename": True}
    assert r["local"] == [{"partial": {"scope_group": {"id": "grp_x", "label": "Break room"}},
                           "opts": {"alreadyOnServer": True}}]
    assert "Break room" in r["after"]
