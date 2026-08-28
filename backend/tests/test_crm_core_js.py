"""The CRM board's logic, exercised under node.

Which column a proposal sits in, which date the card shows, and who owns it are all
decided in frontend/js/crm-core.js. Every one of those has a plausible wrong answer
that looks fine on screen — a lost deal still listed as live work, a column sorted by
the wrong clock, a name that is really just whoever built the estimate — so they need
a test even though they don't run in Python.

Skipped when node isn't installed; it's on the dev box and in the Docker image.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

CORE = (pathlib.Path(__file__).resolve().parents[2]
        / "frontend" / "js" / "crm-core.js")

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is not installed")


def run(script: str):
    """Run `script` with `C` bound to the module; returns its printed JSON."""
    prelude = (
        "const C = require(%s);\n"
        "const out = (v) => console.log(JSON.stringify(v));\n" % json.dumps(str(CORE))
    )
    proc = subprocess.run(["node", "-e", prelude + script],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def prop(**kw):
    """A pipeline row with the shape the portal actually sends."""
    base = {"proposal_id": "p", "proposal_status": "sent", "deposit_status": "pending",
            "schedule_status": "pending", "contacts_status": "pending",
            "deposit_required": True, "approved_total": None,
            "assigned_estimator": None, "estimator_email": None,
            "followup_state": {"enrolled": True, "enabled": True,
                               "paused_until": None, "closed_lost_reason": None,
                               "closed_at": None},
            "sent_at": "2026-07-01T12:00:00+00:00"}
    base.update(kw)
    return base


def stage(**kw):
    return run("out(C.stage(%s));" % json.dumps(prop(**kw)))


# ── which column ────────────────────────────────────────────────────────────
def test_closed_lost_outranks_every_other_signal():
    """A customer who said they aren't moving forward must not keep appearing as
    live work — not even if the job had already been scheduled before they said so."""
    assert stage(proposal_status="closed_lost", schedule_status="scheduled",
                 deposit_status="received", contacts_status="received") == "Closed lost"


def test_the_normal_progression():
    """The fourth column reads "Won/Approved" as of 2026-08-28, not "Approved".

    Marking a job won used to lift its card off the Active board onto a Won tab of its own. It no
    longer does — a won job still owes a deposit and a set of contacts, and the sales meeting is
    run off the Active board — so the by-hand won mark and the customer's approval now share one
    column here. Only the COLUMN was renamed: "Approved" still names the milestone EVENT, which is
    why the lastActivity tests further down still expect that word."""
    assert stage() == "Sent"
    assert stage(proposal_status="viewed") == "Viewed"
    assert stage(proposal_status="approved") == "Won/Approved"
    assert stage(proposal_status="approved", deposit_status="submitted") == "Deposit submitted"
    assert stage(proposal_status="approved", deposit_status="received") == "Deposit received"
    assert stage(proposal_status="approved", deposit_status="received",
                 contacts_status="received") == "Contact info"
    # There used to be a "Scheduled" assertion here. Hanz removed scheduling from the CRM and
    # the customer portal on 2026-08-11, notification included, because Treadwell books the
    # date on the phone. A scheduled job now reads as the furthest stage that still exists,
    # and that it does not fall OFF the board is pinned in test_schedule_removed.py — which is
    # the assertion that matters, since group() drops any row whose stage is not a column.
    assert stage(proposal_status="approved", schedule_status="scheduled") == "Won/Approved"


def test_a_project_created_but_never_sent_comes_before_sent():
    """The board's first column, added 2026-08-11. Read before every portal state, because a
    synthesised draft row has none of them — see test_created_not_sent.py."""
    assert stage(not_sent=True) == "Created but not sent"


def test_an_unpaid_deal_never_reads_as_further_along_than_a_paid_one():
    """The portal lets a customer submit contacts straight after approving. Without
    the deposit gate that deal would jump two columns ahead of one that has paid.

    The column it falls back to was relabelled "Won/Approved" on 2026-08-28. The gate itself is
    untouched — an unpaid deal is held exactly where it was."""
    assert stage(proposal_status="approved", contacts_status="received") == "Won/Approved"


def test_a_job_that_collects_no_deposit_can_still_advance():
    """Typical for GC work. Gating on a deposit that was never asked for would park
    it in Won/Approved permanently."""
    assert stage(proposal_status="approved", deposit_required=False,
                 contacts_status="received") == "Contact info"


def test_an_invoiced_job_still_gates_even_when_the_flag_says_otherwise():
    """Someone sent a request anyway — the money is genuinely outstanding, so the
    flag doesn't get to wave it through.

    Held in "Won/Approved", which is what that column has been called since 2026-08-28. The
    rename does not soften the gate: money still outstanding still stops the card here."""
    assert stage(proposal_status="approved", deposit_required=False,
                 deposit_requested_at="2026-07-02T00:00:00+00:00",
                 contacts_status="received") == "Won/Approved"


def test_a_confirmed_deposit_cannot_fall_back_into_submitted():
    got = run("out(C.stage(%s));" % json.dumps(prop(
        proposal_status="approved", deposit_status="received")))
    assert got == "Deposit received"


# ── the won mark, and what it does not do ───────────────────────────────────
# stage() reordered by one line on 2026-08-28: the won mark now outranks not_sent and still sits
# BELOW the deposit branches. Both halves of that are easy to lose in a refactor without emptying
# a column or throwing, because every answer involved is a real column — a card just quietly reads
# as the wrong one. Hence three tests on an ordering rather than a trust in the source comment.
def test_a_job_marked_won_before_it_was_ever_sent_reads_as_won():
    """The Trabon complaint, pinned. Hanz, 2026-08-20: "I marked Trabon Group project as Won but
    it's still in the Created but Not Sent bucket."

    `won_at` is a DRAFT-side field, so a synthesised unsent row carries it while carrying no portal
    state whatsoever. Testing not_sent first therefore made the one field an unsent card does have
    the one field that could never be read. The mark is a person overriding the derived rule, and
    an override that the estimator can watch do nothing is worse than no button at all."""
    assert stage(won_at="2026-08-20T00:00:00+00:00", not_sent=True) == "Won/Approved"
    # And the column it jumped is still reachable by the cards that belong in it — the reorder
    # promoted the mark, it did not retire "Created but not sent".
    assert stage(not_sent=True) == "Created but not sent"


def test_winning_a_job_never_hides_the_work_still_owed_on_it():
    """The won mark sits BELOW the deposit and contacts branches on purpose. A won job whose money
    has landed still reads "Deposit received", and one whose contacts are in still reads "Contact
    info", because the Active board is what the sales meeting is run off: a paid job parked in
    Won/Approved is a job nobody is chasing. Winning is not the end of the work — it is the point
    the rest of it starts."""
    won = {"won_at": "2026-08-20T00:00:00+00:00"}
    assert stage(deposit_status="submitted", **won) == "Deposit submitted"
    assert stage(deposit_status="received", **won) == "Deposit received"
    assert stage(deposit_status="received", contacts_status="received", **won) == "Contact info"


def test_a_card_leaves_the_board_only_when_a_human_hands_it_off():
    """isHandedOff reads one field and derives nothing, and that is the whole 2026-08-28 change.

    Winning no longer removes a card; pressing Hand it off does. So the two answers have to stay
    independent in both directions — a won job with no hand-off stamp is still on the Active board,
    and the stamp alone is what takes it off. Deriving hand-off from won state would silently
    reinstate the behaviour that was deliberately removed."""
    got = run("out([C.isHandedOff(%s), C.isHandedOff(%s), C.isHandedOff(%s), C.isWon(%s)]);" % (
        json.dumps(prop()),
        json.dumps(prop(won_at="2026-08-20T00:00:00+00:00")),
        json.dumps(prop(handed_off_at="2026-08-28T00:00:00+00:00")),
        json.dumps(prop(handed_off_at="2026-08-28T00:00:00+00:00"))))
    assert got == [False, False, True, False]


# ── what date ───────────────────────────────────────────────────────────────
def test_the_card_names_the_newest_thing_that_happened():
    got = run("out(C.lastActivity(%s));" % json.dumps(prop(
        proposal_status="approved",
        viewed_at="2026-07-02T00:00:00+00:00",
        approved_at="2026-07-05T00:00:00+00:00")))
    assert got == {"ts": "2026-07-05T00:00:00+00:00", "label": "Approved"}


def test_a_customer_message_beats_an_older_milestone():
    """Otherwise a live conversation reads as a deal nobody has touched since it
    was viewed three weeks ago."""
    got = run("out(C.lastActivity(%s));" % json.dumps(prop(
        proposal_status="viewed",
        last_viewed_at="2026-07-02T00:00:00+00:00",
        last_message_at="2026-07-28T00:00:00+00:00")))
    assert got["label"] == "Message"


def test_an_unnameable_server_timestamp_dates_the_card_without_mislabelling_it():
    """`last_activity_at` spans events we get no named stamp for. Taking the date but
    not inventing a label is the honest read — a wrong label is worse than a vague one."""
    got = run("out(C.lastActivity(%s));" % json.dumps(prop(
        last_activity_at="2026-07-30T00:00:00+00:00")))
    assert got == {"ts": "2026-07-30T00:00:00+00:00", "label": "Activity"}


def test_a_stale_server_figure_never_backdates_a_known_milestone():
    got = run("out(C.lastActivity(%s));" % json.dumps(prop(
        proposal_status="approved",
        approved_at="2026-07-20T00:00:00+00:00",
        last_activity_at="2026-07-02T00:00:00+00:00")))
    assert got["label"] == "Approved"


def test_time_in_stage_reads_the_column_own_clock_not_the_last_thing_that_happened():
    """The whole point of the stage sort: a deal viewed weeks ago whose customer
    wrote yesterday must NOT outrank one that only just landed in the column."""
    got = run("out([C.stageTs(%s), C.activityTs(%s)]);" % (
        json.dumps(prop(proposal_status="viewed",
                        last_viewed_at="2026-07-02T00:00:00+00:00",
                        last_message_at="2026-07-28T00:00:00+00:00",
                        last_activity_at="2026-07-28T00:00:00+00:00")),
        json.dumps(prop(proposal_status="viewed",
                        last_viewed_at="2026-07-02T00:00:00+00:00",
                        last_message_at="2026-07-28T00:00:00+00:00",
                        last_activity_at="2026-07-28T00:00:00+00:00"))))
    assert got == ["2026-07-02T00:00:00+00:00", "2026-07-28T00:00:00+00:00"]


def test_a_proposal_older_than_its_stage_stamp_still_dates():
    """The per-stage columns were added after these rows existed, so a deal already
    sitting in Deposit received has no deposit_received_at. Blanking it would sort it
    to the bottom forever."""
    got = run("out(C.stageTs(%s));" % json.dumps(prop(
        proposal_status="approved", deposit_status="received",
        approved_at="2026-07-10T00:00:00+00:00")))
    assert got == "2026-07-10T00:00:00+00:00"


def test_a_lost_deal_dates_from_when_it_closed():
    got = run("out(C.stageTs(%s));" % json.dumps(prop(
        proposal_status="closed_lost",
        followup_state={"enrolled": True, "enabled": True, "paused_until": None,
                        "closed_lost_reason": "price", "closed_at": "2026-07-22T00:00:00+00:00"})))
    assert got == "2026-07-22T00:00:00+00:00"


# ── whose it is ─────────────────────────────────────────────────────────────
def test_an_explicit_assignment_wins_over_the_draft_owner():
    got = run("out([C.estimatorOf(%s), C.isAssigned(%s)]);" % (
        json.dumps(prop(assigned_estimator="kyle@wetreadwell.com",
                        estimator_email="hanz@wetreadwell.com")),
        json.dumps(prop(assigned_estimator="kyle@wetreadwell.com",
                        estimator_email="hanz@wetreadwell.com"))))
    assert got == ["kyle@wetreadwell.com", True]


def test_with_nobody_assigned_the_owner_shows_but_is_not_claimed_as_an_assignment():
    """The board marks this case, because "Hanz" on an unassigned card reads as a
    commitment nobody made."""
    got = run("out([C.estimatorOf(%s), C.isAssigned(%s)]);" % (
        json.dumps(prop(estimator_email="hanz@wetreadwell.com")),
        json.dumps(prop(estimator_email="hanz@wetreadwell.com"))))
    assert got == ["hanz@wetreadwell.com", False]


def test_a_name_is_read_off_the_address():
    got = run("out([C.nameOf('kyle.loseke@wetreadwell.com'), C.nameOf('troy@x.com'), C.nameOf('')]);")
    assert got == ["Kyle Loseke", "Troy", ""]


# ── follow-up state ─────────────────────────────────────────────────────────
def test_a_pause_lapses_on_the_day_it_expires_in_central_time():
    """Compared as plain dates against CENTRAL's today, never the viewer's — the
    board is read from other timezones and a pause must not look expired a day early."""
    p = json.dumps(prop(followup_state={"enrolled": True, "enabled": True,
                                        "paused_until": "2026-09-01",
                                        "closed_lost_reason": None, "closed_at": None}))
    got = run("out([C.pausedUntil(%s,'2026-08-31'), C.pausedUntil(%s,'2026-09-01'), C.pausedUntil(%s,'2026-09-02')]);"
              % (p, p, p))
    assert got == ["2026-09-01", "2026-09-01", ""]


def test_automation_being_on_says_nothing_but_being_off_does():
    on = json.dumps(prop())
    off = json.dumps(prop(followup_state={"enrolled": True, "enabled": False,
                                          "paused_until": None,
                                          "closed_lost_reason": None, "closed_at": None}))
    never = json.dumps(prop(followup_state={"enrolled": False, "enabled": False,
                                            "paused_until": None,
                                            "closed_lost_reason": None, "closed_at": None}))
    got = run("out([C.followupOff(%s), C.followupOff(%s), C.followupOff(%s)]);" % (on, off, never))
    # A legacy proposal was never enrolled — nothing was switched off, so no chip.
    assert got == [False, True, False]


def test_a_lost_reason_renders_as_words_and_an_unknown_code_as_nothing():
    """Two staff answers, one customer-only answer, an invented code and no reason at all.

    `another_contractor` read "Another contractor" here until 2026-08-20, when the cross-repo
    comparison went in (test_close_reason_vocabulary.py) and found the portal had been saying
    "Selected another contractor" about the same key for weeks. The portal's wording won, because
    it is also the wording on the customer's own radio button. Kyle's two answers are asserted
    beside it so this test covers both halves of the derived map rather than only the tail of it."""
    got = run("out([C.lostReason(%s), C.lostReason(%s), C.lostReason(%s), C.lostReason(%s),"
              " C.lostReason(%s)]);" % (
                  json.dumps(prop(followup_state={"closed_lost_reason": "another_contractor"})),
                  json.dumps(prop(followup_state={"closed_lost_reason": "not_low_bid"})),
                  json.dumps(prop(followup_state={"closed_lost_reason": "canceled"})),
                  json.dumps(prop(followup_state={"closed_lost_reason": "invented"})),
                  json.dumps(prop())))
    assert got == ["Selected another contractor", "Not Low Bid", "Project Cancelled", "", ""]


def test_a_hold_answer_is_not_a_lost_reason():
    """The two answers that pause a bid have no business rendering as a cause of death: a held bid
    is on the Active board, and a Lost column headed "Project on Hold" would be a column of live
    work on the tab of dead work. HOLD_REASON is where those two live."""
    got = run("out([C.lostReason(%s), C.lostReason(%s)]);" % (
        json.dumps(prop(followup_state={"closed_lost_reason": "on_hold"})),
        json.dumps(prop(followup_state={"closed_lost_reason": "small_bid_pending"}))))
    assert got == ["", ""], "a hold answer renders as a lost reason: %r" % got


# ── ordering ────────────────────────────────────────────────────────────────
def _ids(field, direction, rows):
    return run("out(C.sort(%s, %s, %s).map(r => r.proposal_id));"
               % (json.dumps(rows), json.dumps(field), json.dumps(direction)))


def test_blanks_stay_last_in_both_directions():
    """Flipping a sort must not surface the empty cards first — they carry no
    information and would bury everything that does."""
    rows = [prop(proposal_id="none"), prop(proposal_id="has", approved_total=1000.0)]
    assert _ids("total", "desc", rows) == ["has", "none"]
    assert _ids("total", "asc", rows) == ["has", "none"]


def test_estimators_order_by_name_not_by_address():
    """Sorted on the raw address, "aaron.troy@" would come before "kyle@" — right
    answer by luck. "zach.abbott@" vs "kyle@" is where it breaks."""
    rows = [prop(proposal_id="z", assigned_estimator="zach.abbott@wetreadwell.com"),
            prop(proposal_id="k", assigned_estimator="kyle@wetreadwell.com")]
    assert _ids("estimator", "asc", rows) == ["k", "z"]


def test_the_stage_sort_orders_each_column_by_its_own_milestone():
    """Both are in Viewed. `old` was viewed first but has a fresher message, so
    last-activity order would invert them."""
    rows = [
        prop(proposal_id="old", proposal_status="viewed",
             last_viewed_at="2026-07-01T00:00:00+00:00",
             last_activity_at="2026-07-29T00:00:00+00:00"),
        prop(proposal_id="new", proposal_status="viewed",
             last_viewed_at="2026-07-20T00:00:00+00:00",
             last_activity_at="2026-07-20T00:00:00+00:00"),
    ]
    assert _ids("stage", "desc", rows) == ["new", "old"]      # most recently arrived first
    assert _ids("stage", "asc", rows) == ["old", "new"]       # longest sitting there first
    assert _ids("activity", "desc", rows) == ["old", "new"]   # the other question


def test_an_unknown_sort_field_falls_back_instead_of_blanking_the_board():
    rows = [prop(proposal_id="a", last_activity_at="2026-07-01T00:00:00+00:00"),
            prop(proposal_id="b", last_activity_at="2026-07-09T00:00:00+00:00")]
    assert _ids("nonsense", "desc", rows) == ["b", "a"]


def test_sorting_does_not_mutate_the_caller_list():
    got = run("const rows = %s; C.sort(rows, 'total', 'asc');"
              "out(rows.map(r => r.proposal_id));"
              % json.dumps([prop(proposal_id="a", approved_total=9.0),
                            prop(proposal_id="b", approved_total=1.0)]))
    assert got == ["a", "b"]


# ── grouping ────────────────────────────────────────────────────────────────
def test_grouping_covers_every_column_even_the_empty_ones():
    got = run("out(Object.keys(C.group([], C.STAGES)));")
    # "Scheduled" came off the end on 2026-08-11 and "Created but not sent" went on the front
    # the same day. The fourth column was relabelled "Won/Approved" on 2026-08-28, when winning a
    # job stopped taking its card off this board. All three are separate changes with their own
    # files; this stays the assertion that the GROUPING covers every column, so an empty column
    # still renders — and a column key that drifts from what stage() returns empties it silently.
    assert got == ["Created but not sent", "Sent", "Viewed", "Won/Approved", "Deposit submitted",
                   "Deposit received", "Contact info"]


def test_a_stage_with_no_column_is_dropped_not_thrown():
    """Closed-lost is hidden by default, so its rows reach group() with no column to
    land in. A portal that grows a new status must not blank the whole board."""
    got = run("out(C.group(%s, C.STAGES));" % json.dumps([prop(proposal_status="closed_lost")]))
    assert all(v == [] for v in got.values())


# ── estimator avatars ───────────────────────────────────────────────────────
# A coloured circle of initials, the way BasisBoard shows an assignee. The colour has
# to be derived, not stored: assigning by list position would repaint everybody the
# moment somebody joins, and a per-page choice would give one person two colours.
def test_initials_come_off_the_name_not_the_raw_address():
    got = run("out(['kyle.loseke@wetreadwell.com','troy@wetreadwell.com',"
              "'marisoll.monserrat.ontiveros@x.com','autopilot',''].map(C.initialsOf));")
    # First and LAST word, so "Marisoll Monserrat Ontiveros" reads as MO — which is how
    # the person who owns that name would write it. Two letters at most; a third stops
    # fitting a 20px circle legibly.
    assert got == ["KL", "T", "MO", "A", ""]


def test_initials_work_from_a_display_name_too():
    """Half the app has an email and half has a BasisBoard display name."""
    got = run("out(['Kyle Loseke','Troy Holmes','Marisoll Monserrat Ontiveros']"
              ".map(C.initialsOf));")
    assert got == ["KL", "TH", "MO"]


def test_a_colour_is_stable_for_one_person():
    """Same estimator, same colour on every page, in every session, on every machine —
    otherwise the colour carries no information at all."""
    got = run("out([C.colorOf('kyle@wetreadwell.com'), C.colorOf('kyle@wetreadwell.com')]);")
    assert got[0] == got[1]


def test_the_address_is_matched_case_insensitively():
    """The portal hands back whatever was typed. Two casings of one person must not be
    two colours."""
    got = run("out([C.colorOf('Kyle@WeTreadwell.com'), C.colorOf('  kyle@wetreadwell.com ')]);")
    assert got[0] == got[1]


def test_one_person_is_one_colour_across_both_data_sources():
    """THE reason the hash keys on a first name. Our screens know Kyle as
    kyle.loseke@wetreadwell.com; the Bid Pipeline and Analytics read BasisBoard, which
    only says "Kyle Loseke". Hashing either string whole paints that person two different
    colours across the app, which defeats colour-coding entirely."""
    got = run("out([['kyle.loseke@wetreadwell.com','Kyle Loseke'],"
              "['troy@wetreadwell.com','Troy Holmes'],"
              "['hanz@wetreadwell.com','Hanz de la Cruz'],"
              "['marisoll.monserrat.ontiveros@x.com','Marisoll Monserrat Ontiveros']]"
              ".map(p => C.colorOf(p[0]) === C.colorOf(p[1])));")
    assert got == [True, True, True, True]


def test_the_identity_key_is_the_first_name():
    got = run("out(['kyle.loseke@wetreadwell.com','Kyle Loseke','KYLE',"
              "'kyle-loseke@x.com',''].map(C.identityKey));")
    assert got == ["kyle", "kyle", "kyle", "kyle", ""]


def test_every_colour_is_one_of_ours():
    """Guards the hash: an out-of-range index would yield undefined and paint a
    transparent chip with unreadable white text on it."""
    # The empty case is excluded on purpose — it gets the reserved "nobody" neutral,
    # which lives outside the palette. See the test below.
    got = run("out(['a@x.com','b@y.com','c@z.com','zz.top@w.com','1@2.co',"
              "'x','autopilot','kyle.loseke@wetreadwell.com','troy@wetreadwell.com',"
              "'hanz@wetreadwell.com','greg.ingebretson@x.com'].map(C.colorOf)"
              ".every(c => C.AVATAR_COLORS.includes(c)));")
    assert got is True


def test_every_estimator_on_the_roster_gets_their_own_colour():
    """The seven people who actually get assigned proposals all separate — that's the
    number the feature is judged on."""
    got = run("const r=['kyle.loseke@wetreadwell.com','troy@wetreadwell.com',"
              "'hanz@wetreadwell.com','greg.ingebretson@x.com','dane.cordova@x.com',"
              "'rj.urzendowski@x.com','marisoll.monserrat.ontiveros@x.com'];"
              "out(new Set(r.map(C.colorOf)).size);")
    assert got == 7


def test_a_wider_cast_still_mostly_separates():
    """Non-estimators (Will, Liz) and the autopilot actor also render chips in places.
    Ten names into fourteen buckets averages ~7.2 distinct by birthday paradox, so 8 is
    the honest expectation, not a defect — and no salt or hash we tried beat it.

    What the feature actually promises is the OTHER direction: one person is always ONE
    colour. Two people sharing one costs a little scanning speed and never misattributes
    anything, because the name is rendered beside every chip."""
    got = run("const r=['kyle.loseke@wetreadwell.com','troy@wetreadwell.com',"
              "'hanz@wetreadwell.com','greg.ingebretson@x.com','dane.cordova@x.com',"
              "'rj.urzendowski@x.com','marisoll.monserrat.ontiveros@x.com',"
              "'liz@wetreadwell.com','autopilot','will@wetreadwell.com'];"
              "out(new Set(r.map(C.colorOf)).size);")
    assert got >= 9, f"only {got} distinct colours across ten names — palette or hash regressed"


def test_two_people_on_one_board_do_not_share_a_colour():
    """Caught on staging, not in a test: with djb2 the assigned Kyle and a demo account
    drew the same colour on the same board. sdbm separates short first names far better —
    12 distinct across a wide cast where djb2 managed 10."""
    got = run("out(new Set(['kyle.loseke@wetreadwell.com','demo@example.com',"
              "'hanz@wetreadwell.com','autopilot'].map(C.colorOf)).size);")
    assert got == 4


def test_no_palette_colour_can_be_mistaken_for_the_nobody_grey():
    """An earlier slate entry sat two hex digits from AVATAR_NONE, so a real person could
    look like the unassigned chip sitting next to them."""
    # The real property is SATURATION, not the leading hex digit: #6D28D9 starts with a
    # 6 and is plainly violet. A grey is anything whose channels sit close together.
    got = run("""
      const sat = (h) => {
        const [r,g,b] = [1,3,5].map(i => parseInt(h.substr(i,2),16)/255);
        const mx = Math.max(r,g,b), mn = Math.min(r,g,b);
        return mx === 0 ? 0 : (mx - mn) / mx;
      };
      out({ dullest: Math.min(...C.AVATAR_COLORS.map(sat)),
            noneSat: sat(C.AVATAR_NONE),
            greyish: C.AVATAR_COLORS.filter(c => sat(c) < 0.35) });
    """)
    assert got["greyish"] == [], f"near-grey palette entries: {got['greyish']}"
    # And the neutral itself really is grey, so "nobody" reads as absence of a person.
    assert got["noneSat"] < 0.25
    assert got["dullest"] > 0.5


def test_the_palette_is_sized_for_the_eye_not_the_hash():
    """Fourteen is roughly where a human stops telling 20px circles apart. Widening it to
    dodge hash collisions would just trade them for perceptual ones."""
    assert run("out(C.AVATAR_COLORS.length);") == 14
    assert run("out(new Set(C.AVATAR_COLORS).size);") == 14      # no duplicate entries


def test_the_nobody_colour_is_not_one_a_person_can_wear():
    """Reserved outside the palette, so the colour that means "unassigned" can never
    also be somebody's colour. It has to stay out of the list rather than be carved from
    it — dropping an entry to free one cost three roster separations, because a modulo
    over a shorter palette reshuffles everybody."""
    got = run("out([C.colorOf(''), C.colorOf(null), C.AVATAR_COLORS.includes(C.colorOf(''))]);")
    assert got[0] == got[1] == "#4B5563"
    assert got[2] is False


def test_the_chip_carries_the_colour_inline_and_hides_from_screen_readers():
    """The CSP forbids an inline <style>, so a per-person colour has to ride on the
    element. aria-hidden because the name sits right next to it — a reader announcing
    "K L Kyle Loseke" is noise."""
    got = run("out(C.avatarHtml('kyle.loseke@wetreadwell.com'));")
    assert 'class="tw-av"' in got
    assert "background:" + run("out(C.colorOf('kyle.loseke@wetreadwell.com'));") in got
    assert ">KL<" in got
    assert 'aria-hidden="true"' in got


def test_an_inherited_owner_renders_dimmed():
    """Nobody chose them. The card also says so in words with a "?" — the dimming is
    reinforcement, never the only signal."""
    got = run("out([C.avatarHtml('a@x.com', true), C.avatarHtml('a@x.com', false)]);")
    assert "tw-av-dim" in got[0]
    assert "tw-av-dim" not in got[1]


def test_the_chip_needs_no_escaping_by_construction():
    """It gets interpolated into markup without esc(), so a hostile address must not be
    able to reach the output: initials are letters pulled out by regex and the colour is
    one of our constants."""
    got = run(r"out(C.avatarHtml('\"><script>alert(1)</script>@x.com'));")
    assert "<script>" not in got
    assert "alert" not in got
