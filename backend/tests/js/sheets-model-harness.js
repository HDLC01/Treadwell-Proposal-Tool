"use strict";
/* THE SHEETS OF A BID, in the model: copy a sheet, add one, rename it, delete it, pick the base bid, and have the rest of the
 * bid follow the base.
 *
 * Sheets phase 1 of the v2 estimating program (docs/v2-architecture.md, 7.13). Everything here EXECUTES the real
 * js/bid-model.js and js/bid-engine.js, and the last section runs the real estimate page (polish-estimate.js, whole,
 * through polish-estimate-harness.js's own boot code). Nothing is a source assertion. One line of JSON comes out and
 * test_v2_sheets_model.py asserts on it, then breaks a scratch copy of the code in many ways and requires the facts to
 * change.
 *
 * Every section catches its own failure and reports it as `{error}`, so the same harness can run over a tree that does
 * not have the functions and fail as an assertion, not a crash.
 *
 * Usage: node sheets-model-harness.js <frontend-dir>   ->  one line of JSON
 */
const path = require("path");
const Module = require("module");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const B = require(path.join(ROOT, "js", "bid-model.js"));
const E = require(path.join(ROOT, "js", "bid-engine.js"));
const T = require(path.join(ROOT, "js", "work-types.js"));

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
const REV2 = "polish-rev2@1";
const LEGACY = "polish-legacy@1";
const sameKeys = (a, b) => Object.keys(a).length === Object.keys(b).length && Object.keys(a).every((k) => a[k] === b[k]);

// ── fixtures ──────────────────────────────────────────────────────────────────────────────────
const AREA = [{ assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: 10000, unit: "SF" }];
/** A saved Polish bid the way the page writes it, with a Travel Labor row so the job's drive has somewhere to live. */
function polish() {
  const m = B.freshModel();
  m.takeoff = clone(AREA);
  m.labor = [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33 },
             { id: "travel", label: "Travel Labor", unit: "hours", guys: 2, days: 4, rate: 33, guys_auto: false }];
  return m;
}
/** A saved Polish bid that was stamped by Polish rev 2 and the purchase pool when it was made. */
function rev2() { const m = polish(); m.profile = REV2; m.pool_packs = true; return m; }
/** The job is 70 miles out: lodging is on, ten nights at $100, typed. */
function far(m) {
  m.conditions.local = false;
  const l = m.travel.lodging;
  l.enabled = true; l.qty_auto = false; l.qty = 10; l.rate = 100;
  return m;
}
const EPOXY_ROWS = [{ assembly_id: "e1", assembly_name: "Flake", measurement: 4000, unit: "SF" },
                    { assembly_id: "e2", assembly_name: "Cove", measurement: 300, unit: "LF" }];
const EPOXY_LABOR = [{ id: "installing", label: "Installing", guys: 3, days: 4, rate: 33 }];
/** A model with an Epoxy section of the given kind. */
function withEpoxy(m, kind, rules) {
  const o = B.activateSection(m, "Epoxy", kind || "option", { rules: rules || [] });
  o.tabs.Epoxy.takeoff = clone(EPOXY_ROWS);
  o.tabs.Epoxy.labor = clone(EPOXY_LABOR);
  return o;
}
const MATS = { polish: 10000, epoxy: 8000, seal: 1500 };
const GYP = { gyp: 6000, extras: 200, sand: 100, soundMat: 300, soundMatRolls: 40 };
/** What the page prices a takeoff at, by the section's ROLE: the model never knows the library. */
const material = (e) => (e.role === "gyp" ? GYP : MATS[e.role]);
const CTX = { material: material, remodel_rate: null };
const bidOf = (m, tab) => (tab === "Polish" || B.sectionOf(m, tab).layout === "polish") ? B.polishBid(m, tab, CTX) : B.priceSection(m, tab, CTX);
function priceAll(m) {
  return { bid: B.polishBid(m, "Polish", CTX), bids: B.priceTabs(m, CTX) };
}
const snapshot = (m, tabOpts) => {
  const p = priceAll(m);
  return B.composePricingSnapshot(m, Object.assign({}, p, tabOpts ? { tabOpts: tabOpts } : {}));
};
const entryRows = (m) => B.sectionsOf(m).map((e) => [e.tab, e.sheet, e.label, e.kind, e.role, e.source]);
const idsOf = (m) => B.sectionsOf(m).map((e) => e.tab);

// ── 1. identity ───────────────────────────────────────────────────────────────────────────────
function identity() {
  const kindOf = (k) => { const x = polish(); if (k !== undefined) x.kind = k; return B.sectionsOf(x)[0].kind; };
  const e0 = B.sectionsOf(polish())[0];
  const oldShape = withEpoxy(B.activateSection(polish(), "Seal (+Jnts)", "option", {}), "base");
  const copied = B.copySection(withEpoxy(polish(), "base"), "Epoxy").model;
  const bad = (mut) => { const m = clone(copied); mut(m.tabs.Copy1); return threw(() => B.sectionsOf(m)); };
  const badKey = (id) => { const m = polish(); m.tabs = { [id]: clone(copied.tabs.Copy1) }; return threw(() => B.sectionsOf(m)); };
  return {
    rootKinds: { missing: kindOf(), base: kindOf("base"), option: kindOf("option"), off: kindOf("off"), junk: kindOf("primary") },
    root: { tab: e0.tab, sheet: e0.sheet, label: e0.label, source: e0.source, root: e0.root, isModel: e0.section === undefined ? null : true },
    oldShapes: entryRows(oldShape),
    copyEntries: entryRows(copied),
    copyEntry: (() => { const e = B.sectionsOf(copied)[2]; return { tab: e.tab, sheet: e.sheet, label: e.label, source: e.source,
      layout: e.layout, kind: e.kind, role: e.role, profile: e.profile }; })(),
    copyIsByReference: (() => { const m = clone(copied); const e = B.sectionsOf(m)[2]; e.section.contingency = 41; return m.tabs.Copy1.contingency; })(),
    throws: {
      copyWithoutSheet: bad((s) => { delete s.sheet; }),
      copyOfUnknownSheet: bad((s) => { s.sheet = "Takeoff"; }),
      copyWithWrongLayout: bad((s) => { s.layout = "polish"; }),
      sheetKeyWithOtherSheet: (() => { const m = clone(oldShape); m.tabs.Epoxy.sheet = "Gyp (FR)"; return threw(() => B.sectionsOf(m)); })(),
      copyZero: badKey("Copy0"), copyLowerCase: badKey("copy1"), copyWords: badKey("Copy1 extra"),
      polishUnderTabs: (() => { const m = polish(); m.tabs = { Polish: clone(copied.tabs.Copy1) }; return threw(() => B.sectionsOf(m)); })(),
    },
    labelNeedsText: (() => { const m = clone(copied); m.tabs.Copy1.label = 7; return B.sectionsOf(m)[2].label; })(),
    blankLabel: (() => { const m = clone(copied); m.tabs.Copy1.label = "  "; return B.sectionsOf(m)[2].label; })(),
  };
}

// ── 2. a copy prices exactly like the sheet it came from ──────────────────────────────────────
function copies() {
  const out = {};
  Object.assign(out, Object.fromEntries([["legacy", polish()], ["rev2", rev2()]].map(([name, m]) => {
    const c = B.copySection(m, "Polish", {});
    const src = B.polishBid(m, "Polish", CTX);
    const cp = B.polishBid(c.model, c.id, CTX);
    const viaSection = B.priceSection(c.model, c.id, CTX);
    // far job: the copy is an OPTION, so it carries its own travel. Made the base it carries the job's, like its source.
    const farM = far(clone(m));
    const farSrc = B.polishBid(farM, "Polish", CTX);
    const farCopy = B.copySection(farM, "Polish", {});
    const asBase = B.pickBase(farCopy.model, [farCopy.id], {});
    return [name, {
      id: c.id, sameKeys: sameKeys(src, cp), total: [src.total, cp.total], viaPriceSection: sameKeys(cp, viaSection),
      hasTooling: [has(src, "tooling"), has(cp, "tooling")], tooling: [src.tooling, cp.tooling],
      profile: c.model.tabs[c.id].profile, poolPacks: c.model.tabs[c.id].pool_packs, hasPoolKey: has(c.model.tabs[c.id], "pool_packs"),
      farAsOption: B.polishBid(farCopy.model, farCopy.id, CTX).travel, farSource: farSrc.travel,
      farAsBase: sameKeys(B.polishBid(asBase.model, farCopy.id, CTX), farSrc),
      keys: Object.keys(c.model.tabs[c.id]), kind: c.model.tabs[c.id].kind, source: c.model.tabs[c.id].source,
      totalsStart: c.model.tabs[c.id].totals,
      rootUntouched: JSON.stringify(Object.assign({}, c.model, { tabs: undefined })) === JSON.stringify(Object.assign({}, m, { tabs: undefined })),
      inputUntouched: JSON.stringify(m) === JSON.stringify(name === "legacy" ? polish() : rev2()),
    }];
  })));
  // the copy is taken from a model that has not been touched; a frozen one is fine
  const frozen = deepFreeze(clone(polish()));
  out.frozenThrew = threw(() => B.copySection(frozen, "Polish", {}));
  // a Polish bid saved before the pool and before rev 2: the copy has neither stamp, and says legacy
  const oldRoot = polish();
  const oldCopy = B.copySection(oldRoot, "Polish", {}).model.tabs.Copy1;
  out.savedBeforeStamps = { hasPool: has(oldCopy, "pool_packs"), profile: oldCopy.profile, rootHasProfile: has(oldRoot, "profile") };
  // an Epoxy section: a copy keeps the profile, the pool stamp, the rates it kept and every row, and prices alike (local job)
  const filed = [{ layout: "epoxy", line_key: "soft_costs", formula: "10%", applies: true }];
  const ep = withEpoxy(polish(), "base", filed);
  const epCopy = B.copySection(ep, "Epoxy", {});
  const a = B.priceSection(ep, "Epoxy", CTX), b = B.priceSection(epCopy.model, epCopy.id, CTX);
  out.epoxy = {
    id: epCopy.id, sameKeys: sameKeys(a, b), total: [a.total, b.total], profile: [ep.tabs.Epoxy.profile, epCopy.model.tabs[epCopy.id].profile],
    pool: [ep.tabs.Epoxy.pool_packs, epCopy.model.tabs[epCopy.id].pool_packs],
    rates: JSON.stringify(ep.tabs.Epoxy.rates) === JSON.stringify(epCopy.model.tabs[epCopy.id].rates) && !!ep.tabs.Epoxy.rates.rates.soft_costs,
    ratesAreOwn: epCopy.model.tabs[epCopy.id].rates !== epCopy.model.tabs.Epoxy.rates,
    rows: JSON.stringify(epCopy.model.tabs[epCopy.id].takeoff) === JSON.stringify(ep.tabs.Epoxy.takeoff),
    sheet: epCopy.model.tabs[epCopy.id].sheet, role: B.sectionOf(epCopy.model, epCopy.id).role, label: B.sectionOf(epCopy.model, epCopy.id).label,
    kind: epCopy.model.tabs[epCopy.id].kind,
    // a stamp the source never had stays off the copy
    noPoolOnSource: (() => { const m = clone(ep); delete m.tabs.Epoxy.pool_packs; return has(B.copySection(m, "Epoxy", {}).model.tabs.Copy1, "pool_packs"); })(),
    farAsOption: (() => { const f = far(clone(ep)); return [B.priceSection(f, "Epoxy", CTX).travel, B.priceSection(B.copySection(f, "Epoxy", {}).model, "Copy1", CTX).travel]; })(),
    ownTravel: B.optionTravelCosts(far(clone(ep)).travel, EPOXY_LABOR).total,
    // the copy of the copy and a copy of a section that is off
    chain: (() => { const c2 = B.copySection(epCopy.model, epCopy.id, {}); return [c2.id, B.sectionOf(c2.model, c2.id).label, c2.model.tabs[c2.id].source]; })(),
    offSource: (() => { const m = clone(ep); m.tabs.Epoxy.kind = "off"; const r = B.copySection(m, "Epoxy", {}); return r.model.tabs[r.id].kind; })(),
  };
  // the proposal's settings: a copy starts OFF the proposal, which the patch says and the next save keeps
  const c = B.copySection(polish(), "Polish", { state: { tab_opts: { Other: { is_option: true } } } });
  const snap = snapshot(c.model, c.patch.tab_opts);
  const bare = snapshot(c.model);
  out.proposal = {
    patchTabOpts: c.patch.tab_opts, kept: has(c.patch.tab_opts, "Other"),
    snapshotEntry: snap.tab_opts.Copy1, snapshotKeepsOther: snap.tab_opts.Other,
    noPatchDefault: bare.tab_opts.Copy1,
    inLump: snap.proposal_lump_sum === B.polishBid(c.model, "Polish", CTX).total,
    pricedAs: snap.priced_tabs.map((t) => [t.id, t.name, t.kind, t.role]),
  };
  out.limit = (() => {
    let m = polish();
    const ids = [];
    for (let i = 0; i < B.MAX_COPIES; i++) { const r = B.copySection(m, "Polish", {}); m = r.model; ids.push(r.id); }
    const over = threw(() => B.copySection(m, "Polish", {}));
    const addOver = threw(() => B.addSheet(m, "Polish", {}));
    const addOwnKey = (() => { try { return B.addSheet(m, "Seal", {}).id; } catch (e) { return String(e.message); } })();
    const freed = B.deleteSection(m, "Copy5", {}).model;
    return { max: B.MAX_COPIES, first: ids[0], last: ids[ids.length - 1], over: over, addOver: addOver, addOwnKey: addOwnKey,
             reused: B.copySection(freed, "Polish", {}).id };
  })();
  return out;
}

// ── 3. a Polish section under tabs prices exactly like the root ───────────────────────────────
function polishCopies() {
  const out = {};
  Object.assign(out, Object.fromEntries([["legacy", polish()], ["rev2", rev2()]].map(([name, base]) => {
    // dye on, a typed remodel rate, contingency and fees, and a hand-built chain with the very inputs the page has always used
    const m = clone(base);
    m.conditions.dye = true; m.conditions.remodel_tax = true; m.contingency = 250; m.fees = 90;
    const c = B.copySection(m, "Polish", {});
    const ctx = { material: () => 12345.67, remodel_rate: 0.07975 };
    const root = B.polishBid(c.model, "Polish", ctx);
    const copy = B.polishBid(c.model, c.id, ctx);
    const byHand = B.markupChain({
      material: 12345.67, labor: B.laborTotal(m.labor, m.conditions),
      travel: B.travelCosts(m.travel, m.labor, B.travelOpts(m, B.ROOT_TAB)).total,
      tooling: B.rootTooling(m), contingency: 250, fees: 90, conditions: m.conditions, sf: B.takeoffSf(m.takeoff), remodel_rate: 0.07975
    }, B.rootProfile(m).stamp);
    return [name, { rootIsTheOldBid: sameKeys(root, byHand), copyIsTheRoot: sameKeys(copy, root), total: copy.total, tooling: copy.tooling === undefined ? null : copy.tooling,
                    keys: Object.keys(copy).length }];
  })));
  // a Polish sheet added to the bid is a rev2 section under tabs, and prices as a rev2 root does
  const added = B.addSheet(polish(), "Polish", {});
  const sec = added.model.tabs[added.id];
  sec.takeoff = clone(AREA); sec.labor = [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33 }];
  const rev2Root = rev2();
  rev2Root.labor = [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33 }];
  out.added = { profile: sec.profile, pool: sec.pool_packs, hasRates: has(sec, "rates"),
                sameAsRev2Root: sameKeys(B.polishBid(added.model, added.id, CTX), B.polishBid(rev2Root, "Polish", CTX)) };
  out.errors = {
    noMaterial: threw(() => B.polishBid(polish(), "Polish", {})),
    noCtx: threw(() => B.polishBid(polish())),
    noModel: threw(() => B.polishBid(null, "Polish", CTX)),
    epoxy: threw(() => B.polishBid(withEpoxy(polish()), "Epoxy", CTX)),
    unknownTab: threw(() => B.polishBid(polish(), "Copy9", CTX)),
    unknownStamp: (() => { const c = B.copySection(polish(), "Polish", {}); c.model.tabs.Copy1.profile = "polish@1";
      const r = B.polishBid(c.model, "Copy1", CTX); return { priceable: r.priceable, total: r.total, line: r.line }; })(),
    movedRev: (() => { const c = B.copySection(polish(), "Polish", {}); c.model.tabs.Copy1.profile = "polish-legacy@7";
      const r = B.polishBid(c.model, "Copy1", CTX); return { priceable: r.priceable, total: r.total }; })(),
  };
  // the sheet's way of counting nights (rev 2) follows the section: a rev 2 copy that carries the job's travel counts them as the rev 2 root
  // does, from the labor dollars (a row paid more than the first crew row reads as extra days), and a legacy one counts man-days
  const nightsOf = (m) => { m.conditions.local = false; m.travel.lodging.enabled = true; m.travel.lodging.qty_auto = true; m.travel.lodging.rate = 100;
    m.labor = [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33 }, { id: "extra", label: "Extra", guys: 1, days: 5, rate: 66 }]; return m; };
  const nr = nightsOf(rev2()), nl = nightsOf(polish());
  const carrierCopy = (m) => { const c = B.copySection(m, "Polish", {}); return B.pickBase(c.model, [c.id], {}).model; };
  out.nights = { rev2Root: B.polishBid(nr, "Polish", CTX).travel, rev2CopyAsCarrier: B.polishBid(carrierCopy(nr), "Copy1", CTX).travel,
                 legacyRoot: B.polishBid(nl, "Polish", CTX).travel, legacyCopyAsCarrier: B.polishBid(carrierCopy(nl), "Copy1", CTX).travel,
                 optsOnCopy: [!!B.travelOpts(carrierCopy(nr), "Copy1"), !!B.travelOpts(carrierCopy(nl), "Copy1"), !!B.travelOpts(nr, "Copy9")] };
  // a bid whose sections cannot be read is still priced at its root, as the page always did
  const broken = withEpoxy(polish(), "base");
  delete broken.tabs.Epoxy.layout;
  out.unreadableTabs = { root: B.polishBid(broken, "Polish", CTX).total, plain: B.polishBid(polish(), "Polish", CTX).total,
                         epoxyThrows: threw(() => B.polishBid(broken, "Epoxy", CTX)) };
  // a root that is off still answers with the job's travel, as bid() always did
  const epoxyJob = far(withEpoxy(polish(), "base"));
  epoxyJob.kind = "off";
  const plainFar = far(polish());
  out.offRoot = { travel: B.polishBid(epoxyJob, "Polish", CTX).travel, plain: B.polishBid(plainFar, "Polish", CTX).travel };
  return out;
}

// ── 4. everything follows the base ────────────────────────────────────────────────────────────
function baseBid() {
  const m0 = far(withEpoxy(polish(), "option"));
  const before = snapshot(m0);
  const state = { tab_opts: { Polish: { is_option: false, show: false, price_mode: "deduct", desc: "keep me" }, Other: { is_option: true } } };
  const pick = B.pickBase(m0, ["Epoxy"], { state: state });
  const m1 = pick.model;
  const after = snapshot(m1, Object.assign({}, state.tab_opts, pick.patch.tab_opts));
  const epoxyBefore = B.priceSection(m0, "Epoxy", CTX), epoxyAfter = B.priceSection(m1, "Epoxy", CTX);
  const polishBefore = B.polishBid(m0, "Polish", CTX), polishAfter = B.polishBid(m1, "Polish", CTX);
  const rowIds = (m, tab) => { const s = B.sectionOf(m, tab).section.labor; return s.map((r) => r.id); };
  const back = B.pickBase(m1, ["Polish"], { state: Object.assign({}, state, { tab_opts: pick.patch.tab_opts }) });
  const same = B.pickBase(m0, ["Polish"], {});
  const frozen = deepFreeze(clone(m0));
  return {
    before: { base: B.baseOf(m0), carrier: B.travelCarrier(m0), lump: before.proposal_lump_sum, baseTabId: before.base_tab_id,
              polishTravel: polishBefore.travel, epoxyAsOptionTravel: epoxyBefore.travel, polishTotal: polishBefore.total },
    after: { base: B.baseOf(m1), carrier: B.travelCarrier(m1), lump: after.proposal_lump_sum, baseTabId: after.base_tab_id,
             epoxyTravel: epoxyAfter.travel, epoxyTotal: epoxyAfter.total, polishAsOptionTravel: polishAfter.travel, polishTotal: polishAfter.total,
             kinds: B.sectionsOf(m1).map((e) => [e.tab, e.kind]), rootKindKey: m1.kind },
    ownTravel: { polishOption: B.optionTravelCosts(m1.travel, m1.labor).total, hand: Math.ceil(B.travelManDays(m1.labor) * 100) },
    jobTravel: Math.ceil(10 * 100),
    patch: pick.patch,
    keptDesc: pick.patch.tab_opts.Polish.desc, otherKept: has(pick.patch.tab_opts, "Other"),
    travelLaborRow: { polishBefore: rowIds(m0, "Polish"), epoxyBefore: rowIds(m0, "Epoxy"), polishAfter: rowIds(m1, "Polish"), epoxyAfter: rowIds(m1, "Epoxy") },
    backAgain: { base: B.baseOf(back.model), polishTotal: B.polishBid(back.model, "Polish", CTX).total, polishTravel: B.polishBid(back.model, "Polish", CTX).travel,
                 rowsBack: rowIds(back.model, "Polish"), epoxyRows: rowIds(back.model, "Epoxy"), patch: back.patch,
                 sameAsStart: JSON.stringify(back.model) === JSON.stringify(m0),
                 // THE DEMOTED BASE KEEPS ITS DRIVE (the fifth audit), so a pick and its undo no longer return the Epoxy option byte for byte: it keeps the Travel Labor row it took
                 // as the base. Everything else is as it was: the Polish side whole (the root's own keys), and Epoxy but for that one row.
                 polishSideSameAsStart: JSON.stringify(Object.assign({}, back.model, { tabs: null })) === JSON.stringify(Object.assign({}, m0, { tabs: null })),
                 epoxyOnlyGainedTravel: JSON.stringify(Object.assign({}, back.model.tabs.Epoxy, { labor: back.model.tabs.Epoxy.labor.filter((r) => r.id !== "travel") })) ===
                   JSON.stringify(m0.tabs.Epoxy) },
    samePick: { sameModel: same.model === m0, patch: same.patch },
    inputUntouched: JSON.stringify(m0) === JSON.stringify(far(withEpoxy(polish(), "option"))),
    frozenThrew: threw(() => B.pickBase(frozen, ["Epoxy"], {})),
    snapshotMoves: { epoxyIsTheLump: after.proposal_lump_sum === epoxyAfter.total, polishNoLongerInLump: after.proposal_lump_sum !== polishBefore.total },
    pricedTabs: after.priced_tabs.map((t) => [t.id, t.kind]),
  };
}

function combinedBase() {
  const m0 = far(withEpoxy(polish(), "option"));
  const pick = B.pickBase(m0, ["Polish", "Epoxy"], {});
  const m = pick.model;
  const p = priceAll(m);
  const snap = B.composePricingSnapshot(m, p);
  const epoxyAsOption = B.priceSection(m0, "Epoxy", CTX);
  const solo = B.pickBase(m, ["Epoxy"], {});
  // the Polish root a combined base leaves as the carrier, and the pair picked in the other order
  const swapped = B.pickBase(m0, ["Epoxy", "Polish"], {});
  return {
    base: B.baseOf(m), patch: pick.patch, lump: snap.proposal_lump_sum,
    sumOfBoth: p.bid.total + p.bids.Epoxy.total, handSum: B.polishBid(m, "Polish", CTX).total + B.priceSection(m, "Epoxy", CTX).total,
    epoxyTravelAsBase: p.bids.Epoxy.travel, epoxyTravelAsOption: epoxyAsOption.travel, polishTravel: p.bid.travel,
    baseTabId: snap.base_tab_id, kinds: B.sectionsOf(m).map((e) => [e.tab, e.kind]),
    areas: snap.sheet_area, pricedTabs: snap.priced_tabs.map((t) => [t.id, t.kind]),
    carrier: B.travelCarrier(m),
    fromCombinedToEpoxy: { base: B.baseOf(solo.model), kinds: B.sectionsOf(solo.model).map((e) => [e.tab, e.kind]), patch: solo.patch,
                           rows: [B.sectionOf(solo.model, "Polish").section.labor.map((r) => r.id), B.sectionOf(solo.model, "Epoxy").section.labor.map((r) => r.id)] },
    otherOrder: { sameModel: JSON.stringify(swapped.model) === JSON.stringify(pick.model), patch: swapped.patch },
    // a Copy of Polish and the root cannot both be the Polish half
    twoPolish: threw(() => B.pickBase(B.copySection(m0, "Polish", {}).model, ["Polish", "Copy1"], {})),
  };
}

function refusals() {
  const m = withEpoxy(B.activateSection(polish(), "Seal", "option", {}), "option");
  const g = B.activateSection(polish(), 'Gyp (USG 1-8")', "option", {});
  const level = polish(); level.tabs = { Leveling: { layout: "leveling", kind: "option", profile: "leveling@1", takeoff: [], labor: [], contingency: 0, fees: 0, totals: {} } };
  return {
    sealBase: threw(() => B.pickBase(m, ["Seal"], {})),
    sealInPair: threw(() => B.pickBase(m, ["Polish", "Seal"], {})),
    levelingBase: threw(() => B.pickBase(level, ["Leveling"], {})),
    twoPolish: threw(() => B.pickBase(B.copySection(m, "Polish", {}).model, ["Polish", "Copy1"], {})),
    polishAndGyp: threw(() => B.pickBase(g, ["Polish", 'Gyp (USG 1-8")'], {})),
    unknown: threw(() => B.pickBase(m, ["Nope"], {})),
    unknownInPair: threw(() => B.pickBase(m, ["Polish", "Nope"], {})),
    three: threw(() => B.pickBase(m, ["Polish", "Epoxy", "Seal"], {})),
    none: threw(() => B.pickBase(m, [], {})),
    sameTwice: threw(() => B.pickBase(m, ["Epoxy", "Epoxy"], {})),
    noModel: threw(() => B.pickBase(null, ["Polish"], {})),
    asString: B.pickBase(m, "Epoxy", {}).patch.base_tab_id,
    gypBase: (() => { const r = B.pickBase(g, ['Gyp (USG 1-8")'], {}); return [B.baseOf(r.model), r.patch.work_type, r.patch.base_tab_id]; })(),
    // the refusal changed nothing
    stillTheSame: JSON.stringify(m) === JSON.stringify(withEpoxy(B.activateSection(polish(), "Seal", "option", {}), "option")),
    deleteBase: threw(() => B.deleteSection(withEpoxy(polish(), "base"), "Epoxy", {})),
    deleteRoot: threw(() => B.deleteSection(polish(), "Polish", {})),
    deleteRootAsOption: threw(() => B.deleteSection(B.pickBase(withEpoxy(polish(), "option"), ["Epoxy"], {}).model, "Polish", {})),
    deleteUnknown: threw(() => B.deleteSection(polish(), "Copy3", {})),
    deleteCombinedHalf: threw(() => B.deleteSection(B.pickBase(withEpoxy(polish(), "option"), ["Polish", "Epoxy"], {}).model, "Epoxy", {})),
    addLeveling: threw(() => B.addSheet(polish(), "Leveling", {})),
    addEpoxyBlank: threw(() => B.addSheet(polish(), "Epoxy blank", {})),
    addNothing: threw(() => B.addSheet(polish(), "Takeoff", {})),
    sheetsOffered: B.sheetsToAdd(),
  };
}

// ── 5. what a deleted sheet leaves behind ─────────────────────────────────────────────────────
function idReuse() {
  const m = polish();
  const draft = () => ({
    tab_opts: { Other: { is_option: true } }, tab_notes: { Other: ["keep"] },
    price_overrides: { lines: { "option:Other": "mine" }, options: { Other: { amount: 1 } } }
  });
  const c1 = B.copySection(m, "Polish", { state: draft() });
  const typed = Object.assign(draft(), c1.patch);
  typed.tab_opts.Copy1 = Object.assign({}, typed.tab_opts.Copy1, { is_option: true, desc: "My words" });
  typed.tab_notes.Copy1 = ["a note"];
  typed.price_overrides.lines["option:Copy1"] = "words over the line";
  typed.price_overrides.lines["option:Copy1:total"] = "$9";
  typed.price_overrides.options.Copy1 = { amount: 5 };
  typed.price_overrides.before = { "option:Copy1": ["above it"] };
  typed.price_overrides.line_props = { "option:Copy1": { bullet: true } };
  const del = B.deleteSection(c1.model, "Copy1", { state: typed });
  const after = Object.assign({}, typed, del.patch);
  const c2 = B.copySection(del.model, "Polish", { state: after });
  const again = Object.assign({}, after, c2.patch);
  // a delete that forgot (an old draft, a crash): the NEXT copy still starts clean
  const stale = B.copySection(del.model, "Polish", { state: typed });
  const staleAfter = Object.assign({}, typed, stale.patch);
  // and a Seal option added again after it was removed
  const seal = B.addSheet(polish(), "Seal", { state: draft() });
  const sealTyped = Object.assign(draft(), seal.patch);
  sealTyped.tab_opts.Seal = Object.assign({}, sealTyped.tab_opts.Seal, { desc: "Seal words" });
  sealTyped.price_overrides.lines["option:Seal"] = "seal line";
  const sealGone = B.deleteSection(seal.model, "Seal", { state: sealTyped });
  const sealAfter = Object.assign({}, sealTyped, sealGone.patch);
  const text = (v) => JSON.stringify(v);
  return {
    firstId: c1.id, tabsAfterDelete: Object.keys(del.model.tabs), tabsIsObject: typeof del.model.tabs === "object",
    patchKeys: Object.keys(del.patch).sort(),
    nothingLeft: text(after).indexOf("Copy1") < 0, otherKept: after.tab_opts.Other && after.tab_notes.Other[0] === "keep" && after.price_overrides.lines["option:Other"] === "mine",
    secondId: c2.id,
    freshAgain: { entry: again.tab_opts.Copy1, desc: has(again.tab_opts.Copy1, "desc"), notes: has(again.tab_notes, "Copy1"),
                  words: text(again.price_overrides).indexOf("Copy1") < 0 },
    staleScrubbed: { entry: staleAfter.tab_opts.Copy1, notes: has(staleAfter.tab_notes, "Copy1"), words: text(staleAfter.price_overrides).indexOf("Copy1") < 0,
                     otherKept: !!staleAfter.tab_opts.Other },
    sealGone: { left: text(sealAfter).indexOf("Seal") >= 0 ? text(sealAfter).slice(text(sealAfter).indexOf("Seal") - 20, text(sealAfter).indexOf("Seal") + 20) : null,
                tabs: Object.keys(sealGone.model.tabs) },
    sealAgain: B.addSheet(sealGone.model, "Seal", { state: sealAfter }).patch.tab_opts.Seal,
    // the first delete of several copies frees the smallest id
    order: (() => { let x = polish(); const ids = [];
      for (let i = 0; i < 3; i++) { const r = B.copySection(x, "Polish", {}); x = r.model; ids.push(r.id); }
      const d = B.deleteSection(x, "Copy2", {}).model; const n = B.copySection(d, "Polish", {});
      return { ids: ids, next: n.id, tabs: Object.keys(n.model.tabs) }; })(),
    inputUntouched: text(c1.model) === text(B.copySection(m, "Polish", { state: draft() }).model),
  };
}

// ── 6. the base bid, and the job type it amounts to ───────────────────────────────────────────
function baseOfCases() {
  const rootOnly = polish();
  const epoxyJob = withEpoxy(polish(), "base"); epoxyJob.kind = "off";
  const combo = withEpoxy(polish(), "base");
  const gypJob = B.activateSection(polish(), 'Gyp (USG 1-8")', "base", {}); gypJob.kind = "off";
  const polishAndGyp = B.activateSection(polish(), 'Gyp (USG 1-8")', "base", {});
  const noBase = withEpoxy(polish(), "option"); noBase.kind = "off";
  const sealDeclared = B.activateSection(polish(), "Seal", "option", {}); sealDeclared.tabs.Seal.kind = "base";
  const copyBase = B.pickBase(B.copySection(polish(), "Polish", {}).model, ["Copy1"], {}).model;
  const rootOption = B.pickBase(withEpoxy(polish(), "option"), ["Epoxy"], {}).model;
  const twoEpoxy = withEpoxy(polish(), "base"); twoEpoxy.kind = "off";
  const second = B.copySection(twoEpoxy, "Epoxy", {}).model; second.tabs.Copy1.kind = "base";
  const out = Object.fromEntries(Object.entries({ rootOnly, epoxyJob, combo, gypJob, polishAndGyp, noBase, sealDeclared, copyBase, rootOption, twoEpoxy: second })
    .map(([k, m]) => [k, B.baseOf(m)]));
  out.unreadable = threw(() => { const m = clone(combo); delete m.tabs.Epoxy.layout; return B.baseOf(m); });
  out.noModel = threw(() => B.baseOf(null));
  return out;
}

// ── 7. rename ─────────────────────────────────────────────────────────────────────────────────
function renaming() {
  const c = B.copySection(withEpoxy(polish(), "base"), "Epoxy", {});
  const m = c.model;                          // Polish, Epoxy, "Epoxy copy" (Copy1)
  const why = (label, except) => B.validateLabel(m, label, except === undefined ? "Copy1" : except);
  const r = B.renameSection(m, "Copy1", "  Garage floor  ");
  const snap = snapshot(r);
  const rootRenamed = B.renameSection(polish(), "Polish", "Main floor");
  const sheetRenamed = B.renameSection(withEpoxy(polish(), "base"), "Epoxy", "Warehouse");
  // a name that is also a property name of every object is only ever a VALUE: it is never a key, so nothing is polluted
  const sneaky = Object.fromEntries(["__proto__", "constructor", "hasOwnProperty", "prototype", "toString"].map((word) => {
    const x = B.renameSection(m, "Copy1", word);
    return [word, { keys: Object.keys(x.tabs), label: B.sectionOf(x, "Copy1").label,
                    protoClean: Object.getPrototypeOf(x.tabs) === Object.prototype && ({}).label === undefined && ({}).Copy1 === undefined }];
  }));
  const long31 = "a".repeat(31), long32 = "a".repeat(32);
  const all = { empty: why(""), blank: why("   "), nothing: why(undefined), long32: why(long32), long31: why(long31),
                dupRoot: why("polish"), dupSheet: why("EPOXY"), dupOther: (() => { const x = B.renameSection(m, "Copy1", "Mine"); return B.validateLabel(x, "mine", "Epoxy"); })(),
                own: why("Epoxy copy"), ownCase: why("EPOXY COPY"), free: why("Something else") };
  ["!", ":", "\\", "/", "?", "*", "[", "]", "\""].forEach((ch) => { all["char " + ch] = why("a" + ch + "b"); });
  const messages = Object.values(all).filter((v) => typeof v === "string");
  return {
    id: Object.keys(r.tabs), label: B.sectionOf(r, "Copy1").label, byLabel: snap.priced_tabs.map((t) => [t.id, t.name]),
    stored: r.tabs.Copy1.label, sheetStays: r.tabs.Copy1.sheet,
    rootRenamed: { label: B.sectionsOf(rootRenamed)[0].label, key: rootRenamed.label,
                   pricedName: (() => { const e = withEpoxy(rootRenamed, "base"); return snapshot(e).priced_tabs.map((t) => [t.id, t.name]); })() },
    sheetRenamed: { keys: Object.keys(sheetRenamed.tabs), label: B.sectionOf(sheetRenamed, "Epoxy").label, name: snapshot(sheetRenamed).priced_tabs.map((t) => [t.id, t.name]) },
    all: all, messageHasEmDash: messages.some((s) => s.indexOf("\u2014") >= 0), messageCount: messages.length,
    refused: { empty: threw(() => B.renameSection(m, "Copy1", "")), dup: threw(() => B.renameSection(m, "Copy1", "Polish")),
               long: threw(() => B.renameSection(m, "Copy1", long32)), unknown: threw(() => B.renameSection(m, "Copy7", "Fine")),
               char: threw(() => B.renameSection(m, "Copy1", "a/b")) },
    sameLabel: B.renameSection(m, "Copy1", "Epoxy copy") === m,
    sneaky: sneaky,
    inputUntouched: JSON.stringify(m) === JSON.stringify(c.model) && m.tabs.Copy1.label === "Epoxy copy",
    copyLabels: (() => { let x = polish(); const labels = [];
      for (let i = 0; i < 3; i++) { x = B.copySection(x, "Polish", {}).model; }
      B.sectionsOf(x).forEach((e) => labels.push(e.label)); return labels; })(),
    longCopyLabel: (() => { const x = B.renameSection(B.copySection(polish(), "Polish", {}).model, "Copy1", "b".repeat(31));
      const y = B.copySection(x, "Copy1", {}); const z = B.copySection(y.model, "Copy1", {});
      return [B.sectionOf(y.model, y.id).label.length, B.sectionOf(z.model, z.id).label.length, B.sectionOf(z.model, z.id).label.slice(-2)]; })(),
  };
}

// ── 7a. a name stays ONE sheet's over the life of the bid ─────────────────────────────────────
function labelsStayUnique() {
  const g1 = 'Gyp (USG 1-8")', fr = "Gyp (FR)";
  const names = (m) => B.sectionsOf(m).map((e) => [e.tab, e.label]);
  const labelKey = (m, id) => (has(m.tabs[id], "label") ? m.tabs[id].label : null);
  const out = {};
  // the root is renamed to the name of a sheet the bid does not hold yet, and that sheet is then added, by hand and by a job type
  const renamed = B.renameSection(polish(), "Polish", "Epoxy");
  const added = B.addSheet(renamed, "Epoxy", {});
  out.addSheet = { names: names(added.model), priced: snapshot(added.model).priced_tabs.map((t) => t.name), key: labelKey(added.model, "Epoxy") };
  out.jobType = names(B.sectionsForJob(renamed, "combo", {}));
  // a copy named "Seal" meets the Seal option
  const sealed = B.renameSection(B.copySection(polish(), "Polish", {}).model, "Copy1", "Seal");
  const opt = B.addOption(sealed, "Seal", {});
  out.addOption = { names: names(opt), key: labelKey(opt, "Seal") };
  // a Gyp copy named for the preset the base then moves to
  const gm = B.activateSection(polish(), g1, "base", {});
  const gc = B.copySection(gm, g1, {});
  const onFr = B.renameSection(B.moveSectionSheet(gc.model, gc.id, fr), gc.id, fr);
  const moved = B.moveSectionSheet(onFr, g1, fr);
  out.preset = { names: names(moved), key: labelKey(moved, fr), plain: names(B.moveSectionSheet(gm, g1, fr)), plainKey: labelKey(B.moveSectionSheet(gm, g1, fr), fr) };
  // a name that is free is not written: a saved bid keeps no `label` for a sheet filed under its own name
  out.free = { addSheet: labelKey(B.addSheet(polish(), "Epoxy", {}).model, "Epoxy"),
               activate: labelKey(B.activateSection(polish(), "Epoxy", "option", {}), "Epoxy"),
               other: labelKey(B.activateSection(renamed, "Seal", "option", {}), "Seal") };
  // a sheet may keep the name it has, even the one the tool made (a quote mark in it), and nobody else may type one
  const own = gc.model.tabs[gc.id].label;
  out.ownName = { label: own, same: B.validateLabel(gc.model, own, gc.id), otherCase: B.validateLabel(gc.model, own.toUpperCase(), gc.id),
                  rename: B.renameSection(gc.model, gc.id, own) === gc.model, typedQuote: B.validateLabel(gc.model, 'a"b', gc.id),
                  forAnother: B.validateLabel(gc.model, own, "Polish"), tooLong: B.validateLabel(gc.model, "a".repeat(32), gc.id),
                  unreadable: B.validateLabel({ tabs: { Epoxy: {} } }, 'a"b', "Polish") };
  return out;
}

// ── 7b. the Gyp preset, on a section filed under its sheet's name and on a copy ───────────────
function presets() {
  const g1 = 'Gyp (USG 1-8")', fr = "Gyp (FR)";
  const m = B.activateSection(polish(), g1, "base", {});
  m.tabs[g1].takeoff = clone(AREA);
  const named = B.moveSectionSheet(m, g1, fr);
  const c = B.copySection(m, g1, {});
  const moved = B.moveSectionSheet(c.model, c.id, fr);
  const sameSheet = B.moveSectionSheet(c.model, c.id, g1);
  return {
    named: { keys: Object.keys(named.tabs), profile: named.tabs[fr].profile, sheet: B.sectionOf(named, fr).sheet },
    copy: { keys: Object.keys(moved.tabs), sheet: moved.tabs[c.id].sheet, label: moved.tabs[c.id].label, profile: moved.tabs[c.id].profile,
            kind: moved.tabs[c.id].kind, entrySheet: B.sectionOf(moved, c.id).sheet, rows: moved.tabs[c.id].takeoff.length,
            sourceUntouched: moved.tabs[g1].sheet === undefined && Object.keys(moved.tabs).indexOf(g1) >= 0 },
    sameSheetIsTheModel: sameSheet === c.model,
    noSectionKeepsItsOldSheetsName: !has(moved.tabs, fr),
    refused: { notAGypSheet: threw(() => B.moveSectionSheet(c.model, c.id, "Epoxy")), unknown: threw(() => B.moveSectionSheet(c.model, "Copy9", fr)),
               root: threw(() => B.moveSectionSheet(c.model, "Polish", fr)),
               heldSheet: threw(() => B.moveSectionSheet(B.activateSection(m, fr, "option", {}), g1, fr)) },
    priceOnCopy: (() => { const r = B.priceSection(moved, c.id, { material: () => GYP }); return [r.priceable, r.total > 0]; })(),
    truckload: [E.forTab(fr).truckload, (() => { const r = B.priceSection(moved, c.id, { material: () => Object.assign({}, GYP, { soundMatRolls: 400 }) });
      const r2 = B.priceSection(B.copySection(m, g1, {}).model, "Copy1", { material: () => Object.assign({}, GYP, { soundMatRolls: 400 }) });
      return [r.shipping, r2.shipping]; })()],
  };
}

// ── 8. adding a fresh sheet ───────────────────────────────────────────────────────────────────
const LIB_LABOR = [
  { id: "travel", name: "Travel", rate: "41.00", unit: "hours", guys_auto: true, favorite: true, default_on: false },
  { id: "lab-ep", name: "Epoxy install", rate: 0, unit: "days", guys_auto: false, favorite: true, default_on: true, default_work_types: ["epoxy"] },
  { id: "lab-po", name: "Polish only", rate: 0, unit: "days", guys_auto: false, favorite: true, default_on: true, default_work_types: ["polish"] },
];
function adding() {
  const seed = (extra) => Object.assign({ laborRows: B.withCrewFallback(clone(LIB_LABOR)), laborRate: 50, travelRates: { lodging: 99, per_diem: 77 },
    feesDefault: 250, calcRows: null, conditionRows: [{ key: "dye", on: true }], cellValues: {}, split: false, asms: [], items: [], reserved: [], sf: {} }, extra || {});
  const out = { offered: B.sheetsToAdd() };
  const gyp = 'Gyp (USG 1-8")';
  const state = { tab_opts: { Other: { is_option: true } } };
  const m0 = polish();
  const before = JSON.stringify(m0);
  out.sheets = Object.fromEntries(B.sheetsToAdd().map((sheet) => {
    const r = B.addSheet(m0, sheet, seed({ state: state, sf: { [sheet]: [8000, ""] } }));
    const s = r.model.tabs[r.id];
    return [sheet, {
      id: r.id, kind: s.kind, layout: s.layout, profile: s.profile, pool: s.pool_packs, ownKey: r.id === sheet,
      hasSheet: has(s, "sheet") ? s.sheet : null, hasLabel: has(s, "label") ? s.label : null, hasRates: has(s, "rates"),
      patch: r.patch.tab_opts[r.id], keptOther: !!r.patch.tab_opts.Other,
      labor: s.labor.map((x) => x.id), takeoff: s.takeoff.map((x) => x.measurement),
      rootUntouched: JSON.stringify(Object.assign({}, r.model, { tabs: undefined })) === JSON.stringify(Object.assign({}, m0, { tabs: undefined })),
      role: B.sectionOf(r.model, r.id).role, entryLabel: B.sectionOf(r.model, r.id).label,
    }];
  }));
  out.inputUntouched = JSON.stringify(m0) === before;
  // a second sheet of a type is a Copy; a different Seal sheet is its own key until a Seal is held
  let m = polish();
  const order = [];
  ["Epoxy", "Epoxy", "Polish", "Seal", "Seal (+Jnts)", gyp, gyp].forEach((sheet) => {
    const r = B.addSheet(m, sheet, {});
    m = r.model; order.push([sheet, r.id, B.sectionOf(m, r.id).label, B.sectionOf(m, r.id).sheet]);
  });
  out.order = order;
  // priced: a new Epoxy sheet through the engine, a new Polish sheet through polishBid
  const prices = {};
  const e = B.addSheet(polish(), "Epoxy", {}); e.model.tabs.Epoxy.takeoff = clone(EPOXY_ROWS); e.model.tabs.Epoxy.labor = clone(EPOXY_LABOR);
  prices.epoxy = B.priceSection(e.model, "Epoxy", CTX).priceable !== false;
  const p = B.addSheet(polish(), "Polish", {}); p.model.tabs.Copy1.takeoff = clone(AREA);
  p.model.tabs.Copy1.labor = [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33 }];
  const pb = B.priceSection(p.model, "Copy1", CTX);
  prices.polish = { priceable: pb.priceable !== false, tooling: pb.tooling > 0 };
  out.prices = prices;
  // the area comes from the caller's sf, keyed by the new id or by the sheet's name
  out.sfByKey = {
    byId: B.addSheet(polish(), "Polish", seed({ sf: { Copy1: [7000, ""] } })).model.tabs.Copy1.takeoff.map((x) => x.measurement),
    bySheet: B.addSheet(polish(), "Polish", seed({ sf: { Polish: [6000, ""] } })).model.tabs.Copy1.takeoff.map((x) => x.measurement),
    none: B.addSheet(polish(), "Polish", seed({})).model.tabs.Copy1.takeoff.map((x) => x.measurement),
  };
  // a sheet added to a bid does not reseed what the estimator typed in the root: its labor is stated, and its takeoff is blank
  // on purpose (an area handed in for the new sheet would fill it if the root were taken from the seeding too)
  const typed = polish(); typed.takeoff = [{ assembly_id: "", assembly_name: "", measurement: "", unit: "SF" }];
  const added = B.addSheet(typed, "Polish", seed({ sf: { Polish: [9999, ""] } }));
  out.rootKept = { takeoff: added.model.takeoff.map((x) => x.measurement), labor: added.model.labor.map((x) => x.id), fees: added.model.fees,
                   newSheet: added.model.tabs.Copy1.takeoff.map((x) => x.measurement) };
  // the new sheet is on the proposal as an option, in the snapshot
  const snap = snapshot(B.addSheet(polish(), "Seal", {}).model);
  out.snapshot = { tabOpts: snap.tab_opts, lump: snap.proposal_lump_sum === B.polishBid(polish(), "Polish", CTX).total };
  out.badSheet = threw(() => B.addSheet(polish(), "Polish ", {}));
  out.noModel = threw(() => B.addSheet(null, "Polish", {}));
  return out;
}

// ── 9. the job type follows the base, and the base is not undone by the job type ──────────────
function jobTypes() {
  const out = {};
  // (a) the bid's base already IS the job type: nothing is added, nothing is turned off, the model is the one handed in
  let m = withEpoxy(polish(), "option");
  m = B.copySection(m, "Epoxy", {}).model;
  m = B.pickBase(m, ["Copy1"], {}).model;
  m = B.deleteSection(m, "Epoxy", {}).model;               // the sheet-named Epoxy is gone: the only Epoxy is Copy1
  const same = B.sectionsForJob(m, "epoxy", {});
  out.baseIsACopy = { base: B.baseOf(m), sameObject: same === m, tabs: Object.keys(same.tabs), kinds: B.sectionsOf(same).map((e) => [e.tab, e.kind]),
                      toAdd: B.sectionsToAdd(m, "epoxy"), leaving: B.sectionsLeaving(m, "epoxy") };
  // (b) the job type moved: a copy of Polish is the base of a Polish job, then the intake says Epoxy
  const polishCopyBase = B.pickBase(B.copySection(withEpoxy(polish(), "option"), "Polish", {}).model, ["Copy1"], {}).model;   // Copy1 base, root and Epoxy options
  out.polishCopyIsThePolishBase = { base: B.baseOf(polishCopyBase), sameObject: B.sectionsForJob(polishCopyBase, "polish", {}) === polishCopyBase,
                                    leaving: B.sectionsLeaving(polishCopyBase, "polish") };
  out.leavingCopy = B.sectionsLeaving(polishCopyBase, "epoxy");
  const toEpoxy = B.sectionsForJob(polishCopyBase, "epoxy", {});
  out.toEpoxy = { base: B.baseOf(toEpoxy), kinds: B.sectionsOf(toEpoxy).map((e) => [e.tab, e.kind]), rootKey: has(toEpoxy, "kind") ? toEpoxy.kind : null,
                  epoxyRowsKept: toEpoxy.tabs.Epoxy.takeoff.length === 2, activated: Object.keys(toEpoxy.tabs) };
  const toCombo = B.sectionsForJob(polishCopyBase, "combo", {});
  out.toCombo = { base: B.baseOf(toCombo), kinds: B.sectionsOf(toCombo).map((e) => [e.tab, e.kind]) };
  const toGyp = B.sectionsForJob(polishCopyBase, "gyp", {});
  out.toGyp = { base: B.baseOf(toGyp), kinds: B.sectionsOf(toGyp).map((e) => [e.tab, e.kind]), activated: Object.keys(toGyp.tabs).filter((k) => k.indexOf("Gyp") === 0) };
  // (c) an option that is the job type's tab is made the base (a saved bid with an Epoxy option, job type moved to Epoxy)
  const optionEpoxy = withEpoxy(polish(), "option");
  const switched = B.sectionsForJob(optionEpoxy, "epoxy", {});
  out.optionBecomesBase = { base: B.baseOf(switched), kinds: B.sectionsOf(switched).map((e) => [e.tab, e.kind]), keptRows: switched.tabs.Epoxy.takeoff.length };
  // (d) back to Polish: the root is lifted (the key is dropped), Epoxy is marked off with its rows kept
  const back = B.sectionsForJob(switched, "polish", {});
  out.backToPolish = { base: B.baseOf(back), kinds: B.sectionsOf(back).map((e) => [e.tab, e.kind]), rootHasKind: has(back, "kind"), epoxyRows: back.tabs.Epoxy.takeoff.length };
  // (e) an option stays an option when the job type moves away from its tab
  const withSeal = B.activateSection(withEpoxy(polish(), "base"), "Seal", "option", {});
  const sealJob = B.sectionsForJob(withSeal, "polish", {});
  out.optionStays = { kinds: B.sectionsOf(sealJob).map((e) => [e.tab, e.kind]) };
  // (f) the root as an option is lifted when the job type needs it and nothing else is the Polish base
  const rootOption = B.pickBase(withEpoxy(polish(), "option"), ["Epoxy"], {}).model;
  const lifted = B.sectionsForJob(rootOption, "polish", {});
  out.rootOptionLifted = { before: B.baseOf(rootOption), after: B.baseOf(lifted), kinds: B.sectionsOf(lifted).map((e) => [e.tab, e.kind]), rootHasKind: has(lifted, "kind") };
  // (g) sections that cannot be read are returned as they are, and the job-type readers never throw on them
  const broken = withEpoxy(polish(), "base"); delete broken.tabs.Epoxy.layout;
  out.unreadable = { same: B.sectionsForJob(broken, "polish", {}) === broken, toAdd: B.sectionsToAdd(broken, "gyp"), leaving: B.sectionsLeaving(broken, "polish") };
  // (h) what the page asks before it loads the library
  out.toAdd = { polishBidForEpoxy: B.sectionsToAdd(polish(), "epoxy"), hasEpoxyOption: B.sectionsToAdd(optionEpoxy, "epoxy"), combo: B.sectionsToAdd(polish(), "combo"),
                comboCopyHeld: B.sectionsToAdd(B.copySection(optionEpoxy, "Epoxy", {}).model, "combo"),
                copyOnly: B.sectionsToAdd(m, "combo") };
  out.throws = { notReady: threw(() => B.sectionsForJob(polish(), "seal", {})), noModel: threw(() => B.sectionsForJob(null, "polish", {})) };
  return out;
}

// ── 10. what a save writes ────────────────────────────────────────────────────────────────────
function snapshots() {
  const out = {};
  const single = snapshot(polish());
  out.singleKeys = Object.keys(single);
  const optionOnly = snapshot(withEpoxy(polish(), "option"));
  out.baseTabId = {
    rootWithOption: optionOnly.base_tab_id,
    epoxyBase: (() => { const m = withEpoxy(polish(), "base"); m.kind = "off"; return snapshot(m).base_tab_id; })(),
    combined: snapshot(withEpoxy(polish(), "base")).base_tab_id,
    copyBase: snapshot(B.pickBase(B.copySection(polish(), "Polish", {}).model, ["Copy1"], {}).model).base_tab_id,
    noBase: (() => { const m = withEpoxy(polish(), "option"); m.kind = "off"; return snapshot(m).base_tab_id; })(),
  };
  const c = B.copySection(withEpoxy(polish(), "base"), "Epoxy", {});
  const renamed = B.renameSection(c.model, "Copy1", "Second floor");
  const s = snapshot(renamed, c.patch.tab_opts);
  out.names = s.priced_tabs.map((t) => [t.id, t.name, t.kind, t.role]);
  out.tabOpts = s.tab_opts;
  out.heldEntryKept = (() => { const held = { Copy1: { is_option: true, show: false, price_mode: "deduct", desc: "words" } }; return snapshot(renamed, held).tab_opts.Copy1; })();
  out.sealTotalOnly = (() => { const m = B.activateSection(polish(), "Seal", "option", {}); return snapshot(m).tab_opts.Seal.price_mode; })();
  out.copyOfSealTotalOnly = (() => { const m = B.copySection(B.activateSection(polish(), "Seal", "option", {}), "Seal", {}); return [m.patch.tab_opts.Copy1.price_mode, snapshot(m.model).tab_opts.Copy1.price_mode]; })();
  // lump sum and area are the bases' alone, a Polish copy option adds nothing
  const withPolishCopy = B.copySection(polish(), "Polish", {});
  const wp = snapshot(withPolishCopy.model);
  out.polishCopyOption = { lump: wp.proposal_lump_sum, rootTotal: B.polishBid(polish(), "Polish", CTX).total, area: wp.sheet_area,
                           tabs: wp.priced_tabs.map((t) => [t.id, t.kind, t.v2, t.sf]) };
  // the root as an option, with a Polish copy as the base: the copy's total is the lump sum, the root is priced apart
  const swapped = B.pickBase(withPolishCopy.model, ["Copy1"], {}).model;
  const sw = snapshot(swapped);
  out.rootOption = { lump: sw.proposal_lump_sum, copyTotal: B.polishBid(swapped, "Copy1", CTX).total, baseTabId: sw.base_tab_id,
                     polishSf: sw.polish_sf, tabs: sw.priced_tabs.map((t) => [t.id, t.kind]), rootKind: swapped.kind,
                     optionEntry: sw.tab_opts && sw.tab_opts.Polish };
  // an old saved bid's pieces are read as they were: nothing is added to a root-only save
  out.oldBid = { entries: entryRows(withEpoxy(B.activateSection(polish(), "Seal", "option", {}), "base")),
                 keys: Object.keys(snapshot(withEpoxy(B.activateSection(polish(), "Seal", "option", {}), "base"))) };
  // reading never writes: a deep-frozen model goes through every reader
  const frozen = deepFreeze(clone(withEpoxy(B.activateSection(polish(), "Seal", "option", {}), "base")));
  out.frozen = {
    entries: threw(() => entryRows(frozen)), baseOf: threw(() => B.baseOf(frozen)), polishBid: threw(() => B.polishBid(frozen, "Polish", CTX)),
    tabs: threw(() => B.priceTabs(frozen, CTX)), snapshot: threw(() => B.composePricingSnapshot(frozen, deepFreeze(clone(priceAll(frozen))))),
    job: threw(() => B.sectionsForJob(frozen, "combo", {})), leaving: threw(() => B.sectionsLeaving(frozen, "polish")),
    rename: threw(() => B.renameSection(frozen, "Epoxy", "Flooring")), copy: threw(() => B.copySection(frozen, "Epoxy", {})),
    delete: threw(() => B.deleteSection(frozen, "Seal", {})), add: threw(() => B.addSheet(frozen, "Gyp (FR)", {})),
  };
  return out;
}

// ── 11. the real estimate page ────────────────────────────────────────────────────────────────
function loadPrelude(file, exportNames) {
  const base = path.join(__dirname, file);
  const code = L.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in sheets-model-harness.js");
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
  const out = {};
  // A Polish bid with a copy of its Polish sheet: the page prices the copy as it prices the root
  const model = clone(P.MODEL);
  model.conditions.dye = true;            // Dye is the job's, and a Polish copy is bought like the root: with it
  const copied = B.copySection(model, "Polish", {});
  const b = P.build({ blob: P.blob({ polish_estimate: clone(copied.model), polish_sf: 12500, tab_opts: copied.patch.tab_opts }) });
  await b.api.init();
  const bids = b.api.sectionBids();
  const rootBid = b.api.bid();
  const direct = B.polishBid(b.api.model(), "Polish", { material: () => 0, remodel_rate: null });
  out.copyOnPage = { tabs: Object.keys(bids), copyTotal: bids.Copy1 && bids.Copy1.total, rootTotal: rootBid.total,
                     same: !!bids.Copy1 && sameKeys(bids.Copy1, rootBid), copyKeys: bids.Copy1 ? Object.keys(bids.Copy1).length : 0,
                     rootIsPolishBid: typeof direct.total === "number" };
  // its material is the root's, Dye and Joint Filler included
  b.api.show("Copy1");
  out.materialOnShow = { copy: b.api.materialTotal(), activeBid: b.api.activeBid().total };
  b.api.show("Polish");
  out.materialRoot = b.api.materialTotal();
  // the save writes the copy as a priced option under its label, and names the base
  P.typeInto(b, '[data-tk="0"][data-k="measurement"]', "12000");
  b.clock.fire();
  const saved = last(b.rec.saves);
  out.saved = { keys: Object.keys(saved), tabs: (saved.priced_tabs || []).map((t) => [t.id, t.name, t.kind, t.role, t.v2]),
                baseTabId: saved.base_tab_id, tabOpts: saved.tab_opts, lump: saved.proposal_lump_sum,
                rootTotal: saved.polish_estimate && saved.polish_estimate.totals && saved.polish_estimate.totals.total };
  // a Copy made the base: the page opens on it and prices both by role
  // The job is 70 miles out (ten nights typed): the base carries the job's Lodging, the option its own for its own crew.
  const farModel = clone(copied.model);
  farModel.conditions.local = false;
  farModel.travel = B.travelCostsSeed();
  farModel.travel.lodging = { label: "Lodging", enabled: true, qty: 10, qty_auto: false, rate: 100 };
  const swapped = B.pickBase(farModel, ["Copy1"], {}).model;
  const s = P.build({ blob: P.blob({ polish_estimate: clone(swapped), polish_sf: 12500 }) });
  await s.api.init();
  const sb = s.api.sectionBids();
  out.rootAsOption = { opensOn: (() => { try { return B.travelCarrier(s.api.model()); } catch (e) { return String(e); } })(),
                       rootKind: s.api.model().kind, copyTotal: sb.Copy1 && sb.Copy1.total, rootTotal: s.api.bid().total,
                       rootTravel: s.api.bid().travel, copyTravel: sb.Copy1 && sb.Copy1.travel,
                       ownByHand: Math.ceil(B.travelManDays(s.api.model().labor) * 100) };
  // renaming a section shows its new name where the page names it (the bar under the title, the section strip)
  const named = B.renameSection(copied.model, "Copy1", "Garage floor");
  const n = P.build({ blob: P.blob({ polish_estimate: clone(named), polish_sf: 12500 }) });
  await n.api.init();
  out.renamedOnPage = { strip: n.doc.getElementById("sheets-panel").innerHTML, maths: n.doc.getElementById("maths").innerHTML };
  // a Gyp section that is a copy is read from its `sheet` and not from its Copy<N> key: the page prices both alike
  const GYPSHEET = 'Gyp (USG 1-8")';
  const gm = clone(P.MODEL);
  gm.kind = "off";
  gm.tabs = { [GYPSHEET]: { layout: "gyp", kind: "base", profile: "gyp@1",
    takeoff: [{ assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: 9000, unit: "SF" }],
    labor: [{ id: "inst", label: "Install", guys: 4, days: 3, rate: 33.66 }], contingency: 0, fees: 0, totals: {} } };
  const gcopy = B.copySection(gm, GYPSHEET, {}).model;
  const g = P.build({ blob: P.blob({ work_type: "gyp", polish_estimate: clone(gcopy), polish_sf: 12500 }) });
  await g.api.init();
  const gb = g.api.sectionBids();
  out.gypCopyOnPage = { tabs: Object.keys(gb), priceable: Object.keys(gb).map((k) => gb[k].priceable !== false),
                        totals: Object.keys(gb).map((k) => gb[k].total), jobType: B.baseOf(g.api.model()).jobType };
  // ...and a real Gyp AREA row on the copy is priced on the page's per-row path (the Material panel, the repaint of the numbers
  // and rowPrice itself), which is where the page must say the workbook SHEET and not the Copy<N> key: the first scenario above
  // never reaches it, because a Polish assembly is not an area row.
  const GYP_AREA = { id: "wb-gyp-area-soft", name: "Gypsum: soft surfaces", unit: "SF", lines: [] };
  const am = clone(gm);
  am.tabs[GYPSHEET].takeoff = [{ assembly_id: GYP_AREA.id, assembly_name: GYP_AREA.name, measurement: 9000, unit: "SF" }];
  const acopy = B.copySection(am, GYPSHEET, {}).model;
  const a = P.build({ blob: P.blob({ work_type: "gyp", polish_estimate: clone(acopy), polish_sf: 12500 }), asms: P.ASMS.concat([clone(GYP_AREA)]) });
  await a.api.init();
  const attempt = (fn) => { try { return { value: fn() }; } catch (e) { return { threw: String(e && e.message || e) }; } };
  const rowOn = (id) => a.api.model().tabs[id].takeoff;
  const rowTotal = (id) => { const r = attempt(() => a.api.rowPrice(rowOn(id)[0], rowOn(id))); return r.threw ? r : r.value && r.value.total; };
  const rows = { source: rowTotal(GYPSHEET), copy: rowTotal("Copy1") };
  const shown = {};
  ["Copy1", GYPSHEET].forEach((id) => {
    a.api.show(id);
    const painted = attempt(() => { a.api.renderPanel(); return a.doc.getElementById("panels").innerHTML.length; });
    const repainted = attempt(() => { a.api.repaintNumbers(); return true; });
    shown[id] = { panel: painted.threw || (painted.value > 0), repaint: repainted.threw || repainted.value };
  });
  out.gypAreaRowOnCopy = { rows: rows, shown: shown };
  return out;
}

// ── main ──────────────────────────────────────────────────────────────────────────────────────
// ── 9. what the draft kept under a sheet's key follows the key when the key changes (a Gyp sheet's preset) ──────────────────────
function draftMoves() {
  const g1 = 'Gyp (USG 1-8")', fr = "Gyp (FR)";
  const line = (id, rest) => "option:" + id + (rest || "");
  const state = {
    work_type: "polish",
    tab_opts: { Other: { keep: 1 }, [g1]: { show_system: true, is_option: false, show: true, price_mode: "deduct", desc: "my gyp words" } },
    tab_notes: { Other: ["kept"], [g1]: ["a note"] },
    price_overrides: {
      options: { Other: { label: "kept" }, [g1]: { label: "mine" } },
      lines: { [line(g1)]: "legacy words" },
      lines2: { base: "base words", [line("Other")]: "kept", [line(g1)]: "my line", [line(g1, ":sales_tax")]: "my tax row", [line(g1, " x")]: "not a row of this sheet" },
      before: { [line(g1)]: ["above"] }, after: { [line(g1, ":remodel")]: ["below"] },
      line_props: { [line(g1)]: { bullet: "o" } }, before_props: {}, after_props: { [line(g1)]: { bullet: "o" } },
      single_bid: { [g1]: "not a line map, so it stays" },
    },
  };
  const frozen = deepFreeze(clone(state));
  const patch = B.moveSheetDraftPatch(frozen, g1, fr);
  const pov = patch.price_overrides || {};
  const keysOf = (o) => Object.keys(o || {});
  // nothing was held under the old key, but a stale entry sits under the new one (left by an earlier sheet of that name)
  const stale = B.moveSheetDraftPatch({ tab_opts: { [fr]: { is_option: true, stale: true }, Other: { keep: 1 } }, tab_notes: { Other: ["kept"] } }, g1, fr);
  const sealed = B.activateSection(polish(), "Seal", "option", {});
  const held = (mode) => ({ tab_opts: { Seal: { is_option: true, show: false, price_mode: mode, desc: "seal words" }, Polish: { price_mode: "deduct" } } });
  const total = B.optionOnlyTotalPatch(sealed, deepFreeze(held("deduct")));
  const copyOfSeal = B.copySection(sealed, "Seal", {});
  const copyHeld = { tab_opts: { Seal: { price_mode: "total" }, Copy1: { is_option: true, price_mode: "deduct" } } };
  return {
    keys: keysOf(patch).sort(), tabOpts: keysOf(patch.tab_opts), opt: patch.tab_opts && patch.tab_opts[fr], otherOpt: patch.tab_opts && patch.tab_opts.Other,
    notes: patch.tab_notes, options: pov.options, lines: pov.lines, lines2: pov.lines2, before: pov.before, after: pov.after,
    lineProps: pov.line_props, afterProps: pov.after_props, beforeProps: pov.before_props, single: pov.single_bid,
    inputUntouched: JSON.stringify(frozen) === JSON.stringify(state),
    stale: { keys: keysOf(stale).sort(), tabOpts: stale.tab_opts, notes: stale.tab_notes },
    nothing: [B.moveSheetDraftPatch({ tab_opts: { Other: {} } }, g1, fr), B.moveSheetDraftPatch(state, g1, g1), B.moveSheetDraftPatch(undefined, g1, fr),
              B.moveSheetDraftPatch({ tab_opts: [1], price_overrides: "x" }, g1, fr)],
    // a Seal option is a total
    // (the draft handed in is frozen, so a write into it would throw and the section would report an error)
    sealTotal: { patch: total, polishUntouched: total.tab_opts && total.tab_opts.Polish.price_mode === "deduct" },
    sealAlready: B.optionOnlyTotalPatch(sealed, held("total")), sealNoEntry: B.optionOnlyTotalPatch(sealed, { tab_opts: { Other: {} } }),
    sealNoOpts: [B.optionOnlyTotalPatch(sealed, {}), B.optionOnlyTotalPatch(sealed, undefined), B.optionOnlyTotalPatch({ tabs: "nonsense" }, held("deduct"))],
    sealCopy: B.optionOnlyTotalPatch(copyOfSeal.model, copyHeld),
    polishDeduct: B.optionOnlyTotalPatch(B.copySection(polish(), "Polish", {}).model, { tab_opts: { Copy1: { price_mode: "deduct" } } }),
  };
}

(async function () {
  const sections = { identity, copies, polishCopies, baseBid, combinedBase, refusals, idReuse, baseOfCases, renaming, labelsStayUnique, presets, draftMoves, adding, jobTypes, snapshots };
  const done = Object.keys(sections).map((name) => {
    try { return [name, sections[name]()]; } catch (e) { return [name, { error: String(e && e.stack || e) }]; }
  });
  let pageOut;
  try { pageOut = await page(); } catch (e) { pageOut = { error: String(e && e.stack || e) }; }
  console.log(JSON.stringify(Object.assign(Object.fromEntries(done), { page: pageOut })));
})();
