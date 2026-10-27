// A Files page holding an OLDER copy of the draft than the server's, driven through the REAL
// shared.js and the shipped done.js functions.
//
// THE CASE (review of fix 3, 2026-09-25). Kyle has project X's Files page open, or reopens it on a
// machine whose localStorage copy is already stamped X — initDraftSync does not re-read those. On
// another machine RJ changes the texture and presses Continue, so the server holds P2. Kyle presses
// Download PDF. /documents renders the SERVER's P2, so Kyle reads RJ's version. The press then used
// to record the build with TW.setState, and 2.5 s later (or at Send's flushState) the page PUT its
// stale copy (P1 and the old rooms) over the draft: RJ's revision gone, and the Send that followed
// froze P1, a document Kyle never saw.
//
// AND THE SEND ITSELF (review of fix 4, 2026-09-25). With both copies keyed by their own Continue,
// the page's Send went through, froze RJ's document from a page showing Kyle's, and the save a send
// makes afterwards (the message and recipients, remembered for a re-send) PUT Kyle's whole copy back
// over RJ's. Now Send refuses unless this page's copy IS the server's, and that later save is made
// only while the server still holds the copy the send was checked against.
//
// EXECUTED, NOT READ. shared.js runs whole, in a vm context, with only the browser and the network
// stubbed — its real setState/flushState/scheduleServerSave/initDraftSync decide whether a PUT
// happens. `freshDocuments`, `builtAt`, `downloadAs` and the Send button's
// click handler are lifted verbatim out of done.js; every collaborator they reach that is not in
// shared.js is bound explicitly, so a name the page expects and does not have is a thrown error
// here. Timers are captured rather than slept, so "after the debounce" is a deterministic step.
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..", "..", "..");
const SHARED = fs.readFileSync(path.join(ROOT, "frontend", "shared.js"), "utf8");
const SRC = fs.readFileSync(path.join(ROOT, "frontend", "js", "done.js"), "utf8");
// The price rule's page half, as done.html loads it before done.js: Send and Download ask its one
// question (TWPrice.confirmOwnFigures) before a price line with a figure of his own goes out.
const TWPRICE = require(path.join(ROOT, "frontend", "js", "price-lines-core.js"));
// The board's words for the project's one email (crm-core.js scopeSendOutcome), as done.html loads
// it before done.js: a grouped proposal's "Send all proposals in one email" says its answer in them.
const TWCRM = require(path.join(ROOT, "frontend", "js", "crm-core.js"));

function balanced(startIndex) {
  let depth = 1;
  for (let j = startIndex; j < SRC.length; j++) {
    if (SRC[j] === "{") depth++;
    else if (SRC[j] === "}") {
      depth--;
      if (depth === 0) return SRC.slice(startIndex, j);
    }
  }
  return "";
}

function lift(name) {
  const m = new RegExp("function " + name + "\\s*\\(([^)]*)\\)\\s*\\{").exec(SRC);
  if (!m) {
    throw new Error(name + " could not be lifted out of done.js. Repoint this harness; do not "
      + "delete the scenarios.");
  }
  return { args: m[1].split(",").map((s) => s.trim()).filter(Boolean),
           body: balanced(m.index + m[0].length) };
}

/** The lines that name the Send button of a grouped proposal when the page mounts, verbatim. */
function liftGroupLabel() {
  const from = SRC.indexOf("const _myGroup = ");
  const to = SRC.indexOf("if (portalBtn) {", from);
  if (from < 0 || to < 0) throw new Error("the grouped Send button's label moved in done.js");
  return SRC.slice(from, to);
}

function liftSendHandler() {
  const marker = 'portalBtn.addEventListener("click", async () => {';
  const i = SRC.indexOf(marker);
  if (i < 0) throw new Error("the Send button's click handler could not be found in done.js");
  return balanced(i + marker.length);
}

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const FRESH = lift("freshDocuments");
const BUILT_AT = lift("builtAt");
const DOWNLOAD = lift("downloadAs");
const ERR_MSG = lift("portalErrMsg");
const REFUSAL = lift("staleDocRefusal");
const SEND = liftSendHandler();
const GROUP_LABEL = liftGroupLabel();
const STALE_CODE = (/const STALE_DOCUMENT_CODE\s*=\s*"([^"]+)"/.exec(SRC) || [])[1];
if (!STALE_CODE) throw new Error("STALE_DOCUMENT_CODE moved in done.js");

const STAMP = (/const STAMP\s*=\s*"([^"]+)"/.exec(SHARED) || [])[1];
const STATE_KEY = (/const STATE_KEY\s*=\s*"([^"]+)"/.exec(SHARED) || [])[1];
const DRAFT_ID_KEY = (/const DRAFT_ID_KEY\s*=\s*"([^"]+)"/.exec(SHARED) || [])[1];
if (!STAMP || !STATE_KEY || !DRAFT_ID_KEY) throw new Error("shared.js storage keys moved");

const P1 = { work_type: "epoxy", audience: "Direct",
             values: { project_name: "X", texture: "Orange Peel", total_formatted: "$10,000.00" } };
const P2 = { work_type: "epoxy", audience: "Direct",
             values: { project_name: "X", texture: "Smooth Finish", total_formatted: "$12,500.00" } };

function storage(initial) {
  const m = new Map(Object.entries(initial || {}));
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)),
           removeItem: (k) => m.delete(k) };
}

/** One browser tab on /done.html?d=d1 whose localStorage holds `local`, against a server holding
 *  `server`. Returns the tab's TW (real shared.js), the lifted page functions, and the record. */
async function tab(local, server, opts) {
  const rec = { puts: [], published: [], renderedTexture: null };
  const timers = [];
  const json = (status, body) => Promise.resolve({
    ok: status < 400, status, statusText: status < 400 ? "OK" : "ERR",
    json: () => Promise.resolve(body), text: () => Promise.resolve(JSON.stringify(body)),
    arrayBuffer: () => Promise.resolve(new ArrayBuffer(3)) });
  const fetch = (url, opts) => {
    const method = (opts && opts.method) || "GET";
    if (url.includes("/api/draft/d1/documents")) {
      const sent = opts && opts.body ? JSON.parse(opts.body) : {};
      rec.documentsBodies = (rec.documentsBodies || []).concat([sent]);
      // api_draft_documents' own rule (test_send_equals_download.py runs the real one): a page that
      // names the save it asked its question of gets nothing built from a draft stored since.
      if (sent.draft_version && sent.draft_version !== String(server.version || "")) {
        return json(409, { detail: "Not built — this proposal was saved again after this page checked it" });
      }
      const pp = JSON.parse(JSON.stringify(server.d1.proposal_payload));
      rec.renderedTexture = pp.values.texture;
      // The render key the server would hand back: a function of what it rendered.
      return json(200, { work_type: "epoxy", audience: "Direct", totals: {},
                         xlsx_download_url: "/api/file/X", docx_download_url: "/api/file/D",
                         pdf_download_url: "/api/file/D/pdf",
                         render_id: "K:" + pp.values.texture,
                         document_total: pp.values.total_formatted });
    }
    // "Send all proposals in one email" (2026-10-27): the project's one press, for a grouped proposal.
    if (url.includes("/api/portal/scope-group/")) {
      rec.sendAll = (rec.sendAll || []).concat([{ path: url.replace(/^https?:\/\/[^/]+/, ""), method,
                                                  body: JSON.parse(opts.body) }]);
      const a = server.sendAllAnswer || { status: 200, body: { ok: true, published: [{ id: "d1" }],
        results: [{ email: "customer@example.com", delivered: true }] } };
      return json(a.status, a.body);
    }
    if (url.includes("/api/portal/publish")) {
      rec.published.push(JSON.parse(opts.body));
      rec.versionAtPublish = server.version;          // the draft the server would reload now
      if (server.refuse) return json(409, server.refuse);
      // A colleague's save that lands while the publish is running.
      if (server.duringPublish) Object.assign(server.d1, server.duringPublish);
      return json(200, server.publishAnswer || { ok: true, revision_no: 1 });
    }
    if (method === "PUT" && url.includes("/api/draft/d1")) {
      const b = JSON.parse(opts.body);
      rec.puts.push(b.data);
      server.d1 = b.data;
      if (typeof server.version === "string") server.version += "+";   // a stored save moves it
      return json(200, { ok: true });
    }
    if (url.includes("/api/file/")) return json(200, {});
    // The proposal page's list of proposals (GET /api/draft/{id}/proposals), when the scenario gives one.
    if (method === "GET" && url.includes("/api/draft/d1/proposals")) {
      return server.proposals ? json(200, server.proposals) : json(404, { ok: false, code: "not_found" });
    }
    if (method === "GET" && url.includes("/api/draft/d1")) {
      if (server.failGet) return json(503, { detail: "down" });
      // `updated_at`, as api_load_draft answers it, when the scenario gives the row one.
      return json(200, { data: server.d1, updated_at: server.version });
    }
    return json(200, {});
  };
  const sandbox = {
    console, JSON, Promise, Math, Date, Object, Array, String, Number, Error, URL,
    URLSearchParams, Map, Set, isFinite,
    localStorage: storage(local), sessionStorage: storage({}),
    setTimeout: (fn) => { timers.push(fn); return timers.length; },
    clearTimeout: (id) => { if (id) timers[id - 1] = null; },
    fetch,
  };
  sandbox.window = {
    location: { href: "https://tool/done.html?d=d1", origin: "https://tool", search: "?d=d1",
                reload() {}, assign() {} },
    history: { replaceState() {} }, addEventListener() {}, crypto: { randomUUID: () => "x" },
    TWAuth: { ready: Promise.resolve() }, TWCrm: TWCRM,
  };
  sandbox.location = sandbox.window.location;
  // The customer message the estimator typed, when the scenario gives one.
  const msgEl = { value: (opts && opts.message) || "" };
  sandbox.document = {
    addEventListener() {}, removeEventListener() {}, querySelectorAll: () => [],
    createElement: () => ({ style: {}, appendChild() {}, setAttribute() {}, click() {},
                            classList: { add() {}, remove() {} } }),
    createTextNode: () => ({}), head: { appendChild() {} },
    body: { appendChild() {}, removeChild() {} },
    getElementById: (id) => (id === "portal-message" ? msgEl
      : (id === "portal-result" && opts && opts.result) ? opts.result : null),
  };
  vm.createContext(sandbox);
  vm.runInContext(SHARED, sandbox);
  const TW = sandbox.window.TW;
  // THE POP-UP (TWPrice.ownFigureDialog, Hanz 2026-09-28). shared.js's confirmDanger draws DOM this
  // sandbox does not have, so the dialog is answered here by the scenario's `window.confirm`, handed
  // what the estimator reads -- the dialog's title, message and button -- so a question asked with
  // the wrong words, or not through the pop-up at all, is what the test sees.
  if (typeof TW.confirmDanger !== "function") throw new Error("shared.js no longer exports confirmDanger");
  TW.confirmDanger = (o) => Promise.resolve(typeof sandbox.window.confirm === "function"
    ? sandbox.window.confirm([o.title, o.message, o.confirmText].join(" | ")) : false);
  await TW.draftReady;
  // The page's copy was built by a Continue on this machine, so it carries that Continue's key
  // (TW.composeKey — see files-door-harness.js). Stamped locally only, as the Continue left it.
  // `moved` is what another tab of this browser does afterwards: an edit, and no Continue.
  TW.setLocalState({ proposal_payload_key: TW.composeKey(TW.getState()) });
  if (opts && opts.moved) TW.setLocalState(opts.moved);
  // The server's copy is RJ's, built by RJ's own Continue, so it carries RJ's key. `serverMoved` is
  // what RJ did afterwards on his machine: an Estimate-step edit, saved, and no Continue.
  server.d1.proposal_payload_key = TW.composeKey(server.d1);
  if (opts && opts.serverMoved) Object.assign(server.d1, opts.serverMoved);

  const builtAt = new Function(...BUILT_AT.args, '"use strict"; ' + BUILT_AT.body);
  const freshDocuments = new AsyncFunction(
    "TW", "builtAt", ...FRESH.args, '"use strict"; ' + FRESH.body)
    .bind(null, TW, builtAt);
  const checkedDocument = { renderId: "" };
  const downloadAs = new AsyncFunction(
    ...DOWNLOAD.args, "TW", "freshDocuments", "paintLumpSum", "fetch", "Blob", "URL", "document",
    "setTimeout", "icon", "console", "checkedDocument", "TWPrice", "window",
    '"use strict"; ' + DOWNLOAD.body);

  // The handler's error path is real too: what the estimator reads is what these two decide.
  const portalErrMsg = new Function(...ERR_MSG.args, '"use strict"; ' + ERR_MSG.body);
  const staleDocRefusal = new Function(...REFUSAL.args, "STALE_DOCUMENT_CODE",
                                       '"use strict"; ' + REFUSAL.body);
  const portalBtn = { textContent: "Send", disabled: false, focus() {} };
  const portalRecip = { allEmails: () => ["customer@example.com"], noFollowupsToSend: () => [],
                        setErr: (m) => { rec.err = m; }, setBusy() {}, hasIntake: false };
  const send = new AsyncFunction(
    "TW", "portalBtn", "portalRecip", "readRequireDeposit", "readAssignedEstimator", "document",
    "alert", "sendAtts", "notifyPick", "showSaveBlocked", "showStaleDoc", "mountRevisions",
    "publishDrift", "staleDocRefusal", "portalErrMsg", "setTimeout", "window", "console",
    "checkedDocument", "TWPrice", '"use strict"; ' + SEND);

  return {
    TW, rec, checkedDocument, ls: sandbox.localStorage, ss: sandbox.sessionStorage,
    window: sandbox.window, portalBtn,
    /** The mount's label for the Send button, run on a fresh button. */
    mountLabel: () => { const btn = { textContent: "\u2197 Send to customer portal" };
      new Function("TW", "portalBtn", '"use strict"; ' + GROUP_LABEL)(TW, btn); return btn.textContent; },
    /** Fire every timer shared.js queued — the 2.5 s autosave debounce among them. */
    elapse: () => { const due = timers.splice(0); due.forEach((fn) => { if (fn) fn(); }); },
    download: () => downloadAs(
      "pdf_download_url", "X_proposal.pdf",
      { textContent: "Download PDF", disabled: false, innerHTML: "" },
      TW, freshDocuments, () => {}, fetch, class { constructor() {} },
      { createObjectURL: () => "blob:1", revokeObjectURL() {} }, sandbox.document,
      () => 0, () => "", { error: (e) => { rec.downloadError = String(e); } }, checkedDocument,
      TWPRICE, sandbox.window),
    send: () => send(
      TW, portalBtn, portalRecip, () => false, () => "kyle@wetreadwell.com", sandbox.document,
      () => {},
      // The attachments being encoded: `duringEncode` is whatever lands on the server meanwhile.
      { payload: async () => { if (opts && opts.duringEncode) opts.duringEncode(server); return []; },
        clear() {} },
      { adds: () => [], mutes: () => [] },
      () => false, () => {}, () => {}, () => "", (e) => staleDocRefusal(e, STALE_CODE),
      portalErrMsg, () => 0,
      sandbox.window, { error() {} }, checkedDocument, TWPRICE),
  };
}

function staleWorld() {
  const local = {};
  // One base room each and no options, so the page's own stale-document gate (docDrift) has
  // nothing to object to and the Send reaches the server — the case is the staleness it CANNOT see.
  local[STATE_KEY] = JSON.stringify({ [STAMP]: "d1", project_name: "X",
                                      rooms: [{ name: "old", is_base: true }],
                                      proposal_payload: P1 });
  local[DRAFT_ID_KEY] = "d1";
  const server = { d1: { project_name: "X", rooms: [{ name: "RJ's revision", is_base: true }],
                         proposal_payload: P2 } };
  return { local, server };
}

/** A page that is CURRENT: this browser and the server hold the same copy (RJ's P2). */
function current() {
  const w = staleWorld();
  const mine = { project_name: "X", rooms: [{ name: "RJ's revision", is_base: true }],
                 proposal_payload: P2 };
  w.local[STATE_KEY] = JSON.stringify(Object.assign({ [STAMP]: "d1" }, mine));
  w.server.d1 = JSON.parse(JSON.stringify(mine));
  return w;
}

(async function () {
  const out = {};

  // A. The stale page presses Download, then the debounce elapses and Send's flush runs.
  {
    const w = staleWorld();
    const t = await tab(w.local, w.server);
    await t.download();
    t.elapse();
    await t.TW.flushState();
    const mine = t.TW.getState();
    out.download = {
      rendered: t.rec.renderedTexture,
      puts: t.rec.puts.length,
      serverTexture: w.server.d1.proposal_payload.values.texture,
      serverRooms: w.server.d1.rooms,
      checked: t.checkedDocument.renderId,
      keptLocally: !!mine.generate_result,
      stamp: mine.generated_lump_sum,
      error: t.rec.downloadError || null,
    };

    // A2. …and presses Send. This page's copy (Orange Peel, the old rooms, keyed by Kyle's own
    //     Continue) is not the server's (RJ's, keyed by RJ's): nothing is sent, and the save a
    //     send makes afterwards never happens, so RJ's copy stays.
    await t.send();
    t.elapse();
    await t.TW.flushState();
    out.staleDownloadThenSend = {
      posted: t.rec.published.length, puts: t.rec.puts.length, err: t.rec.err || null,
      serverTexture: w.server.d1.proposal_payload.values.texture, serverRooms: w.server.d1.rooms,
    };
  }

  // A3. The same stale page, Send with no Download first.
  {
    const w = staleWorld();
    const t = await tab(w.local, w.server);
    await t.send();
    t.elapse();
    await t.TW.flushState();
    out.staleSend = {
      posted: t.rec.published.length, puts: t.rec.puts.length, err: t.rec.err || null,
      serverTexture: w.server.d1.proposal_payload.values.texture, serverRooms: w.server.d1.rooms,
    };
  }

  // B. A CURRENT page presses Download, then Send. The body carries the document downloaded.
  {
    const w = current();
    const t = await tab(w.local, w.server);
    await t.download();
    await t.send();
    const body = t.rec.published[0] || {};
    out.sendAfterDownload = {
      checked: t.checkedDocument.renderId,
      posted: t.rec.published.length,
      renderId: Object.prototype.hasOwnProperty.call(body, "document_render_id")
        ? body.document_render_id : "(absent)",
      err: t.rec.err || null,
    };
  }

  // C. Send with no download on this page view: nothing is claimed, so nothing is checked.
  {
    const w = current();
    const t = await tab(w.local, w.server);
    await t.send();
    const body = t.rec.published[0] || {};
    out.sendWithoutDownload = {
      posted: t.rec.published.length,
      hasKey: Object.prototype.hasOwnProperty.call(body, "document_render_id"),
      err: t.rec.err || null,
    };
  }

  // D. The server refuses: the document changed after the download. The estimator reads the
  //    server's own sentence, and the page does not claim a send.
  {
    const w = current();
    w.server.refuse = { ok: false, code: "document_changed",
                        error: "Not sent — this proposal changed after you downloaded it. "
                               + "Download it again, check it, then send." };
    const t = await tab(w.local, w.server);
    await t.download();
    await t.send();
    out.refused = { posted: t.rec.published.length, err: t.rec.err || null };
  }

  // L. A current page sends, and the server still holds that copy afterwards: the message and the
  //    recipients are remembered on the draft for a re-send, in ONE save made straight away.
  {
    const w = current();
    const t = await tab(w.local, w.server, { message: "See the attached." });
    await t.send();
    out.remembered = { posted: t.rec.published.length, puts: t.rec.puts.length,
                       serverMessage: w.server.d1.portal_message || null,
                       serverTexture: w.server.d1.proposal_payload.values.texture,
                       err: t.rec.err || null };
  }

  // M. A current page sends, and a colleague's save lands WHILE the publish runs (RJ picks
  //    Knockdown). This page's copy is now the older one, so nothing is remembered and nothing is
  //    PUT: RJ's save stands.
  {
    const w = current();
    w.server.duringPublish = { texture: "Knockdown" };
    const t = await tab(w.local, w.server, { message: "See the attached." });
    await t.send();
    t.elapse();
    await t.TW.flushState();
    out.colleagueDuringPublish = { posted: t.rec.published.length, puts: t.rec.puts.length,
                                   serverTexture: w.server.d1.texture || null,
                                   serverMessage: w.server.d1.portal_message || null,
                                   // What this browser now records as the server's copy: the one
                                   // the send found equal, so the next Files visit can tell RJ's
                                   // save is simply newer (it takes it) rather than a conflict.
                                   recordedAsSynced: t.ls.getItem("treadwell.proposal_tool.synced")
                                     === "d1:" + t.TW.draftDigest(t.TW.getState()) };
  }

  // E. The draft moved in ANOTHER tab of this browser after this page opened — a texture picked on
  //    the Estimate step there, no Continue. The document this page would send no longer matches
  //    the draft's key, and the drift gate cannot see a texture. Nothing is posted.
  {
    const w = current();
    const t = await tab(w.local, w.server, { moved: { texture: "Orange Peel" } });
    await t.send();
    out.movedInAnotherTab = { posted: t.rec.published.length, puts: t.rec.puts.length,
                              err: t.rec.err || null };
  }

  // F. Finding 3. The draft moved on ANOTHER MACHINE after this page opened: RJ picked Knockdown on
  //    the Estimate step and left without Continue. This page's copy still holds by its own key, the
  //    render-id gate sees the same payload, and the drift gate cannot see a texture — but the
  //    SERVER's copy, which the publish freezes, no longer matches its document. Nothing is posted.
  {
    const w = current();
    const t = await tab(w.local, w.server, { serverMoved: { texture: "Knockdown" } });
    await t.download();
    await t.send();
    out.movedOnAnotherMachine = { posted: t.rec.published.length, puts: t.rec.puts.length,
                                  err: t.rec.err || null };
  }

  // N. Review of fix 4, round 2. A current page; Kyle presses Send with no Download, and while the
  //    attachments encode RJ's Continue lands on the server (Broadcast Flake, keyed, saved). The
  //    page's checks all passed against the copy it read; the publish then froze RJ's. The publish
  //    now carries WHEN the checked copy was saved, which the server compares with the draft it
  //    reloads (api_portal_publish; test_send_equals_download.py) — here, that it is the checked
  //    copy's and not the one on the server by the time the publish is sent.
  {
    const r = {};
    for (const who of ["colleagueDuringEncode", "nobody"]) {
      const w = current();
      w.server.version = "2026-09-25T15:00:00+00:00";
      const checked = w.server.version;
      const t = await tab(w.local, w.server, who === "nobody" ? {} : { duringEncode: (s) => {
        s.d1 = JSON.parse(JSON.stringify(s.d1));
        s.d1.proposal_payload.values.texture = "RJ Broadcast Flake";
        s.d1.proposal_payload_key = t.TW.composeKey(s.d1);
        s.version = "2026-09-25T15:00:07+00:00";
      } });
      await t.send();
      const body = t.rec.published[0] || {};
      r[who] = { posted: t.rec.published.length, puts: t.rec.puts.length, err: t.rec.err || null,
                 renderIdSent: Object.prototype.hasOwnProperty.call(body, "document_render_id"),
                 versionSent: body.draft_version || null, checked,
                 serverAtPublish: t.rec.versionAtPublish };
    }
    out.versionHeld = r;
  }

  // H. A price line prints a figure of the estimator's own (the Proposal step listed it in the
  //    document it built). Send ASKS, in Hanz's words: Cancel sends nothing, OK sends. Hanz,
  //    2026-09-25: "warn, then let him send."
  {
    const r = {};
    for (const answer of [false, true]) {
      const w = current();
      const pp = JSON.parse(JSON.stringify(P2));
      pp.price_warnings = [{ key: "base", says: "$9,999", estimate: "$12,500" }];
      const mine = { project_name: "X", rooms: [{ name: "RJ's revision", is_base: true }], proposal_payload: pp };
      w.local[STATE_KEY] = JSON.stringify(Object.assign({ [STAMP]: "d1" }, mine));
      w.server.d1 = JSON.parse(JSON.stringify(mine));
      const t = await tab(w.local, w.server);
      const asked = [];
      t.window.confirm = (msg) => { asked.push(msg); return answer; };
      t.TW.setLocalState({ proposal_payload_key: t.TW.composeKey(t.TW.getState()) });
      w.server.d1.proposal_payload_key = t.TW.composeKey(w.server.d1);
      await t.send();
      r[answer ? "ok" : "cancel"] = { asked, posted: t.rec.published.length };
    }
    // And a document with no such line is not asked about at all.
    {
      const w = current();
      const t = await tab(w.local, w.server);
      const asked = [];
      t.window.confirm = (msg) => { asked.push(msg); return false; };
      await t.send();
      r.none = { asked, posted: t.rec.published.length };
    }
    out.priceWarning = r;
  }

  // I. THE COPY THAT IS BUILT (review of dfcf589). Kyle's Files page is current and clean. RJ, on
  //    another machine, types $15,000 over the base amount and presses Continue: the SERVER's copy
  //    now lists it. Kyle presses Download PDF. It used to ask about Kyle's own copy (nothing to ask)
  //    and download RJ's $15,000 document; Send, in the same case, refuses. Download asks about the
  //    copy /documents renders now. Then the same press with RJ saving AGAIN while the question is
  //    on screen (a different figure): the build names the save it asked about, and nothing is
  //    built from the one stored since.
  {
    const r = {};
    const rjs = (w, texture, says) => {
      const pp = JSON.parse(JSON.stringify(P2));
      pp.values.texture = texture;
      pp.price_warnings = [{ key: "base", says, estimate: "$12,500" }];
      w.server.d1 = Object.assign(JSON.parse(JSON.stringify(w.server.d1)), { proposal_payload: pp });
    };
    for (const answer of [false, true, "colleagueUnderTheQuestion"]) {
      const w = current();
      w.server.version = "2026-09-26T10:00:00+00:00";
      const t = await tab(w.local, w.server);
      rjs(w, "RJ hand figure", "$15,000");
      w.server.d1.proposal_payload_key = t.TW.composeKey(w.server.d1);
      w.server.version = "2026-09-26T10:05:00+00:00";
      const asked = [];
      t.window.confirm = (msg) => {
        asked.push(msg);
        if (answer === "colleagueUnderTheQuestion") {
          rjs(w, "RJ again", "$18,000");
          w.server.version = "2026-09-26T10:06:00+00:00";
          return true;
        }
        return answer;
      };
      await t.download();
      r[answer === true ? "ok" : answer === false ? "cancel" : answer] = {
        asked, rendered: t.rec.renderedTexture, bodies: t.rec.documentsBodies || [],
        checked: t.checkedDocument.renderId, error: t.rec.downloadError || null,
        puts: t.rec.puts.length };
    }
    // Send, in the same case as the first: refused, as it always was.
    {
      const w = current();
      const t = await tab(w.local, w.server);
      rjs(w, "RJ hand figure", "$15,000");
      w.server.d1.proposal_payload_key = t.TW.composeKey(w.server.d1);
      const asked = [];
      t.window.confirm = (msg) => { asked.push(msg); return true; };
      await t.send();
      r.send = { asked, posted: t.rec.published.length, err: t.rec.err || null };
    }
    out.serverCopyAsked = r;
  }

  // G. The saved copy cannot be read at Send: nothing can be checked, so nothing is sent.
  {
    const w = current();
    const t = await tab(w.local, w.server);
    w.server.failGet = true;
    await t.send();
    out.serverUnreadable = { posted: t.rec.published.length, err: t.rec.err || null };
  }

  // N. ONE OF SEVERAL PROPOSALS MADE FROM ONE ESTIMATE ("Create Multiple Proposals"): the publish answers with its
  //    scope group, and the line under the button says which proposal of how many (GET .../proposals). A scope made the
  //    older way (a list of one) or a list that cannot be read keeps the scope sentence.
  {
    const said = async (proposals) => {
      const w = current();
      w.server.publishAnswer = { ok: true, revision_no: 1, scope_group: "G1", scope_label: "Base Bid 2" };
      w.server.proposals = proposals;
      const result = { style: {}, textContent: "", kids: [], appendChild(c) { this.kids.push(c); } };
      const t = await tab(w.local, w.server, { result });
      await t.send();
      return { posted: t.rec.published.length, err: t.rec.err || null,
               lines: result.kids.filter((k) => k.className === "portal-scope").map((k) => k.textContent) };
    };
    out.groupedPublish = {
      three: await said({ ok: true, parent_id: "P1", members: [{ id: "P1" }, { id: "d1" }, { id: "C3" }] }),
      one: await said({ ok: true, parent_id: "d1", members: [{ id: "d1" }] }),
      unread: await said(null),
    };
  }

  // O. A PROPOSAL OF A PROJECT WITH SEVERAL (Hanz, 2026-10-27): "it should send out without publishing
  //    ... And it must come in one email only." The button is named for the one press, posts ONCE to
  //    the send-all and never to the publish, and says the answer in the board drawer's own words.
  {
    const grouped = async (answer) => {
      const w = current();
      const sg = { id: "G1", label: "Room 2" };
      const st = JSON.parse(w.local[STATE_KEY]);
      st.scope_group = sg;
      w.local[STATE_KEY] = JSON.stringify(st);
      w.server.d1.scope_group = sg;
      w.server.version = "2026-10-27T09:00:00+00:00";
      if (answer) w.server.sendAllAnswer = answer;
      const result = { style: {}, textContent: "", kids: [], appendChild(c) { this.kids.push(c); } };
      const t = await tab(w.local, w.server, { result, message: "Your three proposals." });
      const label = t.mountLabel();
      t.portalBtn.textContent = label;
      await t.send();
      return { label, button: t.portalBtn.textContent, disabled: t.portalBtn.disabled,
               sendAll: t.rec.sendAll || [], published: t.rec.published.length,
               err: t.rec.err || null, result: result.textContent };
    };
    const ungrouped = await tab(current().local, current().server);
    out.sendAll = {
      ungroupedLabel: ungrouped.mountLabel(),
      sent: await grouped(null),
      blocked: await grouped({ status: 409, body: { ok: false, code: "not_ready_to_send",
        blocked: [{ id: "C3", label: "Room 3", error: "build its files on its Files page first" }],
        error: "Nothing was sent. Room 3: build its files on its Files page first." } }),
      nothing: await grouped({ status: 409, body: { ok: false, error: "nothing_to_send", published: [] } }),
      halfway: await grouped({ status: 502, body: { ok: false, code: "publish_failed",
        published: [{ id: "d1", label: "Room 2", revision_no: 1 }], failed: { id: "C3", label: "Room 3" },
        error: "Nothing was emailed. Room 3 could not be published (Portal error.). Room 2 was published and will go in the email. Press the button again in a minute to finish." } }),
    };
  }

  // P. PROPOSALS THAT WERE NEVER BUILT (Hanz, 2026-10-28): the press answers `needs_build`. The page
  //    starts Send all's walk (send-all-chain.js, the real module) with what the estimator chose,
  //    says it is building, and publishes nothing. A page with no walk, or one that already came back
  //    from one, says the server's manual sentence instead and gives the button back.
  {
    const CHAIN = require(path.join(ROOT, "frontend", "js", "send-all-chain.js"));
    const NEEDS = { status: 409, body: { ok: false, code: "needs_build",
      build: [{ id: "C3", label: "Room 3" }],
      error: "Nothing was sent. Room 3 has never been built. Open its Proposal step and press "
             + "Continue to Done, then send again." } };
    const press = async (how) => {
      const w = current();
      const sg = { id: "G1", label: "Room 2" };
      const st = JSON.parse(w.local[STATE_KEY]);
      st.scope_group = sg;
      w.local[STATE_KEY] = JSON.stringify(st);
      w.server.d1.scope_group = sg;
      w.server.version = "2026-10-28T09:00:00+00:00";
      w.server.sendAllAnswer = NEEDS;
      const t = await tab(w.local, w.server, { message: "Your three proposals." });
      const nav = [];
      t.window.location.href = "https://tool/done.html?composed=1&d=d1";
      t.window.location.assign = (u) => nav.push(String(u));
      let chain = null;
      if (how !== "noWalk") {
        chain = CHAIN.create({ sessionStorage: t.ss, location: t.window.location,
                               history: t.window.history, crypto: require("crypto").webcrypto });
        t.window.TWSendAll = chain;
        if (how === "cameBack") {
          t.ss.setItem(chain.KEY, JSON.stringify({ token: "T1", group: "G1", queue: [], built: ["C3"],
            labels: {}, returnUrl: "/done.html?d=d1", stash: {}, expires: Date.now() + 60000, done: true }));
          chain.take(new URLSearchParams("?sendall_resume=T1"), "G1");
        }
      }
      t.portalBtn.textContent = t.mountLabel();
      await t.send();
      return { button: t.portalBtn.textContent, disabled: t.portalBtn.disabled, err: t.rec.err || null,
               nav, published: t.rec.published.length, sendAll: (t.rec.sendAll || []).length,
               record: chain ? JSON.parse(t.ss.getItem(chain.KEY) || "null") : null };
    };
    out.needsBuild = { walk: await press("walk"), noWalk: await press("noWalk"),
                       cameBack: await press("cameBack") };
  }

  // Q. BACK FROM BUILDING: the mount takes the finished walk once (its own lines, verbatim), and
  //    resumeSendAll puts the choices back and presses the page's own Send button — or, with files
  //    attached before the walk, asks for them again and presses nothing.
  {
    const CHAIN = require(path.join(ROOT, "frontend", "js", "send-all-chain.js"));
    const RESUME = lift("resumeSendAll");
    const resume = new AsyncFunction("document", "portalRecip", "notifyPick", "paintNotifyChips",
                                     ...RESUME.args, '"use strict"; ' + RESUME.body);
    const run = async (stash) => {
      const els = { "portal-message": { value: "" }, "portal-require-deposit": { checked: true },
                    "portal-estimator": { value: "", options: [{ value: "" }, { value: "rj@wetreadwell.com" },
                                                              { value: "kyle@wetreadwell.com" }] } };
      const restored = [];
      const clicks = [];
      let err = null;
      let painted = 0;
      const notifyPick = { ready: true, changed: { "old@wetreadwell.com": true } };
      const ret = await resume({ getElementById: (id) => els[id] || null },
        { restore: (e, n) => restored.push([e, n]), setErr: (m) => { err = m; } },
        notifyPick, () => { painted++; }, stash, { click: () => clicks.push(1), focus() {} },
        Promise.resolve());
      return { ret, message: els["portal-message"].value, deposit: els["portal-require-deposit"].checked,
               estimator: els["portal-estimator"].value, restored, clicks: clicks.length, err,
               changed: notifyPick.changed, painted };
    };
    const stash = { message: "Your three proposals.", emails: ["customer@example.com", "pm@x.test"],
                    no_followups: ["pm@x.test"], assigned_estimator: "rj@wetreadwell.com",
                    require_deposit: false, notify_add: ["troy@wetreadwell.com"], notify_mute: [],
                    attachments: 0 };
    out.resume = { plain: await run(stash), attached: await run(Object.assign({}, stash, { attachments: 2 })) };

    // The mount's take, verbatim, run three times: the walk's return, a repaint, another project.
    const marker = 'if (portalBtn && _myGroup && typeof _myGroup === "object" && _myGroup.id && window.TWSendAll) {';
    const at = SRC.indexOf(marker);
    if (at < 0) throw new Error("the mount's take of Send all's walk moved in done.js");
    const TAKE = marker + balanced(at + marker.length) + "}";
    const mountTake = new Function("portalBtn", "_myGroup", "window", "location", "resumeSendAll",
                                   "_estMounted", "_rosterMounted", '"use strict"; ' + TAKE);
    const ss = storage({});
    const loc = { pathname: "/done.html", search: "?d=d1&files=1&sendall_resume=T2" };
    const hist = [];
    const win = { TWSendAll: CHAIN.create({ sessionStorage: ss, location: loc,
                                            history: { replaceState: (s, t, u) => hist.push(u) } }) };
    ss.setItem(win.TWSendAll.KEY, JSON.stringify({ token: "T2", group: "G1", queue: [], built: ["C3"],
      labels: { C3: "Room 3" }, returnUrl: "/done.html?d=d1&files=1", stash: { message: "hi" },
      expires: Date.now() + 60000, done: true }));
    const calls = [];
    const pressAgain = (s) => calls.push(s);
    mountTake({}, { id: "G2" }, win, loc, pressAgain, null, null);        // another project's page
    const otherProject = calls.length;
    ss.setItem(win.TWSendAll.KEY, JSON.stringify({ token: "T2", group: "G1", queue: [], built: ["C3"],
      labels: { C3: "Room 3" }, returnUrl: "/done.html?d=d1&files=1", stash: { message: "hi" },
      expires: Date.now() + 60000, done: true }));
    mountTake({}, { id: "G1" }, win, loc, pressAgain, null, null);        // back from the walk
    mountTake({}, { id: "G1" }, win, loc, pressAgain, null, null);        // the same page mounting again
    out.mountTake = { otherProject, calls, addressBar: hist[hist.length - 1] || null };
  }

  process.stdout.write(JSON.stringify(out));
})().catch((e) => { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
