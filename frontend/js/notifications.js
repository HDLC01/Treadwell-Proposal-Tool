// Externalized (CSP: no inline scripts). "Notification Sending": who receives Customer Portal
// notification emails. Green = receives, gray = off. Three cards, widest rule first.
//   1. Team (global): the floor. Everyone here hears about every CRM step unless the matrix
//      below says otherwise for one step. Admins edit.
//   2. Per step: a person x CRM-step matrix. A cell is explicit ON, explicit OFF, or INHERITED
//      from the team list, and the three look different on purpose. An explicit OFF really does
//      stop that one email, so what the grid shows is what the resolver does.
//   3. Per project: assign different people to a specific project; overrides everything above
//      for that project only. Admins toggle anyone; other staff may toggle only themselves
//      (server-enforced). The same overrides also show in the Customer Portal drawer, one
//      source of truth.
//
// WHY THE MATRIX EXISTS. Hanz, 2026-08-21: "is there a way like a UI/UX that to implement toggle
// on and off who gets automatically toggled on for the notif sending for each step of the CRM?"
// His premise was that Kylene is toggled on for approval. She is not: she sits on the deposit
// bucket, and approval only LOOKS connected because approving is what triggers a deposit
// request. The roster had exactly two buckets, general and deposit, so all seven other moments
// shared one list that could only be set to everything or nothing.
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
  let ROSTER = [];                 // [{email, enabled}]: the GENERAL rows, the floor
  let STEPS = [];                  // [{id, label, hint}], served by the portal, never hardcoded
  let CELLS = {};                  // { emailLower: { stepId: true|false } }: the EXPLICIT rows
  let INERT = [];                  // addresses whose only rows resolve to nothing (see stepsOfRow)
  let RAW = [];                     // the rows exactly as the API returned them, for a repaint
  let PROJECTS = [];               // [{proposal_id, project_name, customer_email, ...}]
  let OVERRIDES = {};              // { proposal_id: { emailLower: 'add'|'mute' } }

  // The one roster group: the FLOOR.
  //
  // This used to be two cards, "Team" and "Deposit alerts", because `kind` held exactly
  // ('general','deposit'). `kind` now holds a CRM STEP, so the deposit list is two COLUMNS of the
  // matrix below (Deposit sent, Deposit received) rather than a card of its own. Keeping the card
  // as well would have meant two controls writing one row, which is how they come to disagree.
  // Nothing became unreachable: kylene@, the row that was live and invisible before 2026-08-20,
  // is a matrix row with two green cells.
  //
  // STILL BUILT THROUGH rosterCardHtml/paintGroup, parameterised, rather than inlined now that
  // there is one of them. The add, the toggle and the remove all hit kind-agnostic endpoints, and
  // a hand-written card would only be a second place to fix the same bug.
  const GROUPS = [{
    kind: "general", other: "step",
    lbl: "Team (the floor, all projects, every step)",
    intro: "Everyone here hears about every step below, unless the matrix switches one off for " +
      "them. This is the floor: a step nobody has set up still reaches these people, because an " +
      "alert that reaches nobody is worse than one that reaches too many.",
    what: "the team", also: "has step exceptions",
    addLbl: "Add someone",
    empty: "No one on the list yet.",
    removeTitle: "Remove from notifications?",
    removeBefore: "Stop sending Customer Portal notifications to ",
    // Said out loud because the team row and a step row are separate rows: removing this one
    // leaves the step exceptions standing, and somebody who believes they removed everything
    // stops looking.
    removeAlso: "? Their per-step settings stay, so any step switched ON for them keeps sending.",
    chips: "nn-chips", input: "nn-email", btn: "nn-add", alert: "nn-alert",
  }];

  /** Which bucket a stored row belongs to: the floor, or one CRM step.
   *
   *  Anything the step list does not name is treated as the FLOOR, which is the same call the
   *  portal's resolver makes, so a row with a missing or unrecognised kind lands on a card
   *  somebody can see and remove. Filtering such a row out is precisely the failure the second
   *  card was built to end: kylene@ existed, worked, and appeared nowhere.
   *
   *  The one legacy value worth naming is "deposit", which is what BOTH money steps were called
   *  before 2026-08-21. The portal fans such a row out to both steps at resolve time and the
   *  schema change converts it, so it is a step row here too rather than a mystery on the floor. */
  const stepIds = () => STEPS.map((x) => x.id);
  const kindOf = (row) => {
    const k = (row && row.kind) || "general";
    if (k === "deposit") return "deposit";
    return stepIds().indexOf(k) >= 0 ? k : "general";
  };
  /** The step buckets one stored row counts for. Two for the legacy deposit kind, one otherwise,
   *  none for a floor row. Mirrors email_sender.bucket_notify_rows, INCLUDING its one exemption:
   *  a legacy "deposit" row that is switched OFF counts for NEITHER money step.
   *
   *  Under the old vocabulary there was no such thing as a suppression, so an off row could only
   *  ever mean "an address somebody typed into the Deposit-alerts card and never turned green".
   *  The resolver skips it, and drawing it as two explicit OFF cells would be the grid claiming a
   *  suppression that stops no email: the one lie this screen must not tell. It is not hidden
   *  either, because the person keeps a grid row through INERT below. */
  const stepsOfRow = (row) => {
    const k = kindOf(row);
    if (k === "deposit") {
      return row && row.enabled !== false ? ["deposit_submitted", "deposit_received"] : [];
    }
    return k === "general" ? [] : [k];
  };

  const listFor = (kind) => (kind === "general" ? ROSTER : []);

  /** Does this address carry any explicit step setting? A team row and a step row are separate
   *  rows, so both at once is legal and normal. It only ever adds a label to the chip and a
   *  sentence to the remove dialog, so somebody removing a person from the team knows their step
   *  exceptions are still there. */
  const onList = (kind, email) => {
    const e = String(email || "").trim().toLowerCase();
    if (kind === "general") return ROSTER.some((m) => m.email.toLowerCase() === e);
    return Object.keys(CELLS[e] || {}).length > 0;
  };

  // ── per-project categories + paging ─────────────────────────────────────────
  // Hanz, 2026-08-19: "the per project Notification sending should be separate for active and
  // test projects", "for it not to populate the per projects tab there should also be a lost,
  // won category for that. Where it moves the project to there", "add a pagination".
  //
  // One flat list of every project the portal knows about was the complaint: scratch bids,
  // dead deals and finished work all sat in the working list, and it only ever grew.
  //
  // Handed Off sits beside Active because both are news worth reading; Test is at the far end,
  // which is the order Hanz asked for on the CRM board on 2026-08-15 ("Active and Lost are both
  // real work, so they read together and the scratch tab sits at the far end").
  //
  // WAS "Won" until 2026-08-28, and the rename is not cosmetic: the CRM board stopped moving won
  // jobs off Active that day, so a Won tab here would have held live work the board still shows,
  // and the two screens would disagree about where a job lives. Handed off is the state that
  // actually means "not our problem any more" on both.
  const PP_TABS = [["active", "Active"], ["handed_off", "Handed Off"], ["lost", "Lost"], ["test", "Test"]];
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

  // Handed off and Lost both come from crm-core, which is the point. Hanz, 2026-08-19: "CRM lost
  // and won should also tie up to the notification sending okay?" — isWon used to live in this file,
  // the one page with a Won tab, and a local copy is how two screens end up disagreeing about a word
  // Troy reads as a number. The reasoning behind the predicate is documented at its definition.
  const isHandedOff = C.isHandedOff;

  /** Exactly one category per project. The ORDER is the whole content of this function.
   *
   *  LOST FIRST, above Test, because that is what the CRM board does: crm-core's stage() returns
   *  Closed lost before it looks at anything else, and portal.js's boardPool puts a lost test
   *  project on the Lost tab carrying a Test chip. Two screens disagreeing about where a dead deal
   *  lives is worse than either answer, so this page copies the board and carries the same chip.
   *
   *  TEST ABOVE HANDED OFF, because a test project's outcome is fiction. Handed Off is a number a
   *  human reads as real work, and somebody's scratch bid must not be able to inflate it. The board
   *  agrees here too: boardPool files a handed-off test project on its Test tab.
   *
   *  ACTIVE IS THE REMAINDER, never a predicate of its own. That is what makes these four a
   *  partition: a project the categories don't recognise lands in the working list, where someone
   *  will see it, rather than in no tab at all. */
  function ppCategory(p) {
    if (C.isLost(p)) return "lost";
    if (C.isTest(p)) return "test";
    // isHandedOff, NOT isWon, since 2026-08-28: a won job is still live work on the CRM board, so
    // filing it here would take it out of the working list while the board still chased it.
    if (isHandedOff(p)) return "handed_off";
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
      matrixCardHtml() +
      '<div class="card">' +
        '<div class="lbl">Per-project — assign specific people</div>' +
        '<p class="note" style="margin:0 0 8px">Green = receives THIS project’s emails. Overrides the team list above for that project only. ' +
        (ADMIN ? "Toggle anyone." : "You can toggle only yourself.") + '</p>' +
        // The decision, on screen, so nobody has to read peopleFor() to find out.
        '<p class="note" style="margin:0 0 8px">Only the team list is shown here. Somebody who is ' +
        'set for one step only (say the deposit) is not, because a per-project toggle covers ' +
        'every email that project sends: an override is stored by address with no step attached, ' +
        'so switching them on here would sign them up for approvals and replies as well.</p>' +
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

  /** Repaint the roster cards from the rows the last load returned.
   *
   *  RAW is kept because a matrix click changes what the team chips SAY: a person's chip carries
   *  a "has step exceptions" label and its remove dialog warns that those exceptions survive.
   *  Re-fetching to redraw a label would be a round trip for something already in hand. */
  function repaintGroups() {
    GROUPS.forEach((g) => paintGroup(g, RAW.filter((x) => kindOf(x) === g.kind)));
  }

  async function load() {
    try {
      const r = await api("/api/portal/notify-recipients");
      const j = await r.json();
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      RAW = j.recipients || [];
      // THE STEP LIST COMES DOWN THE WIRE. The portal owns the vocabulary (NOTIFY_STEPS) and its
      // resolver reads the same tuple, so the columns cannot advertise a step nothing resolves.
      // A hardcoded copy here is a copy that drifts, and the drift would be silent: a toggle that
      // writes a row no alert ever looks at.
      STEPS = (j.steps || []).filter((x) => x && x.id);
      // Bucket first, paint second. A chip's "has step exceptions" label asks about CELLS, so
      // painting the roster before CELLS existed would silently drop every label.
      // DEDUPED BY ADDRESS. The table's unique key is (kind, lower(email)), so a real general row
      // is already unique per person; duplicates only arise from the unknown-kind fallback above,
      // where two step rows naming a step this page has not been told about both land on the
      // floor. Two chips for one person, each removing a different row, is worse than one chip
      // that removes the first: the second row still shows up on the next load.
      const seenTeam = {};
      ROSTER = RAW.filter((x) => kindOf(x) === "general").reduce((acc, x) => {
        const key = String(x.email || "").toLowerCase();
        if (!key || seenTeam[key]) return acc;
        seenTeam[key] = 1;
        acc.push({ email: x.email, enabled: x.enabled !== false });
        return acc;
      }, []);
      CELLS = {};
      RAW.forEach((x) => {
        const key = String(x.email || "").toLowerCase();
        stepsOfRow(x).forEach((step) => {
          (CELLS[key] = CELLS[key] || {})[step] = x.enabled !== false;
        });
      });
      // Addresses the roster holds whose rows resolve to NOTHING. Today that is exactly a dormant
      // legacy "deposit" row: it is not floor membership, so it wins no chip, and it suppresses
      // nothing, so it draws no cell. They still get a GRID ROW, every cell grey and clickable,
      // because a person the roster holds and the page cannot show is the failure this card was
      // rebuilt to end. Grey rather than off is also what the resolver does with them.
      INERT = [];
      RAW.forEach((x) => {
        const key = String(x.email || "").toLowerCase();
        if (!key || kindOf(x) === "general" || stepsOfRow(x).length) return;
        if (INERT.indexOf(key) < 0) INERT.push(key);
      });
      repaintGroups();
      GROUPS.forEach((g) => alertOf(g, "", ""));
      paintMatrix();
      mxAlert("", "");
    } catch (err) {
      // EVERY card says so. One card reading "Could not load" beside another still showing
      // "Loading…" would look like a half-working page rather than one failed fetch.
      GROUPS.forEach((g) => {
        const wrap = $(g.chips);
        if (wrap) wrap.innerHTML = '<span class="note">Could not load: ' + esc(err.message) + '</span>';
      });
      const grid = $("mx-grid");
      if (grid) grid.innerHTML = '<span class="note">Could not load: ' + esc(err.message) + '</span>';
    }
  }

  async function toggle(id, enabled, chip, g) {
    if (chip) chip.style.opacity = ".5";
    try {
      const r = await api("/api/portal/notify-recipients/" + encodeURIComponent(id),
        { method: "PATCH", body: JSON.stringify({ enabled }) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      await load(); renderProjects();      // load() repaints the matrix; the floor moved   // roster base changed → per-project effective states shift
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
      await load(); renderProjects();      // load() repaints the matrix; the floor moved
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
      await load(); renderProjects();      // load() repaints the matrix; the floor moved
    } catch (err) { alertOf(g, "err", "Could not remove: " + (err.message || "retry")); }
  }

  // ── Per-step matrix: people down the side, CRM steps across the top ────────
  //
  // FOUR CELL STATES, NOT TWO, and that is the whole design. A green cell that came from the team
  // list is not a decision anybody made about this step, and reading it as one is the main risk
  // this feature carries: somebody sees green under "Proposal opened", believes it was chosen,
  // and never asks. So an inherited cell is drawn differently AND says where it came from, in
  // the cell, in the word "team".
  //
  //   on        an explicit row, enabled. This person hears about this step.
  //   off       an explicit row, disabled. This person does NOT, even though the team list would
  //             otherwise have reached them. It really does stop the email (see below).
  //   inherited no row, and they are on the team. The floor decides, and the floor says yes.
  //   none      no row, and they are not on the team. Nobody hears anything about them here.
  //
  // AN EXPLICIT OFF BEATS THE FLOOR. That was a choice against the alternative (make it a no-op
  // and let the floor win), and it is the choice that keeps this screen honest: every green cell
  // receives and every grey cell does not, one rule, readable straight off the grid. The other
  // way round, the only means of taking one moment off somebody would be removing them from the
  // team, which takes the other eight as well: a cliff, not a knob.
  //
  // WHICH MEANS SWITCHING A WHOLE COLUMN OFF REALLY DOES REACH NOBODY. That is said out loud on
  // the column itself, in mxColumn's `silent` flag, rather than left for Hanz to discover.
  const MX_LABEL = { on: "on", off: "off", inherited: "team", none: "" };

  /** A step's label, for a message. Read off STEPS rather than kept here, for the same reason the
   *  columns are: one source of truth for the vocabulary, and it is the portal. */
  const stepLabel = (id) => (STEPS.filter((x) => x.id === id)[0] || {}).label || id;

  /** The person rows: everybody the roster mentions, on the team or not, in one order.
   *
   *  A step row is enough to appear here, which is what makes a deposit-only person visible and
   *  removable instead of configuration that only SQL can see. Sorted by name so the grid does
   *  not reshuffle when somebody is added. */
  function mxPeople() {
    const seen = {}, out = [];
    ROSTER.forEach((m) => {
      const e = m.email.toLowerCase();
      seen[e] = 1;
      out.push({ email: m.email, floorOn: m.enabled !== false, onTeam: true });
    });
    Object.keys(CELLS).concat(INERT).forEach((e) => {
      if (!seen[e]) { seen[e] = 1; out.push({ email: e, floorOn: false, onTeam: false }); }
    });
    return out.sort((a, b) => nameOf(a.email).localeCompare(nameOf(b.email)));
  }

  /** One cell, resolved the way the server resolves it. The mirror is the point: a grid that
   *  computed its own answer would be a second opinion about who gets emailed. */
  function mxCell(person, step) {
    const row = CELLS[person.email.toLowerCase()] || {};
    const explicit = Object.prototype.hasOwnProperty.call(row, step);
    const on = explicit ? !!row[step] : person.floorOn;
    return {
      email: person.email, step: step, explicit: explicit, on: on, floorOn: person.floorOn,
      onTeam: !!person.onTeam,
      state: explicit ? (on ? "on" : "off") : (on ? "inherited" : "none"),
    };
  }

  /** What one click writes. Toggles the EFFECTIVE state and stores whichever value produces it,
   *  preferring "inherit" whenever that matches the team list, so a cell returns to following the
   *  floor rather than accumulating an explicit row that happens to agree with it. Same rule the
   *  per-project chips already use (see toggleProject's "clear when back to global"), because two
   *  toggles on one page should not need two mental models. */
  function mxNext(cell) {
    const wantOn = !cell.on;
    return wantOn === cell.floorOn ? "inherit" : (wantOn ? "on" : "off");
  }

  /** Who this column actually reaches, and whether that is nobody.
   *
   *  Computed from the same three inputs the resolver uses (the floor, this step's opt-ins, this
   *  step's suppressions) rather than by counting green cells, so the warning cannot drift from
   *  the rule. Per-project adds are deliberately NOT counted: a column that only reaches somebody
   *  because one job happens to have an override is still a column nobody set up. */
  function mxColumn(step) {
    const reach = mxPeople().filter((person) => mxCell(person, step).on).map((p) => p.email);
    return { step: step, reach: reach, silent: !reach.length };
  }

  function matrixCardHtml() {
    return '<div class="card">' +
      '<div class="lbl">Per step: who hears about each CRM moment</div>' +
      '<p class="note" style="margin:0 0 8px">Green = receives. A cell marked ' +
      '<strong>team</strong> is not a choice anybody made here: it is inherited from the team ' +
      'list above. Click a cell to set it for that person and that step only.</p>' +
      // The sentence that has to be on screen, because the resolver's floor is invisible
      // otherwise and the consequence of switching a column off is not obvious.
      '<p class="note" style="margin:0 0 8px">Switching a cell off really does stop that one ' +
      'email for that person, and it leaves their other steps alone. Switch a whole column off ' +
      'and the column says <strong>nobody is told</strong>, because that is what it means.</p>' +
      // The one exception, and why it is an exception. This email is also the alert that a
      // proposal did NOT reach the customer, so an empty column here hides a failed send.
      '<p class="note" style="margin:0 0 8px">One column cannot be emptied. ' +
      '<strong>Proposal sent</strong> is also the alert that a proposal did not reach the ' +
      'customer, so somebody has to stay on it. To hand it over, turn the new person on first, ' +
      'then switch the old one off.</p>' +
      '<div id="mx-alert" class="alert"></div>' +
      '<div id="mx-legend" class="mx-legend"></div>' +
      '<div class="mx-scroll"><div id="mx-grid"><span class="note">Loading…</span></div></div>' +
      (ADMIN ? "" : '<p class="note" style="margin-top:12px">Only admins can change this grid.</p>') +
    '</div>';
  }

  function mxAlert(kind, msg) {
    const a = $("mx-alert");
    if (a) { a.className = "alert " + kind; a.textContent = msg || ""; }
  }

  /** The legend, built from the same MX_LABEL the cells use so a renamed state cannot label one
   *  and not the other. */
  function paintLegend() {
    const el = $("mx-legend");
    if (!el) return;
    el.innerHTML = [["on", "set on here"], ["inherited", "on, from the team list"],
                    ["off", "switched off here"], ["none", "not on the team"]]
      .map((x) => '<span class="mx-key"><span class="mx-cell mx-' + x[0] + '" aria-hidden="true">'
        + '<span class="mx-g">' + esc(MX_LABEL[x[0]]) + '</span></span>' + esc(x[1]) + '</span>')
      .join("");
  }

  function paintMatrix() {
    const grid = $("mx-grid");
    if (!grid) return;
    paintLegend();
    if (!STEPS.length) {
      grid.innerHTML = '<span class="note">Could not load the step list.</span>';
      return;
    }
    const people = mxPeople();
    if (!people.length) {
      grid.innerHTML = '<span class="note">Nobody on the roster yet. Add someone above, then '
        + 'set their steps here.</span>';
      return;
    }
    // `STEPS.map(mxColumn)` would hand mxColumn the step OBJECT (and the index, and the array),
    // so every cell lookup would miss and `silent` could never be true while anybody sat on the
    // floor: the warning would simply never appear, and the grid would look perfectly fine.
    // Caught by running it, which is the reason this page is tested by execution.
    const cols = STEPS.map((st) => mxColumn(st.id));
    const head = '<tr><th class="mx-who">Person</th>' + STEPS.map((st, i) =>
      '<th class="mx-head' + (cols[i].silent ? " mx-quiet" : "") + '" title="' + esc(st.hint) + '">'
      + '<span class="mx-h">' + esc(st.label) + '</span>'
      // Only drawn when true, so the row of headers is quiet until something is actually wrong.
      + (cols[i].silent ? '<span class="mx-warn">nobody is told</span>' : "")
      // A step the portal marks `required` cannot be left reaching nobody, and the server refuses
      // the click that would do it. Said on the column so the refusal is predictable rather than
      // a surprise, and only when the column is not already shouting something louder.
      + (st.required && !cols[i].silent
          ? '<span class="mx-req">one person minimum</span>' : "")
      + '</th>').join("") + '</tr>';
    const body = people.map((person) => {
      const cells = STEPS.map((st) => {
        const c = mxCell(person, st.id);
        const cls = "mx-cell mx-" + c.state;
        // aria-label spells the whole thing out, inherited included: the visual difference is
        // colour and one small word, and neither reaches a screen reader on its own.
        // The "none" wording splits on whether they are on the team at all, because those are two
        // different facts and the row header says which: somebody switched off ON the team list is
        // following it, and somebody absent from it is not on it. One sentence for both would make
        // the grid and the row header contradict each other.
        const label = nameOf(person.email) + ", " + st.label + ": "
          + (c.state === "inherited" ? "on, inherited from the team list"
            : c.state === "on" ? "on, set here"
            : c.state === "off" ? "off, switched off here"
            : c.onTeam ? "off, following the team list"
            : "off, not on the team");
        return '<td class="mx-td">'
          + '<button type="button" class="' + cls + '" data-email="' + esc(person.email) + '"'
          + ' data-step="' + esc(st.id) + '" data-state="' + c.state + '"'
          + ' data-on="' + (c.on ? 1 : 0) + '" data-floor="' + (c.floorOn ? 1 : 0) + '"'
          + ' data-next="' + mxNext(c) + '" aria-pressed="' + (c.on ? "true" : "false") + '"'
          + (ADMIN ? "" : " disabled") + ' aria-label="' + esc(label) + '">'
          + '<span class="mx-g" aria-hidden="true">' + esc(MX_LABEL[c.state]) + '</span>'
          + '</button></td>';
      }).join("");
      // The floor state, READ ONLY. It explains every inherited cell on the row, and it is not a
      // second control for the chip above: one state, one switch.
      return '<tr><th class="mx-who" scope="row">' + plainAvatar(person.email)
        + '<span class="mx-name">' + esc(nameOf(person.email)) + '</span>'
        + '<span class="mx-floor">' + (person.onTeam
          ? (person.floorOn ? "on the team" : "on the team, off")
          : "not on the team") + '</span></th>' + cells + '</tr>';
    }).join("");
    grid.innerHTML = '<table class="mx"><thead>' + head + '</thead><tbody>' + body
      + '</tbody></table>';
    if (!ADMIN) return;
    grid.querySelectorAll(".mx-cell").forEach((b) => b.addEventListener("click", () => {
      if (b.disabled) return;
      toggleCell(b.dataset.email, b.dataset.step, b.dataset.next, b);
    }));
  }

  async function toggleCell(email, step, next, btn) {
    if (btn) btn.disabled = true;
    try {
      const r = await api("/api/portal/notify-recipients/step",
        { method: "PUT", body: JSON.stringify({ email: email, step: step, state: next }) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || j.ok === false) {
        // The server refuses to leave a required column reaching nobody. Translated here because
        // "would_silence_step" is a code, not a sentence, and the reader needs the way out.
        // Both keys: the portal answers {error}, and the tool's proxy re-raises it as {detail}.
        const code = j.error || j.detail || ("HTTP " + r.status);
        if (code === "would_silence_step") {
          const e = new Error("Somebody has to hear about " + stepLabel(step) + ", because that "
            + "email is also the alert that a proposal did not reach the customer. Turn another "
            + "person on for it first, then switch this one off.");
          e.silenced = true;
          throw e;
        }
        throw new Error(code);
      }
      const key = String(email).toLowerCase();
      const row = CELLS[key] || (CELLS[key] = {});
      if (next === "inherit") {
        delete row[step];
        if (!Object.keys(row).length) delete CELLS[key];
      } else {
        row[step] = next === "on";
      }
      mxAlert("", "");
      // Both, because a step row is what the team card's "has step exceptions" label reads and
      // what its remove dialog warns about.
      paintMatrix();
      repaintGroups();
    } catch (err) {
      // A refusal is an answer, not a failure, so it is not dressed up as one.
      mxAlert("err", err && err.silenced
        ? err.message : "Could not update: " + ((err && err.message) || "retry"));
      paintMatrix();
    }
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
  // TEAM ROWS ONLY. Somebody who holds a step row and no team row is deliberately absent, and
  // the card says so on screen. A per-project chip is one on/off governing everything that
  // project emails, and an override is stored as (proposal_id, email, mode) with no step at all:
  // switching a step-only person green here would union their address into that project's whole
  // recipient list, quietly promoting somebody who was set up for the two deposit emails into
  // approvals, replies and questions. Rejected alternative: show them with their chip disabled,
  // which invites exactly the "why can't I click this" that a sentence answers better.
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
