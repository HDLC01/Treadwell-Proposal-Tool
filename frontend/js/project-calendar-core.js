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
    if (typeof ev.mobilization === "number" && ev.mobilization > 0) {
      out.push(ordinal(ev.mobilization) + " Mobilization");
    }
    if (ev.is_punch) out.push("Punch");
    if (ev.prevailing_wage) out.push("Prevailing wage");
    if (ev.night_work) out.push("Night work");
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
  var RAKEN_NOT_CONNECTED = "not_connected";

  /** The search box: every word typed must match the Job number, the name, the Foreman or the
   *  Work type (as the page words it, so "unknown" finds the jobs with none). */
  function filterProjects(projects, q) {
    var words = String(q || "").toLowerCase().split(/\s+/).filter(Boolean);
    return (Array.isArray(projects) ? projects : []).filter(function (p) {
      if (!p || typeof p !== "object") return false;
      if (!words.length) return true;
      var hay = [p.job_number, p.name, p.foreman, workTypeOf(p)]
        .map(function (v) { return String(v == null ? "" : v).toLowerCase(); }).join(" \u0001 ");
      for (var i = 0; i < words.length; i++) if (hay.indexOf(words[i]) < 0) return false;
      return true;
    });
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
  // A row's Raken state and its statuses: backend/raken_actuals.py names the same values
  // (ROW_STATES, STATUSES); tests/test_project_calendar_core_js.py holds the two together.
  var RAKEN = {
    not_connected: "not_connected", expired: "expired", not_provisioned: "not_provisioned",
    unreachable: "unreachable", not_refreshed: "not_refreshed", linked: "linked",
    not_linked: "not_linked",
  };
  var STATUS = { behind: "behind", not_linked: "not_linked" };
  var STATUS_LABELS = [[STATUS.not_linked, "Not linked"], [STATUS.behind, "Behind"]];

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
   *  Dashes unless the row is linked. */
  function rakenCells(p) {
    var r = rakenOf(p);
    if (r.state !== RAKEN.linked) return { days: "—", on_site: "—", hours: "—" };
    return { days: numLabel(r.days_clocked), on_site: decLabel(r.avg_on_site),
             hours: decLabel(r.actual_hours) };
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

  /** Why a Not linked row is not linked. "" for any other row. */
  function notLinkedNote(p) {
    var r = rakenOf(p);
    if (r.state !== RAKEN.not_linked) return "";
    var num = p && p.job_number ? String(p.job_number) : "";
    if (r.reason === "no_job_number" || !num) return "No Job number on the calendar";
    var dups = Array.isArray(r.duplicates) ? r.duplicates.filter(Boolean) : [];
    if (r.reason !== "duplicate" || dups.length < 2) {
      return "No Raken project has Project Number " + num;
    }
    var names = dups.map(function (d) {
      return d && typeof d.name === "string" && d.name.trim() ? d.name.trim() : "an unnamed project";
    });
    var list = names.length === 2 ? names[0] + " and " + names[1]
      : names.slice(0, -1).join(", ") + " and " + names[names.length - 1];
    var count = dups.length === 2 ? "Two" : String(dups.length);
    return count + " Raken projects have Project Number " + num + ": " + list;
  }

  /** "Raken as of <Central time>", or what to do when Raken has not been read yet. */
  function asOfText(data) {
    var r = data && data.raken && typeof data.raken === "object" ? data.raken : {};
    var at = centralStamp(r.as_of);
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
      + ". Days clocked in, On site and Actual hours come from Raken time cards.";
  }

  /** What an empty list says. The window is the server's (`window_days`). */
  function pvaEmptyText(data) {
    var n = serverCount(data, "window_days");
    return n == null
      ? "No jobs are running, finished lately, or starting soon."
      : "No jobs are running, finished in the last " + n + " days, or starting in the next "
        + n + " days.";
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
    numLabel: numLabel, rakenLabel: rakenLabel, TIMING: TIMING,
    RAKEN_NOT_CONNECTED: RAKEN_NOT_CONNECTED, pvaFootText: pvaFootText, pvaEmptyText: pvaEmptyText,
    RAKEN: RAKEN, STATUS: STATUS, decLabel: decLabel, rakenCells: rakenCells,
    statusChips: statusChips, notLinkedNote: notLinkedNote, asOfText: asOfText,
    rakenMessage: rakenMessage, rakenOnlyName: rakenOnlyName,
  };
});
