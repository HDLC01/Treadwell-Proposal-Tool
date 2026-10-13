"use strict";
/* The county box fills itself from the job address, EXECUTED on both intake pages.
 *
 * WHAT RUNS. The REAL js/county-picker.js, js/county-autofill.js and js/address-lookup.js, against a
 * hand-built DOM, a hand-cranked clock and a fetch stub that answers Photon, the county reference
 * table (the REAL one, handed in by the test out of backend/reference_tax.py) and POST /api/county.
 * Nothing touches the network.
 *
 * THE PAGE WIRING IS LIFTED, NOT RE-WRITTEN. Each page mounts the autofill next to its address
 * lookup. This harness cuts that exact block out of js/index.js (the live intake) and out of
 * js/polish-intake.js (the v2 intake) and runs it, so a wiring that is deleted, renamed or pointed at
 * the wrong element throws here or changes an answer. Everything else on those pages is covered by
 * their own harnesses (beta-routing-harness.js, polish-intake-harness.js), which still boot the
 * pages with this module absent and prove the guard.
 *
 * Usage: node county-autofill-harness.js <frontend-dir> <county-table.json>   ->   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(process.argv[2]);
const TABLE = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), "utf8").replace(/\r\n/g, "\n");
const SRC = {
  picker: read("js/county-picker.js"), auto: read("js/county-autofill.js"),
  address: read("js/address-lookup.js"), index: read("js/index.js"), polish: read("js/polish-intake.js"),
};
const clone = (o) => JSON.parse(JSON.stringify(o));

// ── lifting the page wiring ──────────────────────────────────────────────────
function balanced(src, from, what) {
  let depth = 0;
  for (let j = from; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return j + 1;
  }
  throw new Error("unbalanced braces reading " + what);
}
function liftLive() {
  const start = SRC.index.indexOf("const countyAuto = (county && window.TWCountyAutofill)");
  if (start < 0) throw new Error("js/index.js no longer mounts the county autofill (const countyAuto)");
  const call = SRC.index.indexOf("window.TWAddress.mount({", start);
  if (call < 0) throw new Error("js/index.js no longer mounts the address lookup after the autofill");
  const end = balanced(SRC.index, SRC.index.indexOf("{", call), "TWAddress.mount");
  return SRC.index.slice(start, end) + ");";
}
function liftPolish() {
  const start = SRC.polish.indexOf("if (window.TWAddress && form) {");
  if (start < 0) throw new Error("js/polish-intake.js no longer mounts the address lookup");
  const end = balanced(SRC.polish, SRC.polish.indexOf("{", start), "the address block");
  return SRC.polish.slice(start, end);
}

// ── a DOM stub, only as much as the three modules touch ───────────────────────
function mkEl(id) {
  const classes = new Set();
  const e = {
    id, value: "", hidden: false, textContent: "", html: "", rows: [], listeners: {},
    classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c), contains: (c) => classes.has(c) },
    addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
    dispatchEvent() { return true; },
    contains() { return false; },
    closest() { return null; },
    querySelectorAll() { return this.rows; },
    set innerHTML(h) {
      this.html = h;
      this.rows = [];
      const n = (String(h).match(/class="addr-row"/g) || []).length;
      for (let i = 0; i < n; i++) {
        this.rows.push({ dataset: { idx: String(i) }, listeners: {},
          addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); } });
      }
    },
    get innerHTML() { return this.html; },
  };
  return e;
}
function fire(el, type) { (el.listeners[type] || []).forEach((f) => f({ target: el, preventDefault() {} })); }

function fakeClock() {
  let due = [];
  return {
    setTimeout: (f) => { due.push({ f, live: true }); return due.length; },
    clearTimeout: (id) => { if (due[id - 1]) due[id - 1].live = false; },
    run: () => { const now = due; due = []; now.forEach((t) => { if (t.live) t.f(); }); },
    armed: () => due.filter((t) => t.live).length,
  };
}
async function settle() {
  for (let i = 0; i < 6; i++) { await new Promise((r) => setImmediate(r)); }
}
function gate() {
  let release; const p = new Promise((r) => { release = r; });
  return { p, release };
}

const FEAT = (o) => ({ properties: Object.assign({
  housenumber: "455", street: "N Main St", city: "Wichita", county: "Sedgwick County",
  state: "Kansas", postcode: "67202", countrycode: "US" }, o || {}) });
const ANS = (county, state, place, sure) => ({ ok: true, county, state: state || "KS", fips: "0", place: place || "",
                                                place_sure: sure !== false, reason: "", address: "x" });

/** One page, mounted the way that page mounts it. page: "live" | "polish". */
async function world(page, opts) {
  opts = opts || {};
  const nodes = {};
  const get = (id) => nodes[id] || (nodes[id] = mkEl(id));
  const doc = { getElementById: get, listeners: {}, addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); } };
  const clock = fakeClock();
  const w = { feats: [FEAT()], census: async () => ANS("Sedgwick County", "KS", "Wichita") };
  const rec = { lookups: [], saves: [], refFetches: 0, photon: 0, errors: [] };
  const win = {};
  win.TW = {
    resolveApiBase: () => "",
    authHeaders: (h) => Object.assign({ Authorization: "Bearer t" }, h || {}),
  };
  const listGate = opts.holdList ? gate() : null;
  const fetchStub = async function (url, init) {
    url = String(url);
    if (url.indexOf("photon.komoot.io") >= 0) {
      rec.photon++;
      return { json: async () => ({ features: clone(w.feats) }) };
    }
    if (url.indexOf("/api/reference/counties") >= 0) {
      rec.refFetches++;
      if (listGate) await listGate.p;
      return { json: async () => ({ counties: clone(TABLE), ks_state_rate: 0.065 }) };
    }
    if (url.indexOf("/api/county") >= 0) {
      if (!init || init.method !== "POST") throw new Error("/api/county must be a POST");
      const body = JSON.parse(init.body);
      rec.lookups.push({ body, headers: init.headers });
      const r = await w.census(body, rec.lookups.length);
      if (r === "badjson") return { json: async () => { throw new Error("not json"); } };
      return { json: async () => r };
    }
    throw new Error("unexpected fetch " + url);
  };
  const run = (src) => new Function("document", "window", "fetch", "setTimeout", "clearTimeout", src)(
    doc, win, fetchStub, clock.setTimeout, clock.clearTimeout);
  run(SRC.picker);
  run(SRC.auto);
  run(SRC.address);

  // The county control, mounted as both pages mount it: the host owns saving, so onChange records
  // the four keys a save would write.
  let county = null;
  county = win.TWCounty.mount({
    remodelTaxOn: () => true,
    onChange: () => rec.saves.push(clone(county.keys())),
  });
  county.wire(page === "live");
  // deferLoad: the live intake calls load() only AFTER its condition defaults arrive, so the autofill
  // is mounted for a moment before any list has been requested. The test calls api.load() itself.
  const loading = opts.deferLoad ? null : county.load();
  if (!opts.holdList && loading) await loading;

  const addr = get("address-input"), city = get("city-input"), st = get("state-input"), zip = get("zip-input");
  get("address-results"); get("business-results"); get("business-input");
  if (opts.openWith) county.hydrate(opts.openWith);     // a saved draft is opened BEFORE the address mounts
  if (opts.fields) { addr.value = opts.fields[0]; city.value = opts.fields[1]; st.value = opts.fields[2]; zip.value = opts.fields[3]; }

  // THE PAGE'S OWN WIRING.
  if (page === "live") {
    new Function("document", "window", "county", liftLive())(doc, win, county);
  } else {
    new Function("document", "window", "county", "form", "$", liftPolish())(
      doc, win, county, {}, (id) => get(id));
  }

  const api = {
    county, rec, w, nodes, clock, listGate,
    keys: () => clone(county.keys()),
    shown: () => ({ input: get("county-input").value, note: get("county-note").textContent,
                    auto: county.isAuto(), has: county.hasPick() }),
    async load() { const p = county.load(); await p; await settle(); },
    /** The estimator typing in the County search box itself (no pick made). */
    typeInCountyBox(text) { get("county-input").value = text; county.onInput(); },
    resultsOpen: () => get("county-results").hidden === false,
    /** Type a suggestion and click its row: the real path, debounce and all. */
    async pick(feature) {
      w.feats = [feature];
      addr.value = [feature.properties.housenumber, feature.properties.street].join(" ");
      fire(addr, "input");
      clock.run();                      // the 300 ms debounce
      await settle();                   // Photon answers, the rows render
      const row = get("address-results").rows[0];
      if (!row) throw new Error("no suggestion row rendered");
      row.listeners.click[0]({ target: row });
      await settle();
    },
    /** Type an address by hand and leave the box. */
    async type(street, c, s, z) {
      addr.value = street; city.value = c; st.value = s; zip.value = z;
      fire(addr, "change");
      clock.run();
      await settle();
    },
    handPick(name, stateAbbr) {
      const row = TABLE.filter((r) => r.name === name && r.state === stateAbbr)[0];
      if (!row) throw new Error("no such row " + name);
      county.choose(row);
    },
  };
  return api;
}

const out = {};

async function scenarios(page) {
  const o = {};

  // 1. An empty box, a picked address: the Photon county shows at once, the Census answer confirms.
  {
    const h = gate();
    const wd = await world(page);
    wd.w.census = async () => { await h.p; return ANS("Sedgwick County", "KS", "Wichita"); };
    await wd.pick(FEAT());
    const guess = Object.assign({ keys: wd.keys(), lookups: wd.rec.lookups.length }, wd.shown());
    h.release();
    await settle();
    o.pickFills = { guess, final: Object.assign({ keys: wd.keys() }, wd.shown()),
                    lookups: wd.rec.lookups.length, body: wd.rec.lookups[0] && wd.rec.lookups[0].body,
                    auth: wd.rec.lookups[0] && wd.rec.lookups[0].headers && wd.rec.lookups[0].headers.Authorization,
                    saves: wd.rec.saves.length };
  }

  // 2. The Census answer wins over Photon's guess.
  {
    const wd = await world(page);
    wd.w.census = async () => ANS("Wyandotte County", "KS", "");
    await wd.pick(FEAT({ county: "Johnson County", city: "Springfield" }));
    o.censusReplacesGuess = Object.assign({ keys: wd.keys() }, wd.shown());
  }

  // 3. A city the list has a verified row for is preferred; a city row of ANOTHER county is not.
  {
    const wd = await world(page);
    wd.w.census = async () => ANS("Johnson County", "KS", "Olathe");
    await wd.pick(FEAT({ city: "Olathe", county: "Johnson County" }));
    o.cityRow = Object.assign({ keys: wd.keys() }, wd.shown());
    const wd2 = await world(page);
    wd2.w.census = async () => ANS("Shawnee County", "KS", "Shawnee");
    await wd2.pick(FEAT({ city: "Shawnee", county: "Shawnee County" }));
    o.cityRowOfAnotherCounty = Object.assign({ keys: wd2.keys() }, wd2.shown());
  }

  // 4. A hand-picked county is never replaced, and no lookup is even made.
  {
    const wd = await world(page);
    wd.handPick("Jackson", "MO");
    wd.rec.saves.length = 0;
    await wd.pick(FEAT());
    await wd.type("1 Main St", "Wichita", "KS", "67202");
    o.handPickKept = Object.assign({ keys: wd.keys(), lookups: wd.rec.lookups.length,
                                      saves: wd.rec.saves.length }, wd.shown());
  }

  // 5. Changing the address re-fills a FILLED county only; a hand pick after that is theirs.
  {
    const wd = await world(page);
    wd.w.census = async () => ANS("Sedgwick County", "KS", "Wichita");
    await wd.pick(FEAT());
    const first = wd.keys().county;
    wd.w.census = async () => ANS("Wyandotte County", "KS", "Kansas City");
    await wd.type("701 N 7th St", "Kansas City", "KS", "66101");
    const second = Object.assign({ keys: wd.keys() }, wd.shown());
    wd.handPick("Jackson", "MO");
    const lookupsBefore = wd.rec.lookups.length;
    wd.w.census = async () => ANS("Sedgwick County", "KS", "Wichita");
    await wd.type("9 Elm St", "Wichita", "KS", "67202");
    o.addressChange = { first, second, afterHandPick: Object.assign({ keys: wd.keys() }, wd.shown()),
                        lookupsBefore, lookupsAfter: wd.rec.lookups.length };
  }

  // 6. A county the list has no row for leaves the box empty, and clears a stale fill.
  {
    const wd = await world(page);
    wd.w.census = async () => ANS("Cherokee County", "KS", "");
    await wd.pick(FEAT({ county: "Cherokee County", city: "Baxter Springs" }));
    const empty = Object.assign({ keys: wd.keys(), saves: wd.rec.saves.length }, wd.shown());
    const wd2 = await world(page);
    wd2.w.census = async () => ANS("Sedgwick County", "KS", "Wichita");
    await wd2.pick(FEAT());
    wd2.w.census = async () => ANS("Cherokee County", "KS", "");
    await wd2.type("5 Oak St", "Baxter Springs", "KS", "66713");
    o.notInList = { empty, staleFillCleared: Object.assign({ keys: wd2.keys() }, wd2.shown()) };
  }

  // 7. A saved draft opens unchanged: no field event fires, so no lookup runs and nothing is saved.
  {
    const saved = { county: "Wyandotte County, KS", county_tax_rate: 0.01, county_remodel_rate: 0.075,
                    county_notes: "KCK" };
    const wd = await world(page, { openWith: saved, fields: ["455 N Main St", "Wichita", "KS", "67202"] });
    await settle(); wd.clock.run(); await settle();
    const opened = Object.assign({ keys: wd.keys(), lookups: wd.rec.lookups.length,
                                    saves: wd.rec.saves.length, timers: wd.clock.armed() }, wd.shown());
    wd.w.census = async () => ANS("Sedgwick County", "KS", "Wichita");
    await wd.pick(FEAT());
    const afterPick = Object.assign({ keys: wd.keys(), lookups: wd.rec.lookups.length }, wd.shown());
    // And a draft with NO county and an address already in the boxes: still no lookup on open.
    const wd2 = await world(page, { fields: ["455 N Main St", "Wichita", "KS", "67202"] });
    await settle(); wd2.clock.run(); await settle();
    o.savedDraft = { opened, afterPick, noCountyOpened: { keys: wd2.keys(), lookups: wd2.rec.lookups.length } };
  }

  // 8. Any failure changes nothing, throws nothing, and a later change retries the same address.
  {
    const wd = await world(page);
    const rejections = [];
    const onRej = (e) => rejections.push(String(e));
    process.on("unhandledRejection", onRej);
    const modes = ["throw", "badjson", "notok", "emptyobj"];
    const seen = {};
    for (const mode of modes) {
      const w2 = await world(page);
      w2.w.census = async () => {
        if (mode === "throw") throw new Error("down");
        if (mode === "badjson") return "badjson";
        if (mode === "notok") return { ok: false, reason: "error", county: "", place: "" };
        return {};
      };
      await w2.type("455 N Main St", "Wichita", "KS", "67202");
      seen[mode] = { keys: w2.keys(), has: w2.county.hasPick(), lookups: w2.rec.lookups.length };
      // The same address, committed again: asked again because the first answer was no answer.
      w2.w.census = async () => ANS("Sedgwick County", "KS", "Wichita");
      fire(w2.nodes["address-input"], "change"); w2.clock.run(); await settle();
      seen[mode].afterRetry = { county: w2.keys().county, lookups: w2.rec.lookups.length };
    }
    await settle();
    process.removeListener("unhandledRejection", onRej);
    o.failures = { seen, unhandled: rejections, unused: wd.keys().county };
  }

  // 9. A slow answer for an address the estimator has already left is dropped.
  {
    const slow = gate();
    const wd = await world(page);
    wd.w.census = async (body, n) => {
      if (n === 1) { await slow.p; return ANS("Sedgwick County", "KS", "Wichita"); }
      return ANS("Wyandotte County", "KS", "");
    };
    await wd.type("1 First St", "Wichita", "KS", "67202");           // answer 1 is held
    await wd.type("2 Second St", "Kansas City", "KS", "66101");      // answer 2 comes at once
    const before = wd.keys().county;
    slow.release(); await settle();
    o.staleAnswer = { before, after: wd.keys().county, lookups: wd.rec.lookups.length };
  }

  // 10. A typed address: one lookup after the pause, none for a thin one, none for a repeat.
  {
    const wd = await world(page);
    await wd.type("455 N Main St", "", "", "");                      // a street and nothing to place it
    const thin = wd.rec.lookups.length;
    await wd.type("455 N Main St", "Wichita", "KS", "");
    const once = wd.rec.lookups.length;
    fire(wd.nodes["address-input"], "change"); wd.clock.run(); await settle();
    const repeat = wd.rec.lookups.length;
    o.typed = { thin, once, repeat, county: wd.keys().county, photon: wd.rec.photon,
                body: wd.rec.lookups[0] && wd.rec.lookups[0].body };
  }

  // 11. The list is still loading when the address is picked: the fill waits for it.
  {
    const wd = await world(page, { holdList: true });
    await wd.pick(FEAT());
    const early = wd.keys().county;
    wd.listGate.release(); await settle();
    o.listNotLoaded = { early, late: wd.keys().county, lookups: wd.rec.lookups.length };
    // The same with a TYPED address, which has no Photon guess: only the Census answer can fill it.
    const wt = await world(page, { holdList: true });
    await wt.type("455 N Main St", "Wichita", "KS", "67202");
    const earlyTyped = wt.keys().county;
    wt.listGate.release(); await settle();
    o.listNotLoaded.typed = { early: earlyTyped, late: wt.keys().county, lookups: wt.rec.lookups.length };
  }

  // 12. Clear is the estimator's too: after Clear, the same address is not refilled by a repeat.
  {
    const wd = await world(page);
    await wd.pick(FEAT());
    wd.county.clear();
    const cleared = wd.keys().county;
    fire(wd.nodes["address-input"], "change"); wd.clock.run(); await settle();
    o.cleared = { cleared, afterRepeat: wd.keys().county, lookups: wd.rec.lookups.length };
  }
  // 14. The Census matched the street in another zip and named a city the job is not in
  // (place_sure false): the county stands, and the city comes from the box the estimator typed.
  {
    const wd = await world(page);
    wd.w.census = async () => ANS("Wyandotte County", "KS", "Edwardsville", false);
    await wd.type("701 N 7th St", "Kansas City", "KS", "66101");
    const unsure = Object.assign({ keys: wd.keys() }, wd.shown());
    const wd2 = await world(page);
    wd2.w.census = async () => ANS("Wyandotte County", "KS", "Edwardsville", true);
    await wd2.type("701 N 7th St", "Kansas City", "KS", "66101");
    o.placeUnsure = { unsure, sure: Object.assign({ keys: wd2.keys() }, wd2.shown()) };
  }

  // 13. The estimator picks a county by hand while the Census answer is still on its way: theirs wins.
  {
    const h = gate();
    const wd = await world(page);
    wd.w.census = async () => { await h.p; return ANS("Sedgwick County", "KS", "Wichita"); };
    await wd.pick(FEAT());
    wd.handPick("Jackson", "MO");
    h.release(); await settle();
    o.handPickDuringLookup = Object.assign({ keys: wd.keys() }, wd.shown());
  }

  // 15. NO ANSWER for a NEW address (not found, down): the county filled for the OLD address must go,
  // because the note under it still says "Filled from the address". A same-address guess must stay.
  {
    const noAnswer = [
      { mode: "not_found", census: async () => ({ ok: false, reason: "not_found", county: "", place: "" }) },
      { mode: "down", census: async () => { throw new Error("down"); } },
      { mode: "empty", census: async () => ({}) },
    ];
    o.staleAfterNoAnswer = [];
    for (const m of noAnswer) {
      const wd = await world(page);
      await wd.pick(FEAT());
      const before = wd.keys().county;
      wd.w.census = m.census;
      await wd.type("1 New Subdivision Ct", "Kansas City", "MO", "64150");
      o.staleAfterNoAnswer.push(Object.assign({ mode: m.mode, before, keys: wd.keys() }, wd.shown()));
    }
    // The street emptied: the address is no longer one, and the fill that belonged to it goes. Typing
    // the same street back is looked up again (the dedupe key was dropped with the fill).
    const ws = await world(page);
    await ws.pick(FEAT());
    await ws.type("", "Wichita", "KS", "67202");
    const emptied = Object.assign({ keys: ws.keys() }, ws.shown());
    await ws.type("455 N Main St", "Wichita", "KS", "67202");
    o.streetCleared = { emptied, back: Object.assign({ keys: ws.keys(), lookups: ws.rec.lookups.length }, ws.shown()) };
    // A picked address whose Census answer never comes keeps Photon's guess: it is for THIS address.
    const wg = await world(page);
    wg.w.census = async () => ({ ok: false, reason: "error", county: "", place: "" });
    await wg.pick(FEAT());
    o.guessSurvivesNoAnswer = Object.assign({ keys: wg.keys(), lookups: wg.rec.lookups.length }, wg.shown());
  }

  // 16. The Census can match a street with no zip typed into a different incorporated place
  // (real, 2026-10-13: 701 N 7th St, Kansas City KS, no zip -> Edwardsville, place_sure true). The city the
  // estimator typed has a verified row in that county, so with nothing to confirm the Census place the
  // typed city wins. With a zip typed the Census place stands (see placeUnsure).
  {
    const wd = await world(page);
    wd.w.census = async () => ANS("Wyandotte County", "KS", "Edwardsville", true);
    await wd.type("701 N 7th St", "Kansas City", "KS", "");
    const noZip = Object.assign({ keys: wd.keys() }, wd.shown());
    const wp = await world(page);
    wp.w.census = async () => ANS("Wyandotte County", "KS", "Edwardsville", true);
    await wp.pick(FEAT({ city: "Kansas City", county: "Wyandotte County", postcode: "" }));
    const photon = Object.assign({ keys: wp.keys() }, wp.shown());
    // A typed city with NO row never beats the Census place: Shawnee Mission is a postal name.
    const wm = await world(page);
    wm.w.census = async () => ANS("Johnson County", "KS", "Overland Park", true);
    await wm.type("7000 W 80th St", "Shawnee Mission", "KS", "");
    const postalName = Object.assign({ keys: wm.keys() }, wm.shown());
    // A typed city whose row belongs to ANOTHER county never beats the Census county either.
    const wo = await world(page);
    wo.w.census = async () => ANS("Shawnee County", "KS", "", true);
    await wo.type("1 Main St", "Shawnee", "KS", "");
    const otherCounty = Object.assign({ keys: wo.keys() }, wo.shown());
    o.typedCityWins = { noZip, photon, postalName, otherCounty };
  }

  // 17. A city the list has no row for: the county FLOOR rate is filled, and the note says so.
  {
    const wd = await world(page);
    wd.w.census = async () => ANS("Johnson County", "KS", "Gardner", true);
    await wd.type("120 E Main St", "Gardner", "KS", "66030");
    const gardner = Object.assign({ keys: wd.keys() }, wd.shown());
    const wb = await world(page);
    wb.w.census = async () => ANS("Wyandotte County", "KS", "Bonner Springs", true);
    await wb.type("1 Front St", "Bonner Springs", "KS", "66012");
    const bonner = Object.assign({ keys: wb.keys() }, wb.shown());
    // A city that HAS a row, an unincorporated address and a hand pick carry no such sentence.
    const wo = await world(page);
    wo.w.census = async () => ANS("Johnson County", "KS", "Olathe", true);
    await wo.type("1 Main St", "Olathe", "KS", "66061");
    const withRow = Object.assign({ keys: wo.keys() }, wo.shown());
    const wu = await world(page);
    wu.w.census = async () => ANS("Johnson County", "KS", "", true);
    await wu.type("1 Country Rd", "Gardner", "KS", "66030");
    const unincorporated = Object.assign({ keys: wu.keys() }, wu.shown());
    const wh = await world(page);
    wh.handPick("Johnson", "KS");
    const hand = wh.shown();
    // Photon names the county but no city; the Census then names the place: the sentence arrives with it.
    const wl = await world(page);
    wl.w.census = async () => ANS("Johnson County", "KS", "Gardner", true);
    await wl.pick(FEAT({ city: "", county: "Johnson County", postcode: "66030" }));
    const lateCity = Object.assign({ keys: wl.keys() }, wl.shown());
    // Missouri labor is exempt, so a city sentence about a tax that is not charged would only confuse.
    const wm = await world(page);
    wm.w.census = async () => ANS("Jackson County", "MO", "Kansas City", true);
    await wm.type("1 Grand Blvd", "Kansas City", "MO", "64108");
    const missouri = Object.assign({ keys: wm.keys() }, wm.shown());
    // Wichita levies no city tax of its own: the Sedgwick row says the county rate is right there
    // (city_ok), so no warning. Another Sedgwick city is warned about.
    const ww = await world(page);
    ww.w.census = async () => ANS("Sedgwick County", "KS", "Wichita", true);
    await ww.type("455 N Main St", "Wichita", "KS", "67202");
    const wichita = Object.assign({ keys: ww.keys() }, ww.shown());
    const wy = await world(page);
    wy.w.census = async () => ANS("Sedgwick County", "KS", "Derby", true);
    await wy.type("1 Madison Ave", "Derby", "KS", "67037");
    const derby = Object.assign({ keys: wy.keys() }, wy.shown());
    o.cityNotOnList = { gardner, bonner, withRow, unincorporated, hand, lateCity, missouri, wichita, derby };
  }

  // 18. The state guards, with real Missouri/Kansas twins. Both states have a Johnson County.
  {
    const wk = await world(page);
    wk.w.census = async () => ANS("Johnson County", "KS", "", true);
    await wk.type("1 Country Rd", "Spring Hill", "KS", "66083");
    const wm = await world(page);
    wm.w.census = async () => ANS("Johnson County", "MO", "Warrensburg", true);
    await wm.type("1 Main St", "Warrensburg", "MO", "64093");
    // Photon names a city in Missouri and no county, and the Census never answers: Kansas City, KS is
    // a different place, so nothing is filled.
    const wc = await world(page);
    wc.w.census = async () => ({ ok: false, reason: "error", county: "", place: "" });
    await wc.pick(FEAT({ city: "Kansas City", county: "", state: "Missouri", postcode: "64108" }));
    o.stateGuards = { johnsonKS: Object.assign({ keys: wk.keys() }, wk.shown()),
                      johnsonMO: Object.assign({ keys: wm.keys() }, wm.shown()),
                      photonMoCityNoCounty: Object.assign({ keys: wc.keys() }, wc.shown()) };
  }

  // 19. The list has not been requested yet (the live intake calls load() after its defaults arrive).
  // The answer that lands in that window cannot be filled; the SAME address is looked up again later.
  {
    const wd = await world(page, { deferLoad: true });
    await wd.type("455 N Main St", "Wichita", "KS", "67202");
    const before = wd.keys().county;
    await wd.load();
    fire(wd.nodes["address-input"], "change"); wd.clock.run(); await settle();
    o.beforeLoadCalled = { before, after: wd.keys().county, lookups: wd.rec.lookups.length };
  }

  // 20. Clear is theirs: correcting the address afterwards does not bring the county back.
  {
    const wd = await world(page);
    wd.handPick("Jackson", "MO");
    wd.county.clear();
    wd.rec.lookups.length = 0;
    await wd.type("455 N Main St", "Wichita", "KS", "67202");
    const afterHandClear = Object.assign({ keys: wd.keys(), lookups: wd.rec.lookups.length }, wd.shown());
    const wf = await world(page);
    await wf.pick(FEAT());
    wf.county.clear();                              // the estimator says this fill is wrong
    await wf.type("455 N Main St", "Wichita", "KS", "67203");
    const afterClearedFill = Object.assign({ keys: wf.keys(), lookups: wf.rec.lookups.length }, wf.shown());
    // A fill the PAGE removed (a new address with no county) is not a clear by hand: the next address fills.
    const wp = await world(page);
    await wp.pick(FEAT());
    wp.w.census = async () => ANS("Cherokee County", "KS", "");
    await wp.type("5 Oak St", "Baxter Springs", "KS", "66713");      // no row: the Sedgwick fill is removed
    const removedByPage = wp.county.hasPick();
    wp.w.census = async () => ANS("Sedgwick County", "KS", "Wichita");
    await wp.type("455 N Main St", "Wichita", "KS", "67202");
    o.clearIsTheirs = { afterHandClear, afterClearedFill,
                        pageRemovalIsNot: Object.assign({ removedByPage, keys: wp.keys() }, wp.shown()) };
  }

  // 21. The estimator is typing in the County search box when the answer lands: their text stays, the list
  // stays open, and once they are done the same address is looked up again.
  {
    const h = gate();
    const wd = await world(page);
    wd.w.census = async () => { await h.p; return ANS("Sedgwick County", "KS", "Wichita"); };
    await wd.type("455 N Main St", "Wichita", "KS", "67202");
    wd.typeInCountyBox("john");
    const typing = { input: wd.nodes["county-input"].value, open: wd.resultsOpen() };
    h.release(); await settle();
    const during = Object.assign({ keys: wd.keys(), open: wd.resultsOpen() }, wd.shown());
    wd.county.close();                              // Escape: the box goes back to what is saved (empty)
    wd.w.census = async () => ANS("Sedgwick County", "KS", "Wichita");
    fire(wd.nodes["address-input"], "change"); wd.clock.run(); await settle();
    o.typingInCountyBox = { typing, during, afterEscape: Object.assign({ keys: wd.keys(),
                            lookups: wd.rec.lookups.length }, wd.shown()) };
  }

  // 22. The address moved on while the list was still loading: no answer for the old one may land.
  {
    // (a) a typed address, answered, then waiting for the list; a second address has no answer.
    const wa = await world(page, { holdList: true });
    await wa.type("455 N Main St", "Wichita", "KS", "67202");
    wa.w.census = async () => ({ ok: false, reason: "not_found", county: "", place: "" });
    await wa.type("1 New Subdivision Ct", "Kansas City", "MO", "64150");
    wa.listGate.release(); await settle();
    // (b) a picked address (Photon's guess waits for the list), no answer for it, then a second address.
    const wb = await world(page, { holdList: true });
    wb.w.census = async () => ({ ok: false, reason: "error", county: "", place: "" });
    await wb.pick(FEAT());
    await wb.type("1 New Subdivision Ct", "Kansas City", "MO", "64150");
    wb.listGate.release(); await settle();
    // (c) the same pick left alone: the guess waits for the list and then lands.
    const wc = await world(page, { holdList: true });
    wc.w.census = async () => ({ ok: false, reason: "error", county: "", place: "" });
    await wc.pick(FEAT());
    wc.listGate.release(); await settle();
    // The draft is saved on every fill AND every removal, so "never written" is the strong claim: the
    // next lookup would remove a stale guess again, but the wrong county would already have been saved.
    o.movedOnWhileLoading = { typed: wa.keys().county, guess: wb.keys().county, guessAlone: wc.keys().county,
                              typedSaves: wa.rec.saves.length, guessSaves: wb.rec.saves.length };
  }
  return o;
}

(async () => {
  out.live = await scenarios("live");
  out.polish = await scenarios("polish");
  out.autoNote = "Filled from the address. Change it if it's wrong.";
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e && e.stack || e); process.exit(1); });
