// Project Calendar engine: pure functions, no DOM, no fetch.
// Externalized (CSP: no inline scripts). Do not add inline scripts.
//
// WHAT THIS FILE KNOWS. The Project Calendar is a read-only view of the crews' Google calendar,
// "Treadwell Projects". The server has already parsed each event's free-text title into a Job
// number, Crew size, Mobilization and Foreman, and already turned Google's dates into inclusive
// Central days ("start" and "last_day", both "YYYY-MM-DD"). What is left for the page is layout and
// arithmetic, and all of it lives here so it can be pinned under node
// (backend/tests/test_project_calendar_core_js.py):
//
//   * laying a multi-day Mobilization across the visible weeks, so a bar spans its day columns
//     and wraps onto the next week row instead of being drawn once per day;
//   * stacking bars that overlap into lanes, so two crews on the same days never draw on top of
//     each other;
//   * workdays (Monday to Friday; a weekend never counts) and workdays left from a Central today;
//   * whether a Deadline has passed, is today, or is still ahead;
//   * the text filter, and the Work type a bar's colour stands for;
//   * which of the two tabs (Plan vs Actual, Schedule) the address opens, and the wording and
//     search of the Plan vs Actual rows, which the SERVER builds (GET /api/project-analytics).
//
// DATES. Every day here is a "YYYY-MM-DD" string on the America/Chicago calendar, and the
// arithmetic is calendar-core.js's (TWCal): parse as UTC midnight, step in whole UTC days, so no
// daylight-saving change can produce a 23- or 25-hour day. The page loads calendar-core.js first;
// under node this file requires it from beside itself. The one place a clock is read is
// centralToday(), and it reads it through Intl with timeZone America/Chicago: the dev box runs about
// thirteen hours ahead of Central, so a naive local date is tomorrow for half of every day.
(function (root, factory) {
  var K = root && root.TWCal;
  if (!K && typeof require === "function") K = require("./calendar-core.js");
  var api = factory(K);
  if (root) root.TWProjCal = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;   // node, for tests
})(typeof self !== "undefined" ? self : this, function (K) {
  "use strict";

  var BIZ_TZ = "America/Chicago";

  // The two views this page offers. A one-week view would cut nearly every Mobilization in half,
  // so it is left out; the ids are calendar-core's, so its range and paging functions apply as-is.
  var MODES = [
    { id: "two", label: "Two weeks" },
    { id: "month", label: "Month" },
  ];

  // Google's own event palette, the fallback when an event arrives without `color` filled in.
  // Every bar is a job's Duration; its colour is the Work type (Darrin, Operations, 2026-11-12).
  var GOOGLE_COLORS = {
    "1": "#7986cb", "2": "#33b679", "3": "#8e24aa", "4": "#e67c73", "5": "#f6bf26",
    "6": "#f4511e", "7": "#039be5", "8": "#616161", "9": "#3f51b5", "10": "#0b8043",
    "11": "#d50000",
  };
  // The words shown for a job whose colour has no Work type (the server sends work_type: null).
  // Which colour is which Work type is the server's alone: see `work_types` in each response.
  var WORK_TYPE_UNKNOWN_LABEL = "Work type unknown";

  // ── days ─────────────────────────────────────────────────────────────
  var _dayFmt = null;
  /** Today on the Central calendar. `now` is injectable so tests can pin the clock. */
  function centralToday(now) {
    if (!_dayFmt) {
      // "en-CA" formats as YYYY-MM-DD.
      _dayFmt = new Intl.DateTimeFormat("en-CA", {
        timeZone: BIZ_TZ, year: "numeric", month: "2-digit", day: "2-digit",
      });
    }
    return _dayFmt.format(now || new Date());
  }

  function validDay(day) {
    return typeof day === "string" && !isNaN(K.ms(day));
  }

  /** The event's inclusive span, or null when it has no usable start.
   *  A missing or impossible last day is read as a one-day event rather than dropped: the page
   *  must never lose an event the server sent. */
  function spanOf(ev) {
    if (!ev || !validDay(ev.start)) return null;
    var last = validDay(ev.last_day) && K.diffDays(ev.start, ev.last_day) >= 0
      ? ev.last_day : ev.start;
    return { start: ev.start, last: last };
  }

  /** Monday to Friday. */
  function isWorkday(day) {
    var w = K.dow(day);
    return w >= 1 && w <= 5;
  }

  /** Workdays from `a` to `b`, both inclusive. 0 when b is before a or either is malformed.
   *  Counted with whole weeks plus a short walk, so a year-long event costs nothing. */
  function workdaysBetween(a, b) {
    if (!validDay(a) || !validDay(b)) return 0;
    var total = K.diffDays(a, b) + 1;
    if (total <= 0) return 0;
    var weeks = Math.floor(total / 7);
    var count = weeks * 5;
    var d = K.addDays(a, weeks * 7);
    for (var i = 0; i < total % 7; i++) {
      if (isWorkday(d)) count++;
      d = K.addDays(d, 1);
    }
    return count;
  }

  /** Workdays the event covers, start to last day. */
  function workdaysOf(ev) {
    var s = spanOf(ev);
    return s ? workdaysBetween(s.start, s.last) : 0;
  }

  /** Workdays still ahead of the crew on this event, counting today if today is a workday.
   *  Before the event starts this is all of its workdays; after its last day it is 0, never
   *  negative. */
  function workdaysLeft(ev, today) {
    var s = spanOf(ev);
    if (!s || !validDay(today)) return 0;
    if (K.diffDays(today, s.last) < 0) return 0;
    var from = K.diffDays(s.start, today) > 0 ? today : s.start;
    return workdaysBetween(from, s.last);
  }

  /** "overdue" (the Deadline has passed), "today", "upcoming", or null when there is none. */
  function deadlineStatus(deadline, today) {
    if (!validDay(deadline) || !validDay(today)) return null;
    var n = K.diffDays(today, deadline);
    if (n < 0) return "overdue";
    if (n === 0) return "today";
    return "upcoming";
  }

  /** Whole calendar days from today to the Deadline (negative once it has passed). */
  function daysUntil(deadline, today) {
    if (!validDay(deadline) || !validDay(today)) return null;
    return K.diffDays(today, deadline);
  }

  // ── colour ───────────────────────────────────────────────────────────
  /** The bar colour: the server's `color`, else Google's palette for `color_id`, else null
   *  (the page then draws its neutral token). Anything that is not a plain #rrggbb is refused,
   *  because the value ends up in a style property. */
  function colorOf(ev) {
    var c = ev && typeof ev.color === "string" ? ev.color.trim().toLowerCase() : "";
    if (/^#[0-9a-f]{6}$/.test(c)) return c;
    var id = ev && ev.color_id != null ? String(ev.color_id) : "";
    return GOOGLE_COLORS[id] || null;
  }

  /** The job's Work type as the server worked it out from the bar's colour, or "Work type
   *  unknown" when the server sent none. */
  function workTypeOf(ev) {
    return ev && ev.work_type ? String(ev.work_type) : WORK_TYPE_UNKNOWN_LABEL;
  }

  /** The text colour that reads best on `hex`: dark ink or white, whichever has the higher
   *  contrast (WCAG relative luminance). Google's yellow and light green need dark text. */
  function textOn(hex) {
    var m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || "");
    if (!m) return null;
    var lin = function (h) {
      var c = parseInt(h, 16) / 255;
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    };
    var L = 0.2126 * lin(m[1]) + 0.7152 * lin(m[2]) + 0.0722 * lin(m[3]);
    var INK_L = 0.0118;                       // #1b1c1c
    var withWhite = 1.05 / (L + 0.05);
    var withInk = (L + 0.05) / (INK_L + 0.05);
    return withInk > withWhite ? "#1b1c1c" : "#ffffff";
  }

  // ── what a bar says ──────────────────────────────────────────────────
  /** The compact pieces of a bar: the tidied name first, then Job number, Crew size and
   *  Foreman. The raw title is never lost; the page puts it in the bar's title attribute. */
  function barParts(ev) {
    var name = String((ev && (ev.name || ev.title)) || "").trim() || "Untitled";
    var meta = [];
    if (ev && ev.job_number) meta.push(String(ev.job_number));
    if (ev && typeof ev.crew_size === "number" && isFinite(ev.crew_size)) {
      meta.push(ev.crew_size + " crew");
    }
    if (ev && ev.foreman) meta.push(String(ev.foreman));
    return { name: name, meta: meta.join(" · ") };
  }

  /** The flags worth a word in the details panel, in a fixed order. */
  function flagsOf(ev) {
    var out = [];
    if (!ev) return out;
    var mob = mobilizationLabel(ev.mobilization);
    if (mob) out.push(mob);
    if (ev.is_punch) out.push("Punch");
    return out.concat(jobFlags(ev));
  }

  /** "2nd Mobilization" for a Mobilization number above zero, else "". */
  function mobilizationLabel(n) {
    return typeof n === "number" && n > 0 ? ordinal(n) + " Mobilization" : "";
  }

  /** The flags an event or a whole job carries, in a fixed order: the one list both the Schedule's
   *  details panel (flagsOf) and Plan vs Actual's job detail (detailFlags) say. */
  function jobFlags(x) {
    var out = [];
    if (x && x.prevailing_wage) out.push("Prevailing wage");
    if (x && x.night_work) out.push("Night work");
    return out;
  }

  function ordinal(n) {
    var s = ["th", "st", "nd", "rd"], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
  }

  // ── filtering ────────────────────────────────────────────────────────
  /** Text search across the raw title, the tidied name, Job number, Foreman and the matched
   *  Project's name. Every word typed must match somewhere, in any order. */
  function matches(ev, q) {
    var words = String(q || "").toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) return true;
    var hay = [ev.title, ev.name, ev.job_number, ev.foreman,
               ev.project && ev.project.name]
      .map(function (v) { return String(v == null ? "" : v).toLowerCase(); }).join(" \u0001 ");
    for (var i = 0; i < words.length; i++) if (hay.indexOf(words[i]) < 0) return false;
    return true;
  }

  function filterEvents(events, opts) {
    var o = opts || {};
    return (Array.isArray(events) ? events : []).filter(function (ev) {
      if (!ev || typeof ev !== "object") return false;
      return matches(ev, o.q);
    });
  }

  /** Start, then title, then id: the server's order, re-applied so the page never depends on it. */
  function byStartThenTitle(a, b) {
    var sa = String(a.start || ""), sb = String(b.start || "");
    if (sa !== sb) return sa < sb ? -1 : 1;
    var ta = String(a.title || ""), tb = String(b.title || "");
    if (ta !== tb) return ta < tb ? -1 : 1;
    return String(a.id || "") < String(b.id || "") ? -1 : (a.id === b.id ? 0 : 1);
  }

  // ── layout ───────────────────────────────────────────────────────────
  /** Lay events out across the weeks of `range` (calendar-core's rangeFor: whole Sunday-first
   *  weeks).
   *
   *  Returns one entry per week row: its seven days, the bar segments that fall in it, and how
   *  many lanes it needs. A segment is the part of one event inside one week:
   *    col     0..6, the first column it covers in this row
   *    span    how many columns it covers
   *    lane    0-based stacking row inside the week
   *    starts  true when the event really begins here (false: it continues from the row above)
   *    ends    true when the event really ends here  (false: it carries on to the next row)
   *
   *  Lanes are packed greedily per week, longest-running first: the events carried over from the
   *  week before take the top lanes (they start in column 0), so a Mobilization that wraps keeps
   *  its place near the top of both rows. An event with no usable start is left out of the grid
   *  and counted in `unplaced`, never thrown on. */
  function layout(events, range) {
    var days = (range && range.days) || [];
    var list = (Array.isArray(events) ? events.slice() : []).filter(Boolean);
    list.sort(byStartThenTitle);
    var weeks = [], unplaced = 0;
    var spans = list.map(function (ev) {
      var s = spanOf(ev);
      if (!s) unplaced++;
      return s;
    });
    for (var w = 0; w + 7 <= days.length; w += 7) {
      var wDays = days.slice(w, w + 7);
      var wFrom = wDays[0], wTo = wDays[6];
      var segs = [];
      for (var i = 0; i < list.length; i++) {
        var s = spans[i];
        if (!s) continue;
        if (K.diffDays(s.last, wFrom) > 0 || K.diffDays(wTo, s.start) > 0) continue;
        var segStart = K.diffDays(s.start, wFrom) > 0 ? wFrom : s.start;
        var segEnd = K.diffDays(wTo, s.last) > 0 ? wTo : s.last;
        segs.push({
          ev: list[i],
          col: K.diffDays(wFrom, segStart),
          span: K.diffDays(segStart, segEnd) + 1,
          lane: -1,
          starts: segStart === s.start,
          ends: segEnd === s.last,
          order: i,
        });
      }
      segs.sort(function (a, b) {
        return (a.col - b.col) || (b.span - a.span) || (a.order - b.order);
      });
      var laneEnds = [];                         // last column taken in each lane
      for (var j = 0; j < segs.length; j++) {
        var sg = segs[j], placed = false;
        for (var l = 0; l < laneEnds.length; l++) {
          if (laneEnds[l] < sg.col) { sg.lane = l; laneEnds[l] = sg.col + sg.span - 1; placed = true; break; }
        }
        if (!placed) { sg.lane = laneEnds.length; laneEnds.push(sg.col + sg.span - 1); }
      }
      segs.forEach(function (sg) { delete sg.order; });
      weeks.push({ days: wDays, segments: segs, lanes: laneEnds.length });
    }
    return { weeks: weeks, unplaced: unplaced };
  }

  /** The day the viewer is looking at in `range`: today when it is in view, otherwise the
   *  middle day. Switching between two weeks and a month re-anchors on this, so the new view
   *  holds the days that were on screen, not the month of the range's first Sunday. */
  function focusDay(range, today) {
    if (!range || !validDay(range.from) || !validDay(range.to)) return today;
    if (validDay(today) && range.from <= today && today <= range.to) return today;
    return K.addDays(range.from, Math.floor(K.diffDays(range.from, range.to) / 2));
  }

  // ── the two tabs ─────────────────────────────────────────────────────
  // Plan vs Actual is the default; the address "#schedule" opens the Schedule (the calendar).
  var TABS = [
    { id: "pva", label: "Plan vs Actual" },
    { id: "schedule", label: "Schedule" },
  ];

  function tabFromHash(hash) {
    return String(hash || "").replace(/^#/, "").toLowerCase() === "schedule" ? "schedule" : "pva";
  }

  // ── Plan vs Actual rows (the server builds them; these only word and filter them) ──
  // A row's `timing` and its Raken `state`: values backend/plan_vs_actual.py names too
  // (TIMING_*, RAKEN_NOT_CONNECTED). tests/test_project_calendar_core_js.py holds the two together,
  // so a state added on one side only fails there.
  var TIMING = { starts: "starts", running: "running", finished: "finished" };
  // A row's Raken state, its statuses and why it is Not linked (#782): backend/raken_actuals.py
  // names the same values (ROW_STATES, STATUSES, REASON_*); tests/test_project_calendar_core_js.py
  // holds the two together.
  var RAKEN = {
    not_connected: "not_connected", expired: "expired", not_provisioned: "not_provisioned",
    unreachable: "unreachable", not_refreshed: "not_refreshed", linked: "linked",
    not_linked: "not_linked",
  };
  var STATUS = {
    behind: "behind", over_budget: "over_budget", on_plan: "on_plan", not_linked: "not_linked",
  };
  // A linked row's Budget pair (#783): raken_actuals.py's BUDGET_*. Shown; none (Raken has no
  // budget for the job); not read (its insights could not be read, or the read predates them).
  var BUDGET = { shown: "shown", none: "none", not_read: "not_read" };
  var REASON = {
    no_job_number: "no_job_number", no_raken_project: "no_raken_project", duplicate: "duplicate",
  };
  var RAKEN_NOT_CONNECTED = RAKEN.not_connected;

  // The most of the search box that is read: the box takes no more (maxlength), and the server
  // reads no more of the Excel download's `q` (plan_vs_actual.SEARCH_MAX).
  var SEARCH_MAX = 200;

  /** The search box: every word typed must match the Job number, the name, the Foreman or the
   *  Work type (as the page words it, so "unknown" finds the jobs with none). */
  function filterProjects(projects, q) {
    var words = String(q || "").slice(0, SEARCH_MAX).toLowerCase().split(/\s+/).filter(Boolean);
    return (Array.isArray(projects) ? projects : []).filter(function (p) {
      if (!p || typeof p !== "object") return false;
      if (!words.length) return true;
      var hay = [p.job_number, p.name, p.foreman, workTypeOf(p)]
        .map(function (v) { return String(v == null ? "" : v).toLowerCase(); }).join(" \u0001 ");
      for (var i = 0; i < words.length; i++) if (hay.indexOf(words[i]) < 0) return false;
      return true;
    });
  }

  /** The rows carrying `status` (one of STATUS), or every row when there is none: a count in the
   *  summary strip (#788) pressed. A row Behind and Over budget is in both lists. */
  function filterByStatus(projects, status) {
    var rows = (Array.isArray(projects) ? projects : []).filter(function (p) {
      return p && typeof p === "object";
    });
    if (!status) return rows;
    return rows.filter(function (p) {
      return Array.isArray(p.statuses) && p.statuses.indexOf(status) >= 0;
    });
  }

  /** The list as shown: the search box, the pressed count, and the Work type and Foreman filters
   *  (#819, `filters` {work_type, foreman}), all together. Each is applied as given: the page
   *  passes the ones in force (viewFilters), as it passes statusFilter's status. */
  function visibleProjects(projects, q, status, filters) {
    return filterByFields(filterByStatus(filterProjects(projects, q), status), filters);
  }

  // ── the Work type and Foreman filters (#819) ──
  // plan_vs_actual.py's work_type_filter, foreman_filter and visible_projects are the same rule on
  // the server (the Excel download); tests/test_plan_vs_actual_xlsx.py runs both on the same input.
  // The value "No foreman" stands for in the Foreman select and the address. No Foreman can be
  // written so on the calendar: a Foreman is the inside of a title's last parenthesis and starts
  // with a letter (project_calendar._NAME_RE).
  var FOREMAN_NONE = "(none)";
  var NO_FOREMAN_LABEL = "No foreman";

  /** A Foreman, a Work type or a filter value as compared: trimmed, case ignored. "" for none.
   *  plan_vs_actual._key is the same. */
  function filterKey(v) {
    return String(v == null ? "" : v).trim().toLowerCase();
  }

  /** The rows of the Work type `filters.work_type` (matched as the row's sub-line words it,
   *  workTypeOf, so "Work type unknown" picks the rows with none) and the Foreman
   *  `filters.foreman` (FOREMAN_NONE picks the rows with none). Case and surrounding spaces are
   *  ignored; an empty value is no filter. */
  function filterByFields(projects, filters) {
    var f = filters && typeof filters === "object" ? filters : {};
    var wt = filterKey(f.work_type);
    var fm = filterKey(f.foreman);
    return (Array.isArray(projects) ? projects : []).filter(function (p) {
      if (!p || typeof p !== "object") return false;
      if (wt && filterKey(workTypeOf(p)) !== wt) return false;
      if (fm === FOREMAN_NONE) return !filterKey(p.foreman);
      return !fm || filterKey(p.foreman) === fm;
    });
  }

  /** The Work type select's options: the server's colour-to-Work-type list (`work_types` in the
   *  response), in its order, then the words for any other colour or none. */
  function workTypeOptions(data) {
    var seen = Object.create(null);
    var out = [];
    var list = data && Array.isArray(data.work_types) ? data.work_types : [];
    list.concat([{ name: WORK_TYPE_UNKNOWN_LABEL }]).forEach(function (w) {
      var name = w && typeof w.name === "string" ? w.name.trim() : "";
      if (!name || seen[name.toLowerCase()]) return;
      seen[name.toLowerCase()] = true;
      out.push({ value: name, label: name });
    });
    return out;
  }

  /** The Foreman select's options: the distinct Foremen of the jobs in the list (trimmed, case
   *  ignored, the spelling first met kept), sorted without regard to case, then "No foreman" when
   *  a job has none. */
  function foremanOptions(projects) {
    var seen = Object.create(null);
    var out = [];
    var none = false;
    (Array.isArray(projects) ? projects : []).forEach(function (p) {
      if (!p || typeof p !== "object") return;
      var name = String(p.foreman == null ? "" : p.foreman).trim();
      if (!name) { none = true; return; }
      if (seen[name.toLowerCase()]) return;
      seen[name.toLowerCase()] = true;
      out.push({ value: name, label: name });
    });
    out.sort(function (a, b) {
      var x = a.value.toLowerCase(), y = b.value.toLowerCase();
      return x < y ? -1 : (x > y ? 1 : 0);
    });
    if (none) out.push({ value: FOREMAN_NONE, label: NO_FOREMAN_LABEL });
    return out;
  }

  /** The option `value` stands for, in the option's own spelling, or "" when no option is it. */
  function pickOption(options, value) {
    var k = filterKey(String(value == null ? "" : value).slice(0, SEARCH_MAX));
    if (!k) return "";
    for (var i = 0; i < options.length; i++) {
      if (options[i].value.toLowerCase() === k) return options[i].value;
    }
    return "";
  }

  /** The Work type filtering the list: `value` when the select offers it, else none. */
  function workTypeFilter(data, value) {
    return pickOption(workTypeOptions(data), value);
  }

  /** The Foreman filtering the list: `value` when the select offers it, else none. */
  function foremanFilter(data, value) {
    return pickOption(foremanOptions(data && data.projects), value);
  }

  /** Workdays left, or "Starts <date>" before the job starts and "Finished" after its Deadline,
   *  so the count is never negative. */
  function leftLabel(p) {
    if (!p) return "";
    if (p.timing === TIMING.starts) return "Starts " + dayLong(p.start);
    if (p.timing === TIMING.finished) return "Finished";
    var n = typeof p.workdays_left === "number" ? p.workdays_left : 0;
    return n + " workday" + (n === 1 ? "" : "s") + " left";
  }

  /** A whole number with thousands separators, or a dash when there is none. */
  function numLabel(n) {
    if (typeof n !== "number" || !isFinite(n)) return "—";
    return Math.round(n).toLocaleString("en-US");
  }

  // ── the Raken side (#782): the server's last "Refresh now" read, set beside each row ──
  // The states, statuses and reasons are RAKEN, STATUS and REASON above.
  // Statuses are flags (#783): a job Behind and Over budget shows both, in this order.
  var STATUS_LABELS = [[STATUS.not_linked, "Not linked"], [STATUS.behind, "Behind"],
    [STATUS.over_budget, "Over budget"], [STATUS.on_plan, "On plan"]];

  function rakenOf(p) {
    return p && p.raken && typeof p.raken === "object" ? p.raken : {};
  }

  /** Why a row's Raken cells are empty, in a few words; "" for a linked row (its numbers speak),
   *  the reason for a Not linked one. */
  function rakenLabel(p) {
    var st = rakenOf(p).state;
    if (!st || st === RAKEN_NOT_CONNECTED) return "Connect Raken to compare";
    if (st === RAKEN.linked) return "";
    if (st === RAKEN.not_linked) return notLinkedNote(p);
    if (st === RAKEN.expired) return "Raken sign-in expired";
    if (st === RAKEN.not_provisioned) return "Raken not turned on yet";
    if (st === RAKEN.unreachable) return "Raken not reached";
    if (st === RAKEN.not_refreshed) return "Press Refresh now";
    return "—";
  }

  /** A number with thousands separators and at most one decimal, or a dash. */
  function decLabel(n) {
    if (typeof n !== "number" || !isFinite(n)) return "—";
    return (Math.round(n * 10) / 10).toLocaleString("en-US", { maximumFractionDigits: 1 });
  }

  /** The Raken side of a row's pairs: days clocked in, average on site a day, Actual hours.
   *  Dashes unless the row is linked. Behind compares days clocked in with the booked days the
   *  read covered (`days_booked`); when that differs from the row's Workdays booked so far, the
   *  days read "2 of 2" with `days_note` "through Nov 17", so the pair and the chip agree. */
  function rakenCells(p) {
    var r = rakenOf(p);
    if (r.state !== RAKEN.linked) return { days: "—", days_note: "", on_site: "—", hours: "—" };
    var days = numLabel(r.days_clocked);
    var note = "";
    if (typeof r.days_booked === "number" && r.days_booked !== (p && p.workdays_so_far)) {
      days += " of " + numLabel(r.days_booked);
      note = validDay(r.through) ? "through " + K.dayLabel(r.through, false) : "";
    }
    return { days: days, days_note: note, on_site: decLabel(r.avg_on_site),
             hours: decLabel(r.actual_hours) };
  }

  /** Over/under in whole hours, signed: "+12 h" under budget, "−130 h" (a real minus) over it,
   *  "0 h" on it, a dash when there is none. Under an hour either way reads "−<1 h" / "+<1 h",
   *  never "0 h": the server calls any Over/under below zero Over budget. */
  function overUnderLabel(n) {
    if (typeof n !== "number" || !isFinite(n)) return "—";
    if (n === 0) return "0 h";
    var r = Math.abs(Math.round(n));
    return (n > 0 ? "+" : "−") + (r === 0 ? "<1" : r.toLocaleString("en-US")) + " h";
  }

  /** A pair's small bar: the plan as a tick, Raken as the fill, both as percentages of the
   *  longer of the two (one decimal). `over` when Raken is past the plan. null when either is
   *  missing or negative, or both are zero: no bar beats a misleading one. */
  function pairBar(plan, raken) {
    var ok = function (n) { return typeof n === "number" && isFinite(n) && n >= 0; };
    if (!ok(plan) || !ok(raken)) return null;
    var scale = Math.max(plan, raken);
    if (scale <= 0) return null;
    var pct = function (n) { return Math.round(n / scale * 1000) / 10; };
    return { fill: pct(raken), tick: pct(plan), over: raken > plan };
  }

  /** The Hours pair's bar: Planned hours (the tick) against Actual hours (the fill). Linked
   *  rows only. */
  function hoursBar(p) {
    var r = rakenOf(p);
    if (r.state !== RAKEN.linked) return null;
    return pairBar(p.planned_hours, r.actual_hours);
  }

  /** The Budget pair (#783): Projected total hours against Budgeted hours, with Over/under and
   *  its bar (Budgeted hours the tick, Projected total hours the fill). Dashes unless the row is
   *  linked and Raken has a budget; `note` says why (no Raken budget, not read) or that Raken's
   *  projection is below the time-card Actual hours. */
  function budgetCells(p) {
    var r = rakenOf(p);
    var out = { shown: false, projected: "—", budgeted: "—", over_under: "—",
      over: false, note: "", bar: null };
    if (r.state !== RAKEN.linked) return out;
    if (r.budget === BUDGET.none) { out.note = "No Raken budget"; return out; }
    if (r.budget !== BUDGET.shown) { out.note = "Raken's budget not read"; return out; }
    out.shown = true;
    out.projected = numLabel(r.projected_total_hours);
    out.budgeted = numLabel(r.budgeted_hours);
    out.over_under = overUnderLabel(r.over_under);
    out.over = typeof r.over_under === "number" && r.over_under < 0;
    out.note = r.projection_below_actual === true
      ? "Raken's projection covers only the work in its budget" : "";
    out.bar = pairBar(r.budgeted_hours, r.projected_total_hours);
    return out;
  }

  /** The row's status flags as chips, Not linked first. Only flags the page knows. */
  function statusChips(p) {
    var st = p && Array.isArray(p.statuses) ? p.statuses : [];
    var out = [];
    STATUS_LABELS.forEach(function (pair) {
      if (st.indexOf(pair[0]) >= 0) out.push({ id: pair[0], label: pair[1] });
    });
    return out;
  }

  // ── the summary strip (#788): the server's counts and figures, worded ──
  // The order the strip shows its four counts in.
  var SUMMARY_COUNTS = [STATUS.on_plan, STATUS.behind, STATUS.over_budget, STATUS.not_linked];
  // Last week's Actual hours: read, Raken not read, or the kept read stops before the week ends.
  // backend/plan_vs_actual.py's LAST_WEEK_*; tests/test_project_calendar_core_js.py holds the two.
  var LAST_WEEK = { read: "read", not_read: "not_read", not_covered: "not_covered" };

  function summaryOf(data) {
    var s = data && data.summary;
    return s && typeof s === "object" ? s : null;
  }

  /** A whole number of jobs the server counted, or 0 for anything else. */
  function jobCount(n) {
    return typeof n === "number" && isFinite(n) && n >= 0 ? Math.round(n) : 0;
  }

  /** "1 job", "2 jobs"; with an adjective, "2 linked jobs". */
  function jobsText(n, adjective) {
    return n + " " + (adjective ? adjective + " " : "") + "job" + (n === 1 ? "" : "s");
  }

  /** Whether the server could count the jobs: Raken was read. Until then no row carries a status,
   *  so its counts are no figure (null), never zeros. */
  function countsKnown(s) {
    return !!s && s.raken_read !== false && !!s.counts && typeof s.counts === "object";
  }

  function statusLabel(id) {
    for (var i = 0; i < STATUS_LABELS.length; i++) {
      if (STATUS_LABELS[i][0] === id) return STATUS_LABELS[i][1];
    }
    return "";
  }

  /** The four count tiles, On plan, Behind, Over budget, Not linked: the server's counts (a job
   *  Behind and Over budget is counted under both), and which one is filtering the list (`active`).
   *  With Raken not read each count is null (the page draws a dash) and the tile is disabled.
   *  [] when the response has no summary: no strip rather than a row of zeros. */
  function countTiles(data, active) {
    var s = summaryOf(data);
    if (!s) return [];
    var known = countsKnown(s);
    return SUMMARY_COUNTS.map(function (id) {
      return { id: id, label: statusLabel(id), count: known ? jobCount(s.counts[id]) : null,
        pressed: known && active === id, disabled: !known };
    });
  }

  /** The count filtering the list: the one pressed, or none while the counts are not known (no row
   *  carries a status then, so it would empty the list). Only the four counts filter
   *  (plan_vs_actual.status_filter is the same rule on the server). */
  function statusFilter(data, status) {
    return countsKnown(summaryOf(data)) && SUMMARY_COUNTS.indexOf(status) >= 0 ? status : "";
  }

  /** The line under the count tiles: why they are not known, or why they add up to fewer jobs
   *  than the list holds (a job whose Raken budget was not read is in no count). "" otherwise. */
  function countsNote(data) {
    var s = summaryOf(data);
    if (!s) return "";
    if (!countsKnown(s)) return "Raken has not been read, so the counts are not known.";
    var n = jobCount(s.unflagged);
    if (!n) return "";
    return n === 1 ? "1 job is in no count: its Raken budget was not read."
      : jobsText(n) + " are in no count: their Raken budgets were not read.";
  }

  /** The status filter after a count is pressed: that count, or none when it was already the one
   *  pressed. Only the four counts filter. */
  function toggleStatus(active, id) {
    if (SUMMARY_COUNTS.indexOf(id) < 0) return "";
    return active === id ? "" : id;
  }

  /** The line beside the search box: "5 jobs", or "2 of 5 jobs" while the search, a count, or the
   *  Work type or Foreman filter (`filters`) narrows the list. */
  function listCountText(shown, total, q, status, filters) {
    var f = filters || {};
    if (String(q || "").trim() || status || f.work_type || f.foreman) {
      return shown + " of " + total + " jobs";
    }
    return jobsText(total);
  }

  /** What a list filtered down to nothing says, naming the filters. "" when nothing filters it. */
  function noMatchText(q, status, filters) {
    var f = filters || {};
    var label = statusLabel(status);
    var searched = !!String(q || "").trim();
    if (f.work_type || f.foreman) {
      var items = [];
      if (f.work_type) items.push(String(f.work_type));
      if (f.foreman) {
        items.push(filterKey(f.foreman) === FOREMAN_NONE ? NO_FOREMAN_LABEL
          : "Foreman " + String(f.foreman).trim());
      }
      if (label) items.push(label);
      return "No job matches " + (searched ? "the search and " : "") + "the filters: "
        + items.join(", ") + ".";
    }
    if (searched && label) return "No " + label + " job matches the search.";
    if (searched) return "No job matches the search.";
    return label ? "No job is " + label + "." : "";
  }

  // ── the Excel download (#785) ──
  var DOWNLOAD_PATH = "/api/project-analytics/export.xlsx";
  // The search and the three filters, in the order the download's and the address's query strings
  // name them. VIEW_KEYS add the page and the page size: the address's own keys (#819). Every other
  // key in the address belongs to someone else (Connect Raken's raken_code and raken_state, #781).
  var FILTER_KEYS = ["q", "status", "work_type", "foreman"];
  var VIEW_KEYS = FILTER_KEYS.concat(["page", "per"]);

  /** The download's address: the list as it is filtered on screen, the pressed count (`status`,
   *  one of the four counts), the search text (`q`) and the Work type and Foreman filters
   *  (`filters`, #819) as query parameters, each cut to SEARCH_MAX. Never the page or the page
   *  size: the file holds every matching job. The server filters with this file's own rule
   *  (plan_vs_actual.visible_projects mirrors visibleProjects). A GET: it writes nothing. */
  function downloadHref(q, status, filters) {
    var f = filters || {};
    var parts = [];
    if (status && SUMMARY_COUNTS.indexOf(status) >= 0) {
      parts.push("status=" + encodeURIComponent(status));
    }
    var given = { q: q, work_type: f.work_type, foreman: f.foreman };
    FILTER_KEYS.forEach(function (k) {
      if (k === "status") return;      // first, above: one of the four counts or nothing
      var text = String(given[k] == null ? "" : given[k]).slice(0, SEARCH_MAX);
      if (text.trim()) parts.push(k + "=" + encodeURIComponent(text));
    });
    return DOWNLOAD_PATH + (parts.length ? "?" + parts.join("&") : "");
  }

  // ── the pager (#819): the page splits the list it has; the server always sends it whole ──
  var PAGE_SIZES = [25, 50, 100];
  var PAGE_SIZE = 25;
  // The highest page the address may name (six digits); a page past the end shows the last page.
  var PAGE_MAX = 999999;
  var ELLIPSIS = "…";

  function perOf(n) {
    return PAGE_SIZES.indexOf(n) >= 0 ? n : PAGE_SIZE;
  }

  /** The page numbers the pager shows: every one up to seven pages, else the first, the last and
   *  the ones around the page shown, with an ellipsis for each gap (always seven items). */
  function pageItems(page, pages) {
    var out = [];
    var i;
    if (pages <= 7) {
      for (i = 1; i <= pages; i++) out.push(i);
      return out;
    }
    if (page <= 4) return [1, 2, 3, 4, 5, ELLIPSIS, pages];
    if (page >= pages - 3) {
      out = [1, ELLIPSIS];
      for (i = pages - 4; i <= pages; i++) out.push(i);
      return out;
    }
    return [1, ELLIPSIS, page - 1, page, page + 1, ELLIPSIS, pages];
  }

  /** The pager for `total` jobs at `per` a page (25, 50 or 100, else 25) on `page` (a page past
   *  the end is the last page, anything else odd the first): which rows (start, end), "Showing
   *  A–B of N" ("" for no jobs), whether Previous and Next can be pressed, and the page numbers. */
  function pageModel(total, page, per) {
    var n = typeof total === "number" && isFinite(total) && total > 0 ? Math.floor(total) : 0;
    var size = perOf(per);
    var pages = Math.max(1, Math.ceil(n / size));
    var p = typeof page === "number" && isFinite(page) && page >= 1 ? Math.floor(page) : 1;
    if (p > pages) p = pages;
    var start = (p - 1) * size;
    var end = Math.min(n, start + size);
    var text = !n ? "" : "Showing " + (start + 1 === end ? end : (start + 1) + "–" + end)
      + " of " + n;
    return { page: p, pages: pages, per: size, total: n, start: start, end: end, text: text,
      prev: p > 1, next: p < pages, items: pageItems(p, pages) };
  }

  /** The rows on the page `model` (pageModel) shows. */
  function pageSlice(rows, model) {
    return (Array.isArray(rows) ? rows : []).slice(model.start, model.end);
  }

  // ── the view in the address (#819) ──
  // The search, the three filters, the page and the page size live in the query string, so a
  // reload or a shared link opens the same list. The hash keeps choosing the tab (tabFromHash).
  /** A view with every value made safe: a status that is not one of the four counts, a page that
   *  is not a whole number from 1 to PAGE_MAX and a page size other than 25, 50 or 100 read as
   *  their defaults; each text is cut to SEARCH_MAX. */
  function cleanView(view) {
    var v = view && typeof view === "object" ? view : {};
    var text = function (x) { return typeof x === "string" ? x.slice(0, SEARCH_MAX) : ""; };
    var page = v.page;
    if (typeof page === "string") page = /^[1-9][0-9]{0,5}$/.test(page) ? Number(page) : 1;
    if (typeof page !== "number" || !(page >= 1 && page <= PAGE_MAX) || Math.floor(page) !== page) {
      page = 1;
    }
    var per = v.per;
    if (typeof per === "string") per = /^(25|50|100)$/.test(per) ? Number(per) : PAGE_SIZE;
    return { q: text(v.q), status: SUMMARY_COUNTS.indexOf(v.status) >= 0 ? v.status : "",
      work_type: text(v.work_type), foreman: text(v.foreman), page: page, per: perOf(per) };
  }

  /** The view a query string ("?q=…&status=…&work_type=…&foreman=…&page=…&per=…") asks for.
   *  Unknown keys are ignored, a repeated key's first value is read, junk is the default. */
  function readView(search) {
    var params = new URLSearchParams(String(search == null ? "" : search));
    var raw = {};
    VIEW_KEYS.forEach(function (k) { var x = params.get(k); if (x != null) raw[k] = x; });
    return cleanView(raw);
  }

  /** The query string for `view` ("" for the default view), defaults left out, so a plain list
   *  keeps a plain address. */
  function viewQuery(view) {
    var v = cleanView(view);
    var parts = [];
    FILTER_KEYS.forEach(function (k) {
      if (v[k].trim()) parts.push(k + "=" + encodeURIComponent(v[k]));
    });
    if (v.page !== 1) parts.push("page=" + v.page);
    if (v.per !== PAGE_SIZE) parts.push("per=" + v.per);
    return parts.length ? "?" + parts.join("&") : "";
  }

  /** The query string for the address `search` with `view` written into it: the view's own keys
   *  (VIEW_KEYS) replaced by viewQuery's, every other key kept as it was written, after them. The
   *  page writes the view with this, so another script's keys (Connect Raken's sign-in coming back
   *  to this page) are still in the address when that script reads them. */
  function addressSearch(search, view) {
    var own = viewQuery(view);
    var kept = String(search == null ? "" : search).replace(/^\?/, "").split("&")
      .filter(function (piece) {
        if (!piece) return false;
        var key = piece.split("=")[0];
        try { key = decodeURIComponent(key.replace(/\+/g, " ")); } catch (e) { /* as written */ }
        return VIEW_KEYS.indexOf(key) < 0;
      });
    if (!kept.length) return own;
    return (own ? own + "&" : "?") + kept.join("&");
  }

  /** The view after `patch`: a change to the search, a filter or the page size goes back to page
   *  1, so the list never sits on a page that no longer exists. `view` itself is not changed. */
  function nextView(view, patch) {
    var cur = cleanView(view);
    var next = cleanView(Object.assign({}, cur, patch || {}));
    var moved = FILTER_KEYS.concat(["per"]).some(function (k) {
      return next[k] !== cur[k];
    });
    if (moved) next.page = 1;
    return next;
  }

  /** Clear filters: no search and no filter, page 1. The page size is not a filter and stays. */
  function clearedView(view) {
    return cleanView({ per: cleanView(view).per });
  }

  /** Whether the search or any filter is set in `view` (Clear filters is shown then). */
  function filtersActive(view) {
    var v = cleanView(view);
    return FILTER_KEYS.some(function (k) { return !!v[k].trim(); });
  }

  /** The view once a list has loaded: a Work type or Foreman the selects do not offer is dropped,
   *  one they offer in another spelling takes theirs, and a Status is dropped while the counts are
   *  not known (it filters nothing then, statusFilter). Dropping one is a filter change, so the
   *  view goes back to page 1; a new spelling is not. Nothing is dropped before a job is listed. */
  function settleView(view, data) {
    var v = cleanView(view);
    if (!data || !Array.isArray(data.projects) || !data.projects.length) return v;
    var settled = { status: statusFilter(data, v.status),
      work_type: workTypeFilter(data, v.work_type), foreman: foremanFilter(data, v.foreman) };
    var dropped = Object.keys(settled).some(function (k) { return v[k].trim() && !settled[k]; });
    Object.assign(v, settled);
    if (dropped) v.page = 1;
    return v;
  }

  /** The filters in force for `view` over the list `data`: the search, the pressed count (none
   *  while the counts are not known, statusFilter), and the Work type and Foreman the selects
   *  offer. What the list, its count line, its no-match line and the download all use. */
  function viewFilters(data, view) {
    var v = cleanView(view);
    return { q: v.q, status: statusFilter(data, v.status), work_type: workTypeFilter(data, v.work_type),
      foreman: foremanFilter(data, v.foreman) };
  }

  /** The three selects' options, and whether the Status one can be used: like the count buttons,
   *  not while the counts are not known (Raken not read). */
  function filterOptions(data) {
    return { work_types: workTypeOptions(data), foremen: foremanOptions(data && data.projects),
      statuses: SUMMARY_COUNTS.map(function (id) { return { value: id, label: statusLabel(id) }; }),
      status_known: countsKnown(summaryOf(data)) };
  }

  /** The saved file's name: the server's (it carries the Central day the file was made), else
   *  one made from `today` (a Central "YYYY-MM-DD"). Only a plain .xlsx name is taken. */
  function downloadName(disposition, today) {
    var m = /filename="([A-Za-z0-9._-]+\.xlsx)"/.exec(String(disposition || ""));
    if (m && m[1].indexOf("..") < 0) return m[1];
    return "project-analytics-" + today + ".xlsx";
  }

  /** Last week's figure tile: the previous Monday to Friday, Planned hours against Actual hours
   *  over the linked jobs in the list. When Raken has not been read the planned figure still
   *  shows (for every job with a Job number) and Actual hours are a dash, never 0, and the note
   *  says so plainly. A Workday with no Crew size adds nothing to Planned hours, and the note says
   *  that too. null without a summary. The server's `raken` is one of LAST_WEEK. */
  function lastWeekTile(data) {
    var s = summaryOf(data);
    var w = s && s.last_week && typeof s.last_week === "object" ? s.last_week : null;
    if (!w) return null;
    var range = validDay(w.from) && validDay(w.to)
      ? DOW_SHORT[K.dow(w.from)] + ", " + K.dayLabel(w.from, false) + " – "
        + DOW_SHORT[K.dow(w.to)] + ", " + K.dayLabel(w.to, false)
      : "";
    var jobs = jobCount(w.jobs);
    var out = { range: range, planned: numLabel(w.planned_hours), actual: "—", note: "" };
    if (w.raken === LAST_WEEK.read) {
      out.actual = decLabel(w.actual_hours);
      out.note = jobs ? "Over the " + jobsText(jobs, "linked") + " in the list."
        : "No job is linked to Raken.";
    } else if (w.raken === LAST_WEEK.not_covered) {
      out.note = "Raken's last read stops before the end of last week.";
    } else {
      out.note = "Raken has not been read, so Actual hours are not known. Planned hours are for the "
        + jobsText(jobs) + " with a Job number.";
    }
    if (w.crew_size_missing === true) {
      out.note += typeof w.planned_hours === "number"
        ? " Some Workdays have no Crew size, so Planned hours are short."
        : " No Workday last week has a Crew size, so Planned hours are not known.";
    }
    return out;
  }

  /** The Budget totals' figure tile: total Budgeted hours against total Projected total hours,
   *  Over/under signed, over the linked jobs whose Raken budget was read, and how many of the
   *  linked jobs that is. Whether Raken was read is the summary's own `raken_read`. null without
   *  a summary. */
  function budgetTile(data) {
    var s = summaryOf(data);
    var b = s && s.budget && typeof s.budget === "object" ? s.budget : null;
    if (!b) return null;
    var jobs = jobCount(b.jobs);
    var linked = jobCount(b.linked_jobs);
    var out = { budgeted: numLabel(b.budgeted_hours), projected: numLabel(b.projected_total_hours),
      over_under: overUnderLabel(b.over_under),
      over: typeof b.over_under === "number" && b.over_under < 0, note: "" };
    if (s.raken_read === false) out.note = "Raken has not been read.";
    else if (!jobs) out.note = "No linked job has a Raken budget read.";
    else out.note = jobs + " of " + jobsText(linked, "linked") + (jobs === 1 ? " has" : " have")
      + " a Raken budget read";
    return out;
  }

  /** Why a Not linked row is not linked. "" for any other row. */
  function notLinkedNote(p) {
    var r = rakenOf(p);
    if (r.state !== RAKEN.not_linked) return "";
    var num = p && p.job_number ? String(p.job_number) : "";
    if (r.reason === REASON.no_job_number || !num) return "No Job number on the calendar";
    var dups = Array.isArray(r.duplicates) ? r.duplicates.filter(Boolean) : [];
    if (r.reason !== REASON.duplicate || dups.length < 2) {
      return "No Raken project carries Job number " + num;
    }
    var names = dups.map(function (d) {
      return d && typeof d.name === "string" && d.name.trim() ? d.name.trim() : "an unnamed project";
    });
    var list = names.length === 2 ? names[0] + " and " + names[1]
      : names.slice(0, -1).join(", ") + " and " + names[names.length - 1];
    var count = dups.length === 2 ? "Two" : String(dups.length);
    return count + " Raken projects carry Job number " + num + ": " + list;
  }

  /** True while the server says a "Refresh now" is reading Raken. */
  function rakenRefreshing(data) {
    return !!(data && data.raken && data.raken.refreshing === true);
  }

  /** "Raken as of <Central time>", what to do when Raken has not been read yet, and whether a
   *  refresh is running. */
  function asOfText(data) {
    var r = data && data.raken && typeof data.raken === "object" ? data.raken : {};
    var at = centralStamp(r.as_of);
    if (rakenRefreshing(data)) {
      return at ? "Raken as of " + at + " (Central). Refreshing…" : "Refreshing Raken…";
    }
    if (at) return "Raken as of " + at + " (Central)";
    if (r.state === RAKEN.not_refreshed) return "Raken has not been read yet. Press Refresh now.";
    return "";
  }

  /** The one plain sentence about Raken the server sent (not connected, expired, unreachable…). */
  function rakenMessage(data) {
    var m = data && data.raken && data.raken.message;
    return typeof m === "string" ? m : "";
  }

  /** A Raken-only project's name, or words for one Raken sent without a name. */
  function rakenOnlyName(x) {
    return x && typeof x.name === "string" && x.name.trim() ? x.name.trim() : "Unnamed Raken project";
  }

  /** A whole positive number the server sent, or null. */
  function serverCount(data, key) {
    var n = data && data[key];
    return typeof n === "number" && isFinite(n) && n > 0 ? n : null;
  }

  /** The line under the list. The hours in a workday are the server's (`hours_per_workday`). */
  function pvaFootText(data) {
    var through = dayLong(data && data.so_far_through);
    var hours = serverCount(data, "hours_per_workday");
    return (through ? "Counts so far run through yesterday, " + through + ". " : "")
      + "Planned hours = Workdays so far × Crew size × "
      + (hours == null ? "the hours in a workday" : hours)
      + ". Days clocked in, On site and Actual hours come from Raken time cards;"
      + " Budgeted hours and Projected total hours from Raken's production insights.";
  }

  /** What an empty list says. The window is the server's (`window_days`). */
  function pvaEmptyText(data) {
    var n = serverCount(data, "window_days");
    return n == null
      ? "No jobs are running, finished lately, or starting soon."
      : "No jobs are running, finished in the last " + n + " days, or starting in the next "
        + n + " days.";
  }

  // ── the job detail (#789) ───────────────────────────────────────────
  /** The four pairs of the job detail, Plan (the calendar) against Actual (Raken), worded as the
   *  list words them, larger. The Budget pair's plan side is Budgeted hours and its Raken side
   *  Projected total hours, with Over/under. */
  function detailPairs(p) {
    var rc = rakenCells(p);
    var bc = budgetCells(p);
    var q = p && typeof p === "object" ? p : {};
    return [
      { id: "days", label: "Days", plan: numLabel(q.workdays_so_far),
        planSub: "Workdays booked so far", actual: rc.days, actualSub: "Days clocked in",
        note: rc.days_note, extra: "", over: false, bar: null },
      { id: "crew", label: "Crew", plan: numLabel(q.crew_size), planSub: "Crew size",
        actual: rc.on_site, actualSub: "On site, average a day", note: "", extra: "",
        over: false, bar: null },
      { id: "hours", label: "Hours so far", plan: numLabel(q.planned_hours),
        planSub: "Planned hours", actual: rc.hours, actualSub: "Actual hours", note: "",
        extra: "", over: false, bar: hoursBar(p) },
      { id: "budget", label: "Budget", plan: bc.budgeted, planSub: "Budgeted hours",
        actual: bc.projected, actualSub: "Projected total hours", note: bc.note,
        extra: bc.shown ? bc.over_under : "", over: bc.over, bar: bc.bar },
    ];
  }

  /** A whole number of people, or null: what a day's planned crew or people on site may be. */
  function people(n) {
    return typeof n === "number" && isFinite(n) && n >= 0 ? n : null;
  }

  /** The Monday a Workday's week starts on, so the chart can mark where each week begins. */
  function weekOf(day) {
    return K.addDays(day, -((K.dow(day) + 6) % 7));
  }

  /** The day-by-day chart (#789): one column per entry the server sent (one per Workday of the
   *  job's Mobilizations and Punches, in date order). One scale serves the line and the bars: the
   *  most people planned or on site on any day (at least 1), so a day with more people than
   *  planned draws its bar past the line. Each column:
   *    tick     the planned crew as a percentage of the scale (null: no Crew size that day)
   *    bar      the people clocked in as a percentage (null: no Raken figure for the day)
   *    over     more people clocked in than planned
   *    warn     a Crew size is missing that day (the server's crew_size_missing): the plan shown
   *             is partial, or unknown when no Mobilization that day has one
   *    kind     "clocked" or "missed" (a past day Raken read), "future" (today on: the plan only)
   *             or "plan" (a past day with no Raken figure: a Not linked job, Raken not read)
   *    actual   the day's Actual hours, "" when there is no Raken figure
   *    planned  the day's Planned hours, a dash when its Crew size is missing
   *    week     "Nov 16" on the first column of each week, else ""
   *    label    the column in words, for a screen reader. One day's people are "clocked in":
   *             On site is the GLOSSARY's average a day, which the Crew pair shows. */
  function dayChart(entries) {
    var list = (Array.isArray(entries) ? entries : []).filter(function (e) {
      return e && typeof e === "object" && validDay(e.date);
    });
    var scale = 1;
    list.forEach(function (e) {
      var c = people(e.planned_crew), s = e.future ? null : people(e.on_site);
      if (c != null && c > scale) scale = c;
      if (s != null && s > scale) scale = s;
    });
    var pct = function (n) { return n == null ? null : Math.round(n / scale * 1000) / 10; };
    var prevWeek = null;
    var columns = list.map(function (e) {
      var crew = people(e.planned_crew);
      var onSite = e.future ? null : people(e.on_site);
      var hasHours = !e.future && typeof e.hours === "number" && isFinite(e.hours);
      var kind = e.future ? "future" : (e.missed === true ? "missed"
        : (onSite != null || hasHours ? "clocked" : "plan"));
      var wk = weekOf(e.date);
      var week = wk !== prevWeek ? K.dayLabel(e.date, false) : "";
      prevWeek = wk;
      var day = DOW_SHORT[K.dow(e.date)] + ", " + K.dayLabel(e.date, false);
      var warn = crew == null || e.crew_size_missing === true;
      var words = crew == null ? ["Crew size missing"]
        : [crew + " planned"].concat(warn ? ["a Crew size is missing"] : []);
      if (kind === "missed") words.push("nobody clocked in, missed");
      else if (kind === "clocked") {
        if (onSite != null) words.push(onSite + " clocked in");
        if (hasHours) {
          words.push(decLabel(e.hours) + (people(e.planned_hours) != null
            ? " of " + decLabel(e.planned_hours) : "") + " hours");
        }
      }
      return {
        dow: DOW_SHORT[K.dow(e.date)], dom: String(Number(e.date.slice(8, 10))),
        week: week, kind: kind, tick: pct(crew), bar: pct(onSite),
        over: onSite != null && crew != null && onSite > crew, warn: warn,
        actual: kind === "clocked" || kind === "missed" ? (hasHours ? decLabel(e.hours) : "0") : "",
        planned: decLabel(e.planned_hours),
        label: day + ": " + words.join(", "),
      };
    });
    return { scale: scale, columns: columns };
  }

  /** The Plan vs Actual row holding a Schedule event, found by the EVENT ID among each row's
   *  Mobilizations and Punches, never by Job number or name: rows merge (#792), so an unnumbered
   *  Mobilization can sit in a Job number's row, and a row can take a Punch's Job number. */
  function rowForEvent(projects, id) {
    if (id == null || id === "") return null;
    var key = String(id);
    var rows = Array.isArray(projects) ? projects : [];
    for (var i = 0; i < rows.length; i++) {
      var p = rows[i];
      if (!p || typeof p !== "object") continue;
      var evs = [].concat(Array.isArray(p.mobilizations) ? p.mobilizations : [],
                          Array.isArray(p.punches) ? p.punches : []);
      for (var j = 0; j < evs.length; j++) {
        if (evs[j] && evs[j].id != null && String(evs[j].id) === key) return p;
      }
    }
    return null;
  }

  /** What a Schedule bar opens: "found" (that row's detail), "absent" (the list has loaded and no
   *  row holds the event: the details panel, saying why) or "unknown" (the list has not loaded:
   *  the details panel, saying nothing it cannot know). */
  function pvaLookup(data, id) {
    if (!data || !Array.isArray(data.projects)) return { state: "unknown", row: null };
    var row = rowForEvent(data.projects, id);
    return row ? { state: "found", row: row } : { state: "absent", row: null };
  }

  /** The details panel's line for a bar whose job is not in the list. The window is the
   *  server's (`window_days`); without it the line names no number, as pvaEmptyText does. */
  function notInPvaLine(data) {
    var n = serverCount(data, "window_days");
    return "Not in Plan vs Actual: outside "
      + (n == null ? "its window" : "the " + n + "-day window");
  }

  /** Where the detail's Back button goes: the Schedule when it was opened from there, else the
   *  list. */
  function detailBack(origin) {
    return origin === "schedule" ? { tab: "schedule", label: "Back to the Schedule" }
      : { tab: "pva", label: "Back to Plan vs Actual" };
  }

  /** "Open project": the job's Project in the tool, opened on its intake, which sends a v2 draft
   *  on to its own page (tests/test_v2_routing_guard.py lists this door). "" with no Project. */
  function projectHref(project) {
    var id = project && typeof project === "object" ? project.id : null;
    if ((typeof id !== "string" && typeof id !== "number") || String(id) === "") return "";
    return "/?d=" + encodeURIComponent(String(id)) + "&edit=1";
  }

  /** The words that end both the Schedule's details panel and Plan vs Actual's job detail:
   *  {href, label} for "Open project", {note} when no Project has the Job number yet, or null. */
  function projectFoot(project, jobNumber) {
    var href = projectHref(project);
    if (href) return { href: href, label: "Open project: " + (project.name || "this project") };
    if (jobNumber) return { note: "No project in this tool has Job number " + jobNumber + " yet." };
    return null;
  }

  /** A link the page may offer: https only, so a typed "javascript:" never becomes a link. */
  function httpsLink(u) {
    return typeof u === "string" && /^https:\/\//i.test(u.trim()) ? u.trim() : "";
  }

  /** The job's Mobilizations and Punches in date order, each with its dates, Crew size and the link
   *  to its event in Google Calendar. */
  function detailEvents(p) {
    var q = p && typeof p === "object" ? p : {};
    var out = [];
    [[q.mobilizations, false], [q.punches, true]].forEach(function (pair) {
      (Array.isArray(pair[0]) ? pair[0] : []).forEach(function (m) {
        if (!m || typeof m !== "object") return;
        out.push({
          id: m.id == null ? "" : String(m.id), start: String(m.start || ""),
          last: String(m.last_day || ""),
          kind: pair[1] ? "Punch" : (mobilizationLabel(m.mobilization) || "Mobilization"),
          dates: spanLabel(m) || "No readable date",
          crew: typeof m.crew_size === "number" && isFinite(m.crew_size)
            ? "Crew size " + m.crew_size : "Crew size missing",
          foreman: m.foreman ? String(m.foreman) : "",
          link: httpsLink(m.html_link),
        });
      });
    });
    out.sort(function (a, b) {
      return a.start < b.start ? -1 : a.start > b.start ? 1
        : a.last < b.last ? -1 : a.last > b.last ? 1 : a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
    });
    out.forEach(function (e) { delete e.start; delete e.last; });
    return out;
  }

  /** The job's flags, as the details panel words them (jobFlags). */
  function detailFlags(p) {
    return jobFlags(p);
  }

  /** The same event can arrive twice (a range fetch and the side list's own fetch). One row per id. */
  function uniqueById(events) {
    var seen = {}, out = [];
    (Array.isArray(events) ? events : []).forEach(function (ev) {
      if (!ev) return;
      var k = ev.id == null ? "" : String(ev.id);
      if (k && seen[k]) return;
      if (k) seen[k] = true;
      out.push(ev);
    });
    return out;
  }

  // ── labels ───────────────────────────────────────────────────────────
  var DOW_SHORT = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

  /** "Thu, Nov 12, 2026". */
  function dayLong(day) {
    if (!validDay(day)) return "";
    return DOW_SHORT[K.dow(day)] + ", " + K.dayLabel(day, true);
  }

  /** "Nov 12 – Nov 20", or a single day when start and last day are the same. */
  function spanLabel(ev) {
    var s = spanOf(ev);
    if (!s) return "";
    if (s.start === s.last) return dayLong(s.start);
    var withYear = s.start.slice(0, 4) !== s.last.slice(0, 4);
    return DOW_SHORT[K.dow(s.start)] + ", " + K.dayLabel(s.start, withYear) + " – "
      + DOW_SHORT[K.dow(s.last)] + ", " + K.dayLabel(s.last, true);
  }

  /** An ISO instant as Central wall-clock, e.g. "Nov 12, 3:04 PM". "" when unreadable. */
  function centralStamp(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleString("en-US", {
      timeZone: BIZ_TZ, month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
    });
  }

  return {
    BIZ_TZ: BIZ_TZ, MODES: MODES, GOOGLE_COLORS: GOOGLE_COLORS,
    WORK_TYPE_UNKNOWN_LABEL: WORK_TYPE_UNKNOWN_LABEL,
    centralToday: centralToday, validDay: validDay, spanOf: spanOf,
    isWorkday: isWorkday, workdaysBetween: workdaysBetween, workdaysOf: workdaysOf,
    workdaysLeft: workdaysLeft, deadlineStatus: deadlineStatus, daysUntil: daysUntil,
    colorOf: colorOf, workTypeOf: workTypeOf, textOn: textOn,
    barParts: barParts, flagsOf: flagsOf, ordinal: ordinal,
    matches: matches, filterEvents: filterEvents, byStartThenTitle: byStartThenTitle,
    layout: layout, focusDay: focusDay, uniqueById: uniqueById,
    dayLong: dayLong, spanLabel: spanLabel, centralStamp: centralStamp,
    TABS: TABS, tabFromHash: tabFromHash, filterProjects: filterProjects, leftLabel: leftLabel,
    SEARCH_MAX: SEARCH_MAX,
    filterByStatus: filterByStatus, visibleProjects: visibleProjects,
    SUMMARY_COUNTS: SUMMARY_COUNTS, LAST_WEEK: LAST_WEEK, countTiles: countTiles,
    toggleStatus: toggleStatus, statusFilter: statusFilter, countsNote: countsNote,
    lastWeekTile: lastWeekTile, budgetTile: budgetTile, listCountText: listCountText,
    noMatchText: noMatchText, downloadHref: downloadHref, downloadName: downloadName,
    FOREMAN_NONE: FOREMAN_NONE, filterByFields: filterByFields, workTypeOptions: workTypeOptions,
    foremanOptions: foremanOptions, workTypeFilter: workTypeFilter, foremanFilter: foremanFilter,
    PAGE_SIZES: PAGE_SIZES, PAGE_SIZE: PAGE_SIZE, pageModel: pageModel, pageSlice: pageSlice,
    readView: readView, viewQuery: viewQuery, addressSearch: addressSearch, nextView: nextView,
    clearedView: clearedView,
    filtersActive: filtersActive, settleView: settleView, viewFilters: viewFilters,
    filterOptions: filterOptions,
    numLabel: numLabel, rakenLabel: rakenLabel, TIMING: TIMING,
    RAKEN_NOT_CONNECTED: RAKEN_NOT_CONNECTED, pvaFootText: pvaFootText, pvaEmptyText: pvaEmptyText,
    RAKEN: RAKEN, STATUS: STATUS, REASON: REASON, rakenRefreshing: rakenRefreshing,
    decLabel: decLabel, rakenCells: rakenCells, BUDGET: BUDGET, overUnderLabel: overUnderLabel,
    pairBar: pairBar, hoursBar: hoursBar, budgetCells: budgetCells,
    statusChips: statusChips, notLinkedNote: notLinkedNote, asOfText: asOfText,
    rakenMessage: rakenMessage, rakenOnlyName: rakenOnlyName,
    detailPairs: detailPairs, dayChart: dayChart, rowForEvent: rowForEvent, pvaLookup: pvaLookup,
    notInPvaLine: notInPvaLine, detailBack: detailBack, projectHref: projectHref,
    projectFoot: projectFoot,
    httpsLink: httpsLink, detailEvents: detailEvents, detailFlags: detailFlags,
  };
});
