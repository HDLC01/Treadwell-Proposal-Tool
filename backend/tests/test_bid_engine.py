"""The bid engine (frontend/js/bid-engine.js) and the profiles it prices with (frontend/js/bid-profiles.js, part two),
held to Kyle's workbook as the oracle recorded it (Phase 8 of the v2 estimating program).

WHAT IS PROVED, and where each half lives.

  * `tests/js/bid-engine-harness.js` runs `priceChain` with the profile that prices each of the eleven priced tabs on
    every chain and lodging case the oracle recorded for that tab (1,993 cases, backend/tests/fixtures/oracle/) and
    compares every answer the two share. They are EQUAL to the dollar. The only profile with departures is
    `polish-legacy`, which is what the v2 model has always charged, and its differences from the sheet are exactly
    fixtures/oracle/departures.json, case by case.
  * Every quirk flag a profile can carry is turned the other way, on every tab, and the answers go red somewhere:
    a flag nothing proves would be a rule nobody tests.
  * Every odd rule of docs/kyle-workbook-odd-rules.md that lives in the chain is exercised: on the recorded cases the
    ordinary reading gives a different figure than the sheet does, and the engine gives the sheet's.
  * A profile's rates, ladders, tiers, hard bid and Gyp soft costs are Markups formula text. Each is evaluated beside
    the workbook's own cell formula over every edge of that formula, and the two agree everywhere.
  * `tests/js/bid-engine-units-harness.js` is the engine's own behaviour: `extends`, reading a filed rule, what is
    unpriceable, combining tabs, and every call that must throw.

THE LAST SECTION BREAKS THE CODE. Each mutation is applied to a scratch copy of the engine or of the profiles and the
same checks must go red, BY NAME. break_source refuses a mutation that applied nowhere, so none can pass by doing
nothing.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil

import pytest

import _oracle_support as S
from _golden_support import FRONTEND, break_source
from _node import last_json_line, require_node, run_node

HARNESS = S.TESTS / "js" / "bid-engine-harness.js"
UNITS = S.TESTS / "js" / "bid-engine-units-harness.js"
ENGINE = "js/bid-engine.js"
PROFILES = "js/bid-profiles.js"
MODEL = "js/bid-model.js"
# What a scratch frontend needs besides the one file under test: the harness loads all of these.
ALSO = (MODEL, ENGINE, PROFILES, "js/work-types.js", "js/markup-core.js", "js/excel-math.js")


def _drive(script, frontend=None):
    require_node()
    proc = run_node(script, *([frontend] if frontend else []))
    assert proc.returncode == 0, "the harness itself failed, read this before assuming a product bug:\n" \
        + proc.stdout[-1500:] + proc.stderr[-3000:]
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    return _drive(HARNESS)


@pytest.fixture(scope="module")
def units():
    return _drive(UNITS)


def _priced_tabs():
    """The eleven priced tabs, as bid-profiles.js lists them. Empty where node is missing (every test here then skips)."""
    if shutil.which("node") is None:
        return []
    return S.profiles()["priced"]


PRICED_TABS = _priced_tabs()


# ── the checks. Each returns what is wrong, as sentences, so the same check is a test and a mutation target ──
def check_tabs(ran):
    out = []
    for tab, rec in ran["tabs"].items():
        if rec.get("bad") or rec["exact"] != rec["vectors"]:
            first = rec["mismatches"][0] if rec["mismatches"] else {}
            out.append("%s (%s): %s of %s cases differ from the workbook, first %s"
                       % (tab, rec["profile"], rec.get("bad"), rec["vectors"], json.dumps(first)[:300]))
    return out


# The one flag the chain never reads: a crew day's hours belong to the labor rows, and the oracle pins the profile's
# figure to the tab's own cell instead (check_pins).
UNREAD_BY_THE_CHAIN = {"dayHours"}


def check_flips(ran):
    out = []
    totals = {}
    for key, changed in ran["flips"].items():
        quirk = key.split(" / ")[1]
        totals[quirk] = totals.get(quirk, 0) + changed
    for quirk, changed in sorted(totals.items()):
        if quirk in UNREAD_BY_THE_CHAIN:
            if changed:
                out.append("%s is not read by the chain, yet flipping it moved %d cases" % (quirk, changed))
        elif not changed:
            out.append("flipping %s changed no answer on any tab: nothing proves it" % quirk)
    return out


def check_pins(ran):
    bad = [p for p in ran["pins"] if p["workbook"] != p["profile"]]
    return ["%(tab)s %(fixed)s: the workbook has %(workbook)r, the profile has %(profile)r" % p for p in bad]


# The rules that live in the chain, and the rules that live before it. A rule of odd_rules.json in neither list fails.
CHAIN_RULES = {
    "bond-twice", "leveling-lodging-eight", "leveling-escalation-left-out", "epoxy-gp-without-fees",
    "gyp-escalation-always-five", "gyp-mat-shipping-truckload", "ship-tiers-inclusive-gp-strict",
}
UPSTREAM_RULES = {
    "gyp-bags-fractional": "bags and sand are worked out from the square feet in the takeoff, before the boundary the chain starts at",
    "leveling-travel-hour": "travel labor is a row of the labor table (its hours and person-days are the takeoff's); the chain takes the labor dollars",
    "leveling-overage-powders": "the overage is an input in dollars; which rows it is taken on is the takeoff's",
    "cove-aggregate-system-1": "which price the aggregate is read at is the takeoff's",
}


def check_odd_rules(ran):
    out = []
    ids = set(ran["odd"]["ruleIds"])
    if CHAIN_RULES & set(UPSTREAM_RULES):
        out.append("a rule is listed as both in the chain and upstream: %s" % sorted(CHAIN_RULES & set(UPSTREAM_RULES)))
    missing = ids - CHAIN_RULES - set(UPSTREAM_RULES)
    if missing:
        out.append("odd rules nobody has placed (in the chain, or before it): %s" % sorted(missing))
    gone = (CHAIN_RULES | set(UPSTREAM_RULES)) - ids
    if gone:
        out.append("rules placed here that odd_rules.json no longer has: %s" % sorted(gone))
    tests = ran["odd"]["testFor"]
    for rule in sorted(CHAIN_RULES):
        name = tests.get(rule)
        seen = ran["odd"]["chain"].get(name, 0) if name else 0
        if not seen:
            out.append("the odd rule %s is shown by no recorded case where the ordinary reading would differ" % rule)
    return out


def check_probes(ran):
    """The oracle's probes that start at the chain's own boundary: the sound mat's shipping at a truckload minus one, at
    it and above it, and Leveling's lodging nights with the day-length cell changed."""
    out = []
    rows = ran["probes"]
    for p in rows:
        if p["sheet"] != p["engine"] and not (isinstance(p["sheet"], float) and abs(p["sheet"] - p["engine"]) < 1e-9):
            out.append("%(tab)s %(probe)s: the sheet says %(sheet)r, the engine %(engine)r (%(rolls)r rolls)" % dict({"rolls": None}, **p))
        if "sheetDollars" in p and p["sheetDollars"] != p["engineDollars"]:
            out.append("%(tab)s %(probe)s: lodging dollars, the sheet says %(sheetDollars)r, the engine %(engineDollars)r" % p)
    mats = [p for p in rows if p["probe"] == "sound-mat-truckload"]
    if len(mats) != 15 or {p["tab"] for p in mats} != {t for t in PRICED_TABS if t.startswith("Gyp")}:
        out.append("the truckload probe was run on %d steps, not three on each of the five Gyp tabs" % len(mats))
    # the rule has to SHOW: shipping is charged below a truckload and waived at it and above it
    for tab in {p["tab"] for p in mats}:
        steps = sorted((p for p in mats if p["tab"] == tab), key=lambda p: p["rolls"])
        if [s["engine"] > 0 for s in steps] != [True, False, False]:
            out.append("%s: the sound mat does not ship free from a truckload on" % tab)
    if len([p for p in rows if p["probe"] == "lodging-divisor"]) != 2:
        out.append("Leveling's lodging probe was not run on both of its steps")
    return out


def check_departures(ran):
    d = ran["departures"]
    out = []
    if d["unexplained"]:
        out.append("polish-legacy differs from the sheet where departures.json does not say so: %s"
                   % json.dumps(d["unexplained"][:3])[:400])
    if d["exact"] + d["excused"] != d["vectors"]:
        out.append("departures: %d exact + %d excused is not %d cases" % (d["exact"], d["excused"], d["vectors"]))
    for dep_id, seen in d["seen"].items():
        if not seen:
            out.append("the declared departure %s is seen on no case: it is not a departure" % dep_id)
    return out


EXPECTED_LEGACY_KEYS = [
    "material", "shipping", "material_total", "labor", "escalation", "burden", "labor_total", "travel", "sub_total",
    "gp_pct", "gp", "super_pto", "soft_costs", "contingency", "sales_tax_pct", "sales_tax", "remodel_pct",
    "remodel_tax", "taxes", "fees", "bond", "bond_pct", "fees_and_bond", "total", "sf", "per_sf",
]


def check_wrapper(ran):
    w = ran["wrapper"]
    out = []
    if "error" in w:
        out.append("bid-model.js did not load: %s" % w["error"])
        return out
    if sorted(w["keys"]) != sorted(EXPECTED_LEGACY_KEYS):
        out.append("markupChain returns other keys than it always has: %s" % w["keys"])
    if w["differ"] or not w["compared"]:
        out.append("markupChain differs from priceChain on polish-legacy on %s of %s cases" % (w["differ"], w["compared"]))
    return out


def check_formulas(ran):
    out = []
    seen = {}
    for f in ran["formulas"]:
        seen[(f["tab"], f["line"])] = f["checked"]
        if f["bad"]:
            out.append("%s %s: a profile rate and the workbook's formula disagree, first %s" % (f["tab"], f["line"], f["bad"][0]))
    for tab in PRICED_TABS:
        if not seen.get((tab, "gp")):
            out.append("%s: the GP ladder was not compared with the workbook's formula" % tab)
    for tab in PRICED_TABS:
        if tab.startswith("Gyp") and not seen.get((tab, "soft_costs")):
            out.append("%s: the soft costs expression was not compared with the workbook's formula" % tab)
    for tab in ("Epoxy", "Epoxy blank", "Leveling"):
        if not seen.get((tab, "ship_pct")):
            out.append("%s: the shipping tiers were not compared with the workbook's formula" % tab)
    return out


def check_layouts(ran):
    return ["%(tab)s: the vocabulary says layout %(vocabulary)s, the profile prices on %(profile)s" % r
            for r in ran["layouts"] if r["vocabulary"] != r["profile"]]


def check_profiles(ran):
    return ["profile %s is not plain data" % k for k, v in ran["profiles"].items() if not v["json"]]


def all_checks(ran):
    return (check_tabs(ran) + check_flips(ran) + check_pins(ran) + check_odd_rules(ran) + check_probes(ran)
            + check_departures(ran) + check_wrapper(ran) + check_formulas(ran) + check_layouts(ran) + check_profiles(ran))


# ── the workbook, tab by tab ─────────────────────────────────────────────────
def test_the_engine_prices_every_recorded_case_exactly_as_the_workbook_does(ran):
    assert check_tabs(ran) == []


def test_every_priced_tab_was_run_and_every_recorded_case_was_compared(ran):
    assert sorted(ran["tabs"]) == sorted(PRICED_TABS) and len(PRICED_TABS) == 11
    for tab in PRICED_TABS:
        golden = S.load_golden(S.profiles()["sheets"][tab]["slug"])
        assert ran["tabs"][tab]["vectors"] == len(golden["vectors"]), tab
    assert sum(r["vectors"] for r in ran["tabs"].values()) == 1993


def test_each_tab_is_priced_by_the_profile_the_vocabulary_expects(ran):
    stamps = {tab: rec["profile"] for tab, rec in ran["tabs"].items()}
    assert stamps == {
        "Epoxy": "epoxy@1", "Polish": "polish@1", "Seal": "seal@1", "Seal (+Jnts)": "seal@1",
        "Epoxy blank": "epoxy-blank@1", "Leveling": "leveling@1",
        'Gyp (USG 1-8")': "gyp@1", "Gyp (USG N12ULTRA)": "gyp@1", 'Gyp (USG N25 1-4")': "gyp@1",
        "Gyp (GWorx SC190)": "gyp@1", "Gyp (FR)": "gyp@1"}
    assert check_layouts(ran) == []


def test_lodging_and_travel_come_out_of_the_labor_dollars_as_the_sheet_has_them(ran):
    """The `lodging/*` cases hold no travel figure: the sheet's travel is lodging plus per diem, nights worked out of
    the labor dollars. Without those cases the lodging divisor (Leveling's 8 on 10 hour days) would be unproven."""
    for tab in PRICED_TABS:
        golden = S.load_golden(S.profiles()["sheets"][tab]["slug"])
        assert sum(1 for v in golden["vectors"] if v["id"].startswith("lodging/")) == 8, tab
    assert ran["flips"]["Leveling / lodgingDivisor"] > 0 and ran["flips"]["Epoxy / travelFromLodging"] > 0


def test_the_probes_that_start_at_the_chains_boundary_are_answered_as_the_sheet_answers_them(ran):
    assert check_probes(ran) == []


def test_polish_legacy_differs_from_the_sheet_exactly_where_the_departures_say(ran):
    assert check_departures(ran) == []
    assert set(ran["departures"]["seen"]) == {"tooling-is-zero", "remodel-base-widened", "hard-bid-removed", "bond-is-not-an-input"}


def test_the_departures_file_still_declares_five_departures_and_the_engine_closes_none_for_saved_bids():
    dep = json.loads((S.ORACLE / "departures.json").read_text(encoding="utf-8"))
    assert [d["id"] for d in dep["departures"]] == [
        "tooling-is-zero", "remodel-base-widened", "hard-bid-removed", "bond-is-not-an-input", "lodging-by-man-days"]


def test_markup_chain_is_the_engine_on_polish_legacy_with_the_keys_it_always_had(ran):
    assert check_wrapper(ran) == []
    assert ran["wrapper"]["compared"] == 171


# ── the flags, the odd rules, the formulas ───────────────────────────────────
def test_every_quirk_flag_turns_an_answer_red_somewhere_when_flipped(ran):
    assert check_flips(ran) == []
    assert set(ran["flips"]) and {k.split(" / ")[1] for k in ran["flips"]} == set(S.profiles()["quirks"])


def test_every_rate_a_profile_carries_is_the_workbooks_own_constant(ran):
    assert check_pins(ran) == []
    pinned = {(p["tab"], p["fixed"]) for p in ran["pins"]}
    for tab in PRICED_TABS:
        assert (tab, "dayHours") in pinned and (tab, "burdenPct") in pinned and (tab, "superPct") in pinned, tab
    assert {p["tab"] for p in ran["pins"] if p["fixed"] == "truckload"} == {t for t in PRICED_TABS if t.startswith("Gyp")}


def test_every_odd_rule_of_the_chain_is_exercised_by_a_recorded_case(ran):
    assert check_odd_rules(ran) == []
    for name, seen in ran["odd"]["chain"].items():
        assert seen >= 1, name


def test_the_odd_rules_that_are_not_in_the_chain_say_why_and_are_the_four_the_document_names():
    doc = (pathlib.Path(__file__).resolve().parents[2] / "docs" / "kyle-workbook-odd-rules.md").read_text(encoding="utf-8")
    for rule_id, why in UPSTREAM_RULES.items():
        assert why and len(why) > 40, rule_id
    # eleven rules in the document: seven live in the chain, four before it
    assert len(CHAIN_RULES) + len(UPSTREAM_RULES) == 11
    assert len(re.findall(r"^### \d+\. ", doc, flags=re.M)) == 11


def test_every_profile_ladder_tier_table_and_expression_is_the_workbooks_formula(ran):
    assert check_formulas(ran) == []
    by = {(f["tab"], f["line"]): f for f in ran["formulas"]}
    # Seal's sixth rung and Gyp's seven tiers are checked on their edges, one dollar either side
    assert by[("Seal", "gp")]["checked"] >= 20 and by[('Gyp (USG 1-8")', "gp")]["checked"] >= 23


def test_profiles_are_plain_data_and_the_tabs_all_have_one(ran, units):
    assert check_profiles(ran) == []
    d = units["data"]
    assert d["jsonRoundTrip"] and d["noFunctionsOrUndefined"] and d["everyRateParses"] and d["everyDefaultParses"]
    assert d["everyTabHasAProfile"] and d["onlyGypTabsHaveATruckload"]


def test_the_workbook_cell_maps_were_not_touched_by_part_two():
    """The oracle's integrity hash covers the cell maps of part one and nothing of part two. If this fails the hash
    in meta.json moved with it and the answers have to be recorded again (node backend/tests/js/workbook-oracle.js)."""
    meta = S.load_meta()
    assert S.profiles_sha256() == meta["integrity"]["profiles"]["sha256"]


# ── the engine's own behaviour ───────────────────────────────────────────────
def test_a_profile_extends_another_and_states_only_what_differs(units):
    e = units["extends"]
    assert e["chains"]["seal"] == ["polish", "seal"] and e["chains"]["leveling"] == ["polish", "epoxy", "epoxy-blank", "leveling"]
    assert e["chains"]["polish-legacy"] == ["polish", "polish-legacy"]
    assert e["sealOnlyDiffersInGp"] == ["gp"] and e["sealQuirksSame"]
    assert e["legacyQuirksDiffer"] == ["bondInput", "hasHardBid", "remodelBase", "remodelRateDefault", "toolingInSubTotal", "travelFromLodging"]
    assert e["legacyRatesSame"], "polish-legacy charges the same rates as polish: its departures are rules, not rates"
    assert e["frozen"] and e["sameObjectTwice"] and e["gypDropsShipPct"] and e["globalsFilledIn"]
    assert e["levelingLaborRate"] == "33.66"
    assert all(v == k + "@1" for k, v in e["stamps"].items())


def test_the_global_defaults_have_one_home_and_the_model_reads_them(units):
    m = units["model"]
    assert m["rates"] == m["literals"], "bid-model's RATES are the figures they always were"
    assert m["shipped"] == {"labor": 33, "lodging": 70, "perDiem": 45}
    assert m["gpBands"] == m["bandsOfLegacy"] == [[6500, 0.52], [15000, 0.45], [22500, 0.35], [32500, 0.32], [None, 0.3]]
    assert m["bandsOfSeal"] == [[6500, 0.52], [15000, 0.45], [22500, 0.35], [32500, 0.32], [42500, 0.3], [None, 0.28]]
    assert m["bandsOfGyp"] == [[15000, 0.45], [25000, 0.4], [50000, 0.35], [75000, 0.33], [100000, 0.28], [150000, 0.26], [None, 0.24]]
    assert m["markupChainKeys"] == EXPECTED_LEGACY_KEYS and m["markupChainPicksEngine"]


def test_bid_model_has_no_second_copy_of_a_rate():
    """RATES, GP_BANDS and the shipped travel and labor figures are READ off the profiles. A number written back
    into the model would be a second home for it, and nothing but this would say so."""
    src = (FRONTEND / "js" / "bid-model.js").read_bytes().decode("utf-8")
    for needle in ("SHIPPING: 0.02", "SUPER_PTO: 0.027", "SOFT_COSTS: 0.16", "SALES_TAX: 0.09475", "BURDEN: 0.12",
                   "[[6500, 0.52]", "var SHIPPED_LODGING_RATE = 70", "var SHIPPED_PER_DIEM_RATE = 45",
                   "var SHIPPED_LABOR_RATE = 33", "KS_STATE: 0.065", "SHEET_REMODEL: 0.10,"):
        assert needle not in src, "bid-model.js writes %r again" % needle
    assert "engine.rateNumber(LEGACY.rates.super_pto)" in src and "engine.bandsOf(LEGACY.rates.gp)" in src


def test_bid_model_seed_library_labor_does_not_key_an_object_by_a_row_id(units):
    """CodeQL alert 154: `seen` was a plain object keyed by the row id. A row called `constructor` was 'already
    seen' because Object.prototype has one. It is a Set now, and the row is added like any other."""
    assert units["model"]["seedLibraryLaborPlainIds"] == ["constructor", "toString"]
    src = (FRONTEND / "js" / "bid-model.js").read_bytes().decode("utf-8")
    src = src.replace("\r\n", "\n")
    start = src.index("function seedLibraryLabor(")
    body = src[start:src.index("\n  }\n", start)]
    assert "var seen = new Set();" in body and "seen[" not in body and "seen = {}" not in body


def test_the_engine_and_the_profiles_never_write_to_an_object_by_a_key_that_came_from_data():
    """The CodeQL js/remote-property-injection pre-flight, as the plan asks: no `obj[key] = value`. Lines that are
    comments are skipped; the engine and the profiles build their maps with Map or Object.fromEntries."""
    for rel in (ENGINE, PROFILES):
        for n, line in enumerate((FRONTEND / rel).read_bytes().decode("utf-8").splitlines(), 1):
            code = line.strip()
            if code.startswith("//") or code.startswith("*") or code.startswith("/*"):
                continue
            assert not re.search(r"[\w\])]\[[^\]]+\]\s*(=|\+=|-=)(?!=)", code), "%s:%d writes by a computed key: %s" % (rel, n, code)


def test_a_rate_is_read_as_the_number_typed_not_the_float_the_division_makes(units):
    r = units["rules"]
    assert r["percent"] == {"ok": True, "value": 0.027, "formula": "2.7%"}
    assert r["percentIsSnapped"] and r["fourPointOne"], "2.7/100 is 0.027000000000000003; the engine snaps to twelve figures"
    assert r["zeroIsARate"]["ok"] and r["zeroIsARate"]["value"] == 0


def test_nothing_filed_or_switched_off_or_blank_is_null_and_the_builtin_applies(units):
    r = units["rules"]
    assert r["nothingFiled"] is None and r["notAList"] is None and r["otherLayout"] is None
    assert r["switchedOff"] is None, "a line switched off is still charged: not used here is not a zero"
    assert r["blank"] == [None, None, None]
    assert r["bondOnALayoutIsNotRead"] is None and r["dollarsAreReadFromGlobalOnly"] is None
    assert r["bondFromGlobalForAnyLayout"]["value"] == 0.01


def test_a_rule_that_will_not_price_says_why_and_is_never_zero(units):
    r = units["rules"]
    for name in ("dollarFigureForARate", "negativeRate", "parseError", "wordsNotAFormula", "unboundName", "gpDollars",
                 "percentWhereDollars", "negativeDollars"):
        assert r[name]["ok"] is False and r[name]["reason"] and "value" not in r[name], name
    assert "dollar figure" in r["dollarFigureForARate"]["reason"] and "dollar figure" in r["gpDollars"]["reason"]
    assert "cannot be read" in r["parseError"]["reason"] and "percentage" in r["percentWhereDollars"]["reason"]
    c = units["compile"]
    # priced with a broken rule filed, the bid has NO figures: a total of null, not of zero
    assert c["brokenPrices"]["priceable"] is False and c["brokenPrices"]["total"] is None
    assert c["brokenPrices"]["keys"] == ["priceable", "profile", "line", "reason", "total"]
    assert c["mixedPrices"]["priceable"] is False and c["mixedPrices"]["total"] is None
    for reason in c["broken"]["unpriceable"].values():
        assert reason
    assert c["mixedUnpriceable"] == ["soft_costs"] and c["mixedFiled"] == ["gp"]


def test_a_filed_ladder_a_filed_rate_and_a_filed_global_line_each_reach_the_bid(units):
    r, c = units["rules"], units["compile"]
    assert r["gpLadder"]["value"] == 0.52 and r["gpFlat"]["value"] == 0.3 and r["gpBare"]["value"] == 0.45
    assert r["gpAtJob"]["value"] == 0.45, "a ladder read at a job's own sub-total"
    assert r["dollars"]["value"] == 33 and r["dollarSign"]["value"] == 33.5 and r["zeroDollars"]["value"] == 0
    assert c["filedSuper"] == {"profile": "polish@1", "rates": {"super_pto": "4%"}, "filed": ["super_pto"], "unpriceable": {}}
    assert c["filedSuperPrices"] > c["builtInSuper"] and c["filedSuperIsFourPercentOfTheBase"]
    assert c["onlyTheFiledLineMoved"]
    assert c["filedGpRate"] == 0.3 and c["sealBuiltInGpRate"] == 0.35
    assert c["lodgingAtFiledRate"] < c["lodgingAtBuiltInRate"], "a $40 labor rate shortens the nights"
    assert c["filedBondPrices"] == 0.02 and c["epoxyLayoutRulesReachBlank"]
    assert c["switchedOffFilesNothing"]["filed"] == [] and c["nothing"]["rates"] == {}
    assert c["stamp"] == "polish@1"


def test_no_snapshot_means_the_builtins_never_the_live_rules(units):
    c = units["compile"]
    assert c["absentSnapshotIsTheBuiltIns"]
    assert c["legacyIgnoresTypedBond"] == 0 and c["sheetTakesTypedBond"] > 0, "bondInput is the sheet's and not the model's"


def test_combo_sums_each_tabs_own_total_and_never_pools_the_sub_totals(units):
    c = units["combine"]
    assert c["total"] == c["sumOfTotals"] == c["epoxyTotal"] + c["polishTotal"] and c["priceable"]
    assert c["sumsGp"] and c["sumsEveryLine"] and c["single"]
    assert [p["layout"] for p in c["parts"]] == ["epoxy", "polish"]
    # pooled, the job lands on a lower rung of the ladder than either part, and pays less
    assert c["pooledGpPct"] < min(c["epoxyGpPct"], c["polishGpPct"])
    assert c["pooledTotal"] < c["total"]
    assert c["brokenPart"]["priceable"] is False and c["brokenPart"]["total"] is None and c["brokenPart"]["reasons"]


def test_layout_and_profile_are_required_and_a_missing_one_throws_by_name(units):
    t = units["throws"]
    for name, got in t.items():
        assert got is not None and got["name"] == "BidEngineError" and got["message"], name
    assert "layout" in t["ruleNumberNoLayout"]["message"] and "layout" in t["combineNoLayout"]["message"]
    assert "profile" in t["priceNoProfile"]["message"] and "truckload" in t["gypWithoutTruckload"]["message"]


def test_a_module_that_is_missing_is_named_where_it_is_loaded(units):
    for key, file in (("noMath", "excel-math.js"), ("noProfiles", "bid-profiles.js"), ("noMarkup", "markup-core.js")):
        assert units["loader"][key]["message"] == "bid-engine.js needs %s loaded before it" % file
    assert units["loader"]["modelNeedsEngine"]["message"] == "bid-model.js needs bid-engine.js loaded before it"


def test_a_profile_that_loops_names_an_unknown_quirk_or_leaves_one_out_is_refused(units):
    b = units["badData"]
    assert "extends itself" in b["loops"]["message"] and "extends itself" in b["selfLoop"]["message"]
    assert "does not exist" in b["extendsNothing"]["message"]
    assert "aQuirkNobodyReads" in b["unknownQuirk"]["message"] and "aNewQuirk" in b["missingQuirk"]["message"]


# ── red without the code: break a COPY and the same checks go red, by name ───
def _mutated(tmp_path, rel, old, new):
    frontend = break_source(tmp_path, rel, old, new, also=[f for f in ALSO if f != rel])
    return _drive(HARNESS, frontend), _drive(UNITS, frontend)


# (name, file, the line, what it becomes, a word the problem list must contain). A mutation the workbook cannot see
# (a rule filed on the Markups page, a missing layout) is caught by the unit table instead, and the word is then the
# name of the section of that table that moved.
CHAIN_MUTATIONS = {
    "the escalation always joins the sub-total (Leveling's odd rule undone)": (
        ENGINE, "if (q.escalationInSubtotal) sub += escalation;       // odd rule 3: Leveling does not",
        "sub += escalation;", "Leveling"),
    "GP takes the fees back off on Epoxy as it does everywhere else": (
        ENGINE, "- roundUp(sub_total + sales_tax + (q.gpSubtractionIncludesFees ? fees : 0));",
        "- roundUp(sub_total + sales_tax + fees);", "Epoxy"),
    "the bond counts the taxes once": (
        ENGINE, "+ sales_tax + remodel_tax + taxes + fees) * bond_pct);",
        "+ sales_tax + remodel_tax + fees) * bond_pct);", "bond"),
    "the sound mat ships free only after a truckload, not at it": (
        ENGINE, "(extras + (rolls < truckload ? soundMat : 0))", "(extras + (rolls <= truckload ? soundMat : 0))", "Gyp"),
    "Gyp's escalation follows Prevailing Wage like everyone else's": (
        ENGINE, "var esc_pct = (q.escalationAlwaysOn || cond.prevailing_wage) ? rate(\"esc_pct\") : 0;",
        "var esc_pct = (cond.prevailing_wage) ? rate(\"esc_pct\") : 0;", "Gyp"),
    "lodging is always divided by 8": (
        ENGINE, "lodging_qty = ((labor - num(input.travelLabor)) / laborRate) / q.lodgingDivisor;",
        "lodging_qty = ((labor - num(input.travelLabor)) / laborRate) / 8;", "Gyp"),
    "the hard bid is on for every profile": (
        ENGINE, "var hardBidOn = !!q.hasHardBid && !!cond.hard_bid;", "var hardBidOn = !!cond.hard_bid;", "Gyp"),
    "the overage line is dropped": (
        ENGINE, "overage = q.hasOverage ? roundUp(input.overage) : 0;", "overage = 0;", "Epoxy blank"),
    "the tooling line leaves the sub-total": (
        ENGINE, "if (q.toolingInSubTotal) sub += tooling;", "sub += 0;", "Polish"),
    "travel never comes from lodging": (
        ENGINE, "var travel = roundUp(isBlank(input.travel) && q.travelFromLodging ? lodging + per_diem : input.travel);",
        "var travel = roundUp(input.travel);", "lodging"),
    "an unset remodel rate is always the Kansas floor": (
        ENGINE, "rate(q.remodelRateDefault === \"state\" ? \"remodel_state\" : \"remodel_sheet\")", "rate(\"remodel_state\")", "Polish"),
    "the remodel base leaves travel and tooling out on every tab": (
        ENGINE, "if (q.remodelBase === \"sheet\") remodelBase += tooling + travel;", "remodelBase += 0;", "Polish"),
    "a typed bond rate is ignored on every tab": (
        ENGINE, "var typedBond = q.bondInput && !isBlank(input.bond_pct);", "var typedBond = false;", "bond"),
    "the rate is not snapped to twelve figures": (
        ENGINE, "function snap(n) { return parseFloat(n.toPrecision(12)); }", "function snap(n) { return n; }", "Polish"),
    "combining adds the last tab's total to every line": (
        ENGINE, "return t + num(x.result[key]);", "return t + num(x.result.total);", "combine"),
    "a rate out of range prices instead of being unpriceable": (
        ENGINE, "if (value < 0 || value >= 1) {", "if (value < 0 || value >= 1e12) {", "rules"),
    "ruleNumber stops asking for the layout": (
        ENGINE, "if (typeof layout !== \"string\" || layout === \"\") throw new BidEngineError(\"ruleNumber needs the layout the rule is for\");",
        "", "throws"),
    "Seal's sixth rung is not 28 percent": (
        PROFILES, "42500,30%, 28%))", "42500,30%, 29%))", "Seal"),
    "Gyp's seventh tier moves": (
        PROFILES, "150000,26%, 24%))", "150000,26%, 25%))", "Gyp"),
    "Gyp's soft cost taper starts a dollar late": (
        PROFILES, "'IF(E69>334900,.05,IF(E69>234450,.035,0)), \"error\")'", "'IF(E69>334901,.05,IF(E69>234450,.035,0)), \"error\")'", "Gyp"),
    "the shipping tier counts its edge on the other side": (
        PROFILES, 'var SHIP_TIERS = "0.05+IF(material<=5000,0.1,IF(material<=10000,0.06,0.04))";',
        'var SHIP_TIERS = "0.05+IF(material<5000,0.1,IF(material<=10000,0.06,0.04))";', "Epoxy"),
    "a Gyp truckload is wrong": (
        PROFILES, '"Gyp (USG 1-8\\")": { profile: "gyp", truckload: 280 },', '"Gyp (USG 1-8\\")": { profile: "gyp", truckload: 281 },', "truckload"),
    "Epoxy's super and PTO is 3.1 percent": (
        PROFILES, 'rates: { ship_pct: SHIP_TIERS, super_pto: "3%", soft_costs: "13%" }',
        'rates: { ship_pct: SHIP_TIERS, super_pto: "3.1%", soft_costs: "13%" }', "Epoxy"),
    "Leveling's day is eight hours": (
        PROFILES, "quirks: { escalationInSubtotal: false, dayHours: 10 },", "quirks: { escalationInSubtotal: false, dayHours: 8 },", "dayHours"),
    "Polish's hard bid threshold moves": (
        PROFILES, "IF(subtotal>=13000, -2.5%, 0)", "IF(subtotal>=13001, -2.5%, 0)", "hard_bid"),
}


@pytest.mark.parametrize("name", sorted(CHAIN_MUTATIONS))
def test_the_checks_go_red_when_the_engine_or_a_profile_changes(tmp_path, name):
    rel, old, new, needle = CHAIN_MUTATIONS[name]
    ran_, units_ = _mutated(tmp_path, rel, old, new)
    problems = all_checks(ran_)
    unit_problem = []
    # the unit harness carries the claims that are about the engine and not about the workbook; a mutation may be
    # caught only there, so its answers are compared with the unbroken ones
    if not problems:
        good = _drive(UNITS)
        unit_problem = [k for k in good if good[k] != units_[k]]
    assert problems or unit_problem, "nothing noticed: " + name
    text = " ".join(problems) + " ".join(unit_problem)
    assert needle.lower() in text.lower(), "%s: caught, but not as %r:\n%s" % (name, needle, text[:900])


def test_a_breakage_the_workbook_cannot_see_is_seen_by_the_unit_table(tmp_path):
    """The wrapper, `extends` and the snapped rate are not the workbook's, so the oracle comparison cannot notice a
    break in them. The unit table does, and the golden does for the wrapper."""
    good = _drive(UNITS)
    frontend = break_source(tmp_path, ENGINE, "if (RESOLVED.has(id)) return RESOLVED.get(id);", "",
                            also=[f for f in ALSO if f != ENGINE])
    broken = _drive(UNITS, frontend)
    assert broken["extends"]["sameObjectTwice"] is False and good["extends"]["sameObjectTwice"] is True
