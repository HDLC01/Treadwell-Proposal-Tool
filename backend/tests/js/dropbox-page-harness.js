"use strict";
/* Drive step 5's WHOLE To-Dropbox section — the destination select, the folder
 * chooser, and the button's click handler — out of frontend/js/dropbox.js.
 *
 * WHY A SECOND HARNESS. dropbox-picker-harness.js lifts the chooser's pure
 * functions and cannot reach the click handler, which needs the page: the select,
 * TW, fetch. But the click handler is where "nothing is filed until a folder is
 * chosen" is actually enforced, and the hole found on 2026-08-20 lived exactly in
 * the seam between the two halves:
 *
 *   file once (uploaded = true) → change the destination (choice = null, and
 *   dbxSyncGo refused to repaint the button while uploaded) → press the still-live
 *   green button → POST with folder_path:"" → a brand-new folder in the new
 *   destination, which is the duplicate the picker exists to prevent.
 *
 * Every step of that is behaviour: a flag set in one function, cleared in another,
 * read by a third. So this runs the real IIFE against a DOM stub and reports what
 * was POSTed. What matters in the JSON below is `posts` — one entry per
 * /api/to-dropbox request the page actually made.
 *
 * Usage: node dropbox-page-harness.js <frontend-dir>   →   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(process.argv[2]);
const SRC = fs.readFileSync(path.join(ROOT, "js", "dropbox.js"), "utf8")
  .replace(/\r\n/g, "\n");

// ── DOM stub ────────────────────────────────────────────────────────────────
// Rows are built as an innerHTML string and then queried, so the radios the
// change handler binds are materialised from the page's OWN output (same trick as
// dropbox-picker-harness.js — a hand-built fixture could agree with the handler
// and disagree with what renders).
const UNESC = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'" };
const unesc = (s) => String(s).replace(/&(?:amp|lt|gt|quot|#39);/g, (m) => UNESC[m]);

function parseRadios(html) {
  const out = [];
  const re = /<input([^>]*)>/g;
  let m;
  while ((m = re.exec(html))) {
    const attrs = m[1];
    const cls = (/class="([^"]*)"/.exec(attrs) || [, ""])[1];
    if (cls.indexOf("dbx-radio") < 0) continue;
    out.push({
      value: unesc((/value="([^"]*)"/.exec(attrs) || [, ""])[1]),
      checked: /\schecked(?=[\s>])|\schecked$/.test(attrs + " "),
      isNew: /data-new="1"/.test(attrs),
      listeners: {},
      addEventListener(k, f) { (this.listeners[k] = this.listeners[k] || []).push(f); },
    });
  }
  out.forEach((n) => {
    n.check = function () {
      out.forEach((o) => { o.checked = (o === n); });
      (n.listeners.change || []).forEach((f) => f({ target: n }));
    };
  });
  return out;
}

function el(extra) {
  return Object.assign({
    style: {}, textContent: "", disabled: false,
    classList: { add() {}, remove() {} },
    listeners: {},
    addEventListener(k, f) { (this.listeners[k] = this.listeners[k] || []).push(f); },
    /** Like a browser: a disabled control does not dispatch a click at all.
     *  Returns whether the listeners ran. */
    fire(k, ev) {
      if (this.disabled) return false;
      (this.listeners[k] || []).forEach((f) => f(ev || {}));
      return true;
    },
    /** The same dispatch with the disabled flag IGNORED — the belt to the DOM's
     *  braces. It proves the handler's own guard, not the button's paint. */
    force(k, ev) {
      (this.listeners[k] || []).forEach((f) => f(ev || {}));
      return true;
    },
  }, extra || {});
}

function foldersNode() {
  let html = "";
  let cache = null;
  return {
    get innerHTML() { return html; },
    set innerHTML(v) { html = String(v); cache = null; },
    _radios() { if (!cache) cache = parseRadios(html); return cache; },
    querySelectorAll(sel) { return sel === ".dbx-radio" ? this._radios() : []; },
  };
}

/** A <select> honest enough for loadFolders(): it rewrites innerHTML from the
 *  server's list and then looks an option up to restore the previous value. */
function selectNode() {
  const node = el({
    value: "",
    options: [],
    selectedIndex: -1,
    querySelector(sel) {
      const m = /option\[value="([^"]*)"\]/.exec(sel || "");
      const want = m ? m[1] : null;
      return this.options.filter((o) => o.value === want)[0] || null;
    },
  });
  Object.defineProperty(node, "innerHTML", {
    set(v) {
      const opts = [];
      const re = /<option value="([^"]*)"[^>]*>([\s\S]*?)<\/option>/g;
      let m;
      while ((m = re.exec(String(v)))) opts.push({ value: unesc(m[1]), text: unesc(m[2]) });
      this.options = opts;
      this._html = String(v);
    },
    get() { return this._html || ""; },
  });
  // Kept in step with `value` the way a browser does, because destLabel() reads
  // options[selectedIndex].text for the note.
  const raw = { value: "" };
  Object.defineProperty(node, "value", {
    get() { return raw.value; },
    set(v) {
      raw.value = String(v == null ? "" : v);
      this.selectedIndex = this.options.findIndex((o) => o.value === raw.value);
    },
  });
  return node;
}

// ── the run ─────────────────────────────────────────────────────────────────
const DESTINATIONS = [
  { key: "gyp", label: "Gyp Estimates" },
  { key: "commercial", label: "Commercial Sales Estimates" },
];
const GYP = "/2023 Treadwell Team Folder/Estimating/$Gyp Estimates";
const COMM = "/2023 Treadwell Team Folder/Estimating/$Commercial Sales Estimates";
const F = (base, name, score) => ({ name, parent: "", score, path: base + "/" + name });

// Gyp: a runaway winner, so one row arrives armed and the first filing is a
// normal, successful send.
const GYP_FOLDERS = [F(GYP, "26.08.14 Fuel House", 0.92),
                     F(GYP, "26.02.03 Traband Warehouse", 0.31)];
// Commercial: 0.90 against 0.85 — contested, so NOTHING is armed. This is the
// list that has to leave the button dead after the destination change.
const COMM_FOLDERS = [F(COMM, "26.06.12 Trabon Office Polish", 0.9),
                      F(COMM, "26.08.02 Trabon Group HQ", 0.85)];

const tick = () => new Promise((r) => setImmediate(r));
const drain = async () => { for (let i = 0; i < 12; i++) await tick(); };

function build(opts) {
  const o = opts || {};
  const nodes = {
    "dbx-main": el(), "dbx-empty": el(), "dbx-project": el(),
    "dbx-dest": selectNode(), "dbx-owner": selectNode(), "dbx-owner-field": el(),
    "dbx-go": el({ disabled: true, textContent: "Choose a folder above" }),
    "dbx-result": el(), "dbx-folder-field": el(), "dbx-folders": foldersNode(),
    "dbx-folder-note": el(), "dbx-search": el({ value: "" }),
  };

  const posts = [];
  const folderResponses = o.folderResponses || {};
  const fetchStub = async (url, init) => {
    const u = String(url);
    if (u.indexOf("/api/dropbox/folders") >= 0) {
      return { ok: true, status: 200,
               json: async () => ({ ok: true, destinations: DESTINATIONS,
                                    commercial_key: "commercial", owners: [] }) };
    }
    if (u.indexOf("/api/dropbox/project-folders") >= 0) {
      const dest = (/destination=([^&]*)/.exec(u) || [, ""])[1];
      const body = folderResponses[dest] || { ok: true, folders: [],
                                              suggested_new_name: "26.08.20 Fuel House" };
      return { ok: true, status: 200, json: async () => body };
    }
    if (u.indexOf("/api/to-dropbox") >= 0) {
      const body = JSON.parse(init.body);
      posts.push(body);
      return { ok: true, status: 200,
               json: async () => ({ ok: true, folder_path: body.folder_path || GYP + "/new",
                                    folder_url: "https://dropbox/x", xlsx_url: "u",
                                    docx_url: "u", pdf_url: "u",
                                    existing: !!body.folder_path,
                                    written_paths: ["p"], renamed: [] }) };
    }
    throw new Error("unexpected fetch: " + u);
  };

  const stored = [];
  const TW = {
    getState: () => ({ project_name: "Fuel House", work_type: "gyp",
                       cell_values: { E20: 4200 },
                       dropbox_result: o.prevResult || undefined }),
    setState: (patch) => stored.push(patch),
    authHeaders: () => ({}),
    getDraftId: () => "d1",
    resolveApiBase: () => "",
  };

  const run = new Function("document", "TW", "fetch", "alert", "CSS", SRC);
  run({ getElementById: (id) => nodes[id] || null }, TW, fetchStub,
      () => { throw new Error("alert() — no draft id"); },
      { escape: (s) => String(s) });

  return {
    nodes, posts, stored,
    snap: () => {
      const radios = nodes["dbx-folders"].querySelectorAll(".dbx-radio");
      return {
        goDisabled: nodes["dbx-go"].disabled,
        goLabel: nodes["dbx-go"].textContent,
        note: nodes["dbx-folder-note"].textContent,
        checked: radios.filter((r) => r.checked).map((r) => r.value),
        radioValues: radios.map((r) => r.value),
      };
    },
  };
}

async function main() {
  const out = {};

  // ═══ the sequence that reached the hole ═══════════════════════════════════
  const s = build({ folderResponses: {
    gyp: { ok: true, folders: GYP_FOLDERS, suggested_new_name: "26.08.20 Fuel House" },
    commercial: { ok: true, folders: COMM_FOLDERS, suggested_new_name: "26.08.20 Fuel House" },
  } });
  await drain();                                   // loadFolders()
  out.destOptions = s.nodes["dbx-dest"].options.map((o) => o.value);

  // 1 — the estimator picks Gyp; the runaway winner arrives armed.
  s.nodes["dbx-dest"].value = "gyp";
  s.nodes["dbx-dest"].fire("change");
  await drain();
  out.armed = s.snap();

  // 2 — and files. This is the successful send that sets `uploaded`.
  out.firstClickDispatched = s.nodes["dbx-go"].fire("click");
  await drain();
  out.afterFiling = s.snap();
  out.postsAfterFirst = s.posts.length;
  out.firstBody = s.posts[0] || null;
  out.mirrored = s.stored[s.stored.length - 1] || null;

  // 3 — the estimator switches destination. The choice is cleared and the request
  // for the new list goes out; the button must go dead in the same breath.
  s.nodes["dbx-dest"].value = "commercial";
  s.nodes["dbx-dest"].fire("change");
  out.whileLoading = s.snap();
  out.clickWhileLoadingDispatched = s.nodes["dbx-go"].fire("click");
  await drain();

  // 4 — the contested list lands: two near-identical folders, nothing armed.
  out.afterDestChange = s.snap();
  out.clickAfterDestChangeDispatched = s.nodes["dbx-go"].fire("click");
  await drain();
  // ...and the same click with the DOM's disabled flag ignored, which is what
  // asserts the handler's own guard rather than the button's paint.
  s.nodes["dbx-go"].force("click");
  await drain();
  out.postsTotal = s.posts.length;
  out.postBodies = s.posts.slice();       // a copy: step 5 below posts again

  // 5 — picking one of the two arms it again, so the guard is a guard and not a
  // wall: step 5 must still be usable after a destination change.
  const radios = s.nodes["dbx-folders"].querySelectorAll(".dbx-radio");
  radios[1].check();
  out.afterPickingAgain = s.snap();
  s.nodes["dbx-go"].fire("click");
  await drain();
  out.postsAfterRepick = s.posts.length;
  out.lastBody = s.posts[s.posts.length - 1] || null;

  // ═══ a re-upload into the SAME folder still works ════════════════════════
  const r = build({ folderResponses: {
    gyp: { ok: true, folders: GYP_FOLDERS, suggested_new_name: "26.08.20 Fuel House" },
  } });
  await drain();
  r.nodes["dbx-dest"].value = "gyp";
  r.nodes["dbx-dest"].fire("change");
  await drain();
  r.nodes["dbx-go"].fire("click");
  await drain();
  out.reuploadEnabled = !r.nodes["dbx-go"].disabled;
  r.nodes["dbx-go"].fire("click");                 // the green "click to re-upload"
  await drain();
  out.reuploadPosts = r.posts.length;
  out.reuploadPaths = r.posts.map((p) => p.folder_path);

  // ═══ a revisit: filed before, folder list not back yet ═══════════════════
  // showUploaded() runs from the draft, before any candidate exists. The green
  // button may not be live over a choice of null.
  const v = build({ prevResult: { destination: "gyp", folder_path: GYP + "/26.08.14 Fuel House",
                                  folder_url: "https://dropbox/x", written_paths: ["p"] },
                    folderResponses: {
                      gyp: { ok: true, folders: GYP_FOLDERS,
                             suggested_new_name: "26.08.20 Fuel House" } } });
  out.revisitBeforeList = v.snap();
  await drain();
  out.revisitAfterList = v.snap();
  out.revisitPosts = v.posts.length;

  console.log(JSON.stringify(out));
}

main().catch((e) => { console.error(e && e.stack || String(e)); process.exit(1); });
