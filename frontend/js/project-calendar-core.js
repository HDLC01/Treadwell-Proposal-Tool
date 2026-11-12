// Project Calendar engine: pure functions, no DOM, no fetch.
// Externalized (CSP: no inline scripts). Do not add inline scripts.
//
// WHAT THIS FILE KNOWS. The Project Calendar is a read-only view of the crews' Google calendar,
// "Treadwell Projects". The server has already parsed each event's free-text title into a Job
// number, Crew size, Mobilization and Crew lead, and already turned Google's dates into inclusive
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
//   * the text filter and the "Durations only" switch.
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
  // Colour 11 (Tomato) is the one with a meaning here: the bar is a job's Duration.
  var GOOGLE_COLORS = {
    "1": "#7986cb", "2": "#33b679", "3": "#8e24aa", "4": "#e67c73", "5": "#f6bf26",
    "6": "#f4511e", "7": "#039be5", "8": "#616161", "9": "#3f51b5", "10": "#0b8043",
    "11": "#d50000",
  };
  var DURATION_COLOR_ID = "11";

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

  function isDuration(ev) {
    if (!ev) return false;
    if (typeof ev.is_duration === "boolean") return ev.is_duration;
    return String(ev.color_id) === DURATION_COLOR_ID;
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
  /** The compact pieces of a bar: the tidied name first, then Job number, Crew size and Crew
   *  lead. The raw title is never lost; the page puts it in the bar's title attribute. */
  function barParts(ev) {
    var name = String((ev && (ev.name || ev.title)) || "").trim() || "Untitled";
    var meta = [];
    if (ev && ev.job_number) meta.push(String(ev.job_number));
    if (ev && typeof ev.crew_size === "number" && isFinite(ev.crew_size)) {
      meta.push(ev.crew_size + " crew");
    }
    if (ev && ev.crew_lead) meta.push(String(ev.crew_lead));
    return { name: name, meta: meta.join(" · ") };
  }

  /** The flags worth a word in the details panel, in a fixed order. */
  function flagsOf(ev) {
    var out = [];
    if (!ev) return out;
    if (isDuration(ev)) out.push("Duration");
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
  /** Text search across the raw title, the tidied name, Job number, Crew lead and the matched
   *  Project's name. Every word typed must match somewhere, in any order. */
  function matches(ev, q) {
    var words = String(q || "").toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) return true;
    var hay = [ev.title, ev.name, ev.job_number, ev.crew_lead,
               ev.project && ev.project.name]
      .map(function (v) { return String(v == null ? "" : v).toLowerCase(); }).join(" \u0001 ");
    for (var i = 0; i < words.length; i++) if (hay.indexOf(words[i]) < 0) return false;
    return true;
  }

  function filterEvents(events, opts) {
    var o = opts || {};
    return (Array.isArray(events) ? events : []).filter(function (ev) {
      if (!ev || typeof ev !== "object") return false;
      if (o.durationsOnly && !isDuration(ev)) return false;
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

  // ── the side list ────────────────────────────────────────────────────
  /** Deadlines from today on, soonest first, then by name. Only Durations carry one.
   *  `withinDays`, when given, drops Deadlines that many days out or more, so a list labelled
   *  "Next 60 days" never shows day 106 just because its Duration overlaps the window. */
  function upcomingDeadlines(events, today, withinDays) {
    var out = [];
    (Array.isArray(events) ? events : []).forEach(function (ev) {
      if (!ev || !isDuration(ev)) return;
      var dl = validDay(ev.deadline) ? ev.deadline : (spanOf(ev) || {}).last;
      if (!validDay(dl) || !validDay(today) || K.diffDays(today, dl) < 0) return;
      if (typeof withinDays === "number" && K.diffDays(today, dl) >= withinDays) return;
      out.push({ ev: ev, deadline: dl, status: deadlineStatus(dl, today),
                 days: K.diffDays(today, dl) });
    });
    out.sort(function (a, b) {
      if (a.deadline !== b.deadline) return a.deadline < b.deadline ? -1 : 1;
      return barParts(a.ev).name.localeCompare(barParts(b.ev).name);
    });
    return out;
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
    DURATION_COLOR_ID: DURATION_COLOR_ID,
    centralToday: centralToday, validDay: validDay, spanOf: spanOf,
    isWorkday: isWorkday, workdaysBetween: workdaysBetween, workdaysOf: workdaysOf,
    workdaysLeft: workdaysLeft, deadlineStatus: deadlineStatus, daysUntil: daysUntil,
    colorOf: colorOf, isDuration: isDuration, textOn: textOn,
    barParts: barParts, flagsOf: flagsOf, ordinal: ordinal,
    matches: matches, filterEvents: filterEvents, byStartThenTitle: byStartThenTitle,
    layout: layout, upcomingDeadlines: upcomingDeadlines, focusDay: focusDay, uniqueById: uniqueById,
    dayLong: dayLong, spanLabel: spanLabel, centralStamp: centralStamp,
  };
});
