"use strict";
/* Run the Notification Sending page's per-project half FOR REAL — categorisation, the pills, the
 * pager, and the chip toggles — out of frontend/js/notifications.js.
 *
 * WHY EXECUTED, NOT GREPPED. Every interesting way this can be wrong is invisible to a source
 * assertion:
 *
 *   * `ppCategory` is an ORDER, not a set of predicates. A grep proves `isLost` is mentioned;
 *     only running it proves a lost test project lands under Lost and not under Test, and that
 *     the four categories still partition the input so no project is reachable from no tab.
 *   * The pills read their numbers from one list and the rows from another. Whether they agree
 *     is behaviour: pointing `ppCounts` at the unfiltered list leaves both call sites intact.
 *   * A page slice is an off-by-one waiting to happen, and `rows.slice(page * N, ...)` reads
 *     perfectly well.
 *   * The chips are re-wired on every render. "Does a toggle on page 2 of Won still send the
 *     right PUT" is a question about handlers attached to freshly generated HTML.
 *
 * The predicates come from the REAL crm-core.js, so a change to what "test" or "lost" or
 * "deposit satisfied" means is felt here rather than stubbed away.
 *
 * Usage: node notify-tabs-harness.js <frontend-dir>   →   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(process.argv[2]);

// CRLF normalised on read: this harness matches the page's SOURCE TEXT and git hands these files
// out with CRLF on a Windows checkout, where a `$`-anchored pattern would find `\r` and miss.
// (library-ui-harness.js learned this the hard way — CI checks out LF and stays green.)
const read = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");

const src = read(path.join(ROOT, "js", "notifications.js"));
const C = require(path.join(ROOT, "js", "crm-core.js"));

/** Lift a named function out of the page's IIFE (two-space indent), braces balanced.
 *  `async` included, because toggleProject is one and dropping the keyword would turn an
 *  awaited fetch into a synchronous call that throws. */
function fn(name) {
  const m = new RegExp("\\n  (?:async )?function " + name + "\\s*\\(").exec(src);
  if (!m) throw new Error(name + "() is gone from notifications.js — rewrite this harness, don't stub it");
  const i = src.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return src.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name + "()");
}
function grab(re, what) {
  const m = re.exec(src);
  if (!m) throw new Error(what + " is gone from notifications.js — rewrite this harness");
  return m[0];
}

// ── a DOM small enough to read, real enough to hold the controls ─────────────
// The page writes rows as an innerHTML string and then queries them, so nodes materialise from
// that string rather than from a parser: the objects the click handlers get are built out of the
// page's OWN output, which is the point — a fixture could agree with the handler and disagree
// with what renders.
function parseControls(html, cls, tag) {
  const out = [];
  const re = new RegExp("<" + tag + '\\s+class="' + cls + '[^"]*"([^>]*)>', "g");
  let m;
  while ((m = re.exec(html))) {
    const attrs = m[1];
    const node = {
      dataset: {}, listeners: {}, disabled: /\sdisabled(?=[\s>])/.test(attrs),
      addEventListener(k, f) { (this.listeners[k] = this.listeners[k] || []).push(f); },
      click() { (this.listeners.click || []).forEach((f) => f({})); },
    };
    let a;
    const ra = /data-([a-z-]+)="([^"]*)"/g;
    while ((a = ra.exec(attrs))) {
      node.dataset[a[1].replace(/-([a-z])/g, (s, c) => c.toUpperCase())] = a[2];
    }
    out.push(node);
  }
  return out;
}

function listNode() {
  let html = "";
  let cache = null;
  return {
    get innerHTML() { return html; },
    set innerHTML(v) { html = String(v); cache = null; },
    /** Cached per rendered string so a handler attached to a node is the node that gets clicked;
     *  invalidated the moment innerHTML is replaced, exactly like a real re-render. */
    _nodes() {
      if (!cache) {
        cache = {
          ".nt-chip": parseControls(html, "nt-chip", "button"),
          ".pp-reset": parseControls(html, "pp-reset", "button"),
        };
      }
      return cache;
    },
    querySelectorAll(sel) { return this._nodes()[sel] || []; },
  };
}

/** One tab pill, with the count badge the page writes into.
 *
 *  `closest` is real behaviour, not scaffolding: the handler is delegated on the strip and reads
 *  `e.target.closest("[data-pptab]")`, because the count badge inside the button is a perfectly
 *  ordinary click target. A handler that read `e.target.dataset.pptab` would work on the label and
 *  do nothing on the number, so the harness clicks BOTH. */
function pill(id) {
  const n = { textContent: "0" };
  const self = {
    dataset: { pptab: id }, attrs: {},
    setAttribute(k, v) { this.attrs[k] = v; },
    querySelector(sel) { return sel === ".n" ? n : null; },
    closest(sel) { return sel === "[data-pptab]" ? self : null; },
    _n: n,
  };
  // The badge, as a click target: it walks up to its pill, exactly as the DOM would.
  self._badge = { closest: (sel) => (sel === "[data-pptab]" ? self : null) };
  return self;
}

/** A node that records the listeners wired onto it, and refuses to fire a click on a disabled
 *  button — which is what a browser does, and the difference between "Next is disabled" being
 *  a real guard and being decoration. */
function control(extra) {
  return Object.assign({
    listeners: {},
    addEventListener(k, f) { (this.listeners[k] = this.listeners[k] || []).push(f); },
    fire(k, ev) {
      if (this.disabled) return false;
      (this.listeners[k] || []).forEach((f) => f(ev || {}));
      return true;
    },
  }, extra || {});
}

function makeDom(tabIds) {
  const pills = tabIds.map(pill);
  const nodes = {
    "pp-list": listNode(),
    "pp-tabs": control({
      querySelectorAll(sel) { return sel === "[data-pptab]" ? pills : []; },
      _pills: pills,
    }),
    "pp-search": control({ value: "" }),
    "pp-alert": { className: "", textContent: "" },
    "pp-pager": { hidden: false },
    "pp-pgn": { textContent: "" },
    "pp-prev": control({ disabled: false }),
    "pp-next": control({ disabled: false }),
  };
  return { nodes, pills };
}

// ── the page's own module state, supplied exactly as the page supplies it ─────
/** One tab's worth of sessionStorage. A FRESH store per scope by default — sharing one across
 *  builds silently carried the previous block's chosen tab into the next and made a passing
 *  assertion depend on the order the blocks happen to run in. Pass a store in to test that the
 *  choice actually survives a reload. */
function makeStorage(store) {
  return {
    store,
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
  };
}

/** Build a live scope holding the REAL functions, sharing one set of module vars. */
function build(opts) {
  const o = opts || {};
  const store = o.store || {};
  const sessionStorage = makeStorage(store);
  const dom = makeDom(["active", "won", "lost", "test"]);
  const puts = [];
  const source = [
    grab(/^  const PP_TABS = .*$/m, "PP_TABS"),
    grab(/^  const PP_IDS = .*$/m, "PP_IDS"),
    "  const PP_LABEL = {};",
    grab(/^  PP_TABS\.forEach\(.*$/m, "the PP_LABEL fill"),
    grab(/^  const PP_PER_PAGE = .*$/m, "PP_PER_PAGE"),
    grab(/^  const PP_TAB_KEY = .*$/m, "the storage keys"),
    grab(/^  const ss = .*$/m, "ss()"),
    grab(/^  const ssSet = .*$/m, "ssSet()"),
    grab(/^  let PP_TAB = .*$/m, "PP_TAB"),
    grab(/^  let PP_PAGE = .*$/m, "PP_PAGE"),
    // isWon moved to crm-core on 2026-08-19 ("CRM lost and won should also tie up to the
    // notification sending"). Lifted from the PAGE as the line that binds it, so the harness
    // still fails loudly if the page ever re-implements it locally instead of reading core.
    grab(/^  const isWon = C\.\w+;$/m, "the isWon binding"), fn("ppCategory"), fn("ppCounts"), fn("ppPageCount"), fn("ppSlice"),
    fn("ppMatches"), fn("ppGoto"), fn("syncPpTabs"), fn("syncPpPager"), fn("ppRowHtml"),
    fn("renderProjects"), fn("peopleFor"), fn("toggleProject"),
    // The REAL wiring out of render(), wrapped in a function so it can be called once. Lifted
    // rather than re-created here on purpose: a harness that set PP_TAB itself and then called
    // renderProjects tested a categorisation nobody clicks. Replacing the handler's `ppGoto(1)`
    // with a bare `renderProjects()` — the mutation that leaves you on page 3 of the new tab —
    // survived that version of this file untouched.
    "  function wirePp() {\n" + grab(
      /^ {4}\$\("pp-search"\)\.addEventListener[\s\S]*?ppGoto\(PP_PAGE \+ 1\)\);$/m,
      "the per-project control wiring in render()") + "\n  }",
  ].join("\n");

  const scope = new Function(
    "$", "esc", "nameOf", "plainAvatar", "C", "sessionStorage", "api", "ADMIN", "MY_EMAIL",
    "ROSTER", "PROJECTS", "OVERRIDES", "ppAlert", "puts",
    '"use strict";\n' + source + "\n" +
    "return { renderProjects, ppCategory, ppCounts, ppPageCount, ppSlice, ppMatches, isWon,\n" +
    "         ppGoto, peopleFor, wirePp, PP_PER_PAGE, PP_IDS,\n" +
    "         tab: () => PP_TAB, page: () => PP_PAGE };");

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const overrides = o.overrides || {};
  const api = (p, init) => {
    puts.push({ path: p, method: (init || {}).method, body: JSON.parse((init || {}).body || "{}") });
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
  };

  const s = scope(
    (id) => dom.nodes[id] || null,
    esc,
    C.nameOf,
    (who) => '<span class="nt-av">' + (C.initialsOf(who) || "—") + "</span>",
    C,
    sessionStorage,
    api,
    o.admin !== false,
    (o.me || "hanz@wetreadwell.com").toLowerCase(),
    o.roster || [{ email: "hanz@wetreadwell.com", enabled: true },
                 { email: "kyle.loseke@wetreadwell.com", enabled: false }],
    o.projects || [],
    overrides,
    () => {},
    puts);
  s.dom = dom;
  s.puts = puts;
  s.overrides = overrides;
  s.store = store;
  s.wirePp();                                   // once, exactly as render() does it

  // ── the page, driven the way a person drives it ─────────────────────────────
  /** Click a tab pill. `onBadge` clicks the count inside it instead of the label. */
  s.clickTab = (id, onBadge) => {
    const p = dom.pills.filter((x) => x.dataset.pptab === id)[0];
    if (!p) throw new Error("no pill for " + id);
    dom.nodes["pp-tabs"].fire("click", { target: onBadge ? p._badge : p });
  };
  s.clickNext = () => dom.nodes["pp-next"].fire("click");
  s.clickPrev = () => dom.nodes["pp-prev"].fire("click");
  s.typeSearch = (v) => {
    dom.nodes["pp-search"].value = v;
    dom.nodes["pp-search"].fire("input");
  };
  s.chips = () => dom.nodes["pp-list"].querySelectorAll(".nt-chip");
  s.html = () => dom.nodes["pp-list"].innerHTML;
  s.rowCount = () => (s.html().match(/class="pp-row"/g) || []).length;
  s.names = () => (s.html().match(/class="pp-name">([^<]*)</g) || []).map((m) => m.slice(16, -1));
  s.pillCounts = () => dom.pills.reduce((a, p) => {
    a[p.dataset.pptab] = Number(p._n.textContent);
    return a;
  }, {});
  return s;
}

// ── fixtures ────────────────────────────────────────────────────────────────
// Named for the case each one exists to pin down. `is_test:false` on the two "…-real" rows is
// deliberate: the tri-state's false has to beat the name heuristic, or a project genuinely called
// "Test Street Remodel" can never leave the Test tab.
const ROWS = [
  // Active: live work, in every shape the pipeline produces one.
  { proposal_id: "a-sent", project_name: "Cedar Ridge Distribution Center",
    proposal_status: "sent" },
  { proposal_id: "a-viewed", project_name: "Maple Street Warehouse", proposal_status: "viewed" },
  { proposal_id: "a-notsent", project_name: "Riverbend Logistics Hub", not_sent: true },
  // Approved, deposit STILL OUTSTANDING — the case Won must not swallow. The board keeps it on
  // its live columns, and it is the most worth-chasing row there is.
  { proposal_id: "a-approved-owes", project_name: "Fairview Clinic", proposal_status: "approved",
    approved_at: "2026-08-01T10:00:00+00:00", deposit_requested_at: "2026-08-02T10:00:00+00:00",
    deposit_status: "requested" },
  { proposal_id: "a-approved-submitted", project_name: "Northgate Fulfilment",
    proposal_status: "approved", approved_at: "2026-08-03T10:00:00+00:00",
    deposit_requested_at: "2026-08-03T12:00:00+00:00", deposit_status: "submitted" },
  // depositSatisfied but NEVER APPROVED: a no-deposit job emailed this morning. Won must not
  // take it — this is the row that kills "Won === depositSatisfied".
  { proposal_id: "a-nodeposit-unapproved", project_name: "Brookside Gym",
    proposal_status: "sent", deposit_required: false },

  // Won: they said yes AND the money question is settled.
  { proposal_id: "w-deposit-in", project_name: "Westport Retail Center",
    proposal_status: "approved", approved_at: "2026-07-20T10:00:00+00:00",
    deposit_requested_at: "2026-07-21T10:00:00+00:00", deposit_status: "received" },
  { proposal_id: "w-no-deposit-needed", project_name: "Harborview Offices",
    proposal_status: "approved", approved_at: "2026-07-22T10:00:00+00:00",
    deposit_required: false },
  // Moved past approval by the portal: contacts in, status no longer says "approved". The
  // approved_at stamp is what keeps it Won.
  { proposal_id: "w-contacts-in", project_name: "Lakeshore Medical",
    proposal_status: "contacts", approved_at: "2026-07-23T10:00:00+00:00",
    deposit_requested_at: "2026-07-24T10:00:00+00:00", deposit_status: "received",
    contacts_status: "received" },

  // MARKED WON BY HAND (2026-08-19). Hanz: "Is there any way to also mark as won for now other than
  // after the deposit has been received". Neither half of the derived rule is true of these two —
  // one was never even sent — so they are what proves the override reaches this page's Won tab.
  { proposal_id: "w-marked", project_name: "Elmwood Cold Storage", proposal_status: "sent",
    won_at: "2026-08-19T15:00:00+00:00" },
  { proposal_id: "w-marked-notsent", project_name: "Pinecrest Distribution", not_sent: true,
    won_at: "2026-08-19T15:00:00+00:00" },

  // Test, by the flag and by the name.
  { proposal_id: "t-flag", project_name: "Cedar Ridge Distribution Center", is_test: true,
    proposal_status: "sent" },
  { proposal_id: "t-name", project_name: "Test Will 7/29", proposal_status: "sent" },
  // WON AND TEST — Test wins: a scratch bid must not inflate a number a human reads as revenue.
  { proposal_id: "t-won", project_name: "QA Sample Job", is_test: true,
    proposal_status: "approved", approved_at: "2026-07-25T10:00:00+00:00",
    deposit_status: "received" },
  // MARKED WON BY HAND AND TEST — still Test. A human pressing the button says nothing about whether
  // the project is real work, so the manual override must not be a way round the same precedence.
  { proposal_id: "t-marked-won", project_name: "Verify Street zz", is_test: true,
    proposal_status: "sent", won_at: "2026-08-19T15:00:00+00:00" },
  // Named like a test but FILED as real — the flag's false has to beat the heuristic.
  { proposal_id: "a-testname-real", project_name: "Test Street Remodel", is_test: false,
    proposal_status: "sent" },

  // Lost, including the two precedence cases.
  { proposal_id: "l-price", project_name: "Ironwood Plaza", proposal_status: "closed_lost",
    followup_state: { closed_lost_reason: "price" } },
  // LOST AND TEST — Lost wins, matching the CRM board exactly.
  { proposal_id: "l-test", project_name: "Demo Bid zz", is_test: true,
    proposal_status: "closed_lost" },
  // LOST AFTER BEING APPROVED AND PAID — Lost still wins. Money came in and the job died.
  { proposal_id: "l-was-won", project_name: "Summit Freight", proposal_status: "closed_lost",
    approved_at: "2026-06-01T10:00:00+00:00", deposit_status: "received" },
  // MARKED WON BY HAND AND THEN CLOSED LOST — Lost still wins. The two facts are stored
  // independently on purpose (see drafts.set_won), because a sent project's closed_lost belongs to
  // the portal and no draft-side write can clear it — so this precedence is the ONLY thing keeping a
  // cancelled job off the Won tab.
  { proposal_id: "l-was-marked-won", project_name: "Grandview Terminal",
    proposal_status: "closed_lost", won_at: "2026-08-19T15:00:00+00:00",
    followup_state: { closed_lost_reason: "canceled" } },
];

/** 25 Active rows, for the paging assertions. Page size is read from the page, never retyped. */
function manyActive(n) {
  const out = [];
  for (let i = 1; i <= n; i++) {
    out.push({ proposal_id: "p" + i, project_name: "Project " + i, proposal_status: "sent" });
  }
  return out;
}

const out = {};

// ── categorisation, run for real ─────────────────────────────────────────────
{
  const s = build({ projects: ROWS });
  out.categoryOf = {};
  ROWS.forEach((p) => { out.categoryOf[p.proposal_id] = s.ppCategory(p); });
  out.everyId = ROWS.map((p) => p.proposal_id);
  out.counts = s.ppCounts(ROWS);
  out.pageSize = s.PP_PER_PAGE;
  out.tabIds = s.PP_IDS;
  // crm-core's own verdicts on the same rows, so a disagreement with the board is visible here
  // rather than only on someone's screen.
  out.boardStage = {};
  ROWS.forEach((p) => { out.boardStage[p.proposal_id] = C.stage(p); });
  out.depositSatisfied = {};
  ROWS.forEach((p) => { out.depositSatisfied[p.proposal_id] = C.depositSatisfied(p); });
}

/** Everything a test wants to know about the page as it stands. Never indexes into a list it has
 *  not checked: a broken slice must come back as a reportable zero, not as a harness crash — an
 *  ERROR says "the harness broke", and only a FAILURE says "the page is wrong". */
function snap(s) {
  const html = s.html();
  return {
    page: s.page(),
    tab: s.tab(),
    rows: s.rowCount(),
    names: s.names(),
    pillCounts: s.pillCounts(),
    pressed: s.dom.pills.filter((p) => p.attrs["aria-pressed"] === "true")
                        .map((p) => p.dataset.pptab),
    text: s.dom.nodes["pp-pgn"].textContent,
    prevDisabled: s.dom.nodes["pp-prev"].disabled,
    nextDisabled: s.dom.nodes["pp-next"].disabled,
    hidden: s.dom.nodes["pp-pager"].hidden,
    testTag: (html.match(/pp-badge-test/g) || []).length,
    // Which rows carry a Test tag, by name — a count alone cannot tell "tagged the right row"
    // from "tagged one row".
    tagged: (html.match(/pp-name">([^<]*)<\/span><span class="pp-cust">[^<]*<\/span><span class="pp-badge pp-badge-test"/g)
              || []).map((m) => m.slice(9).split("<")[0]),
    chipCount: s.chips().length,
    html: html.indexOf("pp-row") < 0 ? html : "",     // the empty-state note, when that's all there is
  };
}

// ── the pills, and what each tab actually RENDERS ─────────────────────────────
// Reached by CLICKING the pill, through the page's own delegated handler.
{
  const s = build({ projects: ROWS });
  s.renderProjects();
  out.tabs = { active: snap(s) };
  ["won", "lost", "test"].forEach((id) => {
    s.clickTab(id);
    out.tabs[id] = snap(s);
  });
  // The count badge inside the pill is an ordinary click target; it must select the same tab.
  s.clickTab("active", true);
  out.badgeClick = snap(s);
}

// ── pagination, driven by Prev/Next ──────────────────────────────────────────
{
  const s = build({ projects: manyActive(25) });
  s.renderProjects();
  out.paging = { p1: snap(s) };
  s.clickNext(); out.paging.p2 = snap(s);
  s.clickNext(); out.paging.p3 = snap(s);
  // Next on the last page: the browser will not fire a click on a disabled button, and the
  // harness honours that — so this is "the guard holds", not "the clamp catches it".
  out.paging.nextFiredPastEnd = s.clickNext();
  out.paging.past = snap(s);
  s.clickPrev(); out.paging.backToP2 = snap(s);
  // Switching tab resets to page 1 — and the pager vanishes on a tab with one page.
  s.clickNext();
  out.paging.beforeTabSwitch = snap(s);
  s.clickTab("won");
  out.paging.afterTabSwitch = snap(s);
  // Back to Active: a fresh tab choice starts at page 1 rather than resuming page 3.
  s.clickTab("active");
  out.paging.backToActive = snap(s);
}

// TWO tabs deep enough to hold a stale page number. This case exists because the obvious one
// cannot see the bug: switching from page 3 of Active to an EMPTY Won lands on page 1 either way —
// the clamp catches it — so dropping the handler's reset passed a whole suite unnoticed. With 25
// rows on both sides, a kept page number is visible as page 3 of the tab you just opened.
{
  const both = manyActive(25).concat(manyActive(25).map((p, i) => (
    { proposal_id: "t" + (i + 1), project_name: "Scratch " + (i + 1), is_test: true,
      proposal_status: "sent" })));
  const s = build({ projects: both });
  s.renderProjects();
  s.clickNext(); s.clickNext();                      // page 3 of Active
  out.deepSwitch = { from: snap(s) };
  s.clickTab("test");
  out.deepSwitch.to = snap(s);
  s.clickTab("active");
  out.deepSwitch.back = snap(s);
}

// The clamp, reached the only way a person can: a stored page from a list that has since shrunk.
{
  const s = build({ projects: manyActive(25) });
  s.renderProjects();
  s.clickNext(); s.clickNext();                      // page 3 of 3, stored
  const t = build({ projects: manyActive(12), store: s.store });
  t.renderProjects();
  out.clampedOnLoad = snap(t);
}

// A single page hides the pager entirely; exactly one full page must NOT paginate.
{
  const s = build({ projects: manyActive(10) });
  s.renderProjects();
  out.exactlyOnePage = snap(s);
}
{
  const s = build({ projects: manyActive(11) });
  s.renderProjects();
  s.clickNext();
  out.elevenRows = snap(s);
}

// ── the empty states, which must say WHICH kind of empty ─────────────────────
{
  const s = build({ projects: [] });
  s.renderProjects();
  out.emptyNothingLoaded = snap(s);

  const t = build({ projects: ROWS });
  t.renderProjects();
  t.clickTab("test");
  t.typeSearch("no-such-project");
  out.emptyFiltered = snap(t);
}

// ── the search still narrows, and the counts follow it ────────────────────────
{
  const s = build({ projects: ROWS });
  s.renderProjects();
  s.typeSearch("cedar");
  out.search = snap(s);
}

// Typing while deep in a long list goes back to page 1 — page 3 of the old pool means nothing.
{
  const s = build({ projects: manyActive(25) });
  s.renderProjects();
  s.clickNext(); s.clickNext();
  s.typeSearch("Project 1");
  out.searchResetsPage = snap(s);
}

// ── the chosen tab and page survive a reload ─────────────────────────────────
// A SECOND scope over the same storage, which is what a reload is. Module vars alone already
// carry the choice through the page's own re-renders; this is the part that would quietly stop
// working if either ssSet call went missing.
{
  const a = build({ projects: manyActive(25) });
  a.renderProjects();
  a.clickNext(); a.clickNext();
  const b = build({ projects: manyActive(25), store: a.store });
  b.renderProjects();
  out.reload = snap(b);

  const c = build({ projects: ROWS });
  c.renderProjects();
  c.clickTab("lost");
  const d = build({ projects: ROWS, store: c.store });
  d.renderProjects();
  out.reloadTab = snap(d);

  // A junk stored tab must not filter everything out and blank the card.
  const e = build({ projects: ROWS, store: { tw_notify_pp_tab: "aliens" } });
  e.renderProjects();
  out.junkStoredTab = snap(e);
}

// ── the chips, still working after a tab and page change ─────────────────────
const tick = () => new Promise((r) => setTimeout(r, 0));
/** The nth chip, or a null-shaped stand-in. A broken slice renders nothing, and the report has to
 *  say so rather than throw before it can. */
const chipAt = (s, i) => s.chips()[i] ||
  { dataset: {}, click() {}, disabled: null, _missing: true };

(async () => {
  // Page 2 of a 25-row Active list: the chip is on a row the first render never produced.
  const s = build({ projects: manyActive(25) });
  s.renderProjects();
  s.clickNext();
  const chip = chipAt(s, 0);
  out.chipsOnPage2 = { count: s.chips().length, pid: chip.dataset.pid,
                       email: chip.dataset.email, eff: chip.dataset.eff,
                       base: chip.dataset.base };
  chip.click();                                      // Hanz is base-on → mute
  await tick();
  out.mutePut = s.puts[s.puts.length - 1] || null;
  out.afterMute = {
    page: s.page(), tab: s.tab(),
    overrides: JSON.parse(JSON.stringify(s.overrides)),
    // Re-read: the toggle re-renders, so this is a node from the NEW html.
    eff: chipAt(s, 0).dataset.eff,
    rows: s.rowCount(),
  };
  // Toggle it back: straight to the global default, so the override is CLEARED not re-added.
  chipAt(s, 0).click();
  await tick();
  out.clearPut = s.puts[s.puts.length - 1] || null;
  out.afterClear = { overrides: JSON.parse(JSON.stringify(s.overrides)), page: s.page() };

  // And on a NON-Active tab, after clicking to it: Kyle is base-off → add.
  const t = build({ projects: ROWS });
  t.renderProjects();
  t.clickTab("lost");
  const kyle = t.chips().filter((c) => c.dataset.email.indexOf("kyle") === 0)[0] ||
               { dataset: {}, click() {} };
  kyle.click();
  await tick();
  out.addPut = t.puts[t.puts.length - 1] || null;
  out.afterAdd = { tab: t.tab(), page: t.page(),
                   overrides: JSON.parse(JSON.stringify(t.overrides)) };

  // A non-admin may toggle only themselves — the disabled attribute has to reach the node.
  const n = build({ projects: manyActive(1), admin: false, me: "kyle.loseke@wetreadwell.com" });
  n.renderProjects();
  out.nonAdminChips = n.chips().map((c) => ({ email: c.dataset.email, disabled: c.disabled }));

  console.log(JSON.stringify(out));
})();
