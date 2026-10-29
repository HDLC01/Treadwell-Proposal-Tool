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
                "email. A revision goes out with Send all proposals in one email on its Files page."),
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


# ── proposals that were never built (Hanz, 2026-10-28) ─────────────────────
BUILDING = ("Building Room 3 first: it has never been built, so its proposal is made from its default "
            "wording and its sheet's price, exactly as Continue on its Proposal step would make it. "
            "Then every proposal goes in one email.")
MANUAL = ("Nothing was sent. Room 3 has never been built. Open its Proposal step and press Continue "
          "to Done, then send again.")


@pytest.fixture(scope="module")
def stale_page():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    return _node(TESTS / "js" / "files-stale-page-harness.js")


@needs_node
def test_the_files_page_says_it_builds_them_and_starts_the_walk(stale_page):
    """`needs_build`: the page starts Send all's walk to Room 3's own Proposal-step door, carrying
    what the estimator chose, says it is building, and publishes nothing.

    Mutation (checked by hand, 2026-10-28): drop the `if (allOut.build)` branch in done.js — the
    walk never starts (`nav` empty) and the button comes back with no building sentence."""
    w = stale_page["needsBuild"]["walk"]
    assert w["err"] == BUILDING
    assert w["button"] == "Building 1 proposal first…" and w["disabled"] is True
    assert len(w["nav"]) == 1 and w["nav"][0].startswith(
        "/proposal-review.html?d=C3&compose=files&sendall=")
    assert w["published"] == 0 and w["sendAll"] == 1
    rec = w["record"]
    assert rec["group"] == "G1" and rec["queue"] == ["C3"]
    assert rec["returnUrl"] == "https://tool/done.html?d=d1", "composed=1 rode the way back"
    assert rec["stash"] == {"message": "Your three proposals.", "emails": ["customer@example.com"],
                            "no_followups": [], "assigned_estimator": "kyle@wetreadwell.com",
                            "require_deposit": False, "notify_add": [], "notify_mute": [],
                            "attachments": 0}


@needs_node
@pytest.mark.parametrize("case", ["noWalk", "cameBack"])
def test_a_page_that_cannot_build_says_the_manual_way(stale_page, case):
    """No walk module, or a page that already came back from a walk (a loop guard): the server's
    own sentence, the button back, nothing started."""
    r = stale_page["needsBuild"][case]
    assert r["err"] == MANUAL
    assert r["button"] == "Send all proposals in one email" and r["disabled"] is False
    assert r["nav"] == [] and r["record"] is None and r["published"] == 0


@needs_node
def test_back_from_building_the_choices_return_and_send_is_pressed_again(stale_page):
    """resumeSendAll, verbatim: the message, deposit, estimator, recipients and notify picks go
    back, then the page's own Send button is pressed once (so every check runs again).

    Mutation (checked by hand): drop `portalBtn.click();` — clicks is 0."""
    r = stale_page["resume"]["plain"]
    assert r["ret"] == "pressed" and r["clicks"] == 1
    assert r["message"] == "Your three proposals." and r["deposit"] is False
    assert r["estimator"] == "rj@wetreadwell.com"
    assert r["restored"] == [[["customer@example.com", "pm@x.test"], ["pm@x.test"]]]
    assert r["changed"] == {"troy@wetreadwell.com": True} and r["err"] is None


@needs_node
def test_back_from_building_with_files_attached_presses_nothing(stale_page):
    """Picked files cannot ride a page change, so nothing is sent without them: the estimator is
    asked to attach them again.

    Mutation (checked by hand): drop the `stash.attachments > 0` stop — clicks is 1."""
    r = stale_page["resume"]["attached"]
    assert r["ret"] == "attach" and r["clicks"] == 0
    assert r["err"].startswith("Every proposal is built now, and nothing has been sent yet.")
    assert "attach them again" in r["err"]


@needs_node
def test_the_files_page_takes_the_walk_once_and_only_for_its_project(stale_page):
    m = stale_page["mountTake"]
    assert m["otherProject"] == 0, "another project's page pressed Send"
    assert m["calls"] == [{"message": "hi"}], "the walk was not taken exactly once"
    assert m["addressBar"] == "/done.html?d=d1&files=1"


@needs_node
def test_the_drawer_says_it_builds_them_and_starts_the_walk(drawer):
    h = drawer["honest"]
    nb = h["needsBuild"]
    assert nb["note"] == BUILDING.replace("Room 3", "Lab 2")
    assert nb["started"] == [{"group": "grp_h", "build": [{"id": "hs-c", "label": "Lab 2"}],
                              "returnUrl": "/portal.html?open=hs-b"}]
    assert nb["disabled"] is True
    nw = h["needsBuildNoWalk"]
    assert nw["note"] == MANUAL.replace("Room 3", "Lab 2") and nw["disabled"] is False


@needs_node
def test_the_drawer_presses_once_when_it_comes_back(drawer):
    """The drawer reopened with `sendall_resume` presses the same send-all exactly once across two
    paints, and a resumed press answered needs_build again never starts another walk."""
    h = drawer["honest"]
    r = h["resumed"]
    assert [x["path"] for x in r["requests"]] == ["/api/portal/scope-group/grp_h/send-all"]
    assert r["asked"][0] == ["T9", "grp_h"] and r["startedAgain"] == 0
    again = h["resumedNeedsBuild"]
    assert again["requests"] == 1 and again["startedAgain"] == 0
    assert again["note"] == MANUAL.replace("Room 3", "Lab 2")


@needs_node
def test_mutation_the_drawer_ignores_needs_build(tmp_path):
    """Without the drawer's needs_build branch nothing is started and the walk never runs."""
    src = (FRONTEND / "js" / "portal.js").read_bytes().decode("utf-8").replace("\r\n", "\n")
    old = "      if (out.build) {\n"
    assert src.count(old) == 1
    front = tmp_path / "frontend"
    shutil.copytree(FRONTEND, front)
    (front / "js" / "portal.js").write_bytes(src.replace(old, "      if (false) {\n").encode("utf-8"))
    out = _node(TESTS / "js" / "drawer-render-harness.js", front)
    assert out["honest"]["needsBuild"]["started"] == []


@needs_node
def test_mutation_the_drawer_never_resumes(tmp_path):
    src = (FRONTEND / "js" / "portal.js").read_bytes().decode("utf-8").replace("\r\n", "\n")
    old = '      if (back) post(send, sendAllBody(), "/send-all", true);\n'
    assert src.count(old) == 1
    front = tmp_path / "frontend"
    shutil.copytree(FRONTEND, front)
    (front / "js" / "portal.js").write_bytes(src.replace(old, "").encode("utf-8"))
    out = _node(TESTS / "js" / "drawer-render-harness.js", front)
    assert out["honest"]["resumed"]["requests"] == []


def test_the_walk_loads_before_every_page_that_uses_it():
    for page, own in (("portal.html", "/js/portal.js"), ("done.html", "/js/done.js"),
                      ("proposal-review.html", "/js/proposal-review.js")):
        html = (FRONTEND / page).read_text(encoding="utf-8")
        assert "/js/send-all-chain.js?v=" in html, page
        assert html.index("/js/send-all-chain.js") < html.index(own), page


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
