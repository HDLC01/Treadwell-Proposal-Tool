"""The BD fixture seed (backend/bd/ops/fixture_seed.py) and its command (python -m bd.ops.seed).

The seed is small and made up, for the tests and for staging (#805, Q27):
  * example.com emails (per-account subdomains of example.com, so a shared email domain is a
    hint the duplicate check can see) and 555-01xx phones, nothing else;
  * two likely-duplicate account pairs (cleaned names equal) and one near miss (names differ;
    a shared phone and email domain are only a hint, and a hint alone never makes a pair);
  * an account with several owners and an account with only maintenance contacts;
  * at least one row in every table the serializers read.
The command loads it into an EMPTY bd schema of a staging or test database, as bd_app. Hanz's and
Troy's emails and their BD roles are given on the command line and are never committed.
"""
from __future__ import annotations

import collections
import datetime as dt
import re

import pytest

from bd.normalize import normalize_company
from bd.phone import to_e164
from bd.ops import fixture_seed
from bd.ops import seed as seed_cmd

import _bd_db

F = fixture_seed.FIXTURE
PHONE_RE = re.compile(r"^\D*(?:1\D*)?\d{3}\D*555\D*01\d{2}\D*$")
EMAIL_RE = re.compile(r"^[a-z0-9._-]+@(?:[a-z0-9-]+\.)*example\.com$", re.I)
E164_RE = re.compile(r"^\+1\d{3}55501\d{2}$")


def _emails():
    for table, key in (("users", "email"), ("contacts", "email"), ("candidates", "email"),
                       ("followup_drafts", "to_address")):
        for row in F[table]:
            v = row.get(key)
            if v and "@" in v:
                yield table, v


def _phones():
    for table, key in (("contacts", "phone"), ("candidates", "phone")):
        for row in F[table]:
            if row.get(key):
                yield table, row[key]


# ── the data itself (no database) ──────────────────────────────────────────────────────────────
def test_every_email_is_an_example_com_address():
    seen = list(_emails())
    assert len(seen) >= 10
    for table, email in seen:
        assert EMAIL_RE.match(email), (table, email)


def test_every_phone_is_a_555_01xx_number():
    seen = list(_phones())
    assert len(seen) >= 8
    for table, phone in seen:
        assert PHONE_RE.match(phone), (table, phone)
    for row in F["unmatched_calls"]:
        assert E164_RE.match(row["from_e164"]), row
    for row in F["followup_drafts"]:
        if row["channel"] == "sms":
            assert E164_RE.match(row["to_address"]), row


def test_no_real_address_is_in_the_seed_source():
    """Hanz's and Troy's emails come in on the command line on staging, never from the repo."""
    text = fixture_seed.__file__ and open(fixture_seed.__file__, encoding="utf-8").read()
    text += open(seed_cmd.__file__, encoding="utf-8").read()
    assert "wetreadwell" not in text.lower()
    assert not re.search(r"@(?!(?:[a-z0-9-]+\.)*example\.com)[a-z0-9-]+\.[a-z]", text.lower())


def test_two_likely_duplicate_account_pairs_and_one_near_miss():
    names = {c["id"]: c["name"] for c in F["companies"]}
    assert len(fixture_seed.LIKELY_DUPLICATE_PAIRS) == 2
    for a, b in fixture_seed.LIKELY_DUPLICATE_PAIRS:
        assert names[a] != names[b]
        assert normalize_company(names[a]) == normalize_company(names[b]), (names[a], names[b])
    a, b = fixture_seed.NEAR_MISS
    assert normalize_company(names[a]) != normalize_company(names[b])
    # ... but it carries both hints, so it is a near miss and not just two other accounts
    def contacts_of(cid):
        return [c for c in F["contacts"] if c["company_id"] == cid]
    domains = lambda cid: {c["email"].split("@", 1)[1] for c in contacts_of(cid) if c.get("email")}
    digits = lambda cid: {re.sub(r"\D", "", c["phone"])[-10:] for c in contacts_of(cid) if c.get("phone")}
    assert domains(a) & domains(b)
    assert digits(a) & digits(b)
    # no other two accounts clean to the same name
    keys = collections.Counter(normalize_company(n) for n in names.values())
    assert sorted(n for n, k in keys.items() if k > 1) == sorted(
        normalize_company(names[a]) for a, _ in fixture_seed.LIKELY_DUPLICATE_PAIRS)


def test_one_account_has_several_owners_and_one_has_only_maintenance_contacts():
    owners = {c["owner_id"] for c in F["contacts"] if c["company_id"] == fixture_seed.MULTI_OWNER_ACCOUNT}
    assert len(owners - {None}) >= 2
    cats = [c["category"] for c in F["contacts"] if c["company_id"] == fixture_seed.MAINTENANCE_ONLY_ACCOUNT]
    assert len(cats) >= 2 and set(cats) == {"maintenance"}
    # the other accounts are not maintenance-only, so the case stands out
    for co in F["companies"]:
        if co["id"] != fixture_seed.MAINTENANCE_ONLY_ACCOUNT:
            assert any(c.get("category", "bd") == "bd" for c in F["contacts"] if c["company_id"] == co["id"])


def test_every_bd_role_is_held_by_a_made_up_person():
    assert {u["role"] for u in F["users"]} == set(seed_cmd.ROLES)


def test_the_ids_are_unique_and_every_reference_points_at_a_row():
    ids = {t: {r["id"] for r in rows} for t, rows in F.items() if rows and "id" in rows[0]}
    for t, rows in F.items():
        if rows and "id" in rows[0]:
            assert len(ids[t]) == len(rows), t
    refs = {"company_id": "companies", "owner_id": "users", "co_owner_id": "users", "user_id": "users",
            "duplicate_of": "contacts", "contact_id": "contacts", "batch_id": "task_batches",
            "interaction_id": "interactions", "decided_by": "users", "possible_duplicate_id": "contacts",
            "by_id": "users"}
    for t, rows in F.items():
        for row in rows:
            for col, target in refs.items():
                if row.get(col) is not None:
                    assert row[col] in ids[target], (t, row["id"], col)


# ── the seed in a database ─────────────────────────────────────────────────────────────────────
def test_the_seed_loads_every_row_and_the_counts_match(bd_seeded, bd_db):
    for table, rows in F.items():
        n = bd_db.execute("select count(*) as n from " + table).fetchone()["n"]
        assert n == len(rows), table
    assert bd_seeded["counts"] == {t: len(rows) for t, rows in F.items()}


def test_the_database_fills_the_generated_columns_and_the_default_frequency(bd_seeded, bd_db):
    rows = bd_db.execute("select id, phone_e164, email_lower, category, frequency_per_year"
                         " from contacts order by id").fetchall()
    assert len(rows) == len(F["contacts"])
    defaulted = 0
    for r in rows:
        src = next(c for c in F["contacts"] if c["id"] == r["id"])
        assert r["phone_e164"] == to_e164(src.get("phone")), r
        assert r["email_lower"] == ((src.get("email") or "").strip().lower() or None), r
        if src.get("frequency_per_year") is None:
            defaulted += 1
            assert r["frequency_per_year"] == {"bd": 4, "maintenance": 3}[r["category"]], r
        else:
            assert r["frequency_per_year"] == src["frequency_per_year"], r
    assert 0 < defaulted < len(rows)       # the trigger fired, and an explicit value was kept


def test_the_view_shows_the_pairs_the_near_miss_and_the_accounts(bd_seeded, bd_db):
    keys = {r["id"]: r["normalized_name"] for r in bd_db.execute("select id, normalized_name from companies")}
    for a, b in fixture_seed.LIKELY_DUPLICATE_PAIRS:
        assert keys[a] == keys[b]
    a, b = fixture_seed.NEAR_MISS
    assert keys[a] != keys[b]
    owners = bd_db.execute("select count(distinct owner_id) as n from contacts_summary where company_id = %s",
                           (fixture_seed.MULTI_OWNER_ACCOUNT,)).fetchone()["n"]
    assert owners >= 2
    cats = {r["category"] for r in bd_db.execute(
        "select category from contacts_summary where company_id = %s", (fixture_seed.MAINTENANCE_ONLY_ACCOUNT,))}
    assert cats == {"maintenance"}


def test_new_rows_get_ids_after_the_seeds(bd_seeded, bd_db):
    top = bd_db.execute("select max(id) as m from companies").fetchone()["m"]
    new = bd_db.execute("insert into companies (name, normalized_name) values ('Fresh Account', 'fresh account')"
                        " returning id").fetchone()["id"]
    assert new > top
    for table in fixture_seed.IDENTITY_TABLES:
        if not F.get(table):
            continue                     # an empty table's sequence was never called: it starts at 1
        top = bd_db.execute("select coalesce(max(id), 0) as m from " + table).fetchone()["m"]
        nxt = bd_db.execute("select last_value from pg_sequences where schemaname = 'bd'"
                            " and sequencename = %s", (table + "_id_seq",)).fetchone()
        assert nxt["last_value"] >= top, table


def test_on_the_fixture_day_the_cadence_reads_as_planned(bd_seeded, bd_db):
    assert bd_seeded["today"] == dt.date(2026, 11, 4)
    rows = {r["id"]: r for r in bd_db.execute("select id, cadence_status, last_live_at from contacts_summary")}
    statuses = {r["cadence_status"] for r in rows.values()}
    assert {"never", "on_track", "behind"} <= statuses


# ── the command ────────────────────────────────────────────────────────────────────────────────
def test_the_people_argument_is_email_equals_role():
    people = seed_cmd.parse_people(["Lead.One@Example.org=super_admin", "second.person@example.net=manager"])
    assert people == [("lead.one@example.org", "Lead One", "super_admin"),
                      ("second.person@example.net", "Second Person", "manager")]
    for bad in (["no-at-sign=admin"], ["a@example.org=owner"], ["a@example.org"],
                ["a@example.org=admin", "A@example.org=manager"]):
        with pytest.raises(ValueError):
            seed_cmd.parse_people(bad)


@pytest.mark.parametrize("url, ok", [
    ("postgresql://bd_app:pw@db:5432/treadwell", True),             # the staging compose's database
    ("postgresql://bd_app:pw@127.0.0.1:5432/bd_test_gw1_0abc", True),   # a test database
    ("postgresql://bd_app:pw@db:5432/postgres", False),
    ("postgresql://bd_app:pw@aws-0-us-east-1.pooler.supabase.com:5432/postgres", False),
    ("postgresql://bd_app:pw@127.0.0.1:5432/treadwell", False),
    ("", False),
])
def test_only_a_staging_or_test_database_is_accepted(url, ok):
    assert seed_cmd.allowed_database(url) is ok


def test_the_command_refuses_any_other_database_before_connecting(capsys):
    url = "postgresql://bd_app:not-a-real-password-0177@aws-0-us-east-1.pooler.supabase.com:1/postgres"
    assert seed_cmd.main(["--url", url]) == 2
    out = capsys.readouterr()
    assert "refusing" in out.err
    assert "not-a-real-password-0177" not in out.out + out.err and url not in out.out + out.err


def test_the_command_refuses_with_no_url(capsys, monkeypatch):
    from bd import config

    monkeypatch.setattr(config, "BD_DATABASE_URL", "")
    assert seed_cmd.main([]) == 2


def test_the_command_refuses_bad_people_before_connecting(capsys):
    assert seed_cmd.main(["--url", "postgresql://u:p@127.0.0.1:1/bd_test_x", "--person", "x=admin"]) == 2


@pytest.fixture
def empty_bd(bd_migrated_url):
    """A freshly migrated database with an empty bd schema, as the bd_app-like login."""
    from psycopg.rows import dict_row

    conn = _bd_db.connect(bd_migrated_url, row_factory=dict_row)
    conn.execute("set search_path = bd, pg_catalog")
    fixture_seed.reset_data(conn)
    conn.close()
    return _bd_db.app_login_url(bd_migrated_url)


def test_the_command_loads_the_seed_and_the_people_into_an_empty_schema(empty_bd, capsys):
    code = seed_cmd.main(["--url", empty_bd, "--person", "lead.one@example.org=super_admin",
                          "--person", "second.person@example.org=manager"])
    out = capsys.readouterr()
    assert code == 0, out.err
    assert empty_bd not in out.out + out.err and _bd_db.APP_TEST_PASSWORD not in out.out + out.err
    with _bd_db.connect(empty_bd) as conn:
        conn.execute("set search_path = bd, pg_catalog")
        users = conn.execute("select email, name, role, active from users order by id").fetchall()
        n = conn.execute("select count(*) from contacts").fetchone()[0]
    assert n == len(F["contacts"])
    assert users[-2:] == [("lead.one@example.org", "Lead One", "super_admin", True),
                          ("second.person@example.org", "Second Person", "manager", True)]
    assert len(users) == len(F["users"]) + 2

    # ... and a second run finds rows and changes nothing
    assert seed_cmd.main(["--url", empty_bd]) == 1
    assert "not empty" in capsys.readouterr().err
    with _bd_db.connect(empty_bd) as conn:
        conn.execute("set search_path = bd, pg_catalog")
        assert conn.execute("select count(*) from users").fetchone()[0] == len(F["users"]) + 2


def test_the_command_refuses_a_schema_with_even_one_row(empty_bd, capsys):
    with _bd_db.connect(empty_bd) as conn:
        conn.execute("set search_path = bd, pg_catalog")
        conn.execute("insert into settings (key, value) values ('bd_cadence', '\"monthly\"')")
    assert seed_cmd.main(["--url", empty_bd]) == 1
    assert "settings" in capsys.readouterr().err
    with _bd_db.connect(empty_bd) as conn:
        conn.execute("set search_path = bd, pg_catalog")
        assert conn.execute("select count(*) from users").fetchone()[0] == 0


def test_the_command_refuses_a_schema_that_is_not_migrated(bd_admin, capsys):
    with _bd_db.new_database(bd_admin) as url:
        assert seed_cmd.main(["--url", url]) == 1
        assert "migrat" in capsys.readouterr().err
