"use strict";
/* SPLITTING A BID'S SHEETS INTO SEPARATE PROPOSALS, in the model (scope groups, tier A1; RJ, 2026-10-24).
 *
 * Executes the real js/bid-model.js and js/bid-engine.js: B.splitOut, B.splitBlockers, B.splitTabs. One line of JSON comes
 * out and test_scope_split_model.py asserts on it. Every section catches its own failure and reports {error}, so a tree
 * without the functions fails as an assertion, not a crash.
 *
 * THE BID: Breakroom (the Polish root, the base, the job's travel carrier, its Lodging TYPED at 10 nights and its drive typed),
 * Lab 1 (an Epoxy option with no drive of its own) and Lab 2 (a copy of Lab 1). Far: Lodging and Per Diem on.
 *
 * Usage: node scope-split-harness.js <frontend-dir>   ->  one line of JSON
 */
const path = require("path");

const ROOT = path.resolve(process.argv[2]);
const B = require(path.join(ROOT, "js", "bid-model.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));
function deepFreeze(v) {
  if (v && typeof v === "object" && !Object.isFrozen(v)) {
    Object.freeze(v);
    Object.keys(v).forEach((k) => deepFreeze(v[k]));
  }
  return v;
}
const threw = (fn) => { try { fn(); return null; } catch (e) { return String((e && e.message) || e); } };

const MATS = { polish: 10000, epoxy: 8000, seal: 1500 };
const CTX = { material: (e) => MATS[e.role] || 0, remodel_rate: null };

function bid() {
  let m = B.freshModel();
  m.takeoff = [{ assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: 10000, unit: "SF" }];
  m.labor = [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33 },
             { id: "travel", label: "Travel Labor", unit: "hours", guys: 2, days: 4, rate: 33, guys_auto: false, guys_typed: true, hours_typed: true }];
  m.conditions.local = false;
  m.travel.lodging = Object.assign(m.travel.lodging, { enabled: true, qty_auto: false, qty: 10, qty_typed: true, rate: 100 });
  m.travel.per_diem = Object.assign(m.travel.per_diem, { enabled: true, qty_auto: true, qty: "", rate: 45 });
  m = B.renameSection(m, "Polish", "Breakroom");
  m = B.activateSection(m, "Epoxy", "option", { rules: [] });
  m.tabs.Epoxy.takeoff = [{ assembly_id: "e1", assembly_name: "Flake", measurement: 4000, unit: "SF" }];
  m.tabs.Epoxy.labor = [{ id: "installing", label: "Installing", guys: 4, days: 6, rate: 33 }];
  m = B.renameSection(m, "Epoxy", "Lab 1");
  const c = B.copySection(m, "Epoxy", {});
  m = B.renameSection(c.model, c.id, "Lab 2");
  m.tabs[c.id].labor = [{ id: "installing", label: "Installing", guys: 2, days: 3, rate: 33 }];
  return m;
}

/** What one sheet is charged for Lodging and Per Diem: the carrier the job's lines, an option its own crew's nights. */
function travelOf(m, tab) {
  const e = B.sectionOf(m, tab);
  if (B.travelCarrier(m) === tab) return B.travelCosts(m.travel, e.section.labor, B.travelOpts(m, tab));
  return B.optionTravelCosts(m.travel, e.section.labor, B.optionNights(m, tab));
}

function facts(child, tab) {
  const live = B.activeSections(child.model).map((e) => [e.tab, e.kind]);
  const sec = B.sectionOf(child.model, tab).section;
  return {
    base: B.baseOf(child.model), live: live, carrier: B.travelCarrier(child.model), wasCarrier: child.carrier,
    label: child.label, patch: child.patch,
    tabsLeft: Object.keys(child.model.tabs || {}), rootKind: B.sectionsOf(child.model)[0].kind,
    lodging: child.model.travel.lodging, perDiem: child.model.travel.per_diem,
    travel: travelOf(child.model, tab),
    driveRows: (sec.labor || []).filter((r) => r && r.id === "travel").map((r) => ({ guys: r.guys, days: r.days })),
    price: (tab === "Polish" ? B.polishBid(child.model, tab, CTX) : B.priceSection(child.model, tab, CTX)).total,
  };
}

const out = {};
function section(name, fn) {
  try { out[name] = fn(); } catch (e) { out[name] = { error: String((e && e.stack) || e) }; }
}

section("clean", () => {
  const m = deepFreeze(bid());
  const tabs = B.splitTabs(m);
  const before = {};
  tabs.forEach((t) => { before[t] = { travel: travelOf(m, t),
    price: (t === "Polish" ? B.polishBid(m, t, CTX) : B.priceSection(m, t, CTX)).total }; });
  const kids = {};
  tabs.forEach((t) => { kids[t] = facts(B.splitOut(m, t, { state: { tab_opts: { Epoxy: { is_option: true } } } }), t); });
  return { tabs: tabs, blockers: B.splitBlockers(m), before: before, kids: kids, untouched: JSON.stringify(m) === JSON.stringify(bid()) };
});

section("refusals", () => {
  const seal = B.activateSection(bid(), "Seal", "option", { rules: [] });
  const one = B.freshModel();
  const combined = B.pickBase(bid(), ["Polish", "Epoxy"], {}).model;
  const epoxyJob = (() => { const m = clone(bid()); m.tabs.Copy1.kind = "off"; return m; })();
  return {
    seal: { blockers: B.splitBlockers(seal), tabs: B.splitTabs(seal), threw: threw(() => B.splitOut(seal, "Polish", {})) },
    one: { blockers: B.splitBlockers(one), tabs: B.splitTabs(one), threw: threw(() => B.splitOut(one, "Polish", {})) },
    combined: { blockers: B.splitBlockers(combined), base: B.baseOf(combined).ids, threw: threw(() => B.splitOut(combined, "Polish", {})) },
    offSheet: { tabs: B.splitTabs(epoxyJob), threw: threw(() => B.splitOut(epoxyJob, "Copy1", {})) },
    unknown: threw(() => B.splitOut(bid(), "Nope", {})),
    notAModel: threw(() => B.splitOut(null, "Polish", {})),
  };
});

section("ownDrive", () => {
  // Lab 1 HAS a drive of its own: it keeps it, figures and all, and nobody else's.
  const m = bid();
  m.tabs.Epoxy.labor.push({ id: "travel", label: "Travel Labor", unit: "hours", guys: 4, days: 3, rate: 33, guys_auto: false, guys_typed: true });
  const k = B.splitOut(m, "Epoxy", {});
  return { driveRows: B.sectionOf(k.model, "Epoxy").section.labor.filter((r) => r.id === "travel").map((r) => ({ guys: r.guys, days: r.days })) };
});

process.stdout.write(JSON.stringify(out) + "\n");
