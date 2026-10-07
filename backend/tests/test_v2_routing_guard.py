"""A v2 draft opens on the v2 pages, and a v2 test copy carries no spreadsheet price.

Phase 2 of the Estimating Tool v2 program (docs/v2-architecture.md section 8). Two defects, one cause:
Estimating Tool v2 prices itself and the spreadsheet does not know about it.

  1. A v2 draft could be opened in the spreadsheet. estimate-review.js snapshots the sheet's totals into
     the draft and then writes `computed_bid` = null, so the estimator lost v2's price and the proposal
     printed the spreadsheet's instead. Every step pill, Back button, bell link and board link can reach
     the spreadsheet with a v2 draft, so the guard stands at the two DESTINATIONS (the spreadsheet step
     and the live intake) and not at each door.
  2. The v2 test copy of a spreadsheet bid (polish-sandbox.js buildCopy) was the source minus four keys,
     so it arrived holding the source's `priced_tabs` and `proposal_lump_sum`. The Proposal step reads the
     sheet's total first and the engine's second, so the copy printed the SOURCE's price. The copy is now an
     allowlist, and a stale copy that already exists is read without the spreadsheet's numbers.

EXECUTED, NOT READ. tests/js/v2-routing-harness.js lifts the real functions out of the page files and runs
them, tests/js/beta-routing-harness.js runs the real index.js, and tests/js/files-door-harness.js (see
test_files_door.py) runs the real Proposal step. What is read as text here is only what cannot be run: the
list of doors, and the list of keys the spreadsheet writes.

Each test names the mutation it exists to kill, and the ones marked MUTATION BREAK a scratch copy of the
shipped file and require the harness to notice: a test that cannot go red proves nothing.
"""
import json
import pathlib

import pytest

import drafts
from _golden_support import break_source
from _node import last_json_line, run_node
from _v2_cases import MIRRORED_CASES, NUMBER_CASES, VERSION_CASES

TESTS = pathlib.Path(__file__).resolve().parent
FRONTEND = TESTS.parents[1] / "frontend"
HARNESS = TESTS / "js" / "v2-routing-harness.js"
BETA_HARNESS = TESTS / "js" / "beta-routing-harness.js"
# What beta-routing-harness.js reads (it does not fall back to the real frontend for a missing file).
BETA_FILES = ["js/index.js", "index.html", "shared.js", "js/projects.js", "js/county-picker.js",
              "js/address-lookup.js", "js/work-types.js"]


# ── the harness runs ─────────────────────────────────────────────────────────────────────────────
def _blob_for(case):
    """The draft a parity case stands for, as the SERVER sees it."""
    kind = case["kind"]
    if kind == "no_estimate":
        return {}
    if kind == "absent":
        return {"polish_estimate": {}}
    if kind == "number":
        return {"polish_estimate": {"version": {"nan": float("nan"), "inf": float("inf"),
                                                "-inf": float("-inf")}[case["value"]]}}
    return {"polish_estimate": {"version": case["value"]}}


def _table():
    """Every case, as (what the harness is told, what the table says the answer is)."""
    rows = [({"kind": "value", "value": raw}, expect) for raw, expect in VERSION_CASES + MIRRORED_CASES]
    rows += [({"kind": "number", "value": tag}, expect) for tag, _val, expect in NUMBER_CASES]
    rows += [({"kind": "absent"}, False), ({"kind": "no_estimate"}, False)]
    return rows


def _server_says(case):
    """backend/drafts.py's answer for the draft, through the same shaper the Projects page uses."""
    return drafts._summary({"id": "x", "data": _blob_for(case)})["polish_beta"]


def _run(frontend, cases_path):
    proc = run_node(HARNESS, frontend, cases_path)
    assert proc.returncode == 0, (
        "the harness itself failed. Read this before assuming a product bug:\n" + proc.stderr)
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def cases_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("v2cases") / "cases.json"
    path.write_text(json.dumps([case for case, _expect in _table()]), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def ran(cases_file):
    return _run(FRONTEND, cases_file)


@pytest.fixture(scope="module")
def beta():
    proc = run_node(BETA_HARNESS, FRONTEND)
    assert proc.returncode == 0, (
        "the harness itself failed. Read this before assuming a product bug:\n" + proc.stderr)
    return last_json_line(proc.stdout)["v2routing"]


# ══ 1. one answer to "is this a v2 draft" ════════════════════════════════════════════════════════
def test_the_table_says_what_the_server_says():
    """The table is only worth holding the JavaScript to if it is the SERVER's own answer. Every case,
    through drafts._summary (the shaper the Projects page's `polish_beta` comes from).

    Mutation: edit an expectation to make the JavaScript pass. This goes red first."""
    for case, expect in _table():
        assert _server_says(case) is expect, (case, expect)


def test_the_browsers_predicate_answers_like_the_servers_on_every_case(ran):
    """THE PARITY. shared.js isV2Draft against backend/drafts.py, on every spelling of a version the
    table holds: numbers, text (PostgREST hands the server the version as TEXT), padded text, signs,
    exponents, an underscore between digits, the JavaScript-only ways to write 2 (hex, binary, octal,
    Infinity), booleans, objects, nothing at all. Two answers to one question is a project that opens
    on the wrong screen but only sometimes.

    Mutation: let Number() decide on its own (see the MUTATION test below)."""
    table = _table()
    assert len(ran["parity"]) == len(table), "the harness answered a different number of cases"
    disagree = [(case, "server", _server_says(case), "browser", got)
                for (case, _expect), got in zip(table, ran["parity"]) if got is not _server_says(case)]
    assert not disagree, "the browser and the server disagree about: %r" % (disagree,)


def test_the_table_covers_the_cases_that_matter_in_both_directions():
    """A parity table that holds only 'no' answers (or only 'yes') would pass a predicate that ignores
    its input. Both outcomes, and the awkward spellings, are in it."""
    answers = [expect for _case, expect in _table()]
    assert answers.count(True) >= 20 and answers.count(False) >= 40
    values = [c.get("value") for c, _e in _table() if c["kind"] == "value"]
    for must in (2, "2", " 2 ", "2.0", "+2", "2e0", "0_2", "0x2", "0b10", "Infinity", True, None, [2]):
        assert must in values, must


def test_a_blob_that_is_not_a_draft_is_not_a_v2_draft(ran):
    """null, a string, a number, a list, an estimate that is not an object. The SERVER raises on a
    non-empty list or string for `polish_estimate` (it calls .get on it), so there is no parity to hold
    here; the browser's answer is simply no, and a page asking it must not throw."""
    assert ran["oddShapes"] == [False] * 10, ran["oddShapes"]


def test_a_spelling_only_javascript_reads_as_two_is_caught_by_the_parity_table(cases_file, tmp_path):
    """MUTATION. Let Number() decide on its own, which is what the first draft of isV2Draft did. It
    reads "0x2", "0b10" and "0o2" as 2, and Python's float() refuses all three, so a project the server
    files as a spreadsheet bid would be sent to the v2 pages by the browser. The parity table must see
    it. If this passes against the unbroken file, the parity test above can never fail."""
    anchor = "return /^[0-9eE+.-]+$/.test(s) && Number(s) === 2;"
    broken = break_source(tmp_path, "shared.js", anchor, "return Number(s) === 2;")
    got = _run(broken, cases_file)["parity"]
    wrong = [case["value"] for (case, _e), g in zip(_table(), got)
             if g is not _server_says(case) and case["kind"] == "value"]
    for spelling in ("0x2", "0b10", "0o2"):
        assert spelling in wrong, "the parity table did not notice %r" % spelling


def test_a_blob_is_this_pages_only_when_its_stamp_names_the_draft_the_page_is_on(ran):
    """The ownership check both guards ask (shared.js isThisDraft), on its own. The stamp is what
    shared.js writes into every blob it stores. A page with no draft id, a blob with no stamp or an
    empty one, another project's stamp, and a value that is not a blob at all are none of them
    provably this project's, so none of them is acted on."""
    o = ran["ownership"]
    assert o["match"] is True
    assert (o["other"], o["unstamped"], o["emptyStamp"], o["noDraftId"]) == (False, False, False, False)
    assert o["notBlobs"] == [False, False, False, False]


# ══ 2. the guard at the spreadsheet step (estimate-review.js) ════════════════════════════════════
V2_PAGE = ["/polish-estimate.html?d=d1"]


@pytest.mark.parametrize("which", ["v2", "v2Text"])
def test_a_v2_draft_opened_in_the_spreadsheet_is_sent_to_its_own_page_and_the_page_stops(ran, which):
    """The real head of estimate-review.js, run against a v2 draft that is this project's. It must
    `replace` (so Back does not return to a page that would only bounce), stop the script (the sentinel
    appended after the guard is never reached, so nothing below it ran), and write nothing: not through
    setState, not through setLocalState, not through flushState. The text version is what PostgREST
    would hand a page that read the version from the server.

    Mutation: delete the guard, or put it after persistTabState (the next test breaks the file)."""
    r = ran["estimate"][which]
    assert r["replaced"] == V2_PAGE, r
    assert r["assigned"] == []
    assert r["reached"] is False, "the script carried on past the guard, so the spreadsheet would load"
    assert r["error"].startswith("estimate-review: a v2 draft"), r["error"]
    assert r["writes"] == [], "a redirected visit wrote to the draft: %r" % r["writes"]


@pytest.mark.parametrize("which", ["anotherProjects", "unstamped", "spreadsheet", "oldPolishEstimate",
                                   "versionOne"])
def test_every_other_draft_still_opens_the_spreadsheet(ran, which):
    """The cases that must NOT redirect matter as much as the one that must.

      anotherProjects  storage holds a v2 project while a link opens a different one (the bell, an
                       email): shared.js is about to fetch the right draft and reload, and sending this
                       first run to v2 would take a spreadsheet bid there because yesterday's project
                       was a v2 one;
      unstamped        a blob that is not provably this project's is not acted on;
      spreadsheet / oldPolishEstimate / versionOne   the spreadsheet workflow, which has no version 2.

    Mutation: drop the ownership check (the MUTATION test below), or read the version loosely."""
    r = ran["estimate"][which]
    assert r["replaced"] == [] and r["assigned"] == []
    assert r["reached"] is True and r["error"] is None, r
    assert r["writes"] == []


def test_the_no_project_card_still_comes_first(ran):
    """A draft with no name has nothing to open anywhere. The existing stop is not replaced by a redirect
    and the guard never runs for it."""
    r = ran["estimate"]["noProject"]
    assert r["error"] == "estimate-review: no project in state"
    assert r["replaced"] == [] and "No project started" in r["main"]


def test_the_redirect_card_is_plain_words(ran):
    """What a person sees for the moment before the v2 page arrives, or for as long as it is slow."""
    card = ran["estimate"]["v2"]["main"]
    assert "Estimating Tool v2" in card and "no spreadsheet" in card
    assert "\u2014" not in card and "\u2013" not in card, "dashes in UI copy (house rule)"


def test_removing_the_spreadsheet_guard_lets_a_v2_draft_load_the_grid(cases_file, tmp_path):
    """MUTATION. With the condition turned off the harness must see the page carry on: no replace, the
    sentinel reached. If this passes against the unbroken file, the test above proves nothing."""
    anchor = "if (TW.isV2Draft(state) && TW.isThisDraft(state)) {"
    broken = break_source(tmp_path, "js/estimate-review.js", anchor, "if (false) {")
    r = _run(broken, cases_file)["estimate"]["v2"]
    assert r["replaced"] == [] and r["reached"] is True


def test_the_spreadsheet_guard_checks_whose_draft_it_is(cases_file, tmp_path):
    """MUTATION. Without the ownership check a v2 blob left in storage sends a spreadsheet bid to the
    v2 pages. The 'anotherProjects' case must turn red when it is dropped."""
    anchor = "if (TW.isV2Draft(state) && TW.isThisDraft(state)) {"
    broken = break_source(tmp_path, "js/estimate-review.js", anchor, "if (TW.isV2Draft(state)) {")
    r = _run(broken, cases_file)["estimate"]["anotherProjects"]
    assert r["replaced"] == ["/polish-estimate.html?d=d9"], (
        "the ownership scenario is vacuous: it does not notice a guard that ignores whose blob it is")


# ══ 3. the guard at the live intake (index.js) ═══════════════════════════════════════════════════
INTAKE_V2 = ["/polish-intake.html?d=d1e2f3a4"]


@pytest.mark.parametrize("which", ["namedAndEdit", "editOnly", "dOnly", "textVersion", "newProjectReloaded"])
def test_a_v2_draft_opened_on_the_live_intake_goes_to_the_v2_intake(beta, which):
    """The real index.js, top to bottom, with the real isV2Draft and isThisDraft. A load that names a
    project (?d= or ?edit=) on a v2 draft that is this project's replaces itself with the v2 intake,
    stops the script before the form is built, and saves nothing. `newProjectReloaded` is the reload of
    a new project's page ("?new=1&d=..."): shared.js puts the id in the address bar, so it names a
    project, and one that has become v2 since belongs on v2.

    Mutation: delete the guard (the MUTATION test below)."""
    r = beta[which]
    assert r["replaced"] == INTAKE_V2, r
    assert r["stopped"] and "polish-intake.html" in r["stopped"]
    assert r["assigned"] == [] and r["saves"] == 0
    assert r["formBuilt"] is False, "the form was built on a page that is already leaving"


@pytest.mark.parametrize("which", ["newProject", "noQuery", "anotherProjectsBlob", "unstamped",
                                   "spreadsheetBid", "noEstimateAtAll", "oldPolishEstimate", "versionOne"])
def test_everything_else_still_gets_the_live_intake_form(beta, which):
    """'?new=1' on its own is somebody starting a project on this form and gets it, whatever storage
    holds. A load that names no project (a bare /index.html) is not a redirect either. And a v2 blob that
    is another project's, an unstamped one, and every spreadsheet draft get the form.

    Mutation: act on a load that names no project, or drop the ownership check."""
    r = beta[which]
    assert r["replaced"] == [] and r["stopped"] is None, r
    assert r["formBuilt"] is True


def test_the_submit_handler_never_carries_a_v2_draft_to_the_spreadsheet(beta):
    """A draft that became v2 while this page sat open (another tab priced it in v2) was not v2 when the
    page loaded, so the load guard cannot see it. Pressing Continue must not walk it into the Excel grid,
    and must not save this older form over it: the stale form says epoxy, the draft says polish.

    Mutation: delete the check in the handler. Continue then saves and goes to /estimate-review.html."""
    r = beta["submitOnAV2Draft"]
    assert r["assigned"] == INTAKE_V2, r
    assert r["saves"] == 0, "the stale form was saved over a v2 draft"
    assert r["savedWorkType"] == "polish", "the v2 draft's work type was overwritten by the stale form"


@pytest.mark.parametrize("which", ["submitOnAnotherProjectsV2Blob", "submitOnASpreadsheetBid"])
def test_the_submit_handler_still_goes_to_the_spreadsheet_for_everything_else(beta, which):
    r = beta[which]
    assert r["assigned"] == ["/estimate-review.html?d=d1e2f3a4"], r
    assert r["saves"] == 1


def _beta_scratch(tmp_path, rel, old, new):
    """A frontend directory holding everything beta-routing-harness.js reads, with `rel` broken."""
    root = break_source(tmp_path, rel, old, new)
    for other in BETA_FILES:
        target = root / other
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((FRONTEND / other).read_bytes())
    return root


def _beta_run(frontend):
    proc = run_node(BETA_HARNESS, frontend)
    assert proc.returncode == 0, proc.stderr
    return last_json_line(proc.stdout)["v2routing"]


INTAKE_GUARD = 'if ((q.has("d") || q.has("edit")) && TW.isV2Draft(here) && TW.isThisDraft(here)) {'


def test_removing_the_intake_guard_lets_a_v2_draft_load_the_live_form(tmp_path):
    """MUTATION. Turn the load guard off and a v2 draft gets the live form. If this passes against the
    unbroken file, the intake tests above prove nothing."""
    r = _beta_run(_beta_scratch(tmp_path, "js/index.js", INTAKE_GUARD, "if (false) {"))["namedAndEdit"]
    assert r["replaced"] == [] and r["formBuilt"] is True


def test_the_intake_guard_checks_whose_draft_it_is(tmp_path):
    """MUTATION. The ownership scenario must go red when the check is dropped."""
    broken = _beta_scratch(tmp_path, "js/index.js", INTAKE_GUARD,
                           'if ((q.has("d") || q.has("edit")) && TW.isV2Draft(here)) {')
    r = _beta_run(broken)["anotherProjectsBlob"]
    assert r["replaced"] == INTAKE_V2, "the ownership scenario is vacuous"


def test_the_intake_guard_only_acts_on_a_load_that_names_a_project(tmp_path):
    """MUTATION. Drop the '?d= or ?edit=' condition and a bare load, and a new project's first load,
    are redirected over a v2 blob."""
    broken = _beta_scratch(tmp_path, "js/index.js", INTAKE_GUARD,
                           "if (TW.isV2Draft(here) && TW.isThisDraft(here)) {")
    r = _beta_run(broken)
    assert r["newProject"]["replaced"] == INTAKE_V2 and r["noQuery"]["replaced"] == INTAKE_V2, (
        "the 'names no project' scenarios are vacuous")


def test_removing_the_submit_check_sends_a_v2_draft_to_the_spreadsheet(tmp_path):
    """MUTATION. Delete the handler's check and Continue saves the stale form and goes to the grid."""
    anchor = "if (TW.isV2Draft(nowHere) && TW.isThisDraft(nowHere)) {"
    r = _beta_run(_beta_scratch(tmp_path, "js/index.js", anchor, "if (false) {"))["submitOnAV2Draft"]
    assert r["assigned"] == ["/estimate-review.html?d=d1e2f3a4"] and r["saves"] == 1


# ══ 4. every door is covered by one of the two guards ════════════════════════════════════════════
SHEET, INTAKE, NOT_A_DOOR = "estimate-review.js", "index.js", "not a door"

# (file under frontend/, text on the line, how many lines, which destination guard covers it, why)
DOORS = [
    ("done.html", 'href="/estimate-review.html"', 1, SHEET, "the 2 · Estimate step pill"),
    ("done.html", 'href="/?edit=1"', 1, INTAKE, "the 1 · Intake step pill"),
    ("estimate-review.html", 'href="/?edit=1"', 1, INTAKE, "the 1 · Intake step pill"),
    ("index.html", 'href="/estimate-review.html"', 1, SHEET, "the 2 · Estimate step pill"),
    ("proposal-review.html", 'href="/?edit=1"', 1, INTAKE, "the 1 · Intake step pill"),
    ("proposal-review.html", 'href="/estimate-review.html"', 1, SHEET, "the 2 · Estimate step pill"),
    ("js/estimate-review.js", 'href="/?edit=1"', 1, INTAKE, "Go to Intake on the no-project card"),
    ("js/estimate-review.js", 'TW.withDraft("/?edit=1")', 1, INTAKE, "Back to intake"),
    ("js/index.js", 'TW.withDraft("/estimate-review.html")', 1, SHEET,
     "Continue on the live intake (the handler also refuses a v2 draft itself)"),
    ("js/index.js", 'q.has("edit")', 1, NOT_A_DOOR, "the load guard reads the parameter, it opens nothing"),
    ("js/leads.js", "&edit=1", 2, INTAKE, "Leads: open the project a lead became"),
    ("js/portal.js", "&edit=1", 2, INTAKE, "the board's drawer: Open"),
    ("js/projects.js", "&edit=1", 1, INTAKE, "a Projects card (a v2 card goes to the v2 intake first)"),
    ("js/proposal-review.js", 'href="/?edit=1"', 1, INTAKE, "Go to Intake on the no-project card"),
    ("js/proposal-review.js", 'TW.withDraft("/estimate-review.html")', 1, SHEET,
     "Back from the proposal step"),
    ("shared.js", 'searchParams.has("edit")', 1, NOT_A_DOOR,
     "the step-link rewriter reads the parameter, it opens nothing"),
]


def _code_lines(text):
    """(number, line) for every line that is code, not comment. Tracked line by line, with no
    stripping: a /* */ block or an HTML comment that spans lines hides the lines inside it, and a line
    that starts with //, * or <!-- is a comment. A trailing comment after code leaves the line code."""
    out, in_block, in_html = [], False, False
    for n, line in enumerate(text.splitlines(), 1):
        bare = line.strip()
        was_comment = in_block or in_html or bare.startswith(("//", "/*", "*", "<!--"))
        if "/*" in line and "*/" not in line.split("/*", 1)[1]:
            in_block = True
        if in_block and "*/" in line:
            in_block = False
        if "<!--" in line and "-->" not in line.split("<!--", 1)[1]:
            in_html = True
        if in_html and "-->" in line:
            in_html = False
        if not was_comment:
            out.append((n, line))
    return out


def _doors_found(root=FRONTEND):
    """Every line in the frontend's scripts and pages that names the spreadsheet step or the intake's
    ?edit parameter, as (file relative to frontend/, line number, line)."""
    found = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in (".js", ".html"):
            continue
        rel = path.relative_to(root).as_posix()
        text = path.read_bytes().decode("utf-8", errors="replace")
        for n, line in _code_lines(text):
            if "estimate-review.html" in line or "edit=1" in line or '"edit"' in line or "'edit'" in line:
                found.append((rel, n, line.strip()))
    return found


def test_every_way_into_the_spreadsheet_or_the_live_intake_is_classified():
    """THE DISCOVERED-DOOR SCAN. The guards stand at the destinations, so a link that nobody remembered
    is still covered, and this is what keeps it so: every line in the frontend that opens the spreadsheet
    step (/estimate-review.html) or the intake with a project (?edit=1) has to be in DOORS with the guard
    that covers it. A new one is red until somebody says which guard covers it, which is the question
    that matters. (The bell's links are built in backend/notifications.py, as `/?d=<id>&edit=1`: the
    same destination, covered by the same guard.)

    Mutation: add a link to /estimate-review.html or ?edit=1 anywhere in the frontend."""
    found = _doors_found()
    assert len(found) >= 15, "the scan found suspiciously few doors: %d" % len(found)
    unlisted = [(rel, n, line) for rel, n, line in found
                if not any(rel == f and text in line for f, text, _c, _g, _w in DOORS)]
    assert not unlisted, (
        "a door the guards were not asked about. Add it to DOORS in this file with the destination "
        "guard that covers it:\n" + "\n".join("  %s:%d  %s" % u for u in unlisted))


@pytest.mark.parametrize("file, text, count, guard, why", DOORS, ids=["%s|%s" % (d[0], d[1]) for d in DOORS])
def test_each_listed_door_is_still_there_exactly_as_often_as_listed(file, text, count, guard, why):
    """A row the code no longer has is a row nobody maintains, and a count that grew is a second door
    hiding behind the first one's description."""
    hits = [(n, line) for rel, n, line in _doors_found() if rel == file and text in line]
    assert len(hits) == count, "%s: %r is on %d lines, the table says %d: %r" % (
        file, text, len(hits), count, hits)


def test_the_guard_each_door_names_is_the_one_its_destination_has():
    """A door that opens /estimate-review.html is covered by the spreadsheet guard, one that opens the
    intake with a project by the intake guard. The table cannot claim the wrong one, and a 'not a door'
    row says why."""
    for file, text, _count, guard, why in DOORS:
        assert why and why.strip(), (file, text)
        if guard == NOT_A_DOOR:
            assert "estimate-review.html" not in text
        elif "estimate-review.html" in text:
            assert guard == SHEET, (file, text)
        else:
            assert "edit" in text and guard == INTAKE, (file, text)


def test_the_two_destinations_load_the_scripts_that_hold_the_guards():
    """The guards are in estimate-review.js and index.js, so the pages that are the destinations have to
    load them, and shared.js (where isV2Draft lives) ahead of them."""
    for page, script in (("estimate-review.html", "/js/estimate-review.js"), ("index.html", "/js/index.js")):
        html = (FRONTEND / page).read_text(encoding="utf-8")
        assert "/shared.js" in html and script in html, page
        assert html.index("/shared.js") < html.index(script), "%s loads %s before shared.js" % (page, script)


def test_the_door_scan_sees_a_door_when_one_is_added(tmp_path):
    """The scan above would pass if it saw nothing. Point it at a frontend holding two new links, a
    comment that names the same strings, and a comment block that spans lines: it has to report the
    two links and neither comment."""
    fake = tmp_path / "frontend"
    (fake / "js").mkdir(parents=True)
    (fake / "js" / "new-page.js").write_text(
        'window.location.assign(TW.withDraft("/estimate-review.html"));\n'
        "// and a comment that names /estimate-review.html and ?edit=1, which is not a door\n"
        "/* a block\n   that names ?d=x&edit=1 across lines */\n"
        'go("/?d=" + id + "&edit=1");\n', encoding="utf-8")
    (fake / "new.html").write_text(
        "<!-- a comment that spans\n  lines and names /estimate-review.html -->\n"
        '<a href="/estimate-review.html">Estimate</a>\n', encoding="utf-8")
    found = _doors_found(fake)
    assert [(rel, n) for rel, n, _l in found] == [("js/new-page.js", 1), ("js/new-page.js", 5),
                                                  ("new.html", 3)], found
    unlisted = [f for f in found if not any(f[0] == d[0] and d[1] in f[2] for d in DOORS)]
    assert len(unlisted) == 3, "the new doors would have passed as classified"


# ══ 5. the test copy ═════════════════════════════════════════════════════════════════════════════
WORK_TYPES = ["epoxy", "polish", "combo", "gyp"]
# An independent list of what the spreadsheet derives, and what the server owns: the oracle the
# allowlist is checked against, written out here and not read from the code under test.
#
# `tax_flags_per_sheet` WAS ON THIS LIST AND IS NOT ANY MORE (Phase 7b). It is the estimate screen's mark
# that every sheet holds its own Taxable and Remodel answer, and it is written by the spreadsheet, so it
# looked derived. It is not a price and it carries none: it is what says how the copied tax cells are to be
# read. A copy without it reads a split project as an unsplit one, and v2's first save writes the base's
# answer over the Leveling and Gypsum options' own. So it is copied on purpose, and
# test_a_copy_of_a_split_source_stays_split pins that it is.
DERIVED = [
    "priced_tabs", "rooms", "base_tab_id", "proposal_lump_sum", "proposal_sales_tax",
    "proposal_remodel_tax", "proposal_taxable", "proposal_remodel_on", "sheet_area", "hf_lump_sums",
    "cost_snapshot", "phase_price", "computed_bid", "alternate_computed_bid", "generate_result",
    "generated_lump_sum", "lump_sum_display", "proposal_payload", "proposal_payload_key",
    "tab_opts", "tab_copies", "tab_labels", "tab_order", "tab_notes", "tab_structs", "lock_overrides",
    "tax_layout", "tax_inclusion", "price_overrides", "price_lines", "extras",
    "paragraph_overrides", "paragraph_overrides_all", "system_name", "texture", "scope_notes",
    "schedule_notes", "exclusions", "notes_text", "estimator_name",
    "dropbox_result", "portal_message", "portal_emails", "require_deposit", "job_number",
    "info_cell_values", "notify_picks", "won", "handed_off", "closed_lost", "on_hold",
]
SERVER_OWNED = ["is_test", "archived", "assigned_estimator", "__draft_id"]


@pytest.mark.parametrize("wt", WORK_TYPES)
def test_a_copy_of_a_spreadsheet_bid_holds_only_what_the_allowlist_names(ran, wt):
    """One spreadsheet-built draft per work type (every derived key the estimate screen and the proposal
    step leave behind, the sheet's own cells, the intake answers). Whatever comes out is a subset of
    COPYABLE_KEYS, so a key the spreadsheet learns to write tomorrow is left behind until somebody lists
    it. THIS IS WHAT A DENYLIST COULD NOT DO.

    Mutation: `Object.assign({}, srcData)` (the MUTATION test below)."""
    r = ran["sandbox"]["byWorkType"][wt]
    allowed = set(ran["sandbox"]["copyableKeys"])
    assert set(r["keys"]) <= allowed, sorted(set(r["keys"]) - allowed)
    assert len(r["sourceKeys"]) > len(r["keys"]) + 20, "the source blob is not spreadsheet-sized"


@pytest.mark.parametrize("wt", WORK_TYPES)
def test_no_derived_or_server_owned_key_survives_in_a_copy(ran, wt):
    """The stale-total defect, key by key: priced_tabs and proposal_lump_sum are what made the copy
    print the source's price, and computed_bid, the files built from it and what was done with them
    belong to the SOURCE. The server's keys (is_test especially: the source may carry `false`, and this
    page PUTs the whole blob on every autosave, so copying it would file the copy as a test and then put
    it back in Active seconds later) and the ownership stamp stay with the source."""
    keys = set(ran["sandbox"]["byWorkType"][wt]["keys"])
    assert not keys & set(DERIVED), sorted(keys & set(DERIVED))
    assert not keys & set(SERVER_OWNED), sorted(keys & set(SERVER_OWNED))


def test_the_allowlist_itself_names_no_derived_or_server_owned_key(ran):
    allowed = set(ran["sandbox"]["copyableKeys"])
    assert not allowed & set(DERIVED), sorted(allowed & set(DERIVED))
    assert not allowed & set(SERVER_OWNED), sorted(allowed & set(SERVER_OWNED))
    assert len(allowed) == len(ran["sandbox"]["copyableKeys"]), "a key is listed twice"


@pytest.mark.parametrize("wt", WORK_TYPES)
def test_a_copy_keeps_what_a_person_typed(ran, wt):
    """The project and intake answers both intake forms save, the quantities, the contacts, the drawings
    box, the county. Compared value for value with the source, for every key the list names (the marks
    and the project name are the copy's own and are checked next)."""
    r = ran["sandbox"]["byWorkType"][wt]
    own = {"project_name", "cell_values", "beta_sandbox_of", "beta_sandbox_of_name"}
    kept = [k for k in ran["sandbox"]["copyableKeys"] if k not in own and k in r["source"]]
    assert len(kept) >= 35, "the source blob lost its intake answers: %d" % len(kept)
    for k in kept:
        assert r["copy"][k] == r["source"][k], k
    for k in ("address", "city_state", "audience", "work_type", "polish_sf", "system_1_sf", "zip",
              "contact_email", "drawings_dated", "spec_section", "county", "county_remodel_rate",
              "remodel_rate_override"):
        assert k in r["copy"], k


@pytest.mark.parametrize("wt", WORK_TYPES)
def test_a_copy_keeps_the_job_conditions_and_not_the_rest_of_the_sheet(ran, wt):
    """cell_values holds the sheet's own working (the project block, the quantities, the rates) AND the
    job's answers (local, prevailing wage, taxable, remodel tax, renovation, dye, joint filler, bulk
    discount). The v2 intake reads the second back; v2 never reads the first.

    A v2 test copy is itself priced on Polish. For a split source whose base is not Polish, buildCopy moves
    the source base's own Taxable/Remodel answers into Polish!B6/Polish!D6 so the copy opens at the bid it is
    meant to compare against. All other condition cells are byte-for-byte from the source."""
    r = ran["sandbox"]["byWorkType"][wt]
    # the live intake's condition cells, and (the fixture is a split draft) the base sheets' own tax cells
    cells = set(ran["sandbox"]["conditionCells"]) | _base_sheets_own_tax_cells()
    assert r["cellKeys"] and set(r["cellKeys"]) == cells, sorted(set(r["cellKeys"]) ^ cells)
    expected = dict(r["source"]["cell_values"])
    if wt == "epoxy":
        expected["Polish!B6"] = expected["Epoxy!B6"]
        expected["Polish!D6"] = expected["Epoxy!D6"]
    elif wt == "gyp":
        expected["Polish!B6"] = expected['Gyp (USG 1-8")!B8']
        expected["Polish!D6"] = expected['Gyp (USG 1-8")!D8']
    for k in r["cellKeys"]:
        assert r["copy"]["cell_values"][k] == expected[k], k
    for sheet_only in ("Epoxy!B1", "Epoxy!E20", "Polish!E18", "Epoxy!E34", "Polish!C25", "Epoxy!D77"):
        assert sheet_only in r["source"]["cell_values"] and sheet_only not in r["cellKeys"], sheet_only


def _base_sheets_own_tax_cells():
    """The cells a SPLIT draft holds the job's Taxable and Remodel answers in: the own flag cells of the
    three sheets a job can be priced on (Epoxy, Polish, the gyp base), read from the BACKEND's table of
    every flag-block sheet and its (Taxable?, Remodel Tax?) cells, an independent source from the one
    under test. The live intake never writes the Polish and Gyp D8 ones itself: it reads them from the
    estimate screen's snapshot, so they are not on its table."""
    import estimate_writer as ew
    cells = set()
    for sheet in ("Epoxy", "Polish", ew.GYP_SHEET):
        cells.update("%s!%s" % (sheet, addr) for addr in ew.FLAG_BLOCK_CELLS[sheet])
    return cells


def test_the_cells_a_copy_keeps_are_the_ones_the_live_intake_writes_and_the_base_sheets_own_tax_cells(ran):
    """COPYABLE_CELLS is READ FROM THE ONE CONDITIONS TABLE since Phase 7 (js/work-types.js copyableCells;
    docs/v2-architecture.md 7.3), no longer a second copy of the live intake's cells. The live intake still
    keeps its own CONDITIONS literal until Phase 9, so this stays as the comparison of the two: the intake's
    table is lifted out of index.js and evaluated by the harness, so a condition (or a cell) added to either
    side that the other does not know turns this red.

    PHASE 7b ADDS THE BASE SHEETS' OWN TAX CELLS, and only those: Polish!B6, Polish!D6 and the gyp base's D8
    (Epoxy's and the gyp base's B8 are on the intake's table already). A split draft holds the job's tax
    answers there, so a copy that kept the `tax_flags_per_sheet` mark and not these would arrive split and
    answerless. The extra set comes from the backend's FLAG_BLOCK_CELLS, not from the table under test.

    Mutation: add a condition (or a cell) to CONDITIONS in index.js, or to the table in work-types.js."""
    s = ran["sandbox"]
    expected = set(s["conditionCells"]) | _base_sheets_own_tax_cells()
    assert sorted(s["copyableCells"]) == sorted(expected)
    assert len(s["conditionCells"]) >= 10, "the lift of CONDITIONS found too little: %r" % s["conditionCells"]
    assert set(s["copyableCells"]) - set(s["conditionCells"]) == {"Polish!B6", "Polish!D6", 'Gyp (USG 1-8")!D8'}


@pytest.mark.parametrize("wt", WORK_TYPES)
def test_a_copy_of_a_split_source_stays_split(ran, wt):
    """`tax_flags_per_sheet` is copied (it is not a spreadsheet price: see the note over DERIVED), and so are
    the answers it refers to. The harness's spreadsheet blob is a split draft (the mark is on it), so every
    copy of it must carry the mark with the value the source had.

    Mutation: take `tax_flags_per_sheet` off COPYABLE_KEYS (test_the_copy_of_a_split_source_forgetting_the_
    mark_is_caught below)."""
    r = ran["sandbox"]["byWorkType"][wt]
    assert r["source"]["tax_flags_per_sheet"] is True, "the fixture is no longer a split draft"
    assert r["copy"].get("tax_flags_per_sheet") is True, "the copy lost the mark, so it reads as an unsplit draft"
    assert "tax_flags_per_sheet" in ran["sandbox"]["copyableKeys"]


def test_the_copy_is_renamed_and_marked_and_the_source_is_left_alone(ran):
    for wt in WORK_TYPES:
        r = ran["sandbox"]["byWorkType"][wt]
        assert r["copy"]["project_name"] == "Nearman Creek (beta test)"
        assert r["copy"]["beta_sandbox_of"] == "src-1" and r["copy"]["beta_sandbox_of_name"] == "Nearman Creek"
        assert r["sourceUntouched"] is True, "buildCopy changed the source row it was handed"


def test_a_source_with_little_in_it_still_makes_a_marked_copy(ran):
    s = ran["sandbox"]
    assert s["empty"] == {"project_name": "Untitled (beta test)", "beta_sandbox_of": "src-2",
                          "beta_sandbox_of_name": ""}
    assert "cell_values" not in s["noCells"] and s["noCells"]["project_name"] == "X (beta test)"
    assert s["oneCell"]["cell_values"] == {"Epoxy!B6": "No"}, "only the condition cell is carried"


def test_a_key_named_like_an_objects_machinery_cannot_name_its_way_into_a_copy(ran):
    """Every key written is a name from the two lists, never one read out of the source, so a source
    holding `__proto__` or `constructor` (JSON.parse makes them own properties) changes nothing."""
    s = ran["sandbox"]
    assert s["hostile"] == {"project_name": "Z (beta test)", "cell_values": {"Epoxy!B6": "Yes"},
                            "beta_sandbox_of": "src-5", "beta_sandbox_of_name": "Z"}
    assert s["hostilePolluted"] is False


def test_letting_the_copy_take_everything_again_is_caught(cases_file, tmp_path):
    """MUTATION. The old buildCopy: a spread of the source. The spreadsheet's price comes back."""
    broken = break_source(tmp_path, "js/polish-sandbox.js", "    var blob = {};",
                          "    var blob = Object.assign({}, srcData);")
    r = _run(broken, cases_file)["sandbox"]["byWorkType"]["polish"]
    survivors = set(r["keys"]) & {"priced_tabs", "proposal_lump_sum", "computed_bid"}
    assert survivors == {"priced_tabs", "proposal_lump_sum", "computed_bid"}


def test_the_copy_of_a_split_source_forgetting_the_mark_is_caught(cases_file, tmp_path):
    """MUTATION. `tax_flags_per_sheet` off the allowlist: the copy of a split project arrives unmarked, and
    v2 reads it as an unsplit one. test_a_copy_of_a_split_source_stays_split has to go red on this."""
    broken = break_source(tmp_path, "js/polish-sandbox.js",
                          '    "polish_estimate", "cell_values", "tax_flags_per_sheet",',
                          '    "polish_estimate", "cell_values",')
    r = _run(broken, cases_file)["sandbox"]["byWorkType"]["polish"]
    assert "tax_flags_per_sheet" not in r["copy"], "the mutation did not take the mark off the allowlist"
    assert r["source"]["tax_flags_per_sheet"] is True


# ══ 6. a stale copy that already exists ══════════════════════════════════════════════════════════
def test_a_stale_v2_copy_is_read_without_the_spreadsheets_numbers(ran):
    """THE EXISTING COPIES. A v2 test copy made before the allowlist still holds the source's
    priced_tabs, proposal_lump_sum and the rest. The Proposal step reads this view, so its lump sum falls
    through to `computed_bid.full_bid.total_base_bid`. Everything the spreadsheet derived is gone from
    the view (the nine keys the work item named, and the three more its snapshot writes); computed_bid is
    v2's own and stays. test_files_door.py runs the real Proposal step over such a copy.

    Mutation: make the view return the blob (the MUTATION test below)."""
    v = ran["view"]["stale"]
    assert v["same"] is False and v["total"] == 14224
    for gone in ("priced_tabs", "rooms", "base_tab_id", "proposal_lump_sum", "proposal_sales_tax",
                 "proposal_remodel_tax", "proposal_taxable", "proposal_remodel_on", "sheet_area",
                 "hf_lump_sums", "cost_snapshot", "phase_price"):
        assert gone not in v["keys"], gone
    assert "computed_bid" in v["keys"] and "polish_estimate" in v["keys"]
    assert v["keys"] == ["project_name", "work_type", "polish_estimate", "computed_bid",
                         "price_overrides", "tab_opts", "cell_values"], "the view dropped something else"


def test_the_view_writes_nothing_and_shares_what_the_page_mutates_in_place(ran):
    """The stored draft keeps its keys (opening a project changes nothing), and nested objects are the
    blob's own: the Proposal step mutates them in place and hands the same references to setState, which
    a deep copy would cut (see liveKey in proposal-review.js)."""
    v = ran["view"]["stale"]
    assert v["originalUntouched"] is True
    assert v["computedBidShared"] is True and v["nestedShared"] is True


@pytest.mark.parametrize("which", ["plainSheet", "oldPolishEstimate", "allMarked", "cleanV2"])
def test_every_other_draft_comes_back_as_the_very_same_object(ran, which):
    """A spreadsheet draft, a pre-beta polish estimate (no version), a v2 draft whose price snapshot v2
    wrote itself (every tab marked v2: true, a later phase), and a v2 draft that carries none of the
    spreadsheet's keys. Identity, not equality: the page's snapshot semantics are untouched."""
    assert ran["view"][which]["same"] is True


def test_the_mark_is_exactly_true_and_nothing_else(ran):
    """`v2: "yes"` is not the mark. A mark that anything truthy could carry would let a stale snapshot
    through on the strength of a stray field."""
    assert ran["view"]["markIsExactlyTrue"]["same"] is False


@pytest.mark.parametrize("which", ["someMarked", "emptyTabsStaleTotal", "nullTab", "textVersion"])
def test_a_v2_draft_is_trusted_only_when_every_priced_tab_is_marked_v2(ran, which):
    """One unmarked tab, no tabs at all beside a stale total, a hole in the list, and a version stored as
    text: each is read without the spreadsheet's keys."""
    r = ran["view"][which]
    assert r["same"] is False
    assert "proposal_lump_sum" not in r["keys"] and "priced_tabs" not in r["keys"]


def test_a_value_that_is_not_a_draft_passes_through(ran):
    assert ran["view"]["notObjects"] == [True, True, True, True]


def test_turning_the_view_off_gives_the_stale_total_back(cases_file, tmp_path):
    """MUTATION. With the view a no-op the stale copy keeps its spreadsheet keys."""
    broken = break_source(tmp_path, "shared.js", "    if (!isV2Draft(blob)) return blob;",
                          "    return blob;")
    v = _run(broken, cases_file)["view"]["stale"]
    assert v["same"] is True and "proposal_lump_sum" in v["keys"]


def test_the_list_of_spreadsheet_keys_holds_everything_the_estimate_screen_writes(ran):
    """SHEET_PRICING_KEYS is what the view strips. The keys come out of the REAL snapshotLumpSumsToState
    (every `state.<key> =` in it), so a key the snapshot learns to write that the list lacks is a stale
    number the view would let through. computed_bid and alternate_computed_bid are the engine's, which
    snapshotLumpSumsToState only nulls, and v2 owns computed_bid.

    Mutation: add `state.something = ...` to snapshotLumpSumsToState."""
    written = set(ran["snapshotKeys"])
    assert len(written) >= 10, "the scan found too few keys: %r" % sorted(written)
    listed = set(ran["sandbox"]["sheetPricingKeys"])
    assert written - {"computed_bid", "alternate_computed_bid"} <= listed, sorted(written - listed)
    assert "computed_bid" not in listed


# ══ 7. what Continue takes off the STORED copy ═══════════════════════════════════════════════════
# The view hides the spreadsheet's keys from the Proposal step and writes nothing. A copy made before the
# allowlist still HOLDS them, and the customer's portal prices a proposal from the stored `rooms`, so the
# stored draft has to lose what the page never read, or the document and the draft disagree and the send is
# refused with nothing on any page to clear it (the review of Phase 2). v2SheetKeysOut is the patch Continue
# writes. test_files_door.py runs it through the real Proposal step; these run the function itself.
STALE_SHAPED = ["stale", "someMarked", "markIsExactlyTrue", "emptyTabsStaleTotal", "nullTab", "textVersion"]
HANDED_BACK_WHOLE = ["plainSheet", "oldPolishEstimate", "allMarked", "cleanV2"]


@pytest.mark.parametrize("which", STALE_SHAPED)
def test_the_patch_names_every_spreadsheet_key_a_stale_draft_holds(ran, which):
    """Each draft the view reads without the spreadsheet's keys gets a patch naming every one of them,
    each as `undefined`: the value setState's merge writes and JSON.stringify leaves out.

    Mutation: the patch that returns {} (the MUTATION test below)."""
    r = ran["keysOut"][which]
    assert r["keys"] == ran["sandbox"]["sheetPricingKeys"], which
    assert r["allUndefined"] is True and r["originalUntouched"] is True


def test_the_patch_names_only_the_keys_the_draft_holds(ran):
    """A copy that holds two of the twelve is handed two, in the list's order."""
    r = ran["keysOut"]["someKeysOnly"]
    assert r["keys"] == ["rooms", "phase_price"] and r["storedEqualsView"] is True


@pytest.mark.parametrize("which", HANDED_BACK_WHOLE)
def test_the_patch_is_empty_for_a_draft_the_view_hands_back_whole(ran, which):
    """A spreadsheet draft, a pre-beta polish estimate, a v2 draft whose price snapshot v2 wrote itself and
    a v2 draft that holds none of the keys lose nothing: the spreadsheet's own keys are the only record a
    spreadsheet bid has, and a later phase's v2 snapshot is v2's own.

    Mutation: the patch that acts on every draft (the MUTATION test below)."""
    assert ran["keysOut"][which]["keys"] == [], which


def test_a_value_that_is_not_a_draft_gets_an_empty_patch(ran):
    assert ran["keysOut"]["notObjects"] == [[], [], [], []]


@pytest.mark.parametrize("which", STALE_SHAPED + HANDED_BACK_WHOLE + ["someKeysOnly"])
def test_what_is_stored_after_the_patch_is_exactly_what_the_page_was_given(ran, which):
    """THE LAW. Apply the patch the way setState does (merge, then the JSON round trip every write goes
    through) and the stored blob equals what v2PricingView handed the page, key for key and value for
    value. A patch that took too little leaves the portal pricing the spreadsheet's rooms; one that took
    too much costs a page a key it was still reading."""
    r = ran["keysOut"][which]
    assert r["storedEqualsView"] is True, which
    assert r["originalUntouched"] is True, "the patch changed the blob it was handed"


@pytest.mark.parametrize("which", STALE_SHAPED + HANDED_BACK_WHOLE + ["someKeysOnly"])
def test_taking_the_keys_off_twice_takes_nothing_more(ran, which):
    """Continue runs again and again (the door, the estimator, a second tab): the second run finds the
    copy already clean and writes nothing further."""
    assert ran["keysOut"][which]["nothingLeftToTake"] == [], which


def test_a_key_named_like_an_objects_machinery_cannot_name_its_way_into_the_patch(ran):
    """Every key in the patch is a name from SHEET_PRICING_KEYS, never one read out of the draft, so a draft
    holding `__proto__` or `constructor` (JSON.parse makes them own properties) changes nothing."""
    h = ran["keysOut"]["hostile"]
    assert h["keys"] == ["rooms"]
    assert h["inheritsFromBlob"] is False and h["patchPrototypeIsPlain"] is True


def test_a_patch_that_takes_nothing_is_caught(cases_file, tmp_path):
    """MUTATION. v2SheetKeysOut returning {}: the page reads the view and the stored draft keeps every
    key, which is the first pass of Phase 2. The law has to notice."""
    broken = break_source(
        tmp_path, "shared.js",
        "    return Object.fromEntries(SHEET_PRICING_KEYS.filter(has).map((k) => [k, undefined]));",
        "    return {};")
    r = _run(broken, cases_file)["keysOut"]["stale"]
    assert r["keys"] == [] and r["storedEqualsView"] is False


def test_a_patch_that_acts_on_every_draft_is_caught(cases_file, tmp_path):
    """MUTATION. The patch no longer asks the view whether it hid anything: a spreadsheet draft would
    lose the keys that are the only record of its price. The law and the empty-patch cases both notice."""
    broken = break_source(tmp_path, "shared.js", "    if (v2PricingView(blob) === blob) return {};",
                          "    if (false) return {};")
    r = _run(broken, cases_file)["keysOut"]
    assert r["plainSheet"]["keys"] != [] and r["plainSheet"]["storedEqualsView"] is False
    assert r["allMarked"]["keys"] != [] and r["allMarked"]["storedEqualsView"] is False
    assert "threw" in r["notObjects"], "and a value that is not a draft is no longer passed over"
