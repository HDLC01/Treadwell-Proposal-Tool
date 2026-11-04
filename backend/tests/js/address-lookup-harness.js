/* js/address-lookup.js, EXECUTED: the shared address / business lookup both intake pages mount.
 *
 * The real module runs against a hand-built DOM (listeners, a classList, dispatchEvent) and a stub
 * fetch that answers with Photon-shaped features. Nothing touches the network.
 *
 * Usage: node address-lookup-harness.js <frontend-dir>   ->   one line of JSON
 */
const fs = require("fs");
const path = require("path");
const SRC = fs.readFileSync(path.join(process.argv[2], "js", "address-lookup.js"), "utf8");

function el(id) {
  const classes = new Set();
  const e = {
    id, value: "", html: "", listeners: {}, events: [], children: [],
    classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c),
                 contains: (c) => classes.has(c) },
    addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
    dispatchEvent(ev) { this.events.push(ev.type + ":" + (ev.bubbles ? "bubbles" : "")); return true; },
    contains(x) { return x === this; },
    querySelectorAll() { return this.rows || []; },
    set innerHTML(h) {
      this.html = h;
      // one stub row per addr-row so a click can be driven by index. Its data-idx is READ FROM THE
      // MARKUP, as the browser's dataset would be, so a row drawn with the wrong index is caught.
      this.rows = [];
      const idxs = (h.match(/class="addr-row"( data-idx="[^"]*")?/g) || [])
        .map((m) => { const x = /data-idx="([^"]*)"/.exec(m); return x ? x[1] : undefined; });
      for (let i = 0; i < idxs.length; i++) {
        const row = { dataset: { idx: idxs[i] }, listeners: {},
                      addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); } };
        this.rows.push(row);
      }
    },
    get innerHTML() { return this.html; },
    isOpen: () => classes.has("open"),
  };
  return e;
}
const FEATS = [
  { properties: { name: "Acme", housenumber: "123", street: "W 5th St", city: "Olathe",
                  state: "Kansas", postcode: "66061", countrycode: "US" } },
  { properties: { name: "Acme", housenumber: "123", street: "W 5th St", city: "Olathe",
                  state: "Kansas", postcode: "66061", countrycode: "US" } },     // duplicate
  { properties: { name: "Abroad", street: "Rue X", city: "Paris", state: "Ile", countrycode: "FR" } },
];

// ── recorded Photon features (live, 2026-11-05) ─────────────────────────────────────────────────
const F = (props, lon, lat) => ({ properties: props, geometry: { coordinates: [lon, lat] } });
const US = (o) => Object.assign({ countrycode: "US" }, o);
const PH = {
  // the OLD question's answer for "8200 Nieman" (downtown KC, limit 6, no bbox)
  foreign: [
    F({ osm_key: "highway", osm_value: "residential", name: "Rue Normandie-Niemen", city: "Montauban",
        county: "Tarn-et-Garonne", state: "Occitania", postcode: "82000", countrycode: "FR" }, 1.38146, 44.01663),
    F({ osm_key: "highway", osm_value: "unclassified", name: "Niemennokantie", city: "Joensuu",
        state: "North Karelia", postcode: "82200", countrycode: "FI" }, 29.86392, 62.43181),
  ],
  nieman: [
    F(US({ osm_key: "highway", osm_value: "tertiary", name: "Nieman Road", city: "Overland Park", county: "Johnson",
           state: "Kansas", postcode: "66210" }), -94.7139, 38.91769),
    F(US({ osm_key: "highway", osm_value: "tertiary", name: "Nieman Road", city: "Overland Park", county: "Johnson",
           state: "Kansas", postcode: "66213" }), -94.71442, 38.89166),
    F(US({ osm_key: "highway", osm_value: "unclassified", name: "Nieman Road", city: "Overland Park", county: "Johnson",
           state: "Kansas", postcode: "66221" }), -94.71638, 38.88287),
  ],
  // "N Oak Street": two bus stops among the streets, and Photon's own order is not by distance
  oak: [
    F(US({ osm_key: "highway", osm_value: "residential", name: "Oak Street", city: "Kansas City", county: "Jackson County",
           state: "Missouri", postcode: "64111" }), -94.58031, 39.06569),
    F(US({ osm_key: "highway", osm_value: "residential", name: "North Oak Street", city: "Gardner", county: "Johnson",
           state: "Kansas", postcode: "66030" }), -94.93249, 38.82036),
    F(US({ osm_key: "highway", osm_value: "bus_stop", name: "N Oak at N Hill St Southbound", street: "Northeast Hill Street",
           county: "Clay", state: "Missouri", postcode: "64116" }), -94.57708, 39.1594),
    F(US({ osm_key: "highway", osm_value: "residential", name: "North Oak Street", city: "Belton", county: "Cass",
           state: "Missouri", postcode: "64012" }), -94.53033, 38.81768),
    F(US({ osm_key: "highway", osm_value: "residential", name: "North Oak Street", city: "Paola", county: "Miami",
           state: "Kansas" }), -94.87378, 38.57405),
    F(US({ osm_key: "highway", osm_value: "bus_stop", name: "201 North Oak", street: "Main Street", city: "Kansas City",
           county: "Jackson County", state: "Missouri", postcode: "64111" }), -94.58466, 39.07714),
    F(US({ osm_key: "public_transport", osm_value: "platform", name: "Oak Platform", city: "Olathe",
           state: "Kansas", postcode: "66061" }), -94.80, 38.90),
    F(US({ osm_key: "highway", osm_value: "residential", name: "North Oakview Street", city: "Olathe", county: "Johnson",
           state: "Kansas", postcode: "66061" }), -94.80404, 38.91215),
    F(US({ osm_key: "highway", osm_value: "residential", name: "Oakmont Street", city: "Overland Park", county: "Johnson",
           state: "Kansas", postcode: "66213" }), -94.72986, 38.89787),
    F(US({ osm_key: "highway", osm_value: "residential", name: "East 36th Street", city: "Kansas City",
           county: "Jackson County", state: "Missouri", postcode: "64128" }), -94.55102, 39.06026),
    F(US({ osm_key: "highway", osm_value: "residential", name: "East 37th Street", city: "Kansas City",
           county: "Jackson County", state: "Missouri", postcode: "64128" }), -94.54381, 39.05873),
    F(US({ osm_key: "highway", osm_value: "residential", name: "West 142nd Street", city: "Overland Park",
           county: "Johnson", state: "Kansas", postcode: "66223" }), -94.68074, 38.8711),
    F(US({ osm_key: "highway", osm_value: "residential", name: "West 82nd Street", city: "Lenexa", county: "Johnson",
           state: "Kansas", postcode: "66215" }), -94.73799, 38.98113),
  ],
  treadwell: [
    F(US({ osm_key: "place", osm_value: "hamlet", name: "Treadwell", county: "Delaware", state: "New York",
           postcode: "13846" }), -75.05128, 42.3423),
    F({ osm_key: "place", osm_value: "hamlet", name: "Treadwell", city: "Alfred and Plantagenet",
        county: "Prescott and Russell", state: "Ontario", postcode: "J0V 1R0", countrycode: "CA" }, -75.01078, 45.5963),
    F(US({ osm_key: "place", osm_value: "neighbourhood", name: "Treadwell", city: "Berryville", county: "Clarke",
           state: "Virginia", postcode: "22611" }), -77.96472, 39.14788),
    F(US({ osm_key: "place", osm_value: "locality", name: "Treadwell", county: "Murray", state: "Georgia" }),
      -84.87078, 34.78341),
    F(US({ osm_key: "highway", osm_value: "tertiary", name: "Treadwell", city: "Aquilla", county: "Hill",
           state: "Texas", postcode: "76622" }), -97.21921, 31.85117),
    // recorded 2026-11-05: 274 mi, nearer than every hamlet above
    F(US({ osm_key: "highway", osm_value: "residential", name: "Treadwell Drive", city: "Galesburg", county: "Knox",
           state: "Illinois", postcode: "61401" }), -90.3712, 40.9478),
  ],
  // what OSM holds at the office: a tenant's name on 1707 East 123rd Terrace
  officeRow: [
    F(US({ osm_key: "craft", osm_value: "repair", housenumber: "1707", name: "Surface Experts Overland Park - Olathe",
           street: "East 123rd Terrace", city: "Olathe", county: "Johnson", state: "Kansas", postcode: "66061" }),
      -94.78667, 38.90447),
  ],
  wichita: [
    F(US({ osm_key: "highway", osm_value: "residential", name: "Wichita Road", county: "Franklin", state: "Kansas" }),
      -95.2, 38.6),
    F(US({ osm_key: "highway", osm_value: "residential", name: "Wichita Road", city: "Walnut Township",
           county: "Brown", state: "Kansas" }), -95.4, 39.4),
    F(US({ osm_key: "place", osm_value: "county", name: "Wichita", state: "Texas" }), -98.70889, 33.95165),
    F(US({ osm_key: "place", osm_value: "city", name: "Wichita", county: "Sedgwick", state: "Kansas" }),
      -97.33754, 37.69224),
  ],
  olathe: [
    F(US({ osm_key: "place", osm_value: "city", name: "Olathe", county: "Johnson", state: "Kansas" }), -94.81887, 38.88389),
    F(US({ osm_key: "landuse", osm_value: "railway", name: "Olathe", city: "Olathe", county: "Johnson", state: "Kansas" }),
      -94.8219, 38.87934),
    F(US({ osm_key: "railway", osm_value: "junction", name: "Olathe", street: "West Elm Street", city: "Olathe",
           county: "Johnson", state: "Kansas", postcode: "66061" }), -94.82176, 38.87818),
    F(US({ osm_key: "building", osm_value: "school", housenumber: "600", name: "Olathe North Senior High School",
           street: "East Prairie Street", city: "Olathe", county: "Johnson", state: "Kansas", postcode: "66061" }),
      -94.80874, 38.88828),
  ],
};
// "600 Prairie": the bare streets nearer, the numbered row farther away. The number wins.
PH.prairie = [
  F(US({ osm_key: "highway", osm_value: "residential", name: "West Prairie Street", city: "Olathe", county: "Johnson",
         state: "Kansas", postcode: "66061" }), -94.80, 38.89),
  F(US({ osm_key: "highway", osm_value: "residential", name: "Prairie Street", city: "Lawrence", county: "Douglas",
         state: "Kansas", postcode: "66044" }), -95.24, 38.97),
  F(US({ osm_key: "building", osm_value: "school", housenumber: "600", name: "Olathe North Senior High School",
         street: "East Prairie Street", city: "Olathe", county: "Johnson", state: "Kansas", postcode: "66061" }),
    -94.80874, 38.88828),
];
// "123 Main St, Lees Summit" (review, live 2026-11-05): Photon's first row was a bar numbered 123 on
// SE 3rd Street. The number matched, the street did not.
PH.leesMain = [
  F(US({ osm_key: "building", osm_value: "yes", housenumber: "123", name: "Third Street Social",
         street: "Southeast 3rd Street", city: "Lee's Summit", county: "Jackson County", state: "Missouri",
         postcode: "64063" }), -94.37552, 38.91078),
  F(US({ osm_key: "highway", osm_value: "tertiary", name: "Southeast Main Street", city: "Lee's Summit",
         county: "Jackson County", state: "Missouri", postcode: "64063" }), -94.37639, 38.90861),
  F(US({ osm_key: "highway", osm_value: "tertiary", name: "Northeast Main Street", city: "Lee's Summit",
         county: "Jackson County", state: "Missouri", postcode: "64063" }), -94.37617, 38.91372),
];
const CENSUS_LEES = { ok: true, reason: "", rows: [
  { line1: "123 NE Main St", city: "Lees Summit", state: "MO", zip: "64063", lat: 38.91196, lon: -94.37619 },
  { line1: "123 SW Main St", city: "Lees Summit", state: "MO", zip: "64063", lat: 38.91036, lon: -94.37661 },
  { line1: "123 SE Main St", city: "Lees Summit", state: "MO", zip: "64063", lat: 38.91031, lon: -94.37612 }] };
// "Oak St" (review, live 2026-11-05): eight shops, shelters and schools near the office that Photon
// matched on their own NAME, nearer than the one real street (Red Oak Street, Shawnee, 7 mi) and Oak
// Street in Kansas City. By distance alone Red Oak Street was cut at row 9.
const POI = (name, key, value, hn, street, city, lon, lat) =>
  F(US({ osm_key: key, osm_value: value, name, housenumber: hn, street, city, county: "Johnson",
         state: "Kansas", postcode: "66061" }), lon, lat);
PH.oakSt = [
  POI("Smokin Oak Wood-fired Pizza", "amenity", "restaurant", "15241", "West 119th Street", "Olathe", -94.7584, 38.9122),
  POI("Oak Shelter", "amenity", "shelter", undefined, "West 105th Street", "Overland Park", -94.7731, 38.9375),
  POI("Oak Grove Shelter", "amenity", "shelter", undefined, "West 104th Street", "Overland Park", -94.7712, 38.9389),
  POI("Oak Hill Elementary", "amenity", "school", "10200", "West 124th Street", "Overland Park", -94.7020, 38.9050),
  POI("Oak Park Cleaners", "shop", "dry_cleaning", "9540", "Monrovia Street", "Lenexa", -94.7400, 38.9550),
  POI("Oak Dental", "amenity", "dentist", "13505", "South Alden Street", "Olathe", -94.7700, 38.8900),
  POI("Oak Room", "amenity", "restaurant", "1200", "East Santa Fe Street", "Olathe", -94.8000, 38.8830),
  POI("Oak Lane Apartments", "building", "apartments", "300", "North Ridgeview Road", "Olathe", -94.8200, 38.8950),
  F(US({ osm_key: "highway", osm_value: "residential", name: "Red Oak Street", city: "Shawnee", county: "Johnson",
         state: "Kansas", postcode: "66216" }), -94.7712, 39.0012),
  F(US({ osm_key: "highway", osm_value: "residential", name: "Oak Street", city: "Kansas City", county: "Jackson County",
         state: "Missouri", postcode: "64111" }), -94.58031, 39.06569),
];
// The server's answer for "8200 Nieman Rd" (POST /api/address-suggest, from the recorded Census answer).
const CENSUS_NIEMAN = { ok: true, reason: "", rows: [
  { line1: "8200 Nieman Rd", city: "Overland Park", state: "KS", zip: "66214", lat: 38.981024, lon: -94.714617 }] };

function gate() { let release; const p = new Promise((r) => { release = r; }); return { p, release }; }

/** A fresh page: the real module mounted on stub boxes, a fetch that answers Photon from `photon(q)`
 *  and our server from `server()`, every request recorded, and timers that run on demand (in delay
 *  order, so "Photon only" can be run before the Census step). */
function nearWorld(opts) {
  opts = opts || {};
  const dom = { address: el("address-input"), business: el("business-input"),
                city: el("city-input"), state: el("state-input"), zip: el("zip-input"),
                ar: el("address-results"), br: el("business-results") };
  const byId = { "address-results": dom.ar, "business-results": dom.br };
  const doc = { getElementById: (id) => byId[id] || null, addEventListener() {} };
  const rec = { photon: [], server: [], picks: [] };
  const fetchStub = async (url, init) => {
    url = String(url);
    let host = "";
    try { host = new URL(url).hostname; } catch (e) { host = ""; }
    if (host === "photon.komoot.io") {
      const q = new URL(url).searchParams.get("q");
      rec.photon.push(url);
      if (opts.photonFails) throw new Error("photon down");
      return { json: async () => ({ features: JSON.parse(JSON.stringify((opts.photon || (() => []))(q))) }) };
    }
    if (url === "/api/address-suggest") {
      rec.server.push({ method: init && init.method, headers: init && init.headers,
                        body: init && init.body ? JSON.parse(init.body) : null, signal: !!(init && init.signal) });
      if (opts.serverGate) await opts.serverGate.p;
      const r = opts.server ? opts.server() : { ok: false, rows: [], reason: "not_found" };
      if (r === "throw") throw new Error("server down");
      if (r === "badjson") return { json: async () => { throw new Error("not json"); } };
      return { json: async () => r };
    }
    throw new Error("unexpected fetch " + url);
  };
  const timers = [];
  const setT = (f, ms) => { timers.push({ f, ms: ms || 0, live: true }); return timers.length; };
  const clearT = (id) => { if (timers[id - 1]) timers[id - 1].live = false; };
  const win = { TW: { resolveApiBase: () => "",
                      authHeaders: (h) => Object.assign({ Authorization: "Bearer t" }, h || {}) } };
  if (opts.noTW) delete win.TW;
  if (opts.authReady) win.TWAuth = { ready: opts.authReady };
  new Function("document", "window", "fetch", "setTimeout", "clearTimeout", "Event", SRC)(
    doc, win, fetchStub, setT, clearT, class { constructor(t, o) { this.type = t; this.bubbles = !!(o && o.bubbles); } });
  win.TWAddress.mount({ address: dom.address, business: dom.business, city: dom.city, state: dom.state,
                        zip: dom.zip, onPick: (p) => rec.picks.push(p) });
  const settle = async () => { for (let i = 0; i < 12; i++) await new Promise((r) => setImmediate(r)); };
  const fire = (node, type, ev) => (node.listeners[type] || []).forEach((f) => f(ev || {}));
  const api = {
    dom, rec, win, settle,
    /** Type into a box, run the timers up to `upTo` ms (default all), then let the answers land. */
    async type(box, text, upTo) {
      const node = box === "business" ? dom.business : dom.address;
      node.value = text; fire(node, "focus"); fire(node, "input");
      await api.run(upTo);
    },
    async run(upTo) {
      const due = timers.filter((t) => t.live && (upTo == null || t.ms <= upTo));
      due.sort((a, b) => a.ms - b.ms);
      due.forEach((t) => { t.live = false; });
      for (const t of due) { t.f(); await settle(); }
      await settle();
    },
    pending: () => timers.filter((t) => t.live).map((t) => t.ms),
    blur(box) { fire(box === "business" ? dom.business : dom.address, "blur"); },
    /** [{l1, l2}] as drawn. */
    rows(box) {
      const html = (box === "business" ? dom.br : dom.ar).html;
      const out = [];
      const re = /<div class="addr-l1">([^<]*)<\/div><div class="addr-l2">([^<]*)<\/div>/g;
      let m;
      while ((m = re.exec(html))) out.push({ l1: m[1], l2: m[2] });
      return out;
    },
    open: (box) => (box === "business" ? dom.br : dom.ar).isOpen(),
    pick(box, i) {
      const r = (box === "business" ? dom.br : dom.ar).rows[i];
      r.listeners.click.forEach((f) => f());
      return { address: dom.address.value, city: dom.city.value, state: dom.state.value, zip: dom.zip.value,
               business: dom.business.value, onPick: rec.picks[rec.picks.length - 1] || null };
    },
  };
  return api;
}

async function nearest() {
  const o = {};
  const A = (() => { const w = {}; new Function("document", "window", "fetch", SRC)({}, w, null); return w.TWAddress; })();

  // 1. THE QUERY. Abbreviations spelled out as whole words; the box keeps what was typed.
  const TABLE = ["8200 Nieman Rd", "1707 e 123rd ter", "1707 E. 123rd Terr", "St. Joseph", "St Joseph Ave",
    "Main St", "Main St.", "Main St, Olathe", "100 Main St Olathe KS", "Lake St. Louis", "100 St Louis Ave",
    "Dr Martin Luther King Jr Blvd", "500 Oak Dr", "12 Elm Ln", "3 Pine Ct", "9 Ward Pkwy", "10 Old Hwy 7",
    "4 Rose Pl", "5 Lake Cir", "6 Bike Trl", "7 Town Sq", "8 Metcalf Av", "1 Lee's Summit Expy",
    "8200 Nieman Rd, KS", "300 W 5th Street", "Roadhouse Rd"];
  o.expand = {};
  TABLE.forEach((q) => { o.expand[q] = A.expandQuery(q); });
  o.houseNumber = { nieman: A.houseNumberOf("8200 Nieman Rd"), dir: A.houseNumberOf("8200 W 75th St"),
                    thin: A.houseNumberOf("8200 N"), none: A.houseNumberOf("Nieman Rd") };
  o.isOffice = ["treadwell", "Treadwell office", "TREADWELL", "1707 e 123rd", "1707 East 123rd Terrace",
                "1707 E. 123rd", "1708 e 123rd", "123rd Terrace"].map((q) => A.isOfficeQuery(q));

  // 2. THE PHOTON QUESTION: around the office, US box, the bias and limit chosen; the box unchanged.
  {
    const w = nearWorld({ photon: () => PH.nieman, server: () => ({ ok: false, rows: [], reason: "not_found" }) });
    await w.type("address", "8200 Nieman Rd");
    const u = new URL(w.rec.photon[0]);
    o.url = { host: u.hostname, q: u.searchParams.get("q"), lat: u.searchParams.get("lat"),
              lon: u.searchParams.get("lon"), bbox: u.searchParams.get("bbox"), zoom: u.searchParams.get("zoom"),
              bias: u.searchParams.get("location_bias_scale"), limit: u.searchParams.get("limit"),
              box: w.dom.address.value, calls: w.rec.photon.length };
  }

  // 3. FOREIGN AND TRANSIT ROWS DROPPED, NEAREST FIRST, AT MOST 8.
  {
    const w = nearWorld({ photon: () => PH.foreign.concat(PH.nieman) });
    await w.type("address", "Nieman Road");
    o.foreign = { rows: w.rows(), server: w.rec.server.length };
    const w2 = nearWorld({ photon: () => PH.oak });
    await w2.type("address", "N Oak Street");
    o.oak = { rows: w2.rows() };
    const w3 = nearWorld({ photon: () => PH.olathe });
    await w3.type("address", "Olathe");
    o.olathe = { rows: w3.rows() };
  }

  // 4. THE TYPED HOUSE NUMBER FIRST; A TOWN TYPED BY NAME IS NOT BURIED.
  {
    const w = nearWorld({ photon: () => PH.prairie, server: () => CENSUS_NIEMAN });
    await w.type("address", "600 Prairie");
    o.prairie = { rows: w.rows(), server: w.rec.server.length };
    const w2 = nearWorld({ photon: () => PH.wichita });
    await w2.type("address", "Wichita");
    o.wichita = { rows: w2.rows() };
    o.rankPure = A.rankFeatures(PH.wichita.concat(PH.oak), "Wichi").map((x) => x.f.properties.name);
  }

  // 5. THE OFFICE, PINNED FIRST.
  {
    const w = nearWorld({ photon: () => PH.treadwell });
    await w.type("address", "treadwell");
    o.officeAddr = { rows: w.rows(), server: w.rec.server.length };
    o.officeAddr.pick = w.pick("address", 0);
    const w2 = nearWorld({ photon: () => PH.officeRow, server: () => CENSUS_NIEMAN });
    await w2.type("address", "1707 e 123rd ter");
    o.officeStreet = { rows: w2.rows(), server: w2.rec.server.length,
                       q: new URL(w2.rec.photon[0]).searchParams.get("q") };
    const w3 = nearWorld({ photon: () => PH.treadwell, server: () => CENSUS_NIEMAN });
    await w3.type("business", "Treadwell office");
    o.officeBiz = { rows: w3.rows("business"), server: w3.rec.server.length };
    o.officeBiz.pick = w3.pick("business", 0);
    const w4 = nearWorld({ photonFails: true });
    await w4.type("address", "Treadwell");
    o.officePhotonDown = { rows: w4.rows(), open: w4.open() };
  }

  // 6. THE CENSUS ROWS: on top when they come, never when the text moved on or the box was left.
  {
    const w = nearWorld({ photon: () => PH.nieman, server: () => CENSUS_NIEMAN });
    await w.type("address", "8200 Nieman Rd", 300);          // Photon only: the Census step waits longer
    const before = { rows: w.rows(), server: w.rec.server.length, pending: w.pending() };
    await w.run();
    const s = w.rec.server[0] || {};
    o.census = { before, rows: w.rows(), calls: w.rec.server.length, method: s.method, body: s.body,
                 auth: s.headers && s.headers.Authorization, type: s.headers && s.headers["Content-Type"],
                 signal: s.signal, box: w.dom.address.value };
    o.census.pick = w.pick("address", 0);

    // a newer text owns the box by the time the answer lands
    const g = gate();
    const w2 = nearWorld({ photon: (q) => (/Nieman/.test(q) ? PH.nieman : PH.oak), server: () => CENSUS_NIEMAN,
                           serverGate: g });
    await w2.type("address", "8200 Nieman Rd");
    await w2.type("address", "N Oak Street");
    g.release(); await w2.settle();
    o.movedOn = { rows: w2.rows(), calls: w2.rec.server.length };

    // the box was left before the answer landed
    const g3 = gate();
    const w3 = nearWorld({ photon: () => PH.nieman, server: () => CENSUS_NIEMAN, serverGate: g3 });
    await w3.type("address", "8200 Nieman Rd");
    const openBefore = w3.open();
    w3.blur("address");
    g3.release(); await w3.settle();
    o.leftBox = { openBefore, open: w3.open(), calls: w3.rec.server.length };

    // Photon has the number: the server is not asked
    const numbered = [F(US({ osm_key: "building", osm_value: "yes", housenumber: "8200", street: "Nieman Road",
                              city: "Overland Park", state: "Kansas", postcode: "66214" }), -94.7146, 38.981)];
    const w4 = nearWorld({ photon: () => numbered.concat(PH.nieman), server: () => CENSUS_NIEMAN });
    await w4.type("address", "8200 Nieman Rd");
    o.photonHasIt = { calls: w4.rec.server.length, first: w4.rows()[0] };

    // every way the server can fail: Photon's rows stand, nothing throws
    o.fails = {};
    const MODES = {
      throw: () => "throw", badjson: () => "badjson",
      notok: () => ({ ok: false, rows: [], reason: "error" }), noTW: () => CENSUS_NIEMAN,
      junkRows: () => ({ ok: true, rows: [null, "x", { line1: "", state: "KS" }, { line1: "1 A St", state: "Kansas" }] }),
    };
    for (const mode of Object.keys(MODES)) {
      const w5 = nearWorld({ photon: () => PH.nieman, server: MODES[mode], noTW: mode === "noTW" });
      let threw = false;
      try { await w5.type("address", "8200 Nieman Rd"); } catch (e) { threw = true; }
      o.fails[mode] = { threw, rows: w5.rows().length, census: w5.rows().filter((r) => /US Census/.test(r.l2)).length,
                        open: w5.open() };
    }

    // the sign-in is waited for before asking
    let readyResolved = false;
    const ready = new Promise((r) => setImmediate(() => { readyResolved = true; r(); }));
    const w6 = nearWorld({ photon: () => PH.nieman, server: () => CENSUS_NIEMAN, authReady: ready });
    await w6.type("address", "8200 Nieman Rd");
    o.authReady = { readyResolved, calls: w6.rec.server.length,
                    census: /US Census/.test((w6.rows()[0] || {}).l2 || "") };

    // the business box never asks the server
    const w7 = nearWorld({ photon: () => PH.nieman, server: () => CENSUS_NIEMAN });
    await w7.type("business", "8200 Nieman Rd");
    o.businessNoCensus = { calls: w7.rec.server.length, rows: w7.rows("business").length };
  }

  // 7. REVIEW FIXES (2026-11-05).
  {
    // The typed number on ANOTHER street is not the address: it is not ranked first, and the
    // Census is still asked (it has 123 NE / SW / SE Main St).
    const w = nearWorld({ photon: () => PH.leesMain, server: () => CENSUS_LEES });
    await w.type("address", "123 Main St, Lees Summit");
    o.leesMain = { calls: w.rec.server.length, rows: w.rows(),
                   pure: A.hasTypedNumber(PH.leesMain[0].properties, "123 Main St, Lees Summit"),
                   onMain: A.hasTypedNumber({ housenumber: "123", street: "Northeast Main Street" }, "123 Main St") };
    o.keyWord = ["123 Main St, Lees Summit", "8200 W 75th St", "N Oak Street", "1707 e 123rd ter", "Treadwell office",
                 "St Joseph Ave", "8200 Niem"].map((q) => A.keyWordOf(q));

    // Streets that carry the typed word come before shops matched on their own name.
    const w2 = nearWorld({ photon: () => PH.oakSt });
    await w2.type("address", "Oak St");
    o.oakSt = { rows: w2.rows() };

    // A pick ends the questions still out: the late Census answer never re-opens the list.
    const g = gate();
    const w3 = nearWorld({ photon: () => PH.nieman, server: () => CENSUS_NIEMAN, serverGate: g });
    await w3.type("address", "8200 Nieman Rd");          // every timer run: the Census question is out
    const asked = w3.rec.server.length;
    const picked = w3.pick("address", 0);
    const picks = w3.rec.picks.length;
    g.release(); await w3.settle();
    o.pickThenLate = { asked, picked: picked.address, openAfter: w3.open(), box: w3.dom.address.value,
                       zip: w3.dom.zip.value, picks: w3.rec.picks.length - picks, rows: w3.rows().length };
    // ... and a pick before the Census wait is over never asks at all.
    const w4 = nearWorld({ photon: () => PH.nieman, server: () => CENSUS_NIEMAN });
    await w4.type("address", "8200 Nieman Rd", 300);
    w4.pick("address", 1);
    await w4.run();
    o.pickBeforeCensus = { calls: w4.rec.server.length, open: w4.open(), box: w4.dom.address.value,
                           zip: w4.dom.zip.value };

    // A click picks the row it shows, below the inserted Census and office rows too.
    const picksAt = async (photon, server, text, idxs) => {
      const out = [];
      for (const i of idxs) {
        const wx = nearWorld({ photon: () => photon, server: () => server });
        await wx.type("address", text);
        const shown = wx.rows()[i];
        const got = wx.pick("address", i);
        out.push({ shown: shown.l1 + " | " + shown.l2, address: got.address, city: got.city, zip: got.zip });
      }
      return out;
    };
    o.pickIdx = {
      census: await picksAt(PH.nieman, CENSUS_NIEMAN, "8200 Nieman Rd", [0, 1, 2, 3]),
      office: await picksAt(PH.treadwell, null, "treadwell", [0, 1, 2]),
    };
  }
  return o;
}

(async () => {
  const out = {};
  const dom = { address: el("address-input"), business: el("business-input"),
                city: el("city-input"), state: el("state-input"), zip: el("zip-input"),
                ar: el("address-results"), br: el("business-results") };
  const byId = { "address-results": dom.ar, "business-results": dom.br };
  const docListeners = {};
  const doc = { getElementById: (id) => byId[id] || null,
                addEventListener: (t, f) => { (docListeners[t] = docListeners[t] || []).push(f); } };
  const calls = [];
  const fetchStub = async (url) => { calls.push(String(url)); return { json: async () => ({ features: FEATS }) }; };
  const timers = [];
  const setT = (f) => { timers.push(f); return timers.length; };
  const win = {};
  new Function("document", "window", "fetch", "setTimeout", "clearTimeout", "Event", SRC)(
    doc, win, fetchStub, setT, () => {}, class { constructor(t, o) { this.type = t; this.bubbles = !!(o && o.bubbles); } });
  const A = win.TWAddress;
  out.exports = Object.keys(A).sort();
  A.mount({ address: dom.address, business: dom.business, city: dom.city, state: dom.state, zip: dom.zip });

  const flush = async () => { while (timers.length) { timers.shift()(); } await new Promise((r) => setImmediate(r)); };

  // under four characters: no request
  dom.address.value = "12"; dom.address.listeners.input.forEach((f) => f()); await flush();
  out.shortQuery = { calls: calls.length, open: dom.ar.isOpen() };

  // a real query: one request, US only, the duplicate collapsed
  dom.address.value = "123 W 5th"; dom.address.listeners.input.forEach((f) => f()); await flush();
  out.query = { calls: calls.length, url: calls[0], open: dom.ar.isOpen(),
                rows: (dom.ar.html.match(/class="addr-row"/g) || []).length,
                hasParis: dom.ar.html.indexOf("Paris") >= 0 };

  // pick the row
  dom.ar.rows[0].listeners.click.forEach((f) => f());
  out.pick = { address: dom.address.value, city: dom.city.value, state: dom.state.value,
               zip: dom.zip.value, closed: !dom.ar.isOpen(),
               cityEvents: dom.city.events.slice(), stateEvents: dom.state.events.slice(),
               zipEvents: dom.zip.events.slice(),
               addressEvents: dom.address.events.slice(), businessEvents: dom.business.events.slice() };

  // the business box fills the location but keeps the typed project name
  dom.business.value = "Acme warehouse retrofit"; dom.business.listeners.input.forEach((f) => f()); await flush();
  dom.city.value = ""; dom.zip.value = "";
  dom.br.rows[0].listeners.click.forEach((f) => f());
  out.business = { name: dom.business.value, city: dom.city.value, zip: dom.zip.value,
                   rows: (dom.br.html.match(/class="addr-row"/g) || []).length };

  // a click elsewhere closes the dropdown; a click inside the input does not
  dom.ar.classList.add("open");
  docListeners.click.forEach((f) => f({ target: dom.address }));
  const stayed = dom.ar.isOpen();
  docListeners.click.forEach((f) => f({ target: {} }));
  out.clickAway = { stayedOpenOnInputClick: stayed, closedElsewhere: !dom.ar.isOpen() };

  // LEAVING THE BOX CLOSES ITS LIST (2026-10-20 browser walk: Tab left it open over City, State and Zip)
  const fire = (node, type, ev) => (node.listeners[type] || []).forEach((f) => f(ev || {}));
  dom.address.value = "123 W 5th St"; fire(dom.address, "focus"); fire(dom.address, "input"); await flush();
  const openWhileIn = dom.ar.isOpen();
  fire(dom.address, "blur");
  const closedOnLeave = !dom.ar.isOpen();
  // an answer that lands after the box was left never opens the list
  dom.address.value = "123 W 5th Street"; fire(dom.address, "input"); fire(dom.address, "blur"); await flush();
  const lateStaysShut = !dom.ar.isOpen();
  // back in the box: it opens again; Escape closes it and is consumed
  fire(dom.address, "focus"); fire(dom.address, "input"); await flush();
  const reopened = dom.ar.isOpen();
  let escPrevented = false;
  fire(dom.address, "keydown", { key: "Escape", preventDefault() { escPrevented = true; } });
  const closedOnEsc = !dom.ar.isOpen();
  // a press on the list keeps the focus in the box, so a pick is never lost to the blur
  let downPrevented = false;
  fire(dom.ar, "mousedown", { preventDefault() { downPrevented = true; } });
  // the business box behaves the same
  fire(dom.business, "focus"); dom.business.value = "Acme warehouse"; fire(dom.business, "input"); await flush();
  const bizOpen = dom.br.isOpen();
  fire(dom.business, "blur");
  out.leave = { openWhileIn, closedOnLeave, lateStaysShut, reopened, closedOnEsc, escPrevented, downPrevented,
                bizOpen, bizClosedOnLeave: !dom.br.isOpen() };

  // a page with no business box (mount tolerates it)
  const doc2 = { getElementById: (id) => (id === "address-results" ? dom.ar : null), addEventListener() {} };
  const w2 = {};
  new Function("document", "window", "fetch", "setTimeout", "clearTimeout", "Event", SRC)(
    doc2, w2, fetchStub, setT, () => {}, class {});
  let threw = false;
  try { w2.TWAddress.mount({ address: dom.address, city: dom.city, state: dom.state, zip: dom.zip }); }
  catch (e) { threw = true; }
  out.noBusinessBox = { threw };
  // ═══ NEAREST FIRST (Hanz, 2026-11-05) ═══════════════════════════════════════════════════════
  // "Treadwell" was Delaware NY, Berryville VA, Murray GA, Aquilla TX; "8200 Nieman" was France and
  // Finland and then nothing. The Photon answers below are the REAL shapes from live calls that day
  // (properties trimmed to what the module reads, coordinates [lon, lat]).
  out.near = await nearest();
  out.office = A.OFFICE;
  out.photon = A.PHOTON;
  process.stdout.write(JSON.stringify(out) + "\n");
})().catch((e) => { process.stderr.write(String(e && e.stack || e) + "\n"); process.exit(1); });
