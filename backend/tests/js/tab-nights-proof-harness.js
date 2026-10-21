"use strict";
/* THE NIGHTS EVERY TAB COUNTS, SET BESIDE WHAT KYLE'S WORKBOOK ANSWERED (round 6, part 3, M2).
 *
 *   node tab-nights-proof-harness.js <frontend dir> <oracle dir>   ->  one line of JSON: { cases: [...] }
 *
 * Kyle's tabs count the nights of lodging, and the same days of per diem, from the labor DOLLARS of the tab: Epoxy!B65 `=IF(B4="No",((D53-D52)/C47)/8)`,
 * Polish!B58 and the two Seal tabs `=IF(B4="No",((D45-D44)/C37)/8)`, Leveling!B61 `=IF(B4="No",((D49-D48)/C44)/8)` (a ten hour day, still divided by 8), and Per Diem
 * is the same figure on every one (`=B65`, `=B58`, `=B61`). The labor total is rounded up to the dollar before it is divided, the drive is taken off, and the rate it is
 * divided by is the FIRST crew row's, so a row paid another rate reads as extra days. The oracle recorded each tab's own answer for four crews (`lodging/one`, `template`,
 * `mixedRates`, `withTravel`; backend/tests/fixtures/oracle/<slug>.json), far (`local0`) and local (`local1`). Each is priced here AS A v2 SECTION OF THAT TAB WITH THE
 * NIGHTS LEFT TO FOLLOW: a new bid's Lodging and Per Diem (empty, off auto) and the model's own distance answer (190 miles far, 30 local: applyDistance), so a far job's
 * lines come on and follow the labor (followDistanceNights) and nothing is typed into them.
 *
 *   carrier   the tab as the base that carries the job's travel: Epoxy beside the Polish root that is off (an Epoxy job), and the Polish root itself (polish-rev3, the
 *             profile a new bid's Polish is priced by). Its lines are charged the JOB'S figure (travelOpts' `follow`, jobNights).
 *   option    the tab as an OPTION beside a Polish base (Epoxy, Seal, Seal (+Jnts), Leveling, and a Polish sheet under `tabs`, a Copy), which is priced apart and charges
 *             its own nights for its own labor (optionNights, optionTravelCosts) at the job's rates while the job's lines are on.
 *
 * The vector's crew rows are typed as the v2 rows a person types: guys, days and the row's own rate, a ten hour day on Leveling (the vector's `hoursPerDay`); the drive is
 * its own Travel Labor row in hours, typed, so the distance leaves it as it is. What comes back, for each: the nights the model counts, each line's dollars and the
 * section's travel and labor from the price the page computes (priceSection, or polishBid for a Polish section), each beside the workbook's, and what a head count
 * (guys x days) would have charged: the rule that was picked, pinned against the one that was not. (Leave the polish-legacy profile out: a saved bid's legacy Polish
 * counts people and is left as it is.)
 */
const fs = require("fs");
const path = require("path");

const FRONTEND = path.resolve(process.argv[2]);
const ORACLE = path.resolve(process.argv[3]);
const B = require(path.join(FRONTEND, "js", "bid-model.js"));

// [the tab, its oracle file, the roles it is priced in here]. Seal, Seal (+Jnts) and Leveling are options on a bid, never the base.
const TABS = [
  ["Epoxy", "epoxy", ["carrier", "option"]],
  ["Seal", "seal", ["option"]],
  ["Seal (+Jnts)", "seal-jnts", ["option"]],
  ["Leveling", "leveling", ["option"]],
  ["Polish", "polish", ["carrier", "option"]],
];
const REV3 = "polish-rev3@1";
const same = (a, b) => {
  const x = a === false ? 0 : a, y = b === false ? 0 : b;
  return (typeof x === "number" && typeof y === "number") ? (x === y || Math.abs(x - y) < 1e-9) : x === y;
};

/** The vector's crew as v2 labor rows (and its drive, typed, as a Travel Labor row in hours at the tab's own travel rate). */
function rowsOf(v, travelRate) {
  const rows = v.rows.map((r, n) => Object.assign({ id: "crew-" + n, label: "Crew " + (n + 1), guys: r.guys, days: r.days, rate: r.rate },
    v.hoursPerDay === 10 ? { hours_per_day: 10 } : {}));
  if (v.in.travelLabor) {
    rows.push({ id: "travel", label: "Travel Labor", guys: 1, days: Math.round((v.in.travelLabor / travelRate) * 1e6) / 1e6, rate: travelRate, unit: "hours",
      guys_typed: true, hours_typed: true });
  }
  return rows;
}

/** A Polish root, priced by polish-rev3 (a new bid's), with nothing on it but what `over` says. */
function rootOf(over) {
  return Object.assign({ version: 2, profile: REV3, takeoff: [], labor: [], conditions: {}, contingency: 0, fees: 0, totals: {} }, over || {});
}

/** The model for one case: `tab` in `role`, holding `rows`; a Polish section is stamped `polishStamp`. Answers [model, the section's tab id]. */
function modelFor(tab, role, rows, polishStamp) {
  if (tab === "Polish" && role === "carrier") return [rootOf({ profile: polishStamp, labor: rows }), B.ROOT_TAB];
  if (tab === "Polish") {
    // A Polish sheet under `tabs` is a Copy: it names its sheet and is priced exactly as the root is (polishBid), by its own stamp.
    const m = rootOf({ tabs: { Copy1: { layout: "polish", kind: "option", sheet: "Polish", label: "Polish copy", profile: polishStamp, takeoff: [], labor: rows,
      contingency: 0, fees: 0, totals: {}, seq: 1 } } });
    return [m, "Copy1"];
  }
  const root = rootOf(role === "carrier" ? { kind: "off" } : {});
  const m = B.activateSection(root, tab, role === "carrier" ? "base" : "option", {});
  m.tabs[tab].labor = rows;
  return [m, tab];
}

function priceOf(m, tab) {
  const ctx = { material: () => 0 };
  return tab === B.ROOT_TAB || (m.tabs && m.tabs[tab] && m.tabs[tab].layout === "polish") ? B.polishBid(m, tab, ctx) : B.priceSection(m, tab, ctx);
}

/** One vector `v` of the tab's oracle file, priced as a v2 section of `tab` in `role`: what the model charged, each figure beside the workbook's. */
function priceCase(tab, role, v, polishStamp) {
  const a = v.out.answers, o = v.out;
  // The drive's rate is the tab's own travel cell: Leveling!C48 is $33.66 like its crew, every other tab's $33 (Epoxy!C52, Polish!C44 and the two Seal tabs').
  const rows = rowsOf(v, tab === "Leveling" ? 33.66 : 33);
  const [m, id] = modelFor(tab, role, rows, polishStamp);
  m.conditions = Object.assign({}, m.conditions, { local: !!a.local, taxable: !!a.taxable, prevailing_wage: !!a.prevailingWage, remodel_tax: !!a.remodel });
  // A NEW bid's lines (empty, off auto) at the tab's own rates, then the model's own distance answer: far fills and follows, local leaves them off and empty.
  m.travel = B.travelCostsSeed(70, 45);
  ["lodging", "per_diem"].forEach((k) => { m.travel[k].qty_auto = false; m.travel[k].qty = ""; });
  B.applyDistance(m, { miles: a.local ? 30 : 190, source: "typed", key: "" });
  const sec = id === B.ROOT_TAB ? m : m.tabs[id];
  const line = m.travel.lodging;
  let nights, costs;
  if (role === "carrier") {
    const opts = B.travelOpts(m, id);
    nights = B.travelQty(line, sec.labor, opts);
    costs = B.travelCosts(m.travel, sec.labor, opts);
  } else {
    nights = B.optionNights(m, id);
    costs = B.optionTravelCosts(m.travel, sec.labor, nights);
  }
  const r = priceOf(m, id);
  const people = B.travelManDays(sec.labor);
  const wrong = [];
  if (r.labor !== v.in.labor) wrong.push("labor: workbook " + v.in.labor + ", v2 " + r.labor);
  if (a.local) {
    if (line.enabled) wrong.push("a local job has its Lodging on");
  } else {
    if (!(line.enabled && line.qty_auto === true && line.qty_follow === "labor")) wrong.push("the far job's nights are not following the labor");
    if (!same(nights, o.lodgingQty)) wrong.push("nights: workbook " + o.lodgingQty + ", v2 " + nights);
  }
  if (costs.lodging !== o.lodging) wrong.push("lodging: workbook " + o.lodging + ", v2 " + costs.lodging);
  if (costs.per_diem !== o.perDiem) wrong.push("per diem: workbook " + o.perDiem + ", v2 " + costs.per_diem);
  if (r.travel !== o.travel) wrong.push("travel: workbook " + o.travel + ", v2 " + r.travel);
  return { tab: tab, role: role, id: v.id, far: !a.local, wrong: wrong, nights: a.local ? null : nights, sheetNights: a.local ? null : o.lodgingQty,
    lodging: costs.lodging, perDiem: costs.per_diem, travel: r.travel, labor: r.labor, sheet: { lodging: o.lodging, perDiem: o.perDiem, travel: o.travel, labor: v.in.labor },
    // what counting people (guys x days) would have charged: the rule that was not picked
    people: { nights: people, lodging: a.local ? 0 : B.roundUp(people * 70), perDiem: a.local ? 0 : B.roundUp(people * 45) } };
}

const vectorsOf = (slug) => JSON.parse(fs.readFileSync(path.join(ORACLE, slug + ".json"), "utf8")).vectors.filter((v) => v.id.startsWith("lodging/"));
const cases = [];
TABS.forEach(([tab, slug, roles]) => {
  vectorsOf(slug).forEach((v) => { roles.forEach((role) => { cases.push(priceCase(tab, role, v, REV3)); }); });
});

// A SAVED bid's Polish, priced by polish-legacy (no profile key, or the legacy stamp), counts people as it always has: the far vectors of the Polish tab, as the root and as a
// Polish sheet that is an option, each with the nights it charged and the head count beside it.
const legacy = [];
vectorsOf("polish").filter((v) => !v.out.answers.local).forEach((v) => {
  ["carrier", "option"].forEach((role) => {
    const c = priceCase("Polish", role, v, "polish-legacy@1");
    legacy.push({ role: role, id: v.id, nights: c.nights, people: c.people.nights, sheetNights: c.sheetNights });
  });
});

console.log(JSON.stringify({ cases: cases, legacy: legacy }));
