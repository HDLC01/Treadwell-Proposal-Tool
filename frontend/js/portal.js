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
  // STAGE_CREATED is in this list because it was NOT, and that took the whole board down on
  // production on 2026-08-12. `kanbanHtml` gained `s === STAGE_CREATED` to decide which column
  // carries the + New button; crm-core exports the constant, portal.js never imported it, and an
  // unresolved identifier in a `.map()` callback throws ReferenceError on the FIRST row. The
  // symptom was the board sitting on "Loading..." for ever with the tab counts painted correctly
  // above it — because the counts are written before `board.innerHTML`, and the throw happened
  // during it.
  //
  // Nothing caught it: every test asserted the source TEXT ("s === STAGE_CREATED" appears in the
  // gate) and none of them ever executed the renderer. See test_board_renders.py, which does.
  const { STAGES, STAGE_SUBMITTED, STAGE_CREATED, NATURAL_DIR, SORT_FIELDS } = C;
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
  const EST_KEY = "tw_crm_est";
  // The STORAGE key keeps its old name deliberately: a rep with a month selected when this
  // shipped should still have it selected after the deploy. Only the variable was renamed,
  // because it now holds either a month ("2026-08") or a week ("w:2026-08-10").
  const PERIOD_KEY = "tw_crm_month";
  const SORTFIELD_KEY = "tw_crm_sortfield", SORTDIR_KEY = "tw_crm_sortdir";
  const TAB_KEY = "tw_crm_tab", VIEW_KEY = "tw_crm_view";
  const ss = (k, d) => { try { const v = sessionStorage.getItem(k); return v == null ? d : v; } catch { return d; } };
  const ssSet = (k, v) => { try { v ? sessionStorage.setItem(k, v) : sessionStorage.removeItem(k); } catch {} };
  let EST = ss(EST_KEY, "");
  let PERIOD = ss(PERIOD_KEY, "");
  let SORTFIELD = SORT_FIELDS.includes(ss(SORTFIELD_KEY, "")) ? ss(SORTFIELD_KEY, "") : "activity";
  let SORTDIR = ss(SORTDIR_KEY, "") === "asc" ? "asc" : (ss(SORTDIR_KEY, "") === "desc" ? "desc" : NATURAL_DIR[SORTFIELD]);
  // Active by default: the working list is what a rep opens this page for, and Test is
  // somewhere you go on purpose. Same default, and the same `is_test` flag, as the
  // Proposals Database.
  //
  // There is no SHOW_LOST toggle. Lost proposals used to be a COLUMN on the live board with a
  // "Show closed lost (N)" switch; Hanz, 2026-08-10: "if its lost remove it from the Customer
  // CRM. To remove clutter." They came off the board, leaving only a count.
  //
  // They now have a TAB. Hanz, 2026-08-12: "Actualy create another tab for 'Lost' This is where
  // the lost projects will be held." Same intent as before — a dead deal must not take up room
  // on a board of live work — with somewhere to actually look at them.
  //
  // WON IS THE SAME SHAPE, since 2026-08-20. Hanz: "I marked Trabon Group project as Won but it's
  // still in the Created but Not Sent bucket." A won job now comes off this board exactly as a lost
  // one does, into a tab whose columns are what is still OUTSTANDING on it (C.WON_COLS) rather than
  // how far along the pipeline it got — so nothing gets hidden by the move. This reverses the
  // 2026-08-19 decision to keep won cards on the live board; see the note in chipsHtml.
  const TABS = ["active", "won", "lost", "test"];
  let TAB = TABS.includes(ss(TAB_KEY, "")) ? ss(TAB_KEY, "") : "active";
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
  /** Narrow to one period of activity — a month, or a week.
   *
   *  Hanz, 2026-08-12: "For the filter adad weeks also please". A month is the wrong grain for a
   *  weekly sales meeting: on the 28th, "August" is every bid anybody has touched, and the question
   *  in the room is what moved since Monday.
   *
   *  The two live in ONE control and one stored value, distinguished by a "w:" prefix. A separate
   *  week dropdown would have let somebody pick a week in one and a different month in the other,
   *  and then the board would show nothing with two filters both looking innocent.
   *
   *  The prefix also makes the change backwards-compatible: every value stored before today is a
   *  bare "YYYY-MM", which still takes the month branch. */
  const applyPeriod = (list) => {
    if (!PERIOD) return list;
    if (PERIOD.slice(0, 2) === "w:") {
      const wk = PERIOD.slice(2);
      return list.filter((p) => TW.bizWeekStart(activityTs(p)) === wk);
    }
    return list.filter((p) => TW.bizYM(activityTs(p)) === PERIOD);   // the month the card shows
  };

  const applySort = (list) => C.sort(list, SORTFIELD, SORTDIR);

  /** The rows this board is ABOUT, before any filter the toolbar owns. Which tab you are on is
   *  the whole of it, and the four pools PARTITION `ALL` — every proposal is in exactly one, so
   *  the tab counts add up to the total and nothing can fall through the gaps.
   *
   *  CLOSED LOST IS ITS OWN TAB, and still absent from the live ones. Hanz, 2026-08-10: "allow
   *  for the projects to be lost even its been approved and if its lost remove it from the
   *  Customer CRM. To remove clutter", then 2026-08-12: "create another tab for 'Lost'".
   *
   *  TEST PROJECTS ARE THEIR OWN TAB, split by C.isTest, the same predicate on the same
   *  `is_test` flag, that the Proposals Database uses. Anything that page shows under Test has
   *  to show up under Test here too.
   *
   *  WON IS ITS OWN TAB TOO, since 2026-08-20 (Hanz: "I marked Trabon Group project as Won but it's
   *  still in the Created but Not Sent bucket"). Won jobs leave the Active board the way lost ones
   *  do, and land under C.WON_COLS, which say what is still outstanding on them.
   *
   *  THE ORDER OF THE THREE TESTS IS THE PARTITION, and each one is load-bearing:
   *    · isLost first — a won-then-cancelled job is Lost only, which is the precedence crm-core
   *      records at isWon ("every reader asks isLost FIRST").
   *    · then is_test — a TEST project that was won stays under Test. Scratch work does not become
   *      real work by being marked won, and the Test tab is the one place its owner looks for it.
   *    · then isWon, over the real live rows only.
   *
   *  A lost TEST project appears under Lost, not Test — Lost is every dead deal, or its count
   *  would be a lie and the row would be reachable from nowhere (Test excludes lost, and always
   *  did). Those cards carry a Test chip so they can't be read as real work.
   *
   *  Also what populateEstimators/populatePeriods count, so an option can never offer a filter
   *  that yields nothing: a month whose only proposals were lost used to sit in that dropdown
   *  and blank the board when picked. */
  function boardPool() {
    if (TAB === "lost") return ALL.filter(isLost);
    const live = ALL.filter((p) => !isLost(p) && isTest(p) === (TAB === "test"));
    if (TAB === "test") return live;
    // C.isWon rather than a destructured isWon, deliberately: chipsHtml reads it the same way, and
    // the node harnesses that lift these functions bind the module by name.
    return live.filter((p) => C.isWon(p) === (TAB === "won"));
  }

  /** Everything the current filters allow, in the current order. Both views read
   *  this, so a filter can never mean two different things depending on the view. */
  function visible() {
    return applySort(applyPeriod(applySearch(applyEstimator(boardPool()))));
  }

  /** The state chips a card and a row both carry. Words, not colour alone: this page
   *  gets a synthesized dark theme in some browsers, which rewrites tint. */
  function chipsHtml(p) {
    const out = [];
    if (isLost(p)) {
      const why = lostReason(p);
      out.push(`<span class="chip chip-lost" title="${esc(why ? "Reason: " + why : "No reason recorded")}">Closed lost${
        why ? " · " + esc(why) : ""}</span>`);
      // The Lost tab holds EVERY dead deal, test ones included (see boardPool), so those cards
      // have to say so. Only here: on the live tabs the tab itself is the label.
      if (isTest(p)) out.push('<span class="chip chip-test" title="A test or demo project — filed under Test before it was closed">Test</span>');
    } else {
      // WON. Hanz, 2026-08-19: "CRM lost and won should also tie up to the notification sending
      // okay?" The Notification Sending page files these under a Won tab; same predicate, from
      // crm-core, one definition.
      //
      // THIS BOARD USED TO KEEP A WON CARD ON THE LIVE TABS, and that reasoning is now REVERSED.
      // The argument for keeping it (recorded here until 2026-08-20) was that a won job still has
      // work on it — "Deposit received" and "Contact info" are live columns, and moving the card off
      // would hide real work from the people doing it. What it missed is the card Hanz actually hit:
      // "I marked Trabon Group project as Won but it's still in the Created but Not Sent bucket."
      // A chip cannot argue with a column. He chose the Won TAB instead, on 2026-08-20, and the risk
      // the old reasoning named is answered by that tab's own columns rather than by keeping the card
      // among live bids: C.WON_COLS groups won jobs by what is still outstanding, so the deposit and
      // the contacts chasing stay visible on the tab that owns them.
      //
      // The chip STAYS, and now only ever draws on the Won tab and on Test (where a won test project
      // stays, because scratch work does not become real work by being marked won — and there the
      // chip is the ONLY thing saying so). On Won it is not redundant with the tab name either: the
      // columns there answer "what is left to do", so the chip is the only thing on the card that
      // says why the card is on that board at all.
      //
      // The title names BOTH routes to the chip since 2026-08-19, because a rep who reads only the
      // derived one on a project nobody has approved would take the chip for a bug rather than for
      // the colleague who marked it won on the phone.
      if (C.isWon(p)) out.push('<span class="chip chip-won" title="Won — either marked won by hand, or approved with the deposit settled. Off the Active board, and counts under Won on the Notification Sending page">Won</span>');
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
  // (calendar.js). It goes at the TOP, before populateEstimators/populatePeriods: those rebuild
  // the filter <select> options, and rebuilding a <select> closes it under the cursor of anyone
  // who happened to have it open.
  let BOARD_SIG = "";

  function renderBoard() {
    // The whole shaped dataset plus every piece of view state renderBoard draws from — a
    // proposal moving stage leaves the count identical, and the filters have to keep repainting
    // or changing one would appear to do nothing.
    //
    // One benign wrinkle: populatePeriods below can clear a PERIOD whose rows have all gone, after
    // this signature captured the old value. The next call then sees a different signature and
    // repaints once. One extra paint, no loop, and only on a month emptying out.
    //
    // The lost COUNT is named even though `ALL` is serialized whole and therefore already
    // implies it. Two reasons it earns its place: the count is painted OUTSIDE the board's
    // innerHTML (it is a link in the toolbar), and lost rows are excluded from everything else
    // this signature is derived from, so narrowing `ALL` to the visible pool, which is the
    // obvious optimisation the day 300 rows per poll starts to hurt, would silently freeze that
    // number at whatever it was on first paint.
    const sig = JSON.stringify([ALL, EST, PERIOD, SORTFIELD, SORTDIR, TAB, VIEW,
                                ($("search") || {}).value || "", lostCount()]);
    if (sig === BOARD_SIG) return;
    BOARD_SIG = sig;

    populateEstimators();
    populatePeriods();
    const items = visible();
    const shown = boardPool().length;
    $("count").textContent = items.length === shown
      ? shown + " proposal" + (shown === 1 ? "" : "s")
      : items.length + " of " + shown;
    const clear = $("crm-clear");
    if (clear) clear.hidden = !(EST || PERIOD || SORTFIELD !== "activity" || SORTDIR !== "desc");
    syncTabs();
    const board = $("board");
    board.classList.toggle("as-table", VIEW === "table");
    board.innerHTML = VIEW === "table" ? tableHtml(items) : kanbanHtml(items);
  }

  /** The Lost tab's columns: the reasons, not the stages.
   *
   *  Every card on that tab has the same stage, so grouping by stage would give one tall column
   *  and answer nothing. Grouped by reason the board answers "why do we lose bids?" — which is
   *  the reason the close dialog offers a fixed six instead of a free-text box.
   *
   *  Built from C.LOST_REASON so the columns are exactly the answers the dialog can produce, plus
   *  the one it cannot: proposals closed before a reason was ever asked for. */
  const LOST_COLS = Object.keys(C.LOST_REASON).map((k) => C.LOST_REASON[k]).concat(["Not recorded"]);

  function groupByReason(items) {
    const by = {};
    LOST_COLS.forEach((c) => { by[c] = []; });
    items.forEach((p) => {
      // An unrecognised stored reason lands in "Not recorded" rather than vanishing — the same
      // bias C.group takes with an unknown stage, for the same reason: a vocabulary that grows
      // must not silently drop cards off the board.
      (by[lostReason(p)] || by["Not recorded"]).push(p);
    });
    return by;
  }

  function kanbanHtml(items) {
    // Three shapes: the pipeline (STAGES) on the live tabs, the close reasons on Lost, and what is
    // still outstanding (C.WON_COLS) on Won.
    //
    // There is no Closed lost and no Won column on the live tabs — neither is in the pool (see
    // boardPool), and C.group drops any row whose stage has no column, so one arriving by some
    // other route is left out rather than throwing.
    const lost = TAB === "lost";
    const won = TAB === "won";
    if (lost && !items.length) {
      return '<div class="empty">Nothing closed lost' + (
        boardPool().length ? " matches those filters." : " — every proposal is still live.") + "</div>";
    }
    // Same two kinds of empty the Lost tab distinguishes: "nothing matches your filter" means clear
    // the filter, and an unfiltered empty tab is just a tab nobody has won a job onto yet.
    if (won && !items.length) {
      return '<div class="empty">Nothing won' + (boardPool().length
        ? " matches those filters."
        : " yet — a job lands here when somebody marks it won, or when it is approved with the"
          + " deposit settled.") + "</div>";
    }
    // Grouping and columns are chosen in ONE ternary each, and the Won branch reads the module off
    // `C`, so nothing new is free in this scope. An unbound identifier inside the .map() below is
    // what took the whole board down on 2026-08-12; see the note at the top of this file.
    const cols = lost ? LOST_COLS : won ? C.WON_COLS : STAGES;
    const byStage = lost ? groupByReason(items) : won ? C.groupWon(items) : C.group(items, STAGES);
    return cols.map((s) => {
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
      // `!lost && !won` is belt as well as braces: no reason label and no Won column equals
      // STAGE_CREATED today, and a "+ New" button on a column of dead deals would file a brand-new
      // bid as closed lost. ("Won before approval" is the near miss on the Won tab — a new bid
      // started from there would be neither won nor approved.)
      const add = !lost && !won && s === STAGE_CREATED
        ? '<button type="button" class="col-add" data-new-proposal title="Start a new proposal — opens the intake form">+ New</button>'
        : "";
      return `<div class="col${attn}"><h2>${esc(s)}<span>${byStage[s].length}</span>${add}</h2>${cards}</div>`;
    }).join("");
  }

  /** THE OUTCOME, on the card. Hanz, 2026-08-20: the two buttons become an outcome pair, and
   *  2026-08-22: they are a MATCHED PAIR - "Mark as won" and "Mark as lost". They were "Mark as
   *  closed" and "Lost", and Hanz read that and asked whether the two were the same thing. They
   *  never were: one posts the won mark, the other opens the reason dialog. But only one of them
   *  said "Mark as", and "closed" sitting beside "Lost" reads as though it might mean lost. Two
   *  buttons that do opposite things have to be named the same way round. The won one always POSTED
   *  the won mark; "closed" was a word for the act rather than the result, and on a card that
   *  sits beside a Lost button it reads as though it might mean either one.
   *
   *  "CLOSED" MEANS WON. Hanz confirmed it, so this reuses the existing by-hand won mark — POST
   *  /api/draft/{id}/status {status:"won"}, the same call the drawer's Mark won button makes — and
   *  invents no third state. A separate "closed" state would be a second word for won that only the
   *  board could speak, and the Won tab, the Won chip and the Notification Sending page would all
   *  have to learn it.
   *
   *  THESE REPLACED Files and Info sheet, which shipped here on 2026-08-12 and moved into BOTH
   *  drawers' Proposal tab on 2026-08-20 — the sent drawer has #go-files/#go-info and the not-sent
   *  one has [data-go-files]/[data-go-info], both on the same URLs. Nothing is lost by taking them
   *  off the card, and the card gets back the room to do the thing the sales meeting actually needs
   *  from it, which is recording an outcome without opening anything.
   *
   *  KANBAN ONLY. There is one call site, in kanbanHtml, and the table view has never carried card
   *  buttons: a row is 7 columns of facts, and a control in a table cell that also opens the drawer
   *  on click is a click nobody can aim. That is a deliberate asymmetry, not an omission.
   *
   *  NOTHING ON A CARD THAT IS ALREADY DECIDED. A lost card offering Lost and a won card offering
   *  Mark as won are both buttons that save and change nothing visible, which reads as broken.
   *  The way back for those two is the drawer's bring-back, which needs a prompt naming the
   *  destination and so cannot live on a 224px card.
   */
  function cardActions(p) {
    if (isLost(p) || C.isWon(p)) return "";
    const id = encodeURIComponent(p.proposal_id);
    return `<div class="deal-acts">
      <button type="button" class="deal-act" data-won="${id}" title="We won it — moves this to the Won tab">Mark as won</button>
      <button type="button" class="deal-act" data-lost="${id}" title="Not going ahead — pick a reason and say what happened">Mark as lost</button>
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
    // sits inside a .deal — without the early return a click would both act and open the drawer,
    // and the drawer would win the paint.
    const won = e.target.closest("[data-won]");
    if (won) { markCardWon(won); return; }
    const lostBtn = e.target.closest("[data-lost]");
    if (lostBtn) { closeCardOut(lostBtn); return; }
    if (e.target.closest("[data-new-proposal]")) { startNewProposal(); return; }

    const row = e.target.closest(".deal, .trow");
    if (row && row.dataset.id) openDetail(row.dataset.id);
  });

  /** The row this button belongs to, out of the board's own array.
   *
   *  ALL, not the filtered pool: the card was drawn from a filtered list, but the poll that runs
   *  every 25s can move a row out of that list between the paint and the click, and a button that
   *  silently does nothing is worse than one that acts on the project whose name is on the card.
   *  A missing row is still possible (the project was trashed in another tab) and both callers
   *  check. */
  function cardRowOf(btn) {
    const id = btn.dataset.won || btn.dataset.lost || "";
    return ALL.find((x) => String(x.proposal_id) === decodeURIComponent(id)) || null;
  }

  /** Mark as won, from the card. The label said "Mark as closed" until 2026-08-22; it posted the
   *  won mark either way, so this is the same
   *  draft-side won mark the drawer's Mark won button makes, on the same route, with no new state.
   *
   *  NO PROMPT, exactly as the drawer's Mark won has none: nothing is sent, nothing leaves the
   *  pipeline, and the way back is the drawer's bring-back. The button reports its own progress
   *  because the card is about to move to another tab and vanish from under the cursor, and a
   *  silent 12 seconds there is indistinguishable from a dead control. */
  async function markCardWon(btn) {
    const row = cardRowOf(btn);
    if (!row) return;
    btn.disabled = true;
    const orig = btn.textContent;
    btn.textContent = "Saving…";
    try {
      const r = await api("/api/draft/" + encodeURIComponent(row.proposal_id) + "/status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "won" }),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      // Patch the board's own object so the card leaves for the Won tab on this paint rather than
      // on the next poll — the same reason the drawer patches its row. load() then re-reads.
      row.won_at = new Date().toISOString();
      renderBoard();
      load();
    } catch (err) {
      btn.textContent = "Failed: " + (err.message || "retry");
      btn.disabled = false;
      setTimeout(() => { btn.textContent = orig; }, 2600);
    }
  }

  /** Lost, from the card. The SAME dialog the two drawers use, so a reason and a required comment
   *  are collected here exactly as they are there and there is one close-out vocabulary.
   *
   *  WHICH ROUTE depends on whether the customer has the proposal, and that is the same split the
   *  drawers make: a sent project has a portal row whose close-lost also stops the cadence, and an
   *  unsent one has no portal row at all, which is why the draft route exists. `not_sent` is the
   *  flag the pipeline sets for exactly this question. */
  async function closeCardOut(btn) {
    const row = cardRowOf(btn);
    if (!row) return;
    const why = await closeOutDialog(row, { unsent: !!row.not_sent });
    if (!why) return;
    btn.disabled = true;
    const orig = btn.textContent;
    btn.textContent = "Saving…";
    const id = encodeURIComponent(row.proposal_id);
    const hold = why.outcome === "hold";
    const path = row.not_sent ? "/api/draft/" + id + "/status"
                              : "/api/portal/proposal/" + id + "/status";
    const body = row.not_sent
      ? (hold ? { status: "on_hold", reason: why.reason, note: why.note }
              : { status: "closed_lost", reason: why.reason, note: why.note })
      : (hold ? { status: "delayed", months: HOLD_MONTHS, reason: why.reason, note: why.note }
              : { status: "closed_lost", reason: why.reason, note: why.note });
    try {
      const r = await api(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      // A HOLD IS NOT PATCHED ONTO THE ROW HERE, deliberately: the card stays where it is, so
      // there is nothing for an optimistic paint to hurry along, and the pause date belongs to the
      // server. Closing lost moves the card off this tab, which is worth not waiting for.
      if (!hold) {
        row.proposal_status = "closed_lost";
        row.followup_state = Object.assign({}, row.followup_state,
                                           { closed_lost_reason: why.reason });
        renderBoard();
      }
      load();
    } catch (err) {
      btn.textContent = "Failed: " + (err.message || "retry");
      btn.disabled = false;
      setTimeout(() => { btn.textContent = orig; }, 2600);
    }
  }

  /** Start a bid from this board. The same three storage keys and the same destination as
   *  "+ New project" on the Proposals Database (projects.js) — a second way of minting a draft
   *  would be a second set of bugs, and the intake form is reached by URL either way.
   *
   *  The test flag follows the TAB you are looking at, which is why this is safe to offer here:
   *  kanbanHtml only draws the button on Active and Test, never on Lost or Won and never on an
   *  "all" view, so a new project can never land un-filed. Same rule Hanz asked for on the Database
   *  ("use the Test category so it wouldn't mix up"). */
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

  // How many recent weeks the dropdown offers. Bounded because weeks accumulate fast: a year of
  // activity is 52 of them, and a list that long is worse than no week filter at all. Six covers
  // "the last month and a half", which is as far back as a weekly meeting ever reaches.
  const WEEKS_OFFERED = 6;

  function populatePeriods() {
    const sel = $("crm-month");
    if (!sel) return;
    const weeks = {}, months = {};
    boardPool().forEach((p) => {
      const ts = activityTs(p);
      const wk = TW.bizWeekStart(ts);
      if (wk) weeks[wk] = (weeks[wk] || 0) + 1;
      const ym = TW.bizYM(ts);
      if (ym) months[ym] = (months[ym] || 0) + 1;
    });

    const shown = Object.keys(weeks).sort().reverse().slice(0, WEEKS_OFFERED);
    const monthKeys = Object.keys(months).sort().reverse();

    // Drop a selection whose rows have all gone — otherwise switching tab leaves a filter that
    // matches nothing and an empty board that reads as broken. Checked against what is actually
    // OFFERED, not merely what exists: a week that fell past WEEKS_OFFERED is unreachable in the
    // dropdown, so leaving it selected would strand the board with no way back but Clear.
    const offered = new Set(monthKeys.concat(shown.map((w) => "w:" + w)));
    if (PERIOD && !offered.has(PERIOD)) { PERIOD = ""; ssSet(PERIOD_KEY, ""); }

    // "This week" / "Last week" beat a date range for the two everybody actually wants, and the
    // range is still shown for the rest. Derived from today rather than from the data, so an empty
    // week is named correctly instead of shifting the labels up.
    const thisWk = TW.bizWeekStart(new Date().toISOString());
    const lastWk = TW.bizWeekStart(new Date(Date.now() - 7 * 86400000).toISOString());
    const weekLabel = (w) => (w === thisWk ? "This week"
      : w === lastWk ? "Last week" : TW.bizWeekLabel(w));

    const opt = (v, label, n) => `<option value="${esc(v)}">${esc(label)} (${n})</option>`;
    let html = '<option value="">Any period</option>';
    if (shown.length) {
      html += '<optgroup label="Weeks">'
        + shown.map((w) => opt("w:" + w, weekLabel(w), weeks[w])).join("")
        + "</optgroup>";
    }
    if (monthKeys.length) {
      html += '<optgroup label="Months">'
        + monthKeys.map((ym) => opt(ym, TW.bizMonthLabel(ym), months[ym])).join("")
        + "</optgroup>";
    }
    sel.innerHTML = html;
    sel.value = PERIOD;
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
    const dl = e.target.closest(".rev-dl");
    if (dl) downloadRevision(CUR_PID, dl.dataset.rev, dl.dataset.kind, dl);
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
      // Through drawerHead like every other panel, so this one keeps the labelled close
      // button. It used to ship a bare `<button class="dclose">×</button>`, which is the only
      // control on screen at that moment and read to a screen reader as "times".
      d.innerHTML = drawerHead("Could not load this project", "") +
        '<div class="dbody"><div class="dpanel"><p class="note">' + esc(err.message) + '</p></div></div>';
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
    const wonHtml = wonControlHtml(row);
    const d = $("drawer");
    // THE SAME FIVE TABS AS A SENT PROJECT. Hanz, 2026-08-19: "For those not sent just please have
    // the same set of tabs so that its clear."
    //
    // This panel deliberately had none, on the reasoning that a deposit and a thread do not exist
    // yet so a tab pointing at them would be pointing at nothing. That was wrong about what a tab
    // strip is FOR: it is the shape of a project, and dropping four fifths of it made this drawer
    // look like a different feature rather than the same project earlier in its life. Somebody who
    // learns the strip on a sent project should not have to re-learn this one.
    //
    // So every tab is present and says what it is waiting for. A tab whose content genuinely does
    // not exist yet says so in the panel, which is a fact about the project rather than an empty
    // box that reads as broken.
    const nsTabs = `<div class="dtabs" role="tablist" aria-label="Project sections">` +
      secTab("chat", "Chat", { val: "—", hint: "Opens when the customer can see the proposal" }) +
      secTab("proposal", "Proposal", { val: "Not sent",
        hint: "Customer, estimator, who hears about it when it goes out" }) +
      secTab("deposit", "Deposit", { val: "—", hint: "Nothing until the customer approves" }) +
      secTab("contacts", "Contacts", { val: "—", hint: "The customer supplies these after approving" }) +
      secTab("followup", "Follow-up", { val: "Off", hint: "Chasing starts when you send it" }) +
      `</div>`;
    // These sections carry `dsec-ns-*` ids, deliberately outside ALL_SEC_CARDS: applySecPanel's
    // per-card eligibility pass is for the sent drawer, where a card can be present but not
    // applicable. Here the PANEL-level hiding is the whole job — one panel per tab, always the
    // right one — so borrowing the card machinery would add a second switch that has to agree
    // with the first.
    NS_MODE = true;
    d.innerHTML = `
      ${drawerHead(row.project_name, "")}
      ${nsTabs}
      <div class="dbody">
       <div class="dpanel" id="dpanel-proposal" role="tabpanel" aria-labelledby="dtab-proposal" tabindex="-1">
        <div class="sec" id="dsec-ns-proposal">
          <div class="lbl">Not sent yet</div>
          <p class="note">The estimate and the proposal are generated, and nobody has sent them to
          the customer. Nothing reaches them until you do.</p>
        </div>
        <div class="sec">
          <div class="facts">
            ${row.customer_email ? fact("Addressed to", esc(row.customer_email)) : ""}
            ${fact("Estimator", who
              ? avatar(who, !isAssigned(row)) + esc(nameOf(who)) + (isAssigned(row) ? "" : "?")
              : '<span class="unassigned">Nobody is assigned</span>')}
            ${total != null ? fact("Bid", `<span class="amt">${money(total)}</span>`) : ""}
            ${row.drafted_at ? fact("Created", esc(TW.fmtBizDate(row.drafted_at))) : ""}
          </div>
        </div>
        <!-- Assign it HERE, not only from the Projects tab. Hanz, 2026-08-13: "Allow to choose
             the estimator on the Created but not sent". The Estimator fact above is a GUESS until
             somebody picks — the draft's author, drawn with a "?" — and this drawer was the one
             place that displayed the guess while offering no way to settle it. Under the facts
             rather than inside them: a fact and the control that changes it are different things,
             and the grid's job is to be scannable. The DRAFT endpoint, because an unsent project
             has no portal row to assign against. -->
        <div class="sec">
          <div class="lbl">Assign an estimator</div>
          <div class="ns-assign">
            <select id="ns-assign" aria-label="Assign an estimator" disabled>
              <option value="">Loading…</option>
            </select>
            <button type="button" class="btn btn-s" id="ns-assign-btn" disabled>Assign</button>
          </div>
          <p class="note ns-assign-note" id="ns-assign-note"></p>
        </div>
        <!-- Chosen HERE, before the send, because this is where somebody is standing when they
             decide who should know about a job. Hanz, 2026-08-19: "add the notif sending in this
             step of the CRM."
             Stored on the DRAFT, for the same reason the estimator above is: an unsent project has
             no portal row, and the portal's per-project override table has a foreign key onto one.
             The Files screen reads this back and carries it into the send that creates the row. -->
        <div class="sec">
          <div class="lbl">Notifications for this project</div>
          <p class="note">Who hears about this once it goes out. Green means they are on. This
          overrides the global roster for this project only, and toggling somebody never sends them
          anything now.</p>
          <div id="ns-nt-chips" class="nt-chips"><span class="note">Loading…</span></div>
          <p class="note" id="ns-nt-note"></p>
        </div>
        <!-- Info sheet, next to the other two ways out of this drawer. Hanz, 2026-08-20: "Move the
             info sheet button inside proposals tab." The URL is the one the card and the Proposals
             Database already use, character for character, because two spellings of one route is
             how one of them rots (test_board_is_the_main_tab.py holds the other end). -->
        <div class="sec row3">
          <button type="button" class="btn btn-p" data-go-files>Open the files</button>
          <button type="button" class="btn btn-s" data-go-edit>Edit the estimate</button>
          <button type="button" class="btn btn-s" data-go-info>Info sheet</button>
        </div>
        <!-- Delete, LAST and in a section of its own. Hanz, 2026-08-24. Deliberately not a fourth
             button in the .row3 above: that row is the three ways OUT of this drawer and a delete
             sitting in it is one an estimator can hit while reaching for the estimate. Admin-only,
             and empty markup for everybody else (the endpoint refuses them too). -->
        ${deleteProjectHtml(row)}
       </div>

       <!-- The other four. Each says what has to happen before it has anything in it, which is a
            fact about where the project is rather than an empty panel that reads as a bug. The
            wording names the trigger, so the strip doubles as an explanation of the sequence. -->
       <div class="dpanel" id="dpanel-deposit" role="tabpanel" aria-labelledby="dtab-deposit" tabindex="-1">
        <div class="sec" id="dsec-ns-deposit">
          <div class="lbl">Deposit</div>
          <p class="note">Nothing to collect yet. A deposit can be requested once the customer has
          approved the proposal, and whether one is required is chosen on the Files screen when you
          send it.</p>
        </div>
       </div>

       <div class="dpanel" id="dpanel-contacts" role="tabpanel" aria-labelledby="dtab-contacts" tabindex="-1">
        <div class="sec" id="dsec-ns-contacts">
          <div class="lbl">Contacts</div>
          <p class="note">The customer fills these in themselves — who to reach for scheduling and
          for invoices — and they are asked for them after they approve.</p>
        </div>
       </div>

       <div class="dpanel" id="dpanel-chat" role="tabpanel" aria-labelledby="dtab-chat" tabindex="-1">
        <div class="sec" id="dsec-ns-chat">
          <div class="lbl">Chat</div>
          <p class="note">The conversation opens when the customer can see the proposal. Send it and
          anything they ask lands here, with your replies going back to them by email.</p>
        </div>
       </div>

       <div class="dpanel" id="dpanel-followup" role="tabpanel" aria-labelledby="dtab-followup" tabindex="-1">
        <div class="sec" id="dsec-ns-followup">
          <div class="lbl">Follow-up</div>
          <p class="note">Chasing starts when you send this. From then on the assigned estimator
          gets the reminders and this project appears in the morning digest until the deposit is
          in. Nobody is chased before a proposal exists.</p>
        </div>
        <!-- Hanz, 2026-08-19: "Allow to mark a proposal as lost tho in the Created not sent
             category." The commonest dead bid there is: priced, generated, and then the GC went
             elsewhere before we sent it. Until now the only place to close a bid lost was the sent
             drawer, so these could only be archived — which hides a project instead of counting it.

             In the FOLLOW-UP tab because that is where somebody who learned this control on a sent
             project will look for it. Posts to the DRAFT endpoint: there is no portal row to close. -->
        <!-- Won, by hand. Hanz, 2026-08-19: "Is there any way to also mark as won for now other than
             after the deposit has been received". ABOVE the closed-lost control, because that is the
             order the two outcomes deserve to be read in. The whole section goes when there is
             nothing to offer — on a lost bid — rather than leaving an empty .sec taking its parent's
             gap above the Reactivate button.

             BOTH OUTCOMES, ON A BID NOBODY HAS SENT. Hanz, 2026-08-20: "Even for created not sent we
             must be able to mark it as won or lost." Both were already here and both post to the
             DRAFT endpoint (wireWon and wireNotSentLost below) — this comment exists because the
             pair is now an asserted invariant rather than two features that happen to coexist, and
             because it has to survive the card MOVING: this panel is reached from whichever tab the
             card is on, so a project marked won still offers Mark closed lost from the Won tab, and
             a won unsent bid the GC then cancels does not have to be un-won first.
             test_won_tab.py renders this panel on a won not-sent row and asserts both controls. -->
        ${wonHtml ? `<div class="sec" id="dsec-ns-won">${wonHtml}</div>` : ""}
        <!-- THREE STATES, not two, since 2026-08-20. Two of the eight answers on Kyle's
             close-out list put a bid ON HOLD rather than killing it, so a held bid needs its own
             reading of this section: it is not lost, and it is not simply live either, and a
             held bid rendered as live would offer no way to say it had woken up. -->
        <div class="sec" id="dsec-ns-lost">
          <div class="lbl">${isLost(row) ? "Closed lost"
            : nsHoldReason(row) ? "On hold" : "Not going ahead?"}</div>
          ${isLost(row) ? `
            <p class="note">This bid is closed lost${lostReason(row)
              ? ' — <strong>' + esc(lostReason(row)) + '</strong>' : ""}. It sits on the Lost tab and
            counts in the numbers there. Bringing it back puts it under Created but not sent.</p>
            ${nsCloseNote(row, "closed_lost_note")}
            <div class="fu-line"><button type="button" class="btn btn-s" id="ns-reopen">Bring this bid back</button></div>`
          : nsHoldReason(row) ? `
            <p class="note">This bid is on hold — <strong>${esc(nsHoldReason(row))}</strong>. It
            stays on the Active board under Created but not sent${pausedUntil(row)
              ? ", and nothing chases it until " + esc(TW.fmtBizDay(pausedUntil(row))) : ""}.
            Bring it back the day it wakes up.</p>
            ${nsCloseNote(row, "on_hold_note")}
            <div class="fu-line"><button type="button" class="btn btn-s" id="ns-reopen">Bring this bid back</button></div>`
          : `
            <p class="note">Close it out and it moves to the Lost tab under a reason, instead of
            sitting here as work nobody is going to do. Two of the answers put it on hold instead
            and leave it on this board. The customer is never emailed either way, and you can put
            it back.</p>
            <!-- .fu-line, the same wrapper the sent drawer's identical buttons sit in. A bare
                 button inside .sec stretches to the full drawer width, which a staging walk showed
                 reads as a banner rather than a control. -->
            <div class="fu-line"><button type="button" class="btn btn-s" id="ns-lost">Close this bid out</button></div>`}
          <p class="note" id="ns-lost-note"></p>
        </div>
       </div>
      </div>`;
    d.querySelector(".dclose").addEventListener("click", closeDrawer);
    const go = (u) => window.location.assign(u);
    d.querySelector("[data-go-files]").addEventListener("click",
      () => go("/done.html?d=" + encodeURIComponent(pid) + "&files=1"));
    d.querySelector("[data-go-edit]").addEventListener("click",
      () => go("/?d=" + encodeURIComponent(pid) + "&edit=1"));
    d.querySelector("[data-go-info]").addEventListener("click",
      () => go("/info-sheet.html?d=" + encodeURIComponent(pid)));
    // Land on Chat, and paint the strip so one tab reads as selected. Without the apply the five
    // tabs render with nothing active and every panel visible at once — the strip has to be applied,
    // not merely present.
    //
    // THE SAME RULE THE SENT DRAWER USES, for the one input this drawer can ever have: no thread.
    //
    // This line read `ACTIVE_SEC = "chat"` for a day, which put the unsent drawer on the only tab
    // it CANNOT fill. There is no portal row here, so there is no conversation, and the Chat panel
    // above is one paragraph explaining that. Hanz asked to land where the conversation is, not to
    // land on an empty box, so restingSection's answer for an empty thread is what belongs here:
    // Proposal, which carries the customer, the estimator, the bid, the notification picker and
    // the three ways out of this drawer.
    //
    // WRITTEN OUT rather than calling restingSection, and that is a real trade: two other node
    // harnesses lift renderNotSent on its own, so a call to a function they do not lift is a
    // ReferenceError for this whole panel rather than a wrong tab. The guard against the two
    // renderers drifting apart again is therefore a test, not the call: test_drawer_chat_default
    // asserts this drawer's landing tab EQUALS restingSection's answer for an empty thread, so
    // changing one without the other fails.
    if (!SEC_TABS[ACTIVE_SEC]) ACTIVE_SEC = "proposal";
    applySecPanel();
    wireNotSentAssign(pid, row);
    wireNotSentLost(pid, row);
    wireDeleteProject(pid, row);
    // The row IS the board's own object (renderNotSent is only ever called with ALL.find(...)), so
    // patching it in place is what makes the mark survive the 12s poll that re-opens this drawer
    // before load() has returned — a copy would be repainted away by the next tick.
    wireWon(pid, row, (patch) => {
      Object.assign(row, patch);
      DRAWER_SIG = "";
      renderNotSent(pid, row);
    });
    loadNotSentNotify(pid);
  }

  /** Close an unsent bid lost, or put it back. Hanz, 2026-08-19: "Allow to mark a proposal as lost
   *  tho in the Created not sent category."
   *
   *  Same two-step shape as the sent drawer's control: the reason dialog first, the request second,
   *  then a redraw from the patched row and a board reload — the board matters because a closed bid
   *  has to leave the Created column and appear under Lost, which the drawer repaint does not do.
   *
   *  The `DRAWER_SIG = ""` below is belt-and-braces, not load-bearing, and mutation testing says so:
   *  the guard only suppresses an IDENTICAL signature, and the patch always adds fields, so the
   *  redraw would go through without it. Kept to match wireNotSentAssign and so a future patch that
   *  happens to be a no-op still repaints. */
  function wireNotSentLost(pid, row) {
    const note = $("ns-lost-note");
    // `optimistic` may be a FUNCTION of the server's answer, which is how the hold gets its date
    // without this file learning to add four months to today. The backend already computes it
    // (_hold_until in main.py) and returns it; a second implementation here would be a second
    // month-add to keep in step, and it would be the one on screen.
    const post = async (btn, body, optimistic) => {
      btn.disabled = true;
      const orig = btn.textContent;
      btn.textContent = "Saving…";
      if (note) note.textContent = "";
      try {
        const r = await api("/api/draft/" + encodeURIComponent(pid) + "/status", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const j = await r.json().catch(() => ({}));
        if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
        DRAWER_SIG = "";
        const patch = typeof optimistic === "function" ? optimistic(j) : optimistic;
        renderNotSent(pid, Object.assign({}, row, patch));
        load();
      } catch (err) {
        btn.textContent = orig;
        btn.disabled = false;
        if (note) note.textContent = "Couldn't save that — " + (err.message || "try again.");
      }
    };

    const lost = $("ns-lost");
    if (lost) lost.addEventListener("click", async () => {
      const why = await closeOutDialog(row, { unsent: true });
      if (!why) return;
      // TWO OUTCOMES OUT OF ONE CONTROL, and the branch is the whole of Hanz's 2026-08-20 decision:
      // six of Kyle's answers close the bid, "Project on Hold" and "Small Bid <$25k - Pending"
      // pause it. A held bid gets NO proposal_status, so stage() still reads `not_sent` and the
      // card stays in the Created column — the optimistic patch has to say the same, or the drawer
      // would repaint as closed lost for the twelve seconds until the board caught up.
      if (why.outcome === "hold") {
        await post(lost, { status: "on_hold", reason: why.reason, note: why.note },
                   (j) => ({ followup_state: { paused_until: j.paused_until || "",
                                               on_hold_reason: why.reason } }));
        return;
      }
      // Shaped as the portal's own closed-lost state, exactly as the synthesised row is, so the
      // redrawn drawer and the reloaded board agree without a second vocabulary.
      await post(lost, { status: "closed_lost", reason: why.reason, note: why.note },
                 { proposal_status: "closed_lost",
                   followup_state: { closed_lost_reason: why.reason } });
    });

    const reopen = $("ns-reopen");
    if (reopen) reopen.addEventListener("click", async () => {
      if (!(await confirmBringBack(row))) return;
      // `bring_back`, not `active`: this bid may have been marked won and THEN closed lost, in
      // which case it reads as Lost only, and clearing one mark would drop the card onto the Won
      // tab instead of back on the board. One press clears both, plus any hold — drafts.clear_outcome.
      post(reopen, { status: "bring_back" },
           { proposal_status: "", followup_state: {}, won_at: "" });
    });
  }

  /** Why an UNSENT bid is on hold, as a label, or "" if it is not.
   *
   *  Read off `on_hold_reason`, which only set_on_hold writes (see _not_sent_rows), and NOT off
   *  paused_until: a sent project can be paused by the plain "Mark delayed" control, which asks
   *  for a number of months and no reason at all, and calling that "on hold" would put a reason on
   *  screen that nobody chose. C.HOLD_REASON, so the label is the one the dialog offered. */
  function nsHoldReason(p) {
    return C.HOLD_REASON[String((C.followup(p).on_hold_reason) || "")] || "";
  }

  /** What somebody WROTE when they closed this bid out, quoted, or "" when there is nothing.
   *
   *  THE POINT OF REQUIRING IT. The comment is the tool's one mandatory free-text field, and the
   *  argument for making it mandatory was that a reason on its own tells the next person nothing:
   *  "Not Low Bid" is eight identical cards by the end of a quarter. A field that costs the
   *  estimator a sentence and is then never printed anywhere would be the worst of both.
   *
   *  HERE AND NOT ON THE CARD. A card is 224px wide and this is a paragraph. The drawer is where
   *  somebody has already asked about one project, and where the reason is printed too.
   *
   *  THE CLOSE, ONLY HERE. A sent bid's comment goes into the customer thread as an internal card
   *  the moment it is written (the portal's admin_set_status), which is a better home for a sentence
   *  about a finished job than a panel nobody opens twice - so there is deliberately no second copy
   *  of a CLOSED-LOST comment on the sent drawer's follow-up panel.
   *
   *  A HOLD IS THE EXCEPTION, added 2026-08-21, and the distinction is a live bid versus a dead
   *  one. A held bid is still in play, its follow-up panel is the only place its state is stated,
   *  and the comment is the input to the one decision left on it: bring it back, or leave it. So the
   *  sent panel prints the hold's comment (see followupPanelHtml) while still leaving the close's to
   *  the thread. Not through this function, though - a sent hold's reason and note live in
   *  portal_followups.detail rather than in followup_state, which is what sentHold reads.
   *
   *  `white-space:pre-wrap` is NOT used, and `esc` is: this is one sentence typed into a textarea,
   *  and a newline in it must not be able to reopen the paragraph it sits in. */
  function nsCloseNote(p, key) {
    const text = String(C.followup(p)[key] || "").trim();
    if (!text) return "";
    return '<p class="note ns-why">“' + esc(text) + '”</p>';
  }

  /** "We won it" — the by-hand mark, and what the panel says once somebody has used it.
   *
   *  Hanz, 2026-08-19: "Is there any way to also mark as won for now other than after the deposit
   *  has been received". Won was derived only (approved AND the deposit settled), so a job we won by
   *  phone on Monday read as Active until the money arrived on Friday. Lost was already markable by
   *  hand; that asymmetry was the bug.
   *
   *  ONE definition for BOTH drawers — the not-sent panel and a sent project's Follow-up tab — and
   *  the ids are shared because only one of them is ever rendered into #drawer at a time. A second
   *  copy is exactly how the word "lost" ended up meaning two things on two screens before crm-core
   *  existed. `lblClass` is the only difference: the sent drawer drops this into the middle of an
   *  existing section, where a heading needs its top margin.
   *
   *  FOUR STATES, because three of them are things a button must NOT be offered for:
   *    · lost      → nothing at all. Lost beats Won everywhere (see isWon), so a Mark won press here
   *                  would save and change nothing visible, which reads as a broken control. The
   *                  Reactivate button beside it is the way back.
   *    · by hand   → the state and an undo, exactly as the closed-lost control does.
   *    · won anyway→ the state, and NO control. There is nothing to undo about a deposit that
   *                  arrived, and a Mark won button would file a redundant human mark over a fact.
   *    · otherwise → the offer. */
  function wonControlHtml(p, lblClass) {
    const lbl = '<div class="' + (lblClass || "lbl") + '">';
    if (isLost(p)) return "";
    // No em dash anywhere in this copy: it renders in the sent drawer, where that is a house rule
    // (test_no_em_dash_in_the_panels_copy) because the portal's own system lines use one as a field
    // separator and splitSystem cuts on it.
    if (C.wonByHand(p)) {
      return `${lbl}Won</div>
        <p class="note">Somebody marked this won, so it sits on the Won tab instead of the Active
        board, and counts under Won on the Notification Sending page. Follow-ups do NOT stop: the
        chasing runs until the deposit is in, and the customer is not emailed about this either
        way.</p>
        <div class="fu-line"><button type="button" class="btn btn-s" id="won-undo">Undo the won mark</button></div>
        <p class="note" id="won-note"></p>`;
    }
    if (C.isWon(p)) {
      // NO BUTTON, and the copy now SAYS SO rather than leaving a gap where every other state has a
      // control. Hanz asked for the bring-back on 2026-08-20 and this is the one case with nothing
      // to bring back: nobody marked this job won, the numbers did, so there is no mark to clear.
      // An Undo here would save and change nothing, which reads as a broken control. Un-approving
      // it or unwinding the deposit are different acts and live where those facts do.
      return `${lbl}Won</div>
        <p class="note">Approved, and the deposit question is settled, so this already counts as won
        without anyone marking it. It sits on the Won tab. There is nothing to bring back here:
        no person marked it, so there is no mark to take off. It stops counting as won if the
        approval or the deposit changes, and both of those are on the Proposal tab.</p>`;
    }
    return `${lbl}Won it already?</div>
      <p class="note">Mark it won as soon as they say yes on the phone. It does not wait for the
      customer to click Approve or for the deposit to land, the customer is not emailed, and the
      follow-ups carry on until the money is in. The card moves to the Won tab, which columns it by
      whatever is still outstanding, so nothing stops being chased. You can undo it.</p>
      <div class="fu-line"><button type="button" class="btn btn-s" id="won-mark">Mark won</button></div>
      <p class="note" id="won-note"></p>`;
  }

  /** Wire the pair of buttons wonControlHtml can render. Shared by both drawers, which is why the
   *  repaint is a callback: the not-sent panel redraws from its board row, and a sent project's
   *  drawer redraws from its cached portal payload with the row merged back in.
   *
   *  Posts to the DRAFT endpoint from BOTH drawers, unlike Mark closed lost, which uses the portal's
   *  route once a proposal exists. There is no portal equivalent to defer to: `proposal_status` is
   *  CHECK-constrained, so a "won" value there would mean DDL on a column the portal owns, and the
   *  mark has to work on an unsent project too. One place records it, one place reads it back.
   *
   *  `patch` carries `won_at`, not a boolean, because that is the field the pipeline sends and isWon
   *  reads. The optimistic value is the browser's clock: nothing renders this stamp, the server
   *  writes its own on the row that matters, and the next board load replaces it. */
  function wireWon(pid, row, repaint) {
    const note = $("won-note");
    const post = async (btn, body, patch) => {
      btn.disabled = true;
      const orig = btn.textContent;
      btn.textContent = "Saving…";
      if (note) note.textContent = "";
      try {
        const r = await api("/api/draft/" + encodeURIComponent(pid) + "/status", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const j = await r.json().catch(() => ({}));
        if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
        repaint(patch);
        load();                     // the chip and the Won count live on the board behind this
      } catch (err) {
        btn.textContent = orig;
        btn.disabled = false;
        if (note) note.textContent = "Couldn't save that — " + (err.message || "try again.");
      }
    };

    const mark = $("won-mark");
    // NO CONFIRM ON THE WAY IN. Nothing is sent, nothing leaves the pipeline, and the way back is
    // one click, so a modal to say "we won it" would be ceremony over a cheerful, reversible fact.
    if (mark) mark.addEventListener("click", () =>
      post(mark, { status: "won" }, { won_at: new Date().toISOString() }));
    // ON THE WAY OUT THERE IS ONE, since 2026-08-20. This comment used to say neither half had a
    // prompt and gave the reason above for both. That held while a won card stayed among the live
    // ones, and stopped holding the day the Won TAB took won jobs off the Active board: undoing the
    // mark MOVES THE CARD now, to whichever Active column its own timestamps earn, and Hanz asked
    // for the prompt in the same breath as the bring-back — "before they do that there should be a
    // prompt saying are they sure". Same helper as the other two, so it names the destination.
    //
    // Still `not_won` and not `bring_back`: this button only ever renders on a card that is NOT
    // lost (see wonControlHtml), so there is no second mark to clear, and `bring_back` would also
    // forward "active" to the portal and resume a cadence somebody may have paused on purpose.
    const undo = $("won-undo");
    if (undo) undo.addEventListener("click", async () => {
      if (!(await confirmBringBack(row || {}))) return;
      post(undo, { status: "not_won" }, { won_at: "" });
    });
  }

  /** The notification picker on a project that has not been sent.
   *
   *  Two reads, because the two halves live in different places and neither is the other's business:
   *  the global roster comes from the portal (it is the same list the Notification Sending page
   *  edits), and this project's deviations come off the DRAFT, where they wait until a send exists
   *  to apply them to.
   *
   *  Writes go to the draft endpoint, not the portal's override route — that route 404s for a project
   *  with no proposal row, which is every project in this drawer state. */
  async function loadNotSentNotify(pid) {
    const wrap = $("ns-nt-chips");
    if (!wrap) return;
    let roster = [];
    let picks = { add: [], mute: [] };
    try {
      const [rr, dr] = await Promise.all([
        api("/api/portal/notify-recipients"),
        api("/api/draft/" + encodeURIComponent(pid)),
      ]);
      const rj = await rr.json();
      roster = (rj.recipients || []).filter((x) => x.kind === "general")
        .map((x) => ({ email: x.email, base: x.enabled !== false }));
      const dj = await dr.json();
      const saved = ((dj.data || {}).notify_picks) || {};
      picks = { add: saved.add || [], mute: saved.mute || [] };
    } catch (err) {
      wrap.innerHTML = '<span class="note">Could not load the roster: ' + esc(err.message) + "</span>";
      return;
    }
    if (!roster.length) {
      wrap.innerHTML = '<span class="note">Nobody is on the notification roster yet.</span>';
      return;
    }
    paintNotSentNotify(pid, roster, picks);
  }

  function paintNotSentNotify(pid, roster, picks) {
    const wrap = $("ns-nt-chips");
    const note = $("ns-nt-note");
    if (!wrap) return;
    const add = new Set(picks.add.map((e) => e.toLowerCase()));
    const mute = new Set(picks.mute.map((e) => e.toLowerCase()));
    const effective = (p) => {
      const k = p.email.toLowerCase();
      return mute.has(k) ? false : (add.has(k) ? true : p.base);
    };
    // Only an admin may toggle somebody else — the same rule the Notification Sending page has, and
    // now enforced by /api/draft/{id}/notify as well, so an ungated chip would simply 403.
    let me = "", isAdmin = false;
    try {
      const who = (window.TWAuth && window.TWAuth.user && window.TWAuth.user()) || {};
      me = String(who.email || "").toLowerCase();
      isAdmin = who.role === "admin" || who.role === "super_admin";
    } catch (e) { /* not signed in yet — read-only is the safe default */ }
    wrap.innerHTML = roster.map((p) => {
      const on = effective(p);
      const mayToggle = isAdmin || p.email.toLowerCase() === me;
      // plainAvatar, not avatar: on this control the colour IS the state (green = will hear about
      // it), so an identity colour would compete with the one signal the chip exists to show.
      const body = plainAvatar(p.email) + esc(nameOf(p.email));
      const cls = "nt-chip" + (on ? " on" : "") + (mayToggle ? "" : " nt-chip-ro");
      if (!mayToggle) {
        return '<span class="' + cls + '" title="'
          + esc(p.email + " — only an admin can change this") + '">' + body + "</span>";
      }
      return '<button type="button" class="' + cls + '"'
        + ' data-ns-notify="' + esc(p.email) + '" title="' + esc(p.email) + '">'
        + body + "</button>";
    }).join("");
    if (note) {
      const n = roster.filter(effective).length;
      note.textContent = n + " of " + roster.length
        + " will hear about this when it is sent."
        + (isAdmin ? "" : " You can change only your own.");
    }
    // `[data-ns-notify]`, not `.nt-chip`: the read-only chips above are spans carrying the same
    // class, and wiring a click onto one would let a non-admin fire a request the server refuses.
    wrap.querySelectorAll("[data-ns-notify]").forEach((b) => b.addEventListener("click", async () => {
      const email = b.getAttribute("data-ns-notify");
      const k = email.toLowerCase();
      const person = roster.find((p) => p.email.toLowerCase() === k);
      const next = !effective(person);
      // Back to what the roster already says → forget the deviation, so a project that agrees with
      // the roster stores nothing and keeps following it as the roster changes.
      add.delete(k); mute.delete(k);
      if (next !== person.base) (next ? add : mute).add(k);
      const body = { add: [...add], mute: [...mute] };
      wrap.querySelectorAll("[data-ns-notify]").forEach((x) => { x.disabled = true; });
      try {
        const r = await api("/api/draft/" + encodeURIComponent(pid) + "/notify",
                            { method: "POST", headers: { "Content-Type": "application/json" },
                              body: JSON.stringify(body) });
        if (!r.ok) throw new Error("HTTP " + r.status);
        paintNotSentNotify(pid, roster, { add: body.add, mute: body.mute });
      } catch (err) {
        if (note) note.textContent = "Could not save that: " + err.message;
        wrap.querySelectorAll("[data-ns-notify]").forEach((x) => { x.disabled = false; });
      }
    }));
  }

  /** The estimator picker on a "Created but not sent" project.
   *
   *  Deliberately the DRAFT endpoint (`/api/draft/{id}/assign`), not the portal one the sent
   *  drawer uses: nothing has been published, so there is no portal row to assign against, and
   *  the draft's own copy is exactly what pre-fills the Files-page picker on the first send.
   *
   *  Same shape as the sent drawer's reassign control — disabled until the roster arrives, the
   *  currently-assigned person stays listed even if they have left it, and the button stays off
   *  until the choice actually differs — so the two read as one feature rather than two. */
  function wireNotSentAssign(pid, row) {
    const sel = $("ns-assign"), btn = $("ns-assign-btn"), note = $("ns-assign-note");
    if (!sel || !btn) return;
    // `assigned_estimator` only. `estimatorOf` coalesces the draft's OWNER in as a fallback, which
    // is what draws the "Kyle?" above — pre-selecting that guess would let one click promote it to
    // a decision nobody made.
    const cur = String(row.assigned_estimator || "").toLowerCase();
    loadEstimators().then((people) => {
      if (!$("ns-assign")) return;                         // drawer closed or re-rendered mid-fetch
      if (!people.length) {
        sel.innerHTML = '<option value="">Unavailable</option>';
        if (note) note.textContent = "Couldn't load the estimator list — reload the page.";
        return;
      }
      const known = people.some((x) => String(x.email).toLowerCase() === cur);
      sel.innerHTML = (!cur ? '<option value="">Choose an estimator…</option>' : "")
        + (cur && !known ? `<option value="${esc(cur)}">${esc(nameOf(cur))} (no longer listed)</option>` : "")
        + people.map((x) => `<option value="${esc(x.email)}">${esc(x.name)}</option>`).join("");
      sel.value = row.assigned_estimator || "";
      sel.disabled = false;
      btn.disabled = true;
      sel.addEventListener("change", () => {
        btn.disabled = !sel.value || sel.value.toLowerCase() === cur;
      });
    });
    btn.addEventListener("click", async () => {
      if (!sel.value) return;
      btn.disabled = true;
      const orig = btn.textContent;
      btn.textContent = "Saving…";
      if (note) note.textContent = "";
      try {
        const r = await api("/api/draft/" + encodeURIComponent(pid) + "/assign", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ estimator_email: sel.value }),
        });
        const j = await r.json().catch(() => ({}));
        if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
        // Force the repaint: renderNotSent is signature-guarded against the 12s poll, and the
        // row in hand still carries the OLD assignment, so without this the drawer would show
        // the guess it just replaced.
        DRAWER_SIG = "";
        renderNotSent(pid, Object.assign({}, row, { assigned_estimator: sel.value }));
        load();                                            // the board's card says who owns it
      } catch (err) {
        btn.textContent = orig;
        btn.disabled = false;
        if (note) note.textContent = "Couldn't save that — " + (err.message || "try again.");
      }
    });
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
    // CHAT IS FIRST, on purpose. Hanz, 2026-08-21: "move that tab to the leftmost and make it a
    // different color tab I guess so its just intuittive to always look there". The conversation
    // is the thing a rep needs most often, so it gets the position the eye lands on and a tint of
    // its own (portal.html, `.dtabs .step[data-sec="chat"]`). Key order here is what the strips and anything deriving the
    // tab list from the product both read, so it is changed HERE rather than only in the markup.
    chat:     ["dsec-chat"],
    // dsec-delete is LAST on this tab on purpose: the order here is the order the cards are read
    // in, and the way to remove a project belongs after everything that describes it.
    proposal: ["dsec-customer", "dsec-recipients", "dsec-approved", "dsec-notify",
               "dsec-revisions", "dsec-files", "dsec-delete"],
    deposit:  ["dsec-deposit"],
    contacts: ["dsec-contacts"],
    // No `schedule`. Hanz removed scheduling from both apps on 2026-08-11, the Mark scheduled
    // button and its customer email included: Treadwell books the date on the phone and the
    // customer hears it there, so the app had a status, a tile and a notification all restating
    // a call that had already happened. schedule_status stays in the database untouched.
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
  const REV_CACHE = {};          // sent versions per PROJECT, for the same reason
  let RENDER_GEN = 0;
  let DEEPLINK_USED = false;
  // True while the drawer is showing a project nobody has sent. The tab strip is the same one, but
  // the Proposal tab's two lazy fetches are not: both address a portal row this project does not
  // have yet, so firing them would answer a tab click with "could not load".
  let NS_MODE = false;

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
    // Both of these read the portal's copy of a project, which an unsent one does not have. The
    // not-sent panel carries its own notification picker (draft-backed) and has no versions to list.
    if (sec === "proposal" && !NS_MODE) {
      loadNotifyChips(CUR_PID, RENDER_GEN);
      loadRevisions(CUR_PID, RENDER_GEN);
    }
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

  /** Where a drawer lands when nothing is waiting on a human.
   *
   *  Chat when there is a conversation to read, Proposal when there is not. Hanz, 2026-08-20: "In
   *  the opening of a project, Chat should be the tab thats the first to appear." The intent is to
   *  land where the conversation is, and on a project with no thread that intent lands the rep on
   *  the one panel with nothing in it: a bid nobody has sent has no messages at all, so its Chat
   *  panel is a single paragraph saying so.
   *
   *  ASKED OF THE THREAD, not of which drawer is painting: defaultSection ends in this with the
   *  messages it is about to show, so a SENT project whose customer has never written also lands on
   *  Proposal instead of on "No messages yet." A test of NS_MODE would have answered only for the
   *  unsent half and left that one wrong. (renderNotSent writes the empty-thread answer out; the
   *  note there says why, and a test pins the two together.)
   *
   *  `thread` is the thread AS RENDERED, view card included, so a project whose only entry is
   *  "The customer opened the proposal" counts as having something to read. That is news, and it
   *  is the reason Hanz asked for the bubble. */
  function restingSection(thread) {
    return (thread && thread.length) ? "chat" : "proposal";
  }

  /** Which tab to open on. Answers "why is this drawer open?" — the two
   *  commonest answers, a customer message and a payment, come first.
   *
   *  Sticky WITHIN an open (renderDetail re-runs after every action, and a rep
   *  who just replied must not be thrown off Chat), re-evaluated on each fresh
   *  open (closeDrawer clears ACTIVE_SEC). Deliberately no per-project memory:
   *  remembering the last tab would permanently defeat this routing, since the
   *  board is one session a rep keeps open all day. */
  function defaultSection(p, unread, thread) {
    if (ACTIVE_SEC) return ACTIVE_SEC;
    if (unread > 0) return "chat";
    if (p.deposit_status === "submitted") return "deposit";        // money in, unconfirmed
    // Don't park on Deposit for a job that doesn't collect one — there's nothing
    // to action there. Contacts/schedule is the real next step.
    if (p.proposal_status === "approved" && !p.deposit_requested_at
        && p.deposit_required !== false) return "deposit";
    // THE CONVERSATION IS THE RESTING TAB when there is one, not Proposal. Hanz, 2026-08-20: "In
    // the opening of a project, Chat should be the tab thats the first to appear." The conversation
    // is what somebody opening a project wants to read: what was said, what was asked, whether they
    // opened it. Proposal is reference material you go to deliberately. The three answers above
    // still win, because each of them names something waiting on a human.
    //
    // It costs nothing: applySecPanel shows the chat panel out of the payload the drawer already
    // fetched (the thread ships in /api/portal/proposal/<id>) and DEFERS the Proposal tab's two
    // requests, loadNotifyChips and loadRevisions, until that tab is actually opened.
    //
    // An EMPTY thread is the exception, and restingSection is where that lives.
    return restingSection(thread);
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

  /** The versions of this estimate that have actually been sent.
   *
   *  Hanz, 2026-08-19: "Make sure to also put the revisions here." The Files screen has shown this
   *  since revisions shipped; the drawer is where somebody is standing when they wonder what the
   *  customer was quoted in July, and it made them leave the project to find out.
   *
   *  Read from the DRAFT, not the portal: a revision is the proposal tool's own snapshot of its
   *  estimate (drafts.create_revision on every publish), and the portal only knows the number of
   *  the version it was handed. Cached per project for the same reason the chips are — openDetail
   *  runs again on every 12s poll, and an unguarded fetch would flash its own "Loading…" four times
   *  a minute. */
  async function loadRevisions(pid, gen) {
    if (!pid) return;
    if (REV_CACHE[pid]) { paintRevisions(REV_CACHE[pid], gen); return; }
    try {
      const r = await api("/api/draft/" + encodeURIComponent(pid) + "/revisions");
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      REV_CACHE[pid] = j.revisions || [];
      paintRevisions(REV_CACHE[pid], gen);
    } catch (err) {
      const box = $("rev-list");
      if (box && gen === RENDER_GEN) {
        box.innerHTML = '<span class="note">Could not load the sent versions: ' + esc(err.message) + "</span>";
      }
    }
  }

  function paintRevisions(revs, gen) {
    const box = $("rev-list");
    if (!box || gen !== RENDER_GEN) return;
    if (!revs.length) {
      // A sent project with no snapshot is one sent before revisions existed, which is a fact
      // about the record rather than an error.
      box.innerHTML = '<span class="note">No snapshots yet — this went out before versions were '
        + "recorded.</span>";
      return;
    }
    box.innerHTML = revs.map((rv, i) => `
      <div class="rev-row">
        <strong>Rev ${esc(rv.revision_no)}</strong>
        ${i === 0 ? '<span class="rev-cur">current</span>' : ""}
        <span class="note">${esc(rv.created_at ? TW.fmtBizDate(rv.created_at) : "—")}</span>
        <span class="note">${rv.created_by
          ? avatar(rv.created_by) + esc(nameOf(rv.created_by)) : "—"}</span>
        <strong class="rev-amt">${rv.total == null ? "—" : money(rv.total)}</strong>
        ${rv.has_documents
          ? ["xlsx", "docx", "pdf"].map((k) =>
              `<button type="button" class="btn btn-s rev-dl" data-rev="${esc(rv.revision_no)}"`
              + ` data-kind="${k}">${k === "pdf" ? "PDF" : "." + k}</button>`).join("")
          : '<span class="note">no documents</span>'}
      </div>`).join("");
  }

  /** Rebuild one sent version's documents and save the requested one.
   *
   *  The rebuild is the point: an old revision must be rendered from ITS snapshot, never from the
   *  live draft, or the download would quietly show today's price under a July heading. Same
   *  endpoint and the same octet-stream trick as the Files screen — without the forced type the
   *  browser's inline PDF viewer hijacks the click and the file is never saved. */
  async function downloadRevision(pid, revNo, kind, button) {
    if (!pid || !revNo) return;
    const orig = button.textContent;
    button.disabled = true;
    button.textContent = "…";
    try {
      const r = await api("/api/draft/" + encodeURIComponent(pid) + "/revisions/"
                          + encodeURIComponent(revNo) + "/files", { method: "POST" });
      const out = await r.json();
      if (!r.ok) throw new Error(out.error || out.detail || ("HTTP " + r.status));
      const url = out[kind === "xlsx" ? "xlsx_download_url"
                     : kind === "docx" ? "docx_download_url" : "pdf_download_url"];
      if (!url) throw new Error("not available for this version");
      const resp = await fetch(TW.absoluteUrl(url), { headers: TW.authHeaders() });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const safe = String(out.project_name || "proposal")
        .replace(/[^A-Za-z0-9._-]+/g, "_").slice(0, 60);
      const blobUrl = URL.createObjectURL(new Blob([await resp.arrayBuffer()],
                                                   { type: "application/octet-stream" }));
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = safe + "_rev" + revNo + "_"
        + (kind === "xlsx" ? "estimate" : "proposal") + "." + kind;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(blobUrl), 1500);
      button.textContent = "✓";
    } catch (err) {
      console.error("revision download failed", err);
      button.textContent = "failed";
    }
    setTimeout(() => { button.textContent = orig; button.disabled = false; }, 1800);
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
    // The summary before the detail: nine chips of which some are green is a thing you have to
    // count, and "who is actually getting these" is the question the strip is scanned for.
    // DERIVED, never stored — nothing here changes who is on, which is deliberate. Hanz
    // confirmed the roster is meant to be partly off.
    let on = 0;
    let mine = false;
    wrap.innerHTML = people.map((p) => {
      const e = String(p.email).toLowerCase();
      const mode = ov[e];
      const eff = mode === "add" ? true : mode === "mute" ? false : p.base;
      if (eff) on++;
      if (eff && e === myEmail) mine = true;
      const canEdit = isAdmin || e === myEmail;
      return `<button class="nt-chip ${eff ? "on" : ""}" data-email="${esc(p.email)}" data-base="${p.base ? 1 : 0}" data-eff="${eff ? 1 : 0}"`
           + `${canEdit ? "" : " disabled"} title="${canEdit ? esc(p.email) : "Only admins can change others"}">`
           + `${plainAvatar(p.email)}${esc(nameOf(p.email))}</button>`;
    }).join("") || '<span class="note">No roster yet. Add people on the Notification Sending page.</span>';
    // Written into its own node rather than prepended to the strip: paintNtChips owns
    // #nt-chips outright and rewrites it on every toggle, so anything that has to survive a
    // toggle needs somewhere else to live. Says who as well as how many when it is you,
    // because "am I on this one?" is the question people ask about their own name.
    const count = $("nt-count");
    if (count) {
      count.textContent = !people.length ? ""
        : on === 0 ? "Nobody is being emailed about this project."
        : on + " of " + people.length + (on === 1 ? " person gets" : " people get")
          + " this project's emails" + (mine ? ", including you." : ".");
    }
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
      secTab("chat", "Chat", { needs: s.unread > 0, val: s.unread > 0 ? s.unread + " unread" : "Open",
        badge: s.unread > 0 ? s.unread : "", hint: "Conversation with the customer" }) +
      secTab("proposal", "Proposal", { done: s.approved, val: s.approved ? "Approved" : "Awaiting",
        hint: "Customer, approval, notification recipients" }) +
      secTab("deposit", "Deposit", Object.assign({ hint: "Invoice, what the customer submitted, mark received" }, dep)) +
      secTab("contacts", "Contacts", { done: s.contactsDone, val: s.contactsDone ? "Received" : "Pending",
        hint: "Project contacts the customer supplied" }) +
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
          { num: true, title: "Routing numbers are printed on every check, so this one shows in full" });
      if (x.account_number) {
        const i = secrets.push(String(x.account_number)) - 1;
        add("Account no.", mask4(x.account_number), {
          num: true, id: "dep-acct-" + i,
          title: "Hidden until you show it",
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

  // ── the drawer's information design ────────────────────────────────────────
  // Hanz, 2026-08-13, with a screenshot of the drawer on a sent project: "Improve this
  // Container for better UI UX remove the URL for active projects. Redesign using claude
  // design."
  //
  // What that panel was: five state cards, then flat stacked sections of tiny uppercase
  // labels with run-on sentences under them. The worst of it was the Customer card, which
  // printed the customer's whole magic link — sixty-odd characters of opaque token, wrapped
  // over two lines and underlined — directly beneath the email address, which is the line a
  // rep actually reads. A token is not information to a human: nobody checks it, nobody
  // types it, and it shoved the identity it belongs to out of the way.
  //
  // The builders below carry the redesign. Every one of them takes payload and returns
  // markup, holding no state and touching no DOM, so the whole panel can be executed under
  // node — see backend/tests/js/drawer-render-harness.js, which runs the real renderDetail
  // over real payloads. Source assertions were what let an unbound identifier take this
  // board down on 2026-08-12; a panel this large has to be run, not read.

  /** One labelled fact: the drawer's unit of information.
   *
   *  `v` is MARKUP, not text — the cells carry money spans, secondary lines and monospaced
   *  references — so every caller escapes its own value. Same contract, and the same reason,
   *  as `add()` inside depositHtml. The KEY is escaped here because it is a label, always
   *  ours, and escaping it costs nothing. */
  const fact = (k, v, wide) =>
    `<div class="fact${wide ? " fact-wide" : ""}"><span class="fact-k">${esc(k)}</span>` +
    `<span class="fact-v">${v}</span></div>`;

  /** The head, with the two facts that stay true on every tab.
   *
   *  The step strip below it says which STAGE the project reached; this says what it IS —
   *  who it is for and what it is worth. Both were previously only on the Proposal tab, so
   *  replying to a customer on the Chat tab meant remembering whose job you were looking at.
   *
   *  `meta` is markup the caller has already escaped, for the same reason `fact` is. */
  function drawerHead(title, meta) {
    return `<div class="dhead">
        <div class="dh-t">
          <h2>${esc(title || "Proposal")}</h2>
          ${meta ? `<div class="dh-meta">${meta}</div>` : ""}
        </div>
        <button class="dclose" aria-label="Close">&times;</button>
      </div>`;
  }

  /** Head facts, middot-separated, with the empties dropped rather than leaving a dangling
   *  separator on a project that has no total yet. */
  const metaLine = (bits) => bits.filter(Boolean)
    .join('<span class="dh-sep" aria-hidden="true">·</span>');

  /** Money for the head. "Approved" only when somebody actually approved it: the portal
   *  calls the field `approved_total` on every row, sent ones included, so labelling a
   *  live bid "Approved" would put a word on it that nobody has earned. Same distinction
   *  cardTotal's own comment draws. */
  const headMoney = (approvedTotal, bidTotal) => {
    if (approvedTotal != null) return `<span class="dh-amt amt">Approved ${money(approvedTotal)}</span>`;
    if (bidTotal != null) return `<span class="dh-amt amt">Bid ${money(bidTotal)}</span>`;
    return "";
  };

  /** Who the customer is, and the two ways to reach their view.
   *
   *  THE TOKEN IS NEVER PRINTED. It lives in the anchor's href and nowhere else: not as
   *  text, not in a title, not in an aria-label. A browser already reveals a link's target
   *  in the status bar on hover, which covers the one person who genuinely wants to see
   *  where they are going, and costs the other ninety-nine nothing.
   *
   *  Two controls rather than one, because a link and a link you can send are different
   *  jobs: "Open the customer's view" is a real <a> so middle-click and open-in-new-tab
   *  behave, and "Copy the link" is what a rep needs when they are pasting it into an
   *  email or a text.
   */
  function customerHtml(p) {
    const name = String(p.customer_name || "").trim();
    const email = String(p.customer_email || "").trim();
    // http(s) only. esc() makes the value safe to put INSIDE an attribute, but it says nothing
    // about the scheme, and `href="javascript:…"` is a script that runs on a staff click. The
    // value comes from our own portal over a service token, so this is not a live hole — it is one
    // condition standing between a compromised or misconfigured upstream and code execution in the
    // CRM. Anything else falls through to the no-link branch rather than rendering a control that
    // cannot be trusted. Matches http too: a local portal is http://localhost:8899/p/….
    const url = /^https?:\/\//i.test(String(p.url || "")) ? String(p.url) : "";
    // The name leads when we have one, otherwise the address is the identity — never an
    // empty strong line with the email demoted underneath it.
    const lead = name || email;
    return `<div class="sec" id="dsec-customer">
      <div class="lbl">Customer</div>
      <div class="idn">
        <div class="idn-n">${esc(lead || "No customer on this proposal")}</div>
        ${name && email ? `<div class="idn-e">${esc(email)}</div>` : ""}
      </div>
      ${url ? `<div class="row3">
        <a class="btn btn-s btn-sm is-link" data-portal-link href="${esc(url)}"
           target="_blank" rel="noopener">Open the customer's view<span aria-hidden="true">↗</span></a>
        <button type="button" class="btn btn-s btn-sm" id="cust-copy" data-copy-portal>Copy the link</button>
      </div>
      <p class="note">Anyone with this link can open the proposal, so send it to the customer and nobody else.</p>
      <p class="note" id="cust-copy-say" role="status" aria-live="polite"></p>`
      : '<p class="note">This proposal has no customer link yet.</p>'}
    </div>`;
  }

  /** Put the customer's link on the clipboard, and SAY what happened.
   *
   *  Every branch has to leave a working button. `navigator.clipboard` is absent on an
   *  insecure origin and can reject outright — a denied permission, or a browser that
   *  decides this click did not count as a gesture — and an uncaught rejection here would
   *  strand the one affordance that replaced the URL we removed. So the button label never
   *  enters a pending state it could be stuck in, and the failure path names the way out
   *  that always works: the Open control sitting next to it.
   *
   *  Deliberately NOT a document.execCommand fallback with a hidden textarea. That would
   *  put the token back into the DOM to work around a browser that already said no, for a
   *  case that cannot arise on https://proposals.wetreadwell.com.
   *
   *  Returns true/false so a test can assert every outcome: copied, no clipboard object, no
   *  writeText on it, a rejected promise, and a synchronous throw.
   */
  async function copyPortalLink(url, btn, say) {
    const tell = (m) => { if (say) say.textContent = m; };
    const orig = btn.textContent;
    tell("");
    try {
      const cb = (typeof navigator !== "undefined" && navigator.clipboard) || null;
      if (!cb || !cb.writeText) throw new Error("no clipboard in this browser");
      await cb.writeText(url);
    } catch {
      btn.textContent = orig;
      tell("This browser blocked the copy. Open the customer's view and copy the address from there.");
      return false;
    }
    btn.textContent = "Link copied";
    tell("The link is on your clipboard.");
    setTimeout(() => { btn.textContent = orig; }, 2200);
    return true;
  }

  /** Wire the copy button to the anchor beside it.
   *
   *  The URL is read off the anchor's href rather than stored in a data attribute, so the
   *  customer's token exists in exactly one place in the DOM. Both nodes are resolved HERE,
   *  at bind time, rather than inside the handler: a lookup that only runs on click is a
   *  lookup no test can see failing. */
  function wirePortalLink(d) {
    const btn = d.querySelector("[data-copy-portal]");
    const link = d.querySelector("[data-portal-link]");
    if (!btn || !link) return;
    const say = $("cust-copy-say");
    btn.addEventListener("click", () => copyPortalLink(link.href, btn, say));
  }

  /** The approval, as facts rather than a sentence.
   *
   *  It used to read "HANZ URIEL A DE LA CRUZ on 2026-08-10 — Polish, Epoxy at $22,763.00",
   *  which buries the two things anybody scans for, the money and the date, in the middle of
   *  a name in capitals. Labelled cells put the figure where the eye lands and let a long
   *  name be long without hiding anything behind it.
   *
   *  The signed-in address stays visible. It is the one thing here that can differ from the
   *  typed name — a customer approving from a colleague's login — and it is an email, not a
   *  token: readable, checkable, and the thing you would search for. */
  function approvalHtml(a) {
    if (!a) return "";
    const opts = a.options && a.options.length ? a.options.join(", ") : (a.option || "");
    const signer = [a.name, a.title].filter(Boolean).map(esc).join(", ");
    return `<div class="sec" id="dsec-approved">
      <div class="lbl">Approved</div>
      <div class="facts">
        ${a.total != null ? fact("Amount", `<span class="amt amt-lg">${money(a.total)}</span>`) : ""}
        ${opts ? fact("What they took", esc(opts)) : ""}
        ${a.date ? fact("Date", esc(a.date)) : ""}
        ${signer ? fact("Signed by", signer + (a.approver_email
          ? `<span class="fact-s">signed in as ${esc(a.approver_email)}</span>` : ""), true) : ""}
      </div>
    </div>`;
  }

  /** The contacts the customer sent, role first.
   *
   *  "Who do I call about access" is the question this card gets opened for, so the role is
   *  the column you scan and the name and the numbers hang off it. It used to be three
   *  paragraphs of "Primary: Dave Smith · dave@x.com · (913) 555-0134", which reads as one
   *  grey run at 12px. */
  function contactsHtml(rows) {
    const list = rows || [];
    if (!list.length) return '<p class="note">The customer has not sent their project contacts yet.</p>';
    return `<div class="ct-list">${list.map((c) => {
      const reach = [c.email, c.phone].filter(Boolean).map(esc).join(" · ");
      return `<div class="ct">
        <div class="ct-role">${esc(ROLE_LABEL[c.role] || c.role || "Contact")}</div>
        <div class="ct-n">${esc(c.name || "No name given")}</div>
        ${reach ? `<div class="ct-m">${reach}</div>` : ""}
      </div>`;
    }).join("")}</div>`;
  }

  /** "The customer opened the proposal" as a thread card, SYNTHESISED FROM THE TIMESTAMPS.
   *
   *  Hanz, 2026-08-20: "If the customer views it why is there no chat bubble like The customer has
   *  viewed it in this chatbox?"
   *
   *  It was never a filtering bug — this drawer already asks the portal for the internal cards
   *  (its detail route passes include_internal=True). The portal DOES write a staff-only view card,
   *  but only on a literal sent -> viewed transition: db.mark_viewed returns true for that one row
   *  state, so a project the customer opened BEFORE that feature shipped has no card and can never
   *  get one without a re-send. The row that prompted this was sent 20:33 and viewed 20:36 on
   *  2026-08-18; the card shipped on 2026-08-19.
   *
   *  So the DISPLAY stops depending on a one-shot event. `viewed_at` is written by every view
   *  (coalesced to the first) and cannot be missed, which makes it the honest thing to render from,
   *  and it also covers a transition lost to a crash, a re-send, or two tabs racing.
   *
   *  ONE BUBBLE, NEVER TWO: a stored card wins and this returns the thread untouched. Preferring
   *  the stored one keeps the name of whoever opened it ("Dave opened the proposal.") — which the
   *  timestamps do not carry — along with its id, author and meta. The detector is `meta.view`,
   *  which is what the portal stamps on that row and on nothing else.
   *
   *  DATED BY THE FIRST VIEW, which is both the newsworthy one and the one that puts the card where
   *  it belongs in the conversation. A later re-read is a footnote on the same card ("last opened
   *  …") rather than a second card: a customer who leaves the tab open would otherwise push a fresh
   *  bubble into the thread on every poll. */
  function withViewCard(msgs, p) {
    const list = msgs || [];
    const first = (p && p.viewed_at) || "";
    if (!first) return list;                                        // nobody has opened it
    if (list.some((m) => m && m.meta && m.meta.view)) return list;   // the portal wrote a real one
    const last = (p && p.last_viewed_at) || "";
    // Compared as RENDERED, not as raw stamps: last_viewed_at moves on every open, so a customer
    // reloading twice inside a minute would otherwise get a hint repeating the date beside it.
    const again = last && when(last) !== when(first);
    const card = {
      msg_type: "system",
      // The same shape as the portal's own card, author_kind included, so the two are
      // indistinguishable on screen — sideOf puts both on the staff side.
      author_kind: "staff",
      meta: { view: true, synthetic: true },
      // " — " is what splitSystem cuts on: heading, then the date under it. A CARD carries no
      // timestamp of its own in this thread (msgHtml dates bubbles only), so the date has to be in
      // the body or the card would not say when.
      body: "The customer opened the proposal — " + when(first)
            + (again ? " · last opened " + when(last) : ""),
      created_at: first,
    };
    // Placed at its chronological slot, and INSERTED rather than sorted: re-sorting would reorder
    // rows the portal returned in its own order, including any with no created_at at all.
    // Date.parse rather than a string compare, because these stamps are isoformat() out of
    // Postgres and reach us as both "…Z" and "…+00:00".
    const at = (v) => { const t = Date.parse(v || ""); return isNaN(t) ? 0 : t; };
    const ts = at(first);
    const i = list.findIndex((m) => at(m && m.created_at) > ts);
    const out = list.slice();
    out.splice(i < 0 ? out.length : i, 0, card);
    return out;
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
  // Every template the portal can write into the history, so a row says which reminder went out
  // rather than the generic "Automatic email". The deposit chase and the four staff notes were
  // missing, which made the busiest part of the cadence the least legible part of the history.
  //
  // Staff templates are labelled "Told the team" because that is what happened — nothing in them
  // reached the customer, and a history that reads "Second nudge" beside "Told the team: not opened"
  // is the difference between knowing whether the customer has been bothered or we have.
  const FU_TEMPLATE_LABEL = {
    not_viewed: "Nudge: not opened yet",
    next_steps: "Next steps after viewing",
    second_nudge: "Second nudge",
    checkin: "Check-in",
    deposit_nudge: "Deposit reminder",
    staff_not_viewed: "Told the team: still not opened",
    staff_pause_expired: "Told the team: the pause ended",
    staff_personal_followup: "Told the team: worth a call",
    staff_deposit_outstanding: "Told the team: deposit outstanding",
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

  /** THE HOLD SOMEBODY HERE PRESSED, on a project the customer already has, or null.
   *
   *  Two of Kyle's close-out answers pause a bid instead of killing it, and on a SENT project they
   *  ride the portal's `delayed` status (see the fu-lost handler). That reuse is deliberate and
   *  stays — it is what keeps the card on the Active board with ONE pause date rather than two —
   *  but it has a cost this function pays: portal_proposals stores only the date. There is no
   *  on_hold_reason column on a sent row the way there is on a draft blob, so `followup_state`
   *  cannot answer "why". The reason and the required comment went into portal_followups.detail
   *  instead, which is why the feature needed no DDL, and that log is ALREADY in this payload — so
   *  it is read from there rather than asking the portal for a new field.
   *
   *  THE NEWEST EVENT THAT SET THE PAUSE DECIDES, and only that one. The log is newest-first
   *  (db.list_followups orders by created_at desc, and the History list below renders it in that
   *  order). Two things can set this date: a staff pause, which writes detail.action "paused" and
   *  carries a reason only when it came from the close-out dialog, and the customer's own "revisit
   *  in a few months", which writes detail.status "delayed" and carries no reason at all. Whichever
   *  is newest is the truth about the pause on the row right now: a held bid whose customer then
   *  rings and asks for one month is the CUSTOMER's pause from that moment. Scanning for the newest
   *  entry that happens to have a reason would keep quoting a hold something later replaced.
   *
   *  Guarded on pausedUntil first, so a lapsed or cleared pause reports nothing. The log keeps
   *  every hold ever pressed, and a bid brought back in March must not still read "on hold" in
   *  July. */
  function sentHold(p, data) {
    if (!pausedUntil(p)) return null;
    const rows = (data && data.followups) || [];
    for (let i = 0; i < rows.length; i++) {
      const d = rows[i].detail || {};
      const staffPause = d.action === "paused";
      // The customer's own delay. A terminator rather than something to skip past: it is a newer
      // answer about the same date, and it is not a hold.
      if (!staffPause && String(d.status || "") !== "delayed") continue;
      const label = staffPause ? (C.HOLD_REASON[String(d.reason || "")] || "") : "";
      return label ? { reason: String(d.reason), label, note: String(d.note || "") } : null;
    }
    return null;
  }

  /** How the follow-up tab summarises itself, and what the panel leads with. One
   *  sentence — an estimator opening this tab is asking "is anything chasing this?"
   *
   *  `hold` is sentHold's answer, passed in rather than derived, because it is read out of the
   *  follow-up LOG and this function is handed only the proposal. Optional on purpose: every
   *  caller has the payload, and a caller that does not gets the honest generic answer for a
   *  paused project instead of a claim about who asked for it. */
  function followupState(p, hold) {
    const f = fu(p);
    if (isLost(p)) {
      const why = lostReason(p);
      return { val: "Closed lost", lead: "The customer said they aren't moving forward"
        + (why ? " (" + why.toLowerCase() + ")" : "") + ". Nothing is being sent." };
    }
    const until = pausedUntil(p);
    // A HOLD KYLE PRESSED IS NOT A PAUSE THE CUSTOMER ASKED FOR, and this panel stated the second
    // about the first until 2026-08-21: every held bid read "The customer asked us to come back to
    // this", which is a sentence about a conversation that never happened. Two of the eight answers
    // on the close-out list are internal calls ("Project on Hold", "Small Bid <$25k - Pending") and
    // the customer is deliberately never emailed about either, so attributing them to the customer
    // is the one reading of this row that cannot be true. Kept as two branches rather than softened
    // into one vague sentence, because who asked is exactly what the next reader needs: it decides
    // whether ringing them is following up or is news.
    if (until && hold) return { val: "On hold", lead: "On hold: " + hold.label
      + ". Somebody here put this on hold, so the customer was not told and is not being emailed. "
      + "Nothing chases it until " + TW.fmtBizDay(until) + ", and you can bring it back sooner." };
    if (until) return { val: "Paused", lead: "The customer asked us to come back to this. Follow-ups resume "
      + TW.fmtBizDay(until) + "." };
    if (!f.enrolled) return { val: "Not automated", lead:
      "This proposal was sent before automatic follow-ups existed. Switch them on to start the cadence from today." };
    if (!f.enabled) return { val: "Off", lead:
      "Automatic follow-ups are off for this project. Nothing is sent to the customer unless you send it." };
    // Approved with the money still out. Said before the general case because the general case
    // promises the cadence STOPS at approval, which stopped being true on 2026-08-12 — Hanz:
    // "followups should be automated until a deposit has been received." An estimator reading
    // the old sentence on a won job would think nothing more was going out, and would either
    // duplicate the chase by hand or leave it entirely.
    if (String(p.proposal_status || "") === "approved" && !C.depositSatisfied(p)) {
      const told = String(p.deposit_status || "") === "submitted";
      return { val: "On", lead: told
        ? "Approved, and they've told us the deposit is on its way, so they aren't being emailed "
          + "about it any more. You keep getting reminded until it actually lands."
        : "Approved. Following up automatically until the deposit is in. Their reminders stop as "
          + "soon as they tell us it's on the way; yours continue until it lands." };
    }
    return { val: "On", lead:
      "Following up automatically until the customer approves, replies, or tells us their timeline changed." };
  }

  function followupPanelHtml(p, data) {
    const hold = sentHold(p, data);
    const f = fu(p), st = followupState(p, hold), enabled = !!f.enabled && !isLost(p);
    const log = (data.followups || []).map(followupRow).join("")
      || '<p class="note">Nothing logged yet.</p>';
    const assignee = p.assigned_estimator || "";
    return `
      <div class="sec" id="dsec-followup">
        <div class="lbl">Follow-up</div>
        <p class="note" id="fu-lead">${esc(st.lead)}</p>
        <!-- WHAT SOMEBODY WROTE WHEN THEY PUT IT ON HOLD, quoted, directly under the sentence that
             says it is on hold. nsCloseNote's docstring argues that a sent bid's comment belongs in
             the customer thread and NOT in a second copy here, and for a bid closed LOST that still
             holds: closing is an end, the thread card is the record, and nobody reopens this panel
             to read it. A HOLD IS THE OPPOSITE CASE. It is a live bid, this panel is the only place
             its state is stated, and the comment is the input to the one decision left on it:
             whether today is the day to bring it back. Requiring a sentence and then filing it on a
             different tab from the button it informs is how a required field becomes paperwork.
             So: the hold, here; the close, in the thread. The reason itself is already in the lead
             above, so this is the sentence only.
             The ns-why class is the unsent panel's own, reused rather than twinned: one quoted
             comment should not have two rules that can drift apart. (No backticks in this comment
             either, and no em dash: it ships inside a template literal, inside the panel.) -->
        ${hold && hold.note ? '<p class="note ns-why">“' + esc(hold.note) + '”</p>' : ""}
        <div id="fu-alert" class="note fu-alert"></div>

        <div class="fu-line">
          <button class="btn btn-s" id="fu-toggle" ${isLost(p) ? "disabled" : ""}
            title="${isLost(p) ? "This proposal is closed. Reactivate it first."
                   : enabled ? "Stop sending automatic follow-ups for this project"
                             : "Start the follow-up cadence from today"}">${
            enabled ? "Turn automation off" : "Turn automation on"}</button>
        </div>

        <div class="lbl fu-lbl">Log what you did</div>
        <p class="note">Recording a call or a text keeps this proposal out of tomorrow's digest, and tells whoever picks it up next what already happened.</p>
        <div class="fu-line">
          <select id="fu-kind" class="tw-select" aria-label="What you did">
            <option value="call">Call</option>
            <option value="email">Email</option>
            <option value="text">Text</option>
            <option value="note">Note</option>
          </select>
          <input id="fu-note" type="text" class="fu-note" maxlength="2000"
                 placeholder="Left a voicemail with Dave, will try Thursday" aria-label="Note" />
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
        <!-- THREE STATES, not two, since 2026-08-21, and the missing third one was a dead end. The
             close-out dialog tells the estimator, in these words, that a held bid "stays on the
             Active board and the reminder emails pause for about 4 months ... You can bring it back
             sooner" - and until today there was no control on this panel that brought it back. The
             bring-back rendered on isLost only, a held bid is not lost, so pressing Hold on a sent
             bid left the delay picker, Mark delayed and Mark closed lost and no way out of the four
             months. The unsent drawer had this right from the day holds shipped (#ns-reopen renders
             on nsHoldReason too), so this is the same shape in the half that was missed.
             THE OTHER CONTROLS STAY on a held bid, which is where this deliberately differs from
             the unsent panel. There, a hold hides the close-out and the two-step costs nothing:
             nothing is chasing a bid nobody sent. Here, bringing a bid back RESUMES the cadence, so
             forcing "bring it back, then close it out" on a job Kyle has just learned went to
             another GC would put an automated chase in front of a customer in between. Mark delayed
             stays for the same kind of reason: a customer who rings mid-hold and asks for one month
             is a newer, shorter answer about the same date, and sentHold reads it as theirs. -->
        <div class="fu-line">
          ${isLost(p)
            ? '<button class="btn btn-s" id="fu-reopen">Reactivate this proposal</button>'
            : `${hold ? '<button class="btn btn-s" id="fu-reopen">Bring this bid back</button>' : ""}
               <select id="fu-months" class="tw-select" aria-label="Delay by">
                 <option value="1">1 month</option><option value="2">2 months</option>
                 <option value="3">3 months</option><option value="4">4+ months</option>
               </select>
               <button class="btn btn-s" id="fu-delay">Mark delayed</button>
               <button class="btn btn-s" id="fu-lost">Mark closed lost</button>`}
        </div>

        <!-- Won, by hand: the SENT drawer's copy of the same control the not-sent panel carries.
             Hanz, 2026-08-19: "Is there any way to also mark as won for now other than after the
             deposit has been received". This is the drawer that needed it most, because a verbal yes
             almost always arrives on a proposal the customer already has, days before they click
             Approve. It sits in this section because the line above already exists for exactly this
             case: "when a customer tells you by phone instead of clicking the link in their email".
             (No em dash in this comment: it ships inside the panel, where that is a house rule.) -->
        ${wonControlHtml(p, "lbl fu-lbl")}

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
        reply. They just stop being chased.</p>
      <div class="fu-clist">${chips}</div>
      <div class="fu-line">
        <input id="fu-add-contact" class="tw-input" type="email" autocomplete="off"
               placeholder="Add a contact: name@company.com">
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
    if (toggle) toggle.addEventListener("click", async (e) => {
      const on = !(fu(p).enabled && !isLost(p));
      // TURNING IT ON NOW LIFTS A PAUSE TOO, so it asks first when there is one to lift.
      //
      // The route used to call set_followup_enabled only. On a paused project that made the button
      // a lie: it says "Start the follow-up cadence from today" in its own title, and the cadence
      // stayed paused, so pressing it changed a flag and sent nothing. It is also the workaround an
      // estimator reaches for when they cannot find a bring-back, which is exactly the state a held
      // sent bid was in. So the endpoint resumes as well (admin_followup_automation), and the cost
      // of that is real: the pause it lifts may be one the CUSTOMER asked for, and dropping that
      // silently would start chasing somebody who told us not to. Hence the confirm, and hence it
      // is asked only when a pause exists - the ordinary toggle is still one click.
      if (on && pausedUntil(p)) {
        const ok = await TW.confirmDanger({
          title: "Start chasing again?",
          before: "Turn automation on for ", name: p.project_name || "this project",
          after: " and lift the pause?",
          detail: "Nothing is being sent until " + TW.fmtBizDay(pausedUntil(p))
            + ". Turning automation on clears that, so the reminders start again. The customer is"
            + " not emailed by this.",
          confirmText: "Turn it on", cancelText: "Leave it paused", tone: "warn", icon: "▶",
        });
        if (!ok) return;
      }
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
      const why = await closeOutDialog(p);
      if (!why) return;
      // A HOLD RIDES THE `delayed` STATUS, which is Hanz's instruction and not a shortcut: this
      // project HAS a portal row and a running cadence, and `delayed` is the one thing that pauses
      // a cadence while leaving the card exactly where it sits on the board. A second pausing
      // mechanism beside it would give one bid two pause dates that can disagree. `reason` and
      // `note` ride along so the pause says WHY in the thread instead of appearing as an
      // unexplained gap in the chasing.
      if (why.outcome === "hold") {
        act(path("/status"), e.target, { body: JSON.stringify(
          { status: "delayed", months: HOLD_MONTHS, reason: why.reason, note: why.note }) });
        return;
      }
      act(path("/status"), e.target, { body: JSON.stringify(
        { status: "closed_lost", reason: why.reason, note: why.note }) });
    });

    const reopen = $("fu-reopen");
    if (reopen) reopen.addEventListener("click", async (e) => {
      // THE SAME BUTTON ON A HELD BID, and one word of the prompt changes. The hold is a pause
      // rather than a closure, so "Follow-up reminders start again" is already the whole of what
      // this press does to it — the extra sentence just names the thing being cleared, because an
      // estimator who pressed Hold four months ago is looking for confirmation that THAT is what is
      // coming off. DETAIL_CACHE rather than a `data` argument: this wiring is handed the proposal
      // only, and openDetail fills the cache before it ever renders (the won control's repaint
      // relies on the same thing two blocks down).
      const held = sentHold(p, DETAIL_CACHE[pid]);
      if (!(await confirmBringBack(p, held ? "That also lifts the hold." : ""))) return;
      // THE DRAFT ROUTE, not the portal's own `/status` this used to call, and the reason is the
      // won mark. A job can be marked won (which lives on OUR blob) and then closed lost (which
      // for a sent project lives in the PORTAL), and it reads as Lost only — so reopening just the
      // portal row would move the card straight onto the Won tab. `bring_back` clears our marks
      // and forwards `active` to the portal itself: one press, both stores, and both legs
      // idempotent so a failure is fixed by pressing it again.
      //
      // AND `active` IS WHAT CLEARS A HOLD: the portal's own handler calls resume_followups there,
      // which nulls followup_paused_until. That is why a held bid can share this button rather than
      // needing a route of its own — the pause is the only thing on the row that a hold set.
      act("/api/draft/" + encodeURIComponent(pid) + "/status", e.target,
          { body: JSON.stringify({ status: "bring_back" }) });
    });

    // Deliberately NOT through `act`, which every other control here uses. `act` refreshes by
    // re-fetching the PORTAL payload, and the Won mark is not in it — the drawer would repaint from
    // the stale board row and show "Mark won" on the project it had just marked, for the twelve
    // seconds until the next poll caught up. So this patches the board row (the client's one copy of
    // the mark, per the merge in renderDetail) and repaints from the cached payload.
    wireWon(pid, p, (patch) => {
      const r = ALL.find((x) => x.proposal_id === pid);
      if (r) Object.assign(r, patch);
      DRAWER_SIG = "";
      // openDetail caches the payload before it ever renders, so this is populated whenever these
      // buttons exist. Guarded rather than defaulted: inventing a payload here would render a drawer
      // with no thread, no deposit and no contacts, which is worse than not repainting.
      if (DETAIL_CACHE[pid]) renderDetail(pid, DETAIL_CACHE[pid]);
    });

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

  /** How long a hold pauses the chasing for, on a project the customer HAS.
   *
   *  FOUR is the picker's open-ended top ("4+ months"), and it is the same number the backend uses
   *  for the unsent half (HOLD_PAUSE_MONTHS in main.py) — test_close_out_family.py asserts the two
   *  are equal, because a hold that paused a sent bid for four months and an unsent one for two
   *  would be one feature behaving two ways for no reason a person could see. A hold has no date
   *  on it: Kyle presses it when the GC has gone quiet indefinitely, so a shorter guess would
   *  restart the chasing on a day nobody chose. */
  const HOLD_MONTHS = 4;

  /** THE CLOSE-OUT DIALOG. Why this bid is not going ahead, in Kyle's own words, and the sentence
   *  that says what actually happened.
   *
   *  Hanz, 2026-08-20, with Kyle's screenshot: eight answers, and TWO OF THEM DO NOT CLOSE
   *  ANYTHING. "Project on Hold" and "Small Bid <$25k - Pending" leave the card on the Active board
   *  and pause the reminder emails. `C.closeOutcome` is what decides, so this dialog, the tool's
   *  draft route and the portal's status route all read one answer from one place.
   *
   *  THE COMMENT IS REQUIRED, and it is the first required free-text field in this tool. Every
   *  other note here is optional on purpose — the follow-up log says so in as many words ("A bare
   *  'Call' with no note is still worth logging"). This one is different because a reason on its
   *  own tells the next person nothing: by the end of a quarter "Not Low Bid" is eight identical
   *  cards, and "we were 12% over Wilson on the pour" is the sentence the sales meeting is
   *  actually held to read.
   *
   *  The house idiom for a field that must be filled, borrowed off the estimator picker two
   *  sections down: the confirm button starts disabled, a sibling <p class="note"> says what is
   *  wanted, and both `input` and `change` re-check. `input` alone misses a paste from the context
   *  menu in some browsers; `change` alone leaves the button dead until the field blurs, which
   *  reads as broken while you are still typing in it.
   *
   *  RESOLVES AN OBJECT — { reason, note, outcome } — or null when dismissed. It resolved a bare
   *  reason string until 2026-08-20, and could not have done otherwise: there was one field. Both
   *  callers still test the falsy answer first, so dismissing is unchanged; what they gained is
   *  the branch on `outcome`, which is the whole of "those two do not close the job".
   */
  function closeOutDialog(p, opts) {
    // `unsent` swaps one sentence. "All follow-ups stop" is the reassurance that matters on a
    // proposal the customer has — and it is not true of a bid that was never sent, where nothing
    // was ever chasing. Promising to stop something that is not running reads as a system that
    // does not know its own state.
    const unsent = !!(opts && opts.unsent);
    const name = p.project_name || "This project";
    return new Promise((resolve) => {
      const ov = document.createElement("div");
      ov.className = "inv-ov";
      ov.innerHTML = `<div class="inv-dlg" role="dialog" aria-modal="true" aria-label="Close this bid out">
        <div class="inv-h">Close this bid out?</div>
        <p class="inv-sub" data-sub></p>
        <label class="inv-f co-f">
          <span>Why?</span>
          <select data-why>${C.CLOSE_CHOICES.map((c) =>
            `<option value="${esc(c.key)}">${esc(c.label)}</option>`).join("")}</select>
        </label>
        <label class="inv-f co-f">
          <span>What happened? Required</span>
          <textarea data-note rows="3" maxlength="2000"
            placeholder="We were 12% over Wilson on the pour, GC said they would call us for phase 2."></textarea>
        </label>
        <p class="note co-err" data-err></p>
        <div class="inv-act">
          <button type="button" class="btn btn-s" data-x>Cancel</button>
          <button type="button" class="btn btn-p" data-go disabled>Close it out</button>
        </div></div>`;
      document.body.appendChild(ov);
      const sel = ov.querySelector("[data-why]");
      const note = ov.querySelector("[data-note]");
      const err = ov.querySelector("[data-err]");
      const go = ov.querySelector("[data-go]");
      const sub = ov.querySelector("[data-sub]");

      /** Repaint the two things the answer changes: what this will do, and what the button says.
       *  Called on every `change` of the select, so the copy can never describe the answer the
       *  estimator had selected a moment ago. */
      const paint = () => {
        const hold = C.closeOutcome(sel.value) === "hold";
        go.textContent = hold ? "Put it on hold" : "Close it out";
        sub.textContent = hold
          ? name + " stays on the Active board and the reminder emails pause for about "
            + HOLD_MONTHS + " months. Nothing is sent to the customer. You can bring it back sooner."
          : name + (unsent
            ? " moves to the Lost tab under the reason you pick. It was never sent, so nothing"
              + " changes for the customer."
            : " moves out of the pipeline and all follow-ups stop. The customer is not emailed.")
            + " You can bring it back later.";
        // The required-field state, recomputed here as well as on input so switching the answer
        // cannot leave a live button above an empty box.
        const filled = !!note.value.trim();
        go.disabled = !filled;
        err.textContent = filled ? ""
          : "Say what happened. One sentence is plenty, and it is the part the sales meeting reads.";
      };
      paint();

      const close = (v) => { ov.remove(); document.removeEventListener("keydown", onKey); resolve(v); };
      const onKey = (e) => { if (e.key === "Escape") close(null); };
      document.addEventListener("keydown", onKey);
      sel.addEventListener("change", paint);
      note.addEventListener("input", paint);
      note.addEventListener("change", paint);
      ov.querySelector("[data-x]").addEventListener("click", () => close(null));
      ov.addEventListener("click", (e) => { if (e.target === ov) close(null); });
      go.addEventListener("click", () => {
        const text = note.value.trim();
        // Checked again on the way out, not only on the way in. The button being disabled is a
        // courtesy; this is the guard. A stray repaint, a browser that fires click on a disabled
        // control, or a future keyboard shortcut all reach here, and the two backend routes 422
        // an empty comment anyway — better to say so in the dialog than to bounce off the server.
        if (!text) { paint(); note.focus(); return; }
        // `|| "other"` for the same reason it was here before: a select with no value at all
        // (which is what a browser gives for an empty <select>) must be a mis-click landing on
        // Other, not a 422 the estimator has to decode.
        const reason = sel.value || "other";
        close({ reason, note: text, outcome: C.closeOutcome(reason) });
      });
      sel.focus();
    });
  }

  /** WHERE THIS CARD WOULD LAND if its outcome were cleared, named the way the board names it.
   *
   *  Hanz, 2026-08-20: "there should be a prompt saying are they sure". A prompt that only asks
   *  "are you sure?" is one nobody can answer — sure of WHAT? So the answer is computed, and
   *  computed the only honest way: by running the board's own stage() over the row with the
   *  outcome taken off it.
   *
   *  THAT WORKS BECAUSE NOTHING WAS OVERWRITTEN. Closing a job lost never touched a pipeline
   *  timestamp — the portal's close_lost leaves approved_at, the deposit columns and the contacts
   *  columns exactly as they were, and reopen_if_closed reads approved_at back to choose the status
   *  it restores. So a card that stops being lost recomputes its own way to the furthest step it
   *  genuinely reached, and there is deliberately no "remember the previous stage" field: that
   *  would be a second source of truth for a question the stamps already answer, and it would be
   *  wrong the first time a deposit landed while the job sat closed.
   *
   *  proposal_status is set to what the PORTAL will restore rather than blanked, because blanking
   *  it would make stage() say "Sent" about a job the customer had signed. reopen_if_closed
   *  restores 'approved' when approved_at survived and 'sent' otherwise; a synthesised not-sent row
   *  has no portal status at all and stage() reads `not_sent` before any of this.
   *
   *  A DERIVED WIN SURVIVES THE CLEAR, so the answer has to be able to be a Won column. Clearing
   *  won_at unmarks a by-hand win, but a job that is approved with the deposit settled is won by
   *  the numbers (C.isWon) and belongs on the Won tab whatever anybody clears — telling the
   *  estimator it was going back to "Contact info" would be a lie about a card they are about to go
   *  looking for.
   *
   *  TWO FIELDS AND NO MORE. followup_state is left exactly as it is, and that is deliberate rather
   *  than an omission: stage(), isWon() and wonColumn() read proposal_status, not_sent, the deposit
   *  and contacts columns and won_at, and none of them touches followup_state - only lostReason,
   *  pausedUntil, followupOff and stageTs do, and none of those is asked here. A copy that also
   *  blanked closed_lost_reason and closed_at would be a line no test could tell from its absence,
   *  which is how a reader comes to believe stage() reads a field it does not. */
  function reopenDestination(p) {
    const clean = Object.assign({}, p, {
      proposal_status: p.not_sent ? "" : (p.approved_at ? "approved" : "sent"),
      won_at: "",
    });
    return C.isWon(clean) ? "Won \u00B7 " + C.wonColumn(clean) : C.stage(clean);
  }

  /** The prompt. ONE helper for all three controls that put a card back, so the three cannot come
   *  to describe the same act three different ways.
   *
   *  TW.confirmDanger rather than window.confirm, and rather than a fourth hand-rolled overlay: it
   *  is what the delay and the deposit confirms in this same drawer already use, it traps focus
   *  between its two buttons, and it focuses Cancel. `warn`, not `danger`: this undoes something
   *  rather than destroying it. */
  function confirmBringBack(p, extra) {
    return TW.confirmDanger({
      title: "Bring this back?",
      before: "Put ", name: p.project_name || "this project",
      after: " back under " + reopenDestination(p) + "?",
      detail: "Follow-up reminders start again." + (extra ? " " + extra : ""),
      confirmText: "Bring it back", cancelText: "Leave it", tone: "warn", icon: "\u21A9",
    });
  }

  /** DELETING A PROJECT, in either drawer. "" for anybody who is not an admin.
   *
   *  Hanz, 2026-08-24: "In the proposals tab under the Active Projects create a 'delete project'
   *  button", and "make sure there is a confirmation dialog". He had two SENT test bids that no
   *  control in either app could take off the Active Projects board: the Proposals Database's
   *  Trash button deletes the DRAFT, and the board is built from the portal's rows, whose query
   *  deliberately ignores the draft's deleted_at. So the card outlived the project.
   *
   *  ONE FUNCTION FOR BOTH PANELS, because a sent project and an unsent one differ in the copy and
   *  in nothing else. `not_sent` is the only field that tells them apart and only the synthesised
   *  rows carry it, so the sent drawer (which is handed the portal's own proposal object) gets the
   *  sent wording without having to ask for it.
   *
   *  APART FROM THE THREE WAYS OUT of this drawer, in its own section under them, and that
   *  placement is the point rather than layout: Open the files, Edit the estimate and Info sheet
   *  sit in one .row3, and a fourth button in that row would be a delete an estimator could hit
   *  while reaching for the estimate.
   *
   *  The admin read is inline rather than a helper for the same reason paintNtChips does it inline:
   *  it is three lines, it must never throw on a page where sign-in has not landed yet, and a
   *  helper would be a fourth name for three harnesses to bind.
   */
  function deleteProjectHtml(p) {
    let isAdmin = false;
    try {
      const who = (window.TWAuth && window.TWAuth.user && window.TWAuth.user()) || {};
      isAdmin = who.role === "admin" || who.role === "super_admin";
    } catch (e) { /* not signed in yet, so the safe answer is "no control at all" */ }
    if (!isAdmin) return "";
    const sent = !(p && p.not_sent);
    // Two ids, because the sent drawer's cards are hidden per-card by applySecPanel (so this one
    // has to be in SEC_TABS) while the not-sent panel hides whole PANELS and keeps its dsec-ns-*
    // ids deliberately outside that machinery.
    return `
        <div class="sec" id="${sent ? "dsec-delete" : "dsec-ns-delete"}">
          <div class="lbl">Delete this project</div>
          <p class="note">${sent
            ? "Takes the card off the board and stops the follow-up emails. The link the customer "
              + "already has keeps working, and you can restore the project from Trash."
            : "Takes the card off the board and files the project in Trash. Nothing reaches the "
              + "customer, and you can restore it from there."}</p>
          <div class="fu-line">
            <button type="button" class="btn btn-s btn-dang" id="del-project">Delete project</button>
          </div>
          <p class="note del-note" id="del-note"></p>
        </div>`;
  }

  /** The button, its confirmation, and what it does. Called by BOTH renderers.
   *
   *  TW.confirmDanger, the same helper confirmBringBack is built on: it traps focus between its two
   *  buttons and focuses Cancel, and it is what every other destructive control in this app asks
   *  through. Never window.confirm.
   *
   *  TWO BODIES, because an unsent scratch bid and a live customer job are not the same act. The
   *  sent one names the two things that go quiet (the card and the chasing) and is honest about the
   *  one thing that does NOT change: the customer's existing link keeps working, because it renders
   *  the revision that was pinned when the proposal was sent rather than anything we are hiding
   *  here. Deleting is not revoking, and a dialog that implied it was would get pressed by somebody
   *  trying to take a link away.
   *
   *  Both name the project. "Are you sure?" is a question nobody can answer.
   *
   *  ONE REQUEST, to a route that owns both halves. Two calls from here (hide the portal row, then
   *  trash the draft) would leave a half-deleted project on a dropped connection, and half is the
   *  exact state this feature exists to remove.
   */
  function wireDeleteProject(pid, row) {
    const btn = $("del-project");
    if (!btn) return;                  // not an admin: there is no control to wire
    const note = $("del-note");
    btn.addEventListener("click", async () => {
      const sent = !(row && row.not_sent);
      const name = (row && row.project_name) || "this project";
      const ok = await TW.confirmDanger(sent ? {
        title: "Delete this project?",
        name: name,
        after: " comes off the board and its follow-up emails stop.",
        detail: "The link the customer already has keeps working: it reads the version pinned"
              + " when you sent it. Restore it from Trash and the reminders stay off.",
        confirmText: "Move it to Trash", cancelText: "Keep it",
        tone: "danger", icon: "🗑",
      } : {
        title: "Delete this project?",
        name: name,
        after: " comes off the board and out of the Proposals Database.",
        detail: "It was never sent, so nothing changes for the customer. You can restore it"
              + " from Trash.",
        confirmText: "Move it to Trash", cancelText: "Keep it",
        tone: "danger", icon: "🗑",
      });
      if (!ok) return;
      btn.disabled = true;
      const orig = btn.textContent;
      btn.textContent = "Deleting…";
      if (note) note.textContent = "";
      try {
        const r = await api("/api/project/" + encodeURIComponent(pid) + "/delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        const j = await r.json().catch(() => ({}));
        if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
        // The drawer is showing a project that is no longer on the board, so it closes rather than
        // repainting into a panel about a deleted job. The board reload is what makes the card go.
        closeDrawer();
        load();
      } catch (err) {
        btn.textContent = orig;
        btn.disabled = false;
        if (note) note.textContent = "Couldn't delete that. " + (err.message || "Try again.");
      }
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

    const contacts = contactsHtml(data.contacts);

    // Built BEFORE the template literal so eligibility below can read the ONE answer to "did this
    // render": a second `isAdmin` computed at setSecEligible time is a second answer, and the two
    // halves of applySecPanel's condition disagreeing is how this drawer ships an empty tab.
    const delHtml = deleteProjectHtml(p);

    // Full account numbers stay in this array, NOT in the markup — see depositHtml.
    const acctFull = [];
    const deposits = (data.deposits || []).map((x) => depositHtml(x, acctFull)).join("");

    const depAmt = p.deposit_amount != null ? p.deposit_amount : (a ? a.total * 0.25 : null);

    const unread = unreadCount(pid, msgs);

    // The board row: the only place several draft-side facts exist for a SENT project, and the
    // same lookup unreadCount and the not-sent branch already rely on. Read here rather than
    // below, so the merge on the next line lands before the signature is taken.
    const row = ALL.find((x) => x.proposal_id === pid);
    // The by-hand Won mark lives on OUR draft blob (drafts.set_won), so the portal's detail payload
    // has never heard of it and isWon would answer "no" in this drawer about a project the board
    // already shows a Won chip on. ASSIGNED, not defaulted: undoing the mark has to clear it here
    // too, and `p` is the cached payload's own object, so a stale `||` would pin the old answer for
    // as long as the drawer stays open. Mutating `p` before the signature is what makes the mark
    // part of it — so a colleague's mark repaints this panel on the next poll.
    if (row) p.won_at = row.won_at || "";
    // The view stamps, read the same way and for the same reason: the staff detail payload has
    // no viewed_at/last_viewed_at on `proposal` (checked against the portal's own handler), the
    // BOARD list endpoint serves both, and the thread's "they opened it" card below is rendered
    // from them. The row WINS when it has a value rather than filling a gap, with the payload's own
    // field as a fallback so this keeps working if the portal ever starts serving one.
    //
    // ONLY `viewed_at` GOES ONTO THE PAYLOAD, and the asymmetry is the fix for a bug this merge
    // caused. Merging it before the signature is what makes a first view repaint an open drawer,
    // exactly as the won mark does, and a first view is news: it draws the bubble.
    if (row) p.viewed_at = row.viewed_at || p.viewed_at || "";
    // `last_viewed_at` stays a LOCAL, out of `data` and therefore out of the signature below. The
    // portal stamps it on every customer view, so it moves whenever a customer merely reloads the
    // page they were already sent. While it lived on `p` the 12s poll rebuilt the whole drawer for
    // that re-read: thread, tab strip, and the reply box with whatever a rep was half way through
    // typing in it. The footnote it feeds ("last opened …") is the only thing that reads the
    // proposal-level stamp, and it catches up on the next repaint something a human is waiting on
    // earns. (The per-RECIPIENT stamps in data.recipient_activity are a separate set of fields and
    // are still in the signature, so a re-read by a named contact can still cost a repaint. That
    // one is older than this drawer and wants the portal's payload pinned down first.)
    const lastViewed = (row && row.last_viewed_at) || p.last_viewed_at || "";

    // Nothing changed? Leave the DOM alone. This is the guard that makes the 12s drawer poll
    // invisible: without it every tick destroyed the thread, the tab strip and every card, and
    // threw away wherever the rep had scrolled.
    //
    // `unread` is in the signature because it is read off the BOARD row, not this payload, so it
    // can move while the proposal itself is unchanged — and it drives the Chat badge. ACTIVE_SEC
    // deliberately is NOT: switching tabs only toggles classes, it never re-renders, so putting
    // it here would repaint the whole drawer on every tab click.
    //
    // WHAT IS NOT IN IT, on purpose: `lastViewed`. It is a local rather than a field on `data` for
    // exactly this reason (see the note on the merge above). A customer re-reading the proposal is
    // not a change anybody is waiting on, and while that stamp was in here it cost the rep with the
    // drawer open their caret and their scroll position on the next poll after every re-read.
    // `viewed_at` IS in, through `data`: the first open draws the bubble.
    const sig = JSON.stringify([pid, data, unread]);
    if (sig === DRAWER_SIG) return;
    DRAWER_SIG = sig;
    NS_MODE = false;                 // a sent project: the portal-backed loads apply again

    // Set BEFORE the markup below is built: msgHtml reads it to decide whether to name the
    // author, and a message rendered before it is populated would go unnamed. `data` is already
    // in the signature above, so a recipient being added repaints on its own.
    DETAIL_RECIPIENTS = (data && data.recipients) || [];

    // The thread, built HERE rather than at the top of this function, for two reasons. msgHtml
    // reads DETAIL_RECIPIENTS (the line above) to decide whether to name the author, and it reads
    // the view stamps read above. `unread` is still counted off the raw `msgs`, so the synthesised
    // card below can never move the Chat badge.
    //
    // Two details in one line below. The stamps are handed over as their own object rather than as
    // `p`, because one of the two deliberately never reached `p` (the signature note above says
    // why) and withViewCard wants both. And the ARRAY is kept, not only the markup: defaultSection
    // asks whether the thread has anything in it before deciding that Chat is worth landing on, and
    // "as rendered" has to mean the same list the panel below shows, view card included.
    const threadMsgs = withViewCard(msgs, { viewed_at: p.viewed_at, last_viewed_at: lastViewed });
    const thread = threadMsgs.map(msgHtml).join("")
      || '<p class="note">No messages yet.</p>';

    // Where the chat was, before the innerHTML below detaches it. Must happen here rather than
    // in the caller: renderDetail is the only place that destroys #thread, and every path
    // through it — poll, action, reply, chip toggle — needs the position kept.
    const t0 = $("thread");
    THREAD_SCROLL = t0
      ? { top: t0.scrollTop, atBottom: t0.scrollHeight - t0.scrollTop - t0.clientHeight < 40 }
      : null;

    ACTIVE_SEC = defaultSection(p, unread, threadMsgs);

    // What the head says on every tab: who it is for, and what it is worth. `row` (above) is the
    // only place a total exists before approval — the drawer payload has no such field — and the
    // drawer is always opened from a loaded board.
    const head = drawerHead(p.project_name, metaLine([
      (p.customer_name || p.customer_email)
        ? `<span class="dh-who">${esc(p.customer_name || p.customer_email)}</span>` : "",
      headMoney(a && a.total != null ? a.total : null, row ? cardTotal(row) : null),
    ]));

    // The tab strip is a THIRD flex item between .dhead and .dbody, not a child
    // of .dbody: #drawer is a flex column and .dhead pins by flex:0 0 auto, so a
    // sibling pins for free — no position:sticky, no z-index, and no fight with
    // .dbody's top padding.
    $("drawer").innerHTML = `
      ${head}
      ${renderSecTabs({ approved, depositDone, depositSubmitted, depositNotRequired,
                        contactsDone,
                        requested: !!p.deposit_requested_at, unread,
                        lost: isLost(p),
                        // The HOLD is passed through here as well as inside the panel, so the tab
                        // pill reads "On hold" rather than "Paused" on a bid a staff member held.
                        // The pill is the only part of this state visible with the panel shut.
                        fuVal: followupState(p, sentHold(p, data)).val })}
      <div class="dbody">
       <div class="dpanel" id="dpanel-proposal" role="tabpanel" aria-labelledby="dtab-proposal" tabindex="-1">
        ${customerHtml(p)}
        ${recipientsHtml(data.recipient_activity)}
        ${approvalHtml(a)}

        <div class="sec" id="dsec-notify">
          <div class="lbl">Notifications for this project</div>
          <p class="note" id="nt-help">Who gets an email when this customer replies, approves, or pays. Green means they are on. This overrides the global roster for this project only, and toggling somebody never sends them anything.</p>
          <p class="note" id="nt-count"></p>
          <div id="nt-alert" class="note"></div>
          <div id="nt-chips" class="nt-chips"><span class="note">Loading…</span></div>
        </div>

        <!-- Every send snapshots the estimate, so the versions are a real record of what each
             customer was quoted and when. Hanz, 2026-08-19: "Make sure to also put the revisions
             here." They were only on the Files screen, which meant answering "what did we send them
             in July?" required leaving the project you were looking at. -->
        <div class="sec" id="dsec-revisions">
          <div class="lbl">Sent versions</div>
          <p class="note">Each send pins the estimate as it was, so an old version stays readable
          even after the draft moves on.</p>
          <div id="rev-list"><span class="note">Loading…</span></div>
        </div>

        <!-- The files and the hand-off sheet, ON A SENT PROJECT TOO. Hanz, 2026-08-20: "Move the
             info sheet button inside proposals tab."
             This panel had NEITHER control. The not-sent drawer has had "Open the files" since it
             shipped, and a sent project reached its files only from the board card, so moving the
             card's buttons into the drawer without adding them here would have left every project
             the customer has actually seen with no route to its estimate, its proposal or its Info
             Sheet at all. Same two URLs as the card and the Proposals Database, character for
             character.
             NB no em dash in this comment: test_drawer_renders.py greps the whole panel, comments
             included. -->
        <div class="sec row3" id="dsec-files">
          <button type="button" class="btn btn-s" id="go-files">Open the files</button>
          <button type="button" class="btn btn-s" id="go-info">Info sheet</button>
        </div>

        <!-- Delete, on a SENT project too. Hanz, 2026-08-24: a sent bid keeps its card otherwise,
             which is the bug he hit. Its own section below the files row for the reason the
             not-sent panel gives: that row is the ways out of the drawer, not a place to put a
             delete. The dialog this button opens carries the heavier of the two bodies, because
             this one stops the follow-up emails.
             NB no em dash in this comment: test_drawer_renders.py greps the whole panel. -->
        ${delHtml}
       </div>

       <div class="dpanel" id="dpanel-deposit" role="tabpanel" aria-labelledby="dtab-deposit" tabindex="-1">
        <div class="sec" id="dsec-deposit">
          <div class="lbl">Deposit</div>
          ${depositNotRequired
            ? `<p class="note">This proposal went out without a deposit, so nothing was invoiced and the customer sees no Deposit step. You can still send a request below if the terms change.${depAmt != null ? ` A 25% deposit would be ${money(depAmt)}.` : ""}</p>`
            : `<div class="facts">
                ${fact("Deposit at 25%", depAmt != null ? `<span class="amt">${money(depAmt)}</span>` : "Not calculated")}
                ${data.deposit_ref ? fact("Match on the statement", `<span class="dep-num">${esc(data.deposit_ref)}</span>`) : ""}
                ${p.deposit_requested_at ? fact("Invoice sent", esc(when(p.deposit_requested_at))) : ""}
              </div>`}
          ${deposits
            ? `<div class="lbl dep-lbl">What the customer submitted</div>${deposits}`
            : '<p class="note dep-none">The customer has not submitted a deposit yet.</p>'}
          <div class="row3">
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
            <div id="reply-alert" class="note"></div>
            <textarea id="reply-body" placeholder="Reply to the customer…">${esc(REPLY_DRAFT[pid] || "")}</textarea>
            <div class="row3"><button class="btn btn-p" id="reply-btn">Send reply</button></div>
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
    // Sent versions. This call was MISSING from the day the card shipped (2026-08-19), so the card
    // was in SEC_TABS, rendered into the Proposal panel, fetched by applySecPanel, painted by
    // paintRevisions, and hidden by applySecPanel on every single render: SEC_ELIGIBLE never held
    // its id, and the two conditions are ANDed. Nobody had ever seen "Sent versions". Always
    // eligible, like the files card below it: every sent project has a version history, and a
    // project sent before revisions existed says so in the panel.
    setSecEligible("dsec-revisions", true);
    // Always: every project has files and an info sheet, sent or not, won or lost.
    setSecEligible("dsec-files", true);
    // Only when the markup exists. A non-admin renders nothing here, and an eligible id with no
    // element is exactly the mismatch test_drawer_renders.py asserts against.
    setSecEligible("dsec-delete", !!delHtml);
    setSecEligible("dsec-deposit", true);
    setSecEligible("dsec-contacts", true);
    setSecEligible("dsec-chat", true);
    setSecEligible("dsec-followup", true);

    const d = $("drawer");
    d.querySelector(".dclose").addEventListener("click", closeDrawer);
    wirePortalLink(d);

    // The two ways out of this drawer to the paperwork. The same URLs the board card, the
    // Proposals Database and the not-sent drawer use, character-for-character.
    $("go-files").addEventListener("click",
      () => window.location.assign("/done.html?d=" + encodeURIComponent(pid) + "&files=1"));
    $("go-info").addEventListener("click",
      () => window.location.assign("/info-sheet.html?d=" + encodeURIComponent(pid)));
    wireDeleteProject(pid, p);

    // Reveal / re-hide a full account number. The value lives in `acctFull`, so it
    // only reaches the DOM when a human asks for it — and goes back on a second click.
    d.querySelectorAll(".dep-show").forEach((b) => b.addEventListener("click", () => {
      const i = Number(b.dataset.acct);
      const el = d.querySelector("#dep-acct-" + i);
      if (!el || acctFull[i] == null) return;
      const shown = b.getAttribute("aria-pressed") === "true";
      el.textContent = shown ? mask4(acctFull[i]) : acctFull[i];
      el.title = shown ? "Hidden until you show it" : "Full account number";
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
        btn.textContent = "Failed: " + (err.message || "retry"); btn.disabled = false;
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
        detail: what + "Check the money has actually landed. The customer is told it is in.",
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

  /** The Active / Won / Lost / Test switch. The counts come off the same predicates boardPool
   *  filters with, so a tab can never advertise a number it then refuses to show — and because the
   *  four pools partition `ALL`, the four counts add up to every proposal there is.
   *
   *  Computed here rather than as `boardPool()` per tab because boardPool closes over TAB: asking it
   *  four times would mean assigning TAB four times mid-render. So the precedence is spelled out a
   *  second time, in the same order — lost, then test, then won — and test_won_tab.py asserts the
   *  four numbers sum to `ALL`, which is the property that catches the two copies drifting.
   *
   *  This replaced a "N closed lost →" link out to /projects.html. That link could never do what
   *  it implied: that page reads no filter from the URL, its tabs are Active / Inactive / All /
   *  Test, and it lists our own drafts rather than portal rows — it has no notion of closed_lost
   *  at all. So it landed you on an unfiltered list to hunt through. The tab shows them. */
  function syncTabs() {
    const wrap = $("crm-tabs");
    if (!wrap) return;
    const live = ALL.filter((p) => !isLost(p));
    // Real live work: what the Active and Won pills split between them. A won TEST project is
    // counted under Test, exactly as boardPool files it.
    const real = live.filter((p) => !isTest(p));
    const n = { test: live.filter(isTest).length,
                won: real.filter((p) => C.isWon(p)).length,
                active: real.filter((p) => !C.isWon(p)).length,
                lost: lostCount() };
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
      PERIOD = month.value; ssSet(PERIOD_KEY, PERIOD); renderBoard();
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
    // Delegated, so the buttons need no per-element binding, and TAB is in BOARD_SIG, so
    // renderBoard is guaranteed to repaint (including the pressed state, via syncTabs).
    if (tabs) tabs.addEventListener("click", (e) => {
      const b = e.target.closest("[data-tab]");
      if (!b || b.dataset.tab === TAB) return;
      // Against the known set, not `=== "test" ? "test" : "active"`. That coercion was correct
      // while there were two tabs and silently swallows a third: clicking Lost would have stored
      // Active, painted the Active board, and looked like a dead button.
      TAB = TABS.includes(b.dataset.tab) ? b.dataset.tab : "active";
      ssSet(TAB_KEY, TAB);
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
      EST = ""; PERIOD = ""; SORTFIELD = "activity"; SORTDIR = "desc";
      [EST_KEY, PERIOD_KEY, SORTFIELD_KEY, SORTDIR_KEY].forEach((k) => ssSet(k, ""));
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
