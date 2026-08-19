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
const ADMIN_SRC = read(path.join(ROOT, "js", "admin.js"));

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

// ── the Admin page's own matrix, lifted and run ───────────────────────────────
/** Lift a named function out of admin.js (four-space indent, no IIFE), braces balanced. */
function adminFn(name) {
  const m = new RegExp("\\n    function " + name + "\\s*\\(").exec(ADMIN_SRC);
  if (!m) throw new Error(name + "() is gone from admin.js — rewrite this harness, don't stub it");
  const i = ADMIN_SRC.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < ADMIN_SRC.length; j++) {
    if (ADMIN_SRC[j] === "{") depth++;
    else if (ADMIN_SRC[j] === "}" && --depth === 0) return ADMIN_SRC.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name + "() in admin.js");
}

function adminGrab(re, what) {
  const m = re.exec(ADMIN_SRC);
  if (!m) throw new Error(what + " is gone from admin.js — rewrite this harness");
  return m[0];
}

/* The page's roleMatrixHtml(), run against the given live TWAuth as role `me`, for `policy`.
 *
 * The POLICY IS PASSED IN rather than assigned to a module variable, because that is the seam the
 * page itself uses: shell() calls roleMatrixHtml() with no argument and it falls back to what boot()
 * fetched. Handing it in here is the same code path with the fetch removed. */
function renderAdminMatrix(win, me, policy) {
  const make = new Function("window", "ME", "policy", `
    "use strict";
    var TWAuth = window.TWAuth;
    ${adminGrab(/^    const ROLE_LABEL = \{[^}]*\};$/m, "ROLE_LABEL")}
    ${adminFn("esc")}
    ${adminFn("roleLabelOf")}
    ${adminFn("roleDiffSentence")}
    ${adminFn("roleMatrixHtml")}
    return roleMatrixHtml(policy);
  `);
  return make(win, { role: me, email: "someone@wetreadwell.com" }, policy || null);
}

/** Rows the rendered panel shows: which cells are ticked, and what switch each one drew. */
function rowsFromPanel(html) {
  const body = html.slice(html.indexOf("<tbody"), html.indexOf("</tbody>"));
  return body.split("</tr>").filter((r) => /data-href=/.test(r)).map((r) => {
    const roles = {}, switches = {};
    const cell = /<td class="rv-cell" data-role="([^"]*)"[^>]*>([\s\S]*?)<\/td>/g;
    let m;
    while ((m = cell.exec(r)) !== null) {
      roles[m[1]] = /✓/.test(m[2]);
      const btn = /<button([^>]*)>/.exec(m[2]);
      switches[m[1]] = btn ? {
        on: /class="rv-sw rv-on"/.test(btn[0]),
        disabled: / disabled/.test(btn[1]),
        pressed: (/aria-pressed="([^"]*)"/.exec(btn[1]) || [])[1],
        dataOn: (/data-on="([^"]*)"/.exec(btn[1]) || [])[1],
        href: (/data-href="([^"]*)"/.exec(btn[1]) || [])[1],
        role: (/data-role="([^"]*)"/.exec(btn[1]) || [])[1],
        title: (/title="([^"]*)"/.exec(btn[1]) || [])[1],
      } : null;
    }
    return {
      href: (/data-href="([^"]*)"/.exec(r) || ["", ""])[1],
      label: (/data-label="([^"]*)"/.exec(r) || ["", ""])[1],
      section: (/data-section="([^"]*)"/.exec(r) || ["", ""])[1],
      chip: (/<span class="rv-(lock|thin|hard)"/.exec(r) || ["", ""])[1],
      roles: roles,
      switches: switches,
    };
  });
}

// ── the runs ─────────────────────────────────────────────────────────────────
// Two roles denied different tabs, so "it filtered the menu" cannot pass by filtering every menu.
const POLICY = { user: ["/leads.html", "/polish-intake.html"], admin: ["/history.html"] };

// The capability table as /api/admin/nav-access serves it. Kept in step with backend/nav_access.py by
// test_nav_permissions_ui.py, which builds this from the module rather than trusting the copy.
const CAPS = [
  { href: "/portal.html", label: "Active Projects", api: [], locked: true },
  { href: "/leads.html", label: "Lead Inbox", api: ["/api/leads", "/api/leads/"], locked: false },
  { href: "/crm.html", label: "Bid Pipeline", api: ["/api/basisboard/"], locked: false },
  { href: "/calendar.html", label: "Bid Calendar",
    api: ["/api/calendar/events", "/api/calendar/events/"], locked: false },
  { href: "/info-sheet.html", label: "Info Sheet", api: ["/api/info-sheet/"], locked: false },
  { href: "/polish-intake.html", label: "Polish Estimate", api: [], locked: false },
  { href: "/analytics.html", label: "Analytics", api: ["/api/analytics/"], locked: false },
  { href: "/projects.html", label: "Proposals Database", api: [], locked: false },
  { href: "/library.html", label: "Items and Assemblies", api: [], locked: false },
  { href: "/history.html", label: "History", api: ["/api/history"], locked: false },
  { href: "/trash.html", label: "Trash", api: ["/api/trash"], locked: false },
  { href: "/notifications.html", label: "Notification Sending", api: [], locked: false },
  { href: "/followup-settings.html", label: "Auto Followups",
    api: ["/api/followup-settings", "/api/followup-settings/"], locked: false },
  { href: "/admin.html", label: "Admin", api: [], locked: true },
];

const FULL_POLICY = {
  deny: POLICY, tabs: CAPS,
  locked_pages: ["/admin.html", "/portal.html"], locked_roles: ["super_admin"],
  updated_at: "2026-08-19T12:00:00Z", updated_by: "kyle@wetreadwell.com",
};

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

  // 4. The Admin page's own panel: with the full policy (as each role, so "which switches may I
  //    touch" can be checked per viewer), with the deny map but NO capability table (a failed policy
  //    fetch — read-only), and with nothing at all (the state test_role_visibility_matrix.py owns).
  win.TWAuth.setNavDeny({});
  const panel = {}, panelHtml = {};
  roles.forEach((r) => {
    panelHtml[r] = renderAdminMatrix(win, r, FULL_POLICY);
    panel[r] = rowsFromPanel(panelHtml[r]);
  });
  const readOnlyHtml = renderAdminMatrix(win, "admin", { deny: POLICY });
  const noPolicyHtml = renderAdminMatrix(win, "admin", null);

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
    caps: CAPS,
    panel: panel,
    panelHtml: panelHtml,
    readOnlyHtml: readOnlyHtml,
    readOnlyRows: rowsFromPanel(readOnlyHtml),
    noPolicyHtml: noPolicyHtml,
    noPolicyRows: rowsFromPanel(noPolicyHtml),
  }) + "\n");
}

main().catch((e) => { console.error(e && e.stack || String(e)); process.exit(1); });
