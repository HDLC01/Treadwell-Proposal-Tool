"""The Follow-ups page shows the follow-ups that WENT OUT, not only the one that is due next.

Hanz, 2026-08-24, the day the cadence started sending on production (its first sweep sent 18
emails): "make sure all follow up emails are shown in the Chat box and in the Follow Ups section."
The chat half lives in the portal's worker. This file owns the page half.

WHAT WAS ACTUALLY WRONG, because "add a column" was not the diagnosis.

The page's feed is /api/portal/followups, which wraps the portal's /api/admin/pipeline. Two
follow-up timestamps travel on each row:

    next_followup_at    what is COMING. Computed per request from followup_rules.next_due_at.
    last_followup_at    the portal's `last_staff_followup_at`, and this is the trap. Its SQL
                        (portal db.list_all_portal_proposals) counts portal_followups rows of kind
                        staff_call / staff_email / staff_text / staff_note with no `action` key.
                        The automation writes kind AUTO_EMAIL, so it is counted nowhere in it.

So a project the cadence had emailed twice that morning rendered "never" under a column headed
"Last chased", and nothing anywhere on the page said an email had gone out. Both halves of that are
fixed here: the column is now headed "Chased by hand" and says in its tooltip what it leaves out,
and each row opens the project's real log.

NO SECOND LOG WAS BUILT. portal_followups already holds one row per send, reserved by the worker
BEFORE it sends (that ordering is the dedupe), and the CRM drawer already reads it through
/api/portal/proposal/{id}. The page opens that same route on demand, one project at a time, because
the pipeline payload does not carry the log and fetching sixty histories to show one would be sixty
round trips through the portal on every page load.

WHAT THE PAGE STILL CANNOT SAY, asserted below so nobody "fixes" it by guessing: which ADDRESS a
reminder went to. followup_worker.reserve_followup stores {audience, template, rule_key} and not the
recipients, and the recipients are not simply the proposal's contacts either (a contact can be opted
out of follow-ups while still getting the proposal). A line may therefore say which SIDE got it and
must not name anybody.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

import main
from fastapi.testclient import TestClient

client = TestClient(main.app)
ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "followups-sent-harness.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def ran():
    out = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr or out.stdout
    return json.loads(out.stdout.strip().splitlines()[-1])


# ── the finding, as an executed claim ─────────────────────────────────────────
def test_the_feed_carries_no_send_log_which_is_why_the_panel_fetches_one(monkeypatch):
    """The reason the Emails button costs a round trip. If the pipeline ever starts carrying the
    log, this fails and the panel should read it off the row instead."""
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: {"email": e, "role": "user"})
    monkeypatch.setattr(main, "_portal", lambda p, m="GET", b=None: {"ok": True, "proposals": [{
        "proposal_id": "p1", "project_name": "Oak Grove", "proposal_status": "sent",
        "customer_email": "d@x.com", "deposit_status": "pending", "schedule_status": "pending",
        "approved_total": 1000.0, "unread": 0, "last_followup_at": None,
        "next_followup_at": "2026-08-27T12:00:00+00:00",
        "followup_state": {"enrolled": True, "enabled": True},
    }]})
    p = client.get("/api/portal/followups").json()["proposals"][0]
    assert "followups" not in p and "sent_followups" not in p, (
        "the feed now carries the log; the page should render it from the row rather than "
        "fetching each project")
    # And the one stamp it does carry is the STAFF one, which is the whole reason the column got
    # renamed. Nothing automated can move it, so an automated send leaves it None.
    assert p["last_followup_at"] is None


def test_the_pipeline_stamp_the_column_reads_is_the_staff_only_one():
    """Read out of the PORTAL, because that is where the exclusion is written and this repo cannot
    execute it. Two facts have to hold together for the rename to be right: the key the page reads
    is fed by last_staff_followup_at, and that column counts only the staff kinds."""
    portal = ROOT.parent / "treadwell-portal" / "backend"
    if not portal.is_dir():
        pytest.skip("the portal checkout is not beside this one")
    api = (portal / "main.py").read_text(encoding="utf-8")
    assert '"last_followup_at": _iso(r.get("last_staff_followup_at"))' in api, (
        "the pipeline no longer maps last_followup_at from the staff-only stamp; re-read whether "
        "the Chased by hand column is still telling the truth")
    sql = (portal / "db.py").read_text(encoding="utf-8")
    i = sql.index("as last_staff_followup_at")
    window = sql[max(0, i - 700):i]
    assert "f.kind in ('staff_call','staff_email','staff_text','staff_note')" in window, (
        "the staff-followup stamp's kind filter changed; if it counts auto_email now, the column "
        "can go back to being called Last chased")
    assert "auto_email" not in window


# ── what the panel renders ────────────────────────────────────────────────────
@needs_node
def test_a_row_carries_no_panel_until_it_is_opened(ran):
    """The button is always there; the panel is not. Executed rather than read, because "renders
    only when OPEN holds the id" is a branch, and a source grep sees both sides of it."""
    closed = ran["closed"]["html"]
    assert 'data-act="sent"' in closed, "the Emails button is gone from the row"
    assert 'aria-expanded="false"' in closed
    assert "fh-row" not in closed, "a closed row is rendering the history panel"
    assert 'aria-expanded="true"' in ran["open"]["html"]


@needs_node
def test_the_automated_sends_are_listed_with_the_side_that_got_them(ran):
    """THE test in this file. Two automated emails went out on this project, one to the customer and
    one to the estimator, and the page showed neither before today.

    The audience wording is the part that must be exact. The staff half of the cadence is written
    for us ("worth a call", "deposit outstanding") and never reaches the customer, so a line that
    said "sent to the customer" would tell an estimator the customer had been chased twice when
    they had been chased once."""
    html = ran["open"]["html"]
    assert "Second nudge" in html, "the customer reminder is not listed"
    assert "sent to the customer" in html
    assert "Told the team: worth a call" in html, "the staff reminder is not listed"
    assert "sent to the estimator, not the customer" in html
    # The staff line must not claim the customer got it. Checked on the line itself, not the page:
    # the customer line above legitimately contains that phrase.
    staff_li = [b for b in html.split("<li ") if "Told the team" in b][0]
    assert "sent to the customer" not in staff_li
    # A person's own call is in the same list, so the panel is the whole history and not a
    # second, automation-only log.
    assert "left a voicemail" in html and "Call" in html


@needs_node
def test_the_summary_counts_the_two_audiences_separately(ran):
    """"2 emails went out" with the staff half inside the total is the same lie as above, in one
    sentence at the top of the panel."""
    assert ran["summary"] == {"emails": 2, "toCustomer": 1, "toStaff": 1,
                             "last": "2026-08-24T13:00:00Z"}
    assert "2 emails went out: 1 to the customer, 1 to the estimator." in ran["open"]["html"]


@needs_node
def test_bookkeeping_is_kept_and_is_not_counted_as_an_email(ran):
    """"Automation off, three weeks ago" is the answer to "why has nothing gone out", so the rows
    stay. They are not outreach, so they must not reach the count."""
    assert "Automation off" in ran["open"]["html"]
    lines = ran["lines"]
    book = [l for l in lines if l["what"] == "Automation off"]
    assert book and book[0]["side"] == "" and book[0]["auto"] is False
    assert ran["summary"]["emails"] == 2, "bookkeeping was counted as an email"


@needs_node
def test_a_malformed_log_renders_instead_of_throwing(ran):
    """This panel is read-only reporting on somebody else's table, reached through a proxy. A legacy
    row with no detail, or a kind added on the portal side and not here, must produce a line rather
    than an exception: row() builds one template literal per project and a throw inside it takes the
    whole table down, not one line of it. Every probe is rendered as markup too, not just counted."""
    for i, got in enumerate(ran["junk"]):
        assert got["ok"], "probe %d threw: %s" % (i, got.get("error"))
    # An auto_email with no detail at all still reads as an email to the CUSTOMER, which is the
    # cautious way round: it appears in the count a human then checks, rather than being silently
    # filed as internal and never shown next to what the customer received.
    assert ran["junk"][4] == {"ok": True, "emails": 1, "lines": 1,
                              "what": "Automatic email", "side": "customer"}
    # An unknown kind prints the kind rather than an empty label, and is not counted as outreach.
    assert ran["junk"][6]["what"] == "wat" and ran["junk"][6]["emails"] == 0


@needs_node
def test_the_panel_never_names_a_recipient(ran):
    """The worker records the audience and not the address, so a line that named somebody would be
    invented. The note says which side, and says outright that it is not the address."""
    html = ran["open"]["html"]
    assert "@" not in html.split('<tr class="fh-row"')[1], (
        "an email address reached the history panel, which the log does not record per send")
    assert "not the address" in html


@needs_node
@pytest.mark.parametrize("state,needle", [
    ("loading", "Reading the follow-up history"),
    ("errored", "Couldn't read the history: HTTP 502"),
    ("empty", "Nothing has been sent or logged on this project yet."),
])
def test_every_state_of_the_panel_says_something(ran, state, needle):
    """A fetch in flight, a portal that 502s, and a project with no history at all. Each is a
    separate branch of one function and each renders, rather than leaving an empty strip that reads
    as "no emails have been sent"."""
    assert needle in ran[state]["html"]
    assert "fh-row" in ran[state]["html"]


@needs_node
def test_every_date_on_the_panel_goes_through_the_business_timezone(ran):
    """House rule: dates render in America/Chicago via TW.fmtBizDate, never viewer-local. The
    harness stubs TW to a marker, so a raw ISO string or a toLocaleDateString would show up as
    itself. Worth an assertion on this page specifically: it was unlinked for a fortnight while the
    rest of the app moved onto TW.*"""
    html = ran["open"]["html"]
    panel = html.split('<tr class="fh-row"')[1]
    assert "BIZ(2026-08-24T13:00:00Z)" in panel, "the newest send is not rendered through TW"
    assert len(ran["open"]["dates"]) >= 4, "not every log line's date went through TW"
    assert not re.search(r"20\d\d-\d\d-\d\dT(?![^(]*\))", panel.replace("BIZ(", "(")), (
        "a raw timestamp reached the panel")
    js = (FRONTEND / "js" / "followups.js").read_text(encoding="utf-8")
    assert "toLocaleDateString" not in js and "toLocaleString(" not in js.replace(
        "toLocaleString(undefined", "MONEY("), "a viewer-local date crept into the page"


# ── the column that was lying ─────────────────────────────────────────────────
@needs_node
def test_the_chased_column_says_what_it_measures(ran):
    """It reads the staff-only stamp, so it cannot be headed "Last chased" while the automation is
    the thing doing most of the chasing. The tooltip is asserted too: the header alone does not
    tell somebody where the automated sends went."""
    head = ran["head"]
    assert "Chased by hand" in head, "the column is back to claiming it counts every chase"
    assert "Last chased" not in head
    assert "Automatic reminders are not counted here" in head
    assert 'data-sortby="chased"' in head, "the column stopped being sortable"


# ── two copies of one vocabulary, pinned ──────────────────────────────────────
def _maps(src: str, name: str) -> dict:
    """A `var|const NAME = { key: "value", ... };` object literal, as a dict.

    Both keywords, because followups-core.js is written in the ES5 style its node harness runs it
    in and portal.js is not. Matching only one of them read as "the map is gone"."""
    m = re.search(r"\n\s*(?:var|const|let) %s = \{" % re.escape(name), src)
    assert m, "%s is gone; rewrite this test rather than deleting it" % name
    body = src[m.start():src.index("};", m.start())]
    got = dict(re.findall(r'(\w+):\s*"([^"]*)"', body))
    assert got, "%s parsed as empty, so comparing it proves nothing" % name
    return got


@needs_node
def test_the_page_and_the_drawer_word_a_follow_up_the_same_way(ran):
    """followups-core.js carries the same three label maps portal.js has for the drawer's History
    list. They are two copies because portal.js is where backend/tests/js/drawer-render-harness.js
    lifts those constants from BY NAME, so moving them out breaks that harness.

    Two copies of one list is how one of them rots, so they are asserted equal here, the same way
    auth.js's NO_SIDEBAR_TABS is asserted equal to nav_access.py's. Executed on the core side (the
    values come out of the module) and read on the drawer's.

    If they ever have to differ, the honest fix is to name the difference here rather than to
    delete the test: an estimator reading "Second nudge" on this page and something else in the
    drawer for the same row cannot tell they are the same event."""
    portal = (FRONTEND / "js" / "portal.js").read_text(encoding="utf-8")
    for name, got in (("FU_TEMPLATE_LABEL", ran["templates"]),
                      ("FU_KIND_LABEL", ran["kinds"]),
                      ("FU_ACTION", ran["actions"])):
        assert _maps(portal, name) == got, (
            "%s has drifted between portal.js (the drawer) and followups-core.js (this page)"
            % name)


def test_every_template_the_worker_can_send_has_a_label():
    """The maps above are only worth pinning if they are complete. Read out of the portal's worker
    and rules: an unmapped template renders as the bare "Automatic email", which is exactly the
    "something went out, no idea what" the panel exists to replace."""
    portal = ROOT.parent / "treadwell-portal" / "backend"
    if not portal.is_dir():
        pytest.skip("the portal checkout is not beside this one")
    rules = (portal / "followup_rules.py").read_text(encoding="utf-8")
    # Every Due(...) the rule engine can return, whose three fields are (rule_key, audience,
    # template). Matched on the audience/template pair because the rule_key is often a computed
    # call spanning a line break, and the pair is what the worker stores.
    sent = set(re.findall(r'"(?:customer|staff)",\s*"([a-z_]+)"', rules, re.S))
    assert len(sent) >= 5, ("only found %s in followup_rules.py; this test needs rewriting rather "
                            "than passing on an empty set" % sorted(sent))
    core = (FRONTEND / "js" / "followups-core.js").read_text(encoding="utf-8")
    labelled = set(_maps(core, "FU_TEMPLATE_LABEL"))
    assert sent <= labelled, (
        "the cadence can send %s, which the Follow-ups page has no wording for"
        % sorted(sent - labelled))


# ── the wiring the harness cannot see ─────────────────────────────────────────
def test_an_open_panel_survives_the_45_second_repaint():
    """#list is replaced wholesale on every paint, and this page polls. So the open set and the
    fetched log are page STATE inside the paint signature, not DOM the click inserted: without them
    in the signature the panel opens and the arriving log never appears, because nothing tells
    paint() anything changed."""
    js = (FRONTEND / "js" / "followups.js").read_text(encoding="utf-8")
    sig = js[js.index("function paint()"):]
    sig = sig[:sig.index("if (sig === LAST_SIG)")]
    # COMMENTS STRIPPED, and that is not fussiness: the comment above this signature explains OPEN
    # and HIST_GEN by name, so a version that dropped them from the actual JSON.stringify still
    # matched. The mutation passed until this line existed.
    sig = "\n".join(l for l in sig.splitlines() if not l.strip().startswith("//"))
    assert "OPEN" in sig and "HIST_GEN" in sig, (
        "the paint signature ignores the history panel, so it cannot repaint for it")


def test_the_emails_button_neither_navigates_nor_swallows_the_row():
    """The row is a link into the CRM drawer, so the button has to stop its click the way Send and
    Log a call do. And a click INSIDE the open panel must not navigate either: the panel is a row
    of its own with no data-id, so without its own guard it falls through to the navigation."""
    js = (FRONTEND / "js" / "followups.js").read_text(encoding="utf-8")
    i = js.index('data-act="sent"]')
    assert "stopPropagation" in js[i:i + 140], "opening the history also leaves the page"
    assert 'e.target.closest("tr.fh-row")' in js, "a click inside the panel navigates away"
    assert js.index('e.target.closest("tr.fh-row")') < js.index('const holder = e.target.closest('), (
        "the panel guard runs after the row lookup, which finds the wrong element")


def test_it_reads_the_drawers_route_and_adds_no_endpoint_of_its_own():
    """The log already exists and is already served. A new /api/... here would be a second reader of
    one table, and (see backend/nav_access.py) a second prefix nobody can gate."""
    js = (FRONTEND / "js" / "followups.js").read_text(encoding="utf-8")
    body = js[js.index("async function toggleSent("):]
    body = body[:body.index("\n  // One delegated listener")]
    assert '"/api/portal/proposal/" + encodeURIComponent(id)' in body
    assert "B.sentLog(" in body, "the page is re-deriving the lines instead of using the core"
    assert "/api/followups" not in js and "/api/sent" not in js
