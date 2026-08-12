// Analytics page controller.
// Externalized from analytics.html (CSP: drop script-src 'unsafe-inline').
// Do not add inline scripts. No onclick attributes — every handler is delegated
// from a container, so innerHTML re-renders are safe.
//
// The page fetches ONE payload (/api/analytics: every bid as a flat row) and
// re-totals it locally on every filter change. That is the whole design: asking
// for "epoxy + gyp, Greg and Troy, awarded this quarter" costs no round trip,
// and the four tabs are four views of the same numbers rather than four queries.
(function () {
  "use strict";

  var X = window.TWAgg, C = window.TWCharts;
  var STATE_KEY = "tw_analytics_state";

  var DATA = null;        // the decoded payload
  var ROWS = [];          // decorated rows
  var NAMES = { estimator: {}, company: {}, stage: {} };
  var STAGES = [];
  var OPEN_POP = null;

  var STATE = {
    tab: "overview", preset: "ytd", from: "", to: "",
    trades: [], estimators: [], companies: [], stages: [], charts: {},
  };

  // ── plumbing ────────────────────────────────────────────────────────
  function $(id) { return document.getElementById(id); }
  var esc = C.esc;

  function api(path, opts) {
    opts = opts || {};
    // Merge, don't replace: passing our own headers object would drop the bearer.
    return fetch(TW.resolveApiBase() + path,
                 Object.assign({}, opts, { headers: TW.authHeaders(opts.headers) }));
  }

  /** auth.js mints the token asynchronously; wait briefly rather than 401. */
  function tokenSoon() {
    return new Promise(function (res) {
      if (window.__TW_TOKEN) return res(true);
      var n = 0;
      var t = setInterval(function () {
        if (window.__TW_TOKEN || ++n > 200) { clearInterval(t); res(!!window.__TW_TOKEN); }
      }, 40);
    });
  }

  function loadState() {
    try {
      var s = JSON.parse(sessionStorage.getItem(STATE_KEY) || "null");
      if (s && typeof s === "object") Object.assign(STATE, s);
    } catch (e) { /* a corrupt blob just means defaults */ }
  }
  function persist() {
    try { sessionStorage.setItem(STATE_KEY, JSON.stringify(STATE)); } catch (e) { /* private mode */ }
  }

  function win() {
    if (STATE.preset === "custom") {
      return { from: STATE.from || null, to: STATE.to || null };
    }
    return X.presetRange(STATE.preset);
  }

  /** The window in the words the cards use. */
  function winText(prefix) {
    var w = win();
    if (!w.from && !w.to) return prefix + " across all time.";
    var us = function (d) {
      if (!d) return "";
      var p = d.split("-");
      return p[1] + "/" + p[2] + "/" + p[0];
    };
    if (w.from && w.to) return prefix + " between " + us(w.from) + " and " + us(w.to) + ".";
    return prefix + (w.from ? " on or after " + us(w.from) : " on or before " + us(w.to)) + ".";
  }

  function filtered() { return X.applyFilters(ROWS, STATE); }

  // ── identity: a colour per estimator, a pill per stage ──────────────
  // Colour is a shortcut, never the message: every chip carries the initials and
  // the name, every pill carries the stage's word. Someone who can't tell two
  // hues apart loses nothing.
  // Estimator colours and initials come from crm-core, the one place that decides them.
  // This page used to index into the CHART palette by roster position, which gave the
  // same person a different colour here than on the CRM board — and repainted everybody
  // whenever somebody joined. crm-core hashes a first name instead, so Kyle is the same
  // colour on a chart, a board card and a Projects row, and BasisBoard's display names
  // line up with our own email-keyed screens.
  function estColor(id) { return window.TWCrm.colorOf(NAMES.estimator[id] || id); }

  /** An estimator, as a coloured initial + their name. */
  function estChip(id) {
    var name = NAMES.estimator[id] || "Unknown";
    // The same chip class the rest of the app uses (defined in auth.js's injected
    // stylesheet), rather than this page's private `.av`.
    return '<span class="who">' + window.TWCrm.avatarHtml(name) + esc(name) + "</span>";
  }

  function estChips(ids) {
    if (!ids || !ids.length) return '<span class="fnote">—</span>';
    return '<span class="whos">' + ids.map(estChip).join("") + "</span>";
  }

  /** A stage, as a pill in its own colour. */
  function stagePill(id) {
    var s = STAGES.filter(function (x) { return x.id === id; })[0] ||
            { name: "Unstaged", color: "#8a857c" };
    return '<span class="pill" style="background:' + C.tint(s.color, 0.14) + ";color:" +
      C.darken(s.color, 0.35) + '"><span class="dot" style="background:' + esc(s.color) +
      '"></span>' + esc(s.name) + "</span>";
  }

  // ── tabs ────────────────────────────────────────────────────────────
  var TABS = [
    { id: "overview", label: "Overview" },
    { id: "trades", label: "Trades", dim: "trade", noun: "Trade" },
    { id: "estimators", label: "Estimators", dim: "estimator", noun: "Estimator" },
    { id: "companies", label: "Companies", dim: "company", noun: "Company" },
  ];
  function tab() { return TABS.filter(function (t) { return t.id === STATE.tab; })[0] || TABS[0]; }

  function renderTabs() {
    $("tabs").innerHTML = TABS.map(function (t) {
      return '<button class="tab' + (t.id === STATE.tab ? " sel" : "") +
        '" data-tab="' + t.id + '">' + esc(t.label) + "</button>";
    }).join("");
  }

  // ── filter bar ──────────────────────────────────────────────────────
  var DIMENSIONS = [
    { key: "trades", label: "Trades" },
    { key: "estimators", label: "Estimators" },
    { key: "companies", label: "Companies" },
    { key: "stages", label: "Stages" },
  ];

  /** Options for a dimension as [{id, name}]. Trades are bare strings, and get
   *  a synthetic bucket so untagged jobs stay reachable rather than invisible. */
  function options(key) {
    if (!DATA) return [];
    if (key === "trades") {
      var t = (DATA.trades || []).map(function (s) { return { id: s, name: s }; });
      return [{ id: X.NO_TRADE, name: "(No trade)" }].concat(t);
    }
    if (key === "estimators") return DATA.estimators || [];
    if (key === "companies") return DATA.companies || [];
    return (DATA.stages || []).map(function (s) { return { id: s.id, name: s.name }; });
  }

  function renderFilterBar() {
    var w = win();
    var presets = X.PRESETS.map(function (p) {
      return '<option value="' + p.id + '"' + (p.id === STATE.preset ? " selected" : "") +
        ">" + esc(p.label) + "</option>";
    }).join("");

    var custom = "";
    if (STATE.preset === "custom") {
      // Typed, not clicked. Kyle's complaint about BasisBoard is that its custom
      // range is a calendar you have to page through; a date input takes the
      // keyboard.
      custom = '<input type="date" id="f-from" value="' + esc(STATE.from || "") +
        '" aria-label="From date" max="' + esc(STATE.to || "") + '" />' +
        '<span class="fnote">to</span>' +
        '<input type="date" id="f-to" value="' + esc(STATE.to || "") +
        '" aria-label="To date" min="' + esc(STATE.from || "") + '" />';
    }

    var chips = DIMENSIONS.map(function (d) {
      var n = (STATE[d.key] || []).length;
      return '<div class="msel" data-dim="' + d.key + '">' +
        '<button class="chip' + (n ? " sel" : "") + '" data-pop="' + d.key + '">' +
        esc(d.label) + (n ? ' <span class="n">' + n + "</span>" : "") +
        '<span class="caret">▼</span></button></div>';
    }).join("");

    $("filterbar").innerHTML =
      '<span class="fb-lab">Dates</span><select id="f-preset" aria-label="Date range">' +
      presets + "</select>" + custom +
      '<span class="fb-lab" style="margin-left:8px">Filters</span>' + chips;

    // Custom with nothing typed yet would silently mean "all time"; say so.
    if (STATE.preset === "custom" && !w.from && !w.to) {
      $("filterbar").insertAdjacentHTML("beforeend",
        '<span class="fnote">— pick dates, or it counts everything</span>');
    }
    // Asking for a slice this tool does not hold. The filter is NOT clamped to the pull window —
    // silently moving somebody's dates is worse than an empty answer — but an empty chart has to
    // say which of the two ranges is the reason.
    var pw = pullWindow();
    var outside = [];
    if (pw.from && w.from && w.from < pw.from) outside.push("before " + esc(pw.from));
    if (pw.to && w.to && w.to > pw.to) outside.push("after " + esc(pw.to));
    if (outside.length) {
      $("filterbar").insertAdjacentHTML("beforeend",
        '<span class="fnote">— we only hold ' + esc(pw.from || "the beginning") + " → " +
        esc(pw.to || "today") + ", so " + outside.join(" and ") + " is empty</span>");
    }
  }

  /** The colour that belongs to one filter option, if it has one. */
  function optDot(dimKey, id) {
    if (dimKey === "estimators") {
      return '<span class="dot" style="background:' + estColor(id) + '"></span>';
    }
    if (dimKey === "stages") {
      var s = STAGES.filter(function (x) { return x.id === id; })[0];
      if (s) return '<span class="dot" style="background:' + esc(s.color) + '"></span>';
    }
    return "";
  }

  function renderActiveFilters() {
    var out = [];
    DIMENSIONS.forEach(function (d) {
      var opts = options(d.key);
      (STATE[d.key] || []).forEach(function (id) {
        var hit = opts.filter(function (o) { return o.id === id; })[0];
        out.push('<span class="fchip">' + optDot(d.key, id) + esc(hit ? hit.name : id) +
          '<button data-clear-one="' + d.key + '" data-id="' + esc(id) +
          '" aria-label="Remove filter">×</button></span>');
      });
    });
    if (out.length) {
      out.push('<button class="linkbtn" data-clear-all="1">Clear filters</button>');
      var n = filtered().length;
      out.push('<span class="fnote">' + C.fmtInt(n) + " of " + C.fmtInt(ROWS.length) +
        " projects match</span>");
    }
    $("active-filters").innerHTML = out.join("");
  }

  function closePop() {
    if (OPEN_POP) { OPEN_POP.remove(); OPEN_POP = null; }
  }

  function openPop(dimKey, anchor) {
    closePop();
    var opts = options(dimKey);
    var sel = STATE[dimKey] || [];
    var pop = document.createElement("div");
    pop.className = "pop";
    pop.setAttribute("data-dim", dimKey);
    pop.innerHTML =
      '<input class="psearch search" type="search" placeholder="Filter…" aria-label="Filter options" />' +
      '<div class="plist">' + opts.map(function (o) {
        return '<label><input type="checkbox" value="' + esc(o.id) + '"' +
          (sel.indexOf(o.id) !== -1 ? " checked" : "") + " />" + optDot(dimKey, o.id) +
          "<span>" + esc(o.name) + "</span></label>";
      }).join("") + "</div>" +
      '<div class="pfoot"><button class="linkbtn" data-all="1">Select all</button>' +
      '<button class="linkbtn" data-none="1">Clear</button></div>';
    anchor.appendChild(pop);
    OPEN_POP = pop;
    var s = pop.querySelector(".psearch");
    if (s) s.focus();
  }

  // ── the card registry ───────────────────────────────────────────────
  // Each card knows how to compute itself, what to caption itself with, and
  // which rows sit underneath it — so "See Breakdown" is the same mechanism
  // everywhere rather than a special case per metric.
  var CAP = {
    won: "Includes amounts won on bids awarded",
    sub: "Includes bids submitted",
    deadline: "Includes bids with a deadline",
  };

  /** Month buckets in the shape the charts read: one `value`, plus the rows
   *  behind it so clicking a bar can open them. */
  function months(dayKey, amountKey) {
    return X.byMonth(filtered(), win(), dayKey, amountKey).map(function (b) {
      return { key: b.key, label: b.label, value: b.amount, count: b.count, rows: b.rows };
    });
  }

  /** The Overview.
   *
   *  Each side leads with ONE number — the money, with the project count folded
   *  into its subline rather than given a card of its own. Ten equal cards meant
   *  nothing was the headline; the eye had to read all of them to find out which
   *  mattered. The two win rates then sit as a pair of small tiles, each with a
   *  meter, so a percentage has a shape as well as a value. */
  function overviewCards(m) {
    var s = m._sets;
    return [
      { id: "won_amount", side: "won", kind: "hero", title: "Won",
        value: C.fmtMoney(m.wonAmount),
        sub: "across " + C.fmtInt(m.nAwarded) + " awarded " +
             (m.nAwarded === 1 ? "project" : "projects"),
        cap: CAP.won, rows: s.aw, dateKey: "awarded_at" },
      { id: "win_proj_aw", side: "won", kind: "tile", title: "Win rate · projects",
        value: C.fmtPct(m.winProjAw.ratio), ratio: m.winProjAw.ratio,
        sub: C.fmtInt(m.winProjAw.num) + " of " + C.fmtInt(m.winProjAw.den) + " also submitted",
        cap: CAP.won, rows: s.aw, dateKey: "awarded_at" },
      { id: "win_amt_aw", side: "won", kind: "tile", title: "Win rate · amount",
        value: C.fmtPct(m.winAmtAw.ratio), ratio: m.winAmtAw.ratio,
        sub: C.fmtMoney(m.winAmtAw.num) + " of " + C.fmtMoney(m.winAmtAw.den) + " bid",
        cap: CAP.won, rows: s.aw, dateKey: "awarded_at" },
      { id: "awarded_by_month", side: "won", kind: "chart", title: "Awarded by month",
        charts: ["bar", "line", "list"], def: "bar", fmt: "moneyShort", noun: "Month",
        data: function () { return months("_aw", "won_amount"); },
        cap: CAP.won, rows: s.aw, dateKey: "awarded_at" },

      { id: "submitted_amount", side: "sub", kind: "hero", title: "Submitted",
        value: C.fmtMoney(m.submittedAmount),
        sub: "across " + C.fmtInt(m.nSubmitted) + " submitted " +
             (m.nSubmitted === 1 ? "project" : "projects"),
        cap: CAP.sub, rows: s.sub, dateKey: "submitted_at" },
      { id: "win_proj_sub", side: "sub", kind: "tile", title: "Win rate · projects",
        value: C.fmtPct(m.winProjSub.ratio), ratio: m.winProjSub.ratio,
        sub: C.fmtInt(m.winProjSub.num) + " won of " + C.fmtInt(m.winProjSub.den),
        cap: CAP.sub, rows: m._subAwarded, dateKey: "submitted_at" },
      { id: "win_amt_sub", side: "sub", kind: "tile", title: "Win rate · amount",
        value: C.fmtPct(m.winAmtSub.ratio), ratio: m.winAmtSub.ratio,
        sub: C.fmtMoney(m.winAmtSub.num) + " of " + C.fmtMoney(m.winAmtSub.den),
        cap: CAP.sub, rows: m._subAwarded, dateKey: "submitted_at" },
      { id: "submitted_by_month", side: "sub", kind: "chart", title: "Submitted by month",
        charts: ["bar", "line", "list"], def: "bar", fmt: "moneyShort", noun: "Month",
        data: function () { return months("_su", "submitted_amount"); },
        cap: CAP.sub, rows: s.sub, dateKey: "submitted_at" },
    ];
  }

  function stageCards() {
    var groups = X.byStage(filtered(), win(), STAGES);
    var rows = groups.reduce(function (a, g) { return a.concat(g.rows); }, []);
    return [
      { id: "stage_amount", side: "won", kind: "chart", title: "Submitted amount by stage (current)",
        charts: ["list", "bar", "pie"], def: "list", fmt: "money", groups: groups,
        stage: "amount", cap: CAP.deadline, rows: rows, dateKey: "bid_deadline_at" },
      { id: "stage_count", side: "sub", kind: "chart", title: "# Projects by stage (current)",
        charts: ["list", "bar", "pie"], def: "list", fmt: "int", groups: groups,
        stage: "count", cap: CAP.deadline, rows: rows, dateKey: "bid_deadline_at" },
    ];
  }

  function dimensionCards(t) {
    var groups = X.byDimension(filtered(), win(), t.dim, {
      name: function (k) { return NAMES[t.dim][k] || k; },
    });
    var mk = function (id, side, title, valueKey, fmt, rowsKey, dateKey, cap) {
      return {
        id: id, side: side, kind: "chart", title: title,
        charts: ["bar", "pie", "list"], def: "bar", fmt: fmt,
        items: X.sortBy(groups, valueKey).filter(function (g) { return g[valueKey] > 0; })
          .map(function (g) {
            return { key: g.key, label: g.label, value: g[valueKey], rows: g[rowsKey],
                     // On the Estimators tab each person keeps their own colour,
                     // so the eye can follow one of them across every card.
                     color: t.dim === "estimator" && g.key ? estColor(g.key) : null };
          }),
        cap: cap, dateKey: dateKey,
        rows: groups.reduce(function (a, g) { return a.concat(g[rowsKey]); }, []),
      };
    };
    return [
      mk("won_by", "won", "Won amount by " + t.noun.toLowerCase(), "wonAmount", "moneyShort",
         "rowsWon", "awarded_at", CAP.won),
      mk("n_awarded_by", "won", "# Awarded by " + t.noun.toLowerCase(), "nAwarded", "int",
         "rowsWon", "awarded_at", CAP.won),
      mk("submitted_by", "sub", "Submitted amount by " + t.noun.toLowerCase(), "submittedAmount",
         "moneyShort", "rowsSub", "submitted_at", CAP.sub),
      mk("n_submitted_by", "sub", "# Submitted by " + t.noun.toLowerCase(), "nSubmitted", "int",
         "rowsSub", "submitted_at", CAP.sub),
      { id: "win_ratio", side: "won", kind: "winlist", title: "Win rate by amount", groups: groups,
        mode: "amount", cap: CAP.sub, noun: t.noun, dim: t.dim, dateKey: "submitted_at",
        rows: groups.reduce(function (a, g) { return a.concat(g.rowsSub); }, []) },
      { id: "win_ratio_proj", side: "sub", kind: "winlist", title: "Win rate by # projects",
        groups: groups, mode: "count", cap: CAP.sub, noun: t.noun, dim: t.dim,
        dateKey: "submitted_at",
        rows: groups.reduce(function (a, g) { return a.concat(g.rowsSub); }, []) },
    ];
  }

  // ── rendering ───────────────────────────────────────────────────────
  var CARDS = {};          // id -> card, so a click can find its rows again

  function chartFor(card) {
    return STATE.charts[STATE.tab + ":" + card.id] || card.def;
  }

  function cardBody(card, mode) {
    if (card.kind === "hero" || card.kind === "tile" || card.kind === "kpi") {
      return '<div class="kpi">' + esc(card.value) + "</div>" +
        (card.kind === "tile" ? C.meter(card.ratio) : "") +
        (card.sub ? '<div class="kpi-sub">' + esc(card.sub) + "</div>" : "");
    }
    if (card.kind === "winlist") {
      var amount = card.mode === "amount";
      var byEst = card.dim === "estimator";
      var rows = X.sortBy(card.groups, amount ? "submittedAmount" : "nSubmitted")
        .filter(function (g) { return (amount ? g.winAmt.den : g.winProj.den) > 0; })
        .map(function (g) {
          var r = amount ? g.winAmt : g.winProj;
          return { key: g.key, label: g.label,
                   labelHtml: byEst && g.key ? estChip(g.key) : null,
                   sub: amount ? C.fmtMoney(r.den) : C.fmtInt(r.den),
                   aw: amount ? C.fmtMoney(r.num) : C.fmtInt(r.num),
                   pct: C.fmtPct(r.ratio) };
        });
      return C.listTable({
        rows: rows, empty: "No bids match these filters.",
        columns: [{ key: "label", label: card.noun, html: "labelHtml" },
                  { key: "sub", label: "Submitted", align: "right" },
                  { key: "aw", label: "Awarded", align: "right" },
                  { key: "pct", label: "Win %", align: "right" }],
      });
    }

    // stage cards carry their own shape
    if (card.groups && card.stage) {
      var key = card.stage;                       // "amount" | "count"
      var items = card.groups.map(function (g) {
        return { key: g.key, label: g.label, value: g[key], color: g.color,
                 pct: C.fmtPct(key === "amount" ? g.pctAmount : g.pctCount) };
      });
      if (mode === "list") {
        return C.listTable({
          rows: items.map(function (i) {
            return { key: i.key, label: i.label, color: i.color, labelHtml: stagePill(i.key),
                     val: key === "amount" ? C.fmtMoney(i.value) : C.fmtInt(i.value), pct: i.pct };
          }),
          empty: "No bids match these filters.",
          columns: [{ key: "label", label: "Stage", html: "labelHtml" },
                    { key: "val", label: key === "amount" ? "Amount" : "Count", align: "right" },
                    { key: "pct", label: "% of total", align: "right" }],
        });
      }
      var live = items.filter(function (i) { return i.value > 0; });
      if (mode === "pie") return C.donut({ items: live, fmt: card.fmt, aria: card.title });
      return C.hbar({ items: live, fmt: card.fmt, aria: card.title });
    }

    var data = card.items || (card.data ? card.data() : []);
    if (mode === "list") {
      return C.listTable({
        rows: data.map(function (d) {
          return { key: d.key, label: d.label,
                   labelHtml: tab().dim === "estimator" && d.key ? estChip(d.key) : null,
                   val: card.fmt === "int" ? C.fmtInt(d.value) : C.fmtMoney(d.value) };
        }),
        empty: "Nothing in this window.",
        columns: [{ key: "label", label: card.noun || "", html: "labelHtml" },
                  { key: "val", label: card.fmt === "int" ? "Projects" : "Amount", align: "right" }],
      });
    }
    if (mode === "pie") return C.donut({ items: data, fmt: card.fmt, aria: card.title });
    if (mode === "line") return C.line({ items: data, fmt: card.fmt, aria: card.title });
    if (card.items) return C.hbar({ items: data, fmt: card.fmt, aria: card.title });
    return C.bar({ items: data, fmt: card.fmt, aria: card.title });
  }

  var CHART_LABEL = { bar: "Bar", line: "Line", pie: "Pie", list: "List" };

  function cardHtml(card) {
    CARDS[card.id] = card;
    var mode = chartFor(card);
    var types = (card.charts || []).map(function (t) {
      // A trend needs a time axis; on a dimension card there isn't one.
      var off = t === "line" && !card.data;
      return '<button class="ctype' + (t === mode ? " sel" : "") + '" data-chart="' + t +
        '" data-card="' + card.id + '"' +
        (off ? ' disabled title="A line needs a time axis"' : "") +
        ">" + CHART_LABEL[t] + "</button>";
    }).join("");

    // The small tiles skip the window caption: it's two lines of the same
    // sentence already sitting on the hero card directly above them, and on a
    // tile it out-weighs the number it's supposed to footnote.
    var caption = card.kind === "tile" ? ""
      : '<p class="caption">' + esc(winText(card.cap)) + "</p>";

    return '<section class="acard clickable' + (card.kind === "tile" ? " tile" : "") +
      '" data-card="' + card.id + '">' +
      '<div class="ah"><h4>' + esc(card.title) + "</h4>" +
      (types ? '<div class="ctypes">' + types + "</div>" : "") + "</div>" +
      cardBody(card, mode) +
      '<button class="brk" data-breakdown="' + card.id + '">See breakdown →</button>' +
      caption + "</section>";
  }

  /** Cards down a column, with consecutive small tiles paired into one row so a
   *  half-height card doesn't leave a half-width hole beside it. */
  function column(cards) {
    var out = [], run = [];
    var flush = function () {
      if (!run.length) return;
      out.push(run.length > 1 ? '<div class="tiles">' + run.join("") + "</div>" : run[0]);
      run = [];
    };
    cards.forEach(function (c) {
      if (c.kind === "tile") { run.push(cardHtml(c)); if (run.length === 2) flush(); return; }
      flush();
      out.push(cardHtml(c));
    });
    flush();
    return out.join("");
  }

  // ── the org's BasisBoard pull window ────────────────────────────────
  // Hanz, 2026-08-12: "we need a date pciker like the custom date in the analytics for when it
  // pulls data" — and, asked, one window for the whole company rather than per viewer.
  //
  // A DIFFERENT QUESTION from the filter bar below it. The filter slices what this tool holds;
  // this sets what it holds at all, for everybody. Two people reading different win rates off the
  // same dashboard is the thing a per-viewer version would cause.
  //
  // Always drawn from the PAYLOAD's window, never from what is typed in these boxes: the caption
  // has to describe the dataset the numbers came from, or a half-finished edit reads as fact.
  function pullWindow() {
    var w = (DATA && DATA.pull_window) || {};
    return { from: w.from || "", to: w.to || "",
             updated_at: w.updated_at || "", updated_by: w.updated_by || "" };
  }

  function renderPullWindow(msg, bad) {
    var el = $("pullwindow");
    if (!el) return;
    var w = pullWindow();
    var by = "";
    if (w.updated_at) {
      var d = new Date(w.updated_at);
      by = "set by " + esc(w.updated_by || "somebody") +
        (isNaN(d.getTime()) ? "" : " on " + X.bizDay(w.updated_at));
    }
    el.innerHTML =
      '<div class="pw">' +
      '<span class="pw-lab">BasisBoard data</span>' +
      '<span>' + (w.from || w.to
        ? "pulling " + esc(w.from || "the beginning") + " → " + esc(w.to || "today")
        : "pulling everything BasisBoard has") + "</span>" +
      '<input type="date" id="pw-from" value="' + esc(w.from) + '" aria-label="Pull data from" ' +
        'max="' + esc(w.to) + '" />' +
      '<span class="fnote">to</span>' +
      '<input type="date" id="pw-to" value="' + esc(w.to) + '" aria-label="Pull data to" ' +
        'min="' + esc(w.from) + '" />' +
      '<button type="button" class="pw-save" id="pw-save">Save range</button>' +
      (msg ? '<span class="pw-msg' + (bad ? " bad" : "") + '">' + esc(msg) + "</span>"
           : '<span class="pw-by">' + by + "</span>") +
      "</div>";
  }

  function savePullWindow() {
    var from = ($("pw-from") || {}).value || "";
    var to = ($("pw-to") || {}).value || "";
    if (from && to && from > to) {
      renderPullWindow("Those dates are backwards.", true);
      return;
    }
    var btn = $("pw-save");
    if (btn) { btn.disabled = true; btn.textContent = "Saving…"; }
    // Returned so a test can await the outcome; nothing in the page depends on the value.
    return api("/api/analytics/pull-window", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ from: from || null, to: to || null }),
    }).then(function (r) {
      if (!r.ok) throw new Error("save failed");
      return r.json();
    }).then(function () {
      // The dataset is being rebuilt for the new dates behind this. Poll the payload rather than
      // echoing what was typed, so the caption only changes once the numbers have.
      renderPullWindow("Saved. Re-reading BasisBoard for those dates…");
      pollForWindow(from, to, 0);
    }).catch(function () {
      renderPullWindow("Couldn't save that range — try again.", true);
    });
  }

  // The window is set; the rows for it take a build (~10s). Keep asking until the payload agrees,
  // then re-render everything off the new dataset.
  function pollForWindow(from, to, n) {
    if (n > 40) { renderPullWindow("Still re-reading BasisBoard. This page will catch up."); return; }
    setTimeout(function () {
      api("/api/analytics").then(function (r) { return r.json(); }).then(function (j) {
        var w = (j && j.pull_window) || {};
        if (j && j.ok && !j.building && (w.from || "") === from && (w.to || "") === to && !j.stale) {
          adopt(j);
          render();
          return;
        }
        pollForWindow(from, to, n + 1);
      }).catch(function () { pollForWindow(from, to, n + 1); });
    }, 3000);
  }

  function render() {
    if (!DATA || !DATA.ok) return;
    CARDS = {};
    renderPullWindow();
    renderTabs();
    renderFilterBar();
    renderActiveFilters();

    var t = tab(), cards;
    if (t.id === "overview") {
      cards = overviewCards(X.metrics(filtered(), win())).concat(stageCards());
    } else {
      cards = dimensionCards(t);
    }

    var side = function (s) {
      return column(cards.filter(function (c) { return c.side === s; }));
    };
    var note = t.dim
      ? '<p class="fnote" style="margin:-10px 0 16px">A project with two ' +
        esc(t.noun.toLowerCase()) + "s counts under each, so these add up to more than the " +
        "overview total.</p>"
      : "";

    $("cards").innerHTML = note +
      '<div class="grid2">' +
      '<div class="col"><div class="colhead">Won</div>' + side("won") + "</div>" +
      '<div class="col"><div class="colhead">Submitted</div>' + side("sub") + "</div></div>";
  }

  // ── breakdown drawer ────────────────────────────────────────────────
  function openBreakdown(title, rows, dateKey) {
    var seen = {}, uniq = [];
    rows.forEach(function (r) { if (!seen[r.id]) { seen[r.id] = 1; uniq.push(r); } });
    uniq.sort(function (a, b) { return (b[dateKey] || "") < (a[dateKey] || "") ? -1 : 1; });

    var dateLabel = dateKey === "awarded_at" ? "Awarded"
      : dateKey === "bid_deadline_at" ? "Bid deadline" : "Submitted";
    var body = uniq.map(function (r) {
      var cos = r.company_ids.map(function (c) { return NAMES.company[c] || "—"; });
      if (r.awarded_by_id && cos.indexOf(NAMES.company[r.awarded_by_id]) === -1) {
        cos.unshift(NAMES.company[r.awarded_by_id] || "—");
      }
      var coText = cos.join(", ") || "—";
      return '<tr><td><div class="pname">' + esc(r.name) + "</div>" +
        (r.city ? '<div class="ploc">' + esc(r.city) +
          (r.region ? ", " + esc(r.region) : "") + "</div>" : "") +
        '</td><td class="nowrap">' +
        esc(TW.fmtBizDate ? (TW.fmtBizDate(r[dateKey]) || "—") : (r[dateKey] || "—")) +
        '</td><td><span class="cos" title="' + esc(coText) + '">' + esc(coText) + "</span>" +
        "</td><td>" + estChips(r.estimator_ids) +
        '</td><td class="nowrap">' + stagePill(r.stage_id) +
        '</td><td class="r">' + C.fmtMoney(r.submitted_amount) +
        '</td><td class="r">' + C.fmtMoney(r.won_amount) + "</td></tr>";
    }).join("");

    var totSub = X.sum(uniq, "submitted_amount"), totWon = X.sum(uniq, "won_amount");
    $("drawer").innerHTML =
      '<div class="dhead"><div><h2>' + esc(title) + "</h2>" +
      '<div class="dsub"><span class="dcount">' + C.fmtInt(uniq.length) + " project" +
      (uniq.length === 1 ? "" : "s") + "</span>" +
      esc(winText("").trim().replace(/^\.?\s*/, "")) + "</div></div>" +
      '<button class="dclose" aria-label="Close">&times;</button></div>' +
      '<div class="dbody">' + (uniq.length
        ? '<div class="tablewrap"><table><thead><tr><th>Project</th><th>' + dateLabel +
          "</th><th>Company</th><th>Estimator</th><th>Stage</th>" +
          '<th class="r">Submitted</th><th class="r">Won</th></tr></thead><tbody>' + body +
          '</tbody><tfoot><tr><td colspan="5">Total</td><td class="r">' + C.fmtMoney(totSub) +
          '</td><td class="r">' + C.fmtMoney(totWon) + "</td></tr></tfoot></table></div>"
        : '<p class="chart-empty">No projects match these filters.</p>') + "</div>";
    $("drawer").classList.add("open");
    $("scrim").classList.add("open");
  }

  function closeDrawer() {
    $("drawer").classList.remove("open");
    $("scrim").classList.remove("open");
  }

  // ── data ────────────────────────────────────────────────────────────
  function adopt(payload) {
    DATA = payload;
    ROWS = X.decorate(payload.projects || []);
    STAGES = payload.stages || [];
    NAMES = { estimator: {}, company: {}, stage: {} };
    (payload.estimators || []).forEach(function (e) { NAMES.estimator[e.id] = e.name; });
    (payload.companies || []).forEach(function (c) { NAMES.company[c.id] = c.name; });
    (payload.stages || []).forEach(function (s) { NAMES.stage[s.id] = s.name; });
    // trades are their own label
    NAMES.trade = {};

    var bits = [];
    if (payload.truncated) {
      bits.push("showing the most recent " + C.fmtInt(payload.shown) + " of " +
                C.fmtInt(payload.total) + " bids");
    }
    if (payload.generated_at) {
      var d = new Date(payload.generated_at);
      if (!isNaN(d.getTime())) {
        bits.push("data as of " + d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }));
      }
    }
    // Which window these numbers were built from — read off the payload, so a reader served the
    // stale snapshot during a rebuild sees the window that dataset actually used.
    var pwin = (payload.pull_window || {});
    if (pwin.from || pwin.to) {
      bits.push("bids " + (pwin.from || "the beginning") + " → " + (pwin.to || "today"));
    }
    $("sub").textContent = "Your BasisBoard bids — won and submitted, sliced any way you like." +
      (bits.length ? "  (" + bits.join(" · ") + ")" : "");
  }

  function showEmpty(html) { $("cards").innerHTML = '<div class="empty">' + html + "</div>"; }

  var POLL_MS = 4000, POLL_MAX = 75;      // ~5 minutes of patience
  var polls = 0;

  function showBuilding(lastError) {
    $("tabs").innerHTML = "";
    $("filterbar").innerHTML = "";
    $("active-filters").innerHTML = "";
    $("alert").innerHTML = lastError
      ? '<div class="alert">' + esc(lastError) + " — trying again.</div>" : "";
    showEmpty("<h2>Reading your bid history…</h2><p>First load pulls every bid from " +
      "BasisBoard — a few thousand of them, at a pace their API is happy with. " +
      "Usually a few seconds. After this it's instant.</p>" +
      '<p class="fnote">This page will fill itself in — no need to refresh.</p>');
  }

  // No sessionStorage copy of the payload: the full history is ~2MB of JSON, and
  // mirroring it per tab risks the quota to save a request the server already
  // answers from its own cache. Only the filter state is worth persisting.
  function load(quiet) {
    tokenSoon().then(function () {
      return api("/api/analytics");
    }).then(function (r) {
      return r.json();
    }).then(function (j) {
      // The server builds off the request thread; poll until it has something.
      if (j && j.ok && j.building) {
        if (!DATA) showBuilding(j.last_error);
        if (++polls <= POLL_MAX) setTimeout(function () { load(true); }, POLL_MS);
        else showEmpty("<h2>Still building</h2><p>" +
          (j.last_error ? "BasisBoard keeps refusing the read. " : "This is taking longer " +
           "than expected. ") + "Reload the page to pick it back up.</p>");
        return;
      }
      if (!j || !j.ok) {
        if (j && j.configured === false) {
          $("tabs").innerHTML = "";
          $("filterbar").innerHTML = "";
          showEmpty("<h2>BasisBoard isn't connected</h2><p>Analytics reads the bids " +
            "already in BasisBoard. Once <code>BASISBOARD_API_KEY</code> is set on the " +
            "server, this page fills itself in.</p>");
          return;
        }
        $("alert").innerHTML = '<div class="alert">Couldn\'t refresh from BasisBoard' +
          (DATA ? " — showing the last numbers this browser loaded." : ".") + "</div>";
        // The server starts a fresh attempt when a read finds nothing cached;
        // keep watching rather than making someone reload to find out.
        if (j && j.retrying && ++polls <= POLL_MAX) {
          if (!DATA) showBuilding();
          setTimeout(function () { load(true); }, POLL_MS);
          return;
        }
        if (!DATA) showEmpty("<h2>No data</h2><p>BasisBoard didn't answer. " +
          "Reload to try again.</p>");
        return;
      }
      $("alert").innerHTML = "";
      polls = 0;
      adopt(j);
      render();
    }).catch(function () {
      $("alert").innerHTML = '<div class="alert">Couldn\'t reach the server.</div>';
      if (!DATA) showEmpty("<h2>No data</h2><p>Couldn't reach the server.</p>");
    });
  }

  // ── events (all delegated) ──────────────────────────────────────────
  function toggle(list, id) {
    var i = list.indexOf(id);
    if (i === -1) list.push(id); else list.splice(i, 1);
    return list;
  }

  document.addEventListener("click", function (ev) {
    var el = ev.target;

    var tabBtn = el.closest("[data-tab]");
    if (tabBtn) { STATE.tab = tabBtn.getAttribute("data-tab"); persist(); render(); return; }

    var popBtn = el.closest("[data-pop]");
    if (popBtn) {
      ev.stopPropagation();
      var dim = popBtn.getAttribute("data-pop");
      var already = OPEN_POP && OPEN_POP.getAttribute("data-dim") === dim;
      closePop();
      if (!already) openPop(dim, popBtn.parentNode);
      return;
    }

    if (OPEN_POP && OPEN_POP.contains(el)) {
      var dimKey = OPEN_POP.getAttribute("data-dim");
      if (el.hasAttribute("data-all")) {
        STATE[dimKey] = options(dimKey).map(function (o) { return o.id; });
        persist(); render(); closePop(); return;
      }
      if (el.hasAttribute("data-none")) {
        STATE[dimKey] = []; persist(); render(); closePop(); return;
      }
      return;                                   // checkbox handled on "change"
    }
    closePop();

    var one = el.closest("[data-clear-one]");
    if (one) {
      var k = one.getAttribute("data-clear-one");
      STATE[k] = (STATE[k] || []).filter(function (v) { return v !== one.getAttribute("data-id"); });
      persist(); render(); return;
    }
    if (el.closest("[data-clear-all]")) {
      DIMENSIONS.forEach(function (d) { STATE[d.key] = []; });
      persist(); render(); return;
    }

    var ct = el.closest("[data-chart]");
    if (ct && !ct.disabled) {
      STATE.charts[STATE.tab + ":" + ct.getAttribute("data-card")] = ct.getAttribute("data-chart");
      persist(); render(); return;
    }

    var brk = el.closest("[data-breakdown]");
    if (brk) {
      var card = CARDS[brk.getAttribute("data-breakdown")];
      if (card) openBreakdown(card.title, card.rows || [], card.dateKey);
      return;
    }

    // Clicking a bar, slice or table row drills into just that bucket.
    var mark = el.closest(".ch-mark");
    if (mark) {
      var host = mark.closest("[data-card]");
      var c = host && CARDS[host.getAttribute("data-card")];
      if (c) {
        var idx = Number(mark.getAttribute("data-idx"));
        var bucket = pickBucket(c, idx, mark.getAttribute("data-key"));
        if (bucket) openBreakdown(c.title + " · " + bucket.label, bucket.rows, c.dateKey);
      }
      return;
    }

    if (el.closest(".dclose") || el.id === "scrim") closeDrawer();
  });

  /** The rows behind one mark. Charts and their list view are the same data in
   *  a different shape, so both resolve through here. */
  function pickBucket(card, idx, key) {
    if (card.items) {
      var it = card.items[idx];
      return it ? { label: it.label, rows: it.rows || [] } : null;
    }
    if (card.groups) {
      var g = key
        ? card.groups.filter(function (x) { return String(x.key) === key; })[0]
        : card.groups[idx];
      if (!g) return null;
      return { label: g.label, rows: g.rows || g.rowsSub || [] };
    }
    if (card.data) {
      var b = card.data()[idx];
      return b ? { label: b.label, rows: b.rows || [] } : null;
    }
    return null;
  }

  document.addEventListener("click", function (ev) {
    if (ev.target && ev.target.id === "pw-save") savePullWindow();
  });

  document.addEventListener("change", function (ev) {
    var el = ev.target;
    // The pull-window inputs are a SETTING, not a filter: typing in them changes nothing until
    // Save. Cross-bound them the way the filter inputs are, and stop here — falling through would
    // re-render the whole page and discard what is half-typed.
    if (el.id === "pw-from" || el.id === "pw-to") {
      var pf = $("pw-from"), pt = $("pw-to");
      if (pf && pt) {
        if (pf.value && pt.value && pf.value > pt.value) {
          if (el.id === "pw-from") pt.value = pf.value; else pf.value = pt.value;
        }
        pt.min = pf.value || "";
        pf.max = pt.value || "";
      }
      return;
    }
    if (el.id === "f-preset") {
      STATE.preset = el.value;
      persist(); render(); return;
    }
    if (el.id === "f-from" || el.id === "f-to") {
      var from = ($("f-from") || {}).value || "";
      var to = ($("f-to") || {}).value || "";
      // Typing a backwards range should correct itself rather than silently
      // return nothing.
      if (from && to && from > to) { if (el.id === "f-from") to = from; else from = to; }
      STATE.from = from; STATE.to = to;
      persist(); render();
      var again = $(el.id);
      if (again) again.focus();
      return;
    }
    if (OPEN_POP && OPEN_POP.contains(el) && el.type === "checkbox") {
      var dimKey = OPEN_POP.getAttribute("data-dim");
      STATE[dimKey] = toggle((STATE[dimKey] || []).slice(), el.value);
      persist();
      // Re-render the cards but keep the popover open — picking three trades
      // shouldn't mean opening the menu three times.
      var scrollTop = OPEN_POP.querySelector(".plist").scrollTop;
      var search = OPEN_POP.querySelector(".psearch").value;
      render();
      var anchor = document.querySelector('.msel[data-dim="' + dimKey + '"]');
      if (anchor) {
        openPop(dimKey, anchor);
        OPEN_POP.querySelector(".plist").scrollTop = scrollTop;
        var s = OPEN_POP.querySelector(".psearch");
        s.value = search;
        filterPop(search);
      }
    }
  });

  function filterPop(q) {
    if (!OPEN_POP) return;
    var needle = (q || "").trim().toLowerCase();
    Array.prototype.forEach.call(OPEN_POP.querySelectorAll(".plist label"), function (l) {
      l.style.display = !needle || l.textContent.toLowerCase().indexOf(needle) !== -1 ? "" : "none";
    });
  }

  document.addEventListener("input", function (ev) {
    if (OPEN_POP && ev.target.classList.contains("psearch")) filterPop(ev.target.value);
  });

  document.addEventListener("keydown", function (ev) {
    if (ev.key !== "Escape") return;
    if (OPEN_POP) { closePop(); return; }
    closeDrawer();
  });

  loadState();
  renderTabs();
  load();
})();
