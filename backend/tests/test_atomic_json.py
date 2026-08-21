"""The one JSON writer, and a guard against a sixth hand-rolled copy of it.

FIVE MODULES had the same three lines - a fixed ".tmp" beside the target, then a bare
`os.replace` - and the same two bugs in them: a temp name that only a same-process lock protects,
and a rename with no retry past a transient Windows PermissionError. The retry was written into
nav_access.py first, and then pull_window.py failed the SAME way on the next merge, in a test that
even has the same name. That is what moved the code into atomic_json rather than copying it a
fourth and fifth time.

The last test here is the one that matters most in a year: it fails if somebody hand-rolls the
pattern again, because that is how the sixth instance gets written without the retry.
"""

import json
import os
import pathlib
import re
import threading

import pytest

import atomic_json

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def test_the_payload_lands_and_no_temp_file_is_left_behind(tmp_path):
    target = tmp_path / "thing.json"
    atomic_json.write_json(target, {"a": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}
    leftovers = [p.name for p in tmp_path.iterdir() if ".tmp" in p.name]
    assert not leftovers, leftovers


def test_the_parent_directory_is_created_when_asked_and_not_when_not(tmp_path):
    deep = tmp_path / "a" / "b" / "thing.json"
    atomic_json.write_json(deep, {"ok": True})
    assert deep.is_file()

    other = tmp_path / "c" / "d" / "thing.json"
    with pytest.raises(OSError):
        atomic_json.write_json(other, {"ok": True}, make_parent=False)


def test_a_transient_rename_refusal_is_retried(tmp_path, monkeypatch):
    real = pathlib.Path.replace
    calls = {"n": 0}

    def flaky(self, dst):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError(5, "Access is denied")
        return real(self, dst)

    monkeypatch.setattr(pathlib.Path, "replace", flaky)
    target = tmp_path / "t.json"
    atomic_json.write_json(target, {"v": 2})
    assert calls["n"] == 3, calls
    assert json.loads(target.read_text(encoding="utf-8")) == {"v": 2}


def test_a_permanent_refusal_raises_and_cleans_up_after_itself(tmp_path, monkeypatch):
    """A write that cannot land must raise - and must not litter the data volume trying."""
    monkeypatch.setattr(pathlib.Path, "replace",
                        lambda self, dst: (_ for _ in ()).throw(PermissionError(5, "denied")))
    target = tmp_path / "t.json"
    with pytest.raises(PermissionError):
        atomic_json.write_json(target, {"v": 3})
    leftovers = [p.name for p in tmp_path.iterdir() if ".tmp" in p.name]
    assert not leftovers, "a failed write left its temp file behind: %r" % leftovers


def test_only_a_permission_error_is_retried(tmp_path, monkeypatch):
    """Retrying a disk-full error three times just delays the error the caller needs."""
    calls = {"n": 0}

    def full(self, dst):
        calls["n"] += 1
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(pathlib.Path, "replace", full)
    with pytest.raises(OSError):
        atomic_json.write_json(tmp_path / "t.json", {})
    assert calls["n"] == 1, "a disk-full error was retried %d times" % calls["n"]


def test_the_temp_name_separates_two_processes(tmp_path):
    """The pid is what stops a SECOND PROCESS colliding, which is the case a lock cannot cover.

    Not tested with threads: every caller holds its own lock across the write, so two writers in one
    process are never simultaneous. An earlier version of this check tried to force that with a
    barrier, deadlocked against exactly that lock, timed out, and still passed - on names collected
    by writers that never renamed anything.
    """
    target = tmp_path / "t.json"
    seen = []
    for pid in (1111, 2222):
        import unittest.mock as mock
        with mock.patch("os.getpid", lambda pid=pid: pid):
            seen.append(atomic_json.temp_path_for(target).name)
    assert "1111" in seen[0] and "2222" in seen[1], seen
    assert seen[0] != seen[1], seen
    assert str(threading.get_ident()) in seen[0], seen[0]


def test_nobody_hand_rolls_the_pattern_any_more():
    """THE POINT OF THIS FILE. A sixth copy is how the retry gets lost again.

    Scans every backend module for the shape that had the bug: a `.with_suffix(".tmp")` temp path,
    or a `.replace(` onto something that looks like a data-volume file, outside atomic_json itself.
    Scripts that are run by hand are exempt - they are one-shot tools, not the app.
    """
    exempt = {
        "atomic_json.py",                 # the implementation
        "annotate_templates.py",          # one-shot template tooling, run by a human
        "prepare_info_sheet_template.py",
        "add_phase_row.py",
        "inspect_templates.py",
        "dropbox_oauth_setup.py",
        "dropbox_oauth_finish.py",
    }
    offenders = []
    for py in sorted(BACKEND.glob("*.py")):
        if py.name in exempt:
            continue
        src = py.read_text(encoding="utf-8")
        # strip comments so a docstring describing the old pattern does not trip this
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        if re.search(r'with_suffix\(\s*["\']\.tmp["\']\s*\)', code):
            offenders.append("%s: fixed .tmp temp name" % py.name)
        for m in re.finditer(r"(\w+)\.replace\(\s*(_[A-Z_]+|self\._\w+)\s*\)", code):
            offenders.append("%s: hand-rolled rename %s" % (py.name, m.group(0)))
    assert not offenders, (
        "these write a data file without going through atomic_json, so they have the fixed temp "
        "name and no rename retry: %r" % offenders)
