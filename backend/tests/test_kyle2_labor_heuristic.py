"""A struct-op on Epoxy must not corrupt the labor heuristic on a revisit.

Kyle, on WhatsApp: "There's some sort of bug because when I went back to the estimate sheet it
changed all of my numbers and I can't get it to reset." / "Changed the labor somehow."

WHAT WAS BROKEN. applyHeuristics() in frontend/js/estimate-review.js writes the SF-derived
crew/days/hourly-rate heuristic to Epoxy!A47/B47/C47, and reads the Prevailing Wage flag from
Epoxy!D5 -- as raw literal template addresses, the one coordinate-dependent read/write in that
file that skipped txAddr, which every sibling function (totalCellsFor, sfFieldsFor, the struct-op
rekeying itself) already goes through. Its blank-check runs inside autofillFromIntake's IIFE,
which fires on EVERY load of Estimate Review, not just the first. So once a row/column insert or
delete on Epoxy moved the real labor cells somewhere else, the OLD address kept reading as
"blank" forever, and the heuristic silently reseeded a fresh SF-derived value into whatever
unrelated cell now occupied that vacated address -- on every single revisit ("can't get it to
reset"), with the wrong value cascading through the sheet's totals ("changed all of my numbers").

TWO BUGS, NOT ONE. The first fix pass added txAddr("Epoxy", "A47") etc., but txAddr() returns a
BARE address ("A49"), while putIfBlank() and intake.cell_values are keyed on the combined
"Sheet!Addr" string every other caller in this file uses. Passing the bare address straight to
putIfBlank would have written to a cellValues key nothing downstream ever reads -- the fix would
still silently fail to land the labor cells after a struct-op, just via a different failure mode.
This was caught by the harness below actually executing the real code and checking real output
values, not by re-reading the diff: every translated address here (a47, b47, c47, d5) has to be
re-prefixed with "Epoxy!" before it reaches putIfBlank or indexes cell_values.

WHY EXECUTED, NOT RESTATED. txAddr's index math (_shiftIdx, insert vs delete, returning null for
a deleted coordinate) is exactly the kind of off-by-one a source read glosses over, and the fix's
correctness hinges on it doing the right thing -- not merely on "some txAddr call was added".
kyle2-labor-heuristic-harness.js lifts _shiftIdx, structOpsFor, txAddr and applyHeuristics
verbatim out of the shipped file and runs them for real, the same way markup-rate-harness.js and
taxable-flag-harness.js run their own coordinate-dependent writers instead of trusting a
re-implementation of the shift math.

THE FIVE SCENARIOS.
  * No struct ops -- the plain-template case must still work exactly as before.
  * Two rows inserted above the labor block (the actual incident) -- A47/B47/C47 move to
    A49/B49/C49, AND a real value an estimator has since typed at the vacated Epoxy!A47 must
    survive untouched. Clobbering that cell is the pre-fix bug, reproduced.
  * A column inserted at column 1 -- shifts A47/B47/C47 AND the D5 prevailing-wage flag read.
    Getting D5's shift wrong would silently default a prevailing-wage job to the standard rate.
  * The labor row deleted outright -- txAddr returns null and the write must be skipped, not
    land at a stale address nobody will ever look at again.
  * A gyp job -- the heuristic is epoxy-only and must keep being skipped regardless of struct ops.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = REPO / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "kyle2-labor-heuristic-harness.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def result():
    proc = subprocess.run(
        ["node", str(HARNESS), str(FRONTEND)],
        capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, (
        "the harness itself failed -- read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_no_struct_ops_the_plain_template_case_is_unchanged(result):
    """Before any row/column insert or delete has ever happened on Epoxy, the heuristic must
    still write the same crew/days/rate it always has -- this fix must not touch the common
    case, only the one that used to corrupt itself on a revisit."""
    assert result["noStructOps"] == {"a47": 3, "b47": 5, "c47": 33}


def test_two_rows_inserted_above_the_labor_block_is_the_actual_incident(result):
    """THE reported bug, reproduced exactly: two rows inserted above row 47 move the labor block
    to row 49. A47/B47/C47 must be left alone (an estimator's own value at that now-vacated
    address must survive -- clobbering it was the pre-fix behaviour), and the heuristic must
    write to the NEW address, A49/B49/C49, not silently do nothing and not reseed the old one."""
    r = result["rowsInserted"]
    assert r["oldA47Untouched"] == "DO NOT TOUCH -- real data now at this address", (
        "a struct-op must not let the heuristic clobber a cell that now legitimately holds "
        "something else -- this is Kyle's \"changed all of my numbers\" bug, reproduced")
    assert "oldB47StillBlank" not in r and "oldC47StillBlank" not in r, (
        "the old B47/C47 addresses must stay untouched too -- nothing should ever be written "
        "to a vacated template coordinate")
    assert r["newA49"] == 3
    assert r["newB49"] == 5
    assert r["newC49"] == 33


def test_column_inserted_shifts_the_labor_cells_and_the_prevailing_wage_flag(result):
    """A column inserted at column 1 shifts every labor address by one column (A47->B47,
    C47->D47) AND the D5 prevailing-wage read has to follow the same shift, to D5->E5. Getting
    the flag's translation wrong would silently default a prevailing-wage job to the standard
    $33 rate instead of the $48 PW rate -- a pricing error a struct-op would introduce with no
    visible cause."""
    r = result["colInserted"]
    assert r["b47"] == 3, "crew heuristic must land at its shifted address (old A47 -> B47)"
    assert r["c47"] == 5, "days heuristic must land at its shifted address (old B47 -> C47)"
    assert r["laborRate"] == 48, (
        "the Prevailing Wage flag (shifted D5 -> E5) must still be read correctly, and the rate "
        "heuristic (shifted C47 -> D47) must pick the $48 PW rate, not silently fall back to $33")


def test_labor_row_deleted_outright_skips_the_write_instead_of_going_stale(result):
    """txAddr returns null for a coordinate that has been deleted outright. The heuristic must
    skip the write entirely in that case -- writing to a stale address nobody will ever look at
    again is exactly the failure mode this whole fix exists to close off."""
    assert result["rowDeleted"]["writtenAnywhere"] == []


def test_gyp_jobs_still_skip_the_heuristic_regardless_of_struct_ops(result):
    """The crew/days/rate heuristic is epoxy-only. A struct-op on Epoxy must not make a gyp job
    start picking up epoxy labor values -- the work-type guard has to keep working exactly as it
    did before txAddr was added to this function."""
    assert result["gypSkipped"]["writtenAnywhere"] == []
