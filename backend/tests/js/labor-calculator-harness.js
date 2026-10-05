"use strict";
/* EXECUTE the Labor Calculator tab's Travel section: the shipped code out of library.js.
 *
 * The block from `// ── the Labor Calculator tab` to `// ── view switch` is taken whole and run
 * against a fake DOM, a fake fetch and the real library-core.js (money) and polish-bid-core.js
 * (travelSeed). Nothing is restated: a source assertion cannot tell a rate box that saves from one
 * that does not, which is exactly how the Defaults tab's Markup inputs shipped with no handler.
 *
 * Usage: node labor-calculator-harness.js <frontend-dir>   ->   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(process.argv[2]);
const read = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");
const src = read(path.join(ROOT, "js", "library.js"));
const L = require(path.join(ROOT, "js", "library-core.js"));
const B = require(path.join(ROOT, "js", "polish-bid-core.js"));

const START = "  // ── the Labor Calculator tab (Hanz, 2026-10-05)";
const END = "  // ── view switch ";
const a = src.indexOf(START);
const b = src.indexOf(END);
if (a < 0 || b < a) {
  throw new Error("the Labor Calculator block is gone from library.js -- rewrite this harness");
}
const BLOCK = src.slice(a, b);

const clone = (v) => JSON.parse(JSON.stringify(v));
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function make(opts) {
  const els = {};
  ["labcalc-body", "labcalc-ro", "labcalc-alert"].forEach((id) => {
    els[id] = { id, innerHTML: "", textContent: "", hidden: false };
  });
  const puts = [];
  const rec = { fetches: [] };
  const GLOBAL_MARKUP = clone(opts.globalMarkup || []);
  const fetchStub = async (url, init) => {
    rec.fetches.push(url);
    if ((init || {}).method === "PUT") {
      const body = JSON.parse(init.body);
      puts.push(body);
      if (opts.putStatus === 403) return { ok: false, status: 403, json: async () => ({}) };
      if (opts.putStatus === 400) {
        return { ok: false, status: 400, json: async () => ({ detail: "the server said no" }) };
      }
      return { ok: true, status: 200, json: async () => ({ ok: true, rule: Object.assign({ id: "n1" }, body) }) };
    }
    if (opts.readFails) throw new Error("down");
    return { ok: true, status: 200, json: async () => ({ ok: true, rules: clone(opts.rules || []) }) };
  };
  const body = BLOCK + "\nreturn { renderLabCalc: renderLabCalc, saveTravelRate: saveTravelRate, " +
    "travelFigure: travelFigure, rules: function () { return TRAVEL_RULES; } };";
  const scope = new Function("$", "esc", "api", "L", "LABOR", "ADMIN", "GLOBAL_MARKUP", "window", body);
  const api = scope((id) => els[id] || null, esc, fetchStub, L, clone(opts.labor || []),
                    opts.admin !== false, GLOBAL_MARKUP, { TWPolishBid: B });
  return { api, els, puts, rec, GLOBAL_MARKUP };
}

const settle = () => new Promise((r) => setImmediate(r));
const input = (key, value) => ({
  value: value,
  getAttribute: (k) => (k === "data-travel-rate" ? key : null),
});
const RULE = (key, formula, extra) => Object.assign({ id: "r-" + key, layout: "global",
  line_key: key, formula: formula, applies: true, notes: "" }, extra || {});

(async () => {
  const out = {};

  // ── an admin sees the stored rates in boxes, and the Travel row's rate off the Labor tab ──────
  {
    const s = make({ rules: [RULE("travel_lodging", "80", { notes: "kept note" })],
                     labor: [{ id: "travel", name: "Travel", rate: "41.50", unit: "hours" }],
                     globalMarkup: [{ id: "r-travel_lodging", line_key: "travel_lodging", formula: "80" }] });
    s.api.renderLabCalc();
    const loadingFirst = s.els["labcalc-body"].innerHTML;
    await settle();
    const html = s.els["labcalc-body"].innerHTML;
    out.admin = {
      loadingFirst: loadingFirst,
      readOnce: s.rec.fetches.length,
      lodgingBox: /data-travel-rate="travel_lodging" value="80"/.test(html),
      perDiemBoxEmptyWithShippedPlaceholder:
        /data-travel-rate="travel_per_diem" value="" placeholder="45"/.test(html),
      travelLaborRow: /Travel Labor<\/td><td class="n">\$41\.50 an hour/.test(html),
      seventyMiles: html.indexOf("70 miles or more") !== -1,
      insideMarkups: html.indexOf("before GP") !== -1,
      roHidden: s.els["labcalc-ro"].hidden,
    };

    // saving keeps the filed note and files the whole row on the GLOBAL layout
    const box = input("travel_per_diem", "55");
    await s.api.saveTravelRate(box);
    const lodgingBox = input("travel_lodging", "$90");
    await s.api.saveTravelRate(lodgingBox);
    out.saved = {
      puts: s.puts,
      alert: s.els["labcalc-alert"].textContent,
      cached: s.api.rules()["travel_per_diem"].formula,
      defaultsTabCopy: s.GLOBAL_MARKUP.map((g) => [g.line_key, g.formula]),
    };

    // the same value again, and a blank, send nothing
    const before = s.puts.length;
    await s.api.saveTravelRate(input("travel_per_diem", "55"));
    await s.api.saveTravelRate(input("travel_per_diem", ""));
    out.noops = { sent: s.puts.length - before, alert: s.els["labcalc-alert"].textContent };

    // refused in words, nothing sent, the box put back
    const bad = [];
    for (const v of ["abc", "0", "-5", "70 a night", "7e1"]) {
      const bx = input("travel_lodging", v);
      const n = s.puts.length;
      await s.api.saveTravelRate(bx);
      bad.push({ v: v, sent: s.puts.length - n, back: bx.value, alert: s.els["labcalc-alert"].textContent });
    }
    out.refused = bad;
  }

  // ── a refused save (403 / 400) puts the old figure back and says so ──────────────────────────
  {
    const s = make({ rules: [RULE("travel_lodging", "80")], putStatus: 403 });
    s.api.renderLabCalc(); await settle();
    const bx = input("travel_lodging", "99");
    await s.api.saveTravelRate(bx);
    const s4 = make({ rules: [RULE("travel_lodging", "80")], putStatus: 400 });
    s4.api.renderLabCalc(); await settle();
    const bx4 = input("travel_lodging", "99");
    await s4.api.saveTravelRate(bx4);
    out.refusedByServer = { back403: bx.value, alert403: s.els["labcalc-alert"].textContent,
                            back400: bx4.value, alert400: s4.els["labcalc-alert"].textContent,
                            cacheKept: s.api.rules()["travel_lodging"].formula };
  }

  // ── a non-admin sees the figures as text, with no boxes ──────────────────────────────────────
  {
    const s = make({ admin: false, rules: [RULE("travel_lodging", "80")] });
    s.api.renderLabCalc(); await settle();
    const html = s.els["labcalc-body"].innerHTML;
    out.nonAdmin = { boxes: (html.match(/data-travel-rate/g) || []).length,
                     showsLodging: html.indexOf("$80.00 per night") !== -1,
                     showsShippedPerDiem: html.indexOf("$45.00 per day") !== -1,
                     roShown: s.els["labcalc-ro"].hidden === false };
  }

  // ── the markup read going down is said out loud and invents no rate ──────────────────────────
  {
    const s = make({ readFails: true });
    s.api.renderLabCalc(); await settle();
    const html = s.els["labcalc-body"].innerHTML;
    out.readFails = { said: html.indexOf("Could not read the saved figures") !== -1,
                      boxesEmpty: /data-travel-rate="travel_lodging" value=""/.test(html) };
  }

  // ── filed-but-off and non-numeric rules read as not filed ────────────────────────────────────
  {
    const s = make({});
    out.figure = [s.api.travelFigure(RULE("travel_lodging", "70")),
                  s.api.travelFigure(RULE("travel_lodging", "$70.5")),
                  s.api.travelFigure(RULE("travel_lodging", "70", { applies: false })),
                  s.api.travelFigure(RULE("travel_lodging", "IF(1,2,3)")),
                  s.api.travelFigure(null)];
  }

  console.log(JSON.stringify(out));
})().catch((err) => { console.error(err && err.stack || err); process.exit(1); });
