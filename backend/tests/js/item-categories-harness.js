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
    saysFixedLines: /Epoxy's patch is a flat\s+charge on the whole area/.test(html) && /Joint Filler and Dye cards sit under/.test(html),
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
  // Each heading is its own container (2026-10-29): the band (name, subtotal) on top, its cards in its body.
  const re = /<section class="tk-cat" data-cat-group="([^"]*)" data-cat-tone="([^"]*)" aria-label="([^"]*)"><div class="tk-cat-head"><h3 class="tk-cat-h">([^<]*)<\/h3><span class="tk-cat-sub">Subtotal <b data-cat-sub="([^"]*)">([^<]*)<\/b><\/span><\/div><div class="tk-cat-body">/g;
  let m;
  while ((m = re.exec(html))) {
    out.push({ id: m[1], tone: m[2], label: m[3], name: m[4], keys: m[5], shown: m[6], at: m.index,
               end: html.indexOf("</div></section>", m.index) });
  }
  // Every container the page opened, matched or not: one this regex misses is a heading drawn some other way.
  const opened = (html.match(/<section class="tk-cat"/g) || []).length;
  // Which cards sit under each heading, read off the order they were drawn in.
  const cards = [];
  const cre = /data-row-card="(\d+)"/g;
  while ((m = cre.exec(html))) cards.push({ i: Number(m[1]), at: m.index });
  // ...and the condition cards (Joint Filler, Dye: their .sub line; Remove Existing: its switch), by key.
  const conds = [];
  const kre = /data-condfig="([a-z_]+)\.sub"|<div class="tk cond[^"]*">[\s\S]*?data-cond="([a-z_]+)"/g;
  while ((m = kre.exec(html))) conds.push({ key: m[1] || m[2], at: m.index });
  // A card belongs to a heading only while it is INSIDE that heading's container (before its </section>).
  const inside = (c) => out.some((g) => c.at > g.at && c.at < g.end);
  const loose = out.length ? cards.filter((c) => !inside(c)).map((c) => c.i)
    .concat(conds.filter((c) => !inside(c)).map((c) => c.key)) : [];
  out.forEach((g) => {
    g.cards = cards.filter((c) => c.at > g.at && c.at < g.end).map((c) => c.i);
    g.conds = conds.filter((c) => c.at > g.at && c.at < g.end).map((c) => c.key);
    delete g.at; delete g.end;
  });
  return { groups: out, cards: cards.map((c) => c.i), conds: conds.map((c) => c.key), loose: loose, opened: opened };
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
    groups: drawn.groups.map((x) => ({ id: x.id, name: x.name, keys: x.keys, cards: x.cards, conds: x.conds,
      shown: money(x.shown), byCards: x.cards.reduce((s, i) => s + shownCost(g, i), 0),
      byHand: x.cards.reduce((s, i) => s + rowTotal(i), 0) })),
    cards: drawn.cards, conds: drawn.conds, rows: g.api.model().takeoff.length,
    moneyAutoOf: drawn.groups.map((x) => g.api.moneyAuto(x.cards.reduce((s, i) => s + rowTotal(i), 0))),
    shownText: drawn.groups.map((x) => x.shown),
    matTotalStill: /data-mat-total/.test(panel(g)),
    // Each heading its own container, coloured by its place in the Admin list (2026-10-29).
    tones: drawn.groups.map((x) => x.tone), labels: drawn.groups.map((x) => x.label),
    loose: drawn.loose, opened: drawn.opened,
    subtotalSum: drawn.groups.reduce((s, x) => s + money(x.shown), 0), materialTotal: g.api.materialTotal(),
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
  out.removedTones = groupsOn(panel(rm)).groups.map((x) => [x.name, x.tone]);
  // Renamed (same id): the material follows the new name with no write to it.
  const renamed = clone(STORE); renamed.work_types.polish[0].name = "Patch and Prep";
  const rn = await boot({ blob: polishBlob(), fetchHook: itemsHook(ITEMS, renamed) });
  out.renamedHeading = groupsOn(panel(rn)).groups.map((x) => [x.name, x.cards]);
  // Reordered in the Admin list: the headings follow that order.
  const reordered = clone(STORE); reordered.work_types.polish.reverse();
  const ro = await boot({ blob: polishBlob(), fetchHook: itemsHook(ITEMS, reordered) });
  out.reorderedHeading = groupsOn(panel(ro)).groups.map((x) => x.name);
  out.reorderedTones = groupsOn(panel(ro)).groups.map((x) => [x.name, x.tone]);
  // A SAVED bid as the server hands it back (jsonb sorts every object's keys): the same headings.
  const rl = await boot({ blob: polishBlob(), reloaded: true, fetchHook: itemsHook(ITEMS, STORE) });
  out.reloaded = groupsOn(panel(rl)).groups.map((x) => [x.name, x.cards]);
  out.reloadedTones = groupsOn(panel(rl)).groups.map((x) => [x.name, x.tone]);

  // ── THE CONDITION CARDS, on and priced: each under its heading, its cost in that heading's subtotal ──
  {
    const on = (b) => { const m = b.api.model(); m.conditions.joint_filler = true; m.conditions.dye = true;
                         b.api.renderPanel(); };
    const read = (b) => {
      const d = groupsOn(panel(b));
      const cost = (key) => money(b.doc.querySelector('[data-condfig="' + key + '.cost"]').textContent);
      return { groups: d.groups.map((x) => ({ name: x.name, cards: x.cards, conds: x.conds, shown: money(x.shown),
        byCards: x.cards.reduce((sum, i) => sum + money(b.doc.querySelector('[data-cost-for="' + i + '"]').textContent), 0) +
          x.conds.filter((k) => k !== "remove_existing_jf").reduce((sum, k) => sum + cost(k), 0) })),
        jf: cost("joint_filler"), dye: cost("dye"), conds: d.conds };
    };
    const c = await boot({ blob: polishBlob(), fetchHook: itemsHook(ITEMS, STORE) });
    on(c);
    out.condCards = read(c);
    { const d = groupsOn(panel(c)); out.condCards.loose = d.loose;
      out.condCards.subtotalSum = d.groups.reduce((s, x) => s + money(x.shown), 0);
      out.condCards.materialTotal = c.api.materialTotal(); }
    // A typed measurement moves the condition card's subtotal in place, as it moves the card.
    const before = c.dom.get("panels").htmlWrites;
    P.typeInto(c, '[data-tk="0"][data-k="measurement"]', "20000");
    const jfSub = c.doc.querySelector('[data-cat-sub="c:joint_filler,c:remove_existing_jf"]');
    out.condCards.repaint = { rebuilt: c.dom.get("panels").htmlWrites !== before, shown: jfSub ? jfSub.textContent : null,
      card: c.doc.querySelector('[data-condfig="joint_filler.cost"]').textContent };
    // The reserved Dye material filed under Patch on the Items tab: the Dye card goes with it.
    const filedItems = ITEMS.concat([{ id: "dye", name: "Dye", unit: "SF", buy_qty: 1, unit_cost: 0.14, coverage: 1,
      material_categories: { polish: "polish-patch" } }]);
    const f = await boot({ blob: polishBlob(), items: filedItems, fetchHook: itemsHook(filedItems, STORE) });
    on(f);
    out.condCards.dyeFiled = read(f);
    // Off the root (an Epoxy section) the cards are not drawn at all, so nothing is added there.
  }

  // ── ASSEMBLIES WITH NO SCOPE HEADING: the heading their materials agree on ──
  {
    const raw = clone(P.ASMS);   // no Scope that names a heading, as the seeded library has
    const filed = (map) => clone(P.ITEMS).map((it) => map[it.id] ? Object.assign(it, { material_categories: { polish: map[it.id] } }) : it);
    const agree = filed({ i1: "polish-floor", i3: "polish-floor", i4: "polish-patch" });
    const a = await boot({ blob: polishBlob(), asms: raw, items: agree, fetchHook: itemsHook(agree, STORE) });
    // a1 (i1, i3) both Floor; a5 (i4) and the Densifier row Patch; a2 (i2, filed nowhere) Other.
    out.derived = groupsOn(panel(a)).groups.filter((x) => x.cards.length).map((x) => [x.name, x.cards]);
    const split = filed({ i1: "polish-floor", i3: "polish-patch", i4: "polish-patch" });
    const b = await boot({ blob: polishBlob(), asms: raw, items: split, fetchHook: itemsHook(split, STORE) });
    // a1's two materials disagree: no heading, so Other.
    out.derivedSplit = groupsOn(panel(b)).groups.filter((x) => x.cards.length).map((x) => [x.name, x.cards]);
  }

  // ── 3. nothing moves: the same edit, with and without the headings ──
  const withCats = await priceOf(await boot({ blob: polishBlob(), fetchHook: itemsHook(ITEMS, STORE) }));
  const withoutCats = await priceOf(await boot({ blob: polishBlob(), fetchHook: itemsHook(ITEMS, undefined) }));
  out.polishTotals = { withCats, withoutCats };

  if (PLAN) out.epoxyTotals = await epoxyTotals();
  console.log(JSON.stringify(out));
}

/** The Epoxy job of epoxy-page-harness.js, on the library the seed plans, with and without the headings. */
async function epoxyTotals() {
  // THE SEEDED ASSEMBLIES, UNTOUCHED: their Scope is the division ("Epoxy"), which names no heading, so a
  // heading can only come from their materials. Each one's materials are filed on the Items tab instead.
  const asms = clone(PLAN.assemblies);
  const norm = (t) => String(t).replace(/\s+/g, " ").trim();
  const flake = asms.find((a) => norm(a.name) === "MACRO Flake Single Broadcast");
  const cove = asms.find((a) => norm(a.name) === norm('Cove: Epoxy 4"'));
  const fileLines = (asm, id) => (it) => asm.lines.some((l) => l.item_id === it.id)
    ? Object.assign(it, { material_categories: { epoxy: id } }) : it;
  const items = clone(PLAN.items).map(fileLines(flake, "epoxy-liquids")).map(fileLines(cove, "epoxy-cove"));
  // The flake with ONE of its materials filed elsewhere: its materials disagree, so it has no heading.
  const odd = flake.lines[flake.lines.length - 1].item_id;
  const split = clone(items).map((it) => it.id === odd ? Object.assign(it, { material_categories: { epoxy: "epoxy-extras" } }) : it);
  const TRAVEL = { id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true, sort: -1, favorite: true,
                   default_work_types: [], default_on: true };
  const labor = [TRAVEL].concat(PLAN.labor.map((r) => Object.assign({}, r, { default_on: true })));
  const calc = PLAN.labor_calc.map((r) => Object.assign({}, r, { days: null, rate: null, sf_per_day: null, crew: null }));
  const draft = () => P.blob({ work_type: "epoxy", system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "",
    polish_estimate: { version: 2, conditions: { taxable: true, prevailing_wage: false, remodel_tax: false } } });
  async function run(cats, lib) {
    lib = lib || items;
    const b = P.build({ blob: draft(), asms: asms, items: lib, labor: labor, laborCalc: calc,
                        fetchHook: itemsHook(lib, cats) });
    await b.api.init();
    await flush();
    b.api.setAssembly(0, flake.name);
    b.api.setAssembly(1, cove.name);
    b.api.changed(true);
    b.clock.fire();
    await flush();
    const saved = b.rec.saves[b.rec.saves.length - 1] || {};
    return { groups: groupsOn(panel(b)).groups.map((x) => [x.name, x.cards]),
             tones: groupsOn(panel(b)).groups.map((x) => [x.name, x.tone]), loose: groupsOn(panel(b)).loose,
             total: b.api.activeBid().total,
             lump: saved.proposal_lump_sum, computed: saved.computed_bid && saved.computed_bid.lump_sum,
             saves: JSON.stringify(b.rec.saves) };
  }
  return { withCats: await run(STORE), withoutCats: await run(undefined),
           split: (await run(STORE, split)).groups,
           // Nothing filed anywhere: a lone Other over the whole takeoff separates nothing, so it is drawn flat.
           noneFiled: (await run(STORE, clone(PLAN.items))).groups,
           scopes: [flake.category, cove.category] };
}

main().catch((err) => { console.error(err && err.stack || err); process.exit(1); });
