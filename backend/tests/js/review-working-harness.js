"use strict";
/* THE REVIEW STEP'S WORKING, ON THE REAL ESTIMATE PAGE (Hanz, 2026-10-19: "show the break down of any thing that has a total
 * ... Make sure to label the columns as price/sf, SF or LF etc.").
 *
 * js/polish-estimate.js, whole, booted the way polish-estimate-harness.js boots it. A Polish bid (the patch line, tooling, Dye,
 * Joint Filler, a crew, travel labor, Hotel and Per Diem, the taxes) and a Jayhawk-like Epoxy bid (5,482 SF of flake, 562 LF
 * of cove, primer, four guys for twelve days at $33) are each taken to the Review step. What is reported is the Review as the
 * page drew it, parsed into cards, rows and cells, beside the bid the chain priced and the numbers the modules answer, so
 * the Python side holds every figure on screen to the figure the chain used. Then the override boxes are typed in as a person
 * types, to see the working move with them.
 *
 * Usage: node review-working-harness.js <frontend-dir> <plan.json>   ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");
const Module = require("module");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const plan = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const B = require(path.join(ROOT, "js", "bid-model.js"));
const E = require(path.join(ROOT, "js", "epoxy-takeoff.js"));
const SEALFILE = path.join(ROOT, "js", "seal-takeoff.js");
const SEAL = fs.existsSync(SEALFILE) ? require(SEALFILE) : undefined;

const clone = (v) => JSON.parse(JSON.stringify(v));

function loadPrelude(file, exportNames) {
  const base = path.join(__dirname, file);
  const code = L.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in review-working-harness.js");
  const m = new Module(base, module);
  m.filename = base;
  m.paths = Module._nodeModulePaths(path.dirname(base));
  m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
  return m.exports;
}

const P = loadPrelude("polish-estimate-harness.js",
  ["build", "blob", "typeInto", "clickEl", "clickOn", "need", "MODEL", "ITEMS", "ASMS"]);

const flush = () => new Promise((r) => setImmediate(r));
const settle = async () => { for (let i = 0; i < 12; i++) await flush(); };
const html = (b, id) => b.doc.getElementById(id).innerHTML;

// ── reading the Review the page drew ───────────────────────────────────────────
const dec = (s) => String(s).replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&");
const text = (s) => dec(String(s).replace(/<[^>]*>/g, "")).replace(/\s+/g, " ").trim();

/** Every card (and the markup block) of a Review: its title, its header row's labels, and each row as { cls, cells } where a
 *  cell is { text, rv, mk }: what it says, the figures keyed data-rv inside it, and the one keyed data-mk, by key. */
function readReview(h) {
  const cards = [];
  String(h).split('<div data-rev="').slice(1).forEach((part) => {
    const key = part.slice(0, part.indexOf('"'));
    const title = text((/<div class="rev-h">([\s\S]*?)<button/.exec(part) || [])[1] || "");
    const head = (part.match(/<th[^>]*>[\s\S]*?<\/th>/g) || []).map(text);
    const rows = (part.match(/<tr[^>]*>[\s\S]*?<\/tr>/g) || []).filter((r) => /<td/.test(r)).map((r) => {
      const cls = (/^<tr(?: class="([^"]*)")?/.exec(r) || [])[1] || "";
      const cells = (r.match(/<td[^>]*>[\s\S]*?<\/td>/g) || []).map((c) => {
        const rv = {}, mk = {};
        (c.match(/data-rv="[^"]*">[^<]*</g) || []).forEach((m) => { const x = /data-rv="([^"]*)">([^<]*)</.exec(m); rv[x[1]] = dec(x[2]); });
        (c.match(/data-mk="[^"]*"[^>]*>[^<]*</g) || []).forEach((m) => { const x = /data-mk="([^"]*)"[^>]*>([^<]*)</.exec(m); mk[x[1]] = dec(x[2]); });
        const rates = {};
        (c.match(/data-mk(?:rate|pct)="[^"]*"[^>]*>[^<]*</g) || []).forEach((m) => { const x = /data-mk(?:rate|pct)="([^"]*)"[^>]*>([^<]*)</.exec(m); rates[x[1]] = dec(x[2]); });
        const inputs = (c.match(/<input[^>]*>/g) || []).length;
        return { text: text(c.replace(/<span class="mkused"[^>]*>[^<]*<\/span>/g, "")), rv: rv, mk: mk, rates: rates, inputs: inputs, cls: (/^<td(?: class="([^"]*)")?/.exec(c) || [])[1] || "" };
      });
      return { cls: cls, label: cells.length ? cells[0].text : "", cells: cells };
    });
    cards.push({ key: key, title: title, head: head, rows: rows });
  });
  return cards;
}

/** What each takeoff row of the section on show cost and its rate, asked of the page's own pricing (rowPrice). */
function rowFacts(api) {
  return api.model().takeoff.map((r, i) => {
    const p = api.rowPrice(r);
    return { i: i, name: r.assembly_name || r.item_name || "", measurement: B.num(r.measurement), unit: r.unit || "SF",
             total: p ? p.total : null, per_unit: p ? p.per_unit : null, priced: p ? p.priced_lines : 0 };
  });
}

/** The figures on screen NOW, read off the live nodes: a repaint changes a node's text and never the panel's markup, so the
 *  panel's innerHTML is the first paint and these are what a person sees after typing. */
function live(b) {
  const rv = {}, mk = {}, rates = {};
  b.doc.querySelectorAll("[data-rv]").forEach((el) => { rv[el.getAttribute("data-rv")] = el.textContent; });
  b.doc.querySelectorAll("[data-mk]").forEach((el) => { mk[el.getAttribute("data-mk")] = el.textContent; });
  b.doc.querySelectorAll("[data-mkrate]").forEach((el) => { rates[el.getAttribute("data-mkrate")] = el.textContent; });
  b.doc.querySelectorAll("[data-mkpct]").forEach((el) => { rates[el.getAttribute("data-mkpct")] = el.textContent; });
  return { rv: rv, mk: mk, rates: rates };
}
const money = (n) => B.money(n);
async function reviewOf(b) {
  b.api.go(2);
  await settle();
  const h = html(b, "panels");
  return { cards: readReview(h), bid: clone(b.api.activeBid()), rows: rowFacts(b.api), htmlWrites: b.dom.get("panels").htmlWrites, html: h };
}

// ── 1. A POLISH BID ────────────────────────────────────────────────────────────
function polishDraft() {
  const model = Object.assign(clone(P.MODEL), {
    profile: "polish-rev3@1",
    conditions: { local: true, prevailing_wage: false, taxable: true, remodel_tax: true, dye: true, joint_filler: true, remove_existing_jf: false },
    labor: [
      { id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 32.2 },
      { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 32.2 },
      { id: "travel", label: "Travel Labor", guys: 2, days: 3, rate: 33, unit: "hours" },
    ],
    travel: { lodging: { label: "Lodging", enabled: true, qty: "", qty_auto: true, rate: 70 },
              per_diem: { label: "Per Diem", enabled: true, qty: "", qty_auto: true, rate: 45 } },
  });
  return P.blob({ polish_estimate: model, county: "Johnson County, KS", county_remodel_rate: 0.0225 });
}

// ── 2. A JAYHAWK-LIKE EPOXY BID ────────────────────────────────────────────────
const norm = (t) => String(t).replace(/\s+/g, " ").trim();
const asmNamed = (n) => plan.assemblies.find((a) => norm(a.name) === norm(n));
const TRAVEL_ROW = { id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true, sort: -1, favorite: true,
  default_work_types: [], default_on: true };
const laborRows = [TRAVEL_ROW].concat(plan.labor.map((r) => Object.assign({}, r, { default_on: true, owner_email: "kyle@wetreadwell.com" })));
const calcRows = plan.labor_calc.map((r) => Object.assign({}, r, { days: null, rate: null, sf_per_day: null, crew: null }));

async function epoxyBid() {
  const draft = P.blob({
    work_type: "epoxy", system_1_sf: 5482, system_2_sf: "", cove_1_lf: 562, cove_2_lf: "",
    polish_estimate: { version: 2, conditions: { taxable: true, prevailing_wage: false, remodel_tax: false } },
  });
  const b = P.build({ blob: draft, asms: plan.assemblies, items: plan.items, labor: laborRows, laborCalc: calcRows });
  await b.api.init();
  await settle();
  const api = b.api;
  api.setAssembly(0, asmNamed("MACRO Flake Single Broadcast").name);
  api.setAssembly(1, asmNamed("Cove: Epoxy 4\"").name);
  const primer = asmNamed("Primer: MVP (@ 12 mils)");
  api.addPickedTakeoffRow({ kind: "asm", id: primer.id, name: primer.name });
  api.changed(true);
  api.go(1);
  const crew = api.model().labor.findIndex((r) => r.id === "epoxy-install");
  P.typeInto(b, '[data-lab="' + crew + '"][data-k="guys"]', "4");
  P.typeInto(b, '[data-lab="' + crew + '"][data-k="days"]', "12");
  P.typeInto(b, '[data-lab="' + crew + '"][data-k="rate"]', "33");
  api.changed(false);
  return b;
}

async function main() {
  const out = { rates: clone(B.RATES) };

  // Polish: the Review, and what the modules say the patch rate and tooling are.
  const pol = P.build({ blob: polishDraft() });
  await pol.api.init();
  await settle();
  out.polish = await reviewOf(pol);
  out.polish.expect = {
    patchRate: SEAL ? SEAL.unitPrice(P.ITEMS, "patchNew").cost : null,
    sf: B.takeoffSf(pol.api.model().takeoff),
    pwApplied: B.prevailingApplied(pol.api.model()),
    laborRows: pol.api.model().labor.map((r) => ({ id: r.id, label: r.label, guys: B.num(r.guys), days: B.num(r.days),
      perDay: r.unit === "hours" ? 1 : B.dayHours(r), rate: B.laborRateOf(r, 0), cost: B.laborCost(r, 0) })),
  };
  // The override boxes still type and reprice, and the working moves with them, in place.
  {
    const before = live(pol);
    const writes = pol.dom.get("panels").htmlWrites;
    P.typeInto(pol, '[data-adj="gp_pct"]', "25");
    pol.clock.fire();
    out.polish.adjust = {
      before: before, after: live(pol),
      noRebuild: pol.dom.get("panels").htmlWrites === writes, bid: clone(pol.api.activeBid()),
      typed: pol.doc.querySelector('[data-adj="gp_pct"]').value,
    };
    P.typeInto(pol, '[data-contingency]', "5000");
    out.polish.adjust.withContingency = { bid: clone(pol.api.activeBid()), live: live(pol) };
  }

  // Epoxy: Jayhawk-like.
  const ep = await epoxyBid();
  out.epoxy = await reviewOf(ep);
  out.epoxy.expect = {
    patchRate: E.unitPrice(plan.items, "patch").cost,
    sf: B.takeoffSf(ep.api.model().takeoff),
    laborRows: ep.api.model().labor.map((r) => ({ id: r.id, label: r.label, guys: B.num(r.guys), days: B.num(r.days),
      perDay: r.unit === "hours" ? 1 : B.dayHours(r), rate: B.laborRateOf(r, 0), cost: B.laborCost(r, 0) })),
  };
  {
    const writes = ep.dom.get("panels").htmlWrites;
    const before = rowFacts(ep.api);
    P.typeInto(ep, '[data-adj="supplier_pct"]', "20");
    ep.clock.fire();
    out.epoxy.discount = {
      noRebuild: ep.dom.get("panels").htmlWrites === writes, rowsBefore: before, rowsAfter: rowFacts(ep.api),
      live: live(ep), bid: clone(ep.api.activeBid()),
    };
    P.typeInto(ep, '[data-adj="ship_pct"]', "12");
    out.epoxy.shipping = { live: live(ep), bid: clone(ep.api.activeBid()) };
  }

  console.log(JSON.stringify(out));
}

main().catch((e) => { console.error(e && e.stack || e); process.exit(1); });
