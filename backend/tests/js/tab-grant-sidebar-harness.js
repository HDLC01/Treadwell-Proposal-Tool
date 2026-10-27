"use strict";
/* A tab granted to one person on the Special permissions card shows in THEIR sidebar and its page
 * opens, while their role stays denied it.
 *
 * frontend/auth.js runs its real init() in a bare VM context (the same stubs as
 * nav-permissions-harness.js) with /api/me answering the JSON the test passes in, which the test
 * takes from the REAL /api/me route. So the claim checked is end to end: server subtraction ->
 * auth.js's menu and page refusal.
 *
 * Usage: node tab-grant-sidebar-harness.js <frontend-dir> <me.json> <pathname>  ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(process.argv[2]);
const ME = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const PATHNAME = process.argv[4] || "/portal.html";
const read = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");
const AUTH_SRC = read(path.join(ROOT, "auth.js"));
const ICONS_SRC = read(path.join(ROOT, "js", "icons.js"));

function browser(pathname) {
  const el = () => {
    const e = {
      id: "", innerHTML: "", textContent: "", title: "", hidden: false, className: "",
      style: { cssText: "", paddingTop: "" }, dataset: {}, kids: [],
      classList: { add() {}, remove() {}, toggle() {} },
      appendChild(c) { e.kids.push(c); }, insertAdjacentHTML() {}, replaceChildren() {},
      remove() {}, addEventListener() {}, setAttribute() {}, getAttribute() { return null; },
      querySelector() { return null; }, querySelectorAll() { return []; },
    };
    return e;
  };
  const win = {
    document: {
      head: el(), body: el(), documentElement: el(), hidden: false, title: "",
      getElementById() { return null; }, createElement() { return el(); },
      querySelector() { return null; }, querySelectorAll() { return []; }, addEventListener() {},
    },
    location: { pathname: pathname, search: "", origin: "https://example.test",
                replace() {}, assign() {} },
    localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    fetch() { return Promise.reject(new Error("harness: no network")); },
    matchMedia() { return { matches: true }; },
    getComputedStyle() { return { paddingTop: "0px" }; },
    setTimeout() {}, setInterval() {}, clearInterval() {}, requestAnimationFrame() {},
    console, JSON, URLSearchParams, Set, Map, Array, Object, Promise, Error,
  };
  win.window = win; win.self = win; win.globalThis = win;
  return win;
}

function hrefs(markup) {
  const i = markup.indexOf('<nav class="tw-nav">');
  const j = markup.indexOf("</nav>");
  const nav = i === -1 || j === -1 ? "" : markup.slice(i, j + 6);
  return Array.from(nav.matchAll(/<a class="tw-nav-item[^"]*" href="([^"]*)"/g)).map((m) => m[1]);
}

async function main() {
  const win = browser(PATHNAME);
  const appended = [];
  win.document.body.appendChild = (e) => { appended.push(e); };
  win.document.getElementById = (id) => (id === "tw-sidebar" || id === "tw-sidebar-css" ? null : {
    addEventListener() {}, hidden: true, innerHTML: "", textContent: "",
  });
  win.fetch = (url) => Promise.resolve({
    json: async () => (String(url).indexOf("/api/public-config") !== -1
      ? { supabase_url: "https://sb.test", supabase_anon_key: "anon", allowed_domain: "wetreadwell.com" }
      : ME),
  });
  win.supabase = { createClient: () => ({ auth: {
    onAuthStateChange() {},
    getSession: async () => ({ data: { session: { access_token: "token",
      user: { email: ME.email, user_metadata: { full_name: "Marisol" } } } } }),
    signOut: async () => {},
  } }) };
  vm.createContext(win);
  vm.runInContext(ICONS_SRC, win, { filename: "icons.js" });
  vm.runInContext(AUTH_SRC, win, { filename: "auth.js" });
  const raced = await Promise.race([
    win.TWAuth.ready.then(() => "settled", () => "rejected"),
    new Promise((res) => setTimeout(() => res("pending"), 80)),
  ]);
  const sidebars = appended.filter((e) => e.id === "tw-sidebar");
  const cards = appended.filter((e) => String(e.className || "").indexOf("tw-refuse") !== -1);
  process.stdout.write(JSON.stringify({
    ready: raced, refusals: cards.length,
    entries: sidebars.length ? hrefs(sidebars[0].innerHTML) : [],
  }));
}
main().catch((e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
