"use strict";
/* THE PREVAILING WAGE CARD ON THE V2 LABOR STEP (Hanz, 2026-10-15), executed.
 *
 * Kyle's workbook has a small calculator on every priced tab (Polish!I47:L54): a Rate box and a Fringes box, the
 * Prevailing Wage Rate they add up to (J48 = SUM(J49:J50)) and the 1:1 "Entry" Half Wage (J53 =
 * IF((J48/2)<23,23,(J48/2))). Nothing in the sheet reads those cells. The v2 Labor step's card works the rate out
 * and sets the labor lines to it, while the job's prevailing wage switch is on and a rate is set: every labor line
 * on every section except Travel Labor and a line where the estimator typed a rate.
 *
 * Everything here EXECUTES the real js/bid-model.js and js/bid-engine.js, and the real estimate page
 * (js/polish-estimate.js, whole), booted by the page harness's own prelude. Nothing is a source assertion. One line
 * of JSON comes out and test_v2_prevailing_wage.py asserts on it, then breaks a scratch copy of the code in several
 * ways and requires the facts to change.
 *
 * Every section catches its own failure and reports it as `{error}`, so the same harness can run over a tree that
 * does not have the functions and fail as an assertion, not a crash.
 *
 * Usage: node prevailing-wage-harness.js <frontend-dir>   ->  one line of JSON
 */
const path = require("path");
const Module = require("module");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const B = require(path.join(ROOT, "js", "bid-model.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));
const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

/** The page harness's own top half (its fixtures, the DOM stub and build()), without its scenarios. */
function loadPrelude(file, exportNames) {
  const base = path.join(__dirname, file);
  const code = L.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in prevailing-wage-harness.js");
  const m = new Module(base, module);
  m.filename = base;
  m.paths = Module._nodeModulePaths(path.dirname(base));
  m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
  return m.exports;
}
const W = require(path.join(ROOT, "js", "work-types.js"));
const P = loadPrelude("polish-estimate-harness.js", ["build", "blob", "typeInto", "changeTo", "clickOn", "need", "txt"]);

const near = (a, b) => Math.abs(a - b) < 1e-9;

// ── 1. the card's two figures, and the rate in force ──────────────────────────────────────────
function figuresSection() {
  const on = (p, flag) => B.prevailingApplied({ conditions: { prevailing_wage: flag !== false }, prevailing: p });
  return {
    constants: { foreman: B.PREVAILING.FOREMAN_MIN, entry: B.PREVAILING.ENTRY_MIN },
    why: W.CONDITIONS.filter((c) => c.key === "prevailing_wage")[0].why,
    // the words each screen shows under the switch
    words: { live: W.conditionsFor("polish", "live").filter((c) => c.key === "prevailing_wage")[0].why,
             v2Intake: W.conditionsFor("polish", "v2Intake").filter((c) => c.key === "prevailing_wage")[0].why },
    trades: B.PREVAILING_TRADES.map((t) => [t.key, t.label]),
    // rate 40 + fringes 12 = 52, and half of it is 26 (above the $23 floor)
    fortyTwelve: { total: B.prevailingTotal({ rate: 40, fringes: 12 }), entry: B.entryHalfWage(52) },
    // rate 30 + fringes 10 = 40, and half of it is 20, so the floor holds the entry wage at 23
    thirtyTen: { total: B.prevailingTotal({ rate: 30, fringes: 10 }), entry: B.entryHalfWage(40) },
    typedAsText: B.prevailingTotal({ rate: "40.5", fringes: "12.25" }),
    floatJunk: B.prevailingTotal({ rate: 0.1, fringes: 0.2 }),
    nothingTyped: { total: B.prevailingTotal({ rate: "", fringes: "" }), none: B.prevailingTotal(undefined) },
    normalised: {
      none: B.normalizePrevailing(undefined), notAnObject: B.normalizePrevailing("52"), list: B.normalizePrevailing([1]),
      empty: B.normalizePrevailing({}), badTrade: B.normalizePrevailing({ trade: "plumber", rate: 5 }).trade,
      painter: B.normalizePrevailing({ trade: "painter", rate: "40", fringes: 12 }),
      keepsHalfTyped: B.prevailingCrewTrade({ rate: "12." }).rate,
      // the estimator's own trades: kept in order with their names; a bad key, a duplicate, a builtin twice,
      // and a name past the limit are all handled; the crew may be one of them
      own: B.normalizePrevailing({ trade: "t2", trades: [
        { key: "painter", rate: 30, fringes: 9 }, { key: "t2", label: "Laborer", rate: "25", fringes: 8 },
        { key: "t2", label: "dupe" }, { key: "../x", label: "bad key" }, { key: "t3", label: "x".repeat(80) },
        { key: "cement_mason", label: "Renamed?", rate: 40, fringes: 12 }] }),
      ownCrewTotal: B.prevailingTotal({ trade: "t2", trades: [{ key: "t2", label: "Laborer", rate: "25", fringes: 8 }] }),
      goneCrew: B.normalizePrevailing({ trade: "t9", trades: [] }).trade,
      newKey: B.newPrevailingTradeKey({ trades: [{ key: "t1", label: "a" }, { key: "t2", label: "b" }] }),
    },
    // the rate in force: switch on AND a rate set
    applied: {
      onWith52: on({ rate: 40, fringes: 12 }), offWith52: on({ rate: 40, fringes: 12 }, false),
      onEmpty: on({ rate: "", fringes: "" }), onNoBlock: B.prevailingApplied({ conditions: { prevailing_wage: true } }),
      onlyFringes: on({ rate: "", fringes: 9 }), noModel: B.prevailingApplied(null),
    },
  };
}

// ── 2. one labor line's rate, and the totals built from it ──────────────────────────────────────
/** The rows a NEW bid holds: every rate filled and stamped with the rate the row started from. */
function crew() {
  return [
    { id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33, rate_default: 33 },
    { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 33, rate_default: 33 },
    { id: "jointfill", label: "Joint filler", guys: 2, days: 2, rate: 33, rate_default: 33 },
    { id: "travel", label: "Travel Labor", guys: 2, days: 3, rate: 36, rate_default: 36, unit: "hours", guys_auto: false },
  ];
}
const cost = (row, pw) => B.laborCost(row, pw);

/** A rate TYPED TO THE LINE'S OWN DEFAULT (B.setLaborRate): the one typed rate a number alone cannot tell from a
 *  line that is following its default. It is marked on the row, and the mark goes when the rate is anything else. */
function typedAtDefaultRates() {
  const typedTo = (value) => { const row = crew()[0]; B.setLaborRate(row, value); return row; };
  const atDefault = typedTo("33");                    // typed 33 on a line whose default is 33
  const other = typedTo("34");                        // a different number: the numbers already say it was typed
  const cleared = typedTo("33"); B.setLaborRate(cleared, "");
  const backTo = typedTo("34"); B.setLaborRate(backTo, "33");
  const noDefault = { id: "polishing", guys: 3, days: 5, rate: 33 };      // a saved bid's row: nothing to compare to
  B.setLaborRate(noDefault, "33");
  const calcRow = { id: "mockup", guys: 3, days: 1, rate: 50, calc_default: { rate: 50 } };
  B.setLaborRate(calcRow, "50");
  const m = job({ trade: "cement_mason", rate: 40, fringes: 12 });
  B.setLaborRate(m.labor[0], "33");
  const reopened = B.migrateModel(clone(m));
  return {
    atDefault: { mark: atDefault.rate_typed, rate: atDefault.rate, atPrevailing: B.laborRateOf(atDefault, 52),
                 follows: B.laborFollowsPrevailing(atDefault, 52), box: B.laborRateBox(atDefault, 52),
                 cost: cost(atDefault, 52), atZero: B.laborRateOf(atDefault, 0), isTyped: B.rateTypedByHand(atDefault) },
    other: { marked: has(other, "rate_typed"), atPrevailing: B.laborRateOf(other, 52) },
    cleared: { marked: has(cleared, "rate_typed"), rate: cleared.rate, follows: B.laborFollowsPrevailing(cleared, 52),
               atPrevailing: B.laborRateOf(cleared, 52) },
    backTo: { mark: backTo.rate_typed, atPrevailing: B.laborRateOf(backTo, 52) },
    noDefault: { marked: has(noDefault, "rate_typed"), atPrevailing: B.laborRateOf(noDefault, 52) },
    calcRow: { mark: calcRow.rate_typed, atPrevailing: B.laborRateOf(calcRow, 52) },
    notARow: (() => { try { B.setLaborRate(null, "33"); B.setLaborRate("x", "33"); return "no throw"; } catch (e) { return "threw"; } })(),
    reopened: { mark: reopened.labor[0].rate_typed, rate: reopened.labor[0].rate,
                atPrevailing: B.laborRateOf(reopened.labor[0], B.prevailingApplied(reopened)),
                bidLabor: B.polishBid(reopened, "Polish", ctxOf()).labor, expected: 3 * 5 * 33 * 8 },
  };
}

function ratesSection() {
  const rows = crew();
  const at = (pw) => rows.map((r) => B.laborRateOf(r, pw));
  const costs = (pw) => rows.map((r) => cost(r, pw));
  const typed = crew(); typed[1].rate = 40;                      // the estimator typed 40 over Mock-up
  const cleared = crew(); cleared[0].rate = "";                  // a cleared box is the line's default
  const zero = crew(); zero[0].rate = 0;                         // typing 0 is still an answer
  const unstamped = { id: "polishing", guys: 3, days: 5, rate: 33 };   // a saved bid's row: nothing to compare to
  const calc = { id: "mockup", guys: 3, days: 1, rate: 50, calc_default: { rate: 50 } };
  const gyp = { id: "pour", label: "Pour", guys: 4, days: 6, rate: 33.66, rate_default: 33.66, unit: "hours" };
  const cond = { joint_filler: true, remove_existing_jf: true };
  return {
    noPw: { rates: at(0), none: at(undefined), costs: costs(0), total: B.laborTotal(rows, {}) },
    pw52: { rates: at(52), costs: costs(52), total: B.laborTotal(rows, {}, 52) },
    // Travel Labor keeps its own rate: the sheet's Polish C44 is $33 whatever the prevailing wage is
    travelKeeps: B.laborRateOf(rows[3], 52),
    typedWins: { rates: B.laborTotal(typed, {}, 52), mockup: B.laborRateOf(typed[1], 52), polishing: B.laborRateOf(typed[0], 52),
                 follows: [B.laborFollowsPrevailing(typed[0], 52), B.laborFollowsPrevailing(typed[1], 52)] },
    cleared: { rate: B.laborRateOf(cleared[0], 52), box: B.laborRateBox(cleared[0], 52), off: B.laborRateOf(cleared[0], 0) },
    zeroIsTyped: { rate: B.laborRateOf(zero[0], 52), cost: cost(zero[0], 52) },
    unstampedRowIsNeverMoved: B.laborRateOf(unstamped, 52),
    calcRowFollows: B.laborRateOf(calc, 52), calcRowTyped: B.laborRateOf(Object.assign({}, calc, { rate: 55 }), 52),
    // a Gyp pour is an hours line: guys x hours x rate, no 8 hour day, and it follows the prevailing rate too
    gypHours: { at33: cost(gyp, 0), at52: cost(gyp, 52), expected: 4 * 6 * 52 },
    // the extra hand on Joint Filler is paid the line's rate
    removeExisting: { off: B.removeExistingHand(crew(), cond, 0), on: B.removeExistingHand(crew(), cond, 52),
                      expected: 1 * 2 * 52 * 8 },
    // the Rate box shows what the line prices at
    box: { following: B.laborRateBox(rows[0], 52), typed: B.laborRateBox(typed[1], 52), travel: B.laborRateBox(rows[3], 52),
           noPw: B.laborRateBox(rows[0], 0) },
    typedAtDefault: typedAtDefaultRates(),
    // a switched-off row is still off
    offRow: cost(Object.assign(crew()[0], { enabled: false }), 52),
    // a pw that is not a positive number is no prevailing wage
    junkPw: [B.laborRateOf(rows[0], NaN), B.laborRateOf(rows[0], -5), B.laborRateOf(rows[0], "x")],
  };
}

// ── 3. every section of a bid, through the real chain ────────────────────────────────────────────
const RULE = (layout, line, formula) => ({ layout: layout, line_key: line, formula: formula, applies: true });
const MATERIAL = { Polish: 10000, Epoxy: 8000, Seal: 1500 };
const ctxOf = () => ({ material: (e) => MATERIAL[e.tab] });
/** A job with a Polish root, an Epoxy base and a Seal option, every row the way a new bid stamps it. */
function job(pw) {
  let m = B.freshModel();
  m.takeoff = [{ assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: 10000, unit: "SF" }];
  m.labor = [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33, rate_default: 33 }];
  m = B.activateSection(m, "Epoxy", "base", { rules: [RULE("epoxy", "soft_costs", "10%")] });
  m.tabs.Epoxy.takeoff = [{ assembly_id: "e1", assembly_name: "Flake", measurement: 4000, unit: "SF" }];
  m.tabs.Epoxy.labor = [{ id: "installing", label: "Installing", guys: 3, days: 4, rate: 33, rate_default: 33 }];
  m = B.activateSection(m, "Seal", "option", {});
  m.tabs.Seal.takeoff = [{ assembly_id: "s1", assembly_name: "Seal", measurement: 10000, unit: "SF" }];
  m.tabs.Seal.labor = [{ id: "sealing", label: "Sealing", guys: 2, days: 1, rate: 33, rate_default: 33 }];
  m.conditions.prevailing_wage = !!pw;
  if (pw) m.prevailing = pw;
  return m;
}
const priced = (m) => Object.assign({ Polish: B.polishBid(m, "Polish", ctxOf()) }, B.priceTabs(m, ctxOf()));
const roundUp = (n) => Math.ceil(n - 1e-9);

function sectionsSection() {
  const PW = { trade: "cement_mason", rate: 40, fringes: 12 };
  const off = priced(job(null));
  const on = priced(job(PW));
  const flagOnNoRate = priced(job({ trade: "cement_mason", rate: "", fringes: "" }));
  const handTyped = job(PW); handTyped.tabs.Epoxy.labor[0].rate = 40;     // typed on the Epoxy section only
  const typedBids = priced(handTyped);
  const m = job(PW);
  const patch = B.buildSavePatch(m, {}, { bid: on.Polish, bids: B.priceTabs(m, ctxOf()) });
  return {
    // labor dollars: guys x days x rate x 8
    off: { Polish: off.Polish.labor, Epoxy: off.Epoxy.labor, Seal: off.Seal.labor },
    on: { Polish: on.Polish.labor, Epoxy: on.Epoxy.labor, Seal: on.Seal.labor },
    expectedOff: { Polish: 3 * 5 * 33 * 8, Epoxy: 3 * 4 * 33 * 8, Seal: 2 * 1 * 33 * 8 },
    expectedOn: { Polish: 3 * 5 * 52 * 8, Epoxy: 3 * 4 * 52 * 8, Seal: 2 * 1 * 52 * 8 },
    // the 5% escalation still follows the switch exactly as before, on the labor figure
    escalationOn: { Polish: on.Polish.escalation, Epoxy: on.Epoxy.escalation, Seal: on.Seal.escalation },
    escalationOnExpected: { Polish: roundUp(on.Polish.labor * 0.05), Epoxy: roundUp(on.Epoxy.labor * 0.05),
                            Seal: roundUp(on.Seal.labor * 0.05) },
    escalationOff: { Polish: off.Polish.escalation, Epoxy: off.Epoxy.escalation, Seal: off.Seal.escalation },
    totalsMove: { Polish: on.Polish.total > off.Polish.total, Epoxy: on.Epoxy.total > off.Epoxy.total, Seal: on.Seal.total > off.Seal.total },
    // a switch that is on with no rate set changes nothing about the labor (the escalation is the old behaviour)
    onNoRate: { Epoxy: flagOnNoRate.Epoxy.labor, Polish: flagOnNoRate.Polish.labor, escalation: flagOnNoRate.Polish.escalation },
    // a rate typed on the Epoxy section's line wins there and only there
    typedOnEpoxy: { Epoxy: typedBids.Epoxy.labor, expected: 3 * 4 * 40 * 8, Polish: typedBids.Polish.labor },
    // what a save writes carries the block, and stamps the totals priced at the prevailing rate
    save: { carried: patch.polish_estimate.prevailing, totalsLabor: patch.polish_estimate.totals.labor,
            epoxyTotalsLabor: patch.polish_estimate.tabs.Epoxy.totals.labor },
    // a model that never used the card saves no `prevailing` key at all
    hasBlockOnAFreshSave: has(B.buildSavePatch(job(null), {}, { bid: off.Polish, bids: B.priceTabs(job(null), ctxOf()) }).polish_estimate, "prevailing"),
    // polish-rev2 counts the nights of Lodging from the labor DOLLARS over the first labor rate, so the rate that divides
    // them is the prevailing one while it is in force (a line typed at $40 is what makes that visible)
    rev2Nights: (() => {
      const x = B.freshModel(); x.profile = "polish-rev2@1"; x.conditions.prevailing_wage = true; x.conditions.local = false;
      x.prevailing = { trade: "cement_mason", rate: 40, fringes: 12 };
      x.labor = [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33, rate_default: 33 },
                 { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 40, rate_default: 33 }];
      x.travel.lodging.enabled = true;
      const opts = B.travelOpts(x, "Polish");
      return { qty: B.travelQty(x.travel.lodging, x.labor, opts), expected: roundUp(3 * 5 * 52 * 8 + 3 * 0.5 * 40 * 8) / 52 / 8,
               optsPrevailing: opts && opts.prevailing };
    })(),
    blockers: (() => {
      // a blank rate on a started line is "missing" until a prevailing rate stands in for it
      const base = (pwBlock) => { const x = B.freshModel(); x.takeoff = [{ assembly_id: "a1", measurement: 100 }];
        x.labor = [{ id: "polishing", label: "Polishing", guys: 3, days: 2, rate: "" }];
        x.conditions.prevailing_wage = !!pwBlock; if (pwBlock) x.prevailing = pwBlock; return B.blockers(x).filter((s) => /rate/.test(s)); };
      return { plain: base(null), withPw: base({ rate: 40, fringes: 12 }) };
    })(),
  };
}

// ── 4. a saved bid prices exactly as before ───────────────────────────────────────────────────────
function savedSection() {
  // a bid saved with the prevailing wage switch ON and no card block, the shape every saved bid has
  const saved = { version: 2, takeoff: [{ assembly_id: "a1", assembly_name: "x", measurement: 10000, unit: "SF" }],
    labor: [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33 },
            { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 33 },
            { id: "travel", label: "Travel", guys: 6, days: 2, rate: 33, unit: "hours", guys_auto: false }],
    conditions: { local: false, prevailing_wage: true, taxable: true }, contingency: 0, totals: {} };
  const m = B.migrateModel(clone(saved));
  const bid = B.polishBid(m, "Polish", { material: () => 10000 });
  const oldWay = B.markupChain({ material: 10000, labor: B.laborTotal(m.labor, m.conditions),
    travel: B.travelCosts(m.travel, m.labor, B.travelOpts(m, "Polish")).total, contingency: m.contingency, fees: m.fees,
    conditions: m.conditions, sf: B.takeoffSf(m.takeoff), remodel_rate: undefined });
  const withBlockOffFlag = clone(saved); withBlockOffFlag.conditions.prevailing_wage = false;
  withBlockOffFlag.prevailing = { trade: "painter", rate: 40, fringes: 12 };
  const mo = B.migrateModel(withBlockOffFlag);
  const savedPatch = B.buildSavePatch(m, {}, { bid: bid });
  const typedRowsOnAStampedBid = { id: "polishing", guys: 3, days: 5, rate: 33, rate_default: 33 };
  return {
    migratedHasBlock: has(m, "prevailing"), applied: B.prevailingApplied(m),
    labor: bid.labor, laborBefore: oldWay.labor, total: bid.total, totalBefore: oldWay.total,
    escalation: bid.escalation, escalationBefore: oldWay.escalation,
    savePatchHasBlock: has(savePatchModel(savedPatch), "prevailing"),
    blockKept: mo.prevailing, offFlagApplied: B.prevailingApplied(mo),
    migrateTwice: JSON.stringify(B.migrateModel(clone(mo))) === JSON.stringify(mo),
    savedRowRate: B.laborRateOf(saved.labor[0], 0), stampedRowAtZero: B.laborRateOf(typedRowsOnAStampedBid, 0),
      };
}
const savePatchModel = (p) => p.polish_estimate;

// ── 5. the card on the real page ────────────────────────────────────────────────────────────────
const settle = async () => { for (let i = 0; i < 6; i++) await new Promise((r) => setImmediate(r)); };
const crewLib = (id, name, sort) => ({ id: id, name: name, rate: 33, unit: "days", guys_auto: false, favorite: true,
  default_work_types: ["polish"], sort: sort, notes: "" });
const LIB = [
  { id: "travel", name: "Travel", rate: 36, unit: "hours", guys_auto: true, favorite: true, default_work_types: [], sort: -1, notes: "" },
  crewLib("polishing", "Polishing", 1), crewLib("mockup", "Mock-up", 2), crewLib("jointfill", "Joint filler", 3),
];
const rendered = [];
/** The Prevailing wage card's own markup out of a panel, up to the first labor card after it ("" if it is not there). */
function cardOf(html) {
  const at = html.indexOf("data-pw-card");
  if (at < 0) return "";
  const end = html.indexOf('class="tk lab', at);
  return html.slice(at, end < 0 ? html.length : end);
}

async function pageSection() {
  const q = P.build({ blob: P.blob({ polish_estimate: null, polish_sf: 12000 }), labor: LIB });
  await q.api.init(); q.api.go(1); await settle();
  const idx = (id) => q.api.model().labor.findIndex((r) => r.id === id);
  const iP = idx("polishing"), iM = idx("mockup"), iT = idx("travel");
  const box = (i, k) => String(P.need(q, '[data-lab="' + i + '"][data-k="' + k + '"]').value);
  const t = (sel) => P.txt(q, sel);
  const warn = (i) => { const el = P.need(q, '[data-ratedflt-for="' + i + '"]'); return { text: el.textContent, hidden: !!el.hidden }; };
  const card = () => ({ total: t("[data-pw-total]"), entry: t("[data-pw-entry]"), sub: t("[data-pw-sub]"),
    note: t("[data-pw-note]"), cls: P.need(q, "[data-pw-card]").className,
    rate: String(P.need(q, '[data-pw="rate"]').value), fringes: String(P.need(q, '[data-pw="fringes"]').value),
    trade: (B.normalizePrevailing(q.api.model().prevailing) || B.normalizePrevailing({})).trade,
    sw: P.need(q, '[data-cond="prevailing_wage"]').attrs["aria-checked"],
    swClass: P.need(q, '[data-cond="prevailing_wage"]').className,
    bodyHidden: !!P.need(q, "[data-pw-body]").hidden,
    caption: { state: t("[data-pw-state]"), esc: t("[data-pw-esc]") } });
  // the switch node and the writes to the panel: pressing the switch must keep THE SAME NODE on screen (a rebuild
  // makes a new one, and the focus that was on the old one is gone) and write the panel's markup no more than once
  const press = (how) => {
    const node = P.need(q, '[data-cond="prevailing_wage"]');
    const writes = q.dom.get("panels").htmlWrites;
    if (how === "key") {
      node.click = function () { q.doc.fire("click", { target: node, preventDefault() {} }); };
      q.doc.fire("keydown", { target: node, key: " ", preventDefault() {} });
    } else P.clickOn(q, '[data-cond="prevailing_wage"]');
    return { sameNode: P.need(q, '[data-cond="prevailing_wage"]') === node, rebuilt: q.dom.get("panels").htmlWrites - writes };
  };
  const out = {};
  rendered.push(cardOf(q.dom.get("panels").innerHTML));

  // a NEW bid: the card is there, empty, and nothing was written to the model by opening it
  out.fresh = { card: card(), hasBlock: has(q.api.model(), "prevailing"), flag: q.api.model().conditions.prevailing_wage,
    rateBoxes: [box(iP, "rate"), box(iM, "rate"), box(idx("jointfill"), "rate"), box(iT, "rate")],
    order: Array.from(q.dom.get("panels").innerHTML.matchAll(/data-pw-card|data-lab-card="0"|data-travel-total|data-pw-state/g)).map((x) => x[0]),
    saves: q.rec.saves.length };

  // the foreman and entry hints, plain words
  out.fresh.cardHtml = cardOf(q.dom.get("panels").innerHTML);
  out.hints = { text: L.stripTags(out.fresh.cardHtml.slice(out.fresh.cardHtml.indexOf(">") + 1)) };

  // the labor quantities, typed while the card is closed (it is its header alone)
  P.typeInto(q, '[data-lab="' + iP + '"][data-k="guys"]', "3"); P.typeInto(q, '[data-lab="' + iP + '"][data-k="days"]', "5");
  P.typeInto(q, '[data-lab="' + iM + '"][data-k="guys"]', "3"); P.typeInto(q, '[data-lab="' + iM + '"][data-k="days"]', "0.5");
  P.typeInto(q, '[data-lab="' + iT + '"][data-k="guys"]', "2"); P.typeInto(q, '[data-lab="' + iT + '"][data-k="days"]', "3");
  out.offTotals = { polishing: t('[data-lcost-for="' + iP + '"]'), labor: t("[data-labor-total]"), bidLabor: q.api.bid().labor,
    escalation: q.api.bid().escalation };

  // OPEN IT: the card's own switch. The body shows, nothing is rebuilt, the switch is the same node, and with no rate
  // typed yet no line moves (the escalation is the only thing the switch adds)
  const pressedOpen = press("click");
  out.opened = Object.assign({ card: card(), flag: q.api.model().conditions.prevailing_wage,
    rateBoxes: [box(iP, "rate"), box(iM, "rate"), box(idx("jointfill"), "rate"), box(iT, "rate")],
    bidLabor: q.api.bid().labor, escalation: q.api.bid().escalation, hasBlock: has(q.api.model(), "prevailing") }, pressedOpen);
  rendered.push(cardOf(q.dom.get("panels").innerHTML));

  // type the rate and the fringes: the two figures move, and so does every line that follows
  P.typeInto(q, '[data-pw="rate"]', "40");
  P.typeInto(q, '[data-pw="fringes"]', "12");
  out.fortyTwelve = { card: card(), rateBoxes: [box(iP, "rate"), box(iM, "rate")], model: clone(q.api.model().prevailing),
    laborTotalText: t("[data-labor-total]") };
  P.typeInto(q, '[data-pw="rate"]', "30");
  P.typeInto(q, '[data-pw="fringes"]', "10");
  out.thirtyTen = { card: card(), rateBoxes: [box(iP, "rate"), box(iM, "rate")] };
  P.typeInto(q, '[data-pw="rate"]', "40");
  P.typeInto(q, '[data-pw="fringes"]', "12");

  out.on = { card: card(), flag: q.api.model().conditions.prevailing_wage,
    rateBoxes: [box(iP, "rate"), box(iM, "rate"), box(idx("jointfill"), "rate"), box(iT, "rate")],
    stored: [q.api.model().labor[iP].rate, q.api.model().labor[iM].rate],
    polishingCost: t('[data-lcost-for="' + iP + '"]'), polishingCostBox: t('[data-lcostbox-for="' + iP + '"]'),
    mockupCost: t('[data-lcost-for="' + iM + '"]'), travelCost: t('[data-lcost-for="' + iT + '"]'),
    laborTotalText: t("[data-labor-total]"), bidLabor: q.api.bid().labor, escalation: q.api.bid().escalation,
    warns: [warn(iP), warn(iM), warn(iT)] };
  out.on.expected = { polishing: 3 * 5 * 52 * 8, mockup: 3 * 0.5 * 52 * 8, travel: 2 * 3 * 36 };
  out.on.expected.labor = out.on.expected.polishing + out.on.expected.mockup + out.on.expected.travel;
  out.on.expected.escalation = roundUp(out.on.expected.labor * 0.05);
  rendered.push(cardOf(q.dom.get("panels").innerHTML));

  // the card's rate moves while on: the lines that follow repaint IN PLACE (no rebuild)
  const w1 = q.dom.get("panels").htmlWrites;
  P.typeInto(q, '[data-pw="fringes"]', "14");
  out.moved = { card: card(), rateBoxes: [box(iP, "rate"), box(iM, "rate")], rebuilt: q.dom.get("panels").htmlWrites - w1,
    polishingCost: t('[data-lcost-for="' + iP + '"]'), bidLabor: q.api.bid().labor, laborTotalText: t("[data-labor-total]") };
  out.moved.expectedPolishing = 3 * 5 * 54 * 8;
  P.typeInto(q, '[data-pw="fringes"]', "12");

  // a rate TYPED on a line wins, and says what the default is
  P.typeInto(q, '[data-lab="' + iM + '"][data-k="rate"]', "40");
  out.typed = { rateBoxes: [box(iP, "rate"), box(iM, "rate")], mockupCost: t('[data-lcost-for="' + iM + '"]'),
    polishingCost: t('[data-lcost-for="' + iP + '"]'), warns: [warn(iP), warn(iM)], model: q.api.model().labor[iM].rate,
    bidLabor: q.api.bid().labor };
  out.typed.expectedMockup = 3 * 0.5 * 40 * 8;
  // ...and it keeps winning when the card's rate moves
  P.typeInto(q, '[data-pw="rate"]', "41");
  out.typed.afterCardMoves = { mockupBox: box(iM, "rate"), polishingBox: box(iP, "rate") };
  P.typeInto(q, '[data-pw="rate"]', "40");

  // the Review step reads the same rate
  q.api.go(2);
  const review = L.stripTags(q.dom.get("panels").innerHTML);
  out.review = { polishing: /Polishing\s*3 × 5 × \$52\.00\s*\$6,240/.test(review), mockup: /Mock-up\s*3 × 0\.5 × \$40\.00\s*\$480/.test(review),
    travel: /Travel Labor\s*2 × 3 × \$36\.00\s*\$216/.test(review), sample: review.slice(review.indexOf("Polishing"), review.indexOf("Polishing") + 80) };
  rendered.push(cardOf(q.dom.get("panels").innerHTML));
  q.api.go(1);
  // BACK ON THE LABOR STEP the panel is drawn afresh, with the card on: its first paint, not a repaint
  out.afterReturn = { card: card(), rateBoxes: [box(iP, "rate"), box(iM, "rate"), box(iT, "rate")],
    polishingCost: t('[data-lcostbox-for="' + iP + '"]'), warns: [warn(iP), warn(iM)] };

  // switch it OFF: every following line is back on its own rate, the typed one stays, and the escalation goes
  // CLOSE IT. The card collapses to its header and one line of words, the same switch node stays on screen with
  // nothing rebuilt, and what was typed is KEPT (the boxes are hidden, not emptied).
  const pressedClosed = press("click");
  out.off = Object.assign({ card: card(), flag: q.api.model().conditions.prevailing_wage,
    block: clone(q.api.model().prevailing),
    rateBoxes: [box(iP, "rate"), box(iM, "rate"), box(iT, "rate")], stored: [q.api.model().labor[iP].rate, q.api.model().labor[iM].rate],
    polishingCost: t('[data-lcost-for="' + iP + '"]'), laborTotalText: t("[data-labor-total]"), bidLabor: q.api.bid().labor,
    escalation: q.api.bid().escalation, warns: [warn(iP), warn(iM)] }, pressedClosed);
  out.off.expected = { polishing: 3 * 5 * 33 * 8, mockup: 3 * 0.5 * 40 * 8 };
  out.off.expected.labor = out.off.expected.polishing + out.off.expected.mockup + 2 * 3 * 36;
  rendered.push(cardOf(q.dom.get("panels").innerHTML));

  // OPEN IT AGAIN: the stored trade, rate and fringes are there, and the lines follow them again
  const pressedReopen = press("click");
  out.reopened = Object.assign({ card: card(), rateBoxes: [box(iP, "rate"), box(iM, "rate"), box(iT, "rate")],
    polishingCost: t('[data-lcost-for="' + iP + '"]') }, pressedReopen);

  // CLEAR a following line's Rate box with it on: the model gets the line's OWN rate back (never the prevailing
  // one), the box still shows what it prices at, and closing the card puts the own rate on screen
  P.typeInto(q, '[data-lab="' + iP + '"][data-k="rate"]', "");
  P.changeTo(q, '[data-lab="' + iP + '"][data-k="rate"]', "");
  out.cleared = { stored: q.api.model().labor[iP].rate, box: box(iP, "rate"), cost: t('[data-lcost-for="' + iP + '"]') };
  press("click");
  out.cleared.afterOff = { stored: q.api.model().labor[iP].rate, box: box(iP, "rate"), cost: t('[data-lcost-for="' + iP + '"]') };
  press("click");

  // TRADES. Typing a painter's figures moves nothing (the crew is paid as a cement mason); paying the crew as a
  // painter moves every following line to the painter's rate and leaves Travel Labor alone.
  const pick = (i) => {
    const el = P.need(q, '[data-pw-pick="' + i + '"]');
    el.checked = true;
    q.doc.fire("change", { target: el });
  };
  const bidBefore = q.api.bid().total;
  P.typeInto(q, '[data-pw="rate"][data-pw-i="1"]', "30");
  P.typeInto(q, '[data-pw="fringes"][data-pw-i="1"]', "10");
  const typedPainter = { sameBid: q.api.bid().total === bidBefore, box: box(iP, "rate"),
    painterTotal: t('[data-pw-total][data-pw-i="1"]'), painterEntry: t('[data-pw-entry][data-pw-i="1"]') };
  pick(1);
  out.trade = { typedPainter: typedPainter, model: clone(q.api.model().prevailing), card: card(),
    box: box(iP, "rate"), travel: box(iT, "rate"), movedBid: q.api.bid().total !== bidBefore,
    crewClass: [P.need(q, '[data-pw-trade="0"]').className, P.need(q, '[data-pw-trade="1"]').className] };
  // ADD ONE OF OUR OWN: + Add a trade, name it, give it figures, pay the crew it, then remove it
  P.clickOn(q, "[data-pw-add]");
  const added = { names: q.doc.querySelectorAll('[data-pw="label"]').length,
    model: clone(q.api.model().prevailing) };
  P.typeInto(q, '[data-pw="label"][data-pw-i="2"]', "Laborer");
  P.typeInto(q, '[data-pw="rate"][data-pw-i="2"]', "25");
  P.typeInto(q, '[data-pw="fringes"][data-pw-i="2"]', "8");
  pick(2);
  added.picked = { box: box(iP, "rate"), sub: t("[data-pw-sub]"), total: t('[data-pw-total][data-pw-i="2"]'),
    model: clone(q.api.model().prevailing) };
  P.clickOn(q, '[data-pw-del="2"]');
  added.removed = { box: box(iP, "rate"), model: clone(q.api.model().prevailing),
    boxes: q.doc.querySelectorAll("[data-pw-trade]").length,
    builtinsHaveNoRemove: q.doc.querySelectorAll("[data-pw-del]").length };
  out.added = added;
  pick(1);

  // the switch answers the keyboard (Space) like the other switches, and keeps its node and its focus the same way
  const before = q.api.model().conditions.prevailing_wage;
  const pressedKey = press("key");
  out.keyboard = Object.assign({ before: before, after: q.api.model().conditions.prevailing_wage,
    bodyHiddenAfter: !!P.need(q, "[data-pw-body]").hidden, caption: t("[data-pw-state]") }, pressedKey);

  // a save carries the block (the page's own timer, fired)
  q.clock.fire();
  const last = q.rec.saves[q.rec.saves.length - 1] || {};
  out.saved = { block: last.polish_estimate && last.polish_estimate.prevailing };
  return out;
}

/** The card and the rate on ANOTHER section's Labor step (an Epoxy base with a Seal option), through the page. */
async function sectionPageSection() {
  const m = job({ trade: "cement_mason", rate: 40, fringes: 12 });
  // work_type combo: the Epoxy section is a base of the job (a polish job marks it off), so it is priced
  const q = P.build({ blob: P.blob({ work_type: "combo", polish_estimate: clone(m) }), labor: LIB });
  await q.api.init(); await settle();
  const out = {};
  for (const tab of ["Epoxy", "Seal"]) {
    q.api.show(tab); q.api.go(1); await settle();
    const lab = q.api.model().labor;
    const box = () => String(P.need(q, '[data-lab="0"][data-k="rate"]').value);
    out[tab] = { card: !!q.doc.querySelector("[data-pw-card]"), total: P.txt(q, "[data-pw-total]"),
      rateBox: box(), cost: P.txt(q, '[data-lcost-for="0"]'), laborTotal: P.txt(q, "[data-labor-total]"),
      sectionBidLabor: q.api.activeBid().labor, stored: lab[0].rate };
    rendered.push(cardOf(q.dom.get("panels").innerHTML));
  }
  out.expected = { Epoxy: 3 * 4 * 52 * 8, Seal: 2 * 1 * 52 * 8 };
  return out;
}

/** A RATE TYPED TO THE LINE'S OWN DEFAULT, on the real page, while the prevailing wage is on. Typing 33 on a line whose
 *  default is 33 used to be read as "following the default", so the line went on pricing at the prevailing rate while its
 *  box said 33 (and showed 52 again on the next repaint). The line is the estimator's own now: box, cost, total, note,
 *  Review and the save all say 33, the card's rate moving does not touch it, and clearing the box hands it back. */
async function typedAtDefaultPageSection() {
  const q = P.build({ blob: P.blob({ polish_estimate: null, polish_sf: 12000 }), labor: LIB });
  await q.api.init(); q.api.go(1); await settle();
  const iP = q.api.model().labor.findIndex((r) => r.id === "polishing");
  const sel = '[data-lab="' + iP + '"][data-k="rate"]';
  const row = () => q.api.model().labor[iP];
  const warn = () => P.need(q, '[data-ratedflt-for="' + iP + '"]');
  const read = () => ({ box: String(P.need(q, sel).value), cost: P.txt(q, '[data-lcost-for="' + iP + '"]'),
    costBox: P.txt(q, '[data-lcostbox-for="' + iP + '"]'), laborTotal: P.txt(q, "[data-labor-total]"), bidLabor: q.api.bid().labor,
    warn: warn().textContent, warnHidden: !!warn().hidden, rate: row().rate, mark: has(row(), "rate_typed") ? row().rate_typed : null });
  P.clickOn(q, '[data-cond="prevailing_wage"]');
  P.typeInto(q, '[data-pw="rate"]', "40"); P.typeInto(q, '[data-pw="fringes"]', "12");
  P.typeInto(q, '[data-lab="' + iP + '"][data-k="guys"]', "3"); P.typeInto(q, '[data-lab="' + iP + '"][data-k="days"]', "5");
  const out = { following: read() };
  P.typeInto(q, sel, "33"); out.typing = read();
  P.changeTo(q, sel, "33"); out.blurred = read();
  // the card's rate moves: a repaint of every figure, and the typed line still says 33
  P.typeInto(q, '[data-pw="fringes"]', "13"); out.cardMoved = read();
  q.api.go(2);
  const review = L.stripTags(q.dom.get("panels").innerHTML);
  out.review = { typed: /Polishing\s*3 × 5 × \$33\.00\s*\$3,960/.test(review), sample: review.slice(review.indexOf("Polishing"), review.indexOf("Polishing") + 80) };
  q.api.go(1);
  out.afterReturn = read();
  q.clock.fire();
  const last = q.rec.saves[q.rec.saves.length - 1] || {};
  const saved = ((last.polish_estimate || {}).labor || []).filter((r) => r.id === "polishing")[0] || {};
  out.saved = { rate: saved.rate, mark: saved.rate_typed };
  // clearing the box. ONLY `change` fires here (no `input` before it: an autofill, a paste): the line is handed back
  P.changeTo(q, sel, ""); out.clearedByChange = read();
  // typed again, then cleared the ordinary way (input, then change)
  P.typeInto(q, sel, "33"); out.typedAgain = read();
  P.typeInto(q, sel, ""); P.changeTo(q, sel, ""); out.clearedByTyping = read();
  // another number: 34 is a typed rate on the numbers alone, and typing 33 again marks it once more
  P.typeInto(q, sel, "34"); out.thirtyFour = read();
  P.typeInto(q, sel, "33"); out.backToThirtyThree = read();
  // the card is switched off: the line is still 33, and the note names no prevailing rate
  P.clickOn(q, '[data-cond="prevailing_wage"]'); out.cardOff = read();
  return out;
}

/** The Lodging hint on a polish-rev2 bid with a prevailing wage. It says what the sheet counts, worked out from the labor
 *  dollars over the first labor rate, so it must read the prevailing rate the totals use. Model and page. */
async function lodgingSection() {
  const mk = (flag) => {
    const x = B.freshModel(); x.profile = "polish-rev2@1"; x.conditions.prevailing_wage = flag; x.conditions.local = false;
    x.prevailing = { trade: "cement_mason", rate: 40, fringes: 12 };
    x.takeoff = [{ assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: 10000, unit: "SF" }];
    // Polishing follows the card (52), Mock-up was typed at 40, Travel keeps its own
    x.labor = [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33, rate_default: 33 },
               { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 40, rate_default: 33 },
               { id: "travel", label: "Travel Labor", guys: "", days: "", rate: 36, rate_default: 36, unit: "hours", guys_auto: false }];
    x.travel.lodging.enabled = true; x.travel.lodging.qty_auto = false; x.travel.lodging.qty = "";
    return x;
  };
  const on = mk(true), off = mk(false);
  const q = P.build({ blob: P.blob({ polish_estimate: clone(on) }), labor: [] });
  await q.api.init(); q.api.go(1); await settle();
  const qOff = P.build({ blob: P.blob({ polish_estimate: clone(off) }), labor: [] });
  await qOff.api.init(); qOff.api.go(1); await settle();
  return {
    // labor dollars over the first rate (52) over 8 hours: (6240 + 480) / 52 / 8
    on: { hint: B.lodgingHint(on, "Polish", false, on.labor), auto: B.lodgingHint(on, "Polish", true, on.labor),
          count: B.sheetNights(on.labor, on.conditions, B.prevailingApplied(on)), manDays: B.travelManDays(on.labor) },
    expectedOn: roundUp(3 * 5 * 52 * 8 + 3 * 0.5 * 40 * 8) / 52 / 8,
    // switched off, the same lines are priced at their own rates and the count is the old one
    off: { hint: B.lodgingHint(off, "Polish", false, off.labor), count: B.sheetNights(off.labor, off.conditions, 0) },
    expectedOff: roundUp(3 * 5 * 33 * 8 + 3 * 0.5 * 40 * 8) / 33 / 8,
    page: { on: String(P.need(q, '[data-hint-trv="lodging"]').textContent), off: String(P.need(qOff, '[data-hint-trv="lodging"]').textContent) },
  };
}

/** The rail's two pips (Labor, Review) on a saved bid with a blank-rate labor line and no stamp, which only the prevailing
 *  wage prices. blockers() and the totals already read the prevailing rate; the pips must say the same. */
async function stepsSection() {
  const mk = (flag) => {
    const m = B.freshModel();
    m.takeoff = [{ assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: 10000, unit: "SF" }];
    m.labor = [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: "" }];
    m.conditions.prevailing_wage = flag; m.prevailing = { trade: "cement_mason", rate: 40, fringes: 12 };
    return m;
  };
  const out = {};
  for (const [name, flag] of [["on", true], ["off", false]]) {
    const q = P.build({ blob: P.blob({ polish_estimate: clone(mk(flag)) }), labor: [] });
    await q.api.init(); await settle();
    out[name] = { step: q.api.stepStatus(), bidLabor: q.api.bid().labor, blockers: B.blockers(q.api.model()),
                  rate: q.api.model().labor[0].rate };
  }
  return out;
}

(async function () {
  const attempt = async (fn) => { try { return await fn(); } catch (e) { return { error: String((e && e.stack) || e) }; } };
  const done = {};
  for (const [name, fn] of [["figures", figuresSection], ["rates", ratesSection], ["sections", sectionsSection],
                            ["saved", savedSection], ["page", pageSection], ["sectionPage", sectionPageSection],
                            ["typedAtDefaultPage", typedAtDefaultPageSection], ["lodging", lodgingSection],
                            ["steps", stepsSection]]) {
    done[name] = await attempt(fn);
  }
  // the words the page may never put on screen (Labour, Crew), over what the card rendered
  const bad = [];
  const re = /labour|crew/gi;
  let hit;
  const text = rendered.join("\n");
  while ((hit = re.exec(text))) bad.push(text.slice(Math.max(0, hit.index - 40), hit.index + 40));
  done.words = { hits: bad, chars: text.length };
  console.log(JSON.stringify(done));
})().catch((err) => { console.error((err && err.stack) || err); process.exit(1); });
