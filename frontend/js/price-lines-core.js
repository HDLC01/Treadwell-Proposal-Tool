// THE PRICE RULE, the editor's half — pure functions, no DOM, no fetch. Externalized (CSP: no
// inline scripts). Its twin is backend/price_rules.py; test_price_rules_parity.py runs BOTH over
// the same matrix and demands the same answer, so a change here without the same change there
// fails the suite.
//
// Hanz, 2026-09-25: "Remodel Tax should be triggered by remodel tax in the estimate form. Taxable
// is where base bid and other options are taxable or not." And: "if one of the taxes is set to
// yes then broken out should be the default option in the proposal tool."
//
// So the ESTIMATE SHEET decides whether there is tax, per priced tab (Taxable? for material sales
// tax, Remodel Tax? for remodel tax), and the proposal's TAX control decides only the layout:
// "One line" or "Broken out". Broken out prints the pre-tax figure with no bracket wording, a
// Material Sales Tax row only if taxable, a Remodel Tax row only if remodel, and the Total, and
// the rows add up. One line prints the whole bid and says which taxes are in it. The bid is
// tax-inclusive (D88 already holds both taxes), so taxes are backed OUT using each tab's own
// tax cells, never added on top.
//
// THE MARKERS. An edited price line keeps the estimator's WORDS; its amount and tax wording stay
// live. Where the typed line still carries today's computed amount and tax phrase verbatim, they
// are stored as ⟦amount⟧ and ⟦tax⟧ and today's values go back in at render — on screen here, in
// the document in price_rules.resolve_line. A line with a DIFFERENT dollar figure keeps it: the
// editor marks it, Send asks, and then it is the estimator's to send.
(function (root, factory) {
  var api = factory();
  root.TWPrice = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;   // node, for tests
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var AMOUNT = "⟦amount⟧";
  var TAX = "⟦tax⟧";
  var PHRASE = {
    both: "(Remodel Tax AND material sales tax INCLUDED)",
    material: "(material sales tax INCLUDED)",
    remodel: "(Remodel Tax INCLUDED)",
    none: "(tax exempt)",
  };
  // Every wording this tool has ever printed for the tax, longest first so a shorter one can
  // never be found inside a longer one.
  var KNOWN_PHRASES = [PHRASE.both, PHRASE.remodel, PHRASE.material, PHRASE.none];
  var BROKEN_ALIASES = ["BROKEN_OUT", "BROKEN OUT", "BROKENOUT", "ITEMIZED", "BREAKOUT"];

  /** Whole cents. The rows have to add up to the cent, not within a float's error. */
  function cents(v) {
    var n = Number(String(v == null ? "" : v).replace(/[$,\s]/g, ""));
    return isFinite(n) ? Math.round(n * 100) : 0;
  }

  /** An estimate flag as a boolean; a draft saved before the flags travelled answers from the
   *  sheet's own figure (its tax cells are 0 exactly when the flag says No). */
  function flag(v, fallback) {
    if (v === true || v === false) return v;
    if (typeof v === "string" && v.trim()) {
      var s = v.trim().toLowerCase();
      if (["yes", "y", "true", "1"].indexOf(s) >= 0) return true;
      if (["no", "n", "false", "0"].indexOf(s) >= 0) return false;
    }
    return !!fallback;
  }

  function phraseFor(taxable, remodelOn) {
    if (taxable && remodelOn) return PHRASE.both;
    if (taxable) return PHRASE.material;
    if (remodelOn) return PHRASE.remodel;
    return PHRASE.none;
  }

  /** THE RULE for one priced system — the base, or one option, off its own tab.
   *  sys = {total, sales_tax, remodel, taxable?, remodel_on?}. Figures come back in CENTS. */
  function taxRule(sys, broken) {
    sys = sys || {};
    var t = cents(sys.total), s = cents(sys.sales_tax), r = cents(sys.remodel);
    // No flag: the figure answers. No flag and no sales-tax figure at all: nothing says the job is
    // exempt, so it reads as taxable — what every such document printed before (price_rules too).
    var salesKnown = sys.sales_tax != null && !(typeof sys.sales_tax === "string" && !sys.sales_tax.trim());
    var tx = flag(sys.taxable, salesKnown ? s > 0 : true), rm = flag(sys.remodel_on, r > 0);
    var out = { broken: !!broken, taxable: tx, remodel_on: rm,
                total_cents: t, sales_cents: s, remodel_cents: r };
    if (broken) {
      out.base_cents = Math.max(0, t - (tx ? s : 0) - (rm ? r : 0));
      out.phrase = ""; out.material = tx; out.remodel = rm; out.total = true;
    } else {
      out.base_cents = t;
      out.phrase = phraseFor(tx, rm); out.material = false; out.remodel = false; out.total = false;
    }
    return out;
  }

  /** "ONE_LINE" or "BROKEN_OUT".
   *
   *  `taxLayout` is the control's own answer and wins. A draft from before the control carries
   *  the old three-way `taxInclusion`, read by what it PRINTED (see price_rules.layout_is_broken
   *  for the table). A draft that carries neither was never decided by anybody, so it takes the
   *  default Hanz asked for — Broken out whenever a tax applies — and keeps following the sheet
   *  until the estimator picks one. */
  function layoutFor(taxLayout, taxInclusion, freeRows, taxable, remodelOn) {
    var lay = String(taxLayout || "").trim().toUpperCase();
    if (lay === "BROKEN_OUT" || lay === "ONE_LINE") return lay;
    var legacy = String(taxInclusion == null ? "" : taxInclusion).trim().toUpperCase();
    var dflt = (taxable || remodelOn) ? "BROKEN_OUT" : "ONE_LINE";
    if (!legacy) return dflt;
    if (BROKEN_ALIASES.indexOf(legacy) >= 0) return "BROKEN_OUT";
    if (freeRows) return dflt;
    return "ONE_LINE";
  }

  /** Where `amount` sits in `s` as a whole figure: "$6,767" is not the start of "$6,767.50". */
  function amountIndex(s, amount) {
    s = String(s == null ? "" : s);
    amount = String(amount == null ? "" : amount);
    if (!amount) return -1;
    var from = 0;
    while (true) {
      var i = s.indexOf(amount, from);
      if (i < 0) return -1;
      var after = s.slice(i + amount.length, i + amount.length + 2);
      var endsMid = /^\d/.test(after) || /^[.,]\d/.test(after);
      var before = i > 0 ? s.charAt(i - 1) : "";
      var startsMid = /[\d$]/.test(before) && /^\d/.test(amount);
      if (!endsMid && !startsMid) return i;
      from = i + 1;
    }
  }

  /** An edited line with today's amount and tax wording where its markers are. A phrase that is
   *  empty (Broken out) takes the one space in front of its marker with it. */
  function resolveLine(text, amount, phrase) {
    var s = String(text == null ? "" : text);
    if (s.indexOf(AMOUNT) >= 0) s = s.split(AMOUNT).join(amount == null ? "" : String(amount));
    if (s.indexOf(TAX) >= 0) {
      var ph = phrase == null ? "" : String(phrase);
      s = s.replace(/([ \t]?)⟦tax⟧/g, function (m, sp) { return ph ? sp + ph : ""; });
    }
    return s;
  }

  /** What to STORE for one line the estimator typed: his words, with today's amount and tax
   *  phrase turned into markers wherever they are still there verbatim.
   *
   *  `slot` says the line has a place for tax wording (the base line, an option's own line, a
   *  combo system line). When that place is EMPTY right now — Broken out prints no bracket — the
   *  marker is put at the end of the line, which is where the template prints the phrase, so a
   *  switch back to one line brings the wording back instead of losing it for good. */
  function captureLine(typed, amount, phrase, slot) {
    var s = String(typed == null ? "" : typed);
    if (amount) {
      var i = amountIndex(s, amount);
      if (i >= 0) s = s.slice(0, i) + AMOUNT + s.slice(i + String(amount).length);
    }
    var hasTax = false;
    var list = (phrase ? [String(phrase)] : []).concat(KNOWN_PHRASES);
    for (var k = 0; k < list.length && !hasTax; k++) {
      var j = s.indexOf(list[k]);
      if (j >= 0) { s = s.slice(0, j) + TAX + s.slice(j + list[k].length); hasTax = true; }
    }
    if (!hasTax && slot && !phrase && s.trim()) s = (/[ \t]$/.test(s) ? s : s + " ") + TAX;
    return s;
  }

  /** Does a stored line carry a dollar figure of its own, in place of the estimate's? */
  function moneyOff(stored) {
    var s = String(stored == null ? "" : stored);
    if (s.indexOf(AMOUNT) >= 0) return false;
    return /\$\s?\d/.test(s.split(TAX).join(""));
  }

  /** The first dollar figure in a line, as printed ("$21,260"), or "". */
  function firstDollar(s) {
    var m = /\(?\$\s?[\d,]+(?:\.\d+)?\)?/.exec(String(s == null ? "" : s));
    return m ? m[0] : "";
  }

  /** Where the first dollar figure in `s` that is the SAME AMOUNT as one of `amounts`, written in
   *  another money style, sits: {at, len}, or null. Only plain "$X" amounts are asked about — an
   *  "Add $X" / "Deduct ($X)" amount carries words of its own and is matched only verbatim. Real
   *  drafts hold "$1,870.00" frozen by the preview when it still printed cents, for today's
   *  "$1,870": the same figure, which a string match calls a different one. */
  function sameAmountAt(s, amounts) {
    s = String(s == null ? "" : s);
    var plain = (amounts || []).filter(function (a) { return /^\$[\d,]+(?:\.\d+)?$/.test(String(a || "")); });
    if (!plain.length) return null;
    var re = /\$\s?[\d,]+(?:\.\d+)?/g, m;
    while ((m = re.exec(s))) {
      var before = m.index > 0 ? s.charAt(m.index - 1) : "";
      if (/[\d$]/.test(before)) continue;
      for (var q = 0; q < plain.length; q++) {
        if (cents(plain[q]) === cents(m[0])) return { at: m.index, len: m[0].length };
      }
    }
    return null;
  }

  /** A line saved before the markers existed: one string holding the whole line, frozen, and
   *  often more lines typed above or below it (Hanz's "\n\nTHis is a test send to Hanz").
   *
   *  Returns {main, before, after, drop}: `main` is the line itself with markers where today's
   *  amount (or any figure the old code froze into it — `parts.candidates`) and a known tax
   *  wording stood; `before` / `after` are the lines around it, each its own line from now on;
   *  `drop` means the line itself was a phantom — a "$0 – Total" the old box-wide sweep froze on
   *  a row nobody had touched — and nothing about it is the estimator's. */
  function migrateLine(legacy, parts) {
    parts = parts || {};
    var lines = String(legacy == null ? "" : legacy).replace(/\r\n?/g, "\n").split("\n");
    var cands = [parts.amount].concat(parts.candidates || []).filter(function (a) { return !!a; });
    var mi = -1;
    for (var i = 0; i < lines.length && mi < 0; i++) {
      for (var c = 0; c < cands.length; c++) if (amountIndex(lines[i], cands[c]) >= 0) { mi = i; break; }
    }
    if (mi < 0) for (var i1 = 0; i1 < lines.length; i1++) if (sameAmountAt(lines[i1], cands)) { mi = i1; break; }
    if (mi < 0) for (var i2 = 0; i2 < lines.length; i2++) if (/\$\s?\d/.test(lines[i2])) { mi = i2; break; }
    if (mi < 0) for (var i3 = 0; i3 < lines.length; i3++) if (lines[i3].trim()) { mi = i3; break; }
    if (mi < 0) return { main: null, before: [], after: [], drop: true };
    var before = lines.slice(0, mi), after = lines.slice(mi + 1);
    var main = lines[mi];
    if (parts.zeroIsPhantom) {
      var fig = firstDollar(main).replace(/[()$,\s]/g, "");
      var now = String(parts.amount || "").replace(/[()$,\s]/g, "");
      if (fig && Number(fig) === 0 && now && Number(now) !== 0) {
        return { main: null, before: before, after: after, drop: true };
      }
    }
    for (var d = 0; d < cands.length; d++) {
      var at = amountIndex(main, cands[d]);
      if (at >= 0) { main = main.slice(0, at) + AMOUNT + main.slice(at + String(cands[d]).length); break; }
    }
    if (main.indexOf(AMOUNT) < 0) {
      var same = sameAmountAt(main, cands);
      if (same) main = main.slice(0, same.at) + AMOUNT + main.slice(same.at + same.len);
    }
    main = captureLine(main, "", parts.phrase, parts.slot);
    return { main: main, before: before, after: after, drop: false };
  }

  // ── THE PRICE BOX'S BULLETS: Kyle's REBID layout ────────────────────────────────────────
  // Hanz, 2026-09-25, choosing it over the 2026-07-16 "no bullets in the pricing" rule: every money
  // line carries the template's red square (the PRICE list, numId 3, level 0), a line typed under or
  // over one is its sub-line and carries the hollow "o" (level 1), and headings and blank lines
  // carry nothing. 2026-09-26: "fix the indents and the bullets now" — what the ribbon sets on a
  // line beats the default. The document's half is price_rules (line_default / resolve_line_props);
  // test_price_bullets.py runs both over the same matrix.
  //
  // A RESOLVED line is {bullet: true, level} or {bullet: false, indent}: a bulleted line is placed
  // by its list level (square at 0 / text at 288 twips on level 0; "o" at 1080 / text at 1440 on
  // level 1 — every template defines numId 3 that way), an unbulleted one says where its text
  // starts. Switching a bullet off does not move the words.
  var LEVEL_LEFT = [288, 1440];
  var LEVEL_HANG = [288, 360];
  var INDENT_STEP = 288;
  var INDENT_MAX = 2880;
  var HEADING_KEYS = ["heading_base", "heading_options", "alt_name"];

  /** One stored override as {bullet?, level?: 0|1, indent?: 0..2880}; anything else dropped. */
  function cleanLineProps(raw) {
    var out = {};
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return out;
    if (raw.bullet === true || raw.bullet === false) out.bullet = raw.bullet;
    if (raw.level === 0 || raw.level === 1) out.level = raw.level;
    if (typeof raw.indent === "number" && isFinite(raw.indent)) {
      out.indent = Math.max(0, Math.min(INDENT_MAX, Math.round(raw.indent)));
    }
    return out;
  }

  /** What one PRICE line prints when the draft says nothing about it. `pos` is null for the line
   *  itself and "before" / "after" for a line typed above / below it. */
  function lineDefault(key, pos) {
    if (HEADING_KEYS.indexOf(String(key == null ? "" : key)) >= 0) return { bullet: false, indent: 0 };
    if (pos === "before" || pos === "after") return { bullet: true, level: 1 };
    return { bullet: true, level: 0 };
  }

  /** The line as set, blank or not: {bullet, level, indent} all filled in, `indent` being where the
   *  TEXT starts (a bulleted line's level's own left edge). */
  function lineIntent(key, pos, override) {
    var d = lineDefault(key, pos), o = cleanLineProps(override);
    var level = "level" in o ? o.level : (d.level || 0);
    var bullet = "bullet" in o ? o.bullet : d.bullet;
    if (bullet) return { bullet: true, level: level, indent: LEVEL_LEFT[level] };
    var indent = "indent" in o ? o.indent : (d.bullet ? LEVEL_LEFT[level] : (d.indent || 0));
    return { bullet: false, level: level, indent: indent };
  }

  /** What one PRICE line PRINTS: a blank line never carries a bullet. */
  function resolveLineProps(key, pos, text, override) {
    var it = lineIntent(key, pos, override);
    if (it.bullet && String(text == null ? "" : text).trim()) return { bullet: true, level: it.level };
    return { bullet: false, indent: it.indent };
  }

  /** One ribbon press on a line of the PRICE box, Word's way: the bullet on or off (the words stay
   *  where they are; a bullet switched on takes its level's own place), and on a bulleted line
   *  indent / outdent move it between the square and the "o" — Word's Increase Indent on a list
   *  item demotes it a level. On a line with no bullet they move the text a step (288 twips) at a
   *  time, from the margin to two inches. `intent` is {bullet, level, indent}; returns the new one,
   *  or null when the press cannot change anything (so the ribbon can say so). Shared by the
   *  computed price lines and the template's own PRICE-list paragraphs, so one box has one ribbon. */
  function paraStep(intent, action) {
    var it = intent || {};
    var bullet = !!it.bullet, level = it.level === 1 ? 1 : 0;
    var indent = Math.max(0, Math.min(INDENT_MAX, Math.round(Number(it.indent) || 0)));
    if (action === "bullet") {
      if (bullet) return { bullet: false, level: level, indent: indent };
      return { bullet: true, level: level, indent: LEVEL_LEFT[level] };
    }
    if (action === "indent") {
      if (bullet) return level === 0 ? { bullet: true, level: 1, indent: LEVEL_LEFT[1] } : null;
      return indent < INDENT_MAX ? { bullet: false, level: level, indent: Math.min(INDENT_MAX, indent + INDENT_STEP) } : null;
    }
    if (action === "outdent") {
      if (bullet) return level === 1 ? { bullet: true, level: 0, indent: LEVEL_LEFT[0] } : null;
      return indent > 0 ? { bullet: false, level: level, indent: Math.max(0, indent - INDENT_STEP) } : null;
    }
    return null;
  }

  /** What to STORE for a line whose intent is now `intent`: the smallest override that says it, or
   *  null when it is the line's own default (an untouched line stores nothing). */
  function overrideFor(key, pos, intent) {
    var d = lineIntent(key, pos, null);
    if (!intent) return null;
    if (intent.bullet) {
      if (d.bullet && d.level === intent.level) return null;
      return { bullet: true, level: intent.level === 1 ? 1 : 0 };
    }
    if (!d.bullet && d.indent === intent.indent) return null;
    // The level rides along when it is not the default one, so switching the bullet back on puts
    // the line back on the level it was switched off from.
    var off = { bullet: false, indent: intent.indent };
    if ((intent.level === 1 ? 1 : 0) !== (d.level || 0)) off.level = intent.level === 1 ? 1 : 0;
    return off;
  }

  return {
    AMOUNT: AMOUNT, TAX: TAX, PHRASE: PHRASE, KNOWN_PHRASES: KNOWN_PHRASES,
    cents: cents, flag: flag, phraseFor: phraseFor, taxRule: taxRule, layoutFor: layoutFor,
    amountIndex: amountIndex, resolveLine: resolveLine, captureLine: captureLine,
    moneyOff: moneyOff, firstDollar: firstDollar, sameAmountAt: sameAmountAt, migrateLine: migrateLine,
    LEVEL_LEFT: LEVEL_LEFT, LEVEL_HANG: LEVEL_HANG, INDENT_STEP: INDENT_STEP, INDENT_MAX: INDENT_MAX,
    HEADING_KEYS: HEADING_KEYS, cleanLineProps: cleanLineProps, lineDefault: lineDefault,
    lineIntent: lineIntent, resolveLineProps: resolveLineProps, paraStep: paraStep,
    overrideFor: overrideFor,
  };
});
