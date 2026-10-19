"use strict";
/* THE SHEETS PANEL ON THE REAL ESTIMATE PAGE: js/polish-estimate.js, whole, booted the way polish-estimate-harness.js boots it, with the
 * REAL js/bid-model.js, js/library-core.js, js/price-lines-core.js and js/epoxy-takeoff.js beneath it.
 *
 * Phase 3 of the v2 Sheets work: the strip of section buttons and the "+ Add option" bar became one floating panel, drawn on every
 * bid. Every fact below is read off the page after it ran: the markup it drew, the model it held, what it wrote to the draft, what the
 * next save said. A price is set beside the same section priced by hand with no page in it. Nothing is a source assertion except the CSS,
 * which a headless run cannot lay out, and that is read as the rules that make it float and drop inline.
 *
 * A section that throws reports `{ error }` instead of crashing, so a tree without the code fails an assertion with a reason.
 *
 * Usage: node sheets-panel-harness.js <frontend-dir>   ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");
const Module = require("module");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const B = require(path.join(ROOT, "js", "bid-model.js"));
const LIB = require(path.join(ROOT, "js", "library-core.js"));
const X = require(path.join(ROOT, "js", "epoxy-takeoff.js"));
const PRICE = require(path.join(ROOT, "js", "price-lines-core.js"));
const GYP = require(path.join(ROOT, "js", "gyp-takeoff.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));

function loadPrelude(file, exportNames) {
  const base = path.join(__dirname, file);
  const code = L.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in sheets-panel-harness.js");
  const m = new Module(base, module);
  m.filename = base;
  m.paths = Module._nodeModulePaths(path.dirname(base));
  m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
  return m.exports;
}

const P = loadPrelude("polish-estimate-harness.js", ["build", "blob", "typeInto", "clickEl", "changeTo", "need", "MODEL", "ITEMS", "ASMS"]);

const flush = () => new Promise((r) => setImmediate(r));
const settle = async () => { for (let i = 0; i < 12; i++) await flush(); };
const html = (b, id) => b.doc.getElementById(id).innerHTML;
const text = (b, id) => b.doc.getElementById(id).textContent;
const money = (n) => "$" + Math.round(n).toLocaleString("en-US");
const last = (l) => l[l.length - 1];

// Dye and joint filler are off, so the Polish root's material is its takeoff alone and the hand pricing below is the whole of it.
const OFF = { taxable: true, prevailing_wage: false, remodel_tax: false, dye: false, joint_filler: false, remove_existing_jf: false, local: true };
const polishModel = (extra) => Object.assign(clone(P.MODEL), { conditions: Object.assign({}, OFF) }, extra || {});
const EPOXY_NOTES = ["Soft costs: the rule filed on the Markups page is blank, so the built-in rate is charged."];
const epoxySection = (kind, sf) => ({
  layout: "epoxy", kind: kind, profile: "epoxy@1",
  takeoff: [{ assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: sf === undefined ? 4000 : sf, unit: "SF" }],
  labor: [{ id: "installing", label: "Installing", guys: 3, days: 4, rate: 33 }], contingency: 0, fees: 0, totals: {},
  rates: { version: 1, profile: "epoxy@1", rates: {}, fees_default: null, notes: EPOXY_NOTES.slice() },
});
const draft = (model, extra) => P.blob(Object.assign({ work_type: "polish", polish_sf: 17500, polish_estimate: clone(model) }, extra || {}));

async function open(blob, extra) {
  const b = P.build(Object.assign({ blob: blob }, extra || {}));
  await b.api.init();
  await settle();
  return b;
}

/** An Epoxy section priced WITHOUT THE PAGE: the engine's epoxy profile over the library, from a saved model. */
function epoxyByHand(model, tab) {
  return B.priceSection(model, tab, {
    material: (e) => {
      const t = e.section.takeoff;
      const r = X.sectionMaterial(t, {
        items: P.ITEMS, sf: B.takeoffSf(t), pool: B.poolsPacks(e.section),
        rowPrice: (row) => { const a = P.ASMS.find((x) => x.id === row.assembly_id); return a ? LIB.priceAssembly(a, P.ITEMS, B.num(row.measurement)) : null; },
      });
      return { material: r.material, tooling: r.tooling };
    },
  });
}

/** How a quote mark in a sheet's id (Gyp (USG 1-8")) reads in the panel's markup, which is what the stub's selector matcher compares. */
const attr = (s) => String(s).replace(/"/g, "&quot;");
/** ...and back: what a browser hands the page. */
const unattr = (s) => String(s).replace(/&quot;/g, '"');
const rowsOf = (h) => (h.match(/data-sh-row="([^"]*)"/g) || []).map((s) => unattr(/"([^"]*)"/.exec(s)[1]));
const tabsOf = (h) => (h.match(/data-section-tab="([^"]*)"/g) || []).map((s) => unattr(/"([^"]*)"/.exec(s)[1]));
const openTab = (h) => { const m = /data-section-tab="([^"]*)"[^>]*aria-current="true"/.exec(h); return m ? unattr(m[1]) : null; };
const sel = (act, tab) => '[data-sh-act="' + act + '"]' + (tab === undefined ? "" : '[data-sh-tab="' + attr(tab) + '"]');
const click = (b, selector) => P.clickEl(b, P.need(b, selector));
/** A press on a control that may not be there. A break that removes a control must change a FACT the section reads, never crash the section:
 *  test_the_checks_go_red counts a crash as no fact noticed, so every step after the first thing a break can remove presses through these. */
const clickIf = (b, selector) => { const el = b.doc.querySelector(selector); if (el) P.clickEl(b, el); return !!el; };
const textIf = (b, selector) => { const el = b.doc.querySelector(selector); return el ? el.textContent : null; };
const openSheet = (b, tab) => click(b, '[data-section-tab="' + attr(tab) + '"]');
/** What the browser sends when a radio is picked: a change event on it. */
function pick(b, selector) { const el = P.need(b, selector); b.doc.fire("change", { target: el }); return el; }
function typeName(b, tab, value) { const el = P.need(b, '[data-sh-name="' + tab + '"]'); el.value = value; b.doc.fire("input", { target: el }); return el; }
function key(b, tab, k) {
  const el = P.need(b, '[data-sh-name="' + tab + '"]');
  let prevented = false;
  b.doc.fire("keydown", { target: el, key: k, preventDefault() { prevented = true; } });
  return prevented;
}
const panel = (b) => html(b, "sheets-panel");
const hasExcelHint = (h) => /The Excel download does not include them/.test(h);
/** The words of a base change waiting for its yes, read out of the row that holds them. */
const confirmOf = (h) => { const m = /<div class="sh-confirm"[^>]*><b>([^<]*)<\/b><p>([^<]*)<\/p>/.exec(h); return m ? { title: m[1], body: m[2] } : null; };
/** The model the page holds NOW: the debounced save is flushed and the model is read back out of it. (api.state() is the blob the page
 *  opened on, and api.model() is the sheet on show, so neither is the whole bid after an edit.) */
const modelOf = (b) => { b.clock.fire(); return clone(last(b.rec.saves.filter((x) => x.polish_estimate)).polish_estimate); };
/** Where the open sheet's bar ends in the panel's markup: at the line under it (the note about copies, or the hint on a one-sheet bid), else at
 *  the end of the markup. The legend line that used to stand there is gone, so a bar can be the last thing in the panel. */
const barEnd = (h, from) => { const ends = ['<p class="sh-hint"', '<p class="sh-empty"'].map((s) => h.indexOf(s, from)).filter((i) => i >= 0); return ends.length ? Math.min.apply(null, ends) : h.length; };
/** Every base radio in the markup, as the tags themselves. */
const radioTags = (h) => h.match(/<input type="radio" class="sh-radio"[^>]*>/g) || [];
/** Everything the bar says about one sheet: its TAB (the strip's <li>), the base change waiting on it, and, when it is the open sheet, its
 *  bar (row 2). The strip and the bar are two blocks now, so the three are joined here and every fact below reads them as it always did. */
const rowHtml = (b, tab) => {
  const h = panel(b), a = attr(tab);
  const stop = (from) => { const ends = ['<div class="sh-open"', '<p class="sh-hint"', '<p class="sh-empty"'].map((s) => h.indexOf(s, from)).filter((i) => i >= 0); return ends.length ? Math.min.apply(null, ends) : h.length; };
  let out = "";
  const at = h.indexOf('data-sh-row="' + a + '"');
  if (at >= 0) out += h.slice(at, h.indexOf("</li>", at));
  const cf = h.indexOf('data-sh-confirm="' + a + '"');
  if (cf >= 0) { const from = h.lastIndexOf("<div", cf); out += h.slice(from, stop(cf)); }
  const op = h.indexOf('data-sh-open="' + a + '"');
  if (op >= 0) out += h.slice(op, barEnd(h, op));
  return out;
};
const stripTags = (s) => s.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
/** What the page says is on show: the open tab's name and the open sheet's bar, as words. (It was the "Open sheet" line above the step rail.) */
const nowOf = (b) => {
  const h = panel(b);
  const t = /aria-current="true"[^>]*><span class="sh-nm">([^<]*)/.exec(h);
  const o = h.indexOf('class="sh-open"');
  return ((t ? unattr(t[1]) : "") + " " + (o >= 0 ? stripTags(h.slice(o, barEnd(h, o))) : "")).trim();
};
const sumOf = (b, tab) => ((/class="sh-sum[^"]*">([^<]*)(?:<b>([^<]*)<\/b>)?/.exec(rowHtml(b, tab))) || []).slice(1, 3).filter(Boolean).join(" ").replace(/\s+/g, " ").trim();

async function main() {
  const out = {};
  const sections = [
    ["list", list], ["copy", copy], ["add", add], ["seal", seal], ["baseSwitch", baseSwitch], ["baseTravel", baseTravel], ["combined", combined], ["deleting", deleting],
    ["renaming", renaming], ["options", options], ["reopen", reopen], ["unreadable", unreadable], ["focus", focus], ["markup", markup], ["floating", floating],
    ["gypPreset", gypPreset], ["limit", limit], ["sealMode", sealMode], ["demote", demote], ["resets", resets], ["unstated", unstated], ["hiddenOption", hiddenOption],
    ["stripKeeps", stripKeeps], ["stickyHead", stickyHead],
  ];
  for (const [name, fn] of sections) {
    try { out[name] = await fn(); } catch (e) { out[name] = { error: String(e && e.stack || e) }; }
  }
  return out;
}

// ── 1. the panel lists every sheet, prices them, and clicking one opens it ──────────────────────────────
async function list() {
  const copyOf = B.copySection(polishModel(), "Polish", {});
  const m = copyOf.model;
  m.tabs.Copy1.takeoff[0].measurement = 7777;               // the copy is told apart from the root by its own area
  m.tabs.Seal = { layout: "seal", kind: "option", profile: "seal@1", takeoff: [], labor: [], contingency: 0, fees: 0, totals: {},
    rates: { version: 1, profile: "seal@1", rates: {}, fees_default: null, notes: EPOXY_NOTES.slice() } };
  const b = await open(draft(m, { tab_opts: copyOf.patch.tab_opts }));
  const h0 = panel(b);
  const bids = b.api.sectionBids();
  const before = { open: openTab(h0), tabs: tabsOf(h0), rows: rowsOf(h0), now: nowOf(b),
                   radios: (h0.match(/data-sh-base="/g) || []).length };
  click(b, '[data-section-tab="Copy1"]');
  const h1 = panel(b);
  return {
    before: before, after: { open: openTab(h1), now: nowOf(b), takeoffOnShow: b.api.model().takeoff[0].measurement,
                             activeBid: b.api.activeBid().total, copyBid: bids.Copy1.total },
    prices: { polish: b.api.bid().total, copy: bids.Copy1.total },
    // ONE TAB A SHEET, the open one selected, the base's radio checked, the base tab marked, + Add sheet at the END of the strip
    tabs: { roles: (h0.match(/role="tab"/g) || []).length, selected: (h0.match(/aria-selected="true"/g) || []).length,
            tablist: /<ul class="sh-list" role="tablist"/.test(h0), polishChecked: /data-sh-base="Polish"[^>]*checked/.test(h0),
            copyChecked: /data-sh-base="Copy1"[^>]*checked/.test(h0), polishMarked: /<li class="sh sh-tab open base" data-sh-row="Polish"/.test(h0),
            copyMarked: /<li class="sh sh-tab base" data-sh-row="Copy1"/.test(h0), addInStrip: /<li class="sh-addli"[^>]*><button[^>]*data-sh-act="add-menu"/.test(h0),
            addLast: h0.indexOf('data-sh-act="add-menu"') > h0.indexOf('data-sh-row="Seal"') && h0.indexOf('data-sh-act="add-menu"') < h0.indexOf('class="sh-open"'),
            selectedAfter: /aria-selected="true" data-section-tab="Copy1"/.test(h1), openBars: (h1.match(/class="sh-open"/g) || []).length,
            barIsOpenSheet: /class="sh-open" data-sh-open="Copy1"/.test(h1) },
    shown: { polish: /Polish<\/span><span class="sh-price">([^<]*)</.exec(h1)[1], copy: /Polish copy<\/span><span class="sh-price">([^<]*)</.exec(h1)[1] },
    // THE LEGEND LINE IS GONE (the bar is in the sticky head now): no line says what the base radio marks, the radio says it itself, and the
    // one line under the bar is the note about copies.
    legend: { gone: !/marks the base bid/.test(h1) && h1.indexOf("rdot") < 0, radios: radioTags(h1).length,
              titled: radioTags(h1).filter((t) => /title="Base bid: sets the lump sum and the job type"/.test(t)).length,
              named: radioTags(h1).filter((t) => /aria-label="Make [^"]+ the base bid, which sets the lump sum and the job type"/.test(t)).length },
    copiesNote: /<p class="sh-hint">Copies print on the proposal\. The Excel download does not include them\.<\/p>/.test(h1),
    addAtEnd: h1.indexOf('data-sh-act="add-menu"') > h1.indexOf('data-sh-row="Seal"'),
  };
}

// ── 2. Copy adds a copy that prices like its source and starts OFF the proposal ──────────────────────────
async function copy() {
  const b = await open(draft(polishModel()));
  const rootTotal = b.api.bid().total;
  click(b, sel("copy", "Polish"));
  b.clock.fire();
  const saved = last(b.rec.saves);
  const model = clone(saved.polish_estimate);
  const bids = b.api.sectionBids();
  return {
    tabs: Object.keys(model.tabs), kind: model.tabs.Copy1.kind, label: model.tabs.Copy1.label, source: model.tabs.Copy1.source,
    rootTotal: rootTotal, copyTotal: bids.Copy1.total, rows: rowsOf(panel(b)), open: openTab(panel(b)),
    tabOpts: clone(b.store.blob.tab_opts), summary: sumOf(b, "Copy1"),
    savedKinds: (saved.priced_tabs || []).map((t) => [t.id, t.name, t.kind]), lump: saved.proposal_lump_sum, baseTabId: saved.base_tab_id,
    nowLine: nowOf(b), copyAgain: (click(b, sel("copy", "Copy1")), Object.keys(b.api.model().tabs || {})),
  };
}

// ── 3. + Add sheet: any type, ON the proposal, at the top, closing when it is done ────────────────────────
async function add() {
  const b = await open(draft(polishModel()));
  click(b, '[data-sh-act="add-menu"]');
  const menu = panel(b);
  click(b, '[data-sh-act="add"][data-sh-sheet="Epoxy"]');
  await settle();
  const excelAfterEpoxy = hasExcelHint(panel(b));
  const model = modelOf(b);
  const afterEpoxy = { tabs: Object.keys(model.tabs), kind: model.tabs.Epoxy.kind, tabOpts: clone(b.store.blob.tab_opts), summary: sumOf(b, "Epoxy"),
                       switchOn: /role="switch" aria-checked="true"/.test(rowHtml(b, "Epoxy")), open: openTab(panel(b)), menuClosed: /data-sh-act="add-menu"[^>]*aria-expanded="false"/.test(panel(b)), busy: /sh-pick-row/.test(panel(b)) };
  click(b, '[data-sh-act="add-menu"]');
  click(b, '[data-sh-act="add"][data-sh-sheet="Polish"]');
  await settle();
  const m2 = modelOf(b);
  b.clock.fire();
  const saved = last(b.rec.saves);
  return {
    // the types on the menu, in order (Gyp is one row: it adds the first preset), and when the hint about the Excel download is drawn
    menuLabels: (menu.match(/class="sh-pick-row" data-sh-act="add"[^>]*><span>([^<]*)<\/span>/g) || []).map((x) => unattr(/<span>([^<]*)<\/span>/.exec(x)[1])),
    excel: [hasExcelHint(menu), excelAfterEpoxy, hasExcelHint(panel(b))],
    menuHasClose: /data-sh-act="add-close"/.test(menu), menuTagged: (menu.match(/Option only/g) || []).length, startsFrom: /It starts from this bid's [\d,]+ SF\./.exec(menu) && /It starts from this bid's [\d,]+ SF\./.exec(menu)[0],
    afterEpoxy: afterEpoxy,
    secondPolish: { tabs: Object.keys(m2.tabs), sheet: m2.tabs.Copy1.sheet, label: m2.tabs.Copy1.label, kind: m2.tabs.Copy1.kind, tabOpts: clone(b.store.blob.tab_opts).Copy1 },
    lump: saved.proposal_lump_sum, rootTotal: b.api.bid().total, pricedKinds: (saved.priced_tabs || []).map((t) => [t.id, t.kind]),
    alert: text(b, "alert"),
  };
}

// ── 4. Seal sheets: Total only, never the base ───────────────────────────────────────────────────────────
async function seal() {
  const b = await open(draft(polishModel()));
  click(b, '[data-sh-act="add-menu"]');
  click(b, '[data-sh-act="add"][data-sh-sheet="Seal"]');
  await settle();
  const h = panel(b);
  const row = rowHtml(b, "Seal");
  // A Seal sheet asked for Add / Deduct (a stale radio, or a click that should not have been) stays a total.
  const fake = { getAttribute: (k) => (k === "data-sh-mode" ? "Seal" : null), value: "deduct" };
  b.doc.fire("change", { target: fake });
  return {
    noBaseRadio: row.indexOf("data-sh-base") < 0, slotSaysWhy: /title="Seal sheets price as options only, never as the base bid"/.test(row),
    noModePair: row.indexOf("data-sh-mode") < 0, note: /Seal sheets are options only\. They are priced as a total and can't be the base bid\./.test(row),
    stillTotal: b.store.blob.tab_opts.Seal.price_mode, switchOn: /role="switch" aria-checked="true"/.test(row),
    baseRadios: (h.match(/data-sh-base="/g) || []).length, polishRadioChecked: /data-sh-base="Polish"[^>]*checked/.test(h),
  };
}

// ── 5. Making Epoxy the base: confirm, then everything follows ───────────────────────────────────────────
async function baseSwitch() {
  const model = polishModel({ tabs: { Epoxy: epoxySection("option") } });
  const AMOUNT = PRICE.AMOUNT, TAX = PRICE.TAX;
  const b = await open(draft(model, {
    tab_opts: { Epoxy: { show_system: true, show_diff: false, is_option: true, show: true, price_mode: "deduct" } },
    // The Proposal step left a base line the estimator re-worded, with the live markers in it.
    price_overrides: { lines2: { base: "Our price, " + AMOUNT + " – Polished Concrete Flooring as described above " + TAX }, options: { Epoxy: { label: "mine" } } },
  }));
  const polishTotal = b.api.bid().total;
  const epoxyBefore = b.api.sectionBids().Epoxy.total;
  const savesBefore = b.rec.saves.length;
  pick(b, '[data-sh-base="Epoxy"]');
  const asked = rowHtml(b, "Epoxy");
  const confirm = { words: confirmOf(asked),
                    nothingChanged: b.store.blob.work_type === "polish" && B.baseOf(b.api.model()).jobType === "polish",
                    saves: b.rec.saves.length - savesBefore };
  // Cancel puts it back without writing anything
  clickIf(b, '[data-sh-act="base-no"]');
  const cancelled = { confirmGone: rowHtml(b, "Epoxy").indexOf("sh-confirm") < 0, saves: b.rec.saves.length - savesBefore };
  pick(b, '[data-sh-base="Epoxy"]');
  clickIf(b, '[data-sh-act="base-yes"]');
  // what the PICK wrote, before the save that follows it gets to restate the snapshot
  const written = clone(b.store.blob);
  b.clock.fire();
  const saved = last(b.rec.saves);
  const blob = b.store.blob;
  const sm = clone(saved.polish_estimate);
  const hand = epoxyByHand(sm, "Epoxy");
  return {
    confirm: confirm, cancelled: cancelled,
    draft: { work_type: written.work_type, base_tab_id: written.base_tab_id, polishOpt: clone(written.tab_opts.Polish), epoxyOpt: clone(written.tab_opts.Epoxy) },
    kinds: B.sectionsOf(sm).map((e) => [e.tab, e.kind]), jobType: B.baseOf(sm).jobType,
    lump: saved.proposal_lump_sum, hand: hand.total, polishTotal: polishTotal, epoxyBefore: epoxyBefore,
    bar: Number(text(b, "bid-total").replace(/[^0-9]/g, "")), maths: text(b, "maths"),
    pricedTabs: (saved.priced_tabs || []).map((t) => [t.id, t.kind, t.total]), savedBase: saved.base_tab_id, savedWorkType: saved.work_type,
    rows: { polish: sumOf(b, "Polish"), epoxy: /<li class="sh sh-tab(?: open)? base" data-sh-row="Epoxy"/.test(panel(b)) },
    // The Proposal step's own edited line followed the base, by the rule the other two base pickers run.
    lines2: clone(blob.price_overrides.lines2), optionsKept: clone(blob.price_overrides.options),
    open: openTab(panel(b)),
  };
}

// ── 5b. A BASE CHANGE IS A JOB TYPE SWITCHED IN THE SESSION TOO (2026-10-20 audit) ─────────────────────────────
// A far Polish bid (190 miles on file, Lodging and Per Diem on) whose Travel Labor was left blank, with an Epoxy option. Making Epoxy the base
// moves the job's travel to the Epoxy sheet and the Travel Labor row moves with it (B.pickBase); a blank row under a far distance is then filled
// by the rule an answer follows (B.followDistance): 6.5 hours, the guys on the base crew (Epoxy's 3). A base change that keeps the carrier
// (to the combined pair: Polish stays the first base) fills nothing, and a row the estimator typed in is left alone.
async function baseTravel() {
  const farModel = (travel) => polishModel({
    labor: [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33 }, { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 33 },
            Object.assign({ id: "travel", label: "Travel Labor", guys: "", days: "", rate: 33, unit: "hours", guys_auto: false }, travel || {})],
    conditions: Object.assign({}, OFF, { local: false }),
    travel: { lodging: { label: "Lodging", enabled: true, qty: 4, qty_auto: false, rate: 70 }, per_diem: { label: "Per Diem", enabled: true, qty: 4, qty_auto: false, rate: 45 } },
    distance: { miles: 190, source: "google", key: "k" }, tabs: { Epoxy: epoxySection("option") } });
  const travelOf = (sec) => ((sec && sec.labor) || []).filter((r) => r.id === "travel")[0];
  const facts = (r) => (r ? { days: r.days, guys: r.guys, guys_auto: r.guys_auto, guys_follow: r.guys_follow, hours_seed: r.hours_seed } : null);
  const run = async (model, ask) => {
    const b = await open(draft(model));
    const before = { carrier: B.travelCarrier(b.api.root()), row: facts(travelOf(b.api.root())) };
    pick(b, ask);
    clickIf(b, '[data-sh-act="base-yes"]');
    const root = b.api.root();
    const carrier = B.travelCarrier(root);
    const sec = carrier === B.ROOT_TAB ? root : root.tabs[carrier];
    return { before: before, carrier: carrier, row: facts(travelOf(sec)), rootHasTravel: !!travelOf(root), epoxyHasTravel: !!travelOf(root.tabs.Epoxy),
             saves: b.rec.saves.length, asked: (b.rec.distanceBodies || []).length };
  };
  return {
    blank: await run(farModel(), '[data-sh-base="Epoxy"]'),
    typed: await run(farModel({ days: "4", hours_typed: true, guys: "2", guys_typed: true }), '[data-sh-base="Epoxy"]'),
    keepsCarrier: await run(farModel(), '[data-sh-base="combined"]'),
    filled: await run(farModel({ days: 6.5, hours_seed: 6.5, guys_auto: true, guys_follow: "crew", guys: 3 }), '[data-sh-base="Epoxy"]'),
  };
}

// ── 6. The combined Epoxy + Polish base ──────────────────────────────────────────────────────────────────
async function combined() {
  const model = polishModel({ tabs: { Epoxy: epoxySection("option") } });
  const b = await open(draft(model));
  const polishTotal = b.api.bid().total, epoxyTotal = b.api.sectionBids().Epoxy.total;
  const hadRow = panel(b).indexOf('data-sh-row="combined"') >= 0;
  const comboTag = (/<input type="radio" class="sh-radio" name="sh-base" data-sh-base="combined"[^>]*>/.exec(panel(b)) || [""])[0];
  pick(b, '[data-sh-base="combined"]');
  const row = rowHtml(b, "combined");
  const confirm = confirmOf(row);
  clickIf(b, '[data-sh-act="base-yes"]');
  const written = clone(b.store.blob);
  b.clock.fire();
  const saved = last(b.rec.saves);
  const sm = clone(saved.polish_estimate);
  const out = {
    hadRow: hadRow, confirm: confirm, draft: { work_type: written.work_type, base_tab_id: written.base_tab_id },
    radio: { titled: /title="Base bid: Epoxy and Polish together\. It sets the lump sum and the job type"/.test(comboTag),
             named: /aria-label="Make Epoxy \+ Polish \(combined\) the base bid, which sets the lump sum and the job type"/.test(comboTag) },
    kinds: B.sectionsOf(sm).map((e) => [e.tab, e.kind]), jobType: B.baseOf(sm).jobType,
    lump: saved.proposal_lump_sum, polishTotal: polishTotal, epoxyTotal: epoxyTotal, savedBase: saved.base_tab_id, savedWorkType: saved.work_type,
    checked: /data-sh-base="combined"[^>]*checked/.test(panel(b)), baseTabs: (panel(b).match(/<li class="sh sh-tab(?: open)? base" data-sh-row="(?!combined)/g) || []).length, chipBase: /class="sh sh-tab combined base"/.test(panel(b)),
    rowPrice: /Epoxy \+ Polish<\/span><span class="sh-price">([^<]*)</.exec(panel(b))[1], rowType: /class="sh sh-tab combined/.test(panel(b)) ? "COMBINED" : null,
  };
  // and back to Epoxy alone: Polish leaves the base, as an option on the proposal, priced as a total
  pick(b, '[data-sh-base="Epoxy"]');
  const back = { body: (confirmOf(rowHtml(b, "Epoxy")) || {}).body };
  clickIf(b, '[data-sh-act="base-yes"]');
  const blob2 = clone(b.store.blob);
  b.clock.fire();
  out.back = { body: back.body, work_type: blob2.work_type, base_tab_id: blob2.base_tab_id, polishOpt: clone(blob2.tab_opts.Polish),
               kinds: B.sectionsOf(clone(last(b.rec.saves).polish_estimate)).map((e) => [e.tab, e.kind]) };
  return out;
}

// ── 7. Delete: refused on the base, two presses elsewhere ────────────────────────────────────────────────
async function deleting() {
  const copyOf = B.copySection(polishModel(), "Polish", {});
  const b = await open(draft(copyOf.model, { tab_opts: copyOf.patch.tab_opts,
    tab_notes: { Copy1: ["a note"], Other: ["kept"] }, price_overrides: { options: { Copy1: { label: "x", amount: 1 } } } }));
  // the base (and the sheet a bid starts on) is open first: its Delete is disabled, with the reason beside it
  openSheet(b, "Polish");
  const baseRow = rowHtml(b, "Polish");
  const baseBtn = /<button[^>]*data-sh-act="delete"[^>]*>/.exec(baseRow)[0];
  click(b, sel("delete", "Polish"));
  const base = { disabled: /\sdisabled/.test(baseBtn), why: /The base bid can't be deleted\. Make another sheet the base first\./.test(baseRow),
                 tabs: Object.keys(b.api.model().tabs), alert: text(b, "alert"), armed: /Click again to delete/.test(rowHtml(b, "Polish")) };
  // an option: the first press arms, a click elsewhere puts it back, two presses delete it and the draft forgets it
  openSheet(b, "Copy1");
  click(b, sel("delete", "Copy1"));
  const armed = { label: textIf(b, sel("delete", "Copy1")), warns: /Deletes Polish copy and everything typed on it\./.test(rowHtml(b, "Copy1")), still: Object.keys(b.api.model().tabs) };
  // a click on something that does not itself clear the arming (the Description toggle), so it is the page's rule that puts it back
  clickIf(b, sel("desc", "Copy1"));
  const disarmed = textIf(b, sel("delete", "Copy1"));
  clickIf(b, sel("delete", "Copy1")); clickIf(b, sel("delete", "Copy1"));
  b.clock.fire();
  const saved = last(b.rec.saves);
  return {
    base: base, armed: armed, disarmed: disarmed,
    after: { tabs: Object.keys(b.api.model().tabs), rows: rowsOf(panel(b)), open: openTab(panel(b)), tabOpts: clone(b.store.blob.tab_opts),
             tabNotes: clone(b.store.blob.tab_notes), options: clone(b.store.blob.price_overrides.options), pricedTabs: (saved.priced_tabs || []).map((t) => t.id) },
  };
}

// ── 8. Rename: the name is checked when it is committed, never while it is typed ─────────────────────────
async function renaming() {
  const copyOf = B.copySection(polishModel(), "Polish", {});
  const b = await open(draft(copyOf.model, { tab_opts: copyOf.patch.tab_opts }));
  openSheet(b, "Copy1");
  click(b, sel("rename", "Copy1"));
  const started = { input: /<input type="text" class="sh-ren-in"[^>]*value="Polish copy"/.test(rowHtml(b, "Copy1")), hasNote: /Enter saves, Esc cancels\. The name is only a label: nothing is repriced\./.test(rowHtml(b, "Copy1")) };
  // typing a name that will not do says nothing until it is committed
  typeName(b, "Copy1", "Po:");
  const midWord = { error: rowHtml(b, "Copy1").indexOf("data-sh-error") >= 0 };
  const refused = {};
  const tryName = (label, value) => {
    typeName(b, "Copy1", value);
    const prevented = key(b, "Copy1", "Enter");
    const h = rowHtml(b, "Copy1");
    refused[label] = { prevented: prevented, msg: ((/data-sh-error>([^<]*)</.exec(h)) || [])[1] || null, stillRenaming: h.indexOf("sh-ren-in") >= 0,
                       draftKept: h.indexOf('class="sh-ren-in" data-sh-name="Copy1" data-sh-key="Copy1|name" value="' + value + '"') >= 0,
                       label: B.sectionOf(b.api.model(), "Copy1").label };
  };
  tryName("blank", "   ");
  tryName("taken", "polish");
  tryName("badChar", "Garage: floor");
  tryName("tooLong", "x".repeat(32));
  // typing again takes the old message down
  typeName(b, "Copy1", "Garage");
  const retyped = { errorNode: P.need(b, "[data-sh-error]").hidden };
  // Esc drops it
  key(b, "Copy1", "Escape");
  const cancelled = { label: B.sectionOf(b.api.model(), "Copy1").label, input: rowHtml(b, "Copy1").indexOf("sh-ren-in") >= 0, saves: b.rec.saves.length };
  // a good name, by the button
  click(b, sel("rename", "Copy1"));
  typeName(b, "Copy1", "Garage floor");
  click(b, sel("rename-save", "Copy1"));
  b.clock.fire();
  const saved = last(b.rec.saves);
  const sm = clone(saved.polish_estimate);
  return {
    started: started, midWord: midWord, refused: refused, retyped: retyped, cancelled: cancelled,
    saved: { label: sm.tabs.Copy1.label, key: Object.keys(sm.tabs), pricedName: (saved.priced_tabs || []).filter((t) => t.id === "Copy1").map((t) => t.name)[0] },
    shownName: /<span class="sh-nm">Garage floor<\/span>/.test(panel(b)), now: nowOf(b), maths: text(b, "maths"),
  };
}

// ── 9. The switch, Total / Add or Deduct, the words, and the derived figure ──────────────────────────────
async function options() {
  const copyOf = B.copySection(polishModel(), "Polish", {});
  const m = copyOf.model;
  m.tabs.Copy1.takeoff[0].measurement = 5000;                 // cheaper than the base
  m.tabs.Copy2 = Object.assign(clone(m.tabs.Copy1), { label: "Polish dearer", source: "Polish" });
  m.tabs.Copy2.takeoff[0].measurement = 17000;                // dearer than the base
  const b = await open(draft(m, { tab_opts: Object.assign({}, copyOf.patch.tab_opts, { Copy2: B.optionSettings(true) }) }));
  const base = b.api.bid().total, cheap = b.api.sectionBids().Copy1.total, dear = b.api.sectionBids().Copy2.total;
  openSheet(b, "Copy1");
  const start = { summary: sumOf(b, "Copy1"), switchOff: /aria-checked="false"/.test(rowHtml(b, "Copy1")), inert: /class="sh-ctl inert"/.test(rowHtml(b, "Copy1")) };
  click(b, sel("on", "Copy1"));
  const on = { opt: clone(b.store.blob.tab_opts.Copy1), summary: sumOf(b, "Copy1"), inert: /class="sh-ctl inert"/.test(rowHtml(b, "Copy1")) };
  pick(b, '[data-sh-mode="Copy1"][value="deduct"]');
  const deduct = { opt: clone(b.store.blob.tab_opts.Copy1), summary: sumOf(b, "Copy1"), checked: /value="deduct"[^>]*checked/.test(rowHtml(b, "Copy1")) };
  openSheet(b, "Copy2");
  click(b, sel("on", "Copy2"));        // it starts ON, so this turns it off
  const off = { opt: clone(b.store.blob.tab_opts.Copy2), summary: sumOf(b, "Copy2") };
  click(b, sel("on", "Copy2"));
  pick(b, '[data-sh-mode="Copy2"][value="deduct"]');
  const add = { summary: sumOf(b, "Copy2") };
  // the words: opened, typed in, kept; the box is not redrawn under the caret while typing
  click(b, sel("desc", "Copy2"));
  const boxOpen = { box: rowHtml(b, "Copy2").indexOf('data-sh-desc="Copy2"') >= 0, ph: /placeholder="([^"]*)"/.exec(rowHtml(b, "Copy2")) && /placeholder="([^"]*)"/.exec(rowHtml(b, "Copy2"))[1] };
  const box = P.need(b, '[data-sh-desc="Copy2"]');
  const writesBefore = b.doc.getElementById("sheets-panel").htmlWrites;
  box.value = "Grind and polish to 400 grit";
  b.doc.fire("input", { target: box });
  const typed = { opt: b.store.blob.tab_opts.Copy2.desc, redraws: b.doc.getElementById("sheets-panel").htmlWrites - writesBefore };
  box.value = "y".repeat(450);
  b.doc.fire("input", { target: box });
  const capped = b.store.blob.tab_opts.Copy2.desc.length;
  box.value = "Grind and polish to 400 grit";
  b.doc.fire("input", { target: box });
  click(b, sel("desc", "Copy2"));
  const collapsed = { preview: /<span class="sh-desc-prev">([^<]*)</.exec(rowHtml(b, "Copy2")), expanded: /data-sh-act="desc"[^>]*aria-expanded="([^"]*)"/.exec(rowHtml(b, "Copy2"))[1] };
  return { base: base, cheap: cheap, dear: dear, start: start, on: on, deduct: deduct, off: off, add: add, boxOpen: boxOpen, typed: typed, capped: capped,
           collapsed: { preview: collapsed.preview && collapsed.preview[1], expanded: collapsed.expanded },
           expectDeduct: "Deduct (" + money(Math.round(base) - Math.round(cheap)) + ")", expectAdd: "Add " + money(Math.round(dear) - Math.round(base)) };
}

// ── 10. A saved bid opens as saved; the base the estimator chose is not undone on open ───────────────────
async function reopen() {
  const model = polishModel({ tabs: { Epoxy: epoxySection("option") } });
  const b = await open(draft(model, { tab_opts: { Epoxy: B.optionSettings(true) } }));
  pick(b, '[data-sh-base="Epoxy"]');
  clickIf(b, '[data-sh-act="base-yes"]');
  b.clock.fire();
  const again = await open(clone(b.store.blob));
  const m = clone(again.api.state().polish_estimate);
  // a Polish bid whose base is a copy of Polish, the root an option
  const copyOf = B.copySection(polishModel(), "Polish", {});
  const made = B.pickBase(copyOf.model, ["Copy1"], { state: { tab_opts: copyOf.patch.tab_opts } });
  const c = await open(draft(made.model, Object.assign({ work_type: made.patch.work_type, base_tab_id: made.patch.base_tab_id }, { tab_opts: made.patch.tab_opts })));
  const cm = clone(c.api.state().polish_estimate);
  return {
    afterSwitch: { saves: again.rec.saves.length, armed: again.clock.armed(), kinds: B.sectionsOf(m).map((e) => [e.tab, e.kind]), workType: again.store.blob.work_type,
                   rows: tabsOf(panel(again)), bar: Number(text(again, "bid-total").replace(/[^0-9]/g, "")), expectBar: Math.round(epoxyByHand(m, "Epoxy").total) },
    copyBase: { saves: c.rec.saves.length, armed: c.clock.armed(), kinds: B.sectionsOf(cm).map((e) => [e.tab, e.kind]), rows: tabsOf(panel(c)),
                bar: Number(text(c, "bid-total").replace(/[^0-9]/g, "")) },
  };
}

// ── 11. A bid whose other sheets cannot be read still shows its first sheet, says so, and offers nothing else ───
async function unreadable() {
  const model = polishModel({ tabs: { Epoxy: Object.assign(epoxySection("base"), { layout: undefined }) } });
  const b = await open(draft(model, { work_type: "combo" }));
  const h = panel(b);
  return { rows: rowsOf(h), warn: /This bid's other sheets can't be read, so only Polish shows\. Polish still prices and saves\. Reload to try again\./.test(h),
           addDisabled: /data-sh-act="add-menu"[^>]*disabled/.test(h), addWhy: /Adding a sheet is off until the other sheets can be read\./.test(h),
           price: /Polish<\/span><span class="sh-price">([^<]*)</.exec(h) && /Polish<\/span><span class="sh-price">([^<]*)</.exec(h)[1], bid: money(b.api.bid().total) };
}

// ── 12. The caret goes back where it was after a repaint ─────────────────────────────────────────────────
async function focus() {
  const copyOf = B.copySection(polishModel(), "Polish", {});
  const b = await open(draft(copyOf.model, { tab_opts: copyOf.patch.tab_opts }));
  openSheet(b, "Copy1");
  const el = b.doc.getElementById("sheets-panel");
  const focused = [];
  const focusOptions = [];            // how each focus() was called: the head is sticky, and a focus that scrolls would throw a scrolled page up to it
  const realAll = el.querySelectorAll;
  el.querySelectorAll = (s) => realAll(s).map((n) => { n.focus = (o) => { focused.push(n.attrs["data-sh-key"]); focusOptions.push(o); }; return n; });
  el.contains = () => true;
  const pressWithCaretOn = (k, selector) => { b.doc.activeElement = { getAttribute: (a) => (a === "data-sh-key" ? k : null) }; click(b, selector); };
  pressWithCaretOn("Copy1|on", sel("on", "Copy1"));
  const afterSwitch = focused.splice(0);
  pressWithCaretOn("Copy1|rename", sel("rename", "Copy1"));
  const afterRename = focused.splice(0);
  pressWithCaretOn("Copy1|save", sel("rename-cancel", "Copy1"));
  const afterCancel = focused.splice(0);
  click(b, sel("copy", "Copy1"));
  const afterCopy = focused.splice(0);
  // a name that will not do keeps the caret in the box; a saved name puts it back on Rename
  click(b, sel("rename", "Copy2"));
  focused.splice(0);
  typeName(b, "Copy2", "   ");
  key(b, "Copy2", "Enter");
  const afterRefusedName = focused.splice(0);
  typeName(b, "Copy2", "Garage");
  key(b, "Copy2", "Enter");
  const afterSavedName = focused.splice(0);
  return { afterSwitch: afterSwitch, afterRename: afterRename, afterCancel: afterCancel, afterCopy: afterCopy,
           afterRefusedName: afterRefusedName, afterSavedName: afterSavedName,
           options: { n: focusOptions.length, noScroll: focusOptions.length > 0 && focusOptions.every((o) => !!o && o.preventScroll === true) } };
}

// ── 13. the pure markup: escaping, no dash, nothing for a bid with no sheets to say ─────────────────────────
async function markup() {
  const m = polishModel({ tabs: { Epoxy: epoxySection("option") } });
  m.tabs.Epoxy.label = 'Epoxy <b>"x"</b> & more';
  const view = { open: "Epoxy", bids: { Polish: { total: 100 }, Epoxy: { total: 80 } }, opts: { Epoxy: { is_option: true, show: true, price_mode: "deduct", desc: '"><img src=x>' } },
                 descOpen: { Epoxy: true }, sysDesc: () => 'p"h', sf: 0, icon: (n) => "<svg data-icon=" + n + "></svg>" };
  const h = B.sheetsPanelHtml(m, view);
  const gyp = B.sheetsPanelHtml(B.sectionsForJob(B.freshModel(), "gyp", {}), { open: 'Gyp (USG 1-8")', bids: {} });
  // the bar in every state the page can leave them in, for the sweep for dashes
  const broken = polishModel({ tabs: { Epoxy: Object.assign(epoxySection("base"), { layout: undefined }) } });
  const both = polishModel({ tabs: { Epoxy: epoxySection("base") } });
  const base = { open: "Polish", bids: { Polish: { total: 100 }, Epoxy: { total: 80 } }, sf: 100, icon: () => "" };
  const states = [
    h,
    B.sheetsPanelHtml(m, Object.assign({}, base, { confirm: { row: "Epoxy", ids: ["Epoxy"] } })),
    B.sheetsPanelHtml(m, Object.assign({}, base, { open: "Epoxy", renaming: "Epoxy", draft: "x", error: "Enter a sheet name." })),
    B.sheetsPanelHtml(m, Object.assign({}, base, { open: "Epoxy", armed: "Epoxy" })),
    B.sheetsPanelHtml(m, Object.assign({}, base, { pick: true })), B.sheetsPanelHtml(m, Object.assign({}, base, { pick: true, busy: true })),
    B.sheetsPanelHtml(both, Object.assign({}, base, { confirm: { row: "combined", ids: ["Epoxy", "Polish"] } })),
    B.sheetsPanelHtml(both, Object.assign({}, base, { open: "Polish" })), B.sheetsPanelHtml(broken, base), B.sheetsPanelHtml(polishModel(), base),
    B.sheetsPanelHtml(B.copySection(polishModel(), "Polish", {}).model, Object.assign({}, base, { open: "Copy1" })),
  ];
  return {
    states: states,
    legendAnywhere: states.some((s) => /marks the base bid/.test(s) || s.indexOf("rdot") >= 0),
    escaped: h.indexOf('<b>"x"</b>') < 0 && h.indexOf("&lt;b&gt;&quot;x&quot;&lt;/b&gt; &amp; more") > 0 && h.indexOf("<img") < 0 && h.indexOf("&lt;img src=x&gt;") > 0,
    placeholder: /placeholder="p&quot;h"/.test(h), icons: (h.match(/data-icon=/g) || []).length >= 5,
    noDash: h.indexOf(String.fromCharCode(0x2014)) < 0, deduct: sumFigure(h),
    noNowLine: typeof B.sheetNowHtml === "undefined",
    gypAttr: gyp.indexOf('data-section-tab="Gyp (USG 1-8&quot;)"') >= 0, noSf: /It starts empty/.test(B.sheetsPanelHtml(polishModel(), { pick: true })),
    pair: B.combinedPair(m), pairNone: B.combinedPair(polishModel()),
    confirmWords: { epoxy: B.baseChangeWords(m, ["Epoxy"]), same: B.baseChangeWords(B.copySection(polishModel(), "Polish", {}).model, ["Copy1"]), combo: B.baseChangeWords(m, ["Epoxy", "Polish"]) },
    optionIsOn: [B.optionIsOn(undefined, "x"), B.optionIsOn({ x: { is_option: false } }, "x"), B.optionIsOn({ x: { is_option: true, show: false } }, "x"), B.optionIsOn({ x: { is_option: true } }, "x")],
    patch: B.tabOptPatch({ tab_opts: { a: { keep: 1 } } }, "b", { price_mode: "deduct" }),
  };
}
function sumFigure(h) { return ((/class="sh-sum[^"]*">([^<]*)<b>([^<]*)<\/b>/.exec(h)) || []).slice(1, 3).join(" ").replace(/\s+/g, " ").trim(); }

// ── 14. it does not float: it is a strip of tabs in the flow, in the sticky head under the top bar (no longer inside #main) ─────────────────
async function floating() {
  const b = await open(draft(polishModel()));
  const css = L.read(path.join(ROOT, "polish-estimate.html"));
  const style = css.slice(css.indexOf("<style>"), css.indexOf("</style>"));
  const js = L.read(path.join(ROOT, "js", "polish-estimate.js"));
  const h = panel(b);
  return {
    floats: clone(b.rec.floats || []),
    floatKeyInPage: js.indexOf("tw_v2sheets_pos") >= 0 || js.indexOf("initSheetsPanelDrag") >= 0,
    fixedRule: /\.sheets\{[^}]*position:\s*fixed/.test(style), gripRule: /sh-head|sh-grip|sh-dragging/.test(style) || /sh-head|sh-grip/.test(h),
    wideLane: /body\{padding-right:288px\}/.test(style),
    markupHasPanelFirst: css.indexOf('id="sheets-panel"') > 0 && css.indexOf('id="sheets-panel"') < css.indexOf('id="rail"'),
    beforeMain: css.indexOf('id="sheets-panel"') < css.indexOf('id="main"'),
    scrolls: /\.sh-strip\{[^}]*overflow-x:auto/.test(style),
    oldStripGone: css.indexOf('id="sections"') < 0 && css.indexOf('id="option-bar"') < 0 && css.indexOf('id="sheet-now"') < 0,
    loadsPriceRule: /<script src="\/js\/price-lines-core\.js"><\/script>/.test(css),
  };
}

// ── 15. a Gyp sheet's preset keeps what the draft held for it ────────────────────────────────────────────────
// THE DEFECT (Sheets phase 3 review): the Add menu always adds the FIRST Gyp preset, so anyone who wants another changes it on the
// Material step, which renames the sheet's key. Nothing carried the draft's settings across: the sheet came back ON the proposal with no words.
async function gypPreset() {
  const FIRST = GYP.tabs()[0], NEXT = GYP.tabs()[1];
  const b = await open(draft(polishModel()));
  click(b, '[data-sh-act="add-menu"]');
  // pressed by its id as a browser hands it over: the row's data-sh-sheet reads Gyp (USG 1-8"), quote mark and all
  if (!clickIf(b, '[data-sh-act="add"][data-sh-sheet="' + attr(FIRST) + '"]')) return { noRow: true };
  await settle();
  const added = { rows: rowsOf(panel(b)), open: openTab(panel(b)), on: B.optionIsOn(b.store.blob.tab_opts, FIRST), alert: text(b, "alert") };
  // The estimator switches it OFF the proposal and types the words it should print; the draft also holds a note, a price override
  // and a line typed on the Proposal step for it.
  click(b, sel("on", FIRST));
  click(b, sel("desc", FIRST));
  const box = P.need(b, '[data-sh-desc="' + attr(FIRST) + '"]');
  box.value = "my gyp words";
  b.doc.fire("input", { target: box });
  b.TW.setState({
    tab_notes: Object.fromEntries([[FIRST, ["a note"]], ["Other", ["kept"]]]),
    price_overrides: { options: Object.fromEntries([[FIRST, { label: "mine" }], ["Other", { label: "kept" }]]),
                       lines2: Object.fromEntries([["option:" + FIRST, "my line"]]) },
  });
  const before = clone(b.store.blob.tab_opts[FIRST]);
  // The Material step's Gyp card moves the sheet to another preset.
  P.changeTo(b, '[data-gyp="preset"]', NEXT);
  const blob = clone(b.store.blob);
  const row = rowHtml(b, NEXT);
  const openNow = openTab(panel(b));
  b.clock.fire();
  const saved = last(b.rec.saves.filter((x) => x.polish_estimate));
  // and back again: the settings come back under the first preset, with nothing left behind
  P.changeTo(b, '[data-gyp="preset"]', FIRST);
  const back = clone(b.store.blob);
  return {
    added: added, before: before, open: openNow,
    keys: { opts: Object.keys(blob.tab_opts), notes: Object.keys(blob.tab_notes), options: Object.keys(blob.price_overrides.options),
            lines: Object.keys(blob.price_overrides.lines2) },
    opt: blob.tab_opts[NEXT], notes: blob.tab_notes[NEXT], option: blob.price_overrides.options[NEXT], line: blob.price_overrides.lines2["option:" + NEXT],
    otherKept: [blob.tab_notes.Other, blob.price_overrides.options.Other],
    row: { switchOn: /role="switch" aria-checked="true"/.test(row), switchOff: /role="switch" aria-checked="false"/.test(row),
           preview: ((/sh-desc-prev">([^<]*)</.exec(row)) || [])[1] || null, summary: sumOf(b, NEXT) },
    saved: { tabs: Object.keys(saved.polish_estimate.tabs), opts: Object.keys(saved.tab_opts), entry: saved.tab_opts[NEXT] },
    back: { opts: Object.keys(back.tab_opts), entry: back.tab_opts[FIRST], notes: Object.keys(back.tab_notes), options: Object.keys(back.price_overrides.options) },
  };
}

// ── 16. at the limit of twelve copies the refusal is said in the panel, beside the button that was pressed ──────────
const noticeOf = (h) => { const m = /<p class="sh-note warn" role="alert" data-sh-notice>([^<]*)<\/p>/.exec(h); return m ? m[1] : null; };
const addBlock = (h) => { const a = ['class="sh-add"', 'class="sh-flow"'].map((s) => h.indexOf(s)).filter((i) => i >= 0).sort((x, y) => x - y)[0]; if (a === undefined) return ""; const e = ['<div class="sh-confirm"', '<div class="sh-open"', '<p class="sh-hint"'].map((s) => h.indexOf(s, a)).filter((i) => i >= 0); return h.slice(a, e.length ? Math.min.apply(null, e) : h.length); };
async function limit() {
  const b = await open(draft(polishModel()));
  for (let i = 0; i < 12; i++) click(b, sel("copy", openTab(panel(b))));
  const last12 = openTab(panel(b));
  click(b, sel("copy", last12));                                  // the 13th
  const copyRefused = { copies: Object.keys(modelOf(b).tabs).length, inRow: noticeOf(rowHtml(b, last12)), inAddBlock: noticeOf(addBlock(panel(b))),
                        alert: text(b, "alert") };
  // the next click, on anything but Copy or Add, takes it down
  click(b, sel("desc", last12));
  const afterClick = noticeOf(rowHtml(b, last12));
  // Add sheet: a second Polish is a copy too, so it is refused; the notice is under the button and the menu stays open for another type
  click(b, '[data-sh-act="add-menu"]');
  click(b, '[data-sh-act="add"][data-sh-sheet="Polish"]');
  await settle();
  const addRefused = { inAddBlock: noticeOf(addBlock(panel(b))), inRow: noticeOf(rowHtml(b, last12)), menuOpen: /sh-pick-row/.test(panel(b)), alert: text(b, "alert") };
  // a type that is not a copy goes in, which says the refusal is over
  click(b, '[data-sh-act="add"][data-sh-sheet="Epoxy"]');
  await settle();
  const added = { inAddBlock: noticeOf(addBlock(panel(b))), epoxy: Object.keys(modelOf(b).tabs).indexOf("Epoxy") >= 0 };
  return { last: last12, copyRefused: copyRefused, afterClick: afterClick, addRefused: addRefused, added: added };
}

// ── 17. a Seal option the Proposal step left on Add / Deduct is put back to a total when the page opens ─────────────
async function sealMode() {
  const seal = { layout: "seal", kind: "option", profile: "seal@1", takeoff: [], labor: [], contingency: 0, fees: 0, totals: {},
                 rates: { version: 1, profile: "seal@1", rates: {}, fees_default: null, notes: EPOXY_NOTES.slice() } };
  const c = B.copySection(polishModel({ tabs: { Seal: seal } }), "Polish", {});
  const held = (mode) => ({ Seal: { show_system: true, show_diff: false, is_option: true, show: true, price_mode: mode, desc: "seal words" },
                            Copy1: Object.assign(B.optionSettings(true), { price_mode: "deduct" }) });
  const b = await open(draft(c.model, { tab_opts: held("deduct") }));
  const written = clone(b.store.blob.tab_opts);
  const writesOnOpen = b.rec.saves.length;
  openSheet(b, "Seal");
  const row = rowHtml(b, "Seal");
  const plain = await open(draft(c.model, { tab_opts: held("total") }));
  return { written: written, writesOnOpen: writesOnOpen, noPair: row.indexOf("data-sh-mode") < 0, plainWritesOnOpen: plain.rec.saves.length };
}

// ── 18. the old base keeps its words and goes on the proposal as a total, whatever it held ──────────────────────────
async function demote() {
  const model = polishModel({ tabs: { Epoxy: epoxySection("option") } });
  const held = { show_system: true, show_diff: false, is_option: false, show: false, price_mode: "deduct", desc: "my polish words" };
  const b = await open(draft(model, { tab_opts: { Polish: held, Epoxy: B.optionSettings(true) } }));
  pick(b, '[data-sh-base="Epoxy"]');
  clickIf(b, '[data-sh-act="base-yes"]');
  return { before: held, written: clone(b.store.blob.tab_opts.Polish), summary: sumOf(b, "Polish") };
}

// ── 19. what a press clears: a base change waiting for its yes, a name being typed and the refusal under it ─────────
async function resets() {
  const c = B.copySection(polishModel({ tabs: { Epoxy: epoxySection("option") } }), "Polish", {});
  const b = await open(draft(c.model, { tab_opts: Object.assign({ Epoxy: B.optionSettings(true) }, c.patch.tab_opts) }));
  const asked = () => confirmOf(rowHtml(b, "Epoxy")) !== null;
  const renaming = () => ({ input: rowHtml(b, "Copy1").indexOf("sh-ren-in") >= 0, error: rowHtml(b, "Copy1").indexOf("data-sh-error") >= 0 });
  openSheet(b, "Copy1");
  // a base change waiting for its yes goes when another sheet is opened
  pick(b, '[data-sh-base="Epoxy"]');
  const askedA = asked();
  openSheet(b, "Polish");
  const afterOpen = asked();
  // a name being typed, and the refusal under it, go when another sheet is opened
  openSheet(b, "Copy1");
  click(b, sel("rename", "Copy1"));
  typeName(b, "Copy1", "Po:");
  key(b, "Copy1", "Enter");
  const refused = renaming();
  openSheet(b, "Polish");
  openSheet(b, "Copy1");
  const afterOpenName = renaming();
  // a base change waiting for its yes goes when a sheet is copied
  pick(b, '[data-sh-base="Epoxy"]');
  const askedC = asked();
  clickIf(b, sel("copy", "Copy1"));
  const afterCopy = asked();
  // ... and when a sheet is added (opening the menu alone does not)
  pick(b, '[data-sh-base="Epoxy"]');
  click(b, '[data-sh-act="add-menu"]');
  const withMenu = asked();
  click(b, '[data-sh-act="add"][data-sh-sheet="Seal"]');
  await settle();
  const afterAdd = asked();
  return { askedA: askedA, afterOpen: afterOpen, refused: refused, afterOpenName: afterOpenName, askedC: askedC, afterCopy: afterCopy, withMenu: withMenu, afterAdd: afterAdd };
}

// ── 20. an option the draft has said nothing about is priced as a Total ──────────────────────────────────────────────
async function unstated() {
  const c = B.copySection(polishModel(), "Polish", {});
  const read = async (extra) => {
    const b = await open(draft(c.model, extra));
    openSheet(b, "Copy1");
    const h = rowHtml(b, "Copy1");
    return { total: /value="total"[^>]*checked/.test(h), deduct: /value="deduct"[^>]*checked/.test(h), summary: sumOf(b, "Copy1"), saves: b.rec.saves.length };
  };
  return { noEntry: await read(), noMode: await read({ tab_opts: { Copy1: { is_option: true, show: true } } }) };
}

// ── 21. the switch brings back an option the Proposal step had hidden ────────────────────────────────────────────────
async function hiddenOption() {
  const c = B.copySection(polishModel(), "Polish", {});
  const b = await open(draft(c.model, { tab_opts: { Copy1: { show_system: true, show_diff: false, is_option: true, show: false, price_mode: "total", desc: "kept words" } } }));
  openSheet(b, "Copy1");
  const state = () => ({ on: /role="switch" aria-checked="true"/.test(rowHtml(b, "Copy1")), summary: sumOf(b, "Copy1") });
  const hidden = state();
  click(b, sel("on", "Copy1"));
  const shown = state();
  const written = clone(b.store.blob.tab_opts.Copy1);
  click(b, sel("on", "Copy1"));
  return { hidden: hidden, shown: shown, written: written, off: Object.assign(state(), { opt: clone(b.store.blob.tab_opts.Copy1) }) };
}

// ── 22. the strip keeps its place across a repaint, scrolls to a newly opened tab, is walked by the arrow keys, and the add notice is in the flow ──
async function stripKeeps() {
  const copyOf = B.copySection(polishModel(), "Polish", {});
  const m = copyOf.model;
  m.tabs.Seal = { layout: "seal", kind: "option", profile: "seal@1", takeoff: [], labor: [], contingency: 0, fees: 0, totals: {},
    rates: { version: 1, profile: "seal@1", rates: {}, fees_default: null, notes: EPOXY_NOTES.slice() } };
  const b = await open(draft(m, { tab_opts: copyOf.patch.tab_opts }));

  // 1. a repaint that changes the markup (a price moved) leaves the strip scrolled where it was
  const strip0 = P.need(b, "[data-sh-strip]");
  strip0.scrollLeft = 150;
  const before = panel(b);
  b.api.model().takeoff[0].measurement = 4321;
  b.api.changed(false);
  const repainted = panel(b) !== before;
  const strip1 = P.need(b, "[data-sh-strip]");
  const kept = { repainted: repainted, newNode: strip1 !== strip0, scrollLeft: strip1.scrollLeft };

  // 2. scrolling to a tab: only as far as it takes, never when it is already in view, never an error without layout
  const reveal = (strip, tab) => { b.api.stripReveal(strip, tab); return strip.scrollLeft; };
  const reach = {
    right: reveal({ scrollLeft: 0, clientWidth: 300, offsetLeft: 0 }, { offsetLeft: 500, offsetWidth: 120 }),
    left: reveal({ scrollLeft: 400, clientWidth: 300, offsetLeft: 0 }, { offsetLeft: 100, offsetWidth: 120 }),
    inView: reveal({ scrollLeft: 50, clientWidth: 300, offsetLeft: 0 }, { offsetLeft: 100, offsetWidth: 120 }),
    noLayout: reveal({ scrollLeft: 7 }, {}),
  };

  // 3. the arrow keys walk the tabs; Enter is left to the button
  const tabs = b.doc.querySelectorAll("[data-section-tab]");
  const names = tabs.map((t) => t.getAttribute("data-section-tab"));
  let focused = null;
  const focusOpts = [];
  // a layout for the strip and for each tab's <li>, so "the strip was scrolled to the tab" is a number: tab i is 150 wide at 200 * i, the strip 300 wide
  const stripNow = P.need(b, "[data-sh-strip]");
  stripNow.clientWidth = 300; stripNow.scrollLeft = 0; stripNow.offsetLeft = 0;
  tabs.forEach((t, i) => {
    t.focus = (o) => { focused = t.getAttribute("data-section-tab"); focusOpts.push(o); };
    t.closest = (s) => (s === "li" ? { offsetLeft: 200 * i, offsetWidth: 150 } : null);
  });
  const press = (from, k) => {
    focused = null;
    let prevented = false;
    b.doc.fire("keydown", { target: tabs[from], key: k, preventDefault() { prevented = true; } });
    return { focused: focused, prevented: prevented };
  };
  const firstRight = press(0, "ArrowRight");
  const revealed = stripNow.scrollLeft;               // right after the first press: tab 1 ends at 350, the strip shows 300 of it, so 350 - 300 + 8
  const keys = { names: names, right: firstRight, wrap: press(names.length - 1, "ArrowRight"), left: press(1, "ArrowLeft"),
                 leftWrap: press(0, "ArrowLeft"), home: press(2, "Home"), end: press(0, "End"), enter: press(0, "Enter"), space: press(0, " "),
                 revealed: revealed, opts: { n: focusOpts.length, noScroll: focusOpts.length > 0 && focusOpts.every((o) => !!o && o.preventScroll === true) } };

  // 4. a refused Add is said in the flow under the strip, never inside the picker's box
  const w = await open(draft(polishModel()));
  for (let i = 0; i < 12; i++) click(w, sel("copy", openTab(panel(w))));
  click(w, '[data-sh-act="add-menu"]');
  click(w, '[data-sh-act="add"][data-sh-sheet="Polish"]');
  await settle();
  const h = panel(w);
  const addAt = h.indexOf('class="sh-add"'), flowAt = h.indexOf('class="sh-flow"');
  const ends = ['<div class="sh-confirm"', '<div class="sh-open"', '<p class="sh-hint"'].map((s) => h.indexOf(s, flowAt)).filter((i) => i >= 0);
  const box = h.slice(addAt, flowAt), flow = h.slice(flowAt, ends.length ? Math.min.apply(null, ends) : h.length);
  const notice = { pickerOpen: addAt >= 0, flowAfterBox: flowAt > addAt, inBox: noticeOf(box), inFlow: noticeOf(flow),
                   pickerHasList: /sh-pick-row/.test(box), openBarAfter: h.indexOf('class="sh-open"') > flowAt };
  return { kept: kept, reach: reach, keys: keys, notice: notice };
}

// ── 23. the sticky head: the bar waits until it has been drawn, and the head's height reaches the page's scroll-padding-top ──────────────────────
/** A ResizeObserver stand-in: it remembers what it was asked to watch, and a scenario says "it changed" by firing it. */
function observerClass() {
  const made = [];
  const cls = class { constructor(cb) { this.cb = cb; this.targets = []; made.push(this); } observe(t) { this.targets.push(t); } disconnect() { this.targets = []; } };
  return { cls: cls, made: made, fire: () => made.forEach((o) => o.cb([], o)) };
}
/** What the page last told the browser the head's height is (--v2head-h on the html element), "" when it never has. */
const headProp = (b) => b.doc.documentElement.style.getPropertyValue("--v2head-h");
/** Give the head a box: the stand-in DOM has no layout, so the height a browser would measure is the one a scenario says. */
const headBox = (b, height) => { b.dom.get("v2head").getBoundingClientRect = () => ({ height: height }); };
async function stickyHead() {
  // 1. HIDDEN UNTIL DRAWN. The page's own markup says hidden; init draws the bar and shows it AFTER that drawing, once, and never hides it again.
  const ro = observerClass();
  const b = P.build({ blob: draft(polishModel()), resizeObserver: ro.cls });
  const bar = b.dom.get("sheets-panel");
  const before = { hidden: bar.hidden, empty: bar.innerHTML === "", mainHidden: b.dom.get("main").hidden };
  headBox(b, 120);
  await b.api.init();
  await settle();
  const events = b.log.filter((e) => /^(html|show|hide):sheets-panel$/.test(e));
  // the page is ready (#main shown) BEFORE the bar is: a bar shown while the page still says "Loading the item library" is the flash this guards
  const shownOrder = b.log.filter((e) => /^show:(main|sheets-panel)$/.test(e));
  const after = { hidden: bar.hidden, drawn: /data-section-tab=/.test(html(b, "sheets-panel")), mainHidden: b.dom.get("main").hidden,
                  readyFirst: shownOrder.indexOf("show:main") >= 0 && shownOrder.indexOf("show:main") < shownOrder.indexOf("show:sheets-panel"),
                  drawnFirst: events.indexOf("html:sheets-panel") >= 0 && events.indexOf("html:sheets-panel") < events.indexOf("show:sheets-panel"),
                  shows: events.filter((e) => e === "show:sheets-panel").length, hides: events.filter((e) => e === "hide:sheets-panel").length };
  // a page that cannot read its library never draws the bar, so it stays hidden behind the message
  const down = P.build({ blob: draft(polishModel()), libraryFails: true });
  await down.api.init();
  await settle();
  const stayed = { hidden: down.dom.get("sheets-panel").hidden, writes: down.dom.get("sheets-panel").htmlWrites,
                   said: /Couldn't load the item library/.test(down.dom.get("loading").textContent) };

  // 2. THE HEAD'S HEIGHT REACHES --v2head-h THROUGH THE OBSERVER. With one, a repaint of the bar measures nothing and the observer does,
  //    rounding up; a head with no height leaves the last good figure.
  const watched = { made: ro.made.length, targets: ro.made.map((o) => o.targets.map((t) => t.attrs.id)),
                    resizeListeners: b.win.listeners.filter((l) => l.type === "resize").length };
  const idle = headProp(b);
  ro.fire();
  const first = headProp(b);
  headBox(b, 150.2);
  ro.fire();
  const second = headProp(b);
  headBox(b, 0);
  ro.fire();
  const none = headProp(b);

  // 3. A BROWSER WITH NO ResizeObserver is told by the bar's own first drawing and by the window's resize.
  const plain = P.build({ blob: draft(polishModel()) });
  headBox(plain, 161);
  await plain.api.init();
  await settle();
  const painted = headProp(plain);
  headBox(plain, 188.4);
  plain.win.fire("resize");
  const resized = headProp(plain);
  const fallback = { resizeListeners: plain.win.listeners.filter((l) => l.type === "resize").length, painted: painted, resized: resized };
  // a document with no html element to write to is no error either
  delete plain.doc.documentElement;
  let noRoot = true;
  try { plain.win.fire("resize"); } catch (e) { noRoot = false; }
  return { before: before, after: after, stayed: stayed, watched: watched, heights: { idle: idle, first: first, second: second, none: none },
           fallback: fallback, noRoot: noRoot };
}

main().then((out) => { process.stdout.write(JSON.stringify(out) + "\n"); }, (e) => { process.stderr.write(String(e && e.stack || e) + "\n"); process.exit(1); });
