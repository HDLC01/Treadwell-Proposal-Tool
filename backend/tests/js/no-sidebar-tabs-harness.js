"use strict";
/* A tab that is GATED but has NO SIDEBAR ROW, executed: Info Sheet after the 2026-08-20 move.
 *
 * WHY A SECOND HARNESS RATHER THAN A CASE IN nav-permissions-harness.js. That one declares one
 * policy (POLICY) which the whole file's assertions are written against, and it deliberately denies
 * two tabs that DO have sidebar rows — its subject is what a policy does to the menu. The subject
 * here is the opposite: a tab with nothing in the menu to take away. Denying it inside that policy
 * would change the numbers every test in test_nav_permissions_ui.py is written against.
 *
 * WHAT ONLY EXECUTION CAN SHOW. auth.js has no navItem() call for this tab, so navMatrix appends its
 * row from a declared list and reads the ticks straight off the deny map instead of off a render.
 * That is the one place in the file where a role's tick is NOT derived from what was rendered, and
 * the mutation that matters — a row that reports "on" for a role that is denied it — looks correct
 * in a diff and is unfalsifiable on screen: the switch shows ON, clicking it saves "deny" again,
 * and the denial can never be lifted from the UI.
 *
 * Usage: node no-sidebar-tabs-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(process.argv[2]);
const read = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");
const AUTH_SRC = read(path.join(ROOT, "auth.js"));

const HIDDEN = "/info-sheet.html";

// ── as much of a browser as auth.js touches (the stub nav-permissions-harness.js uses) ──
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
      getElementById() { return null; },
      createElement() { return el(); },
      querySelector() { return null; },
      querySelectorAll() { return []; },
      addEventListener() {},
    },
    location: { pathname: pathname || "/admin.html", search: "", origin: "https://example.test",
                replace() {}, assign() {} },
    localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    fetch() { return Promise.reject(new Error("harness: no network")); },
    matchMedia() { return { matches: true }; },
    getComputedStyle() { return { paddingTop: "0px" }; },
    setTimeout() {}, setInterval() {}, clearInterval() {},
    requestAnimationFrame() {},
    console, JSON, URLSearchParams, Set, Map, Array, Object, Promise, Error,
  };
  win.window = win;
  win.self = win;
  win.globalThis = win;
  return win;
}

function loadAuth(pathname) {
  const win = browser(pathname);
  vm.createContext(win);
  vm.runInContext(AUTH_SRC, win, { filename: "auth.js" });
  if (!win.TWAuth) throw new Error("auth.js did not publish window.TWAuth");
  return win;
}

/* Sign in as `role` with /api/me answering `me`, and let init() run end to end. */
async function signIn(role, me, pathname) {
  const win = browser(pathname);
  const appended = [];
  win.document.body.appendChild = (e) => { appended.push(e); };
  let emptied = 0;
  win.document.body.replaceChildren = () => { emptied++; };
  win.document.getElementById = (id) => (id === "tw-sidebar" || id === "tw-sidebar-css" ? null : {
    addEventListener() {}, hidden: true, innerHTML: "", textContent: "",
  });
  win.fetch = (url) => Promise.resolve({
    json: async () => (String(url).indexOf("/api/public-config") !== -1
      ? { supabase_url: "https://sb.test", supabase_anon_key: "anon",
          allowed_domain: "wetreadwell.com" }
      : Object.assign({ ok: true, email: "staffer@wetreadwell.com", name: "Sam Staffer",
                        role: role, status: "active" }, me || {})),
  });
  win.supabase = {
    createClient: () => ({
      auth: {
        onAuthStateChange() {},
        getSession: async () => ({ data: { session: {
          access_token: "token", user: { email: "staffer@wetreadwell.com",
                                         user_metadata: { full_name: "Sam Staffer" } } } } }),
        signOut: async () => {},
      },
    }),
  };
  vm.createContext(win);
  vm.runInContext(AUTH_SRC, win, { filename: "auth.js" });

  // The refusal path never settles `ready`, on purpose, so race a turn of the loop and report it.
  const raced = await Promise.race([
    win.TWAuth.ready.then(() => "settled", () => "rejected"),
    new Promise((res) => setTimeout(() => res("pending"), 80)),
  ]);
  const sidebars = appended.filter((e) => e.id === "tw-sidebar");
  const cards = appended.filter((e) => String(e.className || "").indexOf("tw-refuse") !== -1);
  return {
    ready: raced,
    emptied: emptied,
    sidebars: sidebars.length,
    sidebarHtml: sidebars.length ? sidebars[0].innerHTML : "",
    refusals: cards.length,
    refusalHtml: cards.length ? cards[0].innerHTML : "",
    title: win.document.title,
    deniedPaths: win.TWAuth.deniedPaths(),
    role: win.TWAuth.user() ? win.TWAuth.user().role : null,
  };
}

/* This file's own parse of the rendered menu, written independently of auth.js's parseNav so that
 * "the row is gone from the menu" is not one function agreeing with itself. */
function hrefsFromMarkup(markup) {
  const i = String(markup).indexOf('<nav class="tw-nav">');
  const j = String(markup).indexOf("</nav>");
  const nav = i === -1 || j === -1 ? "" : String(markup).slice(i, j);
  return (nav.match(/<a class="tw-nav-item[^"]*" href="([^"]*)"/g) || [])
    .map((a) => /href="([^"]*)"/.exec(a)[1]);
}

// The member is denied ONLY the hidden tab, so nothing about the menu can explain the result: every
// sidebar row a member had, they still have.
const POLICY = {}; POLICY.user = [HIDDEN];

async function main() {
  const win = loadAuth("/admin.html");
  const roles = win.TWAuth.roles();

  const menus = {}, matrixRows = {};
  roles.forEach((r) => {
    menus[r] = hrefsFromMarkup(win.TWAuth.sidebarMarkup(r, POLICY[r] || []));
  });
  // The matrix under the policy: the hidden tab's row must report the DENIED role as off and the
  // other two as on. Ticks read off the deny map, since there is no render to read them from.
  win.TWAuth.navMatrix(POLICY).rows.forEach((r) => { matrixRows[r.href] = r; });

  // The member standing on the page they were denied, and on one they were not.
  const pages = {}; pages[HIDDEN] = HIDDEN;
  const onDenied = await signIn("user", { nav_denied: POLICY.user, nav_denied_pages: pages },
                               HIDDEN);
  const onAllowed = await signIn("user", { nav_denied: POLICY.user, nav_denied_pages: pages },
                                 "/trash.html");
  // An admin, denied nothing, on the same page.
  const adminOnIt = await signIn("admin", { nav_denied: [], nav_denied_pages: {} }, HIDDEN);

  process.stdout.write(JSON.stringify({
    hidden: HIDDEN,
    roles: roles,
    policy: POLICY,
    menus: menus,
    matrixRow: matrixRows[HIDDEN] || null,
    matrixHrefs: Object.keys(matrixRows),
    signedIn: { onDenied: onDenied, onAllowed: onAllowed, adminOnIt: adminOnIt },
  }) + "\n");
}

main().catch((e) => { console.error(e && e.stack || String(e)); process.exit(1); });
