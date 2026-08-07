"""The polish estimate page: step 2 for polish jobs, without the spreadsheet.

The page is a form over the Polish worksheet. HyperFormula recalculates the worksheet's OWN
formulas and the bid is read back out of D82, so the figure on screen is the figure in the
downloaded .xlsx by construction rather than by reconciliation.

What these tests protect is the handful of things that would break that guarantee silently:

  * **Loading only the Polish sheet.** Its formulas reference `Epoxy!` (the whole job header
    mirrors it) and `validation!` (pad and tooling rate bands). Load Polish alone and those
    resolve to nothing while the page still shows a confident-looking number.
  * **Skipping the named expressions.** Product blocks resolve to #NAME? without them, and
    HyperFormula rejects names shaped like a cell reference ("Glaze4") so they need aliasing.
  * **Replacing `cell_values` instead of merging.** That map is what done.js posts to
    /api/generate. Replacing it drops the Epoxy!* entries a job carries from before its work
    type changed.
  * **Re-implementing a rate.** The moment a price lives on this page too, the screen and the
    file can disagree, which is the whole thing this design exists to avoid.
  * **Hijacking the existing flow.** Hanz asked for a standalone beta: the old Estimate Review
    must still work and still be reachable.
"""
import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"


@pytest.fixture()
def html():
    return (FRONTEND / "polish-estimate.html").read_text(encoding="utf-8")


@pytest.fixture()
def js():
    return (FRONTEND / "js" / "polish-estimate.js").read_text(encoding="utf-8")


# ── the shell ─────────────────────────────────────────────────────────────────
def test_the_page_loads_the_engine_and_both_scripts_in_order(html):
    """xl-core must come before the page, and the core module before the page that calls it."""
    order = [html.index(x) for x in ("hyperformula", "/auth.js", "/shared.js",
                                    "/js/xl-core.js", "/js/polish-estimate-core.js",
                                    "/js/polish-estimate.js")]
    assert order == sorted(order), "script tags are out of order"


def test_hyperformula_is_pinned_with_an_integrity_hash(html):
    """A CDN script that can change under us would change every bid."""
    tag = re.search(r'<script src="[^"]*hyperformula[^"]*"[^>]*>', html).group(0)
    assert "hyperformula@2.7.1" in tag, "unpinned HyperFormula"
    assert "integrity=" in tag and "crossorigin=" in tag


def test_no_inline_scripts(html):
    """CSP drops script-src 'unsafe-inline'; an inline block would silently not run."""
    assert "<script>" not in html.replace("<script src", "<script-src")


def test_the_stepper_keeps_the_existing_four_steps(html):
    """Hanz: "this should still have the intake from up to the files." The journey is unchanged;
    only the estimating surface is rebuilt."""
    for step in ("1 · Intake", "2 · Estimate", "3 · Proposal", "4 · Files"):
        assert step in html, step
    assert "/proposal-review.html" in html and "/done.html" in html


def test_the_bid_bar_names_the_cell_it_reads(html):
    """A number with no provenance is a number nobody trusts. D82 is checkable in the file."""
    assert "D82" in html


# ── the engine ────────────────────────────────────────────────────────────────
def test_every_sheet_is_loaded_not_just_polish(js):
    """The polish formulas reference Epoxy! and validation!. Loading Polish alone leaves them
    unresolved while the page still shows a plausible total."""
    assert "/api/sheets" in js, "the sheet list is never fetched"
    assert re.search(r'createEngine\(\s*sheetNames\s*\)', js), (
        "the engine is built for something other than the full sheet list")
    assert re.search(r'sheetNames\.map', js), "sheets are not all loaded"


def test_named_expressions_are_registered_with_an_alias_fallback(js):
    """Without these the product blocks are #NAME?. HyperFormula rejects "Glaze4", so the
    alias path is not optional."""
    assert "/api/named-expressions" in js
    assert "isItPossibleToAddNamedExpression" in js
    assert "nameAliases" in js


def test_the_engine_waits_for_the_auth_token(js):
    """Every /api call is auth-gated. Firing before the token 401s and the page shows an error
    that looks like a server fault — the Bid Calendar shipped exactly that bug."""
    i = js.index("async function init")
    assert "TWAuth" in js[i:i + 400] and "ready" in js[i:i + 400]


def test_the_saved_cell_values_are_replayed_before_the_page_pushes_its_own(js):
    """Otherwise a returning estimator loses everything they typed last time.

    Compares against the FIRST pushCells() inside init, not the next one after the replay loop —
    searching forward from the loop still finds the later call and passes even when an extra one
    has been inserted above it, which is exactly how this test first failed to bite."""
    init = js[js.index("async function init"):]
    replay = init.index("for (var addr in cellValues)")
    first_push = init.index("pushCells();")
    assert replay < first_push, (
        "init calls pushCells() before replaying the saved cell values, so anything typed on a "
        "previous visit is overwritten by this page's defaults")


# ── the .xlsx contract ────────────────────────────────────────────────────────
def test_cell_values_are_merged_never_replaced(js):
    """done.js posts this whole map to /api/generate. Replacing it drops the Epoxy!* entries a
    job carries from before its work type changed."""
    i = js.index("function saveSoon")
    block = js[i:i + 900]
    assert "Object.assign({}, TW.getState().cell_values || {}, cellValues)" in block, (
        "cell_values looks replaced rather than merged")


def test_the_page_writes_the_same_store_the_generate_path_reads(js):
    assert "cell_values" in js, "nothing reaches /api/generate"
    assert "polish_estimate" in js, "the page's own model is not persisted"


def test_the_bid_is_read_from_the_worksheet_not_computed_here(js):
    i = js.index("function bid()")
    block = js[i:i + 420]
    assert "P.CELLS.total" in block and "read(" in block
    assert "*" not in block.split("return")[1].split("}")[0], (
        "the bid looks arithmetically derived; it must be read out of the sheet")


def test_the_page_holds_no_rates_of_its_own(js):
    """A price here is a second opinion waiting to drift from the workbook."""
    body = "\n".join(l for l in js.splitlines() if not l.strip().startswith("//"))
    for rate in ("3.5", "4.5", "0.07", "0.14", "385", "32.20", "48.00", "1.2", "0.9", "1.02"):
        assert rate not in body, (
            "%r looks like a rate copied out of the worksheet" % rate)


# ── the seven sub-steps ───────────────────────────────────────────────────────
def test_there_are_seven_sub_steps_one_per_container(js):
    """Hanz: "each container is a substep", plus a Review at the end."""
    i = js.index("var STEPS = [")
    block = js[i:js.index("];", i)]
    keys = re.findall(r'key:\s*"(\w+)"', block)
    assert keys == ["areas", "conditions", "materials", "labour", "adds", "options", "review"], keys


def test_every_step_has_a_panel(js):
    i = js.index("var PANELS = [")
    panels = re.findall(r'(\w+Panel)', js[i:js.index("];", i)])
    assert len(panels) == 7, panels


def test_the_step_counter_is_generated_not_hardcoded(js):
    """Hand-typed "Step 3 of 6" labels went stale the moment a container was split in two — which
    is exactly what happened to the mockup.

    Checks for the ABSENCE of a literal count as well as the presence of STEPS.length: a
    hardcoded label sitting next to the generated one leaves both in the source, so presence
    alone does not bite."""
    block = js[js.index("function shell"):][:900]
    assert "STEPS.length" in block, "the total is not derived from the step list"
    assert not re.search(r'of\s+\d', block), (
        "a literal step count is being rendered; it will go stale the next time a container is "
        "split or merged")


def test_the_rail_shows_what_still_needs_attention(js):
    """The point of splitting into steps is losing the see-everything view; the rail is what
    gives it back."""
    i = js.index("function paintRail")
    block = js[i:i + 900]
    assert "stepStatus" in block and '"✓"' in block


# ── areas measure, one system prices ─────────────────────────────────────────
def test_the_system_is_chosen_once_for_the_bid_not_per_area(js):
    """The Polish tab has ONE selector — Q10/R10/V10 all key off F36 — so a per-area system
    dropdown would silently misprice. The approved mockup had one; this must not."""
    i = js.index("function areasPanel")
    block = js[i:js.index("function conditionsPanel")]
    assert block.count('data-m="system"') == 1, (
        "the system selector is inside the per-area loop, so each area appears to price its own")
    assert 'data-m="system"' not in block[:block.index('data-add-area')], (
        "the system selector is rendered per area rather than once for the bid")


def test_added_lines_are_capped_at_the_worksheet_capacity(js):
    """Four spare rows exist. A fifth line must be refused with a reason, not written somewhere
    that does not bill."""
    assert "slotsLeft" in js
    i = js.index("data-add-line-new")
    block = js[i:i + 700]
    assert "slotsLeft" in block or "disabled" in block


def test_a_line_with_no_worksheet_row_says_so_on_screen(js):
    i = js.index("function materialsPanel")
    block = js[i:js.index("function labourPanel")]
    assert "no room in the worksheet" in block


# ── the beta runs beside the old page, not instead of it ──────────────────────
def test_the_old_estimate_review_still_exists_and_is_untouched_as_a_route():
    """Hanz chose a standalone beta so a polish bid can be priced both ways and compared."""
    assert (FRONTEND / "estimate-review.html").exists()
    index_js = (FRONTEND / "js" / "index.js").read_text(encoding="utf-8")
    assert "/estimate-review.html" in index_js, (
        "intake was re-routed to the beta; the old path must stay the default while it is a beta")


def test_nothing_is_advertised_above_the_estimate_grid():
    """Estimate Review IS the spreadsheet, so the spreadsheet gets the viewport.

    A polish-beta banner used to sit above the grid — roughly 60px of pink, on the one screen
    where the estimator is reading rows of numbers. Hanz, 2026-08-07: "I can barely see the
    sheet. The Estimate sheet is supposed to be the majority viewport."

    The beta is reached from the sidebar instead (Polish Estimate · BETA), which is where the
    Item Library and the Info Sheet announce themselves too. This test is here so the next
    feature that wants a launch moment does not take it from the grid.
    """
    html = (FRONTEND / "estimate-review.html").read_text(encoding="utf-8")
    body = html[html.index("<main>"):]
    banner = re.search(r'<(div|section|aside)[^>]*\bid="[^"]*(banner|promo|announce|beta)[^"]*"',
                       body, re.I)
    assert not banner, (
        "something is advertising itself above the grid again: %s" % (banner and banner.group(0)))

    review = (FRONTEND / "js" / "estimate-review.js").read_text(encoding="utf-8")
    code = "\n".join(l for l in review.splitlines() if not l.strip().startswith("//"))
    assert "polish-beta-banner" not in code, "the removed banner is still being unhidden"


def test_the_sidebar_entry_is_marked_beta_and_has_its_own_glyph():
    auth = (FRONTEND / "auth.js").read_text(encoding="utf-8")
    assert 'navItem("/polish-estimate.html"' in auth
    i = auth.index('navItem("/polish-estimate.html"')
    assert "BETA" in auth[i:i + 120]
    glyphs = re.findall(r'navItem\("[^"]+", "([^"]+)"', auth)
    assert len(glyphs) == len(set(glyphs)), "two sidebar items share a glyph: %s" % glyphs
