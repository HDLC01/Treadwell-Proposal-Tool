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

// ── the SHIPPED role vocabulary ──────────────────────────────────────────────
// GYP_SHEETS / SEAL_SHEETS / BASE_ROLE / PRICED_ROLES / isPricedRole come out of the real file, so
// this harness cannot disagree with the app about which worksheets are priced. Evaluated as a unit
// because BASE_ROLE is built by two forEach lines over the other two constants.
const NL = String.fromCharCode(10);   // no escapes in this file's own source
const ROLE = (() => {
  const grab = (re, what) => {
    const m = re.exec(SRC);
    if (!m) throw new Error("could not lift " + what + " — rewrite this harness, don't stub it");
    return m[0];
  };
  const src = [
    grab(/^const GYP_BASE = .*$/m, "GYP_BASE"),
    grab(/^const GYP_SHEETS = \[[\s\S]*?\];$/m, "GYP_SHEETS"),
    grab(/^const SEAL_SHEETS = \[[\s\S]*?\];$/m, "SEAL_SHEETS"),
    grab(/^const BASE_ROLE = \{[\s\S]*?\};$/m, "BASE_ROLE"),
    grab(/^GYP_SHEETS\.forEach\(.*$/m, "the gyp role loop"),
    grab(/^SEAL_SHEETS\.forEach\(.*$/m, "the seal role loop"),
    grab(/^const PRICED_ROLES = new Set\(\[[^\]]*\]\);$/m, "PRICED_ROLES"),
    grab(/^const COMBINED_BASE_ROLES = new Set\(\[[^\]]*\]\);$/m, "COMBINED_BASE_ROLES"),
    grab(/^const OPTION_ONLY_ROLES = new Set\(\[[^\]]*\]\);$/m, "OPTION_ONLY_ROLES"),
    grab(/^const isOptionOnlyRole = .*$/m, "isOptionOnlyRole"),
    grab(/^const isPricedRole = .*$/m, "isPricedRole"),
  ].join(NL);
  return new Function(src + NL + "return { BASE_ROLE, PRICED_ROLES, isPricedRole, GYP_SHEETS, SEAL_SHEETS, COMBINED_BASE_ROLES, OPTION_ONLY_ROLES, isOptionOnlyRole };")();
})();
/** A fixture tab's role, from the shipped map — a copy carries its own. */
// By id, then by NAME: the gyp fixture tab is keyed "Gyp" for brevity while the real sheet — and
// therefore the real BASE_ROLE key — is 'Gyp (USG 1-8")', which the fixture carries as its name.
// Without the name fallback the gyp tab silently became role "other" and stopped being priced,
// which is the kind of fixture drift that makes a harness agree with itself and nothing else.
const roleOf = (t) => t.copyRole || ROLE.BASE_ROLE[t.id] || ROLE.BASE_ROLE[t.name] || "other";

// ── the workbook: what a combo job really carries ────────────────────────────
// Two base-kind sheets plus a copy (a "Room 1" style extra) and a gyp variant, because the
// predicate has to exclude both of those and only the real pair may be tagged.
// `role` is NOT hand-written here any more — it comes from the shipped BASE_ROLE map, lifted below,
// so a sheet the app does not price cannot be smuggled into this fixture as if it did.
const TABS = [
  { id: "Epoxy",  name: "Epoxy",  kind: "base" },
  { id: "Polish", name: "Polish", kind: "base" },
  { id: "Copy1",  name: "Room 1", kind: "copy", copyRole: "epoxy" },
  { id: "Gyp",    name: "Gyp (USG 1-8\")", kind: "base" },
  // Both seal sheets, because they are `kind: "base"` template tabs and that is exactly what walked
  // them into the combo predicates when seal became a priced role.
  { id: "Seal",   name: "Seal", kind: "base" },
  { id: "Seal (+Jnts)", name: "Seal (+Jnts)", kind: "base" },
  // A sheet the app must NEVER price, so the role filter is proven to filter something.
  { id: "Leveling", name: "Leveling", kind: "base" },
];
// CELLS, not one number per tab. `hfNum(id)` used to ignore the address entirely, so the chip's
// price came out right no matter which coordinates totalCellsFor resolved — and the wrong-money
// mutation ("seal falls through to the Epoxy coordinates") survived because of it. Each sheet now
// answers only at the address its own layout uses: an Epoxy-layout read of a Polish-layout sheet
// lands on D88, which is empty here exactly as it is in the workbook.
const CELLS = {
  Epoxy:            { D88: 29942 },
  Polish:           { D82: 15801 },
  Copy1:            { D88: 8000 },
  Gyp:              { E87: 4000 },
  Seal:             { D82: 8410 },
  "Seal (+Jnts)":   { D82: 9905 },
  Leveling:         { D82: 3000 },
};
const cellAt = (id, addr) => ((CELLS[id] || {})[addr] || 0);

// The lifted renderBidOptions reads `t.role` directly, so stamp the SHIPPED role onto each fixture
// tab rather than hand-writing one. A sheet the app does not price therefore cannot be smuggled in
// as if it were: Leveling comes out "other" and the real filter drops it.
TABS.forEach((t) => { t.role = roleOf(t); });

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
  // `onlySeal` strips the fixture down to the seal sheets, so resolveBaseTab's last-resort
  // `basePricedTabs()[0]` tail has nothing legitimate to reach for. It must answer null, not Seal.
  const onlySeal = !!(stateIn && stateIn.onlySeal);
  const state = Object.assign({ work_type: "combo", base_tab_id: null, tab_opts: {},
                                reveal_systems: false, price_overrides: {} }, stateIn);
  const document = dom();
  const setStateCalls = [];
  const deps = {
    document,
    state,
    tabs: onlySeal ? TABS.filter((t) => roleOf(t) === "seal") : TABS,
    COMBINED_BASE_ROLES: ROLE.COMBINED_BASE_ROLES,
    TW: { setState: (p) => setStateCalls.push(p) },
    HF: { ready: true, getValue: (id, addr) => cellAt(id, addr) },
    hfNum: (id, addr) => cellAt(id, addr),
    // Also real, for the same reason: these decide whether a Seal chip gets a Base-bid radio, and
    // stubbing them true would let the one-click-to-the-wrong-document path back in unnoticed.
    isOptionOnlyRole: ROLE.isOptionOnlyRole,
    basePricedTabs: () => (onlySeal ? TABS.filter((t) => roleOf(t) === "seal") : TABS)
      .filter((t) => ROLE.isPricedRole(roleOf(t)) && !ROLE.isOptionOnlyRole(roleOf(t))),
    // The job's template capability. Direct prints options; GC does not.
    templatePrintsOptions: (wt, aud) => String(aud || "Direct") === "Direct" || String(wt) === "gyp",
    // THE REAL ONES. These were `pricedTabs: () => TABS.slice()` and `isPricedRole: () => true`,
    // which made this harness structurally incapable of catching a role-filter regression — and the
    // role filter is precisely why an estimator could price the Seal sheet and never find a chip
    // for it. Lifted from the shipped source, so the fixture's roles and the filter are the app's.
    pricedTabs: () => (onlySeal ? TABS.filter((t) => roleOf(t) === "seal") : TABS)
      .filter((t) => ROLE.isPricedRole(roleOf(t))),
    isPricedRole: (r) => ROLE.isPricedRole(r),
    labelFor: (id) => (TABS.find((t) => t.id === id) || {}).name || id,
    // The REAL one. A stub here is why "seal falls through to the Epoxy coordinates" — the whole
    // wrong-money hazard — survived its mutation: the chip price came from the stub, not from the
    // routing under test.
    totalCellsFor: null,   // replaced below, once TOTAL_CELLS and roleFor are lifted
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
  // The real name derivation, plus the two things it reads. This is what the customer's proposal
  // says, so it must come out of the shipped source rather than be asserted from memory.
  // TOTAL_CELLS + roleFor + structOpsFor, so totalCellsFor resolves for real.
  deps.TOTAL_CELLS = new Function(
    /^const TOTAL_CELLS = \{[\s\S]*?^\};$/m.exec(SRC)[0] + NL + "return TOTAL_CELLS;")();
  deps.roleFor = (id) => roleOf(TABS.find((t) => t.id === id) || { id });
  deps.structOpsFor = () => [];
  deps.totalCellsFor = lift("totalCellsFor", deps);
  deps.LAYOUT_SYSTEM_NAME = new Function(
    /^const SEAL_SYSTEM_NAME = .*$/m.exec(SRC)[0] + NL +
    /^const LAYOUT_SYSTEM_NAME = \{[\s\S]*?\};$/m.exec(SRC)[0] +
    NL + "return LAYOUT_SYSTEM_NAME;")();
  deps.layoutIdFor = (id) => id;                 // no copies in this fixture
  deps.txAddr = (id, a) => a;
  deps._cbRealSystem = () => true;
  deps.deriveSystemNameFor = lift("deriveSystemNameFor", deps);
  // resolveBaseTab and isInCombinedBase are real code, lifted with the same dependency set.
  deps.resolveBaseTab = lift("resolveBaseTab", deps);
  deps.isInCombinedBase = lift("isInCombinedBase", deps);
  const renderBidOptions = lift("renderBidOptions", deps);
  deps.renderBidOptions = renderBidOptions;
  const wireBidBar = lift("wireBidBar", deps);
  return { state, document, setStateCalls, renderBidOptions, wireBidBar,
           isInCombinedBase: deps.isInCombinedBase,
           // The real resolver and the real name derivation, so a test can ask them directly
           // rather than inferring from markup.
           resolveBaseTab: deps.resolveBaseTab,
           deriveSystemNameFor: deps.deriveSystemNameFor };
}

// One chip's markup, by data-id.
function chip(html, id) {
  // Sliced by indexOf, never by a RegExp built from the id: "Seal (+Jnts)" contains regex
  // metacharacters, and the unused RegExp that used to sit here threw "Nothing to repeat" the
  // first time a sheet name was not a bare word.
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

// ── 6. SEALED CONCRETE as an option ───────────────────────────────────────────
// An estimator, 2026-08-13: "Working on an estimate and noticed that 'Seal' doesn't come up as an
// optional system to add." Everything below is that request, plus the ways granting it could go
// wrong on a customer's document.
{
  const h = harness({ work_type: "epoxy" });
  h.renderBidOptions();
  const html = h.document.els["bid-options-list"].innerHTML;
  const sealChip = chip(html, "Seal");
  const jointsChip = chip(html, "Seal (+Jnts)");
  out.seal = {
    // The request itself: both sheets are offered on an ordinary epoxy job.
    present: !!sealChip,
    jointsPresent: !!jointsChip,
    offersOption: !!sealChip && /bb-isopt/.test(sealChip),
    price: sealChip && (/bb-price">([^<]*)</.exec(sealChip) || [])[1],
    jointsPrice: jointsChip && (/bb-price">([^<]*)</.exec(jointsChip) || [])[1],
    // NO Base-bid radio: role "seal" has no proposal template, so a seal base would print the
    // epoxy document carrying the seal's money.
    hasBaseRadio: !!sealChip && /class="bb-base"/.test(sealChip),
    jointsHasBaseRadio: !!jointsChip && /class="bb-base"/.test(jointsChip),
    epoxyStillHasRadio: /data-id="Epoxy"[\s\S]{0,400}?class="bb-base"/.test(html),
    // A sheet the app does not price must still be absent — proof the filter filters.
    levelingPresent: !!chip(html, "Leveling"),
  };
  // A draft naming a seal base must be refused, not honoured.
  const h2 = harness({ work_type: "epoxy", base_tab_id: "Seal" });
  h2.renderBidOptions();
  // Asked DIRECTLY, with no render in between: the render's stale-base guard would otherwise have
  // already nulled the seal base, so this is the only way to pin resolveBaseTab's own filter.
  const h2b = harness({ work_type: "epoxy", base_tab_id: "Seal" });
  out.sealAsBase = {
    resolvedWithoutRender: (h2b.resolveBaseTab() || {}).id || null,
    resolved: (h2.resolveBaseTab() || {}).id || null,
    stateBaseAfterRender: h2.state.base_tab_id,
    // And the last-resort fallback must not reach for a seal tab either.
    fallbackOnSealOnlyWorkbook: (harness({ work_type: "epoxy", onlySeal: true })
      .resolveBaseTab() || {}).id || null,
  };
  // The names that reach the proposal.
  const h3 = harness({ work_type: "epoxy" });
  out.sealNames = {
    seal: h3.deriveSystemNameFor("Seal"),
    joints: h3.deriveSystemNameFor("Seal (+Jnts)"),
  };
  // The template that cannot print an option at all says so.
  const gc = harness({ work_type: "epoxy", audience: "GC",
                       tab_opts: { Seal: { is_option: true, show: true, price_mode: "total" } } });
  gc.renderBidOptions();
  const gcSeal = chip(gc.document.els["bid-options-list"].innerHTML, "Seal");
  const direct = harness({ work_type: "epoxy", audience: "Direct",
                           tab_opts: { Seal: { is_option: true, show: true, price_mode: "total" } } });
  direct.renderBidOptions();
  const dirSeal = chip(direct.document.els["bid-options-list"].innerHTML, "Seal");
  out.cannotPrint = {
    warnsOnGC: !!gcSeal && /does not print options/.test(gcSeal),
    quietOnDirect: !!dirSeal && !/does not print options/.test(dirSeal),
  };
}

console.log(JSON.stringify(out));
