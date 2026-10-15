// THE BID ENGINE: one markup chain for every tab, driven by a profile. Pure functions. No DOM, no fetch, no clock.
// Externalized (CSP: no inline scripts). Do not add inline scripts.
//
// WHAT THIS IS. Kyle's estimate workbook prices a job the same way on every tab (material, labor, a sub-total,
// gross profit, super and PTO, soft costs, the taxes, a bond, a total) and each tab does it a little
// differently (Epoxy leaves the fees out of what GP takes back off, Leveling leaves the labor escalation out of
// the sub-total, Gyp has seven GP tiers and splits its shipping). Until Phase 8 only the Polish chain was
// written down in JavaScript (js/bid-model.js markupChain, with the Polish constants inline). This file is
// the one function that walks ANY of them: `priceChain(profile, input, rates)`, where the profile is DATA
// (js/bid-profiles.js, part two: rates as Markups formula text, quirks as named flags) and the function
// holds no work type, no rate and no cell address of its own.
//
//   resolveProfile(id)           a profile with everything it extends folded in, frozen
//   forTab(tab)                  the profile that prices a workbook tab, and that tab's truckload and label
//   priceChain(profile, input, rates)   the bid: every line of the chain, one key per cell of the markup column
//   compileRates(profile, rules)        the Markups rules filed for a profile's layout, read into rates
//   ruleNumber(rules, layout, line)     one filed rule as a number, or "unpriceable" with the reason
//   snapshotRates(profile, rules)       the rates a section keeps when it is first used (Phase 10), notes included
//   ratesOf(snapshot)                   a saved snapshot as priceChain's `rates`, or nothing
//   combine(tabs)                the bid of a job priced on several tabs (Combo): each tab's own total, summed
//   rateNumber / defaultNumber / bandsOf   readers for the code that needs a built-in as a number
//
// THE SAFETY PROPERTY, carried up from js/markup-core.js. A rate that cannot be read, cannot be worked out, or
// comes to a dollar figure where a rate is needed makes the line UNPRICEABLE with a reason. It never prices as
// $0. priceChain answers { priceable: false, line, reason } and every figure null; a caller shows the reason.
//
// WHAT A RATE IS HERE. Text in the Markups vocabulary ("2.7%", "MARKUP(BAND(subtotal, 6500,52%, ..., 30%))"),
// read by markup-core.js and snapped to twelve significant figures, which is what turns 2.7/100 =
// 0.027000000000000003 back into the 0.027 Kyle typed. A filed rule and a built-in are the same kind of thing,
// so one reader serves both. A section saved on a bid keeps the TEXT of the rates that priced it (compileRates
// returns it), not the live Markups rules.
//
// LAYOUT IS NEVER ASSUMED. A profile carries its layout, a function that needs one throws without it, and no
// default is "polish". LOOKUPS by a layout, a line key or any key that came from user data use a Map or a
// null-prototype object, never `obj[key] =` on a plain one.
//
// LOAD ORDER. js/excel-math.js, js/bid-profiles.js and js/markup-core.js are loaded before this file (a script
// tag above this one, and `require` does the same under node). Each is checked, with an error that names it.
(function (root, factory) {
  var isNode = typeof module !== "undefined" && module.exports;
  var deps = {
    math: isNode ? require("./excel-math.js") : root.TWExcelMath,
    profiles: isNode ? require("./bid-profiles.js") : root.TWBidProfiles,
    markup: isNode ? require("./markup-core.js") : root.TWMarkup
  };
  if (!deps.math) throw new Error("bid-engine.js needs excel-math.js loaded before it");
  if (!deps.profiles) throw new Error("bid-engine.js needs bid-profiles.js loaded before it");
  if (!deps.markup) throw new Error("bid-engine.js needs markup-core.js loaded before it");
  var api = factory(deps);
  root.TWBidEngine = api;
  if (isNode) module.exports = api;   // node, for tests
})(typeof self !== "undefined" ? self : this, function (deps) {
  "use strict";

  var num = deps.math.num, roundUp = deps.math.roundUp;
  var P = deps.profiles, K = deps.markup;
  var has = Object.prototype.hasOwnProperty;

  // ── errors ──────────────────────────────────────────────────────────────────
  /** A call that cannot be answered: no profile, no layout, an unknown id. A programming error, so it throws. */
  function BidEngineError(message) {
    this.name = "BidEngineError";
    this.message = message;
    if (Error.captureStackTrace) Error.captureStackTrace(this, BidEngineError);
  }
  BidEngineError.prototype = Object.create(Error.prototype);
  BidEngineError.prototype.constructor = BidEngineError;

  /** A rate that will not price. Caught inside priceChain and handed back as an unpriceable result. */
  function UnpriceableError(line, reason) {
    this.name = "BidUnpriceable";
    this.line = line;
    this.reason = reason;
    this.message = line + ": " + reason;
    if (Error.captureStackTrace) Error.captureStackTrace(this, UnpriceableError);
  }
  UnpriceableError.prototype = Object.create(Error.prototype);
  UnpriceableError.prototype.constructor = UnpriceableError;

  // ── reading a rate ──────────────────────────────────────────────────────────
  var TREES = new Map();
  /** The parse of a formula, kept: the chain reads the same few strings on every keystroke. */
  function tree(text) {
    var hit = TREES.get(text);
    if (hit) return hit;
    var parsed = K.parse(text);
    if (TREES.size > 500) TREES.clear();
    TREES.set(text, parsed);
    return parsed;
  }

  /** Twelve significant figures: the guard that makes 2.7% read as 0.027 and not 0.027000000000000003. */
  function snap(n) { return parseFloat(n.toPrecision(12)); }

  // What each rate line is, for reading it. "gp" may be wrapped in MARKUP(...) (that is how the Markups page
  // files it); "signed" may be negative (the hard bid give-back); "dollars" is a figure, never a fraction.
  var KINDS = new Map([
    ["gp", "gp"], ["hard_bid", "signed"],
    ["labor_rate", "dollars"], ["travel_lodging", "dollars"], ["travel_per_diem", "dollars"],
    ["fees_textura", "dollars"]
  ]);
  var LABELS = new Map([
    ["ship_pct", "Shipping"], ["esc_pct", "Labor escalation"], ["burden_pct", "Labor burden"],
    ["gp", "GP"], ["hard_bid", "Hard bid"], ["super_pto", "Superintendent and PTO"],
    ["soft_costs", "Soft costs"], ["bond", "Bond"], ["sales_tax", "Sales tax"],
    ["material_esc_pct", "Material escalation"], ["ship_gyp_pct", "Gypsum shipping"],
    ["ship_other_pct", "Other shipping"], ["remodel_sheet", "Remodel tax"], ["remodel_state", "Remodel tax"],
    ["labor_rate", "Labor rate"], ["travel_lodging", "Travel lodging"], ["travel_per_diem", "Travel food"],
    ["fees_textura", "Fees"]
  ]);
  function kindOf(key) { return KINDS.has(key) ? KINDS.get(key) : "rate"; }
  function labelOf(key) { return LABELS.has(key) ? LABELS.get(key) : key; }

  /** One formula read as a number, or an UnpriceableError that says why in plain words.
   *
   *  A "rate" or "gp" comes to at least 0 and under 1: a fraction of a base. Anything else is a dollar figure or
   *  a mistake, and pricing it as a rate would charge the job several times its own size. */
  function readRate(text, context, kind, label) {
    if (typeof text !== "string" || text.trim() === "") throw new UnpriceableError(label, "there is no rate for this line");
    var source = kind === "dollars" ? text.replace(/^\s*\$/, "") : text;
    var node;
    try { node = tree(source); } catch (e) {
      throw new UnpriceableError(label, "the formula cannot be read (" + (e && e.message ? e.message : e) + ")");
    }
    if (kind === "gp" && node.type === "Call" && String(node.name).toUpperCase() === "MARKUP" && node.args.length === 1) {
      node = node.args[0];
    }
    if (kind === "dollars" && node.type === "Percent") {
      throw new UnpriceableError(label, "this line is a dollar figure and the formula is a percentage");
    }
    var value;
    try { value = K.evaluate(node, context); } catch (e) {
      throw new UnpriceableError(label, "the formula cannot be worked out (" + (e && e.message ? e.message : e) + ")");
    }
    if (typeof value !== "number" || !isFinite(value)) throw new UnpriceableError(label, "the formula does not come to a number");
    value = snap(value);
    if (kind === "dollars") {
      if (value < 0) throw new UnpriceableError(label, "a dollar figure cannot be negative");
      return value;
    }
    if (kind === "signed") {
      if (!(value > -1 && value < 1)) throw new UnpriceableError(label, "comes to " + value + ", which is not a rate");
      return value;
    }
    if (value < 0 || value >= 1) {
      throw new UnpriceableError(label, "comes to " + value + ", which is a dollar figure or out of range, not a rate");
    }
    return value;
  }

  // ── profiles ────────────────────────────────────────────────────────────────
  var RESOLVED = new Map();

  function freeze(o) {
    if (o && typeof o === "object" && !Object.isFrozen(o)) {
      Object.freeze(o);
      Object.keys(o).forEach(function (k) { freeze(o[k]); });
    }
    return o;
  }

  /** The names a rate formula may use and what each is. Always there: `material`, `subtotal` and `sub_total`,
   *  `local` and `hard_bid` ("Yes" or "No"), `base`. A profile's own `names` add sheet cell names. */
  var CONTEXT_NAMES = ["material", "subtotal", "sub_total", "local", "hard_bid", "base"];

  /** A profile with everything it extends folded in: { id, rev, stamp, layout, label, chain, quirks, rates,
   *  names }, frozen. A closed set of quirks (js/bid-profiles.js `quirks`): a profile that carries a name outside
   *  it, or lacks one, is refused here, and so is an `extends` that loops. */
  function resolveProfile(id) {
    if (typeof id !== "string" || id === "") throw new BidEngineError("resolveProfile needs the id of a profile");
    if (RESOLVED.has(id)) return RESOLVED.get(id);
    if (!has.call(P.profiles, id)) throw new BidEngineError("there is no profile called " + id);
    var chain = [];
    var seen = new Set();
    for (var at = id; at; at = P.profiles[at].extends) {
      if (seen.has(at)) throw new BidEngineError("profile " + id + " extends itself through " + at);
      if (!has.call(P.profiles, at)) throw new BidEngineError("profile " + id + " extends " + at + ", which does not exist");
      seen.add(at);
      chain.unshift(at);
    }
    var quirks = new Map(), rates = new Map(), names = new Map();
    Object.keys(P.defaults).forEach(function (k) { rates.set(k, P.defaults[k]); });
    chain.forEach(function (link) {
      var p = P.profiles[link];
      Object.keys(p.quirks || {}).forEach(function (k) {
        if (P.quirks.indexOf(k) < 0) throw new BidEngineError("profile " + link + " has a quirk called " + k + ", which is not one the engine knows");
        quirks.set(k, p.quirks[k]);
      });
      Object.keys(p.rates || {}).forEach(function (k) {
        if (p.rates[k] === null) rates.delete(k); else rates.set(k, p.rates[k]);
      });
      Object.keys(p.names || {}).forEach(function (k) { names.set(k, p.names[k]); });
    });
    P.quirks.forEach(function (k) {
      if (!quirks.has(k)) throw new BidEngineError("profile " + id + " does not say what " + k + " is");
    });
    var own = P.profiles[id];
    var resolved = freeze({
      id: id, rev: own.rev, stamp: id + "@" + own.rev, layout: own.layout, label: own.label,
      chain: chain,
      quirks: Object.fromEntries(quirks), rates: Object.fromEntries(rates), names: Object.fromEntries(names)
    });
    RESOLVED.set(id, resolved);
    return resolved;
  }

  /** The profile that prices a workbook tab, and what is particular to the tab: { tab, profile, truckload, label }.
   *  `truckload` and `label` are the Gyp tabs' (the rolls of sound mat in a truckload, and what the proposal calls
   *  the system); null on a tab that has none. */
  function forTab(tab) {
    if (typeof tab !== "string" || !has.call(P.tabs, tab)) throw new BidEngineError("no profile prices a tab called " + String(tab));
    var entry = P.tabs[tab];
    return { tab: tab, profile: resolveProfile(entry.profile), truckload: has.call(entry, "truckload") ? entry.truckload : null,
             label: has.call(entry, "label") ? entry.label : null };
  }

  function need(profile, who) {
    if (typeof profile === "string") return resolveProfile(profile);
    if (profile && typeof profile === "object" && typeof profile.layout === "string" && profile.layout &&
        profile.quirks && profile.rates) return profile;
    throw new BidEngineError(who + " needs a profile (an id or a resolved profile that names its layout)");
  }

  // ── the context a rate formula is read in ───────────────────────────────────
  function contextFor(profile, state) {
    var base = {
      material: state.material, subtotal: state.subTotal, sub_total: state.subTotal,
      local: state.local ? "Yes" : "No", hard_bid: state.hardBid ? "Yes" : "No", base: state.base
    };
    var named = Object.keys(profile.names).map(function (n) {
      return [n, has.call(base, profile.names[n]) ? base[profile.names[n]] : 0];
    });
    return Object.assign({}, base, Object.fromEntries(named));
  }

  /** What a rule is checked against when no job is in hand: zeros and "Yes". Every name any profile binds is
   *  present, so a formula written with the sheet's own cell names (Gyp's soft costs) still reads. */
  function probeContext() {
    var base = { material: 0, subtotal: 0, sub_total: 0, local: "Yes", hard_bid: "No", base: 0 };
    var named = [];
    Object.keys(P.profiles).forEach(function (id) {
      var names = P.profiles[id].names || {};
      Object.keys(names).forEach(function (n) { named.push([n, has.call(base, names[n]) ? base[names[n]] : 0]); });
    });
    return Object.assign({}, base, Object.fromEntries(named));
  }

  // ── the Markups rules, as numbers ───────────────────────────────────────────
  /** The filed rule for (layout, line), as a number or a reason.
   *
   *    null                            nothing is filed, or the rule is switched off, or it has no formula. The
   *                                    built-in applies: a line switched off is still charged, because "not used
   *                                    here" is not a zero.
   *    { ok: true, value, formula }    the rule, read
   *    { ok: false, reason, formula }  the rule is there and will not price: UNPRICEABLE, never $0
   *
   *  `layout` is required. A line whose home is Global (bond, travel, labor rate, fees) is read from the Global
   *  rules whatever layout asks. `context` is what a formula names; with none, zeros and "Yes". */
  function ruleNumber(rules, layout, lineKey, context) {
    if (typeof layout !== "string" || layout === "") throw new BidEngineError("ruleNumber needs the layout the rule is for");
    if (!has.call(P.lines, lineKey)) throw new BidEngineError("ruleNumber: " + String(lineKey) + " is not a line the engine reads");
    if (!(rules instanceof Array)) return null;
    var home = P.lines[lineKey].home === "global" ? "global" : layout;
    var rule = null;
    for (var i = 0; i < rules.length; i++) {
      var r = rules[i];
      if (r && r.layout === home && r.line_key === lineKey) { rule = r; break; }
    }
    if (!rule || rule.applies === false) return null;
    var text = rule.formula;
    if (text === null || text === undefined || String(text).trim() === "") return null;
    text = String(text);
    try {
      return { ok: true, value: readRate(text, context || probeContext(), P.lines[lineKey].kind, labelOf(lineKey)), formula: text };
    } catch (e) {
      if (e instanceof UnpriceableError) return { ok: false, reason: e.reason, formula: text };
      throw e;
    }
  }

  /** The Markups rules for `profile`'s layout (and Global), read into what priceChain takes as `rates`:
   *    { profile: "polish@1", rates: { line: formula text }, filed: [lines], unpriceable: { line: reason } }
   *  Only filed lines are in `rates`; every other line prices at the profile's built-in. The text is what
   *  gets saved with a section, so a bid keeps the rates that priced it. */
  function compileRates(profile, rules) {
    profile = need(profile, "compileRates");
    var context = probeContext();
    var out = { profile: profile.stamp, rates: {}, filed: [], unpriceable: {} };
    Object.keys(P.lines).forEach(function (line) {
      var got = ruleNumber(rules, profile.layout, line, context);
      if (!got) return;
      if (!got.ok) {
        out.unpriceable = Object.assign({}, out.unpriceable, Object.fromEntries([[line, got.reason]]));
        return;
      }
      out.rates = Object.assign({}, out.rates, Object.fromEntries([[line, got.formula]]));
      out.filed.push(line);
    });
    return out;
  }

  /** A built-in or filed formula as a number. With no `context` there is no job in hand (zeros and "Yes"), which
   *  is what the code that needs a constant wants; a test that holds a rate to the workbook's own formula passes
   *  the values the formula names. */
  function rateNumber(text, kind, context) {
    return readRate(text, Object.assign({}, probeContext(), context || {}), kind || "rate", "rate");
  }

  /** One of the global defaults (js/bid-profiles.js `defaults`) as a number. */
  function defaultNumber(key) {
    if (!has.call(P.defaults, key)) throw new BidEngineError("there is no global default called " + String(key));
    return readRate(P.defaults[key], probeContext(), kindOf(key), labelOf(key));
  }

  /** A BAND ladder as [[ceiling, rate], ..., [null, default]], the shape bid-model's GP_BANDS has always had. */
  function bandsOf(text) {
    var node = tree(text);
    if (node.type === "Call" && String(node.name).toUpperCase() === "MARKUP" && node.args.length === 1) node = node.args[0];
    if (!(node.type === "Call" && String(node.name).toUpperCase() === "BAND")) {
      throw new BidEngineError("bandsOf wants a BAND ladder and was given " + text);
    }
    var values = node.args.slice(1).map(function (a) { return snap(K.evaluate(a, {})); });
    var out = [];
    for (var i = 0; i + 1 < values.length; i += 2) out.push([values[i], values[i + 1]]);
    out.push([null, values[values.length - 1]]);
    return out;
  }

  // ── the rates a section keeps (Phase 10) ─────────────────────────────────────
  /** The shape of the snapshot below. A saved snapshot of another version is not read. */
  var SNAPSHOT_VERSION = 1;

  /** Lines a filed Markups rule is NOT taken for, because v2 does not charge them yet. Bond is 0 and unwired
   *  (a decision for Kyle, program plan "Later, for Kyle"): the production Markups table holds one rule, polish
   *  bond 1%, and a new section must not start charging a bond because somebody filed that. */
  var UNWIRED = ["bond"];

  /** WHAT A SECTION KEEPS WHEN IT IS FIRST USED: the rates it prices with, so a saved bid never reprices because
   *  somebody edits the Markups page afterwards. Returns
   *
   *    { version, profile: "epoxy@1", rates: { line: formula text }, fees_default, notes: [plain words] }
   *
   *  `rates` holds ONLY the lines a rule is filed for; every other line prices at the profile's built-in, which
   *  is pinned by the profile's rev. Filed rules are honoured (plan default), each as the text the Markups page
   *  holds, which priceChain reads like a built-in.
   *
   *  A FILED RULE THAT WILL NOT PRICE IS LEFT OUT AND SAID SO, never $0 (the safety property at the top of this
   *  file): a blank formula, one that cannot be read or worked out, or one that comes to a dollar figure where a
   *  rate belongs. The built-in stands and `notes` says which line and why, so the page can show it. A bond rule
   *  is left out for the reason UNWIRED gives. The Fees + Textura rule is the fees DEFAULT (a dollar figure the
   *  job's fees line starts at), not a rate: it is kept as `fees_default`, a number or null.
   *
   *  `rules` is GET /api/markup/rules' list, or nothing (no rules: an empty snapshot, which prices at the
   *  built-ins). Nothing here reads a clock or the network. */
  function snapshotRates(profileArg, rules) {
    var profile = need(profileArg, "snapshotRates");
    var list = (rules instanceof Array) ? rules : [];
    var compiled = compileRates(profile, list);
    var notes = [];
    var kept = [];
    compiled.filed.forEach(function (line) {
      if (UNWIRED.indexOf(line) >= 0) {
        notes.push(labelOf(line) + ": a rule is filed on the Markups page, but v2 does not charge it yet, so it was not used.");
      } else if (line !== "fees_textura") {
        kept.push([line, compiled.rates[line]]);
      }
    });
    Object.keys(compiled.unpriceable).forEach(function (line) {
      if (line === "fees_textura") return;
      notes.push(labelOf(line) + ": the rule filed on the Markups page cannot be used (" + compiled.unpriceable[line] +
        "), so the built-in rate is charged.");
    });
    // A blank rule reads as "nothing filed" to ruleNumber, which is right for pricing and silent for a person.
    Object.keys(P.lines).forEach(function (line) {
      var home = P.lines[line].home === "global" ? "global" : profile.layout;
      var blank = list.some(function (r) {
        return r && r.layout === home && r.line_key === line && r.applies !== false &&
          (r.formula === null || r.formula === undefined || String(r.formula).trim() === "");
      });
      if (blank && line !== "fees_textura") {
        notes.push(labelOf(line) + ": the rule filed on the Markups page is blank, so the built-in rate is charged.");
      }
    });
    var fees = ruleNumber(list, profile.layout, "fees_textura");
    if (fees && !fees.ok) {
      notes.push(labelOf("fees_textura") + ": the rule filed on the Markups page cannot be used (" + fees.reason +
        "), so the fees line starts at nothing.");
    }
    return {
      version: SNAPSHOT_VERSION, profile: profile.stamp, rates: Object.fromEntries(kept),
      fees_default: (fees && fees.ok) ? fees.value : null, notes: notes
    };
  }

  /** What priceChain takes as `rates`, out of a saved snapshot: `{ rates: { line: formula } }`, or undefined for
   *  a section that has none (it prices at the profile's built-ins, NEVER at the live Markups rules) or one that
   *  is not a snapshot of this version. */
  function ratesOf(snapshot) {
    if (!snapshot || typeof snapshot !== "object" || snapshot.version !== SNAPSHOT_VERSION) return undefined;
    if (!snapshot.rates || typeof snapshot.rates !== "object" || snapshot.rates instanceof Array) return undefined;
    return { rates: snapshot.rates };
  }
  // ── THE CHAIN ───────────────────────────────────────────────────────────────
  /** NIGHTS OF LODGING, the sheet's way: the labor dollars that are not travel labor, over the labor rate, over the
   *  hours of a day (B58 on Polish: `((D45-D44)/C37)/8`; `lodgingDivisor` is the 8, or the 10 on Gyp). Per diem counts
   *  the same figure (B59 is `=B58`). `labor` is the rounded-up labor total, `travelLabor` the travel row's dollars. A
   *  labor rate that is not above zero counts no nights: a divide by nothing is not a number of nights. */
  function nightsOf(quirks, labor, travelLabor, laborRate) {
    var rate = num(laborRate);
    if (!(rate > 0)) return 0;
    return ((num(labor) - num(travelLabor)) / rate) / quirks.lodgingDivisor;
  }

  /** The same count for a profile and a job, for a caller that wants the nights without pricing the chain (the
   *  estimate page's hint under Lodging and Per Diem, and the oracle's lodging cases). */
  function lodgingNights(profileArg, labor, travelLabor, laborRate) {
    return nightsOf(need(profileArg, "lodgingNights").quirks, labor, travelLabor, laborRate);
  }

  function isBlank(v) { return v === null || v === undefined || v === ""; }

  /** THE ESTIMATOR'S OVERRIDES for one tab, checked (Hanz, 2026-10-16: "all the edge cases"). Kyle types over his own
   *  rules on a real share of bids (2026-08-16 to 10-16: a discount on 21 of 41, soft or super % on 4, GP on 1,
   *  shipping on 1), so each of these replaces the rule's figure when it is a number, and is absent otherwise.
   *
   *  A RATE must be a finite fraction from 0 up to, but not including, 1: GP divides by (1 - gp), so 1 or more is no
   *  price at all, and a negative markup or shipping is not something the sheet's cells are ever typed with. A
   *  DISCOUNT is taken as its size, whichever way it is signed, because Kyle types it as -0.03 and an estimator types
   *  "3": both mean 3% off, and the line is always money given back. Its percentage is below 1 for the same reason a
   *  rate is (100% off is a free floor, not a bid). The dollar figure, when there is one, wins over the percentage:
   *  the sheet's D-cell, typed, replaces its own formula. Anything that is not a usable number throws, so a bad box is
   *  named rather than priced as if it were blank. */
  function adjustOf(raw) {
    if (raw === null || raw === undefined) return {};
    if (typeof raw !== "object") throw new BidEngineError("adjust must be an object of the estimator's overrides");
    // Each key read and written by its own name: a key that came from data never becomes a property (the rule
    // test_bid_engine.py holds this file to).
    function fraction(name, v) {
      if (isBlank(v)) return undefined;
      var n = Number(v);
      if (!isFinite(n)) throw new BidEngineError("the " + name + " override is not a number: " + JSON.stringify(v));
      if (name === "discount_pct") n = Math.abs(n);
      if (n < 0 || n >= 1) throw new BidEngineError("the " + name + " override must be from 0 to under 100%, not " + n);
      return snap(n);
    }
    var out = {
      ship_pct: fraction("ship_pct", raw.ship_pct), gp_pct: fraction("gp_pct", raw.gp_pct),
      super_pct: fraction("super_pct", raw.super_pct), soft_pct: fraction("soft_pct", raw.soft_pct),
      discount_pct: fraction("discount_pct", raw.discount_pct), discount_amt: undefined
    };
    if (!isBlank(raw.discount_amt)) {
      var amt = Number(raw.discount_amt);
      if (!isFinite(amt)) throw new BidEngineError("the discount_amt override is not a number: " + JSON.stringify(raw.discount_amt));
      out.discount_amt = snap(Math.abs(amt));
    }
    // An override that was not given is ABSENT, not undefined, so `has1` below can tell the two apart.
    return JSON.parse(JSON.stringify(out));
  }

  function unpriceable(profile, e) {
    return { priceable: false, profile: profile.stamp, line: e.line, reason: e.reason, total: null };
  }

  /** The bid for one tab. `profile` is a profile id or a resolved profile; `input` is the job:
   *
   *    material, labor      raw sums (the sheet rounds them up here)
   *    overage              the Discount / Overage dollars (a profile with `hasOverage`)
   *    tooling, travel      dollars; with no `travel` and `travelFromLodging`, travel is lodging plus per diem
   *    travelLabor          the travel-labor part of `labor`, which lodging leaves out
   *    fees, contingency    dollars typed on the job
   *    sf                   the area, for the per-SF figure
   *    conditions           { local (yes unless said), taxable, prevailing_wage, remodel_tax, hard_bid }
   *    remodel_rate         the county's remodel rate; null or blank means the profile's default
   *    bond_pct             a bond rate typed for the job (a profile with `bondInput`)
   *    laborRate, lodgingRate, perDiemRate   override the defaults for the lodging nights
   *    gyp, extras, sand, soundMat, soundMatRolls, truckload   a profile with shippingRule "gyp-split"
   *    patch                the patch line's dollars (Polish!D17), taken into the material on a `polishPatch` profile
   *    adjust               what the estimator typed OVER the sheet's rules for this tab (see adjustOf), all optional:
   *                           ship_pct, gp_pct, super_pct, soft_pct   fractions that replace the rule's rate
   *                           discount_pct                           a fraction off (0.03 is 3% off), Kyle's B74/B68
   *                           discount_amt                           dollars off, Kyle's D74/D68 typed; wins over the %
   *
   *  `rates` is what compileRates returned for this profile, or nothing for the profile's own built-ins. The
   *  answer has one key per line of the chain (snake_case, the keys bid-model's markupChain has always
   *  returned, plus the ones only some tabs have) and `priceable: true`, or `priceable: false` with the
   *  `line` and the `reason`. */
  function priceChain(profileArg, input, rates) {
    var profile = need(profileArg, "priceChain");
    input = input || {};
    var q = profile.quirks;
    if (rates && rates.unpriceable) {
      var bad = Object.keys(rates.unpriceable);
      if (bad.length) return unpriceable(profile, new UnpriceableError(labelOf(bad[0]), rates.unpriceable[bad[0]]));
    }
    var lines = Object.assign({}, profile.rates, (rates && rates.rates) || {});
    var cond = input.conditions || {};
    var local = (cond.local === undefined || cond.local === null) ? true : !!cond.local;
    var hardBidOn = !!q.hasHardBid && !!cond.hard_bid;
    var adj = adjustOf(input.adjust);
    var has1 = function (k) { return Object.prototype.hasOwnProperty.call(adj, k); };
    var sf = num(input.sf);
    var state = { material: 0, subTotal: 0, local: local, hardBid: hardBidOn, base: 0 };

    function rate(key, kind) {
      if (typeof lines[key] !== "string") throw new BidEngineError("profile " + profile.id + " has no rate called " + key);
      return readRate(lines[key], contextFor(profile, state), kind || kindOf(key), labelOf(key));
    }

    try {
      // ── materials ──
      var material, shipping, overage = 0, material_escalation = 0, ship_pct = null, material_total;
      if (q.shippingRule === "gyp-split") {
        var gyp = num(input.gyp), extras = num(input.extras), sand = num(input.sand), soundMat = num(input.soundMat);
        var rolls = num(input.soundMatRolls), truckload = num(input.truckload);
        if (!(truckload > 0)) throw new BidEngineError("priceChain: a gyp-split profile needs `truckload`, the rolls in a truckload of this tab");
        material = roundUp(gyp + extras + sand + soundMat);
        material_escalation = roundUp((gyp + extras + soundMat) * rate("material_esc_pct"));
        // The sound mat ships at the 10% rate only while the order is short of a truckload (odd rule 6).
        shipping = roundUp(gyp * rate("ship_gyp_pct")) +
          roundUp((extras + (rolls < truckload ? soundMat : 0)) * rate("ship_other_pct"));
        material_total = material + material_escalation + shipping;
      } else {
        // THE PATCH LINE (Polish!D17) is inside D31's round-up, on a profile that carries it (`polishPatch`). Every
        // other profile, and every caller that passes no `patch`, buys exactly the material it always did.
        // Only a POLISH-layout profile takes it: every profile inherits the quirk from the base Polish tab, and an Epoxy,
        // Seal or Gyp section prices its own patch in its takeoff module, so a stray `patch` there would count twice.
        material = roundUp(num(input.material) + (q.polishPatch && profile.layout === "polish" ? num(input.patch) : 0));
        state.material = material;
        ship_pct = has1("ship_pct") ? adj.ship_pct : rate("ship_pct");
        shipping = roundUp(material * ship_pct);
        overage = q.hasOverage ? roundUp(input.overage) : 0;
        material_total = material + overage + shipping;
      }

      // ── labor ──
      var labor = roundUp(input.labor);
      var esc_pct = (q.escalationAlwaysOn || cond.prevailing_wage) ? rate("esc_pct") : 0;
      var escalation = roundUp(labor * esc_pct);
      var burden_pct = rate("burden_pct");
      var burden = roundUp((labor + escalation) * burden_pct);
      var labor_total = labor + escalation + burden;

      // ── lodging and per diem: nights worked out of the labor dollars (odd rule 2 lives in the divisor) ──
      var lodging_qty = 0, lodging = 0, per_diem = 0;
      if (!local) {
        var laborRate = num(input.laborRate) > 0 ? num(input.laborRate) : rate("labor_rate");
        var lodgingRate = num(input.lodgingRate) > 0 ? num(input.lodgingRate) : rate("travel_lodging");
        var perDiemRate = num(input.perDiemRate) > 0 ? num(input.perDiemRate) : rate("travel_per_diem");
        lodging_qty = nightsOf(q, labor, input.travelLabor, laborRate);
        lodging = roundUp(lodging_qty * lodgingRate);
        per_diem = roundUp(lodging_qty * perDiemRate);
      }
      var per_diem_qty = lodging_qty;

      var travel = roundUp(isBlank(input.travel) && q.travelFromLodging ? lodging + per_diem : input.travel);
      var tooling = q.toolingInSubTotal ? num(input.tooling) : 0;

      // ── the sub-total ──
      var sub = material_total + labor;
      if (q.escalationInSubtotal) sub += escalation;       // odd rule 3: Leveling does not
      sub += burden;
      if (q.toolingInSubTotal) sub += tooling;
      sub += travel;
      var sub_total = roundUp(sub);
      state.subTotal = sub_total;

      // ── the taxes' rates, and the fees line ──
      var sales_tax_pct = cond.taxable ? rate("sales_tax") : 0;
      var sales_tax = roundUp(material_total * sales_tax_pct);          // materials only
      var fees = roundUp(num(input.fees));

      // ── gross profit: a margin, divided up and the cost taken back off ──
      var gp_pct = has1("gp_pct") ? adj.gp_pct : rate("gp");
      var gp = roundUp((sub_total + sales_tax + fees) / (1 - gp_pct))
             - roundUp(sub_total + sales_tax + (q.gpSubtractionIncludesFees ? fees : 0));   // odd rule 4: Epoxy leaves fees out
      // THE DISCOUNT LINE (Kyle's "Hard Bid Discount", Epoxy B74/D74, Polish B68/D68): `=ROUNDUP(SUM(sub,gp)*pct,0)`
      // with a negative pct, ROUNDUP going away from zero. The estimator's typed dollars or percentage replace the
      // profile's own hard-bid rule, on any tab, whether or not the job is a hard bid: it is how Kyle lands a price.
      var hard_bid_pct = 0, hard_bid = 0;
      if (has1("discount_amt")) {
        hard_bid = adj.discount_amt ? -adj.discount_amt : 0;   // never -0, which prints as "-$0"
        hard_bid_pct = null;
      } else if (has1("discount_pct")) {
        hard_bid_pct = -adj.discount_pct;
        hard_bid = adj.discount_pct === 0 ? 0 : roundUp((sub_total + gp) * hard_bid_pct);
      } else if (hardBidOn) {
        hard_bid_pct = rate("hard_bid");
        hard_bid = roundUp((sub_total + gp) * hard_bid_pct);
      }
      var contingency = num(input.contingency);

      var super_pct = has1("super_pct") ? adj.super_pct : rate("super_pto");
      var super_pto = roundUp((sub_total + gp + hard_bid + contingency + sales_tax + fees) * super_pct);
      var soft_pct = has1("soft_pct") ? adj.soft_pct : rate("soft_costs");
      var soft_costs = roundUp((sub_total + gp + hard_bid + super_pto + contingency + sales_tax + fees) * soft_pct);

      // ── the remodel tax: the labor side and the markups, never the materials ──
      var remodel_pct = 0;
      if (cond.remodel_tax) {
        var given = input.remodel_rate;
        remodel_pct = isBlank(given) ? rate(q.remodelRateDefault === "state" ? "remodel_state" : "remodel_sheet") : num(given);
      }
      var remodelBase = labor + escalation + burden;
      if (q.remodelBase === "sheet") remodelBase += tooling + travel;
      remodelBase += gp;
      // The discount is labor-side money given back, so the remodel tax is on what is left (Epoxy D81 sums D73:D77,
      // Polish D75 sums D67:D71, both with the discount cell inside). A profile with no hard-bid rule only ever has
      // one here when the estimator typed it, so every bid priced before overrides existed is unchanged.
      if (q.hasHardBid || hard_bid !== 0) remodelBase += hard_bid;
      remodelBase += super_pto + soft_costs + contingency + fees;
      var remodel_tax = roundUp(remodelBase * remodel_pct);
      var taxes = sales_tax + remodel_tax;

      // ── bond and fees. The base counts both taxes twice, once in each and once in `taxes` (odd rule 1). ──
      var typedBond = q.bondInput && !isBlank(input.bond_pct);
      var bond_pct = typedBond ? num(input.bond_pct) : rate("bond");
      var bond = roundUp((sub_total + gp + hard_bid + super_pto + soft_costs + contingency
                          + sales_tax + remodel_tax + taxes + fees) * bond_pct);
      var fees_and_bond = roundUp(fees + bond);

      var total = sub_total + gp + hard_bid + super_pto + soft_costs + contingency + taxes + fees_and_bond;

      return {
        priceable: true, profile: profile.stamp,
        material: material, overage: overage, material_escalation: material_escalation,
        ship_pct: ship_pct, shipping: shipping, material_total: material_total,
        labor: labor, esc_pct: esc_pct, escalation: escalation, burden_pct: burden_pct, burden: burden, labor_total: labor_total,
        lodging_qty: lodging_qty, lodging: lodging, per_diem_qty: per_diem_qty, per_diem: per_diem,
        travel: travel, tooling: tooling,
        sub_total: sub_total,
        gp_pct: gp_pct, gp: gp,
        hard_bid_pct: hard_bid_pct, hard_bid: hard_bid,
        super_pct: super_pct, super_pto: super_pto, soft_pct: soft_pct, soft_costs: soft_costs, contingency: contingency,
        sales_tax_pct: sales_tax_pct, sales_tax: sales_tax,
        remodel_pct: remodel_pct, remodel_tax: remodel_tax, taxes: taxes,
        fees: fees, bond: bond, bond_pct: bond_pct, fees_and_bond: fees_and_bond,
        total: total,
        sf: sf,
        // Null, not 0, without an area: 0 would read as "free" rather than "not known yet".
        per_sf: sf > 0 ? total / sf : null
      };
    } catch (e) {
      if (e instanceof UnpriceableError) return unpriceable(profile, e);
      throw e;
    }
  }

  // ── a job on several tabs ───────────────────────────────────────────────────
  var SUMMED = ["material_total", "labor_total", "travel", "tooling", "sub_total", "gp", "hard_bid", "super_pto",
    "soft_costs", "contingency", "sales_tax", "remodel_tax", "taxes", "fees", "bond", "fees_and_bond", "total"];

  /** The bid of a job priced on several tabs (Combo is Epoxy plus Polish). `tabs` is a list of
   *  { layout, result } where result is priceChain's answer for that tab. Each tab has already had its OWN
   *  gross profit taken on its OWN sub-total, and what is summed is those answers. Pooling the sub-totals and
   *  pricing the pool once is a different bid: GP steps down with job size, so a pooled job lands on a lower
   *  rung than either part, and the sheet never does that. Every entry must say its layout. */
  function combine(tabs) {
    if (!(tabs instanceof Array) || tabs.length === 0) throw new BidEngineError("combine needs the priced tabs, one entry for each");
    tabs.forEach(function (t, i) {
      if (!t || typeof t.layout !== "string" || t.layout === "") throw new BidEngineError("combine: entry " + i + " does not say which layout it is");
      if (!t.result || typeof t.result !== "object") throw new BidEngineError("combine: entry " + i + " (" + t.layout + ") has no result");
    });
    var broken = tabs.filter(function (t) { return t.result.priceable === false; });
    if (broken.length) {
      return {
        priceable: false, total: null,
        reasons: broken.map(function (t) { return t.layout + ": " + t.result.line + ": " + t.result.reason; })
      };
    }
    var sums = {};
    SUMMED.forEach(function (key) {
      sums = Object.assign({}, sums, Object.fromEntries([[key, tabs.reduce(function (t, x) { return t + num(x.result[key]); }, 0)]]));
    });
    return {
      priceable: true, total: sums.total, sums: sums,
      parts: tabs.map(function (t) { return { layout: t.layout, total: t.result.total }; })
    };
  }

  return {
    BidEngineError: BidEngineError, UnpriceableError: UnpriceableError,
    resolveProfile: resolveProfile, forTab: forTab,
    priceChain: priceChain, combine: combine, lodgingNights: lodgingNights, adjustOf: adjustOf,
    compileRates: compileRates, ruleNumber: ruleNumber,
    snapshotRates: snapshotRates, ratesOf: ratesOf, SNAPSHOT_VERSION: SNAPSHOT_VERSION, UNWIRED: UNWIRED,
    rateNumber: rateNumber, defaultNumber: defaultNumber, bandsOf: bandsOf,
    CONTEXT_NAMES: CONTEXT_NAMES
  };
});
