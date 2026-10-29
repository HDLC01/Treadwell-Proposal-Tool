"use strict";
/* THE MAN HOURS AND BUDGET CARD ON THE REAL REVIEW STEP (Hanz, 2026-10-27: "In the review tab we need to show the Man hours,
 * the budget ... Take it from the sheet").
 *
 * js/polish-estimate.js, whole, booted the way polish-estimate-harness.js boots it, on the library the seed plans. An Epoxy job
 * (Hanz's own block: 3 guys for 6 days, 144 man hours) and the harness's Polish job are taken to the Review step; the card is read
 * off what the page drew and set beside B.manHourBudget over the section's rows and the bid the page priced. Then a keystroke
 * on the Review (Contingency) and one on the Labor step move it without a rebuild, the bid is saved and reopened the way the
 * server hands a draft back (jsonb: every key reordered), and a Seal option on the same bid draws no card.
 *
 * Usage: node man-hours-review-harness.js <frontend-dir> <plan.json>   ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");
const Module = require("module");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const plan = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const B = require(path.join(ROOT, "js", "bid-model.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));

function loadPrelude(file, exportNames) {
  const base = path.join(__dirname, file);
  const code = L.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in man-hours-review-harness.js");
  const m = new Module(base, module);
  m.filename = base;
  m.paths = Module._nodeModulePaths(path.dirname(base));
  m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
  return m.exports;
}

const P = loadPrelude("polish-estimate-harness.js", ["build", "blob", "typeInto", "clickEl", "need", "MODEL"]);

const asms = plan.assemblies;
const items = plan.items;
const norm = (t) => String(t).replace(/\s+/g, " ").trim();
const asmNamed = (n) => asms.find((a) => norm(a.name) === norm(n));
const TRAVEL_ROW = { id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true, sort: -1, favorite: true,
  default_work_types: [], default_on: true };
const laborRows = [TRAVEL_ROW].concat(plan.labor.map((r) => Object.assign({}, r, { default_on: true, owner_email: "kyle@wetreadwell.com" })));
const calcRows = plan.labor_calc.map((r) => Object.assign({}, r, { days: null, rate: null, sf_per_day: null, crew: null }));

const flush = () => new Promise((r) => setImmediate(r));
const html = (b, id) => b.doc.getElementById(id).innerHTML;
const dec = (s) => String(s).replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&");

/** The card as the page DREW it: { present, title, head, rows: [[cell texts]], figs: { mh.key: text } }. */
function drawn(b) {
  const h = html(b, "panels");
  const at = h.indexOf('<div data-rev="manhours"');
  if (at < 0) return { present: false };
  const part = h.slice(at, h.indexOf("</table>", at));
  // Strip tags until none is left (one pass can leave a tag rebuilt from the pieces around it).
  const strip = (s) => { let out = String(s), prev; do { prev = out; out = out.replace(/<[^>]*>/g, ""); } while (out !== prev); return out; };
  const text = (s) => dec(strip(s)).replace(/\s+/g, " ").trim();
  const figs = {};
  (part.match(/data-rv="mh\.[^"]*">[^<]*</g) || []).forEach((m) => { const x = /data-rv="([^"]*)">([^<]*)</.exec(m); figs[x[1]] = dec(x[2]); });
  return {
    present: true,
    title: text((/<div class="rev-h">([\s\S]*?)<button/.exec(part) || [])[1] || ""),
    head: (part.match(/<th[^>]*>[\s\S]*?<\/th>/g) || []).map(text),
    rows: (part.match(/<tr[^>]*>[\s\S]*?<\/tr>/g) || []).filter((r) => /<td/.test(r))
      .map((r) => (r.match(/<td[^>]*>[\s\S]*?<\/td>/g) || []).map(text)),
    figs: figs,
  };
}

/** The mh.* figures on screen NOW, read off the live nodes (a repaint changes a node's text, never the panel's markup). */
function live(b) {
  const out = {};
  b.doc.querySelectorAll("[data-rv]").forEach((el) => {
    const k = el.getAttribute("data-rv");
    if (k.indexOf("mh.") === 0) out[k] = el.textContent;
  });
  return out;
}

/** What the model says the section on show comes to, with no page in it: B.manHourBudget over its rows and its bid. */
function expected(api) {
  const m = api.model();
  return B.manHourBudget(clone(m.labor), clone(m.conditions), B.prevailingApplied(api.root()), api.activeBid());
}

async function open(opts) {
  const b = P.build(Object.assign({ asms: asms, items: items, labor: laborRows, laborCalc: calcRows }, opts));
  await b.api.init();
  await flush();
  return b;
}

async function main() {
  const out = {};

  // ── 1. an Epoxy job: flake and cove, three guys for six days, on the Review ──
  const epoxyBlob = P.blob({
    work_type: "epoxy", system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "",
    polish_estimate: { version: 2, conditions: { taxable: true, prevailing_wage: false, remodel_tax: false } },
  });
  const b = await open({ blob: epoxyBlob });
  const api = b.api;
  api.setAssembly(0, asmNamed("MACRO Flake Single Broadcast").name);
  api.setAssembly(1, asmNamed("Cove: Epoxy 4\"").name);
  api.changed(true);
  api.go(1);
  const crew = api.model().labor.findIndex((r) => r.id === "epoxy-install");
  P.typeInto(b, '[data-lab="' + crew + '"][data-k="guys"]', "3");
  P.typeInto(b, '[data-lab="' + crew + '"][data-k="days"]', "6");
  P.typeInto(b, '[data-lab="' + crew + '"][data-k="rate"]', "32.2");
  api.changed(false);
  api.go(2);
  out.epoxy = { card: drawn(b), want: expected(api), bid: api.activeBid(), labor: clone(api.model().labor) };

  // a keystroke on the Review: Contingency is a dollar figure inside Mark Up + Conting. and MarkUp + Soft Costs
  P.typeInto(b, "[data-contingency]", "500");
  out.epoxy.afterContingency = { live: live(b), want: expected(api), bid: api.activeBid() };
  api.renderPanel();                                         // a fresh paint of the same model, to set the repaint beside
  out.epoxy.afterContingency.rebuilt = drawn(b).figs;

  // a keystroke on the Labor step: one more day, then back to the Review, which is drawn anew
  api.go(1);
  P.typeInto(b, '[data-lab="' + crew + '"][data-k="days"]', "7");
  api.changed(false);
  api.go(2);
  out.epoxy.afterDay = { card: drawn(b), want: expected(api) };
  b.clock.fire();

  // ── 2. saved and reopened as the server hands it back: every object's keys reordered (jsonb) ──
  const again = await open({ blob: clone(b.store.blob), reloaded: true });
  again.api.go(2);
  out.reload = { card: drawn(again), want: expected(again.api), total: again.api.activeBid().total,
                 savedTotal: b.api.activeBid().total, saves: again.rec.saves.length };

  // ── 3. the harness's own Polish job: the root, its Polishing and Mock-up lines at $32.20 ──
  const pol = await open({ blob: P.blob() });
  pol.api.go(2);
  out.polish = { card: drawn(pol), want: expected(pol.api), labor: clone(pol.api.model().labor), bid: pol.api.activeBid() };

  // ── 4. a Seal option beside the Epoxy base: its Review has no such card (its tab's block is not checked yet) ──
  const withSeal = clone(b.store.blob);
  withSeal.polish_estimate.tabs.Seal = { layout: "seal", kind: "option", profile: "seal@1", takeoff: [], labor: [],
    contingency: 0, fees: 0, totals: {} };
  const two = await open({ blob: withSeal });
  P.clickEl(two, two.doc.querySelector('[data-section-tab="Seal"]'));
  two.api.go(2);
  out.seal = { card: drawn(two), onSeal: two.api.model() === two.api.root() ? "root" : "section" };
  P.clickEl(two, two.doc.querySelector('[data-section-tab="Epoxy"]'));
  two.api.go(2);
  out.seal.epoxyCard = drawn(two).present;

  console.log(JSON.stringify(out));
}

main().catch((e) => { console.error(e && e.stack || e); process.exit(1); });
