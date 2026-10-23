"use strict";
/* "SPLIT INTO SEPARATE PROPOSALS" AND THE SCOPE BAR, ON THE REAL ESTIMATE PAGE (scope groups, tier A1; RJ, 2026-10-24): js/polish-estimate.js,
 * whole, booted the way polish-estimate-harness.js boots it, with the REAL js/bid-model.js beneath it.
 *
 * THE RACE THE AUDIT FOUND: after the server rewrites the parent draft (demoting it to one scope's content), this page's own autosave, still
 * holding the three-sheet copy, could PUT it straight back. The page here has an edit PENDING (its 600 ms timer armed) when Split is pressed, and
 * every fact is read off what it then did: the edit saved and flushed BEFORE the split was asked, the split asked of the version it read, the
 * server's copy adopted BEFORE the reload, and NO save of the old copy after the split, whatever fires (the pending timer, a later keystroke,
 * the page closing). The server's own refusal of such a save is test_scope_groups.py's.
 *
 * Usage: node scope-split-page-harness.js <frontend-dir>   ->  one line of JSON
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
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in scope-split-page-harness.js");
  const m = new Module(base, module);
  m.filename = base;
  m.paths = Module._nodeModulePaths(path.dirname(base));
  m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
  return m.exports;
}
const P = loadPrelude("polish-estimate-harness.js", ["build", "blob", "typeInto", "clickEl", "need", "MODEL"]);

const flush = () => new Promise((r) => setImmediate(r));
const settle = async () => { for (let i = 0; i < 16; i++) await flush(); };

const OFF = { taxable: true, prevailing_wage: false, remodel_tax: false, dye: false, joint_filler: false, remove_existing_jf: false, local: true };
const epoxy = (sf, extra) => Object.assign({
  layout: "epoxy", kind: "option", profile: "epoxy@1",
  takeoff: [{ assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: sf, unit: "SF" }],
  labor: [{ id: "installing", label: "Installing", guys: 3, days: 4, rate: 33 }], contingency: 0, fees: 0, totals: {},
  rates: { version: 1, profile: "epoxy@1", rates: {}, fees_default: null, notes: [] },
}, extra || {});

function threeSheets() {
  const m = Object.assign(clone(P.MODEL), { conditions: Object.assign({}, OFF), label: "Breakroom" });
  m.tabs = { Epoxy: epoxy(4000, { label: "Lab 1", seq: 1 }),
             Copy1: epoxy(2500, { sheet: "Epoxy", label: "Lab 2", source: "Epoxy", seq: 2 }) };
  return m;
}
const draft = (model, extra) => P.blob(Object.assign({ work_type: "polish", is_test: true, polish_estimate: clone(model),
  tab_opts: { Epoxy: { show_system: true, show_diff: false, is_option: true, show: true, price_mode: "total" },
              Copy1: { show_system: true, show_diff: false, is_option: true, show: true, price_mode: "total" } } }, extra || {}));

/** A page with the split's server: `answer` is what POST /split says. Everything it did is in `rec`. */
async function open(blob, answer) {
  let b = null;
  const seen = { order: [], splitBody: null, scopeBody: null, adopted: 0, reloads: 0, assigns: [], local: [] };
  b = P.build({
    blob: blob,
    tw: (store, rec) => ({
      readServerRow: async () => { seen.order.push("read"); return { data: clone(store.blob), version: "v-read" }; },
      useServerCopy: async () => { seen.order.push("adopt"); seen.adopted++; return true; },
      setLocalState: (partial, o) => { seen.local.push({ partial: clone(partial), opts: o || null }); store.blob = Object.assign(store.blob, clone(partial)); return store.blob; },
      flushState: async () => { seen.order.push("flush:" + rec.saves.length); rec.flushed++; return true; },
    }),
    location: { reload: () => { seen.order.push("reload"); seen.reloads++; }, assign: (u) => { seen.order.push("assign"); seen.assigns.push(String(u)); } },
    fetchHook: async (url, init) => {
      if (/\/split$/.test(url)) {
        seen.order.push("split:" + b.rec.saves.length);
        seen.splitBody = JSON.parse(init.body || "{}");
        const a = answer || { status: 200, body: { ok: true } };
        return { ok: a.status < 400, status: a.status, json: async () => clone(a.body) };
      }
      if (/\/scope$/.test(url)) {
        seen.scopeBody = JSON.parse(init.body || "{}");
        return { ok: true, status: 200, json: async () => ({ ok: true, group_id: "grp_x", label: seen.scopeBody.label }) };
      }
      return undefined;
    },
  });
  await b.api.init();
  await settle();
  return { b, seen };
}
const bar = (b) => b.doc.getElementById("scope-bar");
/** The bar's words: tags stripped to a fixed point (a removal can join two halves of one), spaces squeezed. */
const barText = (b) => {
  let s = String(bar(b).innerHTML), prev;
  do { prev = s; s = s.replace(/<[^>]*>/g, " "); } while (s !== prev);
  return s.replace(/\s+/g, " ").trim();
};
const press = async (b, act) => { P.clickEl(b, P.need(b, '[data-scope-act="' + act + '"]')); await settle(); };

const out = {};
async function section(name, fn) {
  try { out[name] = await fn(); } catch (e) { out[name] = { error: String((e && e.stack) || e) }; }
}

(async () => {
  await section("race", async () => {
    const { b, seen } = await open(draft(threeSheets()));
    const offered = { hidden: bar(b).hidden, text: barText(b) };
    // An edit nobody has waited for: the page's 600 ms save is armed when Split is pressed.
    P.typeInto(b, '[data-tk="0"][data-k="measurement"]', "20000");
    const armedBefore = b.clock.armed();
    await press(b, "split");
    const asked = barText(b);
    await press(b, "split-yes");
    const savesAtEnd = b.rec.saves.length;
    const saveBeforeSplit = clone(b.rec.saves[b.rec.saves.length - 1]);
    // Everything that could still save the old copy: the pending timer, a keystroke, the page closing.
    b.clock.fire();
    P.typeInto(b, '[data-tk="0"][data-k="measurement"]', "30000");
    b.clock.fire();
    b.win.fire("pagehide", {});
    const body = seen.splitBody || { children: [] };
    const pricedTabs = (saveBeforeSplit && saveBeforeSplit.priced_tabs) || [];
    return {
      offered: offered, armedBefore: armedBefore, asked: asked, order: seen.order, adopted: seen.adopted, reloads: seen.reloads,
      savesAfterSplit: b.rec.saves.length - savesAtEnd,
      editSaved: saveBeforeSplit && saveBeforeSplit.polish_estimate ? saveBeforeSplit.polish_estimate.takeoff[0].measurement : null,
      version: body.draft_version,
      children: body.children.map((c) => ({ tab: c.tab_id, label: c.label, work_type: c.data.work_type, base: c.data.base_tab_id,
        lump: c.data.computed_bid ? c.data.computed_bid.lump_sum : null, proposalLump: c.data.proposal_lump_sum,
        live: B.activeSections(c.data.polish_estimate).map((e) => [e.tab, e.kind]) })),
      sheetPrices: Object.fromEntries(pricedTabs.map((t) => [t.id, t.total])),
      note: barText(b),
    };
  });

  await section("refused", async () => {
    const { b, seen } = await open(draft(threeSheets()), { status: 409, body: { ok: false, code: "document_changed",
      error: "Nothing changed. This project was saved again after this page read it." } });
    await press(b, "split");
    await press(b, "split-yes");
    const note = barText(b);
    const before = b.rec.saves.length;
    P.typeInto(b, '[data-tk="0"][data-k="measurement"]', "21000");
    b.clock.fire();
    return { note: note, adopted: seen.adopted, reloads: seen.reloads, savesAgain: b.rec.saves.length - before };
  });

  await section("blocked", async () => {
    const m = threeSheets();
    m.tabs.Seal = { layout: "seal", kind: "option", profile: "seal@1", takeoff: [], labor: [], contingency: 0, fees: 0, totals: {}, seq: 3,
                    rates: { version: 1, profile: "seal@1", rates: {}, fees_default: null, notes: [] } };
    const { b } = await open(draft(m));
    const one = await open(draft(Object.assign(clone(P.MODEL), { conditions: Object.assign({}, OFF) })));
    return { text: barText(b), button: !!b.doc.querySelector('[data-scope-act="split"]'),
             oneSheetHidden: bar(one.b).hidden, oneSheetText: barText(one.b) };
  });

  await section("rename", async () => {
    const { b, seen } = await open(draft(threeSheets(), { scope_group: { id: "grp_x", label: "Breakroom" } }));
    const shown = barText(b);
    await press(b, "rename");
    const box = b.doc.getElementById("scope-label-box");
    box.value = "  Break   room ";
    b.doc.fire("input", { target: box });
    await press(b, "rename-save");
    return { shown: shown, body: seen.scopeBody, local: seen.local, after: barText(b) };
  });

  process.stdout.write(JSON.stringify(out) + "\n");
})();
