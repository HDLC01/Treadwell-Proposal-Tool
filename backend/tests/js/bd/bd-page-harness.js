"use strict";
/* Runs BD page scripts the way a BD page runs them (#806): in order, in one bare context, with the
 * tool's shell stood in for by what BD reads from it (TWAuth: ready, tokenReady, token, bdMe, and
 * bdFailure, which is the REAL one, lifted out of frontend/auth.js) and a fetch that answers what the
 * scenario says. Then it makes the BDApi calls the scenario lists.
 *
 * Usage: node bd-page-harness.js <frontend-dir> <scenario.json>  ->  one line of JSON
 *
 * scenario: { scripts: ["bd/js/bd-api.js", ...]       paths under frontend/, run in this order
 *             token: "..." | null                      what TWAuth.token() gives
 *             ready: true | false                       whether TWAuth.ready (and tokenReady) settle
 *             bdMe: {status, body} | null               what TWAuth.bdMe() resolves to
 *             now: "2026-11-04T09:30:00-06:00"         the clock the page reads
 *             responses: {"GET /api/bd/me": {status, body} | {status, text, type}}
 *             fetchFails: true                          every fetch rejects (no network)
 *             calls: [{fn: "get" | "post" | ..., path, body}]
 *             ids: ["wk-greeting", ...]                  elements to report
 *             search: "?id=21", pathname: "/bd/contact.html" }   the page's address (#808; default
 *                                                       "" and "/bd/") 
 * out:      { threw, calls: [{ok} | {error: {message, status, code, fields}}], fetches: [{url, method,
 *             headers, body}], els: {id: {text, html, hidden}}, globals: {name: typeof},
 *             replaced: [address, ...] }               every location.replace (a role sent home, #807)
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(process.argv[2]);
const SC = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));

// Text a browser would show for this markup: everything outside <...>. A character walk, not a
// regex, so a tag split across a replacement (<scr<b>ipt) cannot survive into the text.
function stripTags(s) {
  let out = "", inTag = false;
  for (const ch of s) {
    if (ch === "<") inTag = true;
    else if (ch === ">" && inTag) inTag = false;
    else if (!inTag) out += ch;
  }
  return out;
}

const byId = {};
function element(id) {
  const e = {
    id, hidden: false, className: "", attrs: {}, listeners: {},
    _text: "", _html: "",
    get textContent() { return e._text; },
    set textContent(v) { e._text = String(v); e._html = String(v).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); },
    get innerHTML() { return e._html; },
    set innerHTML(v) { e._html = String(v); e._text = stripTags(String(v)); },
    setAttribute(k, v) { e.attrs[k] = String(v); },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(e.attrs, k) ? e.attrs[k] : null; },
    hasAttribute(k) { return Object.prototype.hasOwnProperty.call(e.attrs, k); },
    removeAttribute(k) { delete e.attrs[k]; },
    addEventListener(t, fn) { (e.listeners[t] = e.listeners[t] || []).push(fn); },
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    querySelector() { return null; }, querySelectorAll() { return []; }, appendChild() {},
    focus() {}, contains() { return false; },
    // #809: the Admin and Analytics pages add a glyph or <option>s to an element that is there.
    insertAdjacentHTML(_where, v) { e.innerHTML = e._html + String(v); },
  };
  return e;
}
for (const id of SC.ids || []) byId[id] = element(id);

const fetches = [];
function respond(url, init) {
  const method = (init && init.method) || "GET";
  fetches.push({ url, method, headers: (init && init.headers) || {}, body: (init && init.body) || null });
  if (SC.fetchFails) return Promise.reject(new TypeError("Failed to fetch"));
  const key = method + " " + String(url).split("?")[0];
  const r = (SC.responses || {})[key] || { status: 404, body: { ok: false, error: "not_found", message: "No such route." } };
  const isJson = !("text" in r);
  const type = r.type || (isJson ? "application/json" : "text/html");
  return Promise.resolve({
    ok: r.status >= 200 && r.status < 300, status: r.status, statusText: r.statusText || "",
    headers: { get: (k) => (String(k).toLowerCase() === "content-type" ? type : null) },
    json: () => Promise.resolve(r.body),
    text: () => Promise.resolve(isJson ? JSON.stringify(r.body) : r.text),
  });
}

// TWAuth.bdFailure is auth.js's own: the one reader of a failed BD answer. It is self-contained (its
// constants are inside it), so its source is lifted by name and run here as it is.
function liftBdFailure() {
  const src = fs.readFileSync(path.join(ROOT, "auth.js"), "utf8").replace(/\r\n/g, "\n");
  const start = src.indexOf("  function bdFailure(status, body) {");
  if (start === -1) throw new Error("harness: auth.js has no bdFailure");
  const end = src.indexOf("\n  }\n", start);
  return vm.runInNewContext("(" + src.slice(start, end + 4).trim() + ")");
}

const never = new Promise(() => {});
const replaced = [];
const ctx = {
  console,
  setTimeout, clearTimeout,
  URLSearchParams, URL, Intl, JSON, Math, Promise,
  location: { pathname: SC.pathname || "/bd/", search: SC.search || "", hostname: "proposals.example.com", origin: "https://proposals.example.com",
              replace: (to) => { replaced.push(String(to)); } },
  document: {
    title: "", documentElement: element("html"), body: element("body"),
    getElementById: (id) => byId[id] || null,
    querySelector: () => null, querySelectorAll: () => [],
    createElement: () => element(""),
    addEventListener() {},
  },
  fetch: respond,
  TWAuth: {
    ready: SC.ready === false ? never : Promise.resolve({}),
    tokenReady: SC.ready === false ? never : Promise.resolve(SC.token || null),
    token: () => SC.token || null,
    bdMe: () => Promise.resolve(SC.bdMe || { status: 0, body: null }),
    bdFailure: liftBdFailure(),
  },
};
ctx.window = ctx;
if (SC.now) {
  const RealDate = Date;
  const fixed = RealDate.parse(SC.now);
  class FixedDate extends RealDate {
    constructor(...a) { if (a.length) super(...a); else super(fixed); }
    static now() { return fixed; }
  }
  ctx.Date = FixedDate;
}
vm.createContext(ctx);

let threw = null;
for (const rel of SC.scripts || []) {
  try {
    vm.runInContext(fs.readFileSync(path.join(ROOT, rel), "utf8"), ctx, { filename: rel });
  } catch (e) {
    threw = rel + ": " + String(e && e.stack || e);
    break;
  }
}

function settle() { return new Promise((r) => setTimeout(r, 20)); }

(async function main() {
  const calls = [];
  for (const c of SC.calls || []) {
    try {
      const api = ctx.BDApi;
      const p = c.fn === "get" || c.fn === "del" ? api[c.fn](c.path) : api[c.fn](c.path, c.body);
      calls.push({ ok: await p });
    } catch (e) {
      calls.push({ error: { message: e && e.message, status: e && e.status, code: e && e.code, fields: (e && e.fields) || null } });
    }
  }
  await settle();
  const els = {};
  for (const id of Object.keys(byId)) els[id] = { text: byId[id].textContent, html: byId[id].innerHTML, hidden: !!byId[id].hidden };
  const globals = {};
  for (const g of ["BDApi", "BD", "BDCore", "TWIcon", "BD_MOCK", "BDMock", "BDAuth"]) globals[g] = typeof ctx[g];
  process.stdout.write(JSON.stringify({ threw, calls, fetches, els, globals, replaced }) + "\n");
})();
