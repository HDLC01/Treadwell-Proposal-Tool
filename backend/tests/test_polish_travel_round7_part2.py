"""ROUND 7, PART 2 (2026-10-21), on the real estimate page: what tests/js/travel-round7-part2-harness.js reads off js/polish-estimate.js over the real js/bid-model.js (every reopen a jsonb one).

L1. A WHOLE COUNT IS NOT CALLED ROUNDED. At the library's own Gyp rate ($33.66) a far Gyp crew of 4 for 125 hours is $16,830 of labor, and with its drive (4 x 6.5 x $33 = $858, Hanz's D2 of
2026-10-21) the sheet counts (17,688 - 858) / 33.66 / 10 = 50 nights, which floating point carries as 50.00000000000001. 50 x $70 is $3,500 and the line is charged $3,500: nothing was rounded.
The Review said nothing under the total, and the working on the Labor step said "$3,500.00, rounded up to $3,500", because it compared the bare product (3,500.0000000000005) with the charge. Both
now take travelQtyShown's own verdict (the product to twelve figures against the charge), so the two never disagree.

L2. ONE COUNT, SHOWN ONE WAY. A far Epoxy crew of 5 for 10 days, with its drive (5 x 6.5 x $33 = $1,072.50), counts 50 + 0.5 / 264 = 50.0019 nights the sheet's way (round 6, part 3, M2):
the drive's half dollar rides the sheet's round-up. Lodging at $70 needs four places to read true ("50.002" x $70 is $3,500.14, the price worked out $3,500.13) and Per Diem at $45 needs three, so
the Review showed the one count as 50.0019 nights beside 50.002 days, and so did the working. The two lines charge the same count, and it is now shown to the places the line that needs the most
needs, on both rows of the Review and in both lines of the working. A count the estimator typed on one line is that line's own and is shown its own way (Lodging typed 10, Per Diem 50.002).

G1. A GYP BASE'S DRIVE FILLS FROM THE MILES (Hanz's D2 of 2026-10-21; built in part 1, tests/test_polish_travel_round7.py), and the two things the law also says that part 1's page tests did not
hold: a drive the estimator TYPED on a Gyp base stays typed through every distance answer and a reload, and a far Gyp OPTION (a copy of the Gyp sheet) prices its own drive on its own crew, follows
the answers, and gives a fill nobody touched back whole under 70 miles, like any option. Before part 1 a Gyp option's drive was never filled (followDistanceOptions skipped every Gyp section).

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
HARNESS = TESTS / "js" / "travel-round7-part2-harness.js"
MODEL = "js/bid-model.js"
PAGE = "js/polish-estimate.js"
SECTIONS = ("whole", "same", "gypTyped", "gypOption")
ROUNDED = "rounded up to the dollar, as the sheet does"
GYP = 'Gyp (USG 1-8")'
GYP_FILLED = "4 x 6.5 = $858"
TYPED = "3 x 5 = $495"


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


def _money(text):
    return float(text.replace("$", "").replace(",", ""))


def _reads_true(row, rate):
    """The row's quantity, as it is shown, times its rate rounds up to the total it shows (to twelve figures, as the sheet's ROUNDUP is guarded)."""
    return math.ceil(round(float(row["qty"].replace(",", "")) * rate, 9)) == _money(row["total"])


# ── L1 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_whole_count_carries_float_noise_so_the_case_is_not_vacuous(ran):
    """The count is 50 to the cent of every charge and not 50 to the last bit: the case the bare product compared false on. The drive is the Gyp crew's own (D2)."""
    w = ran["whole"]
    assert w["nights"] != 50 and abs(w["nights"] - 50) < 1e-9, w["nights"]
    assert w["nights"] * 70 != 3500, "the product is whole to the last bit, so nothing here could have read as rounded"
    assert w["costs"] == {"lodging": 3500, "per_diem": 2250, "total": 5750}
    assert w["drive"][GYP + ":base"] == GYP_FILLED


def test_a_whole_count_is_not_called_rounded_on_the_labor_step_or_the_review(ran):
    """THE FINDING (round 6 lows, L1): the working said "$3,500.00, rounded up to $3,500" where nothing was rounded, and the Review row beside the same figure said nothing. Now neither says it."""
    w = ran["whole"]
    assert w["working"]["lodging"] == "Lodging: 50 nights (follows the labor) x $70.00 = $3,500.00"
    assert w["working"]["perDiem"] == "Per Diem: 50 days (follows the labor) x $45.00 = $2,250.00"
    assert (w["lodging"]["qty"], w["lodging"]["total"], w["lodging"]["up"]) == ("50", "$3,500", "")
    assert (w["perDiem"]["qty"], w["perDiem"]["total"], w["perDiem"]["up"]) == ("50", "$2,250", "")


def test_the_labor_step_and_the_review_never_disagree_about_rounding(ran):
    """The one verdict, on every line of every case this file draws: the working says "rounded up" exactly where the Review says the sheet rounded the dollars up."""
    cases = [ran["whole"], ran["same"]["both"], ran["same"]["typed"], ran["same"]["reloaded"]]
    for c in cases:
        for key, name in (("lodging", "Lodging"), ("perDiem", "Per Diem")):
            said = ", rounded up to " in (c["working"][key] or "")
            assert said == (c[key]["up"] == ROUNDED), (name, c["working"][key], c[key])


# ── L2 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_one_count_is_shown_one_way_on_both_review_rows(ran):
    """50.0019 nights and 50.0019 days, where the Review showed 50.0019 beside 50.002: the places the Lodging line needs, on both. Each row still reads true: its quantity times its rate rounds up to
    the total it shows, and the sheet's round-up is said under both."""
    s = ran["same"]["both"]
    assert s["nights"] == pytest.approx(50 + 0.5 / 264) and s["costs"] == {"lodging": 3501, "per_diem": 2251, "total": 5752}
    assert s["lodging"]["qty"] == "50.0019" and s["perDiem"]["qty"] == "50.0019"
    for key, rate in (("lodging", 70), ("perDiem", 45)):
        assert s[key]["up"] == ROUNDED and _reads_true(s[key], rate), s[key]


def test_one_count_is_shown_one_way_in_the_working_too(ran):
    s = ran["same"]["both"]["working"]
    assert s["lodging"] == "Lodging: 50.0019 nights (follows the labor) x $70.00 = $3,500.13, rounded up to $3,501"
    assert s["perDiem"] == "Per Diem: 50.0019 days (follows the labor) x $45.00 = $2,250.09, rounded up to $2,251"


def test_a_count_typed_on_one_line_is_that_lines_own(ran):
    """Lodging typed as 10 nights: it is not the count Per Diem charges, so each is shown its own way, Per Diem to the three places its own charge needs. A reload reads the same."""
    t = ran["same"]["typed"]
    assert (t["lodging"]["qty"], t["lodging"]["total"], t["lodging"]["up"]) == ("10", "$700", "")
    assert (t["perDiem"]["qty"], t["perDiem"]["total"], t["perDiem"]["up"]) == ("50.002", "$2,251", ROUNDED) and _reads_true(t["perDiem"], 45)
    assert t["working"] == {"lodging": "Lodging: 10 nights (typed) x $70.00 = $700.00",
                            "perDiem": "Per Diem: 50.002 days (follows the labor) x $45.00 = $2,250.09, rounded up to $2,251"}
    r = ran["same"]["reloaded"]
    assert {k: r[k] for k in ("lodging", "perDiem", "working", "costs")} == {k: t[k] for k in ("lodging", "perDiem", "working", "costs")}


# ── G1 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_drive_typed_on_a_gyp_base_stays_typed_through_every_answer_and_a_reload(ran):
    """Far Gyp 4 x 120: the drive the miles fill (4 x 6.5, D2), then 3 guys x 5 hours typed over it. 300 miles, 50 and 190 move nothing typed, a jsonb reload prices and holds the same, and 300
    miles typed after the reload moves nothing either."""
    g = ran["gypTyped"]
    assert g["filled"]["rows"][GYP + ":base"] == GYP_FILLED and g["filled"]["marks"]["follow"] == "crew"
    assert g["typed"]["rows"][GYP + ":base"] == TYPED
    assert g["typed"]["marks"]["guysTyped"] is True and g["typed"]["marks"]["hoursTyped"] is True and g["typed"]["marks"]["auto"] is False
    for miles, rows in g["answers"].items():
        assert rows[GYP + ":base"] == TYPED, miles
    assert g["reloaded"] == g["typed"]
    assert g["reloadedAt300"][GYP + ":base"] == TYPED


def test_a_far_gyp_option_prices_its_own_drive_on_its_own_crew(ran):
    """A copy of a far Gyp base is an option priced apart, and its Travel Labor is its own: the copy holds the drive the tool filled (4 x 6.5), and with its own crew typed (6 guys for 100 hours)
    its drive follows its own guys, 6 x 6.5 = $1,287, inside the option's own labor ($19,800 + $1,287). A jsonb reload prices the same."""
    o = ran["gypOption"]
    assert o["made"]["copy"] == "Copy1"
    assert o["made"]["rows"] == {"Polish:off": "1.5 x  = $0", GYP + ":base": GYP_FILLED, "Copy1:option": GYP_FILLED}
    assert o["made"]["marks"] == {"auto": True, "follow": "crew", "seed": 6.5, "guysTyped": False, "hoursTyped": False}
    assert o["own"]["rows"]["Copy1:option"] == "6 x 6.5 = $1287" and o["own"]["rows"][GYP + ":base"] == GYP_FILLED
    assert o["own"]["drive"] == 1287 and o["own"]["labor"] == 6 * 100 * 33 + 1287
    assert o["own"]["price"]["sections"]["Copy1"] == 55847 and o["own"]["price"]["lump"] == 44321
    assert o["reloaded"] == {"rows": o["own"]["rows"], "price": o["own"]["price"]}


def test_a_far_gyp_options_drive_follows_the_answers_and_a_local_one_gives_it_back_whole(ran):
    """300 miles: each drive goes to its own crew x 10 hours (the base 4, the option 6), in the session and after a reload alike. 50 miles: the base's hours go back (its crew marker stays) and the
    option's fill, which nobody touched, goes back whole: no guys, no hours, no marker."""
    o = ran["gypOption"]
    s = o["at300"]["session"]
    assert s["rows"]["Copy1:option"] == "6 x 10 = $1980" and s["rows"][GYP + ":base"] == "4 x 10 = $1320"
    assert o["at300"]["reload"] == s
    assert o["local"]["Copy1:option"] == " x  = $0" and o["local"][GYP + ":base"] == "4 x  = $0"
    assert o["localMarks"] == {"auto": False, "follow": None, "seed": None, "guysTyped": False, "hoursTyped": False}


# ── red without the code: break a COPY of the page or the model one line at a time ──────────────────────────────────────────────────────────────────────────────
WORKING_UP = "        (shownAt[k].roundedUp ? money2(prod) + \", rounded up to \" + money(cost) : money2(cost)) +"
REVIEW_SHARED = "      var shown = shownTrv[k];"

# name -> (file, old, new, a fact that must change)
BREAKS = {
    # --- L1 ---
    "the working compares the bare product with the charge": (
        MODEL, WORKING_UP, "        (prod === cost ? money2(cost) : money2(prod) + \", rounded up to \" + money(cost)) +",
        lambda g: g["whole"]["working"]["lodging"] != "Lodging: 50 nights (follows the labor) x $70.00 = $3,500.00"),
    "the verdict is not taken to twelve figures": (
        MODEL, "    return { text: text, roundedUp: parseFloat((q * r).toPrecision(12)) !== c };", "    return { text: text, roundedUp: q * r !== c };",
        lambda g: g["whole"]["lodging"]["up"] != "" or g["whole"]["working"]["lodging"] != "Lodging: 50 nights (follows the labor) x $70.00 = $3,500.00"),
    # --- L2 ---
    "the Review shows each line its own way": (
        PAGE, REVIEW_SHARED, "      var shown = B.travelQtyShown(trvLines[k].qty, trvLines[k].rate, trvLines[k].cost);",
        lambda g: g["same"]["both"]["perDiem"]["qty"] != "50.0019"),
    "the working shows each line its own way": (
        MODEL, "    var shownAt = travelQtysShown(charged);", "    var shownAt = {}; Object.keys(charged).forEach(function (k) { shownAt[k] = travelQtyShown(charged[k].qty, charged[k].rate, charged[k].cost); });",
        lambda g: not str(g["same"]["both"]["working"]["perDiem"]).startswith("Per Diem: 50.0019 days")),
    "a count is shown the way another line's count needs": (
        MODEL, "        return o !== l && num(o.qty) === num(l.qty);", "        return o !== l;",
        lambda g: g["same"]["typed"]["perDiem"]["qty"] != "50.002"),
    "the text need not read true for the other line": (
        MODEL, "      return charges.every(function (ch) { return cents(v * ch.r) === cents(q * ch.r) && roundUp(v * ch.r) === ch.c; });",
        "      return cents(v * r) === cents(q * r) && roundUp(v * r) === c;",
        lambda g: g["same"]["both"]["perDiem"]["qty"] != "50.0019" or not str(g["same"]["both"]["working"]["perDiem"]).startswith("Per Diem: 50.0019 days")),
    # --- G1 ---
    "a far answer writes over hours the estimator typed": (
        MODEL, "    var fills = !row.hours_typed && (isBlank(row.days) || wrote);", "    var fills = true;",
        lambda g: any(rows[GYP + ":base"] != TYPED for rows in g["gypTyped"]["answers"].values())),
    "a Gyp option is left out of the answers again (the line part 1 took out)": (
        MODEL, "      if (e.kind !== \"option\" || drives.indexOf(e.tab) >= 0 || !isObject(e.section)) return;",
        "      if (e.kind !== \"option\" || drives.indexOf(e.tab) >= 0 || e.layout === \"gyp\" || !isObject(e.section)) return;",
        lambda g: g["gypOption"]["at300"]["session"]["rows"]["Copy1:option"] != "6 x 10 = $1980" or g["gypOption"]["local"]["Copy1:option"] != " x  = $0"),
    "an option's drive follows the biggest crew of the bases": (
        MODEL, 'if (r && r.unit === "hours" && r.guys_auto) r.guys = followsCrew(r) ? ownCrewSize(model, lines) : manDays;',
        'if (r && r.unit === "hours" && r.guys_auto) r.guys = followsCrew(r) ? crewSize(model) : manDays;',
        lambda g: g["gypOption"]["own"]["rows"]["Copy1:option"] != "6 x 6.5 = $1287" and g["gypOption"]["at300"]["session"]["rows"]["Copy1:option"] != "6 x 10 = $1980"),
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
