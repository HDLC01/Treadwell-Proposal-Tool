"""The board and the drawer know a project's scopes (RJ, 2026-10-24), EXECUTED.

Two harnesses run the real portal.js:
  * board-render-harness.js renders every tab in both views; two of its rows are scopes of one
    project (one with no files yet, one published and waiting for the combined email), and the
    card's "Scope 1 of 2 · Breakroom" line, the table's tag and the two chips are read back out of
    the html it produced;
  * drawer-render-harness.js renders both drawers on those rows and PRESSES every scope control
    through the real wireScope: the empty name, the new scope (the request and where it navigates),
    the stale-copy 409, the siblings, and the combined email's 409 and 200.

THE LIFT DISCIPLINE. scopeHtml and wireScope are new names called from renderNotSent and
renderDetail, which three harnesses lift by name. If either is missing from a lift list, every
drawer scenario in that harness dies with a ReferenceError, and test_no_drawer_scenario_threw below
(plus every existing drawer test) goes red, which is what it is for.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

TESTS = pathlib.Path(__file__).resolve().parent
FRONTEND = TESTS.parents[1] / "frontend"
BOARD = TESTS / "js" / "board-render-harness.js"
DRAWER = TESTS / "js" / "drawer-render-harness.js"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _run(*args):
    proc = subprocess.run(["node", *map(str, args)], capture_output=True, text=True,
                          encoding="utf-8", timeout=180)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def board():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    return _run(BOARD, FRONTEND / "js" / "crm-core.js", FRONTEND / "js" / "portal.js",
                FRONTEND / "portal.html")


@pytest.fixture(scope="module")
def drawer():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    return _run(DRAWER, FRONTEND)


# ── the board ───────────────────────────────────────────────────────────────
@needs_node
def test_each_scope_card_says_its_place_and_its_name(board):
    r = board["results"]["active/board"]
    assert [x["text"] for x in r["scopeLines"]] == ["Scope 1 of 2 · Breakroom",
                                                    "Scope 2 of 2 · Lab &lt;1&gt;"]
    assert all("Breakroom, Lab &lt;1&gt;" in x["title"] for x in r["scopeLines"]), r["scopeLines"]


@needs_node
def test_a_scope_without_files_sits_beside_its_sibling_and_says_so(board):
    r = board["results"]["active/board"]
    assert "scope-a" in r["byCol"]["Created but not sent"]
    assert "scope-b" in r["byCol"]["Sent"]
    assert r["filesPendingChips"] == 1 and r["emailNotSentChips"] == 1


@needs_node
def test_the_table_view_tags_the_scope(board):
    assert board["results"]["active/table"]["scopeTags"] == ["Breakroom", "Lab &lt;1&gt;"]


@needs_node
def test_an_ungrouped_card_gains_nothing(board):
    total = sum(len(board["results"][k]["scopeLines"]) for k in board["results"])
    assert total == 2, "a card outside a scope group drew a scope line"


# ── the drawers ─────────────────────────────────────────────────────────────
@needs_node
def test_no_drawer_scenario_threw(drawer):
    assert drawer["errors"] == {}, sorted(drawer["errors"])


@needs_node
def test_the_unsent_scope_lists_its_siblings_escaped(drawer):
    html = drawer["scope"]["notSent"]["html"]
    assert 'id="dsec-ns-scope"' in html and "Scope 1 of 3" in html
    assert 'data-scope-open="scope-b" data-scope-board="1"' in html
    assert "Lab &lt;2&gt;" in html and "Lab <2>" not in html
    assert "files are not built yet" in html, "a scope with no files claims its paperwork exists"
    assert 'id="scope-send"' not in html, "an unpublished scope offered the combined email"


@needs_node
def test_an_empty_name_asks_for_one_and_sends_nothing(drawer):
    e = drawer["scope"]["emptyLabel"]
    assert e["requests"] == 0 and "Name the new scope" in e["note"]


@needs_node
def test_a_new_scope_is_made_with_the_drafts_version_and_opened(drawer):
    m = drawer["scope"]["made"]
    assert m["requests"] == [{"path": "/api/draft/scope-a/scope", "method": "POST",
                              "body": {"label": "Lab 3", "draft_version": "2026-10-20T10:00:00Z"}}]
    assert m["nav"] == ["/?d=scope-new&edit=1"]


@needs_node
def test_a_stale_copy_is_said_in_the_servers_words_and_nothing_opens(drawer):
    s = drawer["scope"]["stale"]
    assert s["note"].startswith("Couldn't make the new scope. Nothing changed.")
    assert s["disabled"] is False and s["nav"] == []


@needs_node
def test_a_sibling_opens_its_drawer_or_its_estimate(drawer):
    assert drawer["scope"]["siblingButtons"] == ["scope-b", "scope-c"]
    assert drawer["scope"]["siblingNav"] == ["/?d=scope-c&edit=1"]


@needs_node
def test_the_sent_scope_card_is_registered_and_offers_the_combined_email(drawer):
    s = drawer["scope"]["sent"]
    assert 'id="dsec-scope"' in s["html"] and "dsec-scope" in s["eligible"]
    assert 'id="scope-send" data-resend=""' in s["html"]
    assert "dsec-scope" in drawer["secMap"]["proposal"]
    assert drawer["secMap"]["proposal"][-1] == "dsec-delete"


@needs_node
def test_the_combined_email_names_the_scopes_still_to_publish(drawer):
    n = drawer["scope"]["notPublished"]
    assert n["requests"] == [{"path": "/api/portal/scope-group/grp_x/send", "method": "POST",
                              "body": {"resend": False}}]
    assert "Not sent yet: Breakroom, Lab <2>." in n["note"]
    assert drawer["scope"]["sentOk"]["note"] == "Sent to 2 contacts, one email with every scope."
