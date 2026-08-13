"""Sealed concrete can be added as a proposal OPTION, and can never become the base bid.

An estimator, 2026-08-13, with a screenshot of Estimate Review: "Working on an estimate and noticed
that 'Seal' doesn't come up as an optional system to add."

He was right, and it was one line: `PRICED_ROLES` held only epoxy/polish/gyp, so `roleFor("Seal")`
returned "other" and `pricedTabs()` dropped both seal sheets before any chip was rendered. The tabs
were fully editable the whole time, which is why it read as broken rather than unbuilt — the sheet
priced fine and then there was nowhere to put it.

WHY THIS FILE IS MOSTLY ABOUT WHAT MUST *NOT* HAPPEN. Granting the request puts two `kind: "base"`
template sheets into the priced set, and three things downstream were written as "anything but gyp":

  * a combo job's combined base bid would have swallowed them — tagging Seal "base bid", removing
    the option controls it was just given, and ADDING its total to the combined price a customer is
    quoted;
  * every visible chip carries a Base-bid radio, so making Seal the base was one click away — and
    role "seal" has no proposal template (`("sealer","GC")` is the only sealer entry in
    TEMPLATE_PICKER), so `effectiveWorkType` falls back to the intake type and the customer receives
    the EPOXY document carrying the seal's money;
  * the Proposal screen's own combo exclusion tested `t.kind === "base"` alone, so a Seal option was
    dropped there while the Estimate screen went on listing it.

Executed, not grepped, because every one of those is a claim about rendered markup or a resolved
value. A source assertion cannot see which chip carries a radio.
"""
import json
import pathlib
import re
import shutil
import subprocess
import zipfile

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = REPO / "frontend"
TEMPLATES = pathlib.Path(__file__).resolve().parents[1] / "templates"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "combo-base-harness.js"
ESTIMATE_JS = (FRONTEND / "js" / "estimate-review.js").read_text(encoding="utf-8")
PROPOSAL_JS = (FRONTEND / "js" / "proposal-review.js").read_text(encoding="utf-8")

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

SEAL_SHEETS = ["Seal", "Seal (+Jnts)"]


@pytest.fixture(scope="module")
def strip():
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── the request ───────────────────────────────────────────────────────────────
@needs_node
def test_both_seal_sheets_are_offered_as_options(strip):
    """His sentence, as an assertion. Both sheets, because the workbook has two and an estimator
    pricing joints is using the second one."""
    s = strip["seal"]
    assert s["present"] and s["jointsPresent"], s
    assert s["offersOption"] is True


@needs_node
def test_the_chip_shows_the_sheets_own_price(strip):
    """Read through TOTAL_CELLS.Seal. If the role fell through to the Epoxy coordinates it would
    read D88 — blank on a Polish-layout sheet — and the chip would show nothing while the option
    was silently dropped downstream by `.filter(o => o.bid.total > 0)`."""
    assert strip["seal"]["price"] == "$8,410", strip["seal"]["price"]
    assert strip["seal"]["jointsPrice"] == "$9,905", strip["seal"]["jointsPrice"]


@needs_node
def test_a_sheet_the_app_does_not_price_is_still_absent(strip):
    """Proof the filter filters. Leveling is in the workbook and must not become a chip just
    because the role vocabulary grew."""
    assert strip["seal"]["levelingPresent"] is False


# ── option only: the one-click path to the wrong document ─────────────────────
@needs_node
def test_a_seal_chip_has_no_base_bid_radio(strip):
    """THE guard. Role "seal" has no proposal template, so a seal base bid prints the epoxy
    document with the seal's price — a wrong document, not a wrong number."""
    s = strip["seal"]
    assert s["hasBaseRadio"] is False, "the Seal chip offers to become the base bid"
    assert s["jointsHasBaseRadio"] is False
    assert s["epoxyStillHasRadio"] is True, (
        "the radio was suppressed for every chip, not just the option-only ones")


@needs_node
def test_the_resolver_itself_refuses_a_seal_base(strip):
    """Asked directly, with no render first. The render's stale-base guard would otherwise have
    already nulled it, so both guards produced the same answer and neither was pinned alone — a
    mutation removing this one passed until this case existed."""
    assert strip["sealAsBase"]["resolvedWithoutRender"] == "Epoxy", strip["sealAsBase"]


@needs_node
def test_the_last_resort_fallback_will_not_reach_for_a_seal_tab(strip):
    """`resolveBaseTab` ends in a "whatever is priced" tail. On a workbook whose only priced sheets
    are the seal ones it must answer nothing at all rather than quietly making Seal the base."""
    assert strip["sealAsBase"]["fallbackOnSealOnlyWorkbook"] is None, (
        "the fallback picked %r as a base bid" % strip["sealAsBase"]["fallbackOnSealOnlyWorkbook"])


@needs_node
def test_a_draft_naming_a_seal_base_is_refused(strip):
    """The belt behind that guard: state can arrive from an older draft, another device, or a
    hand-edited blob. `resolveBaseTab` must not honour it, and the render must rewrite it."""
    b = strip["sealAsBase"]
    assert b["resolved"] == "Epoxy", b
    assert b["stateBaseAfterRender"] == "Epoxy", (
        "the stale seal base survived the render, so the next save persists it")


def test_the_option_only_rule_is_stated_in_both_screens():
    """Two screens disagreeing about which sheets may be the base is how an option gets listed on
    one and dropped from the other."""
    for name, src in (("estimate-review.js", ESTIMATE_JS), ("proposal-review.js", PROPOSAL_JS)):
        assert re.search(r'OPTION_ONLY_ROLES = new Set\(\[[^\]]*"seal"', src), name
    assert "isOptionOnlyRole" in ESTIMATE_JS
    assert "isOptionOnlyTab" in PROPOSAL_JS


def test_the_proposal_screen_refuses_a_seal_base_before_pricing_it():
    """Scoped source assertion, not execution: there is no harness over `rebuildPricing` (it wants
    the whole priced-tabs snapshot), and building one for this is out of proportion to a four-line
    guard. Scoped to the function so an unrelated occurrence elsewhere cannot satisfy it."""
    i = PROPOSAL_JS.index("function rebuildPricing(")
    body = PROPOSAL_JS[i:PROPOSAL_JS.index("\n  function ", i + 10)]
    assert 'toLowerCase() === "seal"' in body, (
        "rebuildPricing no longer drops a seal base, so it would price the bid off a seal sheet "
        "and print whichever template the intake work type picked")
    assert "state.base_tab_id = null" in body


def test_the_sidebar_does_not_tag_seal_as_part_of_a_combo_base():
    """Same reasoning as above. `role !== "gyp"` here would tag both seal sheets "part of the
    combined base bid" on the Proposal screen while the Estimate strip listed them as options."""
    i = PROPOSAL_JS.index("const isPartOfAutoBase = (t) => {")
    body = PROPOSAL_JS[i:i + 400]
    assert '["epoxy", "polish"]' in body, body
    assert 'role !== "gyp"' not in body


def test_the_proposal_screen_still_has_no_seal_work_type():
    """`effectiveWorkType` must keep whitelisting epoxy/polish/gyp. Adding seal there would start
    selecting a template that does not exist for Direct."""
    i = PROPOSAL_JS.index("function effectiveWorkType()")
    body = PROPOSAL_JS[i:i + 900]
    assert '"seal"' not in body, "effectiveWorkType now knows about seal, which has no template"


# ── the combo hazard ──────────────────────────────────────────────────────────
@needs_node
def test_a_seal_sheet_is_never_part_of_the_combined_base(strip):
    """Both seal sheets are `kind: "base"`, which is exactly what the old `role !== "gyp"` test
    swept in."""
    combo = dict(strip["predicate"]["combo"])
    for sheet in SEAL_SHEETS:
        assert combo[sheet] is False, "%s is treated as part of the combined base bid" % sheet
    assert combo["Epoxy"] is True and combo["Polish"] is True, combo


@needs_node
def test_the_combined_price_is_still_only_epoxy_plus_polish(strip):
    """Wrong money on a customer document is the failure this prevents: with the old predicate the
    two seal sheets ($8,410 + $9,905) would have been added to every combo base price."""
    assert strip["comboDefault"]["combinedPrice"] == "$45,743", (
        strip["comboDefault"]["combinedPrice"])


def test_both_combo_predicates_use_the_one_role_set():
    """`isInCombinedBase` and `comboComboTotal` describing the pair differently is the bug this
    file's sibling (test_combo_both_base.py) was written for."""
    assert ESTIMATE_JS.count("COMBINED_BASE_ROLES") >= 3, (
        "the shared role set is not used by both predicates")
    assert not re.search(r'kind === "base" && t\.role !== "gyp"', ESTIMATE_JS), (
        "a combo predicate is back to excluding only gyp")
    assert not re.search(r'kind === "base" && role !== "gyp"', ESTIMATE_JS)


def test_the_proposal_screen_shares_the_predicate():
    """`t.kind === "base"` alone dropped a Seal option from every combo proposal."""
    assert "inCombinedBase" in PROPOSAL_JS
    assert not re.search(r'!\(!state\.base_tab_id && wt === "combo" && t\.kind === "base"\)',
                         PROPOSAL_JS), "the proposal screen still excludes by kind alone"
    assert re.search(r'COMBINED_BASE_ROLES = new Set\(\["epoxy", "polish"\]\)', PROPOSAL_JS)


# ── what the customer reads ───────────────────────────────────────────────────
@needs_node
def test_the_option_is_called_sealed_concrete(strip):
    """The sheet's A22/A26 (the epoxy system-name cells) are empty, so without this the option
    prints the internal worksheet name "Seal"."""
    assert strip["sealNames"]["seal"] == "Sealed Concrete"


@needs_node
def test_the_joints_sheet_is_named_distinctly(strip):
    """Both can be quoted on the same proposal, and two option lines with an identical description
    are unreadable. The sheet itself labels its delta "Add Joint Filler"."""
    joints = strip["sealNames"]["joints"]
    assert joints != strip["sealNames"]["seal"]
    assert "Joint" in joints, joints


def test_the_name_matches_the_wording_the_backend_already_uses():
    """One job must not read two ways. main.py maps the sealer work type to "Sealed Concrete" for
    the GC sealer proposal; the option line has to agree with it."""
    main_py = (pathlib.Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert '"sealer": "Sealed Concrete"' in main_py, (
        "the backend's sealer wording moved — update SEAL_SYSTEM_NAME with it")
    assert 'const SEAL_SYSTEM_NAME = "Sealed Concrete";' in ESTIMATE_JS


# ── the workbook, which is where the coordinates come from ────────────────────
def _js_map(name):
    """One entry out of the TOTAL_CELLS literal.

    Scoped to that literal, not searched file-wide: `AREA_SF_CELLS` also has a `Polish:` key and it
    appears FIRST, so an unscoped search returned {polish_sf: "E18"} and the comparison below
    silently had nothing to compare. A test that reads the wrong constant is worse than no test."""
    block = re.search(r"const TOTAL_CELLS = \{(.*?)\n\};", ESTIMATE_JS, re.S)
    assert block, "TOTAL_CELLS moved"
    m = re.search(r"\n  %s:\s*\{([^}]*)\}" % name, block.group(1))
    assert m, "TOTAL_CELLS.%s is missing" % name
    return dict(re.findall(r'(\w+):\s*"([A-Z]+\d+)"', m.group(1)))


def test_the_seal_coordinates_are_the_polish_ones_and_the_workbook_agrees():
    """Derived from the real .xlsx rather than restated here. Every shared key must hold an
    IDENTICAL formula on Polish and on both seal sheets — that identity is the whole reason the
    coordinates are reused instead of invented, and if Kyle ever re-lays out a seal sheet this test
    is what says so before an estimator quotes from it."""
    openpyxl = pytest.importorskip("openpyxl")
    seal, polish = _js_map("Seal"), _js_map("Polish")
    assert seal, "no Seal entry in TOTAL_CELLS"
    wb = openpyxl.load_workbook(TEMPLATES / "estimate_sheet_5.7.xlsx", data_only=False)
    try:
        for field, addr in seal.items():
            assert addr == polish[field], (
                "Seal.%s is %s but Polish.%s is %s — they are the same layout"
                % (field, addr, field, polish[field]))
            want = wb["Polish"][addr].value
            for sheet in SEAL_SHEETS:
                got = wb[sheet][addr].value
                assert got == want, (
                    "%s!%s is %r but Polish!%s is %r — the layouts have diverged and the money "
                    "cells must be re-derived" % (sheet, addr, got, addr, want))
        # The one place they differ, and the reason there is no phase key.
        assert "phase" not in seal, (
            "TOTAL_CELLS.Seal has a phase cell; the seal sheets do not price a phase")
        assert wb["Polish"]["C85"].value == 4500
        for sheet in SEAL_SHEETS:
            assert wb[sheet]["C85"].value is None, (
                "%s now has something in the phase cell — re-check phaseAt's guard" % sheet)
    finally:
        wb.close()


def test_the_seal_sheets_exist_under_exactly_these_names():
    """The report said "Seal"; the app must key off what the workbook actually calls them. They are
    NOT "Sealer" — that word only appears as a material row and in the GC template's name."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.load_workbook(TEMPLATES / "estimate_sheet_5.7.xlsx", read_only=True)
    try:
        for sheet in SEAL_SHEETS:
            assert sheet in wb.sheetnames, wb.sheetnames
    finally:
        wb.close()
    assert re.search(r'const SEAL_SHEETS = \["Seal", "Seal \(\+Jnts\)"\]', ESTIMATE_JS)


def test_the_seal_sf_cell_is_the_polish_one():
    """`sfFieldsFor` sends role seal to AREA_SF_CELLS.Polish. If it fell through to Epoxy it would
    read E20/E24/E34 — cove and second-system cells that mean something else entirely on this
    layout."""
    openpyxl = pytest.importorskip("openpyxl")
    m = re.search(r'Polish:\s*\{ polish_sf: "([A-Z]+\d+)" \}', ESTIMATE_JS)
    assert m, "AREA_SF_CELLS.Polish moved"
    addr = m.group(1)
    wb = openpyxl.load_workbook(TEMPLATES / "estimate_sheet_5.7.xlsx", data_only=False)
    try:
        # B35 rolls the SF input up on all three sheets; that shared plumbing is the evidence the
        # input cell is the same one.
        for sheet in ["Polish"] + SEAL_SHEETS:
            assert wb[sheet]["B35"].value == "=%s" % addr, (
                "%s!B35 is %r, so its SF does not come from %s" % (sheet, wb[sheet]["B35"].value, addr))
    finally:
        wb.close()
    assert re.search(r'role === "seal"\s*\?\s*AREA_SF_CELLS\.Polish', ESTIMATE_JS)


# ── an option that cannot print ───────────────────────────────────────────────
@needs_node
def test_a_template_that_cannot_print_options_says_so(strip):
    """GC Polish, GC Resinous, GC Sealer and Direct Budget have no {{#price_line}} block, so a
    ticked option reaches the customer as nothing at all. Silence there is the complaint from the
    same morning ("There are two options but the PDF Shows one") wearing a different hat."""
    c = strip["cannotPrint"]
    assert c["warnsOnGC"] is True, "a GC job configures an option and is told nothing"
    assert c["quietOnDirect"] is True, "the warning fires on a template that CAN print options"


def test_the_option_capable_list_matches_the_actual_templates():
    """Derived from the .docx files, so annotating a GC template later fails this test until the
    frontend list is updated — which is the right way round. A hand-maintained capability list that
    nothing checks is how the warning starts lying."""
    m = re.search(r"const OPTION_CAPABLE = new Set\(\[([^\]]*)\]\)", ESTIMATE_JS)
    assert m, "OPTION_CAPABLE moved"
    claimed = set(re.findall(r'"([^"]+)"', m.group(1)))

    picker = (pathlib.Path(__file__).resolve().parents[1] / "proposal_writer.py").read_text(encoding="utf-8")
    pairs = re.findall(r'\("(\w+)",\s*(?:"(\w+)"|None)\):\s*"([^"]+)"', picker)
    assert pairs, "TEMPLATE_PICKER moved"

    actual = set()
    for work_type, audience, rel in pairs:
        path = TEMPLATES / rel.replace("/", "\\") if "\\" in str(TEMPLATES) else TEMPLATES / rel
        path = TEMPLATES / rel
        with zipfile.ZipFile(path) as z:
            flat = re.sub(r"<[^>]+>", "", z.read("word/document.xml").decode("utf-8", "replace"))
        if "{{#price_line}}" in flat:
            actual.add("%s:%s" % (work_type, audience or "*"))
    assert claimed == actual, (
        "OPTION_CAPABLE says %s but the templates that actually carry {{#price_line}} are %s"
        % (sorted(claimed), sorted(actual)))


# ── the hand-off sheet ────────────────────────────────────────────────────────
def test_a_seal_option_is_never_reported_as_sold_scope():
    """The Project Info Sheet's second-system block describes what ops must order. An option is an
    alternate the customer was quoted; sealed concrete is ALWAYS an option, so it is never sold
    base scope. Skipped by role rather than by the option flag because tab ORDER is the
    estimator's, so a Seal tab dragged ahead of Polish would otherwise take the slot."""
    import info_sheet_writer as isw

    assert isw._SF_KEYS["seal"] == (("polish_sf",), ("polish_sf",)), (
        "seal is missing from _SF_KEYS, so it silently reads the EPOXY intake keys")
    data = {
        "work_type": "combo",
        "priced_tabs": [
            {"id": "Seal", "role": "seal", "name": "Seal", "sf": {"polish_sf": 9000},
             "system_desc": "Sealed Concrete"},
            {"id": "Polish", "role": "polish", "name": "Polish", "sf": {"polish_sf": 4000},
             "system_desc": "Treadwell Polished Concrete"},
        ],
        "tab_opts": {},
    }
    got = isw._second_system(data, "epoxy")
    assert got is not None, "the polish half of the combo was lost"
    assert "seal" not in str(got).lower(), (
        "a seal tab was reported as the second system: %r" % (got,))


@needs_node
def test_the_seal_role_resolves_to_the_polish_coordinates(strip):
    """The wrong-money hazard, executed. `totalCellsFor`'s else-branch is Epoxy, so a seal tab that
    falls through reads D88 — a cell the Polish layout does not use — and the option is dropped
    downstream by `.filter(o => o.bid.total > 0)` without a word. The harness models each sheet's
    cells BY ADDRESS so the wrong address yields nothing, which is what makes this visible."""
    assert strip["seal"]["price"] == "$8,410"
    assert strip["seal"]["jointsPrice"] == "$9,905"
