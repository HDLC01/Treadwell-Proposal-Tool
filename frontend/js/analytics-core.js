// Analytics aggregation engine — pure functions, no DOM, no fetch.
// Externalized from analytics.html (CSP: drop script-src 'unsafe-inline').
// Do not add inline scripts.
//
// Every number on the dashboard is computed here, in the browser, from the flat
// rows /api/analytics ships. That is what lets a filter combination like
// "epoxy + gyp, Greg and Troy, awarded this quarter" answer instantly — the
// server never sees the question.
//
// DATES. Every window comparison is a string compare of "YYYY-MM-DD" in
// America/Chicago. Timestamps arrive as UTC and a bid submitted at 7pm Central
// is stamped the NEXT day in UTC, so comparing raw ISO strings would file it
// under the wrong day, and — at month boundaries — the wrong bar on the chart.
// `decorate()` stamps each row's Central calendar day once, up front.
//
// MONEY. Already dollars: the backend converts Basisboard's cents at the
// boundary. Never divide here.
(function (root, factory) {
  var api = factory();
  root.TWAgg = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;   // node, for tests
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var BIZ_TZ = "America/Chicago";
  var _dayFmt = null;
  function dayFmt() {
    if (!_dayFmt) {
      // "en-CA" formats as YYYY-MM-DD, which sorts and compares as a string.
      _dayFmt = new Intl.DateTimeFormat("en-CA", {
        timeZone: BIZ_TZ, year: "numeric", month: "2-digit", day: "2-digit",
      });
    }
    return _dayFmt;
  }

  /** ISO timestamp -> "YYYY-MM-DD" on the Central calendar, or "" if absent. */
  function bizDay(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return dayFmt().format(d);
  }

  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function monthLabel(key) {                       // "2026-01" -> "Jan 2026"
    var p = key.split("-");
    return MONTHS[Number(p[1]) - 1] + " " + p[0];
  }
  function addMonth(key) {
    var y = Number(key.slice(0, 4)), m = Number(key.slice(5, 7));
    if (m === 12) return (y + 1) + "-01";
    return y + "-" + String(m + 1).padStart(2, "0");
  }

  /** Stamp each row's Central calendar days once. Mutates and returns rows. */
  function decorate(rows) {
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      r._aw = bizDay(r.awarded_at);
      r._su = bizDay(r.submitted_at);
      r._bd = bizDay(r.bid_deadline_at);
    }
    return rows;
  }

  /** Today on the Central calendar — the dashboard's "now". */
  function today(now) {
    return dayFmt().format(now || new Date());
  }

  var PRESETS = [
    { id: "all", label: "All time" },
    { id: "ytd", label: "Year to date" },
    { id: "prev_year", label: "Previous year" },
    { id: "mtd", label: "Month to date" },
    { id: "last_month", label: "Last month" },
    { id: "custom", label: "Custom" },
  ];

  /** A preset -> {from, to} as "YYYY-MM-DD"; null means unbounded. */
  function presetRange(preset, now) {
    var t = today(now), y = Number(t.slice(0, 4)), m = t.slice(5, 7);
    if (preset === "ytd") return { from: y + "-01-01", to: t };
    if (preset === "prev_year") return { from: (y - 1) + "-01-01", to: (y - 1) + "-12-31" };
    if (preset === "mtd") return { from: y + "-" + m + "-01", to: t };
    if (preset === "last_month") {
      var pm = m === "01" ? (y - 1) + "-12" : y + "-" + String(Number(m) - 1).padStart(2, "0");
      return { from: pm + "-01", to: lastDayOf(pm) };
    }
    return { from: null, to: null };                       // "all", and "custom" before entry
  }

  function lastDayOf(monthKey) {
    var y = Number(monthKey.slice(0, 4)), m = Number(monthKey.slice(5, 7));
    return monthKey + "-" + String(new Date(Date.UTC(y, m, 0)).getUTCDate()).padStart(2, "0");
  }

  /** "YYYY-MM-DD" shifted n months, the way a spreadsheet means it (Excel EDATE):
   *  keep the day of the month, and clamp to the target month's last day.
   *  2026-05-31 minus 15 months is 2025-02-28, not "2025-03-03".
   *
   *  Deliberately NOT `new Date(y, m + n, d)`: JS rolls an out-of-range day forward into the next
   *  month, so a 31st would silently land days later and a trailing window would start on the
   *  wrong side of a month boundary. Integer month arithmetic keeps it in day-string space, which
   *  is the only space inWin understands. */
  function shiftMonths(day, n) {
    var y = Number(day.slice(0, 4)), m = Number(day.slice(5, 7)), d = Number(day.slice(8, 10));
    var idx = y * 12 + (m - 1) + n;
    var key = Math.floor(idx / 12) + "-" + String(((idx % 12) + 12) % 12 + 1).padStart(2, "0");
    var last = Number(lastDayOf(key).slice(8, 10));
    return key + "-" + String(Math.min(d, last)).padStart(2, "0");
  }

  /** "YYYY-MM-DD" shifted n days. UTC arithmetic on the day string itself, so a daylight-saving
   *  boundary can never move the answer by a day. */
  function shiftDays(day, n) {
    var t = new Date(day + "T00:00:00Z");
    t.setUTCDate(t.getUTCDate() + n);
    return t.toISOString().slice(0, 10);
  }

  /** Is this Central day inside the window? Bounds are INCLUSIVE, matching how
   *  the captions read ("between 01/01/2026 - 07/31/2026"). A row with no date
   *  never counts — not even for "All time", because the metric asking is
   *  always asking about a specific date it doesn't have. */
  function inWin(day, win) {
    if (!day) return false;
    if (win.from && day < win.from) return false;
    if (win.to && day > win.to) return false;
    return true;
  }

  function has(list, values) {
    for (var i = 0; i < values.length; i++) if (list.indexOf(values[i]) !== -1) return true;
    return false;
  }

  var NO_TRADE = "__none__";                        // the untagged bucket's sentinel

  /** Dimension filters. An empty selection means "no constraint", so the default
   *  view is everything; selections within a dimension are OR, across dimensions
   *  AND — which is the combination Basisboard can't express. */
  function applyFilters(rows, f) {
    f = f || {};
    var tr = f.trades || [], es = f.estimators || [], co = f.companies || [], st = f.stages || [];
    if (!tr.length && !es.length && !co.length && !st.length) return rows;
    var wantUntagged = tr.indexOf(NO_TRADE) !== -1;
    var realTrades = tr.filter(function (t) { return t !== NO_TRADE; });

    return rows.filter(function (r) {
      if (tr.length) {
        var hit = (wantUntagged && !r.trades.length) ||
                  (realTrades.length && has(r.trades, realTrades));
        if (!hit) return false;
      }
      if (es.length && !has(r.estimator_ids, es)) return false;
      if (co.length) {
        var cos = r.awarded_by_id ? r.company_ids.concat([r.awarded_by_id]) : r.company_ids;
        if (!has(cos, co)) return false;
      }
      if (st.length && st.indexOf(r.stage_id) === -1) return false;
      return true;
    });
  }

  /** The two base selections every metric is built from. */
  function sets(rows, win) {
    var sub = [], aw = [];
    for (var i = 0; i < rows.length; i++) {
      if (inWin(rows[i]._su, win)) sub.push(rows[i]);
      if (inWin(rows[i]._aw, win)) aw.push(rows[i]);
    }
    return { sub: sub, aw: aw };
  }

  function sum(rows, key) {
    var t = 0;
    for (var i = 0; i < rows.length; i++) t += (rows[i][key] || 0);
    return t;
  }

  /** A ratio that refuses to lie: no denominator means no answer (the UI shows
   *  "—"), and a result over 100% is left alone because it happens — a job can
   *  be awarded for more than it was submitted at. */
  function ratio(num, den) {
    return { num: num, den: den, ratio: den ? num / den : null };
  }

  /** The eight Overview numbers. */
  function metrics(rows, win) {
    var s = sets(rows, win);
    var subAwarded = s.sub.filter(function (r) { return !!r._aw; });
    var awSubmitted = s.aw.filter(function (r) { return !!r._su; });
    return {
      wonAmount: sum(s.aw, "won_amount"),
      nAwarded: s.aw.length,
      submittedAmount: sum(s.sub, "submitted_amount"),
      nSubmitted: s.sub.length,
      winProjSub: ratio(subAwarded.length, s.sub.length),
      winAmtSub: ratio(sum(subAwarded, "won_amount"), sum(s.sub, "submitted_amount")),
      winProjAw: ratio(s.aw.length, awSubmitted.length),
      winAmtAw: ratio(sum(s.aw, "won_amount"), sum(s.aw, "submitted_amount")),
      _sets: s,
      _subAwarded: subAwarded,
    };
  }

  /** Months between the window bounds (or the data's own span for "All time"),
   *  materialized CONTIGUOUSLY so a month with no bids reads as a zero bar
   *  rather than silently closing the gap. */
  function byMonth(rows, win, dayKey, amountKey) {
    var picked = rows.filter(function (r) { return inWin(r[dayKey], win); });
    var buckets = {};
    var lo = win.from ? win.from.slice(0, 7) : null;
    var hi = win.to ? win.to.slice(0, 7) : null;
    for (var i = 0; i < picked.length; i++) {
      var k = picked[i][dayKey].slice(0, 7);
      if (!buckets[k]) buckets[k] = { key: k, label: monthLabel(k), amount: 0, count: 0, rows: [] };
      buckets[k].amount += (picked[i][amountKey] || 0);
      buckets[k].count += 1;
      buckets[k].rows.push(picked[i]);
      if (!lo || k < lo) lo = k;
      if (!hi || k > hi) hi = k;
    }
    if (!lo || !hi) return [];
    var out = [], guard = 0;
    for (var k2 = lo; k2 <= hi && guard < 600; k2 = addMonth(k2), guard++) {
      out.push(buckets[k2] || { key: k2, label: monthLabel(k2), amount: 0, count: 0, rows: [] });
    }
    return out;
  }

  /** Current stage of everything whose bid deadline falls in the window — the
   *  two stage cards. Every configured stage appears, zero rows included. */
  function byStage(rows, win, stages) {
    var picked = rows.filter(function (r) { return inWin(r._bd, win); });
    var by = {};
    for (var i = 0; i < picked.length; i++) {
      var id = picked[i].stage_id || "";
      if (!by[id]) by[id] = { amount: 0, count: 0, rows: [] };
      by[id].amount += (picked[i].submitted_amount || 0);
      by[id].count += 1;
      by[id].rows.push(picked[i]);
    }
    var totalAmt = 0, totalCnt = picked.length;
    for (var k in by) if (by.hasOwnProperty(k)) totalAmt += by[k].amount;

    var out = stages.map(function (s) {
      var b = by[s.id] || { amount: 0, count: 0, rows: [] };
      delete by[s.id];
      return {
        key: s.id, label: s.name, color: s.color,
        amount: b.amount, count: b.count, rows: b.rows,
        pctAmount: totalAmt ? b.amount / totalAmt : 0,
        pctCount: totalCnt ? b.count / totalCnt : 0,
      };
    });
    // A row can sit in a stage the settings no longer list; show it rather than
    // let the totals stop adding up.
    for (var leftover in by) {
      if (!by.hasOwnProperty(leftover)) continue;
      out.push({
        key: leftover, label: "Unstaged", color: "#5c403f",
        amount: by[leftover].amount, count: by[leftover].count, rows: by[leftover].rows,
        pctAmount: totalAmt ? by[leftover].amount / totalAmt : 0,
        pctCount: totalCnt ? by[leftover].count / totalCnt : 0,
      });
    }
    out.sort(function (a, b) { return b.amount - a.amount || b.count - a.count; });
    return out;
  }

  var DIMS = {
    trade: { keys: function (r) { return r.trades; }, empty: "(No trade)" },
    estimator: { keys: function (r) { return r.estimator_ids; }, empty: "(No estimator)" },
    company: { keys: function (r) { return r.company_ids; }, empty: "(No company)" },
  };

  /** Group by trade / estimator / company, returning every dimension card at once.
   *
   *  A project with two trades counts in BOTH — the same way Basisboard reports
   *  it, and the only answer that doesn't hide work. It does mean the buckets
   *  sum to more than the overview total, which the tab says out loud.
   *
   *  Won-side company attribution prefers `awarded_by_id` (the company that
   *  actually awarded it) and falls back to the sole bidding company; a project
   *  with neither lands in "(No company)" rather than being spread across every
   *  GC that invited it. */
  function byDimension(rows, win, dim, ctx) {
    var spec = DIMS[dim], name = (ctx && ctx.name) || function (k) { return k; };
    var s = sets(rows, win);
    var groups = {};

    function bucket(key) {
      if (!groups[key]) {
        groups[key] = {
          key: key, label: key === "" ? spec.empty : name(key),
          wonAmount: 0, submittedAmount: 0, nAwarded: 0, nSubmitted: 0,
          submittedForWin: 0, wonForWin: 0, nSubForWin: 0, nAwForWin: 0,
          rowsWon: [], rowsSub: [],
        };
      }
      return groups[key];
    }

    function keysFor(r, side) {
      if (dim === "company" && side === "won") {
        if (r.awarded_by_id) return [r.awarded_by_id];
        return r.company_ids.length === 1 ? r.company_ids : [];
      }
      var ks = spec.keys(r) || [];
      return ks.length ? ks : [];
    }

    function each(r, side, fn) {
      var ks = keysFor(r, side);
      if (!ks.length) { fn(bucket("")); return; }
      for (var i = 0; i < ks.length; i++) fn(bucket(ks[i]));
    }

    s.aw.forEach(function (r) {
      each(r, "won", function (g) {
        g.wonAmount += (r.won_amount || 0);
        g.nAwarded += 1;
        g.rowsWon.push(r);
      });
    });
    s.sub.forEach(function (r) {
      each(r, "sub", function (g) {
        g.submittedAmount += (r.submitted_amount || 0);
        g.nSubmitted += 1;
        g.rowsSub.push(r);
        // Win rate is measured over what was SUBMITTED in the window, so both
        // halves of the ratio come from the same set of bids.
        g.submittedForWin += (r.submitted_amount || 0);
        g.nSubForWin += 1;
        if (r._aw) { g.wonForWin += (r.won_amount || 0); g.nAwForWin += 1; }
      });
    });

    var out = [];
    for (var k in groups) {
      if (!groups.hasOwnProperty(k)) continue;
      var g = groups[k];
      g.winAmt = ratio(g.wonForWin, g.submittedForWin);
      g.winProj = ratio(g.nAwForWin, g.nSubForWin);
      out.push(g);
    }
    return out;
  }

  // ── Kyle's trailing-12 ritual ──────────────────────────────────────────────
  // He does this by hand in "Trailing 12TH MONTH.xlsx": pull BasisBoard twice with two custom
  // date ranges, paste six numbers per trade into a fresh dated tab, and read the win rates off
  // the formulas. The point of the 15-month span is the SUBTRACTION, in his words: "if its a
  // normal 12 month trail then its including 3 months worth of projects that is too early to
  // know" — a bid submitted last month has not been decided yet, so counting it in the
  // denominator understates the win rate. So: award numerator over a 15-month window, denominator
  // that same window MINUS the last 90 days of submissions. What is left is a true trailing
  // twelve months that ended 90 days ago.
  var T12_TRADES = ["Gyp", "Epoxy", "Polish"];

  /** The whole ritual, computed.
   *
   *  `todayStr` is REQUIRED rather than read from the clock: the page passes today(), and tests
   *  inject a fixed day, so nothing in here is time-dependent.
   *
   *  Built ON metrics()/sets() rather than beside them — the won and submitted definitions are
   *  then the SAME ones the Overview tab shows, by construction rather than by two formulas that
   *  agree today. Ratios come back as ratio() objects, so an empty denominator is null ("—")
   *  instead of a divide-by-zero. */
  function trailing12(rows, todayStr, trades) {
    var w15 = { from: shiftMonths(todayStr, -15), to: todayStr };
    var w90 = { from: shiftDays(todayStr, -90), to: todayStr };

    function col(key, label, subset) {
      var m = metrics(subset, w15);
      var s90 = sets(subset, w90);
      var sub90 = sum(s90.sub, "submitted_amount");
      var nSub90 = s90.sub.length;
      return {
        key: key, label: label,
        wonAmount: m.wonAmount, nAwarded: m.nAwarded,                 // sheet C4, C12
        submittedAmount: m.submittedAmount, nSubmitted: m.nSubmitted, // sheet C5, C13
        sub90Amount: sub90, nSub90: nSub90,                           // sheet C8, C16
        winVol: ratio(m.wonAmount, m.submittedAmount),                // sheet C6
        winVolEx90: ratio(m.wonAmount, m.submittedAmount - sub90),    // sheet C10
        winProj: ratio(m.nAwarded, m.nSubmitted),                     // sheet C14
        winProjEx90: ratio(m.nAwarded, m.nSubmitted - nSub90),        // sheet C18
        avgBid: ratio(m.submittedAmount, m.nSubmitted),               // sheet C20
        avgWin: ratio(m.wonAmount, m.nAwarded),                       // sheet C21
      };
    }

    var out = { today: todayStr, w15: w15, w90: w90,
                columns: [col("all", "All Bids", rows)] };
    // Same multi-tag rule as DIMS.trade: a project tagged Gyp AND Epoxy counts under both, so the
    // trade columns can add to more than All Bids. The card says so out loud.
    (trades || T12_TRADES).forEach(function (t) {
      out.columns.push(col(t, t, rows.filter(function (r) {
        return (r.trades || []).indexOf(t) !== -1;
      })));
    });
    return out;
  }

  /** Biggest first by default — a ranked list is the point of these cards. */
  function sortBy(items, key, dir) {
    var asc = dir === "asc";
    return items.slice().sort(function (a, b) {
      var av = a[key], bv = b[key];
      if (av === null || av === undefined) av = -Infinity;
      if (bv === null || bv === undefined) bv = -Infinity;
      if (av === bv) return String(a.label).localeCompare(String(b.label));
      return asc ? (av - bv) : (bv - av);
    });
  }

  return {
    BIZ_TZ: BIZ_TZ, NO_TRADE: NO_TRADE, PRESETS: PRESETS, DIMS: DIMS,
    bizDay: bizDay, monthLabel: monthLabel, today: today, lastDayOf: lastDayOf,
    shiftMonths: shiftMonths, shiftDays: shiftDays,
    decorate: decorate, presetRange: presetRange, inWin: inWin,
    applyFilters: applyFilters, sets: sets, sum: sum, ratio: ratio,
    metrics: metrics, byMonth: byMonth, byStage: byStage, byDimension: byDimension,
    trailing12: trailing12, T12_TRADES: T12_TRADES,
    sortBy: sortBy,
  };
});
