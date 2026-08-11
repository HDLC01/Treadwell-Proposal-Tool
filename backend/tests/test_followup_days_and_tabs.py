"""Auto Followups: timing in days, and each tab saying which email you are editing.

Hanz, 2026-08-12:

    "Then for the Cadence & Emails which was renamed / Change the timing to Days instead of Hours
     then each category in the emails should have different language or terms. For example if its
     in the Not opened yet category the Label would be 'First Reminder after not Opening' / Just to
     clearly show what category we are in."

DAYS ON SCREEN, HOURS IN THE DATABASE — and that is the whole design decision here.

Hours is what the WORKER reads: followup_rules compares against `*_hours`, the floors and ceilings
in followup_settings.BOUNDS are in hours, and every settings row ever written stores hours.
Changing the stored unit would mean touching the rules engine, the bounds, the digest, and
migrating live data — to change a word on a form. So the conversion lives in the editor and
nowhere else, and this file pins that it is a round trip rather than a one-way lossy change.

Rounded rather than floored, because a stored 36 hours from before this change reads as 2 days,
which is the nearer truth. Floored at 1 day, because 0 would mean "chase instantly, for ever".

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


# ── days on screen ───────────────────────────────────────────────────────────
def test_the_form_says_days_and_not_hours():
    page = HTML.read_text(encoding="utf-8")
    assert "<span>hours</span>" not in page, "a timing field still reads hours"
    assert page.count("<span>days</span>") == 4, (
        "expected exactly the four durations in days; the fifth field is a COUNT of reminders "
        "and was always unitless")
    assert "Days between reminders" in page, "the card's own sentence still says hours"
    assert "<span>reminders</span>" in page, "Stop after N lost its unit"


def test_no_hour_figure_survives_anywhere_on_the_page():
    """One hint read "72 is the 'every 3 days' on the flow chart" — true in hours and nonsense
    beside a field showing 3. It was rewritten to say 3, and then Hanz deleted all five hints
    on 2026-08-12, so what is left to assert is that no stale hour figure lingers."""
    page = HTML.read_text(encoding="utf-8")
    for stale in ("72 is the", "72 hours", "48 hours", "24 hours"):
        assert stale not in page, "a leftover hour figure is still on screen: %r" % stale


def test_the_four_durations_are_converted_on_the_way_in_and_out():
    fill, collect = _block("fillNumbers"), _block("collect")
    for field in ("first", "second", "recurring", "staff"):
        assert 'toDays(CFG.%s' % ("first_nudge_hours" if field == "first" else
                                  "second_nudge_hours" if field == "second" else
                                  "recurring_hours" if field == "recurring" else
                                  "staff_personal_hours") in fill, (
            "the %s field is filled without converting to days" % field)
        assert 'toHours($("%s").value)' % field in collect, (
            "the %s field is saved without converting back to hours" % field)


def test_the_reminder_COUNT_is_not_converted():
    """max_recurring is "stop after N reminders" — a count, not a duration. Multiplying it by 24
    would turn 20 reminders into 480 and the cadence would nag for a year."""
    fill, collect = _block("fillNumbers"), _block("collect")
    assert 'CFG.max_recurring' in fill and "toDays(CFG.max_recurring" not in fill
    assert 'max_recurring: $("maxrec").value' in collect, (
        "the reminder count is being converted as though it were a duration")


@pytest.mark.parametrize("hours,days", [
    (24, 1), (48, 2), (72, 3), (720, 30),
    (36, 2),    # a pre-existing odd value rounds to the NEARER day, not down to 1
    (12, 1),    # under a day still means "chase after a day", never 0
    (0, 1),     # 0 days would be "chase instantly, for ever"
])
def test_the_conversion_is_a_round_trip(hours, days):
    """Run for real rather than asserted from the source: the arithmetic is the whole risk here,
    and a stored cadence that drifts every time somebody opens the page would be silent."""
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    src = _js()
    to_days = src[src.index("function toDays"):src.index("\n", src.index("function toHours"))]
    out = subprocess.run(
        ["node", "-e", to_days + "\nconsole.log(JSON.stringify([toDays(%d), toHours(toDays(%d))]));"
         % (hours, hours)],
        capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr
    import json
    got_days, back = json.loads(out.stdout)
    assert got_days == days, "%dh should read as %d days, got %d" % (hours, days, got_days)
    assert back == days * 24, "saving %d days did not store %dh" % (days, days * 24)


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
    for key in ("not_viewed", "next_steps", "second_nudge", "checkin"):
        assert key in code[code.index("var EDITOR_TITLES"):code.index("var EDITOR_TITLES") + 600]


def test_the_fallback_wording_names_when_the_email_fires():
    """Hanz's example was "First Reminder after not Opening" — the point is to say WHEN, not to
    repeat the tab."""
    code = _code()
    block = code[code.index("var EDITOR_TITLES"):code.index("};", code.index("var EDITOR_TITLES"))]
    assert "First reminder" in block and "after not opening" in block
    assert "Recurring check-in" in block and "repeats until" in block


def test_the_heading_falls_back_to_the_tab_label_rather_than_to_nothing():
    body = _block("paintTabs")
    assert "LABELS[KEY]" in body, (
        "an unknown key would leave the heading empty instead of showing the tab's own name")
