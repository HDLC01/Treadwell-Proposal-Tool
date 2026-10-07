"""Today's v2 Polish model, checked against Kyle's Polish tab: the first thing the workbook oracle is used for.

backend/tests/js/oracle-polish-harness.js runs the model (markupChain, and travelCosts for lodging) on every
Polish case the oracle recorded and compares each answer the two share. They have to be equal. Where they are
not, it has to be one of the DECLARED departures in backend/tests/fixtures/oracle/departures.json, each with
its reason:

  - the model has no tooling line (the sheet's D55 is at least $150)
  - the model's remodel tax base leaves out travel and tooling (the sheet's D75 includes both)
  - the model counts lodging nights as people-days (the sheet works them out from dollars)
  - the model has no hard-bid give-back, and no bond

THE DEPARTURES ARE PREDICTED, NOT JUST EXCUSED. For the first two the harness rebuilds the sheet's answer from
the model plus exactly what the reason says (tooling added in with travel, travel and tooling added into the
remodel base) and requires it to equal the oracle to the dollar, which proves each reason is the whole reason.
Every departure must also be SEEN on at least one case, or it is a comment and not a departure.

THE RATCHET. Phase 17 closes these gaps for new bids. The moment a model change closes one, this test goes red
until the departure is taken out of departures.json, so the list can only shrink on purpose and in view.
"""
import json

import pytest

import _oracle_support as S
from _golden_support import break_source
from _node import last_json_line, require_node, run_node

HARNESS = S.TESTS / "js" / "oracle-polish-harness.js"
MODEL = "js/bid-model.js"


def run(frontend=None):
    require_node()
    proc = run_node(HARNESS, *([frontend] if frontend else []))
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-4000:]
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def summary():
    return run()


@pytest.fixture(scope="module")
def departures():
    return json.loads((S.ORACLE / "departures.json").read_text(encoding="utf-8"))


def test_the_model_equals_the_oracle_except_where_a_departure_says_so(summary):
    assert summary["chain"]["unexplained"] == [] and summary["lodging"]["unexplained"] == []
    assert summary["chain"]["vectors"] >= 170 and summary["lodging"]["vectors"] == 8


def test_the_comparison_is_mostly_agreement_and_not_mostly_excuses(summary):
    chain = summary["chain"]
    assert chain["exact"] >= 120 and chain["excused"] <= 50, chain
    assert chain["exact"] + chain["excused"] == chain["vectors"]


def test_every_departure_is_seen_on_at_least_one_case(summary, departures):
    assert set(summary["departures"]) == {d["id"] for d in departures["departures"]}
    for d in departures["departures"]:
        seen = summary["departures"][d["id"]]
        assert seen["seen"] >= 1, d["id"] + ": no case shows the model differing here, so it is not a departure"
        assert seen["applies"] >= seen["seen"]


def test_departures_json_is_well_formed(departures):
    ids = [d["id"] for d in departures["departures"]]
    assert ids == ["tooling-is-zero", "remodel-base-widened", "hard-bid-removed", "bond-is-not-an-input", "lodging-by-man-days"]
    for d in departures["departures"]:
        assert len(d["reason"]) > 80 and d["scope"] in ("chain", "lodging"), d["id"]
        assert d["cells"] and d["keys"] and d["appliesWhen"], d["id"]
        assert d["explain"] in (None, "tooling-folds-into-travel", "remodel-base-widened"), d["id"]
        valid = set(departures["outputKeys"]) if d["scope"] == "chain" else set(departures["lodgingKeys"])
        assert set(d["keys"]) <= valid, d["id"]


def test_each_departure_names_cells_that_really_say_it(departures):
    """The reasons are claims about the Polish tab. Read them back out of the template."""
    from test_workbook_formula_pins import _index
    for d in departures["departures"]:
        for ev in d["evidence"]:
            kind, text = _index(departures["tab"]).get(ev["cell"], ("empty", None))
            assert kind == "formula", (d["id"], ev)
            for piece in ev["contains"]:
                assert piece in text, (d["id"], ev["cell"], "no longer holds", piece, text)


# ── the comparison can fail: break the model and watch it ────────────────────
def test_a_wrong_burden_turns_it_red(tmp_path):
    frontend = break_source(tmp_path, MODEL, "var burden = roundUp((labor + escalation) * RATES.BURDEN);",
                            "var burden = roundUp((labor) * RATES.BURDEN);")
    summary = run(frontend)
    keys = {d["key"] for u in summary["chain"]["unexplained"] for d in u["diffs"]}
    assert summary["chain"]["unexplained"] and "burden" in keys, "burden must differ wherever prevailing wage adds an escalation"


def test_a_moved_gp_edge_turns_it_red(tmp_path):
    frontend = break_source(tmp_path, MODEL, "var GP_BANDS = [[6500, 0.52],", "var GP_BANDS = [[6501, 0.52],")
    summary = run(frontend)
    ids = {u["id"] for u in summary["chain"]["unexplained"]}
    assert any(i.startswith("edge/gpPct/6500/0") for i in ids), ids


def test_closing_the_remodel_base_departure_in_the_model_turns_it_red_until_the_list_says_so(tmp_path):
    """Put travel into the model's remodel base, as Kyle's sheet has it. That closes the departure, and the
    harness, which describes the model as leaving travel out, says the model is no longer that: red. The departure
    has to come out of departures.json in the same change."""
    frontend = break_source(
        tmp_path, MODEL,
        "(labor + escalation + burden + gp + super_pto + soft_costs + contingency + fees)",
        "(labor + escalation + burden + travel + gp + super_pto + soft_costs + contingency + fees)")
    summary = run(frontend)
    keys = {d["key"] for u in summary["chain"]["unexplained"] for d in u["diffs"]}
    assert "(remodel-base-widened)" in keys, "a closed departure must be noticed, and named"


def test_closing_the_tooling_departure_in_the_model_turns_it_red_until_the_list_says_so(tmp_path):
    """Give the model a tooling line in its sub-total, as Kyle's sheet has it. The harness predicts the sheet by
    folding tooling into travel, so a model that now reads tooling counts it twice: red."""
    frontend = break_source(
        tmp_path, MODEL,
        "var sub_total = roundUp(material_total + labor + escalation + burden + travel);",
        "var sub_total = roundUp(material_total + labor + escalation + burden + travel + num(input.tooling));")
    summary = run(frontend)
    keys = {d["key"] for u in summary["chain"]["unexplained"] for d in u["diffs"]}
    assert "subTotal" in keys, "a closed departure must be noticed"


def test_a_wrong_lodging_count_turns_the_lodging_half_red(tmp_path):
    frontend = break_source(tmp_path, MODEL, "t += num(r.guys) * num(r.days);", "t += num(r.guys) * num(r.days) * 2;")
    summary = run(frontend)
    assert summary["lodging"]["unexplained"], "lodging nights are compared too"
