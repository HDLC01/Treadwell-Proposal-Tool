"""THE JOB'S ONE DRIVE, OVER EVERY SEQUENCE OF SWITCHES, part 2 of 4: what the estimator said, and the Sheets panel.

Part 1 (test_polish_travel_sequences.py) walks a new far bid whose Travel Labor nobody touched. This walks the cases the third audit (2026-10-20, of 7d32336) found
the settling did not hold:

  typed, clearHours, clearGuys, off   the estimator's own say on the carrier's Travel Labor row (3 guys x 5 hours typed; the Hours box cleared; the Guys box cleared; the
                      row switched off) before any switch: through EVERY sequence of job types after it, the row is the carrier's, as they left it, and on no other section.
                      "Typed, cleared and switched-off are the estimator's, are never refilled, and follow the job's drive when the carrier changes." At 7d32336 the typed 3 x 5
                      stayed behind on the old carrier while the new one was filled beside it ($858 + $495), and a cleared or switched-off row read $858 on the new carrier.
  rate                (the fourth audit, 2026-10-20, of c0255de) a RATE typed over the line's $33 ($40) with the guys and the hours left on the distance: the typed rate is the
                      estimator's too, and follows the job's drive to every carrier as typed guys and hours do ($40 read $33 on Epoxy).
  mixed               the same say-sos (the rate too), applied ONCE anywhere along the sequence instead of at the start.
  sheets              the four job types AND the Sheets panel: every base change it offers (a sheet, or the Epoxy + Polish pair) and a copy of the carrier (an option, which
                      is priced apart and carries its own row). The base's Travel Labor is judged by the same rules; an option's is its own.
  sheetsTyped, ...    the Sheets walk with the estimator's say on the carrier's row first: a copy carries that row too, and made a base it must not price the drive twice.
  said                (round 7, part 3: the round-7 audit's F1) the sequences that copy the say onto a SECOND base, each after each of the five say-sos: far Polish, an Epoxy sheet
                      added and made the base (the job's one drive follows it as a copy), then Combo by the job type or by the pair; far Epoxy and a Polish sheet the same way; and a
                      copy of the Polish sheet made the pair with Epoxy after the job's drive went to Epoxy. SAID_TWICE: what was said once of one crew is on one base;
                      COPY_TRIP (round 7, part 4, P1): the copy given back keeps the trip, the hours and the rate the estimator typed, on its own crew's guys.
  typed@local, ...    the estimator's say on a 40 mile job, and on one whose distance could not be found (typed hours are priced there: typing lifts the grey).
  nightsTyped         (round 6, N4) the estimator's say on the job's NIGHTS: Lodging typed as 10 and Per Diem typed over and cleared, on the Labor step of the carrier, before any
                      switch. "Typed lines are the estimator's": through every sequence of job types and crews after it, on a far job, a 40 mile one and one with no distance, Lodging
                      still holds 10 and Per Diem still holds nothing, both typed, off auto, with no follow marker. No answer fills them, no crew or carrier change follows them.

Every step is judged by travel-sequence-harness.js's rules (see _travel_sequences.RULES): one priced drive, no man-days row, a far carrier always has its row, nothing
filled on a Gyp carrier, no filled row left on a section that is not the carrier, the estimator's row on the carrier, and a plain reopen that changes and saves nothing and
shows the price the draft saved.
"""
import pytest

from _node import require_node
from _travel_sequences import explain, run


@pytest.mark.parametrize("variant", ["typed", "clearHours", "clearGuys", "off", "rate"])
def test_what_the_estimator_said_on_travel_labor_follows_the_carrier_through_every_sequence_of_job_types(variant):
    """Four starts (Polish, Epoxy, Combo, Gyp), the estimator's say applied to the carrier's row, then every sequence of the four job types three steps deep: 340 pages
    each. After every step the row is on the CARRIER with what they left (typed 3 x 5; the empty Hours or Guys box; switched off; the rate typed as $40 with the guys and
    hours left on the distance, which the 2026-10-20 fourth audit found staying behind on the old carrier at $33), no other section holds anything of theirs or prices
    anything, and the drive is priced at most once."""
    require_node()
    got = run(variant, 3)
    assert got["runs"] >= 340 and got["plain"] >= 84 and got["reopens"] >= 190, "the walk was cut short: %r" % ({k: got[k] for k in ("runs", "plain", "reopens")},)
    assert got.get("skipped", 0) == 0, "a start had no Travel Labor row to say it on"
    assert got["violations"] == {} and got["crashes"] == [], explain(got)


def test_the_estimators_say_applied_anywhere_in_a_sequence_follows_the_carrier_on():
    """The same four, applied once at ANY step of a sequence (before it, between two switches, at the end), through every sequence of the four job types: 1,252 pages."""
    require_node()
    got = run("mixed", 3)
    assert got["runs"] >= 1250 and got["plain"] >= 220 and got["reopens"] >= 830, "the walk was cut short: %r" % ({k: got[k] for k in ("runs", "plain", "reopens")},)
    assert got["violations"] == {} and got["crashes"] == [], explain(got)


def test_job_switches_copies_and_every_base_change_the_sheets_panel_offers_price_the_base_once():
    """The four job types, a copy of the carrier, and every base change the Sheets panel offers at the state it is in (making Epoxy or Polish the base, the combined
    pair), three steps deep: 939 pages. A base change settles the job's drive exactly as a job switch does: a Combo made Epoxy the base, then Polish, then the pair again
    through the panel alone priced the drive twice ($858 + $858) at 7d32336, and so did a copy of the Polish sheet made the other half of the pair beside Epoxy."""
    require_node()
    got = run("sheets", 3)
    assert got["runs"] >= 900 and got["plain"] >= 150 and got["reopens"] >= 650, "the walk was cut short: %r" % ({k: got[k] for k in ("runs", "plain", "reopens")},)
    assert got["violations"] == {} and got["crashes"] == [], explain(got)


@pytest.mark.parametrize("variant", ["Typed", "ClearHours", "ClearGuys", "Off", "Rate"])
def test_what_the_estimator_said_survives_every_job_switch_copy_and_base_change_together(variant):
    """The estimator's say on the carrier's row (typed, a cleared box, switched off), then every sequence of job switches, copies of the carrier and Sheets base changes
    three steps deep: 939 pages each. The estimator's row is the carrier's after every step, and each base crew's drive is priced once. A COPY of the carrier's sheet carries
    the row the carrier had, so it carries the estimator's typed 3 x 5 too, as the tool's copy (`tool_copy`); made a base beside the base that holds the estimator's own row
    (Polish copied, the job made Epoxy so the typed drive went to Epoxy, then the copy and Epoxy made the pair) it priced the one figure on two crews ($495 + $495) until round 7,
    part 3 (SAID_TWICE: the round-7 audit's F1), and now the copy is given back and filled on its own crew (Hanz's D1 of 2026-10-21: a base nobody typed on drives its own crew).

    Mutation: never give a copy back, or never mark a sheet's copy as the tool's (test_polish_travel_sequences_mutations.py)."""
    require_node()
    got = run("sheets" + variant, 3)
    assert got["runs"] >= 900 and got["plain"] >= 150 and got["reopens"] >= 650, "the walk was cut short: %r" % ({k: got[k] for k in ("runs", "plain", "reopens")},)
    assert got.get("skipped", 0) == 0 and got["violations"] == {} and got["crashes"] == [], explain(got)


@pytest.mark.parametrize("where", ["", "@local", "@unknown"])
def test_what_the_estimator_said_once_is_on_one_base_through_every_sequence_that_copies_it_to_a_second(where):
    """ROUND 7, PART 3 (the round-7 audit's F1). The estimator says it once on the carrier's row (3 x 5 typed, the Hours or the Guys box cleared, the row switched off, $40 typed over the
    rate), and then the four sequences that copy it onto a second base: far Polish, an Epoxy sheet added and made the base (the job's one drive follows it, as the tool's COPY, and the demoted
    Polish option keeps its own), then Combo by the intake's job type or by "Make Epoxy + Polish the base"; far Epoxy and a Polish sheet the same way; and a copy of the Polish sheet made the
    pair with Epoxy after the job's typed drive went to Epoxy. 20 sequences, 80 pages, every rule judged after every step and every Sheets action against a jsonb reload at four distance
    answers. Until this round each ended with the say on BOTH bases (SAID_TWICE in all 20: the Polish crew's typed 7 x 3.25 priced on the Epoxy crew too, +$1,505 in the audit's own bid); now
    the tool's copy is given back and the base drives its own crew (Hanz's D1 of 2026-10-21), and the estimator's own row stays where the job's drive took it. SINCE PART 4 (P1) the copy given
    back keeps the TRIP it held, the hours the estimator typed (the typed variant's 5) and the rate ($40), on its own crew's guys (COPY_TRIP), as Kyle's sheets carry the same trip on both crews;
    SAID_TWICE judges what was said of one crew (the typed guys, a cleared box, the switch). A copy with no figure in its Hours box (a cleared box, or on a 40 mile job and one with no distance
    a copy of a drive whose hours nobody typed) is given back empty, as a base's drive nobody typed is there."""
    require_node()
    got = run("said" + where, 0)
    assert got["sequences"] == 20 and got["runs"] >= 80 and got.get("reloadJudged", 0) >= 50, "the walk was cut short: %r" % ({k: got.get(k) for k in ("sequences", "runs", "reloadJudged")},)
    assert got.get("skipped", 0) == 0 and got["violations"] == {} and got["crashes"] == [], explain(got)


@pytest.mark.parametrize("where,depth,floor", [("far", 3, (2300, 290, 1700)), ("local", 2, (290, 36, 220)), ("unknown", 2, (290, 36, 220))])
def test_nights_the_estimator_typed_stay_theirs_through_every_sequence_of_job_types_and_crews(where, depth, floor):
    """Round 6, N4: "typed lines are the estimator's". The estimator types 10 in Lodging and types over and clears Per Diem (an emptied box is an answer too: 2026-10-12), then every
    sequence of the four job types, each plain or with the crew typed on the new carrier, runs after it: three steps deep on a far job (2,340 pages, 1,792 reopened plain), two on a
    40 mile one and on one with no distance (292 each). After every step Lodging holds 10 and Per Diem holds nothing, both typed, off auto and with no marker that they follow the labor:
    a carrier that moved under a far distance fills only what nobody typed (a cleared box is typed), a crew that grew is not followed, and going local takes back only the figure the
    labor had filled.

    Mutation (test_polish_travel_sequences_reload.py): a far answer fills a box that was typed and left empty; typing in the box marks nothing; going local empties a typed figure."""
    require_node()
    got = run("nightsTyped" + ("" if where == "far" else "@" + where), depth)
    runs, plain, reopens = floor
    assert got["runs"] >= runs and got["plain"] >= plain and got["reopens"] >= reopens, "the walk was cut short: %r" % ({k: got[k] for k in ("runs", "plain", "reopens")},)
    assert got.get("skipped", 0) == 0, "a start had no Lodging and Per Diem boxes to type in"
    assert got["violations"] == {} and got["crashes"] == [], explain(got)


@pytest.mark.parametrize("distance", ["local", "unknown"])
@pytest.mark.parametrize("variant", ["typed", "clearHours", "clearGuys", "off", "rate"])
def test_what_the_estimator_said_follows_the_carrier_on_a_short_job_or_one_with_no_distance_too(variant, distance):
    """The estimator's say is theirs wherever the job is: typed Travel Labor on a 40 mile job (it is priced: typing lifts the grey) or on a job whose distance the
    lookup could not find still goes with the job's drive to every carrier, and nothing is filled beside it. Every sequence of the four job types two steps deep."""
    require_node()
    got = run(variant + "@" + distance, 2)
    assert got["runs"] >= 80 and got["plain"] >= 20 and got["reopens"] >= 40, "the walk was cut short: %r" % ({k: got[k] for k in ("runs", "plain", "reopens")},)
    assert got.get("skipped", 0) == 0 and got["violations"] == {} and got["crashes"] == [], explain(got)
