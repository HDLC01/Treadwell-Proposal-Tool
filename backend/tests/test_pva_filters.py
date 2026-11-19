"""Plan vs Actual: the Work type, Foreman and Status filters, the pager, and the view in the address
(#819, spec #818).

Three seams, each tested through its public face:

  * THE PURE CORE (js/project-calendar-core.js, run under node): the visible-jobs rule with the
    two new filters alone and combined with the search and the status; the Foreman options (trimmed,
    deduped without regard to case, sorted, "No foreman" when a job has none); the page slice and
    the pager model (first, middle and last page, a page past the end, 25/50/100, the ellipsis);
    reading and writing the view in the query string, junk included; and the download address,
    which carries `work_type` and `foreman` but never the page.
  * THE PAGE (js/plan-vs-actual.js + project-calendar.html), run WHOLE in a small fake browser
    (tests/js/pva-filters-harness.js): the filters are labelled selects, the Status select and the
    count buttons are one filter, Clear filters resets everything, the pager moves, a filter change
    goes back to page 1, the address follows, and Back from a job's detail keeps the page.
  * The server's mirror rule and the export route are in test_plan_vs_actual_xlsx.py, next to the
    test that already holds the page and the server to the same rows.

Every expected value is worked out by hand from the rows below, never by the code's own rule.
PUBLIC REPO: every job and person is made up.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

from test_project_calendar_core_js import FRONTEND, run

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "pva-filters-harness.js"
PAGE = FRONTEND / "project-calendar.html"
PVA = FRONTEND / "js" / "plan-vs-actual.js"
BASE = "/api/project-analytics/export.xlsx"

# Seven made-up rows. Work types come from the server's legend (Epoxy, Polish, Gyp); job:3 has none.
# Foremen: "Lee" first met as "Lee", "Pat" and " pat " the same person, job:4 and job:6 none.
ROWS = """
const pr = (o) => Object.assign({key:"", job_number:null, name:"", work_type:null, foreman:null,
  statuses:[]}, o);
const FX = [
  pr({key:"job:1", job_number:"26.601", name:"Example Clinic", work_type:"Epoxy", foreman:"Pat",
      statuses:["on_plan"]}),
  pr({key:"job:2", job_number:"26.602", name:"Example Depot", work_type:"Polish", foreman:"Sam",
      statuses:["behind", "over_budget"]}),
  pr({key:"job:3", job_number:"26.603", name:"Example Annex", foreman:" pat ",
      statuses:["not_linked"]}),
  pr({key:"job:4", job_number:"26.604", name:"Example Hall", work_type:"Polish", foreman:null,
      statuses:["behind"]}),
  pr({key:"job:5", job_number:"26.605", name:"Example Gym", work_type:"Gyp", foreman:"Lee"}),
  pr({key:"job:6", job_number:"26.606", name:"Example Shop", work_type:"Epoxy", foreman:"  ",
      statuses:["on_plan"]}),
  pr({key:"job:7", job_number:"26.607", name:"Example Yard", work_type:"Polish", foreman:"lee",
      statuses:["behind"]}),
];
const LEGEND = [{name:"Epoxy", color_id:"11", color:"#d50000"},
  {name:"Polish", color_id:"9", color:"#3f51b5"}, {name:"Gyp", color_id:"10", color:"#0b8043"}];
const DATA = {work_types: LEGEND, projects: FX,
  summary: {raken_read: true, counts: {on_plan: 2, behind: 3, over_budget: 1, not_linked: 1}}};
const keys = (rows) => rows.map((p) => p.key.slice(4));
const vis = (q, st, f) => keys(P.visibleProjects(FX, q, st, f));
"""


# ── the filter rule ─────────────────────────────────────────────────────────────────────────────
def test_each_new_filter_alone_picks_its_jobs():
    got = run(ROWS + 'out([vis("", "", {work_type: "Polish"}), vis("", "", {work_type: "Epoxy"}),'
              ' vis("", "", {work_type: "Work type unknown"}), vis("", "", {foreman: "Pat"}),'
              ' vis("", "", {foreman: "Lee"}), vis("", "", {foreman: "(none)"}),'
              ' vis("", "", {}), vis("", ""), vis("", "", {work_type: "", foreman: ""})])')
    every = ["1", "2", "3", "4", "5", "6", "7"]
    assert got == [["2", "4", "7"], ["1", "6"], ["3"], ["1", "3"], ["5", "7"], ["4", "6"],
                   every, every, every]


def test_the_filters_combine_with_each_other_the_search_and_the_status():
    got = run(ROWS + 'out([vis("", "over_budget", {work_type: "Polish"}),'
              ' vis("", "", {work_type: "Polish", foreman: "Lee"}),'
              ' vis("", "behind", {work_type: "Polish", foreman: "(none)"}),'
              ' vis("yard", "", {work_type: "Polish"}), vis("depot", "", {foreman: "Lee"}),'
              ' vis("", "", {work_type: "Epoxy", foreman: "(none)"}),'
              ' vis("example", "on_plan", {foreman: "Pat"}),'
              ' vis("26.60", "behind", {})])')
    assert got == [["2"], ["7"], ["4"], ["7"], [], ["6"], ["1"], ["2", "4", "7"]]


def test_foreman_matching_ignores_case_and_surrounding_spaces():
    got = run(ROWS + 'out([vis("", "", {foreman: "  PAT "}), vis("", "", {foreman: "lee"}),'
              ' vis("", "", {work_type: "polish"})])')
    assert got == [["1", "3"], ["5", "7"], ["2", "4", "7"]]


def test_the_foreman_options_are_the_distinct_foremen_sorted_with_no_foreman_last():
    """Deduped without regard to case or surrounding spaces, the spelling first met in the list
    kept, sorted without regard to case; "No foreman" only when a job has none."""
    got = run(ROWS + 'out([P.foremanOptions(FX), P.foremanOptions(FX.filter((p) => p.foreman'
              ' && p.foreman.trim())), P.foremanOptions([]), P.foremanOptions(null),'
              ' P.foremanOptions([pr({foreman: "zed"}), pr({foreman: "Amy"}), pr({foreman: "ZED"})])])')
    assert got[0] == [{"value": "Lee", "label": "Lee"}, {"value": "Pat", "label": "Pat"},
                      {"value": "Sam", "label": "Sam"},
                      {"value": "(none)", "label": "No foreman"}]
    assert got[1] == [{"value": "Lee", "label": "Lee"}, {"value": "Pat", "label": "Pat"},
                      {"value": "Sam", "label": "Sam"}], "no job without one: no No foreman"
    assert got[2] == [] and got[3] == []
    assert got[4] == [{"value": "Amy", "label": "Amy"}, {"value": "zed", "label": "zed"}]


def test_the_work_type_options_are_the_servers_list_and_the_unknown_label():
    got = run(ROWS + 'out([P.workTypeOptions(DATA), P.workTypeOptions({}),'
              ' P.workTypeOptions({work_types: [{name: "Epoxy"}, null, {name: ""}, {name: "Epoxy"}]})])')
    assert got[0] == [{"value": "Epoxy", "label": "Epoxy"}, {"value": "Polish", "label": "Polish"},
                      {"value": "Gyp", "label": "Gyp"},
                      {"value": "Work type unknown", "label": "Work type unknown"}]
    assert got[1] == [{"value": "Work type unknown", "label": "Work type unknown"}]
    assert got[2] == [{"value": "Epoxy", "label": "Epoxy"},
                      {"value": "Work type unknown", "label": "Work type unknown"}]


def test_a_value_the_lists_do_not_offer_filters_nothing():
    """The address can carry anything; only a value the page offers filters, in its offered
    spelling (the server's work_type_filter / foreman_filter are the same rule)."""
    got = run(ROWS + 'out([P.workTypeFilter(DATA, "polish"), P.workTypeFilter(DATA, " GYP "),'
              ' P.workTypeFilter(DATA, "Combo"), P.workTypeFilter(DATA, "work type unknown"),'
              ' P.workTypeFilter(DATA, null), P.foremanFilter(DATA, "PAT"),'
              ' P.foremanFilter(DATA, "Juan"), P.foremanFilter(DATA, "(none)"),'
              ' P.foremanFilter({projects: [pr({foreman: "Pat"})]}, "(none)"),'
              ' P.foremanFilter(DATA, ""), P.foremanFilter(null, "Pat")])')
    assert got == ["Polish", "Gyp", "", "Work type unknown", "", "Pat", "", "(none)", "", "", ""]


def test_the_filters_in_force_are_worked_out_from_the_view_and_the_list():
    got = run(ROWS + 'const v = (o) => Object.assign(P.readView(""), o);'
              'const un = Object.assign({}, DATA, {summary: {raken_read: false, counts: null}});'
              'out([P.viewFilters(DATA, v({q: "yard", status: "behind", work_type: "polish",'
              ' foreman: "LEE"})), P.viewFilters(un, v({status: "behind", foreman: "Juan"}))])')
    assert got[0] == {"q": "yard", "status": "behind", "work_type": "Polish", "foreman": "Lee"}
    assert got[1] == {"q": "", "status": "", "work_type": "", "foreman": ""}, \
        "a pressed count is ignored while the counts are not known, as before"


def test_the_count_says_m_of_n_while_anything_filters():
    got = run('out([P.listCountText(3, 7, "", "", {work_type: "Polish"}),'
              ' P.listCountText(2, 7, "", "", {foreman: "(none)"}),'
              ' P.listCountText(7, 7, "", "", {work_type: "", foreman: ""}),'
              ' P.listCountText(7, 7, "", ""), P.listCountText(1, 7, "x", "behind", {})])')
    assert got == ["3 of 7 jobs", "2 of 7 jobs", "7 jobs", "7 jobs", "1 of 7 jobs"]


def test_a_list_filtered_to_nothing_names_the_filters():
    got = run('out([P.noMatchText("", "", {work_type: "Polish", foreman: "Pat"}),'
              ' P.noMatchText("yard", "behind", {work_type: "Gyp", foreman: "(none)"}),'
              ' P.noMatchText("", "", {foreman: "(none)"}),'
              ' P.noMatchText("", "over_budget", {work_type: "Work type unknown"}),'
              ' P.noMatchText("pat", "behind", {}), P.noMatchText("", "", {})])')
    assert got == ["No job matches the filters: Polish, Foreman Pat.",
                   "No job matches the search and the filters: Gyp, No foreman, Behind.",
                   "No job matches the filters: No foreman.",
                   "No job matches the filters: Work type unknown, Over budget.",
                   "No Behind job matches the search.", ""]


def test_filters_active_is_true_while_the_search_or_any_filter_is_set():
    got = run('const v = (o) => Object.assign(P.readView(""), o);'
              'out([P.filtersActive(v({})), P.filtersActive(v({q: "  "})),'
              ' P.filtersActive(v({q: "x"})), P.filtersActive(v({status: "behind"})),'
              ' P.filtersActive(v({work_type: "Gyp"})), P.filtersActive(v({foreman: "(none)"})),'
              ' P.filtersActive(v({page: 3, per: 100}))])')
    assert got == [False, False, True, True, True, True, False]


# ── the pager ───────────────────────────────────────────────────────────────────────────────────
def test_the_pager_model_for_the_first_middle_and_last_page():
    got = run('out([P.pageModel(73, 1, 25), P.pageModel(73, 2, 25), P.pageModel(73, 3, 25)])')
    assert got[0] == {"page": 1, "pages": 3, "per": 25, "total": 73, "start": 0, "end": 25,
                      "text": "Showing 1–25 of 73", "prev": False, "next": True,
                      "items": [1, 2, 3]}
    assert got[1]["text"] == "Showing 26–50 of 73"
    assert (got[1]["start"], got[1]["end"], got[1]["prev"], got[1]["next"]) == (25, 50, True, True)
    assert got[2]["text"] == "Showing 51–73 of 73"
    assert (got[2]["start"], got[2]["end"], got[2]["prev"], got[2]["next"]) == (50, 73, True, False)


def test_a_page_past_the_end_shows_the_last_page_and_odd_input_reads_as_the_default():
    got = run('const m = (t, p, n) => { const x = P.pageModel(t, p, n);'
              ' return [x.page, x.pages, x.per, x.text]; };'
              'out([m(73, 9, 25), m(73, 1, 50), m(73, 2, 50), m(73, 1, 100), m(73, 1, 30),'
              ' m(73, 0, 25), m(73, -2, 25), m(73, "x", null), m(0, 4, 25), m(26, 2, 25),'
              ' m(1, 1, 25)])')
    assert got == [[3, 3, 25, "Showing 51–73 of 73"], [1, 2, 50, "Showing 1–50 of 73"],
                   [2, 2, 50, "Showing 51–73 of 73"], [1, 1, 100, "Showing 1–73 of 73"],
                   [1, 3, 25, "Showing 1–25 of 73"], [1, 3, 25, "Showing 1–25 of 73"],
                   [1, 3, 25, "Showing 1–25 of 73"], [1, 3, 25, "Showing 1–25 of 73"],
                   [1, 1, 25, ""], [2, 2, 25, "Showing 26 of 26"], [1, 1, 25, "Showing 1 of 1"]]


def test_a_long_pager_shortens_its_page_numbers_with_an_ellipsis():
    got = run('const it = (t, p) => P.pageModel(t, p, 25).items;'
              'out([it(300, 1), it(300, 4), it(300, 5), it(300, 6), it(300, 9), it(300, 12),'
              ' it(175, 3), it(200, 1), it(25, 1)])')
    e = "…"
    assert got == [[1, 2, 3, 4, 5, e, 12], [1, 2, 3, 4, 5, e, 12], [1, e, 4, 5, 6, e, 12],
                   [1, e, 5, 6, 7, e, 12], [1, e, 8, 9, 10, 11, 12], [1, e, 8, 9, 10, 11, 12],
                   [1, 2, 3, 4, 5, 6, 7], [1, 2, 3, 4, 5, e, 8], [1]]


def test_the_page_slice_is_the_models_start_and_end():
    got = run('const rows = Array.from({length: 73}, (_, i) => i + 1);'
              'const sl = (p, n) => P.pageSlice(rows, P.pageModel(rows.length, p, n));'
              'out([sl(1, 25).length, sl(2, 25)[0], sl(2, 25).slice(-1)[0], sl(3, 25),'
              ' sl(9, 50)[0], sl(1, 100).length, P.pageSlice([], P.pageModel(0, 1, 25))])')
    assert got[0] == 25 and got[1] == 26 and got[2] == 50
    assert got[3] == list(range(51, 74))
    assert got[4] == 51 and got[5] == 73 and got[6] == []


def test_the_page_sizes_are_25_50_and_100():
    assert run("out([P.PAGE_SIZES, P.PAGE_SIZE])") == [[25, 50, 100], 25]


# ── the view in the address ─────────────────────────────────────────────────────────────────────
DEFAULT = {"q": "", "status": "", "work_type": "", "foreman": "", "page": 1, "per": 25}


def test_the_view_is_read_from_the_query_string():
    got = run('out([P.readView(""), P.readView(null),'
              ' P.readView("?q=pat%20clinic&status=behind&work_type=Polish&foreman=Lee&page=2&per=50"),'
              ' P.readView("q=a+b&foreman=%28none%29"), P.readView("?per=100&page=12")])')
    assert got[0] == DEFAULT and got[1] == DEFAULT
    assert got[2] == {"q": "pat clinic", "status": "behind", "work_type": "Polish",
                      "foreman": "Lee", "page": 2, "per": 50}
    assert got[3] == dict(DEFAULT, q="a b", foreman="(none)")
    assert got[4] == dict(DEFAULT, page=12, per=100)


def test_junk_in_the_address_falls_back_to_the_defaults():
    got = run('const r = (s) => P.readView(s);'
              'out([r("?status=nope"), r("?status=BEHIND"), r("?page=0"), r("?page=-3"),'
              ' r("?page=2.5"), r("?page=1e3"), r("?page=abc"), r("?page=99999999"), r("?per=30"),'
              ' r("?per=25.0"), r("?per="), r("?q="),'
              ' r("?work_type=" + "x".repeat(300)).work_type.length,'
              ' r("?foreman=" + "y".repeat(300)).foreman.length, r("?q=" + "z".repeat(300)).q.length,'
              ' r("?zzz=1&page=2&page=5"), r("#schedule")])')
    for i in range(12):
        assert got[i] == DEFAULT, (i, got[i])
    assert got[12:15] == [200, 200, 200], "each text is cut to 200 characters, like the search"
    assert got[15] == dict(DEFAULT, page=2), "the first of a repeated key"
    assert got[16] == DEFAULT


def test_the_view_is_written_to_the_query_string_without_its_defaults():
    got = run('const v = (o) => Object.assign(P.readView(""), o);'
              'const w = (o) => P.viewQuery(v(o));'
              'out([w({}), w({q: "pat clinic", status: "behind", work_type: "Polish",'
              ' foreman: "(none)", page: 2, per: 50}), w({q: "   "}), w({page: 1, per: 25}),'
              ' w({q: "a&b=c#d"}), w({per: 100})])')
    assert got == ["", "?q=pat%20clinic&status=behind&work_type=Polish&foreman=(none)&page=2&per=50",
                   "", "", "?q=a%26b%3Dc%23d", "?per=100"]


def test_a_view_written_and_read_back_is_the_same_view():
    got = run('const v = Object.assign(P.readView(""), {q: "Example & co", status: "not_linked",'
              ' work_type: "Work type unknown", foreman: "O\'Neil", page: 4, per: 100});'
              'out([P.readView(P.viewQuery(v)), v])')
    assert got[0] == got[1]


def test_any_filter_search_or_page_size_change_goes_back_to_page_one():
    got = run('const v = Object.assign(P.readView(""), {page: 3});'
              'const n = (patch) => { const x = P.nextView(v, patch); return [x.page, x.per]; };'
              'out([n({page: 2}), n({work_type: "Polish"}), n({foreman: "Pat"}),'
              ' n({status: "behind"}), n({q: "x"}), n({per: 50}), n({per: 25}),'
              ' n({q: ""}), n({page: "junk"}), n({per: 7}),'
              ' P.nextView(v, {status: "nope"}).status, v.page])')
    assert got == [[2, 25], [1, 25], [1, 25], [1, 25], [1, 25], [1, 50], [3, 25],
                   [3, 25], [1, 25], [3, 25], "", 3], \
        "an unchanged value keeps the page; the view handed in is never changed"


def test_clear_filters_resets_every_filter_and_the_search_and_keeps_the_page_size():
    got = run('const v = {q: "yard", status: "behind", work_type: "Gyp", foreman: "Lee", page: 4,'
              ' per: 50};'
              'out(P.clearedView(v))')
    assert got == dict(DEFAULT, per=50)


def test_a_loaded_list_settles_the_views_filters_to_what_it_offers():
    """A shared link's Work type or Foreman the list does not offer is dropped; one it offers in
    another spelling takes the offered one. Before anything is listed nothing is dropped."""
    got = run(ROWS + 'const v = (o) => Object.assign(P.readView(""), o);'
              'out([P.settleView(v({work_type: "polish", foreman: " pat", page: 3}), DATA),'
              ' P.settleView(v({work_type: "Combo", foreman: "Juan", status: "behind"}), DATA),'
              ' P.settleView(v({work_type: "Combo", foreman: "Juan"}), {projects: []}),'
              ' P.settleView(v({work_type: "Combo"}), null)])')
    assert got[0] == dict(DEFAULT, work_type="Polish", foreman="Pat", page=3)
    assert got[1] == dict(DEFAULT, status="behind")
    assert got[2] == dict(DEFAULT, work_type="Combo", foreman="Juan")
    assert got[3] == dict(DEFAULT, work_type="Combo")


def test_the_filter_options_for_the_page():
    got = run(ROWS + 'const un = Object.assign({}, DATA, {summary: {raken_read: false}});'
              'const a = P.filterOptions(DATA), b = P.filterOptions(un);'
              'out([a.statuses, a.status_known, b.status_known, a.work_types.length,'
              ' a.foremen.length, P.filterOptions(null)])')
    assert got[0] == [{"value": "on_plan", "label": "On plan"}, {"value": "behind", "label": "Behind"},
                      {"value": "over_budget", "label": "Over budget"},
                      {"value": "not_linked", "label": "Not linked"}]
    assert got[1:5] == [True, False, 4, 4]
    assert got[5] == {"work_types": [{"value": "Work type unknown", "label": "Work type unknown"}],
                      "foremen": [], "statuses": got[0], "status_known": False}


# ── the download address ────────────────────────────────────────────────────────────────────────
def test_the_download_carries_work_type_and_foreman_but_never_the_page():
    got = run('out([P.downloadHref("", "", {work_type: "Polish"}),'
              ' P.downloadHref("pat", "behind", {work_type: "Work type unknown", foreman: "(none)",'
              ' page: 3, per: 50}), P.downloadHref("", "", {foreman: "O\'Neil & Son"}),'
              ' P.downloadHref("", "", {work_type: "w".repeat(250)}),'
              ' P.downloadHref("", "", {}), P.downloadHref("", ""), P.downloadHref("", "", null)])')
    assert got == [BASE + "?work_type=Polish",
                   BASE + "?status=behind&q=pat&work_type=Work%20type%20unknown&foreman=(none)",
                   BASE + "?foreman=O'Neil%20%26%20Son",
                   BASE + "?work_type=" + "w" * 200, BASE, BASE, BASE]


# ── the page, run whole in a fake browser ───────────────────────────────────────────────────────
def page(scenario, search="", hash_=""):
    """Run js/plan-vs-actual.js and the real core in tests/js/pva-filters-harness.js, then the
    scenario's steps; returns what the harness printed."""
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND), scenario, search, hash_],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_page_opens_on_page_one_of_25_with_the_pager_under_the_list():
    got = page("open")
    assert got["rows"] == 25 and got["first"] == "26.701"
    assert got["range"] == "Showing 1–25 of 60"
    assert got["count"] == "60 jobs"
    assert got["pages"] == ["1", "2", "3"] and got["current"] == "1"
    assert got["prev_disabled"] is True and got["next_disabled"] is False
    assert got["url"] == "/project-calendar.html"
    assert got["clear_hidden"] is True


def test_the_filters_render_as_labelled_selects_with_all_first():
    got = page("open")
    assert got["wt_options"] == [["", "All"], ["Epoxy", "Epoxy"], ["Polish", "Polish"],
                                 ["Gyp", "Gyp"], ["Work type unknown", "Work type unknown"]]
    assert got["fm_options"] == [["", "All"], ["Lee", "Lee"], ["Pat", "Pat"], ["Sam", "Sam"],
                                 ["(none)", "No foreman"]]
    assert got["st_options"] == [["", "All"], ["on_plan", "On plan"], ["behind", "Behind"],
                                 ["over_budget", "Over budget"], ["not_linked", "Not linked"]]
    assert got["st_disabled"] is False
    html = PAGE.read_text(encoding="utf-8")
    for sid, label in (("pva-wt", "Work type"), ("pva-fm", "Foreman"), ("pva-st", "Status"),
                       ("pva-per", "Per page")):
        assert re.search(r'<label[^>]*for="%s"[^>]*>%s</label>' % (sid, label), html), sid
        assert re.search(r'<select id="%s" class="tw-select"' % sid, html), sid
    assert '<button type="button" id="pva-clear" class="btn"' in html
    assert re.search(r'<nav id="pva-pager"[^>]*aria-label="Pages"', html)


def test_a_filter_change_goes_back_to_page_one_and_into_the_address():
    got = page("polish")
    assert got["before"] == {"page": "2", "url": "/project-calendar.html?page=2"}
    assert got["rows"] == 25 and got["current"] == "1"
    assert got["range"] == "Showing 1–25 of 30"
    assert got["count"] == "30 of 60 jobs"
    assert got["url"] == "/project-calendar.html?work_type=Polish"
    assert got["clear_hidden"] is False


def test_the_status_select_and_the_count_buttons_are_one_filter():
    got = page("status")
    assert got["after_select"] == {"pressed": ["behind"], "select": "behind",
                                   "url": "/project-calendar.html?status=behind", "rows": 20}
    assert got["after_tile"] == {"pressed": ["over_budget"], "select": "over_budget",
                                 "url": "/project-calendar.html?status=over_budget", "rows": 10}
    assert got["after_showall"] == {"pressed": [], "select": "",
                                    "url": "/project-calendar.html", "rows": 25}


def test_the_status_select_is_disabled_while_the_counts_are_not_known():
    got = page("unknown-counts", "?status=behind")
    assert got["st_disabled"] is True and got["select"] == ""
    assert got["rows"] == 25 and got["count"] == "60 jobs", "an unknown count filters nothing"


def test_clear_filters_resets_everything_and_goes_to_page_one():
    got = page("clear", "?q=example&status=behind&work_type=Polish&foreman=Lee&page=2&per=50")
    assert got["before"]["count"] == "10 of 60 jobs"
    assert got["url"] == "/project-calendar.html?per=50"
    assert got["values"] == {"q": "", "wt": "", "fm": "", "st": "", "per": "50"}
    assert got["rows"] == 50 and got["current"] == "1" and got["clear_hidden"] is True
    assert got["focus"] == "pva-q"


def test_the_pager_moves_by_number_next_and_previous_and_keeps_the_focus():
    got = page("pager")
    assert got["steps"] == [
        ["3", "Showing 51–60 of 60", False, True, "/project-calendar.html?page=3"],
        ["2", "Showing 26–50 of 60", False, False, "/project-calendar.html?page=2"],
        ["3", "Showing 51–60 of 60", False, True, "/project-calendar.html?page=3"],
        ["1", "Showing 1–60 of 60", True, True, "/project-calendar.html?per=100"]]
    assert got["focus"][:3] == ["page:3", "page:prev", "page:3"], (
        "Next is disabled on the last page, so the focus goes to the current page")


def test_a_shared_link_opens_the_same_view_and_junk_falls_back():
    good = page("open", "?q=example&work_type=polish&foreman=LEE&page=2&per=25")
    assert good["values"] == {"q": "example", "wt": "Polish", "fm": "Lee", "st": "", "per": "25"}
    assert good["url"] == "/project-calendar.html?q=example&work_type=Polish&foreman=Lee", \
        "10 jobs fit one page, so page 2 is the last page, page 1"
    assert good["current"] == "1" and good["rows"] == 10
    junk = page("open", "?work_type=Combo&foreman=Juan&status=nope&page=x&per=7", "#schedule")
    assert junk["values"] == {"q": "", "wt": "", "fm": "", "st": "", "per": "25"}
    assert junk["rows"] == 25 and junk["url"] == "/project-calendar.html#schedule"
    assert junk["tab"] == "schedule", "#schedule still opens the Schedule"


def test_a_page_past_the_end_shows_the_last_page():
    got = page("open", "?page=9")
    assert got["current"] == "3" and got["range"] == "Showing 51–60 of 60"
    assert got["url"] == "/project-calendar.html?page=3"


def test_back_from_a_jobs_detail_returns_to_the_same_page_and_filters():
    got = page("detail", "?work_type=Polish&page=2")
    assert got["detail_open"] is True and got["url_in_detail"] == got["url"]
    assert got["url"] == "/project-calendar.html?work_type=Polish&page=2"
    assert got["current"] == "2" and got["first"] == "26.752"
    assert got["focus"] == "row:job:26.752"


def test_the_download_carries_the_filters_on_screen():
    got = page("download", "?q=example&work_type=Polish&foreman=Lee&page=2&per=50")
    assert got["fetched"] == BASE + "?q=example&work_type=Polish&foreman=Lee"


def test_the_no_match_message_names_the_filters():
    got = page("open", "?work_type=Gyp&foreman=(none)")
    assert got["rows"] == 0 and got["empty"] == "No job matches the filters: Gyp, No foreman."
    assert got["pager_hidden"] is True and got["count"] == "0 of 60 jobs"


# ── markup and layout ───────────────────────────────────────────────────────────────────────────
def test_the_filters_wrap_and_the_pager_stays_usable_at_phone_width():
    html = PAGE.read_text(encoding="utf-8")
    assert re.search(r"\.pva-filters\s*\{[^}]*flex-wrap:\s*wrap", html)
    assert re.search(r"\.pva-pager\s*\{[^}]*flex-wrap:\s*wrap", html)
    phone = html[html.index("@media (max-width:767px)"):]
    phone = phone[:phone.index("\n    }\n")]
    assert re.search(r"\.pva-f\s*\{[^}]*flex:\s*1 1", phone), "each filter takes a share of the row"
    assert re.search(r"\.tw-select\s*\{[^}]*width:\s*100%", phone)
    assert re.search(r"\.tw-select\s*\{[^}]*max-width", html), "a long Foreman never widens the page"


def test_the_new_controls_escape_their_text_and_set_no_style_attribute():
    js = PVA.read_text(encoding="utf-8")
    assert 'style="' not in js and "style='" not in js
    i = js.index("function optionsHtml(")
    body = js[i:js.index("\n  }\n", i)]
    assert "esc(o.value)" in body and "esc(o.label)" in body
    i = js.index("function pagerHtml(")
    body = js[i:js.index("\n  }\n", i)]
    assert "esc(" in body
    # The search box no longer keeps its own copy in sessionStorage: the address holds the view.
    assert "tw_pva_q" not in js
