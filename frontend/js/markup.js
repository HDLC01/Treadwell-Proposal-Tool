// Markup page — the markup chain's rates, as editable formula strings, per sheet LAYOUT.
// Externalized (CSP: no inline scripts). Do not add inline scripts.
//
// WHAT THIS PAGE IS. backend/markup.py's module docstring is the authority on the domain; read it
// first. In short: the Polish beta's price walks one compounding chain over a subtotal —
// gp → hard_bid → contingency → super_pto → soft_costs → remodel_tax → bond — each line's base
// being the running sum ABOVE it. Those rates are hardcoded constants in polish-bid-core.js. The
// markup_rules table is where an admin overrides them, and this is that table's screen.
//
// NO eval, NO new Function. Every formula is parsed and evaluated by markup-core.js, a hand-rolled
// tokenizer + recursive-descent parser, because prod's CSP is `script-src 'self'
// https://cdn.jsdelivr.net` with no unsafe-eval. A dynamic-code shortcut here would work locally
// and die silently in production.
//
// THREE ROW STATES, and keeping them apart is the whole job:
//
//   filed / built-in   a formula applies and prices the line. An empty box means "no override
//                      filed yet, the chain uses its built-in constant" — the placeholder shows
//                      which constant.
//   ABSENT             `applies === false`, `formula === null`. Gyp has NO hard-bid rate: the
//                      workbook cell is EMPTY, not 0. Rendered as a greyed row with a caption
//                      naming the tab and NO input at all — an empty editable box invites
//                      somebody to fill it in, and "0%" reads as a discount that was declined.
//   read-only          `contingency` and `remodel_tax`. In CHAIN, excluded from LINE_KEYS,
//                      refused by name if posted. markup.py's own sentences say why.
//
// A BROKEN LINE NEVER READS AS $0.00. An unparseable formula, or one that evaluates to Kyle's own
// "error" sentinel, makes its own line and every line below it read "Unpriceable" — which is
// markup-core.js's stated safety property carried up into the screen.
(function () {
  "use strict";

  /** The engine. markup-core.js is loaded ahead of this file; if it is missing the page
   *  must refuse to price rather than pretend, so the stand-in reports every formula as
   *  unreadable instead of quietly returning a number. */
  var M = window.TWMarkup || {
    validate: function () { return { ok: false, error: "the formula engine did not load" }; },
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

  var SUBS = { contingency: "typed per job", remodel_tax: "set by the county table" };

  var EXPLAIN = {
    gp: "Divide-up margin, not a mark-on: the base is divided up by (1 - rate) and the base " +
      "taken back off. Kyle's tab steps the rate down in bands as the job gets bigger.",
    hard_bid: "Money given back to win a competitive bid, so the rate is negative. A job that " +
      "is neither big enough nor local gets nothing taken off.",
    super_pto: "Supervision and paid time off, as a flat rate on everything above.",
    soft_costs: "Overhead the field never sees. On the Gyp tab this line is a whole expression, " +
      "not a rate.",
    bond: "Bond premium on the running total. The workbook ships this line at zero."
  };

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
  // two cells render "no built-in on this page" instead, and the tab's total says Unpriceable
  // until a formula is filed, which is the same refusal Kyle's own `"error"` sentinel makes.

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

  // ── the sample job the preview prices ──────────────────────────────────────
  // A formula's effect has to be visible the moment it is typed, and nothing real may be at
  // stake in that. These figures price NOTHING: they are the mockup's own sample job, and the
  // footnote on the page says so.
  var SAMPLE_SUBTOTAL = 85000;
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
  /** Typed-but-unsaved edits, keyed "<layout>/<line_key>". A formula the admin is still working
   *  on outlives a re-render; nothing here is sent until it is valid. */
  var LOCAL = {};
  var ERRORS = {};                 // same key → the message under the box
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
  function icon(name) {
    var d = name === "info"
        ? '<circle cx="12" cy="12" r="9.5"></circle><path d="M12 8v.01M11 11h1.5v5.5H11"></path>'
      : name === "slash"
        ? '<circle cx="12" cy="12" r="9.5"></circle><path d="M5.5 5.5l13 13"></path>'
      : "";
    return '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" ' +
      'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ' +
      'focusable="false">' + d + "</svg>";
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

  /** One row's whole truth: is it editable, does it apply, what prices it, and where that came
   *  from. `source` is what the caption reads off — "filed" (a row in the table), "builtin" (the
   *  hardcoded constant), "unknown" (no row and no constant on record). */
  function rowState(lineKey) {
    var editable = LINE_KEYS.indexOf(lineKey) >= 0;
    var readOnlyWhy = NOT_EDITABLE[lineKey] || (editable ? "" : "Not editable on this page.");
    var st = {
      line_key: lineKey,
      label: LABELS[lineKey] || labelFor(lineKey),
      sub: SUBS[lineKey] || "",
      explain: NOT_EDITABLE[lineKey] || EXPLAIN[lineKey] || "",
      editable: editable && !NOT_EDITABLE[lineKey],
      readOnlyWhy: readOnlyWhy,
      rule: null, id: null, notes: "",
      applies: true, formula: "", builtin: "", source: "unknown", dirty: false
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
        out[k] = { state: "ok", amount: SAMPLE_CONTINGENCY, rate: null };
        amounts[k] = SAMPLE_CONTINGENCY;
        base += SAMPLE_CONTINGENCY;
        continue;
      }
      if (k === "remodel_tax") {
        var tax = base * SAMPLE_COUNTY_RATE;
        out[k] = { state: "ok", amount: tax, rate: SAMPLE_COUNTY_RATE };
        amounts[k] = tax;
        base += tax;
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
      // The percentage chip is shown only when the formula RETURNED a rate. A divide-up GP hands
      // back dollars, and back-deriving a percentage from them prints 42.858% beside a 30% band —
      // a number nobody typed, on the one line whose arithmetic already misleads people.
      out[k] = { state: "ok", amount: amount, rate: isRate ? value : null };
      amounts[k] = amount;
      base += amount;
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
    if (p.state === "downstream" || p.state === "unknownline") {
      return '<span class="nodash" aria-label="not priced">&mdash;</span>';
    }
    return (p.rate == null ? "" : '<span class="pct">' + esc(pct(p.rate)) + "</span>") +
      '<span class="amt">' + esc(money(p.amount)) + "</span>";
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
    // GATED HERE, not at the two call sites. The ABSENT branch returns before this function's
    // other caller reaches the `if (!ADMIN)` fork, so a gate per call site would have to be
    // remembered twice -- and the first version of this fix handed a non-admin a delete button on
    // Gyp's empty hard-bid row. One function, one rule.
    if (!ADMIN || !r.id) return "";
    return '<button class="ghostlink" type="button" data-drop="' + esc(r.line_key) + '"' +
      ' data-focus="d-' + esc(r.line_key) + '">Stop overriding this line</button>';
  }

  function formulaCellHtml(r, p) {
    var k = r.line_key;

    // ── ABSENT ──────────────────────────────────────────────────────────────
    // No input, no empty box, no zero. A caption that names the tab, and nothing to type into.
    if (r.editable && !r.applies) {
      return '<span class="absent-note">' + icon("slash") +
        " Not used on " + esc(nounFor(LAYOUT)) + "</span>" +
        '<span class="wbnote">' + icon("info") +
        "<span>The cell is empty on this tab, which is not the same as 0%." +
        (r.dirty ? " Unsaved." : "") + "</span></span>" +
        dropBtnHtml(r);
    }

    // ── read-only chain lines ───────────────────────────────────────────────
    if (!r.editable) {
      var text = k === "contingency" ? "Typed on the bid"
        : k === "remodel_tax" ? "Typed % → county table → 6.5% floor"
        : "Not set here";
      return '<span class="ftext locked">' + esc(text) + "</span>";
    }

    // A message the admin earned by typing wins, but a formula that was ALREADY filed and cannot
    // be read has to account for itself too — otherwise the row reads "Unpriceable" and the only
    // way to find out why is to retype it.
    var err = ERRORS[key(k)] || (p && p.state === "invalid" ? p.error : "") || "";
    var shown = r.formula;

    // ── a non-admin reads it ────────────────────────────────────────────────
    if (!ADMIN) {
      var ro = shown || r.builtin;
      return '<span class="ftext' + (shown ? "" : " dim") + '">' +
        esc(ro || "No built-in on this page for " + labelFor(LAYOUT)) + "</span>" +
        (shown ? "" : '<span class="wbnote">' + icon("info") +
          "<span>" + (r.builtin ? "Built in — not overridden yet." : "Nothing prices this line " +
            "until a formula is filed.") + "</span></span>");
    }

    // ── an admin edits it ───────────────────────────────────────────────────
    // The box is EMPTY when nothing is filed, and the placeholder shows the constant the chain is
    // using instead. Prefilling the box with a value that is not stored would be a lie about
    // state, and the first blur would save it as though somebody had chosen it.
    var out = '<input class="finput' + (err ? " err" : "") + '" type="text" spellcheck="false"' +
      ' autocomplete="off" data-formula="' + esc(k) + '" data-focus="f-' + esc(k) + '"' +
      ' aria-label="' + esc(r.label) + ' formula for ' + esc(labelFor(LAYOUT)) + '"' +
      ' value="' + esc(shown) + '"' +
      ' placeholder="' + esc(r.builtin || "no built-in — type a formula") + '" />' +
      '<div class="errmsg" data-err="' + esc(k) + '"' + (err ? "" : " hidden") + ">" +
      esc(err) + "</div>";

    // DIRTY IS CHECKED FIRST. A row switched back on with an empty box is both unsaved AND
    // showing its built-in placeholder, and "Built in — not overridden yet" would be flatly
    // untrue there: what is stored is `applies=false`. The unsaved state is the one that changes
    // what the person should do next, so it is the one that gets said.
    if (r.dirty) {
      out += '<span class="wbnote">' + icon("info") +
        "<span>Not saved yet — " + (shown ? "leave the box to save it."
          : "type a formula, or switch the line back off.") + "</span></span>";
    } else if (!shown && r.builtin) {
      out += '<span class="wbnote">' + icon("info") +
        "<span>Built in — not overridden yet. Typing here overrides it.</span></span>";
    } else if (!shown && !r.builtin) {
      out += '<span class="wbnote">' + icon("info") +
        "<span>No built-in on this page for " + esc(labelFor(LAYOUT)) +
        ". The tab cannot be priced until this is filed.</span></span>";
    }

    out += dropBtnHtml(r);
    return out;
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

  function rowHtml(r, p) {
    var absent = r.editable && !r.applies;
    var explain = r.explain;
    if (p && p.state === "downstream") explain = "Depends on " + p.dependsOn + ", above.";
    if (p && p.state === "nobuiltin") {
      explain = "No formula filed and no built-in on this page for " + labelFor(LAYOUT) + ".";
    }
    return '<div class="mkrow' + (absent ? " absent" : "") + '" data-row="' + esc(r.line_key) +
      '">' +
      '<div class="line">' + esc(r.label) +
      (r.sub ? '<span class="sub">' + esc(r.sub) + "</span>" : "") + "</div>" +
      "<div>" + formulaCellHtml(r, p) + "</div>" +
      "<div>" + appliesCellHtml(r) + "</div>" +
      '<div class="explain' + (p && p.state === "downstream" ? " dim" : "") + '">' +
      esc(explain) + "</div>" +
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
      "<div>Line</div><div>Formula</div><div>Applies</div><div>What it does</div>" +
      '<div style="text-align:right">Preview</div></div>';

    out += '<div class="mkrow"><div class="line">Sub-total costs' +
      '<span class="sub">the base</span></div>' +
      '<div><span class="ftext locked">material + labour + escalation + burden</span></div>' +
      '<div><span class="swro">Always</span></div>' +
      '<div class="explain">The base every line below builds on. Not a formula — it comes off ' +
      'the takeoff and labour tabs.</div>' +
      '<div class="prev"><span class="amt">' + esc(money(SAMPLE_SUBTOTAL)) +
      "</span></div></div>";

    for (var i = 0; i < rows.length; i++) out += rowHtml(rows[i], priced[rows[i].line_key]);

    var total = priced.__total;
    out += '<div class="mkrow grand"><div class="line">Total lump sum</div><div></div>' +
      '<div></div><div class="explain">' +
      (total.state === "ok"
        ? esc("on a " + money(SAMPLE_SUBTOTAL) + " sub-total")
        : esc("can't price this tab — fix " + total.dependsOn)) +
      '</div><div class="prev">' +
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
    // `focus: false` on the way OUT of a box. During `focusout` the browser is mid-transition:
    // document.activeElement is still the control being left, so "restoring" it would yank the
    // caret back out of the cell the person just tabbed into. That is the exact bug this repo
    // keeps re-finding, and it is a one-word argument rather than a comment asking for care.
    var wantFocus = !(opts && opts.focus === false);
    rendering = true;
    try {
      var active = wantFocus ? document.activeElement : null;
      var focusKey = (active && active.getAttribute) ? active.getAttribute("data-focus") : null;
      var selStart = null, selEnd = null;
      if (focusKey) {
        try { selStart = active.selectionStart; selEnd = active.selectionEnd; } catch (e) {}
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
   *  All three toggle with `el.hidden` and every one of them has an attribute rule in the
   *  stylesheet, because a class that sets `display` beats the attribute and this repo has
   *  shipped four of those. */
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
        "estimator. Typing a formula here overrides one; removing it hands the line back.";
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
      "rate, so a formula's effect is visible the moment it's typed — they price nothing real. " +
      "The chain that prices a bid reads these same rows.";
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
      say("Type a formula for " + r.label + ", or switch it off.");
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
        say(json.detail || "That didn't save.");
        render();
        return;
      }
      replaceRule(json.rule);
      delete LOCAL[key(lineKey)];
      delete ERRORS[key(lineKey)];
      render();
    } catch (err) {
      ERRORS[key(lineKey)] = "Couldn't reach the server.";
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
      delete ERRORS[key(lineKey)];
      render();
    } catch (err) {
      say("Couldn't remove that. " + (err && err.message ? err.message : ""));
    }
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

    var sw = t.closest("[data-applies]");
    if (sw) {
      var swKey = sw.getAttribute("data-applies");
      var cur = rowState(swKey);
      var next = !cur.applies;
      LOCAL[key(swKey)] = { applies: next, formula: cur.formula };
      delete ERRORS[key(swKey)];
      if (next && !cur.formula) {
        // Switched ON with nothing to run. Do not post a save the backend must refuse — show the
        // box and say what it needs.
        say("Type a formula for " + cur.label + " and leave the box to save it.");
        render();
        var box = document.querySelector('[data-focus="f-' + swKey + '"]');
        if (box && box.focus) box.focus();
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
   *  Validation happens on the way OUT of the box, not on every keystroke — half a formula is
   *  always invalid, and being told so mid-word teaches somebody to ignore the message. */
  $("mk-chain").addEventListener("input", function (ev) {
    var t = ev.target;
    if (!t || !t.getAttribute) return;
    var k = t.getAttribute("data-formula");
    if (!k) return;
    if (ERRORS[key(k)]) {
      delete ERRORS[key(k)];
      t.classList.remove("err");
      var msg = document.querySelector('[data-err="' + k + '"]');
      if (msg) { msg.textContent = ""; msg.hidden = true; }
    }
  });

  /** `focusout` rather than `blur`, because blur does not bubble and these boxes are replaced by
   *  every render. Guarded against the render that itself moves focus. */
  $("mk-chain").addEventListener("focusout", function (ev) {
    if (rendering) return;
    var t = ev.target;
    if (!t || !t.getAttribute) return;
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
      render({ focus: false });
      return;
    }

    // The backend checks a formula's SHAPE and nothing about its grammar, so it is checked here,
    // while the admin is still looking at it.
    var checked = M.validate(typed);
    if (!checked.ok) {
      LOCAL[key(k)] = { applies: true, formula: typed };
      ERRORS[key(k)] = checked.error;
      say("That formula can't be read, so it wasn't saved.");
      render({ focus: false });
      return;
    }
    LOCAL[key(k)] = { applies: true, formula: typed };
    render({ focus: false });
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
