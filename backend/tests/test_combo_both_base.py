"""On a combo job, Epoxy AND Polish are both the base bid.

Hanz, 2026-08-12, with a screenshot of Estimate Review's "BASE BID & OPTIONS" strip:
"If thge work type is combo both epoxy and polish are base bids."

The money has always agreed with him. With no sheet explicitly picked, the lump sum sums Epoxy +
Polish and the proposal prints the pair as Option 1 / Option 2. The strip was the only thing that
disagreed: it rendered Epoxy's radio CHECKED with a "base bid" tag through the `soloBase` fallback
and offered Polish as "add as option", so the screen described a one-system bid while charging for
two. Clicking the radio that already looked checked then collapsed the sum to epoxy alone, dropped
the breakout, and this screen had no control to undo it — only the Proposal screen could.

Two more defects fell out of the same reading:

* the rooms snapshot had no exclusion for a base sheet, so ticking "add as option" on Polish in a
  combo put Polish in the base sum AND listed it as an extra — the same work quoted twice. It only
  looked harmless because the Proposal screen rebuilds rooms on load and drops it there.
* there was no way back from a narrowed combo on this screen at all.

Executed, not grepped: the bug lived in rendered markup while both halves of the source read
correctly, and a source assertion cannot see which radio carries `checked`.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = REPO / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "combo-base-harness.js"
ESTIMATE = (FRONTEND / "js" / "estimate-review.js").read_text(encoding="utf-8")
PROPOSAL = (FRONTEND / "js" / "proposal-review.js").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def strip():
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── the ask ───────────────────────────────────────────────────────────────────
def test_both_sheets_are_tagged_as_the_base_bid(strip):
    """His sentence, as an assertion."""
    d = strip["comboDefault"]
    assert d["epoxy"]["tagged"] is True, d["epoxy"]
    assert d["polish"]["tagged"] is True, d["polish"]


def test_neither_base_sheet_is_offered_as_an_option_against_itself(strip):
    """"add as option" on Polish used to build rooms with Polish in the base sum AND listed as an
    extra. A sheet cannot be an option against a bid it is part of."""
    d = strip["comboDefault"]
    assert d["epoxy"]["offersOption"] is False
    assert d["polish"]["offersOption"] is False
    assert d["epoxy"]["partOfBase"] and d["polish"]["partOfBase"], d


def test_a_copy_sheet_is_still_an_ordinary_option(strip):
    """The exclusion is the base PAIR, not "everything on a combo". Room 1 must keep its
    controls — that is how a combo bid carries extras."""
    assert strip["comboDefault"]["copy"]["offersOption"] is True
    assert strip["comboDefault"]["copy"]["tagged"] is False


def test_the_combined_chip_is_checked_and_priced_at_the_sum(strip):
    """One control saying what is actually being charged. $29,942 + $15,801."""
    d = strip["comboDefault"]
    assert d["combinedPresent"] and d["combinedChecked"] and d["combinedTagged"], d
    assert d["combinedPrice"] == "$45,743", d["combinedPrice"]


def test_the_strip_does_not_write_a_base_into_a_combo_draft(strip):
    """`base_tab_id` null IS the combined bid. Persisting a resolved base here would collapse the
    sum on the next load — the destructive click, without the click."""
    assert strip["comboDefault"]["wroteBase"] is False
    assert strip["comboDefault"]["stateBase"] is None


def test_the_legend_says_a_combo_is_both_sheets(strip):
    assert strip["comboDefault"]["hint"] is True


# ── narrowing, and the way back ───────────────────────────────────────────────
def test_picking_one_sheet_still_narrows_the_bid(strip):
    """Deliberate narrowing stays: a combo estimate can be sent as epoxy alone."""
    n = strip["comboNarrowed"]
    assert n["epoxy"]["tagged"] and n["epoxy"]["checked"], n["epoxy"]
    assert n["polish"]["offersOption"] is True, n["polish"]
    assert n["polish"]["tagged"] is False


def test_there_is_a_way_back_to_both(strip):
    """The half of this that was purely destructive. One click narrowed a combo permanently on
    this screen; the combined chip is offered, unchecked, whenever a single sheet is picked."""
    n = strip["comboNarrowed"]
    assert n["combinedOffered"] is True
    assert n["combinedChecked"] is False


def test_the_radio_round_trips_null_to_a_sheet_and_back(strip):
    """Executed through the real #bid-bar change handler, because `value=""` → null is the whole
    mechanism of the way back."""
    r = strip["roundTrip"]
    assert r["handlerFound"] is True
    assert r["before"] is None
    assert r["narrowed"] == "Epoxy"
    assert r["back"] is None, "the combined chip did not restore the pair"


# ── the predicate ─────────────────────────────────────────────────────────────
def test_the_pair_is_exactly_the_two_base_kind_sheets(strip):
    """Not copies (they are extras), not gyp (a gyp variant is priced on every job, so a loose
    predicate would tag a sheet nobody bid), and — since 2026-08-13 — not the two SEAL sheets,
    which are `kind: "base"` template tabs and were swept in by the old `role !== "gyp"` test the
    moment seal became a priced role. Equality, not a subset, so the next priced system cannot
    join the pair by default either."""
    assert dict(strip["predicate"]["combo"]) == {
        "Epoxy": True, "Polish": True, "Copy1": False, "Gyp": False,
        "Seal": False, "Seal (+Jnts)": False, "Leveling": False}


def test_an_explicit_pick_dissolves_the_pair(strip):
    assert set(dict(strip["predicate"]["narrowed"]).values()) == {False}


def test_a_single_system_job_has_no_pair(strip):
    assert set(dict(strip["predicate"]["epoxyJob"]).values()) == {False}


# ── nothing else moved ────────────────────────────────────────────────────────
@pytest.mark.parametrize("wt", ["epoxy", "polish", "gyp"])
def test_a_single_system_job_renders_exactly_as_before(strip, wt):
    """One base bid, no combined chip, the base persisted into the draft, legend untouched."""
    j = strip["job_" + wt]
    assert j["combinedChip"] is False
    assert j["taggedCount"] == 1, j
    assert j["stateBase"], "a single-system job must persist its resolved base"
    assert j["hintRewritten"] is False


def test_one_predicate_serves_the_strip_and_the_rooms_snapshot():
    """Two copies of this rule is how the screen and the money came apart in the first place."""
    assert ESTIMATE.count("function isInCombinedBase(") == 1
    assert "isPartOfAutoBase = isInCombinedBase" in ESTIMATE
    assert "!isInCombinedBase(t)" in ESTIMATE, (
        "the rooms snapshot no longer excludes the combined base sheets")
    # And the Proposal screen applies the same rule. It used to spell the condition out inline as
    # `t.kind === "base"`, which was only ever right because epoxy/polish/copies were the whole
    # world: both seal sheets are base-kind too, so that inline test dropped a Seal option from
    # every combo proposal while this screen went on listing it. Now both screens name the roles.
    assert "!inCombinedBase(t)" in PROPOSAL, (
        "the proposal screen's exclusion moved — it must share the named-role predicate")
    for src, name in ((ESTIMATE, "estimate-review.js"), (PROPOSAL, "proposal-review.js")):
        assert re.search(r'COMBINED_BASE_ROLES = new Set\(\["epoxy", "polish"\]\)', src), name


def test_the_estimate_screen_no_longer_fakes_a_single_base_on_combo():
    """The mechanism of the original lie, named so it cannot come back quietly."""
    m = re.search(r"const soloBase = ([^;]+);", ESTIMATE)
    assert m, "soloBase moved"
    assert "comboBoth" in m.group(1), (
        "soloBase applies on a combo again — Epoxy would render as the sole base bid")
