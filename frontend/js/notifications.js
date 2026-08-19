// Externalized (CSP: no inline scripts). "Notification Sending" — who receives
// Customer Portal notification emails (approvals, replies, questions, deposits,
// contacts, customer email replies). Green = receives, gray = off.
//   • Team (global): the default roster for every project. Admins edit.
//   • Per-project: assign different people to a specific project; overrides the
//     global setting for that project only. Admins toggle anyone; other staff
//     may toggle only themselves (server-enforced). The same overrides also show
//     in the Customer Portal drawer — one source of truth.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const api = (path, opts) => fetch(path, Object.assign({ headers: TW.authHeaders() }, opts || {}));
  // Names and avatar colours come from crm-core, the one place that decides them, so a
  // person on this roster looks the same as they do on a CRM card or a Projects row.
  const nameOf = window.TWCrm.nameOf;
  const avatar = window.TWCrm.avatarHtml;
  /** The same chip, but with the identity colour taken OUT — for the per-project toggles
   *  below, where green already means "receives this project's email". A purple Alejandro
   *  next to a green Hanz leaves "green" ambiguous: is it the state or is it just him? So
   *  state owns colour on that control and the initials carry who it is. esc() because
   *  initials follow whatever string we were handed, not a whitelist. */
  const plainAvatar = (who) =>
    '<span class="nt-av" aria-hidden="true">' + (esc(window.TWCrm.initialsOf(who)) || "—") + "</span>";

  // The one place that decides what a project IS — the same module the CRM board reads, so
  // "test", "lost" and "deposit settled" cannot mean one thing there and another here.
  const C = window.TWCrm;

  let ADMIN = false, MY_EMAIL = "";
  let ROSTER = [];                 // [{email, enabled}] — the GENERAL rows: the global base
  let DEPOSIT_EXTRAS = [];         // [{email, enabled}] — deposit-kind rows, ADDITIVE to ROSTER
  let PROJECTS = [];               // [{proposal_id, project_name, customer_email, ...}]
  let OVERRIDES = {};              // { proposal_id: { emailLower: 'add'|'mute' } }

  // ── The two roster groups ───────────────────────────────────────────────────
  // A roster row carries a `kind`. A GENERAL alert resolves to the enabled general rows; a
  // DEPOSIT alert resolves to those PLUS the enabled deposit rows, deduped. Additive, not a
  // swap — a swapping rule would cut the whole team off deposits the moment the first
  // deposit-only person was added, and nothing on screen would have said so.
  //
  // WHY THIS SECOND CARD EXISTS. This page filtered the roster to general rows, so kylene@ —
  // live as an enabled deposit row — was configuration nobody could see or change from the UI,
  // and the next person like her needed SQL. Config you cannot see is config that rots.
  //
  // ONE CARD, BUILT TWICE, parameterised by kind: the toggle, the remove and the add all hit the
  // same kind-agnostic endpoints, so a second hand-written card would only be a second place to
  // fix the same bug. Rejected alternative: one list with a "deposits only" checkbox per chip.
  // `kind` is half the row's unique key, so flipping it in place is a delete plus an insert —
  // a half-failed pair leaves somebody silently unnotified, and a checkbox hides that.
  const GROUPS = [{
    kind: "general", other: "deposit",
    lbl: "Team — global default (all projects)",
    intro: "Everyone here gets every notification, deposits included.",
    what: "the team", also: "also on deposits",
    addLbl: "Add someone",
    empty: "No one on the list yet.",
    removeTitle: "Remove from notifications?",
    removeBefore: "Stop sending Customer Portal notifications to ",
    // Said out loud because these are two separate rows: removing this one leaves the other
    // standing, and somebody who believes they just removed both stops looking.
    removeAlso: "? Their deposit row stays, so they keep getting the three deposit emails.",
    chips: "nn-chips", input: "nn-email", btn: "nn-add", alert: "nn-alert",
  }, {
    kind: "deposit", other: "general",
    lbl: "Deposit alerts — in addition to the team above",
    intro: "These people also hear about deposits: the invoice going out, the customer sending " +
      "payment details, and a deposit marked received. They get nothing else — no approvals, " +
      "replies, questions or contacts. This list adds to the team above rather than replacing it, " +
      "so everyone up there keeps getting deposit emails too.",
    what: "deposit alerts", also: "also on the team",
    addLbl: "Add someone to deposit alerts",
    // A deliberate state, not a broken panel: an empty list here means "nobody EXTRA", and the
    // team above is still told. "No one on the list yet" would read as nobody being told at all.
    empty: "Nobody extra is told about deposits — the team above still gets them.",
    removeTitle: "Remove from deposit alerts?",
    removeBefore: "Stop sending deposit alerts to ",
    removeAlso: "? They stay on the team list above, which gets deposit emails too.",
    chips: "nn-depchips", input: "nn-depemail", btn: "nn-depadd", alert: "nn-depalert",
  }];

  /** Which group a row belongs to. Anything that is not "deposit" is general — the same call the
   *  portal's own resolver makes when it buckets the rows, so a row with a missing or
   *  unrecognised kind lands on a card somebody can see and remove. Filtering such a row out
   *  is precisely the failure this card exists to end. */
  const kindOf = (row) => (row && row.kind === "deposit" ? "deposit" : "general");

  const listFor = (kind) => (kind === "deposit" ? DEPOSIT_EXTRAS : ROSTER);

  /** Is this address on the OTHER list too? A row's unique key is kind + email, so both at once
   *  is legal and means "everything, deposits included" — not a duplicate and not a conflict.
   *  It only ever adds a label to the chip and a sentence to the remove dialog. */
  const onList = (kind, email) => listFor(kind)
    .some((m) => m.email.toLowerCase() === String(email || "").trim().toLowerCase());

  // ── per-project categories + paging ─────────────────────────────────────────
  // Hanz, 2026-08-19: "the per project Notification sending should be separate for active and
  // test projects", "for it not to populate the per projects tab there should also be a lost,
  // won category for that. Where it moves the project to there", "add a pagination".
  //
  // One flat list of every project the portal knows about was the complaint: scratch bids,
  // dead deals and finished work all sat in the working list, and it only ever grew.
  //
  // Won sits beside Active because both are news worth reading; Test is at the far end, which
  // is the order Hanz asked for on the CRM board on 2026-08-15 ("Active and Lost are both real
  // work, so they read together and the scratch tab sits at the far end").
  const PP_TABS = [["active", "Active"], ["won", "Won"], ["lost", "Lost"], ["test", "Test"]];
  const PP_IDS = PP_TABS.map((t) => t[0]);
  const PP_LABEL = {};
  PP_TABS.forEach((t) => { PP_LABEL[t[0]] = t[1]; });
  const PP_PER_PAGE = 10;
  const PP_TAB_KEY = "tw_notify_pp_tab", PP_PAGE_KEY = "tw_notify_pp_page";
  // sessionStorage, exactly as the CRM board keeps its own tab: a chip toggle re-renders the
  // list, and reaching for the same person on page 3 of Won after every click is the bug.
  const ss = (k, d) => { try { return sessionStorage.getItem(k) || d; } catch (e) { return d; } };
  const ssSet = (k, v) => { try { v ? sessionStorage.setItem(k, String(v)) : sessionStorage.removeItem(k); } catch (e) {} };
  let PP_TAB = PP_IDS.indexOf(ss(PP_TAB_KEY, "")) >= 0 ? ss(PP_TAB_KEY, "") : "active";
  let PP_PAGE = Math.max(1, parseInt(ss(PP_PAGE_KEY, "1"), 10) || 1);

  // Won and Lost both come from crm-core, which is the point. Hanz, 2026-08-19: "CRM lost and won
  // should also tie up to the notification sending okay?" — isWon used to live in this file, the one
  // page with a Won tab, and a local copy is how two screens end up disagreeing about a word Troy
  // reads as a number. The reasoning behind the predicate is documented at its definition.
  const isWon = C.isWon;

  /** Exactly one category per project. The ORDER is the whole content of this function.
   *
   *  LOST FIRST, above Test, because that is what the CRM board does: crm-core's stage() returns
   *  Closed lost before it looks at anything else, and portal.js's boardPool puts a lost test
   *  project on the Lost tab carrying a Test chip. Two screens disagreeing about where a dead deal
   *  lives is worse than either answer, so this page copies the board and carries the same chip.
   *
   *  TEST ABOVE WON, because a test project's outcome is fiction. Won is a number a human reads as
   *  real work, and somebody's scratch bid must not be able to inflate it. The board agrees here
   *  too — it has no Won tab, and a won test project sits on its Test tab.
   *
   *  ACTIVE IS THE REMAINDER, never a predicate of its own. That is what makes these four a
   *  partition: a project the categories don't recognise lands in the working list, where someone
   *  will see it, rather than in no tab at all. */
  function ppCategory(p) {
    if (C.isLost(p)) return "lost";
    if (C.isTest(p)) return "test";
    if (isWon(p)) return "won";
    return "active";
  }

  /** Counted THROUGH ppCategory, never by re-testing the predicates: a pill must not be able to
   *  advertise a number the tab then refuses to show. */
  function ppCounts(rows) {
    const n = {};
    PP_IDS.forEach((id) => { n[id] = 0; });
    rows.forEach((p) => { n[ppCategory(p)]++; });
    return n;
  }

  function ppPageCount(total) { return Math.max(1, Math.ceil(total / PP_PER_PAGE)); }

  function ppSlice(rows, page) {
    const start = (Math.max(1, page) - 1) * PP_PER_PAGE;
    return rows.slice(start, start + PP_PER_PAGE);
  }

  function ppMatches(p, q) {
    return !q ||
      String(p.project_name || "").toLowerCase().includes(q) ||
      String(p.customer_email || "").toLowerCase().includes(q);
  }

  function ppGoto(page) {
    PP_PAGE = Math.max(1, page);
    ssSet(PP_PAGE_KEY, PP_PAGE);
    renderProjects();
  }

  async function boot() {
    try { await window.TWAuth.ready; } catch (e) { /* auth.js handles redirect */ }
    const me = (window.TWAuth && window.TWAuth.user && window.TWAuth.user()) || {};
    ADMIN = me.role === "admin" || me.role === "super_admin";
    MY_EMAIL = (me.email || "").toLowerCase();
    render();
    await load();          // global roster (also fills ROSTER)
    await loadProjects();  // per-project card
  }

  /** One roster card. Both groups render through here rather than through two blocks of
   *  hand-written markup, so the deposit list is the same control as the team list — same chip,
   *  same green = receives / grey = off, same Add field, same × — and cannot drift into being
   *  a second, subtly different thing. */
  function rosterCardHtml(g) {
    return '<div class="card">' +
      '<div class="lbl">' + g.lbl + '</div>' +
      '<p class="note" style="margin:0 0 10px">' + g.intro + '</p>' +
      '<div id="' + g.alert + '" class="alert"></div>' +
      '<div id="' + g.chips + '" class="chips"><span class="note">Loading…</span></div>' +
      (ADMIN
        // aria-label on both, because two identical "Add" buttons on one page are
        // indistinguishable to anyone reading it through a screen reader's control list.
        ? '<div style="margin-top:16px"><div class="lbl">' + g.addLbl + '</div>' +
          '<div class="addrow"><input id="' + g.input + '" type="email" placeholder="name@wetreadwell.com"' +
          ' autocomplete="off" aria-label="' + g.addLbl + '" />' +
          '<button class="btn btn-p" id="' + g.btn + '" type="button" aria-label="' + g.addLbl + '">Add</button></div></div>'
        : '<p class="note" style="margin-top:12px">Only admins can change this list — ask an admin to add or toggle someone.</p>') +
    '</div>';
  }

  function render() {
    $("root").innerHTML =
      '<h1>Notification Sending</h1>' +
      '<p class="sub">Who gets emailed when a customer approves, replies, asks a question, or submits a deposit or contacts. ' +
      'Green = receives; gray = off. <strong>Toggling a name never sends an email.</strong> It only sets who gets ' +
      'notified the next time a customer replies, approves, or pays.</p>' +
      GROUPS.map(rosterCardHtml).join("") +
      '<div class="card">' +
        '<div class="lbl">Per-project — assign specific people</div>' +
        '<p class="note" style="margin:0 0 8px">Green = receives THIS project’s emails. Overrides the team list above for that project only. ' +
        (ADMIN ? "Toggle anyone." : "You can toggle only yourself.") + '</p>' +
        // The decision, on screen, so nobody has to read peopleFor() to find out.
        '<p class="note" style="margin:0 0 8px">Only the team list is shown here — deposit-only people are not. ' +
        'A per-project toggle covers every email that project sends, and an override is stored by address with no kind, ' +
        'so switching a deposit-only person on here would sign them up for approvals and replies as well.</p>' +
        '<input id="pp-search" type="search" class="pp-search" placeholder="Filter by project or customer…" />' +
        // Static markup, updated in place by syncPpTabs/syncPpPager rather than re-rendered:
        // pressing a pill or Next repaints the list under it, and replacing the node you just
        // pressed throws away the keyboard focus that got you there.
        '<div id="pp-tabs" class="tw-tabs">' +
          PP_TABS.map((t) => '<button type="button" class="tw-tab" data-pptab="' + t[0] + '"'
            + ' aria-pressed="false">' + t[1] + ' <span class="n">0</span></button>').join("") +
        '</div>' +
        '<div id="pp-alert" class="alert"></div>' +
        '<div id="pp-list"><span class="note">Loading…</span></div>' +
        '<nav id="pp-pager" class="pp-pager" hidden aria-label="Project pages">' +
          '<button type="button" class="pp-pg" id="pp-prev">‹ Prev</button>' +
          // aria-live so the page you just moved to is ANNOUNCED; without it the only feedback
          // for a keyboard user is a list they cannot see changing under them.
          '<span class="pp-pgn" id="pp-pgn" aria-live="polite"></span>' +
          '<button type="button" class="pp-pg" id="pp-next">Next ›</button>' +
        '</nav>' +
      '</div>';
    if (ADMIN) {
      GROUPS.forEach((g) => {
        $(g.btn).addEventListener("click", () => addEmail(g));
        $(g.input).addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addEmail(g); } });
      });
    }
    // Typing narrows the pool, so page 3 of the old pool is meaningless — back to the first.
    $("pp-search").addEventListener("input", () => ppGoto(1));
    $("pp-tabs").addEventListener("click", (e) => {
      const b = e.target.closest("[data-pptab]");
      if (!b || b.dataset.pptab === PP_TAB) return;
      // Against the known set, not trusted from the attribute: an unrecognised tab must fall
      // back to the working list rather than filter everything out and blank the card.
      PP_TAB = PP_IDS.indexOf(b.dataset.pptab) >= 0 ? b.dataset.pptab : "active";
      ssSet(PP_TAB_KEY, PP_TAB);
      ppGoto(1);                                   // a new category starts at its first page
    });
    $("pp-prev").addEventListener("click", () => ppGoto(PP_PAGE - 1));
    $("pp-next").addEventListener("click", () => ppGoto(PP_PAGE + 1));
  }

  function alertOf(g, kind, msg) { const a = $(g.alert); if (a) { a.className = "alert " + kind; a.textContent = msg || ""; } }
  function ppAlert(kind, msg) { const a = $("pp-alert"); if (a) { a.className = "alert " + kind; a.textContent = msg || ""; } }

  // ── Global roster cards: the team, and the deposit-only extras ──────────────
  /** One group's chips, from the rows the API returned for its kind. Identical markup and
   *  handlers for both groups — a deposit chip toggles and removes through the same
   *  kind-agnostic row-id endpoints as a team chip, because that is what the API offers. */
  function paintGroup(g, rows) {
    const wrap = $(g.chips);
    if (!wrap) return;
    wrap.innerHTML = rows.map((x) => {
      const on = x.enabled !== false;
      // The same address may legitimately sit on both lists. Labelled rather than flagged: it
      // is a choice ("everything, deposits included"), and an unexplained twin reads as a bug
      // somebody will "fix" by deleting one of them.
      const both = onList(g.other, x.email);
      return '<span class="chip ' + (on ? "on " : "") + (ADMIN ? "can" : "") + '" data-id="' + esc(x.id) + '" data-on="' + (on ? 1 : 0) + '"'
           + ' data-kind="' + esc(g.kind) + '"' + (ADMIN ? ' role="button" tabindex="0"' : "") + '>'
           + avatar(x.email) + esc(nameOf(x.email)) + ' <span class="em">' + esc(x.email) + '</span>'
           + (both ? ' <span class="also">' + esc(g.also) + '</span>' : "")
           + (ADMIN ? ' <button class="x" title="Remove" aria-label="Remove">&times;</button>' : "")
           + '</span>';
    }).join("") || '<span class="note">' + g.empty + (ADMIN ? " Add someone below." : "") + '</span>';
    if (ADMIN) {
      wrap.querySelectorAll(".chip").forEach((c) => {
        const id = c.dataset.id, on = c.dataset.on === "1";
        c.addEventListener("click", (e) => { if (e.target.classList.contains("x")) return; toggle(id, !on, c, g); });
        const x = c.querySelector(".x");
        if (x) x.addEventListener("click", (e) => { e.stopPropagation(); removeOne(id, c, g); });
      });
    }
  }

  async function load() {
    try {
      const r = await api("/api/portal/notify-recipients");
      const j = await r.json();
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      const rows = j.recipients || [];
      const byKind = {};
      GROUPS.forEach((g) => { byKind[g.kind] = rows.filter((x) => kindOf(x) === g.kind); });
      const asList = (k) => byKind[k].map((x) => ({ email: x.email, enabled: x.enabled !== false }));
      // Both module lists first, THEN paint: a chip's "also on…" label asks about the other
      // group, so painting group one before group two's list existed would silently drop it.
      ROSTER = asList("general");
      DEPOSIT_EXTRAS = asList("deposit");
      GROUPS.forEach((g) => { paintGroup(g, byKind[g.kind]); alertOf(g, "", ""); });
    } catch (err) {
      // Both cards say so. One card reading "Could not load" beside another still showing
      // "Loading…" would look like a half-working page rather than one failed fetch.
      GROUPS.forEach((g) => {
        const wrap = $(g.chips);
        if (wrap) wrap.innerHTML = '<span class="note">Could not load: ' + esc(err.message) + '</span>';
      });
    }
  }

  async function toggle(id, enabled, chip, g) {
    if (chip) chip.style.opacity = ".5";
    try {
      const r = await api("/api/portal/notify-recipients/" + encodeURIComponent(id),
        { method: "PATCH", body: JSON.stringify({ enabled }) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      await load(); renderProjects();   // roster base changed → per-project effective states shift
    } catch (err) { alertOf(g, "err", "Could not update: " + (err.message || "retry")); if (chip) chip.style.opacity = ""; }
  }

  async function addEmail(g) {
    const email = ($(g.input).value || "").trim().toLowerCase();
    if (!email) { alertOf(g, "err", "Enter an email address."); return; }
    const btn = $(g.btn); btn.disabled = true; btn.textContent = "Adding…";
    try {
      const r = await api("/api/portal/notify-recipients",
        // The kind of the field it was typed into. The proxy defaults a missing kind to
        // "general", so a dropped field here would quietly create the wrong sort of row.
        { method: "POST", body: JSON.stringify({ email, kind: g.kind }) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      $(g.input).value = "";
      await load(); renderProjects();
      alertOf(g, "ok", "Added " + email + " to " + g.what + " — it's off (gray). Click it to turn green and start sending.");
    } catch (err) { alertOf(g, "err", "Could not add: " + (err.message || "retry")); }
    finally { btn.disabled = false; btn.textContent = "Add"; }
  }

  async function removeOne(id, chip, g) {
    const em = chip.querySelector(".em");
    const who = em ? em.textContent : "this person";
    const ok = await TW.confirmDanger({
      title: g.removeTitle, before: g.removeBefore, name: who,
      // Two rows, two ids: removing one leaves the other, and the dialog has to say which.
      after: onList(g.other, who) ? g.removeAlso : "?",
      confirmText: "Remove", tone: "danger",
    });
    if (!ok) return;
    try {
      const r = await api("/api/portal/notify-recipients/" + encodeURIComponent(id), { method: "DELETE" });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      await load(); renderProjects();
    } catch (err) { alertOf(g, "err", "Could not remove: " + (err.message || "retry")); }
  }

  // ── Per-project card ────────────────────────────────────────────────────────
  async function loadProjects() {
    try {
      const [rp, ro] = await Promise.all([
        api("/api/portal/pipeline"),
        api("/api/portal/notify-overrides-all"),
      ]);
      const jp = await rp.json(), jo = await ro.json();
      if (!rp.ok || jp.ok === false) throw new Error(jp.error || jp.detail || ("HTTP " + rp.status));
      if (!ro.ok || jo.ok === false) throw new Error(jo.error || jo.detail || ("HTTP " + ro.status));
      PROJECTS = jp.proposals || [];
      OVERRIDES = {};
      (jo.overrides || []).forEach((o) => {
        (OVERRIDES[o.proposal_id] = OVERRIDES[o.proposal_id] || {})[String(o.email).toLowerCase()] = o.mode;
      });
      renderProjects();
    } catch (err) {
      $("pp-list").innerHTML = '<span class="note">Could not load projects: ' + esc(err.message) + '</span>';
    }
  }

  // Roster members + any override-only emails (someone 'add'ed who isn't on the roster).
  //
  // GENERAL ROWS ONLY — deposit-only people are deliberately absent, and the card says so on
  // screen. A per-project chip is one on/off that governs everything that project emails, and an
  // override is stored as (proposal_id, email, mode) with no kind at all: switching a
  // deposit-only person green here would union their address into that project's general
  // recipients too, quietly promoting somebody who was added for three deposit emails into
  // approvals, replies and questions. Rejected alternative: show them with their chip disabled —
  // a row of permanently dead chips invites exactly the "why can't I click this" that a sentence
  // answers better.
  function peopleFor(pid) {
    const ov = OVERRIDES[pid] || {};
    const seen = {}, people = [];
    ROSTER.forEach((m) => { const e = m.email.toLowerCase(); seen[e] = 1; people.push({ email: m.email, base: m.enabled }); });
    Object.keys(ov).forEach((e) => { if (!seen[e]) people.push({ email: e, base: false }); });
    return people;
  }

  /** The pills, updated in place. Counts follow the SEARCH, not the raw list, because the search
   *  box sits directly above them: a pill reading 40 that then shows 2 rows is describing a list
   *  nobody can see. */
  function syncPpTabs(counts) {
    const wrap = $("pp-tabs");
    if (!wrap) return;
    wrap.querySelectorAll("[data-pptab]").forEach((b) => {
      const on = b.dataset.pptab === PP_TAB;
      b.setAttribute("aria-pressed", on ? "true" : "false");
      const c = b.querySelector(".n");
      if (c) c.textContent = counts[b.dataset.pptab] || 0;
    });
  }

  /** Hidden at one page: "Page 1 of 1" beside two dead buttons is noise on the common case. */
  function syncPpPager(total, pages) {
    const nav = $("pp-pager");
    if (!nav) return;
    nav.hidden = pages < 2;
    const n = $("pp-pgn");
    if (n) n.textContent = "Page " + PP_PAGE + " of " + pages
      + " · " + total + " project" + (total === 1 ? "" : "s");
    const prev = $("pp-prev"), next = $("pp-next");
    if (prev) prev.disabled = PP_PAGE <= 1;
    if (next) next.disabled = PP_PAGE >= pages;
  }

  function ppRowHtml(p) {
    const pid = p.proposal_id;
    const ov = OVERRIDES[pid] || {};
    const custom = Object.keys(ov).length;
    // The only tab that needs the tag: Lost holds every dead deal, scratch ones included (see
    // ppCategory), so it is the one place test and real work sit side by side. On the other three
    // the tab IS the label — the same call the CRM board makes on its own Lost cards.
    const tag = (PP_TAB === "lost" && C.isTest(p))
      ? '<span class="pp-badge pp-badge-test">Test</span>' : "";
    const chips = peopleFor(pid).map((person) => {
      const e = person.email.toLowerCase();
      const mode = ov[e];
      const eff = mode === "add" ? true : mode === "mute" ? false : person.base;
      const canEdit = ADMIN || e === MY_EMAIL;
      return '<button class="nt-chip ' + (eff ? "on" : "") + '" data-pid="' + esc(pid) + '" data-email="' + esc(person.email) + '"'
           + ' data-base="' + (person.base ? 1 : 0) + '" data-eff="' + (eff ? 1 : 0) + '"'
           + (canEdit ? "" : " disabled") + ' title="' + esc(person.email) + '">'
           + plainAvatar(person.email) + esc(nameOf(person.email)) + '</button>';
    }).join("");
    return '<div class="pp-row">' +
      '<div class="pp-head"><span class="pp-name">' + esc(p.project_name || "Proposal") + '</span>' +
      '<span class="pp-cust">' + esc(p.customer_email || "") + '</span>' + tag +
      (custom ? '<span class="pp-badge">' + custom + ' custom</span>' : "") +
      (ADMIN && custom ? '<button class="pp-reset" data-pid="' + esc(pid) + '" type="button">Reset to global</button>' : "") +
      '</div><div class="nt-chips">' + chips + '</div></div>';
  }

  function renderProjects() {
    const list = $("pp-list");
    if (!list) return;
    const q = ($("pp-search").value || "").toLowerCase().trim();
    const matched = PROJECTS.filter((p) => ppMatches(p, q));
    syncPpTabs(ppCounts(matched));
    const pool = matched.filter((p) => ppCategory(p) === PP_TAB);
    const pages = ppPageCount(pool.length);
    // Clamped on the way OUT, not only when a tab or the search changes: a project that just
    // moved category — someone's deposit landed — can shorten the pool under a page you are
    // already standing on, and a silently blank list reads as a broken page.
    if (PP_PAGE > pages) { PP_PAGE = pages; ssSet(PP_PAGE_KEY, PP_PAGE); }
    syncPpPager(pool.length, pages);
    if (!pool.length) {
      // Three different kinds of empty, three different answers: nothing loaded at all, this
      // category is genuinely empty, or the search hid it. Only the last one means "clear it".
      list.innerHTML = '<span class="note">' + (!PROJECTS.length
        ? "No published proposals yet."
        : "No " + esc(PP_LABEL[PP_TAB]) + " projects" + (q ? " match your search." : " yet."))
        + '</span>';
      return;
    }
    list.innerHTML = ppSlice(pool, PP_PAGE).map(ppRowHtml).join("");
    list.querySelectorAll(".nt-chip").forEach((b) => b.addEventListener("click", () => {
      if (b.disabled) return;
      toggleProject(b.dataset.pid, b.dataset.email, b.dataset.base === "1", b.dataset.eff === "1", b);
    }));
    list.querySelectorAll(".pp-reset").forEach((b) => b.addEventListener("click", () => resetProject(b.dataset.pid)));
  }

  async function toggleProject(pid, email, base, eff, btn) {
    const newEff = !eff;
    const mode = (newEff === base) ? "clear" : (newEff ? "add" : "mute");   // clear when back to global
    if (btn) btn.disabled = true;
    try {
      const r = await api("/api/portal/proposal/" + encodeURIComponent(pid) + "/notify-overrides",
        { method: "PUT", body: JSON.stringify({ email, mode }) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      const bucket = OVERRIDES[pid] || (OVERRIDES[pid] = {});
      if (mode === "clear") { delete bucket[email.toLowerCase()]; if (!Object.keys(bucket).length) delete OVERRIDES[pid]; }
      else bucket[email.toLowerCase()] = mode;
      ppAlert("", ""); renderProjects();
    } catch (err) { ppAlert("err", "Could not update: " + (err.message || "retry")); renderProjects(); }
  }

  async function resetProject(pid) {
    const ov = OVERRIDES[pid] || {};
    const emails = Object.keys(ov);
    if (!emails.length) return;
    const ok = await TW.confirmDanger({
      title: "Reset to global?",
      message: "Clear " + emails.length + " per-project exception(s) and use the global default for this project?",
      confirmText: "Reset", tone: "warn", icon: "↺",
    });
    if (!ok) return;
    try {
      for (const e of emails) {
        const r = await api("/api/portal/proposal/" + encodeURIComponent(pid) + "/notify-overrides",
          { method: "PUT", body: JSON.stringify({ email: e, mode: "clear" }) });
        const j = await r.json().catch(() => ({}));
        if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      }
      delete OVERRIDES[pid];
      renderProjects();
    } catch (err) { ppAlert("err", "Could not reset: " + (err.message || "retry")); }
  }

  boot();
})();
