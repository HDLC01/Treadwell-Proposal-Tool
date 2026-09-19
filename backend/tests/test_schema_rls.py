"""Every table this repo creates on PROD is locked down, and the lock is stated in the file.

THIS TEST EXISTS BECAUSE `library_labor` SHIPPED WITHOUT IT. The table was added on 2026-09-17
into the middle of `supabase_schema.sql` and left out of the RLS/grant block ~130 lines below,
which already covered `library_items`, `library_assemblies`, `library_vendors`,
`library_divisions`, `library_units` and `markup_rules`. Nothing caught it, and nothing could
have, for a reason worth writing down:

  * On STAGING the store is self-hosted Postgres and the app connects as the OWNER. RLS is off on
    every table there and a grant is moot, so the omission is invisible — the feature works, the
    tests pass, the page renders.
  * On PROD the store is Supabase. Every other table in this schema has RLS on, and a table
    WITHOUT it is reachable through the PostgREST API by `anon` and `authenticated` — i.e. by any
    browser holding the publishable key. `library_labor` carries Treadwell's labor rates.

It was caught before `library_labor` existed on production at all, so nothing was ever exposed.
The class of mistake is what this guards: the block is far from the tables it covers, so the next
table added in the middle of the file is exactly as easy to miss.

THE PORTAL REPO HAS THIS TEST ALREADY (`test_every_rls_table_also_has_a_grant_and_a_policy`) and
it is what caught the same mistake there, twice — `portal_settings` and `portal_proposal_views`
both shipped RLS-on-and-unreachable. This repo had no equivalent, which is why it slipped here.

THIS FILE ONLY, NOT `backend/staging/schema_pg.sql`, and that is deliberate rather than an
oversight for somebody to "fix" later. Staging is self-hosted Postgres and the app connects to it
as the OWNER: it declares no RLS at all, so half of this guard has nothing to check there, and its
grants are covered by the `grant all on all tables in schema public to service_role` it runs after
its tables. Pointing this test at that file would fail on every table in it and say nothing true.

GREPPED, NOT EXECUTED, AND THAT IS THE RIGHT LEVEL. The artefact under test IS text — a .sql file
a human pastes into the Supabase SQL editor. There is no function to run and no database in this
suite to run it against; what can go wrong is a line that is not in the file, and that is a thing
a reader of the file can see. Compare `test_library_labor.py`, which executes the real
`library.py` against the in-memory store: that is where behaviour is checked.
"""
import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parents[1]
SCHEMA = BACKEND / "supabase_schema.sql"

# The three that predate the per-table grants and DO NOT CARRY ONE IN THIS FILE.
#
# They are exempt from the grant half only — each still has to have RLS on, and each is asserted
# below to actually exist, so a stale name here cannot quietly excuse a table that was renamed.
#
# Why they work on prod without a line here: they were created in the very first run of this
# schema, when Supabase's own `alter default privileges … grant all on tables to service_role`
# still applied to what the migration was making. The later tables were added after that window
# and needed the grant said out loud — which is the measured lesson the `condition_defaults`
# block at the foot of the file records in one sentence ("a blanket grant only covers the tables
# that exist when it runs").
#
# They are LISTED rather than back-filled for the reason the portal's copy of this test gives:
# editing the DDL of a live table to re-state a grant it demonstrably already has buys nothing
# and risks a typo on the three tables the whole tool runs on.
GRANTED_BEFORE_THIS_FILE_SAID_SO = {"drafts", "events", "profiles"}

_CREATE = re.compile(r"create table if not exists\s+public\.(\w+)", re.I)
_RLS = re.compile(r"alter table\s+public\.(\w+)\s+enable row level security", re.I)
_GRANT = re.compile(r"grant [^;]*\bon\s+public\.(\w+)\s+to\s+service_role", re.I)


def _schema() -> str:
    return SCHEMA.read_text(encoding="utf-8")


def test_every_table_this_schema_creates_has_rls_enabled():
    """A table without RLS on Supabase is served to `anon` over the REST API.

    NOT VACUOUS: the sets are asserted non-empty first, so a regex that stopped matching (someone
    reformats the block, or moves to `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` on one line with
    different spacing) fails here rather than passing by matching nothing.

    Mutation: delete `alter table public.library_labor enable row level security;` and this names
    library_labor. That is the exact line that was missing until 2026-09-19."""
    schema = _schema()
    tables = set(_CREATE.findall(schema))
    rls = set(_RLS.findall(schema))
    assert len(tables) >= 10, (
        "only %d tables found — the create-table regex has stopped matching and this guard is "
        "checking nothing" % len(tables))
    assert rls, "no `enable row level security` found at all — this guard is checking nothing"
    missing = sorted(tables - rls)
    assert missing == [], (
        "these tables are created with NO row level security: %s. On production (Supabase) that "
        "means anon and authenticated can read and write them straight through the PostgREST "
        "API. Add `alter table public.<name> enable row level security;` to the block beside the "
        "other library tables." % ", ".join(missing))


def test_every_table_this_schema_creates_is_granted_to_the_service_role():
    """The other half, and the half that is silent rather than dangerous when it is missing.

    RLS on with no grant is how a table reads as "locked down" and is simply unreachable by the
    app as well. Here the backend holds the service-role key, which bypasses RLS but still needs
    the privilege — and the note at the foot of the schema records the measurement: a blanket
    grant only covers the tables that existed when it ran.

    Mutation: delete `grant … on public.library_labor to service_role;` and this names
    library_labor."""
    schema = _schema()
    tables = set(_CREATE.findall(schema))
    granted = set(_GRANT.findall(schema))
    assert granted, "no `grant … to service_role` found at all — this guard is checking nothing"
    # A stale exemption must not silently excuse a table. If one of the three is ever renamed or
    # dropped, this fails rather than widening the hole by the width of the old name.
    unknown = sorted(GRANTED_BEFORE_THIS_FILE_SAID_SO - tables)
    assert unknown == [], (
        "GRANTED_BEFORE_THIS_FILE_SAID_SO names tables this schema no longer creates: %s — the "
        "exemption is stale and is now excusing nothing it was written for" % ", ".join(unknown))
    assert tables - GRANTED_BEFORE_THIS_FILE_SAID_SO, "the exemption covers every table checked"
    missing = sorted((tables - GRANTED_BEFORE_THIS_FILE_SAID_SO) - granted)
    assert missing == [], (
        "these tables have no `grant … to service_role`: %s. The backend holds the service-role "
        "key; without the grant every read answers empty and every write fails, on prod only."
        % ", ".join(missing))


def test_the_guard_can_actually_see_a_table_that_is_missing_a_line():
    """THE MUTATION, RUN IN-PROCESS, because the two tests above are the kind that pass by
    matching nothing. This adds a table to a COPY of the schema text and declares neither line
    for it; both checks must name it.

    Without this, a typo in `_CREATE` would make both tests above vacuously green forever — which
    is precisely how the original omission survived: the thing that would have seen it did not
    exist, and its absence looked identical to a pass."""
    doctored = _schema() + (
        "\r\ncreate table if not exists public.library_smuggled (\r\n  id text primary key\r\n);\r\n")
    tables = set(_CREATE.findall(doctored))
    assert "library_smuggled" in tables, "the create-table regex did not see a plain new table"
    assert "library_smuggled" not in set(_RLS.findall(doctored))
    assert "library_smuggled" not in set(_GRANT.findall(doctored))
    # And the exemption list cannot be what rescues it.
    assert "library_smuggled" not in GRANTED_BEFORE_THIS_FILE_SAID_SO


def test_library_labor_specifically_carries_both_lines():
    """NAMED, not just covered by the loop, because this is the table that shipped without them
    and the one whose rows are Treadwell's labor rates.

    The generic tests above would go green again if somebody deleted the `create table` for
    library_labor as well as its two lines. This one would not."""
    schema = _schema()
    assert "create table if not exists public.library_labor" in schema
    assert "alter table public.library_labor enable row level security;" in schema, (
        "library_labor has no RLS on prod — anon can read every labor rate over the REST API")
    assert "grant select, insert, update, delete on public.library_labor to service_role;" in schema, (
        "library_labor is not granted to service_role, so every library labor write 500s on prod")
