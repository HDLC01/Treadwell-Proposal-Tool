"""Anything that emails a customer or the team on a schedule is OFF unless switched on.

The two defaults are not symmetric, which is the whole argument:

  * default ON and be wrong  -> mail goes to real customers and the real estimating team,
    from whatever box happens to be running, and you find out when somebody forwards it
    back to you.
  * default OFF and be wrong -> nothing sends, and somebody notices a missing digest.

Production was previously safe only by coincidence: `DIGEST_ENABLED=off` was set explicitly
in the compose file. A fresh container, a dropped variable, a new environment, or a compose
file edited in a hurry would all have started the 6 AM digest on its own. Nothing in the
suite pinned the default, so flipping it to opt-in broke no test — which is exactly why
this file exists.

Hanz, 2026-08-04: "email follow ups should be automatically off".
"""
import importlib
import os

import pytest

import digest_worker


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("DIGEST_ENABLED", raising=False)
    yield


def test_the_digest_is_off_when_nobody_has_said_otherwise():
    """THE rule. An unset variable must mean silence, not "6 AM mail to the whole team"."""
    assert digest_worker._enabled() is False


@pytest.mark.parametrize("value", ["on", "ON", "1", "true", "TRUE", "yes", " on "])
def test_it_takes_an_explicit_yes_to_turn_on(monkeypatch, value):
    monkeypatch.setenv("DIGEST_ENABLED", value)
    assert digest_worker._enabled() is True


@pytest.mark.parametrize("value", [
    "off", "OFF", "0", "false", "no", "",
    "disabled",      # not a word we accept — must NOT read as "on"
    "maybe",         # nonsense must fail closed
    "of",            # a typo of "off" must not enable it
    "onn",           # a typo of "on" must not enable it either
])
def test_anything_that_is_not_an_explicit_yes_leaves_it_off(monkeypatch, value):
    """Fail closed on junk. The old check was `not in ("off","0","false","no")`, so a typo
    like "of" — or the word "disabled" — silently meant ON."""
    monkeypatch.setenv("DIGEST_ENABLED", value)
    assert digest_worker._enabled() is False


def test_the_worker_will_not_start_when_the_digest_is_off(monkeypatch):
    """The switch has to gate the thread, not just the send — a running worker that decides
    per-tick is one refactor away from mailing."""
    monkeypatch.delenv("DIGEST_ENABLED", raising=False)
    monkeypatch.setitem(__import__("sys").modules, "pytest", None)
    try:
        started = digest_worker.ensure_started(portal=lambda *a, **k: {},
                                               run_claude=lambda *a, **k: "")
    finally:
        __import__("sys").modules["pytest"] = pytest
    assert started is False


def test_the_docstring_still_tells_the_truth_about_the_default():
    """A stale comment here would send the next person looking for a bug that isn't there —
    or worse, reassure them that it defaults off when somebody has flipped it back."""
    doc = digest_worker.__doc__ or ""
    assert "default OFF" in doc, "the module docstring no longer documents the OFF default"


def test_prod_and_staging_compose_do_not_quietly_rely_on_the_default(tmp_path):
    """Belt and braces: the compose files should still say `off` explicitly. It is now
    redundant, and that is the point — it documents intent at the place an operator looks,
    and it keeps working if the code default is ever changed back."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    for name in ("docker-compose.yml", "docker-compose.staging.yml"):
        text = (root / name).read_text(encoding="utf-8")
        if "DIGEST_ENABLED" in text:
            assert "DIGEST_ENABLED=off" in text or "DIGEST_ENABLED: \"off\"" in text \
                or "DIGEST_ENABLED: off" in text, f"{name} sets DIGEST_ENABLED to something else"
