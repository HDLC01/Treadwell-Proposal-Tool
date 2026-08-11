"""The board's first column: finished paperwork nobody has sent.

Hanz, 2026-08-11: "Under the Active Proposals we need to create a new category before sent
'Created but not Sent'."

Asked what should qualify, he chose "projects with generated files but no portal send". So a
started-and-abandoned intake form is not a proposal and must not appear; a priced, generated bid
sitting in the filing cabinet is, and is the one worth chasing.

WHY THESE ROWS ARE SYNTHESISED, AND WHAT THAT COSTS.

The board reads /api/portal/pipeline, and the portal only knows about proposals that were SENT to
it — an unsent draft has no portal row, no token, no thread and no dates. So the proxy builds the
rows itself from the drafts list it was already reading for the test flag, and shapes them like
portal rows so nothing downstream needs to know the difference. `not_sent` is the only new field.

Two consequences that each get a test below:

  * `stage()` must read `not_sent` BEFORE every portal state, because a synthesised row has none
    of them. Put the branch lower and these cards fall through to whatever the absent statuses
    happen to imply.
  * the drawer must NOT fetch. /api/portal/proposal/<id> would 404 on an id the portal has never
    heard of, and the rep would get "Error: HTTP 404" on a project that is perfectly fine.

AND THE ONE THAT DELETES CARDS SILENTLY. `group()` keeps only rows whose stage is a live column:

    items.forEach(function (p) { var s = stage(p); if (by[s]) by[s].push(p); })

so a `stage()` returning "Created but not sent" without that string being in STAGES drops every
one of these on the floor. No error, no empty column. Same pairing as the Scheduled removal (see
test_schedule_removed.py), from the opposite direction.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
CORE = FRONTEND / "js" / "crm-core.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _src(name: str) -> str:
    return (FRONTEND / "js" / name).read_text(encoding="utf-8")


def _code(name: str) -> str:
    """Source with // comment lines stripped — this file's prose quotes what it asserts."""
    return "\n".join(l for l in _src(name).splitlines() if not l.strip().startswith("//"))


def _braced(src: str, i: int, what: str) -> str:
    i = src.index("{", i)
    depth, j = 0, i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
        j += 1
    pytest.fail("unbalanced braces reading %s" % what)


def _block(name: str, fn: str) -> str:
    """The body of a top-level `function fn(...)` in js/<name>. Every source assertion is
    scoped through this: a whole-file grep for a guard is how an earlier test in this repo
    passed while one panel was broken."""
    src = _code(name)
    m = re.search(r"\n\s{2,6}(?:async\s+)?function " + re.escape(fn) + r"\s*\(", src)
    assert m, "%s() is gone from %s: these tests need rewriting, not deleting" % (fn, name)
    return _braced(src, m.end(), "%s() in %s" % (fn, name))


def _block_py(fn: str, module: str = "main") -> str:
    """The source of `def fn(...)` in backend/<module>.py, by indentation.

    Scoped for the same reason _block is: main.py is 2000+ lines and drafts.py holds two
    summary shapers with near-identical dict literals, so a whole-file grep for a field name
    cannot tell which one carries it.
    """
    src = (ROOT / "backend" / ("%s.py" % module)).read_text(encoding="utf-8")
    lines = src.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if re.match(r"\s*def %s\s*\(" % re.escape(fn), l)), None)
    assert start is not None, "%s() is gone from %s.py: rewrite these tests, don't delete" % (
        fn, module)
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = start + 1
    while end < len(lines):
        l = lines[end]
        if l.strip() and (len(l) - len(l.lstrip())) <= indent:
            break
        end += 1
    return "\n".join(lines[start:end])


def _node(expr: str):
    src = ("const C = require(%s);\nconsole.log(JSON.stringify(%s));\n"
           % (json.dumps(str(CORE)), expr))
    out = subprocess.run(["node", "-e", src], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# ── the column, and the pairing that would otherwise delete the cards ────────
@needs_node
def test_the_new_column_is_first():
    """"before sent", verbatim. It is also chronological, which is the only order this board
    reads in."""
    assert _node("C.STAGES")[0] == "Created but not sent"


@needs_node
def test_a_synthesised_row_lands_in_it():
    assert _node('C.stage({"not_sent":true})') == "Created but not sent"


@needs_node
def test_a_synthesised_row_is_not_dropped_off_the_board():
    """THE one that matters. If STAGE_CREATED were missing from STAGES while stage() still
    returned it, group() would silently discard every unsent project."""
    kept = _node('Object.values(C.group([{"not_sent":true}], C.STAGES))'
                 '.reduce((n,a)=>n+a.length,0)')
    assert kept == 1, "an unsent project is dropped off the board entirely"


@needs_node
def test_not_sent_is_read_before_every_portal_state():
    """A synthesised row has no proposal_status, deposit_status or contacts_status at all. Move
    the branch below them and these cards fall through to whatever absent implies — which is
    "Sent", the column Hanz asked us to put this one in FRONT of."""
    row = {"not_sent": True, "proposal_status": "", "deposit_status": "", "contacts_status": ""}
    assert _node("C.stage(%s)" % json.dumps(row)) == "Created but not sent"


@needs_node
def test_a_real_sent_proposal_is_untouched():
    assert _node('C.stage({"proposal_status":"sent","sent_at":"2026-08-01"})') == "Sent"


@needs_node
def test_lost_still_beats_it():
    """isLost is checked first and stays first: a bid marked lost leaves the board whatever
    else is true of it."""
    assert _node('C.stage({"not_sent":true,"proposal_status":"closed_lost"})') == "Closed lost"


@needs_node
def test_the_card_is_dated_and_sorts_by_when_it_was_last_touched():
    """Without drafted_at these cards would be dateless: stageTs blank, lastActivity null, and
    every one of them tied for last in the ordering. The label has to be its own, too —
    last_activity_at alone renders as the vague "Activity"."""
    row = {"not_sent": True, "drafted_at": "2026-08-09T10:00:00Z",
           "last_activity_at": "2026-08-09T10:00:00Z"}
    assert _node("C.stageTs(%s)" % json.dumps(row)) == "2026-08-09T10:00:00Z"
    assert _node("C.lastActivity(%s)" % json.dumps(row))["label"] == "Created"
    assert _node("C.activityTs(%s)" % json.dumps(row)) == "2026-08-09T10:00:00Z"


@needs_node
def test_drafted_at_loses_every_tie_to_a_real_event():
    """It is the earliest thing that can happen to a project, so if a real portal stamp shares
    the timestamp the real one has to win the card's activity line."""
    row = {"drafted_at": "2026-08-09T10:00:00Z", "sent_at": "2026-08-09T10:00:00Z"}
    assert _node("C.lastActivity(%s)" % json.dumps(row))["label"] == "Sent"


# ── the money on the card ────────────────────────────────────────────────────
@needs_node
@pytest.mark.parametrize("row,expect,why", [
    ({"approved_total": 41250}, 41250, "a sent proposal: the figure the customer was given"),
    ({"bid_total": 41250}, 41250, "an unsent draft: the figure the Proposals Database shows"),
    ({"approved_total": 900, "bid_total": 1}, 900, "approved wins when both are present"),
    ({}, None, "nothing to show is not zero"),
    ({"approved_total": None, "bid_total": 41250}, 41250, "a null approved must not mask the bid"),
])
def test_cardTotal_reads_both_sources(row, expect, why):
    assert _node("C.cardTotal(%s)" % json.dumps(row)) == expect, why


def test_the_unsent_figure_is_not_called_approved():
    """Naming it approved_total would have been one field fewer and a lie on every card in the
    first column: nobody has approved these. The pipeline sends bid_total instead, so the word
    "approved" never attaches to a bid the customer has not seen."""
    body = _block_py("_not_sent_rows")
    assert '"bid_total"' in body, "the synthesised row no longer carries bid_total"
    assert '"approved_total"' not in body, (
        "an unsent draft is being sent as approved_total, which prints 'approved' money "
        "for a proposal nobody has received")


def test_both_renderers_and_the_sort_read_the_same_accessor():
    """Three places print or order that number. Let one read approved_total directly and the
    first column shows blank money in the board, or in the table, or sorts to the bottom —
    depending which one you missed."""
    code = _code("portal.js")
    assert code.count("cardTotal(p)") >= 2, "a renderer still reads approved_total directly"
    for fn in ("kanbanHtml", "tableHtml"):
        assert "cardTotal(p)" in _block("portal.js", fn), "%s does not use cardTotal" % fn
    total = _code("crm-core.js")
    i = total.index("total: function (dir)")
    assert "cardTotal(x)" in total[i:i + 400], "the Value sort still reads approved_total"


# ── the proxy: which drafts become cards ─────────────────────────────────────
def _row(pid="p1", **kw):
    base = {"proposal_id": pid, "project_name": "Oak Grove", "customer_email": "dave@x.com",
            "proposal_status": "sent", "deposit_status": "pending",
            "contacts_status": "pending", "unread": 0, "sent_at": "2026-08-01T12:00:00+00:00"}
    base.update(kw)
    return base


def _draft(did="d1", **kw):
    """A drafts-list summary shaped the way _build_summaries actually returns one."""
    base = {"id": did, "project_name": "Nearman Creek", "has_files": True, "archived": False,
            "is_test": None, "owner_email": "kyle@wetreadwell.com", "assigned_estimator": None,
            "contact_email": "gc@example.com", "total": 41250,
            "updated_at": "2026-08-09T10:00:00+00:00", "work_type": "epoxy", "sent_revision": 0}
    base.update(kw)
    return base


def _wire(monkeypatch, rows, projects):
    monkeypatch.setattr(main, "_portal",
                        lambda p, m="GET", b=None: {"ok": True, "proposals": rows})
    monkeypatch.setattr(main.drafts, "list_drafts", lambda *a, **k: projects)


def _pipeline():
    r = client.get("/api/portal/pipeline")
    assert r.status_code == 200, r.text
    return {p["proposal_id"]: p for p in r.json()["proposals"]}


def test_a_generated_draft_with_no_portal_row_becomes_a_card(monkeypatch):
    _wire(monkeypatch, [], [_draft("d1")])
    out = _pipeline()
    assert out["d1"]["not_sent"] is True
    assert out["d1"]["project_name"] == "Nearman Creek"
    assert out["d1"]["customer_email"] == "gc@example.com"
    assert out["d1"]["bid_total"] == 41250
    assert out["d1"]["drafted_at"] == "2026-08-09T10:00:00+00:00"


def test_a_draft_with_no_generated_files_is_not_a_proposal(monkeypatch):
    """Hanz's line was "projects with generated files". Every abandoned intake form in the
    database would otherwise arrive on the board as work in progress."""
    _wire(monkeypatch, [], [_draft("d1", has_files=False)])
    assert _pipeline() == {}


def test_a_sent_project_is_not_listed_twice(monkeypatch):
    """The portal's row is the real one — it has the dates, the thread and the deposit. A draft
    keeps its generate_result forever after sending, so without this guard every sent proposal
    would appear a second time in the first column."""
    _wire(monkeypatch, [_row("d1")], [_draft("d1")])
    out = _pipeline()
    assert len(out) == 1
    assert "not_sent" not in out["d1"]
    assert out["d1"]["proposal_status"] == "sent"


def test_an_archived_draft_stays_filed(monkeypatch):
    """Archiving is how staff take a project off their list. Resurrecting it on the board would
    make the archive button look broken."""
    _wire(monkeypatch, [], [_draft("d1", archived=True)])
    assert _pipeline() == {}


def test_the_test_flag_carries_so_the_card_lands_on_the_right_tab(monkeypatch):
    """These rows never went through the stamping loop — they ARE the drafts list. Drop the flag
    and Kyle's scratch bids appear under Active among customer work, which is the exact mixing
    Hanz asked to stop."""
    _wire(monkeypatch, [], [_draft("d1", is_test=True), _draft("d2", is_test=False),
                            _draft("d3", is_test=None)])
    out = _pipeline()
    assert out["d1"]["is_test"] is True
    assert out["d2"]["is_test"] is False
    assert out["d3"]["is_test"] is None


def test_the_estimator_falls_back_to_whoever_priced_it(monkeypatch):
    """Nobody is assigned until the project is sent, so with only assigned_estimator every card
    in this column would read "—". The owner is the person to ask about it."""
    _wire(monkeypatch, [], [_draft("d1", assigned_estimator=None),
                            _draft("d2", assigned_estimator="will@wetreadwell.com")])
    out = _pipeline()
    assert out["d1"]["estimator_email"] == "kyle@wetreadwell.com"
    assert out["d2"]["assigned_estimator"] == "will@wetreadwell.com"


@needs_node
def test_the_estimator_fallback_is_the_one_the_board_reads(monkeypatch):
    """Asserting the field is set proves nothing unless estimatorOf consults it."""
    assert _node('C.estimatorOf({"estimator_email":"kyle@wetreadwell.com"})') \
        == "kyle@wetreadwell.com"
    assert _node('C.isAssigned({"estimator_email":"kyle@wetreadwell.com"})') is False, (
        "an owner fallback is being shown as an assignment, so the ? marker disappears")


def test_an_unreadable_drafts_list_costs_the_column_not_the_board(monkeypatch):
    """Same posture as the test flag: the pipeline is the page."""
    monkeypatch.setattr(main, "_portal",
                        lambda p, m="GET", b=None: {"ok": True, "proposals": [_row("p1")]})
    monkeypatch.setattr(main.drafts, "list_drafts",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("postgrest down")))
    out = _pipeline()
    assert out["p1"]["project_name"] == "Oak Grove"
    assert len(out) == 1


def test_it_is_still_one_drafts_read_for_the_whole_board(monkeypatch):
    """The synthesis reuses the list that was already being read for the test flag. A second
    read here would double the cost of a poll that runs every 25 seconds."""
    calls = []
    monkeypatch.setattr(main, "_portal", lambda p, m="GET", b=None: {"ok": True, "proposals": []})

    def list_drafts(*a, **k):
        calls.append(1)
        return [_draft("d%d" % i) for i in range(20)]
    monkeypatch.setattr(main.drafts, "list_drafts", list_drafts)
    assert len(_pipeline()) == 20
    assert len(calls) == 1, "the drafts list is read %d times per board load" % len(calls)


# ── the drafts summary has to carry the two new fields ───────────────────────
def test_the_summary_reports_whether_generate_has_run():
    """has_files is selected as one scalar out of generate_result, not the object: that blob
    carries three download URLs and a totals map, and this list is read 300 rows at a time on
    every Projects page load."""
    cols = _block_py("_build_summaries", module="drafts")
    assert "has_files:data->generate_result->>work_type" in cols, (
        "the cheap existence probe is gone; check it was not replaced by selecting the blob")
    assert "data->generate_result\"" not in cols and "data->>generate_result" not in cols, (
        "the whole generate_result object is being selected into the list payload")
    assert '"has_files": bool(' in cols, "has_files is not coerced to a boolean"
    assert "contact_email:data->>contact_email" in cols


def test_the_fallback_shaper_reports_them_too():
    """_build_summaries falls back to a full-blob read on any PostgREST quirk. If only the fast
    path knew about these fields, the first column would silently empty out in exactly the
    conditions where somebody is already debugging something else."""
    body = _block_py("_summary", module="drafts")
    assert '"has_files": bool(data.get("generate_result"))' in body
    assert '"contact_email": data.get("contact_email")' in body


def test_the_two_shapers_agree_about_what_has_files_means():
    """One reads a jsonb scalar, the other a Python dict, and they must answer the same
    question — "has Generate ever run here" — or the column's membership would depend on which
    read path served the request."""
    import drafts
    assert drafts._summary({"id": "x", "data": {"generate_result": {"work_type": "epoxy"}}})[
        "has_files"] is True
    assert drafts._summary({"id": "x", "data": {}})["has_files"] is False
    assert drafts._summary({"id": "x", "data": {"generate_result": {}}})["has_files"] is False, (
        "an empty generate_result counts as generated on one path and not the other")


# ── the drawer must not fetch a proposal the portal has never heard of ───────
def test_clicking_the_card_does_not_ask_the_portal_for_a_row_that_does_not_exist():
    """/api/portal/proposal/<id> 404s on a synthesised id. Without this intercept the rep gets
    "Error: HTTP 404" on a project that is perfectly fine, and it repeats every 12s poll."""
    body = _block("portal.js", "openDetail")
    assert "renderNotSent" in body, "openDetail has no not-sent branch"
    guard = body.index("renderNotSent")
    fetch = body.index('api("/api/portal/proposal/')
    assert guard < fetch, "the drawer fetches before it checks, so the 404 still happens"
    assert "row.not_sent" in body, "the branch is not keyed on not_sent"
    assert re.search(r"if \(row && row\.not_sent\) \{[^}]*return", body), (
        "the not-sent branch does not return, so it falls through to the fetch anyway")


def test_the_not_sent_drawer_is_signature_guarded():
    """openDetail runs again on every 12s drawer poll. An unguarded innerHTML here rebuilds the
    panel four times a minute — the same blink Hanz reported on the board and the chat."""
    body = _block("portal.js", "renderNotSent")
    assert "DRAWER_SIG" in body, "renderNotSent has no signature guard"
    assert body.index("DRAWER_SIG) return") < body.index("innerHTML"), (
        "the guard runs after the repaint, so it guards nothing")


def test_the_not_sent_drawer_offers_the_action_that_moves_the_project_on():
    """The column exists so somebody sends these. A panel that only explains the state and
    leaves the rep to navigate by hand would be the report without the fix."""
    body = _block("portal.js", "renderNotSent")
    assert "/done.html?d=" in body and "files=1" in body, "no route to the Files page"
    assert "dclose" in body, "the panel cannot be closed"
    assert "dtabs" not in body, (
        "the tab strip is rendered for a project whose six other tabs are all empty")


def test_the_not_sent_drawer_uses_buttons_the_page_actually_styles():
    """.btn is written for <button> (no display, no text-decoration reset), so an <a class=btn>
    renders as underlined inline text. .drow and .ghost do not exist on this page at all."""
    body = _block("portal.js", "renderNotSent")
    assert "btn btn-p" in body and "btn btn-s" in body
    for absent in ('class="btn ghost"', "drow"):
        assert absent not in body, "%s is not a class this page defines" % absent


# ── the chat bubble, simplified (Hanz, 2026-08-11) ───────────────────────────
def test_the_crm_bubble_is_contents_date_and_whether_it_came_by_email():
    """"can we simplify it to just the reply contents and the date? just specify if its from
    email". The TREADWELL / CUSTOMER line above every bubble restated what the side and colour
    already said: red and right-aligned is us, grey and left is them.

    The portal's renderMsg is kept in the same shape (see the portal repo's
    test_signature_and_bubble.py) — the two views are meant to be one conversation.
    """
    body = _block("portal.js", "msgHtml")
    assert '"Treadwell" : "Customer"' not in body, (
        "the unconditional TREADWELL / CUSTOMER label is back on every bubble")
    assert "via-email" in body, "an emailed reply is no longer marked as one"
    assert 'class="mbody"' in body, "the text is not in the element pre-wrap is written for"
    # A `who` line DOES render again, but only for a customer message on a proposal with more
    # than one recipient — see test_per_recipient_attribution.py. That is a different claim from
    # the one Hanz made: with a single contact it still says nothing the side does not.
    assert "DETAIL_RECIPIENTS" in body and "length > 1" in body, (
        "the author name is no longer gated on there being more than one recipient")


def test_the_emailed_reply_keeps_its_line_breaks():
    """Stripping the sender's signature server-side is only half the fix. Without pre-wrap a
    multi-paragraph customer email still renders as one run of text."""
    page = (FRONTEND / "portal.html").read_text(encoding="utf-8")
    assert re.search(r"\.msg \.mbody \{[^}]*white-space:pre-wrap", page), (
        "the message body does not preserve the sender's line breaks")
    assert re.search(r"\.msg \.mbody \{[^}]*overflow-wrap:anywhere", page), (
        "a long URL can push the bubble past its max-width")
    # `.msg .who` came BACK on 2026-08-11 for the multi-recipient case. What must stay gone is
    # the unconditional label in the markup, which the test above covers.
    assert ".msg .who {" in page, "the conditional author name has no styling"
