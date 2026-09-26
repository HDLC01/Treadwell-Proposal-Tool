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
// editor marks it, Send, Download and To Dropbox ask (confirmOwnFigures), and then it is the
// estimator's to send.
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

  /** Where the line's first dollar figure starts ("$6,767", the "$" of "($6,000)"), or -1. */
  function firstMoneyAt(s) {
    var m = /\$\s?\d/.exec(String(s == null ? "" : s));
    return m ? m.index : -1;
  }

  /** Where `amount` sits in `s` as the line's OWN PRICE: a whole figure (amountIndex) that holds
   *  the line's first dollar figure. The price is the first figure on a price line; today's amount
   *  anywhere further along is the estimator quoting it ("$5,800 – … (discounted from $6,307)"),
   *  and marking THAT as the live amount would print his $5,800 as if it followed the estimate —
   *  no warning, no Send prompt — while the figure he quoted moved with every re-price. */
  function priceIndex(s, amount) {
    s = String(s == null ? "" : s);
    var i = amountIndex(s, amount);
    if (i < 0) return -1;
    var f = firstMoneyAt(s);
    if (f < 0) return i;
    return (f >= i && f < i + String(amount).length) ? i : -1;
  }

  /** Tax wording of the estimator's own in a line: a bracket that talks about tax, this tool's
   *  wordings included ("(material sales tax EXCLUDED)", "(tax exempt)"). */
  var OWN_TAX_WORDS = /\([^()]*\btax(?:es)?\b[^()]*\)/i;

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
   *  The amount becomes the marker only where it is the line's own price (priceIndex). The tax
   *  marker is only ever TODAY'S wording, and only on a line that has a place for tax wording
   *  (`slot`: the base line, an option's own line, a combo system line). Any other wording is his:
   *  "(tax exempt)" typed over a taxable job's "(material sales tax INCLUDED)" is his correction,
   *  and "(material sales tax INCLUDED)" typed on a manual line, a Total or an Add/Deduct line —
   *  lines with no tax wording of their own — is his words. Turned into the marker, the first came
   *  back as the computed wording and the second as nothing, on screen and in the document.
   *
   *  When the slot is EMPTY right now — Broken out prints no bracket — the marker is put at the
   *  end of the line, which is where the template prints the phrase, so a switch back to one line
   *  brings the wording back instead of losing it for good. Not when the line already carries tax
   *  wording of his own: that switch would print both. */
  function captureLine(typed, amount, phrase, slot) {
    var s = String(typed == null ? "" : typed);
    if (amount) {
      var i = priceIndex(s, amount);
      if (i >= 0) s = s.slice(0, i) + AMOUNT + s.slice(i + String(amount).length);
    }
    var hasTax = s.indexOf(TAX) >= 0;
    if (!hasTax && slot && phrase) {
      var j = s.indexOf(String(phrase));
      if (j >= 0) { s = s.slice(0, j) + TAX + s.slice(j + String(phrase).length); hasTax = true; }
    }
    if (!hasTax && slot && !phrase && s.trim() && !OWN_TAX_WORDS.test(s)) {
      s = (/[ \t]$/.test(s) ? s : s + " ") + TAX;
    }
    return s;
  }

  /** Does a stored line carry a dollar figure of its own, in place of the estimate's? It does when
   *  its first dollar figure is typed rather than the live amount: a line stored before priceIndex
   *  can hold "$5,800 – … (discounted from ⟦amount⟧)", and that line's price is $5,800. */
  function moneyOff(stored) {
    var s = String(stored == null ? "" : stored).split(TAX).join("");
    var f = firstMoneyAt(s);
    if (f < 0) return false;
    var a = s.indexOf(AMOUNT);
    return a < 0 || f < a;
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
   *  (an own figure as its price, or a tab's figure at its amount) and, in a slot, a known tax
   *  wording stood;
   *  `before` / `after` are the lines around it, each its own line from now on; `drop` means the
   *  line itself was a phantom — a "$0 – Total" the old box-wide sweep froze on a row nobody had
   *  touched — and nothing about it is the estimator's. */
  function migrateLine(legacy, parts) {
    parts = parts || {};
    var lines = String(legacy == null ? "" : legacy).replace(/\r\n?/g, "\n").split("\n");
    var cands = [parts.amount].concat(parts.candidates || []).filter(function (a) { return !!a; });
    var others = (parts.others || []).filter(function (a) { return !!a; });
    // Today's figure in another money style, where it is the line's PRICE (its first figure) —
    // the same rule as priceIndex: a figure further along is one he quoted.
    var samePrice = function (s) {
      var hit = sameAmountAt(s, cands);
      return hit && hit.at === firstMoneyAt(s) ? hit : null;
    };
    // One of the line's own figures, AS ITS PRICE (priceIndex / samePrice): "$5,800 – … (discounted
    // from $6,307)" does not carry today's $6,307 as its price, so it is not the line priced at it.
    function own(l) {
      for (var c = 0; c < cands.length; c++) if (priceIndex(l, cands[c]) >= 0) return true;
      return !!samePrice(l);
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
      var at = priceIndex(main, cands[d]);
      if (at >= 0) { main = main.slice(0, at) + AMOUNT + main.slice(at + String(cands[d]).length); break; }
    }
    if (main.indexOf(AMOUNT) < 0) {
      var same = samePrice(main);
      if (same) main = main.slice(0, same.at) + AMOUNT + main.slice(same.at + same.len);
    }
    // A figure a tab of this draft priced the line at: only at the line's own amount, so a figure
    // quoted in his words ("…, Polish alternative $9,860") is never made the base bid's amount.
    if (main.indexOf(AMOUNT) < 0 && amountIsOneOf(main, others)) {
      var am = amountAt(main);
      main = main.slice(0, am.at) + AMOUNT + main.slice(am.at + am.len);
    }
    // The tax wording the OLD code printed in the slot: any of this tool's wordings, since the
    // layout and the flags that chose it may both have moved. Only in a slot: a line with no tax
    // wording of its own (a manual line, an Add/Deduct line, a Total) never had one printed for
    // it, so a wording there is the estimator's, and stays.
    if (parts.slot) {
      var list = (parts.phrase ? [String(parts.phrase)] : []).concat(KNOWN_PHRASES);
      for (var k = 0; k < list.length; k++) {
        var j = main.indexOf(list[k]);
        if (j >= 0) { main = main.slice(0, j) + TAX + main.slice(j + list[k].length); break; }
      }
    }
    // The marker at the end of an EMPTY slot (captureLine) only when the caller says what the slot
    // prints now: "" is Broken out, where the tool printed no wording. A caller that names no
    // phrase at all (applyBasePick with no basePhrase) does not know the layout, and gets no
    // marker added. Every page caller passes a string.
    main = captureLine(main, "", parts.phrase, parts.slot && parts.phrase != null);
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
   *  kept, marked in the editor, and Send, Download and To Dropbox ask ("says $7,447, the estimate
   *  says $15,149"). A base pick keeps it as his too (applyBasePick: Hanz, 2026-09-26, keep the
   *  words); typing today's figure back into the line makes it live again (captureLine).
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

  /** The base line's words for the system it prices, after its amount, by the work type the base
   *  tab gives the job: "Epoxy flooring as described above", "Polished Concrete Flooring as
   *  described above", ... Its twin is proposal-review.js baseDescLabel (with effectiveWorkType,
   *  which picks the work type): test_base_pick_follows.py runs both over every work type and base
   *  role and demands the same words. `role` is the base tab's; none (the combined base, or a tab
   *  nothing on the draft names) leaves the draft's own work type. */
  function baseDesc(workType, role) {
    var wt = String(workType || "epoxy").toLowerCase();
    var r = String(role || "").toLowerCase();
    var eff = wt === "combo" ? "combo" : (r === "epoxy" || r === "polish" || r === "gyp") ? r : wt;
    var noun = eff === "polish" ? "Polished Concrete Flooring"
             : eff === "combo" ? "Epoxy & Polished Concrete flooring"
             : eff === "sealer" ? "Sealed Concrete"
             : eff === "gyp" ? "Gypsum Underlayment System"
             : "Epoxy flooring";
    return noun + " as described above";
  }

  /** The lines that print the base bid itself, and the words each tax row prints after its amount. */
  var BASE_ROW_WORDS = { sales_tax: "Material Sales Tax", remodel: "Remodel Tax", total: "Total" };

  /** The tax wording the BASE line prints for a draft as it stands, "" when Broken out: the layout
   *  (layoutFor, off tax_layout / tax_inclusion) and the base's tax answers as the pages snapshot
   *  them (proposal_sales_tax, proposal_remodel_tax, proposal_taxable, proposal_remodel_on). For the
   *  Estimate step, which has no document to ask; the Proposal step's own is baseTaxRule, which
   *  also knows a template whose tax rows are plain paragraphs (GC, Gyp: no base line in a price
   *  box, so nothing for a pick to migrate). */
  function draftBasePhrase(draft) {
    var d = draft && typeof draft === "object" ? draft : {};
    var sys = { total: d.proposal_lump_sum, sales_tax: d.proposal_sales_tax, remodel: d.proposal_remodel_tax,
                taxable: d.proposal_taxable, remodel_on: d.proposal_remodel_on };
    var f = taxRule(sys, false);
    return taxRule(sys, layoutFor(d.tax_layout, d.tax_inclusion, false, f.taxable, f.remodel_on) === "BROKEN_OUT").phrase;
  }

  /** THE BASE-PICK RULE, one for all three ways the base bid changes: the Estimate step's bid strip
   *  (estimate-review.js wireBidBar), the Proposal step's sidebar (proposal-review.js), and deleting
   *  the base copy on the Estimate step (deleteTab: the base falls back to the one the sheet
   *  derives).
   *
   *  Hanz, 2026-09-26, twice. First, "the base bid was not updating": a base picked on the Estimate
   *  page went on printing the old tab's figure. Then, on the rule that fixed it by forgetting his
   *  edits: KEEP THE WORDS. A base price line he re-worded keeps his words through a pick; its
   *  amount, its words for the tab's system and its tax wording become the new base's.
   *
   *  WHAT A PICK DOES to the lines that print the base bid (the base line, its Material Sales Tax
   *  and Remodel Tax rows, its Total):
   *   * A LIVE line (lines2, carrying the amount marker) is kept as it is. It resolves against the
   *     new base when it is drawn and when the document is built.
   *   * A FIGURE OF HIS OWN (lines2, no marker) whose amount is a figure one of this draft's tabs
   *     prices that line at today (tabFigures: the old base's, a copy being deleted, the new base's)
   *     becomes the live marker: the figure is the tool's. Any other figure stays his -- kept,
   *     marked in the editor, and Send, Download and To Dropbox ask before it goes.
   *   * A LINE IN THE OLD SHAPE (lines) is migrated the same way HERE, while the figures of the tab
   *     it was frozen under are still on the draft (a deleted copy's leave it at the next pricing):
   *     migrateLine splits off the lines typed round it, and a tab's figure at its amount and a tax
   *     wording this tool has printed become markers. A "$0" on a tax row or the Total is the old
   *     box-wide sweep's phantom and goes.
   *     THE SAME PARTS AS DRAWING IT. The Proposal step migrates such a line the first time it draws
   *     it (proposal-review.js lineOverride), with the base line's tax slot and the wording it
   *     prints under the layout of the moment; a pick that meets the line first has to read it the
   *     same way, or the two disagree about the same line (review of dfcf589). So the base line is
   *     migrated with `opts.basePhrase`, the tax wording it prints right now (the old base's, "" when
   *     Broken out). Under Broken out the tool printed NO wording, so a line with none gets the tax
   *     marker at its end (captureLine) and a later One line brings the wording back; under One line
   *     a line with none had its wording taken out, and prints none after the pick, as before it.
   *     All three callers say (the Estimate step through draftBasePhrase, the sidebar through its
   *     own baseTaxRule); a caller that does not gets no marker added.
   *   * THE WORDS FOR THE TAB'S SYSTEM (baseDesc) are the old base's wherever they still stand
   *     verbatim in the base line, and become the new base's. His own words round them stay,
   *     whatever they say.
   *   * A line that now reads exactly as the tool prints it is no edit, and is not kept.
   *
   *  WHAT STILL RESETS: the per-field buckets of the oldest editor (single_bid, rows, combo). They
   *  froze an amount, a tax phrase or a description with no marker, and the document applies
   *  single_bid's amount as the base figure outright, so keeping one would print the old base's
   *  price under the new base. No editor writes them now.
   *
   *  NOTHING ELSE IS TOUCHED: the lines typed above and below any price line, the combo lines (they
   *  print only under the combined base, whose tabs no pick changes, and are migrated when drawn),
   *  every option line -- those of the old and the new base tab included (an option line prints
   *  only while its tab is an option, and his words for it come back if it is one again) -- manual
   *  lines, both headings, the lines typed on the gap, the alternate.
   *
   *  `from` / `to` are the base tab ids before and after (null: the combined or derived base).
   *  `tabs` is the draft's priced_tabs. `opts.workType` is the draft's work_type; `opts.roles`
   *  ({id: role}) names the tabs priced_tabs may not hold yet (the Estimate step passes its own tab
   *  list: a copy made a moment ago and picked at once); `opts.basePhrase` is the tax wording the
   *  base line prints before the pick (draftBasePhrase; see THE SAME PARTS above). Mutates `pov` in
   *  place; every caller saves it. Returns whether anything changed.
   *
   *  Page state only, like tabFigures: the document prints what the page saved, so price_rules.py
   *  has no twin of it (the parity test covers the rule the two halves both run). */
  function applyBasePick(pov, from, to, tabs, opts) {
    if (!pov || typeof pov !== "object" || Array.isArray(pov)) return false;
    var o = opts && typeof opts === "object" ? opts : {};
    var changed = false;
    var own = Object.prototype.hasOwnProperty;
    ["single_bid", "rows", "combo"].forEach(function (b) {
      var m = pov[b];
      if (m && typeof m === "object" && Object.keys(m).length) changed = true;
      pov[b] = {};
    });
    function roleOf(id) {
      if (id == null || id === "") return "";
      if (o.roles && typeof o.roles === "object" && own.call(o.roles, id) && o.roles[id]) return o.roles[id];
      var list = Array.isArray(tabs) ? tabs : [];
      for (var i = 0; i < list.length; i++) if (list[i] && list[i].id === id) return list[i].role || "";
      return "";
    }
    var descFrom = baseDesc(o.workType, roleOf(from)), descTo = baseDesc(o.workType, roleOf(to));
    var legacy = pov.lines && typeof pov.lines === "object" && !Array.isArray(pov.lines) ? pov.lines : null;
    var live = pov.lines2 && typeof pov.lines2 === "object" && !Array.isArray(pov.lines2) ? pov.lines2 : null;
    ["base", "sales_tax", "remodel", "total"].forEach(function (k) {
      var figs = tabFigures(tabs, k);
      var hasLive = !!live && typeof live[k] === "string" && !!live[k].trim();
      var text = hasLive ? live[k] : null;
      if (legacy && typeof legacy[k] === "string") {
        if (!hasLive) {
          // The base line always has a tax slot, so a wording this tool printed in it is the tool's
          // (migrateLine); the tax rows and the Total have none, and a wording on them is his.
          var m = migrateLine(legacy[k], k === "base"
            ? { others: figs, phrase: typeof o.basePhrase === "string" ? o.basePhrase : undefined, slot: true }
            : { others: figs });
          [["before", m.before], ["after", m.after]].forEach(function (pair) {
            var rows = pair[1];
            if (!rows || !rows.length) return;
            var b = pov[pair[0]];
            if (!b || typeof b !== "object" || Array.isArray(b)) b = pov[pair[0]] = {};
            if (!Array.isArray(b[k]) || !b[k].length) b[k] = rows.slice();
          });
          var main = !m.drop && m.main != null && m.main.trim() ? m.main : null;
          var at = main && k !== "base" ? amountAt(main) : null;
          if (at && cents(at.text) === 0) main = null;          // the old sweep's "$0 – Total"
          text = main;
        }
        delete legacy[k];
        changed = true;
      }
      if (text == null) return;
      var next = text;
      if (next.indexOf(AMOUNT) < 0 && amountIsOneOf(next, figs)) {
        var am = amountAt(next);
        next = next.slice(0, am.at) + AMOUNT + next.slice(am.at + am.len);
      }
      if (k === "base" && descFrom !== descTo && next.indexOf(descFrom) >= 0) {
        next = next.split(descFrom).join(descTo);
      }
      var canon = k === "base" ? AMOUNT + " – " + descTo + " " + TAX : AMOUNT + " – " + BASE_ROW_WORDS[k];
      if (next === canon) {
        if (hasLive) { delete live[k]; changed = true; }
        return;
      }
      if (!hasLive || live[k] !== next) {
        if (!live) live = pov.lines2 = {};
        live[k] = next;
        changed = true;
      }
    });
    return changed;
  }

  /** THE QUESTION a price line with a dollar figure of the estimator's own asks before the document
   *  leaves, one sentence per line, in Hanz's words: "This line says $X but the estimate says $Y —
   *  send anyway?" -- or "" when there is none. Hanz, 2026-09-25: warn, then let him send; and
   *  2026-09-26: the same on all three ways out. `act` is the verb: "send" (Send), "download" (the
   *  Files page's .docx and PDF buttons), "file" (To Dropbox). `warnings` is the document's own list
   *  (proposal-review.js priceWarnings, carried on proposal_payload.price_warnings). */
  function ownFigureQuestion(warnings, act) {
    var list = Array.isArray(warnings) ? warnings.filter(function (w) { return w && typeof w === "object"; }) : [];
    if (!list.length) return "";
    function one(w) {
      var says = String(w.says || "").trim() || "a figure of its own";
      var est = String(w.estimate || "").trim();
      return est ? "This line says " + says + " but the estimate says " + est
                 : "This line says " + says + ", typed by hand";
    }
    var lines = list.slice(0, 6).map(one);
    if (list.length > 6) lines.push("…and " + (list.length - 6) + " more line(s) like it");
    return lines.join(".\n") + " — " + (String(act || "").trim() || "send") + " anyway?";
  }

  /** THE CHECK all three ways out run before they build, file or send anything: ask the question
   *  when the draft's document has a price line with a figure of his own, and say whether to go on.
   *  `draft` is the copy that goes out: for Send this page's (TW.getState(), read at the press, once
   *  Send has checked it IS the server's), for Download and To Dropbox the server's (through
   *  confirmSavedCopy, below); `ask` puts the
   *  question to him (window.confirm) and is not called when there is nothing to ask. True: nothing
   *  to ask, or he said OK. False: he cancelled, and the caller does nothing at all. */
  function confirmOwnFigures(draft, act, ask) {
    var pp = draft && typeof draft === "object" ? draft.proposal_payload : null;
    var q = ownFigureQuestion(pp && typeof pp === "object" ? pp.price_warnings : null, act);
    if (!q) return true;
    return !!(typeof ask === "function" && ask(q));
  }

  /** THE CHECK, ASKED OF THE COPY THAT IS BUILT: Download and To Dropbox.
   *
   *  Neither builds this page's copy of the draft. The server builds and files ITS copy (POST
   *  /api/draft/{id}/documents, /api/to-dropbox), and a Files page's copy can be older than the
   *  server's: initDraftSync does not re-read a copy already stamped for the draft. Review of
   *  dfcf589: Kyle's Files page was current and clean; RJ typed $15,000 over the base amount on his
   *  machine and pressed Continue; Kyle pressed Download PDF, was asked nothing (his copy had no
   *  such line), and downloaded RJ's $15,000 document. Send was refused in the same case, because
   *  it reads the server's copy (TW.readServerRow) and will not go when the two differ.
   *
   *  So: this page's pending save goes first (flushState: it would go by itself within seconds,
   *  and the server must hold it before the server's copy is asked about), then the server's copy
   *  is read and the question asked of IT, by confirmOwnFigures, the one check. A draft with no id
   *  has no server copy; its own payload is what gets built, so it is the one asked about.
   *
   *  `tw` is the page's TW (shared.js). Resolves {go, failed, version}: `failed` when the save
   *  could not land or the server's copy could not be read, so nothing could be asked and nothing
   *  may be built; `go` false when he cancelled; `version`, when the server stored the copy asked
   *  about, which the build hands back (draft_version) so the server refuses a draft stored again
   *  since. The question can sit on screen a long while, and a colleague's save landing under it
   *  would otherwise be what gets built. No fetch here: `tw` does it. */
  function confirmSavedCopy(tw, act, ask) {
    var none = { go: false, failed: true, version: "" };
    return Promise.resolve(tw.flushState()).then(function (saved) {
      if (!saved) return none;
      if (!tw.getDraftId()) return { go: confirmOwnFigures(tw.getState(), act, ask), failed: false, version: "" };
      return Promise.resolve(tw.readServerRow()).then(function (row) {
        if (!row || !row.data || typeof row.data !== "object") return none;
        return { go: confirmOwnFigures(row.data, act, ask), failed: false,
                 version: typeof row.version === "string" ? row.version : "" };
      });
    });
  }

  return {
    AMOUNT: AMOUNT, TAX: TAX, PHRASE: PHRASE, KNOWN_PHRASES: KNOWN_PHRASES,
    cents: cents, flag: flag, phraseFor: phraseFor, taxRule: taxRule, layoutFor: layoutFor,
    amountIndex: amountIndex, priceIndex: priceIndex, firstMoneyAt: firstMoneyAt,
    resolveLine: resolveLine, captureLine: captureLine,
    moneyOff: moneyOff, firstDollar: firstDollar, sameAmountAt: sameAmountAt, migrateLine: migrateLine,
    amountAt: amountAt, amountIsOneOf: amountIsOneOf, priceShaped: priceShaped,
    usd: usd, tabFigures: tabFigures, baseDesc: baseDesc, applyBasePick: applyBasePick,
    draftBasePhrase: draftBasePhrase,
    ownFigureQuestion: ownFigureQuestion, confirmOwnFigures: confirmOwnFigures,
    confirmSavedCopy: confirmSavedCopy,
  };
});
