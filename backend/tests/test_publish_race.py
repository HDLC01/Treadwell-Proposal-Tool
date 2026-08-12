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
    for blob in ({}, {"rooms": "not a list"}, {"rooms": [None, 7, {}]}, {"rooms": 5},
                 {"rooms": {"a": 1}}, {"rooms": True},
                 {"rooms": [{"is_base": True}], "proposal_lump_sum": None}):
        d = main._publish_digest(blob)
        assert set(d) == {"base_tab_id", "base_label", "lump_sum", "option_count"}
        assert isinstance(d["option_count"], int)


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
