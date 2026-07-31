"""The browser-side aggregation engine, exercised under node.

Every number on the dashboard comes from frontend/js/analytics-core.js, so the
formulas need a test even though they don't run in Python. The file is UMD-ish
on purpose (`module.exports` when node is present) so this can require() it.

Skipped when node isn't installed; it's on the dev box and in the Docker image.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

CORE = (pathlib.Path(__file__).resolve().parents[2]
        / "frontend" / "js" / "analytics-core.js")

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is not installed")


def run(script: str):
    """Run `script` with `agg` bound to the engine; returns its printed JSON."""
    prelude = (
        "const agg = require(%s);\n"
        "const out = (v) => console.log(JSON.stringify(v));\n" % json.dumps(str(CORE))
    )
    proc = subprocess.run(["node", "-e", prelude + script],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def row(**kw):
    base = {"id": "x", "name": "Job", "stage_id": "s1", "estimator_ids": [],
            "company_ids": [], "awarded_by_id": "", "trades": [],
            "awarded_at": None, "submitted_at": None, "lost_at": None,
            "created_at": None, "bid_deadline_at": None,
            "quote": 0, "won_amount": 0, "pending_amount": 0,
            "submitted_amount": 0, "lost_amount": 0, "archived": False}
    base.update(kw)
    return base


def js_rows(rows):
    return "const rows = agg.decorate(%s);\n" % json.dumps(rows)


def test_a_late_evening_bid_counts_on_the_central_day_not_the_utc_one():
    """7pm Central is already tomorrow in UTC. Comparing raw ISO strings files
    the bid under the wrong day — and at a month boundary, the wrong bar."""
    got = run("out([agg.bizDay('2026-01-31T02:00:00.000Z'),"
              "     agg.bizDay('2026-02-01T02:00:00.000Z'),"
              "     agg.bizDay(null)]);")
    assert got == ["2026-01-30", "2026-01-31", ""]


def test_window_bounds_are_inclusive():
    got = run(
        "const w = {from:'2026-01-01', to:'2026-01-31'};"
        "out([agg.inWin('2026-01-01',w), agg.inWin('2026-01-31',w),"
        "     agg.inWin('2025-12-31',w), agg.inWin('2026-02-01',w),"
        "     agg.inWin('',w), agg.inWin('2026-05-05',{from:null,to:null})]);"
    )
    assert got == [True, True, False, False, False, True]


def test_presets_resolve_on_the_central_calendar():
    got = run(
        "const now = new Date('2026-07-31T18:00:00Z');"
        "out({ytd: agg.presetRange('ytd', now), prev: agg.presetRange('prev_year', now),"
        "     mtd: agg.presetRange('mtd', now), last: agg.presetRange('last_month', now),"
        "     all: agg.presetRange('all', now),"
        "     janLast: agg.presetRange('last_month', new Date('2026-01-15T18:00:00Z'))});"
    )
    assert got["ytd"] == {"from": "2026-01-01", "to": "2026-07-31"}
    assert got["prev"] == {"from": "2025-01-01", "to": "2025-12-31"}
    assert got["mtd"] == {"from": "2026-07-01", "to": "2026-07-31"}
    assert got["last"] == {"from": "2026-06-01", "to": "2026-06-30"}
    assert got["all"] == {"from": None, "to": None}
    assert got["janLast"] == {"from": "2025-12-01", "to": "2025-12-31"}   # wraps the year


def test_leap_february_gets_29_days():
    got = run("out([agg.lastDayOf('2028-02'), agg.lastDayOf('2026-02'), agg.lastDayOf('2026-12')]);")
    assert got == ["2028-02-29", "2026-02-28", "2026-12-31"]


def test_the_overview_metrics_match_basisboards_own_definitions():
    rows = [
        # submitted AND awarded in window
        row(id="a", submitted_at="2026-03-31T14:00:00Z", awarded_at="2026-05-07T13:00:00Z",
            submitted_amount=1000.0, won_amount=1200.0),
        # submitted in window, never awarded
        row(id="b", submitted_at="2026-02-10T14:00:00Z", submitted_amount=500.0),
        # awarded in window, submitted BEFORE it — counts for won, not for submitted
        row(id="c", submitted_at="2025-11-01T14:00:00Z", awarded_at="2026-06-01T14:00:00Z",
            submitted_amount=300.0, won_amount=400.0),
        # entirely outside
        row(id="d", submitted_at="2025-01-01T14:00:00Z", submitted_amount=999.0),
    ]
    got = run(js_rows(rows) +
              "const m = agg.metrics(rows, {from:'2026-01-01', to:'2026-07-31'});"
              "out({won:m.wonAmount, nAw:m.nAwarded, sub:m.submittedAmount, nSub:m.nSubmitted,"
              "     winProjSub:m.winProjSub, winAmtSub:m.winAmtSub,"
              "     winProjAw:m.winProjAw, winAmtAw:m.winAmtAw});")
    assert got["won"] == 1600.0 and got["nAw"] == 2          # a + c
    assert got["sub"] == 1500.0 and got["nSub"] == 2         # a + b
    assert got["winProjSub"] == {"num": 1, "den": 2, "ratio": 0.5}
    assert got["winAmtSub"] == {"num": 1200.0, "den": 1500.0, "ratio": 0.8}
    assert got["winProjAw"] == {"num": 2, "den": 2, "ratio": 1.0}
    assert got["winAmtAw"] == {"num": 1600.0, "den": 1300.0, "ratio": pytest.approx(1.2307, rel=1e-3)}


def test_a_ratio_with_no_denominator_is_null_and_over_100_percent_is_left_alone():
    """No denominator means no answer, not zero. And a job really can be awarded
    for more than it was bid at — a real company sits at 166.8%."""
    got = run(js_rows([row(id="a", awarded_at="2026-05-01T14:00:00Z",
                           submitted_at="2026-05-01T14:00:00Z",
                           submitted_amount=100.0, won_amount=250.0)]) +
              "const m = agg.metrics(rows, {from:'2026-01-01', to:'2026-12-31'});"
              "const e = agg.metrics([], {from:'2026-01-01', to:'2026-12-31'});"
              "out({over:m.winAmtAw.ratio, none:e.winProjSub.ratio, noneAmt:e.winAmtSub.ratio});")
    assert got["over"] == 2.5
    assert got["none"] is None and got["noneAmt"] is None


def test_a_row_with_no_date_never_counts_even_for_all_time():
    got = run(js_rows([row(id="a", submitted_amount=500.0)]) +
              "const m = agg.metrics(rows, {from:null, to:null});"
              "out({sub:m.submittedAmount, nSub:m.nSubmitted});")
    assert got["sub"] == 0 and got["nSub"] == 0


def test_months_are_contiguous_so_a_quiet_month_reads_as_zero():
    rows = [row(id="a", submitted_at="2026-01-15T14:00:00Z", submitted_amount=100.0),
            row(id="b", submitted_at="2026-04-15T14:00:00Z", submitted_amount=300.0)]
    got = run(js_rows(rows) +
              "out(agg.byMonth(rows, {from:'2026-01-01', to:'2026-04-30'}, '_su', 'submitted_amount')"
              "  .map(b => [b.label, b.amount, b.count]));")
    assert got == [["Jan 2026", 100.0, 1], ["Feb 2026", 0, 0],
                   ["Mar 2026", 0, 0], ["Apr 2026", 300.0, 1]]


def test_filters_are_or_within_a_dimension_and_and_across_them():
    """The combination Basisboard can't express."""
    rows = [
        row(id="a", trades=["Epoxy"], estimator_ids=["greg"], stage_id="won"),
        row(id="b", trades=["Gyp"], estimator_ids=["troy"], stage_id="won"),
        row(id="c", trades=["Epoxy"], estimator_ids=["troy"], stage_id="lost"),
        row(id="d", trades=["Polish"], estimator_ids=["greg"], stage_id="won"),
    ]
    got = run(js_rows(rows) +
              "const ids = (f) => agg.applyFilters(rows, f).map(r => r.id);"
              "out({none: ids({}),"
              "     twoTrades: ids({trades:['Epoxy','Gyp']}),"
              "     crossed: ids({trades:['Epoxy','Gyp'], estimators:['troy']}),"
              "     plusStage: ids({trades:['Epoxy','Gyp'], estimators:['troy'], stages:['won']})});")
    assert got["none"] == ["a", "b", "c", "d"]
    assert got["twoTrades"] == ["a", "b", "c"]
    assert got["crossed"] == ["b", "c"]
    assert got["plusStage"] == ["b"]


def test_untagged_projects_are_filterable_as_their_own_bucket():
    rows = [row(id="a", trades=["Epoxy"]), row(id="b", trades=[])]
    got = run(js_rows(rows) +
              "out({untagged: agg.applyFilters(rows, {trades:[agg.NO_TRADE]}).map(r=>r.id),"
              "     both: agg.applyFilters(rows, {trades:[agg.NO_TRADE,'Epoxy']}).map(r=>r.id),"
              "     epoxy: agg.applyFilters(rows, {trades:['Epoxy']}).map(r=>r.id)});")
    assert got["untagged"] == ["b"]
    assert got["both"] == ["a", "b"]
    assert got["epoxy"] == ["a"]


def test_a_company_filter_also_matches_the_company_that_awarded_the_job():
    rows = [row(id="a", company_ids=["c1"], awarded_by_id="c2"),
            row(id="b", company_ids=["c3"])]
    got = run(js_rows(rows) +
              "out(agg.applyFilters(rows, {companies:['c2']}).map(r=>r.id));")
    assert got == ["a"]


def test_a_two_trade_project_counts_in_both_buckets():
    """Deliberate: it's how Basisboard reports, and the only answer that doesn't
    hide work. The consequence is that buckets sum past the overview total."""
    rows = [row(id="a", trades=["Epoxy", "Polish"], submitted_at="2026-02-01T14:00:00Z",
                submitted_amount=1000.0)]
    got = run(js_rows(rows) +
              "out(agg.byDimension(rows, {from:'2026-01-01',to:'2026-12-31'}, 'trade', {})"
              "  .map(g => [g.key, g.submittedAmount, g.nSubmitted]).sort());")
    assert got == [["Epoxy", 1000.0, 1], ["Polish", 1000.0, 1]]


def test_untagged_and_unassigned_rows_group_under_their_own_label():
    rows = [row(id="a", trades=[], submitted_at="2026-02-01T14:00:00Z", submitted_amount=10.0),
            row(id="b", estimator_ids=[], submitted_at="2026-02-01T14:00:00Z", submitted_amount=20.0)]
    got = run(js_rows(rows) +
              "const w={from:'2026-01-01',to:'2026-12-31'};"
              "out({t: agg.byDimension(rows,w,'trade',{}).map(g=>[g.key,g.label,g.nSubmitted]),"
              "     e: agg.byDimension(rows,w,'estimator',{}).map(g=>[g.key,g.label,g.nSubmitted])});")
    assert got["t"] == [["", "(No trade)", 2]]
    assert got["e"] == [["", "(No estimator)", 2]]


def test_won_side_company_credit_goes_to_the_company_that_awarded_it():
    """Spreading a win across every GC that invited the bid would multiply it."""
    rows = [
        row(id="a", company_ids=["c1", "c2"], awarded_by_id="c2",
            awarded_at="2026-05-01T14:00:00Z", won_amount=900.0),
        # awarded with no awardedById but only one bidder — credit that one
        row(id="b", company_ids=["c3"], awarded_at="2026-05-01T14:00:00Z", won_amount=100.0),
        # awarded, no awardedById, several bidders — unattributable
        row(id="c", company_ids=["c4", "c5"], awarded_at="2026-05-01T14:00:00Z", won_amount=50.0),
    ]
    got = run(js_rows(rows) +
              "out(agg.byDimension(rows, {from:'2026-01-01',to:'2026-12-31'}, 'company',"
              "     {name: k => k.toUpperCase()})"
              "  .map(g => [g.key, g.wonAmount, g.nAwarded]).sort());")
    assert got == [["", 50.0, 1],            # several bidders, no awardedById
                   ["c2", 900.0, 1],         # the awarding company, not both bidders
                   ["c3", 100.0, 1]]         # sole bidder, credited


def test_dimension_win_rate_measures_both_halves_over_the_submitted_set():
    rows = [
        row(id="a", trades=["Epoxy"], submitted_at="2026-02-01T14:00:00Z",
            awarded_at="2026-03-01T14:00:00Z", submitted_amount=1000.0, won_amount=1000.0),
        row(id="b", trades=["Epoxy"], submitted_at="2026-02-01T14:00:00Z",
            submitted_amount=3000.0),
    ]
    got = run(js_rows(rows) +
              "const g = agg.byDimension(rows, {from:'2026-01-01',to:'2026-12-31'}, 'trade', {})[0];"
              "out({amt:g.winAmt, proj:g.winProj});")
    assert got["amt"] == {"num": 1000.0, "den": 4000.0, "ratio": 0.25}
    assert got["proj"] == {"num": 1, "den": 2, "ratio": 0.5}


def test_stage_cards_use_the_bid_deadline_window_and_the_current_stage():
    rows = [
        row(id="a", stage_id="lost", bid_deadline_at="2026-03-01T14:00:00Z", submitted_amount=700.0),
        row(id="b", stage_id="won", bid_deadline_at="2026-04-01T14:00:00Z", submitted_amount=300.0),
        row(id="c", stage_id="won", bid_deadline_at="2025-01-01T14:00:00Z", submitted_amount=999.0),
        row(id="d", stage_id="won", submitted_amount=999.0),          # no deadline at all
    ]
    stages = [{"id": "won", "name": "Awarded", "color": "#0a0"},
              {"id": "lost", "name": "Lost", "color": "#a00"},
              {"id": "quiet", "name": "Undecided", "color": "#ccc"}]
    got = run(js_rows(rows) +
              "out(agg.byStage(rows, {from:'2026-01-01',to:'2026-12-31'}, %s)"
              "  .map(s => [s.label, s.amount, s.count, Math.round(s.pctAmount*1000)/1000]));"
              % json.dumps(stages))
    assert got == [["Lost", 700.0, 1, 0.7], ["Awarded", 300.0, 1, 0.3],
                   ["Undecided", 0, 0, 0]]          # empty stage still listed


def test_ranked_lists_put_the_biggest_first():
    """These cards are rankings — ascending order buries the headline."""
    got = run(
        "const g = [{label:'Polish', v:350}, {label:'Epoxy', v:1000}, {label:'Gyp', v:413},"
        "           {label:'Zilch', v:null}, {label:'Also', v:413}];"
        "out({desc: agg.sortBy(g,'v').map(x=>x.label),"
        "     asc: agg.sortBy(g,'v','asc').map(x=>x.label)});"
    )
    assert got["desc"] == ["Epoxy", "Also", "Gyp", "Polish", "Zilch"]   # ties break by label
    assert got["asc"] == ["Zilch", "Polish", "Also", "Gyp", "Epoxy"]


def test_a_row_in_a_stage_the_settings_dropped_still_shows_up():
    rows = [row(id="a", stage_id="ghost", bid_deadline_at="2026-03-01T14:00:00Z",
                submitted_amount=100.0)]
    got = run(js_rows(rows) +
              "out(agg.byStage(rows, {from:null,to:null}, [])"
              "  .map(s => [s.label, s.amount, s.count]));")
    assert got == [["Unstaged", 100.0, 1]]
