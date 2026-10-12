"use strict";
/* A BID PRICED ON SEVERAL WORKBOOK TABS: the model's sections, the rates each keeps, the one composition of
 * what a save writes for the proposal side, and the new-bid seeding per section.
 *
 * Phase 10 of the v2 estimating program. Everything here EXECUTES the real js/bid-model.js and
 * js/bid-engine.js (and, in the last section, the real estimate page, polish-estimate.js whole, through
 * polish-estimate-harness.js's own boot code). Nothing is a source assertion. One line of JSON comes out and
 * test_v2_multi_section.py asserts on it, then breaks a scratch copy of the code in several ways and requires
 * the facts to change.
 *
 * Every section catches its own failure and reports it as `{error}`, so the same harness can run over a tree
 * that does not have the functions and fail as an assertion, not a crash.
 *
 * Usage: node multi-section-harness.js <frontend-dir>   ->  one line of JSON
 */
const path = require("path");
const Module = require("module");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const B = require(path.join(ROOT, "js", "bid-model.js"));
const E = require(path.join(ROOT, "js", "bid-engine.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));
const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
const threw = (fn) => { try { fn(); return null; } catch (e) { return String(e && e.message || e); } };
function deepFreeze(v) {
  if (v && typeof v === "object" && !Object.isFrozen(v)) {
    Object.freeze(v);
    Object.keys(v).forEach((k) => deepFreeze(v[k]));
  }
  return v;
}

// ── fixtures ──────────────────────────────────────────────────────────────────────────────────
const RULE = (layout, line, formula, applies) =>
  ({ layout: layout, line_key: line, formula: formula, applies: applies !== false });
/** The one rule filed on production on 2026-10-12: polish bond 1%. */
const PROD_RULES = [RULE("polish", "bond", "1%")];

/** A saved Polish bid, the way the page writes it: no `tabs`, no snapshot, root keys only. */
function polishBid() {
  const m = B.freshModel();
  m.takeoff = [{ assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: 10000, unit: "SF" }];
  m.labor = [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33 }];
  return m;
}
/** Material per section, as the page would price a takeoff from its library. */
const MATERIAL = { Polish: 10000, Epoxy: 8000, Seal: 1500, 'Gyp (USG 1-8")': 6000 };
const ctxOf = (extra) => Object.assign({ material: (e) => MATERIAL[e.tab] }, extra || {});
function withEpoxy(rules) {
  let m = B.activateSection(polishBid(), "Epoxy", "base", { rules: rules || [] });
  m.tabs.Epoxy.takeoff = [{ assembly_id: "e1", assembly_name: "Flake", measurement: 4000, unit: "SF" },
                          { assembly_id: "e2", assembly_name: "Cove", measurement: 300, unit: "LF" }];
  m.tabs.Epoxy.labor = [{ id: "installing", label: "Installing", guys: 3, days: 4, rate: 33 }];
  return m;
}
function comboWithSeal() {
  let m = withEpoxy([RULE("epoxy", "soft_costs", "10%")]);
  m = B.activateSection(m, "Seal", "option", {});
  m.tabs.Seal.takeoff = [{ assembly_id: "s1", assembly_name: "Seal", measurement: 10000, unit: "SF" }];
  m.tabs.Seal.labor = [{ id: "sealing", label: "Sealing", guys: 2, days: 1, rate: 33 }];
  return m;
}
/** What the page prices the root with: markupChain over the model's own rows. */
function rootBid(m, material) {
  return B.markupChain({ material: material, labor: B.laborTotal(m.labor, m.conditions),
    travel: B.travelCosts(m.travel, m.labor).total, contingency: m.contingency, fees: m.fees,
    conditions: m.conditions, sf: B.takeoffSf(m.takeoff), remodel_rate: null });
}
const priceAll = (m) => ({ bid: rootBid(m, MATERIAL.Polish), bids: B.priceTabs(m, ctxOf()) });

// ── 1. sectionsOf ─────────────────────────────────────────────────────────────────────────────
function sectionsSection() {
  const single = polishBid();
  const one = B.sectionsOf(single);
  const multi = comboWithSeal();
  const list = B.sectionsOf(multi);
  // by reference: a write through the entry is a write to the model
  list[1].section.contingency = 77;
  list[0].section.fees = 5;
  const bad = (mut) => { const m = comboWithSeal(); mut(m); return threw(() => B.sectionsOf(m)); };
  const tab = (m, id) => m.tabs[id];
  return {
    single: { length: one.length, tab: one[0].tab, root: one[0].root, isModel: one[0].section === single,
              kind: one[0].kind, profile: one[0].profile, layout: one[0].layout, role: one[0].role },
    multi: { tabs: list.map((e) => e.tab), kinds: list.map((e) => e.kind), roles: list.map((e) => e.role),
             layouts: list.map((e) => e.layout), profiles: list.map((e) => e.profile),
             byRefTab: multi.tabs.Epoxy.contingency, byRefRoot: multi.fees },
    activeSkipsOff: (() => { const m = comboWithSeal(); m.tabs.Seal.kind = "off";
      return B.activeSections(m).map((e) => e.tab); })(),
    rootOff: (() => { const m = polishBid(); m.kind = "off"; return B.sectionsOf(m)[0].kind; })(),
    rootProfileKeyIsReserved: (() => { const m = polishBid(); m.profile = "polish@1"; m.kind = "option";
      return B.sectionsOf(m)[0].profile; })(),
    throws: {
      noLayout: bad((m) => { delete tab(m, "Epoxy").layout; }),
      wrongLayout: bad((m) => { tab(m, "Epoxy").layout = "gyp"; }),
      badKind: bad((m) => { tab(m, "Epoxy").kind = "primary"; }),
      noProfile: bad((m) => { delete tab(m, "Epoxy").profile; }),
      junkProfile: bad((m) => { tab(m, "Epoxy").profile = "epoxy"; }),
      otherLayoutProfile: bad((m) => { tab(m, "Epoxy").profile = "gyp@1"; }),
      notATab: bad((m) => { m.tabs.Takeoff = clone(m.tabs.Epoxy); }),
      polishUnderTabs: bad((m) => { m.tabs.Polish = clone(m.tabs.Epoxy); }),
      tabsNotAnObject: bad((m) => { m.tabs = [1]; }),
      sectionNotAnObject: bad((m) => { m.tabs.Epoxy = 5; }),
      noModel: threw(() => B.sectionsOf(null)),
    },
    unknownProfileIdIsNotRefusedHere: (() => { const m = comboWithSeal(); m.tabs.Epoxy.profile = "epoxy-x@1";
      return threw(() => B.sectionsOf(m)); })(),
  };
}

// ── 2. new sections and the gate on seeding them ──────────────────────────────────────────────
function newSection() {
  const empty = { layout: "epoxy", kind: "base", profile: "epoxy@1", takeoff: [{ assembly_id: "", measurement: "" }], labor: [] };
  return {
    rootIsLaborUnstated: [undefined, null, {}, { version: 2 }, { version: 2, labor: [] }, { version: 2, labor: [{ id: "x" }] },
                          { areas: [] }].map((s) => B.isNewSection(s, true) === B.laborUnstated(s)),
    tabEmpty: B.isNewSection(empty, false),
    tabNotAnObject: B.isNewSection(null, false),
    tabWithLabor: B.isNewSection(Object.assign(clone(empty), { labor: [{ id: "a" }] }), false),
    tabWithPick: B.isNewSection(Object.assign(clone(empty), { takeoff: [{ assembly_id: "e1", measurement: "" }] }), false),
    tabWithMeasurement: B.isNewSection(Object.assign(clone(empty), { takeoff: [{ assembly_id: "", measurement: 5 }] }), false),
    tabWithSnapshotButNothingStated: B.isNewSection(Object.assign(clone(empty), { rates: { version: 1, rates: {} } }), false),
    activatedIsNew: (() => { const m = B.activateSection(polishBid(), "Epoxy", "base", {});
      return B.isNewSection(m.tabs.Epoxy, false); })(),
  };
}

// ── 3. activating a section keeps its rates ───────────────────────────────────────────────────
function activation() {
  const base = polishBid();
  const frozen = deepFreeze(clone(base));
  let frozenThrew = null, m = null;
  try { m = B.activateSection(frozen, "Epoxy", "base", { rules: [RULE("epoxy", "soft_costs", "10%")] }); }
  catch (e) { frozenThrew = String(e); }
  const s = m && m.tabs.Epoxy;
  const noted = B.activateSection(polishBid(), "Epoxy", "base", { rules: [
    RULE("epoxy", "soft_costs", "abc"), RULE("epoxy", "super_pto", ""), RULE("epoxy", "gp", "150%"),
    RULE("global", "bond", "1%"), RULE("polish", "bond", "1%"), RULE("global", "labor_rate", "$41"),
    RULE("global", "fees_textura", "250"), RULE("epoxy", "labor_rate", "99", false)] }).tabs.Epoxy;
  const gypTab = 'Gyp (USG 1-8")';
  return {
    frozenThrew: frozenThrew,
    shape: s ? { keys: Object.keys(s), layout: s.layout, kind: s.kind, profile: s.profile, labor: s.labor.length,
                 takeoffRows: s.takeoff.length, contingency: s.contingency, fees: s.fees } : null,
    snapshot: s ? s.rates : null,
    rootUntouched: m ? !has(m, "profile") && !has(m, "rates") && !has(base, "tabs") && !has(frozen, "tabs") : null,
    noRules: B.activateSection(polishBid(), "Epoxy", "base", {}).tabs.Epoxy.rates,
    noCtx: B.activateSection(polishBid(), "Epoxy", "base").tabs.Epoxy.rates.rates,
    // a rule that will not price is left out and SAID, and a bond rule is not taken
    notedRates: noted.rates.rates, notedNotes: noted.rates.notes, notedFees: noted.rates.fees_default,
    gypProfile: B.activateSection(polishBid(), gypTab, "base", {}).tabs[gypTab].profile,
    sealProfile: B.activateSection(polishBid(), "Seal (+Jnts)", "option", {}).tabs["Seal (+Jnts)"].profile,
    refuses: {
      polish: threw(() => B.activateSection(polishBid(), "Polish", "base", {})),
      notATab: threw(() => B.activateSection(polishBid(), "Takeoff", "base", {})),
      badKind: threw(() => B.activateSection(polishBid(), "Epoxy", "off", {})),
      sealAsBase: threw(() => B.activateSection(polishBid(), "Seal", "base", {})),
      levelingAsBase: threw(() => B.activateSection(polishBid(), "Leveling", "base", {})),
      twice: threw(() => B.activateSection(B.activateSection(polishBid(), "Epoxy", "base", {}), "Epoxy", "option", {})),
    },
    snapshotCopyIsOwn: (() => { const r = [RULE("epoxy", "soft_costs", "10%")];
      const a = B.activateSection(polishBid(), "Epoxy", "base", { rules: r });
      r[0].formula = "20%"; return a.tabs.Epoxy.rates.rates.soft_costs; })(),
  };
}

// ── 4. a saved bid never reprices because somebody edits the Markups rules ────────────────────
function noReprice() {
  const filed = [RULE("epoxy", "soft_costs", "20%"), RULE("epoxy", "gp", "MARKUP(30%)")];
  const total = (m, tab, ctx) => B.priceSection(m, tab, ctxOf(ctx)).total;

  // (a) a section with NO snapshot prices at the profile's built-ins, whatever is filed
  const bare = withEpoxy([]);
  delete bare.tabs.Epoxy.rates;
  const builtIn = E.priceChain("epoxy", { material: MATERIAL.Epoxy, labor: B.laborTotal(bare.tabs.Epoxy.labor, bare.conditions),
    travel: 0, contingency: 0, fees: 0, conditions: bare.conditions, sf: 4000, remodel_rate: null }).total;
  // (b) the same bid activated AFTER the rules were filed honours them, as a snapshot
  const honoured = withEpoxy(filed);
  // (c) ... and editing the filed rules afterwards moves neither
  const edited = clone(honoured);
  const afterEdit = [RULE("epoxy", "soft_costs", "30%"), RULE("epoxy", "gp", "MARKUP(10%)")];
  // (d) the production rule (polish bond 1%) reaches nothing: not the root, not a new section
  const prodBare = polishBid();
  const prodNew = withEpoxy(PROD_RULES);
  const prodSeeded = B.seedNewSections(prodBare, { saved: prodBare, rules: PROD_RULES, laborRate: 33 });
  const noRules = withEpoxy([]);
  return {
    bareTotal: total(bare, "Epoxy"), builtInTotal: builtIn,
    bareIgnoresFiled: total(bare, "Epoxy", { rules: filed, filed: filed }) === builtIn,
    honouredTotal: total(honoured, "Epoxy"), honouredDiffers: total(honoured, "Epoxy") !== builtIn,
    editedAfterTotal: total(edited, "Epoxy", { rules: afterEdit }), editedSame: total(edited, "Epoxy", { rules: afterEdit }) === total(honoured, "Epoxy"),
    prodRuleRootTotal: B.priceSection(prodBare, "Polish", ctxOf({ rules: PROD_RULES })).total,
    prodRuleRootChain: rootBid(prodBare, MATERIAL.Polish).total,
    // the root is priced at the built-ins whatever is filed, a Polish gross profit rule included
    rootIgnoresFiled: B.priceSection(prodBare, "Polish", ctxOf({ rules: [RULE("polish", "gp", "MARKUP(10%)"), RULE("polish", "soft_costs", "30%")] })).total
      === rootBid(prodBare, MATERIAL.Polish).total,
    prodRuleSeedLeavesTheModel: JSON.stringify(prodSeeded) === JSON.stringify(prodBare),
    prodRuleNewSectionTotal: total(prodNew, "Epoxy"), noRuleNewSectionTotal: total(noRules, "Epoxy"),
    prodRuleKept: prodNew.tabs.Epoxy.rates.rates, prodRuleNotes: prodNew.tabs.Epoxy.rates.notes,
    // a rule that cannot be read is the built-in with a note, never $0
    unreadable: (() => { const m = withEpoxy([RULE("epoxy", "soft_costs", "abc"), RULE("epoxy", "super_pto", "")]);
      return { total: total(m, "Epoxy"), builtIn: total(noRules, "Epoxy"), notes: m.tabs.Epoxy.rates.notes.length }; })(),
    // a snapshot a person edits into something unreadable prices as unpriceable, never $0
    hand: (() => { const m = withEpoxy([]); m.tabs.Epoxy.rates.rates.soft_costs = "abc";
      const r = B.priceSection(m, "Epoxy", ctxOf()); return { priceable: r.priceable, total: r.total, line: r.line }; })(),
    otherVersion: (() => { const m = withEpoxy([RULE("epoxy", "soft_costs", "20%")]); m.tabs.Epoxy.rates.version = 9;
      return total(m, "Epoxy") === total(noRules, "Epoxy"); })(),
  };
}

// ── 5. priceSection ───────────────────────────────────────────────────────────────────────────
function pricing() {
  const m = comboWithSeal();
  const bids = B.priceTabs(m, ctxOf());
  const root = B.priceSection(m, "Polish", ctxOf());
  const rootChain = rootBid(m, MATERIAL.Polish);
  const chainKeys = Object.keys(rootChain);
  // the job's travel is charged to the carrier only
  const far = comboWithSeal();
  far.conditions.local = false;
  far.travel.lodging.enabled = true; far.travel.lodging.qty = 10; far.travel.lodging.qty_auto = false; far.travel.lodging.rate = 100;
  const farRoot = B.priceSection(far, "Polish", ctxOf());
  const farEpoxy = B.priceSection(far, "Epoxy", ctxOf());
  const noTravel = comboWithSeal(); noTravel.conditions.local = false;
  const swapped = comboWithSeal(); swapped.kind = "off";
  const swappedFar = clone(far); swappedFar.kind = "off";
  const gyp = 'Gyp (USG 1-8")';
  const g = B.activateSection(polishBid(), gyp, "base", {});
  g.tabs[gyp].takeoff = [{ assembly_id: "g1", assembly_name: "Underlayment", measurement: 9000, unit: "SF" }];
  g.tabs[gyp].labor = [{ id: "inst", label: "Install", guys: 4, days: 3, rate: 33.66 }];
  const stale = comboWithSeal(); stale.tabs.Epoxy.profile = "epoxy@2";
  const unknown = comboWithSeal(); unknown.tabs.Epoxy.profile = "epoxy-x@1";
  const objectMaterial = B.priceSection(g, gyp, { material: () => ({ gyp: 6000, extras: 200, sand: 100, soundMat: 300, soundMatRolls: 40 }) });
  return {
    rootEqualsChain: chainKeys.every((k) => root[k] === rootChain[k]),
    rootTotal: root.total, rootChainTotal: rootChain.total,
    tabs: Object.keys(bids), epoxy: bids.Epoxy.total, seal: bids.Seal.total,
    epoxyGp: bids.Epoxy.gp_pct, epoxyProfile: bids.Epoxy.profile, sealProfile: bids.Seal.profile,
    epoxyRemodelDefault: (() => { const r = withEpoxy([]); r.conditions.remodel_tax = true;
      return B.priceSection(r, "Epoxy", ctxOf({ remodel_rate: 0.07 })).remodel_pct; })(),
    carrier: B.travelCarrier(m), carrierWhenRootOff: B.travelCarrier(swapped),
    farTravel: { root: farRoot.travel, epoxy: farEpoxy.travel },
    noTravelRoot: B.priceSection(noTravel, "Polish", ctxOf()).travel,
    carrierMoves: { epoxy: B.priceSection(swappedFar, "Epoxy", ctxOf()).travel, root: threw(() => B.priceSection(swappedFar, "Polish", ctxOf())) },
    stale: (() => { const r = B.priceSection(stale, "Epoxy", ctxOf()); return { priceable: r.priceable, total: r.total, line: r.line, reason: r.reason }; })(),
    unknownProfile: (() => { const r = B.priceSection(unknown, "Epoxy", ctxOf()); return { priceable: r.priceable, total: r.total, line: r.line }; })(),
    gyp: { priceable: objectMaterial.priceable, total: objectMaterial.total, profile: objectMaterial.profile,
           materialEscalation: objectMaterial.material_escalation > 0 },
    gypNumberMaterialThrows: (() => { const r = B.priceSection(g, gyp, { material: () => 6000 });
      return { priceable: r.priceable, total: r.total }; })(),
    needsMaterial: threw(() => B.priceSection(m, "Epoxy", {})),
    unknownSection: threw(() => B.priceSection(m, "Leveling", ctxOf())),
    pricesAreNumbers: Object.values(bids).every((b) => typeof b.total === "number"),
    noTabsIsEmpty: JSON.stringify(B.priceTabs(polishBid(), ctxOf())),
    offIsNotPriced: (() => { const o = comboWithSeal(); o.tabs.Seal.kind = "off"; return Object.keys(B.priceTabs(o, ctxOf())); })(),
  };
}

// ── 6. composePricingSnapshot ─────────────────────────────────────────────────────────────────
function composer() {
  const single = polishBid();
  const sb = priceAll(single);
  const one = B.composePricingSnapshot(single, { bid: sb.bid });
  const m = comboWithSeal();
  const p = priceAll(m);
  const frozenModel = deepFreeze(clone(m));
  let frozenThrew = null, d = null;
  try { d = B.composePricingSnapshot(frozenModel, deepFreeze(clone(p))); } catch (e) { frozenThrew = String(e); }
  d = d || B.composePricingSnapshot(m, p);
  const base = d.priced_tabs.filter((t) => t.kind === "base");
  const sumOfParts = base.reduce((t, x) => t + x.total, 0);
  // pooled: one chain over the base sections' sub-totals, which is NOT what is written
  const pooled = (() => { const e = p.bids.Epoxy, r = p.bid;
    return B.markupChain({ material: MATERIAL.Polish + MATERIAL.Epoxy, labor: B.laborTotal(m.labor, m.conditions) + B.laborTotal(m.tabs.Epoxy.labor, m.conditions),
      travel: 0, contingency: 0, fees: 0, conditions: m.conditions, sf: 14000, remodel_rate: null }).total; })();
  const unpriceable = clone(p); unpriceable.bids.Epoxy = { priceable: false, profile: "epoxy@1", line: "GP", reason: "no rate", total: null };
  const u = B.composePricingSnapshot(m, unpriceable);
  const rootOff = comboWithSeal(); rootOff.kind = "off";
  const ro = B.composePricingSnapshot(rootOff, { bids: p.bids });
  const sealOnly = polishBid(); sealOnly.kind = "off";
  const sealTab = B.activateSection(sealOnly, "Seal", "option", {});
  sealTab.tabs.Seal.takeoff = [{ assembly_id: "s1", assembly_name: "Seal", measurement: 10000, unit: "SF" }];
  const so = B.composePricingSnapshot(sealTab, { bids: B.priceTabs(sealTab, ctxOf()) });
  const taxed = comboWithSeal(); taxed.conditions.taxable = false; taxed.conditions.remodel_tax = true;
  const t = B.composePricingSnapshot(taxed, priceAll(taxed));
  const stamped = d.polish_estimate;
  const cpy = comboWithSeal(); cpy.tabs.Seal.kind = "base";                      // an option-only tab declared as a base
  const sealBase = B.composePricingSnapshot(cpy, priceAll(cpy));
  return {
    singleKeys: Object.keys(one), singleComputed: one.computed_bid, singleTotalsStamped: one.polish_estimate.totals === sb.bid,
    singleHasNoSnapshot: !has(one, "priced_tabs") && !has(one, "proposal_lump_sum"),
    frozenThrew: frozenThrew,
    keys: Object.keys(d),
    pricedTabs: d.priced_tabs.map((x) => [x.id, x.role, x.kind, x.v2, x.total]),
    allMarkedV2: d.priced_tabs.every((x) => x.v2 === true),
    tabKeys: Object.keys(d.priced_tabs[1]).sort(),
    lump: d.proposal_lump_sum, sumOfBaseParts: sumOfParts, pooledWouldBe: pooled,
    sealIsNotInTheLump: d.proposal_lump_sum === sumOfParts && d.priced_tabs.some((x) => x.id === "Seal" && x.kind === "option"),
    computed: d.computed_bid, taxes: [d.proposal_sales_tax, d.proposal_remodel_tax],
    flags: [d.proposal_taxable, d.proposal_remodel_on], area: d.sheet_area, cost: d.cost_snapshot, phase: d.phase_price,
    polishSf: [d.polish_sf, d.polish_2_sf],
    totalsStampedOnEverySection: [stamped.totals.total, stamped.tabs.Epoxy.totals.total, stamped.tabs.Seal.totals.total],
    stampedAreCopies: stamped.tabs.Epoxy !== m.tabs.Epoxy && !has(m.tabs.Epoxy, "totals_x") && m.tabs.Epoxy.totals !== stamped.tabs.Epoxy.totals,
    inputsUntouched: JSON.stringify(m) === JSON.stringify(comboWithSeal()),
    unpriceable: { computed: u.computed_bid, lump: u.proposal_lump_sum, taxes: [u.proposal_sales_tax, u.proposal_remodel_tax],
      epoxyTab: u.priced_tabs.filter((x) => x.id === "Epoxy").map((x) => [x.total, x.unpriceable]),
      totalsStamped: u.polish_estimate.tabs.Epoxy.totals.priceable, cost: u.cost_snapshot },
    rootOff: { computed: ro.computed_bid && ro.computed_bid.lump_sum, hasPolishSf: has(ro, "polish_sf"), tabs: ro.priced_tabs.map((x) => x.id),
               rootTotalsStamped: has(ro.polish_estimate, "totals") && ro.polish_estimate.totals !== undefined && has(ro.polish_estimate.totals || {}, "total") },
    noBase: { computed: so.computed_bid, lump: so.proposal_lump_sum },
    taxFlags: { taxable: t.proposal_taxable, remodelOn: t.proposal_remodel_on, tab: [t.priced_tabs[1].taxable, t.priced_tabs[1].remodel_on] },
    sealDeclaredBaseIsNeverBase: sealBase.proposal_lump_sum === priceAll(cpy).bid.total + priceAll(cpy).bids.Epoxy.total,
    throws: {
      noBid: threw(() => B.composePricingSnapshot(m, { bids: p.bids })),
      noTabBid: threw(() => B.composePricingSnapshot(m, { bid: p.bid, bids: { Epoxy: p.bids.Epoxy } })),
      noCtx: threw(() => B.composePricingSnapshot(m)),
      noModel: threw(() => B.composePricingSnapshot(null, {})),
      badTabs: threw(() => { const x = clone(m); delete x.tabs.Epoxy.layout; return B.composePricingSnapshot(x, p); }),
      savePatchNoBid: threw(() => B.buildSavePatch(m, {}, { bids: p.bids })),
    },
    // buildSavePatch is the composer plus the condition cells, in the order the page has always saved
    savePatchKeys: Object.keys(B.buildSavePatch(single, {}, { bid: sb.bid })),
    savePatchMultiKeys: Object.keys(B.buildSavePatch(m, {}, p)),
    savePatchEqualsComposer: JSON.stringify(Object.assign({}, B.buildSavePatch(m, {}, p), { cell_values: null })) ===
      JSON.stringify(Object.assign({ polish_estimate: d.polish_estimate, cell_values: null }, (() => { const r = Object.assign({}, d); delete r.polish_estimate; return r; })())),
  };
}

// ── 7. the new-bid seeding, per section ───────────────────────────────────────────────────────
const LIB_LABOR = [
  { id: "travel", name: "Travel", rate: "41.00", unit: "hours", guys_auto: true, favorite: true, default_on: false },
  { id: "lab-x", name: "Tint", rate: 0, unit: "days", guys_auto: false, favorite: true, default_on: false },
  { id: "lab-ep", name: "Epoxy install", rate: 0, unit: "days", guys_auto: false, favorite: true, default_on: true, default_work_types: ["epoxy"] },
  { id: "lab-po", name: "Polish only", rate: 0, unit: "days", guys_auto: false, favorite: true, default_on: true, default_work_types: ["polish"] },
];
function seeding() {
  const seedCtx = (extra) => Object.assign({ saved: undefined, laborRows: B.withCrewFallback(clone(LIB_LABOR)), laborRate: 50,
    travelRates: { lodging: 99, per_diem: 77 }, feesDefault: 250, calcRows: null, conditionRows: [{ key: "dye", on: true }],
    cellValues: {}, split: false, asms: [], items: [], reserved: [], sf: {} }, extra || {});
  // a NEW bid: one section, nothing saved
  const fresh = B.migrateModel(undefined);
  const root = B.seedNewSections(fresh, seedCtx({ sf: { Polish: [8000, ""] } }));
  // a SAVED bid: the gates are shut, so nothing lands on it
  const saved = polishBid();
  const savedBlob = clone(saved);
  // everything the library could answer is handed in, the calculator and the conditions too: the gates alone
  // must keep a saved bid as it was
  const calc = [{ line_id: "polishing", mode: "fixed", crew: null, sf_per_day: null, hours_per_day: null, guys: 9, days: 9, rate: 99 }];
  const after = B.seedNewSections(saved, seedCtx({ saved: savedBlob, calcRows: calc, conditionRows: [{ key: "dye", on: true }, { key: "joint_filler", on: true }] }));
  // a new bid with a new Epoxy section, a new Gyp section and an old Seal section
  let multi = B.migrateModel(undefined);
  multi = B.activateSection(multi, "Epoxy", "base", {});
  multi = B.activateSection(multi, "Seal", "option", {});
  multi.tabs.Seal.labor = [{ id: "sealing", label: "Sealing", guys: 2, days: 1, rate: 33 }];
  multi.tabs.Seal.takeoff = [{ assembly_id: "s1", assembly_name: "Seal", measurement: 5000, unit: "SF" }];
  const frozen = deepFreeze(clone(multi));
  let frozenThrew = null, seeded = null;
  try { seeded = B.seedNewSections(frozen, seedCtx({ sf: { Polish: [8000, ""], Epoxy: [4000, ""] } })); } catch (e) { frozenThrew = String(e); }
  seeded = seeded || B.seedNewSections(multi, seedCtx({ sf: { Polish: [8000, ""], Epoxy: [4000, ""] } }));
  const ids = (rows) => rows.map((r) => r.id);
  // an Epoxy-only job: the root is off, so the carrier is Epoxy and the root is left alone
  let epoxyOnly = B.migrateModel(undefined);
  epoxyOnly.kind = "off";
  epoxyOnly = B.activateSection(epoxyOnly, "Epoxy", "base", {});
  const eo = B.seedNewSections(epoxyOnly, seedCtx({ sf: { Epoxy: [4000, ""] } }));
  const noLayout = B.activateSection(B.migrateModel(undefined), "Epoxy", "base", {});
  delete noLayout.tabs.Epoxy.layout;
  const badLayout = B.activateSection(B.migrateModel(undefined), "Epoxy", "base", {});
  badLayout.tabs.Epoxy.layout = "polishing";
  // the library says "no Travel Labor" (a travel row that is not a favourite), or "only for Polish"
  const noTravel = (extra) => B.withCrewFallback([Object.assign({ id: "travel", name: "Travel", rate: 0, unit: "hours" }, extra)]);
  const declined = B.seedNewSections(B.migrateModel(undefined), seedCtx({ laborRows: noTravel({ favorite: false }) }));
  const epoxyJob = () => B.activateSection(Object.assign(B.migrateModel(undefined), { kind: "off" }), "Epoxy", "base", {});
  const declinedEpoxy = B.seedNewSections(epoxyJob(), seedCtx({ laborRows: noTravel({ favorite: true, default_work_types: ["polish"] }) })).no_travel_labor === true;
  const keptEpoxy = B.seedNewSections(epoxyJob(), seedCtx({ laborRows: noTravel({ favorite: true, default_work_types: ["epoxy"] }) })).no_travel_labor === true;
  return {
    rootLaborIds: ids(root.labor), rootRates: root.labor.map((r) => r.rate), rootTakeoff: root.takeoff.map((r) => r.measurement),
    rootFees: [root.fees, root.fees_default], rootTravelRates: [root.travel.lodging.rate, root.travel.per_diem.rate], rootDye: root.conditions.dye,
    rootShown: root.conditions_shown,
    savedUntouched: JSON.stringify(after) === JSON.stringify(savedBlob),
    inputsUntouched: JSON.stringify(saved) === JSON.stringify(savedBlob),
    frozenThrew: frozenThrew,
    multi: {
      rootLabor: ids(seeded.labor), epoxyLabor: ids(seeded.tabs.Epoxy.labor), sealLabor: ids(seeded.tabs.Seal.labor),
      epoxyTakeoff: seeded.tabs.Epoxy.takeoff.map((r) => r.measurement), sealTakeoff: seeded.tabs.Seal.takeoff.map((r) => r.measurement),
      epoxyRates: seeded.tabs.Epoxy.labor.map((r) => r.rate), rootTakeoff: seeded.takeoff.map((r) => r.measurement),
      epoxyHasTravel: ids(seeded.tabs.Epoxy.labor).indexOf("travel") >= 0, rootHasTravel: ids(seeded.labor).indexOf("travel") >= 0,
      epoxyFees: seeded.tabs.Epoxy.fees, rootFees: seeded.fees,
      sealLaborKept: seeded.tabs.Seal.labor.length === 1 && seeded.tabs.Seal.labor[0].id === "sealing",
      epoxyKeepsItsSnapshot: !!seeded.tabs.Epoxy.rates, travelLine: seeded.travel.lodging.qty,
    },
    epoxyOnly: { carrier: B.travelCarrier(epoxyOnly), epoxyLabor: ids(eo.tabs.Epoxy.labor), rootLabor: ids(eo.labor), epoxyFees: eo.tabs.Epoxy.fees,
                 rootFees: eo.fees, feesDefault: eo.fees_default, epoxyTakeoff: eo.tabs.Epoxy.takeoff.map((r) => r.measurement) },
    throws: {
      noModel: threw(() => B.seedNewSections(null, seedCtx())),
      noCtx: threw(() => B.seedNewSections(fresh)),
      noLayout: threw(() => B.seedNewSections(noLayout, seedCtx())),
      unknownLayout: threw(() => B.seedNewSections(badLayout, seedCtx())),
    },
    noTravelLabor: { root: declined.no_travel_labor === true, carrierEpoxy: declinedEpoxy, carrierEpoxyKept: keptEpoxy },
  };
}

// ── 8. the strip that switches section ────────────────────────────────────────────────────────
function switcher() {
  const m = comboWithSeal();
  const p = priceAll(m);
  const bids = Object.assign({}, p.bids, { Polish: p.bid });
  const html = B.sectionSwitcherHtml(m, "Epoxy", bids);
  const gyp = 'Gyp (USG 1-8")';
  const g = B.activateSection(polishBid(), gyp, "base", {});
  return {
    single: B.sectionSwitcherHtml(polishBid(), "Polish", {}),
    buttons: (html.match(/<button /g) || []).length,
    tabs: (html.match(/data-section-tab="[^"]*"/g) || []),
    current: (html.match(/aria-current="true"/g) || []).length,
    activeIsEpoxy: /data-section-tab="Epoxy" aria-current="true"/.test(html),
    prices: html.indexOf("$") >= 0,
    optionLabelled: html.indexOf("(option)") >= 0,
    escapes: B.sectionSwitcherHtml(g, gyp, {}).indexOf('data-section-tab="Gyp (USG 1-8&quot;)"') >= 0,
    noPriceSaysSo: B.sectionSwitcherHtml(g, gyp, {}).indexOf("no price") >= 0,
    noEmDash: B.sectionSwitcherHtml(g, gyp, {}).indexOf("—") < 0 && html.indexOf("—") < 0,
  };
}

// ── 9. the real estimate page ─────────────────────────────────────────────────────────────────
function loadPrelude(file, exportNames) {
  const base = path.join(__dirname, file);
  const code = L.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in multi-section-harness.js");
  const m = new Module(base, module);
  m.filename = base;
  m.paths = Module._nodeModulePaths(path.dirname(base));
  m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
  return m.exports;
}
let ESTIMATE = null;
const est = () => ESTIMATE || (ESTIMATE = loadPrelude("polish-estimate-harness.js",
  ["build", "blob", "typeInto", "clickEl", "need", "MODEL", "ITEMS", "ASMS"]));

async function page() {
  const P = est();
  const last = (l) => l[l.length - 1];
  const seg = (b) => ({ hidden: !!b.doc.getElementById("sections").hidden, html: b.doc.getElementById("sections").innerHTML,
                        htmlWrites: b.doc.getElementById("sections").htmlWrites });
  // one section (every bid today): the strip is never drawn and a save writes the five keys
  const one = P.build({ blob: P.blob({ polish_estimate: clone(P.MODEL), polish_sf: 17500 }) });
  await one.api.init();
  P.typeInto(one, '[data-tk="0"][data-k="measurement"]', "12000");
  one.clock.fire();
  const oneSave = last(one.rec.saves);
  const oneStrip = seg(one);

  // several sections
  const model = Object.assign(clone(P.MODEL), { tabs: {
    Epoxy: { layout: "epoxy", kind: "base", profile: "epoxy@1",
      takeoff: [{ assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: 4000, unit: "SF" }],
      labor: [{ id: "installing", label: "Installing", guys: 3, days: 4, rate: 33 }],
      contingency: 0, fees: 0, totals: {},
      rates: { version: 1, profile: "epoxy@1", rates: {}, fees_default: null, notes: ["Soft costs: the rule filed on the Markups page is blank, so the built-in rate is charged."] } },
    Seal: { layout: "seal", kind: "option", profile: "seal@1", takeoff: [], labor: [], contingency: 0, fees: 0, totals: {} },
  } });
  const b = P.build({ blob: P.blob({ polish_estimate: clone(model), polish_sf: 17500 }) });
  await b.api.init();
  const strip = seg(b);
  const rootOnly = b.api.bid().total;
  P.clickEl(b, P.need(b, '[data-section-tab="Epoxy"]'));
  const panelEpoxy = b.doc.getElementById("panels").innerHTML;
  const stripAfter = seg(b);
  P.clickEl(b, P.need(b, '[data-section-tab="Polish"]'));
  const panelRoot = b.doc.getElementById("panels").innerHTML;
  P.typeInto(b, '[data-tk="0"][data-k="measurement"]', "12000");
  const before = b.rec.saves.length;
  b.clock.fire();
  const saved = last(b.rec.saves.slice(before));
  const total = b.doc.getElementById("bid-total").textContent;
  const maths = b.doc.getElementById("maths").textContent;
  b.win.fire("pagehide");
  const flushed = last(b.rec.saves);

  // a bid whose sections cannot be read still saves what was typed, and keeps the sections as they were
  const broken = clone(model); delete broken.tabs.Epoxy.layout;
  const c = P.build({ blob: P.blob({ polish_estimate: clone(broken), polish_sf: 17500 }) });
  await c.api.init();
  P.typeInto(c, '[data-tk="0"][data-k="measurement"]', "12000");
  c.clock.fire();
  const brokenSave = last(c.rec.saves);

  // a new bid seeds through the model and opens with the same strip rules
  return {
    one: { strip: oneStrip, keys: Object.keys(oneSave).sort(), hasSnapshot: has(oneSave, "priced_tabs"), alert: one.doc.getElementById("alert").textContent },
    multi: { strip: strip, total: total, maths: maths, rootOnlyTotal: rootOnly, panelEpoxy: panelEpoxy,
             stripAfterClick: stripAfter.html, panelRootIsTakeoff: panelRoot.indexOf("Polish 800 Grit") >= 0,
             savedKeys: Object.keys(saved).sort(), pricedTabs: saved.priced_tabs.map((t) => [t.id, t.v2, t.kind]),
             savedLump: saved.computed_bid.lump_sum, proposalLump: saved.proposal_lump_sum,
             flushEqualsAutosave: JSON.stringify(saved) === JSON.stringify(flushed),
             tabsKept: Object.keys(saved.polish_estimate.tabs), rootTotalsStamped: saved.polish_estimate.totals.total,
             epoxyTotalsStamped: saved.polish_estimate.tabs.Epoxy.totals.total,
             barMatchesSave: total.replace(/[^0-9]/g, "") === String(saved.computed_bid.lump_sum) },
    broken: { alert: c.doc.getElementById("alert").textContent, keys: Object.keys(brokenSave).sort(),
              tabsKept: JSON.stringify(brokenSave.polish_estimate.tabs) === JSON.stringify(broken.tabs),
              hasSnapshot: has(brokenSave, "priced_tabs"), measurement: brokenSave.polish_estimate.takeoff[0].measurement },
  };
}

(async function () {
  const attempt = async (fn) => {
    try { return await fn(); } catch (e) { return { error: String((e && e.stack) || e) }; }
  };
  const sections = [["sections", sectionsSection], ["newSection", newSection], ["activation", activation],
    ["noReprice", noReprice], ["pricing", pricing], ["composer", composer], ["seeding", seeding],
    ["switcher", switcher], ["page", page]];
  const done = [];
  for (const [name, fn] of sections) done.push([name, await attempt(fn)]);
  console.log(JSON.stringify(Object.fromEntries(done)));
})().catch((err) => { console.error((err && err.stack) || err); process.exit(1); });
