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
const rowHtml = (b, tab) => { const h = panel(b); const at = h.indexOf('data-sh-row="' + attr(tab) + '"'); if (at < 0) return ""; const end = h.indexOf("</li>", at); return h.slice(at, end); };
const sumOf = (b, tab) => ((/class="sh-sum[^"]*">([^<]*)(?:<b>([^<]*)<\/b>)?/.exec(rowHtml(b, tab))) || []).slice(1, 3).filter(Boolean).join(" ").replace(/\s+/g, " ").trim();

async function main() {
  const out = {};
  const sections = [
    ["list", list], ["copy", copy], ["add", add], ["seal", seal], ["baseSwitch", baseSwitch], ["combined", combined], ["deleting", deleting],
    ["renaming", renaming], ["options", options], ["reopen", reopen], ["unreadable", unreadable], ["focus", focus], ["markup", markup], ["floating", floating],
    ["gypPreset", gypPreset], ["limit", limit], ["sealMode", sealMode], ["demote", demote], ["resets", resets], ["unstated", unstated], ["hiddenOption", hiddenOption],
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
  const before = { open: openTab(h0), tabs: tabsOf(h0), rows: rowsOf(h0), now: text(b, "sheet-now"), nowHidden: !!b.doc.getElementById("sheet-now").hidden,
                   radios: (h0.match(/data-sh-base="/g) || []).length };
  click(b, '[data-section-tab="Copy1"]');
  const h1 = panel(b);
  return {
    before: before, after: { open: openTab(h1), now: text(b, "sheet-now"), takeoffOnShow: b.api.model().takeoff[0].measurement,
                             activeBid: b.api.activeBid().total, copyBid: bids.Copy1.total },
    prices: { polish: b.api.bid().total, copy: bids.Copy1.total },
    shown: { polish: /Polish<\/span><span class="sh-price">([^<]*)</.exec(h1)[1], copy: /Polish copy<\/span><span class="sh-price">([^<]*)</.exec(h1)[1] },
    hasHint: /marks the base bid, which sets the lump sum and the job type/.test(h1) && /The Excel download does not include them/.test(h1),
    addAtTop: h1.indexOf('data-sh-act="add-menu"') > 0 && h1.indexOf('data-sh-act="add-menu"') < h1.indexOf('data-sh-row="Polish"'),
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
    nowLine: text(b, "sheet-now"), copyAgain: (click(b, sel("copy", "Copy1")), Object.keys(b.api.model().tabs || {})),
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
    rows: { polish: sumOf(b, "Polish"), epoxy: rowHtml(b, "Epoxy").indexOf("pill base") > 0 },
    // The Proposal step's own edited line followed the base, by the rule the other two base pickers run.
    lines2: clone(blob.price_overrides.lines2), optionsKept: clone(blob.price_overrides.options),
    open: openTab(panel(b)),
  };
}

// ── 6. The combined Epoxy + Polish base ──────────────────────────────────────────────────────────────────
async function combined() {
  const model = polishModel({ tabs: { Epoxy: epoxySection("option") } });
  const b = await open(draft(model));
  const polishTotal = b.api.bid().total, epoxyTotal = b.api.sectionBids().Epoxy.total;
  const hadRow = panel(b).indexOf('data-sh-row="combined"') >= 0;
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
    kinds: B.sectionsOf(sm).map((e) => [e.tab, e.kind]), jobType: B.baseOf(sm).jobType,
    lump: saved.proposal_lump_sum, polishTotal: polishTotal, epoxyTotal: epoxyTotal, savedBase: saved.base_tab_id, savedWorkType: saved.work_type,
    checked: /data-sh-base="combined"[^>]*checked/.test(panel(b)), pills: (panel(b).match(/In the base bid/g) || []).length,
    rowPrice: /Epoxy \+ Polish<\/span><span class="sh-price">([^<]*)</.exec(panel(b))[1], rowType: /Epoxy \+ Polish<\/span>[^]*?<span class="sh-type">([^<]*)</.exec(panel(b))[1],
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
             tabNotes: clone(b.store.blob.tab_notes), options: clone(b.store.blob.price_overrides.options), pricedTabs: (saved.priced_tabs || []).map((t) => t.id),
             nowHidden: !!b.doc.getElementById("sheet-now").hidden },
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
    shownName: /<span class="sh-nm">Garage floor<\/span>/.test(panel(b)), now: text(b, "sheet-now"), maths: text(b, "maths"),
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
  const realAll = el.querySelectorAll;
  el.querySelectorAll = (s) => realAll(s).map((n) => { n.focus = () => focused.push(n.attrs["data-sh-key"]); return n; });
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
           afterRefusedName: afterRefusedName, afterSavedName: afterSavedName };
}

// ── 13. the pure markup: escaping, no dash, nothing for a bid with no sheets to say ─────────────────────────
async function markup() {
  const m = polishModel({ tabs: { Epoxy: epoxySection("option") } });
  m.tabs.Epoxy.label = 'Epoxy <b>"x"</b> & more';
  const view = { open: "Epoxy", bids: { Polish: { total: 100 }, Epoxy: { total: 80 } }, opts: { Epoxy: { is_option: true, show: true, price_mode: "deduct", desc: '"><img src=x>' } },
                 descOpen: { Epoxy: true }, sysDesc: () => 'p"h', sf: 0, icon: (n) => "<svg data-icon=" + n + "></svg>" };
  const h = B.sheetsPanelHtml(m, view);
  const gyp = B.sheetsPanelHtml(B.sectionsForJob(B.freshModel(), "gyp", {}), { open: 'Gyp (USG 1-8")', bids: {} });
  // the panel and the line above the step rail in every state the page can leave them in, for the sweep for dashes
  const broken = polishModel({ tabs: { Epoxy: Object.assign(epoxySection("base"), { layout: undefined }) } });
  const both = polishModel({ tabs: { Epoxy: epoxySection("base") } });
  const base = { open: "Polish", bids: { Polish: { total: 100 }, Epoxy: { total: 80 } }, sf: 100, icon: () => "" };
  const states = [
    h, B.sheetNowHtml(m, view),
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
    escaped: h.indexOf('<b>"x"</b>') < 0 && h.indexOf("&lt;b&gt;&quot;x&quot;&lt;/b&gt; &amp; more") > 0 && h.indexOf("<img") < 0 && h.indexOf("&lt;img src=x&gt;") > 0,
    placeholder: /placeholder="p&quot;h"/.test(h), icons: (h.match(/data-icon=/g) || []).length > 5,
    noDash: h.indexOf(String.fromCharCode(0x2014)) < 0 && B.sheetNowHtml(m, view).indexOf(String.fromCharCode(0x2014)) < 0,
    deduct: sumFigure(h), nowLine: B.sheetNowHtml(m, view), oneSheetNow: B.sheetNowHtml(polishModel(), { open: "Polish", bids: {} }),
    gypAttr: gyp.indexOf('data-section-tab="Gyp (USG 1-8&quot;)"') >= 0, noSf: /It starts empty/.test(B.sheetsPanelHtml(polishModel(), { pick: true })),
    pair: B.combinedPair(m), pairNone: B.combinedPair(polishModel()),
    confirmWords: { epoxy: B.baseChangeWords(m, ["Epoxy"]), same: B.baseChangeWords(B.copySection(polishModel(), "Polish", {}).model, ["Copy1"]), combo: B.baseChangeWords(m, ["Epoxy", "Polish"]) },
    optionIsOn: [B.optionIsOn(undefined, "x"), B.optionIsOn({ x: { is_option: false } }, "x"), B.optionIsOn({ x: { is_option: true, show: false } }, "x"), B.optionIsOn({ x: { is_option: true } }, "x")],
    patch: B.tabOptPatch({ tab_opts: { a: { keep: 1 } } }, "b", { price_mode: "deduct" }),
  };
}
function sumFigure(h) { return ((/class="sh-sum[^"]*">([^<]*)<b>([^<]*)<\/b>/.exec(h)) || []).slice(1, 3).join(" ").replace(/\s+/g, " ").trim(); }

// ── 14. it floats under its own key, and the page keeps a lane for it ──────────────────────────────────────────
async function floating() {
  const b = await open(draft(polishModel()));
  const css = L.read(path.join(ROOT, "polish-estimate.html"));
  const style = css.slice(css.indexOf("<style>"), css.indexOf("</style>"));
  const block = (re) => { const m = re.exec(style); if (!m) return null; let depth = 1, i = m.index + m[0].length; const start = i; while (i < style.length && depth) { if (style[i] === "{") depth++; else if (style[i] === "}") depth--; i++; } return style.slice(start, i - 1); };
  return {
    floats: clone(b.rec.floats || []),
    wide: block(/@media \(min-width:1401px\)\s*\{/), narrow: block(/@media \(max-width:1400px\)\s*\{/),
    markupHasPanelFirst: css.indexOf('id="sheets-panel"') > 0 && css.indexOf('id="sheets-panel"') < css.indexOf('id="rail"'),
    oldStripGone: css.indexOf('id="sections"') < 0 && css.indexOf('id="option-bar"') < 0,
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
const addBlock = (h) => h.slice(h.indexOf('class="sh-add"'), h.indexOf('class="sh-list"'));
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

main().then((out) => { process.stdout.write(JSON.stringify(out) + "\n"); }, (e) => { process.stderr.write(String(e && e.stack || e) + "\n"); process.exit(1); });
