"use strict";
/* Execute the REAL sidebar and the REAL sign-in path under a deny policy.
 *
 * WHAT THIS PROVES, AND WHY GREPPING CANNOT. Hanz asked for switches on the Admin page's role matrix
 * and chose real blocking over hiding. Three claims follow on the client side, and none of them is
 * visible in source text:
 *
 *   * a denied path leaves THAT role's menu and stays in every other role's — which needs the
 *     sidebar rendered per role under a policy, not an indexOf call spotted in a diff;
 *   * navMatrix REFLECTS stored denials, so the Admin page's ticks move with the policy rather than
 *     being a second opinion about it;
 *   * a denied page paints a refusal card INSTEAD of its own content, and auth.js's ready promise
 *     never settles afterwards — which is the mechanism that stops the page's own boot running
 *     against a document that has just been emptied.
 *
 * frontend/auth.js runs in a bare VM context, the same way nav-visibility-harness.js does it. The
 * refusal runs go all the way through init() with a stubbed Supabase and a stubbed /api/me.
 *
 * Usage: node nav-permissions-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(process.argv[2]);

// Line endings normalised on read: git hands these out with CRLF on a Windows checkout.
const read = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");
const AUTH_SRC = read(path.join(ROOT, "auth.js"));

// ── as much of a browser as auth.js touches ──────────────────────────────────
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

/* Sign in as `role` and let auth.js run init() end to end, with /api/me answering `me`.
 * Everything except the sidebar is "already there" so the notification mount bails. */
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

  // THE REFUSAL PATH NEVER SETTLES `ready` — on purpose, so no page module boots against the
  // document it just emptied. Raced against a turn of the loop so this harness reports "pending" as
  // a RESULT rather than hanging on it.
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
    entries: sidebars.length ? entriesFromMarkup(sidebars[0].innerHTML) : [],
    refusals: cards.length,
    refusalHtml: cards.length ? cards[0].innerHTML : "",
    title: win.document.title,
    deniedPaths: win.TWAuth.deniedPaths(),
    role: win.TWAuth.user() ? win.TWAuth.user().role : null,
  };
}

function navOf(markup) {
  const i = markup.indexOf('<nav class="tw-nav">');
  const j = markup.indexOf("</nav>");
  return i === -1 || j === -1 ? "" : markup.slice(i, j + 6);
}

// This file's OWN parse of the markup, written independently of auth.js's parseNav so that "the menu
// lost the tab" is not one function agreeing with itself.
function entriesFromMarkup(markup) {
  const nav = navOf(markup);
  const out = [];
  let section = "";
  const re = /<div class="tw-section">([^<]*)<\/div>|<a class="tw-nav-item([^"]*)" href="([^"]*)">([\s\S]*?)<\/a>/g;
  let m;
  while ((m = re.exec(nav)) !== null) {
    if (m[1] !== undefined) { section = m[1].replace(/&amp;/g, "&"); continue; }
    const label = /<span class="tw-nav-label">([^<]*)<\/span>/.exec(m[4]);
    out.push({ section: section, href: m[3], label: label ? label[1].replace(/&amp;/g, "&") : "" });
  }
  return out;
}

// ── the runs ─────────────────────────────────────────────────────────────────
// Two roles denied different tabs, so "it filtered the menu" cannot pass by filtering every menu.
const POLICY = { user: ["/leads.html", "/polish-intake.html"], admin: ["/history.html"] };

async function main() {
  // 1. The menu per role, under the policy and with nothing denied — asked for explicitly, so this
  //    run does not depend on /api/me having happened.
  const win = loadAuth("/admin.html");
  const roles = win.TWAuth.roles();
  const menus = {}, menusOpen = {};
  roles.forEach((r) => {
    menus[r] = entriesFromMarkup(win.TWAuth.sidebarMarkup(r, POLICY[r] || []));
    menusOpen[r] = entriesFromMarkup(win.TWAuth.sidebarMarkup(r, []));
  });

  // 2. The matrix, with and without the policy.
  const matrixOpen = win.TWAuth.navMatrix({});
  const matrixDenied = win.TWAuth.navMatrix(POLICY);
  // Called with NO argument after a policy was handed in via setNavDeny — the ordinary page path.
  win.TWAuth.setNavDeny(POLICY);
  const matrixStored = win.TWAuth.navMatrix();
  const menuStored = entriesFromMarkup(win.TWAuth.sidebarMarkup("user"));
  win.TWAuth.setNavDeny({});
  const matrixCleared = win.TWAuth.navMatrix();

  // 3. Real sign-ins: on a page the role may not open, on its second page, on one it may, on a
  //    container that predates the feature, and as a role denied something else entirely.
  const pages = { "/leads.html": "/leads.html",
                  "/polish-intake.html": "/polish-intake.html",
                  "/polish-estimate.html": "/polish-intake.html" };
  const denied = await signIn("user", { nav_denied: POLICY.user, nav_denied_pages: pages },
                              "/leads.html");
  const deniedStepTwo = await signIn("user", { nav_denied: POLICY.user, nav_denied_pages: pages },
                                     "/polish-estimate.html");
  const allowed = await signIn("user", { nav_denied: POLICY.user, nav_denied_pages: pages },
                               "/trash.html");
  const legacy = await signIn("user", {}, "/leads.html");
  const otherRole = await signIn("admin",
    { nav_denied: POLICY.admin, nav_denied_pages: { "/history.html": "/history.html" } },
    "/leads.html");

  process.stdout.write(JSON.stringify({
    roles: roles,
    policy: POLICY,
    menus: menus,
    menusOpen: menusOpen,
    matrixOpen: matrixOpen.rows.map((r) => ({ href: r.href, roles: r.roles })),
    matrixDenied: matrixDenied.rows.map((r) => ({ href: r.href, label: r.label, roles: r.roles })),
    matrixStored: matrixStored.rows.map((r) => ({ href: r.href, roles: r.roles })),
    matrixCleared: matrixCleared.rows.map((r) => ({ href: r.href, roles: r.roles })),
    menuStored: menuStored,
    signedIn: { denied: denied, deniedStepTwo: deniedStepTwo, allowed: allowed,
                legacy: legacy, otherRole: otherRole },
  }) + "\n");
}

main().catch((e) => { console.error(e && e.stack || String(e)); process.exit(1); });
