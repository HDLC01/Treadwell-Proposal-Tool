"""Phase 12, the proof: an Epoxy job priced through the v2 path matches Kyle's workbook.

THE QUESTION. Hanz's decision (2026-10-12): match Kyle's workbook EXACTLY, odd rules included. The workbook oracle
already proves the markup chain on each tab (test_bid_engine.py). What it cannot prove is the material that arrives at
the chain, and the plumbing between a takeoff and the chain. This does both, against the workbook itself:

  1. THE JOBS. tests/js/epoxy-jobs-recorder.js typed 250 jobs into the Epoxy tab of the template (a system for System 1
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
  * PRICE BREAK ON TWO LINES. The sheet judges a flake or quartz price break on the two broadcast lines ADDED TOGETHER;
    the library judges each line alone (the Phase 11 gap). It only shows where the two lines straddle the break.
  * FOUR PLACES. A library cost has four decimal places and the sheet's prices have more, so a sum can land exactly on a
    whole dollar that the sheet's sum is a hair above, and ROUNDUP then differs by a dollar.
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

# Jobs where a declared departure applies, and why.
COMBINED_BREAK = {   # the two broadcast lines straddle the 240 lb / 450 lb break at 1,000 SF or under
    "system/40-s-q28-quartz-double-broadcast/1000",
    "system/hybrid-macro-flake/1000",
    "system/hybrid-micro-flake/1000",
    "system/hybrid-quartz-double-broadcast-standard-texture/1000",
    "system/micro-flake-double-broadcast/1000",
    "system/trowel-hybrid-quartz-double-broadcast-orange-peel-texture-trowel-texture/1000",
    "edge/quartz/800",
}
FOUR_PLACES = {      # the library's 4-place WR kit price puts the sum on 32,804.0000; the sheet's is 32,804.0000002
    "cove/wr-4/40/under-trowel-hybrid-quartz-double-broadcast-orange-peel-texture-trowel-texture",
    "cove/wr-4-cap/40/under-trowel-hybrid-quartz-double-broadcast-orange-peel-texture-trowel-texture",
    "cove/wr-6/40/under-trowel-hybrid-quartz-double-broadcast-orange-peel-texture-trowel-texture",
}
NO_AREA = {"empty/none"}
DECLARED = COMBINED_BREAK | FOUR_PLACES | NO_AREA
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
        name = " ".join(a["name"].replace("Primer: ", "").replace("Cove: ", "").split())
        assert name in used, "no recorded job prices %s" % a["name"]


# ── 1. the jobs ──────────────────────────────────────────────────────────────────────────────────
def test_every_job_outside_the_declared_departures_is_equal_to_the_workbook_to_the_dollar(golden, ran):
    by_id = {c["id"]: c for c in ran["cases"]}
    checked = 0
    for case in golden["cases"]:
        if case["id"] in DECLARED:
            continue
        w, g = case["out"], by_id[case["id"]]
        assert abs(g["raw"] - w["raw"]) <= _tolerance(w["raw"]), (case["id"], w["raw"], g["raw"])
        assert (g["material"], g["tooling"], g["sub_total"], g["gp"], g["taxes"], g["total"]) == (
            w["D40"], w["D62"], w["D70"], w["D73"], w["D82"], w["D88"]), case["id"]
        checked += 1
    assert checked >= 230, "the proof compared only %d jobs" % checked


def test_the_declared_departures_are_exactly_the_jobs_that_differ(golden, ran):
    assert _differing(golden, ran) == DECLARED, (
        "the jobs that differ from the workbook are not the declared ones. Differ and not declared: %s. Declared and "
        "equal (a departure closed, so say so): %s" % (
            sorted(_differing(golden, ran) - DECLARED), sorted(DECLARED - _differing(golden, ran))))


def test_each_departure_is_the_one_it_says_it_is(golden, ran):
    by_id = {c["id"]: c for c in ran["cases"]}
    want = {c["id"]: c for c in golden["cases"]}
    for cid in COMBINED_BREAK:
        w, g = want[cid]["out"], by_id[cid]
        assert g["raw"] > w["raw"] + 1, "%s: the library should charge the small-lot price where the sheet pays the large-lot one" % cid
    for cid in FOUR_PLACES:
        w, g = want[cid]["out"], by_id[cid]
        assert abs(g["raw"] - w["raw"]) < 0.01 and g["material"] == w["D40"] - 1, cid
    w, g = want["empty/none"]["out"], by_id["empty/none"]
    assert w["D62"] == 220 and g["tooling"] == 0 and g["material"] == 0, "a section with no area charges no tooling"


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
    "the section's labor is not read": (
        MODEL, "      labor: laborTotal(s.labor, model.conditions),", "      labor: 0,"),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_proof_goes_red_when_the_takeoff_or_the_model_changes(tmp_path, golden, ran, name):
    rel, old, new = BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new, also=[MODEL, "js/library-core.js", TAKEOFF])
    broken = run(frontend, tmp_path)
    jobs_red = _differing(golden, broken) != DECLARED
    chain_red = any(c.get("wrong") for c in broken["chain"])
    assert jobs_red or chain_red, "the proof did not notice: " + name
