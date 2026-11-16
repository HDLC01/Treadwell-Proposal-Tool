"""The Project Calendar's layout and workday arithmetic, exercised under node.

frontend/js/project-calendar-core.js is pure: it lays the crews' Google events out across the
visible weeks, stacks overlapping ones into lanes, counts workdays (Monday to Friday) and decides
whether a Deadline has passed. Every wrong answer here looks plausible on screen, a bar one column
short or a "3 workdays left" that counted a Saturday, so each rule is pinned.

Run exactly like test_calendar_core_js.py runs calendar-core.js. The fixtures are MADE-UP project
and person names in the same shapes the real titles use; this repo is public.

Skipped when node isn't installed; it's on the dev box and in the Docker image.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
CORE = FRONTEND / "js" / "project-calendar-core.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                               reason="node is not installed")


def run(script: str):
    """Run `script` with `P` bound to the module (and `K` to calendar-core); returns its printed
    JSON. Non-ASCII is escaped before printing for the same reason as test_calendar_core_js.py:
    node on Windows writes stdout in the console code page."""
    prelude = (
        "const P = require(%s);\n"
        "const K = require(%s);\n"
        "const out = (v) => console.log(JSON.stringify(v).replace(\n"
        "  /[\\u0080-\\uffff]/g,\n"
        "  (c) => '\\\\u' + c.charCodeAt(0).toString(16).padStart(4, '0')));\n"
        % (json.dumps(str(CORE)), json.dumps(str(FRONTEND / "js" / "calendar-core.js")))
    )
    proc = subprocess.run(["node", "-e", prelude + script],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# A fortnight of made-up events in the API's shape. 2026-11-08 is a Sunday.
EVENTS = """
const ev = (o) => Object.assign({id:"x", title:"", name:"", job_number:null, crew_size:null,
  mobilization:null, foreman:null, is_punch:false, prevailing_wage:false, night_work:false,
  color_id:null, color:null, work_type:null, start:"", last_day:"", workdays:0,
  deadline:null, project:null, html_link:null}, o);
const EVENTS = [
  ev({id:"a", title:"26.125, Acme Clinic Psych (6) (Pat)", name:"Acme Clinic Psych",
      job_number:"26.125", crew_size:6, foreman:"Pat", color_id:"11", color:"#d50000",
      start:"2026-11-10", last_day:"2026-11-19", deadline:"2026-11-19"}),
  ev({id:"b", title:"Example Diner (4)", name:"Example Diner", crew_size:4, color_id:"7",
      color:"#039be5", start:"2026-11-11", last_day:"2026-11-12"}),
  ev({id:"c", title:"Example Punch - (1) (Lee)", name:"Example Punch", crew_size:1,
      foreman:"Lee", is_punch:true, start:"2026-11-13", last_day:"2026-11-13"}),
  ev({id:"d", title:"G25.110, The Example Lofts (3rd and 2nd) - 2nd Mob - (PW) (8) (Sam)",
      name:"The Example Lofts (3rd and 2nd)", job_number:"G25.110", crew_size:8,
      mobilization:2, foreman:"Sam", prevailing_wage:true, color_id:"2", color:"#33b679",
      start:"2026-11-05", last_day:"2026-11-09"}),
];
const range = K.rangeFor("2026-11-10", "two");
"""


def test_the_module_loads_and_finds_the_bid_calendar_engine():
    """A syntax error, or calendar-core.js not being found beside it, would fail every test below
    with the same opaque message."""
    assert run("out([typeof P.layout, typeof P.workdaysLeft, P.MODES.map(m => m.id)])") == [
        "function", "function", ["two", "month"]]


def test_the_page_offers_only_views_calendar_core_can_draw():
    """Both ids must be calendar-core modes, or rangeFor silently falls back to a fortnight."""
    assert run("out(P.MODES.map(m => K.modeOf(m.id).id))") == ["two", "month"]


# ── today is Central, not the machine's ─────────────────────────────────
def test_today_is_the_central_date_not_the_utc_or_local_one():
    """The dev box runs about thirteen hours ahead of Central. At 03:30 UTC on Nov 13 it is still
    the evening of Nov 12 in Chicago."""
    got = run('out([P.centralToday(new Date("2026-11-13T03:30:00Z")),'
              ' P.centralToday(new Date("2026-11-13T06:30:00Z")),'
              ' P.centralToday(new Date("2026-07-01T04:59:00Z"))])')
    assert got == ["2026-11-12", "2026-11-13", "2026-06-30"]


def test_the_page_never_reads_a_naive_local_date():
    """The page script must take today from the core's Central clock, never from getDate()."""
    js = (FRONTEND / "js" / "project-calendar.js").read_text(encoding="utf-8")
    assert "P.centralToday()" in js
    for naive in ("getDate()", "getFullYear()", "toISOString().slice(0, 10)"):
        assert naive not in js, "the page derives a date from the local clock: %s" % naive


# ── workdays ────────────────────────────────────────────────────────────
def test_workdays_count_monday_to_friday_only():
    got = run('out([P.workdaysBetween("2026-11-09","2026-11-13"),'   # Mon-Fri
              ' P.workdaysBetween("2026-11-07","2026-11-08"),'       # Sat-Sun
              ' P.workdaysBetween("2026-11-06","2026-11-09"),'       # Fri-Mon
              ' P.workdaysBetween("2026-11-01","2026-11-30"),'       # November 2026
              ' P.workdaysBetween("2026-11-10","2026-11-10"),'       # one Tuesday
              ' P.workdaysBetween("2026-11-14","2026-11-14")])')     # one Saturday
    assert got == [5, 0, 2, 21, 1, 0]


def test_workdays_are_never_negative_and_survive_bad_input():
    got = run('out([P.workdaysBetween("2026-11-13","2026-11-09"),'
              ' P.workdaysBetween("","2026-11-09"), P.workdaysBetween("2026-02-31","2026-03-05"),'
              ' P.workdaysBetween(null, undefined)])')
    assert got == [0, 0, 0, 0]


def test_a_long_span_counts_the_same_as_walking_it_day_by_day():
    """The fast whole-weeks path must agree with the obvious walk, for every start weekday."""
    got = run('const walk = (a,b) => { let n=0; for (let d=a; K.diffDays(d,b)>=0; d=K.addDays(d,1))'
              ' { const w=K.dow(d); if (w>=1&&w<=5) n++; } return n; };'
              'let bad = [];'
              'for (let s=0; s<7; s++) for (let len=0; len<60; len++) {'
              '  const a = K.addDays("2026-11-01", s), b = K.addDays(a, len);'
              '  if (walk(a,b) !== P.workdaysBetween(a,b)) bad.push([a,b]); }'
              'out(bad)')
    assert got == []


def test_a_workday_count_across_a_dst_change_is_unaffected():
    """US DST ends 2026-11-01. Mon Oct 26 to Fri Nov 6 is ten workdays either way."""
    assert run('out(P.workdaysBetween("2026-10-26","2026-11-06"))') == 10


def test_workdays_left_counts_from_today_and_never_goes_negative():
    """Acme runs Tue Nov 10 to Thu Nov 19: eight workdays."""
    got = run(EVENTS + 'const a = EVENTS[0];'
              'out([P.workdaysOf(a),'
              ' P.workdaysLeft(a, "2026-11-02"),'   # before it starts: all of it
              ' P.workdaysLeft(a, "2026-11-10"),'   # its first day counts
              ' P.workdaysLeft(a, "2026-11-14"),'   # a Saturday in the middle
              ' P.workdaysLeft(a, "2026-11-19"),'   # the Deadline itself
              ' P.workdaysLeft(a, "2026-11-20"),'   # the day after: 0, not -1
              ' P.workdaysLeft(a, "2027-01-04")])')
    assert got == [8, 8, 8, 4, 1, 0, 0]


def test_an_event_with_a_bad_last_day_is_read_as_one_day_not_dropped():
    got = run('out([P.spanOf({start:"2026-11-10", last_day:"2026-11-08"}),'
              ' P.spanOf({start:"2026-11-10", last_day:"garbage"}),'
              ' P.spanOf({start:"", last_day:"2026-11-10"}), P.spanOf(null)])')
    assert got == [{"start": "2026-11-10", "last": "2026-11-10"},
                   {"start": "2026-11-10", "last": "2026-11-10"}, None, None]


# ── Deadlines ───────────────────────────────────────────────────────────
def test_a_deadline_is_overdue_today_or_upcoming():
    got = run('out([P.deadlineStatus("2026-11-11","2026-11-12"),'
              ' P.deadlineStatus("2026-11-12","2026-11-12"),'
              ' P.deadlineStatus("2026-11-13","2026-11-12"),'
              ' P.deadlineStatus(null,"2026-11-12"), P.deadlineStatus("2026-11-12","")])')
    assert got == ["overdue", "today", "upcoming", None, None]


# ── colour ──────────────────────────────────────────────────────────────
def test_colour_comes_from_the_api_then_googles_palette_then_nothing():
    got = run('out([P.colorOf({color:"#D50000"}), P.colorOf({color_id:"5"}),'
              ' P.colorOf({color_id:11}), P.colorOf({}), P.colorOf({color_id:"99"}),'
              ' P.colorOf({color:"red; background:url(x)"})])')
    assert got == ["#d50000", "#f6bf26", "#d50000", None, None, None]


def test_text_on_a_bar_stays_readable():
    """White on Tomato and on dark blue; dark ink on Google's yellow."""
    got = run('out([P.textOn("#d50000"), P.textOn("#3f51b5"), P.textOn("#f6bf26"),'
              ' P.textOn("nope")])')
    assert got == ["#ffffff", "#ffffff", "#1b1c1c", None]


# ── what a bar says ─────────────────────────────────────────────────────
def test_a_bar_reads_name_then_job_number_crew_size_and_foreman():
    got = run(EVENTS + 'out([P.barParts(EVENTS[0]), P.barParts(EVENTS[1]),'
              ' P.barParts({title:"Example Patch?"}), P.barParts({})])')
    assert got == [{"name": "Acme Clinic Psych", "meta": "26.125 · 6 crew · Pat"},
                   {"name": "Example Diner", "meta": "4 crew"},
                   {"name": "Example Patch?", "meta": ""},
                   {"name": "Untitled", "meta": ""}]


def test_flags_are_named_in_plain_words():
    got = run(EVENTS + 'out([P.flagsOf(EVENTS[0]), P.flagsOf(EVENTS[2]), P.flagsOf(EVENTS[3]),'
              ' P.flagsOf(ev({night_work:true, mobilization:1})), P.ordinal(3), P.ordinal(11)])')
    assert got == [[], ["Punch"], ["2nd Mobilization", "Prevailing wage"],
                   ["1st Mobilization", "Night work"], "3rd", "11th"]


# ── filtering ───────────────────────────────────────────────────────────
def test_search_matches_title_name_job_number_and_foreman_case_blind():
    got = run(EVENTS + 'const ids = (o) => P.filterEvents(EVENTS, o).map(e => e.id);'
              'out([ids({q:"acme"}), ids({q:"G25.110"}), ids({q:"lee"}), ids({q:"pw"}),'
              ' ids({q:"example lofts"}), ids({q:"lofts diner"}), ids({q:"   "}), ids({})])')
    assert got == [["a"], ["d"], ["c"], ["d"], ["d"], [], ["a", "b", "c", "d"], ["a", "b", "c", "d"]]


def test_filtering_never_throws_on_odd_input():
    got = run(EVENTS + 'out([P.filterEvents(null,{}).length, P.filterEvents([null, 3, EVENTS[1]],{}).length,'
              ' P.filterEvents(EVENTS,{q:"diner"}).map(e => e.id)])')
    assert got == [0, 1, ["b"]]


def test_search_can_find_the_matched_project_by_name():
    got = run(EVENTS + 'const e = ev({id:"p", title:"26.200, Example Shop (3) Night Work",'
              ' name:"Example Shop", project:{id:"d-1", name:"Example Shop Remodel"}});'
              'out(P.filterEvents([e],{q:"remodel"}).length)')
    assert got == 1


# ── layout ──────────────────────────────────────────────────────────────
def test_a_multi_week_mobilization_spans_its_columns_and_wraps():
    """Acme runs Tue Nov 10 to Thu Nov 19: Tue-Sat in week one (cols 2-6), then Sun-Thu in week
    two (cols 0-4). It is one event drawn as two segments, not ten day cards."""
    got = run(EVENTS + 'const L = P.layout(EVENTS, range);'
              'const segs = L.weeks.map(w => w.segments.filter(s => s.ev.id === "a")'
              '  .map(s => [s.col, s.span, s.starts, s.ends]));'
              'out([L.weeks.length, segs])')
    assert got == [2, [[[2, 5, True, False]], [[0, 5, False, True]]]]


def test_an_event_that_started_before_the_range_is_clipped_not_dropped():
    """The Example Lofts runs Thu Nov 5 to Mon Nov 9; the range opens Sun Nov 8."""
    got = run(EVENTS + 'const s = P.layout(EVENTS, range).weeks[0].segments.find(s => s.ev.id === "d");'
              'out([s.col, s.span, s.starts, s.ends])')
    assert got == [0, 2, False, True]


def test_an_event_outside_the_range_is_not_drawn():
    got = run(EVENTS + 'const far = ev({id:"z", start:"2026-12-01", last_day:"2026-12-03"});'
              'const L = P.layout(EVENTS.concat([far]), range);'
              'out(L.weeks.flatMap(w => w.segments).filter(s => s.ev.id === "z").length)')
    assert got == 0


def test_overlapping_bars_get_their_own_lanes_and_never_collide():
    got = run(EVENTS + 'const L = P.layout(EVENTS, range);'
              'const clash = L.weeks.some(w => w.segments.some((a, i) => w.segments.some((b, j) =>'
              '  i < j && a.lane === b.lane && a.col <= b.col + b.span - 1 && b.col <= a.col + a.span - 1)));'
              'const w0 = L.weeks[0];'
              'out([clash, w0.lanes, w0.segments.map(s => [s.ev.id, s.lane])])')
    clash, lanes, placed = got
    assert clash is False
    # Week one: Lofts (cols 0-1), Acme (2-6), Diner (3-4), Punch (5). Lofts and Acme share lane 0;
    # Diner overlaps Acme, so lane 1; Punch fits beside Diner in lane 1.
    assert dict(placed) == {"d": 0, "a": 0, "b": 1, "c": 1}
    assert lanes == 2


def test_a_wrapped_event_keeps_the_top_lane_in_the_next_week():
    """Carried-over events start in column 0, so they are packed first and stay near the top."""
    got = run(EVENTS + 'const extra = ev({id:"n", title:"Example Shop (3)", start:"2026-11-15",'
              ' last_day:"2026-11-15"});'
              'const w1 = P.layout(EVENTS.concat([extra]), range).weeks[1];'
              'out(w1.segments.map(s => [s.ev.id, s.lane]))')
    assert dict(got)["a"] == 0


def test_month_view_lays_out_six_whole_weeks():
    got = run(EVENTS + 'const m = K.rangeFor("2026-11-12","month");'
              'const L = P.layout(EVENTS, m);'
              'out([L.weeks.length, L.weeks.every(w => w.days.length === 7),'
              ' L.weeks.flatMap(w => w.segments).filter(s => s.ev.id === "a").length])')
    assert got == [5, True, 2]


def test_layout_never_throws_and_counts_what_it_could_not_place():
    got = run('const r = K.rangeFor("2026-11-10","two");'
              'out([P.layout(null, r).weeks.length, P.layout([], r).unplaced,'
              ' P.layout([{id:"q", title:"Example Patch?"}, null, {start:"2026-11-10"}], r).unplaced,'
              ' P.layout([{start:"2026-11-10"}], {}).weeks.length])')
    assert got == [2, 0, 1, 0]


def test_layout_does_not_depend_on_input_order():
    got = run(EVENTS + 'const a = P.layout(EVENTS, range), b = P.layout(EVENTS.slice().reverse(), range);'
              'const sig = (L) => L.weeks.map(w => w.segments.map(s => [s.ev.id, s.col, s.span, s.lane]));'
              'out(JSON.stringify(sig(a)) === JSON.stringify(sig(b)))')
    assert got is True


def test_events_seen_twice_collapse_to_one():
    got = run('out(P.uniqueById([{id:"a"},{id:"b"},{id:"a"},{},{}]).length)')
    assert got == 4


# ── labels ──────────────────────────────────────────────────────────────
def test_labels_are_central_and_human():
    got = run('out([P.dayLong("2026-11-12"), P.spanLabel({start:"2026-11-10", last_day:"2026-11-19"}),'
              ' P.spanLabel({start:"2026-12-30", last_day:"2027-01-04"}),'
              ' P.spanLabel({start:"2026-11-12", last_day:"2026-11-12"}),'
              ' P.centralStamp("2026-11-13T03:04:00Z"), P.centralStamp("nope")])')
    assert got == ["Thu, Nov 12, 2026",
                   "Tue, Nov 10 – Thu, Nov 19, 2026",
                   "Wed, Dec 30, 2026 – Mon, Jan 4, 2027",
                   "Thu, Nov 12, 2026",
                   "Nov 12, 9:04 PM", ""]


# ── the page itself: structural pins ────────────────────────────────────
def _page():
    return (FRONTEND / "project-calendar.html").read_text(encoding="utf-8")


def _page_js():
    return (FRONTEND / "js" / "project-calendar.js").read_text(encoding="utf-8")


def test_the_page_loads_the_bid_calendar_engine_before_its_own():
    html = _page()
    i, j, k = (html.index(s) for s in ('src="/js/calendar-core.js"',
                                        'src="/js/project-calendar-core.js"',
                                        'src="/js/project-calendar.js"'))
    assert i < j < k


def test_the_page_is_read_only():
    """No write verb, and no create, edit or delete control, anywhere on the page."""
    js, html = _page_js(), _page()
    for verb in ('"POST"', '"PATCH"', '"PUT"', '"DELETE"', "method:"):
        assert verb not in js, "the read-only page sends a write: %s" % verb
    for word in ("draggable", "contenteditable", "+ Add", ">Delete<", ">Save<", ">Edit<"):
        assert word not in html and word not in js, "a write control appeared: %s" % word
    assert "/api/project-calendar?start=" in js


def test_every_api_value_is_escaped_before_it_reaches_markup():
    """Titles are typed by hand in Google. Each place a free-text field enters an HTML string
    must pass through esc()."""
    js = _page_js()
    fields = ("parts.name", "parts.meta", "ev.job_number", "ev.foreman", "P.workTypeOf(ev)",
              "ev.project.name")
    for field in fields:
        for m in re.finditer(re.escape(field), js):
            line = js[js.rfind("\n", 0, m.start()) + 1: js.find("\n", m.end())]
            if "innerHTML" in line or "'<" in line or '"<' in line:
                assert "esc(" in line or "textContent" in line, (
                    "%s reaches markup unescaped: %s" % (field, line.strip()))


def test_colours_and_positions_go_through_the_cssom_not_inline_style_attributes():
    """The nginx CSP is not widened for this page: no style="..." is ever written into markup."""
    js = _page_js()
    assert 'style="' not in js and "style='" not in js
    assert ".style.gridColumn" in js and ".style.background" in js


def test_the_google_link_must_be_https():
    js = _page_js()
    assert "safeLink(ev.html_link)" in js
    assert 'target="_blank" rel="noopener noreferrer"' in js


def test_the_sidebar_row_sits_right_after_the_bid_calendar():
    src = (FRONTEND / "auth.js").read_text(encoding="utf-8")
    bid = src.index('navItem("/calendar.html"')
    proj = src.index('navItem("/project-calendar.html"')
    assert proj > bid
    between = src[bid:proj]
    assert between.count("navItem(") == 1, "something sits between the two calendars"
    assert re.search(r'navItem\("/project-calendar\.html",\s*"[^"]+",\s*"Project Analytics"\)', src)


def test_the_not_connected_state_is_a_plain_message_not_an_error():
    js = _page_js()
    i = js.index("current.connected === false")
    block = js[i:i + 500]
    assert "not connected yet" in block
    assert "alert" not in block.replace('showAlert("")', ""), "the not-connected state is styled as an error"


def test_the_stale_notice_names_the_time_in_central():
    js = _page_js()
    assert "Showing the last copy from " in js
    assert "P.centralStamp(current.fetched_at)" in js


# ── review fixes ─────────────────────────────────────────────────────────────
def test_switching_view_length_keeps_the_days_being_looked_at():
    """Paged forward in two weeks to a mostly-February range, Month must show February."""
    got = run('out([P.focusDay({from:"2027-01-31", to:"2027-02-13"}, "2026-11-12"),'
              '     P.focusDay({from:"2026-11-08", to:"2026-11-21"}, "2026-11-12"),'
              '     P.focusDay({from:"2026-11-01", to:"2026-12-12"}, "2026-12-20")])')
    assert got == ["2027-02-06", "2026-11-12", "2026-11-21"]


def test_the_servers_message_reaches_the_screen_when_there_are_bars():
    """A free/busy-only calendar, or a stale copy after the Google sign-in was revoked, comes with
    bars AND a message saying what to fix. With no bars the state box shows it; with bars the
    alert line must, as text, never markup."""
    js = _page_js()
    assert "if (current.error && events.length) notice.push(String(current.error));" in js
    assert "showAlert(notice.join(\" \"));" in js
    assert '$("alert").textContent = text' in js
    assert "if (!events.length && current.error)" in js


def test_a_notice_rides_beside_the_grid_and_never_reads_as_a_failed_read():
    """A free/busy-only read that worked comes back with `notice`, not `error`. An empty month read
    that way must draw its empty weeks with the notice in the alert line, not the "Couldn't read
    the calendar" box."""
    js = _page_js()
    assert "if (current.notice) notice.push(String(current.notice));" in js
    i = js.index("if (!events.length && current.error)")
    assert "notice" not in js[i:js.index("\n", i)], "the failure box keys on a notice"
    assert "cached.notice" in js, "a changed notice must repaint"


# ── #778: every bar is a Duration, colour is the Work type, the name is Foreman ───────────────────
def test_the_page_shows_the_servers_work_type_and_unknown_when_there_is_none():
    """Which colour is which Work type is the server's alone; the page never works it out again
    (docs/v2-architecture.md section 5, rule 1). A colour with no Work type arrives as null."""
    got = run(EVENTS + 'out([ev({work_type:"Epoxy"}), ev({work_type:"Gyp"}), ev({color_id:"11"}),'
              ' ev({}), ev({work_type:null})].map(e => P.workTypeOf(e)))')
    assert got == ["Epoxy", "Gyp", "Work type unknown", "Work type unknown", "Work type unknown"]


def test_the_legend_is_drawn_from_the_servers_list_not_a_copy():
    js = _page_js()
    assert "WORK_TYPES.map(" in js and "res.body.work_types" in js
    core = (FRONTEND / "js" / "project-calendar-core.js").read_text(encoding="utf-8")
    assert "WORK_TYPE_BY_COLOR" not in core and "WORK_TYPE_BY_COLOR" not in js


def test_a_bar_names_the_foreman_and_search_finds_the_foreman():
    got = run(EVENTS + 'const f = ev({id:"f", name:"Example Hall", foreman:"Rosa", crew_size:3});'
              'out([P.barParts(f).meta.indexOf("Rosa") >= 0,'
              '     P.filterEvents([f], {q: "rosa"}).length])')
    assert got == [True, 1]


def test_the_page_says_foreman_and_never_crew_lead():
    js, page = _page_js(), (FRONTEND / "project-calendar.html").read_text(encoding="utf-8")
    assert 'fact("Foreman"' in js
    for text in (js, page):
        assert "Crew lead" not in text and "crew_lead" not in text


# ── #780: two tabs, Plan vs Actual first; the Schedule loses its side list ──────────────────────
PVA = FRONTEND / "js" / "plan-vs-actual.js"

# Rows in the shape GET /api/project-analytics sends them. Made-up jobs and people.
PROJECTS = """
const pr = (o) => Object.assign({key:"", job_number:null, name:"", is_punch:false, label:null,
  work_type:null, color:null, foreman:null, start:"2026-11-16", deadline:"2026-11-20",
  timing:"running", workdays_left:3, workdays_so_far:2, crew_size:4, planned_hours:64,
  crew_size_missing:false, mobilizations:[], punches:[], raken:{state:"not_connected"}}, o);
const PROJECTS = [
  pr({key:"job:26.125", job_number:"26.125", name:"Acme Clinic Psych", work_type:"Epoxy",
      foreman:"Pat"}),
  pr({key:"job:G25.110", job_number:"G25.110", name:"The Example Lofts", work_type:"Polish",
      foreman:"Sam"}),
  pr({key:"name:examplediner", name:"Example Diner", foreman:"Lee"}),
  pr({key:"punch:name:exampleshoppunch", name:"Example Shop Punch", is_punch:true, label:"Punch",
      work_type:"Gyp", foreman:null}),
];
"""


def _pva_js():
    return PVA.read_text(encoding="utf-8")


def test_the_page_opens_on_plan_vs_actual_unless_the_address_asks_for_the_schedule():
    got = run('out([P.TABS.map(t => [t.id, t.label]), P.tabFromHash(""), P.tabFromHash("#schedule"),'
              ' P.tabFromHash("#Schedule"), P.tabFromHash("#plan"), P.tabFromHash(null),'
              ' P.tabFromHash("#nonsense")])')
    assert got == [[["pva", "Plan vs Actual"], ["schedule", "Schedule"]],
                   "pva", "schedule", "schedule", "pva", "pva", "pva"]


def test_search_filters_the_list_by_job_number_name_foreman_or_work_type():
    got = run(PROJECTS + 'const keys = (q) => P.filterProjects(PROJECTS, q).map(p => p.key);'
              'out([keys("26.125"), keys("g25"), keys("lofts"), keys("LEE"), keys("epoxy"),'
              ' keys("gyp"), keys("unknown"), keys("acme pat"), keys("acme sam"), keys(""),'
              ' keys("  ")])')
    every = ["job:26.125", "job:G25.110", "name:examplediner", "punch:name:exampleshoppunch"]
    assert got == [["job:26.125"], ["job:G25.110"], ["job:G25.110"], ["name:examplediner"],
                   ["job:26.125"], ["punch:name:exampleshoppunch"], ["name:examplediner"],
                   ["job:26.125"], [], every, every]


def test_filtering_projects_never_throws_on_odd_input():
    got = run(PROJECTS + 'out([P.filterProjects(null, "x").length,'
              ' P.filterProjects([null, 4, PROJECTS[0]], "").length,'
              ' P.filterProjects([{key:"zz"}], "zz").length])')
    assert got == [0, 1, 0]


def test_workdays_left_read_as_starts_a_count_or_finished():
    got = run(PROJECTS + 'out([P.leftLabel(pr({timing:"starts", start:"2026-11-23", workdays_left:null})),'
              ' P.leftLabel(pr({timing:"running", workdays_left:3})),'
              ' P.leftLabel(pr({timing:"running", workdays_left:1})),'
              ' P.leftLabel(pr({timing:"finished", workdays_left:null})), P.leftLabel(null)])')
    assert got == ["Starts Mon, Nov 23, 2026", "3 workdays left", "1 workday left", "Finished", ""]


def test_hours_and_counts_read_as_whole_numbers_or_a_dash():
    got = run('out([P.numLabel(1136), P.numLabel(0), P.numLabel(null), P.numLabel("x"),'
              ' P.numLabel(12.6)])')
    assert got == ["1,136", "0", "\u2014", "\u2014", "13"]


def test_the_raken_side_says_why_it_has_no_numbers():
    got = run(PROJECTS + 'out([P.rakenLabel(PROJECTS[0]), P.rakenLabel(pr({raken:null})),'
              ' P.rakenLabel(pr({raken:{state:"linked"}})),'
              ' P.rakenLabel(pr({raken:{state:"expired"}})),'
              ' P.rakenLabel(pr({raken:{state:"not_provisioned"}})),'
              ' P.rakenLabel(pr({raken:{state:"unreachable"}})),'
              ' P.rakenLabel(pr({raken:{state:"not_refreshed"}})),'
              ' P.rakenLabel(pr({raken:{state:"made-up"}}))])')
    assert got == ["Connect Raken to compare", "Connect Raken to compare", "",
                   "Raken sign-in expired", "Raken not turned on yet", "Raken not reached",
                   "Press Refresh now", "\u2014"]


def test_the_footer_and_the_empty_list_word_the_servers_numbers():
    """Planned hours' "x 8" and the window's "14 days" come from the response, so changing either
    on the server can never leave the page's wording wrong."""
    got = run('const d = {so_far_through:"2026-11-17", hours_per_workday:8, window_days:14};'
              'const e = {so_far_through:"2026-11-17", hours_per_workday:10, window_days:21};'
              'out([P.pvaFootText(d), P.pvaEmptyText(d), P.pvaFootText(e), P.pvaEmptyText(e),'
              ' P.pvaFootText({}), P.pvaEmptyText(null)])')
    assert got == [
        "Counts so far run through yesterday, Tue, Nov 17, 2026. Planned hours = Workdays so far"
        " × Crew size × 8. Days clocked in, On site and Actual hours come from Raken time cards.",
        "No jobs are running, finished in the last 14 days, or starting in the next 14 days.",
        "Counts so far run through yesterday, Tue, Nov 17, 2026. Planned hours = Workdays so far"
        " × Crew size × 10. Days clocked in, On site and Actual hours come from Raken time cards.",
        "No jobs are running, finished in the last 21 days, or starting in the next 21 days.",
        "Planned hours = Workdays so far × Crew size × the hours in a workday."
        " Days clocked in, On site and Actual hours come from Raken time cards.",
        "No jobs are running, finished lately, or starting soon.",
    ]
    js = _pva_js()
    assert "P.pvaFootText(DATA)" in js and "P.pvaEmptyText(DATA)" in js
    assert "× 8" not in js and "14 days" not in js


def test_the_page_and_the_server_name_the_same_timing_and_raken_states():
    """A row's timing and its Raken state are a contract between plan_vs_actual.py and the page.
    Each side names them once; a state added on one side only fails here."""
    import plan_vs_actual as pva
    got = run("out([P.TIMING, P.RAKEN_NOT_CONNECTED])")
    assert got == [{"starts": pva.TIMING_STARTS, "running": pva.TIMING_RUNNING,
                    "finished": pva.TIMING_FINISHED}, pva.RAKEN_NOT_CONNECTED]
    assert sorted(got[0].values()) == sorted(pva.TIMINGS)
    core = CORE.read_text(encoding="utf-8")
    i = core.index("function leftLabel(")
    j = core.index("function rakenLabel(")
    assert '"starts"' not in core[i:j] and '"finished"' not in core[i:j]
    assert '"not_connected"' not in core[j:core.index("}", j)]


def test_the_page_and_the_server_name_the_same_raken_states_and_statuses():
    """A row's Raken state and its statuses are raken_actuals.py's; the page names each once."""
    import raken_actuals as ra
    got = run("out([P.RAKEN, P.STATUS])")
    assert sorted(got[0].values()) == sorted(ra.ROW_STATES)
    assert all(k == v for k, v in got[0].items())
    assert sorted(got[1].values()) == sorted(ra.STATUSES)
    assert got[0]["not_connected"] == ra.STATE_NOT_CONNECTED
    assert got[0]["linked"] == ra.STATE_LINKED and got[0]["not_linked"] == ra.STATE_NOT_LINKED
    assert got[1]["behind"] == ra.STATUS_BEHIND and got[1]["not_linked"] == ra.STATUS_NOT_LINKED


def test_the_column_headings_use_the_glossary_words():
    """GLOSSARY.md: Workday, Planned hours, Crew size ("people", never "men" or "guys")."""
    html = _page()
    head = html[html.index('<table class="pva">'):html.index("</thead>")]
    assert "Workdays<small>booked so far</small>" in head
    assert "Planned hours<small>so far</small>" in head
    assert "Crew size<small>planned</small>" in head
    assert "Days clocked in<small>Raken</small>" in head
    assert "On site<small>average a day</small>" in head
    assert "Actual hours<small>so far</small>" in head
    assert ">Status<" in head
    for word in ("men", "guys", "Days<small>", "Hours so far"):
        assert not re.search(r"(?<![A-Za-z])%s(?![A-Za-z])" % re.escape(word), head), word


def test_the_side_list_of_upcoming_deadlines_is_gone():
    js, page = _page_js(), _page()
    core = CORE.read_text(encoding="utf-8")
    for text in (js, page, core):
        assert "Upcoming Deadlines" not in text and "upcomingDeadlines" not in text
        assert "SIDE_DAYS" not in text and "side-body" not in text


def test_the_page_has_two_tabs_with_plan_vs_actual_selected_and_the_schedule_hidden():
    html = _page()
    pva = html.index('id="tab-pva"')
    sched = html.index('id="tab-schedule"')
    assert pva < sched, "Plan vs Actual comes first"
    assert 'role="tablist"' in html
    tab_pva = html[html.rfind("<button", 0, pva):html.index(">", pva)]
    tab_sched = html[html.rfind("<button", 0, sched):html.index(">", sched)]
    assert 'aria-selected="true"' in tab_pva and 'aria-selected="false"' in tab_sched
    panel = html[html.index('id="panel-schedule"') - 80:html.index('id="panel-schedule"') + 120]
    assert "hidden" in panel, "the Schedule panel starts hidden"
    # The calendar moved behind the Schedule tab, with its toolbar and details panel.
    i, j = html.index('id="panel-schedule"'), html.index('id="grid"')
    assert i < html.index('id="toolbar"') < j


def test_the_plan_vs_actual_script_loads_after_the_core_and_its_one_write_is_refresh_now():
    """Plan vs Actual reads only, with one exception: "Refresh now" (#782) POSTs to
    /api/project-analytics/refresh, which reads Raken and keeps the result. Nothing else on the
    page writes, and that POST changes nothing in Google Calendar or Raken."""
    html, js = _page(), _pva_js()
    assert html.index('src="/js/project-calendar-core.js"') < html.index('src="/js/plan-vs-actual.js"')
    for verb in ('"PATCH"', '"PUT"', '"DELETE"'):
        assert verb not in js, "the read-only page sends a write: %s" % verb
    assert js.count("method:") == 1 and js.count('"POST"') == 1
    i = js.index('method: "POST"')
    assert '"/api/project-analytics/refresh"' in js[i - 200:i], "the one POST is Refresh now"
    assert '"/api/project-analytics"' in js
    assert ">Refresh now<" in html


def test_plan_vs_actual_escapes_every_value_and_styles_through_the_cssom():
    js = _pva_js()
    assert 'style="' not in js and "style='" not in js
    assert ".style.background" in js
    for field in ("p.name", "p.job_number", "p.foreman", "P.workTypeOf(p)", "P.leftLabel(p)",
                  "P.rakenLabel(p)", "why", "p.label", "c.label", "x.number",
                  "P.rakenOnlyName(x)", "P.decLabel("):
        hits = list(re.finditer(re.escape(field), js))
        assert hits, field
        for m in hits:
            line = js[js.rfind("\n", 0, m.start()) + 1: js.find("\n", m.end())]
            if "innerHTML" in line or "'<" in line or '"<' in line:
                assert "esc(" in line or "textContent" in line, (
                    "%s reaches markup unescaped: %s" % (field, line.strip()))


def test_plan_vs_actual_reads_today_from_the_server_never_the_local_clock():
    js = _pva_js()
    for naive in ("getDate()", "getFullYear()", "toISOString().slice(0, 10)", "new Date()"):
        assert naive not in js, naive


def test_the_list_scrolls_sideways_inside_its_card_at_phone_width():
    html = _page()
    assert 'class="pva-scroll"' in html
    assert re.search(r"\.pva-scroll\s*\{[^}]*overflow-x:\s*auto", html)


def test_the_schedule_arrow_keys_only_page_the_calendar_when_it_is_shown():
    js = _page_js()
    i = js.index('document.addEventListener("keydown"')
    assert 'panel-schedule").hidden' in js[i:i + 400]


# ── #782: the Raken side ─────────────────────────────────────────────────────────────────────────
LINKED = """
const linked = (o) => pr({raken: Object.assign({state:"linked", projects:[], days_booked:5,
  days_clocked:4, avg_on_site:3.5, actual_hours:131.5, through:"2026-11-17"}, o || {}),
  statuses: []});
"""


def test_a_linked_row_shows_days_clocked_people_on_site_and_actual_hours():
    got = run(PROJECTS + LINKED + 'const c = (p) => P.rakenCells(p);'
              'out([c(linked()), c(linked({avg_on_site:null, days_clocked:0, actual_hours:0})),'
              ' c(linked({actual_hours:1136})), c(PROJECTS[0]),'
              ' c(pr({raken:{state:"not_linked", reason:"no_job_number"}})), c(null)])')
    dash = "\u2014"
    assert got == [
        {"days": "4", "on_site": "3.5", "hours": "131.5"},
        {"days": "0", "on_site": dash, "hours": "0"},
        {"days": "4", "on_site": "3.5", "hours": "1,136"},
        {"days": dash, "on_site": dash, "hours": dash},
        {"days": dash, "on_site": dash, "hours": dash},
        {"days": dash, "on_site": dash, "hours": dash},
    ]


def test_hours_and_averages_keep_one_decimal_only_when_they_need_it():
    got = run('out([P.decLabel(38.5), P.decLabel(40), P.decLabel(2.333), P.decLabel(1136.25),'
              ' P.decLabel(null), P.decLabel("7")])')
    assert got == ["38.5", "40", "2.3", "1,136.3", "\u2014", "\u2014"]


def test_the_status_chips_are_the_rows_flags_and_nothing_else():
    got = run(PROJECTS + LINKED + 'out([P.statusChips(pr({statuses:["behind"]})),'
              ' P.statusChips(pr({statuses:["not_linked"]})), P.statusChips(linked()),'
              ' P.statusChips(pr({statuses:["made-up", "behind"]})), P.statusChips(null),'
              ' P.statusChips(pr({statuses:"behind"}))])')
    assert got == [[{"id": "behind", "label": "Behind"}],
                   [{"id": "not_linked", "label": "Not linked"}],
                   [], [{"id": "behind", "label": "Behind"}], [], []]


def test_a_not_linked_row_says_why():
    got = run(PROJECTS + 'const n = (r, o) => P.notLinkedNote(pr(Object.assign({job_number:"26.125",'
              ' raken: Object.assign({state:"not_linked", reason:r}, o || {})})));'
              'out([n("no_job_number"), n("no_raken_project"),'
              ' n("duplicate", {duplicates:[{name:"Example Clinic"}, {name:"Example Copy"}]}),'
              ' n("duplicate", {duplicates:[{name:"A"}, {name:null, number:"26.125"}, {name:"C"}]}),'
              ' P.notLinkedNote(PROJECTS[0])])')
    assert got == [
        "No Job number on the calendar",
        "No Raken project has Project Number 26.125",
        "Two Raken projects have Project Number 26.125: Example Clinic and Example Copy",
        "3 Raken projects have Project Number 26.125: A, an unnamed project and C",
        "",
    ]


def test_the_as_of_line_and_the_one_message():
    got = run('out([P.asOfText({raken:{state:"connected", as_of:"2026-11-18T09:05:00-06:00"}}),'
              ' P.asOfText({raken:{state:"not_refreshed", as_of:null}}),'
              ' P.asOfText({raken:{state:"not_connected", as_of:null}}), P.asOfText(null),'
              ' P.rakenMessage({raken:{message:"Raken is not connected."}}),'
              ' P.rakenMessage({raken:{message:null}}), P.rakenMessage({}),'
              ' P.rakenMessage({raken:{message:{x:1}}})])')
    assert got == ["Raken as of Nov 18, 9:05 AM (Central)",
                   "Raken has not been read yet. Press Refresh now.", "", "",
                   "Raken is not connected.", "", "", ""]


def test_a_raken_only_project_is_named_even_without_a_name():
    got = run('out([P.rakenOnlyName({name:"Example Unscheduled"}), P.rakenOnlyName({name:null}),'
              ' P.rakenOnlyName(null)])')
    assert got == ["Example Unscheduled", "Unnamed Raken project", "Unnamed Raken project"]


def test_the_page_has_the_refresh_button_the_as_of_line_and_the_raken_only_section():
    html, js = _page(), _pva_js()
    for el in ('id="pva-refresh"', 'id="pva-asof"', 'id="pva-only"', 'id="pva-only-body"'):
        assert el in html, el
    assert "P.rakenCells(p)" in js and "P.statusChips(p)" in js
    assert "P.asOfText(DATA)" in js and "P.rakenMessage(DATA)" in js
    assert "DATA.raken_only" in js
    # The words the glossary avoids never reach the page.
    for word in ("men", "guys", "headcount"):
        assert not re.search(r"(?<![A-Za-z])%s(?![A-Za-z])" % word, html, re.I), word
