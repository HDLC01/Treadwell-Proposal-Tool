"""The cut-over copy (#812, #802 Q3, Q37, Q38): BD's data between the OLD BD database and schema bd.

    cd backend
    python -m bd.ops.cutover check                       # the preflight and the source's proof; writes nothing
    python -m bd.ops.cutover forward --record PATH       # old database -> schema bd, then the duplicates list

    cutover.forward(old_url, tool_url, record_path) -> exit code
    cutover.check(old_url, tool_url) -> exit code

THE TWO DATABASES come from the environment, never the command line, and are never printed, logged
or put in an error message (bd/config.py reads them live):
    BD_CUTOVER_OLD_URL    the old BD database, as its owner login. Only ever READ: every session on it
                          is read only, so a forward copy cannot write there.
    BD_CUTOVER_TOOL_URL   the tool's database as bd_app (the same value as BD_DATABASE_URL). The command
                          refuses a login that could change schema bd's structure, and touches nothing
                          outside schema bd: every table it names is bd.<table>, and the catalog is read
                          only for schema bd's own tables and sequences.
On the server it runs in a one-off container from the tool's image that joins the old BD network,
because the old database publishes no port (docs/bd/cutover-runbook.md). It is never run against
staging, prod or real data except by that runbook, on Hanz's go.

THE MAP. MAP below is the one explicit map from BD's old tables (schema public of the old database,
from BD's own migrations 001 to 004) to schema bd (the tool's 001 to 005). The tool's 001 to 004 are
BD's four files placed in schema bd, so every table keeps its name and every column its name and type.
What differs, and why bd_carry exists (a later stage of #812): only schema bd has companies.merged_into,
merged_at and merged_by and the table account_pairs_kept (005, #811). The old app has no column the
tool lacks. Generated columns (contacts.email_lower and phone_e164, interactions.counts_as_touch) are
never written: the database fills them. The old migrations table (public.schema_migrations) is never
copied, and bd.schema_migrations is never written.

PREFLIGHT (forward and check). It refuses, naming each problem, before anything is written:
  * the record file already exists (a cut-over record is never overwritten);
  * any other client is connected to the old database (pg_stat_activity; this command's own session
    is not counted);
  * the old database's ledger is not BD's original four migrations;
  * either side's tables and columns differ from MAP (a missing or extra table or column, a type, or
    a column generated on one side only), so no column can be dropped or reinterpreted unnoticed;
  * the tool login can create in schema bd (it must be bd_app);
  * schema bd is behind the code (the runner's ledger has a migration pending);
  * any table in schema bd holds rows, each one named. bd.schema_migrations is left out, and a settings
    row a migration inserts by itself (MIGRATION_SETTINGS_KEYS) counts as empty: the copy replaces it.

PROOF. Per table: the row count, and a checksum of the non-generated columns in MAP's order, computed in
SQL on each side with the session's TimeZone UTC: md5 over the md5 of each row's
json_build_array(columns)::text, in key order (id; text keys compared byte-wise, collate "C", so two
databases that sort text differently agree). JSON is the canonical text form: timestamps in ISO with
their UTC offset, dates, numerics with their scale, booleans, nulls, jsonb in its normalized form, arrays,
and text escaped, all the same on both sides. The two sides never differ in a column's type (MAP and the
preflight make sure), so no column needs a declared cross-type form.
  * The source's counts and checksums are read in ONE snapshot with the rows copied, and read again
    after the target is written. Any change stops the command with a freeze error: the freeze did not
    hold, and nothing is kept.
  * The target's counts and checksums, read inside the copy's own transaction, must equal the source's.
  * Every identity sequence in schema bd is set past the highest id and past the old sequence's own
    position (so an id the old app ever handed out is never handed out again), then compared: its next
    value must be past the highest id.
Any difference exits non-zero and rolls the target back.

FORWARD writes the whole target in ONE transaction, all or nothing, as bd_app: every row with its id,
a self-reference (contacts.duplicate_of) set once every contact is in, the sequences, the proof. Only
when the proof holds does it write the cut-over record (PATH, a new file: the source's per-table counts
and checksums and the time, names and numbers only) and commit. Then it prints the one-time list of
likely duplicate BD accounts for Hanz, by the very rule the Possible duplicates filter uses
(bd/account_pairs_service.py), as account ids, names and the kind of hint. Nothing is merged.

OUTPUT is names, counts, checksums, account ids and names, and plain error lines. Never a person's
name, phone, email or note, never any other row data, and never a connection string: a database error
is reported by its class, its SQLSTATE and the table, never its message (which can quote a row).

Exit codes: 0 done, 1 an error (nothing kept), 2 usage, 3 refused by the preflight, 4 the proof did not
match, 5 the freeze did not hold.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import json
import pathlib
import re
import sys
from typing import Any, Callable

OLD_SCHEMA = "public"
TOOL_SCHEMA = "bd"
OLD_LEDGER = "schema_migrations"
TOOL_LEDGER = "schema_migrations"
# BD's own migrations, the ones the old database holds (their files are vendored unchanged in
# tests/fixtures/bd_old_migrations).
OLD_MIGRATIONS = ("001_schema.sql", "002_import_values_and_event_history.sql", "003_one_friday_batch.sql",
                  "004_cadence_rules.sql")
# settings rows a migration inserts by itself (004: bd_cadence, when it finds BD contacts). On the
# target they count as empty, and the copy replaces them with the source's.
MIGRATION_SETTINGS_KEYS = ("bd_cadence",)

CHECKSUM_FORM = "md5 of each row's md5(json_build_array(non-generated columns)::text), key order, UTC"
RECORD_NAME = "bd cut-over"

EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_REFUSED, EXIT_MISMATCH, EXIT_FREEZE = 0, 1, 2, 3, 4, 5

OLD_URL_ENV = "BD_CUTOVER_OLD_URL"
TOOL_URL_ENV = "BD_CUTOVER_TOOL_URL"

TS, TEXT, BIGINT, INT, BOOL, DATE, JSONB, TEXTS = (
    "timestamp with time zone", "text", "bigint", "integer", "boolean", "date", "jsonb", "text[]")


@dataclasses.dataclass(frozen=True)
class Table:
    """One table of the map. `old` and `tool` are its names on each side (schema public of the old
    database, schema bd). columns: (name, type) copied and checksummed, the same on both sides.
    generated: (name, type) the database computes on both sides, never written. tool_only: (name, type)
    only schema bd has. key: the order rows are checksummed in. identity: an id identity column.
    deferred: self-references written once every row is in."""
    old: str
    tool: str
    columns: tuple
    key: tuple = ("id",)
    identity: bool = True
    generated: tuple = ()
    tool_only: tuple = ()
    deferred: tuple = ()

    def column_type(self, name: str) -> str:
        return dict(self.columns + self.generated + self.tool_only)[name]


# ── THE MAP: old BD (001-004, schema public) -> schema bd (001-005). Parents first. ───────────────
MAP: tuple = (
    Table("users", "users", (
        ("id", BIGINT), ("email", TEXT), ("name", TEXT), ("role", TEXT), ("active", BOOL), ("auth_sub", TEXT),
        ("last_seen_at", TS), ("created_at", TS))),
    Table("companies", "companies", (
        ("id", BIGINT), ("name", TEXT), ("normalized_name", TEXT), ("city", TEXT), ("industry", TEXT),
        ("created_at", TS)),
        tool_only=(("merged_into", BIGINT), ("merged_at", TS), ("merged_by", BIGINT))),
    Table("contacts", "contacts", (
        ("id", BIGINT), ("company_id", BIGINT), ("name", TEXT), ("title", TEXT), ("email", TEXT),
        ("phone", TEXT), ("city", TEXT), ("industry", TEXT), ("lead_source", TEXT), ("stage", TEXT),
        ("category", TEXT), ("account_type", TEXT), ("owner_id", BIGINT), ("co_owner_id", BIGINT),
        ("co_owner_name", TEXT), ("frequency_per_year", INT), ("confirmed", BOOL), ("importance", INT),
        ("next_step", TEXT), ("next_step_date", DATE), ("promised_date", DATE), ("last_quote_date", DATE),
        ("duplicate_of", BIGINT), ("duplicate_reason", TEXT), ("source", TEXT), ("tags", TEXTS), ("notes", TEXT),
        ("archived_at", TS), ("created_at", TS), ("import_values", JSONB), ("cadence_override", TEXT),
        ("cadence_override_until", DATE)),
        generated=(("email_lower", TEXT), ("phone_e164", TEXT)),
        deferred=("duplicate_of",)),
    Table("interactions", "interactions", (
        ("id", BIGINT), ("contact_id", BIGINT), ("kind", TEXT), ("direction", TEXT), ("outcome", TEXT),
        ("occurred_at", TS), ("duration_s", INT), ("summary", TEXT), ("transcript", TEXT),
        ("recording_url", TEXT), ("provider", TEXT), ("external_id", TEXT), ("user_id", BIGINT),
        ("followup_status", TEXT), ("followup_at", TS), ("created_at", TS)),
        generated=(("counts_as_touch", BOOL),)),
    Table("task_batches", "task_batches", (
        ("id", BIGINT), ("owner_id", BIGINT), ("week_start", DATE), ("kind", TEXT), ("generated_at", TS),
        ("replaced_at", TS))),
    Table("tasks", "tasks", (
        ("id", BIGINT), ("batch_id", BIGINT), ("contact_id", BIGINT), ("kind", TEXT), ("reason", TEXT),
        ("reasons", TEXTS), ("score", INT), ("status", TEXT), ("done_at", TS), ("snoozed_until", DATE),
        ("snooze_reason", TEXT), ("closed_by_archive", BOOL), ("created_at", TS))),
    Table("ai_recommendations", "ai_recommendations", (
        ("id", BIGINT), ("contact_id", BIGINT), ("interaction_id", BIGINT), ("action", TEXT), ("due_date", DATE),
        ("reason", TEXT), ("source", TEXT), ("status", TEXT), ("created_at", TS), ("decided_at", TS),
        ("decided_by", BIGINT))),
    Table("followup_drafts", "followup_drafts", (
        ("id", BIGINT), ("contact_id", BIGINT), ("interaction_id", BIGINT), ("channel", TEXT),
        ("to_address", TEXT), ("subject", TEXT), ("body", TEXT), ("source", TEXT), ("status", TEXT),
        ("sent_interaction_id", BIGINT), ("created_at", TS), ("sent_at", TS))),
    Table("candidates", "candidates", (
        ("id", BIGINT), ("project_id", TEXT), ("project_name", TEXT), ("company", TEXT), ("contact_name", TEXT),
        ("email", TEXT), ("phone", TEXT), ("quote_total", "numeric(14,2)"), ("quote_date", DATE),
        ("status", TEXT), ("possible_duplicate_id", BIGINT), ("contact_id", BIGINT), ("origin", TEXT),
        ("payload", JSONB), ("added_by", BIGINT), ("created_at", TS), ("decided_at", TS))),
    Table("integration_events", "integration_events", (
        ("provider", TEXT), ("event_id", TEXT), ("event_type", TEXT), ("received_at", TS), ("payload", JSONB),
        ("result", TEXT), ("interaction_id", BIGINT)),
        key=("provider", "event_id"), identity=False),
    Table("unmatched_calls", "unmatched_calls", (
        ("id", BIGINT), ("provider", TEXT), ("external_id", TEXT), ("kind", TEXT), ("direction", TEXT),
        ("from_e164", TEXT), ("occurred_at", TS), ("duration_s", INT), ("summary", TEXT), ("transcript", TEXT),
        ("recording_url", TEXT), ("status", TEXT), ("attached_interaction_id", BIGINT), ("handled_by", BIGINT),
        ("handled_at", TS), ("created_at", TS))),
    Table("settings", "settings", (
        ("key", TEXT), ("value", JSONB), ("updated_at", TS), ("updated_by", BIGINT)),
        key=("key",), identity=False),
    Table("events", "events", (
        ("id", BIGINT), ("kind", TEXT), ("actor_id", BIGINT), ("contact_id", BIGINT), ("detail", TEXT),
        ("data", JSONB), ("at", TS))),
    Table("imports", "imports", (
        ("id", BIGINT), ("file_name", TEXT), ("dry_run", BOOL), ("started_at", TS), ("finished_at", TS),
        ("by_id", BIGINT), ("rows_read", INT), ("created", INT), ("updated", INT), ("skipped", INT),
        ("possible_duplicates", INT), ("errors", JSONB))),
)

# Tables only schema bd has (#811). Never copied forward; checked for rows like every other table.
TOOL_ONLY_TABLES: tuple = (
    Table("", "account_pairs_kept", (
        ("account_a", BIGINT), ("account_b", BIGINT), ("decided_by", BIGINT), ("decided_at", TS)),
        key=("account_a", "account_b"), identity=False),
)

_SEQUENCE_NAME = re.compile(r"^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*$")


class CutoverError(Exception):
    """An error the command reports in one plain line. Its message never holds a URL or row data."""


# ── sessions ─────────────────────────────────────────────────────────────────────────────────────
def _session_sql(search_path: str) -> tuple:
    return ("select set_config('TimeZone', 'UTC', false), set_config('DateStyle', 'ISO, MDY', false),"
            " set_config('IntervalStyle', 'postgres', false), set_config('extra_float_digits', '3', false),"
            " set_config('search_path', %s, false), set_config('lock_timeout', '10s', false),"
            " set_config('statement_timeout', '10min', false)", (search_path,))


def _connect(url: str, side: str, read_only: bool) -> Any:
    """A session on one side: UTC, ISO dates, its own search_path. The old side is read only and
    repeatable read, so the forward copy can never write there and reads one snapshot at a time."""
    import psycopg

    try:
        conn = psycopg.connect(url, autocommit=False, connect_timeout=15)
    except Exception as exc:  # noqa: BLE001  (a libpq message can quote the host or the login)
        raise CutoverError("could not connect to the %s database (%s)" % (side, exc.__class__.__name__)) from None
    try:
        if read_only:
            conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            conn.read_only = True
        conn.execute(*_session_sql("pg_catalog" if side == "old" else "bd, pg_catalog"))
        conn.commit()
    except Exception:
        conn.close()
        raise
    return conn


def _rows(conn: Any, query: Any, params: Any = None) -> list:
    from psycopg.rows import tuple_row

    return conn.cursor(row_factory=tuple_row).execute(query, params).fetchall()


def _ident(schema: str, table: str) -> Any:
    from psycopg import sql

    return sql.Identifier(schema, table)


def _name(t: Table, side: str) -> str:
    return t.old if side == "old" else t.tool


# ── preflight ───────────────────────────────────────────────────────────────────────────────────
_CATALOG_SQL = (
    "select c.relname, a.attname, pg_catalog.format_type(a.atttypid, a.atttypmod), a.attgenerated <> ''"
    " from pg_catalog.pg_class c join pg_catalog.pg_namespace n on n.oid = c.relnamespace"
    " left join pg_catalog.pg_attribute a on a.attrelid = c.oid and a.attnum > 0 and not a.attisdropped"
    " where n.nspname = %s and c.relkind in ('r', 'p')")


def schema_problems(conn: Any, side: str) -> list:
    """Each way the side's tables and columns differ from MAP, as plain lines (names only)."""
    schema = OLD_SCHEMA if side == "old" else TOOL_SCHEMA
    where = "the old database" if side == "old" else "schema bd"
    ledger = OLD_LEDGER if side == "old" else TOOL_LEDGER
    tables = MAP if side == "old" else MAP + TOOL_ONLY_TABLES
    want: dict = {}
    for t in tables:
        cols = {c: (ty, False) for c, ty in t.columns}
        cols.update({c: (ty, True) for c, ty in t.generated})
        if side == "tool":
            cols.update({c: (ty, False) for c, ty in t.tool_only})
        want[_name(t, side)] = cols
    have: dict = {}
    for rel, col, typ, gen in _rows(conn, _CATALOG_SQL, (schema,)):
        if rel != ledger:
            have.setdefault(rel, {})
            if col is not None:
                have[rel][col] = (typ, bool(gen))
    out = []
    for rel in sorted(set(want) | set(have)):
        label = "%s.%s" % (schema, rel)
        if rel not in have:
            out.append("refusing: %s has no table %s" % (where, label))
            continue
        if rel not in want:
            out.append("refusing: %s has a table the map does not know: %s" % (where, label))
            continue
        for col in sorted(set(want[rel]) | set(have[rel])):
            if col not in have[rel]:
                out.append("refusing: %s: %s has no column %s" % (where, label, col))
            elif col not in want[rel]:
                out.append("refusing: %s: %s has a column the map does not know: %s" % (where, label, col))
            elif have[rel][col] != want[rel][col]:
                out.append("refusing: %s: %s.%s is not what the map says (%s%s, expected %s%s)" % (
                    where, label, col, have[rel][col][0], " generated" if have[rel][col][1] else "",
                    want[rel][col][0], " generated" if want[rel][col][1] else ""))
    return out


def _other_clients(old: Any) -> int:
    return _rows(old, "select count(*) from pg_catalog.pg_stat_activity where datname = current_database()"
                      " and backend_type = 'client backend' and pid <> pg_catalog.pg_backend_pid()")[0][0]


def _old_ledger_problems(old: Any) -> list:
    if _rows(old, "select to_regclass(%s)", ("%s.%s" % (OLD_SCHEMA, OLD_LEDGER),))[0][0] is None:
        return ["refusing: the old database has no migrations ledger (%s.%s)" % (OLD_SCHEMA, OLD_LEDGER)]
    from psycopg import sql

    names = [r[0] for r in _rows(old, sql.SQL("select name from {} order by name collate \"C\"").format(
        _ident(OLD_SCHEMA, OLD_LEDGER)))]
    if names == list(OLD_MIGRATIONS):
        return []
    extra = [n for n in names if n not in OLD_MIGRATIONS]
    missing = [n for n in OLD_MIGRATIONS if n not in names]
    return ["refusing: the old database's migrations ledger is not BD's original four (001 to 004): %s" % "; ".join(
        ["%s is unexpected" % n for n in extra] + ["%s is missing" % n for n in missing])]


def _tool_login_problems(tool: Any) -> tuple:
    """(problems, whether schema bd exists): the tool login must be bd_app, which cannot create in
    schema bd."""
    if _rows(tool, "select pg_catalog.to_regnamespace('bd') is null")[0][0]:
        return ["refusing: the tool's database has no schema bd (the runner, python -m bd.migrate, makes it)"], False
    can_create = _rows(tool, "select pg_catalog.has_schema_privilege(current_user, 'bd', 'CREATE')")[0][0]
    if can_create:
        return ["refusing: the tool side must connect as bd_app; this login can change schema bd"], True
    return [], True


def _tool_ledger_problems(tool: Any) -> list:
    from .. import ledger

    todo = ledger.pending(tool)
    if todo:
        return ["refusing: schema bd is not migrated up to date (pending: %s)" % ", ".join(todo)]
    return []


def _filled_tables(tool: Any) -> list:
    """The schema bd tables holding a row, settings rows the migrations insert not counted."""
    from psycopg import sql

    out = []
    for t in MAP + TOOL_ONLY_TABLES:
        if t.tool == "settings":
            q = sql.SQL("select exists (select 1 from {} where key <> all(%s))").format(_ident(TOOL_SCHEMA, t.tool))
            filled = _rows(tool, q, (list(MIGRATION_SETTINGS_KEYS),))[0][0]
        else:
            filled = _rows(tool, sql.SQL("select exists (select 1 from {})").format(_ident(TOOL_SCHEMA, t.tool)))[0][0]
        if filled:
            out.append(t.tool)
    return out


def preflight_forward(old: Any, tool: Any, record: pathlib.Path | None) -> list:
    """Every reason the forward copy must not start, as plain lines; [] when it may. Reads only."""
    return _preflight(old, tool, record)[0]


def _preflight(old: Any, tool: Any, record: pathlib.Path | None) -> tuple:
    """(problems, whether the old database's tables are the map's)."""
    problems = []
    if record is not None and record.exists():
        problems.append("refusing: the cut-over record %s already exists (it is never overwritten)" % record.name)
    others = _other_clients(old)
    if others:
        problems.append("refusing: %d other client%s connected to the old database" % (
            others, " is" if others == 1 else "s are"))
    problems += _old_ledger_problems(old)
    old_schema = schema_problems(old, "old")
    problems += old_schema
    old.commit()
    login, has_schema = _tool_login_problems(tool)
    problems += login
    if has_schema:
        problems += _tool_ledger_problems(tool)
        tool_schema = schema_problems(tool, "tool")
        problems += tool_schema
        if not tool_schema:
            problems += ["refusing: bd.%s holds rows" % t for t in _filled_tables(tool)]
    tool.commit()
    return problems, not old_schema


# ── the proof ───────────────────────────────────────────────────────────────────────────────────
def _order(t: Table) -> Any:
    from psycopg import sql

    return sql.SQL(", ").join(
        sql.SQL('{} collate "C"').format(sql.Identifier(k)) if t.column_type(k) == TEXT else sql.Identifier(k)
        for k in t.key)


def checksum_sql(t: Table, side: str) -> Any:
    """count(*) and the checksum of one table on one side (see the module docstring)."""
    from psycopg import sql

    schema = OLD_SCHEMA if side == "old" else TOOL_SCHEMA
    cols = sql.SQL(", ").join(sql.Identifier(c) for c, _ in t.columns)
    return sql.SQL(
        "select count(*)::bigint, pg_catalog.md5(coalesce(pg_catalog.string_agg("
        "pg_catalog.md5(pg_catalog.json_build_array({cols})::text), '' order by {order}), '')) from {table}"
    ).format(cols=cols, order=_order(t), table=_ident(schema, _name(t, side)))


def proof(conn: Any, side: str) -> dict:
    """{old table name: (count, checksum)} for every copied table, in the session's transaction."""
    return {t.old: tuple(_rows(conn, checksum_sql(t, side))[0]) for t in MAP}


def _differences(a: dict, b: dict) -> list:
    return [name for name in a if a[name] != b.get(name)]


# ── sequences ───────────────────────────────────────────────────────────────────────────────────
def _sequence(conn: Any, schema: str, table: str) -> Any:
    from psycopg import sql

    name = _rows(conn, "select pg_catalog.pg_get_serial_sequence(%s, 'id')", ("%s.%s" % (schema, table),))[0][0]
    if not name or not _SEQUENCE_NAME.match(name):
        raise CutoverError("the id sequence of %s.%s could not be found" % (schema, table))
    seq_schema, seq = name.split(".")
    if seq_schema != schema:
        raise CutoverError("the id sequence of %s.%s is outside its schema" % (schema, table))
    return sql.Identifier(seq_schema, seq)


def sequence_state(conn: Any, side: str) -> dict:
    """{old table name: (highest id or 0, the highest value the sequence handed out, its next value)}."""
    from psycopg import sql

    schema = OLD_SCHEMA if side == "old" else TOOL_SCHEMA
    out = {}
    for t in MAP:
        if not t.identity:
            continue
        seq = _sequence(conn, schema, _name(t, side))
        last, called = _rows(conn, sql.SQL("select last_value, is_called from {}").format(seq))[0]
        high = _rows(conn, sql.SQL("select coalesce(max(id), 0) from {}").format(_ident(schema, _name(t, side))))[0][0]
        out[t.old] = (high, last if called else last - 1, last + 1 if called else last)
    return out


def sequence_problems(conn: Any, side: str = "bd") -> list:
    """Each identity sequence whose next value is not past its table's highest id, as plain lines
    ("tasks: ..."). side is "bd" (schema bd) or "old"."""
    side = "old" if side == "old" else "tool"
    return ["%s: the next id %d is not past the highest id %d" % (name, nxt, high)
            for name, (high, _used, nxt) in sequence_state(conn, side).items() if nxt <= high]


# ── forward ─────────────────────────────────────────────────────────────────────────────────────
def _read_source(old: Any) -> tuple:
    """In ONE snapshot: the proof, every row as text, and the sequences."""
    from psycopg import sql

    before = proof(old, "old")
    data = {}
    for t in MAP:
        cols = sql.SQL(", ").join(sql.SQL("{}::text").format(sql.Identifier(c)) for c, _ in t.columns)
        data[t.old] = _rows(old, sql.SQL("select {} from {} order by {}").format(
            cols, _ident(OLD_SCHEMA, t.old), _order(t)))
    seqs = sequence_state(old, "old")
    old.commit()
    return before, data, seqs


def _write_target(tool: Any, data: dict) -> None:
    """Every row into schema bd, in the tool session's open transaction (never committed here)."""
    from psycopg import sql

    settings = _ident(TOOL_SCHEMA, "settings")
    tool.execute(sql.SQL("delete from {} where key = any(%s)").format(settings), (list(MIGRATION_SETTINGS_KEYS),))
    for t in MAP:
        names = [c for c, _ in t.columns]
        values = sql.SQL(", ").join(
            sql.SQL("NULL") if c in t.deferred else sql.SQL("%s::" + ty) for c, ty in t.columns)
        insert = sql.SQL("insert into {} ({}) values ({})").format(
            _ident(TOOL_SCHEMA, t.tool), sql.SQL(", ").join(map(sql.Identifier, names)), values)
        keep = [i for i, c in enumerate(names) if c not in t.deferred]
        rows = data[t.old]
        if rows:
            with tool.cursor() as cur:
                cur.executemany(insert, [[r[i] for i in keep] for r in rows])
        for col in t.deferred:
            i, k = names.index(col), names.index("id")
            later = [(r[i], r[k]) for r in rows if r[i] is not None]
            if later:
                with tool.cursor() as cur:
                    cur.executemany(sql.SQL("update {} set {} = %s::bigint where id = %s::bigint").format(
                        _ident(TOOL_SCHEMA, t.tool), sql.Identifier(col)), later)


def _setval(tool: Any, seq: Any, value: int, called: bool) -> None:
    from psycopg import sql

    _rows(tool, sql.SQL("select pg_catalog.setval({}::regclass, %s, %s)").format(
        sql.Literal(seq.as_string(tool))), (value, called))


def _set_sequences(tool: Any, old_seqs: dict) -> list:
    """Every identity sequence in schema bd past its highest id and past the old sequence's position.
    setval is not undone by a rollback, so this runs only once the rows are proven, and returns what
    the sequences held before ([(sequence, last_value, is_called)]) for _restore_sequences."""
    from psycopg import sql

    before = []
    for t in MAP:
        if not t.identity:
            continue
        seq = _sequence(tool, TOOL_SCHEMA, t.tool)
        before.append((seq,) + tuple(_rows(tool, sql.SQL("select last_value, is_called from {}").format(seq))[0]))
        high = _rows(tool, sql.SQL("select coalesce(max(id), 0) from {}").format(_ident(TOOL_SCHEMA, t.tool)))[0][0]
        upto = max(high, old_seqs[t.old][1])
        _setval(tool, seq, max(upto, 1), upto >= 1)
    return before


def _restore_sequences(tool: Any, before: list) -> None:
    """Put schema bd's sequences back after a copy that is not kept (a fresh transaction)."""
    for seq, last, called in before:
        _setval(tool, seq, last, called)
    tool.commit()


def _record(before: dict) -> dict:
    return {"record": RECORD_NAME, "direction": "forward",
            "at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "checksum": CHECKSUM_FORM,
            "tables": {name: {"count": n, "checksum": s} for name, (n, s) in before.items()}}


def _print_proof(source: dict, target: dict | None, out: Any) -> None:
    if target is None:
        print("%-20s %7s  %s" % ("table", "rows", "checksum"), file=out)
        for name, (n, s) in source.items():
            print("%-20s %7d  %s" % (name, n, s), file=out)
        return
    print("%-20s %7s %7s  %-32s" % ("table", "source", "target", "checksum"), file=out)
    for name, (n, s) in source.items():
        tn, ts = target.get(name, (None, None))
        print("%-20s %7d %7s  %s  %s" % (name, n, tn, s, "matches" if (tn, ts) == (n, s) else "DIFFERS"), file=out)


def _hint(phones: Any, domains: Any) -> str:
    kinds = (["phone"] if phones else []) + (["email domain"] if domains else [])
    return ", ".join(kinds) or "none"


def duplicates(tool: Any) -> list:
    """The one-time list: [(a id, a name, b id, b name, hint kind)] by the Possible duplicates rule."""
    from psycopg.rows import dict_row

    from .. import account_pairs_service as pairs

    previous, tool.row_factory = tool.row_factory, dict_row
    try:
        found = pairs.likely_pairs(tool)
        hints = pairs.hints(tool, sorted({p[1]["id"] for p in found} | {p[2]["id"] for p in found}))
        listed = [(a["id"], a["name"], b["id"], b["name"], _hint(*pairs.shared(hints, a["id"], b["id"])))
                  for _key, a, b in found]
        tool.commit()
    finally:
        tool.row_factory = previous
    return listed


def _print_duplicates(listed: list, out: Any) -> None:
    print("", file=out)
    print("Likely duplicate BD accounts (the Possible duplicates rule), for Hanz to approve:", file=out)
    for row in listed:
        print("  %d %s  +  %d %s  (hint: %s)" % row, file=out)
    print("%d likely pair%s. Nothing was merged." % (len(listed), "" if len(listed) == 1 else "s"), file=out)


def _db_error(exc: Exception, step: str) -> CutoverError:
    """A database error as one plain line: its class, SQLSTATE and table, never its message."""
    diag = getattr(exc, "diag", None)
    table = getattr(diag, "table_name", None) if diag is not None else None
    schema = getattr(diag, "schema_name", None) if diag is not None else None
    where = " on %s.%s" % (schema, table) if table and schema else (" on %s" % table if table else "")
    state = getattr(exc, "sqlstate", None)
    return CutoverError("%s failed: %s%s%s" % (step, exc.__class__.__name__, " (SQLSTATE %s)" % state if state else "",
                                               where))


def forward(old_url: str, tool_url: str, record_path: Any, *, out: Any = None, err: Any = None,
            after_source_read: Callable[[], None] | None = None) -> int:
    """The forward copy (see the module docstring). Returns the exit code. `after_source_read` runs
    between the source's first reading and its second (tests use it to break the freeze)."""
    out = out or sys.stdout
    err = err or sys.stderr
    try:
        return _forward(old_url, tool_url, pathlib.Path(record_path), out, err, after_source_read)
    except CutoverError as exc:
        print("error: %s" % exc, file=err)
        return EXIT_ERROR


def _forward(old_url: str, tool_url: str, record: pathlib.Path, out: Any, err: Any,
             after_source_read: Callable[[], None] | None) -> int:
    import psycopg

    old = tool = None
    try:
        old = _connect(old_url, "old", read_only=True)
        tool = _connect(tool_url, "tool", read_only=False)
        step = "the preflight"
        try:
            problems = preflight_forward(old, tool, record)
            if problems:
                for line in problems:
                    print(line, file=err)
                return EXIT_REFUSED
            step = "reading the old database"
            before, data, old_seqs = _read_source(old)
            if after_source_read is not None:
                after_source_read()
            step = "writing schema bd"
            _write_target(tool, data)
            step = "the proof"
            target = proof(tool, "tool")
            after = proof(old, "old")
            old.commit()
            changed = _differences(before, after)
            mismatched = _differences(before, target)
            seq_problems: list = []
            seqs_before: list = []
            if not changed and not mismatched:
                step = "setting the sequences"
                seqs_before = _set_sequences(tool, old_seqs)
                seq_problems = sequence_problems(tool, "bd")
                if seq_problems:
                    tool.rollback()
                    _restore_sequences(tool, seqs_before)
        except psycopg.Error as exc:
            tool.rollback()
            raise _db_error(exc, step) from None
        if changed:
            tool.rollback()
            print("freeze broken: the old database changed during the copy, so nothing was kept in schema bd.",
                  file=err)
            for name in changed:
                (n0, s0), (n1, s1) = before[name], after[name]
                print("  %s: %s" % (name, "rows %d -> %d" % (n0, n1) if n0 != n1 else "checksum changed"), file=err)
            return EXIT_FREEZE
        if mismatched or seq_problems:
            tool.rollback()
            print("proof failed, so nothing was kept in schema bd:", file=err)
            for name in mismatched:
                print("  %s: the source has %d rows, %s; schema bd has %d rows, %s" % (
                    (name,) + before[name] + target[name]), file=err)
            for line in seq_problems:
                print("  " + line, file=err)
            _print_proof(before, target, err)
            return EXIT_MISMATCH
        try:
            with open(record, "x", encoding="utf-8") as fh:
                json.dump(_record(before), fh, indent=2)
                fh.write("\n")
        except OSError as exc:
            tool.rollback()
            raise CutoverError("the cut-over record could not be written (%s), so nothing was kept"
                               % exc.__class__.__name__) from None
        try:
            tool.commit()
        except psycopg.Error as exc:
            record.unlink(missing_ok=True)
            try:
                tool.rollback()
                _restore_sequences(tool, seqs_before)
            except psycopg.Error:
                pass
            raise _db_error(exc, "committing schema bd") from None
        print("Forward copy: the old BD database -> schema bd. Every table matches.", file=out)
        _print_proof(before, target, out)
        print("Sequences: every id sequence in schema bd continues past its highest id.", file=out)
        print("Freeze held: the old database did not change during the copy.", file=out)
        print("Cut-over record written: %s" % record.name, file=out)
        try:
            listed = duplicates(tool)
        except psycopg.Error as exc:
            raise _db_error(exc, "the duplicates list (the copy itself is in and proven)") from None
        _print_duplicates(listed, out)
        return EXIT_OK
    finally:
        for conn in (tool, old):
            if conn is not None:
                conn.close()


def check(old_url: str, tool_url: str, *, out: Any = None, err: Any = None) -> int:
    """The forward preflight and the source's proof. Writes nothing anywhere."""
    out = out or sys.stdout
    err = err or sys.stderr
    try:
        return _check(old_url, tool_url, out, err)
    except CutoverError as exc:
        print("error: %s" % exc, file=err)
        return EXIT_ERROR


def _check(old_url: str, tool_url: str, out: Any, err: Any) -> int:
    import psycopg

    old = tool = None
    try:
        old = _connect(old_url, "old", read_only=True)
        tool = _connect(tool_url, "tool", read_only=False)
        tool.read_only = True
        try:
            problems, old_schema_ok = _preflight(old, tool, None)
            source = proof(old, "old") if old_schema_ok else None
            old.commit()
        except psycopg.Error as exc:
            raise _db_error(exc, "the check") from None
        for line in problems:
            print(line, file=err)
        if source is not None:
            print("The old BD database:", file=out)
            _print_proof(source, None, out)
        return EXIT_REFUSED if problems else EXIT_OK
    finally:
        for conn in (tool, old):
            if conn is not None:
                conn.close()


def main(argv: Any = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m bd.ops.cutover",
        description="Copy BD's data between the old BD database and schema bd, with proof. The two "
                    "databases come from %s and %s, never the command line." % (OLD_URL_ENV, TOOL_URL_ENV))
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="the preflight and the old database's counts and checksums; writes nothing")
    fwd = sub.add_parser("forward", help="copy the old database into an empty schema bd, prove it, list likely "
                                         "duplicate accounts")
    fwd.add_argument("--record", required=True, metavar="PATH",
                     help="the cut-over record to write (a new file: counts and checksums, no row data)")
    args = ap.parse_args(argv)

    from .. import config

    urls = {OLD_URL_ENV: config.cutover_old_url(), TOOL_URL_ENV: config.cutover_tool_url()}
    missing = [name for name, value in urls.items() if not value]
    if missing:
        print("refusing: set %s in the environment (never on the command line)" % " and ".join(missing),
              file=sys.stderr)
        return EXIT_USAGE
    try:
        if args.command == "forward":
            return forward(urls[OLD_URL_ENV], urls[TOOL_URL_ENV], args.record)
        return check(urls[OLD_URL_ENV], urls[TOOL_URL_ENV])
    except CutoverError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return EXIT_ERROR
    except Exception as exc:  # noqa: BLE001  (its message could quote a row or a URL: the class only)
        print("error: %s; no details are printed because they can hold row data" % exc.__class__.__name__,
              file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
