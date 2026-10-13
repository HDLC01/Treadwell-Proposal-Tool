"""Phase 12, the proof: an Epoxy job priced through the v2 path matches Kyle's workbook.

THE QUESTION. Hanz's decision (2026-10-12): match Kyle's workbook EXACTLY, odd rules included. The workbook oracle
already proves the markup chain on each tab (test_bid_engine.py). What it cannot prove is the material that arrives at
the chain, and the plumbing between a takeoff and the chain. This does both, against the workbook itself:

  1. THE JOBS. tests/js/epoxy-jobs-recorder.js typed 440 jobs into the Epoxy tab of the template (a system for System 1
     and for System 2, a primer, a cove and its length, the job questions, a crew) and recorded what its cells answered
     (tests/fixtures/epoxy_jobs_golden.json). tests/js/epoxy-v2-proof-harness.js builds each job as a v2 Epoxy section
     over the library backend/ops/seed_library_from_workbook.py plans and prices it the way the estimate page does.
     Material (before D40 rounds it), D40, the tooling, the sub-total, the taxes and the total have to be EQUAL, to the
     dollar, for every job except the ones a declared departure explains. The declared set is checked both ways: every
     job outside it is equal, and every job inside it really differs (so a departure that closes is noticed).
  2. THE CHAIN. Every Epoxy vector of the workbook oracle (tests/fixtures/oracle/epoxy.json) is priced as a v2 section
     whose labor, travel, fees, contingency, questions and area are the vector's, and equals the oracle on every figure
     they share, except the vectors that a declared departure keeps out.

THE DECLARED DEPARTURES (each is in docs/v2-architecture.md, and each is a named modelling gap for Kyle):
  * NO ONE-PURCHASE DEPARTURE (Hanz, 2026-10-13, "Buy packs for the whole job", then "Round each coat like Kyle"). This
    REPLACED the Phase 12 departure "price break on two lines", where the library charged the small-lot price for a flake or
    quartz system whose two broadcast lines reach the break together and neither does alone (every size up to 1,000 to 1,600
    SF, 83 of the 440 jobs, $10 to $38 high). A section buys each COAT once (library-core pricePool): a coat is one line of
    one assembly, and its fractional quantity on every row that holds it is added first, then the roundup and the price break
    happen once. Two different lines of one assembly that buy the same item are two coats, each rounded to its own whole packs
    exactly as the sheet rounds each line, and a system's two broadcast lines (two library items on one price ladder) have the
    break judged together as the sheet does. So a single-area job is the workbook to the cent again and the departure set is
    EMPTY: 83 of 83 formerly gapped jobs are now exactly the workbook's, 0 jobs are below it (the version of the pool that
    bought the ITEM once for a whole system, #662, was below it on 110 jobs, $79 to $476 of material). The harness still
    prices every job the sheet's way WITHOUT the pool (each line to its own packs, the break judged on the lines added
    together, worked out from the library's own breakAt) and the test requires the pooled price to equal it on every job.
    What stays a deliberate, undeclared-by-job difference is the one thing Hanz asked for and the workbook has no way to say:
    the SAME coat on two areas is one purchase (5,000 + 3,000 SF costs what 8,000 SF does), shown on the real library in
    test_v2_pool_packs.py. Only one recorded job has one system on both areas and it lands on the workbook's figure.
  * FOUR PLACES. A library cost has four decimal places and the sheet's prices have more, so a sum can land a hair
    either side of a whole dollar and ROUNDUP then differs by a dollar. It is rare (about 5 jobs in 1,500 scanned, all of
    them large or on a cove) and is checked at the three cove jobs and two plain sizes recorded.
  * THREE PLACES. A coverage has three places (a bag of flake covers 266.66667 SF and is stored 266.667, rounded up), so
    an area typed to two decimals within 0.003 SF past a bag edge buys one bag fewer than the sheet. Whole square feet
    cannot do this.
  * NO TOOLING FOR NO AREA. The sheet charges its tooling minimums for a job with no square feet; a v2 section does not.
  * HARD BID, BOND, LODGING. v2 has no hard bid (Hanz removed it, 2026-09-22), no bond input (it is 0 and unwired), and
    prices travel from the model's own Lodging and Per Diem lines, not from the sheet's local switch.

Each mutation at the bottom breaks a scratch copy of the takeoff or the model and the proof has to notice.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from _golden_support import FRONTEND, break_source
from _node import last_json_line, require_node, run_node
from _oracle_support import ORACLE, template_hash
from _seed_support import PLAN, plan_json, seed

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "epoxy-v2-proof-harness.js"
GOLDEN = TESTS / "fixtures" / "epoxy_jobs_golden.json"
ORACLE_EPOXY = ORACLE / "epoxy.json"

# Jobs where a declared departure applies, and why. The one purchase has no jobs left (see _one_purchase_jobs, which the proof
# requires to be empty): it is read from the proof's run, not listed by hand, because a hand list is what understated the first one.
FOUR_PLACES = {      # a sum a hair either side of a whole dollar
    # the library's 4-place WR kit price puts the sum on 32,804.0000; the sheet's is 32,804.0000002
    "cove/wr-4/40/under-trowel-hybrid-quartz-double-broadcast-orange-peel-texture-trowel-texture",
    "cove/wr-4-cap/40/under-trowel-hybrid-quartz-double-broadcast-orange-peel-texture-trowel-texture",
    "cove/wr-6/40/under-trowel-hybrid-quartz-double-broadcast-orange-peel-texture-trowel-texture",
    "places/q28/3000",            # the sheet's sum is 10,915.0002 and the library's 10,914.9976
    "places/shop-single/15500",   # the sheet's sum is 38,325.9981 and the library's 38,326.0022
}
THREE_PLACES = {"places/frac/macro-2666.67"}   # 2,666.67 SF is 0.003 past 10 bags of 266.66667; stored 266.667 it is 10
NO_AREA = {"empty/none"}
CHAIN_SKIPS = {"hard bid": 60, "bond": 12, "lodging": 8}


def _tolerance(raw):
    """The four-place price: a library cost is kept to four decimals, so a sum of a few thousand units is off by a few
    cents at most, 3e-7 of the sum at the largest job recorded."""
    return 5e-7 * max(raw, 1.0) + 0.01


def run(frontend=FRONTEND, tmp=None):
    proc = run_node(HARNESS, frontend, plan_json(tmp), GOLDEN, ORACLE_EPOXY)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran(tmp_path_factory):
    require_node()
    return run(tmp=tmp_path_factory.mktemp("proof"))


@pytest.fixture(scope="module")
def golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _differs(want, got):
    w = want["out"]
    return (abs(got["raw"] - w["raw"]) > _tolerance(w["raw"]) or got["material"] != w["D40"]
            or got["total"] != w["D88"] or got["tooling"] != w["D62"])


def _differing(golden, ran):
    by_id = {c["id"]: c for c in ran["cases"]}
    return {c["id"] for c in golden["cases"] if _differs(c, by_id[c["id"]])}


def _one_purchase_jobs(ran):
    """The jobs where the pool costs anything other than the sheet's way (each line to its own packs, the price break
    judged on the lines added together): the harness prices both, the second without pricePool. There are none."""
    return {c["id"] for c in ran["cases"] if abs(c["raw"] - c["sheet_raw"]) > _tolerance(c["raw"])}


def _declared(ran):
    return FOUR_PLACES | THREE_PLACES | NO_AREA


# ── the recorded answers are the workbook's, and current ─────────────────────────────────────────
def test_the_recorded_jobs_were_taken_from_the_template_and_the_engine_as_they_are_now(golden):
    digest, cells, names = template_hash(["Epoxy"])
    assert golden["template"] == {"hash": digest, "cells": cells, "names": names}, (
        "the Epoxy tab or a defined name of the template changed since the jobs were recorded: re-run "
        "`node backend/tests/js/epoxy-jobs-recorder.js --plan <seed --json> --write` and read the diff")
    meta = json.loads((ORACLE / "meta.json").read_text(encoding="utf-8"))
    assert golden["engine"]["hyperformula"]["sri"] == meta["engine"]["hyperformula"]["sri"], (
        "the jobs were recorded by another HyperFormula than the oracle's")


def test_the_proof_touches_every_system_primer_wall_and_cove_the_seed_plans(golden):
    used = set()
    for c in golden["cases"]:
        for k in ("sys1", "sys2", "cove1", "cove2", "primer1", "primer2"):
            if c["in"].get(k):
                used.add(" ".join(c["in"][k].split()))
    for a in PLAN.as_dict()["assemblies"]:
        if a["id"].startswith("wb-gyp-"):
            continue                                     # the Gyp areas are proved in test_gyp_v2_proof.py
        name = " ".join(a["name"].replace("Primer: ", "").replace("Cove: ", "").split())
        assert name in used, "no recorded job prices %s" % a["name"]


# ── 1. the jobs ──────────────────────────────────────────────────────────────────────────────────
def test_every_job_outside_the_declared_departures_is_equal_to_the_workbook_to_the_dollar(golden, ran):
    by_id = {c["id"]: c for c in ran["cases"]}
    declared = _declared(ran)
    checked = 0
    for case in golden["cases"]:
        if case["id"] in declared:
            continue
        w, g = case["out"], by_id[case["id"]]
        assert abs(g["raw"] - w["raw"]) <= _tolerance(w["raw"]), (case["id"], w["raw"], g["raw"])
        assert (g["material"], g["tooling"], g["sub_total"], g["gp"], g["taxes"], g["total"]) == (
            w["D40"], w["D62"], w["D70"], w["D73"], w["D82"], w["D88"]), case["id"]
        checked += 1
    assert checked >= 300, "the proof compared only %d jobs" % checked


def test_the_declared_departures_are_exactly_the_jobs_that_differ(golden, ran):
    declared = _declared(ran)
    assert _one_purchase_jobs(ran) == set(), "the pool must cost what the sheet's way costs on every recorded job"
    assert _differing(golden, ran) == declared, (
        "the jobs that differ from the workbook are not the declared ones. Differ and not declared: %s. Declared and "
        "equal (a departure closed, so say so): %s" % (
            sorted(_differing(golden, ran) - declared), sorted(declared - _differing(golden, ran))))


def test_each_departure_is_the_one_it_says_it_is(golden, ran):
    by_id = {c["id"]: c for c in ran["cases"]}
    want = {c["id"]: c for c in golden["cases"]}
    for cid in FOUR_PLACES:
        w, g = want[cid]["out"], by_id[cid]
        assert abs(g["sheet_raw"] - w["raw"]) < 0.01, cid
        assert abs(g["raw"] - w["raw"]) < 0.01 and abs(g["material"] - w["D40"]) == 1, cid
    for cid in THREE_PLACES:
        w, g = want[cid]["out"], by_id[cid]
        assert g["material"] < w["D40"] - 50, "%s: the stored coverage should buy one bag fewer than the sheet" % cid
    # ... and the same area a hair further on is a whole bag past the edge and is equal, so the departure is a window
    assert by_id["places/frac/macro-2666.7"]["material"] == want["places/frac/macro-2666.7"]["out"]["D40"]
    w, g = want["empty/none"]["out"], by_id["empty/none"]
    assert w["D62"] == 220 and g["tooling"] == 0 and g["material"] == 0, "a section with no area charges no tooling"


def test_the_sheets_own_way_of_buying_is_the_workbook_on_every_job(golden, ran):
    """THE SHEET'S READING, held to the workbook with no pool in it. Each line rounds to its own packs and a flake or
    quartz break is judged on a system's two broadcast lines added together (the harness works that out from the library's
    own breakAt, not from pricePool). Priced that way the raw material is the workbook's on EVERY job (bar the one the
    stored coverage moves, and the one with no area), so the library rows, the ladders and the packs are the sheet's, and
    what pricePool does on top is the only thing that moves a price. Priced with no pool and no break reading (a section
    saved before the pool) the raw material is over the workbook's by exactly the break the lines earned together."""
    by_id = {c["id"]: c for c in ran["cases"]}
    want = {c["id"]: c for c in golden["cases"]}
    gapped = 0
    for cid, w in want.items():
        if cid in THREE_PLACES or cid in NO_AREA:
            continue
        g = by_id[cid]
        assert abs(g["sheet_raw"] - w["out"]["raw"]) <= _tolerance(w["out"]["raw"]), (cid, g["sheet_raw"], w["out"]["raw"])
        assert abs((g["alone"] - w["out"]["raw"]) - g["sheet_break_gap"]) <= _tolerance(w["out"]["raw"]), cid
        gapped += g["sheet_break_gap"] > 1
    assert gapped >= 80, "the old price break was recorded biting in only %d jobs" % gapped
    # where it reached, as before: the widest system bit at 1,600 SF and not at 1,700, and a small system on a big job
    assert by_id["break/hybrid-macro-flake/1600"]["sheet_break_gap"] > 1 and by_id["break/hybrid-macro-flake/1700"]["sheet_break_gap"] == 0
    assert all(by_id["break/two-systems/%d" % i]["sheet_break_gap"] > 1 for i in (1, 2, 3))


def test_buying_each_coat_once_closes_the_price_break_and_prices_every_job_at_the_workbook(golden, ran):
    """The Phase 12 departure was a library price ABOVE the workbook on 83 jobs (the break judged on each line alone). The
    version of the pool that bought each ITEM once for a system (#662) closed 54 of them and put the other 29 BELOW the sheet
    (and 110 jobs in all, $79 to $476 of material, the packs rounded once where the sheet rounds each line). Buying each COAT
    once (one line of one assembly) closes all 83, exactly, and leaves nothing above or below the workbook."""
    by_id = {c["id"]: c for c in ran["cases"]}
    want = {c["id"]: c for c in golden["cases"]}
    for cid, w in want.items():
        assert by_id[cid]["raw"] <= w["out"]["raw"] + _tolerance(w["out"]["raw"]), (
            "%s: the pool priced ABOVE the workbook: %r against %r" % (cid, by_id[cid]["raw"], w["out"]["raw"]))
    below = {cid for cid, w in want.items() if by_id[cid]["raw"] < w["out"]["raw"] - _tolerance(w["out"]["raw"])}
    assert below == THREE_PLACES, "jobs below the workbook that are not the stored-coverage window: %s" % sorted(below - THREE_PLACES)
    formerly = {c["id"] for c in ran["cases"] if c["sheet_break_gap"] > 1}
    exact = {cid for cid in formerly if abs(by_id[cid]["raw"] - want[cid]["out"]["raw"]) <= _tolerance(want[cid]["out"]["raw"])}
    assert len(formerly) == 83 and len(exact) == 83, (len(formerly), len(exact))
    # one such job, whole: the 700 SF hybrid flake (two flake items, one ladder) is the workbook's to the dollar
    for cid in ("break/hybrid-macro-flake/700", "break/hybrid-macro-flake/1000"):
        w, g = want[cid]["out"], by_id[cid]
        assert (g["material"], g["sub_total"], g["gp"], g["taxes"], g["total"]) == (
            w["D40"], w["D70"], w["D73"], w["D82"], w["D88"]), cid
        assert g["alone"] > g["raw"], "%s: pooled and priced alone should differ, or this proves nothing" % cid


def test_the_pool_costs_what_the_sheets_own_way_of_buying_costs_on_every_job(golden, ran):
    """Where #662 bought the ITEM once, 110 jobs priced below the sheet's way (a material two lines of a system share, such
    as the flake of a double broadcast, or a primer or system in both System 1 and System 2 rounded once). Each coat now
    keeps its own rounding, so the pooled raw material IS the sheet's way on EVERY job, the recorded ones that name a
    material twice included, and a system used on both areas still lands on the workbook's figure."""
    by_id = {c["id"]: c for c in ran["cases"]}
    want = {c["id"]: c for c in golden["cases"]}
    for cid, g in by_id.items():
        assert abs(g["raw"] - g["sheet_raw"]) <= _tolerance(g["raw"]), (cid, g["raw"], g["sheet_raw"])
    assert _one_purchase_jobs(ran) == set()
    # the jobs that used to be a one-purchase departure, named: a double broadcast, a primer on both areas, two systems
    for cid in ("system2/hybrid-micro-flake", "primer2/hp-gripper-primer", "break/two-systems/1", "system2/shop-floor-single-broadcast"):
        assert abs(by_id[cid]["raw"] - want[cid]["out"]["raw"]) <= _tolerance(want[cid]["out"]["raw"]), cid
    # not vacuous: the sheet's way differs from the old no-break reading on jobs the pool changes, and 300+ jobs are equal
    assert any(c["alone"] > c["raw"] + 1 for c in ran["cases"])
    assert len([c for c in golden["cases"] if c["id"] not in _declared(ran)]) >= 300


def test_a_section_saved_before_the_pool_is_priced_row_by_row(ran):
    """The gate. A section stamped `pool_packs` (every section made now) pools; the same job with no stamp is priced
    as it always was, so a saved bid does not move."""
    assert all(c["pooled"] for c in ran["cases"])
    assert any(c["alone"] > c["raw"] + 1 for c in ran["cases"]), "no job separates the pooled price from the row-by-row one"


def test_the_flake_systems_are_exact_at_every_size_the_pack_edges_were_recorded_at(golden, ran):
    """The CEILING edges (a 40 lb bag of flake covers 266.667 SF) are where a coverage stored to three places could buy a
    bag the sheet does not. The edge cases at and either side of every one are equal."""
    by_id = {c["id"]: c for c in ran["cases"]}
    edges = [c for c in golden["cases"] if c["id"].startswith("edge/macro/")]
    assert len(edges) >= 12
    for case in edges:
        assert by_id[case["id"]]["material"] == case["out"]["D40"], case["id"]


# ── odd rule 11, shown happening ─────────────────────────────────────────────────────────────────
def test_the_cove_aggregate_follows_system_one_even_in_system_twos_block(golden, ran):
    """Epoxy!AF126 reads `$A$22`, System 1's choice. So under a flake System 1 the cove of a quartz System 2 is priced
    with silica, and under a quartz System 1 the cove of a flake System 2 is priced with quartz. The workbook's own
    cove cells (D37 and D38) say which, and v2 gives the same figure; and the two prices differ, so this is not
    vacuous."""
    by_id = {c["id"]: c for c in ran["cases"]}
    want = {c["id"]: c for c in golden["cases"]}
    for cid, follows in (("cove2/epoxy-4/flake-then-quartz", "silica"), ("cove2/epoxy-4/quartz-then-flake", "quartz"),
                         ("cove2/epoxy-8-cap/flake-then-quartz", "silica"), ("cove2/epoxy-8-cap/quartz-then-flake", "quartz")):
        parts = want[cid]["parts"]
        sheet_cove = parts["D37"] + parts["D38"]
        c2 = by_id[cid]["cove2"]
        assert c2["quartz"] != c2["silica"], cid
        assert abs(c2["actual"] - sheet_cove) < 0.05, (cid, c2, sheet_cove)
        assert abs(c2[follows] - sheet_cove) < 0.05 and abs(c2["silica" if follows == "quartz" else "quartz"] - sheet_cove) > 1, cid


def test_every_cove_is_priced_to_the_cent_under_a_flake_system_and_under_each_quartz_one(golden, ran):
    by_id = {c["id"]: c for c in ran["cases"]}
    seen = 0
    for case in golden["cases"]:
        if not case["id"].startswith("cove/"):
            continue
        p = case["parts"]
        sheet = p["D35"] + p["D36"]
        mine = by_id[case["id"]]["cove1"]["actual"]
        assert abs(mine - sheet) <= 0.05, (case["id"], sheet, mine)
        seen += 1
    assert seen == 12 * 3 * 4


# ── 2. the chain ─────────────────────────────────────────────────────────────────────────────────
def test_every_oracle_vector_the_v2_section_can_express_is_priced_exactly_as_the_workbook_prices_it(ran):
    chain = ran["chain"]
    oracle = json.loads(ORACLE_EPOXY.read_text(encoding="utf-8"))
    assert [c["id"] for c in chain] == [v["id"] for v in oracle["vectors"]]
    wrong = {c["id"]: c["wrong"] for c in chain if c.get("wrong")}
    assert wrong == {}, "the v2 section disagrees with the workbook oracle on: %r" % dict(list(wrong.items())[:5])
    compared = [c for c in chain if "skipped" not in c]
    assert len(compared) >= 100, "the chain proof compared only %d vectors" % len(compared)
    # not vacuous: the compared vectors hold every job question both ways and money on every input
    ids = " ".join(c["id"] for c in compared)
    assert "flags/mid" in ids and "scale/x100" in ids and "sf/250000" in ids


def test_what_the_chain_proof_leaves_out_is_the_declared_departures_and_nothing_else(ran):
    skipped = {}
    for c in ran["chain"]:
        if "skipped" in c:
            skipped[c["skipped"]] = skipped.get(c["skipped"], 0) + 1
    assert skipped == CHAIN_SKIPS, skipped


# ── the model and engine plumbing, named ─────────────────────────────────────────────────────────
def test_a_v2_epoxy_section_prices_through_the_engines_epoxy_profile_and_stamps_it(ran):
    assert all(c["priceable"] for c in ran["cases"])
    oracle = json.loads(ORACLE_EPOXY.read_text(encoding="utf-8"))
    assert oracle["sheet"] == "Epoxy"


# ── red without the code ─────────────────────────────────────────────────────────────────────────
TAKEOFF = "js/epoxy-takeoff.js"
MODEL = "js/bid-model.js"
BREAKS = {
    "the 4 inch cove goes 25 feet a gallon": (
        TAKEOFF, '    "wb-epoxy-cove-epoxy-4in":          { kind: "epoxy", per: 30,   lbs: 25, cap: false },',
        '    "wb-epoxy-cove-epoxy-4in":          { kind: "epoxy", per: 25,   lbs: 25, cap: false },'),
    "the cove aggregate follows System 2's choice (never quartz)": (
        TAKEOFF, "      return QUARTZ_SYSTEMS.indexOf(id) >= 0;", "      return false;"),
    "the cove rounds the gallons once, not twice": (
        TAKEOFF, "      var units = roundUp(gallons / 8) + roundUp(gallons / 4);", "      var units = roundUp(gallons / 8 + gallons / 4);"),
    "the patch is not charged": (
        TAKEOFF, "    var patch = patchCost(items, ctx.sf);", "    var patch = 0;"),
    "the tooling floor is 100": (
        TAKEOFF, "consumablesPerSf: 0.33, consumablesMin: 150 };", "consumablesPerSf: 0.33, consumablesMin: 100 };"),
    "the cap comes in 10 foot sticks": (
        TAKEOFF, "  var CAP_STICK_LF = 8;", "  var CAP_STICK_LF = 10;"),
    "the aggregate is bought by the pound, not the bag": (
        TAKEOFF, "      var lbs = ceiling(gallons * variant.lbs, AGGREGATE_BAG_LB);", "      var lbs = gallons * variant.lbs;"),
    "the section's tooling never reaches the chain": (
        MODEL, "    if (isObject(mat)) copyInto(input, mat); else input.material = num(mat);",
        "    if (isObject(mat)) input.material = num(mat.material); else input.material = num(mat);"),
    "a price break starts above its quantity, not from it": (
        "js/library-core.js", "      if (list[i].min_qty <= u && (hit === null || list[i].min_qty > hit.min_qty)) hit = list[i];",
        "      if (list[i].min_qty < u && (hit === null || list[i].min_qty > hit.min_qty)) hit = list[i];"),
    "the section's labor is not read": (
        MODEL, "      labor: laborTotal(s.labor, model.conditions),", "      labor: 0,"),
    "a price break is judged on each line alone again": (
        "js/library-core.js", "                       g.needed, rep.roundup, g.bulk, g.cost0, g.ladder.units);",
        "                       g.needed, rep.roundup, g.bulk, g.cost0);"),
    "a coat is the item alone again (every line of the item pools, as #662 did)": (
        "js/library-core.js", '    return (a === undefined || a === null || a === "") ? JSON.stringify(["m", id]) : JSON.stringify(["a", a, j, id]);',
        '    return JSON.stringify(["m", id]);'),
    "a new section is not stamped to pool": (
        MODEL, "      pool_packs: true      // a section made now", "      pool_packs: false     // a section made now"),
    "the pooled cost is not handed back to its rows": (
        "js/library-core.js", "          cost: share[k], pack_cost: fin.pack_cost,", "          cost: 0, pack_cost: fin.pack_cost,"),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_proof_goes_red_when_the_takeoff_or_the_model_changes(tmp_path, golden, ran, name):
    rel, old, new = BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new, also=[MODEL, "js/library-core.js", TAKEOFF])
    broken = run(frontend, tmp_path)
    jobs_red = _differing(golden, broken) != _declared(ran)
    chain_red = any(c.get("wrong") for c in broken["chain"])
    assert jobs_red or chain_red, "the proof did not notice: " + name
