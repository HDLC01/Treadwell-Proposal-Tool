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

  /** The line's AMOUNT, where the tool prints it: its first plain dollar figure ("$7,447" in
   *  "$7,447 – …" and in "Add $7,447 – …"), as {at, len, text}, or null. */
  function amountAt(s) {
    s = String(s == null ? "" : s);
    var re = /\$\s?[\d,]+(?:\.\d+)?/g, m;
    while ((m = re.exec(s))) {
      var before = m.index > 0 ? s.charAt(m.index - 1) : "";
      if (/[\d$]/.test(before)) continue;
      return { at: m.index, len: m[0].length, text: m[0] };
    }
    return null;
  }

  /** Is the line's amount (amountAt) the same figure as one of `figures`, in any money style? */
  function amountIsOneOf(s, figures) {
    var a = amountAt(s);
    if (!a || !figures || !figures.length) return false;
    var c = cents(a.text);
    for (var i = 0; i < figures.length; i++) {
      if (/^\$[\d,]+(?:\.\d+)?$/.test(String(figures[i] || "")) && cents(figures[i]) === c) return true;
    }
    return false;
  }

  /** Does a line read like one of the tool's own price lines: its amount first ("$7,447 – …",
   *  "Add $3,189 – …", "($500) – …"), or a tax wording this tool has printed in it?
   *
   *  A line saved in the old shape holds the tool's line AND whatever was typed round it, and a
   *  note may quote a figure too: "Includes $500 cove allowance" above the price line, or "Polish
   *  alternative quoted separately at $9,860" (another tab's own total). Taking the first line with
   *  a figure in it for the price line made the note the price line: its words were printed with
   *  the base bid's amount, and the real price line was kept as a line he typed, frozen at the old
   *  figure, never re-priced, never forgotten on a later base pick and never warned about. */
  var PRICE_SHAPE = /^\s*(?:(?:add|deduct)\s+)?\(?\$\s?[\d,]+(?:\.\d+)?\)?\s*[–—-]/i;
  function priceShaped(line, phrase) {
    var s = String(line == null ? "" : line);
    if (PRICE_SHAPE.test(s)) return true;
    var list = (phrase ? [String(phrase)] : []).concat(KNOWN_PHRASES);
    for (var k = 0; k < list.length; k++) if (s.indexOf(list[k]) >= 0) return true;
    return false;
  }

  /** A line saved before the markers existed: one string holding the whole line, frozen, and
   *  often more lines typed above or below it (Hanz's "\n\nTHis is a test send to Hanz").
   *
   *  `parts` = {amount, phrase, slot, candidates, others, zeroIsPhantom}. `amount` and
   *  `candidates` are the line's OWN figures today (its amount, and the page's other forms of it:
   *  the total a broken-out base line froze under one line, say). `others` are the figures any tab
   *  of the draft prices this kind of line at (tabFigures): the old code often froze one of those,
   *  the old base's. They are weaker evidence -- a note can quote another tab's figure -- so they
   *  only ever count at the line's own amount (amountAt), never in its words.
   *
   *  WHICH LINE IS THE PRICE LINE, in order: a price-shaped line carrying one of its own figures;
   *  a price-shaped line whose amount is one a tab priced; the first price-shaped line; a line
   *  carrying one of its own figures; the first line with a figure; the first line with anything.
   *
   *  Returns {main, before, after, drop}: `main` is the line itself with markers where its amount
   *  (an own figure anywhere, or a tab's figure at its amount) and a known tax wording stood;
   *  `before` / `after` are the lines around it, each its own line from now on; `drop` means the
   *  line itself was a phantom — a "$0 – Total" the old box-wide sweep froze on a row nobody had
   *  touched — and nothing about it is the estimator's. */
  function migrateLine(legacy, parts) {
    parts = parts || {};
    var lines = String(legacy == null ? "" : legacy).replace(/\r\n?/g, "\n").split("\n");
    var cands = [parts.amount].concat(parts.candidates || []).filter(function (a) { return !!a; });
    var others = (parts.others || []).filter(function (a) { return !!a; });
    function own(l) {
      for (var c = 0; c < cands.length; c++) if (amountIndex(l, cands[c]) >= 0) return true;
      return !!sameAmountAt(l, cands);
    }
    function shaped(l) { return priceShaped(l, parts.phrase); }
    var steps = [
      function (l) { return shaped(l) && own(l); },
      function (l) { return shaped(l) && amountIsOneOf(l, others); },
      shaped,
      own,
      function (l) { return /\$\s?\d/.test(l); },
      function (l) { return !!l.trim(); },
    ];
    var mi = -1;
    for (var st = 0; st < steps.length && mi < 0; st++) {
      for (var i = 0; i < lines.length; i++) if (steps[st](lines[i])) { mi = i; break; }
    }
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
    // A figure a tab of this draft priced the line at: only at the line's own amount, so a figure
    // quoted in his words ("…, Polish alternative $9,860") is never made the base bid's amount.
    if (main.indexOf(AMOUNT) < 0 && amountIsOneOf(main, others)) {
      var am = amountAt(main);
      main = main.slice(0, am.at) + AMOUNT + main.slice(am.at + am.len);
    }
    main = captureLine(main, "", parts.phrase, parts.slot);
    return { main: main, before: before, after: after, drop: false };
  }

  /** A figure in the documents' own money style, from cents: "$7,447", "$1,870.50" (what the
   *  editor's fmtUSDdoc and the backend's _fmt_usd print). */
  function usd(c) {
    c = Math.round(Number(c) || 0);
    var neg = c < 0;
    if (neg) c = -c;
    var whole = String(Math.floor(c / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    var frac = c % 100;
    return (neg ? "-" : "") + "$" + whole + (frac ? "." + (frac < 10 ? "0" : "") + frac : "");
  }

  /** Every figure the draft's tabs price a line of this kind at TODAY, off ANY priced tab
   *  (state.priced_tabs, the old base included), in the documents' money style.
   *
   *  A line saved before the markers froze the figure it was typed next to, and that was often not
   *  today's base. Hanz, 2026-09-26, on the "Hanz Fix" staging project: he typed a note under the
   *  base line while Epoxy ($7,447) was the base, then made "Epoxy copy" ($15,149) the base; the
   *  note had frozen "$7,447" into the base line, and revisions 2-5 printed that figure as the base
   *  bid of a $15,149 job. While a tab still prices the line at the frozen figure, the tool made it,
   *  and migrateLine turns it into the live marker (at the line's amount only, see there).
   *
   *  TODAY is the limit. Only today's tab figures are known: nothing on the page records what a
   *  tab priced at before. On Hanz Fix itself, Epoxy was re-priced to $7,696 by revision 2, so its
   *  frozen $7,447 is no tab's figure any more, and that line is treated as a figure of his own:
   *  kept, marked in the editor, and Send asks ("says $7,447, the estimate says $15,149"). A pick
   *  of the base on either page forgets it (forgetBaseLines); typing today's figure back into the
   *  line makes it live again (captureLine).
   *
   *  `key` is the line's: a base, option or combo line asks for each tab's total and its pre-tax
   *  figure under any tax answer; a Material Sales Tax / Remodel Tax row for that tax; a Total for
   *  the total. Anything else (a manual line, a heading, the alternate) is no tab's line: []. */
  function tabFigures(tabs, key) {
    var k = String(key == null ? "" : key);
    var row = /(?:^|:)(sales_tax|remodel|total)$/.exec(k);
    var kind = row ? row[1] : (/^(?:base$|option:|combo:)/.test(k) ? "line" : "");
    if (!kind || !Array.isArray(tabs)) return [];
    var seen = {}, out = [];
    function add(c) { if (c > 0 && !seen[c]) { seen[c] = true; out.push(usd(c)); } }
    for (var i = 0; i < tabs.length; i++) {
      var t = tabs[i];
      if (!t || typeof t !== "object") continue;
      var tot = cents(t.total), s = cents(t.sales_tax), r = cents(t.remodel);
      if (kind === "sales_tax") add(s);
      else if (kind === "remodel") add(r);
      else if (kind === "total") add(tot);
      else { add(tot); add(tot - s); add(tot - r); add(tot - s - r); }
    }
    return out;
  }

  /** THE BASE-PICK RULE, one for both places a base bid is picked: the Estimate step's bid strip
   *  (estimate-review.js) and the Proposal step's sidebar (proposal-review.js).
   *
   *  Hanz, 2026-09-26, on staging: "the base bid was not updating". He picked another base tab on
   *  the Estimate page and the proposal went on quoting the old tab's price. The sidebar's pick
   *  forgot the old base's edited lines; the Estimate page's pick forgot only the oldest bucket
   *  (single_bid), so a base line saved with the old figure in it printed that figure under the new
   *  base, on screen and in the customer's document.
   *
   *  The lines that print the base bid itself belong to the base that was picked before: the base
   *  line (its words describe that tab's system), its tax rows and Total, and the combo lines. So
   *  do the option lines of the two tabs the pick moves: the one that was the base and the one that
   *  now is (it stops being an option). Their edited text is forgotten, both shapes, so the new
   *  base's own lines print. Every other option keeps its edit: its amount is a live marker that
   *  follows its own tab (an add/deduct amount follows the new base too), and its words are the
   *  estimator's. Lines he TYPED above and below any price line are his own lines and stay; a line
   *  saved in the old shape, with such lines inside it, gives them up to before / after first.
   *  Lines no base changes (manual price lines, the Base Bid and Options headings and the lines
   *  typed on the gap, the alternate system) are left alone.
   *
   *  `from` / `to` are the base tab ids before and after (null: the combined base). `tabs` is the
   *  draft's priced_tabs: a line in the old shape is split by migrateLine, and the figures those
   *  tabs price the line at tell its price line from a note typed round it that quotes a figure of
   *  its own ("$500 – cove allowance, included below"). Without them a note typed above the price
   *  line could be taken for it: deleted with the old base's line, while the real price line was
   *  kept as a typed line and printed its old figure under the new base, with no warning. Mutates
   *  `pov` in place; both pages save it. Returns whether a line went.
   *
   *  THE THIRD WAY the base changes is deleting the base copy on the Estimate step (deleteTab):
   *  the base falls back to the one the sheet derives, by this same rule.
   *
   *  Page state only, like tabFigures: the document prints what the page saved, so price_rules.py
   *  has no twin of either (the parity test covers the rule the two halves both run). */
  function forgetBaseLines(pov, from, to, tabs) {
    if (!pov || typeof pov !== "object" || Array.isArray(pov)) return false;
    var changed = false;
    function bound(key) {
      var k = String(key);
      if (/^(?:base|sales_tax|remodel|total)$/.test(k) || k.indexOf("combo:") === 0) return true;
      var m = /^option:(.*?)(?::(?:sales_tax|remodel|total))?$/.exec(k);
      return !!m && ((!!from && m[1] === from) || (!!to && m[1] === to));
    }
    ["single_bid", "rows", "combo"].forEach(function (b) {
      var m = pov[b];
      if (m && typeof m === "object" && Object.keys(m).length) changed = true;
      pov[b] = {};
    });
    var legacy = pov.lines && typeof pov.lines === "object" && !Array.isArray(pov.lines) ? pov.lines : null;
    if (legacy) {
      Object.keys(legacy).forEach(function (k) {
        if (!bound(k)) return;
        if (typeof legacy[k] === "string") {
          var m = migrateLine(legacy[k], { others: tabFigures(tabs, k) });
          [["before", m.before], ["after", m.after]].forEach(function (pair) {
            var rows = pair[1];
            if (!rows || !rows.length) return;
            var b = pov[pair[0]];
            if (!b || typeof b !== "object" || Array.isArray(b)) b = pov[pair[0]] = {};
            if (!Array.isArray(b[k]) || !b[k].length) b[k] = rows.slice();
          });
        }
        delete legacy[k];
        changed = true;
      });
    }
    var live = pov.lines2 && typeof pov.lines2 === "object" && !Array.isArray(pov.lines2) ? pov.lines2 : null;
    if (live) {
      Object.keys(live).forEach(function (k) {
        if (bound(k)) { delete live[k]; changed = true; }
      });
    }
    return changed;
  }

  return {
    AMOUNT: AMOUNT, TAX: TAX, PHRASE: PHRASE, KNOWN_PHRASES: KNOWN_PHRASES,
    cents: cents, flag: flag, phraseFor: phraseFor, taxRule: taxRule, layoutFor: layoutFor,
    amountIndex: amountIndex, resolveLine: resolveLine, captureLine: captureLine,
    moneyOff: moneyOff, firstDollar: firstDollar, sameAmountAt: sameAmountAt, migrateLine: migrateLine,
    amountAt: amountAt, amountIsOneOf: amountIsOneOf, priceShaped: priceShaped,
    usd: usd, tabFigures: tabFigures, forgetBaseLines: forgetBaseLines,
  };
});
