"""The Active Projects board survives the portal being down.

2026-08-28, minutes after a staging deploy: the board came up as a red box reading "Could not load
the portal pipeline: Portal error.. Check that the portal is configured (PORTAL_ADMIN_URL /
SERVICE_TOKEN)", every tab at 0. Nothing was broken here — staging's customer-portal container had
auto-slept and answered 502. Hanz: "portal and proposal are two different services so if portal is
down it should still show the projects... that is bad architecture, if that happens live then we
are cooked."

He is right, and the failure was structural: /api/portal/pipeline was ONE unguarded call to another
service's admin API, and it is the only thing the board fetches. So the other service's uptime was
the board's uptime — even for the "Created but not sent" column, which is built entirely from our
own drafts table and needs the portal for nothing.

The fix is the discipline _refresh_crm already uses for the bell (test_bell_crm_steps.py), applied
to the page the sales meeting is run from, in two tiers:

  * TIER 1 "stale" — serve the last pipeline the portal gave us, from an in-process cache. Full
    fidelity: real stages, real approval and deposit timestamps, just a few minutes old. This is
    the common case (a blip, a redeploy, an auto-sleep).
  * TIER 2 "offline" — nothing cached, because this container has never had a good answer. Rebuild
    the board from local drafts alone: `_not_sent_rows` for what was never sent, and the new
    `_sent_unknown_rows` for what WAS, carrying `portal_unknown` and no invented status.

THE THING THAT MAKES TIER 2 WORTH HAVING, and the thing to break if you want to see this file fail:
offline, `_not_sent_rows`'s "does the portal know this one" set is empty, so without the split
every proposal ever sent files itself under "Created but not sent". A blank board is a bad hour; a
board that tells a rep six months of live bids were never sent is a bad week.

WHY THE CACHE IS RESET PER TEST. `_PIPELINE_CACHE` is module state on `main`, so any other test in
the session that drives this endpoint to success warms it. A cold-cache assertion that depends on
file ordering is a test that passes alone and fails in the suite.
"""
import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def cold_cache():
    """Every test here states its own cache; none inherits one."""
    main._PIPELINE_CACHE.update({"rows": None, "fetched_at": None})
    yield
    main._PIPELINE_CACHE.update({"rows": None, "fetched_at": None})


def _row(pid="p1", **kw):
    base = {"proposal_id": pid, "project_name": "Oak Grove", "customer_email": "dave@x.com",
            "proposal_status": "viewed", "deposit_status": "pending",
            "contacts_status": "pending", "unread": 0, "sent_at": "2026-08-01T12:00:00+00:00"}
    base.update(kw)
    return base


def _draft(did="d1", **kw):
    """A drafts-list summary shaped the way _build_summaries actually returns one — including
    `sent_revision`, which is the local answer to "did this go out"."""
    base = {"id": did, "project_name": "Nearman Creek", "has_files": True, "archived": False,
            "is_test": None, "owner_email": "kyle@wetreadwell.com", "assigned_estimator": None,
            "contact_email": "gc@example.com", "total": 41250,
            "updated_at": "2026-08-09T10:00:00+00:00", "work_type": "epoxy", "sent_revision": 0}
    base.update(kw)
    return base


def _up(monkeypatch, rows, projects):
    monkeypatch.setattr(main, "_portal",
                        lambda p, m="GET", b=None: {"ok": True, "proposals": rows})
    monkeypatch.setattr(main.drafts, "list_drafts", lambda *a, **k: projects)


def _down(monkeypatch, projects, exc=None):
    """The portal as it actually fails: _portal raises HTTPException(502) when it cannot be
    reached and HTTPException(503) when this app was deployed without its address."""
    err = exc or main.HTTPException(502, "Could not reach the customer portal.")

    def boom(*a, **k):
        raise err
    monkeypatch.setattr(main, "_portal", boom)
    monkeypatch.setattr(main.drafts, "list_drafts", lambda *a, **k: projects)


def _get():
    r = client.get("/api/portal/pipeline")
    assert r.status_code == 200, "the board returned %d: %s" % (r.status_code, r.text)
    return r.json()


def _by_id(body):
    return {p["proposal_id"]: p for p in body["proposals"]}


# ── tier 1: a warm cache ─────────────────────────────────────────────────────
def test_a_portal_that_goes_down_keeps_serving_the_last_board_it_gave_us(monkeypatch):
    """The auto-sleep case, and the redeploy case, and the 30-second-blip case. The rep should
    not be able to tell, except for the banner: these are the REAL rows, with the real stage the
    customer's proposal is at."""
    _up(monkeypatch, [_row("p1", proposal_status="approved")], [])
    assert _get()["portal_status"] == "live"

    _down(monkeypatch, [])
    body = _get()
    assert body["portal_status"] == "stale"
    assert _by_id(body)["p1"]["proposal_status"] == "approved", (
        "the cached row lost the stage it was cached for")
    assert body["portal_fetched_at"], "a stale board with no date on it cannot say how stale"


def test_a_warm_cache_never_synthesises_a_second_card_for_a_project_it_already_has(monkeypatch):
    """`_sent_unknown_rows` is for the cold case only. Run it against cached rows and every sent
    project appears twice — once with its real stage and once as "status unknown"."""
    _up(monkeypatch, [_row("d1", proposal_status="approved")],
        [_draft("d1", sent_revision=2)])
    _get()
    _down(monkeypatch, [_draft("d1", sent_revision=2)])
    body = _get()
    assert [p["proposal_id"] for p in body["proposals"]] == ["d1"], (
        "the board doubled the project: %r" % body["proposals"])
    assert "portal_unknown" not in body["proposals"][0]


def test_the_cache_refills_and_the_board_snaps_back_to_live(monkeypatch):
    """Wake the portal, reload, get the truth again — including a stage that moved while we were
    serving the old snapshot."""
    _up(monkeypatch, [_row("p1", proposal_status="sent")], [])
    _get()
    _down(monkeypatch, [])
    assert _get()["portal_status"] == "stale"
    _up(monkeypatch, [_row("p1", proposal_status="approved")], [])
    body = _get()
    assert body["portal_status"] == "live"
    assert _by_id(body)["p1"]["proposal_status"] == "approved"


# ── tier 2: no cache at all ──────────────────────────────────────────────────
def test_a_cold_start_against_a_dead_portal_still_shows_our_own_projects(monkeypatch):
    """The case the old posture had no answer for: a container that restarted while the portal was
    down has nothing cached, and every one of these projects lives in OUR database."""
    _down(monkeypatch, [_draft("never", project_name="Cedar Ridge", sent_revision=0),
                        _draft("gone_out", project_name="Nearman Creek", sent_revision=3)])
    body = _get()
    assert body["portal_status"] == "offline"
    assert body["portal_fetched_at"] is None, "an offline board dated itself off nothing"
    out = _by_id(body)
    assert out["never"]["not_sent"] is True
    assert "portal_unknown" not in out["never"]
    assert out["gone_out"]["portal_unknown"] is True
    assert "not_sent" not in out["gone_out"], (
        "a proposal the customer already has is being shown as never sent")


def test_a_sent_bid_is_never_filed_under_created_but_not_sent(monkeypatch):
    """The whole reason `_sent_unknown_rows` exists. `_not_sent_rows` excludes what the PORTAL
    knows about, and offline it knows about nothing — so without the split, stage() puts every
    live proposal in the first column and a rep starts re-sending work customers already have.

    Mutation: delete the `if portal_status == "offline"` append. This test and the cold-start one
    above are the two that fail."""
    _down(monkeypatch, [_draft("d%d" % i, sent_revision=1) for i in range(3)])
    body = _get()
    assert all(p.get("portal_unknown") for p in body["proposals"]), body["proposals"]
    assert not any(p.get("not_sent") for p in body["proposals"])


def test_an_unknown_row_claims_no_status_it_cannot_know(monkeypatch):
    """We know it left the door. We do not know whether it was opened, approved or paid, and
    stage() falling back to "Sent" is the honest bucket. Writing proposal_status "viewed" to make
    the board look complete would be a lie with a timestamp on it."""
    _down(monkeypatch, [_draft("d1", sent_revision=1)])
    row = _by_id(_get())["d1"]
    for invented in ("proposal_status", "deposit_status", "contacts_status", "approved_total",
                     "approved_at", "last_viewed_at"):
        assert invented not in row, "%s was invented on a row nobody can vouch for" % invented


def test_the_local_facts_we_do_own_still_reach_the_card(monkeypatch):
    """`is_test` decides which TAB the card lands on, the estimator decides who is asked about it,
    and the bid is the number Kyle looks for. All three are ours and all three survive an outage —
    a degraded card with no money and no owner is barely better than no card."""
    _down(monkeypatch, [_draft("d1", sent_revision=1, is_test=True, total=41250,
                               assigned_estimator=None,
                               owner_email="will@wetreadwell.com",
                               contact_email="gc@example.com")])
    row = _by_id(_get())["d1"]
    assert row["is_test"] is True
    assert row["estimator_email"] == "will@wetreadwell.com"
    assert row["bid_total"] == 41250
    assert row["customer_email"] == "gc@example.com"
    assert row["project_name"] == "Nearman Creek"
    assert row["last_activity_at"] == "2026-08-09T10:00:00+00:00", (
        "with no date these cards sort to the bottom of whatever column they land in")
    assert "approved_total" not in row, "an unapproved bid is being sent as approved money"


def test_a_hand_marked_lost_bid_still_reads_as_lost(monkeypatch):
    """The one status we CAN still state, because somebody in this app typed it. Shaped as the
    portal's own closed_lost state so the Lost tab, its reason columns and the chip keep working
    with nothing new — the same trick `_not_sent_rows` already plays."""
    _down(monkeypatch, [_draft("d1", sent_revision=1, closed_lost_reason="price",
                               closed_lost_at="2026-08-20T09:00:00+00:00",
                               closed_lost_note="GC went with the incumbent")])
    row = _by_id(_get())["d1"]
    assert row["proposal_status"] == "closed_lost"
    assert row["followup_state"]["closed_lost_reason"] == "price"
    assert row["followup_state"]["closed_at"] == "2026-08-20T09:00:00+00:00"


def test_a_hold_pauses_the_card_without_killing_it(monkeypatch):
    """Two of the eight close-out answers pause a bid instead of closing it, and the card STAYS on
    the live board. Same `elif` as the sibling function, for the same reason: both branches write
    followup_state, and a hold overwriting a lost mark would put a dead bid back on the board."""
    _down(monkeypatch, [_draft("d1", sent_revision=1, on_hold_reason="owner_delay",
                               on_hold_until="2026-09-15")])
    row = _by_id(_get())["d1"]
    assert "proposal_status" not in row
    assert row["followup_state"]["paused_until"] == "2026-09-15"


def test_an_archived_project_stays_filed_even_in_an_outage(monkeypatch):
    """Archiving is how staff take a project off their list. An outage resurrecting it would make
    the archive button look broken at the worst possible moment."""
    _down(monkeypatch, [_draft("d1", sent_revision=1, archived=True)])
    assert _get()["proposals"] == []


def test_a_generated_draft_that_never_went_out_is_not_called_sent(monkeypatch):
    """`has_files` only means Generate has run — that is the whole premise of the "Created but not
    sent" column. `sent_revision` is what create_revision writes on publish (and deletes again if
    the send fails), so it is the only local field that answers "did the customer get this"."""
    _down(monkeypatch, [_draft("d1", has_files=True, sent_revision=0)])
    row = _by_id(_get())["d1"]
    assert row["not_sent"] is True
    assert "portal_unknown" not in row


def test_a_summary_with_no_sent_revision_invents_no_send(monkeypatch):
    """`_build_summaries` has a full-blob fallback for the day PostgREST refuses the projection,
    and it does not carry sent_revision. A missing field must degrade to the old behaviour, not to
    a guess — this is a real second code path, not a hypothetical."""
    d = _draft("d1")
    d.pop("sent_revision")
    _down(monkeypatch, [d])
    assert _by_id(_get())["d1"]["not_sent"] is True


# ── the empty and the misconfigured cases ────────────────────────────────────
def test_a_dead_portal_and_no_projects_is_an_empty_board_not_an_error(monkeypatch):
    """A fresh container, an empty database and a sleeping portal. The honest answer is a board
    with nothing on it and a reason attached — not a 502 the browser turns into a red box."""
    _down(monkeypatch, [])
    body = _get()
    assert body["proposals"] == []
    assert body["portal_status"] == "offline"


def test_an_unconfigured_portal_degrades_the_same_way_an_unreachable_one_does(monkeypatch):
    """_portal raises 503 before it makes a request when PORTAL_ADMIN_URL / SERVICE_TOKEN are
    missing. That is a deploy mistake in THIS app's env, and it was the sentence in the red box on
    staging — but it still must not cost the estimator the projects we hold locally."""
    _down(monkeypatch, [_draft("d1", sent_revision=0)],
          exc=main.HTTPException(503, "Customer portal is not configured "
                                      "(PORTAL_ADMIN_URL / SERVICE_TOKEN)."))
    body = _get()
    assert body["portal_status"] == "offline"
    assert _by_id(body)["d1"]["not_sent"] is True


def test_an_unreadable_drafts_list_on_top_of_a_dead_portal_is_still_a_200(monkeypatch):
    """Both stores down at once. There is genuinely nothing to show, and the board must say so
    rather than hand the browser a stack trace."""
    _down(monkeypatch, [])
    monkeypatch.setattr(main.drafts, "list_drafts",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("postgrest down")))
    body = _get()
    assert body["proposals"] == []
    assert body["portal_status"] == "offline"


def test_any_exception_from_the_portal_degrades_rather_than_escaping(monkeypatch):
    """HTTPException is what _portal raises today, but the catch is deliberately wider. A json
    decode on a half-written response, or an httpx surprise, must not reach the browser as a 500 —
    the estimator cannot act on either, and both mean the same thing: ask again later."""
    for exc in (RuntimeError("portal offline"), ValueError("Expecting value: line 1 column 1")):
        _down(monkeypatch, [], exc=exc)
        assert _get()["portal_status"] == "offline", exc


# ── the live path is unchanged ───────────────────────────────────────────────
def test_a_live_board_is_decorated_exactly_as_before_and_synthesises_nothing(monkeypatch):
    """The regression guard for the other 99.9% of loads. The is_test / bid_total / won_at
    stamping is untouched, and `portal_unknown` must never appear on a healthy board — a chip
    saying "status unknown" beside a status we DO know is worse than no chip."""
    _up(monkeypatch, [_row("d1", proposal_status="viewed")],
        [_draft("d1", is_test=True, total=41250, sent_revision=2,
                won_at="2026-08-20T14:00:00+00:00")])
    body = _get()
    assert body["portal_status"] == "live"
    row = _by_id(body)["d1"]
    assert row["is_test"] is True
    assert row["bid_total"] == 41250
    assert row["won_at"] == "2026-08-20T14:00:00+00:00"
    assert row["proposal_status"] == "viewed"
    assert "portal_unknown" not in row
    assert not any(p.get("portal_unknown") for p in body["proposals"])


def test_a_healthy_board_says_so_and_dates_itself(monkeypatch):
    """The frontend keys its banner off these two. `live` has to be the value on the happy path or
    the banner shows on every load and stops being read."""
    _up(monkeypatch, [_row("p1")], [])
    body = _get()
    assert body["portal_status"] == "live"
    assert isinstance(body["portal_fetched_at"], float)


# ── the other two pages off the same call ────────────────────────────────────
# The board was the outage Hanz saw, but it is not the only page whose entire content is one
# unguarded call to the portal's admin pipeline. Follow-ups and the digest preview read the SAME
# upstream, so before this they failed in the same breath and for the same reason. They share the
# cache too, which is the point: one successful board load keeps all three warm.
#
# WHAT IS DELIBERATELY DIFFERENT: neither of these synthesises anything offline. Both are ABOUT
# portal-side send and view history, so there is nothing local to rebuild them from and an invented
# row would be a guess about a customer. Offline is an honest empty list that says so.
def _followups():
    r = client.get("/api/portal/followups")
    assert r.status_code == 200, "follow-ups returned %d: %s" % (r.status_code, r.text)
    return r.json()


def test_the_followups_page_keeps_its_list_when_the_portal_drops(monkeypatch):
    """The win that matters here. A rep working down the list mid-review loses it entirely if this
    502s, and the list is the whole page."""
    _up(monkeypatch, [_row("p1", proposal_status="approved")], [])
    assert _followups()["portal_status"] == "live"

    _down(monkeypatch, [])
    body = _followups()
    assert body["portal_status"] == "stale"
    assert [p["proposal_id"] for p in body["proposals"]] == ["p1"], (
        "the cached follow-up list was dropped rather than served")
    assert body["portal_fetched_at"], "a stale list with no date on it cannot say how stale"


def test_the_followups_page_is_an_honest_empty_when_nothing_is_cached(monkeypatch):
    """Cold cache. A 200 with an empty list and `offline` beside it — the page reads that and says
    why. It must NOT be a 502, and it must NOT invent rows: the frontend's empty state otherwise
    reads as "everybody has been chased", which is good news that is not true."""
    _down(monkeypatch, [_draft("d1", sent_revision=3)])
    body = _followups()
    assert body["portal_status"] == "offline"
    assert body["proposals"] == [], (
        "follow-ups synthesised rows it cannot know the send history of: %s" % body["proposals"])


def test_the_followups_page_scores_a_stale_row_exactly_as_a_live_one(monkeypatch):
    """Tier 1 is full fidelity or it is worthless. The scoring runs on the cached row unchanged, so
    a rep's ordering does not silently reshuffle the moment the portal blips."""
    _up(monkeypatch, [_row("p1", proposal_status="approved")], [])
    live = _followups()["proposals"][0]
    _down(monkeypatch, [])
    stale = _followups()["proposals"][0]
    for key in ("followup_score", "eligible", "reason"):
        assert stale[key] == live[key], (
            "%s changed between the live and the cached copy of the same row" % key)


def test_the_digest_preview_degrades_instead_of_502ing(monkeypatch):
    """An admin preview, so `stale` costs nothing and `offline` is an honest empty. The reason it
    is guarded at all is that a 502 here looks exactly like the digest itself being broken, and the
    digest is the thing that emails estimators every morning."""
    monkeypatch.setattr(main, "_require_admin", lambda *a, **k: None)
    _up(monkeypatch, [_row("p1", proposal_status="approved")], [])
    r = client.get("/api/admin/digest/preview")
    assert r.status_code == 200, r.text
    assert r.json()["portal_status"] == "live"

    _down(monkeypatch, [])
    r = client.get("/api/admin/digest/preview")
    assert r.status_code == 200, "the preview 502'd instead of degrading: %s" % r.text
    body = r.json()
    assert body["portal_status"] == "stale"
    assert body["considered"] == 1, "the cached row never reached the digest builder"


def test_the_digest_preview_considers_nothing_rather_than_guessing(monkeypatch):
    """Cold. `considered: 0` is the honest answer — and it is the one that matters, because the
    number on screen is what an admin uses to decide whether the morning mail is working."""
    monkeypatch.setattr(main, "_require_admin", lambda *a, **k: None)
    _down(monkeypatch, [_draft("d1", sent_revision=3)])
    r = client.get("/api/admin/digest/preview")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["portal_status"] == "offline"
    assert body["considered"] == 0
    assert body["would_send"] == [], (
        "the preview named estimators to email off a board it could not read: %s"
        % body["would_send"])


def test_one_good_board_load_warms_all_three_pages(monkeypatch):
    """The cache is shared on purpose, and this is the assertion that keeps it shared. Give each
    page its own and a rep who has only opened the board gets a dead Follow-ups page during the
    very outage the cache exists for."""
    monkeypatch.setattr(main, "_require_admin", lambda *a, **k: None)
    _up(monkeypatch, [_row("p1", proposal_status="approved")], [])
    _get()                                   # the BOARD is the only page loaded while it was up
    _down(monkeypatch, [])
    assert _followups()["portal_status"] == "stale", "follow-ups did not see the board's cache"
    assert client.get("/api/admin/digest/preview").json()["portal_status"] == "stale", (
        "the digest preview did not see the board's cache")
