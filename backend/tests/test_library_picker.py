"""The shared search pop-up (frontend/js/library-picker.js): the logic, executed.

Both Estimating Tool v2 "Add" buttons open it (Takeoff: assemblies and materials; Labor: the
Labor list). The pure half is run here by tests/js/library-picker-harness.js; the DOM half is run
end to end, on the real estimate page, by tests/test_polish_estimate_page.py (the "pop-up" tests).

Mutation proofs, each a one-line change in a scratch copy that turns a test below red:
  * shown(): drop the `e.first` split              -> test_work_type_rows_are_listed_first
  * matches(): any word instead of every word      -> test_every_word_typed_has_to_match
  * picked(): drop the `!e.on` guard                -> test_locked_rows_are_never_returned_and_order_is_the_lists
"""
from __future__ import annotations

import pathlib

import pytest

from _node import last_json_line, run_node

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "library-picker-harness.js"


@pytest.fixture(scope="module")
def ran():
    proc = run_node(HARNESS, FRONTEND)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


def test_work_type_rows_are_listed_first(ran):
    # b and d carry first=true: they lead, each group keeps the caller's own order.
    assert ran["all"] == ["b", "d", "a", "c", "e"]


def test_every_word_typed_has_to_match(ran):
    assert ran["oneWord"] == ["b"]
    assert ran["twoWordsNarrow"] == ["c", "e"], "two words must narrow, not widen"
    assert ran["matchesTheSmallLine"] == ["b"], "the small line under a name is searchable too"
    assert ran["caseAndSpaces"] == ["c"]
    assert ran["none"] == [] and ran["notArray"] == []
    assert ran["inputUntouched"] is True


def test_ticks_toggle_and_keep_the_order_they_were_made_in(ran):
    assert ran["afterTwo"] == ["c", "a"]
    assert ran["afterUntick"] == ["a"]
    assert ran["toggleIsNew"] is True
    assert ran["protoKey"] == ["__proto__", "constructor"]


def test_locked_rows_are_never_returned_and_order_is_the_lists(ran):
    # c and a were ticked, e is locked (already on the bid), "gone" no longer exists.
    assert ran["picked"] == ["a", "c"]


def test_a_one_off_name_is_trimmed_and_nothing_is_not_a_name(ran):
    assert ran["clean"] == ["Hand grind", "", "", "x"]
