"use strict";
/* SEVERAL BASE BIDS ON ONE ESTIMATE ("Create Multiple Proposals"), plan step 3: the v1 base picks, RUN rather than read.
 *
 * On a spreadsheet draft the Proposal step's "Pricing options" card draws a Base-bid CHECKBOX per sheet: every ticked sheet
 * is a base bid, tagged "Base Bid N", and becomes its own proposal. The pricing base (base_tab_id) is Base Bid 1 and is
 * kept inside the ticked list (base_tab_ids). Ticking adds; unticking the base moves it to the next ticked sheet; the last
 * one cannot be unticked. A CHILD (a proposal the server made from another draft's estimate) shows its base read-only and
 * says where base bids are picked. The Estimate step keeps the list consistent: its base radio, deleting a copy, and the
 * per-tab phase / cost figures the server copies into a child.
 *
 * What runs here is the pages' own code, lifted by name (the same proposal-review.js units v2-options-panel-harness.js
 * lifts, and estimate-review.js's wireBidBar / deleteTab / snapshotLumpSumsToState) over a small DOM; TWPrice is the real
 * price-lines-core.js, loaded whole.
 *
 * Usage: node multi-proposals-harness.js <frontend-dir>   ->  one line of JSON
 */
const path = require("path");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const SRC = L.read(path.join(ROOT, "js", "proposal-review.js"));
const EST = L.read(path.join(ROOT, "js", "estimate-review.js"));
const B = require(path.join(ROOT, "js", "bid-model.js"));
globalThis.TWPrice = require(path.join(ROOT, "js", "price-lines-core.js"));
const SNAPSHOTS = require("./v2-proposal-snapshot-harness.js").build(B);

const clone = (x) => (x === undefined ? undefined : JSON.parse(JSON.stringify(x)));
const NL = "\n";
const top = (name) => L.grabConst(SRC, name, { indent: "  ", where: "proposal-review.js" });
const fn = (name) => L.liftSource(SRC, name, { indent: "  ", where: "proposal-review.js" });

// ── the smallest DOM the panel needs (v2-options-panel-harness.js's) ─────────────────────────────────────────────────
const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'", nbsp: " " };
const unesc = (s) => String(s).replace(/&(#39|amp|lt|gt|quot|nbsp);/g, (_, k) => ENTITIES[k]);
function matches(el, sel) {
  return String(sel).split(",").some((one) => {
    const part = one.trim();
    if (!part) return false;
    const tag = /^[a-zA-Z][\w-]*/.exec(part);
    if (tag && el.tagName !== tag[0].toUpperCase()) return false;
    for (const m of part.matchAll(/\.([\w-]+)/g)) if (!el.classList.contains(m[1])) return false;
    return true;
  });
}
class Text { constructor(v) { this.nodeType = 3; this.nodeValue = String(v); this.parentNode = null; } }
class El {
  constructor(tag) {
    this.nodeType = 1;
    this.tagName = String(tag).toUpperCase();
    this.childNodes = [];
    this.parentNode = null;
    this.style = {};
    this.attrs = {};
    this._classes = new Set();
    this._listeners = new Map();
    const self = this;
    this.dataset = {};
    this.classList = { contains: (c) => self._classes.has(c), add: (c) => self._classes.add(c), remove: (c) => self._classes.delete(c) };
  }
  get children() { return this.childNodes.filter((n) => n.nodeType === 1); }
  appendChild(c) { c.parentNode = this; this.childNodes.push(c); return c; }
  removeChild(c) { const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1); c.parentNode = null; return c; }
  get textContent() { return this.childNodes.map((n) => (n.nodeType === 3 ? n.nodeValue : n.textContent)).join(""); }
  get innerHTML() { return this._html || ""; }
  set innerHTML(html) {
    this._html = html;
    while (this.childNodes.length) this.removeChild(this.childNodes[0]);
    const stack = [this];
    const re = /<\/([a-zA-Z][\w-]*)\s*>|<([a-zA-Z][\w-]*)((?:\s+[\w-]+(?:="[^"]*")?)*)\s*\/?>|([^<]+)/g;
    let m;
    while ((m = re.exec(html))) {
      const tail = stack[stack.length - 1];
      if (m[1]) { if (stack.length > 1) stack.pop(); }
      else if (m[2]) {
        const el = new El(m[2]);
        for (const a of m[3].matchAll(/([\w-]+)(?:="([^"]*)")?/g)) {
          const v = a[2] === undefined ? "" : unesc(a[2]);
          Object.assign(el.attrs, Object.fromEntries([[a[1], v]]));
          if (a[1] === "class") v.split(/\s+/).filter(Boolean).forEach((c) => el._classes.add(c));
          else if (a[1] === "style") el.style.raw = v;
          else if (a[1].startsWith("data-")) {
            Object.assign(el.dataset, Object.fromEntries([[a[1].slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase()), v]]));
          }
        }
        if (el.tagName === "INPUT") { el.value = el.attrs.value || ""; el.checked = "checked" in el.attrs; }
        if (el.tagName === "SELECT") el.value = "";
        tail.appendChild(el);
        if (el.tagName !== "BR" && el.tagName !== "INPUT") stack.push(el);
      } else if (m[4] !== undefined) tail.appendChild(new Text(unesc(m[4])));
    }
    for (const s of this.querySelectorAll("select")) {
      const o = s.querySelectorAll("option").filter((x) => "selected" in x.attrs)[0] || s.querySelectorAll("option")[0];
      s.value = o ? o.attrs.value : "";
    }
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  querySelectorAll(sel) {
    const out = [];
    for (const c of this.children) { if (matches(c, sel)) out.push(c); out.push(...c.querySelectorAll(sel)); }
    return out;
  }
  addEventListener(type, f) { this._listeners.set(type, (this._listeners.get(type) || []).concat([f])); }
  handlers(type) { return this._listeners.get(type) || []; }
  /** What a browser does with a change on a control: a DISABLED control takes no event at all. */
  fire(type, props) {
    if ("disabled" in this.attrs) return false;
    const e = Object.assign({ type, target: this }, props || {});
    this.handlers(type).forEach((f) => f(e));
    return true;
  }
}
function rowEl(id) {
  const o = { id, textContent: "", dataset: {}, style: { display: "" }, title: "", _classes: new Set(),
              removeAttribute() { this.title = ""; }, appendChild() {}, _html: "",
              get innerHTML() { return this._html; }, set innerHTML(v) { this._html = v; } };
  o.classList = { toggle(c, on) { if (on) o._classes.add(c); else o._classes.delete(c); }, contains(c) { return o._classes.has(c); } };
  return o;
}

// ── the Proposal step's real units (v2-options-panel-harness.js's lift list) ─────────────────────────────────────────
const UNITS = [
  top("fmtUSD"), top("fmtUSDdoc"), top("fmtSF"), top("_OVERRIDE_TITLE"), top("COMPUTED_PRICE_LINE_KEYS"), top("_LIVE_TITLE"),
  top("_MONEY_TITLE"), top("_escLine"), top("GYP_BASE"),
  fn("effectiveWorkType"), fn("basePriceSystem"), fn("taxLayout"), fn("taxTreatmentMode"), fn("baseTaxRule"), fn("printedTaxRows"),
  fn("baseBidFigure"), fn("lineOverride"), fn("lineValue"), fn("lineCue"), fn("linePropsOf"), fn("paintLineParas"),
  fn("extraLinesHtml"), fn("lineEl"), fn("paintExtras"), fn("makeExtraLine"), fn("paintLine"), fn("comboSystemLines"),
  fn("comboLinesForPayload"), fn("baseDescLabel"), fn("refreshPriceDisplay"), fn("paintOptionsGap"),
  top("SINGLE_LINE_EM"), fn("paraLineHeight"), fn("applyParaSpacing"), fn("priceLineRecord"), fn("gapModelRecord"),
  top("TWIPS_PER_PT"), top("LINE_SEL"), fn("lineAt"),
  "const blockById = new Map();",
  fn("aboveOptionsGap"), fn("gapShown"), fn("isGapTyped"), fn("gapTypedEls"),
  fn("renderProposalExtras"), fn("computeTokenValues"), fn("priceRowVisibility"),
  top("OPTION_ONLY_ROLES"), top("COMBINED_BASE_ROLES"), top("roleOfTab"), top("isOptionOnlyTab"), top("inCombinedBase"),
  fn("baseAreaFrom"), top("PAYLOAD_PRICING_KEYS"), fn("pruneComputedPriceLineOverrides"), fn("syncPayloadPricing"),
  fn("rebuildPricing"),
].join(NL);

function open(st) {
  const panel = new El("div");
  panel.hidden = true;
  const rows = {};
  for (const id of ["base-bid-heading", "combo-price-block", "base-bid-row", "sales-tax-row", "remodel-tax-row", "total-row",
                    "options-heading", "rooms-block", "price-lines-block", "alternate-block"]) rows[id] = rowEl(id);
  const tbTotal = { textContent: "$0.00" };
  const document = {
    querySelector: (sel) => (sel === "#tb-total" ? tbTotal : null),
    getElementById: (id) => (id === "options-panel" ? panel : (rows[id] || null)),
  };
  const sets = [];
  const reloads = [];
  const TW = { readForm: () => ({}), setState: (patch) => { sets.push(clone(patch)); },
               withDraft: (p) => p + (p.indexOf("?") >= 0 ? "&" : "?") + "d=DRAFT-1" };
  const body = UNITS + NL + "return { renderProposalExtras, rebuildPricing, refreshPriceDisplay, effectiveWorkType };";
  const api = new Function("state", "document", "form", "TW", "window", "templateBlocks", "focusInside", "lineAtSelection",
                           "scheduleFit", "reloadForWorkType", body)(
    st, document, { querySelector: () => null }, TW, { TWAuth: null }, null, () => false, () => null,
    () => {}, () => { reloads.push(1); });
  api.rebuildPricing();
  api.refreshPriceDisplay();
  return { st, api, panel, sets, reloads };
}

const boxes = (p) => p.panel.querySelectorAll("input.pr-base");
const boxOf = (p, id) => boxes(p).filter((b) => b.attrs.value === id)[0] || null;
const rowOf = (p, id) => p.panel.querySelectorAll(".op-row").filter((r) => r.dataset.id === id)[0] || null;
/** Tick or untick one sheet's box as a person would (a disabled one takes no event). */
function setBox(p, id, on) {
  const b = boxOf(p, id);
  if (!b) throw new Error("no Base-bid box for " + JSON.stringify(id));
  b.checked = on;
  return { fired: b.fire("change"), box: b };
}
function look(p) {
  return {
    boxes: boxes(p).map((b) => ({ value: b.attrs.value, type: b.attrs.type, name: b.attrs.name === undefined ? null : b.attrs.name,
                                  checked: !!b.checked, disabled: "disabled" in b.attrs })),
    tags: Object.fromEntries(p.panel.querySelectorAll(".op-row").map((r) => {
      const t = r.querySelector(".pr-bidtag");
      return [r.dataset.id, t ? t.textContent : null];
    })),
    notes: Object.fromEntries(p.panel.querySelectorAll(".op-row").map((r) => {
      const n = r.querySelector(".pr-base-note");
      return [r.dataset.id, n ? n.textContent : null];
    })),
    isopt: Object.fromEntries(p.panel.querySelectorAll(".op-row").map((r) => [r.dataset.id, !!r.querySelector(".pr-isopt")])),
    locked: (() => { const h = p.panel.querySelector(".pr-base-locked"); return h ? h.textContent : null; })(),
    parentLink: (() => { const a = p.panel.querySelector(".pr-parent-link"); return a ? a.attrs.href : null; })(),
    base_tab_id: p.st.base_tab_id === undefined ? null : p.st.base_tab_id,
    base_tab_ids: p.st.base_tab_ids === undefined ? null : clone(p.st.base_tab_ids),
    lump: p.st.proposal_lump_sum,
    reloads: p.reloads.length,
  };
}
/** The saves, merged in order: what the draft holds after the page's writes. */
const merged = (p) => Object.assign({}, ...p.sets);
const savedKey = (p, k) => p.sets.some((s) => Object.prototype.hasOwnProperty.call(s, k));
/** The same bids as the spreadsheet would save them: the v2 marks taken off. */
const sheet = (name, edit) => {
  const s = clone(SNAPSHOTS[name].state);
  s.priced_tabs.forEach((t) => { delete t.v2; });
  delete s.polish_estimate;
  if (edit) edit(s);
  return s;
};
const out = {};

// 1. THE CHECKBOX ROWS. A spreadsheet Epoxy bid: a box per sheet that can be a base (none on Seal), the base ticked and
//    tagged "Base Bid 1", no radio group name.
out.rows = (() => {
  const p = open(sheet("epoxy"));
  return Object.assign(look(p), { anyBaseIdsSaved: savedKey(p, "base_tab_ids") });
})();

// 2. A TICK ADDS A BASE BID; the base stays, the price stays, the sheet stops being an option, nothing reloads.
out.tick = (() => {
  const p = open(sheet("epoxy", (s) => { s.tab_opts.Copy1 = Object.assign({}, s.tab_opts.Copy1 || {}, { is_option: true, show: true }); }));
  const before = look(p);
  const r = setBox(p, "Copy1", true);
  const one = Object.assign(look(p), { fired: r.fired, saved: clone(merged(p).base_tab_ids), copyIsOption: p.st.tab_opts.Copy1.is_option,
                                       roomIds: (p.st.rooms || []).map((x) => x.id) });
  setBox(p, "Polish", true);
  const two = Object.assign(look(p), { saved: clone(merged(p).base_tab_ids) });
  return { before, one, two };
})();

// 3. UNTICKING THE BASE MOVES IT to the next ticked sheet (Base Bid 1 now), re-prices and reloads for its work type.
out.untickBase = (() => {
  const p = open(sheet("epoxy"));
  setBox(p, "Copy1", true);
  setBox(p, "Polish", true);
  const r = setBox(p, "Epoxy", false);
  return Object.assign(look(p), { fired: r.fired, saved: { base_tab_id: merged(p).base_tab_id, base_tab_ids: clone(merged(p).base_tab_ids) } });
})();

// 4. UNTICKING ANOTHER base bid takes it off and leaves the base where it was.
out.untickOther = (() => {
  const p = open(sheet("epoxy"));
  setBox(p, "Copy1", true);
  setBox(p, "Copy1", false);
  return look(p);
})();

// 5. THE LAST ONE CANNOT BE UNTICKED: the box goes back on, the base and the list are as they were, the row says why.
out.last = (() => {
  const p = open(sheet("epoxy"));
  const setsBefore = p.sets.length;
  const r = setBox(p, "Epoxy", false);
  return Object.assign(look(p), { fired: r.fired, boxChecked: !!r.box.checked, savesByRefusal: p.sets.length - setsBefore });
})();

// 6. A CHILD: its base ticked and every box read-only, the hint names its base and links to Base Bid 1's proposal, and a
//    change forced at a box changes nothing.
out.child = (() => {
  const p = open(sheet("epoxy", (s) => {
    s.proposal_of = "PARENT-1"; s.base_tab_id = "Copy1"; s.base_tab_ids = ["Copy1"];
    s.scope_group = { id: "G-1", label: "Base Bid 2" };
  }));
  const before = look(p);
  const attempts = boxes(p).map((b) => { b.checked = !b.checked; return b.fire("change"); });
  const forced = boxes(p).map((b) => { b.handlers("change").forEach((h) => h({ type: "change", target: b })); return b.handlers("change").length; });
  return Object.assign(before, { attempts, forced, after: { base_tab_id: p.st.base_tab_id, base_tab_ids: clone(p.st.base_tab_ids) },
                                 reloadsAfter: p.reloads.length, isopt: look(p).isopt });
})();

// 7. A v2 DRAFT KEEPS ITS READ-ONLY RADIOS (its base bids are picked on the v2 strip).
out.v2 = (() => look(open(clone(SNAPSHOTS.epoxy.state))))();

// 8. rebuildPricing KEEPS THE BASE IN THE LIST when it refuses an option-only base: the base it resolves takes its place.
//    A draft that never ticked a second sheet gets no list written.
out.rebuild = (() => {
  const p = open(sheet("epoxy", (s) => { s.base_tab_id = "Seal"; s.base_tab_ids = ["Seal", "Copy1"]; }));
  const q = open(sheet("epoxy", (s) => { s.base_tab_id = "Seal"; }));
  const k = open(sheet("epoxy", (s) => { s.base_tab_ids = ["Epoxy", "Copy1"]; }));
  return { refused: { base_tab_id: p.st.base_tab_id, base_tab_ids: clone(p.st.base_tab_ids), saved: clone(merged(p).base_tab_ids) },
           noList: { base_tab_id: q.st.base_tab_id, base_tab_ids: q.st.base_tab_ids === undefined ? null : q.st.base_tab_ids,
                     saved: savedKey(q, "base_tab_ids") },
           kept: { base_tab_ids: clone(k.st.base_tab_ids) } };
})();

// 9. A COMBO'S COMBINED BASE is one base on its own: ticking a sheet replaces it, ticking it back clears the list.
out.combined = (() => {
  const p = open(sheet("combined"));
  const start = look(p);
  setBox(p, "Epoxy", true);
  const sheetPicked = look(p);
  setBox(p, "Copy1", true);
  const two = look(p);
  setBox(p, "", true);
  return { start, sheetPicked, two, back: look(p) };
})();

// 10. THE TWPrice HELPERS, by themselves.
out.core = (() => {
  const T = globalThis.TWPrice;
  const tabs = [{ id: "Polish" }, { id: "Copy1" }, { id: "Epoxy" }, { id: "Copy2" }];
  const st = (base, ids, extra) => Object.assign({ base_tab_id: base, priced_tabs: tabs }, ids === undefined ? {} : { base_tab_ids: ids }, extra || {});
  return {
    ids: {
      none: T.baseIds(st("Epoxy")),
      ordered: T.baseIds(st("Epoxy", ["Copy2", "Epoxy", "Polish", "Copy2", "", 7])),
      baseMissing: T.baseIds(st("Copy2", ["Polish"])),
      gone: T.baseIds(st("Epoxy", ["Gone", "Copy1"])),
      explicitOrder: T.baseIds(st("Epoxy", ["Polish", "Copy1"]), ["Epoxy", "Copy1", "Polish"]),
      noBase: T.baseIds(st(null, ["Copy1"])),
      notState: T.baseIds(null),
    },
    labels: [T.baseLabelFor(st("Epoxy", ["Copy1", "Polish"]), "Epoxy"), T.baseLabelFor(st("Epoxy", ["Copy1", "Polish"]), "Polish"),
             T.baseLabelFor(st("Epoxy", ["Copy1", "Polish"]), "Copy1"), T.baseLabelFor(st("Epoxy", ["Copy1", "Polish"]), "Copy2")],
    toggle: {
      add: T.toggleBaseId(st("Epoxy"), "Copy1", true),
      addAgain: T.toggleBaseId(st("Epoxy", ["Epoxy", "Copy1"]), "Copy1", true),
      dropOther: T.toggleBaseId(st("Epoxy", ["Epoxy", "Copy1"]), "Copy1", false),
      dropBase: T.toggleBaseId(st("Epoxy", ["Epoxy", "Polish", "Copy1"]), "Epoxy", false),
      dropLast: T.toggleBaseId(st("Epoxy"), "Epoxy", false),
      dropUnticked: T.toggleBaseId(st("Epoxy"), "Copy1", false),
      combinedOn: T.toggleBaseId(st("Epoxy", ["Epoxy", "Copy1"]), "", true),
      combinedOff: T.toggleBaseId(st(null), "", false),
      sheetOverCombined: T.toggleBaseId(st(null), "Copy1", true),
    },
    move: {
      swap: T.moveBaseId(st("Polish", ["Epoxy", "Copy1"]), "Epoxy", "Polish"),
      toNull: T.moveBaseId(st(null, ["Epoxy", "Copy1"]), "Epoxy", null),
      ordered: T.moveBaseId(st("Copy2", ["Epoxy", "Polish"]), "Epoxy", "Copy2", ["Copy2", "Polish", "Epoxy"]),
    },
    child: [T.isProposalChild({ proposal_of: "P-1" }), T.isProposalChild({ proposal_of: "" }), T.isProposalChild({}),
            T.isProposalChild(null), T.isProposalChild({ proposal_of: 5 })],
  };
})();

// ── the Estimate step ────────────────────────────────────────────────────────────────────────────────────────────
const est = (name, deps) => L.lift(EST, name, deps, { indent: "", where: "estimate-review.js" });

// 11. THE BID-BAR BASE RADIO moves the base; the new base takes the old one's place among the ticked sheets.
function bidBarPick(stateIn, pick) {
  const state = Object.assign({ work_type: "epoxy", tab_opts: {}, price_overrides: {} }, clone(stateIn));
  const listeners = {};
  const list = { addEventListener: (type, f) => { listeners[type] = f; } };
  const tabs = [{ id: "Epoxy", role: "epoxy", kind: "base" }, { id: "Polish", role: "polish", kind: "base" },
                { id: "Copy1", role: "epoxy", kind: "copy" }];
  let persisted = 0;
  est("wireBidBar", {
    state, tabs, document: { getElementById: (id) => (id === "bid-options-list" ? list : null) },
    TWPrice: globalThis.TWPrice, renderBidOptions: () => {}, persistBidOptions: () => {},
    persistTabState: () => { persisted++; }, HF: { ready: false }, updateTotalBarFromHF: () => {},
    ensureOpt: () => ({}), TW: { setState: () => {} },
  })();
  listeners.change({ target: { checked: true, value: pick, classList: { contains: (c) => c === "bb-base" }, closest: () => null } });
  return { base_tab_id: state.base_tab_id, base_tab_ids: state.base_tab_ids === undefined ? null : state.base_tab_ids, persisted };
}
out.bidBar = {
  swap: bidBarPick({ base_tab_id: "Epoxy", base_tab_ids: ["Epoxy", "Copy1"] }, "Polish"),
  toTicked: bidBarPick({ base_tab_id: "Epoxy", base_tab_ids: ["Epoxy", "Copy1"] }, "Copy1"),
  noList: bidBarPick({ base_tab_id: "Epoxy" }, "Polish"),
};

// 12. DELETING A COPY takes it off the ticked sheets; deleting the BASE copy moves the base to the next ticked one.
function deleteCopy(stateIn, id) {
  const state = Object.assign({ work_type: "epoxy", tab_labels: {}, tab_notes: {}, tab_opts: {}, lock_overrides: {},
                                price_overrides: {}, priced_tabs: [] }, clone(stateIn));
  const saved = [];
  const tabs = [{ id: "Epoxy", role: "epoxy", kind: "base" }];
  const deleteTab = est("deleteTab", {
    state, TW: { confirmDanger: async () => true, setState: (s) => { saved.push(clone({ base_tab_id: s.base_tab_id, base_tab_ids: s.base_tab_ids })); } },
    HF: { removeSheet: () => {} }, BASE_ROLE: {}, sheets: ["Epoxy", "Polish"], cellValues: {}, sheetCache: {},
    activeSheet: "Epoxy", labelFor: (x) => x, buildTabs: () => {}, renderTabs: () => {}, showSheet: () => {},
    defaultBaseSheet: () => "Epoxy", reKeyPriceLineOverrides: () => {}, tabs, TWPrice: globalThis.TWPrice,
    // The derived base after the base copy goes (the real one reads `tabs`, which no longer holds the copy).
    resolveBaseTab: () => (state.base_tab_id ? { id: state.base_tab_id } : tabs[0]),
  });
  return deleteTab(id).then(() => ({ base_tab_id: state.base_tab_id, base_tab_ids: state.base_tab_ids === undefined ? null : state.base_tab_ids,
                                     saved: saved[saved.length - 1] }));
}

// 13. THE PRICING SNAPSHOT carries each tab's own phase surcharge, costs and man-hours (the server copies them into the
//     proposal it makes of that tab).
out.snapshot = (() => {
  const TOTAL_CELLS = new Function(L.grabConst(EST, "TOTAL_CELLS", { indent: "" }) + NL + "return TOTAL_CELLS;")();
  const E = TOTAL_CELLS.Epoxy, P = TOTAL_CELLS.Polish;
  const values = {
    Epoxy: { [E.total]: 10000, [E.phase]: 4500, [E.costs]: 6100, [E.man_hours]: 40.4 },
    Copy1: { [E.total]: 8000, [E.phase]: 3900, [E.costs]: 5200, [E.man_hours]: 31.6 },
    Polish: { [P.total]: 12000, [P.phase]: 5100, [P.costs]: 7300, [P.man_hours]: 52 },
  };
  const tabs = [{ id: "Epoxy", role: "epoxy", kind: "base" }, { id: "Polish", role: "polish", kind: "base" },
                { id: "Copy1", role: "epoxy", kind: "copy" }];
  const roleOf = (id) => (tabs.find((t) => t.id === id) || {}).role;
  const layoutOf = (id) => (id === "Copy1" ? "Epoxy" : id);
  const state = { work_type: "epoxy", base_tab_id: "Epoxy", tab_opts: {}, tab_notes: {} };
  est("snapshotLumpSumsToState", {
    state, tabs, HF: { ready: true, getValue: (s, a) => ((values[s] || {})[a] ?? null) },
    totalCellsFor: (id) => TOTAL_CELLS[layoutOf(id)], TOTAL_CELLS, resolveBaseTab: () => tabs[0],
    layoutIdFor: layoutOf, JOB_FLAG_LAYOUTS: [], txAddr: (id, a) => a, jobFlagAddrFor: () => null, GYP_BASE: "Gyp",
    roleFor: roleOf, deriveSystemNameFor: (id) => id, labelFor: (id) => id, deriveNotes: () => [],
    pricedTabs: () => tabs, isInCombinedBase: () => false, sfFieldsFor: () => ({}), sysNamesFor: () => [],
    jobFlagCellsFor: () => ({}), baseAreaFrom: () => ({}),
  })();
  return Object.fromEntries(state.priced_tabs.map((t) => [t.id, { phase: t.phase === undefined ? null : t.phase,
                                                                   costs: t.costs === undefined ? null : t.costs,
                                                                   man_hours: t.man_hours === undefined ? null : t.man_hours }]));
})();

Promise.all([
  deleteCopy({ base_tab_id: "Epoxy", base_tab_ids: ["Epoxy", "Copy1"], tab_copies: [{ id: "Copy1" }, { id: "Copy2" }] }, "Copy1"),
  deleteCopy({ base_tab_id: "Copy1", base_tab_ids: ["Copy1", "Copy2"], tab_copies: [{ id: "Copy1" }, { id: "Copy2" }] }, "Copy1"),
  deleteCopy({ base_tab_id: "Copy1", base_tab_ids: ["Copy1"], tab_copies: [{ id: "Copy1" }] }, "Copy1"),
  deleteCopy({ base_tab_id: "Epoxy", tab_copies: [{ id: "Copy1" }] }, "Copy1"),
]).then(([other, base, lastBase, noList]) => {
  out.deleteTab = { other, base, lastBase, noList };
  console.log(JSON.stringify(out));
}).catch((e) => { console.error(e && e.stack || e); process.exit(1); });
