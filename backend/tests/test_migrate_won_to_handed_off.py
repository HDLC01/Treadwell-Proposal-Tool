"""The one-off that moves every project on the old Won tab onto Handed Off.

Hanz, 2026-08-29, choosing between the options: all current Won-tab rows migrate.

WHY A SCRIPT AND NOT A SQL UPDATE. Most rows on that tab were never marked by hand. The Won tab
showed `!isLost && !isTest && isWon`, and `isWon` is mostly DERIVED — approved in the portal with
the deposit question settled — so those projects have no draft-side field to copy from. The
selection has to be recomputed, in Python, against the same merged board rows the page reads.

WHICH MAKES THE ONLY REAL RISK A MIRRORING BUG. If the Python drifts from crm-core.js by one clause,
the migration silently skips a project the estimator watched on the Won tab yesterday, and on deploy
day that project reappears on the Active board in the middle of the sales meeting — the precise
failure this script exists to prevent. So the tests that matter here are DIFFERENTIAL: the same
fixtures go through the real crm-core.js under node and through the script's own predicates, and the
two have to agree. Restating the Python in an assertion would only prove I can copy a line twice.

The fixtures are built from the wrong answers rather than the right ones: a lost-but-approved bid, a
job needing no deposit that was invoiced anyway, a project called "Demolition" (which contains
"demo"), and a real project explicitly flagged `is_test: true`.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

import migrate_won_to_handed_off as M

CORE = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "js" / "crm-core.js")


def _row(**kw):
    r = {"proposal_id": "p", "project_name": "Nearman Creek", "proposal_status": "sent",
         "deposit_status": "pending", "deposit_required": True}
    r.update(kw)
    return r


# Every row below is named for the judgement it forces, and each is a case where a lazier predicate
# gets it wrong. Shared by the differential test and the selection tests so the two cannot drift.
CASES = {
    "plainly_live": _row(),
    "won_by_hand": _row(won_at="2026-08-20T12:00:00+00:00"),
    "won_by_hand_and_unsent": _row(proposal_status="not_sent",
                                   won_at="2026-08-20T12:00:00+00:00"),
    "approved_deposit_received": _row(proposal_status="approved", deposit_status="received"),
    "approved_deposit_outstanding": _row(proposal_status="approved"),
    "approved_no_deposit_needed": _row(proposal_status="approved", deposit_required=False),
    # Needs no deposit, but an invoice went out anyway — money is outstanding whatever the flag says.
    "approved_no_deposit_but_invoiced": _row(proposal_status="approved", deposit_required=False,
                                             deposit_requested_at="2026-08-01T00:00:00+00:00"),
    # closed_lost REPLACES approved in the portal's one terminal column; approved_at survives it.
    "lost_after_being_approved": _row(proposal_status="closed_lost",
                                      approved_at="2026-08-10T00:00:00+00:00",
                                      deposit_status="received"),
    "lost_after_being_won_by_hand": _row(proposal_status="closed_lost",
                                         won_at="2026-08-20T12:00:00+00:00"),
    "named_like_a_test": _row(project_name="QA test — ignore",
                              won_at="2026-08-20T12:00:00+00:00"),
    # "demo" lives inside "demolition", which is a live word in a construction tool.
    "demolition_is_not_a_demo": _row(project_name="Demolition — Bay 4",
                                     won_at="2026-08-20T12:00:00+00:00"),
    "flagged_a_test": _row(project_name="Oak Grove", is_test=True,
                           won_at="2026-08-20T12:00:00+00:00"),
    # The flag wins in BOTH directions: a real project that happens to be called "Test Kitchen".
    "flagged_real_despite_the_name": _row(project_name="Test Kitchen remodel", is_test=False,
                                          won_at="2026-08-20T12:00:00+00:00"),
    "already_handed_off": _row(won_at="2026-08-20T12:00:00+00:00",
                               handed_off_at="2026-08-28T12:00:00+00:00"),
}


# ── the differential: the script's predicates against the board's own ────────
@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_script_picks_exactly_what_the_won_tab_was_showing():
    """THE test in this file. `boardPool()` filtered `!isLost && !isTest && isWon` for the Won tab;
    `_pick` is that expression in Python. Both run here over the same fixtures.

    A mismatch in either direction is a real bug with a different cost. Python saying no where JS
    said yes strands a project on Active. Python saying yes where JS said no hands off a job nobody
    has won."""
    script = (
        "const C = require(%s);\n"
        "const rows = %s;\n"
        "console.log(JSON.stringify(rows.map("
        "  (p) => !C.isLost(p) && !C.isTest(p) && C.isWon(p))));\n"
        % (json.dumps(str(CORE)), json.dumps([CASES[k] for k in sorted(CASES)]))
    )
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                          encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    from_js = json.loads(proc.stdout.strip().splitlines()[-1])

    keys = sorted(CASES)
    from_py = [(not M._is_lost(CASES[k]) and not M._is_test(CASES[k]) and M._is_won(CASES[k]))
               for k in keys]
    disagree = [k for k, a, b in zip(keys, from_js, from_py) if a != b]
    assert not disagree, (
        "the migration's Python has drifted from crm-core.js on %s — a project the Won tab showed "
        "would be left behind and reappear on the Active board" % disagree)
    assert any(from_js), "every fixture was rejected, so the test proves nothing about agreement"
    assert not all(from_js), "every fixture was accepted, so the test proves nothing either"


# ── the selection, stated in the product's terms ─────────────────────────────
def test_a_job_won_by_hand_is_taken():
    assert M._pick([CASES["won_by_hand"]]) == [CASES["won_by_hand"]]


def test_a_job_won_before_it_was_ever_sent_is_taken():
    """Unsent rows are synthesised by `_not_sent_rows` and carry `won_at` like any other. They were
    on the Won tab, so they migrate."""
    assert M._pick([CASES["won_by_hand_and_unsent"]])


def test_approved_with_the_deposit_in_is_taken_though_nobody_pressed_a_button():
    """The derived half, and the reason this cannot be a SQL UPDATE over a draft field: there is no
    draft field on these rows to update."""
    assert M._pick([CASES["approved_deposit_received"]])


def test_approved_with_money_still_outstanding_is_left_alone():
    assert M._pick([CASES["approved_deposit_outstanding"]]) == []


def test_a_job_needing_no_deposit_is_settled_unless_one_was_actually_invoiced():
    assert M._pick([CASES["approved_no_deposit_needed"]])
    assert M._pick([CASES["approved_no_deposit_but_invoiced"]]) == []


def test_lost_beats_won_in_both_of_its_forms():
    """Lost is asked first by every reader, so a lost bid was never on the Won tab no matter how it
    got its win. Handing one off would file a dead job with operations."""
    assert M._pick([CASES["lost_after_being_approved"]]) == []
    assert M._pick([CASES["lost_after_being_won_by_hand"]]) == []


def test_test_projects_do_not_migrate_but_a_demolition_job_does():
    """The Test tab is its own pool. "demo" inside "demolition" is the trap — a real job would be
    quietly dropped from operations by a looser regex."""
    assert M._pick([CASES["named_like_a_test"]]) == []
    assert M._pick([CASES["flagged_a_test"]]) == []
    assert M._pick([CASES["demolition_is_not_a_demo"]])
    assert M._pick([CASES["flagged_real_despite_the_name"]]), (
        "an explicit is_test=False lost to the project's name")


def test_the_whole_board_at_once_takes_exactly_the_rows_that_belong():
    """Run over every fixture together, because a predicate that is right one row at a time can
    still be wired into `_pick` with the wrong `and`. Named rather than counted — a count passes
    just as happily when the script takes the wrong seven."""
    order = sorted(CASES)
    picked = M._pick([CASES[k] for k in order])
    got = {k for k in order if any(r is CASES[k] for r in picked)}
    assert got == {
        "won_by_hand",
        "won_by_hand_and_unsent",
        "approved_deposit_received",
        "approved_no_deposit_needed",
        "demolition_is_not_a_demo",
        "flagged_real_despite_the_name",
        "already_handed_off",
    }


# ── idempotence, which is what makes a re-run safe ───────────────────────────
def test_a_project_already_handed_off_is_still_picked_but_has_nothing_left_to_do():
    """`_pick` is the Won-tab filter, not the to-do list — `main()` splits the picked rows into
    `already` and `todo` on the stamp. Keeping the split there is what lets a second run report
    "0 to stamp" instead of re-stamping and overwriting the original hand-off date."""
    row = CASES["already_handed_off"]
    assert M._pick([row]) == [row]
    assert row.get("handed_off_at"), "the fixture stopped being the already-handed-off case"


def test_the_stamp_backdates_to_when_the_job_was_actually_won():
    """`won_at || approved_at || now`. Stamping today on every row would make the Handed Off tab
    read as though the whole backlog was handed over on deploy day, and sort it that way."""
    src = (pathlib.Path(M.__file__)).read_text(encoding="utf-8")
    assert src.count('p.get("won_at") or p.get("approved_at") or drafts._now_iso()') == 2, (
        "the dry-run preview and the write must compute the same date, or the list the estimator "
        "approved is not the list that gets written")


def test_the_script_does_not_write_unless_it_is_told_to(monkeypatch, capsys):
    """Dry run is the default. This one runs `main()` end to end with the board stubbed, so a
    default that silently flipped to writing fails here rather than on prod."""
    monkeypatch.setattr(M, "api_portal_pipeline",
                        lambda: {"proposals": [CASES["won_by_hand"], CASES["plainly_live"]]})

    def _no(*a, **k):
        raise AssertionError("the dry run reached the database")

    monkeypatch.setattr(M.drafts, "get_client", _no)
    assert M.main([]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "Nearman Creek" in out, "the preview printed no project names to check"
