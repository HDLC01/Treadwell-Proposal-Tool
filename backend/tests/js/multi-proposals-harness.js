"use strict";
/* SEVERAL BASE BIDS ON ONE ESTIMATE ("Create Multiple Proposals"), plan step 3: the v1 base picks, RUN rather than read.
 *
 * On a spreadsheet draft the Proposal step's "Pricing options" card draws a Base-bid CHECKBOX per sheet: every ticked sheet
 * is a base bid, tagged "Base Bid N", and becomes its own proposal. The pricing base (base_tab_id) is Base Bid 1 and is
 * kept inside the ticked list (base_tab_ids). Ticking adds; unticking the base moves it to the next ticked sheet; the last
 * one cannot be unticked. A CHILD (a proposal the server made from another draft's estimate) shows its base read-only and
 * says where base bids are picked. The Estimate step keeps the list consistent: its Base-bid boxes, deleting a copy, and the
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
      keepTicked: T.moveBaseId(st("Copy1", ["Epoxy", "Copy1"]), "Epoxy", "Copy1", null, true),
      keepImplicit: T.moveBaseId(st("Copy1", ["Copy1"]), "Epoxy", "Copy1", null, true),
      noKeepTicked: T.moveBaseId(st("Copy1", ["Epoxy", "Copy1"]), "Epoxy", "Copy1"),
      keepUnticked: T.moveBaseId(st("Polish", ["Epoxy", "Copy1"]), "Epoxy", "Polish", null, true),
    },
    child: [T.isProposalChild({ proposal_of: "P-1" }), T.isProposalChild({ proposal_of: "" }), T.isProposalChild({}),
            T.isProposalChild(null), T.isProposalChild({ proposal_of: 5 })],
  };
})();

// ── the Estimate step ────────────────────────────────────────────────────────────────────────────────────────────
const est = (name, deps) => L.lift(EST, name, deps, { indent: "", where: "estimate-review.js" });

// 11. THE BID-BAR BASE-BID BOXES (checkboxes since 2026-10-27, the Proposal card's rule): `steps` are [value, checked]
//     changes delivered in order to the real handler.
function bidBarPick(stateIn, steps) {
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
  for (const [value, checked] of steps) {
    listeners.change({ target: { checked, value, classList: { contains: (c) => c === "bb-base" }, closest: () => null } });
  }
  return { base_tab_id: state.base_tab_id, base_tab_ids: state.base_tab_ids === undefined ? null : state.base_tab_ids, persisted };
}
out.bidBar = {
  // Tick Polish, then untick the base: Polish is the base, Copy1 stays ticked.
  swap: bidBarPick({ base_tab_id: "Epoxy", base_tab_ids: ["Epoxy", "Copy1"] }, [["Polish", true], ["Epoxy", false]]),
  // Untick the base while Base Bid 2 is ticked: Base Bid 2 becomes the base.
  toTicked: bidBarPick({ base_tab_id: "Epoxy", base_tab_ids: ["Epoxy", "Copy1"] }, [["Epoxy", false]]),
  // A draft that never ticked a second sheet: a tick writes the list, the base stays.
  noList: bidBarPick({ base_tab_id: "Epoxy" }, [["Polish", true]]),
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

// ── plan step 4: the proposal page's tabs, its button, the Estimate-changed strip, the child guards ──────────────────
// mountProposalTabs, run over a small DOM against a recording TW and fetch. The page's own repaintNote paints a
// refusal, parentStepHref re-points a child's links, and shared.js's redirectProposalChild / readProposals run whole.
const STRIP_UNITS = [fn("icon"), fn("repaintNote"), fn("parentStepHref"), fn("mountProposalTabs")].join(NL);
const tick = () => new Promise((r) => setTimeout(r, 0));
async function settle() { for (let i = 0; i < 6; i++) await tick(); }

const PARENT_VIEW = { parent_id: "P1", group_id: "G1", estimate_digest: "D2", members: [
  { id: "P1", label: "Base Bid 1", index: 1, is_parent: true, base_tab_id: "Epoxy", stale: false },
  { id: "C2", label: "Room <2>", index: 2, is_parent: false, base_tab_id: "Copy1", stale: true },
  { id: "C3", label: "", index: 3, is_parent: false, base_tab_id: "Polish", stale: false },
] };

/** One proposal page: `id` is the draft it is on, `st` its state, `view` what GET .../proposals answers, `answers`
 *  [regex, method, {status, body}] for the rest. Everything the page asks of TW and fetch is logged in order. */
async function proposalPage(o) {
  const log = [];
  const btn = (id) => ({ id, hidden: false, disabled: false, title: "", textContent: id === "multi-btn" ? "Create Multiple Proposals" : "Refresh",
                         _l: {}, addEventListener(t, f) { (this._l[t] = this._l[t] || []).push(f); },
                         async press() { if (this.disabled) return false; for (const f of this._l.click || []) await f({}); return true; } });
  const els = {
    "proposal-tabs": Object.assign(new El("div"), { hidden: true }),
    "options-panel": new El("div"),
    "multi-btn": btn("multi-btn"),
    "proposals-refresh": btn("proposals-refresh"),
    "proposals-note": { hidden: true },
    "proposals-note-what": { textContent: "" },
    "resync-note": { hidden: true, scrollIntoView() {} },
    "resync-note-head": { textContent: "The PDF has the old numbers." },
    "resync-note-what": { textContent: "x" },
    "resync-note-do": { textContent: "Look over the document below." },
  };
  const document = { getElementById: (id) => els[id] || null };
  const answers = o.answers || [];
  const fetchStub = async (url, init) => {
    const method = (init && init.method) || "GET";
    log.push(["fetch", method, url, init && init.body ? JSON.parse(init.body) : null]);
    const hit = answers.filter(([re, m]) => re.test(url) && m === method)[0];
    const a = hit ? hit[2] : { status: 200, body: { ok: true } };
    return { ok: a.status < 400, status: a.status, json: async () => a.body };
  };
  const TW = {
    getDraftId: () => o.id, resolveApiBase: () => "", authHeaders: () => ({ "Content-Type": "application/json" }),
    readForm: () => ({ texture: "Smooth" }),
    setState: () => { log.push(["setState"]); },
    flushState: async () => { log.push(["flush"]); return o.flush !== false; },
    readServerRow: async () => { log.push(["readRow"]); return o.row === undefined ? { data: {}, version: "V-1" } : o.row; },
    useServerCopy: async () => { log.push(["adopt"]); return o.adopt !== false; },
    readProposals: async (pid) => { log.push(["readProposals", pid]); return o.view === undefined ? clone(PARENT_VIEW) : clone(o.view); },
    setLocalState: (p, opt) => { log.push(["setLocalState", clone(p), clone(opt)]); },
    confirmDanger: async (d) => { log.push(["confirm", d.title, d.name]); return o.confirm !== false; },
  };
  const win = { location: { assign: (h) => log.push(["assign", h]), reload: () => log.push(["reload"]) }, TWAuth: null };
  const st = clone(o.st || { base_tab_id: "Epoxy", base_tab_ids: ["Epoxy", "Copy1", "Polish"],
                             priced_tabs: [{ id: "Epoxy" }, { id: "Copy1" }, { id: "Polish" }] });
  const mod = new Function("state", "document", "TW", "TWPrice", "window", "fetch", "form",
    STRIP_UNITS + NL + "return { mountProposalTabs, parentStepHref };")(
    st, document, TW, globalThis.TWPrice, win, fetchStub, {});
  const api = await mod.mountProposalTabs();
  await settle();
  const strip = els["proposal-tabs"];
  const look = () => ({
    stripHidden: !!strip.hidden,
    tabs: strip.querySelectorAll(".pt-tab").map((li) => {
      const name = li.querySelector(".pt-name");
      return { id: li.dataset.ptId, open: li.classList.contains("open"), stale: !!li.querySelector(".pt-stale"),
               label: (li.querySelector(".pt-nm") || { textContent: null }).textContent,
               selected: name ? name.attrs["aria-selected"] : null, x: !!li.querySelector(".pt-x"),
               renaming: !!li.querySelector(".pt-ren-in") };
    }),
    msg: (strip.querySelector(".pt-msg") || { textContent: null }).textContent,
    note: { hidden: !!els["proposals-note"].hidden, what: els["proposals-note-what"].textContent },
    multi: { hidden: !!els["multi-btn"].hidden, disabled: !!els["multi-btn"].disabled, title: els["multi-btn"].title,
             text: els["multi-btn"].textContent },
    resync: { hidden: !!els["resync-note"].hidden, head: els["resync-note-head"].textContent,
              doIt: els["resync-note-do"].textContent },
  });
  const press = async (cls, pid, type) => {
    const b = strip.querySelectorAll(cls).filter((x) => (x.dataset.ptOpen || x.dataset.ptDel) === pid)[0];
    if (!b) throw new Error("no " + cls + " for " + pid);
    b.fire(type || "click");
    await settle();
  };
  return { log, els, st, api, mod, look, press, strip };
}
const fetches = (p) => p.log.filter((x) => x[0] === "fetch").map((x) => x.slice(1));
const steps = (p) => p.log.map((x) => (x[0] === "fetch" ? x[1] + " " + x[2] : x[0]));

async function step4() {
  const s = {};

  // 14. THE STRIP on Base Bid 1's page: a tab per proposal, this one open, the x on the others only, the
  //     stale one marked and named on the Estimate-changed strip; the button live for three ticked base bids.
  {
    const p = await proposalPage({ id: "P1" });
    s.parent = Object.assign(p.look(), { asked: p.log.filter((x) => x[0] === "readProposals").map((x) => x[1]) });
  }
  // 15. A DRAFT ON ITS OWN: no strip, no note; one ticked base bid leaves the button off, with a title saying why.
  {
    const p = await proposalPage({ id: "S1", view: { parent_id: "S1", members: [{ id: "S1", label: "", index: 1, is_parent: true, stale: false }] },
                                   st: { base_tab_id: "Epoxy", priced_tabs: [{ id: "Epoxy" }, { id: "Copy1" }] } });
    const before = p.look();
    // A tick in the Pricing options card (renderProposalExtras writes state.base_tab_ids) repaints the button.
    p.st.base_tab_ids = ["Epoxy", "Copy1"];
    p.els["options-panel"].fire("change");
    s.alone = { before, afterTick: p.look().multi };
    // Pressed while off: nothing is asked.
    const q = await proposalPage({ id: "S1", view: null, st: { base_tab_id: "Epoxy", priced_tabs: [{ id: "Epoxy" }] } });
    q.log.length = 0;
    await q.api.create();
    s.alone.pressedOff = { log: steps(q), unread: q.look().stripHidden };
  }
  // 16. A CHILD's page: the button is hidden, its own tab is the open one.
  {
    const p = await proposalPage({ id: "C2", st: { proposal_of: "P1", base_tab_id: "Copy1", base_tab_ids: ["Copy1"],
                                                   priced_tabs: [{ id: "Epoxy" }, { id: "Copy1" }] } });
    s.child = p.look();
  }
  // 17. A CLICK ON ANOTHER TAB saves, then opens that proposal's page; a click on the open tab does nothing.
  {
    const p = await proposalPage({ id: "P1" });
    p.log.length = 0;
    await p.press(".pt-name", "P1");
    const self = steps(p);
    await p.press(".pt-name", "C3");
    s.navigate = { self, other: steps(p).concat(p.log.filter((x) => x[0] === "assign").map((x) => x[1])) };
  }
  // 18. CREATE MULTIPLE PROPOSALS: saved, version read, asked of that version with the ticked base bids in order, the
  //     server's copy adopted, the page reloaded.
  {
    const p = await proposalPage({ id: "P1", view: { parent_id: "P1", members: [{ id: "P1", index: 1, is_parent: true }] },
                                   answers: [[/\/api\/draft\/P1\/proposals$/, "POST", { status: 200, body: { ok: true, children: [] } }]] });
    p.log.length = 0;
    const pressed = await p.els["multi-btn"].press();
    await settle();
    s.create = { pressed, steps: steps(p), body: fetches(p)[0] ? fetches(p)[0][2] : null, look: p.look() };
  }
  // 19. A REFUSED CREATE says the server's sentence on the warning strip and adopts nothing.
  {
    const p = await proposalPage({ id: "P1", answers: [[/\/api\/draft\/P1\/proposals$/, "POST", { status: 409,
      body: { ok: false, code: "document_changed", error: "Nothing changed. This project was saved again after this page read it." } }]] });
    p.log.length = 0;
    await p.els["multi-btn"].press();
    await settle();
    s.refused = { steps: steps(p), look: p.look() };
    const q = await proposalPage({ id: "P1", flush: false });
    q.log.length = 0;
    await q.els["multi-btn"].press();
    await settle();
    s.unsaved = { steps: steps(q), look: q.look() };
  }
  // 20. REFRESH: the same order, against .../proposals/refresh; a child's page refreshes through its own id.
  {
    const p = await proposalPage({ id: "C2", st: { proposal_of: "P1", base_tab_id: "Copy1", base_tab_ids: ["Copy1"], priced_tabs: [{ id: "Copy1" }] },
      answers: [[/\/proposals\/refresh$/, "POST", { status: 200, body: { ok: true, refreshed: ["C2", "C3"], skipped: [] } }]] });
    p.log.length = 0;
    await p.els["proposals-refresh"].press();
    await settle();
    s.refresh = { steps: steps(p), body: fetches(p)[0] ? fetches(p)[0][2] : null };
    // A proposal whose sheet left the estimate is skipped; this page's own draft did not change, so it says so without a reload.
    const q = await proposalPage({ id: "P1", answers: [[/\/proposals\/refresh$/, "POST", { status: 200, body: { ok: true,
      refreshed: ["C3"], skipped: [{ id: "C2", label: "Room <2>", code: "sheet_gone" }],
      proposals: { parent_id: "P1", members: [PARENT_VIEW.members[0], Object.assign({}, PARENT_VIEW.members[1], { stale: true }),
                                              Object.assign({}, PARENT_VIEW.members[2], { stale: false })] } } }]] });
    q.log.length = 0;
    await q.els["proposals-refresh"].press();
    await settle();
    s.refreshSkipped = { steps: steps(q), look: q.look() };
    const r = await proposalPage({ id: "P1", answers: [[/\/proposals\/refresh$/, "POST", { status: 409,
      body: { ok: false, code: "document_changed", error: "Nothing changed." } }]] });
    r.log.length = 0;
    await r.els["proposals-refresh"].press();
    await settle();
    s.refreshRefused = { steps: steps(r), look: r.look() };
  }
  // 21. RENAME: a double-click on the open tab opens a box; Enter sends the cleaned name, the strip shows the
  //     server's, and this browser remembers it as already on the server. A double-click on another tab does nothing.
  {
    const p = await proposalPage({ id: "C2", st: { proposal_of: "P1", base_tab_id: "Copy1", priced_tabs: [{ id: "Copy1" }] },
      answers: [[/\/api\/draft\/C2\/scope$/, "POST", { status: 200, body: { ok: true, group_id: "G1", label: "Lab 2" } }]] });
    await p.press(".pt-name", "P1", "dblclick");
    const other = p.look().tabs.map((t) => t.renaming);
    await p.press(".pt-name", "C2", "dblclick");
    const open = p.look().tabs.map((t) => t.renaming);
    const box = p.strip.querySelector(".pt-ren-in");
    box.value = "  Lab   2 ";
    p.log.length = 0;
    box.fire("keydown", { key: "Enter", preventDefault() {} });
    await settle();
    s.rename = { other, open, fetches: fetches(p), local: p.log.filter((x) => x[0] === "setLocalState").map((x) => x.slice(1)),
                 labels: p.look().tabs.map((t) => t.label) };
    // Escape puts the tab back with nothing sent.
    await p.press(".pt-name", "C2", "dblclick");
    p.log.length = 0;
    p.strip.querySelector(".pt-ren-in").fire("keydown", { key: "Escape", preventDefault() {} });
    await settle();
    s.rename.escape = { fetches: fetches(p).length, renaming: p.look().tabs.some((t) => t.renaming) };
  }
  // 22. DELETE: the x asks first; a yes sends the child to the Trash and takes its tab off (Base Bid 1's page stays);
  //     a no sends nothing; a child deleting itself goes to Base Bid 1.
  {
    const p = await proposalPage({ id: "P1" });
    p.log.length = 0;
    await p.press(".pt-x", "C3");
    s.del = { steps: steps(p), tabs: p.look().tabs.map((t) => t.id) };
    const q = await proposalPage({ id: "P1", confirm: false });
    q.log.length = 0;
    await q.press(".pt-x", "C3");
    s.del.cancel = { steps: steps(q), tabs: q.look().tabs.map((t) => t.id) };
    const r = await proposalPage({ id: "C3", st: { proposal_of: "P1", base_tab_id: "Polish", priced_tabs: [{ id: "Polish" }] } });
    r.log.length = 0;
    await r.press(".pt-x", "C3");
    s.del.self = { steps: steps(r), went: r.log.filter((x) => x[0] === "assign").map((x) => x[1]) };
  }
  // 23. THE CHILD'S LINKS: Intake and Estimate open the parent's, Files stays its own; any other draft keeps its links.
  {
    const c = await proposalPage({ id: "C2", st: { proposal_of: "P1", base_tab_id: "Copy1" } });
    const n = await proposalPage({ id: "P1" });
    const hrefs = ["/?edit=1", "/estimate-review.html", "/polish-estimate.html?d=C2", "/polish-intake.html?d=C2", "/done.html?d=C2", "/"];
    s.links = { child: hrefs.map((h) => c.mod.parentStepHref(h)), parent: hrefs.map((h) => n.mod.parentStepHref(h)) };
  }
  return s;
}

// 24. shared.js, WHOLE: redirectProposalChild sends a child (this page's own blob) to its parent and nothing else;
//     readProposals reads the list and answers null on a refusal.
async function sharedJs() {
  const SHARED = L.read(path.join(ROOT, "shared.js"));
  const STAMP = /const STAMP\s*=\s*"([^"]+)"/.exec(SHARED)[1];
  const STATE_KEY = /const STATE_KEY\s*=\s*"([^"]+)"/.exec(SHARED)[1];
  async function load(blob, id, fetchAnswer) {
    const m = new Map();
    if (blob) m.set(STATE_KEY, JSON.stringify(blob));
    const store = { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) };
    const replaced = [];
    const asked = [];
    const loc = { href: "http://x/estimate-review.html?d=" + id, search: "?d=" + id, pathname: "/estimate-review.html",
                  origin: "http://x", assign() {}, replace: (h) => replaced.push(h), reload() {} };
    const win = { addEventListener() {}, removeEventListener() {}, location: loc, history: { replaceState() {} },
                  setTimeout, clearTimeout };
    const doc = { addEventListener() {}, removeEventListener() {}, readyState: "complete", querySelectorAll: () => [],
                  querySelector: () => null, getElementById: () => null,
                  createElement: () => ({ setAttribute() {}, appendChild() {}, style: {}, classList: { add() {}, remove() {} } }),
                  head: { appendChild() {} }, body: { appendChild() {} }, cookie: "" };
    const f = async (url, init) => {
      asked.push(String(url));
      if (/\/proposals$/.test(String(url)) && fetchAnswer) return fetchAnswer;
      return { ok: true, status: 200, json: async () => ({ ok: true, data: blob || {}, updated_at: "V" }) };
    };
    win.fetch = f;
    new Function("window", "document", "localStorage", "sessionStorage", "fetch", "location", SHARED)(win, doc, store, store, f, loc);
    return { TW: win.TW, replaced, asked };
  }
  const r = {};
  {
    const t = await load({ [STAMP]: "C2", project_name: "X", proposal_of: "P1" }, "C2");
    r.child = { answer: t.TW.redirectProposalChild("/estimate-review.html"), replaced: t.replaced };
    const u = await load({ [STAMP]: "C2", project_name: "X", proposal_of: "P1" }, "C2");
    r.childQuery = { answer: u.TW.redirectProposalChild("/?edit=1"), replaced: u.replaced };
  }
  {
    const t = await load({ [STAMP]: "P1", project_name: "X" }, "P1");
    r.parent = { answer: t.TW.redirectProposalChild("/estimate-review.html"), replaced: t.replaced };
  }
  {
    // Another project's blob in this browser while the page is on C2: not provably this page's, so nothing moves.
    const t = await load({ [STAMP]: "OTHER", project_name: "X", proposal_of: "P1" }, "C2");
    r.notThisDraft = { answer: t.TW.redirectProposalChild("/estimate-review.html"), replaced: t.replaced };
  }
  {
    const t = await load({ [STAMP]: "P1" }, "P1", { ok: true, status: 200, json: async () => clone(PARENT_VIEW) });
    const got = await t.TW.readProposals();
    const other = await t.TW.readProposals("C2");
    r.read = { members: got && got.members.map((m) => m.id), asked: t.asked.filter((u) => /\/proposals$/.test(u)),
               other: !!other };
    const q = await load({ [STAMP]: "P1" }, "P1", { ok: false, status: 404, json: async () => ({ ok: false, code: "not_found" }) });
    r.read.missing = await q.TW.readProposals();
  }
  return r;
}

// 25. EACH INTAKE / ESTIMATE PAGE'S OWN GUARD STATEMENT, cut out of the page (the `if` that asks TW.redirectProposalChild)
//     and run with a TW whose guard answers yes (a child) or no: does the page stop there, and at which path did it ask?
function guards() {
  const pages = ["js/estimate-review.js", "js/index.js", "js/polish-intake.js", "js/polish-estimate.js"];
  const res = {};
  for (const rel of pages) {
    const src = L.read(path.join(ROOT, rel));
    const at = src.indexOf("TW.redirectProposalChild(");
    if (at < 0) { res[rel] = null; continue; }
    const start = src.lastIndexOf("if (", src.lastIndexOf("typeof TW.redirectProposalChild", at));
    const head = L.balanced(src, src.indexOf("(", start));
    let rest = src.slice(head + 1).replace(/^\s+/, "");
    const stmt = src.slice(start, head + 1) + " " + (rest[0] === "{" ? rest.slice(0, L.balanced(rest, 0) + 1) : rest.slice(0, rest.indexOf(";") + 1));
    const run = (yes) => {
      const asked = [];
      const TW = { redirectProposalChild: (p) => { asked.push(p); return yes; } };
      const q = { has: (k) => k === "d" };
      // The statement is followed by the rest of the page: reaching "continued" is the page carrying on; a throw or
      // a return before it is the page stopping there.
      let how;
      try {
        how = new Function("TW", "q", "document", stmt + NL + "return 'continued';")(TW, q, {}) === "continued" ? "continued" : "stopped";
      } catch (e) { how = "stopped"; }
      return [how, asked];
    };
    res[rel] = { child: run(true), other: run(false) };
  }
  return res;
}

Promise.all([
  deleteCopy({ base_tab_id: "Epoxy", base_tab_ids: ["Epoxy", "Copy1"], tab_copies: [{ id: "Copy1" }, { id: "Copy2" }] }, "Copy1"),
  deleteCopy({ base_tab_id: "Copy1", base_tab_ids: ["Copy1", "Copy2"], tab_copies: [{ id: "Copy1" }, { id: "Copy2" }] }, "Copy1"),
  deleteCopy({ base_tab_id: "Copy1", base_tab_ids: ["Copy1"], tab_copies: [{ id: "Copy1" }] }, "Copy1"),
  deleteCopy({ base_tab_id: "Epoxy", tab_copies: [{ id: "Copy1" }] }, "Copy1"),
]).then(async ([other, base, lastBase, noList]) => {
  out.deleteTab = { other, base, lastBase, noList };
  out.page = await step4();
  out.shared = await sharedJs();
  out.guards = guards();
  console.log(JSON.stringify(out));
}).catch((e) => { console.error(e && e.stack || e); process.exit(1); });
