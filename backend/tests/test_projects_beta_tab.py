"""A Beta Polish tab on the Projects page — and why its absence read as data loss.

Hanz, 2026-09-02: *"Since it's in beta can we have a project list for the Beta Polish tool?"*

**IT IS ALSO HALF OF WILL'S REPORT.** He said beta work "doesn't save". One half of that was real
and is fixed in `frontend/js/polish-intake.js` (nothing on the page listened for typing). The other
half is this: a beta project was *invisible everywhere anyone would look for it*. The sandbox files
every beta copy with `is_test: true` and renames it `"<name> (beta test)"`; `realOnly()` then
excludes test rows from Active, Inactive **and** All; and the default tab is Active. So beta work
could only be found by clicking **Test**, under a renamed title, mixed in with every demo, QA and
"delete me" row in the database. An estimator who saved beta work and then looked where they always
look saw nothing — which reads as "it didn't save" even when it did.

**RUN, NOT READ.** Every claim worth making here is about ORDER, which no source assertion can see:

* Because beta rows *are* test rows, the beta branch has to sit **above** the `realOnly()` call.
  Put it below and the tab renders empty with every string still in the file and every grep green.
* The chip count and the grid are separate expressions over different lists. Counting off the
  real-bids list instead of `ALL_PROJECTS` shows "Beta Polish 0" above a tab full of rows — the
  exact disagreement `realOnly()` was introduced to end.
* A chip can render and bind nothing.

See [backend/tests/js/projects-beta-tab-harness.js](js/projects-beta-tab-harness.js), which lifts
the page's real `applyFilter` and `renderChips`.

No backend change: `/api/drafts` has always projected `polish_beta` on every row
(`drafts.py:620`, `:684`). The frontend read it in exactly one place — the resume router — and
nowhere else.
"""

import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "projects-beta-tab-harness.js"


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_beta_tab_shows_beta_projects(ran):
    """The ask, and the assertion that fails if the branch is placed below realOnly().

    Rows c and d are the beta ones. Both carry `is_test: true`, because that is what the sandbox
    files them as — so a beta branch reading the already-filtered list returns an empty tab.
    """
    assert ran["shown"]["beta"] == ["c", "d"], (
        "the Beta Polish tab is not showing beta projects. If it is empty, the branch has been "
        "moved below `const real = realOnly(list)` — beta rows are test rows, so it must read the "
        "unfiltered list.")


def test_an_archived_beta_project_still_appears_under_beta(ran):
    """Row d is archived and still shows, on purpose.

    The tab answers "where is my beta work", not "what is live". Splitting beta into active and
    archived would rebuild the same hiding problem one level down — and there is no Beta/Inactive
    tab for the archived ones to go to.
    """
    assert "d" in ran["shown"]["beta"]


def test_a_test_project_that_is_not_beta_stays_out_of_the_beta_tab(ran):
    """The counterexample. Without it, `return list.filter(isTest)` passes the test above.

    Row e ("delete me") and row f ("QA sample", a legacy row with no `is_test` at all) are both test
    projects and neither is beta. If they appear here, the tab is just a second Test tab and the
    estimator is back to hunting through demo rows — which is the problem this tab exists to solve.
    """
    assert "e" not in ran["shown"]["beta"]
    assert "f" not in ran["shown"]["beta"]
    assert ran["shown"]["test"] == ["c", "d", "e", "f"], "the Test tab must keep showing everything"


def test_beta_projects_are_still_hidden_from_active_inactive_and_all(ran):
    """Nothing about the new tab may leak beta rows onto the tabs the sales meeting is run from.

    This is the constraint that forces the branch to be a `return` rather than an extra predicate
    layered onto the real-bids list.
    """
    assert ran["shown"]["active"] == ["a"]
    assert ran["shown"]["inactive"] == ["b"]
    assert ran["shown"]["all"] == ["a", "b"]


def test_the_chip_count_agrees_with_the_rows_the_tab_shows(ran):
    """The number on the tab and the length of the tab, compared — not each asserted separately.

    `realOnly()` exists because those two were once filtered independently and could disagree. A
    count taken off the real-bids list would read 0 here while the grid showed two rows.
    """
    beta = [c for c in ran["chips"] if c["key"] == "beta"]
    assert len(beta) == 1, "there is no Beta Polish chip in the rendered chip row"
    assert beta[0]["label"] == "Beta Polish"
    assert beta[0]["n"] == len(ran["shown"]["beta"]), (
        "the chip count disagrees with what the tab shows — count off ALL_PROJECTS, not realOnly()")


def test_every_chip_is_bound_to_a_click(ran):
    """Derived from what rendered, never a hard-coded list of tabs.

    `test_active_projects_board.py:325` records that a hard-coded tab pin was replaced with a
    derived check precisely because it broke every time a tab was added. This follows that lesson:
    it asserts each chip the page emitted is clickable, whatever the set turns out to be.
    """
    keys = [c["key"] for c in ran["chips"]]
    assert ran["bound"] == [k + ":click" for k in keys], (
        "a chip rendered without a click listener — it would sit there doing nothing forever")
    assert "beta" in keys


def test_the_selected_chip_is_the_one_we_are_standing_in(ran):
    """The harness ran with CURRENT_FILTER = "beta", so exactly that chip carries `sel`.

    Without this, a chip could render, count and bind correctly and never look selected — the tab
    would work while appearing not to have been clicked.
    """
    sel = [c["key"] for c in ran["chips"] if c["selected"]]
    assert sel == ["beta"], sel


def test_no_projects_at_all_hides_the_chip_row_and_does_not_throw(ran):
    """An empty database is a real state — a brand-new environment, or every project deleted.

    `p.polish_beta` on an empty list is never evaluated, but `renderChips` still runs, and a
    count expression that assumed a non-empty list would throw here and take the whole page down.
    """
    assert ran["chipsEmpty"]["hidden"] is True
    assert ran["shownEmpty"] == []


def test_new_project_from_the_beta_tab_states_no_test_intent():
    """A deliberate fall-through, recorded so nobody has to guess whether it was one.

    `+ New project` sets an explicit intent from the Test tab (`true`) and the Active tab (`false`),
    and `null` everywhere else. Beta joins the `null` group **on purpose**: a new project always
    starts on the live intake as an ordinary bid, and only becomes a beta project when the estimator
    presses the beta button — at which point `polish-sandbox.js` files the copy as a test itself. So
    pre-declaring test intent here would mark a bid that may never enter the beta at all.
    """
    src = (FRONTEND / "js" / "projects.js").read_text(encoding="utf-8")
    i = src.index("setNewProjectTestIntent")
    block = src[max(0, i - 1200):i + 400]
    assert 'CURRENT_FILTER === "beta"' not in block, (
        "the beta tab has been given its own test intent. If that is deliberate, say why here — "
        "the reasoning above is that a new project is not a beta project until the beta button is "
        "pressed, and the sandbox files it as a test at that point.")
    assert "setNewProjectTestIntent(null)" in block
