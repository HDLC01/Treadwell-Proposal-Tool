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

  var state = TW.getState();

  /** Strip any Polish cell that the worksheet computes for itself.
   *
   *  Refusing to WRITE a derived cell is not enough on its own. Drafts saved by the earlier
   *  build already carry entries like {"Polish!B20": 0} where the template has "=E18", and both
   *  the engine load and the save are a MERGE - so without this the poison outlives the fix and
   *  keeps the material lines pinned at zero on any job already touched.
   *
   *  Dropping the key restores the template's formula, because a cell nobody overrides is
   *  whatever the workbook says it is. */
  function dropDerived(map) {
    var out = {};
    Object.keys(map || {}).forEach(function (k) {
      var m = /^Polish!([A-Z]+\d+)$/.exec(k);
      if (m && P.isDerived(m[1])) return;
      out[k] = map[k];
    });
    return out;
  }

  var cellValues = dropDerived(state.cell_values || {});
  var engine = null;
  var sheetNames = [];
  var at = 0;

  // The page's own model. Kept under one key so it round-trips with the draft and cannot
  // collide with the epoxy page's fields.
  var M = Object.assign({
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
  }, state.polish_estimate || {});

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
      var merged = dropDerived(
        Object.assign({}, TW.getState().cell_values || {}, cellValues));
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
      : '<a class="btn" href="/proposal-review.html">Continue to proposal →</a>';
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
  function derivedCell(addr) {
    var v = read(addr);
    var shown = v == null || v === "" ? "—"
      : (typeof v === "number" ? P.num(v).toLocaleString("en-US",
          { maximumFractionDigits: Math.abs(v) < 10 ? 2 : 0 }) : String(v));
    return '<span class="derived" title="' + esc(addr + "  " + P.DERIVED[addr]) +
      '">' + esc(shown) + '</span>';
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

  // ── boot ────────────────────────────────────────────────────────────────────
  async function init() {
    try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch (e) {}

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
