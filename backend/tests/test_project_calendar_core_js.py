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
    """One tested function owns the https-only rule for both the Schedule's details panel and Plan
    vs Actual's job detail (#789 review: the page's own safeLink was a copy of it)."""
    js = _page_js()
    assert "P.httpsLink(ev.html_link)" in js
    assert "safeLink" not in js, "the rule lives once, in the core"
    assert 'target="_blank" rel="noopener noreferrer"' in js
    assert run('out([P.httpsLink(" https://calendar.example/e "),'
               ' P.httpsLink("HTTPS://x.example/"),'
               ' P.httpsLink("javascript:alert(1)"), P.httpsLink("http://x.example/"),'
               ' P.httpsLink(null), P.httpsLink(42)])') == [
        "https://calendar.example/e", "HTTPS://x.example/", "", "", "", ""]


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
        " × Crew size × 8. Days clocked in, On site and Actual hours come from Raken time cards;"
        " Budgeted hours and Projected total hours from Raken's production insights.",
        "No jobs are running, finished in the last 14 days, or starting in the next 14 days.",
        "Counts so far run through yesterday, Tue, Nov 17, 2026. Planned hours = Workdays so far"
        " × Crew size × 10. Days clocked in, On site and Actual hours come from Raken time cards;"
        " Budgeted hours and Projected total hours from Raken's production insights.",
        "No jobs are running, finished in the last 21 days, or starting in the next 21 days.",
        "Planned hours = Workdays so far × Crew size × the hours in a workday."
        " Days clocked in, On site and Actual hours come from Raken time cards;"
        " Budgeted hours and Projected total hours from Raken's production insights.",
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
    assert got[1]["over_budget"] == ra.STATUS_OVER_BUDGET and got[1]["on_plan"] == ra.STATUS_ON_PLAN


def test_the_page_and_the_server_name_the_same_not_linked_reasons():
    """Why a row is Not linked is raken_actuals.py's REASON_*; the page names each once, so a
    reason renamed on one side fails here instead of falling through to the wrong sentence."""
    import raken_actuals as ra
    got = run("out([P.REASON, P.RAKEN_NOT_CONNECTED === P.RAKEN.not_connected])")
    assert got[0] == {"no_job_number": ra.REASON_NO_JOB_NUMBER,
                      "no_raken_project": ra.REASON_NO_RAKEN_PROJECT,
                      "duplicate": ra.REASON_DUPLICATE}
    assert got[1] is True
    core = CORE.read_text(encoding="utf-8")
    assert "var RAKEN_NOT_CONNECTED = RAKEN.not_connected;" in core
    i = core.index("function notLinkedNote(")
    body = core[i:core.index("\n  }\n", i)]
    for literal in ('"no_job_number"', '"no_raken_project"', '"duplicate"'):
        assert literal not in body, literal


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
const linked = (o) => pr({workdays_so_far:5, raken: Object.assign({state:"linked", projects:[], days_booked:5,
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
        {"days": "4", "days_note": "", "on_site": "3.5", "hours": "131.5"},
        {"days": "0", "days_note": "", "on_site": dash, "hours": "0"},
        {"days": "4", "days_note": "", "on_site": "3.5", "hours": "1,136"},
        {"days": dash, "days_note": "", "on_site": dash, "hours": dash},
        {"days": dash, "days_note": "", "on_site": dash, "hours": dash},
        {"days": dash, "days_note": "", "on_site": dash, "hours": dash},
    ]


def test_days_clocked_in_names_the_days_raken_was_compared_against_when_they_differ():
    """Behind compares days clocked in with the booked days the read covered. When that is fewer
    than the row's Workdays booked so far (a read from yesterday, a job older than the read), the
    pair says so, or "3 booked, 2 clocked in" with no Behind would look wrong."""
    got = run(PROJECTS + LINKED + 'const c = (p) => P.rakenCells(p);'
              'out([c(linked({days_booked:2, days_clocked:2})),'
              ' c(linked({days_booked:2, days_clocked:1, through:null})),'
              ' c(linked({days_booked:5, days_clocked:5}))])')
    assert [g["days"] for g in got] == ["2 of 2", "1 of 2", "5"]
    assert [g["days_note"] for g in got] == ["through Nov 17", "", ""]
    js = _pva_js()
    assert "rc.days_note" in js


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
        "No Raken project carries Job number 26.125",
        "Two Raken projects carry Job number 26.125: Example Clinic and Example Copy",
        "3 Raken projects carry Job number 26.125: A, an unnamed project and C",
        "",
    ]
    # GLOSSARY.md: Job number, never "Project number".
    for text in (CORE.read_text(encoding="utf-8"), _pva_js(), _page()):
        assert not re.search(r"project number", text, re.I)


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


def test_the_as_of_line_says_when_a_refresh_is_running_and_the_page_polls_until_done():
    got = run('out([P.asOfText({raken:{state:"connected", as_of:"2026-11-18T09:05:00-06:00",'
              ' refreshing:true}}),'
              ' P.asOfText({raken:{state:"not_refreshed", as_of:null, refreshing:true}}),'
              ' P.rakenRefreshing({raken:{refreshing:true}}), P.rakenRefreshing({raken:{}}),'
              ' P.rakenRefreshing(null), P.rakenRefreshing({raken:{refreshing:"yes"}})])')
    assert got == ["Raken as of Nov 18, 9:05 AM (Central). Refreshing\u2026",
                   "Refreshing Raken\u2026", True, False, False, False]
    js = _pva_js()
    assert "P.rakenRefreshing(DATA)" in js and "setTimeout(" in js


def test_refresh_now_goes_through_the_same_api_helper_as_the_get():
    js = _pva_js()
    assert 'api("/api/project-analytics/refresh", { method: "POST" })' in js
    assert js.count("fetch(") == 1, "one fetch, inside api()"


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
    assert re.search(r"\.pva \.rk \{ background:var\(--rk-wash\); \}", html)
    assert "--rk-wash:" in html[html.index(":root"):html.index("}", html.index(":root"))]
    assert "whose Job number matches no job on the calendar" in " ".join(html.split())
    # The words the glossary avoids never reach the page.
    for word in ("men", "guys", "headcount"):
        assert not re.search(r"(?<![A-Za-z])%s(?![A-Za-z])" % word, html, re.I), word


# ── #783: the Budget pair, Over budget and On plan ──────────────────────────────────────────────
BUDGETED = """
const budgeted = (o, st) => pr({workdays_so_far:5, planned_hours:160,
  raken: Object.assign({state:"linked", projects:[], days_booked:5, days_clocked:5,
    avg_on_site:4, actual_hours:150, through:"2026-11-17", budget:"shown", budgeted_hours:1200,
    projected_total_hours:1330, over_under:-130, projection_below_actual:false}, o || {}),
  statuses: st || ["over_budget"]});
"""


def test_over_under_reads_signed_whole_hours():
    """Over/under = Budgeted hours - Projected total hours: below zero is over budget, so it reads
    with a minus sign (U+2212), and above zero with a plus. Under an hour either way reads "<1 h"
    with its sign, never "0 h": the server calls -0.3 Over budget, and the cell is red."""
    got = run('out([P.overUnderLabel(12), P.overUnderLabel(-130), P.overUnderLabel(0),'
              ' P.overUnderLabel(-0.4), P.overUnderLabel(1234.6), P.overUnderLabel(-1500),'
              ' P.overUnderLabel(null), P.overUnderLabel("12"), P.overUnderLabel(NaN),'
              ' P.overUnderLabel(-0.3), P.overUnderLabel(0.3), P.overUnderLabel(-0.5),'
              ' P.overUnderLabel(-0.01), P.overUnderLabel(0.6)])')
    assert got == ["+12 h", "−130 h", "0 h", "−<1 h", "+1,235 h", "−1,500 h",
                   "—", "—", "—", "−<1 h", "+<1 h", "−<1 h", "−<1 h", "+1 h"]


def test_a_pair_bar_puts_the_plan_as_a_tick_and_raken_as_the_fill():
    """The longer of the two fills the bar; the widths are percentages of it, one decimal."""
    got = run('out([P.pairBar(160, 150), P.pairBar(1200, 1330), P.pairBar(100, 100),'
              ' P.pairBar(0, 16), P.pairBar(64, 0), P.pairBar(0, 0), P.pairBar(null, 5),'
              ' P.pairBar(5, null), P.pairBar(-3, 5), P.pairBar("160", 150),'
              ' P.pairBar(3, 1)])')
    assert got == [
        {"fill": 93.8, "tick": 100, "over": False},
        {"fill": 100, "tick": 90.2, "over": True},
        {"fill": 100, "tick": 100, "over": False},
        {"fill": 100, "tick": 0, "over": True},
        {"fill": 0, "tick": 100, "over": False},
        None, None, None, None, None,
        {"fill": 33.3, "tick": 100, "over": False},
    ]


def test_the_hours_bar_is_planned_hours_against_actual_hours_for_a_linked_row_only():
    got = run(PROJECTS + BUDGETED + 'out([P.hoursBar(budgeted()),'
              ' P.hoursBar(budgeted({actual_hours:200})), P.hoursBar(PROJECTS[0]),'
              ' P.hoursBar(pr({raken:{state:"not_linked", reason:"no_job_number"}})),'
              ' P.hoursBar(pr({planned_hours:null, raken:{state:"linked", actual_hours:5}})),'
              ' P.hoursBar(null)])')
    assert got == [{"fill": 93.8, "tick": 100, "over": False},
                   {"fill": 100, "tick": 80, "over": True}, None, None, None, None]


def test_the_budget_pair_reads_projected_total_against_budgeted_with_over_under():
    got = run(PROJECTS + BUDGETED + 'const b = (o) => P.budgetCells(budgeted(o));'
              'out([b(), b({budgeted_hours:1180, projected_total_hours:1050.4, over_under:129.6}),'
              ' b({projected_total_hours:140, budgeted_hours:180, over_under:40,'
              '    projection_below_actual:true})])')
    assert got[0] == {"shown": True, "projected": "1,330", "budgeted": "1,200",
                      "over_under": "−130 h", "over": True, "note": "",
                      "bar": {"fill": 100, "tick": 90.2, "over": True}}
    assert got[1]["projected"] == "1,050" and got[1]["budgeted"] == "1,180"
    assert got[1]["over_under"] == "+130 h" and got[1]["over"] is False
    assert got[2]["note"] == "Raken's projection covers only the work in its budget"
    assert got[2]["bar"] == {"fill": 77.8, "tick": 100, "over": False}


def test_no_raken_budget_or_a_budget_not_read_shows_dashes_and_says_which():
    dash = "—"
    got = run(PROJECTS + BUDGETED + 'const nb = {budget:"none", budgeted_hours:null,'
              ' projected_total_hours:null, over_under:null, projection_below_actual:false};'
              'out([P.budgetCells(budgeted(nb, ["on_plan"])),'
              ' P.budgetCells(budgeted(Object.assign({}, nb, {budget:"not_read"}), ["on_plan"])),'
              ' P.budgetCells(budgeted({budget:undefined, budgeted_hours:undefined,'
              '   projected_total_hours:undefined, over_under:undefined}, [])),'
              ' P.budgetCells(PROJECTS[0]),'
              ' P.budgetCells(pr({raken:{state:"not_linked", reason:"no_job_number"}})),'
              ' P.budgetCells(null)])')
    empty = {"shown": False, "projected": dash, "budgeted": dash, "over_under": dash,
             "over": False, "bar": None}
    assert got[0] == dict(empty, note="No Raken budget")
    assert got[1] == dict(empty, note="Raken's budget not read")
    assert got[2] == dict(empty, note="Raken's budget not read"), "a read from before #783"
    assert got[3] == dict(empty, note="")
    assert got[4] == dict(empty, note="")
    assert got[5] == dict(empty, note="")


def test_the_status_chips_are_on_plan_behind_over_budget_and_not_linked():
    """Statuses are flags: a job Behind and Over budget shows both chips."""
    got = run(PROJECTS + 'const c = (s) => P.statusChips(pr({statuses:s})).map(x => x.label);'
              'out([c(["on_plan"]), c(["behind"]), c(["over_budget"]), c(["over_budget", "behind"]),'
              ' c(["not_linked"]), c([]), c(["made-up"])])')
    assert got == [["On plan"], ["Behind"], ["Over budget"], ["Behind", "Over budget"],
                   ["Not linked"], [], []]


def test_the_page_and_the_server_name_the_same_budget_states():
    import raken_actuals as ra
    got = run("out(P.BUDGET)")
    assert got == {"shown": ra.BUDGET_SHOWN, "none": ra.BUDGET_NONE, "not_read": ra.BUDGET_NOT_READ}
    assert sorted(got.values()) == sorted(ra.BUDGET_STATES)
    core = CORE.read_text(encoding="utf-8")
    i = core.index("function budgetCells(")
    body = core[i:core.index("\n  }\n", i)]
    for literal in ('"shown"', '"none"', '"not_read"', '"linked"'):
        assert literal not in body, literal


def test_the_page_shows_the_budget_pair_and_draws_both_bars_through_the_cssom():
    html, js = _page(), _pva_js()
    head = html[html.index('<table class="pva">'):html.index("</thead>")]
    assert "Projected total hours<small>of Budgeted hours, Over/under</small>" in head
    assert head.index("Actual hours<small>") < head.index("Projected total hours<small>") \
        < head.index(">Status<")
    assert "P.budgetCells(p)" in js and "P.hoursBar(p)" in js
    # The widths and the tick's place go through element.style once the markup is in place (CSP).
    assert ".style.width" in js and ".style.left" in js
    assert 'style="' not in js and "style='" not in js
    for cls in (".pbar", ".pbar-fill", ".pbar-tick", ".chip.st-over_budget", ".chip.st-on_plan"):
        rule = re.search(re.escape(cls) + r"\s*\{([^}]*)\}", html)
        assert rule, cls
        assert "#" not in rule.group(1), "%s uses a new hard-coded colour" % cls
    for field in ("bc.projected", "bc.budgeted", "bc.over_under", "bc.note"):
        hits = list(re.finditer(re.escape(field), js))
        assert hits, field
        for m in hits:
            line = js[js.rfind("\n", 0, m.start()) + 1: js.find("\n", m.end())]
            assert "esc(" in line, "%s reaches markup unescaped: %s" % (field, line.strip())


# ── #789: the job detail, its day-by-day chart, and the Schedule's way into it ──────────────────
# Day-by-day entries in the shape GET /api/project-analytics sends them (plan_vs_actual._day_by_day,
# filled by raken_actuals for a linked row). "Today" is Wed Nov 18.
DAYS = """
const dd = (date, o) => Object.assign({date: date, planned_crew: 3, planned_hours: 24,
  crew_size_missing: false, future: false, on_site: null, hours: null, missed: false}, o || {});
const DAYS = [
  dd("2026-11-13", {planned_crew: 5, planned_hours: 40, on_site: 6, hours: 47.5}),
  dd("2026-11-16", {on_site: 2, hours: 16}),
  dd("2026-11-17", {on_site: 0, hours: 0, missed: true}),
  dd("2026-11-18", {future: true}),
  dd("2026-11-19", {future: true, planned_crew: null, planned_hours: null, crew_size_missing: true}),
];
"""


def test_the_chart_scale_is_the_largest_crew_or_people_on_site():
    """One scale for the line and the bars: the most people planned or on site on any day, so a
    day with more people than planned draws its bar past the line, never clipped."""
    got = run(DAYS + 'const c = P.dayChart(DAYS);'
              'out([c.scale, c.columns.map(x => [x.bar, x.tick]),'
              ' P.dayChart([dd("2026-11-16", {planned_crew: 4, on_site: 2})]).scale,'
              ' P.dayChart([dd("2026-11-16", {planned_crew: null, planned_hours: null})]).scale,'
              ' P.dayChart([]).columns, P.dayChart(null).columns, P.dayChart("x").scale])')
    assert got == [6, [[100, 83.3], [33.3, 50], [0, 50], [None, 50], [None, None]],
                   4, 1, [], [], 1]


def test_past_days_compare_and_future_days_carry_the_plan_only():
    got = run(DAYS + 'out(P.dayChart(DAYS).columns.map(x => [x.kind, x.actual, x.planned]))')
    assert got == [["clocked", "47.5", "40"], ["clocked", "16", "24"], ["missed", "0", "24"],
                   ["future", "", "24"], ["future", "", "—"]]
    # A past day Raken did not read (a Not linked job, or Raken not connected): the plan only,
    # and never marked missed.
    got = run(DAYS + 'out(P.dayChart([dd("2026-11-16")]).columns.map(x => [x.kind, x.actual,'
              ' x.bar]))')
    assert got == [["plan", "", None]]


def test_the_chart_names_each_day_and_marks_where_each_week_starts():
    got = run(DAYS + 'out(P.dayChart(DAYS).columns.map(x => [x.dow, x.dom, x.week]))')
    assert got == [["Fri", "13", "Nov 13"], ["Mon", "16", "Nov 16"], ["Tue", "17", ""],
                   ["Wed", "18", ""], ["Thu", "19", ""]]
    got = run(DAYS + 'out(P.dayChart(DAYS).columns.map(x => x.label))')
    # One Workday's people are "clocked in", never "on site": On site is the GLOSSARY's average a
    # day, shown in the Crew pair just above the chart.
    assert got[0] == "Fri, Nov 13: 5 planned, 6 clocked in, 47.5 of 40 hours"
    assert got[2] == "Tue, Nov 17: 3 planned, nobody clocked in, missed"
    assert got[3] == "Wed, Nov 18: 3 planned"
    assert got[4] == "Thu, Nov 19: Crew size missing"
    assert all("on site" not in g for g in got)


def test_a_day_with_one_crew_size_missing_says_so_and_is_marked():
    """Two Mobilizations overlap; one has a Crew size, the other none (the server sets
    crew_size_missing). The column shows the partial plan, so it must say a Crew size is missing,
    in words and as a mark, not only when every Mobilization that day lacks one."""
    got = run(DAYS + 'out(P.dayChart([dd("2026-11-16", {planned_crew: 2, planned_hours: 16,'
              ' crew_size_missing: true, on_site: 2, hours: 16}), dd("2026-11-17"),'
              ' dd("2026-11-18", {future: true, planned_crew: null, planned_hours: null,'
              ' crew_size_missing: true})]).columns.map(x => [x.warn, x.label]))')
    assert got == [[True, "Mon, Nov 16: 2 planned, a Crew size is missing, 2 clocked in,"
                          " 16 of 16 hours"],
                   [False, "Tue, Nov 17: 3 planned"],
                   [True, "Wed, Nov 18: Crew size missing"]]
    # The column carries only what is drawn: no copies of the server's fields beside it.
    keys = run(DAYS + 'out(Object.keys(P.dayChart(DAYS).columns[0]).sort())')
    assert keys == sorted(["dow", "dom", "week", "kind", "tick", "bar", "over", "warn", "actual",
                           "planned", "label"])
    js = _pva_js()
    assert '(c.warn ? " warn" : "")' in js
    assert re.search(r"\.pd-col\.warn [^{]*\{[^}]*var\(--warn\)", _page())
    assert "<i class=\"k-bar\"></i>People clocked in (Raken)" in _page()


def test_a_schedule_bar_finds_its_row_by_the_event_id():
    """By the EVENT ID, never by Job number or name (#789's note from #792): a merged row holds an
    unnumbered Mobilization under a Job number, and a Punch with a Job number of its own."""
    got = run(PROJECTS + 'const rows = ['
              ' pr({key:"job:26.125", job_number:"26.125", name:"Acme Clinic Psych",'
              '     mobilizations:[{id:"m1", job_number:"26.125"}, {id:"m2", job_number:null}],'
              '     punches:[{id:"p1", job_number:"26.912"}]}),'
              ' pr({key:"name:examplediner", name:"Example Diner", mobilizations:[{id:"m3"}]})];'
              'const k = (id) => (P.rowForEvent(rows, id) || {}).key || null;'
              'out([k("m1"), k("m2"), k("p1"), k("m3"), k("26.125"), k("Acme Clinic Psych"),'
              ' k(""), k(null), (P.rowForEvent(null, "m1") || null),'
              ' (P.rowForEvent([null, {mobilizations:"x"}], "m1") || null)])')
    assert got == ["job:26.125", "job:26.125", "job:26.125", "name:examplediner",
                   None, None, None, None, None, None]


def test_a_bar_with_no_row_says_why_only_once_the_list_has_loaded():
    got = run(PROJECTS + 'const data = {window_days: 14, projects: [pr({key:"job:1",'
              ' mobilizations:[{id:"m1"}]})]};'
              'const s = (d, id) => { const r = P.pvaLookup(d, id);'
              ' return [r.state, r.row ? r.row.key : null]; };'
              'out([s(data, "m1"), s(data, "zz"), s(null, "m1"), s({projects:"x"}, "m1"),'
              ' P.notInPvaLine(data), P.notInPvaLine({}), P.notInPvaLine({window_days: 21})])')
    assert got == [["found", "job:1"], ["absent", None], ["unknown", None], ["unknown", None],
                   "Not in Plan vs Actual: outside the 14-day window",
                   "Not in Plan vs Actual: outside its window",
                   "Not in Plan vs Actual: outside the 21-day window"]
    # The window is the server's: with no window_days the line says so without a number, as
    # pvaEmptyText does, rather than a copy of plan_vs_actual.WINDOW_DAYS.
    assert run('out([P.notInPvaLine(null), P.notInPvaLine({window_days: "14"}),'
               ' P.notInPvaLine({window_days: 0})])') == [
        "Not in Plan vs Actual: outside its window"] * 3


def test_back_returns_to_where_the_detail_was_opened_from():
    got = run('out([P.detailBack("schedule"), P.detailBack("pva"), P.detailBack(null),'
              ' P.detailBack("made-up")])')
    assert got == [{"tab": "schedule", "label": "Back to the Schedule"},
                   {"tab": "pva", "label": "Back to Plan vs Actual"},
                   {"tab": "pva", "label": "Back to Plan vs Actual"},
                   {"tab": "pva", "label": "Back to Plan vs Actual"}]


def test_open_project_goes_to_the_project_in_the_tool():
    got = run('out([P.projectHref({id:"d1e2-f3", name:"x"}), P.projectHref({id:"a b/c"}),'
              ' P.projectHref({name:"x"}), P.projectHref(null)])')
    assert got == ["/?d=d1e2-f3&edit=1", "/?d=a%20b%2Fc&edit=1", "", ""]


def test_the_open_project_footer_is_worded_once_for_both_panels():
    """The Schedule's details panel and Plan vs Actual's job detail both end on "Open project", or
    on why there is none. The words live in the core (#789 review), so changing them is one edit."""
    got = run('out([P.projectFoot({id:"d1", name:"Example Clinic"}, "26.501"),'
              ' P.projectFoot({id:"d1"}, null), P.projectFoot(null, "26.501"),'
              ' P.projectFoot({name:"x"}, ""), P.projectFoot(undefined, undefined)])')
    assert got == [{"href": "/?d=d1&edit=1", "label": "Open project: Example Clinic"},
                   {"href": "/?d=d1&edit=1", "label": "Open project: this project"},
                   {"note": "No project in this tool has Job number 26.501 yet."},
                   None, None]
    for js in (_page_js(), _pva_js()):
        assert "No project in this tool" not in js and "Open project:" not in js
        assert "P.projectFoot(" in js
    # The Plan vs Actual status chips are written once on that page, for the row and the detail.
    assert _pva_js().count('<span class="chip st-') == 1


def test_the_detail_lists_mobilizations_and_punches_with_dates_crew_and_google_links():
    got = run(PROJECTS + 'out(P.detailEvents(pr({'
              ' mobilizations:[{id:"m2", start:"2026-11-16", last_day:"2026-11-20", crew_size:2,'
              '   mobilization:2, html_link:"https://calendar.example/e?eid=m2"},'
              '  {id:"m1", start:"2026-11-02", last_day:"2026-11-06", crew_size:null,'
              '   mobilization:null, html_link:"javascript:alert(1)"}],'
              ' punches:[{id:"p1", start:"2026-11-23", last_day:"2026-11-23", crew_size:1,'
              '   html_link:"https://calendar.example/e?eid=p1"}]})))')
    assert [g["id"] for g in got] == ["m1", "m2", "p1"], "date order, Punches with the rest"
    assert [g["kind"] for g in got] == ["Mobilization", "2nd Mobilization", "Punch"]
    assert [g["crew"] for g in got] == ["Crew size missing", "Crew size 2", "Crew size 1"]
    assert got[0]["link"] == "", "only an https link is ever offered"
    assert got[2]["link"] == "https://calendar.example/e?eid=p1"
    assert got[1]["dates"] == "Mon, Nov 16 – Fri, Nov 20, 2026"


def test_the_detail_shows_the_four_pairs():
    got = run(PROJECTS + BUDGETED + 'out(P.detailPairs(budgeted()).map(x => [x.id, x.label,'
              ' x.plan, x.actual]))')
    assert got == [["days", "Days", "5", "5"], ["crew", "Crew", "4", "4"],
                   ["hours", "Hours so far", "160", "150"],
                   ["budget", "Budget", "1,200", "1,330"]]
    got = run(PROJECTS + 'out(P.detailPairs(PROJECTS[0]).map(x => [x.plan, x.actual]))')
    assert got == [["2", "—"], ["4", "—"], ["64", "—"], ["—", "—"]]


def test_the_detail_flags_are_prevailing_wage_and_night_work():
    got = run(PROJECTS + 'out([P.detailFlags(pr({prevailing_wage:true, night_work:true})),'
              ' P.detailFlags(pr({})), P.detailFlags(null)])')
    assert got == [["Prevailing wage", "Night work"], [], []]
    # The two panels word the flags and the "<ordinal> Mobilization" the same way because one
    # list says them (#789 review): a new flag, or new wording, is written in one place.
    core = CORE.read_text(encoding="utf-8")
    for words in ('"Prevailing wage"', '"Night work"', '" Mobilization"'):
        assert core.count(words) == 1, words


def test_the_detail_is_a_view_inside_the_plan_vs_actual_panel_with_a_back_button():
    """Not a new page and no new nav entry: the list and the detail share the Plan vs Actual panel,
    and the detail starts hidden."""
    html = _page()
    panel = html[html.index('id="panel-pva"'):html.index('id="panel-schedule"')]
    assert 'id="pva-list"' in panel and 'id="pva-detail"' in panel
    tag = panel[panel.rfind("<section", 0, panel.index('id="pva-detail"')):]
    assert "hidden" in tag[:tag.index(">")], "the detail starts hidden"
    detail = tag
    for el in ('id="pd-back"', 'id="pd-pairs"', 'id="pd-chart"', 'id="pd-events"', 'id="pd-facts"',
               'id="pd-foot"', 'id="pd-chips"'):
        assert el in detail, el
    assert 'class="pd-chart-scroll"' in html
    assert re.search(r"\.pd-chart-scroll\s*\{[^}]*overflow-x:\s*auto", html), (
        "the chart's weeks scroll inside their box at phone width")


def test_a_big_figure_in_a_pair_never_spills_past_its_card_at_phone_width():
    """At 375px the pairs sit two across, so each half of a pair is about 65px: a Projected total
    of "12,345.5" did not fit. Below 420px each pair's two figures stack, and a figure may wrap."""
    html = _page()
    assert re.search(r"\.pd-two b \{[^}]*overflow-wrap:\s*anywhere", html)
    m = re.search(r"@media \(max-width:\s*420px\) \{([^@]*)", html)
    assert m, "a narrow-phone block"
    assert re.search(r"\.pd-two \{\s*grid-template-columns:\s*1fr;?\s*\}", m.group(1))


def test_a_row_opens_its_detail_by_keyboard_and_back_or_esc_closes_it():
    js = _pva_js()
    assert '<button type="button" class="jlink" data-key="\' + esc(p.key)' in js
    assert '$("pva-body").addEventListener("click"' in js
    assert '$("pd-back").addEventListener("click", closeDetail)' in js
    i = js.index('if (e.key !== "Escape" || !DETAIL')
    assert "closeDetail()" in js[i:i + 200]
    assert 'document.addEventListener("keydown", onEscape)' in js
    assert "P.detailBack(was.origin)" in js and "P.detailBack(DETAIL.origin).label" in js


def test_the_detail_draws_its_chart_through_the_cssom_and_escapes_every_value():
    js = _pva_js()
    assert ".style.height = pct(" in js and ".style.bottom = pct(" in js
    assert 'style="' not in js and "style='" not in js
    for field in ("x.plan", "x.actual", "x.label", "x.note", "x.extra", "c.label", "c.actual",
                  "c.planned", "c.week", "e.kind", "e.dates", "e.crew", "e.foreman", "e.link",
                  "f)", "href"):
        hits = [m for m in re.finditer(re.escape(field), js)]
        assert hits, field
        for m in hits:
            line = js[js.rfind("\n", 0, m.start()) + 1: js.find("\n", m.end())]
            if "innerHTML" in line or "'<" in line or '"<' in line:
                assert "esc(" in line or "textContent" in line, (
                    "%s reaches markup unescaped: %s" % (field, line.strip()))
    # The Google links are https only (P.detailEvents, through P.httpsLink) and open a new tab.
    assert "P.detailEvents(p)" in js
    assert 'target="_blank" rel="noopener noreferrer"' in js
    assert "P.dayChart(p.day_by_day)" in js and "P.detailPairs(p)" in js
    assert "P.detailFlags(p)" in js and "P.projectFoot(p.project, p.job_number)" in js


def test_a_schedule_bar_opens_the_detail_by_event_id_or_the_panel_saying_why():
    """#789's note from #792: by the EVENT ID, never by Job number or name."""
    js = _page_js()
    i = js.index("const openFrom = (e) => {")
    block = js[i:js.index("  };", i)]
    # One call (#789 review): the Schedule never learns Plan vs Actual's states or its data.
    assert "pva.openEvent(ev.id, b.dataset.k)" in block
    assert "openDetails(ev, r.line)" in block
    assert "job_number" not in block and ".name" not in block
    assert "lookup" not in block and ".data(" not in block and "notInPvaLine" not in block
    pva = _pva_js()
    assert "window.TWPva = { openEvent: openEvent };" in pva and "P.pvaLookup(DATA, id)" in pva
    html = _page()
    assert 'id="dlg-note"' in html
    assert '$("dlg-note").textContent = line' in js
    # One door into the tool's intake for both: built once in the core (P.projectHref, worded by
    # P.projectFoot).
    assert "P.projectFoot(ev.project, ev.job_number)" in js and "edit=1" not in js
    assert "edit=1" not in pva


# ── the job detail's wiring, run under node: functions lifted out of plan-vs-actual.js ──────────
def _lift(path, name):
    """One function out of a page script, by brace-matching (the page is an IIFE that needs a
    browser, so it cannot be required)."""
    src = path.read_text(encoding="utf-8")
    m = re.search(r"^  function " + re.escape(name) + r"\b", src, re.M)
    assert m, "%s not found in %s" % (name, path.name)
    depth, j = 0, src.index("{", m.start())
    for k in range(j, len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[m.start():k + 1]
    raise AssertionError("unterminated " + name)


# A fake page: elements by id, the row's name button, the focus and the address. `P` is the real
# core (run() binds it). The page's own DATA and DETAIL are plain variables, as in the IIFE.
PVA_WORLD = """
const els = {};
const focused = [];
const $ = (id) => els[id] || (els[id] = { id: id, hidden: false, open: false, tabIndex: 0,
  dataset: {}, setAttribute() {}, focus() { focused.push(id); }, querySelectorAll: () => [] });
$("pva-body").querySelectorAll = () => [{ dataset: { key: "job:1" },
  focus() { focused.push("row:job:1"); } }];
const location = { hash: "", pathname: "/project-calendar.html", search: "" };
const history = { replaceState: (a, b, url) => {
  location.hash = url.indexOf("#") >= 0 ? url.slice(url.indexOf("#")) : ""; } };
const document = { querySelectorAll: () => [] };
let painted = 0;
const paint = () => { painted++; };
let DATA = { window_days: 14, projects: [{ key: "job:1", mobilizations: [{ id: "m1" }] }] };
let DETAIL = null;
let VIEW = P.readView("");
const press = (key) => ({ key: key, prevented: false,
  preventDefault() { this.prevented = true; } });
"""


def _pva_world(script):
    lifted = "\n".join(_lift(PVA, n) for n in ("showTab", "openDetail", "closeDetail", "onEscape",
                                               "openEvent"))
    return run(PVA_WORLD + lifted + "\n" + script)


def test_esc_closes_an_open_detail_and_puts_the_focus_back_on_its_row():
    got = _pva_world('showTab("pva", false); openDetail("job:1", "pva", ""); focused.length = 0;'
                     'const e = press("Escape"); onEscape(e);'
                     'out([e.prevented, DETAIL, focused])')
    assert got == [True, None, ["row:job:1"]]


def test_leaving_by_the_tab_closes_the_detail_and_esc_on_the_schedule_does_nothing():
    """#789 review: the detail outlived a tab switch, so Esc on the Schedule (its search box
    included) ran closeDetail on a hidden view and moved the focus into it, and coming back showed
    the old detail instead of the list."""
    got = _pva_world('showTab("pva", false); openDetail("job:1", "pva", ""); focused.length = 0;'
                     'showTab("schedule", false);'
                     'const e = press("Escape"); onEscape(e);'
                     'const onSchedule = [e.prevented, DETAIL, focused.slice(), location.hash];'
                     'showTab("pva", false);'
                     'out([onSchedule, DETAIL, $("panel-pva").hidden])')
    assert got == [[False, None, [], "#schedule"], None, False]


def test_esc_with_the_detail_shown_but_the_schedule_panel_open_leaves_the_detail():
    """The Schedule's details panel (a dialog) handles its own Esc."""
    got = _pva_world('showTab("pva", false); openDetail("job:1", "pva", ""); $("dlg").open = true;'
                     'const e = press("Escape"); onEscape(e); out([e.prevented, DETAIL.key])')
    assert got == [False, "job:1"]


def test_a_schedule_bar_asks_one_question_and_gets_the_detail_or_the_line():
    """TWPva.openEvent(eventId, barKey): opened, or not with the details panel's line, "" while
    the list has not loaded (the page cannot know the job is outside the window)."""
    got = _pva_world('showTab("schedule", false);'
                     'const a = openEvent("m1", "bar-7"); const opened = [a, DETAIL,'
                     ' $("panel-pva").hidden, location.hash];'
                     'DETAIL = null; const b = openEvent("zz", "bar-8");'
                     'DATA = null; const c = openEvent("m1", "bar-9");'
                     'out([opened, b, c, DETAIL])')
    assert got == [[{"opened": True, "line": ""},
                    {"key": "job:1", "origin": "schedule", "barKey": "bar-7"}, False, ""],
                   {"opened": False, "line": "Not in Plan vs Actual: outside the 14-day window"},
                   {"opened": False, "line": ""}, None]


# ── the summary strip (#788): the counts filter the list ────────────────────────────────────────
STRIP = """
const ST = [
  pr({key:"job:1", job_number:"26.501", name:"Example Clinic", foreman:"Pat", statuses:["on_plan"]}),
  pr({key:"job:2", job_number:"26.502", name:"Example Depot", foreman:"Sam",
      statuses:["behind", "over_budget"]}),
  pr({key:"job:3", job_number:"26.503", name:"Example Annex", foreman:"Pat", statuses:["not_linked"]}),
  pr({key:"job:4", job_number:"26.504", name:"Example Clinic Annex", foreman:"Lee", statuses:[]}),
  pr({key:"job:5", job_number:"26.505", name:"Example Gym", foreman:"Pat", statuses:["behind"]}),
];
const keys = (rows) => rows.map(p => p.key);
"""


def test_a_count_filter_and_the_search_box_work_together():
    got = run(PROJECTS + STRIP + 'out([keys(P.visibleProjects(ST, "", "behind")),'
              ' keys(P.visibleProjects(ST, "pat", "behind")),'
              ' keys(P.visibleProjects(ST, "clinic", "")),'
              ' keys(P.visibleProjects(ST, "clinic", "on_plan")),'
              ' keys(P.visibleProjects(ST, "sam", "on_plan")),'
              ' keys(P.visibleProjects(ST, "", "over_budget")),'
              ' keys(P.visibleProjects(ST, "", "")).length])')
    assert got == [["job:2", "job:5"], ["job:5"], ["job:1", "job:4"], ["job:1"], [],
                   ["job:2"], 5]


SUMMARY = """
const SUM = {jobs: 5, raken_read: true, unflagged: 0,
  counts: {on_plan: 2, behind: 2, over_budget: 1, not_linked: 1},
  last_week: {from: "2026-11-09", to: "2026-11-13", planned_hours: 184, actual_hours: 47.5,
    crew_size_missing: false, jobs: 2, raken: "read"},
  budget: {budgeted_hours: 1200, projected_total_hours: 1330, over_under: -130, jobs: 2,
    linked_jobs: 4}};
const data = (o) => ({summary: Object.assign({}, SUM, o)});
"""


def test_the_four_count_tiles_say_on_plan_behind_over_budget_and_not_linked_in_that_order():
    """The counts are the server's; a job Behind and Over budget counted under both is why they
    can add up to more than the jobs. The pressed tile is the one filtering the list."""
    got = run(PROJECTS + SUMMARY + 'out([P.countTiles(data({}), "behind"),'
              ' P.countTiles(data({counts: {behind: "x", on_plan: -1}}), "").map(t => t.count),'
              ' P.countTiles({summary: null}, ""), P.countTiles(null, "")])')
    assert got[0] == [
        {"id": "on_plan", "label": "On plan", "count": 2, "pressed": False, "disabled": False},
        {"id": "behind", "label": "Behind", "count": 2, "pressed": True, "disabled": False},
        {"id": "over_budget", "label": "Over budget", "count": 1, "pressed": False,
         "disabled": False},
        {"id": "not_linked", "label": "Not linked", "count": 1, "pressed": False,
         "disabled": False}]
    assert got[1] == [0, 0, 0, 0], "an odd count reads as none"
    assert got[2] == [] and got[3] == [], "no strip without the server's summary"


def test_with_raken_not_read_the_counts_are_unknown_and_cannot_be_pressed():
    """The server sends no counts until Raken is read: each tile is no figure (the page draws a
    dash) and is disabled, and a count pressed earlier no longer filters the list."""
    got = run(PROJECTS + SUMMARY + 'const un = data({raken_read: false, counts: null});'
              'out([P.countTiles(un, "behind"), P.statusFilter(un, "behind"),'
              ' P.statusFilter(data({}), "behind"), P.statusFilter(null, "behind")])')
    assert got[0] == [{"id": i, "label": l, "count": None, "pressed": False, "disabled": True}
                      for i, l in (("on_plan", "On plan"), ("behind", "Behind"),
                                   ("over_budget", "Over budget"), ("not_linked", "Not linked"))]
    assert got[1:] == ["", "behind", ""]


def test_only_the_four_counts_filter_the_list():
    """A status that is not one of the four counts filters nothing (the server's status_filter is
    the same rule, so the Excel download and the screen agree)."""
    got = run(PROJECTS + SUMMARY + 'const d = data({});'
              'out(["behind", "made_up", "BEHIND", "", null, "toString"]'
              '.map((s) => P.statusFilter(d, s)))')
    assert got == ["behind", "", "", "", "", ""]


def test_the_strip_says_why_the_counts_fall_short_or_are_not_known():
    got = run(PROJECTS + SUMMARY + 'out([P.countsNote(data({})), P.countsNote(data({unflagged: 1})),'
              ' P.countsNote(data({unflagged: 2})),'
              ' P.countsNote(data({raken_read: false, counts: null, unflagged: null})),'
              ' P.countsNote({summary: null})])')
    assert got == ["", "1 job is in no count: its Raken budget was not read.",
                   "2 jobs are in no count: their Raken budgets were not read.",
                   "Raken has not been read, so the counts are not known.", ""]


def test_pressing_a_count_again_clears_it_and_only_known_statuses_filter():
    got = run(PROJECTS + 'out([P.toggleStatus("", "behind"), P.toggleStatus("behind", "behind"),'
              ' P.toggleStatus("behind", "over_budget"), P.toggleStatus("", "made-up"),'
              ' P.toggleStatus("on_plan", null)])')
    assert got == ["behind", "", "over_budget", "", ""]


def test_last_week_reads_planned_against_actual_and_says_plainly_when_raken_was_not_read():
    """Raken not read: the planned figure shows and Actual hours are a dash, never 0."""
    got = run(PROJECTS + SUMMARY + 'const lw = (o) => P.lastWeekTile(data({last_week:'
              ' Object.assign({}, SUM.last_week, o)}));'
              'out([lw({}), lw({raken: "not_read", actual_hours: null, jobs: 3, planned_hours: 344}),'
              ' lw({raken: "not_covered", actual_hours: null}), lw({jobs: 1}),'
              ' lw({raken: "read", actual_hours: 0, jobs: 0, planned_hours: 0}),'
              ' P.lastWeekTile({summary: null}),'
              ' lw({crew_size_missing: true, planned_hours: 136}),'
              ' lw({crew_size_missing: true, planned_hours: null})])')
    assert got[0] == {"range": "Mon, Nov 9 – Fri, Nov 13", "planned": "184", "actual": "47.5",
                      "note": "Over the 2 linked jobs in the list."}
    assert got[1] == {"range": "Mon, Nov 9 – Fri, Nov 13", "planned": "344",
                      "actual": "—",
                      "note": "Raken has not been read, so Actual hours are not known. "
                              "Planned hours are for the 3 jobs with a Job number."}
    assert got[2]["actual"] == "—"
    assert got[2]["note"] == "Raken's last read stops before the end of last week."
    assert got[3]["note"] == "Over the 1 linked job in the list."
    assert got[4]["actual"] == "0" and got[4]["note"] == "No job is linked to Raken."
    assert got[5] is None
    # A Workday with no Crew size adds nothing: the figure is short, or no figure, and says so.
    assert got[6]["planned"] == "136"
    assert got[6]["note"] == ("Over the 2 linked jobs in the list. Some Workdays have no Crew size,"
                              " so Planned hours are short.")
    assert got[7]["planned"] == "—"
    assert got[7]["note"] == ("Over the 2 linked jobs in the list. No Workday last week has a"
                              " Crew size, so Planned hours are not known.")


def test_the_budget_totals_say_how_many_jobs_they_cover():
    """Whether Raken was read is the summary's own `raken_read`, never last week's state: the
    tile reads the same with last week missing."""
    got = run(PROJECTS + SUMMARY + 'const bt = (o, s) => P.budgetTile(data(Object.assign({budget:'
              ' Object.assign({}, SUM.budget, o)}, s)));'
              'out([bt({}), bt({over_under: 12.4, projected_total_hours: 1187.6}),'
              ' bt({budgeted_hours: null, projected_total_hours: null, over_under: null, jobs: 0}),'
              ' bt({jobs: 1, linked_jobs: 1}),'
              ' bt({budgeted_hours: null, projected_total_hours: null, over_under: null, jobs: 0,'
              ' linked_jobs: 0}, {raken_read: false, last_week: null}), P.budgetTile(null),'
              ' bt({}, {last_week: {raken: "not_read"}})])')
    assert got[0] == {"budgeted": "1,200", "projected": "1,330", "over_under": "−130 h",
                      "over": True, "note": "2 of 4 linked jobs have a Raken budget read"}
    assert got[1]["over_under"] == "+12 h" and got[1]["over"] is False
    assert got[2] == {"budgeted": "—", "projected": "—", "over_under": "—",
                      "over": False, "note": "No linked job has a Raken budget read."}
    assert got[3]["note"] == "1 of 1 linked job has a Raken budget read"
    assert got[4]["note"] == "Raken has not been read."
    assert got[5] is None
    assert got[6]["note"] == got[0]["note"], "last week's state is not the Budget tile's"


def test_a_filtered_list_says_how_many_it_shows_and_why_it_is_empty():
    got = run(PROJECTS + 'out([P.listCountText(2, 5, "", ""), P.listCountText(1, 1, "", ""),'
              ' P.listCountText(2, 5, "pat", ""), P.listCountText(2, 5, "", "behind"),'
              ' P.noMatchText("pat", ""), P.noMatchText("", "over_budget"),'
              ' P.noMatchText("pat", "behind"), P.noMatchText("", "")])')
    assert got == ["5 jobs", "1 job", "2 of 5 jobs", "2 of 5 jobs",
                   "No job matches the search.", "No job is Over budget.",
                   "No Behind job matches the search.", ""]


def _strip_world(script):
    lifted = "\n".join(_lift(PVA, n) for n in ("focusTile", "setStatus", "clearStatus", "setView",
                                               "writeView"))
    return run(PVA_WORLD + lifted + "\n" + script)


# The strip's count tiles as the fake page holds them after a paint: each takes the focus.
TILES = """
$("pva-sum").querySelectorAll = () => ["on_plan", "behind", "over_budget", "not_linked"].map(
  (st) => ({ dataset: { st: st }, focus() { focused.push("tile:" + st); } }));
"""


def test_a_pressed_count_keeps_the_keyboard_focus():
    """Painting the strip rebuilds its buttons, so the one just pressed (Enter or Space) would take
    the focus with it to <body>; it goes back to the tile pressed, as "Show all jobs" does."""
    got = _strip_world(TILES + 'setStatus("behind"); setStatus("behind");'
                       'setStatus("over_budget"); clearStatus(); out(focused)')
    assert got == ["tile:behind", "tile:behind", "tile:over_budget", "tile:over_budget"]


def test_pressing_a_count_filters_pressing_it_again_or_show_all_clears_it():
    got = _strip_world('const seen = [];'
                       'setStatus("behind"); seen.push(VIEW.status);'
                       'setStatus("behind"); seen.push(VIEW.status);'
                       'setStatus("over_budget"); seen.push(VIEW.status);'
                       'setStatus("not_linked"); seen.push(VIEW.status);'
                       'clearStatus(); seen.push(VIEW.status);'
                       'const before = painted; clearStatus();'
                       'out([seen, painted - before, painted > 0])')
    assert got == [["behind", "", "over_budget", "not_linked", ""], 0, True]


def test_the_strip_is_drawn_from_the_core_and_its_counts_are_buttons_with_aria_pressed():
    """The tiles are real buttons (keyboard, screen reader) whose pressed state is aria-pressed;
    the list shows P.visibleProjects: the search box, the pressed count and (#819) the Work type and
    Foreman filters together."""
    html, js = _page(), _pva_js()
    assert 'id="pva-sum"' in html and 'id="pva-showall"' in html
    assert html.index('id="pva-sum"') < html.index('<table class="pva">'), "above the list"
    assert ">Show all jobs<" in html
    assert "P.countTiles(DATA, VIEW.status)" in js
    assert "P.lastWeekTile(DATA)" in js and "P.budgetTile(DATA)" in js
    assert "P.countsNote(DATA)" in js
    # A count pressed while Raken is not read must not empty the list: the core decides
    # (P.viewFilters applies statusFilter, #819).
    assert "const f = P.viewFilters(DATA, VIEW);" in js
    assert "P.visibleProjects(projects, f.q, f.status, f)" in js
    assert "P.listCountText(shown.length, projects.length, f.q, f.status, f)" in js
    assert "P.noMatchText(f.q, f.status, f)" in js and '$("pva-showall").hidden = !f.status;' in js
    assert 'aria-pressed="' + "' + (t.pressed" in js
    assert '<button type="button" class="sum-tile' in js
    assert '(t.disabled ? " disabled" : "")' in js, "an unknown count cannot be pressed"
    assert 'esc(t.count === null ? "—" : t.count)' in js, "an unknown count is a dash, never 0"
    i = js.index('$("pva-sum").addEventListener("click"')
    assert "setStatus(" in js[i:i + 200]
    assert '$("pva-showall").addEventListener("click", clearStatus)' in js
    # The two figure tiles are the job detail's own plan-beside-Raken pair (pairHtml, .pd-pair /
    # .pd-two), never a second copy of its markup or its rules.
    i = js.index("function paintSummary(")
    body = js[i:js.index("\n  }\n", i)]
    assert body.count("pairHtml({") == 2 and "figHtml" not in js
    for dup in (".sum-fig", ".sum-two"):
        assert dup not in html, "%s copies the detail's pair" % dup
    # Its values reach markup escaped (pairHtml escapes what it is given, once); nothing is styled
    # through a style attribute.
    for field in ("t.id", "t.label"):
        hits = list(re.finditer(r"(?<![\w.])" + re.escape(field) + r"\b", js))
        assert hits, field
        for m in hits:
            line = js[js.rfind("\n", 0, m.start()) + 1: js.find("\n", m.end())]
            if "innerHTML" in line or "'<" in line or '"<' in line:
                assert "esc(" + field in line, "%s reaches markup unescaped: %s" % (field, line)
    for field in ("lw.range", "lw.planned", "lw.actual", "lw.note", "bt.budgeted",
                  "bt.projected", "bt.note", "bt.over_under"):
        assert field in body and "esc(" + field not in js, "%s escaped twice" % field
    assert "esc(note)" in body, "the counts' note is escaped"
    assert 'style="' not in js and "style='" not in js
    for cls in (".sum", ".sum-tile", ".sum-note"):
        rule = re.search(r"\n\s*" + re.escape(cls) + r"\s*\{([^}]*)\}", html)
        assert rule, cls
        assert "#" not in rule.group(1), "%s uses a new hard-coded colour" % cls
    # DESIGN.md: a status is a 3-4px LEFT border, and Signal Red is the focus ring's only.
    tile = re.search(r"\n\s*\.sum-tile\s*\{([^}]*)\}", html).group(1)
    assert "border-left:3px" in tile and "border-top" not in tile
    pressed = re.search(r'\.sum-tile\[aria-pressed="true"\]\s*\{([^}]*)\}', html).group(1)
    assert "var(--red)" not in pressed and "var(--red-wash)" not in pressed


def test_the_page_and_the_server_name_the_same_summary_counts_and_last_week_states():
    """The strip's counts and last week's Raken states are plan_vs_actual.py's; the page names each
    once, so one renamed on one side fails here instead of reading as nothing."""
    import plan_vs_actual as pva
    got = run("out([P.SUMMARY_COUNTS, P.LAST_WEEK])")
    assert got[0] == list(pva.SUMMARY_COUNTS)
    assert got[1] == {"read": pva.LAST_WEEK_READ, "not_read": pva.LAST_WEEK_NOT_READ,
                      "not_covered": pva.LAST_WEEK_NOT_COVERED}
    assert sorted(got[1].values()) == sorted(pva.LAST_WEEK_STATES)
    core = CORE.read_text(encoding="utf-8")
    for name in ("function lastWeekTile(", "function budgetTile("):
        i = core.index(name)
        body = core[i:core.index("\n  }\n", i)]
        for literal in ('"read"', '"not_read"', '"not_covered"'):
            assert literal not in body, literal


# ── the Excel download (#785): a GET carrying the pressed count and the search text ─────────────
def test_the_download_link_carries_the_pressed_count_and_the_search_text():
    """The server applies the page's own filter to `status` and `q` (plan_vs_actual
    .visible_projects); test_plan_vs_actual_xlsx.py checks the two agree. Only the four counts go
    as a status; a blank search goes as none."""
    got = run('out([P.downloadHref("", ""), P.downloadHref("pat", ""),'
              ' P.downloadHref("", "behind"), P.downloadHref("example clinic & co", "over_budget"),'
              ' P.downloadHref("   ", "made_up"), P.downloadHref(null, null),'
              ' P.downloadHref("26.501#x?y=1", "not_linked")])')
    base = "/api/project-analytics/export.xlsx"
    assert got == [base, base + "?q=pat", base + "?status=behind",
                   base + "?status=over_budget&q=example%20clinic%20%26%20co", base, base,
                   base + "?status=not_linked&q=26.501%23x%3Fy%3D1"]


def test_the_search_is_cut_to_200_characters_on_the_page_as_on_the_server():
    """The server reads at most SEARCH_MAX characters of `q`; the box takes no more, and the page
    filters and downloads with the same 200, so a long search lists the same rows in both."""
    got = run('const q = "pat" + " ".repeat(300) + "zzz";'
              'const rows = [{job_number: "26.501", name: "Example Clinic", foreman: "Pat"}];'
              'out([P.SEARCH_MAX, P.filterProjects(rows, q).length,'
              ' P.downloadHref(q, "").length, P.downloadHref("a".repeat(250), "")])')
    base = "/api/project-analytics/export.xlsx"
    assert got[0] == 200
    assert got[1] == 1, "the words past the 200th character are not searched"
    assert got[2] == len(base + "?q=pat") + 197 * len("%20")
    assert got[3] == base + "?q=" + "a" * 200
    assert re.search(r'<input id="pva-q"[^>]*\smaxlength="200"', _page())


def test_the_downloaded_file_takes_the_servers_name_else_the_central_day():
    got = run('out([P.downloadName(\'attachment; filename="project-analytics-2026-11-18.xlsx"\','
              ' "2026-11-19"),'
              ' P.downloadName("", "2026-11-19"), P.downloadName(null, "2026-11-19"),'
              ' P.downloadName(\'attachment; filename="../evil.exe"\', "2026-11-19")])')
    assert got == ["project-analytics-2026-11-18.xlsx", "project-analytics-2026-11-19.xlsx",
                   "project-analytics-2026-11-19.xlsx", "project-analytics-2026-11-19.xlsx"]


def test_the_page_downloads_the_list_as_it_is_filtered_on_screen():
    """The button's address is the search box and the count the list is filtered by right now:
    none while the counts are not known, as the list itself ignores a pressed count then."""
    world = ("let VIEW = Object.assign(P.readView(''), {q: 'pat clinic', status: 'behind'});"
             "let DATA = {summary: {raken_read: true, counts: {behind: 1}}};")
    lifted = _lift(PVA, "downloadPath")
    got = run(world + lifted + "\nconst a = downloadPath();"
              "DATA = {summary: {raken_read: false, counts: null}}; const b = downloadPath();"
              "VIEW = P.readView(''); const c = downloadPath(); out([a, b, c])")
    base = "/api/project-analytics/export.xlsx"
    assert got == [base + "?status=behind&q=pat%20clinic", base + "?q=pat%20clinic", base]


def test_the_download_is_a_get_and_keeps_refresh_now_the_pages_one_write():
    html, js = _page(), _pva_js()
    # A button, not a link: every /api route needs the sign-in header, so a link opened, saved or
    # copied without the script would fetch a refusal and save it as the file.
    assert '<button type="button" id="pva-download" class="btn">Download</button>' in html
    assert "export.xlsx" not in html and 'setAttribute("href"' not in js
    assert "btn.disabled = true;" in js and "btn.disabled = false;" in js
    assert "P.downloadHref(" in js and "api(downloadPath())" in js
    assert js.count("method:") == 1 and js.count('"POST"') == 1, "the download is not a write"
