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
      const pp = JSON.parse(JSON.stringify(server.d1.proposal_payload));
      rec.renderedTexture = pp.values.texture;
      // The render key the server would hand back: a function of what it rendered.
      return json(200, { work_type: "epoxy", audience: "Direct", totals: {},
                         xlsx_download_url: "/api/file/X", docx_download_url: "/api/file/D",
                         pdf_download_url: "/api/file/D/pdf",
                         render_id: "K:" + pp.values.texture,
                         document_total: pp.values.total_formatted });
    }
    if (url.includes("/api/portal/publish")) {
      rec.published.push(JSON.parse(opts.body));
      if (server.refuse) return json(409, server.refuse);
      return json(200, { ok: true, revision_no: 1 });
    }
    if (method === "PUT" && url.includes("/api/draft/d1")) {
      const b = JSON.parse(opts.body);
      rec.puts.push(b.data);
      server.d1 = b.data;
      return json(200, { ok: true });
    }
    if (url.includes("/api/file/")) return json(200, {});
    if (method === "GET" && url.includes("/api/draft/d1")) {
      if (server.failGet) return json(503, { detail: "down" });
      return json(200, { data: server.d1 });
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
    TWAuth: { ready: Promise.resolve() },
  };
  sandbox.location = sandbox.window.location;
  sandbox.document = {
    addEventListener() {}, removeEventListener() {}, querySelectorAll: () => [],
    createElement: () => ({ style: {}, appendChild() {}, setAttribute() {}, click() {},
                            classList: { add() {}, remove() {} } }),
    createTextNode: () => ({}), head: { appendChild() {} },
    body: { appendChild() {}, removeChild() {} }, getElementById: () => null,
  };
  vm.createContext(sandbox);
  vm.runInContext(SHARED, sandbox);
  const TW = sandbox.window.TW;
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
    "TW", "builtAt", '"use strict"; ' + FRESH.body)
    .bind(null, TW, builtAt);
  const checkedDocument = { renderId: "" };
  const downloadAs = new AsyncFunction(
    ...DOWNLOAD.args, "TW", "freshDocuments", "paintLumpSum", "fetch", "Blob", "URL", "document",
    "setTimeout", "icon", "console", "checkedDocument", '"use strict"; ' + DOWNLOAD.body);

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
    "checkedDocument", '"use strict"; ' + SEND);

  return {
    TW, rec, checkedDocument,
    /** Fire every timer shared.js queued — the 2.5 s autosave debounce among them. */
    elapse: () => { const due = timers.splice(0); due.forEach((fn) => { if (fn) fn(); }); },
    download: () => downloadAs(
      "pdf_download_url", "X_proposal.pdf",
      { textContent: "Download PDF", disabled: false, innerHTML: "" },
      TW, freshDocuments, () => {}, fetch, class { constructor() {} },
      { createObjectURL: () => "blob:1", revokeObjectURL() {} }, sandbox.document,
      () => 0, () => "", { error: (e) => { rec.downloadError = String(e); } }, checkedDocument),
    send: () => send(
      TW, portalBtn, portalRecip, () => false, () => "kyle@wetreadwell.com", sandbox.document,
      () => {}, { payload: async () => [], clear() {} }, { adds: () => [], mutes: () => [] },
      () => false, () => {}, () => {}, () => "", (e) => staleDocRefusal(e, STALE_CODE),
      portalErrMsg, () => 0,
      sandbox.window, { error() {} }, checkedDocument),
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

    // B. …and presses Send. The body carries the document that was downloaded.
    await t.send();
    const body = t.rec.published[0] || {};
    out.sendAfterDownload = {
      posted: t.rec.published.length,
      renderId: Object.prototype.hasOwnProperty.call(body, "document_render_id")
        ? body.document_render_id : "(absent)",
      err: t.rec.err || null,
    };
  }

  // C. Send with no download on this page view: nothing is claimed, so nothing is checked.
  {
    const w = staleWorld();
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
    const w = staleWorld();
    w.server.refuse = { ok: false, code: "document_changed",
                        error: "Not sent — this proposal changed after you downloaded it. "
                               + "Download it again, check it, then send." };
    const t = await tab(w.local, w.server);
    await t.download();
    await t.send();
    out.refused = { posted: t.rec.published.length, err: t.rec.err || null };
  }

  // E. The draft moved in ANOTHER tab of this browser after this page opened — a texture picked on
  //    the Estimate step there, no Continue. The document this page would send no longer matches
  //    the draft's key, and the drift gate cannot see a texture. Nothing is posted.
  {
    const w = staleWorld();
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
    const w = staleWorld();
    const t = await tab(w.local, w.server, { serverMoved: { texture: "Knockdown" } });
    await t.download();
    await t.send();
    out.movedOnAnotherMachine = { posted: t.rec.published.length, puts: t.rec.puts.length,
                                  err: t.rec.err || null };
  }

  // G. The saved copy cannot be read at Send: nothing can be checked, so nothing is sent.
  {
    const w = staleWorld();
    const t = await tab(w.local, w.server);
    w.server.failGet = true;
    await t.send();
    out.serverUnreadable = { posted: t.rec.published.length, err: t.rec.err || null };
  }

  process.stdout.write(JSON.stringify(out));
})().catch((e) => { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
