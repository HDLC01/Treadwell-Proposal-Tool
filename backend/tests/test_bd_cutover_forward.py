"""The cut-over copy, forward (#812): the old BD database -> schema bd, with its proof.

    python -m bd.ops.cutover forward --record PATH     (bd/ops/cutover.py)

The source is built from BD's ORIGINAL four migrations (tests/fixtures/bd_old_migrations) and holds
made-up rows covering every table (tests/_bd_old_source.py). The target is a fresh schema bd
migrated by the runner, in a database that sorts text the ICU en-US way while the source sorts it
byte-wise. The command connects to the target as the bd_app-like test login, never the owner.

What is expected is read from the databases plainly (every row as text) or worked out by hand from
the fixture, never recomputed by the command's own checksum code.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
import types

import pytest

import _bd_db
import _bd_old_source as src
from bd.ops import cutover

EXIT_OK, EXIT_REFUSED, EXIT_MISMATCH, EXIT_FREEZE = 0, 3, 4, 5
OLD_TABLES = list(src.ROWS)        # the old app's 15 tables, parents first


@pytest.fixture(scope="module")
def templates(bd_admin):
    with src.databases(bd_admin) as names:
        yield names


@pytest.fixture
def dbs(bd_admin, templates, tmp_path):
    with src.clone(bd_admin, templates["old"]) as old, src.clone(bd_admin, templates["tool"]) as tool:
        yield types.SimpleNamespace(old=old, tool=tool, app=_bd_db.app_login_url(tool),
                                    record=tmp_path / "cutover-record.json")


def forward(dbs, **kw):
    return cutover.forward(dbs.old, dbs.app, dbs.record, **kw)


def scalar(url, query, params=None):
    with _bd_db.connect(url) as conn:
        return conn.execute(query, params).fetchone()[0]


def columns_of(url, schema, table):
    """The table's columns in the database's own order, from the catalog (not the command's map)."""
    with _bd_db.connect(url) as conn:
        return [r[0] for r in conn.execute(
            "select a.attname from pg_attribute a join pg_class c on c.oid = a.attrelid"
            " join pg_namespace n on n.oid = c.relnamespace where n.nspname = %s and c.relname = %s"
            " and a.attnum > 0 and not a.attisdropped order by a.attnum", (schema, table)).fetchall()]


ORDER = {"settings": 'key collate "C"', "schema_migrations": "name", "integration_events": 'provider collate "C", event_id collate "C"'}


def rows(url, schema, table, cols):
    return src.table_rows(url, schema, table, cols, ORDER.get(table, "id"))


def bd_counts(url):
    with _bd_db.connect(url) as conn:
        tables = [r[0] for r in conn.execute(
            "select relname from pg_class where relnamespace = 'bd'::regnamespace and relkind = 'r'"
            " and relname <> 'schema_migrations' order by 1").fetchall()]
        return {t: conn.execute("select count(*) from bd.%s" % t).fetchone()[0] for t in tables}


def md5_rows(lines):
    return hashlib.md5("".join(hashlib.md5(x.encode("utf-8")).hexdigest() for x in lines).encode()).hexdigest()


# ── the copy itself ─────────────────────────────────────────────────────────────────────────────
def test_every_row_of_every_table_arrives_as_it_was(dbs, capsys):
    assert forward(dbs) == EXIT_OK
    for table in OLD_TABLES:
        cols = columns_of(dbs.old, "public", table)           # generated columns included
        old_rows = rows(dbs.old, "public", table, cols)
        assert len(old_rows) == len(src.ROWS[table])
        assert rows(dbs.tool, "bd", table, cols) == old_rows, table


def test_contact_company_and_interaction_ids_are_unchanged(dbs, capsys):
    assert forward(dbs) == EXIT_OK
    for table, want in (("contacts", list(range(51, 60))), ("companies", list(range(40, 49))),
                        ("interactions", list(range(101, 109)))):
        with _bd_db.connect(dbs.tool) as conn:
            assert [r[0] for r in conn.execute("select id from bd.%s order by id" % table)] == want


def test_the_flag_pointing_at_a_higher_id_comes_through(dbs, capsys):
    assert forward(dbs) == EXIT_OK
    assert scalar(dbs.tool, "select duplicate_of from bd.contacts where id = 54") == 58


def test_generated_columns_are_filled_by_the_database(dbs, capsys):
    assert forward(dbs) == EXIT_OK
    with _bd_db.connect(dbs.tool) as conn:
        got = {r[0]: (r[1], r[2]) for r in conn.execute("select id, email_lower, phone_e164 from bd.contacts")}
        touch = dict(conn.execute("select id, counts_as_touch from bd.interactions").fetchall())
    assert got[51] == ("thessaly.brookhart@juniperridge.example.com", "+18165550141")
    assert got[52] == ("orrin@valdemar-mail.example.com", "+18165550141")
    assert got[58] == ("bart.eckhart@quarrylane.example.com", None)        # "  " is no phone
    assert got[59] == (None, "+19135550149")                                 # "" is no email
    assert touch == {101: True, 102: False, 103: True, 104: False, 105: True, 106: False, 107: False, 108: False}


def test_settings_and_events_come_through(dbs, capsys):
    assert forward(dbs) == EXIT_OK
    with _bd_db.connect(dbs.tool) as conn:
        settings = {r[0]: r[1] for r in conn.execute("select key, value from bd.settings")}
        events = [tuple(r) for r in conn.execute("select id, kind, contact_id, data from bd.events order by id")]
    assert settings == {"bd_cadence": "monthly", "default_frequency": {"maintenance": 3},
                        "lead_sources": ["Referral", "Web", "Other/Misc"],
                        "Weekly": {"day": "friday", "hour": 16, "note": "tab\there \"q\" é ZQ"}}
    assert [e[:3] for e in events] == [(901, "created", 51), (902, "imported", None), (903, "edited", 58)]
    assert scalar(dbs.tool, "select data::text from bd.events where id = 903") == \
        '{"before": {"n": 1.10, "title": null}, "fields": ["title", "notes"]}'


def test_what_only_the_tool_has_stays_empty_and_the_old_ledger_is_not_copied(dbs, capsys):
    ledger_before = scalar(dbs.tool, "select array_agg(name order by name) from bd.schema_migrations")
    assert forward(dbs) == EXIT_OK
    assert scalar(dbs.tool, "select count(*) from bd.companies where merged_into is not null"
                            " or merged_at is not null or merged_by is not null") == 0
    assert scalar(dbs.tool, "select count(*) from bd.account_pairs_kept") == 0
    assert scalar(dbs.tool, "select array_agg(name order by name) from bd.schema_migrations") == ledger_before
    assert scalar(dbs.tool, "select to_regclass('public.schema_migrations')") is None


def test_the_old_database_is_never_written(dbs, capsys):
    def everything(url):
        return {t: rows(url, "public", t, columns_of(url, "public", t)) for t in OLD_TABLES + ["schema_migrations"]}

    before = everything(dbs.old)
    seqs = scalar(dbs.old, "select array_agg(last_value order by sequencename) from pg_sequences")
    assert forward(dbs) == EXIT_OK
    assert everything(dbs.old) == before
    assert scalar(dbs.old, "select array_agg(last_value order by sequencename) from pg_sequences") == seqs
    assert scalar(dbs.old, "select count(*) from pg_namespace where nspname like 'bd%'") == 0


# ── sequences ───────────────────────────────────────────────────────────────────────────────────
def test_every_identity_table_takes_a_new_row_after_the_copy(dbs, capsys):
    """As the bd_app-like login, a row with no id in each identity table: the id it gets is past every
    copied id. Contacts continue after the OLD sequence (75), not just after the highest row (59)."""
    assert forward(dbs) == EXIT_OK
    inserts = [
        ("users", "insert into bd.users (email, name, role) values ('new.zz@example.com', 'New Zz', 'salesperson')"),
        ("companies", "insert into bd.companies (name, normalized_name) values ('Newco', 'newco')"),
        ("contacts", "insert into bd.contacts (company_id, name) values (48, 'New Zz')"),
        ("interactions", "insert into bd.interactions (contact_id, kind, occurred_at) values (51, 'note', now())"),
        ("task_batches", "insert into bd.task_batches (owner_id, week_start, kind)"
                         " values (2, '2026-11-09', 'friday')"),
        ("tasks", "insert into bd.tasks (batch_id, contact_id, kind) values (201, 55, 'new')"),
        ("ai_recommendations", "insert into bd.ai_recommendations (contact_id, action, source)"
                               " values (51, 'Call', 'ai')"),
        ("followup_drafts", "insert into bd.followup_drafts (contact_id, channel, source) values (51, 'sms', 'ai')"),
        ("candidates", "insert into bd.candidates (project_id) values ('p-new')"),
        ("unmatched_calls", "insert into bd.unmatched_calls (provider, occurred_at) values ('quo', now())"),
        ("events", "insert into bd.events (kind) values ('note')"),
        ("imports", "insert into bd.imports (file_name, dry_run) values ('x.csv', true)"),
    ]
    assert sorted(t for t, _ in inserts) == sorted(src.IDENTITY_TABLES)
    got = {}
    with _bd_db.connect(_bd_db.app_login_url(dbs.tool)) as conn:
        for table, sql in inserts:
            got[table] = conn.execute(sql + " returning id").fetchone()[0]
    highest = {t: max(r["id"] for r in src.ROWS[t]) for t in src.IDENTITY_TABLES}
    assert got == {t: (src.CONTACTS_SEQUENCE_AT if t == "contacts" else highest[t]) + 1 for t in highest}


def test_sequence_problems_names_a_sequence_that_is_not_past_its_highest_id(dbs, capsys):
    assert forward(dbs) == EXIT_OK
    with _bd_db.connect(dbs.app) as conn:
        assert cutover.sequence_problems(conn, "bd") == []
    with _bd_db.connect(dbs.tool) as conn:
        conn.execute("select setval(pg_get_serial_sequence('bd.users', 'id'), 3)")       # next is 4: fine
        conn.execute("select setval(pg_get_serial_sequence('bd.events', 'id'), 903)")    # next 904: fine
        conn.execute("select setval(pg_get_serial_sequence('bd.tasks', 'id'), 305, false)")  # next 305: not
        conn.execute("select setval(pg_get_serial_sequence('bd.imports', 'id'), 2)")     # next 3: not
    with _bd_db.connect(dbs.app) as conn:
        problems = cutover.sequence_problems(conn, "bd")
    assert [p.split(":")[0] for p in problems] == ["tasks", "imports"]


# ── the proof ───────────────────────────────────────────────────────────────────────────────────
def test_the_record_holds_names_counts_checksums_and_the_time_only(dbs, capsys):
    assert forward(dbs) == EXIT_OK
    record = json.loads(dbs.record.read_text(encoding="utf-8"))
    assert set(record) == {"record", "direction", "at", "checksum", "tables"}
    assert record["record"] == "bd cut-over" and record["direction"] == "forward"
    assert record["at"].endswith("Z")
    assert list(record["tables"]) == OLD_TABLES
    for table, entry in record["tables"].items():
        assert set(entry) == {"count", "checksum"}
        assert entry["count"] == len(src.ROWS[table]) == scalar(dbs.tool, "select count(*) from bd.%s" % table)
        assert len(entry["checksum"]) == 32


def test_the_checksums_follow_the_declared_canonical_form(dbs, capsys):
    """Worked by hand: each row is the JSON array of its non-generated columns in the map's order,
    timestamps in UTC; the table's checksum is the md5 of its rows' md5s in key order (text keys in
    byte order, whatever the database's collation: "Weekly" before "bd_cadence")."""
    assert forward(dbs) == EXIT_OK
    tables = json.loads(dbs.record.read_text(encoding="utf-8"))["tables"]
    assert tables["settings"]["checksum"] == md5_rows([
        '["Weekly", {"day": "friday", "hour": 16, "note": "tab\\there \\"q\\" é ZQ"}, '
        '"2026-11-01T07:30:00+00:00", null]',
        '["bd_cadence", "monthly", "2026-03-08T08:30:00+00:00", 3]',
        '["default_frequency", {"maintenance": 3}, "2026-01-05T15:00:00+00:00", null]',
        '["lead_sources", ["Referral", "Web", "Other/Misc"], "2026-11-01T06:30:00+00:00", 1]',
    ])
    assert tables["users"]["checksum"] == md5_rows([
        '[1, "marlo.quint@example.com", "Marlo Quint", "salesperson", true, "sub-ZQ-0001", '
        '"2026-11-01T06:30:00.123456+00:00", "2026-01-05T15:00:00+00:00"]',
        '[2, "tamsin.okafor@example.com", "Tamsin Okafor", "assistant", true, null, null, '
        '"2026-01-05T15:00:01+00:00"]',
        '[3, "ziggy.halvorsen@example.com", "Ziggy Halvorsen", "admin", false, "", '
        '"2026-03-08T07:59:59+00:00", "2026-01-05T15:00:02+00:00"]',
    ])
    assert tables["integration_events"]["checksum"] == md5_rows([
        '["Quo", "evt-ZQ-1", "sms.received", "2026-11-02T18:00:00+00:00", {"text": "ZQ"}, "ignored", null]',
        '["quo", "evt-ZQ-1", "call.completed", "2026-11-01T07:30:30+00:00", '
        '{"id": "evt-ZQ-1", "call": {"from": "+19135550199", "seconds": 0}}, "interaction_created", 104]',
        '["quo", "evt-ZQ-2", null, "2026-11-01T07:31:00+00:00", {}, "unmatched", null]',
    ])


def test_generated_columns_are_left_out_of_the_checksum(dbs, capsys):
    """interactions, worked by hand: its 16 written columns per row, never counts_as_touch (the
    database computes it). Each row is written here as a Python list and dumped as JSON, the same text
    json_build_array makes for these types."""
    assert forward(dbs) == EXIT_OK
    t = "+00:00"
    manual = "manual"
    lines = [
        [101, 51, "call", "out", "answered", "2026-03-08T07:59:59" + t, 420, "Spoke about the ZQ floor.", None,
         None, manual, None, 1, None, None, "2026-03-08T07:59:59" + t],
        [102, 51, "voicemail", "out", "voicemail", "2026-03-08T08:00:00" + t, 35, "Left a ZQ message.", None,
         None, manual, None, 1, None, None, "2026-03-08T08:00:00" + t],
        [103, 53, "meeting", None, None, "2026-11-01T06:30:00" + t, None, "Walked the ZQ site.", src.ODD,
         None, manual, None, 2, None, None, "2026-11-01T06:30:00" + t],
        [104, 53, "call", "in", "no_answer", "2026-11-01T07:30:00" + t, 0, None, None, None, "quo", "QZ-0001",
         None, None, None, "2026-11-01T07:30:00" + t],
        [105, 57, "hosted", None, None, "2026-06-10T22:00:00.5" + t, None, "Lunch and learn ZQ.", None, None,
         manual, None, 1, None, None, "2026-06-10T22:00:00.5" + t],
        [106, 55, "email", "out", None, "2026-10-28T13:00:00" + t, None, "Sent the ZQ options.", None,
         "https://recordings.example.com/zq/106", manual, None, 2, None, None, "2026-10-28T13:00:00" + t],
        [107, 52, "sms", "out", None, "2026-11-02T18:00:00" + t, None, "Sorry we missed you ZQ.", None, None,
         manual, None, 1, "sent", "2026-11-02T18:05:00" + t, "2026-11-02T18:00:00" + t],
        [108, 51, "note", None, None, "2026-11-03T17:00:00" + t, None, "", None, None, manual, None, 3, None,
         None, "2026-11-03T17:00:00" + t],
    ]
    tables = json.loads(dbs.record.read_text(encoding="utf-8"))["tables"]
    assert tables["interactions"]["checksum"] == md5_rows([json.dumps(x, ensure_ascii=False) for x in lines])


def test_the_checksum_does_not_depend_on_the_sessions_time_zone(dbs, capsys):
    """The command sets UTC itself: a login whose own time zone is Central gets the same proof."""
    from psycopg import conninfo

    assert cutover.forward(conninfo.make_conninfo(dbs.old, options="-c TimeZone=America/Chicago"),
                           conninfo.make_conninfo(dbs.app, options="-c search_path=bd,pg_catalog"
                                                                   " -c TimeZone=America/Chicago"),
                           dbs.record) == EXIT_OK
    tables = json.loads(dbs.record.read_text(encoding="utf-8"))["tables"]
    assert tables["users"]["checksum"] == md5_rows([
        '[1, "marlo.quint@example.com", "Marlo Quint", "salesperson", true, "sub-ZQ-0001", '
        '"2026-11-01T06:30:00.123456+00:00", "2026-01-05T15:00:00+00:00"]',
        '[2, "tamsin.okafor@example.com", "Tamsin Okafor", "assistant", true, null, null, '
        '"2026-01-05T15:00:01+00:00"]',
        '[3, "ziggy.halvorsen@example.com", "Ziggy Halvorsen", "admin", false, "", '
        '"2026-03-08T07:59:59+00:00", "2026-01-05T15:00:02+00:00"]',
    ])


def test_the_output_prints_every_table_with_its_count_and_checksum(dbs, capsys):
    assert forward(dbs) == EXIT_OK
    out = capsys.readouterr().out
    tables = json.loads(dbs.record.read_text(encoding="utf-8"))["tables"]
    for table, entry in tables.items():
        line = next(x for x in out.splitlines() if x.split()[:1] == [table])
        assert line.split()[1:] == [str(entry["count"]), str(entry["count"]), entry["checksum"], "matches"]


def test_a_target_that_does_not_match_the_source_is_rolled_back(dbs, capsys):
    """A trigger in schema bd changes one name on the way in: the target's checksum for users differs,
    so the command stops, names the table, and leaves schema bd empty with no record."""
    with _bd_db.connect(dbs.tool) as conn:
        conn.execute("create function bd.zz_twist() returns trigger language plpgsql as $$"
                     " begin new.name := new.name || '!'; return new; end $$")
        conn.execute("create trigger zz_twist before insert on bd.users for each row"
                     " when (new.id = 2) execute function bd.zz_twist()")
    assert forward(dbs) == EXIT_MISMATCH
    err = capsys.readouterr().err
    assert [x.split(":")[0].strip() for x in err.splitlines() if x.startswith("  ")] == ["users"]
    assert set(bd_counts(dbs.tool).values()) == {0}
    assert not dbs.record.exists()


@pytest.mark.parametrize("change,table", [
    ("insert into public.events (kind, detail) values ('note', 'written during the copy')", "events"),
    ("update public.contacts set notes = notes || '.' where id = 52", "contacts"),
])
def test_a_source_that_changes_during_the_copy_stops_with_a_freeze_error(dbs, capsys, change, table):
    def someone_writes():
        with _bd_db.connect(dbs.old) as conn:
            conn.execute(change)

    assert forward(dbs, after_source_read=someone_writes) == EXIT_FREEZE
    err = capsys.readouterr().err
    assert "freeze" in err.lower()
    assert [x.split(":")[0].strip() for x in err.splitlines() if x.startswith("  ")] == [table]
    assert set(bd_counts(dbs.tool).values()) == {0}
    assert not dbs.record.exists()


def test_check_prints_the_source_proof_and_writes_nothing(dbs, capsys):
    assert cutover.check(dbs.old, dbs.app) == EXIT_OK
    out = capsys.readouterr().out
    for table in OLD_TABLES:
        line = next(x for x in out.splitlines() if x.split()[:1] == [table])
        assert line.split()[1] == str(len(src.ROWS[table]))
    assert set(bd_counts(dbs.tool).values()) == {0}
    assert list(dbs.record.parent.iterdir()) == []


def test_check_and_forward_agree_on_the_checksums(dbs, capsys):
    assert cutover.check(dbs.old, dbs.app) == EXIT_OK
    out = capsys.readouterr().out
    assert forward(dbs) == EXIT_OK
    tables = json.loads(dbs.record.read_text(encoding="utf-8"))["tables"]
    for table, entry in tables.items():
        line = next(x for x in out.splitlines() if x.split()[:1] == [table])
        assert line.split()[1:3] == [str(entry["count"]), entry["checksum"]]


# ── the duplicates list ─────────────────────────────────────────────────────────────────────────
def test_the_duplicates_list_is_the_possible_duplicates_rule_on_the_copied_data(dbs, capsys):
    assert forward(dbs) == EXIT_OK
    out = capsys.readouterr().out.splitlines()
    start = next(i for i, x in enumerate(out) if x.startswith("Likely duplicate BD accounts"))
    pairs = [x for x in out[start + 1:] if x.startswith("  ")]
    assert pairs == ["  %d %s  +  %d %s  (hint: %s)" % p for p in src.EXPECTED_PAIRS]
    assert "2 likely pairs" in out[start + 1 + len(pairs)]


def test_the_command_never_imports_a_router():
    code = ("import sys\nimport bd.ops.cutover\n"
            "print(sorted(m for m in sys.modules if m.startswith('bd.routers') or m == 'fastapi'))\n")
    res = subprocess.run([sys.executable, "-c", code], cwd=str(_bd_db.BACKEND), capture_output=True, text=True,
                         timeout=60)
    assert res.returncode == 0, res.stderr[-2000:]
    assert res.stdout.strip() == "[]"


# ── only schema bd, only as bd_app ──────────────────────────────────────────────────────────────
def test_the_tool_side_reads_and_writes_nothing_outside_schema_bd(dbs, bd_admin, capsys):
    """Decoys with BD's table names in schema public of the tool's database, which the bd_app-like
    login may read and write. After the copy, Postgres's own counters show no scan of them and no
    row written, read or changed there, while schema bd's tables got their rows."""
    _bd_db.ensure_app_login(bd_admin)
    with _bd_db.connect(dbs.tool) as conn:
        conn.execute("create schema if not exists public")
        for t in OLD_TABLES:
            conn.execute("create table public.%s (id bigint primary key, decoy text)" % t)
            conn.execute("insert into public.%s values (1, 'decoy')" % t)
            conn.execute("grant all on public.%s to %s" % (t, _bd_db.APP_TEST_LOGIN))
        conn.execute("grant usage, create on schema public to %s" % _bd_db.APP_TEST_LOGIN)

    def decoys():
        with _bd_db.connect(dbs.tool) as conn:
            return {r[0]: tuple(r[1:]) for r in conn.execute(
                "select relname, coalesce(seq_scan, 0), coalesce(idx_scan, 0), n_tup_ins, n_tup_upd, n_tup_del"
                " from pg_stat_user_tables where schemaname = 'public'").fetchall()}

    def bd_inserted():
        with _bd_db.connect(dbs.tool) as conn:
            return conn.execute("select n_tup_ins from pg_stat_user_tables where schemaname = 'bd'"
                                " and relname = 'contacts'").fetchone()[0]

    deadline = time.monotonic() + 15
    while (time.monotonic() < deadline
           and sorted(v[2] for v in decoys().values()) != [1] * len(OLD_TABLES)):
        time.sleep(0.2)             # the decoys' own inserts reach the counters when that session ends
    before = decoys()
    assert len(before) == len(OLD_TABLES) and {v[2] for v in before.values()} == {1}
    app = _bd_db.app_login_url(dbs.tool).replace("search_path=bd,pg_catalog", "search_path=public,bd,pg_catalog")
    assert "search_path=public" in app
    assert cutover.forward(dbs.old, app, dbs.record) == EXIT_OK
    deadline = time.monotonic() + 15
    while bd_inserted() < len(src.ROWS["contacts"]) and time.monotonic() < deadline:
        time.sleep(0.2)             # the command's session flushes its counters as it ends
    assert bd_inserted() >= len(src.ROWS["contacts"])
    assert decoys() == before


def test_the_tool_side_must_be_bd_app_not_a_login_that_can_change_schema_bd(dbs, capsys):
    assert cutover.forward(dbs.old, dbs.tool, dbs.record) == EXIT_REFUSED
    assert "bd_app" in capsys.readouterr().err
    assert set(bd_counts(dbs.tool).values()) == {0}
