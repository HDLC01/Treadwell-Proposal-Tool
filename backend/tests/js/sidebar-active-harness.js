"use strict";
/* Which sidebar row is lit, standing on each address. Runs the REAL frontend/auth.js.
 *
 * WHY EXECUTED. The rule is one expression inside navItem() and one inside alsoActive(), and what
 * matters is what they produce for a given location.pathname, not how they are spelled. A page under
 * /bd/ named admin.html or analytics.html is the case that tells a full-path match from an
 * ends-with match, and only running the code tells you which one you have.
 *
 * The address "/" is served portal.html's bytes, and portal.html runs js/root-path.js before
 * auth.js, which rewrites the address bar to /portal.html. So a case can ask for that guard to run
 * first, the way the page runs it, with "|root-path" after the pathname. Without it, "/" is what the
 * intake form sees when it is served at "/?new=1".
 *
 * Usage: node sidebar-active-harness.js <frontend-dir> <pathname>[|root-path] ...
 * stdout: one line of JSON, { hrefs: [every row's href], cases: [{ pathname, guarded, seen, lit }] }
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(process.argv[2]);
const read = (p) => fs.readFileSync(p, "utf8");
const AUTH_SRC = read(path.join(ROOT, "auth.js"));
const ICONS_SRC = read(path.join(ROOT, "js", "icons.js"));
const ROOT_PATH_SRC = read(path.join(ROOT, "js", "root-path.js"));

// As much of a browser as auth.js touches on the way to its sidebar markup. Spec mode appends
// nothing; these stubs exist so the file can load (its init() finds no Supabase config and stops).
function browser(pathname) {
  const el = () => ({
    id: "", innerHTML: "", textContent: "", title: "", hidden: false, className: "",
    style: { cssText: "" }, dataset: {},
    classList: { add() {}, remove() {}, toggle() {} },
    appendChild() {}, insertAdjacentHTML() {}, replaceChildren() {}, remove() {},
    addEventListener() {}, setAttribute() {}, getAttribute() { return null; },
    querySelector() { return null; }, querySelectorAll() { return []; },
  });
  const loc = { pathname: pathname, search: "", hash: "", origin: "https://example.test",
                replace() {}, assign() {} };
  const win = {
    document: {
      head: el(), body: el(), documentElement: el(), hidden: false,
      getElementById() { return null; },
      createElement() { return el(); },
      querySelector() { return null; },
      querySelectorAll() { return []; },
      addEventListener() {},
    },
    location: loc,
    // Applied the way a browser applies it, so the pathname auth.js reads afterwards is the new one.
    history: {
      replaceState(state, title, url) {
        const next = new URL(url, loc.origin);
        loc.pathname = next.pathname;
        loc.search = next.search;
        loc.hash = next.hash;
      },
    },
    localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    fetch() { return Promise.reject(new Error("harness: no network")); },
    matchMedia() { return { matches: true }; },
    getComputedStyle() { return { paddingTop: "0px" }; },
    setTimeout() {}, setInterval() {}, clearInterval() {},
    requestAnimationFrame() {},
    console, JSON, URL, URLSearchParams, Set, Map,
  };
  win.window = win;
  win.self = win;
  win.globalThis = win;
  return win;
}

function nav(markup) {
  const i = markup.indexOf('<nav class="tw-nav">');
  const j = markup.indexOf("</nav>");
  return i === -1 || j === -1 ? "" : markup.slice(i, j + 6);
}

function run(arg) {
  const parts = arg.split("|");
  const pathname = parts[0];
  const guarded = parts.indexOf("root-path") !== -1;
  const win = browser(pathname);
  vm.createContext(win);
  if (guarded) vm.runInContext(ROOT_PATH_SRC, win, { filename: "root-path.js" });
  vm.runInContext(ICONS_SRC, win, { filename: "icons.js" });
  vm.runInContext(AUTH_SRC, win, { filename: "auth.js" });
  if (!win.TWAuth) throw new Error("auth.js did not publish window.TWAuth");
  // super_admin with nothing denied: every row the sidebar can draw, Admin included.
  const markup = nav(win.TWAuth.sidebarMarkup("super_admin", []));
  const rows = Array.from(markup.matchAll(/<a class="tw-nav-item( active)?" href="([^"]*)"/g));
  return {
    pathname: pathname,
    guarded: guarded,
    seen: win.location.pathname,
    hrefs: rows.map((m) => m[2]),
    lit: rows.filter((m) => m[1]).map((m) => m[2]),
  };
}

const cases = process.argv.slice(3).map(run);
process.stdout.write(JSON.stringify({ hrefs: cases.length ? cases[0].hrefs : [], cases: cases }) + "\n");
