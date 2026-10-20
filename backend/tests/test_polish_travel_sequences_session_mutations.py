"""THE JOB'S ONE DRIVE, OVER EVERY SEQUENCE OF SWITCHES, part 6 (continued): the session walk must SEE the old order (round 6, item C2).

test_polish_travel_sequences_session.py walks a session that never reloads against a reload of what it saved. Here the old order is put back in a COPY of js/bid-model.js, one line at a
time, and the same walk (a far job, two steps deep) is required to report the difference as SESSION_AGREES, and as a divergence in PRICES too: a walk that stopped seeing it would pass
for the wrong reason, which is what the clean runs in that file cannot tell you.

A file of its own (round 6, item O4) so that `--dist loadfile` runs the two walks on another worker than the agreement walks.
"""
import pytest

from _golden_support import break_source, copy_unmodified
from _node import require_node
from _travel_sequences import PAGE_FILES, explain, run


# ── red without the code: put the old order back in a COPY of the model ──────────────────────────
SECTIONS_OF = "    tabIdsInOrder(tabs).forEach(function (id) {"
BY_SEQ = "      if (a.seq !== b.seq) return a.seq - b.seq;"

# name -> (old, new)
BREAKS = {
    "the sheets are listed in the order their keys come back in (before the order was kept)": (
        SECTIONS_OF, "    Object.keys(tabs).forEach(function (id) {"),
    "the places are ignored and the keys decide (what a tie did before the id settled it)": (
        BY_SEQ, "      if (a.seq !== b.seq) return 0;"),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_walk_reports_the_difference_when_the_old_order_is_put_back(tmp_path, name):
    """The break must be SEEN as SESSION_AGREES, and as a divergence in PRICES too (a crash of the page is not seeing it: a break that stopped the page has nothing to compare)."""
    require_node()
    old, new = BREAKS[name]
    frontend = break_source(tmp_path, "js/bid-model.js", old, new)
    copy_unmodified(frontend, PAGE_FILES)
    got = run("session", 2, frontend)
    assert not got["crashes"], "the break crashed the page instead of breaking a rule: %s\n%s" % (name, explain(got))
    assert got["violations"].get("SESSION_AGREES") and got["priced"].get("SESSION_AGREES"), "the walk did not see the prices move: %s\n%s" % (name, explain(got))
