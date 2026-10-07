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

THE NEWEST SHAPES (added 2026-10-07 for the v2 estimating program, see NEWEST_TOTALS below). The
fixtures above are what a bid looked like before Kyle's B1-B8 batches. A bid saved by today's page
holds more: the Lodging / Per Diem block and a saved distance, the Labor Calculator's `calc_default`
and `hours_per_day`, rows saved switched off (a library default with default_on false) and
`same_floor` rows, the bid's own coverage (`coverage`, `line_cov`, `cond_cov`), Fees + Textura, a
library that said "no Travel Labor", and a stale `totals` snapshot the page must never price from.
The v2 program rewrites exactly the code that reads and writes these (the model passthrough, the
save patch, the profile engine, multi-section estimates), and a refactor that quietly drops or
re-derives one of them moves a customer's price. Those fixtures did not exist at 8708a75, so their
totals are pinned from `git archive origin/staging` at the commit named in NEWEST_PINNED_FROM: a
ratchet from there, not an independent derivation. Each is opened plain, opened with a library full
of defaults (which a saved bid ignores), and SAVED then REOPENED (the second open must not drift).
"""
import json
import pathlib
import shutil
import subprocess

import pytest

from _golden_support import break_source

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

# The newest shapes (see the module docstring). Pinned from origin/staging at this commit, by running
# saved-bid-harness.js over `git archive origin/staging frontend`; whole dollars.
NEWEST_PINNED_FROM = "3f94ed20e31dfdd1a56af5a28583f5e4b638ca2f"
NEWEST_TOTALS = {
    "v2_travel_block_far_job": 60233,
    "v2_travel_typed_and_hand_flipped": 40105,
    "v2_labor_calculator_rows": 106310,
    "v2_default_rows_saved": 41583,
    "v2_coverage_overrides": 45266,
    "v2_fees_contingency_no_travel_labor": 42759,
    "v2_remodel_rate_override_wins": 35834,
    "v2_remodel_county_without_a_rate": 34307,
}


def _run(script, frontend=FRONTEND):
    proc = subprocess.run(["node", str(script), str(frontend)], capture_output=True, text=True,
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


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# THE NEWEST SHAPES (see the module docstring). Pinned from origin/staging at NEWEST_PINNED_FROM.
# ═══════════════════════════════════════════════════════════════════════════════════════════════
def _newest(ran, name, pass_name="fixtures"):
    return ran["newest"][pass_name][name]


@needs_node
@pytest.mark.parametrize("name", sorted(NEWEST_TOTALS))
def test_the_newest_saved_shapes_open_at_their_pinned_totals(ran, name):
    """Opened plain and opened with a library full of defaults (a company labor rate of $50, lodging
    $99, per diem $77, a calculator, default rows, a far distance answer waiting): a saved bid ignores
    every bit of it. And opening writes nothing and asks the server nothing.

    Mutation: any new-bid default reaching a saved bid, or a refactored model dropping a key it used
    to carry, moves one of these totals or one of the facts asserted below."""
    for pass_name in ("fixtures", "withLibrary"):
        got = _newest(ran, name, pass_name)
        assert got["total"] == NEWEST_TOTALS[name], (pass_name, name, got["total"])
        assert got["totalAfterSettle"] == NEWEST_TOTALS[name], (pass_name, name)
        assert got["saves"] == 0, (pass_name, name, "opening a saved bid writes nothing")
        assert got["distanceAsked"] == 0, (pass_name, name, "a saved bid never asks the server")


@needs_node
@pytest.mark.parametrize("name", sorted(NEWEST_TOTALS))
def test_a_newest_shape_bid_comes_back_to_the_same_total_after_a_save(ran, name):
    """Save it (the autosave, forced), then open what was saved in a fresh page. The total, the
    `computed_bid` the board reads and the SF on file all agree with the first open, and the second
    open still writes nothing. A save that drifted would move a customer's price on the SECOND open
    of a bid, which no single-open test sees."""
    rt = ran["newest"]["roundTrip"][name]
    assert rt["totalFirst"] == rt["savedLump"] == rt["totalAgain"] == NEWEST_TOTALS[name], (name, rt)
    assert rt["savesAgain"] == 0, name
    assert rt["savedSf"] == _newest(ran, name)["sf"], name


@needs_node
def test_travel_lines_hotel_and_per_diem_stay_as_saved(ran):
    """The far job keeps both lines ON at the rates it was saved with (the library's $99 / $77 are
    for NEW bids only), its saved distance, and a total that is not the stale snapshot's 11,111."""
    far = _newest(ran, "v2_travel_block_far_job")
    t = json.loads(far["travelDetail"])
    assert t["lodging"]["enabled"] is True and t["per_diem"]["enabled"] is True
    assert (t["lodging"]["rate"], t["per_diem"]["rate"]) == (70, 45)
    assert (t["lodging"]["qty"], t["lodging"]["qty_auto"]) == (19.5, True)       # the crew's man-days
    assert far["distance"] == '{"miles":150,"source":"google","key":"1 water works dr|kansas city|ks|66101"}'
    assert far["local"] is False and far["rateDefaults"] == [33, 33, 33, 33]
    assert far["total"] not in (11111, 99, 5), "the page priced from the stale `totals` snapshot"
    assert _newest(ran, "v2_travel_block_far_job", "withLibrary")["rates"] == [33, 33, 33, 33]


@needs_node
def test_typed_travel_quantities_and_hand_flips_are_not_re_derived(ran):
    typed = _newest(ran, "v2_travel_typed_and_hand_flipped")
    t = json.loads(typed["travelDetail"])
    assert t["lodging"] == {"label": "Lodging", "enabled": True, "qty": 12, "qty_auto": False, "rate": 85,
                            "hand": True, "rate_default": 70}
    # per diem was switched off by hand on a far job: the distance does not turn it back on
    assert t["per_diem"]["enabled"] is False and t["per_diem"]["hand"] is True and t["per_diem"]["rate"] == 52
    assert typed["distance"] == '{"miles":82.3,"source":"typed","key":""}'
    assert typed["laborGuys"][3] == 6 and typed["laborDays"][3] == 4, "typed Travel Guys and hours"
    assert typed["rates"] == [35, 35, 35, 41]


@needs_node
def test_labor_calculator_rows_keep_their_numbers_on_open(ran):
    """A `From SF` line whose takeoff has since grown to 20,000 SF keeps its 13 days on open (the days
    follow the takeoff only when the SF changes inside a session); a line the estimator typed over keeps
    their 2; a 10-hour line stays on 10-hour days; calc_default is carried intact."""
    calc = _newest(ran, "v2_labor_calculator_rows")
    assert calc["laborDays"] == [13, 2, 3, "", 1]
    assert calc["laborHoursPerDay"] == [10, None, 10, None, None]
    assert calc["calcDefaults"] == [
        '{"guys":5,"days":13,"rate":50,"hours_per_day":10,"sf_per_day":1000}',
        '{"guys":3,"days":1,"rate":50,"hours_per_day":8}',
        '{"guys":2,"days":3,"rate":50,"hours_per_day":10}', None, None]
    assert calc["laborGuys"][3] == 79, "Travel Guys is the crew's man-days: 5x13 + 3x2 + 2x3 + 2x1"
    assert calc["rateDefaults"] == [None, None, None, 50, 40]
    assert calc["sf"] == 20000 and calc["offRows"] == 1


@needs_node
def test_default_rows_keep_their_off_switches_and_the_one_floor(ran):
    """default_on false is saved as `enabled: false`; a same_floor row is priced but not counted twice;
    a hidden card stays hidden. The floor is counted ONCE (10,000 SF), not once per default."""
    d = _newest(ran, "v2_default_rows_saved")
    assert d["takeoff"] == [[10000, False, False, None, None], [10000, False, True, None, None],
                            [10000, True, True, None, None], ["", True, False, None, None],
                            [10000, True, True, "", None]]
    assert d["offRows"] == 5 and d["sf"] == 10000
    assert d["conditionsShown"] == '{"dye":false}'
    assert d["labels"][-2:] == ["Tint", "Saw"] and d["rateDefaults"] == [33, 33, 33, 33, 50, 50]


@needs_node
def test_the_bids_own_coverage_survives_and_reaches_the_workbook_cells(ran):
    """A row's `coverage`, an assembly row's `line_cov` and the model's `cond_cov` are carried as saved,
    and the cells the downloaded workbook is written from quote them: dye at $0.14 over a typed coverage
    of 2 is $0.07 a square foot, and the joint-filler kit count divides by the typed 3,000."""
    c = _newest(ran, "v2_coverage_overrides")
    assert c["takeoff"] == [[12500, False, False, None, '{"0":300,"1":700}'], [5000, False, False, 500, None],
                            [200, False, False, None, '{"0":"150"}']]
    assert c["condCov"] == '{"joint_filler":3000,"dye":2}'
    cells = json.loads(ran["newest"]["roundTrip"]["v2_coverage_overrides"]["cellsKeepTheConditions"])
    assert cells["Polish!C25"] == cells["Polish!C26"] == 0.07 and cells["Polish!C29"] == 500
    assert cells["Polish!B29"] == '=ROUNDUP(IF(E29="yes",(E18/3000),0),0)'


@needs_node
def test_fees_contingency_and_a_library_that_said_no_travel_labor_are_kept(ran):
    f = _newest(ran, "v2_fees_contingency_no_travel_labor")
    assert (f["fees"], f["feesDefault"], f["contingency"]) == (750, 750, 1200)
    assert f["noTravelLabor"] is True and f["labels"] == ["Polishing", "Mock-up", "Joint filler"], \
        "the page must not put Travel Labor back on a bid whose library said no"
    assert f["conditionsShown"] == '{"dye":false}'
    t = json.loads(f["travelDetail"])
    assert (t["lodging"]["rate"], t["per_diem"]["rate"]) == (65, 40)
    lib = _newest(ran, "v2_fees_contingency_no_travel_labor", "withLibrary")
    assert lib["labels"] == f["labels"] and lib["fees"] == 750


@needs_node
def test_where_the_remodel_rate_comes_from_is_pinned_at_the_page(ran):
    """A rate typed for THIS address (7.15%) beats the county's (7.975%), and a county with no rate on
    file (Missouri) is an explicit zero, not the Kansas 6.5% floor. Between them the totals order:
    7.15% taxes more than 0%."""
    over = _newest(ran, "v2_remodel_rate_override_wins")["total"]
    none = _newest(ran, "v2_remodel_county_without_a_rate")["total"]
    assert over > none


# ── red without the code: break a COPY of the page or the model and watch the ratchet notice ───────
HARNESS_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/library-core.js"]

NEWEST_MUTATIONS = {
    "migrate drops the bid's own coverage": (
        "js/bid-model.js", "if (Object.keys(cc).length) out.cond_cov = cc;", "void cc;",
        "v2_coverage_overrides", lambda got: got["condCov"] is None and got["total"] != NEWEST_TOTALS["v2_coverage_overrides"]),
    "migrate drops the saved distance": (
        "js/bid-model.js", "if (dist) out.distance = dist;", "void dist;",
        "v2_travel_block_far_job", lambda got: got["distance"] is None),
    "migrate drops which cards a bid shows": (
        "js/bid-model.js", "out.conditions_shown = shown;", "void shown;",
        "v2_default_rows_saved", lambda got: got["conditionsShown"] is None),
    "migrate forgets the library said no Travel Labor": (
        "js/bid-model.js", "out.no_travel_labor = true;", "void 0;",
        "v2_fees_contingency_no_travel_labor", lambda got: got["noTravelLabor"] is False),
    "a hand flip on a travel line is forgotten": (
        "js/bid-model.js", "if (l.hand === true) out[k].hand = true;", "void l;",
        "v2_travel_typed_and_hand_flipped", lambda got: '"hand"' not in got["travelDetail"]),
    "every labor day becomes eight hours": (
        "js/bid-model.js", 'var perDay = row.unit === "hours" ? 1 : dayHours(row);',
        'var perDay = row.unit === "hours" ? 1 : HOURS_PER_DAY;',
        "v2_labor_calculator_rows", lambda got: got["total"] != NEWEST_TOTALS["v2_labor_calculator_rows"]),
    "opening a bid re-follows the takeoff": (
        "js/polish-estimate.js", "followSf = B.takeoffSf(M.takeoff);",
        "followSf = B.takeoffSf(M.takeoff); M.labor = B.followLaborDays(M.labor, followSf);",
        "v2_labor_calculator_rows", lambda got: got["laborDays"][0] != 13 and got["total"] != NEWEST_TOTALS["v2_labor_calculator_rows"]),
    "the county's rate beats the one typed for the address": (
        "js/polish-estimate.js", "var r = state.remodel_rate_override;", "var r = state.county_remodel_rate;",
        "v2_remodel_rate_override_wins", lambda got: got["total"] != NEWEST_TOTALS["v2_remodel_rate_override_wins"]),
    "a county with no rate is read as nobody-picked-one": (
        "js/polish-estimate.js", "if (state.county) return 0;", "void 0;",
        "v2_remodel_county_without_a_rate", lambda got: got["total"] != NEWEST_TOTALS["v2_remodel_county_without_a_rate"]),
}


@needs_node
@pytest.mark.parametrize("name", sorted(NEWEST_MUTATIONS))
def test_the_ratchet_goes_red_when_the_page_or_the_model_changes(tmp_path, name):
    """Each change is the kind a refactor makes by accident, applied to a scratch copy of the page and
    its two core modules; the ratchet must show it on the fixture that holds that shape. The anchor line
    must exist exactly once (break_source refuses otherwise), so none can pass by applying nowhere."""
    rel, old, new, fixture, notices = NEWEST_MUTATIONS[name]
    frontend = break_source(tmp_path, rel, old, new)
    for f in HARNESS_FILES:
        dest = frontend / f
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(FRONTEND / f, dest)
    got = _run(HARNESS, frontend)["newest"]["fixtures"][fixture]
    assert notices(got), (name, fixture, {k: got[k] for k in ("total", "laborDays", "distance", "condCov")})
