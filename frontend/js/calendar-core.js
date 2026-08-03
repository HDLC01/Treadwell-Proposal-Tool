// Bid Calendar date engine — pure functions, no DOM, no fetch.
// Externalized (CSP: no inline scripts). Do not add inline scripts.
//
// DATES, AND WHY THIS FILE EXISTS AT ALL.
//
// Every value here is a "YYYY-MM-DD" string on the America/Chicago calendar. Rows
// arrive from /api/analytics with UTC timestamps, and TWAgg.decorate() has already
// stamped each one's Central day as `_bd` — so the conversion happens once, in the
// place that already knows how, and this file never touches a timezone again.
//
// Arithmetic is then done by parsing those strings as UTC midnight and stepping in
// whole UTC days. That is the point: a local-time `new Date(y, m, d)` plus
// `setDate(+1)` silently produces a 23- or 25-hour day twice a year, so a
// fortnight spanning a DST change comes out with a duplicated or missing column.
// UTC has no such days. The strings are already Central, so stepping them in UTC
// is both correct and immune to whatever zone the viewer's laptop is in.
//
// Basisboard's own calendar gets this wrong in the other direction: it shows bid
// deadlines at 3:00 AM and 5:00 AM, which nobody sets as a deadline. Those are
// evening cut-offs rendered in the wrong zone.
(function (root, factory) {
  var api = factory();
  root.TWCal = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;   // node, for tests
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var MODES = [
    { id: "week", label: "Week", days: 7 },
    { id: "two", label: "Two weeks", days: 14 },
    { id: "month", label: "Month", days: 0 },      // 0 = whole calendar month, padded
  ];
  var DOW = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  // ── day-string arithmetic, all in UTC ──────────────────────────────
  /** "YYYY-MM-DD" -> ms at UTC midnight. NaN for anything unparseable. */
  function ms(day) {
    if (!day || typeof day !== "string" || day.length < 10) return NaN;
    var y = Number(day.slice(0, 4)), m = Number(day.slice(5, 7)), d = Number(day.slice(8, 10));
    if (!y || !m || !d) return NaN;
    var t = Date.UTC(y, m - 1, d);
    // Date.UTC rolls 2026-02-31 forward to March. Round-tripping catches that, so a
    // malformed day can't quietly become a real one three days away.
    return fromMs(t) === day.slice(0, 10) ? t : NaN;
  }

  /** ms -> "YYYY-MM-DD", read back with UTC getters so no local offset leaks in. */
  function fromMs(t) {
    var d = new Date(t);
    return d.getUTCFullYear() + "-"
      + String(d.getUTCMonth() + 1).padStart(2, "0") + "-"
      + String(d.getUTCDate()).padStart(2, "0");
  }

  var DAY_MS = 86400000;

  function addDays(day, n) {
    var t = ms(day);
    return isNaN(t) ? "" : fromMs(t + n * DAY_MS);
  }

  /** 0 = Sunday. Sunday-first because that is how the estimating week is read here. */
  function dow(day) {
    var t = ms(day);
    return isNaN(t) ? -1 : new Date(t).getUTCDay();
  }

  function isWeekend(day) {
    var w = dow(day);
    return w === 0 || w === 6;
  }

  /** Whole days from `a` to `b`; negative if b is earlier. */
  function diffDays(a, b) {
    var x = ms(a), y = ms(b);
    if (isNaN(x) || isNaN(y)) return null;
    return Math.round((y - x) / DAY_MS);
  }

  function startOfWeek(day) {
    var w = dow(day);
    return w < 0 ? "" : addDays(day, -w);
  }

  function startOfMonth(day) {
    return ms(day) ? day.slice(0, 8) + "01" : "";
  }

  function endOfMonth(day) {
    var y = Number(day.slice(0, 4)), m = Number(day.slice(5, 7));
    return fromMs(Date.UTC(m === 12 ? y + 1 : y, m === 12 ? 0 : m, 1) - DAY_MS);
  }

  // ── the visible range ──────────────────────────────────────────────
  /** The grid for `mode` around `anchor`.
   *
   *  Always whole weeks starting Sunday, so the seven column headers line up with
   *  every row. Month view is therefore padded out to the weeks that contain the
   *  1st and the last — those leading/trailing days are real and their bids are
   *  shown, because a deadline on the 31st matters just as much when you are
   *  looking at the following month. */
  function rangeFor(anchor, mode) {
    var m = modeOf(mode);
    var from, to;
    if (m.id === "month") {
      from = startOfWeek(startOfMonth(anchor));
      to = addDays(startOfWeek(endOfMonth(anchor)), 6);
    } else {
      from = startOfWeek(anchor);
      to = addDays(from, m.days - 1);
    }
    var days = [];
    for (var d = from; d && diffDays(d, to) >= 0; d = addDays(d, 1)) days.push(d);
    return { from: from, to: to, days: days, mode: m.id };
  }

  function modeOf(id) {
    for (var i = 0; i < MODES.length; i++) if (MODES[i].id === id) return MODES[i];
    return MODES[1];                                 // two weeks is the default view
  }

  /** Move one whole range forward (+1) or back (-1). Month steps by month, not by
   *  28 days — otherwise "next month" from a padded grid can land back where it
   *  started, and the header would repeat itself. */
  function shift(anchor, mode, dir) {
    var m = modeOf(mode);
    if (m.id !== "month") return addDays(startOfWeek(anchor), dir * m.days);
    var y = Number(anchor.slice(0, 4)), mo = Number(anchor.slice(5, 7)) + dir;
    if (mo > 12) { mo = 1; y += 1; }
    if (mo < 1) { mo = 12; y -= 1; }
    return y + "-" + String(mo).padStart(2, "0") + "-01";
  }

  /** "Aug 2 – Aug 15", "Aug 30 – Sep 5", "Aug 2026" for a month, and a year on
   *  either side when the range straddles New Year. */
  function rangeLabel(range, mode) {
    if (!range.from || !range.to) return "";
    if (modeOf(mode).id === "month") {
      var mid = range.days[Math.floor(range.days.length / 2)] || range.from;
      return MON[Number(mid.slice(5, 7)) - 1] + " " + mid.slice(0, 4);
    }
    return dayLabel(range.from, range.from.slice(0, 4) !== range.to.slice(0, 4))
      + " – " + dayLabel(range.to, range.from.slice(0, 4) !== range.to.slice(0, 4));
  }

  function dayLabel(day, withYear) {
    var out = MON[Number(day.slice(5, 7)) - 1] + " " + Number(day.slice(8, 10));
    return withYear ? out + ", " + day.slice(0, 4) : out;
  }

  function contains(range, day) {
    return !!day && diffDays(range.from, day) >= 0 && diffDays(day, range.to) >= 0;
  }

  /** Is `today` inside this range? Drives the Today button's disabled state. */
  function isCurrent(range, today) {
    return contains(range, today);
  }

  // ── urgency ───────────────────────────────────────────────────────
  /** How loudly a card should read. Deliberately a small vocabulary: the eye can
   *  triage three levels at card size, not five.
   *
   *  "late" covers today as well as overdue, because a bid due at 2pm is not a
   *  calmer problem than one that closed at 5pm yesterday. */
  var SOON_DAYS = 2;
  function urgency(day, today) {
    var n = diffDays(today, day);
    if (n === null) return "none";
    if (n <= 0) return "late";
    if (n <= SOON_DAYS) return "soon";
    return "calm";
  }

  // ── bucketing ─────────────────────────────────────────────────────
  /** Group decorated rows onto the days of `range`.
   *
   *  Rows are keyed off `_bd` — the Central deadline day TWAgg.decorate() stamped.
   *  Anything with no deadline at all goes to `undated` rather than being dropped:
   *  Basisboard's calendar hides those, and they are exactly the bids that go quiet
   *  and get forgotten. Rows with a deadline outside the range are simply not shown
   *  (they belong to another page of the calendar), which is a different thing from
   *  having no deadline and must not be conflated with it. */
  function bucket(rows, range) {
    var byDay = {}, undated = [], outside = 0;
    for (var i = 0; i < range.days.length; i++) byDay[range.days[i]] = [];
    for (var j = 0; j < (rows || []).length; j++) {
      var r = rows[j];
      var day = r._bd || "";
      if (!day) { undated.push(r); continue; }
      if (byDay[day]) byDay[day].push(r);
      else outside++;
    }
    for (var k in byDay) if (byDay.hasOwnProperty(k)) byDay[k].sort(byTimeThenValue);
    undated.sort(byValueDesc);
    return { byDay: byDay, undated: undated, outside: outside };
  }

  /** Earliest deadline first — the order you work the day in. Ties break on the
   *  bigger number, since that is the one you want to start. */
  function byTimeThenValue(a, b) {
    var ta = String(a.bid_deadline_at || ""), tb = String(b.bid_deadline_at || "");
    if (ta !== tb) return ta < tb ? -1 : 1;
    return byValueDesc(a, b);
  }

  function byValueDesc(a, b) {
    return (num(b.quote) - num(a.quote)) || String(a.name || "").localeCompare(String(b.name || ""));
  }

  function num(v) { return typeof v === "number" && isFinite(v) ? v : 0; }

  /** Count and total for a day header — "4 · $721k" answers the actual planning
   *  question, which is how much lands on Thursday. */
  function dayLoad(rows) {
    var total = 0;
    for (var i = 0; i < (rows || []).length; i++) total += num(rows[i].quote);
    return { count: (rows || []).length, value: total };
  }

  /** The strip above the grid. Counted over what is IN VIEW, so it always agrees
   *  with what you can see — a summary that includes filtered-out bids reads as a
   *  bug every time somebody checks the arithmetic. */
  function summarize(buckets, today) {
    var bids = 0, value = 0, dueToday = 0, soon = 0, unassigned = 0;
    var days = buckets.byDay;
    for (var day in days) {
      if (!days.hasOwnProperty(day)) continue;
      var u = urgency(day, today);
      for (var i = 0; i < days[day].length; i++) {
        var r = days[day][i];
        bids++; value += num(r.quote);
        if (day === today) dueToday++;
        else if (u === "soon" || u === "late") soon++;
        if (!hasEstimator(r)) unassigned++;
      }
    }
    for (var j = 0; j < buckets.undated.length; j++) {
      if (!hasEstimator(buckets.undated[j])) unassigned++;
    }
    return { bids: bids, value: value, due_today: dueToday, due_soon: soon,
             unassigned: unassigned, undated: buckets.undated.length };
  }

  function hasEstimator(r) {
    return !!(r && r.estimator_ids && r.estimator_ids.length);
  }

  return {
    MODES: MODES, DOW: DOW, MON: MON, SOON_DAYS: SOON_DAYS,
    ms: ms, fromMs: fromMs, addDays: addDays, diffDays: diffDays, dow: dow,
    isWeekend: isWeekend, startOfWeek: startOfWeek, startOfMonth: startOfMonth,
    endOfMonth: endOfMonth, rangeFor: rangeFor, modeOf: modeOf, shift: shift,
    rangeLabel: rangeLabel, dayLabel: dayLabel, contains: contains, isCurrent: isCurrent,
    urgency: urgency, bucket: bucket, dayLoad: dayLoad, summarize: summarize,
    hasEstimator: hasEstimator,
  };
});
