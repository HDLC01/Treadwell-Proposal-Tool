"""THE NIGHTS EVERY TAB COUNTS, PROVED AGAINST KYLE'S WORKBOOK (round 6, part 3, M2, 2026-10-21).

Kyle's tabs count the nights of lodging, and the same days of per diem, from the labor DOLLARS of the tab: Epoxy!B65 `=IF(B4="No",((D53-D52)/C47)/8)`, Polish!B58 and the two
Seal tabs `=IF(B4="No",((D45-D44)/C37)/8)`, Leveling!B61 `=IF(B4="No",((D49-D48)/C44)/8)` (a ten hour day, still divided by 8), and the per diem days are the same figure (`=B65`,
`=B58`, `=B61`): the labor total rounded up to the dollar, less the drive, over the FIRST crew row's rate, over 8. Round 6 counted that way on a Polish section priced by rev 2 or 3
and on every Gyp section (Gyp!B64, over 10), and counted PEOPLE (guys x days) on an Epoxy carrier, on an Epoxy, Seal, Seal (+Jnts) or Leveling option and on a Polish sheet that is an
option, while the words said each tab is counted its own way. A head count is the sheet's figure only while every row is paid the first row's rate, a day is 8 hours and the labor
comes to a whole dollar: a row paid $48 beside $33 rows reads as more days on the sheet (20.82 nights for a crew whose head count is 19), and a Leveling day is ten hours still divided
by 8 (18.75 nights for 15 man-days).

THE PROOF (tests/js/tab-nights-proof-harness.js): the oracle's own lodging vectors (tests/fixtures/oracle/<slug>.json, recorded from the template: four crews, far and local) priced
as a v2 SECTION of each tab with the nights left to follow (a new bid's lines, empty and off auto, and the model's own distance answer, so nothing is typed into them): Epoxy as
the carrier and as an option, Seal, Seal (+Jnts) and Leveling as options (they are never a base), and Polish as the root that carries the job's travel and as a sheet under `tabs`
that is an option. Every far line follows the labor; every nights figure is the workbook's to 1e-9 and every dollar is the workbook's to the cent (the labor the rows come to, the
Lodging, the Per Diem and the section's travel line); a local job charges nothing. The polish-legacy profile (a saved bid's Polish) counts people, as it always has.

HANZ, 2026-10-21: "Let them re-price". Every v2 bid is still a test copy, so a saved v2 bid whose lines FOLLOW the labor, or whose option counts its own nights, is charged by this rule
the next time it is priced; a figure the estimator typed is theirs and does not move.

The last block breaks a scratch copy of the model (or the profiles) one line at a time, and the proof has to notice.
"""
from __future__ import annotations

import pathlib

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node
from _oracle_support import ORACLE

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "tab-nights-proof-harness.js"
MODEL = "js/bid-model.js"
PROFILES = "js/bid-profiles.js"
# The five tabs and the roles each is priced in (Seal, Seal (+Jnts) and Leveling are options, never a base).
ROLES = {"Epoxy": {"carrier", "option"}, "Seal": {"option"}, "Seal (+Jnts)": {"option"}, "Leveling": {"option"}, "Polish": {"carrier", "option"}}


def run(frontend=FRONTEND):
    proc = run_node(HARNESS, frontend, ORACLE)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr[-1500:]
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    require_node()
    return run()


def test_every_lodging_vector_of_the_five_tabs_is_the_workbooks_to_the_cent_through_a_v2_section(ran):
    """Eight vectors a tab (four crews, far and local), in every role the tab can be priced in: 56 sections, 28 of them far. Nothing is skipped, and nothing differs."""
    cases = ran["cases"]
    assert {(c["tab"], c["role"]) for c in cases} == {(t, r) for t, roles in ROLES.items() for r in roles}
    assert len(cases) == 56 and sum(1 for c in cases if c["far"]) == 28
    wrong = ["%s %s %s: %s" % (c["tab"], c["role"], c["id"], "; ".join(c["wrong"])) for c in cases if c["wrong"]]
    assert wrong == [], "\n".join(wrong)
    for c in cases:
        if c["far"]:
            assert c["nights"] == pytest.approx(c["sheetNights"], abs=1e-9), c
        else:
            assert (c["lodging"], c["perDiem"], c["travel"]) == (0, 0, 0), c


def test_the_proof_tells_the_sheets_dollars_from_a_head_count_on_every_tab(ran):
    """Not vacuous: on every tab, in every role, a far crew whose head count is NOT the workbook's figure is among the vectors (the $48 row on every tab; every crew on Leveling, whose ten
    hour day is still divided by 8), so a model that counted people would fail this proof. 18.75 nights for 3 guys for 5 days on Leveling: $1,313 of hotel where a head count charges $1,050."""
    far = [c for c in ran["cases"] if c["far"]]
    for tab, roles in ROLES.items():
        for role in roles:
            differs = [c["id"] for c in far if c["tab"] == tab and c["role"] == role and (c["people"]["lodging"], c["people"]["perDiem"]) != (c["sheet"]["lodging"], c["sheet"]["perDiem"])]
            assert "lodging/mixedRates/local0" in differs, (tab, role, differs)
    leveling = {c["id"]: c for c in far if c["tab"] == "Leveling"}
    assert leveling["lodging/one/local0"]["lodging"] == 1313 and leveling["lodging/one/local0"]["people"]["lodging"] == 1050
    assert sorted(i for i, c in leveling.items() if c["people"]["nights"] != pytest.approx(c["sheetNights"], abs=1e-9)) == sorted(leveling)


def test_a_saved_bids_legacy_polish_counts_people_as_it_always_has(ran):
    """The polish-legacy profile is left as it is: a Polish section priced by it (a bid saved before Phase 17), the root or a sheet that is an option, charges the head count, 19 nights for
    the crew the sheet counts as 20.82."""
    legacy = ran["legacy"]
    assert len(legacy) == 8
    for c in legacy:
        assert c["nights"] == c["people"], c
    assert {c["role"] for c in legacy if c["nights"] != pytest.approx(c["sheetNights"], abs=1e-9)} == {"carrier", "option"}


# ── red without the code: break a COPY of the model one line at a time ───────────────────────────────────────────────
COUNTS_ITS_TAB = "    return entry.layout === \"polish\" ? null : profileOf(entry);"
OPTION_COUNTS = "    return sectionNights(model, entry).count;"

MUTATIONS = {
    "Epoxy, Seal and Leveling count people again": (MODEL, COUNTS_ITS_TAB, "    return null;", lambda g: any(c["wrong"] for c in g["cases"] if c["tab"] in ("Epoxy", "Leveling"))),
    "a saved bid's legacy Polish counts the sheet's dollars": (MODEL, COUNTS_ITS_TAB, "    return profileOf(entry);",
                                                              lambda g: any(c["nights"] != c["people"] for c in g["legacy"])),
    "an option counts its people and not its tab's dollars": (MODEL, OPTION_COUNTS, "    return sectionNights(model, entry).days;",
                                                              lambda g: any(c["wrong"] for c in g["cases"] if c["role"] == "option")),
    "Leveling's nights are divided by its ten hour day": (PROFILES, "      quirks: { escalationInSubtotal: false, dayHours: 10 },",
                                                          "      quirks: { escalationInSubtotal: false, dayHours: 10, lodgingDivisor: 10 },",
                                                          lambda g: any(c["wrong"] for c in g["cases"] if c["tab"] == "Leveling")),
}


def test_no_fact_a_break_looks_for_is_already_changed_on_the_real_tree(ran):
    already = sorted(name for name, (_rel, _old, _new, noticed) in MUTATIONS.items() if noticed(ran))
    assert already == [], "these breaks are noticed on the real tree, so they prove nothing: %s" % already


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_the_proof_goes_red_when_the_code_changes(tmp_path, name):
    require_node()
    rel, old, new, noticed = MUTATIONS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, [MODEL, PROFILES])
    assert noticed(run(frontend)), "the proof did not notice: " + name
