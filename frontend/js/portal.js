// Customer Portal admin page — proxies to the portal's admin API via the
// proposal-tool backend (/api/portal/*). Externalized (no inline scripts; CSP).
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (n) => (n == null ? "" : "$" + Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  // Central, not viewer-local: "submitted 7/27 10:04 PM" must mean the same day to
  // Kyle in Kansas and to anyone testing from another timezone. Falls back to the
  // old local rendering only if shared.js somehow hasn't loaded.
  const when = (s) => (s
    ? ((window.TW && TW.fmtBizDateTime) ? TW.fmtBizDateTime(s) : new Date(s).toLocaleString())
    : "");
  // Which column, what date, whose it is — all in crm-core.js, which has no DOM
  // and is exercised under node. See the header there for why each answer is what
  // it is. This file owns rendering and nothing else about the board's meaning.
  const C = window.TWCrm;
  const { STAGES, STAGE_SUBMITTED, NATURAL_DIR, SORT_FIELDS } = C;
  const { stage: stageOf, lastActivity, activityTs, stageTs, estimatorOf, isAssigned,
          isLost, isTest, lostReason, followupOff, nameOf, cardTotal } = C;
  const fu = C.followup;
  const avatar = C.avatarHtml;
  /** The same chip with the identity colour taken OUT — for the drawer's notification
   *  toggles, where green already means "receives this project's email". State owns
   *  colour on that one control and the initials carry who it is. esc() because the
   *  initials follow whatever string the roster handed us, not a whitelist. */
  const plainAvatar = (who) =>
    '<span class="nt-av" aria-hidden="true">' + (esc(C.initialsOf(who)) || "—") + "</span>";
  const pausedUntil = (p) => C.pausedUntil(p, TW.bizToday());
  const ROLE_LABEL = { primary: "Primary", accounts_payable: "Accounts payable", other: "Other" };
  let ALL = [];

  // ── filter / sort state ────────────────────────────────────────────────────
  // Module-level and mirrored to sessionStorage: renderBoard re-runs after every
  // staff action (act() calls load()), and the controls live in static HTML, so
  // a scan survives both a re-render and a return visit.
  const EST_KEY = "tw_crm_est", MONTH_KEY = "tw_crm_month";
  const SORTFIELD_KEY = "tw_crm_sortfield", SORTDIR_KEY = "tw_crm_sortdir";
  const TAB_KEY = "tw_crm_tab", VIEW_KEY = "tw_crm_view";
  const ss = (k, d) => { try { const v = sessionStorage.getItem(k); return v == null ? d : v; } catch { return d; } };
  const ssSet = (k, v) => { try { v ? sessionStorage.setItem(k, v) : sessionStorage.removeItem(k); } catch {} };
  let EST = ss(EST_KEY, "");
  let MONTH = ss(MONTH_KEY, "");
  let SORTFIELD = SORT_FIELDS.includes(ss(SORTFIELD_KEY, "")) ? ss(SORTFIELD_KEY, "") : "activity";
  let SORTDIR = ss(SORTDIR_KEY, "") === "asc" ? "asc" : (ss(SORTDIR_KEY, "") === "desc" ? "desc" : NATURAL_DIR[SORTFIELD]);
  // Active by default: the working list is what a rep opens this page for, and Test is
  // somewhere you go on purpose. Same default, and the same `is_test` flag, as the
  // Proposals Database.
  //
  // There is no SHOW_LOST here any more. It used to add a Lost column and a "Show closed
  // lost (N)" toggle; Hanz, 2026-08-10: "if its lost remove it from the Customer CRM. To
  // remove clutter." The count now sits on the tab row as a link out. See syncLostLink.
  let TAB = ss(TAB_KEY, "") === "test" ? "test" : "active";
  let VIEW = ss(VIEW_KEY, "") === "table" ? "table" : "board";

  function api(path, opts) {
    // MERGE headers — a caller passing its own `headers` used to replace the auth
    // ones wholesale via Object.assign, so any request that set Content-Type
    // silently lost its bearer token and came back 401.
    opts = opts || {};
    return fetch(TW.resolveApiBase() + path,
                 Object.assign({}, opts, { headers: TW.authHeaders(opts.headers) }));
  }
  async function tokenReady() {
    try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch {}
    for (let i = 0; i < 200 && !window.__TW_TOKEN; i++) await new Promise((r) => setTimeout(r, 40));
  }

  // Pure, composed in renderBoard. Search is read live from the DOM (the input
  // is static markup, so it survives every re-render) — the rest read state.
  const applySearch = (list) => {
    const q = ($("search").value || "").toLowerCase().trim();
    if (!q) return list;
    const tokens = q.split(/\s+/);
    return list.filter((p) => {
      // Recipients included: a proposal sent to two people has to be findable by EITHER
      // address, or searching for the person who actually replied turns up nothing.
      const hay = [p.project_name, p.customer_email, p.customer_name, p.estimator_email,
                   (p.recipients || []).join(" ")]
        .filter(Boolean).join(" ").toLowerCase();
      return tokens.every((t) => hay.includes(t));
    });
  };
  const applyEstimator = (list) => (EST
    ? list.filter((p) => estimatorOf(p).toLowerCase() === EST)
    : list);
  const applyMonth = (list) => (MONTH
    ? list.filter((p) => TW.bizYM(activityTs(p)) === MONTH)   // the month the card shows
    : list);

  const applySort = (list) => C.sort(list, SORTFIELD, SORTDIR);

  /** The rows this board is ABOUT, before any filter the toolbar owns. Two exclusions,
   *  and neither of them is something the rep can switch back on:
   *
   *  CLOSED LOST IS GONE. Hanz, 2026-08-10: "allow for the projects to be lost even its been
   *  approved and if its lost remove it from the Customer CRM. To remove clutter." No Lost
   *  column, no toggle. The tab row carries the count and links out to the Proposals Database,
   *  so a dead deal is still findable without occupying a board of live work.
   *
   *  TEST PROJECTS ARE THEIR OWN TAB, split by C.isTest, the same predicate on the same
   *  `is_test` flag, that the Proposals Database uses. Anything that page shows under Test has
   *  to show up under Test here too.
   *
   *  Also what populateEstimators/populateMonths count, so an option can never offer a filter
   *  that yields nothing: a month whose only proposals were lost used to sit in that dropdown
   *  and blank the board when picked. */
  function boardPool() {
    return ALL.filter((p) => !isLost(p) && isTest(p) === (TAB === "test"));
  }

  /** Everything the current filters allow, in the current order. Both views read
   *  this, so a filter can never mean two different things depending on the view. */
  function visible() {
    return applySort(applyMonth(applySearch(applyEstimator(boardPool()))));
  }

  /** The state chips a card and a row both carry. Words, not colour alone: this page
   *  gets a synthesized dark theme in some browsers, which rewrites tint. */
  function chipsHtml(p) {
    const out = [];
    if (isLost(p)) {
      const why = lostReason(p);
      out.push(`<span class="chip chip-lost" title="${esc(why ? "Reason: " + why : "No reason recorded")}">Closed lost${
        why ? " · " + esc(why) : ""}</span>`);
    } else {
      const until = pausedUntil(p);
      if (until) out.push(`<span class="chip chip-pause" title="The customer asked us to come back to this">Paused to ${esc(TW.fmtBizDay(until))}</span>`);
      // Only worth saying when it's OFF: automation being on is the norm, and a chip
      // on every card would say nothing.
      else if (followupOff(p)) out.push('<span class="chip chip-off" title="Automatic follow-up emails are switched off for this project">Follow-up off</span>');
    }
    return out.join("");
  }

  // What the board currently shows. `renderBoard()` replaces the board's entire innerHTML, so
  // painting data that hasn't changed destroys and rebuilds every column and card for no reason
  // — which the eye sees as the whole board blinking. This page polls every 25s, the shortest
  // interval in the app, so it blinked more than any other board here.
  //
  // Same guard as the Bid Pipeline (crm.js), the Lead Inbox (leads.js) and the Bid Calendar
  // (calendar.js). It goes at the TOP, before populateEstimators/populateMonths: those rebuild
  // the filter <select> options, and rebuilding a <select> closes it under the cursor of anyone
  // who happened to have it open.
  let BOARD_SIG = "";

  function renderBoard() {
    // The whole shaped dataset plus every piece of view state renderBoard draws from — a
    // proposal moving stage leaves the count identical, and the filters have to keep repainting
    // or changing one would appear to do nothing.
    //
    // One benign wrinkle: populateMonths below can clear a MONTH whose rows have all gone, after
    // this signature captured the old value. The next call then sees a different signature and
    // repaints once. One extra paint, no loop, and only on a month emptying out.
    //
    // The lost COUNT is named even though `ALL` is serialized whole and therefore already
    // implies it. Two reasons it earns its place: the count is painted OUTSIDE the board's
    // innerHTML (it is a link in the toolbar), and lost rows are excluded from everything else
    // this signature is derived from, so narrowing `ALL` to the visible pool, which is the
    // obvious optimisation the day 300 rows per poll starts to hurt, would silently freeze that
    // number at whatever it was on first paint.
    const sig = JSON.stringify([ALL, EST, MONTH, SORTFIELD, SORTDIR, TAB, VIEW,
                                ($("search") || {}).value || "", lostCount()]);
    if (sig === BOARD_SIG) return;
    BOARD_SIG = sig;

    populateEstimators();
    populateMonths();
    const items = visible();
    const shown = boardPool().length;
    $("count").textContent = items.length === shown
      ? shown + " proposal" + (shown === 1 ? "" : "s")
      : items.length + " of " + shown;
    const clear = $("crm-clear");
    if (clear) clear.hidden = !(EST || MONTH || SORTFIELD !== "activity" || SORTDIR !== "desc");
    syncTabs();
    syncLostLink();
    const board = $("board");
    board.classList.toggle("as-table", VIEW === "table");
    board.innerHTML = VIEW === "table" ? tableHtml(items) : kanbanHtml(items);
  }

  function kanbanHtml(items) {
    // STAGES only. There is no Closed lost column: those proposals never reach here (see
    // boardPool), and C.group drops any row whose stage has no column, so one arriving by
    // some other route is left out rather than throwing.
    const byStage = C.group(items, STAGES);
    return STAGES.map((s) => {
      const cards = byStage[s].map((p) => {
        const act = lastActivity(p);
        // Who owns it and when it last moved, on one line each — the column is only
        // 224px of usable width, so this is the whole budget for both facts.
        // Labelled: a bare "Hanz · Invoiced 7/27" reads as one fact, and it isn't
        // obvious which name that is on a board where the line above is an email.
        const email = estimatorOf(p);
        // The avatar is the scannable half and the name is the readable half. The
        // chip alone would fail anyone who can't tell the colours apart, so the
        // name and the "?" stay exactly as they were.
        const who = email
          ? avatar(email, !isAssigned(p))
            + `<span${isAssigned(p) ? "" : ' class="unassigned" title="Nobody is assigned — this is whoever built the estimate"'}>${
              esc(nameOf(email))}${isAssigned(p) ? "" : "?"}</span>`
          : '<span class="unassigned" title="Nobody is assigned">—</span>';
        const chips = chipsHtml(p);
        return `
        <div class="deal" data-id="${esc(p.proposal_id)}">
          ${p.unread ? `<span class="unread" title="${p.unread} customer message${p.unread === 1 ? "" : "s"} awaiting a reply">${p.unread}</span>` : ""}
          <div class="name">${esc(p.project_name || "Proposal")}</div>
          <div class="meta">${esc(p.customer_email || "")}</div>
          ${recipientLine(p)}
          <div class="meta who"><span class="k">Estimator:</span> ${who}</div>
          ${act ? `<div class="meta act"><span class="k">${esc(act.label)}:</span> ${esc(TW.fmtBizDate(act.ts))}</div>` : ""}
          ${chips ? `<div class="chips">${chips}</div>` : ""}
          ${cardTotal(p) != null ? `<div class="val">${money(cardTotal(p))}</div>` : ""}
          ${cardActions(p)}
        </div>`;
      }).join("") || '<div class="empty">—</div>';
      // Money is in and unconfirmed → flag the column, it's the one needing a human.
      const attn = s === STAGE_SUBMITTED && byStage[s].length ? " col-attn" : "";
      // The board can now START a bid, not only track one. Hanz, 2026-08-12: with the Proposals
      // Database moved out of the way, "when we click a container we are able to create a
      // proposal under that not sent category". Only this column gets the button, because it is
      // the only one whose membership rule a new project can satisfy — everything to the right
      // requires the customer to have been sent something.
      const add = s === STAGE_CREATED
        ? '<button type="button" class="col-add" data-new-proposal title="Start a new proposal — opens the intake form">+ New</button>'
        : "";
      return `<div class="col${attn}"><h2>${esc(s)}<span>${byStage[s].length}</span>${add}</h2>${cards}</div>`;
    }).join("");
  }

  /** Files and Info Sheet, on every card.
   *
   *  Hanz, 2026-08-12: "There should be a button for each container for the files and info sheet
   *  as well." On EVERY card rather than only the unsent ones: this board is where the sales
   *  meeting happens, so reaching a won job's Info Sheet hand-off should not mean going to
   *  another page to find the same project.
   *
   *  The URLs are the ones the Proposals Database already uses (projects.js), deliberately
   *  character-for-character — two spellings of the same route is how one of them rots. That a
   *  synthesised not-sent row works here at all is because its `proposal_id` IS the draft id.
   */
  function cardActions(p) {
    const id = encodeURIComponent(p.proposal_id);
    return `<div class="deal-acts">
      <button type="button" class="deal-act" data-files="${id}" title="Estimate and proposal files">Files</button>
      <button type="button" class="deal-act" data-info="${id}" title="Project Info Sheet — the hand-off to accounting and ops">Info</button>
    </div>`;
  }

  /** "2 recipients · 1 viewed" — only when there are two or more.
   *
   *  The board already dates a card by last_viewed_at, which answers "has anybody looked". This
   *  answers "have they BOTH looked", which is the one that decides whether there is somebody
   *  left to chase. Silent for a single contact, where the two lines would say the same thing.
   */
  function recipientLine(p) {
    const n = (p.recipients || []).length;
    if (n < 2) return "";
    const v = (p.viewed_by || []).length;
    return `<div class="meta rc-line" title="${esc((p.recipients || []).join(", "))}">${
      n} recipients · ${v} viewed</div>`;
  }

  // ── the same pipeline as one table ─────────────────────────────────────────
  // A kanban answers "what's the shape of the pipeline"; a table answers "show me
  // all 60 in one order". Kyle asked for both. Headers re-sort using the SAME
  // COMPARE map the board uses, so the two views can never disagree on ordering.
  const COLS = [
    { key: "project", label: "Project", sort: null },
    { key: "customer", label: "Customer", sort: null },
    { key: "stage", label: "Stage", sort: "stage" },
    { key: "stageDate", label: "In stage since", sort: "stage" },
    { key: "estimator", label: "Estimator", sort: "estimator" },
    { key: "total", label: "Value", sort: "total", num: true },
    { key: "activity", label: "Last activity", sort: "activity" },
  ];

  function tableHtml(items) {
    if (!items.length) return '<div class="empty">Nothing matches those filters.</div>';
    const head = COLS.map((c) => {
      if (!c.sort) return `<th class="${c.num ? "num" : ""}">${esc(c.label)}</th>`;
      const on = SORTFIELD === c.sort;
      const arrow = on ? (SORTDIR === "asc" ? " ↑" : " ↓") : "";
      return `<th class="${c.num ? "num " : ""}th-sort${on ? " is-sorted" : ""}" aria-sort="${
        on ? (SORTDIR === "asc" ? "ascending" : "descending") : "none"}">` +
        `<button type="button" data-sortby="${c.sort}">${esc(c.label)}${arrow}</button></th>`;
    }).join("");
    const rows = items.map((p) => {
      const act = lastActivity(p);
      const email = estimatorOf(p);
      const chips = chipsHtml(p);
      return `<tr class="trow" data-id="${esc(p.proposal_id)}" tabindex="0">
        <td class="t-name">${esc(p.project_name || "Proposal")}${
          p.unread ? ` <span class="unread-dot" title="${p.unread} unread customer message${p.unread === 1 ? "" : "s"}">${p.unread}</span>` : ""}</td>
        <td>${esc(p.customer_name || p.customer_email || "")}</td>
        <td>${esc(stageOf(p))}${chips ? `<div class="chips">${chips}</div>` : ""}</td>
        <td>${esc(TW.fmtBizDate(stageTs(p)))}</td>
        <td${isAssigned(p) ? "" : ' class="unassigned" title="Nobody is assigned — this is whoever built the estimate"'}>${
          email ? avatar(email, !isAssigned(p)) + esc(nameOf(email)) + (isAssigned(p) ? "" : "?") : "—"}</td>
        <td class="num">${cardTotal(p) != null ? money(cardTotal(p)) : ""}</td>
        <td>${act ? esc(act.label) + " " + esc(TW.fmtBizDate(act.ts)) : ""}</td>
      </tr>`;
    }).join("");
    return `<table class="ptable"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table>`;
  }

  // One delegated listener on #board, wired once — renderBoard replaces the node's
  // innerHTML on every poll (every 25s), so per-element listeners would be re-bound
  // dozens of times an hour and leak with each repaint.
  $("board").addEventListener("click", (e) => {
    const th = e.target.closest("[data-sortby]");
    if (th) {
      const f = th.dataset.sortby;
      // Clicking the column already sorted flips it; a new column opens its natural way.
      SORTDIR = SORTFIELD === f ? (SORTDIR === "asc" ? "desc" : "asc") : (NATURAL_DIR[f] || "desc");
      SORTFIELD = f;
      ssSet(SORTFIELD_KEY, SORTFIELD); ssSet(SORTDIR_KEY, SORTDIR);
      syncSortControls();
      renderBoard();
      return;
    }
    // These three run BEFORE the row branch below and each returns, because every one of them
    // sits inside a .deal — without the early return a click would both navigate and open the
    // drawer, and the drawer would win the paint.
    const files = e.target.closest("[data-files]");
    if (files) { window.location.assign("/done.html?d=" + files.dataset.files + "&files=1"); return; }
    const info = e.target.closest("[data-info]");
    if (info) { window.location.assign("/info-sheet.html?d=" + info.dataset.info); return; }
    if (e.target.closest("[data-new-proposal]")) { startNewProposal(); return; }

    const row = e.target.closest(".deal, .trow");
    if (row && row.dataset.id) openDetail(row.dataset.id);
  });

  /** Start a bid from this board. The same three storage keys and the same destination as
   *  "+ New project" on the Proposals Database (projects.js) — a second way of minting a draft
   *  would be a second set of bugs, and the intake form is reached by URL either way.
   *
   *  The test flag follows the TAB you are looking at, which is why this is safe to offer here:
   *  the board is always on Active or Test, never on an "all" view, so a new project can never
   *  land un-filed. Same rule Hanz asked for on the Database ("use the Test category so it
   *  wouldn't mix up"). */
  function startNewProposal() {
    try {
      localStorage.removeItem("treadwell.proposal_tool.state");
      localStorage.removeItem("treadwell.proposal_tool.draft_id");
      sessionStorage.removeItem("treadwell.proposal_tool.hydrated_once");
    } catch {/* private mode — the intake form still works, it just won't resume */}
    TW.setNewProjectTestIntent(TAB === "test");
    window.location.assign("/?new=1");
  }
  $("board").addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const row = e.target.closest && e.target.closest(".trow");
    if (!row) return;
    e.preventDefault();
    openDetail(row.dataset.id);
  });

  /** Options come from the data, so the list can't offer an estimator with no
   *  cards. A stale selection is dropped rather than leaving the board blank.
   *
   *  boardPool(), not ALL: an estimator whose only proposals are lost, or who is only on the
   *  other tab, would otherwise be listed here and empty the board when picked. */
  function populateEstimators() {
    const sel = $("crm-est");
    if (!sel) return;
    const counts = {};
    boardPool().forEach((p) => {
      const e = estimatorOf(p).toLowerCase();
      if (e) counts[e] = (counts[e] || 0) + 1;
    });
    if (EST && !counts[EST]) { EST = ""; ssSet(EST_KEY, ""); }
    const emails = Object.keys(counts).sort((a, b) => nameOf(a).localeCompare(nameOf(b)));
    sel.innerHTML = '<option value="">Any estimator</option>'
      + emails.map((e) => `<option value="${esc(e)}">${esc(nameOf(e))} (${counts[e]})</option>`).join("");
    sel.value = EST;
  }

  function populateMonths() {
    const sel = $("crm-month");
    if (!sel) return;
    const counts = {};
    boardPool().forEach((p) => {
      const ym = TW.bizYM(activityTs(p));
      if (ym) counts[ym] = (counts[ym] || 0) + 1;
    });
    if (MONTH && !counts[MONTH]) { MONTH = ""; ssSet(MONTH_KEY, ""); }
    const months = Object.keys(counts).sort().reverse();
    sel.innerHTML = '<option value="">Any month</option>'
      + months.map((ym) => `<option value="${esc(ym)}">${esc(TW.bizMonthLabel(ym))} (${counts[ym]})</option>`).join("");
    sel.value = MONTH;
  }

  async function load() {
    await tokenReady();
    try {
      const r = await api("/api/portal/pipeline");
      const j = await r.json();
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      ALL = j.proposals || [];
      renderBoard();
    } catch (err) {
      // Only when there is nothing to keep. This runs on a 25s timer, so a single blip on a
      // page a rep leaves open all day would otherwise throw the whole board away and flash an
      // error over work they were reading. Stale rows beat that.
      //
      // The signature describes WHAT IS ON SCREEN, so an error goes in it too. A first draft
      // cleared it instead, and on staging — where the portal is genuinely unreachable — that
      // repainted the identical error every 25s: the same blink, in the one situation where it
      // is least useful. Holding the message means an unchanged error is silent, while a
      // recovery produces a data signature that differs and repaints.
      if (!ALL.length) {
        const esig = "error:" + err.message;
        if (esig !== BOARD_SIG) {
          $("board").innerHTML = '<div class="empty">Could not load the portal pipeline: ' + esc(err.message) +
            '. Check that the portal is configured (PORTAL_ADMIN_URL / SERVICE_TOKEN).</div>';
          BOARD_SIG = esig;
        }
      }
    }
    // Deep-link from a staff notification email: ?open=<proposal_id>.
    //
    // ONCE. load() re-runs on every poll, and an unguarded read here re-opened the drawer every
    // 25s — over a rep who had closed it, and on top of refreshLive's own openDetail, giving two
    // concurrent fetches and two blanks per tick. Reps arrive this way as a matter of course
    // (notifications.py builds /portal.html?open=<pid>, and the Follow-ups board links with
    // &sec=followup), so this was the normal case, not an edge one.
    const openId = new URLSearchParams(location.search).get("open");
    if (openId && !DEEPLINK_USED) openDetail(openId);
  }

  // ── keeping the board live ──────────────────────────────────────────────────
  // The board is a screen reps leave open all day, and until now it only refreshed
  // on page load or after the viewer's OWN action — so a colleague's reply, a
  // customer approval or a deposit landing stayed invisible behind an F5. Filters,
  // sort and search survive a repaint (they live in sessionStorage and the DOM), so
  // re-running load() is safe at any moment.
  const BOARD_POLL_MS = 25000;
  const DRAWER_POLL_MS = 12000;

  /** True when repainting the drawer would interrupt something the rep is doing.
   *
   *  renderDetail rebuilds the drawer's innerHTML. The reply TEXT already survives
   *  that (REPLY_DRAFT), but focus and caret position do not — so refreshing under
   *  someone's hands mid-sentence throws them out of the box. The invoice review
   *  dialog is worse: it would be torn down with half-entered numbers in it.
   *  Staleness for a few seconds beats either. */
  function drawerBusy() {
    if (document.querySelector(".inv-dlg")) return true;   // invoice review is open
    const a = document.activeElement;
    if (!a) return false;
    const tag = (a.tagName || "").toLowerCase();
    return tag === "textarea" || tag === "input" || tag === "select" || a.isContentEditable;
  }

  /** Refresh the board, and the open drawer with it.
   *
   *  `load()` stays in here even though the board has its own 25s timer: the Chat tab's unread
   *  badge is read off the BOARD row, so letting the two drift means the badge disagrees with
   *  the thread printed directly beneath it. Both renders are signature-guarded, so calling it
   *  costs a fetch and no repaint.
   *
   *  Scroll handling used to live here, capturing #thread around the await. It has moved into
   *  renderDetail (capture) and applySecPanel (apply), because renderDetail is the function that
   *  destroys #thread — every path that repaints needs the behaviour, not just this one, and the
   *  version here read a node that a concurrent openDetail had already replaced. */
  async function refreshLive() {
    if (document.hidden) return;
    await load();
    if (!CUR_PID || drawerBusy()) return;
    await openDetail(CUR_PID);
  }

  function startLiveUpdates() {
    setInterval(() => { if (!document.hidden && !drawerBusy()) load(); }, BOARD_POLL_MS);
    setInterval(() => { if (!document.hidden && CUR_PID) refreshLive(); }, DRAWER_POLL_MS);
    // Switching back to the tab should show current state at once, not up to 25s
    // later. This is the moment a rep actually looks at the screen.
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) { CUR_PID ? refreshLive() : load(); }
    });
  }

  // ── modal pop-up (detail drawer) ────────────────────────────────────────────
  function syncScrim() {
    $("scrim").style.display = $("drawer").classList.contains("open") ? "block" : "none";
  }
  function closeDrawer() {
    $("drawer").classList.remove("open"); syncScrim();
    // Clear the tab so the NEXT open routes by what needs attention again.
    CUR_PID = null; ACTIVE_SEC = null;
    // And the signature, or reopening the same proposal with unchanged data would be skipped as
    // "already showing that" — leaving an empty drawer and skipping defaultSection's routing.
    DRAWER_SIG = "";
  }
  function closeAll() { closeDrawer(); }
  // Delegated on #drawer: renderDetail replaces its innerHTML, never the node
  // itself, so this is the only attachment that outlives a re-render.
  $("drawer").addEventListener("click", (e) => {
    const b = e.target.closest(".dtabs .step");     // closest, so a click on .lbl/.val counts
    if (b && b.dataset.sec) focusSection(b.dataset.sec);
  });
  $("drawer").addEventListener("keydown", (e) => {
    const b = e.target.closest && e.target.closest(".dtabs .step");
    if (!b) return;
    const keys = Object.keys(SEC_TABS);
    const i = keys.indexOf(b.dataset.sec);
    let j = -1;
    if (e.key === "ArrowRight") j = (i + 1) % keys.length;
    else if (e.key === "ArrowLeft") j = (i - 1 + keys.length) % keys.length;
    else if (e.key === "Home") j = 0;
    else if (e.key === "End") j = keys.length - 1;
    if (j < 0) return;
    e.preventDefault();
    focusSection(keys[j], true);                    // keep focus on the strip
  });
  $("scrim").addEventListener("click", closeAll);              // click the backdrop to close
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeAll(); });  // Esc to close

  async function openDetail(pid) {
    if (pid !== CUR_PID) { CUR_PID = pid; ACTIVE_SEC = null; }
    // A notification can deep-link straight to a tab (?open=<id>&sec=chat).
    // Consumed ONCE: openDetail re-runs after every action, so an unguarded read
    // would slam the rep back to that tab for the rest of the session.
    if (!DEEPLINK_USED) {
      DEEPLINK_USED = true;
      const want = new URLSearchParams(location.search).get("sec");
      if (want && SEC_TABS[want]) ACTIVE_SEC = want;
    }
    $("scrim").style.display = "block";
    const d = $("drawer"); d.classList.add("open");

    // A "Created but not sent" card is synthesised from a draft — the portal has never heard of
    // it, so /api/portal/proposal/<id> would 404 and the rep would get "Error: HTTP 404" on a
    // project that is perfectly fine. There is also nothing for the real drawer to show: no
    // dates, no thread, no deposit, no contacts. So this answers the only question the card
    // raises, and hands over the one action that moves it along.
    const row = ALL.find((p) => p.proposal_id === pid);
    if (row && row.not_sent) { renderNotSent(pid, row); return; }

    // NEVER BLANK A DRAWER THAT IS ALREADY SHOWING SOMETHING.
    //
    // This line used to be an unconditional `d.innerHTML = 'Loading…'`, and it is what Hanz
    // reported as "blinking": #drawer is a fixed, centred white box over a dark scrim, so
    // emptying it to one line collapses it to a small white card in the middle of a greyed-out
    // screen. It then waited on an uncached proxy hop to the portal (20s timeout) before
    // painting again — every 12s while the drawer was open, and after every button press.
    //
    // Rendering the cached payload first means the poll is invisible: the signature guard in
    // renderDetail throws the repaint away when nothing changed, and shows the difference when
    // something did. Same shape as the Lead Inbox drawer, which this one was copied from.
    if (DETAIL_CACHE[pid]) renderDetail(pid, DETAIL_CACHE[pid]);
    else d.innerHTML = '<div class="dbody"><p class="note">Loading…</p></div>';

    // Which request this is. Two can be in flight — a poll and a click, or two clicks — and the
    // slower one must not paint over the newer one, or repopulate a drawer the rep has closed.
    const gen = ++DETAIL_GEN;
    let data;
    try {
      const r = await api("/api/portal/proposal/" + encodeURIComponent(pid));
      data = await r.json();
      if (!r.ok || data.ok === false) throw new Error(data.error || data.detail || ("HTTP " + r.status));
    } catch (err) {
      if (gen !== DETAIL_GEN || pid !== CUR_PID) return;
      // Keep the last good view rather than replacing it with an error a poll caused. Only a
      // first open, with nothing to fall back on, has to show the failure.
      if (DETAIL_CACHE[pid]) return;
      d.innerHTML = '<div class="dhead"><h2>Error</h2><button class="dclose">&times;</button></div>' +
        '<div class="dbody"><p class="note">' + esc(err.message) + '</p></div>';
      d.querySelector(".dclose").addEventListener("click", closeDrawer);
      return;
    }
    if (gen !== DETAIL_GEN || pid !== CUR_PID) return;
    DETAIL_CACHE[pid] = data;
    renderDetail(pid, data);
  }

  /** The drawer for a bid that exists only as paperwork.
   *
   *  No tab strip, because six of the seven tabs would be empty: there is no customer view, no
   *  thread, no approval and no deposit until somebody sends it. What a rep needs here is the
   *  value, who priced it, how long it has been sitting, and a way to act.
   *
   *  Signature-guarded like renderDetail. openDetail runs again on every 12s poll, and an
   *  unguarded innerHTML here would blank and rebuild the panel four times a minute — the same
   *  blink Hanz reported on the board and the chat. */
  function renderNotSent(pid, row) {
    const sig = JSON.stringify(["not_sent", pid, row]);
    if (sig === DRAWER_SIG) return;
    DRAWER_SIG = sig;
    const who = estimatorOf(row);
    const total = cardTotal(row);
    const d = $("drawer");
    d.innerHTML = `
      <div class="dhead">
        <h2>${esc(row.project_name || "Proposal")}</h2>
        <button class="dclose" aria-label="Close">&times;</button>
      </div>
      <div class="dbody">
        <div class="sec">
          <div class="lbl">Not sent yet</div>
          <p class="note" style="margin:0">The estimate and proposal are generated, but nobody has
          sent them to the customer. Nothing is shared until you do.</p>
        </div>
        ${row.customer_email ? `<div class="sec"><div class="lbl">Addressed to</div>${esc(row.customer_email)}</div>` : ""}
        <div class="sec"><div class="lbl">Estimator</div>${
          who ? avatar(who, !isAssigned(row)) + esc(nameOf(who)) + (isAssigned(row) ? "" : "?")
              : '<span class="unassigned">Nobody is assigned</span>'}</div>
        ${total != null ? `<div class="sec"><div class="lbl">Bid</div><strong>${money(total)}</strong></div>` : ""}
        ${row.drafted_at ? `<div class="sec"><div class="lbl">Created</div>${esc(TW.fmtBizDate(row.drafted_at))}</div>` : ""}
        <div class="sec row3">
          <button type="button" class="btn btn-p" data-go-files>Open the files</button>
          <button type="button" class="btn btn-s" data-go-edit>Edit the estimate</button>
        </div>
      </div>`;
    d.querySelector(".dclose").addEventListener("click", closeDrawer);
    const go = (u) => window.location.assign(u);
    d.querySelector("[data-go-files]").addEventListener("click",
      () => go("/done.html?d=" + encodeURIComponent(pid) + "&files=1"));
    d.querySelector("[data-go-edit]").addEventListener("click",
      () => go("/?d=" + encodeURIComponent(pid) + "&edit=1"));
  }

  // ── drawer sections ────────────────────────────────────────────────────────
  // The drawer used to be one long scroll — status pills, customer, approval,
  // deposit, contacts, notification chips and the whole chat thread — so a rep
  // scrolled past everything to reach the reply box. It is now tabbed, mirroring
  // the customer portal's tracker so "the customer is on the Deposit step" means
  // the same thing in both apps. Chat is its own tab: a long thread must not
  // push the deposit and contact sections off screen.
  //
  // Two pieces of state, deliberately kept apart so they cannot fight over who
  // owns `.hidden`: SEC_ELIGIBLE says which cards APPLY given the project's
  // state, ACTIVE_SEC says which tab is ON SCREEN. Only applySecPanel() reads
  // both and touches visibility — nothing else may.
  const SEC_TABS = {
    proposal: ["dsec-customer", "dsec-recipients", "dsec-approved", "dsec-notify"],
    deposit:  ["dsec-deposit"],
    contacts: ["dsec-contacts"],
    // No `schedule`. Hanz removed scheduling from both apps on 2026-08-11, the Mark scheduled
    // button and its customer email included: Treadwell books the date on the phone and the
    // customer hears it there, so the app had a status, a tile and a notification all restating
    // a call that had already happened. schedule_status stays in the database untouched.
    chat:     ["dsec-chat"],
    followup: ["dsec-followup"],
  };
  const ALL_SEC_CARDS = Object.values(SEC_TABS).flat();
  const SEC_ELIGIBLE = new Set();
  const setSecEligible = (id, on) => { on ? SEC_ELIGIBLE.add(id) : SEC_ELIGIBLE.delete(id); };

  // Module-level, because renderDetail re-runs after every action (act() calls
  // openDetail again) and a local would be wiped each time.
  let ACTIVE_SEC = null;
  let CUR_PID = null;            // the drawer is reused across projects
  const REPLY_DRAFT = {};        // unsent text survives the post-action re-render
  const NT_CACHE = {};           // chips per PROJECT, so a poll doesn't refetch them
  let RENDER_GEN = 0;
  let DEEPLINK_USED = false;

  // What the drawer currently shows, same idea as BOARD_SIG. renderDetail replaces the drawer's
  // whole innerHTML including the chat thread, so an unchanged repaint tears down and rebuilds
  // every message for nothing.
  let DRAWER_SIG = "";
  // Recipients of the proposal currently open. Module-scoped because msgHtml is called per
  // message and threading it through every call site would touch a dozen signatures.
  let DETAIL_RECIPIENTS = [];
  // The last payload per project, so a refresh can render from memory instead of blanking the
  // drawer while it waits on the network. Bounded by projects opened in one session.
  const DETAIL_CACHE = {};
  // Which detail fetch is current; an older one must not paint. Separate from RENDER_GEN, which
  // counts RENDERS (chips use it to detect a re-render mid-fetch).
  let DETAIL_GEN = 0;
  // Where the chat thread was scrolled to just before the drawer was torn down. Captured in
  // renderDetail, consumed once by applySecPanel's next frame.
  let THREAD_SCROLL = null;

  /** Show only the active tab's eligible cards. The single place that sets
   *  visibility — see the note above. */
  function applySecPanel() {
    const sec = SEC_TABS[ACTIVE_SEC] ? ACTIVE_SEC : "proposal";
    for (const id of ALL_SEC_CARDS) {
      const el = $(id);
      if (!el) continue;
      el.classList.toggle("hidden", !((SEC_TABS[sec] || []).includes(id) && SEC_ELIGIBLE.has(id)));
    }
    for (const key of Object.keys(SEC_TABS)) {
      const panel = $("dpanel-" + key);
      if (panel) panel.classList.toggle("hidden", key !== sec);
    }
    // aria in the SAME loop as the class, so a screen reader can never disagree
    // with what is painted.
    const drawer = $("drawer");
    drawer.querySelectorAll(".dtabs .step").forEach((b) => {
      const on = b.dataset.sec === sec;
      b.classList.toggle("is-active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
      b.tabIndex = on ? 0 : -1;
    });
    const body = drawer.querySelector(".dbody");
    if (body) body.dataset.sec = sec;                      // arms the chat-scroll CSS
    if (sec === "proposal") loadNotifyChips(CUR_PID, RENDER_GEN);
    if (sec === "chat") requestAnimationFrame(() => {
      const t = $("thread");
      if (!t) return;
      // Consume the capture renderDetail took before it destroyed the old thread. One-shot: a
      // later tab switch must land on the newest message, not on where someone was reading
      // several polls ago.
      const held = THREAD_SCROLL;
      THREAD_SCROLL = null;
      // Reading back through older messages? Stay there. At the bottom, or opening fresh?
      // Follow the newest message down, which is what a live thread should do.
      //
      // A fresh open captures nothing (no #thread existed) and a tab switch captures a hidden
      // node whose metrics all read 0, which counts as "at the bottom" — so both land on the
      // newest message without needing a special case.
      t.scrollTop = (held && !held.atBottom) ? held.top : t.scrollHeight;
    });
  }

  /** The one navigation entry point. `fromKey` keeps focus on the tab strip when
   *  the rep is arrowing along it — moving focus into the panel would end the
   *  keyboard walk after a single press. */
  function focusSection(sec, fromKey) {
    if (!SEC_TABS[sec]) return;                            // never blank the panel
    ACTIVE_SEC = sec;
    applySecPanel();
    requestAnimationFrame(() => {
      // The panel is display:none at call time, so scrolling or focusing it
      // before the next frame is a silent no-op.
      const body = $("drawer").querySelector(".dbody");
      if (body && sec !== "chat") body.scrollTop = 0;
      if (fromKey) { const t = $("dtab-" + sec); if (t) t.focus(); return; }
      const p = $("dpanel-" + sec);
      if (p) p.focus({ preventScroll: true });
    });
  }

  /** Which tab to open on. Answers "why is this drawer open?" — the two
   *  commonest answers, a customer message and a payment, come first.
   *
   *  Sticky WITHIN an open (renderDetail re-runs after every action, and a rep
   *  who just replied must not be thrown off Chat), re-evaluated on each fresh
   *  open (closeDrawer clears ACTIVE_SEC). Deliberately no per-project memory:
   *  remembering the last tab would permanently defeat this routing, since the
   *  board is one session a rep keeps open all day. */
  function defaultSection(p, unread) {
    if (ACTIVE_SEC) return ACTIVE_SEC;
    if (unread > 0) return "chat";
    if (p.deposit_status === "submitted") return "deposit";        // money in, unconfirmed
    // Don't park on Deposit for a job that doesn't collect one — there's nothing
    // to action there. Contacts/schedule is the real next step.
    if (p.proposal_status === "approved" && !p.deposit_requested_at
        && p.deposit_required !== false) return "deposit";
    return "proposal";
  }

  /** Per-project notification chips: who receives THIS project's emails.
   *  Effective state = global roster toggle, overridden per-project (add/mute).
   *  Admins may toggle anyone; other staff only their own address (the server
   *  enforces it too). Loaded only when the Proposal tab is actually on screen,
   *  so replying to a customer no longer costs a round-trip. */
  async function loadNotifyChips(pid, gen) {
    if (!pid) return;
    // Keyed by PROJECT, not by render.
    //
    // The key used to be `pid + "|" + gen`, and gen increments on every render — so the cache
    // never hit across a poll and the chip strip refetched, flashing its own "Loading…" every
    // 12s while the Proposal tab was open. It also grew a new entry per render and never freed
    // one.
    //
    // Storing the PAYLOAD rather than a marker matters: with a pid key, a marker hit would
    // return early and leave the freshly-rendered static "Loading…" markup on screen for good.
    if (NT_CACHE[pid]) { paintNtChips(pid, NT_CACHE[pid], gen); return; }
    try {
      const r = await api("/api/portal/proposal/" + encodeURIComponent(pid) + "/notify-overrides");
      const j = await r.json();
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      NT_CACHE[pid] = j;
      paintNtChips(pid, j, gen);
    } catch (err) {
      const wrap = $("nt-chips");
      if (wrap && gen === RENDER_GEN) wrap.innerHTML = '<span class="note">Could not load notifications: ' + esc(err.message) + "</span>";
    }
  }

  /** Draw the chip strip from an already-fetched payload. Synchronous on purpose: called
   *  straight after the drawer's innerHTML on a cache hit, so the chips appear in the same frame
   *  as everything around them and there is nothing to see flashing. */
  function paintNtChips(pid, j, gen) {
    const me = (window.TWAuth && window.TWAuth.user && window.TWAuth.user()) || {};
    const isAdmin = me.role === "admin" || me.role === "super_admin";
    const myEmail = (me.email || "").toLowerCase();
    // Re-read the node rather than trusting one captured before an await: a re-render mid-fetch
    // would otherwise leave us writing into a detached element.
    const wrap = $("nt-chips");
    if (!wrap || gen !== RENDER_GEN) return;
    const ov = {};                                          // email -> 'add' | 'mute'
    (j.overrides || []).forEach((o) => { ov[String(o.email).toLowerCase()] = o.mode; });
    const seen = {}, people = [];
    (j.roster || []).forEach((m) => { const e = String(m.email).toLowerCase(); seen[e] = 1; people.push({ email: m.email, base: !!m.enabled }); });
    Object.keys(ov).forEach((e) => { if (!seen[e]) people.push({ email: e, base: false }); });   // 'add'ed non-roster person
    wrap.innerHTML = people.map((p) => {
      const e = String(p.email).toLowerCase();
      const mode = ov[e];
      const eff = mode === "add" ? true : mode === "mute" ? false : p.base;
      const canEdit = isAdmin || e === myEmail;
      return `<button class="nt-chip ${eff ? "on" : ""}" data-email="${esc(p.email)}" data-base="${p.base ? 1 : 0}" data-eff="${eff ? 1 : 0}"`
           + `${canEdit ? "" : " disabled"} title="${canEdit ? esc(p.email) : "Only admins can change others"}">`
           + `${plainAvatar(p.email)}${esc(nameOf(p.email))}</button>`;
    }).join("") || '<span class="note">No roster yet — add people on the Notification Sending page.</span>';
    wrap.querySelectorAll(".nt-chip").forEach((b) => b.addEventListener("click", async () => {
      if (b.disabled) return;
      const email = b.dataset.email, base = b.dataset.base === "1", eff = b.dataset.eff === "1";
      const newEff = !eff;
      const mode = (newEff === base) ? "clear" : (newEff ? "add" : "mute");   // clear when back to base
      b.disabled = true;
      try {
        const rr = await api("/api/portal/proposal/" + encodeURIComponent(pid) + "/notify-overrides",
          { method: "PUT", body: JSON.stringify({ email, mode }) });
        const jj = await rr.json().catch(() => ({}));
        if (!rr.ok || jj.ok === false) throw new Error(jj.error || jj.detail || ("HTTP " + rr.status));
        // Repaint the chips, not the drawer.
        //
        // This used to call openDetail(pid), which is now wrong twice over: it would rebuild the
        // entire drawer to update one chip, and the overrides are NOT part of the proposal
        // payload — so the drawer signature would find nothing changed, skip the repaint, and
        // the toggle would never appear to take effect.
        delete NT_CACHE[pid];
        loadNotifyChips(pid, RENDER_GEN);
      } catch (err) {
        const al = $("nt-alert");
        if (al) al.textContent = "Could not update: " + (err.message || "retry");
        b.disabled = false;
      }
    }));
  }

  /** Unread customer messages for the Chat tile. Prefer the server's own number
   *  off the board row, so the badge here always matches the one the rep just
   *  clicked — the server compares message ids, which a positional client-side
   *  walk can disagree with when an inbound email arrives backdated. */
  function unreadCount(pid, msgs) {
    const row = ALL.find((x) => x.proposal_id === pid);
    if (row && row.unread != null) return Number(row.unread) || 0;
    let last = -1;
    (msgs || []).forEach((m, i) => { if (m.author_kind === "staff" && m.msg_type === "text") last = i; });
    return (msgs || []).slice(last + 1)
      .filter((m) => m.author_kind === "customer" && m.msg_type === "text").length;
  }

  function secTab(key, label, o) {
    const badge = o.badge ? `<span class="tab-badge">${esc(o.badge)}</span>` : "";
    // Attention is carried by WORDS and a badge, not tint alone: the rep's
    // browser synthesizes dark mode over this page, so colour can be rewritten.
    return `<button type="button" role="tab" class="step${o.done ? " is-done" : ""}${o.needs ? " needs" : ""}"` +
      ` id="dtab-${key}" data-sec="${key}" aria-controls="dpanel-${key}" aria-selected="false" tabindex="-1"` +
      ` title="${esc(o.hint || "")}" aria-label="${esc(label + ", " + o.val)}">` +
      `<span class="lbl">${esc(label)}${badge}</span><span class="val">${esc(o.val)}</span></button>`;
  }

  function renderSecTabs(s) {
    // "Not required" is a resting state, not a to-do: no needs-attention flag, so
    // the tab doesn't nag about work that isn't wanted. Staff can still open it and
    // send a request manually.
    const dep = s.depositDone ? { done: true, val: "Received" }
      : s.depositSubmitted ? { needs: true, val: "Confirm it" }
      : (s.depositNotRequired && !s.requested) ? { val: "Not required" }
      : (s.approved && !s.requested) ? { needs: true, val: "Send request" }
      : { val: s.requested ? "Requested" : "Pending" };
    return `<div class="dtabs" role="tablist" aria-label="Project sections">` +
      secTab("proposal", "Proposal", { done: s.approved, val: s.approved ? "Approved" : "Awaiting",
        hint: "Customer, approval, notification recipients" }) +
      secTab("deposit", "Deposit", Object.assign({ hint: "Invoice, what the customer submitted, mark received" }, dep)) +
      secTab("contacts", "Contacts", { done: s.contactsDone, val: s.contactsDone ? "Received" : "Pending",
        hint: "Project contacts the customer supplied" }) +
      secTab("chat", "Chat", { needs: s.unread > 0, val: s.unread > 0 ? s.unread + " unread" : "Open",
        badge: s.unread > 0 ? s.unread : "", hint: "Conversation with the customer" }) +
      // Closed-lost is "done" in the sense the tab means it: nothing left to chase.
      // Paused isn't flagged either — the customer asked for the quiet.
      secTab("followup", "Follow-up", { done: s.lost, val: s.fuVal,
        hint: "Automatic follow-ups, what you've chased personally, and the customer's timeline" }) +
      `</div>`;
  }

  // ── deposit submissions ────────────────────────────────────────────────────
  // What the CUSTOMER sent us. Staff act on this, so it renders directly above
  // the deposit buttons. Bank numbers appear here and nowhere else: the routing
  // number in full (it's printed on every check), the account number masked
  // until someone presses Show. Nothing here is ever logged.
  const ACCT_TYPE_LABEL = { checking: "Checking", savings: "Savings" };
  const METHOD_LABEL = { ach: "ACH transfer", check: "Check mailed by the customer" };
  const METHOD_PHRASE = { ach: "ACH details", check: "a mailed check" };

  function mask4(v) {
    const s = String(v == null ? "" : v).replace(/\s/g, "");
    return s.length > 4 ? "••••" + s.slice(-4) : "••••";
  }

  /** One submission card. `secrets` collects the full account numbers by index —
   *  the markup ships masked, so the real value only enters the DOM on Show. */
  function depositHtml(x, secrets) {
    const m = String(x.method || "").toLowerCase();
    const rows = [];
    // `v` is always escaped here; `o.after` is our own markup (the Show button).
    const add = (k, v, o) => {
      if (v == null || v === "") return;
      o = o || {};
      rows.push(`<div class="dep-f"><span class="dep-k">${esc(k)}</span>` +
        `<span class="dep-v${o.num ? " dep-num" : ""}"${o.id ? ` id="${o.id}"` : ""}` +
        `${o.title ? ` title="${esc(o.title)}"` : ""}>${esc(v)}</span>${o.after || ""}</div>`);
    };

    if (m === "ach") {
      add("Account name", x.account_name);
      add("Account type", ACCT_TYPE_LABEL[String(x.account_type || "").toLowerCase()] || x.account_type);
      add("Routing no.", x.routing_number,
          { num: true, title: "Routing number — printed on every check, shown in full" });
      if (x.account_number) {
        const i = secrets.push(String(x.account_number)) - 1;
        add("Account no.", mask4(x.account_number), {
          num: true, id: "dep-acct-" + i,
          title: "Account number — hidden until you show it",
          after: `<button type="button" class="dep-show" data-acct="${i}" aria-pressed="false"` +
                 ` aria-label="Show the full account number">Show</button>`,
        });
      } else if (x.masked_ref) {
        // account_number arrived in a later migration, so a pre-ACH-V1 row has
        // only the last four. Show it HERE rather than in the trail below —
        // rendering both put a stray "••••1234" under the revealed number.
        add("Account no.", x.masked_ref,
            { num: true, title: "Only the last four were recorded for this submission" });
      }
    } else if (m === "check") {
      add("Check no.", x.check_number);
      add("Written by", x.account_name);
    } else {
      add("Method", x.method);
    }
    add("Bank", x.bank_name);
    // WHICH contact paid, on a proposal with two. Full address here because this is the staff
    // drawer and somebody may need to phone them; the customer's own banner gets a first name.
    // Absent on rows written before submitted_by existed, and add() skips empty values.
    if (x.submitted_by) add("Submitted by", nameOf(x.submitted_by), { title: x.submitted_by });
    add("Customer note", x.note);

    // Staff-entered wire/trace details — same fields as before, just grouped.
    const sentTo = [x.sent_to_beneficiary, x.sent_to_bank,
                    x.sent_to_routing ? "rtg " + x.sent_to_routing : "",
                    x.sent_to_account ? "acct " + x.sent_to_account : ""].filter(Boolean).map(esc).join(" / ");
    const trail = [x.sent_date ? "sent " + x.sent_date : "",
                   x.trace_ref ? "trace " + x.trace_ref : ""].filter(Boolean).map(esc).join(" · ");

    return `<div class="dep">
      <div class="dep-h">
        <span class="dep-m">${esc(METHOD_LABEL[m] || (m ? m.toUpperCase() : "Deposit"))}</span>
        <span class="dep-t">${x.submitted_at ? "Submitted " + esc(when(x.submitted_at))
                                             : "Submission time not recorded"}</span>
      </div>
      ${rows.join("")}
      ${trail ? `<div class="dep-s">${trail}</div>` : ""}
      ${sentTo ? `<div class="dep-s">sent to: ${sentTo}</div>` : ""}
    </div>`;
  }

  // System lines read "Heading — detail"; split so they render as a card. Length
  // guard stops a long sentence containing a dash becoming a giant title.
  function splitSystem(body) {
    const s = String(body == null ? "" : body);
    const i = s.indexOf(" — ");
    if (i > 0 && i <= 60) return { title: s.slice(0, i), body: s.slice(i + 3) };
    return { title: "Update", body: s };
  }

  // ── edit the invoice before sending ────────────────────────────────────────
  /** Show the invoice fields for review. Resolves to {amount, invoice} when the
   *  user sends, or null if they cancel. The customer receives this exact
   *  document, so nothing goes out unseen. */
  // Kyle numbers invoices off the job: 23.150-01, then -02 on each resend. So the
  // job no. is recoverable from the last invoice we issued, and the next number is
  // just a bump — no second place to type it. The portal's own TW-INV-##### seq is
  // NOT job-based, so it's excluded.
  function splitInvoiceNo(no) {
    const s = String(no || "").trim();
    const m = /^(.+)-(\d+)$/.exec(s);
    if (!m || /^TW-INV/i.test(s)) return { job: "", seq: 0 };
    return { job: m[1], seq: Number(m[2]) };
  }
  function jobInvoiceNo(job, seq) {
    return job ? job + "-" + String((seq || 0) + 1).padStart(2, "0") : "";
  }

  function editInvoiceDialog(pid, data, depAmt) {
    const p = (data && data.proposal) || {};
    // Central, not the browser's clock: an invoice dated a day ahead because the
    // person raising it is east of Kansas is a document Kyle has to reissue.
    const todayBiz = (window.TW && TW.fmtBizDate)
      ? TW.fmtBizDate(new Date().toISOString()) : new Date().toLocaleDateString("en-US");
    // Prefilled, not blank: an existing job number bumps its own sequence,
    // otherwise fall back to the number the portal would assign anyway.
    const prior = splitInvoiceNo(p.deposit_invoice_no);
    const invoiceNo = jobInvoiceNo(prior.job, prior.seq)
      || p.deposit_invoice_no || (data && data.next_invoice_no) || "";
    const f = [
      ["invoice_no", "Invoice no.", invoiceNo],
      ["invoice_date_text", "Date", todayBiz],
      ["job_number", "Job no.", prior.job],
      ["job_name", "Job name", p.project_name || ""],
      ["customer_name", "Bill to", p.customer_name || p.customer_email || ""],
      ["customer_address", "Address", ""],
      ["city_state", "City, State ZIP", ""],
    ];
    const amt = depAmt != null ? Number(depAmt).toFixed(2) : "";

    return new Promise((resolve) => {
      const ov = document.createElement("div");
      ov.className = "inv-ov";
      ov.innerHTML =
        `<div class="inv-dlg" role="dialog" aria-modal="true" aria-label="Review the invoice">
           <div class="inv-h">Review the deposit invoice</div>
           <p class="inv-sub">This is the document the customer receives. Correct anything before it goes out.</p>
           <div class="inv-grid">
             ${f.map(([k, label, v]) =>
               `<label class="inv-f"><span>${esc(label)}</span>
                  <input data-k="${k}" type="text" value="${esc(v)}"></label>`).join("")}
             <label class="inv-f"><span>Deposit amount</span>
               <input data-k="__amount" type="number" step="0.01" min="0.01" value="${esc(amt)}"></label>
           </div>
           <div class="inv-act">
             <button type="button" class="btn btn-s" data-x>Cancel</button>
             <button type="button" class="btn btn-s" data-preview>Preview PDF</button>
             <button type="button" class="btn btn-p" data-go>Send to customer</button>
           </div>
         </div>`;
      document.body.appendChild(ov);

      const collect = () => {
        const inv = {};
        let amount = null;
        ov.querySelectorAll("input[data-k]").forEach((i) => {
          const v = i.value.trim();
          if (i.dataset.k === "__amount") { amount = v ? Number(v) : null; return; }
          if (v) inv[i.dataset.k] = v;
        });
        return { amount, invoice: inv };
      };
      const close = (val) => { ov.remove(); document.removeEventListener("keydown", onKey); resolve(val); };
      const onKey = (e) => { if (e.key === "Escape") close(null); };
      document.addEventListener("keydown", onKey);

      ov.querySelector("[data-x]").addEventListener("click", () => close(null));
      ov.addEventListener("click", (e) => { if (e.target === ov) close(null); });
      ov.querySelector("[data-go]").addEventListener("click", () => {
        const out = collect();
        if (!(out.amount > 0)) { alert("Enter a deposit amount."); return; }
        close(out);
      });
      // Preview renders the REAL document from the same fields, so what staff
      // approve here is exactly what the customer gets.
      ov.querySelector("[data-preview]").addEventListener("click", async (e) => {
        const b = e.target; const orig = b.textContent;
        b.disabled = true; b.textContent = "Rendering…";
        try {
          const out = collect();
          const r = await api("/api/portal/proposal/" + encodeURIComponent(pid) + "/invoice-preview", {
            method: "POST",
            body: JSON.stringify({ amount: out.amount, invoice: out.invoice }),
          });
          if (!r.ok) throw new Error("HTTP " + r.status);
          const url = URL.createObjectURL(await r.blob());
          window.open(url, "_blank");
          setTimeout(() => URL.revokeObjectURL(url), 60000);
        } catch (err) {
          alert("Couldn't render the preview. " + (err.message || ""));
        } finally { b.disabled = false; b.textContent = orig; }
      });
      // Typing the job no. renumbers the invoice in Kyle's format — until staff
      // edit the invoice box themselves, at which point their value stands.
      const jobIn = ov.querySelector('input[data-k="job_number"]');
      const noIn = ov.querySelector('input[data-k="invoice_no"]');
      let noTouched = false;
      if (noIn) noIn.addEventListener("input", () => { noTouched = true; });
      const syncNo = () => {
        if (noTouched || !jobIn || !noIn) return;
        const job = jobIn.value.trim();
        noIn.value = jobInvoiceNo(job, job === prior.job ? prior.seq : 0)
          || p.deposit_invoice_no || (data && data.next_invoice_no) || "";
      };
      if (jobIn) jobIn.addEventListener("input", syncNo);

      const first = ov.querySelector("input");
      if (first) first.focus();

      // The drawer payload has no address — those live on the draft, and the
      // portal's proposal_id IS the draft id. Fill them in so staff review what
      // will actually print. A blank box just means "use the derived value", so a
      // failure here is harmless.
      (async () => {
        try {
          const r = await api("/api/draft/" + encodeURIComponent(pid));
          const d = ((await r.json()) || {}).data || {};
          const put = (k, v) => {
            const i = ov.querySelector(`input[data-k="${k}"]`);
            if (i && !i.value && v) i.value = v;
          };
          put("customer_address", d.address);
          put("city_state", d.city_state);
          put("job_number", d.job_number);
          syncNo();
        } catch { /* leave blank → server derives it */ }
      })();
    });
  }

  // Our server writes every system row as author_kind 'staff', including the two
  // that record something the CUSTOMER did — so on author_kind alone a customer's
  // own approval would sit on Treadwell's side of the thread. The row carries no
  // actor field, so these prefixes are the only signal available. Reword one in
  // the portal and the card simply falls back to author_kind: it loses its side,
  // nothing breaks.
  const CUSTOMER_EVENTS = ["Approved by", "Project contacts received"];

  /** Which side of the thread a row sits on. Cards are events rather than speech,
   *  but each one still belongs to whoever caused it, so it takes that party's
   *  side — same discriminator the bubbles use. */
  const sideOf = (m) => {
    const body = String(m.body == null ? "" : m.body);
    if (m.msg_type === "system" && CUSTOMER_EVENTS.some((p) => body.startsWith(p))) return "customer";
    return m.author_kind === "staff" ? "staff" : "customer";
  };

  /** Who the proposal went to, and what each of them has actually done.
   *
   *  Hanz, 2026-08-11: "It should then highlight in the CRM who viewed it as well and who
   *  replied." The peer notifications tell the other CONTACT; this tells the estimator, which is
   *  what turns "somebody opened it" into "chase the one who hasn't".
   *
   *  Returns "" for one recipient or none: the card is only meaningful when there is somebody to
   *  distinguish, and setSecEligible gates the tab on the same condition.
   *
   *  NOT nt-chip. That class is the notification roster's, where green means "receives this
   *  project's emails" — reusing it here would say something untrue about every contact.
   */
  function recipientsHtml(rows) {
    const list = rows || [];
    if (list.length < 2) return "";
    const chips = list.map((r) => {
      const badges = [
        r.viewed_at ? `<span class="rc-b on" title="${esc(TW.fmtBizDateTime(r.last_viewed_at || r.viewed_at))}${
          r.view_count > 1 ? ` · ${r.view_count} opens` : ""}">Viewed</span>`
                    : '<span class="rc-b">Not viewed</span>',
        r.replied ? '<span class="rc-b on">Replied</span>' : "",
        r.paid ? '<span class="rc-b on">Paid</span>' : "",
        r.approved ? '<span class="rc-b on">Approved</span>' : "",
      ].filter(Boolean).join("");
      // Full address in the title, not on screen: staff may need it to phone somebody, and the
      // chip has to stay readable with four badges on it.
      return `<div class="rc-chip" title="${esc(r.email)}">${avatar(r.email)}<span class="rc-n">${
        esc(r.name || r.email)}</span>${badges}</div>`;
    }).join("");
    return `<div class="sec" id="dsec-recipients">
      <div class="lbl">Recipients (${list.length})</div>
      <div class="rc-list">${chips}</div>
    </div>`;
  }

  function msgHtml(m) {
    const t = when(m.created_at);
    // These three render as CARDS, matching the customer portal exactly, so staff
    // see the thread the same way the customer does.
    // 'deposit_submitted' is customer-authored (that's what routes it to the bell),
    // but it's a status line, not something they typed — card it like the portal
    // does, or it renders as a speech bubble putting our words in their mouth.
    // It still lands on their side, because they are the ones who did it.
    if (m.msg_type === "system" || m.msg_type === "deposit_submitted") {
      const s = splitSystem(m.body);
      return `<div class="chat-card system ${sideOf(m)}"><div class="cc-title">${esc(s.title)}</div>
        <div class="cc-body">${esc(s.body)}</div></div>`;
    }
    if (m.msg_type === "proposal_card") {
      // A revised estimate posts a new card and retires the old one, so the thread
      // shows which version is current instead of two identical-looking cards.
      const meta = m.meta || {};
      const dead = !!meta.superseded;
      const rev = meta.revision_no;
      const title = (rev && rev > 1) ? `Revision ${esc(rev)} of the proposal` : "Your proposal is ready";
      return `<div class="chat-card proposal ${sideOf(m)}${dead ? " is-superseded" : ""}">
        <div class="cc-title">${title}${dead ? ' <span class="cc-tag">Superseded</span>' : ""}</div>
        ${dead && meta.superseded_by ? `<div class="cc-meta">Replaced by revision ${esc(meta.superseded_by)}</div>` : ""}
        <div class="cc-body">${esc(m.body)}</div></div>`;
    }
    if (m.msg_type === "deposit_request") {
      const meta = m.meta || {};
      const amt = meta.amount != null ? money(meta.amount) : "";
      const dead = !!meta.superseded;   // replaced by a later resend
      const line = meta.invoice_no
        ? `Invoice ${esc(meta.invoice_no)}${meta.reference ? ` · Reference ${esc(meta.reference)}` : ""}`
          + (dead && meta.superseded_by ? ` · replaced by ${esc(meta.superseded_by)}` : "")
        : "";
      return `<div class="chat-card deposit ${sideOf(m)}${dead ? " is-superseded" : ""}">
        <div class="cc-title">Deposit invoice${amt ? ` — <span class="cc-amt">${amt}</span>` : ""}${
          dead ? ' <span class="cc-tag">Superseded</span>' : ""}</div>
        ${line ? `<div class="cc-meta">${line}</div>` : ""}
        <div class="cc-body">${esc(m.body)}</div></div>`;
    }
    const staff = m.author_kind === "staff";
    const viaEmail = m.meta && m.meta.source === "email";
    // WHICH contact said it — but only when there is more than one, because with a single
    // contact the name adds nothing and the label was removed for exactly that reason. This is
    // the one thing the side of the bubble cannot tell you on a multi-recipient proposal.
    const many = (DETAIL_RECIPIENTS || []).length > 1;
    const who = !staff && many && m.author_email ? nameOf(m.author_email) : "";
    // Hanz, 2026-08-11: "can we simplify it to just the reply contents and the date? just
    // specify if its from email". The "TREADWELL" / "CUSTOMER" line said nothing the side of
    // the thread does not already say — red and right-aligned is us, grey and left is them —
    // and it cost a line of chrome on every bubble. Where the message CAME FROM is the part
    // that isn't inferable, so that is what stays, next to the date.
    return `<div class="msg ${staff ? "staff" : "customer"}">
      ${who ? `<div class="who" title="${esc(m.author_email)}">${esc(who)}</div>` : ""}
      <div class="mbody">${esc(m.body)}</div>
      <div class="when">${t}${viaEmail ? ' <span class="via-email">via email</span>' : ""}</div>
    </div>`;
  }

  // ── follow-up section ──────────────────────────────────────────────────────
  // Everything about chasing this proposal in one place: whether the automation is
  // running, what it has already sent, what a human did personally, and what the
  // customer said about their timeline. The digest reads the same log, so a logged
  // call here is what stops tomorrow morning recommending this proposal again.
  // The portal STORES the staff kinds prefixed (`staff_call`), and accepts the short
  // form the drawer posts. Both are mapped, because the log renders what came back
  // from the server, not what we sent.
  const FU_KIND_LABEL = {
    staff_call: "Call", staff_email: "Email", staff_text: "Text", staff_note: "Note",
    call: "Call", email: "Email", text: "Text", note: "Note",
    auto_email: "Automatic email", customer_status: "Customer update",
  };
  // `template`, not `rule` — the worker records what it SENT. The rule key that
  // deduped it is scheduling bookkeeping and means nothing to an estimator.
  const FU_TEMPLATE_LABEL = {
    not_viewed: "Nudge — not opened yet",
    next_steps: "Next steps after viewing",
    second_nudge: "Second nudge",
    checkin: "Check-in",
  };
  // Bookkeeping the portal writes as a `staff_note` with an `action` key.
  const FU_ACTION = {
    reassigned: "Reassigned", automation_on: "Automation on", automation_off: "Automation off",
    paused: "Paused", closed_lost: "Closed lost", reactivated: "Reactivated",
  };
  const STATUS_LABEL = { delayed: "Delayed", not_moving_forward: "Not moving forward", resume: "Back on" };

  /** One line of the follow-up log. Every kind renders — including the automation's
   *  own sends, because "the system already emailed them twice this week" is exactly
   *  what an estimator needs before picking up the phone. */
  function followupRow(f) {
    const d = f.detail || {};
    const kind = String(f.kind || "");
    let what = FU_KIND_LABEL[kind] || kind;
    let detail = d.note || "";
    if (kind === "auto_email") {
      what = FU_TEMPLATE_LABEL[d.template] || "Automatic email";
      detail = d.audience === "staff" ? "sent to the estimator" : "sent to the customer";
    } else if (kind === "customer_status") {
      what = "Customer: " + (STATUS_LABEL[d.status] || d.status || "update");
      detail = [d.months ? d.months + " month" + (d.months === 1 ? "" : "s") : "",
                d.reason ? (C.LOST_REASON[d.reason] || d.reason) : "",
                d.note || ""].filter(Boolean).join(" · ");
    } else if (d.action) {
      // Bookkeeping, not outreach. Named so the log reads as a history of the
      // project rather than a row saying "System" with nothing after it.
      what = FU_ACTION[d.action] || "System";
      detail = d.action === "reassigned" ? "to " + (d.to ? nameOf(d.to) : "?")
        : d.action === "paused" ? (d.until ? "until " + TW.fmtBizDay(d.until) : "")
        : d.action === "closed_lost" ? (C.LOST_REASON[d.reason] || d.reason || "")
        : "";
    }
    return `<div class="fu-row">
      <span class="fu-k">${esc(what)}</span>
      <span class="fu-d">${esc(detail)}</span>
      <span class="fu-t">${esc(TW.fmtBizDate(f.created_at))}${f.by ? " · " + esc(nameOf(f.by)) : ""}</span>
    </div>`;
  }

  /** How the follow-up tab summarises itself, and what the panel leads with. One
   *  sentence — an estimator opening this tab is asking "is anything chasing this?" */
  function followupState(p) {
    const f = fu(p);
    if (isLost(p)) {
      const why = lostReason(p);
      return { val: "Closed lost", lead: "The customer said they aren't moving forward"
        + (why ? " — " + why.toLowerCase() : "") + ". Nothing is being sent." };
    }
    const until = pausedUntil(p);
    if (until) return { val: "Paused", lead: "The customer asked us to come back to this. Follow-ups resume "
      + TW.fmtBizDay(until) + "." };
    if (!f.enrolled) return { val: "Not automated", lead:
      "This proposal was sent before automatic follow-ups existed. Switch them on to start the cadence from today." };
    if (!f.enabled) return { val: "Off", lead:
      "Automatic follow-ups are off for this project. Nothing is sent to the customer unless you send it." };
    return { val: "On", lead:
      "Following up automatically until the customer approves, replies, or tells us their timeline changed." };
  }

  function followupPanelHtml(p, data) {
    const f = fu(p), st = followupState(p), enabled = !!f.enabled && !isLost(p);
    const log = (data.followups || []).map(followupRow).join("")
      || '<p class="note">Nothing logged yet.</p>';
    const assignee = p.assigned_estimator || "";
    return `
      <div class="sec" id="dsec-followup">
        <div class="lbl">Follow-up</div>
        <p class="note" id="fu-lead">${esc(st.lead)}</p>
        <div id="fu-alert" class="note fu-alert"></div>

        <div class="fu-line">
          <button class="btn btn-s" id="fu-toggle" ${isLost(p) ? "disabled" : ""}
            title="${isLost(p) ? "This proposal is closed — reactivate it first"
                   : enabled ? "Stop sending automatic follow-ups for this project"
                             : "Start the follow-up cadence from today"}">${
            enabled ? "Turn automation off" : "Turn automation on"}</button>
        </div>

        <div class="lbl fu-lbl">Log what you did</div>
        <p class="note">Recording a call or a text keeps this proposal out of tomorrow's digest — and tells whoever picks it up next what already happened.</p>
        <div class="fu-line">
          <select id="fu-kind" class="tw-select" aria-label="What you did">
            <option value="call">Call</option>
            <option value="email">Email</option>
            <option value="text">Text</option>
            <option value="note">Note</option>
          </select>
          <input id="fu-note" type="text" class="fu-note" maxlength="2000"
                 placeholder="Left a voicemail with Dave — will try Thursday" aria-label="Note" />
          <button class="btn btn-s" id="fu-log">Log it</button>
        </div>

        <div class="lbl fu-lbl">Assigned to</div>
        <div class="fu-line">
          ${assignee ? avatar(assignee) : ""}
          <select id="fu-assign" class="tw-select" aria-label="Assigned estimator">
            <option value="${esc(assignee)}">${assignee ? esc(nameOf(assignee)) : "Loading…"}</option>
          </select>
          <button class="btn btn-s" id="fu-reassign" disabled>Reassign</button>
        </div>
        <p class="note">${assignee
          ? "They get this project's follow-up emails and its line in the morning digest."
          : "Nobody is assigned. The digest skips unassigned proposals, so this one is being chased by nobody."}</p>

        <div class="lbl fu-lbl">The customer's timeline</div>
        <p class="note">Use these when a customer tells you by phone instead of clicking the link in their email. The customer is not emailed.</p>
        <div class="fu-line">
          ${isLost(p)
            ? '<button class="btn btn-s" id="fu-reopen">Reactivate this proposal</button>'
            : `<select id="fu-months" class="tw-select" aria-label="Delay by">
                 <option value="1">1 month</option><option value="2">2 months</option>
                 <option value="3">3 months</option><option value="4">4+ months</option>
               </select>
               <button class="btn btn-s" id="fu-delay">Mark delayed</button>
               <button class="btn btn-s" id="fu-lost">Mark closed lost</button>`}
        </div>

        ${followupContactsHtml(data.recipient_activity)}

        <div class="lbl fu-lbl">History</div>
        <div class="fu-log">${log}</div>
      </div>`;
  }

  /** Who the automated follow-ups go to, and the controls to change it.
   *
   *  Hanz, 2026-08-12: "on this project container on the follow ups we must have the ability to
   *  add or remove COntacts who receive the follow ups."
   *
   *  UN-TICKING IS NOT REMOVING THE CONTACT, and the copy says so, because the two are one click
   *  apart and only one of them is reversible without consequence: the contact keeps the
   *  proposal, the invoice and every reply, and only the chasing stops. Revoking access is a
   *  different act and is not offered here.
   *
   *  Rendered even for a single contact, unlike the Recipients card on the Proposal tab — "is
   *  this person being chased" is worth answering for one contact, whereas "which of them
   *  replied" is not.
   */
  function followupContactsHtml(rows) {
    const list = rows || [];
    if (!list.length) return "";
    const chips = list.map((r) => `
      <label class="fu-c" title="${esc(r.email)}">
        <input type="checkbox" data-fu-contact="${esc(r.email)}"${r.followups ? " checked" : ""}>
        <span>${esc(r.name || r.email)}</span>
      </label>`).join("");
    return `
      <div class="lbl fu-lbl">Automated follow-ups go to</div>
      <p class="note">Un-tick somebody and they still get the proposal, the invoice and every
        reply — they just stop being chased.</p>
      <div class="fu-clist">${chips}</div>
      <div class="fu-line">
        <input id="fu-add-contact" class="tw-input" type="email" autocomplete="off"
               placeholder="Add a contact — name@company.com">
        <button class="btn btn-s" id="fu-add-contact-btn">Add</button>
      </div>
      <p class="note" id="fu-c-alert"></p>`;
  }

  /** Wire the follow-up panel. Called from renderDetail, so every handler is bound
   *  against the CURRENT render — `act` already re-opens the drawer on success. */
  function wireFollowup(pid, p, act) {
    const alert = (msg) => { const el = $("fu-alert"); if (el) el.textContent = msg || ""; };
    const path = (suffix) => "/api/portal/proposal/" + encodeURIComponent(pid) + suffix;

    // ── who gets chased ───────────────────────────────────────────────────
    // Delegated on the list rather than per checkbox: renderDetail rebuilds this panel on every
    // 12s poll and after every action, so per-element listeners would be re-bound continually.
    const cAlert = (m) => { const el = $("fu-c-alert"); if (el) el.textContent = m || ""; };
    const clist = document.querySelector(".fu-clist");
    if (clist) clist.addEventListener("change", (e) => {
      const box = e.target.closest("[data-fu-contact]");
      if (!box) return;
      cAlert("");
      act(path("/followup-recipient"), box,
          { body: JSON.stringify({ email: box.dataset.fuContact, enabled: box.checked }) });
    });

    const addC = $("fu-add-contact-btn");
    if (addC) addC.addEventListener("click", (e) => {
      const input = $("fu-add-contact");
      const email = (input.value || "").trim().toLowerCase();
      // Shape-checked here so an obvious typo does not cost a round trip; the portal re-validates,
      // because this is the field that decides who gets sent a link to the proposal.
      if (!email || !/^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$/.test(email)) {
        cAlert("That doesn't look like an email address.");
        input.focus();
        return;
      }
      cAlert("");
      // `add: true` also sends them the proposal link — they cannot reach the portal without one.
      act(path("/followup-recipient"), e.target,
          { body: JSON.stringify({ email, add: true, enabled: true }) });
    });
    const addCIn = $("fu-add-contact");
    if (addCIn) addCIn.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); addC.click(); }
    });

    const toggle = $("fu-toggle");
    if (toggle) toggle.addEventListener("click", (e) => {
      const on = !(fu(p).enabled && !isLost(p));
      act(path("/followup-automation"), e.target, { body: JSON.stringify({ enabled: on }) });
    });

    const logBtn = $("fu-log");
    if (logBtn) logBtn.addEventListener("click", (e) => {
      alert("");
      const kind = $("fu-kind").value, note = $("fu-note").value.trim();
      // A bare "Call" with no note is still worth logging — it's the timestamp that
      // suppresses the digest — so an empty note is not an error.
      act(path("/followups"), e.target, { body: JSON.stringify({ kind, note }) });
    });
    const noteIn = $("fu-note");
    if (noteIn) noteIn.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); logBtn.click(); }
    });

    const delay = $("fu-delay");
    if (delay) delay.addEventListener("click", async (e) => {
      const months = Number($("fu-months").value) || 1;
      const ok = await TW.confirmDanger({
        title: "Pause follow-ups?",
        before: "Stop chasing ", name: p.project_name || "this project",
        after: " for " + months + " month" + (months === 1 ? "" : "s") + "?",
        detail: "Nothing is sent to the customer until then. They aren't emailed about this.",
        confirmText: "Pause", cancelText: "Keep chasing", tone: "warn", icon: "⏸",
      });
      if (!ok) return;
      act(path("/status"), e.target, { body: JSON.stringify({ status: "delayed", months }) });
    });

    const lost = $("fu-lost");
    if (lost) lost.addEventListener("click", async (e) => {
      const why = await lostReasonDialog(p);
      if (!why) return;
      act(path("/status"), e.target, { body: JSON.stringify({ status: "closed_lost", reason: why }) });
    });

    const reopen = $("fu-reopen");
    if (reopen) reopen.addEventListener("click", (e) =>
      act(path("/status"), e.target, { body: JSON.stringify({ status: "active" }) }));

    // The estimator list is a separate fetch, so the control starts disabled and
    // opens only once there is something real to pick.
    const sel = $("fu-assign"), btn = $("fu-reassign");
    if (sel && btn) {
      const cur = String(p.assigned_estimator || "").toLowerCase();
      loadEstimators().then((people) => {
        if (!$("fu-assign")) return;                       // re-rendered mid-fetch
        if (!people.length) { sel.innerHTML = '<option value="">Unavailable</option>'; return; }
        const known = people.some((x) => String(x.email).toLowerCase() === cur);
        sel.innerHTML = (!cur ? '<option value="">Choose an estimator…</option>' : "")
          // Whoever is assigned stays listed even if they've since left the roster —
          // silently dropping them would make the control read as "unassigned".
          + (cur && !known ? `<option value="${esc(cur)}">${esc(nameOf(cur))} (no longer listed)</option>` : "")
          + people.map((x) => `<option value="${esc(x.email)}">${esc(x.name)}</option>`).join("");
        sel.value = p.assigned_estimator || "";
        btn.disabled = true;
        sel.addEventListener("change", () => {
          btn.disabled = !sel.value || sel.value.toLowerCase() === cur;
        });
      });
      btn.addEventListener("click", (e) => {
        if (!sel.value) return;
        act(path("/assign"), e.target, { body: JSON.stringify({ estimator_email: sel.value }) });
      });
    }
  }

  /** Why we lost it. Free text would make the reasons uncountable, so this offers
   *  the same six the customer's own form does — the two have to agree for a
   *  "why do we lose bids?" question to have an answer. */
  function lostReasonDialog(p) {
    return new Promise((resolve) => {
      const ov = document.createElement("div");
      ov.className = "inv-ov";
      ov.innerHTML = `<div class="inv-dlg" role="dialog" aria-modal="true" aria-label="Mark closed lost">
        <div class="inv-h">Mark this closed lost?</div>
        <p class="inv-sub">${esc(p.project_name || "This project")} moves out of the pipeline and all follow-ups stop.
          The customer is not emailed. You can reactivate it later.</p>
        <label class="inv-f" style="text-transform:none;letter-spacing:0;font-size:12.5px">
          <span>Why?</span>
          <select data-why>${Object.keys(C.LOST_REASON).map((k) =>
            `<option value="${esc(k)}">${esc(C.LOST_REASON[k])}</option>`).join("")}</select>
        </label>
        <div class="inv-act">
          <button type="button" class="btn btn-s" data-x>Cancel</button>
          <button type="button" class="btn btn-p" data-go>Mark closed lost</button>
        </div></div>`;
      document.body.appendChild(ov);
      const close = (v) => { ov.remove(); document.removeEventListener("keydown", onKey); resolve(v); };
      const onKey = (e) => { if (e.key === "Escape") close(null); };
      document.addEventListener("keydown", onKey);
      ov.querySelector("[data-x]").addEventListener("click", () => close(null));
      ov.addEventListener("click", (e) => { if (e.target === ov) close(null); });
      ov.querySelector("[data-go]").addEventListener("click", () =>
        close(ov.querySelector("[data-why]").value || "other"));
      ov.querySelector("[data-why]").focus();
    });
  }

  /** The active roster, fetched once per page. Reassign is rare and the list barely
   *  changes, so re-fetching it on every drawer open would be pure waste. */
  let EST_LIST = null;
  function loadEstimators() {
    if (EST_LIST) return EST_LIST;
    EST_LIST = api("/api/estimators")
      .then((r) => r.json())
      .then((j) => (j && j.estimators) || [])
      .catch(() => {
        EST_LIST = null;                 // a blip must not poison the page for good
        return [];
      });
    return EST_LIST;
  }

  function renderDetail(pid, data) {
    const p = data.proposal, a = data.approval;
    const approved = p.proposal_status === "approved";
    const depositDone = p.deposit_status === "received";
    const depositSubmitted = p.deposit_status === "submitted";
    // Sent without a deposit (typical for GC). Manual invoicing is still offered.
    const depositNotRequired = p.deposit_required === false && !p.deposit_requested_at;
    const contactsDone = p.contacts_status === "received";

    // Full chat thread (fallback to the legacy text-only questions if a pre-PP1
    // portal hasn't shipped yet).
    const msgs = (data.messages && data.messages.length)
      ? data.messages
      : (data.questions || []).map((q) => Object.assign({ msg_type: "text" }, q));
    const thread = msgs.map(msgHtml).join("") || '<p class="note">No messages yet.</p>';

    const contacts = (data.contacts || []).map((c) =>
      `<div class="note" style="margin-bottom:4px"><strong>${esc(ROLE_LABEL[c.role] || c.role)}</strong>: ${esc(c.name)}` +
      `${c.email ? " · " + esc(c.email) : ""}${c.phone ? " · " + esc(c.phone) : ""}</div>`).join("")
      || '<p class="note">No contacts submitted yet.</p>';

    // Full account numbers stay in this array, NOT in the markup — see depositHtml.
    const acctFull = [];
    const deposits = (data.deposits || []).map((x) => depositHtml(x, acctFull)).join("");

    const approvedOpts = a && a.options && a.options.length ? a.options.join(", ") : (a ? a.option : "");
    const depAmt = p.deposit_amount != null ? p.deposit_amount : (a ? a.total * 0.25 : null);

    const unread = unreadCount(pid, msgs);

    // Nothing changed? Leave the DOM alone. This is the guard that makes the 12s drawer poll
    // invisible: without it every tick destroyed the thread, the tab strip and every card, and
    // threw away wherever the rep had scrolled.
    //
    // `unread` is in the signature because it is read off the BOARD row, not this payload, so it
    // can move while the proposal itself is unchanged — and it drives the Chat badge. ACTIVE_SEC
    // deliberately is NOT: switching tabs only toggles classes, it never re-renders, so putting
    // it here would repaint the whole drawer on every tab click.
    const sig = JSON.stringify([pid, data, unread]);
    if (sig === DRAWER_SIG) return;
    DRAWER_SIG = sig;

    // Set BEFORE the markup below is built: msgHtml reads it to decide whether to name the
    // author, and a message rendered before it is populated would go unnamed. `data` is already
    // in the signature above, so a recipient being added repaints on its own.
    DETAIL_RECIPIENTS = (data && data.recipients) || [];

    // Where the chat was, before the innerHTML below detaches it. Must happen here rather than
    // in the caller: renderDetail is the only place that destroys #thread, and every path
    // through it — poll, action, reply, chip toggle — needs the position kept.
    const t0 = $("thread");
    THREAD_SCROLL = t0
      ? { top: t0.scrollTop, atBottom: t0.scrollHeight - t0.scrollTop - t0.clientHeight < 40 }
      : null;

    ACTIVE_SEC = defaultSection(p, unread);

    // The tab strip is a THIRD flex item between .dhead and .dbody, not a child
    // of .dbody: #drawer is a flex column and .dhead pins by flex:0 0 auto, so a
    // sibling pins for free — no position:sticky, no z-index, and no fight with
    // .dbody's top padding.
    $("drawer").innerHTML = `
      <div class="dhead">
        <h2>${esc(p.project_name || "Proposal")}</h2>
        <button class="dclose" aria-label="Close">&times;</button>
      </div>
      ${renderSecTabs({ approved, depositDone, depositSubmitted, depositNotRequired,
                        contactsDone,
                        requested: !!p.deposit_requested_at, unread,
                        lost: isLost(p), fuVal: followupState(p).val })}
      <div class="dbody">
       <div class="dpanel" id="dpanel-proposal" role="tabpanel" aria-labelledby="dtab-proposal" tabindex="-1">
        <div class="sec" id="dsec-customer"><div class="lbl">Customer</div>${esc(p.customer_name || "")} &lt;${esc(p.customer_email)}&gt;<br>
          <a class="link" href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.url)}</a></div>
        ${recipientsHtml(data.recipient_activity)}
        ${a ? `<div class="sec" id="dsec-approved"><div class="lbl">Approved</div>${esc(a.name)}${a.title ? ", " + esc(a.title) : ""}
          on ${esc(a.date || "")} — <strong>${esc(approvedOpts || "")}</strong> at <strong>${money(a.total)}</strong>${
            a.approver_email ? `<div class="note" style="margin-top:2px">signed in as ${esc(nameOf(a.approver_email))} &lt;${esc(a.approver_email)}&gt;</div>` : ""}</div>` : ""}

        <div class="sec" id="dsec-notify">
          <div class="lbl">Notifications for this project</div>
          <p class="note" id="nt-help" style="margin:0 0 4px">Green = receives this project's emails. Overrides the global roster for this project only. Toggling never sends an email; it only sets who's notified when a customer next replies, approves, or pays.</p>
          <div id="nt-alert" class="note" style="margin:4px 0"></div>
          <div id="nt-chips" class="nt-chips"><span class="note">Loading…</span></div>
        </div>
       </div>

       <div class="dpanel" id="dpanel-deposit" role="tabpanel" aria-labelledby="dtab-deposit" tabindex="-1">
        <div class="sec" id="dsec-deposit">
          <div class="lbl">Deposit</div>
          ${depositNotRequired
            ? `<div class="note">Sent without a deposit — nothing was invoiced and the customer sees no Deposit step. You can still send a request below if the terms change (25% would be ${depAmt != null ? money(depAmt) : "—"}).</div>`
            : `<div class="note">Auto-calculated (25%): <strong>${depAmt != null ? money(depAmt) : "—"}</strong>${data.deposit_ref ? ` · match ref <strong>${esc(data.deposit_ref)}</strong> on the statement` : ""}${p.deposit_requested_at ? ` · requested ${when(p.deposit_requested_at)}` : ""}</div>`}
          ${deposits
            ? `<div class="lbl dep-lbl">Deposit submissions</div>${deposits}`
            : '<p class="note dep-none">Nothing submitted by the customer yet.</p>'}
          <div class="row3" style="margin-top:8px">
            <button class="btn btn-p" id="send-deposit-req" ${approved ? "" : "disabled"} title="${approved ? "" : "Available once the customer approves"}">${p.deposit_requested_at ? "Resend deposit request" : "Send deposit request"}</button>
            <button class="btn btn-s" id="mark-deposit" ${depositDone ? "disabled" : ""}>Mark deposit received</button>
          </div>
        </div>
       </div>

       <div class="dpanel" id="dpanel-contacts" role="tabpanel" aria-labelledby="dtab-contacts" tabindex="-1">
        <div class="sec" id="dsec-contacts">
          <div class="lbl">Project contacts</div>
          ${contacts}
        </div>
       </div>


       <div class="dpanel" id="dpanel-chat" role="tabpanel" aria-labelledby="dtab-chat" tabindex="-1">
        <div class="sec" id="dsec-chat">
          <div id="thread">${thread}</div>
          <div id="chat-compose">
            <div id="reply-alert" class="note" style="margin:6px 0;"></div>
            <textarea id="reply-body" placeholder="Reply to the customer…">${esc(REPLY_DRAFT[pid] || "")}</textarea>
            <div style="margin-top:8px;"><button class="btn btn-p" id="reply-btn">Send reply</button></div>
          </div>
        </div>
       </div>

       <div class="dpanel" id="dpanel-followup" role="tabpanel" aria-labelledby="dtab-followup" tabindex="-1">
        ${followupPanelHtml(p, data)}
       </div>
      </div>`;

    const gen = ++RENDER_GEN;
    // Which cards APPLY. Every id in SEC_TABS must appear here or it can never
    // render — the portal shipped two bugs from exactly this omission.
    setSecEligible("dsec-customer", true);
    // Only when there is somebody to distinguish. One contact needs no per-contact card, and an
    // eligible-but-empty card is how the drawer grows tabs that lead nowhere. Registered in
    // SEC_TABS above AND here: a card in one but not the other either never renders or renders
    // in a tab that cannot be reached, and both have gone wrong in this file before.
    setSecEligible("dsec-recipients", ((data.recipient_activity || []).length > 1));
    setSecEligible("dsec-approved", !!a);
    setSecEligible("dsec-notify", true);
    setSecEligible("dsec-deposit", true);
    setSecEligible("dsec-contacts", true);
    setSecEligible("dsec-chat", true);
    setSecEligible("dsec-followup", true);

    const d = $("drawer");
    d.querySelector(".dclose").addEventListener("click", closeDrawer);

    // Reveal / re-hide a full account number. The value lives in `acctFull`, so it
    // only reaches the DOM when a human asks for it — and goes back on a second click.
    d.querySelectorAll(".dep-show").forEach((b) => b.addEventListener("click", () => {
      const i = Number(b.dataset.acct);
      const el = d.querySelector("#dep-acct-" + i);
      if (!el || acctFull[i] == null) return;
      const shown = b.getAttribute("aria-pressed") === "true";
      el.textContent = shown ? mask4(acctFull[i]) : acctFull[i];
      el.title = shown ? "Account number — hidden until you show it" : "Full account number";
      b.setAttribute("aria-pressed", shown ? "false" : "true");
      b.setAttribute("aria-label", (shown ? "Show" : "Hide") + " the full account number");
      b.textContent = shown ? "Show" : "Hide";
    }));

    const act = async (path, btn, opts) => {
      btn.disabled = true; const orig = btn.textContent; btn.textContent = "Working…";
      try {
        const r = await api(path, Object.assign({ method: "POST" }, opts || {}));
        const j = await r.json().catch(() => ({}));
        if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
        await openDetail(pid);   // refresh drawer
        load();                  // refresh board
      } catch (err) {
        btn.textContent = "Failed — " + (err.message || "retry"); btn.disabled = false;
        setTimeout(() => { btn.textContent = orig; }, 2600);
      }
    };

    $("send-deposit-req").addEventListener("click", async (e) => {
      const btn = e.target;
      if (btn.disabled) return;
      // Review + edit the actual invoice before it goes out — the customer sees
      // this document, so staff get the last word on every field.
      // `data`, not `d` — `d` is the drawer ELEMENT; passing it left every field blank.
      const edits = await editInvoiceDialog(pid, data, depAmt);
      if (!edits) return;
      act("/api/portal/proposal/" + encodeURIComponent(pid) + "/deposit-request", btn, {
        body: JSON.stringify({ amount: edits.amount, invoice: edits.invoice }),
      });
    });
    // Confirm first. This tells the customer, in their thread and by email, that
    // the money is in and asks for project contacts — far too loud for a stray click.
    $("mark-deposit").addEventListener("click", async (e) => {
      const btn = e.target;
      if (btn.disabled) return;
      const sub = (data.deposits || []).find((x) => x.submitted_at) || (data.deposits || [])[0];
      const what = sub
        ? "The customer submitted " + (METHOD_PHRASE[String(sub.method || "").toLowerCase()] || "a deposit")
          + (sub.submitted_at ? " on " + when(sub.submitted_at) : "") + ". "
        : "No submission is on file for this project. ";
      const ok = await TW.confirmDanger({
        title: "Mark the deposit as received?",
        before: "Record the deposit for ", name: p.project_name || "this project", after: " as received?",
        detail: what + "Check the money has actually landed — the customer is told it's in.",
        confirmText: "Mark received", cancelText: "Not yet", tone: "warn", icon: "💵",
      });
      if (!ok) return;
      act("/api/portal/proposal/" + encodeURIComponent(pid) + "/deposit-received", btn);
    });
    wireFollowup(pid, p, act);

    $("reply-body").addEventListener("input", (e) => { REPLY_DRAFT[pid] = e.target.value; });

    $("reply-btn").addEventListener("click", async () => {
      const body = $("reply-body").value.trim();
      if (!body) return;
      const btn = $("reply-btn"); btn.disabled = true; btn.textContent = "Sending…";
      try {
        const r = await api("/api/portal/proposal/" + encodeURIComponent(pid) + "/reply",
          { method: "POST", body: JSON.stringify({ body }) });
        const j = await r.json().catch(() => ({}));
        if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
        delete REPLY_DRAFT[pid];
        // Sending is a deliberate "take me to the newest message". Pin the thread to the bottom
        // BEFORE the repaint so renderDetail's capture records atBottom, and your own reply is
        // followed down instead of the view holding wherever you were reading.
        const t = $("thread");
        if (t) t.scrollTop = t.scrollHeight;
        await openDetail(pid);
      } catch (err) {
        $("reply-alert").textContent = "Could not send: " + (err.message || "retry");
        btn.disabled = false; btn.textContent = "Send reply";
      }
    });

    applySecPanel();   // after EVERY render — see the note on SEC_ELIGIBLE
  }

  // (The global notification roster moved to its own page — /notifications.html.
  //  Per-project overrides live in the detail drawer above.)

  /** Push SORTFIELD/SORTDIR back into the toolbar. The table's own headers can
   *  change the sort, so the select and the arrow must be able to catch up — a
   *  toolbar reading "Last activity" over a board sorted by value is a lie. */
  function syncSortControls() {
    const sort = $("crm-sort"), dir = $("crm-dir");
    if (sort) sort.value = SORTFIELD;
    if (!dir) return;
    dir.textContent = SORTDIR === "asc" ? "↑ Asc" : "↓ Desc";
    dir.setAttribute("aria-pressed", SORTDIR === "asc" ? "true" : "false");
    dir.title = SORTDIR === "asc"
      ? "Ascending (oldest · A→Z · low→high) — click for descending"
      : "Descending (newest · Z→A · high→low) — click for ascending";
  }

  function lostCount() { return ALL.filter(isLost).length; }

  /** How many proposals the customer closed lost, and the way to them.
   *
   *  They are not on this board at all any more (see boardPool), so this count is the only
   *  thing here that says they exist, which is exactly what Hanz asked for when he chose it
   *  over a Lost column: "Gone from the board, but keep a count somewhere."
   *
   *  The link is PLAIN, and that is a real limitation rather than an oversight. /projects.html
   *  reads no filter out of the URL: its tabs are Active / Inactive / All / Test, held in
   *  sessionStorage, and it has no idea what a lost proposal is: `closed_lost` lives on the
   *  portal row, while that page lists our own drafts. So this lands you on the project list,
   *  not on a pre-filtered view of the dead ones. Passing ?filter=lost would be a parameter
   *  that page silently ignores. */
  function syncLostLink() {
    const a = $("crm-lost");
    if (!a) return;
    const n = lostCount();
    a.hidden = n === 0;                       // nothing lost yet → no link at all
    a.textContent = n + " closed lost →";
    a.title = n + " proposal" + (n === 1 ? "" : "s") + " the customer isn't moving forward with."
      + " They're off this board. Open the Proposals Database to find them.";
  }

  /** The Active / Test switch. The counts come off the same predicate the board filters with,
   *  so a tab can never advertise a number it then refuses to show. Lost proposals are outside
   *  both tabs, so they are subtracted before either is counted. */
  function syncTabs() {
    const wrap = $("crm-tabs");
    if (!wrap) return;
    const live = ALL.filter((p) => !isLost(p));
    const n = { test: live.filter(isTest).length, active: live.filter((p) => !isTest(p)).length };
    wrap.querySelectorAll("[data-tab]").forEach((b) => {
      const on = b.dataset.tab === TAB;
      b.setAttribute("aria-pressed", on ? "true" : "false");
      b.classList.toggle("on", on);
      const c = b.querySelector(".n");
      if (c) c.textContent = n[b.dataset.tab] || 0;
    });
  }

  function syncViewToggle() {
    const b = $("crm-view");
    if (!b) return;
    b.textContent = VIEW === "table" ? "▦ Board" : "☰ Table";
    b.title = VIEW === "table" ? "Switch back to the pipeline columns" : "Show every proposal as one sortable list";
    b.setAttribute("aria-pressed", VIEW === "table" ? "true" : "false");
  }

  // Wired ONCE — the controls live in static markup, not in renderBoard, so they
  // keep their focus and value while the board repaints after a staff action.
  (function wireToolbar() {
    const est = $("crm-est"), month = $("crm-month");
    const sort = $("crm-sort"), dir = $("crm-dir"), clear = $("crm-clear");
    const tabs = $("crm-tabs"), view = $("crm-view");
    const syncDir = syncSortControls;
    $("search").addEventListener("input", renderBoard);
    $("search").addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.target.value = ""; renderBoard(); }
    });
    if (est) est.addEventListener("change", () => {
      EST = est.value; ssSet(EST_KEY, EST); renderBoard();
    });
    if (month) month.addEventListener("change", () => {
      MONTH = month.value; ssSet(MONTH_KEY, MONTH); renderBoard();
    });
    if (sort) {
      sort.value = SORTFIELD;
      sort.addEventListener("change", () => {
        SORTFIELD = sort.value;
        SORTDIR = NATURAL_DIR[SORTFIELD] || "desc";   // open each field its natural way
        ssSet(SORTFIELD_KEY, SORTFIELD); ssSet(SORTDIR_KEY, SORTDIR);
        syncDir(); renderBoard();
      });
    }
    if (dir) {
      syncDir();
      dir.addEventListener("click", () => {
        SORTDIR = SORTDIR === "asc" ? "desc" : "asc";
        ssSet(SORTDIR_KEY, SORTDIR); syncDir(); renderBoard();
      });
    }
    // Delegated, so the two buttons need no per-element binding, and TAB is in BOARD_SIG,
    // so renderBoard is guaranteed to repaint (including the pressed state, via syncTabs).
    if (tabs) tabs.addEventListener("click", (e) => {
      const b = e.target.closest("[data-tab]");
      if (!b || b.dataset.tab === TAB) return;
      TAB = b.dataset.tab === "test" ? "test" : "active";
      ssSet(TAB_KEY, TAB === "test" ? "test" : "");
      renderBoard();
    });
    if (view) view.addEventListener("click", () => {
      VIEW = VIEW === "table" ? "board" : "table";
      ssSet(VIEW_KEY, VIEW === "table" ? "table" : "");
      syncViewToggle(); renderBoard();
    });
    if (clear) clear.addEventListener("click", () => {
      // Deliberately NOT the view or the Active/Test tab: those are which board the rep is
      // looking at, not a filter narrowing what's on it.
      EST = ""; MONTH = ""; SORTFIELD = "activity"; SORTDIR = "desc";
      [EST_KEY, MONTH_KEY, SORTFIELD_KEY, SORTDIR_KEY].forEach((k) => ssSet(k, ""));
      $("search").value = "";
      syncDir(); renderBoard();
    });
    syncViewToggle();
    // Before the first fetch lands, so a remembered Test tab reads as selected while the
    // board still says "Loading…" rather than flipping under the rep a second later.
    syncTabs();
  })();
  load();
  startLiveUpdates();
})();
