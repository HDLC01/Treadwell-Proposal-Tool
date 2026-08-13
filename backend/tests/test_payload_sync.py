"""The customer's PDF follows the pricing, not the last time somebody pressed Continue.

Hanz, 2026-08-13 evening, on a Test-tab project:

    "I tried to resend and inversed the bids it doesnt update in the portal the new PDF"
    "Not the same?"

WHAT WAS ACTUALLY WRONG. That morning's fix pinned the customer's page to a revision snapshot, and
the page was right. The PDF was not, because one revision describes the same pricing TWICE:

    data["rooms"]              → what the portal PAGE renders
    data["proposal_payload"]   → what the customer's PDF is re-rendered from, on demand

`proposal_payload` was written by exactly ONE line in the entire frontend: the Proposal step's
Continue handler. Inverting the base bid in the Pricing sidebar went through `rebuildPricing`,
which updated `rooms` / `base_tab_id` / `proposal_lump_sum` and left the payload frozen. Leaving
by the "4 · Files" step pill skipped Continue entirely, so the resend snapshotted a blob whose top
half said "Epoxy base, $18,670" and whose document half still said "Polish base, $13,265" — and
nothing anywhere noticed, because the drift warning compared the page's fields to the page's
fields.

WHY EXECUTED. Every claim here is a comparison between two runs of real code: "the payload's money
equals a freshly computed money", "the narrative did not move", "the persisted blob a reload reads
carries the new pricing". A source assertion that `syncPayloadPricing` is CALLED would pass with a
whitelist that misses half the price block — the same customer-visible bug wearing a new hat. The
completeness case DERIVES the required key set by diffing two real computes rather than restating
the list, so adding a token to the mapping and forgetting it here fails the suite.

THE ONE THING THE HARNESS STUBS is the document editor (templateVersion / collectOverrides /
collectBoxOverrides / sheetSystems), which needs a mounted template. They are injected as seams so
the tests can observe WHEN the sync reaches for them — never for a plain re-price, always when the
template itself changed. Everything in the pricing path is the shipped code.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "payload-sync-harness.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

# The estimator's own words, which a pricing change must never touch.
NARRATIVE = {
    "scope_notes": "Grind and polish per spec.",
    "schedule_notes": "Two mobilizations.",
    "exclusions": "Moisture mitigation excluded.",
    "work_notes": "Call Kyle before pour.",
    "system_name": "Treadwell Polished Concrete",
    "texture": "Salt & pepper",
    "estimator_name": "Kyle",
}


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── the incident ─────────────────────────────────────────────────────────────
@needs_node
def test_a_base_flip_moves_the_document_payload(ran):
    """His exact flip: Polish base $13,265 → Epoxy base $18,670. The document half has to arrive
    at the same arrangement as the page, or the customer reads a superseded proposal."""
    i = ran["incident"]
    assert i["returnedPayload"], "syncPayloadPricing refused to patch a real payload"
    assert i["docBase"] == "Epoxy" and i["docBaseTotal"] == 18670
    assert i["valuesBaseTabId"] == "Epoxy" and i["valuesLumpSum"] == 18670
    assert i["valuesRoomsBase"] == "Epoxy", "values.rooms still names the old base"


@needs_node
def test_every_line_of_the_price_block_is_rewritten(ran):
    """The PRICE block is what a customer signs. All of it moves, including the itemised breakdown
    the epoxy layout has to make add up: base bid + material tax = total."""
    i = ran["incident"]
    assert i["totalLabel"] == "$18,670.00 – Total"
    assert i["lumpSumLabel"] == "$18,670.00 – Epoxy Flooring as described above"
    assert i["totalFormatted"] == "$18,670.00"
    assert i["baseBidFormatted"] == "$18,060.00"
    assert i["materialTaxFormatted"] == "$610.00"


@needs_node
def test_the_area_the_proposal_quotes_follows_the_base_tab(ran):
    """SF is sheet-first, resolved from the base tab's own cells — so a flip changes the square
    footage the proposal quotes, not only the price. 5,000 sf of polish became 7,400 of epoxy."""
    i = ran["incident"]
    assert i["epoxySf"] == "7,400" and i["polishSf"] == "0"
    assert i["areaDescription"] == "~7,400 sf of epoxy flooring"


@needs_node
def test_the_estimators_words_are_left_alone(ran):
    """A pricing flip must not silently rewrite the narrative. This is what the whitelist buys —
    the alternative (patch everything computeTokenValues returns) would let a sidebar click revert
    scope text the estimator typed, which is the bug class we fixed earlier this week."""
    assert ran["incident"]["narrative"] == NARRATIVE


# ── the completeness guarantee ───────────────────────────────────────────────
@needs_node
def test_the_whitelist_covers_every_token_a_flip_changes(ran):
    """DERIVED, NOT RESTATED. Compute the token mapping before and after the flip; every key whose
    value moved must end up in the payload. A token added to computeTokenValues and forgotten in
    PAYLOAD_PRICING_KEYS shows up here as a hole instead of as a wrong number on a customer's
    proposal months later."""
    c = ran["completeness"]
    assert c["changed"], "the fixture flip changed nothing — the case has stopped testing anything"
    assert c["missed"] == [], (
        "these keys change with the pricing and are not reaching the document: " +
        ", ".join(c["missed"]))


# ── the template, not just the numbers ───────────────────────────────────────
@needs_node
def test_the_template_follows_the_base_role(ran):
    """`work_type` is derived from the base tab's ROLE and picks which .docx the customer receives.
    A frozen "polish" here is why his PDF's base line still read "Polished Concrete Flooring": the
    old template, rendered with its old prices. Found by the completeness diff above, which
    reported `work_type` as the one changed key the sync was leaving behind."""
    t = ran["templateFollows"]
    assert t["workType"] == "epoxy" and t["valuesWorkType"] == "epoxy"
    assert t["audience"] == "Direct"


@needs_node
def test_a_template_change_recollects_the_overrides_it_invalidates(ran):
    """Paragraph and box overrides are {id: text} against ONE template's block walk. Replaying
    them onto a different .docx would land the estimator's words on whatever paragraph happens to
    share that id, so the template swap has to re-collect from the (already reloaded) editor."""
    t = ran["templateFollows"]
    assert t["calls"]["collectOverrides"] == 1
    assert t["calls"]["collectBoxOverrides"] == 1
    assert t["templateVersion"] == "tpl-v9", "the payload kept the old template's version stamp"
    assert t["paragraphOverrides"] == [{"id": 7, "text": "edited on the NEW template"}]
    assert t["boxOverrides"] == {"3": {"w_pt": 300}}


@needs_node
def test_a_plain_reprice_never_touches_the_narrative(ran):
    """The common case, and the one that must stay boring: same template, new money. Re-collecting
    overrides here would let a price edit clobber unsaved document text."""
    s = ran["samePriceSameTemplate"]
    assert s["calls"]["collectOverrides"] == 0
    assert s["calls"]["collectBoxOverrides"] == 0
    assert s["templateVersion"] == "tpl-OLD"
    assert s["paragraphOverrides"] == [{"id": 1, "text": "hand written"}]
    assert s["totalFormatted"] == "$14,000.00", "the pricing did not sync"


@needs_node
def test_an_unmounted_editor_still_lets_the_pricing_through(ran):
    """A flip can land before the template finishes loading. Leaving the previous overrides for
    the backend's template_version guard to drop is recoverable; throwing out of the sidebar's
    save is not."""
    e = ran["editorUnavailable"]
    assert e["threw"] is False
    assert e["workType"] == "epoxy"
    assert e["pricingStillSynced"] == "$18,670.00"
    assert e["paragraphOverrides"] == [{"id": 1, "text": "from the old template"}]


@needs_node
def test_an_unloaded_template_never_blanks_the_version_stamp(ran):
    """`rebuildPricing` runs at PAGE INIT, before the editor resolves a template version. The
    backend reads an EMPTY `template_version` as "legacy caller — apply the overrides", so writing
    "" here would land the previous template's edits on the new template's paragraphs. Leaving the
    stored, now-mismatched version is what makes the backend drop them instead."""
    t = ran["templateNotLoadedYet"]
    assert t["workType"] == "epoxy", "the template pick must still follow the base role"
    assert t["templateVersion"] == "tpl-POLISH", "the version stamp was blanked"
    assert t["paragraphOverrides"] == [{"id": 1, "text": "captured on polish"}]
    assert t["calls"]["collectOverrides"] == 0
    assert t["pricingStillSynced"] == "$18,670.00"


@needs_node
def test_the_work_section_systems_follow_the_base_tab(ran):
    """The WORK rows are resolved from the base tab's own cells, so they move with a flip. The
    "Options" placeholder row is filtered the same way continueToDone filters it."""
    s = ran["sheetSystems"]
    assert s["resolved"] == [{"name": "Epoxy System", "sf": 7400, "lf": 120}]
    assert s["keptOnFailure"] == [{"name": "Kept", "sf": 1}], (
        "a failed resolution emptied the WORK rows instead of leaving the previous ones")


# ── the no-op and failure paths ──────────────────────────────────────────────
@needs_node
@pytest.mark.parametrize("shape", ["missing", "nul", "str", "noValues", "badValues"])
def test_no_payload_means_no_op(ran, shape):
    """Before the first Continue there is nothing stale to correct, and the Done page builds a
    fresh payload from raw state. Returning null keeps `proposal_payload` out of the persist
    entirely rather than writing a half-built one."""
    assert ran["noPayload"][shape] is None


@needs_node
def test_a_failing_compute_does_not_break_the_save(ran):
    """The sidebar's job is to persist pricing. If the token mapping throws on a half-built state,
    the document sync is what we can afford to lose."""
    c = ran["computeThrows"]
    assert c["threw"] is False and c["result"] is None
    assert c["payloadUntouched"] == "$13,265.00 – Total", "a failed sync half-wrote the payload"


# ── the other things that change the price block ─────────────────────────────
@needs_node
@pytest.mark.parametrize("mode,phrase", [
    ("INCLUDED", "(Remodel Tax AND material sales tax INCLUDED)"),
    ("BROKEN_OUT", ""),
    ("EXCLUDED", "(tax exempt)"),
])
def test_the_tax_treatment_reaches_the_document(ran, mode, phrase):
    """The dropdown changes the parenthetical a customer reads and which of the three price lines
    the backend fills. It travels through the FORM, not through rooms — which is why the debounced
    form persist syncs as well as the sidebar."""
    assert ran["taxFlip"][mode]["base_tax_phrase"] == phrase
    assert ran["taxFlip"][mode]["sales_tax_handling"] == mode


@needs_node
def test_narrowing_a_combo_to_one_base_clears_the_two_price_lines(ran):
    """A combo with no base prints BOTH systems as options. Choosing one base makes that block
    wrong, and leaving the old lines in the payload prints two prices in a one-price proposal."""
    c = ran["comboNarrowing"]
    assert len(c["comboBefore"]) == 4, c["comboBefore"]
    assert any("Option 1" in l for l in c["comboBefore"])
    assert c["afterNarrowing"] == []


@needs_node
def test_the_remodel_tax_line_appears_and_disappears_with_the_tax(ran):
    """`{{#remodel}}` is a conditional block: a leftover line prints a $0.00 Kansas Remodel Tax
    row, and a missing one makes the three price lines stop summing to the bid."""
    r = ran["remodelLine"]
    assert r["on"] == [{"amount_formatted": "$1,234.50"}]
    assert r["off"] == []


@needs_node
def test_hand_edited_price_lines_survive_the_sync(ran):
    """`price_overrides` are the estimator's own wording for a price line. Dropping them would
    restore computed text they deliberately replaced; a garbage value must not travel."""
    o = ran["overrides"]
    assert o["kept"] == {"lines": {"base": "Flat fee, all in"}}
    assert o["garbageBecomes"] == {}


@needs_node
def test_gyp_area_buckets_reach_the_document(ran):
    """Gyp quotes three thicknesses as separate SF buckets and the template prints those tokens
    directly, so its area numbers live in keys nothing else uses. The whitelist carries them; this
    is the case that proves they move rather than sitting in the list unexercised."""
    g = ran["gyp"]
    assert (g["soft"], g["hard"], g["corridor"]) == ("27,825", "4,100", "900")
    assert g["sqft"] == "32,825", "the total SF the proposal quotes"
    assert g["area"] == "~32,825 sf of gypsum underlayment"
    assert g["total"] == "$24,000.00"


# ── the wiring ───────────────────────────────────────────────────────────────
@needs_node
def test_the_sidebar_and_the_form_both_call_the_sync(ran):
    """A correct sync that nothing calls is the bug unchanged. Both persist paths need it: the
    sidebar (base flips, option toggles) and the debounced form (tax treatment)."""
    w = ran["wiring"]
    assert w["rebuildCallsSync"], "rebuildPricing does not sync the document payload"
    assert w["formPersistCallsSync"], "the debounced form persist does not sync"
    assert w["syncRunsAfterTotalIsWritten"], (
        "the sync runs before #tb-total is written — computeTokenValues reads the lump sum from "
        "that element, so it would compute the PREVIOUS total")


@needs_node
def test_the_persist_names_the_payload_key(ran):
    """THE SNAPSHOT TRAP. `state` is a one-shot TW.getState(); TW.setState merges into a FRESH
    localStorage read. Mutating the nested payload is not persistence — the key has to be named in
    the setState argument or the whole sync is lost on reload."""
    assert ran["wiring"]["rebuildPersistsPayload"]


@needs_node
def test_the_files_pill_rebuilds_the_whole_payload(ran):
    """The "4 · Files" step pill was a plain link to done.html, so it reached the Done page without
    running Continue — the exact route he took. Routing it through continueToDone means a same-tab
    exit always rebuilds the FULL payload, narrative included.

    Executed, because a source check for `continueToDone(e)` is satisfied by the function's own
    declaration: `async function continueToDone(e)`. A mutation that deleted the listener outright
    survived that check."""
    p = ran["wiring"]["filesPill"]
    assert "click" in p["wiredEvents"], "nothing listens for a click on the Files pill"
    assert p["prevented"] == 1, "the browser still follows the href, skipping Continue"
    assert p["continued"] == 1, "the click does not run continueToDone"


@needs_node
def test_the_synced_payload_survives_a_reload(ran):
    """End to end through the REAL shared.js: seed a draft, take the page's one-shot snapshot,
    flip the base, sync, persist in rebuildPricing's exact call shape, then read back what the
    next page load would see. This is the case that fails if the persist line is subtly wrong."""
    e = ran["endToEnd"]
    assert e["pageBase"] == "Epoxy", "the page's own half did not persist"
    assert e["docBase"] == "Epoxy", "the document half was lost between setState and getState"
    assert e["docTotalFormatted"] == "$18,670.00"
    assert e["docWorkType"] == "epoxy"
    assert e["docNarrativeKept"] == NARRATIVE["scope_notes"]
