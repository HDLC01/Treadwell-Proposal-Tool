"""F5: a bid SAVED before Kyle's B1-B8 batches opens on this branch at the same total.

Every assertion runs the real page. tests/js/saved-bid-harness.js boots js/polish-estimate.js whole
(the same boot code polish-estimate-harness.js uses) over fixtures shaped the way staging's drafts
are today: a v2 model with a "Travel" labor row and no `travel` block / `distance` / `enabled` /
`hours_per_day`, a v1 {areas} model, and an intake-only blob with none of B1's new fields.

THE PINNED TOTALS ARE NOT THIS BRANCH'S OUTPUT. They are what origin/staging's page (8708a75, before
B1) computes for the same blob, taken by running the same harness over `git archive origin/staging
frontend`. A branch that reprices a saved bid fails here even if its own arithmetic is internally
consistent.

Before / after (staging -> this branch), whole dollars:
    v2 local job, "Travel" row, dye + joint filler on        49,798 -> 49,798
    v2 far job (local:false), no distance, remodel tax       38,865 -> 38,865
    v2 renamed Travel ("Drive time") + a custom line         54,328 -> 54,328
    v2 saved before Travel existed                           45,513 -> 45,513
    v1 {areas}                                                1,102 ->  1,102
    intake-only blob, System 1 SF only                        1,102 ->  1,102
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "saved-bid-harness.js"
INTAKE_HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "polish-intake-harness.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

STAGING_TOTALS = {
    "v2_local_travel_row": 49798,
    "v2_far_job_no_distance": 38865,
    "v2_renamed_travel_and_custom_line": 54328,
    "v2_before_travel_row": 45513,
    "v1_areas": 1102,
}


def _run(script):
    proc = subprocess.run(["node", str(script), str(FRONTEND)], capture_output=True, text=True,
                          encoding="utf-8", timeout=180)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    return _run(HARNESS)


@pytest.fixture(scope="module")
def intake():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    return _run(INTAKE_HARNESS)


@needs_node
@pytest.mark.parametrize("name", sorted(STAGING_TOTALS))
def test_a_saved_bid_opens_at_the_total_staging_gives_it(ran, name):
    """Plain library (nothing filed) and a library full of defaults must both leave it alone.

    Mutation: normalizeTravel's `enabled: l.enabled === true` -> `!== false` switches Lodging and
    Per Diem on for every old bid (the far job moves by the crew's man-days x $70 + $45)."""
    for pass_name in ("fixtures", "withLibrary"):
        got = ran[pass_name][name]
        assert got["total"] == STAGING_TOTALS[name], (pass_name, name, got)
        assert got["totalAfterSettle"] == STAGING_TOTALS[name], (pass_name, name, got)
        assert got["travelBlock"] == '{"lodging":false,"per_diem":false}', (pass_name, name)
        assert got["offRows"] == 0, "nothing on an old bid is switched off"


@needs_node
def test_opening_a_saved_bid_writes_nothing_and_asks_the_server_nothing(ran):
    """polish_sf on an estimate-saved draft is already the takeoff total, so a plain reopen is not
    a save; and the distance lookup belongs to a NEW bid only (a far answer would flip Travel on).

    Mutation: `if (laborDefaults && !M.distance) lookupDistance(false)` -> `if (!M.distance)`."""
    for pass_name in ("fixtures", "withLibrary"):
        for name in STAGING_TOTALS:
            got = ran[pass_name][name]
            assert got["saves"] == 0, (pass_name, name)
            assert got["distanceAsked"] == 0, (pass_name, name)


@needs_node
def test_the_travel_row_is_only_relabelled_and_the_rates_are_the_bids_own(ran):
    """"Travel" -> "Travel Labor" is a label and nothing else; a name somebody typed is theirs; and
    the company labor rate ($50 in the stubbed library) reaches no saved row."""
    f = ran["withLibrary"]
    assert f["v2_local_travel_row"]["labels"] == ["Polishing", "Mock-up", "Joint filler", "Travel Labor"]
    assert f["v2_renamed_travel_and_custom_line"]["labels"][3] == "Drive time"
    assert f["v2_local_travel_row"]["rates"] == [33, 33, 33, 33]
    assert f["v2_renamed_travel_and_custom_line"]["rates"] == [35, 35, 35, 35, 40]
    assert f["v2_far_job_no_distance"]["local"] is False, "a saved far job stays a far job"


@needs_node
def test_the_library_stub_is_live_so_the_pass_above_is_not_vacuous(ran):
    """The SAME stubbed library on a NEW bid acts: the company rate, the default rows (two OFF),
    Lodging and Per Diem coming on at 150 miles, local going false. If this fails the withLibrary
    pass proves nothing."""
    c = ran["control"]
    assert c["rates"] == [50, 50, 50, 41, 50]
    assert c["offRows"] == 2
    assert c["takeoffRows"] > 3
    assert c["travel"] == '{"lodging":true,"per_diem":true}'
    assert c["local"] is False


@needs_node
def test_an_old_intake_blob_seeds_from_system_one_exactly_as_before(ran):
    got = ran["fixtures"]["intake_only_no_estimate"]
    assert got["sf"] == 8250
    assert got["total"] == 1102


@needs_node
def test_switching_off_the_only_sf_row_keeps_the_measured_floor(ran):
    """B5 low. The slider is a price choice; the floor stays measured. polish_sf on file is the
    floor, not 0 (proposal-review's SF token reads it), the bid's own area is 0, and a reopen does
    not re-seed over the off row.

    Mutation: polish_sf: b.sf  (the old line) saves 0 here."""
    o = ran["offOnly"]
    assert o["before"] == {"total": 29826, "sf": 12500}
    assert o["rowEnabled"] is False
    assert o["afterPricedSf"] == 0 and o["priced"] == 0
    assert o["afterTotal"] < o["before"]["total"], "the off row really left the price"
    assert o["savedPolishSf"] == 12500
    assert o["computedSf"] == 0, "computed_bid keeps the AREA PRICED (price per SF divides by it)"
    assert o["measured"] == 12500
    assert o["sameFloorCarrierOff"] == 5000
    assert o["lfOnly"] == 0
    assert o["reopenedMeasurement"] == [12500] and o["reopenedRows"] == 1


@needs_node
def test_intake_keeps_its_sf_lock_when_the_only_row_is_off(intake):
    """Mutation: sfLocked back to B.takeoffSf(model.takeoff) > 0 unlocks both boxes and lets the
    stale 1 / 2 the form hands over reach polish_sf."""
    o = intake["f5"]["offLocked"]
    assert o["ro1"] is True and o["ro2"] is True
    assert o["v1"] == 12500
    assert o["noteHidden"] is False
    assert o["saveHasSf"] is False
    assert o["blobSf"] == 12500
    assert o["takeoffEnabled"] is False


@needs_node
def test_required_project_name_and_bid_date_never_block_an_old_drafts_save(intake):
    """`required` on Bid date and Project name is the browser's gate on the Continue button. The
    page's own save() (the 600ms autosave, the pagehide flush, onSubmit) asks nobody for validity:
    an old draft with a blank name saves, keeps its takeoff, keeps its saved local answer, and the
    blank Bid date defaults to today on load."""
    o = intake["f5"]["oldBlob"]
    assert o["threw"] is None and o["saved"] is True
    assert o["dateAfterBoot"] and len(o["dateAfterBoot"]) == 10
    assert o["savedName"] == ""
    assert o["takeoffKept"] == 1
    assert o["navigated"] == 1 and o["submitSaved"] is True


def test_the_two_required_attributes_are_html_only():
    """Pinned so nobody 'fixes' the autosave path into a validity gate: the JS holds no
    checkValidity / reportValidity call."""
    js = (FRONTEND / "js" / "polish-intake.js").read_text(encoding="utf-8")
    assert "checkValidity" not in js and "reportValidity" not in js
