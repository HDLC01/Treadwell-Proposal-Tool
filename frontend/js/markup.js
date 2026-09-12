// Markup page — the markup chain's rates, per sheet LAYOUT, as the numbers they actually are.
// Externalized (CSP: no inline scripts). Do not add inline scripts.
//
// WHAT THIS PAGE IS. backend/markup.py's module docstring is the authority on the domain; read it
// first. In short: the Polish beta's price walks one compounding chain over a subtotal —
// gp → hard_bid → contingency → super_pto → soft_costs → remodel_tax → bond — each line's base
// being the running sum ABOVE it. Those rates are hardcoded constants in polish-bid-core.js. The
// markup_rules table is where an admin overrides them, and this is that table's screen.
//
// A LINE WHOSE ANSWER IS ONE NUMBER GETS ONE NUMBER BOX. This page used to ask an estimator to
// read three paragraphs and then hand-author
// `MARKUP(BAND(subtotal, 6500,52%, 15000,45%, 22500,35%, 32500,32%, 30%))` in a text field to
// answer what is, for six of the eight lines, a one-number question: what is our rate? So there
// are now three controls instead of one, and which one a row gets is READ OFF THE STORED FORMULA
// rather than assumed:
//
//   flat     `2.7%`, `16%`, `MARKUP(30%)`, `500`  → one number box and a % or $ affordance
//   bands    `MARKUP(BAND(subtotal, 6500,52%, …))` → a short editable ladder, one row per band
//   ladder   `IF(hard_bid_on, IF(subtotal>=60000, -4%, IF(local, …)))` → the same, stepping up,
//            with Kyle's local-jobs-only rule as a checkbox on the step it belongs to
//
// and anything else — Gyp's soft-costs expression, a hand-written formula — opens in ADVANCED, the
// original expression box, which is still reachable on every row and still round-trips. A row the
// simple control cannot represent opens in Advanced BY ITSELF rather than misrepresenting what is
// stored. That is the whole contract; simpleFrom/simpleTo below are where it lives.
//
// NO eval, NO new Function. Every formula is parsed and evaluated by markup-core.js, a hand-rolled
// tokenizer + recursive-descent parser, because prod's CSP is `script-src 'self'
// https://cdn.jsdelivr.net` with no unsafe-eval. A dynamic-code shortcut here would work locally
// and die silently in production. The simple controls are built on that same parser: they read the
// AST, never a second looser regex of the same grammar.
//
// THREE ROW STATES, and keeping them apart is the whole job:
//
//   filed / built-in   a rate applies and prices the line. An empty ONE-NUMBER box means "no
//                      override filed yet, the chain uses its built-in constant" — the
//                      placeholder shows which. A ladder cannot be empty (ten blank boxes would
//                      mean filling all ten to change one), so it is seeded from the built-in and
//                      says so — and an untouched seeded ladder saves nothing.
//   ABSENT             `applies === false`, `formula === null`. Gyp has NO hard-bid rate: the
//                      workbook cell is EMPTY, not 0. Rendered as a greyed row with a caption
//                      naming the tab and NO control at all — an empty editable box invites
//                      somebody to fill it in, and "0%" reads as a discount that was declined.
//   context            `contingency` and `remodel_tax`. In CHAIN, excluded from LINE_KEYS,
//                      refused by name if posted. They are context the chain includes, not
//                      markup rules: tinted, chipped "Set elsewhere", no control, and
//                      markup.py's own sentences say why.
//
// A BROKEN LINE NEVER READS AS $0.00. An unparseable formula, or one that evaluates to Kyle's own
// "error" sentinel, makes its own line and every line below it read "Unpriceable" — which is
// markup-core.js's stated safety property carried up into the screen.
(function () {
  "use strict";

  /** The engine. markup-core.js is loaded ahead of this file; if it is missing the page
   *  must refuse to price rather than pretend, so the stand-in reports every formula as
   *  unreadable instead of quietly returning a number — and `parse` throws, which makes every
   *  row fall back to the expression box rather than to a simple control built on a guess. */
  var M = window.TWMarkup || {
    validate: function () { return { ok: false, error: "the formula engine did not load" }; },
    parse: function () { throw new Error("the formula engine did not load"); },
    run: function () { throw new Error("the formula engine did not load"); }
  };
  var $ = function (id) { return document.getElementById(id); };

  // ── vocabularies ───────────────────────────────────────────────────────────

  /** The compounding order, and the ONE backend vocabulary this page keeps a copy of.
   *
   *  /api/markup/rules ships `layouts` and `line_keys` precisely so the editor cannot drift from
   *  them, and both are read off the response below. It does NOT ship CHAIN — and CHAIN is what
   *  puts `contingency` and `remodel_tax` in their places between the editable lines, which is
   *  the only way a reader can see what a line's base actually is. So it is written here and
   *  PINNED against markup.CHAIN by backend/tests/test_markup_page.py: a change on either side
   *  fails there rather than on somebody's bid. Anything the API offers that is not in this list
   *  is appended rather than dropped — a line silently missing from the chain is worse than one
   *  in the wrong place. */
  var CHAIN = ["gp", "hard_bid", "contingency", "super_pto", "soft_costs", "remodel_tax", "bond"];

  /** markup.py's `_NOT_EDITABLE`, VERBATIM — not paraphrased, and not re-worded to fit the
   *  column. These two lines are refused BY NAME by the backend and the user is entitled to the
   *  same reason the API would give them. test_markup_page.py compares these strings against the
   *  Python dict, so a reword on either side is a failing test rather than two screens
   *  explaining the same rule differently. */
  var NOT_EDITABLE = {
    contingency: "Contingency isn't a markup rule — it's typed per job by the estimator, " +
      "not a tab-wide formula. There's nothing to file here.",
    remodel_tax: "Remodel tax isn't a markup rule here — it's already set by a typed percent, " +
      "then the county table, then the 6.5% floor. File a county rate instead of a formula."
  };

  var LABELS = {
    gp: "GP",
    hard_bid: "Hard bid discount",
    contingency: "Contingency",
    super_pto: "Superintendent & PTO",
    soft_costs: "Soft costs",
    remodel_tax: "Remodel tax",
    bond: "Bond"
  };

  /** The one-line caption under a line's name. Free to read — it is the half of the old WHAT IT
   *  DOES column that was worth having in the grid. */
  var SUBS = {
    gp: "steps down as the job gets bigger",
    hard_bid: "money given back to win a competitive bid",
    contingency: "typed per job, on the bid",
    super_pto: "a flat rate on everything above",
    soft_costs: "overhead the field never sees",
    remodel_tax: "set by the county table",
    bond: "the workbook ships this at zero"
  };

  /** The rest of it, behind the row's own disclosure. Good writing, and it does not belong
   *  repeated in every row of a table of eight numbers. */
  var EXPLAIN = {
    gp: "Divide-up margin, not a mark-on: the base is divided up by (1 - rate) and the base " +
      "taken back off. That is why the preview shows dollars and no percentage — $36,429 on " +
      "$85,000 back-derives to 42.858%, a number nobody typed.",
    hard_bid: "Only applied when the bid is marked hard bid, so the rate is negative. A job " +
      "that is neither big enough nor local gets nothing taken off.",
    super_pto: "Supervision and paid time off, charged as one rate on the running total above " +
      "this line.",
    soft_costs: "Overhead the field never sees. On the Gyp tab this line is a whole expression " +
      "rather than a rate, so Gyp opens it in Advanced.",
    // BOTH BOND FACTS, because they answer different questions and only one of them is
    // reachSentence's. reachSentence says bond reaches no bid; it does not say WHY, and the why is
    // the part that stops somebody finishing the feature: Kyle's bond row multiplies a range that
    // contains its own tax subtotal, so a 1% rate charges $110 where $108 is honest. The other
    // clause is the redesign's, and it is about the CONTROL — a zero typed in that box is a real
    // answer and not the same as the switch being off.
    bond: "Bond premium on the running total. The workbook ships this line at zero, and zero " +
      "is a real answer here — it is not the same as switching the line off. Kyle's own bond " +
      "row counts the two tax lines twice, so a rate filed here would over-charge until he " +
      "corrects the sheet."
  };

  /** A chip beside the name, for the lines an admin does not set. Short, and it says the one
   *  thing a reader needs before they look for a box that is not there. */
  var CHIPS = { contingency: "Set elsewhere", remodel_tax: "Set elsewhere" };
  var HELP_LABEL = { contingency: "Why it isn't here", remodel_tax: "Why it isn't here" };

  /** The prose name of a tab, for the ABSENT caption. A layout with no entry gets "this tab",
   *  so a sixth layout added on the backend still produces a readable sentence. */
  var LAYOUT_NOUN = {
    polish: "polished concrete",
    seal: "sealed concrete",
    epoxy: "epoxy",
    leveling: "self-leveling",
    gyp: "gypsum underlayment"
  };

  // ── the built-in constants, per tab ────────────────────────────────────────
  // What the chain uses TODAY for a line with no row filed. Transcribed from
  // frontend/js/polish-bid-core.js (RATES, GP_BANDS, hardBidPct) and backend/markup.py's audit of
  // estimate_sheet_5.7.xlsx, and from nowhere else.
  //
  // WHERE A NUMBER IS NOT ON RECORD, THERE IS NO ENTRY. markup.py's audit says Seal has a SIXTH
  // GP tier topping out at 0.28 and Gyp has SEVEN tiers on different edges, but it does not give
  // those edges — and inventing a band edge to fill a column would be inventing pricing. Those
  // two cells render an empty rate box instead, and the tab's total says Unpriceable until a rate
  // is filed, which is the same refusal Kyle's own `"error"` sentinel makes.

  /** B67 as a BAND: `=IF(D64<6500,0.52,IF(D64<15000,0.45,IF(D64<22500,0.35,IF(D64<32500,0.32,
   *  0.3))))`, wrapped in MARKUP because GP is a divide-up (D67), not a rate on the base. */
  var GP_5_BANDS = "MARKUP(BAND(subtotal, 6500,52%, 15000,45%, 22500,35%, 32500,32%, 30%))";

  /** B68 `=IF(B5="yes",IF(D64>=60000,-0.04,IF(B4="yes",IF(D64>=13000,-0.025,0))))`, with the
   *  innermost else written out. Excel returns a bare FALSE there and sums it as 0; markup-core
   *  refuses to do arithmetic on a FALSE on purpose, so the branch is explicit. */
  var HARD_BID = "IF(hard_bid_on, IF(subtotal>=60000, -4%, " +
    "IF(local, IF(subtotal>=13000, -2.5%, 0), 0)), 0)";

  /** Gyp's soft-costs cell, verbatim from markup.py's docstring — string sentinel and all. */
  var GYP_SOFT_COSTS = 'IF(OR(B5="Yes",B5="No"), IF(B5="Yes",.09,.1) - ' +
    'IF(E69>334900,.05,IF(E69>234450,.035,0)), "error")';

  var F = function (formula) { return { formula: formula }; };
  /** "This line does not exist on this tab" as a DEFAULT, before anybody files a row. Gyp's
   *  hard-bid cell is empty in the workbook, so an unconfigured Gyp tab must show the absent
   *  state, not an empty box waiting to be filled in. */
  var NOT_ON_TAB = { applies: false };

  var BUILTIN = {
    polish: { gp: F(GP_5_BANDS), hard_bid: F(HARD_BID), super_pto: F("2.7%"),
              soft_costs: F("16%"), bond: F("0%") },
    // Same rates as Polish; its GP tiers are the sixth-tier set and are not on record here.
    seal: { hard_bid: F(HARD_BID), super_pto: F("2.7%"), soft_costs: F("16%"), bond: F("0%") },
    epoxy: { gp: F(GP_5_BANDS), hard_bid: F(HARD_BID), super_pto: F("3%"),
             soft_costs: F("13%"), bond: F("0%") },
    leveling: { gp: F(GP_5_BANDS), hard_bid: F(HARD_BID), super_pto: F("3%"),
                soft_costs: F("13%"), bond: F("0%") },
    // A different species: 7 GP tiers on edges not on record, NO hard-bid rate at all, and soft
    // costs is an expression rather than a rate.
    gyp: { hard_bid: NOT_ON_TAB, super_pto: F("4.1%"), soft_costs: F(GYP_SOFT_COSTS),
           bond: F("0%") }
  };

  // ── which rows actually reach the estimate workbook ────────────────────────
  //
  // WHY THIS IS ON THE SCREEN AND NOT ONLY IN A COMMENT. Until 2026-09-08 this page
  // carried a paragraph saying filed rates priced nothing at all, and it was there
  // because "a number that quietly does nothing is how people come to distrust the whole
  // form". Wiring two of the seven lines up does not retire that problem, it RELOCATES
  // it: an admin can now file a GP ladder, watch it save with a green tick, and move no
  // price — with a page that no longer warns them. So every row says for itself.
  //
  // THE SAME SOURCE OF TRUTH AS THE WRITER, and the drift is caught by execution rather
  // than by hoping: this is the (layout -> line_keys) projection of MARKUP_RATE_TARGETS in
  // frontend/js/estimate-review.js, and backend/tests/test_markup_rate_reaches_the_bid.py
  // lifts BOTH out of the real sources and asserts them equal. The estimate page cannot
  // simply import this — markup.js is not loaded there, and loading it would run this
  // whole IIFE against a DOM it does not have.
  //
  // gp and hard_bid are on NO layout: gp's built-in returns dollars from a tier ladder and
  // hard_bid keys on a frozen "No" on four of seven layouts. soft_costs is missing from gyp
  // alone, where Kyle's cell is an expression with a local/away branch, a job-size taper and
  // his own "error" sentinel. estimate-review.js explains each exclusion in full.
  // MUST MIRROR estimate-review.js's MARKUP_RATE_TARGETS, and a test asserts the two
  // agree key for key. If this list claims a line prices the bid when the writer has
  // no address for it, the page tells an admin their rate took effect and it did not.
  //
  // `bond` is absent from BOTH on purpose: Kyle's bond row multiplies a range that
  // contains its own tax subtotal, so sales and remodel tax are counted twice in the
  // bond base on all eleven sheets. Bond is 0 in the template, so filing a rate is
  // what would first expose it — as an over-charge. His formula, his fix; see the
  // note over MARKUP_RATE_TARGETS.
  var PRICES_THE_BID = {
    polish:   ["super_pto", "soft_costs"],
    seal:     ["super_pto", "soft_costs"],
    epoxy:    ["super_pto", "soft_costs"],
    leveling: ["super_pto", "soft_costs"],
    gyp:      ["super_pto"]
  };

  /** Does this formula reach the workbook, and at what percent?
   *
   *  The TWIN of rateTextFrom in estimate-review.js, and deliberately answering in PERCENT
   *  rather than in Kyle's decimal: the admin typed a percent, so echoing "2.7%" needs no
   *  arithmetic at all — the digits go back out as they came in. The writer does the decimal
   *  shift on its own side, through the same captured group.
   *
   *  Same regex, same >= 100% ceiling, same refusal of a bare decimal with no % sign — and
   *  the agreement is asserted by executing both against one adversarial input table, not by
   *  reading them side by side. Returns null when the workbook would keep its own rate. */
  var _RATE_LITERAL_RE = /^\s*(\d*\.?\d*)\s*%\s*$/;
  function ratePctFrom(formula) {
    var m = _RATE_LITERAL_RE.exec(String(formula == null ? "" : formula));
    if (!m || !m[1] || m[1] === ".") return null;
    var n = Number(m[1]);
    if (!isFinite(n) || n >= 100) return null;
    return m[1] + "%";
  }

  /** One plain sentence about whether THIS row moves a bid. Appended to the row's "What it
   *  does" cell, which is where somebody already is when they decide this page is worth
   *  trusting. Editable rows only: `contingency` and `remodel_tax` carry markup.py's own
   *  wording verbatim and test_markup_page.py compares them character for character.
   *
   *  Five states, and they are genuinely five different things to do next. The one that
   *  reads worst is deliberate: a line switched OFF here is still charged by the workbook,
   *  because "not used on this tab" is not a zero and this tool will not silently turn it
   *  into one. */
  function reachSentence(r) {
    if (!r.editable) return "";
    var keys = PRICES_THE_BID[LAYOUT] || [];
    if (keys.indexOf(r.line_key) < 0) {
      return " The estimate workbook does not read this line yet, so a rate filed here " +
        "changes no bid.";
    }
    if (!r.applies) {
      return " Switched off here — but the workbook still charges its own rate for this " +
        "line on this tab.";
    }
    if (!r.formula) return " The workbook keeps its own rate until a percent is filed here.";
    var pct = ratePctFrom(r.formula);
    if (pct === null) {
      return " Only a plain percent like 2.7% reaches the workbook, so this one does not — " +
        "the bid keeps the sheet's own rate.";
    }
    return " Prices the bid: every " + nounFor(LAYOUT) + " tab is charged " + pct + ".";
  }

  // ── the sample job the preview prices ──────────────────────────────────────
  // A rate's effect has to be visible the moment it is typed, and nothing real may be at
  // stake in that. These figures price NOTHING: they are the mockup's own sample job, and the
  // footnote on the page says so.
  //
  // THE SUB-TOTAL IS TYPEABLE, and only because of that "prices NOTHING". A band ladder reads
  // very differently at $6,000 than at $85,000 -- which step you land on IS the thing being
  // checked -- and picking one fixed job size hid that. Deliberately NOT persisted: it is a
  // question you ask, not a setting you keep, and a remembered figure would have somebody
  // reading last week's what-if as today's default.
  var SAMPLE_SUBTOTAL_DEFAULT = 85000;
  var SAMPLE_SUBTOTAL = SAMPLE_SUBTOTAL_DEFAULT;
  // Exactly what is in the box mid-edit, or null when nobody is typing in it. The box echoes THIS
  // rather than a re-formatted figure, because `fmtEdge` inserts separators: re-rendering "6500"
  // as "6,500" on the fourth keystroke makes the string longer than the caret offset render()
  // saved, and the caret jumps a character every time the thousands mark appears. Cleared on the
  // way out, so the box settles back to a formatted figure once it is no longer being typed in.
  var SUBTOTAL_RAW = null;
  var SAMPLE_CONTINGENCY = 2500;
  var SAMPLE_COUNTY_RATE = 0.07975;      // Johnson County, KS — reference_tax.py's own figure

  // ── state ──────────────────────────────────────────────────────────────────

  /** FAIL CLOSED. A page that paints editable and then locks is worse than one that resolves
   *  late, so this starts false and is settled before the first render. It is not a security
   *  boundary either way — `_require_admin` in main.py is — it only keeps a non-admin from being
   *  shown a control that would 403 on click. */
  var ADMIN = false;
  var LAYOUTS = [];
  var LINE_KEYS = [];
  var RULES = [];                  // every live rule, all layouts
  var LAYOUT = "";                 // the tab on screen
  /** Typed-but-unsaved edits, keyed "<layout>/<line_key>". A rate the admin is still working
   *  on outlives a re-render; nothing here is sent until it is valid. */
  var LOCAL = {};
  var ERRORS = {};                 // same key → the message under the control
  var EPARTS = {};                 // same key → which control the message is about
  /** Which rows the admin has opened in Advanced, keyed the same way. A row whose stored formula
   *  no simple control can represent is forced open regardless — see rowState. */
  var ADV = {};
  /** A ladder mid-structural-edit: a band just added with nothing in it yet, or one just removed.
   *  Only bands and ladders ever have one — a single number box has no structure to draft. */
  var SDRAFT = {};
  /** Which per-row disclosures are open, by line key, so a re-render does not snap them shut.
   *  Not per layout: somebody who opened "What this does" on GP wants it open on the next tab. */
  var HELP = {};
  var LOADED = false;
  var LOADFAIL = "";
  var rendering = false;           // re-entrancy guard: render() blurs, and blur triggers a save

  // ── plumbing ───────────────────────────────────────────────────────────────

  /** Every request waits for the bearer token in ONE place; doing it per-call is how the Bid
   *  Calendar shipped a 401 that hid the estimator's own entries. */
  var api = async function (path, opts) {
    try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch (e) {}
    return fetch(TW.resolveApiBase() + path,
      Object.assign({}, opts || {}, { headers: TW.authHeaders((opts || {}).headers) }));
  };

  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  };

  function say(msg) { $("alert").textContent = msg || ""; }

  /** One inline SVG glyph, Lucide-shaped: 24x24 box, no fill, currentColor stroke, width 2,
   *  round caps. NEVER an emoji — an emoji is drawn by whatever font the machine has, cannot take
   *  the row's colour, and ignores every size token on the page. */
  function icon(name, size) {
    var d = name === "info"
        ? '<circle cx="12" cy="12" r="9.5"></circle><path d="M12 8v.01M11 11h1.5v5.5H11"></path>'
      : name === "slash"
        ? '<circle cx="12" cy="12" r="9.5"></circle><path d="M5.5 5.5l13 13"></path>'
      : name === "arrow" ? '<path d="M5 12h13M13 7l5 5-5 5"></path>'
      : name === "plus" ? '<path d="M12 5v14M5 12h14"></path>'
      : name === "x" ? '<path d="M6 6l12 12M18 6L6 18"></path>'
      : name === "chev" ? '<path d="M9 5l7 7-7 7"></path>'
      : "";
    var px = size || 12;
    return '<svg viewBox="0 0 24 24" width="' + px + '" height="' + px + '" fill="none" ' +
      'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ' +
      'aria-hidden="true" focusable="false">' + d + "</svg>";
  }

  function money(n) {
    var v = Number(n) || 0;
    return (v < 0 ? "-$" : "$") +
      Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  /** A rate as a percentage, trimmed. 0.30 → "30%", -0.04 → "-4%", 0.07975 → "7.975%". */
  function pct(rate) {
    var v = Number(rate) * 100;
    if (!isFinite(v)) return "";
    return String(Math.round(v * 1000) / 1000) + "%";
  }

  function key(lineKey) { return LAYOUT + "/" + lineKey; }
  function nounFor(layout) { return LAYOUT_NOUN[layout] || "this tab"; }
  function labelFor(layout) {
    return String(layout || "").charAt(0).toUpperCase() + String(layout || "").slice(1);
  }

  // ── numbers, in and out of a box ───────────────────────────────────────────

  /** Float dust, at 12 significant figures — the same guard markup-core's excelRoundUp uses, for
   *  the same reason: `0.027 * 100` is 2.7000000000000006 and nobody typed that. */
  function round12(n) { return parseFloat(Number(n).toPrecision(12)); }

  function trimNum(n) {
    if (n === null || n === undefined || n === "" || !isFinite(Number(n))) return "";
    return String(round12(n));
  }

  /** A job size, with separators, because a threshold is money: 6500 → "6,500". Read back by
   *  parseNum, which strips them again. */
  function fmtEdge(n) {
    if (n === null || n === undefined || !isFinite(Number(n))) return "";
    return Number(n).toLocaleString("en-US", { maximumFractionDigits: 2 });
  }

  /** What somebody typed, as a number, or null. Lenient about the things a person types into a
   *  money or percent box — "$15,000", "2.7%", " 45 " — and refuses everything else rather than
   *  guessing, because the wrong guess here is a rate. */
  function parseNum(raw) {
    var t = String(raw == null ? "" : raw).replace(/[$,%\s]/g, "");
    if (t === "" || !/^[-+]?(\d+\.?\d*|\.\d+)$/.test(t)) return null;
    var n = Number(t);
    return isFinite(n) ? n : null;
  }

  // ── the simple model ───────────────────────────────────────────────────────
  // What a line's answer actually is, when it is one number or a short ladder — and NOTHING when
  // it is not. Two functions, and the contract between them is the safety property:
  //
  //     simpleTo(simpleFrom(text)) reproduces `text` for every shape simpleFrom accepts.
  //
  // Byte for byte, for all five built-ins. If it did not, tabbing through a row would rewrite a
  // stored formula into a "normalised" one nobody asked for. Where an exact reproduction is
  // impossible — `.09` and `0.09` are the same rate written two ways — nothing is saved anyway,
  // because an edit is compared against the render's OWN serialization (rowState's `baseline`),
  // not against the stored string.
  //
  // READ OFF THE AST, not off a regex. markup-core.js's parser is already the authority on what
  // these strings mean, and a second, looser reader of the same grammar is how the two come to
  // disagree about a formula that prices a job.

  function isCall(n, name) {
    return !!n && n.type === "Call" && String(n.name).toUpperCase() === name;
  }
  function isIdent(n, name) {
    return !!n && n.type === "Ident" &&
      String(n.name).replace(/\$/g, "").toLowerCase() === name;
  }
  /** A literal nothing: the terminator of a give-back ladder. `0` and `0%` both count — being
   *  generous about what is READ is safe; being generous about what is WRITTEN is not. */
  function isZero(n) {
    if (!n) return false;
    if (n.type === "Num") return n.value === 0;
    return n.type === "Percent" && n.operand && n.operand.type === "Num" &&
      n.operand.value === 0;
  }

  /** A rate node as the number a person types plus the way it was written. `52%` and `.52` are
   *  the same rate; which one comes back out has to match which one went in. */
  function nodeRate(n) {
    if (!n) return null;
    if (n.type === "Unary" && (n.op === "-" || n.op === "+")) {
      var inner = nodeRate(n.operand);
      if (!inner) return null;
      return { value: n.op === "-" ? -inner.value : inner.value, style: inner.style };
    }
    if (n.type === "Percent" && n.operand && n.operand.type === "Num") {
      return { value: n.operand.value, style: "pct" };
    }
    if (n.type === "Num") return { value: round12(n.value * 100), style: "bare" };
    return null;
  }

  function rateText(rate) {
    if (!rate || rate.value === null || rate.value === undefined) return "";
    if (rate.style === "bare") return trimNum(round12(rate.value / 100));
    return trimNum(rate.value) + "%";
  }

  /** One flat rate or dollar figure: `2.7%`, `16%`, `MARKUP(30%)`, `.52`, `500`. */
  function flatFrom(ast) {
    var markup = false, node = ast;
    if (isCall(node, "MARKUP") && node.args.length === 1) { markup = true; node = node.args[0]; }
    var r = nodeRate(node);
    if (!r) return null;
    // A BARE number of 1 or more is DOLLARS, not a rate — the same reading priceChain makes, and
    // it has to be the same reading or the box and the figure beside it describe different money.
    // A MARKUP() rate is never dollars: markup-core refuses a rate of 1 or more outright.
    if (!markup && r.style === "bare" && Math.abs(r.value) >= 100) {
      return { kind: "flat", markup: false, unit: "$", value: round12(r.value / 100),
               style: "dollars" };
    }
    return { kind: "flat", markup: markup, unit: "%", value: r.value, style: r.style };
  }

  function flatTo(m) {
    var s = m.style === "dollars" ? trimNum(m.value)
      : m.style === "bare" ? trimNum(round12(m.value / 100))
      : trimNum(m.value) + "%";
    return m.markup ? "MARKUP(" + s + ")" : s;
  }

  /** `MARKUP(BAND(subtotal, 6500,52%, 15000,45%, 22500,35%, 32500,32%, 30%))` — Kyle's GP column.
   *  The steps are CEILINGS ("up to $6,500"), first match wins, and the last one has no ceiling:
   *  it is what everything above the top band gets. */
  function bandsFrom(ast) {
    var markup = false, node = ast;
    if (isCall(node, "MARKUP") && node.args.length === 1) { markup = true; node = node.args[0]; }
    if (!isCall(node, "BAND")) return null;
    var args = node.args;
    if (args.length < 2 || (args.length % 2) !== 0) return null;
    if (!isIdent(args[0], "subtotal")) return null;
    var steps = [];
    for (var i = 1; i < args.length - 1; i += 2) {
      if (!args[i] || args[i].type !== "Num") return null;
      var rate = nodeRate(args[i + 1]);
      if (!rate) return null;
      steps.push({ edge: args[i].value, rate: rate, localOnly: false });
    }
    var dflt = nodeRate(args[args.length - 1]);
    if (!dflt) return null;
    steps.push({ edge: null, rate: dflt, localOnly: false });
    return { kind: "bands", markup: markup, steps: steps };
  }

  function bandsTo(m) {
    var parts = [];
    for (var i = 0; i < m.steps.length - 1; i++) {
      parts.push(trimNum(m.steps[i].edge) + "," + rateText(m.steps[i].rate));
    }
    parts.push(rateText(m.steps[m.steps.length - 1].rate));
    var inner = "BAND(subtotal, " + parts.join(", ") + ")";
    return m.markup ? "MARKUP(" + inner + ")" : inner;
  }

  /** `IF(hard_bid_on, IF(subtotal>=60000, -4%, IF(local, IF(subtotal>=13000, -2.5%, 0), 0)), 0)`
   *  — a give-back that steps UP with job size, gated on the bid being a hard bid, with Kyle's
   *  local-jobs-only rule on the smaller step. The steps are FLOORS ("from $60,000") and the
   *  terminator is always nothing-off, which is why it is not editable. */
  function ladderFrom(ast) {
    if (!isCall(ast, "IF") || ast.args.length !== 3) return null;
    if (!isIdent(ast.args[0], "hard_bid_on")) return null;
    if (!isZero(ast.args[2])) return null;
    var steps = [];
    if (!walkLadder(ast.args[1], false, steps)) return null;
    if (!steps.length) return null;
    return { kind: "ladder", markup: false, steps: steps };
  }

  function walkLadder(node, localOnly, steps) {
    if (isZero(node)) return true;                     // the terminator: nothing off
    if (!isCall(node, "IF") || node.args.length !== 3) return false;
    var cond = node.args[0];
    if (isIdent(cond, "local")) {
      // Everything inside the gate is local-jobs-only. ONE gate, not a nest of them, and its own
      // else has to be a zero or the shape means something this editor cannot show.
      if (localOnly) return false;
      return isZero(node.args[2]) && walkLadder(node.args[1], true, steps);
    }
    if (cond && cond.type === "Compare" && cond.op === ">=" && isIdent(cond.left, "subtotal") &&
        cond.right && cond.right.type === "Num") {
      var rate = nodeRate(node.args[1]);
      if (!rate) return false;
      steps.push({ edge: cond.right.value, rate: rate, localOnly: localOnly });
      return walkLadder(node.args[2], localOnly, steps);
    }
    return false;
  }

  function ladderTo(m) {
    var open = [], near = [];
    for (var i = 0; i < m.steps.length; i++) {
      (m.steps[i].localOnly ? near : open).push(m.steps[i]);
    }
    var tail = near.length ? "IF(local, " + ladderChain(near, "0") + ", 0)" : "0";
    return "IF(hard_bid_on, " + ladderChain(open, tail) + ", 0)";
  }

  function ladderChain(steps, tail) {
    var out = tail;
    for (var i = steps.length - 1; i >= 0; i--) {
      out = "IF(subtotal>=" + trimNum(steps[i].edge) + ", " + rateText(steps[i].rate) + ", " +
        out + ")";
    }
    return out;
  }

  function simpleFrom(text) {
    if (typeof text !== "string" || !text.trim()) return null;
    var ast;
    try { ast = M.parse(text); } catch (e) { return null; }
    return flatFrom(ast) || bandsFrom(ast) || ladderFrom(ast);
  }

  function simpleTo(m) {
    if (!m) return "";
    if (m.kind === "flat") return flatTo(m);
    if (m.kind === "bands") return bandsTo(m);
    if (m.kind === "ladder") return ladderTo(m);
    return "";
  }

  /** The control a line with NOTHING on record gets. Seal's GP tiers and Gyp's are not in this
   *  file (inventing a band edge would be inventing pricing), and the question those cells are
   *  asking is still "what is our rate?" — so they get the one-number box, and Advanced is one
   *  click away for a tab whose answer really is a ladder.
   *
   *  GP IS A DIVIDE-UP. A bare `30%` on that line would be a mark-on: the wrong arithmetic, on
   *  the one line whose arithmetic already misleads people. So a blank GP box writes MARKUP(). */
  function blankFlat(lineKey) {
    return { kind: "flat", markup: lineKey === "gp", unit: "%", value: null, style: "pct" };
  }

  function cloneModel(m) {
    var out = { kind: m.kind, markup: !!m.markup, unit: m.unit, value: m.value, style: m.style };
    if (m.steps) {
      out.steps = m.steps.map(function (s) {
        return { edge: s.edge, localOnly: !!s.localOnly,
                 rate: s.rate ? { value: s.rate.value, style: s.rate.style } : null };
      });
    }
    return out;
  }

  // ── the row model ──────────────────────────────────────────────────────────

  /** Every displayed line, in the order the chain compounds.
   *
   *  Built from CHAIN plus anything in the API's `line_keys` that CHAIN has not heard of, so a
   *  line added on the backend appears at the end instead of vanishing. */
  function displayOrder() {
    var out = CHAIN.slice();
    for (var i = 0; i < LINE_KEYS.length; i++) {
      if (out.indexOf(LINE_KEYS[i]) < 0) out.push(LINE_KEYS[i]);
    }
    return out;
  }

  function ruleFor(layout, lineKey) {
    for (var i = 0; i < RULES.length; i++) {
      if (RULES[i].layout === layout && RULES[i].line_key === lineKey) return RULES[i];
    }
    return null;
  }

  /** One row's whole truth: is it editable, does it apply, what prices it, which control it gets,
   *  and where the numbers in that control came from. `source` is what the note reads off —
   *  "filed" (a row in the table), "builtin" (the hardcoded constant), "unknown" (neither). */
  function rowState(lineKey) {
    var editable = LINE_KEYS.indexOf(lineKey) >= 0;
    var readOnlyWhy = NOT_EDITABLE[lineKey] || (editable ? "" : "Not editable on this page.");
    var st = {
      line_key: lineKey,
      label: LABELS[lineKey] || labelFor(lineKey),
      sub: SUBS[lineKey] || "",
      chip: CHIPS[lineKey] || "",
      helpLabel: HELP_LABEL[lineKey] || "What this does",
      explain: NOT_EDITABLE[lineKey] || EXPLAIN[lineKey] || "",
      editable: editable && !NOT_EDITABLE[lineKey],
      readOnlyWhy: readOnlyWhy,
      rule: null, id: null, notes: "",
      applies: true, formula: "", builtin: "", source: "unknown", dirty: false,
      filedText: "", simple: null, simpleFiled: false, canSimple: false, sdraft: false,
      advanced: false, baseline: ""
    };
    if (!st.editable) return st;

    var rule = ruleFor(LAYOUT, lineKey);
    var b = (BUILTIN[LAYOUT] || {})[lineKey];
    if (b && b.formula) st.builtin = b.formula;

    if (rule) {
      st.rule = rule;
      st.id = rule.id;
      st.notes = rule.notes || "";
      // READ FROM THE COLUMN, never re-derived from whether a formula is present — that
      // inference is exactly the conflation markup.py refuses to make.
      st.applies = rule.applies !== false;
      st.formula = rule.formula || "";
      st.source = "filed";
    } else if (b && b.applies === false) {
      st.applies = false;
      st.source = "builtin";
    } else if (st.builtin) {
      st.source = "builtin";
    }

    var pending = LOCAL[key(lineKey)];
    if (pending) {
      st.applies = pending.applies;
      st.formula = pending.formula;
      st.dirty = true;
    }
    st.effective = st.applies ? (st.formula || st.builtin) : "";

    // ── which control, and what is in it ────────────────────────────────────
    st.filedText = st.applies ? (st.formula || "") : "";
    var src = st.applies ? (st.filedText || st.builtin) : "";
    var srcModel = src ? simpleFrom(src) : null;
    st.simpleFiled = !!(st.filedText && srcModel);
    if (!srcModel && st.applies && !src) srcModel = blankFlat(lineKey);
    // AFTER the blank fallback, or Advanced is a trapdoor. A line with nothing on record has a
    // simple control available (an empty rate box), so the door back out of the expression box
    // has to be offered on it -- the same corner as the off row that lost its only exit when
    // touched. `false` here means one thing only: a formula is stored that no box can hold.
    st.canSimple = !!srcModel;

    // WHAT AN UNTOUCHED CONTROL RECOMPOSES TO, and the reason there are two answers.
    // A one-number box for a line with nothing filed is EMPTY with the built-in as its
    // placeholder — prefilling a value that is not stored is a lie about state. A ladder cannot
    // do that: ten blank boxes with placeholders would mean filling all ten in to change one, so
    // it is SEEDED from the built-in and its note says the numbers are not yet overridden. Either
    // way, tabbing through it without typing recomposes to exactly this string and saves nothing.
    st.baseline = !srcModel ? ""
      : (st.simpleFiled || srcModel.kind !== "flat") ? simpleTo(srcModel)
      : "";

    var draft = SDRAFT[key(lineKey)];
    st.sdraft = !!draft;
    st.simple = draft || srcModel;
    // A stored formula no simple control can represent opens in Advanced BY ITSELF, rather than
    // being misrepresented by a box that cannot hold it.
    st.advanced = ADV[key(lineKey)] === true || (st.applies && !st.simple);
    return st;
  }

  function rowStates() {
    return displayOrder().map(rowState);
  }

  // ── pricing the sample job ─────────────────────────────────────────────────

  /** The names a formula may reach for, rebuilt at every line because `base` moves.
   *
   *  `base` is required by MARKUP() and is markup.py's "running sum ABOVE it". Kyle's own cell
   *  names are seeded too (B5, D64, E69) so the Gyp soft-costs expression, which is stored
   *  verbatim, previews instead of reporting an unresolved name. */
  function context(base, amounts) {
    var ctx = {
      base: base, running_total: base, subtotal: SAMPLE_SUBTOTAL,
      hard_bid_on: 1, local: 1, taxable: 1, remodel: 1,
      county_rate: SAMPLE_COUNTY_RATE,
      B4: "Yes", B5: "No", D64: SAMPLE_SUBTOTAL, E69: SAMPLE_SUBTOTAL
    };
    for (var k in amounts) {
      if (Object.prototype.hasOwnProperty.call(amounts, k)) ctx[k] = amounts[k];
    }
    return ctx;
  }

  /** Walk the chain over the sample job.
   *
   *  A result under 1 in absolute value is read as a RATE and multiplied by the base; 1 or more
   *  is read as DOLLARS, which is what MARKUP() and a typed figure return. No markup rate in this
   *  chain reaches 100% (GP tops out at 52%) and no dollar line is under a dollar, so the two
   *  cannot collide on any real row — and the preview is explicitly not the pricing path.
   *
   *  `running` is the total THROUGH that line, which is the next line's base. It is printed under
   *  each amount so the compounding is visible on the screen instead of asserted in a paragraph.
   *
   *  ONE BROKEN LINE STOPS THE CHAIN. Everything below it reads "—, depends on <line>" and the
   *  total reads "Unpriceable". It never reads $0.00: a markup line that silently drops to zero
   *  is a bid that is wrong in the customer's favour and nobody notices. */
  function priceChain(rows) {
    var base = SAMPLE_SUBTOTAL;
    var amounts = {};
    var broken = null;
    var out = {};

    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      var k = r.line_key;

      if (broken) { out[k] = { state: "downstream", dependsOn: broken }; continue; }

      if (!r.applies) { out[k] = { state: "absent" }; continue; }

      // A CHAIN line the backend has stopped offering as editable and that has no sample value
      // here. Unreachable today (LINE_KEYS is CHAIN minus _NOT_EDITABLE) and deliberately does
      // NOT break the chain: a vocabulary change on the server should not read as a broken
      // formula on somebody's tab.
      if (!r.editable && k !== "contingency" && k !== "remodel_tax") {
        out[k] = { state: "unknownline" };
        continue;
      }

      if (k === "contingency") {
        base += SAMPLE_CONTINGENCY;
        out[k] = { state: "ok", amount: SAMPLE_CONTINGENCY, rate: null, running: base };
        amounts[k] = SAMPLE_CONTINGENCY;
        continue;
      }
      if (k === "remodel_tax") {
        var tax = base * SAMPLE_COUNTY_RATE;
        base += tax;
        out[k] = { state: "ok", amount: tax, rate: SAMPLE_COUNTY_RATE, running: base };
        amounts[k] = tax;
        continue;
      }

      var text = r.effective;
      if (!text) {
        out[k] = { state: "nobuiltin" };
        broken = r.label;
        continue;
      }

      var checked = M.validate(text);
      if (!checked.ok) {
        out[k] = { state: "invalid", error: checked.error };
        broken = r.label;
        continue;
      }

      var value;
      try {
        value = M.run(text, context(base, amounts));
      } catch (e) {
        out[k] = { state: "invalid", error: (e && e.message) ? e.message : String(e) };
        broken = r.label;
        continue;
      }
      // Kyle's own "error" sentinel lands here, and so does a 2-argument IF that fell through to
      // Excel's bare FALSE. Both are a refusal to price, not a zero.
      if (typeof value !== "number" || !isFinite(value)) {
        out[k] = { state: "invalid",
                   error: "that came out as " + JSON.stringify(value) + ", not a number" };
        broken = r.label;
        continue;
      }

      var isRate = Math.abs(value) < 1;
      var amount = isRate ? value * base : value;
      base += amount;
      // The percentage chip is shown only when the formula RETURNED a rate. A divide-up GP hands
      // back dollars, and back-deriving a percentage from them prints 42.858% beside a 30% band —
      // a number nobody typed, on the one line whose arithmetic already misleads people.
      out[k] = { state: "ok", amount: amount, rate: isRate ? value : null, running: base };
      amounts[k] = amount;
    }

    out.__total = broken
      ? { state: "unpriceable", dependsOn: broken }
      : { state: "ok", amount: base };
    return out;
  }

  // ── rendering ──────────────────────────────────────────────────────────────

  function tabsHtml() {
    var out = "";
    for (var i = 0; i < LAYOUTS.length; i++) {
      var lay = LAYOUTS[i];
      out += '<button type="button" role="tab" id="mk-tab-' + esc(lay) + '"' +
        ' aria-selected="' + (lay === LAYOUT ? "true" : "false") + '"' +
        ' aria-controls="mk-chain" data-layout="' + esc(lay) + '"' +
        ' data-focus="tab-' + esc(lay) + '">' + esc(labelFor(lay)) + "</button>";
    }
    return out;
  }

  function previewHtml(p) {
    if (!p) return "";
    if (p.state === "absent") {
      // NOT "0%" and NOT "$0.00". A line that does not exist on this tab has no figure.
      return '<span class="nodash" aria-label="not priced on this tab">&mdash;</span>';
    }
    if (p.state === "invalid" || p.state === "nobuiltin") {
      return '<span class="unpriced">Unpriceable</span>';
    }
    if (p.state === "downstream") {
      // The reason sits WHERE THE FIGURE IS MISSING rather than behind the row's disclosure: it
      // is the one line of explanation on this page that is about right now.
      return '<span class="nodash" aria-label="not priced">&mdash;</span>' +
        '<span class="run">depends on ' + esc(p.dependsOn) + "</span>";
    }
    if (p.state === "unknownline") {
      return '<span class="nodash" aria-label="not priced">&mdash;</span>';
    }
    return (p.rate == null ? "" : '<span class="pct">' + esc(pct(p.rate)) + "</span>") +
      '<span class="amt">' + esc(money(p.amount)) + "</span>" +
      (p.running == null ? "" : '<span class="run" title="running total through this line">' +
        "&rarr; " + esc(money(p.running)) + "</span>");
  }

  /** Soft delete, worded as what it does. "Delete" would read as "charge nothing"; the chain
   *  falls back to its hardcoded constant for a line with no rule.
   *
   *  IT HAS TO BE REACHABLE FROM THE OFF ROW TOO, which is why this is a function and not three
   *  lines at the bottom of the priced branch. Switching a line off files `applies=false`, so the
   *  row HAS a rule id -- and it is the row that most needs a way back, because the off state has
   *  no box to type in. Without this the only route home was the transient on-but-unsaved row:
   *  flip the switch on and the button appears, blur the empty box and the row reverts to off and
   *  takes the button with it. A corner with one exit, where the exit disappears when touched.
   *  Same family as the send-gate loop of 2026-09-03 -- the cure the screen named could not be
   *  carried out. */
  function dropBtnHtml(r) {
    // GATED HERE, not at the call sites. The ABSENT branch returns before the other caller
    // reaches its own `if (!ADMIN)` fork, so a gate per call site would have to be remembered
    // twice -- and the first version of this fix handed a non-admin a delete button on Gyp's
    // empty hard-bid row. One function, one rule.
    if (!ADMIN || !r.id) return "";
    return '<button class="ghostlink" type="button" data-drop="' + esc(r.line_key) + '"' +
      ' data-focus="d-' + esc(r.line_key) + '">Stop overriding this line</button>';
  }

  /** The message under a control. `err` is passed IN rather than read out of ERRORS, because a
   *  filed formula that cannot be parsed has to account for itself too — and a renderer that
   *  wrote that into ERRORS would make it stick after the formula was fixed. */
  function errHtml(k, err) {
    var msg = err || "";
    return '<div class="errmsg" data-err="' + esc(k) + '"' + (msg ? "" : " hidden") + ">" +
      esc(msg) + "</div>";
  }

  /** A ghost-link row, or nothing. One place, so an empty one never renders an empty box. */
  function btnsHtml(inner) {
    return inner ? '<div class="rowbtns">' + inner + "</div>" : "";
  }

  /** One info note under a control. Two callers need it — the ABSENT branch of rateCellHtml
   *  returns before noteHtml is ever reached — and a second hand-rolled copy of this span is how
   *  one component quietly becomes two. */
  function wbnoteHtml(text) {
    return '<span class="wbnote">' + icon("info") + "<span>" + esc(text) + "</span></span>";
  }

  /** The reach sentence where it is read for free: beside the box, not inside a closed
   *  disclosure. Same builder as the disclosure's copy, so the two cannot drift.
   *
   *  ADMIN ONLY, and that is a different call from the notes below it. "Built in — not overridden
   *  yet" is a fact about the ROW that a non-admin needs in order to read the page at all, so they
   *  get it. This sentence is about what TYPING here would do, and a non-admin cannot type — the
   *  fact is still in their row's disclosure, and the redesign's own
   *  `rateText == "16%"` assertion says a read-only rate cell is the rate and nothing else. */
  function reachNoteHtml(r) {
    if (!ADMIN) return "";
    var s = reachSentence(r).trim();
    return s ? wbnoteHtml(s) : "";
  }

  function noteHtml(r) {
    var parts = [];
    // DIRTY IS CHECKED FIRST. A row switched back on with an empty box is both unsaved AND
    // showing its built-in placeholder, and "Built in — not overridden yet" would be flatly
    // untrue there: what is stored is `applies=false`. The unsaved state is the one that changes
    // what the person should do next, so it is the one that gets said.
    if (r.dirty && ADMIN) {
      parts.push("Not saved yet — " + (r.filedText ? "leave the box to save it."
        : "type a rate, or switch the line back off."));
    } else if (!r.filedText && r.builtin) {
      // `filedText`, NOT `simpleFiled`. "Not overridden yet" is a fact about the TABLE: a filed
      // formula the simple control cannot hold is still an override, and telling somebody their
      // own stored rule is the built-in is the kind of wrong that gets typed over.
      parts.push("Built in — not overridden yet." + (!ADMIN ? ""
        : r.advanced ? " Typing here overrides it." : " Changing a number here overrides it."));
    } else if (!r.filedText && !r.builtin) {
      parts.push("No built-in on this page for " + labelFor(LAYOUT) +
        ". The tab cannot be priced until a rate is filed.");
    }
    // Said out loud, because the alternative is somebody hunting for a simple editor that this
    // row will never have. Gyp's soft-costs cell is a whole expression, sentinel and all.
    if (ADMIN && r.advanced && !r.canSimple) {
      parts.push(r.filedText
        ? "This isn't a plain rate or a ladder, so there's no simple editor for it."
        : "This tab's built-in is a whole expression, so there's no simple editor for it.");
    }
    // FIRST, because it is the note that decides whether the rest of this row matters. A rate
    // that reaches no bid is worth knowing before "not overridden yet".
    var out = reachNoteHtml(r);
    for (var i = 0; i < parts.length; i++) out += wbnoteHtml(parts[i]);
    return out;
  }

  /** Add-a-step, stop-overriding, and the Advanced door. Admin only — every one of them writes. */
  function rowBtnsHtml(r) {
    if (!ADMIN) return "";
    var out = "";
    if (!r.advanced && r.simple && r.simple.kind !== "flat") {
      out += '<button class="ghostlink" type="button" data-add="' + esc(r.line_key) + '"' +
        ' data-focus="add-' + esc(r.line_key) + '">' + icon("plus") + " " +
        (r.simple.kind === "bands" ? "Add a band" : "Add a step") + "</button>";
    }
    out += dropBtnHtml(r);
    // The expression box never goes away, and the way back out of it only appears when there is
    // something to go back TO: a formula no simple control can hold has no simple editor to open.
    if (r.advanced) {
      if (r.canSimple) {
        out += '<button class="ghostlink" type="button" data-adv="' + esc(r.line_key) + '"' +
          ' data-adv-to="off" data-focus="adv-' + esc(r.line_key) +
          '">Use the simple editor</button>';
      }
    } else {
      out += '<button class="ghostlink" type="button" data-adv="' + esc(r.line_key) + '"' +
        ' data-adv-to="on" data-focus="adv-' + esc(r.line_key) + '">Advanced</button>';
    }
    return btnsHtml(out);
  }

  function ariaFor(r, part) {
    var m = /^(edge|rate|local)-(\d+)$/.exec(part);
    if (!m) return r.label + " rate for " + labelFor(LAYOUT);
    var idx = Number(m[2]);
    var kind = r.simple ? r.simple.kind : "";
    var isDefault = kind === "bands" && r.simple && idx === r.simple.steps.length - 1;
    var noun = kind === "ladder" ? "step " + (idx + 1)
      : isDefault ? "rate above the last band" : "band " + (idx + 1);
    if (m[1] === "edge") return r.label + " " + noun + " job size on " + labelFor(LAYOUT);
    if (m[1] === "local") {
      return r.label + " " + noun + " is for local jobs only, on " + labelFor(LAYOUT);
    }
    return r.label + " " + noun + (isDefault ? "" : " rate") + " on " + labelFor(LAYOUT);
  }

  /** One number, with its unit. `.finput` carries the interaction states and `.num` narrows it,
   *  so there is one input component on this page rather than two drifting apart. */
  function numHtml(r, part, value, opts) {
    var o = opts || {};
    var k = r.line_key;
    var text = o.money ? fmtEdge(value) : trimNum(value);
    var pre = o.money ? '<span class="unit pre">$</span>' : "";
    var post = o.money ? "" : '<span class="unit">%</span>';
    if (o.readonly) {
      return '<span class="numwrap">' + pre + '<span class="ftext mono">' +
        esc(text || "—") + "</span>" + post + "</span>";
    }
    var bad = ERRORS[key(k)] && EPARTS[key(k)] === part;
    return '<span class="numwrap">' + pre +
      '<input class="finput num' + (bad ? " err" : "") + '" type="text" inputmode="decimal"' +
      ' spellcheck="false" autocomplete="off" data-simple="' + esc(k) + '"' +
      ' data-part="' + esc(part) + '" data-focus="s-' + esc(k) + "-" + esc(part) + '"' +
      ' aria-label="' + esc(o.aria || ariaFor(r, part)) + '"' +
      ' value="' + esc(text) + '" placeholder="' + esc(o.placeholder || "") + '" />' +
      post + "</span>";
  }

  function localHtml(r, i, s, readonly) {
    if (readonly) return s.localOnly ? '<span class="bandnote">local jobs only</span>' : "";
    return '<label class="bandnote"><input type="checkbox" data-simple="' + esc(r.line_key) +
      '" data-part="local-' + i + '" data-focus="s-' + esc(r.line_key) + "-local-" + i + '"' +
      ' aria-label="' + esc(ariaFor(r, "local-" + i)) + '"' +
      (s.localOnly ? " checked" : "") + " /> local jobs only</label>";
  }

  /** The ladder. Fixed tracks, one row per step, every threshold and every rate a number you can
   *  type — because the SHAPE is the information, and a text box holding
   *  MARKUP(BAND(subtotal, 6500,52%, …)) hides it completely. */
  function bandsHtml(r, m, readonly) {
    var ladder = m.kind === "ladder";
    var n = m.steps.length;
    var out = '<div class="bands">';
    for (var i = 0; i < n; i++) {
      var s = m.steps[i];
      var isDefault = !ladder && i === n - 1;
      out += '<div class="band' + (isDefault ? " last" : "") + '">' +
        '<span class="edgelbl">' +
        (isDefault ? "above that" : (ladder ? "from" : "up to")) + "</span>" +
        (isDefault ? "<span></span>"
          : numHtml(r, "edge-" + i, s.edge, { money: true, readonly: readonly })) +
        '<span class="arrow">' + icon("arrow", 14) + "</span>" +
        numHtml(r, "rate-" + i, s.rate ? s.rate.value : null, { readonly: readonly }) +
        ((readonly || isDefault) ? "<span></span>" : delBtnHtml(r, i)) +
        "</div>";
      if (ladder) out += localHtml(r, i, s, readonly);
    }
    if (ladder) {
      // The terminator is not editable, and saying so out loud beats a zero in a box: a give-back
      // that does not apply is nothing off, not a rate of nothing.
      out += '<div class="band last"><span class="edgelbl">otherwise</span><span></span>' +
        '<span class="arrow">' + icon("arrow", 14) + "</span>" +
        '<span class="ftext locked">nothing off</span><span></span></div>';
    }
    return out + "</div>";
  }

  function delBtnHtml(r, i) {
    var noun = r.simple && r.simple.kind === "bands" ? "band" : "step";
    return '<button class="bdel" type="button" data-del="' + esc(r.line_key) + '"' +
      ' data-idx="' + i + '" data-focus="del-' + esc(r.line_key) + "-" + i + '"' +
      ' aria-label="Remove ' + esc(r.label) + " " + noun + " " + (i + 1) + " on " +
      esc(labelFor(LAYOUT)) + '">' + icon("x", 13) + "</button>";
  }

  function flatHtml(r, m) {
    // The box is EMPTY when nothing is filed, and the placeholder shows the constant the chain is
    // using instead. Prefilling the box with a value that is not stored would be a lie about
    // state, and it is only safe on a ladder because a ladder's numbers cannot be shown any
    // other way.
    var filed = r.simpleFiled;
    return numHtml(r, "value", filed ? m.value : null, {
      money: m.unit === "$",
      placeholder: filed ? "" : (m.unit === "$" ? fmtEdge(m.value) : trimNum(m.value)),
      aria: r.label + " rate for " + labelFor(LAYOUT)
    });
  }

  function advancedHtml(r, err) {
    return '<input class="finput' + (err && !EPARTS[key(r.line_key)] ? " err" : "") +
      '" type="text" spellcheck="false" autocomplete="off"' +
      ' data-formula="' + esc(r.line_key) + '" data-focus="f-' + esc(r.line_key) + '"' +
      ' aria-label="' + esc(r.label) + ' formula for ' + esc(labelFor(LAYOUT)) + '"' +
      ' value="' + esc(r.filedText) + '"' +
      ' placeholder="' + esc(r.builtin || "no built-in — type a formula") + '" />';
  }

  function rateCellHtml(r, p) {
    var k = r.line_key;

    // ── ABSENT ──────────────────────────────────────────────────────────────
    // No control, no empty box, no zero. A caption that names the tab, and nothing to type into.
    if (r.editable && !r.applies) {
      // THE REACH NOTE BELONGS ON THIS ROW MOST OF ALL. Switching a line off here files
      // `applies=false`, which markup.py keeps apart from a filed zero on purpose — so the
      // workbook goes on charging its own rate for the line, and the row has to say so rather
      // than letting somebody believe they have switched a charge off.
      //
      // The empty-cell note below is deliberately NOT routed through wbnoteHtml, unlike the ones
      // in noteHtml: test_markup_page.py's off-row mutation anchors on the literal
      // `"</span></span>" +` / `btnsHtml(dropBtnHtml(r));` tail, and folding that span into the
      // helper would leave that mutation matching nothing and the test passing while defending
      // nothing. The reach note goes in FRONT of it, which is the reading order anyway.
      return '<span class="absent-note">' + icon("slash", 13) +
        " Not used on " + esc(nounFor(LAYOUT)) + "</span>" +
        reachNoteHtml(r) +
        '<span class="wbnote">' + icon("info") +
        "<span>The cell is empty on this tab, which is not the same as 0%." +
        (r.dirty ? " Unsaved." : "") + "</span></span>" +
        btnsHtml(dropBtnHtml(r));
    }

    // ── context: in the chain, set somewhere else ───────────────────────────
    if (!r.editable) {
      var text = k === "contingency" ? "Typed on the bid"
        : k === "remodel_tax" ? "Typed % → county table → 6.5% floor"
        : "Not set here";
      return '<span class="ftext locked">' + esc(text) + "</span>";
    }

    // A message the admin earned by typing wins, but a formula that was ALREADY filed and cannot
    // be read has to account for itself too — otherwise the row reads "Unpriceable" and the only
    // way to find out why is to retype it. Computed here rather than written into ERRORS: a
    // renderer that filed its own message would leave it stuck on the row after the fix.
    var err = ERRORS[key(k)] || (p && p.state === "invalid" ? p.error : "") || "";

    // ── a non-admin reads it ────────────────────────────────────────────────
    // Read-only is not a redaction: the rate, the ladder and the preview are all here, and only
    // the controls are gone.
    if (!ADMIN) {
      if (r.simple && r.simple.kind !== "flat") return bandsHtml(r, r.simple, true) + noteHtml(r);
      var ro = r.filedText || (r.simple ? simpleTo(r.simple) : "") || r.builtin;
      return '<span class="ftext mono' + (r.filedText ? "" : " dim") + '">' +
        esc(ro || "No built-in on this page for " + labelFor(LAYOUT)) + "</span>" + noteHtml(r);
    }

    // ── an admin edits it ───────────────────────────────────────────────────
    var ctl = r.advanced ? advancedHtml(r, err)
      : r.simple.kind === "flat" ? flatHtml(r, r.simple)
      : bandsHtml(r, r.simple, false);
    return ctl + errHtml(k, err) + noteHtml(r) + rowBtnsHtml(r);
  }

  function appliesCellHtml(r) {
    if (!r.editable) return '<span class="swro">Always</span>';
    if (!ADMIN) {
      return '<span class="swro">' + (r.applies ? "Yes" : "Not used") + "</span>";
    }
    // A REAL button with role=switch. Native tab order, native Space and Enter, and aria-checked
    // as the single source of truth — no keydown handler to forget, and nothing to get out of
    // step with a separate class.
    return '<span class="swwrap">' +
      '<button class="sw" type="button" role="switch"' +
      ' aria-checked="' + (r.applies ? "true" : "false") + '"' +
      ' data-applies="' + esc(r.line_key) + '" data-focus="a-' + esc(r.line_key) + '"' +
      ' aria-label="' + esc(r.label) + ' applies on ' + esc(labelFor(LAYOUT)) + '"></button>' +
      '<span class="swl">' + (r.applies ? "Yes" : "Not used") + "</span></span>";
  }

  /** Name, chip, one-line caption, and the disclosure the old WHAT IT DOES column became.
   *
   *  `explain` is passed IN rather than read off `r`, because the row's prose is the line's own
   *  explanation PLUS whether a rate filed on it reaches the workbook — and the second half is
   *  assembled in rowHtml, next to the mutation anchor the suite aims at. */
  function lineCellHtml(r, explain) {
    var out = '<span class="nm">' + esc(r.label) +
      (r.chip ? '<span class="chip">' + esc(r.chip) + "</span>" : "") + "</span>";
    if (r.sub) out += '<span class="sub">' + esc(r.sub) + "</span>";
    if (explain) {
      out += '<details class="help"' + (HELP[r.line_key] ? " open" : "") + ">" +
        '<summary data-help="' + esc(r.line_key) + '" data-focus="h-' + esc(r.line_key) + '">' +
        icon("chev") + " " + esc(r.helpLabel) + "</summary>" +
        '<p class="explain">' + esc(explain) + "</p></details>";
    }
    return out;
  }

  function rowHtml(r, p) {
    var absent = r.editable && !r.applies;
    // ── WHETHER THIS ROW REACHES THE WORKBOOK ────────────────────────────────
    // Two changes met here and both had to survive. The redesign deleted the WHAT IT DOES column
    // and moved every line's prose into the row's own disclosure; the rate wiring had just added
    // this sentence to that column. Dropping it in the move would put the page back to letting an
    // admin file a GP ladder, watch it save with a green tick, and move no price — the exact
    // failure the deleted "nothing is priced yet" paragraph was written about, now narrowed onto
    // the four lines the workbook still does not read.
    //
    // `reachSentence` returns "" for the two lines nobody sets here, so contingency and
    // remodel_tax keep markup.py's own wording character for character.
    //
    // THE DISCLOSURE STARTS CLOSED, so this is not the whole answer on its own: the same string
    // from the same builder is also the first note under the rate box, where an admin reads it
    // without opening anything. One builder, two call sites — a second wording for one fact is
    // how `--r-s` and `--r-sm` came to differ by a letter and a pixel.
    //
    // The two preview-driven rewrites this line used to sit behind went with the column and are
    // not reinstated: `downstream` now prints "depends on <line>" where the missing figure is,
    // and `nobuiltin` reads Unpriceable with the reason in its own rate cell.
    var explain = r.explain;
    explain += reachSentence(r);
    var cls = "mkrow" + (absent ? " absent" : "") + (r.editable ? "" : " ctx");
    return '<div class="' + cls + '" data-row="' + esc(r.line_key) + '">' +
      '<div class="line">' + lineCellHtml(r, explain) + "</div>" +
      '<div class="rate">' + rateCellHtml(r, p) + "</div>" +
      '<div class="applies">' + appliesCellHtml(r) + "</div>" +
      '<div class="prev">' + previewHtml(p) + "</div>" +
      "</div>";
  }

  function chainHtml() {
    if (LOADFAIL) {
      return '<p class="state"><b>The markup rates didn\'t load.</b>' + esc(LOADFAIL) +
        '<br /><button class="btn" type="button" id="mk-retry">Try again</button></p>';
    }
    if (!LOADED) {
      return '<p class="state"><b>Loading the chain…</b>Reading the rates filed for this tab.' +
        "</p>";
    }
    if (!LAYOUT) {
      return '<p class="state"><b>No sheet layouts came back.</b>The chain cannot be shown ' +
        "without them — reload, and tell Hanz if it happens twice.</p>";
    }

    var rows = rowStates();
    var priced = priceChain(rows);

    var out = '<div class="mkrow head">' +
      "<div>Line</div><div>Rate</div><div>Applies</div>" +
      '<div class="prev">Preview</div></div>';

    out += '<div class="mkrow ctx"><div class="line">' +
      '<span class="nm">Sub-total costs<span class="chip">The base</span></span>' +
      '<span class="sub">material + labor + escalation + burden</span></div>' +
      '<div class="rate"><span class="ftext locked">Comes off the takeoff and labor tabs' +
      "</span></div>" +
      '<div class="applies"><span class="swro">Always</span></div>' +
      // The one typeable box in a row that is otherwise all read-only, so it says out loud that
      // it is a what-if and not a filed rate. `data-focus` is what lets render() put the caret
      // back mid-keystroke -- every preview below repaints on each character typed.
      '<div class="prev"><span class="numwrap"><span class="unit pre">$</span>' +
      '<input class="finput num" type="text" inputmode="decimal" spellcheck="false"' +
      ' autocomplete="off" data-subtotal="1" data-focus="sample-subtotal"' +
      ' aria-label="Sample sub-total the preview prices, in dollars"' +
      ' value="' + esc(SUBTOTAL_RAW == null ? fmtEdge(SAMPLE_SUBTOTAL) : SUBTOTAL_RAW) + '" /></span>' +
      '<span class="prevnote">try a job size</span></div></div>';

    for (var i = 0; i < rows.length; i++) out += rowHtml(rows[i], priced[rows[i].line_key]);

    var total = priced.__total;
    out += '<div class="mkrow grand"><div class="line">' +
      '<span class="nm">Total lump sum</span><span class="sub">' +
      (total.state === "ok"
        ? esc("on a " + money(SAMPLE_SUBTOTAL) + " sub-total")
        : esc("can't price this tab — fix " + total.dependsOn)) +
      '</span></div><div class="rate"></div><div class="applies"></div><div class="prev">' +
      (total.state === "ok"
        ? '<span class="amt">' + esc(money(total.amount)) + "</span>"
        : '<span class="unpriced">Unpriceable</span>') +
      "</div></div>";
    return out;
  }

  /** Paint everything, and put the focus back where the person left it.
   *
   *  A re-render on `change` that steals the focus somebody just tabbed into is a bug this repo
   *  has shipped before, so the restore is deliberate rather than hoped for: every control
   *  carries a stable `data-focus` key, and the caret position rides along with it. */
  function render(opts) {
    var o = opts || {};
    rendering = true;
    try {
      // THREE WAYS IN, and the difference between them is the whole keyboard story:
      //
      //   render()                    keep whatever has the focus now — a click somewhere else
      //                               repainted the table under an open caret.
      //   render({ focus: false })     take the focus nowhere. The person left for the page.
      //   render({ focusKey: k })     put it on `k`. Used on the way OUT of a box, because during
      //                               `focusout` document.activeElement is still the control
      //                               being LEFT: "restoring" that would yank the caret back out
      //                               of the box the person just tabbed INTO. `ev.relatedTarget`
      //                               is where the focus is really going, and on a ladder of ten
      //                               boxes this is the difference between tabbing across a row
      //                               and being thrown out of it at every field.
      var focusKey = null;
      if (Object.prototype.hasOwnProperty.call(o, "focusKey")) {
        focusKey = o.focusKey || null;
      } else if (o.focus !== false) {
        var active = document.activeElement;
        focusKey = (active && active.getAttribute) ? active.getAttribute("data-focus") : null;
      }
      var selStart = null, selEnd = null;
      if (focusKey) {
        var from = document.querySelector('[data-focus="' + focusKey + '"]');
        if (from) {
          try { selStart = from.selectionStart; selEnd = from.selectionEnd; } catch (e) {}
        }
      }

      $("mk-tabs").innerHTML = tabsHtml();
      $("mk-chain").innerHTML = chainHtml();
      if (LAYOUT) $("mk-chain").setAttribute("aria-labelledby", "mk-tab-" + LAYOUT);

      paintNotes();

      if (focusKey) {
        var again = document.querySelector('[data-focus="' + focusKey + '"]');
        if (again && again.focus) {
          again.focus();
          if (selStart != null && again.setSelectionRange) {
            try { again.setSelectionRange(selStart, selEnd); } catch (e2) {}
          }
        }
      }
    } finally { rendering = false; }
  }

  /** The three notes above the table: read-only, day-one fallback, and the broken banner.
   *
   *  All three toggle with `el.hidden`, which markup.html makes win outright — a class that sets
   *  `display` beats the attribute and this repo has shipped four of those. */
  function paintNotes() {
    $("mk-ro").hidden = ADMIN;

    var rows = LOADED && LAYOUT ? rowStates() : [];
    var overrides = rows.filter(function (r) { return r.editable && r.source === "filed"; });
    var fallback = $("mk-fallback");
    if (!LOADED || !LAYOUT) {
      fallback.hidden = true;
    } else if (!overrides.length) {
      fallback.hidden = false;
      fallback.textContent = "Nothing is filed for " + labelFor(LAYOUT) + " yet, and that is " +
        "the normal first state — every line below is priced by the constant built into the " +
        "estimator. Changing a rate here overrides one; removing it hands the line back.";
    } else {
      fallback.hidden = false;
      fallback.textContent = overrides.length + " of " + rows.filter(function (r) {
        return r.editable;
      }).length + " lines on " + labelFor(LAYOUT) + " are overridden here. The rest are " +
        "priced by the constant built into the estimator.";
    }

    var priced = rows.length ? priceChain(rows) : { __total: { state: "ok" } };
    var broken = priced.__total.state !== "ok" ? priced.__total.dependsOn : "";
    $("mk-broken").hidden = !broken;
    $("mk-broken-line").textContent = broken ? broken + " can't be priced." : "";
    $("mk-broken-rest").textContent = broken
      ? "Every line below it reads Unpriceable rather than zero, and " + labelFor(LAYOUT) +
        " can't be generated until it's fixed."
      : "";

    $("mk-foot").textContent = "Preview figures are computed against a sample " +
      money(SAMPLE_SUBTOTAL) + " job with a " + pct(SAMPLE_COUNTY_RATE) + " county remodel " +
      "rate, so a rate's effect is visible the moment it's typed — they price nothing real. " +
      "The arrow under each amount is the running total through that line, which is the next " +
      "line's base. The chain that prices a bid reads these same rows.";
  }

  // ── errors on a row, without a repaint ─────────────────────────────────────

  /** Say what is wrong WITHOUT re-rendering.
   *
   *  A repaint here would throw away the half-typed characters that caused the message and move
   *  the caret out of the box being corrected. The message element is already in the row, so it
   *  is written to directly — the same thing the `input` handler does in reverse. */
  function showRowError(lineKey, msg, part) {
    ERRORS[key(lineKey)] = msg;
    if (part) EPARTS[key(lineKey)] = part; else delete EPARTS[key(lineKey)];
    var box = document.querySelector('[data-err="' + lineKey + '"]');
    if (box) { box.textContent = msg; box.hidden = false; }
    var ctl = part ? document.querySelector('[data-focus="s-' + lineKey + "-" + part + '"]') : null;
    if (ctl && ctl.classList) ctl.classList.add("err");
    say(msg);
  }

  function clearRowError(lineKey) {
    if (!ERRORS[key(lineKey)]) return;
    delete ERRORS[key(lineKey)];
    delete EPARTS[key(lineKey)];
    var box = document.querySelector('[data-err="' + lineKey + '"]');
    if (box) { box.textContent = ""; box.hidden = true; }
  }

  // ── reading the simple controls back ───────────────────────────────────────

  function ctlOf(lineKey, part) {
    return document.querySelector('[data-focus="s-' + lineKey + "-" + part + '"]');
  }
  function readCtl(lineKey, part) {
    var el = ctlOf(lineKey, part);
    return el ? String(el.value == null ? "" : el.value).trim() : "";
  }
  function readChecked(lineKey, part) {
    var el = ctlOf(lineKey, part);
    return !!(el && el.checked);
  }

  /** Read one row's simple controls back out of the DOM and rebuild the formula string.
   *
   *  FROM THE DOM, not from a model kept in step with every keystroke. The DOM is what the person
   *  is looking at, and this page judges a box on the way OUT of it rather than on every
   *  character — so there is nothing to keep in step, and no half-typed value can be lost to a
   *  model that refused it.
   *
   *  Returns { text } or { error, part }. An empty one-number box is `{ text: "" }`, which is
   *  "nothing filed" and NOT an error. */
  function recompose(lineKey) {
    var r = rowState(lineKey);
    if (!r.simple) return { error: "There is no simple rate to read on this line." };
    var kind = r.simple.kind;

    if (kind === "flat") {
      var raw = readCtl(lineKey, "value");
      if (!raw) return { text: "" };
      var n = parseNum(raw);
      if (n === null) {
        return { error: "“" + raw + "” isn't a number — type a rate like 2.7.",
                 part: "value" };
      }
      return { text: simpleTo({ kind: "flat", markup: r.simple.markup, unit: r.simple.unit,
                                value: n, style: r.simple.style }) };
    }

    var steps = [];
    var n2 = r.simple.steps.length;
    for (var i = 0; i < n2; i++) {
      var s = r.simple.steps[i];
      // A ladder's steps ALL have a threshold; a band's last one is the default and has none.
      var wantEdge = kind === "ladder" || i < n2 - 1;
      var rateRaw = readCtl(lineKey, "rate-" + i);
      var rateVal = parseNum(rateRaw);
      if (rateVal === null) {
        return { error: rateRaw
          ? "“" + rateRaw + "” isn't a rate — type a number like 45 or -2.5."
          : "Every step needs a rate.", part: "rate-" + i };
      }
      var step = { edge: null, localOnly: false,
                   rate: { value: rateVal, style: (s.rate && s.rate.style) || "pct" } };
      if (wantEdge) {
        var edgeRaw = readCtl(lineKey, "edge-" + i);
        var edgeVal = parseNum(edgeRaw);
        if (edgeVal === null) {
          return { error: edgeRaw
            ? "“" + edgeRaw + "” isn't a job size — type a number like 15000."
            : "Every step needs a job size.", part: "edge-" + i };
        }
        step.edge = edgeVal;
      }
      if (kind === "ladder") step.localOnly = readChecked(lineKey, "local-" + i);
      steps.push(step);
    }
    return { text: simpleTo({ kind: kind, markup: r.simple.markup, steps: steps }) };
  }

  /** Recompose one row, and save it if it changed into something readable.
   *
   *  `focusKey` is where the focus is going, not where it was — see render(). */
  function commitSimple(lineKey, focusKey) {
    var r = rowState(lineKey);
    var res = recompose(lineKey);

    if (res.error) { showRowError(lineKey, res.error, res.part); return; }

    if (res.text === r.baseline) {
      // Tabbed through and changed nothing. THE CASE THAT MATTERS: a ladder is ten boxes, and a
      // repaint per blur would replace the box the browser is moving the focus into. It also
      // means a control seeded from a built-in never files that built-in as an override just
      // because somebody looked at it.
      clearRowError(lineKey);
      if (r.sdraft) { delete SDRAFT[key(lineKey)]; render({ focusKey: focusKey }); }
      return;
    }

    if (!res.text) {
      // The one-number box, emptied. Same rule as the expression box: emptying is not how a rule
      // is removed — that would leave `applies=true` with nothing to run, which markup.py refuses.
      if (r.id) {
        say("Emptying the box doesn't remove the rate. Use “Stop overriding this line”.");
      }
      delete LOCAL[key(lineKey)];
      delete SDRAFT[key(lineKey)];
      clearRowError(lineKey);
      render({ focusKey: focusKey });
      return;
    }

    // Belt and braces. The serializers above write the grammar, so this cannot fail today — and
    // if a future shape ever makes it fail, the person hears about it here instead of the server
    // storing a rate nothing can read.
    var checked = M.validate(res.text);
    if (!checked.ok) {
      showRowError(lineKey, "That came out as something the engine can't read: " + checked.error,
                   res.part);
      return;
    }

    LOCAL[key(lineKey)] = { applies: true, formula: res.text };
    delete SDRAFT[key(lineKey)];
    clearRowError(lineKey);
    say("");
    render({ focusKey: focusKey });
    save(lineKey);
  }

  function addStep(lineKey) {
    var r = rowState(lineKey);
    if (!r.simple || r.simple.kind === "flat") return;
    var model = cloneModel(r.simple);
    var blank = { edge: null, rate: null, localOnly: false };
    var at;
    if (model.kind === "bands") {
      // BEFORE the default. A band is a ceiling and the default is what everything above the top
      // ceiling gets, so a new band appended after it could never be reached.
      at = model.steps.length - 1;
      model.steps.splice(at, 0, blank);
    } else {
      at = model.steps.length;
      model.steps.push(blank);
    }
    SDRAFT[key(lineKey)] = model;
    clearRowError(lineKey);
    say("Fill in the new " + (model.kind === "bands" ? "band" : "step") +
        "'s job size and rate to save it.");
    render({ focusKey: "s-" + lineKey + "-edge-" + at });
  }

  function dropStep(lineKey, idx) {
    var r = rowState(lineKey);
    if (!r.simple || !r.simple.steps || !r.simple.steps[idx]) return;
    if (r.simple.kind === "bands" && idx === r.simple.steps.length - 1) return;
    if (r.simple.kind === "ladder" && r.simple.steps.length === 1) {
      say("A give-back needs at least one step. Switch the line off instead.");
      return;
    }
    var model = cloneModel(r.simple);
    model.steps.splice(idx, 1);
    SDRAFT[key(lineKey)] = model;
    clearRowError(lineKey);
    // Painted first, so the recompose below reads the ladder the person is now looking at. A
    // removal is a decision rather than half a word, so it saves straight away when it can. The
    // focus lands on the step above the one that went, because the button it was on is gone.
    var back = "s-" + lineKey + "-rate-" + Math.max(0, idx - 1);
    render({ focusKey: back });
    commitSimple(lineKey, back);
  }

  // ── saving ─────────────────────────────────────────────────────────────────

  function replaceRule(row) {
    var next = RULES.filter(function (r) {
      return !(r.layout === row.layout && r.line_key === row.line_key);
    });
    next.push(row);
    RULES = next;
  }

  async function save(lineKey) {
    var r = rowState(lineKey);
    if (!r.editable) return;
    var body = {
      layout: LAYOUT,
      line_key: lineKey,
      applies: r.applies,
      // validate_rule is NOT partial: it states the whole row every time, so `notes` has to ride
      // along or a save from this page would silently clear a note filed elsewhere.
      notes: r.notes || "",
      formula: r.applies ? r.formula : null
    };
    if (r.applies && !r.formula) {
      // The backend would refuse this, correctly: an empty formula on a line that applies would
      // price the job to nothing without saying so. Say it here instead of collecting a 400.
      say("Type a rate for " + r.label + ", or switch it off.");
      return;
    }
    say("");
    try {
      var res = await api("/api/markup/rules",
        { method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body) });
      if (res.status === 403) {
        ADMIN = false;
        say("Changing markup rates is admin-only. Nothing was saved.");
        render();
        return;
      }
      var json = await res.json().catch(function () { return {}; });
      if (!res.ok) {
        ERRORS[key(lineKey)] = json.detail || ("HTTP " + res.status);
        delete EPARTS[key(lineKey)];
        say(json.detail || "That didn't save.");
        render();
        return;
      }
      replaceRule(json.rule);
      delete LOCAL[key(lineKey)];
      delete ERRORS[key(lineKey)];
      delete EPARTS[key(lineKey)];
      render();
    } catch (err) {
      ERRORS[key(lineKey)] = "Couldn't reach the server.";
      delete EPARTS[key(lineKey)];
      say("Couldn't save that. " + (err && err.message ? err.message : ""));
      render();
    }
  }

  async function drop(lineKey) {
    var r = rowState(lineKey);
    if (!r.id) return;
    var ok = await TW.confirmDanger({
      tone: "warn",
      title: "Stop overriding this line?",
      name: r.label,
      after: " goes back to the constant built into the estimator on " + labelFor(LAYOUT) + ".",
      // Said out loud because the opposite reading is the expensive one: removing a rule is not
      // "charge nothing for this line".
      detail: "It does not price the line at nothing" +
        (r.builtin ? " — the chain uses " + r.builtin + " again." : "."),
      confirmText: "Stop overriding"
    });
    if (!ok) return;
    try {
      var res = await api("/api/markup/rules/" + encodeURIComponent(r.id), { method: "DELETE" });
      if (res.status === 403) {
        ADMIN = false;
        say("Changing markup rates is admin-only. Nothing was removed.");
        render();
        return;
      }
      if (res.status === 404) {
        // It went in another tab. Reload rather than insisting on a stale row.
        say("That rule had already been removed. Showing the current rates.");
        await reload();
        return;
      }
      if (!res.ok) { say("That didn't save. HTTP " + res.status); return; }
      RULES = RULES.filter(function (x) { return x.id !== r.id; });
      delete LOCAL[key(lineKey)];
      delete SDRAFT[key(lineKey)];
      delete ERRORS[key(lineKey)];
      delete EPARTS[key(lineKey)];
      render();
    } catch (err) {
      say("Couldn't remove that. " + (err && err.message ? err.message : ""));
    }
  }

  /** The first control on a row, whichever kind it turned out to be. Used when the page needs to
   *  put somebody's next keystroke where it will do some good. */
  function firstControl(lineKey) {
    var tries = ["s-" + lineKey + "-value", "s-" + lineKey + "-edge-0",
                 "s-" + lineKey + "-rate-0", "f-" + lineKey];
    for (var i = 0; i < tries.length; i++) {
      var el = document.querySelector('[data-focus="' + tries[i] + '"]');
      if (el) return el;
    }
    return null;
  }

  // ── events ─────────────────────────────────────────────────────────────────

  $("mk-tabs").addEventListener("click", function (ev) {
    var t = ev.target;
    var btn = t && t.closest ? t.closest("[data-layout]") : null;
    if (!btn) return;
    var lay = btn.getAttribute("data-layout");
    if (!lay || lay === LAYOUT) return;
    LAYOUT = lay;
    say("");
    render();
  });

  $("mk-chain").addEventListener("click", function (ev) {
    var t = ev.target;
    if (!t || !t.closest) return;

    var retry = t.closest("#mk-retry");
    if (retry) { reload(); return; }

    // Recorded, not performed: <details> opens itself, and this only remembers which ones are
    // open so the next repaint does not snap them shut.
    var help = t.closest("[data-help]");
    if (help) {
      var hk = help.getAttribute("data-help");
      HELP[hk] = !HELP[hk];
      return;
    }

    var adv = t.closest("[data-adv]");
    if (adv) {
      var ak = adv.getAttribute("data-adv");
      ADV[key(ak)] = adv.getAttribute("data-adv-to") === "on";
      delete SDRAFT[key(ak)];
      clearRowError(ak);
      say("");
      render();
      var box = firstControl(ak);
      if (box && box.focus) box.focus();
      return;
    }

    var addBtn = t.closest("[data-add]");
    if (addBtn) { addStep(addBtn.getAttribute("data-add")); return; }

    var delBtn = t.closest("[data-del]");
    if (delBtn) {
      dropStep(delBtn.getAttribute("data-del"), Number(delBtn.getAttribute("data-idx")));
      return;
    }

    var sw = t.closest("[data-applies]");
    if (sw) {
      var swKey = sw.getAttribute("data-applies");
      var cur = rowState(swKey);
      var next = !cur.applies;
      LOCAL[key(swKey)] = { applies: next, formula: cur.formula };
      clearRowError(swKey);
      if (next && !cur.formula) {
        // Switched ON with nothing to run. Do not post a save the backend must refuse — show the
        // control and say what it needs.
        say("Type a rate for " + cur.label + " and leave the box to save it.");
        render();
        var ctl = firstControl(swKey);
        if (ctl && ctl.focus) ctl.focus();
        return;
      }
      render();
      save(swKey);
      return;
    }

    var dropBtn = t.closest("[data-drop]");
    if (dropBtn) { drop(dropBtn.getAttribute("data-drop")); return; }
  });

  /** Typing clears a message it has already been given; it never earns a new one.
   *
   *  Validation happens on the way OUT of the box, not on every keystroke — half a rate is
   *  always invalid, and being told so mid-word teaches somebody to ignore the message. */
  $("mk-chain").addEventListener("input", function (ev) {
    var t = ev.target;
    if (!t || !t.getAttribute) return;

    // THE WHAT-IF BOX REPAINTS ON EVERY KEYSTROKE, unlike every other input on this page, and the
    // difference is what each one is for: a rate is a value being FILED, so it is validated on the
    // way out of the box; this is a question being ASKED, and an answer that waited for blur would
    // not be an answer. A half-typed figure falls back to the default rather than painting $NaN
    // down every row below -- "1" on the way to "15000" is not an error worth showing.
    if (t.getAttribute("data-subtotal")) {
      if (rendering) return;
      SUBTOTAL_RAW = t.value;
      var typed = parseNum(t.value);
      SAMPLE_SUBTOTAL = (typed != null && typed > 0) ? typed : SAMPLE_SUBTOTAL_DEFAULT;
      render();
      return;
    }

    var k = t.getAttribute("data-formula") || t.getAttribute("data-simple");
    if (!k) return;
    if (ERRORS[key(k)]) {
      delete ERRORS[key(k)];
      delete EPARTS[key(k)];
      if (t.classList) t.classList.remove("err");
      var msg = document.querySelector('[data-err="' + k + '"]');
      if (msg) { msg.textContent = ""; msg.hidden = true; }
    }
  });

  /** A checkbox is a decision, not half a word, so it commits on `change` — and the focus is put
   *  straight back on the box that was just ticked. A repaint on `change` that steals the focus
   *  somebody tabbed into is the exact bug this repo has shipped before. */
  $("mk-chain").addEventListener("change", function (ev) {
    if (rendering) return;
    var t = ev.target;
    if (!t || !t.getAttribute) return;
    var k = t.getAttribute("data-simple");
    var part = t.getAttribute("data-part") || "";
    if (!k || part.indexOf("local-") !== 0) return;
    commitSimple(k, t.getAttribute("data-focus"));
  });

  /** `focusout` rather than `blur`, because blur does not bubble and these boxes are replaced by
   *  every render. Guarded against the render that itself moves focus. */
  $("mk-chain").addEventListener("focusout", function (ev) {
    if (rendering) return;
    var t = ev.target;
    if (!t || !t.getAttribute) return;

    // Where the focus is HEADED. During focusout document.activeElement is still this box, so
    // this is the only honest answer to "what should the repaint focus?".
    var rel = ev.relatedTarget;
    var goingTo = (rel && rel.getAttribute) ? rel.getAttribute("data-focus") : null;

    // Let go of the raw text so the box settles back to a separated figure ("6,500"), and so an
    // abandoned half-entry does not sit there reading as the number the previews below used.
    if (t.getAttribute("data-subtotal")) {
      SUBTOTAL_RAW = null;
      render({ focusKey: goingTo });
      return;
    }

    var sk = t.getAttribute("data-simple");
    if (sk) {
      if ((t.getAttribute("data-part") || "").indexOf("local-") === 0) return;   // handled above
      commitSimple(sk, goingTo);
      return;
    }

    var k = t.getAttribute("data-formula");
    if (!k) return;

    var cur = rowState(k);
    var typed = String(t.value == null ? "" : t.value).trim();
    if (typed === (cur.rule ? (cur.rule.formula || "") : "") && !LOCAL[key(k)]) return;

    if (!typed) {
      if (cur.id) {
        // Emptying the box is not how a rule is removed — that would leave `applies=true` with
        // nothing to run, which is the state markup.py refuses outright.
        say("Emptying the box doesn't remove the rule. Use “Stop overriding this line”.");
      }
      delete LOCAL[key(k)];
      render({ focusKey: goingTo });
      return;
    }

    // The backend checks a formula's SHAPE and nothing about its grammar, so it is checked here,
    // while the admin is still looking at it.
    var checked = M.validate(typed);
    if (!checked.ok) {
      LOCAL[key(k)] = { applies: true, formula: typed };
      ERRORS[key(k)] = checked.error;
      delete EPARTS[key(k)];
      say("That formula can't be read, so it wasn't saved.");
      render({ focusKey: goingTo });
      return;
    }
    LOCAL[key(k)] = { applies: true, formula: typed };
    delete ERRORS[key(k)];
    delete EPARTS[key(k)];
    render({ focusKey: goingTo });
    save(k);
  });

  // ── loading ────────────────────────────────────────────────────────────────

  async function reload() {
    LOADFAIL = "";
    LOADED = false;
    render();
    try {
      var res = await api("/api/markup/rules");
      if (!res.ok) throw new Error("HTTP " + res.status);
      var json = await res.json();
      RULES = json.rules || [];
      LINE_KEYS = json.line_keys || [];
      // THE TABS COME FROM THE API, so the editor cannot keep a drifting second copy of them.
      // `combo` is filtered anyway: markup.py refuses the string by name because a combo job is
      // two option lines each priced off its own tab, and a Combo tab here would offer to store a
      // rate that could never be read.
      LAYOUTS = (json.layouts || []).filter(function (l) {
        return l && String(l).toLowerCase() !== "combo";
      });
      if (LAYOUTS.indexOf(LAYOUT) < 0) LAYOUT = LAYOUTS[0] || "";
      LOADED = true;
      render();
    } catch (err) {
      LOADFAIL = "The server said: " + (err && err.message ? err.message : String(err)) + ".";
      LOADED = true;
      render();
    }
  }

  async function load() {
    // Settled BEFORE the first paint. A page that flashes editable and then locks is worse than
    // one that resolves late, and an admin control shown to a non-admin is a button that 403s.
    try {
      if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready;
      var me = (window.TWAuth && window.TWAuth.user && window.TWAuth.user()) || {};
      ADMIN = me.role === "admin" || me.role === "super_admin";
    } catch (e) { ADMIN = false; }
    paintNotes();
    await reload();
  }

  load();
})();
