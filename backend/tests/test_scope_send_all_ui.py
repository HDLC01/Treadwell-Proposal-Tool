"""SEND ALL PROPOSALS IN ONE EMAIL, on the two pages that send it (Hanz, 2026-10-27).

The Files page of a grouped proposal and the board drawer press the SAME server action
(POST /api/portal/scope-group/{gid}/send-all, test_scope_send_all.py) and say its answer in the SAME
words: scopeSendOutcome, which moved from portal.js into crm-core.js so both pages load one copy.

EXECUTED, NOT READ: the Files page's real Send handler and mount label run in
files-stale-page-harness.js (scenario O, `sendAll`), the drawer's real wireScope in
drawer-render-harness.js.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

TESTS = pathlib.Path(__file__).resolve().parent
FRONTEND = TESTS.parents[1] / "frontend"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _node(*args):
    proc = subprocess.run(["node", *map(str, args)], capture_output=True, text=True,
                          encoding="utf-8", timeout=180)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def files():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    return _node(TESTS / "js" / "files-stale-page-harness.js")["sendAll"]


@pytest.fixture(scope="module")
def drawer():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    out = _node(TESTS / "js" / "drawer-render-harness.js", FRONTEND)
    assert "honest" not in out["errors"], out["errors"].get("honest")
    return out


# ── the Files page ──────────────────────────────────────────────────────────
@needs_node
def test_a_grouped_proposals_button_is_the_one_press(files):
    """Mutation: drop the mount label in done.js — the grouped button still reads "Send to customer
    portal"."""
    assert files["sent"]["label"] == "Send all proposals in one email"
    assert files["ungroupedLabel"] == "↗ Send to customer portal", "an ungrouped button changed"


@needs_node
def test_the_files_page_posts_once_to_the_send_all_and_never_publishes(files):
    """ONE request, to the send-all, carrying this page's publish body for its own proposal and the
    customer message; the plain publish route is never called (it would publish this proposal only).

    Mutation: post to /api/portal/publish for a grouped proposal as before — `published` is 1 and
    `sendAll` is empty."""
    s = files["sent"]
    assert s["published"] == 0, "the grouped Send published on its own"
    assert len(s["sendAll"]) == 1
    (req,) = s["sendAll"]
    assert req["path"] == "/api/portal/scope-group/G1/send-all" and req["method"] == "POST"
    body = req["body"]
    assert body["draft_id"] == "d1" and body["message"] == "Your three proposals."
    pub = body["publish"]
    assert pub["emails"] == ["customer@example.com"]
    assert pub["assigned_estimator"] == "kyle@wetreadwell.com"
    assert pub["draft_version"] == "2026-10-27T09:00:00+00:00", "the stale-copy guard was dropped"


@needs_node
def test_the_files_page_says_the_answer_in_the_drawers_words(files):
    s = files["sent"]
    assert s["result"] == "Sent to 1 contact, one email with every scope."
    assert s["button"] == "✓ Sent, one email with every proposal" and s["err"] is None
    assert s["disabled"] is True, "the button was usable again while the send was being confirmed"


@needs_node
@pytest.mark.parametrize("case,words", [
    ("blocked", "Nothing was sent. Room 3: build its files on its Files page first."),
    ("nothing", "Nothing was sent: the customer already has every scope of this project in their "
                "email. A new scope or a revision, once published, can be emailed from here."),
    ("halfway", "Nothing was emailed. Room 3 could not be published (Portal error.). Room 2 was "
                "published and will go in the email. Press the button again in a minute to finish."),
])
def test_a_refused_press_says_why_and_gives_the_button_back(files, case, words):
    """Mutation: throw the refusal at the generic handler instead (portalErrMsg) — the estimator
    reads a code or a JSON dump, not the sentence."""
    r = files[case]
    assert r["err"] == words, r
    assert r["button"] == "Send all proposals in one email" and r["disabled"] is False
    assert r["published"] == 0 and len(r["sendAll"]) == 1


# ── the drawer ──────────────────────────────────────────────────────────────
@needs_node
def test_the_drawers_button_presses_the_same_send_all(drawer):
    """Mutation: drop "/send-all" from the drawer's #scope-send wiring — the request goes to /send,
    which only emails what is already published."""
    h = drawer["honest"]
    for k in ("noOne", "partial", "nothing", "sendAllBlocked"):
        assert [r["path"] for r in h[k]["requests"]] == ["/api/portal/scope-group/grp_h/send-all"], k
    # The retry of the missed contacts and the "send them again" stay on the plain send.
    assert [r["path"] for r in h["retry"]["requests"]] == ["/api/portal/scope-group/grp_h/send"]
    assert [r["path"] for r in h["lostResend"]["requests"]] == ["/api/portal/scope-group/grp_h/send"]
    assert h["retry"]["requests"][0]["body"] == {"retry_failed": True}
    assert h["lostResend"]["requests"][0]["body"] == {"resend_unknown": True}


@needs_node
def test_the_drawer_says_the_send_alls_refusals_as_they_are(drawer):
    """Mutation: drop SEND_ALL_REFUSALS in crm-core.js — the drawer reads "Couldn't send it. Nothing
    was sent. ..." with a doubled verdict."""
    h = drawer["honest"]
    assert h["sendAllBlocked"]["note"] == "Nothing was sent. Lab 2: build its files on its Files page first."
    assert h["sendAllPublishFailed"]["note"].startswith("Nothing was emailed. Lab 2 could not be published")
    assert h["sendAllPublishFailed"]["retryShown"] is False


# ── one copy of the words ───────────────────────────────────────────────────
def test_the_words_live_in_one_file_both_pages_load():
    """scopeSendOutcome is crm-core.js's, portal.js takes it from there, and done.js calls it
    through window.TWCrm. A second copy in portal.js is how the two pages would drift apart."""
    portal = (FRONTEND / "js" / "portal.js").read_text(encoding="utf-8")
    core = (FRONTEND / "js" / "crm-core.js").read_text(encoding="utf-8")
    done = (FRONTEND / "js" / "done.js").read_text(encoding="utf-8")
    assert not re.search(r"\bfunction scopeSendOutcome\b", portal), "portal.js has its own copy"
    assert re.search(r"const \{ scopeSendOutcome \} = C;", portal)
    assert re.search(r"\bfunction scopeSendOutcome\(status, j, p\)", core)
    assert "scopeSendOutcome: scopeSendOutcome" in core
    assert "window.TWCrm.scopeSendOutcome(" in done
    for page in ("portal.html", "done.html"):
        html = (FRONTEND / page).read_text(encoding="utf-8")
        own = "/js/portal.js" if page == "portal.html" else "/js/done.js"
        assert html.index("/js/crm-core.js") < html.index(own), page
