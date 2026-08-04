"""The Follow-ups board: which column a proposal sits in, and who may move it.

The board draws the SAME rows the list draws, so its column order has to agree with the
list's `stateOf()` precedence exactly — a proposal reading "Paused to 12 Oct" in the table
while sitting under Chasing on the board would make one of the two a liar.

The collisions are the whole reason this logic is extracted and tested. `proposal_status` is
what the CUSTOMER did (sent -> viewed -> approved / closed_lost); `followup_state` is what WE
decided (enrolled, paused until a date, automation off). A proposal can be "sent, not viewed"
AND "paused for three months" at the same time. Our decision wins, because that is the one
that answers "do I need to do anything today".

THREE COLUMNS ARE NOT DROP TARGETS, and that is a correctness rule rather than a UI
preference: Sent, Viewed and Approved record what the customer did. Dragging a card into
Viewed would assert that somebody opened a proposal they never opened — and `viewed_at` feeds
the digest's ranking and its 6 AM sentence, so the lie would propagate into an email.

Run under node, like test_crm_core_js.py and test_calendar_core_js.py: this is pure state
logic with no DOM in it, and it is the only way to pin column precedence without a browser.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
CORE = FRONTEND / "js" / "followups-core.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                               reason="node is not installed")

TODAY = "2026-08-04"


def run(script: str):
    """Run `script` with `C` bound to the module; returns its printed JSON."""
    prelude = (
        "const C = require(%s);\n"
        "const T = %s;\n"
        "const row = (o) => Object.assign({proposal_status:'sent', followup_state:{}}, o||{});\n"
        "const out = (v) => console.log(JSON.stringify(v));\n"
        % (json.dumps(str(CORE)), json.dumps(TODAY))
    )
    proc = subprocess.run(["node", "-e", prelude + script],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_module_loads():
    """A syntax error would make every test below fail with the same opaque message."""
    assert run("out(typeof C.column)") == "function"


def test_there_are_six_columns_and_three_are_ours():
    got = run("out([C.COLUMNS.map(c=>c.id), C.COLUMNS.filter(c=>c.ours).map(c=>c.id)])")
    assert got[0] == ["sent", "viewed", "chasing", "paused", "approved", "lost"]
    assert got[1] == ["chasing", "paused", "lost"], (
        "the customer-owned set changed — Sent/Viewed/Approved must stay non-droppable")


# ── column precedence, including the collisions ───────────────────────
@pytest.mark.parametrize("desc,row_js,expect", [
    ("sent, nothing else", "{}", "sent"),
    ("viewed", "{proposal_status:'viewed'}", "viewed"),
    ("enrolled + enabled", "{followup_state:{enrolled:1,enabled:1}}", "chasing"),
    ("approved", "{proposal_status:'approved'}", "approved"),
    ("closed_lost", "{proposal_status:'closed_lost'}", "lost"),
    ("closed via closed_at", "{followup_state:{closed_at:'2026-07-01'}}", "lost"),
])
def test_the_simple_cases(desc, row_js, expect):
    assert run(f"out(C.column(row({row_js}), T))") == expect, desc


def test_our_decision_beats_the_customers_state():
    """THE collision: sent-and-not-viewed AND paused three months. Paused wins, because it is
    the answer to "is there anything to do today"."""
    got = run("out(C.column(row({proposal_status:'sent',"
              "followup_state:{enrolled:1,enabled:1,paused_until:'2026-10-12'}}), T))")
    assert got == "paused"


def test_approved_outranks_paused_and_lost_outranks_everything():
    got = run("out([ C.column(row({proposal_status:'approved',"
              "  followup_state:{paused_until:'2026-10-12'}}), T),"
              "C.column(row({proposal_status:'closed_lost',"
              "  followup_state:{enrolled:1,enabled:1,paused_until:'2026-10-12'}}), T) ])")
    assert got == ["approved", "lost"]


def test_a_lapsed_pause_falls_back_instead_of_sticking():
    """String compare against Central's today, like crm-core's pausedUntil — so a pause that
    has run out simply stops matching, with no sweep job needed."""
    got = run("out([ C.column(row({followup_state:{enrolled:1,enabled:1,"
              "  paused_until:'2026-07-01'}}), T),"
              "C.column(row({proposal_status:'viewed',followup_state:{paused_until:'2026-07-01'}}), T) ])")
    assert got == ["chasing", "viewed"]


def test_automation_off_is_not_chasing():
    """"Chasing" has to mean reminders are actually going out. Enrolled-but-disabled, or never
    enrolled, sits in the customer column it came from — the board must not imply a cadence
    that is switched off."""
    got = run("out([ C.column(row({proposal_status:'viewed',"
              "  followup_state:{enrolled:1,enabled:0}}), T),"
              "C.column(row({proposal_status:'viewed',followup_state:{}}), T),"
              "C.column(row({proposal_status:'sent',followup_state:{enrolled:0,enabled:1}}), T) ])")
    assert got == ["viewed", "viewed", "sent"]


def test_every_row_lands_in_exactly_one_column():
    got = run("""
      const rows = [row({}), row({proposal_status:'viewed'}),
        row({followup_state:{enrolled:1,enabled:1}}),
        row({followup_state:{enrolled:1,enabled:1,paused_until:'2026-10-12'}}),
        row({proposal_status:'approved'}), row({proposal_status:'closed_lost'})];
      const g = C.group(rows, T);
      out([Object.keys(g).length, Object.values(g).reduce((n,a)=>n+a.length,0)]);
    """)
    assert got == [6, 6], "group() must place every row once and keep all six columns"


# ── who may move what ─────────────────────────────────────────────────
def test_customer_owned_columns_refuse_every_drop():
    """The rule that keeps the board from recording something untrue."""
    got = run("const p = row({followup_state:{enrolled:1,enabled:1}});"
              "out(['sent','viewed','approved'].map(c => C.canMove(p, c, T)));")
    assert got == [False, False, False]


def test_our_columns_accept_a_move():
    got = run("const p = row({followup_state:{enrolled:1,enabled:1}});"
              "out([C.canMove(p,'paused',T), C.canMove(p,'lost',T)]);")
    assert got == [True, True]


def test_a_card_cannot_be_dropped_on_its_own_column():
    got = run("out(C.canMove(row({followup_state:{enrolled:1,enabled:1}}), 'chasing', T))")
    assert got is False


def test_an_approved_proposal_cannot_be_closed_lost():
    """The portal returns 400 already_approved for this. Offering a move the server will
    refuse is worse than not offering it."""
    got = run("out(C.canMove(row({proposal_status:'approved'}), 'lost', T))")
    assert got is False


def test_an_unknown_column_is_refused():
    got = run("out([C.canMove(row({}), 'nonsense', T), C.movePlan(row({}), 'nonsense', T)])")
    assert got == [False, None]


# ── what a drop actually DOES ─────────────────────────────────────────
def test_dropping_on_paused_asks_for_months_and_delays():
    """Months, not an arbitrary date — the portal only accepts 1-4 (invalid_months otherwise),
    and those are the choices in Will's cadence diagram."""
    got = run("const p = row({followup_state:{enrolled:1,enabled:1}});"
              "const plan = C.movePlan(p,'paused',T); out([plan.status, plan.needs]);")
    assert got == ["delayed", "months"]


def test_dropping_on_closed_lost_asks_why():
    got = run("const p = row({followup_state:{enrolled:1,enabled:1}});"
              "const plan = C.movePlan(p,'lost',T); out([plan.status, plan.needs]);")
    assert got == ["closed_lost", "reason"]


def test_resuming_a_paused_and_disabled_card_needs_two_writes():
    """The trap. The portal's resume_followups() clears followup_paused_until but NOT
    followup_disabled_at, so one request would land the card in Chasing with nothing actually
    sending — the worst kind of wrong, because it looks fine."""
    got = run("const p = row({followup_state:{enrolled:1,enabled:0,paused_until:'2026-10-12'}});"
              "const plan = C.movePlan(p,'chasing',T); out([plan.status, plan.then]);")
    assert got == ["active", ["enable_automation"]]


def test_resuming_a_still_enabled_card_needs_only_one():
    got = run("const p = row({followup_state:{enrolled:1,enabled:1,paused_until:'2026-10-12'}});"
              "const plan = C.movePlan(p,'chasing',T); out(plan.then);")
    assert got == []


def test_a_never_enrolled_card_moved_to_chasing_gets_enrolled():
    """Enrolling is what `followup-automation {enabled:true}` does for legacy rows — without
    it there is no cadence to resume."""
    got = run("const p = row({proposal_status:'viewed', followup_state:{}});"
              "const plan = C.movePlan(p,'chasing',T); out(plan.then);")
    assert got == ["enable_automation"]


# ── the neglect stripe ────────────────────────────────────────────────
def test_never_chased_is_the_worst_case_not_a_blank():
    """Same rule the list sorts by: a proposal nobody has ever chased is the most urgent thing
    on the page, not a missing value."""
    got = run("out(C.neglect(row({last_followup_at:null}), Date.parse('2026-08-04T12:00:00Z')))")
    assert got == "cold"


@pytest.mark.parametrize("days_ago,expect", [(9, "cold"), (7, "cold"), (4, "warm"),
                                             (3, "warm"), (1, "fine"), (0, "fine")])
def test_the_stripe_tracks_how_long_it_has_been_ignored(days_ago, expect):
    got = run(f"""
      const now = Date.parse('2026-08-04T12:00:00Z');
      const ago = (d) => new Date(now - d*86400000).toISOString();
      out(C.neglect(row({{last_followup_at: ago({days_ago}), last_activity_at: ago({days_ago})}}), now));
    """)
    assert got == expect


@pytest.mark.parametrize("status", ["approved", "closed_lost"])
def test_finished_proposals_are_never_nagged_about(status):
    """Colouring a won job red because nobody has chased it would train people to ignore the
    colour."""
    got = run(f"out(C.neglect(row({{proposal_status:'{status}', last_followup_at:null}}), "
              f"Date.parse('2026-08-04T12:00:00Z')))")
    assert got == "fine"


def test_an_unparseable_date_does_not_produce_nan():
    got = run("out(C.neglect(row({last_followup_at:'not-a-date'}), "
              "Date.parse('2026-08-04T12:00:00Z')))")
    assert got in ("fine", "cold")          # either verdict is fine; NaN is not


# ── header totals + robustness ────────────────────────────────────────
def test_the_header_totals_only_real_numbers():
    """One row without a value would otherwise turn a column header into "$NaN"."""
    got = run("out(C.load([{approved_total:100},{approved_total:null},{},"
              "{approved_total:'nope'}]))")
    assert got == {"count": 4, "value": 100}


def test_a_null_feed_does_not_throw():
    """The page paints before the first fetch lands."""
    got = run("out([C.group(null, T).sent.length, C.load(null), C.load([])])")
    assert got[0] == 0 and got[1]["count"] == 0 and got[2]["count"] == 0


def test_a_row_with_no_followup_state_is_handled():
    """Rows arrive from the portal; a missing followup_state must not throw."""
    got = run("out([C.column({proposal_status:'sent'}, T), C.isLost({}), "
              "C.pausedUntil({}, T)])")
    assert got == ["sent", False, ""]
