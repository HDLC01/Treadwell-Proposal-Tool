"""THE JOB'S ONE DRIVE, OVER EVERY SEQUENCE OF SWITCHES, part 6: a session that never reloads, against a reload (round 6, item C2, 2026-10-20).

Every walk before this one starts each step from the draft the step before SAVED, reopened. So a Sheets action (a copy, a fresh sheet) always acted on sheets the server had already
put in its own order, and none could see what depends on how the sheets are ordered in a SESSION. The draft is a jsonb column and jsonb keeps no key order: a reopened blob has every
object's keys sorted by length and then by bytes (tests/js/_jsonb.js, held to PostgreSQL's order by test_jsonb_key_order.py), so "Copy1" came before "Epoxy" after a reload, and the
section that carries the job's travel (the first base) with it.

tests/js/travel-sequence-harness.js now has a `session` mode (and every reopen in every walk goes through the server's order). ONE page carries a whole path of the four job types, the
Sheets panel's base changes, a copy of the carrier and a fresh Epoxy or Polish sheet, and after EVERY prefix of every path it is judged against a reload:

    SESSION_AGREES   the bid the session made and a page opened on the blob it saved, with every key in jsonb's order, hold the same prices, the same sheets in the same order with the
                     same kinds, the same carrier, the same priced_tabs and the same Travel Labor rows, and each of the four distance answers (50, 300, 190, cleared) leaves the same ones

At 619f092 (the code before this round) the depth-2 walk reports it in 800 of its 1,380 checks (276 pages, each as it stands and after four answers), 5 of them in PRICES: an Epoxy job,
a Polish sheet added beside it, the pair made the base (the Polish sheet is a Copy1 under `tabs`, so both bases are):

    session  lump $48,739  (Epoxy $40,431 + Copy1 $8,308)    after a reload  lump $40,720  (Epoxy $32,412 + Copy1 $8,308)

Epoxy carried the drive and the nights in the session, and Copy1 (which has no crew) carried them after the reload: $8,019 less on a bid with nothing edited. It is clean now.

THE THREE FILES (round 6, item O4). The walk is long: each full run of it takes 30 to 50 seconds, and five of them in one file made a four minute file that `--dist loadfile`
(which keeps a file on one worker) could not spread. So the same tests are in three files that run on three workers, and the suite's wall time does not grow by them: this one (a
far job, the 190 mile Wichita bid), test_polish_travel_sequences_session_local.py (a 40 mile job, and one whose distance could not be found) and
test_polish_travel_sequences_session_mutations.py (the old order put back in a COPY of the model, which the walk is required to see).
"""
import pytest

from _node import require_node
from _travel_sequences import explain, run, session_walked


@pytest.mark.parametrize("distance", [""])
def test_a_session_that_never_reloaded_and_a_reload_of_what_it_saved_agree_after_every_prefix(distance):
    """The four job types, a copy of the carrier, a fresh Epoxy or Polish sheet and every base change the panel offers, two steps deep from each of the four starts: 276 pages, each
    judged as it stands and after the miles typed as 50, 300, 190 and cleared, on the draft as the session saved it and on the draft as the server returns it. A far job (190 miles);
    the 40 mile job and the one whose distance could not be found are in test_polish_travel_sequences_session_local.py."""
    require_node()
    got = run("session" + distance, 2)
    session_walked(got)
    assert got["violations"] == {} and got["crashes"] == [] and got["priced"] == {}, explain(got)
