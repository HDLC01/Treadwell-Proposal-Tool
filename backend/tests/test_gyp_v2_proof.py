"""Phase 14, the proof: a Gyp job priced through the v2 path matches Kyle's workbook, on all five Gyp tabs.

THE QUESTION. Hanz's decision (2026-10-07, 2026-10-12): match Kyle's workbook EXACTLY, odd rules included. The workbook
oracle already proves the markup chain on each Gyp tab (test_bid_engine.py: the chain called directly). What that cannot
prove is the plumbing between a v2 section and the chain, and the material that arrives at it. This does both, against
the workbook itself, through js/bid-model.js priceSection, the function the estimate page prices a Gyp section with:

  1. THE CHAIN, THROUGH A v2 SECTION. Every vector of the five Gyp oracle files (tests/fixtures/oracle/gyp-*.json: the
     chain's inputs typed at its boundary, answered by the workbook) is priced as a section filed under that tab, with
     its labor as a crew row priced by the hour, its fees and contingency the section's own, the job questions the
     model's conditions, and the gypsum, extras, sand, sound mat and its rolls as the page would hand them over. Equal
     to the CENT on every figure they share. It includes the sound mat at 279 rolls against 280 on the first tab (the
     rolls under a truckload ship at 10%, a truckload ships free: odd rule 6) and the soft-cost taper's two edges, a
     sub-total of 234,450 and one dollar more, 334,900 and one dollar more (the bands are strict).
  2. THE JOBS. tests/js/gyp-jobs-recorder.js typed 401 jobs into the five tabs of the template (the three areas, a
     thickness for each, the mix, ISO strip at all areas, the sound mat, moisture tests, a job either side of a truckload
     on every mat) and recorded what the workbook answered (tests/fixtures/gyp_jobs_golden.json). Each is built as a v2
     Gyp section over the library backend/ops/seed_library_from_workbook.py plans, and priced. The material split into
     gypsum, extras, sand and sound mat (before E38 rounds it), the rolls and the truckload, the tooling, the material
     total, the sub-total, the gross profit, the taxes and the total have to be EQUAL, to the dollar, for every job.

NO DECLARED DEPARTURES. The Epoxy proof carries ten (price breaks judged on two lines, coverage kept to three places, a
cost kept to four). Gyp has none: every price is a whole number of cents except the USG primer, which is stored as the
drum it is bought in (53 gallons at $891) so a gallon is exactly the sheet's `=891/53`, and a bag's yield is code. The
labor is the one input the proof hands in rather than derives: the sheet works its hours out of the takeoff
(mobilizations, bags a pour hour, the hard area a mat hour) and v2 types them, so a job is priced on the labor dollars
the workbook's own lines came to (E52), and the hours the sheet suggests are proved separately (`hours` below).

Each mutation at the bottom breaks a scratch copy of the takeoff, the model or the page and the proof has to notice.
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
HARNESS = TESTS / "js" / "gyp-v2-proof-harness.js"
GOLDEN = TESTS / "fixtures" / "gyp_jobs_golden.json"
TABS = ['Gyp (USG 1-8")', "Gyp (USG N12ULTRA)", 'Gyp (USG N25 1-4")', "Gyp (GWorx SC190)", "Gyp (FR)"]
SLUGS = {'Gyp (USG 1-8")': "gyp-usg-1-8", "Gyp (USG N12ULTRA)": "gyp-usg-n12ultra", 'Gyp (USG N25 1-4")': "gyp-usg-n25-1-4",
         "Gyp (GWorx SC190)": "gyp-gworx-sc190", "Gyp (FR)": "gyp-fr"}
TAKEOFF = "js/gyp-takeoff.js"


def run(frontend=FRONTEND, tmp=None):
    proc = run_node(HARNESS, frontend, plan_json(tmp), GOLDEN, ORACLE)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran(tmp_path_factory):
    require_node()
    return run(tmp=tmp_path_factory.mktemp("proof"))


@pytest.fixture(scope="module")
def golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


# the figures the workbook answers, and where the v2 section answers them
JOB_PAIRS = (("material", "E38"), ("material_escalation", "E39"), ("shipping", "E40"), ("material_total", "E41"),
             ("sub_total", "E69"), ("gp", "E72"), ("taxes", "E81"), ("total", "E87"))


def _tolerance(raw):
    return 1e-9 * max(raw, 1.0) + 1e-6


# ── the recorded answers are the workbook's, and current ─────────────────────────────────────────
def test_the_recorded_jobs_were_taken_from_the_template_and_the_engine_as_they_are_now(golden):
    digest, cells, names = template_hash(TABS)
    assert golden["template"] == {"hash": digest, "cells": cells, "names": names}, (
        "a Gyp tab or a defined name of the template changed since the jobs were recorded: re-run "
        "`node backend/tests/js/gyp-jobs-recorder.js --write` and read the diff")
    meta = json.loads((ORACLE / "meta.json").read_text(encoding="utf-8"))
    assert golden["engine"]["hyperformula"]["sri"] == meta["engine"]["hyperformula"]["sri"], (
        "the jobs were recorded by another HyperFormula than the oracle's")
    assert golden["tabs"] == TABS


def test_the_recorded_jobs_cover_what_the_proof_claims(golden):
    ids = [c["id"] for c in golden["cases"]]
    assert len(ids) == len(set(ids)) == 401
    for tab in TABS:
        mine = [c for c in golden["cases"] if c["tab"] == tab]
        kinds = {c["id"].split("/")[1] for c in mine}
        assert {"soft", "hard", "corridor", "all", "thick", "iso", "moisture", "mat", "truck", "job", "empty"} <= kinds, tab
    # the roll counts the truckload cases were built to hit: one under, exactly, one over, for every mat of every tab
    for c in golden["cases"]:
        if "/truck/" not in c["id"]:
            continue
        truck, rolls = c["out"]["H36"], c["out"]["B36"]
        want = {"below": truck - 1, "at": truck, "above": truck + 1}[c["id"].rsplit("/", 1)[1]]
        assert rolls == want, (c["id"], rolls, want)
    # and the sound mat's shipping really does flip at the truckload on the first tab (the figure the proof relies on)
    first = {c["id"].rsplit("/", 1)[1]: c["out"] for c in golden["cases"] if c["id"].startswith('Gyp (USG 1-8")/truck/0/')}
    assert first["below"]["B36"] == 279 and first["at"]["B36"] == 280 and first["below"]["H36"] == 280
    assert first["below"]["E40"] > first["at"]["E40"], "279 rolls ship the mat at 10%, 280 ship it free"


# ── 1. the chain, through a v2 section ───────────────────────────────────────────────────────────
def test_every_oracle_vector_of_all_five_gyp_tabs_is_equal_to_the_cent_through_a_v2_section(ran):
    chain = ran["chain"]
    skipped = [c for c in chain if c.get("skipped")]
    checked = [c for c in chain if not c.get("skipped")]
    assert [c for c in checked if c["wrong"]] == [], [c for c in checked if c["wrong"]][:5]
    assert {c["tab"] for c in checked} == set(TABS)
    for tab in TABS:
        assert sum(1 for c in checked if c["tab"] == tab) >= 140, "too few vectors of %s were compared" % tab
    # what v2 has no box for is counted, not hidden: a typed bond rate (bond is 0 and unwired). The sheet's own lodging, which v2 took from lines the estimator typed and this proof left out
    # (40 vectors) until round 6 of the travel work, is compared now: test_the_sheets_own_lodging_is_equal_to_the_cent_through_a_v2_section_with_the_nights_left_to_follow
    reasons = {}
    for c in skipped:
        reasons[c["skipped"]] = reasons.get(c["skipped"], 0) + 1
    assert reasons == {"bond": 60}, reasons
    assert len(checked) == 835
    assert sum(1 for c in checked if c.get("lodging")) == 40


# What the workbook answers for the four crews of its own lodging vectors, on a far job (`local0`; the same job local, `local1`, is $0 on every line): the nights it counts (Gyp!B64), the Lodging
# and Per Diem dollars (E64 and E65, each rounded up) and the two together (E67). Read off the recorded oracle, not off v2.
LODGING = {
    "one": (15.000000000000004, 1050, 675, 1725),
    "template": (18.000594177064766, 1261, 811, 2072),
    "mixedRates": (20.704099821746883, 1450, 932, 2382),
    "withTravel": (15.000356506238862, 1051, 676, 1727),
}


def test_the_sheets_own_lodging_is_equal_to_the_cent_through_a_v2_section_with_the_nights_left_to_follow(ran):
    """ROUND 6, N1. The 40 vectors that ask the template for its OWN nights (Gyp!B64 `=IF(B5="No",((E52-E51)/C46)/10)`, per diem `=B64`: 4 crews x 5 tabs x far and local) were left out of
    this proof because v2 took a Gyp job's Lodging and Per Diem from lines the estimator types. Each is priced now through a v2 section, the crew as v2 types it (in HOURS, a day of the sheet's
    ten, at its own rate, the drive its own row) and the job answered far, so the Lodging and Per Diem lines come on and FOLLOW THE LABOR: the nights, each line's dollars, the sum and every figure
    of the chain are equal to the workbook to the cent, on all five tabs. A local job is $0 on every line.

    THE RULE THAT WAS PICKED. A head count (guys x hours over ten, the man-days the page quotes) cannot match: three of the four crews differ from the sheet by a dollar or more, because the
    sheet counts labor DOLLARS: the labor total is rounded UP to a whole dollar before it is divided (`template`: 18.0006 nights where a head count says 18, $1,261 against $1,260 and $811 against
    $810; `withTravel`: 15.0004 against 15, $1,051 against $1,050), and a row paid another rate reads as extra days (`mixedRates`: 3 guys at $33.66 and 2 at $48, 20.704 nights where a head
    count says 19, $1,450 against $1,330). Hanz's decision of 2026-10-12 is to match the workbook EXACTLY, so a Gyp section counts the sheet's dollars (bid-model `sheetNights`, with the Gyp
    profile's divisor of 10), as a Polish section priced by rev 2 has since Phase 17; a head count would have been wrong by up to $120 a line and has no vector it alone satisfies.

    Mutation: count a Gyp section's head count; take the whole crew off as the drive; divide by 8; leave a Gyp section's nights typed (see MUTATIONS below)."""
    vectors = [c for c in ran["chain"] if c.get("lodging")]
    assert len(vectors) == 40 and {c["tab"] for c in vectors} == set(TABS)
    assert [c for c in vectors if c["wrong"]] == [], [c for c in vectors if c["wrong"]][:4]
    far = [c for c in vectors if c["far"]]
    assert len(far) == 20 and len([c for c in vectors if not c["far"]]) == 20
    for c in far:
        crew = c["id"].split("/")[1]
        nights, lodging, per_diem, travel = LODGING[crew]
        assert c["nights"] == pytest.approx(nights, abs=1e-9) and c["lodgingCost"] == lodging and c["perDiemCost"] == per_diem, (c["tab"], crew)
        assert c["sheet"] == {"lodging": lodging, "perDiem": per_diem, "travel": travel}, (c["tab"], crew)
    for c in vectors:
        if not c["far"]:
            assert c["lodgingCost"] == 0 and c["perDiemCost"] == 0 and c["sheet"]["travel"] == 0, c["id"]
    # the rule that was not picked: a head count matches the one crew whose dollars are whole and one rate, and misses the other three, on every tab
    for tab in TABS:
        missed = sorted(c["id"].split("/")[1] for c in far if c["tab"] == tab and (c["people"]["lodging"], c["people"]["perDiem"]) != (c["sheet"]["lodging"], c["sheet"]["perDiem"]))
        assert missed == ["mixedRates", "template", "withTravel"], (tab, missed)


def test_the_sound_mat_at_279_rolls_against_280_through_a_v2_section(ran):
    """Odd rule 6, the workbook's own probe on each of the five tabs: $10,000 of sound mat at a truckload less one, a
    truckload and a truckload more. The shipping is $1,000 (10%) below a truckload and nothing from it."""
    truck = {'Gyp (USG 1-8")': 280, "Gyp (USG N12ULTRA)": 260, 'Gyp (USG N25 1-4")': 208, "Gyp (GWorx SC190)": 384, "Gyp (FR)": 448}
    steps = [p for p in ran["probes"] if p["probe"] == "sound-mat-truckload"]
    assert len(steps) == 15 and {p["tab"] for p in steps} == set(TABS)
    for p in steps:
        assert p["truckload"] == truck[p["tab"]], p
        assert p["v2"] == p["workbook"], p
    for tab, size in truck.items():
        got = {p["rolls"]: p["v2"] for p in steps if p["tab"] == tab}
        assert got == {size - 1: 1000, size: 0, size + 1: 0}, (tab, got)
    first = {p["rolls"]: p["v2"] for p in steps if p["tab"] == 'Gyp (USG 1-8")'}
    assert first == {279: 1000, 280: 0, 281: 0}, "the sound mat ships at 10% below 280 rolls and free from it"


def test_the_fractional_bags_and_the_sand_through_a_v2_section_at_each_tabs_own_thickness(ran):
    """Odd rule 7, the workbook's probe: 1,000, 2,000 and 500 SF in the three areas. Bags are not rounded and the sand is
    worked out from their sum (8.68 tons on the first tab). Each tab opens on its own thickness (N25 pours 1 1/4" soft
    and 1" hard), so the bags differ by tab and v2 agrees with every one."""
    steps = [p for p in ran["probes"] if p["probe"] == "bags-fractional-sand-follows"]
    assert len(steps) == 5 and {p["tab"] for p in steps} == set(TABS)
    for p in steps:
        w, v = p["workbook"], p["v2"]
        assert v["bags"] == pytest.approx(w["bags"], abs=1e-9), p["tab"]
        assert v["total"] == pytest.approx(w["total"], abs=1e-9) and v["tons"] == pytest.approx(w["tons"], abs=1e-9), p["tab"]
    first = [p for p in steps if p["tab"] == 'Gyp (USG 1-8")'][0]["v2"]
    assert first["bags"] == pytest.approx([25.75, 2000 / 42 * 1.03, 12.875]) and first["tons"] == pytest.approx(8.679589285714288)
    n25 = [p for p in steps if p["tab"] == 'Gyp (USG N25 1-4")'][0]["v2"]
    assert n25["total"] != first["total"], "the thicker pour needs more bags"


def test_the_soft_cost_edges_are_in_the_chain_proof(ran):
    """The first tab's oracle vectors hold sub-totals of 234,450 and 334,900 and one dollar past each, so the equality
    of the chain above covers the soft costs' strict edges (and the seven GP tiers'), through the section."""
    by_tab = {}
    for c in ran["chain"]:
        if not c.get("skipped"):
            by_tab.setdefault(c["tab"], []).append(c)
    for tab in TABS:
        ids = {c["id"] for c in by_tab[tab]}
        oracle = json.loads((ORACLE / (SLUGS[tab] + ".json")).read_text(encoding="utf-8"))
        edges = {v["out"]["subTotal"]: v["out"]["softPct"] for v in oracle["vectors"] if v["id"] in ids}
        for edge in (234450, 234451, 334900, 334901):
            assert edge in edges, "no vector of %s has a sub-total of %d" % (tab, edge)
        assert edges[234450] == 0.09 and edges[234451] == 0.09 - 0.035
        assert edges[334900] == 0.09 - 0.035 and edges[334901] == 0.09 - 0.05, tab
        gp = {v["out"]["gpPct"] for v in oracle["vectors"] if v["id"] in ids}
        assert {0.45, 0.4, 0.35, 0.33, 0.28, 0.26, 0.24} <= gp, "all seven GP tiers are in %s" % tab


# ── 2. the jobs ──────────────────────────────────────────────────────────────────────────────────
def test_every_recorded_job_is_equal_to_the_workbook_to_the_dollar_on_every_tab(golden, ran):
    by_id = {j["id"]: j for j in ran["jobs"]}
    checked = 0
    for case in golden["cases"]:
        w, g = case["out"], by_id[case["id"]]
        assert g["priceable"] is True, case["id"]
        assert g["raw"]["gyp"] == pytest.approx(w["gyp"], abs=_tolerance(w["gyp"])), (case["id"], "gypsum")
        assert g["raw"]["extras"] == pytest.approx(w["extras"], abs=_tolerance(w["extras"])), (case["id"], "extras")
        assert g["raw"]["sand"] == pytest.approx(w["E33"], abs=_tolerance(w["E33"])), (case["id"], "sand")
        assert g["raw"]["soundMat"] == pytest.approx(w["E36"], abs=_tolerance(w["E36"])), (case["id"], "sound mat")
        assert g["rolls"] == w["B36"] and g["truckload"] == w["H36"], (case["id"], "rolls and truckload")
        assert g["tooling"] == w["E61"], (case["id"], "tooling")
        for mine, cell in JOB_PAIRS:
            assert g[mine] == w[cell], (case["id"], mine, cell, w[cell], g[mine])
        checked += 1
    assert checked == 401


def test_the_bags_the_sand_and_the_areas_are_the_workbooks_before_any_rounding(golden, ran):
    by_id = {j["id"]: j for j in ran["jobs"]}
    for case in golden["cases"]:
        w, g = case["out"], by_id[case["id"]]
        for area in ("soft", "hard", "corridor"):
            assert g["bags"][area] == pytest.approx(w["bags"][area], abs=1e-9), (case["id"], area)
            assert g["areas"][area] == w["areas"][area], (case["id"], area)
        assert g["bags"]["total"] == pytest.approx(w["H33"], abs=1e-9), case["id"]
        assert g["tons"] == pytest.approx(w["B33"], abs=1e-9), case["id"]


def test_the_hours_the_sheet_suggests_are_the_sheets_own_for_the_hours_a_takeoff_decides(golden, ran):
    """The sheet derives three of its labor hours from the takeoff (mat time from the hard area, the pour from the bags)
    and the rest from mobilizations and distance, which the recorder left at zero. v2 quotes them, so they must agree."""
    by_id = {j["id"]: j for j in ran["jobs"]}
    for case in golden["cases"]:
        w, g = case["out"]["hours"], by_id[case["id"]]["hours"]
        assert g["mat"] == pytest.approx(w["mat"], abs=1e-9) and g["pour"] == pytest.approx(w["pour"], abs=1e-9), case["id"]
        assert g["prep"] == w["prep"] == 0 and g["unload"] == w["unload"] == 0 and g["travel"] == w["travel"] == 0, case["id"]


def test_the_proof_is_not_vacuous_on_the_odd_rules(golden, ran):
    """Odd rule 7 (fractional bags) and odd rule 6 (the truckload) actually bite in the recorded jobs, and v2 reproduces
    them: a bag count that is not whole, and a job whose mat shipping changed between 279 and 280 rolls."""
    by_id = {j["id"]: j for j in ran["jobs"]}
    fractional = [c for c in golden["cases"] if c["out"]["bags"]["soft"] % 1 != 0 and by_id[c["id"]]["bags"]["soft"] % 1 != 0]
    assert len(fractional) > 100
    pairs = {}
    for c in golden["cases"]:
        if "/truck/" in c["id"]:
            tab, _kind, mat, edge = c["id"].split("/")
            pairs.setdefault((tab, mat), {})[edge] = (c["out"]["E40"], by_id[c["id"]]["shipping"], c["out"]["B36"] * c["out"]["D36"])
    for key, p in pairs.items():
        assert p["below"][0] == p["below"][1] and p["at"][0] == p["at"][1] and p["above"][0] == p["above"][1], key
    # the sound mat ships at 10% below a truckload and free at it, so the roll just below costs MORE to ship than the one at
    # the truckload, though it holds a roll fewer
    assert all(p["below"][0] > p["at"][0] for p in pairs.values())


# ── the proof can go red ─────────────────────────────────────────────────────────────────────────
MUTATIONS = {
    # the takeoff
    "bags are rounded up": (
        TAKEOFF, "return (num(sf) / yieldBag) * (1 + WASTE.gyp);", "return Math.ceil((num(sf) / yieldBag) * (1 + WASTE.gyp));"),
    "the hard surface gets no extra yield": (TAKEOFF, "var HARD_EXTRA = 12;", "var HARD_EXTRA = 0;"),
    "sand is worked out from whole bags": (
        TAKEOFF, "var tons = ((sandLb * bags.total) / POUNDS_A_TON) * (1 + WASTE.sand);",
        "var tons = ((sandLb * Math.ceil(bags.total)) / POUNDS_A_TON) * (1 + WASTE.sand);"),
    "the mat rolls are not rounded up": (
        TAKEOFF, "var rolls = areas.hard > 0 ? roundUp((areas.hard / m.sf) * (1 + WASTE.soundMat)) : 0;",
        "var rolls = areas.hard > 0 ? Math.floor((areas.hard / m.sf) * (1 + WASTE.soundMat)) : 0;"),
    "the mat's truckload is the first tab's for every mat": (
        TAKEOFF, "rolls: rolls, truckload: m.truckload,", "rolls: rolls, truckload: 280,"),
    "ISO strip goes on every area whatever is asked": (
        TAKEOFF, "var isoRolls = (isoAll ? areas.soft + areas.hard + areas.corridor : areas.hard) / p.isoSf;",
        "var isoRolls = (areas.soft + areas.hard + areas.corridor) / p.isoSf;"),
    "the primer covers the hard area too": (
        TAKEOFF, "var primerGal = (areas.soft + areas.corridor) / PRIMER_SF;",
        "var primerGal = (areas.soft + areas.hard + areas.corridor) / PRIMER_SF;"),
    "tape is bought on the soft area": (TAKEOFF, "var tapeRolls = areas.hard / TAPE_SF;", "var tapeRolls = areas.soft / TAPE_SF;"),
    "tooling is not rounded": (
        TAKEOFF, "return roundUp(num(tests) * TOOLING.moistureTest) + roundUp(num(sf) * TOOLING.consumablesPerSf);",
        "return num(tests) * TOOLING.moistureTest + num(sf) * TOOLING.consumablesPerSf;"),
    # the model and the engine, which the section is priced through
    "the tab's own truckload always wins over the mat's": (
        "js/bid-model.js", "if (profile.quirks.shippingRule === \"gyp-split\" && !(num(input.truckload) > 0)) {",
        "if (profile.quirks.shippingRule === \"gyp-split\") {"),
    "the sound mat ships free at one roll short of a truckload": (
        "js/bid-engine.js", "(extras + (rolls < truckload ? soundMat : 0))", "(extras + (rolls < truckload - 1 ? soundMat : 0))"),
    "the soft cost taper starts a dollar early": (
        "js/bid-profiles.js", "IF(E69>334900,.05,IF(E69>234450,.035,0))", "IF(E69>334899,.05,IF(E69>234450,.035,0))"),
    "a Gyp section escalates labor only with prevailing wage": (
        "js/bid-engine.js", "var esc_pct = (q.escalationAlwaysOn || cond.prevailing_wage) ? rate(\"esc_pct\") : 0;",
        "var esc_pct = (cond.prevailing_wage) ? rate(\"esc_pct\") : 0;"),
}

# What each mutation breaks, so a mutation cannot go unnoticed because the check that should see it was the wrong one.
# A takeoff mutation is seen by the jobs; the model and engine ones by the chain (and the jobs that pass through them).
SEEN_BY = {name: ("jobs" if rel == TAKEOFF else "chain") for name, (rel, _old, _new) in MUTATIONS.items()}


def _jobs_differ(golden, ran):
    by_id = {j["id"]: j for j in ran["jobs"]}
    return [c["id"] for c in golden["cases"]
            if any(by_id[c["id"]][mine] != c["out"][cell] for mine, cell in JOB_PAIRS)
            or by_id[c["id"]]["tooling"] != c["out"]["E61"] or by_id[c["id"]]["rolls"] != c["out"]["B36"]
            or abs(by_id[c["id"]]["tons"] - c["out"]["B33"]) > 1e-9
            or abs(by_id[c["id"]]["bags"]["total"] - c["out"]["H33"]) > 1e-9]


def _chain_wrong(ran):
    return [c for c in ran["chain"] if c.get("wrong")]


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_the_proof_goes_red_when_the_code_changes(tmp_path, golden, name):
    require_node()
    rel, old, new = MUTATIONS[name]
    frontend = break_source(tmp_path, rel, old, new)
    # the rest of the frontend the harness loads comes from the real tree
    for other in ("js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js", "js/gyp-takeoff.js", "js/excel-math.js",
                  "js/library-core.js", "js/work-types.js", "js/markup-core.js"):
        dest = frontend / other
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((FRONTEND / other).read_bytes())
    broken = run(frontend=frontend, tmp=tmp_path)
    jobs, chain = _jobs_differ(golden, broken), _chain_wrong(broken)
    if SEEN_BY[name] == "jobs":
        assert jobs, "the proof did not notice: " + name
    else:
        assert jobs or chain, "the proof did not notice: " + name
