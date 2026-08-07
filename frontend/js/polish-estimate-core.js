// Polish estimating — the pure parts.
//
// WHY THIS FILE EXISTS AT ALL, AND WHAT IT REFUSES TO DO.
//
// The Polish worksheet stays the calculation engine. Nothing here prices anything: it maps form
// state onto worksheet cells, reads computed values back out, and does the small amount of
// arithmetic the SCREEN needs (summing measured areas, allocating an added line to a spare row).
// Every rate, markup and tax stays in the workbook where Kyle maintains it, which is the only
// reason the figure on screen can equal the figure in the downloaded file.
//
// The temptation this file exists to resist is re-implementing the polish maths in JavaScript
// "just for the preview". There is already a Python implementation of polish pricing that
// disagrees with the workbook, and a third opinion would be worse than a second.
//
// UMD so node can test it without a DOM.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.TWPolish = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // ── the worksheet's own vocabulary ──────────────────────────────────────────
  //
  // ONE system per bid, because the sheet has one selector. Q10/R10/V10 all key off F36:
  //   =IF(F36="cream",Q14,IF(F36="S&P",Q15,IF(F36="full",Q16,0)))
  // The strings must match those comparisons exactly, or every rate lookup falls through to
  // its zero branch and the bid comes out impossibly cheap. That is the failure this list
  // prevents, and why the values are not prettified.
  var SYSTEMS = [
    { value: "cream", label: "Cream", rateCell: "Q14", note: "Ground and polished to a cream finish" },
    { value: "S&P",   label: "Salt & Pepper", rateCell: "Q15", note: "Light aggregate exposure" },
    { value: "full",  label: "Full aggregate", rateCell: "Q16", note: "Full stone exposure" },
  ];

  // G36 picks the tooling family, read by R10 alongside F36.
  var TOOLINGS = [
    { value: "traditional", label: "Traditional tooling" },
    { value: "hybrid",      label: "Hybrid pads" },
  ];

  // The sheet stores these as the literal words Yes/No, not booleans.
  var CONDITIONS = [
    { key: "local",     cell: "B4", label: "Local job",
      why: "Under 70 miles. Off means travel and lodging get added." },
    { key: "hard_bid",  cell: "B5", label: "Hard bid",
      why: "Competitive bid. Tightens the margin the sheet applies." },
    { key: "prevailing_wage", cell: "D5", label: "Prevailing wage",
      why: "Raises every labour line to the prevailing rate." },
    { key: "taxable",   cell: "B6", label: "Taxable",
      why: "Adds sales tax. The bid you see already includes it." },
    { key: "remodel_tax", cell: "D6", label: "Remodel tax",
      why: "Occupied remodel. Adds the county remodel rate on top." },
  ];

  // Material lines the template already names. qty -> B, cost -> C, and D=B*C is the
  // worksheet's own formula, summed by D31.
  var MATERIAL_LINES = [
    { row: 17, label: "Patch material",           group: "Patch" },
    { row: 20, label: "Densifier",                group: "Floor" },
    { row: 21, label: "Sealer",                   group: "Floor" },
    { row: 22, label: "Grout compound",           group: "Floor" },
    { row: 25, label: "Dye",                      group: "Dye" },
    { row: 26, label: "Dye (second coat)",        group: "Dye" },
    { row: 29, label: "Joint filler (10 gal kit)", group: "Joint filler" },
  ];

  // Rows whose =B*C formula is live with the inputs left blank, and which SUM(D17:D30) already
  // covers. Four of them, materials only.
  //
  // Rows 19, 24 and 28 look empty too and are NOT here: they are the sub-section headers
  // ("MATERIAL - Floor", "MATERIAL - Dye", "MATERIAL - Joint Filler"). Writing a cost onto one
  // would print money against a heading in Kyle's file. The labour block (37-44) and tooling
  // block (50-54) have every row occupied, so there is nowhere to add there at all.
  var LINE_SLOTS = [18, 23, 27, 30];

  var LABOUR_LINES = [
    { key: "polishing",    crew: "A37", days: "B37", rate: "C37", label: "Polishing" },
    { key: "mockup",       crew: "A40", days: "B40", rate: "C40", label: "Mock-up" },
    { key: "joint_filler", crew: "A44", days: "B44", rate: "C44", label: "Joint filler" },
  ];

  // Standard adds: a quantity in J, the sheet looks the rate up by band into I, K extends it.
  var ADDS = [
    { key: "ram_board",     cell: "J17", label: "Ram board",       unit: "LF" },
    { key: "joint_filler",  cell: "J18", label: "Joint filler",    unit: "LF" },
    { key: "cove_4",        cell: "J19", label: "4″ rubber cove",  unit: "LF" },
    { key: "cove_6",        cell: "J20", label: "6″ rubber cove",  unit: "LF" },
    { key: "stripe_4",      cell: "J21", label: "4″ line striping", unit: "LF" },
    { key: "stripe_6",      cell: "J22", label: "6″ line striping", unit: "LF" },
  ];

  // Options quoted beside the base bid. They never change it — L28:L30 are J + $D$82.
  var OPTIONS = [
    { key: "salt_pepper",    rateCell: "I28", addCell: "J28", label: "Salt & Pepper finish" },
    { key: "standard_sheen", rateCell: "I29", addCell: "J29", label: "Standard sheen" },
    { key: "dye",            rateCell: "I30", addCell: "J30", label: "Dye" },
  ];

  var CELLS = {
    area:    "E18",   // the ONE polish area. Every rate band and pad lookup keys off it.
    system:  "F36",
    tooling: "G36",
    material_total: "D31",
    labour_total:   "D45",
    tooling_total:  "D55",
    total:          "D82",   // the bid. NOT D88 — that is the Epoxy tab's total.
    per_sf:         "C82",
  };

  var SHEET = "Polish";

  // ── small helpers ───────────────────────────────────────────────────────────
  function num(v) {
    if (typeof v === "number") return isFinite(v) ? v : 0;
    if (v === null || v === undefined) return 0;
    var n = parseFloat(String(v).replace(/[$,\s]/g, ""));
    return isFinite(n) ? n : 0;
  }

  function yesNo(v) { return v ? "Yes" : "No"; }

  /** Total measured area. Several areas are a MEASUREMENT — the sheet prices one system, so
   *  they sum into the single area cell rather than pricing separately. */
  function totalArea(areas) {
    return (areas || []).reduce(function (t, a) { return t + num(a && a.sf); }, 0);
  }

  /** Which spare worksheet row an added line goes in, or null when there is no room.
   *  Returning null rather than throwing is deliberate: the page shows "no room left" and
   *  keeps the typed line on screen instead of losing it. */
  function slotForAdded(index) {
    return (index >= 0 && index < LINE_SLOTS.length) ? LINE_SLOTS[index] : null;
  }

  function slotsLeft(addedCount) {
    return Math.max(0, LINE_SLOTS.length - Math.max(0, addedCount || 0));
  }

  function systemByValue(v) {
    for (var i = 0; i < SYSTEMS.length; i++) if (SYSTEMS[i].value === v) return SYSTEMS[i];
    return null;
  }

  /** Every cell this form writes, as {"Polish!E18": 12500, …}.
   *
   *  Blank is `null`, never `""`. Excel ranks any text above any number, so `"" > 149000` is
   *  true and a blank string silently corrupts the sheet's comparisons — a lesson already paid
   *  for in xl-core's loadSheet. */
  function cellWrites(state) {
    state = state || {};
    var out = {};
    var put = function (addr, v) { out[SHEET + "!" + addr] = v; };

    // A FIELD LEFT BLANK MEANS "LEAVE THE SHEET ALONE", NOT "CLEAR IT".
    //
    // The template arrives with Kyle's own figures already in it - the material rates in C20,
    // C21, C29 and the rest. Writing null for every field nobody had typed wiped them, and the
    // bid on a real staging project fell from $17,431 to $6,194 the moment the page opened.
    // Caught in a browser; every unit test passed, because they all fed it a POPULATED model.
    //
    // So putIf only writes a value the estimator actually supplied. To zero something
    // deliberately, type 0 - a real value, and it does get written.
    var putIf = function (addr, v) {
      if (v === "" || v === null || v === undefined) return;
      put(addr, num(v));
    };

    put(CELLS.area, totalArea(state.areas) || null);
    if (systemByValue(state.system)) put(CELLS.system, state.system);
    if (state.tooling) put(CELLS.tooling, state.tooling);

    CONDITIONS.forEach(function (c) { put(c.cell, yesNo((state.conditions || {})[c.key])); });

    MATERIAL_LINES.forEach(function (l) {
      var m = (state.materials || {})[l.row] || {};
      putIf("B" + l.row, m.qty);
      putIf("C" + l.row, m.cost);
    });

    // Added lines take the spare rows in order: description into A, quantity into B, rate into
    // C, and the sheet's own =B*C bills it through D31.
    (state.added || []).forEach(function (line, i) {
      var row = slotForAdded(i);
      if (row === null) return;                 // over capacity; the page says so
      if (line && line.name) put("A" + row, String(line.name));
      putIf("B" + row, line && line.qty);
      putIf("C" + row, line && line.cost);
    });

    LABOUR_LINES.forEach(function (l) {
      var v = (state.labour || {})[l.key] || {};
      putIf(l.crew, v.crew);
      putIf(l.days, v.days);
      putIf(l.rate, v.rate);
    });

    ADDS.forEach(function (a) {
      putIf(a.cell, (state.adds || {})[a.key]);
    });

    return out;
  }

  /** Per-sub-step state for the rail: "ok", "att" (needs a look), or "" (untouched).
   *  Drives the ticks and amber rings, so an estimator can see what is still outstanding
   *  without opening every step. */
  function stepStatus(state) {
    state = state || {};
    var area = totalArea(state.areas);
    var mats = state.materials || {};
    var anyMaterial = Object.keys(mats).some(function (r) { return num(mats[r].qty) > 0; });
    var lab = state.labour || {};
    var anyLabour = LABOUR_LINES.some(function (l) {
      return num((lab[l.key] || {}).crew) > 0 && num((lab[l.key] || {}).days) > 0;
    });
    var adds = state.adds || {};
    var anyAdd = Object.keys(adds).some(function (k) { return num(adds[k]) > 0; });
    var anyOption = Object.keys(state.options || {}).some(function (k) { return state.options[k]; });

    return {
      areas: area > 0 ? "ok" : "att",             // nothing else can be priced without it
      conditions: "ok",                            // every flag has a valid default
      materials: anyMaterial ? "ok" : "att",
      labour: anyLabour ? "ok" : "att",
      adds: anyAdd ? "ok" : "",                    // legitimately empty on most jobs
      options: anyOption ? "ok" : "",
      review: (area > 0 && anyMaterial && anyLabour) ? "ok" : "",
    };
  }

  /** What is stopping this bid from being finished. Empty array = ready. */
  function blockers(state) {
    var out = [];
    if (totalArea(state && state.areas) <= 0) out.push("No floor area yet, so nothing can be priced.");
    if (!systemByValue((state || {}).system)) out.push("Pick the polish system.");
    var st = stepStatus(state);
    if (st.labour === "att") out.push("Crew and days are still empty.");
    return out;
  }

  function fmtMoney(v) {
    var n = num(v);
    return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  }
  function fmtSf(v) { return num(v).toLocaleString("en-US") + " SF"; }
  function fmtRate(v) {
    return "$" + num(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  return {
    SHEET: SHEET, CELLS: CELLS,
    SYSTEMS: SYSTEMS, TOOLINGS: TOOLINGS, CONDITIONS: CONDITIONS,
    MATERIAL_LINES: MATERIAL_LINES, LINE_SLOTS: LINE_SLOTS,
    LABOUR_LINES: LABOUR_LINES, ADDS: ADDS, OPTIONS: OPTIONS,
    num: num, yesNo: yesNo, totalArea: totalArea,
    slotForAdded: slotForAdded, slotsLeft: slotsLeft, systemByValue: systemByValue,
    cellWrites: cellWrites, stepStatus: stepStatus, blockers: blockers,
    fmtMoney: fmtMoney, fmtSf: fmtSf, fmtRate: fmtRate,
  };
});
