"""A coat typed the floor's own number stays on that floor (2026-10-16).

Found re-entering a real job on staging: a primer added beside a 5,482 SF Epoxy floor started on the same floor (it
carries the floor's number and takeoffSf does not count it again). The estimator then typed 5,482 into it, a keystroke
at a time, and the first "5" made it a second floor for good. The area doubled to 10,964 SF, and with it the patch, the
tooling and consumables and the square feet the proposal printed: $55,795 against the workbook's $51,165.

Now a row that leaves its floor by being typed into keeps `same_floor_left`, and rejoins the floor the moment its number
is the floor's again. A row that never followed a floor is never joined to one (two rooms of one size are two floors),
and a coat of area 2 can only rejoin area 2.
"""
from __future__ import annotations

import pathlib

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "coat-floor-harness.js"
SCRATCH = ["js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js", "js/work-types.js", "js/markup-core.js",
           "js/excel-math.js"]


def _run(frontend):
    require_node()
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    return _run(FRONTEND)


def test_a_primer_retyped_to_the_floors_number_is_still_that_floor(ran):
    r = ran["retyped"]
    assert r["sf"] == 5482, "the floor is counted once"
    assert r["rows"][2].get("same_floor") is True and "same_floor_left" not in r["rows"][2]


def test_a_coat_typed_another_number_is_its_own_floor_until_it_is_the_floors_again(ran):
    assert ran["other"]["sf"] == 8482 and ran["other"]["rows"][2].get("same_floor_left") is True
    assert ran["backToFloor"]["sf"] == 5482 and ran["backToFloor"]["rows"][2].get("same_floor") is True
    assert ran["zero"]["sf"] == 5482, "a 0 row adds nothing and never joins a floor"


def test_the_floor_moved_to_the_coats_number_takes_the_coat_back_on_the_next_keystroke_only(ran):
    """Moving the FLOOR does not reach into a coat that left it (only the coat's own typing decides), so the area counts
    both until the coat is touched. That is the rule the floor's own drag has always had for a row set to its own number."""
    assert ran["floorMovedToIt"]["sf"] == 6000


def test_two_rooms_of_one_size_are_two_floors(ran):
    assert ran["twoRooms"]["sf"] == 4000
    assert "same_floor" not in ran["twoRooms"]["rows"][1]


def test_a_coat_of_one_area_only_rejoins_its_own(ran):
    assert ran["area2Retyped"]["sf"] == 6500
    assert ran["area2Retyped"]["rows"][2].get("same_floor_of") == 2
    assert ran["area2TypedArea1Number"]["sf"] == 10500, "area 2's coat never joins area 1"
    assert ran["area2TypedArea1Number"]["rows"][2].get("same_floor_left_of") == 2


def test_a_unit_change_forgets_the_coats_floor(ran):
    row = ran["unitChanged"]["rows"][2]
    assert row["unit"] == "LF" and "same_floor_left" not in row and "same_floor_left_of" not in row


MUTATIONS = {
    "typing still drops the floor for good": (
        "js/bid-model.js", "      if (floor && num(value) > 0 && num(value) === num(floor.measurement)) {",
        "      if (false) {", lambda r: r["retyped"]["sf"] != 5482),
    "a coat may join another area": (
        "js/bid-model.js", "      if (carrierTag(q) === tag && num(q.measurement) > 0) return q;",
        "      if (num(q.measurement) > 0) return q;", lambda r: r["area2TypedArea1Number"]["sf"] != 10500),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_the_facts_go_red_when_the_code_changes(tmp_path, name):
    rel, old, new, noticed = MUTATIONS[name]
    frontend = break_source(tmp_path, rel, old.strip(), new.strip())
    copy_unmodified(frontend, SCRATCH)
    assert noticed(_run(frontend)), "the facts did not notice: " + name
