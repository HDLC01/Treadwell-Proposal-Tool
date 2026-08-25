"""The drawer's Delete project button: the endpoint behind it, and the dialog in front of it.

Hanz, 2026-08-24: "In the proposals tab under the Active Projects create a 'delete project'
button", and "make sure there is a confirmation dialog". He had two SENT test bids that no control
in either app could take off the Active Projects board.

THE BUG THIS FIXES, measured before it was written. The Proposals Database's Trash button calls
DELETE /api/draft/{id}, which is drafts.trash_draft() -- one table, no portal call. The board is
built from the PORTAL's rows (/api/portal/pipeline -> the portal's list_all_portal_proposals),
whose join deliberately ignores the draft's deleted_at, so trashing a SENT project removed it from
the Proposals Database and left its card on the board for good. And the card that stayed behind was
corrupted: api_portal_pipeline enriches it from drafts.list_drafts(), which excludes trashed rows,
so it lost is_test, bid_total and won_at -- and is_test falling back to the name regex can move a
card from the Test tab onto Active with nobody touching it.

BOTH HALVES OR NEITHER is therefore the whole design, and it is what the tests below drive:
/api/project/{id}/delete hides the portal row FIRST and only then trashes the draft, so a portal
failure leaves the project exactly as it was rather than producing the trashed-but-still-on-the-
board card this feature exists to remove. The card ends up GONE rather than half-populated, and
that is asserted, not assumed.

THE FAKE PORTAL IMPLEMENTS THE CONTRACT, not the answer. It holds rows, hides them on /delete,
un-hides them on /restore, and serves /pipeline from whatever is live -- so "the card leaves the
board" is a consequence here rather than a fixture. The SQL that does the same job on the portal's
own side has its own tests in the portal repo (backend/tests/test_delete_project.py there).

REVERSIBLE, ADMINS ONLY, AND OFFERED ON SENT PROJECTS TOO: Hanz's three decisions, one section of
this file each.
"""
import json
import pathlib
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

import drafts
import main
import profiles

client = TestClient(main.app)

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "drawer-render-harness.js"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


# ── the fake portal ──────────────────────────────────────────────────────────
class FakePortal:
    """A stand-in that behaves like the portal rather than like an answer.

    _portal() translates the portal's 404 into HTTPException(404), which the tool reads as "there
    is no portal row" -- the normal state of a bid nobody ever sent. This reproduces that exactly,
    because the tolerance is the part most likely to be got wrong: too strict and an unsent project
    cannot be deleted at all, too loose and a real outage looks like a successful delete.
    """

    def __init__(self, rows=()):
        self.rows = {r["proposal_id"]: dict(r) for r in rows}
        self.calls = []
        self.fail = None                       # an HTTPException to raise instead of answering

    def __call__(self, path, method="GET", body=None):
        self.calls.append({"path": path, "method": method, "body": body})
        if self.fail is not None:
            raise self.fail
        if path == "/api/admin/pipeline":
            live = [dict(r) for r in self.rows.values() if r.get("deleted_at") is None]
            return {"ok": True, "proposals": live}
        for what in ("delete", "restore"):
            prefix, suffix = "/api/admin/proposal/", "/" + what
            if path.startswith(prefix) and path.endswith(suffix):
                pid = path[len(prefix):-len(suffix)]
                row = self.rows.get(pid)
                if row is None:
                    raise HTTPException(404, "not_found")
                row["deleted_at"] = "2026-08-24T12:00:00+00:00" if what == "delete" else None
                # The portal stamps this in the same statement. Carried here because the tool must
                # never be the thing that switches the chasing back on.
                if what == "delete":
                    row.setdefault("followup_disabled_at", "2026-08-24T12:00:00+00:00")
                return {"ok": True, what + "d": True}
        raise AssertionError("the tool called an endpoint this fake does not implement: " + path)

    def hidden(self, pid):
        return self.rows[pid].get("deleted_at") is not None


def _row(pid, **kw):
    r = {"proposal_id": pid, "token": "tok-" + pid, "project_name": "Nearman Creek",
         "customer_email": "gc@example.com", "proposal_status": "sent",
         "deposit_status": "pending", "schedule_status": "pending",
         "approved_total": None, "deposit_amount": None, "created_at": "2026-08-01T10:00:00+00:00",
         "deleted_at": None}
    r.update(kw)
    return r


def _draft_row(pid, **kw):
    """A `drafts` row as the store holds it, blob and all."""
    data = {"project_name": "Nearman Creek", "contact_email": "gc@example.com",
            "work_type": "epoxy", "is_test": True, "proposal_lump_sum": 41250,
            # has_files is what qualifies a project for the board's "Created but not sent"
            # column, so it is what makes the unsent assertions below able to fail.
            "generate_result": {"work_type": "epoxy"}}
    data.update(kw.pop("data", {}))
    row = {"id": pid, "data": data, "owner_email": "kyle@wetreadwell.com",
           "created_at": "2026-08-01T10:00:00+00:00", "updated_at": "2026-08-09T10:00:00+00:00",
           "deleted_at": None}
    row.update(kw)
    return row


@pytest.fixture
def wired(fake_supabase, monkeypatch):
    """A real drafts store, a fake portal, and an admin caller.

    The drafts half runs the REAL drafts.trash_draft / restore_draft / list_drafts. The fake
    PostgREST refuses the projected select, which is a documented path in _build_summaries (it
    falls back to the full-blob read plus the real _summary), and that is deliberate: the fallback
    is the only path that derives has_files and the trash filter from the row itself, which is what
    makes "the card leaves the board" a computed result rather than a fixture.
    """
    # Two projects, with DIFFERENT names: p1 has a portal row (it was sent), d2 does not (it was
    # only ever generated). One name for both would let an assertion about p1's card be satisfied
    # by d2's.
    store = {"drafts": [_draft_row("p1"),
                        _draft_row("d2", data={"project_name": "Cedar Ridge"})],
             "events": []}
    fake = fake_supabase(store)

    class Client:
        store = fake.store

        def table(self, name):
            t = fake.table(name)
            real = t.select

            def select(*a, **k):
                if a and "->" in str(a[0]):
                    raise RuntimeError("PostgREST: projected select unsupported here")
                return real(*a, **k)

            t.select = select
            return t

    monkeypatch.setattr(drafts, "get_client", lambda: Client())
    portal = FakePortal([_row("p1")])
    monkeypatch.setattr(main, "_portal", portal)
    monkeypatch.setattr(profiles, "get_by_email",
                        lambda e: {"id": "a1", "email": e, "role": "admin"})

    class W:
        pass

    w = W()
    w.store = store
    w.portal = portal
    w.monkeypatch = monkeypatch
    return w


def _board():
    r = client.get("/api/portal/pipeline")
    assert r.status_code == 200, r.text
    return {p["proposal_id"]: p for p in r.json()["proposals"]}


def _draft(store, pid):
    return [r for r in store["drafts"] if r["id"] == pid][0]


# ── 1. admins only, at the ENDPOINT ─────────────────────────────────────────
def test_a_non_admin_is_refused_at_the_endpoint(wired):
    """Hanz: admins only. Hiding the button is a courtesy; this is the gate.

    Nothing may move either -- a 403 that had already hidden the portal row would be the worst of
    both, since the drawer would report a failure while the card was gone."""
    wired.monkeypatch.setattr(profiles, "get_by_email",
                              lambda e: {"id": "u1", "email": e, "role": "user"})
    main._profile_cache_clear()
    r = client.post("/api/project/p1/delete")
    assert r.status_code == 403, r.text
    assert wired.portal.calls == [], "a refused caller still reached the portal"
    assert _draft(wired.store, "p1")["deleted_at"] is None


# ── 2. the card leaves the board ────────────────────────────────────────────
def test_deleting_a_sent_project_takes_its_card_off_the_board(wired):
    """The case Hanz hit. The card is on the board before and gone after, and BOTH stores moved."""
    assert "p1" in _board(), "fixture is not on the board, so the test cannot bite"
    r = client.post("/api/project/p1/delete")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "existed": True, "trashed": True, "portal_hidden": True}
    assert wired.portal.hidden("p1")
    assert _draft(wired.store, "p1")["deleted_at"] is not None
    assert "p1" not in _board(), "the card is still on the board"


def test_the_card_is_gone_rather_than_left_behind_half_populated(wired):
    """FACT 3, pinned. Trashing a sent draft on its own leaves the portal card in place with its
    is_test flag, its bid total and its won mark stripped, because the board's enrichment reads
    drafts.list_drafts() and that excludes trashed rows. A card whose is_test has silently reverted
    to the NAME heuristic can move itself from the Test tab onto Active with nobody touching it.

    Deleting removes the card entirely, so the trap has nowhere to live -- and that is the claim:
    not "the flag survives" but "there is no row to have lost it"."""
    before = _board()["p1"]
    assert before["is_test"] is True, "fixture is not carrying the flag that gets lost"
    client.post("/api/project/p1/delete")
    board = _board()
    assert "p1" not in board, (
        "the card outlived the project, which is the half-trashed state this replaces")
    # And nothing was synthesised in its place either: _not_sent_rows would file a sent project
    # under "Created but not sent" if the portal row went and the draft stayed.
    assert not [p for p in board.values() if p.get("project_name") == "Nearman Creek"]


def test_deleting_an_unsent_project_takes_its_card_off_the_board(wired):
    """The other half, and the one that runs entirely on real code: d2 has no portal row, so its
    card is synthesised by _not_sent_rows out of the drafts list. Trashing the draft is the whole
    of the delete, and the portal's 404 is expected rather than an error."""
    assert _board()["d2"]["not_sent"] is True
    r = client.post("/api/project/d2/delete")
    assert r.status_code == 200, r.text
    assert r.json()["portal_hidden"] is False, (
        "a bid nobody sent has no portal row; claiming one was hidden hides a real failure")
    assert "d2" not in _board()


def test_a_portal_failure_leaves_the_project_exactly_as_it_was(wired):
    """ORDER AND ABORT. If the portal cannot be reached, trashing the draft anyway is how you get
    the corrupted card above -- now with no way to reach the project that made it. So nothing of
    ours moves and the estimator is told."""
    wired.portal.fail = HTTPException(502, "Could not reach the customer portal.")
    r = client.post("/api/project/p1/delete")
    assert r.status_code == 502, r.text
    assert _draft(wired.store, "p1")["deleted_at"] is None, "the draft was trashed anyway"
    # The portal row is untouched too, so recovering is one press once the portal is back.
    assert not wired.portal.hidden("p1")


# ── 3. reversible, and it logs the verb that already existed ────────────────
def test_it_logs_the_trashed_verb_and_invents_no_second_one(wired):
    """`deleted_project` is a dead History verb: it has a label and a CSS dot and nothing has ever
    written it. Hanz's decision was that this is a move to TRASH, so the honest record is the verb
    Trash already writes. Two words for one act would make the feed read as two events."""
    client.post("/api/project/p1/delete")
    actions = [e["action"] for e in wired.store["events"]]
    assert "trashed" in actions
    assert "deleted_project" not in actions, "a second verb for the same act"
    ev = [e for e in wired.store["events"] if e["action"] == "trashed"][0]
    assert ev["detail"]["project_name"] == "Nearman Creek"


def test_restoring_puts_the_portal_row_back_and_the_card_reads_as_sent(wired):
    """From the Trash page, which is where the existing restore lives. The portal half is not
    optional: with only our deleted_at cleared, _not_sent_rows would synthesise a "Created but not
    sent" card for a project the customer has had for weeks."""
    client.post("/api/project/p1/delete")
    r = client.post("/api/draft/p1/restore")
    assert r.status_code == 200, r.text
    assert r.json()["portal_restored"] is True
    assert not wired.portal.hidden("p1")
    back = _board()["p1"]
    assert back.get("not_sent") is None, "a sent project came back as never sent"
    assert back["proposal_status"] == "sent"


def test_a_restore_leaves_the_cadence_off(wired):
    """Hanz: restore must not silently resume chasing. The stamp the delete left is still there
    after the restore, and nothing the tool sends asks the portal to clear it -- the follow-up
    panel's own switch is the way back on, which says so on the button."""
    client.post("/api/project/p1/delete")
    client.post("/api/draft/p1/restore")
    assert wired.portal.rows["p1"]["followup_disabled_at"] is not None
    bodies = [c for c in wired.portal.calls if c["path"].endswith("/restore")]
    assert len(bodies) == 1
    assert "followup" not in json.dumps(bodies[0]["body"] or {}), (
        "the restore is asking the portal to touch the cadence")


def test_a_restore_the_portal_refuses_leaves_the_project_in_trash(wired):
    """Same posture as the delete, and recoverable in the same way: press it again."""
    client.post("/api/project/p1/delete")
    wired.portal.fail = HTTPException(502, "Could not reach the customer portal.")
    r = client.post("/api/draft/p1/restore")
    assert r.status_code == 502
    assert _draft(wired.store, "p1")["deleted_at"] is not None, "the draft came back regardless"


def test_a_project_that_never_had_a_portal_row_still_restores(wired):
    """The Trash page restores everything, most of it never sent. A 404 from the portal is that
    project's normal answer and must not stop the restore."""
    client.post("/api/project/d2/delete")
    r = client.post("/api/draft/d2/restore")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "existed": True, "portal_restored": False}
    assert _board()["d2"]["not_sent"] is True


# ── 4. the dialog ───────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def out():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        "the harness itself failed - read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])["del"]


@needs_node
@pytest.mark.parametrize("where", ["sent", "notSent"])
def test_both_drawers_offer_the_button(out, where):
    """BOTH, and the sent one is the one Hanz asked for: an unsent bid could already be archived,
    a sent one had no way off the board at all."""
    assert out[where]["offered"] is True


@needs_node
@pytest.mark.parametrize("where", ["sent", "notSent"])
def test_the_button_sits_apart_from_the_three_ways_out_of_the_drawer(out, where):
    """Hanz's placement, and the reason for it: Open the files / Edit the estimate / Info sheet sit
    in one .row3, and a delete inside that row is one an estimator can hit while reaching for the
    estimate. Asserted off the markup, because "apart" is a fact about the DOM: the button must not
    be inside the same section element as any of those three."""
    html = out[where]["html"]
    i = html.index('id="del-project"')
    # The nearest section opening before the button, and what else is inside that section.
    j = html.rindex('<div class="sec', 0, i)
    section = html[j:i]
    for other in ("go-files", "go-info", "go-edit", "data-go-files", "data-go-info"):
        assert other not in section, (
            "the delete button shares a section with %s in the %s drawer" % (other, where))
    assert "row3" not in html[j:html.index(">", j)], (
        "the delete button is in the .row3 button row it must stay out of")


@needs_node
@pytest.mark.parametrize("where", ["sent", "notSent"])
def test_it_asks_before_it_posts_and_the_ask_names_the_project(out, where):
    """The pattern this week: NAME THE CONSEQUENCE, do not ask "are you sure". The dialog is
    TW.confirmDanger -- the helper confirmBringBack is built on, which traps focus and focuses
    Cancel -- and never window.confirm, which cannot be styled, cannot be tested and cannot say
    what it is about to do."""
    asked = out[where]["asked"]
    assert len(asked) == 1, "the button posted without asking, or asked twice"
    a = asked[0]
    assert a["name"] in ("Nearman Creek", "Cedar Ridge Distribution Center"), a["name"]
    assert a["confirmText"] and a["confirmText"] != "OK"
    assert a["tone"] == "danger"
    # The consequence, in the sentence beside the name.
    assert "board" in a["after"]


@needs_node
@pytest.mark.parametrize("where", ["sentCancelled", "notSentCancelled"])
def test_cancelling_writes_nothing(out, where):
    """The whole value of a confirmation. It was asked, and no request left the page."""
    assert out[where]["asked"], "nothing was asked at all"
    assert out[where]["requests"] == []
    assert out[where]["label"] == "Delete project", (
        "the button is left mid-action after a cancel")


@needs_node
def test_the_two_dialog_bodies_differ(out):
    """An unsent scratch bid and a live customer job are not the same act, so they must not read
    alike. The sent body has to name what else goes quiet AND be honest about what does not."""
    sent = out["sent"]["asked"][0]
    unsent = out["notSent"]["asked"][0]
    assert sent["after"] != unsent["after"]
    assert sent["detail"] != unsent["detail"]
    # What goes quiet.
    assert "follow-up" in sent["after"].lower()
    # What does NOT change, and why. The customer's link reads the pinned revision, so deleting a
    # project off our board is not revoking what they were sent -- a dialog that implied otherwise
    # would be pressed by somebody trying to take a link away.
    low = sent["detail"].lower()
    assert "keeps working" in low and "pinned" in low
    # And the unsent one must not promise to stop something that was never running.
    assert "follow-up" not in unsent["after"].lower()
    assert "never sent" in unsent["detail"].lower()


@needs_node
def test_the_delete_copy_has_no_em_dashes(out):
    """House rule, and this copy is read in a modal where a dash is a guess about tone."""
    for key in ("sent", "notSent"):
        a = out[key]["asked"][0]
        for field in ("title", "after", "detail", "confirmText", "cancelText"):
            assert "—" not in a[field], (key, field)
        # Scoped to the section this feature added. The rest of the drawer is
        # test_drawer_renders.py's business, and the chat thread carries the portal's own
        # "Heading - detail" separator, which is inbound data rather than our words.
        html = out[key]["html"]
        i = html.index('id="del-project"')
        j = html.rindex('<div class="sec', 0, i)
        assert "—" not in html[j:html.index("</div>", i)]


@needs_node
def test_a_refused_delete_claims_nothing_and_gives_the_button_back(out):
    """The drawer closes on success, so a failure that also closed it would look like a delete
    that worked. The panel stays, the reason is on screen, and the button is pressable."""
    r = out["refused"]
    assert r["requests"], "nothing was even attempted"
    assert r["label"] == "Delete project" and r["disabled"] is False
    assert "Couldn't delete" in r["note"]


@needs_node
@pytest.mark.parametrize("where", ["notAdminSent", "notAdminNotSent"])
def test_a_non_admin_gets_no_control_at_all(out, where):
    """The UI half of "admins only". Not disabled, not hidden by CSS -- absent, so there is no
    element to un-hide from a console. An opacity:0 or a class-based hide has caught this codebase
    out before. The endpoint refuses them regardless, which is the assertion at the top of this
    file."""
    assert out[where]["offered"] is False
    assert 'id="del-project"' not in out[where]["html"]
