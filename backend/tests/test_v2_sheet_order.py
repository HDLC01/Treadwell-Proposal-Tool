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
then the sections by `seq`, whatever order their keys are in. A bid saved before the order was kept has no `seq` and keeps the order it opens with (its keys' order), which is stamped
when it opens and saved by its next save; nothing is written on open and no price moves.

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
SECTIONS = ["comboCopyBase", "epoxyAddPolish", "stripOrder", "documentOrder", "lifecycle", "legacy", "model"]
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


def test_a_rename_moves_nothing(ran):
    before = [s for s in ran["lifecycle"]["steps"] if s["step"] == "copy Polish (Copy2)"][0]
    after = [s for s in ran["lifecycle"]["steps"] if s["step"] == "rename Copy1"][0]
    assert after["session"]["order"] == before["session"]["order"] and after["reload"]["order"] == before["session"]["order"]


# ── a bid saved before the order was kept ────────────────────────────────────────────────────
def test_a_legacy_bid_opens_in_the_order_its_keys_are_held_in(ran):
    got = ran["legacy"]
    assert got["keyOrder"] == ["Copy1", "Copy2", "Epoxy"], got["keyOrder"]
    assert got["opened"]["order"] == ["Polish"] + got["keyOrder"], got["opened"]


def test_a_legacy_bid_stamps_its_order_when_it_opens_and_writes_nothing(ran):
    got = ran["legacy"]
    assert got["quiet"] == {"armed": 0, "saves": 0, "asked": 0}, got["quiet"]
    assert got["opened"]["seqs"] == [1, 2, 3], got["opened"]


def test_stamping_the_order_changes_no_price(ran):
    """The same bid with its keys' order written down by hand as 1, 2, 3 prices, lists and carries exactly what the unstamped one does."""
    got = ran["legacy"]
    assert differences(got["facts"], got["byHand"]) == []


def test_the_next_save_of_a_legacy_bid_keeps_the_order_it_opened_with(ran):
    got = ran["legacy"]
    assert got["savedSeqs"] == [["Copy1", 1], ["Copy2", 2], ["Epoxy", 3]], got["savedSeqs"]
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
STAMP_LIST = "    out.tabs = copyInto({}, Object.fromEntries(tabIdsInOrder(tabs).map(function (id, i) {"
STAMPED_ALREADY = "    if (ids.every(function (id) { return hasSeq(tabs[id]); })) return model;       // (and a bid with no sections at all)"
READABLE = "    if (readableSections(model) === null) return model;"
TIE = "      return a.id < b.id ? -1 : (a.id > b.id ? 1 : 0);    // one place claimed twice: by the id, which survives a reload"
UNSTAMPED_LAST = "        return a.seq === null ? 1 : -1;                   // one that says none is newer than one that does"
UNSTAMPED_KEYS = "        if (a.seq === b.seq) return a.held - b.held;      // neither says its place: the order the keys are held in"
BY_SEQ = "      if (a.seq !== b.seq) return a.seq - b.seq;"
PRESET = "    var moved = Object.assign({}, out.tabs[fromTab], { profile: profile.stamp });"
ADOPT = "    ROOT = B.withSectionOrder(B.migrateModel(state.polish_estimate));"
SAVE_ON_OPEN = "    if (restructured) saveSoon();"
HELD = ["Copy1", "Copy2", "Epoxy"]

# name -> (file, old, new, what the harness must report for the break to have been seen)
MUTATIONS = {
    "sectionsOf lists the sections in the order their keys are held in": (
        MODEL, SECTIONS_OF, "    Object.keys(tabs).forEach(function (id) {",
        lambda r: _flipped(r) and len(set(r["model"]["stampedOrders"])) > 1),
    "the places are ignored (every section sorts by its id or its key)": (
        MODEL, BY_SEQ, "      if (a.seq !== b.seq) return 0;",
        lambda r: _flipped(r) and len(set(r["model"]["stampedOrders"])) > 1),
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
        lambda r: r["legacy"]["opened"]["order"] != ["Polish"] + HELD and r["model"]["stampedOnce"]["order"] != ["Polish", "Copy2", "Epoxy", GYP, "Copy1"]),
    "a bid that is already stamped is stamped again": (
        MODEL, STAMPED_ALREADY, "    void ids;",
        lambda r: r["model"]["alreadyStampedSame"] is not True and r["model"]["stampedTwiceSame"] is not True),
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
        lambda r: r["model"]["legacy"]["order"] != ["Polish"] + r["model"]["legacy"]["held"] and r["legacy"]["opened"]["order"] != ["Polish"] + HELD),
    "a Gyp sheet that changes preset loses its place": (
        MODEL, PRESET, "    var moved = Object.assign({}, out.tabs[fromTab], { profile: profile.stamp, seq: null });",
        lambda r: [s for s in r["lifecycle"]["steps"] if s["step"].startswith("change the Gyp sheet")][0]["session"]["order"] != ["Polish", "Epoxy", GYP_FR, "Copy1", "Copy2"]),
    "a bid that merely opens saves": (
        PAGE, SAVE_ON_OPEN, "    saveSoon();",
        lambda r: r["legacy"]["quiet"] != {"armed": 0, "saves": 0, "asked": 0}),
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
