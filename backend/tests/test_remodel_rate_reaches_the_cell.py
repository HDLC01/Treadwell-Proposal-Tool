"""Picking a county must move the workbook's actual remodel-tax number, not just JS state.

Kyle, via a screenshot: "It was brought to my attention that the remodel tax calculator is not
giving correct tax %. I'm not sure how that works but we use the link within the original excel
sheet to go to the website, enter the address, and get the tax % from there."

An earlier fix corrected the REFERENCE data (backend/reference_tax.py — see
test_reference_tax.py) and stopped there. This test file is for the deeper half of the same bug:
the county picker never actually reached the bid. `pickCounty` (frontend/js/estimate-review.js)
only ever set `state.county_remodel_rate` and told the estimator to hand-type the number into
K81/K75/K80 — plain text LABEL cells wired to nothing. The real formula cell that drives the
math — `Epoxy!B81` / `Polish!B75` / `<Gyp variant>!B80` — kept Kyle's own hardcoded
`=IF(D6="yes",0.1,0)` 10% placeholder forever, no matter what the picker said on screen.

The fix writes the corrected formula straight into `cellValues` (the same verbatim
`"<Sheet>!<Addr>"` dict that `/api/generate` already forwards untouched into
`estimate_writer.fill_estimate()`'s cell_values write step — see test_cell_lock.py's
`test_cell_values_write_into_locked_cell_still_lands` for that mechanism) and into the live HF
engine so the on-screen total updates immediately, matching the pattern the AI-autofill feature
already uses for its own cell writes.

Executed, not grepped: the original bug was invisible to source reading — the code that existed
was internally consistent, it just never reached the one cell that mattered. Only running
`pickCounty` for real and inspecting the resulting `cellValues`/HF writes can prove the fix
actually lands.

2026-09-02 — the same bug, one layer down. That fix wrote the rate to a hand-typed list of
sheets: Epoxy, Polish and the five gyp variants. Reading the shipped workbook instead of the
comment above that list turned up three more sheets carrying the identical
`=IF(D6="yes",0.1,0)` placeholder — `Seal!B75`, `Leveling!B77` and `Epoxy blank!B78` — and a
fourth hole with no sheet name at all: a COPIED tab. Copies are the ordinary way to put a priced
option in front of a customer, and `estimate_writer._create_copied_tabs` clones them from the
PRISTINE template, so a copy's rate cell arrives holding the 10% placeholder. Copying before
picking the county, or changing the county after copying, shipped a 10% option line beside an
otherwise correct base bid — while the pill overhead said the real rate was applied
automatically. Cases 6-9 in the harness are those four holes.

Case 10 is the regression cases 6-9 introduced, and it took a real browser to see it. Bringing
copies in meant the override's own grid refresh reached a copied tab for the first time — and it
refreshed by discarding the active sheet's cache and re-fetching it, which 404s for a copy and
painted "Failed to load Copy1" over the tab. All nine cases above sit on a base tab, where that
refetch happens to succeed, so all nine stayed green while staging carried the bug.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = REPO / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "remodel-rate-harness.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def result():
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_covers_every_sheet_with_a_remodel_tax_line(result):
    """Epoxy + Polish + Seal + Leveling + Epoxy blank + every Gyp variant = 10 cells.

    This count was 7 until 2026-09-02, and the three missing sheets are the point: the list was
    written from a comment asserting they had no remodel line, and the workbook says otherwise.
    If a 6th Gyp variant is ever added, this is the number that must move — not a hand-typed
    count going stale while a real customer's option line quotes 10%."""
    assert result["gypSheetCount"] == 5
    assert result["pickedCity"]["cellCount"] == 10


def test_picking_a_city_writes_the_real_rate_into_every_formula_cell(result):
    p = result["pickedCity"]
    assert p["epoxy"] == '=IF(D6="yes",0.0935,0)'
    assert p["polish"] == '=IF(D6="yes",0.0935,0)'
    for sheet, formula in p["gyp"].items():
        assert formula == '=IF(D8="yes",0.0935,0)', (sheet, formula)


def test_the_write_also_reaches_the_live_hf_engine(result):
    """So the on-screen total is right NOW, not just in the file the estimator downloads later."""
    p = result["pickedCity"]
    assert p["hfCallCount"] == 10
    assert p["hfMatchesCellValues"] is True


def test_the_active_sheets_grid_is_refreshed(result):
    """cellValues alone would be right in the generated file but stale on screen — the estimator
    would see the old total until they clicked away and back.

    HOW it refreshes matters, which is why the cache is asserted alongside. This used to
    `delete sheetCache[activeSheet]` and re-run `showSheet` — a wasteful round trip on a base tab,
    and outright data loss on a copy (see the last test in this file). It now
    re-renders from the live HF engine and leaves the cache alone."""
    p = result["pickedCity"]
    assert p["gridRefreshedFor"] == ["Epoxy"]
    assert p["cachePreserved"] is True


def test_state_still_carries_what_the_proposal_step_reads(result):
    """The {{county}} token and the on-screen state must keep working exactly as before — this
    fix adds a cellValues write, it does not replace the existing state bookkeeping."""
    p = result["pickedCity"]
    assert p["stateCounty"] == "Overland Park, KS"
    assert p["stateCountyTaxRate"] == 0.0935
    assert p["stateCountyRemodelRate"] == 0.0935
    assert p["persistedRemodelRate"] == 0.0935


def test_the_hint_no_longer_tells_the_estimator_to_hand_type_a_dead_cell(result):
    """The old copy said "(enter in K81)" — a legend cell wired to nothing. Following that
    instruction changed zero dollars on the bid; the new copy must not repeat that instruction."""
    pill = result["pickedCity"]["pillHtml"]
    assert "K81" not in pill
    assert "applied automatically" in pill
    assert "9.350%" in pill


def test_a_county_with_no_override_reverts_every_cell_to_kyles_own_placeholder(result):
    """A county-only pick (no `remodel_rate` override, e.g. the KS floor-rate rows) must not
    leave a stale rate from a previous city pick sitting in the formula."""
    p = result["pickedCountyNoOverride"]
    assert p["epoxy"] == '=IF(D6="yes",0.1,0)'
    assert p["polish"] == '=IF(D6="yes",0.1,0)'
    assert p["oneGyp"] == '=IF(D8="yes",0.1,0)'
    assert p["stateCountyRemodelRate"] is None


def test_clearing_the_pill_reverts_the_cell_and_the_state(result):
    c = result["cleared"]
    assert c["epoxy"] == '=IF(D6="yes",0.1,0)'
    assert c["stateHasCounty"] is False
    assert c["stateHasRemodelRate"] is False
    assert c["pillCleared"] is True


def test_a_draft_saved_before_this_fix_self_heals_on_reopen(result):
    """Before this fix shipped, a draft could have `state.county_remodel_rate` set with nothing
    in `cellValues` for these addresses at all — the exact shape a pre-fix save left behind. The
    page-load restore path must replay the override, not just redraw the pill."""
    s = result["staleDraftSelfHeals"]
    assert s["epoxy"] == '=IF(D6="yes",0.0935,0)'
    assert s["polish"] == '=IF(D6="yes",0.0935,0)'


def test_the_toggle_reference_is_local_to_each_sheet(result):
    """Epoxy/Polish read D6, every Gyp variant reads D8 — the same local, unqualified reference
    Kyle's own original placeholder formula used (Polish!D6 and each Gyp D8 are formula mirrors
    of Epoxy!D6, confirmed by direct inspection of the workbook), so no cross-sheet qualifier is
    needed or correct here."""
    t = result["toggleShape"]
    assert t["epoxy"].startswith('=IF(D6=')
    assert t["polish"].startswith('=IF(D6=')
    assert t["gyp"].startswith('=IF(D8=')


# ─── The four sheets the first fix missed (2026-09-02) ─────────────────────


def test_seal_leveling_and_epoxy_blank_get_the_picked_rate(result):
    """Three sheets the previous target list left out, on the strength of a comment claiming they
    had no remodel-tax line. All three hold `=IF(D6="yes",0.1,0)` in the shipped workbook, and
    Seal is a priced role (`BASE_ROLE` via `SEAL_SHEETS`) whose number reaches the customer as a
    proposal price line — so every sealer bid was taxed at Kyle's 10% placeholder instead of the
    ~9.1-9.7% the picker had already looked up and displayed."""
    p = result["previouslyMissedLayouts"]
    assert p["seal"] == '=IF(D6="yes",0.0935,0)'
    assert p["leveling"] == '=IF(D6="yes",0.0935,0)'
    assert p["epoxyBlank"] == '=IF(D6="yes",0.0935,0)'


def test_seal_with_joints_is_deliberately_left_as_a_mirror(result):
    """`Seal (+Jnts)!B75` is `=Seal!B75`, so writing Seal already carries it. Writing a literal
    there too would replace the mirror and let the two sheets drift apart independently — the
    exact divergence found in Kyle's own filed workbooks. This absence is a decision, so it is
    asserted rather than left to whoever next extends the list."""
    assert result["sealJointsLeftAsMirror"]["written"] is False


def test_a_tab_copied_before_the_county_was_picked_still_gets_the_rate(result):
    """Copies are how a priced option gets in front of a customer, and the backend clones them
    from the pristine template (`estimate_writer._create_copied_tabs`), so a copy's rate cell
    arrives at 10%. `addCopy` replaying the source's `cellValues` covers "pick, then copy" as a
    side effect — it can do nothing for "copy, then pick", which is this test. Before the fix
    that sequence shipped a 10% option beside a correct base bid."""
    c = result["copyThenPick"]
    assert c["copy1"] == '=IF(D6="yes",0.0935,0)'    # copy of Epoxy  → its layout's B81
    assert c["copy2"] == '=IF(D6="yes",0.0935,0)'    # copy of Polish → its layout's B75
    assert c["base"] == '=IF(D6="yes",0.0935,0)'     # and the base tab is untouched by all this


def test_a_copy_of_a_copy_resolves_through_the_chain_to_its_template_layout(result):
    """The address depends on the LAYOUT, not the tab: B81 for an epoxy-derived tab, B75 for a
    polish- or seal-derived one. A copy of a copy has to walk the chain (`layoutIdFor`) to find
    it — the same resolution `test_cell_lock.py::test_copy_of_copy_resolves_through_chain`
    already pins for cell protection."""
    c = result["copyChain"]
    assert c["copy2"] == '=IF(D6="yes",0.0935,0)'    # Copy2 → Copy1 → Epoxy → B81
    assert c["copy3"] == '=IF(D6="yes",0.0935,0)'    # Copy3 → Seal → B75
    # 10 template layouts + 3 copies, each written exactly once. A `seen` set guards the overlap:
    # the base tabs in the tab bar are the same ids as the layouts, and writing one twice would
    # be harmless here but would hide a double-write bug on a real structural translation.
    assert c["targetCount"] == 13


def test_picking_while_sitting_on_a_copied_tab_keeps_the_tab_on_screen(result):
    """The regression the four tests above created, caught by a browser and not by any of them.

    Once copies became rate targets, the override's own grid refresh reached a copied tab for the
    first time — and it refreshed by discarding the active sheet's cache and re-fetching it. A copy
    has no server-side worksheet (`addCopy` builds `sheetCache[newId]` client-side from its
    source), so `GET /api/sheet/Copy1` 404s and `showSheet`'s `!r.ok` branch paints
    "Failed to load Copy1" over a tab whose cache is now gone. Picking a county with a copy open —
    an ordinary sequence — blanked the option the estimator was looking at.

    For a client-side-only cache, a refetch is data loss, not a round trip. Every one of cases 1-9
    sits on a base tab, where the refetch happens to succeed, which is exactly why they were all
    green while staging carried the bug."""
    c = result["pickedWhileOnACopy"]
    assert c["copy1"] == '=IF(D6="yes",0.0935,0)'   # the rate still lands
    assert c["cachePreserved"] is True              # ...without destroying the tab to deliver it
    assert c["gridRefreshedFor"] == ["Copy1"]       # ...and the copy redraws with the new number
