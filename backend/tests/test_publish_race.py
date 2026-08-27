"""Publishing must not race the autosave, and an option that appears nowhere must say so.

THE INCIDENT, 2026-08-13. Hanz, on a resend of the test project "Hanz Company 123":

    "I have made changes and resent the proposal but the new proposal does not appear
     correctly. There are two options but the PDF Shows one. This side bar, I chose Room 1
     as base bid and Epoxy as option but it doesnt show in the proposal"

Two independent defects, stacked, which is why it read as one incomprehensible bug.

DEFECT 1 — THE SEND RACED THE SAVE. Checked against the production rows: revision 2 (created
16:00:28, the one the portal pins the customer's view to) carried `base_tab_id = "Epoxy"` and
rooms of Epoxy $29,942 base + Room 1 $15,801 option. The live draft, updated 16:02:14, carried
what he had actually chosen: Room 1 as base, Epoxy as the option. `/api/portal/publish`
snapshots the SERVER's copy of the draft (`create_revision`), and the debounced autosave
(2.5s) had not landed — so the portal faithfully showed the version from before his change,
while the PDF (regenerated from the request body, i.e. the live state) showed the version
after. Both surfaces were internally correct. Neither was what he meant to send.

`putDraft` returned nothing, so no caller COULD wait for a save. `TW.flushState()` now forces
the pending write out immediately and resolves only once the server has it; the Done page
awaits it before publishing and refuses to send if it fails. `publishDrift` covers what a
flush cannot — a second tab, another device, a colleague editing mid-send — by comparing the
digest of what the server actually snapshotted against what the page is showing.

DEFECT 2 — AN OPTION MARKED BUT NOT SHOWN IS INERT AND SILENT. Epoxy had "Show as a proposal
option" ticked and the nested "Show in proposal" un-ticked. `rebuildPricing` drops
`show === false` rows, so the option reached NEITHER the PDF NOR the portal. Worse, the
handler only defaulted an UNDEFINED `show`, so an option un-shown once stayed un-shown when
re-enabled and ticking the outer box did nothing at all, forever, with no feedback.

EXECUTED, NOT GREPPED. Ordering ("did the save finish before the publish began?") and reset
semantics ("does re-ticking restore show?") are behaviour. The STAGE_CREATED outage the day
before proved what source-text assertions are worth: the string was present, the identifier
was unbound, and the board was dead.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "publish-race-harness.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── defect 1: the race ───────────────────────────────────────────────────────
@needs_node
def test_a_draft_write_can_be_awaited_at_all(ran):
    """The root cause. `putDraft` fired the PUT and returned undefined, so no caller could
    know whether the server had the edit — which is why publishing could not wait."""
    assert ran["putDraftReturnsAPromise"], "putDraft is fire-and-forget again"
    assert ran["exportsFlushState"], "TW.flushState is not exported"


@needs_node
def test_flush_forces_the_pending_save_out_immediately(ran):
    """It must not wait out the 2.5s debounce. Somebody who edits and clicks Send in the same
    breath is the normal case — and the sent blob has to be the EDITED one."""
    f = ran["forcedImmediately"]
    assert f["putsBefore"] == 0 and f["putsAfterCall"] == 1, f
    assert f["sentBase"] == "Copy1", (
        "the write that flush forced out did not carry the pending edit: %s" % f)


@needs_node
def test_flush_does_not_resolve_until_the_write_LANDS(ran):
    """THE test. Resolving early would leave the publish exactly as racy as before, while
    looking fixed — the failure mode is invisible and reaches a customer."""
    a = ran["awaitsTheWrite"]
    assert a["resolvedWhileInFlight"] is False, (
        "flushState resolved while the save was still in flight — the race is still open")
    assert a["finalResult"] is True


@needs_node
def test_a_failed_write_reports_false_so_the_send_can_be_refused(ran):
    """Publishing after a failed save would pin the customer to a stale revision. Better to
    refuse and say so than to send the wrong price."""
    assert ran["failedWriteIsFalse"] is False


@needs_node
def test_nothing_dirty_is_still_a_yes(ran):
    """"The server is in sync" is the honest answer when there was nothing to write, and it
    must not cost a redundant PUT on every send."""
    n = ran["nothingPending"]
    assert n["result"] is True and n["puts"] == 0, n


@needs_node
def test_the_done_page_flushes_BEFORE_it_publishes_and_refuses_on_failure(ran):
    d = ran["donePage"]
    assert d["flushesBeforePublish"], "the publish call does not wait for the flush"
    assert d["refusesOnFailedFlush"], "a failed flush still lets the send through"
    assert d["hasDriftCheck"], "no post-send comparison against what the server snapshotted"


# ── defect 1b: the drift warning, for what a flush cannot fix ────────────────
@needs_node
def test_the_drift_warning_reproduces_the_real_incident(ran):
    """The exact numbers from 2026-08-13: the server sent Epoxy at $29,942 while the page
    showed Room 1 at $15,801. The estimator must be told WHICH pricing went out — a bare
    "something differs" leaves them to guess, and the portal is already pinned."""
    msg = ran["drift"]["incident"]
    assert "Epoxy" in msg and "Room 1" in msg, msg
    assert "29942" in msg.replace(",", "") and "15801" in msg.replace(",", ""), msg


@needs_node
def test_the_warning_stays_quiet_when_the_send_matches(ran):
    """A warning on every successful send is a warning nobody reads."""
    assert ran["drift"]["agree"] == ""


@needs_node
def test_an_older_backend_produces_no_warning(ran):
    """The digest is new. A deploy where the page is ahead of the API must not cry wolf."""
    assert ran["drift"]["noSnapshot"] == ""


@needs_node
def test_a_differing_option_count_is_reported(ran):
    """The half of his complaint about the PDF: options that did not travel."""
    assert "2 options" in ran["drift"]["optCount"], ran["drift"]["optCount"]


@needs_node
def test_a_deliberately_hidden_option_is_not_drift(ran):
    """Both sides must count PICKABLE options the same way. The server applies the `show` rule;
    if the page counted every option regardless, every send carrying a hidden option would
    warn — and a warning that fires on correct sends is one nobody reads. A mutation removing
    the page's `show !== false` filter survived until this case existed."""
    assert ran["drift"]["hiddenOption"] == "", ran["drift"]["hiddenOption"]


@needs_node
def test_sub_cent_rounding_is_not_drift(ran):
    """Floating point must not manufacture a warning: 15801.004 and 15801 are the same money."""
    assert ran["drift"]["rounding"] == ""


# ── defect 1c: the two halves of one revision ────────────────────────────────
# The morning's fix pinned the customer's page to a revision. It did not make the revision
# self-consistent: the page reads `rooms`, the customer's PDF is re-rendered from
# `proposal_payload`, and only the Proposal step's Continue writes the second one. Hanz,
# 2026-08-13: "I tried to resend and inversed the bids it doesnt update in the portal the new PDF".
# `syncPayloadPricing` stops NEW revisions drifting; these cases are the safety net for the ones
# already in the database, and for any path we haven't thought of.
@needs_node
def test_a_stale_document_inside_the_sent_revision_is_reported(ran):
    """His exact case: the page half says Epoxy $18,670, the document half still says Polish
    $13,265. Both numbers come from the SERVER's snapshot, so this fires no matter which tab,
    device or colleague caused it — and no matter what this browser's local state says."""
    msg = ran["drift"]["docStale"]
    assert "PDF" in msg, msg
    assert "Polish" in msg and "Epoxy" in msg, msg
    assert "13265" in msg.replace(",", "") and "18670" in msg.replace(",", ""), msg
    # It must still say how to fix it, and it now names the ONE control that does it. The old
    # wording ("Open the Proposal step, press Continue, then re-send") sent the estimator on a
    # hunt across two pages; the teammate who hit this at 11:47pm on 2026-08-26 could not tell
    # what it meant. See test_stale_document_gate.py for the button it points at.
    assert "Update the PDF" in msg, "the warning must name the control that fixes it"


@needs_node
def test_a_consistent_revision_says_nothing_about_the_document(ran):
    assert ran["drift"]["docAgrees"] == ""


@needs_node
def test_a_base_only_document_is_not_reported_as_drift(ran):
    """Base-only proposals have no base ROOM, so `doc_base_label` is null and the price comes
    from the payload's own lump sum. Comparing a null label against a real one would warn on
    every single-system send — the most common shape this tool produces."""
    assert ran["drift"]["baseOnlyAgrees"] == "", ran["drift"]["baseOnlyAgrees"]


@needs_node
def test_a_snapshot_from_the_previous_build_stays_quiet(ran):
    """Revisions already in the database carry no doc_* keys. Absent evidence is not evidence of
    drift — and every one of these snapshots predates the fix, so warning on all of them would
    train the estimators to ignore the banner."""
    assert ran["drift"]["legacySnapshot"] == ""
    assert ran["drift"]["noDocument"] == "", "has_document false must be treated as unknown"


@needs_node
def test_document_price_drift_alone_is_enough(ran):
    """A re-price without a Continue keeps the base NAME and changes the money — the version of
    this bug that costs the most and shows the least."""
    msg = ran["drift"]["docPriceOnly"]
    assert "PDF" in msg and "17110" in msg.replace(",", ""), msg


@needs_node
def test_document_option_count_drift_is_reported(ran):
    """An option added on the page that never reached the document: the customer can't pick it,
    and the approval total they see excludes work we intended to offer."""
    msg = ran["drift"]["docOptionCount"]
    assert "PDF" in msg and "1 option" in msg, msg


# ── defect 2: the inert option, in BOTH strips ──────────────────────────────
@needs_node
@pytest.mark.parametrize("strip", ["proposalStrip", "estimateStrip"])
def test_re_ticking_an_option_restores_show(ran, strip):
    """The silent-forever bug. `if (o.show === undefined) o.show = true` preserved a stale
    false, so ticking "Show as a proposal option" on a previously-unshown option did nothing
    anywhere — no PDF line, no portal option, no message."""
    s = ran[strip]
    assert s["resetsShow"], (
        "%s still only defaults an undefined show, so re-enabling an option leaves it inert"
        % strip)
    assert s["stillDefaultsPriceMode"], "the price_mode default was lost in the same edit"


@needs_node
@pytest.mark.parametrize("strip", ["proposalStrip", "estimateStrip"])
def test_an_option_that_appears_nowhere_says_so(ran, strip):
    """Marked as an option, not shown: it reaches neither document nor portal. That was
    completely silent, and a ticked box reads as done."""
    assert ran[strip]["hasWarning"], (
        "%s renders no warning for is_option && !show" % strip)


@needs_node
@pytest.mark.parametrize("strip", ["proposalStrip", "estimateStrip"])
def test_the_show_rule_that_makes_it_inert_still_exists(ran, strip):
    """Guard against "fixing" this by silently including unshown options — that would put a
    price in front of a customer that the estimator deliberately hid."""
    assert ran[strip]["dropsUnshownFromRooms"]


def test_both_warnings_are_styled_as_warnings():
    """Amber, not the grey hint colour they sit among. A misconfiguration that looks like one
    more piece of help text is one nobody acts on."""
    est = (FRONTEND / "estimate-review.html").read_text(encoding="utf-8")
    pro = (FRONTEND / "proposal-review.html").read_text(encoding="utf-8")
    done = (FRONTEND / "done.html").read_text(encoding="utf-8")
    assert ".bb-inert" in est and "#7a5c00" in est
    assert ".pr-inert-warn" in pro and "#7a5c00" in pro
    assert ".portal-drift" in done and "#7a5c00" in done


# ── the server half: the digest of what was actually snapshotted ─────────────
# Real shapes from the incident, read out of production: revision 2 is what the portal pinned,
# `LIVE` is what his browser held two minutes later.
REV2 = {"base_tab_id": "Epoxy", "proposal_lump_sum": 29942,
        "rooms": [{"name": "Epoxy", "is_base": True, "bid": {"total": 29942}},
                  {"name": "Room 1", "is_base": False, "bid": {"total": 15801}, "show": True}]}
LIVE = {"base_tab_id": "Copy1", "proposal_lump_sum": 15801,
        "rooms": [{"name": "Room 1", "is_base": True, "bid": {"total": 15801}},
                  {"name": "Epoxy", "is_base": False, "bid": {"total": 29942}, "show": False}]}


def test_the_digest_names_the_base_the_customer_will_see():
    """`base_tab_id` alone is a sheet id ("Copy1") and means nothing to a person. The digest
    carries the ROOM NAME too, so the warning can say "it sent Epoxy, not Room 1"."""
    import main
    d = main._publish_digest(REV2)
    assert d["base_label"] == "Epoxy" and d["lump_sum"] == 29942
    live = main._publish_digest(LIVE)
    assert live["base_label"] == "Room 1" and live["base_tab_id"] == "Copy1"


def test_the_digest_counts_only_options_a_customer_can_pick():
    """Same `show` rule as the portal and the document, so the count can never disagree with
    the proposal. In the incident LIVE has an Epoxy option that is marked but not shown — it
    counts as zero, which is precisely the second defect made visible."""
    import main
    assert main._publish_digest(REV2)["option_count"] == 1
    assert main._publish_digest(LIVE)["option_count"] == 0


def test_the_digest_never_raises_on_a_malformed_blob():
    """It runs inside a successful publish. A KeyError here would turn a delivered proposal
    into a 500 and tell the estimator the send failed when the customer already has it."""
    import main
    # A NON-ITERABLE rooms value is the case that distinguishes the isinstance guard from a
    # bare truthiness check: `for r in 5` raises TypeError, and the downstream isinstance
    # checks never get the chance to save it. Without this input the guard was untested and a
    # mutation to `rooms or []` survived.
    # The document half takes the same treatment: proposal_payload is a nested blob written by a
    # browser, so every shape below has to fall through to "we can't read it" rather than raise.
    for blob in ({}, {"rooms": "not a list"}, {"rooms": [None, 7, {}]}, {"rooms": 5},
                 {"rooms": {"a": 1}}, {"rooms": True},
                 {"rooms": [{"is_base": True}], "proposal_lump_sum": None},
                 {"proposal_payload": "nope"}, {"proposal_payload": {}},
                 {"proposal_payload": {"values": 5}},
                 {"proposal_payload": {"values": {"rooms": "not a list"}}},
                 {"proposal_payload": {"values": {"rooms": [{"is_base": True,
                                                             "bid": "not a dict"}]}}}):
        d = main._publish_digest(blob)
        assert set(d) == {"base_tab_id", "base_label", "lump_sum", "option_count",
                          "has_document", "doc_base_label", "doc_lump_sum", "doc_option_count"}
        assert isinstance(d["option_count"], int)
        assert isinstance(d["has_document"], bool)


# ── the document half of the digest ──────────────────────────────────────────
# The 2026-08-13 evening report. Staff inverted the base bid — Epoxy $18,670 became the base,
# Polish $13,265 the option — and re-sent. The page updated; the customer's PDF did not, because
# it is re-rendered from `proposal_payload`, which only the Proposal step's Continue rewrites.
# This is the blob a resend snapshotted: top half new, document half two edits old.
#
# Note WHERE the document's rooms live: `proposal_payload["rooms"]` is `GenerateIn.rooms`, the
# field `fill_proposal` renders the price table from. `values` also carries a copy (it is a spread
# of the whole page state), but the renderer never reads it, so the digest must not either.
DOC_ROOMS = [{"name": "Polish", "is_base": True, "bid": {"total": 13265}},
             {"name": "Epoxy", "is_base": False, "bid": {"total": 18670}, "show": True}]
DRIFTED = {
    "base_tab_id": "Epoxy", "proposal_lump_sum": 18670,
    "rooms": [{"name": "Epoxy", "is_base": True, "bid": {"total": 18670}},
              {"name": "Polish", "is_base": False, "bid": {"total": 13265}, "show": True}],
    "proposal_payload": {"rooms": DOC_ROOMS,
                         "values": {"proposal_lump_sum": 13265, "rooms": DOC_ROOMS}},
}


def test_the_digest_reads_the_document_that_will_actually_render():
    """One revision, two halves. Until this existed the digest looked only at the half that was
    already correct, so the drift check it feeds was structurally incapable of catching the
    complaint it was built for."""
    import main
    d = main._publish_digest(DRIFTED)
    assert d["base_label"] == "Epoxy" and d["lump_sum"] == 18670       # the page
    assert d["has_document"] is True
    assert d["doc_base_label"] == "Polish" and d["doc_lump_sum"] == 13265   # the PDF
    assert d["doc_option_count"] == 1


def test_a_consistent_payload_digests_to_matching_halves():
    """The state after a Continue — and after `syncPayloadPricing`, the state after a base flip
    too. Both halves must read the same or the estimator gets a warning on a correct send."""
    import main
    fixed = [{"name": "Epoxy", "is_base": True, "bid": {"total": 18670}},
             {"name": "Polish", "is_base": False, "bid": {"total": 13265}, "show": True}]
    good = {**DRIFTED, "proposal_payload": {
        "rooms": fixed, "values": {"proposal_lump_sum": 18670, "rooms": fixed}}}
    d = main._publish_digest(good)
    assert (d["doc_base_label"], d["doc_lump_sum"], d["doc_option_count"]) == \
           (d["base_label"], d["lump_sum"], d["option_count"])


def test_a_base_only_document_falls_back_to_the_payloads_lump_sum():
    """Single-system proposals carry no base ROOM at all. Reading only rooms[is_base] would make
    every one of them look like a document with no price — a warning on the most common shape
    this tool produces."""
    import main
    d = main._publish_digest({
        "base_tab_id": "Epoxy", "proposal_lump_sum": 18670,
        "rooms": [], "proposal_payload": {"values": {"proposal_lump_sum": 18670}}})
    assert d["has_document"] is True
    assert d["doc_base_label"] is None
    assert d["doc_lump_sum"] == 18670
    assert d["doc_option_count"] == 0


def test_a_draft_with_no_payload_reports_no_document():
    """Nothing has been generated yet, so there is nothing to be stale. `has_document` false is
    what keeps the page's warning silent instead of guessing."""
    import main
    d = main._publish_digest({"rooms": [{"name": "Epoxy", "is_base": True,
                                         "bid": {"total": 18670}}]})
    assert d["has_document"] is False
    assert d["doc_base_label"] is None and d["doc_lump_sum"] is None
    assert d["doc_option_count"] is None


def test_the_document_half_counts_options_the_same_way():
    """Same `show is not False` rule as the page half. Two different counting rules would make
    every proposal with a hidden option look drifted."""
    import main
    d = main._publish_digest({**DRIFTED, "proposal_payload": {
        "rooms": [{"name": "Epoxy", "is_base": True, "bid": {"total": 18670}},
                  {"name": "Polish", "is_base": False, "bid": {"total": 13265}, "show": False},
                  {"name": "Seal", "is_base": False, "bid": {"total": 4000}}],
        "values": {"proposal_lump_sum": 18670}}})
    assert d["doc_option_count"] == 1      # Seal (no key = shown), not Polish (explicitly hidden)


def test_the_document_half_reads_the_field_the_RENDERER_reads():
    """`GenerateIn.rooms` is what fills the price table; `values.rooms` is an inert echo of the
    page state that travels alongside it. Reading the echo would report the pricing the estimator
    was LOOKING at rather than the pricing the customer's PDF prints — the same class of mistake
    as the bug this digest exists to catch."""
    import main
    d = main._publish_digest({
        "base_tab_id": "Epoxy", "proposal_lump_sum": 18670,
        "rooms": [{"name": "Epoxy", "is_base": True, "bid": {"total": 18670}}],
        "proposal_payload": {
            "rooms": [{"name": "Polish", "is_base": True, "bid": {"total": 13265}}],
            "values": {"proposal_lump_sum": 18670,
                       "rooms": [{"name": "Epoxy", "is_base": True,
                                  "bid": {"total": 18670}}]}}})
    assert d["doc_base_label"] == "Polish", "the digest followed values.rooms, not the renderer's"
    assert d["doc_lump_sum"] == 13265


def test_the_digest_holds_only_primitives():
    """It is echoed into an API response. Reaching for a nested blob here would leak internal
    pricing structure to any caller."""
    import main
    for v in main._publish_digest(REV2).values():
        assert v is None or isinstance(v, (str, int, float)), v


def test_the_publish_response_ECHOES_what_it_snapshotted(monkeypatch):
    """The wiring, not the helper. `_publish_digest` being correct is worthless if the route
    never returns it — the page would silently lose its only cross-check against a stale send,
    and a mutation deleting the echo survived until this existed."""
    import main
    from fastapi.testclient import TestClient

    sent = {"base_tab_id": "Copy1", "proposal_lump_sum": 15801,
            "rooms": [{"name": "Room 1", "is_base": True, "bid": {"total": 15801}},
                      {"name": "Epoxy", "is_base": False, "bid": {"total": 29942},
                       "show": True}]}
    monkeypatch.setattr(main.drafts, "load_draft", lambda i: {"id": i, "data": sent})
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: {"email": e, "role": "admin"})
    monkeypatch.setattr(main.drafts, "create_revision", lambda did, data, by=None: 7)
    monkeypatch.setattr(main.drafts, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(main, "_portal", lambda p, method="GET", body=None: {
        "ok": True, "url": "https://portal/x", "customer_email": "c@x.com"})

    r = TestClient(main.app).post("/api/portal/publish?draft_id=d1",
                                  json={"assigned_estimator": "kyle@wetreadwell.com"})
    assert r.status_code == 200, r.text
    snap = r.json().get("sent_snapshot")
    assert snap, "the publish response carries no sent_snapshot"
    assert snap["base_label"] == "Room 1" and snap["lump_sum"] == 15801
    assert snap["option_count"] == 1
    assert r.json()["revision_no"] == 7


def test_the_echo_never_overwrites_what_the_portal_returned(monkeypatch):
    """`setdefault`, not assignment: if the portal itself ever returns these keys they are the
    authority, and clobbering them would hide a disagreement rather than surface one."""
    import main
    from fastapi.testclient import TestClient

    monkeypatch.setattr(main.drafts, "load_draft", lambda i: {"id": i, "data": {}})
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: {"email": e, "role": "admin"})
    monkeypatch.setattr(main.drafts, "create_revision", lambda did, data, by=None: 3)
    monkeypatch.setattr(main.drafts, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(main, "_portal", lambda p, method="GET", body=None: {
        "ok": True, "revision_no": 99, "sent_snapshot": {"from": "the portal"}})

    j = TestClient(main.app).post("/api/portal/publish?draft_id=d1",
                                  json={"assigned_estimator": "kyle@wetreadwell.com"}).json()
    assert j["revision_no"] == 99 and j["sent_snapshot"] == {"from": "the portal"}


# ── 2026-08-27: the drift is now a REFUSAL, not an apology ────────────────────
# Everything above this line was built on the assumption that a drifted send is worth warning
# about. It is not. A teammate, 23:47:
#
#     "I revised a proposal and am getting the error message in yellow below. I think it's
#      sending an outdated proposal."
#
# He was right, and the yellow message was the tool agreeing with him AFTER the fact.
# `sent_snapshot` had the whole answer — the customer's PDF said $29,104 where his screen said
# $27,721, and offered two options where his screen offered none — and the publish minted the
# revision, wrote the portal row, sent the email, and returned 200 anyway. The estimator read
# "Sent".
#
# That is the attachment bug wearing different clothes: detect, commit, report success. So the
# order changed. The digest is computed BEFORE `create_revision`, and a document half that
# disagrees with its portal half now stops the send with nothing written.
#
# THESE TESTS DRIVE THE ROUTE, not the helper alone. The helper returning a correct refusal is
# worthless if the route computes it after the email has gone — which is precisely the bug — so
# every case below counts the side effects.
REPORTED = {
    "base_tab_id": "Epoxy", "proposal_lump_sum": 27721,
    "rooms": [{"name": "Epoxy", "is_base": True, "bid": {"total": 27721}}],
    "proposal_payload": {
        "rooms": [{"name": "Epoxy", "is_base": True, "bid": {"total": 29104}},
                  {"name": "Polish", "is_base": False, "bid": {"total": 9000}, "show": True},
                  {"name": "Seal", "is_base": False, "bid": {"total": 4000}, "show": True}],
        "values": {"proposal_lump_sum": 29104}},
}
CLEAN = {
    "base_tab_id": "Epoxy", "proposal_lump_sum": 27721,
    "rooms": [{"name": "Epoxy", "is_base": True, "bid": {"total": 27721}},
              {"name": "Polish", "is_base": False, "bid": {"total": 9000}, "show": True}],
    "proposal_payload": {
        "rooms": [{"name": "Epoxy", "is_base": True, "bid": {"total": 27721}},
                  {"name": "Polish", "is_base": False, "bid": {"total": 9000}, "show": True}],
        "values": {"proposal_lump_sum": 27721}},
}


class _Publish:
    """A publish route with every write instrumented and nothing real behind it.

    `writes` is the point. A refusal that logs beautifully and still mints a revision, or still
    reaches `/api/admin/publish` (which writes the portal row AND sends the customer's email), is
    the bug — so the assertion every test below shares is that the list is empty."""

    def __init__(self, monkeypatch, blob, portal_out=None):
        import main
        self.writes = []
        self.bodies = []
        self.rev = 0
        self.blob = blob
        monkeypatch.setattr(main.drafts, "load_draft",
                            lambda i: {"id": i, "data": self.blob, "owner_email": ""})
        monkeypatch.setattr(main.profiles, "get_by_email",
                            lambda e: {"email": e, "role": "admin"})
        monkeypatch.setattr(main.drafts, "create_revision", self._create_revision)
        monkeypatch.setattr(main.drafts, "delete_revision",
                            lambda *a, **k: self.writes.append("delete_revision"))
        monkeypatch.setattr(main.drafts, "log_event",
                            lambda *a, **k: self.writes.append("log_event"))
        monkeypatch.setattr(main, "_portal", self._portal)
        self.portal_out = portal_out or {"ok": True, "url": "https://portal/x",
                                         "customer_email": "c@x.com"}

    def _create_revision(self, did, data, by=None):
        self.writes.append("create_revision")
        self.rev += 1
        return self.rev

    def _portal(self, path, method="GET", body=None):
        # ONE call, and it is the one that writes the portal row and sends the email. Recorded
        # under a name a failure message can be read out loud: "the email went".
        self.writes.append("portal " + path)
        self.bodies.append(body)
        # A COPY. The route does `out.setdefault("revision_no", …)` on whatever comes back, and
        # the real `_portal` parses fresh JSON per call — a shared dict would carry the first
        # send's revision number into the second and fake a re-send bug that does not exist.
        return dict(self.portal_out)

    def send(self, **extra):
        import main
        from fastapi.testclient import TestClient
        body = {"assigned_estimator": "kyle@wetreadwell.com"}
        body.update(extra)
        return TestClient(main.app).post("/api/portal/publish?draft_id=d1", json=body)


def test_a_drifted_publish_is_REFUSED(monkeypatch):
    """The reported case, driven through the real route. 409, not 200 — and the estimator must
    not be able to mistake the response for a send."""
    p = _Publish(monkeypatch, REPORTED)
    r = p.send()
    assert r.status_code == 409, r.text
    assert r.json()["ok"] is False


def test_a_refused_publish_WRITES_NOTHING_AND_SENDS_NOTHING(monkeypatch):
    """THE test. The old behaviour did all of this and then apologised. If any of these fire, a
    customer has the wrong price in their inbox and the refusal is theatre.

    `create_revision` would pin the portal to the drifted snapshot; `/api/admin/publish` writes
    the proposal row and sends the customer's email; `log_event` would record a send that never
    happened. Nothing may run."""
    p = _Publish(monkeypatch, REPORTED)
    p.send()
    assert p.writes == [], (
        "a refused publish still had side effects — the customer may have been emailed: %s"
        % p.writes)
    assert p.rev == 0, "a revision was minted for a send that was refused"


def test_the_refusal_names_the_MONEY_and_the_OPTION_COUNT(monkeypatch):
    """A refusal that says "stale" and nothing else sends the estimator hunting. It has to carry
    the same substance as the warning it replaces — his figures, both sides, in one sentence a UI
    can print unchanged."""
    msg = _Publish(monkeypatch, REPORTED).send().json()["error"]
    flat = msg.replace(",", "")
    assert "29104" in flat and "27721" in flat, msg
    assert "$" in msg, "the figures must read like money, not like floats: %s" % msg
    assert "2 options, not 0" in msg, msg
    assert "not sent" in msg.lower(), "the sentence must say the send did NOT happen: %s" % msg
    assert "Proposal step" in msg and "Continue" in msg, (
        "the refusal must name the way out, not just the problem: %s" % msg)


def test_the_refusal_is_MACHINE_READABLE(monkeypatch):
    """The page has to offer a one-click fix without parsing English. A code plus both halves as
    numbers; the prose is for humans only."""
    import main
    j = _Publish(monkeypatch, REPORTED).send().json()
    assert j["code"] == main.STALE_DOCUMENT_CODE == "stale_document"
    assert j["page"] == {"base_label": "Epoxy", "lump_sum": 27721, "option_count": 0}
    assert j["document"] == {"base_label": "Epoxy", "lump_sum": 29104, "option_count": 2}
    # Same shape as a successful send's echo, so one reader understands both.
    assert j["snapshot"]["doc_lump_sum"] == 29104 and j["snapshot"]["has_document"] is True
    assert isinstance(j["differences"], list) and len(j["differences"]) == 2


def test_the_refusal_reaches_the_CURRENTLY_DEPLOYED_page_as_a_sentence(monkeypatch):
    """Deploys are not atomic and estimators keep tabs open for days. Today's `portalErrMsg`
    recovers a message from the raw response text with a regex over "detail"/"error", so the body
    must be FLAT (`{"error": ...}`, not HTTPException's `{"detail": {...}}`) and the sentence must
    contain no quote character. Otherwise the person this was built for reads a JSON dump and
    calls it broken."""
    import re
    raw = _Publish(monkeypatch, REPORTED).send().text
    m = re.search(r'"(?:detail|error)"\s*:\s*"([^"]+)"', raw)
    assert m, "the old page's regex finds nothing to show: %s" % raw
    assert "29104" in m.group(1).replace(",", ""), m.group(1)


def test_the_refusal_is_LOGGED_with_the_reason_and_both_figures(monkeypatch, caplog):
    """A bare "refused" costs an SSH session and a container probe. The one line has to answer
    "refused what, and how far apart" without anybody opening the database."""
    import logging
    caplog.set_level(logging.WARNING)
    _Publish(monkeypatch, REPORTED).send()
    recs = [r for r in caplog.records if "refused" in r.getMessage()]
    assert recs, "a refused publish logged nothing: %s" % [r.getMessage() for r in caplog.records]
    line = recs[0].getMessage()
    assert "d1" in line, "the log does not say WHICH draft: %s" % line
    assert "27721" in line and "29104" in line, "the log omits a figure: %s" % line
    # BOTH figures AND the reason. The raw values alone leave whoever is reading at 2am to work
    # out which of base / price / option count actually drifted — a mutation that logged the
    # numbers under a bare "stale" survived until this line existed.
    assert "its price is" in line and "it shows 2 options" in line, (
        "the log names no reason, only figures: %s" % line)
    # …and side by side, so nobody has to cross-reference two log lines to compare them.
    assert "page base=" in line and "document base=" in line, line


# ── and the ordinary send must be completely unaffected ──────────────────────
def test_a_CLEAN_publish_still_succeeds(monkeypatch):
    """The gate is worthless if it costs the normal case. Both halves agree, so this must be the
    byte-for-byte old behaviour: a revision, a portal call, an event, and the echo."""
    p = _Publish(monkeypatch, CLEAN)
    r = p.send()
    assert r.status_code == 200, r.text
    assert p.writes == ["create_revision", "portal /api/admin/publish", "log_event"], p.writes
    assert r.json()["revision_no"] == 1
    snap = r.json()["sent_snapshot"]
    assert snap["lump_sum"] == snap["doc_lump_sum"] == 27721


def test_a_clean_RE_SEND_still_succeeds(monkeypatch):
    """Re-sending an already-sent revision that has not drifted is routine — a customer lost the
    email, a recipient was added, a deposit flag flipped. It must mint the next revision and go,
    exactly as before. Breaking this would be the fix causing its own outage."""
    p = _Publish(monkeypatch, CLEAN)
    assert p.send().status_code == 200
    second = p.send()
    assert second.status_code == 200, second.text
    assert second.json()["revision_no"] == 2, "the re-send did not mint its own revision"
    assert p.writes.count("portal /api/admin/publish") == 2, p.writes


def test_a_project_that_has_never_been_GENERATED_still_publishes(monkeypatch):
    """No `proposal_payload` at all — nothing has been generated, so nothing can be stale.
    Refusing here would lock out every project that reaches the portal before the Proposal step,
    and there would be no Continue to press that changes anything."""
    p = _Publish(monkeypatch, {"base_tab_id": "Epoxy", "proposal_lump_sum": 27721,
                               "rooms": [{"name": "Epoxy", "is_base": True,
                                          "bid": {"total": 27721}}]})
    assert p.send().status_code == 200
    assert "portal /api/admin/publish" in p.writes


def test_has_document_is_the_SAME_gate_the_page_uses(monkeypatch):
    """A payload carrying `rooms` but no `values` reads as NO DOCUMENT, and still publishes.

    `has_document` is `bool(payload["values"])`, and the Files page gates its own comparison on
    exactly that key — so the server must too. Deciding this shape was readable here would give us
    two rules: the page would say the send was fine and the server would refuse it, which is worse
    than either answer on its own. Every real generate spreads the whole page state into `values`,
    so the shape does not occur in practice; this test exists to keep the two halves in step if
    somebody ever "improves" the guard. A mutation deleting it survived until this case existed."""
    p = _Publish(monkeypatch, {
        "base_tab_id": "Epoxy", "proposal_lump_sum": 27721,
        "rooms": [{"name": "Epoxy", "is_base": True, "bid": {"total": 27721}}],
        "proposal_payload": {"rooms": [
            {"name": "Polish", "is_base": True, "bid": {"total": 13265}},
            {"name": "Epoxy", "is_base": False, "bid": {"total": 18670}, "show": True}]}})
    assert p.send().status_code == 200, (
        "the server refused a shape the page treats as having no document to compare")


def test_a_BASE_ONLY_proposal_still_publishes(monkeypatch):
    """The commonest shape this tool produces: one system, no options, so the document carries no
    base ROOM and `doc_base_label` is None. Comparing a null label against a real one would refuse
    almost every send in the building."""
    p = _Publish(monkeypatch, {
        "base_tab_id": "Epoxy", "proposal_lump_sum": 27721, "rooms": [],
        "proposal_payload": {"values": {"proposal_lump_sum": 27721}}})
    assert p.send().status_code == 200, "a base-only proposal was refused"


def test_SUB_CENT_rounding_does_not_refuse_a_send(monkeypatch):
    """Floating point must never block a proposal. 27721.004 and 27721 are the same money, and a
    gate that cannot tell the difference is a gate that stops work at random."""
    blob = {**CLEAN, "proposal_lump_sum": 27721.004}
    assert _Publish(monkeypatch, blob).send().status_code == 200


def test_a_LEGACY_snapshot_shape_does_not_refuse_a_send(monkeypatch):
    """A payload with values but no rooms and no readable price: we know a document exists and
    know nothing about it. Absent evidence is not evidence of drift, and refusing on it would
    strand old projects with no action that clears the block."""
    p = _Publish(monkeypatch, {
        "base_tab_id": "Epoxy", "proposal_lump_sum": 27721,
        "rooms": [{"name": "Epoxy", "is_base": True, "bid": {"total": 27721}}],
        "proposal_payload": {"values": {"job_name": "x"}}})
    assert p.send().status_code == 200, "an unreadable document half refused the send"


# ── the helper's own edges ───────────────────────────────────────────────────
def test_a_base_FLIP_alone_is_enough_to_refuse():
    """The original 2026-08-13 report: same money on both sides of the flip, inverted base bid.
    The page says Epoxy, the PDF says Polish, and the customer signs for the wrong system."""
    import main
    ref = main._stale_document_refusal(main._publish_digest(DRIFTED))
    assert ref is not None, "an inverted base bid was allowed through"
    assert "Polish, not Epoxy" in ref["error"], ref["error"]


def test_the_refusal_never_raises_on_a_malformed_blob():
    """It now decides whether a proposal can be sent AT ALL, so a TypeError here is not a 500 on a
    cosmetic warning — it is an estimator who cannot send anything and no idea why. Every shape a
    browser could have written must fall through to "we don't know", which means send it."""
    import main
    for blob in ({}, {"rooms": "not a list"}, {"rooms": 5}, {"proposal_payload": "nope"},
                 {"proposal_payload": {}}, {"proposal_payload": {"values": 5}},
                 {"proposal_payload": {"values": {"proposal_lump_sum": "29,104"}}},
                 {"proposal_lump_sum": "27721",
                  "proposal_payload": {"values": {"proposal_lump_sum": 29104}}},
                 {"proposal_lump_sum": True,
                  "proposal_payload": {"values": {"proposal_lump_sum": 29104}}},
                 {"proposal_lump_sum": float("nan"),
                  "proposal_payload": {"values": {"proposal_lump_sum": 29104}}},
                 {"proposal_lump_sum": float("inf"),
                  "proposal_payload": {"values": {"proposal_lump_sum": 29104}}},
                 {"proposal_lump_sum": {"a": 1},
                  "proposal_payload": {"values": {"proposal_lump_sum": 29104}}}):
        assert main._stale_document_refusal(main._publish_digest(blob)) is None, blob


def test_money_in_the_refusal_reads_like_the_screen_it_contradicts():
    """`_usd` mirrors the page's TW.fmtUsd (whole dollars, thousands separators). "29104.0" in a
    refusal about money the estimator is looking at formatted as $27,721 reads as a different
    kind of bug."""
    import main
    assert main._usd(29104) == "$29,104"
    assert main._usd(27721.4) == "$27,721"
    assert main._usd(None) == "$—" and main._usd("x") == "$—"
