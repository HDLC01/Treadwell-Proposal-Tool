"""The cut-over copy, reverse, and the BD-only state it carries through a rollback (#812).

    python -m bd.ops.cutover reverse --record PATH     (bd/ops/cutover.py)

The old database is built from BD's ORIGINAL four migrations with made-up rows (tests/_bd_old_source.py),
copied forward into a fresh schema bd, changed in the tool through the tool's own BD API (#808's Add
contact, the call logger, and #811's real Merge, Undo and Keep separate), then copied back. The tool
side is always the bd_app-like test login.

THE TOOL-SIDE CHANGES (tool_changes below), worked by hand on the fixture before any code ran:
    Marlo (salesperson, user 1) adds Ondine at 48 Velvetleaf Dental      -> contact 76 (the old
        sequence had handed out 75, so the tool goes on from 76), and Fennimore at a new account
        "Brackenfold Roofing" -> company 49, contact 77; logs a call on 51 and a voicemail on 77.
    Tamsin (assistant, user 2) keeps 46 + 48 separate, then merges
        40 Juniper Ridge Const. LLC   into 41, keeping 41's name     (Thessaly 51 moves to 41)
        42 Harrow & Finch Glazing Inc. into 43, keeping 42's name, then UNDOES it
        46 Quarry Lane Storage        into 47, keeping 47's name     (Wilhelmina 57 moves to 47)
    and keeps 44 + 45 separate.
So schema bd holds two merge marks (40 -> 41 and 46 -> 47, both by user 2) and two kept pairs
(44 + 45 and 46 + 48), and the old app has no column for either: they go to bd_carry.

What is expected is read from the databases plainly, or worked out above, never recomputed by the
command's own checksum code.
"""
from __future__ import annotations

import json
import time

import pytest

import _bd_db
import _bd_old_source as src
from _bd_old_source import columns_of, dbs, refused_lines, rows, scalar, templates  # noqa: F401  (fixtures)
from bd.ops import cutover

EXIT_OK, EXIT_ERROR, EXIT_REFUSED, EXIT_MISMATCH, EXIT_FREEZE = 0, 1, 3, 4, 5
OLD_TABLES = list(src.ROWS)
MARLO, TAMSIN = "marlo.quint@example.com", "tamsin.okafor@example.com"
MERGE = "/api/bd/contacts/accounts/%s/merge"
UNDO = "/api/bd/contacts/accounts/merges/%s/undo"
KEEP = "/api/bd/contacts/accounts/duplicates/keep"

# What the tool side adds, all made up: the command must print none of it.
NEW_PEOPLE = [
    {"company": {"id": 48}, "name": "Ondine Ravensworth", "email": "ondine@velvetleaf.example.com",
     "phone": "913-555-0161", "title": "Office Manager ZQ", "notes": "Met at the ZQ expo."},
    {"company": {"name": "Brackenfold Roofing"}, "name": "Fennimore Quayle",
     "email": "fennimore@brackenfold.example.com", "phone": "816-555-0162", "notes": "Wants a ZQ quote."},
]
NEW_PERSONAL = sorted({p[k] for p in NEW_PEOPLE for k in ("name", "email", "phone")})


@pytest.fixture
def api(dbs, bd_app):
    """The tool's own BD API on the copied schema bd, as the bd_app-like login: sign in by email."""
    from fastapi.testclient import TestClient

    from _bd_conftest import BDAuthedClient
    from bd import db as dbmod

    previous = dbmod.configure(dbs.app)
    client = TestClient(bd_app.app, raise_server_exceptions=False)
    try:
        yield lambda email: BDAuthedClient(client, {"email": email})
    finally:
        dbmod.configure(previous)


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def merge(api, loser, into, name_from):
    return ok(api(TAMSIN).post(MERGE % loser, json={"into": into, "name_from": name_from}))["merge"]["id"]


def keep(api, a, b):
    ok(api(TAMSIN).post(KEEP, json={"accounts": [a, b]}))


def tool_changes(api):
    """THE TOOL-SIDE CHANGES of the module docstring. Returns {name: merge event id}."""
    marlo = api(MARLO)
    added = [ok(marlo.post("/api/bd/contacts", json=p), 201)["contact"]["id"] for p in NEW_PEOPLE]
    assert added == [76, 77]
    ok(marlo.post("/api/bd/contacts/51/interactions",
                  json={"kind": "call", "outcome": "answered", "direction": "out", "summary": "Talked ZQ terms."}))
    ok(marlo.post("/api/bd/contacts/77/interactions", json={"kind": "voicemail", "summary": "Left a ZQ note."}))
    keep(api, 46, 48)
    merges = {"juniper": merge(api, 40, 41, 41), "harrow": merge(api, 42, 43, 42),
              "quarry": merge(api, 46, 47, 47)}
    ok(api(TAMSIN).post(UNDO % merges["harrow"]))
    keep(api, 44, 45)
    return merges


# ── plain readings (not the command's code) ─────────────────────────────────────────────────────
def old_everything(url):
    """Every row of every table the old app has, its ledger, its sequences, and whether bd_carry exists."""
    out = {t: rows(url, "public", t, columns_of(url, "public", t)) for t in OLD_TABLES + ["schema_migrations"]}
    out["sequences"] = scalar(url, "select array_agg(array[sequencename, last_value::text] order by sequencename)"
                                   " from pg_sequences where schemaname = 'public'")
    out["bd_carry"] = scalar(url, "select to_regnamespace('bd_carry') is not null")
    return out


def tool_everything(url):
    with _bd_db.connect(url) as conn:
        tables = [r[0] for r in conn.execute("select relname from pg_class where relnamespace = 'bd'::regnamespace"
                                             " and relkind = 'r' order by 1").fetchall()]
    out = {t: rows(url, "bd", t, columns_of(url, "bd", t)) for t in tables if t != "account_pairs_kept"}
    out["account_pairs_kept"] = src.table_rows(url, "bd", "account_pairs_kept",
                                               columns_of(url, "bd", "account_pairs_kept"), "account_a, account_b")
    return out


def marks(url):
    """Schema bd's merge marks: (account, merged into, when, by)."""
    with _bd_db.connect(url) as conn:
        conn.execute("set timezone = 'UTC'")
        return [tuple(r) for r in conn.execute(
            "select id, merged_into, merged_at::text, merged_by from bd.companies where merged_into is not null"
            " order by id").fetchall()]


def kept(url):
    with _bd_db.connect(url) as conn:
        conn.execute("set timezone = 'UTC'")
        return [tuple(r) for r in conn.execute(
            "select account_a, account_b, decided_by, decided_at::text from bd.account_pairs_kept"
            " order by 1, 2").fetchall()]


def people_at(url, company_id):
    with _bd_db.connect(url) as conn:
        return [r[0] for r in conn.execute("select id from bd.contacts where company_id = %s order by id",
                                           (company_id,)).fetchall()]


def empty_schema_bd(url):
    """What Hanz's re-cut-over does first: the admin login empties schema bd's tables, the ledger stays."""
    with _bd_db.connect(url) as conn:
        tables = [r[0] for r in conn.execute("select relname from pg_class where relnamespace = 'bd'::regnamespace"
                                             " and relkind = 'r' and relname <> 'schema_migrations'").fetchall()]
        conn.execute("truncate " + ", ".join("bd." + t for t in tables))


def bd_carry(url):
    """The old database's bd_carry, read plainly: ({account: (into, when, by, people)}, [kept pairs])."""
    with _bd_db.connect(url) as conn:
        conn.execute("set timezone = 'UTC'")
        m = {r[0]: tuple(r[1:]) for r in conn.execute(
            "select company_id, merged_into, merged_at::text, merged_by, people from bd_carry.merge_marks")}
        k = [tuple(r) for r in conn.execute(
            "select account_a, account_b, decided_by, decided_at::text from bd_carry.kept_pairs order by 1, 2")]
    return m, k


def forward(dbs, record):
    return cutover.forward(dbs.old, dbs.app, record)


def reverse(dbs, **kw):
    return cutover.reverse(dbs.old, dbs.app, dbs.record, **kw)


# ── the round trip ──────────────────────────────────────────────────────────────────────────────
def test_the_round_trip_brings_every_tool_row_back_on_the_old_apps_columns(dbs, api, capsys):
    assert forward(dbs, dbs.record) == EXIT_OK
    tool_changes(api)
    tool_before = tool_everything(dbs.tool)
    ledger = rows(dbs.old, "public", "schema_migrations", ["name", "applied_at"])
    capsys.readouterr()
    assert reverse(dbs) == EXIT_OK, capsys.readouterr().err
    for table in OLD_TABLES:
        cols = columns_of(dbs.old, "public", table)          # the old app's columns, generated ones too
        assert rows(dbs.old, "public", table, cols) == rows(dbs.tool, "bd", table, cols), table
    with _bd_db.connect(dbs.old) as conn:
        assert [r[0] for r in conn.execute("select id from public.contacts where id > 75 order by id")] == [76, 77]
        assert conn.execute("select company_id from public.contacts where id = 51").fetchone()[0] == 41
        assert conn.execute("select count(*) from public.interactions").fetchone()[0] == len(src.ROWS["interactions"]) + 2
        assert conn.execute("select name from public.companies where id = 43").fetchone()[0] == \
            "Harrow and Finch Glazing"                                 # the undone merge's rename is gone
    assert rows(dbs.old, "public", "schema_migrations", ["name", "applied_at"]) == ledger
    assert tool_everything(dbs.tool) == tool_before                   # the tool side is only read
    out = capsys.readouterr().out
    for table in OLD_TABLES:
        line = next(x for x in out.splitlines() if x.split()[:1] == [table])
        n = scalar(dbs.old, "select count(*) from public.%s" % table)
        assert line.split()[1:3] == [str(n), str(n)] and line.split()[-1] == "matches"


def test_after_the_reverse_copy_the_old_app_inserts_new_rows(dbs, api, capsys):
    """Every identity sequence in the old database is past its highest id AND past what the tool
    handed out: the tool burned interaction ids up to 120 without keeping a row, so the old app's
    next call is 121, never an id the tool once used. A new contact, call and task go in through
    the OLD schema as the old app would write them."""
    assert forward(dbs, dbs.record) == EXIT_OK
    tool_changes(api)
    with _bd_db.connect(dbs.tool) as conn:
        conn.execute("select setval(pg_get_serial_sequence('bd.interactions', 'id'), 120)")
    assert reverse(dbs) == EXIT_OK, capsys.readouterr().err
    with _bd_db.connect(dbs.old) as conn:
        for table in src.IDENTITY_TABLES:
            last, called = conn.execute("select last_value, is_called from %s" % conn.execute(
                "select pg_get_serial_sequence(%s, 'id')", ("public." + table,)).fetchone()[0]).fetchone()
            high = conn.execute("select coalesce(max(id), 0) from public.%s" % table).fetchone()[0]
            assert (last + 1 if called else last) > high, table
        contact = conn.execute("insert into public.contacts (company_id, name, category)"
                               " values (48, 'Newly Added', 'bd') returning id").fetchone()[0]
        call = conn.execute("insert into public.interactions (contact_id, kind, outcome, occurred_at)"
                            " values (%s, 'call', 'answered', now()) returning id", (contact,)).fetchone()[0]
        task = conn.execute("insert into public.tasks (batch_id, contact_id, kind) values (201, %s, 'new')"
                            " returning id", (contact,)).fetchone()[0]
    assert (contact, call, task) == (78, 121, 306)


# ── the BD-only state: bd_carry ─────────────────────────────────────────────────────────────────
def test_the_bd_only_state_survives_a_rollback_and_a_re_cut_over(dbs, api, capsys):
    assert forward(dbs, dbs.record) == EXIT_OK
    merges = tool_changes(api)
    marks_before, kept_before = marks(dbs.tool), kept(dbs.tool)
    assert [(m[0], m[1], m[3]) for m in marks_before] == [(40, 41, 2), (46, 47, 2)]
    assert [(k[0], k[1], k[2]) for k in kept_before] == [(44, 45, 2), (46, 48, 2)]
    assert reverse(dbs) == EXIT_OK, capsys.readouterr().err

    carried, carried_kept = bd_carry(dbs.old)
    assert carried == {40: (41, marks_before[0][2], 2, []), 46: (47, marks_before[1][2], 2, [])}
    assert carried_kept == kept_before
    with _bd_db.connect(dbs.old) as conn:                    # the old app sees an empty account 40
        assert conn.execute("select count(*) from public.contacts where company_id in (40, 46)").fetchone()[0] == 0

    empty_schema_bd(dbs.tool)
    assert forward(dbs, dbs.record2) == EXIT_OK, capsys.readouterr().err
    assert marks(dbs.tool) == marks_before
    assert kept(dbs.tool) == kept_before
    assert people_at(dbs.tool, 40) == [] and people_at(dbs.tool, 46) == []
    assert people_at(dbs.tool, 41) == [51, 52] and people_at(dbs.tool, 47) == [57, 58]
    # Exactly as before the rollback: #811's Undo still takes the merge back.
    ok(api(TAMSIN).post(UNDO % merges["quarry"]))
    assert people_at(dbs.tool, 46) == [57]
    out = capsys.readouterr().out
    assert "bd_carry re-applied: 2 merge marks, 2 kept pairs." in out


def test_a_later_reverse_copy_replaces_the_earlier_carry(dbs, api, capsys):
    assert forward(dbs, dbs.record) == EXIT_OK
    merges = tool_changes(api)
    assert reverse(dbs) == EXIT_OK
    empty_schema_bd(dbs.tool)
    assert forward(dbs, dbs.record2) == EXIT_OK
    ok(api(TAMSIN).post(UNDO % merges["juniper"]))
    with _bd_db.connect(dbs.tool) as conn:
        conn.execute("delete from bd.account_pairs_kept where account_a = 44")
    assert cutover.reverse(dbs.old, dbs.app, dbs.record2) == EXIT_OK, capsys.readouterr().err
    carried, carried_kept = bd_carry(dbs.old)
    assert list(carried) == [46]
    assert [(k[0], k[1]) for k in carried_kept] == [(46, 48)]
    assert "bd_carry saved in the old database: 1 merge mark, 1 kept pair" in capsys.readouterr().out


def test_a_merged_away_account_that_gained_people_gets_no_mark_back_and_is_listed(dbs, api, capsys):
    assert forward(dbs, dbs.record) == EXIT_OK
    tool_changes(api)
    assert reverse(dbs) == EXIT_OK
    with _bd_db.connect(dbs.old) as conn:                    # the old app, during the rollback
        newcomer = conn.execute("insert into public.contacts (company_id, name, category)"
                                " values (40, 'Rosalind Ketteridge', 'bd') returning id").fetchone()[0]
    capsys.readouterr()
    empty_schema_bd(dbs.tool)
    assert forward(dbs, dbs.record2) == EXIT_OK
    out = capsys.readouterr().out
    assert [m[:2] for m in marks(dbs.tool)] == [(46, 47)]                  # 46 has nobody new: marked
    assert people_at(dbs.tool, 40) == [newcomer]                            # not hidden
    lines = out.splitlines()
    start = next(i for i, x in enumerate(lines) if x.startswith("Merged-away accounts whose mark was not put back"))
    assert [x for x in lines[start + 1:] if x.startswith("  ")][:1] == [
        "  40 Juniper Ridge Const. LLC, merged into 41 Juniper Ridge Construction: gained people in the old app"]
    assert "Rosalind" not in out
    assert "bd_carry re-applied: 1 merge mark, 2 kept pairs." in out


def test_recently_merged_no_longer_offers_undo_for_a_merge_whose_mark_was_not_put_back(dbs, api):
    """40 gained a person in the old app, so its mark is not put back: its merge (still in the
    copied ledger) must leave Recently merged, whose Undo could only answer 409. 46's mark is put
    back, so its merge stays listed; Harrow's was undone in the tool and stays off the list. Merged
    anew into 43, 40 lists only the new merge: the old one's mark (into 41) is gone."""
    assert forward(dbs, dbs.record) == EXIT_OK
    merges = tool_changes(api)
    shown = ok(api(TAMSIN).get("/api/bd/contacts/accounts/duplicates"))["merges"]
    assert [(m["id"], m["account"]["id"]) for m in shown] == [(merges["quarry"], 46), (merges["juniper"], 40)]
    assert reverse(dbs) == EXIT_OK
    with _bd_db.connect(dbs.old) as conn:
        conn.execute("insert into public.contacts (company_id, name, category) values (40, 'Rosalind Ketteridge', 'bd')")
    empty_schema_bd(dbs.tool)
    assert forward(dbs, dbs.record2) == EXIT_OK
    shown = ok(api(TAMSIN).get("/api/bd/contacts/accounts/duplicates"))["merges"]
    assert [(m["id"], m["account"]["id"]) for m in shown] == [(merges["quarry"], 46)]
    again = merge(api, 40, 43, 43)                     # 40 merged anew, into another survivor
    shown = ok(api(TAMSIN).get("/api/bd/contacts/accounts/duplicates"))["merges"]
    assert [(m["id"], m["account"]["id"]) for m in shown] == [(again, 40), (merges["quarry"], 46)]


def test_a_merged_away_account_the_old_app_deleted_is_listed_with_its_kept_pair(dbs, api, capsys):
    assert forward(dbs, dbs.record) == EXIT_OK
    tool_changes(api)
    assert reverse(dbs) == EXIT_OK
    with _bd_db.connect(dbs.old) as conn:
        conn.execute("delete from public.companies where id = 46")
    capsys.readouterr()
    empty_schema_bd(dbs.tool)
    assert forward(dbs, dbs.record2) == EXIT_OK
    out = capsys.readouterr().out
    assert [m[:2] for m in marks(dbs.tool)] == [(40, 41)]
    assert [k[:2] for k in kept(dbs.tool)] == [(44, 45)]
    assert "  46 (gone), merged into 47 Quarry Lane Storage, Inc.: no longer in the old database" in out.splitlines()
    assert "  46 + 48: no longer in the old database" in out.splitlines()


def test_a_mark_schema_bd_does_not_keep_as_given_stops_the_forward_copy(dbs, api, capsys):
    """A trigger in schema bd drops the merging user from every mark put back: the carry's proof
    fails, and nothing is kept."""
    assert forward(dbs, dbs.record) == EXIT_OK
    tool_changes(api)
    assert reverse(dbs) == EXIT_OK
    empty_schema_bd(dbs.tool)
    with _bd_db.connect(dbs.tool) as conn:
        conn.execute("create function bd.zz_unmark() returns trigger language plpgsql as $$"
                     " begin new.merged_by := null; return new; end $$")
        conn.execute("create trigger zz_unmark before update on bd.companies for each row"
                     " when (new.merged_into is not null) execute function bd.zz_unmark()")
    capsys.readouterr()
    assert forward(dbs, dbs.record2) == EXIT_MISMATCH
    err = capsys.readouterr().err
    assert [x.split(":")[0].strip() for x in err.splitlines() if x.startswith("  ")] == ["bd_carry"]
    assert tool_everything(dbs.tool)["companies"] == [] and not dbs.record2.exists()


def test_bd_carry_changing_during_the_forward_copy_stops_it_with_a_freeze_error(dbs, api, capsys):
    assert forward(dbs, dbs.record) == EXIT_OK
    tool_changes(api)
    assert reverse(dbs) == EXIT_OK
    empty_schema_bd(dbs.tool)

    def someone_writes():
        with _bd_db.connect(dbs.old) as conn:
            conn.execute("delete from bd_carry.kept_pairs where account_a = 44")

    capsys.readouterr()
    assert cutover.forward(dbs.old, dbs.app, dbs.record2, after_source_read=someone_writes) == EXIT_FREEZE
    err = capsys.readouterr().err
    assert [x.split(":")[0].strip() for x in err.splitlines() if x.startswith("  ")] == ["bd_carry"]
    assert tool_everything(dbs.tool)["companies"] == [] and not dbs.record2.exists()


def test_a_carry_the_old_database_does_not_keep_as_given_stops_the_reverse_copy(dbs, api, capsys):
    """An event trigger in the old database puts a row trigger on bd_carry.merge_marks as soon as the
    reverse copy makes it, dropping the merging user: the carry read back differs, so the old
    database is rolled back, rows and bd_carry alike."""
    assert forward(dbs, dbs.record) == EXIT_OK
    tool_changes(api)
    with _bd_db.connect(dbs.old) as conn:
        conn.execute("create function public.zz_unmark() returns trigger language plpgsql as $$"
                     " begin new.merged_by := null; return new; end $$")
        conn.execute("create function public.zz_on_create() returns event_trigger language plpgsql as $$"
                     " begin if exists (select 1 from pg_event_trigger_ddl_commands()"
                     "   where object_identity = 'bd_carry.merge_marks') then"
                     "   execute 'create trigger zz_unmark before insert on bd_carry.merge_marks for each row"
                     "     execute function public.zz_unmark()';"
                     " end if; end $$")
        conn.execute("create event trigger zz_on_create on ddl_command_end when tag in ('CREATE TABLE')"
                     " execute function public.zz_on_create()")
    old_before = old_everything(dbs.old)
    capsys.readouterr()
    try:
        assert reverse(dbs) == EXIT_MISMATCH
        err = capsys.readouterr().err
        assert [x.split(":")[0].strip() for x in err.splitlines() if x.startswith("  ")] == ["bd_carry"]
        assert old_everything(dbs.old) == old_before
    finally:
        with _bd_db.connect(dbs.old) as conn:
            conn.execute("drop event trigger zz_on_create")


def test_a_bd_carry_that_is_not_the_commands_shape_is_refused(dbs, capsys):
    with _bd_db.connect(dbs.old) as conn:
        conn.execute("create schema bd_carry")
        conn.execute("create table bd_carry.merge_marks (company_id bigint primary key, note text)")
    assert forward(dbs, dbs.record) == EXIT_REFUSED
    lines = refused_lines(capsys.readouterr().err)
    assert lines and all("bd_carry" in x for x in lines)
    assert set(tool_everything(dbs.tool)["users"]) == set()


# ── refusals ────────────────────────────────────────────────────────────────────────────────────
def test_the_reverse_copy_refuses_an_old_database_that_changed_since_the_cut_over(dbs, api, capsys):
    assert forward(dbs, dbs.record) == EXIT_OK
    tool_changes(api)
    with _bd_db.connect(dbs.old) as conn:
        conn.execute("update public.contacts set notes = notes || ' later' where id = 52")
        conn.execute("insert into public.events (kind) values ('note')")
    old_before, tool_before = old_everything(dbs.old), tool_everything(dbs.tool)
    capsys.readouterr()
    assert reverse(dbs) == EXIT_REFUSED
    lines = refused_lines(capsys.readouterr().err)
    assert lines == ["refusing: the old database no longer matches the cut-over record: contacts (checksum changed)",
                     "refusing: the old database no longer matches the cut-over record: events (rows 3 -> 4)"]
    assert old_everything(dbs.old) == old_before and tool_everything(dbs.tool) == tool_before


@pytest.mark.parametrize("record,why", [
    (None, "does not exist"),
    ("{}", "is not a cut-over record from a forward copy"),
    ("not json", "is not a cut-over record from a forward copy"),
    ("other form", "was made with another checksum form"),
    ("fewer tables", "is not a cut-over record from a forward copy"),
])
def test_the_reverse_copy_needs_the_forward_copys_record(dbs, capsys, record, why):
    assert forward(dbs, dbs.record) == EXIT_OK
    good = json.loads(dbs.record.read_text(encoding="utf-8"))
    if record is None:
        dbs.record.unlink()
    elif record == "other form":
        dbs.record.write_text(json.dumps(dict(good, checksum="sha1 of something")), encoding="utf-8")
    elif record == "fewer tables":
        good["tables"].pop("imports")
        dbs.record.write_text(json.dumps(good), encoding="utf-8")
    else:
        dbs.record.write_text(record, encoding="utf-8")
    old_before = old_everything(dbs.old)
    capsys.readouterr()
    assert reverse(dbs) == EXIT_REFUSED
    assert refused_lines(capsys.readouterr().err) == ["refusing: the cut-over record %s %s" % (dbs.record.name, why)]
    assert old_everything(dbs.old) == old_before


def test_the_reverse_copy_refuses_another_client_on_the_old_database(dbs, capsys):
    assert forward(dbs, dbs.record) == EXIT_OK
    old_before = old_everything(dbs.old)
    with _bd_db.connect(dbs.old) as other:
        other.execute("select 1")
        assert reverse(dbs) == EXIT_REFUSED
    assert refused_lines(capsys.readouterr().err) == ["refusing: 1 other client is connected to the old database"]
    assert old_everything(dbs.old) == old_before


def test_the_reverse_copy_refuses_an_empty_schema_bd(dbs, capsys):
    """An empty schema bd would empty the old database: refused."""
    assert forward(dbs, dbs.record) == EXIT_OK
    empty_schema_bd(dbs.tool)
    old_before = old_everything(dbs.old)
    capsys.readouterr()
    assert reverse(dbs) == EXIT_REFUSED
    assert refused_lines(capsys.readouterr().err) == [
        "refusing: schema bd holds no BD rows, so a reverse copy would empty the old database"]
    assert old_everything(dbs.old) == old_before


def test_the_reverse_copy_refuses_a_schema_bd_that_is_not_the_map(dbs, capsys):
    assert forward(dbs, dbs.record) == EXIT_OK
    with _bd_db.connect(dbs.tool) as conn:
        conn.execute("alter table bd.events add column extra text")
    old_before = old_everything(dbs.old)
    assert reverse(dbs) == EXIT_REFUSED
    assert any("bd.events" in x and "extra" in x for x in refused_lines(capsys.readouterr().err))
    assert old_everything(dbs.old) == old_before


def test_the_reverse_copy_must_run_as_bd_app(dbs, capsys):
    assert forward(dbs, dbs.record) == EXIT_OK
    old_before = old_everything(dbs.old)
    assert cutover.reverse(dbs.old, dbs.tool, dbs.record) == EXIT_REFUSED
    assert "bd_app" in capsys.readouterr().err
    assert old_everything(dbs.old) == old_before


@pytest.mark.parametrize("ddl", [
    "insert into public.schema_migrations (name) values ('005_later.sql')",
    "alter table public.contacts add column nickname text",
])
def test_the_reverse_copy_refuses_an_old_database_that_is_not_bds_four_migrations(dbs, capsys, ddl):
    assert forward(dbs, dbs.record) == EXIT_OK
    with _bd_db.connect(dbs.old) as conn:
        conn.execute(ddl)
    old_before = old_everything(dbs.old)
    capsys.readouterr()
    assert reverse(dbs) == EXIT_REFUSED
    lines = refused_lines(capsys.readouterr().err)
    assert lines and all("old database" in x for x in lines)
    assert old_everything(dbs.old) == old_before


# ── while it runs ───────────────────────────────────────────────────────────────────────────────
def test_the_old_app_cannot_write_while_the_reverse_copy_runs(dbs, api, capsys):
    """From the preflight's comparison with the record to the commit, the old tables are locked
    against writes: a write in the middle waits, and here gives up after 200 ms."""
    import psycopg

    assert forward(dbs, dbs.record) == EXIT_OK
    tool_changes(api)
    blocked = []

    def the_old_app_writes():
        with _bd_db.connect(dbs.old) as conn:
            conn.execute("set lock_timeout = '200ms'")
            try:
                conn.execute("insert into public.events (kind) values ('note')")
            except psycopg.errors.LockNotAvailable:
                blocked.append(True)

    assert reverse(dbs, after_source_read=the_old_app_writes) == EXIT_OK, capsys.readouterr().err
    assert blocked == [True]
    assert scalar(dbs.old, "select count(*) from public.events") == scalar(dbs.tool, "select count(*) from bd.events")


def test_sequence_problems_names_an_old_sequence_that_is_not_past_its_highest_id(dbs, api, capsys):
    assert forward(dbs, dbs.record) == EXIT_OK
    tool_changes(api)
    assert reverse(dbs) == EXIT_OK
    with _bd_db.connect(dbs.old) as conn:
        assert cutover.sequence_problems(conn, "old") == []
        conn.execute("select setval(pg_get_serial_sequence('public.tasks', 'id'), 304)")       # next 305: not
        conn.execute("select setval(pg_get_serial_sequence('public.users', 'id'), 3)")         # next 4: fine
        assert [p.split(":")[0] for p in cutover.sequence_problems(conn, "old")] == ["tasks"]


def test_a_person_already_at_a_merged_away_account_does_not_count_as_gained(dbs, api, capsys):
    """Normally a merged-away account holds nobody. If schema bd had someone there anyway, the old
    app gets them there too, and they are no reason to leave the mark off: the mark comes back as it
    was."""
    assert forward(dbs, dbs.record) == EXIT_OK
    tool_changes(api)
    with _bd_db.connect(dbs.tool) as conn:
        conn.execute("update bd.contacts set company_id = 46 where id = 58")
    marks_before = marks(dbs.tool)
    assert reverse(dbs) == EXIT_OK
    assert bd_carry(dbs.old)[0][46][3] == [58]
    empty_schema_bd(dbs.tool)
    capsys.readouterr()
    assert forward(dbs, dbs.record2) == EXIT_OK
    assert marks(dbs.tool) == marks_before
    assert "Merged-away accounts whose mark was not put back" not in capsys.readouterr().out


# ── all or nothing ──────────────────────────────────────────────────────────────────────────────
def test_a_row_the_old_database_rejects_leaves_it_as_it_was(dbs, api, capsys):
    assert forward(dbs, dbs.record) == EXIT_OK
    tool_changes(api)
    with _bd_db.connect(dbs.old) as conn:
        conn.execute("alter table public.contacts add constraint zz_no_fennimore check (name <> 'Fennimore Quayle')"
                     " not valid")
    old_before = old_everything(dbs.old)
    capsys.readouterr()
    assert reverse(dbs) == EXIT_ERROR
    out = capsys.readouterr()
    assert "public.contacts" in out.err
    assert "Fennimore" not in out.out + out.err and "zz_no_fennimore" not in out.out + out.err
    assert old_everything(dbs.old) == old_before


def test_a_sequence_that_cannot_be_found_puts_back_the_ones_set_before_it(dbs, api, capsys):
    """public.imports lost its identity in the old database (an odd hand change the map does not
    see), so the reverse copy fails on the last sequence, after the other eleven were set. setval is
    not undone by a rollback: the command puts those back itself, and the old database is as it was."""
    assert forward(dbs, dbs.record) == EXIT_OK
    tool_changes(api)
    with _bd_db.connect(dbs.old) as conn:
        conn.execute("alter table public.imports alter column id drop identity")
    old_before = old_everything(dbs.old)
    capsys.readouterr()
    assert reverse(dbs) == EXIT_ERROR
    assert "the id sequence of public.imports could not be found" in capsys.readouterr().err
    assert old_everything(dbs.old) == old_before


def test_schema_bd_changing_during_the_reverse_copy_stops_with_a_freeze_error(dbs, api, capsys):
    assert forward(dbs, dbs.record) == EXIT_OK
    tool_changes(api)
    old_before = old_everything(dbs.old)

    def someone_writes():
        with _bd_db.connect(dbs.tool) as conn:
            conn.execute("insert into bd.events (kind) values ('note')")

    capsys.readouterr()
    assert reverse(dbs, after_source_read=someone_writes) == EXIT_FREEZE
    err = capsys.readouterr().err
    assert "freeze" in err.lower()
    assert [x.split(":")[0].strip() for x in err.splitlines() if x.startswith("  ")] == ["events"]
    assert old_everything(dbs.old) == old_before


def test_a_merge_mark_changing_during_the_reverse_copy_stops_it_too(dbs, api, capsys):
    assert forward(dbs, dbs.record) == EXIT_OK
    merges = tool_changes(api)
    old_before = old_everything(dbs.old)

    def someone_merges():
        with _bd_db.connect(dbs.tool) as conn:
            conn.execute("update bd.companies set merged_by = 1 where id = 40")

    capsys.readouterr()
    assert merges and reverse(dbs, after_source_read=someone_merges) == EXIT_FREEZE
    err = capsys.readouterr().err
    assert [x.split(":")[0].strip() for x in err.splitlines() if x.startswith("  ")] == ["bd_carry"]
    assert old_everything(dbs.old) == old_before


def test_an_old_database_that_does_not_take_the_rows_as_they_are_is_rolled_back(dbs, api, capsys):
    """A trigger in the old database changes one name on the way in: its users checksum differs from
    schema bd's, so nothing is kept there."""
    assert forward(dbs, dbs.record) == EXIT_OK
    tool_changes(api)
    with _bd_db.connect(dbs.old) as conn:
        conn.execute("create function public.zz_twist() returns trigger language plpgsql as $$"
                     " begin new.name := new.name || '!'; return new; end $$")
        conn.execute("create trigger zz_twist before insert on public.users for each row"
                     " when (new.id = 2) execute function public.zz_twist()")
    old_before = old_everything(dbs.old)
    capsys.readouterr()
    assert reverse(dbs) == EXIT_MISMATCH
    err = capsys.readouterr().err
    assert [x.split(":")[0].strip() for x in err.splitlines() if x.startswith("  ")] == ["users"]
    assert old_everything(dbs.old) == old_before


# ── only schema bd, only as bd_app; no row data printed ─────────────────────────────────────────
def test_the_reverse_copy_reads_nothing_outside_schema_bd_on_the_tool_side(dbs, api, bd_admin, capsys):
    """Decoys with BD's table names in schema public of the tool's database, first on the login's
    search_path: Postgres's own counters show none of them scanned, read or written."""
    assert forward(dbs, dbs.record) == EXIT_OK
    tool_changes(api)
    with _bd_db.connect(dbs.tool) as conn:
        conn.execute("create schema if not exists public")
        for t in OLD_TABLES + ["account_pairs_kept"]:
            conn.execute("create table public.%s (id bigint primary key, decoy text)" % t)
            conn.execute("insert into public.%s values (1, 'decoy')" % t)
            conn.execute("grant all on public.%s to %s" % (t, _bd_db.APP_TEST_LOGIN))
        conn.execute("grant usage on schema public to %s" % _bd_db.APP_TEST_LOGIN)

    def decoys():
        with _bd_db.connect(dbs.tool) as conn:
            return {r[0]: tuple(r[1:]) for r in conn.execute(
                "select relname, coalesce(seq_scan, 0), coalesce(idx_scan, 0), n_tup_ins, n_tup_upd, n_tup_del"
                " from pg_stat_user_tables where schemaname = 'public'").fetchall()}

    def bd_scans():
        with _bd_db.connect(dbs.tool) as conn:
            return conn.execute("select coalesce(seq_scan, 0) + coalesce(idx_scan, 0) from pg_stat_user_tables"
                                " where schemaname = 'bd'"
                                " and relname = 'contacts'").fetchone()[0]

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and sorted(v[2] for v in decoys().values()) != [1] * (len(OLD_TABLES) + 1):
        time.sleep(0.2)
    before, scans = decoys(), bd_scans()
    assert {v[2] for v in before.values()} == {1}
    app = dbs.app.replace("search_path=bd,pg_catalog", "search_path=public,bd,pg_catalog")
    assert "search_path=public" in app
    assert cutover.reverse(dbs.old, app, dbs.record) == EXIT_OK, capsys.readouterr().err
    deadline = time.monotonic() + 15
    while bd_scans() == scans and time.monotonic() < deadline:
        time.sleep(0.2)
    assert bd_scans() > scans
    assert decoys() == before


def test_no_subcommand_prints_row_data_through_a_rollback_and_a_re_cut_over(dbs, api, monkeypatch, capsys):
    printed = []

    def main(*args):
        code = cutover.main(list(args))
        out = capsys.readouterr()
        printed.append(out.out + out.err)
        return code

    monkeypatch.setenv("BD_CUTOVER_OLD_URL", dbs.old)
    monkeypatch.setenv("BD_CUTOVER_TOOL_URL", dbs.app)
    assert main("forward", "--record", str(dbs.record)) == EXIT_OK
    tool_changes(api)
    with _bd_db.connect(dbs.old):
        assert main("reverse", "--record", str(dbs.record)) == EXIT_REFUSED          # another client
    assert main("reverse", "--record", str(dbs.record) + ".missing") == EXIT_REFUSED
    assert main("reverse", "--record", str(dbs.record)) == EXIT_OK
    assert main("reverse", "--record", str(dbs.record)) == EXIT_REFUSED              # no longer matches
    with _bd_db.connect(dbs.old) as conn:
        conn.execute("insert into public.contacts (company_id, name, email, phone, notes) values"
                     " (40, 'Rosalind Ketteridge', 'rosalind@juniperridge.example.com', '816-555-0163', 'ZQ new')")
    empty_schema_bd(dbs.tool)
    assert main("check") == EXIT_OK
    assert main("forward", "--record", str(dbs.record2)) == EXIT_OK
    joined = "\n".join(printed)
    assert "gained people" in joined and "bd_carry saved" in joined and "bd_carry (saved by a reverse copy)" in joined
    assert "ZQ" not in joined
    for value in src.PERSONAL + NEW_PERSONAL + ["Rosalind Ketteridge", "rosalind@juniperridge.example.com",
                                                "816-555-0163"]:
        assert value not in joined, value
    for leak in ("postgresql://", _bd_db.APP_TEST_PASSWORD, _bd_db.dbname(dbs.old), _bd_db.dbname(dbs.tool)):
        assert leak not in joined
