"""Sheets phase 1 of the v2 estimating program: a bid is made of SHEETS, any sheet can be copied, a fresh one can be added, and
everything follows the BASE bid.

THIS PHASE IS THE MODEL ONLY (frontend/js/bid-model.js), plus the few lines the estimate page needs so that nothing it does today
changes. There is no new screen. What the model does now:

  * IDENTITY. A section's key is its workbook sheet ("Epoxy", "Seal (+Jnts)", the form every saved bid uses) or a `Copy<N>` id that
    names its sheet in `sheet`, with a `label` (what it is called) and a `source` (what it was copied from). The root stays the
    Polish section, and its `kind` may now be base, option or off (a missing key is base). Code that means the workbook sheet
    reads `entry.sheet`; the label is never a key.
  * `polishBid(model, tabId, ctx)` prices ANY Polish section as the root is priced, so a copy of the Polish sheet, or a Polish
    sheet added to the bid, is exactly the root's price. The page's bid() is a call to it for the root.
  * `copySection`, `addSheet`, `renameSection`, `deleteSection`, `pickBase` and `baseOf`: pure functions that answer a new model
    (and a `patch` for what the draft keeps around the model).
  * the job's travel goes by ROLE: the carrier (the first base) takes the job's Lodging and Per Diem, an option its own for its
    own crew, any other base none.
  * `sectionsForJob` is base-aware, and `composePricingSnapshot` also writes `base_tab_id` and names each tab by its label.

EVERYTHING RUNS CODE. tests/js/sheets-model-harness.js executes the real model and engine and the real estimate page and prints
one line of JSON. The last tests break a scratch copy of the code in many ways and require each fact to notice;
`break_source` refuses an anchor that is not in the file exactly once. What did not move is held by tests that already exist:
test_polish_chain_golden.py (the chain's 2,247 vectors), test_v2_multi_section.py (save_patch_golden.json, byte for byte, over
every saved-bid fixture and seven new bids) and test_polish_saved_bid_safety.py (every saved bid opens to the same total and
writes nothing).
"""
import json
import pathlib

import pytest

from _golden_support import break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
FRONTEND = TESTS.parents[1] / "frontend"
HARNESS = TESTS / "js" / "sheets-model-harness.js"
MODEL = "js/bid-model.js"
PAGE = "js/polish-estimate.js"

SCRATCH_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js",
                 "js/bid-profiles.js", "js/markup-core.js", "js/library-core.js", "js/library-picker.js",
                 "js/work-types.js", "js/excel-math.js", "js/epoxy-takeoff.js", "js/gyp-takeoff.js", "js/seal-takeoff.js"]

REV2 = "polish-rev2@1"
LEGACY = "polish-legacy@1"
OFF_THE_PROPOSAL = {"show_system": True, "show_diff": False, "is_option": False, "show": True, "price_mode": "total"}
ON_THE_PROPOSAL = dict(OFF_THE_PROPOSAL, is_option=True)


def _run(frontend=FRONTEND):
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    require_node()
    return _run()


SECTIONS = ["identity", "copies", "polishCopies", "baseBid", "combinedBase", "refusals", "idReuse", "baseOfCases", "renaming",
            "presets", "adding", "jobTypes", "snapshots", "page"]


@pytest.mark.parametrize("section", SECTIONS)
def test_no_section_of_the_harness_failed(ran, section):
    """A section that threw reports it instead of crashing, so running this over a tree without the functions fails an
    assertion with a reason."""
    assert "error" not in ran[section], ran[section].get("error")


# ── 1. identity ──────────────────────────────────────────────────────────────────────────────────
def test_the_roots_kind_is_read_in_full_and_a_missing_one_is_a_base(ran):
    assert ran["identity"]["rootKinds"] == {"missing": "base", "base": "base", "option": "option", "off": "off", "junk": "base"}
    r = ran["identity"]["root"]
    assert (r["tab"], r["sheet"], r["label"], r["source"], r["root"]) == ("Polish", "Polish", "Polish", None, True)


def test_a_section_filed_under_its_sheets_name_reads_exactly_as_it_always_did(ran):
    """Saved bids never carried a sheet, a label or a source. Their entries say the sheet is the key and the label is the
    key too, so the names that appear on screen and on the proposal do not move."""
    assert ran["identity"]["oldShapes"] == [
        ["Polish", "Polish", "Polish", "base", "polish", None],
        ["Seal (+Jnts)", "Seal (+Jnts)", "Seal (+Jnts)", "option", "seal", None],
        ["Epoxy", "Epoxy", "Epoxy", "base", "epoxy", None]]
    assert ran["snapshots"]["oldBid"]["entries"] == [
        ["Polish", "Polish", "Polish", "base", "polish", None], ["Seal", "Seal", "Seal", "option", "seal", None],
        ["Epoxy", "Epoxy", "Epoxy", "base", "epoxy", None]]


def test_a_copy_is_keyed_Copy_N_and_names_its_sheet_its_label_and_its_source(ran):
    i = ran["identity"]
    assert i["copyEntry"] == {"tab": "Copy1", "sheet": "Epoxy", "label": "Epoxy copy", "source": "Epoxy", "layout": "epoxy",
                              "kind": "option", "role": "epoxy", "profile": "epoxy@1"}
    assert i["copyEntries"][2] == ["Copy1", "Epoxy", "Epoxy copy", "option", "epoxy", "Epoxy"]
    assert i["copyIsByReference"] == 41, "a write through an entry is a write to the model"
    assert i["labelNeedsText"] == "Copy1" and i["blankLabel"] == "Copy1", "a label that is not text is not read, the id stands in"


def test_a_section_that_does_not_say_what_it_is_is_refused_and_never_guessed(ran):
    t = ran["identity"]["throws"]
    assert "does not name a priced workbook sheet" in t["copyWithoutSheet"] and "does not name a priced workbook sheet" in t["copyOfUnknownSheet"]
    assert "says layout" in t["copyWithWrongLayout"], "a copy of an Epoxy sheet that says it is Polish is refused"
    assert "says it is the sheet" in t["sheetKeyWithOtherSheet"]
    for key in ("copyZero", "copyLowerCase", "copyWords"):
        assert "is not a priced workbook tab" in t[key], key
    assert "root section's own tab" in t["polishUnderTabs"]


# ── 2. a copy prices exactly like the sheet it came from ─────────────────────────────────────────
@pytest.mark.parametrize("which", ["legacy", "rev2"])
def test_a_copy_of_the_polish_sheet_prices_exactly_like_the_root_and_keeps_its_stamps(ran, which):
    c = ran["copies"][which]
    assert c["id"] == "Copy1" and c["kind"] == "option" and c["source"] == "Polish" and c["totalsStart"] == {}
    assert c["sameKeys"] is True and c["total"][0] == c["total"][1], "every figure of the chain, tooling included"
    assert c["viaPriceSection"] is True, "priceSection hands a Polish section under tabs to polishBid"
    assert c["rootUntouched"] is True and c["inputUntouched"] is True
    if which == "rev2":
        assert c["profile"] == REV2 and c["poolPacks"] is True
        assert c["hasTooling"] == [True, True] and c["tooling"][0] == c["tooling"][1] > 0
    else:
        assert c["profile"] == LEGACY and c["hasPoolKey"] is False, "a bid saved before rev 2 and the pool keeps neither in its copy"
        assert c["hasTooling"] == [False, False]


def test_a_copy_is_an_option_so_it_carries_its_own_travel_and_made_the_base_it_prices_like_its_source(ran):
    """The job's Lodging and Per Diem belong to the carrier only. A copy starts as an option, so on a job 70 miles out it is
    charged its own for its own crew (15 man-days at $100), where the source is charged the job's ten typed nights ($1,000).
    Made the base it carries the job's travel, and then every figure equals the source's."""
    for which in ("legacy", "rev2"):
        c = ran["copies"][which]
        assert c["farSource"] == 1000 and c["farAsOption"] == 1500, which
        assert c["farAsBase"] is True, which


def test_a_copy_keeps_everything_a_section_holds_and_stamps_it_never_had_stay_off(ran):
    assert ran["copies"]["frozenThrew"] is None, "a copy is made without touching the model it was handed"
    assert ran["copies"]["savedBeforeStamps"] == {"hasPool": False, "profile": LEGACY, "rootHasProfile": False}
    e = ran["copies"]["epoxy"]
    assert e["sameKeys"] is True and e["total"][0] == e["total"][1]
    assert e["profile"] == ["epoxy@1", "epoxy@1"] and e["pool"] == [True, True]
    assert e["rates"] is True and e["ratesAreOwn"] is True, "the rates snapshot it kept, as its own copy"
    assert e["rows"] is True and e["sheet"] == "Epoxy" and e["role"] == "epoxy" and e["label"] == "Epoxy copy" and e["kind"] == "option"
    assert e["noPoolOnSource"] is False, "a section that was not stamped for the pool is copied without the stamp"
    assert e["farAsOption"] == [0, 1200] and e["ownTravel"] == 1200, "an Epoxy base takes no travel, its option copy takes its own"
    assert e["chain"] == ["Copy2", "Epoxy copy copy", "Copy1"], "a copy of a copy is the next id and says what it came from"
    assert e["offSource"] == "option", "a sheet that is off can be copied, and the copy is an option"


def test_a_copy_starts_off_the_proposal_and_the_save_keeps_it_so(ran):
    p = ran["copies"]["proposal"]
    assert p["patchTabOpts"]["Copy1"] == OFF_THE_PROPOSAL and p["kept"] is True, "the draft's other entries ride along in the patch"
    assert p["snapshotEntry"] == OFF_THE_PROPOSAL and p["snapshotKeepsOther"] == {"is_option": True}
    assert p["noPatchDefault"] == ON_THE_PROPOSAL, "with no entry at all an option is what composePricingSnapshot has always written"
    assert p["inLump"] is True
    assert p["pricedAs"] == [["Polish", "Polish", "base", "polish"], ["Copy1", "Polish copy", "option", "polish"]]


def test_a_bid_holds_twelve_copies_and_an_id_that_was_freed_is_handed_out_again(ran):
    lim = ran["copies"]["limit"]
    assert lim["max"] == 12 and lim["first"] == "Copy1" and lim["last"] == "Copy12"
    assert "12 copied sheets" in lim["over"] and "12 copied sheets" in lim["addOver"]
    assert lim["addOwnKey"] == "Seal", "a sheet filed under its own name does not count against the limit"
    assert lim["reused"] == "Copy5"


# ── 3. a Polish section under tabs prices exactly like the root ──────────────────────────────────
@pytest.mark.parametrize("which", ["legacy", "rev2"])
def test_polishBid_prices_the_root_as_the_page_always_did_and_a_copy_as_the_root(ran, which):
    """The root's polishBid equals markupChain over the model's own rows with the inputs bid() has always used (dye, a typed
    remodel rate, contingency, fees, the sheet's tooling on rev 2), and a copy under tabs equals it key for key."""
    p = ran["polishCopies"][which]
    assert p["rootIsTheOldBid"] is True and p["copyIsTheRoot"] is True
    assert ((p["tooling"] or 0) > 0) == (which == "rev2") and (p["tooling"] is None) == (which == "legacy")


def test_a_polish_sheet_added_to_the_bid_is_a_rev2_section_priced_as_a_rev2_root(ran):
    a = ran["polishCopies"]["added"]
    assert a["profile"] == REV2 and a["pool"] is True and a["hasRates"] is False and a["sameAsRev2Root"] is True


def test_a_rev2_copy_that_carries_the_jobs_travel_counts_nights_the_sheets_way_and_a_legacy_one_counts_man_days(ran):
    """Rev 2 counts the nights from the labor dollars, so a row paid more than the first crew row reads as extra days: 25
    nights here where the people are 20 man-days. The section carries the profile it was made with, wherever it is filed."""
    n = ran["polishCopies"]["nights"]
    assert n["rev2Root"] == n["rev2CopyAsCarrier"] == 2500 and n["legacyRoot"] == n["legacyCopyAsCarrier"] == 2000
    assert n["optsOnCopy"] == [True, False, False], "travelOpts follows a section's own stamp, and says nothing for a section it does not hold"


def test_polishBid_refuses_what_it_cannot_price_in_words_and_never_reprices(ran):
    e = ran["polishCopies"]["errors"]
    assert "ctx.material" in e["noMaterial"] and "ctx.material" in e["noCtx"] and "needs the model" in e["noModel"]
    assert "polishBid prices Polish sections" in e["epoxy"] and "no section" in e["unknownTab"]
    assert e["unknownStamp"] == {"priceable": False, "total": None, "line": "profile"}
    assert e["movedRev"] == {"priceable": False, "total": None}


def test_the_root_of_a_bid_whose_sections_cannot_be_read_is_still_priced_and_an_off_root_still_answers_travel(ran):
    u = ran["polishCopies"]["unreadableTabs"]
    assert u["root"] == u["plain"], "the page opens such a bid as it is and saves what was typed"
    assert "does not say its layout" in u["epoxyThrows"]
    o = ran["polishCopies"]["offRoot"]
    assert o["travel"] == o["plain"] == 1000, "bid() has always charged an off root the job's travel, and nothing reads it"


def test_the_page_prices_a_copy_of_the_polish_sheet_as_the_root_dye_included_and_says_its_name(ran):
    p = ran["page"]
    c = p["copyOnPage"]
    assert c["tabs"] == ["Copy1"] and c["same"] is True and c["copyTotal"] == c["rootTotal"] > 0
    assert p["materialOnShow"]["copy"] == p["materialRoot"] > 0
    assert p["materialOnShow"]["activeBid"] == c["rootTotal"]
    s = p["saved"]
    assert s["tabs"] == [["Polish", "Polish", "base", "polish", True], ["Copy1", "Polish copy", "option", "polish", True]]
    assert s["baseTabId"] == "Polish" and s["tabOpts"] == {"Copy1": OFF_THE_PROPOSAL}, "the draft's own entry is kept"
    assert s["lump"] == s["rootTotal"], "a copy is never in the lump sum"
    r = p["renamedOnPage"]
    assert "Garage floor (option)" in r["strip"] and "Garage floor" in r["maths"]


def test_the_page_charges_a_root_that_is_an_option_its_own_travel_and_the_base_the_jobs(ran):
    r = ran["page"]["rootAsOption"]
    assert r["opensOn"] == "Copy1" and r["rootKind"] == "option"
    assert r["copyTravel"] == 1000 and r["rootTravel"] == r["ownByHand"] == 1650


def test_the_page_prices_a_gyp_section_that_is_a_copy_by_its_sheet_and_not_its_key(ran):
    g = ran["page"]["gypCopyOnPage"]
    assert g["tabs"] == ['Gyp (USG 1-8")', "Copy1"] and g["priceable"] == [True, True]
    assert g["totals"][0] == g["totals"][1] > 0 and g["jobType"] == "gyp"


# ── 4. everything follows the base ───────────────────────────────────────────────────────────────
def test_picking_another_base_moves_the_lump_sum_and_the_travel(ran):
    """A Polish base with an Epoxy option, on a job 70 miles out with ten nights typed at $100. The Polish root carries the
    job's $1,000. Epoxy made the base takes it over, the lump sum becomes Epoxy's own total, and the Polish root, now an option,
    is charged its own Lodging for its own 15 man-days ($1,500)."""
    b = ran["baseBid"]
    assert b["before"]["base"] == {"ids": ["Polish"], "jobType": "polish"} and b["before"]["carrier"] == "Polish"
    assert b["before"]["lump"] == b["before"]["polishTotal"] and b["before"]["polishTravel"] == 1000
    assert b["before"]["epoxyAsOptionTravel"] == 1200
    a = b["after"]
    assert a["base"] == {"ids": ["Epoxy"], "jobType": "epoxy"} and a["carrier"] == "Epoxy" and a["baseTabId"] == "Epoxy"
    assert a["epoxyTravel"] == b["jobTravel"] == 1000, "the job's own Lodging, once"
    assert a["polishAsOptionTravel"] == b["ownTravel"]["polishOption"] == b["ownTravel"]["hand"] == 1500
    assert a["lump"] == a["epoxyTotal"] != b["before"]["lump"] and b["snapshotMoves"] == {"epoxyIsTheLump": True, "polishNoLongerInLump": True}
    assert a["kinds"] == [["Polish", "option"], ["Epoxy", "base"]] and a["rootKindKey"] == "option"
    assert b["pricedTabs"] == [["Polish", "option"], ["Epoxy", "base"]]


def test_the_travel_labor_row_follows_the_carrier_and_comes_back_with_it(ran):
    b = ran["baseBid"]
    assert b["travelLaborRow"] == {"polishBefore": ["polishing", "travel"], "epoxyBefore": ["installing"],
                                   "polishAfter": ["polishing"], "epoxyAfter": ["installing", "travel"]}
    back = b["backAgain"]
    assert back["base"] == {"ids": ["Polish"], "jobType": "polish"} and back["rowsBack"] == ["polishing", "travel"] and back["epoxyRows"] == ["installing"]
    assert back["polishTotal"] == b["before"]["polishTotal"] and back["polishTravel"] == 1000
    assert back["sameAsStart"] is True, "picking the base and picking it back leaves the model exactly as it was"


def test_the_prior_base_becomes_an_option_that_is_on_the_proposal_as_a_total_and_keeps_its_words(ran):
    b = ran["baseBid"]
    assert b["patch"]["work_type"] == "epoxy" and b["patch"]["base_tab_id"] == "Epoxy"
    assert b["patch"]["tab_opts"]["Polish"] == dict(ON_THE_PROPOSAL, desc="keep me"), \
        "on, shown, a total, whatever the entry said before, and the words typed on it stay"
    assert b["otherKept"] is True
    back = b["backAgain"]["patch"]
    assert back["work_type"] == "polish" and back["base_tab_id"] == "Polish"
    assert back["tab_opts"]["Polish"]["is_option"] is False, "the new base is not also an option"
    assert back["tab_opts"]["Epoxy"] == ON_THE_PROPOSAL


def test_picking_the_base_it_already_has_changes_nothing_and_a_pick_never_touches_what_it_was_handed(ran):
    b = ran["baseBid"]
    assert b["samePick"] == {"sameModel": True, "patch": {"work_type": "polish", "base_tab_id": "Polish"}}
    assert b["inputUntouched"] is True and b["frozenThrew"] is None


def test_the_combined_epoxy_and_polish_base_is_the_sum_of_both_and_names_no_one_sheet(ran):
    c = ran["combinedBase"]
    assert c["base"] == {"ids": ["Polish", "Epoxy"], "jobType": "combo"}
    assert c["patch"] == {"work_type": "combo", "base_tab_id": None} and c["baseTabId"] is None
    assert c["lump"] == c["sumOfBoth"] == c["handSum"], "each sheet's total after its own gross profit, added"
    assert c["kinds"] == [["Polish", "base"], ["Epoxy", "base"]] and c["carrier"] == "Polish"
    assert c["areas"] == {"polish_sf": 10000, "epoxy_sf": 4000, "cove_lf": 300}
    assert c["polishTravel"] == 1000 and c["epoxyTravelAsBase"] == 0 and c["epoxyTravelAsOption"] == 1200, \
        "the job's travel once, on the carrier: the other base takes none, an option its own"
    assert c["otherOrder"] == {"sameModel": True, "patch": {"work_type": "combo", "base_tab_id": None}}
    e = c["fromCombinedToEpoxy"]
    assert e["base"] == {"ids": ["Epoxy"], "jobType": "epoxy"} and e["kinds"] == [["Polish", "option"], ["Epoxy", "base"]]
    assert e["rows"] == [["polishing"], ["installing", "travel"]]
    assert e["patch"]["tab_opts"] == {"Polish": ON_THE_PROPOSAL}, "only the half that stopped being a base is demoted"
    assert "one Epoxy sheet and one Polish sheet" in c["twoPolish"]


def test_only_a_priced_sheet_can_be_the_base_and_the_base_is_never_deleted(ran):
    r = ran["refusals"]
    assert "never the base" in r["sealBase"] and "never the base" in r["sealInPair"] and "never the base" in r["levelingBase"]
    for key in ("twoPolish", "polishAndGyp"):
        assert "one Epoxy sheet and one Polish sheet" in r[key], key
    for key in ("three", "none", "sameTwice"):
        assert "one sheet, or one Epoxy sheet and one Polish sheet" in r[key], key
    assert "no section" in r["unknown"] and "no section" in r["unknownInPair"] and "needs the model" in r["noModel"]
    assert r["asString"] == "Epoxy" and r["gypBase"] == [{"ids": ['Gyp (USG 1-8")'], "jobType": "gyp"}, "gyp", 'Gyp (USG 1-8")']
    assert r["stillTheSame"] is True, "a refused pick changes nothing"
    assert "Pick another base bid" in r["deleteBase"] and "Pick another base bid" in r["deleteCombinedHalf"]
    assert "cannot be deleted" in r["deleteRoot"] and "cannot be deleted" in r["deleteRootAsOption"]
    assert "no section" in r["deleteUnknown"]


def test_the_sheets_a_bid_can_take_are_the_ready_ones_and_leveling_is_not_one(ran):
    r = ran["refusals"]
    assert r["sheetsOffered"] == ["Polish", "Seal", "Seal (+Jnts)", "Epoxy", 'Gyp (USG 1-8")', "Gyp (USG N12ULTRA)",
                                  'Gyp (USG N25 1-4")', "Gyp (GWorx SC190)", "Gyp (FR)"]
    for key in ("addLeveling", "addEpoxyBlank", "addNothing"):
        assert "cannot be added to a bid" in r[key], key


def test_baseOf_says_which_sections_are_the_base_and_what_job_type_that_amounts_to(ran):
    b = ran["baseOfCases"]
    assert b["rootOnly"] == {"ids": ["Polish"], "jobType": "polish"}
    assert b["epoxyJob"] == {"ids": ["Epoxy"], "jobType": "epoxy"}, "an Epoxy job holds an off Polish root"
    assert b["combo"] == {"ids": ["Polish", "Epoxy"], "jobType": "combo"}
    assert b["gypJob"] == {"ids": ['Gyp (USG 1-8")'], "jobType": "gyp"}
    assert b["polishAndGyp"] == {"ids": ["Polish", 'Gyp (USG 1-8")'], "jobType": None}, "two bases that are not Epoxy and Polish are no job type"
    assert b["noBase"] == {"ids": [], "jobType": None}
    assert b["sealDeclared"] == {"ids": ["Polish"], "jobType": "polish"}, "an option-only tab that a saved model calls a base is not one"
    assert b["copyBase"] == {"ids": ["Copy1"], "jobType": "polish"}, "a copy made the base is the base"
    assert b["rootOption"] == {"ids": ["Epoxy"], "jobType": "epoxy"}
    assert b["twoEpoxy"] == {"ids": ["Epoxy", "Copy1"], "jobType": None}
    assert "layout" in b["unreadable"] and "needs the model" in b["noModel"]


# ── 5. what a deleted sheet leaves behind ────────────────────────────────────────────────────────
def test_a_deleted_sheet_leaves_nothing_on_the_draft_so_the_id_it_frees_starts_clean(ran):
    """A Copy id is handed out again, so anything the draft kept under it (its proposal settings, its notes, the words typed over
    its line and the lines typed around it, the bullets set on them) would print on the next sheet to take the id."""
    r = ran["idReuse"]
    assert r["firstId"] == "Copy1" and r["tabsAfterDelete"] == [] and r["tabsIsObject"] is True
    assert r["patchKeys"] == ["price_overrides", "tab_notes", "tab_opts"]
    assert r["nothingLeft"] is True and r["otherKept"] is True, "another sheet's words are not touched"
    assert r["secondId"] == "Copy1"
    f = r["freshAgain"]
    assert f["entry"] == OFF_THE_PROPOSAL and f["desc"] is False and f["notes"] is False and f["words"] is True


def test_a_new_copy_forgets_what_an_old_draft_still_kept_under_its_id(ran):
    """The delete may have been missed (an older draft, a crash). The next copy scrubs the id itself, so it never inherits."""
    s = ran["idReuse"]["staleScrubbed"]
    assert s == {"entry": OFF_THE_PROPOSAL, "notes": False, "words": True, "otherKept": True}


def test_a_sheet_filed_under_its_own_name_is_forgotten_the_same_way(ran):
    r = ran["idReuse"]
    assert r["sealGone"] == {"left": None, "tabs": []} and r["sealAgain"] == ON_THE_PROPOSAL


def test_the_smallest_free_id_is_the_next_one_and_the_input_is_untouched(ran):
    o = ran["idReuse"]["order"]
    assert o["ids"] == ["Copy1", "Copy2", "Copy3"] and o["next"] == "Copy2" and o["tabs"] == ["Copy1", "Copy3", "Copy2"]
    assert ran["idReuse"]["inputUntouched"] is True


# ── 6. rename ────────────────────────────────────────────────────────────────────────────────────
def test_a_rename_changes_the_label_and_never_the_id_and_the_proposal_gets_the_label(ran):
    r = ran["renaming"]
    assert r["id"] == ["Epoxy", "Copy1"] and r["label"] == "Garage floor" and r["stored"] == "Garage floor" and r["sheetStays"] == "Epoxy"
    assert r["byLabel"] == [["Polish", "Polish"], ["Epoxy", "Epoxy"], ["Copy1", "Garage floor"]]
    assert r["rootRenamed"] == {"label": "Main floor", "key": "Main floor", "pricedName": [["Polish", "Main floor"], ["Epoxy", "Epoxy"]]}
    assert r["sheetRenamed"] == {"keys": ["Epoxy"], "label": "Warehouse", "name": [["Polish", "Polish"], ["Epoxy", "Warehouse"]]}, \
        "a sheet filed under its own name is renamed without moving its key"
    assert r["sameLabel"] is True and r["inputUntouched"] is True


def test_a_name_has_31_characters_at_most_none_of_the_bad_ones_and_is_not_another_sheets(ran):
    a = ran["renaming"]["all"]
    assert a["empty"] == a["blank"] == a["nothing"] == "Enter a sheet name."
    assert "31 characters" in a["long32"] and a["long31"] is None
    for key in ("dupRoot", "dupSheet", "dupOther"):
        assert "is already the name of a sheet" in a[key], key
    assert a["own"] is None and a["ownCase"] is None and a["free"] is None, "a sheet may keep its own name, in any case"
    bad = [k for k in a if k.startswith("char ")]
    assert len(bad) == 9
    for key in bad:
        assert "cannot have any of these" in a[key], key
    r = ran["renaming"]["refused"]
    assert r["empty"] == "Enter a sheet name." and "already the name" in r["dup"] and "31 characters" in r["long"]
    assert "no section" in r["unknown"] and "cannot have any of these" in r["char"]


def test_the_words_a_name_may_not_be_are_plain_and_a_label_is_never_a_key(ran):
    r = ran["renaming"]
    assert r["messageHasEmDash"] is False and r["messageCount"] == 16
    assert set(r["sneaky"]) == {"__proto__", "constructor", "hasOwnProperty", "prototype", "toString"}
    for word, got in r["sneaky"].items():
        assert got == {"keys": ["Epoxy", "Copy1"], "label": word, "protoClean": True}, word
    assert r["copyLabels"] == ["Polish", "Polish copy", "Polish copy 2", "Polish copy 3"]
    assert r["longCopyLabel"] == [31, 31, " 3"], "a copy's name is made free and cut to 31 characters with room for its number"


# ── 7. a Gyp copy's preset ───────────────────────────────────────────────────────────────────────
def test_changing_the_preset_of_a_gyp_copy_rewrites_its_sheet_and_keeps_its_key(ran):
    p = ran["presets"]
    assert p["named"] == {"keys": ["Gyp (FR)"], "profile": "gyp@1", "sheet": "Gyp (FR)"}, "a section filed under its sheet's name is re-filed"
    c = p["copy"]
    assert c["keys"] == ['Gyp (USG 1-8")', "Copy1"] and c["sheet"] == c["entrySheet"] == "Gyp (FR)" and c["kind"] == "option"
    assert c["label"] == 'Gyp (USG 1-8") copy' and c["profile"] == "gyp@1" and c["rows"] == 1 and c["sourceUntouched"] is True
    assert p["sameSheetIsTheModel"] is True and p["noSectionKeepsItsOldSheetsName"] is True
    r = p["refused"]
    assert "is not another sheet of the gyp tab" in r["notAGypSheet"] and "no section" in r["unknown"]
    assert "root of the model" in r["root"] and "already a section of this bid" in r["heldSheet"]
    assert p["priceOnCopy"] == [True, True]
    assert p["truckload"][0] == 448 and p["truckload"][1][0] != p["truckload"][1][1], \
        "the copy is priced on its own sheet's truckload, not on a sheet its key names"


# ── 8. adding a fresh sheet ──────────────────────────────────────────────────────────────────────
def test_every_sheet_a_bid_can_take_is_added_as_an_option_that_starts_on_the_proposal(ran):
    a = ran["adding"]
    assert a["offered"] == ran["refusals"]["sheetsOffered"] and a["inputUntouched"] is True
    assert set(a["sheets"]) == set(a["offered"])
    for sheet, s in a["sheets"].items():
        assert s["kind"] == "option" and s["patch"] == ON_THE_PROPOSAL and s["keptOther"] is True, sheet
        assert s["pool"] is True, sheet + ": a new section buys each material once for the whole section"
        assert s["rootUntouched"] is True, sheet + ": nothing the estimator typed in the root is reseeded"
        assert s["takeoff"] == [8000], sheet + ": the area handed in under the sheet's name"
    p = a["sheets"]["Polish"]
    assert p["id"] == "Copy1" and p["profile"] == REV2 and p["hasSheet"] == "Polish" and p["hasLabel"] == "Polish 2" and p["hasRates"] is False
    assert p["layout"] == "polish" and p["role"] == "polish" and p["entryLabel"] == "Polish 2"
    assert "lab-po" in p["labor"] and "lab-ep" not in p["labor"], "a Polish sheet is crewed from the Polish defaults"
    e = a["sheets"]["Epoxy"]
    assert e["id"] == "Epoxy" and e["ownKey"] is True and e["profile"] == "epoxy@1" and e["hasSheet"] is None and e["hasLabel"] is None
    assert e["labor"] == ["lab-ep"], "an Epoxy sheet is crewed from the Epoxy defaults, and the job's Travel stays with the carrier"
    for sheet in ("Seal", "Seal (+Jnts)"):
        assert a["sheets"][sheet]["profile"] == "seal@1" and a["sheets"][sheet]["ownKey"] is True and a["sheets"][sheet]["hasRates"] is True
    for sheet in ('Gyp (USG 1-8")', "Gyp (USG N12ULTRA)", 'Gyp (USG N25 1-4")', "Gyp (GWorx SC190)", "Gyp (FR)"):
        assert a["sheets"][sheet]["profile"] == "gyp@1" and a["sheets"][sheet]["ownKey"] is True, sheet


def test_a_sheet_takes_its_own_name_as_its_id_until_the_bid_holds_one_of_its_type_and_then_a_copy_id(ran):
    assert ran["adding"]["order"] == [
        ["Epoxy", "Epoxy", "Epoxy", "Epoxy"], ["Epoxy", "Copy1", "Epoxy 2", "Epoxy"], ["Polish", "Copy2", "Polish 2", "Polish"],
        ["Seal", "Seal", "Seal", "Seal"], ["Seal (+Jnts)", "Copy3", "Seal (+Jnts)", "Seal (+Jnts)"],
        ['Gyp (USG 1-8")', 'Gyp (USG 1-8")', 'Gyp (USG 1-8")', 'Gyp (USG 1-8")'], ['Gyp (USG 1-8")', "Copy4", 'Gyp (USG 1-8") 2', 'Gyp (USG 1-8")']]


def test_a_new_sheet_is_priced_and_the_area_comes_from_the_new_id_or_the_sheets_name(ran):
    a = ran["adding"]
    assert a["prices"] == {"epoxy": True, "polish": {"priceable": True, "tooling": True}}
    assert a["sfByKey"] == {"byId": [7000], "bySheet": [6000], "none": [""]}
    assert a["snapshot"]["tabOpts"] == {"Seal": ON_THE_PROPOSAL} and a["snapshot"]["lump"] is True
    assert "cannot be added to a bid" in a["badSheet"] and "needs the model" in a["noModel"]


def test_adding_a_sheet_never_reseeds_what_the_estimator_typed_in_another(ran):
    """The root's labor is stated and its takeoff blank, with an area on offer under its sheet's name. Taking the root from the
    seeding too would fill it; only the new sheet is taken."""
    r = ran["adding"]["rootKept"]
    assert r["takeoff"] == [""] and r["labor"] == ["polishing", "travel"] and r["fees"] == 0 and r["newSheet"] == [9999]


# ── 9. the job type follows the base, and the base is not undone by the job type ─────────────────
def test_a_job_type_that_the_base_already_is_changes_nothing(ran):
    """The only Epoxy in this bid is Copy1, and it is the base. The intake says Epoxy: the model is the one handed in, no
    `Epoxy` section is added beside it, and nothing is turned off."""
    j = ran["jobTypes"]["baseIsACopy"]
    assert j["base"] == {"ids": ["Copy1"], "jobType": "epoxy"} and j["sameObject"] is True
    assert j["tabs"] == ["Copy1"] and j["kinds"] == [["Polish", "option"], ["Copy1", "base"]]
    assert j["toAdd"] == [] and j["leaving"] == []
    q = ran["jobTypes"]["polishCopyIsThePolishBase"]
    assert q["base"] == {"ids": ["Copy1"], "jobType": "polish"} and q["sameObject"] is True and q["leaving"] == []


def test_a_job_type_that_moved_makes_the_matching_sections_the_base_and_marks_the_leaving_bases_off(ran):
    j = ran["jobTypes"]
    e = j["toEpoxy"]
    assert e["base"] == {"ids": ["Epoxy"], "jobType": "epoxy"} and e["epoxyRowsKept"] is True
    assert e["kinds"] == [["Polish", "option"], ["Epoxy", "base"], ["Copy1", "off"]], "the leaving base is off, an option stays an option"
    assert e["activated"] == ["Epoxy", "Copy1"], "the Epoxy option it already had is the base, none is added"
    c = j["toCombo"]
    assert c["base"] == {"ids": ["Epoxy", "Copy1"], "jobType": "combo"} and c["kinds"] == [["Polish", "option"], ["Epoxy", "base"], ["Copy1", "base"]], \
        "the Polish half is the copy that was already a base, not a second Polish"
    g = j["toGyp"]
    assert g["base"] == {"ids": ['Gyp (USG 1-8")'], "jobType": "gyp"} and g["activated"] == ['Gyp (USG 1-8")']
    assert g["kinds"] == [["Polish", "option"], ["Epoxy", "option"], ["Copy1", "off"], ['Gyp (USG 1-8")', "base"]]


def test_an_option_that_is_the_job_types_tab_becomes_the_base_and_comes_back_off_when_the_job_moves_back(ran):
    j = ran["jobTypes"]
    o = j["optionBecomesBase"]
    assert o["base"] == {"ids": ["Epoxy"], "jobType": "epoxy"} and o["kinds"] == [["Polish", "off"], ["Epoxy", "base"]] and o["keptRows"] == 2
    b = j["backToPolish"]
    assert b["base"] == {"ids": ["Polish"], "jobType": "polish"} and b["kinds"] == [["Polish", "base"], ["Epoxy", "off"]]
    assert b["rootHasKind"] is False, "the root's key is dropped, not written as base, so a bid that never left Polish saves as it did"
    assert b["epoxyRows"] == 2
    assert j["optionStays"]["kinds"] == [["Polish", "base"], ["Epoxy", "off"], ["Seal", "option"]]
    r = j["rootOptionLifted"]
    assert r["before"] == {"ids": ["Epoxy"], "jobType": "epoxy"} and r["after"] == {"ids": ["Polish"], "jobType": "polish"}
    assert r["kinds"] == [["Polish", "base"], ["Epoxy", "off"]] and r["rootHasKind"] is False


def test_sections_that_cannot_be_read_are_returned_as_they_are_and_what_the_page_asks_first_is_by_sheet(ran):
    j = ran["jobTypes"]
    assert j["unreadable"] == {"same": True, "toAdd": [], "leaving": []}
    assert j["toAdd"] == {"polishBidForEpoxy": ["Epoxy"], "hasEpoxyOption": [], "combo": ["Epoxy"], "comboCopyHeld": [], "copyOnly": []}, \
        "a bid whose only Epoxy is a copy has an Epoxy: none is added"
    assert j["leavingCopy"] == ["Copy1"], "a copy that is the base leaves with its job type like any base"
    assert "not a job type" in j["throws"]["notReady"] and "needs the model" in j["throws"]["noModel"]


# ── 10. what a save writes ───────────────────────────────────────────────────────────────────────
def test_a_save_names_the_base_and_a_combined_base_names_none(ran):
    s = ran["snapshots"]
    assert s["baseTabId"] == {"rootWithOption": "Polish", "epoxyBase": "Epoxy", "combined": None, "copyBase": "Copy1", "noBase": None}
    assert s["singleKeys"] == ["polish_estimate", "polish_sf", "polish_2_sf", "computed_bid"], "a bid of one sheet writes what it always wrote"
    assert s["oldBid"]["keys"][4:6] == ["priced_tabs", "base_tab_id"]


def test_a_save_names_each_tab_by_its_label_and_keeps_the_entries_the_draft_holds(ran):
    s = ran["snapshots"]
    assert s["names"] == [["Polish", "Polish", "base", "polish"], ["Epoxy", "Epoxy", "base", "epoxy"], ["Copy1", "Second floor", "option", "epoxy"]]
    assert s["tabOpts"] == {"Copy1": OFF_THE_PROPOSAL}
    assert s["heldEntryKept"] == {"is_option": True, "show": False, "price_mode": "deduct", "desc": "words"}, \
        "what the estimator did in the Proposal step survives the next save"
    assert s["sealTotalOnly"] == "total" and s["copyOfSealTotalOnly"] == ["total", "total"], "Seal has no Add or Deduct, so what the model writes is a total"


def test_a_polish_copy_is_an_option_in_the_snapshot_and_a_root_that_is_an_option_names_the_copy_as_the_base(ran):
    c = ran["snapshots"]["polishCopyOption"]
    assert c["lump"] == c["rootTotal"] and c["area"] == {"polish_sf": 10000}, "an option adds no money and no area"
    assert c["tabs"] == [["Polish", "base", True, {"polish_sf": 10000}], ["Copy1", "option", True, {"polish_sf": 10000}]]
    r = ran["snapshots"]["rootOption"]
    assert r["lump"] == r["copyTotal"] and r["baseTabId"] == "Copy1" and r["rootKind"] == "option"
    assert r["tabs"] == [["Polish", "option"], ["Copy1", "base"]] and r["polishSf"] == 10000
    assert r["optionEntry"] == ON_THE_PROPOSAL, "the root, an option now, is on the proposal like any other"


def test_reading_never_writes_every_function_goes_through_a_deep_frozen_model(ran):
    assert ran["snapshots"]["frozen"] == {k: None for k in ("entries", "baseOf", "polishBid", "tabs", "snapshot", "job", "leaving", "rename", "copy",
                                                           "delete", "add")}


# ── the checks go red when the code changes ──────────────────────────────────────────────────────
def _all(r, *keys):
    return any("error" in r[k] for k in keys)


BREAKS = {
    # --- copy ---
    "a copy loses its source's profile stamp": (
        MODEL, '      body = { layout: "polish", profile: rootProfile(model).stamp, takeoff: pick("takeoff"), labor: pick("labor"),',
        '      body = { layout: "polish", profile: LEGACY.stamp, takeoff: pick("takeoff"), labor: pick("labor"),',
        lambda r: r["copies"]["rev2"]["profile"] != REV2),
    "a copy gains a pool stamp its source never had": (
        MODEL, "      if (model.pool_packs !== undefined) body.pool_packs = model.pool_packs;", "      body.pool_packs = true;",
        lambda r: r["copies"]["savedBeforeStamps"]["hasPool"] is True),
    "a copy starts on the proposal": (
        MODEL, "             patch: newOptionPatch(isObject(ctx) ? ctx.state : undefined, id, optionSettings(false)) };",
        "             patch: newOptionPatch(isObject(ctx) ? ctx.state : undefined, id, optionSettings(true)) };",
        lambda r: r["copies"]["proposal"]["snapshotEntry"] != OFF_THE_PROPOSAL),
    "a copy edits the section it came from": (
        MODEL, "      body = jsonCopy(src.section);", "      body = src.section;",
        lambda r: _all(r, "copies") or r["copies"]["epoxy"]["kind"] != "option" or r["identity"]["copyEntries"][1][3] != "base"),
    "a copy is not an option": (
        MODEL, '    body = Object.assign(body, { kind: "option", sheet: src.sheet, label: uniqueLabel(model, src.label + " copy"),',
        '    body = Object.assign(body, { kind: "base", sheet: src.sheet, label: uniqueLabel(model, src.label + " copy"),',
        lambda r: _all(r, "copies") or r["copies"]["legacy"]["kind"] != "option"),
    "a copy forgets its sheet": (
        MODEL, '    body = Object.assign(body, { kind: "option", sheet: src.sheet, label: uniqueLabel(model, src.label + " copy"),',
        '    body = Object.assign(body, { kind: "option", sheet: ROOT_TAB, label: uniqueLabel(model, src.label + " copy"),',
        lambda r: _all(r, "copies", "identity") or r["copies"]["epoxy"]["sheet"] != "Epoxy"),
    # --- polishBid ---
    "a Polish copy is priced by the generic engine path": (
        MODEL, '    if (e.layout === "polish" && !e.root) return polishBid(model, tabId, ctx);',
        '    if (false) return polishBid(model, tabId, ctx);',
        lambda r: _all(r, "copies") or r["copies"]["legacy"]["viaPriceSection"] is not True),
    "polishBid prices every Polish section as legacy": (
        MODEL, "    }, profile.stamp);", "    }, LEGACY.stamp);",
        lambda r: r["polishCopies"]["rev2"]["rootIsTheOldBid"] is not True),
    "polishBid leaves the tooling out": (
        MODEL, "      tooling: profile.quirks.toolingInSubTotal ? takeoffTooling(s.takeoff, model.conditions) : 0,", "      tooling: 0,",
        lambda r: r["polishCopies"]["rev2"]["rootIsTheOldBid"] is not True),
    "polishBid charges every section the job's travel": (
        MODEL, '    if (carrier || (e.root && e.kind === "off")) return travelCosts(model.travel, s.labor, travelOpts(model, e.tab)).total;',
        "    if (true) return travelCosts(model.travel, s.labor, travelOpts(model, e.tab)).total;",
        lambda r: r["copies"]["legacy"]["farAsOption"] != 1500),
    "polishBid gives an option no travel": (
        MODEL, '    if (e.kind === "option") return optionTravelCosts(model.travel, s.labor).total;',
        '    if (false) return optionTravelCosts(model.travel, s.labor).total;',
        lambda r: r["copies"]["legacy"]["farAsOption"] != 1500),
    "a rev 2 copy counts the nights of the people and not the sheet's": (
        MODEL, '    return isObject(s) && s.layout === "polish" && s.profile === REV2.stamp;', "    return false;",
        lambda r: r["polishCopies"]["nights"]["rev2CopyAsCarrier"] != r["polishCopies"]["nights"]["rev2Root"]),
    "an off root stops answering the job's travel": (
        MODEL, '    if (carrier || (e.root && e.kind === "off")) return travelCosts(model.travel, s.labor, travelOpts(model, e.tab)).total;',
        "    if (carrier) return travelCosts(model.travel, s.labor, travelOpts(model, e.tab)).total;",
        lambda r: r["polishCopies"]["offRoot"]["travel"] != 1000),
    "an unreadable bid cannot price its root": (
        MODEL, "      if (tabId !== ROOT_TAB) throw err;", "      throw err;",
        lambda r: _all(r, "polishCopies")),
    "polishBid reprices a stamp it does not know": (
        MODEL, "    var profile = e.profile === LEGACY.stamp ? LEGACY : (e.profile === REV2.stamp ? REV2 : null);",
        "    var profile = e.profile === REV2.stamp ? REV2 : LEGACY;",
        lambda r: r["polishCopies"]["errors"]["unknownStamp"].get("priceable") is not False),
    "the page leaves Dye out of a Polish copy": (
        PAGE, '    if (entry.role === "polish") return { material: polishMaterial(takeoff) };', "    void polishMaterial;",
        lambda r: _all(r, "page") or r["page"]["copyOnPage"]["same"] is not True),
    "the page reads a Gyp copy by its key": (
        PAGE, "      var g = G.sectionMaterial(takeoff, entry.section.gyp, entry.sheet, {",
        "      var g = G.sectionMaterial(takeoff, entry.section.gyp, entry.tab, {",
        lambda r: _all(r, "page") or r["page"]["gypCopyOnPage"]["priceable"] != [True, True]),
    # --- pick the base ---
    "the prior base stays a base": (
        MODEL, '      var next = want.indexOf(e.tab) >= 0 ? "base" : (isBaseEntry(e) ? "option" : e.kind);',
        '      var next = want.indexOf(e.tab) >= 0 ? "base" : e.kind;',
        lambda r: _all(r, "baseBid", "combinedBase") or r["baseBid"]["after"]["kinds"] != [["Polish", "option"], ["Epoxy", "base"]]),
    "the prior base is not put on the proposal": (
        MODEL, '      var kept = Object.assign(optionSettings(true), entryOf(id), { is_option: true, show: true, price_mode: "total" });',
        "      var kept = Object.assign(optionSettings(true), entryOf(id));",
        lambda r: r["baseBid"]["patch"]["tab_opts"]["Polish"]["is_option"] is not True),
    "the prior base loses the words typed on it": (
        MODEL, '      var kept = Object.assign(optionSettings(true), entryOf(id), { is_option: true, show: true, price_mode: "total" });',
        '      var kept = Object.assign(optionSettings(true), { is_option: true, show: true, price_mode: "total" });',
        lambda r: r["baseBid"].get("keptDesc") != "keep me"),
    "the new base stays an option on the draft": (
        MODEL, "      if (!has.call(held, id) || !isObject(held[id]) || held[id].is_option !== true) return;", "      return;",
        lambda r: r["baseBid"]["backAgain"]["patch"]["tab_opts"]["Polish"]["is_option"] is not False),
    "the jobs travel labor stays on the old carrier": (
        MODEL, "    if (carrierAfter !== carrierBefore) out = moveTravelLabor(out, carrierBefore, carrierAfter);", "    void moveTravelLabor;",
        lambda r: r["baseBid"]["travelLaborRow"]["epoxyAfter"] != ["installing", "travel"]),
    "the travel labor row is added even when the new carrier has one": (
        MODEL, "    if (!mine.length || theirs.length) return model;", "    if (!mine.length) return model;",
        lambda r: _all(r, "baseBid", "copies") or r["copies"]["legacy"]["farAsBase"] is not True),
    "a pick forgets the work type": (
        MODEL, "    var patch = { work_type: baseOf(out).jobType, base_tab_id: want.length === 1 ? want[0] : null };",
        "    var patch = { base_tab_id: want.length === 1 ? want[0] : null };",
        lambda r: "work_type" not in r["baseBid"]["patch"]),
    "a combined base names one sheet": (
        MODEL, "    var patch = { work_type: baseOf(out).jobType, base_tab_id: want.length === 1 ? want[0] : null };",
        "    var patch = { work_type: baseOf(out).jobType, base_tab_id: want[0] };",
        lambda r: r["combinedBase"]["patch"]["base_tab_id"] is not None),
    "Seal can be the base": (
        MODEL, "      if (rec.optionOnly) throw new Error(", "      if (false) throw new Error(",
        lambda r: r["refusals"]["sealBase"] is None),
    "any two sheets are a combined base": (
        MODEL, '      if (roles[0] !== "epoxy" || roles[1] !== "polish") throw new Error("A combined base is one Epoxy sheet and one Polish sheet.");',
        '      if (false) throw new Error("A combined base is one Epoxy sheet and one Polish sheet.");',
        lambda r: r["refusals"]["polishAndGyp"] is None),
    "the same sheet twice is a pair": (
        MODEL, "    if (want.length < 1 || want.length > 2 || (want.length === 2 && want[0] === want[1])) {",
        "    if (want.length < 1 || want.length > 2) {",
        lambda r: "one sheet, or" not in (r["refusals"]["sameTwice"] or "")),
    # --- baseOf ---
    "an option-only tab declared a base is counted": (
        MODEL, '    return e.kind === "base" && !types.tab(types.tabOfSheet(e.sheet)).optionOnly;', '    return e.kind === "base";',
        lambda r: r["baseOfCases"]["sealDeclared"]["ids"] != ["Polish"]),
    "an Epoxy and a Polish base are not a combo": (
        MODEL, '      if (roles[0] === "epoxy" && roles[1] === "polish") return "combo";', '      if (false) return "combo";',
        lambda r: r["baseOfCases"]["combo"]["jobType"] != "combo" or r["combinedBase"]["base"]["jobType"] != "combo"),
    "two bases of any kind are a combo": (
        MODEL, '      if (roles[0] === "epoxy" && roles[1] === "polish") return "combo";', '      if (roles.length === 2) return "combo";',
        lambda r: r["baseOfCases"]["polishAndGyp"]["jobType"] is not None),
    # --- delete ---
    "the base can be deleted": (
        MODEL, '    if (e.kind === "base") throw new Error("Pick another base bid before you delete " + e.label + ".");',
        '    if (false) throw new Error("Pick another base bid before you delete " + e.label + ".");',
        lambda r: r["refusals"]["deleteBase"] is None),
    "the root can be deleted": (
        MODEL, '    if (e.root) throw new Error("The " + e.label + " sheet is where this bid starts, so it cannot be deleted. Take it off the proposal instead.");',
        '    if (false) throw new Error("The " + e.label + " sheet is where this bid starts, so it cannot be deleted. Take it off the proposal instead.");',
        lambda r: "cannot be deleted" not in (r["refusals"]["deleteRoot"] or "")),
    "a delete leaves the draft's words for the next sheet": (
        MODEL, "    return { model: out, patch: optionLeftoverPatch(isObject(ctx) ? ctx.state : undefined, id) };",
        "    return { model: out, patch: {} };",
        lambda r: r["idReuse"]["nothingLeft"] is not True),
    "a new sheet inherits what the draft kept under its id": (
        MODEL, "    var gone = optionLeftoverPatch(st, id);", "    var gone = {};",
        lambda r: r["idReuse"]["staleScrubbed"]["words"] is not True),
    "the smallest free id is not handed out": (
        MODEL, '    while (used.has("Copy" + i)) i++;', "    i = used.size + 1;",
        lambda r: r["idReuse"]["order"]["next"] != "Copy2"),
    "there is no limit on copies": (
        MODEL, "    if (held >= MAX_COPIES) throw new Error(", "    if (false) throw new Error(",
        lambda r: r["copies"]["limit"]["over"] is None),
    # --- rename ---
    "a rename is not validated": (
        MODEL, "    if (why) throw new Error(why);", "    void why;",
        lambda r: r["renaming"]["refused"]["dup"] is None),
    "a name can be any length": (
        MODEL, '    if (n.length > 31) return "A sheet name can have 31 characters at most.";', "    void n;",
        lambda r: r["renaming"]["all"]["long32"] is None),
    "a name can have the characters a workbook refuses": (
        MODEL, '    if (/[!:\\\\/?*\\[\\]"]/.test(n)) return', '    if (false) return',
        lambda r: r["renaming"]["all"]["char !"] is None),
    "a name can be another sheet's": (
        MODEL, "    return taken ? '\"' + n + '\" is already the name of a sheet.' : null;", "    return null;",
        lambda r: r["renaming"]["all"]["dupRoot"] is None),
    "a rename stores the name under the wrong key": (
        MODEL, "    return withSectionPatch(model, id, { label: next });", "    return withSectionPatch(model, id, { name: next });",
        lambda r: r["renaming"]["label"] != "Garage floor"),
    "the proposal is given the key and not the label": (
        MODEL, "        id: x.e.tab, name: x.e.label, role: x.e.role, kind: x.e.kind,", "        id: x.e.tab, name: x.e.tab, role: x.e.role, kind: x.e.kind,",
        lambda r: r["renaming"]["byLabel"] != [["Polish", "Polish"], ["Epoxy", "Epoxy"], ["Copy1", "Garage floor"]]),
    "the root's name is not read": (
        MODEL, '    return typeof model.label === "string" && model.label.trim() ? model.label : ROOT_TAB;', "    return ROOT_TAB;",
        lambda r: r["renaming"]["rootRenamed"]["label"] != "Main floor"),
    # --- preset on a copy ---
    "a copy's preset change renames its key": (
        MODEL, "    if (COPY_ID.test(fromTab)) return withSectionPatch(model, fromTab, { sheet: toTab, profile: profile.stamp });", "    void profile;",
        lambda r: _all(r, "presets")),
    "a Gyp copy is priced on its key's truckload": (
        MODEL, "        input.truckload = engine.forTab(e.sheet).truckload;", "        input.truckload = engine.forTab(e.tab).truckload;",
        lambda r: _all(r, "presets") or r["presets"]["priceOnCopy"] != [True, True]),
    # --- add ---
    "a new Polish sheet is not stamped rev 2": (
        MODEL, "    var profile = polish ? REV2 : engine.forTab(sheet).profile;", "    var profile = engine.forTab(sheet).profile;",
        lambda r: _all(r, "adding") or r["adding"]["sheets"]["Polish"]["profile"] != REV2),
    "a new sheet is not stamped for the purchase pool": (
        MODEL, "    section.pool_packs = true;      // a section made now buys each material once for the whole section (see poolsPacks)",
        "    void 0;",
        lambda r: r["adding"]["sheets"]["Epoxy"].get("pool") is not True),
    "a new sheet starts off the proposal": (
        MODEL, "             patch: newOptionPatch(c.state, id, optionSettings(true)) };", "             patch: newOptionPatch(c.state, id, optionSettings(false)) };",
        lambda r: r["adding"]["sheets"]["Epoxy"]["patch"] != ON_THE_PROPOSAL),
    "an added sheet takes the root from the seeding": (
        MODEL, "    return { model: withSectionPut(withSection, id, seeded.tabs[id]), id: id,", "    return { model: seeded, id: id,",
        lambda r: r["adding"]["rootKept"]["takeoff"] != [""]),
    "every sheet is filed under its own name": (
        MODEL, "    var id = ownKey ? sheet : nextCopyId(model);", "    var id = sheet;",
        lambda r: _all(r, "adding", "copies") or r["adding"]["order"][1][1] != "Copy1"),
    "Leveling can be added": (
        MODEL, "      if (!(rec.optionOnly ? rec.offered === true : tabIsReady(key))) return;", "      if (false) return;",
        lambda r: _all(r, "adding") or r["refusals"]["addLeveling"] is None),
    # --- the job type ---
    "a job type takes the first section of a tab and not the one that is the base": (
        MODEL, "    if (base.length) return base[0];", "    void base;",
        lambda r: r["jobTypes"]["toCombo"]["kinds"] != [["Polish", "option"], ["Epoxy", "base"], ["Copy1", "base"]]),
    "an option is not made the base": (
        MODEL, '      } else if (out.tabs[id].kind !== "base") out = withSectionKind(out, id, "base");', "      } else void 0;",
        lambda r: r["jobTypes"]["optionBecomesBase"]["base"]["jobType"] != "epoxy"),
    "an option leaves with the job type": (
        MODEL, '      if (e.kind !== "base" || picked.indexOf(e.tab) >= 0 || !leavesWithJob(e)) return;',
        "      if (picked.indexOf(e.tab) >= 0 || !leavesWithJob(e)) return;",
        lambda r: r["jobTypes"]["optionStays"]["kinds"] != [["Polish", "base"], ["Epoxy", "off"], ["Seal", "option"]]
        or r["jobTypes"]["toEpoxy"]["kinds"][0] != ["Polish", "option"]),
    "a root option is not lifted": (
        MODEL, '        if (out.kind === "off" || out.kind === "option") { out = Object.assign({}, out); delete out.kind; }',
        '        if (out.kind === "off") { out = Object.assign({}, out); delete out.kind; }',
        lambda r: r["jobTypes"]["rootOptionLifted"]["after"]["jobType"] != "polish"),
    "a second Epoxy is added beside a copy that is the bid's Epoxy": (
        MODEL, "      return rec.sheets[0] !== ROOT_TAB && !held.some(function (e) { return types.tabOfSheet(e.sheet) === rec.key; });",
        "      return rec.sheets[0] !== ROOT_TAB && sheetHeld(model, rec) === null;",
        lambda r: r["jobTypes"]["toAdd"]["copyOnly"] != []),
    "a copy is not a leaving base": (
        MODEL, '      return !e.root && e.kind === "base" && mine.indexOf(types.tabOfSheet(e.sheet)) < 0 && tabIsReady(types.tabOfSheet(e.sheet));',
        '      return !e.root && e.kind === "base" && mine.indexOf(types.tabOfSheet(e.sheet)) < 0 && tabIsReady(types.tabOfSheet(e.sheet)) && e.tab === e.sheet;',
        lambda r: r["jobTypes"]["leavingCopy"] != ["Copy1"]),
    # --- identity ---
    "a copy's sheet is read from its key": (
        MODEL, '      var sheet = copy ? (typeof s.sheet === "string" ? s.sheet : "") : id;', "      var sheet = id;",
        lambda r: _all(r, "identity", "copies")),
    "the root's kind is not read": (
        MODEL, '    var rootKind = model.kind === "off" ? "off" : (model.kind === "option" ? "option" : "base");',
        '    var rootKind = model.kind === "off" ? "off" : "base";',
        lambda r: r["identity"]["rootKinds"]["option"] != "option"),
    "a section that says another sheet is believed": (
        MODEL, "      if (!copy && s.sheet !== undefined && s.sheet !== id) throw new Error(", "      if (false) throw new Error(",
        lambda r: r["identity"]["throws"]["sheetKeyWithOtherSheet"] is None),
    "the label is the key": (
        MODEL, '      out.push({ tab: id, sheet: sheet, label: typeof s.label === "string" && s.label.trim() ? s.label : id,',
        "      out.push({ tab: id, sheet: sheet, label: id,",
        lambda r: r["renaming"]["label"] != "Garage floor"),
    # --- the save ---
    "the base's id is not written": (
        MODEL, "    out.base_tab_id = base.length === 1 ? base[0].e.tab : null;", "    out.base_tab_id = null;",
        lambda r: r["snapshots"]["baseTabId"]["rootWithOption"] != "Polish"),
    "a combined base names the first sheet": (
        MODEL, "    out.base_tab_id = base.length === 1 ? base[0].e.tab : null;", "    out.base_tab_id = base.length ? base[0].e.tab : null;",
        lambda r: r["snapshots"]["baseTabId"]["combined"] is not None),
    "an entry the draft holds is rewritten on every save": (
        MODEL, "        if (has.call(heldOpts, id)) return;", "        void 0;",
        lambda r: r["snapshots"]["heldEntryKept"] != {"is_option": True, "show": False, "price_mode": "deduct", "desc": "words"}),
    "an option is added into the lump sum": (
        MODEL, '    return e.kind === "base" && !types.tab(types.tabOfSheet(e.sheet)).optionOnly;', '    return e.kind !== "off";',
        lambda r: r["snapshots"]["polishCopyOption"]["lump"] != r["snapshots"]["polishCopyOption"]["rootTotal"]),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_facts_go_red_when_the_code_changes(tmp_path, name):
    """Each change is the kind a refactor makes by accident, applied to a scratch copy of the model or the page. The anchor
    must be in the file exactly once (break_source refuses otherwise)."""
    require_node()
    rel, old, new, noticed = BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, SCRATCH_FILES)
    got = _run(frontend)
    assert noticed(got), "the facts did not notice: " + name
