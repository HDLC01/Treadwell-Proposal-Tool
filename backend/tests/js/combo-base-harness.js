"use strict";
/* Execute the real bid strip out of estimate-review.js on a COMBO job.
 *
 * WHY EXECUTED. The bug being fixed was invisible to source reading: the strip rendered Epoxy's
 * radio as CHECKED with a "base bid" tag through a fallback, while the lump sum summed Epoxy AND
 * Polish. Both halves were correct in isolation; only the rendered markup showed the lie. And on
 * 2026-08-12 an unbound identifier took the board down on prod with every source assertion green.
 *
 * Lifts three real units — `isInCombinedBase`, `renderBidOptions`, and the `#bid-bar` change
 * handler out of `wireBidBar` — and runs them against a two-sheet combo workbook.
 *
 * Usage: node combo-base-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");

const SRC = fs.readFileSync(path.join(process.argv[2], "js", "estimate-review.js"), "utf8");

// ── the workbook: what a combo job really carries ────────────────────────────
// Two base-kind sheets plus a copy (a "Room 1" style extra) and a gyp variant, because the
// predicate has to exclude both of those and only the real pair may be tagged.
const TABS = [
  { id: "Epoxy",  name: "Epoxy",  role: "epoxy",  kind: "base" },
  { id: "Polish", name: "Polish", role: "polish", kind: "base" },
  { id: "Copy1",  name: "Room 1", role: "epoxy",  kind: "copy" },
  { id: "Gyp",    name: "Gyp (USG 1-8\")", role: "gyp", kind: "base" },
];
const TOTALS = { Epoxy: 29942, Polish: 15801, Copy1: 8000, Gyp: 4000 };

function lift(name, deps) {
  const re = new RegExp("^function " + name + "\\([^)]*\\) \\{[\\s\\S]*?\\n\\}", "m");
  const m = re.exec(SRC);
  if (!m) throw new Error("could not lift " + name);
  const names = Object.keys(deps);
  return new Function(...names, m[0] + "\nreturn " + name + ";")(...names.map((k) => deps[k]));
}

// A DOM stub that keeps the two elements the strip writes to, and hands back the listener the
// bid bar registers so a radio click can actually be delivered.
function dom() {
  const els = {
    "bid-options-list": { innerHTML: "", listeners: {},
      addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); } },
    "bid-options-hint": { innerHTML: "" },
  };
  return { getElementById: (id) => els[id] || null, els };
}

function harness(stateIn) {
  const state = Object.assign({ work_type: "combo", base_tab_id: null, tab_opts: {},
                                reveal_systems: false, price_overrides: {} }, stateIn);
  const document = dom();
  const setStateCalls = [];
  const deps = {
    document,
    state,
    tabs: TABS,
    TW: { setState: (p) => setStateCalls.push(p) },
    HF: { ready: true, getValue: (id) => TOTALS[id] || 0 },
    hfNum: (id) => TOTALS[id] || 0,
    pricedTabs: () => TABS.slice(),
    isPricedRole: () => true,
    labelFor: (id) => (TABS.find((t) => t.id === id) || {}).name || id,
    totalCellsFor: () => ({ total: "D88", sales_tax: "D80", remodel: "D81" }),
    GYP_BASE: "Gyp",
    _escBB: (s) => String(s).replace(/[&<>"]/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])),
    _moneyBB: (n) => "$" + Number(n || 0).toLocaleString("en-US", { maximumFractionDigits: 0 }),
    ensureOpt: (id) => (state.tab_opts[id] = state.tab_opts[id] ||
      { show_system: true, show_diff: false, is_option: false, show: true, price_mode: "total" }),
    persistBidOptions: () => setStateCalls.push({ persisted: true }),
    clearSingleBidDisplayOverride: () => {},
    renderPricePreview: () => {},
    syncSingleBidDisplay: () => {},
    scheduleRecalcAll: () => {},
  };
  // resolveBaseTab and isInCombinedBase are real code, lifted with the same dependency set.
  deps.resolveBaseTab = lift("resolveBaseTab", deps);
  deps.isInCombinedBase = lift("isInCombinedBase", deps);
  const renderBidOptions = lift("renderBidOptions", deps);
  deps.renderBidOptions = renderBidOptions;
  const wireBidBar = lift("wireBidBar", deps);
  return { state, document, setStateCalls, renderBidOptions, wireBidBar,
           isInCombinedBase: deps.isInCombinedBase };
}

// One chip's markup, by data-id.
function chip(html, id) {
  const re = new RegExp('<span class="bb-opt" data-id="' + id + '">([\\s\\S]*?)</span></span>|' +
                        '<span class="bb-opt" data-id="' + id + '">([\\s\\S]*?)$');
  // Chips are flat siblings; slice from this chip's start to the next chip's start instead of
  // trying to balance nested spans with a regex.
  const start = html.indexOf('data-id="' + id + '"');
  if (start < 0) return null;
  const from = html.lastIndexOf("<span", start);
  const next = html.indexOf('<span class="bb-opt"', start);
  return html.slice(from, next < 0 ? html.length : next);
}
const facts = (c) => c && ({
  tagged: /bb-tag">base bid</.test(c),
  offersOption: /bb-isopt/.test(c),
  partOfBase: /Part of the combined base bid/.test(c),
  checked: /class="bb-base" value="[^"]*" checked/.test(c) ||
           /class="bb-base"[^>]*checked/.test(c),
});

const out = {};

// ── 1. combo, nothing picked: BOTH sheets are the base bid ───────────────────
{
  const h = harness({});
  h.renderBidOptions();
  const html = h.document.els["bid-options-list"].innerHTML;
  const combinedStart = html.indexOf("bb-combined");
  const combined = combinedStart < 0 ? null
    : html.slice(html.lastIndexOf("<span", combinedStart),
                 html.indexOf('<span class="bb-opt" data-id='));
  out.comboDefault = {
    epoxy: facts(chip(html, "Epoxy")),
    polish: facts(chip(html, "Polish")),
    copy: facts(chip(html, "Copy1")),
    combinedPresent: combinedStart >= 0,
    combinedChecked: !!combined && /class="bb-base" value="" checked/.test(combined),
    combinedTagged: !!combined && /bb-tag">base bid</.test(combined),
    combinedPrice: combined && (/bb-price">([^<]*)</.exec(combined) || [])[1],
    // The strip must not silently write a base into the draft on a combo.
    wroteBase: h.setStateCalls.some((c) => c && c.base_tab_id),
    stateBase: h.state.base_tab_id,
    hint: /both<\/b> sheets/i.test(h.document.els["bid-options-hint"].innerHTML),
  };
}

// ── 2. combo with an explicit single sheet: that sheet alone is the base ──────
{
  const h = harness({ base_tab_id: "Epoxy" });
  h.renderBidOptions();
  const html = h.document.els["bid-options-list"].innerHTML;
  out.comboNarrowed = {
    epoxy: facts(chip(html, "Epoxy")),
    polish: facts(chip(html, "Polish")),
    // The way BACK: the combined chip is still offered, unchecked.
    combinedOffered: html.indexOf("bb-combined") >= 0,
    combinedChecked: /bb-combined[\s\S]*?class="bb-base" value="" checked/.test(html),
  };
}

// ── 3. the round buttons round-trip null → Epoxy → null ──────────────────────
{
  const h = harness({});
  h.renderBidOptions();
  h.wireBidBar();
  const list = h.document.els["bid-options-list"];
  const change = (list.listeners.change || [])[0];
  const click = (value) => change({
    target: { classList: { contains: (c) => c === "bb-base" }, value, checked: true,
              closest: () => null },
  });
  const before = h.state.base_tab_id;
  click("Epoxy");
  const narrowed = h.state.base_tab_id;
  click("");                                  // the combined chip
  out.roundTrip = { before, narrowed, back: h.state.base_tab_id,
                    handlerFound: typeof change === "function" };
}

// ── 4. a base sheet is never also an option against itself ───────────────────
{
  const h = harness({});
  const inBase = TABS.map((t) => [t.id, h.isInCombinedBase(t)]);
  const h2 = harness({ base_tab_id: "Epoxy" });
  const narrowed = TABS.map((t) => [t.id, h2.isInCombinedBase(t)]);
  const h3 = harness({ work_type: "epoxy" });
  const soloJob = TABS.map((t) => [t.id, h3.isInCombinedBase(t)]);
  out.predicate = { combo: inBase, narrowed, epoxyJob: soloJob };
}

// ── 5. off combo nothing changes ──────────────────────────────────────────────
{
  for (const wt of ["epoxy", "polish", "gyp"]) {
    const h = harness({ work_type: wt });
    h.renderBidOptions();
    const html = h.document.els["bid-options-list"].innerHTML;
    out["job_" + wt] = {
      combinedChip: html.indexOf("bb-combined") >= 0,
      taggedCount: (html.match(/bb-tag">base bid</g) || []).length,
      stateBase: h.state.base_tab_id,
      hintRewritten: h.document.els["bid-options-hint"].innerHTML !== "",
    };
  }
}

console.log(JSON.stringify(out));
