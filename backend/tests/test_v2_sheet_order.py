"""A BID'S SHEETS KEEP THEIR ORDER ACROSS A SAVE AND A RELOAD (2026-10-20, round 6, item C1).

THE DEFECT. `model.tabs` is an object, one key to a sheet, and the draft lives in a jsonb column, which keeps NO key order: PostgreSQL hands every object back with its keys sorted
by length in bytes and then by the bytes (tests/js/_jsonb.js). So a bid saved in one order was read back in another ("Copy1" sorts before 'Gyp (USG 1-8")'; on staging the sheet bar
read [Gyp (base), Polish 2] in the session and [Polish 2, Gyp (base)] after a reload). Everything that reads the sheets in order read the other one: the sheet bar, the sheet the bid
opens on, the options the customer's document lists, and, because the section that carries the job's travel is the FIRST base, the drive and the nights that are charged. With two
bases that are both under `tabs` (a Polish copy made the base beside Epoxy, the root an option or off) the carrier, its crew and the price flipped:

    far Combo (Polish 6 x 10, Epoxy 4 x 12), the Polish sheet copied, the copy made the base, then Epoxy + the copy made the base:
    session   carrier Epoxy, lump sum $78,628   (Epoxy $41,253 + Copy1 $37,375)
    reload    carrier Copy1, lump sum $81,086   (Copy1 $47,813 + Epoxy $33,273)

THE FIX. Every section under `tabs` carries `seq`, its place in the bid (a number that only ever grows: a new, copied or added sheet is last), and `sectionsOf` lists the root and
then the sections by `seq`, whatever order their keys are in. A bid saved before the order was kept has no `seq`: it is stamped when it opens, in the order its saved price was computed
in (the draft's priced_tabs, an array, which jsonb keeps in order) when that names two or more of its sheets and in its keys' order when it does not, and saved by its next save; nothing is
written on open and no price moves (round 6 audit: stamped in the keys' order, a far Combo saved at $78,628 with Epoxy and a Polish copy both bases opened on the copy as the carrier and
its first save wrote $81,086). Two sheets that claim one place (a copy made by a tab still running the code from before this) are told apart by `source`, a copy standing after the sheet it
was copied from, and then by their ids.

HOW THESE TESTS RUN. tests/js/sheet-order-harness.js drives js/polish-estimate.js whole, over the real js/bid-model.js, as a person does (a new far bid, a copy, a fresh sheet, a base
change, a rename, a delete, a job-type switch), and reads every fact twice: off the session that made the bid, and off a page opened on the blob that session saved, re-keyed as the server
returns it (tests/js/_jsonb.js, validated against PostgreSQL's documented order by test_jsonb_key_order.py). The customer's document is the real proposal-review.js `rebuildPricing` run
over what the page saved. The last block breaks a COPY of the model one line at a time and requires a fact to change (never a crash).
"""
from __future__ import annotations

import pathlib

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "sheet-order-harness.js"
PAGE_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js",
              "js/markup-core.js", "js/library-core.js", "js/library-picker.js", "js/work-types.js", "js/excel-math.js",
              "js/epoxy-takeoff.js", "js/gyp-takeoff.js", "js/seal-takeoff.js", "js/price-lines-core.js", "js/proposal-review.js"]
SECTIONS = ["comboCopyBase", "epoxyAddPolish", "stripOrder", "documentOrder", "lifecycle", "staleCopy", "partlyStamped", "gypCopyPreset", "afterReload", "legacy", "model",
            "invariance"]
GYP = 'Gyp (USG 1-8")'
GYP_FR = "Gyp (FR)"
# What a page shows that depends on the order of the sheets, as the harness reads it. (Not `open`: a session is on whatever sheet the estimator was last
# working on, and a bid that is opened is on the sheet that carries the job; test_a_reloaded_bid_opens_on_the_sheet_that_carries_the_job holds that one.)
FACTS = ["order", "kinds", "carrier", "strip", "bases", "jobType", "prices", "document"]


def run(frontend=FRONTEND):
    proc = run_node(HARNESS, frontend, timeout=600)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr[-800:]
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    require_node()
    got = run()
    crashed = sorted(k for k in SECTIONS if "error" in got.get(k, {}))
    assert not crashed, "a section of the harness failed: " + "; ".join("%s: %s" % (k, got[k]["error"][:600]) for k in crashed)
    return got


def differences(left, right, label=""):
    """Every fact the two pages disagree on, as 'fact: session X, reload Y' lines (the facts listed in FACTS)."""
    out = []
    for fact in FACTS:
        if left.get(fact) != right.get(fact):
            out.append("%s%s: session %s  /  reload %s" % (label, fact, left.get(fact), right.get(fact)))
    return out


# ── the proof: two bases under `tabs` ───────────────────────────────────────────────────────────
def test_two_bases_under_tabs_are_the_setup_the_defect_needs(ran):
    """Not vacuous: Epoxy and the Polish copy are both bases, neither is the root, the root is an option, and their crews differ (the guys on the carrier's labor are what the nights
    count, so the carrier is the one thing that moves the price)."""
    got = ran["comboCopyBase"]["session"]
    assert got["bases"] == ["Epoxy", "Copy1"] and got["jobType"] == "combo", got
    assert got["order"][0] == "Polish" and got["kinds"][0] == "option", got
    assert sorted(got["prices"]["sections"]) == ["Copy1", "Epoxy"] and got["prices"]["sections"]["Copy1"] != got["prices"]["sections"]["Epoxy"], got["prices"]
    assert got["prices"]["lump"] > 0


def test_the_carrier_and_the_price_are_the_sessions_after_a_reload(ran):
    """THE DEFECT: far Combo, Polish copy made the base beside Epoxy. Epoxy carried the drive in the session and Copy1 after a reload: $78,628 became $81,086 with nothing edited."""
    got = ran["comboCopyBase"]
    assert got["session"]["carrier"] == "Epoxy"
    assert got["reload"]["carrier"] == got["session"]["carrier"], differences(got["session"], got["reload"])
    assert got["reload"]["prices"] == got["session"]["prices"], (got["session"]["prices"], got["reload"]["prices"])


@pytest.mark.parametrize("scenario", ["comboCopyBase", "epoxyAddPolish", "stripOrder", "documentOrder"])
def test_every_fact_that_depends_on_the_sheets_order_is_the_sessions_after_a_reload(ran, scenario):
    got = ran[scenario]
    assert differences(got["session"], got["reload"]) == []


def test_the_pair_made_from_an_epoxy_job_has_both_bases_under_tabs_too(ran):
    got = ran["epoxyAddPolish"]
    assert got["madeCombined"] is True and got["copyId"] == "Copy1", got
    assert got["session"]["bases"] == ["Epoxy", "Copy1"] and got["session"]["kinds"][0] == "off", got["session"]


def test_the_sheet_bar_lists_the_sheets_in_the_order_they_were_added(ran):
    """Seen on staging: [Gyp (base), Polish 2] in the session, [Polish 2, Gyp (base)] after a reload."""
    got = ran["stripOrder"]
    assert got["session"]["strip"] == [GYP, "Copy1"], got["session"]
    assert got["reload"]["strip"] == got["session"]["strip"], got["reload"]["strip"]
    assert got["session"]["order"] == ["Polish", GYP, "Copy1"] == got["reload"]["order"]


@pytest.mark.parametrize("scenario", ["comboCopyBase", "epoxyAddPolish", "stripOrder", "documentOrder"])
def test_a_reloaded_bid_opens_on_the_sheet_that_carries_the_job(ran, scenario):
    """A bid opens on the first sheet that is part of it as a base (openingTab): the carrier. Reloaded, that is the sheet the session carried the job on."""
    got = ran[scenario]
    assert got["reload"]["open"] == got["reload"]["carrier"] == got["session"]["carrier"], (got["session"]["carrier"], got["reload"]["carrier"], got["reload"]["open"])


def test_the_customers_document_lists_the_options_in_the_order_they_were_added(ran):
    """The real proposal-review.js rebuildPricing over what the page saved: Epoxy added first, then the Polish sheet. After a reload, and after the reloaded page saves again."""
    got = ran["documentOrder"]
    assert got["session"]["document"] == [GYP + " (base)", "Epoxy", "Copy1"], got["session"]["document"]
    assert got["reload"]["document"] == got["session"]["document"], got["reload"]["document"]
    assert got["reloadTwice"]["document"] == got["session"]["document"], got["reloadTwice"]["document"]
    assert got["editedOnce"]["prices"]["pricedTabs"] == got["session"]["prices"]["pricedTabs"], got["editedOnce"]["prices"]["pricedTabs"]


def test_a_reload_edited_and_reloaded_again_still_agrees(ran):
    got = ran["comboCopyBase"]
    assert got["reloadTwice"]["order"] == got["session"]["order"], got["reloadTwice"]["order"]
    assert got["reloadTwice"]["carrier"] == got["editedOnce"]["carrier"] == "Epoxy"
    assert got["reloadTwice"]["prices"] == got["editedOnce"]["prices"], (got["editedOnce"]["prices"], got["reloadTwice"]["prices"])


# ── every way a sheet comes, goes and changes ──────────────────────────────────────────────────
LIFECYCLE = ["start", "add Gyp", "copy Epoxy (Copy1)", "copy Polish (Copy2)", "rename Copy1", "delete Copy2",
             "copy Epoxy again (takes the freed Copy2)", "change the Gyp sheet to another preset (its key changes)", "make Gyp the base",
             "make the Epoxy + Polish pair the base", "job type switched to Epoxy"]


def test_the_lifecycle_walk_ran_every_step(ran):
    assert [s["step"] for s in ran["lifecycle"]["steps"]] == LIFECYCLE


@pytest.mark.parametrize("step", LIFECYCLE)
def test_the_order_survives_a_reload_after_every_step(ran, step):
    got = [s for s in ran["lifecycle"]["steps"] if s["step"] == step][0]
    assert differences(got["session"], got["reload"]) == []


def test_a_freed_copy_id_taken_again_goes_last(ran):
    """Copy2 was deleted and Epoxy copied again: the new Copy2 is the newest sheet, so it is last, not where the old Copy2 stood."""
    step = [s for s in ran["lifecycle"]["steps"] if s["step"].startswith("copy Epoxy again")][0]
    assert step["session"]["order"] == ["Polish", "Epoxy", GYP, "Copy1", "Copy2"], step["session"]["order"]
    assert step["reload"]["order"] == step["session"]["order"]


def test_a_gyp_sheet_that_changes_preset_keeps_its_place(ran):
    """The preset re-files the section under another KEY ('Gyp (USG 1-8")' to 'Gyp (FR)': eight bytes, so it sorts in front of the long one), and its place stays where it was."""
    step = [s for s in ran["lifecycle"]["steps"] if s["step"].startswith("change the Gyp sheet")][0]
    assert step["session"]["order"] == ["Polish", "Epoxy", GYP_FR, "Copy1", "Copy2"], step["session"]["order"]
    assert step["reload"]["order"] == step["session"]["order"], step["reload"]["order"]


# ── round 7, part 2 (L5): the two shapes the round-6 order audit found no test held ─────────────────────────
PARTLY_STAMPED = {"Epoxy": 1, GYP: 2, "Copy1": 3, "Copy2": 4}


def test_a_bid_some_of_whose_sheets_say_no_place_has_every_place_written_down_when_it_opens(ran):
    """A page that kept the order wrote Epoxy's place, and a tab running the code from before it added Gyp and two copies with none (the draft holds them in the order that tab wrote them). Opened, the
    page writes down the place of EVERY sheet (withSectionOrder completes the stamping; its early return is only for a bid whose every sheet says its place), saves nothing on open, and its next save
    carries all four places, so a reload lists the sheets exactly as the session did. jsonb hands the keys back as Copy1, Copy2, Epoxy, Gyp: a save that left the three without a place came back with
    Gyp moved to the end.

    Mutation: the early return taken when ANY sheet says its place (`ids.some`): the three are never stamped, and the reload moves Gyp."""
    got = ran["partlyStamped"]
    assert got["held"] == {"keys": ["Epoxy", GYP, "Copy1", "Copy2"], "seqs": {"Epoxy": 1, GYP: None, "Copy1": None, "Copy2": None}}, "not the shape the case needs: %r" % (got["held"],)
    assert got["quiet"] == {"armed": 0, "saves": 0}
    assert got["stamped"] == PARTLY_STAMPED and got["savedSeqs"] == PARTLY_STAMPED
    assert got["session"]["order"] == ["Polish", "Epoxy", GYP, "Copy1", "Copy2"], got["session"]["order"]
    assert differences(got["session"], got["reload"]) == []


def test_a_copy_of_the_gyp_sheet_that_changes_preset_keeps_its_place(ran):
    """A copy keeps its Copy<N> key when its preset changes (moveSectionSheet writes the new sheet into it), where the Gyp sheet itself is re-filed under the new sheet's key
    (test_a_gyp_sheet_that_changes_preset_keeps_its_place). Gyp, Epoxy, Copy1 (the Gyp copy), Copy2 (an Epoxy copy): Copy1 moved to Gyp (FR) holds its place, third, in the session and after a reload.

    Mutation: the copy's preset change drops its place."""
    got = ran["gypCopyPreset"]
    order = ["Polish", GYP, "Epoxy", "Copy1", "Copy2"]
    assert (got["gypCopy"], got["epoxyCopy"]) == ("Copy1", "Copy2") and got["before"]["order"] == order, got["before"]
    assert got["moved"] == {"sheet": GYP_FR, "seq": 3}
    assert got["session"]["order"] == order and got["session"]["strip"] == order[1:], got["session"]
    assert differences(got["session"], got["reload"]) == []


def test_a_rename_moves_nothing(ran):
    before = [s for s in ran["lifecycle"]["steps"] if s["step"] == "copy Polish (Copy2)"][0]
    after = [s for s in ran["lifecycle"]["steps"] if s["step"] == "rename Copy1"][0]
    assert after["session"]["order"] == before["session"]["order"] and after["reload"]["order"] == before["session"]["order"]


# ── a rename, a delete, a kind change, a copy and a job switch made AFTER A RELOAD ──────────────
# The lifecycle above makes each of them in a session that never reloaded, where the keys of `tabs` are in the order of the sheets' places: a step that renumbered the sheets
# by their keys (or put them last, or dropped their places) would move nothing there. On a page opened on the server's blob the keys are in jsonb's order, and it would move them.
AFTER_START = ["Polish", "Epoxy", GYP, "Copy1", "Copy2"]


def test_the_bid_the_after_reload_steps_start_from_is_not_in_jsonbs_order(ran):
    """Not vacuous: the places are Epoxy, Gyp, Copy1, Copy2 and the keys the server returns are Copy1, Copy2, Epoxy, Gyp. A page opened on the blob lists the sheets by their places."""
    got = ran["afterReload"]["start"]
    assert got["keys"] == ["Epoxy", GYP, "Copy1", "Copy2"] and got["reloadedKeys"] == ["Copy1", "Copy2", "Epoxy", GYP], got
    assert got["opened"]["order"] == AFTER_START and got["opened"]["strip"] == AFTER_START, got["opened"]
    assert got["opened"]["kinds"] == ["base", "base", "option", "option", "option"], got["opened"]


@pytest.mark.parametrize("step, order, strip", [("rename", AFTER_START, AFTER_START), ("kind", AFTER_START, AFTER_START), ("delete", ["Polish", "Epoxy", GYP, "Copy1"], ["Polish", "Epoxy", GYP, "Copy1"]),
                                                ("copy", AFTER_START + ["Copy3"], AFTER_START + ["Copy3"]),
                                                ("job", AFTER_START, AFTER_START[1:])])         # (a job type that puts the root off leaves it no tab on the bar)
def test_a_step_made_after_a_reload_moves_no_sheet_and_the_next_reload_agrees(ran, step, order, strip):
    """The sheets stay in the order they were in (a delete takes its sheet out and a copy goes last), on the sheet bar and in the model, in the session that made the step and on a
    page opened on what it saved."""
    got = ran["afterReload"][step]
    assert got["session"]["order"] == order and got["session"]["strip"] == strip, (step, got["session"]["order"], got["session"]["strip"])
    assert got["reload"]["order"] == order and got["reload"]["strip"] == strip, (step, got["reload"]["order"], got["reload"]["strip"])
    assert differences(got["session"], got["reload"]) == []


def test_the_after_reload_steps_did_what_they_say(ran):
    """So a step that quietly did nothing cannot pass for one that moved nothing."""
    got = ran["afterReload"]
    assert "Garage" in got["rename"]["labels"], got["rename"]["labels"]
    assert "Copy2" in got["delete"]["before"]["order"] and "Copy2" not in got["delete"]["session"]["order"]
    assert got["kind"]["before"]["kinds"] == ["base", "base", "option", "option", "option"], got["kind"]["before"]
    assert got["kind"]["session"]["kinds"] == ["option", "option", "option", "base", "option"] and got["kind"]["session"]["carrier"] == "Copy1", got["kind"]["session"]
    assert got["copy"]["session"]["order"][-1] == "Copy3"
    assert got["job"]["session"]["kinds"] == ["off", "base", "option", "option", "option"] and got["job"]["session"]["carrier"] == "Epoxy", got["job"]["session"]


def test_the_pure_steps_made_on_a_model_the_server_returned_move_no_sheet(ran):
    """The same steps as functions of the model (rename, delete, removeOption, pickBase, copy, addOption), on a model whose keys are in jsonb's order (Copy1, Copy2, Epoxy, Gyp) and whose
    places are Epoxy 1, Copy1 2, Copy2 3, Gyp 4. removeOption is public model API the page does not reach (its press is the Sheets delete), and it rewrites `tabs` the same way."""
    got = ran["model"]["served"]
    assert got["keys"] == ["Copy1", "Copy2", "Epoxy", GYP], got["keys"]
    whole = ["Polish", "Epoxy", "Copy1", "Copy2", GYP]
    assert got["rename"] == whole and got["kind"] == whole, got
    assert got["delete"] == got["removeOption"] == ["Polish", "Epoxy", "Copy1", GYP], got
    assert got["copy"] == whole + ["Copy3"] and got["option"] == whole + ["Seal"], got


# ── nothing else depends on key order either ─────────────────────────────────────────────────
def test_nothing_a_saved_draft_shows_or_does_depends_on_the_order_of_any_objects_keys(ran):
    """Every draft the scenarios saved (twenty of them: the pairs, the bar, the document, every step of the lifecycle, a bid saved before the order was kept, and since round 7, part 2 a bid some of
    whose sheets said no place and a Gyp copy moved to another preset), opened with the keys of EVERY object in five orders (as saved,
    jsonb's, jsonb's reversed, two seeded shuffles): the sheets in order with their kinds, the carrier, the bases, the bar, every price, what the customer's document lists and the whole
    blob the page then saves are the same each time. The sheets under `tabs` were the only thing that read an object's key order (run the same check over a bid saved by 619f092 and the
    keys of `tabs` are the only ones whose order moves anything); this holds the rest of the draft to it."""
    got = ran["invariance"]
    assert got["blobs"] >= 20 and got["compared"] >= 80, "the check was cut short: %r" % ({k: got[k] for k in ("blobs", "compared")},)
    assert got["differ"] == [], got["differ"][:5]


# ── a bid saved before the order was kept ────────────────────────────────────────────────────
LEGACY_CASES = ["unlisted", "oneListed"]


def test_the_legacy_bid_is_one_the_keys_would_flip(ran):
    """Not vacuous. The order the saved price was computed in (priced_tabs: Polish, Epoxy, Copy1, Copy2; Epoxy carries the job's travel) is not the order jsonb holds the sheets'
    keys in (Copy1, Copy2, Epoxy: Copy1 would carry it), so a page that took the keys' order opens the bid on another carrier and prices it differently."""
    got = ran["legacy"]
    assert got["pricedTabs"] == ["Polish", "Epoxy", "Copy1", "Copy2"] and got["keyOrder"] == ["Copy1", "Copy2", "Epoxy"], got
    assert got["session"]["carrier"] == "Epoxy" and got["session"]["bases"] == ["Epoxy", "Copy1"], got["session"]
    assert got["unlisted"]["opened"]["carrier"] == "Copy1", "with nothing but the keys' order the carrier is Copy1: the setup the defect needs"
    assert got["savedLump"] == got["session"]["prices"]["lump"] and got["savedLump"] > 0


def test_a_legacy_bid_opens_in_the_order_its_saved_price_was_computed_in(ran):
    """A save writes priced_tabs in the same save as the model and the lump sum, in the order the sheets were in, and jsonb keeps an array's order. A bid saved before `seq` was
    kept has no place written anywhere, and its list is the only record of the order its price was made in (the first base carries the job's travel)."""
    got = ran["legacy"]
    assert got["opened"]["order"] == got["pricedTabs"], got["opened"]
    assert got["opened"]["seqs"] == [1, 2, 3] and got["opened"]["carrier"] == "Epoxy", got["opened"]


def test_the_first_save_of_a_legacy_bid_writes_the_price_it_was_saved_at(ran):
    """THE DEFECT (round 6 audit): far Combo, Epoxy 4 x 12 and a Polish copy 6 x 10 the two bases, saved at $78,628. Opened on Copy1 as the carrier (jsonb's key order), and its first
    save stamped THAT order for good and wrote $81,086: +$2,458 with nothing edited. Every fact the order decides is the saving session's, and so is the lump sum."""
    got = ran["legacy"]
    assert got["facts"]["prices"]["lump"] == got["savedLump"], (got["savedLump"], got["facts"]["prices"]["lump"])
    assert differences(got["session"], got["facts"]) == []


def test_a_legacy_bid_the_list_says_nothing_about_opens_in_the_order_its_keys_are_held_in(ran):
    """No priced_tabs, or one that names a single sheet under `tabs` (which says nothing about the order of the others): the order the keys are held in is all there is."""
    for case in LEGACY_CASES:
        got = ran["legacy"][case]
        assert got["opened"]["order"] == ["Polish"] + ran["legacy"]["keyOrder"], (case, got["opened"])
        assert got["opened"]["seqs"] == [1, 2, 3], (case, got["opened"])


def test_a_legacy_bid_stamps_its_order_when_it_opens_and_writes_nothing(ran):
    for got in [ran["legacy"]] + [ran["legacy"][c] for c in LEGACY_CASES]:
        assert got["quiet"] == {"armed": 0, "saves": 0, "asked": 0}, got["quiet"]
        assert got["opened"]["seqs"] == [1, 2, 3], got["opened"]


def test_stamping_the_order_changes_no_price(ran):
    """The same bid with the order it opens in written down by hand as 1, 2, 3 prices, lists and carries exactly what the unstamped one does."""
    for got in [ran["legacy"]] + [ran["legacy"][c] for c in LEGACY_CASES]:
        assert differences(got["facts"], got["byHand"]) == []


def test_the_next_save_of_a_legacy_bid_keeps_the_order_it_opened_with(ran):
    got = ran["legacy"]
    assert got["savedSeqs"] == [["Epoxy", 1], ["Copy1", 2], ["Copy2", 3]], got["savedSeqs"]
    assert differences(got["facts"], got["reloadOfSaved"]) == []
    for case in LEGACY_CASES:
        got = ran["legacy"][case]
        assert got["savedSeqs"] == [["Copy1", 1], ["Copy2", 2], ["Epoxy", 3]], (case, got["savedSeqs"])
        assert differences(got["facts"], got["reloadOfSaved"]) == []


# ── the model alone ─────────────────────────────────────────────────────────────────────────────
def test_the_order_does_not_depend_on_the_order_of_the_keys(ran):
    got = ran["model"]
    assert got["stamped"] == {"Epoxy": 1, "Copy1": 2, "Copy2": 3, GYP: 4}, got["stamped"]
    assert got["order"] == ["Polish", "Epoxy", "Copy1", "Copy2", GYP]
    assert set(got["stampedOrders"]) == {" | ".join(got["order"])}, "the order moved with the keys: %d different orders" % len(set(got["stampedOrders"]))
    assert got["viaServer"] == got["order"]


def test_an_unstamped_section_is_newer_than_a_stamped_one(ran):
    """Whatever put it there kept no order (a model made by hand, a page still running the code from before this), and what it put is the newest thing in the bid. The unstamped
    ones keep the order their keys are held in."""
    got = ran["model"]
    assert got["mixed"]["keysAB"] == ["Polish", "Copy2", GYP, "Epoxy", "Copy1"], got["mixed"]
    assert got["mixed"]["keysBA"] == ["Polish", "Copy2", GYP, "Copy1", "Epoxy"], got["mixed"]


def test_two_sections_with_one_stamp_are_told_apart_by_their_ids_and_not_by_their_keys(ran):
    got = ran["model"]
    assert set(got["tieOrders"]) == {" | ".join(["Polish", "Copy1", "Copy2", "Epoxy", GYP])}, got["tieOrders"]


def test_a_copy_that_holds_its_sources_place_stands_after_it_whatever_the_keys_and_the_ids(ran):
    """A page still running the code from before this round copied a section whole, `seq` and all, so the copy and its source claim one place and the tie was settled by the ids:
    Copy2 (a copy of Epoxy) sorted in front of the sheet it came from. The copy is the newer sheet, and stands after it, with the keys in any of their 24 orders."""
    got = ran["model"]["sourceTie"]
    assert got["pair"] == [" | ".join(["Polish", "Epoxy", "Copy2", "Copy1", GYP])], got["pair"]


def test_copies_of_copies_with_one_place_stand_in_the_order_they_were_made(ran):
    """Epoxy, Copy2 (a copy of Epoxy) and Copy3 (a copy of Copy2) all hold place 1; the ids alone would say Copy2, Copy3, Epoxy."""
    got = ran["model"]["sourceTie"]
    assert got["chain"] == [" | ".join(["Polish", "Epoxy", "Copy2", "Copy3", "Copy1", GYP])], got["chain"]


def test_a_copy_of_a_copy_stands_after_both_not_after_one_hop_and_the_ids(ran):
    """Epoxy, Copy2 (a copy of Epoxy) and Copy1 (a copy of Copy2: a freed id handed out again) hold place 1. One hop and the ids would give Epoxy, Copy1, Copy2."""
    got = ran["model"]["sourceTie"]
    assert got["deepChain"] == [" | ".join(["Polish", "Epoxy", "Copy2", "Copy1", GYP])], got["deepChain"]


def test_a_loop_of_sources_ends_and_is_told_apart_by_the_ids(ran):
    """A hand-made model in which Epoxy and Copy2 each name the other as their source: no copy is older, so the ids decide, and the walk down the sources stops."""
    got = ran["model"]["sourceTie"]
    assert got["loop"] == [" | ".join(["Polish", "Copy2", "Epoxy", "Copy1", GYP])], got["loop"]


def test_a_source_that_is_not_in_the_tie_is_nothing(ran):
    """Copy1 ties with Gyp. Its source is Epoxy, which holds another place, or it is not a sheet's name at all (a number, an unknown id, the root, null, a list), or it is Copy1 itself: the
    ids decide (Copy1 first)."""
    got = ran["model"]["sourceTie"]
    expected = [" | ".join(["Polish", "Epoxy", "Copy2", "Copy1", GYP])]
    assert got["apart"] == expected, got["apart"]
    assert got["junkSource"] == [expected] * 6, got["junkSource"]


def test_a_copy_an_older_page_made_opens_right_after_its_source(ran):
    """A saved bid (Epoxy place 1, Gyp place 2) with a copy of Epoxy added the way the code from before this round made one: Copy1 holds place 1 too, and jsonb keeps its key first."""
    got = ran["staleCopy"]
    assert got["held"]["epoxy"] == got["held"]["copy"] == 1 and got["held"]["gyp"] == 2, got["held"]
    assert got["held"]["keys"][0] == "Copy1", "the setup: the keys and the ids both put the copy in front of its source"
    assert got["opened"]["order"] == ["Polish", "Epoxy", "Copy1", GYP] and got["opened"]["strip"] == got["opened"]["order"], got["opened"]
    assert got["reload"]["order"] == got["opened"]["order"] and got["reload"]["strip"] == got["opened"]["strip"], got["reload"]
    assert got["savedSeqs"]["Copy1"] == 1 and got["savedSeqs"]["Epoxy"] == 1, "nothing renumbers the tie: the next save carries the places it was given"


def test_a_bid_with_no_stamps_is_in_the_order_its_keys_are_held_in(ran):
    got = ran["model"]
    assert got["legacy"]["held"] == ["Copy2", "Epoxy", GYP, "Copy1"]
    assert got["legacy"]["order"] == ["Polish"] + got["legacy"]["held"], got["legacy"]


def test_withSectionOrder_stamps_the_order_once(ran):
    got = ran["model"]
    assert got["stampedOnce"] == {"seqs": {"Copy2": 1, "Epoxy": 2, GYP: 3, "Copy1": 4}, "order": ["Polish", "Copy2", "Epoxy", GYP, "Copy1"]}, got["stampedOnce"]
    assert got["stampedTwiceSame"] is True and got["alreadyStampedSame"] is True


def test_a_copy_takes_its_own_place_last_and_never_its_sources(ran):
    got = ran["model"]
    assert got["copy"]["id"] == "Copy3" and got["copy"]["order"][-1] == "Copy3", got["copy"]
    assert got["copy"]["seqs"]["Copy3"] == 5 and got["copy"]["seqs"]["Epoxy"] == 1, got["copy"]["seqs"]
    assert got["copy"]["copyOfCopy"]["id"] == "Copy4" and got["copy"]["copyOfCopy"]["seqs"]["Copy4"] == 6, got["copy"]["copyOfCopy"]


def test_an_option_added_to_a_bid_goes_last(ran):
    got = ran["model"]["option"]
    assert got["order"] == ["Polish", "Epoxy", "Copy1", "Copy2", GYP, "Seal"], got["order"]
    assert got["seqs"]["Seal"] == 5 and got["seqs"]["Epoxy"] == 1, got["seqs"]


def test_a_freed_copy_id_handed_out_again_is_last(ran):
    got = ran["model"]["reused"]
    assert got["id"] == "Copy1" and got["order"] == ["Polish", "Epoxy", "Copy2", GYP, "Copy1"], got


def test_sections_that_cannot_be_read_are_carried_as_they_are(ran):
    got = ran["model"]["hostile"]
    assert got == {"same": True, "strange": 5, "seqsUntouched": True}, got
    assert ran["model"]["unreadable"] == {"same": True}, "a bid whose sections cannot be read is carried exactly as it was saved (a section with no layout)"


def test_a_sheet_added_to_a_bid_saved_before_the_order_was_kept_goes_last(ran):
    """Copy2, Epoxy, Gyp, Copy1 are held in that order and none says its place: they are stamped in that order first, and the new one comes after all of them."""
    got = ran["model"]["oldBid"]
    assert got["held"] == ["Copy2", "Epoxy", GYP, "Copy1"], got
    assert got["copy"]["id"] == "Copy3" and got["copy"]["order"] == ["Polish", "Copy2", "Epoxy", GYP, "Copy1", "Copy3"], got["copy"]
    assert got["copy"]["seqs"] == {"Copy2": 1, "Epoxy": 2, GYP: 3, "Copy1": 4, "Copy3": 5}, got["copy"]
    assert got["fresh"]["id"] == "Seal" and got["fresh"]["order"][-1] == "Seal" and got["fresh"]["seqs"]["Seal"] == 5, got["fresh"]


def test_a_save_carries_the_order_and_lists_the_priced_tabs_in_it(ran):
    """What a save writes for a bid with no stamps (composePricingSnapshot): every section holds its place, 1 to n in the order they are listed, and priced_tabs is that order."""
    got = ran["model"]["composed"]
    assert "error" not in got, got
    assert got["seqs"] == {"Copy2": 1, "Epoxy": 2, "Copy1": 3}, got
    assert got["pricedTabs"] == ["Polish", "Copy2", "Epoxy", "Copy1"] and got["keys"] == ["Copy2", "Epoxy", "Copy1"], got


# ── the saved list (priced_tabs) as the order of a bid with no places ───────────────────────────
KEYED = ["Polish", "Copy2", "Epoxy", GYP, "Copy1"]          # oldBid: the keys are held in this order, none says its place
KEYED_SEQS = {"Copy2": 1, "Epoxy": 2, GYP: 3, "Copy1": 4}


def test_a_saved_list_that_names_two_or_more_sheets_is_the_order_of_a_bid_with_no_places(ran):
    got = ran["model"]["priced"]
    assert got["full"]["order"] == ["Polish", "Epoxy", "Copy1", "Copy2", GYP] and got["full"]["seqs"] == {"Epoxy": 1, "Copy1": 2, "Copy2": 3, GYP: 4}, got["full"]
    assert got["full"]["same"] is False


def test_the_sheets_a_saved_list_does_not_name_go_after_the_ones_it_does_in_key_order(ran):
    """An `off` sheet is never priced, so a save does not list it: it has no place in the list. It goes after the named ones, in the order its keys are held in (Copy2, then Copy1)."""
    got = ran["model"]["priced"]["named2"]
    assert got["order"] == ["Polish", GYP, "Epoxy", "Copy2", "Copy1"] and got["seqs"] == {GYP: 1, "Epoxy": 2, "Copy2": 3, "Copy1": 4}, got


def test_a_list_that_says_nothing_about_the_order_leaves_the_keys_in_charge(ran):
    """No list, not a list, an empty one, and one that names a single sheet under `tabs`."""
    got = ran["model"]["priced"]
    for name in ("named1", "none", "notAList", "empty"):
        assert got[name]["order"] == KEYED and got[name]["seqs"] == KEYED_SEQS, (name, got[name])


def test_whatever_in_a_list_names_no_sheet_of_the_bid_names_nothing(ran):
    """A repeat, an id the bid has no sheet for, the root, `toString` and `__proto__` (which every object has and `tabs` does not), and a string, a number, a null and a list where an entry belongs."""
    got = ran["model"]["priced"]
    assert got["junk"] == got["named2"], got["junk"]


def test_a_list_is_read_only_when_no_sheet_says_its_place(ran):
    """One sheet that says its place makes the places the order (the others are newer, in key order); a bid that says every place is handed back as it is."""
    got = ran["model"]["priced"]
    assert got["partlyStamped"]["order"] == ["Polish", "Epoxy", "Copy2", GYP, "Copy1"], got["partlyStamped"]
    # ...and every sheet of it has its place written down, not only the one that had one (round 7, part 2, L5: withSectionOrder's early return is for a bid that says EVERY place)
    assert got["partlyStamped"]["seqs"] == {"Epoxy": 1, "Copy2": 2, GYP: 3, "Copy1": 4} and got["partlyStamped"]["same"] is False, got["partlyStamped"]
    assert got["allStamped"]["same"] is True and got["allStamped"]["order"] == ["Polish", "Epoxy", "Copy1", "Copy2", GYP], got["allStamped"]


# ── the backend's half: what the customer's document is made from ─────────────────────────────────
def test_the_document_prints_the_options_in_the_order_of_the_rooms_it_is_given():
    """main._build_options walks `rooms` (the list the Proposal step builds out of priced_tabs, which a save writes in the sheets' order) and sorts nothing: the order the page
    saves is the order the customer reads. Held here because the whole round's premise is that nothing downstream puts the options in an order of its own."""
    import main

    def room(i, total):
        return {"id": i, "name": i, "is_base": False, "show": True, "price_mode": "total", "base_total": 90000, "system_desc": i,
                "bid": {"total": total, "sales_tax": 0, "remodel": 0, "taxable": False, "remodel_on": False}}

    rooms = [room("Epoxy", 41000), room("Copy1", 37000), room("Copy2", 52000)]
    assert [o["id"] for o in main._build_options(rooms, {}, "epoxy")] == ["Epoxy", "Copy1", "Copy2"]
    assert [o["id"] for o in main._build_options(list(reversed(rooms)), {}, "epoxy")] == ["Copy2", "Copy1", "Epoxy"]


# ── red without the code: break a COPY of the model one line at a time ─────────────────────────────
def _flipped(r):
    """The session and the reload disagree about something the order of the sheets decides."""
    return any(differences(r[k]["session"], r[k]["reload"]) for k in ("comboCopyBase", "epoxyAddPolish", "stripOrder", "documentOrder")) or \
        any(differences(s["session"], s["reload"]) for s in r["lifecycle"]["steps"])


MODEL = "js/bid-model.js"
PAGE = "js/polish-estimate.js"
SECTIONS_OF = "    tabIdsInOrder(tabs).forEach(function (id) {"
PUT_STAMP = "    var body = isObject(section) && !hasSeq(section) ? Object.assign({}, section, { seq: lastSeq(tabs) + 1 }) : section;"
PUT_FIRST = "    var out = withSectionOrder(jsonCopy(model));"
COPY_SEQ = "      delete body.seq;"
COMPOSE = "    var entries = sectionsOf(withSectionOrder(model));"
STAMP_LIST = "    out.tabs = copyInto({}, Object.fromEntries(listed.map(function (id, i) {"
LISTED = "    var listed = (anyPlace ? null : savedOrderOf(tabs, pricedTabs)) || tabIdsInOrder(tabs);"
NAMED_ENOUGH = "    if (named.length < 2) return null;"
NAMED_TAIL = "    return named.concat(tabIdsInOrder(tabs).filter(function (id) { return named.indexOf(id) < 0; }));"
NAMED_PUSH = "      if (id !== null && has.call(tabs, id) && named.indexOf(id) < 0) named.push(id);"
KIND = "    out.tabs = copyInto(copyInto({}, out.tabs), Object.fromEntries([[tabId, Object.assign({}, model.tabs[tabId], { kind: kind })]]));"
DELETE = "      .map(function (k) { return [k, out.tabs[k]]; })));"
RENAME = "    return withSectionPatch(model, id, { label: next });"
REMOVE = "      .map(function (id) { return [id, out.tabs[id]]; })));"
AFTER_DELETED = ["Polish", "Epoxy", GYP, "Copy1"]
WAITING = '      return typeof s === "string" && s !== row.id && left.some(function (r) { return r.id === s; });'
PICK = "      var pick = 0;"
RUNS = "      while (rows[i].seq !== null && j < rows.length && rows[j].seq === rows[i].seq) j++;"
PAIR_ORDER = [" | ".join(["Polish", "Epoxy", "Copy2", "Copy1", GYP])]
LOOP_ORDER = [" | ".join(["Polish", "Copy2", "Epoxy", "Copy1", GYP])]
STAMPED_ALREADY = "    if (ids.every(function (id) { return hasSeq(tabs[id]); })) return model;       // (and a bid with no sections at all)"
READABLE = "    if (readableSections(model) === null) return model;"
TIE = "      return a.id < b.id ? -1 : (a.id > b.id ? 1 : 0);    // one place claimed twice: by the id, which survives a reload"
UNSTAMPED_LAST = "        return a.seq === null ? 1 : -1;                   // one that says none is newer than one that does"
UNSTAMPED_KEYS = "        if (a.seq === b.seq) return a.held - b.held;      // neither says its place: the order the keys are held in"
BY_SEQ = "      if (a.seq !== b.seq) return a.seq - b.seq;"
PRESET = "    var moved = Object.assign({}, out.tabs[fromTab], { profile: profile.stamp });"
COPY_PRESET = "    if (COPY_ID.test(fromTab)) return withSectionPatch(model, fromTab, { sheet: toTab, profile: profile.stamp });"
ADOPT = "    ROOT = B.withSectionOrder(B.migrateModel(state.polish_estimate), state.priced_tabs);"
SAVE_ON_OPEN = "    if (restructured) saveSoon();"
HELD = ["Copy1", "Copy2", "Epoxy"]

# name -> (file, old, new, what the harness must report for the break to have been seen)
MUTATIONS = {
    "sectionsOf lists the sections in the order their keys are held in": (
        MODEL, SECTIONS_OF, "    Object.keys(tabs).forEach(function (id) {",
        lambda r: _flipped(r) and len(set(r["model"]["stampedOrders"])) > 1 and len(r["invariance"]["differ"]) > 0),
    "the places are ignored (every section sorts by its id or its key)": (
        MODEL, BY_SEQ, "      if (a.seq !== b.seq) return 0;",
        lambda r: _flipped(r) and len(set(r["model"]["stampedOrders"])) > 1 and len(r["invariance"]["differ"]) > 0),
    "a new section is given no place": (
        MODEL, PUT_STAMP, "    var body = section;",
        lambda r: r["model"]["copy"]["seqs"].get("Copy3") is None and r["model"]["reused"]["seqs"].get("Copy1") is None and r["model"]["option"]["seqs"].get("Seal") is None),
    "a new section takes the first place": (
        MODEL, PUT_STAMP, "    var body = isObject(section) && !hasSeq(section) ? Object.assign({}, section, { seq: 1 }) : section;",
        lambda r: r["model"]["copy"]["seqs"].get("Copy3") != 5 and r["model"]["copy"]["order"][-1] != "Copy3"),
    "the sections already there are not stamped before a new one is put": (
        MODEL, PUT_FIRST, "    var out = jsonCopy(model);",
        lambda r: r["model"]["oldBid"]["copy"]["order"][-1] != "Copy3" and r["model"]["oldBid"]["fresh"]["order"][-1] != "Seal"),
    "a copy takes its source's place": (
        MODEL, COPY_SEQ, "      void src;",
        lambda r: r["model"]["copy"]["seqs"]["Copy3"] != 5 and r["model"]["copy"]["copyOfCopy"]["seqs"]["Copy4"] != 6),
    "a save does not carry the order of a bid that has none": (
        MODEL, COMPOSE, "    var entries = sectionsOf(model);",
        lambda r: r["model"]["composed"].get("seqs") != {"Copy2": 1, "Epoxy": 2, "Copy1": 3}),
    "a bid is not stamped when it opens": (
        PAGE, ADOPT, "    ROOT = B.migrateModel(state.polish_estimate);",
        lambda r: r["legacy"]["opened"]["seqs"] != [1, 2, 3]),
    "a bid that opens is stamped in the wrong order": (
        MODEL, STAMP_LIST, "    out.tabs = copyInto({}, Object.fromEntries(Object.keys(tabs).reverse().map(function (id, i) {",
        lambda r: r["legacy"]["opened"]["order"] != r["legacy"]["pricedTabs"] and r["model"]["stampedOnce"]["order"] != ["Polish", "Copy2", "Epoxy", GYP, "Copy1"]),
    "a bid that is already stamped is stamped again": (
        MODEL, STAMPED_ALREADY, "    void ids;",
        lambda r: r["model"]["alreadyStampedSame"] is not True and r["model"]["stampedTwiceSame"] is not True),
    # round 7, part 2 (L5): a bid some of whose sheets say no place, and a Gyp copy that changes preset
    "a bid that says some places is left with the others unsaid": (
        MODEL, STAMPED_ALREADY, "    if (ids.some(function (id) { return hasSeq(tabs[id]); })) return model;",
        lambda r: r["partlyStamped"]["stamped"] != PARTLY_STAMPED and r["partlyStamped"]["savedSeqs"] != PARTLY_STAMPED
        and differences(r["partlyStamped"]["session"], r["partlyStamped"]["reload"]) != [] and r["model"]["priced"]["partlyStamped"]["same"] is True),
    "a Gyp copy that changes preset loses its place": (
        MODEL, COPY_PRESET, "    if (COPY_ID.test(fromTab)) return withSectionPatch(model, fromTab, { sheet: toTab, profile: profile.stamp, seq: undefined });",
        lambda r: r["gypCopyPreset"]["moved"]["seq"] is None and r["gypCopyPreset"]["session"]["order"] != r["gypCopyPreset"]["before"]["order"]),
    "a bid whose sections cannot be read is stamped": (
        MODEL, READABLE, "    void model;",
        lambda r: r["model"]["unreadable"] != {"same": True} and r["model"]["hostile"] != {"same": True, "strange": 5, "seqsUntouched": True}),
    "two sections with one place are told apart by their keys": (
        MODEL, TIE, "      return a.held - b.held;",
        lambda r: len(set(r["model"]["tieOrders"])) > 1),
    "a section with no place is older than one that has one": (
        MODEL, UNSTAMPED_LAST, "        return a.seq === null ? -1 : 1;",
        lambda r: r["model"]["mixed"]["keysAB"] != ["Polish", "Copy2", GYP, "Epoxy", "Copy1"]),
    "sections with no place are in the reverse of the order their keys are held in": (
        MODEL, UNSTAMPED_KEYS, "        if (a.seq === b.seq) return b.held - a.held;",
        lambda r: r["model"]["legacy"]["order"] != ["Polish"] + r["model"]["legacy"]["held"] and r["legacy"]["unlisted"]["opened"]["order"] != ["Polish"] + HELD),
    "a Gyp sheet that changes preset loses its place": (
        MODEL, PRESET, "    var moved = Object.assign({}, out.tabs[fromTab], { profile: profile.stamp, seq: null });",
        lambda r: [s for s in r["lifecycle"]["steps"] if s["step"].startswith("change the Gyp sheet")][0]["session"]["order"] != ["Polish", "Epoxy", GYP_FR, "Copy1", "Copy2"]),
    "a bid that merely opens saves": (
        PAGE, SAVE_ON_OPEN, "    saveSoon();",
        lambda r: r["legacy"]["quiet"] != {"armed": 0, "saves": 0, "asked": 0}),
    # round 6, O1: a bid with no places is stamped in the order its saved price was computed in (the draft's priced_tabs)
    "the page does not hand the saved list to the stamp": (
        PAGE, ADOPT, "    ROOT = B.withSectionOrder(B.migrateModel(state.polish_estimate));",
        lambda r: r["legacy"]["facts"]["prices"]["lump"] != r["legacy"]["savedLump"] and r["legacy"]["opened"]["order"] != r["legacy"]["pricedTabs"]),
    "a bid with no places is stamped in the order its keys are held in, whatever its list says": (
        MODEL, LISTED, "    var listed = tabIdsInOrder(tabs);",
        lambda r: r["model"]["priced"]["full"]["order"] != ["Polish", "Epoxy", "Copy1", "Copy2", GYP] and r["legacy"]["facts"]["prices"]["lump"] != r["legacy"]["savedLump"]),
    "a bid that already says some places is stamped by its list": (
        MODEL, LISTED, "    var listed = savedOrderOf(tabs, pricedTabs) || tabIdsInOrder(tabs);",
        lambda r: r["model"]["priced"]["partlyStamped"]["order"] != ["Polish", "Epoxy", "Copy2", GYP, "Copy1"]),
    "a list that names one sheet is taken for an order": (
        MODEL, NAMED_ENOUGH, "    if (named.length < 1) return null;",
        lambda r: r["model"]["priced"]["named1"]["order"] != KEYED and r["legacy"]["oneListed"]["opened"]["order"] != ["Polish"] + HELD),
    "the sheets a list does not name are dropped": (
        MODEL, NAMED_TAIL, "    return named;",
        lambda r: r["model"]["priced"]["named2"].get("order") != ["Polish", GYP, "Epoxy", "Copy2", "Copy1"]),
    "the sheets a list does not name go before the ones it does": (
        MODEL, NAMED_TAIL, "    return tabIdsInOrder(tabs).filter(function (id) { return named.indexOf(id) < 0; }).concat(named);",
        lambda r: r["model"]["priced"]["named2"].get("order") != ["Polish", GYP, "Epoxy", "Copy2", "Copy1"]),
    "a sheet a list names twice is taken twice": (
        MODEL, NAMED_PUSH, "      if (id !== null && has.call(tabs, id)) named.push(id);",
        lambda r: r["model"]["priced"]["junk"] != r["model"]["priced"]["named2"]),
    "a name that is a property of every object is taken for a sheet": (
        MODEL, NAMED_PUSH, "      if (id !== null && id in tabs && named.indexOf(id) < 0) named.push(id);",
        lambda r: r["model"]["priced"]["junk"] != r["model"]["priced"]["named2"]),
    # round 6, O2: a kind change, a delete and a rename made AFTER A RELOAD (a session that never reloaded has its keys in the order of the places, which hides every one of these)
    "a kind change takes the sheet's place from it": (
        MODEL, KIND, KIND.replace("{ kind: kind }", "{ kind: kind, seq: undefined }"),
        lambda r: r["afterReload"]["kind"]["session"]["order"] != AFTER_START and r["model"]["served"]["kind"] != ["Polish", "Epoxy", "Copy1", "Copy2", GYP]),
    "a kind change puts the sheet last": (
        MODEL, KIND, KIND.replace("{ kind: kind }", "{ kind: kind, seq: lastSeq(out.tabs) + 1 }"),
        lambda r: r["afterReload"]["kind"]["session"]["order"] != AFTER_START and r["model"]["served"]["kind"] != ["Polish", "Epoxy", "Copy1", "Copy2", GYP]),
    "a kind change renumbers every sheet by its key's position": (
        MODEL, KIND,
        "    out.tabs = copyInto({}, Object.fromEntries(Object.keys(out.tabs).map(function (id, i) { return [id, Object.assign({}, id === tabId ? model.tabs[tabId] : out.tabs[id], id === tabId ? { kind: kind, seq: i + 1 } : { seq: i + 1 })]; })));",
        lambda r: r["afterReload"]["kind"]["session"]["order"] != AFTER_START and r["model"]["served"]["kind"] != ["Polish", "Epoxy", "Copy1", "Copy2", GYP]),
    "a delete renumbers the sheets left by their keys' position": (
        MODEL, DELETE, "      .map(function (k, i) { return [k, Object.assign({}, out.tabs[k], { seq: i + 1 })]; })));",
        lambda r: r["afterReload"]["delete"]["session"]["order"] != AFTER_DELETED and r["model"]["served"]["delete"] != ["Polish", "Epoxy", "Copy1", GYP]),
    "a delete takes the places of the sheets left": (
        MODEL, DELETE, "      .map(function (k) { return [k, Object.assign({}, out.tabs[k], { seq: undefined })]; })));",
        lambda r: r["afterReload"]["delete"]["session"]["order"] != AFTER_DELETED and r["model"]["served"]["delete"] != ["Polish", "Epoxy", "Copy1", GYP]),
    "taking an option off renumbers the sheets left by their keys' position": (
        MODEL, REMOVE, "      .map(function (id, i) { return [id, Object.assign({}, out.tabs[id], { seq: i + 1 })]; })));",
        lambda r: r["model"]["served"]["removeOption"] != ["Polish", "Epoxy", "Copy1", GYP]),
    "a rename takes the sheet's place from it": (
        MODEL, RENAME, "    return withSectionPatch(model, id, { label: next, seq: undefined });",
        lambda r: r["afterReload"]["rename"]["session"]["order"] != AFTER_START and r["model"]["served"]["rename"] != ["Polish", "Epoxy", "Copy1", "Copy2", GYP]),
    # round 6, O3: a copy that holds its source's place stands after it
    "a copy that holds its source's place is not held behind it": (
        MODEL, WAITING, "      return false;",
        lambda r: r["model"]["sourceTie"]["pair"] != PAIR_ORDER and r["model"]["sourceTie"]["deepChain"] != PAIR_ORDER and r["staleCopy"]["opened"]["order"] != ["Polish", "Epoxy", "Copy1", GYP]),
    "a section that names itself as its source waits for itself": (
        MODEL, WAITING, '      return typeof s === "string" && left.some(function (r) { return r.id === s; });',
        lambda r: r["model"]["sourceTie"]["junkSource"] != [PAIR_ORDER] * 6),
    "a loop of sources puts the last by id first": (
        MODEL, PICK, "      var pick = -1;",
        lambda r: r["model"]["sourceTie"]["loop"] != LOOP_ORDER),
    "sections that say no place are held behind their sources too": (
        MODEL, RUNS, "      while (j < rows.length && rows[j].seq === rows[i].seq) j++;",
        lambda r: r["model"]["legacy"]["order"] != ["Polish"] + r["model"]["legacy"]["held"] and r["legacy"]["unlisted"]["opened"]["order"] != ["Polish"] + HELD),
    "a rename renumbers every sheet by its key's position": (
        MODEL, RENAME,
        "    var renamed = withSectionPatch(model, id, { label: next }); if (isObject(renamed.tabs)) renamed.tabs = copyInto({}, Object.fromEntries(Object.keys(renamed.tabs).map(function (k, i) { return [k, Object.assign({}, renamed.tabs[k], { seq: i + 1 })]; }))); return renamed;",
        lambda r: r["afterReload"]["rename"]["session"]["order"] != AFTER_START and r["model"]["served"]["rename"] != ["Polish", "Epoxy", "Copy1", "Copy2", GYP]),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_the_order_checks_go_red_when_the_line_that_keeps_the_order_is_broken(tmp_path, name):
    """The break must be SEEN: a fact the harness reads changes (a section that crashed is not a fact noticing: a break that stopped the page has nothing to compare)."""
    require_node()
    rel, old, new, noticed = MUTATIONS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, PAGE_FILES)
    got = run(frontend)
    crashed = sorted(k for k in SECTIONS if "error" in got.get(k, {}))
    assert not crashed, "the break crashed the harness instead of changing a fact: %s\n%s" % (name, "; ".join("%s: %s" % (k, got[k]["error"][:400]) for k in crashed))
    assert noticed(got), "the checks did not notice: %s" % name


def test_the_break_checks_are_quiet_on_the_unbroken_tree(ran):
    """A check that is already true of the real tree would 'notice' any break. Every one of them is false here."""
    loud = sorted(name for name, (_rel, _old, _new, noticed) in MUTATIONS.items() if noticed(ran))
    assert loud == [], "these checks fire on the unbroken tree, so they prove nothing: %s" % loud
