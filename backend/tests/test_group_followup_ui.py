"""The follow-up tab for a project of several scopes: the decision after one scope is approved.

The portal (2026-10-24, Hanz's decisions 2, 6-9) chases a project of several separately-priced
scopes as ONE project. Its follow-up task lists every scope it covers and shows on every scope's
drawer; when one scope is approved, the chase on the others stops and a "Decide the other scopes"
task asks a person to close them as lost, leave them, or keep chasing them. Nothing is ever closed
without a tick, a reason and a note.

EXECUTED, not read: backend/tests/js/group-followup-harness.js runs the real followupTaskHtml,
followupDecisionHtml, wireFuDecision, fuDecide and fuSettle out of portal.js with only the network,
the dialog and the repaint stubbed. Since 2026-10-28 the worker emails the customer itself, so the
decision is the only follow-up task the drawer draws. The bell half is notifications.py, called directly.
"""
import json
import pathlib
import re
import shutil
import subprocess
from datetime import datetime, timezone

import pytest

import main
import notifications as n

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
JS = pathlib.Path(__file__).resolve().parent / "js"
HARNESS = JS / "group-followup-harness.js"


@pytest.fixture(scope="module")
def out():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)], capture_output=True, text=True,
                          encoding="utf-8", timeout=120)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    assert not data["errors"], data["errors"]
    return data


@pytest.fixture(scope="module")
def dec(out):
    return out["decision"]


def _text(html: str) -> str:
    s = re.sub(r"<[^<>]*>", " ", html)
    for ent, ch in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'"), ("&amp;", "&")):
        s = s.replace(ent, ch)
    return re.sub(r"\s+", " ", s).strip()


# ── a cadence reminder is not a task any more ───────────────────────────────────
@pytest.mark.parametrize("shape", ["summary", "sending", "deposit", "view", "group", "none"])
def test_a_cadence_reminder_task_draws_no_card(out, shape):
    """Hanz, 2026-10-28: "the follow ups should be a follow up email to the customer okay?" The
    portal's worker emails the customer itself again, so a reminder task row left over from the
    remind-only weeks (any shape the pipeline serves: the compact summary, a send in flight, the
    deposit stage, the full view with null group keys, a scope group's project reminder) draws
    NOTHING: a Send button beside an email the worker sends on its own would be a double email.

    Mutation: let followupTaskHtml fall through to a card for a non-decision task and every shape
    here fails."""
    assert out["reminders"][shape] == "", out["reminders"][shape][:300]


# ── the decision card ─────────────────────────────────────────────────────────
def test_the_decision_card_names_the_approved_scope_and_lists_the_others(dec):
    text = _text(dec["html"])
    assert text.startswith("Decide the other scopes Breakroom was approved - it is now the project.")
    assert ("Follow-up emails about the other scopes of Acme Labs have stopped, and nothing has been "
            "closed." in text)
    assert dec["boxes"] == [{"id": "s2", "disabled": False}, {"id": "s3", "disabled": False},
                            {"id": "s4", "disabled": True}], "a scope approved since is tickable"
    assert " checked" not in dec["html"], "a scope is ticked before anybody ticked it"
    assert re.search(r'id="fu-dec-close" disabled', dec["html"]), "close starts enabled"


def test_a_decision_task_offers_no_email_and_fetches_no_draft(dec):
    """The portal answers 409 decision_task to send, skip, called and snooze."""
    for el_id in ("fu-task", "fu-compose", "fu-send", "fu-skip", "fu-called", "fu-snooze"):
        assert 'id="%s"' % el_id not in dec["html"], el_id
    assert dec["draftRequests"] == []


def test_the_reasons_are_the_apps_own_close_out_answers_that_close(dec):
    """Kyle's list, from crm-core's CLOSE_CHOICES: the six that close plus `other`, in his order.
    The two hold answers do not close anything and the portal refuses them here."""
    offered = [r for r in dec["reasons"] if r]
    assert dec["reasons"][0] == "", "a reason is pre-selected"
    assert offered == ["not_low_bid", "no_response", "to_rebid", "different_gc", "gc_schedule",
                       "canceled", "other"]
    assert set(offered) <= set(main.LOST_REASONS)
    assert not set(offered) & set(main.HOLD_REASONS)


def test_close_is_enabled_only_with_a_tick_a_reason_and_a_note(dec):
    assert dec["steps"] == {"start": True, "ticked": True, "reason": True, "blankNote": True,
                            "all": False, "unticked": True, "onlyApprovedTicked": True,
                            "noReason": True}


def test_a_stale_enable_still_refuses_on_the_page(dec):
    got = dec["pressedNotReady"]
    assert got["requests"] == [] and got["asked"] == 0
    assert got["alert"] == {"text": "Pick why they were lost first.", "err": True}


def test_close_asks_through_the_apps_dialog_and_a_no_sends_nothing(dec):
    got = dec["closeDeclined"]
    assert got["requests"] == []
    assert len(got["asked"]) == 1
    asked = got["asked"][0]
    assert asked["name"] == "Lab 1" and asked["title"] == "Close these scopes as lost?"


def test_close_sends_exactly_the_ticked_scopes_the_reason_and_the_note(dec):
    got = dec["close"]
    assert got["requests"] == [{
        "path": "/api/portal/followup-task/d-1/scope-decision", "method": "POST",
        "body": {"action": "close", "scope_ids": ["s2", "s3"], "reason": "not_low_bid",
                 "note": "They went with the lab floors only"}}]
    assert got["asked"][0]["name"] == "Lab 1, Lab 2"
    # The portal skipped one (approved since): said, as a warning, and the card goes.
    assert got["notice"]["text"] == ("Closed as lost: Lab 1. Left open, because they were approved "
                                     "or closed since: Lab 2.")
    assert got["notice"]["warn"] is True
    assert got["rowTask"] is None and got["reloaded"] == 1


@pytest.mark.parametrize("action,said", [
    ("leave", "Left as they are. Their follow-up emails stay off."),
    ("keep", "Follow-up emails start again for every scope that is still open."),
])
def test_leave_and_keep_close_nothing_and_ask_nothing(dec, action, said):
    got = dec[action]
    assert got["requests"] == [{"path": "/api/portal/followup-task/d-1/scope-decision",
                                "method": "POST", "body": {"action": action, "scope_ids": []}}]
    assert got["asked"] == 0
    assert got["notice"]["text"].startswith(said)
    assert got["rowTask"] is None


def test_keep_says_when_the_portal_could_not_record_it(dec):
    assert dec["keep"]["notice"]["warn"] is True
    assert "could not record it" in dec["keep"]["notice"]["text"]


def test_keep_explains_itself_in_one_plain_sentence(dec):
    """"One interval from now" went with the interval (2026-10-28): nothing repeats any more."""
    assert "Follow-up emails start again for every scope that is still open." in _text(dec["html"])
    assert "interval" not in _text(dec["html"])


@pytest.mark.parametrize("name,said", [
    ("scopeNotOpen", "Nothing was closed: Lab 2 is no longer open (approved or closed since). "
                     "Untick it and try again."),
    ("scopesNotOpen", "Nothing was closed: Lab 1, Lab 2 are no longer open (approved or closed "
                      "since). Untick them and try again."),
    ("invalidReason", "Nothing was closed: pick why they were lost."),
    ("noteRequired", "Nothing was closed: write a note saying why."),
    ("noScopes", "Nothing was closed: tick at least one scope."),
    ("unknownScope", "Nothing was closed: a ticked scope is no longer part of this decision. "
                     "Reload the page and try again."),
    ("portalDown", "The portal could not be reached, so nothing changed. Try again."),
])
def test_a_refusal_is_a_plain_sentence_and_the_card_stays(dec, name, said):
    got = dec["refusals"][name]
    assert got["alert"] == {"text": said, "err": True}
    assert got["stillThere"] and got["buttonBack"] and got["reloaded"] == 0


def test_an_answer_somebody_else_gave_takes_the_card_away(dec):
    got = dec["alreadyDecided"]
    assert got["rowTask"] is None
    assert got["notice"]["text"] == "Somebody already answered this, so nothing changed."


def test_no_network_keeps_the_card(dec):
    assert dec["offline"] == {"alert": {"text": "Could not reach the server, so nothing changed. "
                                                 "Try again.", "err": True}, "stillThere": True}


def test_every_id_the_decision_wiring_reaches_for_was_rendered(dec):
    missing = [l["id"] for l in dec["lookups"] if not l["present"]]
    assert dec["lookups"] and not missing, missing


def test_every_class_the_decision_card_emits_is_styled(out, dec):
    css = (FRONTEND / "portal.html").read_text(encoding="utf-8")
    css = css[css.index("<style>"):css.index("</style>")]
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    auth = re.sub(r"/\*.*?\*/", "", (FRONTEND / "auth.js").read_text(encoding="utf-8"), flags=re.S)
    defined = set(re.findall(r"\.(-?[_a-zA-Z][\w-]*)", css + auth))
    emitted = {c for g in re.findall(r'class="([^"]*)"', dec["html"])
               for c in g.split() if c}
    assert not sorted(emitted - defined), sorted(emitted - defined)


# ── the Follow-ups page's words ────────────────────────────────────────────────
def test_the_follow_ups_page_names_what_the_group_surface_writes(out):
    assert out["sentLog"] == {"staff_followup_due": "Told the team: a follow-up is due",
                              "staff_scope_decision": "Told the team: decide the other scopes",
                              "scope_decision": "Decide the other scopes",
                              "resume": "Kept chasing the other scopes"}


# ── the bell ──────────────────────────────────────────────────────────────────
NOW = datetime(2026, 10, 25, 15, 0, tzinfo=timezone.utc)
GROUP_TASK = {"id": "g1", "proposal_id": "home", "link_proposal_id": "s2",
              "project_name": "Acme Labs", "label": "Check-in", "stage": "pre",
              "due_at": "2026-10-25T12:00:00Z", "scope_group": "grp-1",
              "scopes": [{"proposal_id": "home", "label": "Breakroom", "status": "sent"},
                         {"proposal_id": "s2", "label": "Lab 1", "status": "viewed"},
                         {"proposal_id": "s3", "label": "Lab 2", "status": "sent"}]}
# The portal's link_proposal_id for a decision task is FRESH (round 3): the first listed sibling
# that is still open, here Lab 1.
DECISION_TASK = {"id": "d1", "proposal_id": "s1", "link_proposal_id": "s2",
                 "project_name": "Acme Labs", "label": "Decide the other scopes",
                 "stage": "decision", "due_at": "2026-10-25T12:00:00Z", "scope_group": "grp-1",
                 "approved_scope": {"proposal_id": "s1", "label": "Breakroom"},
                 "scopes": [{"proposal_id": "s2", "label": "Lab 1", "status": "sent"}]}


def _bell(monkeypatch, *tasks):
    monkeypatch.setattr(n, "_now", lambda: NOW)
    return {r["id"]: r for r in n._followup_task_notifications({"followup_tasks": list(tasks)})}


@pytest.mark.parametrize("task", [
    GROUP_TASK,
    {"id": "t1", "proposal_id": "p1", "project_name": "Nearman Creek", "label": "Second nudge",
     "due_at": "2026-10-23T12:00:00Z"},
    {"id": "t2", "proposal_id": "p1", "project_name": "Nearman Creek", "label": "Deposit reminder",
     "stage": "deposit", "due_at": "2026-10-23T12:00:00Z", "scope_group": None, "scopes": []},
], ids=["group-reminder", "ordinary", "deposit"])
def test_a_cadence_reminder_never_rings(monkeypatch, task):
    """2026-10-28: the worker emails the customer itself, so a reminder task left over from remind
    mode is nobody's job. Mutation: drop the stage check in _followup_task_notifications."""
    assert _bell(monkeypatch, task) == {}


def test_the_bell_says_what_a_decision_task_is(monkeypatch):
    row = _bell(monkeypatch, DECISION_TASK)["fut:d1"]
    assert row["body"] == "Decide the other scopes: Acme Labs"
    assert row["link"] == "/portal.html?open=s2&sec=followup"


def test_a_decision_task_opens_a_sibling_not_the_approved_scope_chasing_its_deposit(monkeypatch):
    # The approved scope raised its own deposit task after the decision (a higher id, no
    # scope_group): the portal's row query shows that scope only its newest open task, so its
    # drawer has no decision card. The portal names a still-open sibling for the decision.
    deposit = {"id": "d2", "proposal_id": "s1", "link_proposal_id": "s1",
               "project_name": "Acme Labs", "label": "Deposit reminder", "stage": "deposit",
               "due_at": "2026-10-25T13:00:00Z", "scope_group": None, "scopes": []}
    rows = _bell(monkeypatch, dict(DECISION_TASK, scopes=[
        {"proposal_id": "s2", "label": "Lab 1", "status": "sent"},
        {"proposal_id": "s3", "label": "Lab 2", "status": "viewed"}]), deposit)
    assert rows["fut:d1"]["link"] == "/portal.html?open=s2&sec=followup"
    assert "fut:d2" not in rows, "a deposit reminder task rang the bell"


def test_a_decision_task_opens_the_sibling_the_portal_names_now(monkeypatch):
    """Round 3: Lab 1 was closed lost after the decision task was raised, so its detail.scopes still
    lists it first. The portal's FRESH link_proposal_id names Lab 2, the first sibling still open,
    and the bell opens that one rather than the closed scope listed first."""
    row = _bell(monkeypatch, dict(DECISION_TASK, link_proposal_id="s3", scopes=[
        {"proposal_id": "s2", "label": "Lab 1", "status": "sent"},
        {"proposal_id": "s3", "label": "Lab 2", "status": "viewed"}]))["fut:d1"]
    assert row["link"] == "/portal.html?open=s3&sec=followup"


def test_a_decision_task_with_no_open_sibling_opens_the_approved_scope_the_portal_names(monkeypatch):
    """Every listed sibling is closed: the portal falls back on the approved scope, and so does the
    bell, instead of opening a closed scope."""
    row = _bell(monkeypatch, dict(DECISION_TASK, link_proposal_id="s1"))["fut:d1"]
    assert row["link"] == "/portal.html?open=s1&sec=followup"


def test_an_older_portal_without_the_link_opens_the_first_listed_sibling(monkeypatch):
    task = {k: v for k, v in DECISION_TASK.items() if k != "link_proposal_id"}
    row = _bell(monkeypatch, dict(task, scopes=[
        {"proposal_id": "s1", "label": "Breakroom", "status": "approved"},
        {"proposal_id": "s2", "label": "Lab 1", "status": "sent"},
        {"proposal_id": "s3", "label": "Lab 2", "status": "viewed"}]))["fut:d1"]
    assert row["link"] == "/portal.html?open=s2&sec=followup"
    row = _bell(monkeypatch, dict(task, scopes=[]))["fut:d1"]
    assert row["link"] == "/portal.html?open=s1&sec=followup"


def test_a_decision_task_with_no_sibling_listed_keeps_the_portals_link(monkeypatch):
    row = _bell(monkeypatch, dict(DECISION_TASK, link_proposal_id="s1", scopes=[]))["fut:d1"]
    assert row["link"] == "/portal.html?open=s1&sec=followup"


def test_a_link_id_never_escapes_its_query_value(monkeypatch):
    row = _bell(monkeypatch, dict(DECISION_TASK, link_proposal_id="s2&sec=x#y"))["fut:d1"]
    assert row["link"] == "/portal.html?open=s2%26sec%3Dx%23y&sec=followup"
