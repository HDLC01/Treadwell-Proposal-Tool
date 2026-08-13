"use strict";
/* Execute the real syncPayloadPricing() over the real computeTokenValues() out of
 * proposal-review.js, and report what the stored generate payload looks like afterwards.
 *
 * THE BUG IT COVERS (Hanz, 2026-08-13). He inverted the base bid in the Pricing sidebar — Epoxy
 * became the base at $18,670, Polish the option at $13,265 — left via the "4 · Files" step pill,
 * and re-sent. The portal PAGE showed the new arrangement. The customer's PDF showed the old one.
 * Same pinned revision, two halves: the page renders top-level `rooms`, the PDF is re-rendered
 * from `proposal_payload`, and that sub-object was written by exactly ONE line in the whole
 * frontend (the Continue handler). Every sidebar path left it frozen.
 *
 * WHY EXECUTED, NOT GREPPED. The claim is "the payload's money now equals a freshly computed
 * money", which is a comparison between two runs of real code. A source assertion that
 * `syncPayloadPricing` is CALLED says nothing about whether the whitelist reaches every token the
 * price block prints — and a whitelist with a hole is the same customer-visible bug in a new
 * costume. The completeness case below derives the required key set by DIFFING two real computes
 * instead of restating the list, so it fails when a token is added to the mapping and forgotten
 * here.
 *
 * Usage: node payload-sync-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = process.argv[2];
const SRC = fs.readFileSync(path.join(ROOT, "js", "proposal-review.js"), "utf8");
const NL = String.fromCharCode(10);

/** Lift a real unit by name, refusing to invent a stub if the file moved on. */
function grab(re, what) {
  const m = re.exec(SRC);
  if (!m) throw new Error("could not lift " + what + " — rewrite this harness, don't stub it");
  return m[0];
}
/** Lift `function name(...) {...}` by brace counting (bodies contain braces + regexes). */
function fn(name) {
  const m = new RegExp("\\n  function " + name + "\\s*\\(").exec(SRC);
  if (!m) throw new Error(name + "() is gone — rewrite this harness, don't stub it");
  const i = SRC.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < SRC.length; j++) {
    if (SRC[j] === "{") depth++;
    else if (SRC[j] === "}" && --depth === 0) return SRC.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name);
}

// The real units, in dependency order. computeTokenValues and syncPayloadPricing are the subjects;
// everything else is lifted rather than stubbed so the harness cannot disagree with the app about
// how a dollar is formatted or which work type is in effect.
// `templateVersion`, `collectOverrides`, `collectBoxOverrides` and `sheetSystems` belong to the
// document editor, which needs a whole mounted template to exist. They are INJECTED as harness
// parameters (see scopeFor) rather than lifted: the subject here is what syncPayloadPricing DOES
// with them — calls them when the template changed, leaves them alone otherwise — and injection is
// what lets the test observe that. Everything in the pricing path itself is real.
const UNITS = [
  grab(/^  const fmtUSD = [\s\S]*?;$/m, "fmtUSD"),
  grab(/^  const fmtUSDdoc = .*$/m, "fmtUSDdoc"),
  grab(/^  const fmtSF = .*$/m, "fmtSF"),
  fn("effectiveWorkType"),
  fn("taxTreatmentMode"),
  fn("lineOverride"),
  fn("comboSystemLines"),
  fn("comboLinesForPayload"),
  fn("computeTokenValues"),
  grab(/^  const PAYLOAD_PRICING_KEYS = \[[\s\S]*?\];$/m, "PAYLOAD_PRICING_KEYS"),
  fn("syncPayloadPricing"),
].join(NL);

/** Build a page scope around one state object and return handles into the real functions. */
function scopeFor(state, opts) {
  const o = opts || {};
  const lumpText = o.lumpText != null ? o.lumpText : "$0.00";
  const formValues = o.form || {};
  // #tb-total is where computeTokenValues reads the lump sum from — the page writes it before
  // calling, so the harness models it as the rendered total, not as a state field.
  // `noTotalEl: true` models PAGE INIT. #tb-total appears in NO html for this screen — the init
  // block near the bottom of proposal-review.js creates it, which happens AFTER the page-init
  // rebuildPricing() call. Stubbing it as always-present is exactly why a regression that wrote
  // $0.00 into every opened project's document payload passed the whole suite.
  const doc = {
    querySelector: (sel) => (sel === "#tb-total" && !o.noTotalEl ? { textContent: lumpText } : null),
    getElementById: () => null,
  };
  const form = {
    querySelector: (sel) => {
      const m = /\[name='([^']+)'\]/.exec(sel);
      return m && formValues[m[1]] !== undefined ? { value: formValues[m[1]] } : null;
    },
  };
  const TW = { readForm: () => formValues };
  // Editor seams. `calls` records what the sync reached for, so a test can assert that a plain
  // re-price never touches the narrative and a template change does.
  const calls = { collectOverrides: 0, collectBoxOverrides: 0, sheetSystems: 0 };
  const collectOverrides = () => {
    calls.collectOverrides++;
    if (o.editorThrows) throw new Error("editor not mounted");
    return o.overrides || [{ id: 7, text: "edited on the NEW template" }];
  };
  const collectBoxOverrides = () => {
    calls.collectBoxOverrides++;
    if (o.editorThrows) throw new Error("editor not mounted");
    return o.boxOverrides || { 3: { w_pt: 300 } };
  };
  const sheetSystems = () => {
    calls.sheetSystems++;
    if (o.sheetSystemsThrows) throw new Error("no template");
    return o.sheetSystems !== undefined ? o.sheetSystems
      : [{ name: "Epoxy System", sf: 7400, lf: 120 }, { name: "Options", sf: 0, lf: 0 }];
  };
  const body = UNITS + NL +
    "return { syncPayloadPricing, computeTokenValues, comboLinesForPayload, PAYLOAD_PRICING_KEYS };";
  const api = new Function("state", "document", "form", "TW", "window", "templateVersion",
                           "collectOverrides", "collectBoxOverrides", "sheetSystems", body)(
    // `?? "tpl-v9"`, not `|| "tpl-v9"`: an explicit "" is the page-init case under test, and a
    // truthiness default would silently substitute a loaded template for it.
    state, doc, form, TW, { TWAuth: null },
    o.templateVersion === undefined ? "tpl-v9" : o.templateVersion,
    collectOverrides, collectBoxOverrides, sheetSystems);
  api.calls = calls;
  return api;
}

/** A production-shaped state: two priced tabs, Polish as the base, plus a generated payload. */
function baseState() {
  const rooms = [
    { name: "Polish", is_base: true, bid: { total: 13265 } },
    { name: "Epoxy", is_base: false, bid: { total: 18670 }, show: true },
  ];
  return {
    work_type: "polish", audience: "Direct", project_name: "Hanz Test Company",
    base_tab_id: "Polish", proposal_lump_sum: 13265,
    proposal_sales_tax: 420, proposal_remodel_tax: 0,
    sheet_area: { polish_sf: 5000, epoxy_sf: 0, cove_lf: 0 },
    priced_tabs: [
      { id: "Polish", role: "polish", kind: "base", total: 13265, sales_tax: 420, remodel: 0 },
      { id: "Epoxy", role: "epoxy", kind: "base", total: 18670, sales_tax: 610, remodel: 0 },
    ],
    rooms,
    price_overrides: { lines: {} },
    // What the estimator typed. NONE of it may move when the pricing does.
    scope_notes: "Grind and polish per spec.", schedule_notes: "Two mobilizations.",
    exclusions: "Moisture mitigation excluded.", work_notes: "Call Kyle before pour.",
    system_name: "Treadwell Polished Concrete", texture: "Salt & pepper",
    estimator_name: "Kyle",
    // The payload frozen by the last Continue — the stale half.
    proposal_payload: {
      work_type: "polish", audience: "Direct",
      rooms: rooms.map((r) => ({ ...r })),
      remodel: [], combo_options: [], price_overrides: { lines: {} },
      values: {
        project_name: "Hanz Test Company",
        proposal_lump_sum: 13265, base_tab_id: "Polish",
        rooms: rooms.map((r) => ({ ...r })),
        total_label: "$13,265.00 – Total",
        lump_sum_label: "$13,265.00 – Polished Concrete Flooring as described above",
        lump_sum_formatted: "$13,265.00", total_formatted: "$13,265.00",
        base_bid_formatted: "$12,845.00", material_tax_formatted: "$420.00",
        tax_amount_formatted: "$0.00", polish_sf: "5,000", sqft: "5,000",
        area_description: "~5,000 sf of polished concrete flooring",
        scope_notes: "Grind and polish per spec.", schedule_notes: "Two mobilizations.",
        exclusions: "Moisture mitigation excluded.", work_notes: "Call Kyle before pour.",
        system_name: "Treadwell Polished Concrete", texture: "Salt & pepper",
        estimator_name: "Kyle",
      },
    },
  };
}

/** Apply the sidebar's base flip to a state the way rebuildPricing does. */
function flipToEpoxy(s) {
  s.base_tab_id = "Epoxy";
  s.work_type = "epoxy";
  s.proposal_lump_sum = 18670;
  s.proposal_sales_tax = 610;
  s.sheet_area = { polish_sf: 0, epoxy_sf: 7400, cove_lf: 120 };
  s.rooms = [
    { name: "Epoxy", is_base: true, bid: { total: 18670 } },
    { name: "Polish", is_base: false, bid: { total: 13265 }, show: true },
  ];
}

const out = {};

// ── 1. THE INCIDENT ──────────────────────────────────────────────────────────
out.incident = (() => {
  const s = baseState();
  flipToEpoxy(s);
  const sc = scopeFor(s, { lumpText: "$18,670.00", form: { tax_inclusion: "INCLUDED" } });
  const pp = sc.syncPayloadPricing();
  return {
    returnedPayload: !!pp,
    docBase: (pp.rooms.find((r) => r.is_base) || {}).name,
    docBaseTotal: ((pp.rooms.find((r) => r.is_base) || {}).bid || {}).total,
    valuesBaseTabId: pp.values.base_tab_id,
    valuesLumpSum: pp.values.proposal_lump_sum,
    totalLabel: pp.values.total_label,
    lumpSumLabel: pp.values.lump_sum_label,
    totalFormatted: pp.values.total_formatted,
    baseBidFormatted: pp.values.base_bid_formatted,
    materialTaxFormatted: pp.values.material_tax_formatted,
    areaDescription: pp.values.area_description,
    epoxySf: pp.values.epoxy_sf,
    polishSf: pp.values.polish_sf,
    valuesRoomsBase: (pp.values.rooms.find((r) => r.is_base) || {}).name,
    // The narrative must be untouched, character for character.
    narrative: {
      scope_notes: pp.values.scope_notes, schedule_notes: pp.values.schedule_notes,
      exclusions: pp.values.exclusions, work_notes: pp.values.work_notes,
      system_name: pp.values.system_name, texture: pp.values.texture,
      estimator_name: pp.values.estimator_name,
    },
  };
})();

// ── 1b. THE TEMPLATE FOLLOWS THE BASE ROLE ───────────────────────────────────
// `work_type` is derived from the base tab's ROLE, so inverting an Epoxy/Polish base changes which
// .docx the customer receives — not just the numbers on it. The harness's own completeness diff
// surfaced this: `work_type` was the one changed key the sync left behind.
out.templateFollows = (() => {
  const s = baseState();
  flipToEpoxy(s);
  s.proposal_payload.work_type = "polish";       // frozen at the last Continue
  const sc = scopeFor(s, { lumpText: "$18,670.00", form: { tax_inclusion: "INCLUDED" } });
  const pp = sc.syncPayloadPricing();
  return {
    workType: pp.work_type, valuesWorkType: pp.values.work_type, audience: pp.audience,
    // Overrides are captured against ONE template's block ids, so a template change must
    // re-collect them from the (already reloaded) editor rather than replay the old ids.
    templateVersion: pp.template_version,
    paragraphOverrides: pp.paragraph_overrides,
    boxOverrides: pp.box_overrides,
    calls: sc.calls,
  };
})();

// A plain re-price on the SAME template must not go near the narrative at all.
out.samePriceSameTemplate = (() => {
  const s = baseState();
  s.proposal_lump_sum = 14000;                   // re-priced, still polish, still Direct
  s.proposal_payload.work_type = "polish";
  s.proposal_payload.audience = "Direct";
  s.proposal_payload.template_version = "tpl-OLD";
  s.proposal_payload.paragraph_overrides = [{ id: 1, text: "hand written" }];
  const sc = scopeFor(s, { lumpText: "$14,000.00", form: { tax_inclusion: "INCLUDED" } });
  const pp = sc.syncPayloadPricing();
  return { calls: sc.calls, templateVersion: pp.template_version,
           paragraphOverrides: pp.paragraph_overrides, totalFormatted: pp.values.total_formatted };
})();

// The editor may not be mounted (a flip before the template finishes loading). Better to leave the
// previous overrides for the backend's version guard to drop than to throw and lose the save.
out.editorUnavailable = (() => {
  const s = baseState();
  flipToEpoxy(s);
  s.proposal_payload.work_type = "polish";
  s.proposal_payload.paragraph_overrides = [{ id: 1, text: "from the old template" }];
  const sc = scopeFor(s, { lumpText: "$18,670.00", form: { tax_inclusion: "INCLUDED" },
                           editorThrows: true });
  let threw = false, pp;
  try { pp = sc.syncPayloadPricing(); } catch { threw = true; }
  return { threw, workType: pp && pp.work_type,
           paragraphOverrides: pp && pp.paragraph_overrides,
           pricingStillSynced: pp && pp.values.total_formatted };
})();

// rebuildPricing runs at PAGE INIT, before the doc editor has resolved a template version. An
// empty version reads to the backend as "legacy caller, apply the overrides" — so writing one here
// would land the old template's edits on the new template's paragraphs.
out.templateNotLoadedYet = (() => {
  const s = baseState();
  flipToEpoxy(s);
  s.proposal_payload.work_type = "polish";
  s.proposal_payload.template_version = "tpl-POLISH";
  s.proposal_payload.paragraph_overrides = [{ id: 1, text: "captured on polish" }];
  const sc = scopeFor(s, { lumpText: "$18,670.00", form: { tax_inclusion: "INCLUDED" },
                           templateVersion: "" });
  const pp = sc.syncPayloadPricing();
  return { workType: pp.work_type, templateVersion: pp.template_version,
           paragraphOverrides: pp.paragraph_overrides, calls: sc.calls,
           pricingStillSynced: pp.values.total_formatted };
})();

// The WORK section's system rows resolve from the BASE tab's cells, so they move with a flip too.
out.sheetSystems = (() => {
  const s = baseState();
  flipToEpoxy(s);
  const sc = scopeFor(s, { lumpText: "$18,670.00", form: { tax_inclusion: "INCLUDED" } });
  const pp = sc.syncPayloadPricing();

  const bad = baseState();
  flipToEpoxy(bad);
  bad.proposal_payload.sheet_systems = [{ name: "Kept", sf: 1 }];
  const pp2 = scopeFor(bad, { lumpText: "$18,670.00", form: {}, sheetSystemsThrows: true })
    .syncPayloadPricing();
  return { resolved: pp.sheet_systems, keptOnFailure: pp2.sheet_systems };
})();

// ── 1c. PAGE INIT MUST NOT ZERO THE DOCUMENT ─────────────────────────────────
// THE REGRESSION THIS FIX ITSELF SHIPPED TO STAGING (found by adversarial review, 2026-08-13).
// rebuildPricing() runs once at page load, BEFORE the init block creates #tb-total, and
// computeTokenValues falls back to "$0.00" when that element is missing. Merely OPENING an
// already-generated project's Proposal step therefore wrote a $0.00 total — and a NEGATIVE
// flooring line, (0 − remodel tax) — into the customer's document, and persisted it. Observed
// live: a staging draft's stored total_formatted went from "$36,763.00" to "$0.00" on page load.
out.pageInitNoTotalElement = (() => {
  const s = baseState();
  s.proposal_remodel_tax = 1494;
  const before = JSON.parse(JSON.stringify(s.proposal_payload.values));
  const sc = scopeFor(s, { noTotalEl: true, form: { tax_inclusion: "INCLUDED" } });
  const pp = sc.syncPayloadPricing();
  return {
    returned: pp,                                   // must be null — nothing written, nothing persisted
    valuesUnchanged: JSON.stringify(s.proposal_payload.values) === JSON.stringify(before),
    stillTheOldTotal: s.proposal_payload.values.total_formatted,
  };
})();

// The same refusal when the element exists but has not caught up with the pricing — a stale
// element is the same hazard as a missing one, and it is the shape a future reorder would produce.
out.totalElementDisagrees = (() => {
  const s = baseState();
  flipToEpoxy(s);                                   // state says 18,670 …
  const sc = scopeFor(s, { lumpText: "$13,265.00", // … the element still shows the old 13,265
                           form: { tax_inclusion: "INCLUDED" } });
  const pp = sc.syncPayloadPricing();
  return { returned: pp, stillTheOldTotal: s.proposal_payload.values.total_formatted };
})();

// ── 2. WHITELIST COMPLETENESS ────────────────────────────────────────────────
// Derived, not restated: compute the token mapping before and after the flip and diff it. Every
// key whose value MOVED is a key the payload must carry, so a token added to computeTokenValues
// and forgotten in PAYLOAD_PRICING_KEYS shows up here as a leak rather than as a silent hole.
out.completeness = (() => {
  const stale = baseState();
  const staleScope = scopeFor(stale, { lumpText: "$13,265.00", form: { tax_inclusion: "INCLUDED" } });
  const before = staleScope.computeTokenValues(Object.assign({}, stale));

  const flipped = baseState();
  flipToEpoxy(flipped);
  const sc = scopeFor(flipped, { lumpText: "$18,670.00", form: { tax_inclusion: "INCLUDED" } });
  const after = sc.computeTokenValues(Object.assign({}, flipped));

  // Keys the flip actually changed. `proposal_date` is today's date on both sides, so it can't
  // appear here; anything that does appear is pricing- or area-derived by construction.
  const changed = Object.keys(after).filter((k) => {
    const a = before[k], b = after[k];
    if (typeof a === "object" || typeof b === "object") return false;   // state mirrors, handled explicitly
    return a !== b;
  });

  const pp = sc.syncPayloadPricing();
  const missed = changed.filter((k) => pp.values[k] !== after[k]);
  return { changed, missed, whitelist: sc.PAYLOAD_PRICING_KEYS };
})();

// ── 3. NO PAYLOAD → NO-OP ────────────────────────────────────────────────────
out.noPayload = (() => {
  const shapes = { missing: undefined, nul: null, str: "nope", noValues: {}, badValues: { values: 7 } };
  const res = {};
  for (const [k, v] of Object.entries(shapes)) {
    const s = baseState();
    if (v === undefined) delete s.proposal_payload; else s.proposal_payload = v;
    const sc = scopeFor(s, { lumpText: "$18,670.00", form: {} });
    res[k] = sc.syncPayloadPricing();
  }
  return res;
})();

// ── 4. A THROWING COMPUTE MUST NOT BREAK THE PERSIST ─────────────────────────
// The sidebar's job is to save pricing. If the token mapping ever throws on a half-built state,
// syncing the document is the part we can afford to lose — the save is not.
out.computeThrows = (() => {
  const s = baseState();
  // No #tb-total, no form: computeTokenValues reads document.querySelector(...)?.textContent, so
  // force a hard failure by making the lookup itself explode.
  const sc = (() => {
    const body = UNITS + NL + "return { syncPayloadPricing };";
    const doc = { querySelector: () => { throw new Error("boom"); }, getElementById: () => null };
    return new Function("state", "document", "form", "TW", "window", body)(
      s, doc, { querySelector: () => null }, { readForm: () => ({}) }, {});
  })();
  let threw = false, result;
  try { result = sc.syncPayloadPricing(); } catch { threw = true; }
  return { threw, result, payloadUntouched: s.proposal_payload.values.total_label };
})();

// ── 5. TAX TREATMENT ─────────────────────────────────────────────────────────
// Flipping the dropdown changes the parenthetical the customer reads and the itemisation. It goes
// through the FORM, not through rooms, which is why the form's debounced persist syncs too.
out.taxFlip = (() => {
  const res = {};
  for (const mode of ["INCLUDED", "BROKEN_OUT", "EXCLUDED"]) {
    const s = baseState();
    s.proposal_remodel_tax = 900;
    const sc = scopeFor(s, { lumpText: "$13,265.00",
                             form: { tax_inclusion: mode, sales_tax_handling: mode } });
    const pp = sc.syncPayloadPricing();
    res[mode] = { base_tax_phrase: pp.values.base_tax_phrase,
                  tax_phrase: pp.values.tax_phrase,
                  sales_tax_handling: pp.values.sales_tax_handling,
                  remodelLines: pp.remodel };
  }
  return res;
})();

// ── 6. COMBO → SINGLE BASE CLEARS THE COMBO LINES ────────────────────────────
// A combo with no base prints BOTH systems as options. Choosing one base makes that block wrong;
// leaving the old lines in the payload prints two prices in a one-price proposal.
out.comboNarrowing = (() => {
  const s = baseState();
  s.work_type = "combo";
  s.base_tab_id = null;                      // combo with no base → both systems print
  s.proposal_lump_sum = 31935;               // must match #tb-total; see the corroboration guard
  const sc = scopeFor(s, { lumpText: "$31,935.00", form: { tax_inclusion: "INCLUDED" } });
  const withBoth = sc.syncPayloadPricing();
  const comboBefore = withBoth.combo_options.map((l) => l.label);

  const s2 = baseState();
  s2.work_type = "combo";
  s2.base_tab_id = "Epoxy";                  // narrowed to one
  s2.proposal_lump_sum = 18670;
  s2.proposal_payload.combo_options = comboBefore.map((label) => ({ label, amount_formatted: "$1" }));
  const sc2 = scopeFor(s2, { lumpText: "$18,670.00", form: { tax_inclusion: "INCLUDED" } });
  const narrowed = sc2.syncPayloadPricing();
  return { comboBefore, afterNarrowing: narrowed.combo_options };
})();

// ── 7. THE REMODEL LINE FOLLOWS THE TAX ──────────────────────────────────────
out.remodelLine = (() => {
  const on = baseState(); on.proposal_remodel_tax = 1234.5;
  const off = baseState(); off.proposal_remodel_tax = 0;
  const f = { tax_inclusion: "INCLUDED" };
  return {
    on: scopeFor(on, { lumpText: "$13,265.00", form: f }).syncPayloadPricing().remodel,
    off: scopeFor(off, { lumpText: "$13,265.00", form: f }).syncPayloadPricing().remodel,
  };
})();

// ── 8. DISPLAY OVERRIDES SURVIVE ─────────────────────────────────────────────
// The estimator's hand-edited price lines live in state.price_overrides and are re-published on
// every sync. Dropping them would silently restore computed wording they deliberately replaced.
out.overrides = (() => {
  const s = baseState();
  s.price_overrides = { lines: { base: "Flat fee, all in" } };
  const sc = scopeFor(s, { lumpText: "$13,265.00", form: { tax_inclusion: "INCLUDED" } });
  const pp = sc.syncPayloadPricing();
  const bad = baseState();
  bad.price_overrides = "garbage";
  const pp2 = scopeFor(bad, { lumpText: "$13,265.00", form: {} }).syncPayloadPricing();
  return { kept: pp.price_overrides, garbageBecomes: pp2.price_overrides };
})();

// ── 9. THE WIRING ────────────────────────────────────────────────────────────
// A perfect syncPayloadPricing that nothing calls is the bug unchanged. These read the source
// because the claim is about call sites, and each one is checked by EXECUTION elsewhere:
// rebuildPricing's persist shape is asserted below against the real setState in shared.js.
out.wiring = (() => {
  const rebuild = fn("rebuildPricing");
  // rebuildPricing persists twice (a pruned price_overrides early, the pricing at the end), so
  // check EVERY setState rather than the first one — asserting on [0] silently tested the wrong
  // call and reported the fix missing.
  const setStates = rebuild.match(/TW\.setState\(\{[\s\S]*?\}\);/g) || [];
  return {
    rebuildCallsSync: /syncPayloadPricing\(\)/.test(rebuild),
    // The snapshot trap: setState merges into a FRESH localStorage read, so mutating the nested
    // payload is not enough — rebuildPricing must name proposal_payload in the object it passes.
    rebuildPersistsPayload: setStates.some((s) => /proposal_payload/.test(s)),
    setStateCount: setStates.length,
    syncRunsAfterTotalIsWritten: rebuild.indexOf("#tb-total") < rebuild.indexOf("syncPayloadPricing()"),
    formPersistCallsSync: (() => {
      // The DEBOUNCED persist listener, not the first `input` listener (which only repaints).
      // Identified by its own timer variable so this can't drift onto the wrong handler.
      const m = /form\.addEventListener\("input", \(\) => \{\s*if \(_persistTimer\)[\s\S]*?\}, 300\);/
        .exec(SRC);
      if (!m) throw new Error("the debounced form persist moved — rewrite this check");
      return /syncPayloadPricing\(\)/.test(m[0]) && /proposal_payload: _pp/.test(m[0]);
    })(),
    // EXECUTED. A source check for `continueToDone(e)` is satisfied by the function's own
    // declaration — `async function continueToDone(e)` — so a mutation that deleted the listener
    // survived it. Run the two real statements and fire the handler.
    filesPill: (() => {
      const decl = grab(/^  const _filesPill = .*$/m, "the _filesPill lookup");
      const wire = grab(/^  if \(_filesPill\) .*$/m, "the _filesPill wiring");
      const listeners = [];
      const pill = { addEventListener: (ev, h) => listeners.push([ev, h]) };
      const calls = { prevented: 0, continued: 0 };
      new Function("document", "continueToDone", decl + NL + wire)(
        { querySelector: (sel) => (sel === 'a.step[href="/done.html"]' ? pill : null) },
        () => { calls.continued++; });
      const click = listeners.find(([ev]) => ev === "click");
      if (click) click[1]({ preventDefault: () => { calls.prevented++; } });
      return { wiredEvents: listeners.map(([ev]) => ev), ...calls };
    })(),
  };
})();

// ── 9b. GYP ──────────────────────────────────────────────────────────────────
// Gyp quotes three thicknesses as separate SF buckets and prints them as tokens the template reads
// directly, so its area numbers live in different keys from every other work type. The whitelist
// carries them; this proves they actually move.
out.gyp = (() => {
  const s = baseState();
  s.work_type = "gyp";
  s.base_tab_id = "Gyp";
  s.priced_tabs = [{ id: "Gyp", role: "gyp", kind: "base", total: 24000, sales_tax: 780, remodel: 0 }];
  s.rooms = [{ name: "Gyp", is_base: true, bid: { total: 24000 } }];
  s.proposal_lump_sum = 24000;
  s.sheet_area = { gyp_soft_sf: 27825, gyp_hard_sf: 4100, gyp_corridor_sf: 900 };
  s.proposal_payload.work_type = "gyp";
  s.proposal_payload.values.gyp_soft_sf = "0";
  const sc = scopeFor(s, { lumpText: "$24,000.00", form: { tax_inclusion: "INCLUDED" } });
  const pp = sc.syncPayloadPricing();
  return { soft: pp.values.gyp_soft_sf, hard: pp.values.gyp_hard_sf,
           corridor: pp.values.gyp_corridor_sf, sqft: pp.values.sqft,
           area: pp.values.area_description, total: pp.values.total_formatted };
})();

// ── 10. THE SNAPSHOT TRAP, END TO END ────────────────────────────────────────
// `state` on this page is `TW.getState()` — a ONE-SHOT read. `TW.setState` merges its argument into
// a FRESH read of localStorage, so mutating a nested object and hoping is not persistence: a
// REPLACED top-level key is lost unless it is named in the setState argument. This runs the REAL
// shared.js and the REAL sync, in rebuildPricing's exact call shape, and reads back what a page
// reload would see. It is the only case here that can fail if the persist line is subtly wrong.
out.endToEnd = (() => {
  const store = (() => {
    const m = new Map();
    return { getItem: (k) => (m.has(k) ? m.get(k) : null),
             setItem: (k, v) => m.set(k, String(v)),
             removeItem: (k) => m.delete(k), clear: () => m.clear() };
  })();
  const win = {
    addEventListener() {}, removeEventListener() {},
    location: { href: "http://x/proposal-review.html", search: "", pathname: "/proposal-review.html",
                origin: "http://x", assign() {}, replace() {}, reload() {} },
    history: { replaceState() {} }, setTimeout, clearTimeout,
    fetch: () => Promise.resolve({ ok: true, status: 200, json: async () => ({ ok: true }) }),
  };
  const doc = {
    addEventListener() {}, removeEventListener() {}, readyState: "complete",
    querySelectorAll: () => [], querySelector: () => null, getElementById: () => null,
    createElement: () => ({ setAttribute() {}, appendChild() {}, style: {},
                            classList: { add() {}, remove() {} } }),
    head: { appendChild() {} }, body: { appendChild() {} }, cookie: "",
  };
  const sharedSrc = fs.readFileSync(path.join(ROOT, "shared.js"), "utf8");
  new Function("window", "document", "localStorage", "sessionStorage", "fetch", "location",
               sharedSrc)(win, doc, store, store, win.fetch, win.location);
  const TW = win.TW;

  TW.setState(baseState());                     // what the last Continue left behind
  const snapshot = TW.getState();               // line 2 of proposal-review.js
  flipToEpoxy(snapshot);                        // the sidebar mutates the snapshot in place

  // The real sync, over the real snapshot, with the page's own TW.
  const body = UNITS + NL + "return { syncPayloadPricing };";
  const sc = new Function("state", "document", "form", "TW", "window", "templateVersion",
                          "collectOverrides", "collectBoxOverrides", "sheetSystems", body)(
    snapshot,
    { querySelector: (s) => (s === "#tb-total" ? { textContent: "$18,670.00" } : null),
      getElementById: () => null },
    { querySelector: () => null },
    { readForm: () => ({}) }, { TWAuth: null }, "tpl-v9",
    () => [], () => ({}), () => []);
  const _pp = sc.syncPayloadPricing();

  // rebuildPricing's exact persist.
  TW.setState({ rooms: snapshot.rooms, base_tab_id: snapshot.base_tab_id,
                tab_opts: snapshot.tab_opts, proposal_lump_sum: 18670,
                proposal_sales_tax: 610, proposal_remodel_tax: 0,
                sheet_area: snapshot.sheet_area,
                ...(_pp ? { proposal_payload: _pp } : {}) });

  const reloaded = TW.getState();               // what the next page load reads
  const pp = reloaded.proposal_payload || {};
  return {
    pageBase: (reloaded.rooms.find((r) => r.is_base) || {}).name,
    docBase: ((pp.rooms || []).find((r) => r.is_base) || {}).name,
    docTotalFormatted: (pp.values || {}).total_formatted,
    docWorkType: pp.work_type,
    docNarrativeKept: (pp.values || {}).scope_notes,
  };
})();

console.log(JSON.stringify(out));
