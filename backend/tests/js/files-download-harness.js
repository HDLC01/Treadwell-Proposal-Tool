// Lifts the Files page's download path out of frontend/js/done.js and drives it.
//
// EXECUTED, NOT READ. `freshDocuments`, `payloadFromDraft`, `builtAt`, `doGenerate` and the
// `downloadAs` nested inside showPostGenerate are taken verbatim out of the shipped file and run in
// a bare scope with every collaborator bound explicitly — so an identifier the page expects and does
// not have is a thrown error here, not a green suite and a dead button.
//
// WHAT IS PINNED: a Download press builds its file NOW, from the SAVED draft, through the server
// route Send uses (/api/draft/{id}/documents), after the page's pending save is flushed — and never
// fetches the token kept in `generate_result` from an earlier build. Hanz, 2026-09-25: "Sending out
// the proposal should be the same PDF from the download button in the last page." The press
// records the build LOCALLY only (setLocalState, never setState) and keeps the render_id of the
// file that came back in `checkedDocument`, which Send hands to the server. That the press writes
// nothing to the server is proven against the REAL shared.js in files-stale-page-harness.js.
"use strict";

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..", "..");
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

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const FRESH = lift("freshDocuments");
const FROM_DRAFT = lift("payloadFromDraft");
const BUILT_AT = lift("builtAt");
const DOWNLOAD = lift("downloadAs");
const GENERATE = lift("doGenerate");

const OLD = { work_type: "epoxy", xlsx_download_url: "/api/file/OLDX",
              docx_download_url: "/api/file/OLD", pdf_download_url: "/api/file/OLD/pdf" };
// `document_total` deliberately NOT the page's own figure ($41,250.00, below): the server rendered
// ITS copy of the payload, and the card must show what that copy printed.
const NEW = { work_type: "epoxy", xlsx_download_url: "/api/file/NEWX",
              docx_download_url: "/api/file/NEW", pdf_download_url: "/api/file/NEW/pdf",
              render_id: "K-NEW", document_total: "$44,000.00" };

/** One page's worth of collaborators. `log` is the order everything happened in. */
function page(opts) {
  const log = [];
  const posted = [];
  const fetched = [];
  const clicked = [];
  let st = JSON.parse(JSON.stringify(opts.state));
  const TW = {
    flushState: async () => { log.push("flush"); return opts.flushOk !== false; },
    getState: () => st,
    setState: (p) => { st = Object.assign({}, st, p); log.push("setState"); return st; },
    setLocalState: (p) => { st = Object.assign({}, st, p); log.push("setLocalState"); return st; },
    getDraftId: () => (opts.draftId === undefined ? "d1" : opts.draftId),
    postJSON: async (p, body) => {
      log.push("post " + p);
      posted.push({ path: p, body: body });
      return JSON.parse(JSON.stringify(NEW));
    },
    absoluteUrl: (u) => "https://tool" + u,
    authHeaders: () => ({ Authorization: "Bearer t" }),
  };
  const fetchStub = async (url) => {
    log.push("fetch " + url);
    fetched.push(url);
    const status = opts.fetchStatus || 200;
    return { ok: status < 400, status: status, statusText: status < 400 ? "OK" : "Not Found",
             arrayBuffer: async () => new ArrayBuffer(3) };
  };
  const documentStub = {
    createElement: () => ({ click() { clicked.push(this.download); } }),
    body: { appendChild() {}, removeChild() {} },
    getElementById: (id) => (opts.nodes || {})[id] || null,
  };
  const URLStub = { createObjectURL: () => "blob:1", revokeObjectURL() {} };
  class BlobStub { constructor(parts, o) { this.type = o && o.type; } }
  const builtAt = new Function(...BUILT_AT.args, '"use strict"; ' + BUILT_AT.body);
  const payloadFromDraft = new Function(...FROM_DRAFT.args, '"use strict"; ' + FROM_DRAFT.body);
  const freshDocuments = new AsyncFunction(
    "TW", "payloadFromDraft", "builtAt", '"use strict"; ' + FRESH.body)
    .bind(null, TW, payloadFromDraft, builtAt);
  let painted = 0;
  // done.js's module-level record of the document the estimator downloaded (Send reads it).
  const checkedDocument = { renderId: "" };
  const downloadAs = new AsyncFunction(
    ...DOWNLOAD.args, "TW", "freshDocuments", "paintLumpSum", "fetch", "Blob", "URL", "document",
    "setTimeout", "icon", "console", "checkedDocument", '"use strict"; ' + DOWNLOAD.body);
  const shown = [];
  const preEl = { style: { display: "" } };
  // `TW` and `state` are bound although doGenerate no longer reads them: the page has both at
  // module scope, so a regression that went back to posting `state.proposal_payload` must fail on
  // WHAT it posts, not on an unbound name the page would have had.
  const doGenerate = new AsyncFunction(
    "document", "freshDocuments", "preEl", "showPostGenerate", "alert", "TW", "state",
    '"use strict"; ' + GENERATE.body);
  return {
    log, posted, fetched, clicked, shown, preEl,
    state: () => st,
    painted: () => painted,
    checked: () => checkedDocument.renderId,
    download: (key, name, button) => downloadAs(
      key, name, button, TW, freshDocuments, () => { painted++; }, fetchStub, BlobStub, URLStub,
      documentStub, () => 0, () => "", { error() {} }, checkedDocument),
    generate: () => doGenerate(documentStub, freshDocuments, preEl,
                               (r) => shown.push(r), () => {}, TW, st),
  };
}

const button = () => ({ textContent: "Download PDF", disabled: false, innerHTML: "" });
const SAVED = { values: { total_formatted: "$41,250.00", project_name: "Niagara" },
                work_type: "epoxy", audience: "Direct" };

(async function () {
  const out = {};

  // A. THE CASE: a build kept from before an edit, and a newer saved payload.
  {
    const p = page({ state: { generate_result: OLD, generated_lump_sum: "$36,700.00",
                              proposal_payload: SAVED, project_name: "Niagara" } });
    const b = button();
    await p.download("pdf_download_url", "Niagara_proposal.pdf", b);
    out.stale = { log: p.log, fetched: p.fetched, posted: p.posted.map((x) => x.path),
                  body: p.posted.length ? p.posted[0].body : null, clicked: p.clicked,
                  kept: p.state().generate_result, stamp: p.state().generated_lump_sum,
                  painted: p.painted(), html: b.innerHTML, checked: p.checked() };
  }

  // B. A save that cannot land builds nothing.
  {
    const p = page({ flushOk: false, state: { generate_result: OLD, proposal_payload: SAVED } });
    const b = button();
    await p.download("pdf_download_url", "x.pdf", b);
    out.flushFails = { log: p.log, fetched: p.fetched, button: b.textContent };
  }

  // C. No saved payload: rebuilt from the draft's own fields, through /api/generate.
  {
    const p = page({ state: { project_name: "No Payload", work_type: "polish", audience: "GC",
                              cover_letter_enabled: true, notes_text: "one\ntwo\n" } });
    const b = button();
    await p.download("docx_download_url", "x.docx", b);
    const body = p.posted.length ? p.posted[0].body : {};
    out.noPayload = { posted: p.posted.map((x) => x.path), fetched: p.fetched, log: p.log,
                      stamp: p.state().generated_lump_sum,
                      workType: body.work_type, audience: body.audience,
                      letter: body.cover_letter_enabled, notes: body.notes,
                      valuesName: body.values && body.values.project_name };
  }

  // D. A 404 on a token minted a moment ago is a failure, not a cue to rebuild from elsewhere.
  {
    const p = page({ fetchStatus: 404, state: { generate_result: OLD, proposal_payload: SAVED } });
    const b = button();
    await p.download("pdf_download_url", "x.pdf", b);
    out.notFound = { posted: p.posted.map((x) => x.path), fetched: p.fetched,
                     button: b.textContent, checked: p.checked() };
  }

  // E. The Generate button renders the SAVED payload too.
  {
    const p = page({ state: { proposal_payload: SAVED, project_name: "Niagara" },
                     nodes: { "gen-btn": { disabled: false, textContent: "Generate Files →" } } });
    await p.generate();
    out.generate = { log: p.log, posted: p.posted.map((x) => x.path), shown: p.shown,
                     pre: p.preEl.style.display, stamp: p.state().generated_lump_sum };
  }

  // F. No draft id to ask the server about: the page's own payload goes to /api/generate.
  {
    const p = page({ draftId: null, state: { proposal_payload: SAVED } });
    await p.download("pdf_download_url", "x.pdf", button());
    out.noDraftId = { posted: p.posted.map((x) => x.path),
                      sentSaved: p.posted.length && p.posted[0].body === p.state().proposal_payload };
  }

  process.stdout.write(JSON.stringify(out));
})().catch((e) => { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
