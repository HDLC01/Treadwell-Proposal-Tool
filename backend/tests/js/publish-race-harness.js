"use strict";
/* Execute the real flushState() out of shared.js, and the real inert-option logic out of both
 * option strips.
 *
 * WHY EXECUTED. On 2026-08-12 a constant used-but-never-imported took the Active Projects board
 * down with every source-text assertion green. Ordering ("did the save finish before the publish
 * started?") and reset semantics ("does re-ticking restore show?") are behaviour — a grep can see
 * neither.
 *
 * Usage: node publish-race-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = process.argv[2];

// ── the smallest window/fetch shim shared.js needs to load ───────────────────
function loadTW(opts) {
  const o = opts || {};
  const calls = [];                       // every fetch, in order, with a resolve handle
  let pending = [];                       // unresolved PUTs, so the test controls timing
  const store = (() => {
    const m = new Map();
    return { getItem: (k) => (m.has(k) ? m.get(k) : null),
             setItem: (k, v) => m.set(k, String(v)),
             removeItem: (k) => m.delete(k), clear: () => m.clear() };
  })();
  const win = {
    addEventListener() {}, removeEventListener() {},
    location: { href: "http://x/done.html?d=" + (o.draftId || "d1"),
                search: "?d=" + (o.draftId || "d1"), pathname: "/done.html",
                origin: "http://x", assign() {}, replace() {}, reload() {} },
    history: { replaceState() {} },
    setTimeout: setTimeout, clearTimeout: clearTimeout,
  };
  const doc = {
    addEventListener() {}, removeEventListener() {}, readyState: "complete",
    querySelectorAll: () => [], querySelector: () => null, getElementById: () => null,
    createElement: () => ({ setAttribute() {}, appendChild() {}, style: {},
                            classList: { add() {}, remove() {} } }),
    head: { appendChild() {} }, body: { appendChild() {} }, cookie: "",
  };
  const fetchStub = (url, init) => {
    const rec = { url: String(url), method: (init && init.method) || "GET", body: init && init.body,
                  t: calls.length };
    calls.push(rec);
    if (rec.method === "PUT" && /\/api\/draft\//.test(rec.url)) {
      // A save the test resolves by hand — this is what makes the race testable.
      let resolve;
      const p = new Promise((r) => { resolve = r; });
      pending.push({ rec, resolve: (ok) => resolve({ ok: ok !== false, json: async () => ({ ok: true }) }) });
      return p;
    }
    return Promise.resolve({ ok: true, status: 200, json: async () => ({ ok: true }) });
  };
  win.fetch = fetchStub;

  const src = fs.readFileSync(path.join(ROOT, "shared.js"), "utf8");
  new Function("window", "document", "localStorage", "sessionStorage", "fetch", "location", src)(
    win, doc, store, store, fetchStub, win.location);
  return { TW: win.TW, calls, pending: () => pending, flushPending: (ok) => {
    const q = pending; pending = [];
    q.forEach((x) => x.resolve(ok));
  }, store };
}

const out = {};

// ── flushState ───────────────────────────────────────────────────────────────
out.exportsFlushState = (() => {
  const { TW } = loadTW({});
  return typeof TW.flushState === "function";
})();

out.putDraftReturnsAPromise = (() => {
  // The root cause: putDraft was fire-and-forget, so nothing could be awaited.
  const src = fs.readFileSync(path.join(ROOT, "shared.js"), "utf8");
  const m = /function putDraft\(id, blob\) \{[\s\S]*?\n  \}/.exec(src);
  return !!m && /return p;/.test(m[0]);
})();

out.flushWithNothingPending = (() => {
  const { TW, calls } = loadTW({});
  return { result: null, calls: calls.length, note: "resolved below" };
})();

// Async cases have to be sequenced, so collect them in one promise chain.
async function asyncCases() {
  // 1. Nothing dirty → resolves true, writes nothing.
  {
    const h = loadTW({});
    const before = h.calls.filter((c) => c.method === "PUT").length;
    const r = await h.TW.flushState();
    out.nothingPending = { result: r, puts: h.calls.filter((c) => c.method === "PUT").length - before };
  }

  // 2. A debounced edit is FORCED OUT immediately — flushState does not wait 2.5s.
  {
    const h = loadTW({});
    h.TW.setState({ base_tab_id: "Copy1" });
    const putsBefore = h.calls.filter((c) => c.method === "PUT").length;
    const p = h.TW.flushState();              // must fire the save now
    const putsAfterCall = h.calls.filter((c) => c.method === "PUT").length;
    h.flushPending(true);
    const r = await p;
    const put = h.calls.filter((c) => c.method === "PUT").pop();
    out.forcedImmediately = {
      putsBefore, putsAfterCall, result: r,
      sentBase: put ? (JSON.parse(put.body).data || {}).base_tab_id : null,
    };
  }

  // 3. THE RACE: flushState must not resolve until the save actually lands.
  {
    const h = loadTW({});
    h.TW.setState({ base_tab_id: "Copy1" });
    let resolved = false;
    const p = h.TW.flushState().then((v) => { resolved = true; return v; });
    await new Promise((r) => setImmediate(r));      // let microtasks drain
    const resolvedWhileInFlight = resolved;
    h.flushPending(true);
    const r = await p;
    out.awaitsTheWrite = { resolvedWhileInFlight, finalResult: r };
  }

  // 4. A failed write reports false, so the caller can refuse to publish.
  {
    const h = loadTW({});
    h.TW.setState({ base_tab_id: "Copy1" });
    const p = h.TW.flushState();
    h.flushPending(false);
    out.failedWriteIsFalse = await p;
  }
}

// ── the inert-option logic in both strips ────────────────────────────────────
function stripFacts(file, warnClass, isoptClass) {
  const src = fs.readFileSync(path.join(ROOT, "js", file), "utf8");
  // The warning is rendered exactly when marked-as-option AND not shown.
  const warn = new RegExp("isOpt && !show[\\s\\S]{0,400}?" + warnClass).test(src)
            || new RegExp(warnClass + "[\\s\\S]{0,200}?isOpt && !show").test(src);
  // Re-ticking the option RESETS show rather than defaulting an undefined one.
  const handler = new RegExp("is_option = (?:el\\.checked|iso\\.checked)[\\s\\S]{0,600}?" +
                             "if \\(o\\.is_option\\) \\{([^}]*)\\}").exec(src);
  const body = handler ? handler[1] : "";
  return {
    hasWarning: warn,
    resetsShow: /o\.show = true/.test(body) && !/o\.show === undefined/.test(body),
    stillDefaultsPriceMode: /price_mode = "total"/.test(body),
    dropsUnshownFromRooms: /show !== false/.test(src),
  };
}
out.proposalStrip = stripFacts("proposal-review.js", "pr-inert-warn", "pr-isopt");
out.estimateStrip = stripFacts("estimate-review.js", "bb-inert", "bb-isopt");

// ── the Done page: flush BEFORE publish, and the drift comparison ────────────
out.donePage = (() => {
  const src = fs.readFileSync(path.join(ROOT, "js", "done.js"), "utf8");
  const iFlush = src.indexOf("TW.flushState()");
  const iPublish = src.indexOf("/api/portal/publish");
  return {
    flushesBeforePublish: iFlush > 0 && iPublish > 0 && iFlush < iPublish,
    refusesOnFailedFlush: /if \(!await TW\.flushState\(\)\)[\s\S]{0,200}?throw/.test(src),
    hasDriftCheck: /function publishDrift/.test(src),
  };
})();

// publishDrift executed against real shapes.
//
// LIFT ITS CALLEES TOO. publishDrift delegates the document comparison to docDriftRows, which
// the pre-send gate and the warning panel also use, so injecting publishDrift alone gives every
// scenario below a ReferenceError. This is the sixth time in this repo that adding a function an
// already-lifted function calls has killed a harness; the fix is to keep this list current, not
// to inline the helper back into the caller.
out.drift = (() => {
  const src = fs.readFileSync(path.join(ROOT, "js", "done.js"), "utf8");
  const m = /function publishDrift\(sent\) \{[\s\S]*?\n  \}/.exec(src);
  const dep = /function docDriftRows\(d\) \{[\s\S]*?\n  \}/.exec(src);
  if (!m) return { missing: true };
  if (!dep) return { missingDep: "docDriftRows" };
  let STATE = {};
  const fn = new Function("TW", "window", dep[0] + "\n" + m[0] + "; return publishDrift;")(
    { getState: () => STATE, fmtUsd: (n) => "$" + Number(n).toFixed(2) },
    { TW: { fmtUsd: (n) => "$" + Number(n).toFixed(2) } });
  const set = (s) => { STATE = s; };

  // Exactly the 2026-08-13 incident: sent base Epoxy @29942, page showing Room 1 @15801.
  set({ rooms: [{ name: "Room 1", is_base: true }, { name: "Epoxy", show: true }],
        proposal_lump_sum: 15801 });
  const incident = fn({ base_label: "Epoxy", lump_sum: 29942, option_count: 1 });

  set({ rooms: [{ name: "Room 1", is_base: true }, { name: "Epoxy", show: true }],
        proposal_lump_sum: 15801 });
  const agree = fn({ base_label: "Room 1", lump_sum: 15801, option_count: 1 });

  const noSnapshot = fn(null);                     // older backend → say nothing

  set({ rooms: [{ name: "Room 1", is_base: true }], proposal_lump_sum: 15801 });
  const optCount = fn({ base_label: "Room 1", lump_sum: 15801, option_count: 2 });

  set({ rooms: [{ name: "Room 1", is_base: true }], proposal_lump_sum: 15801.004 });
  const rounding = fn({ base_label: "Room 1", lump_sum: 15801, option_count: 0 });

  // An option the estimator deliberately HID. The server counts pickable options, so it sends
  // 0; the page must count the same way or every send with a hidden option cries drift.
  set({ rooms: [{ name: "Room 1", is_base: true },
                { name: "Epoxy", is_base: false, show: false }],
        proposal_lump_sum: 15801 });
  const hiddenOption = fn({ base_label: "Room 1", lump_sum: 15801, option_count: 0 });

  // ── the DOCUMENT half of the snapshot ──────────────────────────────────────
  // Server truth vs server truth, so the local state is deliberately made to AGREE with the page
  // half in every case below: the drift being caught is inside the revision itself.
  const pageOk = { rooms: [{ name: "Epoxy", is_base: true }, { name: "Polish", show: true }],
                   proposal_lump_sum: 18670 };

  // The 2026-08-13 report: page says Epoxy $18,670 base, the PDF still renders Polish $13,265.
  set(pageOk);
  const docStale = fn({ base_label: "Epoxy", lump_sum: 18670, option_count: 1,
                        has_document: true, doc_base_label: "Polish", doc_lump_sum: 13265,
                        doc_option_count: 1 });

  set(pageOk);
  const docAgrees = fn({ base_label: "Epoxy", lump_sum: 18670, option_count: 1,
                         has_document: true, doc_base_label: "Epoxy", doc_lump_sum: 18670,
                         doc_option_count: 1 });

  // A snapshot minted by the previous build carries none of the doc keys — it must stay silent
  // rather than claim the document is wrong because we can't see it.
  set(pageOk);
  const legacySnapshot = fn({ base_label: "Epoxy", lump_sum: 18670, option_count: 1 });

  // The payload exists but is unreadable/legacy-shaped: has_document false → silent.
  set(pageOk);
  const noDocument = fn({ base_label: "Epoxy", lump_sum: 18670, option_count: 1,
                          has_document: false, doc_base_label: null, doc_lump_sum: null,
                          doc_option_count: null });

  // Price-only drift (same base name, different money — a re-price without a Continue).
  set(pageOk);
  const docPriceOnly = fn({ base_label: "Epoxy", lump_sum: 18670, option_count: 1,
                            has_document: true, doc_base_label: "Epoxy", doc_lump_sum: 17110,
                            doc_option_count: 1 });

  // Option-count drift only: an option added on the page never reached the document.
  set(pageOk);
  const docOptionCount = fn({ base_label: "Epoxy", lump_sum: 18670, option_count: 2,
                              has_document: true, doc_base_label: "Epoxy", doc_lump_sum: 18670,
                              doc_option_count: 1 });

  // A base-only document: doc_lump_sum comes from values.proposal_lump_sum, doc_option_count 0.
  set({ rooms: [{ name: "Epoxy", is_base: true }], proposal_lump_sum: 18670 });
  const baseOnlyAgrees = fn({ base_label: "Epoxy", lump_sum: 18670, option_count: 0,
                              has_document: true, doc_base_label: null, doc_lump_sum: 18670,
                              doc_option_count: 0 });

  return { incident, agree, noSnapshot, optCount, rounding, hiddenOption,
           docStale, docAgrees, legacySnapshot, noDocument, docPriceOnly, docOptionCount,
           baseOnlyAgrees };
})();

asyncCases().then(() => { console.log(JSON.stringify(out)); });
