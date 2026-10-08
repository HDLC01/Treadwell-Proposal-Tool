"use strict";
/* THE BID ENGINE, set beside Kyle's workbook as the oracle recorded it.
 *
 *   node bid-engine-harness.js [<frontend dir>]
 *
 * For every priced tab, this runs js/bid-engine.js priceChain with the profile that prices the tab on every
 * chain and lodging case in backend/tests/fixtures/oracle/<tab>.json and compares every answer the two share.
 * They have to be EQUAL, to the dollar, with no excuses: the profiles other than polish-legacy have no
 * departures. Then it does the things that make "equal" mean something:
 *
 *   - QUIRK FLIPS. For every tab and every quirk flag, the profile is run again with that one flag turned the
 *     other way. A flag whose flip changes no answer on any tab proves nothing, so the test requires every
 *     flag the chain reads to show up red somewhere.
 *   - THE ODD RULES. Every rule of fixtures/oracle/odd_rules.json that lives in the chain is tested against the
 *     counterfactual ("what the ordinary reading would have charged") on the cases the oracle recorded.
 *   - THE DEPARTURES. polish-legacy against the sheet's own profile `polish`, case by case: every difference
 *     has to be one departures.json declares for that case, and every declared departure has to be seen.
 *   - THE PINS. Every rate a profile carries equals the constant in the workbook's cell (the oracle's `fixed`).
 *   - THE WRAPPER. bid-model's markupChain gives exactly what priceChain gives for polish-legacy.
 *
 * Prints, as its last line, one JSON object the test reads. <frontend dir> defaults to this repository's
 * frontend; the test hands it a copy with the engine or the profiles deliberately broken to watch this go red.
 */
const fs = require("fs");
const path = require("path");

const HERE = __dirname;
const REPO = path.resolve(HERE, "..", "..", "..");
const FRONTEND = process.argv[2] ? path.resolve(process.argv[2]) : path.join(REPO, "frontend");
const ORACLE = path.join(HERE, "..", "fixtures", "oracle");

const E = require(path.join(FRONTEND, "js", "bid-engine.js"));
const P = require(path.join(FRONTEND, "js", "bid-profiles.js"));
const dep = JSON.parse(fs.readFileSync(path.join(ORACLE, "departures.json"), "utf8"));
const odd = JSON.parse(fs.readFileSync(path.join(ORACLE, "odd_rules.json"), "utf8"));
const roundUp = require(path.join(FRONTEND, "js", "excel-math.js")).roundUp;

// oracle output name -> engine key
const KEYS = new Map(Object.entries({
  shipPct: "ship_pct", shipping: "shipping", materialTotal: "material_total", escPct: "esc_pct",
  escalation: "escalation", burden: "burden", lodgingQty: "lodging_qty", lodging: "lodging",
  perDiemQty: "per_diem_qty", perDiem: "per_diem", subTotal: "sub_total", gpPct: "gp_pct", gp: "gp",
  hardBidPct: "hard_bid_pct", hardBid: "hard_bid", superPto: "super_pto", softPct: "soft_pct",
  softCosts: "soft_costs", salesTaxPct: "sales_tax_pct", salesTax: "sales_tax", remodelTax: "remodel_tax",
  taxes: "taxes", bond: "bond", feesAndBond: "fees_and_bond", total: "total", perSf: "per_sf",
  remodelPct: "remodel_pct", materialSubTotal: "material", materialEscalation: "material_escalation",
  travel: "travel"
}));

const load = (slug) => JSON.parse(fs.readFileSync(path.join(ORACLE, slug + ".json"), "utf8"));

/** A case, as the job the engine is asked to price. */
function toInput(v, fp) {
  const i = v.in, a = v.out.answers;
  const input = {
    sf: i.sf, material: i.material, overage: i.overage, labor: i.labor, tooling: i.tooling,
    travel: i.travel === "template" ? undefined : i.travel,
    travelLabor: i.travelLabor, fees: i.fees, contingency: i.contingency,
    gyp: i.gyp, extras: i.extras, sand: i.sand, soundMat: i.soundMat, soundMatRolls: i.soundMatRolls,
    truckload: fp.truckload === null ? undefined : fp.truckload,
    conditions: { local: a.local, taxable: a.taxable, prevailing_wage: a.prevailingWage, remodel_tax: a.remodel, hard_bid: a.hardBid },
    remodel_rate: a.remodel && i.remodelPct !== undefined ? i.remodelPct : undefined,
    bond_pct: i.bondPct
  };
  // Seal (+Jnts) reads its remodel RATE from Seal (B75 is `=Seal!B75`), and Seal's own Remodel answer is the
  // one these cases never set: they write the answer on the (+Jnts) tab, where in the real workbook it is a
  // formula that follows Seal. So a remodel job with no rate typed is priced at Seal's rate, 0, in the case. That
  // state cannot be reached in the workbook as Kyle keeps it, and it is a fact about how the oracle drives a
  // mirrored tab, not a rule of the chain: the case is handed the rate the sheet read.
  if (fp.tab === "Seal (+Jnts)" && a.remodel && i.remodelPct === undefined) input.remodel_rate = 0;
  return input;
}

function same(want, got) {
  const a = want === false ? 0 : want, b = got === false ? 0 : got;
  if (typeof a === "number" && typeof b === "number") return a === b || Math.abs(a - b) < 1e-9;
  return a === b;
}

/** The oracle's answers that the engine also gives, compared. [{key, oracle, engine}] for each that differs. */
function diffs(v, r) {
  const out = [];
  for (const [name, key] of KEYS) {
    if (!(name in v.out)) continue;
    if (!same(v.out[name], r[key])) out.push({ key: name, oracle: v.out[name], engine: r[key] });
  }
  return out;
}

function run(profile, v, fp) {
  try { return E.priceChain(profile, toInput(v, fp)); }
  catch (e) { return { priceable: false, thrown: String(e && e.message) }; }
}

/** Does a departure's `appliesWhen` hold for this case? (The same reader oracle-polish-harness.js has.) */
function holds(cond, v) {
  if (cond.allOf) return cond.allOf.every((c) => holds(c, v));
  if (cond.anyOf) return cond.anyOf.some((c) => holds(c, v));
  if (cond.in !== undefined) {
    const x = v.in[cond.in] === undefined ? 0 : v.in[cond.in];
    return "ne" in cond ? x !== cond.ne : x === cond.eq;
  }
  if (cond.answers !== undefined) {
    const x = v.out.answers[cond.answers];
    return "ne" in cond ? x !== cond.ne : x === cond.eq;
  }
  if (cond.out !== undefined) {
    const x = v.out[cond.out];
    return cond.nonzero ? (typeof x === "number" && x !== 0) : x === cond.eq;
  }
  if (cond.rows !== undefined) return new Set((v.rows || []).map((r) => r.rate)).size > 1;
  throw new Error("departures.json: a condition this harness does not know: " + JSON.stringify(cond));
}

const out = { tabs: {}, flips: {}, pins: [], odd: {}, departures: {}, wrapper: {}, profiles: {} };

// ── 1. every tab, every case, no excuses ─────────────────────────────────────
const TABS = P.priced.map((tab) => ({ tab, fp: E.forTab(tab), golden: load(P.sheets[tab].slug) }));
for (const { tab, fp, golden } of TABS) {
  const rec = { profile: fp.profile.stamp, vectors: golden.vectors.length, exact: 0, mismatches: [] };
  for (const v of golden.vectors) {
    const r = run(fp.profile, v, fp);
    const d = r.priceable === false ? [{ key: "(priceable)", oracle: true, engine: r.thrown || r.reason }] : diffs(v, r);
    if (d.length) { if (rec.mismatches.length < 12) rec.mismatches.push({ id: v.id, diffs: d.slice(0, 4) }); rec.bad = (rec.bad || 0) + 1; }
    else rec.exact++;
  }
  out.tabs[tab] = rec;
}

// ── 2. quirk flips ───────────────────────────────────────────────────────────
function flipped(profile, quirk) {
  const q = Object.assign({}, profile.quirks);
  const v = q[quirk];
  q[quirk] = typeof v === "boolean" ? !v
    : quirk === "remodelBase" ? (v === "sheet" ? "model" : "sheet")
    : quirk === "remodelRateDefault" ? (v === "sheet" ? "state" : "sheet")
    : quirk === "shippingRule" ? (v === "rate" ? "gyp-split" : "rate")
    : quirk === "lodgingDivisor" ? (v === 8 ? 10 : 8)
    : quirk === "dayHours" ? (v === 8 ? 10 : 8)
    : (() => { throw new Error("harness: no flip for " + quirk); })();
  return Object.assign({}, profile, { quirks: q });
}
for (const { tab, fp, golden } of TABS) {
  for (const quirk of P.quirks) {
    const other = flipped(fp.profile, quirk);
    let changed = 0;
    for (const v of golden.vectors) {
      const r = run(other, v, fp);
      if (r.priceable === false || diffs(v, r).length) changed++;
    }
    out.flips[tab + " / " + quirk] = changed;
  }
}

// ── 3. the pins: a profile's rates are the workbook's constants ──────────────
const PINNED = [["burdenPct", "burden_pct"], ["superPct", "super_pto"], ["softPct", "soft_costs"], ["shipPct", "ship_pct"],
  ["escPctMat", "material_esc_pct"], ["shipGypPct", "ship_gyp_pct"], ["shipOtherPct", "ship_other_pct"], ["escPct", "esc_pct"]];
for (const { tab, fp, golden } of TABS) {
  for (const [fixed, line] of PINNED) {
    if (!(fixed in golden.fixed)) continue;
    if (golden.fixed[fixed] === null || typeof golden.fixed[fixed] !== "number") continue;
    // Gyp's soft costs is an expression, not a constant: its fixed cell is the formula's last answer.
    if (line === "soft_costs" && fp.profile.layout === "gyp") continue;
    out.pins.push({ tab, fixed, line, workbook: golden.fixed[fixed], profile: E.rateNumber(fp.profile.rates[line]) });
  }
  out.pins.push({ tab, fixed: "dayHours", line: "dayHours", workbook: golden.fixed.dayHours, profile: fp.profile.quirks.dayHours + " hour days" });
  if (golden.fixed.truckload !== undefined) {
    out.pins.push({ tab, fixed: "truckload", line: "truckload", workbook: golden.fixed.truckload, profile: fp.truckload });
  }
  const labor = P.sheets[tab].rates.laborRate;
  if (labor.value !== undefined) {
    out.pins.push({ tab, fixed: "laborRate", line: "labor_rate", workbook: labor.value, profile: E.rateNumber(fp.profile.rates.labor_rate, "dollars") });
  }
}

// ── 4. the odd rules that live in the chain ──────────────────────────────────
// Each is tested on the cases the oracle recorded: the engine matched the sheet there (section 1), and here
// the ordinary reading is computed and must be DIFFERENT, so the case shows the odd rule and not a tie.
const perCase = (tab, fn) => {
  const t = TABS.find((x) => x.tab === tab);
  return t.golden.vectors.filter((v) => !v.id.startsWith("lodging/")).map((v) => ({ v, r: run(t.fp.profile, v, t.fp), fp: t.fp }))
    .filter(({ v, r }) => r.priceable !== false && fn(v, r));
};
const ODD_CHAIN = {
  // The bond base adds `taxes` on top of the two taxes it already holds.
  "bond-twice": () => {
    const tabs = P.priced.filter((t) => TABS.find((x) => x.tab === t).fp.profile.quirks.bondInput);
    let seen = 0;
    for (const tab of tabs) for (const { v, r } of perCase(tab, (v, r) => r.bond_pct > 0 && r.taxes > 0)) {
      const once = roundUp((r.sub_total + r.gp + r.hard_bid + r.super_pto + r.soft_costs + r.contingency + r.sales_tax + r.remodel_tax + r.fees) * r.bond_pct);
      if (once !== r.bond && same(v.out.bond, r.bond)) seen++;
    }
    return seen;
  },
  // Leveling counts nights over 8 although its days are 10 hours.
  "leveling-lodging-eight": () => {
    const t = TABS.find((x) => x.tab === "Leveling");
    let seen = 0;
    for (const v of t.golden.vectors) {
      if (v.out.answers.local || !(v.in.labor > 0)) continue;
      const r = run(t.fp.profile, v, t.fp);
      const qty10 = ((r.labor - (v.in.travelLabor || 0)) / 33.66) / 10;
      if (r.lodging_qty !== qty10 && same(v.out.lodgingQty, r.lodging_qty)) seen++;
    }
    return seen;
  },
  // Leveling's sub-total leaves the escalation out although the escalation is shown.
  "leveling-escalation-left-out": () => perCase("Leveling", (v, r) => r.escalation > 0 && same(v.out.subTotal, r.sub_total))
    .filter(({ r }) => roundUp(r.material_total + r.labor + r.escalation + r.burden + r.tooling + r.travel) !== r.sub_total).length,
  // Epoxy's GP divides the fees up and does not take them back off.
  "epoxy-gp-without-fees": () => perCase("Epoxy", (v, r) => r.fees > 0 && same(v.out.gp, r.gp))
    .filter(({ r }) => roundUp((r.sub_total + r.sales_tax + r.fees) / (1 - r.gp_pct)) - roundUp(r.sub_total + r.sales_tax + r.fees) !== r.gp).length,
  // Gyp's escalation is 5% whatever Prevailing Wage says.
  "gyp-escalation-always-five": () => perCase("Gyp (USG 1-8\")", (v, r) => !v.out.answers.prevailingWage && r.labor > 0 && r.escalation === roundUp(r.labor * 0.05)).length,
  // The sound mat ships free from a truckload on.
  "gyp-mat-shipping-truckload": () => {
    let seen = 0;
    for (const t of TABS.filter((x) => x.fp.profile.layout === "gyp")) {
      for (const v of t.golden.vectors) {
        if (!(v.in.soundMat > 0) || !(v.in.soundMatRolls >= t.fp.truckload)) continue;
        const r = run(t.fp.profile, v, t.fp);
        const withMat = roundUp(v.in.gyp * 0.2) + roundUp((v.in.extras + v.in.soundMat) * 0.1);
        if (withMat !== r.shipping && same(v.out.shipping, r.shipping)) seen++;
      }
    }
    return seen;
  },
  // Shipping tiers count their edge, GP bands do not: exactly 5,000 of material is still the 15% tier, and a
  // sub-total of exactly 6,500 is already on the 45% rung.
  "edge-tiers-and-bands": () => {
    const t = TABS.find((x) => x.tab === "Epoxy");
    const byId = (id) => t.golden.vectors.find((v) => v.id === id);
    const tier = byId("edge/shipPct/5000/0"), band = byId("edge/gpPct/6500/0");
    if (!tier || !band) return 0;
    const a = run(t.fp.profile, tier, t.fp), b = run(t.fp.profile, band, t.fp);
    return (a.ship_pct === 0.15 && b.gp_pct === 0.45 && same(tier.out.shipPct, a.ship_pct) && same(band.out.gpPct, b.gp_pct)) ? 1 : 0;
  }
};
// which odd-rules.json ids each ODD_CHAIN test belongs to; an id in neither list fails the test
const RULE_TEST = { "bond-twice": "bond-twice", "leveling-lodging-eight": "leveling-lodging-eight",
  "leveling-escalation-left-out": "leveling-escalation-left-out", "epoxy-gp-without-fees": "epoxy-gp-without-fees",
  "gyp-escalation-always-five": "gyp-escalation-always-five", "gyp-mat-shipping-truckload": "gyp-mat-shipping-truckload",
  "ship-tiers-inclusive-gp-strict": "edge-tiers-and-bands" };
out.odd.ruleIds = odd.rules.map((r) => r.id);
out.odd.chain = Object.fromEntries(Object.keys(ODD_CHAIN).map((k) => [k, ODD_CHAIN[k]()]));
out.odd.testFor = RULE_TEST;

// ── 4b. the probes that start at the chain's own boundary ────────────────────────────────────────────
// Two of the oracle's probes set a cell the chain reads and read a cell it writes, so the engine can answer them:
// the sound mat's shipping at a truckload minus one, at it and above it (Gyp), and Leveling's lodging nights with
// the day-length cell left at 10 hours and changed to 8 (the nights do not move).
out.probes = [];
for (const { tab, fp, golden } of TABS) {
  for (const pr of golden.probes) {
    if (pr.id === "sound-mat-truckload") {
      for (const st of pr.steps) {
        const r = E.priceChain(fp.profile, { soundMat: st.set.E36, soundMatRolls: st.set.B36, truckload: fp.truckload });
        out.probes.push({ tab, probe: pr.id, rolls: st.set.B36, truckload: st.got.H36, sheet: st.got.E40, engine: r.shipping });
      }
    }
    if (pr.id === "lodging-divisor") {
      for (const st of pr.steps) {
        const r = E.priceChain(fp.profile, { labor: st.set.D49, conditions: { local: false } });
        out.probes.push({ tab, probe: pr.id, label: st.label, sheet: st.got.B61, engine: r.lodging_qty, sheetDollars: st.got.D61, engineDollars: r.lodging });
      }
    }
  }
}

// ── 5. the departures: polish-legacy against the sheet's own polish profile ──
{
  const t = TABS.find((x) => x.tab === "Polish");
  const legacy = E.resolveProfile("polish-legacy");
  const chain = dep.departures.filter((d) => d.scope === "chain");
  out.departures = { vectors: 0, exact: 0, excused: 0, unexplained: [], seen: Object.fromEntries(chain.map((d) => [d.id, 0])) };
  for (const v of t.golden.vectors.filter((x) => !x.id.startsWith("lodging/"))) {
    out.departures.vectors++;
    const sheet = run(t.fp.profile, v, t.fp);
    const mine = run(legacy, v, t.fp);
    const allowed = new Set();
    const active = chain.filter((d) => holds(d.appliesWhen, v));
    for (const d of active) for (const k of d.keys) allowed.add(k);
    const delta = [];
    for (const [name, key] of KEYS) {
      if (name in dep.outputKeys && !same(sheet[key], mine[key])) delta.push(name);
    }
    for (const d of active) if (delta.some((k) => d.keys.includes(k))) out.departures.seen[d.id]++;
    const loose = delta.filter((k) => !allowed.has(k));
    if (loose.length) out.departures.unexplained.push({ id: v.id, keys: loose });
    else if (delta.length) out.departures.excused++;
    else out.departures.exact++;
  }
}

// ── 6. the wrapper: bid-model's markupChain is the engine on polish-legacy ───
{
  let M = null;
  try { M = require(path.join(FRONTEND, "js", "bid-model.js")); } catch (e) { out.wrapper.error = String(e && e.message); }
  if (M) {
    const t = TABS.find((x) => x.tab === "Polish");
    const legacy = E.resolveProfile("polish-legacy");
    let compared = 0, differ = 0;
    const KEYS_OF_CHAIN = Object.keys(M.markupChain({}));
    out.wrapper.keys = KEYS_OF_CHAIN;
    for (const v of t.golden.vectors.filter((x) => !x.id.startsWith("lodging/"))) {
      const input = toInput(v, t.fp);
      const m = M.markupChain({
        material: input.material, labor: input.labor, travel: input.travel, fees: input.fees, contingency: input.contingency,
        sf: input.sf, conditions: { prevailing_wage: input.conditions.prevailing_wage, taxable: input.conditions.taxable, remodel_tax: input.conditions.remodel_tax },
        remodel_rate: input.remodel_rate
      });
      const r = E.priceChain(legacy, input);
      compared++;
      if (!KEYS_OF_CHAIN.every((k) => same(m[k], r[k]))) differ++;
    }
    out.wrapper.compared = compared;
    out.wrapper.differ = differ;
  }
}

// ── 7. the formulas: a profile's rate TEXT against the workbook's own cell formula ───────────────────────
// The cell maps carry the formula text the template holds (and test_workbook_formula_pins.py holds that to the
// template). A profile's ladder, tier table, hard bid and Gyp soft costs are written once more in the Markups
// vocabulary, so each is evaluated beside the cell's own formula (markup-core reads both) over every edge of the
// formula, one either side, and the two have to agree everywhere. That is what "taken from the template's
// formula text, pinned" means: a changed edge in either place shows as the first number they disagree on.
{
  const K = require(path.join(FRONTEND, "js", "markup-core.js"));
  const strip = (f) => String(f).replace(/^=/, "");
  const edgesOf = (formula) => {
    const at = new Set([0, 1, 10, 1000, 1e6]);
    const re = /[<>]=?\s*(\d+(?:\.\d+)?)/g;
    let m;
    while ((m = re.exec(formula)) !== null) { const n = Number(m[1]); at.add(n - 1); at.add(n); at.add(n + 1); }
    return Array.from(at).sort((a, b) => a - b);
  };
  const num0 = (x) => (x === false ? 0 : x);
  out.formulas = [];
  for (const { tab, fp } of TABS) {
    const map = P.sheets[tab], rates = fp.profile.rates;
    const check = (line, kind, formula, grid, sheetCtx, ownCtx) => {
      let checked = 0; const bad = [];
      for (const x of grid) {
        for (const [sc, oc] of sheetCtx(x).map((s, i) => [s, ownCtx(x)[i]])) {
          const want = num0(K.evaluate(K.parse(strip(formula)), sc));
          const got = E.rateNumber(rates[line], kind, oc);
          checked++;
          if (!same(want, got) && bad.length < 5) bad.push({ at: x, sheet: want, profile: got });
        }
      }
      out.formulas.push({ tab, line, checked, bad });
    };
    const sub = map.outputs.subTotal.addr;
    if (map.outputs.gpPct) {
      check("gp", "gp", map.outputs.gpPct.formula, edgesOf(map.outputs.gpPct.formula),
        (x) => [Object.fromEntries([[sub, x]])], (x) => [{ subtotal: x, sub_total: x }]);
    }
    if (map.outputs.shipPct) {
      check("ship_pct", "rate", map.outputs.shipPct.formula, edgesOf(map.outputs.shipPct.formula),
        (x) => [Object.fromEntries([[map.inputs.material.addr, x]])], (x) => [{ material: x }]);
    }
    if (map.outputs.hardBidPct && rates.hard_bid) {
      const flagAddr = map.flags.hardBid.addr, localAddr = map.flags.local.addr;
      const answers = [["Yes", "Yes"], ["Yes", "No"], ["No", "Yes"], ["No", "No"]];
      check("hard_bid", "signed", map.outputs.hardBidPct.formula, edgesOf(map.outputs.hardBidPct.formula),
        (x) => answers.map(([h, l]) => Object.fromEntries([[sub, x], [flagAddr, h], [localAddr, l]])),
        (x) => answers.map(([h, l]) => ({ subtotal: x, hard_bid: h, local: l })));
    }
    if (map.outputs.softPct) {
      const local = map.flags.local.addr;
      const answers = ["Yes", "No"];
      check("soft_costs", "rate", map.outputs.softPct.formula, edgesOf(map.outputs.softPct.formula),
        (x) => answers.map((l) => Object.fromEntries([[sub, x], [local, l]])),
        (x) => answers.map((l) => ({ sub_total: x, local: l, B5: l, E69: x })));
    }
    if (map.outputs.salesTaxPct) {
      const taxable = map.flags.taxable.addr;
      // Taxable = Yes only: with "No" the sheet's cell reads 0 and the engine never reads the rate at all
      // (sales_tax_pct is 0 on a non-taxable job, which section 1 compares on every case).
      check("sales_tax", "rate", map.outputs.salesTaxPct.formula, [0],
        () => [Object.fromEntries([[taxable, "Yes"]])], () => [{}]);
    }
  }
}

// ── 8. a tab's profile prices on the layout the vocabulary says the tab has ───────────────────────────
{
  const T = require(path.join(FRONTEND, "js", "work-types.js"));
  out.layouts = TABS.map(({ tab, fp }) => ({ tab, vocabulary: T.tab(T.tabOfSheet(tab)).markupLayout, profile: fp.profile.layout }));
}

// ── 9. profiles are data ─────────────────────────────────────────────────────
for (const id of Object.keys(P.profiles)) {
  const r = E.resolveProfile(id);
  out.profiles[id] = { json: JSON.stringify(P.profiles[id]) === JSON.stringify(JSON.parse(JSON.stringify(P.profiles[id]))),
    chain: r.chain, layout: r.layout, stamp: r.stamp };
}

console.log(JSON.stringify(out));
