"use strict";
/* ITEM CATEGORIES (Hanz, 2026-10-27), EXECUTED: the Admin page's card, and the v2 estimate's Material step.
 *
 *   1. THE ADMIN CARD. js/admin.js's itemCategoriesPanelHtml (what the card draws) and itemCategoriesAfter (what
 *      one add / rename / remove / move sends to PUT /api/item-categories), lifted out of the real file and run.
 *   2. THE MATERIAL STEP. js/polish-estimate.js, whole, booted the way polish-estimate-harness.js boots it, with
 *      GET /api/library/items carrying `item_categories` the way main.py answers it. The rows are read back off
 *      the panel the page drew: which heading each card sits under, in what order, and each heading's subtotal,
 *      set beside the same rows priced by the real library-core with no page in it.
 *   3. NOTHING MOVES. The same bids are booted with and without categories, and the lump sum, the material, and
 *      every save the page wrote are compared: on the harness's own Polish job and, when a plan is given, on the
 *      Epoxy job priced off the library the seed script plans from Kyle's workbook.
 *
 * Usage: node item-categories-harness.js <frontend-dir> [<plan.json>]  ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");
const Module = require("module");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const PLAN = process.argv[3] ? JSON.parse(fs.readFileSync(process.argv[3], "utf8")) : null;
const B = require(path.join(ROOT, "js", "bid-model.js"));
const LIB = require(path.join(ROOT, "js", "library-core.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));
const flush = () => new Promise((r) => setImmediate(r));

// ── 1. the Admin card ────────────────────────────────────────────────────────────────────────────────────────
const adminSrc = L.read(path.join(ROOT, "js", "admin.js")).replace(/\r\n/g, "\n");
function liftAdmin(name) {
  const m = new RegExp("\\n    (?:async )?function " + name + "\\s*\\(").exec(adminSrc);
  if (!m) throw new Error(name + "() is gone from admin.js: rewrite this harness, don't stub it");
  const i = adminSrc.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < adminSrc.length; j++) {
    if (adminSrc[j] === "{") depth++;
    else if (adminSrc[j] === "}" && --depth === 0) return adminSrc.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name);
}
const admin = new Function("TWIcon", liftAdmin("itemCategoriesPanelHtml") + liftAdmin("itemCategoriesAfter") +
  "\nreturn { panel: itemCategoriesPanelHtml, after: itemCategoriesAfter };")(undefined);

// What GET /api/item-categories answers on a fresh box: the sheet's headings (backend/item_categories.py SEED).
const STORE = {
  ok: true, order: ["epoxy", "polish", "gyp", "seal", "leveling"],
  labels: { epoxy: "Epoxy", polish: "Polish", gyp: "Gyp", seal: "Seal", leveling: "Leveling" },
  work_types: {
    epoxy: [{ id: "epoxy-patch", name: "Patch" }, { id: "epoxy-liquids", name: "Epoxy Liquids" },
            { id: "epoxy-extras", name: "Extras" }, { id: "epoxy-cove", name: "Cove" }],
    polish: [{ id: "polish-patch", name: "Patch" }, { id: "polish-floor", name: "Floor" },
             { id: "polish-dye", name: "Dye" }, { id: "polish-joint-filler", name: "Joint Filler" }],
    gyp: [], seal: [], leveling: [],
  },
  seeded: true, updated_at: null, updated_by: null,
};

const out = {};
{
  const html = admin.panel(STORE, "Saved.");
  const blocks = (html.match(/data-ic-block="([^"]*)"/g) || []).map((x) => /"([^"]*)"/.exec(x)[1]);
  const namesOf = (wt) => {
    const at = html.indexOf('data-ic-block="' + wt + '"');
    const next = html.indexOf("data-ic-block=", at + 1);
    const chunk = html.slice(at, next === -1 ? html.length : next);
    return (chunk.match(/data-ic-act="rename"[^>]*value="([^"]*)"/g) || []).map((x) => /value="([^"]*)"/.exec(x)[1]);
  };
  const after = (act, wt, id, name) => admin.after(STORE, act, wt, id, name);
  const before = JSON.stringify(STORE);
  out.admin = {
    blocks: blocks,
    epoxy: namesOf("epoxy"), polish: namesOf("polish"), gyp: namesOf("gyp"),
    firstUpDisabled: /data-ic-act="up" data-ic-wt="epoxy" data-ic-id="epoxy-patch" disabled/.test(html),
    lastDownDisabled: /data-ic-act="down" data-ic-wt="epoxy" data-ic-id="epoxy-cove" disabled/.test(html),
    addBoxes: (html.match(/data-ic-new="/g) || []).length,
    saysUncategorized: /Removing a category leaves its materials\s+uncategorized/.test(html),
    saysSeeded: /headings on Kyle's sheet/.test(html),
    status: /id="ic-status"[^>]*>Saved\.</.test(html),
    emptyWtSays: /None yet/.test(html),
    escapes: admin.panel(Object.assign(clone(STORE), { work_types: Object.assign(clone(STORE.work_types),
      { gyp: [{ id: "gyp-x", name: '<b>"Bags"</b>' }] }) })).indexOf("<b>\"Bags\"</b>") === -1,
    failed: admin.panel(null, ""),
    // One edit each, as the PUT body.
    add: after("add", "gyp", "", "  Bags  "),
    addDup: after("add", "epoxy", "", "patch"),
    addBlank: after("add", "epoxy", "", "   "),
    rename: after("rename", "epoxy", "epoxy-patch", "Patch and Prep"),
    renameDup: after("rename", "epoxy", "epoxy-patch", "cove"),
    remove: after("remove", "polish", "polish-dye", ""),
    up: after("up", "epoxy", "epoxy-cove", ""),
    upAtTop: after("up", "epoxy", "epoxy-patch", ""),
    down: after("down", "polish", "polish-patch", ""),
    unknown: after("rename", "epoxy", "nope", "X"),
    storeUntouched: JSON.stringify(STORE) === before,
  };
}

// ── 2 and 3. the Material step ───────────────────────────────────────────────────────────────────────────────
function loadPrelude(file, exportNames) {
  const base = path.join(__dirname, file);
  const code = L.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in item-categories-harness.js");
  const m = new Module(base, module);
  m.filename = base;
  m.paths = Module._nodeModulePaths(path.dirname(base));
  m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
  return m.exports;
}
const P = loadPrelude("polish-estimate-harness.js", ["build", "blob", "typeInto", "MODEL", "ITEMS", "ASMS"]);

/** The page's /api/library/items answer, with or without the categories riding on it (main.py). */
function itemsHook(items, cats) {
  return async (url) => {
    if (!/\/api\/library\/items/.test(url)) return undefined;
    const body = { ok: true, items: clone(items) };
    if (cats !== undefined) body.item_categories = clone(cats);
    return { json: async () => body };
  };
}

/** Every heading the panel drew, in order, with the cards under it and its subtotal as shown. */
function groupsOn(html) {
  const out = [];
  const re = /<div class="tk-cat" data-cat-group="([^"]*)"><h3 class="tk-cat-h">([^<]*)<\/h3><span class="tk-cat-sub">Subtotal <b data-cat-sub="([^"]*)">([^<]*)<\/b>/g;
  let m;
  while ((m = re.exec(html))) out.push({ id: m[1], name: m[2], keys: m[3], shown: m[4], at: m.index });
  // Which cards sit under each heading, read off the order they were drawn in.
  const cards = [];
  const cre = /data-row-card="(\d+)"/g;
  while ((m = cre.exec(html))) cards.push({ i: Number(m[1]), at: m.index });
  out.forEach((g, k) => {
    const end = k + 1 < out.length ? out[k + 1].at : Infinity;
    g.cards = cards.filter((c) => c.at > g.at && c.at < end).map((c) => c.i);
    delete g.at;
  });
  return { groups: out, cards: cards.map((c) => c.i) };
}
const money = (t) => Number(String(t).replace(/[^0-9.\-]/g, ""));

// The Polish job: the harness's own three rows, plus one MATERIAL row, so both kinds of row are grouped.
const ITEMS = clone(P.ITEMS).map((it) => it.id === "i4"
  ? Object.assign(it, { material_categories: { polish: "polish-patch", epoxy: "epoxy-extras" } }) : it);
const ASMS = clone(P.ASMS).map((a) => {
  if (a.id === "a1") return Object.assign(a, { category: "Floor" });
  if (a.id === "a5") return Object.assign(a, { category: "  floor " });     // case and spacing ignored
  if (a.id === "a2") return Object.assign(a, { category: "Cove" });         // a heading of EPOXY's, not Polish's
  return a;
});
function polishBlob() {
  const m = clone(P.MODEL);
  m.takeoff.push({ kind: "item", item_id: "i4", item_name: "Densifier", measurement: 3000, unit: "SF" });
  return P.blob({ polish_estimate: m });
}

async function boot(opts) {
  const b = P.build(Object.assign({ asms: ASMS, items: ITEMS }, opts));
  await b.api.init();
  await flush();
  return b;
}
const panel = (b) => b.dom.get("panels").innerHTML;

/** What a bid comes to and what the page saved, after one edit that reprices it (typing a measurement). */
async function priceOf(b) {
  P.typeInto(b, '[data-tk="0"][data-k="measurement"]', "14000");
  b.clock.fire();
  await flush();
  const bid = b.api.activeBid();
  const saved = b.rec.saves[b.rec.saves.length - 1] || {};
  return { total: bid.total, material: b.api.materialTotal(), lump: saved.computed_bid && saved.computed_bid.lump_sum,
           saved: b.rec.saves.length,
           saves: JSON.stringify(b.rec.saves), takeoff: JSON.stringify(b.api.model().takeoff) };
}

async function main() {
  // ── grouped ──
  const g = await boot({ blob: polishBlob(), fetchHook: itemsHook(ITEMS, STORE) });
  const drawn = groupsOn(panel(g));
  const rowTotal = (i) => {
    const r = g.api.model().takeoff[i];
    return r.item_id ? LIB.priceLine({ item_id: r.item_id }, ITEMS, B.num(r.measurement)).cost
      : LIB.priceAssembly(ASMS.filter((a) => a.id === r.assembly_id)[0], ITEMS, B.num(r.measurement)).total;
  };
  const shownCost = (b, i) => money(b.doc.querySelector('[data-cost-for="' + i + '"]').textContent);
  out.grouped = {
    groups: drawn.groups.map((x) => ({ id: x.id, name: x.name, keys: x.keys, cards: x.cards,
      shown: money(x.shown), byCards: x.cards.reduce((s, i) => s + shownCost(g, i), 0),
      byHand: x.cards.reduce((s, i) => s + rowTotal(i), 0) })),
    cards: drawn.cards, rows: g.api.model().takeoff.length,
    moneyAutoOf: drawn.groups.map((x) => g.api.moneyAuto(x.cards.reduce((s, i) => s + rowTotal(i), 0))),
    shownText: drawn.groups.map((x) => x.shown),
    matTotalStill: /data-mat-total/.test(panel(g)),
  };
  // A typed measurement moves the heading's subtotal in place (repaintNumbers), without a panel rebuild.
  const before = g.dom.get("panels").htmlWrites;
  P.typeInto(g, '[data-tk="0"][data-k="measurement"]', "20000");
  const floor = g.doc.querySelector('[data-cat-sub="0,2"]');
  out.grouped.repaint = {
    rebuilt: g.dom.get("panels").htmlWrites !== before,
    shown: floor ? floor.textContent : null,
    expected: g.api.moneyAuto(rowTotal(0) + rowTotal(2)),
    card0: g.doc.querySelector('[data-cost-for="0"]').textContent,
  };

  // ── the Epoxy section reads ITS OWN headings: the same material is under Extras there ──
  // (and a work type with no headings at all draws the rows as one list, exactly as before)
  const flat = await boot({ blob: polishBlob(),
    fetchHook: itemsHook(ITEMS, Object.assign(clone(STORE), { work_types: Object.assign(clone(STORE.work_types), { polish: [] }) })) });
  out.flatWhenNone = { groups: groupsOn(panel(flat)).groups.length, cards: groupsOn(panel(flat)).cards };
  const none = await boot({ blob: polishBlob(), fetchHook: itemsHook(ITEMS, undefined) });
  out.flatWhenAbsent = { groups: groupsOn(panel(none)).groups.length, cards: groupsOn(panel(none)).cards };
  // A heading that has been removed: its material falls to Other.
  const removed = clone(STORE); removed.work_types.polish = removed.work_types.polish.filter((c) => c.id !== "polish-patch");
  const rm = await boot({ blob: polishBlob(), fetchHook: itemsHook(ITEMS, removed) });
  out.removedHeading = groupsOn(panel(rm)).groups.map((x) => [x.name, x.cards]);
  // Renamed (same id): the material follows the new name with no write to it.
  const renamed = clone(STORE); renamed.work_types.polish[0].name = "Patch and Prep";
  const rn = await boot({ blob: polishBlob(), fetchHook: itemsHook(ITEMS, renamed) });
  out.renamedHeading = groupsOn(panel(rn)).groups.map((x) => [x.name, x.cards]);
  // Reordered in the Admin list: the headings follow that order.
  const reordered = clone(STORE); reordered.work_types.polish.reverse();
  const ro = await boot({ blob: polishBlob(), fetchHook: itemsHook(ITEMS, reordered) });
  out.reorderedHeading = groupsOn(panel(ro)).groups.map((x) => x.name);
  // A SAVED bid as the server hands it back (jsonb sorts every object's keys): the same headings.
  const rl = await boot({ blob: polishBlob(), reloaded: true, fetchHook: itemsHook(ITEMS, STORE) });
  out.reloaded = groupsOn(panel(rl)).groups.map((x) => [x.name, x.cards]);

  // ── 3. nothing moves: the same edit, with and without the headings ──
  const withCats = await priceOf(await boot({ blob: polishBlob(), fetchHook: itemsHook(ITEMS, STORE) }));
  const withoutCats = await priceOf(await boot({ blob: polishBlob(), fetchHook: itemsHook(ITEMS, undefined) }));
  out.polishTotals = { withCats, withoutCats };

  if (PLAN) out.epoxyTotals = await epoxyTotals();
  console.log(JSON.stringify(out));
}

/** The Epoxy job of epoxy-page-harness.js, on the library the seed plans, with and without the headings. */
async function epoxyTotals() {
  const asms = clone(PLAN.assemblies).map((a) => /^Cove/.test(a.name) ? Object.assign(a, { category: "Cove" }) : a);
  const items = clone(PLAN.items).map((it, k) => k % 3 === 0
    ? Object.assign(it, { material_categories: { epoxy: "epoxy-liquids" } }) : it);
  const norm = (t) => String(t).replace(/\s+/g, " ").trim();
  const flake = asms.find((a) => norm(a.name) === "MACRO Flake Single Broadcast");
  const cove = asms.find((a) => norm(a.name) === norm('Cove: Epoxy 4"'));
  const TRAVEL = { id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true, sort: -1, favorite: true,
                   default_work_types: [], default_on: true };
  const labor = [TRAVEL].concat(PLAN.labor.map((r) => Object.assign({}, r, { default_on: true })));
  const calc = PLAN.labor_calc.map((r) => Object.assign({}, r, { days: null, rate: null, sf_per_day: null, crew: null }));
  const draft = () => P.blob({ work_type: "epoxy", system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "",
    polish_estimate: { version: 2, conditions: { taxable: true, prevailing_wage: false, remodel_tax: false } } });
  async function run(cats) {
    const b = P.build({ blob: draft(), asms: asms, items: items, labor: labor, laborCalc: calc,
                        fetchHook: itemsHook(items, cats) });
    await b.api.init();
    await flush();
    b.api.setAssembly(0, flake.name);
    b.api.setAssembly(1, cove.name);
    b.api.changed(true);
    b.clock.fire();
    await flush();
    const saved = b.rec.saves[b.rec.saves.length - 1] || {};
    return { groups: groupsOn(panel(b)).groups.map((x) => [x.name, x.cards]), total: b.api.activeBid().total,
             lump: saved.proposal_lump_sum, computed: saved.computed_bid && saved.computed_bid.lump_sum,
             saves: JSON.stringify(b.rec.saves) };
  }
  return { withCats: await run(STORE), withoutCats: await run(undefined) };
}

main().catch((err) => { console.error(err && err.stack || err); process.exit(1); });
