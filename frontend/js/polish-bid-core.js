// Polish BID MATHS — pure functions. No DOM, no fetch, no HyperFormula.
// Externalized (CSP: no inline scripts). Do not add inline scripts.
//
// WHERE EVERY NUMBER IN HERE COMES FROM.
//
// Every constant and every step of the chain below is transcribed, cell by cell, from the
// **Polish tab of `backend/templates/estimate_sheet_5.7.xlsx`** — Kyle's own estimate workbook.
// This is not a model of his sheet or an approximation of it; it is his markup column rewritten
// in JavaScript, so the beta screen can price a polish job without loading a 1.2 MB workbook
// into a formula engine.
//
// The chain, in the order the sheet evaluates it, with the cell each line came from:
//
//   D31 material        =ROUNDUP(SUM(D17:D30),0)              the takeoff, rounded up
//   D32 shipping        =ROUNDUP(D31*B32,0)                   B32 = 2%
//   D33 material_total  =SUM(D31:D32)
//   D45 labor           =ROUNDUP(SUM(D37:D44),0)              the labour rows, rounded up
//   D46 escalation      =ROUNDUP((D45*C46),0)                 C46 =IF(D5="Yes",5%,0)  prevailing wage
//   D47 burden          =ROUNDUP((D45+D46)*C47,0)             C47 = 12%
//   D64 sub_total       =ROUNDUP(SUM(D33,D45:D47,D55,D61),0)  + tooling D55 and travel D61, both 0 here
//   B74 sales_tax_pct   =IF($B$6="no",0,0.09475)
//   D74 sales_tax       =ROUNDUP(SUM(D33)*B74,0)              MATERIALS ONLY
//   D77 fees            =ROUNDUP(B77*C77,0)                   B77/C77 are blank, so 0 in the beta
//   B67 gp_pct          =IF(D64<6500,0.52,IF(D64<15000,0.45,IF(D64<22500,0.35,IF(D64<32500,0.32,0.3))))
//   D67 gp              =ROUNDUP(SUM(D64,D74,D77)/(1-B67),0)-ROUNDUP(SUM(D64,D74,D77),0)
//   B68 hard_bid_pct    =IF(B5="yes",IF(D64>=60000,-0.04,IF(B4="yes",IF(D64>=13000,-0.025,0))))
//   D68 hard_bid        =ROUNDUP(SUM(D64,D67)*B68,0)          NEGATIVE — a hard-bid give-back
//   D71 contingency     a typed constant
//   D69 super_pto       =ROUNDUP(SUM(D64:D68,D71,D74,D77)*B69,0)     B69 = 2.7%
//   D70 soft_costs      =(ROUNDUP(SUM(D64:D69,D71,D74,D77)*B70,0))+0 B70 = 16%
//   B75 remodel_pct     =IF(D6="yes",0.1,0)
//   D75 remodel_tax     =ROUNDUP(SUM(D45:D47,D55,D61,D67:D71,D77)*B75,0)  labour + markups, NO materials
//   D76 taxes           =SUM(D74:D75)
//   D78 bond            =ROUNDUP(SUM(D64,D67,D68,D69:D71,D74,D75:D77)*B78,0)   B78 = 0
//   D79 fees_and_bond   =ROUNDUP(SUM(D77:D78),0)
//   D82 total           =SUM(D64,D67:D71,D76,D79)
//   C82 per_sf          =D82/C81, and C81 =B35 =E18, the takeoff area
//
// SIX THINGS WORTH KNOWING BEFORE CHANGING ANY OF IT.
//
// 1. ROUNDUP runs at EVERY step, not once at the end. That is not cosmetic — rounding up the
//    shipping line and then rounding up the sub-total is a different bid from rounding once, and
//    the difference compounds through GP, super/PTO, soft costs and the remodel tax. Kyle's sheet
//    rounds where it rounds; so do we.
//
// 2. ROUNDUP rounds AWAY FROM ZERO. The hard-bid line (D68) is negative, so ROUNDUP takes
//    -1,234.2 to -1,235 — a bigger give-back, not a smaller one. Math.ceil() would round it the
//    wrong way and quietly raise every hard bid.
//
// 3. `SUM(D64:D68,…)` collapses to D64+D67+D68. D65 is EMPTY and D66 holds the TEXT "Totals",
//    and Excel's SUM skips both. Reading that range as five live rows would add the label to the
//    money. Same for `SUM(D64:D69,…)` in the soft-costs line.
//
// 4. Sales tax is charged on MATERIALS ONLY (D74 takes D33), and the remodel tax on the
//    LABOUR SIDE PLUS THE MARKUPS and never on materials (D75 skips D33 deliberately). Getting
//    these two bases the wrong way round produces a plausible total that is thousands out.
//
// 5. B68's inner IF has no else. Excel yields FALSE there, and FALSE sums as 0 — so a hard bid
//    that is neither ≥ $60k nor local-and-≥ $13k gets no adjustment at all.
//
// 6. A day is EIGHT hours: D37 is `=(A37*B37*C37)*IF($E$35="8 hour days",8,10)` and E35 says
//    "8 hour days". Kyle's own screenshot — 3 guys × 5 days × $32.20 = $3,864 — is what pins it.
//
// `backend/tests/test_polish_markup_parity.py` pins every formula string quoted above against the
// real .xlsx, and re-derives every number below in Python. If Kyle edits his workbook, that test
// fails — which is the whole point of it: it is the only thing standing between a template edit
// and a silently wrong bid. Change this file and that pin together, never one without the other.
(function (root, factory) {
  var api = factory();
  root.TWPolishBid = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;   // node, for tests
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  /** A number from anything a person might type or paste. 0 when it isn't one.
   *
   *  Deliberately unlike library-core's num(), which returns null: every caller here is
   *  ARITHMETIC, and one null in the middle of the chain would poison every line below it. An
   *  empty labour row has to cost nothing, not NaN. Tolerates "$1,200" and " 12,500 " because
   *  these values get pasted out of spreadsheets. */
  function num(raw) {
    if (raw === null || raw === undefined || raw === "") return 0;
    if (typeof raw === "number") return isFinite(raw) ? raw : 0;
    if (typeof raw === "boolean") return 0;
    var s = String(raw).replace(/[$,\s]/g, "");
    if (s === "" || !/^-?\d*\.?\d+$/.test(s)) return 0;
    var n = parseFloat(s);
    return isFinite(n) ? n : 0;
  }

  /** Excel's ROUNDUP(n, 0): away from zero, so -1.2 becomes -2.
   *
   *  Float-guarded to twelve significant figures first. 27,500 × 1.10 is 110.00000000000001 in
   *  IEEE-754 and a bare ceil() would buy a whole extra dollar off the back of the error — on
   *  exactly the round numbers an estimator checks by hand. Twelve figures is far finer than any
   *  money on this screen and far coarser than the noise. */
  function roundUp(n) {
    var v = num(n);
    var g = parseFloat(v.toPrecision(12));
    return g >= 0 ? Math.ceil(g) : -Math.ceil(-g);
  }

  /** Whole dollars: "$15,681". Every line of the chain is already an integer (ROUNDUP put it
   *  there), so decimals here would only be float dust. */
  function money(n) {
    var v = num(n);
    var r = Math.round(Math.abs(v));
    return (v < 0 && r !== 0 ? "-$" : "$") + r.toLocaleString("en-US");
  }

  /** Dollars and cents: "$32.20". For the things a person types — an hourly rate, a price per SF
   *  — where the cents are the number. */
  function money2(n) {
    var v = num(n);
    var s = Math.abs(v).toLocaleString("en-US",
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return (v < 0 && parseFloat(s.replace(/,/g, "")) !== 0 ? "-$" : "$") + s;
  }

  /** A rate as a percentage: 0.45 -> "45%", -0.025 -> "-2.5%", 0.09475 -> "9.475%".
   *
   *  Float noise is stripped first (0.027 × 100 is 2.7000000000000006 in IEEE-754), then the
   *  trailing zeros go, so a whole percentage reads as one. Precision is KEPT rather than
   *  rounded to a tidy two places: 9.475% is the Kansas sales-tax rate and 9.5% is a different
   *  bid on a 40,000 SF floor. */
  function pct(n) {
    var v = num(n) * 100;
    var s = parseFloat(v.toPrecision(12)).toFixed(4);
    s = s.replace(/0+$/, "").replace(/\.$/, "");
    return s + "%";
  }

  /** An area for reading: 12500 -> "12,500". */
  function fmtSf(n) {
    return num(n).toLocaleString("en-US", { maximumFractionDigits: 2 });
  }

  // ── the constants, straight off the Polish tab ──────────────────────────────
  /** D37: `=(A37*B37*C37)*IF($E$35="8 hour days",8,10)`, and E35 says "8 hour days". */
  var HOURS_PER_DAY = 8;

  var RATES = {
    SHIPPING: 0.02,       // B32
    ESCALATION: 0.05,     // C46, when prevailing wage applies
    BURDEN: 0.12,         // C47
    SUPER_PTO: 0.027,     // B69
    SOFT_COSTS: 0.16,     // B70
    SALES_TAX: 0.09475,   // B74, when the job is taxable
    BOND: 0,              // B78 — the sheet ships it at zero
    FEES: 0,              // D77 — B77 and C77 are blank, so the line is zero

    /* THE ONE PLACE THIS ENGINE DELIBERATELY DEPARTS FROM KYLE'S SHEET.
     *
     * B75 hardcodes the remodel tax at 10%. That figure is not a real rate anywhere: Kansas
     * charges sales tax on commercial remodel LABOUR at the state rate plus the county portion
     * only, which is 7.975% in Johnson County and lower in most others. The live estimating tool
     * has looked the real rate up per county since 2026-06-02 (see backend/reference_tax.py,
     * pulled from the KS DOR Address Tax Rate Locator), and Hanz's instruction on 2026-08-18 was
     * to do the same here: "please use the real state tax or city tax, DONT USE 10%".
     *
     * So markupChain takes `remodel_rate` as an input. SHEET_REMODEL is kept only so the parity
     * test can pin the sheet's own number and prove the departure is the one we intended rather
     * than drift. Nothing prices from it. */
    SHEET_REMODEL: 0.10,  // B75 — what the workbook says, NOT what this engine charges
    KS_STATE: 0.065       // the floor when nobody has picked a county yet
  };

  /** B67, as bands: [ceiling, rate]. Strictly BELOW the ceiling, and the last band is the floor
   *  for everything above. A `<=` here would move the GP on every job that lands exactly on a
   *  round number, which is most of the ones anybody checks. */
  var GP_BANDS = [[6500, 0.52], [15000, 0.45], [22500, 0.35], [32500, 0.32], [null, 0.30]];

  /** B67 `=IF(D64<6500,0.52,IF(D64<15000,0.45,IF(D64<22500,0.35,IF(D64<32500,0.32,0.3))))` */
  function gpPct(subTotal) {
    var v = num(subTotal);
    for (var i = 0; i < GP_BANDS.length; i++) {
      if (GP_BANDS[i][0] === null || v < GP_BANDS[i][0]) return GP_BANDS[i][1];
    }
    return GP_BANDS[GP_BANDS.length - 1][1];
  }

  /** B68 `=IF(B5="yes",IF(D64>=60000,-0.04,IF(B4="yes",IF(D64>=13000,-0.025,0))))`
   *
   *  B5 is Hard Bid, B4 is Local. Negative on purpose: it is money given back to win a hard bid.
   *  The innermost IF has no else branch, so Excel returns FALSE, which sums as 0 — a hard bid
   *  that is neither big nor local gets no adjustment. */
  function hardBidPct(subTotal, conditions) {
    var c = conditions || {};
    var v = num(subTotal);
    if (!c.hard_bid) return 0;
    if (v >= 60000) return -0.04;
    if (c.local && v >= 13000) return -0.025;
    return 0;
  }

  /** One labour row's cost. D37: guys × days × hourly rate × 8 hours.
   *
   *  Kyle's screenshot: 3 guys × 5 days × $32.20 = $3,864. That figure is what pins the 8. */
  function laborCost(row) {
    row = row || {};
    return num(row.guys) * num(row.days) * num(row.rate) * HOURS_PER_DAY;
  }

  /** The labour rows added up, UNROUNDED. D45 is where the rounding happens
   *  (`=ROUNDUP(SUM(D37:D44),0)`), and markupChain does it — rounding twice would drift. */
  function laborTotal(rows) {
    rows = rows || [];
    var t = 0;
    for (var i = 0; i < rows.length; i++) t += laborCost(rows[i]);
    return t;
  }

  /** The square feet the bid is priced per. LF rows (cove, saw-cut, stripe) measure a different
   *  thing and must not be added to an area — C82 divides the total by the AREA. */
  function takeoffSf(rows) {
    rows = rows || [];
    var t = 0;
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i] || {};
      if (r.unit === "SF") t += num(r.measurement);
    }
    return t;
  }

  /** THE CHAIN. Materials and labour in, a bid out, one key per cell of Kyle's markup column.
   *
   *  `material` is the raw sum of the takeoff assemblies and `labor` the raw sum of the labour
   *  rows — both unrounded, because D31 and D45 are where the sheet rounds them. */
  function markupChain(input) {
    input = input || {};
    var cond = input.conditions || {};
    var sf = num(input.sf);

    // ── materials ──
    var material = roundUp(input.material);                              // D31
    var shipping = roundUp(material * RATES.SHIPPING);                   // D32
    var material_total = material + shipping;                            // D33

    // ── labour ──
    var labor = roundUp(input.labor);                                    // D45
    var escPct = cond.prevailing_wage ? RATES.ESCALATION : 0;            // C46
    var escalation = roundUp(labor * escPct);                            // D46
    var burden = roundUp((labor + escalation) * RATES.BURDEN);           // D47
    var labor_total = labor + escalation + burden;

    // D64. D55 (tooling) and D61 (travel) are in the sheet's range and are 0 in the beta.
    var sub_total = roundUp(material_total + labor + escalation + burden);

    // ── the two taxes' rates, and the fees line, all of which feed the markups below ──
    var sales_tax_pct = cond.taxable ? RATES.SALES_TAX : 0;              // B74
    var sales_tax = roundUp(material_total * sales_tax_pct);             // D74 — MATERIALS ONLY
    var fees = roundUp(RATES.FEES);                                      // D77 — B77×C77, both blank

    // ── markups ──
    var gp_pct = gpPct(sub_total);                                       // B67
    // D67. A margin, not a mark-on: the sheet divides UP to the sell price and subtracts the
    // cost, so 32% GP is 32% OF THE BID, not 32% added to the cost.
    var gp = roundUp((sub_total + sales_tax + fees) / (1 - gp_pct))
           - roundUp(sub_total + sales_tax + fees);
    var hard_bid_pct = hardBidPct(sub_total, cond);                      // B68
    var hard_bid = roundUp((sub_total + gp) * hard_bid_pct);             // D68 — negative
    var contingency = num(input.contingency);                            // D71

    // D69 `=ROUNDUP(SUM(D64:D68,D71,D74,D77)*B69,0)` — D65 empty, D66 the text "Totals".
    var super_pto = roundUp(
      (sub_total + gp + hard_bid + contingency + sales_tax + fees) * RATES.SUPER_PTO);
    // D70 `=(ROUNDUP(SUM(D64:D69,D71,D74,D77)*B70,0))+0` — same collapse, plus super/PTO.
    var soft_costs = roundUp(
      (sub_total + gp + hard_bid + super_pto + contingency + sales_tax + fees) * RATES.SOFT_COSTS);

    // ── the remodel tax, on the labour side and the markups. NEVER on materials. ──
    //
    // The RATE is the county's real one, handed in by the caller from the project's county (see
    // RATES.SHEET_REMODEL for why this is not the sheet's 10%). With the remodel toggle on and no
    // county picked yet, fall back to the Kansas state rate rather than to 10% — a low answer an
    // estimator can correct beats an invented one they might not question.
    // NULL AND ZERO MEAN DIFFERENT THINGS HERE, and conflating them overcharges a whole state.
    // `null`/absent is "nobody has said which county" → stand the state rate up until they do.
    // An explicit `0` is "we know, and it is nothing": Missouri taxes remodel labour as exempt, so
    // a Missouri county has no remodel rate on purpose. Reading that 0 as "unknown" would charge a
    // Missouri job the Kansas rate. Same null-is-not-zero rule as per_unit and per_sf.
    var remodel_pct = 0;                                                 // B75
    if (cond.remodel_tax) {
      var given = input.remodel_rate;
      remodel_pct = (given === null || given === undefined || given === "")
        ? RATES.KS_STATE
        : num(given);
    }
    var remodel_tax = roundUp(
      (labor + escalation + burden + gp + hard_bid + super_pto + soft_costs + contingency + fees)
      * remodel_pct);                                                    // D75
    var taxes = sales_tax + remodel_tax;                                 // D76

    // ── bond, fees ──
    var bond_pct = RATES.BOND;                                           // B78
    // D78. The sheet's range double-counts D74/D75 through D76; kept as written, because B78 is
    // zero and quietly "fixing" his arithmetic is how the two files stop agreeing.
    var bond = roundUp((sub_total + gp + hard_bid + super_pto + soft_costs + contingency
                        + sales_tax + remodel_tax + taxes + fees) * bond_pct);
    var fees_and_bond = roundUp(fees + bond);                            // D79

    var total = sub_total + gp + hard_bid + super_pto + soft_costs       // D82
              + contingency + taxes + fees_and_bond;

    return {
      material: material, shipping: shipping, material_total: material_total,
      labor: labor, escalation: escalation, burden: burden, labor_total: labor_total,
      sub_total: sub_total,
      gp_pct: gp_pct, gp: gp, hard_bid_pct: hard_bid_pct, hard_bid: hard_bid,
      super_pto: super_pto, soft_costs: soft_costs, contingency: contingency,
      sales_tax_pct: sales_tax_pct, sales_tax: sales_tax,
      remodel_pct: remodel_pct, remodel_tax: remodel_tax, taxes: taxes,
      fees: fees, bond: bond, bond_pct: bond_pct, fees_and_bond: fees_and_bond,
      total: total,
      sf: sf,
      // Null, not 0, without an area: 0 would read as "free" rather than "not known yet".
      per_sf: sf > 0 ? total / sf : null
    };
  }

  // ── the model the page holds ────────────────────────────────────────────────
  /** The labour rows the template itself seeds: A37 = 3 guys at C37 = $32.20/hr, the mock-up at
   *  B40 = half a day, and joint filling at C44 = $32.20. Days are left blank on the two an
   *  estimator has to judge. */
  function freshModel() {
    return {
      version: 2,
      takeoff: [{ assembly_id: "", assembly_name: "", measurement: "", unit: "SF" }],
      labor: [
        { id: "polishing", label: "Polishing", guys: 3, days: "", rate: 32.2 },
        { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 32.2 },
        { id: "jointfill", label: "Joint filler", guys: 3, days: "", rate: 32.2 }
      ],
      conditions: { local: true, hard_bid: false, prevailing_wage: false,
                    taxable: true, remodel_tax: false },
      contingency: 0,
      totals: {}
    };
  }

  /** v1 kept its labour under these keys. `crew` was the GUYS COUNT, not a crew cost — reading it
   *  as money would multiply a saved estimate by eight. */
  var V1_LABOUR_KEY = { polishing: "polishing", mockup: "mockup", jointfill: "joint_filler" };

  function isBlank(v) {
    return v === null || v === undefined || (typeof v === "string" && v.replace(/\s/g, "") === "");
  }

  /** True when a field holds a usable number. 0 counts: a labour row at 0 days is a row the
   *  estimator has deliberately switched off, not a half-filled one. */
  function filledIn(v) {
    if (isBlank(v) || typeof v === "boolean") return false;
    if (typeof v === "number") return isFinite(v);
    return /^-?\d*\.?\d+$/.test(String(v).replace(/[$,\s]/g, ""));
  }

  /** Bring any saved model up to v2. Never throws: a draft is whatever was in localStorage or
   *  the drafts table, including something a half-shipped build wrote, and an estimator opening
   *  an old job should get a working screen rather than a blank one. */
  function migrateModel(model) {
    if (!model || typeof model !== "object") return freshModel();
    var fresh = freshModel();

    if (model.version === 2) {
      var out = {
        version: 2,
        takeoff: model.takeoff, labor: model.labor,
        conditions: {}, contingency: model.contingency,
        totals: (model.totals && typeof model.totals === "object") ? model.totals : {}
      };
      if (!(out.takeoff instanceof Array) || !out.takeoff.length) out.takeoff = fresh.takeoff;
      if (!(out.labor instanceof Array) || !out.labor.length) out.labor = fresh.labor;
      var saved = (model.conditions && typeof model.conditions === "object") ? model.conditions : {};
      for (var k in fresh.conditions) {
        if (!fresh.conditions.hasOwnProperty(k)) continue;
        out.conditions[k] = (k in saved) ? !!saved[k] : fresh.conditions[k];
      }
      if (isBlank(out.contingency)) out.contingency = 0;
      return out;
    }

    // v1: named areas, each with an SF figure, and no assemblies at all — materials were typed
    // straight into worksheet rows. There is nothing to map those onto, so the takeoff comes
    // across as measurements waiting for an assembly to be picked, which is what `blockers()`
    // then says out loud.
    if (!model.version && model.areas instanceof Array) {
      var takeoff = [];
      for (var i = 0; i < model.areas.length; i++) {
        var a = model.areas[i] || {};
        takeoff.push({ assembly_id: "", assembly_name: "", measurement: num(a.sf), unit: "SF" });
      }
      if (!takeoff.length) takeoff = fresh.takeoff;

      var labour = (model.labour && typeof model.labour === "object") ? model.labour : {};
      var labor = [];
      for (var j = 0; j < fresh.labor.length; j++) {
        var seed = fresh.labor[j];
        var old = labour[V1_LABOUR_KEY[seed.id]] || {};
        labor.push({
          id: seed.id, label: seed.label,
          guys: num(old.crew) || seed.guys,
          days: isBlank(old.days) ? seed.days : num(old.days),
          rate: num(old.rate) || seed.rate
        });
      }

      var v1cond = (model.conditions && typeof model.conditions === "object") ? model.conditions : {};
      var cond = {};
      for (var c in fresh.conditions) {
        if (!fresh.conditions.hasOwnProperty(c)) continue;
        cond[c] = (c in v1cond) ? !!v1cond[c] : fresh.conditions[c];
      }
      // system / tooling / materials / added / adds / options are dropped on purpose: assemblies
      // replace all six, and carrying half of them forward would price the same material twice.
      return { version: 2, takeoff: takeoff, labor: labor, conditions: cond,
               contingency: 0, totals: {} };
    }

    /* An unversioned blob that is not v1 either, but which STATES something we recognise.
     *
     * This is the shape the beta intake writes on a brand-new project: it owns the five
     * conditions and nothing else, so the first save is `{conditions: {…}}` with no version and
     * no areas. Falling through to `fresh` discarded it — the estimator set prevailing wage on
     * the intake step, and the calculator then priced at standard rates while the intake screen
     * still showed the switch on. Nothing on either page said a word.
     *
     * So: read it as a PARTIAL v2. The branch above already backfills every key it does not
     * state, which is exactly the right treatment for a half-written model. */
    if ((model.conditions && typeof model.conditions === "object")
        || model.takeoff instanceof Array || model.labor instanceof Array
        || !isBlank(model.contingency)) {
      var partial = {};
      for (var p in model) { if (model.hasOwnProperty(p)) partial[p] = model[p]; }
      partial.version = 2;
      return migrateModel(partial);
    }

    return fresh;
  }

  /** What is stopping this model being priced, in plain words. [] when nothing is.
   *
   *  Written for estimators, not for the console: every line names the row it is about, so the
   *  screen can say what to do rather than greying out a button for reasons of its own. */
  function blockers(model) {
    var m = migrateModel(model);
    var out = [];

    var used = 0;
    for (var i = 0; i < m.takeoff.length; i++) {
      var r = m.takeoff[i] || {};
      var measured = num(r.measurement);
      var picked = !!r.assembly_id;
      if (!picked && measured <= 0) continue;          // an untouched row is not a problem
      used += 1;
      if (!picked) out.push("Pick an assembly for takeoff row " + (i + 1));
      else if (measured <= 0) {
        var name = isBlank(r.assembly_name) ? "takeoff row " + (i + 1) : r.assembly_name;
        out.push("Add a measurement for " + name);
      }
    }
    if (!used) out.push("Add at least one takeoff row");

    // Name the boxes that are actually empty. Listing all three at a row where guys and rate are
    // already filled sends the estimator hunting through fields that are fine.
    for (var j = 0; j < m.labor.length; j++) {
      var row = m.labor[j] || {};
      var missing = [];
      if (!filledIn(row.guys)) missing.push("guys");
      if (!filledIn(row.days)) missing.push("days");
      if (!filledIn(row.rate)) missing.push("rate");
      if (missing.length > 0 && missing.length < 3) {
        var which = missing.length === 1 ? missing[0]
          : missing.slice(0, -1).join(", ") + " and " + missing[missing.length - 1];
        out.push("Add the " + which + " for " + (row.label || row.id || ("row " + (j + 1))));
      }
    }

    return out;
  }

  return {
    num: num, roundUp: roundUp,
    money: money, money2: money2, pct: pct, fmtSf: fmtSf,
    HOURS_PER_DAY: HOURS_PER_DAY, RATES: RATES, GP_BANDS: GP_BANDS,
    gpPct: gpPct, hardBidPct: hardBidPct,
    laborCost: laborCost, laborTotal: laborTotal, takeoffSf: takeoffSf,
    markupChain: markupChain,
    freshModel: freshModel, migrateModel: migrateModel, blockers: blockers
  };
});
