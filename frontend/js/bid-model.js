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
//
// THE CHAIN ITSELF MOVED (Phase 8). markupChain below is now a thin wrapper: it hands the job to
// js/bid-engine.js priceChain with the profile `polish-legacy` (js/bid-profiles.js), which is exactly what
// this file priced before, and returns the same keys with the same values. The rates the comment above
// quotes live in that profile as Markups formula text now; RATES, GP_BANDS and the shipped travel and
// labor figures below are READ from it, so there is one copy of each number. The chain golden
// (backend/tests/fixtures/polish_chain_golden.json) is what says nothing moved.
//
// LOAD ORDER. This file needs js/excel-math.js, js/work-types.js and js/bid-engine.js loaded before it (and
// bid-engine.js needs js/bid-profiles.js and js/markup-core.js): a script tag above this one on a page, and
// `require` does the same under node. The number helpers it exports (num,
// roundUp, copyInto, money, money2, pct, fmtSf) are excel-math's own functions, bound below to the names
// this file has always used. The work-type vocabulary and the job-conditions table (which workbook cells
// each condition writes, what a new bid answers, which defaults apply to a job) are work-types.js's, and
// this file derives CONDITION_CELLS, a fresh model's conditions and workTypeApplies from them.
(function (root, factory) {
  var isNode = typeof module !== "undefined" && module.exports;
  var deps = {
    math: isNode ? require("./excel-math.js") : root.TWExcelMath,
    types: isNode ? require("./work-types.js") : root.TWWorkTypes,
    engine: isNode ? require("./bid-engine.js") : root.TWBidEngine
  };
  if (!deps.math) throw new Error("bid-model.js needs excel-math.js loaded before it");
  if (!deps.types) throw new Error("bid-model.js needs work-types.js loaded before it");
  if (!deps.engine) throw new Error("bid-model.js needs bid-engine.js loaded before it");
  var api = factory(deps);
  root.TWBidModel = api;
  if (isNode) module.exports = api;   // node, for tests
})(typeof self !== "undefined" ? self : this, function (deps) {
  "use strict";

  // The number helpers live in excel-math.js (Phase 5). They are bound here to the names this file has
  // always used, so every line below reads as it did, and they are exported again at the bottom under
  // those same names.
  var num = deps.math.num, copyInto = deps.math.copyInto, roundUp = deps.math.roundUp,
      money = deps.math.money, money2 = deps.math.money2, pct = deps.math.pct, fmtSf = deps.math.fmtSf,
      isBlank = deps.math.isBlank;

  // The work-type vocabulary and the job-conditions table (js/work-types.js, Phase 7). Every question
  // this file answers about WHICH JOB TYPE, WHICH TAB or WHICH CONDITION goes through it.
  var types = deps.types;

  // ── the constants, straight off the Polish tab ──────────────────────────────
  /** D37: `=(A37*B37*C37)*IF($E$35="8 hour days",8,10)`, and E35 says "8 hour days". */
  var HOURS_PER_DAY = 8;

  // THE PROFILE THIS FILE PRICES WITH, and the rates it reads. `polish-legacy` (js/bid-profiles.js) is the
  // Polish tab as this model has always charged it. Every figure in RATES below, and the GP ladder, is READ
  // off it and off the global defaults, as Markups formula text snapped to twelve significant figures, so the
  // number lives in one file. The cell each came from is still named beside it.
  var engine = deps.engine;
  var LEGACY = engine.resolveProfile("polish-legacy");
  // POLISH REV 2 (Phase 17), the profile a NEW bid's Polish section is stamped with. The root section is priced by
  // exactly one of these two, and by REV2 only when its own `profile` key says so (rootProfile): a bid saved before
  // Phase 17 has no such key and prices as it always has.
  var REV2 = engine.resolveProfile("polish-rev2");
  // polish-rev3 (2026-10-16): rev2 with the sheet's patch line. What a NEW Polish section is priced by from that day.
  var REV3 = engine.resolveProfile("polish-rev3");

  var RATES = {
    SHIPPING: engine.rateNumber(LEGACY.rates.ship_pct),         // B32
    ESCALATION: engine.rateNumber(LEGACY.rates.esc_pct),        // C46, when prevailing wage applies
    BURDEN: engine.rateNumber(LEGACY.rates.burden_pct),         // C47
    SUPER_PTO: engine.rateNumber(LEGACY.rates.super_pto),       // B69
    SOFT_COSTS: engine.rateNumber(LEGACY.rates.soft_costs),     // B70
    SALES_TAX: engine.rateNumber(LEGACY.rates.sales_tax),       // B74, when the job is taxable
    BOND: engine.rateNumber(LEGACY.rates.bond),                 // B78 — the sheet ships it at zero
    FEES: engine.defaultNumber("fees_textura"),                 // D77 — B77 and C77 are blank, so the line is zero
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
    SHEET_REMODEL: engine.defaultNumber("remodel_sheet"),  // B75 — what the workbook says, NOT what this engine charges
    KS_STATE: engine.defaultNumber("remodel_state")        // the floor when nobody has picked a county yet
  };

  /** B67, as bands: [ceiling, rate]. Strictly BELOW the ceiling, and the last band is the floor
   *  for everything above. A `<=` here would move the GP on every job that lands exactly on a
   *  round number, which is most of the ones anybody checks. Read off the profile's ladder (the Polish tab's
   *  five rungs); the edges and rates live in js/bid-profiles.js and nowhere else. */
  var GP_BANDS = engine.bandsOf(LEGACY.rates.gp);

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

  /** The hint under a Guys / Lodging / Per Diem box: one wording, drawn by the card builders and
   *  repainted in place as the tasks above change. A box on auto (a bid saved before 2026-10-12) says
   *  the figure IS the man-days. Any other box says what the sheet would count, as text and
   *  never as a value: the box itself is the estimator's to type. `manDays` is travelManDays of the
   *  rows; left out, the hint says only that the box is typed. (Travel Labor's Guys on a job the
   *  distance sent far are on auto too, but they follow the crew's size and not the man-days:
   *  travelGuysHint words those.) */
  function manDaysHint(auto, manDays) {
    if (auto) return "Man-days from the tasks above.";
    if (manDays === undefined || manDays === null) return "Typed by you.";
    return "Man-days from the tasks above: " + (Math.round(num(manDays) * 100) / 100) + ".";
  }

  /** The hint under a Lodging or Per Diem box. A bid priced by Polish rev 2 says what the SHEET counts, which is worked
   *  out from the labor dollars (sheetNights) and so can be more than the man-days; every other bid says the man-days as
   *  it always has (manDaysHint), and so does a rev 2 bid while the sheet's count and the man-days are the same figure.
   *  Text only: the box stays the estimator's to type. `rows` are the labor rows of the
   *  section on show. */
  function lodgingHint(model, tab, auto, rows) {
    var opts = travelOpts(model, tab);
    if (!opts) return manDaysHint(auto, travelManDays(rows));
    // The prevailing rate in force rides in opts (travelOpts), so the count here is the one the page prices with.
    var days = travelManDays(rows), nights = sheetNights(rows, opts.conditions, opts.prevailing);
    // While every row is paid the same rate the two counts are one figure and the words are the ones every bid shows.
    if (Math.abs(nights - days) < 1e-9) return manDaysHint(auto, days);
    if (auto) return "Nights counted from the labor above, as the sheet does.";
    return "Nights from the labor above, as the sheet counts them: " + (Math.round(nights * 100) / 100) + ".";
  }

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
  function laborCost(row, pw) {
    row = row || {};
    // A ROW SWITCHED OFF ADDS NOTHING (Kyle's on/off slider, 2026-10-05). Zero HERE, at the one
    // function every total goes through, so the figure is skipped in laborTotal BEFORE markupChain
    // rounds the sum -- zeroing after the rounding would drift the bid by up to a dollar.
    if (!rowOn(row)) return 0;
    // A DAY IS 8 HOURS UNLESS THE ROW SAYS 10 (the Labor Calculator's "hours a day", 2026-10-06).
    // Only 8 and 10 are honoured, so a stray value in a saved blob prices as the sheet does.
    var perDay = row.unit === "hours" ? 1 : dayHours(row);
    return num(row.guys) * num(row.days) * laborRateOf(row, pw) * perDay;
  }

  /** THE RATE A LABOR ROW PRICES AT, the one place a blank Rate box is resolved (Hanz, 2026-10-09).
   *  A rate that is typed is the rate, 0 included: typing 0 still means zero. A rate that is BLANK
   *  is the line's own default rate, not $0: the rate the row was filled with (`calc_default.rate`
   *  when the Labor Calculator filled it, else the `rate_default` stamp a new bid carries on every
   *  row). A row with no stamp (a saved bid from before the stamp, which was never filled from
   *  anything) keeps pricing a blank rate at 0, so no saved bid's total moves. laborCost, the
   *  Review lines and the box on the card all read this, so the screen and the totals agree.
   *
   *  THE PREVAILING WAGE IS A LINE'S DEFAULT RATE (Hanz, 2026-10-15). `pw` is the job's prevailing
   *  rate IN FORCE (prevailingApplied(model): the Labor step's card is on and a rate is set), 0 or
   *  absent when there is none. A crew line that follows its default prices at `pw` instead of its
   *  own default; a line whose rate was typed by hand on this bid keeps what was typed, and Travel
   *  Labor keeps its own rate (laborFollowsPrevailing). Every total, the Review lines and the Rate
   *  box on the card pass the same `pw`, so they cannot disagree, and a caller that passes none
   *  prices exactly as before. */
  function laborRateOf(row, pw) {
    row = row || {};
    if (laborFollowsPrevailing(row, pw)) return num(pw);
    if (!isBlank(row.rate)) return num(row.rate);
    var own = ownDefaultRate(row);
    return own === null ? 0 : own;
  }

  /** The rate a row was FILLED with and falls back to, or null when it has none: the Labor
   *  Calculator's (`calc_default.rate`), else the stamp a new bid carries on every row
   *  (`rate_default`). A saved bid from before the stamp has neither, and a null here is what keeps
   *  its rates exactly as it saved them. */
  function ownDefaultRate(row) {
    var d = row && row.calc_default;
    if (d && !isBlank(d.rate) && isFinite(Number(d.rate))) return num(d.rate);
    if (row && !isBlank(row.rate_default) && isFinite(Number(row.rate_default))) return num(row.rate_default);
    return null;
  }

  /** A rate the estimator TYPED on this bid: a box that is not blank and either not the line's own default or
   *  marked typed (`rate_typed`, see setLaborRate: the one case a number alone cannot tell, a typed rate that
   *  IS the line's default). Typing 0 counts (0 means zero). A row with no default to compare to (a saved bid
   *  from before the stamp) holds a rate that cannot be told from a typed one, so it is treated as typed and
   *  no prevailing wage moves it. */
  function rateTypedByHand(row) {
    if (!row || isBlank(row.rate)) return false;
    if (row.rate_typed === true) return true;
    var own = ownDefaultRate(row);
    return own === null || num(row.rate) !== own;
  }

  /** THE ESTIMATOR TYPES A RATE ON A LABOR LINE: the one place the Rate box is written into a row.
   *  The rate goes in as typed. A rate that differs from the line's own default is already known as typed
   *  (rateTypedByHand reads the two numbers), but a rate typed to the line's own default looks exactly like a
   *  line that is following it, and while a prevailing wage is in force a following line is repriced. So
   *  that one case is marked on the row (`rate_typed`), and the mark goes the moment the rate is anything
   *  else, blank included: nothing is written onto a row whose rate says it all by itself. */
  function setLaborRate(row, value) {
    if (!row || typeof row !== "object") return;
    row.rate = value;
    var own = ownDefaultRate(row);
    if (!isBlank(value) && own !== null && num(value) === own) row.rate_typed = true;
    else delete row.rate_typed;
  }

  /** Is this the Travel Labor row? It is the one labor line the prevailing wage never touches: the
   *  sheet keeps its own rate (Polish C44 and Epoxy C52 are $33), and a drive is not paid as a trade. */
  function isTravelRow(row) { return !!row && String(row.id) === "travel"; }

  /** DOES THIS LINE'S RATE FOLLOW THE PREVAILING WAGE? Yes when a prevailing rate is in force, the line
   *  is a crew line (anything but Travel Labor, a Gyp pour included) and nobody typed a rate over it. */
  function laborFollowsPrevailing(row, pw) {
    return num(pw) > 0 && !isTravelRow(row) && !rateTypedByHand(row);
  }

  /** What the Rate box on a labor card holds: the prevailing rate while the line follows it, else the
   *  rate as stored (a blank stays blank). The box and the cost beside it are one figure. */
  function laborRateBox(row, pw) {
    return laborFollowsPrevailing(row, pw) ? num(pw) : (row || {}).rate;
  }

  // ── THE PREVAILING WAGE CALCULATOR (Hanz, 2026-10-15) ───────────────────────
  // Kyle's workbook has a small calculator on every priced tab (Polish!I47:L54, Epoxy!I55:L62, Gyp K54:N66),
  // two identical boxes, Cement Mason and Painter:
  //   J48  Prevailing Wage Rate     =SUM(J49:J50)             rate (J49) + fringes (J50)
  //   J53  1:1 "Entry" Half Wage    =IF((J48/2)<23,23,(J48/2))   "Entry" Laborer for MO "State" Wage ONLY,
  //                                                              NOT davis-bacon
  //   I51/I52  notes: Foreman *min. $32, (Entry *min. $23)
  // NOTHING in the sheet reads those cells: the estimator types the rate into the labor Rate box (Polish C37,
  // Epoxy C47) by hand, and D5 PrevailingWage? only adds the 5% escalation (C46). The v2 Labor step's card
  // does what the estimator did by hand: it works the rate out and sets the crew lines to it.
  // AS MANY TRADES AS THE JOB NEEDS (Hanz, 2026-10-15: "there is a prevailing wage for others apart from the
  // painter and mason ... we can label it on our own"). Cement Mason and Painter are always there, the sheet's
  // two boxes; any other trade is added with a name the estimator types. Each trade works out its own figures,
  // and ONE of them is the rate the crew is paid (`trade`), as the sheet has one typed Rate box per tab. No crew
  // blending (Hanz: "we dont need specifics, just the calculator").
  /** The two figures of the calculator that are not typed, as named constants: the "Entry" wage floor
   *  (J53) and the foreman minimum (the note beside it). Shown as text; the foreman figure prices nothing. */
  var PREVAILING = Object.freeze({ ENTRY_MIN: 23, FOREMAN_MIN: 32 });
  /** The two boxes the workbook draws, always on the card, first and in this order. Other trades are the
   *  estimator's own, added beside them. */
  var PREVAILING_TRADES = Object.freeze([
    Object.freeze({ key: "cement_mason", label: "Cement Mason" }),
    Object.freeze({ key: "painter", label: "Painter" })
  ]);

  /** A trade the estimator added: its key is minted here ("t" + letters and digits), never typed. */
  var PREVAILING_OWN_KEY = /^t[0-9a-z]{1,24}$/;
  /** How long a trade's own name may be. */
  var PREVAILING_LABEL_MAX = 60;

  function isBuiltinTrade(key) {
    for (var i = 0; i < PREVAILING_TRADES.length; i++) if (PREVAILING_TRADES[i].key === key) return true;
    return false;
  }

  /** A key for a trade the estimator adds, not already used on this card. */
  function newPrevailingTradeKey(p) {
    var used = {};
    ((normalizePrevailing(p) || {}).trades || []).forEach(function (t) { used[t.key] = true; });
    for (var n = 1; ; n++) if (!used["t" + n]) return "t" + n;
  }

  /** A saved `prevailing` block read as a full one, or null when the model has none (and then nothing
   *  is added: a bid that never used the card prices and saves exactly as before).
   *
   *  { trade: <the key the crew is paid at>, trades: [{ key, label, rate, fringes }, ...] }
   *  Cement Mason and Painter always come first; the estimator's own trades follow in the order they were
   *  added, each with the name typed for it. Rate and fringes are kept AS TYPED (a half-typed "12." must
   *  not snap back to 12), or "" when blank.
   *
   *  THE FIRST SHAPE ({ trade, rate, fringes }, one trade per bid, staging only 2026-10-15) is read into
   *  this one: its rate and fringes go on its trade, and that trade stays the one the crew is paid. Never throws. */
  function normalizePrevailing(p) {
    if (!p || typeof p !== "object" || p instanceof Array) return null;
    var box = function (v) { return (typeof v === "number" || typeof v === "string") && !isBlank(v) ? v : ""; };
    var saved = p.trades instanceof Array ? p.trades : [];
    // Only a key this card can have is kept (a built-in, or one minted as "t" + digits), in a Map rather than an
    // object: a saved blob is data a person can hand-edit, and a key such as "__proto__" must never become a property.
    var byKey = new Map();
    saved.forEach(function (t) {
      if (!t || typeof t !== "object" || typeof t.key !== "string") return;
      if (!isBuiltinTrade(t.key) && !PREVAILING_OWN_KEY.test(t.key)) return;
      if (!byKey.has(t.key)) byKey.set(t.key, t);
    });
    var trades = PREVAILING_TRADES.map(function (b) {
      var t = byKey.get(b.key) || {};
      return { key: b.key, label: b.label, rate: box(t.rate), fringes: box(t.fringes) };
    });
    saved.forEach(function (t) {
      if (!t || typeof t !== "object" || byKey.get(t.key) !== t || isBuiltinTrade(t.key)) return;
      if (typeof t.key !== "string" || !PREVAILING_OWN_KEY.test(t.key)) return;
      var label = typeof t.label === "string" ? t.label.slice(0, PREVAILING_LABEL_MAX) : "";
      trades.push({ key: t.key, label: label, rate: box(t.rate), fringes: box(t.fringes) });
    });
    if (!(p.trades instanceof Array) && ("rate" in p || "fringes" in p)) {
      var legacy = trades[0];
      for (var i = 0; i < trades.length; i++) if (trades[i].key === p.trade) legacy = trades[i];
      legacy.rate = box(p.rate);
      legacy.fringes = box(p.fringes);
    }
    var pick = trades[0].key;
    for (var j = 0; j < trades.length; j++) if (trades[j].key === p.trade) pick = p.trade;
    return { trade: pick, trades: trades };
  }

  /** The trade the crew is paid at, out of a block (normalised first), or null when there is no block. */
  function prevailingCrewTrade(p) {
    var n = normalizePrevailing(p);
    if (!n) return null;
    for (var i = 0; i < n.trades.length; i++) if (n.trades[i].key === n.trade) return n.trades[i];
    return n.trades[0];
  }

  /** J48: the prevailing wage rate, rate plus fringes, 0 while nothing is typed. Given ONE trade
   *  ({ rate, fringes }) it is that trade's figure; given a whole block it is the figure of the trade the
   *  crew is paid at. */
  function prevailingTotal(p) {
    if (!p || typeof p !== "object") return 0;
    if (p.trades instanceof Array) p = prevailingCrewTrade(p) || {};
    return parseFloat((num(p.rate) + num(p.fringes)).toPrecision(12));
  }

  /** J53: the 1:1 "Entry" half wage, half the prevailing rate and never under the $23 floor. The
   *  sheet's own formula, so an empty calculator reads 23 here as it does there; the card shows it
   *  only once a prevailing rate is set. */
  function entryHalfWage(total) {
    var half = num(total) / 2;
    return half < PREVAILING.ENTRY_MIN ? PREVAILING.ENTRY_MIN : half;
  }

  /** THE PREVAILING RATE IN FORCE for a job: the card's rate plus fringes while the job's prevailing
   *  wage switch is on (conditions.prevailing_wage, the one flag the intake and the Review step use),
   *  and 0 otherwise. 0 means "no prevailing wage", and every labor price then reads as it always has. */
  function prevailingApplied(model) {
    if (!model || typeof model !== "object") return 0;
    if (!(model.conditions && model.conditions.prevailing_wage)) return 0;
    var total = prevailingTotal(model.prevailing);
    return total > 0 ? total : 0;
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

  /** `labor` with each row that has a saved mode given its RATE and hours a day -- NEW BIDS ONLY (the
   *  caller's gate is laborUnstated, the same one that guards every other default). A NEW array of
   *  NEW rows. Guys and Days are NOT filled (Hanz, 2026-10-12): they start empty and are typed.
   *  The values written are also kept on the row as `calc_default`, which is what the estimate's
   *  "Default value: N" warning compares against (an empty default names nothing): once saved, the
   *  bid keeps its own numbers and nothing here ever runs on it again. Travel (an hours row) is
   *  never touched. */
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
      // GUYS AND DAYS ARE NOT FILLED (Hanz, 2026-10-12: "nights, days, guys and hours should have
      // nothing when it starts"). A new bid takes the calculator's RATE and hours a day and nothing
      // else; how many guys and how many days is the estimator's to type. So the "From SF" marker
      // (sf_per_day, which made Days follow the takeoff) is not written either: there is no filled
      // Days for it to follow. laborCalcValues still works the full figures out for the Calculator
      // page's "Try it" box.
      var copy = copyInto({}, r);
      copy.guys = ""; copy.days = ""; copy.rate = v.rate; copy.hours_per_day = v.hours_per_day;
      copy.calc_default = { guys: "", days: "", rate: v.rate, hours_per_day: v.hours_per_day };
      out[i] = copy;
    }
    return out;
  }

  /** A LIBRARY LINE'S OWN RATE BEATS THE COMPANY RATE EVEN WHEN THE CALCULATOR FILLED IT. The
   *  calculator's blank rate means "the company rate", and applyLaborCalc stamps that over the row;
   *  but a rate an admin typed on the Labor tab (a Polishing at $40) is the line's own, and the
   *  calculator row carries none. Run after applyLaborCalc, NEW BIDS ONLY, on the rows seedLibraryLabor
   *  took from `libRows`: a row whose calculator mode has no rate of its own and whose library row
   *  does gets that rate, in both the row and its calc_default so no "Default value" warning shows.
   *  A NEW array of NEW rows where changed. */
  function keepLibraryRates(labor, libRows, cfgs) {
    var out = (labor instanceof Array) ? labor.slice() : [];
    var lib = {}, cfg = {};
    (libRows instanceof Array ? libRows : []).forEach(function (l) { if (l && l.id != null) lib[String(l.id)] = l; });
    (cfgs instanceof Array ? cfgs : []).forEach(function (c) { if (c && c.line_id) cfg[String(c.line_id)] = c; });
    for (var i = 0; i < out.length; i++) {
      var r = out[i];
      if (!r || !r.calc_default || r.id === "travel") continue;
      var l = lib[String(r.id)], c = cfg[String(r.id)];
      if (!l || !c || num(c.rate) > 0 || !libraryRateIsOwn(l, isCrewId(l.id))) continue;
      var copy = copyInto({}, r), dc = copyInto({}, r.calc_default);
      copy.rate = Number(l.rate);
      dc.rate = Number(l.rate);
      copy.calc_default = dc;
      out[i] = copy;
    }
    return out;
  }

  /** G2: LABOR DAYS FOLLOW THE TAKEOFF, the same pattern as coverage (untouched follows the source,
   *  edited keeps the bid's number). A row carrying the marker `calc_default.sf_per_day` whose Days
   *  still read what the calculator filled is moved to ceil(sf / sf_per_day) -- blank while there
   *  is no SF -- and its calc_default.days moves with it, so the "Default value" warning stays
   *  quiet. A row whose Days the estimator changed keeps its number. Rows without the marker (every
   *  fixed line, every row on a saved bid from before this) are never touched. The caller runs it
   *  only when the takeoff SF CHANGED in this session, so opening a saved bid moves nothing.
   *  A NEW array; rows that do not move are the same objects. */
  function followLaborDays(labor, sf) {
    var out = (labor instanceof Array) ? labor.slice() : [];
    var area = num(sf);
    for (var i = 0; i < out.length; i++) {
      var r = out[i], d = r && r.calc_default;
      if (!d || !(num(d.sf_per_day) > 0)) continue;
      var untouched = (isBlank(r.days) && isBlank(d.days)) ||
        (!isBlank(r.days) && !isBlank(d.days) && num(r.days) === num(d.days));
      if (!untouched) continue;
      var next = area > 0 ? Math.ceil(area / num(d.sf_per_day)) : "";
      if (next === d.days) continue;
      var copy = copyInto({}, r), dc = copyInto({}, d);
      dc.days = next;
      copy.days = next;
      copy.calc_default = dc;
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
  function laborTotal(rows, conditions, pw) {
    rows = rows || [];
    var t = 0;
    for (var i = 0; i < rows.length; i++) t += laborCost(rows[i], pw);
    return t + removeExistingHand(rows, conditions, pw);
  }

  /** REMOVE EXISTING JOINT FILLER = A FOURTH HAND ON THE JOINT-FILLER LINE (Polish A42 is
   *  `=IF(F29="NO",3,4)`). The crew row keeps its own typed Guys; the extra hand is one more guy
   *  for the same days at the same rate, so its cost is that row priced at 1 guy. It needs joint
   *  filler ON (no filler, no crew to add a hand to), and it follows the row's own on/off switch
   *  because laborCost does. Absent `conditions` adds nothing, so every caller that predates this
   *  prices exactly as before. */
  function removeExistingHand(rows, conditions, pw) {
    if (!conditions || !conditions.joint_filler || !conditions.remove_existing_jf) return 0;
    rows = rows || [];
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i] || {};
      if (r.id !== "jointfill") continue;
      // The extra hand is paid the line's rate, the prevailing one included: it is read here, so the
      // copy below carries a typed number and never has to say whether it was typed.
      return laborCost({ guys: 1, days: r.days, rate: laborRateOf(r, pw), unit: r.unit,
                         hours_per_day: r.hours_per_day, enabled: r.enabled });
    }
    return 0;
  }

  /** THE TWO TRAVEL COSTS BESIDE TRAVEL LABOR: LODGING (a night) and PER DIEM (a day). Hanz,
   *  2026-10-05: "separate line for Travel Lodging and Per Diem", priced INSIDE the markups like
   *  Kyle's sheet D61 -- they join the sub-total (D64) that GP, super/PTO and soft costs are taken
   *  on, and are NOT labor (no escalation, no burden). They live on the model as `M.travel`,
   *  `{lodging: line, per_diem: line}`, each `{label, enabled, qty, qty_auto, rate}`, and not as rows
   *  of M.labor, because a labor row is guys x days x rate x 8 and neither of these is.
   *
   *  THE QUANTITY. Nights (and days of food) are the crew's man-days on Kyle's sheet and in
   *  backend/pricing.py (`nights = labor man-days`, one lodging and one meal charge per man per
   *  night). A NEW bid does NOT count them (Hanz, 2026-10-12): its lines open with an empty quantity
   *  and `qty_auto` false (travelLinesStartEmpty), and a line switched on with nothing typed is $0.
   *  A bid SAVED before then keeps `qty_auto` true and still follows travelManDays until the
   *  estimator types a number; typing is how you leave auto, and clearing the box leaves it empty.
   *  An OFF line, or an absent `travel`, is $0.
   *
   *  THE RATES are the Global markup_rules rows (set on Items & Assemblies -> Labor) `travel_lodging` ($70) and `travel_per_diem` ($45),
   *  copied onto a NEW bid when it opens (applyTravelRates) and never again, so a rate edited later
   *  reaches new bids and leaves saved ones alone. 70 and 45 are Kyle's literals and what stands
   *  when nothing is filed.
   *
   *  BOTH START OFF (Hanz's decision, 2026-10-05): a bid that never leaves town pays nothing for a
   *  hotel, and an old saved bid opened after this shipped is not repriced. */
  var SHIPPED_LODGING_RATE = engine.defaultNumber("travel_lodging");
  var SHIPPED_PER_DIEM_RATE = engine.defaultNumber("travel_per_diem");
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

  /** What a line is charged for: the typed quantity, or the crew's man-days while it is auto. `opts.sheetNights` (a
   *  polish-rev2 bid's) counts the auto quantity the sheet's way instead: from the labor dollars (sheetNights). */
  function travelQty(line, rows, opts) {
    line = line || {};
    if (line.qty_auto === false) return num(line.qty);
    if (opts && opts.sheetNights) return sheetNights(rows, opts.conditions, opts.prevailing);
    return travelManDays(rows);
  }

  /** NIGHTS OF LODGING THE WAY KYLE'S SHEET COUNTS THEM (Polish!B58 `=IF(B4="No",((D45-D44)/C37)/8)`, and B59 is `=B58`
   *  for the per diem): the labor dollars that are not travel labor, over the rate of the first crew row (C37), over
   *  an 8 hour day. It is guys x days (travelManDays) while every row is paid that rate, and more once a row is paid
   *  another (a prevailing wage row), because the extra pay reads as extra days. The divide is the engine's own, so
   *  the chain and this are one formula (bid-engine nightsOf). Money, not people: used for polish-rev2 only. */
  function sheetNights(rows, conditions, pw) {
    rows = rows || [];
    var travelLabor = 0, rate = 0;
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i] || {};
      if (r.unit === "hours") { travelLabor += laborCost(r, pw); continue; }
      if (!rate && rowOn(r) && laborRateOf(r, pw) > 0) rate = laborRateOf(r, pw);
    }
    return engine.lodgingNights(REV2, roundUp(laborTotal(rows, conditions, pw)), travelLabor, rate || SHIPPED_LABOR_RATE);
  }

  /** One travel line's cost, ROUNDED UP TO THE DOLLAR like pricing.py's D68 (each of lodging and
   *  food is its own ROUNDUP there). An off line is 0. */
  function travelLineCost(line, rows, opts) {
    if (!line || !rowOn(line)) return 0;
    return roundUp(travelQty(line, rows, opts) * num(line.rate));
  }

  /** Both lines and their sum. `travel` may be absent (an old model that never migrated). */
  function travelCosts(travel, rows, opts) {
    var t = travel || {};
    var lodging = travelLineCost(t.lodging, rows, opts);
    var per_diem = travelLineCost(t.per_diem, rows, opts);
    return { lodging: lodging, per_diem: per_diem, total: lodging + per_diem };
  }

  /** AN OPTION'S OWN LODGING AND PER DIEM. The job's two lines are charged once, on the carrier section, for the carrier's
   *  crew. An option is priced apart and the workbook charges it its own: the Seal tabs read Local = No and bill Lodging and
   *  Per Diem for their own man-days (Seal!B58 and B59). So an OPTION takes the job's two lines AS THEY ARE SWITCHED (on for a
   *  job 70 miles out, gray for a local one, a hand flip kept) at the job's rates, for the option's own crew's man-days. The
   *  typed quantity belongs to the carrier's crew and is not used here. */
  function optionTravelCosts(travel, rows) {
    var t = travel || {};
    var days = travelManDays(rows);
    function ownLineCost(line) { return (line && rowOn(line)) ? roundUp(days * num(line.rate)) : 0; }
    var lodging = ownLineCost(t.lodging);
    var per_diem = ownLineCost(t.per_diem);
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
      copyInto(next, keep);
      if (!(isFinite(Number(keep.rate)) && Number(keep.rate) > 0 && Number(keep.rate) !== shipped)) {
        next.rate = out[k].rate;
      }
      out[k] = next;
    });
    // G3: each line remembers the rate it was filled with (the Items & Assemblies -> Labor figure, or the
    // shipped one when none is filed), which is what the "Default value" warning compares against.
    TRAVEL_LINE_KEYS.forEach(function (k) { out[k].rate_default = num(out[k].rate); });
    return out;
  }

  /** A NEW bid's Lodging and Per Diem with their quantities empty (Hanz, 2026-10-12: "nights, days,
   *  guys and hours should have nothing when it starts"). The rate stays; the quantity is typed, and
   *  a line switched on with nothing typed prices $0. Not on auto, so the man-days never fill it in
   *  behind the estimator's back. This departs from Kyle's sheet, which counts nights and days from
   *  the man-days. A NEW object; the one handed in is never touched. */
  function travelLinesStartEmpty(travel) {
    var out = copyInto({}, travel || {});
    TRAVEL_LINE_KEYS.forEach(function (k) {
      if (!out[k] || typeof out[k] !== "object") return;
      var line = copyInto({}, out[k]);
      line.qty_auto = false;
      line.qty = "";
      out[k] = line;
    });
    return out;
  }

  /** A NEW bid's labor row with its quantities empty: no guys, no days or hours, and not on auto
   *  (guys_auto false is what stops syncAutoGuys writing the man-days into an hours row), and none of
   *  the markers a far distance answer or the estimator's typing leaves on Travel Labor: no hours_seed,
   *  no guys_follow, no guys_typed, no hours_typed (nothing has been written or typed yet;
   *  followDistanceHours writes them later). The library row's own guys_auto stays what the library
   *  says (libraryLaborRow is one faithful mapping); it is this step, the one that opens a new bid,
   *  that decides the man-days fill nothing -- until a far distance answer puts Travel Labor's guys on
   *  the crew's size (2026-10-20). The rate and the rest of the row stay. A copy; the row handed in is
   *  never touched. */
  function laborRowStartsEmpty(row) {
    return clearQuantities(copyInto({}, row));
  }

  /** A labor row's quantities put back to nothing, IN PLACE: no guys, no days or hours, off auto, and none of the markers a far
   *  distance answer or the estimator's typing leaves on Travel Labor (hours_seed, guys_follow, guys_typed, hours_typed). The one
   *  statement of "a row with nothing in it", for a NEW bid's rows (laborRowStartsEmpty) and for the Travel Labor row an old carrier
   *  gives back when the job's drive moves to another section (takeBackStrayTravel). */
  function clearQuantities(row) {
    row.guys = ""; row.days = ""; row.guys_auto = false;
    delete row.hours_seed; delete row.guys_follow; delete row.guys_typed; delete row.hours_typed;
    return row;
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
      // The rate a NEW bid's line was filled with (applyTravelRates); absent on every saved line.
      if (!isBlank(l.rate_default) && isFinite(Number(l.rate_default))) {
        out[k].rate_default = Number(l.rate_default);
      }
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
   *  Travel Labor is also FILLED on a far job, its hours from the miles and its guys from the
   *  crew's size (followDistanceHours, below); Lodging and Per Diem are only switched.
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
    // Travel Labor's own two boxes follow the answer as well (Hanz, 2026-10-20).
    followDistanceHours(model, miles);
    return model;
  }

  /** One round trip from the Olathe office to the job at DRIVE_MPH, to the half hour: the hours a far answer writes into
   *  Travel Labor (190 miles -> 6.5). "" under LOCAL_MILES, and when there are no usable miles. The rules for what is done
   *  with it are written out above followDistanceHours. */
  var DRIVE_MPH = 60;
  function driveHoursFor(miles) {
    var m = milesOrNull(miles);
    if (m === null || m < LOCAL_MILES) return "";
    return Math.ceil((2 * m / DRIVE_MPH) * 2) / 2;
  }

  /** The job's Travel Labor row and the rows beside it (the man-days are theirs), or null when the bid
   *  has none to fill: no Travel Labor row, or a Gyp carrier. A one-section bid is its own carrier. */
  function travelLaborHeld(model) {
    if (!isObject(model)) return null;
    var holder = model, layout = "polish";
    if (isObject(model.tabs)) {
      try {
        var carrier = sectionOf(model, travelCarrier(model));
        holder = carrier.section;
        layout = carrier.layout;
      } catch (err) { holder = model; }
    }
    if (layout === "gyp") return null;
    var rows = holder && holder.labor instanceof Array ? holder.labor : [];
    for (var i = 0; i < rows.length; i++) {
      if (isTravelRow(rows[i]) && rows[i].unit === "hours") return { row: rows[i], rows: rows };
    }
    return null;
  }

  /** Is this Travel Labor row's Guys box on the CREW'S SIZE? It is on auto (guys_auto) and carries the
   *  `guys_follow: "crew"` marker followDistanceHours writes when a far answer fills it. A row on auto WITHOUT
   *  the marker is the older kind, a bid saved before 2026-10-12, and its guys are the man-days, as they always were. */
  function followsCrew(row) {
    return !!row && !!row.guys_auto && row.guys_follow === "crew";
  }

  /** THE CREW'S SIZE, which is what Travel Labor's Guys are on a job the distance sent far (Hanz, 2026-10-20, from Kyle's
   *  own sheets: see followDistanceHours): the most guys on any ONE labor line of the base sections the job is priced
   *  on, other than Travel Labor itself. A line with no guys counts 0, a line switched off is not driving anywhere, and
   *  the fourth hand of "Remove existing joint filler" counts through the joint-filler line: the model keeps that hand
   *  as one more guy on that line (removeExistingHand) and not in the line's own Guys, so it is added here when it applies.
   *  A bid with several base sections (Combo: one Epoxy and one Polish) has ONE crew that drives once, so the
   *  most is taken over all of them; a bid with no base reads the carrier's. A model with no `tabs` is its own
   *  one section. Pass the WHOLE model, never a section view: a view answers `labor` from the section on show. */
  function crewSize(model) {
    if (!isObject(model)) return 0;
    var lists = [];
    var entries = isObject(model.tabs) ? readableSections(model) : null;
    if (entries) {
      var live = entries.filter(function (e) { return e.kind !== "off"; });
      var bases = live.filter(function (e) { return e.kind === "base"; });
      (bases.length ? bases : live.slice(0, 1)).forEach(function (e) { lists.push(e.section.labor); });
    }
    if (!lists.length) lists.push(model.labor);
    var cond = isObject(model.conditions) ? model.conditions : {};
    var most = 0;
    lists.forEach(function (rows) { most = mostGuysOn(rows, cond, most); });
    return most;
  }

  /** The most guys on any ONE line of `rows`, or `most` when no line beats it: the reading crewSize takes of every list it is
   *  given. Travel Labor is never one of the lines and a line switched off is not driving anywhere. `cond` is the job's
   *  conditions (the fourth hand of Remove existing joint filler counts through the joint-filler line). */
  function mostGuysOn(rows, cond, most) {
    (rows instanceof Array ? rows : []).forEach(function (r) {
      if (!r || isTravelRow(r) || !rowOn(r)) return;
      var guys = num(r.guys);
      if (!(guys > 0)) return;
      if (r.id === "jointfill" && cond.joint_filler && cond.remove_existing_jf) guys += 1;
      if (guys > most) most = guys;
    });
    return most;
  }

  /** THE CREW OF AN OPTION is its OWN labor lines' (Hanz, 2026-10-20 audit). An option is priced apart, with its own Lodging and
   *  Per Diem for its own crew (optionTravelCosts) and, when it was copied from the carrier, its own Travel Labor row; that row's
   *  guys follow the option's own lines and not the base crew the job's one drive is charged for (crewSize). */
  function ownCrewSize(model, rows) {
    return mostGuysOn(rows, isObject(model) && isObject(model.conditions) ? model.conditions : {}, 0);
  }

  /** How many base sections the job is priced on: 2 for a Combo, else 1. A model with no readable `tabs` is one. */
  function baseCount(model) {
    var entries = isObject(model) && isObject(model.tabs) ? readableSections(model) : null;
    if (!entries) return 1;
    return Math.max(1, entries.filter(function (e) { return e.kind === "base"; }).length);
  }

  /** Where the crew's size is read from, in words for a note: "the labor lines above" for a job with one base
   *  sheet, "the labor lines of the base sheets" for a Combo, whose one crew is the biggest of both. A row on an option (`own`)
   *  reads its own section's lines, which are the ones above it, whatever the job. */
  function crewWhere(model, own) {
    return !own && baseCount(model) > 1 ? "the labor lines of the base sheets" : "the labor lines above";
  }

  /** Is the figure in this Travel row's Hours box the one the distance wrote? `hours_seed` holds what
   *  the tool wrote, and the figure still being that number is what makes it the tool's to move. A
   *  number on both sides: what the estimator types in the box is text, so it is never taken for the
   *  tool's, whatever digits it spells. A box the estimator has typed in (`hours_typed`) is never the tool's. */
  function driveHoursAreTools(row) {
    return !!row && row.hours_typed !== true && typeof row.days === "number" && typeof row.hours_seed === "number" && row.days === row.hours_seed;
  }

  /** THE ESTIMATOR TYPES IN A TRAVEL LABOR BOX, Guys or Hours, by any input and clearing the box included: mark the
   *  box as theirs, on the row, so no later distance answer ever writes into it (Hanz, 2026-10-12: a cleared box stays
   *  empty; 2026-10-20 audit: an answer was refilling one). `key` is the box: "guys", or "days" for the Hours box.
   *  Typing in the Guys box also takes the box off the crew's size (the marker goes; the page turns guys_auto off).
   *  The marker is saved with the row, so the rule holds after a reopen. Only the Travel Labor row is marked; any
   *  other row is returned as it is. MUTATES the row. */
  function markTypedByHand(row, key) {
    if (!isTravelRow(row)) return row;
    if (key === "guys") { row.guys_typed = true; delete row.guys_follow; }
    else if (key === "days") { row.hours_typed = true; }
    return row;
  }

  /** THE DISTANCE FILLS TRAVEL LABOR, ON A JOB 70 MILES OR MORE OUT, THE WAY KYLE TYPES IT (Hanz, 2026-10-20: "For jobs
   *  outside the local scope we need to automatically turn on travel time ... it would auto calculate based on the miles
   *  from the treadwell office ... its just an estimate though"). Fills (or takes back) Travel Labor for a distance
   *  answer of `miles` (a number, or null when the distance is cleared). MUTATES the model; pass the WHOLE model.
   *
   *  THIS REVERSES 2026-10-12 FOR THAT ONE LINE. From 2026-10-06 the answer wrote a round trip at DRIVE_MPH into a new
   *  bid's Travel Labor hours (150 mi -> 5); on 2026-10-12 it was stopped, with everything else a new bid opened with
   *  ("nights, days, guys and hours should have nothing when it starts"). A far answer fills Travel Labor again, and
   *  only Travel Labor: Lodging and Per Diem still open empty and are typed, and a job under 70 miles still opens with nothing.
   *
   *  WHAT KYLE'S SHEETS SHOW. The template's Travel row (Polish row 44, Epoxy row 52) is Guys = (A37*B37)+(A38*B38)+... --
   *  the crew's MAN-DAYS -- times Hours, which he types beside his note "Drive Time: ?", times $33. The first version of this
   *  fill took that formula at its word (every guy on every work day). A read-only scan of every estimate workbook in his
   *  Dropbox (2026-10-20: 276 out-of-town jobs, 489 real sheets) shows that on 9 of 10 out-of-town sheets he TYPED OVER
   *  that formula with the crew size, so each guy is charged ONE round trip, and typed the round trip's drive hours
   *  (median 5.5; most often 4, 6, 5.5, 7 and 5), while hotel and food were still charged for every man-day on the same
   *  jobs. A far answer therefore fills the line's two boxes the way he types them:
   *    Hours  driveHoursFor(miles): one round trip at DRIVE_MPH, to the half hour (190 miles -> 6.5);
   *    Guys   the CREW'S SIZE (crewSize), on auto with the marker `guys_follow: "crew"`, so syncAutoGuys keeps them in
   *           step as the crew is typed.
   *  Wichita, 190 miles, four guys for twelve days: 4 guys x 6.5 hours x $33 = $858 (the man-days, 48, are not the guys).
   *  A long job drives home more than once; the estimator types more trips into Hours.
   *
   *  A TYPED FIGURE ALWAYS WINS, AND SO DOES A CLEARED ONE. A box nobody has touched takes the answer. A box the estimator
   *  has typed in, clearing it included, never does again (markTypedByHand leaves the marker, saved with the row). The
   *  hours the tool wrote are remembered too (`hours_seed`, a number; hours typed in the box arrive as text), so a later
   *  answer moves the tool's own figure and no other. Under 70 miles, or with the miles cleared, the hours the tool wrote
   *  go back to empty and the line grays as it always did; typed hours stay. The guys keep following the crew
   *  either way: a count that prices nothing without hours.
   *
   *  A ROW ON THE OLD MAN-DAYS AUTO (guys_auto, no marker: every bid saved before 2026-10-12, and the model's own shipped row, which is
   *  what a Polish root that was never seeded still holds) IS LEFT ALONE WHILE A BID MERELY OPENS: syncAutoGuys keeps its guys on the
   *  man-days they followed, so it prices as it always did. An answer applied in a session that FILLS such a row's hours (the Hours
   *  box is empty or still the tool's own figure) puts it on the crew's size like every other row it fills, and the marker is written
   *  with it. Leaving its guys on the man-days would charge every man-day a round trip the moment the hours arrived: $10,296 for a
   *  190 mile job that Kyle types as $858 (the 2026-10-20 audit's Epoxy to Polish switch: 49.5 man-days x 6.5 x $33 = $10,617.75).
   *  Guys somebody typed (guys_typed, or a figure in a box that is not on auto) are never converted, and neither is a row whose hours
   *  were typed and so was not filled: its figures are the estimator's.
   *
   *  A ROW SWITCHED OFF IS LEFT EXACTLY AS IT IS, whether the slider on its card or the Defaults tab's switched it: no
   *  fill, no take-back, no note. The Labor step says once that travel time is off for this bid (travelHow).
   *
   *  A SAVED BID NEVER MOVES ON OPEN. Nothing here runs when a bid opens. It runs when an answer is APPLIED in a session
   *  (applyDistance, clearDistance): the estimator typing miles, asking for the lookup, or a NEW bid's own lookup after its first
   *  paint; and when the job type is switched in the session (the intake's choice reaching the estimate page, or a base change
   *  on the Sheets panel) so that the bid has a new carrier (followDistance).
   *
   *  WHERE IT LANDS. The job's Travel Labor row lives on the section that carries the job's travel (travelCarrier), so that
   *  is the row filled. Pass the WHOLE model: a section view (sectionView) answers `labor` from the section on show, which is
   *  not the carrier's when another section is open. A Gyp carrier is left alone: its crew is priced by the hour in ten hour
   *  days, and the Gyp sheet works its own drive time per mobilization (js/gyp-takeoff.js sheetHours), so a Gyp bid's Travel
   *  Labor is typed. */
  function followDistanceHours(model, miles) {
    var held = travelLaborHeld(model);
    if (!held) return;
    var row = held.row;
    if (!rowOn(row)) return;   // switched off: no fill and no take-back
    var hours = driveHoursFor(miles), wrote = driveHoursAreTools(row);
    if (hours === "") {
      // Local, or no distance: only the hours the tool wrote go back to empty; typed ones stay.
      if (wrote) { row.days = ""; row.hours_seed = ""; }
      return;
    }
    // A far job. Hours: a box nobody has typed in takes the answer when it is empty or still the tool's own figure.
    var fills = !row.hours_typed && (isBlank(row.days) || wrote);
    if (fills) { row.days = hours; row.hours_seed = hours; }
    // Guys: a box nobody has typed in, and not on the older man-days auto, goes on the crew's size and follows it.
    if (!row.guys_typed && !row.guys_auto && !filledIn(row.guys)) { row.guys_auto = true; row.guys_follow = "crew"; }
    // A row on the older man-days auto that this answer fills goes on the crew's size too (see above): the marker is what moves it.
    if (!row.guys_typed && row.guys_auto && !row.guys_follow && fills) row.guys_follow = "crew";
    if (followsCrew(row)) row.guys = crewSize(model);
    else if (row.guys_auto) row.guys = travelManDays(held.rows);   // the older auto the answer did not fill: the man-days, as syncAutoGuys keeps them
  }

  /** THE JOB'S ONE DRIVE, SETTLED AFTER A RESTRUCTURE (the 2026-10-20 audits). The job type was switched in the session (js/polish-estimate.js: init,
   *  after sectionsForJob) or the Sheets panel made another sheet the base (makeBase), so sections changed kind and the one that carries the job's
   *  travel may have changed with them. The page calls this after EVERY such restructure, whether or not the carrier moved, and says in `fromTab` which
   *  section carried the job's travel BEFORE it. Left out, the caller does not know, and the carrier is taken to have moved (the stranded row is looked
   *  for: strandedTravelTab). MUTATES the model and returns it. Never called when a bid merely opens: a saved bid never moves on open.
   *
   *  THE RULE (Hanz, 2026-10-20). On a job 70 miles or more out there is exactly ONE priced drive: the carrier's Travel Labor row, the crew's size x one
   *  round trip's hours x its rate (followDistanceHours). Hotel and Per Diem stay as they were. What the estimator typed, a box they cleared and a row
   *  they switched off are theirs: never refilled, and they follow the job's drive when the carrier changes. In this order:
   *    1. THE ROW GOES WITH THE CARRIER (carryTravelRow). A new carrier that has no Travel Labor row takes the old carrier's, the way pickBase moves it:
   *       a Combo switched to Epoxy left the filled row stranded on the off Polish root while Lodging and Per Diem stayed on.
   *    2. WHAT THE ESTIMATOR SAID FOLLOWS (followOwnedRow). A new carrier that has a row nobody touched takes the old carrier's row when the old one is
   *       the estimator's (typed figures and their markers, a cleared box, a switch turned off): the audit found a typed 3 x 5 stay behind on the Epoxy
   *       section while the new carrier was filled with the crew's size beside it ($858 + $495), and a cleared or switched-off row refilled to $858.
   *    3. THE DISTANCE ON FILE FILLS THE NEW CARRIER'S ROW, by the rule above: only a row nobody touched takes it. Done only when the carrier MOVED: a
   *       restructure that keeps the carrier (a Combo made Polish) fills nothing, so a bid saved with a blank row is not filled by it.
   *    4. EVERY OTHER SECTION GIVES THE DRIVE BACK (takeBackStrayTravel). A Travel Labor row the distance filled and nobody touched, on any section that
   *       is not the carrier and is not an option, off sections included, is emptied and loses its fill markers (and so is the estimator's row that only
   *       repeats the carrier's, which is what a copy of the carrier's sheet carries once it is made a base beside it). It was only ever taken back from a
   *       base, and only when the carrier moved, so Epoxy to Polish to Combo left Epoxy's filled row on the off section until Combo turned it back on, and
   *       the drive was priced twice ($1,716 where Kyle types $858).
   *    5. THE GUYS FOLLOW THE CREW OF THE BID AS IT IS NOW (syncAutoGuys): Combo made Polish left the carrier's guys on the Combo's bigger crew, and
   *       the price the draft saved was not the price a plain reopen showed ($33,514 and $32,632).
   *  A bid with no distance on file fills nothing (the rest still settles). An option is priced apart and its row is its own. */
  function followDistance(model, fromTab) {
    if (!isObject(model)) return model;
    if (!carrierKept(model, fromTab)) {
      carryTravelRow(model, fromTab);
      var d = model.distance;
      var miles = d ? milesOrNull(d.miles) : null;
      if (miles !== null) followDistanceHours(model, miles);
    }
    takeBackStrayTravel(model);
    syncAutoGuys(model);
    return model;
  }

  /** Did the section that carried the job's travel before a restructure carry it still? Only a caller that says which section that was can say yes. */
  function carrierKept(model, fromTab) {
    if (typeof fromTab !== "string" || fromTab === "") return false;
    try { return travelCarrier(model) === fromTab; } catch (err) { return false; }
  }

  /** The Travel Labor rows of one section (the root is the model itself), as the section holds them. */
  function travelRowsIn(section) {
    return (isObject(section) && section.labor instanceof Array ? section.labor : []).filter(function (r) { return isTravelRow(r); });
  }

  /** Does the estimator own this Travel Labor row's Guys? Typed in the box (guys_typed), or a figure sitting in a box that is not on
   *  auto: every box a person has typed in is off auto, and an older bid that predates the marker shows it the same way. */
  function travelGuysAreTyped(row) {
    return !!row && (row.guys_typed === true || (!row.guys_auto && filledIn(row.guys)));
  }

  /** Has nobody put a hand on this Travel Labor row's boxes? No marker says a box was typed in or cleared, no guys sit in a Guys box that is off auto, and
   *  no hours are typed over the tool's own. The distance may have filled it. (The row can still be switched off, which is the estimator's too:
   *  travelRowIsTheEstimators counts that.) */
  function travelRowIsHandsOff(row) {
    if (!row || row.guys_typed === true || row.hours_typed === true) return false;
    if (travelGuysAreTyped(row)) return false;
    return isBlank(row.days) || driveHoursAreTools(row);
  }

  /** Is this Travel Labor row one the DISTANCE filled and nobody typed in? Its hours are the tool's own figure (or empty), its
   *  guys are on auto (the crew's size, or the older man-days) or empty, and no marker says a box was typed in or cleared. Such a
   *  row can be taken back without costing the estimator anything they wrote; a row with any figure of theirs in it cannot. */
  function travelRowIsAutoFilled(row) {
    return travelRowIsHandsOff(row) && (driveHoursAreTools(row) || followsCrew(row));    // and the tool wrote something there
  }

  /** Is this Travel Labor row the ESTIMATOR'S? A box they typed in or cleared (the markers saved with the row, or guys in a box that is off auto, or hours that are
   *  not the tool's own) or a row they switched off, by the slider on its card or by its default on the Defaults tab. The tool never writes into it, and it
   *  follows the job's drive when the carrier moves (followOwnedRow). A blank row, and one the distance filled, are nobody's. */
  function travelRowIsTheEstimators(row) {
    return !!row && (!rowOn(row) || !travelRowIsHandsOff(row));
  }

  /** The Travel Labor row of the section that carried the job's travel moves with the carrier, and what the estimator said on it moves too. The job-type path's half
   *  of pickBase's moveTravelLabor, done IN PLACE on the live model: a new carrier that has no row takes the old carrier's (it is a copy and not a move when the
   *  old carrier keeps no other row); one that has a row nobody touched takes the old carrier's when that one is the estimator's (followOwnedRow); a new
   *  carrier whose own row is the estimator's keeps it. `fromTab` is the old carrier when the caller knows it; otherwise strandedTravelTab looks for it.
   *  Never throws: a bid whose sections cannot be read, or a section that is gone, has nothing to carry. */
  function carryTravelRow(model, fromTab) {
    try {
      var to = travelCarrier(model);
      var from = typeof fromTab === "string" && fromTab !== "" ? fromTab : strandedTravelTab(model, to);
      // (A COPY and not a move, when the old carrier keeps no other row, leaves the old carrier holding a repeat of the row that went: takeBackStrayTravel
      // gives a repeat of the carrier's row back, the estimator's included, and the row the distance filled.)
      if (from && from !== to && !shiftTravelRow(model, from, to)) followOwnedRow(model, from, to);
    } catch (err) { /* nothing to carry */ }
  }

  /** A Travel Labor row given back to nobody: empty, off auto, no marker of a fill or of the estimator's hand, and switched on again. IN PLACE. What an old
   *  carrier is left holding when its row has gone with the job's drive to another section. */
  function releaseTravelRow(row) {
    clearQuantities(row);
    delete row.enabled;
    return row;
  }

  /** WHAT THE ESTIMATOR SAID ON THE JOB'S DRIVE FOLLOWS THE CARRIER (2026-10-20 audit). The old carrier's Travel Labor row is the estimator's (travelRowIsTheEstimators: typed
   *  figures, a cleared box, a switch turned off) and the new carrier has a row of its own that nobody touched: the two rows change places. The estimator's takes the
   *  new carrier's slot in its labor list, markers and rate and all, and the old carrier is left holding the new carrier's former row, emptied (releaseTravelRow): every
   *  section keeps its one row and only the carrier's is priced, as when the distance's own fill is given back, and no row is ever shared or copied. If the new carrier's
   *  own row is the estimator's too, both are theirs and both stay. True when the rows changed places. THROWS for a section the model does not have, like sectionOf. */
  function followOwnedRow(model, fromTab, toTab) {
    var from = sectionOf(model, fromTab).section, to = sectionOf(model, toTab).section;
    var mine = travelRowsIn(from), theirs = travelRowsIn(to);
    if (!mine.length || !theirs.length) return false;
    var row = mine[0], leaves = theirs[0];
    if (!travelRowIsTheEstimators(row) || theirs.some(travelRowIsTheEstimators)) return false;
    to.labor[to.labor.indexOf(leaves)] = row;
    from.labor[from.labor.indexOf(row)] = leaves;
    releaseTravelRow(leaves);
    return true;
  }

  /** WHERE THE JOB'S TRAVEL LABOR ROW IS STRANDED when the caller does not say which section carried it: the first section other than
   *  `carrier` that holds a Travel Labor row and is off or a base (an option's row is its own and is never carried), "" for none. A bid whose
   *  library said no Travel Labor (no_travel_labor) has no row to carry, and one with sections that cannot be read has none to find. */
  function strandedTravelTab(model, carrier) {
    if (model.no_travel_labor === true) return "";
    var entries = readableSections(model);
    if (entries === null) return "";
    for (var i = 0; i < entries.length; i++) {
      var e = entries[i];
      if (e.tab === carrier || e.kind === "option" || !isObject(e.section)) continue;
      if ((e.section.labor instanceof Array ? e.section.labor : []).some(function (r) { return isTravelRow(r); })) return e.tab;
    }
    return "";
  }

  /** ONE DRIVE, ONE TRAVEL LABOR ROW PRICED (2026-10-20 audits). Every Travel Labor row the distance filled and nobody touched (travelRowIsAutoFilled), on any
   *  section that does not hold the job's fill, is taken back: guys and hours empty, every fill marker gone. The fill lives on the carrier, so that is every
   *  other section that is a base OR OFF (an off section prices nothing, but its row would be priced again the day its job type came back: Epoxy to Polish to
   *  Combo charged $858 twice), and a Gyp carrier too, whose drive is typed and which the distance never fills. Left alone: a row somebody typed in or cleared
   *  or switched off (it is theirs), and an option's row (an option is priced apart, for its own crew, and carries its own). ONE EXCEPTION to "theirs": the
   *  estimator's row on a section that is not the carrier that says exactly what the carrier's row says is a COPY of it (a copy of the carrier's sheet carries the
   *  row it had, and was made a base beside it), so it is given back too: the job's drive is typed once and charged once. MUTATES the model. */
  function takeBackStrayTravel(model) {
    var entries = readableSections(model);
    if (entries === null) return;
    var carrier = travelCarrier(model);
    var held = entries.filter(function (e) { return e.tab === carrier; })[0];
    var carrierRow = held ? travelRowsIn(held.section)[0] : null;
    entries.forEach(function (e) {
      if (e.kind === "option" || !isObject(e.section) || (e.tab === carrier && e.layout !== "gyp")) return;
      travelRowsIn(e.section).forEach(function (r) {
        if (r.unit !== "hours") return;
        if (rowOn(r) && travelRowIsAutoFilled(r)) clearQuantities(r);
        else if (e.tab !== carrier && travelRowRepeats(r, carrierRow)) releaseTravelRow(r);
      });
    });
  }

  /** Does this Travel Labor row repeat the carrier's: both the estimator's, with the same guys and hours (and the same hands on them: typed, cleared, switched
   *  off, on auto or not)? What a copy of the carrier's sheet holds beside the carrier's own row once the copy is a base of the job. */
  function travelRowRepeats(row, carrierRow) {
    if (!row || !carrierRow || row === carrierRow || !travelRowIsTheEstimators(row) || !travelRowIsTheEstimators(carrierRow)) return false;
    var same = function (k) { return String(row[k] == null ? "" : row[k]) === String(carrierRow[k] == null ? "" : carrierRow[k]); };
    return same("guys") && same("days") && !!row.guys_auto === !!carrierRow.guys_auto && (row.enabled === false) === (carrierRow.enabled === false) &&
      (row.guys_typed === true) === (carrierRow.guys_typed === true) && (row.hours_typed === true) === (carrierRow.hours_typed === true);
  }

  /** The number as it reads in a sentence: at most two places, none when it is whole. */
  function plainNum(n) { return String(Math.round(num(n) * 100) / 100); }

  /** WHERE THE TRAVEL LABOR HOURS CAME FROM, when the distance wrote them: `{hours, roundTrip, mph}`,
   *  or null when they did not (typed, empty, no distance, a job under 70 miles, or a figure this
   *  distance would not give). One reading for the card's note, the how-it-is-worked-out note and the
   *  Review's working. `model` is read only for its distance. */
  function driveHoursSource(model, row) {
    var d = model && model.distance;
    var miles = d ? milesOrNull(d.miles) : null;
    if (miles === null || !driveHoursAreTools(row) || row.days !== driveHoursFor(miles)) return null;
    return { hours: row.days, roundTrip: Math.round(2 * miles * 10) / 10, mph: DRIVE_MPH };
  }

  /** "one 380 mile round trip at 60 mph from the Olathe office": the trip, in words. */
  function driveTripWords(src) {
    return "one " + plainNum(src.roundTrip) + " mile round trip at " + src.mph + " mph from the Olathe office";
  }

  /** Who the trip is charged to, in words, while Travel Labor's guys are on the crew's size: "for each of the 4 guys on the
   *  labor lines above". "" when the guys are typed (the note says so itself) or are the older man-days. `own`: the row is an
   *  option's, whose guys are the lines of its own section (crewWhere). */
  function driveGuysWords(model, row, own) {
    if (!followsCrew(row)) return "";
    var n = num(row.guys);
    if (n === 1) return "for the one guy on " + crewWhere(model, own);
    return (n > 0 ? "for each of the " + plainNum(n) + " guys on " : "for each guy on ") + crewWhere(model, own);
  }

  /** "6.5 hrs: one 380 mile round trip at 60 mph from the Olathe office, for each of the 4 guys on the labor lines above", or ""
   *  when the distance did not write this row's hours. Kyle's way: each guy is charged one round trip. The one reading for
   *  the card's note, the how-it-is-worked-out note's trip and the Review's working. (The estimate page never says
   *  "crew": its column is Guys, and a test holds every word it renders to that.) `own`: see driveGuysWords. */
  function driveHoursSentence(model, row, own) {
    var src = driveHoursSource(model, row);
    if (!src) return "";
    var who = driveGuysWords(model, row, own);
    return plainNum(src.hours) + " hrs: " + driveTripWords(src) + (who ? ", " + who : "");
  }

  /** THE NOTE UNDER THE TRAVEL LABOR CARD: where its hours came from and what the line is, or "" while the hours are typed
   *  or empty, or the row is switched off (and the card shows nothing). `rows` are the labor rows the man-days of an
   *  older bid are counted on. Plain words, Kyle's way: each guy is charged one round trip, and a long job types more trips.
   *  A Guys box the estimator cleared is empty and says so: it never reads "the guys are typed". `own`: see driveGuysWords. */
  function driveHoursNote(model, row, rows, own) {
    if (!row || !rowOn(row)) return "";
    var src = driveHoursSource(model, row);
    if (!src) return "";
    var head = driveHoursSentence(model, row, own) + ". ";
    var trips = "Type more trips for a long job.";
    if (followsCrew(row)) {
      return head + (num(row.guys) > 0 ? "" : "It prices once those lines have guys. ") + trips;
    }
    if (!row.guys_auto) {
      return head + (filledIn(row.guys)
        ? "The guys are typed, so Travel Labor is your guys x those hours. "
        : "The Guys box is empty, so Travel Labor adds nothing until you type the guys. ") +
        "Type more trips for a long job, or type over the hours to use your own.";
    }
    // A bid saved before 2026-10-12, still on the man-days.
    var days = travelManDays(rows);
    return head + "Travel Labor is the man-days on the labor lines above" + (days > 0 ? " (" + plainNum(days) + ")" : "") +
      " x those hours, the way Kyle's sheet works it" +
      (days > 0 ? "." : ", so it prices once those lines have days.") +
      " Type over the hours or the guys to use your own.";
  }

  /** The hint under Travel Labor's Guys box. On the crew's size it says so ("Most guys on one labor line above: 4."); a bid saved
   *  before 2026-10-12 still on auto says the figure IS the man-days (manDaysHint); and a Travel Labor box that is typed or empty
   *  says what its guys are: "One round trip for each guy." It never quotes the man-days beside a typed count (2026-10-20 audit: "Man-days
   *  from the tasks above: 48." under a box of 2 invited typing 48, which charges every man-day a round trip). Any other hours line
   *  is worded as manDaysHint words it. `rows` are the labor rows of the section on show; `own`: see driveGuysWords. */
  function travelGuysHint(model, row, rows, own) {
    if (followsCrew(row)) {
      var n = num(row.guys);
      return "Most guys on one labor line" + (!own && baseCount(model) > 1 ? " of the base sheets" : " above") + (n > 0 ? ": " + plainNum(n) : "") + ".";
    }
    if (isTravelRow(row) && !row.guys_auto) return "One round trip for each guy.";
    return manDaysHint(!!(row && row.guys_auto), travelManDays(rows));
  }

  /** THE WORDS ON A TRAVEL LABOR CARD THAT SITS ON A BASE SECTION WHICH DOES NOT CARRY THE JOB'S TRAVEL (2026-10-20 audits). The job's
   *  drive is one trip and is charged once, on the carrier (`carrierTab`), so the card says so. A row the distance filled and nobody
   *  touched has been taken back (followDistance) and is empty: the words say to leave it so. One that still holds figures is worded
   *  by what they ARE: the estimator's own (typed, and so left as typed), a row switched off (it adds nothing), or the drive the distance
   *  filled that a bid saved before the take-back still holds (not typed: the audit caught the card saying "typed" over the tool's own
   *  figures). A row somebody typed in, and the drive the distance filled, both still add to this section's labor, and the words say what to do. */
  function strayTravelNote(carrierTab, row) {
    var where = "The job's drive is charged once, on the " + carrierTab + " section.";
    if (row && (filledIn(row.guys) || filledIn(row.days))) {
      if (!rowOn(row)) return where + " This line holds figures but is switched off, so it adds nothing to this section's labor.";
      if (travelRowIsAutoFilled(row)) {
        return where + " This line still holds the drive the distance filled, so it adds to this section's labor as well. " +
          "Clear it, or remove the line.";
      }
      return where + " This line holds figures that were typed, so it was left as typed and still adds to this section's labor. " +
        "Clear it, or remove the line, if the drive is already charged there.";
    }
    return where + " Leave this line empty: anything typed here is charged a second time.";
  }

  /** Back to "unknown": the estimator cleared the miles they had typed. Local again (the shipped
   *  default) and every line the estimator never touched gray again; a hand flip stays. The hours
   *  the distance wrote into Travel Labor go back to empty with it; typed hours stay. */
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
    followDistanceHours(model, null);
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

  /** HOW THE TRAVEL LINES ARE WORKED OUT, in plain words (Hanz, 2026-10-06: "a note that it is
   *  calculated based off whether it's a local job ... just to show you how it's being solved").
   *  Returns `{decision, lines, text}`: the local-or-not call and why, one working line per travel
   *  line (the real numbers, from the same functions that price the bid: laborCost, travelQty,
   *  travelLineCost), and `text`, those joined with newlines for one element to show with
   *  `white-space: pre-line`. A pure read of the model: it prices nothing and changes nothing.
   *
   *  Lives here, not in js/polish-estimate.js, because the harness for that file lifts init() and
   *  laborPanel() by name and a new local function they call is a ReferenceError in every scenario. */
  function travelHow(model) {
    var M = model || {};
    var d = M.distance;
    var miles = d ? milesOrNull(d.miles) : null;
    var far = miles !== null && miles >= LOCAL_MILES;
    var local = !!(M.conditions || {}).local;
    var trv = M.travel || {};
    var rows = M.labor || [];
    var cut = String(LOCAL_MILES) + " miles";
    var qty = function (n) { return String(Math.round(num(n) * 100) / 100); };

    var decision;
    if (miles === null) {
      decision = "Distance not known yet, so the tool cannot tell if this is a local job. " +
        "Type the miles above.";
    } else if (far) {
      decision = distanceNote(M) + ". That is " + cut + " or more, so this is NOT a local job: " +
        "Travel Labor, Lodging and Per Diem come on.";
    } else {
      decision = distanceNote(M) + ". That is under " + cut + ", so this IS a local job: the " +
        "three travel lines stay gray unless you switch one on.";
    }
    var hand = [];
    var names = { lodging: "Lodging", per_diem: "Per Diem" };
    var tr = null;
    for (var i = 0; i < rows.length; i++) { if (rows[i] && rows[i].id === "travel") { tr = rows[i]; break; } }
    // A far job whose Travel Labor row was switched off says so, once, or the decision line ("come on")
    // and the working line ("off, $0") contradict each other with nothing in between. Switched off by
    // the slider on its card or by its default on the Defaults tab: either way the distance leaves the
    // row exactly as it is (followDistanceHours), so the words say what to do about it.
    if (far && tr && !rowOn(tr)) {
      hand.push("Travel Labor was switched off by hand, or by its default, so it adds nothing and the distance fills no " +
        "drive time into it. Switch it on and type the guys and the hours.");
    }
    TRAVEL_LINE_KEYS.forEach(function (k) {
      var l = trv[k];
      if (l && l.hand === true) {
        hand.push(names[k] + " was switched " + (rowOn(l) ? "on" : "off") +
          " by hand, so the distance does not change it.");
      }
    });

    var lines = [];
    var usesAuto = false;
    // The travel panel is the root section's: a bid priced by Polish rev 2 counts auto nights the sheet's way, so the
    // working lines count them the same way the cost box and the bid do.
    var trvOpts = travelOpts(M, ROOT_TAB);
    // Set when a travel line that is on is not on auto: the man-days the sheet would count are then shown as text.
    var showManDays = false;
    // The Travel row's guys are on the crew's size (a far answer put them there) or on the older man-days (a bid saved
    // before 2026-10-12); the how-note words each its own way and never calls the crew's size a count of man-days.
    var crewFollow = !!tr && followsCrew(tr);
    if (tr && rowOn(tr) && (num(tr.days) > 0 || !local)) {
      var hrs = "";
      // The round trip the hours were worked from, when the distance wrote them (Hanz, 2026-10-20): the trip in words,
      // charged to each guy (Kyle's way) while the guys are the crew's size.
      var drive = driveHoursSource(M, tr);
      if (!isBlank(tr.days) && num(tr.days) > 0) {
        // A figure the distance wrote says the trip it came from. One it wrote for a distance that is gone or has
        // moved (the miles cleared on a bid saved before 2026-10-12) says so plainly, and the rest was typed.
        hrs = drive ? " (" + driveTripWords(drive) + (crewFollow ? ", for each guy" : "") + ")"
          : driveHoursAreTools(tr)
            ? (miles !== null ? " (round trip at " + DRIVE_MPH + " mph)"
                              : " (from an earlier distance; type the miles or the hours)")
            : " (typed)";
      }
      // Only the older man-days auto makes the note explain man-days (below); the crew's size explains itself, and so do guys the
      // estimator typed: a typed Travel Labor count is GUYS, one round trip each, never man-days (2026-10-20 audit: "2 man-days
      // (typed)" beside "Man-days from the tasks above: 48" invited typing 48). The man-days are still said, as a reference, for
      // the nights and days typed in the two lines below.
      var oldAuto = !!tr.guys_auto && !crewFollow;
      if (oldAuto) usesAuto = true;
      // What is still to do on the line: the hours, or (when the distance wrote them and the guys follow labor lines
      // that have none yet) the guys on those lines.
      var todo = "";
      if (!(num(tr.days) > 0)) todo = ". Type the drive hours.";
      else if (crewFollow && !(num(tr.guys) > 0)) {
        todo = ". The guys follow " + crewWhere(M) + ", so type the guys there.";
      } else if (drive && oldAuto && !(travelManDays(rows) > 0)) {
        todo = ". The guys follow the man-days, so type the days on the labor lines above.";
      } else if (!tr.guys_auto && !(num(tr.guys) > 0)) {
        todo = ". Type the guys.";
      }
      lines.push("Travel Labor: " + qty(tr.guys) + (oldAuto ? " man-days" : " guys") +
        ((tr.guys_auto || !filledIn(tr.guys)) ? "" : " (typed)") +
        " x " + qty(tr.days) + " drive hours" + hrs + " x " + money2(tr.rate) + " = " +
        money2(laborCost(tr)) + todo);
    } else {
      lines.push("Travel Labor: off, $0");
    }
    TRAVEL_LINE_KEYS.forEach(function (k) {
      var l = trv[k];
      if (!l || !rowOn(l)) { lines.push(names[k] + ": off, $0"); return; }
      var q = travelQty(l, rows, trvOpts);
      var prod = q * num(l.rate);
      var cost = travelLineCost(l, rows, trvOpts);
      if (l.qty_auto !== false) usesAuto = true;
      var typedQty = l.qty_auto === false && filledIn(l.qty);
      if (l.qty_auto === false) showManDays = true;
      lines.push(names[k] + ": " + qty(q) + (k === "lodging" ? " nights" : " days") +
        (typedQty ? " (typed)" : "") + " x " + money2(l.rate) + " = " +
        (prod === cost ? money2(cost) : money2(prod) + ", rounded up to " + money(cost)) +
        (typedQty || l.qty_auto !== false ? "" : ". Type the " + (k === "lodging" ? "nights." : "days.")));
    });
    // THE CREW'S SIZE, said once, where Travel Labor's guys came from (a far answer put them on it). It is a head count, one
    // round trip each, and is never worded as man-days: those are the nights and days below, a different figure.
    if (crewFollow && tr && rowOn(tr) && (num(tr.days) > 0 || !local)) {
      lines.push("Guys = the most guys on any one labor line " + (baseCount(M) > 1 ? "of the base sheets" : "above") +
        " (" + qty(tr.guys) + " now), one round trip each.");
    }
    // The nights and days are counted from the labor above, and the Lodging hint under the box says the same figure in the
    // same words (lodgingHint): the sheet's count where a profile counts them from the labor dollars (a fourth hand on the
    // joint-filler line, or a row paid more, makes that more than guys x days), guys x days otherwise.
    var nightsNow = trvOpts ? sheetNights(rows, trvOpts.conditions, trvOpts.prevailing) : null;
    var manDaysNow = travelManDays(rows);
    var sheetCounts = nightsNow !== null && Math.abs(nightsNow - manDaysNow) >= 1e-9;
    if (usesAuto && sheetCounts) {
      lines.push("Nights = the labor dollars above over the first labor line's rate over 8 hours, as the sheet counts them (" +
        qty(nightsNow) + " now). Guys x days is " + qty(manDaysNow) + ".");
    } else if (usesAuto) {
      lines.push("Man-days = guys x days on the labor lines above (" + qty(manDaysNow) +
        " now).");
    } else if (showManDays) {
      // Text only: the figure is not used anywhere until the estimator types it into a box.
      if (sheetCounts) {
        lines.push("For reference, the labor lines above count " + qty(nightsNow) + " nights the way the sheet does (guys x days is " +
          qty(manDaysNow) + ").");
      } else {
        lines.push("For reference, the man-days on the labor lines above are " + qty(manDaysNow) + ".");
      }
    }
    return { decision: decision, hand: hand, lines: lines,
             text: [decision].concat(hand, lines).join("\n") };
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

  /** THE UNIT A TAKEOFF ROW IS MEASURED IN COMES FROM ITEMS & ASSEMBLIES (Hanz, 2026-10-12: "Unit
   *  should be pulled from the items and assemblies tab").
   *
   *  An ASSEMBLY declares its own unit, SF or LF. A MATERIAL is measured by its COVERAGE BASIS,
   *  never by `item.unit`: that one is the unit the material is BOUGHT in (Gallon, Kit, Pail) and
   *  has nothing to do with how the floor is measured. A takeoff only prices SF and LF (takeoffSf
   *  and takeoffLf are the two measures the bid reads), so a basis of "each" cannot be priced as a
   *  count here and is read as SF; `state` says so, so the screen can too.
   *
   *  `kind` is "asm" or "item"; `lib` is that library row. Returns null when there is no row, and
   *  otherwise `{unit: "SF"|"LF", state}`: "set" when the library said, "unset" when it did not
   *  (priced as SF, today's default), "each" for a count. Lives in this file, not in
   *  js/polish-estimate.js, because the harness for that file lifts functions BY NAME and a new
   *  local helper called from one of them is a ReferenceError in every scenario. */
  function takeoffUnit(kind, lib) {
    if (!lib || typeof lib !== "object") return null;
    var word = kind === "asm" ? lib.unit : lib.coverage_basis;
    word = String(word == null ? "" : word).trim().toUpperCase();
    if (word === "SF" || word === "LF") return { unit: word, state: "set" };
    if (kind !== "asm" && word === "EACH") return { unit: "SF", state: "each" };
    return { unit: "SF", state: "unset" };
  }

  /** True for exactly "SF" or "LF": the only two units takeoffSf and takeoffLf count. */
  function validTakeoffUnit(u) {
    return u === "SF" || u === "LF";
  }

  /** Give takeoff row `i` the unit a pick on Items & Assemblies decided, without quietly turning a
   *  number into a different kind of number.
   *
   *  A measurement is a count of ONE unit. Moving a row that holds one from SF to LF (or back) would
   *  keep the digits and change what they mean: a 5,000 SF floor becomes 5,000 LF of cove and drops
   *  out of the area. So when the unit really changes and the row holds a measurement, the
   *  measurement is cleared (through setMeasurement, so a floor's same-floor rows follow it and a
   *  follower stops following) and the estimator types the new one. A row whose saved unit was not
   *  SF or LF counted nowhere, so its number belongs to no unit and is kept. Returns true when the
   *  unit changed. */
  function adoptTakeoffUnit(rows, i, unit) {
    var r = rows && rows[i];
    if (!r || r.unit === unit) return false;
    var held = String(r.measurement == null ? "" : r.measurement).trim() !== "";
    if (held && validTakeoffUnit(r.unit)) setMeasurement(rows, i, "");
    delete r.same_floor;
    delete r.same_floor_of;
    delete r.same_floor_left;
    delete r.same_floor_left_of;
    delete r.floor_area;
    r.unit = unit;
    return true;
  }

  /** What a takeoff row's Unit box shows and the line under it says.
   *
   *  `row` is the takeoff row, `kind` and `lib` as takeoffUnit. The row's SAVED unit is what it
   *  prices with, so that is what shows; when it differs from the library's the line says so
   *  instead of repricing a saved bid behind the estimator's back. No library row (nothing picked
   *  yet) is a dash. Returns `{text, hint, note}`; `note` is true only for the saved-differs
   *  case, which the page draws louder than the ordinary line. */
  function takeoffUnitView(row, kind, lib) {
    var lu = takeoffUnit(kind, lib);
    if (!lu) return { text: "—", hint: "From Items & Assemblies.", note: false };
    var saved = (row || {}).unit;
    // A SAVED UNIT THAT IS NOT EXACTLY "SF" OR "LF" IS COUNTED IN NEITHER MEASURE: takeoffSf and
    // takeoffLf compare strictly. Showing the library's unit there would say the row is measured in
    // a unit the totals ignore, so the box says what is true instead.
    if (!validTakeoffUnit(saved)) {
      return { text: "—", note: true,
        hint: "No unit is saved on this row, so the bid does not count it. Retype the name to take " +
              "the unit from Items & Assemblies." };
    }
    var ordinary = lu.state === "set" ? "From Items & Assemblies."
      : (lu.state === "each"
        ? "Items & Assemblies says Each, which a takeoff prices as SF."
        : "Not set in Items & Assemblies, so SF.");
    if (saved === lu.unit) return { text: saved, hint: ordinary, note: false };
    var now = lu.state === "set" ? "Items & Assemblies now says " + lu.unit + "."
      : (lu.state === "each" ? "Items & Assemblies now says Each, which prices as SF."
        : "Items & Assemblies has no unit set, so it would be SF.");
    return { text: saved, hint: "Saved as " + saved + "; " + now, note: true };
  }

  /** THE DEFAULTS, LOADED INTO A NEW ESTIMATE'S TAKEOFF (Hanz, 2026-10-05: "each default becomes its
   *  own Takeoff row, measured with the intake polish SF").
   *
   *  `asms` / `items` are the library catalogs. A row seeds when it is a favorite (the Defaults tab
   *  list) AND applies to the job being opened (default_work_types, empty = every tab) -- the same two
   *  tests the Defaults tab draws its Takeoff lists with. Assemblies first, then materials, the order
   *  the tab shows them. The three reserved materials (`reserved` ids: dye, joint filler kit, remove-
   *  existing) are NOT seeded here: they are the condition cards, which have their own defaults.
   *
   *  `workType` is the JOB TYPE being opened, and a default applies when it applies to ANY tab that job
   *  is priced on (workTypeApplies): polish reads the polish list, epoxy the epoxy list, and a combo job
   *  reads both. It was Polish alone, written into this function, until a combo job needed its own. It
   *  is "polish" when a caller leaves it out, which is every caller that existed before it did.
   *
   *  HOW IT COMBINES WITH seedTakeoffSf WITHOUT COUNTING THE FLOOR TWICE. takeoffSf adds every SF
   *  row, so ten defaults each measured with the intake 8,250 SF would read as 82,500 SF of floor,
   *  and polish_sf, the price per SF and every area-driven condition would follow it. The defaults
   *  of ONE area are all the SAME floor, so:
   *    - ONE row carries the area: the first ENABLED SF-unit default. Counted as always.
   *    - every other default carries the same number for pricing but is marked `same_floor`, which
   *      takeoffSf skips. The marker is data on the row, so it survives save and reload.
   *    - no enabled SF default (all off, all LF, or the library has none): the intake boxes seed
   *      plain area rows exactly as seedTakeoffSf always did (System 1 / System 2, one row each),
   *      appended after the defaults, and every default is marked `same_floor`.
   *
   *  SYSTEM 1 AND SYSTEM 2 ARE TWO AREAS FROM THE START (Hanz, 2026-10-13, "Separate areas"). Each
   *  positive intake box is its OWN area, and each area gets its OWN copy of the default lines: the
   *  System 1 lines measured with System 1, the System 2 lines with System 2, the floor being the
   *  two added. Before this, one carrier held the SUM and System 2 read blank, so typing System 2
   *  added a third row on top (a double count). A line costs its rate times its measurement, so the
   *  two copies price the same as one copy on the combined floor. A material bought in whole packs
   *  used to round up once per area; a section made now buys each material once for the whole
   *  section (poolsPacks, library-core pricePool), so the two areas cost what one floor costs.
   *  The marker that says which area a row belongs to is data on the row, so it survives save and
   *  reload: the carrier holds `floor_area: n`, every row that follows it `same_floor: true` and
   *  `same_floor_of: n` (n = 1 for the first area, 2 for the second). A saved takeoff made before
   *  this has neither, and keeps behaving as one area. An LF default is not a floor: it is seeded
   *  once, blank, with the first area.
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
  function seedDefaultTakeoff(rows, asms, items, reserved, sf1, sf2, workType) {
    rows = Array.isArray(rows) ? rows : [];
    for (var i = 0; i < rows.length; i++) {
      var q = rows[i] || {};
      if (num(q.measurement) > 0 || q.assembly_id || q.item_id) return rows;
    }
    var applies = function (r) { return workTypeApplies(r, workType); };
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

    // One pass per measured area, in box order. With nothing measured there is one pass of blank rows.
    var areas = [num(sf1), num(sf2)].filter(function (v) { return v > 0; });
    var out = [];
    var plain = [];
    (areas.length ? areas : [0]).forEach(function (sf, a) {
      var tag = sf > 0 ? a + 1 : 0;
      var carried = false;
      picks.forEach(function (p) {
        var on = p.row.default_on !== false;
        // The unit is Items & Assemblies' say: an assembly's own unit, a material's coverage basis.
        var unit = takeoffUnit(p.kind, p.row).unit;
        // A linear-foot default measures something else than a floor: one row, with the first area.
        if (unit !== "SF" && a > 0) return;
        var r;
        if (p.kind === "asm") {
          r = { assembly_id: p.row.id, assembly_name: p.row.name, measurement: "", unit: unit };
        } else {
          r = { kind: "item", item_id: p.row.id, item_name: p.row.name, coverage: "",
                measurement: "", unit: unit };
        }
        if (unit === "SF" && sf > 0) {
          r.measurement = sf;
          if (on && !carried) { carried = true; r.floor_area = tag; }
          else { r.same_floor = true; r.same_floor_of = tag; }
        }
        if (!on) r.enabled = false;
        out.push(r);
      });
      if (!carried && sf > 0) {
        plain.push({ assembly_id: "", assembly_name: "", measurement: sf, unit: "SF", floor_area: tag });
      }
    });
    // No default carried an area: the plain System rows seedTakeoffSf makes, after the defaults.
    plain.forEach(function (r) { out.push(r); });
    return out;
  }

  /** The area a takeoff row belongs to, as seedDefaultTakeoff marks it: a carrier holds `floor_area`,
   *  a row that follows it holds `same_floor_of`, both the same whole number (1, 2, ...). 0 = no mark,
   *  which is every row of a bid saved before the areas were separate: they all read as one area. */
  function areaTagOf(n) {
    var v = Number(n);
    return v > 0 && v === Math.floor(v) ? v : 0;
  }
  function carrierTag(r) { return r ? areaTagOf(r.floor_area) : 0; }
  function followerTag(r) { return r ? areaTagOf(r.same_floor_of) : 0; }

  /** The floor a coat row belongs to: the row (not `i`) that carries area `tag`'s floor — an SF row that is on, carries a
   *  floor of its own (neither follows a floor nor left one) and is that area's (`floor_area`, or no mark for a bid with
   *  one area). The first such row, as the row was matched when it was added. Null when there is none. */
  function floorOf(rows, i, tag) {
    for (var j = 0; j < rows.length; j++) {
      var q = rows[j];
      if (j === i || !q || q.unit !== "SF" || !rowOn(q) || q.same_floor || q.same_floor_left) continue;
      if (carrierTag(q) === tag && num(q.measurement) > 0) return q;
    }
    return null;
  }

  /** Type `value` into row `i`'s measurement, keeping the same-floor rows honest.
   *  - A `same_floor` row the estimator types its OWN number into stops sharing: the marker is
   *    cleared, so takeoffSf counts what it was told rather than ignoring it for good.
   *  - BUT A COAT THAT IS TYPED THE FLOOR'S OWN NUMBER IS STILL ON THAT FLOOR (2026-10-16). The re-check of a real job
   *    found it: a primer added beside a 5,482 SF floor carried 5,482 and was the same floor, and then the estimator
   *    typed 5,482 into it, a keystroke at a time, and the first "5" made it a second floor for good: the area doubled,
   *    and with it the patch, the tooling and the proposal's square feet. So a row that leaves its floor this way keeps
   *    `same_floor_left` (and `same_floor_left_of`, its area), and rejoins the floor the moment its number is the
   *    floor's again. A row that never followed a floor is never joined to one: two rooms of the same size are two
   *    floors.
   *  - The carrier (an enabled SF row that is not same_floor) moving drags every same_floor row
   *    of ITS OWN area still holding its old number along, so the rows the default load made as
   *    one floor keep pricing one floor. A same_floor row already set to something else is left
   *    alone, and so is a row that follows the OTHER area (two areas can hold the same number). */
  function setMeasurement(rows, i, value) {
    var r = rows && rows[i];
    if (!r) return;
    var old = r.measurement;
    r.measurement = value;
    if (r.same_floor || r.same_floor_left) {
      var ftag = r.same_floor ? followerTag(r) : areaTagOf(r.same_floor_left_of);
      var floor = floorOf(rows, i, ftag);
      if (floor && num(value) > 0 && num(value) === num(floor.measurement)) {
        r.same_floor = true;
        if (ftag) r.same_floor_of = ftag;
        delete r.same_floor_left; delete r.same_floor_left_of;
        return;
      }
      if (r.same_floor) {
        delete r.same_floor_of;
        delete r["same_floor"];
        r.same_floor_left = true;
        if (ftag) r.same_floor_left_of = ftag;
      }
      return;
    }
    if (r.unit !== "SF" || !rowOn(r)) return;
    var tag = carrierTag(r);
    for (var k = 0; k < rows.length; k++) {
      var o = rows[k];
      if (k !== i && o && o.same_floor && followerTag(o) === tag && num(o.measurement) === num(old)) o.measurement = value;
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
   *  all carry the one floor's number, so the largest of them is the answer.
   *
   *  PER AREA, FOR A BID SEEDED WITH SEPARATE AREAS. An area whose carrier is gone but whose
   *  same_floor rows (marked `same_floor_of`) remain still counts, once, as the largest of them,
   *  added to the other areas. A takeoff with no marks reads exactly as it always did. */
  function measuredSf(rows) {
    rows = rows || [];
    var t = 0, same = 0, carriers = [], held = [];
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i] || {};
      if (r.unit !== "SF") continue;
      var m = num(r.measurement);
      if (r.same_floor) {
        var ft = followerTag(r);
        if (!ft) { if (m > same) same = m; continue; }
        var g = null;
        for (var h = 0; h < held.length; h++) if (held[h].tag === ft) g = held[h];
        if (!g) { g = { tag: ft, max: 0 }; held.push(g); }
        if (m > g.max) g.max = m;
      } else {
        t += m;
        if (carrierTag(r) && m > 0) carriers.push(carrierTag(r));
      }
    }
    held.forEach(function (g) { if (carriers.indexOf(g.tag) < 0) t += g.max; });
    return t > 0 ? t : same;
  }

  /** THE SEPARATE MEASURED AREAS OF A TAKEOFF, in takeoff order: the row index of each (the rows
   *  measuredSf adds up). Intake's System 1 box mirrors the first, System 2 the second.
   *
   *  Counted exactly the way measuredSf counts: SF rows with a number on them, the on/off slider
   *  ignored, and a same_floor row not counted on top of its carrier. When the carrier has no
   *  number and only same_floor rows hold the floor, they are all the one floor: that is one area,
   *  shown by the first of them.
   *
   *  A bid seeded with separate areas marks which area a row belongs to (seedDefaultTakeoff). An
   *  area whose carrier is gone but whose marked same_floor rows remain is still an area, shown by
   *  the first of those rows. An unmarked same_floor row is the one-floor case above. */
  function measuredSfRows(rows) {
    rows = rows || [];
    var carriers = [];
    for (var j = 0; j < rows.length; j++) {
      var c = rows[j] || {};
      if (c.unit === "SF" && !c.same_floor && num(c.measurement) > 0 && carrierTag(c)) carriers.push(carrierTag(c));
    }
    var areas = [], seen = [], same = -1;
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i] || {};
      if (r.unit !== "SF" || !(num(r.measurement) > 0)) continue;
      if (!r.same_floor) { areas.push(i); continue; }
      var ft = followerTag(r);
      if (!ft) { if (same < 0) same = i; continue; }
      if (carriers.indexOf(ft) < 0 && seen.indexOf(ft) < 0) { seen.push(ft); areas.push(i); }
    }
    return areas.length ? areas : (same >= 0 ? [same] : []);
  }

  /** How many separate measured areas the takeoff holds. */
  function measuredSfAreas(rows) {
    return measuredSfRows(rows).length;
  }

  /** The measurement of each separate area, in order (what the two intake boxes show). */
  function measuredSfValues(rows) {
    rows = rows || [];
    return measuredSfRows(rows).map(function (i) { return num(rows[i].measurement); });
  }

  /** TYPE A FLOOR SIZE FOR AREA `k` (0 = the first measured area, 1 = the second). Returns true when
   *  it wrote, false when it left the model alone (no positive number, k not 0 or 1, or nothing
   *  measured yet: then intake's boxes SEED the takeoff instead).
   *
   *  Area 0 and 1 change that row's measurement and nothing else. Asking for area 1 when only one
   *  area is measured ADDS the area. Rows after the second are never touched. Changes
   *  `model.takeoff` in place; callers hand it a copy (patchModel does).
   *
   *  TWO KINDS OF TAKEOFF.
   *  - SEPARATE AREAS (a new bid, seeded by seedDefaultTakeoff: the carrier holds `floor_area: n`,
   *    the rows that follow it `same_floor_of: n`). Typing an area moves its carrier and the rows
   *    following THAT area that still held its old number, and nothing of the other area. Adding the
   *    second area gives it its own copy of the first area's rows (the same assemblies and materials,
   *    the typed floor on each), so the defaults price the new floor as they price the first.
   *  - ONE FLOOR (a bid saved before the areas were separate: one carrier holding the whole floor,
   *    unmarked same_floor rows carrying the same number). Behaves as it always did: the carrier is
   *    area 0, the second area is a plain row added after it, and the same_floor rows that carried the
   *    whole floor move with it, on or off, so the on/off slider never decides which number the bid
   *    is built on. */
  function setAreaSf(model, k, sf) {
    var v = num(sf);
    var rows = model && model.takeoff;
    if (!(v > 0) || !(rows instanceof Array) || (k !== 0 && k !== 1)) return false;
    var areas = measuredSfRows(rows);
    if (!areas.length) return false;
    var before = measuredSf(rows);
    var isRow = function (x) { return x && x.unit === "SF"; };
    if (k < areas.length) {
      var row = rows[areas[k]];
      if (row.same_floor) {
        // Only same_floor rows hold this area (its carrier is gone): they are all the one number, so all move.
        var ft = followerTag(row);
        rows.forEach(function (x) {
          if (isRow(x) && x.same_floor && followerTag(x) === ft && num(x.measurement) > 0) x.measurement = v;
        });
        return true;
      }
      var old = num(row.measurement);
      row.measurement = v;
      var ct = carrierTag(row);
      if (ct) {
        rows.forEach(function (x) {
          if (isRow(x) && x.same_floor && followerTag(x) === ct && num(x.measurement) === old) x.measurement = v;
        });
        return true;
      }
    } else {
      var first = rows[areas[0]];
      var tag = first.same_floor ? followerTag(first) : carrierTag(first);
      if (tag) {
        // A SEPARATE-AREAS bid: promote a carrier-less area's first row, then copy the area under a new tag.
        if (first.same_floor) { delete first.same_floor; delete first.same_floor_of; first.floor_area = tag; }
        var next = 1;
        rows.forEach(function (x) { next = Math.max(next, carrierTag(x) + 1, followerTag(x) + 1); });
        var group = rows.filter(function (x) { return isRow(x) && (carrierTag(x) === tag || (x.same_floor && followerTag(x) === tag)); });
        group.forEach(function (x) {
          var c = JSON.parse(JSON.stringify(x));
          c.measurement = v;
          if (c.same_floor) c.same_floor_of = next; else c.floor_area = next;
          rows.push(c);
        });
        return true;
      }
      // Only same_floor rows hold the floor (the carrier was deleted or has no number), and
      // measuredSf counts them only while no row of the takeoff's own does. Adding a plain row
      // would make that row the whole floor and the old figure vanish (8,000 + 3,000 read as
      // 3,000). So the first of them becomes the counted row, as the carrier is, and the rest follow.
      if (first.same_floor) delete first.same_floor;
      rows.push({ assembly_id: "", assembly_name: "", measurement: v, unit: "SF" });
    }
    var after = measuredSf(rows);
    rows.forEach(function (x) {
      if (isRow(x) && x.same_floor && !followerTag(x) && num(x.measurement) === before) x.measurement = after;
    });
    return true;
  }

  // ══ THE INTAKE'S QUANTITY BOXES, AND THE TAKEOFF EACH ONE EDITS (Hanz, 2026-10-13) ═══════════════════════
  //
  // WHAT WENT WRONG. The v2 intake's floor SF boxes were wired to the takeoff, but only the ROOT (Polish) one:
  // setAreaSf, measuredSfValues and patchModel's sf_areas all worked on `model.takeoff`. Since an Epoxy job's
  // floor lives in tabs["Epoxy"] and a Gyp job's in its Gyp tab, "Epoxy floor SF" typed 331,133 on an Epoxy job was
  // saved as system_1_sf and never reached the takeoff the estimate prices from.
  //
  // THE ONE MAPPING is work-types.js fieldHome: a quantity field -> the tab whose takeoff owns it, its unit (SF or
  // LF) and its place in that group (System 1 is 0, System 2 is 1; Gyp's soft, hard and corridor are 0, 1, 2). Here
  // the tab becomes the job's SECTION (sectionsOf, so a section that is off is never touched), and the rest is the
  // rule the Polish boxes always had, for every section:
  //   * a box mirrors its row of the takeoff once the section has a measured floor, and is never read-only;
  //   * only a box the estimator typed in writes, a figure above zero, and clearing or typing 0 deletes nothing;
  //   * area 3 and on of an SF group are left to the Takeoff;
  //   * a section with nothing measured is left to the estimate page when it is NEW (its boxes seed it there, with
  //     the library's defaults, as for any new bid), and written here when it was started, because the estimate page
  //     seeds only a new one (see applyBoxes).
  var GYP_BUCKETS = ["soft", "hard", "corridor"];
  // The three area assemblies the library seeds (js/gyp-takeoff.js AREA_ASSEMBLIES holds the same, and a test holds
  // the two equal). Here only to give an area the takeoff has no row for yet its row.
  var GYP_AREA_ASSEMBLIES = [
    { bucket: "soft", id: "wb-gyp-area-soft", name: "Gypsum: soft surfaces" },
    { bucket: "hard", id: "wb-gyp-area-hard", name: "Gypsum: hard surfaces over the sound mat" },
    { bucket: "corridor", id: "wb-gyp-area-corridor", name: "Gypsum: corridors" }
  ];

  /** The Gyp area a takeoff row is: its `bucket` mark, else the area its assembly names, else null (an extra). */
  function gypBucketOf(r) {
    if (!r) return null;
    if (GYP_BUCKETS.indexOf(r.bucket) >= 0) return r.bucket;
    for (var i = 0; i < GYP_AREA_ASSEMBLIES.length; i++) if (GYP_AREA_ASSEMBLIES[i].id === r.assembly_id) return GYP_AREA_ASSEMBLIES[i].bucket;
    return null;
  }

  /** The row indexes of Gyp area `bucket` that hold a measurement, in takeoff order (the on/off slider is ignored,
   *  as measuredSfRows ignores it). */
  function measuredGypRows(rows, bucket) {
    var out = [];
    (rows || []).forEach(function (r, i) {
      if (r && r.unit !== "LF" && !r.same_floor && gypBucketOf(r) === bucket && num(r.measurement) > 0) out.push(i);
    });
    return out;
  }

  function gypMeasured(rows) {
    return GYP_BUCKETS.some(function (b) { return measuredGypRows(rows, b).length > 0; });
  }

  /** TYPE A FIGURE FOR GYP AREA `bucket`. The area's measured row changes; an area with a blank row of its own
   *  fills it; an area with no row is ADDED as the library's area assembly. True when it wrote. */
  function setGypArea(model, bucket, sf) {
    var v = num(sf);
    var rows = model && model.takeoff;
    if (!(v > 0) || !(rows instanceof Array) || GYP_BUCKETS.indexOf(bucket) < 0) return false;
    var held = measuredGypRows(rows, bucket);
    if (held.length) { rows[held[0]].measurement = v; return true; }
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      if (r && r.unit !== "LF" && !r.same_floor && gypBucketOf(r) === bucket) { r.measurement = v; return true; }
    }
    var asm = GYP_AREA_ASSEMBLIES.filter(function (a) { return a.bucket === bucket; })[0];
    rows.push({ assembly_id: asm.id, assembly_name: asm.name, measurement: v, unit: "SF", bucket: bucket });
    return true;
  }

  /** The row indexes of the linear-foot rows (cove) that hold a measurement, in takeoff order. */
  function measuredLfRows(rows) {
    var out = [];
    (rows || []).forEach(function (r, i) {
      if (r && r.unit === "LF" && !r.same_floor && num(r.measurement) > 0) out.push(i);
    });
    return out;
  }

  /** The measurement of each measured linear-foot row, in order (what the Cove LF boxes show). */
  function measuredLfValues(rows) {
    rows = rows || [];
    return measuredLfRows(rows).map(function (i) { return num(rows[i].measurement); });
  }

  /** THE ROW A FIGURE TYPED INTO THE INTAKE FILLS WHEN NO MEASURED ROW IS THERE FOR IT: the first row of `unit` that is
   *  on, follows no other row and holds no measurement, in the takeoff AFTER row `after` (-1 for anywhere), preferring
   *  one the estimator already picked an assembly or a material for. -1 when there is none. A picked row whose length
   *  is still blank is the row the figure is for: adding another row beside it would count the figure in the
   *  takeoff's total while the picked line stayed unmeasured, and so unpriced. "After" keeps the order the boxes read
   *  in (the first measured row is box 1, the second box 2): a figure for box 2 must not land above box 1's row. */
  function blankRowFor(rows, unit, after) {
    var at = -1;
    (rows || []).forEach(function (r, i) {
      if (i <= after || !r || r.same_floor || !rowOn(r) || num(r.measurement) > 0) return;
      if (!(r.unit === unit || (unit === "SF" && !r.unit))) return;
      if (at < 0 || (!(rows[at].assembly_id || rows[at].item_id) && (r.assembly_id || r.item_id))) at = i;
    });
    return at;
  }

  /** Put `v` in the blank row blankRowFor names, or add a blank-assembly row of `unit` when there is none. */
  function putFigure(rows, unit, v, after) {
    var at = blankRowFor(rows, unit, after);
    if (at < 0) { rows.push({ assembly_id: "", assembly_name: "", measurement: v, unit: unit }); return; }
    rows[at].measurement = v;
    rows[at].unit = unit;
  }

  /** TYPE A LENGTH FOR COVE ROW `k` (0 = the first measured linear-foot row, 1 = the second). The row changes. With
   *  no such row the figure goes into a linear-foot row that is picked but not yet measured (after the first
   *  measured one, for the second), and only when there is none is a blank-assembly row ADDED, as the intake's
   *  seeding adds one. Only 0 and 1, and only a figure above zero. Changes `model.takeoff` in place. True when it wrote.
   *
   *  The boxes read the MEASURED rows in order, so a second length typed while no cove row is measured is the first
   *  measured row afterwards, and the box repaints it as Cove 1. There is no second cove without a first to put it
   *  after, and the figure is counted once. */
  function setAreaLf(model, k, lf) {
    var v = num(lf);
    var rows = model && model.takeoff;
    if (!(rows instanceof Array) || (k !== 0 && k !== 1)) return false;
    if (!(v > 0)) return false;
    var held = measuredLfRows(rows);
    if (k < held.length) rows[held[k]].measurement = v;
    else putFigure(rows, "LF", v, held.length ? held[held.length - 1] : -1);
    return true;
  }

  /** Is row `r` a square-foot line that was picked (an assembly or a material) and has no figure yet? */
  function pickedBlankSf(r) {
    return !!r && !r.same_floor && (r.unit === "SF" || !r.unit) && !!(r.assembly_id || r.item_id) && !(num(r.measurement) > 0);
  }

  /** TYPE A FLOOR SIZE INTO A SECTION THAT HAS NONE YET (nothing measured, so setAreaSf has no area to change), and
   *  the takeoff is seeded the way a new bid's is (seedDefaultTakeoff): ONE row carries the floor, the first blank
   *  square-foot row that is on (a picked one before a bare one, else a blank-assembly row is added), and every OTHER
   *  picked square-foot row with no figure is the same floor, so it carries the number marked `same_floor` and the
   *  area is not counted twice. The library's defaults of a bid opened with no floor are exactly such rows, and
   *  filling only the first would leave the second unpriced. A row switched off follows too (measured, so switching
   *  it on needs nothing typed) but never carries the floor. The area is marked `floor_area` so a second area typed
   *  after it (setAreaSf) gets its own copy of the rows. Only a figure above zero. Changes `model.takeoff` in
   *  place. True when it wrote. */
  function seedAreaSf(model, sf) {
    var v = num(sf);
    var rows = model && model.takeoff;
    if (!(v > 0) || !(rows instanceof Array)) return false;
    var at = blankRowFor(rows, "SF", -1);
    if (at < 0) { rows.push({ assembly_id: "", assembly_name: "", measurement: v, unit: "SF" }); at = rows.length - 1; }
    var tag = 1;
    rows.forEach(function (x) { tag = Math.max(tag, carrierTag(x) + 1, followerTag(x) + 1); });
    var carrier = rows[at];
    carrier.measurement = v;
    carrier.unit = "SF";
    carrier.floor_area = tag;
    rows.forEach(function (r, i) {
      if (i === at || !pickedBlankSf(r)) return;
      r.measurement = v;
      r.unit = "SF";
      r.same_floor = true;
      r.same_floor_of = tag;
    });
    return true;
  }

  /** The names of every intake quantity box, in the vocabulary's order. */
  function boxNames() {
    return types.FIELDS.map(function (f) { return f.name; });
  }

  /** The boxes that share `name`'s tab and unit (its group: System 1 and 2, the two cove boxes, the gypsum three), in
   *  the vocabulary's order. A typed box rewrites its group-mates' draft keys too, so the intake asks for the group. */
  function boxGroup(name) {
    var home = types.fieldHome(name);
    return boxNames().filter(function (n) {
      var h = types.fieldHome(n);
      return !!home && h.tab === home.tab && h.unit === home.unit;
    });
  }

  /** The section that owns quantity box `name`, and where in it the box lives: { entry, home }, or null when the
   *  name is not a box or the bid has no live section for it (a section that is off is not part of the bid). */
  function boxEntry(model, name) {
    var home = types.fieldHome(name);
    if (!home || !isObject(model)) return null;
    var sheets = types.tab(home.tab).sheets;
    var list;
    try { list = sectionsOf(model); } catch (err) { return null; }
    for (var i = 0; i < list.length; i++) {
      if (list[i].kind !== "off" && sheets.indexOf(list[i].tab) >= 0) return { entry: list[i], home: home };
    }
    return null;
  }

  /** Has the section behind `hit` (boxEntry's answer) been measured, so its boxes mirror it? SF rows count,
   *  on or off; a section of linear feet alone has no floor to disagree about. Gyp counts any area row. */
  function boxMeasured(hit) {
    var rows = hit.entry.section.takeoff;
    return hit.home.tab === "gyp" ? gypMeasured(rows) : measuredSfAreas(rows) > 0;
  }

  /** WHAT BOX `name` SHOWS: the figure of its row in the section's takeoff, "" when the section is measured and
   *  has no such row (System 2 of a one-area floor), or null when there is nothing to mirror (the section is not
   *  part of the bid, or not measured yet): then the box keeps what the draft holds and seeds the takeoff. */
  function boxValue(model, name) {
    var hit = boxEntry(model, name);
    if (!hit || !boxMeasured(hit)) return null;
    var rows = hit.entry.section.takeoff, h = hit.home;
    if (h.tab === "gyp") {
      var at = measuredGypRows(rows, GYP_BUCKETS[h.index]);
      return at.length ? num(rows[at[0]].measurement) : "";
    }
    var vals = h.unit === "SF" ? measuredSfValues(rows) : measuredLfValues(rows);
    return h.index < vals.length ? vals[h.index] : "";
  }

  /** WHAT THE DRAFT HOLDS UNDER `name` once a figure typed there has gone into the takeoff, so the draft says what
   *  the takeoff says. The same as boxValue, except for a POOLED group (Polish: one area cell): its first box is
   *  the whole priced area (an off row is out of it; when nothing is on, the measured floor) and the later boxes are
   *  blank, as js/polish-estimate.js leaves them. null when there is nothing to mirror. */
  function boxDraftValue(model, name) {
    var v = boxValue(model, name);
    if (v === null) return null;
    var hit = boxEntry(model, name);
    if (!hit.home.pooled) return v;
    if (hit.home.index > 0) return "";
    var rows = hit.entry.section.takeoff;
    var priced = takeoffSf(rows);
    return priced > 0 ? priced : measuredSf(rows);
  }

  /** The floors with more measured areas than the two boxes reach: [{ tab, areas, total }], one per section. The
   *  intake says so in a plain line and links to the Takeoff. */
  function boxExtras(model) {
    var out = [];
    types.FIELDS.forEach(function (f) {
      var hit = boxEntry(model, f.name);
      if (!hit || hit.home.unit !== "SF" || hit.home.tab === "gyp" || hit.home.index !== 0 || !boxMeasured(hit)) return;
      var rows = hit.entry.section.takeoff;
      var n = measuredSfAreas(rows);
      if (n > 2) out.push({ tab: hit.entry.tab, areas: n, total: measuredSf(rows) });
    });
    return out;
  }

  /** `model` with section `tab`'s takeoff replaced by a copy the caller may edit. A NEW model; the one handed in
   *  (migrateModel's, which holds the SAVED rows) is not touched. `tab` came from sectionsOf over this very model. */
  function withTakeoffCopy(model, tab) {
    var out = Object.assign({}, model);
    if (tab === ROOT_TAB) { out.takeoff = jsonCopy(model.takeoff); return out; }
    var sec = model.tabs[tab];
    out.tabs = Object.assign({}, model.tabs, Object.fromEntries([[tab, Object.assign({}, sec, { takeoff: jsonCopy(sec.takeoff) })]]));
    return out;
  }

  /** The figures typed into the intake's boxes, written to the sections that own them. `boxes` is
   *  { boxName: figure }, only the boxes the estimator typed in. A figure that is not above zero and a box whose
   *  section is not part of the bid write nothing (each writer below refuses a figure that is not above zero).
   *  Boxes are taken in the vocabulary's order, so System 1 goes before System 2 and the second area is added
   *  after the first is set. Returns a NEW model when a figure reached a section and the one handed in when
   *  none did.
   *
   *  A SECTION WITH NOTHING MEASURED. The estimate page seeds the root, and a NEW section, from the draft's box keys
   *  when it opens (seedNewSections), so for those the intake writes nothing here: the library's default takeoff is
   *  still to be laid down, and a figure written first would stop it. But a section that was STARTED (it holds a
   *  labor line, a picked assembly or a figure, so isNewSection says no) is never seeded again, and its takeoff
   *  would stay empty under a draft key that says 5,000 SF: the estimate would price nothing, which is the bug
   *  this function exists to end. So the figure typed into a started, unmeasured section is written here, into the
   *  row it fills (seedAreaSf, setAreaLf, setGypArea) and a figure is written only because the estimator just typed
   *  it, never re-read from a draft key on a later open. */
  function applyBoxes(model, boxes) {
    var copied = [];
    types.FIELDS.forEach(function (f) {
      if (!has.call(boxes, f.name)) return;
      var v = num(boxes[f.name]);
      var hit = boxEntry(model, f.name);
      if (!hit) return;
      var measured = boxMeasured(hit);
      if (!measured && (hit.entry.root || isNewSection(hit.entry.section, false))) return;
      var tab = hit.entry.tab;
      if (copied.indexOf(tab) < 0) { model = withTakeoffCopy(model, tab); copied.push(tab); }
      var view = sectionView(model, tab), h = hit.home;
      if (h.tab === "gyp") setGypArea(view, GYP_BUCKETS[h.index], v);
      else if (h.unit === "LF") setAreaLf(view, h.index, v);
      else if (measured) setAreaSf(view, h.index, v);
      else seedAreaSf(view, v);
    });
    return model;
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

  /** WHICH PROFILE PRICES THE ROOT (Polish) SECTION OF A BID, as a resolved profile. The model's own `profile` key at
   *  the root, and only when it is exactly the stamp of polish-rev2: every other value, and no value at all, is
   *  polish-legacy, so a saved bid (which never had the key) prices as it always did and a stray value cannot move a
   *  total. The key is written once, when a new bid is seeded (seedNewSections). */
  function rootProfile(model) {
    if (!isObject(model)) return LEGACY;
    if (model.profile === REV3.stamp) return REV3;
    return model.profile === REV2.stamp ? REV2 : LEGACY;
  }

  /** The profile markupChain prices with: nothing means polish-legacy (every caller that predates Phase 17), a stamp
   *  or a model names one of the two root profiles. Anything else THROWS: pricing a bid by a profile nobody named is
   *  the wrong bid made quietly. */
  function chainProfile(which) {
    if (which === undefined || which === null) return LEGACY;
    if (typeof which === "string") {
      if (which === LEGACY.stamp) return LEGACY;
      if (which === REV2.stamp) return REV2;
      if (which === REV3.stamp) return REV3;
      throw new Error("markupChain prices the Polish root with " + LEGACY.stamp + ", " + REV2.stamp + " or " + REV3.stamp +
        ", not " + JSON.stringify(which));
    }
    if (isObject(which)) return rootProfile(which);
    throw new Error("markupChain needs a profile stamp or the model, not " + String(which));
  }

  /** POLISH TOOLING AND CONSUMABLES, the sheet's D51 to D55, for a profile that charges them (polish-rev2). Four lines:
   *
   *    D51 tooling and consumables   ROUNDUP(IF(sf * C51 > 150, sf * C51, 150), 0): a $150 minimum, whatever the size.
   *                                  C51 = (V10 + W10) * 1.08 (the calculator's figure, "+8%"). V10 is the tooling cost a
   *                                  square foot of the polish system costs at this size, from the template's
   *                                  `validation` tab (E32:E34 cream, I32:I34 salt and pepper, M32:M34 aggregate
   *                                  exposure; below 4,000 SF, below 7,000 SF, above), and W10 adds $0.20 a square foot
   *                                  for a traditional polish.
   *    D52 demo tooling              a typed square footage at $0.33 ("/sf"); the model has no such box, so 0.
   *    D53 slurry hardener           ROUNDUP(sf / 5000, 0) bags at $210
   *    D54 plastic                   LF at $0.25, when Dye is on, or when the job is 5,000 SF or more AND a renovation.
   *                                  The model has no Renovation answer, so only the Dye leg is reachable (`reno` is the
   *                                  caller's, false when it does not know).
   *
   *  `sf` is the polished area (B35 = E18), `lf` the linear feet (D35 = E19). `opts.system` is the polish system the
   *  sheet picks in F36 ("cream", "sp" or "full"; the template ships "sp"), and `opts.traditional` is G36. THE ONE
   *  DIFFERENCE FROM THE SHEET is a bid with no area at all: the sheet charges its $150 even then, and this charges
   *  nothing (the same call as Epoxy's toolingCost, epoxy-takeoff.js: a bid for nothing has no tooling, and an
   *  Epoxy-only job's Polish root, which is off and empty, must not carry $150).
   *  Answers { consumables, demo, slurry, plastic, rate, total }, whole dollars (`rate` is C51). */
  var POLISH_TOOLING = {
    // validation!E32:E34, I32:I34 and M32:M34, by the size of the job: up to 4,000 SF, under 7,000 SF, and above.
    rates: { cream: [0.6, 0.2, 0.2], sp: [0.85, 0.4, 0.45], full: [1.5, 0.65, 0.75] },
    tiers: [4000, 7000], traditionalPerSf: 0.2, markup: 1.08, min: 150, demoPerSf: 0.33,
    slurryEverySf: 5000, slurryBag: 210, plasticPerLf: 0.25, plasticFromSf: 4999, defaultSystem: "sp"
  };

  function polishTooling(sf, lf, opts) {
    var area = num(sf), run = num(lf), o = opts || {};
    var none = { consumables: 0, demo: 0, slurry: 0, plastic: 0, rate: 0, total: 0 };
    if (!(area > 0)) return none;
    var T = POLISH_TOOLING;
    var system = has.call(T.rates, o.system) ? o.system : T.defaultSystem;
    var tier = area <= T.tiers[0] ? 0 : (area < T.tiers[1] ? 1 : 2);
    var rate = (T.rates[system][tier] + (o.traditional ? T.traditionalPerSf : 0)) * T.markup;
    var perSf = area * rate;
    var consumables = roundUp(perSf > T.min ? perSf : T.min);
    var slurry = roundUp(roundUp(area / T.slurryEverySf) * T.slurryBag);
    var plasticLf = (o.dye || (area > T.plasticFromSf && o.reno)) ? run : 0;
    var plastic = roundUp(plasticLf * T.plasticPerLf);
    return { consumables: consumables, demo: 0, slurry: slurry, plastic: plastic, rate: rate,
             total: consumables + slurry + plastic };
  }

  /** The polish system and kind a takeoff says it is, the way the sheet's F36 and G36 say it: the first row that is on
   *  and names one. "aggregate" is full aggregate exposure, "s&p", "salt" or "pepper" is salt and pepper, "cream" is
   *  cream (the order backend/info_sheet_writer.py reads a polish floor in), and "traditional" in a name is a traditional
   *  polish. A takeoff that names no system gets the template's own, salt and pepper, hybrid. */
  function polishSystemOf(rows) {
    var system = null, traditional = false;
    (rows || []).forEach(function (r) {
      if (!r || !rowOn(r)) return;
      var name = String(r.assembly_name || r.item_name || "").toLowerCase();
      if (!name) return;
      if (/traditional/.test(name)) traditional = true;
      if (system) return;
      if (/aggregate/.test(name)) system = "full";
      else if (/s&p|salt|pepper/.test(name)) system = "sp";
      else if (/cream/.test(name)) system = "cream";
    });
    return { system: system || POLISH_TOOLING.defaultSystem, traditional: traditional };
  }

  /** The options travelCosts takes for the section `tab` of this model: the sheet's way of counting nights (sheetNights) for
   *  a Polish section priced by polish-rev2 (the root of a bid stamped so, or a Polish section under `tabs` that was made
   *  with the stamp), and none for every other section, which count as they always did. */
  function travelOpts(model, tab) {
    if (!isRev2Polish(model, tab)) return undefined;
    // The prevailing rate in force rides along only when there is one, so a bid with none gets exactly the
    // two keys it always did. The nights divide the labor dollars by the crew's rate, and that rate is it.
    var opts = { sheetNights: true, conditions: model.conditions };
    var pw = prevailingApplied(model);
    if (pw > 0) opts.prevailing = pw;
    return opts;
  }

  /** Is the section `tab` of this model a Polish section priced by polish-rev2? The root is when its own `profile` key
   *  says so (rootProfile). A Polish section under `tabs` (a copy, or a sheet added to the bid) is when its own profile
   *  stamp is exactly REV2's. Reads the model without throwing: a tab the model does not hold, or a section that is not
   *  one, is not. */
  function isRev2Polish(model, tab) {
    if (!isObject(model)) return false;
    // polish-rev3 is rev2 with the patch line, so everything rev2 does it does too.
    if (tab === ROOT_TAB) return rootProfile(model) === REV2 || rootProfile(model) === REV3;
    if (!isObject(model.tabs) || !has.call(model.tabs, tab)) return false;
    var s = model.tabs[tab];
    return isObject(s) && s.layout === "polish" && (s.profile === REV2.stamp || s.profile === REV3.stamp);
  }

  /** DOES THIS POLISH SECTION CARRY THE SHEET'S PATCH LINE (Polish!D17)? Its profile says (the `polishPatch` quirk):
   *  polish-rev3, and any later profile that keeps it. Every bid saved before 2026-10-16 is rev2 or legacy and has no
   *  patch line, so its total does not move. Reads the model without throwing. */
  /** WHETHER A SECTION'S CHAIN HAS KYLE'S HARD BID RULE (the profile's hasHardBid): the Polish root on polish-rev3 and
   *  later, and every Epoxy, Seal and Leveling section. Gyp, and a rev2 or legacy Polish root, have none, and the Review
   *  step shows them no switch. */
  function hardBidRuleOn(model, tab) {
    if (!isObject(model)) return false;
    if (tab === ROOT_TAB) return !!rootProfile(model).quirks.hasHardBid;
    if (!isObject(model.tabs) || !has.call(model.tabs, tab)) return false;
    var s = model.tabs[tab];
    var stamp = isObject(s) && typeof s.profile === "string" ? PROFILE_STAMP.exec(s.profile) : null;
    if (!stamp) return false;
    try { return !!engine.resolveProfile(stamp[1]).quirks.hasHardBid; } catch (err) { return false; }
  }

  function polishPatchOn(model, tab) {
    if (!isObject(model)) return false;
    if (tab === ROOT_TAB) return !!rootProfile(model).quirks.polishPatch;
    if (!isObject(model.tabs) || !has.call(model.tabs, tab)) return false;
    var s = model.tabs[tab];
    if (!isObject(s) || s.layout !== "polish") return false;
    var p = s.profile === REV3.stamp ? REV3 : (s.profile === REV2.stamp ? REV2 : (s.profile === LEGACY.stamp ? LEGACY : null));
    return !!(p && p.quirks.polishPatch);
  }

  /** The tooling of a model's ROOT section: the sheet's, for a bid priced by polish-rev2, and 0 for every other (the
   *  legacy bid has no tooling line, and its chain would ignore a figure anyway). Reads the same area and linear feet
   *  the chain's sf is read from. */
  function rootTooling(model) {
    if (!rootProfile(model).quirks.toolingInSubTotal) return 0;
    return takeoffTooling(model.takeoff, model.conditions);
  }

  /** The sheet's tooling for ONE Polish section's takeoff, on a profile that charges it: the same figure rootTooling gives
   *  the root, for a Polish section under `tabs`. `conditions` are the job's (Dye is the job's, not a section's). */
  function takeoffTooling(takeoff, conditions) {
    var rows = takeoff || [];
    var kind = polishSystemOf(rows);
    return polishTooling(takeoffSf(rows), takeoffLf(rows), {
      dye: !!(conditions && conditions.dye), system: kind.system, traditional: kind.traditional }).total;
  }

  /** THE CHAIN. Materials and labor in, a bid out, one key per cell of Kyle's markup column.
   *
   *  `material` is the raw sum of the takeoff assemblies and `labor` the raw sum of the labor
   *  rows -- both unrounded, because D31 and D45 are where the sheet rounds them.
   *
   *  A WRAPPER SINCE PHASE 8. The arithmetic (every ROUNDUP, every base, the Epoxy and Leveling quirks that
   *  this tab does not have) is js/bid-engine.js priceChain, and the rates are the profile `polish-legacy`'s.
   *  This function hands the job over and returns the keys it has always returned, with the values it has
   *  always returned: backend/tests/fixtures/polish_chain_golden.json is the proof, vector by vector. The
   *  notes that used to sit in this body (the remodel rate's null against zero, the fees line being marked
   *  up, the bond base counting the taxes twice) are in the engine beside the lines they explain. */
  function markupChain(input, which) {
    var profile = chainProfile(which);
    var r = engine.priceChain(profile, input);
    var out = {
      material: r.material, shipping: r.shipping, material_total: r.material_total,
      labor: r.labor, escalation: r.escalation, burden: r.burden, labor_total: r.labor_total,
      travel: r.travel,
      sub_total: r.sub_total,
      gp_pct: r.gp_pct, gp: r.gp,
      super_pto: r.super_pto, soft_costs: r.soft_costs, contingency: r.contingency,
      sales_tax_pct: r.sales_tax_pct, sales_tax: r.sales_tax,
      remodel_pct: r.remodel_pct, remodel_tax: r.remodel_tax, taxes: r.taxes,
      fees: r.fees, bond: r.bond, bond_pct: r.bond_pct, fees_and_bond: r.fees_and_bond,
      total: r.total,
      sf: r.sf,
      per_sf: r.per_sf
    };
    // The tooling line is part of the bid only on a profile that charges it, so the key is not there on the
    // legacy answer (every saved bid keeps exactly the keys it always had).
    if (profile.quirks.toolingInSubTotal) out.tooling = r.tooling;
    // THE RATES AN OVERRIDE MOVED, and the discount line, reported only when the section has overrides, so a bid that
    // never typed one answers with exactly the keys it always did (polish_chain_golden.json is the proof).
    if (input && input.adjust && Object.keys(input.adjust).length) {
      out.ship_pct = r.ship_pct; out.super_pct = r.super_pct; out.soft_pct = r.soft_pct;
      out.hard_bid = r.hard_bid; out.hard_bid_pct = r.hard_bid_pct;
      if (r.discount_refused) out.discount_refused = true;
    } else if (r.hard_bid) {
      // A DISCOUNT THE HARD BID RULE GAVE (polish-rev3, the job's Hard bid switch on), with nothing typed. Only a bid
      // that answered Hard bid has one, so every other bid keeps its keys.
      out.hard_bid = r.hard_bid; out.hard_bid_pct = r.hard_bid_pct;
    }
    return out;
  }

  // ── the model the page holds ────────────────────────────────────────────────
  /** THE COMPANY LABOR RATE. One number, set on Items & Assemblies -> Labor (filed as the Global markup row `labor_rate`), and
   *  the starting rate of every labor line on a NEW bid: the three crew rows, Travel Labor, every
   *  library labor row that has no rate of its own, and every line the estimator adds. 33 is
   *  Kyle's sheet (C37 / C44) and is what stands when nothing is filed or the read failed.
   *
   *  A SAVED BID NEVER MOVES. This is a starting point, read once when a bid is first opened and
   *  never applied to a model that already states a labor row (laborUnstated is the gate). */
  var SHIPPED_LABOR_RATE = engine.defaultNumber("labor_rate");

  // ── THE ESTIMATOR'S OVERRIDES ON A SECTION (Hanz, 2026-10-16) ─────────────────────────────────────────────────
  // What Kyle types OVER his own sheet's rules, as boxes on the Review step, one set per section (a section is one
  // workbook tab, and each tab has its own cells). Approved after a scan of the bids made from 2026-08-16 to 10-16:
  // the discount (his "Hard Bid Discount" line, B74/D74 Epoxy, B68/D68 Polish) on 21 of 41, Bulk Discount on 11 Epoxy
  // bids, soft or super % on 4, GP and shipping on 1 each, and his supplier discount (B41/C41) on the Jayhawk job.
  // This REVERSES 2026-09-22 ("remove all hard bids ... and also on the markups"): the line is back as a plain
  // per-bid discount, never tied to a hard-bid answer, and blank is no discount.
  //
  // STORED AS TYPED (text or a number), like contingency and fees, so a half-typed "1." is not snapped while
  // somebody is typing it. `chainAdjust` and `materialAdjust` read them; a box that does not read as a usable figure
  // is left out of the price and named by `adjustProblems`, never priced as zero and never allowed to break the bid.
  //
  //   discount_pct   % off the bid (Kyle's B74 / B68). Taken as its size: "3", "-3", "3%" are all 3% off.
  //   discount_amt   $ off the bid (Kyle's D74 / D68 typed). Wins over the % when both are typed.
  //   ship_pct, gp_pct, super_pct, soft_pct   the rate, in %, that replaces the sheet's rule for that line
  //   supplier_pct   % off the Sherwin-Williams liquids (Epoxy B41); the escalation is kept (see MATERIAL_ESCALATION)
  //   polycrete_pct  % off the Poly-Crete liquids (Epoxy C41); blank follows supplier_pct, as C41 = B41 does
  //   (no `bulk`: the Bulk Discount switch was removed from v2 on 2026-10-20, Hanz; normalizeAdjust drops a saved one)
  //   hard_bid       the Hard bid switch (Hanz, 2026-10-17; the tab's B5): Kyle's rule fills the discount, 4% from a
  //                  $60,000 sub-total, 2.5% on a local job from $13,000, until a discount is typed. A section's own
  //                  answer, as each of his tabs has its own B5, and kept here rather than in the job's `conditions` so a
  //                  bid that never pressed it saves exactly what it saved before.
  var ADJUST_PCT_KEYS = Object.freeze(["discount_pct", "ship_pct", "gp_pct", "super_pct", "soft_pct",
                                       "supplier_pct", "polycrete_pct"]);
  var ADJUST_KEYS = Object.freeze(ADJUST_PCT_KEYS.concat(["discount_amt", "hard_bid"]));

  /** THE ESCALATION BAKED INTO EVERY LIBRARY COST the workbook seed wrote: Kyle's Epoxy!U140, +6%. A library cost is
   *  the list price x 1.06; the sheet's discounted price is list x (1 + 0.06 - discount). So a discount is applied as
   *  (1 + E - d) / (1 + E) of the library cost, which is the sheet's figure exactly, rather than as (1 - d), which
   *  would also take the discount off the escalation. */
  var MATERIAL_ESCALATION = 0.06;

  /** The discount groups of Kyle's sheet, by the vendor a library material names (the seed tags them from each
   *  material's price column): the Epoxy discount takes the Sherwin-Williams liquids (column T, T141), the Poly-Crete
   *  discount takes SL, MD and WR (T142). Sand, flake, quartz and the rest name neither and are never discounted. */
  var DISCOUNT_VENDORS = Object.freeze({ supplier_pct: "Sherwin-Williams", polycrete_pct: "Poly-Crete" });

  /** A box as typed, as a fraction: "3", "3%", " 3 % " and 3 are all 0.03. Null for a blank or anything that is not
   *  a plain number (an expression, "abc", "3%%"). */
  function pctFraction(v) {
    if (v === null || v === undefined) return null;
    if (typeof v === "number") return isFinite(v) ? parseFloat((v / 100).toPrecision(12)) : null;
    if (typeof v !== "string") return null;
    var t = v.replace(/\s+/g, "");
    if (t === "") return null;
    if (t.charAt(t.length - 1) === "%") t = t.slice(0, -1);
    if (!/^[+-]?(\d+\.?\d*|\.\d+)$/.test(t)) return null;
    // To twelve significant figures HERE, the one place, so the range check and the figure the chain is handed are the
    // same number: checked unrounded, 99.99999999999 passed as under 100% and then reached the chain as exactly 1.
    return parseFloat((Number(t) / 100).toPrecision(12));
  }

  /** A dollar box as typed: "1,500", "$1500", "-1500" and 1500 all read. Null for a blank or anything else. */
  function dollars(v) {
    if (v === null || v === undefined) return null;
    if (typeof v === "number") return isFinite(v) ? v : null;
    if (typeof v !== "string") return null;
    var t = v.replace(/[\s,$]/g, "");
    if (t === "") return null;
    if (!/^[+-]?(\d+\.?\d*|\.\d+)$/.test(t)) return null;
    return Number(t);
  }

  /** The highest a % box may say, and the lowest. GP divides by (1 - gp), so 100% is no price at all; a discount of
   *  100% or more is a free floor; a negative markup, shipping or supplier discount is not what any of these boxes is
   *  for (the supplier discount is money off, never a surcharge). */
  function pctInRange(key, f) {
    if (key === "discount_pct") f = Math.abs(f);
    return f >= 0 && f < 1;
  }

  /** A saved `adjust` as the model keeps it: only the known keys, each as it was typed, with blanks, `false` and
   *  anything that is not text, a number or (for `bulk`) `true` dropped. Null when nothing is left, so a section that
   *  never used the boxes saves no key at all and prices exactly as before. Never throws. */
  function normalizeAdjust(raw) {
    if (!isObject(raw)) return null;
    var out = {}, any = false;
    ADJUST_KEYS.forEach(function (k) {
      if (!Object.prototype.hasOwnProperty.call(raw, k)) return;
      var v = raw[k];
      if (k === "hard_bid") { if (v === true) { out.hard_bid = true; any = true; } return; }
      if (typeof v === "number" && isFinite(v)) { out[k] = v; any = true; return; }
      if (typeof v === "string" && v.trim() !== "") { out[k] = v.slice(0, 32); any = true; }
    });
    return any ? out : null;
  }

  /** The boxes that are typed but cannot be used, as `{key, text}` in the order the Review step draws them. A box here
   *  is left OUT of the price (the rule's own figure stands) and the page says so beside it. */
  function adjustProblems(adj) {
    var a = normalizeAdjust(adj) || {};
    var out = [];
    ADJUST_PCT_KEYS.forEach(function (k) {
      if (!Object.prototype.hasOwnProperty.call(a, k)) return;
      var f = pctFraction(a[k]);
      if (f === null) out.push({ key: k, text: "not a number, so it is not used" });
      else if (!pctInRange(k, f)) out.push({ key: k, text: "must be from 0 to under 100%, so it is not used" });
    });
    if (Object.prototype.hasOwnProperty.call(a, "discount_amt") && dollars(a.discount_amt) === null) {
      out.push({ key: "discount_amt", text: "not a dollar figure, so it is not used" });
    }
    return out;
  }

  /** The material overrides alone (supplier, Poly-Crete), and the Hard bid switch: what a section's boxes do to
   *  its MATERIAL, and which rule its discount follows, without the figures typed over the markup lines. The Review step
   *  greys each markup box with the rule's figure for the material the section really buys (and the Discount box with
   *  the hard bid rule's), so the rule it shows is the one a typed figure replaces. Null when there are none. */
  function materialOnlyAdjust(adj) {
    var a = normalizeAdjust(adj);
    if (!a) return null;
    return normalizeAdjust({ supplier_pct: a.supplier_pct, polycrete_pct: a.polycrete_pct, hard_bid: a.hard_bid });
  }

  /** The job's conditions as one section's chain reads them: the section's Hard bid switch (its `adjust`) is the
   *  chain's `hard_bid`. The job's own object is handed back untouched when the switch is off. */
  function chainConditions(conditions, adj) {
    var a = normalizeAdjust(adj);
    return a && a.hard_bid ? Object.assign({}, conditions || {}, { hard_bid: true }) : conditions;
  }

  /** What the markup chain takes from a section's boxes (bid-engine's `adjust`): fractions for the rates, the
   *  discount's size, the dollars. A box adjustProblems names is left out. Empty when nothing usable is typed. */
  function chainAdjust(adj) {
    var a = normalizeAdjust(adj) || {};
    var out = {};
    ["discount_pct", "ship_pct", "gp_pct", "super_pct", "soft_pct"].forEach(function (k) {
      if (!Object.prototype.hasOwnProperty.call(a, k)) return;
      var f = pctFraction(a[k]);
      if (f === null || !pctInRange(k, f)) return;
      out[k] = parseFloat((k === "discount_pct" ? Math.abs(f) : f).toPrecision(12));
    });
    if (Object.prototype.hasOwnProperty.call(a, "discount_amt")) {
      var d = dollars(a.discount_amt);
      if (d !== null) out.discount_amt = Math.abs(d);
    }
    return out;
  }

  /** What a section's boxes do to its MATERIAL prices (library-core's itemsForBid): the fraction off each discount
   *  group's library cost. `bulk` is always false: v2 has no Bulk Discount switch (2026-10-20), so a material is never
   *  bought at its bulk cost here; library-core keeps the ability for the library's own use. A Poly-Crete box left blank follows the supplier box, as Kyle's
   *  C41 is `=B41`. Unusable boxes are left out, as everywhere else. */
  function materialAdjust(adj) {
    var a = normalizeAdjust(adj) || {};
    var off = function (k) {
      if (!Object.prototype.hasOwnProperty.call(a, k)) return null;
      var f = pctFraction(a[k]);
      return (f === null || !pctInRange(k, f)) ? null : f;
    };
    var sw = off("supplier_pct");
    var pc = Object.prototype.hasOwnProperty.call(a, "polycrete_pct") ? off("polycrete_pct") : sw;
    var discounts = {};
    if (sw) discounts[DISCOUNT_VENDORS.supplier_pct] = sw;
    if (pc) discounts[DISCOUNT_VENDORS.polycrete_pct] = pc;
    return { bulk: false, discounts: discounts, escalation: MATERIAL_ESCALATION };
  }

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

  /** THE FEES + TEXTURA DEFAULT (Hanz, 2026-10-06). One dollar figure, filed as the Markups -> Global
   *  line `fees_textura` (the Defaults tab's "Fees + Textura" box is a second door onto the same
   *  row), and the starting value of D77 on a NEW beta bid. Null when none is filed, switched off,
   *  or not a plain number; ZERO IS A REAL ANSWER ("nothing", which is what the sheet ships), so
   *  unlike the labor rate this accepts 0 and the caller treats 0 and null alike. */
  function feesFromRules(rules) {
    if (!(rules instanceof Array)) return null;
    for (var i = 0; i < rules.length; i++) {
      var r = rules[i];
      if (!r || r.layout !== "global" || r.line_key !== "fees_textura") continue;
      if (r.applies === false) return null;
      var m = /^\s*\$?\s*(\d+(?:\.\d+)?)\s*$/.exec(String(r.formula === null ||
        r.formula === undefined ? "" : r.formula));
      if (!m) return null;
      var n = Number(m[1]);
      return isFinite(n) ? n : null;
    }
    return null;
  }

  /** A NEW bid's Fees + Textura line, started at the default. NEW BIDS ONLY: the caller's gate is
   *  laborUnstated, the same one the labor and travel defaults ride, so a saved bid never reaches
   *  this. A default of nothing (null / 0 / junk) changes NOTHING -- the model keeps RATES.FEES --
   *  and stamps nothing, because "Default value: $0" under a box the estimator typed a fee into
   *  would warn about a default nobody set. A real default is written to `fees` AND remembered as
   *  `fees_default`, which is what the shared amber warning compares against and which, being part
   *  of the saved model, survives a reload. Returns a NEW model. */
  function applyFeesDefault(model, fees) {
    var n = (fees === null || fees === undefined || fees === "") ? NaN : Number(fees);
    if (!model || !isFinite(n) || n <= 0) return model;
    var out = {};
    for (var k in model) if (Object.prototype.hasOwnProperty.call(model, k)) out[k] = model[k];
    out.fees = n;
    out.fees_default = n;
    return out;
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
      // Travel and the three crew lines move only while still on the shipped $33 or blank: a rate
      // the library gave one of them is that rate's to keep (the crew lines are library rows now).
      var onShipped = (id === "travel" || isCrewId(id)) &&
        (isBlank(r.rate) || !isFinite(Number(r.rate)) || Number(r.rate) === SHIPPED_LABOR_RATE);
      if (onShipped) {
        var copy = copyInto({}, r);
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
      var copy = copyInto({}, r);
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
             // `dflt` is the company labor rate (Items & Assemblies -> Labor). Omitted, it is the shipped
             // $33.00, which is what the library page's Reset and its "is this still the shipped
             // row" comparison rely on -- they call travelSeed() with no second argument.
             rate: (isBlank(r.rate) || !isFinite(rate)) ? laborRateOrShipped(dflt) : rate,
             unit: isBlank(r.unit) ? "hours" : String(r.unit),
             guys_auto: Object.prototype.hasOwnProperty.call(r, "guys_auto")
               ? !!r.guys_auto : true };
  }

  /** The Travel row's `hours_seed` marker: the drive hours the distance wrote there, "" while it has
   *  written none. followDistanceHours writes it and reads it back (2026-10-20) to tell a figure the
   *  tool wrote from one somebody typed. The shipped model's Travel row carries it empty; a new bid's
   *  Travel row has it taken off again (laborRowStartsEmpty), and the fill treats a missing marker and
   *  an empty one alike, so a row without it is filled all the same. It stays on freshModel() because
   *  that model's exact shape is pinned by the polish chain golden. */
  function withHoursSeed(row) { row.hours_seed = ""; return row; }

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
    // `dflt` omitted is the old behaviour exactly (the stored number, 0 included). The three crew
    // lines are seeded at the shipped $33.00, which nobody chose, so it reads as "no rate" for them
    // exactly as it does for Travel.
    var rate = (dflt !== undefined && dflt !== null && !libraryRateIsOwn(r, isCrewId(r.id)))
      ? laborRateOrShipped(dflt) : Number(r.rate);
    var out = { id: r.id, label: r.name, guys: "", days: "", rate: rate,
                unit: r.unit, guys_auto: !!r.guys_auto };
    // THE DEFAULTS-TAB SLIDER: a default saved as OFF starts the bid's row switched off (grayed,
    // $0). Written only when explicitly false, so every other row keeps exactly the shape it had.
    if (r.default_on === false) out.enabled = false;
    return out;
  }

  /** ONE library Labor row as the labor card it becomes when an estimator picks it from the
   *  Labor step's search pop-up: the SAME mapping seedLibraryLabor uses (libraryLaborRow), then the
   *  `rate_default` stamp a new bid gets (stampRateDefaults), so the "Default value" note and the
   *  blank-rate fallback behave on a picked line exactly as on a seeded one. Guys and days start
   *  empty. A NEW object. */
  function laborRowFromLibrary(row, dflt) {
    // A line picked for a bid never takes its Guys from the man-days (2026-10-12), whatever the
    // library row's guys_auto says.
    return stampRateDefaults([laborRowStartsEmpty(libraryLaborRow(row, dflt))])[0];
  }

  /** WHAT THE LABOR POP-UP SAYS A LINE COSTS (Hanz, 2026-10-12): the rate the line will start at,
   *  in plain words. A rate is ALWAYS dollars an hour, on a "Days" line too (laborCost multiplies
   *  guys x days x rate x hours in a day), so it never reads "a day": "$33.00 a day" would be an
   *  eighth of what the card charges. A line with no rate of its own starts at the company labor
   *  rate (libraryLaborRow's rule, asked of libraryRateIsOwn, not restated) and says so. */
  function laborPriceText(row, companyRate) {
    var r = row || {};
    if (libraryRateIsOwn(r, isCrewId(r.id))) return money2(Number(r.rate)) + " an hour";
    return money2(laborRateOrShipped(companyRate)) + " an hour (labor rate)";
  }

  /** The note under the pop-up's One-off line: where a typed line starts. */
  function oneOffRateText(companyRate) {
    return "Starts at the company labor rate, " + money2(laborRateOrShipped(companyRate)) + " an hour.";
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
   *  TRAVEL FOLLOWS THE SAME TWO FLAGS (Hanz, 2026-10-06), through travelAppliesToBid below: a
   *  stored Travel row that is not a default (`favorite` false) or is scoped to other work types
   *  (`default_work_types`) leaves Travel OFF a new bid -- the row freshModel put there is taken
   *  out again -- and every other case is today's behaviour. No stored row, or a row whose
   *  `favorite` is absent/null with no work types, is Travel on every new bid, as it always was.
   *  The Defaults tab's Edit / Remove and the Labor tab's work-type chips on Travel write exactly
   *  these two fields, so each of those controls changes what a new bid opens holding.
   *
   *  `workType` is the kind of bid being opened ("polish" -- the only estimate that seeds labor
   *  today); the work-type scope applies to every row, Travel and the custom lines alike. */
  function seedLibraryLabor(labor, rows, dflt, workType) {
    var out = (labor instanceof Array) ? labor.slice() : [];
    if (!(rows instanceof Array)) return out;
    var wt = workType || "polish";
    // A Set, not an object keyed by the row id: ids come out of the library and out of saved drafts, and a
    // key that is user data does not belong on a plain object (CodeQL js/remote-property-injection).
    var seen = new Set();
    var i;
    for (i = 0; i < out.length; i++) {
      if (out[i] && out[i].id !== null && out[i].id !== undefined) seen.add(String(out[i].id));
    }
    for (i = 0; i < rows.length; i++) {
      var r = rows[i];
      if (!r || r.id === null || r.id === undefined) continue;
      var rid = String(r.id);
      if (rid === "travel") {
        if (!travelAppliesToBid(r, wt)) {
          // Not a default, or not for this work type: the bid does not get Travel. The row
          // freshModel put on the model is taken out (a copy; the input array is never touched).
          out = out.filter(function (x) { return !(x && String(x.id) === "travel"); });
          seen.add(rid);
          continue;
        }
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
          if (Object.prototype.hasOwnProperty.call(out[at], "hours_seed")) travel.hours_seed = out[at].hours_seed;
          out[at] = travel;
        }
        seen.add(rid);
        continue;
      }
      if (!r.favorite) continue;
      if (!workTypeApplies(r, wt)) continue;
      if (seen.has(rid)) continue;
      seen.add(rid);
      out.push(libraryLaborRow(r, dflt));
    }
    return out;
  }

  /** Does a default scoped by `row.default_work_types` apply to this kind of bid? EMPTY / ABSENT MEANS
   *  EVERY TAB -- work-types.js's appliesTo, the one reading the library page's appliesToWorkType and
   *  seedDefaultTakeoff share.
   *
   *  A default's work types are TABS, and a job type is priced on one or more of them, so a default
   *  applies when it applies to ANY tab of the job: a combo job reads the Epoxy list AND the Polish
   *  list, where it used to read neither (nothing is filed under "combo"). `workType` is the job type,
   *  "polish" when it is left out (the one job this model has priced), and anything that is not a job
   *  type THROWS from tabsFor rather than answering "no" quietly. */
  function workTypeApplies(row, workType) {
    var list = row && row.default_work_types;
    // A SECTION IS ONE TAB, and an option tab (Seal, Leveling) is not a job type, so a section is named by
    // `{ tab: "seal" }`, never by the bare string: a bare tab key still THROWS from tabsFor, which is the guard
    // against reading a job's defaults under the wrong name. The object says "exactly this tab", and `types.tab`
    // refuses anything that is not one. A Seal option is seeded with it, from the defaults filed under the Seal pill.
    if (workType && typeof workType === "object") {
      return types.appliesTo(list, types.tab(String(workType.tab)).key);
    }
    return types.tabsFor(workType || "polish").some(function (tab) { return types.appliesTo(list, tab); });
  }

  /** What to hand workTypeApplies, seedLibraryLabor, seedDefaultTakeoff and travelDeclined for a SECTION of a bid:
   *  the section's layout, which is a job type for Polish, Epoxy and Gyp (so those read exactly what they always
   *  read, a job type's defaults) and a bare tab for an option (Seal), named as `{ tab }`. */
  function kindOfSection(layout) {
    return types.isJobType(layout) ? layout : { tab: layout };
  }

  /** Does the stored Travel row (library_labor id `travel`) put Travel on a NEW bid of this work
   *  type? NO ROW IS YES, and so is a row whose `favorite` is absent/null with no work types:
   *  Travel has been on every new bid since it shipped and nothing stored may change that by
   *  being silent. Only an explicit `favorite: false` (the Defaults tab's Remove) or a work-type
   *  list that leaves this one out turns it off. */
  function travelAppliesToBid(row, workType) {
    if (!row) return true;
    if (row.favorite === false) return false;
    return workTypeApplies(row, workType);
  }

  /** Did seeding leave Travel off this new bid? True exactly when the library's Travel row says
   *  not to put it on. The caller records the answer on the model (`no_travel_labor`) so a reload
   *  does not mistake the missing row for a stale draft and append it back (migrateModel). */
  function travelDeclined(rows, workType) {
    if (!(rows instanceof Array)) return false;
    for (var i = 0; i < rows.length; i++) {
      if (rows[i] && String(rows[i].id) === "travel") return !travelAppliesToBid(rows[i], workType);
    }
    return false;
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

  /** The conditions this model carries that ALSO live as Yes/No literals in Kyle's workbook.
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
   *  Polish!B4 holds its own Yes/No, so Local writes both B4 cells, while Polish!D5, B6 and D6 are the
   *  formulas =Epoxy!D5 / =Epoxy!B6 / =Epoxy!D6, and writing them would replace a live reference with
   *  a literal.
   *
   *  DERIVED, NOT TYPED, SINCE PHASE 7 (js/work-types.js). The cells, the literals and which job types
   *  are asked each condition are rows of the one job-conditions table, and this is that table cut for
   *  the one job type this model prices (polish), keeping the conditions the model CARRIES. A job type
   *  writes exactly the cells the live intake writes for it, because both come from the same rows:
   *  that is what puts the Leveling and Gypsum Taxable cells in here (Taxable is four cells, not one),
   *  which this mapping used to leave out, so a tax-exempt option on a v2 bid kept charging 9.475%.
   *  The first cell of a row is the one the intake reads the switch back from.
   *
   *  NO hard_bid ENTRY. It used to write Epoxy!B5/Polish!B5; a cell this beta never writes to is a
   *  blank cell, and Kyle's own =IF(B5="yes",...) reads a blank the same way it reads "No" -- so
   *  leaving the entry out is enough, with nothing to change in his real sheet. `bond` has no cell.
   *
   *  Dye, joint filler and remove-existing MOVED OFF THE INTAKE FORM on 2026-09-16 (Hanz asked for
   *  them on the Takeoff step, where the work they describe is), and they were moved INTO THE MODEL:
   *  two screens can answer them, so there is one writer, `conditionCellWrites`, called by both. BOTH
   *  LITERALS, ALWAYS, INCLUDING remove_existing_jf WHILE JOINT FILLER IS OFF: a blank Yes/No cell is
   *  not "No" to Kyle's formulas, it is whatever his IF() falls through to. The switch greys out on
   *  screen because it moves no money, not because its answer stopped existing. */
  var POLISH_CELLS = types.cellsFor("polish");
  var MODEL_JOB = "polish";   // the job type cellsFor() was cut for on the line above, asked again below
  var CONDITION_CELLS = Object.fromEntries(POLISH_CELLS
    .filter(function (c) { return c.model; })
    .map(function (c) { return [c.key, { cells: c.cells, on: c.on, off: c.off }]; }));

  /** The conditions this job is asked on the live intake and the model does NOT carry: Renovation
   *  (Epoxy!B10 and Polish!B10). Estimating Tool v2 has no question for it (Hanz, 2026-09-23, took the
   *  toggle off its intake), so it has no answer on the model -- and the live intake writes it for every
   *  polish job, so a job that arrives from there has it in cell_values, or a draft whose AI autofill
   *  set it has. conditionCellWrites carries the answer through and writes the default only while the
   *  cell is blank, exactly what the live intake does with it: a blank Polish!B10 is not "New" to
   *  Polish!C17 (IF(B10="New",0.05,0.15)), it takes the Reno branch and triples the patch material rate.
   *  Each is { key, cells, on, off, default }. */
  var CARRIED_CELLS = POLISH_CELLS
    .filter(function (c) { return !c.model; })
    .map(function (c) { return { key: c.key, cells: c.cells, on: c.on, off: c.off, default: c.default }; });

  /** `cells` with every condition's literals written over it (conditionCellWrites below).
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
   *  applies rather than a silent "off".
   *
   *  A CONDITION WITH SEVERAL CELLS IS ANSWERED BY THE FIRST ONE THAT HOLDS AN ANSWER, not by the first
   *  cell: Local is two cells (Epoxy!B4 and Polish!B4) and Taxable is four, and a blank first cell with
   *  an answer after it is an answered question. Reading only the first took the default instead, and the
   *  next save wrote that default over the real answer in every cell of the row.
   *
   *  `split` is whether the draft is split (work-types.js isSplit(draft)): once the estimate screen has
   *  given every sheet its own Taxable and Remodel answer, those two are the BASE sheet's own cell and no
   *  other (work-types.js writeCellsFor decides, for this and for conditionCellWrites). It is the draft's
   *  to say and not the cells', so it is an argument; left out, the draft is not split. */
  function conditionsFromCells(conditions, cells, split) {
    var out = Object.assign({}, conditions || {});
    var cv = (cells && typeof cells === "object") ? cells : {};
    for (var key in CONDITION_CELLS) {
      if (!CONDITION_CELLS.hasOwnProperty(key)) continue;
      var cell = firstFilled(types.writeCellsFor(key, MODEL_JOB, !!split), cv, unanswered);
      if (cell === undefined) continue;
      out[key] = String(cell).trim().toLowerCase() ===
                 String(CONDITION_CELLS[key].on).toLowerCase();
    }
    return out;
  }

  /** What a cell that is absent, null or "" says: nothing. (Whitespace is an answer here, and reads as no.) */
  function unanswered(v) { return v == null || v === ""; }

  /** The value of the first of `list`'s cells that holds an answer, or undefined when none does.
   *  `blank` is the test for "holds no answer": conditionsFromCells and the carried conditions below
   *  have always disagreed about whitespace, and each keeps its own. */
  function firstFilled(list, values, blank) {
    for (var i = 0; i < list.length; i++) {
      var v = values[list[i]];
      if (!blank(v)) return v;
    }
    return undefined;
  }

  /** `cells` with every condition's literals written over it, merged and never blank for "off" (the
   *  first doc block above says why). `split` is the draft's (see conditionsFromCells): on a split draft
   *  Taxable and Remodel tax are written to the base sheet's own cell and every other sheet's tax cell
   *  is left exactly as the draft has it, so an option keeps its own answer through a save. The same
   *  rule the live intake follows (js/index.js splitFlagCells), from the same table. */
  function conditionCellWrites(conditions, cells, library, split) {
    var out = Object.assign({}, cells || {});
    var c = conditions || {};
    for (var key in CONDITION_CELLS) {
      if (!CONDITION_CELLS.hasOwnProperty(key)) continue;
      var spec = CONDITION_CELLS[key];
      var lit = c[key] ? spec.on : spec.off;
      var to = types.writeCellsFor(key, MODEL_JOB, !!split);
      for (var i = 0; i < to.length; i++) out[to[i]] = lit;
    }
    // THE CONDITIONS THE MODEL DOES NOT CARRY (Renovation): the answer is whatever the first cell that
    // holds one says, else the default, and it is written to every cell of the row -- the live intake's
    // own read-then-write, so a "Reno" it or the AI autofill put there survives a v2 save and a blank
    // gets "New". The first cell THAT HOLDS ONE, not the first cell: a "Reno" in Polish!B10 with
    // Epoxy!B10 blank is an answer, and reading only the first turned it into "New" on the next save.
    CARRIED_CELLS.forEach(function (carried) {
      var first = firstFilled(carried.cells, out, isBlank);
      var on = isBlank(first) ? carried.default
        : String(first).trim().toLowerCase() === String(carried.on).trim().toLowerCase();
      carried.cells.forEach(function (cell) { out[cell] = on ? carried.on : carried.off; });
    });
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

  /** THE THREE CREW LINES, as the Labor list holds them (Hanz, 2026-10-09: "Labor is like the Items
   *  tab for pulling in data in the estimate sheet"). They are rows of public.library_labor with
   *  these SAME ids, so a bid saved before they moved and a bid opened after read the same rows
   *  (seedLibraryLabor's id de-dup keeps the two from doubling), and the starting guys / days live
   *  where every other default's do: a `fixed` row of library_labor_calc keyed by the line id.
   *
   *  THE LIBRARY IS THE SOURCE; THIS CONSTANT IS ONLY THE FALLBACK, the dye / joint filler reserved
   *  row contract: it stands when the library cannot answer (a database the seed has not reached, a
   *  read that failed) and nowhere else. backend/ops/seed_crew_labor.sql writes the same figures,
   *  and test_crew_labor_library.py pins the two equal. `rate` is the $33.00 the sheet ships, which
   *  libraryLaborRow reads as "no rate of its own" so these follow the company labor rate until an
   *  admin types one. `guys`/`days` are the starting crew; blank days is an unknown, never 0. */
  var SHIPPED_CREW = [
    { id: "polishing", name: "Polishing", sort: 1, guys: 3, days: "" },
    { id: "mockup", name: "Mock-up", sort: 2, guys: 3, days: 0.5 },
    { id: "jointfill", name: "Joint filler", sort: 3, guys: 3, days: "" }
  ];

  function isCrewId(id) {
    for (var i = 0; i < SHIPPED_CREW.length; i++) if (SHIPPED_CREW[i].id === String(id)) return true;
    return false;
  }

  /** The shipped crew lines as library_labor rows (what GET /api/library/labor returns). */
  function shippedCrewRows() {
    return SHIPPED_CREW.map(function (c) {
      return { id: c.id, name: c.name, rate: SHIPPED_LABOR_RATE, unit: "days", guys_auto: false,
               sort: c.sort, notes: "", favorite: true, default_on: null, default_work_types: ["polish"] };
    });
  }

  /** The shipped crew lines' starting guys / days as library_labor_calc rows (GET
   *  /api/library/labor-calc). `rate` null is the company labor rate. */
  function shippedCrewCalc() {
    return SHIPPED_CREW.map(function (c) {
      return { line_id: c.id, mode: "fixed", crew: null, sf_per_day: null, hours_per_day: 8,
               guys: c.guys, days: c.days === "" ? null : c.days, rate: null };
    });
  }

  /** `rows` (the library's labor list) with the shipped crew lines added WHEN THE LIBRARY HAS NONE
   *  OF THEM: not one of the three ids, favorited or not. That is the only way this can tell "the
   *  library cannot answer" (no table, a failed read) from "somebody took a line off the defaults"
   *  (its row is still listed, favorite false), and only the first is the fallback's to answer.
   *  A NEW array; the input is never touched. */
  function withCrewFallback(rows) {
    var out = (rows instanceof Array) ? rows.slice() : [];
    for (var i = 0; i < out.length; i++) if (out[i] && isCrewId(out[i].id)) return out;
    return out.concat(shippedCrewRows());
  }

  /** `cfgs` (the labor calculator's rows) plus the shipped starting guys / days for each crew line
   *  that has no row of its own. A mode cannot be cleared once saved, so an absent one only ever
   *  means the seed has not reached this database. A NEW array. */
  function withCrewCalcFallback(cfgs) {
    var out = (cfgs instanceof Array) ? cfgs.slice() : [];
    var have = {};
    out.forEach(function (c) { if (c && c.line_id) have[String(c.line_id)] = true; });
    shippedCrewCalc().forEach(function (c) { if (!have[c.line_id]) out.push(c); });
    return out;
  }

  /** The four rows freshModel() used to carry, for what still has to READ a model that states no
   *  rows of its own: migrateModel on a saved v2 blob with an empty `labor`, and a v1 draft. The
   *  figures come from SHIPPED_CREW, so there is one list. A NEW array of NEW rows each call. */
  function legacyLabor() {
    var rows = SHIPPED_CREW.map(function (c) {
      return { id: c.id, label: c.name, guys: c.guys, days: c.days, rate: SHIPPED_LABOR_RATE };
    });
    rows.push(withHoursSeed(travelSeed()));
    return rows;
  }

  /** THE SHEET'S ORDER: the crew lines first (Polishing, Mock-up, Joint filler, in SHIPPED_CREW's
   *  order), then Travel, then every other line as it came. The crew rows now arrive from the Labor
   *  list after Travel and after any custom line, and a new bid should still open the way the sheet
   *  reads (A37..A44) and the way every bid has. A NEW array; rows are the same objects. */
  function crewFirst(rows) {
    var list = (rows instanceof Array) ? rows : [];
    var crew = [], travel = [], rest = [];
    SHIPPED_CREW.forEach(function (c) {
      list.forEach(function (r) { if (r && String(r.id) === c.id) crew.push(r); });
    });
    list.forEach(function (r) {
      if (r && String(r.id) === "travel") travel.push(r);
      else if (!(r && isCrewId(r.id))) rest.push(r);
    });
    return crew.concat(travel, rest);
  }

  /** A SAVED ROW'S BLANK RATE STAYS ZERO. The blank-rate fallback (laborRateOf) is for the box a
   *  person clears on screen; a saved draft that already holds a blank rate beside a stamp priced it
   *  at $0, so loading pins it to 0 and the bid's total does not move. A NEW array. */
  function pinSavedBlankRates(rows) {
    if (!(rows instanceof Array)) return rows;
    return rows.map(function (r) {
      if (!r || typeof r !== "object" || !isBlank(r.rate)) return r;
      if (r.rate_default === undefined && !r.calc_default) return r;
      var copy = copyInto({}, r);
      copy.rate = 0;
      return copy;
    });
  }

  /** `rows` without the cards nobody filled in: no name, no guys and no days, and not Travel.
   *  Such a row prices $0 (laborCost multiplies guys by days), so dropping it moves no total; it is
   *  what "+ Add a labor line" leaves behind when it is never used. A library default always has a
   *  name, so it never matches. A NEW array; the rows are the same objects. */
  function dropEmptyLaborRows(rows) {
    if (!(rows instanceof Array)) return rows;
    return rows.filter(function (r) {
      if (!r || typeof r !== "object") return true;
      if (r.id === "travel" || r.unit === "hours") return true;
      return !(isBlank(r.label) && isBlank(r.guys) && isBlank(r.days));
    });
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
      // THE SHIPPED FOUR, still. This is what every reader that has no library to ask sees (the
      // golden, a model that states no rows, the v1 migration), and what the polish-chain golden pins
      // unchanged. A NEW bid on the estimate page does NOT keep the three crew rows from here: init
      // keeps only Travel and takes Polishing / Mock-up / Joint filler from the Labor list
      // (Items & Assemblies -> Labor) like any other default, with SHIPPED_CREW as the fallback
      // when the library cannot answer. legacyLabor() builds these rows FROM SHIPPED_CREW, so there
      // is one list.
      labor: legacyLabor(),
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
      //
      // READ FROM THE TABLE (js/work-types.js modelDefaults), which is now the one place a condition's
      // shipped answer is written: the eight keys this model carries, local and taxable on, the rest
      // off. The live intake's own `def` for the same questions used to be kept in step with this
      // literal by hand; test_work_types.py holds the two equal now.
      conditions: types.modelDefaults(),
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

  /** True when a field holds a usable number. 0 counts: a labor row at 0 days is a row the
   *  estimator has deliberately switched off, not a half-filled one. */
  function filledIn(v) {
    if (isBlank(v) || typeof v === "boolean") return false;
    if (typeof v === "number") return isFinite(v);
    return /^-?\d*\.?\d+$/.test(String(v).replace(/[$,\s]/g, ""));
  }

  /** THE TOP-LEVEL KEYS migrateModel's v2 branch READS AND NORMALISES ITSELF, and so the only keys it
   *  may ever rewrite or drop. Every OTHER own key of a saved v2 model belongs to somebody else and
   *  is carried through exactly as it was saved (carryUnknownKeys below).
   *
   *  Until Phase 4 of the v2 estimating program this branch rebuilt the model from a fixed list of
   *  keys, so any key it did not name was erased by the NEXT SAVE: a field a later phase writes (the
   *  other sheets' `tabs`, a rates snapshot, a profile stamp) would have come back as nothing the
   *  first time an estimator touched an unrelated switch. Pinned by test_v2_model_safety.py two
   *  ways: round-trip laws over every saved-bid fixture, and this list against what a model that
   *  states all of these comes back with. A key added to the OUTPUT without being added HERE would
   *  be carried raw over its own normalisation, which is the one mistake this list exists to stop. */
  var MODEL_KEYS = Object.freeze(["version", "takeoff", "labor", "conditions", "contingency", "fees",
    "totals", "no_travel_labor", "conditions_shown", "cond_cov", "travel", "prevailing", "adjust", "distance", "fees_default"]);

  /** `out` with every own key of `saved` that is not in MODEL_KEYS copied on, unchanged.
   *
   *  copyInto, not a hand-written `out[key] = ...`: a saved key is user data (a draft is whatever
   *  was in localStorage or the drafts table), and copyInto is this file's one idiom that refuses
   *  `__proto__`, `constructor` and `prototype`. Values are carried BY REFERENCE and never looked
   *  into, `tabs` included: this function does not know what is inside them and must not pretend
   *  to. Nothing already on `out` is overwritten, so a known key keeps exactly the normalisation
   *  the branch above gave it, and a known key that normalisation DROPPED (a distance that is not a
   *  distance) stays dropped. */
  function carryUnknownKeys(out, saved) {
    var rest = Object.entries(saved).filter(function (e) {
      return MODEL_KEYS.indexOf(e[0]) < 0 && !Object.prototype.hasOwnProperty.call(out, e[0]);
    });
    return copyInto(out, Object.fromEntries(rest));
  }

  /** Bring any saved model up to v2. Never throws: a draft is whatever was in localStorage or
   *  the drafts table, including something a half-shipped build wrote, and an estimator opening
   *  an old job should get a working screen rather than a blank one. */
  function migrateModel(model) {
    if (!model || typeof model !== "object") return freshModel();
    var fresh = freshModel();

    if (model.version === 2) {
      // THE CARDS NOBODY FILLED IN ARE NOT OPENED (Hanz, 2026-10-09: no empty cards). Such a row
      // prices $0, so no total moves. Travel is never one of them.
      var laborIn = model.labor;
      if (laborIn instanceof Array && laborIn.length) {
        laborIn = pinSavedBlankRates(dropEmptyLaborRows(laborIn));
        if (!laborIn.length) laborIn = [withHoursSeed(travelSeed())];
      }
      var out = {
        version: 2,
        takeoff: model.takeoff, labor: laborIn,
        conditions: {}, contingency: model.contingency, fees: model.fees,
        totals: (model.totals && typeof model.totals === "object") ? model.totals : {}
      };
      if (!(out.takeoff instanceof Array) || !out.takeoff.length) out.takeoff = fresh.takeoff;
      if (!(out.labor instanceof Array) || !out.labor.length) {
        out.labor = legacyLabor();
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
        for (var li = 0; li < laborIn.length; li++) {
          if (laborIn[li] && laborIn[li].id === "travel") { hasTravel = true; break; }
        }
        if (model.no_travel_labor === true) {
          // A NEW bid the library said not to give Travel (seedLibraryLabor): its absence is the
          // answer, not a stale draft. Carried through so the next load does not append it back.
          out.no_travel_labor = true;
        } else if (!hasTravel) {
          out.labor = laborIn.concat([travelSeed()]);
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
          out.labor = laborIn.map(function (r) {
            if (!r || r.id !== "travel") return r;
            // RELABEL, "Travel" -> "Travel Labor" (2026-10-05). Only a label that is EXACTLY the
            // old word: a name somebody typed over it is theirs. A copy, never an edit in place.
            if (r.label === "Travel") {
              var relabeled = copyInto({}, r);
              relabeled.label = TRAVEL_LABEL;
              r = relabeled;
            }
            var current = r.unit === "hours" &&
                          Object.prototype.hasOwnProperty.call(r, "guys_auto") &&
                          !isBlank(r.rate);
            if (current) return r;
            var next = copyInto({}, r);
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
      // THE PREVAILING WAGE CALCULATOR's trade, rate and fringes (Labor step). Absent on every bid that never
      // used the card, and then absent stays absent: nothing is added, so such a bid prices and saves as before.
      var pwBlock = normalizePrevailing(model.prevailing);
      if (pwBlock) out.prevailing = pwBlock;
      // THE ESTIMATOR'S OVERRIDES on the Polish section's Review step. Absent on every bid that never typed one, and
      // absent stays absent.
      var adjBlock = normalizeAdjust(model.adjust);
      if (adjBlock) out.adjust = adjBlock;
      if (isBlank(out.contingency)) out.contingency = 0;
      // Every v2 draft saved before the Fees line became typeable has no `fees` at all, and a
      // missing one must read as the zero the sheet ships.
      if (isBlank(out.fees)) out.fees = fresh.fees;
      // The default this bid was STARTED from, kept so the warning survives a reload. Absent on
      // every bid saved before it existed and on every bid whose default was nothing.
      if (!isBlank(model.fees_default) && isFinite(Number(model.fees_default)) &&
          Number(model.fees_default) > 0) out.fees_default = Number(model.fees_default);
      // EVERYTHING ELSE THE SAVED MODEL HOLDS comes back as it went in (see MODEL_KEYS). The v1
      // branch below does NOT do this, on purpose: it is a one-way upgrade that consumes `areas` and
      // `labour` and drops six legacy keys so the same material is never priced twice.
      return carryUnknownKeys(out, model);
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
      var legacy = legacyLabor();
      for (var j = 0; j < legacy.length; j++) {
        var seed = legacy[j];
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

  function isObject(v) { return !!v && typeof v === "object" && !(v instanceof Array); }

  // (patchModel also reads `boxes`: { boxName: figure } for the intake's quantity boxes the estimator typed in, any
  //  of the nine of work-types.js FIELDS, each written to the takeoff of the section that owns it (applyBoxes). The
  //  `sf_areas` described below is the Polish pair of them, polish_sf and polish_2_sf.)
  /** The saved model with ONE writer's fields laid over it, and everything else left as it was.
   *
   *  THE INTAKE PAGE'S SAVE. It used to migrate what was saved and then overlay its own answers by
   *  hand, in the page. It is a function of the model now so that "what the intake may state" is
   *  decided in ONE place, next to the model, and can be tested without a page: a second writer that
   *  states a little more (Phase 9's intake, a section-aware model) widens this function and nothing
   *  else.
   *
   *  `existing` is whatever the draft holds under `polish_estimate`: nothing, a v1 model, a partial
   *  blob, a v2 model. It is read through migrateModel, so what comes back is ALWAYS a well-formed v2
   *  with its version stamped. That matters because the intake MINTS the first model on a brand-new
   *  project, and backend/drafts.py reads `polish_estimate.version` to decide that a project resumes
   *  on the beta intake and not on the spreadsheet one. Every key the model holds that this function
   *  does not name (`tabs`, a rates snapshot, a profile stamp, anything a later phase adds) comes
   *  back exactly as saved, because migrateModel carries it and nothing here touches it.
   *
   *  `patch` states ONLY what the intake owns, and only these two are read from it:
   *
   *    conditions        merged key by key over the saved answers, never replacing the object: an
   *                      answer the patch does not mention stays as it was saved
   *    conditions_shown  which condition cards this bid shows, replaced when the patch states one
   *
   *  and ONE more, read only as positive numbers:
   *
   *    sf_areas          [first, second]: the floor sizes typed into intake's System 1 and System 2
   *                      boxes, each null when that box was not typed in. Written to the first and
   *                      second measured SF rows of the takeoff (setAreaSf; the second is ADDED when
   *                      the takeoff has only one) and to nothing else, so the boxes and the takeoff
   *                      cannot disagree. Ignored while nothing is measured: then the boxes seed.
   *
   *  Anything else in `patch` is ignored. The takeoff, the labor rows and `tabs` belong to the
   *  estimate page, and a patch that could overwrite them is how recording one toggle deletes a
   *  finished takeoff. sf_areas is the one narrow, named way in: it changes one number on a row, or
   *  adds the second area.
   *
   *  A PATCH NEVER STATES LABOR ON A BID THAT NEVER STATED IT. migrateModel fills a missing `labor`
   *  in from freshModel(), and the intake used to persist those four rows: that made the library's
   *  default labor lines unreachable, because laborUnstated(saved) is the gate the estimate page
   *  seeds them behind and a model minted here had already stated labor. So `labor` is taken back off
   *  when `existing` stated none. It is asked of `existing` itself and not of the migrated copy,
   *  for the reason laborUnstated gives.
   *
   *  Pure: neither argument is changed. */
  function patchModel(existing, patch) {
    var model = migrateModel(existing);
    var p = isObject(patch) ? patch : {};
    if (isObject(p.conditions)) model.conditions = Object.assign({}, model.conditions, p.conditions);
    if (isObject(p.conditions_shown)) model.conditions_shown = copyInto({}, p.conditions_shown);
    // THE BOXES THE ESTIMATOR TYPED IN, to the takeoff of the section that owns each (applyBoxes works on COPIES of
    // the rows: migrateModel hands back the SAVED arrays, and this function is pure). `sf_areas` is the Polish
    // pair as it was first written, kept as the same two boxes.
    var boxes = isObject(p.boxes) ? p.boxes : {};
    if (p.sf_areas instanceof Array) {
      boxes = Object.assign({}, boxes, Object.fromEntries([["polish_sf", p.sf_areas[0]], ["polish_2_sf", p.sf_areas[1]]]));
    }
    model = applyBoxes(model, boxes);
    if (laborUnstated(existing)) delete model.labor;
    return model;
  }

  /** EVERY DRAFT KEY THE ESTIMATE PAGE SAVES, as one patch, for the page to lay over the draft:
   *  `TW.setState(Object.assign({}, draft, buildSavePatch(model, draft, ctx)))`.
   *
   *  ONE COMPOSITION, USED BY BOTH SAVES. The 600 ms autosave and the `pagehide` flush used to build
   *  this blob in two places, and the two had drifted: a tab closed inside the debounce window did
   *  not refresh the condition cells, and when the only SF row was switched off it saved a polish SF
   *  of 0 where the autosave kept the measured floor. A key can only be added or fixed here now.
   *
   *  `model` is the page's own (already migrated) model. `state` is the draft as it stands, and only
   *  its `cell_values` (the base the condition cells are MERGED over) and its `tax_flags_per_sheet`
   *  mark (whether the tax answers are written per sheet) are read. `ctx` carries what
   *  only the page can compute: `bid`, the markupChain result for `model` (required, and this throws
   *  without it, because a save with no price is a save of zero), and `library`, what the page priced
   *  Dye and Joint Filler with (see conditionCellWrites; left out, it writes nothing for those two).
   *
   *  What it returns, and why each key is there:
   *
   *    polish_estimate  the model, with `totals` stamped from `ctx.bid`: a snapshot for reading later,
   *                     which the page never prices FROM. Every other key rides along as the model
   *                     holds it, the ones migrateModel does not know included.
   *    cell_values      THE CONDITION CELLS, merged over the draft's own. This page does not write
   *                     the takeoff or the pricing cells, because it no longer prices through the
   *                     workbook; it has to write the conditions, because they are not a rendering of
   *                     the bid, they are the contract it shares with the intake page, which reads
   *                     them back on load and lets the CELL win over the model. That rule is safe only
   *                     while every writer writes both places. The Dye and Joint Filler rate and
   *                     quantity cells ride the same write, so the downloaded workbook prices those
   *                     two lines off the same library rows the bid does.
   *    polish_sf        the area the bid PRICES (an OFF row is out of it). When nothing is on, the
   *                     MEASURED floor, not 0: a 0 here unlocked intake's SF boxes and sent the
   *                     proposal an empty SF token because somebody flipped the only row's slider.
   *    polish_2_sf      blank. polish_sf IS the takeoff total, so intake's System 2 box has nothing
   *                     left to say. Left stale it reseeded a deleted row.
   *    computed_bid     REPLACED, not merged: on a sandbox copy the source project's figures arrived
   *                     with the blob, and merging would leave a real project's total sitting under a
   *                     beta price. `full_bid` is what the rest of the app reads (_bid_total in
   *                     backend/drafts.py for the projects card; proposal-review for the lump sum and
   *                     the two tax lines it itemizes).
   *
   *  Pure: nothing it is handed is changed. The model is COPIED to take the `totals` stamp. */
  function buildSavePatch(model, state, ctx) {
    if (!isObject(model)) throw new Error("buildSavePatch needs the model it is saving");
    if (!isObject(ctx)) {
      throw new Error("buildSavePatch needs ctx.bid, the markupChain result for this model: a save " +
                      "with no price is a save of zero");
    }
    var cells = isObject(state) ? state.cell_values : undefined;
    // EVERY KEY THE PROPOSAL SIDE READS, AND THE MODEL WITH ITS TOTALS STAMPED, IS composePricingSnapshot's.
    // For a bid with one section (all of them today) that is exactly what this function wrote by hand until
    // Phase 10: polish_estimate, polish_sf, polish_2_sf, computed_bid, in that order.
    // The draft's own tab_opts ride along, so an option's proposal settings are kept (see composePricingSnapshot).
    var derived = composePricingSnapshot(model, isObject(state) && isObject(state.tab_opts)
      ? Object.assign({}, ctx, { tabOpts: state.tab_opts }) : ctx);
    var rest = Object.assign({}, derived);
    delete rest.polish_estimate;
    return Object.assign({
      polish_estimate: derived.polish_estimate,
      // `split` is the draft's own mark (work-types.js isSplit), so the one save both pages share is also
      // the one that keeps an option's tax answer out of the base's way on a split draft.
      cell_values: conditionCellWrites(model.conditions, cells, ctx.library, types.isSplit(state)),
    }, rest);
  }

  // ══ SECTIONS (Phase 10): a bid priced on several workbook tabs ═══════════════════════════════════════════
  //
  // WHAT A SECTION IS. One workbook tab's worth of bid: its takeoff, labor, contingency and fees, the profile
  // that prices it, the rates it kept, and the totals last stamped. The model has always held exactly one, the
  // Polish section, as its ROOT keys (takeoff, labor, contingency, fees, totals). Every other section lives
  // under `tabs`, keyed by the workbook tab id ("Epoxy", 'Gyp (USG 1-8")'), as
  //
  //   { layout, kind: "base" | "option" | "off", profile: "<id>@<rev>", takeoff, labor, contingency, fees,
  //     rates: <the snapshot, see snapshotRates>, totals }
  //
  // JOB-LEVEL KEYS STAY AT THE ROOT and are shared by every section: conditions, conditions_shown, cond_cov,
  // travel, distance, fees_default, prevailing (and no_travel_labor). The root keys keep today's meaning, so the model is
  // still `polish_estimate` at `version: 2` and no saved bid is rewritten.
  //
  // A SECTION'S KEY IS ITS WORKBOOK SHEET, OR A Copy<N> ID (Sheets phase 1). A copy of a sheet, and any second section of
  // a type, is filed under "Copy1", "Copy2" and so on and says its workbook sheet in `sheet`, what it is called in `label`
  // and what it was copied from in `source`. The key never changes and a label is never a key. Code that means "the
  // workbook sheet" (the engine's tab, a Gyp preset, a truckload) reads the entry's `sheet`; code that means "this section"
  // (a price, a proposal setting, a click) reads its `tab`. The root's own `kind` is read in full (base, option, off; a
  // missing key is base), so the Polish sheet can be an option when something else is the base.
  //
  // `sectionsOf` is the ONE place that knows root from tabs; everything else asks it and gets the section BY
  // REFERENCE. THE ROOT SECTION is priced by `polish-legacy@1`'s built-ins, as it has been since the model was
  // written, unless its own `profile` key is exactly `polish-rev2@1` (Phase 17): a NEW bid is stamped so when it is
  // seeded (seedNewSections), and a saved bid has no such key and never will, so its totals cannot move (rootProfile).
  // No snapshot is written for the root either way. A `rates` at the root is reserved and is not read. Its `kind` is:
  // "off" is a root Polish section that is not part of the bid (what an Epoxy-only job holds), "option" is a Polish sheet
  // that is not the base (since Sheets phase 1; it is then charged its own travel), and base is a missing key.
  //
  // PRICING NEVER READS THE LIVE MARKUPS RULES. A section prices with its own profile (resolved by the stamp it
  // was saved with) and the rates it kept when it was first used. A section with no snapshot prices at the
  // profile's built-ins. A Markups rule filed afterwards moves no saved bid; it applies to a section activated
  // after it was filed (activateSection), and only as a snapshot.
  /** The workbook tab id of the root section. */
  var ROOT_TAB = "Polish";
  var SECTION_KINDS = ["base", "option", "off"];
  var PROFILE_STAMP = /^([a-z0-9-]+)@(\d+)$/;
  var has = Object.prototype.hasOwnProperty;
  /** A SECTION'S KEY IS EITHER ITS WORKBOOK SHEET OR A Copy<N> ID (Sheets phase 1). A copy of a sheet, and any second section
   *  of a type, is filed under "Copy1", "Copy2" and so on, and says which workbook sheet it is in its own `sheet` key, so a
   *  key is never a label somebody typed and a rename moves nothing. A key that is a sheet's own name is the old,
   *  unchanged form every saved bid uses. At most MAX_COPIES sections hold a Copy id, the live estimate's own limit. */
  var COPY_ID = /^Copy[1-9]\d*$/;
  var MAX_COPIES = 12;

  /** Every section of the model, root first, then `tabs` in the order they were added, as
   *  { tab, root, section, layout, kind, profile, role }. `section` is the live object (the root section IS
   *  the model); nothing here copies. THROWS on a section that is not well formed, because a section priced as
   *  something it is not is a wrong bid: a tab that is not a priced workbook tab, a missing or wrong layout, a
   *  kind or profile stamp that is not one, a profile that belongs to another layout. There is no default
   *  layout, and "polish" is never assumed. */
  function sectionsOf(model) {
    if (!isObject(model)) throw new Error("sectionsOf needs the model");
    // The root's kind is read in full since the Sheets work (Sheets phase 1): "off" (an Epoxy job's Polish, not part of
    // the bid), "option" (a Polish sheet that is no longer the base, priced apart like any option) and base, which is what a
    // missing key means, so a bid saved before any of this reads as it always did. Anything else is base.
    var rootKind = model.kind === "off" ? "off" : (model.kind === "option" ? "option" : "base");
    var out = [{ tab: ROOT_TAB, sheet: ROOT_TAB, label: rootLabel(model), source: null, root: true, section: model,
                 layout: "polish", kind: rootKind, profile: rootProfile(model).stamp, role: "polish" }];
    var tabs = model.tabs;
    if (tabs === undefined || tabs === null) return out;
    if (!isObject(tabs)) throw new Error("model.tabs must be an object of sections keyed by workbook tab id");
    Object.keys(tabs).forEach(function (id) {
      var s = tabs[id];
      var where = "section " + JSON.stringify(id);
      if (id === ROOT_TAB) throw new Error(where + " is the root section's own tab: it lives at the root of the model, not under tabs");
      // A key is either a workbook sheet ("Epoxy", "Seal (+Jnts)") or a Copy<N> id, which names its sheet in `sheet`.
      var copy = COPY_ID.test(id);
      if (copy && !isObject(s)) throw new Error(where + " is not a section");
      var sheet = copy ? (typeof s.sheet === "string" ? s.sheet : "") : id;
      var tabKey = types.tabOfSheet(sheet);
      if (!tabKey) throw new Error(where + (copy ? " does not name a priced workbook sheet" : " is not a priced workbook tab"));
      if (!isObject(s)) throw new Error(where + " is not a section");
      if (!copy && s.sheet !== undefined && s.sheet !== id) throw new Error(where + " says it is the sheet " + JSON.stringify(s.sheet));
      if (typeof s.layout !== "string" || s.layout === "") throw new Error(where + " does not say its layout (there is no default)");
      var rec = types.tab(tabKey);
      if (s.layout !== rec.markupLayout) throw new Error(where + " says layout " + JSON.stringify(s.layout) + ", but that tab is " + rec.markupLayout);
      if (SECTION_KINDS.indexOf(s.kind) < 0) throw new Error(where + " has kind " + JSON.stringify(s.kind) + " (base, option or off)");
      var stamp = typeof s.profile === "string" ? PROFILE_STAMP.exec(s.profile) : null;
      if (!stamp) throw new Error(where + " has no profile stamp (like epoxy@1)");
      var known = null;
      try { known = engine.resolveProfile(stamp[1]); } catch (err) { known = null; }   // an unknown id is priceSection's to say
      if (known && known.layout !== s.layout) {
        throw new Error(where + " is priced by profile " + stamp[1] + ", which belongs to another layout");
      }
      out.push({ tab: id, sheet: sheet, label: typeof s.label === "string" && s.label.trim() ? s.label : id,
                 source: typeof s.source === "string" ? s.source : null,
                 root: false, section: s, layout: s.layout, kind: s.kind, profile: s.profile, role: rec.role });
    });
    return out;
  }

  /** What the root section is called on screen: its own `label` when it was renamed, else its workbook sheet. */
  function rootLabel(model) {
    return typeof model.label === "string" && model.label.trim() ? model.label : ROOT_TAB;
  }

  /** The sections that are part of the bid: every kind but "off". */
  function activeSections(model) {
    return sectionsOf(model).filter(function (e) { return e.kind !== "off"; });
  }

  /** One section's entry, by workbook tab id. THROWS when there is none. */
  function sectionOf(model, tabId) {
    var list = sectionsOf(model);
    for (var i = 0; i < list.length; i++) if (list[i].tab === tabId) return list[i];
    throw new Error("the model has no section for " + JSON.stringify(String(tabId)));
  }

  /** The five keys that are a SECTION's own: what a panel edits when a section other than the root is on show. */
  var SECTION_KEYS = ["takeoff", "labor", "contingency", "fees", "totals", "adjust"];

  /** THE MODEL AS THE PANELS SEE IT while one section is on show (Phase 12). The estimate page's Material,
   *  Labor and Review panels have always edited `M.takeoff`, `M.labor`, `M.contingency` and `M.fees`, which is
   *  right for the root (Polish) section because those ARE the root's keys. For any other section the same four
   *  keys live in `model.tabs[tab]`, and a second copy of every panel for them is what this avoids: the view
   *  answers those keys from the section and every other key (the conditions, the travel, the distance, the
   *  fees default) from the model, and a write goes to the same place a read came from. It holds NOTHING of its
   *  own, so the model underneath is always the one that is saved. The root's view is the model itself.
   *  THROWS for a tab the model has no section for. */
  function sectionView(model, tabId) {
    var e = sectionOf(model, tabId);
    if (e.root) return model;
    var sec = e.section;
    // Reflect, so a write is never `object[name] = value` with a name that came from outside (CodeQL's
    // remote-property-injection rule, and the repo's rule 5): the keys are the five of SECTION_KEYS or the model's own.
    var ownerOf = function (target, key) { return SECTION_KEYS.indexOf(key) >= 0 ? sec : target; };
    return new Proxy(model, {
      get: function (target, key) { return Reflect.get(ownerOf(target, key), key); },
      set: function (target, key, value) { return Reflect.set(ownerOf(target, key), key, value); }
    });
  }

  /** WHICH SECTIONS A JOB TYPE NEEDS (Phase 12). A job type's base tab is a section of the bid, and the model
   *  holds the Polish section as its root, so an Epoxy job is: the root marked "off" (it is not part of the bid)
   *  and an Epoxy section as the base. Polish returns the model it was given, unchanged (no saved bid moves).
   *  Idempotent: a section the model already has is left as it is, and the root's kind is only ever written
   *  here, never read back to decide anything else. Returns a NEW model when it changes anything, else the one
   *  handed in. A job type that is not ready in the vocabulary THROWS, because pricing it would be a guess.
   *
   *  BASE-AWARE (Sheets phase 1). A bid whose base already IS this job type (baseOf) is left exactly as it is, which
   *  is what lets the estimator make a copy or a second sheet the base without the intake's job type undoing it.
   *  When the job type really moved, each tab it is priced on gets its base from the sections the bid HAS, found by
   *  their workbook sheet and not by their key: one that is already a base, else the sheet's own section, else a
   *  copy. A section that was an option or off is made the base (it keeps its rows); only a tab with no section at
   *  all is added. Bases the new job type does not use are marked off, rows kept, as since Phase 12, and an option
   *  stays an option. A bid whose sections cannot be read is returned as it is. */
  function sectionsForJob(model, jobType, ctx) {
    if (!isObject(model)) throw new Error("sectionsForJob needs the model");
    var job = types.jobType(jobType);
    if (!job) throw new Error(JSON.stringify(String(jobType)) + " is not a job type");
    if (job.ready !== true) throw new Error(job.label + " is not ready in Estimating Tool v2 yet");
    var held = readableSections(model);
    if (held === null) return model;
    if (baseTypeOf(held) === jobType) return model;
    var out = model;
    var baseTabs = types.tabsFor(jobType).map(function (key) { return types.tab(key); });
    var picked = [];
    baseTabs.forEach(function (rec) {
      // A tab that has several sheets (Gyp's five presets) is ONE section, filed under the sheet the estimator
      // chose, so "does the bid have it" asks every sheet of the tab and not the first alone.
      var mine = held.filter(function (e) { return types.tabOfSheet(e.sheet) === rec.key; });
      if (!mine.length) {
        out = activateSection(out, rec.sheets[0], "base", ctx);
        picked.push(rec.sheets[0]);
        return;
      }
      // A saved bid whose job type moved back to this tab: the section was marked off when it left, and its
      // rows are kept, so bringing it back is only turning it on.
      picked.push(preferredSection(mine).tab);
    });
    var rootLifted = model.kind === "off" && picked.indexOf(ROOT_TAB) >= 0;
    picked.forEach(function (id) {
      // The root is part of this job type again (a saved Epoxy bid switched to Combo or Polish): only its "off" (or
      // "option") is lifted. The key is dropped rather than written as "base", so a bid that never left Polish saves as it did.
      if (id === ROOT_TAB) {
        if (out.kind === "off" || out.kind === "option") { out = Object.assign({}, out); delete out.kind; }
      } else if (out.tabs[id].kind !== "base") out = withSectionKind(out, id, "base");
    });
    // A saved bid whose job type moved to one that does not use a base section it has: that section is marked
    // off, never deleted, so the estimator's rows survive a switch back.
    held.forEach(function (e) {
      if (e.kind !== "base" || picked.indexOf(e.tab) >= 0 || !leavesWithJob(e)) return;
      out = e.root ? Object.assign({}, out, { kind: "off" }) : withSectionKind(out, e.tab, "off");
    });
    // A Polish section that has never held a takeoff is new to the bid, so it is priced by Polish rev 2 like any other new
    // one (Phase 17). A root that was priced before and is coming back keeps the profile it had, or none.
    if (rootLifted && out.profile === undefined && !takeoffStated(out.takeoff)) out = Object.assign({}, out, { profile: REV3.stamp });
    return out;
  }

  /** The model's sections, or null when they cannot be read (sectionsOf throws). The job-type functions below never throw
   *  for a bid whose `tabs` are malformed: the page opens such a bid as it is and says why. */
  function readableSections(model) {
    try { return sectionsOf(model); } catch (err) { return null; }
  }

  /** Is this entry a BASE of the bid: a section that is part of it as a base, and on a tab that can be one (Seal and
   *  Leveling never are, even if a saved model says so). */
  function isBaseEntry(e) {
    return e.kind === "base" && !types.tab(types.tabOfSheet(e.sheet)).optionOnly;
  }

  /** The job type a list of section entries is a bid for: the one base's own work type, "combo" for exactly one Epoxy and one
   *  Polish base, and null for anything else (no base, two bases that are not that pair). */
  function baseTypeOf(entries) {
    var bases = entries.filter(isBaseEntry);
    if (bases.length === 1) return types.isJobType(bases[0].role) ? bases[0].role : null;
    if (bases.length === 2) {
      var roles = bases.map(function (e) { return e.role; }).sort();
      if (roles[0] === "epoxy" && roles[1] === "polish") return "combo";
    }
    return null;
  }

  /** WHICH SECTIONS ARE THE BASE BID AND WHAT JOB TYPE THAT MAKES IT (Sheets phase 1): `{ ids, jobType }`. `ids` are the
   *  section ids of the bases in the model's order (one, or the Epoxy and Polish pair, or none), and `jobType` is
   *  the intake's job type they amount to: polish, epoxy or gyp for one base, "combo" for the pair, null when there is
   *  no base or the bases are not a job type. THROWS for sections that cannot be read, like sectionsOf. */
  function baseOf(model) {
    var entries = sectionsOf(model);
    return { ids: entries.filter(isBaseEntry).map(function (e) { return e.tab; }), jobType: baseTypeOf(entries) };
  }

  /** Of several sections of one tab, the one a job type takes as its base: one that already is a base, else the
   *  sheet's own section (the root, or the one filed under its sheet's name), else the first copy. */
  function preferredSection(entries) {
    var base = entries.filter(function (e) { return e.kind === "base"; });
    if (base.length) return base[0];
    var named = entries.filter(function (e) { return !COPY_ID.test(e.tab); });
    return named.length ? named[0] : entries[0];
  }

  /** Does a base section stop being one when the job type moves away from its tab? Only on a tab Estimating Tool v2
   *  prices (a job type that is ready) and that can be a base: Leveling, until its phase, is never touched. */
  function leavesWithJob(e) {
    var tabKey = types.tabOfSheet(e.sheet);
    return !types.tab(tabKey).optionOnly && tabIsReady(tabKey);
  }

  /** Is this workbook tab part of a job type that Estimating Tool v2 prices yet? */
  function tabIsReady(tabKey) {
    return types.jobTypeKeys().some(function (k) {
      return types.jobType(k).ready === true && types.tabsFor(k).indexOf(tabKey) >= 0;
    });
  }

  /** The sheet of tab record `rec` that the model already holds a section under, or null. A tab has several sheets
   *  only for Gyp (its five presets); every other tab has the one, so for them this is the plain "is there a
   *  section called that". The sheets are asked in the tab's own order. */
  function sheetHeld(model, rec) {
    if (!isObject(model) || !isObject(model.tabs)) return null;
    for (var i = 0; i < rec.sheets.length; i++) if (has.call(model.tabs, rec.sheets[i])) return rec.sheets[i];
    return null;
  }

  /** The base sections a model has that a job type does not use, and that Estimating Tool v2 can price (a job
   *  type that is ready): the ones sectionsForJob marks off. An option stays an option, and a section v2 cannot
   *  price (Leveling, until its phase) is never touched. Reads only, and never throws. */
  function sectionsLeaving(model, jobType) {
    if (!isObject(model) || !isObject(model.tabs) || !types.jobType(jobType)) return [];
    var held = readableSections(model);
    if (held === null) return [];
    var mine = types.tabsFor(jobType);
    return held.filter(function (e) {
      return !e.root && e.kind === "base" && mine.indexOf(types.tabOfSheet(e.sheet)) < 0 && tabIsReady(types.tabOfSheet(e.sheet));
    }).map(function (e) { return e.tab; });
  }

  /** What a workbook tab is called on screen: the name the proposal gives its system (a Gyp tab's "N12 1/8" + 3/4" Gyp"),
   *  else the tab id itself. Never throws. */
  function sheetLabel(tab) {
    try { return engine.forTab(tab).label || String(tab); } catch (err) { return String(tab); }
  }

  /** MOVE A SECTION TO ANOTHER SHEET OF ITS OWN TAB: the Gyp preset. A Gyp bid is priced on one of five Gyp sheets
   *  and its section is filed under that sheet's workbook tab id, so changing the preset renames the section's key
   *  and keeps everything inside it (rows, settings, rates). The profile is restamped from the new sheet, which is
   *  the same profile for all five Gyp tabs, so no price changes except the ones the preset itself makes. A NEW
   *  model; the order of the sections is kept. THROWS for a section the model does not have, a sheet of another
   *  tab, and a sheet the model already holds a section under. Moving to the sheet it is already on returns the
   *  model it was given. */
  function moveSectionSheet(model, fromTab, toTab) {
    var e = sectionOf(model, fromTab);
    if (e.root) throw new Error("the " + ROOT_TAB + " section is the root of the model and has no other sheet");
    // A copy keeps its Copy<N> key and names its sheet in `sheet`, so a preset change on one rewrites that and leaves the key.
    if (e.sheet === toTab) return model;
    var tabKey = types.tabOfSheet(toTab);
    if (!tabKey || tabKey !== types.tabOfSheet(e.sheet)) {
      throw new Error(JSON.stringify(String(toTab)) + " is not another sheet of the " + e.layout + " tab");
    }
    var profile = engine.forTab(toTab).profile;
    if (COPY_ID.test(fromTab)) return withSectionPatch(model, fromTab, { sheet: toTab, profile: profile.stamp });
    if (has.call(model.tabs, toTab)) throw new Error(JSON.stringify(toTab) + " is already a section of this bid");
    var out = jsonCopy(model);
    var moved = Object.assign({}, out.tabs[fromTab], { profile: profile.stamp });
    // A section with no name of its own is called by its key, and the key is changing: it must not take a name another section has.
    if (!(typeof moved.label === "string" && moved.label.trim())) moved = Object.assign(moved, labelIfTaken(out, toTab));
    out.tabs = copyInto({}, Object.fromEntries(Object.keys(out.tabs).map(function (id) {
      return id === fromTab ? [toTab, moved] : [id, out.tabs[id]];
    })));
    return out;
  }

  /** A NEW model with one existing section's kind changed. The section's rows are the same objects' contents. */
  function withSectionKind(model, tabId, kind) {
    var out = jsonCopy(model);
    // The root's kind is the model's own `kind` key, and base is a missing key, so a bid that never left Polish saves as it did.
    if (tabId === ROOT_TAB) {
      if (kind === "base") delete out.kind; else out.kind = kind;
      return out;
    }
    out.tabs = copyInto(copyInto({}, out.tabs), Object.fromEntries([[tabId, Object.assign({}, model.tabs[tabId], { kind: kind })]]));
    return out;
  }

  /** The tabs sectionsForJob would ADD to this model for a job type: the base tabs it has no section for yet.
   *  The estimate page asks it before it loads the library, because a section added to a SAVED bid is a new
   *  section and is given the library's crew like one. [] for a job type that is not ready. */
  function sectionsToAdd(model, jobType) {
    var job = types.jobType(jobType);
    if (!isObject(model) || !job || job.ready !== true) return [];
    var held = readableSections(model);
    if (held === null) return [];
    return types.tabsFor(jobType).map(function (key) { return types.tab(key); }).filter(function (rec) {
      return rec.sheets[0] !== ROOT_TAB && !held.some(function (e) { return types.tabOfSheet(e.sheet) === rec.key; });
    }).map(function (rec) { return rec.sheets[0]; });
  }

  function takeoffStated(rows) {
    return rows instanceof Array && rows.some(function (r) {
      return !!r && (!!r.assembly_id || !!r.item_id || !isBlank(r.measurement));
    });
  }

  /** Has nobody stated anything in this section yet? The gate on seeding it from the library, the per-section
   *  form of laborUnstated (and as strict). ROOT: exactly laborUnstated, the gate the page has always used,
   *  which reads the SAVED blob (see it). A TAB SECTION: no labor rows and nothing in its takeoff, which is what
   *  activateSection hands back; its rates snapshot says nothing either way (activating writes it). A section
   *  that the library gave no default rows stays new until somebody types in it, as the root does when it has
   *  no labor, and only ever receives what is in the library at that moment. */
  /** DOES THIS SECTION BUY EACH MATERIAL ONCE FOR THE WHOLE SECTION? (Hanz, 2026-10-13, "Buy packs for the whole job".)
   *  True only for a section stamped `pool_packs: true`, which is stamped when a section is made or seeded
   *  (activateSection, seedNewSections). A section saved before that carries no stamp and keeps pricing each
   *  takeoff row's packs on its own, so no saved bid moves. The pool itself is library-core's pricePool. */
  function poolsPacks(section) {
    return isObject(section) && section.pool_packs === true;
  }

  function isNewSection(section, isRoot) {
    if (isRoot) return laborUnstated(section);
    if (!isObject(section)) return true;
    return !(section.labor instanceof Array && section.labor.length) && !takeoffStated(section.takeoff);
  }

  /** WHICH SECTION CARRIES THE JOB'S TRAVEL (and the Fees + Textura default): once per job, not once per tab
   *  (plan default for Combo, to be confirmed with Kyle). The first section that is part of the bid as a base,
   *  else the first that is part of it at all, else the root. Returns a workbook tab id. */
  function travelCarrier(model) {
    var list = activeSections(model);
    for (var i = 0; i < list.length; i++) if (list[i].kind === "base") return list[i].tab;
    return list.length ? list[0].tab : ROOT_TAB;
  }

  // ── pricing a section ───────────────────────────────────────────────────────
  function unpriceableSection(stamp, line, reason) {
    return { priceable: false, profile: stamp, line: line, reason: reason, total: null };
  }

  /** One section's bid, through the engine with THAT SECTION'S profile and the rates it kept.
   *
   *  `ctx.material(entry)` is the page's: a takeoff is priced from the library, which the model does not hold.
   *  It answers a number (the raw material sum) or an object of the engine's material inputs
   *  ({ material } or { gyp, extras, sand, soundMat, soundMatRolls }). `ctx.remodel_rate` is the county's, or
   *  nothing for the profile's own default.
   *
   *  The job's travel is charged to the carrier section only (travelCarrier); the other bases carry none. An OPTION
   *  carries its own Lodging and Per Diem for its own crew (optionTravelCosts), as the workbook's tab does. A profile
   *  that is not the one the section was saved with (an unknown id, or a rev that has moved) is not priced: the
   *  answer is unpriceable with the reason, never a silent reprice at the new rules. */
  function priceSection(model, tabId, ctx) {
    if (!isObject(ctx) || typeof ctx.material !== "function") {
      throw new Error("priceSection needs ctx.material(entry): the page prices a takeoff from its library");
    }
    var e = sectionOf(model, tabId);
    // A Polish section under `tabs` (a copy, or a sheet added to the bid) is priced exactly as the root is: polishBid.
    if (e.layout === "polish" && !e.root) return polishBid(model, tabId, ctx);
    var s = e.section;
    var stamp = PROFILE_STAMP.exec(e.profile);
    var profile;
    try { profile = engine.resolveProfile(stamp[1]); } catch (err) {
      return unpriceableSection(e.profile, "profile", "this section was priced with " + e.profile +
        ", which the engine does not have. Its saved figures are kept.");
    }
    if (String(profile.rev) !== stamp[2]) {
      return unpriceableSection(e.profile, "profile", "this section was priced with " + e.profile +
        ", and the engine's " + profile.id + " is now " + profile.stamp + ". Its saved figures are kept.");
    }
    var carrier = travelCarrier(model) === e.tab;
    var input = {
      labor: laborTotal(s.labor, model.conditions, prevailingApplied(model)),
      travel: carrier ? travelCosts(model.travel, s.labor).total : 0,
      contingency: s.contingency, fees: s.fees, conditions: chainConditions(model.conditions, s.adjust),
      sf: takeoffSf(s.takeoff), remodel_rate: ctx.remodel_rate,
      adjust: chainAdjust(s.adjust)
    };
    // An OPTION carries its own Lodging and Per Diem for its own crew (optionTravelCosts), as the workbook's tab does.
    if (!carrier && e.kind === "option") input.travel = optionTravelCosts(model.travel, s.labor).total;
    // The root carries the job's travel counted the sheet's way when a profile asks for it (polish-rev2).
    if (carrier && e.root) input.travel = travelCosts(model.travel, s.labor, travelOpts(model, e.tab)).total;
    // The root's tooling is the sheet's D55 on a profile that charges it. Another section brings its own, in `mat`.
    if (e.root && profile.quirks.toolingInSubTotal) input.tooling = rootTooling(model);
    var mat = ctx.material(e);
    // A material that says why it cannot be worked out (a Gyp area with no thickness) is no price, in its own
    // words, and never a bid priced on the part that could be.
    if (isObject(mat) && typeof mat.unpriceable === "string" && mat.unpriceable) {
      return unpriceableSection(e.profile, "material", mat.unpriceable);
    }
    if (isObject(mat)) copyInto(input, mat); else input.material = num(mat);
    // A gyp-split profile reads the engine's material inputs (gyp, extras, sand, soundMat), never a plain sum:
    // a number would price the material at $0 and still call the section priceable. No price rather than a wrong one.
    if (profile.quirks.shippingRule === "gyp-split" && !isObject(mat)) {
      return unpriceableSection(e.profile, "material", "the " + e.label + " material has to come as gyp, extras, sand " +
        "and sound mat figures. A single material total cannot be priced here.");
    }
    try {
      // A Gyp tab's truckload is the tab's own (H36), unless the page says the sound mat chosen has another: on
      // four of the five tabs the truckload follows the product (js/gyp-takeoff.js).
      if (profile.quirks.shippingRule === "gyp-split" && !(num(input.truckload) > 0)) {
        input.truckload = engine.forTab(e.sheet).truckload;
      }
      // The root keeps no snapshot (see above): it prices at the built-ins.
      return engine.priceChain(profile, input, e.root ? undefined : engine.ratesOf(s.rates));
    } catch (err) {
      if (err && err.name === "BidEngineError") return unpriceableSection(e.profile, "profile", err.message);
      throw err;
    }
  }

  /** THE BID OF A POLISH SECTION, the root's or one under `tabs` (Sheets phase 1): markupChain over the section's own rows, so a
   *  copy of the Polish sheet, or a Polish sheet added to the bid, prices exactly as the root does. The estimate page's
   *  bid() calls it for the root, and priceSection calls it for every other Polish section.
   *
   *  `ctx.material(entry)` is the page's: the raw material of the section's takeoff (a number, or an object holding
   *  `material`), because the library belongs to the page. Dye and Joint Filler are the JOB's conditions and the Polish
   *  tab's lines, so the page adds them to the material of every Polish section. `ctx.remodel_rate` is the county's.
   *
   *  THE PROFILE is the one the section was made with: the root's by rootProfile (a saved bid has no key and prices
   *  as polish-legacy), a section under `tabs` by its own stamp, polish-legacy@1 or polish-rev2@1, which is what
   *  a copy keeps from its source. Any other stamp is unpriceable with the reason, never repriced. No rates snapshot
   *  is read, as for the root: a Polish section prices at the profile's built-ins.
   *
   *  THE JOB'S TRAVEL goes by the section's role. The carrier (the first base) takes the job's Lodging and Per Diem, counted
   *  the sheet's way on rev2. An option takes its own, for its own crew (optionTravelCosts). Any other base takes none.
   *  A root that is off (an Epoxy job's) still answers with the job's travel, as bid() always has; nothing reads it.
   *
   *  Answers markupChain's keys, so what a save stamps into `totals` is what it always was. THROWS for a section that is not
   *  Polish and for a section the model does not have, except the root, which a bid whose sections cannot be read still has. */
  function polishBid(model, tabId, ctx) {
    if (!isObject(model)) throw new Error("polishBid needs the model");
    if (!isObject(ctx) || typeof ctx.material !== "function") {
      throw new Error("polishBid needs ctx.material(entry): the page prices a takeoff from its library");
    }
    var e = polishEntry(model, tabId);
    var s = e.section;
    var profile = e.profile === LEGACY.stamp ? LEGACY : (e.profile === REV2.stamp ? REV2 : (e.profile === REV3.stamp ? REV3 : null));
    if (!profile) {
      return unpriceableSection(e.profile, "profile", "this section was priced with " + e.profile +
        ", which a Polish section is not priced with. Its saved figures are kept.");
    }
    var mat = ctx.material(e);
    var labor = laborTotal(s.labor, model.conditions, prevailingApplied(model));
    return markupChain({
      material: isObject(mat) ? mat.material : mat,
      // The patch line (Polish!D17), which the chain takes into the material only on a profile that carries it.
      patch: isObject(mat) ? mat.patch : 0,
      labor: labor,
      // Lodging + Per Diem: inside the markups (the sheet's D61), not labor.
      travel: polishTravel(model, e),
      // The sheet's tooling and consumables (D55) for a profile that charges it; 0 for every saved bid.
      tooling: profile.quirks.toolingInSubTotal ? takeoffTooling(s.takeoff, model.conditions) : 0,
      contingency: s.contingency,
      fees: s.fees,
      conditions: chainConditions(model.conditions, s.adjust),
      sf: takeoffSf(s.takeoff),
      remodel_rate: ctx.remodel_rate,
      adjust: chainAdjust(s.adjust)
    }, profile.stamp);
  }

  /** The entry polishBid prices. The root of a bid whose `tabs` cannot be read is still the root, as it was when bid() read
   *  only the model's own keys: a bid like that opens as it is and saves what was typed. */
  function polishEntry(model, tabId) {
    var e;
    try { e = sectionOf(model, tabId); } catch (err) {
      if (tabId !== ROOT_TAB) throw err;
      e = { tab: ROOT_TAB, sheet: ROOT_TAB, label: rootLabel(model), source: null, root: true, section: model,
            layout: "polish", kind: "base", profile: rootProfile(model).stamp, role: "polish" };
    }
    if (e.layout !== "polish") {
      throw new Error("the " + e.label + " section is a " + e.layout + " section, and polishBid prices Polish sections");
    }
    return e;
  }

  /** What a Polish section is charged for the job's travel, by its role (see polishBid). */
  function polishTravel(model, e) {
    var s = e.section;
    var carrier = true;
    try { carrier = travelCarrier(model) === e.tab; } catch (err) { carrier = true; }
    if (carrier || (e.root && e.kind === "off")) return travelCosts(model.travel, s.labor, travelOpts(model, e.tab)).total;
    if (e.kind === "option") return optionTravelCosts(model.travel, s.labor).total;
    return 0;
  }

  /** The bids of every section that is NOT the root and is part of the bid, as { tabId: bid }. {} when the
   *  model has no `tabs`, without reading anything else of it. */
  function priceTabs(model, ctx) {
    if (!isObject(model) || !isObject(model.tabs)) return {};
    return Object.fromEntries(activeSections(model).filter(function (e) { return !e.root; })
      .map(function (e) { return [e.tab, priceSection(model, e.tab, ctx)]; }));
  }

  // ── activating and seeding a section ────────────────────────────────────────
  function jsonCopy(v) { return JSON.parse(JSON.stringify(v)); }

  /** ADD A SECTION: the first time a tab is used on a bid. A NEW model with `tabs[tabId]` holding a blank
   *  section, its profile stamped, and the rates it prices with kept: snapshotRates of `ctx.rules` (the Markups
   *  rules as GET /api/markup/rules lists them; none means the profile's built-ins). Filed rules are honoured and
   *  kept as text; one that will not price is left out with a note in `rates.notes` (never $0); a bond rule is
   *  not taken (it is unwired). THROWS for the root's tab (it is always there), a tab the engine has no profile
   *  for, a tab that is already a section, and a BASE kind on an option-only tab (Seal, Leveling: never a base). */
  function activateSection(model, tabId, kind, ctx) {
    if (!isObject(model)) throw new Error("activateSection needs the model");
    if (tabId === ROOT_TAB) throw new Error("the " + ROOT_TAB + " section is the root of the model and is always there");
    var tabKey = types.tabOfSheet(tabId);
    if (!tabKey) throw new Error(JSON.stringify(String(tabId)) + " is not a priced workbook tab");
    if (kind !== "base" && kind !== "option") throw new Error("a section is activated as a base or an option, not " + JSON.stringify(kind));
    var rec = types.tab(tabKey);
    if (kind === "base" && rec.optionOnly) throw new Error(rec.label + " is an option on a bid, never the base");
    if (isObject(model.tabs) && has.call(model.tabs, tabId)) throw new Error(JSON.stringify(tabId) + " is already a section of this bid");
    return withSectionPut(model, tabId, Object.assign(newSectionBody(tabId, kind, ctx), labelIfTaken(model, tabId)));
  }

  /** A BLANK SECTION for a workbook sheet, as activateSection and addSheet make it: its layout, its kind, the profile that
   *  prices it stamped, an empty takeoff and labor, and `pool_packs`, so it buys each material once for the whole
   *  section (see poolsPacks). A Polish sheet is stamped polish-rev2 (Phase 17: what a NEW Polish section is priced
   *  by) and keeps no rates snapshot, because a Polish section prices at its profile's built-ins (polishBid). Every
   *  other sheet keeps `snapshotRates` of `ctx.rules`, the Markups rules filed at this moment, as text. */
  function newSectionBody(sheet, kind, ctx) {
    var rec = types.tab(types.tabOfSheet(sheet));
    var polish = rec.markupLayout === "polish";
    var profile = polish ? REV3 : engine.forTab(sheet).profile;
    var section = {
      layout: rec.markupLayout, kind: kind, profile: profile.stamp,
      takeoff: [{ assembly_id: "", assembly_name: "", measurement: "", unit: "SF" }],
      labor: [], contingency: 0, fees: 0
    };
    if (!polish) section.rates = engine.snapshotRates(profile, isObject(ctx) ? ctx.rules : undefined);
    section.totals = {};
    section.pool_packs = true;      // a section made now buys each material once for the whole section (see poolsPacks)
    return section;
  }

  /** A NEW model with `section` filed under `id` in `tabs` (added, or replacing the one there). The model handed in is not touched. */
  function withSectionPut(model, id, section) {
    var out = jsonCopy(model);
    var tabs = isObject(out.tabs) ? out.tabs : {};
    out.tabs = copyInto(copyInto({}, tabs), Object.fromEntries([[id, section]]));
    return out;
  }

  /** A NEW model with some keys of one section laid over it. The root is the model itself, so for it they land on the
   *  model's own keys. The model handed in is not touched. */
  function withSectionPatch(model, id, patch) {
    var out = jsonCopy(model);
    if (id === ROOT_TAB) return Object.assign(out, patch);
    out.tabs = copyInto(copyInto({}, out.tabs), Object.fromEntries([[id, Object.assign({}, out.tabs[id], patch)]]));
    return out;
  }

  // ── options on a bid (Phase 15) ─────────────────────────────────────────────
  /** THE OPTIONS THIS BID CAN STILL TAKE: the sheets Estimating Tool v2 prices as an option (Seal and Seal (+Jnts)
   *  today, js/work-types.js optionSheets) that the bid has no section for yet, in the vocabulary's order. A new array. */
  function optionsToOffer(model) {
    var held = isObject(model) && isObject(model.tabs) ? model.tabs : {};
    return types.optionSheets().filter(function (id) { return !has.call(held, id); });
  }

  /** ADD AN OPTION TO A BID: an option section for one offered sheet, priced separately and never part of the lump sum.
   *  A NEW model; the one handed in is not touched. The section is made as activateSection makes any (its profile
   *  stamped, the Markups rules filed at this moment kept as text) and then given the library's defaults like a new
   *  section of a new bid (seedNewSections): its own crew from the labor lines filed under its work type, the labor
   *  calculator's fills, and a starting takeoff over `ctx.sf[tabId]`. ONLY THE NEW SECTION IS TAKEN from that seeding:
   *  every other key of the model, the root and the job's travel included, is as it was handed in, so adding an option
   *  to a bid somebody has worked on can never reseed what they typed.
   *
   *  `ctx` is seedNewSections' (rules, laborRows, laborRate, calcRows, asms, items, reserved, sf, lf, takeoffRows), and
   *  its `saved` is never read: the model handed in is the saved state. THROWS for a sheet that is not offered as an
   *  option and for one the bid already holds. */
  function addOption(model, tabId, ctx) {
    if (!isObject(model)) throw new Error("addOption needs the model");
    if (types.optionSheets().indexOf(tabId) < 0) {
      throw new Error(JSON.stringify(String(tabId)) + " is not offered as an option (" + types.optionSheets().join(", ") + ")");
    }
    var c = isObject(ctx) ? ctx : {};
    var withSection = activateSection(model, tabId, "option", { rules: c.rules });
    var seeded = seedNewSections(withSection, Object.assign({}, c, { saved: model }));
    var out = jsonCopy(withSection);
    out.tabs = copyInto(copyInto({}, out.tabs), Object.fromEntries([[tabId, seeded.tabs[tabId]]]));
    return out;
  }

  /** TAKE AN OPTION OFF A BID, rows and all. A NEW model. The bid keeps an (empty) `tabs` object, so its next save
   *  still writes the whole price snapshot and the proposal side stops listing the option. THROWS unless the bid has
   *  that section and it is an OPTION: a base is never removed this way (a job type's sections follow the job type). */
  function removeOption(model, tabId) {
    var e = sectionOf(model, tabId);
    if (e.root || e.kind !== "option") throw new Error(JSON.stringify(String(tabId)) + " is not an option of this bid");
    var out = jsonCopy(model);
    out.tabs = copyInto({}, Object.fromEntries(Object.keys(out.tabs).filter(function (id) { return id !== tabId; })
      .map(function (id) { return [id, out.tabs[id]]; })));
    return out;
  }

  /** The maps in price_overrides whose keys are the lines of an option ("option:<tab>" and its tax rows "option:<tab>:..."):
   *  the words typed over a line, the lines typed above and below it, and the bullets set on them. */
  var OPTION_LINE_MAPS = ["lines", "lines2", "before", "after", "line_props", "before_props", "after_props"];

  /** WHAT AN OPTION LEAVES BEHIND ON THE DRAFT WHEN IT IS TAKEN OFF, as a patch for TW.setState (a NEW object; `state`
   *  is not touched; {} when there is nothing to forget). A Seal option's id is its sheet's name, so it is the SAME id the
   *  next time the option is added, and anything kept under it would print on the new option's line of the customer's
   *  proposal: the words typed over the old option's line (price_overrides.lines / .lines2 under "option:<tab>" and its
   *  tax rows "option:<tab>:..."), the lines typed above and below it and the bullets set on them, its own price display
   *  override (price_overrides.options), its manual notes (tab_notes) and its option settings (tab_opts). The estimate
   *  page's deleteTab forgets the same set for a deleted copy. */
  function optionLeftoverPatch(state, tab) {
    var st = isObject(state) ? state : {};
    var mine = "option:" + tab;
    var patch = {};
    function without(map, isMine) {
      return Object.fromEntries(Object.keys(map).filter(function (k) { return !isMine(k); })
        .map(function (k) { return [k, map[k]]; }));
    }
    function holds(map, isMine) { return isObject(map) && Object.keys(map).some(isMine); }
    function byTab(k) { return k === tab; }
    function byLine(k) { return k === mine || k.indexOf(mine + ":") === 0; }
    ["tab_opts", "tab_notes"].forEach(function (key) {
      if (holds(st[key], byTab)) patch[key] = without(st[key], byTab);
    });
    var pov = st.price_overrides;
    if (isObject(pov)) {
      var changed = false;
      var next = Object.fromEntries(Object.keys(pov).map(function (key) {
        var map = pov[key];
        var test = key === "options" ? byTab
          : (OPTION_LINE_MAPS.indexOf(key) >= 0 ? byLine : null);
        if (test && holds(map, test)) { changed = true; return [key, without(map, test)]; }
        return [key, map];
      }));
      if (changed) patch.price_overrides = next;
    }
    return patch;
  }

  /** WHAT THE DRAFT KEPT UNDER ONE SHEET'S ID, MOVED TO ANOTHER ID, as a patch for TW.setState (a NEW object; `state` is not
   *  touched; {} when there is nothing under either id). For a sheet whose KEY changes while the sheet stays: a Gyp sheet is filed
   *  under its preset's workbook tab, so changing the preset renames the key (moveSectionSheet), and everything the draft holds
   *  under the old key (its proposal settings tab_opts, its notes, its own price override, the words typed over its line and the
   *  lines around it) has to follow, or the sheet comes back with fresh settings and an option the estimator switched off prints.
   *  The same set optionLeftoverPatch forgets. Whatever the draft held under the NEW id is dropped first: nothing is a section of
   *  this bid under it (moveSectionSheet refuses that), so it is left over from an earlier sheet of that name. Key order is kept. */
  function moveSheetDraftPatch(state, fromTab, toTab) {
    var st = isObject(state) ? state : {};
    var patch = {};
    if (fromTab === toTab) return patch;
    var lineKey = function (id) { return "option:" + id; };
    var byTab = function (k, id) { return k === id; };
    var byLine = function (k, id) { return k === lineKey(id) || k.indexOf(lineKey(id) + ":") === 0; };
    var renameTab = function () { return toTab; };
    var renameLine = function (k) { return lineKey(toTab) + k.slice(lineKey(fromTab).length); };
    function move(map, isMine, rename) {
      if (!isObject(map)) return null;
      var keys = Object.keys(map);
      if (!keys.some(function (k) { return isMine(k, fromTab) || isMine(k, toTab); })) return null;
      return Object.fromEntries(keys.filter(function (k) { return !isMine(k, toTab); })
        .map(function (k) { return [isMine(k, fromTab) ? rename(k) : k, map[k]]; }));
    }
    ["tab_opts", "tab_notes"].forEach(function (key) {
      var moved = move(st[key], byTab, renameTab);
      if (moved) patch[key] = moved;
    });
    var pov = st.price_overrides;
    if (isObject(pov)) {
      var changed = false;
      var next = Object.fromEntries(Object.keys(pov).map(function (key) {
        var moved = key === "options" ? move(pov[key], byTab, renameTab)
          : (OPTION_LINE_MAPS.indexOf(key) >= 0 ? move(pov[key], byLine, renameLine) : null);
        if (moved) { changed = true; return [key, moved]; }
        return [key, pov[key]];
      }));
      if (changed) patch.price_overrides = next;
    }
    return patch;
  }

  // ══ SHEETS (Sheets phase 1): copy, add, rename and delete a sheet, and pick the base bid ═══════════════════════
  //
  // A BID IS MADE OF SHEETS, each a section (see the block above). The root is the Polish one. Any sheet can be copied, a
  // fresh one of any ready type can be added, and exactly one thing is the BASE BID: one sheet, or the combined Epoxy and Polish
  // pair. Everything else is an option, priced apart with its own travel and never in the lump sum. Everything follows the
  // base: the lump sum, the job's travel (the first base carries it), the job type baseOf answers, and what the proposal
  // reads (composePricingSnapshot writes `base_tab_id`).
  //
  // Every function here is pure: it answers a NEW model and never touches the one it was handed. A function that also changes
  // what the DRAFT holds around the model (the proposal's per-sheet settings, `tab_opts`, and the words typed over an option's
  // line) answers `patch`, for TW.setState, built from `ctx.state`, the draft as it stands.

  /** THE SHEETS A BID CAN TAKE (workbook sheet ids): Polish, Epoxy, the five Gyp presets, Seal and Seal (+Jnts), in the
   *  vocabulary's order. Leveling is not offered until it is priced, and Epoxy blank is not a sheet v2 uses. A new array. */
  function sheetsToAdd() {
    var out = [];
    types.tabKeys().forEach(function (key) {
      var rec = types.tab(key);
      if (!(rec.optionOnly ? rec.offered === true : tabIsReady(key))) return;
      rec.sheets.forEach(function (sheet) { if (sheet !== "Epoxy blank") out.push(sheet); });
    });
    return out;
  }

  /** The next free Copy<N> id: the smallest N not used as a key. A deleted copy's id is handed out again, which is why
   *  deleteSection forgets everything the draft kept under it. */
  function nextCopyId(model) {
    var used = new Set(isObject(model) && isObject(model.tabs) ? Object.keys(model.tabs) : []);
    var i = 1;
    while (used.has("Copy" + i)) i++;
    return "Copy" + i;
  }

  function requireRoomForCopy(model) {
    var held = isObject(model.tabs) ? Object.keys(model.tabs).filter(function (id) { return COPY_ID.test(id); }).length : 0;
    if (held >= MAX_COPIES) throw new Error("A bid can hold " + MAX_COPIES + " copied sheets at most.");
  }

  /** WHY A SHEET NAME WILL NOT DO, in plain words, or null when it will: not blank, 31 characters at most, none of
   *  ! : \ / ? * [ ] " (a workbook's own limits), and not another sheet's name (the check ignores case). `exceptId` is the
   *  sheet being renamed, which may keep its own name. THROWS for sections that cannot be read, like sectionsOf. */
  function validateLabel(model, label, exceptId) {
    var n = String(label == null ? "" : label).trim();
    if (!n) return "Enter a sheet name.";
    if (n.length > 31 && !keepsItsName(model, n, exceptId)) return "A sheet name can have 31 characters at most.";
    if (/[!:\\/?*\[\]"]/.test(n) && !keepsItsName(model, n, exceptId)) return 'A sheet name cannot have any of these: ! : \\ / ? * [ ] "';
    var taken = sectionsOf(model).some(function (e) { return e.tab !== exceptId && e.label.toLowerCase() === n.toLowerCase(); });
    return taken ? '"' + n + '" is already the name of a sheet.' : null;
  }

  /** Is `name` the name the sheet `id` already has (any case)? A sheet may keep its name even when it is one the tool made for it that
   *  a typed name could not be: a Gyp sheet's own name has a quote mark in it, and so does the name of its copy. False for a bid
   *  whose sections cannot be read. */
  function keepsItsName(model, name, id) {
    try {
      return sectionsOf(model).some(function (e) { return e.tab === id && e.label.toLowerCase() === name.toLowerCase(); });
    } catch (err) { return false; }
  }

  /** What a section filed under its own sheet's name needs beside its key, as keys to lay over it: nothing when that name is free (it is
   *  called by its key, which is the form every saved bid has), else a `label` that is free. A rename can have given the name to another
   *  section, and two sheets of one name would print twice on the proposal. A bid whose sections cannot be read has nothing to compare
   *  with and is left as it was. */
  function labelIfTaken(model, sheet) {
    var free;
    try { free = uniqueLabel(model, sheet); } catch (err) { return {}; }
    return free === sheet ? {} : { label: free };
  }

  /** `base` as a sheet name that is free: itself when it is, else with " 2", " 3" and so on, cut to leave room. */
  function uniqueLabel(model, base) {
    var used = new Set(sectionsOf(model).map(function (e) { return e.label.toLowerCase(); }));
    var root = base.slice(0, 31);
    if (!used.has(root.toLowerCase())) return root;
    for (var i = 2; ; i++) {
      var suffix = " " + i;
      var label = base.slice(0, 31 - suffix.length) + suffix;
      if (!used.has(label.toLowerCase())) return label;
    }
  }

  /** THE DRAFT'S SIDE OF A NEW OPTION: a patch that forgets everything the draft kept under this id (a Copy<N> id is handed
   *  out again after a delete) and lays the option's proposal settings (`settings`) in its tab_opts. A NEW object. */
  function newOptionPatch(state, id, settings) {
    var st = isObject(state) ? state : {};
    var gone = optionLeftoverPatch(st, id);
    var held = isObject(gone.tab_opts) ? gone.tab_opts : (isObject(st.tab_opts) ? st.tab_opts : {});
    return Object.assign({}, gone, { tab_opts: Object.assign(copyInto({}, held), Object.fromEntries([[id, settings]])) });
  }

  /** COPY A SHEET (Sheets phase 1). Answers `{ model, id, patch }`: a NEW model holding the copy under the next free Copy<N> id,
   *  that id, and the draft's side (`patch`, from `ctx.state`).
   *
   *  A COPY PRICES EXACTLY LIKE THE SHEET IT CAME FROM: it takes everything the source holds (takeoff, labor, contingency, fees,
   *  and for Gyp its settings), and keeps the source's PROFILE and pool_packs stamps, so a copy of a bid saved before Polish
   *  rev 2 or before the purchase pool is still priced the way its source is, whatever is stamped on new bids today. A section
   *  under `tabs` also keeps its rates snapshot. The copy is an OPTION that starts OFF the proposal (`patch.tab_opts[id]` says
   *  is_option false), so copying a sheet to try something prints nothing until the estimator turns it on. Its totals start
   *  empty, because a save stamps them. Its name is "<source name> copy", made free. The root can be copied, and so can a sheet
   *  that is off.
   *
   *  Money by role is not copied: an option carries its own travel (optionTravelCosts), so the copy matches its source in
   *  every figure but the job's Lodging and Per Diem, which only the carrier takes. Made the base (pickBase) it prices like the
   *  source. THROWS for a sheet the bid does not have, and at the limit of twelve copies. */
  function copySection(model, sourceId, ctx) {
    if (!isObject(model)) throw new Error("copySection needs the model");
    var src = sectionOf(model, sourceId);
    requireRoomForCopy(model);
    var id = nextCopyId(model);
    var body;
    if (src.root) {
      // The root's own keys are its section. Read the way migrateModel reads them, so a model that states none copies the shipped rows.
      var fresh = freshModel();
      var pick = function (key) { return jsonCopy(model[key] !== undefined ? model[key] : fresh[key]); };
      body = { layout: "polish", profile: rootProfile(model).stamp, takeoff: pick("takeoff"), labor: pick("labor"),
               contingency: pick("contingency"), fees: pick("fees") };
      if (model.pool_packs !== undefined) body.pool_packs = model.pool_packs;
      // its overrides too: a copy prices exactly like the sheet it came from
      if (normalizeAdjust(model.adjust)) body.adjust = jsonCopy(normalizeAdjust(model.adjust));
    } else {
      body = jsonCopy(src.section);
    }
    body = Object.assign(body, { kind: "option", sheet: src.sheet, label: uniqueLabel(model, src.label + " copy"),
                                 source: sourceId, totals: {} });
    return { model: withSectionPut(model, id, body), id: id,
             patch: newOptionPatch(isObject(ctx) ? ctx.state : undefined, id, optionSettings(false)) };
  }

  /** ADD A FRESH SHEET (Sheets phase 1): one of sheetsToAdd, as an OPTION that starts ON the proposal, priced as a total. Answers
   *  `{ model, id, patch }` like copySection.
   *
   *  The id is the sheet's own name when the bid has no section of that tab yet (the form every saved bid uses), else the next
   *  Copy<N> with `sheet` and `label`, so a second Epoxy sheet, or any Polish one (the root is the first), is a Copy. The section is made as
   *  activateSection makes one (a Polish sheet stamped polish-rev2, every sheet pool_packs) and then given the library's
   *  defaults like a new section of a new bid (seedNewSections): its own crew from the labor lines filed under its work type, the
   *  calculator's fills, and a starting takeoff over the area in `ctx.sf`, keyed by the new id or by the sheet's name. ONLY THE NEW
   *  SECTION IS TAKEN from that seeding, so nothing the estimator typed anywhere else is reseeded (see addOption). `ctx` is
   *  seedNewSections' (rules, laborRows, laborRate, calcRows, asms, items, reserved, sf, lf, takeoffRows), and `ctx.state` the draft.
   *  THROWS for a sheet that is not offered, and at the limit of twelve copies. */
  function addSheet(model, sheet, ctx) {
    if (!isObject(model)) throw new Error("addSheet needs the model");
    if (sheetsToAdd().indexOf(sheet) < 0) {
      throw new Error(JSON.stringify(String(sheet)) + " cannot be added to a bid (" + sheetsToAdd().join(", ") + ")");
    }
    var c = isObject(ctx) ? ctx : {};
    var tabKey = types.tabOfSheet(sheet);
    var held = sectionsOf(model);
    var ownKey = !held.some(function (e) { return types.tabOfSheet(e.sheet) === tabKey; }) && !has.call(model.tabs || {}, sheet) && sheet !== ROOT_TAB;
    if (!ownKey) requireRoomForCopy(model);
    var id = ownKey ? sheet : nextCopyId(model);
    var body = newSectionBody(sheet, "option", { rules: c.rules });
    body = Object.assign(body, ownKey ? labelIfTaken(model, sheet) : { sheet: sheet, label: uniqueLabel(model, sheet) });
    var withSection = withSectionPut(model, id, body);
    var seeded = seedNewSections(withSection, Object.assign({}, c, { saved: model }));
    return { model: withSectionPut(withSection, id, seeded.tabs[id]), id: id,
             patch: newOptionPatch(c.state, id, optionSettings(true)) };
  }

  /** RENAME A SHEET: what it is called on screen and on the proposal. A NEW model. The id is never changed and the label is never used as a
   *  key, so nothing the draft keeps for the sheet is orphaned. Answers the model it was handed when the name is the one it has.
   *  THROWS with validateLabel's words for a name that will not do, and for a sheet the bid does not have. */
  function renameSection(model, id, label) {
    var e = sectionOf(model, id);
    var next = String(label == null ? "" : label).trim();
    var why = validateLabel(model, next, id);
    if (why) throw new Error(why);
    if (next === e.label) return model;
    return withSectionPatch(model, id, { label: next });
  }

  /** DELETE A SHEET, rows and all. Answers `{ model, patch }`: a NEW model without it, and the draft's side, which is
   *  optionLeftoverPatch, ALWAYS: a Copy<N> id is handed out again, so anything the draft kept under it (its proposal settings,
   *  notes, and the words typed over its line) would print on the next sheet to take the id. A bid keeps an (empty) `tabs`
   *  object, so its next save still writes the whole price snapshot. THROWS for the BASE bid (pick another base first), for
   *  the root, which is where a bid starts and cannot be removed from itself, and for a sheet the bid does not have. */
  function deleteSection(model, id, ctx) {
    var e = sectionOf(model, id);
    if (e.root) throw new Error("The " + e.label + " sheet is where this bid starts, so it cannot be deleted. Take it off the proposal instead.");
    if (e.kind === "base") throw new Error("Pick another base bid before you delete " + e.label + ".");
    var out = jsonCopy(model);
    out.tabs = copyInto({}, Object.fromEntries(Object.keys(out.tabs).filter(function (k) { return k !== id; })
      .map(function (k) { return [k, out.tabs[k]]; })));
    return { model: out, patch: optionLeftoverPatch(isObject(ctx) ? ctx.state : undefined, id) };
  }

  /** PICK THE BASE BID (Sheets phase 1): one sheet, or the combined pair, one Epoxy and one Polish. Answers `{ model, patch }`: a
   *  NEW model and the draft's side. THE PRIOR BASE BECOMES AN OPTION that is ON the proposal, priced as a total, and the new
   *  base is no option, so nothing is dropped from what the customer sees. Every other sheet keeps its kind. The job's
   *  travel follows the carrier (the first base): when it moves, the Travel Labor row moves with it to the new carrier, unless
   *  the new carrier has its own, so the base the job is priced on is the one that drives. `patch` carries `work_type` (what baseOf
   *  says the base amounts to: a combined base is "combo"), `base_tab_id` (the one base, null for the pair) and, when it changed,
   *  `tab_opts` from `ctx.state`. THROWS for Seal and Leveling (an option on a bid, never the base), for two sheets
   *  that are not one Epoxy and one Polish, and for a sheet the bid does not have. Picking the base it already has changes
   *  nothing but still answers the patch. */
  function pickBase(model, ids, ctx) {
    if (!isObject(model)) throw new Error("pickBase needs the model");
    var want = ids instanceof Array ? ids.slice() : [ids];
    if (want.length < 1 || want.length > 2 || (want.length === 2 && want[0] === want[1])) {
      throw new Error("The base bid is one sheet, or one Epoxy sheet and one Polish sheet together.");
    }
    var list = sectionsOf(model);
    var chosen = want.map(function (id) {
      var found = list.filter(function (e) { return e.tab === id; })[0];
      if (!found) throw new Error("the model has no section for " + JSON.stringify(String(id)));
      var rec = types.tab(types.tabOfSheet(found.sheet));
      if (rec.optionOnly) throw new Error(rec.label + " is an option on a bid, never the base");
      return found;
    });
    if (chosen.length === 2) {
      var roles = chosen.map(function (e) { return e.role; }).sort();
      if (roles[0] !== "epoxy" || roles[1] !== "polish") throw new Error("A combined base is one Epoxy sheet and one Polish sheet.");
    }
    var carrierBefore = travelCarrier(model);
    var out = model;
    var demoted = [];
    list.forEach(function (e) {
      var next = want.indexOf(e.tab) >= 0 ? "base" : (isBaseEntry(e) ? "option" : e.kind);
      if (next === e.kind) return;
      if (next === "option") demoted.push(e.tab);
      out = withSectionKind(out, e.tab, next);
    });
    var carrierAfter = travelCarrier(out);
    if (carrierAfter !== carrierBefore) out = moveTravelLabor(out, carrierBefore, carrierAfter);
    var st = isObject(ctx) && isObject(ctx.state) ? ctx.state : {};
    var held = isObject(st.tab_opts) ? st.tab_opts : {};
    var opts = copyInto({}, held);
    var touched = false;
    var entryOf = function (id) { return has.call(held, id) && isObject(held[id]) ? held[id] : {}; };
    demoted.forEach(function (id) {
      touched = true;
      var kept = Object.assign(optionSettings(true), entryOf(id), { is_option: true, show: true, price_mode: "total" });
      opts = Object.assign({}, opts, Object.fromEntries([[id, kept]]));
    });
    want.forEach(function (id) {
      if (!has.call(held, id) || !isObject(held[id]) || held[id].is_option !== true) return;
      touched = true;
      opts = Object.assign({}, opts, Object.fromEntries([[id, Object.assign({}, held[id], { is_option: false })]]));
    });
    var patch = { work_type: baseOf(out).jobType, base_tab_id: want.length === 1 ? want[0] : null };
    if (touched) patch.tab_opts = opts;
    return { model: out, patch: patch };
  }

  /** The job's Travel Labor row follows the carrier. The row (labor id `travel`) is the job's drive, and only the carrier holds one,
   *  so when the base moves to another sheet the row moves with it. Moved only when the old carrier has one, the new carrier has
   *  none, and the old one keeps at least one other row (a root with no labor reads as the four shipped rows, so it is
   *  copied instead). A NEW model; the one handed in when nothing moves. */
  function moveTravelLabor(model, fromTab, toTab) {
    var out = jsonCopy(model);
    return shiftTravelRow(out, fromTab, toTab) ? out : model;
  }

  /** moveTravelLabor's move, IN PLACE on the model it is handed, which is also how followDistance carries the row when the job type
   *  (and not the Sheets panel) moves the carrier. True when a row moved. A copy is a COPY: when the old carrier keeps no other row the
   *  row stays there, and the new carrier takes its own object, so the two sections never share one row. THROWS for a section the model
   *  does not have, like sectionOf. */
  function shiftTravelRow(model, fromTab, toTab) {
    var from = sectionOf(model, fromTab).section, to = sectionOf(model, toTab).section;
    var isTravel = function (r) { return !!r && r.id === "travel"; };
    var mine = (from.labor instanceof Array ? from.labor : []).filter(isTravel);
    var theirs = (to.labor instanceof Array ? to.labor : []).filter(isTravel);
    if (!mine.length || theirs.length) return false;
    var rest = from.labor.filter(function (r) { return !isTravel(r); });
    if (rest.length) from.labor = rest;
    to.labor = (to.labor instanceof Array ? to.labor : []).concat(rest.length ? mine : mine.map(jsonCopy));
    return true;
  }

  /** Keep the Travel row's Guys (and Lodging and Per Diem's quantity) in step with the crew while they are on auto.
   *  The estimate page's syncAutoGuys, as a function of the model, because the seeding below has to run it between its
   *  steps. MUTATES `model`. A Travel row a far distance answer filled (guys_follow "crew") follows the job's crew SIZE
   *  (crewSize: the most guys on any one labor line of the base sections), except one on an OPTION, which is priced apart for
   *  its own crew and follows its OWN labor lines' (ownCrewSize); a row on the older auto, from a bid saved
   *  before 2026-10-12, follows its own section's man-days as it always did. The job's Lodging and Per Diem follow the
   *  carrier section's man-days. */
  function syncAutoGuys(model) {
    var multi = isObject(model.tabs);
    var sections = [{ section: model, option: false }];
    if (multi) {
      // A saved model whose tabs are not well formed is not this function's to refuse (the page runs it on every
      // open, and priceSection / composePricingSnapshot say what is wrong): it keeps the root in step.
      try {
        sections = activeSections(model).map(function (e) { return { section: e.section, option: e.kind === "option" }; });
      } catch (err) { multi = false; }
    }
    sections.forEach(function (s) {
      var manDays = travelManDays(s.section.labor);
      (s.section.labor || []).forEach(function (r) {
        if (r && r.unit === "hours" && r.guys_auto) {
          r.guys = followsCrew(r) ? (s.option ? ownCrewSize(model, s.section.labor) : crewSize(model)) : manDays;
        }
      });
    });
    if (model.travel) {
      var carrier = multi ? sectionOf(model, travelCarrier(model)).section : model;
      var days = travelManDays(carrier.labor);
      TRAVEL_LINE_KEYS.forEach(function (k) {
        var l = model.travel[k];
        if (l && l.qty_auto !== false) l.qty = days;
      });
    }
  }

  function requireLayout(layout) {
    if (typeof layout !== "string" || !types.isTab(layout)) {
      throw new Error("seeding needs the layout of every section, one of " + types.tabKeys().join(", ") +
        " (got " + JSON.stringify(layout) + ")");
    }
  }

  /** Put the library's defaults on every NEW section of a bid: the estimate page's whole new-bid seeding, once,
   *  per section. Returns a NEW model; the one handed in is not touched.
   *
   *  `ctx` is what the library answered, each part null when it was not asked (the page asks only for a new bid):
   *    saved          what the draft held under polish_estimate when the page opened. The gates read it: the
   *                   model cannot be asked, because migrateModel has already answered every question
   *    laborRows      the library's default labor lines (after withCrewFallback), or null
   *    laborRate      the company labor rate
   *    travelRates    { lodging, per_diem } or null          feesDefault   a number or null
   *    calcRows       the labor calculator's rows (after withCrewCalcFallback), or null
   *    conditionRows  the stored condition defaults, or null
   *    cellValues, split   the draft's cell_values and isSplit(draft): a condition answer a cell holds wins
   *    asms, items, reserved   the library, for the default takeoff
   *    sf             { tabId: [sf1, sf2] }, intake's two area boxes for each section (Gyp's are three)
   *    takeoffRows    function (entry, sfs), optional: a section's own starting takeoff (Gyp), else null
   *
   *  THE ORDER IS THE PAGE'S, step for step: labor and Travel, the job's lodging and per diem rates and fees
   *  default, then the job's conditions, then each takeoff, then the labor calculator, with the Travel guys kept
   *  in step after the labor and after the calculator. THE ROOT is seeded behind laborUnstated(saved) (its labor,
   *  the job's travel and fees), conditionsUnstated(saved) (the job's conditions) and either of them (which
   *  default takeoff it gets); a TAB SECTION behind isNewSection. A section that is "off" is left alone. Every
   *  section's layout is REQUIRED: sectionsOf throws for a tab section that has none, and nothing here guesses
   *  one. The job's Travel and the fees default go to the carrier section (travelCarrier), once per job. */
  function seedNewSections(model, ctx) {
    if (!isObject(model)) throw new Error("seedNewSections needs the model");
    if (!isObject(ctx)) throw new Error("seedNewSections needs ctx, what the library answered");
    var out = jsonCopy(model);   // the caller's model is never edited
    var saved = ctx.saved;
    var laborGate = laborUnstated(saved);
    var condGate = conditionsUnstated(saved);
    var carrierTab = travelCarrier(out);
    var names = sectionsOf(out).filter(function (e) {
      return e.kind !== "off" && (e.root || isNewSection(e.section, false));
    }).map(function (e) { return e.tab; });
    // The entries again, from the model as it stands (applyFeesDefault hands back a new root object).
    var now = function () {
      return sectionsOf(out).filter(function (e) { return names.indexOf(e.tab) >= 0; });
    };
    names.forEach(function (tab) { requireLayout(sectionOf(out, tab).layout); });
    // A section's two area boxes, by its id, else by its workbook sheet: the caller of a NEW sheet does not know the Copy<N>
    // id the model is about to give it, only the sheet it is adding.
    var byTabOrSheet = function (map, e) {
      if (!isObject(map)) return undefined;
      if (has.call(map, e.tab) && map[e.tab] instanceof Array) return map[e.tab];
      return has.call(map, e.sheet) && map[e.sheet] instanceof Array ? map[e.sheet] : undefined;
    };
    var sfOf = function (e) {
      var v = byTabOrSheet(ctx.sf, e);
      return v ? v : [undefined, undefined];
    };
    var asked = laborGate && !!ctx.laborRows;

    // 1. labor and Travel, then the job's lodging and per diem rates and the fees default
    now().forEach(function (e) {
      if (!(e.root ? asked : !!ctx.laborRows)) return;
      var s = e.section;
      // A model that states no rows reads as the four shipped ones, so keep only Travel and let the library put
      // the rest on. Another section than the carrier has no Travel of its own.
      var keep = carrierTab === e.tab ? (s.labor || []).filter(function (r) { return r && r.id === "travel"; }) : [];
      var rows = crewFirst(applyLaborRate(seedLibraryLabor(keep, ctx.laborRows, ctx.laborRate, kindOfSection(e.layout)), ctx.laborRate));
      // Every row opens with no guys, days or hours, and on neither auto nor the distance (see laborRowStartsEmpty).
      rows = rows.map(function (r) { return r ? laborRowStartsEmpty(r) : r; });
      s.labor = carrierTab === e.tab ? rows : rows.filter(function (r) { return !r || r.id !== "travel"; });
    });
    if (asked) {
      // Travel is a default like any other: if the library says this bid does not get it, say so on the model so
      // a reload does not append the "missing" row back (migrateModel).
      if (travelDeclined(ctx.laborRows, kindOfSection(sectionOf(out, carrierTab).layout))) out = Object.assign(out, { no_travel_labor: true });
      syncAutoGuys(out);
      out.travel = travelLinesStartEmpty(applyTravelRates(out.travel, ctx.travelRates));
      if (carrierTab === ROOT_TAB) {
        out = applyFeesDefault(out, ctx.feesDefault);
      } else {
        var fee = Number(ctx.feesDefault);
        if (isFinite(fee) && fee > 0) { sectionOf(out, carrierTab).section.fees = fee; out.fees_default = fee; }
      }
    }

    // 2. the job's conditions: the library's answers, then a cell wins (see the page)
    if (condGate && ctx.conditionRows) {
      out.conditions = conditionsFromCells(seedConditionDefaults(out.conditions, ctx.conditionRows), ctx.cellValues, !!ctx.split);
      out.conditions_shown = seedConditionsShown(ctx.conditionRows);
    }

    // 3. each takeoff, an empty one only
    now().forEach(function (e) {
      var s = e.section;
      if (takeoffSf(s.takeoff)) return;
      var sfs = sfOf(e);
      // A section whose takeoff is not "System 1 and System 2" (Gyp's three areas) asks the page for its own rows:
      // `ctx.takeoffRows(entry, sfs)` answers a list of rows, or null to take the ordinary path. An empty list
      // leaves the section's blank row as it is.
      var own = typeof ctx.takeoffRows === "function" ? ctx.takeoffRows(e, sfs) : null;
      if (own instanceof Array) {
        if (own.length) s.takeoff = own;
        return;
      }
      s.takeoff = (e.root ? (condGate || laborGate) : true)
        ? seedDefaultTakeoff(s.takeoff, ctx.asms, ctx.items, ctx.reserved, sfs[0], sfs[1], kindOfSection(e.layout))
        : seedTakeoffSf(s.takeoff, sfs[0], sfs[1]);
      // The intake's cove lengths, as takeoff rows of their own (Epoxy has a cove, Polish does not). A blank
      // assembly the estimator picks a cove for, never over a row that is already measured in linear feet.
      var lfs = byTabOrSheet(ctx.lf, e) || [];
      if (!(takeoffLf(s.takeoff) > 0)) {
        lfs.forEach(function (v) {
          if (num(v) > 0) s.takeoff.push({ assembly_id: "", assembly_name: "", measurement: num(v), unit: "LF" });
        });
      }
    });

    // 4. the labor calculator, after the takeoff (a "from SF" line needs the area)
    if (ctx.calcRows) {
      var calculated = false;
      now().forEach(function (e) {
        if (e.root && !laborGate) return;
        calculated = true;
        var s = e.section;
        s.labor = applyLaborCalc(s.labor, ctx.calcRows, takeoffSf(s.takeoff), ctx.laborRate);
        // A rate typed on the Labor tab beats the calculator's blank ("company rate").
        s.labor = keepLibraryRates(s.labor, ctx.laborRows || [], ctx.calcRows);
        // Every row the calculator did not fill remembers the rate it was seeded with.
        s.labor = stampRateDefaults(s.labor);
      });
      if (calculated) syncAutoGuys(out);
    }

    // 5. THE NEW ROOT BUYS ITS MATERIAL ONCE FOR THE WHOLE SECTION (see poolsPacks). A tab section is stamped
    // when it is made (activateSection), so this is the root's half: it is new on exactly the gate that seeds its
    // labor or its conditions, and a saved root never passes it, so a bid saved before the pool keeps its pricing.
    if ((laborGate || condGate) && now().some(function (e) { return e.root; }) && out.pool_packs === undefined) out.pool_packs = true;

    // 6. THE NEW ROOT IS PRICED BY POLISH REV 2 (Phase 17, Hanz 2026-10-07: Kyle's Polish fixes apply to NEW bids only).
    // Stamped on the same gate as the pool above, so a saved root never gains it and keeps pricing as polish-legacy.
    // A root that already carries a `profile` of any kind is left exactly as it is.
    if ((laborGate || condGate) && now().some(function (e) { return e.root; }) && out.profile === undefined) out.profile = REV3.stamp;
    return out;
  }

  // ── the proposal's side of the price ────────────────────────────────────────
  /** The LF rows of a takeoff that the bid prices (cove, base), counted like takeoffSf counts SF. */
  function takeoffLf(rows) {
    rows = rows || [];
    var t = 0;
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i] || {};
      if (r.unit === "LF" && rowOn(r) && !r.same_floor) t += num(r.measurement);
    }
    return t;
  }

  /** A Gyp section's three area figures, the keys the proposal's Area line sums (gyp_soft_sf, gyp_hard_sf,
   *  gyp_corridor_sf). A row says which area it is with its `bucket` mark; a square-foot row that names none is the
   *  soft surface's, which is what the single figure it replaces always was. */
  function gypAreaFields(rows) {
    var out = { gyp_soft_sf: 0, gyp_hard_sf: 0, gyp_corridor_sf: 0 };
    (rows || []).forEach(function (r) {
      if (!r || !rowOn(r) || r.unit === "LF" || r.same_floor) return;
      // An explicit branch for each area (never `out[name] +=`): the mark came out of a saved draft.
      if (r.bucket === "hard") out.gyp_hard_sf += num(r.measurement);
      else if (r.bucket === "corridor") out.gyp_corridor_sf += num(r.measurement);
      else out.gyp_soft_sf += num(r.measurement);
    });
    return out;
  }

  /** The area fields a section's priced tab carries (the keys the Estimate step's snapshot uses, which the
   *  proposal's Area line sums from the base tabs): Polish and Seal one SF figure, Epoxy its area and cove,
   *  Gyp its three areas (soft, hard, corridor), Leveling none. */
  function areaFields(e) {
    var rows = e.section.takeoff;
    if (e.role === "polish" || e.role === "seal") return { polish_sf: takeoffSf(rows) };
    if (e.role === "epoxy") return { epoxy_sf: takeoffSf(rows), cove_lf: takeoffLf(rows) };
    if (e.role === "gyp") return gypAreaFields(rows);
    return {};
  }

  /** The workbook's "Man Hour Budget" (Polish!F67, Epoxy!F73) as the model has it: every labor row that is on,
   *  Guys x Days x the row's hours in a day, and an hours row (Travel) Guys x Hours. */
  function sectionManHours(s) {
    var t = 0;
    (s.labor || []).forEach(function (r) {
      if (!r || !rowOn(r)) return;
      var g = num(r.guys), d = num(r.days);
      t += r.unit === "hours" ? g * d : g * d * dayHours(r);
    });
    return t;
  }

  function systemDesc(s, entry) {
    // A Gyp section is named by the tab it is filed under (the sheet's own A1: "N12 1/8" + 3/4" Gyp"), not by its
    // first row, which is an area. A Seal option is named by its sheet too, in the live estimate's own words
    // ("Sealed Concrete", "Sealed Concrete with Joint Filler"): two options can be on one proposal, and the joints
    // one must not read as the plain one.
    if (entry && (entry.role === "gyp" || entry.role === "seal")) {
      var label = engine.forTab(entry.sheet).label;
      if (label) return label;
    }
    var rows = s.takeoff || [];
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      if (!r || !rowOn(r)) continue;
      var name = String(r.assembly_name || r.item_name || "").replace(/\s+/g, " ").trim();
      if (name) return name;
    }
    return "";
  }

  /** THE ONE COMPOSITION OF WHAT A SAVE WRITES THAT THE PROPOSAL SIDE READS. A pure function of the model and the
   *  bids the page priced; buildSavePatch is its only caller, so the 600 ms autosave and the `pagehide` flush
   *  write the same keys, and on a v2 draft nothing else writes a derived key.
   *
   *  `ctx.bid` is the root (Polish) section's bid, `ctx.bids` { tabId: bid } the others' (priceTabs). A section
   *  that is part of the bid and has no bid THROWS: a save with no price is a save of zero.
   *
   *  A MODEL WITH ONLY THE ROOT SECTION (every saved bid today) gets exactly the keys the page has always
   *  written, in the order it wrote them: polish_estimate (the model with `totals` stamped from the bid), polish_sf,
   *  polish_2_sf and computed_bid. save_patch_golden.json holds that, byte for byte. Nothing else is added: a
   *  price snapshot (priced_tabs marked v2) on a Polish bid would change what the proposal side reads for every
   *  saved bid, and it is not wanted until another section exists.
   *
   *  A MODEL WITH MORE THAN ONE SECTION writes the complete set the proposal side reads, all of it from the
   *  sections' bids (engine.combine: each section has had its OWN gross profit taken, and what is summed is those
   *  totals):
   *    priced_tabs         one entry per section that is part of the bid, base and option, each marked `v2: true`
   *                        with its tab id, role, kind, total, taxes, area, and the job's two tax answers
   *    proposal_lump_sum, proposal_sales_tax, proposal_remodel_tax   the sum of the BASE sections (an option-only
   *                        tab, Seal or Leveling, is never in it)
   *    proposal_taxable, proposal_remodel_on   the job's two answers (conditions.taxable, conditions.remodel_tax)
   *    sheet_area          the base sections' areas, summed key by key
   *    cost_snapshot       the base sections' costs (sub-total, taxes, fees and bond) and man hours
   *    phase_price         0: v2 has no phase surcharge, and the proposal falls back to its own default
   *    tab_opts            ONLY when the bid has an option: the draft's own tab_opts, with an entry added (is_option and
   *                        show on, price_mode total) for every option section the draft holds none for. The proposal
   *                        side prints a priced tab as an option only when this says so; an entry already there is kept
   *    computed_bid        { lump_sum, price_per_sf, polish_sf, full_bid } as above, for the combined base
   *  A section that cannot price (a profile rev that has moved, a rate that cannot be read) is listed with a null
   *  total and the reason, and takes the combined price with it: there is NO price rather than a wrong one, so
   *  computed_bid, the lump sum and the tax figures are null. */
  /** The height of the first cove the base sections buy, in inches as text ("4", "6", "8"), read off the cove
   *  system's id (`wb-epoxy-cove-epoxy-4in`, `wb-epoxy-cove-wr-6in-plus-cap`, ...), or "" for none. Only an LF row that
   *  is on counts. */
  function coveHeightOf(entries) {
    for (var i = 0; i < entries.length; i++) {
      var rows = (entries[i].section && entries[i].section.takeoff) || [];
      for (var j = 0; j < rows.length; j++) {
        var r = rows[j];
        if (!r || r.unit !== "LF" || !rowOn(r) || !(num(r.measurement) > 0)) continue;
        var m = /^wb-epoxy-cove-[a-z]+-(\d+)in(?:-|$)/.exec(String(r.assembly_id || ""));
        if (m) return m[1];
      }
    }
    return "";
  }

  function composePricingSnapshot(model, ctx) {
    if (!isObject(model)) throw new Error("composePricingSnapshot needs the model it is pricing");
    if (!isObject(ctx)) throw new Error("composePricingSnapshot needs ctx, the bids the page priced");
    var entries = sectionsOf(model);
    var bidOf = function (e) {
      var b = e.root ? ctx.bid : (isObject(ctx.bids) && has.call(ctx.bids, e.tab) ? ctx.bids[e.tab] : undefined);
      if (!isObject(b)) {
        throw new Error("a save needs ctx." + (e.root ? "bid" : "bids[" + JSON.stringify(e.tab) + "]") + ", the " +
          (e.root ? "markupChain result" : "priced bid") + " of the " + e.tab + " section: a save with no price is a save of zero");
      }
      return b;
    };
    var live = entries.filter(function (e) { return e.kind !== "off"; });
    var bids = live.map(function (e) { return { e: e, b: bidOf(e) }; });
    var rootLive = live.length && live[0].root ? bids[0].b : null;
    var root = entries[0];

    // the model, with every section's totals stamped from its bid
    var stamped = Object.assign(copyInto({}, model), rootLive ? { totals: rootLive } : {});
    if (isObject(model.tabs)) {
      stamped.tabs = Object.fromEntries(entries.filter(function (e) { return !e.root; }).map(function (e) {
        var hit = bids.filter(function (x) { return x.e.tab === e.tab; })[0];
        return [e.tab, hit ? Object.assign(copyInto({}, e.section), { totals: hit.b }) : e.section];
      }));
    }

    var out = { polish_estimate: stamped };
    if (rootLive) {
      out.polish_sf = rootLive.sf > 0 ? rootLive.sf : measuredSf(model.takeoff);
      out.polish_2_sf = "";
    }
    // A bid whose model holds a `tabs` object is never "single", even when its last option was just removed: the
    // draft still holds the price snapshot that option was in (priced_tabs, the lump sum), and only the complete set
    // below overwrites it. A bid that never had a second section has no `tabs` and writes what it always wrote.
    var single = entries.length === 1 && root.kind === "base" && !isObject(model.tabs);
    var rootComputed = rootLive ? {
      lump_sum: rootLive.total, price_per_sf: rootLive.per_sf, polish_sf: rootLive.sf,
      full_bid: { total_base_bid: rootLive.total, sales_tax: rootLive.sales_tax, remodel_tax: rootLive.remodel_tax }
    } : null;
    if (single) { out.computed_bid = rootComputed; return out; }

    // ── more than one section: the complete derived set ──
    var cond = isObject(model.conditions) ? model.conditions : {};
    var priceable = function (b) { return b.priceable !== false; };
    var base = bids.filter(function (x) { return isBaseEntry(x.e); });
    var ok = base.length > 0 && base.every(function (x) { return priceable(x.b); });
    var sums = ok ? engine.combine(base.map(function (x) { return { layout: x.e.layout, result: x.b }; })).sums : null;
    var area = {};
    base.forEach(function (x) {
      var f = areaFields(x.e);
      Object.keys(f).forEach(function (k) { area = Object.assign({}, area, Object.fromEntries([[k, num(area[k]) + f[k]]])); });
    });
    var areaTotal = base.reduce(function (t, x) { return t + takeoffSf(x.e.section.takeoff); }, 0);

    out.computed_bid = ok ? {
      lump_sum: sums.total, price_per_sf: areaTotal > 0 ? sums.total / areaTotal : null,
      polish_sf: rootLive ? rootLive.sf : 0,
      full_bid: { total_base_bid: sums.total, sales_tax: sums.sales_tax, remodel_tax: sums.remodel_tax }
    } : null;
    out.priced_tabs = bids.map(function (x) {
      var b = x.b, good = priceable(b);
      return Object.assign({
        id: x.e.tab, name: x.e.label, role: x.e.role, kind: x.e.kind,
        total: good ? b.total : null, sales_tax: good ? b.sales_tax : null, remodel: good ? b.remodel_tax : null,
        system_desc: systemDesc(x.e.section, x.e), notes_auto: [],
        sf: areaFields(x.e), sys_names: [],
        taxable: !!cond.taxable, remodel_on: !!cond.remodel_tax, v2: true
      }, good ? {} : { unpriceable: String(b.reason || "") });
    });
    // THE BASE'S ID, for the Proposal step (Sheets phase 1): the one base's own id, and null for a combined base (Epoxy and
    // Polish together), which the proposal tells by role. The proposal reads `base_tab_id` to know which priced tab IS the
    // base, so a copy or a second sheet made the base is named here, and a bid with no base names none.
    out.base_tab_id = base.length === 1 ? base[0].e.tab : null;
    out.proposal_lump_sum = ok ? sums.total : null;
    out.proposal_sales_tax = ok ? sums.sales_tax : null;
    out.proposal_remodel_tax = ok ? sums.remodel_tax : null;
    out.proposal_taxable = !!cond.taxable;
    out.proposal_remodel_on = !!cond.remodel_tax;
    // THE COVE'S HEIGHT, as the base's cove system names it (2026-10-16: a 4" cove printed as 6" on the proposal, because
    // the proposal reads `cove_height`, which a v2 bid never fills, and falls back to 6). "" when the base has no cove.
    out.cove_height_v2 = coveHeightOf(base.map(function (x) { return x.e; }));
    out.sheet_area = area;
    out.cost_snapshot = ok ? {
      costs: sums.sub_total + sums.taxes + sums.fees_and_bond,
      man_hours: Math.round(base.reduce(function (t, x) { return t + sectionManHours(x.e.section); }, 0))
    } : { costs: 0, man_hours: 0 };
    out.phase_price = 0;
    // AN OPTION IS AN OPTION ON THE PROPOSAL SIDE ONLY WHEN THE DRAFT SAYS SO (tab_opts[id].is_option, the key the
    // Estimate step's "add as option" tick and the Proposal step's sidebar both write; proposal-review.js reads it to
    // put the section under "Options & Unit Prices"). A v2 option has no tick on this page, so the first save of it
    // writes the entry with the option on and shown, as a total (its own price). An entry the draft already holds is
    // never rewritten, so what the estimator did in the Proposal step's sidebar (hide it, turn it into a deduction,
    // type its words) survives the next save of this page. `ctx.tabOpts` is the draft's own tab_opts.
    // Every option the bid holds, a Copy<N> one and the root as an option included, has an entry here. What the model WRITES is
    // always a total (optionSettings), so a Seal option, which has no Add or Deduct, is never written as one.
    var optionIds = bids.filter(function (x) { return x.e.kind === "option"; }).map(function (x) { return x.e.tab; });
    if (optionIds.length) {
      var heldOpts = isObject(ctx.tabOpts) ? ctx.tabOpts : {};
      var opts = copyInto({}, heldOpts);
      optionIds.forEach(function (id) {
        if (has.call(heldOpts, id)) return;
        opts = Object.assign({}, opts, Object.fromEntries([[id, optionSettings(true)]]));
      });
      out.tab_opts = opts;
    }
    return out;
  }

  /** IS THE PRICE THE DRAFT HOLDS BEHIND THE ROWS THE MODEL HOLDS? True when a section that is part of the bid was
   *  priced on another floor than its takeoff now says, so the page should save once and let computed_bid, the
   *  stamped totals and priced_tabs come from the model as it is.
   *
   *  WHY IT EXISTS. The intake's boxes edit the takeoff rows (patchModel's `boxes`) but cannot reprice, because the
   *  library lives on the estimate page. So after a figure is typed there, the draft's snapshot still says the old
   *  floor. This is asked for EVERY live section: the root's snapshot is polish_sf and computed_bid.polish_sf, any
   *  other section's is its entry in priced_tabs (the area and cove it was priced on). A section the draft holds no
   *  snapshot for is not behind (a draft that never had one writes nothing on open), and neither is one whose
   *  snapshot agrees, so a plain reopen writes nothing. Reads only; false for a model whose sections cannot be read. */
  function snapshotBehind(model, state) {
    if (!isObject(model) || !isObject(state)) return false;
    var list;
    try { list = activeSections(model); } catch (err) { return false; }
    var snap = isObject(state.computed_bid) ? state.computed_bid : null;
    var priced = state.priced_tabs instanceof Array ? state.priced_tabs : [];
    return list.some(function (e) {
      if (e.root) {
        var tk = takeoffSf(e.section.takeoff);
        var snapSf = snap ? num(snap.polish_sf) : 0;
        return tk > 0 && (tk !== num(state.polish_sf) || (snapSf > 0 && snapSf !== tk));
      }
      var held = priced.filter(function (x) { return isObject(x) && x.id === e.tab; })[0];
      if (!held || !isObject(held.sf)) return false;
      var now = areaFields(e);
      return Object.keys(now).some(function (k) { return has.call(held.sf, k) && num(held.sf[k]) !== now[k]; });
    });
  }

  /** The proposal's own settings for a section that is an option (tab_opts[id]): the keys the Estimate step's tick and the
   *  Proposal step's sidebar both write. `on` is whether the option prints on the proposal (is_option); it always starts
   *  shown, as a total, with its system named and no difference line. */
  function optionSettings(on) {
    return { show_system: true, show_diff: false, is_option: !!on, show: true, price_mode: "total" };
  }

  /** The strip that switches between a bid's sections, or "" when there is only one (every bid today), so a
   *  single-section estimate looks exactly as it did. One button per section, naming it, its kind and its price;
   *  `active` is the tab id on show and `bids` the { tabId: bid } the page priced (the root's under its own tab
   *  id). The page's delegated click handler reads `data-section-tab`. */
  function sectionSwitcherHtml(model, active, bids, opts) {
    var list = sectionsOf(model);
    // `opts.skipOff`: leave out a section that is not part of the bid (an Epoxy job's Polish root), so the strip
    // lists only what the bid is made of. Without it every section is listed, as it always was.
    if (opts && opts.skipOff) list = list.filter(function (e) { return e.kind !== "off"; });
    if (list.length < 2) return "";
    var esc = function (s) {
      return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    };
    return list.map(function (e) {
      var b = isObject(bids) && has.call(bids, e.tab) ? bids[e.tab] : null;
      var price = b && b.priceable !== false && b.total ? money(b.total) : "no price";
      var kind = e.kind === "base" ? "" : (e.kind === "option" ? " (option)" : " (off)");
      return '<button type="button" data-section-tab="' + esc(e.tab) + '" aria-current="' +
        (e.tab === active ? "true" : "false") + '">' + esc(e.label) + esc(kind) + " · " + esc(price) + "</button>";
    }).join("");
  }
  // ══ THE SHEETS PANEL (Sheets phase 3): what the floating widget on the estimate page draws ═══════════════════
  //
  // sectionSwitcherHtml above is the strip the panel replaced on the page. These are PURE, like it: they answer markup and
  // change nothing, so the page's handlers and a test read the very same text. The page hands in a `view`:
  //
  //   open       the sheet on show (a section id)            bids       { sectionId: bid } the page priced
  //   opts       the draft's tab_opts                        sf         the area a new sheet starts from, or 0
  //   confirm    { row, ids } a base change waiting for its yes, or null
  //   armed      the sheet whose Delete was pressed once     renaming   the sheet being renamed, with `draft` and `error`
  //   descOpen   { sectionId: true } the description boxes that are open
  //   pick       the "Add a sheet" menu is open              busy       a sheet is being added (the library is being read)
  //   icon       function (name, size) -> svg markup, or none   sysDesc    function (sectionId) -> what the option prints now
  //   notice     { at, text }: why a press was refused, drawn under the control that was pressed (at: a section id, or "add")
  //
  // EVERY CONTROL CARRIES A data- ATTRIBUTE THE PAGE'S ONE CLICK HANDLER READS: data-section-tab (open it), data-sh-base (the
  // radio), data-sh-act with data-sh-tab (on, desc, copy, rename, rename-save, rename-cancel, delete, base-yes, base-no,
  // add-menu, add-close, add with data-sh-sheet), data-sh-mode (the Total / Add or Deduct pair), data-sh-desc and data-sh-name (the
  // two boxes). data-sh-key names a control so the page can put the caret back on it after a repaint.

  /** THE PAIR A COMBINED BASE WOULD BE, as [epoxyId, polishId], or null when the bid has no Epoxy or no Polish sheet that is part
   *  of it. The pair the bid already has when it is combined; otherwise the Epoxy and the Polish sheet a job type would take (one
   *  that already is a base, else the sheet's own, else the first copy). Never throws. */
  function combinedPair(model) {
    var entries = readableSections(model);
    if (entries === null) return null;
    var bases = entries.filter(isBaseEntry);
    if (baseTypeOf(entries) === "combo" && bases.length === 2) {
      return bases.slice().sort(function (a, b) { return a.role === "epoxy" ? -1 : (b.role === "epoxy" ? 1 : 0); })
        .map(function (e) { return e.tab; });
    }
    var live = entries.filter(function (e) { return e.kind !== "off"; });
    var one = function (role) {
      var mine = live.filter(function (e) { return e.role === role; });
      return mine.length ? preferredSection(mine) : null;
    };
    var epoxy = one("epoxy"), polish = one("polish");
    return epoxy && polish ? [epoxy.tab, polish.tab] : null;
  }

  /** Is this option ON the proposal? tab_opts says so when it is an option and not hidden. An option the draft holds no entry for
   *  yet is ON: the first save writes its entry that way (composePricingSnapshot). */
  function optionIsOn(opts, id) {
    var o = isObject(opts) && has.call(opts, id) && isObject(opts[id]) ? opts[id] : null;
    return o ? (o.is_option === true && o.show !== false) : true;
  }

  /** The draft's side of one sheet's proposal settings: a patch for TW.setState that lays `change` over tab_opts[id] (made as
   *  optionSettings(true) when the draft holds none yet). A NEW object; `state` is not touched. */
  function tabOptPatch(state, id, change) {
    var st = isObject(state) ? state : {};
    var held = isObject(st.tab_opts) ? st.tab_opts : {};
    var cur = has.call(held, id) && isObject(held[id]) ? held[id] : optionSettings(true);
    return { tab_opts: Object.assign({}, copyInto({}, held), Object.fromEntries([[id, Object.assign({}, cur, change)]])) };
  }

  /** A SEAL OPTION IS A TOTAL, NEVER AN ADD OR DEDUCT: a patch for TW.setState that sets tab_opts[id].price_mode back to "total" for
   *  every option-only sheet (Seal and its copies) whose entry says "deduct", and {} when none does (a NEW object; `state` is not
   *  touched). The panel offers a Seal sheet no Total / Add or Deduct pair and says it is priced as a total, but the Proposal step's
   *  own "Price as" box can leave one on Add / Deduct, and the proposal prints what the draft says: the panel would state one
   *  thing and the customer's document another. Everything else the entry holds is kept. */
  function optionOnlyTotalPatch(model, state) {
    var st = isObject(state) ? state : {};
    if (!isObject(st.tab_opts)) return {};
    var entries;
    try { entries = sectionsOf(model); } catch (err) { return {}; }
    var next = null;
    entries.forEach(function (e) {
      var held = has.call(st.tab_opts, e.tab) && isObject(st.tab_opts[e.tab]) ? st.tab_opts[e.tab] : null;
      if (!held || held.price_mode !== "deduct" || !types.tab(types.tabOfSheet(e.sheet)).optionOnly) return;
      next = Object.assign({}, next || copyInto({}, st.tab_opts), Object.fromEntries([[e.tab, Object.assign({}, held, { price_mode: "total" })]]));
    });
    return next ? { tab_opts: next } : {};
  }

  // WHAT THE BASE RADIO MEANS, said on the radio itself (its title and its accessible name). It was a legend line under the
  // sheet bar ("marks the base bid, which sets the lump sum and the job type") until 2026-10-20, when the bar moved into the
  // page's sticky head, where every line is height that stays on screen.
  var BASE_MEANS = "sets the lump sum and the job type";
  var JOB_WORDS = { polish: "Polish", epoxy: "Epoxy", gyp: "Gyp", combo: "Combo" };
  function jobWord(jobType) { return has.call(JOB_WORDS, jobType) ? JOB_WORDS[jobType] : String(jobType == null ? "" : jobType); }
  function anWord(w) { return /^[AEIOU]/i.test(w) ? "an" : "a"; }
  function escHtml(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  /** WHAT THE PANEL SAYS ABOUT EACH SHEET, worked out once for the panel and the "Open sheet" line. Every sheet that is part of
   *  the bid, as { e, base, inBase, opt, optOnly, canBase, price, on, mode, typeLabel, lead, figure, off }; the base bid(s)' ids
   *  and total; the combined pair and its total. A bid whose sections cannot be read is the root alone, with `unreadable` set. */
  function sheetsFacts(model, view) {
    var v = isObject(view) ? view : {};
    var unreadable = false, entries;
    try { entries = sectionsOf(model); } catch (err) {
      unreadable = true;
      entries = [{ tab: ROOT_TAB, sheet: ROOT_TAB, label: rootLabel(model), source: null, root: true, section: model,
                   layout: "polish", kind: "base", profile: "", role: "polish" }];
    }
    var list = entries.filter(function (e) { return e.kind !== "off"; });
    var baseIds = entries.filter(isBaseEntry).map(function (e) { return e.tab; });
    var priceOf = function (id) {
      var b = isObject(v.bids) && has.call(v.bids, id) ? v.bids[id] : null;
      return b && b.priceable !== false && num(b.total) > 0 ? num(b.total) : null;
    };
    var sumOf = function (ids) {
      var t = 0;
      for (var i = 0; i < ids.length; i++) { var p = priceOf(ids[i]); if (p === null) return null; t += p; }
      return ids.length ? t : null;
    };
    var baseTotal = sumOf(baseIds);
    var pair = unreadable ? null : combinedPair(model);
    var rows = list.map(function (e) {
      var rec = types.tab(types.tabOfSheet(e.sheet));
      var base = baseIds.length === 1 && baseIds[0] === e.tab;
      var inBase = baseIds.length === 2 && baseIds.indexOf(e.tab) >= 0;
      var opt = !base && !inBase;
      var optOnly = !!rec.optionOnly;
      var price = priceOf(e.tab);
      var on = opt && optionIsOn(v.opts, e.tab);
      var held = isObject(v.opts) && has.call(v.opts, e.tab) && isObject(v.opts[e.tab]) ? v.opts[e.tab] : {};
      var mode = !optOnly && held.price_mode === "deduct" ? "deduct" : "total";
      var lead = "", figure = "", off = false;
      if (opt) {
        if (price === null) { lead = "Option, no price yet"; off = true; }
        else if (!on) { lead = "Not on the proposal"; off = true; }
        else if (mode === "deduct") {
          // The proposal's own rule (proposal-review.js): the option's total less the base's, cheaper is a Deduct.
          if (baseTotal === null) lead = "Option, add or deduct";
          else {
            var d = Math.round(price) - Math.round(baseTotal);
            lead = "Option,";
            figure = d < 0 ? "Deduct (" + money(-d) + ")" : (d > 0 ? "Add " + money(d) : "No change");
          }
        } else lead = "Option, total";
      }
      return { e: e, base: base, inBase: inBase, opt: opt, optOnly: optOnly, canBase: !optOnly, price: price, on: on, mode: mode,
               desc: typeof held.desc === "string" ? held.desc : "", typeLabel: e.role === "seal" ? e.sheet : rec.label,
               lead: lead, figure: figure, off: off };
    });
    return { view: v, unreadable: unreadable, entries: entries, rows: rows, baseIds: baseIds, baseTotal: baseTotal,
             pair: pair, pairTotal: pair ? sumOf(pair) : null };
  }

  /** What a base change says before it is made: { title, body } for pressing `ids` (one sheet, or the combined pair). The base
   *  the bid has now stays ON the proposal as an option, priced as a total, which is said where it is asked. */
  function baseChangeWords(model, ids) {
    var entries = sectionsOf(model);
    var nameOf = function (id) { return entries.filter(function (e) { return e.tab === id; })[0]; };
    var now = baseOf(model);
    var combined = ids.length === 2;
    var next = combined ? "combo" : (nameOf(ids[0]) && types.isJobType(nameOf(ids[0]).role) ? nameOf(ids[0]).role : null);
    var leaving = entries.filter(function (e) { return isBaseEntry(e) && ids.indexOf(e.tab) < 0; })
      .map(function (e) { return e.label; });
    var title = "Make " + (combined ? "Epoxy + Polish (combined)" : nameOf(ids[0]).label) + " the base bid?";
    var word = jobWord(next);
    var body = next === now.jobType
      ? "The job stays " + word + ". "
      : "The job becomes " + anWord(word) + " " + word + " job and the proposal switches to the " + word + " format. ";
    if (leaving.length) body += leaving.join(" and ") + (leaving.length > 1 ? " become options" : " becomes an option") +
      " on the proposal, priced as a total.";
    return { title: title, body: body.trim() };
  }

  /** The "Sheets" bar, as the markup inside its element: ONE strip of tabs (a sheet each, like the worksheet tabs of the live
   *  estimate) and, under it, the bar of the sheet that is open. See the block comment above for `view`.
   *
   *  Row 1, the strip: the base-bid radio, the name and the price of each sheet in sheetsFacts order, the combined Epoxy + Polish
   *  choice when the bid has the pair, and "+ Add sheet" last. Row 2, the open sheet only: what it is (the base, or the option and
   *  its figure) and every control it has. A base change waiting for its yes shows between the two, whichever sheet it is for. */
  function sheetsPanelHtml(model, view) {
    var f = sheetsFacts(model, view);
    var v = f.view;
    var ic = typeof v.icon === "function" ? v.icon : function () { return ""; };
    var key = function (id, what) { return ' data-sh-key="' + escHtml(id + "|" + what) + '"'; };
    var h = "";
    if (f.unreadable) {
      h += '<div class="sh-warn" role="alert">' + ic("warning", 14) + '<span>This bid\'s other sheets can\'t be read, so only ' +
        escHtml(rootLabel(model)) + ' shows. ' + escHtml(rootLabel(model)) + ' still prices and saves. Reload to try again.</span></div>';
    }

    // ROW 1: the tabs.
    var tabs = [];
    if (f.pair && !f.unreadable) {
      var combined = f.baseIds.length === 2;
      tabs.push('<li class="sh sh-tab combined' + (combined ? " base" : "") + '" data-sh-row="combined" role="presentation">' +
        '<span class="sh-slot"><input type="radio" class="sh-radio" name="sh-base" data-sh-base="combined"' + key("combined", "base") +
        (combined ? " checked" : "") + ' aria-label="Make Epoxy + Polish (combined) the base bid, which ' + BASE_MEANS +
        '" title="Base bid: Epoxy and Polish together. It ' + BASE_MEANS + '"></span>' +
        '<span class="sh-name static" title="Epoxy and Polish together"><span class="sh-nm">Epoxy + Polish</span><span class="sh-price' +
        (f.pairTotal === null ? " none" : "") + '">' + (f.pairTotal === null ? "no price" : money(f.pairTotal)) + '</span></span></li>');
    }
    f.rows.forEach(function (r) { tabs.push(tabHtml(r)); });
    // "+ Add sheet" STAYS IN THE STRIP while its list is open (browser walk, 2026-10-20: it vanished under the cursor). Open, it
    // closes the list again, which is what the list's own close button does.
    tabs.push('<li class="sh-addli" role="presentation"><button type="button" class="sh-addbtn' + (v.pick ? " on" : "") +
      '" data-sh-act="' + (v.pick ? "add-close" : "add-menu") + '"' + key("add", "menu") +
      ' aria-expanded="' + (v.pick ? "true" : "false") + '"' + (f.unreadable ? " disabled" : "") + '>' + ic("plus", 14) + 'Add sheet</button></li>');
    var strip = '<div class="sh-strip" data-sh-strip><ul class="sh-list" role="tablist" aria-label="Sheets on this bid">' + tabs.join("") + '</ul></div>';

    // The add picker opens just under the strip, IN THE FLOW: it pushes the open sheet's bar down and nothing is laid over it.
    var add = "";
    // Why a sheet could not be added, and why adding is off, sit in the flow under the strip too, never inside the picker's box
    // (which is only the list). The page's own alert is above the fold of a long page.
    var flow = "";
    if (isObject(v.notice) && v.notice.at === "add") flow += noticeHtml(v.notice);
    if (f.unreadable) flow += '<p class="sh-cap">Adding a sheet is off until the other sheets can be read.</p>';
    if (v.pick) {
      // One row a type. Gyp's five presets are one product (the Gyp card on the Material step switches between them), so the menu
      // lists "Gyp" once and adds the first preset; Seal and Seal (+Jnts) are two different sheets and are both listed.
      var rank = { polish: 0, epoxy: 1, gyp: 2, seal: 3 };
      var seenGyp = false;
      var kinds = sheetsToAdd().map(function (s, i) { return { s: s, i: i, role: types.tab(types.tabOfSheet(s)).role }; })
        .filter(function (k) { if (k.role !== "gyp") return true; var first = !seenGyp; seenGyp = true; return first; })
        .sort(function (a, b) { return (rank[a.role] - rank[b.role]) || (a.i - b.i); });
      add += '<div class="sh-pick" role="group" aria-label="Add a sheet"><div class="sh-pick-h">Add a sheet' +
        '<button type="button" class="x" aria-label="Close" data-sh-act="add-close"' + key("add", "close") + '>' + ic("x", 14) +
        '</button></div><p class="sh-cap">' + (num(v.sf) > 0 ? "It starts from this bid's " + fmtSf(num(v.sf)) + " SF."
          : "It starts empty. Measure it on its Material step.") + '</p><ul class="sh-pick-l">';
      kinds.forEach(function (k) {
        var only = types.tab(types.tabOfSheet(k.s)).optionOnly;
        add += '<li><button type="button" class="sh-pick-row" data-sh-act="add" data-sh-sheet="' + escHtml(k.s) + '"' +
          key("add", k.s) + (v.busy ? " disabled" : "") + '><span>' + escHtml(k.role === "gyp" ? types.tab(types.tabOfSheet(k.s)).label : k.s) + '</span>' +
          (only ? '<span class="pill">Option only</span>' : "") + '</button></li>';
      });
      // A sheet type the tool does not price yet is listed so nobody wonders where it went.
      types.tabKeys().forEach(function (tk) {
        var rec = types.tab(tk);
        if (rec.optionOnly && rec.offered !== true) {
          add += '<li><button type="button" class="sh-pick-row" disabled><span>' + escHtml(rec.label) +
            '</span><span class="pill">Coming</span></button></li>';
        }
      });
      add += '</ul></div>';
    }
    h += '<div class="sh-stripwrap">' + strip + (add ? '<div class="sh-add">' + add + '</div>' : "") + '</div>' +
      (flow ? '<div class="sh-flow">' + flow + '</div>' : "");

    // A base change waiting for its yes, whichever tab it is for.
    if (isObject(v.confirm)) h += confirmHtml(model, v);

    // ROW 2: the open sheet.
    f.rows.forEach(function (r, i) { if (r.e.tab === v.open) h += openHtml(r, i); });

    // NO LEGEND LINE (2026-10-20). The bar lives in the page's sticky head, so a footer line is height that never scrolls away: what the
    // base radio means is on the radio (BASE_MEANS). The one note that stays is about copies, and it is drawn only when there is one.
    if (f.rows.some(function (r) { return COPY_ID.test(r.e.tab); })) {
      h += '<p class="sh-hint">Copies print on the proposal. The Excel download does not include them.</p>';
    }
    if (f.rows.length === 1 && !f.unreadable) {
      h += '<p class="sh-empty">Add a sheet to price an option. Options never change the lump sum.</p>';
    }
    return h;

    /** Why a press was refused, in the model's own words, as a line of the panel (the page sets view.notice = { at, text }). */
    function noticeHtml(n) {
      return '<p class="sh-note warn" role="alert" data-sh-notice>' + escHtml(n.text) + '</p>';
    }

    function confirmHtml(m, view2) {
      var words;
      try { words = baseChangeWords(m, view2.confirm.ids); } catch (err) { return ""; }
      return '<div class="sh-confirm" role="group" aria-label="Confirm the base bid" data-sh-confirm="' + escHtml(view2.confirm.row) +
        '"><b>' + escHtml(words.title) + '</b><p>' +
        escHtml(words.body) + '</p><div class="sh-btns"><button type="button" class="btn sm" data-sh-act="base-yes"' +
        key("confirm", "yes") + '>Make it the base</button><button type="button" class="btn ghost sm" data-sh-act="base-no"' +
        key("confirm", "no") + '>Cancel</button></div></div>';
    }

    /** One tab of the strip: the base radio (none for an option-only Seal sheet), the name, and the price. */
    function tabHtml(r) {
      var e = r.e, t = e.tab, open = t === v.open, ren = open && v.renaming === t;
      var s = '<li class="sh sh-tab' + (open ? " open" : "") + (r.base || r.inBase ? " base" : "") + '" data-sh-row="' + escHtml(t) + '" role="presentation"' + (open ? ' data-sh-cur="1"' : "") + '>' +
        '<span class="sh-slot"' + (r.canBase ? "" : ' title="Seal sheets price as options only, never as the base bid"') + '>' +
        (r.canBase ? '<input type="radio" class="sh-radio" name="sh-base" data-sh-base="' + escHtml(t) + '"' + key(t, "base") +
          (r.base ? " checked" : "") + ' aria-label="Make ' + escHtml(e.label) + ' the base bid, which ' + BASE_MEANS +
          '" title="Base bid: ' + BASE_MEANS + '">' : "") + '</span>';
      if (ren) {
        s += '<input type="text" class="sh-ren-in" data-sh-name="' + escHtml(t) + '"' + key(t, "name") + ' value="' +
          escHtml(v.draft) + '" aria-label="Sheet name">';
      } else {
        s += '<button type="button" class="sh-name" role="tab" aria-selected="' + (open ? "true" : "false") + '" data-section-tab="' +
          escHtml(t) + '"' + key(t, "open") + ' aria-current="' + (open ? "true" : "false") + '"><span class="sh-nm">' + escHtml(e.label) +
          '</span><span class="sh-price' + (r.price === null ? " none" : "") + '">' + (r.price === null ? "no price" : money(r.price)) + '</span>' +
          // THE BASE SAYS SO IN WORDS (browser walk, 2026-10-20): its red edge read as a second selected tab.
          (r.base || r.inBase ? '<span class="sh-basetag">Base</span>' : "") + '</button>';
      }
      return s + '</li>';
    }

    /** The bar under the strip: what the open sheet is, and every control it has. */
    function openHtml(r, i) {
      var e = r.e, t = e.tab, ren = v.renaming === t;
      var tabAttr = ' data-sh-tab="' + escHtml(t) + '"';
      var s = '<div class="sh-open" data-sh-open="' + escHtml(t) + '" role="tabpanel"><div class="sh-meta"><span class="sh-type">' +
        escHtml(String(r.typeLabel).toUpperCase()) + '</span>';
      if (r.base) s += '<span class="pill base">Base bid</span>';
      else if (r.inBase) s += '<span class="pill">In the base bid</span>';
      else s += '<span class="sh-sum' + (r.off ? " off" : "") + '">' + escHtml(r.lead) +
        (r.figure ? ' <b>' + escHtml(r.figure) + '</b>' : "") + '</span>';
      s += '</div><div class="sh-body">';
      if (ren) {
        s += '<div class="sh-btns"><button type="button" class="btn sm" data-sh-act="rename-save"' + tabAttr + key(t, "save") +
          '>Save name</button><button type="button" class="btn ghost sm" data-sh-act="rename-cancel"' + tabAttr + key(t, "cancel") +
          '>Cancel</button></div><p class="sh-note">Enter saves, Esc cancels. The name is only a label: nothing is repriced.</p>';
        if (v.error) s += '<p class="sh-note warn" role="alert" data-sh-error>' + escHtml(v.error) + '</p>';
      } else {
        if (r.opt) {
          s += '<button type="button" class="mw-sw' + (r.on ? " on" : "") + '" role="switch" aria-checked="' + (r.on ? "true" : "false") +
            '" data-sh-act="on"' + tabAttr + key(t, "on") + '><span class="track"></span>On the proposal as an option</button>' +
            '<div class="sh-ctl' + (r.on ? "" : " inert") + '">';
          if (!r.optOnly) {
            s += '<div class="sh-mode"><span class="sh-lbl">Price as</span><span class="seg" role="radiogroup" aria-label="Price as">' +
              '<input type="radio" id="sh-m' + i + '-t" name="sh-m' + i + '" data-sh-mode="' + escHtml(t) + '" value="total"' +
              key(t, "mode-total") + (r.mode === "total" ? " checked" : "") + '><label for="sh-m' + i + '-t">Total</label>' +
              '<input type="radio" id="sh-m' + i + '-d" name="sh-m' + i + '" data-sh-mode="' + escHtml(t) + '" value="deduct"' +
              key(t, "mode-deduct") + (r.mode === "deduct" ? " checked" : "") + '><label for="sh-m' + i + '-d">Add / Deduct</label>' +
              '</span></div>';
          }
          var dOpen = isObject(v.descOpen) && v.descOpen[t] === true;
          s += '<div class="sh-desc"><button type="button" class="sh-desc-t" data-sh-act="desc"' + tabAttr + key(t, "desc") +
            ' aria-expanded="' + (dOpen ? "true" : "false") + '">' + ic("chev-right", 12) + 'Description <span class="opt">optional</span></button>';
          if (dOpen) {
            var ph = typeof v.sysDesc === "function" ? v.sysDesc(t) : "";
            s += '<textarea class="sh-desc-in" rows="3" maxlength="400" data-sh-desc="' + escHtml(t) + '"' + key(t, "desc-box") +
              ' aria-label="Description" placeholder="' + escHtml(ph) + '">' + escHtml(r.desc) + '</textarea>' +
              '<p class="sh-cap">Prints as the option line. Left empty, the grey text prints.</p>';
          } else if (r.desc) {
            s += '<span class="sh-desc-prev">' + escHtml(r.desc) + '</span>';
          }
          s += '</div></div>';
          if (r.optOnly) s += '<p class="sh-note">Seal sheets are options only. They are priced as a total and can\'t be the base bid.</p>';
        }
        var locked = r.base || r.inBase || e.root;
        var armed = v.armed === t && !locked;
        s += '<div class="sh-acts"><button type="button" class="kindpick" data-sh-act="copy"' + tabAttr + key(t, "copy") + '>' +
          ic("copy", 12) + 'Copy</button><button type="button" class="kindpick" data-sh-act="rename"' + tabAttr + key(t, "rename") + '>' +
          ic("pencil", 12) + 'Rename</button><button type="button" class="kindpick' + (armed ? " armed" : "") +
          '" data-sh-act="delete"' + tabAttr + key(t, "delete") + (locked ? " disabled" : "") + '>' + ic("trash", 12) +
          (armed ? "Click again to delete" : "Delete") + '</button></div>';
        if (r.base) s += '<p class="sh-note">The base bid can\'t be deleted. Make another sheet the base first.</p>';
        else if (r.inBase) s += '<p class="sh-note">' + escHtml(e.label) + ' is part of the base bid, so it can\'t be deleted. Pick a different base first.</p>';
        else if (e.root) s += '<p class="sh-note">' + escHtml(e.label) + ' is where this bid starts, so it can\'t be deleted. Switch it off above to keep it off the proposal.</p>';
        if (armed) s += '<p class="sh-note warn">Deletes ' + escHtml(e.label) + ' and everything typed on it.</p>';
        if (isObject(v.notice) && v.notice.at === t) s += noticeHtml(v.notice);
      }
      return s + '</div></div>';
    }
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
      if (!filledIn(row.rate) && !(laborRateOf(row, prevailingApplied(m)) > 0)) missing.push("rate");
      if (missing.length > 0 && missing.length < 3) {
        var which = missing.length === 1 ? missing[0]
          : missing.slice(0, -1).join(", ") + " and " + missing[missing.length - 1];
        out.push("Add the " + which + " for " + (row.label || row.id || ("row " + (j + 1))));
      }
    }

    return out;
  }

  return {
    num: num, roundUp: roundUp, copyInto: copyInto,
    money: money, money2: money2, pct: pct, fmtSf: fmtSf,
    HOURS_PER_DAY: HOURS_PER_DAY, RATES: RATES, GP_BANDS: GP_BANDS, DYE_COATS: DYE_COATS,
    gpPct: gpPct,
    CONDITION_CELLS: CONDITION_CELLS, CARRIED_CELLS: CARRIED_CELLS, conditionCellWrites: conditionCellWrites,
    workTypeApplies: workTypeApplies, kindOfSection: kindOfSection,
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
    pinSavedBlankRates: pinSavedBlankRates, laborCost: laborCost, laborRateOf: laborRateOf, laborTotal: laborTotal, removeExistingHand: removeExistingHand,travelManDays: travelManDays,
    // The prevailing wage calculator (Labor step): the constants, the card's two figures, and the rate in force.
    PREVAILING: PREVAILING, PREVAILING_TRADES: PREVAILING_TRADES, normalizePrevailing: normalizePrevailing,
    prevailingCrewTrade: prevailingCrewTrade, newPrevailingTradeKey: newPrevailingTradeKey,
    PREVAILING_LABEL_MAX: PREVAILING_LABEL_MAX,
    prevailingTotal: prevailingTotal, entryHalfWage: entryHalfWage, prevailingApplied: prevailingApplied,
    laborFollowsPrevailing: laborFollowsPrevailing, laborRateBox: laborRateBox, rateTypedByHand: rateTypedByHand,
    ownDefaultRate: ownDefaultRate, isTravelRow: isTravelRow, setLaborRate: setLaborRate,
    // Lodging and Per Diem, the two travel costs beside Travel Labor (see travelCostsSeed).
    SHIPPED_LODGING_RATE: SHIPPED_LODGING_RATE, SHIPPED_PER_DIEM_RATE: SHIPPED_PER_DIEM_RATE,
    TRAVEL_LINE_KEYS: TRAVEL_LINE_KEYS, TRAVEL_LABEL: TRAVEL_LABEL, travelLabel: travelLabel,
    travelCostsSeed: travelCostsSeed, travelQty: travelQty, travelLineCost: travelLineCost,
    travelCosts: travelCosts, optionTravelCosts: optionTravelCosts, travelRatesFromRules: travelRatesFromRules,
    applyTravelRates: applyTravelRates, normalizeTravel: normalizeTravel,
    // Distance decides "local" (see LOCAL_MILES).
    LOCAL_MILES: LOCAL_MILES, milesOrNull: milesOrNull, distanceKey: distanceKey,
    normalizeDistance: normalizeDistance, driveHoursFor: driveHoursFor, isFarMiles: isFarMiles, applyDistance: applyDistance,
    clearDistance: clearDistance, distanceNote: distanceNote, travelHow: travelHow,
    // Travel Labor filled from the distance (2026-10-20): what it wrote, where it says so, the crew size its guys follow, and the
    // marker the estimator's typing leaves so an answer never writes into a box they have touched.
    driveHoursAreTools: driveHoursAreTools, driveHoursSource: driveHoursSource,
    driveHoursSentence: driveHoursSentence, driveHoursNote: driveHoursNote, travelGuysHint: travelGuysHint,
    followsCrew: followsCrew, crewSize: crewSize, ownCrewSize: ownCrewSize, followDistance: followDistance, markTypedByHand: markTypedByHand,
    // One drive, one Travel Labor row priced (2026-10-20 audits): what a restructure takes back, what follows the carrier (the estimator's own row), and the
    // words on a row it leaves behind.
    travelRowIsAutoFilled: travelRowIsAutoFilled, travelRowIsTheEstimators: travelRowIsTheEstimators,
    takeBackStrayTravel: takeBackStrayTravel, strayTravelNote: strayTravelNote,
    rowOn: rowOn, sliderHtml: sliderHtml, manDaysHint: manDaysHint, lodgingHint: lodgingHint,
    filledIn: filledIn,
    takeoffSf: takeoffSf, measuredSf: measuredSf, measuredSfAreas: measuredSfAreas, measuredSfRows: measuredSfRows,
    measuredSfValues: measuredSfValues, setAreaSf: setAreaSf,
    measuredLfRows: measuredLfRows, measuredLfValues: measuredLfValues, setAreaLf: setAreaLf, setGypArea: setGypArea,
    seedAreaSf: seedAreaSf,
    GYP_BUCKETS: GYP_BUCKETS, GYP_AREA_ASSEMBLIES: GYP_AREA_ASSEMBLIES,
    boxNames: boxNames, boxGroup: boxGroup, boxEntry: boxEntry, boxValue: boxValue, boxDraftValue: boxDraftValue, boxExtras: boxExtras,
    applyBoxes: applyBoxes, snapshotBehind: snapshotBehind,
    seedTakeoffSf: seedTakeoffSf,
    seedDefaultTakeoff: seedDefaultTakeoff,
    takeoffUnit: takeoffUnit,
    takeoffUnitView: takeoffUnitView,
    validTakeoffUnit: validTakeoffUnit, adoptTakeoffUnit: adoptTakeoffUnit,
    dyeCost: dyeCost, jointFillerCost: jointFillerCost,
    markupChain: markupChain, rootProfile: rootProfile, rootTooling: rootTooling, travelOpts: travelOpts,
    polishTooling: polishTooling, polishSystemOf: polishSystemOf, POLISH_TOOLING: POLISH_TOOLING, sheetNights: sheetNights,
    freshModel: freshModel, migrateModel: migrateModel, blockers: blockers,
    // The model's safety (Phase 4): the keys migrateModel owns, what the intake may state on a saved
    // model, and the ONE composition of everything the estimate page saves.
    MODEL_KEYS: MODEL_KEYS, patchModel: patchModel, buildSavePatch: buildSavePatch,
    // Sections (Phase 10): a bid priced on several workbook tabs. See the block above blockers().
    ROOT_TAB: ROOT_TAB, SECTION_KINDS: SECTION_KINDS, sectionsOf: sectionsOf, activeSections: activeSections,
    sectionOf: sectionOf, isNewSection: isNewSection, travelCarrier: travelCarrier,
    // Phase 12: the model as a panel sees one section, and the sections a job type is made of.
    ADJUST_KEYS: ADJUST_KEYS, MATERIAL_ESCALATION: MATERIAL_ESCALATION, DISCOUNT_VENDORS: DISCOUNT_VENDORS,
    normalizeAdjust: normalizeAdjust, adjustProblems: adjustProblems, polishPatchOn: polishPatchOn, hardBidRuleOn: hardBidRuleOn,
    materialOnlyAdjust: materialOnlyAdjust, chainAdjust: chainAdjust, materialAdjust: materialAdjust,
    pctFraction: pctFraction,
    SECTION_KEYS: SECTION_KEYS, sectionView: sectionView, sectionsForJob: sectionsForJob, sectionsToAdd: sectionsToAdd, sectionsLeaving: sectionsLeaving,
    moveSectionSheet: moveSectionSheet, sheetHeld: sheetHeld, sheetLabel: sheetLabel, gypAreaFields: gypAreaFields,
    priceSection: priceSection, priceTabs: priceTabs, activateSection: activateSection,
    optionsToOffer: optionsToOffer, addOption: addOption, removeOption: removeOption, optionLeftoverPatch: optionLeftoverPatch,
    // Sheets (Sheets phase 1): the bid's sheets, its base, and how a Polish section is priced.
    MAX_COPIES: MAX_COPIES, polishBid: polishBid, baseOf: baseOf, pickBase: pickBase, sheetsToAdd: sheetsToAdd,
    copySection: copySection, addSheet: addSheet, renameSection: renameSection, deleteSection: deleteSection,
    validateLabel: validateLabel, nextCopyId: nextCopyId, optionSettings: optionSettings,
    seedNewSections: seedNewSections, syncAutoGuys: syncAutoGuys, poolsPacks: poolsPacks,
    composePricingSnapshot: composePricingSnapshot, coveHeightOf: coveHeightOf, sectionSwitcherHtml: sectionSwitcherHtml,
    // Sheets phase 3: the floating panel's markup and the proposal settings it writes (pure, see the block above blockers()).
    sheetsPanelHtml: sheetsPanelHtml, baseChangeWords: baseChangeWords, combinedPair: combinedPair,
    optionIsOn: optionIsOn, tabOptPatch: tabOptPatch, optionOnlyTotalPatch: optionOnlyTotalPatch,
    // A Gyp sheet's key changes with its preset: what the draft kept under the old key follows (see moveSheetDraftPatch).
    moveSheetDraftPatch: moveSheetDraftPatch,
    takeoffLf: takeoffLf, sectionManHours: sectionManHours,
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
    libraryLaborRow: libraryLaborRow, laborRowFromLibrary: laborRowFromLibrary,
    seedLibraryLabor: seedLibraryLabor,
    travelAppliesToBid: travelAppliesToBid, travelDeclined: travelDeclined,
    LABOR_CALC_BUILTINS: LABOR_CALC_BUILTINS, dayHours: dayHours, laborCalcValues: laborCalcValues, applyLaborCalc: applyLaborCalc,
    laborCalcDiffers: laborCalcDiffers,
    laborUnstated: laborUnstated, keepLibraryRates: keepLibraryRates,
    SHIPPED_CREW: SHIPPED_CREW, isCrewId: isCrewId, shippedCrewRows: shippedCrewRows,
    shippedCrewCalc: shippedCrewCalc, withCrewFallback: withCrewFallback,
    withCrewCalcFallback: withCrewCalcFallback, legacyLabor: legacyLabor,
    dropEmptyLaborRows: dropEmptyLaborRows, crewFirst: crewFirst,
    // The company labor rate (Items & Assemblies -> Labor): read, applied to a new bid, and the fallback.
    SHIPPED_LABOR_RATE: SHIPPED_LABOR_RATE, laborRateOrShipped: laborRateOrShipped,
    laborPriceText: laborPriceText, oneOffRateText: oneOffRateText,
    laborRateFromRules: laborRateFromRules, applyLaborRate: applyLaborRate,
    stampRateDefaults: stampRateDefaults, followLaborDays: followLaborDays,
    // The Fees + Textura default (Markups -> Global `fees_textura`), read and applied to a new bid.
    feesFromRules: feesFromRules, applyFeesDefault: applyFeesDefault
  };
});
