"""Phase 10 of the v2 estimating program: a bid priced on several workbook tabs.

NO NEW WORK TYPE IS TURNED ON HERE AND NO SAVED BID'S TOTAL MOVES. This is the groundwork Epoxy, Combo and
Gyp pricing need, in the model and in the engine:

  * `sectionsOf` (bid-model.js): the ONE place that knows the root section (Polish, as the model has always
    held it) from `tabs` (every other section, keyed by workbook tab id). By reference. A section must say its
    layout, kind and profile stamp, and nothing is assumed ("polish" included).
  * `priceSection` / `priceTabs`: each section is priced by the engine with the profile it was SAVED with and
    the rates it KEPT. `snapshotRates` (bid-engine.js) is what a section keeps when it is first used
    (`activateSection`). An absent snapshot means the profile's built-ins, never the live Markups rules, so a
    saved bid does not reprice when somebody edits the Markups page.
  * `composePricingSnapshot`: the one pure function that writes the derived keys the proposal side reads.
    For a bid with one section (all of them today) it writes exactly what the page has always written;
    for several sections it writes the complete set (priced_tabs marked v2, the lump sum summed AFTER each
    section's own gross profit, the taxes, the area, the costs). `buildSavePatch` uses it for both saves.
  * `seedNewSections`: the estimate page's new-bid seeding, moved out of its init() and made per section.
  * the estimate page draws a strip that switches section ONLY when there is more than one.

HOW THE DECISION "A NEW SECTION HONOURS A FILED RULE, A SAVED ONE NEVER READS ONE" IS PINNED. The live data
dump of 2026-10-12: production `markup_rules` holds one row, (polish, bond, '1%', applies), and staging has
(global, fees_textura, '0', applies) and (gyp, soft_costs, '', not applied). So:
  - a section with no snapshot (every saved bid) prices at the built-ins even with the production rule
    filed, and a bond rule is not taken by any section (bond is 0 and unwired until Kyle decides);
  - a section activated AFTER a rule was filed keeps it as text, and editing the Markups page later moves
    neither;
  - a blank or unreadable filed rule is the built-in with a note, never $0.

EVERYTHING RUNS CODE. tests/js/multi-section-harness.js executes the real model and engine and the real
estimate page; tests/js/save-patch-golden-harness.js records what the page SAVES and what a NEW bid opens
holding, and tests/fixtures/save_patch_golden.json is that record cut from origin/staging 28a5d1f BEFORE this
phase changed a line. The last tests break a scratch copy of the code in many ways and require each law to
notice, and `break_source` refuses an anchor that is not in the file exactly once.
"""
import json
import pathlib

import pytest

from _golden_support import break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
FRONTEND = TESTS.parents[1] / "frontend"
HARNESS = TESTS / "js" / "multi-section-harness.js"
GOLDEN_HARNESS = TESTS / "js" / "save-patch-golden-harness.js"
GOLDEN = TESTS / "fixtures" / "save_patch_golden.json"

SCRATCH_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js",
                 "js/bid-profiles.js", "js/markup-core.js", "js/library-core.js", "js/library-picker.js",
                 "js/work-types.js", "js/excel-math.js", "js/epoxy-takeoff.js", "js/gyp-takeoff.js"]


def _run(script, frontend=FRONTEND):
    proc = run_node(script, frontend)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    require_node()
    return _run(HARNESS)


@pytest.fixture(scope="module")
def recorded():
    require_node()
    return _run(GOLDEN_HARNESS)


@pytest.mark.parametrize("section", ["sections", "newSection", "activation", "noReprice", "pricing", "composer",
                                     "seeding", "switcher", "pins", "page"])
def test_no_section_of_the_harness_failed(ran, section):
    """A section that threw reports it instead of crashing, so running this over a tree without the
    functions fails an assertion with a reason."""
    assert "error" not in ran[section], ran[section].get("error")


# ── 0. nothing a saved or new Polish bid does has moved ──────────────────────────────────────────
def test_what_the_page_saves_and_what_a_new_bid_opens_holding_is_the_golden_byte_for_byte(recorded):
    """The golden was cut from origin/staging 28a5d1f before this phase touched the model or the page.
    Every saved-bid fixture the ratchet pins, opened plain and over a library full of defaults, saved by
    the 600 ms timer and by `pagehide` (the whole blob each wrote), and seven NEW or part-saved bids (a library of
    defaults, an empty one, two SF boxes, intake's condition cells, no SF, a saved bid with a blank takeoff,
    and the model the beta intake mints), each
    as the model the page holds after init() and the blob its first save writes. Compared as JSON text, so
    key order is part of it.

    Mutations: see test_the_golden_goes_red_when_the_code_changes."""
    want = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert want["meta"]["commit"] == "28a5d1f"
    # The 26 `saved` records are still the 28a5d1f ones, byte for byte. The seven `newBid` records were
    # re-recorded on 2026-10-12 (meta.newBid_recut): a new bid's Labor step opens with every quantity empty.
    assert "newBid_recut" in want["meta"]
    assert len(want["golden"]["saved"]) == 26 and len(want["golden"]["newBid"]) == 7
    assert json.dumps(recorded) == json.dumps(want["golden"])


def test_the_golden_is_not_vacuous():
    """The recorded saves are real: every one wrote the five keys in the page's order, the new bids were
    really seeded (labor lines from the library, Fees + Textura, the dye answer), and the two save paths
    wrote the same blob."""
    g = json.loads(GOLDEN.read_text(encoding="utf-8"))["golden"]
    for name, got in g["saved"].items():
        assert got["autosave"] is not None and got["pagehide"] is not None, name
        assert "polish_estimate" in got["autosave"] and "computed_bid" in got["autosave"], name
        assert got["autosave"] == got["pagehide"], name
        assert "priced_tabs" not in got["autosave"], name
    lib = g["newBid"]["library"]["model"]
    assert [r["label"] for r in lib["labor"]] == ["Polishing", "Mock-up", "Joint filler", "Travel Labor", "Tint"]
    assert lib["conditions"]["dye"] is True and g["newBid"]["empty"]["model"]["conditions"]["dye"] is False
    assert g["newBid"]["twoSystems"]["model"]["takeoff"][-2:][0]["measurement"] == 8250
    assert g["newBid"]["mintedByIntake"]["saved"] is not None


# ── 1. sections ──────────────────────────────────────────────────────────────────────────────────
def test_a_bid_with_no_tabs_has_exactly_one_section_and_it_is_the_model_itself(ran):
    s = ran["sections"]["single"]
    assert s == {"length": 1, "tab": "Polish", "root": True, "isModel": True, "kind": "base",
                 "profile": "polish-legacy@1", "layout": "polish", "role": "polish"}


def test_sections_come_root_first_then_tabs_in_the_order_they_were_added_and_by_reference(ran):
    m = ran["sections"]["multi"]
    assert m["tabs"] == ["Polish", "Epoxy", "Seal"]
    assert m["kinds"] == ["base", "base", "option"]
    assert m["roles"] == ["polish", "epoxy", "seal"] and m["layouts"] == ["polish", "epoxy", "seal"]
    assert m["profiles"] == ["polish-legacy@1", "epoxy@1", "seal@1"]
    assert m["byRefTab"] == 77 and m["byRefRoot"] == 5, "a write through an entry must be a write to the model"


def test_an_off_section_is_part_of_the_model_and_not_of_the_bid(ran):
    s = ran["sections"]
    assert s["activeSkipsOff"] == ["Polish", "Epoxy"]
    assert s["rootOff"] == "off"


def test_the_roots_profile_is_always_the_legacy_one_whatever_the_root_keys_say(ran):
    """A `profile` at the root other than polish-rev2@1 (and a `rates` snapshot) is not read: the root prices at
    polish-legacy@1's built-ins, so no saved bid's total can move. The root's `kind` IS read since Sheets phase 1, and
    that is the one thing this test's model also says (an option), which moves no profile."""
    assert ran["sections"]["rootProfileKeyIsReserved"] == "polish-legacy@1"


def test_the_page_prices_a_gyp_section_from_its_takeoff(ran):
    """The page's sectionMaterial answered a number for every tab. A Gyp section needs the gyp-split inputs,
    so it gets them (js/gyp-takeoff.js splits the takeoff into gypsum, extras, sand and sound mat): a priced
    section with a material, and a combined price, never a $0 material. This section's one row is not an area, so
    the sheet buys it as an extra."""
    g = ran["page"]["gypOnPage"]
    assert g["priceable"] is True and g["material"] > 0 and g["total"] > 0
    assert g["computed"] is True and g["lump"] > 0


def test_a_root_kind_of_option_is_read_and_each_section_is_charged_travel_by_its_role(ran):
    """The root's `kind` is read in full since Sheets phase 1 (base, option, off). An "option" root moves the travel carrier to
    the first base, Epoxy, and the page's bid() prices the root through polishBid, which charges it by its role too: the job's
    Lodging and Per Diem once, on the carrier (10 x $100), and the option its own for its own crew (15 man-days x $100)."""
    r = ran["pins"]["rootOption"]
    assert r["kind"] == "option" and r["carrier"] == "Epoxy"
    assert r["epoxyTravel"] == 1000 and r["rootTravel"] == 1500
    assert r["polishBidTravel"] == r["rootTravel"], "bid() and priceSection charge the option root alike"


def test_the_combined_tax_figures_are_each_sections_own_sales_and_remodel_tax_summed(ran):
    t = ran["pins"]["taxes"]
    assert t["rootSales"] > 0 and t["epoxySales"] > 0 and t["rootRemodel"] > 0 and t["epoxyRemodel"] > 0
    assert t["sales"] == t["rootSales"] + t["epoxySales"]
    assert t["remodel"] == t["rootRemodel"] + t["epoxyRemodel"]
    assert t["sales"] != t["remodel"] and t["computed"] == [t["sales"], t["remodel"]]


def test_a_tab_sections_contingency_fees_and_labor_conditions_reach_its_own_price(ran):
    p = ran["pins"]
    assert p["contingencyMoves"] is True and p["feesMove"] is True
    with_cond, without = p["laborReadsConditions"]
    assert with_cond > without, "remove-existing joint filler adds a fourth hand to the section's own labor"


def test_a_gyp_base_section_writes_its_area_and_a_base_tab_carries_travel_when_the_root_is_off(ran):
    p = ran["pins"]
    # a Gyp section's area line is its three areas (a row with no area mark is the soft surface's)
    assert p["gypArea"] == {"polish_sf": 10000, "gyp_soft_sf": 9000, "gyp_hard_sf": 0, "gyp_corridor_sf": 0}
    assert p["gypTabArea"] == {"gyp_soft_sf": 9000, "gyp_hard_sf": 0, "gyp_corridor_sf": 0}
    assert p["carrierRootOff"] == 'Gyp (USG 1-8")', "the first BASE section carries it, not the first section"


@pytest.mark.parametrize("case,words", [
    ("noLayout", "does not say its layout"), ("wrongLayout", "but that tab is epoxy"),
    ("badKind", "has kind"), ("noProfile", "no profile stamp"), ("junkProfile", "no profile stamp"),
    ("otherLayoutProfile", "belongs to another layout"), ("notATab", "not a priced workbook tab"),
    ("polishUnderTabs", "root section's own tab"), ("tabsNotAnObject", "must be an object"),
    ("sectionNotAnObject", "is not a section"), ("noModel", "needs the model")])
def test_a_section_that_is_not_well_formed_is_refused_with_the_reason(ran, case, words):
    """A section priced as something it is not is a wrong bid, so there is no default layout and
    "polish" is never assumed.

    Mutation: see test_the_laws_go_red_when_the_code_changes ("a section with no layout is read as one")."""
    got = ran["sections"]["throws"][case]
    assert got and words in got, got


def test_an_unknown_profile_id_is_not_refused_when_sections_are_read_it_is_unpriceable_when_priced(ran):
    assert ran["sections"]["unknownProfileIdIsNotRefusedHere"] is None
    assert ran["pricing"]["unknownProfile"]["priceable"] is False


def test_a_tab_section_is_new_until_somebody_states_labor_or_a_takeoff_in_it(ran):
    n = ran["newSection"]
    assert all(n["rootIsLaborUnstated"]), "the root's gate is laborUnstated, the one the page has always used"
    assert n["tabEmpty"] is True and n["tabNotAnObject"] is True and n["activatedIsNew"] is True
    assert n["tabWithSnapshotButNothingStated"] is True
    assert n["tabWithLabor"] is False and n["tabWithPick"] is False and n["tabWithMeasurement"] is False


# ── 2. activating a section keeps its rates ──────────────────────────────────────────────────────
def test_activating_a_section_stamps_its_profile_and_keeps_the_rules_filed_at_that_moment(ran):
    a = ran["activation"]
    assert a["frozenThrew"] is None, "activateSection edited a frozen input: %s" % a["frozenThrew"]
    assert a["shape"] == {"keys": ["layout", "kind", "profile", "takeoff", "labor", "contingency", "fees", "rates",
                                   "totals", "pool_packs"], "layout": "epoxy", "kind": "base", "profile": "epoxy@1", "labor": 0,
                          "takeoffRows": 1, "contingency": 0, "fees": 0}
    assert a["snapshot"] == {"version": 1, "profile": "epoxy@1", "rates": {"soft_costs": "10%"},
                             "fees_default": None, "notes": []}
    assert a["rootUntouched"] is True, "the root gains no profile or rates key, and the input model gains no tabs"
    assert a["snapshotCopyIsOwn"] == "10%", "the snapshot is text, not a reference to the rule"
    assert a["gypProfile"] == "gyp@1" and a["sealProfile"] == "seal@1"


def test_with_no_rules_the_snapshot_is_empty_and_the_built_ins_stand(ran):
    a = ran["activation"]
    assert a["noRules"] == {"version": 1, "profile": "epoxy@1", "rates": {}, "fees_default": None, "notes": []}
    assert a["noCtx"] == {}


def test_a_rule_that_will_not_price_is_left_out_and_said_so_and_a_bond_rule_is_not_taken(ran):
    """Blank, unreadable, and out of range ("150%" for a gross profit) rules are NOT recorded: the built-in
    stands and `notes` says which line and why. Bond is unwired (0 until Kyle decides), a switched-off rule is
    ignored, the Global rate lines are kept, and the Fees + Textura rule becomes the fees default."""
    a = ran["activation"]
    assert a["notedRates"] == {"labor_rate": "$41"}
    assert a["notedFees"] == 250
    text = " | ".join(a["notedNotes"])
    assert "Bond: a rule is filed" in text and "does not charge it yet" in text
    assert "GP:" in text and "not a rate" in text
    assert "Soft costs:" in text and "cannot be used" in text
    assert "Superintendent and PTO: the rule filed on the Markups page is blank" in text
    assert len(a["notedNotes"]) == 4


@pytest.mark.parametrize("case,words", [
    ("polish", "root of the model"), ("notATab", "not a priced workbook tab"), ("badKind", "base or an option"),
    ("sealAsBase", "option on a bid, never the base"), ("levelingAsBase", "never the base"),
    ("twice", "already a section")])
def test_activating_what_cannot_be_activated_is_refused(ran, case, words):
    got = ran["activation"]["refuses"][case]
    assert got and words in got, got


# ── 3. a saved bid never reprices because somebody edits the Markups rules ───────────────────────
def test_a_section_with_no_snapshot_prices_at_the_built_ins_even_when_rules_are_filed(ran):
    """THE LAW. A saved bid has no snapshot, and the live Markups rules are never read at pricing time:
    the section's total is exactly the engine's, for its profile, with its own built-in rates.

    Mutation: see the table ("a section with no snapshot reads the filed rules")."""
    n = ran["noReprice"]
    assert n["bareTotal"] == n["builtInTotal"] == 28086
    assert n["bareIgnoresFiled"] is True


def test_the_production_rule_polish_bond_1_percent_reaches_nothing(ran):
    """Production's one filed rule (2026-10-12). Not the root (its total is the chain's to the dollar), not a
    saved bid, and not a section activated after it was filed (bond is not taken, and a polish-layout bond
    rule is not even a line the engine reads: bond's home is Global)."""
    n = ran["noReprice"]
    assert n["prodRuleRootTotal"] == n["prodRuleRootChain"] == 33798
    assert n["prodRuleSeedLeavesTheModel"] is True
    assert n["prodRuleNewSectionTotal"] == n["noRuleNewSectionTotal"] == 28086
    assert n["prodRuleKept"] == {} and n["prodRuleNotes"] == []


def test_the_root_is_priced_at_the_built_ins_whatever_is_filed(ran):
    assert ran["noReprice"]["rootIgnoresFiled"] is True


def test_a_section_activated_after_a_rule_was_filed_honours_it_and_keeps_it(ran):
    """Soft costs 20% and a 30% gross profit filed BEFORE activation: the section prices differently, and
    editing the filed rules afterwards (30% and 10%) moves it by nothing."""
    n = ran["noReprice"]
    assert n["honouredDiffers"] is True and n["honouredTotal"] == 23434 != n["builtInTotal"]
    assert n["editedSame"] is True and n["editedAfterTotal"] == n["honouredTotal"]


def test_an_unreadable_filed_rule_is_the_built_in_and_never_zero(ran):
    n = ran["noReprice"]
    assert n["unreadable"]["total"] == n["unreadable"]["builtIn"] > 0
    assert n["unreadable"]["notes"] == 2


def test_a_snapshot_somebody_edited_into_nonsense_is_unpriceable_not_free(ran):
    h = ran["noReprice"]["hand"]
    assert h["priceable"] is False and h["total"] is None and h["line"] == "Soft costs"


def test_a_snapshot_of_another_version_is_not_read(ran):
    assert ran["noReprice"]["otherVersion"] is True


# ── 4. pricing a section ─────────────────────────────────────────────────────────────────────────
def test_the_root_section_prices_exactly_as_the_pages_chain_does(ran):
    p = ran["pricing"]
    assert p["rootEqualsChain"] is True and p["rootTotal"] == p["rootChainTotal"] == 33798


def test_each_section_is_priced_with_its_own_profile(ran):
    p = ran["pricing"]
    assert p["tabs"] == ["Epoxy", "Seal"] and p["pricesAreNumbers"] is True
    assert p["epoxyProfile"] == "epoxy@1" and p["sealProfile"] == "seal@1"
    assert p["epoxy"] == 27340 and p["seal"] == 5628
    assert p["epoxyGp"] == 0.45, "Epoxy's GP ladder, not Polish's"
    assert p["epoxyRemodelDefault"] == 0.07, "the county's remodel rate reaches a tab section"
    assert p["noTabsIsEmpty"] == "{}" and p["offIsNotPriced"] == ["Epoxy"]


def test_the_jobs_travel_is_charged_once_to_the_carrier_section(ran):
    """Plan default for Combo, to be confirmed with Kyle: travel and the fees default belong to the job once.
    The carrier is the first section that is part of the bid as a base."""
    p = ran["pricing"]
    assert p["carrier"] == "Polish" and p["carrierWhenRootOff"] == "Epoxy"
    assert p["farTravel"] == {"root": 1000, "epoxy": 0}
    assert p["noTravelRoot"] == 0
    assert p["carrierMoves"]["epoxy"] == 1000


def test_a_profile_that_is_not_the_one_the_section_was_saved_with_is_unpriceable_not_repriced(ran):
    """The stamp is `<id>@<rev>`. When the engine's rev has moved the section keeps its saved figures and
    says why; it is never silently priced at the new rules.

    Mutation: see the table ("a moved profile rev is priced anyway")."""
    s = ran["pricing"]["stale"]
    assert s["priceable"] is False and s["total"] is None and s["line"] == "profile"
    assert "epoxy@2" in s["reason"] and "epoxy@1" in s["reason"]


def test_a_gyp_section_gets_its_truckload_and_takes_the_engines_material_inputs(ran):
    g = ran["pricing"]["gyp"]
    assert g["priceable"] is True and g["profile"] == "gyp@1" and g["total"] == 26751 and g["materialEscalation"]


def test_a_gyp_section_handed_one_material_number_is_unpriceable_not_priced_at_zero_material(ran):
    """A gyp-split profile reads gyp, extras, sand and sound mat. A plain number (what the estimate page's
    sectionMaterial answers for every tab) would price the material at $0 and still say priceable: so there is
    no price instead, with the reason, and the combined bid takes it with it."""
    r = ran["pricing"]["gypNumberMaterialIsUnpriceable"]
    assert r["priceable"] is False and r["total"] is None and r["line"] == "material"
    assert "gyp, extras, sand" in r["reason"] and "—" not in r["reason"]


def test_pricing_without_the_pages_material_or_for_a_section_that_is_not_there_is_refused(ran):
    p = ran["pricing"]
    assert "needs ctx.material" in p["needsMaterial"] and "no section" in p["unknownSection"]


# ── 5. the one composition of what a save writes for the proposal side ──────────────────────────
def test_a_bid_with_one_section_writes_exactly_the_four_keys_it_always_wrote(ran):
    c = ran["composer"]
    assert c["singleKeys"] == ["polish_estimate", "polish_sf", "polish_2_sf", "computed_bid"]
    assert c["singleHasNoSnapshot"] is True and c["singleTotalsStamped"] is True
    assert c["savePatchKeys"] == ["polish_estimate", "cell_values", "polish_sf", "polish_2_sf", "computed_bid"]
    assert c["singleComputed"] == {"lump_sum": 33798, "price_per_sf": 3.3798, "polish_sf": 10000,
                                   "full_bid": {"total_base_bid": 33798, "sales_tax": 967, "remodel_tax": 0}}


def test_a_bid_with_several_sections_writes_the_complete_derived_set(ran):
    c = ran["composer"]
    assert c["frozenThrew"] is None, c["frozenThrew"]
    assert c["keys"] == ["polish_estimate", "polish_sf", "polish_2_sf", "computed_bid", "priced_tabs", "base_tab_id",
                         "proposal_lump_sum", "proposal_sales_tax", "proposal_remodel_tax", "proposal_taxable",
                         "proposal_remodel_on", "sheet_area", "cost_snapshot", "phase_price", "tab_opts"], (
        "tab_opts is written only because this bid holds an option (Phase 15): the proposal side prints a priced tab "
        "under Options & Unit Prices only when it says is_option")
    assert c["savePatchMultiKeys"] == ["polish_estimate", "cell_values"] + c["keys"][1:]
    assert c["savePatchEqualsComposer"] is True, "buildSavePatch is the composer plus the condition cells"
    assert c["pricedTabs"] == [["Polish", "polish", "base", True, 33798], ["Epoxy", "epoxy", "base", True, 27340],
                               ["Seal", "seal", "option", True, 5628]]
    assert c["allMarkedV2"] is True, "an unmarked tab makes the Proposal step hide the snapshot (v2PricingView)"
    assert c["tabKeys"] == sorted(["id", "name", "role", "kind", "total", "sales_tax", "remodel", "system_desc",
                                   "notes_auto", "sf", "sys_names", "taxable", "remodel_on", "v2"])


def test_the_combined_base_is_each_sections_own_total_summed_not_one_pooled_chain(ran):
    """GP steps down with job size, so pricing the pooled job once is a different (lower) bid and the
    sheet never does it. Each section has had its OWN gross profit taken, then they are added.

    Mutation: see the table ("an option is added into the base bid")."""
    c = ran["composer"]
    assert c["lump"] == c["sumOfBaseParts"] == 61138
    assert c["pooledWouldBe"] != c["lump"]
    assert c["sealIsNotInTheLump"] is True and c["sealDeclaredBaseIsNeverBase"] is True
    assert c["computed"] == {"lump_sum": 61138, "price_per_sf": 4.367, "polish_sf": 10000,
                             "full_bid": {"total_base_bid": 61138, "sales_tax": 1809, "remodel_tax": 0}}
    assert c["taxes"] == [1809, 0]


def test_the_areas_costs_flags_and_phase_come_from_the_base_sections(ran):
    c = ran["composer"]
    assert c["area"] == {"polish_sf": 10000, "epoxy_sf": 4000, "cove_lf": 300}, "an option never adds to the area"
    assert c["cost"] == {"costs": 28874, "man_hours": 216}
    assert c["phase"] == 0 and c["polishSf"] == [10000, ""]
    assert c["flags"] == [True, False]
    assert c["taxFlags"] == {"taxable": False, "remodelOn": True, "tab": [False, True]}


def test_a_save_stamps_each_sections_totals_on_a_copy_and_touches_nothing_it_was_handed(ran):
    c = ran["composer"]
    assert c["totalsStampedOnEverySection"] == [33798, 27340, 5628]
    assert c["stampedAreCopies"] is True and c["inputsUntouched"] is True


def test_a_section_that_cannot_price_takes_the_combined_price_with_it(ran):
    """No price rather than a wrong one: the lump sum, the taxes and computed_bid are null, the tab lists the
    reason, and the stamped totals say it is unpriceable instead of printing the last figure."""
    u = ran["composer"]["unpriceable"]
    assert u["computed"] is None and u["lump"] is None and u["taxes"] == [None, None]
    assert u["epoxyTab"] == [[None, "no rate"]] and u["totalsStamped"] is False
    assert u["cost"] == {"costs": 0, "man_hours": 0}


def test_a_root_that_is_off_and_a_bid_with_no_base_section(ran):
    c = ran["composer"]
    assert c["rootOff"]["computed"] == 27340 and c["rootOff"]["hasPolishSf"] is False
    assert c["rootOff"]["tabs"] == ["Epoxy", "Seal"]
    assert c["noBase"] == {"computed": None, "lump": None}


def test_a_save_with_no_price_for_a_section_is_refused_and_so_is_a_section_that_cannot_be_read(ran):
    t = ran["composer"]["throws"]
    assert "ctx.bid" in t["noBid"] and "save of zero" in t["noBid"]
    assert 'ctx.bids["Seal"]' in t["noTabBid"] and "save of zero" in t["noTabBid"]
    assert t["noCtx"] and t["noModel"] and "layout" in t["badTabs"] and "ctx.bid" in t["savePatchNoBid"]


# ── 6. the new-bid seeding, per section ──────────────────────────────────────────────────────────
def test_a_new_bids_root_is_seeded_the_way_the_page_always_seeded_it(ran):
    """(The byte-for-byte proof is the golden above; these are the facts it holds.) The library's labor
    lines beside Travel at the company rate, Lodging and Per Diem rates, the Fees + Textura default, the
    dye answer, and intake's first SF box on the takeoff."""
    s = ran["seeding"]
    assert s["rootLaborIds"] == ["polishing", "mockup", "jointfill", "travel", "lab-x", "lab-po"]
    assert s["rootRates"] == [50, 50, 50, 41, 50, 50]
    assert s["rootTakeoff"] == [8000] and s["rootFees"] == [250, 250] and s["rootTravelRates"] == [99, 77]
    assert s["rootDye"] is True


def test_a_saved_bid_is_given_nothing_and_the_input_is_never_edited(ran):
    s = ran["seeding"]
    assert s["savedUntouched"] is True, "a library default landed on a saved bid"
    assert s["inputsUntouched"] is True and s["frozenThrew"] is None


def test_a_new_tab_section_is_seeded_by_its_own_layout_and_a_saved_one_is_left_alone(ran):
    m = ran["seeding"]["multi"]
    assert m["epoxyLabor"] == ["lab-x", "lab-ep"], "the Epoxy defaults, not the Polish-only one"
    assert "lab-po" not in m["epoxyLabor"] and "lab-ep" not in m["rootLabor"]
    assert m["epoxyRates"] == [50, 50] and m["epoxyTakeoff"] == [4000] and m["rootTakeoff"] == [8000]
    assert m["epoxyKeepsItsSnapshot"] is True
    assert m["sealLabor"] == ["sealing"] and m["sealLaborKept"] is True and m["sealTakeoff"] == [5000]


def test_travel_and_the_fees_default_go_to_the_carrier_only(ran):
    s = ran["seeding"]
    assert s["multi"]["rootHasTravel"] is True and s["multi"]["epoxyHasTravel"] is False
    assert s["multi"]["rootFees"] == 250 and s["multi"]["epoxyFees"] == 0
    e = s["epoxyOnly"]
    assert e["carrier"] == "Epoxy" and e["epoxyLabor"] == ["travel", "lab-x", "lab-ep"]
    assert e["epoxyFees"] == 250 and e["rootFees"] == 0 and e["feesDefault"] == 250 and e["epoxyTakeoff"] == [4000]
    assert e["rootLabor"] == ["polishing", "mockup", "jointfill", "travel"], "an off root is left alone"


def test_a_library_that_declines_travel_says_so_on_the_model(ran):
    n = ran["seeding"]["noTravelLabor"]
    assert n == {"root": True, "carrierEpoxy": True, "carrierEpoxyKept": False}


@pytest.mark.parametrize("case,words", [
    ("noModel", "needs the model"), ("noCtx", "needs ctx"), ("noLayout", "does not say its layout"),
    ("unknownLayout", "but that tab is epoxy")])
def test_seeding_needs_every_sections_layout_and_never_guesses_one(ran, case, words):
    got = ran["seeding"]["throws"][case]
    assert got and words in got, got


# ── 7. the strip that switches section ───────────────────────────────────────────────────────────
def test_the_strip_is_empty_for_one_section_and_one_button_each_for_several(ran):
    s = ran["switcher"]
    assert s["single"] == "" and s["buttons"] == 3 and s["current"] == 1 and s["activeIsEpoxy"] is True
    assert s["tabs"] == ['data-section-tab="Polish"', 'data-section-tab="Epoxy"', 'data-section-tab="Seal"']
    assert s["prices"] and s["optionLabelled"] and s["escapes"] and s["noPriceSaysSo"] and s["noEmDash"]


def test_the_page_draws_no_strip_for_one_section_and_saves_what_it_always_saved(ran):
    one = ran["page"]["one"]
    assert one["strip"] == {"hidden": True, "html": "", "htmlWrites": 0}, "a single-section bid must look as it did"
    assert one["keys"] == sorted(["__draft_id", "cell_values", "city", "computed_bid", "polish_2_sf",
                                  "polish_estimate", "polish_sf", "project_name", "state", "work_type"])
    assert one["hasSnapshot"] is False and one["alert"] == ""


def test_the_page_draws_the_strip_prices_every_section_and_switches_the_panel(ran):
    m = ran["page"]["multi"]
    assert m["strip"]["hidden"] is False
    assert m["strip"]["html"].count("data-section-tab=") == 3
    # Epoxy is edited on the page's own panels now (Phase 12): its Material panel is the takeoff, with the patch
    # that the sheet always charges, not a summary. A section not edited here yet keeps the summary.
    assert "data-epoxy-patch" in m["panelEpoxy"] and "Priced with epoxy@1" not in m["panelEpoxy"]
    # The Seal option is edited on the page's own panels since Phase 15 (its Material panel is the takeoff, with the
    # patch); the Leveling option, which Phase 16 brings, is the section that still shows the summary.
    assert "data-seal-patch" in m["panelSeal"] and "Priced with seal@1" not in m["panelSeal"]
    assert "Leveling" in m["panelLeveling"] and "Priced with leveling@1" in m["panelLeveling"]
    assert "blank, so the built-in rate is charged" in m["panelLeveling"], "the Markups notes are shown, not hidden"
    assert 'aria-current="true">Epoxy' in m["stripAfterClick"]
    assert m["panelRootIsTakeoff"] is True, "choosing Polish again brings the takeoff panel back"
    assert m["maths"].startswith("Polish $") and "+ Epoxy $" in m["maths"]


def test_the_page_saves_the_composed_set_and_the_bar_shows_the_figure_it_saves(ran):
    m = ran["page"]["multi"]
    assert "priced_tabs" in m["savedKeys"] and "proposal_lump_sum" in m["savedKeys"]
    assert m["pricedTabs"] == [["Polish", True, "base"], ["Epoxy", True, "base"], ["Seal", True, "option"]]
    assert m["savedLump"] == m["proposalLump"] > m["rootOnlyTotal"]
    assert m["barMatchesSave"] is True
    assert m["flushEqualsAutosave"] is True, "the autosave and the pagehide flush write the same blob"
    assert m["tabsKept"] == ["Epoxy", "Seal"]
    assert m["rootTotalsStamped"] > 0 and m["epoxyTotalsStamped"] > 0


def test_a_bid_whose_sections_cannot_be_read_still_saves_what_was_typed_and_keeps_them_as_saved(ran):
    b = ran["page"]["broken"]
    assert "cannot be read" in b["alert"] and "layout" in b["alert"]
    assert b["measurement"] == "12000", "the edit was lost"
    assert b["tabsKept"] is True and b["hasSnapshot"] is False


# ── red without the code: break a COPY and watch each law notice ─────────────────────────────────
BREAKS = {
    # --- the engine: what a section keeps ---
    "a bond rule is taken": (
        "js/bid-engine.js", '  var UNWIRED = ["bond"];', "  var UNWIRED = [];",
        lambda r: r["noReprice"]["prodRuleKept"] != {} or r["activation"]["notedRates"] != {"labor_rate": "$41"}),
    "a blank rule says nothing": (
        "js/bid-engine.js", '      if (blank && line !== "fees_textura") {', "      if (false) {",
        lambda r: r["noReprice"]["unreadable"]["notes"] != 2),
    "a snapshot of another version is read": (
        "js/bid-engine.js",
        '    if (!snapshot || typeof snapshot !== "object" || snapshot.version !== SNAPSHOT_VERSION) return undefined;',
        '    if (!snapshot || typeof snapshot !== "object") return undefined;',
        lambda r: r["noReprice"]["otherVersion"] is False),
    "an unreadable rule is kept as the snapshot": (
        "js/bid-engine.js", "    Object.keys(compiled.unpriceable).forEach(function (line) {",
        "    Object.keys({}).forEach(function (line) {",
        lambda r: len(r["activation"]["notedNotes"]) != 4),
    # --- the model: pricing ---
    "a section with no snapshot reads the filed rules": (
        "js/bid-model.js", "      return engine.priceChain(profile, input, e.root ? undefined : engine.ratesOf(s.rates));",
        "      return engine.priceChain(profile, input, e.root ? undefined : (ctx.rules ? engine.compileRates(profile, ctx.rules) : engine.ratesOf(s.rates)));",
        lambda r: r["noReprice"]["bareIgnoresFiled"] is False and r["noReprice"]["editedSame"] is False),
    "the root reads the filed rules": (
        "js/bid-model.js", "      return engine.priceChain(profile, input, e.root ? undefined : engine.ratesOf(s.rates));",
        "      return engine.priceChain(profile, input, e.root ? (ctx.rules ? engine.compileRates(profile, ctx.rules) : undefined) : engine.ratesOf(s.rates));",
        lambda r: r["noReprice"]["rootIgnoresFiled"] is False),
    "a moved profile rev is priced anyway": (
        "js/bid-model.js", "    if (String(profile.rev) !== stamp[2]) {", "    if (false) {",
        lambda r: r["pricing"]["stale"]["priceable"] is True),
    "every section carries the jobs travel": (
        "js/bid-model.js", "      travel: carrier ? travelCosts(model.travel, s.labor).total : 0,",
        "      travel: travelCosts(model.travel, s.labor).total,",
        lambda r: r["pricing"]["farTravel"]["epoxy"] != 0),
    "a section with no layout is read as one": (
        "js/bid-model.js",
        '      if (typeof s.layout !== "string" || s.layout === "") throw new Error(where + " does not say its layout (there is no default)");',
        '      if (typeof s.layout !== "string" || s.layout === "") s.layout = "polish";',
        lambda r: "does not say its layout" not in (r["sections"]["throws"]["noLayout"] or "")),
    "a profile of another layout is accepted": (
        "js/bid-model.js", "      if (known && known.layout !== s.layout) {", "      if (false) {",
        lambda r: r["sections"]["throws"]["otherLayoutProfile"] is None),
    # --- the model: the composition ---
    "a single section saves the complete set": (
        "js/bid-model.js", "    if (single) { out.computed_bid = rootComputed; return out; }",
        "    if (false) { out.computed_bid = rootComputed; return out; }",
        lambda r: r["composer"]["singleHasNoSnapshot"] is False),
    "an option is added into the base bid": (
        "js/bid-model.js",
        '    return e.kind === "base" && !types.tab(types.tabOfSheet(e.sheet)).optionOnly;',
        '    return e.kind !== "off";',
        lambda r: r["composer"]["sealIsNotInTheLump"] is False),
    "an option-only tab declared a base is believed": (
        "js/bid-model.js",
        '    return e.kind === "base" && !types.tab(types.tabOfSheet(e.sheet)).optionOnly;',
        '    return e.kind === "base";',
        lambda r: r["composer"]["sealDeclaredBaseIsNeverBase"] is False),
    "a section that cannot price is priced as zero": (
        "js/bid-model.js", "    var priceable = function (b) { return b.priceable !== false; };",
        "    var priceable = function (b) { return true; };",
        lambda r: "error" in r["composer"] or r["composer"]["unpriceable"]["lump"] is not None),
    "the tabs are not marked v2": (
        "js/bid-model.js", '        taxable: !!cond.taxable, remodel_on: !!cond.remodel_tax, v2: true',
        '        taxable: !!cond.taxable, remodel_on: !!cond.remodel_tax, v2: false',
        lambda r: r["composer"]["allMarkedV2"] is False),
    "the totals are stamped onto the model it was handed": (
        "js/bid-model.js", "    var stamped = Object.assign(copyInto({}, model), rootLive ? { totals: rootLive } : {});",
        "    var stamped = Object.assign(model, rootLive ? { totals: rootLive } : {});",
        lambda r: r["composer"]["inputsUntouched"] is False or r["composer"]["frozenThrew"] is not None),
    "the area of an option is added to the proposal's": (
        "js/bid-model.js", "    var base = bids.filter(function (x) { return isBaseEntry(x.e); });",
        "    var base = bids;",
        lambda r: r["composer"]["area"] != {"polish_sf": 10000, "epoxy_sf": 4000, "cove_lf": 300}
        or r["composer"]["lump"] != r["composer"]["sumOfBaseParts"]),
    # --- the model: seeding ---
    "a saved bid is seeded": (
        "js/bid-model.js", "    var asked = laborGate && !!ctx.laborRows;", "    var asked = !!ctx.laborRows;",
        lambda r: r["seeding"]["savedUntouched"] is False),
    "a saved tab section is seeded": (
        "js/bid-model.js", "      return e.kind !== \"off\" && (e.root || isNewSection(e.section, false));",
        '      return e.kind !== "off";',
        lambda r: "error" in r["seeding"] or r["seeding"]["multi"]["sealLaborKept"] is False),
    "every section gets Travel": (
        "js/bid-model.js",
        "      s.labor = carrierTab === e.tab ? rows : rows.filter(function (r) { return !r || r.id !== \"travel\"; });",
        "      s.labor = rows;",
        lambda r: r["seeding"]["multi"]["epoxyHasTravel"] is True),
    "the calculator runs on a saved bid": (
        "js/bid-model.js", "        if (e.root && !laborGate) return;", "        void laborGate;",
        lambda r: r["seeding"]["savedUntouched"] is False),
    "the fees default is dropped": (
        "js/bid-model.js", "        out = applyFeesDefault(out, ctx.feesDefault);", "        void 0;",
        lambda r: r["seeding"]["rootFees"] != [250, 250]),
    "the seeding edits its input": (
        "js/bid-model.js", "    var out = jsonCopy(model);   // the caller's model is never edited",
        "    var out = model;",
        lambda r: r["seeding"]["frozenThrew"] is not None or r["seeding"]["inputsUntouched"] is False),
    # --- the strip ---
    "the strip is drawn for one section": (
        "js/bid-model.js", "    if (list.length < 2) return \"\";", "    if (list.length < 1) return \"\";",
        lambda r: r["switcher"]["single"] != ""),
    "a root kind of option is not read": (
        "js/bid-model.js", '    var rootKind = model.kind === "off" ? "off" : (model.kind === "option" ? "option" : "base");',
        '    var rootKind = model.kind === "off" ? "off" : "base";',
        lambda r: r["pins"]["rootOption"]["kind"] != "option" or r["pins"]["rootOption"]["epoxyTravel"] != 1000),
    "a gyp section is priced from a plain number": (
        "js/bid-model.js", '    if (profile.quirks.shippingRule === "gyp-split" && !isObject(mat)) {',
        "    if (false) {",
        lambda r: r["pricing"]["gypNumberMaterialIsUnpriceable"]["priceable"] is True),
    "the remodel tax is dropped from the lump": (
        "js/bid-model.js", "    out.proposal_remodel_tax = ok ? sums.remodel_tax : null;",
        "    out.proposal_remodel_tax = ok ? 0 : null;",
        lambda r: r["pins"]["taxes"]["remodel"] != r["pins"]["taxes"]["rootRemodel"] + r["pins"]["taxes"]["epoxyRemodel"]),
    "the sales tax is every tax": (
        "js/bid-model.js", "    out.proposal_sales_tax = ok ? sums.sales_tax : null;",
        "    out.proposal_sales_tax = ok ? sums.taxes : null;",
        lambda r: r["pins"]["taxes"]["sales"] != r["pins"]["taxes"]["rootSales"] + r["pins"]["taxes"]["epoxySales"]),
    "the gyp area is forgotten": (
        "js/bid-model.js", '    if (e.role === "gyp") return gypAreaFields(rows);',
        '    if (e.role === "gyp") return {};',
        lambda r: r["pins"]["gypArea"] != {"polish_sf": 10000, "gyp_soft_sf": 9000, "gyp_hard_sf": 0, "gyp_corridor_sf": 0}),
    "the travel carrier is the first section": (
        "js/bid-model.js", '    for (var i = 0; i < list.length; i++) if (list[i].kind === "base") return list[i].tab;',
        "    for (var i = 0; i < list.length; i++) if (i >= 0) return list[i].tab;",
        lambda r: r["pins"]["carrierRootOff"] != 'Gyp (USG 1-8")'),
    "a sections labor ignores the job's conditions": (
        "js/bid-model.js", "      labor: laborTotal(s.labor, model.conditions),",
        "      labor: laborTotal(s.labor),",
        lambda r: r["pins"]["laborReadsConditions"][0] <= r["pins"]["laborReadsConditions"][1]),
    "a sections contingency is dropped": (
        "js/bid-model.js", "      contingency: s.contingency, fees: s.fees, conditions: model.conditions,",
        "      contingency: 0, fees: s.fees, conditions: model.conditions,",
        lambda r: r["pins"]["contingencyMoves"] is False),
    "a sections fees are dropped": (
        "js/bid-model.js", "      contingency: s.contingency, fees: s.fees, conditions: model.conditions,",
        "      contingency: s.contingency, fees: 0, conditions: model.conditions,",
        lambda r: r["pins"]["feesMove"] is False),
    "the page hands a gyp section a plain number": (
        "js/polish-estimate.js", '    if (entry.role === "gyp" && G) {',
        "    if (false) {",
        lambda r: r["page"]["gypOnPage"]["priceable"] is False or not r["page"]["gypOnPage"].get("material")),
    "the page saves without pricing its other sections": (
        "js/polish-estimate.js", "      return B.buildSavePatch(ROOT, now, priceCtx());",
        "      return B.buildSavePatch(ROOT, now, { bid: bid(), library: conditionLibrary() });",
        lambda r: "error" in r["page"] or "priced_tabs" not in r["page"]["multi"]["savedKeys"]),
}


def _scratch_run(tmp_path, rel, old, new, script):
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, SCRATCH_FILES)
    return _run(script, frontend)


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_laws_go_red_when_the_code_changes(tmp_path, name):
    """Each change is the kind a refactor makes by accident, applied to a scratch copy of the page and the
    core. The anchor must be in the file exactly once (break_source refuses otherwise)."""
    require_node()
    rel, old, new, noticed = BREAKS[name]
    got = _scratch_run(tmp_path, rel, old, new, HARNESS)
    assert noticed(got), "the laws did not notice: " + name


GOLDEN_BREAKS = {
    "the composer adds a snapshot to a single section": (
        "js/bid-model.js", "    if (single) { out.computed_bid = rootComputed; return out; }",
        "    if (false) { out.computed_bid = rootComputed; return out; }"),
    "the seeding forgets the travel rates": (
        "js/bid-model.js", "      out.travel = travelLinesStartEmpty(applyTravelRates(out.travel, ctx.travelRates));",
        "      void ctx.travelRates;"),
    "the seeding leaves every labor row filled in by the man-days": (
        "js/bid-model.js",
        "      rows = rows.map(function (r) { return r ? laborRowStartsEmpty(r) : r; });",
        "      void laborRowStartsEmpty;"),
    "the calculator fills the days again": (
        "js/bid-model.js", '      copy.guys = ""; copy.days = ""; copy.rate = v.rate; copy.hours_per_day = v.hours_per_day;',
        "      copy.guys = v.guys; copy.days = v.days; copy.rate = v.rate; copy.hours_per_day = v.hours_per_day;"),
    "the seeding forgets which cards a bid shows": (
        "js/bid-model.js", "      out.conditions_shown = seedConditionsShown(ctx.conditionRows);", "      void ctx.conditionRows;"),
    "the seeding lets the library beat the intake's cell": (
        "js/bid-model.js",
        "      out.conditions = conditionsFromCells(seedConditionDefaults(out.conditions, ctx.conditionRows), ctx.cellValues, !!ctx.split);",
        "      out.conditions = seedConditionDefaults(out.conditions, ctx.conditionRows);"),
    "the page seeds with the wrong gate": (
        "js/polish-estimate.js", "      saved: savedEstimate,", "      saved: undefined,"),
    "the save forgets the condition cells": (
        "js/bid-model.js", "      cell_values: conditionCellWrites(model.conditions, cells, ctx.library, types.isSplit(state)),",
        "      cell_values: cells,"),
}


@pytest.mark.parametrize("name", sorted(GOLDEN_BREAKS))
def test_the_golden_goes_red_when_the_code_changes(tmp_path, name):
    """The byte-for-byte record must notice each of these. Every one is a plausible slip in the move of the
    seeding or of the save's composition, and each leaves the harness itself running."""
    require_node()
    rel, old, new = GOLDEN_BREAKS[name]
    got = _scratch_run(tmp_path, rel, old, new, GOLDEN_HARNESS)
    want = json.loads(GOLDEN.read_text(encoding="utf-8"))["golden"]
    assert json.dumps(got) != json.dumps(want), "the golden did not notice: " + name
