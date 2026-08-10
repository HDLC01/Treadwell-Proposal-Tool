"""Scheduling is gone from the CRM, and no card may fall off the board because of it.

Hanz, 2026-08-11: "We need to remove the schedule status on the CRM and on the Customer portal
Status." Asked how far it should go, he chose to take the notification with it: the board column,
the drawer tab, the Mark scheduled button, the customer's SCHEDULE tile and the "Your project is
scheduled" email all went together. Treadwell books the date on the phone, so every one of those
was restating a conversation the customer had already had.

THE FAILURE MODE THIS FILE EXISTS FOR.

`group()` in crm-core.js buckets cards by `stage(p)` and keeps only the ones whose stage is a live
column:

    items.forEach(function (p) { var s = stage(p); if (by[s]) by[s].push(p); });

So removing "Scheduled" from STAGES while leaving the `schedule_status === "scheduled"` branch in
stage() would not have moved those projects, it would have DELETED them from the board. No error,
no empty column, just a job that silently stops appearing anywhere. The two edits are a pair, and
this file is what keeps them paired.

The database is untouched: schedule_status, scheduled_at and db.set_schedule_status all still
exist, so reinstating any of this is a code change rather than a migration.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
CORE = FRONTEND / "js" / "crm-core.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _code(path: pathlib.Path) -> str:
    """Source with comment lines stripped, BOTH // and #.

    These files record removals by quoting what was removed, so a raw grep matches its own prose.
    The first version of this helper stripped only `//` and was then pointed at main.py, where the
    comment explaining the removal is a `#` line: the test failed on its own explanation. Third
    time this class of mistake has bitten in a day, hence both markers.
    """
    return "\n".join(l for l in path.read_text(encoding="utf-8").splitlines()
                     if not (l.strip().startswith("//") or l.strip().startswith("#")))


def _node(expr: str):
    src = ("const C = require(%s);\nconsole.log(JSON.stringify(%s));\n"
           % (json.dumps(str(CORE)), expr))
    out = subprocess.run(["node", "-e", src], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# ── the behaviour, exercised rather than grepped ──────────────────────────────
def test_a_scheduled_job_still_lands_on_the_board():
    """The one that matters. A project whose schedule_status is "scheduled" must appear in a real
    column, not be dropped by group()."""
    p = {"proposal_status": "approved", "deposit_status": "received",
         "contacts_status": "received", "schedule_status": "scheduled"}
    kept = _node("Object.values(C.group([%s], C.STAGES)).reduce((n,a)=>n+a.length,0)"
                 % json.dumps(p))
    assert kept == 1, "a scheduled project is dropped off the board entirely"


def test_a_scheduled_job_reads_as_the_furthest_stage_that_still_exists():
    p = {"proposal_status": "approved", "deposit_status": "received",
         "contacts_status": "received", "schedule_status": "scheduled"}
    assert _node("C.stage(%s)" % json.dumps(p)) == "Contact info"


def test_scheduled_is_not_a_column():
    assert "Scheduled" not in _node("C.STAGES")


def test_the_columns_that_remain_are_the_expected_six():
    """Named explicitly so a stray edit to the list is a test failure rather than a surprise on
    the board."""
    assert _node("C.STAGES") == ["Sent", "Viewed", "Approved", "Deposit submitted",
                                 "Deposit received", "Contact info"]


def test_closed_lost_still_works():
    """isLost is checked before everything else and is unrelated to this removal; it also went
    through its own change the same week, so it is worth re-asserting here."""
    assert _node('C.stage({"proposal_status":"closed_lost"})') == "Closed lost"


def test_the_stage_date_key_has_no_scheduled_entry():
    """A column that does not exist cannot date a card. A leftover entry here would be read by
    stageTs for a stage nothing returns."""
    assert "Scheduled" not in _node("C.STAGE_DATE_KEY")


def test_no_milestone_names_scheduled():
    """MILESTONES drives the "newest thing that happened" line on every card. Leaving
    scheduled_at in it would print "Scheduled" under a project the board no longer tracks that
    way."""
    labels = [m[1] for m in _node("C.MILESTONES")]
    assert "Scheduled" not in labels
    keys = [m[0] for m in _node("C.MILESTONES")]
    assert "scheduled_at" not in keys


# ── the drawer, and the endpoint behind it ───────────────────────────────────
def test_the_drawer_has_no_schedule_tab():
    code = _code(FRONTEND / "js" / "portal.js")
    assert "dsec-schedule" not in code, "the Schedule card is still registered in the drawer"
    assert "dpanel-schedule" not in code
    assert re.search(r'^\s*schedule:\s*\[', code, re.M) is None, (
        "SEC_TABS still has a schedule entry, which renders a tab with no cards")


def test_the_mark_scheduled_button_is_gone():
    """It was the only way to set the status, and it emailed the customer. Hanz chose to remove
    the notification with the status."""
    code = _code(FRONTEND / "js" / "portal.js")
    assert "mark-scheduled" not in code
    assert "scheduledDone" not in code


def test_the_default_drawer_tab_never_routes_to_a_tab_that_is_gone():
    """defaultSection used to send a contacts-complete project to "schedule". That tab no longer
    exists, so it would have opened the drawer on nothing."""
    code = _code(FRONTEND / "js" / "portal.js")
    i = code.index("function defaultSection")
    j = code.find("\n  function ", i + 1)
    body = code[i:j if j != -1 else len(code)]
    assert '"schedule"' not in body


def test_the_tool_no_longer_proxies_the_scheduled_endpoint():
    """The portal's route went too, so a surviving proxy would forward to a 404.

    Asserts on the ROUTE rather than the bare string: the string also appears in the comment that
    records the removal, and in "scheduled" inside other prose.
    """
    main = _code(ROOT / "backend" / "main.py")
    assert not re.search(r'@app\.\w+\(\s*"[^"]*/scheduled"', main), (
        "the tool still exposes a /scheduled route")
    assert "api_portal_scheduled" not in main, "the handler is still defined"
