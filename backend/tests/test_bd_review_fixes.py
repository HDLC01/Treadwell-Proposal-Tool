"""Regression tests for BD's Phase 2 review findings, one block per finding id, on the tool's app (#809).

BD's test_review_fixes, ported. Each test keeps its finding's id (SEC-*, C*, DATA-*) so a regression
points straight back at the review. Every route is now under /api/bd/; people are the fixture seed's
(bd/ops/fixture_seed.py) or a made-up team in an empty BD database. Every person and file here is
made up (555-01xx phones, example.com emails, workbooks built with openpyxl or zipfile in the test).

What changed on the way:
  * C6 (AI is off unless asked for): BD's AI setting was not carried (#802), so the check is that
    ai_enabled is false and that the BD package reads no AI setting at all.
  * C7 (no "method_not_allowed"): BD's own catch-all answers a wrong method under /api/bd/; an
    OPTIONS or a path outside /api/bd/ is the proposal tool's own answer (test_bd_app_shell.py).
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import pathlib
import threading
import time
import zipfile

import psycopg
import pytest

from _bd_conftest import bd_token_headers
from bd import db as dbmod
from bd.ops import import_workbook as iw
from test_bd_import_workbook import ok_import, upload, workbook_bytes

BACKEND = pathlib.Path(__file__).resolve().parents[1]
TODAY = "2026-11-04"


@pytest.fixture
def team(bd_client, bd_db, bd_today):
    """Avery (salesperson), Casey (assistant) and Frankie (super admin) in an empty BD database."""
    bd_today(TODAY)
    for email, name, role in (("avery.quill@example.com", "Avery Quill", "salesperson"),
                              ("casey.moret@example.com", "Casey Moret", "assistant"),
                              ("frankie.oduya@example.com", "Frankie Oduya", "super_admin")):
        bd_db.execute("insert into bd.users (email, name, role) values (%s, %s, %s)", (email, name, role))
    return {r["name"].split()[0].lower(): r for r in bd_db.execute("select * from bd.users order by id").fetchall()}


def envelope(r, status, code):
    assert r.status_code == status, r.text
    body = r.json()
    assert body["ok"] is False and body["error"] == code and body["message"].endswith(".")
    return body


# ── SEC-1: the upload is capped while it streams ─────────────────────────────────────────────
def _asgi_post(app, path, headers, chunks):
    """Drive the ASGI app directly (TestClient reads a streamed body in full before the app sees
    it). Returns (status, json body, request bytes the app pulled)."""
    pulled = 0
    sent = []
    source = iter(chunks)

    async def receive():
        nonlocal pulled
        try:
            chunk = next(source)
        except StopIteration:
            return {"type": "http.request", "body": b"", "more_body": False}
        pulled += len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": True}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
             "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
             "root_path": "", "client": ("127.0.0.1", 50000), "server": ("testserver", 80),
             "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()]}
    asyncio.run(app(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, json.loads(body), pulled


def _multipart(boundary, name, payload_chunks, tail=True):
    yield ("--%s\r\nContent-Disposition: form-data; name=\"dry_run\"\r\n\r\ntrue\r\n" % boundary).encode()
    yield ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
           "Content-Type: text/csv\r\n\r\n" % (boundary, name)).encode()
    yield from payload_chunks
    if tail:
        yield ("\r\n--%s--\r\n" % boundary).encode()


def _headers(boundary):
    h = {"content-type": "multipart/form-data; boundary=%s" % boundary}     # no Content-Length: chunked
    h.update({k.lower(): v for k, v in bd_token_headers("casey.moret@example.com").items()})
    return h


def test_sec1_a_chunked_body_is_refused_once_it_passes_the_limit(team, bd_app):
    chunk = b"a" * (64 * 1024)
    endless = (chunk for _ in range(60 * 16))                                # 60 MB, never all read
    status, body, pulled = _asgi_post(bd_app.app, "/api/bd/admin/import", _headers("SEC1"),
                                      _multipart("SEC1", "big.csv", endless))
    assert status == 413 and body == {"ok": False, "error": "bad_request",
                                      "message": "That file is too big. The limit is 10 MB.",
                                      "fields": {"file": "Pick a smaller file."}}
    # Stopped as soon as the count passed the limit plus the envelope's slack (one chunk late at most).
    assert pulled <= iw.MAX_BYTES + 64 * 1024 + 2 * len(chunk), pulled


def test_sec1_a_small_chunked_upload_still_imports(team, bd_app):
    rows = [b"Company,Name,Email\n", b"Northvane Plastics,Lou Kim,lou.kim@northvane.example.com\n"]
    status, body, _ = _asgi_post(bd_app.app, "/api/bd/admin/import", _headers("SEC1ok"),
                                 _multipart("SEC1ok", "people.csv", iter(rows)))
    assert status == 200, body
    assert body["import"]["created"] == 1 and body["import"]["dry_run"] is True


def test_sec1_a_refused_role_never_has_its_body_read(team, bd_app, bd_db):
    """The role check comes before the upload is read: a manager's 60 MB stream is refused unread."""
    bd_db.execute("insert into bd.users (email, name, role) values ('devon.hale@example.com', 'Devon Hale', 'manager')")
    h = _headers("SEC1m")
    h["authorization"] = bd_token_headers("devon.hale@example.com")["Authorization"]
    endless = (b"a" * (64 * 1024) for _ in range(60 * 16))
    status, body, pulled = _asgi_post(bd_app.app, "/api/bd/admin/import", h, _multipart("SEC1m", "big.csv", endless))
    assert (status, body["message"]) == (403, "Your role can't do that.")
    assert pulled == 0


# ── SEC-2: a compressed workbook cannot pin the parser or a pooled connection ───────────────────
def _zip(parts):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in parts.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_sec2_a_huge_shared_strings_part_is_refused_before_parsing(team, bd_as_user):
    bomb = _zip({"[Content_Types].xml": b"<Types/>", "xl/sharedStrings.xml": b"<si><t>x</t></si>" * 1_400_000})
    assert len(bomb) < iw.MAX_BYTES
    start = time.monotonic()
    r = upload(bd_as_user("casey.moret@example.com"), bomb)
    assert envelope(r, 413, "bad_request")["message"] == "That workbook is too big to read."
    assert time.monotonic() - start < 10


def test_sec2_a_part_compressed_more_than_100_times_is_refused():
    data = _zip({"xl/worksheets/sheet1.xml": b"\0" * (5 * 1024 * 1024)})       # ~1000x, under 20 MB
    with pytest.raises(iw.ImportFileError) as exc:
        iw.check_zip(data)
    assert exc.value.status == 413


def test_sec2_an_ordinary_workbook_passes_the_zip_checks():
    iw.check_zip(workbook_bytes())
    with zipfile.ZipFile(io.BytesIO(workbook_bytes())) as zf:
        assert max(i.file_size for i in zf.infolist()) < iw.MAX_PART_UNPACKED


def test_sec2_the_file_is_parsed_with_no_database_connection_held(team, bd_as_user, monkeypatch):
    open_now = {"n": 0}
    seen = {}
    real_connect, real_parse = dbmod.connect, iw.parse_file

    @contextlib.contextmanager
    def counting_connect(*a, **kw):
        with real_connect(*a, **kw) as conn:
            open_now["n"] += 1
            try:
                yield conn
            finally:
                open_now["n"] -= 1

    def watching_parse(*a, **kw):
        seen["open_during_parse"] = open_now["n"]
        return real_parse(*a, **kw)

    monkeypatch.setattr(dbmod, "connect", counting_connect)
    monkeypatch.setattr(iw, "parse_file", watching_parse)
    ok_import(upload(bd_as_user("casey.moret@example.com"), workbook_bytes()))
    assert seen == {"open_during_parse": 0}


# ── C1: a PATCH that makes a touch meets the promised date and next step ─────────────────────
def test_c1_patch_to_answered_clears_a_met_promise_and_next_step(bd_seeded, bd_as_user, bd_db):
    bd_db.execute("update bd.contacts set promised_date = '2026-11-03', next_step = 'Call',"
                  " next_step_date = '2026-11-03' where id = 32")
    avery = bd_as_user(1)
    r = avery.post("/api/bd/contacts/32/interactions",
                   json={"kind": "voicemail", "occurred_at": "2026-11-04T10:05:00-06:00"})
    assert r.status_code == 200, r.text
    iid = r.json()["interaction"]["id"]
    assert avery.get("/api/bd/contacts/32").json()["contact"]["promised_date"] == "2026-11-03"   # a voicemail meets nothing
    r = avery.patch("/api/bd/interactions/%d" % iid, json={"outcome": "answered"})
    assert r.status_code == 200 and r.json()["interaction"]["counts_as_touch"] is True
    c = avery.get("/api/bd/contacts/32").json()["contact"]
    assert c["last_live_at"] == "2026-11-04T10:05:00-06:00"
    assert (c["promised_date"], c["next_step"], c["next_step_date"]) == (None, None, None)


# ── C2: a kind change sets the direction the contract allows ────────────────────────────────
def test_c2_a_kind_change_fixes_the_direction(bd_seeded, bd_as_user):
    avery = bd_as_user(1)
    call = avery.post("/api/bd/contacts/32/interactions", json={"kind": "call", "outcome": "no_answer"}).json()
    assert call["interaction"]["direction"] == "out"
    r = avery.patch("/api/bd/interactions/%d" % call["interaction"]["id"], json={"kind": "meeting"})
    assert r.status_code == 200 and r.json()["interaction"]["kind"] == "meeting"
    assert r.json()["interaction"]["direction"] is None
    note = avery.post("/api/bd/contacts/32/interactions", json={"kind": "note", "summary": "Left a card."}).json()
    assert note["interaction"]["direction"] is None
    r = avery.patch("/api/bd/interactions/%d" % note["interaction"]["id"], json={"kind": "call", "outcome": "answered"})
    assert r.status_code == 200 and r.json()["interaction"]["direction"] == "out"


# ── C3: one paging rule on every list ───────────────────────────────────────────────────────
@pytest.mark.parametrize("path", ["/api/bd/admin/unmatched-calls", "/api/bd/admin/imports", "/api/bd/contacts",
                                  "/api/bd/users", "/api/bd/admin/users"])
@pytest.mark.parametrize("limit", ["0", "501", "100000"])
def test_c3_a_zero_or_large_limit_is_the_default_or_the_cap(bd_seeded, bd_as_user, path, limit):
    r = bd_as_user(6).get(path + "?limit=" + limit)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True and "total" in r.json()


@pytest.mark.parametrize("path,total", [("/api/bd/users", 6), ("/api/bd/admin/users", 7)])
def test_c3_the_user_lists_page(bd_seeded, bd_as_user, path, total):
    c = bd_as_user(6)
    full = c.get(path).json()
    assert full["total"] == len(full["items"]) == total
    page = c.get(path + "?limit=1&offset=1").json()
    assert page["total"] == total and [u["id"] for u in page["items"]] == [full["items"][1]["id"]]


# ── C4: a path id that cannot name a row is a 404 everywhere ────────────────────────────────
@pytest.mark.parametrize("who,method,path", [
    (1, "GET", "/api/bd/contacts/abc"), (1, "POST", "/api/bd/contacts/abc/confirm"),
    (1, "POST", "/api/bd/contacts/abc/archive"), (1, "GET", "/api/bd/companies/abc"),
    (6, "PATCH", "/api/bd/admin/users/abc"), (3, "POST", "/api/bd/admin/unmatched-calls/abc/dismiss"),
    (3, "POST", "/api/bd/admin/unmatched-calls/abc/attach"),
    (1, "POST", "/api/bd/tasks/abc/done"), (1, "PATCH", "/api/bd/interactions/abc"),
    (1, "GET", "/api/bd/contacts/abc/interactions"),
])
def test_c4_non_numeric_ids_are_404(bd_seeded, bd_as_user, who, method, path):
    r = bd_as_user(who).request(method, path, json={} if method != "GET" else None)
    envelope(r, 404, "not_found")


# ── C5: another salesperson may flag "not the right person" (no own-list check) ──────────────
def test_c5_another_salesperson_may_flag_not_the_right_person(bd_seeded, bd_as_user, bd_db):
    """Task 301 (Hal Brecken, contact 30) is on Avery's (1) list. Blair (2), another salesperson, may
    not tick it done (the own-list check), but may flag Hal as not the right person: a data fix, not
    a list action. The Kaw Valley row stays open (#828): Nora is still there to call."""
    envelope(bd_as_user(2).post("/api/bd/tasks/301/done", json={}), 403, "forbidden")
    r = bd_as_user(2).post("/api/bd/tasks/301/not-right-person", json={"note": "Hal retired."})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["task"]["id"], body["task"]["status"]) == (301, "open")
    assert (body["contact"]["id"], body["contact"]["confirmed"]) == (30, False)
    ev = bd_db.execute("select kind, actor_id, contact_id, detail from bd.events").fetchall()
    assert ev == [{"kind": "unconfirmed", "actor_id": 2, "contact_id": 30, "detail": "Hal retired."}]


# ── C6: AI is off; BD reads no AI setting (#802 did not carry it) ──────────────────────────────
def test_c6_ai_enabled_is_false_and_no_ai_setting_is_read(team, bd_as_user, bd_db, monkeypatch):
    from bd import appsettings

    monkeypatch.setenv("AI_ENABLED", "true")
    monkeypatch.setenv("BD_AI_ENABLED", "true")
    r = bd_as_user("avery.quill@example.com").get("/api/bd/settings")
    assert r.status_code == 200 and r.json()["settings"]["ai_enabled"] is False
    assert appsettings.load(bd_db)["ai_enabled"] is False
    sources = "\n".join(p.read_text(encoding="utf-8") for p in (BACKEND / "bd").rglob("*.py"))
    assert "AI_ENABLED" not in sources


# ── C7: no "method_not_allowed" in BD's envelope ─────────────────────────────────────────────
@pytest.mark.parametrize("method,path", [("PUT", "/api/bd/contacts"), ("DELETE", "/api/bd/admin/users"),
                                         ("GET", "/api/bd/admin/import"), ("POST", "/api/bd/admin/telephony")])
def test_c7_a_wrong_method_is_a_400_bad_request(bd_seeded, bd_as_user, method, path):
    body = envelope(bd_as_user(6).request(method, path), 400, "bad_request")
    assert body["message"] == "%s is not allowed on %s." % (method, path)


# ── DATA-1: re-importing never undoes what happened in the app ─────────────────────────────────
def _one_row(**over):
    row = {"Company Name": "Wexford Coatings", "Contact Name": "Lee Tran", "Title": "Facilities Lead",
           "Phone": "816-555-0161", "Email": "lee.tran@wexford.example.com", "Stage": "Met",
           "Next Step": "Send the coating quote", "Next Step Date": "2026-11-03", "Owner": "Avery"}
    row.update(over)
    return workbook_bytes(bd=[row], maint=[])


def _contact(db):
    return db.execute("select * from bd.contacts where email_lower = 'lee.tran@wexford.example.com'").fetchone()


def test_data1_reimport_does_not_bring_back_a_met_next_step(team, bd_as_user, bd_db):
    casey, avery = bd_as_user("casey.moret@example.com"), bd_as_user("avery.quill@example.com")
    assert ok_import(upload(casey, _one_row(), dry_run="false"))["created"] == 1
    cid = _contact(bd_db)["id"]
    r = avery.post("/api/bd/contacts/%d/interactions" % cid,
                   json={"kind": "call", "outcome": "answered", "occurred_at": "2026-11-04T09:00:00-06:00"})
    assert r.status_code == 200, r.text
    assert (_contact(bd_db)["next_step"], _contact(bd_db)["next_step_date"]) == (None, None)
    again = ok_import(upload(casey, _one_row(), dry_run="false"))
    assert (again["created"], again["updated"], again["skipped"]) == (0, 0, 1)
    assert (_contact(bd_db)["next_step"], _contact(bd_db)["next_step_date"]) == (None, None)


def test_data1_a_met_step_stays_cleared_even_with_no_import_record(team, bd_as_user, bd_db):
    """The touch rule holds by itself: a step dated on or before a logged touch never returns."""
    casey, avery = bd_as_user("casey.moret@example.com"), bd_as_user("avery.quill@example.com")
    ok_import(upload(casey, _one_row(), dry_run="false"))
    cid = _contact(bd_db)["id"]
    avery.post("/api/bd/contacts/%d/interactions" % cid, json={"kind": "meeting", "occurred_at": "2026-11-04T09:00:00-06:00"})
    bd_db.execute("update bd.contacts set import_values = '{}'::jsonb where id = %s", (cid,))
    ok_import(upload(casey, _one_row(), dry_run="false"))
    assert (_contact(bd_db)["next_step"], _contact(bd_db)["next_step_date"]) == (None, None)


def test_data1_an_app_edit_wins_until_the_file_changes_that_field(team, bd_as_user, bd_db):
    casey, avery = bd_as_user("casey.moret@example.com"), bd_as_user("avery.quill@example.com")
    ok_import(upload(casey, _one_row(), dry_run="false"))
    cid = _contact(bd_db)["id"]
    r = avery.patch("/api/bd/contacts/%d" % cid, json={"title": "Plant Manager", "phone": "913-555-0162"})
    assert r.status_code == 200, r.text
    same = ok_import(upload(casey, _one_row(), dry_run="false"))
    assert (same["updated"], same["skipped"]) == (0, 1)
    c = _contact(bd_db)
    assert (c["title"], c["phone"]) == ("Plant Manager", "913-555-0162")
    # The sheet now says something new for the title: that is newer news, so it is written.
    changed = ok_import(upload(casey, _one_row(Title="Operations Director"), dry_run="false"))
    assert changed["updated"] == 1
    c = _contact(bd_db)
    assert (c["title"], c["phone"]) == ("Operations Director", "913-555-0162")
    assert c["import_values"]["title"] == "Operations Director"
    assert c["import_values"]["next_step_date"] == "2026-11-03"


def test_data1_a_dry_run_leaves_the_import_record_alone(team, bd_as_user, bd_db):
    casey = bd_as_user("casey.moret@example.com")
    ok_import(upload(casey, _one_row(), dry_run="false"))
    before = _contact(bd_db)["import_values"]
    ok_import(upload(casey, _one_row(Title="Somebody Else"), dry_run="true"))
    assert _contact(bd_db)["import_values"] == before


# ── DATA-2: one company per normalized name, however many adds race ─────────────────────────
def test_data2_concurrent_find_or_create_makes_one_company(bd_db, bd_client, monkeypatch):
    from bd import contacts_service
    from bd.normalize import normalize_company

    real_insert = contacts_service.insert_company

    def slow_insert(conn, *a, **kw):
        time.sleep(0.3)                     # widen the window between the look and the insert
        return real_insert(conn, *a, **kw)

    monkeypatch.setattr(contacts_service, "insert_company", slow_insert)
    barrier = threading.Barrier(2)
    got, failures = [], []

    def add(name):
        try:
            barrier.wait(timeout=10)
            with dbmod.connect() as conn:
                got.append(contacts_service.resolve_company(conn, {"name": name})["id"])
        except Exception as exc:  # reported below
            failures.append(exc)

    threads = [threading.Thread(target=add, args=(n,))
               for n in ("Thornbury Cold Storage", " thornbury  cold storage, inc. ")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not failures, failures
    assert len(set(got)) == 1
    n = bd_db.execute("select count(*) as n from bd.companies where normalized_name = %s",
                      (normalize_company("Thornbury Cold Storage"),)).fetchone()["n"]
    assert n == 1


# ── DATA-3: a timestamp near year 1 is a 400, not a 500 ───────────────────────────────────────
ANCIENT = "0001-01-01T00:00:00+05:00"


def test_data3_post_and_patch_with_an_ancient_occurred_at_are_400(bd_seeded, bd_as_user):
    avery = bd_as_user(1)
    r = avery.post("/api/bd/contacts/21/interactions", json={"kind": "call", "outcome": "answered",
                                                             "occurred_at": ANCIENT})
    assert envelope(r, 400, "bad_request")["fields"] == {"occurred_at": "Use a date and time (ISO 8601)."}
    iid = avery.post("/api/bd/contacts/21/interactions", json={"kind": "note", "summary": "x"}).json()["interaction"]["id"]
    r = bd_as_user(6).patch("/api/bd/interactions/%d" % iid, json={"occurred_at": ANCIENT})
    assert envelope(r, 400, "bad_request")["fields"] == {"occurred_at": "Use a date and time (ISO 8601)."}
    r = avery.post("/api/bd/contacts/21/interactions",
                   json={"kind": "call", "outcome": "answered", "occurred_at": "1985-06-01T12:00:00-05:00"})
    assert envelope(r, 400, "bad_request")["fields"] == {"occurred_at": "Use a date from 1990 on."}


# ── DATA-4: a contact's events are never deleted with it ─────────────────────────────────────
def test_data4_deleting_a_contact_with_events_is_refused(team, bd_as_user, bd_db):
    casey = bd_as_user("casey.moret@example.com")
    r = casey.post("/api/bd/contacts", json={"name": "Lee Tran", "company": {"name": "Wexford Coatings"},
                                             "email": "lee.tran@wexford.example.com", "phone": "816-555-0161"})
    assert r.status_code in (200, 201), r.text
    cid = r.json()["contact"]["id"]
    assert casey.post("/api/bd/contacts/%d/archive" % cid, json={}).status_code == 200
    n = bd_db.execute("select count(*) as n from bd.events where contact_id = %s", (cid,)).fetchone()["n"]
    assert n >= 2
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        bd_db.execute("delete from bd.contacts where id = %s", (cid,))
    assert bd_db.execute("select count(*) as n from bd.events where contact_id = %s", (cid,)).fetchone()["n"] == n


def test_data4_the_schema_says_no_cascade(bd_db):
    rule = bd_db.execute(
        "select c.confdeltype from pg_constraint c join pg_namespace n on n.oid = c.connamespace"
        " where n.nspname = 'bd' and c.conname = 'events_contact_id_fkey'").fetchone()
    assert rule["confdeltype"] == "a"                                       # NO ACTION
