"""The drawer's Follow-up tab now the cadence emails the customer itself: the schedule, and no writer.

Hanz, 2026-10-28: "the follow ups should be a follow up email to the customer okay?" The portal's
worker SENDS the customer email at each due follow-up (at most two before they open the proposal and
two after, from sending until it is approved). That reverses remind mode (2026-10-23), when a due
follow-up was parked as a TASK for the estimator to write and send from this drawer. So:

  * a follow-up task left on a pipeline row draws no card and fetches no AI draft (this build has
    no scope groups, so not even a "Decide the other scopes" task is a card here);
  * the per-project schedule is the next email's date and nothing else ("Then every" and "Stop
    after" went with the repeating cadence), and the Follow-ups switch stays;
  * the wording says the tool emails the customer automatically, and that approval stops it.

Everything here is EXECUTED, through drawer-render-harness.js: the real renderDetail paints the
panel, the real focusSection opens the tab, and the real wireFollowup's handlers are pressed.

ONE DISTINCTION IS PINNED ON PURPOSE: the "Tell the estimator" email goes to the assigned estimator,
and the "Tell the team" chips on the Files page (and the per-project notification chips in this same
drawer) are a different list for a different event. The two must not share a data path.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "drawer-render-harness.js"
PORTAL_JS = (FRONTEND / "js" / "portal.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def out():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    assert "fuTask" not in data["errors"], data["errors"].get("fuTask")
    return data


@pytest.fixture(scope="module")
def fu(out):
    return out["fuTask"]


def _decode(s: str) -> str:
    """Entity-decode what the markup carries, `&amp;` LAST, so `&amp;lt;` reads back as the four
    characters `&lt;` that were written rather than as `<`."""
    for ent, ch in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")):
        s = s.replace(ent, ch)
    return s.replace("&amp;", "&")


def _strip_tags(s: str) -> str:
    """Tags removed to a FIXED POINT: one pass over `<<b>script>` leaves a `<script>` behind."""
    while True:
        nxt = re.sub(r"<[^<>]*>", " ", s)
        if nxt == s:
            return s
        s = nxt


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", _decode(_strip_tags(html))).strip()


def _value_of(html: str, el_id: str) -> str:
    m = re.search(r'id="%s"[^>]*\svalue="([^"]*)"' % re.escape(el_id), html)
    assert m, "#%s carries no value attribute" % el_id
    return _decode(m.group(1))


def _block(name: str) -> str:
    m = re.search(r"\n\s{2,6}(?:async\s+)?function " + re.escape(name) + r"\s*\(", PORTAL_JS)
    assert m, "%s() is gone from portal.js" % name
    i = PORTAL_JS.index("{", m.end())
    depth = 0
    for j in range(i, len(PORTAL_JS)):
        if PORTAL_JS[j] == "{":
            depth += 1
        elif PORTAL_JS[j] == "}":
            depth -= 1
            if depth == 0:
                return PORTAL_JS[i:j + 1]
    pytest.fail("unbalanced braces reading %s" % name)


# ── no email writer ──────────────────────────────────────────────────────────
def test_a_cadence_reminder_task_draws_no_card_and_costs_no_ai_draft(fu):
    """A reminder task left on the row from the remind-only weeks, with the tab opened. Before
    2026-10-28 this painted "Follow-up waiting on you" with a Send button and fetched a paid AI
    draft. The worker sends that email itself now, so a Send here would be a second email.

    Mutation: put the task card back into followupPanelHtml, and the ids come back."""
    html = fu["legacy"]["html"]
    for el_id in ("fu-task", "fu-compose", "fu-send", "fu-skip", "fu-called", "fu-snooze"):
        assert 'id="%s"' % el_id not in html, el_id
    assert "waiting on you" not in _text(html)
    assert "until you press Send" not in _text(html)
    assert fu["legacy"]["requests"] == [], "opening the tab still asks for an AI draft"


def test_a_decision_task_draws_no_card_on_this_build(fu):
    """A scope group's "Decide the other scopes" task can only come from a project of several
    proposals, which this build does not have, so it draws nothing either: no decision card, no
    task card, no Send, and nothing fetched."""
    html = fu["decision"]["html"]
    for el_id in ("fu-decide", "fu-dec-close", "fu-task", "fu-send"):
        assert 'id="%s"' % el_id not in html, el_id
    assert 'id="fu-sched"' not in html, "an approved project offers a date for an email"
    assert fu["decision"]["requests"] == []


def test_the_writer_is_gone_from_portal_js():
    """Not just unreachable: deleted, so nothing can wire a Send to a reminder by accident."""
    for name in ("followupComposeHtml", "wireFuCompose", "paintFuCompose", "loadFuDraft",
                 "fuTaskAct", "fuDoneText", "fuLinkState", "fuPutLinkBack", "fuGroupHtml",
                 # and the task card it lived in, with the notice and settle its buttons used
                 "followupTaskHtml", "followupDecisionHtml", "fuNoticeHtml", "fuSay", "fuSettle"):
        assert not re.search(r"function %s\s*\(" % name, PORTAL_JS), name
    code = re.sub(r"//[^\n]*", "", PORTAL_JS)
    assert "FU_DRAFT" not in code and "FU_NOTICE" not in code


# ── what the panel says ───────────────────────────────────────────────────────
def test_the_panel_says_the_tool_emails_the_customer_automatically(fu):
    text = _text(fu["leadOn"]["html"])
    assert ("The tool emails the customer automatically until they approve: at most 2 follow-up "
            "emails before they open the proposal and 2 after.") in text
    assert "Following up automatically until the customer approves, replies" not in text


def test_the_schedule_says_the_days_count_from_the_day_it_was_sent(fu):
    """Hanz, 2026-10-29: "the days should be based off the date it was sent". Each step's 1st email
    counts from the send, so the drawer must not say the opened emails count from the day they open
    it. The 2nd email of a step still counts from its 1st (followup_rules.plan), so the drawer must
    not say "the days" all count from the send either: an estimator would expect a 7-day 2nd email
    on day 7 and it goes on day 10.

    Mutation: put back "The days count from the day the proposal was sent" and this fails."""
    text = _text(fu["schedule"]["html"])
    assert ("as set on Auto Followups. Each step's 1st email counts from the day the proposal was "
            "sent, its 2nd from the 1st, and it stops when they approve.") in text
    assert "The days count from the day the proposal was sent" not in text
    assert "days after they open" not in text


def _toggle_title(html: str) -> str:
    m = re.search(r'<button[^>]*id="fu-toggle"[^>]*\stitle="([^"]*)"', html)
    assert m, "no Follow-ups switch with a title"
    return re.sub(r"\s+", " ", _decode(m.group(1))).strip()


def test_the_switch_does_not_promise_a_fresh_start_when_turned_back_on(fu):
    """Turning follow-ups back on keeps the proposal's send date (set_followup_enabled coalesces
    followup_enrolled_at), and both steps count from it, so an email already due goes at the next
    check. The switch used to say "Start the follow-up cadence from today" here.

    Mutation: drop the f.enrolled branch of the title and this fails."""
    title = _toggle_title(fu["toggleReenable"]["html"])
    assert "from today" not in title, title
    assert title == ("Turn the follow-ups back on. They still count from the day the proposal was "
                     "sent, so an email that is already due goes out at the next check.")


def test_a_never_enrolled_proposal_still_starts_from_today(fu):
    """A proposal sent before automation existed IS enrolled at the moment it is switched on, so
    for that one "from today" is true and stays."""
    assert _toggle_title(fu["toggleNever"]["html"]) == "Start the follow-up cadence from today"


def test_an_approved_project_says_the_emails_stopped_and_has_no_schedule(fu):
    """Approved is the end of the cadence again: no deposit chase. The old sentence promised
    follow-ups "until the deposit is in"."""
    html = fu["leadApproved"]["html"]
    text = _text(html)
    assert ("Approved, so the automatic follow-up emails have stopped. Nothing chases the deposit."
            in text)
    assert "until the deposit is in" not in text
    assert 'id="fu-sched"' not in html, (
        "an approved project offers a date for an email that never goes")


# ── the schedule ─────────────────────────────────────────────────────────────
def test_the_schedule_is_the_next_email_date_and_nothing_else(fu):
    html = fu["schedule"]["html"]
    assert _value_of(html, "fu-next") == "2026-10-27"
    assert ">Next email on<" in html
    for gone in ("fu-every", "fu-stop"):
        assert 'id="%s"' % gone not in html, gone
    text = _text(html)
    assert "Then every" not in text and "Stop after" not in text
    assert 'id="fu-toggle"' in html, "the per-project Follow-ups switch went with them"
    assert 'id="fu-task"' not in html, "a task card without a task"


def test_the_schedule_says_who_sends_what(fu):
    sched = _text(fu["schedule"]["html"])
    assert "The tool emails the customer automatically" in sched
    assert "it stops when they approve" in sched


def test_the_schedule_saves_the_date_on_change_and_never_per_keystroke(fu):
    s = fu["schedule"]
    assert s["typed"]["bodies"] == [], "a keystroke saved"
    assert s["next"]["bodies"] == [{"next_at": "2026-11-02"}]
    assert s["next"]["paths"] == ["/api/portal/proposal/futask/followup-plan"]
    assert s["next"]["msg"] == "Saved."
    assert s["planAfter"]["next_at"] == "2026-11-02", "the board row did not take the saved plan"
    assert s["cleared"]["bodies"] == [{"next_at": None}]
    assert s["cleared"]["msg"] == "Back on the usual schedule."
    assert s["repaintedBySave"] is False, "a save repainted the drawer and took the caret with it"


def test_the_schedule_refuses_bad_dates_before_a_round_trip(fu):
    s = fu["schedule"]
    for k in ("pastNext", "junk"):
        assert s[k]["bodies"] == [] and s[k]["err"] is True, k
    assert s["refused"]["err"] is True
    assert s["refused"]["msg"] == "Not saved: That date is too far out."


def test_a_closed_lost_proposal_has_no_schedule(out):
    assert 'id="fu-sched"' not in out["scenarios"]["bare"]["html"]
    assert 'id="fu-sched"' in out["scenarios"]["sent"]["html"]
    for name in ("approved", "sent"):
        assert 'id="fu-task"' not in out["scenarios"][name]["html"], name


def test_every_class_the_schedule_emits_is_styled(fu):
    css = (FRONTEND / "portal.html").read_text(encoding="utf-8")
    css = css[css.index("<style>"):css.index("</style>")]
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    auth = re.sub(r"/\*.*?\*/", "", (FRONTEND / "auth.js").read_text(encoding="utf-8"), flags=re.S)
    defined = set(re.findall(r"\.(-?[_a-zA-Z][\w-]*)", css + auth))
    html = fu["schedule"]["html"] + fu["decision"]["html"]
    emitted = {c for g in re.findall(r'class="([^"]*)"', html) for c in g.split() if c}
    assert not sorted(emitted - defined), sorted(emitted - defined)


# ── the assigned estimator is NOT the "Tell the team" list ───────────────────
def test_no_follow_up_action_touches_the_notification_lists(fu):
    """Every request every schedule save made, executed."""
    paths = fu["allPaths"]
    assert any("/followup-plan" in p for p in paths)
    assert not [p for p in paths if "notify" in p], paths


def test_the_follow_up_code_and_the_notification_code_share_nothing():
    """Two lists, two meanings. The "Tell the estimator" email goes to the ASSIGNED ESTIMATOR (one person,
    the "Assigned to" picker, posted to /assign). The notification chips in this drawer and the
    "Tell the team" chips on the Files page decide who hears about replies, approvals and a send.
    Neither side of this file may read the other's list."""
    fu_fns = ("followupScheduleHtml", "saveFuPlan")
    for fn in fu_fns:
        body = _block(fn)
        for word in ("notify", "nt-chip", "NT_CACHE", "notify_picks", "Tell the team"):
            assert word not in body, "%s() reaches into the notification list (%s)" % (fn, word)
    for fn in ("loadNotifyChips", "paintNtChips"):
        body = _block(fn)
        assert "followup" not in body.lower(), "%s() reaches into the follow-up schedule" % fn
    # The estimator email's recipient is changed by the Assigned to picker, and only there.
    wire = _block("wireFollowup")
    assert 'path("/assign")' in wire and "notify" not in wire
    # And the schedule tells the estimator who that is.
    sched = _block("followupScheduleHtml")
    assert "assigned estimator" in sched and "Assigned to" in sched


def test_the_backend_follow_up_routes_do_not_read_the_notification_roster():
    src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    start = src.index("# ── follow-up TASKS")
    end = src.index('@app.get("/api/admin/health")')
    block = src[start:end]
    assert "notify" not in block.lower().replace("tell the team", ""), (
        "a follow-up task route reads the notification roster")


def test_the_files_page_keeps_the_estimator_and_the_team_list_apart():
    """On the send page the assigned estimator is its own select and the Tell the team chips are
    their own strip; the estimator is read from the select alone."""
    html = (FRONTEND / "done.html").read_text(encoding="utf-8")
    assert 'id="portal-estimator"' in html and 'id="notify-pick-chips"' in html
    done = (FRONTEND / "js" / "done.js").read_text(encoding="utf-8")
    m = re.search(r"const readAssignedEstimator = \(\) =>\s*\n?\s*(.*?);", done, re.S)
    assert m and "portal-estimator" in m.group(1) and "notify" not in m.group(1)
