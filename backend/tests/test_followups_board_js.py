"""The Follow-ups board: how far the customer has got, and what we may change.

REWRITTEN for the customer-journey columns. Hanz, looking at the board:

    "What I thought is follow ups would look like a CRM and then it's split into categories —
     Not viewed / Seen (through email or through the portal) / No reply (they have opened it but
     not replied)."

He was right that the old columns were confused. They mixed two independent questions:
Sent / Viewed / Approved / Closed lost is where the CUSTOMER stands, while Chasing / Paused is
what OUR automation is doing. A proposal can be un-opened AND paused for three months, so a card
satisfied two columns at once and the code had to rank them — which is why one could read "Sent"
in the table and sit under "Chasing" on the board.

The columns are now one axis, and every proposal is in exactly one:

    not_opened -> seen -> talking -> approved
                                 \\-> lost

"What we are doing about it" became a badge, which is what it always was.

What these tests exist to protect:

  * **Exactly one column, no ranking.** The old bug class was a card qualifying for two.
  * **"Replied" means the CUSTOMER replied.** `last_message_at` is the newest message from
    either side, so a thread where we sent the last note looks identical to one they answered.
    Using it would put silent customers in "In conversation" and quietly stop them being chased.
  * **`unread` is not the same question either.** It counts messages we have not answered, so a
    customer we already replied to would read as never having spoken.
  * **Only Closed lost accepts a drop.** The other four record what the customer did. Dragging a
    card into "Seen" would assert somebody opened a proposal they never opened, and `viewed_at`
    feeds the digest's ranking and its 6 AM sentence — the lie would reach a customer's inbox.
  * **Pause and Resume are actions, not columns**, and resuming a card that is both paused and
    switched off still needs two writes.

Run under node, like test_crm_core_js.py and test_calendar_core_js.py: pure state logic with no
DOM, and the only way to pin column precedence without a browser.
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
        "const out = (v) => console.log(JSON.stringify(v === undefined ? '<undefined>' : v));\n"
        % (json.dumps(str(CORE)), json.dumps(TODAY))
    )
    proc = subprocess.run(["node", "-e", prelude + script],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_module_loads():
    """A syntax error would make every test below fail with the same opaque message."""
    assert run("out(typeof C.column)") == "function"


# ── the columns ───────────────────────────────────────────────────────
def test_the_columns_follow_the_customers_journey_and_only_one_is_ours():
    got = run("out([C.COLUMNS.map(c=>c.id), C.COLUMNS.filter(c=>c.ours).map(c=>c.id)])")
    assert got[0] == ["not_opened", "seen", "talking", "approved", "lost"]
    assert got[1] == ["lost"], (
        "only Closed lost is ours to set; the rest record what the customer did")


def test_every_column_carries_a_label_and_a_subtitle():
    """The subtitle is what makes a column self-explanatory — "Seen" alone does not say these are
    the ones who opened it and never answered."""
    assert run("out(C.COLUMNS.filter(c => !c.label || !c.sub || !c.dot).map(c => c.id))") == []


def test_a_fresh_proposal_nobody_has_opened():
    assert run("out(C.column(row()))") == "not_opened"


def test_an_email_link_click_alone_counts_as_seen():
    """The weak signal still separates a silent customer from a wrong address, which is the
    distinction this column exists to make."""
    assert run("out(C.column(row({link_clicked_at:'2026-08-01T10:00:00Z'})))") == "seen"


def test_a_portal_view_counts_as_seen():
    assert run("out(C.column(row({viewed_at:'2026-08-01T10:00:00Z'})))") == "seen"
    assert run("out(C.column(row({proposal_status:'viewed'})))") == "seen"


def test_a_customer_reply_moves_them_past_seen():
    got = run("out(C.column(row({viewed_at:'2026-08-01T10:00:00Z',"
              " customer_replied_at:'2026-08-02T10:00:00Z'})))")
    assert got == "talking"


def test_a_reply_counts_even_from_someone_who_never_opened_the_portal():
    """They can answer the email without ever signing in. Filing them under "Not opened" would
    earn a reply an automated chase."""
    assert run("out(C.column(row({customer_replied_at:'2026-08-02T10:00:00Z'})))") == "talking"


def test_our_own_last_message_is_not_a_reply():
    """THE one that matters. `last_message_at` is the newest message from either side. Reading it
    as a reply would put every proposal we chased into "In conversation" and quietly stop it being
    chased again."""
    got = run("out(C.column(row({viewed_at:'2026-08-01T10:00:00Z',"
              " last_message_at:'2026-08-03T10:00:00Z'})))")
    assert got == "seen", "our own message was mistaken for the customer replying"


def test_an_unanswered_message_is_not_the_same_question_as_having_replied():
    """`unread` counts what we have not answered yet. A customer we already answered has still
    replied, so they belong in "In conversation"; one with unread messages obviously does too.
    Neither case can be derived from `unread` alone."""
    answered = run("out(C.column(row({customer_replied_at:'2026-08-02T10:00:00Z', unread:0})))")
    waiting = run("out(C.column(row({customer_replied_at:'2026-08-02T10:00:00Z', unread:3})))")
    assert answered == "talking" and waiting == "talking"


def test_approved_wins_over_everything_the_customer_did_before_it():
    got = run("out(C.column(row({proposal_status:'approved',"
              " customer_replied_at:'2026-08-02T10:00:00Z'})))")
    assert got == "approved"


def test_approved_without_ever_opening_the_portal_is_still_approved():
    """They can approve straight from the email link."""
    assert run("out(C.column(row({proposal_status:'approved'})))") == "approved"


def test_lost_wins_over_absolutely_everything():
    got = run("out([C.column(row({proposal_status:'closed_lost',"
              " customer_replied_at:'2026-08-02T10:00:00Z'})),"
              " C.column(row({followup_state:{closed_at:'2026-08-01'}}))])")
    assert got == ["lost", "lost"]


def test_being_paused_no_longer_changes_which_column_it_is_in():
    """This is the fix. A paused proposal the customer never opened used to jump to "Paused",
    which said nothing about the customer and disagreed with the table."""
    assert run("out(C.column(row({followup_state:{paused_until:'2026-12-01'}})))") == "not_opened"


def test_chasing_no_longer_changes_which_column_it_is_in():
    got = run("out(C.column(row({viewed_at:'2026-08-01T10:00:00Z',"
              " followup_state:{enrolled:true, enabled:true}})))")
    assert got == "seen"


def test_every_row_lands_in_exactly_one_column():
    """The old model's whole difficulty was a row qualifying for two. With one axis it cannot."""
    got = run("""
      const rows = [row(), row({link_clicked_at:'x'}), row({viewed_at:'x'}),
        row({customer_replied_at:'x'}), row({proposal_status:'approved'}),
        row({proposal_status:'closed_lost'}),
        row({viewed_at:'x', followup_state:{paused_until:'2026-12-01'}}),
        row({customer_replied_at:'x', followup_state:{enrolled:true, enabled:true}})];
      const g = C.group(rows, T);
      let total = 0;
      for (const k in g) total += g[k].length;
      out([rows.length, total]);
    """)
    assert got[0] == got[1], "a row was dropped or duplicated by group()"


# ── how they saw it ───────────────────────────────────────────────────
def test_the_card_can_say_how_they_saw_it():
    assert run("out(C.seenHow(row({viewed_at:'x'})))") == "portal"
    assert run("out(C.seenHow(row({link_clicked_at:'x'})))") == "email"
    assert run("out(C.seenHow(row()))") == ""


def test_a_portal_view_outranks_an_email_click_in_the_label():
    """Both happened; the portal one is the stronger fact and means a person definitely looked,
    so that is what the card should claim."""
    assert run("out(C.seenHow(row({viewed_at:'x', link_clicked_at:'y'})))") == "portal"


# ── the automation badge ──────────────────────────────────────────────
def test_the_badge_reports_what_we_are_doing():
    assert run("out(C.automation(row({followup_state:{enrolled:true,enabled:true}}), T))") == "chasing"
    assert run("out(C.automation(row({followup_state:{paused_until:'2026-12-01'}}), T))") == "paused"
    assert run("out(C.automation(row({followup_state:{enrolled:true,enabled:false}}), T))") == "off"
    assert run("out(C.automation(row(), T))") == "off"


def test_a_lapsed_pause_is_not_a_pause():
    got = run("out(C.automation(row({followup_state:{paused_until:'2026-01-01', enrolled:true,"
              " enabled:true}}), T))")
    assert got == "chasing", "a pause that expired should stop counting"


def test_the_badge_is_blank_where_chasing_is_meaningless():
    """Nothing is going out for a closed-lost proposal, or an approved one that has been paid."""
    assert run("out(C.automation(row({proposal_status:'closed_lost'}), T))") == ""
    assert run("out(C.automation(row({proposal_status:'approved',"
               " deposit_status:'received'}), T))") == ""
    assert run("out(C.automation(row({proposal_status:'approved',"
               " deposit_required:false}), T))") == ""


def test_an_approved_job_with_the_deposit_OUT_still_reads_as_chasing():
    """This assertion used to be `automation(approved) == ""`, on the reasoning that nothing goes
    out after approval. Hanz, 2026-08-12: "followups should be automated until a deposit has been
    received", so something does — and a blank badge told staff the opposite of the truth while the
    worker emailed the customer every few days.

    `submitted` still counts as in: this page describes what the CUSTOMER is being sent, and their
    reminders stop the moment they tell us the money is on its way."""
    chasing = "{enrolled:true,enabled:true}"
    assert run("out(C.automation(row({proposal_status:'approved', deposit_status:'pending',"
               " followup_state:%s}), T))" % chasing) == "chasing"
    assert run("out(C.automation(row({proposal_status:'approved',"
               " followup_state:%s}), T))" % chasing) == "chasing", (
        "a legacy row with no deposit_status reads as paid, so its badge goes blank")
    assert run("out(C.automation(row({proposal_status:'approved', deposit_status:'submitted',"
               " followup_state:%s}), T))" % chasing) == "", (
        "the customer is shown as still being chased after telling us the deposit is on its way")


def test_a_no_deposit_job_that_was_INVOICED_anyway_still_reads_as_chasing():
    """`deposit_required=false` says none was asked for; `deposit_requested_at` says somebody
    raised an invoice regardless, and the portal chases that money. depositIn() short-circuited on
    the flag alone while claiming in its own docstring to mirror the portal rule — so the card said
    nothing was going out on a job the worker was emailing about.

    crm-core.depositSatisfied already had this right, which is what made the disagreement findable:
    two staff modules, one question, two answers."""
    chasing = "{enrolled:true,enabled:true}"
    assert run("out(C.automation(row({proposal_status:'approved', deposit_required:false,"
               " deposit_requested_at:'2026-08-05T12:00:00Z',"
               " followup_state:%s}), T))" % chasing) == "chasing"
    # And the plain no-deposit job is still settled at approval — the exception must not swallow
    # the rule it is an exception to.
    assert run("out(C.automation(row({proposal_status:'approved', deposit_required:false,"
               " followup_state:%s}), T))" % chasing) == ""


def test_a_paused_won_job_says_paused_rather_than_chasing():
    """The pause check has to stay BELOW the deposit check and above the enrolled check, or a
    customer who asked us to wait is shown as being emailed."""
    got = run("out(C.automation(row({proposal_status:'approved', deposit_status:'pending',"
              " followup_state:{enrolled:true, enabled:true, paused_until:'2026-12-01'}}), T))")
    assert got == "paused"


# ── what may be dragged ───────────────────────────────────────────────
def test_only_closed_lost_accepts_a_drop():
    got = run("out(['not_opened','seen','talking','approved','lost']"
              ".map(id => C.canMove(row({viewed_at:'x'}), id)))")
    assert got == [False, False, False, False, True]


def test_dragging_into_a_customer_column_is_refused_even_from_lost():
    got = run("out(['not_opened','seen','talking','approved']"
              ".map(id => C.canMove(row({proposal_status:'closed_lost'}), id)))")
    assert got == [False, False, False, False]


def test_a_card_cannot_be_dropped_where_it_already_is():
    assert run("out(C.canMove(row({proposal_status:'closed_lost'}), 'lost'))") is False


def test_an_approved_proposal_cannot_be_closed_lost():
    """The portal refuses it (already_approved), and offering a move the server will reject is
    worse than not offering it."""
    assert run("out(C.canMove(row({proposal_status:'approved'}), 'lost'))") is False


def test_an_unknown_column_is_refused():
    assert run("out(C.canMove(row(), 'nope'))") is False
    assert run("out(C.canMove(row(), ''))") is False


# ── the actions ───────────────────────────────────────────────────────
def test_closing_lost_asks_why():
    got = run("out(C.actionPlan(row({viewed_at:'x'}), 'lost', T))")
    assert got["status"] == "closed_lost" and got["needs"] == "reason"


def test_pausing_asks_for_how_long():
    got = run("out(C.actionPlan(row(), 'pause', T))")
    assert got["status"] == "delayed" and got["needs"] == "months"


def test_pausing_something_already_paused_is_not_offered():
    got = run("out(C.actionPlan(row({followup_state:{paused_until:'2026-12-01'}}), 'pause', T))")
    assert got is None


def test_resuming_a_paused_and_disabled_card_needs_two_writes():
    """resume_followups() clears paused_until but NOT followup_disabled_at, so a card that is both
    paused and switched off needs both writes, in this order."""
    got = run("out(C.actionPlan(row({followup_state:{paused_until:'2026-12-01',"
              " enrolled:true, enabled:false}}), 'resume', T))")
    assert got["status"] == "active"
    assert got["then"] == ["enable_automation"]


def test_resuming_a_still_enabled_card_needs_only_one():
    got = run("out(C.actionPlan(row({followup_state:{paused_until:'2026-12-01',"
              " enrolled:true, enabled:true}}), 'resume', T))")
    assert got["then"] == []


def test_a_never_enrolled_card_gets_enrolled_when_resumed():
    assert run("out(C.actionPlan(row({followup_state:{}}), 'resume', T))")["then"] == ["enable_automation"]


def test_resuming_something_already_chasing_is_not_offered():
    got = run("out(C.actionPlan(row({followup_state:{enrolled:true,enabled:true}}), 'resume', T))")
    assert got is None


def test_no_action_is_offered_on_an_approved_or_lost_proposal():
    for st in ("approved", "closed_lost"):
        got = run("out(['pause','resume','lost'].map(a =>"
                  " C.actionPlan(row({proposal_status:'%s'}), a, T) === null))" % st)
        assert got == [True, True, True], st


def test_an_unknown_action_is_refused():
    assert run("out(C.actionPlan(row(), 'delete_everything', T))") is None
    assert run("out(C.actionPlan(row(), '', T))") is None


def test_the_offered_actions_match_the_state():
    """A chasing card offers Pause and Closed lost; a paused one offers Resume instead."""
    chasing = run("out(C.actionsFor(row({followup_state:{enrolled:true,enabled:true}}), T)"
                  ".map(a => a.id))")
    paused = run("out(C.actionsFor(row({followup_state:{paused_until:'2026-12-01'}}), T)"
                 ".map(a => a.id))")
    done = run("out(C.actionsFor(row({proposal_status:'approved'}), T).map(a => a.id))")
    assert chasing == ["pause", "lost"]
    assert paused == ["resume", "lost"]
    assert done == []


# ── neglect stripe ────────────────────────────────────────────────────
def test_never_chased_is_the_worst_case_not_a_blank():
    assert run("out(C.neglect(row(), Date.parse('2026-08-04')))") == "cold"


def test_a_decided_proposal_is_never_flagged_as_neglected():
    for st in ("approved", "closed_lost"):
        got = run("out(C.neglect(row({proposal_status:'%s'}), Date.parse('2026-08-04')))" % st)
        assert got == "fine", st


def test_the_stripe_warms_then_goes_cold():
    warm = run("out(C.neglect(row({last_followup_at:'2026-08-01T00:00:00Z',"
               " last_activity_at:'2026-08-01T00:00:00Z'}), Date.parse('2026-08-04')))")
    cold = run("out(C.neglect(row({last_followup_at:'2026-07-20T00:00:00Z',"
               " last_activity_at:'2026-07-20T00:00:00Z'}), Date.parse('2026-08-04')))")
    fine = run("out(C.neglect(row({last_followup_at:'2026-08-04T00:00:00Z',"
               " last_activity_at:'2026-08-04T00:00:00Z'}), Date.parse('2026-08-04')))")
    assert [warm, cold, fine] == ["warm", "cold", "fine"]


# ── column headers ────────────────────────────────────────────────────
def test_a_column_header_counts_and_totals():
    assert run("out(C.load([{approved_total:100},{approved_total:250},{}]))") == {
        "count": 3, "value": 350}


def test_a_non_numeric_total_does_not_poison_the_sum():
    got = run("out(C.load([{approved_total:'1,000'},{approved_total:100},{approved_total:null}]))")
    assert got == {"count": 3, "value": 100}


# ── never throw on real-world data ────────────────────────────────────
@pytest.mark.parametrize("bad", ["null", "undefined", "{}", "{followup_state:null}",
                                 "{proposal_status:null}", "{customer_replied_at:null}",
                                 "{viewed_at:''}", "{link_clicked_at:''}"])
def test_a_malformed_row_never_throws(bad):
    """The feed is a proxy of the portal's board; a field can be absent on a legacy row and the
    page must still draw."""
    got = run("out([C.column(%s), typeof C.automation(%s, T), C.seenHow(%s)])" % (bad, bad, bad))
    assert got[0] in ("not_opened", "seen", "talking", "approved", "lost")


def test_a_null_feed_does_not_throw():
    got = run("out([Object.keys(C.group(null, T)).length, C.load(null)])")
    assert got[0] == 5
    assert got[1] == {"count": 0, "value": 0}


def test_the_group_keys_are_exactly_the_columns():
    got = run("out(Object.keys(C.group([], T)))")
    assert got == ["not_opened", "seen", "talking", "approved", "lost"]
