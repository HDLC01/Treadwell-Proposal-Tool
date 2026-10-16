"""A real job, priced through v2, equals what Kyle's workbook priced it at: every line, to the cent.

Hanz, 2026-10-16, handing over a finished Polish + Epoxy job (Kyle's 10.01 workbook and the two proposals he sent):
"compare the output of the v2 estimates ... we just need the price to be the same to the centavos".

The first comparison did not match: Epoxy $54,364 against $51,165, Polish $28,733 against $32,864. Every gap was an
input, never the markup chain:
  * the Polish tab had never been seeded into the library (a placeholder system priced one wrong product), and v2's
    Polish material had no patch line (Polish!D17);
  * Kyle typed three things over his own rules on the Epoxy tab that v2 had no box for: a 20% supplier discount on the
    Sherwin-Williams liquids (B41), shipping at 6% instead of the tier's 9% (B42), and a 3% discount line (B74) on a job
    that was not a hard bid.
Fixed by seeding the Polish tab (backend/ops/seed_library_from_workbook.py), the polish-rev3 profile (the patch line)
and the per-section overrides on the Review step (bid-model.js `adjust`; library-core itemsForBid for the discounts).

The job is tests/fixtures/recorded_job_2026_10.json, anonymised: the inputs as typed and the figures the sheet answered.
Nothing of the customer is in it. The harness prices it through the page's own engines on the library the seed plans.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node
from _seed_support import plan_json

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "recorded-job-parity-harness.js"
JOB = TESTS / "fixtures" / "recorded_job_2026_10.json"
# the modules the harness loads, copied unbroken beside the one a mutation breaks
SCRATCH_FRONTEND_FILES = ["js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js", "js/library-core.js",
                          "js/epoxy-takeoff.js", "js/seal-takeoff.js", "js/work-types.js", "js/markup-core.js",
                          "js/excel-math.js"]
RECORDED = json.loads(JOB.read_text(encoding="utf-8"))


def _run(frontend, tmp_path):
    require_node()
    plan = plan_json(tmp_path)
    proc = run_node(HARNESS, frontend, plan, JOB)
    assert proc.returncode == 0, proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran(tmp_path_factory):
    return _run(FRONTEND, tmp_path_factory.mktemp("recorded"))


@pytest.mark.parametrize("tab", ["epoxy", "polish"])
def test_every_line_is_the_workbooks(ran, tab):
    sheet, got = RECORDED[tab]["sheet"], ran[tab]
    for key, want in sheet.items():
        assert got[key] == pytest.approx(want, abs=0.005), (
            "%s %s (%s): the workbook says %r, v2 says %r" % (tab, key, RECORDED[tab]["cells"].get(key, "raw"), want, got[key]))


@pytest.mark.parametrize("tab", ["epoxy", "polish"])
def test_the_proposals_price_lines_are_the_bids(ran, tab):
    p, got = RECORDED[tab]["proposal"], ran[tab]
    assert got["total"] == p["total"]
    assert (got["sales_tax"], got["remodel_tax"]) == (p["sales_tax"], p["remodel_tax"])
    assert got["total"] - got["sales_tax"] - got["remodel_tax"] == p["base"]


def test_without_kyles_typed_overrides_the_epoxy_bid_is_not_the_workbooks(ran):
    """The overrides are doing the work, not a coincidence: the same job on the sheet's own rules is a different bid."""
    assert ran["epoxyNoOverrides"]["total"] != RECORDED["epoxy"]["sheet"]["total"]
    assert ran["epoxyNoOverrides"]["hard_bid"] == 0


def test_the_polish_patch_line_is_the_renovation_rate_over_the_whole_floor(ran):
    assert ran["polish"]["patch"] == pytest.approx(0.15 * RECORDED["polish"]["in"]["sf"], abs=0.005)


# ── the same job as a hard bid (Hanz, 2026-10-17: "lets make the hard bid have those rules but still overridable in the
#    review tab") ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _rule(r, pct):
    """Kyle's D74 / D68: =ROUNDUP(SUM(sub_total, gp) * -pct, 0), rounded away from zero."""
    import math
    return -math.ceil(round((r["sub_total"] + r["gp"]) * pct, 6))


def test_a_local_hard_bid_from_13000_takes_kyles_two_and_a_half_percent(ran):
    r = ran["hardBid"]["epoxy"]
    assert (r["sub_total"], r["gp"]) == (28064, 13736), "the job is not the recorded one"
    assert r["hard_bid"] == _rule(r, 0.025) == -1045


def test_a_typed_discount_wins_over_the_rule(ran):
    h = ran["hardBid"]
    assert h["epoxyTyped"]["hard_bid"] == -1254 and h["epoxyTyped"]["total"] == RECORDED["epoxy"]["sheet"]["total"], (
        "Kyle's typed 3% with Hard bid on is still his bid")
    assert h["epoxyDollars"]["hard_bid"] == -500


def test_under_60000_a_job_that_is_not_local_gets_nothing(ran):
    r = ran["hardBid"]["epoxyNotLocal"]
    assert r["sub_total"] < 60000 and r["hard_bid"] == 0


def test_from_60000_the_rule_is_four_percent(ran):
    r, off = ran["hardBid"]["epoxyBig"], ran["hardBid"]["epoxyBigOff"]
    assert r["sub_total"] >= 60000
    assert r["hard_bid"] == _rule(r, 0.04) != 0
    assert off["hard_bid"] == 0 and off["total"] > r["total"], "with the switch off the same job has no discount"


def test_a_new_polish_bid_has_the_rule_and_a_saved_rev2_one_does_not(ran):
    h = ran["hardBid"]
    assert h["polish"]["sub_total"] >= 13000 and h["polish"]["hard_bid"] == _rule(h["polish"], 0.025) != 0
    assert h["polishRev2"]["hard_bid"] == 0, "a bid saved on rev2 keeps its total whatever it says"


def test_the_switch_is_shown_only_where_kyles_sheet_has_the_rule(ran):
    assert ran["hardBid"]["ruleOn"] == {"rev3": True, "rev2": False, "epoxy": True, "gyp": False, "nothing": False}


def test_the_switch_is_kept_only_as_true_and_survives_the_boxes_being_set_aside(ran):
    k = ran["hardBid"]["kept"]
    assert k["on"] == {"hard_bid": True} and k["notTrue"] is None
    assert k["ruleKeepsIt"] == {"hard_bid": True}, "the Review step's grey Discount figure would not show the rule"


MUTATIONS = {
    "the hard bid switch does not reach the chain": (
        "js/bid-model.js", "    return a && a.hard_bid ? Object.assign({}, conditions || {}, { hard_bid: true }) : conditions;",
        "    return conditions;", ("hardBid.epoxy", "hard_bid")),
    "the supplier discount is not applied to the materials": (
        "js/library-core.js", "      if (offOf.has(vkey(it.vendor))) factor = (1 + esc - offOf.get(vkey(it.vendor))) / (1 + esc);",
        "      if (false) factor = 1;", ("epoxy", "material")),
    "the discount comes off the escalation too": (
        "js/library-core.js", "      if (offOf.has(vkey(it.vendor))) factor = (1 + esc - offOf.get(vkey(it.vendor))) / (1 + esc);",
        "      if (offOf.has(vkey(it.vendor))) factor = 1 - offOf.get(vkey(it.vendor));", ("epoxy", "material")),
    "a typed shipping rate is ignored": (
        "js/bid-engine.js", '        ship_pct = has1("ship_pct") ? adj.ship_pct : rate("ship_pct");',
        '        ship_pct = rate("ship_pct");', ("epoxy", "shipping")),
    "the discount line is left out of super and soft costs": (
        "js/bid-engine.js", "      var super_pto = roundUp((sub_total + gp + hard_bid + contingency + sales_tax + fees) * super_pct);",
        "      var super_pto = roundUp((sub_total + gp + contingency + sales_tax + fees) * super_pct);", ("epoxy", "super_pto")),
    "the patch line is not taken into the material": (
        "js/bid-engine.js", "        material = roundUp(num(input.material) + (q.polishPatch && profile.layout === \"polish\" ? num(input.patch) : 0));",
        "        material = roundUp(num(input.material));", ("polish", "material")),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_the_match_goes_red_when_the_code_changes(tmp_path, name):
    rel, old, new, (tab, key) = MUTATIONS[name]
    frontend = break_source(tmp_path, rel, old.strip(), new.strip())
    copy_unmodified(frontend, SCRATCH_FRONTEND_FILES)
    got = _run(frontend, tmp_path)
    if tab == "hardBid.epoxy":
        assert got["hardBid"]["epoxy"][key] != -1045, "the match did not notice: " + name
        return
    assert got[tab][key] != pytest.approx(RECORDED[tab]["sheet"][key], abs=0.005), "the match did not notice: " + name
