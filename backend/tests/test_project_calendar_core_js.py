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
  mobilization:null, crew_lead:null, is_punch:false, prevailing_wage:false, night_work:false,
  color_id:null, color:null, is_duration:false, start:"", last_day:"", workdays:0,
  deadline:null, project:null, html_link:null}, o);
const EVENTS = [
  ev({id:"a", title:"26.125, Acme Clinic Psych (6) (Pat)", name:"Acme Clinic Psych",
      job_number:"26.125", crew_size:6, crew_lead:"Pat", color_id:"11", color:"#d50000",
      is_duration:true, start:"2026-11-10", last_day:"2026-11-19", deadline:"2026-11-19"}),
  ev({id:"b", title:"Example Diner (4)", name:"Example Diner", crew_size:4, color_id:"7",
      color:"#039be5", start:"2026-11-11", last_day:"2026-11-12"}),
  ev({id:"c", title:"Example Punch - (1) (Lee)", name:"Example Punch", crew_size:1,
      crew_lead:"Lee", is_punch:true, start:"2026-11-13", last_day:"2026-11-13"}),
  ev({id:"d", title:"G25.110, The Example Lofts (3rd and 2nd) - 2nd Mob - (PW) (8) (Sam)",
      name:"The Example Lofts (3rd and 2nd)", job_number:"G25.110", crew_size:8,
      mobilization:2, crew_lead:"Sam", prevailing_wage:true, color_id:"2", color:"#33b679",
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


def test_upcoming_deadlines_are_durations_from_today_on_soonest_first():
    """Only red Durations carry a Deadline. One that has passed is not "upcoming"."""
    got = run(EVENTS + 'const extra = [ev({id:"e", name:"Example Plaza", title:"Example Plaza (6)",'
              ' color_id:"11", is_duration:true, start:"2026-11-02", last_day:"2026-11-12",'
              ' deadline:"2026-11-12"}),'
              ' ev({id:"f", name:"Beta Hall", title:"Beta Hall", color_id:"11", is_duration:true,'
              ' start:"2026-11-03", last_day:"2026-11-11", deadline:"2026-11-11"}),'
              ' ev({id:"g", name:"Alpha Hall", title:"Alpha Hall", color_id:"11", is_duration:true,'
              ' start:"2026-11-16", last_day:"2026-11-19", deadline:"2026-11-19"})];'
              'out(P.upcomingDeadlines(EVENTS.concat(extra), "2026-11-12")'
              '  .map(r => [r.ev.id, r.deadline, r.status, r.days]))')
    # Beta Hall (Nov 11) has passed. Acme and Alpha share Nov 19, so they are ordered by name.
    assert got == [["e", "2026-11-12", "today", 0],
                   ["a", "2026-11-19", "upcoming", 7],
                   ["g", "2026-11-19", "upcoming", 7]]


# ── colour ──────────────────────────────────────────────────────────────
def test_colour_comes_from_the_api_then_googles_palette_then_nothing():
    got = run('out([P.colorOf({color:"#D50000"}), P.colorOf({color_id:"5"}),'
              ' P.colorOf({color_id:11}), P.colorOf({}), P.colorOf({color_id:"99"}),'
              ' P.colorOf({color:"red; background:url(x)"})])')
    assert got == ["#d50000", "#f6bf26", "#d50000", None, None, None]


def test_only_tomato_is_a_duration():
    got = run('out([P.isDuration({color_id:"11"}), P.isDuration({color_id:"4"}),'
              ' P.isDuration({color_id:"11", is_duration:false}), P.isDuration({is_duration:true}),'
              ' P.isDuration(null)])')
    assert got == [True, False, False, True, False]


def test_text_on_a_bar_stays_readable():
    """White on Tomato and on dark blue; dark ink on Google's yellow."""
    got = run('out([P.textOn("#d50000"), P.textOn("#3f51b5"), P.textOn("#f6bf26"),'
              ' P.textOn("nope")])')
    assert got == ["#ffffff", "#ffffff", "#1b1c1c", None]


# ── what a bar says ─────────────────────────────────────────────────────
def test_a_bar_reads_name_then_job_number_crew_size_and_crew_lead():
    got = run(EVENTS + 'out([P.barParts(EVENTS[0]), P.barParts(EVENTS[1]),'
              ' P.barParts({title:"Example Patch?"}), P.barParts({})])')
    assert got == [{"name": "Acme Clinic Psych", "meta": "26.125 · 6 crew · Pat"},
                   {"name": "Example Diner", "meta": "4 crew"},
                   {"name": "Example Patch?", "meta": ""},
                   {"name": "Untitled", "meta": ""}]


def test_flags_are_named_in_plain_words():
    got = run(EVENTS + 'out([P.flagsOf(EVENTS[0]), P.flagsOf(EVENTS[2]), P.flagsOf(EVENTS[3]),'
              ' P.flagsOf(ev({night_work:true, mobilization:1})), P.ordinal(3), P.ordinal(11)])')
    assert got == [["Duration"], ["Punch"], ["2nd Mobilization", "Prevailing wage"],
                   ["1st Mobilization", "Night work"], "3rd", "11th"]


# ── filtering ───────────────────────────────────────────────────────────
def test_search_matches_title_name_job_number_and_crew_lead_case_blind():
    got = run(EVENTS + 'const ids = (o) => P.filterEvents(EVENTS, o).map(e => e.id);'
              'out([ids({q:"acme"}), ids({q:"G25.110"}), ids({q:"lee"}), ids({q:"pw"}),'
              ' ids({q:"example lofts"}), ids({q:"lofts diner"}), ids({q:"   "}), ids({})])')
    assert got == [["a"], ["d"], ["c"], ["d"], ["d"], [], ["a", "b", "c", "d"], ["a", "b", "c", "d"]]


def test_durations_only_keeps_the_red_bars():
    got = run(EVENTS + 'out([P.filterEvents(EVENTS,{durationsOnly:true}).map(e => e.id),'
              ' P.filterEvents(EVENTS,{durationsOnly:true, q:"diner"}).length,'
              ' P.filterEvents(null,{}).length, P.filterEvents([null, 3, EVENTS[1]],{}).length])')
    assert got == [["a"], 0, 0, 1]


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
    for field in ("parts.name", "parts.meta", "ev.job_number", "ev.crew_lead", "ev.project.name"):
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
    assert re.search(r'navItem\("/project-calendar\.html",\s*"[^"]+",\s*"Project Calendar"\)', src)


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
def test_upcoming_deadlines_stay_inside_the_window_they_are_labelled_with():
    """The side list reads "Next 60 days". A Duration that overlaps the window but ends on day 106
    must not appear, and two Deadlines on the same far day are treated the same."""
    got = run(EVENTS + 'const far = [ev({id:"long", name:"Long Job", color_id:"11", is_duration:true,'
              ' start:"2026-11-02", last_day:"2027-02-26", deadline:"2027-02-26"}),'
              ' ev({id:"near", name:"Near Job", color_id:"11", is_duration:true,'
              ' start:"2026-11-02", last_day:"2027-01-10", deadline:"2027-01-10"})];'
              'out([P.upcomingDeadlines(far, "2026-11-12", 60).map(r => r.ev.id),'
              '     P.upcomingDeadlines(far, "2026-11-12").map(r => r.ev.id)])')
    assert got == [["near"], ["near", "long"]]


def test_switching_view_length_keeps_the_days_being_looked_at():
    """Paged forward in two weeks to a mostly-February range, Month must show February."""
    got = run('out([P.focusDay({from:"2027-01-31", to:"2027-02-13"}, "2026-11-12"),'
              '     P.focusDay({from:"2026-11-08", to:"2026-11-21"}, "2026-11-12"),'
              '     P.focusDay({from:"2026-11-01", to:"2026-12-12"}, "2026-12-20")])')
    assert got == ["2027-02-06", "2026-11-12", "2026-11-21"]


def test_the_deadline_list_says_when_it_could_not_load():
    js = _page_js()
    assert "Couldn't load Deadlines. " in js
    assert "P.upcomingDeadlines(visible(SIDE.events), TODAY, SIDE_DAYS)" in js
    assert "P.centralStamp(SIDE.fetched_at)" in js


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
    the calendar" box, and the Deadlines list must not say "Couldn't load"."""
    js = _page_js()
    assert "if (current.notice) notice.push(String(current.notice));" in js
    i = js.index("if (!events.length && current.error)")
    assert "notice" not in js[i:js.index("\n", i)], "the failure box keys on a notice"
    j = js.index("Couldn't load Deadlines. \" + esc(SIDE.error)")
    assert "notice" not in js[js.rfind("\n", 0, j - 80):j]
    assert "cached.notice" in js, "a changed notice must repaint"
