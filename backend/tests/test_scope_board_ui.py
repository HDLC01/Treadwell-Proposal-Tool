"""The board and the drawer know a project's scopes (RJ, 2026-10-24), EXECUTED.

Two harnesses run the real portal.js:
  * board-render-harness.js renders every tab in both views; two of its rows are scopes of one
    project (one with no files yet, one published and waiting for the combined email), and the
    card's "Scope 1 of 2 · Breakroom" line, the table's tag and the two chips are read back out of
    the html it produced;
  * drawer-render-harness.js renders both drawers on those rows and PRESSES every scope control
    through the real wireScope: the siblings and the combined email's 409 and 200. Since plan step 7
    (2026-10-27) the card is "Proposals of this project", drawn only on a project with two or more
    proposals, and no drawer offers a new scope (the proposal page's Create Multiple Proposals does).

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


NEW_SCOPE_MARKS = ('id="scope-new-btn"', 'id="scope-new-label"', "New scope for this project",
                   "Name the new scope")


def _no_new_scope_control(html):
    return [m for m in NEW_SCOPE_MARKS if m in html]


@needs_node
def test_a_grouped_drawer_titles_its_card_and_offers_no_new_scope(drawer):
    """Plan step 7: Create Multiple Proposals replaced the drawer's New scope box, in both drawers."""
    for key in ("notSent", "sent"):
        html = drawer["scope"][key]["html"]
        assert "Proposals of this project" in html, key
        assert "Scopes of this project" not in html, key
        assert _no_new_scope_control(html) == [], key
        assert 'id="scope-note"' in html, key
    assert '<ul class="scope-list">' in drawer["scope"]["sent"]["html"]


@needs_node
def test_a_project_of_one_proposal_has_no_card_in_either_drawer(drawer):
    one = drawer["one"]
    for key in ("soloSent", "loneSent"):
        assert 'id="dsec-scope"' not in one[key]["html"], key
        assert "dsec-scope" not in one[key]["eligible"], key
        assert _no_new_scope_control(one[key]["html"]) == [], key
        assert "Proposals of this project" not in one[key]["html"], key
    assert 'id="dsec-ns-scope"' not in one["soloNotSent"]["html"]
    assert _no_new_scope_control(one["soloNotSent"]["html"]) == []


@needs_node
def test_a_sibling_not_on_the_board_yet_still_makes_two_proposals(drawer):
    one = drawer["one"]
    sent = one["offBoardSent"]["html"]
    assert 'id="dsec-scope"' in sent and "dsec-scope" in one["offBoardSent"]["eligible"]
    assert "(this one)" in sent and "(not on the board yet)" in sent
    assert 'id="scope-send"' in sent
    # pair-c was made by Create Multiple Proposals (proposal_of), so it opens on its proposal page.
    assert one["offBoardNav"] == ["/proposal-review.html?d=pair-c"]
    ns = one["offBoardNotSent"]["html"]
    assert 'id="dsec-ns-scope"' in ns and "(not on the board yet)" in ns and "(this one)" in ns
    assert _no_new_scope_control(sent + ns) == []


@needs_node
def test_a_project_that_gains_a_sibling_shows_the_card_on_the_next_paint(drawer):
    one = drawer["one"]
    assert 'id="dsec-scope"' not in one["growBefore"]["html"]
    assert "dsec-scope" not in one["growBefore"]["eligible"]
    assert 'id="dsec-scope"' in one["growAfter"]["html"]
    assert "dsec-scope" in one["growAfter"]["eligible"]
    assert one["growSendPresent"] is True


@needs_node
def test_a_sibling_opens_its_drawer_or_its_estimate(drawer):
    assert drawer["scope"]["siblingButtons"] == ["scope-b", "scope-c"]
    assert drawer["scope"]["siblingNav"] == ["/?d=scope-c&edit=1"]


@needs_node
def test_a_proposal_made_from_another_scopes_estimate_opens_on_its_proposal_page(drawer):
    """Create Multiple Proposals (2026-10-27): a member with `proposal_of` has no intake of its own, so off the board it
    opens /proposal-review.html, and only it is marked data-scope-proposal."""
    c = drawer["scope"]["proposalChild"]
    assert c["marks"] == [["scope-b", ""], ["scope-c", ""], ["scope-d", "1"]]
    assert c["nav"] == ["/?d=scope-c&edit=1", "/proposal-review.html?d=scope-d"]


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
    # The drawer's button is the project's ONE press (2026-10-27): the send-all, which publishes what
    # the customer does not have yet before the one email (main.py api_scope_group_send_all).
    assert n["requests"] == [{"path": "/api/portal/scope-group/grp_x/send-all", "method": "POST",
                              "body": {"resend": False}}]
    assert "Not published yet: Breakroom, Lab <2>." in n["note"]
    assert n["note"].startswith("Nothing was sent.")
    assert drawer["scope"]["sentOk"]["note"] == "Sent to 2 contacts, one email with every scope."


# ── the project workbook (plan step 6, 2026-10-27) ─────────────────────────
@needs_node
def test_a_v1_groups_workbook_button_opens_its_homes_files_page(drawer):
    """A v1 home's own .xlsx is already one workbook with a tab per sheet, and the group route refuses
    v1 members (member_not_v2), so the button goes to the HOME's Files page (the member the others
    were made from), not this drawer's project, and builds nothing."""
    b = drawer["scope"]["v1Book"]
    assert b["present"] and b["label"] == "scope-b"
    assert "Open the project workbook" in b["html"] and "Lab 1's estimate, on its Files page" in b["html"]
    assert b["nav"] == ["/done.html?d=scope-b&files=1"]
    assert not any("/workbook" in p for p in b["requests"]), b["requests"]


@needs_node
def test_a_v1_group_of_independent_scopes_offers_no_project_workbook(drawer):
    """A #711 group (each scope its own intake and estimate, no proposal_of): the first scope's .xlsx
    holds only its own sheets, so no button claims to be the project workbook."""
    b = drawer["scope"]["v1Independent"]
    assert b["present"] is False
    assert "project workbook" not in b["html"]


@needs_node
def test_a_mixed_v1_groups_workbook_button_names_whose_workbook_it_is(drawer):
    """scope-d was made from Lab 1, but Breakroom and Lab <2> have their own estimates: the button opens
    Lab 1's Files page and says it is Lab 1's workbook, not the project's."""
    b = drawer["scope"]["v1Mixed"]
    assert b["present"] and b["files"] == "scope-b"
    assert "Open Lab 1's workbook" in b["html"] and "Open the project workbook" not in b["html"]
    assert "Each other scope's estimate is on its own Files page." in b["html"]


@needs_node
def test_a_v2_groups_workbook_button_builds_and_saves_the_group_workbook(drawer):
    b = drawer["scope"]["v2Book"]
    assert 'id="scope-workbook" data-files=""' in b["html"] and "Download the project workbook" in b["html"]
    ok = b["ok"]
    assert ok["requests"] == [["GET", "/api/scope-group/grp_x/workbook"], ["GET", "/api/file/tok-wb"]]
    assert ok["saved"] == [{"download": "Acme_HQ_scopes_estimate.xlsx", "clicks": 1, "detached": True}]
    assert ok["nav"] == [] and ok["note"] == "" and ok["disabled"] is False


@needs_node
def test_a_refused_v2_workbook_is_said_in_the_servers_words_and_nothing_is_saved(drawer):
    r = drawer["scope"]["v2Book"]["refused"]
    assert r["requests"] == ["/api/scope-group/grp_x/workbook"] and r["saved"] == 0
    assert r["note"] == ("Couldn't build the project workbook. “Lab 1” is not priced on one sheet. "
                         "Make one sheet its base first.")
    assert r["disabled"] is False


@needs_node
def test_a_project_of_one_proposal_offers_no_project_workbook(drawer):
    assert drawer["scope"]["loneBook"] is False
