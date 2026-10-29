"""The Auto Followups page as Hanz approved it on 2026-10-28: two emails per step, nothing repeats.

What triggered it: Will typed 0 into "Then every", "Tell the estimator after" and "Stop after" on
prod, and the portal silently clamped and defaulted the zeros (prod saved daily check-ins, up to 20).
The rules that came out of it, and what this file proves about the PAGE half of them:

  * a follow-up is an automatic email to the customer, from "sent" until "approved";
  * two steps (not opened yet; opened, no decision), each with a 1st and a 2nd email, each with its
    own switch and days; an estimator email N days after the last one, with its own switch;
  * no "Then every", no "Stop after", no recurring check-in, no deposit reminder;
  * 0 is never "off": a day out of 1..90 is REFUSED by the portal with a sentence and a `field`,
    the page shows that sentence under the box it is about, and never replaces what was typed;
  * after a save the page shows what was SAVED.

EXECUTED through backend/tests/js/followup-settings-harness.js, which runs the whole of
frontend/js/followup-settings.js against the ids followup-settings.html really has. Each test names
the mutation that makes it fail.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

import main

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "followup-settings-harness.js"
HTML = (FRONTEND / "followup-settings.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)], capture_output=True, text=True,
                          encoding="utf-8", timeout=120)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    assert not data["errors"], data["errors"]
    return data


def _visible(html: str) -> str:
    body = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    body = body[body.index("<body"):]
    body = re.sub(r"<script\b.*?</script\b[^>]*>", "", body, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))


# ── the page, as the approved mock ──────────────────────────────────────────────
def test_the_card_reads_as_the_approved_mock():
    text = _visible(HTML)
    assert "Auto follow-ups" in text
    assert "Sent → Approved. Stops when approved, lost, or the project's Follow-ups switch is off." in text
    for legend in ("Not opened yet", "Opened, no decision", "Estimator"):
        assert ">%s</legend>" % legend in HTML, legend
    for unit in ("days after sending", "days after the 1st", "days after the last email"):
        assert unit in text, unit
    assert text.count("days after the 1st") == 2, "each step has its own 2nd email"
    # Hanz, 2026-10-29: "the days should be based off the date it was sent", for both steps.
    assert text.count("days after sending") == 2, "each step's 1st email counts from sending"
    assert "days after they open it" not in text
    assert "Tell the estimator" in text


def test_the_intro_says_both_steps_count_from_the_day_it_was_sent():
    """Hanz, 2026-10-29: "the days should be based off the date it was sent". The opened step used
    to count from the day they opened it; it counts from the send now, like the first step.

    Mutation: put back the old intro (no sent date) and this fails."""
    text = _visible(HTML)
    assert ("Both steps count from the day the proposal was sent: a 1st email goes out that many "
            "days after the send, never sooner than that after the email before it, and a 2nd "
            "email that many days after its 1st.") in text


def test_the_opened_email_heading_says_it_counts_from_sending(ran):
    """The page's own heading over each email (its fallback, when the portal serves none), read off
    the page after the real tab click. Mutation: put back "days after they open it" and this fails."""
    h = ran["headings"]
    assert h["next_steps"] == "Opened, no decision — 1st email, days after sending"
    assert h["not_viewed"] == "Not opened yet — 1st email, days after sending"
    assert h["second_nudge"] == "Opened, no decision — 2nd email, days after the 1st"
    assert not [k for k, v in h.items() if "open it" in v], h


def test_nothing_repeats_any_more():
    """Mutation: put any of the old fields back and this fails."""
    text = _visible(HTML)
    for gone in ("Then every", "Stop after", "Recurring check-in", "Deposit reminder"):
        assert gone not in text, gone
    for gone_id in ('id="recurring"', 'id="maxrec"', 'id="first"', 'id="second"', 'id="staff"'):
        assert gone_id not in HTML, gone_id


def test_every_email_has_a_switch_and_a_days_box():
    for rid in ("no1", "no2", "op1", "op2", "est"):
        assert re.search(r'type="checkbox" role="switch" id="%s-on"' % rid, HTML), rid
        assert re.search(r'id="%s-days" class="num" type="number" min="1" max="90"' % rid, HTML), rid
        assert 'id="%s-err"' % rid in HTML and 'id="%s-row"' % rid in HTML, rid


# ── what a load shows ───────────────────────────────────────────────────────────
def test_a_load_shows_every_switch_and_number_as_stored(ran):
    """Mutation: fill a box from a default instead of the stored rule (or read `on` as true when
    it is false) and a box disagrees with what the portal holds."""
    b = ran["loaded"]["boxes"]
    assert {k: (v["on"], v["days"]) for k, v in b.items()} == {
        "no1": (True, "3"), "no2": (True, "7"), "op1": (True, "3"), "op2": (False, "7"),
        "est": (True, "1")}
    assert b["op2"]["off"] is True and b["op1"]["off"] is False, "an off email does not read as off"
    assert ran["loaded"]["saveDisabled"] is False


def test_the_check_in_and_deposit_tabs_are_gone_even_when_an_older_portal_serves_them(ran):
    """Mutation: drop the RETIRED filter and the two tabs come back."""
    assert ran["loaded"]["tabs"] == ["sent", "not_viewed", "next_steps", "second_nudge"]


def test_an_old_portal_is_shown_as_the_migration_maps_it_and_cannot_be_saved(ran):
    """A portal still on the flat hours (prod's row: 72/168/2160/1/24). The page would otherwise
    PUT the new shape to a validate() that refills every old field from its defaults.

    Mutation: drop the oldPortal lock and Save is live."""
    o = ran["oldPortal"]
    assert {k: (v["on"], v["days"]) for k, v in o["boxes"].items()} == {
        "no1": (True, "3"), "no2": (True, "7"), "op1": (True, "3"), "op2": (True, "7"),
        "est": (True, "1")}
    assert o["saveDisabled"] is True and o["resetDisabled"] is True
    assert "has not been updated for the new follow-ups" in o["alert"]


# ── a refusal ───────────────────────────────────────────────────────────────────
def test_zero_is_sent_as_zero_and_the_portal_s_sentence_lands_under_its_box(ran):
    """THE BUG THAT STARTED THIS. 0 typed into a box reaches the portal as 0 (never clamped to 1 or
    read as "off"), and the portal's refusal is shown under the 2nd email of NOT OPENED YET, with
    the step named in the alert because the sentence is true of both steps.

    Mutations: clamp in daysTyped (the PUT carries 1); drop ruleForField (no row is marked)."""
    r = ran["refused"]
    sent = r["puts"][0]["settings"]
    assert sent["steps"]["not_opened"]["second"] == {"on": True, "days": 0}
    no2 = r["boxes"]["no2"]
    assert no2["err"] == "2nd email must be 1 to 90 days after the 1st"
    assert no2["invalid"] == "true"
    assert no2["days"] == "0", "the refused value was replaced instead of left to fix"
    others = [k for k, v in r["boxes"].items() if k != "no2" and (v["err"] or v["invalid"])]
    assert others == [], "the refusal marked the wrong row: %s" % others
    assert r["alert"] == "Not saved. Not opened yet: 2nd email must be 1 to 90 days after the 1st."
    assert r["alertOk"] is False


def test_typing_in_the_box_clears_its_refusal(ran):
    assert ran["afterRetype"] == {"on": True, "days": "10", "off": False, "err": None,
                                  "invalid": None}


def test_an_estimator_refusal_lands_under_the_estimator(ran):
    r = ran["estRefused"]
    assert r["puts"][0]["settings"]["estimator"] == {"on": True, "days": 200}
    assert r["boxes"]["est"]["err"] == "Tell the estimator must be 1 to 90 days after the last email"
    assert r["alert"] == ("Not saved. Estimator: Tell the estimator must be 1 to 90 days after the "
                          "last email.")


def test_a_refusal_about_no_row_is_said_and_marks_nothing(ran):
    r = ran["templateRefused"]
    assert r["alert"] == "Not saved. The Not opened yet email needs {link}."
    assert not [k for k, v in r["boxes"].items() if v["err"] or v["invalid"]]


# ── a save ──────────────────────────────────────────────────────────────────────
def test_save_sends_the_two_per_step_shape_and_no_old_field(ran):
    """Mutation: put first_nudge_hours / recurring_hours / max_recurring back in collect()."""
    s = ran["saved"]["puts"][0]["settings"]
    assert s["steps"] == {"not_opened": {"first": {"on": True, "days": 3},
                                         "second": {"on": True, "days": 10}},
                          "opened": {"first": {"on": False, "days": 3},
                                     "second": {"on": False, "days": 7}}}
    assert s["estimator"] == {"on": True, "days": 1}
    for old in ("first_nudge_hours", "second_nudge_hours", "recurring_hours", "max_recurring",
                "staff_personal_hours", "deposit_hours", "deposit_max"):
        assert old not in s, old
    # Round-tripped untouched, for the reasons in collect(): an absent key resets them.
    assert (s["send_start_hour"], s["send_end_hour"]) == (9, 17)
    assert s["thread_subject"] == "Your Treadwell proposal — {project}"
    assert "checkin" in s["templates"], "a retired template's wording was dropped on save"


def test_a_switch_turned_off_is_sent_as_off(ran):
    assert ran["switchedOff"]["off"] is True
    assert ran["saved"]["puts"][0]["settings"]["steps"]["opened"]["first"]["on"] is False


def test_after_a_save_the_page_shows_what_was_saved(ran):
    r = ran["saved"]
    assert r["alert"] == "Saved." and r["alertOk"] is True
    assert (r["boxes"]["no2"]["days"], r["boxes"]["op1"]["on"]) == ("10", False)
    assert r["meta"] == "Last changed BIZ(2026-10-29T15:00:00Z) by hanz@wetreadwell.com"


def test_when_the_portal_stored_something_else_the_page_says_so_and_shows_it(ran):
    """Mutation: fill the boxes from what was typed instead of from the answer, or always say
    "Saved." and this fails."""
    r = ran["differs"]
    assert r["boxes"]["est"]["days"] == "2", "the box shows what was typed, not what was stored"
    assert r["alert"].startswith("Saved, but the portal stored different values")


def test_reset_is_asked_first_and_is_an_explicit_flag_beside_an_empty_payload(ran):
    """Mutation: drop `reset: true` from the PUT and this fails. The two-per-step portal fills an
    absent field from what is SAVED, so a bare `{settings: {}}` saves the current cadence again."""
    assert ran["reset"]["asked"] == 1
    assert ran["reset"]["puts"] == [{"settings": {}, "reset": True}]


def test_an_acknowledged_reset_says_so_and_shows_the_defaults_the_portal_answered(ran):
    r = ran["reset"]
    assert r["alert"] == "Reset to the default cadence." and r["alertOk"] is True
    assert (r["boxes"]["no2"]["days"], r["boxes"]["est"]["days"]) == ("5", "2")


def test_a_reset_the_portal_did_not_apply_is_never_called_a_reset(ran):
    """Review finding 2026-10-29: Reset sent an empty payload, the portal refilled it from the
    saved row (not_opened 1st = 20 days, estimator off), stored the same values again, and the page
    still said "Reset to the default cadence." in green. Mutation: say that sentence whenever the
    PUT succeeds, ignoring the portal's `reset` acknowledgement, and this fails."""
    r = ran["resetIgnored"]
    assert r["alert"] != "Reset to the default cadence."
    assert r["alert"].startswith("Not reset.") and r["alertOk"] is False
    # The boxes show what the portal kept, so nobody reads the old values as defaults.
    assert (r["boxes"]["no1"]["days"], r["boxes"]["est"]["on"]) == ("20", False)


# ── the flat spelling ───────────────────────────────────────────────────────────
def test_the_flat_spelling_is_read_and_written_back_in_the_same_spelling(ran):
    """The portal half was built with flat keys (not_opened_first_on, ..._days, estimator_on/_days)
    rather than the nested {steps, estimator}. The page reads either and answers in the spelling it
    was sent. Mutation: always write the nested shape, and a flat portal ignores every number."""
    f = ran["flat"]
    assert {k: (v["on"], v["days"]) for k, v in f["loaded"].items()} == {
        "no1": (True, "3"), "no2": (False, "7"), "op1": (True, "4"), "op2": (True, "8"),
        "est": (True, "2")}
    assert f["saveDisabled"] is False
    sent = f["refused"]["puts"][0]["settings"]
    assert "steps" not in sent and "estimator" not in sent
    assert {k: sent[k] for k in sent if k.endswith(("_on", "_days"))} == {
        "not_opened_first_on": True, "not_opened_first_days": 3,
        "not_opened_second_on": False, "not_opened_second_days": 7,
        "opened_first_on": True, "opened_first_days": 4,
        "opened_second_on": True, "opened_second_days": 0,
        "estimator_on": True, "estimator_days": 2}


def test_a_refusal_with_only_a_sentence_still_lands_under_its_box(ran):
    """That portal's 400 carries the sentence and no `field`; the sentence names the step and the
    email, so the page reads the row off it. Mutation: drop ruleForSentence."""
    r = ran["flat"]["refused"]
    assert r["boxes"]["op2"]["err"] == ("Opened, no decision: the 2nd email must be 1 to 90 days "
                                        "after the 1st.")
    assert r["boxes"]["op2"]["days"] == "0"
    assert not [k for k, v in r["boxes"].items() if k != "op2" and v["err"]]
    assert r["alert"] == ("Not saved. Opened, no decision: the 2nd email must be 1 to 90 days after "
                          "the 1st."), "the step was named twice, or not at all"
    assert ran["flat"]["saved"]["alert"] == "Saved."
    assert ran["flat"]["saved"]["boxes"]["op2"]["days"] == "9"


# ── the proxy keeps the refusal's field ─────────────────────────────────────────
def test_the_settings_put_passes_the_portal_s_refusal_through_with_its_field(monkeypatch):
    """`_portal` raised a 400 as a bare {"detail": sentence}, which loses `field`, so the page
    could not say WHICH box. Mutation: return the PUT through `_portal` again."""
    calls = []

    def fake_call(path, method="GET", body=None):
        calls.append((path, method, body))
        return 400, {"ok": False, "error": "2nd email must be 1 to 90 days after the 1st",
                     "field": "steps.opened.second.days"}

    monkeypatch.setattr(main, "_portal_call", fake_call)
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: {"email": e, "role": "admin"})
    client = TestClient(main.app)
    r = client.put("/api/followup-settings", json={"settings": {"steps": {}}})
    assert r.status_code == 400
    j = r.json()
    assert j["field"] == "steps.opened.second.days"
    assert j["error"] == j["detail"] == "2nd email must be 1 to 90 days after the 1st"
    assert j["ok"] is False
    assert calls[0][0:2] == ("/api/admin/settings/followups", "PUT")
    assert calls[0][2]["by"], "the server no longer stamps who changed it"


def test_the_settings_put_forwards_the_reset_flag_and_hands_back_the_acknowledgement(monkeypatch):
    """The reset contract rides the proxy both ways: `reset: true` reaches the portal, and the
    portal's `reset: true` reaches the page, which only says "Reset" when it sees it. Mutation:
    rebuild the payload from `settings` alone in the proxy, or drop `reset` from its answer."""
    calls = []

    def fake_call(path, method="GET", body=None):
        calls.append((path, method, body))
        return 200, {"ok": True, "reset": True, "settings": {"steps": {}}, "saved": True}

    monkeypatch.setattr(main, "_portal_call", fake_call)
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: {"email": e, "role": "admin"})
    client = TestClient(main.app)
    r = client.put("/api/followup-settings", json={"settings": {}, "reset": True})
    assert r.status_code == 200 and r.json()["reset"] is True
    assert calls[0][2]["reset"] is True and calls[0][2]["settings"] == {}
