"use strict";
/* RENDER the CRM project drawer, for real, on payloads shaped like production's.
 *
 * WHY THIS EXISTS. On 2026-08-12 the Active Projects board went down on production with
 * `ReferenceError: STAGE_CREATED is not defined` while every test was green, because every test
 * asserted the source TEXT of the renderer and none of them had ever run it. The drawer is the
 * biggest single block of markup in this app — five tab panels, eight cards, a chat thread and
 * about thirty ids that a handler binds to — and until this file nothing executed a line of it.
 *
 * WHAT IT RUNS. The real `renderDetail` and `renderNotSent` out of the real portal.js, with ONLY
 * the names portal.js actually binds in scope: crm-core's exports under their real names, taken
 * from portal.js's own destructuring lines, and the page's own helpers lifted from source rather
 * than reimplemented here — `esc`, `money`, `when`, `$`, `avatar`, `plainAvatar`, `fact`. A
 * reimplemented `esc` would prove the harness escapes, not that the page does.
 *
 * WHAT IT ASSERTS THROUGH THE PYTHON SIDE (test_drawer_renders.py):
 *   - the panel renders at all, on every shape of proposal, without throwing;
 *   - the customer's portal token appears NOWHERE in the markup as text — the whole point of
 *     the 2026-08-13 redesign — while the link still works as an href;
 *   - every id the wiring looks up was rendered by the paint it is wiring (the "handler bound
 *     to an id nobody renders" bug this file's siblings have caught twice by grep);
 *   - the signature guard genuinely skips an unchanged repaint, executed rather than read;
 *   - copy-to-clipboard survives a missing clipboard and a rejected promise.
 *
 * THE DOM STUB IS A BAG OF MARKUP, NOT A TREE. It answers `querySelector`/`getElementById` out
 * of the html the code just wrote, so "does this element exist" is answered by the renderer's
 * own output. That is deliberately not jsdom: a stubbed tree lets a missing import hide behind
 * a global, which is exactly how the outage above stayed invisible. The limit is stated plainly
 * so nobody mistakes it for a browser — it cannot tell you about layout, cascade or events it
 * was not asked to fire.
 *
 * Usage: node drawer-render-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");

// Resolved, because require() takes a relative path as relative to THIS file, not to the cwd —
// so a caller passing "frontend" would get a module-not-found that reads like a missing file.
const ROOT = path.resolve(process.argv[2]);
const C = require(path.join(ROOT, "js", "crm-core.js"));
const src = fs.readFileSync(path.join(ROOT, "js", "portal.js"), "utf8");

// ── lifting real code out of the IIFE ────────────────────────────────────────
function fnSrc(name) {
  const m = new RegExp("\\n\\s{2,6}(?:async\\s+)?function " + name + "\\s*\\(").exec(src);
  if (!m) throw new Error(name + "() is gone from portal.js — rewrite this harness, don't delete it");
  const i = src.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return src.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name);
}

/** A module-level `const NAME = …;` / `let NAME = …;`, bracket-counted to its own semicolon.
 *
 *  Bracket-counted rather than line-based because half of these are multi-line object and arrow
 *  literals. It throws when a name is missing instead of returning "": a silently empty lift
 *  surfaces later as `ReferenceError: SEC_TABS is not defined` from the harness itself, which
 *  looks exactly like the product bug this file hunts. */
function declSrc(kind, name) {
  // The name is escaped because one of them IS `$` — portal.js's own getElementById shorthand —
  // and an unescaped `$` in a pattern means end-of-input, so the lift failed claiming the
  // declaration was gone.
  const m = new RegExp("\\n\\s*" + kind + " " + name.replace(/[$]/g, "\\$&") + " = ").exec(src);
  if (!m) throw new Error(kind + " " + name + " is gone from portal.js — rewrite this harness");
  let depth = 0;
  for (let j = m.index + m[0].length; j < src.length; j++) {
    const ch = src[j];
    if ("([{".includes(ch)) depth++;
    else if (")]}".includes(ch)) depth--;
    else if (ch === ";" && depth === 0) return src.slice(m.index, j + 1);
  }
  throw new Error("unterminated declaration reading " + name);
}

// EXACTLY what portal.js pulls off crm-core, read from its own destructuring lines so this cannot
// drift into binding something the page does not have.
const destructured = [];
for (const m of src.matchAll(/const \{([^}]*)\} = C;/g)) {
  for (const part of m[1].split(",")) {
    const t = part.trim();
    if (!t) continue;
    const [from, to] = t.includes(":") ? t.split(":").map((x) => x.trim()) : [t, t];
    if (!(from in C)) throw new Error("portal.js destructures C." + from + ", which crm-core does not export");
    destructured.push([to, C[from]]);
  }
}

// Order matters for the ones that run at declaration time: ALL_SEC_CARDS reads SEC_TABS, and
// fu/avatar read C.
const CONST_NAMES = [
  "$", "esc", "money", "when", "fu", "avatar", "plainAvatar", "pausedUntil", "ROLE_LABEL",
  "ACCT_TYPE_LABEL", "METHOD_LABEL", "METHOD_PHRASE", "CUSTOMER_EVENTS", "sideOf",
  "FU_KIND_LABEL", "FU_TEMPLATE_LABEL", "FU_ACTION", "STATUS_LABEL",
  "SEC_TABS", "ALL_SEC_CARDS", "SEC_ELIGIBLE", "setSecEligible",
  "REPLY_DRAFT", "NT_CACHE", "REV_CACHE", "DETAIL_CACHE", "fact", "metaLine", "headMoney",
];
// The page's mutable module state, lifted by name rather than re-declared here: rename one in
// portal.js and this file fails loudly instead of testing a variable the page no longer has.
const LET_NAMES = ["ALL", "ACTIVE_SEC", "CUR_PID", "RENDER_GEN", "DEEPLINK_USED", "DRAWER_SIG",
                   "DETAIL_RECIPIENTS", "DETAIL_GEN", "THREAD_SCROLL", "NS_MODE"];
const FN_NAMES = [
  "drawerHead", "customerHtml", "copyPortalLink", "wirePortalLink", "approvalHtml",
  "contactsHtml", "recipientsHtml", "msgHtml", "splitSystem", "depositHtml", "mask4",
  "followupPanelHtml", "followupContactsHtml", "followupRow", "followupState",
  "renderSecTabs", "secTab", "defaultSection", "unreadCount",
  "applySecPanel", "focusSection", "loadNotifyChips", "paintNtChips", "wireFollowup",
  "renderDetail", "renderNotSent",
  // renderNotSent calls this at the end of every render (the estimator picker on a project
  // nobody has sent). Omitting it made the whole panel a ReferenceError rather than a partial
  // render — which is the failure this harness exists to catch, so it caught its own gap.
  "wireNotSentAssign",
  // Sent versions, and the notification picker on an unsent project. Same gap as
  // wireNotSentAssign above: applySecPanel calls loadRevisions on the Proposal tab and
  // renderNotSent calls loadNotSentNotify at the end, so omitting either turns the whole panel
  // into a ReferenceError instead of a partial render — which is what this harness is for, and
  // it caught this the first time it ran.
  "loadRevisions", "paintRevisions", "downloadRevision",
  "loadNotSentNotify", "paintNotSentNotify",
];

// ── the DOM stub ─────────────────────────────────────────────────────────────
function makeDom() {
  const dom = {
    html: "",          // what was last written to #drawer
    parts: new Map(),  // every other innerHTML write, by element: the notify chips, the estimator
                       // select. Keyed and REPLACED rather than appended, or painting the chip
                       // strip twice (which is exactly what a tab switch back to Proposal does)
                       // would leave two of every chip in the bag and double every count.
    lookups: [],       // $() calls since the last #drawer paint
    paints: 0,
    focused: null,
    els: new Map(),
  };
  Object.defineProperty(dom, "extra",
    { get: () => Array.from(dom.parts.values()).join("") });
  const all = () => dom.html + dom.extra;

  // Every opening tag in the markup, with its attributes — so a stub element can carry the
  // data-* and href the renderer actually wrote. That matters more than it sounds: without it
  // `b.dataset.sec` is undefined inside applySecPanel and NO tab ever reads as selected, so the
  // aria contract of the strip would look broken while being fine, or fine while being broken.
  const OPEN = /<([a-zA-Z0-9]+)((?:\s+[-a-zA-Z0-9:_]+(?:="[^"]*")?)*)\s*\/?>/g;
  function tagsMatching(part) {
    const found = [];
    const src2 = all();
    OPEN.lastIndex = 0;
    let m;
    while ((m = OPEN.exec(src2))) {
      const attrs = {};
      const ar = /([-a-zA-Z0-9:_]+)(?:="([^"]*)")?/g;
      let a;
      while ((a = ar.exec(m[2] || ""))) attrs[a[1]] = a[2] === undefined ? "" : a[2];
      if (matchesTag(part, m[1], attrs)) found.push(attrs);
    }
    return found;
  }
  function matchesTag(part, tag, attrs) {
    if (part.startsWith(".")) return String(attrs.class || "").split(/\s+/).includes(part.slice(1));
    if (part.startsWith("#")) return attrs.id === part.slice(1);
    if (part.startsWith("[")) {
      const [k, v] = part.slice(1, -1).split("=");
      return v === undefined ? k in attrs : attrs[k] === v.replace(/^["']|["']$/g, "");
    }
    return tag.toLowerCase() === part.toLowerCase();
  }
  // No real ancestor test: a descendant selector is satisfied when each of its parts appears
  // somewhere. The drawer's selectors are ".dtabs .step" and ".dclose" over markup this file
  // renders itself, so the distinction cannot bite here — and it is written down rather than
  // discovered.
  const hasSimple = (part) => tagsMatching(part).length > 0;
  const parts = (sel) => sel.trim().split(/\s+/);

  function makeEl(key) {
    const classes = new Set();
    const el = {
      key,
      tagName: "DIV",
      dataset: {},
      style: {},
      attrs: {},
      listeners: {},
      textContent: "",
      value: "",
      href: "",
      disabled: false,
      hidden: false,
      tabIndex: 0,
      scrollTop: 0,
      scrollHeight: 0,
      clientHeight: 0,
      isContentEditable: false,
      _html: "",
      get innerHTML() { return this._html; },
      set innerHTML(v) {
        this._html = String(v);
        if (this.key === "#drawer") {
          dom.html = this._html;
          dom.parts.clear();
          dom.lookups.length = 0;   // a lookup only counts against the paint it is wiring
          dom.paints++;
          for (const k of Array.from(dom.els.keys())) if (k !== "#drawer") dom.els.delete(k);
        } else {
          dom.parts.set(this.key, this._html);
        }
      },
      classList: {
        add: (c) => classes.add(c),
        remove: (c) => classes.delete(c),
        contains: (c) => classes.has(c),
        toggle: (c, on) => { const v = on === undefined ? !classes.has(c) : !!on; v ? classes.add(c) : classes.delete(c); return v; },
      },
      cls: () => Array.from(classes),
      addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
      removeEventListener() {},
      setAttribute(k, v) { this.attrs[k] = String(v); },
      getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
      focus() { dom.focused = this.key; },
      querySelector(sel) { return dom.query(sel); },
      querySelectorAll(sel) { return dom.queryAll(sel); },
      closest() { return null; },
      fire(t, ev) { return Promise.all((this.listeners[t] || []).map((f) => f(ev || { target: this }))); },
    };
    return el;
  }

  /** Copy the rendered attributes onto a stub, once, when it is first handed out. */
  function seed(el, attrs) {
    if (!attrs) return el;
    el.attrs = Object.assign({}, attrs);
    for (const k of Object.keys(attrs)) {
      if (k.startsWith("data-")) {
        el.dataset[k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = attrs[k];
      }
    }
    if (attrs.href) el.href = attrs.href;
    if (attrs.class) attrs.class.split(/\s+/).filter(Boolean).forEach((c) => el.classList.add(c));
    if ("disabled" in attrs) el.disabled = true;
    if (attrs.id) el.id = attrs.id;
    return el;
  }

  dom.el = (key, attrs) => {
    if (!dom.els.has(key)) dom.els.set(key, seed(makeEl(key), attrs));
    return dom.els.get(key);
  };
  dom.query = (sel) => {
    const p = parts(sel);
    if (!p.every(hasSimple)) return null;
    return dom.el(sel, tagsMatching(p[p.length - 1])[0]);
  };
  dom.queryAll = (sel) => {
    const p = parts(sel);
    if (!p.slice(0, -1).every(hasSimple)) return [];
    const hits = tagsMatching(p[p.length - 1]);
    return hits.map((attrs, i) => dom.el(sel + "#" + i, attrs));
  };
  dom.getElementById = (id) => {
    const hit = tagsMatching("#" + id)[0];
    const present = !!hit || id === "drawer" || id === "scrim";
    dom.lookups.push({ id, present });
    if (!present) return null;
    return dom.el(id === "drawer" ? "#drawer" : "#" + id, hit);
  };
  return dom;
}

// ── fixtures: the shapes production actually serves ──────────────────────────
const URL_TOKEN = "gZ3liSuON-bK-jR37bxIb0psjkXmAKp8";
const PORTAL_URL = "https://portal.wetreadwell.com/p/" + URL_TOKEN;

const BOARD_ROWS = [
  { proposal_id: "combo", project_name: "Combo Test", proposal_status: "approved",
    approved_total: 22763.0, assigned_estimator: "kyle@wetreadwell.com", unread: 0 },
  { proposal_id: "sent", project_name: "Maple Street Warehouse", proposal_status: "sent",
    approved_total: 41250.0, assigned_estimator: "will@wetreadwell.com", unread: 2 },
  { proposal_id: "bare", project_name: "Threadbare" },
  { proposal_id: "notsent", project_name: "Cedar Ridge Distribution Center", not_sent: true,
    bid_total: 88000.0, drafted_at: "2026-08-09T12:00:00Z", estimator_email: "kyle@wetreadwell.com",
    customer_email: "dave@cedarridge.com" },
];

/** The drawer payload as /api/portal/proposal/<id> returns it. */
function payload(over) {
  return Object.assign({
    ok: true,
    proposal: {
      project_name: "Combo Test",
      customer_name: "HANZ URIEL A DE LA CRUZ",
      customer_email: "hdlcruz03@gmail.com",
      url: PORTAL_URL,
      proposal_status: "approved",
      deposit_status: "requested",
      deposit_required: true,
      deposit_requested_at: "2026-08-11T15:04:00Z",
      contacts_status: "pending",
      assigned_estimator: "kyle@wetreadwell.com",
      followup_state: { enrolled: true, enabled: true },
    },
    approval: { name: "HANZ URIEL A DE LA CRUZ", title: "Owner", date: "2026-08-10",
                options: ["Polish", "Epoxy"], total: 22763.0,
                approver_email: "hdlcruz03@gmail.com" },
    deposit_ref: "TW-4821",
    messages: [
      { msg_type: "system", body: "Approved by HANZ URIEL A DE LA CRUZ — Polish, Epoxy",
        author_kind: "staff", created_at: "2026-08-10T18:00:00Z" },
      { msg_type: "text", body: "Can you start the week of the 24th?", author_kind: "customer",
        author_email: "hdlcruz03@gmail.com", created_at: "2026-08-11T14:00:00Z" },
      { msg_type: "deposit_request", body: "Your deposit invoice is attached.",
        author_kind: "staff", created_at: "2026-08-11T15:04:00Z",
        meta: { amount: 5690.75, invoice_no: "23.150-01", reference: "TW-4821" } },
    ],
    contacts: [
      { role: "primary", name: "Dave Smith", email: "dave@x.com", phone: "(913) 555-0134" },
      { role: "accounts_payable", name: "Ann Boyle", email: "ap@x.com" },
    ],
    deposits: [],
    recipients: ["hdlcruz03@gmail.com"],
    recipient_activity: [{ email: "hdlcruz03@gmail.com", name: "Hanz", viewed_at: "2026-08-10T12:00:00Z",
                           approved: true }],
    followups: [
      { kind: "auto_email", created_at: "2026-08-09T12:00:00Z", detail: { template: "not_viewed", audience: "customer" } },
      { kind: "staff_call", created_at: "2026-08-10T12:00:00Z", by: "kyle@wetreadwell.com",
        detail: { note: "Left a voicemail" } },
    ],
    next_invoice_no: "23.150-02",
  }, over || {});
}

const SCENARIOS = {
  // An approved proposal with a deposit invoice out: the shape in Hanz's screenshot.
  approved: { pid: "combo", data: payload() },
  // Two recipients, money submitted and unconfirmed, contacts in. Exercises the recipients card,
  // the deposit submission card (incl. the masked account number) and the Confirm-it tab state.
  submitted: {
    pid: "combo",
    data: payload({
      proposal: Object.assign(payload().proposal, { deposit_status: "submitted",
        contacts_status: "received", deposit_amount: 5690.75 }),
      deposits: [{ method: "ach", account_name: "Cedar Ridge LLC", account_type: "checking",
                   routing_number: "101000187", account_number: "12345678901",
                   bank_name: "Commerce", submitted_at: "2026-08-12T02:14:00Z",
                   submitted_by: "ap@x.com", note: "Sent this morning" },
                 { method: "check", check_number: "4471", account_name: "Cedar Ridge LLC",
                   submitted_at: "2026-08-12T03:00:00Z", masked_ref: "••••8901" }],
      recipient_activity: [
        { email: "hdlcruz03@gmail.com", name: "Hanz", viewed_at: "2026-08-10T12:00:00Z",
          view_count: 3, last_viewed_at: "2026-08-11T12:00:00Z", replied: true, approved: true },
        { email: "ap@x.com", name: "Ann Boyle", paid: true, followups: false }],
    }),
  },
  // Sent, nobody has approved: no approval card, unread messages, and a total that must NOT be
  // called "Approved" in the head.
  sent: {
    pid: "sent",
    data: payload({
      proposal: { project_name: "Maple Street Warehouse", customer_name: "", customer_email: "dave@x.com",
                  url: PORTAL_URL, proposal_status: "sent", deposit_status: "pending",
                  contacts_status: "pending", followup_state: { enrolled: true, enabled: false } },
      approval: null, deposit_ref: null, contacts: [], deposits: [], recipient_activity: [],
      followups: [],
    }),
  },
  // Closed lost, no deposit wanted, and a payload stripped to almost nothing. This is the row
  // that catches a template assuming a field: a missing value must not print "undefined".
  //
  // Its url is a javascript: URL rather than an empty string, which does double duty. The panel
  // must fall back to "no customer link yet" (the same branch an absent url takes), and it must
  // never put that scheme in an href — esc() makes a value safe inside an attribute and says
  // nothing whatever about the scheme.
  bare: {
    pid: "bare",
    data: { ok: true, proposal: { project_name: "Threadbare", customer_email: "",
                                  url: "javascript:alert(document.cookie)",
                                  proposal_status: "closed_lost", deposit_required: false,
                                  followup_state: { closed_lost_reason: "price" } } },
  },
};

// ── the page's collaborators, stubbed at the edges only ──────────────────────
const dom = makeDom();
const clipboard = { impl: null };                 // swapped per clipboard scenario
const navigatorStub = { get clipboard() { return clipboard.impl; } };
const timers = [];                                // setTimeout, captured rather than scheduled
// The nine-person roster with only some of them on, which Hanz confirmed is deliberate, plus one
// override of each kind: `add` turns somebody on for this project alone and `mute` turns somebody
// off. Both directions matter — the effective state is the roster's answer OVERRIDDEN, and a
// mutation that reads only the roster or only the overrides passes if the fixture has one kind.
// One of the adds is the signed-in user, so the summary line's "including you" branch runs.
const NOTIFY = {
  ok: true,
  roster: ["dane", "greg", "hanz", "kyle", "kylene", "marisol", "rj", "tyler", "will"]
    .map((n, i) => ({ email: n + "@wetreadwell.com", enabled: i % 3 === 0 })),
  overrides: [{ email: "will@wetreadwell.com", mode: "add" },
              { email: "hanz@wetreadwell.com", mode: "add" },
              { email: "kyle@wetreadwell.com", mode: "mute" }],
};
const api = (p) => Promise.resolve({
  ok: true,
  json: () => Promise.resolve(p.includes("notify-overrides") ? NOTIFY
    : p.includes("estimators") ? { estimators: [{ email: "kyle@wetreadwell.com", name: "Kyle" }] }
    : { ok: true }),
});
const TW = {
  fmtBizDate: (v) => (v ? String(v).slice(0, 10) : ""),
  fmtBizDay: (v) => String(v || ""),
  fmtBizDateTime: (v) => String(v || "").replace("T", " ").slice(0, 16),
  bizToday: () => "2026-08-13",
  confirmDanger: () => Promise.resolve(false),
};
const windowStub = { TW, TWAuth: { user: () => ({ email: "hanz@wetreadwell.com", role: "admin" }) } };

const injected = [
  ["C", C],
  ...destructured,
  ["document", { getElementById: dom.getElementById, querySelector: dom.query,
                 querySelectorAll: dom.queryAll, addEventListener() {}, activeElement: null }],
  ["window", windowStub],
  ["TW", TW],
  ["navigator", navigatorStub],
  ["api", api],
  ["setTimeout", (f, ms) => { timers.push({ f, ms }); return timers.length; }],
  ["requestAnimationFrame", (f) => f()],            // synchronous, so the scroll logic runs
  ["closeDrawer", () => {}],
  ["openDetail", () => Promise.resolve()],
  ["load", () => Promise.resolve()],
  ["loadEstimators", () => Promise.resolve([{ email: "kyle@wetreadwell.com", name: "Kyle" }])],
  ["editInvoiceDialog", () => Promise.resolve(null)],
  ["lostReasonDialog", () => Promise.resolve(null)],
];

const body = `"use strict";
  ${LET_NAMES.map((n) => declSrc("let", n)).join("\n")}
  ${CONST_NAMES.map((n) => declSrc("const", n)).join("\n")}
  ${FN_NAMES.map(fnSrc).join("\n")}
  return {
    renderDetail, renderNotSent, focusSection, copyPortalLink,
    setBoard: (v) => { ALL = v; },
    open: (pid) => { CUR_PID = pid; ACTIVE_SEC = null; DRAWER_SIG = ""; },
    eligible: () => Array.from(SEC_ELIGIBLE),
    activeSec: () => ACTIVE_SEC,
    secTabs: () => SEC_TABS,
    allSecCards: () => ALL_SEC_CARDS,
    // Drive eligibility DIRECTLY, so a card can be present in the markup and still not eligible.
    // Every payload produces markup and eligibility together (an ineligible card renders as "" and
    // the DOM stub never creates an element for it), so no payload can put the two halves of
    // applySecPanel's condition in disagreement, and the SEC_ELIGIBLE half went unpinned: an
    // adversarial review deleted that half of the toggle and the whole suite stayed green.
    // NB no backticks in this string — it is inside a template literal.
    setEligible: (id, on) => setSecEligible(id, on),
  };`;

const page = new Function(...injected.map(([n]) => n), body)(...injected.map(([, v]) => v));
page.setBoard(BOARD_ROWS);

// ── run ──────────────────────────────────────────────────────────────────────
// secMap, not just the tab names: the python side needs to know which cards BELONG to a tab to
// assert that a tab shows those and only those. Read out of the running module, so it is the map
// applySecPanel actually consulted rather than a copy that can drift.
const out = { imported: destructured.map(([n]) => n), tabs: Object.keys(page.secTabs()),
  // The sent drawer's card ids. applySecPanel looks up every one of them to decide what to
  // hide and tolerates absence by design, so a panel that does not render them is not
  // "wiring an id it never rendered" — the not-sent test subtracts these.
  allSecCards: page.allSecCards(),
              secMap: page.secTabs(),
              scenarios: {}, clipboard: {}, notSent: {}, errors: {} };

/** What one tab looks like once focusSection has switched to it: which cards are on screen,
 *  which panel is, and which step reads as selected. Read off the classList the real
 *  applySecPanel toggled, not guessed from the markup. */
function tabState(sec) {
  page.focusSection(sec);
  const shown = [];
  for (const id of Object.values(page.secTabs()).flat()) {
    const el = dom.els.get("#" + id);
    if (el && !el.classList.contains("hidden")) shown.push(id);
  }
  const panels = Object.keys(page.secTabs())
    .filter((k) => { const el = dom.els.get("#dpanel-" + k); return el && !el.classList.contains("hidden"); });
  const steps = dom.queryAll(".dtabs .step")
    .filter((b) => b.getAttribute("aria-selected") === "true").length;
  return { shown, panels, selectedSteps: steps, focused: dom.focused };
}

async function tick() { await new Promise((r) => setImmediate(r)); }

async function runScenario(name, s) {
  page.open(s.pid);
  dom.paints = 0;
  page.renderDetail(s.pid, s.data);
  const firstPaints = dom.paints;
  const html = dom.html;
  const lookups = dom.lookups.slice();
  // BEFORE the tab walk below moves it. defaultSection answers "why is this drawer open?", and
  // ACTIVE_SEC is sticky within an open on purpose, so reading it after focusSection would only
  // ever report the last tab this harness clicked.
  const openedOn = page.activeSec();
  // Chips and the estimator select land on a microtask (both are fetches). Let them.
  await tick();
  await tick();
  // The masked account number, revealed and re-masked through the real handler. Bank numbers are
  // the one thing in this drawer that must not be in the markup until a human asks.
  const reveal = (() => {
    const b = dom.queryAll(".dep-show")[0];
    if (!b) return null;
    const cell = dom.els.get("#dep-acct-0") || dom.query("#dep-acct-0");
    b.fire("click");
    const shown = cell.textContent;
    b.fire("click");
    return { inMarkup: /12345678901/.test(html), shown, remasked: cell.textContent,
             label: b.textContent, pressed: b.getAttribute("aria-pressed") };
  })();
  const tabs = {};
  for (const sec of Object.keys(page.secTabs())) tabs[sec] = tabState(sec);
  // AFTER the walk, because the chips deliberately load only while the Proposal tab is on screen
  // ("so replying to a customer no longer costs a round-trip") — a drawer that opens on Chat has
  // no chips yet, and reading them before the walk reported an empty strip on three of four
  // fixtures. dom.extra survives a tab switch; only a drawer repaint clears it.
  await tick();
  const chips = dom.queryAll(".nt-chip");
  const notify = {
    count: chips.length,
    on: chips.filter((c) => c.classList.contains("on")).length,
    locked: chips.filter((c) => c.disabled).length,
    summary: (dom.els.get("#nt-count") || {}).textContent || "",
  };
  // Everything written into a node OTHER than the drawer, captured here rather than at the end:
  // the repaint checks below deliberately paint the drawer again, and that clears these. Leaving
  // it to the end reported an empty string, which quietly stopped the class-coverage assertion in
  // test_drawer_renders.py from ever seeing a chip.
  const written = dom.extra;
  // THE GUARD, EXECUTED. A second identical render must not touch the DOM: this is the
  // difference between the 12s poll being invisible and the drawer blinking four times a
  // minute, which is what Hanz reported on 2026-08-08.
  const before = dom.paints;
  page.renderDetail(s.pid, s.data);
  const repainted = dom.paints > before;
  // And a CHANGED payload must repaint, or the guard is just a freeze.
  const moved = JSON.parse(JSON.stringify(s.data));
  moved.proposal.contacts_status = "received";
  moved.proposal.project_name = String(moved.proposal.project_name || "") + " (renamed)";
  page.renderDetail(s.pid, moved);
  const repaintedOnChange = dom.paints > before + (repainted ? 1 : 0);

  return {
    paints: firstPaints,
    chars: html.length,
    html,
    written,
    eligible: page.eligible(),
    openedOn,
    notify,
    reveal,
    lookups,
    missing: lookups.filter((l) => !l.present).map((l) => l.id),
    tabs,
    repaintedOnIdenticalPayload: repainted,
    repaintedOnChange,
  };
}

(async () => {
  for (const [name, s] of Object.entries(SCENARIOS)) {
    try {
      out.scenarios[name] = await runScenario(name, s);
    } catch (e) {
      out.errors[name] = e.constructor.name + ": " + e.message + "\n" + (e.stack || "");
    }
  }

  // ── the not-sent panel ─────────────────────────────────────────────────────
  try {
    page.open("notsent");
    dom.paints = 0;
    const row = BOARD_ROWS.find((r) => r.proposal_id === "notsent");
    page.renderNotSent("notsent", row);
    const html = dom.html;
    const before = dom.paints;
    page.renderNotSent("notsent", row);
    out.notSent = { html, chars: html.length, paints: before,
                    repaintedOnIdenticalPayload: dom.paints > before,
                    missing: dom.lookups.filter((l) => !l.present).map((l) => l.id) };
    // ── the eligibility half of applySecPanel, which no payload can reach ──────
    // A card present in the markup but NOT eligible. Impossible to produce from a payload, because
    // an ineligible card renders as "" — so this drives setSecEligible directly, which is the only
    // way to put SEC_TABS and SEC_ELIGIBLE in disagreement and see which one applySecPanel obeys.
    const rich = SCENARIOS.submitted;
    page.open(rich.pid);
    page.renderDetail(rich.pid, rich.data);
    const everything = page.eligible();
    const withheld = "dsec-notify";                  // on the Proposal tab in every arrangement
    page.setEligible(withheld, false);               // markup stays, eligibility goes
    page.focusSection("proposal");
    const el = dom.els.get("#" + withheld);
    out.eligibilityHalf = {
      cardIsInTheMarkup: !!el,
      wasEligibleBefore: everything.indexOf(withheld) >= 0,
      hiddenWhenNotEligible: !!(el && el.classList.contains("hidden")),
      // The others on that tab must still be on screen, or this proves nothing except that
      // something broke.
      siblingsStillShown: Object.values(page.secTabs()).flat()
        .filter((id) => id !== withheld && page.secTabs().proposal.indexOf(id) >= 0)
        .filter((id) => { const e2 = dom.els.get("#" + id); return e2 && !e2.classList.contains("hidden"); }),
    };
  } catch (e) {
    out.errors.notSent = e.constructor.name + ": " + e.message + "\n" + (e.stack || "");
  }

  // ── copy to clipboard, every way it can go ─────────────────────────────────
  // The button replaced a URL a rep used to be able to select by hand, so a dead button here
  // means the customer's link is unreachable. Every branch has to end with a usable control.
  const btn = () => ({ textContent: "Copy the link" });
  const say = () => ({ textContent: "" });
  async function copyCase(impl) {
    clipboard.impl = impl;
    timers.length = 0;
    const b = btn(), s = say();
    const ok = await page.copyPortalLink(PORTAL_URL, b, s);
    // The label in TWO states, which is the whole behaviour: what it says the moment the copy
    // lands, and what it says once the reset timer has run. Reading it only after firing the
    // timers (the first version of this) made the confirmation invisible to the test — success and
    // failure both reported "Copy the link" and looked identical.
    const label = b.textContent;
    timers.forEach((t) => t.f());
    return { ok, label, said: s.textContent, timers: timers.length, afterTimers: b.textContent };
  }
  let copied = null;
  try {
    // FIRST, end to end: render, then fire the click the page itself wired. This is what proves
    // the button reaches the clipboard at all — copyPortalLink can be perfect while nothing calls
    // it — and that the URL it sends is the one off the anchor's href rather than a copy of the
    // token kept somewhere else in the markup.
    clipboard.impl = { writeText: (v) => { copied = v; return Promise.resolve(); } };
    page.open("combo");
    page.renderDetail("combo", SCENARIOS.approved.data);
    const wired = dom.query("[data-copy-portal]");
    await wired.fire("click");
    out.clipboard.wiredClick = { fired: !!wired, sent: copied,
                                 label: wired.textContent, said: (dom.els.get("#cust-copy-say") || {}).textContent };
    copied = null;
    out.clipboard.works = await copyCase({ writeText: (v) => { copied = v; return Promise.resolve(); } });
    out.clipboard.copiedValue = copied;
    out.clipboard.absent = await copyCase(null);
    out.clipboard.noWriteText = await copyCase({});
    out.clipboard.rejects = await copyCase({ writeText: () => Promise.reject(new Error("NotAllowedError")) });
    out.clipboard.throwsSync = await copyCase({ writeText: () => { throw new Error("boom"); } });
  } catch (e) {
    out.errors.clipboard = e.constructor.name + ": " + e.message;
  }

  console.log(JSON.stringify(out));
})();
