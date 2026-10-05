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
      // one stub row per addr-row so a click can be driven by index
      this.rows = [];
      const n = (h.match(/class="addr-row"/g) || []).length;
      for (let i = 0; i < n; i++) {
        const row = { dataset: { idx: String(i) }, listeners: {},
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

  // a page with no business box (mount tolerates it)
  const doc2 = { getElementById: (id) => (id === "address-results" ? dom.ar : null), addEventListener() {} };
  const w2 = {};
  new Function("document", "window", "fetch", "setTimeout", "clearTimeout", "Event", SRC)(
    doc2, w2, fetchStub, setT, () => {}, class {});
  let threw = false;
  try { w2.TWAddress.mount({ address: dom.address, city: dom.city, state: dom.state, zip: dom.zip }); }
  catch (e) { threw = true; }
  out.noBusinessBox = { threw };
  process.stdout.write(JSON.stringify(out) + "\n");
})().catch((e) => { process.stderr.write(String(e && e.stack || e) + "\n"); process.exit(1); });
