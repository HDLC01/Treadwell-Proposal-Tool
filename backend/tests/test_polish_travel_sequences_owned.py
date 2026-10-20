"""THE JOB'S ONE DRIVE, OVER EVERY SEQUENCE OF SWITCHES, part 2 of 3: what the estimator said, and the Sheets panel.

Part 1 (test_polish_travel_sequences.py) walks a new far bid whose Travel Labor nobody touched. This walks the cases the third audit (2026-10-20, of 7d32336) found
the settling did not hold:

  typed, clearHours, clearGuys, off   the estimator's own say on the carrier's Travel Labor row (3 guys x 5 hours typed; the Hours box cleared; the Guys box cleared; the
                      row switched off) before any switch: through EVERY sequence of job types after it, the row is the carrier's, as they left it, and on no other section.
                      "Typed, cleared and switched-off are the estimator's, are never refilled, and follow the job's drive when the carrier changes." At 7d32336 the typed 3 x 5
                      stayed behind on the old carrier while the new one was filled beside it ($858 + $495), and a cleared or switched-off row read $858 on the new carrier.
  mixed               the same four say-sos, applied ONCE anywhere along the sequence instead of at the start.
  sheets              the four job types AND the Sheets panel: every base change it offers (a sheet, or the Epoxy + Polish pair) and a copy of the carrier (an option, which
                      is priced apart and carries its own row). The base's Travel Labor is judged by the same rules; an option's is its own.
  sheetsTyped, ...    the Sheets walk with the estimator's say on the carrier's row first: a copy carries that row too, and made a base it must not price the drive twice.
  typed@local, ...    the estimator's say on a 40 mile job, and on one whose distance could not be found (typed hours are priced there: typing lifts the grey).

Every step is judged by travel-sequence-harness.js's rules (see _travel_sequences.RULES): one priced drive, no man-days row, a far carrier always has its row, nothing
filled on a Gyp carrier, no filled row left on a section that is not the carrier, the estimator's row on the carrier, and a plain reopen that changes and saves nothing and
shows the price the draft saved.
"""
import pytest

from _node import require_node
from _travel_sequences import explain, run


@pytest.mark.parametrize("variant", ["typed", "clearHours", "clearGuys", "off"])
def test_what_the_estimator_said_on_travel_labor_follows_the_carrier_through_every_sequence_of_job_types(variant):
    """Four starts (Polish, Epoxy, Combo, Gyp), the estimator's say applied to the carrier's row, then every sequence of the four job types three steps deep: 340 pages
    each. After every step the row is on the CARRIER with what they left (typed 3 x 5; the empty Hours or Guys box; switched off), no other section holds anything of
    theirs or prices anything, and the drive is priced at most once."""
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


@pytest.mark.parametrize("variant", ["Typed", "ClearHours", "ClearGuys", "Off"])
def test_what_the_estimator_said_survives_every_job_switch_copy_and_base_change_together(variant):
    """The estimator's say on the carrier's row (typed, a cleared box, switched off), then every sequence of job switches, copies of the carrier and Sheets base changes
    three steps deep: 939 pages each. The estimator's row is the carrier's after every step, and the drive is priced at most once. A COPY of the carrier's sheet carries the
    row the carrier had, so it carries the estimator's typed 3 x 5 too; made a base beside the carrier (the combined pair) it would price the drive a second time ($495 +
    $495), so a row that repeats the carrier's exactly is given back when its section is a base that does not carry the travel.

    Mutation: leave the copy's repeat of the row on its section (test_polish_travel_hours.py runs it on the model)."""
    require_node()
    got = run("sheets" + variant, 3)
    assert got["runs"] >= 900 and got["plain"] >= 150 and got["reopens"] >= 650, "the walk was cut short: %r" % ({k: got[k] for k in ("runs", "plain", "reopens")},)
    assert got.get("skipped", 0) == 0 and got["violations"] == {} and got["crashes"] == [], explain(got)


@pytest.mark.parametrize("distance", ["local", "unknown"])
@pytest.mark.parametrize("variant", ["typed", "clearHours", "clearGuys", "off"])
def test_what_the_estimator_said_follows_the_carrier_on_a_short_job_or_one_with_no_distance_too(variant, distance):
    """The estimator's say is theirs wherever the job is: typed Travel Labor on a 40 mile job (it is priced: typing lifts the grey) or on a job whose distance the
    lookup could not find still goes with the job's drive to every carrier, and nothing is filled beside it. Every sequence of the four job types two steps deep."""
    require_node()
    got = run(variant + "@" + distance, 2)
    assert got["runs"] >= 80 and got["plain"] >= 20 and got["reopens"] >= 40, "the walk was cut short: %r" % ({k: got[k] for k in ("runs", "plain", "reopens")},)
    assert got.get("skipped", 0) == 0 and got["violations"] == {} and got["crashes"] == [], explain(got)
