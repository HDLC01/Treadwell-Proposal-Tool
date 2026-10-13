"""Phase 15, the proof: a Seal option priced through the v2 path matches Kyle's workbook, on both Seal tabs.

THE QUESTION. Hanz's decision (2026-10-07, 2026-10-12): match Kyle's workbook EXACTLY, odd rules included. The workbook
oracle already proves the markup chain on each Seal tab (test_bid_engine.py: the chain called directly). What that cannot
prove is the plumbing between a v2 OPTION section and the chain, and the material that arrives at it. This does both,
against the workbook itself, through js/bid-model.js priceSection, the function the estimate page prices an option with:

  1. THE CHAIN, THROUGH A v2 OPTION. Every vector of the two Seal oracle files (tests/fixtures/oracle/seal.json and
     seal-jnts.json: the chain's inputs typed at its boundary, answered by the workbook) is priced as a section of kind
     "option" filed under that tab, with its labor as a crew row, its fees and contingency the section's own, the job
     questions the model's conditions, and the material and tooling as the page would hand them over. Equal to the CENT on
     every figure they share. It includes Seal's sixth gross profit rung on its edge (odd rule "Seal's gross profit ladder":
     30% up to a sub-total of 42,499 and 28% from 42,500, against Polish's 30% from 32,500 on).
  2. THE JOBS. tests/js/seal-jobs-recorder.js typed 80 jobs into the two Seal tabs (the area either side of the joint filler's
     3,500 SF and the tooling's $150 floor, a new floor and a renovation, one coat of sealer or two, joint filler on and off,
     the crew's days) and recorded what the workbook answered (tests/fixtures/seal_jobs_golden.json). Each is built as a v2
     Seal option over the library backend/ops/seed_library_from_workbook.py plans, and priced. The material before it is
     rounded, the tooling, the material total, the labor, the sub-total, the taxes and the total have to be EQUAL, to the
     dollar, for every job.

NO DECLARED DEPARTURES in the figures proved here. What v2 has no box for is COUNTED, not hidden: a Hard Bid answer (Hanz
removed the switch, 2026-10-03), a typed bond rate (bond is 0 and unwired) and the sheet's own lodging (v2 takes Hotel and
Per Diem from the lines the estimator types, once for the job).

Each mutation at the bottom breaks a scratch copy of the takeoff, the profile or the engine and the proof has to notice.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from _golden_support import FRONTEND, break_source
from _node import last_json_line, require_node, run_node
from _oracle_support import ORACLE, template_hash
from _seed_support import plan_json

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "seal-v2-proof-harness.js"
GOLDEN = TESTS / "fixtures" / "seal_jobs_golden.json"
TABS = ["Seal", "Seal (+Jnts)"]
HARNESS_FILES = ["js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js", "js/seal-takeoff.js", "js/library-core.js"]


def run(frontend=FRONTEND, tmp=None):
    proc = run_node(HARNESS, frontend, plan_json(tmp), GOLDEN, ORACLE)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran(tmp_path_factory):
    require_node()
    return run(tmp=tmp_path_factory.mktemp("seal-proof"))


@pytest.fixture(scope="module")
def golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


# the figures the workbook answers, and where the v2 option answers them
JOB_PAIRS = (("material", "D31"), ("material_total", "D33"), ("tooling", "D55"), ("labor", "D45"), ("sub_total", "D64"),
             ("sales_tax", "D74"), ("total", "D82"))


# ── the recorded answers are the workbook's, and current ─────────────────────────────────────────
def test_the_recorded_jobs_were_taken_from_the_template_and_the_engine_as_they_are_now(golden):
    digest, cells, names = template_hash(TABS)
    assert golden["template"] == {"hash": digest, "cells": cells, "names": names}, (
        "a Seal tab or a defined name of the template changed since the jobs were recorded: re-run "
        "`node backend/tests/js/seal-jobs-recorder.js --write` and read the diff")
    meta = json.loads((ORACLE / "meta.json").read_text(encoding="utf-8"))
    assert golden["engine"]["hyperformula"]["sri"] == meta["engine"]["hyperformula"]["sri"], (
        "the jobs were recorded by another HyperFormula than the oracle's")
    assert golden["tabs"] == TABS


def test_the_recorded_jobs_cover_what_the_proof_claims(golden):
    ids = [c["id"] for c in golden["cases"]]
    assert len(ids) == len(set(ids)) == 80
    for tab in TABS:
        mine = [c for c in golden["cases"] if c["tab"] == tab]
        kinds = {c["id"].split("/")[1] for c in mine}
        assert {"sf", "coats1", "jf", "days"} <= kinds, tab
        sfs = {c["in"]["sf"] for c in mine}
        assert {500, 3499, 3500, 3501, 250000} <= sfs, "the joint filler's 3,500 SF edge and the tooling floor are in " + tab
        assert {c["in"].get("reno") for c in mine if c["id"].startswith(tab + "/sf/")} == {True, False}
    # the cases are not alike: the patch price, the tooling floor, the joint filler kits and the coats really move the answer
    seal = {c["id"]: c["out"] for c in golden["cases"] if c["tab"] == "Seal"}
    assert seal["Seal/sf/12345/reno"]["D17"] == pytest.approx(3 * seal["Seal/sf/12345/new"]["D17"]), "a renovation pays three times the patch"
    assert seal["Seal/sf/500/new"]["D51"] == 150 and seal["Seal/sf/1000/new"]["D51"] == 270, "the $150 tooling floor, then $0.27 a SF"
    assert seal["Seal/coats1/12345/new"]["D21"] == 0 and seal["Seal/sf/12345/new"]["D21"] > 0, "one coat drops the second sealer line"
    assert seal["Seal/jf/on/3500"]["B29"] == 1 and seal["Seal/jf/on/3501"]["B29"] == 2, "a kit for every 3,500 SF, rounded up"
    assert all(c["out"]["B29"] == 0 for c in golden["cases"] if c["id"].startswith("Seal/sf/"))
    jnts = {c["id"]: c["out"] for c in golden["cases"] if c["tab"] == "Seal (+Jnts)"}
    assert jnts["Seal (+Jnts)/sf/3501/new"]["B29"] == 2 and jnts["Seal (+Jnts)/jf/off/3501"]["B29"] == 0


# ── 1. the chain, through a v2 option ────────────────────────────────────────────────────────────
def test_every_oracle_vector_of_both_seal_tabs_is_equal_to_the_cent_through_a_v2_option(ran):
    chain = ran["chain"]
    skipped = [c for c in chain if c.get("skipped")]
    checked = [c for c in chain if not c.get("skipped")]
    assert [c for c in checked if c["wrong"]] == [], [c for c in checked if c["wrong"]][:5]
    assert {c["tab"] for c in checked} == set(TABS)
    for tab in TABS:
        assert sum(1 for c in checked if c["tab"] == tab) == 102, "too few vectors of %s were compared" % tab
    # what v2 has no box for is counted, not hidden
    reasons = {}
    for c in skipped:
        reasons[c["skipped"]] = reasons.get(c["skipped"], 0) + 1
    assert reasons == {"hard bid": 120, "bond": 24, "lodging": 16}, reasons
    assert len(chain) == 364 and len(checked) == 204


def test_each_of_those_is_priced_as_an_option_section_by_the_seal_profile(ran):
    """The proof would mean nothing if the section were a base or priced by another profile: every checked vector is a
    section of kind option, on seal@1, which carries the sixth rung."""
    checked = [c for c in ran["chain"] if not c.get("skipped")]
    assert {c["kind"] for c in checked} == {"option"} and {c["profile"] for c in checked} == {"seal@1"}


def test_the_sixth_gross_profit_rung_is_on_its_edge_through_the_option(ran):
    """Seal's GP is 30% up to a sub-total of 42,499 and 28% from 42,500; Polish's stays 30% from 32,500. The oracle has the
    sub-total one dollar either side, on both tabs, and v2 charges what the workbook did."""
    by = {(c["tab"], c["id"]): c for c in ran["chain"] if not c.get("skipped")}
    for tab in TABS:
        rungs = [by[(tab, "edge/gpPct/42500/%s" % d)]["gpPct"] for d in ("-1", "0", "+1")]
        assert rungs == [0.3, 0.28, 0.28], (tab, rungs)
        assert by[(tab, "edge/gpPct/32500/0")]["gpPct"] == 0.3, "Seal pays 30% at 32,500, where Polish steps down to 30% and stays"


# ── 2. the jobs ──────────────────────────────────────────────────────────────────────────────────
def test_every_recorded_job_is_equal_to_the_workbook_to_the_dollar_on_both_tabs(golden, ran):
    by_id = {j["id"]: j for j in ran["jobs"]}
    checked = 0
    for case in golden["cases"]:
        w, g = case["out"], by_id[case["id"]]
        assert g["priceable"] is True and g["kind"] == "option", case["id"]
        assert g["material_raw"] == pytest.approx(w["material"], abs=1e-6), (case["id"], "material before it is rounded")
        assert g["patch"] == pytest.approx(w["D17"], abs=1e-6), (case["id"], "patch")
        for mine, cell in JOB_PAIRS:
            assert g[mine] == w[cell], (case["id"], mine, cell, w[cell], g[mine])
        checked += 1
    assert checked == 80


def test_the_jobs_prove_the_option_through_a_real_library_and_not_the_numbers_handed_in(golden, ran):
    """The material of a job is arrived at from four seeded assemblies, the patch rows and the tooling constants. A job on
    the other tab's assembly would not match: Seal (+Jnts) is the same sealer plus a kit of joint filler."""
    by_id = {j["id"]: j for j in ran["jobs"]}
    seal = by_id["Seal/sf/12345/new"]["material_raw"]
    jnts = by_id["Seal (+Jnts)/sf/12345/new"]["material_raw"]
    assert jnts - seal == 4 * 500, "12,345 SF is four kits of joint filler at $500"
    assert by_id["Seal/sf/12345/reno"]["material_raw"] - seal == pytest.approx(12345 * 0.10)


# ── the checks go red when the code changes ──────────────────────────────────────────────────────
PROOF_BREAKS = {
    "the patch ignores a renovation": (
        "js/seal-takeoff.js", '    return a * unitPrice(items, reno ? "patchReno" : "patchNew").cost;',
        '    return a * unitPrice(items, "patchNew").cost;'),
    "the tooling has no $150 floor": (
        "js/seal-takeoff.js", "    return roundUp(perSf > TOOLING.min ? perSf : TOOLING.min);", "    return roundUp(perSf);"),
    "the tooling is $0.17 a square foot": (
        "js/seal-takeoff.js", "  var TOOLING = { perSf: 0.27, min: 150 };", "  var TOOLING = { perSf: 0.17, min: 150 };"),
    "the option leaves its tooling out of the material it hands over": (
        "js/seal-takeoff.js", "    return { material: sum + patch, tooling: toolingCost(ctx.sf), patch: patch };",
        "    return { material: sum + patch, tooling: 0, patch: patch };"),
    "the patch is not added to the material": (
        "js/seal-takeoff.js", "    return { material: sum + patch, tooling: toolingCost(ctx.sf), patch: patch };",
        "    return { material: sum, tooling: toolingCost(ctx.sf), patch: patch };"),
    "the sixth gross profit rung is Polish's": (
        "js/bid-profiles.js", '"MARKUP(BAND(subtotal, 6500,52%, 15000,45%, 22500,35%, 32500,32%, 42500,30%, 28%))";',
        '"MARKUP(BAND(subtotal, 6500,52%, 15000,45%, 22500,35%, 32500,32%, 30%))";'),
    "the labor burden forgets the escalation": (
        "js/bid-engine.js", "    var burden = roundUp((labor + escalation) * burden_pct);", "    var burden = roundUp((labor) * burden_pct);"),
}


@pytest.mark.parametrize("name", sorted(PROOF_BREAKS))
def test_the_proof_goes_red_when_the_code_changes(tmp_path, name):
    require_node()
    rel, old, new = PROOF_BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new, also=HARNESS_FILES)
    proc = run_node(HARNESS, frontend, plan_json(tmp_path), GOLDEN, ORACLE)
    assert proc.returncode == 0, proc.stderr
    got = last_json_line(proc.stdout)
    golden_ = json.loads(GOLDEN.read_text(encoding="utf-8"))
    by_id = {j["id"]: j for j in got["jobs"]}
    wrong_chain = [c for c in got["chain"] if not c.get("skipped") and c["wrong"]]
    wrong_jobs = []
    for case in golden_["cases"]:
        w, g = case["out"], by_id[case["id"]]
        if not g["priceable"] or any(g[mine] != w[cell] for mine, cell in JOB_PAIRS) or abs(g["material_raw"] - w["material"]) > 1e-6:
            wrong_jobs.append(case["id"])
    assert wrong_chain or wrong_jobs, "the proof did not notice: " + name
