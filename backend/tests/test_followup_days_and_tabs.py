"""Auto Followups: timing in days, and each tab saying which email you are editing.

Hanz, 2026-08-12:

    "Then for the Cadence & Emails which was renamed / Change the timing to Days instead of Hours
     then each category in the emails should have different language or terms. For example if its
     in the Not opened yet category the Label would be 'First Reminder after not Opening' / Just to
     clearly show what category we are in."

DAYS ON SCREEN AND IN THE PAYLOAD since 2026-10-28. Until then the editor converted days on
screen to the hours the worker stored; the two-per-step settings ({on, days} per email) are stored
in days, so nothing is converted and nothing is floored. 0 is not silently made 1 any more: the
portal refuses it with a sentence (test_followup_two_per_step_page.py).

THE TAB HEADING IS SERVED, NOT HARDCODED. LABELS (short, for the tabs) is already served by the
portal because its validation refusals quote those names verbatim — "the Not opened yet email
needs {link}". The longer when-it-fires wording follows the same rule for the same reason: a
heading above the form that disagreed with the message refusing the save would be worse than no
heading.
"""
import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
JS = FRONTEND / "js" / "followup-settings.js"
HTML = FRONTEND / "followup-settings.html"


def _js() -> str:
    return JS.read_text(encoding="utf-8")


def _code() -> str:
    return "\n".join(l for l in _js().splitlines() if not l.strip().startswith("//"))


def _block(fn: str) -> str:
    code = _code()
    m = re.search(r"\n\s{0,6}function " + re.escape(fn) + r"\s*\(", code)
    assert m, "%s() is gone from followup-settings.js" % fn
    i = code.index("{", m.end())
    depth, j = 0, i
    while j < len(code):
        if code[j] == "{":
            depth += 1
        elif code[j] == "}":
            depth -= 1
            if depth == 0:
                return code[i:j + 1]
        j += 1
    pytest.fail("unbalanced braces reading %s" % fn)


# ── days on screen AND in the payload (2026-10-28) ───────────────────────────────
def test_the_form_says_days_and_not_hours():
    page = HTML.read_text(encoding="utf-8")
    assert "<span>hours</span>" not in page, "a timing field still reads hours"
    assert page.count("<span>days after") == 5, (
        "expected the five durations in days: two emails per step, and the estimator's")
    assert "<span>reminders</span>" not in page, "Stop after N is back"


def test_no_hour_figure_survives_anywhere_on_the_page():
    page = HTML.read_text(encoding="utf-8")
    for stale in ("72 is the", "72 hours", "48 hours", "24 hours"):
        assert stale not in page, "a leftover hour figure is still on screen: %r" % stale


def test_nothing_is_converted_any_more():
    """The two-per-step settings are stored in DAYS ({on, days} per email), so the hour helpers
    went: a page that still multiplied by 24 would send 72 for "3 days", which the portal refuses
    as out of 1..90. Executed in test_followup_two_per_step_page.py (the PUT carries days)."""
    code = _code()
    for gone in ("function toDays", "function toHours", "toHours(", "toDays("):
        assert gone not in code, gone
    # The old flat hours are READ (fromOldShape, for a portal not yet updated) and never written.
    assert "_hours" not in _block("collect") and "_hours" not in _block("scheduleTyped")


def test_the_send_window_is_still_round_tripped():
    """Pre-existing trap, re-asserted because collect() was edited: validate() falls back to the
    DEFAULT for any absent key, so dropping these would silently reset a window somebody set."""
    collect = _block("collect")
    assert "send_start_hour: CFG.send_start_hour" in collect
    assert "send_end_hour: CFG.send_end_hour" in collect


def test_the_project_subject_is_still_round_tripped():
    """Same trap, same reason — added yesterday, and collect() has been edited since."""
    assert 'thread_subject: $("thread-subject").value' in _block("collect")


# ── which email am I editing ──────────────────────────────────────────────────
def test_the_page_says_which_email_is_open():
    page = HTML.read_text(encoding="utf-8")
    assert 'id="which-email"' in page, "there is no heading naming the open email"
    assert page.index('id="tabs"') < page.index('id="which-email"'), (
        "the heading sits above the tabs, so it reads as a title for all of them")


def test_the_heading_is_repainted_on_every_tab_switch():
    """In paintTabs rather than in the click handler: paintTabs runs on load AND on every switch,
    so the heading cannot get out of step with the form under it."""
    body = _block("paintTabs")
    assert '$("which-email")' in body, "the heading is never painted"
    assert "EDITOR_TITLES[KEY]" in body


def test_the_server_owns_the_wording():
    """Same rule as LABELS: the portal's refusal messages quote what an email is called, and a
    heading that disagreed with the message refusing a save would be worse than none."""
    code = _code()
    assert "j.editor_titles" in code, "the served wording is ignored"
    i = code.index("j.editor_titles")
    assert "EDITOR_TITLES[k] = j.editor_titles[k]" in code[i:i + 400]


def test_there_is_a_local_fallback_so_the_heading_is_never_blank():
    """A failed or older GET must still say which email is open."""
    code = _code()
    assert re.search(r"var EDITOR_TITLES = \{", code), "no fallback map"
    for key in ("not_viewed", "next_steps", "second_nudge"):
        assert key in code[code.index("var EDITOR_TITLES"):code.index("var EDITOR_TITLES") + 600]


def test_the_fallback_wording_names_when_the_email_fires():
    """Hanz's example was "First Reminder after not Opening" — the point is to say WHEN, not to
    repeat the tab."""
    code = _code()
    block = code[code.index("var EDITOR_TITLES"):code.index("};", code.index("var EDITOR_TITLES"))]
    assert "Not opened yet — 1st email, days after sending" in block
    assert "Opened, no decision — 1st email, days after sending" in block
    assert "days after they open it" not in block
    assert "Recurring check-in" not in block, "a fallback heading for an email nothing sends"


def test_the_heading_falls_back_to_the_tab_label_rather_than_to_nothing():
    body = _block("paintTabs")
    assert "LABELS[KEY]" in body, (
        "an unknown key would leave the heading empty instead of showing the tab's own name")
