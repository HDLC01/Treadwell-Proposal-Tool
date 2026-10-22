"use strict";
/* A JOB WITH NO STREET IS MEASURED, AND AN UNKNOWN DISTANCE IS NEVER CALLED LOCAL (Hanz, 2026-10-22), run on the REAL estimate page: js/polish-estimate.js,
 * whole, booted the way polish-estimate-harness.js boots it, over the REAL js/bid-model.js. Every fact is read off the page after it ran.
 *
 * Hanz, testing staging: a v2 bid with City "Wichita", State "KS", County "Sedgwick County, KS" and no street said "This job is marked local, so no
 * travel is expected" and filled no travel. "based on the county and city and state it should have calculated it already". What the page does now:
 *
 *   newCity       a NEW bid with a city, a state and a county and no street asks on open, sends the county, and the answer (the city's centre) is kept
 *                 with its precision and worded as approximate.
 *   savedNone     a SAVED bid that never had a distance (nothing measured, nothing typed) asks on open too.
 *   savedTyped    a saved bid whose miles were TYPED is never measured again without the button.
 *   approxMoved   a saved APPROXIMATE figure (zip / city / county centre) whose address gained a street since is measured again on open; approxSame,
 *                 the same figure with the address unchanged, is not.
 *   streetMoved   a saved STREET figure whose address changed is left as it is with "the address changed" and the button (as before); legacyMoved is
 *                 one saved before precision existed, read as a street figure.
 *   unknown       no figure: the base sheet's Travel Labor card and an option's say "Distance unknown", never "marked local"; nearTyped, a measured
 *                 local job, still says local.
 *   reload        what newCity saved, reopened as jsonb hands it back: the precision and the words survive and nothing is asked.
 *   blank         no city, state, zip or county: nothing is asked and the words say what is enough.
 *   streetMissed  a street the geocoder could not find, measured to the city centre: the words say so.
 *
 * A section that throws reports `{ error }` instead of crashing. Usage: node distance-approx-harness.js <frontend-dir>  ->  one line of JSON
 */
const path = require("path");
const Module = require("module");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const B = require(path.join(ROOT, "js", "bid-model.js"));
const clone = (v) => JSON.parse(JSON.stringify(v));

function loadPrelude(file, exportNames) {
  const base = path.join(__dirname, file);
  const code = L.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in distance-approx-harness.js");
  const m = new Module(base, module);
  m.filename = base;
  m.paths = Module._nodeModulePaths(path.dirname(base));
  m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
  return m.exports;
}
const P = loadPrelude("polish-estimate-harness.js", ["build", "blob", "typeInto", "clickOn", "MODEL"]);

const CITY = { address: "", city: "Wichita", state: "KS", zip: "", county: "Sedgwick County, KS" };
const STREET = { address: "100 Main St", city: "Wichita", state: "KS", zip: "67202", county: "Sedgwick County, KS" };
const CITY_ANSWER = { ok: true, miles: 190.1, reason: "", office: "Olathe office", precision: "city", measured_to: "Wichita, KS", street_not_found: false };
const STREET_ANSWER = { ok: true, miles: 177.2, reason: "", office: "Olathe office", precision: "street", measured_to: "100 Main St, Wichita, KS 67202", street_not_found: false };
const MISSED_ANSWER = Object.assign({}, CITY_ANSWER, { street_not_found: true });
const NONE = { ok: false, miles: null, reason: "not_found" };
const keyOf = (a) => B.distanceKey(a.address, a.city, a.state, a.zip, a.county);

const flush = () => new Promise((r) => setImmediate(r));
const settle = async () => { for (let i = 0; i < 10; i++) await flush(); };

/** A saved Polish bid with stated labor (so it is not a new bid) and a Travel Labor line, at `address`, holding `distance` (or none). */
function savedBid(address, distance, extra) {
  const m = { version: 2, takeoff: clone(P.MODEL.takeoff),
    labor: [{ id: "polishing", label: "Polishing", guys: 4, days: 12, rate: 33 },
            { id: "travel", label: "Travel Labor", guys: "", days: "", rate: 33, unit: "hours", guys_auto: true }],
    conditions: Object.assign(clone(P.MODEL.conditions), { local: true }), contingency: 0, fees: 0, totals: {} };
  if (distance) m.distance = distance;
  return P.blob(Object.assign({ polish_estimate: Object.assign(m, extra || {}) }, address));
}
function newBid(address) {
  const b = P.blob(address);
  delete b.polish_estimate;
  return b;
}

async function open(blob, answer, extra) {
  const b = P.build(Object.assign({ blob: blob, distance: answer }, extra || {}));
  await b.api.init();
  await settle();
  b.api.go(1);
  await settle();
  return b;
}

const textOf = (b, sel) => { const el = b.doc.querySelector(sel); return el ? el.textContent : null; };
/** Text of a fragment: tags taken out until none is left, then the entities the page's esc() writes, `&amp;` last. */
const strip = (html) => {
  let s = String(html), prev;
  do { prev = s; s = s.replace(/<[^>]*>/g, ""); } while (s !== prev);
  return s.replace(/&#39;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&mdash;/g, "—").replace(/&amp;/g, "&");
};
/** What the page shows and holds about the distance. */
function facts(b) {
  const m = b.api.root();
  const panel = b.dom.get("panels").innerHTML;
  const inert = (panel.match(/<p class="inertline"[^>]*>([\s\S]*?)<\/p>/g) || []).map(strip);
  const tr = (m.labor || []).filter((r) => r && r.id === "travel")[0] || null;
  return {
    asked: (b.rec.distanceBodies || []).length,
    bodies: clone(b.rec.distanceBodies || []),
    distance: m.distance === undefined ? null : clone(m.distance),
    local: !!(m.conditions || {}).local,
    lodging: !!(m.travel && m.travel.lodging && m.travel.lodging.enabled),
    hours: tr ? tr.days : null,
    note: textOf(b, "[data-dist-note]"),
    status: textOf(b, "[data-dist-status]"),
    how: textOf(b, "[data-trv-how]"),
    inert: inert,
    saysLocal: panel.indexOf("marked local") !== -1,
    saved: b.store.blob.polish_estimate && b.store.blob.polish_estimate.distance ? clone(b.store.blob.polish_estimate.distance) : null,
  };
}

async function section(fn) {
  try { return await fn(); } catch (e) { return { error: String(e && e.stack || e) }; }
}

(async function main() {
  const out = {};
  let newCitySaved = null;

  out.newCity = await section(async () => {
    const b = await open(newBid(CITY), CITY_ANSWER);
    const f = facts(b);
    b.clock.fire();
    newCitySaved = clone(b.store.blob);
    f.saved = newCitySaved.polish_estimate && newCitySaved.polish_estimate.distance ? clone(newCitySaved.polish_estimate.distance) : null;
    f.key = keyOf(CITY);
    return f;
  });

  out.savedNone = await section(async () => {
    const b = await open(savedBid(CITY, null), CITY_ANSWER);
    const f = facts(b);
    b.clock.fire();
    f.saved = clone(b.store.blob.polish_estimate.distance || null);
    return f;
  });

  out.savedTyped = await section(async () => facts(await open(savedBid(CITY, { miles: 40, source: "typed", key: "" }), CITY_ANSWER)));

  out.approxMoved = await section(async () => {
    const approx = { miles: 190.1, source: "google", key: keyOf(CITY), precision: "city", measured_to: "Wichita, KS" };
    return facts(await open(savedBid(STREET, approx), STREET_ANSWER));
  });

  out.approxSame = await section(async () => {
    const approx = { miles: 190.1, source: "google", key: keyOf(CITY), precision: "city", measured_to: "Wichita, KS" };
    return facts(await open(savedBid(CITY, approx), STREET_ANSWER));
  });

  out.streetMoved = await section(async () => {
    const was = { miles: 177.2, source: "google", key: keyOf(STREET), precision: "street", measured_to: "100 Main St, Wichita, KS 67202" };
    return facts(await open(savedBid(Object.assign({}, STREET, { address: "200 Main St" }), was), CITY_ANSWER));
  });

  out.legacyMoved = await section(async () => {
    const was = { miles: 177.2, source: "google", key: B.distanceKey("100 Main St", "Wichita", "KS", "67202") };
    return facts(await open(savedBid(Object.assign({}, STREET, { address: "200 Main St" }), was), CITY_ANSWER));
  });

  out.legacySame = await section(async () => {
    // A street figure saved before the county was part of anything: its key is the four parts it always was, and it still matches.
    const was = { miles: 177.2, source: "google", key: "100 main st|wichita|ks|67202" };
    return facts(await open(savedBid(STREET, was), CITY_ANSWER));
  });

  out.unknown = await section(async () => {
    const option = { layout: "epoxy", kind: "option", profile: "epoxy@1",
      takeoff: [{ assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: 4000, unit: "SF" }],
      labor: [{ id: "installing", label: "Installing", guys: 3, days: 4, rate: 33 },
              { id: "travel", label: "Travel Labor", guys: "", days: "", rate: 33, unit: "hours", guys_auto: true }],
      contingency: 0, fees: 0, totals: {} };
    const b = await open(savedBid(CITY, null, { tabs: { Epoxy: option } }), NONE);
    const base = facts(b);
    b.api.show("Epoxy");
    b.api.go(1);
    await settle();
    return { base: base, option: facts(b) };
  });

  out.nearTyped = await section(async () => {
    const b = await open(savedBid(CITY, null), NONE);
    P.typeInto(b, "[data-dist-miles]", "30");
    await settle();
    return facts(b);
  });

  out.reload = await section(async () => {
    if (!newCitySaved) throw new Error("newCity did not run");
    return facts(await open(newCitySaved, STREET_ANSWER, { reloaded: true }));
  });

  out.blank = await section(async () => facts(await open(savedBid({ address: "", city: "", state: "", zip: "", county: "" }, null), CITY_ANSWER)));

  out.cityOnly = await section(async () => facts(await open(newBid({ address: "", city: "Wichita", state: "KS", zip: "", county: "" }), CITY_ANSWER)));

  out.countyOnly = await section(async () => facts(await open(newBid({ address: "", city: "", state: "", zip: "", county: "Sedgwick County, KS" }),
    { ok: true, miles: 186.4, reason: "", office: "Olathe office", precision: "county", measured_to: "Sedgwick County, KS", street_not_found: false })));

  out.streetMissed = await section(async () => facts(await open(newBid(Object.assign({}, STREET, { address: "1 Nowhere Ln", zip: "" })), MISSED_ANSWER)));

  process.stdout.write(JSON.stringify(out) + "\n");
})().catch((e) => { process.stderr.write(String(e && e.stack || e) + "\n"); process.exit(1); });
