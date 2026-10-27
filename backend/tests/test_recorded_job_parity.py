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


# ── the same job saved as a hard bid. The Hard bid switch (2026-10-17, #685) was REMOVED on 2026-10-27 (Hanz: "I told you
#    to remove this hard bid discount"): the rule prices nothing now, and a bid saved with it on opens with the discount it
#    gave typed in its Discount box (B.settleHardBid), so its price does not move. ───────────────────────────────────────
def _rule(r, pct):
    """Kyle's D74 / D68: =ROUNDUP(SUM(sub_total, gp) * -pct, 0), rounded away from zero."""
    import math
    return -math.ceil(round((r["sub_total"] + r["gp"]) * pct, 6))


# WHAT EACH SAVED BID PRICED AT WHILE THE SWITCH PRICED ITS RULE: (discount line, total), recorded from the harness on
# origin/staging 58cf4a5c, the last code that had the switch. Settling must land every one of them exactly.
PRICED_WITH_THE_SWITCH = {
    "epoxy": (-1045, 51426),          # local, sub-total 28,064: Kyle's 2.5%
    "epoxyTyped": (-1254, 51165),     # his typed 3% won over the rule
    "epoxyDollars": (-500, 52108),    # typed dollars won over the rule
    "epoxyNotLocal": (0, 52733),      # not local and under $60,000: the rule gave nothing
    "epoxyBadTyped": (-1045, 51426),  # a % box that is not a number was left out, and the rule priced
    "epoxyBig": (-5242, 158913),      # sub-total over $60,000: 4%
    "polish": (-639, 32046),          # polish-rev3, local: 2.5%
    "polishRev2": (0, 31331),         # rev2 has no rule
}


@pytest.mark.parametrize("name", sorted(PRICED_WITH_THE_SWITCH))
def test_a_saved_hard_bid_keeps_its_price_once_settled(ran, name):
    r = ran["hardBid"]["settled"][name]
    assert (r["hard_bid"], r["total"]) == PRICED_WITH_THE_SWITCH[name]
    assert r["input_kept"], "settling changed the model it was handed"
    assert "hard_bid" not in (r["adjust"] or {}), "the switch survived the open"


def test_the_rules_percentage_becomes_a_typed_discount(ran):
    s = ran["hardBid"]["settled"]
    assert (s["epoxy"]["sub_total"], s["epoxy"]["gp"]) == (28064, 13736), "the job is not the recorded one"
    assert s["epoxy"]["hard_bid"] == _rule(s["epoxy"], 0.025)
    assert s["epoxy"]["adjust"] == {"discount_pct": "2.5", "ship_pct": "6", "supplier_pct": "20"}
    assert s["epoxyBig"]["sub_total"] >= 60000 and s["epoxyBig"]["adjust"] == {"discount_pct": "4"}
    assert s["epoxyBig"]["hard_bid"] == _rule(s["epoxyBig"], 0.04)
    assert s["polish"]["adjust"] == {"discount_pct": "2.5"}
    assert s["epoxyBadTyped"]["adjust"]["discount_pct"] == "2.5", "the rule priced over the unusable box"


def test_a_typed_figure_wins_and_the_switch_is_just_dropped(ran):
    s = ran["hardBid"]["settled"]
    assert s["epoxyTyped"]["adjust"] == {"discount_pct": "3", "ship_pct": "6", "supplier_pct": "20"}
    assert s["epoxyTyped"]["total"] == RECORDED["epoxy"]["sheet"]["total"], "Kyle's typed 3% is still his bid"
    assert s["epoxyDollars"]["adjust"] == {"ship_pct": "6", "supplier_pct": "20", "discount_amt": "500"}
    # the rule gave nothing: no figure is invented, the key just goes (an adjust left empty goes with it)
    assert s["epoxyNotLocal"]["adjust"] == {"ship_pct": "6", "supplier_pct": "20"}
    assert s["polishRev2"]["adjust"] is None


@pytest.mark.parametrize("name", ["epoxyNever", "epoxyNeverBare", "polishNever"])
def test_a_bid_that_never_had_the_switch_is_handed_back_untouched(ran, name):
    assert ran["hardBid"]["settled"][name]["untouched"], "the same object, byte for byte"


def test_the_switch_no_longer_prices_anything(ran):
    raw = ran["hardBid"]["raw"]
    assert raw["epoxy"]["hard_bid"] == 0 and raw["epoxy"]["total"] == raw["epoxyOff"]["total"]
    assert raw["epoxyBig"]["hard_bid"] == 0
    assert raw["polish"]["hard_bid"] == 0 and raw["polish"]["total"] == raw["polishOff"]["total"]


def test_the_switch_is_read_only_to_be_settled(ran):
    k = ran["hardBid"]["kept"]
    assert k["on"] == {"hard_bid": True}, "a saved switch must survive migrateModel until the page settles it"
    assert k["ruleGone"] is None, "the Review step's grey figures are priced with no rule"
    assert k["noSwitchApi"] == "undefined", "hardBidRuleOn is gone with the switch"


MUTATIONS = {
    "settling does not write the rule's figure": (
        "js/bid-model.js", "        if (pct !== null) next.discount_pct = pctTyped(pct);",
        "        if (false) next.discount_pct = pctTyped(pct);", ("hardBid.settled.epoxy", "total", 51426)),
    "a saved switch still prices the rule": (
        "js/bid-model.js",
        "    return ctx && ctx.hardBidRule === true ? Object.assign({}, conditions || {}, { hard_bid: true }) : conditions;",
        "    return Object.assign({}, conditions || {}, { hard_bid: true });", ("hardBid.raw.epoxy", "hard_bid", 0)),
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
    rel, old, new, (tab, key, *want) = MUTATIONS[name]
    frontend = break_source(tmp_path, rel, old.strip(), new.strip())
    copy_unmodified(frontend, SCRATCH_FRONTEND_FILES)
    got = _run(frontend, tmp_path)
    if tab.startswith("hardBid."):
        _, group, case = tab.split(".")
        assert got["hardBid"][group][case][key] != want[0], "the match did not notice: " + name
        return
    assert got[tab][key] != pytest.approx(RECORDED[tab]["sheet"][key], abs=0.005), "the match did not notice: " + name
