"""ROUND 6, PART 3 (2026-10-21), on the real estimate page: what tests/js/travel-round6-part3-harness.js reads off js/polish-estimate.js over the real js/bid-model.js.

M3. AN OPTION MADE THE CARRIER BY A JOB-TYPE SWITCH BRINGS ITS OWN DRIVE, AS A BASE PICK DOES. A far Polish bid (4 x 12, 190 miles) with an Epoxy sheet added as an option (its own crew, 5 x 10);
the x on the Polish carrier's Travel Labor (the job says it has no drive), then Add Travel Labor on the Epoxy option (its own drive, filled on its own crew: 5 guys x 6.5 hours, $1,072.50). Epoxy
is then made the base two ways. The Sheets panel's pick kept the option's line and dropped the job's answer (pickBase's settleTravelAnswer: the new carrier holds a line). The intake's job type
took the line off (followDistance's release of a blank line nobody typed, which is for a section that was OFF) and kept the answer: the same base, $41,410 against $39,350. Now the switch settles
the flag the same way the pick does (sectionsForJob: an option made the carrier brings its own line), and the two paths price, hold and reopen the same. HANZ'S DECISION OF 2026-10-21 stands beside
it: after the carrier's x, a job-type switch keeps the JOB's drive removed (no seed, no carry; Add Travel Labor is the way back): `keeps` holds that a new carrier the switch makes is seeded no line.

M4. THE REVIEW ROW READS TRUE. At the library's own Gyp rate ($33.66) a far Gyp crew of 4 for 120 hours is $16,156.80 of labor, which the sheet rounds UP to $16,157 before it divides: 48.0006
nights, and each line rounded up to the dollar, $3,361 and $2,161. The Review said "48 nights x $70 / night = $3,361", and the working on the Labor step "48 nights x $70.00 = $3,360.04". Both show
the count to as many places as it takes for the count x the rate to come to the cent the price worked out (48.0006: x $70 is $3,360.04, which rounds up to the $3,361 charged) and say the sheet
rounds the dollars up; a whole count (a far Polish 4 x 12 at $33: 48 x $70 = $3,360) reads as it always did.

The last block breaks a COPY of the page or the model one line at a time; a fact above must change.
"""
from __future__ import annotations

import math
import pathlib

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node
from _travel_sequences import PAGE_FILES

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "travel-round6-part3-harness.js"
MODEL = "js/bid-model.js"
PAGE = "js/polish-estimate.js"
SECTIONS = ("m3", "keeps", "m4")
DRIVE = "5 x 6.5 = $1072.5"
ROUNDED = "rounded up to the dollar, as the sheet does"


def run(frontend=FRONTEND):
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr[-1500:]
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    require_node()
    got = run()
    for k in SECTIONS:
        assert "error" not in got[k], "%s threw: %s" % (k, got[k]["error"][:600])
    return got


# ── M3 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_option_holds_its_own_drive_while_the_job_says_it_has_none(ran):
    s = ran["m3"]["start"]
    assert s["x"] is True and s["added"] is True and s["flag"] is True
    assert s["rows"] == {"Polish:base": None, "Epoxy:option": DRIVE}


def test_a_job_type_switch_that_makes_the_option_the_carrier_keeps_its_drive_as_the_base_pick_does(ran):
    """The same base two ways: Epoxy is the carrier, its own line is the job's drive, the job's "no drive" answer is gone, and the bid prices the same, to the dollar (the root is an option after
    the pick and off after the switch, and neither is in the lump sum)."""
    pick, sw = ran["m3"]["pick"], ran["m3"]["switched"]
    assert pick["carrier"] == sw["carrier"] == "Epoxy"
    assert pick["flag"] is False and sw["flag"] is False
    assert pick["rows"] == {"Polish:option": None, "Epoxy:base": DRIVE}
    assert sw["rows"] == {"Polish:off": None, "Epoxy:base": DRIVE}
    assert sw["price"]["lump"] == pick["price"]["lump"] == 41410
    assert sw["price"]["sections"]["Epoxy"] == pick["price"]["sections"]["Epoxy"]


def test_both_paths_reopen_quietly_and_follow_the_next_answer_alike(ran):
    """Each path's draft, reopened from the server (jsonb key order), arms no save and prices as saved; 300 miles typed then fills the one drive by the rule on both (5 guys x 10 hours)."""
    a, b = ran["m3"]["pickReopened"], ran["m3"]["switchReopened"]
    for r in (a, b):
        assert r["quiet"] == {"armed": 0, "saves": 0}
        assert r["rows"]["Epoxy:base"] == DRIVE and r["price"]["lump"] == 41410
        assert r["at300"]["rows"]["Epoxy:base"] == "5 x 10 = $1650"
    assert a["at300"]["price"]["lump"] == b["at300"]["price"]["lump"]


def test_after_the_carriers_x_a_switch_still_seeds_and_carries_no_drive(ran):
    """Hanz, 2026-10-21: after the carrier's x a job-type switch keeps the drive REMOVED. A far Polish bid, the x, then the job type Epoxy: the new Epoxy carrier holds no line (it was never an
    option, so it has none of its own to bring), the job still says it has no drive, and Add Travel Labor is drawn on it: the way back."""
    k = ran["keeps"]
    assert k["x"] is True and k["carrier"] == "Epoxy" and k["flag"] is True
    assert k["rows"] == {"Polish:off": None, "Epoxy:base": None}
    assert k["addShown"] is True


# ── M4 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _money(text):
    return float(text.replace("$", "").replace(",", ""))


def test_the_review_shows_the_count_the_price_used_and_says_the_sheet_rounds_the_dollars_up(ran):
    """48.0006 nights at the library's Gyp rate: the Review's quantity is the count to as many places as the price needs (48.0006), quantity x rate rounds up to the total it shows, and the words
    under the total say the sheet rounds up. The figures are the ones the price charged ($3,361 and $2,161)."""
    g = ran["m4"]["gyp"]
    assert g["nights"] == pytest.approx(16157 / 33.66 / 10) and g["costs"] == {"lodging": 3361, "per_diem": 2161, "total": 5522}
    for key, rate in (("lodging", 70), ("perDiem", 45)):
        row = g[key]
        assert row["qty"] == "48.0006" and row["up"] == ROUNDED, row
        total = _money(row["total"])
        assert total == g["costs"]["lodging" if key == "lodging" else "per_diem"]
        assert math.ceil(round(float(row["qty"]) * rate, 9)) == total, "quantity x rate does not come to the total: %r" % (row,)


def test_the_working_on_the_labor_step_reads_true_too(ran):
    """The same two lines in the working under the travel block: the count to the places it needs, times the rate, is the product it prints to the cent, and that is rounded up to the charge."""
    w = ran["m4"]["gyp"]["working"]
    assert w["lodging"] == "Lodging: 48.0006 nights (follows the labor) x $70.00 = $3,360.04, rounded up to $3,361"
    assert w["perDiem"] == "Per Diem: 48.0006 days (follows the labor) x $45.00 = $2,160.03, rounded up to $2,161"
    p = ran["m4"]["polish"]["working"]
    assert p["lodging"] == "Lodging: 48 nights (follows the labor) x $70.00 = $3,360.00"


def test_a_whole_count_reads_as_it_always_did(ran):
    """A far Polish bid at $33 a man-hour: 48 nights exactly, 48 x $70 = $3,360 and 48 x $45 = $2,160, and nothing is said under the totals."""
    p = ran["m4"]["polish"]
    assert p["nights"] == 48
    assert (p["lodging"]["qty"], p["lodging"]["total"], p["lodging"]["up"]) == ("48", "$3,360", "")
    assert (p["perDiem"]["qty"], p["perDiem"]["total"], p["perDiem"]["up"]) == ("48", "$2,160", "")


# ── red without the code: break a COPY of the page or the model one line at a time ──────────────────────────────────────────────────────────────────────────────
OPTION_BRINGS_ITS_DRIVE = ("    if (out !== model && out.no_travel_labor === true && held.some(function (e) { return e.kind === \"option\" && e.tab === carrierTabOf(out); })) "
                           "settleTravelAnswer(out);")
REVIEW_QTY_TEXT = "      var shown = B.travelQtyShown(qty, tl.rate, cost);"
WORKING_QTY = '      lines.push(names[k] + ": " + travelQtyShown(q, l.rate, cost).text + (k === "lodging" ? " nights" : " days") +'
REVIEW_UP = "                    rv(\"trv.\" + k + \".tot\", moneyAuto(cost)) + '<span class=\"note work\">' + rv(\"trv.\" + k + \".up\", shown.roundedUp ? ROUNDED_UP : \"\") + '</span>']);"

# name -> (file, old, new, a fact that must change)
BREAKS = {
    "a job-type switch takes the option's own drive off its new carrier": (
        MODEL, OPTION_BRINGS_ITS_DRIVE, "    void held;",
        lambda g: g["m3"]["switched"]["rows"]["Epoxy:base"] != DRIVE or g["m3"]["switched"]["price"]["lump"] != g["m3"]["pick"]["price"]["lump"]),
    "the Review shows the count to two places": (
        PAGE, REVIEW_QTY_TEXT, "      var shown = { text: B.fmtSf(B.num(qty)), roundedUp: B.travelQtyShown(qty, tl.rate, cost).roundedUp };",
        lambda g: g["m4"]["gyp"]["lodging"]["qty"] != "48.0006"),
    "the Review does not say the sheet rounds the dollars up": (
        PAGE, REVIEW_UP, "                    rv(\"trv.\" + k + \".tot\", moneyAuto(cost))]);",
        lambda g: g["m4"]["gyp"]["lodging"]["up"] != ROUNDED),
    "the working shows the count to two places": (
        MODEL, WORKING_QTY, '      lines.push(names[k] + ": " + qty(q) + (k === "lodging" ? " nights" : " days") +',
        lambda g: not str(g["m4"]["gyp"]["working"]["lodging"]).startswith("Lodging: 48.0006 nights")),
}


def test_no_fact_a_break_looks_for_is_already_changed_on_the_real_tree(ran):
    already = sorted(name for name, (_rel, _old, _new, noticed) in BREAKS.items() if noticed(ran))
    assert already == [], "these breaks are noticed on the real tree, so they prove nothing: %s" % already


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_scenarios_go_red_when_the_page_or_the_model_changes(tmp_path, name):
    """Each change is a line a fact above depends on, broken in a scratch copy; a FACT must change. A break that stops the harness, or makes a section throw, is not counted as noticed."""
    require_node()
    rel, old, new, noticed = BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, PAGE_FILES)
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the break stopped the harness outright, so no fact noticed it: " + name + "\n" + proc.stderr[-600:]
    got = last_json_line(proc.stdout)
    crashed = sorted(k for k in SECTIONS if "error" in got.get(k, {}))
    assert not crashed, "the break crashed %s instead of changing a fact: %s" % (", ".join(crashed), name)
    assert noticed(got), "the scenarios did not notice: " + name
