"""BD_TEST_DATABASE_URL may only name a THROWAWAY Postgres (#805).

The BD fixtures (tests/_bd_db.py) make login roles with passwords that sit in this public repo
(bd_app with the staging-only one, the bd_app-like test login, the staging file's authenticator)
and leave them on the server. On a local container or CI's service that is harmless; on a shared or
Supabase server it would leave logins anyone can use. So the admin URL is taken only when it points
at this machine, and never at a server that looks like Supabase. The refusal never quotes the URL.
"""
from __future__ import annotations

import pytest

import _bd_db

SECRET = "not-a-real-password-0143"


@pytest.mark.parametrize("url", [
    "postgresql://postgres:%s@127.0.0.1:5439/postgres" % SECRET,
    "postgresql://postgres:%s@localhost:5432/postgres" % SECRET,
    "postgresql://postgres:%s@[::1]:5432/postgres" % SECRET,
    "host=/var/run/postgresql dbname=postgres user=postgres password=%s" % SECRET,
    "dbname=postgres user=postgres password=%s" % SECRET,                   # libpq's default socket
])
def test_a_local_server_is_accepted(url):
    assert _bd_db.is_local_server(url)


@pytest.mark.parametrize("url", [
    "postgresql://postgres:%s@db.example.com:5432/postgres" % SECRET,
    "postgresql://postgres.abcd:%s@aws-0-us-east-1.pooler.supabase.com:5432/postgres" % SECRET,
    "postgresql://postgres:%s@10.0.0.5:5432/postgres" % SECRET,
    "postgresql://postgres:%s@db:5432/treadwell" % SECRET,                 # staging's own Postgres
    "host=127.0.0.1,db.example.com dbname=postgres password=%s" % SECRET,  # any remote host counts
    "password=%s dbname" % SECRET,                                         # unparsable
])
def test_any_other_server_is_refused(url):
    assert not _bd_db.is_local_server(url)


def test_admin_url_fails_on_a_remote_server_without_quoting_it(monkeypatch):
    url = "postgresql://postgres:%s@db.example.com:5432/postgres" % SECRET
    monkeypatch.setenv("BD_TEST_DATABASE_URL", url)
    with pytest.raises(pytest.fail.Exception) as err:
        _bd_db.admin_url()
    assert SECRET not in str(err.value) and "example.com" not in str(err.value)


def test_a_database_that_looks_like_supabase_is_refused(bd_admin, monkeypatch):
    """Supabase databases carry an auth schema (and the cluster a supabase_admin role)."""
    with _bd_db.new_database(bd_admin) as url:
        assert _bd_db.looks_like_supabase(url) is False
        with _bd_db.connect(url) as conn:
            conn.execute("create schema auth")
        assert _bd_db.looks_like_supabase(url) is True
        monkeypatch.setenv("BD_TEST_DATABASE_URL", url)
        with pytest.raises(pytest.fail.Exception) as err:
            _bd_db.admin_url()
        assert _bd_db.dbname(url) not in str(err.value)
