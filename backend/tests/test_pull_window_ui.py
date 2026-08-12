"""The pull-window control on Analytics, and the notice it puts on the Bid Calendar.

Executed, not grepped. Every claim here is about what a person sees or what request leaves the
browser — whether the caption describes the dataset or a half-typed edit, whether Save sends
from/to the right way round, whether the calendar prefers "this is a saved copy" over "the range is
bounded". Source text answers none of those, and on 2026-08-12 an unbound identifier took the
Active Projects board down on prod with every source assertion green.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "pull-window-ui-harness.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def ui():
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── the control ───────────────────────────────────────────────────────────────
def test_with_no_window_it_says_it_pulls_everything(ui):
    """The default has to be legible, not blank: an empty control reads as "no setting exists"."""
    u = ui["unset"]
    assert u["saysEverything"] is True
    assert u["hasFrom"] and u["hasTo"] and u["hasSave"], u


def test_a_set_window_is_described_with_who_set_it_and_when(ui):
    """One shared setting that everybody reads. "Why is 2019 missing?" has to be answerable from
    the page rather than from asking around."""
    s = ui["set"]
    assert s["describes"] is True
    assert s["inputsCarryIt"] is True
    assert s["saysWho"] and s["saysWhen"], s


def test_the_picker_itself_refuses_a_backwards_range(ui):
    """min/max cross-bound, the same pattern the filter inputs use."""
    assert ui["set"]["crossBounded"] is True


def test_the_caption_describes_the_DATA_not_what_is_being_typed(ui):
    """The whole reason the window is read off the payload. A half-finished edit describing the
    numbers on screen is a caption that lies for as long as somebody hesitates."""
    assert ui["captionIgnoresTyping"] is True


def test_saving_puts_the_window_to_the_server(ui):
    s = ui["save"]
    assert s["path"] == "/api/analytics/pull-window"
    assert s["method"] == "PUT"
    assert s["body"] == {"from": "2024-01-01", "to": "2026-08-01"}, (
        "from/to are swapped or renamed: %s" % s["body"])


def test_emptying_a_box_clears_that_side_rather_than_sending_blank(ui):
    """`""` is not a date. The server would reject it, and the way back to all-time would be a
    500 nobody can explain."""
    assert ui["cleared"] == {"from": None, "to": None}


def test_a_backwards_range_never_reaches_the_server(ui):
    b = ui["backwards"]
    assert b["requests"] == 0, "the browser sent a range it could see was wrong"
    assert b["says"] is True and b["bad"] is True


def test_a_failed_save_is_reported_as_a_failure(ui):
    """Nothing worse here than a control that looks saved: the next person to read the dashboard
    inherits the dates somebody thought they had changed."""
    f = ui["failedSave"]
    assert f["saysFailed"] is True and f["bad"] is True


# ── asking for a slice we do not hold ─────────────────────────────────────────
def test_a_filter_reaching_outside_the_window_says_which_range_is_the_reason(ui):
    """An empty chart has two possible causes — no bids, or no data — and they need different
    actions from the reader."""
    assert ui["warn"]["before"] is True
    assert ui["warn"]["after"] is True


def test_a_filter_inside_the_window_says_nothing(ui):
    assert ui["warn"]["inside"] is False
    assert ui["warn"]["noWindow"] is False


def test_the_filter_dates_are_not_clamped_to_the_window(ui):
    """Silently moving somebody's typed dates is worse than an empty answer with an explanation:
    they would read a total for a range they did not ask for."""
    assert ui["warn"]["keepsTypedDates"] is True


# ── the Bid Calendar ──────────────────────────────────────────────────────────
def test_the_calendar_explains_a_bounded_window(ui):
    """This page shares the analytics payload but the range is set on a different page, so a
    calendar that had quietly lost last spring would be a mystery here."""
    text = ui["calendar"]["windowed"]
    assert "company data range" in text
    assert "2024-01-01" in text and "2025-12-31" in text
    assert "pcoming bids always show" in text, (
        "the notice has to say the thing that stops it reading as broken")
    assert "Analytics" in text, "it must say where to change it"


def test_an_open_window_says_nothing_at_all(ui):
    assert ui["calendar"]["open"] == ""


def test_a_payload_without_the_key_says_nothing(ui):
    """Snapshots written before this feature carry no `pull_window`. The deploy that introduces
    it must not put a notice on every calendar."""
    assert ui["calendar"]["missingKey"] == ""


def test_stale_data_is_the_more_important_thing_to_say(ui):
    """One line, two candidates. "These numbers are a saved copy" changes how you read every row;
    a bounded window only explains a thinner past."""
    assert "last saved copy" in ui["calendar"]["staleWins"]
    assert "company data range" not in ui["calendar"]["staleWins"]
