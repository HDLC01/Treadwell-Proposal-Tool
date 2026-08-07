"""Lead inbox: the merge contract, the intake blob, the AI whitelist, the email
reader, the /api/leads* endpoints, and the autopilot sweep.

EVERY network and DB seam is stubbed, deliberately and by default: `_no_live_seams`
below replaces basisboard's transport, both `get_client()`s, `subprocess.run` and
`httpx.Client` with functions that raise, so a path this file forgot to stub fails
in milliseconds instead of dialling out to api.basisboard.com (or blocking on a
`claude -p` run) and hanging the suite. The autopilot's daemon thread is never
started either — `_sweep()` is called directly.
"""
import subprocess
import time
from datetime import timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

import basisboard_client as bb
import drafts
import leads
import leads_worker
import main
import supabase_client

client = TestClient(main.app)

# Captured BEFORE _no_live_seams patches it, so the "off mode never spawns a
# thread" test can exercise the genuine starter (conftest does the same for
# verify_token).
_REAL_ENSURE_STARTED = leads_worker.ensure_started


# ── fake data store ───────────────────────────────────────────────────
# The conftest FakeClient has no `upsert`, which is the only write leads.py makes.
class _Res:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, store, name):
        self.store, self.name = store, name
        self._op = self._payload = None
        self._filters = []
        self._nulls = []
        self._limit = None

    def select(self, *a, **k):
        self._op = "select"; return self

    def insert(self, row):
        self._op, self._payload = "insert", row; return self

    def update(self, patch):
        self._op, self._payload = "update", patch; return self

    def upsert(self, row, **k):
        self._op, self._payload = "upsert", row; return self

    def eq(self, key, val):
        self._filters.append((key, [val])); return self

    def in_(self, key, vals):
        self._filters.append((key, list(vals))); return self

    def is_(self, key, val):
        # PostgREST's IS NULL / IS NOT NULL. Absent and None are both null here,
        # which matches a column the row was inserted without.
        self._nulls.append((key, str(val).lower() == "null")); return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        self._limit = n; return self

    def _rows(self):
        return self.store.setdefault(self.name, [])

    def _match(self):
        sel = list(self._rows())
        for key, vals in self._filters:
            sel = [r for r in sel if r.get(key) in vals]
        for key, want_null in self._nulls:
            sel = [r for r in sel if (r.get(key) is None) is want_null]
        return sel

    def execute(self):
        rows = self._rows()
        if self._op == "insert":
            rows.append(dict(self._payload))
            return _Res([dict(self._payload)])
        if self._op == "upsert":
            patch = dict(self._payload)
            for row in rows:
                if row.get("id") == patch.get("id"):
                    row.update(patch)
                    return _Res([dict(row)])
            # Mirror the table defaults so a first-touch row reads like the DB's.
            row = {"lead_status": "new", "category": None, "ai": {}, "extract": {},
                   "draft_id": None, "notes": None, "meta": {}, "status_by": None}
            row.update(patch)
            rows.append(row)
            return _Res([dict(row)])
        if self._op == "update":
            hit = self._match()
            for row in hit:
                row.update(self._payload)
            return _Res([dict(r) for r in hit])
        sel = self._match()
        return _Res([dict(r) for r in (sel[:self._limit] if self._limit else sel)])


class _FakeClient:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _Table(self.store, name)


# ── fixtures ──────────────────────────────────────────────────────────
def _boom(what):
    def _raise(*a, **k):
        raise AssertionError(f"unstubbed seam reached: {what}")
    return _raise


@pytest.fixture(autouse=True)
def _no_live_seams(monkeypatch):
    """Nail every door shut. A test that needs one of these opens it explicitly."""
    monkeypatch.setattr(bb, "_get", _boom("basisboard_client._get"))
    monkeypatch.setattr(bb, "_session", _boom("basisboard_client._session"))
    monkeypatch.setattr(leads, "get_client", _boom("leads.get_client"))
    monkeypatch.setattr(drafts, "get_client", _boom("drafts.get_client"))
    monkeypatch.setattr(supabase_client, "get_client", _boom("supabase_client.get_client"))
    monkeypatch.setattr(subprocess, "run", _boom("subprocess.run (claude -p)"))
    monkeypatch.setattr(httpx, "Client", _boom("httpx.Client (.eml download)"))
    # The daemon must never run in a test — the endpoints call this on every hit.
    monkeypatch.setattr(leads_worker, "ensure_started", lambda **k: False)


@pytest.fixture(autouse=True)
def _clear_module_caches():
    """Both modules hold TTLCaches that would otherwise make these tests
    order-dependent (a cached inbox or a cached email body leaking forward)."""
    def _clear():
        leads._STATES_CACHE.clear()
        leads._TEXT_CACHE.clear()
        bb._inbox_cache.clear()
        bb._meta_cache.clear()
        bb._pipeline_cache.clear()
        main._AUTOFILL_HITS.clear()
        leads_worker._ATTEMPTS.clear()
        leads_worker._FAILS = 0
        leads_worker._QUIET_UNTIL = 0.0
    _clear()
    yield
    _clear()


_CDT = timezone(timedelta(hours=-5))        # America/Chicago in August


@pytest.fixture
def central(monkeypatch):
    """Pin the business timezone for the date-conversion tests.

    `leads._biz_tz()` falls back to UTC when the host has no tz database, and a
    Windows dev box has none (the image installs `tzdata`). Without this the
    conversion under test silently becomes a no-op and the assertion passes for
    the wrong reason — or fails only locally."""
    monkeypatch.setattr(leads, "_biz_tz", lambda: _CDT)


@pytest.fixture
def db(monkeypatch, _no_live_seams):
    """An in-memory stand-in for PostgREST, wired into both modules that read it.
    Depends on _no_live_seams explicitly so it patches AFTER the booby traps."""
    store = {"leads": [], "drafts": [], "events": []}
    fake = _FakeClient(store)
    monkeypatch.setattr(leads, "get_client", lambda: fake)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    monkeypatch.setattr(supabase_client, "get_client", lambda: fake)
    return store


# ── message fixtures (shapes captured from the live API) ──────────────
def _full_msg(mid="m1"):
    return {
        "id": mid,
        "subject": "Bid Invitation: Edgerton Logistics Center - Building 4",
        "fromEmail": '"Lorena Fonseca (Lemartec Corporation a MasTec company)" '
                     "<team@buildingconnected.com>",
        "createdAt": "2026-07-27T14:02:11.000Z",
        "platformId": "building_connected",
        "communicationType": "bid_invite",
        "status": "unlinked",
        "isSpam": False,
        "project": {"name": "Edgerton Logistics Center",
                    "location": "Edgerton, KS 66021, United States of America",
                    "region": "Midwest", "addressLine": "31000 W 191st St",
                    "city": "Edgerton"},
        "company": {"name": "Lemartec Corporation"},
        "bidDeadlineAt": "2026-08-05T02:30:00.000Z",
        "distance": "20.0 mi",
        "travelTime": "23 mins",
        "duplicateMessagesCount": 2,
        "groupedMessages": [{"id": "m1b", "subject": "FW: Bid Invitation",
                             "createdAt": "2026-07-27T15:31:00.000Z",
                             "fromEmail": "pm@lemartec.example",
                             "platformId": "unknown",
                             "communicationType": "bid_invite"}],
        "suggestedGroupedMessages": [],
        "scrapedIndicator": {"projectName": True, "projectLocation": True,
                             "companyName": True, "bidDueDate": True},
    }


def _sparse_msg(mid="m2"):
    """What the scraper produces when it finds almost nothing: no company object
    at all, "N/A" where a field failed, and nulls for the computed geography."""
    return {
        "id": mid,
        "subject": "Addendum 3 - Riverside Apartments",
        "fromEmail": "noreply@isqft.com",
        "createdAt": "2026-07-26T09:00:00.000Z",
        "platformId": "unknown",
        "communicationType": "addendum",
        "status": "unlinked",
        "isSpam": False,
        "project": {"name": "N/A"},
        "bidDeadlineAt": None,
        "distance": None,
        "travelTime": None,
        "duplicateMessagesCount": None,
        "groupedMessages": None,
    }


# leads.js reads these by name. Adding one is fine; renaming one breaks the page.
_ROW_KEYS = {
    "id", "subject", "from_email", "company", "project_name", "location",
    "address_line", "city", "region", "bid_deadline_at", "communication_type",
    "platform", "distance", "travel_time", "created_at", "is_spam",
    "duplicate_count", "grouped", "lead_status", "category", "draft_id",
    "ai_score", "ai_recommendation", "ai_summary", "has_ai", "lead_auto",
}


# ── 1. merge_inbox ────────────────────────────────────────────────────
def test_merge_maps_a_full_message_onto_the_row_contract():
    row, = leads.merge_inbox([_full_msg()], {})
    assert set(row) == _ROW_KEYS
    assert row["id"] == "m1"
    assert row["company"] == "Lemartec Corporation"
    assert row["project_name"] == "Edgerton Logistics Center"
    assert row["address_line"] == "31000 W 191st St"
    assert row["city"] == "Edgerton" and row["region"] == "Midwest"
    assert row["bid_deadline_at"] == "2026-08-05T02:30:00.000Z"
    assert row["communication_type"] == "bid_invite"
    assert row["platform"] == "building_connected"
    assert row["distance"] == "20.0 mi" and row["travel_time"] == "23 mins"
    assert row["is_spam"] is False and row["duplicate_count"] == 2
    assert row["grouped"] == [{"id": "m1b", "subject": "FW: Bid Invitation",
                               "created_at": "2026-07-27T15:31:00.000Z"}]


def test_merge_renders_absences_as_blank_never_as_na():
    row, = leads.merge_inbox([_sparse_msg()], {})
    assert set(row) == _ROW_KEYS
    assert row["company"] == ""              # the message carried no company object
    assert row["project_name"] == ""         # scraped "N/A" is an absence, not a name
    assert row["location"] == row["address_line"] == row["city"] == ""
    assert row["distance"] == row["travel_time"] == ""
    assert row["bid_deadline_at"] is None    # timestamps stay null, not ""
    assert row["duplicate_count"] == 0 and row["grouped"] == []
    assert "N/A" not in {str(v) for v in row.values()}


def test_merge_reads_an_untouched_message_as_new():
    row, = leads.merge_inbox([_full_msg()], {})
    assert row["lead_status"] == "new"
    assert row["category"] == "" and row["draft_id"] is None
    assert row["has_ai"] is False
    assert row["ai_score"] is None and row["ai_recommendation"] == ""


def test_merge_overlays_our_lead_row():
    states = {"m1": {"id": "m1", "lead_status": "qualified", "category": "polish",
                     "draft_id": "d-42",
                     "ai": {"fit_score": 82, "recommendation": "pursue",
                            "summary": "Warehouse polish, 20 mi out."}}}
    row, = leads.merge_inbox([_full_msg()], states)
    assert row["lead_status"] == "qualified" and row["category"] == "polish"
    assert row["draft_id"] == "d-42"
    assert row["ai_score"] == 82 and row["ai_recommendation"] == "pursue"
    assert row["ai_summary"].startswith("Warehouse polish")
    assert row["has_ai"] is True


def test_merge_skips_messages_with_no_id():
    assert leads.merge_inbox([{"subject": "orphan"}, _full_msg()], {})[0]["id"] == "m1"


# ── 2. build_base_blob ────────────────────────────────────────────────
def test_base_blob_maps_the_scraped_metadata():
    blob = leads.build_base_blob(_full_msg(), "Full email text here.", "draft-123")
    assert blob["project_name"] == "Edgerton Logistics Center"
    assert blob["address"] == "31000 W 191st St"
    assert blob["city"] == "Edgerton"
    assert blob["state"] == "KS"                  # parsed out of the location string
    assert blob["zip"] == "66021"
    assert blob["city_state"] == "Edgerton, KS"
    assert blob["source"] == "email" and blob["audience"] == "GC"
    assert blob["num_systems"] == 2
    assert blob["lead_id"] == "m1" and blob["lead_auto"] is False
    assert blob["__draft_id"] == "draft-123"


def test_base_blob_splits_the_sender_and_drops_the_company_parenthetical():
    blob = leads.build_base_blob(_full_msg(), "", "d1")
    assert blob["contact_name"] == "Lorena Fonseca"
    assert blob["contact_email"] == "team@buildingconnected.com"


def test_base_blob_converts_the_deadline_to_a_central_calendar_date(central):
    """2026-08-05T02:30Z is still 2026-08-04 in Olathe — every date this app shows
    a human is a Central date (TW.fmtBizDate), so intake must agree."""
    blob = leads.build_base_blob(_full_msg(), "", "d1")
    assert blob["bid_date"] == "2026-08-04"
    assert blob["deadline"] == blob["bid_date"]


def test_the_business_timezone_really_resolves_where_it_ships():
    """The UTC fallback in `_biz_tz` is silent, so on a host with no tz database
    every bid deadline after 7pm Central lands a day late. Guards the deploy
    target (the image installs tzdata); skipped on a dev box that hasn't."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        ZoneInfo(leads._TZ_NAME)
    except ZoneInfoNotFoundError:
        pytest.skip("no tz database on this host — `pip install tzdata` to run it")
    assert leads._biz_date("2026-08-05T02:30:00.000Z") == "2026-08-04"


def test_base_blob_carries_the_email_text_into_notes():
    """Estimate Review's Autofill reads state.notes — that's the lead text the
    flag inference needs, so the whole email lands there."""
    blob = leads.build_base_blob(_full_msg(), "Approx 12,500 SF of epoxy.", "d1")
    assert blob["notes"] == "Approx 12,500 SF of epoxy."


def test_base_blob_falls_back_to_the_subject_and_blanks_the_rest():
    blob = leads.build_base_blob(_sparse_msg(), "", "d2")
    assert blob["project_name"] == "Addendum 3 - Riverside Apartments"
    assert blob["address"] == blob["city"] == blob["state"] == ""
    assert blob["city_state"] == "" and blob["zip"] == ""
    assert blob["bid_date"] == "" and blob["deadline"] == ""
    assert blob["contact_name"] == "" and blob["contact_email"] == "noreply@isqft.com"
    assert blob["notes"] == ""


def test_state_parse_needs_a_real_state_not_an_english_word():
    assert leads._parse_state("Lee's Summit, Missouri") == "MO"
    assert leads._parse_state("", "ks") == "KS"
    assert leads._parse_state("somewhere in the middle of nowhere") == ""
    assert leads._parse_state("Ontario, Canada") == ""


# ── 3. apply_ai_overlay ───────────────────────────────────────────────
def _overlay(ai):
    return leads.apply_ai_overlay(leads.build_base_blob(_full_msg(), "text", "d1"), ai)


def test_overlay_applies_whitelisted_keys_and_leaves_the_base_alone():
    base = leads.build_base_blob(_full_msg(), "text", "d1")
    out = leads.apply_ai_overlay(base, {
        "project_name": "Edgerton LC - Building 4",
        "architect": "BRR Architecture",
        "contact_phone": "913-555-0142",
        "contact_notes": "Tilt-up warehouse, 190k SF slab.",
    })
    assert out["project_name"] == "Edgerton LC - Building 4"
    assert out["architect"] == "BRR Architecture"
    assert out["contact_phone"] == "913-555-0142"
    assert out["contact_notes"].startswith("Tilt-up warehouse")
    assert base["project_name"] == "Edgerton Logistics Center"   # not mutated


def test_overlay_rejects_anything_off_the_whitelist():
    """The AI prefills a form; it does not get to author the project. Pricing
    inputs and the raw lead text in particular must stay out of its reach."""
    out = _overlay({
        "cell_values": {"Epoxy!E20": 999999},
        "computed_bid": {"full_bid": {"total_base_bid": 1.0}},
        "notes": "clobbered",
        "lump_sum": 12345,
        "reasoning": {"city": "signature block"},
        "__draft_id": "someone-elses-draft",
    })
    for key in ("cell_values", "computed_bid", "lump_sum", "reasoning"):
        assert key not in out
    assert out["notes"] == "text"                  # the email text survives
    assert out["__draft_id"] == "d1"


def test_overlay_only_accepts_work_types_the_tool_can_build():
    assert _overlay({"work_type": "polish"})["work_type"] == "polish"
    assert _overlay({"work_type": "gyp"})["work_type"] == "gyp"
    assert _overlay({"work_type": "sealer"})["work_type"] == "epoxy"    # base kept
    assert _overlay({"work_type": "Combo"})["work_type"] == "combo"


def test_overlay_coerces_quantities_and_drops_junk_ones():
    out = _overlay({"system_1_sf": "1,250 sf", "polish_sf": "~ 8,400 SF",
                    "cove_1_lf": 310.0, "system_2_sf": "see plans",
                    "gyp_soft_sf": True})
    assert out["system_1_sf"] == 1250 and isinstance(out["system_1_sf"], int)
    assert out["polish_sf"] == 8400
    assert out["cove_1_lf"] == 310
    assert "system_2_sf" not in out          # no number in it -> dropped, not zeroed
    assert "gyp_soft_sf" not in out          # a bool is not a quantity


def test_overlay_recomputes_city_state_and_deadline_after_the_ai_moves_them():
    out = _overlay({"city": "Gardner", "state": "Kansas", "bid_date": "2026-08-12"})
    assert out["state"] == "KS"              # re-parsed, not truncated
    assert out["city_state"] == "Gardner, KS"
    assert out["deadline"] == "2026-08-12"


def test_overlay_ignores_empty_and_malformed_values(central):
    out = _overlay({"city": "", "state": "   ", "audience": "subcontractor",
                    "bid_date": "next Thursday", "contact_email": None})
    assert out["city"] == "Edgerton"                  # base values survive
    assert out["state"] == "KS"
    assert out["audience"] == "GC"
    assert out["bid_date"] == "2026-08-04"
    assert out["contact_email"] == "team@buildingconnected.com"


def test_overlay_accepts_both_audiences():
    assert _overlay({"audience": "direct"})["audience"] == "Direct"
    assert _overlay({"audience": "GC"})["audience"] == "GC"


# ── 4. fetch_email_text ───────────────────────────────────────────────
_HTML_BODY = (
    "<html><head><style>.hdr{color:#ff0000}</style>"
    "<script>var t = new Image(); t.src='/px';</script></head><body>"
    "<!-- open tracking pixel -->"
    "<p>Bid&nbsp;invitation for Edgerton &amp; Gardner</p>"
    "<div>Scope: <b>epoxy</b> flooring</div>"
    "<table><tr><td>Due</td><td>8/5</td></tr></table>"
    "</body></html>"
)


def _fake_httpx(pages):
    """A stand-in httpx.Client for the .eml download. `pages` is a list of
    (status, body) served in order so the 403-then-fresh-URL retry is testable."""
    served = []

    class _Resp:
        def __init__(self, status, content):
            self.status_code, self.content = status, content

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            served.append(url)
            return _Resp(*pages[min(len(served) - 1, len(pages) - 1)])

    return _Client, served


def _raw_eml(subject, plain=None, html=None):
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = "Kyle Loseke <kyle@gc.example>"
    if plain is not None:
        msg.set_content(plain)
        if html is not None:
            msg.add_alternative(html, subtype="html")
    else:
        msg.set_content(html or "", subtype="html")
    return msg.as_bytes()


def test_detail_body_is_stripped_to_readable_text(monkeypatch):
    monkeypatch.setattr(bb, "get_message_detail", lambda mid: {"message": {
        "id": mid, "subject": "Bid Invitation", "fromEmail": "gc@example.com",
        "body": _HTML_BODY}})
    out = leads.fetch_email_text("m1")
    assert out["ok"] is True and out["via"] == "detail"
    assert out["subject"] == "Bid Invitation" and out["from"] == "gc@example.com"
    text = out["text"]
    assert "color:#ff0000" not in text and "new Image" not in text   # style/script content
    assert "tracking pixel" not in text                              # comments
    assert "<" not in text and ">" not in text                       # every tag
    assert "Bid invitation for Edgerton & Gardner" in text           # entities unescaped
    assert "Scope: epoxy flooring" in text
    assert "Due 8/5" in text                                         # cells stay on one line


def test_email_text_is_cached_per_message(monkeypatch):
    hits = {"n": 0}

    def detail(mid):
        hits["n"] += 1
        return {"message": {"subject": "S", "fromEmail": "a@b.c", "body": "<p>Body</p>"}}

    monkeypatch.setattr(bb, "get_message_detail", detail)
    assert leads.fetch_email_text("m1")["text"] == "Body"
    assert leads.fetch_email_text("m1")["text"] == "Body"
    assert hits["n"] == 1


def test_falls_back_to_the_raw_eml_when_detail_has_no_body(monkeypatch):
    monkeypatch.setattr(bb, "get_message_detail", lambda mid: {"message": {"body": ""}})
    monkeypatch.setattr(bb, "get_message_url",
                        lambda mid: "https://storage.googleapis.com/bb/x.eml?sig=1")
    fake, served = _fake_httpx([(200, _raw_eml(
        "Bid Invitation – Café Building",
        plain="Plain body wins over the HTML alternative.",
        html="<p>HTML twin</p>"))])
    monkeypatch.setattr(httpx, "Client", fake)

    out = leads.fetch_email_text("m9")
    assert out["ok"] is True and out["via"] == "eml"
    assert out["subject"] == "Bid Invitation – Café Building"   # RFC-2047 decoded
    assert out["from"] == "Kyle Loseke <kyle@gc.example>"
    assert "Plain body wins" in out["text"] and "HTML twin" not in out["text"]
    assert len(served) == 1


def test_eml_html_only_part_is_stripped(monkeypatch):
    monkeypatch.setattr(bb, "get_message_detail", lambda mid: None)
    monkeypatch.setattr(bb, "get_message_url", lambda mid: "https://storage/x.eml")
    fake, _ = _fake_httpx([(200, _raw_eml("Invite", html=_HTML_BODY))])
    monkeypatch.setattr(httpx, "Client", fake)
    out = leads.fetch_email_text("m10")
    assert out["ok"] is True and "<" not in out["text"]
    assert "Scope: epoxy flooring" in out["text"]


def test_expired_signed_url_is_reminted_once(monkeypatch):
    """A 403 from GCS means the 15-minute link went stale, not that we're
    forbidden — mint a fresh one and try again."""
    monkeypatch.setattr(bb, "get_message_detail", lambda mid: None)
    minted = []
    monkeypatch.setattr(bb, "get_message_url",
                        lambda mid: minted.append(mid) or f"https://storage/x?n={len(minted)}")
    fake, served = _fake_httpx([(403, b""), (200, _raw_eml("Invite", plain="Second try."))])
    monkeypatch.setattr(httpx, "Client", fake)

    out = leads.fetch_email_text("m11")
    assert out["ok"] is True and "Second try." in out["text"]
    assert len(minted) == 2 and served[0] != served[1]      # a genuinely fresh URL


def test_long_body_is_capped(monkeypatch):
    monkeypatch.setattr(bb, "get_message_detail", lambda mid: {"message": {
        "subject": "Huge", "fromEmail": "a@b.c",
        "body": "<p>" + ("scope of work. " * 4000) + "</p>"}})
    out = leads.fetch_email_text("m12")
    assert out["ok"] is True
    assert out["text"].endswith("[truncated]")
    assert len(out["text"]) <= leads._TEXT_CAP + 16


def test_total_failure_returns_not_ok_instead_of_raising(monkeypatch):
    monkeypatch.setattr(bb, "get_message_detail", _boom("detail"))
    monkeypatch.setattr(bb, "get_message_url", lambda mid: None)
    out = leads.fetch_email_text("m404")
    assert out["ok"] is False and out["text"] == "" and out["error"]
    assert out["subject"] == "" and out["from"] == ""


def test_blank_message_id_is_rejected_without_a_call():
    out = leads.fetch_email_text("")
    assert out["ok"] is False and out["error"]


# ── 5. GET /api/leads ─────────────────────────────────────────────────
def _stub_inbox(monkeypatch, messages, **extra):
    payload = {"ok": True, "configured": True, "messages": messages,
               "stats": {"received": 724, "automaticallyProcessed": 59},
               "shown": len(messages), "total": len(messages)}
    payload.update(extra)
    monkeypatch.setattr(bb, "get_inbox", lambda status="unlinked": payload)
    return payload


@pytest.fixture
def inbox(monkeypatch, _no_live_seams):
    _stub_inbox(monkeypatch, [_full_msg(), _sparse_msg()])


def test_api_leads_returns_the_merged_list(monkeypatch, db, inbox):
    db["leads"].append({"id": "m1", "lead_status": "qualified", "category": "epoxy",
                        "draft_id": None, "ai": {"fit_score": 77,
                                                 "recommendation": "pursue",
                                                 "summary": "Warehouse."}})
    body = client.get("/api/leads").json()
    assert body["ok"] is True and body["configured"] is True
    assert body["stats"]["received"] == 724 and body["total"] == 2
    rows = {r["id"]: r for r in body["leads"]}
    assert set(rows) == {"m1", "m2"}
    assert set(rows["m1"]) == _ROW_KEYS
    assert rows["m1"]["lead_status"] == "qualified" and rows["m1"]["ai_score"] == 77
    assert rows["m2"]["lead_status"] == "new"


def test_api_leads_is_200_when_basisboard_is_unconfigured(monkeypatch):
    monkeypatch.setattr(bb, "get_inbox", lambda status="unlinked": {
        "ok": False, "configured": False, "messages": [], "stats": {},
        "error": "Basisboard is not configured"})
    resp = client.get("/api/leads")
    assert resp.status_code == 200          # a work queue must not 500 on someone else's outage
    body = resp.json()
    assert body["ok"] is False and body["configured"] is False
    assert body["leads"] == [] and body["error"]


def test_api_leads_is_200_when_basisboard_is_down(monkeypatch):
    monkeypatch.setattr(bb, "get_inbox", lambda status="unlinked": {
        "ok": False, "configured": True, "messages": [], "stats": {},
        "error": "Couldn't reach Basisboard"})
    body = client.get("/api/leads").json()
    assert body["ok"] is False and body["configured"] is True and body["leads"] == []


def test_get_lead_states_swallows_a_dead_data_store():
    """`leads.get_client` is still the booby trap — a missing table (pre-migration)
    or a DB blip returns {} rather than propagating."""
    assert leads.get_lead_states(["m1", "m2"]) == {}


def test_api_leads_degrades_to_all_new_when_our_table_is_unreachable(inbox):
    """Same failure one layer up: it must cost the overlay, not the page."""
    body = client.get("/api/leads").json()
    assert body["ok"] is True
    assert {r["lead_status"] for r in body["leads"]} == {"new"}
    assert all(r["has_ai"] is False for r in body["leads"])


def test_api_leads_never_starts_the_worker_inline(monkeypatch, db, inbox):
    started = []
    monkeypatch.setattr(leads_worker, "ensure_started",
                        lambda **k: started.append(sorted(k)) or True)
    client.get("/api/leads")
    assert started == [["create_estimate", "prequalify"]]   # hooks handed over, no thread here


# ── 5b. status + body endpoints ───────────────────────────────────────
def test_status_endpoint_persists_and_rejects_unknown_values(db, inbox):
    ok = client.post("/api/leads/m1/status",
                     json={"lead_status": "passed", "category": "Polish"}).json()
    assert ok["ok"] is True and ok["lead"]["lead_status"] == "passed"
    assert db["leads"][0]["category"] == "polish"
    assert db["leads"][0]["status_by"] == "tester@wetreadwell.com"
    assert [e["action"] for e in db["events"]] == ["lead_status_changed"]

    bad = client.post("/api/leads/m1/status", json={"lead_status": "deleted"})
    assert bad.status_code == 400


def test_body_endpoint_returns_text_only(monkeypatch):
    monkeypatch.setattr(bb, "get_message_detail", lambda mid: {"message": {
        "subject": "Invite", "fromEmail": "gc@x.com", "body": _HTML_BODY}})
    body = client.get("/api/leads/m1/body").json()
    assert body["ok"] is True and "<" not in body["text"]


# ── 6. POST /api/leads/{id}/create-estimate ───────────────────────────
_EMAIL_TEXT = "Bid invitation for Edgerton Logistics Center. Approx 12,500 SF of epoxy."


@pytest.fixture
def lead_text(monkeypatch, _no_live_seams):
    monkeypatch.setattr(leads, "fetch_email_text", lambda mid: {
        "ok": True, "subject": "Bid Invitation", "from": "gc@x.com",
        "text": _EMAIL_TEXT, "via": "detail"})


def _stub_cli(monkeypatch, result):
    """Replace the paid `claude -p` runner; records the system prompt it was
    handed so the two lead prompts can't be swapped by accident."""
    calls = []

    def fake(user_input, system_prompt=None):
        calls.append((user_input, system_prompt))
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(main, "_autofill_via_cli", fake)
    return calls


def test_create_estimate_saves_a_prefilled_draft(monkeypatch, db, inbox, lead_text):
    calls = _stub_cli(monkeypatch, {
        "project_name": "Edgerton LC - Building 4", "city": "Gardner",
        "state": "Kansas", "work_type": "polish", "system_1_sf": "1,250 sf",
        "contact_notes": "Tilt-up warehouse.", "cell_values": {"Epoxy!E20": 99},
    })
    out = client.post("/api/leads/m1/create-estimate").json()
    assert out["ok"] is True and out["existing"] is False and out["ai_used"] is True
    assert out["warning"] is None

    draft, = db["drafts"]
    assert draft["id"] == out["draft_id"]
    assert draft["owner_email"] == "tester@wetreadwell.com"
    blob = draft["data"]
    assert blob["project_name"] == "Edgerton LC - Building 4"
    assert blob["work_type"] == "polish" and blob["system_1_sf"] == 1250
    assert blob["city_state"] == "Gardner, KS"          # recomputed after the overlay
    assert blob["notes"] == _EMAIL_TEXT                 # the AI can't touch this
    assert blob["source"] == "email" and blob["lead_id"] == "m1"
    assert blob["lead_auto"] is False                   # a human pressed the button
    assert "cell_values" not in blob

    lead, = db["leads"]
    assert lead["lead_status"] == "estimate_created" and lead["draft_id"] == out["draft_id"]
    assert lead["extract"]["work_type"] == "polish"
    assert [c[1] for c in calls] == [leads._EXTRACT_SYSTEM_PROMPT]
    assert "Distance from the Olathe office: 20.0 mi" in calls[0][0]
    assert _EMAIL_TEXT in calls[0][0]
    assert "created_from_lead" in [e["action"] for e in db["events"]]


def test_create_estimate_still_ships_the_draft_when_the_ai_dies(monkeypatch, db, inbox, lead_text):
    _stub_cli(monkeypatch, RuntimeError("claude CLI exited with code 1"))
    out = client.post("/api/leads/m1/create-estimate").json()
    assert out["ok"] is True and out["ai_used"] is False
    assert "scraped fields only" in out["warning"]
    blob = db["drafts"][0]["data"]
    assert blob["project_name"] == "Edgerton Logistics Center"    # metadata leg only
    assert blob["notes"] == _EMAIL_TEXT
    assert db["leads"][0]["draft_id"] == out["draft_id"]


def test_create_estimate_rejects_a_non_object_from_the_ai(monkeypatch, db, inbox, lead_text):
    _stub_cli(monkeypatch, ["not", "an", "object"])
    out = client.post("/api/leads/m1/create-estimate").json()
    assert out["ok"] is True and out["ai_used"] is False and out["warning"]


def test_create_estimate_is_idempotent(monkeypatch, db, inbox, lead_text):
    calls = _stub_cli(monkeypatch, {"project_name": "Edgerton LC"})
    first = client.post("/api/leads/m1/create-estimate").json()
    second = client.post("/api/leads/m1/create-estimate").json()
    assert second["draft_id"] == first["draft_id"] and second["existing"] is True
    assert len(db["drafts"]) == 1
    assert len(calls) == 1                     # the repeat spends nothing


def test_create_estimate_reuses_a_grouped_siblings_draft(monkeypatch, db, inbox, lead_text):
    """The same invite arrives two or three times under different message ids.
    None of the copies may become a second project."""
    db["leads"].append({"id": "m1b", "lead_status": "estimate_created",
                        "draft_id": "d-sibling", "ai": {}})
    db["drafts"].append({"id": "d-sibling", "data": {"project_name": "Already drafted"},
                         "owner_email": "kyle@wetreadwell.com"})
    calls = _stub_cli(monkeypatch, {"project_name": "should not be used"})

    out = client.post("/api/leads/m1/create-estimate").json()
    assert out["ok"] is True and out["existing"] is True
    assert out["draft_id"] == "d-sibling"
    assert len(db["drafts"]) == 1 and calls == []


def test_create_estimate_404s_for_a_message_outside_the_inbox(db, inbox, lead_text):
    assert client.post("/api/leads/nope/create-estimate").status_code == 404


def test_create_estimate_downgrades_to_metadata_when_the_ai_budget_is_spent(
        monkeypatch, db, inbox, lead_text):
    """A spent budget must cost the estimator the AI read, never the project."""
    main._AUTOFILL_HITS["leadest|tester@wetreadwell.com"] = [time.time()] * 3
    calls = _stub_cli(monkeypatch, {"project_name": "unused"})
    out = client.post("/api/leads/m1/create-estimate").json()
    assert out["ok"] is True and out["ai_used"] is False
    assert "limit is reached" in out["warning"]
    assert calls == [] and db["drafts"][0]["data"]["project_name"] == "Edgerton Logistics Center"


# ── 7. POST /api/leads/{id}/prequalify ────────────────────────────────
_AI_SCORE = {"fit_score": 84, "recommendation": "pursue", "work_type_guess": "epoxy",
             "flooring_scope_present": True, "is_noise": False,
             "summary": "Warehouse epoxy, 20 mi from Olathe."}


def test_prequalify_scores_then_serves_the_cached_result(monkeypatch, db, inbox, lead_text):
    calls = _stub_cli(monkeypatch, _AI_SCORE)
    first = client.post("/api/leads/m1/prequalify").json()
    assert first["ok"] is True and first["cached"] is False
    assert first["ai"]["fit_score"] == 84
    assert [c[1] for c in calls] == [leads._PREQUAL_SYSTEM_PROMPT]

    second = client.post("/api/leads/m1/prequalify").json()
    assert second["ok"] is True and second["cached"] is True
    assert second["ai"]["fit_score"] == 84
    assert len(calls) == 1                      # reopening the drawer is free


def test_prequalify_force_reruns(monkeypatch, db, inbox, lead_text):
    calls = _stub_cli(monkeypatch, _AI_SCORE)
    client.post("/api/leads/m1/prequalify")
    forced = client.post("/api/leads/m1/prequalify?force=true").json()
    assert forced["cached"] is False and len(calls) == 2


def test_prequalify_seeds_the_category_but_never_overwrites_a_human(
        monkeypatch, db, inbox, lead_text):
    _stub_cli(monkeypatch, _AI_SCORE)
    client.post("/api/leads/m1/prequalify")
    assert db["leads"][0]["category"] == "epoxy"

    db["leads"].append({"id": "m2", "category": "gyp", "ai": {}})
    client.post("/api/leads/m2/prequalify?force=1")
    assert next(r for r in db["leads"] if r["id"] == "m2")["category"] == "gyp"


def test_prequalify_refunds_the_slot_when_the_ai_fails(monkeypatch, db, inbox, lead_text):
    _stub_cli(monkeypatch, RuntimeError("claude down"))
    for _ in range(5):
        out = client.post("/api/leads/m1/prequalify")
        assert out.status_code == 200            # never 429 — failures are refunded
        assert out.json()["ok"] is False


def test_prequalify_429s_once_the_budget_is_spent(monkeypatch, db, inbox, lead_text):
    _stub_cli(monkeypatch, _AI_SCORE)
    for _ in range(3):
        assert client.post("/api/leads/m1/prequalify?force=1").status_code == 200
    limited = client.post("/api/leads/m1/prequalify?force=1")
    assert limited.status_code == 429
    assert limited.json()["rate_limited"] is True


# ── 8. the autopilot sweep (called directly — the thread never runs) ──
class _Autopilot:
    """Stands in for main's two entry points so the sweep's decisions are
    observable without a CLI run, a DB, or a draft."""

    def __init__(self):
        self.scored, self.created, self.bells = [], [], []
        self.ai = {}
        self.existing = set()

    def prequalify(self, msg, actor_email=None):
        mid = str(msg.get("id"))
        self.scored.append((mid, actor_email))
        return self.ai.get(mid, {"fit_score": 10, "recommendation": "pass"})

    def create_estimate(self, msg, actor_email=None, auto=False):
        mid = str(msg.get("id"))
        self.created.append((mid, actor_email, auto))
        return {"ok": True, "draft_id": f"d-{mid}", "existing": mid in self.existing,
                "ai_used": True}


@pytest.fixture
def autopilot(monkeypatch, _no_live_seams):
    ap = _Autopilot()
    monkeypatch.setitem(leads_worker._HOOKS, "prequalify", ap.prequalify)
    monkeypatch.setitem(leads_worker._HOOKS, "create_estimate", ap.create_estimate)
    monkeypatch.setattr(leads_worker.notifications, "add_lead_estimate",
                        lambda did, title, body="": ap.bells.append((did, title, body)))
    monkeypatch.setattr(leads, "get_lead_states", lambda ids: {})
    monkeypatch.setenv("LEADS_AUTOPILOT", "create")
    monkeypatch.setenv("LEADS_AUTOCREATE_SCORE", "70")
    return ap


def _mixed_inbox():
    spam = dict(_full_msg("m_spam"), isSpam=True)
    reply = dict(_sparse_msg("m_reply"), communicationType="response")
    update = dict(_sparse_msg("m_upd"), communicationType="platform_update")
    return [_full_msg("m1"), spam, _sparse_msg("m2"), reply, update]


def test_sweep_scores_only_fresh_non_spam_bid_invites(monkeypatch, autopilot):
    _stub_inbox(monkeypatch, _mixed_inbox())
    leads_worker._sweep()
    assert [mid for mid, _ in autopilot.scored] == ["m1"]
    assert autopilot.scored[0][1] == leads_worker.ACTOR      # a server actor, not a person


def test_sweep_skips_a_lead_that_already_has_a_score(monkeypatch, autopilot):
    monkeypatch.setattr(leads, "get_lead_states",
                        lambda ids: {"m1": {"ai": {"fit_score": 40}}})
    _stub_inbox(monkeypatch, [_full_msg("m1")])
    leads_worker._sweep()
    assert autopilot.scored == []


def test_sweep_skips_trashed_and_already_drafted_leads(monkeypatch, autopilot):
    monkeypatch.setattr(leads, "get_lead_states", lambda ids: {
        "m1": {"lead_status": "trash"}, "m3": {"lead_status": "estimate_created"}})
    _stub_inbox(monkeypatch, [_full_msg("m1"), _full_msg("m3")])
    leads_worker._sweep()
    assert autopilot.scored == []


def test_a_weak_score_is_recorded_but_never_drafted(monkeypatch, autopilot):
    autopilot.ai["m1"] = {"fit_score": 69, "recommendation": "pursue"}
    _stub_inbox(monkeypatch, [_full_msg("m1")])
    leads_worker._sweep()
    assert autopilot.scored and autopilot.created == [] and autopilot.bells == []


def test_pursue_at_the_threshold_drafts_an_estimate_and_rings_the_bell(monkeypatch, autopilot):
    autopilot.ai["m1"] = {"fit_score": 70, "recommendation": "pursue",
                          "summary": "Warehouse epoxy."}
    _stub_inbox(monkeypatch, [_full_msg("m1")])
    leads_worker._sweep()
    assert autopilot.created == [("m1", leads_worker.ACTOR, True)]
    draft_id, title, body = autopilot.bells[0]
    assert draft_id == "d-m1" and title == "Edgerton Logistics Center"
    assert "Lemartec Corporation" in body and "fit 70" in body


def test_a_high_score_without_pursue_is_not_drafted(monkeypatch, autopilot):
    autopilot.ai["m1"] = {"fit_score": 95, "recommendation": "review"}
    _stub_inbox(monkeypatch, [_full_msg("m1")])
    leads_worker._sweep()
    assert autopilot.created == []


def test_an_unparseable_score_can_never_clear_the_bar(monkeypatch, autopilot):
    autopilot.ai["m1"] = {"fit_score": "very good", "recommendation": "pursue"}
    _stub_inbox(monkeypatch, [_full_msg("m1")])
    leads_worker._sweep()
    assert autopilot.created == []


def test_a_reused_grouped_draft_does_not_ring_the_bell(monkeypatch, autopilot):
    autopilot.ai["m1"] = {"fit_score": 90, "recommendation": "pursue"}
    autopilot.existing.add("m1")
    _stub_inbox(monkeypatch, [_full_msg("m1")])
    leads_worker._sweep()
    assert autopilot.created and autopilot.bells == []


def test_score_mode_scores_but_never_creates(monkeypatch, autopilot):
    monkeypatch.setenv("LEADS_AUTOPILOT", "score")
    autopilot.ai["m1"] = {"fit_score": 99, "recommendation": "pursue"}
    _stub_inbox(monkeypatch, [_full_msg("m1")])
    leads_worker._sweep()
    assert [mid for mid, _ in autopilot.scored] == ["m1"]
    assert autopilot.created == []


def test_the_DEFAULT_scores_but_never_creates(monkeypatch, autopilot):
    """With nothing set in the environment, the server must not create projects.

    THE BUG THIS EXISTS TO PREVENT. The default used to be `create`, and neither the prod nor
    the staging .env set the variable — so both ran armed. Eight of staging's fifteen Active
    projects were machine-made off real Basisboard invites, owned by nobody, sitting beside
    Kyle's and RJ's actual bids. Prod was equally armed and had simply not had a qualifying lead
    since its last restart.

    A project in the Active tab has to mean a person decided to bid the job. Hanz, 2026-08-07:
    "Wait for them to actually create that project from the lead inbox."

    The env vars on the box are a hand-edit and a rebuilt .env would silently re-arm it. This
    test is what makes the safe behaviour survive that.
    """
    monkeypatch.delenv("LEADS_AUTOPILOT", raising=False)     # the fixture sets it; unset it
    assert leads_worker._mode() == "score"
    autopilot.ai["m1"] = {"fit_score": 99, "recommendation": "pursue"}
    _stub_inbox(monkeypatch, [_full_msg("m1")])
    leads_worker._sweep()
    assert [mid for mid, _ in autopilot.scored] == ["m1"], "scoring must stay on"
    assert autopilot.created == [], "the server created a project nobody asked for"
    assert autopilot.bells == []


@pytest.mark.parametrize("value", ["", "   ", "Create ", "CREATE", "yes", "true", "1", "auto"])
def test_only_the_exact_word_create_arms_auto_creation(monkeypatch, autopilot, value):
    """A typo, a leftover, or a well-meant "true" must fall back to score rather than arm the
    thing. Falling back to `create` on an unrecognised value is how a one-character mistake in a
    .env turns into projects nobody asked for.

    "CREATE" and "Create " ARE accepted — the read lowercases and strips, which is deliberate.
    """
    monkeypatch.setenv("LEADS_AUTOPILOT", value)
    expected = "create" if value.strip().lower() == "create" else "score"
    assert leads_worker._mode() == expected, (
        "LEADS_AUTOPILOT=%r resolved to %r" % (value, leads_worker._mode()))


def test_off_mode_does_nothing_at_all(monkeypatch, autopilot):
    monkeypatch.setenv("LEADS_AUTOPILOT", "off")
    monkeypatch.setattr(bb, "get_inbox", _boom("get_inbox in off mode"))
    leads_worker._sweep()
    assert autopilot.scored == [] and autopilot.created == []


def test_off_mode_never_spawns_the_thread(monkeypatch):
    monkeypatch.setenv("LEADS_AUTOPILOT", "off")
    assert _REAL_ENSURE_STARTED(create_estimate=lambda **k: None,
                                prequalify=lambda **k: None) is False
    assert leads_worker._THREAD is None


def test_sweep_honours_the_batch_size(monkeypatch, autopilot):
    monkeypatch.setenv("LEADS_AUTOPILOT_BATCH", "2")
    _stub_inbox(monkeypatch, [_full_msg(f"m{i}") for i in range(5)])
    leads_worker._sweep()
    assert len(autopilot.scored) == 2


def test_sweep_takes_the_oldest_lead_first(monkeypatch, autopilot):
    monkeypatch.setenv("LEADS_AUTOPILOT_BATCH", "1")
    newer = dict(_full_msg("new"), createdAt="2026-07-28T10:00:00.000Z")
    older = dict(_full_msg("old"), createdAt="2026-07-20T10:00:00.000Z")
    _stub_inbox(monkeypatch, [newer, older])
    leads_worker._sweep()
    assert [mid for mid, _ in autopilot.scored] == ["old"]


def test_a_failing_lead_backs_the_sweep_off_instead_of_killing_the_thread(
        monkeypatch, autopilot):
    monkeypatch.setitem(leads_worker._HOOKS, "prequalify", _boom("CLI auth expired"))
    _stub_inbox(monkeypatch, [_full_msg("m1"), _full_msg("m3")])
    leads_worker._sweep()                                   # must not raise
    assert leads_worker._ATTEMPTS["m1"] == 1
    assert leads_worker._QUIET_UNTIL > 0                    # and the next sweep waits

    leads_worker._sweep()
    assert autopilot.scored == []                           # quiet period respected


def test_a_poison_lead_stops_being_a_candidate(monkeypatch, autopilot):
    _stub_inbox(monkeypatch, [_full_msg("m1")])
    leads_worker._ATTEMPTS["m1"] = leads_worker._MAX_ATTEMPTS
    leads_worker._sweep()
    assert autopilot.scored == []


def test_sweep_is_a_noop_when_basisboard_is_down(monkeypatch, autopilot):
    monkeypatch.setattr(bb, "get_inbox", lambda status="unlinked": {
        "ok": False, "configured": True, "messages": [], "stats": {}})
    leads_worker._sweep()
    assert autopilot.scored == []


# ── regressions: two bugs found in review, fixed before the first deploy ───────
def test_trashing_the_auto_draft_frees_the_lead_to_try_again(monkeypatch, db, inbox, lead_text):
    """The documented remedy for a misread email is "bin the draft". That only
    works if a trashed draft stops counting as the lead's estimate — otherwise
    create-estimate keeps handing back an id the Projects list won't show."""
    _stub_cli(monkeypatch, {"project_name": "Edgerton LC"})
    first = client.post("/api/leads/m1/create-estimate").json()
    assert first["existing"] is False

    for row in db["drafts"]:                       # the estimator bins it
        if row["id"] == first["draft_id"]:
            row["deleted_at"] = "2026-07-29T00:00:00Z"

    second = client.post("/api/leads/m1/create-estimate").json()
    assert second["ok"] is True and second["existing"] is False
    assert second["draft_id"] != first["draft_id"]
    assert len(db["drafts"]) == 2


def test_an_empty_but_successful_extract_still_costs_a_slot(monkeypatch, db, inbox, lead_text):
    """The extract prompt is told to omit whatever it can't find, so {} is an
    honest answer from a 20-30s paid run. Refunding it would make a thin invite
    infinitely retryable."""
    bucket = "leadest|tester@wetreadwell.com"
    main._AUTOFILL_HITS.pop(bucket, None)
    calls = _stub_cli(monkeypatch, {})             # ran fine, found nothing

    out = client.post("/api/leads/m1/create-estimate").json()
    assert out["ok"] is True and len(calls) == 1
    assert out["ai_used"] is False and out["ai_ran"] is True
    assert len(main._AUTOFILL_HITS.get(bucket, [])) == 1


def test_a_failed_extract_hands_the_slot_back(monkeypatch, db, inbox, lead_text):
    """The other side of the same coin: the call never landed, so it's free."""
    bucket = "leadest|tester@wetreadwell.com"
    main._AUTOFILL_HITS.pop(bucket, None)
    _stub_cli(monkeypatch, RuntimeError("claude exploded"))

    out = client.post("/api/leads/m1/create-estimate").json()
    assert out["ok"] is True and out["ai_used"] is False and out["ai_ran"] is False
    assert out["warning"]
    assert main._AUTOFILL_HITS.get(bucket, []) == []


def test_an_autopilot_lead_is_flagged_as_machine_made(db):
    """leads.js prints "Drafted automatically" off this flag. The autopilot is
    already the actor on its own rows, so nothing extra is stored."""
    states = {"m1": {"lead_status": "estimate_created", "draft_id": "d1",
                     "status_by": leads.AUTOPILOT_ACTOR, "ai": {}},
              "m2": {"lead_status": "estimate_created", "draft_id": "d2",
                     "status_by": "kyle@wetreadwell.com", "ai": {}}}
    rows = {r["id"]: r for r in leads.merge_inbox([_full_msg(), _sparse_msg()], states)}
    assert rows["m1"]["lead_auto"] is True
    assert rows["m2"]["lead_auto"] is False
