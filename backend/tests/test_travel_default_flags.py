"""Travel is a labor default like any other (Hanz, 2026-10-06): a new bid honours the stored Travel
row's `favorite` and `default_work_types`. Runs the real engine. No stored row, or a row with
favorite absent/null and no work types, is Travel on every new bid, exactly as before."""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "travel-default-harness.js"
CREW = ["polishing", "mockup", "jointfill"]


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    p = subprocess.run(["node", str(HARNESS), str(FRONTEND)], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])


def test_unchanged_behaviour_gives_every_new_bid_travel(ran):
    for k in ("noRow", "noRowAtAll", "absentFavorite", "nullFavorite", "favoriteTrue", "scopedPolish"):
        assert ran[k] == CREW + ["travel"], "%s: %s" % (k, ran[k])


def test_a_removed_or_out_of_scope_travel_is_not_seeded(ran):
    """Mutation: drop the travelAppliesToBid gate in seedLibraryLabor -> all three keep Travel."""
    assert ran["removed"] == CREW
    assert ran["scopedEpoxy"] == CREW
    assert ran["scopedEpoxyBidIsEpoxy"] == CREW + ["travel"]


def test_work_type_scope_applies_to_custom_lines_too(ran):
    assert ran["customScopedElsewhere"] == CREW + ["travel", "c2"]


def test_declined_is_true_only_when_the_row_says_no(ran):
    assert ran["declined"] == {"removed": True, "scoped": True, "absent": False, "noRow": False}


def test_a_declined_travel_is_not_appended_back_on_reload(ran):
    """Mutation: drop the no_travel_labor branch in migrateModel -> Travel returns on reload."""
    assert ran["reloadKeepsItOff"] == CREW and ran["reloadMarker"] is True
    assert ran["staleDraftStillBackfilled"] == CREW + ["travel"]
