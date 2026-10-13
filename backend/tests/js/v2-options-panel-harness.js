"use strict";
/* THE PROPOSAL STEP'S "Pricing options" PANEL ON A DRAFT THE v2 ESTIMATE SAVED, RUN rather than read.
 *
 * Sheets phase 4. A v2 estimate saves its bid as a price snapshot (priced_tabs, every tab marked `v2: true`), and the base
 * bid is picked on the estimate: each v2 option was priced with its own travel beside the base it was priced against, so a
 * base switched on the Proposal step would print a price nobody worked out. So on such a draft the panel's base radios are
 * READ-ONLY, they say where to pick the base and link to the estimate, and everything else in the panel (an option on or off,
 * total or add / deduct, the description, the notes) stays live and writes the keys it always wrote. A draft from the
 * spreadsheet is untouched.
 *
 * What runs here is the page's own code, lifted from js/proposal-review.js by name (renderProposalExtras, rebuildPricing,
 * refreshPriceDisplay and what they call) and driven over a small DOM: the panel's markup is parsed, its radios and boxes are
 * found by the same selectors the page wires, and a change is fired at them as a browser would. The drafts are the real
 * model's (v2-proposal-snapshot-harness.js: copySection, activateSection, pickBase, composePricingSnapshot).
 *
 * Usage: node v2-options-panel-harness.js <frontend-dir>   ->  one line of JSON
 */
const path = require("path");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const SRC = L.read(path.join(ROOT, "js", "proposal-review.js"));
const SHARED = L.read(path.join(ROOT, "shared.js"));
const B = require(path.join(ROOT, "js", "bid-model.js"));
// The price rule's page half, a script the page loads before proposal-review.js; the lifted code reads it as the bare global.
globalThis.TWPrice = require(path.join(ROOT, "js", "price-lines-core.js"));
const SNAPSHOTS = require("./v2-proposal-snapshot-harness.js").build(B);

const clone = (x) => (x === undefined ? undefined : JSON.parse(JSON.stringify(x)));
const NL = "\n";
const top = (name) => L.grabConst(SRC, name, { indent: "  ", where: "proposal-review.js" });
const fn = (name) => L.liftSource(SRC, name, { indent: "  ", where: "proposal-review.js" });

// ── the smallest DOM the panel needs (the shim price-lines-harness.js uses, cut to what is read here) ──────────────────
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
    // bare attributes too (`checked`, `disabled`, `selected`): the panel's radios and options carry them
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
    // a <select>'s value is its selected <option>'s, as a browser reads it
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
/** A plain element double for the rows the price writers paint (price-block-harness.js's). */
function rowEl(id) {
  const o = { id, textContent: "", dataset: {}, style: { display: "" }, title: "", _classes: new Set(),
              removeAttribute() { this.title = ""; }, appendChild() {}, _html: "",
              get innerHTML() { return this._html; }, set innerHTML(v) { this._html = v; } };
  o.classList = { toggle(c, on) { if (on) o._classes.add(c); else o._classes.delete(c); }, contains(c) { return o._classes.has(c); } };
  return o;
}

// ── the real units, in dependency order (the same list price-block-harness.js lifts, so the two run one page) ───────────
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

/** One page on one draft. `st` is the draft (the page mutates it in place, as the real one does its `state`). */
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
  const fits = [];
  const TW = { readForm: () => ({}), setState: (patch) => { sets.push(clone(patch)); },
               withDraft: (p) => p + (p.indexOf("?") >= 0 ? "&" : "?") + "d=DRAFT-1" };
  const body = UNITS + NL + "return { renderProposalExtras, rebuildPricing, refreshPriceDisplay, effectiveWorkType };";
  const api = new Function("state", "document", "form", "TW", "window", "templateBlocks", "focusInside", "lineAtSelection",
                           "scheduleFit", "reloadForWorkType", body)(
    st, document, { querySelector: () => null }, TW, { TWAuth: null }, null, () => false, () => null,
    () => { fits.push(1); }, () => { reloads.push(1); });
  api.rebuildPricing();
  api.refreshPriceDisplay();
  return { st, api, panel, sets, reloads, fits, rows };
}

const radios = (p) => p.panel.querySelectorAll("input.pr-base");
const rowOf = (p, id) => p.panel.querySelectorAll(".op-row").filter((r) => r.dataset.id === id)[0] || null;
const radioState = (r) => ({ value: r.attrs.value, checked: !!r.checked, disabled: "disabled" in r.attrs });
/** What the panel offered for one sheet's row. */
function rowFacts(p, id) {
  const r = rowOf(p, id);
  if (!r) return null;
  const mode = r.querySelector(".pr-mode");
  return {
    base: !!r.querySelector(".pr-base"),
    isOption: r.querySelector(".pr-isopt") ? !!r.querySelector(".pr-isopt").checked : null,
    show: r.querySelector(".pr-show") ? !!r.querySelector(".pr-show").checked : null,
    mode: mode ? mode.value : null,
    desc: !!r.querySelector(".room-desc"), notes: !!r.querySelector(".room-notes"),
    totalOnly: !!r.querySelector(".pr-total-only"), deductHint: !!r.querySelector(".pr-deduct-hint"),
    text: r.textContent,
  };
}
function facts(p) {
  const hint = p.panel.querySelector(".pr-base-locked");
  const link = p.panel.querySelector(".pr-est-link");
  return {
    hidden: !!p.panel.hidden,
    locked: !!hint,
    hint: hint ? hint.textContent : null,
    link: link ? link.attrs.href : null,
    radios: radios(p).map(radioState),
    rows: Object.fromEntries(p.panel.querySelectorAll(".op-row").map((r) => [r.dataset.id, rowFacts(p, r.dataset.id)])),
    addSystem: !!p.panel.querySelector(".pr-addsys-btn"),
    base_tab_id: p.st.base_tab_id === undefined ? null : p.st.base_tab_id,
    lump: p.st.proposal_lump_sum,
    work_type: p.api.effectiveWorkType(),
    rooms: (p.st.rooms || []).map((r) => [r.id, r.is_base, r.price_mode, r.bid.total]),
  };
}
/** The saves that carried a key, merged in order: what the draft holds after the page's writes. */
const merged = (p) => Object.assign({}, ...p.sets);

const draft = (name, edit) => { const s = clone(SNAPSHOTS[name].state); if (edit) edit(s); return s; };
const unmarked = (s) => { s.priced_tabs.forEach((t) => { delete t.v2; }); return s; };
const out = {};

// 1. EVERY DRAFT THE v2 ESTIMATE CAN SAVE: the base radios are drawn disabled, the hint says where to pick the base, the link
//    goes to the estimate with this draft's id, and a change fired at a radio changes nothing.
out.locked = {};
for (const name of ["polish", "epoxy", "combined", "copy"]) {
  const p = open(draft(name));
  const before = { base: p.st.base_tab_id === undefined ? null : p.st.base_tab_id, lump: p.st.proposal_lump_sum };
  const f = facts(p);
  const savesBefore = p.sets.length;
  // a person cannot change a disabled radio; a browser gives it no event, so none is delivered here
  const attempts = radios(p).map((r) => { r.checked = true; return r.fire("change"); });
  // ...and a script that dispatches one at it anyway reaches no handler, because none was wired
  const forced = radios(p).map((r) => { r.checked = true; r.handlers("change").forEach((h) => h({ type: "change", target: r })); return r.handlers("change").length; });
  const after = facts(p);
  out.locked[name] = Object.assign(f, {
    attempts: attempts, forcedHandlers: forced, afterAttempt: { base: after.base_tab_id, lump: after.lump }, before: before,
    savesByAttempts: p.sets.length - savesBefore, reloads: p.reloads.length,
  });
}

// 2. THE SAME BIDS AS A SPREADSHEET WROTE THEM (the marks taken off): the radios are live, the old hint is there, and a pick
//    moves the base.
out.live = {};
for (const name of ["polish", "epoxy"]) {
  const p = open(draft(name, unmarked));
  const f = facts(p);
  const pick = name === "polish" ? "Epoxy" : "Polish";
  const radio = radios(p).filter((r) => r.attrs.value === pick)[0];
  radio.checked = true;
  const fired = radio.fire("change");
  out.live[name] = Object.assign(f, { fired: fired, after: facts(p), reloads: p.reloads.length, saved: merged(p).base_tab_id });
}

// 3. ONE TAB WITHOUT THE MARK: not a v2 snapshot, so the draft is read as a spreadsheet's.
out.oneUnmarked = (() => {
  const p = open(draft("polish", (s) => { delete s.priced_tabs[0].v2; }));
  return { locked: facts(p).locked, radios: facts(p).radios };
})();

// 4. THE OPTION CONTROLS A v2 DRAFT KEEPS, and the keys they write.
out.options = (() => {
  const p = open(draft("polish"));
  const before = clone(p.st.tab_opts);
  const copy = () => rowOf(p, "Copy1");
  const result = { start: rowFacts(p, "Copy1"), seal: rowFacts(p, "Seal"), epoxy: rowFacts(p, "Epoxy"), root: rowFacts(p, "Polish") };
  // 4a. the Copy as a TOTAL
  let md = copy().querySelector(".pr-mode");
  md.value = "total"; md.fire("change");
  result.copyAsTotal = { opts: clone(p.st.tab_opts.Copy1), rooms: facts(p).rooms, lump: p.st.proposal_lump_sum };
  // 4b. back to a DEDUCT
  md = rowOf(p, "Copy1").querySelector(".pr-mode");
  md.value = "deduct"; md.fire("change");
  result.copyAsDeduct = { opts: clone(p.st.tab_opts.Copy1), rooms: facts(p).rooms };
  // 4c. the Epoxy sheet taken off the proposal and put back
  let iso = rowOf(p, "Epoxy").querySelector(".pr-isopt");
  iso.checked = false; iso.fire("change");
  result.epoxyOff = { opts: clone(p.st.tab_opts.Epoxy), rooms: facts(p).rooms.map((r) => r[0]), after: facts(p).rows.Epoxy };
  iso = rowOf(p, "Epoxy").querySelector(".pr-isopt");
  iso.checked = true; iso.fire("change");
  result.epoxyOn = { opts: clone(p.st.tab_opts.Epoxy), rooms: facts(p).rooms.map((r) => r[0]) };
  // 4d. the words typed on an option are saved under desc, and are its line
  const ta = rowOf(p, "Epoxy").querySelector(".room-desc");
  ta.value = "Add for an epoxy floor in the loading dock"; ta.fire("input");
  result.desc = { opts: clone(p.st.tab_opts.Epoxy), room: (p.st.rooms.filter((r) => r.id === "Epoxy")[0] || {}).custom_desc };
  // 4e. notes
  const notes = rowOf(p, "Seal").querySelector(".room-notes");
  notes.value = "Two coats\nClear"; notes.fire("input");
  result.notes = { tab_notes: clone(p.st.tab_notes), saved: merged(p).tab_notes };
  result.keysTouched = Object.keys(p.st.tab_opts).sort();
  result.untouchedCopyEntry = JSON.stringify(before.Seal) === JSON.stringify(Object.assign({}, p.st.tab_opts.Seal));
  result.base = { id: p.st.base_tab_id, lump: p.st.proposal_lump_sum };
  return result;
})();

// 5. SEAL IS A TOTAL ONLY on a v2 draft: a stale "deduct" on it is read as a total, and the panel offers no choice.
//    A Seal option on a spreadsheet bid is read as it always was.
out.seal = (() => {
  const staleSeal = (s) => { s.tab_opts.Seal.price_mode = "deduct"; return s; };
  const v2 = open(staleSeal(draft("polish")));
  const live = open(staleSeal(unmarked(draft("polish"))));
  const sealRoom = (p) => (p.st.rooms.filter((r) => r.id === "Seal")[0] || {}).price_mode;
  return { v2Room: sealRoom(v2), v2Row: rowFacts(v2, "Seal"), v2Opts: v2.st.tab_opts.Seal.price_mode,
           liveRoom: sealRoom(live), liveRow: rowFacts(live, "Seal") };
})();

// 6. A v2 DRAFT LISTS EVERY SHEET IT HOLDS and has no "+ Add another system". The spreadsheet's panel hides the other work types'
//    sheets (it holds every tab of the workbook) until they are engaged or revealed; a v2 bid holds only what somebody put in it,
//    so a Gyp sheet that is on the bid but off the proposal is a row here, and is not on a spreadsheet draft.
out.systems = (() => {
  const withGyp = (s) => {
    s.priced_tabs.push({ id: 'Gyp (USG 1-8")', name: "Gyp", role: "gyp", kind: "option", total: 6000, sales_tax: 150, remodel: 0,
                         system_desc: "Gypsum underlayment", notes_auto: [], sf: {}, sys_names: [], taxable: true, remodel_on: false, v2: true });
    s.tab_opts['Gyp (USG 1-8")'] = { show_system: true, show_diff: false, is_option: false, show: true, price_mode: "total" };
    return s;
  };
  const p = open(withGyp(draft("polish")));
  const q = open(withGyp(unmarked(draft("polish"))));
  return { v2Rows: Object.keys(facts(p).rows), v2Add: facts(p).addSystem, liveRows: Object.keys(facts(q).rows), liveAdd: facts(q).addSystem };
})();

// 7. allV2 and shared.js v2PricingView answer one question: a snapshot v2 wrote is left alone by the view exactly when allV2 says so.
out.parity = (() => {
  const isV2Draft = L.lift(SHARED, "isV2Draft", {}, { indent: "  ", where: "shared.js" });
  const SHEET_PRICING_KEYS = new Function(L.grabConst(SHARED, "SHEET_PRICING_KEYS", { indent: "  " }) + NL + "return SHEET_PRICING_KEYS;")();
  const v2PricingView = L.lift(SHARED, "v2PricingView", { isV2Draft, SHEET_PRICING_KEYS }, { indent: "  ", where: "shared.js" });
  const tab = (v2) => Object.assign({ id: "Polish", role: "polish", kind: "base", total: 1 }, v2 === undefined ? {} : { v2: v2 });
  const cases = {
    "all marked": [tab(true), tab(true)], "one marked": [tab(true)], "one unmarked": [tab()], "mixed": [tab(true), tab()],
    "false mark": [tab(false)], "string mark": [tab("true")], "empty": [], "null entry": [tab(true), null], "not a list": null,
  };
  return Object.fromEntries(Object.keys(cases).map((k) => {
    const blob = { polish_estimate: { version: 2 }, priced_tabs: cases[k], proposal_lump_sum: 5 };
    return [k, { allV2: TWPrice.allV2(cases[k]), viewKeepsIt: v2PricingView(blob) === blob }];
  }));
})();

console.log(JSON.stringify(out));
