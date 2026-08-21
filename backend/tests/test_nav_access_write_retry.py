"""The policy write survives a transient rename refusal, and still fails when it should.

WHY THIS EXISTS. `nav_access.save()` writes a temp file and `os.replace()`s it over the real one.
That rename is atomic, but on Windows it raises PermissionError (WinError 5) whenever anything else
holds a handle on either path for the instant of the rename - an antivirus scanning the file we just
wrote being the usual culprit. Reproduced on the dev box under deliberate CPU load: four threads
doing twenty replaces each, and roughly one run in eight surfaced as
NavAccessWriteError("[WinError 5] Access is denied"). It made the suite fail about half the time
under `-n auto` while passing solo every time, and a red run on an unrelated branch reads as that
branch's fault.

Production runs on Linux, which has no such failure mode, so this is a dev-experience fix more than
a production one. It is still the right behaviour: a save that failed for a reason that has nothing
to do with the save is worth retrying.

THE LOAD TEST IS NOT ENOUGH ON ITS OWN. "0 failures in 14 runs under load" is evidence, not proof -
the bug is probabilistic and the absence of it is unfalsifiable that way. So the retry is also
tested directly and deterministically here, by making the rename fail on demand.

The unique temp name is tested too. The shared ".tmp" was safe against threads (the lock covers
them) and not against a second PROCESS writing the same path, which is a different bug in the same
two lines and has no test of its own otherwise.
"""

import json
import os
import pathlib
import threading

import pytest

import nav_access


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(nav_access, "_FILE", tmp_path / "nav_access.json")
    monkeypatch.setattr(nav_access, "_DATA_DIR", tmp_path)


def _a_policy():
    return {"user": [list(nav_access.TABS)[1]]}


def test_a_transient_rename_refusal_is_retried_and_the_policy_lands(monkeypatch):
    """Two refusals then success: save() must return normally and the file must be correct."""
    real = pathlib.Path.replace
    calls = {"n": 0}

    def flaky(self, target):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError(5, "Access is denied")
        return real(self, target)

    monkeypatch.setattr(pathlib.Path, "replace", flaky)
    out = nav_access.save(_a_policy(), "someone@wetreadwell.com")

    assert calls["n"] == 3, "expected two refusals and one success, got %d attempts" % calls["n"]
    assert out["deny"] == _a_policy()
    # and it is really on disk, not just returned
    assert json.loads(nav_access._FILE.read_text(encoding="utf-8"))["deny"] == _a_policy()


def test_a_rename_that_never_succeeds_still_raises(monkeypatch):
    """The retry must not turn a real, permanent failure into a silent success.

    This is the half that matters more: a save that quietly does nothing would let an admin believe
    they had locked a tab down.
    """
    calls = {"n": 0}

    def always(self, target):
        calls["n"] += 1
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(pathlib.Path, "replace", always)
    with pytest.raises(nav_access.NavAccessWriteError):
        nav_access.save(_a_policy(), "someone@wetreadwell.com")
    assert calls["n"] == 3, "expected exactly three attempts, got %d" % calls["n"]


def test_a_failure_that_is_not_a_permission_error_is_not_retried(monkeypatch):
    """Only the transient class is retried. Retrying a genuine error three times just delays it."""
    calls = {"n": 0}

    def boom(self, target):
        calls["n"] += 1
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(pathlib.Path, "replace", boom)
    with pytest.raises(nav_access.NavAccessWriteError):
        nav_access.save(_a_policy(), "someone@wetreadwell.com")
    assert calls["n"] == 1, "a disk-full error was retried %d times; it should fail at once" % calls["n"]

def test_the_temp_name_separates_two_processes():
    """The temp path must differ between PROCESSES, which is the collision the lock cannot prevent.

    TWO EARLIER VERSIONS OF THIS TEST WERE WRONG, and both wrongnesses are worth recording because
    each one passed.

    The first counted distinct temp names across six threads run to completion and demanded six.
    Linux RECYCLES thread ids, so six sequential threads produced three names and CI went red on a
    property the design never promised. It had passed on Windows, where the ids happened not to be
    reused in that window.

    The second tried to make the six writers genuinely simultaneous with a barrier inside the
    rename. That CANNOT work: `save()` holds `_LOCK` across the whole write-and-rename, so two
    writers in one process are never both inside it. The barrier deadlocked, timed out after ten
    seconds, broke, and every `BrokenBarrierError` was swallowed by save()'s own `except Exception`
    and then lost inside its thread. The assertions still passed, on names collected by writers that
    never renamed anything. The only visible symptom was the test taking eleven seconds.

    So: same-process concurrency is not the risk, because the lock already excludes it. The risk is
    a SECOND PROCESS - a worker, a second uvicorn, a test runner - writing the same fixed path and
    truncating our half-written file before either rename. That is what the pid in the name buys,
    and it is what this asserts, by writing as two different pids rather than by pretending to be
    concurrent.
    """
    seen = []
    real = pathlib.Path.replace

    def note(self, target):
        seen.append(self.name)
        return real(self, target)

    import unittest.mock as mock
    with mock.patch.object(pathlib.Path, "replace", note):
        with mock.patch("os.getpid", lambda: 1111):
            nav_access.save(_a_policy(), "one@x.com")
        with mock.patch("os.getpid", lambda: 2222):
            nav_access.save(_a_policy(), "two@x.com")

    assert len(seen) == 2, seen
    for n in seen:
        assert n.startswith("nav_access.tmp."), n
    assert "1111" in seen[0] and "2222" in seen[1], (
        "the temp name does not carry the pid, so two processes would collide on it: %r" % (seen,))
    assert seen[0] != seen[1], seen
    # and the thread id is in there too, so removing the lock later would not reintroduce the bug
    assert str(threading.get_ident()) in seen[0], seen[0]
