"use strict";
/* POLISH REV 2 IN THE MODEL: which bids are priced by it, and what it does to the numbers.
 *
 *   node polish-rev2-model-harness.js <frontend dir>
 *
 * Phase 17 gives a NEW bid's Polish section the profile `polish-rev2@1` and leaves every saved bid on
 * `polish-legacy@1`. Everything here EXECUTES the real js/bid-model.js and js/bid-engine.js (the estimate page,
 * whole, is run by save-patch-golden-harness.js and compared in test_polish_rev2.py). Each part catches its own
 * failure and reports it as `{error}`, so the same harness can run over a broken scratch copy and fail as an
 * assertion. Prints, as its last line, one JSON object.
 */
const path = require("path");

const ROOT = path.resolve(process.argv[2]);
const B = require(path.join(ROOT, "js", "bid-model.js"));
const E = require(path.join(ROOT, "js", "bid-engine.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));
const threw = (fn) => { try { fn(); return null; } catch (e) { return String(e && e.message || e); } };
const REV2 = "polish-rev2@1", REV3 = "polish-rev3@1", LEGACY = "polish-legacy@1";

/** A Polish bid with an area, a crew and a county, the way the page writes it: root keys only. */
function polishBid(extra) {
  const m = B.freshModel();
  m.takeoff = [{ assembly_id: "a1", assembly_name: "Polish - S&P", measurement: 10000, unit: "SF" }];
  m.labor = [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33 }];
  return Object.assign(m, extra || {});
}
const MATERIAL = (e) => 12000;
const priced = (model) => B.priceSection(model, "Polish", { material: MATERIAL, remodel_rate: 0.07975 });
const LIB_LABOR = [{ id: "travel", name: "Travel", rate: "41.00", unit: "hours", guys_auto: true, favorite: true, default_on: false }];
const seedCtx = (extra) => Object.assign({ saved: undefined, laborRows: B.withCrewFallback(clone(LIB_LABOR)), laborRate: 50,
  travelRates: { lodging: 99, per_diem: 77 }, feesDefault: 0, calcRows: null, conditionRows: [{ key: "dye", on: true }],
  cellValues: {}, split: false, asms: [], items: [], reserved: [], sf: {} }, extra || {});

function part(fn) { try { return fn(); } catch (e) { return { error: String(e && e.stack || e) }; } }
const out = {};

// ── 1. who is stamped ────────────────────────────────────────────────────────────────────────────────────────
out.stamping = part(() => {
  const fresh = B.migrateModel(undefined);
  const newBid = B.seedNewSections(fresh, seedCtx({ sf: { Polish: [8000, ""] } }));
  // A saved bid: the gates are shut (the saved blob states labor), so nothing is written to it
  const saved = polishBid();
  const savedBlob = clone(saved);
  const afterSeed = B.seedNewSections(saved, seedCtx({ saved: savedBlob }));
  // A new Combo bid: the Polish root is stamped, the Epoxy section carries its own profile
  let combo = B.migrateModel(undefined);
  combo = B.activateSection(combo, "Epoxy", "base", { rules: [] });
  const comboSeeded = B.seedNewSections(combo, seedCtx({ sf: { Polish: [8000, ""], Epoxy: [4000, ""] } }));
  // A new EPOXY-ONLY bid: the root is off, it is not a Polish bid, and it is not stamped
  let epoxyOnly = B.activateSection(B.migrateModel(undefined), "Epoxy", "base", { rules: [] });
  epoxyOnly = Object.assign({}, epoxyOnly, { kind: "off" });
  const epoxySeeded = B.seedNewSections(epoxyOnly, seedCtx({ sf: { Epoxy: [4000, ""] } }));
  // A key the caller already put there is never overwritten
  const keep = B.seedNewSections(Object.assign(B.migrateModel(undefined), { profile: "polish-legacy@1" }), seedCtx({}));
  // A saved rev2 bid (made before 2026-10-16) is seeded again and is still rev2: rev3 never reaches it
  const keepRev2 = B.seedNewSections(Object.assign(B.migrateModel(undefined), { profile: REV2 }), seedCtx({}));
  // The job type moving: an Epoxy bid whose root never held a takeoff is switched to Polish; one that did keeps none
  const epoxyBid = Object.assign(B.activateSection(B.migrateModel(undefined), "Epoxy", "base", { rules: [] }), { kind: "off" });
  const liftedEmpty = B.sectionsForJob(epoxyBid, "polish", {});
  const usedRoot = Object.assign(clone(epoxyBid), { takeoff: polishBid().takeoff });
  const liftedUsed = B.sectionsForJob(usedRoot, "polish", {});
  return {
    newBid: newBid.profile === undefined ? null : newBid.profile, savedAfterSeed: afterSeed.profile === undefined ? null : afterSeed.profile,
    savedHasNoKey: !Object.prototype.hasOwnProperty.call(afterSeed, "profile"),
    combo: comboSeeded.profile === undefined ? null : comboSeeded.profile, comboEpoxySection: comboSeeded.tabs.Epoxy.profile,
    epoxyOnlyRoot: epoxySeeded.profile === undefined ? null : epoxySeeded.profile,
    keptTheKeyItHad: keep.profile === undefined ? null : keep.profile,
    keptRev2: keepRev2.profile === undefined ? null : keepRev2.profile,
    liftedEmptyRoot: liftedEmpty.profile === undefined ? null : liftedEmpty.profile,
    liftedUsedRoot: liftedUsed.profile === undefined ? null : liftedUsed.profile,
    newBidSections: B.sectionsOf(newBid).map((e) => [e.tab, e.profile]),
  };
});

// ── 2. the root reads exactly one stamp ──────────────────────────────────────────────────────────────────────
out.rootProfile = part(() => {
  const stamp = (v) => B.sectionsOf(polishBid(v === undefined ? {} : { profile: v }))[0].profile;
  return {
    none: stamp(undefined), rev2: stamp(REV2), rev3: stamp(REV3), legacy: stamp(LEGACY), reserved: stamp("polish@1"),
    laterRev: stamp("polish-rev2@2"), junk: stamp(7), nullKey: stamp(null),
    markupChainNoStamp: threw(() => B.markupChain({ material: 1 })),
    markupChainUnknown: threw(() => B.markupChain({ material: 1 }, "epoxy@1")),
    markupChainBadArg: threw(() => B.markupChain({ material: 1 }, 5)),
  };
});

// ── 3. what the chain does with the tooling, by stamp ────────────────────────────────────────────────────────
out.chain = part(() => {
  const input = { material: 5000, labor: 6000, travel: 400, tooling: 700, contingency: 0, fees: 0, sf: 10000,
    conditions: { local: true, taxable: true, prevailing_wage: false, remodel_tax: true }, remodel_rate: 0.07975 };
  const legacy = B.markupChain(input), legacyStamped = B.markupChain(input, LEGACY), rev2 = B.markupChain(input, REV2);
  const fromModel = B.markupChain(input, { profile: REV2 });
  const noTooling = B.markupChain(Object.assign({}, input, { tooling: 0 }), REV2);
  const base = (r) => r.labor + r.escalation + r.burden + r.gp + r.super_pto + r.soft_costs + r.contingency + r.fees;
  // THE PATCH LINE (polish-rev3, 2026-10-16): a patch handed to the chain is bought only by rev3. Saved bids are rev2 or
  // legacy, so the same patch handed to them must change nothing, and rev3 without one must be rev2 to the key.
  const withPatch = Object.assign({}, input, { patch: 400 });
  const rev3 = B.markupChain(withPatch, REV3), rev3NoPatch = B.markupChain(input, REV3);
  return {
    legacyPatchIgnored: JSON.stringify(B.markupChain(withPatch, LEGACY)) === JSON.stringify(legacy),
    rev2PatchIgnored: JSON.stringify(B.markupChain(withPatch, REV2)) === JSON.stringify(rev2),
    rev3NoPatchIsRev2: JSON.stringify(Object.assign({}, rev3NoPatch, { profile: 0 })) === JSON.stringify(Object.assign({}, rev2, { profile: 0 })),
    rev3Material: rev3.material, rev2Material: rev2.material, rev3SubTotalMinusRev2: rev3.sub_total - rev2.sub_total,
    legacyIgnoresTooling: legacy.sub_total === B.markupChain(Object.assign({}, input, { tooling: 0 })).sub_total,
    legacyStampSame: JSON.stringify(legacy) === JSON.stringify(legacyStamped),
    legacyKeys: Object.keys(legacy).includes("tooling"),
    rev2Keys: Object.keys(rev2).includes("tooling"), rev2Tooling: rev2.tooling,
    rev2SubTotalMinusLegacy: rev2.sub_total - legacy.sub_total,
    modelNamesTheProfile: JSON.stringify(rev2) === JSON.stringify(fromModel),
    // the remodel tax the sheet takes (D75): the labor side, tooling and travel, and the markups
    rev2Tax: rev2.remodel_tax, rev2TaxByHand: B.roundUp((base(rev2) + rev2.tooling + rev2.travel) * 0.07975),
    legacyTax: legacy.remodel_tax, legacyTaxByHand: B.roundUp(base(legacy) * 0.07975),
    noToolingRev2Total: noTooling.total,
  };
});

// ── 4. pricing the root as a section: a saved bid is as it was, a stamped one has the sheet's tooling ───────
out.pricing = part(() => {
  const saved = polishBid();
  const stamped = polishBid({ profile: REV2 });
  const noArea = polishBid({ profile: REV2, takeoff: [] });
  const s = priced(saved), r = priced(stamped), n = priced(noArea);
  const hand = B.polishTooling(10000, 0, { system: "sp" }).total;
  return {
    savedProfile: s.profile, stampedProfile: r.profile,
    savedTooling: s.tooling, stampedTooling: r.tooling, toolingByHand: hand,
    savedSubTotalByHand: s.material_total + s.labor + s.escalation + s.burden + s.travel,
    savedSubTotal: s.sub_total, stampedSubTotal: r.sub_total,
    stampedSubTotalByHand: r.material_total + r.labor + r.escalation + r.burden + r.travel + hand,
    noAreaTooling: n.tooling,
    rootToolingSaved: B.rootTooling(saved), rootToolingStamped: B.rootTooling(stamped),
    sameAsMarkupChain: JSON.stringify(B.markupChain({ material: 12000, labor: B.laborTotal(saved.labor, saved.conditions), travel: 0,
      contingency: 0, fees: 0, conditions: saved.conditions, sf: 10000, remodel_rate: 0.07975 }).total) === JSON.stringify(s.total),
  };
});

// ── 5. nights counted from labor, and who counts them so ─────────────────────────────────────────────────────
out.nights = part(() => {
  const mixed = [{ guys: 3, days: 5, rate: 33 }, { guys: 2, days: 2, rate: 48 }];
  const withTravel = [{ guys: 3, days: 5, rate: 33 }, { id: "travel", unit: "hours", guys: 18, days: 1, rate: 33 }];
  const auto = { lodging: { enabled: true, qty_auto: true, rate: 70 }, per_diem: { enabled: true, qty_auto: true, rate: 45 } };
  const typed = { lodging: { enabled: true, qty_auto: false, qty: 4, rate: 70 }, per_diem: { enabled: true, qty_auto: false, qty: 5, rate: 45 } };
  const rev2Opts = B.travelOpts(polishBid({ profile: REV2 }), "Polish");
  return {
    mixedPeopleDays: B.travelManDays(mixed), mixedSheet: B.sheetNights(mixed),
    withTravelSheet: B.sheetNights(withTravel), withTravelPeople: B.travelManDays(withTravel),
    firstRowRate: B.sheetNights([{ guys: 1, days: 2, rate: 40 }, { guys: 1, days: 2, rate: 20 }]),
    noRows: B.sheetNights([]), offRowLeftOut: B.sheetNights([{ guys: 3, days: 5, rate: 33 }, { guys: 9, days: 9, rate: 33, enabled: false }]),
    autoLegacy: B.travelCosts(auto, mixed).total, autoSheet: B.travelCosts(auto, mixed, rev2Opts).total,
    typedLegacy: B.travelCosts(typed, mixed).total, typedSheet: B.travelCosts(typed, mixed, rev2Opts).total,
    optsLegacyRoot: B.travelOpts(polishBid(), "Polish") === undefined,
    optsRev2Root: !!rev2Opts && rev2Opts.sheetNights === true,
    optsRev2Section: B.travelOpts(polishBid({ profile: REV2 }), "Epoxy") === undefined,
    // the model's conditions reach the night count: Remove Existing Joint Filler adds a fourth hand's dollars to the labor
    // the sheet's B58 divides, so the nights through travelOpts are 1 hand's worth more than the nights without them
    optsConditionsNights: (() => {
      const jf = [{ id: "jointfill", guys: 3, days: 5, rate: 33 }];
      const on = polishBid({ profile: REV2, conditions: { joint_filler: true, remove_existing_jf: true } });
      const off = polishBid({ profile: REV2, conditions: { joint_filler: true, remove_existing_jf: false } });
      const line = { lodging: { enabled: true, qty_auto: true, rate: 100 }, per_diem: { enabled: false } };
      return { on: B.travelCosts(line, jf, B.travelOpts(on, "Polish")).lodging,
               off: B.travelCosts(line, jf, B.travelOpts(off, "Polish")).lodging };
    })(),
    engineByHand: E.lodgingNights("polish-rev2", 5496, 0, 33),
    engineBadRate: E.lodgingNights("polish-rev2", 5496, 0, 0),
    engineGyp: E.lodgingNights("gyp", 5500, 0, 55),
    hintLegacy: B.lodgingHint(polishBid(), "Polish", false, mixed),
    hintRev2: B.lodgingHint(polishBid({ profile: REV2 }), "Polish", false, mixed),
    hintRev2SameRate: B.lodgingHint(polishBid({ profile: REV2 }), "Polish", false, [{ guys: 3, days: 5, rate: 33 }]),
    hintRev2Auto: B.lodgingHint(polishBid({ profile: REV2 }), "Polish", true, mixed),
    hintRev2OtherSection: B.lodgingHint(polishBid({ profile: REV2 }), "Epoxy", false, mixed),
  };
});

console.log(JSON.stringify(out));
