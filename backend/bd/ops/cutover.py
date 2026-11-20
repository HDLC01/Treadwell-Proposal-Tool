"""The cut-over copy (#812, #802 Q3, Q37, Q38): BD's data between the OLD BD database and schema bd.

    cd backend
    python -m bd.ops.cutover check                       # the preflight and the source's proof; writes nothing
    python -m bd.ops.cutover forward --record PATH       # old database -> schema bd, then the duplicates list
    python -m bd.ops.cutover reverse --record PATH       # schema bd -> old database (a rollback), with bd_carry

    cutover.forward(old_url, tool_url, record_path) -> exit code
    cutover.reverse(old_url, tool_url, record_path) -> exit code
    cutover.check(old_url, tool_url) -> exit code

THE TWO DATABASES come from the environment, never the command line, and are never printed, logged
or put in an error message (bd/config.py reads them live):
    BD_CUTOVER_OLD_URL    the old BD database, as its owner login. check and forward only READ it (their
                          sessions on it are read only); only reverse writes there.
    BD_CUTOVER_TOOL_URL   the tool's database as bd_app (the same value as BD_DATABASE_URL). The command
                          refuses a login that could change schema bd's structure, and touches nothing
                          outside schema bd: every table it names is bd.<table>, and the catalog is read
                          only for schema bd's own tables and sequences. reverse only READS it (its
                          session there is read only).
On the server it runs in a one-off container from the tool's image that joins the old BD network,
because the old database publishes no port (docs/bd/cutover-runbook.md). It is never run against
staging, prod or real data except by that runbook, on Hanz's go.

THE MAP. MAP below is the one explicit map from BD's old tables (schema public of the old database,
from BD's own migrations 001 to 004) to schema bd (the tool's 001 to 005). The tool's 001 to 004 are
BD's four files placed in schema bd, so every table keeps its name and every column its name and type.
What differs, and why bd_carry exists (below): only schema bd has companies.merged_into, merged_at and
merged_by and the table account_pairs_kept (005, #811). The old app has no column the tool lacks.
Generated columns (contacts.email_lower and phone_e164, interactions.counts_as_touch) are never
written: the database fills them. The old migrations table (public.schema_migrations) is never copied,
and bd.schema_migrations is never written.

PREFLIGHT (forward and check). It refuses, naming each problem, before anything is written:
  * the record file already exists (a cut-over record is never overwritten);
  * the old login cannot see other sessions (it is neither a superuser nor in pg_read_all_stats, so
    Postgres hides the other roles' sessions from it), or any other client is connected to the old
    database (pg_stat_activity; this command's own session is not counted, and a session still
    listed for a client that has just disconnected is waited for, up to OTHER_CLIENTS_WAIT seconds);
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
    position (so an id the old app ever handed out is never handed out again), and never moved back
    from where it already was, then compared: its next value must be past the highest id.
Any difference exits non-zero and rolls the target back. setval is not undone by a rollback, so the
command puts back every sequence it had set itself, whatever stopped it.
The freeze is proven up to the proof: between the source's second reading and the commit only the
sequences, the duplicates list and the record are written, and what keeps the source still in that
moment is the freeze itself (the old app stopped, no other client, as the preflight saw).

FORWARD writes the whole target in ONE transaction, all or nothing, as bd_app: every row with its id,
a self-reference (contacts.duplicate_of) set once every contact is in, the sequences, the proof. Only
when the proof holds does it read the one-time list of likely duplicate BD accounts (in the same
transaction), write the cut-over record (PATH, a new file: the source's per-table counts and checksums
and the time, names and numbers only) and commit. Then it prints the list for Hanz, by the Likely
duplicate accounts rule (bd/account_pairs_service.py, the pairs the Contacts page's Possible duplicates
filter shows), as account ids, names and the kind of hint. Nothing is merged.
When the commit fails, the record is deleted only when the server clearly refused it; when the
connection dropped during the commit, the commit may have landed, so the record stays and the command
exits 6 (run check: "bd.<table> holds rows" means the copy is in).
When the old database holds a bd_carry (a rollback happened), the forward copy puts it back once the
rows are in and before the proof, in the same transaction, and proves schema bd then holds exactly
the marks and kept pairs it put back (see BD_CARRY).

REVERSE (a rollback, #802 Q38) copies schema bd back into the old database's tables, as the old
database's owner. Its preflight refuses, naming each problem, before anything is written:
  * the cut-over record PATH is missing, is not a forward copy's record, or was made with another
    checksum form;
  * the old login cannot see other sessions, or any other client is connected to the old database;
  * the old database's ledger is not BD's four, or either side differs from MAP;
  * the tool login can create in schema bd, or schema bd is behind the code;
  * schema bd holds no BD rows at all (the copy would empty the old database);
  * the old database no longer matches the record, each differing table named: something wrote to it
    after the cut-over. Its tables are locked (EXCLUSIVE, so the old app cannot write) before this
    comparison, in the very transaction that then replaces them.
Then, in ONE transaction on the old database: every old table emptied (TRUNCATE, which is
transactional and fires no row trigger) and refilled from schema bd with the columns the old app has
(MAP's columns; a self-reference once every row is in), bd_carry replaced, the proof (the old
database's counts and checksums equal schema bd's; schema bd read in one read-only snapshot and again
after the write, its merge marks and kept pairs too: the freeze proof; bd_carry read back equal to
what was saved), then every identity sequence in the old database set past its highest id and past
schema bd's own sequence (an id the tool handed out is never handed out again by the old app) and
compared. Any difference rolls the old database back, sequences included. Schema bd is never written.

BD_CARRY. The BD-only state the old app has no column for, kept in schema bd_carry of the OLD database,
which the old app never reads. A reverse copy replaces it (its two tables dropped and made again, in
the same transaction):
    bd_carry.merge_marks (company_id, merged_into, merged_at, merged_by, people)   every merged-away
                         account's mark, and the ids of the people at it in schema bd (normally none)
    bd_carry.kept_pairs  (account_a, account_b, decided_by, decided_at)            account_pairs_kept
The next forward copy puts each mark back, except on an account that is no longer in the old database
(or whose survivor or merging user is not), and on an account that GAINED PEOPLE in the old app during
the rollback (any person there who was not there when it was saved): marking it would hide them, so
it gets no mark and is listed for Hanz by account id and name. A kept pair whose account or user is
gone is listed too. A forward copy refuses a bd_carry whose tables are not the two above.

OUTPUT is names, counts, checksums, account ids and names, and plain error lines. Never a person's
name, phone, email or note, never any other row data, and never a connection string: a database error
is reported by its class, its SQLSTATE and the table, never its message (which can quote a row).

Exit codes: 0 done, 1 an error (nothing kept), 2 usage, 3 refused by the preflight, 4 the proof did not
match, 5 the freeze did not hold (forward: the old database changed; reverse: schema bd changed),
6 forward only: the connection dropped during the commit, so whether schema bd holds the copy is
unknown (the record is kept; run check before anything else).
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import json
import pathlib
import re
import sys
import time
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

EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_REFUSED, EXIT_MISMATCH, EXIT_FREEZE, EXIT_COMMIT_UNKNOWN = 0, 1, 2, 3, 4, 5, 6

# A client that has just disconnected is still listed in pg_stat_activity until its backend has
# finished exiting, which the client never waits for (1 to 70 ms measured on a local server, longer
# on a loaded one): the old app just stopped, a pg_dump just finished, the previous subcommand just
# ended. Before refusing over another client the preflight reads the list again, every
# OTHER_CLIENTS_POLL seconds for up to OTHER_CLIENTS_WAIT seconds; a client still connected then is
# refused. Postgres waits the same 5 seconds for such sessions before CREATE or DROP DATABASE refuses
# a database "being accessed by other users".
OTHER_CLIENTS_WAIT = 5.0
OTHER_CLIENTS_POLL = 0.05

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

# bd_carry in the OLD database (see BD_CARRY): the BD-only state a reverse copy saves for the next
# forward copy. Its shape is checked by the forward preflight; the reverse copy makes it.
CARRY_SCHEMA = "bd_carry"
CARRY: dict = {      # {table: ((column, type), ...)}
    "merge_marks": (("company_id", BIGINT), ("merged_into", BIGINT), ("merged_at", TS), ("merged_by", BIGINT),
                    ("people", "bigint[]")),
    "kept_pairs": (("account_a", BIGINT), ("account_b", BIGINT), ("decided_by", BIGINT), ("decided_at", TS)),
}
CARRY_DDL = (
    "create table bd_carry.merge_marks (company_id bigint primary key, merged_into bigint not null,"
    " merged_at timestamptz not null, merged_by bigint, people bigint[] not null)",
    "create table bd_carry.kept_pairs (account_a bigint not null, account_b bigint not null,"
    " decided_by bigint not null, decided_at timestamptz not null, primary key (account_a, account_b))",
)
CARRY_COMMENT = ("BD-only state saved by the cut-over copy's reverse copy (#812); the next forward copy "
                 "puts it back. The old BD app never reads it.")
GAINED = "gained people in the old app"
GONE = "no longer in the old database"

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
    """A session on one side (side names it in errors and picks its search_path): UTC, ISO dates.
    read_only=True makes the session read only and repeatable read, so it can never write and each
    transaction reads one snapshot: check and forward open the old side so, reverse the tool side."""
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
    return _shape_problems(want, have, schema, where)


def _carry_problems(old: Any) -> list:
    """Each way the old database's bd_carry differs from CARRY ([] when there is none)."""
    if _rows(old, "select pg_catalog.to_regnamespace(%s) is null", (CARRY_SCHEMA,))[0][0]:
        return []
    want = {name: {c: (ty, False) for c, ty in cols} for name, cols in CARRY.items()}
    have: dict = {}
    for rel, col, typ, gen in _rows(old, _CATALOG_SQL, (CARRY_SCHEMA,)):
        have.setdefault(rel, {})
        if col is not None:
            have[rel][col] = (typ, bool(gen))
    return _shape_problems(want, have, CARRY_SCHEMA, "the old database's bd_carry")


def _shape_problems(want: dict, have: dict, schema: str, where: str) -> list:
    """{table: {column: (type, generated)}} wanted against what the catalog has, as plain lines."""
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
    """How many other client sessions the old database has, once those that are only leaving have
    gone (see OTHER_CLIENTS_WAIT). pg_stat_activity is read once per transaction unless its snapshot
    is cleared, so each new reading clears it first."""
    deadline = time.monotonic() + OTHER_CLIENTS_WAIT
    while True:
        others = _rows(old, "select count(*) from pg_catalog.pg_stat_activity where datname = current_database()"
                            " and backend_type = 'client backend' and pid <> pg_catalog.pg_backend_pid()")[0][0]
        if not others or time.monotonic() >= deadline:
            return others
        time.sleep(OTHER_CLIENTS_POLL)
        _rows(old, "select pg_catalog.pg_stat_clear_snapshot()")


def _old_login_problems(old: Any) -> list:
    """Postgres hides another role's session details (backend_type among them) from a login that is
    neither a superuser nor in pg_read_all_stats, so such a login cannot count the other clients."""
    sees = _rows(old, "select r.rolsuper or pg_catalog.pg_has_role(current_user, 'pg_read_all_stats', 'USAGE')"
                      " from pg_catalog.pg_roles r where r.rolname = current_user")[0][0]
    if sees:
        return []
    return ["refusing: the old login cannot see other sessions; use the old database's owner (a superuser)"
            " or a login in pg_read_all_stats"]


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


def _shared_preflight(old: Any, tool: Any) -> tuple:
    """The checks both directions run: (problems, whether the old database's tables are the map's,
    whether schema bd's are, how many other clients the old database has). Leaves the old session's
    transaction open (the reverse copy locks in it); ends the tool session's."""
    problems = _old_login_problems(old)
    others = _other_clients(old)
    if others:
        problems.append("refusing: %d other client%s connected to the old database" % (
            others, " is" if others == 1 else "s are"))
    problems += _old_ledger_problems(old)
    old_schema = schema_problems(old, "old")
    problems += old_schema
    login, has_schema = _tool_login_problems(tool)
    problems += login
    tool_ok = False
    if has_schema:
        problems += _tool_ledger_problems(tool)
        tool_schema = schema_problems(tool, "tool")
        problems += tool_schema
        tool_ok = not tool_schema
    tool.commit()
    return problems, not old_schema, tool_ok, others


def _preflight(old: Any, tool: Any, record: pathlib.Path | None) -> tuple:
    """(problems, whether the old database's tables are the map's)."""
    problems = []
    if record is not None and record.exists():
        problems.append("refusing: the cut-over record %s already exists (it is never overwritten)" % record.name)
    shared, old_ok, tool_ok, _others = _shared_preflight(old, tool)
    problems += shared + _carry_problems(old)
    old.commit()
    if tool_ok:
        problems += ["refusing: bd.%s holds rows" % t for t in _filled_tables(tool)]
        tool.commit()
    return problems, old_ok


# ── the reverse preflight ───────────────────────────────────────────────────────────────────────
def read_record(record: pathlib.Path) -> tuple:
    """(the forward copy's {table: (count, checksum)}, problems): the cut-over record, checked."""
    bad = ["refusing: the cut-over record %s is not a cut-over record from a forward copy" % record.name]
    if not record.exists():
        return None, ["refusing: the cut-over record %s does not exist" % record.name]
    try:
        data = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, bad
    if not isinstance(data, dict) or data.get("record") != RECORD_NAME or data.get("direction") != "forward":
        return None, bad
    if data.get("checksum") != CHECKSUM_FORM:
        return None, ["refusing: the cut-over record %s was made with another checksum form" % record.name]
    tables = data.get("tables")
    if not isinstance(tables, dict) or set(tables) != {t.old for t in MAP}:
        return None, bad
    out = {}
    for t in MAP:
        entry = tables[t.old]
        if not isinstance(entry, dict) or type(entry.get("count")) is not int \
                or not re.fullmatch(r"[0-9a-f]{32}", str(entry.get("checksum"))):
            return None, bad
        out[t.old] = (entry["count"], entry["checksum"])
    return out, []


def _lock_old_tables(old: Any) -> None:
    """EXCLUSIVE on every old table until the transaction ends: others may read, nobody may write."""
    from psycopg import sql

    old.execute(sql.SQL("lock table {} in exclusive mode").format(
        sql.SQL(", ").join(_ident(OLD_SCHEMA, t.old) for t in MAP)))


def _preflight_reverse(old: Any, tool: Any, record: pathlib.Path) -> list:
    """Every reason the reverse copy must not start, as plain lines. On [] the old database's tables
    are locked in the old session's open transaction, which the copy then uses."""
    recorded, problems = read_record(record)
    shared, old_ok, tool_ok, others = _shared_preflight(old, tool)
    problems += shared
    if tool_ok and not [t for t in _filled_tables(tool) if t in {m.tool for m in MAP}]:
        problems.append("refusing: schema bd holds no BD rows, so a reverse copy would empty the old database")
    tool.commit()
    if recorded is not None and old_ok:
        if not others:
            _lock_old_tables(old)
        now = proof(old, "old")
        for name, (n, s) in recorded.items():
            if now[name] != (n, s):
                problems.append("refusing: the old database no longer matches the cut-over record: %s (%s)" % (
                    name, "rows %d -> %d" % (n, now[name][0]) if now[name][0] != n else "checksum changed"))
    return problems


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


def sequence_problems(conn: Any, side: str = "tool") -> list:
    """Each identity sequence whose next value is not past its table's highest id, as plain lines
    ("tasks: ..."). side is "tool" (schema bd) or "old"."""
    return ["%s: the next id %d is not past the highest id %d" % (name, nxt, high)
            for name, (high, _used, nxt) in sequence_state(conn, side).items() if nxt <= high]


# ── forward ─────────────────────────────────────────────────────────────────────────────────────
def _read_source(conn: Any, side: str) -> tuple:
    """In ONE snapshot of the source side: the proof, every row as text, the sequences, and the
    BD-only state (forward: the old database's bd_carry or None; reverse: schema bd's marks and kept
    pairs)."""
    from psycopg import sql

    schema = OLD_SCHEMA if side == "old" else TOOL_SCHEMA
    before = proof(conn, side)
    data = {}
    for t in MAP:
        cols = sql.SQL(", ").join(sql.SQL("{}::text").format(sql.Identifier(c)) for c, _ in t.columns)
        data[t.old] = _rows(conn, sql.SQL("select {} from {} order by {}").format(
            cols, _ident(schema, _name(t, side)), _order(t)))
    seqs = sequence_state(conn, side)
    carry = read_carry(conn) if side == "old" else tool_carry(conn)
    conn.commit()
    return before, data, seqs, carry


def _write_rows(conn: Any, side: str, data: dict) -> None:
    """Every row into the target side, in its session's open transaction (never committed here).
    Schema bd starts empty but for a migration-inserted settings row, which goes; the old database's
    tables are emptied first (the reverse copy REPLACES them)."""
    from psycopg import sql

    schema = OLD_SCHEMA if side == "old" else TOOL_SCHEMA
    if side == "old":
        conn.execute(sql.SQL("truncate table {}").format(
            sql.SQL(", ").join(_ident(OLD_SCHEMA, t.old) for t in MAP)))
    else:
        settings = _ident(TOOL_SCHEMA, "settings")
        conn.execute(sql.SQL("delete from {} where key = any(%s)").format(settings), (list(MIGRATION_SETTINGS_KEYS),))
    for t in MAP:
        names = [c for c, _ in t.columns]
        values = sql.SQL(", ").join(
            sql.SQL("NULL") if c in t.deferred else sql.SQL("%s::" + ty) for c, ty in t.columns)
        insert = sql.SQL("insert into {} ({}) values ({})").format(
            _ident(schema, _name(t, side)), sql.SQL(", ").join(map(sql.Identifier, names)), values)
        keep = [i for i, c in enumerate(names) if c not in t.deferred]
        rows = data[t.old]
        if rows:
            with conn.cursor() as cur:
                cur.executemany(insert, [[r[i] for i in keep] for r in rows])
        for col in t.deferred:
            i, k = names.index(col), names.index("id")
            later = [(r[i], r[k]) for r in rows if r[i] is not None]
            if later:
                with conn.cursor() as cur:
                    cur.executemany(sql.SQL("update {} set {} = %s::bigint where id = %s::bigint").format(
                        _ident(schema, _name(t, side)), sql.Identifier(col)), later)


def _setval(tool: Any, seq: Any, value: int, called: bool) -> None:
    from psycopg import sql

    _rows(tool, sql.SQL("select pg_catalog.setval({}::regclass, %s, %s)").format(
        sql.Literal(seq.as_string(tool))), (value, called))


def _set_sequences(conn: Any, side: str, other_seqs: dict, done: list) -> None:
    """Every identity sequence on the target side past its highest id and past the source sequence's
    position (other_seqs, from sequence_state of the other side), and never back from where it is.
    setval is not undone by a rollback, so this runs only once the rows are proven, and appends what
    each sequence held before ((sequence, last_value, is_called)) to `done` as soon as it is set: a
    failure partway leaves `done` naming exactly the ones to put back (_undo)."""
    from psycopg import sql

    schema = OLD_SCHEMA if side == "old" else TOOL_SCHEMA
    for t in MAP:
        if not t.identity:
            continue
        seq = _sequence(conn, schema, _name(t, side))
        last, called = _rows(conn, sql.SQL("select last_value, is_called from {}").format(seq))[0]
        high = _rows(conn, sql.SQL("select coalesce(max(id), 0) from {}").format(_ident(schema, _name(t, side))))[0][0]
        upto = max(high, other_seqs[t.old][1], last if called else last - 1)
        _setval(conn, seq, max(upto, 1), upto >= 1)
        done.append((seq, last, called))


def _restore_sequences(conn: Any, before: list) -> None:
    """Put the target's sequences back after a copy that is not kept (a fresh transaction)."""
    for seq, last, called in before:
        _setval(conn, seq, last, called)
    conn.commit()


def _undo(conn: Any, seqs_set: list) -> None:
    """Roll the target back and put back every sequence this run set. Best effort: on a connection
    that is gone, the sequences it set stay ahead, which leaves a gap in ids, never a reused one."""
    import psycopg

    try:
        conn.rollback()
        if seqs_set:
            _restore_sequences(conn, seqs_set)
    except psycopg.Error:
        pass


# ── bd_carry ────────────────────────────────────────────────────────────────────────────────────
def tool_carry(tool: Any) -> tuple:
    """Schema bd's BD-only state, as it goes into bd_carry: ([(account, merged into, merged at as UTC
    text, merged by, [ids of the people at it])], [(account a, account b, decided by, decided at)])."""
    marks = _rows(tool, "select co.id, co.merged_into, co.merged_at::text, co.merged_by,"
                        " coalesce((select array_agg(c.id order by c.id) from bd.contacts c where c.company_id = co.id),"
                        " '{}'::bigint[]) from bd.companies co where co.merged_into is not null order by co.id")
    kept = _rows(tool, "select account_a, account_b, decided_by, decided_at::text from bd.account_pairs_kept"
                       " order by account_a, account_b")
    return [tuple(r) for r in marks], [tuple(r) for r in kept]


def _tool_marks_and_kept(tool: Any) -> tuple:
    """What schema bd holds now: ([(account, merged into, merged at, merged by)], [kept pair rows])."""
    marks, kept = tool_carry(tool)
    return [m[:4] for m in marks], kept


def read_carry(old: Any) -> dict | None:
    """The old database's bd_carry, None when there is none. Each mark carries the account's and its
    survivor's names (None when gone), whether the account gained people (a person there now who was
    not there when it was saved) and whether the account, its survivor and the merging user are all
    still there; each kept pair whether its accounts and user are."""
    if _rows(old, "select pg_catalog.to_regnamespace(%s) is null", (CARRY_SCHEMA,))[0][0]:
        return None
    marks = _rows(
        old, "select m.company_id, m.merged_into, m.merged_at::text, m.merged_by, co.name, su.name,"
             " exists (select 1 from public.contacts c where c.company_id = m.company_id"
             "   and c.id <> all(m.people)),"
             " co.id is not null and su.id is not null and (m.merged_by is null"
             "   or exists (select 1 from public.users u where u.id = m.merged_by))"
             " from bd_carry.merge_marks m left join public.companies co on co.id = m.company_id"
             " left join public.companies su on su.id = m.merged_into order by m.company_id")
    kept = _rows(
        old, "select k.account_a, k.account_b, k.decided_by, k.decided_at::text,"
             " exists (select 1 from public.companies c where c.id = k.account_a)"
             " and exists (select 1 from public.companies c where c.id = k.account_b)"
             " and exists (select 1 from public.users u where u.id = k.decided_by)"
             " from bd_carry.kept_pairs k order by k.account_a, k.account_b")
    return {"marks": [tuple(r) for r in marks], "kept": [tuple(r) for r in kept]}


def _saved_carry(old: Any) -> tuple:
    """bd_carry read back as saved: (marks with their people, kept pairs), in tool_carry's shape."""
    marks = _rows(old, "select company_id, merged_into, merged_at::text, merged_by, people"
                       " from bd_carry.merge_marks order by company_id")
    kept = _rows(old, "select account_a, account_b, decided_by, decided_at::text from bd_carry.kept_pairs"
                      " order by account_a, account_b")
    return [tuple(r) for r in marks], [tuple(r) for r in kept]


def _save_carry(old: Any, carry: tuple) -> None:
    """Replace the old database's bd_carry with schema bd's state (the old session's transaction)."""
    from psycopg import sql

    marks, kept = carry
    old.execute("create schema if not exists bd_carry")
    old.execute("drop table if exists bd_carry.merge_marks, bd_carry.kept_pairs")
    for ddl in CARRY_DDL:
        old.execute(ddl)
    old.execute(sql.SQL("comment on schema bd_carry is {}").format(sql.Literal(CARRY_COMMENT)))
    with old.cursor() as cur:
        if marks:
            cur.executemany("insert into bd_carry.merge_marks (company_id, merged_into, merged_at, merged_by, people)"
                            " values (%s::bigint, %s::bigint, %s::timestamptz, %s::bigint, %s::bigint[])", marks)
        if kept:
            cur.executemany("insert into bd_carry.kept_pairs (account_a, account_b, decided_by, decided_at)"
                            " values (%s::bigint, %s::bigint, %s::bigint, %s::timestamptz)", kept)


def _apply_carry(tool: Any, carry: dict) -> dict:
    """Put bd_carry back into schema bd, in the tool session's open transaction, once the rows are in.
    Returns {"marks": put back, "kept": put back, "left": [(account, its name, survivor, its name,
    why)] not put back, "left_kept": [(a, b)] not put back}."""
    marks, kept, left, left_kept = [], [], [], []
    for cid, into, at, by, name, into_name, gained, present in carry["marks"]:
        if not present:
            left.append((cid, name, into, into_name, GONE))
        elif gained:
            left.append((cid, name, into, into_name, GAINED))
        else:
            marks.append((cid, into, at, by))
    for a, b, by, at, present in carry["kept"]:
        if present:
            kept.append((a, b, by, at))
        else:
            left_kept.append((a, b))
    with tool.cursor() as cur:
        for cid, into, at, by in marks:
            cur.execute("update bd.companies set merged_into = %s::bigint, merged_at = %s::timestamptz,"
                        " merged_by = %s::bigint where id = %s::bigint and merged_into is null", (into, at, by, cid))
            if cur.rowcount != 1:
                raise CutoverError("the merge mark of BD account %d could not be put back, so nothing was kept"
                                   % cid)
        if kept:
            cur.executemany("insert into bd.account_pairs_kept (account_a, account_b, decided_by, decided_at)"
                            " values (%s::bigint, %s::bigint, %s::bigint, %s::timestamptz)", kept)
    return {"marks": marks, "kept": kept, "left": left, "left_kept": left_kept}


def _plural(n: int, word: str) -> str:
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def _print_carry_left(applied: dict, out: Any) -> None:
    if applied["left"]:
        print("Merged-away accounts whose mark was not put back, so nobody is hidden (for Hanz):", file=out)
        for cid, name, into, into_name, why in applied["left"]:
            print("  %d %s, merged into %d %s: %s" % (cid, name or "(gone)", into, into_name or "(gone)", why),
                  file=out)
    if applied["left_kept"]:
        print("Kept pairs not put back (for Hanz):", file=out)
        for a, b in applied["left_kept"]:
            print("  %d + %d: %s" % (a, b, GONE), file=out)


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
    """The one-time list: [(a id, a name, b id, b name, hint kind)] by the Likely duplicate accounts
    rule. Reads in the session's open transaction (the forward copy's, before its commit)."""
    from psycopg.rows import dict_row

    from .. import account_pairs_service as pairs

    previous, tool.row_factory = tool.row_factory, dict_row
    try:
        found = pairs.likely_pairs(tool)
        hints = pairs.hints(tool, sorted({p[1]["id"] for p in found} | {p[2]["id"] for p in found}))
        listed = [(a["id"], a["name"], b["id"], b["name"], _hint(*pairs.shared(hints, a["id"], b["id"])))
                  for _key, a, b in found]
    finally:
        tool.row_factory = previous
    return listed


def _print_duplicates(listed: list, out: Any) -> None:
    print("", file=out)
    print("Likely duplicate BD accounts, for Hanz to approve (merge or keep separate in the BD CRM):", file=out)
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
    seqs_set: list = []
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
            before, data, old_seqs, carry = _read_source(old, "old")
            if after_source_read is not None:
                after_source_read()
            step = "writing schema bd"
            _write_rows(tool, "tool", data)
            step = "putting bd_carry back"
            applied = _apply_carry(tool, carry) if carry is not None else None
            step = "the proof"
            target = proof(tool, "tool")
            after = proof(old, "old")
            changed = _differences(before, after)
            if carry is not None and read_carry(old) != carry:
                changed.append(CARRY_SCHEMA)
            old.commit()
            mismatched = _differences(before, target)
            if applied is not None and _tool_marks_and_kept(tool) != (applied["marks"], applied["kept"]):
                mismatched.append(CARRY_SCHEMA)
            seq_problems: list = []
            listed: list = []
            if not changed and not mismatched:
                step = "setting the sequences"
                _set_sequences(tool, "tool", old_seqs, seqs_set)
                seq_problems = sequence_problems(tool, "tool")
                if not seq_problems:
                    step = "the duplicates list"
                    listed = duplicates(tool)
        except Exception as exc:  # noqa: BLE001  (whatever stopped it, the sequences it set go back)
            _undo(tool, seqs_set)
            if isinstance(exc, psycopg.Error):
                raise _db_error(exc, step) from None
            raise
        if changed:
            _undo(tool, seqs_set)
            print("freeze broken: the old database changed during the copy, so nothing was kept in schema bd.",
                  file=err)
            _print_changed(changed, before, after, err)
            return EXIT_FREEZE
        if mismatched or seq_problems:
            _undo(tool, seqs_set)
            print("proof failed, so nothing was kept in schema bd:", file=err)
            _print_mismatched(mismatched, before, target, "schema bd", err)
            for line in seq_problems:
                print("  " + line, file=err)
            _print_proof(before, target, err)
            return EXIT_MISMATCH
        try:
            with open(record, "x", encoding="utf-8") as fh:
                json.dump(_record(before), fh, indent=2)
                fh.write("\n")
        except OSError as exc:
            _undo(tool, seqs_set)
            raise CutoverError("the cut-over record could not be written (%s), so nothing was kept"
                               % exc.__class__.__name__) from None
        try:
            tool.commit()
        except psycopg.Error as exc:
            if isinstance(exc, psycopg.OperationalError) or tool.closed:
                # The connection dropped during the COMMIT: the server may have taken it. The record
                # stays, because without it a copy that did land could never be rolled back.
                print("error: the commit's outcome is unknown (%s): schema bd may hold the copy, so the "
                      "cut-over record %s is kept; run check before anything else" % (
                          exc.__class__.__name__, record.name), file=err)
                return EXIT_COMMIT_UNKNOWN
            record.unlink(missing_ok=True)      # the server refused the commit: nothing was kept
            _undo(tool, seqs_set)
            raise _db_error(exc, "committing schema bd") from None
        print("Forward copy: the old BD database -> schema bd. Every table matches.", file=out)
        _print_proof(before, target, out)
        print("Sequences: every id sequence in schema bd continues past its highest id.", file=out)
        print("Freeze held: the old database did not change during the copy.", file=out)
        print("Cut-over record written: %s" % record.name, file=out)
        if applied is not None:
            print("bd_carry re-applied: %s, %s." % (_plural(len(applied["marks"]), "merge mark"),
                                                     _plural(len(applied["kept"]), "kept pair")), file=out)
            _print_carry_left(applied, out)
        _print_duplicates(listed, out)
        return EXIT_OK
    finally:
        for conn in (tool, old):
            if conn is not None:
                conn.close()


def _print_changed(changed: list, before: dict, after: dict, err: Any) -> None:
    for name in changed:
        if name == CARRY_SCHEMA:
            print("  %s: the merge marks or kept pairs changed" % name, file=err)
            continue
        n0, n1 = before[name][0], after[name][0]
        print("  %s: %s" % (name, "rows %d -> %d" % (n0, n1) if n0 != n1 else "checksum changed"), file=err)


def _print_mismatched(mismatched: list, before: dict, target: dict, where: str, err: Any) -> None:
    for name in mismatched:
        if name == CARRY_SCHEMA:
            print("  %s: %s does not hold the merge marks and kept pairs that were put in" % (name, where),
                  file=err)
            continue
        print("  %s: the source has %d rows, %s; %s has %d rows, %s" % (
            (name,) + before[name] + (where,) + target[name]), file=err)


# ── reverse ─────────────────────────────────────────────────────────────────────────────────────
def reverse(old_url: str, tool_url: str, record_path: Any, *, out: Any = None, err: Any = None,
            after_source_read: Callable[[], None] | None = None) -> int:
    """The reverse copy, a rollback (see the module docstring). Returns the exit code.
    `after_source_read` runs between schema bd's first reading and its second (tests use it to
    break the freeze)."""
    out = out or sys.stdout
    err = err or sys.stderr
    try:
        return _reverse(old_url, tool_url, pathlib.Path(record_path), out, err, after_source_read)
    except CutoverError as exc:
        print("error: %s" % exc, file=err)
        return EXIT_ERROR


def _reverse(old_url: str, tool_url: str, record: pathlib.Path, out: Any, err: Any,
             after_source_read: Callable[[], None] | None) -> int:
    import psycopg

    old = tool = None
    seqs_set: list = []
    try:
        old = _connect(old_url, "old", read_only=False)
        tool = _connect(tool_url, "tool", read_only=True)
        step = "the preflight"
        try:
            problems = _preflight_reverse(old, tool, record)
            if problems:
                old.rollback()
                for line in problems:
                    print(line, file=err)
                return EXIT_REFUSED
            step = "reading schema bd"
            before, data, tool_seqs, carry = _read_source(tool, "tool")
            if after_source_read is not None:
                after_source_read()
            step = "writing the old database"
            _write_rows(old, "old", data)
            step = "saving bd_carry"
            _save_carry(old, carry)
            step = "the proof"
            target = proof(old, "old")
            after = proof(tool, "tool")
            changed = _differences(before, after)
            if tool_carry(tool) != carry:
                changed.append(CARRY_SCHEMA)
            tool.commit()
            mismatched = _differences(before, target)
            if _saved_carry(old) != carry:
                mismatched.append(CARRY_SCHEMA)
            seq_problems: list = []
            if not changed and not mismatched:
                step = "setting the sequences"
                _set_sequences(old, "old", tool_seqs, seqs_set)
                seq_problems = sequence_problems(old, "old")
        except Exception as exc:  # noqa: BLE001  (whatever stopped it, the sequences it set go back)
            _undo(old, seqs_set)
            if isinstance(exc, psycopg.Error):
                raise _db_error(exc, step) from None
            raise
        if changed:
            _undo(old, seqs_set)
            print("freeze broken: schema bd changed during the reverse copy, so nothing was kept in the old "
                  "database.", file=err)
            _print_changed(changed, before, after, err)
            return EXIT_FREEZE
        if mismatched or seq_problems:
            _undo(old, seqs_set)
            print("proof failed, so nothing was kept in the old database:", file=err)
            _print_mismatched(mismatched, before, target, "the old database", err)
            for line in seq_problems:
                print("  " + line, file=err)
            _print_proof(before, target, err)
            return EXIT_MISMATCH
        try:
            old.commit()
        except psycopg.Error as exc:
            _undo(old, seqs_set)
            raise _db_error(exc, "committing the old database") from None
        marks, kept = carry
        print("Reverse copy: schema bd -> the old BD database. Every table matches on the old app's columns.",
              file=out)
        _print_proof(before, target, out)
        print("Sequences: every id sequence in the old database continues past its highest id and past "
              "schema bd's.", file=out)
        print("Freeze held: schema bd did not change during the copy.", file=out)
        print("bd_carry saved in the old database: %s, %s (the old app never reads it; the next forward copy "
              "puts them back)." % (_plural(len(marks), "merge mark"), _plural(len(kept), "kept pair")), file=out)
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
            carry = read_carry(old) if old_schema_ok and not _carry_problems(old) else None
            old.commit()
        except psycopg.Error as exc:
            raise _db_error(exc, "the check") from None
        for line in problems:
            print(line, file=err)
        if source is not None:
            print("The old BD database:", file=out)
            _print_proof(source, None, out)
        if carry is not None:
            print("bd_carry (saved by a reverse copy): %s, %s; the forward copy puts them back." % (
                _plural(len(carry["marks"]), "merge mark"), _plural(len(carry["kept"]), "kept pair")), file=out)
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
    rev = sub.add_parser("reverse", help="a rollback: copy schema bd back into the old database, which must "
                                         "still match the cut-over record, and save bd_carry there")
    rev.add_argument("--record", required=True, metavar="PATH",
                     help="the cut-over record the forward copy wrote")
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
        if args.command == "reverse":
            return reverse(urls[OLD_URL_ENV], urls[TOOL_URL_ENV], args.record)
        return check(urls[OLD_URL_ENV], urls[TOOL_URL_ENV])
    except Exception as exc:  # noqa: BLE001  (its message could quote a row or a URL: the class only)
        print("error: %s; no details are printed because they can hold row data" % exc.__class__.__name__,
              file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
