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
  // The resting-tab rule (2026-08-20), shared by BOTH renderers: defaultSection ends in it and
  // renderNotSent asks it directly. Fifth entry in this list added for the same reason as the four
  // below, and it would be the loudest: leaving it out is a ReferenceError inside defaultSection,
  // which every single render of either drawer goes through.
  "restingSection",
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
  // Closing an unsent bid lost (2026-08-19). Third time this list has had to grow for the same
  // reason: renderNotSent calls it unconditionally, so leaving it out is a ReferenceError for the
  // whole panel rather than a missing button. lostReasonDialog comes with it because the handler
  // awaits it.
  "wireNotSentLost", "lostReasonDialog",
  // Marking a project won by hand (2026-08-19). FOURTH time, and this pair is called from BOTH
  // renderers — wonControlHtml from renderNotSent and from followupPanelHtml, wireWon from
  // renderNotSent and from wireFollowup — so omitting either is a ReferenceError that takes out the
  // whole drawer on a sent project as well as an unsent one.
  "wonControlHtml", "wireWon",
  // The "customer opened it" card, synthesised from viewed_at/last_viewed_at (2026-08-20).
  // renderDetail builds the thread through it on EVERY payload, so leaving it out is a
  // ReferenceError for the whole drawer rather than a missing bubble.
  "withViewCard",
];

// openDetail, RENAMED so the module can hold both it and the stub the action helpers call.
//
// It is lifted because the ?sec= deep link lives in it and nowhere else: four lines that read the
// query string, gate the value against SEC_TABS and pre-set ACTIVE_SEC, which is the only thing
// that overrides defaultSection's routing. A source read cannot tell you whether the gate still
// runs before the render, and the routing changed on 2026-08-20 (Chat is now the resting tab), so
// the override had to become an executed claim.
//
// The rename is textual and touches the NAME only. Nothing inside it calls itself; the stub stays
// bound for `act()` and the reply button, which is what those really do in the browser — they
// re-enter through the same entry point, and a real re-entry here would fire a second fetch per
// click and make every won/deposit scenario depend on the network stub's payload.
const openDetailRealSrc = fnSrc("openDetail")
  .replace(/(^|\n)(\s*)async function openDetail\(/, "$1$2async function openDetailReal(");
if (!/function openDetailReal\(/.test(openDetailRealSrc)) {
  throw new Error("openDetail's declaration changed shape — the deep-link lift needs rewriting");
}

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
  // The Won-by-hand rows (2026-08-19). Separate from the four above so the click scenarios can
  // mutate them — the drawer patches the board row in place, which is the point — without changing
  // what every other scenario renders.
  { proposal_id: "wonsent", project_name: "Fairview Clinic", proposal_status: "sent" },
  { proposal_id: "marksent", project_name: "Northgate Fulfilment", proposal_status: "sent" },
  { proposal_id: "marknotsent", project_name: "Riverbend Logistics Hub", not_sent: true,
    bid_total: 41250.0, drafted_at: "2026-08-09T12:00:00Z", estimator_email: "kyle@wetreadwell.com" },
  { proposal_id: "paid", project_name: "Westport Retail Center", proposal_status: "approved" },
  // ── the view stamps (2026-08-20) ──
  // These live on the BOARD row and nowhere else: the portal's staff detail payload has no
  // viewed_at on `proposal` (checked against its own handler), so the drawer merges them off the
  // row exactly as it merges the won mark. Shaped after the real project Hanz was looking at:
  // sent 20:33, opened 20:36, and opened again the following afternoon.
  { proposal_id: "viewed", project_name: "Elmwood Cold Storage", proposal_status: "viewed",
    unread: 0, sent_at: "2026-08-18T20:33:55Z",
    viewed_at: "2026-08-18T20:36:04Z", last_viewed_at: "2026-08-19T14:02:00Z" },
  // Opened exactly once: first and last are the same stamp, so the card must NOT grow a "last
  // opened" footnote repeating the date beside it.
  { proposal_id: "viewedonce", project_name: "Brookfield Bakery", proposal_status: "viewed",
    unread: 0, viewed_at: "2026-08-18T20:36:04Z", last_viewed_at: "2026-08-18T20:36:04Z" },
  // Viewed AND the portal managed to write its own card — the post-2026-08-19 send. One bubble,
  // and it has to be the stored one, which names who opened it.
  { proposal_id: "viewedcard", project_name: "Ashford Plant", proposal_status: "viewed",
    unread: 0, viewed_at: "2026-08-18T20:36:04Z", last_viewed_at: "2026-08-19T14:02:00Z" },
  // Sent, and nobody has opened it. No stamps, no bubble.
  { proposal_id: "unviewed", project_name: "Larkspur Depot", proposal_status: "sent", unread: 0 },
  // Money in AND an unread message: the two top precedence rules against each other, which is the
  // only shape that can still prove the unread rule exists now that Chat is also the fallback.
  { proposal_id: "bothwait", project_name: "Halstead Cannery", proposal_status: "approved",
    unread: 2 },
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
  // ── the "customer opened it" card, from the timestamps (2026-08-20) ──────────
  // Two ordinary messages STRADDLING the view, because where the card lands is half the claim:
  // Hanz asked for a bubble in the conversation, and a bubble pinned to the top or the bottom
  // regardless of its date is not part of the conversation.
  viewed: {
    pid: "viewed",
    data: payload({
      proposal: { project_name: "Elmwood Cold Storage", customer_name: "Dave Nunn",
                  customer_email: "dave@elmwood.com", url: PORTAL_URL,
                  proposal_status: "viewed", deposit_status: "pending",
                  contacts_status: "pending", followup_state: { enrolled: true, enabled: true } },
      approval: null, contacts: [], deposits: [], recipient_activity: [], followups: [],
      messages: [
        { msg_type: "text", body: "Sending this over for the cold storage build.",
          author_kind: "staff", created_at: "2026-08-17T10:00:00Z" },
        { msg_type: "text", body: "Looks good, we will review it internally.",
          author_kind: "customer", author_email: "dave@elmwood.com",
          created_at: "2026-08-19T09:00:00Z" },
      ],
    }),
  },
  // Opened once. Same shape, one stamp.
  viewedOnce: {
    pid: "viewedonce",
    data: payload({
      proposal: { project_name: "Brookfield Bakery", customer_email: "ops@brookfield.com",
                  url: PORTAL_URL, proposal_status: "viewed", deposit_status: "pending",
                  contacts_status: "pending", followup_state: { enrolled: true, enabled: true } },
      approval: null, contacts: [], deposits: [], recipient_activity: [], followups: [],
      messages: [{ msg_type: "text", body: "Proposal attached.", author_kind: "staff",
                   created_at: "2026-08-17T10:00:00Z" }],
    }),
  },
  // The portal DID write its own view card (a send after 2026-08-19). Exactly one bubble must
  // render, and it has to be this one — it names who opened it, which the stamps cannot.
  viewedStoredCard: {
    pid: "viewedcard",
    data: payload({
      proposal: { project_name: "Ashford Plant", customer_email: "dave@ashford.com",
                  url: PORTAL_URL, proposal_status: "viewed", deposit_status: "pending",
                  contacts_status: "pending", followup_state: { enrolled: true, enabled: true } },
      approval: null, contacts: [], deposits: [], recipient_activity: [], followups: [],
      messages: [
        { msg_type: "text", body: "Proposal attached.", author_kind: "staff",
          created_at: "2026-08-17T10:00:00Z" },
        { msg_type: "system", body: "Dave opened the proposal.", author_kind: "staff",
          created_at: "2026-08-18T20:36:10Z", meta: { view: true, internal: true } },
      ],
    }),
  },
  // Sent, never opened. No stamps on the row, so no card at all.
  unviewed: {
    pid: "unviewed",
    data: payload({
      proposal: { project_name: "Larkspur Depot", customer_email: "ap@larkspur.com",
                  url: PORTAL_URL, proposal_status: "sent", deposit_status: "pending",
                  contacts_status: "pending", followup_state: { enrolled: true, enabled: true } },
      approval: null, contacts: [], deposits: [], recipient_activity: [], followups: [],
      messages: [{ msg_type: "text", body: "Proposal attached.", author_kind: "staff",
                   created_at: "2026-08-17T10:00:00Z" }],
    }),
  },
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
// Every request the drawer makes, recorded. WHICH endpoint a button posts to is a behavioural claim
// no source read settles — the won control has to reach the DRAFT route even on a sent project,
// because the portal has no column for the mark — and `fails` lets one scenario prove that a refused
// write does not leave the rep looking at a panel claiming it saved.
const net = { requests: [], fails: false };
// The drawer payload the lifted openDetail is served, set by the deep-link scenario. Only the
// bare detail GET reads it — every other path keeps the generic {ok:true} below, or a deposit
// request would answer with a whole proposal.
const detailFetch = { pid: null, data: null };
const isDetailGet = (p, init) =>
  !(init && init.method) && /^\/api\/portal\/proposal\/[^/]+$/.test(p);
const api = (p, init) => {
  net.requests.push({ path: p, method: (init && init.method) || "GET",
                      body: init && init.body ? JSON.parse(init.body) : null });
  if (isDetailGet(p, init) && detailFetch.data) {
    return Promise.resolve({ ok: true, status: 200,
                             json: () => Promise.resolve(detailFetch.data) });
  }
  if (net.fails) {
    return Promise.resolve({ ok: false, status: 500,
                             json: () => Promise.resolve({ error: "postgrest down" }) });
  }
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve(p.includes("notify-overrides") ? NOTIFY
      : p.includes("estimators") ? { estimators: [{ email: "kyle@wetreadwell.com", name: "Kyle" }] }
      : { ok: true }),
  });
};
const TW = {
  fmtBizDate: (v) => (v ? String(v).slice(0, 10) : ""),
  fmtBizDay: (v) => String(v || ""),
  fmtBizDateTime: (v) => String(v || "").replace("T", " ").slice(0, 16),
  bizToday: () => "2026-08-13",
  confirmDanger: () => Promise.resolve(false),
};
// Where the page tried to navigate. The drawer's "Open the files" and "Info sheet" buttons are
// <button>s that call window.location.assign, so the URL they send is only visible by firing the
// click the renderer wired — an href assertion would prove nothing about a button.
const nav = [];
const windowStub = { TW, TWAuth: { user: () => ({ email: "hanz@wetreadwell.com", role: "admin" }) },
                     location: { assign: (u) => nav.push(String(u)) } };
// The query string, for the lifted openDetail's ?sec= deep link. Mutated per scenario.
const locationStub = { search: "", assign: (u) => nav.push(String(u)) };

const injected = [
  ["C", C],
  ...destructured,
  ["document", { getElementById: dom.getElementById, querySelector: dom.query,
                 querySelectorAll: dom.queryAll, addEventListener() {}, activeElement: null }],
  ["window", windowStub],
  ["location", locationStub],
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
  ${openDetailRealSrc}
  return {
    renderDetail, renderNotSent, focusSection, copyPortalLink,
    // The real entry point, under its lifted name: the ?sec= deep link and the per-project
    // ACTIVE_SEC reset live in it.
    openDetail: openDetailReal,
    // defaultSection, driven directly. The precedence above the fallback is four conditions over
    // three fields, and since the fallback became "chat" a test that only reads the tab a drawer
    // opened on can no longer tell "unread won" from "nothing matched" — so the rules are
    // exercised one at a time, with the sticky value set explicitly.
    // The thread is the fourth argument on purpose: the resting tab now depends on whether there
    // is a conversation to land on, so a caller that leaves it out is asking "and what about a
    // project with nothing in its thread?" rather than accidentally testing a default.
    // NB no backticks in this comment either: it is inside a template literal.
    route: (p, unread, sticky, thread) => {
      ACTIVE_SEC = sticky || null;
      return defaultSection(p, unread, thread);
    },
    withViewCard: (msgs, p) => withViewCard(msgs, p),
    setBoard: (v) => { ALL = v; },
    open: (pid) => { CUR_PID = pid; ACTIVE_SEC = null; DRAWER_SIG = ""; },
    // DEEPLINK_USED is a page-LIFETIME latch, which is correct in the browser (one navigation, one
    // deep link) and makes a second ?sec= scenario impossible to run in one process. Reset is the
    // only honest way to drive the query-string gate twice: the alternative was a scenario that set
    // location.search and then called renderDetail, which never reads it, and proved nothing at all
    // while claiming to cover the whitelist.
    resetDeepLink: () => { DEEPLINK_USED = false; },
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
    // openDetail is stubbed in this harness, and it is what fills DETAIL_CACHE in the browser
    // (before it ever renders). The won control's repaint on a SENT project reads the cache back,
    // so a scenario has to stand in for that one line or it would be testing the stub.
    cache: (pid, data) => { DETAIL_CACHE[pid] = data; },
    // The board row a renderer merged from, read back out of the module: the won mark lives on it
    // and nowhere else on the client (see the merge at the top of renderDetail).
    row: (pid) => ALL.filter((x) => x.proposal_id === pid)[0] || null,
    sig: () => DRAWER_SIG,
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
              scenarios: {}, clipboard: {}, notSent: {}, won: {}, errors: {} };

/** What one tab looks like once focusSection has switched to it: which cards are on screen,
 *  which panel is, and which step reads as selected. Read off the classList the real
 *  applySecPanel toggled, not guessed from the markup. */
/** Which tab panels are on screen right now, read off the classList applySecPanel toggled.
 *  Separate from tabState because tabState CLICKS a tab first, and the deep-link scenarios need to
 *  see where a drawer landed on its own. */
function visiblePanels() {
  return Object.keys(page.secTabs()).filter((k) => {
    const el = dom.els.get("#dpanel-" + k);
    return el && !el.classList.contains("hidden");
  });
}

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
                    // WHICH tab this drawer landed on. It hard-codes its own landing tab (there is
                    // no portal payload for defaultSection to read), so it is the half of "Chat
                    // opens first" that the sent scenarios cannot speak for.
                    openedOn: page.activeSec(),
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

  // ── marking a project won, by hand, in BOTH drawers ────────────────────────
  // Hanz, 2026-08-19: "Is there any way to also mark as won for now other than after the deposit has
  // been received". Everything asserted here is behavioural: which route the button posts to, that
  // the panel it repaints into offers the undo, that the mark survives on the board row the next
  // poll will render from, and that a refused write claims nothing.
  try {
    /** Press one of the two won buttons and report what the drawer did about it. */
    async function pressWon(id) {
      net.requests.length = 0;
      const b = dom.getElementById(id);
      if (!b) return { pressed: false };
      b.textContent = id === "won-mark" ? "Mark won" : "Undo — not won yet";
      await b.fire("click");
      for (let i = 0; i < 6; i++) await tick();          // api() + .json() + the repaint
      return { pressed: true, requests: net.requests.slice(), html: dom.html,
               note: (dom.els.get("#won-note") || {}).textContent || "",
               label: b.textContent, disabled: b.disabled };
    }

    // ── the not-sent drawer ──
    page.open("marknotsent");
    const nsRow = page.row("marknotsent");
    page.renderNotSent("marknotsent", nsRow);
    out.won.notSentOffered = { html: dom.html };
    const nsMark = await pressWon("won-mark");
    out.won.notSentMarked = Object.assign({}, nsMark, { rowWonAt: (page.row("marknotsent") || {}).won_at,
                                                        sig: page.sig() });
    const nsUndo = await pressWon("won-undo");
    out.won.notSentUndone = Object.assign({}, nsUndo, { rowWonAt: (page.row("marknotsent") || {}).won_at });

    // ── the sent drawer: a project somebody already marked ──
    // won_at reaches this drawer ONLY through the board row (the portal payload has no such field),
    // so this is the merge at the top of renderDetail, executed.
    const wonRow = page.row("wonsent");
    wonRow.won_at = "2026-08-19T15:00:00+00:00";
    const wonData = payload({ proposal: { project_name: "Fairview Clinic", customer_email: "d@x.com",
                                          url: PORTAL_URL, proposal_status: "sent",
                                          deposit_status: "pending", contacts_status: "pending",
                                          followup_state: { enrolled: true, enabled: true } },
                              approval: null, contacts: [], deposits: [], recipient_activity: [],
                              followups: [] });
    page.open("wonsent");
    page.cache("wonsent", wonData);
    page.renderDetail("wonsent", wonData);
    out.won.sentAlreadyWon = { html: dom.html, merged: wonData.proposal.won_at };

    // ── the sent drawer: marking one from scratch ──
    const markData = payload({ proposal: { project_name: "Northgate Fulfilment",
                                           customer_email: "d@x.com", url: PORTAL_URL,
                                           proposal_status: "sent", deposit_status: "pending",
                                           contacts_status: "pending",
                                           followup_state: { enrolled: true, enabled: true } },
                               approval: null, contacts: [], deposits: [], recipient_activity: [],
                               followups: [] });
    page.open("marksent");
    page.cache("marksent", markData);
    page.renderDetail("marksent", markData);
    out.won.sentOffered = { html: dom.html };
    const sentMark = await pressWon("won-mark");
    out.won.sentMarked = Object.assign({}, sentMark, { rowWonAt: (page.row("marksent") || {}).won_at });

    // ── a refused write ──
    // The optimistic patch is the hazard in this design: the panel redraws from a row it patched
    // itself, so a failed save must leave the mark OFF the row as well as off the screen.
    const failRow = page.row("marknotsent");
    failRow.won_at = "";
    page.open("marknotsent");
    page.renderNotSent("marknotsent", failRow);
    net.fails = true;
    const failed = await pressWon("won-mark");
    net.fails = false;
    out.won.failed = Object.assign({}, failed, { rowWonAt: (page.row("marknotsent") || {}).won_at });

    // ── a closed-lost project offers nothing ──
    // Lost beats Won in every reader, so a Mark won press here would save and change nothing
    // visible, which reads as a broken control. Reactivate is the way back.
    page.open("bare");
    page.cache("bare", SCENARIOS.bare.data);
    page.renderDetail("bare", SCENARIOS.bare.data);
    out.won.lost = { html: dom.html };

    // ── a project won the DERIVED way says so, and offers no button ──
    const paidData = payload({ proposal: { project_name: "Westport Retail Center",
                                           customer_email: "d@x.com", url: PORTAL_URL,
                                           proposal_status: "approved",
                                           approved_at: "2026-07-20T10:00:00Z",
                                           deposit_status: "received", contacts_status: "pending",
                                           followup_state: { enrolled: true, enabled: true } },
                               contacts: [], deposits: [], recipient_activity: [], followups: [] });
    page.open("paid");
    page.cache("paid", paidData);
    page.renderDetail("paid", paidData);
    out.won.derived = { html: dom.html };
  } catch (e) {
    out.errors.won = e.constructor.name + ": " + e.message + "\n" + (e.stack || "");
  }

  // ── the routing rules, one at a time ──────────────────────────────────────
  // Chat became the fallback on 2026-08-20 ("In the opening of a project, Chat should be the tab
  // thats the first to appear"), which quietly made the old proof of the unread rule vacuous: a
  // drawer opening on Chat no longer distinguishes "a customer is waiting" from "nothing matched".
  // So each rule is put against the tab it has to BEAT.
  try {
    const P = (o) => Object.assign({ proposal_status: "sent", deposit_status: "pending" }, o || {});
    // A thread with something in it, and one with nothing. The resting tab depends on which of
    // these the project has: Chat is only worth landing on when there is a conversation there.
    const SOME = [{ msg_type: "text", body: "Can you start the 24th?", author_kind: "customer",
                    created_at: "2026-08-11T14:00:00Z" }];
    const NONE = [];
    out.route = {
      // Nothing waiting, and something to read → the conversation.
      quiet: page.route(P(), 0, null, SOME),
      // Nothing waiting and NOTHING TO READ → Proposal. This is the shape that made the unsent
      // drawer open on its own empty panel: landing on Chat is only right when Chat has content.
      quietNoThread: page.route(P(), 0, null, NONE),
      // A customer message beats an unconfirmed payment, which is the only pairing that can still
      // fail if the unread rule is deleted.
      unreadBeatsDeposit: page.route(P({ deposit_status: "submitted" }), 2, null, SOME),
      depositSubmitted: page.route(P({ deposit_status: "submitted" }), 0, null, SOME),
      // Both precedence rules AGAINST an empty thread, because the fallback is now the thing that
      // changes with the thread: a rule that only wins when there is a conversation to fall back to
      // is not above the fallback at all.
      unreadNoThread: page.route(P({ deposit_status: "submitted" }), 2, null, NONE),
      depositNoThread: page.route(P({ deposit_status: "submitted" }), 0, null, NONE),
      // Approved, nothing invoiced yet: contacts and the deposit are the next step.
      approvedNoRequest: page.route(P({ proposal_status: "approved" }), 0, null, SOME),
      // Approved but the invoice is already out, and one that never wanted a deposit: neither has
      // anything to action on that tab, so both fall through to the resting tab.
      approvedRequested: page.route(P({ proposal_status: "approved",
                                        deposit_requested_at: "2026-08-11T15:04:00Z" }), 0, null, SOME),
      approvedNoDeposit: page.route(P({ proposal_status: "approved", deposit_required: false }),
                                    0, null, SOME),
      // STICKY within an open: renderDetail re-runs after every action and a rep who just replied
      // must not be thrown back to Chat — or, now, off the tab they walked to.
      sticky: page.route(P({ deposit_status: "submitted" }), 2, "followup", SOME),
      // Sticky wins over the resting tab too, empty thread and all: a rep standing on Chat with
      // nothing in it (they are about to type) must not be walked to Proposal by the next poll.
      stickyChatNoThread: page.route(P(), 0, "chat", NONE),
    };
  } catch (e) {
    out.errors.route = e.constructor.name + ": " + e.message + "\n" + (e.stack || "");
  }

  // ── where the view card lands in the thread ───────────────────────────────
  // The markup section above proves it renders; this proves it lands in the right SLOT, which is
  // the part Hanz's wording was about ("a chat bubble ... in this chatbox"). Labels rather than
  // markup, so the failure names the order it got.
  try {
    const label = (m) => ((m.meta && m.meta.synthetic) ? "VIEW" : m.body);
    const msgs = [
      { msg_type: "text", body: "A", author_kind: "staff", created_at: "2026-08-17T10:00:00Z" },
      { msg_type: "text", body: "B", author_kind: "customer", created_at: "2026-08-19T09:00:00Z" },
    ];
    const both = { viewed_at: "2026-08-18T20:36:04Z", last_viewed_at: "2026-08-19T14:02:00Z" };
    const stored = msgs.concat([{ msg_type: "system", body: "Dave opened the proposal.",
                                 author_kind: "staff", created_at: "2026-08-18T20:36:10Z",
                                 meta: { view: true, internal: true } }]);
    out.insertion = {
      middle: page.withViewCard(msgs, both).map(label),
      // The slot has to MOVE with the stamp, or it is a fixed position dressed up as an order.
      earliest: page.withViewCard(msgs, { viewed_at: "2026-08-16T00:00:00Z" }).map(label),
      latest: page.withViewCard(msgs, { viewed_at: "2026-08-20T00:00:00Z" }).map(label),
      // "+00:00" against "Z". Both come out of Postgres isoformat(), and a string compare orders
      // them wrongly while looking perfectly reasonable.
      offsetForm: page.withViewCard(
        [{ msg_type: "text", body: "B", created_at: "2026-08-19T09:00:00+00:00" }],
        { viewed_at: "2026-08-18T20:36:04Z" }).map(label),
      // An unparseable stamp must not throw and must not jump the card to the top.
      junkStamp: page.withViewCard(
        [{ msg_type: "text", body: "A", created_at: "not a date" }], both).map(label),
      never: page.withViewCard(msgs, {}).map(label),
      // A stored card suppresses the synthetic one, whatever the stamps say.
      storedWins: page.withViewCard(stored, both).map(label),
      syntheticCount: page.withViewCard(stored, both).filter((m) => m.meta && m.meta.synthetic).length,
    };
  } catch (e) {
    out.errors.insertion = e.constructor.name + ": " + e.message + "\n" + (e.stack || "");
  }

  // ── a customer re-reading the proposal must not repaint an open drawer ─────
  // `last_viewed_at` is stamped by EVERY customer view, and renderDetail reads it off the board row
  // a few lines before it takes the signature. It used to be merged onto the payload there, which
  // put it in the signature: a customer reloading the page they were already sent moved it, and the
  // 12s poll then rebuilt the whole drawer, thread and tab strip and the caret of whoever was
  // mid-sentence in the reply box. That is the exact cost the signature exists to avoid, so the
  // exclusion is asserted from both sides here.
  //
  // EXECUTED, because which fields end up inside a signature is not something a source read
  // settles: the answer depends on what those lines above chose to write onto the payload, and the
  // stamps arrive from the BOARD ROW rather than from the payload the caller passes in.
  try {
    const row = page.row("viewed");
    const keep = { viewed_at: row.viewed_at, last_viewed_at: row.last_viewed_at };
    const data = JSON.parse(JSON.stringify(SCENARIOS.viewed.data));
    page.open("viewed");
    dom.paints = 0;
    page.renderDetail("viewed", data);
    const opened = dom.paints;                            // the open itself
    row.last_viewed_at = "2026-08-20T09:15:00Z";          // the customer opened it a third time
    page.renderDetail("viewed", data);
    const afterReread = dom.paints;
    // THE CONTROL, on the same payload one line later. A quiet drawer and a frozen one look
    // identical from the re-read half alone, so something a human IS waiting on has to still get
    // through: money in and unconfirmed.
    data.proposal.deposit_status = "submitted";
    page.renderDetail("viewed", data);
    const afterRealChange = dom.paints;
    // And the stamp is still READ, which is a different thing from being in the signature: the
    // repaint above must carry the NEW footnote, not the one from the first paint.
    const footnote = /last opened 2026-08-20 09:15/.test(dom.html);
    // ── the FIRST view is news ──
    // It is what draws the bubble, so `viewed_at` must NOT have been excluded alongside its
    // neighbour. A project nobody had opened, opened.
    const unrow = page.row("unviewed");
    const unkeep = { viewed_at: unrow.viewed_at, last_viewed_at: unrow.last_viewed_at };
    const un = JSON.parse(JSON.stringify(SCENARIOS.unviewed.data));
    page.open("unviewed");
    page.renderDetail("unviewed", un);
    const beforeFirstView = dom.paints;
    const bubbleBefore = /opened the proposal/.test(dom.html);
    unrow.viewed_at = "2026-08-20T09:15:00Z";
    page.renderDetail("unviewed", un);
    out.reread = {
      opened,
      repaintedOnReread: afterReread > opened,
      repaintedOnRealChange: afterRealChange > afterReread,
      footnote,
      bubbleBefore,
      repaintedOnFirstView: dom.paints > beforeFirstView,
      bubbleAfter: /opened the proposal/.test(dom.html),
    };
    // Restored: ALL is the board itself and the blocks below render these two projects again.
    Object.assign(row, keep);
    Object.assign(unrow, unkeep);
  } catch (e) {
    out.errors.reread = e.constructor.name + ": " + e.message + "\n" + (e.stack || "");
  }

  // ── the ?sec= deep link still wins ────────────────────────────────────────
  // A notification links straight to a tab (?open=<id>&sec=deposit). That override is the one
  // thing above defaultSection, it is consumed ONCE per page, and it lives in openDetail — so
  // this runs the real openDetail, LAST, because DEEPLINK_USED is a page-lifetime latch.
  try {
    const s = SCENARIOS.viewed;
    detailFetch.data = JSON.parse(JSON.stringify(s.data));
    locationStub.search = "?open=viewed&sec=deposit";
    await page.openDetail("viewed");
    for (let i = 0; i < 6; i++) await tick();
    const first = page.activeSec();
    // A SECOND open must not be dragged back to that tab: the latch is what stops the deep link
    // becoming a sticky preference for the rest of the session.
    detailFetch.data = JSON.parse(JSON.stringify(SCENARIOS.unviewed.data));
    await page.openDetail("unviewed");
    for (let i = 0; i < 6; i++) await tick();
    out.deepLink = { openedOn: first, secondProject: page.activeSec() };

    // ── a ?sec= naming a tab that does not exist ──
    // THROUGH openDetail, and that is the whole point of this scenario. The gate that ignores an
    // unknown value is `if (want && SEC_TABS[want])` inside openDetail and nowhere else; the first
    // version of this scenario set location.search and then called renderDetail, which never reads
    // the query string, so deleting `SEC_TABS[want]` from portal.js left the entire suite green.
    // resetDeepLink is needed because DEEPLINK_USED is a page-lifetime latch already spent above.
    locationStub.search = "?open=viewed&sec=nonsense";
    page.resetDeepLink();
    detailFetch.data = JSON.parse(JSON.stringify(s.data));
    page.open("viewed");
    await page.openDetail("viewed");
    for (let i = 0; i < 6; i++) await tick();
    out.deepLink.junkSec = page.activeSec();
    // Not merely "some tab": the state and the paint have to AGREE. An ungated value survives as
    // ACTIVE_SEC while applySecPanel quietly falls back to Proposal, so the drawer shows one tab
    // and the routing believes another, and defaultSection then returns the junk for the rest of
    // the open because ACTIVE_SEC is truthy.
    out.deepLink.junkPanels = visiblePanels();
    out.deepLink.junkSelected = dom.queryAll(".dtabs .step")
      .filter((b) => b.getAttribute("aria-selected") === "true").map((b) => b.dataset.sec);
    locationStub.search = "";
  } catch (e) {
    out.errors.deepLink = e.constructor.name + ": " + e.message + "\n" + (e.stack || "");
  }

  // ── the files and the info sheet, in BOTH drawers ─────────────────────────
  // Fired, not read: these are <button>s that call window.location.assign, so the URL only exists
  // at click time. A sent project had NEITHER control until 2026-08-20 — the board card was its
  // only route to its own paperwork.
  try {
    nav.length = 0;
    const s = SCENARIOS.viewed;
    page.open("viewed");
    page.renderDetail("viewed", JSON.parse(JSON.stringify(s.data)));
    const sentFiles = dom.getElementById("go-files");
    const sentInfo = dom.getElementById("go-info");
    if (sentFiles) await sentFiles.fire("click");
    if (sentInfo) await sentInfo.fire("click");
    const sentNav = nav.slice();

    nav.length = 0;
    const nsRow = BOARD_ROWS.find((r) => r.proposal_id === "notsent");
    page.open("notsent");
    page.renderNotSent("notsent", nsRow);
    const nsFiles = dom.query("[data-go-files]");
    const nsInfo = dom.query("[data-go-info]");
    const nsEdit = dom.query("[data-go-edit]");
    if (nsFiles) await nsFiles.fire("click");
    if (nsInfo) await nsInfo.fire("click");
    if (nsEdit) await nsEdit.fire("click");
    out.paperwork = {
      sent: { files: !!sentFiles, info: !!sentInfo, nav: sentNav },
      notSent: { files: !!nsFiles, info: !!nsInfo, edit: !!nsEdit, nav: nav.slice() },
    };
  } catch (e) {
    out.errors.paperwork = e.constructor.name + ": " + e.message + "\n" + (e.stack || "");
  }

  console.log(JSON.stringify(out));
})();
