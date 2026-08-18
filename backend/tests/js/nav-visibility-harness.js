"use strict";
/* Execute the REAL sidebar and the REAL Admin-page matrix, and report both.
 *
 * WHAT THIS PROVES, AND WHY GREPPING CANNOT. The Admin page shows which sidebar tabs each role
 * gets. The only way that table is worth reading is if it is the menu — so this harness runs
 * frontend/auth.js in a bare VM context, asks it for the sidebar markup of each role, and runs
 * frontend/js/admin.js's own roleMatrixHtml() against the same live TWAuth. Three things then have
 * to agree, and none of them is a source assertion:
 *
 *   * the markup the sidebar would put on the page for a role, parsed HERE with this file's own
 *     regex — a second opinion, so a broken parser inside auth.js cannot agree with itself;
 *   * TWAuth.navMatrix()'s rows and ticks;
 *   * the rows the Admin page actually renders.
 *
 * THE PROBE RUNS are the ones that catch a duplicated list. A second context gets auth.js with an
 * extra navItem() spliced into the sidebar expression (one open to everybody, one behind the admin
 * gate) and NOTHING else changed — not admin.js, not the matrix. A hardcoded table shows neither.
 *
 * Usage: node nav-visibility-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(process.argv[2]);

// Line endings normalised on read: git hands these files out with CRLF on a Windows checkout and
// the source patterns below are anchored on what precedes a newline. Same trap library-ui-harness
// records at length — a passing CI on LF and a harness that "itself failed" locally.
const read = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");

const AUTH_SRC = read(path.join(ROOT, "auth.js"));
const ADMIN_SRC = read(path.join(ROOT, "js", "admin.js"));

// ── as much of a browser as auth.js touches on the way to the nav ────────────
// Deliberately not a DOM emulator. Spec mode never appends anything; these stubs exist so the
// file can LOAD (its init() runs, finds no Supabase config, and paints its fatal banner).
function browser() {
  const el = () => ({
    id: "", innerHTML: "", textContent: "", title: "", hidden: false, className: "",
    style: { cssText: "" }, dataset: {},
    classList: { add() {}, remove() {}, toggle() {} },
    appendChild() {}, insertAdjacentHTML() {}, replaceChildren() {}, remove() {},
    addEventListener() {}, setAttribute() {}, getAttribute() { return null; },
    querySelector() { return null; }, querySelectorAll() { return []; },
  });
  const win = {
    document: {
      head: el(), body: el(), documentElement: el(), hidden: false,
      getElementById() { return null; },
      createElement() { return el(); },
      querySelector() { return null; },
      querySelectorAll() { return []; },
      addEventListener() {},
    },
    location: { pathname: "/admin.html", search: "", origin: "https://example.test",
                replace() {}, assign() {} },
    localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    fetch() { return Promise.reject(new Error("harness: no network")); },
    matchMedia() { return { matches: true }; },
    getComputedStyle() { return { paddingTop: "0px" }; },
    setTimeout() {}, setInterval() {}, clearInterval() {},
    requestAnimationFrame() {},
    console, JSON, URLSearchParams, Set, Map,
  };
  win.window = win;
  win.self = win;
  win.globalThis = win;
  return win;
}

/** Load a copy of auth.js (optionally patched) and hand back its TWAuth. */
function loadAuth(src) {
  const win = browser();
  vm.createContext(win);
  vm.runInContext(src, win, { filename: "auth.js" });
  if (!win.TWAuth) throw new Error("auth.js did not publish window.TWAuth");
  return win;
}

/* Sign in as `role` and let auth.js render the sidebar for real, all the way to
 * document.body.appendChild — then hand back the markup it appended.
 *
 * This is the run that makes the matrix honest. Everything else here goes through spec mode; if
 * spec mode ever drifted from the DOM path — a role read from the wrong place, a gate evaluated
 * against currentUser instead of the argument — every other check would agree with itself and be
 * wrong. Comparing the appended markup with sidebarMarkup(role) character for character is the
 * only thing that catches it. */
async function renderForReal(src, role) {
  const win = browser();
  const appended = [];
  win.document.body.appendChild = (el) => { appended.push(el); };
  // Everything except the sidebar itself is "already there", so the notification mount bails and
  // the wiring finds objects to attach handlers to.
  win.document.getElementById = (id) => (id === "tw-sidebar" || id === "tw-sidebar-css" ? null : {
    addEventListener() {}, hidden: true, innerHTML: "", textContent: "",
  });
  win.fetch = (url) => Promise.resolve({
    json: async () => (String(url).indexOf("/api/public-config") !== -1
      ? { supabase_url: "https://sb.test", supabase_anon_key: "anon",
          allowed_domain: "wetreadwell.com" }
      : { ok: true, email: "staffer@wetreadwell.com", name: "Sam Staffer",
          role: role, status: "active" }),
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
  vm.runInContext(src, win, { filename: "auth.js" });
  await win.TWAuth.ready;
  const bar = appended.filter((el) => el.id === "tw-sidebar");
  const markup = bar.length ? bar[0].innerHTML : "";
  const spec = win.TWAuth.sidebarMarkup(role);
  return {
    appendedCount: appended.length,
    sidebars: bar.length,
    markup: markup,
    role: win.TWAuth.user() ? win.TWAuth.user().role : null,
    specMarkup: spec,
    // The NAV is what has to match character for character. The whole aside cannot: the signed-in
    // chip below it carries a name, an email and an avatar colour, and spec mode has a role and
    // nothing else — by design, since nobody is being asked to render a person.
    navMatches: navOf(markup) === navOf(spec),
    nav: navOf(markup),
    specNav: navOf(spec),
  };
}

/** The <nav> section of a rendered sidebar, inclusive of its closing tag. */
function navOf(markup) {
  const i = markup.indexOf('<nav class="tw-nav">');
  const j = markup.indexOf("</nav>");
  return i === -1 || j === -1 ? "" : markup.slice(i, j + 6);
}

// ── this file's OWN parse of the sidebar markup ──────────────────────────────
// Written independently of auth.js's parseNav on purpose: if both used the same code, "the matrix
// matches the sidebar" would only prove one function agrees with itself.
function entriesFromMarkup(markup) {
  const nav = markup.slice(markup.indexOf('<nav class="tw-nav">'), markup.indexOf("</nav>"));
  const out = [];
  let section = "";
  const re = /<div class="tw-section">([^<]*)<\/div>|<a class="tw-nav-item([^"]*)" href="([^"]*)">([\s\S]*?)<\/a>/g;
  let m;
  while ((m = re.exec(nav)) !== null) {
    if (m[1] !== undefined) { section = m[1].replace(/&amp;/g, "&"); continue; }
    const ico = /<span class="tw-nav-ico">([^<]*)<\/span>/.exec(m[4]);
    const label = /<span class="tw-nav-label">([^<]*)<\/span>/.exec(m[4]);
    const tag = /<span class="tw-nav-tag">([^<]*)<\/span>/.exec(m[4]);
    out.push({
      section: section,
      href: m[3],
      glyph: ico ? ico[1] : "",
      label: label ? label[1].replace(/&amp;/g, "&") : "",
      tag: tag ? tag[1] : "",
      active: /\bactive\b/.test(m[2]),
    });
  }
  return out;
}

// ── the Admin page's own renderer, lifted and run ────────────────────────────
/** Lift a named function out of admin.js (four-space indent, no IIFE), braces balanced. */
function adminFn(name) {
  const m = new RegExp("\\n    function " + name + "\\s*\\(").exec(ADMIN_SRC);
  if (!m) {
    throw new Error(name + "() is gone from admin.js — rewrite this harness, don't stub it");
  }
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

/** The page's roleMatrixHtml(), running against the given live TWAuth as role `me`. */
function renderAdminMatrix(win, me) {
  const make = new Function("window", "ME", `
    "use strict";
    var TWAuth = window.TWAuth;
    ${adminGrab(/^    const ROLE_LABEL = \{[^}]*\};$/m, "ROLE_LABEL")}
    ${adminFn("esc")}
    ${adminFn("roleLabelOf")}
    ${adminFn("roleDiffSentence")}
    ${adminFn("roleMatrixHtml")}
    return roleMatrixHtml();
  `);
  return make(win, { role: me, email: "someone@wetreadwell.com" });
}

/** Rows the rendered panel actually shows: label + which role cells are ticked. */
function rowsFromPanel(html) {
  const body = html.slice(html.indexOf("<tbody"), html.indexOf("</tbody>"));
  return body.split("</tr>").filter((r) => /data-href=/.test(r)).map((r) => {
    const href = /data-href="([^"]*)"/.exec(r)[1];
    const cells = [];
    const re = /<td class="rv-cell" data-role="([^"]*)"[^>]*>([\s\S]*?)<\/td>/g;
    let m;
    while ((m = re.exec(r)) !== null) cells.push([m[1], /✓/.test(m[2])]);
    const roles = {};
    cells.forEach(([role, on]) => { roles[role] = on; });
    return {
      href: href,
      roles: roles,
      label: (/data-label="([^"]*)"/.exec(r) || ["", ""])[1],
      section: (/data-section="([^"]*)"/.exec(r) || ["", ""])[1],
      // What the section COLUMN prints, which is blank on all but the first row of a group.
      sectionCell: (/<td class="rv-sec">([^<]*)<\/td>/.exec(r) || ["", ""])[1],
    };
  });
}

// ── run 1: the shipped file ──────────────────────────────────────────────────
const win = loadAuth(AUTH_SRC);
const roles = win.TWAuth.roles();
const sidebar = {}, spec = {};
roles.forEach((r) => {
  sidebar[r] = entriesFromMarkup(win.TWAuth.sidebarMarkup(r));
  spec[r] = win.TWAuth.navSpec(r);
});
const matrix = win.TWAuth.navMatrix();
// The panel as each role would see it. A member never reaches this page (boot() bounces them), but
// rendering it for all three is what proves the "which column is mine" marker follows the viewer.
const panel = {}, panelHtml = {};
roles.forEach((r) => {
  panelHtml[r] = renderAdminMatrix(win, r);
  panel[r] = rowsFromPanel(panelHtml[r]);
});

// ── run 2: a probe item spliced into the sidebar, nothing else changed ───────
// Anchored on the end of the nav and on an item that is not itself gated, so this run stays
// independent of the ONE real gate. Anchoring the gated probe on the Admin item would mean a
// mutation that drops that gate breaks the harness instead of failing the test that is about it.
const OPEN_ANCHOR = 'navItem("/trash.html", "🗑", "Trash") +';
const GATED_ANCHOR = "      '</nav>' +";
if (AUTH_SRC.indexOf(OPEN_ANCHOR) === -1 || AUTH_SRC.indexOf(GATED_ANCHOR) === -1) {
  throw new Error("the sidebar expression has moved; re-point the probe anchors in this harness");
}
const probeSrc = AUTH_SRC
  .replace(OPEN_ANCHOR,
    OPEN_ANCHOR + '\n      navItem("/probe-open.html", "★", "Probe Open", "NEW") +')
  .replace(GATED_ANCHOR,
    '      (isAdmin ? navItem("/probe-gated.html", "☆", "Probe Gated") : "") +\n' + GATED_ANCHOR);
const probeWin = loadAuth(probeSrc);
const probeMatrix = probeWin.TWAuth.navMatrix();
const probePanel = rowsFromPanel(renderAdminMatrix(probeWin, "admin"));

// ── run 3+: the real DOM render, once per role ────────────────────────────────
async function main() {
  const rendered = {};
  for (const r of roles) rendered[r] = await renderForReal(AUTH_SRC, r);
  process.stdout.write(JSON.stringify({
    roles: roles,
    sidebar: sidebar,
    spec: spec,
    matrix: matrix,
    panel: panel,
    panelHtml: panelHtml,
    rendered: rendered,
    renderedEntries: Object.keys(rendered).reduce((acc, r) => {
      acc[r] = entriesFromMarkup(rendered[r].markup);
      return acc;
    }, {}),
    probe: {
      matrixRows: probeMatrix.rows.map((r) => ({ href: r.href, label: r.label, tag: r.tag,
                                                 roles: r.roles })),
      panelRows: probePanel,
    },
  }) + "\n");
}

main().catch((e) => { console.error(e && e.stack || String(e)); process.exit(1); });
