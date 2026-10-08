"""Phase 4 of the v2 estimating program: the saved estimate keeps what it does not know, and every
writer saves it the same way.

TWO DEFECTS stood in front of every later phase.

  1. `migrateModel`'s v2 branch rebuilt the model from a fixed key list, so any key it did not name was
     erased by the next save. Nothing writes the other sheets' `tabs`, a rates snapshot or a profile
     stamp yet, and the first thing that does would lose them the first time an estimator flipped an
     unrelated switch. The model now carries every key it does not normalise, `tabs` included.
  2. The estimate page composed what it saves in two places, the 600 ms autosave and the `pagehide`
     flush, and the two had drifted: the flush skipped the condition cells (a tab closed inside the
     debounce window left the workbook's Yes/No literals stale) and the measured-floor fallback (with
     the only SF row switched off it saved a polish SF of 0). One `buildSavePatch` now, and the
     intake's merge is one `patchModel`.

EVERYTHING HERE RUNS CODE. tests/js/model-safety-harness.js executes the real bid-model.js over
every saved-bid fixture that tests/js/saved-bid-scenarios.js holds (lifted from that file by name, so a
fixture added there is covered here) plus synthetic models carrying `work_type`, `tabs`, a rates
snapshot and a profile stamp; the real estimate page, saved once by its timer and once by `pagehide`
from identical drafts; and the real intake page's save() after an estimate save. The last test in this
file breaks a scratch copy of the code in twelve ways and requires the harness to notice each one, and
`break_source` refuses an anchor that is not in the file exactly once, so none of them can pass by
applying nowhere.

NOT CHANGED BY THIS PHASE: no price. The saved-bid ratchet (test_polish_saved_bid_safety.py) and the
library golden are untouched and green. The Polish chain golden moves by exactly one vector, the one
that recorded the model DROPPING unknown keys (`model/migrate/unknownKeys`), and
test_polish_chain_golden.py says which.
"""
import pathlib
import shutil

import pytest

from _golden_support import break_source, copy_unmodified
from _node import last_json_line, run_node
from test_polish_saved_bid_safety import NEWEST_TOTALS, STAGING_TOTALS

TESTS = pathlib.Path(__file__).resolve().parent
FRONTEND = TESTS.parents[1] / "frontend"
BACKEND = TESTS.parents[1] / "backend"
HARNESS = TESTS / "js" / "model-safety-harness.js"

SAVED_V1 = ["v1_areas"]
SAVED_V2 = sorted((set(STAGING_TOTALS) | set(NEWEST_TOTALS)) - set(SAVED_V1))
SYNTHETIC = ["synthetic_work_type", "synthetic_tabs", "synthetic_rates_snapshot", "synthetic_profile_stamp",
             "synthetic_falsy_unknowns", "synthetic_all_together", "synthetic_unversioned_partial"]
SYNTHETIC_WITH_TABS = ["synthetic_tabs", "synthetic_all_together", "synthetic_unversioned_partial"]
ESTIMATE_SCENARIOS = ["typed", "condition", "onlyRowOff", "library", "withTabs"]


def _run(frontend=FRONTEND):
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    return _run()


# ── the harness is not vacuous ───────────────────────────────────────────────────────────────────
def test_the_harness_covers_every_fixture_the_saved_bid_ratchet_pins(ran):
    """The round-trip laws are run over the SAME fixtures test_polish_saved_bid_safety.py pins totals
    for. A fixture added to saved-bid-scenarios.js is picked up by the harness on its own; this fails
    if the ratchet and the harness ever stop agreeing about which fixtures exist."""
    assert sorted(ran["names"]["saved"]) == sorted(set(STAGING_TOTALS) | set(NEWEST_TOTALS))
    assert sorted(ran["names"]["synthetic"]) == sorted(SYNTHETIC)


@pytest.mark.parametrize("section", ["fixtures", "hostile", "patch", "savePatch", "estimate", "intake"])
def test_no_section_of_the_harness_failed_or_is_missing_its_function(ran, section):
    """A section that threw (or whose function does not exist) reports it instead of crashing, so
    that running this harness over an older tree fails an assertion with a reason, not a stack."""
    got = ran[section]
    assert "error" not in got, got.get("error")
    assert "missing" not in got, "bid-model.js has no %s" % ("patchModel" if section == "patch" else "buildSavePatch")


# ── 1. the round-trip laws ───────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", SAVED_V2)
def test_every_key_of_a_saved_bid_comes_back_through_migrate(ran, name):
    """migrateModel(JSON.parse(JSON.stringify(x))) keeps every key x had, over every bid the ratchet
    saves in today's shapes. (They hold only keys the model knows, so this is the ratchet that
    normalising a known key never loses one: the same law is what the synthetic models below prove
    for keys it does NOT know.)

    Mutation: any branch of migrateModel's v2 output that stops stating a key it used to."""
    got = ran["fixtures"]["saved"][name]
    assert got["kind"] == "v2"
    assert got["missing"] == [], "migrateModel dropped %r from %s" % (got["missing"], name)
    assert got["unknownChanged"] == []


@pytest.mark.parametrize("name", SYNTHETIC)
def test_a_key_the_model_does_not_know_comes_back_as_saved(ran, name):
    """`work_type`, `tabs`, a rates snapshot, a profile stamp, and falsy values (null, false, 0, "",
    [], {}) are somebody else's: migrateModel carries them and does not touch what is inside.

    Mutation: `return carryUnknownKeys(out, model)` -> `return out` (the old behaviour)."""
    got = ran["fixtures"]["synthetic"][name]
    assert got["unknown"], "the fixture %s states nothing the model does not know: the law is vacuous" % name
    assert got["missing"] == [], "migrateModel erased %r" % got["missing"]
    assert got["unknownChanged"] == [], "migrateModel changed %r on the way through" % got["unknownChanged"]


def test_the_synthetic_models_between_them_carry_every_kind_of_extra_key(ran):
    unknown = {k for n in SYNTHETIC for k in ran["fixtures"]["synthetic"][n]["unknown"]}
    assert {"work_type", "tabs", "rates", "profile", "a_null", "a_false", "a_zero", "an_empty_string",
            "an_empty_list", "an_empty_object"} <= unknown


@pytest.mark.parametrize("name", SYNTHETIC_WITH_TABS)
def test_tabs_come_back_byte_for_byte(ran, name):
    """Compared as JSON text, so key order and an awkward tab name (`Gyp (USG 1-8")`) are part of it."""
    assert ran["fixtures"]["synthetic"][name]["tabsIdentical"] is True


@pytest.mark.parametrize("name", SAVED_V2 + SAVED_V1 + SYNTHETIC)
def test_migrating_twice_is_migrating_once(ran, name):
    """migrateModel(migrateModel(x)) deep-equals migrateModel(x), strictly (prototypes included).

    Mutation: carry an unknown key through a different path on the second pass than the first."""
    where = "saved" if name in SAVED_V2 + SAVED_V1 else "synthetic"
    got = ran["fixtures"][where][name]
    assert got["idempotent"], got["idempotentDiff"]


@pytest.mark.parametrize("name", SAVED_V2 + SAVED_V1 + SYNTHETIC)
def test_reading_a_saved_model_never_edits_it(ran, name):
    where = "saved" if name in SAVED_V2 + SAVED_V1 else "synthetic"
    assert ran["fixtures"][where][name]["inputUntouched"] is True


def test_a_v1_model_is_still_a_one_way_upgrade_that_consumes_its_legacy_keys(ran):
    """The v1 branch is NOT a passthrough, on purpose: `areas` became the takeoff, `labour` became
    the labor rows, and carrying the old keys forward would price the same material twice. Pinned
    here beside the passthrough so nobody 'fixes' it into one: the result is exactly the documented
    v2 shape, with the two v1 keys of the fixture consumed."""
    got = ran["fixtures"]["saved"]["v1_areas"]
    assert got["kind"] == "v1"
    assert got["outKeys"] == ["conditions", "contingency", "fees", "labor", "takeoff", "totals",
                              "travel", "version"]
    assert got["missing"] == ["areas", "polishing"]


def test_the_known_key_list_is_what_the_v2_branch_actually_normalises(ran):
    """MODEL_KEYS is the list of keys migrateModel rewrites or drops, so it is the list a carried key
    must never overlap. It is checked against what a model that states EVERY one of them comes back
    with: a key added to migrateModel's output and forgotten in MODEL_KEYS would be carried raw OVER
    its own normalisation.

    Mutation: delete `"distance"` from MODEL_KEYS."""
    k = ran["known"]
    assert k["keys"] == k["maximalKeys"], "the maximal model is not stating every key it comes back with"
    assert len(k["keys"]) == 13
    assert k["exported"] == k["keys"]


def test_a_hostile_key_in_a_saved_model_is_dropped_and_pollutes_nothing(ran):
    """`__proto__`, `constructor` and `prototype` are refused by copyInto, the file's one idiom for
    copying user data; an ordinary key beside them still comes through.

    Mutation: `copyInto(out, ...)` -> `Object.assign(out, ...)` in carryUnknownKeys."""
    h = ran["hostile"]
    assert h["ownProto"] is False and h["ownConstructor"] is False and h["ownPrototype"] is False
    assert h["protoIsObjectPrototype"] is True, "a saved `__proto__` replaced the model's prototype"
    assert h["leaked"] is None, "a saved `__proto__` polluted Object.prototype"
    assert h["fine"] == {"kept": 1}


# ── 2. patchModel: what the intake owns, and nothing else ────────────────────────────────────────
def test_a_patch_lays_the_intakes_answers_over_the_saved_model_and_touches_nothing_else(ran):
    p = ran["patch"]
    assert p["conditions"] == p["expectedConditions"], "conditions are merged key by key over the saved ones"
    assert p["shown"] == {"dye": False}, "conditions_shown is replaced when the patch states one"
    assert p["restDiff"] is None, "something the patch does not own changed: %s" % p["restDiff"]
    assert p["tabsIdentical"] is True and p["extrasKept"] is True


def test_a_patch_cannot_state_what_the_intake_does_not_own(ran):
    """A patch that carries a takeoff, labor rows, `tabs`, a version, fees, totals or a work type
    changes none of them, and a `conditions_shown` that is not an object is ignored.

    Mutation: `copyInto(model, p)` after the patch is read, in patchModel."""
    p = ran["patch"]
    assert p["smuggledRestDiff"] is None, "a patch overwrote what only the estimate page owns: %s" % p["smuggledRestDiff"]
    assert p["smuggledShown"] == {"joint_filler": False}, "a non-object conditions_shown replaced the saved one"


def test_patching_is_pure_and_idempotent(ran):
    p = ran["patch"]
    assert p["pureThrew"] is None, "patchModel edited a frozen input: %s" % p["pureThrew"]
    assert p["inputsUntouched"] is True
    assert p["idempotent"] is True


def test_a_patch_always_mints_a_well_formed_v2_and_never_states_labor_that_was_never_stated(ran):
    """What the intake page needs from its save: a version stamped on whatever is saved (backend/drafts.py
    reads it to resume the project on the beta intake), a takeoff, and NO `labor` key when nothing ever
    stated one (laborUnstated is the gate the estimate page seeds the library's labor lines behind).

    Mutation: delete `if (laborUnstated(existing)) delete model.labor;`."""
    mint = ran["patch"]["mint"]
    for name, got in mint.items():
        assert got["version"] == 2 and got["hasTakeoff"], name
        assert got["taxable"] is False, "the patch's answer did not land on %s" % name
        assert got["hasLabor"] == (not got["unstated"]), name
    # the cases that matter are really in the table: nothing saved, and a v2 that states no labor
    assert mint["undef"]["unstated"] and mint["nul"]["unstated"] and mint["v2NoLabor"]["unstated"]
    assert not mint["v2WithLabor"]["unstated"] and mint["v2WithLabor"]["hasLabor"]


# ── 3. buildSavePatch, as a pure function ────────────────────────────────────────────────────────
def test_the_save_patch_holds_exactly_the_five_keys_the_estimate_page_saves(ran):
    s = ran["savePatch"]
    assert s["frozenThrew"] is None, "buildSavePatch edited a frozen input: %s" % s["frozenThrew"]
    assert s["keys"] == ["cell_values", "computed_bid", "polish_2_sf", "polish_estimate", "polish_sf"]
    assert s["polish2Sf"] == ""


def test_the_save_patch_carries_the_whole_model_and_stamps_the_bid_as_its_totals(ran):
    """Everything the model holds rides along (`tabs` included), `totals` is the bid it was handed,
    and the model it was handed is neither the object it saved nor edited to take the stamp.

    Mutation: `Object.assign(copyInto({}, model), { totals: b })` -> `Object.assign(model, { totals: b })`."""
    s = ran["savePatch"]
    assert s["modelExpected"] is None, s["modelExpected"]
    assert s["totalsAreTheBid"] is True and s["tabsIdentical"] is True
    assert s["modelCopied"] is True and s["modelUntouched"] is True


def test_the_save_patch_writes_the_condition_cells_merged_over_the_drafts_own(ran):
    """A cell this page does not own survives; a stale one it does own is overwritten; Dye and Joint
    Filler's rate and quantity cells follow the library lines the page priced with; and with no library
    handed in, those two are left exactly as they were.

    Mutation: `cell_values: conditionCellWrites(model.conditions, cells, ctx.library)` -> `cell_values: cells`."""
    s = ran["savePatch"]
    c = s["cells"]
    assert c["foreignKept"] == 5000
    assert c["taxable"] == "No" and c["localOverwritesStale"] == "Yes"
    assert c["dyeRate"] == c["dyeRateSecondCoat"] == 0.07, "dye is $0.14 over a coverage of 2 on both coats"
    assert c["jfRate"] == 500 and c["jfQty"] == '=ROUNDUP(IF(E29="yes",(E18/3000),0),0)'
    assert s["noLibraryWritesNoLibraryCells"] is True


def test_the_save_patch_keeps_the_measured_floor_when_nothing_is_priced(ran):
    """polish_sf is the priced area; with the only SF row switched off it is the MEASURED floor, not 0
    (a 0 unlocked intake's SF boxes and sent the proposal an empty SF token). computed_bid keeps the
    AREA PRICED, because price per SF divides by it.

    Mutation: `polish_sf: b.sf > 0 ? b.sf : measuredSf(model.takeoff)` -> `polish_sf: b.sf`."""
    s = ran["savePatch"]
    assert s["polishSf"]["saved"] == s["polishSf"]["priced"] == 17500
    assert s["floor"] == {"pricedSf": 0, "saved": 12500, "computedSf": 0}


def test_the_save_patch_replaces_computed_bid_with_the_figures_the_app_reads(ran):
    s = ran["savePatch"]
    assert s["computed"] == s["expectedComputed"]


def test_a_save_with_no_price_is_refused(ran):
    s = ran["savePatch"]
    assert s["throwsWithoutBid"] and s["throwsWithoutCtx"] and s["throwsWithoutModel"]


# ── 4. the estimate page: the autosave and the pagehide flush write the same thing ───────────────
@pytest.mark.parametrize("name", ESTIMATE_SCENARIOS)
def test_the_autosave_and_the_pagehide_flush_write_the_same_blob(ran, name):
    """From identical drafts, the same edit, saved once by the 600 ms timer and once by `pagehide`:
    the whole blob handed to TW.setState is deep-equal. Before this phase the flush left out
    `cell_values` (every scenario but one) and saved `polish_sf: b.sf` (the one with the only row off).

    Mutation: give the pagehide flush its own composition again (see the table at the bottom)."""
    s = ran["estimate"][name]
    assert s["savesAutosave"] == 1 and s["savesPagehide"] == 1
    assert s["flushedByPagehide"] == 1, "pagehide saved locally but never forced the network flush"
    assert s["equal"], "the two save paths drifted: %s" % s["diff"]


@pytest.mark.parametrize("name", ESTIMATE_SCENARIOS)
def test_closing_the_tab_after_the_autosave_leaves_the_draft_as_the_autosave_wrote_it(ran, name):
    """The page never clears its timer handle once the timer has fired, so its `pagehide` handler
    runs after EVERY edit, not only inside the debounce window. Before Phase 4 that meant leaving the
    page overwrote a correct autosave with the drifted flush: with the only SF row switched off the
    autosave kept `polish_sf` at the measured 12,500 and the flush then saved 0. Now the flush is the
    same composition, so it writes what the autosave already wrote.

    Mutation: give the pagehide flush its own composition again (see the table at the bottom)."""
    s = ran["estimate"][name]
    assert s["settled"], "the flush changed the draft after the autosave: %s" % s["settledDiff"]


def test_the_estimate_scenarios_exercise_what_used_to_drift(ran):
    """So the equality above cannot pass because both paths wrote nothing. The condition cell moves
    with the switch, the floor survives the only row going off, and the library's cells are written
    on BOTH paths."""
    e = ran["estimate"]
    for way in ("autosave", "pagehide"):
        assert e["condition"][way]["cells"]["Epoxy!B6"] == "No", way
        assert e["condition"][way]["taxable"] is False, way
        assert e["onlyRowOff"][way]["polish_sf"] == 12500, way
        assert e["onlyRowOff"][way]["computedSf"] == 0, way
        assert e["library"][way]["cells"]["Polish!C25"] == 0.14, way
        assert e["library"][way]["cells"]["Polish!C29"] == 500, way
        assert e["typed"][way]["polish_2_sf"] == "", way
        assert e["typed"][way]["lump"] == e["typed"][way]["totalsTotal"] > 0, way


def test_an_estimate_save_keeps_the_tabs_and_everything_else_the_model_does_not_know(ran):
    """Through the real page, both ways: the model the page saves holds `work_type`, `tabs`, `rates`,
    `profile` and a null, and `tabs` is byte for byte what was sent."""
    w = ran["estimate"]["withTabs"]
    for way in ("autosave", "pagehide"):
        keys = w[way]["modelKeys"]
        for k in ("work_type", "tabs", "rates", "profile", "a_null"):
            assert k in keys, "%s: the page saved a model with no %s" % (way, k)
        assert w[way]["tabs"] == w["sentTabs"], way


# ── 5. the intake page ───────────────────────────────────────────────────────────────────────────
def test_an_intake_save_leaves_the_tabs_and_the_other_keys_alone(ran):
    a = ran["intake"]["alone"]
    assert a["tabsIdentical"] is True
    assert a["extrasMissing"] == []
    assert a["taxableFlipped"] is True, "the toggle it was saving did not land"
    assert a["takeoffKept"] is True and a["version"] == 2


def test_an_intake_save_after_an_estimate_save_leaves_tabs_byte_identical(ran):
    """The cross-page law, through the two real pages over one draft: an estimate save, then an intake
    save. `tabs` is the same bytes before, after the estimate save and after the intake save, nothing
    else the model carries goes missing in either, and the estimate's takeoff survives the intake."""
    c = ran["intake"]["cross"]
    assert c["tabsAfterEstimate"] == c["tabsBefore"]
    assert c["tabsAfterIntake"] == c["tabsBefore"]
    assert c["extrasMissingAfterEstimate"] == [] and c["extrasMissingAfterIntake"] == []
    assert c["measurementAfterEstimate"] == c["measurementAfterIntake"] == "12000"
    assert c["prevailingWageAfterIntake"] is True, "the intake's own answer did not land"
    assert c["saves"] == {"estimate": 1, "intake": 1}


# ── red without the code: break a COPY and watch each law notice ─────────────────────────────────
SCRATCH_FRONTEND_FILES = ["polish-estimate.html", "polish-intake.html", "js/polish-estimate.js",
                          "js/polish-intake.js", "js/bid-model.js", "js/library-core.js"]

MUTATIONS = {
    "migrate stops carrying the keys it does not know": (
        "js/bid-model.js", "return carryUnknownKeys(out, model);", "return out;",
        lambda r: r["fixtures"]["synthetic"]["synthetic_tabs"]["missing"] == ["tabs"]
        and r["intake"]["cross"]["tabsAfterEstimate"] != r["intake"]["cross"]["tabsBefore"]),
    "the known-key list forgets a key the branch normalises": (
        "js/bid-model.js", '"distance", "fees_default"]);', '"fees_default"]);',
        lambda r: r["known"]["exported"] != r["known"]["keys"]),
    "a hostile key reaches the model": (
        "js/bid-model.js", "return copyInto(out, Object.fromEntries(rest));",
        "return Object.assign(out, Object.fromEntries(rest));",
        lambda r: r["hostile"]["protoIsObjectPrototype"] is False),
    "the pagehide flush forgets the library's dye and joint filler lines": (
        "js/polish-estimate.js", "B.buildSavePatch(M, cur, { bid: bid(), library: conditionLibrary() })",
        "B.buildSavePatch(M, cur, { bid: bid() })",
        lambda r: r["estimate"]["library"]["equal"] is False
        and "Polish!C25" in r["estimate"]["library"]["diff"]),
    "the pagehide flush saves the priced area again, as it did before": (
        "js/polish-estimate.js", "B.buildSavePatch(M, cur, { bid: bid(), library: conditionLibrary() })));",
        "Object.assign(B.buildSavePatch(M, cur, { bid: bid(), library: conditionLibrary() }), { polish_sf: bid().sf })));",
        lambda r: r["estimate"]["onlyRowOff"]["equal"] is False and r["estimate"]["onlyRowOff"]["settled"] is False
        and r["estimate"]["typed"]["settled"] is True),
    "a save keeps the priced area when the only row is off": (
        "js/bid-model.js", "polish_sf: b.sf > 0 ? b.sf : measuredSf(model.takeoff),", "polish_sf: b.sf,",
        lambda r: r["savePatch"]["floor"]["saved"] == 0 and r["estimate"]["onlyRowOff"]["autosave"]["polish_sf"] == 0),
    "a save forgets the condition cells": (
        "js/bid-model.js", "cell_values: conditionCellWrites(model.conditions, cells, ctx.library, types.isSplit(state)),",
        "cell_values: cells,",
        lambda r: r["savePatch"]["cells"]["taxable"] is None
        and (r["estimate"]["condition"]["autosave"]["cells"] or {}).get("Epoxy!B6") != "No"),
    "a save edits the model it was handed": (
        "js/bid-model.js", "polish_estimate: Object.assign(copyInto({}, model), { totals: b }),",
        "polish_estimate: Object.assign(model, { totals: b }),",
        lambda r: r["savePatch"]["modelCopied"] is False and r["savePatch"]["frozenThrew"] is not None),
    "a patch overwrites what the intake does not own": (
        "js/bid-model.js", "var p = isObject(patch) ? patch : {};",
        "var p = isObject(patch) ? patch : {}; copyInto(model, p);",
        lambda r: r["patch"]["smuggledRestDiff"] is not None),
    "a patch states labor on a bid that never stated it": (
        "js/bid-model.js", "if (laborUnstated(existing)) delete model.labor;", "void 0;",
        lambda r: r["patch"]["mint"]["undef"]["hasLabor"] is True),
    "the intake rebuilds the model from nothing": (
        "js/polish-intake.js", "var model = B.patchModel(cur.polish_estimate, {", "var model = B.patchModel({}, {",
        lambda r: r["intake"]["alone"]["takeoffKept"] is False and r["intake"]["alone"]["tabsIdentical"] is False),
    "an estimate save stops carrying what the model holds": (
        "js/bid-model.js", "polish_estimate: Object.assign(copyInto({}, model), { totals: b }),",
        "polish_estimate: { version: 2, takeoff: model.takeoff, labor: model.labor, conditions: model.conditions, contingency: model.contingency, fees: model.fees, travel: model.travel, totals: b },",
        lambda r: "tabs" not in r["estimate"]["withTabs"]["autosave"]["modelKeys"]
        and r["intake"]["cross"]["tabsAfterIntake"] != r["intake"]["cross"]["tabsBefore"]),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_the_laws_go_red_when_the_code_changes(tmp_path, name):
    """Each change is the kind a refactor makes by accident, applied to a scratch copy of the page
    files and the core. The anchor must be in the file exactly once (break_source refuses otherwise)."""
    rel, old, new, noticed = MUTATIONS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, SCRATCH_FRONTEND_FILES)      # and what each declares it needs: js/excel-math.js
    # the intake prelude reads the county table out of the backend module that serves it
    (tmp_path / "backend").mkdir(exist_ok=True)
    shutil.copyfile(BACKEND / "reference_tax.py", tmp_path / "backend" / "reference_tax.py")
    got = _run(frontend)
    assert noticed(got), "the laws did not notice: " + name
