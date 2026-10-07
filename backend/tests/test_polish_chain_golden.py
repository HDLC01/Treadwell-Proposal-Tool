"""The Polish bid chain, recorded before the v2 program rewrites what stands behind it.

backend/tests/fixtures/polish_chain_golden.json holds what js/bid-model.js (TWBidModel)
answers for 2,228 deliberately awkward inputs: markupChain over every GP edge and all 256 settings
of the eight job conditions, every shape the remodel rate arrives in and a sweep of dirty values;
the number helpers; labor, travel and takeoff; the conditions and what they write into Kyle's
workbook; the default readers; the model; the labor calculator; and what a new bid is seeded with.
It was cut from a clean export of an origin/staging commit (meta.commit says which) by
tests/js/gen-chain-golden.js, whose recipe lists inputs only: every answer is the real code's. Phase 3
cut it from 3f94ed2. Phase 4 re-cut it on d569332 and exactly ONE vector moved, `model/migrate/unknownKeys`
(the model now keeps the keys it does not know); the other 2,227 are as Phase 3 recorded them.

Phases 4 to 10 move this code: the model module is renamed, ROUNDUP and the number helpers move to a
leaf module, rates and the GP ladder become profile data, the chain becomes an engine. Each must
leave this file's comparison green, or change it on purpose, in view, as a diff of lines somebody
can read. Where a later phase legitimately moves a number (Phase 17, new bids only) the fixture is
regenerated in that PR and the diff IS the review.

THE COMPARISON IS assert.deepStrictEqual, run in node against the decoded file. JSON cannot say -0,
NaN, Infinity or undefined, and a comparison through JSON would let a refactor turn -0 into 0 or a
NaN into null unseen. The golden stores each as a tagged value and the tests below prove, by
breaking a copy of the module on purpose, that those very changes turn the comparison red.

Run under node; a missing node FAILS under CI (tests/_node.py).
"""
import json
import re

import pytest

from _golden_support import FIXTURES, break_source, compare, generate, load
from _node import require_node

GOLDEN = FIXTURES / "polish_chain_golden.json"
GENERATOR = "gen-chain-golden.js"
MODULE = "js/bid-model.js"


@pytest.fixture(scope="module")
def node():
    return require_node()


@pytest.fixture(scope="module")
def golden():
    return load(GOLDEN)


@pytest.fixture(scope="module")
def vectors(golden):
    return {v["id"]: v for v in golden["vectors"]}


# ── the comparison itself ────────────────────────────────────────────────────
def test_this_trees_polish_chain_answers_exactly_as_the_golden_says(node):
    """The whole point. Red here means a number moved: read the first difference below and decide
    whether it is the change you meant. If it is, regenerate (the message says how) and review the
    fixture diff line by line."""
    proc = compare(GENERATOR, GOLDEN)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == {"ok": True, "n": load(GOLDEN)["meta"]["n"]}


def test_the_recipe_is_deterministic(node):
    """No random numbers, no clock: two runs print the same bytes, so the file regenerates exactly
    and a diff after regeneration is a change in the code, never in the dice."""
    assert generate(GENERATOR) == generate(GENERATOR)


def test_the_golden_says_where_it_came_from(golden):
    meta = golden["meta"]
    assert re.fullmatch(r"[0-9a-f]{40}", meta["commit"]), "cut from a clean export of a named origin/staging commit"
    assert meta["recipe_version"] == 1
    assert meta["n"] == len(golden["vectors"]) == len({v["id"] for v in golden["vectors"]})
    assert meta["generator"] == "backend/tests/js/gen-chain-golden.js"


# ── the golden is not vacuous: it holds the cases it exists for ──────────────
def test_every_gp_band_is_reached(vectors):
    bands = {v["out"]["gp_pct"] for v in vectors.values() if v["fn"] == "markupChain" and "out" in v
             and isinstance(v["out"], dict) and isinstance(v["out"].get("gp_pct"), (int, float))}
    assert bands == {0.52, 0.45, 0.35, 0.32, 0.3}


EDGE_LANDINGS = {
    # route, input -> the sub-total it must land on. Travel alone is exact; material alone is
    # m + ROUNDUP(m * 2%); labor alone is labor + ROUNDUP(labor * 12%) (+ 5% under prevailing wage).
    "chain/edge/travel/6499": 6499, "chain/edge/travel/6500": 6500, "chain/edge/travel/6501": 6501,
    "chain/edge/travel/14999": 14999, "chain/edge/travel/15000": 15000, "chain/edge/travel/15001": 15001,
    "chain/edge/travel/22499": 22499, "chain/edge/travel/22500": 22500, "chain/edge/travel/22501": 22501,
    "chain/edge/travel/32499": 32499, "chain/edge/travel/32500": 32500, "chain/edge/travel/32501": 32501,
    "chain/edge/material/6371": 6499, "chain/edge/material/6372": 6500, "chain/edge/material/6373": 6501,
    "chain/edge/material/14704": 14999, "chain/edge/material/14705": 15000, "chain/edge/material/14706": 15001,
    "chain/edge/material/22057": 22499, "chain/edge/material/22058": 22500, "chain/edge/material/22059": 22501,
    "chain/edge/material/31861": 32499, "chain/edge/material/31862": 32500, "chain/edge/material/31863": 32501,
    "chain/edge/labor/pw-false/5802": 6499, "chain/edge/labor/pw-false/5803": 6500, "chain/edge/labor/pw-false/5804": 6501,
    "chain/edge/labor/pw-false/13392": 15000, "chain/edge/labor/pw-false/20088": 22499,
    "chain/edge/labor/pw-false/20089": 22500, "chain/edge/labor/pw-false/29017": 32500,
    "chain/edge/labor/pw-true/5525": 6499, "chain/edge/labor/pw-true/5526": 6500, "chain/edge/labor/pw-true/5527": 6501,
    "chain/edge/labor/pw-true/12754": 15000, "chain/edge/labor/pw-true/19131": 22499,
    "chain/edge/labor/pw-true/19132": 22500, "chain/edge/labor/pw-true/27635": 32500,
}


@pytest.mark.parametrize("vector_id, sub_total", sorted(EDGE_LANDINGS.items()))
def test_each_gp_edge_vector_lands_on_the_edge_its_id_names(vectors, vector_id, sub_total):
    """B67 is strictly `<`, so 6,500 belongs to the 45% band and 6,499 to the 52% one. A vector that
    drifted one dollar off its edge would still be green and test nothing; this pins where each
    one actually lands, and the band on each side of every edge."""
    out = vectors[vector_id]["out"]
    assert out["sub_total"] == sub_total
    edges = [6500, 15000, 22500, 32500]
    expected_band = [0.52, 0.45, 0.35, 0.32, 0.3][sum(1 for e in edges if sub_total >= e)]
    assert out["gp_pct"] == expected_band


def test_all_256_condition_settings_are_there_and_the_live_ones_move_the_bid(vectors):
    combos = [v for k, v in vectors.items() if k.startswith("chain/cond256/")]
    assert len(combos) == 256
    assert {tuple(sorted(v["args"][0]["conditions"].items())) for v in combos}.__len__() == 256
    # the three conditions the chain reads change the total; eight combinations of them, eight totals
    live = {}
    for v in combos:
        c = v["args"][0]["conditions"]
        live.setdefault((c["prevailing_wage"], c["taxable"], c["remodel_tax"]), set()).add(v["out"]["total"])
    assert len(live) == 8 and len({t for totals in live.values() for t in totals}) >= 8


def test_the_remodel_rate_is_pinned_in_every_shape_it_arrives_in(vectors):
    """Null / absent / "" is "nobody picked a county": the 6.5% state floor. An explicit 0 is a
    Missouri county, exempt: no tax at all. They must never be read as one another."""
    pct = {k.split("/", 3)[3]: v["out"]["remodel_pct"] for k, v in vectors.items()
           if k.startswith("chain/remodel/") and k.endswith("/on")}
    assert pct["absent/on"] == 0.065 and pct["null/on"] == 0.065 and pct['""/on'] == 0.065
    assert pct["0/on"] == 0 and pct['"0"/on'] == 0
    assert pct['"0.07975"/on'] == 0.07975 and pct["0.07975/on"] == 0.07975
    off = [v["out"]["remodel_pct"] for k, v in vectors.items() if k.startswith("chain/remodel/") and k.endswith("/off")]
    assert off and set(off) == {0}, "a rate handed in with the toggle off must tax nothing"


def test_dirty_inputs_are_all_there(vectors):
    for field in ("material", "labor", "sf", "fees", "contingency", "travel"):
        ids = [k for k in vectors if k.startswith("chain/dirty/%s/" % field)]
        text = " ".join(ids)
        for needle in ('"12,500"', '"$1,200"', '/""', "null", "undefined", "NaN", "Infinity", "/absent"):
            assert needle in text, (field, needle)


def test_what_json_would_hide_is_in_the_file():
    """Negative zero, NaN and undefined are stored as tagged values and appear in both inputs and
    answers: if a recipe edit dropped them, the comparison would go back to being JSON-blind."""
    raw = GOLDEN.read_text(encoding="utf-8")
    for tag in ('{"$":"-0"}', '{"$":"NaN"}', '{"$":"undefined"}', '{"$":"Infinity"}'):
        assert tag in raw, tag
    # an ANSWER, not just an input, is negative zero and NaN
    assert re.search(r'"out":\{"\$":"-0"\}', raw)
    assert re.search(r'"rate":\{"\$":"NaN"\}', raw)


def test_a_latent_crash_is_pinned_not_fixed(vectors):
    """seedTakeoffSf over a takeoff with a null row throws TypeError today. Recorded as it is: a
    later phase that fixes it changes this one line, visibly."""
    assert vectors["seed/takeoffSf/holes"].get("threw") == "TypeError"


def test_a_function_that_mutates_its_argument_is_flagged(vectors):
    mutators = sorted(k for k, v in vectors.items() if v.get("mut"))
    assert "seed/setMeasurement/0" in mutators and "seed/takeoffSf/blankBoth" in mutators
    assert not [k for k in mutators if k.startswith(("chain/", "labor/", "ltot/", "trv/"))], \
        "the pricing functions are pure; one that starts writing into its input is a finding"


def test_what_a_function_left_in_its_argument_is_recorded_and_not_only_that_it_wrote(vectors):
    """setMeasurement returns nothing: its whole effect is the rows it edits. `mut` says THAT it wrote
    and `after` says WHAT. With `mut` alone, a refactor that wrote another number, or into another row,
    left this file green (see the setMeasurement changes in the table of broken copies below)."""
    mutators = {k for k, v in vectors.items() if v.get("mut")}
    assert mutators
    assert {k for k, v in vectors.items() if "after" in v} == mutators, "`after` is there exactly where `mut` is"


# What typing a number into a takeoff row must leave, as (measurement, same_floor) for each row, and None
# for a hole in the list. Cut by hand from the comment on setMeasurement, then checked against the
# golden, so a regenerated file cannot drift off the layout its id names without somebody noticing.
LEFT_BEHIND = {
    # floor(): the carrier a1, a same-floor row a3, an LF row a2, a same-floor row a4 that is switched OFF
    "seed/setMeasurement/0": [(12000, False), (12000, True), (300, False), (12000, True)],   # the carrier drags both, the OFF one too
    "seed/setMeasurement/1": [(10000, False), (4000, False), (300, False), (10000, True)],   # typed over: stops sharing, nothing drags
    "seed/setMeasurement/2": [(10000, False), (10000, True), (350, False), (10000, True)],   # an LF row is not a carrier
    "seed/setMeasurement/3": [(10000, False), (10000, True), (300, False), (99, False)],     # typed over while OFF: stops sharing
    "seed/setMeasurement/4": [("", False), ("", True), (300, False), ("", True)],            # clearing the carrier clears them too
    "seed/setMeasurement/5": [("9,000", False), ("9,000", True), (300, False), ("9,000", True)],
    "seed/setMeasurement/offCarrier": [(200, False), (100, True)],                           # an OFF carrier drags nothing
    "seed/setMeasurement/sameFloorAbove": [(12000, True), (12000, False), (12000, True)],    # above the carrier counts too
    "seed/setMeasurement/plainRowsSameNumber": [(12000, False), (10000, False), (10000, False), (12000, True)],
    "seed/setMeasurement/sameFloorHoldsOther": [(12000, False), (12000, True), (7500, True)],
    "seed/setMeasurement/lfCarrierSameNumber": [(12000, False), (10000, True)],
    "seed/setMeasurement/typedAsText": [("12,000", False), ("12,000", True), ("12,000", True)],
    "seed/setMeasurement/nullRowInList": [None, (12000, False), (12000, True)],
}


@pytest.mark.parametrize("vector_id, left", sorted(LEFT_BEHIND.items()))
def test_each_setmeasurement_vector_leaves_the_rows_its_id_promises(vectors, vector_id, left):
    rows = vectors[vector_id]["after"][0]
    assert [None if r is None else (r["measurement"], bool(r.get("same_floor"))) for r in rows] == left


def test_every_setmeasurement_vector_that_writes_is_in_that_table(vectors):
    """A vector added to the recipe without its expected rows here would be pinned by the golden alone."""
    writers = {k for k, v in vectors.items() if v["fn"] == "setMeasurement" and v.get("mut")}
    assert writers == set(LEFT_BEHIND)


REQUIRED_FUNCTIONS = {
    "markupChain", "gpPct", "roundUp", "num", "money", "money2", "pct", "fmtSf", "laborCost", "laborTotal",
    "removeExistingHand", "travelManDays", "travelQty", "travelLineCost", "travelCosts", "normalizeTravel",
    "takeoffSf", "measuredSf", "dyeCost", "jointFillerCost", "conditionCellWrites", "conditionsFromCells",
    "seedConditionDefaults", "conditionsUnstated", "seedConditionsShown", "conditionShown", "laborRateOrShipped",
    "laborRateFromRules", "feesFromRules", "travelRatesFromRules", "freshModel", "migrateModel", "blockers",
    "laborCalcValues", "applyLaborCalc", "followLaborDays", "seedTakeoffSf", "seedDefaultTakeoff",
    "applyTravelRates", "applyLaborRate", "applyFeesDefault", "seedLibraryLabor", "libraryLaborRow",
}


def test_every_function_the_later_phases_will_move_is_covered(vectors):
    assert REQUIRED_FUNCTIONS <= {v["fn"] for v in vectors.values()}
    for name in ("RATES", "GP_BANDS", "CONDITION_CELLS", "LIBRARY_LINE_CELLS", "HOURS_PER_DAY", "DYE_COATS"):
        assert "const/" + name in vectors
    assert "exports" in vectors


def test_phase_4_changed_exactly_this_the_model_keeps_keys_it_does_not_know(vectors):
    """The one vector Phase 4 moved, pinned so a change that drops these keys again shows as the diff
    it is. Until Phase 4 an unknown key or a `tabs` block on a saved model was dropped on load (this
    test used to say so, and the recipe still says so beside the input); now it comes back as saved.
    Every other key of the answer is what it was, and the input is the same."""
    v = vectors["model/migrate/unknownKeys"]
    assert v["args"][0]["tabs"] and v["args"][0]["custom_key"] == 1
    assert v["out"]["tabs"] == v["args"][0]["tabs"] and v["out"]["custom_key"] == 1
    assert sorted(set(v["out"]) - {"tabs", "custom_key"}) == [
        "conditions", "contingency", "fees", "labor", "takeoff", "totals", "travel", "version"]


# ── red without the code: break a COPY of the module and watch the comparison fail ────────────────
MUTATIONS = {
    "a GP band moves": (
        "var GP_BANDS = [[6500, 0.52], [15000, 0.45], [22500, 0.35], [32500, 0.32], [null, 0.30]];",
        "var GP_BANDS = [[6500, 0.53], [15000, 0.45], [22500, 0.35], [32500, 0.32], [null, 0.30]];",
        ["const/GP_BANDS", "golden 0.52, now 0.53"]),
    "negative zero becomes zero": (
        "return num(row.guys) * num(row.days) * num(row.rate) * perDay;",
        "return 0 + num(row.guys) * num(row.days) * num(row.rate) * perDay;",
        ["labor/negzero/0", "golden -0, now 0"]),
    "NaN becomes null (a JSON-only comparison cannot see this)": (
        "? laborRateOrShipped(dflt) : Number(r.rate);",
        "? laborRateOrShipped(dflt) : (isNaN(Number(r.rate)) ? null : Number(r.rate));",
        ["newbid/libraryLaborRow/", "golden NaN, now null"]),
    "the ROUNDUP float guard loosens": (
        "var g = parseFloat(v.toPrecision(12));",
        "var g = parseFloat(v.toPrecision(15));",
        ["round/", "chain/float/material/0"]),
    "a Missouri zero is read as no county": (
        'remodel_pct = (given === null || given === undefined || given === "")',
        'remodel_pct = (given === null || given === undefined || given === "" || given === 0)',
        ["chain/remodel/3/0/on", "golden 0, now 0.065"]),
    "an export the module has today goes missing": (
        "rowOn: rowOn, sliderHtml: sliderHtml, manDaysHint: manDaysHint,",
        "rowOn: rowOn, sliderHtml: sliderHtml,",
        ["exports", ".out.manDaysHint", "golden 'function', now 'missing'"]),

    # setMeasurement writes into its rows and returns nothing, so these are changes only the rows it
    # LEAVES can show (`after` in the vector). Each is a real way to break the rule its comment states.
    "typing writes another number into the row": (
        "r.measurement = value;",
        "r.measurement = 0;",
        ["seed/setMeasurement/0", ".after[0][0].measurement: golden 12000, now 0"]),
    "an OFF carrier drags the same-floor rows along": (
        'if (r.unit !== "SF" || !rowOn(r)) return;',
        'if (r.unit !== "SF" && !rowOn(r)) return;',
        ["seed/setMeasurement/offCarrier", ".after[0][1].measurement: golden 100, now 200"]),
    "typing into an LF row drags the floor": (
        'if (r.unit !== "SF" || !rowOn(r)) return;',
        "if (!rowOn(r)) return;",
        ["seed/setMeasurement/lfCarrierSameNumber", ".after[0][1].measurement: golden 10000, now 12000"]),
    "a same-floor row above the carrier is never dragged": (
        "for (var k = 0; k < rows.length; k++) {",
        "for (var k = 1; k < rows.length; k++) {",
        ["seed/setMeasurement/sameFloorAbove", ".after[0][0].measurement: golden 12000, now 10000"]),
    "a plain row holding the same number is dragged along": (
        "o && o.same_floor && num(o.measurement) === num(old)",
        "o && (o.same_floor || num(o.measurement) === num(old))",
        ["seed/setMeasurement/plainRowsSameNumber", ".after[0][1].measurement: golden 10000, now 12000"]),
    "a same-floor row holding another number is dragged anyway": (
        "o.same_floor && num(o.measurement) === num(old)",
        "o.same_floor",
        ["seed/setMeasurement/sameFloorHoldsOther", ".after[0][2].measurement: golden 7500, now 12000"]),
    "rows are compared as text, not as numbers": (
        "num(o.measurement) === num(old)",
        "o.measurement === old",
        ["seed/setMeasurement/typedAsText", ".after[0][1].measurement: golden '12,000', now 9000"]),
    "a hole in the list becomes a crash": (
        "o && o.same_floor",
        "o.same_floor",
        ["seed/setMeasurement/nullRowInList"]),
}


# A helper the model borrows is broken where it now lives. The generator reaches it through the model,
# so the model comes along unmodified (`also=` in the test below).
MUTATION_MODULE = {
    "the ROUNDUP float guard loosens": "js/excel-math.js",
}


def test_a_new_export_does_not_turn_the_golden_red(node, tmp_path):
    """An unrelated change that adds a helper to the module is not a pricing change, so it must not
    cost its author a regenerated fixture. (A name that goes MISSING or changes type does: see above.)"""
    frontend = break_source(tmp_path, MODULE,
                            "rowOn: rowOn, sliderHtml: sliderHtml, manDaysHint: manDaysHint,",
                            "rowOn: rowOn, sliderHtml: sliderHtml, manDaysHint: manDaysHint, aBrandNewHelper: rowOn,")
    proc = compare(GENERATOR, GOLDEN, frontend)
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_the_golden_goes_red_when_the_code_changes(node, tmp_path, name):
    """The proof the golden is not decoration: each change below is the kind a refactor makes by
    accident, applied to a scratch copy, and each must fail the comparison BY NAME. The anchor line
    must exist exactly once (break_source refuses otherwise), so none of these can pass by applying
    nowhere."""
    old, new, expected = MUTATIONS[name]
    frontend = break_source(tmp_path, MUTATION_MODULE.get(name, MODULE), old, new, also=[MODULE])
    proc = compare(GENERATOR, GOLDEN, frontend, "--limit", "100000")        # list every vector that moved
    assert proc.returncode == 1, "the golden did not notice: " + name + "\n" + proc.stdout
    assert "GOLDEN MASTER MISMATCH" in proc.stdout
    for fragment in expected:
        assert fragment in proc.stdout, (fragment, proc.stdout[:1500])
