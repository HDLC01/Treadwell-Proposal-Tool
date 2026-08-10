// Polish estimating, step 2 for polish jobs — the spreadsheet replaced by seven sub-steps.
// Externalized (CSP: no inline scripts). Do not add inline scripts.
//
// WHAT THIS PAGE IS, AND WHAT IT IS CAREFUL NOT TO BE.
//
// It is a form over the Polish worksheet. Every field writes a cell; HyperFormula recalculates
// the worksheet's OWN formulas; the bid is read back out of D82. Nothing here prices anything,
// so the figure on screen is the figure in the downloaded .xlsx by construction rather than by
// reconciliation — the whole reason the spreadsheet could stop being the interface without
// ceasing to be the engine.
//
// Two details that are load-bearing rather than incidental:
//
//   * EVERY sheet is loaded, not just Polish. The polish formulas reference `Epoxy!` (the whole
//     job header mirrors it) and `validation!` (pad and tooling rate bands). Loading Polish
//     alone leaves those as #REF and the bid reads as nonsense.
//   * Values are persisted into `state.cell_values`, the same store estimate-review writes and
//     done.js posts to /api/generate. That is what makes the screen and the file one thing
//     instead of two agreeing things. MERGED, never replaced: the draft may carry Epoxy!* from
//     a job that changed work type.
(function () {
  "use strict";

  var P = window.TWPolish;
  var X = window.TWXL;
  var $ = function (id) { return document.getElementById(id); };

  // The draft this page is working ON, and the two views derived from it. Reassigned together by
  // adopt(), because the page can switch drafts mid-boot: opening a real bid here works on a test
  // copy instead (see enterSandbox), and rendering the copy with the real bid's numbers still in
  // hand would be the same silent mix-up in a different direction.
  var state = {};
  var cellValues = {};
  var M = null;

  /** An estimator's DELIBERATE override of a worksheet formula, kept exactly as they left it.
   *
   *  This page must never CREATE one - writing a number into "=E18" because a form field
   *  happened to be filled is the bug that put materials at $0. cellWrites refuses that.
   *
   *  But an override that already exists is a different thing entirely, and the difference is
   *  the whole point. Estimate Review is a spreadsheet: typing over a formula there is an
   *  ordinary, intentional act, the same as it is in Excel. Kyle does it - a real prod job has
   *  Polish!B37 = 2.5 where the template says "=E37", because he judged the days himself.
   *
   *  An earlier version of this file STRIPPED every such entry, on the theory that they were all
   *  poison left by the broken build. They are not. On production there was no poison at all -
   *  this page had never run there - so stripping only destroyed real work, silently, and made
   *  the two screens disagree about the same job by $5,634.
   *
   *  So: keep it, show it, and mark it. Same amber convention the rest of the tool uses for a
   *  hand-edited figure. */
  function overrideFor(addr) {
    var v = (state.cell_values || {})["Polish!" + addr];
    return (v === undefined || v === null || v === "") ? null : v;
  }

  var engine = null;
  var sheetNames = [];
  var at = 0;

  // The page's own model. Kept under one key so it round-trips with the draft and cannot
  // collide with the epoxy page's fields.
  function freshModel(s) {
    return Object.assign({
      areas: [{ name: "", sf: "" }],
      system: "S&P",
      tooling: "traditional",
      conditions: { local: true, hard_bid: false, prevailing_wage: false,
                    taxable: true, remodel_tax: false },
      materials: {},
      added: [],
      labour: {},
      adds: {},
      options: {},
    }, (s || {}).polish_estimate || {});
  }

  /** Point the page at one draft's blob: its state, its cell map, its model. */
  function adopt(blob) {
    state = blob || {};
    cellValues = Object.assign({}, state.cell_values || {});
    M = freshModel(state);
  }

  adopt(TW.getState());

  var STEPS = [
    { key: "areas",      label: "Areas" },
    { key: "conditions", label: "Conditions" },
    { key: "materials",  label: "Materials" },
    { key: "labour",     label: "Crew" },
    { key: "adds",       label: "Adds" },
    { key: "options",    label: "Options" },
    { key: "review",     label: "Review" },
  ];

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

  // ── reading the workbook ────────────────────────────────────────────────────
  function read(addr) {
    if (!engine) return null;
    var v = engine.getValue(P.SHEET, addr);
    return typeof v === "number" ? v : null;
  }

  /** Push the form's cells into the engine, and remember them for the .xlsx.
   *  Only what changed is written: setCellValue triggers a recalculation each time, and the
   *  material block alone is thirty cells. */
  function pushCells() {
    var want = P.cellWrites(M);
    for (var addr in want) {
      var v = want[addr];
      if (cellValues[addr] === v) continue;
      cellValues[addr] = v;
      var parts = addr.split("!");
      engine.setCellValue(parts[0], parts[1], v === null ? "" : v);
    }
  }

  function bid() {
    return {
      material: read(P.CELLS.material_total),
      labour:   read(P.CELLS.labour_total),
      tooling:  read(P.CELLS.tooling_total),
      total:    read(P.CELLS.total),
      perSf:    read(P.CELLS.per_sf),
      area:     P.totalArea(M.areas),
    };
  }

  function paintBid() {
    var b = bid();
    $("bidbar").hidden = false;
    $("bid-total").textContent = b.total == null ? "—" : P.fmtMoney(b.total);
    $("bid-psf").textContent = (b.perSf == null ? "" : P.fmtRate(b.perSf) + " / SF")
      + (b.area ? " · " + P.fmtSf(b.area) : "");
    var bits = [];
    if (b.material != null) bits.push("Materials " + Math.round(b.material).toLocaleString());
    if (b.labour != null) bits.push("Labour " + Math.round(b.labour).toLocaleString());
    if (b.tooling != null) bits.push("Tooling " + Math.round(b.tooling).toLocaleString());
    $("maths").innerHTML = bits.map(esc).join(' <i>+</i> ');
  }

  // ── saving ──────────────────────────────────────────────────────────────────
  var saveTimer = null;
  function saveSoon() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      // Merge, never replace: cell_values may carry Epoxy!* entries from before this job's
      // work type changed, and the generate path reads the whole map.
      var merged = Object.assign({}, TW.getState().cell_values || {}, cellValues);
      TW.setState(Object.assign({}, TW.getState(), {
        cell_values: merged,
        polish_estimate: M,
        // What the rest of the app reads for the card and the proposal.
        computed_bid: Object.assign({}, TW.getState().computed_bid || {}, {
          lump_sum: read(P.CELLS.total),
          price_per_sf: read(P.CELLS.per_sf),
          polish_sf: P.totalArea(M.areas),
        }),
      }));
    }, 600);
  }

  /** One place every edit funnels through, so nothing can change a value without the bid,
   *  the rail and the draft all catching up. */
  function changed(rerender) {
    pushCells();
    paintBid();
    paintRail();
    saveSoon();
    if (rerender) renderPanel();
  }

  // ── the rail ────────────────────────────────────────────────────────────────
  function paintRail() {
    var st = P.stepStatus(M);
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

  function areasPanel() {
    var html = M.areas.map(function (a, i) {
      var sys = P.systemByValue(M.system);
      return '<div class="area"><div class="area-h">' +
        '<span class="tag">AREA ' + (i + 1) + '</span>' +
        '<span class="area-sub">' + esc(P.fmtSf(a.sf || 0)) + '</span>' +
        (M.areas.length > 1
          ? '<button class="x" data-del-area="' + i + '" title="Remove this area">✕</button>'
          : '') +
        '</div><div class="grid">' +
        '<div class="f"><label>Area name <span class="unit">text</span></label>' +
        '<input data-area="' + i + '" data-k="name" value="' + esc(a.name || "") + '">' +
        '<p class="hint">Yours, for reading the bid later. Not printed.</p></div>' +
        '<div class="f"><label>Floor area <span class="unit">SF</span>' +
        (i === 0 ? '<span class="cell">' + P.CELLS.area + '</span>' : '') + '</label>' +
        '<input class="n" data-area="' + i + '" data-k="sf" value="' + esc(a.sf || "") + '">' +
        '<p class="hint">' + (i === 0
          ? 'Every area adds into this one cell — the sheet prices one figure.'
          : 'Adds to the total measured area.') + '</p></div>' +
        '</div></div>';
    }).join("");

    html += '<button class="addbtn" data-add-area="1">+ Add another area</button>';
    html += '<div class="grid" style="margin-top:18px">' +
      '<div class="f"><label>Polish system <span class="cell">' + P.CELLS.system +
      '</span></label><select data-m="system">' +
      P.SYSTEMS.map(function (s) {
        return '<option value="' + esc(s.value) + '"' +
          (s.value === M.system ? " selected" : "") + '>' + esc(s.label) + '</option>';
      }).join("") +
      '</select><p class="hint">One system per bid — the worksheet has one selector, and every' +
      ' rate lookup keys off it.</p></div>' +
      '<div class="f"><label>Tooling <span class="cell">' + P.CELLS.tooling +
      '</span></label><select data-m="tooling">' +
      P.TOOLINGS.map(function (t) {
        return '<option value="' + esc(t.value) + '"' +
          (t.value === M.tooling ? " selected" : "") + '>' + esc(t.label) + '</option>';
      }).join("") + '</select></div></div>' +
      '<p class="cap">Total measured area <b>' + esc(P.fmtSf(P.totalArea(M.areas))) + '</b>.</p>';

    return shell("What are we polishing?",
      "Area and system. Everything downstream is priced off these numbers.", html);
  }

  function conditionsPanel() {
    var html = P.CONDITIONS.map(function (c) {
      var on = !!M.conditions[c.key];
      return '<div class="sw' + (on ? " on" : "") + '" data-cond="' + esc(c.key) + '">' +
        '<span class="track"></span><span><span class="t">' + esc(c.label) + '</span>' +
        '<span class="c">' + esc(c.why) + '</span></span>' +
        '<span class="cell">' + esc(c.cell) + '</span></div>';
    }).join("");
    return shell("Job conditions", "The five things that move the price. Each says what it does.",
      html);
  }

  /** A worksheet cell the estimator may type into, OR the value the worksheet works out itself.
   *
   *  The difference matters more than it looks. A derived cell holds a FORMULA — B20 is "=E18",
   *  so the densifier quantity follows the area on its own. Rendering it as an input invites a
   *  number that overwrites the formula, in the download as well as on screen, and the line
   *  stops tracking the area for good.
   *
   *  So a derived cell is shown, never offered: the computed figure, dimmed, with the formula in
   *  its tooltip so the estimator can see WHY it says what it says and which field to change to
   *  move it. */
  function fmtCell(v) {
    if (v == null || v === "") return "—";
    if (typeof v === "number") {
      return P.num(v).toLocaleString("en-US",
        { maximumFractionDigits: Math.abs(v) < 10 ? 2 : 0 });
    }
    return String(v);
  }

  function derivedCell(addr) {
    var ov = overrideFor(addr);
    if (ov !== null) {
      // Somebody typed over the formula in Estimate Review. Show THEIR number - it is what the
      // bid is built from - and mark it, so the figure is not mistaken for the worksheet's own.
      return '<span class="overridden" title="' + esc(
        addr + " was set by hand to " + ov + ", replacing " + P.DERIVED[addr] +
        ". Clear it in Estimate Review to go back to the worksheet’s own figure."
      ) + '">' + esc(fmtCell(ov)) + ' <span class="flag">⚠</span></span>';
    }
    return '<span class="derived" title="' + esc(addr + "  " + P.DERIVED[addr]) +
      '">' + esc(fmtCell(read(addr))) + '</span>';
  }

  function qtyOrCostCell(addr, row, k, value) {
    if (P.isDerived(addr)) return derivedCell(addr);
    return '<input class="n" data-mat="' + row + '" data-k="' + k + '" value="' +
      esc(value == null ? "" : value) + '">';
  }

  function materialsPanel() {
    var rows = "";
    var lastGroup = null;
    P.MATERIAL_LINES.forEach(function (l) {
      if (l.group !== lastGroup) {
        rows += '<tr class="head-row"><td class="rowcell"></td><td colspan="4">' +
          esc(l.group) + '</td></tr>';
        lastGroup = l.group;
      }
      var m = M.materials[l.row] || {};
      var d = read("D" + l.row);
      rows += '<tr><td class="rowcell">' + l.row + '</td><td>' + esc(l.label) + '</td>' +
        '<td class="r">' + qtyOrCostCell("B" + l.row, l.row, "qty", m.qty) + '</td>' +
        '<td class="r">' + qtyOrCostCell("C" + l.row, l.row, "cost", m.cost) + '</td>' +
        '<td class="r calc">' + (d == null ? "" : Math.round(d).toLocaleString()) + '</td></tr>';
    });

    M.added.forEach(function (a, i) {
      var row = P.slotForAdded(i);
      var d = row == null ? null : read("D" + row);
      rows += '<tr class="added"><td class="rowcell">' + (row == null ? "—" : row) + '</td>' +
        '<td><input data-add-line="' + i + '" data-k="name" value="' + esc(a.name || "") + '"> ' +
        '<span class="flag" title="Your own line. It writes into a spare worksheet row, so it ' +
        'bills like any other material.">⚠</span>' +
        (row == null ? ' <b style="color:var(--warn)">no room in the worksheet</b>' : '') +
        '</td>' +
        '<td class="r"><input class="n" data-add-line="' + i + '" data-k="qty" value="' +
        esc(a.qty == null ? "" : a.qty) + '"></td>' +
        '<td class="r"><input class="n" data-add-line="' + i + '" data-k="cost" value="' +
        esc(a.cost == null ? "" : a.cost) + '"></td>' +
        '<td class="r calc">' + (d == null ? "" : Math.round(d).toLocaleString()) + '</td>' +
        '</tr>';
    });

    var sub = read(P.CELLS.material_total);
    rows += '<tr class="sum-row"><td></td><td>Material subtotal</td><td></td>' +
      '<td class="r rowcell">' + P.CELLS.material_total + '</td><td class="r">' +
      (sub == null ? "" : Math.round(sub).toLocaleString()) + '</td></tr>';

    var left = P.slotsLeft(M.added.length);
    var html = '<table><thead><tr><th style="width:34px"></th><th>Item</th>' +
      '<th class="r" style="width:104px">Quantity</th>' +
      '<th class="r" style="width:104px">Cost each</th>' +
      '<th class="r" style="width:104px">Line total</th></tr></thead><tbody>' + rows +
      '</tbody></table>' +
      '<button class="addbtn" data-add-line-new="1"' + (left ? "" : " disabled") + '>' +
      (left ? "+ Add your own material line" : "No spare worksheet rows left") + '</button>' +
      '<p class="cap">' + left + ' spare worksheet row' + (left === 1 ? "" : "s") +
      ' left. Your lines total into <b>' + P.CELLS.material_total +
      '</b> like every other material, so the bid and the file agree.</p>';

    return shell("Materials",
      "Quantity × cost each. The row number is where it lands in the worksheet.", html);
  }

  function labourPanel() {
    var rows = P.LABOUR_LINES.map(function (l) {
      var v = M.labour[l.key] || {};
      var d = read("D" + l.crew.replace(/\D/g, ""));
      var fld = function (addr, k, val) {
        if (P.isDerived(addr)) return derivedCell(addr);
        return '<input class="n" data-lab="' + esc(l.key) + '" data-k="' + k + '" value="' +
          esc(val == null ? "" : val) + '">';
      };
      return '<tr><td>' + esc(l.label) + ' <span class="rowcell">' + esc(l.crew) + '</span></td>' +
        '<td class="r">' + fld(l.crew, "crew", v.crew) + '</td>' +
        '<td class="r">' + fld(l.days, "days", v.days) + '</td>' +
        '<td class="r">' + fld(l.rate, "rate", v.rate) + '</td>' +
        '<td class="r calc">' + (d == null ? "" : Math.round(d).toLocaleString()) + '</td></tr>';
    }).join("");
    var tot = read(P.CELLS.labour_total);
    rows += '<tr class="sum-row"><td>Labour total</td><td></td><td></td>' +
      '<td class="r rowcell">' + P.CELLS.labour_total + '</td><td class="r">' +
      (tot == null ? "" : Math.round(tot).toLocaleString()) + '</td></tr>';

    var pw = M.conditions.prevailing_wage;
    return shell("Crew and days",
      "Change what's wrong. The worksheet's own heuristic fills what you leave blank.",
      '<table><thead><tr><th>Task</th><th class="r" style="width:90px">Guys</th>' +
      '<th class="r" style="width:90px">Days</th>' +
      '<th class="r" style="width:104px">Rate / day</th>' +
      '<th class="r" style="width:104px">Cost</th></tr></thead><tbody>' + rows + '</tbody></table>' +
      '<p class="cap">Prevailing wage is <b>' + (pw ? "on" : "off") + '</b>, so these are ' +
      (pw ? "prevailing" : "standard") + ' rates. Change it in step 2.</p>');
  }

  function addsPanel() {
    var html = '<div class="grid">' + P.ADDS.map(function (a) {
      var v = M.adds[a.key];
      var k = read(a.cell.replace("J", "K"));
      // Ram board and joint filler follow B35; the two coves follow E19. The worksheet already
      // knows the quantity, so showing an empty box beside it would be asking for a number that
      // has an answer — and any answer typed would cut the link.
      var derived = P.isDerived(a.cell);
      var field = derived
        ? '<div class="derived-box">' + derivedCell(a.cell) + '</div>'
        : '<input class="n" data-add="' + esc(a.key) + '" value="' + esc(v == null ? "" : v) + '">';
      var hint = derived
        ? "Follows the area. Change the area in step 1."
        : (k ? "<b>" + esc(P.fmtMoney(k)) + "</b> at this quantity"
             : "Leave at zero if the job has none.");
      return '<div class="f"><label>' + esc(a.label) + ' <span class="unit">' + esc(a.unit) +
        '</span><span class="cell">' + esc(a.cell) + '</span></label>' + field +
        '<p class="hint">' + hint + '</p></div>';
    }).join("") + '</div>';
    return shell("Standard adds",
      "Enter a quantity and it prices itself off the worksheet's rate bands.",
      html + '<p class="cap">Rates step by quantity, so the per-unit price changes as you type.' +
      ' Zero means the add is off.</p>');
  }

  function optionsPanel() {
    var total = read(P.CELLS.total);
    var html = P.OPTIONS.map(function (o) {
      var on = !!M.options[o.key];
      var rate = read(o.rateCell);
      var add = read(o.addCell);
      return '<div class="opt" data-opt="' + esc(o.key) + '">' +
        '<span class="track' + '"' + (on ? ' style="background:var(--red);border-color:transparent"' : '') +
        '></span>' +
        '<span><span class="nm">' + esc(o.label) + '</span><span class="rate">' +
        (rate == null ? "" : esc(P.fmtRate(rate)) + "/SF") + '</span></span>' +
        '<span class="adds"><b>' + (add == null ? "—" : "+ " + esc(P.fmtMoney(add))) +
        '</b><span>' + (add != null && total != null
          ? "bid with option " + esc(P.fmtMoney(add + total)) : "") + '</span></span></div>';
    }).join("");
    return shell("Options to quote alongside",
      "Upgrades priced per SF and shown to the customer beside the base bid.",
      html + '<p class="cap">These never change the base bid — the worksheet adds them to it' +
      ' for the customer to choose.</p>');
  }

  function reviewPanel() {
    var b = bid();
    var blk = P.blockers(M);
    var html = "";
    if (blk.length) {
      html += '<div class="blockers"><b>Not finished yet.</b><ul>' +
        blk.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + '</ul></div>';
    }
    var sys = P.systemByValue(M.system);
    html += card("Areas", 0, P.fmtSf(b.area),
      M.areas.filter(function (a) { return a.sf; }).map(function (a) {
        return [a.name || "Unnamed area", P.fmtSf(a.sf)];
      }).concat([["System", sys ? sys.label : "—"]]));
    html += card("Job conditions", 1, "",
      P.CONDITIONS.map(function (c) {
        return [c.label, M.conditions[c.key] ? "Yes" : "No"];
      }));
    html += card("Materials", 2, b.material == null ? "" : P.fmtMoney(b.material),
      [["Lines", String(P.MATERIAL_LINES.length + M.added.length)],
       ["Your own", String(M.added.length)]]);
    html += card("Labour", 3, b.labour == null ? "" : P.fmtMoney(b.labour),
      P.LABOUR_LINES.map(function (l) {
        var v = M.labour[l.key] || {};
        return [l.label, (v.crew || 0) + " × " + (v.days || 0)];
      }));
    var addOn = Object.keys(M.adds).filter(function (k) { return P.num(M.adds[k]) > 0; });
    html += card("Standard adds", 4, "",
      addOn.length ? addOn.map(function (k) {
        var a = P.ADDS.filter(function (x) { return x.key === k; })[0];
        return [a ? a.label : k, M.adds[k] + " " + (a ? a.unit : "")];
      }) : [["None", ""]]);
    var optOn = Object.keys(M.options).filter(function (k) { return M.options[k]; });
    html += card("Options quoted", 5, "",
      optOn.length ? optOn.map(function (k) {
        var o = P.OPTIONS.filter(function (x) { return x.key === k; })[0];
        return [o ? o.label : k, "quoted"];
      }) : [["None", ""]]);
    return shell("Review the bid",
      "Everything on one screen before it becomes a proposal. Any line jumps back to its step.",
      html);
  }

  function card(title, step, amt, pairs) {
    return '<div class="rev"><div class="rev-h">' + esc(title) +
      ' <button data-go="' + step + '">Edit</button>' +
      (amt ? '<span class="amt">' + esc(amt) + '</span>' : '') + '</div>' +
      '<div class="rev-b">' + pairs.map(function (p) {
        return '<div><b>' + esc(p[0]) + '</b><span>' + esc(p[1]) + '</span></div>';
      }).join("") + '</div></div>';
  }

  var PANELS = [areasPanel, conditionsPanel, materialsPanel, labourPanel,
                addsPanel, optionsPanel, reviewPanel];

  function renderPanel() { $("panels").innerHTML = PANELS[at](); }

  // ── events ──────────────────────────────────────────────────────────────────
  // Delegated, because every panel is re-rendered from state rather than mutated in place.
  document.addEventListener("click", function (e) {
    var t = e.target;
    var go_ = t.closest("[data-go]");
    if (go_) { e.preventDefault(); go(parseInt(go_.getAttribute("data-go"), 10)); return; }

    var sw = t.closest("[data-cond]");
    if (sw) {
      var k = sw.getAttribute("data-cond");
      M.conditions[k] = !M.conditions[k];
      changed(true);
      return;
    }
    var opt = t.closest("[data-opt]");
    if (opt) {
      var ok = opt.getAttribute("data-opt");
      M.options[ok] = !M.options[ok];
      changed(true);
      return;
    }
    if (t.closest("[data-add-area]")) { M.areas.push({ name: "", sf: "" }); changed(true); return; }
    var da = t.closest("[data-del-area]");
    if (da) {
      M.areas.splice(parseInt(da.getAttribute("data-del-area"), 10), 1);
      if (!M.areas.length) M.areas.push({ name: "", sf: "" });
      changed(true);
      return;
    }
    if (t.closest("[data-add-line-new]")) {
      if (P.slotsLeft(M.added.length) <= 0) {
        say("The worksheet has no spare material rows left, so there is nowhere for another " +
            "line to bill from. Kyle would need to extend the template.");
        return;
      }
      M.added.push({ name: "", qty: "", cost: "" });
      changed(true);
    }
  });

  document.addEventListener("input", function (e) {
    var el = e.target;
    if (!el.matches || !el.matches("input")) return;
    var k = el.getAttribute("data-k");

    var ai = el.getAttribute("data-area");
    if (ai !== null) { M.areas[+ai][k] = el.value; changed(false); repaintAreaSub(); return; }

    var mi = el.getAttribute("data-mat");
    if (mi !== null) {
      M.materials[mi] = M.materials[mi] || {};
      M.materials[mi][k] = el.value;
      changed(false); repaintCalcs(); return;
    }
    var li = el.getAttribute("data-add-line");
    if (li !== null) {
      M.added[+li] = M.added[+li] || {};
      M.added[+li][k] = el.value;
      changed(false); repaintCalcs(); return;
    }
    var lk = el.getAttribute("data-lab");
    if (lk !== null) {
      M.labour[lk] = M.labour[lk] || {};
      M.labour[lk][k] = el.value;
      changed(false); repaintCalcs(); return;
    }
    var ak = el.getAttribute("data-add");
    if (ak !== null) { M.adds[ak] = el.value; changed(false); return; }
  });

  document.addEventListener("change", function (e) {
    var m = e.target.getAttribute && e.target.getAttribute("data-m");
    if (!m) return;
    M[m] = e.target.value;
    changed(true);
  });

  /** Refresh the computed columns without rebuilding the table — re-rendering mid-keystroke
   *  would move the caret out of the field being typed in. */
  function repaintCalcs() {
    document.querySelectorAll("#panels td.calc").forEach(function (td) {
      var tr = td.closest("tr");
      var rowCell = tr.querySelector(".rowcell");
      var n = rowCell ? parseInt(rowCell.textContent, 10) : NaN;
      if (!isFinite(n)) return;
      var v = read("D" + n);
      td.textContent = v == null ? "" : Math.round(v).toLocaleString();
    });
    var sum = document.querySelector("#panels tr.sum-row td:last-child");
    if (sum) {
      var which = at === 2 ? P.CELLS.material_total : P.CELLS.labour_total;
      var t = read(which);
      sum.textContent = t == null ? "" : Math.round(t).toLocaleString();
    }
  }

  function repaintAreaSub() {
    document.querySelectorAll("#panels .area").forEach(function (el, i) {
      var sub = el.querySelector(".area-sub");
      if (sub) sub.textContent = P.fmtSf((M.areas[i] || {}).sf || 0);
    });
  }

  /** Fill the form from what the workbook already holds.
   *
   *  The template arrives with Kyle's own figures in it - material rates, crew sizes, day rates.
   *  Showing blanks beside a bid computed FROM those figures would misrepresent where the number
   *  came from, and leave the estimator nothing to change. So the page reads the sheet and shows
   *  what is really there.
   *
   *  Only fills what the estimator has not already set: a returning visit must show their work,
   *  not the template's defaults.
   *
   *  A DERIVED CELL IS NEVER HYDRATED. Reading a formula's current result into form state is how
   *  it gets written back as a constant on the next save - the formula is gone, and the line
   *  stops following the area. That is precisely the bug this pass fixes, and hydrate was half
   *  of it: B20 ("=E18") was read as 0 while the area was still loading, then saved as 0.
   */
  function hydrateFromSheet() {
    var raw = function (addr) {
      if (P.isDerived(addr)) return null;       // see above - never freeze a formula
      var v = engine.getValue(P.SHEET, addr);
      return typeof v === "number" ? v : null;
    };
    var blank = function (v) { return v === undefined || v === ""; };

    P.MATERIAL_LINES.forEach(function (l) {
      var m = M.materials[l.row] = M.materials[l.row] || {};
      if (blank(m.qty))  { var q = raw("B" + l.row); if (q !== null) m.qty = q; }
      if (blank(m.cost)) { var c = raw("C" + l.row); if (c !== null) m.cost = c; }
    });
    P.LABOUR_LINES.forEach(function (l) {
      var v = M.labour[l.key] = M.labour[l.key] || {};
      if (blank(v.crew)) { var a = raw(l.crew); if (a !== null) v.crew = a; }
      if (blank(v.days)) { var b = raw(l.days); if (b !== null) v.days = b; }
      if (blank(v.rate)) { var c = raw(l.rate); if (c !== null) v.rate = c; }
    });
    P.ADDS.forEach(function (a) {
      if (blank(M.adds[a.key])) {
        var v = raw(a.cell);
        if (v !== null && v !== 0) M.adds[a.key] = v;
      }
    });
    var sys = engine.getValue(P.SHEET, P.CELLS.system);
    if (typeof sys === "string" && P.systemByValue(sys)) M.system = sys;
    var tool = engine.getValue(P.SHEET, P.CELLS.tooling);
    if (typeof tool === "string" && tool) M.tooling = String(tool).toLowerCase();
  }

  // ── the beta is a sandbox: it never edits a live bid ────────────────────────
  //
  // Hanz, 2026-08-11: "The current polish excel sheet and the beta shuold be two different
  // workflows okay? The BETA is for testing and which means all data from that leads to the
  // 'test' Category of the proposals database." Asked what should happen when somebody opens a
  // REAL project in the beta, he chose: make a test copy, leave the real bid alone. It sits
  // under his standing rule from 2026-08-07: never test against a live Active project.
  //
  // So Kyle opening Nearman Creek here leaves Nearman Creek in Active exactly as it was, and
  // works on "Nearman Creek (beta test)" under Test. He can price one job both ways and compare
  // them, which is the whole reason the beta runs beside the old screen instead of replacing it.
  var BETA_SUFFIX = " (beta test)";

  /** The copy's id is DERIVED from the source's, not minted.
   *
   *  Idempotence is the reason, and there is no other cheap way to get it. Reopening the beta on
   *  the same real project has to find the copy it made last time or it mints a second, third and
   *  fourth; the projects list cannot be searched for it (_build_summaries in backend/drafts.py
   *  selects a fixed set of columns, and a "copy of" field is not one of them); and the obvious
   *  alternative, a pointer written onto the SOURCE, is exactly the write this whole feature
   *  exists to avoid. A derived id needs neither: one GET answers whether the copy exists. It
   *  also reads plainly in the database, which matters when Kyle is looking at two rows for one
   *  job. */
  function sandboxIdFor(id) { return id + "-beta"; }

  /** Recognisable at a glance in the Proposals Database, and it never stacks up: run the logic
   *  twice and the name still ends in ONE " (beta test)". */
  function betaName(name) {
    var n = String(name == null ? "" : name).trim();
    if (!n) return "Untitled" + BETA_SUFFIX;
    return n.slice(-BETA_SUFFIX.length) === BETA_SUFFIX ? n : n + BETA_SUFFIX;
  }

  function draftUrl(id, tail) {
    return TW.resolveApiBase() + "/api/draft/" + encodeURIComponent(id) + (tail || "");
  }

  /** Has anything actually been typed into this draft yet?
   *
   *  __draft_id is not content: it is shared.js's ownership stamp, and shared.js writes a
   *  stamped-EMPTY blob on purpose (initDraftSync's 404 floor, and again when its hydration guard
   *  trips). Counting it would read "nobody has touched this" as "there is work here". Same rule,
   *  and the same reason, as flushEvictedBlob in shared.js. */
  function hasContent(blob) {
    if (!blob) return false;
    return Object.keys(blob).filter(function (k) { return k !== "__draft_id"; }).length > 0;
  }

  /** Ask shared.js to file this project as a test on its FIRST real save, instead of creating the
   *  row here to have something to file.
   *
   *  The sidebar door is a bare /polish-estimate.html with no ?d=, so shared.js has already minted
   *  an id by the time enterSandbox runs, and saving unconditionally filed a nameless "Untitled"
   *  row under Test every time somebody opened the beta to look at it, `created` event and all.
   *  That is the same thing ae23c5d stopped the server doing ("the server stops creating projects
   *  nobody asked for").
   *
   *  Bound to this id ("<id>:1", the format pendingTestIntentFor reads) rather than the bare "1"
   *  that setNewProjectTestIntent writes: an unbound intent lands on whatever project is saved
   *  next, which is how a real customer bid would end up filed as a test. */
  function markNewProjectAsTest(id) {
    try { localStorage.setItem("treadwell.proposal_tool.new_is_test", id + ":1"); } catch (e) {}
  }

  /** A draft's blob, or null when that id has never been saved.
   *
   *  READ ONLY, deliberately: no method, no body. This is the one call that touches the real
   *  project, and it must not be able to change it.
   *
   *  Anything other than 200/404 throws rather than answering. An indeterminate reply read as
   *  "not filed as a test" would copy a project needlessly; read as "filed" it would edit a live
   *  bid, which is the one outcome there is no undoing. The caller stops the page instead. */
  async function loadRow(id) {
    var res = await fetch(draftUrl(id), { headers: TW.authHeaders() });
    if (res.status === 404) return null;
    if (!res.ok) throw new Error("HTTP " + res.status);
    var body = await res.json();
    return (body && body.data) || {};
  }

  /** File a draft under the Projects page's Test tab.
   *
   *  The route is "/test". An earlier pass named it after the handler instead
   *  (api_test_flag_draft), got a silent 405 on every call, and the project sat in Active looking
   *  fine. projects.js has always posted to "/test" and this has to agree with it.
   *
   *  keepalive because the estimator can navigate while this is in flight; a plain fetch is
   *  cancelled on unload, same reason shared.js carries its own saves that way. */
  function fileAsTest(id) {
    return fetch(draftUrl(id, "/test"), {
      method: "POST",
      headers: TW.authHeaders(),
      body: JSON.stringify({ is_test: true }),
      keepalive: true,
    });
  }

  /** Write `blob` under `id`, and file it as a test only once that has actually landed.
   *
   *  Ordering is not stylistic. set_test_flag returns False on a missing draft, so filing before
   *  the first successful save is a silent no-op and the project stays in Active.
   *
   *  And "landed" is not res.ok: api_save_draft catches its own failures and answers 200 with
   *  {"ok": false, "error": ...}, so a save that never happened looks like a success to anyone
   *  checking the status alone.
   *
   *  The flag POST is best-effort on purpose. If it fails the copy still exists and is still safe
   *  to edit (it is not the real bid), and its "(beta test)" name puts it in the Test tab via
   *  the projects-page name heuristic anyway. Refusing to open over that would be worse. */
  async function saveThenFileAsTest(id, blob) {
    var res = await fetch(draftUrl(id), {
      method: "PUT",
      headers: TW.authHeaders(),
      body: JSON.stringify({ data: blob }),
      keepalive: true,
    });
    var body = res.ok ? await res.json().catch(function () { return null; }) : null;
    if (!res.ok || (body && body.ok === false)) {
      throw new Error("save refused: " + ((body && body.error) || res.status));
    }
    await fileAsTest(id).catch(function (e) { console.warn("[polish beta] test flag failed", e); });
  }

  /** The source's numbers under a new name, plus the marks that make the copy a copy. */
  function buildCopy(srcData, srcId) {
    var blob = Object.assign({}, srcData);
    // Server-owned (_SERVER_OWNED_KEYS in backend/drafts.py). is_test especially: the source may
    // carry `false`, meaning a human said "this IS a real bid", and this page PUTs the whole blob
    // on every autosave, so copying that key across would file the copy as a test through /test
    // and then quietly put it back in Active a couple of seconds later.
    delete blob.is_test;
    delete blob.archived;
    delete blob.assigned_estimator;
    delete blob.__draft_id;              // shared.js's ownership stamp; it belongs to the source
    blob.project_name = betaName(srcData.project_name);
    // Paired with the derived id, this is what makes reopening idempotent: a draft that says
    // whose sandbox it is never gets copied again, even if its test flag went missing.
    blob.beta_sandbox_of = srcId;
    blob.beta_sandbox_of_name = srcData.project_name || "";
    return blob;
  }

  /** Move the page, and the address bar, onto `id`, with `blob` as its state.
   *
   *  The URL matters as much as the id. A reload that still said ?d=<the real project> would land
   *  back on the live bid, and the next autosave would write to it.
   *
   *  clearState first so the source's blob is out of localStorage before anything is written: with
   *  it still there and stamped, shared.js refuses the setState below as a foreign write. */
  function adoptDraft(id, blob) {
    TW.clearState();
    try {
      var url = new URL(window.location.href);
      url.searchParams.set("d", id);
      window.history.replaceState({}, "", url);
    } catch (e) {}
    // shared.js keeps the id here for navigations that drop the query string and exports no
    // setter for it; projects.js reaches for the same key when it starts a fresh project.
    try { localStorage.setItem("treadwell.proposal_tool.draft_id", id); } catch (e) {}
    adopt(blob);
    TW.setState(state);
    repointWizardLinks();
  }

  /** shared.js stamps ?d= onto the static wizard links at DOMContentLoaded, which is long before
   *  this page has settled which draft it is on. Left alone, "3 · Proposal" walks the estimator
   *  straight back onto the real bid. */
  function repointWizardLinks() {
    var id = TW.getDraftId();
    if (!id) return;
    document.querySelectorAll("a[href]").forEach(function (a) {
      try {
        var u = new URL(a.getAttribute("href"), location.origin);
        if (u.origin !== location.origin || !u.searchParams.has("d")) return;
        u.searchParams.set("d", id);
        a.setAttribute("href", u.pathname + u.search + u.hash);
      } catch (e) {}
    });
  }

  /** Say so, on screen. Working on a different project than the one clicked is worse than the bug
   *  being fixed if nobody is told. textContent throughout: a project name is not markup. */
  function showCopyNote(srcName, copyName) {
    var el = $("sandbox-note");
    if (!el) return;
    el.textContent = "";
    var ic = document.createElement("span");
    ic.className = "ic";
    ic.textContent = "⧉";
    el.appendChild(ic);
    var p = document.createElement("span");
    p.appendChild(document.createTextNode("You are editing a test copy. Everything here saves to "));
    var b1 = document.createElement("b");
    b1.textContent = copyName;
    p.appendChild(b1);
    p.appendChild(document.createTextNode(" under the Test tab. The real project, "));
    var b2 = document.createElement("b");
    b2.textContent = srcName || "the one you opened";
    p.appendChild(b2);
    p.appendChild(document.createTextNode(", is untouched in Active."));
    el.appendChild(p);
    el.hidden = false;
  }

  /** `pending` = the row does not exist yet, so nothing has been filed yet either. Saying "this
   *  project is filed as a test" over an empty page would be a claim about a row that is not
   *  there. */
  function showDirectNote(pending) {
    var el = $("sandbox-note");
    if (!el) return;
    el.textContent = "";
    var ic = document.createElement("span");
    ic.className = "ic";
    ic.textContent = "⧉";
    el.appendChild(ic);
    var p = document.createElement("span");
    p.textContent = pending
      ? "Nothing has been priced here yet. Whatever you enter is saved as a NEW test project, " +
        "under the Test tab. No real bid is involved."
      : "This project is filed as a test, so the beta is editing it directly. " +
        "No real bid is involved.";
    el.appendChild(p);
    el.hidden = false;
  }

  /** Settle which draft this page may write to, BEFORE it can be typed into.
   *
   *  Returns false when it could not settle that safely, in which case the caller leaves the page
   *  on its loading message. Stopping is the correct failure: the alternative is a beta that
   *  edits a customer's bid because a fetch blipped. */
  async function enterSandbox() {
    var id = TW.getDraftId();
    if (!id) return true;                        // no project at all, nothing to protect

    var row;
    try { row = await loadRow(id); }
    catch (e) {
      $("loading").textContent = "Couldn't check whether this project is filed as a test, so the " +
        "beta stopped rather than risk editing a real bid. Reload to try again.";
      return false;
    }

    // Never saved: this id IS the sandbox, there is nothing to copy, and Hanz asked for
    // everything the beta touches to land under Test. Save it so the row exists, then file it.
    //
    // Only when there is something to save, though. Opening the beta must not CREATE a project:
    // see markNewProjectAsTest, which hands the filing to the first save the estimator earns.
    if (row === null) {
      if (hasContent(state)) {
        try { await saveThenFileAsTest(id, state); }
        catch (e) { console.warn("[polish beta] could not file the new project as a test", e); }
        showDirectNote(false);
      } else {
        markNewProjectAsTest(id);
        showDirectNote(true);
      }
      return true;
    }

    // Already filed as a test, or a copy this page made earlier. Work on it directly: no copy, no
    // rename. This is the normal path once somebody is working in the sandbox.
    //
    // `=== true` exactly, because is_test is a tri-state (see _tribool in backend/drafts.py):
    // `false` is a human saying "this IS a real bid" and absent is nobody having said. Both of
    // those are projects to copy, and a truthiness check would have read absent as filed.
    if (row.is_test === true || row.beta_sandbox_of) {
      showDirectNote(false);
      return true;
    }

    var copyId = sandboxIdFor(id);
    var copy;
    try { copy = await loadRow(copyId); }
    catch (e) {
      $("loading").textContent = "Couldn't check for this project's test copy, so the beta " +
        "stopped rather than risk editing the real bid. Reload to try again.";
      return false;
    }

    if (copy) {
      // Second visit. Reuse the copy AS IT IS: re-seeding it from the source would throw away
      // whatever was priced here last time, which is the comparison the beta exists for.
      if (copy.is_test !== true) {
        fileAsTest(copyId).catch(function (e) { console.warn("[polish beta] refiling failed", e); });
      }
      adoptDraft(copyId, copy);
    } else {
      var blob = buildCopy(row, id);
      try { await saveThenFileAsTest(copyId, blob); }
      catch (e) {
        $("loading").textContent = "Couldn't make the test copy, so the beta stopped rather than " +
          "edit the real project itself. Reload to try again.";
        return false;
      }
      adoptDraft(copyId, blob);
    }
    showCopyNote(row.project_name, state.project_name);
    return true;
  }

  // ── boot ────────────────────────────────────────────────────────────────────
  async function init() {
    try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch (e) {}
    // shared.js is still deciding which draft this page is on (it can even hydrate and reload),
    // and every decision below turns on that id.
    try { await TW.draftReady; } catch (e) {}
    adopt(TW.getState());

    // Before the workbook, before the form, before anything can be typed: whatever happens after
    // this line writes to a test project. A save timer started against the real bid and fired
    // after the switch would be the bug with extra steps.
    if (!(await enterSandbox())) return;

    $("proj-line").textContent = [state.project_name, state.city && state.state
      ? state.city + ", " + state.state : ""].filter(Boolean).join(" · ") || "Untitled project";

    try {
      var r = await fetch("/api/sheets", { headers: TW.authHeaders() });
      sheetNames = (await r.json()).sheets || [];
      if (!sheetNames.length) throw new Error("no sheets returned");
    } catch (err) {
      $("loading").textContent = "Couldn't load the workbook. " + (err.message || "");
      return;
    }

    // EVERY sheet, not just Polish: the polish formulas reference Epoxy! for the whole job
    // header and validation! for the pad and tooling rate bands.
    engine = X.createEngine(sheetNames);

    // Named expressions, or the product blocks resolve to #NAME?. HyperFormula rejects names
    // shaped like a cell reference ("Glaze4"), so those get an alias and loadSheet rewrites the
    // same token in every formula.
    try {
      var nr = await fetch("/api/named-expressions", { headers: TW.authHeaders() });
      var nd = await nr.json();
      (nd.names || []).forEach(function (n) {
        var scopeId = (n.scope && engine.sheetIdByName[n.scope] !== undefined)
          ? engine.sheetIdByName[n.scope] : undefined;
        var reg = n.name;
        try {
          if (!engine.instance.isItPossibleToAddNamedExpression(reg, n.expression, scopeId)) {
            reg = n.name.replace(/(\d+)$/, "_$1");
            if (reg === n.name) reg = n.name + "_n";
            engine.nameAliases[n.name] = reg;
          }
          if (scopeId !== undefined) engine.instance.addNamedExpression(reg, n.expression, scopeId);
          else engine.instance.addNamedExpression(reg, n.expression);
        } catch (e) { delete engine.nameAliases[n.name]; }
      });
    } catch (err) { console.warn("named expressions unavailable", err); }

    await Promise.all(sheetNames.map(async function (name) {
      try {
        var res = await fetch("/api/sheet/" + encodeURIComponent(name),
                              { headers: TW.authHeaders() });
        engine.loadSheet(name, (await res.json()).cells);
      } catch (err) { console.warn("could not load " + name, err); }
    }));

    // Replay what was typed before, then push this page's own state over the top.
    for (var addr in cellValues) {
      var p = addr.split("!");
      if (p.length === 2) engine.setCellValue(p[0], p[1], cellValues[addr]);
    }

    // Seed the area from intake if the estimator has not measured here yet, so the page opens
    // with the number they already gave us rather than a blank.
    if (!P.totalArea(M.areas) && P.num(state.polish_sf) > 0) {
      M.areas[0].sf = P.num(state.polish_sf);
    }
    // If intake had no area but the sheet does, take the sheet's.
    if (!P.totalArea(M.areas)) {
      var sheetArea = engine.getValue(P.SHEET, P.CELLS.area);
      if (typeof sheetArea === "number" && sheetArea > 0) M.areas[0].sf = sheetArea;
    }

    // Read the workbook's own figures into the form BEFORE pushing anything back, or the page
    // overwrites Kyle's rates with blanks. On a real staging project that dropped the bid from
    // $17,431 to $6,194 the instant the page opened.
    hydrateFromSheet();

    $("loading").hidden = true;
    $("main").hidden = false;
    pushCells();
    paintBid();
    paintRail();
    renderPanel();
  }

  init();
})();
