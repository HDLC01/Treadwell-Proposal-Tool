"use strict";
/* Sign-in return (#806): the page a signed-out person asked for, remembered in the browser tab and
 * returned to after sign-in. Runs the REAL frontend/auth.js init(), or frontend/bd/js/login-return.js.
 *
 * Usage: node sign-in-return-harness.js <frontend-dir> <scenario.json>  ->  one line of JSON
 *
 * scenario: { script: "auth" | "bd-login", pathname, search, session: bool, stored: string | null,
 *             signIn: bool (call TWAuth.signInWithGoogle once the page has settled) }
 * out:      { replaced: [every location.replace target], stored: the tab's return value afterwards,
 *             redirectTo: what Supabase was told, painted: whether a sidebar went up }
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(process.argv[2]);
const SC = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const read = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");
const KEY = "tw_return_to";

function storage(initial) {
  const s = Object.assign({}, initial || {});
  return {
    data: s,
    getItem(k) { return Object.prototype.hasOwnProperty.call(s, k) ? s[k] : null; },
    setItem(k, v) { s[k] = String(v); },
    removeItem(k) { delete s[k]; },
  };
}

function element(id) {
  const e = {
    id: id || "", innerHTML: "", textContent: "", title: "", hidden: false, className: "",
    style: { cssText: "", paddingTop: "", display: "" }, dataset: {}, attrs: {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    appendChild() {}, insertAdjacentHTML() {}, replaceChildren() {}, remove() {},
    addEventListener() {}, setAttribute() {}, getAttribute() { return null; }, removeAttribute() {},
    focus() {}, querySelector() { return null; }, querySelectorAll() { return []; },
  };
  return e;
}

const replaced = [];
let redirectTo = null;
let painted = false;
const session = storage(SC.stored == null ? {} : { [KEY]: SC.stored });

const win = {
  location: { pathname: SC.pathname, search: SC.search || "", hash: "", origin: "https://example.test",
              replace(u) { replaced.push(String(u)); }, assign(u) { replaced.push(String(u)); } },
  localStorage: storage({}),
  sessionStorage: session,
  matchMedia() { return { matches: true, addEventListener() {} }; },
  getComputedStyle() { return { paddingTop: "0px" }; },
  setTimeout() {}, setInterval() {}, clearInterval() {}, requestAnimationFrame() {},
  console, JSON, URL, URLSearchParams, Set, Map, Array, Object, Promise, Error, String,
};
const body = element("body");
body.appendChild = (e) => { if (e && e.id === "tw-sidebar") painted = true; };
win.document = {
  head: element("head"), body: body, documentElement: element("html"), hidden: false, title: "",
  getElementById(id) { return id === "tw-sidebar" || id === "tw-sidebar-css" || id === "google-signin" ? null : element(id); },
  createElement() { return element(""); },
  querySelector() { return null; }, querySelectorAll() { return []; }, addEventListener() {},
};
win.fetch = (url) => {
  const u = String(url);
  if (u.indexOf("/api/public-config") !== -1) {
    return Promise.resolve({ ok: true, status: 200, json: async () => (
      { supabase_url: "https://sb.test", supabase_anon_key: "anon", allowed_domain: "wetreadwell.com" }) });
  }
  return Promise.resolve({ ok: true, status: 200, json: async () => (
    { ok: true, email: "marisol@wetreadwell.com", name: "Marisol Quint", role: "user", status: "active",
      nav_denied: [], nav_denied_pages: {}, grants: [], nav_off: [] }) });
};
win.supabase = { createClient: () => ({ auth: {
  onAuthStateChange() {},
  getSession: async () => ({ data: { session: SC.session ? { access_token: "token",
    user: { email: "marisol@wetreadwell.com", user_metadata: { full_name: "Marisol Quint" } } } : null } }),
  signOut: async () => {},
  signInWithOAuth: async (opts) => { redirectTo = opts && opts.options ? opts.options.redirectTo : null; },
} }) };
win.window = win; win.self = win; win.globalThis = win;

const settle = () => new Promise((res) => setImmediate(res));

async function main() {
  vm.createContext(win);
  if (SC.script === "bd-login") {
    vm.runInContext(read(path.join(ROOT, "bd", "js", "login-return.js")), win, { filename: "login-return.js" });
  } else {
    vm.runInContext(read(path.join(ROOT, "js", "icons.js")), win, { filename: "icons.js" });
    vm.runInContext(read(path.join(ROOT, "auth.js")), win, { filename: "auth.js" });
    for (let i = 0; i < 8; i++) await settle();
    if (SC.signIn) { await win.TWAuth.signInWithGoogle(); for (let i = 0; i < 3; i++) await settle(); }
  }
  process.stdout.write(JSON.stringify({
    replaced: replaced, stored: session.getItem(KEY), redirectTo: redirectTo, painted: painted,
  }) + "\n");
}
main().catch((e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
