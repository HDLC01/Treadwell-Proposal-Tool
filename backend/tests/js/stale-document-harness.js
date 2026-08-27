"use strict";
/* Execute the Files page's PRE-SEND gate: the check that refuses a send whose PDF is older
 * than the pricing, and the panel that tells the estimator so.
 *
 * WHY EXECUTED. The whole class of bug this guards against was invisible to source-text
 * assertions: on 2026-08-12 a used-but-never-imported constant took the Active Projects board
 * down with every grep-style test green. A gate is worth nothing unless the verdict it reaches
 * on a real draft blob is the right one, and the panel is worth nothing unless the numbers it
 * paints are the ones the estimator has to act on.
 *
 * Usage: node stale-document-harness.js <frontend-dir>   ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = process.argv[2];
const SRC = fs.readFileSync(path.join(ROOT, "js", "done.js"), "utf8");
const out = {};

// ── lift the real functions out of done.js ───────────────────────────────────
// Injected by CONCATENATION, never into a template literal: done.js is full of backticks and a
// template-literal harness terminates on the first one.
function grab(sig) {
  const re = new RegExp("function " + sig + " \\{[\\s\\S]*?\\n  \\}");
  const m = re.exec(SRC);
  if (!m) throw new Error("function " + sig + " is gone from done.js - rewrite this harness");
  return m[0];
}

const LIFTED = [grab("localPublishDigest\\(s\\)"),
                grab("docDriftRows\\(d\\)"),
                grab("showStaleDoc\\(rows, mode\\)")].join("\n");

// ── the smallest DOM the panel touches ───────────────────────────────────────
function makeEl(id) {
  return {
    id, hidden: true, className: "", scrolled: false, focused: false,
    _text: "", children: [],
    set textContent(v) { this._text = String(v); this.children = []; },
    get textContent() { return this._text; },
    appendChild(c) { this.children.push(c); },
    scrollIntoView() { this.scrolled = true; },
    focus() { this.focused = true; },
    // What a person would actually read out of the rendered block.
    read() { return this.children.map((c) => c.textContent).join(" | "); },
  };
}

function load() {
  const nodes = { "stale-doc": makeEl("stale-doc"),
                  "stale-doc-lede": makeEl("stale-doc-lede"),
                  "stale-doc-rows": makeEl("stale-doc-rows") };
  const doc = {
    getElementById: (id) => nodes[id] || null,
    createElement: () => makeEl(""),
  };
  const TW = { fmtUsd: (n) => "$" + Number(n).toLocaleString("en-US") };
  const fns = new Function("document", "window", "TW",
    LIFTED + "; return { localPublishDigest, docDriftRows, showStaleDoc };")(
      doc, { TW: TW }, TW);
  return Object.assign({ nodes: nodes }, fns);
}

// ── the real 2026-08-13 / 2026-08-26 shapes ──────────────────────────────────
// The pricing was revised on the page. `proposal_payload` is the frozen document half, written
// only by the Proposal step's Continue, so it still carries the arrangement from before.
const DOC_ROOMS = [{ name: "Polish", is_base: true, bid: { total: 13265 } },
                   { name: "Epoxy", is_base: false, bid: { total: 18670 }, show: true }];
const DRIFTED = {
  proposal_lump_sum: 18670,
  rooms: [{ name: "Epoxy", is_base: true, bid: { total: 18670 } },
          { name: "Polish", is_base: false, bid: { total: 13265 }, show: true }],
  proposal_payload: { rooms: DOC_ROOMS,
                      values: { proposal_lump_sum: 13265, rooms: DOC_ROOMS } },
};
const AGREED = (() => {
  const fixed = [{ name: "Epoxy", is_base: true, bid: { total: 18670 } },
                 { name: "Polish", is_base: false, bid: { total: 13265 }, show: true }];
  return { proposal_lump_sum: 18670, rooms: fixed,
           proposal_payload: { rooms: fixed,
                               values: { proposal_lump_sum: 18670, rooms: fixed } } };
})();

// ── the verdict, on real blobs ───────────────────────────────────────────────
out.verdict = (() => {
  const h = load();
  const rows = (s) => h.docDriftRows(h.localPublishDigest(s));
  const flat = (s) => rows(s).map((r) => r.k + ":" + r.pdf + ">" + r.now);
  return {
    // The report: revised to Epoxy at $18,670, the document still Polish at $13,265.
    drifted: rows(DRIFTED),
    driftedSay: rows(DRIFTED).map((r) => r.say).join(" and "),
    // A project whose halves agree must send with no interruption at all.
    agreed: flat(AGREED),
    // Never been through the Proposal step: nothing exists to be stale, and a first send
    // must not be blocked by a document that does not exist yet.
    noPayload: flat({ proposal_lump_sum: 18670, rooms: AGREED.rooms }),
    // Base-only, the most common shape this tool produces: no base ROOM in either half.
    baseOnly: flat({ proposal_lump_sum: 18670, rooms: [],
                     proposal_payload: { values: { proposal_lump_sum: 18670 } } }),
    // An option the estimator deliberately hid reaches neither surface, so both halves must
    // count it the same way or every send carrying one is refused.
    hiddenOption: flat({
      proposal_lump_sum: 18670,
      rooms: [{ name: "Epoxy", is_base: true }, { name: "Seal", show: false }],
      proposal_payload: {
        rooms: [{ name: "Epoxy", is_base: true, bid: { total: 18670 } },
                { name: "Seal", show: false, bid: { total: 4000 } }],
        values: { proposal_lump_sum: 18670 } },
    }),
    // The page has no lump sum of its own. That is not evidence the document is wrong, and a
    // refusal here would read "a price of $18,670, not $—".
    pageLostItsPrice: flat({ rooms: [{ name: "Epoxy", is_base: true }],
                             proposal_payload: { values: { proposal_lump_sum: 18670 } } }),
    // Floating point must not manufacture a refusal.
    subCent: flat({ proposal_lump_sum: 18670.004,
                    rooms: [{ name: "Epoxy", is_base: true }],
                    proposal_payload: { values: { proposal_lump_sum: 18670 } } }),
    // THE ECHO TRAP. `proposal_payload.values.rooms` is a spread of the page state that
    // travels beside the real field; the renderer reads `proposal_payload.rooms`. A digest
    // that followed the echo would clear a send whose PDF prints the old base bid.
    echoTrap: flat({
      proposal_lump_sum: 18670,
      rooms: [{ name: "Epoxy", is_base: true, bid: { total: 18670 } }],
      proposal_payload: {
        rooms: [{ name: "Polish", is_base: true, bid: { total: 13265 } }],
        values: { proposal_lump_sum: 18670,
                  rooms: [{ name: "Epoxy", is_base: true, bid: { total: 18670 } }] } },
    }),
    // A blob a browser wrote. None of these may throw: an exception here would take out the
    // Send button entirely and the estimator would have no way to send anything at all.
    junk: [null, undefined, 5, "nope", {}, { rooms: "not a list" }, { rooms: [null, 7] },
           { proposal_payload: "nope" }, { proposal_payload: {} },
           { proposal_payload: { values: 5 } },
           { proposal_payload: { rooms: [{ is_base: true, bid: "not a dict" }],
                                 values: {} } }]
      .map((b) => { try { return flat(b).length; } catch (e) { return "THREW: " + e.message; } }),
  };
})();

// ── the mirror ───────────────────────────────────────────────────────────────
// localPublishDigest is a copy of the server's _publish_digest, and a copy that disagrees with
// the original is worse than no copy: it would clear a send the server refuses (a dead Send
// button with no explanation) or refuse one the server would have taken (a proposal that cannot
// be sent at all). Each blob goes out WITH the digest so the python side can feed the identical
// dict to main._publish_digest and compare field for field.
out.mirror = (() => {
  const h = load();
  const blobs = {
    drifted: DRIFTED,
    agreed: AGREED,
    noPayload: { proposal_lump_sum: 18670, rooms: AGREED.rooms },
    baseOnly: { proposal_lump_sum: 18670, rooms: [],
                proposal_payload: { values: { proposal_lump_sum: 18670 } } },
    // The case that separates "count what a customer can pick" from "count every option".
    hiddenOption: {
      proposal_lump_sum: 18670,
      rooms: [{ name: "Epoxy", is_base: true, bid: { total: 18670 } },
              { name: "Seal", show: false, bid: { total: 4000 } },
              { name: "Cove", bid: { total: 900 } }],
      proposal_payload: {
        rooms: [{ name: "Epoxy", is_base: true, bid: { total: 18670 } },
                { name: "Seal", show: false, bid: { total: 4000 } }],
        values: { proposal_lump_sum: 18670 } },
    },
    emptyDraft: {},
    junkRooms: { rooms: "not a list", proposal_payload: { values: { proposal_lump_sum: 1 } } },
    junkPayload: { rooms: [{ name: "Epoxy", is_base: true }], proposal_payload: "nope" },
    payloadNoValues: { rooms: [{ name: "Epoxy", is_base: true }],
                       proposal_payload: { rooms: [{ name: "Polish", is_base: true }] } },
  };
  return Object.keys(blobs).map((name) => ({
    name: name, blob: blobs[name], digest: h.localPublishDigest(blobs[name]) }));
})();

// ── the panel ────────────────────────────────────────────────────────────────
out.panel = (() => {
  const h = load();
  const rows = h.docDriftRows(h.localPublishDigest(DRIFTED));
  const box = h.nodes["stale-doc"], lede = h.nodes["stale-doc-lede"];

  h.showStaleDoc(rows, "blocked");
  const blocked = { hidden: box.hidden, lede: lede.textContent,
                    table: h.nodes["stale-doc-rows"].read(), scrolled: box.scrolled };

  h.showStaleDoc(rows, "mount");
  const mount = { hidden: box.hidden, lede: lede.textContent };

  h.showStaleDoc(rows, "sent");
  const sent = { hidden: box.hidden, lede: lede.textContent };

  // No rows means no problem, and the panel must take itself away: a stop sign left standing
  // after the thing it stopped is fixed is a stop sign nobody reads next time.
  h.showStaleDoc([], "mount");
  const cleared = { hidden: box.hidden };

  // A base bid's name is a worksheet label the estimator typed. It has to arrive as text.
  const h2 = load();
  h2.showStaleDoc(h2.docDriftRows(h2.localPublishDigest({
    proposal_lump_sum: 1, rooms: [{ name: "<img src=x>", is_base: true }],
    proposal_payload: { rooms: [{ name: "<b>Polish</b>", is_base: true, bid: { total: 1 } }],
                        values: { proposal_lump_sum: 1 } },
  })), "blocked");

  return { blocked, mount, sent, cleared,
           rawName: h2.nodes["stale-doc-rows"].read(),
           usesInnerHtml: /innerHTML/.test(grab("showStaleDoc\\(rows, mode\\)")) };
})();

// ── the wiring: where the gate sits in the send handler ──────────────────────
// Source ORDER, deliberately: the verdict above is executed, but "no request went out" is a
// claim about position in a handler that needs the whole page to run. The three indices below
// are what make the executed verdict matter.
out.wiring = (() => {
  const iFlush = SRC.indexOf("TW.flushState()");
  // By its own line, not by the shared expression: the same call is made on mount, EARLIER in
  // the file, and matching that one would report the ordering of the wrong check.
  const iGate = SRC.indexOf("const stale = docDriftRows(localPublishDigest(TW.getState()))");
  const iPublish = SRC.indexOf("/api/portal/publish");
  const between = (iGate > 0 && iPublish > iGate) ? SRC.slice(iGate, iPublish) : "";
  return {
    gateAfterFlush: iFlush > 0 && iGate > iFlush,
    gateBeforePublish: iGate > 0 && iPublish > iGate,
    // The refusal has to LEAVE the handler. Showing the panel and falling through would send
    // the stale document with a warning painted next to it.
    gateReturns: /\n\s*return;/.test(between),
    // And it has to hand the button back, or a blocked send leaves a dead "Sending..." button
    // and the estimator reloads the page to escape it.
    gateRestoresButton: /portalBtn\.disabled = false/.test(between),
    // Checked on mount too, so the news does not arrive at the last click.
    checkedOnMount: /showStaleDoc\(docDriftRows\(localPublishDigest\(TW\.getState\(\)\)\)/.test(SRC),
    // The post-send warning is NOT replaced by the gate. Both exist: the gate cannot see drift
    // that arrives from another tab between the flush and the write.
    keepsPostSendWarning: /function publishDrift/.test(SRC)
      && /publishDrift\(j\.sent_snapshot\)/.test(SRC),
    fixButtonGoesToTheProposalStep:
      /stale-doc-fix[\s\S]{0,1200}?proposal-review\.html/.test(SRC),
  };
})();

console.log(JSON.stringify(out));
