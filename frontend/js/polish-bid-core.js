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
//   D45 labor           =ROUNDUP(SUM(D37:D44),0)              the labor rows, rounded up
//   D46 escalation      =ROUNDUP((D45*C46),0)                 C46 =IF(D5="Yes",5%,0)  prevailing wage
//   D47 burden          =ROUNDUP((D45+D46)*C47,0)             C47 = 12%
//   D64 sub_total       =ROUNDUP(SUM(D33,D45:D47,D55,D61),0)  + tooling D55 and travel D61, both 0 here
//   B74 sales_tax_pct   =IF($B$6="no",0,0.09475)
//   D74 sales_tax       =ROUNDUP(SUM(D33)*B74,0)              MATERIALS ONLY
//   D77 fees            =ROUNDUP(B77*C77,0)                   B77/C77 are blank, so 0 in the beta
//   B67 gp_pct          =IF(D64<6500,0.52,IF(D64<15000,0.45,IF(D64<22500,0.35,IF(D64<32500,0.32,0.3))))
//   D67 gp              =ROUNDUP(SUM(D64,D74,D77)/(1-B67),0)-ROUNDUP(SUM(D64,D74,D77),0)
//   B68/D68 hard_bid    REMOVED 2026-09-22 -- Hanz: "remove all hard bids from the polish
//                       intake form. And also on the markups." This file no longer models the
//                       give-back at all; the row stays in this comment only as the reason
//                       D69/D70/D75/D78/D82 below are each one D-cell short of Kyle's literal
//                       SUM range, on purpose, everywhere in this file.
//   D71 contingency     a typed constant
//   D69 super_pto       =ROUNDUP(SUM(D64:D68,D71,D74,D77)*B69,0)     B69 = 2.7%
//   D70 soft_costs      =(ROUNDUP(SUM(D64:D69,D71,D74,D77)*B70,0))+0 B70 = 16%
//   B75 remodel_pct     =IF(D6="yes",0.1,0)
//   D75 remodel_tax     =ROUNDUP(SUM(D45:D47,D55,D61,D67:D71,D77)*B75,0)  labor + markups, NO materials
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
//    LABOR SIDE PLUS THE MARKUPS and never on materials (D75 skips D33 deliberately). Getting
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
   *  empty labor row has to cost nothing, not NaN. Tolerates "$1,200" and " 12,500 " because
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
    DYE_PER_SF: 0.14,            // C25 — Dye, a flat rate across the polished area
    JOINT_FILLER_KIT_COST: 500,  // C29 — Joint Filler (10 gal kit), per kit

    /* THE ONE PLACE THIS ENGINE DELIBERATELY DEPARTS FROM KYLE'S SHEET.
     *
     * B75 hardcodes the remodel tax at 10%. That figure is not a real rate anywhere: Kansas
     * charges sales tax on commercial remodel LABOR at the state rate plus the county portion
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

  // NO hardBidPct(). Hanz, 2026-09-22: "remove all hard bids from the polish intake form. And
  // also on the markups" -- confirmed to the Polish beta specifically. This used to be B68
  // `=IF(B5="yes",IF(D64>=60000,-0.04,IF(B4="yes",IF(D64>=13000,-0.025,0))))`, money given back
  // to win a competitive bid; deleted rather than pinned at zero, because leaving a function
  // that only ever returns 0 is a comment claiming a feature that is not there. Kyle's real
  // sheet is untouched and still carries B68/D68 -- this beta simply no longer writes a "Yes"
  // to B5, so his own formula reads it as not-hard-bid, which is the same outcome.

  /** Is this row counted? `enabled` is absent on every row saved before the slider existed and on
   *  every row nobody has switched, and absent means ON -- only an explicit false is off. Shared by
   *  labor rows, takeoff rows and (through M.conditions) the condition cards, so there is one
   *  answer to "does this row count" in the whole estimate. */
  function rowOn(row) {
    return !(row && row.enabled === false);
  }

  /** The markup for the on/off slider, ONE piece used by the estimate's cards and by the Defaults
   *  tab's rows (both pages load this file), so the two cannot look or behave differently.
   *
   *  Returns a span in the page's `.mw-sw` vocabulary. `attr` is the one data- attribute the
   *  caller's delegated handler listens for (e.g. `data-on-lab="2"`); `label` is the words beside
   *  the track. role=switch + aria-checked so a screen reader hears the state. */
  function sliderHtml(on, attr, label, title, cls) {
    var esc = function (s) {
      return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    };
    return '<span class="mw-sw' + (on ? " on" : "") + (cls || "") + '" ' + attr +
      ' role="switch" tabindex="0" aria-checked="' + (on ? "true" : "false") + '"' +
      (title ? ' title="' + esc(title) + '"' : "") + '>' +
      '<span class="track"></span>' + esc(label == null ? "" : label) + '</span>';
  }

  /** One labor row's cost. D37: guys × days × hourly rate × 8 hours.
   *
   *  Kyle's screenshot: 3 guys × 5 days × $32.20 = $3,864. That figure is what pins the 8.
   *
   *  EXCEPT AN HOURS ROW, WHICH IS NOT MULTIPLIED BY THE DAY. Travel is the only one today, and
   *  the sheet is explicit about it: the crew rows read `Guys | Days` and compute
   *  `=(A37*B37*C37)*8`, while Travel (Polish A43/B43) reads `Guys | HOURS` and computes
   *  `=(A44*B44*C44)` with no multiplier at all. Its middle number is already hours, so applying
   *  the 8 would bill a two-hour drive as sixteen.
   *
   *  Keyed on `unit` rather than on `id === "travel"` so the header can be drawn from the same
   *  field, and so a custom "+ Add a labor line" row could be hours-based later without this
   *  function learning another name. Absent `unit` means days, which is every row written before
   *  this existed and every custom row an estimator adds today. */
  function laborCost(row) {
    row = row || {};
    // A ROW SWITCHED OFF ADDS NOTHING (Kyle's on/off slider, 2026-10-05). Zero HERE, at the one
    // function every total goes through, so the figure is skipped in laborTotal BEFORE markupChain
    // rounds the sum -- zeroing after the rounding would drift the bid by up to a dollar.
    if (!rowOn(row)) return 0;
    // A DAY IS 8 HOURS UNLESS THE ROW SAYS 10 (the Labor Calculator's "hours a day", 2026-10-06).
    // Only 8 and 10 are honoured, so a stray value in a saved blob prices as the sheet does.
    var perDay = row.unit === "hours" ? 1 : dayHours(row);
    return num(row.guys) * num(row.days) * num(row.rate) * perDay;
  }

  /** The built-in crew lines the Labor Calculator can configure (the ids freshModel() gives them).
   *  Custom lines are the favorited rows of library_labor; Travel is not here (it is hours-based
   *  and has its own Travel section). */
  var LABOR_CALC_BUILTINS = [
    { id: "polishing", name: "Polishing" },
    { id: "mockup", name: "Mock-up" },
    { id: "jointfill", name: "Joint filler" }
  ];

  /** Hours in this row's working day: 10 when the row says 10, else the sheet's 8. */
  function dayHours(row) {
    return num((row || {}).hours_per_day) === 10 ? 10 : HOURS_PER_DAY;
  }

  /** THE LABOR CALCULATOR (Library -> Labor Calculator), the arithmetic. A line's saved mode
   *  `cfg` -- `{mode, crew, sf_per_day, hours_per_day, guys, days, rate}` -- turned into the
   *  Guys / Days / Hours-a-day / Rate a new bid's line starts with, for a job of `sf` square feet.
   *
   *    sf     guys = crew, days = ceil(sf / sf_per_day)   (blank days when there is no SF yet, or
   *           no production rate: an unknown is blank, never 0 -- 0 would read as "free")
   *    fixed  guys and days as typed
   *
   *  `rate` is the line's own, else the company labor rate `dflt`. Null when `cfg` has no usable
   *  mode, which is "behave as today". ONE DEFINITION: the estimate's seeding and the Calculator's
   *  "Try it" box both call this, so the box shows exactly what a new bid would get. */
  function laborCalcValues(cfg, sf, dflt) {
    if (!cfg || (cfg.mode !== "sf" && cfg.mode !== "fixed")) return null;
    var hpd = num(cfg.hours_per_day) === 10 ? 10 : HOURS_PER_DAY;
    var own = num(cfg.rate);
    var rate = own > 0 ? own : laborRateOrShipped(dflt);
    var guys, days;
    if (cfg.mode === "sf") {
      var per = num(cfg.sf_per_day), area = num(sf);
      guys = num(cfg.crew) > 0 ? num(cfg.crew) : "";
      days = (per > 0 && area > 0) ? Math.ceil(area / per) : "";
    } else {
      guys = num(cfg.guys) > 0 ? num(cfg.guys) : "";
      days = num(cfg.days) > 0 ? num(cfg.days) : "";
    }
    return { guys: guys, days: days, hours_per_day: hpd, rate: rate };
  }

  /** `labor` with each row that has a saved mode filled from it -- NEW BIDS ONLY (the caller's gate
   *  is laborUnstated, the same one that guards every other default). A NEW array of NEW rows.
   *  The values written are also kept on the row as `calc_default`, which is what the estimate's
   *  "Default value: N" warning compares against: once saved, the bid keeps its own numbers and
   *  nothing here ever runs on it again. Travel (an hours row) is never touched. */
  function applyLaborCalc(labor, cfgs, sf, dflt) {
    var out = (labor instanceof Array) ? labor.slice() : [];
    if (!(cfgs instanceof Array)) return out;
    var byId = {};
    cfgs.forEach(function (c) { if (c && c.line_id) byId[String(c.line_id)] = c; });
    for (var i = 0; i < out.length; i++) {
      var r = out[i];
      if (!r || r.unit === "hours" || r.id === "travel") continue;
      var v = laborCalcValues(byId[String(r.id)], sf, dflt);
      if (!v) continue;
      var copy = {};
      for (var k in r) if (Object.prototype.hasOwnProperty.call(r, k)) copy[k] = r[k];
      copy.guys = v.guys; copy.days = v.days; copy.rate = v.rate; copy.hours_per_day = v.hours_per_day;
      copy.calc_default = { guys: v.guys, days: v.days, rate: v.rate, hours_per_day: v.hours_per_day };
      out[i] = copy;
    }
    return out;
  }

  /** What a labor row's four calculator boxes read against their default: the names of the boxes
   *  whose value is not the default the calculator filled. `[]` for a row with no calc_default
   *  (every row today) and for a row still holding its defaults. */
  function laborCalcDiffers(row) {
    var d = row && row.calc_default;
    if (!d) return [];
    var diff = [];
    if (num(row.guys) !== num(d.guys)) diff.push("guys");
    if (num(row.days) !== num(d.days)) diff.push("days");
    if (num(row.rate) !== num(d.rate)) diff.push("rate");
    if (dayHours(row) !== (num(d.hours_per_day) === 10 ? 10 : HOURS_PER_DAY)) diff.push("hours_per_day");
    return diff;
  }

  /** The man-days a travel row is priced against: Σ guys × days over the rows that are NOT travel.
   *
   *  Polish A44 is `=(A37*B37)+(A38*B38)+(A40*B40)+(A42*B42)` — the crew rows' guys×days summed.
   *  So the "Guys" column on a travel row is not a head count at all; it is how many man-days are
   *  driving to the job, which is why the sheet's own screenshot shows 18 there against a 3-guy
   *  crew (3×5 + 3×0.5 + 3×0.5).
   *
   *  Rows with no `days` contribute nothing, so a half-filled crew simply moves the figure as it
   *  gets filled in. */
  function travelManDays(rows) {
    rows = rows || [];
    var t = 0;
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i] || {};
      if (r.unit === "hours") continue;
      // An OFF crew row is not driving anywhere: it drops out of the man-days Travel is priced on.
      if (!rowOn(r)) continue;
      t += num(r.guys) * num(r.days);
    }
    return t;
  }

  /** The labor rows added up, UNROUNDED. D45 is where the rounding happens
   *  (`=ROUNDUP(SUM(D37:D44),0)`), and markupChain does it — rounding twice would drift. */
  function laborTotal(rows) {
    rows = rows || [];
    var t = 0;
    for (var i = 0; i < rows.length; i++) t += laborCost(rows[i]);
    return t;
  }

  /** THE TWO TRAVEL COSTS BESIDE TRAVEL LABOR: LODGING (a night) and PER DIEM (a day). Hanz,
   *  2026-10-05: "separate line for Travel Lodging and Per Diem", priced INSIDE the markups like
   *  Kyle's sheet D61 -- they join the sub-total (D64) that GP, super/PTO and soft costs are taken
   *  on, and are NOT labor (no escalation, no burden). They live on the model as `M.travel`,
   *  `{lodging: line, per_diem: line}`, each `{label, enabled, qty, qty_auto, rate}`, and not as rows
   *  of M.labor, because a labor row is guys x days x rate x 8 and neither of these is.
   *
   *  THE QUANTITY. Nights (and days of food) are the crew's man-days, the way backend/pricing.py
   *  works them out (`nights = labor man-days`, one lodging and one meal charge per man per night).
   *  `qty_auto` follows travelManDays until the estimator types a number; typing is how you leave
   *  auto, and clearing the box is how you come back. An OFF line, or an absent `travel`, is $0.
   *
   *  THE RATES are the Markups -> Global lines `travel_lodging` ($70) and `travel_per_diem` ($45),
   *  copied onto a NEW bid when it opens (applyTravelRates) and never again, so a rate edited later
   *  reaches new bids and leaves saved ones alone. 70 and 45 are Kyle's literals and what stands
   *  when nothing is filed.
   *
   *  BOTH START OFF (Hanz's decision, 2026-10-05): a bid that never leaves town pays nothing for a
   *  hotel, and an old saved bid opened after this shipped is not repriced. */
  var SHIPPED_LODGING_RATE = 70;
  var SHIPPED_PER_DIEM_RATE = 45;
  var TRAVEL_LINE_KEYS = ["lodging", "per_diem"];

  /** The fresh travel block, built each call so no two models share an object. */
  function travelCostsSeed(lodgingRate, perDiemRate) {
    return {
      lodging: { label: "Lodging", enabled: false, qty: "", qty_auto: true,
                 rate: rateOrShipped(lodgingRate, SHIPPED_LODGING_RATE) },
      per_diem: { label: "Per Diem", enabled: false, qty: "", qty_auto: true,
                  rate: rateOrShipped(perDiemRate, SHIPPED_PER_DIEM_RATE) }
    };
  }

  /** A usable positive rate, or the shipped one. Same rule as laborRateOrShipped. */
  function rateOrShipped(rate, shipped) {
    var n = (rate === null || rate === undefined || rate === "") ? NaN : Number(rate);
    return (isFinite(n) && n > 0) ? n : shipped;
  }

  /** What a line is charged for: the typed quantity, or the crew's man-days while it is auto. */
  function travelQty(line, rows) {
    line = line || {};
    if (line.qty_auto === false) return num(line.qty);
    return travelManDays(rows);
  }

  /** One travel line's cost, ROUNDED UP TO THE DOLLAR like pricing.py's D68 (each of lodging and
   *  food is its own ROUNDUP there). An off line is 0. */
  function travelLineCost(line, rows) {
    if (!line || !rowOn(line)) return 0;
    return roundUp(travelQty(line, rows) * num(line.rate));
  }

  /** Both lines and their sum. `travel` may be absent (an old model that never migrated). */
  function travelCosts(travel, rows) {
    var t = travel || {};
    var lodging = travelLineCost(t.lodging, rows);
    var per_diem = travelLineCost(t.per_diem, rows);
    return { lodging: lodging, per_diem: per_diem, total: lodging + per_diem };
  }

  /** The Lodging and Per Diem rates out of GET /api/markup/rules' `rules`, as
   *  `{lodging, per_diem}`, each null when none is filed (or switched off, or not a plain dollar
   *  figure). Null, not the shipped number: the caller decides what nothing-filed means. */
  function travelRatesFromRules(rules) {
    var out = { lodging: null, per_diem: null };
    if (!(rules instanceof Array)) return out;
    var keys = { travel_lodging: "lodging", travel_per_diem: "per_diem" };
    for (var i = 0; i < rules.length; i++) {
      var r = rules[i];
      if (!r || r.layout !== "global" || !keys[r.line_key]) continue;
      if (r.applies === false) continue;
      var m = /^\s*\$?\s*(\d+(?:\.\d+)?)\s*$/.exec(String(r.formula === null ||
        r.formula === undefined ? "" : r.formula));
      if (!m) continue;
      var n = Number(m[1]);
      if (isFinite(n) && n > 0) out[keys[r.line_key]] = n;
    }
    return out;
  }

  /** The two company rates written onto a NEW bid's travel lines. A NEW object; the input is never
   *  touched. A line the estimator has already typed a rate over is not this function's to move --
   *  the caller's gate (a bid nobody has saved) is what keeps that true, and this only fills lines
   *  still on the shipped figure. */
  function applyTravelRates(travel, rates) {
    var out = travelCostsSeed(rates && rates.lodging, rates && rates.per_diem);
    var t = travel || {};
    TRAVEL_LINE_KEYS.forEach(function (k) {
      var keep = t[k];
      if (!keep || typeof keep !== "object") return;
      var shipped = (k === "lodging") ? SHIPPED_LODGING_RATE : SHIPPED_PER_DIEM_RATE;
      var next = {};
      for (var f in keep) if (Object.prototype.hasOwnProperty.call(keep, f)) next[f] = keep[f];
      if (!(isFinite(Number(keep.rate)) && Number(keep.rate) > 0 && Number(keep.rate) !== shipped)) {
        next.rate = out[k].rate;
      }
      out[k] = next;
    });
    return out;
  }

  /** A saved `travel` block read as a full one: both lines, every field. Missing lines come from
   *  the seed (OFF, shipped rates); a line keeps what it was saved with. Never throws. */
  function normalizeTravel(travel) {
    var seed = travelCostsSeed();
    var t = (travel && typeof travel === "object") ? travel : {};
    var out = {};
    TRAVEL_LINE_KEYS.forEach(function (k) {
      var s = seed[k];
      var l = (t[k] && typeof t[k] === "object") ? t[k] : {};
      out[k] = {
        label: isBlank(l.label) ? s.label : String(l.label),
        // Explicit true/false on this block (unlike a labor row, whose absent key means on): the
        // seed is OFF, so "on" has to be written down to survive a save and a reload.
        enabled: l.enabled === true,
        qty: l.qty === undefined || l.qty === null ? "" : l.qty,
        qty_auto: l.qty_auto === false ? false : true,
        rate: (isBlank(l.rate) || !isFinite(Number(l.rate))) ? s.rate : Number(l.rate)
      };
      // Set when the ESTIMATOR flipped the line, so a later distance answer (the 70-mile rule)
      // never overrides a choice somebody made.
      if (l.hand === true) out[k].hand = true;
    });
    return out;
  }

  /** DISTANCE DECIDES "LOCAL" (Kyle 9/18; Hanz, 2026-10-05). The intake "Local job" switch is gone;
   *  the Labor step works the driving miles from the Olathe office to the job address out on the
   *  server (POST /api/distance) and this is what it does with the answer. The model carries it as
   *  `distance: {miles, source, key}`:
   *    miles   a number (0 is a real answer), or null for "unknown";
   *    source  "google" (the server's figure) or "typed" (the estimator's own, which always wins);
   *    key     which address the figure belongs to (distanceKey), so a changed address is noticed.
   *  `conditions.local` stays on the model -- it is still what Polish!B4 / Epoxy!B4 are written from
   *  -- but it is DERIVED now: under 70 miles is local. At 70 or more the three travel lines come
   *  on (Travel Labor by un-graying, Lodging and Per Diem by switching on); under 70 they go gray.
   *
   *  A HAND FLIP WINS. A Lodging / Per Diem line the estimator flipped (`hand`) is never moved by a
   *  distance answer in either direction -- the same rule normalizeTravel's note records.
   *
   *  UNKNOWN IS NOT AN ANSWER. No figure leaves `conditions.local` and the lines exactly as they
   *  were (a new bid: local, all three gray). Nothing here ever guesses a distance. */
  var LOCAL_MILES = 70;

  /** A positive-or-zero finite number, else null. A blank box and "abc" are both unknown. */
  function milesOrNull(v) {
    if (v === null || v === undefined || v === "" || typeof v === "boolean") return null;
    var n = Number(String(v).replace(/[,\s]/g, ""));
    return (isFinite(n) && n >= 0) ? Math.round(n * 10) / 10 : null;
  }

  /** The address a distance belongs to, lower-cased and squeezed -- or "" when the address is too
   *  thin to look up (needs a street AND a city+state or a zip, the same rule the server applies in
   *  distance.clean_address). "" means: do not ask, and say so. */
  function distanceKey(address, city, state, zip) {
    function one(v) { return String(v == null ? "" : v).replace(/\s+/g, " ").trim().toLowerCase(); }
    var a = one(address), c = one(city), s = one(state), z = one(zip);
    if (!a) return "";
    if (!((c && s) || z)) return "";
    return [a, c, s, z].join("|");
  }

  /** A saved `distance` read as a full one, or undefined when there is none. Never throws. */
  function normalizeDistance(d) {
    if (!d || typeof d !== "object") return undefined;
    var out = { miles: milesOrNull(d.miles), source: d.source === "typed" ? "typed" : "google",
                key: typeof d.key === "string" ? d.key : "" };
    // A record with no figure says nothing (a failed lookup is never stored, so it is asked again
    // on the next open -- the key may have been configured since).
    if (out.miles === null) return undefined;
    return out;
  }

  /** Is a job at this many miles a travel job? Unknown is false: it is not asked to be anything. */
  function isFarMiles(miles) {
    var n = milesOrNull(miles);
    return n !== null && n >= LOCAL_MILES;
  }

  /** The model with a distance answer applied, IN PLACE (and returned). `result` is
   *  `{miles, source, key}`; a result with no usable miles records nothing and changes nothing. */
  function applyDistance(model, result) {
    var miles = milesOrNull(result && result.miles);
    if (!model || miles === null) return model;
    model.distance = { miles: miles, source: (result.source === "typed" ? "typed" : "google"),
                       key: String(result.key || "") };
    var far = miles >= LOCAL_MILES;
    if (!model.conditions) model.conditions = {};
    model.conditions.local = !far;
    if (!model.travel) model.travel = normalizeTravel(null);
    TRAVEL_LINE_KEYS.forEach(function (k) {
      var l = model.travel[k];
      if (l && l.hand !== true) l.enabled = far;
    });
    return model;
  }

  /** Back to "unknown": the estimator cleared the miles they had typed. Local again (the shipped
   *  default) and every line the estimator never touched gray again; a hand flip stays. */
  function clearDistance(model) {
    if (!model) return model;
    delete model.distance;
    if (!model.conditions) model.conditions = {};
    model.conditions.local = true;
    if (model.travel) {
      TRAVEL_LINE_KEYS.forEach(function (k) {
        var l = model.travel[k];
        if (l && l.hand !== true) l.enabled = false;
      });
    }
    return model;
  }

  /** The words under the Travel heading: what the estimator is looking at, and what they can do. */
  function distanceNote(model) {
    var d = model && model.distance;
    if (d && milesOrNull(d.miles) !== null) {
      var n = milesOrNull(d.miles);
      var shown = (n % 1 === 0) ? String(n) : n.toFixed(1);
      return shown + " mi from Olathe office" + (d.source === "typed" ? " (typed by you)" : "");
    }
    return "Distance unknown — enter miles";
  }

  /** The square feet the bid is priced per. LF rows (cove, saw-cut, stripe) measure a different
   *  thing and must not be added to an area — C82 divides the total by the AREA. */
  /** THE INTAKE'S SF BOXES, TURNED INTO TAKEOFF ROWS (Hanz, 2026-10-05: "Add SF, seed the takeoff").
   *
   *  Intake asks for System 1 and System 2 Polish SF; the step-2 takeoff is where the price comes
   *  from, so each positive number becomes one row of it. Typed once, priced once.
   *
   *  NEVER OVER A MEASUREMENT. Returns the rows UNCHANGED (same array) when any row already
   *  carries a number, SF or not -- an LF row with 900 on it is somebody's work too. Otherwise a
   *  blank SF row (the one freshModel hands out) takes the first value and the rest are appended
   *  as new blank-assembly SF rows. A system-2-only job seeds one row from system 2: the number
   *  is the estimator's, and which box it was typed in changes nothing the takeoff prices.
   *
   *  Lives here, not in js/polish-estimate.js, because the harness for that file lifts init() by
   *  name and a new local function it calls is a ReferenceError in every scenario. */
  function seedTakeoffSf(rows, sf1, sf2) {
    rows = Array.isArray(rows) ? rows : [];
    for (var i = 0; i < rows.length; i++) {
      if (num((rows[i] || {}).measurement) > 0) return rows;
    }
    var vals = [num(sf1), num(sf2)].filter(function (v) { return v > 0; });
    if (!vals.length) return rows;
    var blank = -1;
    for (var j = 0; j < rows.length; j++) {
      var r = rows[j] || {};
      if ((r.unit === "SF" || !r.unit) && !r.assembly_id) { blank = j; break; }
    }
    vals.forEach(function (v, k) {
      if (k === 0 && blank >= 0) {
        rows[blank].measurement = v;
        rows[blank].unit = "SF";
      } else {
        rows.push({ assembly_id: "", assembly_name: "", measurement: v, unit: "SF" });
      }
    });
    return rows;
  }

  /** THE DEFAULTS, LOADED INTO A NEW ESTIMATE'S TAKEOFF (Hanz, 2026-10-05: "each default becomes its
   *  own Takeoff row, measured with the intake polish SF").
   *
   *  `asms` / `items` are the library catalogs. A row seeds when it is a favorite (the Defaults tab
   *  list) AND applies to Polish (default_work_types, empty = every tab) -- the same two tests the
   *  Defaults tab draws its Takeoff lists with. Assemblies first, then materials, the order the tab
   *  shows them. The three reserved materials (`reserved` ids: dye, joint filler kit, remove-
   *  existing) are NOT seeded here: they are the condition cards, which have their own defaults.
   *
   *  HOW IT COMBINES WITH seedTakeoffSf WITHOUT COUNTING THE FLOOR TWICE. takeoffSf adds every SF
   *  row, so ten defaults each measured with the intake 8,250 SF would read as 82,500 SF of floor,
   *  and polish_sf, the price per SF and every area-driven condition would follow it. They are all
   *  the SAME floor, so:
   *    - ONE row carries the area: the first ENABLED SF-unit default. Counted as always.
   *    - every other default carries the same number for pricing but is marked `same_floor`, which
   *      takeoffSf skips. The marker is data on the row, so it survives save and reload.
   *    - no enabled SF default (all off, all LF, or the library has none): the intake boxes seed
   *      plain area rows exactly as seedTakeoffSf always did (System 1 / System 2, one row each),
   *      appended after the defaults, and every default is marked `same_floor`.
   *  With both intake systems filled, the defaults take the SUM (the whole floor each default
   *  covers) and the carrier counts it once.
   *
   *  A default switched OFF (default_on === false) is kept, grayed (`enabled:false`), measured too
   *  so flipping it on needs nothing typed; rowOn already gives it $0 and leaves it out of area.
   *  An LF assembly is never measured with square feet: its measurement stays blank for the
   *  estimator -- the blocker names it -- rather than a guess. Coverage is NOT copied onto a row:
   *  a blank coverage already follows the library's current value (covPlaceholder), which is how
   *  a later library change reaches new bids and an untouched row never freezes a stale number.
   *
   *  NEVER OVER WORK: unchanged rows are returned (same array) when any row already carries a
   *  pick or a measurement. With no defaults it IS seedTakeoffSf. Callers gate "new bid" on the
   *  saved blob (conditionsUnstated); this function is only the combination rule. */
  function seedDefaultTakeoff(rows, asms, items, reserved, sf1, sf2) {
    rows = Array.isArray(rows) ? rows : [];
    for (var i = 0; i < rows.length; i++) {
      var q = rows[i] || {};
      if (num(q.measurement) > 0 || q.assembly_id || q.item_id) return rows;
    }
    var applies = function (r) {
      var l = r && r.default_work_types;
      return !l || !l.length || l.indexOf("polish") !== -1;
    };
    var picks = [];
    (Array.isArray(asms) ? asms : []).forEach(function (a) {
      if (a && a.favorite && applies(a)) picks.push({ kind: "asm", row: a });
    });
    (Array.isArray(items) ? items : []).forEach(function (it) {
      if (!it || !it.favorite || !applies(it)) return;
      if ((reserved || []).indexOf(it.id) !== -1) return;
      picks.push({ kind: "item", row: it });
    });
    if (!picks.length) return seedTakeoffSf(rows, sf1, sf2);

    var total = (num(sf1) > 0 ? num(sf1) : 0) + (num(sf2) > 0 ? num(sf2) : 0);
    var out = [];
    var carried = false;
    picks.forEach(function (p) {
      var on = p.row.default_on !== false;
      var unit = "SF";
      if (p.kind === "asm") {
        var u = String(p.row.unit == null ? "" : p.row.unit).toUpperCase();
        if (u === "LF") unit = "LF";
      }
      var r;
      if (p.kind === "asm") {
        r = { assembly_id: p.row.id, assembly_name: p.row.name, measurement: "", unit: unit };
      } else {
        r = { kind: "item", item_id: p.row.id, item_name: p.row.name, coverage: "",
              measurement: "", unit: "SF" };
      }
      if (unit === "SF" && total > 0) {
        r.measurement = total;
        if (on && !carried) carried = true;
        else r.same_floor = true;
      }
      if (!on) r.enabled = false;
      out.push(r);
    });
    if (!carried && total > 0) {
      seedTakeoffSf([], sf1, sf2).forEach(function (r) { out.push(r); });
    }
    return out;
  }

  /** Type `value` into row `i`'s measurement, keeping the same-floor rows honest.
   *  - A `same_floor` row the estimator types its OWN number into stops sharing: the marker is
   *    cleared, so takeoffSf counts what it was told rather than ignoring it for good.
   *  - The carrier (an enabled SF row that is not same_floor) moving drags every same_floor row
   *    still holding its old number along, so the rows the default load made as one floor keep
   *    pricing one floor. A same_floor row already set to something else is left alone. */
  function setMeasurement(rows, i, value) {
    var r = rows && rows[i];
    if (!r) return;
    var old = r.measurement;
    r.measurement = value;
    if (r.same_floor) { delete r.same_floor; return; }
    if (r.unit !== "SF" || !rowOn(r)) return;
    for (var k = 0; k < rows.length; k++) {
      var o = rows[k];
      if (k !== i && o && o.same_floor && num(o.measurement) === num(old)) o.measurement = value;
    }
  }

  function takeoffSf(rows) {
    rows = rows || [];
    var t = 0;
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i] || {};
      // An OFF row is out of the area too: the price per SF divides by what the bid actually buys.
      if (r.unit === "SF" && rowOn(r) && !r.same_floor) t += num(r.measurement);
    }
    return t;
  }

  /** THE FLOOR THAT HAS BEEN MEASURED, WHETHER OR NOT THE BID IS BUYING IT RIGHT NOW.
   *
   *  takeoffSf above is the AREA THE BID PRICES: an OFF row is out of it. That is right for the
   *  price per SF and for the area-driven conditions, and wrong as the answer to "has anybody typed
   *  a floor size in here?". Switching OFF the only SF row made takeoffSf 0, so the intake page
   *  unlocked its SF boxes (and its next save wrote whatever they showed over polish_sf), and the
   *  estimate saved polish_sf as 0. THE DECISION (F5, 2026-10-06): the intake lock and the
   *  polish_sf the estimate files key on MEASURED rows, on or off. The slider is a pricing choice;
   *  it does not un-measure the floor.
   *
   *  Counted the way takeoffSf counts (SF rows, a same_floor row not added on top of its carrier),
   *  minus the on/off test. When the carrier itself is off and only same_floor rows remain they
   *  all carry the one floor's number, so the largest of them is the answer. */
  function measuredSf(rows) {
    rows = rows || [];
    var t = 0, same = 0;
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i] || {};
      if (r.unit !== "SF") continue;
      if (r.same_floor) { if (num(r.measurement) > same) same = num(r.measurement); }
      else t += num(r.measurement);
    }
    return t > 0 ? t : same;
  }

  /** HOW MANY COATS OF DYE A JOB BUYS: Kyle's Polish tab has TWO "Dye" lines, rows 25 and 26,
   *  both =IF(E25="Yes",E18) at 0.14 a square foot, switched by the one E25 answer. So with dye
   *  on his sheet charges $0.28/SF, and backend/pricing.py (dye_coats 2) always agreed.
   *
   *  THE BETA CHARGED ONE UNTIL 2026-09-30, reading row 25 alone; Hanz, looking at the original
   *  file: make it match Kyle's. The library row `dye` is ONE coat, and dyeCost, condLine in
   *  polish-estimate.js and the workbook writer below all take the count from here. */
  var DYE_COATS = 2;

  /** B25/B26 `=IF(E25="Yes",E18)`, C25/C26 `0.14`, D25/D26 `=B*C` — Kyle's two Dye lines, one
   *  per coat (DYE_COATS). A flat rate across the whole polished area for each coat, charged only
   *  when the condition is on: area x 0.14 x 2, which is D25 + D26 to the bit (doubling is exact).
   *
   *  THE FALLBACK NOW, NOT THE ANSWER (2026-09-30). Dye is a reserved library_items row, id
   *  `dye` (backend/library.py's RESERVED_ITEM_IDS), one coat, and polish-estimate.js prices each
   *  coat through library-core's priceLine off that row, so an admin edits it on the Items tab.
   *  This formula is what stands when the row is not there to read: a database the seed has not
   *  reached. The seed (coverage 1, waste 0, no roundup, $0.14) prices to the cent what this
   *  does, and test_polish_estimate_page.py holds the two together. 0 when the condition is off
   *  or the area is not yet a positive number. */
  function dyeCost(area, on) {
    var a = num(area);
    if (!on || !(a > 0)) return 0;
    return a * RATES.DYE_PER_SF * DYE_COATS;
  }

  /** B29 `=ROUNDUP(IF(E29="yes",(E18/3500),0),0)`, C29 `500`, D29 `=B29*C29` — Joint
   *  Filler (10 gal kit). One kit per 3,500 SF of polished area, ROUNDED UP to a whole kit —
   *  this file's own roundUp(), not a second rounding function — charged only when the
   *  condition is on. Same 0-guard as dyeCost above, and THE SAME FALLBACK ROLE: the live price
   *  is the reserved `joint-filler-kit` row (coverage 3500, waste 0, roundup on, $500), which
   *  priceLine turns into exactly this ROUNDUP(area / 3500) × 500 while the seeded values
   *  stand. */
  function jointFillerCost(area, on) {
    var a = num(area);
    if (!on || !(a > 0)) return 0;
    var kits = roundUp(a / 3500);
    return kits * RATES.JOINT_FILLER_KIT_COST;
  }

  /** THE CHAIN. Materials and labor in, a bid out, one key per cell of Kyle's markup column.
   *
   *  `material` is the raw sum of the takeoff assemblies and `labor` the raw sum of the labor
   *  rows — both unrounded, because D31 and D45 are where the sheet rounds them. */
  function markupChain(input) {
    input = input || {};
    var cond = input.conditions || {};
    var sf = num(input.sf);

    // ── materials ──
    var material = roundUp(input.material);                              // D31
    var shipping = roundUp(material * RATES.SHIPPING);                   // D32
    var material_total = material + shipping;                            // D33

    // ── labor ──
    var labor = roundUp(input.labor);                                    // D45
    var escPct = cond.prevailing_wage ? RATES.ESCALATION : 0;            // C46
    var escalation = roundUp(labor * escPct);                            // D46
    var burden = roundUp((labor + escalation) * RATES.BURDEN);           // D47
    var labor_total = labor + escalation + burden;

    // ── travel costs: Lodging + Per Diem (D61). INSIDE the sub-total, so GP's band, super/PTO, soft
    // costs and the remodel tax's markup base all see them, exactly as Kyle's D64 `SUM(...,D61)`
    // does. Not labor: no escalation and no burden. 0 when the caller passes none, which is every
    // caller written before this existed.
    var travel = roundUp(input.travel);                                  // D61

    // D64. D55 (tooling) is in the sheet's range and is 0 in the beta; D61 is the line above.
    var sub_total = roundUp(material_total + labor + escalation + burden + travel);

    // ── the two taxes' rates, and the fees line, all of which feed the markups below ──
    var sales_tax_pct = cond.taxable ? RATES.SALES_TAX : 0;              // B74
    var sales_tax = roundUp(material_total * sales_tax_pct);             // D74 — MATERIALS ONLY
    // D77. The sheet computes this as B77×C77 -- a quantity times a rate -- and ships both blank,
    // so it has always been zero here. It is now a figure the estimator types on the Review step,
    // for the same reason contingency (D71) is: the workbook leaves the cells open, and a line an
    // estimator cannot fill in is one they have to remember to add somewhere else.
    //
    // ONE DOLLAR FIGURE, NOT TWO CELLS. Collapsing B77×C77 into the product they make loses
    // nothing the bid uses -- every formula below reads D77, never its two factors -- and asking
    // for a quantity and a rate would be asking an estimator to decompose a number they already
    // have in hand.
    //
    // IT IS MARKED UP, and that is the sheet's own behaviour rather than a choice made here: D77
    // sits inside GP's base (D67), super/PTO's (D69), soft costs' (D70) and the remodel tax's
    // (D75). A fee typed here therefore grows the bid by more than itself.
    var fees = roundUp(num(input.fees));                                 // D77 -- B77×C77

    // ── markups ──
    var gp_pct = gpPct(sub_total);                                       // B67
    // D67. A margin, not a mark-on: the sheet divides UP to the sell price and subtracts the
    // cost, so 32% GP is 32% OF THE BID, not 32% added to the cost.
    var gp = roundUp((sub_total + sales_tax + fees) / (1 - gp_pct))
           - roundUp(sub_total + sales_tax + fees);
    // NO hard_bid TERM. It was B68/D68 in Kyle's real sheet -- see the note above hardBidPct's
    // old home for why it is gone rather than pinned at zero. Every SUM below is one D-cell
    // short of his literal range for exactly that reason; this file has diverged from his
    // ranges on purpose, and it is the only place that has.
    var contingency = num(input.contingency);                            // D71

    // D69 `=ROUNDUP(SUM(D64:D68,D71,D74,D77)*B69,0)` — D65 empty, D66 the text "Totals", D68 no
    // longer a term this file computes.
    var super_pto = roundUp(
      (sub_total + gp + contingency + sales_tax + fees) * RATES.SUPER_PTO);
    // D70 `=(ROUNDUP(SUM(D64:D69,D71,D74,D77)*B70,0))+0` — same collapse, plus super/PTO.
    var soft_costs = roundUp(
      (sub_total + gp + super_pto + contingency + sales_tax + fees) * RATES.SOFT_COSTS);

    // ── the remodel tax, on the labor side and the markups. NEVER on materials. ──
    //
    // The RATE is the county's real one, handed in by the caller from the project's county (see
    // RATES.SHEET_REMODEL for why this is not the sheet's 10%). With the remodel toggle on and no
    // county picked yet, fall back to the Kansas state rate rather than to 10% — a low answer an
    // estimator can correct beats an invented one they might not question.
    // NULL AND ZERO MEAN DIFFERENT THINGS HERE, and conflating them overcharges a whole state.
    // `null`/absent is "nobody has said which county" → stand the state rate up until they do.
    // An explicit `0` is "we know, and it is nothing": Missouri taxes remodel labor as exempt, so
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
      (labor + escalation + burden + gp + super_pto + soft_costs + contingency + fees)
      * remodel_pct);                                                    // D75
    var taxes = sales_tax + remodel_tax;                                 // D76

    // ── bond, fees ──
    var bond_pct = RATES.BOND;                                           // B78
    // D78. The sheet's range double-counts D74/D75 through D76; kept as written, because B78 is
    // zero and quietly "fixing" his arithmetic is how the two files stop agreeing.
    var bond = roundUp((sub_total + gp + super_pto + soft_costs + contingency
                        + sales_tax + remodel_tax + taxes + fees) * bond_pct);
    var fees_and_bond = roundUp(fees + bond);                            // D79

    var total = sub_total + gp + super_pto + soft_costs                  // D82
              + contingency + taxes + fees_and_bond;

    return {
      material: material, shipping: shipping, material_total: material_total,
      labor: labor, escalation: escalation, burden: burden, labor_total: labor_total,
      travel: travel,
      sub_total: sub_total,
      gp_pct: gp_pct, gp: gp,
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
  /** THE COMPANY LABOR RATE. One number, set on Markups -> Global (line_key `labor_rate`), and
   *  the starting rate of every labor line on a NEW bid: the three crew rows, Travel Labor, every
   *  library labor row that has no rate of its own, and every line the estimator adds. 33 is
   *  Kyle's sheet (C37 / C44) and is what stands when nothing is filed or the read failed.
   *
   *  A SAVED BID NEVER MOVES. This is a starting point, read once when a bid is first opened and
   *  never applied to a model that already states a labor row (laborUnstated is the gate). */
  var SHIPPED_LABOR_RATE = 33.0;

  /** A usable rate, or the shipped one. Anything that is not a positive finite number reads as
   *  "nothing said", because a $0 company rate would price every new line at nothing. */
  function laborRateOrShipped(rate) {
    var n = (rate === null || rate === undefined || rate === "") ? NaN : Number(rate);
    return (isFinite(n) && n > 0) ? n : SHIPPED_LABOR_RATE;
  }

  /** The labor rate out of GET /api/markup/rules' `rules`, or null when none is filed (or the one
   *  filed is switched off or is not a plain dollar figure). Null, not 33: the caller decides what
   *  "nothing filed" means, and today that is laborRateOrShipped. The formula is the markup page's
   *  own box, so `33`, `33.50` and `$33` all read; an expression does not -- a labor rate that
   *  needed arithmetic would be a price nobody can read off the page. */
  function laborRateFromRules(rules) {
    if (!(rules instanceof Array)) return null;
    for (var i = 0; i < rules.length; i++) {
      var r = rules[i];
      if (!r || r.layout !== "global" || r.line_key !== "labor_rate") continue;
      if (r.applies === false) return null;
      var m = /^\s*\$?\s*(\d+(?:\.\d+)?)\s*$/.exec(String(r.formula === null ||
        r.formula === undefined ? "" : r.formula));
      if (!m) return null;
      var n = Number(m[1]);
      return (isFinite(n) && n > 0) ? n : null;
    }
    return null;
  }

  /** Does this stored library_labor row carry a rate of its OWN? `library_labor.rate` is NOT NULL
   *  (a blank is stored as 0), so "no rate of its own" can only be spelled 0 -- and for Travel,
   *  also the $33.00 the table was seeded with, which nobody chose. A row somebody re-rated to
   *  anything else keeps their number. */
  function libraryRateIsOwn(row, isTravel) {
    var n = Number(row && row.rate);
    if (isBlank(row && row.rate) || !isFinite(n) || n <= 0) return false;
    if (isTravel && n === SHIPPED_LABOR_RATE) return false;
    return true;
  }

  /** The three crew rows and Travel, set to the company rate -- NEW BIDS ONLY (the caller's gate is
   *  laborUnstated). A NEW array of NEW rows. Travel is only moved while it is still on the shipped
   *  $33 or blank: a Travel the library gave its own rate is that rate's to keep. Every other row
   *  (a library default, a typed line) is left alone, because seedLibraryLabor already resolved
   *  those. */
  function applyLaborRate(labor, rate) {
    var dflt = laborRateOrShipped(rate);
    var out = (labor instanceof Array) ? labor.slice() : [];
    for (var i = 0; i < out.length; i++) {
      var r = out[i];
      if (!r) continue;
      var id = String(r.id);
      var crew = (id === "polishing" || id === "mockup" || id === "jointfill");
      var travelOnShipped = (id === "travel") &&
        (isBlank(r.rate) || !isFinite(Number(r.rate)) || Number(r.rate) === SHIPPED_LABOR_RATE);
      if (crew || travelOnShipped) {
        var copy = {};
        for (var k in r) if (Object.prototype.hasOwnProperty.call(r, k)) copy[k] = r[k];
        copy.rate = dflt;
        out[i] = copy;
      }
    }
    return out;
  }

  /** A ROW'S DEFAULT RATE IS THE RATE IT WAS FILLED WITH (Hanz's library precedence): the library
   *  row's own rate when it has one, else the company labor rate -- whichever seeding actually
   *  wrote. Stamped as `rate_default` on every row of a NEW bid once all the seeding has run, so
   *  the "Default value" warning compares a rate to what the row started from, not to the company
   *  rate (a library Travel of $41 on a $50 company rate used to warn with nothing typed).
   *
   *  A row the Labor Calculator filled already carries calc_default.rate and is left alone. A row
   *  that already has a rate_default keeps it. Saved bids never reach this (the caller's gate is
   *  laborUnstated), so they have no stamp and fall back to the company rate as before. A NEW
   *  array of NEW rows. */
  function stampRateDefaults(labor) {
    var out = (labor instanceof Array) ? labor.slice() : [];
    for (var i = 0; i < out.length; i++) {
      var r = out[i];
      if (!r || r.calc_default || r.rate_default !== undefined) continue;
      var copy = {};
      for (var k in r) if (Object.prototype.hasOwnProperty.call(r, k)) copy[k] = r[k];
      copy.rate_default = num(r.rate);
      out[i] = copy;
    }
    return out;
  }

  /** The Travel row as the sheet has it, built fresh each call so no two models share an object.
   *
   *  ONE DEFINITION, THREE CALLERS: `freshModel` seeds it into a new sandbox, `migrateModel`
   *  appends it to a draft saved before it existed, and the library page's Defaults tab draws it.
   *  Written out twice, the two drifted within a day — the migration's copy was still handing out
   *  the blank-rate version after the seed had moved on.
   *
   *  `row` IS THE STORED library_labor ROW WITH THE RESERVED ID `travel`, OR NOTHING. Hanz on the
   *  BUILT IN chip the Defaults tab used to draw beside this line: "again this too how can we
   *  edit this?", and twice before that, "don't put in a hard coded or built in line items". So
   *  the rate is a row somebody can type over — and the 33.0 below is what stands when there is
   *  no row to read: a database where `library_labor` has not been created (production, until the
   *  DDL runs), a row the Defaults tab's Reset has put back, or a read that could not answer. It
   *  is a FALLBACK, not a second source of truth; the stored row is an override of it, which is
   *  the same shape `seedConditionDefaults` takes over `freshModel().conditions`.
   *
   *  THE ID NEVER COMES FROM THE ROW. `travel` is what migrateModel's backfill finds this line by
   *  on every draft ever saved, and an id read off a payload is an id that can arrive wrong.
   *
   *  ONLY THE FOUR FIELDS THE DEFAULTS TAB CAN EDIT are taken. `guys` and `days` are what THIS
   *  job needs and stay empty for the reason libraryLaborRow gives: a seeded quantity is a number
   *  nobody chose sitting inside a customer's price.
   *
   *  A BLANK RATE FALLS BACK RATHER THAN READING AS FREE, and `isFinite` is what catches the
   *  string PostgREST hands numeric back as when it is something other than a number. 0 is NOT
   *  blank: a rate somebody deliberately set to zero is an answer, and `isBlank` agrees. */
  var TRAVEL_LABEL = "Travel Labor";
  /** The label a Travel row carries: blank or exactly the old "Travel" is "Travel Labor"; a name an
   *  admin chose is kept. Also used to relabel a saved draft's row (migrateModel). */
  function travelLabel(name) {
    if (isBlank(name) || String(name) === "Travel") return TRAVEL_LABEL;
    return String(name);
  }

  function travelSeed(row, dflt) {
    var r = row || {};
    var rate = Number(r.rate);
    return { id: "travel",
             // "Travel Labor" (Hanz, 2026-10-05): Lodging and Per Diem now stand beside it as their
             // own lines, so "Travel" alone no longer says which of the three this is. A stored
             // name that is exactly the old "Travel" (the table was seeded with it) reads the same.
             label: travelLabel(r.name),
             guys: "", days: "",
             // `dflt` is the company labor rate (Markups -> Global). Omitted, it is the shipped
             // $33.00, which is what the library page's Reset and its "is this still the shipped
             // row" comparison rely on -- they call travelSeed() with no second argument.
             rate: (isBlank(r.rate) || !isFinite(rate)) ? laborRateOrShipped(dflt) : rate,
             unit: isBlank(r.unit) ? "hours" : String(r.unit),
             guys_auto: Object.prototype.hasOwnProperty.call(r, "guys_auto")
               ? !!r.guys_auto : true };
  }

  /** One row of `public.library_labor`, read as one of THIS model's labor rows.
   *
   *  THE TWO SHAPES DIFFER, AND NEITHER IS RENAMED TO MATCH THE OTHER. The table calls the line's
   *  text `name`, the way every other library table does; a labor row on this model calls it
   *  `label`, the way the three crew rows and Travel above have since the model existed. Renaming
   *  the column would break the library page and the API contract three tracks agreed on; renaming
   *  `label` would blank the Labor step's names on every bid already saved. So the difference is
   *  kept and bridged, once, here.
   *
   *  ONE DEFINITION, and the note on travelSeed directly above says why it is stated only once:
   *  that row written out twice drifted within a day. This is the same row with one more source.
   *
   *  GUYS AND DAYS START EMPTY on purpose. A default says what the line IS and what it costs per
   *  unit; how much of it THIS job needs is the estimator's to type, and a seeded quantity would
   *  be a number nobody chose sitting inside a customer's price. `rate` is Number(), not num():
   *  the endpoint refuses a non-numeric rate with a 400, so there is nothing here for a coercion
   *  to rescue, and laborCost already reads a NaN as 0 rather than poisoning the bid. */
  function libraryLaborRow(row, dflt) {
    var r = row || {};
    // A row with no rate of its own follows the company labor rate -- when the caller has one.
    // `dflt` omitted is the old behaviour exactly (the stored number, 0 included).
    var rate = (dflt !== undefined && dflt !== null && !libraryRateIsOwn(r, false))
      ? laborRateOrShipped(dflt) : Number(r.rate);
    var out = { id: r.id, label: r.name, guys: "", days: "", rate: rate,
                unit: r.unit, guys_auto: !!r.guys_auto };
    // THE DEFAULTS-TAB SLIDER: a default saved as OFF starts the bid's row switched off (grayed,
    // $0). Written only when explicitly false, so every other row keeps exactly the shape it had.
    if (r.default_on === false) out.enabled = false;
    return out;
  }

  /** `labor` with the library's default lines standing beside it. A NEW array; the one handed in
   *  is never touched, and neither are the rows inside it.
   *
   *  `travel` IS A RESERVED ID AND THE ONE EXCEPTION. Every other id already on the model wins
   *  outright, so a default can never displace a row the bid is holding. Travel is the other way
   *  round on purpose: it is the ONE built-in line the Defaults tab can now edit, so its stored
   *  row is APPLIED ONTO the model's own Travel row rather than skipped or pushed beside it.
   *  Skipping it would make the edit do nothing. Pushing it would put TWO rows carrying the id
   *  `travel` on the bid, and migrateModel's backfill finds Travel by that exact id -- it would
   *  start filling fields onto whichever one it reached first. Either way the row an admin typed
   *  a rate into is not the row that prices the job.
   *
   *  GUYS AND DAYS SURVIVE THE OVERLAY. They are quantities for THIS job, not a property of the
   *  default, and editing a rate in the library has no business touching them. The gate below
   *  already means this only runs on a bid with no stated labor at all, so today they are always
   *  blank -- carrying them across is what keeps that true if the gate is ever widened.
   *
   *  A TRAVEL ROW THE MODEL DOES NOT HAVE IS ADDED, not dropped. Every model minted by
   *  freshModel() carries one, so that is the short-fixture case rather than a real bid -- and
   *  the safe direction is the one where Travel is on the estimate either way.
   *
   *  ORDER IS THE SERVER'S. GET /api/library/labor sorts by `sort` then `name`; re-sorting here
   *  would be a second opinion on the order the estimator arranged them in on the library page.
   *  Travel keeps the POSITION IT ALREADY HAD on the model, which is the sheet's own.
   *
   *  WHO IS ALLOWED TO CALL THIS is the whole safety question, and the answer is laborUnstated
   *  below -- never this function, which will happily add rows to a finished bid if asked.
   *
   *  ONLY A FAVORITED ROW SEEDS, 2026-09-24 -- the change that makes the new Labor tab and the
   *  Defaults tab two different presses. `rows` is GET /api/library/labor's full catalog, every
   *  labor type Treadwell has ever typed in, not just the ones somebody has chosen as a default --
   *  `list_labor()` on the server deliberately does not filter it either, because the Labor tab
   *  itself needs the WHOLE list. Before `favorite` existed there was no other tab a custom labor
   *  line could come from, so every row WAS a default by definition and this function seeded all
   *  of them; now that a row can exist without being one, seeding all of them would put every
   *  labor type ever created into every new bid, which is the opposite of what a "Labor tab, and
   *  separately a Default Items & Assemblies tab" was for. `!r.favorite` alone is enough --
   *  `_shape_labor` already reads a row with no stored value as `false`, so this needs no fallback
   *  of its own the way `default_work_types` does for an empty list meaning "every tab": there is
   *  no old data to stay compatible with, because no row anywhere carried `favorite` before today.
   *
   *  TRAVEL IS UNCHANGED BY THIS. The branch above it applies unconditionally, whatever its stored
   *  `favorite` reads -- Travel is not opted into a bid the way a chosen default is, it is built
   *  into every estimate the way it always has been, and the migration backfills it to true
   *  regardless, so the two should never actually disagree. */
  function seedLibraryLabor(labor, rows, dflt) {
    var out = (labor instanceof Array) ? labor.slice() : [];
    if (!(rows instanceof Array)) return out;
    var seen = {};
    var i;
    for (i = 0; i < out.length; i++) {
      if (out[i] && out[i].id !== null && out[i].id !== undefined) seen[String(out[i].id)] = true;
    }
    for (i = 0; i < rows.length; i++) {
      var r = rows[i];
      if (!r || r.id === null || r.id === undefined) continue;
      var rid = String(r.id);
      if (rid === "travel") {
        var travel = travelSeed(r);
        if (dflt !== undefined && dflt !== null && !libraryRateIsOwn(r, true)) {
          travel.rate = laborRateOrShipped(dflt);
        }
        if (r.default_on === false) travel.enabled = false;
        var at = -1;
        for (var t = 0; t < out.length; t++) {
          if (out[t] && String(out[t].id) === "travel") { at = t; break; }
        }
        if (at === -1) {
          out.push(travel);
        } else {
          travel.guys = out[at].guys;
          travel.days = out[at].days;
          out[at] = travel;
        }
        seen[rid] = true;
        continue;
      }
      if (!r.favorite) continue;
      if (seen[rid]) continue;
      seen[rid] = true;
      out.push(libraryLaborRow(r, dflt));
    }
    return out;
  }

  /** Does this SAVED blob state no labor rows of its own?
   *
   *  THE GATE ON THE DEFAULTS, and the only thing standing between a library edit and somebody's
   *  finished bid. True means exactly one thing: nobody has ever stated a labor row for this
   *  estimate, so there is no estimator's work for a default to land on top of.
   *
   *  IT READS THE SAVED BLOB, NOT A MODEL, and it has to. migrateModel fills a missing `labor` in
   *  from freshModel() before it hands the model back, so by the time a model exists the question
   *  can no longer be asked of it -- every model has four labor rows whether or not anybody chose
   *  them. Ask it of the blob or do not ask it at all.
   *
   *  ANYTHING THAT IS NOT A v2 MODEL ANSWERS FALSE, which is the conservative direction. A v1
   *  draft keeps its crew under `labour` (see V1_LABOUR_KEY) and has no `labor` at all, so reading
   *  the absence as "never stated" would inject defaults into a bid that has real crew numbers on
   *  it -- the one outcome this gate exists to prevent. A version-less partial blob is treated the
   *  same way for the same reason: it is not ours to judge. Only "nothing saved whatsoever" and
   *  "a v2 model that states no rows" are seedable. `version !== 2` is the identical strict
   *  comparison migrateModel makes, so the two cannot disagree about what a v2 model is. */
  function laborUnstated(saved) {
    if (!saved || typeof saved !== "object") return true;
    if (saved.version !== 2) return false;
    return !(saved.labor instanceof Array) || !saved.labor.length;
  }

  /** The five conditions that ALSO live as Yes/No literals in Kyle's workbook.
   *
   *  HERE, IN THE SHARED MODULE, BECAUSE THERE ARE NOW TWO SCREENS THAT CAN CHANGE A CONDITION.
   *  It used to live in polish-intake.js, when that page was the only writer. The rule it
   *  supports is stated there: the intake page reads these cells back on load and lets the CELL
   *  win over the model, because a project that arrived from the live intake has no
   *  polish_estimate yet and the estimator's answers are sitting in cell_values.
   *
   *  That rule is only safe while EVERY writer writes both places, which the intake page's own
   *  comment says out loud: "the cell can never be the staler of the two". The Review step became
   *  a second writer on 2026-09-15 and for one commit wrote only the model — so turning Sales tax
   *  off on Review and then following either of Review's own links back to Intake handed the
   *  estimator their old answer, and intake's next save made the revert permanent. A silently
   *  reverted `taxable` moves the bid by 9.475% of materials.
   *
   *  One mapping used by both, for the same reason syncPayloadPricing calls computeTokenValues
   *  rather than re-deriving the money: a second copy is how the two screens drift again.
   *
   *  Only Epoxy!B4 and B5 are paired with a Polish cell: Polish!B4/B5 hold their own Yes/No,
   *  while Polish!D5, B6 and D6 are the formulas =Epoxy!D5 / =Epoxy!B6 / =Epoxy!D6, and writing
   *  them would replace a live reference with a literal. */
  var CONDITION_CELLS = {
    local:           { cells: ["Epoxy!B4", "Polish!B4"], on: "Yes", off: "No" },
    // NO hard_bid ENTRY. It used to write Epoxy!B5/Polish!B5; a cell this beta never writes to
    // is a blank cell, and Kyle's own =IF(B5="yes",...) reads a blank the same way it reads
    // "No" -- so leaving the entry out is enough, with nothing to change in his real sheet.
    prevailing_wage: { cells: ["Epoxy!D5"],              on: "Yes", off: "No" },
    taxable:         { cells: ["Epoxy!B6"],              on: "Yes", off: "No" },
    remodel_tax:     { cells: ["Epoxy!D6"],              on: "Yes", off: "No" },

    // MOVED OFF THE INTAKE FORM, 2026-09-16. These three were "carry" conditions: they lived in a
    // separate object on polish-intake.js, outside the model, because the beta engine prices none
    // of them -- they exist to set a Yes/No literal in Kyle's workbook and nothing else. Hanz
    // asked for them on the Takeoff step instead, where the work they describe actually is.
    //
    // THE MOVE IS INTO THE MODEL, AND THAT IS THE WHOLE POINT. Their old home wrote these cells
    // from exactly one page. Two screens can answer them now, so they go where the other five
    // already are: one writer, `conditionCellWrites`, called by both. The alternative -- a second
    // carry object on a second page -- is how the same question gets two different answers.
    //
    // BOTH LITERALS, ALWAYS, INCLUDING remove_existing_jf WHILE JOINT FILLER IS OFF. The loop
    // below writes every key unconditionally, which is the behaviour being preserved rather than
    // a detail of it: a blank Yes/No cell is not "No" to Kyle's formulas, it is whatever his IF()
    // falls through to. The switch greys out on screen because it moves no money, not because its
    // answer stopped existing.
    dye:               { cells: ["Polish!E25"], on: "Yes", off: "No" },
    joint_filler:      { cells: ["Polish!E29"], on: "Yes", off: "No" },
    remove_existing_jf: { cells: ["Polish!F29"], on: "Yes", off: "No" }
  };

  /** `cells` with those five literals written over it.
   *
   *  MERGED, never a fresh object: cell_values also carries the AI autofill's flags and every
   *  cell the estimator edited by hand on the estimate grid.
   *
   *  Never a blank for "off" — both literals are written explicitly, because a blank Yes/No cell
   *  is not "No" to Kyle's formulas, it is whatever the IF() defaults to.
   *
   *  `bond` is deliberately not in the mapping and so is untouched here: the sheet's bond rate is
   *  a hardcoded cell, not a Yes/No flag, so there is no legacy cell to keep in sync and nothing
   *  for the intake page to read back. That is also why bond is the one condition the Review step
   *  could always flip safely. */
  /** The read-back: the conditions a saved blob's CELLS state, with the cell winning.
   *
   *  THE MIRROR OF conditionCellWrites, and it lives beside it so the two cannot answer the same
   *  question differently. polish-intake.js had this loop written out; polish-estimate.js did not,
   *  and that asymmetry was a live bug rather than an untidiness: the Takeoff step built its model
   *  from migrateModel alone, so every draft written before a condition existed showed freshModel's
   *  ANSWER rather than the estimator's -- and the next save wrote that answer over the real one in
   *  Kyle's workbook. joint_filler is the one that bit: it ships ON, so a project where somebody
   *  deliberately turned it off would have had it silently turned back on.
   *
   *  WHY THE CELL WINS, restated here because it is the whole rule. A project that came through the
   *  live intake has no polish_estimate yet, so migrateModel hands back defaults while the choices
   *  the estimator actually made sit in cell_values. That is only safe while every writer writes
   *  both places -- which conditionCellWrites is for, and which is why these two functions are
   *  adjacent rather than one per page.
   *
   *  A BLANK IS NOT AN ANSWER. An absent or empty cell leaves the model's value alone: every save
   *  writes both literals, so a blank means nobody has answered yet, and the documented default
   *  applies rather than a silent "off". */
  function conditionsFromCells(conditions, cells) {
    var out = Object.assign({}, conditions || {});
    var cv = (cells && typeof cells === "object") ? cells : {};
    for (var key in CONDITION_CELLS) {
      if (!CONDITION_CELLS.hasOwnProperty(key)) continue;
      var cell = cv[CONDITION_CELLS[key].cells[0]];
      if (cell == null || cell === "") continue;
      out[key] = String(cell).trim().toLowerCase() ===
                 String(CONDITION_CELLS[key].on).toLowerCase();
    }
    return out;
  }

  function conditionCellWrites(conditions, cells, library) {
    var out = Object.assign({}, cells || {});
    var c = conditions || {};
    for (var key in CONDITION_CELLS) {
      if (!CONDITION_CELLS.hasOwnProperty(key)) continue;
      var spec = CONDITION_CELLS[key];
      var lit = c[key] ? spec.on : spec.off;
      for (var i = 0; i < spec.cells.length; i++) out[spec.cells[i]] = lit;
    }
    return libraryLineWrites(out, library);
  }

  /** KYLE'S DYE AND JOINT FILLER LINES, as the template ships them (Polish rows 25 and 29).
   *
   *  `template` is his B cell's formula text exactly, character for character: libraryLineWrites
   *  compares against it to tell "the library says what the template already says" from a
   *  change. `shipped` is what polish-estimate.js's condLine falls back to when a row cannot
   *  price -- RATES and the template's own 3,500 -- so a fallback writes the template's figures.
   *
   *  DYE IS TWO LINES, rows 25 and 26 -- one per coat (DYE_COATS), each written the same, so the
   *  sheet's D25 + D26 is the bid's dye figure. `qty` and `rate` are lists for that reason. */
  var LIBRARY_LINE_CELLS = {
    dye: { qty: ["Polish!B25", "Polish!B26"], rate: ["Polish!C25", "Polish!C26"],
           flag: 'E25="Yes"', template: '=IF(E25="Yes",E18)',
           shipped: { unit_price: RATES.DYE_PER_SF, coverage: 1, waste_pct: 0, roundup: false,
                      buy_qty: 1 } },
    joint_filler: { qty: ["Polish!B29"], rate: ["Polish!C29"], flag: 'E29="yes"',
                    template: '=ROUNDUP(IF(E29="yes",(E18/3500),0),0)',
                    shipped: { unit_price: RATES.JOINT_FILLER_KIT_COST, coverage: 3500,
                               waste_pct: 0, roundup: true, buy_qty: 1 } }
  };

  /** `cells` with Kyle's Dye and Joint Filler cells rewritten to the library's own figures.
   *  `cells` is conditionCellWrites' own fresh copy, so writing into it mutates nothing a
   *  caller holds.
   *
   *  ONE PRICE EVERYWHERE. polish-estimate.js prices these two lines off the reserved
   *  library_items rows (condLine); the workbook still carried Kyle's C25 0.14 and C29 500 and
   *  his "/3500", so an edited row would have had the bid and the downloaded .xlsx quoting
   *  different figures. `library` is what the page priced with, per condition key:
   *
   *    absent     no row in the library at all (a database the seed has not reached). NOTHING
   *               is written or removed: the template's cells stand, exactly as before, and a
   *               value an estimator typed on the grid is not touched.
   *    null       the row is there but cannot price (cost or coverage blanked), so the page fell
   *               back to the shipped formula -- and the cells get the shipped figures.
   *    an object  {unit_price, coverage, waste_pct, roundup, buy_qty} off priceLine.
   *
   *  THE RATE CELLS ARE ALWAYS WRITTEN once a row exists: dye's is one coat's price per square
   *  foot (one unit's price over what one unit covers, plus its waste), written into BOTH C25
   *  and C26, one per coat; the kit's is one kit's price. THE
   *  QUANTITY FORMULA IS WRITTEN ONLY WHEN IT DIFFERS from the template's text -- or when the key
   *  is already there, so a coverage put back to 3,500 replaces the formula an earlier save wrote
   *  rather than leaving it stale. With the seeded rows every value written equals the template's,
   *  so the workbook is unchanged. Formulas stay formulas: estimate_writer's _coerce passes an
   *  "=ROUNDUP(IF(...))" through as one, and Excel recomputes D25/D29 and the tab on open. */
  function libraryLineWrites(cells, library) {
    var out = cells;
    var lib = library || {};
    for (var key in LIBRARY_LINE_CELLS) {
      if (!LIBRARY_LINE_CELLS.hasOwnProperty(key)) continue;
      if (!Object.prototype.hasOwnProperty.call(lib, key) || lib[key] === undefined) continue;
      var spec = LIBRARY_LINE_CELLS[key];
      var ln = lib[key] || spec.shipped;
      var price = num(ln.unit_price);
      var cov = num(ln.coverage);
      var waste = num(ln.waste_pct);
      var pack = num(ln.buy_qty) > 0 ? num(ln.buy_qty) : 1;
      var roundup = ln.roundup !== false;
      if (!(cov > 0)) { ln = spec.shipped; price = num(ln.unit_price); cov = ln.coverage;
                        waste = 0; pack = 1; roundup = ln.roundup; }
      // What one unit of the row covers, inflated by its waste: the formula's divisor, written
      // out rather than pre-multiplied so Kyle reads his own shape back ("/3500", "*(1+10/100)").
      var need = "E18" + (waste ? "*(1+" + waste + "/100)" : "") + "/" + cov;
      var qty, rate;
      if (key === "dye" && !roundup) {
        // Dye is charged across the area: the quantity stays his =IF(E25="Yes",E18) and the
        // whole of the row's arithmetic goes into the per-square-foot rate.
        qty = spec.template;
        rate = price * (1 + waste / 100) / cov;
      } else {
        // Units bought: whole packs when the row rounds up, the exact need when it does not.
        var core = "IF(" + spec.flag + ",(" + need + ")" + (roundup && pack !== 1 ? "/" + pack : "") +
          ",0)";
        qty = roundup ? "=ROUNDUP(" + core + ",0)" + (pack !== 1 ? "*" + pack : "") : "=" + core;
        rate = price;
      }
      // Twelve significant figures, this file's roundUp() tolerance: 0.2 x 1.05 / 2 is
      // 0.10500000000000001 in IEEE-754, and a 17-digit rate is not something to put in front
      // of Kyle in his own workbook. The seeded 0.14 and 500 come through unchanged.
      for (var j = 0; j < spec.rate.length; j++) {
        out[spec.rate[j]] = parseFloat(rate.toPrecision(12));
        if (qty !== spec.template || Object.prototype.hasOwnProperty.call(out, spec.qty[j])) {
          out[spec.qty[j]] = qty;
        }
      }
    }
    return out;
  }

  /** `conditions` with the library's stored answers written over it. A NEW object; the one handed
   *  in is never touched.
   *
   *  AN OVERRIDE OF A LITERAL, NOT A SECOND COPY OF IT. freshModel() still states what the tool
   *  SHIPS answering -- joint filler on, dye and remove-existing off -- and a row only arrives
   *  here for a condition somebody has deliberately changed on the Defaults tab. That is why
   *  neither this file nor backend/condition_defaults.py holds a second statement of the shipped
   *  answer: the note above travelSeed records what two copies of one fact did within a day.
   *
   *  ONLY A KEY THE MODEL ALREADY CARRIES. migrateModel whitelists condition keys against
   *  freshModel().conditions and DROPS every other one, so a key seeded here that the model does
   *  not have would look applied on screen and come back missing on the next load -- the exact
   *  trap polish-intake.js records for `reno`. An off-vocabulary row is skipped rather than
   *  thrown over: the endpoint already refuses one on the way in, and a page that died over a row
   *  it could ignore would cost an estimator the whole Takeoff step.
   *
   *  WHO IS ALLOWED TO CALL THIS is the whole safety question, and the answer is
   *  conditionsUnstated below -- never this function, which will happily rewrite the answers on a
   *  finished bid if asked. The same split seedLibraryLabor and laborUnstated already take. */
  function seedConditionDefaults(conditions, rows) {
    var out = Object.assign({}, conditions || {});
    if (!(rows instanceof Array)) return out;
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      if (!r || !r.key) continue;
      if (!Object.prototype.hasOwnProperty.call(out, r.key)) continue;
      out[r.key] = !!r.on;
    }
    return out;
  }

  /** Has NOTHING been saved for this estimate at all?
   *
   *  THE GATE ON THE CONDITION DEFAULTS, and deliberately stricter than laborUnstated. Hanz's
   *  rule for this feature, verbatim: changing a default must not change any estimate that
   *  already exists, because an estimator's saved answers are their work. So the one seedable
   *  case is the one with no work to protect -- nothing saved whatsoever, or a blob that states
   *  literally nothing.
   *
   *  WHY NOT laborUnstated's "a v2 model stating an empty array" CLAUSE. An empty `labor` array is
   *  a shape a real model can hold and genuinely means "no rows chosen". `conditions` has no
   *  equivalent: migrateModel backfills every key from freshModel on the way out, so a saved v2
   *  blob that omitted `conditions` was still SHOWN an answer, and its next save wrote that answer
   *  into Kyle's workbook through conditionCellWrites. Reading that as unstated would move a
   *  Yes/No literal on a bid somebody has already worked on -- which is the one thing this gate
   *  exists to prevent.
   *
   *  IT READS THE SAVED BLOB, NOT A MODEL, for the reason laborUnstated gives: by the time a model
   *  exists every condition has an answer whether or not anybody chose it. Ask it of the blob or
   *  do not ask it at all. */
  function conditionsUnstated(saved) {
    if (!saved || typeof saved !== "object") return true;
    for (var k in saved) {
      if (Object.prototype.hasOwnProperty.call(saved, k)) return false;
    }
    return true;
  }

  /** Which condition cards a NEW estimate shows, out of the library's stored answers.
   *
   *  Hanz, 2026-10-01: "Everything that is in the defaults and labor tab in the Items and
   *  Assemblies appear as grayed out options that can be enabled or not." A condition on the
   *  Defaults tab (`listed`, the default) shows its card on a new bid, grayed until it is switched
   *  on; one taken off the Defaults tab does not. Only the OFF-the-list answers are recorded --
   *  `{ dye: false }` -- so an estimate saved before this existed, which has no map at all, shows
   *  all three exactly as it did.
   *
   *  SNAPSHOTTED ONTO THE BID, behind the same conditionsUnstated gate as seedConditionDefaults:
   *  taking a condition off the Defaults tab later must not change an estimate somebody already
   *  has open. Only the three keys CONDITION_CELLS writes are read. */
  function seedConditionsShown(rows) {
    var out = {};
    if (!(rows instanceof Array)) return out;
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      if (!r || !r.key || !Object.prototype.hasOwnProperty.call(CONDITION_CELLS, r.key)) continue;
      if (r.listed === false) out[r.key] = false;
    }
    return out;
  }

  /** Does this estimate show the card for `key`? A condition that is switched ON always shows,
   *  whatever the map says -- an answer that prices the bid is never hidden from the estimator. */
  function conditionShown(model, key) {
    var m = model || {};
    if ((m.conditions || {})[key]) return true;
    return !(m.conditions_shown && m.conditions_shown[key] === false);
  }

  /** The labor rows the template itself seeds: A37 = 3 guys at C37 = $33.00/hr, the mock-up at
   *  B40 = half a day, and joint filling at C44 = $33.00. Days are left blank on the two an
   *  estimator has to judge.
   *
   *  TRAVEL IS THE SHEET'S OWN ROW, transcribed like the other three rather than invented. Polish
   *  A43/B43 head it `Guys | Hours` and C44 carries the same $33.00; its hours are left blank for
   *  the same reason two of the crew rows leave days blank. (An earlier note here said the sheet
   *  had no Travel row to copy and seeded it blank — that was wrong, written before the workbook
   *  was read; rows 43-44 are right there under Joint Filler.)
   *
   *  `unit: "hours"` is what stops laborCost multiplying it by the 8-hour day, and `guys_auto`
   *  is what keeps its Guys column equal to the crew's man-days until somebody types over it —
   *  see travelManDays and the note on guys_auto in migrateModel. */
  function freshModel() {
    return {
      version: 2,
      takeoff: [{ assembly_id: "", assembly_name: "", measurement: "", unit: "SF" }],
      labor: [
        { id: "polishing", label: "Polishing", guys: 3, days: "", rate: SHIPPED_LABOR_RATE },
        { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: SHIPPED_LABOR_RATE },
        { id: "jointfill", label: "Joint filler", guys: 3, days: "", rate: SHIPPED_LABOR_RATE },
        travelSeed()
      ],
      // ALL THREE TAKEOFF CONDITIONS SHIP OFF, and joint_filler is the one that moved.
      //
      // It shipped ON until 2026-09-19 because Kyle's template ships Polish!E29 = "Yes". That was
      // a faithful transcription of the workbook and the wrong default for this tool, and the
      // difference is that the workbook is a thing Kyle fills in while this is a thing that
      // prices a bid on its own. Since 2026-09-18 the condition carries real money --
      // jointFillerCost charges one $500 kit per 3,500 sq ft -- so shipping it on added $2,500 to
      // a 17,500 SF bid that nobody had asked for and no screen made anybody decide. Hanz's call:
      // all three start off and the estimator switches on what the job actually needs, on the
      // estimate's own Takeoff step.
      //
      // THE WORKBOOK STILL GETS ITS LITERAL. conditionCellWrites writes both Yes and No
      // unconditionally, so Polish!E29 lands as "No" rather than blank -- a blank Yes/No cell is
      // not "No" to Kyle's formulas, it is whatever his IF() falls through to.
      //
      // AN ADMIN OVERRIDE STILL WINS over every one of these: seedConditionDefaults writes a
      // stored condition_defaults row over this literal on a brand new bid. This is what the tool
      // SHIPS answering, not the last word on it.
      conditions: { local: true, prevailing_wage: false,
                    taxable: true, remodel_tax: false, bond: false,
                    dye: false, joint_filler: false, remove_existing_jf: false },
      contingency: 0,
      // D77, the Fees + Textura line. Seeded from RATES.FEES rather than a bare 0 so the constant
      // stays the one place that says what the workbook ships -- the parity test pins B77×C77 as
      // blank, and a literal here would let the two drift apart silently.
      fees: RATES.FEES,
      // Lodging and Per Diem, both OFF (see travelCostsSeed).
      travel: travelCostsSeed(),
      totals: {}
    };
  }

  /** v1 kept its labor under these keys. `crew` was the GUYS COUNT, not a crew cost — reading it
   *  as money would multiply a saved estimate by eight. */
  var V1_LABOUR_KEY = { polishing: "polishing", mockup: "mockup", jointfill: "joint_filler" };

  function isBlank(v) {
    return v === null || v === undefined || (typeof v === "string" && v.replace(/\s/g, "") === "");
  }

  /** True when a field holds a usable number. 0 counts: a labor row at 0 days is a row the
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
        conditions: {}, contingency: model.contingency, fees: model.fees,
        totals: (model.totals && typeof model.totals === "object") ? model.totals : {}
      };
      if (!(out.takeoff instanceof Array) || !out.takeoff.length) out.takeoff = fresh.takeoff;
      if (!(out.labor instanceof Array) || !out.labor.length) {
        out.labor = fresh.labor;
      } else {
        // Travel joined `freshModel()`'s labor rows here on 2026-09-12 (#491), but a sandbox
        // already saved before that keeps whatever row count it had FOREVER — the branch above
        // only replaces the WHOLE array, and only when it is missing or empty, so a non-empty
        // saved array (Hanz's real "Akoya Omakase (beta test)": polishing/mockup/jointfill, no
        // travel) passes straight through untouched. Nothing else backfills a labor row, so
        // Travel simply never arrived on reload no matter how many times the page was reopened.
        //
        // Fix is additive and keyed by id: append the blank Travel row only when it's missing.
        // Existing rows are never touched — including one an estimator typed in by hand via
        // "+ Add a labor line", and any guys/days/rate already entered on the original three —
        // and a sandbox opened after Travel shipped already has the id, so nothing doubles up.
        //
        // NARROW ON PURPOSE, not a generic "diff against freshModel().labor and backfill every
        // missing id" loop: `conditions` just below has exactly that shape because it was built
        // in on day one (2df0136) with a real per-key merge from the start, so generalizing it
        // costs nothing. `labor` never had one, and testing a generic version here showed real
        // cost — `blockers()` and several page-harness fixtures build INTENTIONALLY short labor
        // arrays (one row, to isolate a single scenario; two rows, to test add/delete UI
        // mechanics) that are not stale drafts at all, and a generic backfill can't tell the two
        // apart, so it silently padded rows those fixtures never asked for and broke assertions
        // about row count and index that have nothing to do with Travel. The one-off costs three
        // lines instead of a loop and touches nothing that isn't actually missing Travel.
        // NEXT TIME A LABOR TASK IS ADDED: don't copy this block verbatim. Either (a) add another
        // narrow `if` right below it, naming the new id explicitly — fine as long as it's one or
        // two more — or (b) once there are several of these, replace all of them with the generic
        // per-id loop this comment talks past, AND update `blockers()`'s and the page harnesses'
        // short fixtures to carry a full row set, so a short array reliably means "a stale draft,"
        // not "a test that only cares about one row." Don't add the generic loop without doing
        // that second half — that's exactly what broke here.
        var hasTravel = false;
        for (var li = 0; li < model.labor.length; li++) {
          if (model.labor[li] && model.labor[li].id === "travel") { hasTravel = true; break; }
        }
        if (!hasTravel) {
          out.labor = model.labor.concat([travelSeed()]);
        } else {
          // A TRAVEL ROW CAN ALSO BE OUT OF DATE, which is the second half of the same problem and
          // the reason this is a map rather than the one-line pass-through it started as. Travel
          // shipped on 2026-09-12 priced like a crew row — `guys × days × rate × 8`, no `unit`,
          // blank rate — and was corrected hours later to the sheet's own Guys × HOURS × $33 with
          // no multiplier. Every sandbox opened in between holds the first shape, and left alone
          // it would bill a 2-hour drive as 16 and then price it at nothing, because its rate is
          // blank. So the fields Travel gained are filled in the same additive way the row itself
          // is: only what is missing, never over a number somebody typed.
          //
          // `guys_auto` is decided from the row rather than defaulted true: a draft where Travel
          // already carries a guys figure had that typed by hand (nothing auto-filled it before
          // this existed), so turning the auto back on would overwrite their number on the next
          // keystroke anywhere in the panel.
          out.labor = model.labor.map(function (r) {
            if (!r || r.id !== "travel") return r;
            // RELABEL, "Travel" -> "Travel Labor" (2026-10-05). Only a label that is EXACTLY the
            // old word: a name somebody typed over it is theirs. A copy, never an edit in place.
            if (r.label === "Travel") {
              var relabeled = {};
              for (var rk in r) {
                if (Object.prototype.hasOwnProperty.call(r, rk)) relabeled[rk] = r[rk];
              }
              relabeled.label = TRAVEL_LABEL;
              r = relabeled;
            }
            var current = r.unit === "hours" &&
                          Object.prototype.hasOwnProperty.call(r, "guys_auto") &&
                          !isBlank(r.rate);
            if (current) return r;
            var next = {};
            for (var kk in r) {
              if (Object.prototype.hasOwnProperty.call(r, kk)) next[kk] = r[kk];
            }
            next.unit = "hours";
            if (!Object.prototype.hasOwnProperty.call(next, "guys_auto")) {
              next.guys_auto = isBlank(next.guys);
            }
            if (isBlank(next.rate)) next.rate = travelSeed().rate;
            return next;
          });
        }
      }
      var saved = (model.conditions && typeof model.conditions === "object") ? model.conditions : {};
      for (var k in fresh.conditions) {
        if (!fresh.conditions.hasOwnProperty(k)) continue;
        out.conditions[k] = (k in saved) ? !!saved[k] : fresh.conditions[k];
      }
      // WHICH CONDITION CARDS THIS BID SHOWS -- seedConditionsShown's snapshot. Carried through
      // only as `key: false` for the three keys CONDITION_CELLS writes; anything else is dropped,
      // and a bid with no map shows all three, as every bid did before it existed.
      if (model.conditions_shown && typeof model.conditions_shown === "object") {
        var shown = {};
        for (var sk in CONDITION_CELLS) {
          if (Object.prototype.hasOwnProperty.call(CONDITION_CELLS, sk) &&
              model.conditions_shown[sk] === false) shown[sk] = false;
        }
        out.conditions_shown = shown;
      }
      // THIS BID'S OWN COVERAGE for the two priced condition lines (Joint Filler, Dye), typed on
      // the Takeoff step's cards. Carried only for those two keys and only when stated: a draft
      // saved before the boxes existed has no `cond_cov` and keeps pricing with the library row,
      // which is what absent means. (A takeoff row's own `coverage` / `line_cov` ride inside
      // `takeoff`, which passes through whole.)
      if (model.cond_cov && typeof model.cond_cov === "object") {
        var cc = {};
        ["joint_filler", "dye"].forEach(function (ck) {
          var v = model.cond_cov[ck];
          if (v !== undefined && v !== null && v !== "") cc[ck] = v;
        });
        if (Object.keys(cc).length) out.cond_cov = cc;
      }
      // LODGING AND PER DIEM. A draft saved before they existed has no `travel`, and reads as the
      // seed: both lines OFF at the shipped rates, so an old bid opened after this shipped prices
      // exactly what it did and is not repriced behind anybody's back.
      out.travel = normalizeTravel(model.travel);
      // THE JOB'S DISTANCE, when one is stated. Absent on every draft saved before it existed, and
      // absent reads as "unknown" -- the page then asks the server once.
      var dist = normalizeDistance(model.distance);
      if (dist) out.distance = dist;
      if (isBlank(out.contingency)) out.contingency = 0;
      // Every v2 draft saved before the Fees line became typeable has no `fees` at all, and a
      // missing one must read as the zero the sheet ships.
      if (isBlank(out.fees)) out.fees = fresh.fees;
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
        // BUILT ON THE SEED, not listed field by field. This used to name the five v1 fields
        // explicitly and rebuild each row from scratch, which silently dropped every field a seed
        // gained afterwards: Travel's `unit`/`guys_auto` went missing, so a v1 draft opened with
        // travel priced by the eight-hour day, and the v2 branch then added them back on the NEXT
        // load — migrating twice differing from migrating once, which is the thing
        // migrationIsIdempotent exists to catch. Copying the seed first means the next field to
        // be added is carried here for free.
        var row = {};
        for (var sk in seed) {
          if (Object.prototype.hasOwnProperty.call(seed, sk)) row[sk] = seed[sk];
        }
        row.guys = num(old.crew) || seed.guys;
        row.days = isBlank(old.days) ? seed.days : num(old.days);
        row.rate = num(old.rate) || seed.rate;
        labor.push(row);
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
               contingency: 0, fees: fresh.fees, totals: {}, travel: fresh.travel };
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
      if (!rowOn(r)) continue;                         // switched off: not part of this bid
      var measured = num(r.measurement);
      // EITHER ID IS A PICK. A takeoff row has been able to be one material rather than an
      // assembly since 2026-09-19, and reading assembly_id alone told a bid made of materials it
      // had nothing picked -- which kept the Review step's pip grey and its blocker list shouting
      // at rows that were finished. The MESSAGE is left exactly as it was: it is the text two
      // test files pin, and it is still the right sentence for a row with nothing picked at all.
      var picked = !!(r.assembly_id || r.item_id);
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
      if (!rowOn(row)) continue;                       // switched off: not part of this bid

      // AN HOURS ROW WITH NO HOURS IS UNUSED, NOT UNFINISHED, and skipping it here is what keeps
      // the Review step reachable. The rule below reads a row as half-filled when 1 or 2 of the
      // three boxes are empty, and deliberately ignores a row where all three are — "switched
      // off". Travel used to qualify for that: it seeded fully blank. It no longer can. It now
      // arrives with a rate of $33 off the sheet and a Guys figure this page fills in from the
      // crew's man-days, so on a bid nobody has typed a single travel hour into, exactly one box
      // is empty — and without this line every draft in the system would open saying "Add the
      // days for Travel", including the local jobs that will never drive anywhere.
      //
      // Hours is the field that means "we are doing this": guys and rate are both defaults the
      // estimator never chose, so neither says anything about intent. A travel row WITH hours is
      // checked like any other — miss the rate on it and it still complains.
      if (row.unit === "hours" && !filledIn(row.days)) continue;

      // A line nobody has named or sized is an untouched blank, not a half-filled one. New lines
      // arrive with the company rate already in the rate box, so "one box filled" no longer means
      // the estimator started it.
      if (isBlank(row.label) && !filledIn(row.guys) && !filledIn(row.days)) continue;

      var missing = [];
      if (!filledIn(row.guys)) missing.push("guys");
      if (!filledIn(row.days)) missing.push(row.unit === "hours" ? "hours" : "days");
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
    HOURS_PER_DAY: HOURS_PER_DAY, RATES: RATES, GP_BANDS: GP_BANDS, DYE_COATS: DYE_COATS,
    gpPct: gpPct,
    CONDITION_CELLS: CONDITION_CELLS, conditionCellWrites: conditionCellWrites,
    LIBRARY_LINE_CELLS: LIBRARY_LINE_CELLS,
    conditionsFromCells: conditionsFromCells,
    // The library's answer for a condition, and the gate that decides whether it may be
    // applied at all. Exported as a PAIR on purpose: seedConditionDefaults will rewrite the
    // answers on a finished bid if a caller asks it to, and conditionsUnstated is the only
    // thing standing between a Defaults-tab edit and somebody's saved work.
    seedConditionDefaults: seedConditionDefaults,
    conditionsUnstated: conditionsUnstated,
    setMeasurement: setMeasurement,
    seedConditionsShown: seedConditionsShown, conditionShown: conditionShown,
    laborCost: laborCost, laborTotal: laborTotal, travelManDays: travelManDays,
    // Lodging and Per Diem, the two travel costs beside Travel Labor (see travelCostsSeed).
    SHIPPED_LODGING_RATE: SHIPPED_LODGING_RATE, SHIPPED_PER_DIEM_RATE: SHIPPED_PER_DIEM_RATE,
    TRAVEL_LINE_KEYS: TRAVEL_LINE_KEYS, TRAVEL_LABEL: TRAVEL_LABEL, travelLabel: travelLabel,
    travelCostsSeed: travelCostsSeed, travelQty: travelQty, travelLineCost: travelLineCost,
    travelCosts: travelCosts, travelRatesFromRules: travelRatesFromRules,
    applyTravelRates: applyTravelRates, normalizeTravel: normalizeTravel,
    // Distance decides "local" (see LOCAL_MILES).
    LOCAL_MILES: LOCAL_MILES, milesOrNull: milesOrNull, distanceKey: distanceKey,
    normalizeDistance: normalizeDistance, isFarMiles: isFarMiles, applyDistance: applyDistance,
    clearDistance: clearDistance, distanceNote: distanceNote,
    rowOn: rowOn, sliderHtml: sliderHtml,
    filledIn: filledIn,
    takeoffSf: takeoffSf, measuredSf: measuredSf,
    seedTakeoffSf: seedTakeoffSf,
    seedDefaultTakeoff: seedDefaultTakeoff,
    dyeCost: dyeCost, jointFillerCost: jointFillerCost,
    markupChain: markupChain,
    freshModel: freshModel, migrateModel: migrateModel, blockers: blockers,
    // EXPORTED 2026-09-16 for a THIRD reader: the library page's Defaults tab lists Travel as the
    // labor default that already exists. It is exported rather than re-typed there for the reason
    // written above travelSeed itself -- the two copies that existed before drifted within a day,
    // and a third on another page would have drifted unseen, because nothing on the library page
    // prices anything and nobody would have noticed the rate go stale.
    travelSeed: travelSeed,
    // AND THE SAME ARGUMENT AGAIN, 2026-09-17, for the library's CUSTOM labor lines. The seam
    // between a library_labor row and an estimate labor row lives in libraryLaborRow and nowhere
    // else -- the table says "name", the estimate says "label", and a second hand-written mapping
    // is exactly how travelSeed came to have two copies that disagreed.
    //
    // The conflict resolved here was the seed branch replacing travelSeed's export rather than
    // joining it: that branch was cut from main, which did not have the 2026-09-16 export yet.
    // Both belong -- Travel is built in, the library rows are additions beside it.
    libraryLaborRow: libraryLaborRow, seedLibraryLabor: seedLibraryLabor,
    LABOR_CALC_BUILTINS: LABOR_CALC_BUILTINS, dayHours: dayHours, laborCalcValues: laborCalcValues, applyLaborCalc: applyLaborCalc,
    laborCalcDiffers: laborCalcDiffers,
    laborUnstated: laborUnstated,
    // The company labor rate (Markups -> Global): read, applied to a new bid, and the fallback.
    SHIPPED_LABOR_RATE: SHIPPED_LABOR_RATE, laborRateOrShipped: laborRateOrShipped,
    laborRateFromRules: laborRateFromRules, applyLaborRate: applyLaborRate,
    stampRateDefaults: stampRateDefaults
  };
});
