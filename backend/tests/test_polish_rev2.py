"""POLISH REV 2 (Phase 17): Kyle's Polish fixes for NEW bids, and only new bids.

Hanz decided on 2026-10-07 that the fixes to the Polish tab apply to bids made from now on, and that a saved bid keeps
its total. This file holds the whole change to that:

  1. THE TOOLING. A new Polish bid charges what Kyle's tab charges for tooling and consumables (D51 to D55): a $150
     minimum, the per-square-foot tooling the validation tab sets by size and polish system, slurry hardener and plastic.
     bid-model.js polishTooling is held to the tab on 1,008 recorded cases, to the cent
     (fixtures/polish_tooling_oracle.json, recorded by js/polish-tooling-oracle.js from the real workbook).
  2. THE PROFILE. `polish-rev2@1` (js/bid-profiles.js) is `polish-legacy` with the tooling line in the sub-total and the
     remodel tax on the sheet's base. Held to the workbook oracle's Polish vectors with `oracle-polish-harness.js --rev2`:
     the three departures it closes (tooling, remodel base, lodging nights) have to EQUAL the sheet on every case, and
     what is left to differ is the hard bid and the bond, which are decisions.
  3. WHO GETS IT. A new bid's root is stamped when it is seeded and a saved bid never is, so every saved bid prices as it
     always did (js/polish-rev2-model-harness.js, and the page's own record in fixtures/save_patch_golden.json).

Every check here goes red when the change it guards is taken out: the last tests of each part break a scratch copy of the
code and require the facts to move.
"""
import json
import pathlib
import subprocess

import pytest

import _oracle_support as S
from _golden_support import break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
FRONTEND = TESTS.parents[1] / "frontend"
TOOLING_HARNESS = TESTS / "js" / "polish-tooling-harness.js"
ORACLE_HARNESS = TESTS / "js" / "oracle-polish-harness.js"
MODEL_HARNESS = TESTS / "js" / "polish-rev2-model-harness.js"
GOLDEN_HARNESS = TESTS / "js" / "save-patch-golden-harness.js"
TOOLING_ORACLE = TESTS / "fixtures" / "polish_tooling_oracle.json"
GOLDEN = TESTS / "fixtures" / "save_patch_golden.json"
MODEL = "js/bid-model.js"
PROFILES = "js/bid-profiles.js"
PAGE = "js/polish-estimate.js"
REV2 = "polish-rev2@1"
PAGE_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js",
              "js/bid-profiles.js", "js/markup-core.js", "js/library-core.js", "js/library-picker.js",
              "js/work-types.js", "js/excel-math.js", "js/epoxy-takeoff.js", "js/gyp-takeoff.js"]


def run(script, frontend=None, *flags):
    require_node()
    args = ([str(frontend)] if frontend else []) + list(flags)
    proc = run_node(script, *args)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-4000:]
    return last_json_line(proc.stdout)


def broken(tmp_path, rel, old, new, script, *flags):
    frontend = break_source(tmp_path, rel, old, new, also=[MODEL])
    copy_unmodified(frontend, PAGE_FILES)
    return run(script, frontend, *flags)


# ═══ 1. the tooling, held to Kyle's tab ═══════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def tooling():
    return run(TOOLING_HARNESS)


def test_the_model_charges_the_tooling_the_tab_charges_to_the_cent(tooling):
    assert tooling["mismatches"] == [] and "bad" not in tooling, tooling["mismatches"][:2]
    assert tooling["cases"] == 1056
    assert tooling["exact"] == tooling["cases"] - tooling["noArea"]["cases"] == 1008


def test_the_recorded_cases_move_every_line_of_the_block(tooling):
    """A line that no case moves is a line nothing checks: the $150 floor both binding and not, the slurry, the plastic,
    and the plastic's renovation leg both reached (5,000 SF and up) and idle (under it)."""
    seen = tooling["seen"]
    for key in ("consumablesAtMinimum", "consumablesAboveMinimum", "slurry", "plastic", "plasticRenoLegOnTheSheet",
                "plasticRenoLegIdleUnder5k"):
        assert seen.get(key, 0) >= 40, (key, seen)


def test_the_polish_system_is_read_from_the_takeoff_the_way_the_sheet_reads_it(tooling):
    s = tooling["system"]
    sp, full, cream = {"system": "sp", "traditional": False}, {"system": "full", "traditional": False}, \
        {"system": "cream", "traditional": False}
    assert s["none"] == s["empty"] == s["sp"] == s["salt"] == sp, "no named system is the template's own, salt and pepper"
    assert s["cream"] == cream and s["aggregate"] == full
    assert s["firstNamedWins"] == cream, "the first row that names a system decides"
    assert s["traditional"] == {"system": "sp", "traditional": True}, "'traditional' marks the kind, not the system"
    assert s["offRowIgnored"] == full, "a switched-off row names nothing"


def test_the_root_tooling_follows_the_system_and_the_dye_condition(tooling):
    r = tooling["root"]
    assert r["rev2"] == r["rev2ByHand"] == 5280
    assert r["rev2Dye"] == r["rev2DyeByHand"] == 2146, "Dye's plastic reaches the root's tooling through the model's conditions"
    assert r["rev2Cream"] == r["rev2CreamByHand"], "the root reads the system the takeoff names"
    assert r["rev2Cream"] < r["rev2"], "cream over 7,000 SF is cheaper than salt and pepper"
    assert r["rev2Traditional"] == r["rev2TraditionalByHand"] > r["rev2"], "a traditional polish adds its per-SF charge"


def test_a_bid_with_no_area_is_the_one_case_the_model_does_not_copy(tooling):
    """The sheet charges its $150 even for no square footage; the model charges nothing, as Epoxy's tooling does, so an
    Epoxy-only job's empty Polish root carries no $150. Every no-area case shows the sheet's minimum, and none shows the model's."""
    none = tooling["noArea"]
    assert none["cases"] == 48 and none["sheetMinimum"] == 48 and none["modelCharges"] == 0


def test_the_cells_the_oracle_was_recorded_from_are_still_the_templates():
    """The recorded answers say nothing if Kyle changes the tooling block. Read each cell the model's constants came from
    back out of the template."""
    from test_workbook_formula_pins import _index
    polish, validation = _index("Polish"), _index("validation")
    want_formula = {
        "D51": ["ROUNDUP", "IF((B51*C51)>150,(B51*C51),150)"], "C51": ["SUM(V10:W10)", "*1.08"], "B51": ["B35"],
        "D52": ["B52*C52"], "D53": ["B53*C53"], "B53": ["ROUNDUP(B35/5000,0)"],
        "D54": ["B54*C54"], "B54": ['IF(E25="yes",D35,IF(B35>4999,IF(B10="reno",D35)))'],
        "D55": ["SUM(D50:D54)"], "W10": ['IF(G36="traditional",V16,0)'],
        "V10": ['IF(F36="cream",V13,IF(F36="S&P",V14,IF(F36="full",V15,0.25)))'],
        "V13": ["$E$18<=4000", "$E$18<7000", "validation!$E$32", "validation!$E$33", "validation!$E$34"],
        "V14": ["$E$18<=4000", "$E$18<7000", "validation!$I$32", "validation!$I$33", "validation!$I$34"],
        "V15": ["$E$18<=4000", "$E$18<7000", "validation!$M$32", "validation!$M$33", "validation!$M$34"],
    }
    for addr, pieces in want_formula.items():
        kind, text = polish.get(addr, ("empty", None))
        assert kind == "formula", (addr, kind)
        for piece in pieces:
            assert piece in text, (addr, "no longer says", piece, text)
    # the constants the model carries
    constants = {"C52": 0.33, "C53": 210, "C54": 0.25, "V16": 0.2}
    for addr, value in constants.items():
        assert polish.get(addr) == ("value", value), (addr, polish.get(addr))
    cream, sp, full = ("E", "I", "M")
    model = {"cream": [0.6, 0.2, 0.2], "sp": [0.85, 0.4, 0.45], "full": [1.5, 0.65, 0.75]}
    for col, name in ((cream, "cream"), (sp, "sp"), (full, "full")):
        got = [validation.get(col + str(row)) for row in (32, 33, 34)]
        assert got == [("value", v) for v in model[name]], (name, got)


def test_the_models_constants_are_the_ones_the_pins_above_read():
    node = require_node()
    # the constants live in one object, and this is that object read from the model itself
    code = ("const M=require(%s);console.log(JSON.stringify(M.POLISH_TOOLING))" % json.dumps(str(FRONTEND / "js" / "bid-model.js")))
    got = json.loads(subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=60).stdout)
    assert got["rates"] == {"cream": [0.6, 0.2, 0.2], "sp": [0.85, 0.4, 0.45], "full": [1.5, 0.65, 0.75]}
    assert got["min"] == 150 and got["slurryBag"] == 210 and got["slurryEverySf"] == 5000 and got["plasticPerLf"] == 0.25
    assert got["markup"] == 1.08 and got["traditionalPerSf"] == 0.2 and got["tiers"] == [4000, 7000] and got["plasticFromSf"] == 4999


TOOLING_BREAKS = {
    "the $150 minimum moves": (
        "    tiers: [4000, 7000], traditionalPerSf: 0.2, markup: 1.08, min: 150, demoPerSf: 0.33,",
        "    tiers: [4000, 7000], traditionalPerSf: 0.2, markup: 1.08, min: 100, demoPerSf: 0.33,"),
    "a bag of slurry hardener costs $200": (
        "    slurryEverySf: 5000, slurryBag: 210, plasticPerLf: 0.25, plasticFromSf: 4999, defaultSystem: \"sp\"",
        "    slurryEverySf: 5000, slurryBag: 200, plasticPerLf: 0.25, plasticFromSf: 4999, defaultSystem: \"sp\""),
    "a bag covers 4,000 SF": (
        "    slurryEverySf: 5000, slurryBag: 210, plasticPerLf: 0.25, plasticFromSf: 4999, defaultSystem: \"sp\"",
        "    slurryEverySf: 4000, slurryBag: 210, plasticPerLf: 0.25, plasticFromSf: 4999, defaultSystem: \"sp\""),
    "plastic is charged for Dye only": (
        "    var plasticLf = (o.dye || (area > T.plasticFromSf && o.reno)) ? run : 0;",
        "    var plasticLf = o.dye ? run : 0;"),
    "plastic is $0.30 a foot": (
        "    slurryEverySf: 5000, slurryBag: 210, plasticPerLf: 0.25, plasticFromSf: 4999, defaultSystem: \"sp\"",
        "    slurryEverySf: 5000, slurryBag: 210, plasticPerLf: 0.3, plasticFromSf: 4999, defaultSystem: \"sp\""),
    "the first size tier is under 4,000 and not up to it": (
        "    var tier = area <= T.tiers[0] ? 0 : (area < T.tiers[1] ? 1 : 2);",
        "    var tier = area < T.tiers[0] ? 0 : (area < T.tiers[1] ? 1 : 2);"),
    "salt and pepper over 7,000 SF costs a nickel more": (
        "    rates: { cream: [0.6, 0.2, 0.2], sp: [0.85, 0.4, 0.45], full: [1.5, 0.65, 0.75] },",
        "    rates: { cream: [0.6, 0.2, 0.2], sp: [0.85, 0.4, 0.5], full: [1.5, 0.65, 0.75] },"),
    "a traditional polish adds nothing": (
        "    var rate = (T.rates[system][tier] + (o.traditional ? T.traditionalPerSf : 0)) * T.markup;",
        "    var rate = (T.rates[system][tier]) * T.markup;"),
    "the eight percent is left off": (
        "    var rate = (T.rates[system][tier] + (o.traditional ? T.traditionalPerSf : 0)) * T.markup;",
        "    var rate = (T.rates[system][tier] + (o.traditional ? T.traditionalPerSf : 0));"),
    "the consumables are not rounded up": (
        "    var consumables = roundUp(perSf > T.min ? perSf : T.min);",
        "    var consumables = perSf > T.min ? perSf : T.min;"),
}


@pytest.mark.parametrize("name", sorted(TOOLING_BREAKS))
def test_the_tooling_check_goes_red_when_the_model_changes(tmp_path, name):
    old, new = TOOLING_BREAKS[name]
    got = broken(tmp_path, MODEL, old, new, TOOLING_HARNESS)
    assert got.get("bad", 0) > 0, "the tooling oracle did not notice: " + name


# ═══ 2. the profile, held to the workbook oracle ═══════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def rev2():
    return run(ORACLE_HARNESS, None, "--rev2")


@pytest.fixture(scope="module")
def departures():
    return json.loads((S.ORACLE / "departures.json").read_text(encoding="utf-8"))


def test_rev2_equals_the_oracle_except_the_two_decisions(rev2):
    assert rev2["profile"] == REV2
    assert rev2["chain"]["unexplained"] == [] and rev2["lodging"]["unexplained"] == []
    assert rev2["chain"]["vectors"] >= 170 and rev2["lodging"]["vectors"] == 8
    assert rev2["lodging"]["exact"] == 8, "every lodging case, mixed rates included, is the sheet's to the dollar"


def test_what_is_left_to_differ_is_the_hard_bid_and_the_bond_and_each_is_seen(rev2):
    assert sorted(rev2["departures"]) == ["bond-is-not-an-input", "hard-bid-removed"]
    for name, seen in rev2["departures"].items():
        assert seen["seen"] >= 1 and seen["applies"] >= seen["seen"], name


def test_each_departure_rev2_closes_is_equal_to_the_sheet_on_every_case_it_applied_to(rev2, departures):
    """`clean` is the cases where the closed departure applied and no open one did, so any difference there is the closed
    one's. None may differ, and there have to be cases to say so."""
    closed = {d["id"] for d in departures["departures"] if d.get("closedBy") == REV2}
    assert closed == {"tooling-is-zero", "remodel-base-widened", "lodging-by-man-days"}
    assert set(rev2["closed"]) == closed
    for name, c in rev2["closed"].items():
        assert c["differ"] == 0, (name, c)
        assert c["clean"] >= 1 and c["applies"] >= c["clean"], (name, c)
    assert rev2["closed"]["tooling-is-zero"]["clean"] >= 50 and rev2["closed"]["remodel-base-widened"]["clean"] >= 20


def test_the_legacy_model_still_differs_where_it_always_did(departures):
    """Saved bids keep their totals, so polish-legacy still departs from the sheet on all five, each one seen. The
    ordinary run (test_polish_model_vs_oracle.py) holds this; here it is stated beside rev2's."""
    legacy = run(ORACLE_HARNESS)
    assert legacy["profile"] == "polish-legacy@1" and legacy["chain"]["unexplained"] == []
    assert set(legacy["departures"]) == {d["id"] for d in departures["departures"]}
    assert all(v["seen"] >= 1 for v in legacy["departures"].values())
    assert legacy["closed"] == {}


def test_departures_json_marks_the_three_and_records_what_rev2_still_does_on_purpose(departures):
    marked = [d["id"] for d in departures["departures"] if d.get("closedBy")]
    assert marked == ["tooling-is-zero", "remodel-base-widened", "lodging-by-man-days"]
    assert all(d["closedBy"] == REV2 for d in departures["departures"] if d.get("closedBy"))
    # the two that are decisions are not closed
    assert not any(d.get("closedBy") for d in departures["departures"] if d["id"] in ("hard-bid-removed", "bond-is-not-an-input"))
    ids = [d["id"] for d in departures["decisions"]]
    assert ids == ["lodging-quantity-is-typed", "tooling-needs-an-area", "polish-system-is-read-from-the-takeoff",
                   "plastic-has-no-renovation-leg", "remodel-rate-floor"]
    for d in departures["decisions"]:
        assert len(d["reason"]) > 120, d["id"]
    assert "closedBy" in departures["about"] and "polish-rev2@1" in departures["about"]


REV2_BREAKS = {
    "rev2 drops the tooling from the sub-total": (
        PROFILES, 'quirks: { toolingInSubTotal: true, remodelBase: "sheet" }',
        'quirks: { toolingInSubTotal: false, remodelBase: "sheet" }', "tooling-is-zero"),
    "rev2 takes the remodel tax on the narrow base": (
        PROFILES, 'quirks: { toolingInSubTotal: true, remodelBase: "sheet" }',
        'quirks: { toolingInSubTotal: true, remodelBase: "model" }', "remodel-base-widened"),
    "rev2 counts nights in people-days": (
        MODEL, "    return engine.lodgingNights(REV2, roundUp(laborTotal(rows, conditions)), travelLabor, rate || SHIPPED_LABOR_RATE);",
        "    return travelManDays(rows);", "lodging-by-man-days"),
    "rev2 forgets to ask for the sheet's nights": (
        MODEL, "    if (opts && opts.sheetNights) return sheetNights(rows, opts.conditions);",
        "    void opts;", "lodging-by-man-days"),
    "the nights are divided by ten hours": (
        "js/bid-engine.js", "    return ((num(labor) - num(travelLabor)) / rate) / quirks.lodgingDivisor;",
        "    return ((num(labor) - num(travelLabor)) / rate) / 10;", "lodging-by-man-days"),
}


@pytest.mark.parametrize("name", sorted(REV2_BREAKS))
def test_the_rev2_check_goes_red_when_a_departure_it_closed_opens_again(tmp_path, name):
    rel, old, new, closed = REV2_BREAKS[name]
    got = broken(tmp_path, rel, old, new, ORACLE_HARNESS, "--rev2")
    noticed = (got["closed"][closed]["differ"] > 0 or got["chain"]["unexplained"] or got["lodging"]["unexplained"])
    assert noticed, "the rev2 oracle run did not notice: " + name
    # and it is the departure that opened that is seen, not some other
    if closed == "lodging-by-man-days":
        assert got["lodging"]["unexplained"] or got["closed"][closed]["differ"] > 0
    else:
        assert got["closed"][closed]["differ"] > 0


def test_rev2_is_a_profile_that_extends_legacy_and_states_only_what_it_changes():
    require_node()
    profiles = S.profiles()
    rev2 = profiles["profiles"]["polish-rev2"]
    assert rev2["extends"] == "polish-legacy" and rev2["layout"] == "polish" and rev2["rev"] == 1
    assert rev2["quirks"] == {"toolingInSubTotal": True, "remodelBase": "sheet"} and "rates" not in rev2
    # the quirk list did not grow: nothing reads a name nobody declared
    assert len(profiles["quirks"]) == 13


# ═══ 3. who gets it ═════════════════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def model():
    return run(MODEL_HARNESS, FRONTEND)


@pytest.mark.parametrize("part", ["stamping", "rootProfile", "chain", "pricing", "nights"])
def test_no_part_of_the_model_harness_failed(model, part):
    assert "error" not in model[part], model[part].get("error")


def test_a_new_bid_is_stamped_rev2_and_a_saved_bid_never_is(model):
    s = model["stamping"]
    assert s["newBid"] == REV2 and s["combo"] == REV2, "a new Polish bid, and a new Combo's Polish section, are rev2"
    assert s["comboEpoxySection"] == "epoxy@1", "the other sections keep their own profile"
    assert s["savedAfterSeed"] is None and s["savedHasNoKey"], "seeding a saved bid writes nothing: the gates are shut"
    assert s["epoxyOnlyRoot"] is None, "an Epoxy-only bid's root is off and is not a Polish bid"
    assert s["keptTheKeyItHad"] == "polish-legacy@1", "a profile already on the model is never overwritten"
    assert s["newBidSections"] == [["Polish", REV2]]


def test_a_polish_section_brought_in_by_a_job_type_change_is_new_only_if_it_never_held_a_takeoff(model):
    s = model["stamping"]
    assert s["liftedEmptyRoot"] == REV2, "an Epoxy bid switched to Polish gets a Polish section that is new"
    assert s["liftedUsedRoot"] is None, "a root that was priced before comes back as it was"


def test_the_root_reads_exactly_one_stamp_and_every_other_value_is_legacy(model):
    r = model["rootProfile"]
    assert r["rev2"] == REV2 and r["none"] == r["legacy"] == "polish-legacy@1"
    for junk in ("reserved", "laterRev", "junk", "nullKey"):
        assert r[junk] == "polish-legacy@1", junk
    assert r["markupChainNoStamp"] is None, "no stamp is the legacy chain every older caller means"
    assert "polish-legacy@1 or polish-rev2@1" in r["markupChainUnknown"], "an unknown stamp is refused, never priced as something else"
    assert "needs a profile stamp" in r["markupChainBadArg"]


def test_the_chain_charges_tooling_and_the_wider_remodel_base_on_rev2_only(model):
    c = model["chain"]
    assert c["legacyIgnoresTooling"] and c["legacyStampSame"] and not c["legacyKeys"], "legacy: no tooling, and no tooling key"
    assert c["rev2Keys"] and c["rev2Tooling"] == 700 and c["rev2SubTotalMinusLegacy"] == 700
    assert c["modelNamesTheProfile"], "handing the model names the same profile as handing its stamp"
    assert c["rev2Tax"] == c["rev2TaxByHand"] and c["legacyTax"] == c["legacyTaxByHand"]
    assert c["rev2Tax"] > c["legacyTax"], "the sheet's base is wider: tooling and travel are in it"


def test_a_saved_bid_prices_exactly_as_before_and_a_stamped_one_carries_the_sheets_tooling(model):
    p = model["pricing"]
    assert p["savedProfile"] == "polish-legacy@1" and p["stampedProfile"] == REV2
    assert p["savedTooling"] == 0 and p["rootToolingSaved"] == 0
    assert p["savedSubTotal"] == p["savedSubTotalByHand"], "material, labor and travel only"
    assert p["sameAsMarkupChain"], "pricing the unstamped root is the legacy markupChain, figure for figure"
    assert p["stampedTooling"] == p["toolingByHand"] == p["rootToolingStamped"] == 5280
    assert p["stampedSubTotal"] == p["stampedSubTotalByHand"] == p["savedSubTotal"] + 5280
    assert p["noAreaTooling"] == 0, "no area, no tooling"


def test_nights_are_counted_from_labor_dollars_the_sheets_way_on_rev2_only(model):
    n = model["nights"]
    assert n["mixedPeopleDays"] == 19 and n["mixedSheet"] == pytest.approx(5496 / 33 / 8)
    assert n["withTravelSheet"] == n["withTravelPeople"] == 15, "travel labor is not nights"
    assert n["firstRowRate"] == 3, "the first crew row's rate is the sheet's C37"
    assert n["noRows"] == 0 and n["offRowLeftOut"] == 15
    assert n["autoSheet"] > n["autoLegacy"], "mixed rates: the sheet counts more nights than there are people-days"
    assert n["typedLegacy"] == n["typedSheet"] == 505, "a typed quantity is the estimator's, whatever the profile"
    assert n["optsLegacyRoot"] and n["optsRev2Root"] and n["optsRev2Section"]
    # 3 guys x 5 days at $33 = 15 nights; Remove Existing Joint Filler adds a 4th hand (5 more nights) to the dollars
    assert n["optsConditionsNights"] == {"on": 2000, "off": 1500}, "travelOpts hands the model's conditions to the night count"
    assert n["engineByHand"] == pytest.approx(5496 / 33 / 8) and n["engineBadRate"] == 0 and n["engineGyp"] == 10
    assert n["hintLegacy"] == "Man-days from the tasks above: 19."
    assert n["hintRev2"] == "Nights from the labor above, as the sheet counts them: 20.82."
    assert n["hintRev2SameRate"] == "Man-days from the tasks above: 15.", "while the counts agree the words are the usual ones"
    assert n["hintRev2Auto"] == "Nights counted from the labor above, as the sheet does."
    assert n["hintRev2OtherSection"] == n["hintLegacy"]


MODEL_BREAKS = {
    "a new bid is not stamped": (
        MODEL, "    if ((laborGate || condGate) && now().some(function (e) { return e.root; }) && out.profile === undefined) out.profile = REV2.stamp;",
        "    void REV2;",
        lambda m: m["stamping"]["newBid"] != REV2),
    "a saved bid is stamped too": (
        MODEL, "    if ((laborGate || condGate) && now().some(function (e) { return e.root; }) && out.profile === undefined) out.profile = REV2.stamp;",
        "    if (now().some(function (e) { return e.root; }) && out.profile === undefined) out.profile = REV2.stamp;",
        lambda m: m["stamping"]["savedAfterSeed"] == REV2),
    "any profile key at the root is read": (
        MODEL, "    return isObject(model) && model.profile === REV2.stamp ? REV2 : LEGACY;",
        "    return isObject(model) && model.profile ? REV2 : LEGACY;",
        lambda m: m["rootProfile"]["junk"] == REV2 or m["rootProfile"]["reserved"] == REV2),
    "a legacy bid is charged tooling": (
        MODEL, "    if (!rootProfile(model).quirks.toolingInSubTotal) return 0;",
        "    void rootProfile;",
        lambda m: m["pricing"]["rootToolingSaved"] != 0 or m["pricing"]["savedTooling"] != 0 or m["pricing"]["sameAsMarkupChain"] is False),
    "the root is always priced by legacy": (
        MODEL, "                 layout: \"polish\", kind: rootKind, profile: rootProfile(model).stamp, role: \"polish\" }];",
        "                 layout: \"polish\", kind: rootKind, profile: LEGACY.stamp, role: \"polish\" }];",
        lambda m: m["pricing"]["stampedProfile"] != REV2),
    "a lifted root is never stamped": (
        MODEL, "    if (rootLifted && out.profile === undefined && !takeoffStated(out.takeoff)) out = Object.assign({}, out, { profile: REV2.stamp });",
        "    void REV2;",
        lambda m: m["stamping"]["liftedEmptyRoot"] != REV2),
    "a used root coming back is stamped": (
        MODEL, "    if (rootLifted && out.profile === undefined && !takeoffStated(out.takeoff)) out = Object.assign({}, out, { profile: REV2.stamp });",
        "    if (rootLifted && out.profile === undefined) out = Object.assign({}, out, { profile: REV2.stamp });",
        lambda m: m["stamping"]["liftedUsedRoot"] == REV2),
    "an unknown stamp is priced as legacy": (
        MODEL, '      throw new Error("markupChain prices the Polish root with " + LEGACY.stamp + " or " + REV2.stamp + ", not " + JSON.stringify(which));',
        "      return LEGACY;",
        lambda m: m["rootProfile"]["markupChainUnknown"] is None),
    "the chain leaves tooling out of the answer": (
        MODEL, "    if (profile.quirks.toolingInSubTotal) out.tooling = r.tooling;",
        "    void r;",
        lambda m: not m["chain"]["rev2Keys"]),
    "a saved bid's lodging hint says nights": (
        MODEL, "    if (!opts) return manDaysHint(auto, travelManDays(rows));",
        "    if (!opts) return \"Nights from the labor above, as the sheet counts them: 0.\";",
        lambda m: m["nights"]["hintLegacy"] != "Man-days from the tasks above: 19."),
}


@pytest.mark.parametrize("name", sorted(MODEL_BREAKS))
def test_the_model_checks_go_red_when_the_code_changes(tmp_path, name):
    rel, old, new, noticed = MODEL_BREAKS[name]
    got = broken(tmp_path, rel, old, new, MODEL_HARNESS)
    assert noticed(got), "the checks did not notice: " + name


# ═══ 4. the page: every saved bid as it was, every new bid stamped ═════════════════════════════════════════════
@pytest.fixture(scope="module")
def page():
    return run(GOLDEN_HARNESS, FRONTEND)


def test_the_page_saves_every_saved_bid_as_it_did_and_stamps_every_new_one(page):
    """The REAL page (polish-estimate.js, whole) over the 26 saved-bid fixtures the ratchet pins and seven new or part-saved
    bids. A saved bid's model has no `profile` and its bid no `tooling`, and the whole record equals the one cut from
    origin/staging 28a5d1f; a new bid's model carries polish-rev2@1 and its bid carries the tooling its area works out to."""
    want = json.loads(GOLDEN.read_text(encoding="utf-8"))["golden"]
    assert json.dumps(page["saved"]) == json.dumps(want["saved"]), "a saved bid's save moved"
    assert len(page["saved"]) == 26
    for name, rec in page["saved"].items():
        for key, blob in rec.items():
            text = json.dumps(blob)
            assert "polish-rev2" not in text, (name, key)
    stamped = {n: r for n, r in page["newBid"].items() if r["model"].get("profile") == REV2}
    assert set(stamped) == set(page["newBid"]) - {"savedEmptyTakeoff"}
    assert "profile" not in page["newBid"]["savedEmptyTakeoff"]["model"], "a bid that was already saved is not stamped"
    for name, rec in stamped.items():
        assert rec["saved"]["polish_estimate"]["profile"] == REV2, name
        tooling = rec["bid"]["tooling"]
        assert tooling == 0 if name == "noSf" else tooling >= 150 + 210, (name, tooling)
        assert rec["saved"]["polish_estimate"]["totals"]["tooling"] == tooling, name


# Since Sheets phase 1 the page's bid() hands the root to the model's polishBid, so the two lines that make the page
# price the root by its profile, with its tooling, are the model's. The recorded page is still what must notice.
PAGE_BREAKS = {
    "the page leaves the tooling out of the bid": (
        MODEL, "      tooling: profile.quirks.toolingInSubTotal ? takeoffTooling(s.takeoff, model.conditions) : 0,",
        "      tooling: 0,"),
    "the page prices every root as legacy": (
        MODEL, "    }, profile.stamp);", "    }, LEGACY.stamp);"),
}


@pytest.mark.parametrize("name", sorted(PAGE_BREAKS))
def test_the_page_check_goes_red_when_the_page_stops_using_the_profile(tmp_path, name):
    rel, old, new = PAGE_BREAKS[name]
    got = broken(tmp_path, rel, old, new, GOLDEN_HARNESS)
    want = json.loads(GOLDEN.read_text(encoding="utf-8"))["golden"]
    assert json.dumps(got) != json.dumps(want), "the recorded page did not notice: " + name
