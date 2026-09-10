// Lifts `coverLetterCheck` and BOTH of its callers out of frontend/js/done.js and drives all
// three against a stub DOM, a stub TW store, a stub TWAuth, a stub fetch and fake timers.
//
// WHY EXECUTED. Two surfaces tell an estimator whether the page their customer reads first is
// still carrying instructions addressed to them — the review row before Generate and the banner
// after it. Between them they have to distinguish "no letter", "no letter is WRITTEN for this
// work type", "could not check", "clean" and "N lines still need wording", from inputs that live
// in a state blob and behind a network call. A source read cannot tell those apart: every branch
// is present in the text of the functions in all five cases.
//
// AND IT SHIPPED WRONG SEVEN TIMES, which is why this file is shaped the way it is. Every one was
// the same sentence — the warning's input was not the input the document is built from — and five
// of the seven UNDER-reported, the direction that reaches a customer:
//   1. `Array.isArray(result.cover_letter_placeholders)` before the field existed: key absent, so
//      tick-then-Continue hid the banner;
//   2. `hasOwnProperty`: TRUE, because the field had arrived as `default_factory=list` and a
//      letter-off generate answered `[]`, read as "scanned, clean";
//   3. the cached list described epoxy/Direct while a GC letter was pinned: 1 shown, 4 sent;
//   4. the gate read the TOP-LEVEL flag while the document was built from `proposal_payload`;
//   5. the same mistake, surviving in the review row after the banner was fixed;
//   6. an unbounded fetch: a hung request left the banner absent with Send live, forever;
//   7. `has_letter` returned by the endpoint and read by nothing, so a sealer bid promised a
//      letterhead page 1 and then met a 400.
//
// SO THERE IS ONE READER NOW, and that is the structural point these tests defend.
// `coverLetterCheck` owns the source (`proposal_payload`, with viewFiles' own fallback), the
// variant in the query, the bearer wait, the status check, the body-shape guard and the timeout.
// Both surfaces delegate to it, so they CANNOT disagree — which is the fix for defect 5 stated as
// a property rather than as a patch. The structural assertions therefore all point at the reader,
// and what is left to check of the callers is that each renders every outcome it can be handed.
//
// WHAT IS AND IS NOT EXECUTED. `showPostGenerate` and `showPreGenerate` are hundreds of lines
// wiring buttons, the portal send, the deposit pill and the revision list; lifting them whole
// would need most of the page. What runs here is the three functions verbatim, with their real
// free identifiers bound and nothing else — anything new is a named ReferenceError, which is how
// this file reported the last two rewrites instead of silently testing a stale copy.
"use strict";
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..", "..");
const SRC = fs.readFileSync(path.join(ROOT, "frontend", "js", "done.js"), "utf8");

function balanced(startIndex, open, close) {
  let depth = 1;
  for (let j = startIndex; j < SRC.length; j++) {
    if (SRC[j] === open) depth++;
    else if (SRC[j] === close) {
      depth--;
      if (depth === 0) return SRC.slice(startIndex, j);
    }
  }
  return "";
}

function gone(what, why) {
  throw new Error(what + " could not be lifted out of done.js. " + why
    + " Repoint this harness; do not delete the scenarios.");
}

/** The body of a declared `[async] function NAME() { ... }`. */
function liftDecl(name, why) {
  const m = new RegExp("(?:async\\s+)?function " + name + "\\s*\\(\\s*\\)\\s*\\{").exec(SRC);
  if (!m) gone(name, why);
  return balanced(m.index + m[0].length, "{", "}");
}

/** The body of `([async] function NAME() { ... })();`. */
function liftIIFE(name, why) {
  const m = new RegExp("\\((?:async\\s+)?function " + name + "\\s*\\(\\s*\\)\\s*\\{").exec(SRC);
  if (!m) gone(name, why);
  return balanced(m.index + m[0].length, "{", "}");
}

const CHECK_BODY = liftDecl("coverLetterCheck",
  "It is the ONE reader both cover-letter surfaces delegate to — the source of the variant, the "
  + "flag, the bearer wait, the status check and the timeout.");
const BANNER_BODY = liftIIFE("showCoverLetterPlaceholders",
  "It is the only place an estimator is told that page 1 of their customer's proposal still "
  + "carries instructions written to them.");
const ROW_BODY = liftIIFE("coverLetterRow",
  "It is the line on the review card that says whether the customer's document starts with a "
  + "letterhead page, and the only place a work type with no letter is reported before the 400.");

// One reader, one fetch. Asserted here rather than on the Python side because it is the premise
// of every scenario below: two readers is defect 5 waiting to happen again.
if ((SRC.match(/function coverLetterCheck/g) || []).length !== 1) {
  gone("a single coverLetterCheck", "There is more than one definition, so the two surfaces can "
    + "drift apart again.");
}
if ((SRC.match(/cover-letter\/placeholders/g) || []).length !== 1) {
  gone("a single placeholders fetch site", "A second caller means a second set of decisions about "
    + "which variant to ask about.");
}

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
// A FACTORY, so each scenario gets the reader built over its own stubs. The body is verbatim.
const buildCheck = new Function(
  "TW", "window", "fetch", "console", "AbortController", "setTimeout", "clearTimeout",
  '"use strict"; return async function coverLetterCheck() {' + CHECK_BODY + "};");
const runBanner = new AsyncFunction("document", "coverLetterCheck",
                                    '"use strict";\n' + BANNER_BODY);
// `state` is bound for the row even though the fixed version no longer reads it: bound to a
// snapshot that DISAGREES with the store, so a reintroduced `state` read is a wrong ANSWER rather
// than an unbound identifier. That read is exactly what defect 5 was.
const runRow = new AsyncFunction("document", "coverLetterCheck", "state",
                                 '"use strict";\n' + ROW_BODY);

// ── the smallest DOM these touch ─────────────────────────────────────────────
function el(id) {
  const node = {
    id: id,
    tagName: null,
    style: { display: "<untouched>" },
    textContent: "<untouched>",
    children: [],
    appendChild(child) { this.children.push(child); return child; },
    // Recorded, never used by the shipped code. A placeholder is TEMPLATE COPY out of a .docx
    // and it lands in a page staff read; `innerHTML` would make Kyle's wording an injection
    // vector into the staff tool.
    set innerHTML(v) { node._innerHTMLWrites = (node._innerHTMLWrites || 0) + 1; },
    get innerHTML() { return ""; },
  };
  return node;
}

function reported(v) { return v === undefined ? "<undefined>" : v; }

/** shared.js's store: `getState` PARSES and returns a NEW object every call.
 *  Modelled faithfully because two of the seven defects were stale reads, and a stub that handed
 *  the same object back every time would let a snapshot-based gate pass. */
function makeStore(stored) {
  let raw = JSON.stringify(stored === undefined ? {} : stored);
  return {
    getState() { try { return raw ? JSON.parse(raw) : {}; } catch (e) { return {}; } },
    setState(partial) {
      const merged = Object.assign(this.getState(), partial || {});
      raw = JSON.stringify(merged);
      return merged;
    },
  };
}

/**
 * Build one world: the store, the stubs, and the reader over them.
 *
 *   stored        the state blob (put `proposal_payload` in it to exercise the real source)
 *   reply         {ok, status, body, jsonThrows} — what the endpoint answers
 *   fetchThrows   fetch rejects: offline / DNS / CORS
 *   hang          fetch never resolves unless aborted (drives the real timeout path)
 *   fireTimer     run the timeout callback as soon as it is registered (the fake clock)
 *   noAuth        no window.TWAuth at all (the shipped code feature-detects it)
 *   baseThrows    TW.resolveApiBase() throws
 */
function world(cfg) {
  const store = makeStore(cfg.stored);
  const calls = [];
  const errors = [];
  const timers = { set: [], cleared: [] };
  let nextTimer = 1;

  // A FAKE CLOCK. The shipped timeout is 8 seconds; waiting for it would make this suite
  // unrunnable, and `jest`-style clock control is not available here. So `setTimeout` records
  // (fn, delay) and, when the scenario asks, invokes the callback immediately — which is how the
  // abort below is a REAL abort rather than an assertion that an AbortController was constructed.
  const setTimeoutStub = (fn, delay) => {
    const id = nextTimer++;
    timers.set.push({ id: id, delay: delay });
    if (cfg.fireTimer) fn();
    return id;
  };
  const clearTimeoutStub = (id) => { timers.cleared.push(id); };

  let authResolved = false;
  const ready = new Promise((res) => { queueMicrotask(() => { authResolved = true; res(); }); });
  const win = cfg.noAuth ? {} : { TWAuth: { ready: ready } };

  const fetchStub = (url, opts) => {
    const o = opts || {};
    calls.push({
      url: String(url), opts: o, authWasReady: authResolved,
      hadSignal: !!o.signal, headers: o.headers || null,
    });
    if (cfg.fetchThrows) return Promise.reject(new Error("Failed to fetch"));
    if (cfg.hang) {
      // Resolves ONLY on abort, exactly as a real fetch does.
      return new Promise((resolve, reject) => {
        if (!o.signal) return;                       // unbounded: nothing will ever settle this
        if (o.signal.aborted) {
          const e = new Error("The operation was aborted.");
          e.name = "AbortError";
          return reject(e);
        }
        o.signal.addEventListener("abort", () => {
          const e = new Error("The operation was aborted.");
          e.name = "AbortError";
          reject(e);
        });
      });
    }
    const reply = cfg.reply || { ok: true, body: { placeholders: [] } };
    return Promise.resolve({
      ok: reply.ok !== false,
      status: reply.status || (reply.ok === false ? 500 : 200),
      json: () => (reply.jsonThrows
        ? Promise.reject(new Error("Unexpected token < in JSON"))
        : Promise.resolve(reply.body)),
    });
  };

  const TW = {
    getState: () => store.getState(),
    setState: (p) => store.setState(p),
    resolveApiBase: () => (cfg.baseThrows
      ? (() => { throw new Error("no api base"); })()
      : "https://api.test"),
    authHeaders: () => ({ Authorization: "Bearer test-token" }),
  };
  const consoleStub = { error: (...a) => errors.push(a.map(String).join(" ")) };
  const check = buildCheck(TW, win, fetchStub, consoleStub, AbortController,
                           setTimeoutStub, clearTimeoutStub);
  return { check, calls, errors, timers, store };
}

/** What the READER answers, plus what it did to get there. */
async function reader(cfg) {
  const w = world(cfg);
  let threw = null;
  let out = null;
  try { out = await w.check(); } catch (e) { threw = String((e && e.message) || e); }
  const first = w.calls[0] || null;
  const q = {};
  if (first) {
    (first.url.split("?")[1] || "").split("&").forEach((kv) => {
      const i = kv.indexOf("=");
      if (i > 0) q[decodeURIComponent(kv.slice(0, i))] = decodeURIComponent(kv.slice(i + 1));
    });
  }
  return {
    threw: threw,
    enabled: out ? out.enabled : null,
    hasLetter: out ? reported(out.hasLetter) : null,
    placeholders: out ? (out.placeholders === null ? null : out.placeholders) : null,
    fetches: w.calls.length,
    url: first ? first.url : null,
    q: q,
    headers: first ? first.headers : null,
    hadSignal: first ? first.hadSignal : null,
    authWasReadyAtFetch: first ? first.authWasReady : null,
    timersSet: w.timers.set,
    timersCleared: w.timers.cleared,
    consoleErrors: w.errors.length,
  };
}

/** What the BANNER renders for a stubbed reader answer. */
async function banner(answer, opts) {
  const o = opts || {};
  const nodes = {
    "cl-placeholders": o.noBox ? null : el("cl-placeholders"),
    "cl-ph-list": o.noList ? null : el("cl-ph-list"),
    "cl-ph-head": o.noHead ? null : el("cl-ph-head"),
    "cl-ph-text": o.noNote ? null : el("cl-ph-text"),
  };
  let created = 0;
  let checkCalls = 0;
  const doc = {
    getElementById: (id) => (id in nodes ? nodes[id] : null),
    createElement: (tag) => {
      created++;
      const n = el(null);
      n.tagName = String(tag).toUpperCase();
      n.textContent = "";
      return n;
    },
  };
  let threw = null;
  try {
    await runBanner(doc, async () => { checkCalls++; return answer; });
  } catch (e) { threw = String((e && e.message) || e); }
  const box = nodes["cl-placeholders"];
  const ul = nodes["cl-ph-list"];
  const head = nodes["cl-ph-head"];
  const note = nodes["cl-ph-text"];
  return {
    threw: threw,
    display: box ? box.style.display : "<no box>",
    shown: box ? box.style.display === "" : false,
    head: head ? reported(head.textContent) : "<no head>",
    note: note ? reported(note.textContent) : "<no note>",
    items: ul ? ul.children.map((c) => c.textContent) : [],
    itemTags: ul ? ul.children.map((c) => c.tagName) : [],
    created: created,
    checkCalls: checkCalls,
    innerHTMLWrites: [box, ul, head, note].filter(Boolean)
      .reduce((n, x) => n + (x._innerHTMLWrites || 0), 0),
  };
}

/** What the REVIEW ROW renders for a stubbed reader answer. */
async function row(answer, opts) {
  const o = opts || {};
  const nodes = {
    "rv-cover-row": o.noRow ? null : el("rv-cover-row"),
    "rv-cover": o.noVal ? null : el("rv-cover"),
  };
  const doc = { getElementById: (id) => (id in nodes ? nodes[id] : null) };
  let checkCalls = 0;
  let threw = null;
  try {
    // `state` deliberately DISAGREES with any real store: see runRow above.
    await runRow(doc, async () => { checkCalls++; return answer; },
                 { cover_letter_enabled: !answer.enabled });
  } catch (e) { threw = String((e && e.message) || e); }
  const r = nodes["rv-cover-row"];
  const v = nodes["rv-cover"];
  return {
    threw: threw,
    display: r ? r.style.display : "<no row>",
    shown: r ? r.style.display === "" : false,
    text: v ? reported(v.textContent) : "<no val>",
    checkCalls: checkCalls,
  };
}

/** BOTH surfaces over the SAME world and the SAME REAL reader — no stub between them.
 *
 *  The scenarios above test the reader's decisions and the callers' rendering separately, which
 *  is the right factoring but leaves one thing unsaid: that a defect in the shared reader reaches
 *  BOTH surfaces. That is the whole improvement of extracting it — the row and the banner used to
 *  have a source each, so fixing one left the other wrong for a build. This runs them against one
 *  real reader over one state blob, so `src = st` is a failure of the pair rather than of a unit.
 */
async function pair(cfg) {
  const w = world(cfg);
  const bannerNodes = {
    "cl-placeholders": el("cl-placeholders"), "cl-ph-list": el("cl-ph-list"),
    "cl-ph-head": el("cl-ph-head"), "cl-ph-text": el("cl-ph-text"),
  };
  const rowNodes = { "rv-cover-row": el("rv-cover-row"), "rv-cover": el("rv-cover") };
  const docFor = (nodes) => ({
    getElementById: (id) => (id in nodes ? nodes[id] : null),
    createElement: (tag) => {
      const n = el(null);
      n.tagName = String(tag).toUpperCase();
      n.textContent = "";
      return n;
    },
  });
  let threw = null;
  try {
    await runBanner(docFor(bannerNodes), w.check);
    await runRow(docFor(rowNodes), w.check, { cover_letter_enabled: "deliberately-wrong" });
  } catch (e) { threw = String((e && e.message) || e); }
  return {
    threw: threw,
    bannerShown: bannerNodes["cl-placeholders"].style.display === "",
    bannerHead: reported(bannerNodes["cl-ph-head"].textContent),
    bannerItems: bannerNodes["cl-ph-list"].children.map((c) => c.textContent),
    rowShown: rowNodes["rv-cover-row"].style.display === "",
    rowText: reported(rowNodes["rv-cover"].textContent),
    fetches: w.calls.length,
  };
}

const LINES = ["[SHEEN - pick one: Level 2 (400 grit) / Level 3 (800 grit).]",
               "[COVE HEIGHT - pick one: 4\" / 6\" / 8\".]"];

/** A blob whose `proposal_payload` and top-level keys DISAGREE, so every read is attributable. */
function blob({ ppOn, topOn, ppVariant, topVariant, noPayload }) {
  const st = {
    cover_letter_enabled: topOn,
    work_type: (topVariant || {}).work_type,
    audience: (topVariant || {}).audience,
  };
  if (!noPayload) {
    st.proposal_payload = Object.assign(
      { values: { project_name: "Banner Test" }, cover_letter_enabled: ppOn },
      ppVariant || {});
  }
  return st;
}

const OK = (list, hasLetter) => ({
  ok: true,
  body: { work_type: "epoxy", audience: "Direct",
          has_letter: hasLetter === undefined ? true : hasLetter,
          placeholders: list },
});

// The five answers the reader can produce, named once and shared by both callers' scenarios —
// which is what makes "the row and the banner agree" a comparison and not two descriptions.
const ANSWERS = {
  disabled: { enabled: false, placeholders: null },
  noLetterForWorkType: { enabled: true, hasLetter: false, placeholders: [] },
  couldNotCheck: { enabled: true, hasLetter: null, placeholders: null },
  clean: { enabled: true, hasLetter: true, placeholders: [] },
  lines: { enabled: true, hasLetter: true, placeholders: LINES },
  oneLine: { enabled: true, hasLetter: true, placeholders: [LINES[0]] },
};

async function main() {
  const out = { reader: {}, banner: {}, row: {} };
  const ON = { ppOn: true, topOn: true, ppVariant: { work_type: "epoxy", audience: "Direct" } };

  // ══ THE READER ════════════════════════════════════════════════════════════
  // The flag: proposal_payload wins over top-level, both ways (defect 4/5).
  out.reader.flagOnInPayloadOffOnTop = await reader({
    stored: blob({ ppOn: true, topOn: false,
                   ppVariant: { work_type: "epoxy", audience: "Direct" } }),
    reply: OK(LINES) });
  out.reader.flagOffInPayloadOnOnTop = await reader({
    stored: blob({ ppOn: false, topOn: true,
                   ppVariant: { work_type: "epoxy", audience: "Direct" } }),
    reply: OK(LINES) });
  out.reader.noPayloadTopOn = await reader({
    stored: blob({ topOn: true, topVariant: { work_type: "polish", audience: "GC" },
                   noPayload: true }),
    reply: OK(LINES) });
  out.reader.noPayloadTopOff = await reader({
    stored: blob({ topOn: false, noPayload: true }), reply: OK(LINES) });

  // The variant: asked about the one being SENT, both ways (defect 3).
  out.reader.variantFromPayload = await reader({
    stored: blob({ ppOn: true, topOn: true,
                   ppVariant: { work_type: "polish", audience: "GC" },
                   topVariant: { work_type: "epoxy", audience: "Direct" } }),
    reply: OK(LINES) });
  out.reader.variantFromPayloadReversed = await reader({
    stored: blob({ ppOn: true, topOn: true,
                   ppVariant: { work_type: "epoxy", audience: "Direct" },
                   topVariant: { work_type: "polish", audience: "GC" } }),
    reply: OK(LINES) });
  out.reader.variantDefaults = await reader({
    stored: { cover_letter_enabled: true,
              proposal_payload: { values: { project_name: "x" }, cover_letter_enabled: true } },
    reply: OK(LINES) });

  // The answers it can produce.
  out.reader.lines = await reader({ stored: blob(ON), reply: OK(LINES) });
  out.reader.clean = await reader({ stored: blob(ON), reply: OK([]) });
  out.reader.noLetter = await reader({ stored: blob(ON), reply: OK([], false) });
  out.reader.blanksFiltered = await reader({
    stored: blob(ON), reply: OK(["", "   ", LINES[0], null]) });

  // FAIL LOUD: "cannot tell" is never "clean" (defects 1, 2 and 6 by a new route).
  out.reader.fetchRejects = await reader({ stored: blob(ON), fetchThrows: true });
  out.reader.notOk = await reader({ stored: blob(ON), reply: { ok: false, status: 500, body: {} } });
  out.reader.unauthorized = await reader({
    stored: blob(ON), reply: { ok: false, status: 401, body: {} } });
  // A FAILED REQUEST WHOSE BODY LOOKS LIKE A GOOD ANSWER — what makes `r.ok` load-bearing rather
  // than belt-and-braces. A gateway or auth proxy answers 502/401 with its own JSON envelope.
  out.reader.notOkWithCleanBody = await reader({
    stored: blob(ON),
    reply: { ok: false, status: 502, body: { has_letter: true, placeholders: [] } } });
  out.reader.notOkWithLines = await reader({
    stored: blob(ON),
    reply: { ok: false, status: 401, body: { has_letter: true, placeholders: LINES } } });
  out.reader.jsonThrows = await reader({ stored: blob(ON), reply: { ok: true, jsonThrows: true } });
  out.reader.placeholdersNull = await reader({
    stored: blob(ON), reply: { ok: true, body: { has_letter: true, placeholders: null } } });
  out.reader.placeholdersString = await reader({
    stored: blob(ON), reply: { ok: true, body: { placeholders: "nope" } } });
  out.reader.placeholdersObject = await reader({
    stored: blob(ON), reply: { ok: true, body: { placeholders: { n: 2 } } } });
  out.reader.placeholdersMissing = await reader({
    stored: blob(ON), reply: { ok: true, body: { has_letter: true } } });
  out.reader.apiBaseThrows = await reader({ stored: blob(ON), baseThrows: true, reply: OK(LINES) });

  // The bound (defect 6). `hang` never settles unless the abort fires; `fireTimer` runs the
  // registered callback at once, so this is a real abort through a real AbortController.
  out.reader.hungFetchAborted = await reader({ stored: blob(ON), hang: true, fireTimer: true });
  // The same hang WITHOUT firing the clock would never settle, so it is not run — a harness that
  // hung would be the very failure under test. What is asserted instead is the registered delay.
  out.reader.noAuthObject = await reader({ stored: blob(ON), noAuth: true, reply: OK(LINES) });

  // ══ THE TWO CALLERS, over the SAME five answers ═══════════════════════════
  for (const name of Object.keys(ANSWERS)) {
    out.banner[name] = await banner(ANSWERS[name]);
    out.row[name] = await row(ANSWERS[name]);
  }
  out.banner.blanksAlreadyFiltered = await banner(
    { enabled: true, hasLetter: true, placeholders: [LINES[0]] });
  out.banner.markupAsText = await banner({
    enabled: true, hasLetter: true,
    placeholders: ['[NOTE - <img src=x onerror="alert(1)"> pick one.]'] });
  out.banner.noBoxAtAll = await banner(ANSWERS.lines, { noBox: true });
  out.banner.noListElement = await banner(ANSWERS.lines, { noList: true });
  out.banner.noHeadOrNote = await banner(ANSWERS.lines, { noHead: true, noNote: true });
  out.row.noMarkup = await row(ANSWERS.lines, { noRow: true });
  out.row.noValue = await row(ANSWERS.lines, { noVal: true });

  // ══ THE PAIR, through the real reader ═════════════════════════════════════
  out.pair = {};
  // The payload says a letter IS coming and the top-level flag says it is not. Both surfaces must
  // act on the payload — this is defect 5, and it must now be impossible for one to get it right
  // while the other gets it wrong.
  out.pair.payloadOnTopOff = await pair({
    stored: blob({ ppOn: true, topOn: false,
                   ppVariant: { work_type: "epoxy", audience: "Direct" } }),
    reply: OK(LINES) });
  out.pair.payloadOffTopOn = await pair({
    stored: blob({ ppOn: false, topOn: true,
                   ppVariant: { work_type: "epoxy", audience: "Direct" } }),
    reply: OK(LINES) });
  out.pair.noLetterForWorkType = await pair({
    stored: blob({ ppOn: true, topOn: true,
                   ppVariant: { work_type: "sealer", audience: "GC" } }),
    reply: OK([], false) });
  out.pair.couldNotCheck = await pair({
    stored: blob({ ppOn: true, topOn: true,
                   ppVariant: { work_type: "epoxy", audience: "Direct" } }),
    fetchThrows: true });
  out.pair.clean = await pair({
    stored: blob({ ppOn: true, topOn: true,
                   ppVariant: { work_type: "epoxy", audience: "Direct" } }),
    reply: OK([]) });

  process.stdout.write(JSON.stringify(out));
}

main().catch((e) => { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
