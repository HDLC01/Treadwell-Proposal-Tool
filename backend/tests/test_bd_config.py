"""bd/config.py: every BD setting carries the BD_ prefix and the default #805 states.

The BD CRM now runs inside the proposal tool's process, so a BD setting must never be confused with
one of the tool's: every name BD reads starts with BD_, BD never reads the tool's own
SUPER_ADMIN_EMAIL (or any other unprefixed name; the one read-only exception is the tool's sign-in
domain, read by bd/auth.py alone), and nothing in the BD package loads a .env file
(python-dotenv is not a BD dependency). backend/.env.example lists exactly the BD_ settings the
code reads.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from bd import config

BACKEND = pathlib.Path(__file__).resolve().parents[1]
BD = BACKEND / "bd"
EXAMPLE = BACKEND / ".env.example"

# The settings table of #805, with the default each one has when it is unset. A setting the code
# reads must be here, and every one here must be read.
DEFAULTS = {
    "BD_ENABLED": False,                 # the switch (#806): off, every /api/bd/ route answers 503
    "BD_DATABASE_URL": "",               # unset: BD answers 503
    "BD_DB_POOL_MIN": 1,
    "BD_DB_POOL_MAX": 5,
    "BD_WEEKLY_ENABLED": False,          # the Friday batch: off unless switched on
    "BD_WEEKLY_HOUR": 16,
    "BD_SUPER_ADMIN_EMAIL": "",
    "BD_ADMIN_EMAILS": frozenset(),
    "BD_TELEPHONY_PROVIDER": "",
    "BD_QUO_API_KEY": "",
    "BD_QUO_WEBHOOK_SECRET": "",
    "BD_TEST_DATABASE_URL": "",          # tests only; CI sets it
}
# Read on every call (bizdate's business clock), never held as an attribute.
LIVE = {"BD_TODAY": config.bd_today_override, "BD_NOW": config.bd_now_override}

# How a module reads a variable: config's own helpers, or os.environ / os.getenv directly.
_READS = re.compile(r"""(?:_str|_bool|_int|_emails|environ\.get|getenv|environ\[)\(?\s*["']([A-Za-z_][A-Za-z0-9_]*)["']""")


def _bd_sources():
    return sorted(p for p in BD.rglob("*.py") if "__pycache__" not in p.parts)


def names_the_bd_package_reads():
    names = set()
    for path in _bd_sources():
        names |= set(_READS.findall(path.read_text(encoding="utf-8")))
    return names


def example_bd_keys():
    text = EXAMPLE.read_text(encoding="utf-8")
    return [m.group(1) for m in re.finditer(r"^(BD_[A-Z0-9_]*)=", text, re.M)]


@pytest.fixture
def fresh_env(monkeypatch):
    """No BD setting in the environment (and the tool's SUPER_ADMIN_EMAIL set, to prove it is
    ignored); config re-read, and re-read again from the real environment afterwards."""
    for name in [*DEFAULTS, *LIVE]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SUPER_ADMIN_EMAIL", "tool.owner@example.com")
    monkeypatch.setenv("ADMIN_EMAILS", "tool.admin@example.com")
    monkeypatch.setenv("WEEKLY_ENABLED", "true")
    config.reload()
    yield monkeypatch
    monkeypatch.undo()
    config.reload()


def test_the_package_reads_something():
    """The scan below is only worth something if it finds the reads."""
    assert {"BD_DATABASE_URL", "BD_TODAY"} <= names_the_bd_package_reads()


def test_every_setting_the_bd_package_reads_has_the_bd_prefix():
    unprefixed = sorted(n for n in names_the_bd_package_reads() if not n.startswith("BD_"))
    assert not unprefixed, "the BD package reads %s; every BD setting starts with BD_" % unprefixed


def test_every_setting_read_is_in_the_table_and_every_one_in_the_table_is_read():
    read = names_the_bd_package_reads()
    assert read == set(DEFAULTS) | set(LIVE)


@pytest.mark.parametrize("name", sorted(DEFAULTS))
def test_each_setting_has_its_stated_default_when_unset(fresh_env, name):
    value = getattr(config, name)
    assert value == DEFAULTS[name] and type(value) is type(DEFAULTS[name]), (name, value)


def test_the_switch_is_off_unless_set_on(fresh_env):
    assert config.BD_ENABLED is False
    for value, want in (("on", True), ("true", True), ("1", True), ("off", False), ("", False), ("nope", False)):
        fresh_env.setenv("BD_ENABLED", value)
        config.reload()
        assert config.BD_ENABLED is want, value


def test_the_weekly_batch_is_off_when_unset_even_if_the_old_unprefixed_name_is_on(fresh_env):
    assert config.BD_WEEKLY_ENABLED is False
    fresh_env.setenv("BD_WEEKLY_ENABLED", "on")
    config.reload()
    assert config.BD_WEEKLY_ENABLED is True
    fresh_env.setenv("BD_WEEKLY_ENABLED", "off")
    config.reload()
    assert config.BD_WEEKLY_ENABLED is False


def test_bd_never_reads_the_tools_super_admin_or_admin_emails(fresh_env):
    assert config.BD_SUPER_ADMIN_EMAIL == "" and config.BD_ADMIN_EMAILS == frozenset()
    for path in _bd_sources():
        src = path.read_text(encoding="utf-8")
        assert not re.search(r"""["'](SUPER_ADMIN_EMAIL|ADMIN_EMAILS)["']""", src), path


# The one read-only exception to "BD never reads a tool setting": the email domain the tool's sign-in
# lets in, which BD's People table checks a new login against. bd/auth.py, the seam to the tool's
# gate, is the only BD module that may import the tool's supabase_client.
_TOOL_AUTH_IMPORT = re.compile(r"""^\s*(import\s+supabase_client\b|from\s+supabase_client\s+import\b)|import_module\(\s*["']supabase_client""", re.M)


def test_only_bd_auth_imports_the_tools_sign_in_module():
    importers = sorted(p.relative_to(BD).as_posix() for p in _bd_sources()
                       if _TOOL_AUTH_IMPORT.search(p.read_text(encoding="utf-8")))
    assert importers == ["auth.py"], importers


def test_no_bd_module_loads_a_dotenv_file():
    for path in _bd_sources():
        assert not re.search(r"^\s*(from|import)\s+dotenv\b|load_dotenv\(", path.read_text(encoding="utf-8"), re.M), path


def test_types_and_parsing(fresh_env):
    fresh_env.setenv("BD_ADMIN_EMAILS", " Pat.Lee@Example.COM , sam.ortiz@example.com,, ")
    fresh_env.setenv("BD_SUPER_ADMIN_EMAIL", " Owner@Example.com ")
    fresh_env.setenv("BD_WEEKLY_HOUR", "25")
    fresh_env.setenv("BD_DB_POOL_MIN", "x")
    fresh_env.setenv("BD_DB_POOL_MAX", "0")
    fresh_env.setenv("BD_TELEPHONY_PROVIDER", " Quo ")
    config.reload()
    assert config.BD_ADMIN_EMAILS == frozenset({"pat.lee@example.com", "sam.ortiz@example.com"})
    assert config.BD_SUPER_ADMIN_EMAIL == "owner@example.com"
    assert config.BD_WEEKLY_HOUR == 16              # out of range -> the default
    assert config.BD_DB_POOL_MIN == 1               # not a number -> the default
    assert config.BD_DB_POOL_MAX == 5               # below its floor of 1 -> the default
    assert config.BD_TELEPHONY_PROVIDER == "quo"


def test_the_clock_overrides_are_read_live(monkeypatch):
    monkeypatch.setenv("BD_TODAY", " 2026-11-04 ")
    assert config.bd_today_override() == "2026-11-04"
    monkeypatch.delenv("BD_TODAY")
    assert config.bd_today_override() == ""
    monkeypatch.setenv("BD_NOW", "2026-11-04T09:30:00-06:00")
    assert config.bd_now_override() == "2026-11-04T09:30:00-06:00"
    monkeypatch.delenv("BD_NOW")
    assert config.bd_now_override() == ""


def test_the_env_example_lists_exactly_the_bd_settings_with_no_values():
    keys = example_bd_keys()
    assert len(keys) == len(set(keys)), "a BD setting is listed twice in backend/.env.example"
    assert set(keys) == set(DEFAULTS) | set(LIVE)
    text = EXAMPLE.read_text(encoding="utf-8")
    filled = re.findall(r"^(BD_[A-Z0-9_]*)=(\S+)", text, re.M)
    assert not filled, "backend/.env.example gives a BD setting a value: %s" % filled
