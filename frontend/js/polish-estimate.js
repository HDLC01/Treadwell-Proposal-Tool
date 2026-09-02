// Polish estimating, step 2 for polish jobs — three steps, priced from the item library.
// Externalized (CSP: no inline scripts). Do not add inline scripts.
//
// WHAT CHANGED, AND WHY THE WORKBOOK IS GONE FROM THIS PAGE.
//
// The first version of this page was a form over the Polish worksheet: every field wrote a cell,
// HyperFormula recalculated the sheet's own formulas, and the bid was read back out of D82. That
// held as long as the beta only re-arranged inputs the worksheet already had.
//
// Will's 2026-08-17 pass asked for things the worksheet cannot represent — a takeoff whose rows are
// ASSEMBLIES out of the Items & Assemblies library, labour lines an estimator can add, and the
// markup chain shown as its own reviewable block. There is no cell to write an assembly into. So
// the beta now prices itself, and the connection to Kyle's file is kept a different way: every
// percentage and every step of the chain is transcribed in polish-bid-core.js, and
// backend/tests/test_polish_markup_parity.py fails if his workbook and that transcription ever
// disagree. The pin replaces the engine.
//
// Two consequences worth stating plainly:
//
//   * This page NO LONGER writes state.cell_values. The downloaded .xlsx therefore shows the
//     template's own Polish tab, not what was priced here. That is survivable only because the
//     beta works on test projects by construction (see polish-sandbox.js) — it must be revisited
//     before any of this prices a real bid.
//   * computed_bid is REPLACED on every save, not merged. On a sandbox copy the source project's
//     computed_bid arrived with the blob, and merging would leave a real project's total sitting
//     underneath a beta price.
(function () {
  "use strict";

  var B = window.TWPolishBid;      // the markup chain, pinned to Kyle's Polish tab
  var L = window.TWLib;            // priceAssembly — the same maths the library page shows
  var S = window.TWPolishSandbox;  // never edit a live bid
  var $ = function (id) { return document.getElementById(id); };

  // The draft this page is working ON, and the model derived from it. Reassigned together by
  // adopt(), because the page can switch drafts mid-boot: opening a real bid here works on a test
  // copy instead, and rendering the copy with the real bid's numbers still in hand would be the
  // same silent mix-up in a different direction.
  var state = {};
  var M = null;

  // The library, loaded once at boot. Prices are recomputed from these on every keystroke rather
  // than stored on the row: an item's cost can move, and a stored line total would then disagree
  // with the same assembly priced on the library page.
  var ASMS = [];
  var ITEMS = [];

  var at = 0;

  function adopt(blob) {
    state = blob || {};
    M = B.migrateModel(state.polish_estimate);
  }

  adopt(TW.getState());

  var STEPS = [
    { key: "takeoff", label: "Takeoff and Material" },
    { key: "labor",   label: "Labor" },
    { key: "review",  label: "Review" },
  ];

  var UNITS = ["SF", "LF"];

  function say(msg, ok) {
    var el = $("alert");
    el.textContent = msg || "";
    el.className = "alert" + (ok ? " ok" : "");
  }

  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  };

  /** A form value: the estimator's own text, or empty. Never "0" for a field they left alone. */
  function nv(v) { return v == null ? "" : String(v); }

  /** Money with cents only when there are cents.
   *
   *  Kyle's sheet shows whole dollars, and a column of "$3,864.00" reads heavy. But hiding cents
   *  under a total that sums the exact figures is how "11 × $85.38" ended up printed under
   *  $939.21 on the library page. So: round figures stay round, and a fraction says so. */
  function moneyAuto(n) {
    var v = B.num(n);
    return Math.abs(v - Math.round(v)) < 0.005 ? B.money(v) : B.money2(v);
  }

  var api = async function (path, opts) {
    try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch (e) {}
    return fetch(TW.resolveApiBase() + path,
      Object.assign({}, opts || {}, { headers: TW.authHeaders((opts || {}).headers) }));
  };

  // ── pricing ─────────────────────────────────────────────────────────────────
  function asmById(id) {
    if (!id) return null;
    for (var i = 0; i < ASMS.length; i++) { if (ASMS[i].id === id) return ASMS[i]; }
    return null;
  }

  /** Resolve typed text to an assembly: exact name first, then a UNIQUE case-insensitive match.
   *
   *  Never a fuzzy guess — the same rule as the material picker on the library page. Two
   *  assemblies whose names differ only by case is a library problem to fix in the library, not
   *  something to resolve by picking one of them here. */
  function assemblyByName(text) {
    var want = String(text == null ? "" : text).trim();
    if (!want) return null;
    var i;
    for (i = 0; i < ASMS.length; i++) {
      if (String(ASMS[i].name == null ? "" : ASMS[i].name) === want) return ASMS[i];
    }
    var lc = want.toLowerCase();
    var hits = [];
    for (i = 0; i < ASMS.length; i++) {
      if (String(ASMS[i].name == null ? "" : ASMS[i].name).toLowerCase() === lc) hits.push(ASMS[i]);
    }
    return hits.length === 1 ? hits[0] : null;
  }

  /** What one takeoff row costs: the library's own price for that assembly at that measurement.
   *  null when the row has no assembly picked yet — which is not an error, just unfinished. */
  function rowPrice(row) {
    var r = row || {};
    var asm = asmById(r.assembly_id);
    if (!asm) return null;
    return L.priceAssembly(asm, ITEMS, B.num(r.measurement));
  }

  /** The row's cost as it should READ: a figure only when something was actually priced.
   *
   *  An assembly picked with no measurement yet prices to a perfectly legitimate 0 —
   *  priceAssembly returns {total: 0, priced_lines: 0} — and printing "$0" there tells the
   *  estimator the row is FREE, when the truth is that nobody has said how much of it there is.
   *  That is the state every row sits in for the whole time between picking an assembly and typing
   *  a number, so it is the state most likely to be read.
   *
   *  Both engines already refuse to do this with their own per-unit figures for exactly this
   *  reason (library-core.js's per_unit and polish-bid-core.js's per_sf are null rather than 0),
   *  and the cost box has to agree with them. Same for an assembly whose items cannot price: the
   *  warning line beneath it says why, and "—" is what invites reading it. */
  function rowCost(row) {
    var p = rowPrice(row);
    if (!p || !p.priced_lines) return { text: "—", empty: true, price: p };
    return { text: moneyAuto(p.total), empty: false, price: p };
  }

  function materialTotal() {
    var sum = 0;
    M.takeoff.forEach(function (r) {
      var p = rowPrice(r);
      if (p) sum += p.total;
    });
    return sum;
  }

  /** The county's REAL remodel-tax rate for this project, or 0 when nobody has picked a county.
   *
   *  Read off the draft under the same keys the live estimate screen writes (`county_remodel_rate`,
   *  set by its county picker and by the beta intake's), so a project that chose its county on
   *  either screen prices the same on both. Kyle's sheet hardcodes 10% here; that is not a real
   *  rate anywhere, and Hanz's instruction on 2026-08-18 was to use the actual one. When this
   *  returns 0 the engine falls back to the Kansas state rate rather than to 10%. */
  function remodelRate() {
    var r = state.county_remodel_rate;
    if (r !== null && r !== undefined && r !== "") return B.num(r);
    // A county IS chosen but carries no remodel rate — that is Missouri, where remodel labour is
    // generally exempt. Return a definite 0, not null: null would stand the Kansas state rate up
    // and charge a Missouri job a Kansas tax.
    if (state.county) return 0;
    return null;                        // nobody has picked a county yet
  }

  /** The whole bid, recomputed from the model. Cheap enough to call on every keystroke. */
  function bid() {
    return B.markupChain({
      material: materialTotal(),
      labor: B.laborTotal(M.labor),
      contingency: M.contingency,
      conditions: M.conditions,
      sf: B.takeoffSf(M.takeoff),
      remodel_rate: remodelRate(),
    });
  }

  // ── saving ──────────────────────────────────────────────────────────────────
  var saveTimer = null;
  function saveSoon() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      var b = bid();
      M.totals = b;                        // a snapshot for the card and for reading later; the
                                           // page never prices FROM it
      TW.setState(Object.assign({}, TW.getState(), {
        polish_estimate: M,
        // proposal-review reads this for the SF token, and /api/generate's files-mode rebuild
        // gates on it.
        polish_sf: b.sf,
        // Replaced, not merged — see the file header.
        computed_bid: {
          lump_sum: b.total,
          price_per_sf: b.per_sf,
          polish_sf: b.sf,
          // What the rest of the app reads: _bid_total in backend/drafts.py for the projects card,
          // and proposal-review for the lump sum and the two tax lines it itemizes.
          full_bid: {
            total_base_bid: b.total,
            sales_tax: b.sales_tax,
            remodel_tax: b.remodel_tax,
          },
        },
      }));
    }, 600);
  }

  // Same gap as the intake page's Fault 3: nothing here flushed its own 600ms debounce before
  // navigating away, and shared.js's pagehide net only flushes a timer THIS page armed. A takeoff
  // number typed and then left via the step nav inside that window was silently lost.
  window.addEventListener("pagehide", function () {
    if (!saveTimer) return;
    clearTimeout(saveTimer);
    saveTimer = null;
    var b = bid();
    M.totals = b;
    TW.setState(Object.assign({}, TW.getState(), {
      polish_estimate: M,
      polish_sf: b.sf,
      computed_bid: {
        lump_sum: b.total,
        price_per_sf: b.per_sf,
        polish_sf: b.sf,
        full_bid: {
          total_base_bid: b.total,
          sales_tax: b.sales_tax,
          remodel_tax: b.remodel_tax,
        },
      },
    }));
    TW.flushState();
  });

  /** One place every edit funnels through, so nothing can change a value without the bid, the
   *  rail and the draft all catching up.
   *
   *  `rerender` false repaints the computed figures in place instead of rebuilding the panel:
   *  rebuilding mid-keystroke moves the caret out of the field being typed in. */
  function changed(rerender) {
    paintBid();
    paintRail();
    saveSoon();
    if (rerender) renderPanel(); else repaintNumbers();
  }

  // ── the bid bar ─────────────────────────────────────────────────────────────
  function paintBid() {
    var b = bid();
    $("bidbar").hidden = false;
    $("bid-total").textContent = b.total ? B.money(b.total) : "—";
    $("bid-psf").textContent = (b.per_sf == null ? "" : B.money2(b.per_sf) + " / SF")
      + (b.sf ? " · " + B.fmtSf(b.sf) + " SF" : "");
    var bits = [];
    if (b.material_total) bits.push("Material " + B.money(b.material_total));
    if (b.labor_total) bits.push("Labor " + B.money(b.labor_total));
    $("maths").innerHTML = bits.map(esc).join(' <i>+</i> ');
  }

  // ── the rail ────────────────────────────────────────────────────────────────
  /** Untouched, done, or needs attention. Untouched is deliberately blank rather than a warning:
   *  a page that opens shouting at the estimator has said nothing. */
  function stepStatus() {
    var priced = 0, half = 0;
    M.takeoff.forEach(function (r) {
      var measured = B.num(r.measurement) > 0;
      if (r.assembly_id && measured) priced += 1;
      else if (r.assembly_id || measured) half += 1;
    });
    var lab = 0;
    M.labor.forEach(function (r) { if (B.laborCost(r) > 0) lab += 1; });
    return {
      takeoff: half ? "att" : (priced ? "ok" : ""),
      labor: lab ? "ok" : "",
      review: (priced && lab && !B.blockers(M).length) ? "ok" : "",
    };
  }

  function paintRail() {
    var st = stepStatus();
    var rail = $("rail");
    rail.innerHTML = "";
    STEPS.forEach(function (s, i) {
      var b = document.createElement("button");
      b.type = "button";
      if (i === at) b.setAttribute("aria-current", "true");
      var pip = document.createElement("span");
      var status = st[s.key] || "";
      pip.className = "pip" + (i === at ? "" : (status ? " " + status : ""));
      pip.textContent = (status === "ok" && i !== at) ? "✓" : String(i + 1);
      b.appendChild(pip);
      b.appendChild(document.createTextNode(s.label));
      b.addEventListener("click", function () { go(i); });
      rail.appendChild(b);
    });
  }

  function go(i) {
    at = Math.max(0, Math.min(STEPS.length - 1, i));
    paintRail();
    renderPanel();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // ── panels ──────────────────────────────────────────────────────────────────
  function shell(title, blurb, body) {
    var prev = at > 0
      ? '<button class="btn ghost" data-go="' + (at - 1) + '">← Back</button>' : "";
    var next = at < STEPS.length - 1
      ? '<button class="btn" data-go="' + (at + 1) + '">Next · ' +
        esc(STEPS[at + 1].label) + ' →</button>'
      // withDraft, not a bare path: this panel is rendered long after shared.js has finished
      // stamping ?d= onto the static links, and on a test copy the id it would have stamped is
      // the REAL project's. Continue has to carry the draft the page is actually editing.
      : '<a class="btn" href="' + esc(TW.withDraft("/proposal-review.html")) +
        '">Continue to proposal →</a>';
    return '<section class="sec"><div class="sec-h"><h2>' + esc(title) + '</h2><p>' +
      esc(blurb) + '</p></div><div class="sec-b">' + body + '</div>' +
      '<div class="nav"><span class="step-of">Step ' + (at + 1) + ' of ' + STEPS.length +
      '</span>' + prev + next + '</div></section>';
  }

  /** The hint under an assembly picker: what was matched, or that nothing was. */
  function asmHint(row) {
    var asm = asmById((row || {}).assembly_id);
    if (asm) {
      var n = (asm.lines || []).length;
      return n + " item line" + (n === 1 ? "" : "s") + " · priced per " + (asm.unit || "SF");
    }
    if (String((row || {}).assembly_name || "").trim()) {
      return "No assembly by that name — pick one from the list.";
    }
    return "From the Items &amp; Assemblies library.";
  }

  function measureText(row) {
    var r = row || {};
    return B.num(r.measurement) ? B.fmtSf(r.measurement) + " " + (r.unit || "SF") : "";
  }

  function takeoffPanel() {
    var html = M.takeoff.map(function (r, i) {
      var rc = rowCost(r);
      var p = rc.price;
      var warn = "";
      if (p && p.broken_lines) {
        warn = '<p class="warnline" data-broken-for="' + i + '">' + p.broken_lines + ' line' +
          (p.broken_lines === 1 ? '' : 's') + ' in this assembly cannot price yet — check the ' +
          'cost and coverage of its items in the library.</p>';
      }
      return '<div class="tk"><div class="tk-h">' +
        '<span class="tag">ROW ' + (i + 1) + '</span>' +
        '<span class="tk-sub" data-measure-for="' + i + '">' + esc(measureText(r)) + '</span>' +
        (M.takeoff.length > 1
          ? '<button class="x" data-del-row="' + i + '" title="Remove this row">✕</button>'
          : '') +
        '</div><div class="tk-g">' +

        '<div class="f"><label>Assembly</label>' +
        '<input list="dl-assemblies" data-tk="' + i + '" data-k="assembly_name" ' +
        'placeholder="Search assemblies…" value="' + esc(nv(r.assembly_name)) + '">' +
        '<p class="hint" data-asmhint-for="' + i + '">' + asmHint(r) + '</p></div>' +

        '<div class="f"><label>Measurement</label>' +
        '<input class="n" data-tk="' + i + '" data-k="measurement" value="' +
        esc(nv(r.measurement)) + '">' +
        '<p class="hint">How much of it there is.</p></div>' +

        '<div class="f"><label>Unit</label><select data-tk="' + i + '" data-k="unit">' +
        UNITS.map(function (u) {
          return '<option value="' + u + '"' + (r.unit === u ? " selected" : "") + '>' + u +
            '</option>';
        }).join("") + '</select>' +
        '<p class="hint">SF or LF.</p></div>' +

        '<div class="f"><label>Total cost</label>' +
        '<div class="costbox' + (rc.empty ? " empty" : "") + '" data-cost-for="' + i + '">' +
        esc(rc.text) + '</div>' +
        '<p class="hint" data-perunit-for="' + i + '">' +
        esc(p && p.per_unit != null ? B.money2(p.per_unit) + " / " + (r.unit || "SF") : "") +
        '</p></div>' +

        '</div>' + warn + '</div>';
    }).join("");

    html += '<button class="addbtn" data-add-row="1">＋ Add another assembly</button>';
    html += '<p class="cap">Material total <b data-mat-total>' +
      esc(moneyAuto(materialTotal())) + '</b> · measured area <b data-area-total>' +
      esc(B.fmtSf(B.takeoffSf(M.takeoff))) + ' SF</b>. LF rows are priced like any other but do ' +
      'not count toward the square footage the price-per-SF is divided by.</p>';

    return shell("Takeoff and material",
      "One row per assembly. The library prices it against the measurement you give it.", html);
  }

  function laborPanel() {
    var rows = M.labor.map(function (r, i) {
      return '<tr>' +
        '<td><input data-lab="' + i + '" data-k="label" value="' + esc(nv(r.label)) +
        '" placeholder="Task"></td>' +
        '<td class="r"><input class="n" data-lab="' + i + '" data-k="guys" value="' +
        esc(nv(r.guys)) + '"></td>' +
        '<td class="r"><input class="n" data-lab="' + i + '" data-k="days" value="' +
        esc(nv(r.days)) + '"></td>' +
        '<td class="r"><span class="mny">$<input class="n" data-lab="' + i +
        '" data-k="rate" value="' + esc(nv(r.rate)) + '"></span></td>' +
        '<td class="r calc" data-lcost-for="' + i + '">' +
        esc(moneyAuto(B.laborCost(r))) + '</td>' +
        '<td class="r">' + (M.labor.length > 1
          ? '<button class="x" data-del-lab="' + i + '" title="Remove this line">✕</button>'
          : '') + '</td></tr>';
    }).join("");

    rows += '<tr class="sum-row"><td>Labor total</td><td></td><td></td><td></td>' +
      '<td class="r" data-labor-total>' + esc(moneyAuto(B.laborTotal(M.labor))) +
      '</td><td></td></tr>';

    var pw = !!(M.conditions || {}).prevailing_wage;
    return shell("Labor",
      "Guys × days × rate, at " + B.HOURS_PER_DAY + " hours a day.",
      '<table><thead><tr><th>Task</th><th class="r" style="width:84px">Guys</th>' +
      '<th class="r" style="width:84px">Days</th>' +
      '<th class="r" style="width:112px">Rate / day</th>' +
      '<th class="r" style="width:112px">Cost</th><th style="width:28px"></th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table>' +
      '<button class="addbtn" data-add-lab="1">＋ Add a labor line</button>' +
      '<p class="cap">Prevailing wage is <b>' + (pw ? "on" : "off") + '</b>' +
      (pw ? ", so a 5% escalation is added on the review step" : "") +
      '. Change it on <a href="' + esc(TW.withDraft("/polish-intake.html")) +
      '">the intake step</a>.</p>');
  }

  // ── review ──────────────────────────────────────────────────────────────────
  function card(title, step, amt, inner) {
    return '<div class="rev"><div class="rev-h">' + esc(title) +
      ' <button data-go="' + step + '">Edit</button>' +
      (amt ? '<span class="amt">' + esc(amt) + '</span>' : '') + '</div>' + inner + '</div>';
  }

  /** rows: [label, middle, money, rowClass]. `money` may be pre-built HTML for a keyed cell. */
  function revTable(rows) {
    return '<table class="rev-t"><tbody>' + rows.map(function (r) {
      return '<tr' + (r[3] ? ' class="' + r[3] + '"' : '') + '><td>' + esc(r[0]) +
        '</td><td class="r">' + esc(r[1] == null ? "" : r[1]) + '</td><td class="r">' +
        (r[2] == null ? "" : r[2]) + '</td></tr>';
    }).join("") + '</tbody></table>';
  }

  /** An amount the chain computes, keyed so repaintNumbers can refresh it without a rebuild. */
  function mkAmt(b, key) {
    return '<span data-mk="' + key + '">' + esc(moneyAuto(b[key])) + '</span>';
  }

  function reviewPanel() {
    var b = bid();
    var blk = B.blockers(M);
    var html = "";
    if (blk.length) {
      html += '<div class="blockers"><b>Not finished yet.</b><ul>' +
        blk.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + '</ul></div>';
    }

    // Takeoff and material
    var tkRows = [];
    M.takeoff.forEach(function (r) {
      if (!r.assembly_id && !B.num(r.measurement)) return;
      tkRows.push([r.assembly_name || "(no assembly picked)", measureText(r),
                   esc(rowCost(r).text)]);
    });
    if (!tkRows.length) tkRows.push(["Nothing measured yet", "", ""]);
    tkRows.push(["Materials", "", mkAmt(b, "material")]);
    tkRows.push(["Shipping", B.pct(B.RATES.SHIPPING), mkAmt(b, "shipping")]);
    tkRows.push(["Material total", "", mkAmt(b, "material_total"), "tot"]);
    html += card("Takeoff and Material", 0, moneyAuto(b.material_total), revTable(tkRows));

    // Labor
    var labRows = [];
    M.labor.forEach(function (r) {
      if (!B.laborCost(r)) return;
      labRows.push([r.label || "Labor line",
                    B.num(r.guys) + " × " + B.num(r.days) + " × " + B.money2(r.rate),
                    esc(moneyAuto(B.laborCost(r)))]);
    });
    if (!labRows.length) labRows.push(["No labor entered yet", "", ""]);
    labRows.push(["Labor", "", mkAmt(b, "labor")]);
    labRows.push(["Labor escalation", b.escalation
      ? B.pct(B.RATES.ESCALATION) : "prevailing wage off", mkAmt(b, "escalation")]);
    labRows.push(["Labor burden", B.pct(B.RATES.BURDEN), mkAmt(b, "burden")]);
    labRows.push(["Labor total", "", mkAmt(b, "labor_total"), "tot"]);
    html += card("Labor", 1, moneyAuto(b.labor_total), revTable(labRows));

    html += '<div class="rev">' + markupTable(b) + '</div>';
    return shell("Review the bid",
      "Costs, then the markup Kyle's sheet applies, then the lump sum.", html);
  }

  /** Built at RENDER time, never at parse time.
   *
   *  withDraft has to be asked for the id the page settled on, and this module is parsed before
   *  shared.js has finished deciding — on a sandbox copy the id at parse time is still the REAL
   *  project's, so a link baked in then walks the estimator onto the live bid. Same reason shell()
   *  builds its Continue href inside the function. */
  function intakeNote() {
    return ' <span class="note">off · <a href="' +
      esc(TW.withDraft("/polish-intake.html")) + '">edit in Intake</a></span>';
  }

  /** Where the remodel rate came from, said out loud beside the row.
   *
   *  Worth the words: Kyle's sheet charges a flat 10% here, so an estimator who knows the workbook
   *  will read this line expecting that number. Naming the county, or naming the state fallback,
   *  is what stops the difference looking like a bug. */
  function remodelSource() {
    if (!(M.conditions || {}).remodel_tax) return intakeNote();
    var rate = remodelRate();
    // `county` already reads "Johnson County, KS" — the shape the live estimate screen's picker
    // writes and the beta intake matches, so both screens store one thing. Printing it as-is:
    // appending " County" to it produced "Johnson County, KS County".
    if (rate > 0) {
      return ' <span class="note">' + esc(state.county || "county rate") + '</span>';
    }
    if (rate === 0 && state.county) {
      return ' <span class="note">' + esc(state.county) +
        ' — remodel labor is exempt there</span>';
    }
    return ' <span class="note">Kansas state rate · <a href="' +
      esc(TW.withDraft("/polish-intake.html")) + '">pick a county</a> for the real one</span>';
  }

  /** Rows 64-82 of the Polish tab, in the same order, so an estimator who knows Kyle's sheet can
   *  read down it and recognise every line. Percentages are the sheet's own and not editable —
   *  the workbook locks these cells in the generated download for the same reason. Contingency is
   *  the one exception, because the sheet leaves D71 open too. */
  function markupTable(b) {
    var r = "";
    var row = function (label, pctHtml, key, cls) {
      return '<tr' + (cls ? ' class="' + cls + '"' : '') + '><td>' + label + '</td>' +
        '<td class="pct">' + pctHtml + '</td>' +
        '<td class="amt" data-mk="' + key + '">' + esc(moneyAuto(b[key])) + '</td></tr>';
    };
    var keyedPct = function (key) {
      return '<span data-mkpct="' + key + '">' + esc(B.pct(b[key])) + '</span>';
    };

    r += '<tr class="sub"><td>Sub-total costs</td><td class="pct"></td>' +
      '<td class="amt" data-mk="sub_total">' + esc(moneyAuto(b.sub_total)) + '</td></tr>';

    r += '<tr class="band"><td colspan="3">Markup</td></tr>';
    r += row("GP <span class=\"note\">before the lines below</span>", keyedPct("gp_pct"), "gp");
    r += row("Hard bid discount" + (b.hard_bid_pct ? "" :
      ' <span class="note">' + ((M.conditions || {}).hard_bid
        ? "under the discount threshold" : "hard bid off") + '</span>'),
      keyedPct("hard_bid_pct"), "hard_bid", b.hard_bid_pct ? "" : "off");
    r += row("Superintendent &amp; PTO", esc(B.pct(B.RATES.SUPER_PTO)), "super_pto");
    r += row("Soft costs", esc(B.pct(B.RATES.SOFT_COSTS)), "soft_costs");
    r += '<tr><td>Contingency <span class="note">yours to set</span></td>' +
      '<td class="pct"></td><td class="amt"><input data-contingency value="' +
      esc(nv(M.contingency)) + '" inputmode="decimal"></td></tr>';

    r += '<tr class="band"><td colspan="3">Taxes &amp; fees</td></tr>';
    r += row("Sales tax <span class=\"note\">on materials</span>" +
      ((M.conditions || {}).taxable ? "" : intakeNote()),
      keyedPct("sales_tax_pct"), "sales_tax", b.sales_tax_pct ? "" : "off");
    r += row("Remodel tax" + remodelSource(), keyedPct("remodel_pct"), "remodel_tax",
      b.remodel_pct ? "" : "off");
    r += row("Total taxes", "", "taxes", "tot");
    r += row("Fees + Textura", "", "fees", b.fees ? "" : "off");
    r += row("Bond", esc(B.pct(B.RATES.BOND)), "bond", b.bond ? "" : "off");
    r += row("Total fees + bond", "", "fees_and_bond", "tot");

    r += '<tr class="grand"><td>Total lump sum</td>' +
      '<td class="pct" data-mk-persf>' + esc(perSfText(b)) + '</td>' +
      '<td class="amt" data-mk="total">' + esc(moneyAuto(b.total)) + '</td></tr>';

    return '<table class="mk"><tbody>' + r + '</tbody></table>';
  }

  function perSfText(b) {
    if (!b.sf) return "";
    return B.money2(b.per_sf) + " / SF";
  }

  var PANELS = [takeoffPanel, laborPanel, reviewPanel];

  function renderPanel() { $("panels").innerHTML = PANELS[at](); }

  function renderDatalist() {
    var dl = $("dl-assemblies");
    if (!dl) return;
    dl.innerHTML = ASMS.map(function (a) {
      return '<option value="' + esc(a.name) + '"></option>';
    }).join("");
  }

  /** Refresh every computed figure in place, without rebuilding the panel.
   *
   *  Keyed by data-attribute, never by column position. The library page addressed its computed
   *  cells by column index and shipped Quantity and Cost written into each other's columns; the
   *  test agreed with the constants and missed it entirely. An attribute cannot be off by one. */
  function repaintNumbers() {
    var b = bid();

    document.querySelectorAll("[data-cost-for]").forEach(function (el) {
      var rc = rowCost(M.takeoff[parseInt(el.getAttribute("data-cost-for"), 10)]);
      el.textContent = rc.text;
      el.className = "costbox" + (rc.empty ? " empty" : "");
    });
    document.querySelectorAll("[data-perunit-for]").forEach(function (el) {
      var i = parseInt(el.getAttribute("data-perunit-for"), 10);
      var p = rowPrice(M.takeoff[i]);
      var r = M.takeoff[i] || {};
      el.textContent = (p && p.per_unit != null)
        ? B.money2(p.per_unit) + " / " + (r.unit || "SF") : "";
    });
    document.querySelectorAll("[data-measure-for]").forEach(function (el) {
      el.textContent = measureText(M.takeoff[parseInt(el.getAttribute("data-measure-for"), 10)]);
    });
    document.querySelectorAll("[data-asmhint-for]").forEach(function (el) {
      el.innerHTML = asmHint(M.takeoff[parseInt(el.getAttribute("data-asmhint-for"), 10)]);
    });
    document.querySelectorAll("[data-lcost-for]").forEach(function (el) {
      el.textContent = moneyAuto(B.laborCost(M.labor[parseInt(
        el.getAttribute("data-lcost-for"), 10)]));
    });

    var one = function (sel, txt) {
      var el = document.querySelector(sel);
      if (el) el.textContent = txt;
    };
    one("[data-mat-total]", moneyAuto(materialTotal()));
    one("[data-area-total]", B.fmtSf(B.takeoffSf(M.takeoff)) + " SF");
    one("[data-labor-total]", moneyAuto(B.laborTotal(M.labor)));
    one("[data-mk-persf]", perSfText(b));

    document.querySelectorAll("[data-mk]").forEach(function (el) {
      el.textContent = moneyAuto(b[el.getAttribute("data-mk")]);
    });
    // The GP band and the two tax rates move with the sub-total and the toggles, so the percentage
    // column is as computed as the money column is.
    document.querySelectorAll("[data-mkpct]").forEach(function (el) {
      el.textContent = B.pct(b[el.getAttribute("data-mkpct")]);
    });
  }

  // ── events ──────────────────────────────────────────────────────────────────
  // Delegated, because every panel is re-rendered from state rather than mutated in place.
  // Monotonic, not derived from the row count: add-delete-add inside one millisecond used to
  // regenerate an id that had already been used. Nothing indexes labor rows by id today (the page
  // works by array position), so this is closing a door rather than fixing a symptom.
  var laborSeq = 0;
  function newLaborRow() {
    laborSeq += 1;
    return { id: "u_" + Date.now() + "_" + laborSeq, label: "", guys: "", days: "", rate: "" };
  }

  document.addEventListener("click", function (e) {
    var t = e.target;
    if (!t || !t.closest) return;

    var go_ = t.closest("[data-go]");
    if (go_) { e.preventDefault(); go(parseInt(go_.getAttribute("data-go"), 10)); return; }

    if (t.closest("[data-add-row]")) {
      M.takeoff.push({ assembly_id: "", assembly_name: "", measurement: "", unit: "SF" });
      changed(true);
      return;
    }
    var dr = t.closest("[data-del-row]");
    if (dr) {
      M.takeoff.splice(parseInt(dr.getAttribute("data-del-row"), 10), 1);
      if (!M.takeoff.length) {
        M.takeoff.push({ assembly_id: "", assembly_name: "", measurement: "", unit: "SF" });
      }
      changed(true);
      return;
    }
    if (t.closest("[data-add-lab]")) {
      M.labor.push(newLaborRow());
      changed(true);
      return;
    }
    var dl = t.closest("[data-del-lab]");
    if (dl) {
      M.labor.splice(parseInt(dl.getAttribute("data-del-lab"), 10), 1);
      if (!M.labor.length) M.labor.push(newLaborRow());
      changed(true);
      return;
    }
  });

  /** Point a takeoff row at an assembly, by the name that was typed or picked. */
  function setAssembly(i, text) {
    var row = M.takeoff[i];
    if (!row) return false;
    var before = row.assembly_id || "";
    row.assembly_name = text;
    var asm = assemblyByName(text);
    row.assembly_id = asm ? asm.id : "";
    // Adopt the assembly's own unit only when the pick actually CHANGES. Doing it on every
    // keystroke would snap a row whose unit the estimator switched by hand back to the library's.
    if (asm && row.assembly_id !== before) {
      var u = String(asm.unit == null ? "" : asm.unit).toUpperCase();
      if (u === "SF" || u === "LF") {
        row.unit = u;
        var sel = document.querySelector('select[data-tk="' + i + '"][data-k="unit"]');
        if (sel) sel.value = u;        // in place: a rebuild here would take the caret with it
      }
    }
    return !!asm;
  }

  document.addEventListener("input", function (e) {
    var el = e.target;
    if (!el || !el.matches) return;

    if (el.matches("[data-contingency]")) {
      M.contingency = el.value;
      changed(false);
      return;
    }
    if (!el.matches("input")) return;
    var k = el.getAttribute("data-k");

    var ti = el.getAttribute("data-tk");
    if (ti !== null && k) {
      var i = parseInt(ti, 10);
      if (k === "assembly_name") setAssembly(i, el.value);
      else if (M.takeoff[i]) M.takeoff[i][k] = el.value;
      changed(false);
      return;
    }

    var li = el.getAttribute("data-lab");
    if (li !== null && k) {
      var j = parseInt(li, 10);
      if (M.labor[j]) M.labor[j][k] = el.value;
      changed(false);
      return;
    }
  });

  document.addEventListener("change", function (e) {
    var el = e.target;
    if (!el || !el.getAttribute) return;
    var ti = el.getAttribute("data-tk");
    if (ti === null) return;
    var i = parseInt(ti, 10);
    var k = el.getAttribute("data-k");
    if (k === "unit") {
      if (M.takeoff[i]) M.takeoff[i].unit = el.value;
      changed(false);
      return;
    }
    if (k === "assembly_name") {
      // Committed — blurred, or picked off the list. A TARGETED repaint, not a re-render.
      //
      // `change` on this field fires when the estimator leaves it, and the ordinary way to leave it
      // is Tab into Measurement. A full re-render at that moment rebuilds the row, destroys the
      // field they have just tabbed into, and drops focus onto <body> — so the number they type
      // next goes nowhere at all. Found by tabbing between the two fields on staging; every unit
      // test passed, because a test never has to reach for the keyboard.
      //
      // Nothing is lost by repainting instead: the hint, the per-unit line, the measurement label
      // and the cost are all keyed and refreshed by repaintNumbers, and setAssembly already syncs
      // the unit select in place.
      setAssembly(i, el.value);
      changed(false);
    }
  });

  // ── boot ────────────────────────────────────────────────────────────────────
  async function init() {
    try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch (e) {}
    // shared.js is still deciding which draft this page is on (it can even hydrate and reload),
    // and every decision below turns on that id.
    try { await TW.draftReady; } catch (e) {}
    adopt(TW.getState());

    // Before the library, before the form, before anything can be typed: whatever happens after
    // this line writes to a test project. A save timer started against the real bid and fired
    // after the switch would be the bug with extra steps.
    if (!(await S.enterSandbox(adopt))) return;

    $("proj-line").textContent = [state.project_name, state.city && state.state
      ? state.city + ", " + state.state : ""].filter(Boolean).join(" · ") || "Untitled project";

    try {
      var res = await Promise.all([
        api("/api/library/assemblies"),
        api("/api/library/items"),
      ]);
      var aj = await res[0].json();
      var ij = await res[1].json();
      ASMS = (aj && aj.assemblies) || [];
      ITEMS = (ij && ij.items) || [];
    } catch (err) {
      $("loading").textContent = "Couldn't load the item library, so there is nothing to price " +
        "against. " + (err.message || "") + " Reload to try again.";
      return;
    }

    if (!ASMS.length) {
      say("The item library has no assemblies yet, so a takeoff row has nothing to point at. " +
          "Add one under Items & Assemblies first.");
    }

    // Seed the measurement from intake if nothing has been measured here yet, so the page opens
    // with the number the estimator already gave us rather than a blank.
    if (!B.takeoffSf(M.takeoff) && B.num(state.polish_sf) > 0) {
      M.takeoff[0].measurement = B.num(state.polish_sf);
    }

    renderDatalist();
    $("loading").hidden = true;
    $("main").hidden = false;
    paintBid();
    paintRail();
    renderPanel();
  }

  init();
})();
