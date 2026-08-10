// Follow-ups page — every proposal that has been sent, and where its chase stands.
// Externalized (no inline scripts; CSP). Do not add inline handlers.
//
// WHY THIS PAGE EXISTS. The cadence, the pauses and the "nobody has chased this in nine
// days" facts were all real but invisible: they lived in the follow-up worker, in a
// drawer tab you had to open one project at a time, and in a 6 AM email. This is the one
// screen that shows all of it at once, for everybody.
//
// The ranking and the "why it's here" sentence come from the SERVER
// (/api/portal/followups -> digest_worker), the same code that writes the morning email.
// Recomputing them here in JavaScript is how a page ends up disagreeing with the email it
// is supposed to explain.
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const C = window.TWCrm;
  const money = (n) => (typeof n === "number" ? "$" + n.toLocaleString(undefined, { maximumFractionDigits: 0 }) : "");

  const api = (path, opts) => fetch(TW.resolveApiBase() + path,
    Object.assign({}, opts || {}, { headers: TW.authHeaders((opts || {}).headers) }));

  let ALL = [];
  const K = { tab: "tw_fu_tab", est: "tw_fu_est", sort: "tw_fu_sort", dir: "tw_fu_dir", q: "tw_fu_q",
              view: "tw_fu_view" };
  const ss = (k, d) => { try { const v = sessionStorage.getItem(k); return v == null ? d : v; } catch { return d; } };
  const ssSet = (k, v) => { try { v ? sessionStorage.setItem(k, v) : sessionStorage.removeItem(k); } catch {} };

  const SORTS = ["score", "due", "chased", "quiet", "name", "value"];
  // Each opens the way you'd want to read it: worst first, soonest first, longest-ago first.
  const NATURAL = { score: "desc", due: "asc", chased: "asc", quiet: "desc", name: "asc", value: "desc" };
  let TAB = ss(K.tab, "live");
  let EST = ss(K.est, "");
  let SORT = SORTS.includes(ss(K.sort, "")) ? ss(K.sort, "") : "score";
  let DIR = ss(K.dir, "") || NATURAL[SORT];
  let Q = ss(K.q, "");
  let VIEW = ss(K.view, "") === "board" ? "board" : "list";
  let DRAGGING = false;   // pauses the 45s poll — a repaint mid-drag drops the card

  // ── how a row reads ────────────────────────────────────────────────────────
  const DAY = 86400000;
  const days = (iso) => (iso ? Math.floor((Date.now() - new Date(iso).getTime()) / DAY) : null);

  /** "in 2 days" / "tomorrow" / "not sending" / "—".
   *
   *  A date in the PAST means something specific and worth shouting about, and it isn't
   *  "the customer is overdue a nudge". The server computes when the cadence next
   *  MATURES; the worker ticks every 15 minutes, so for a healthy proposal this is always
   *  in the future. A past date therefore means the cadence matured and nothing sent it —
   *  automation is off globally, or the worker is down. That's a stalled-sender warning,
   *  so it says so rather than blaming the customer. */
  function dueLabel(p) {
    if (!p.next_followup_at) return { text: "—", cls: "soft", title: "Nothing scheduled" };
    const ms = new Date(p.next_followup_at).getTime() - Date.now();
    const d = Math.round(ms / DAY);
    if (ms < 0) {
      return { text: "not sending", cls: "due-over",
               title: "This was due " + TW.fmtBizDate(p.next_followup_at)
                    + " and nothing sent it — automatic follow-ups are switched off, "
                    + "or the sender has stopped." };
    }
    if (d === 0) return { text: "today", cls: "due-soon", title: "" };
    if (d === 1) return { text: "tomorrow", cls: "due-soon", title: "" };
    return { text: "in " + d + " days", cls: "", title: TW.fmtBizDate(p.next_followup_at) };
  }

  const fu = (p) => p.followup_state || {};

  /** The automation state, in words. Colour is reinforcement only. */
  function stateOf(p) {
    if (C.isLost(p)) {
      const why = C.lostReason(p);
      return { label: "Closed lost" + (why ? " · " + why : ""), cls: "st-lost", rank: 5 };
    }
    const st = String(p.proposal_status || "");
    if (st === "approved") return { label: "Approved", cls: "st-done", rank: 4 };
    const until = C.pausedUntil(p, TW.bizToday());
    if (until) return { label: "Paused to " + TW.fmtBizDay(until), cls: "st-paused", rank: 3 };
    if (!fu(p).enrolled) return { label: "Not automated", cls: "st-off", rank: 2 };
    if (!fu(p).enabled) return { label: "Automation off", cls: "st-off", rank: 2 };
    return { label: "Chasing", cls: "st-on", rank: 1 };
  }

  /** Which tab a row belongs to. "live" is the working list — anything still in play. */
  function bucket(p) {
    if (C.isLost(p)) return "lost";
    if (String(p.proposal_status || "") === "approved") return "won";
    if (C.pausedUntil(p, TW.bizToday())) return "paused";
    return "live";
  }

  const TABS = [["live", "In play"], ["paused", "Paused"], ["won", "Approved"],
                ["lost", "Closed lost"], ["all", "All"]];

  // ── filter + sort ──────────────────────────────────────────────────────────
  const matches = (p) => {
    const q = Q.trim().toLowerCase();
    if (!q) return true;
    const hay = [p.project_name, p.customer_name, p.customer_email,
                 C.estimatorOf(p), C.nameOf(C.estimatorOf(p))].filter(Boolean).join(" ").toLowerCase();
    return q.split(/\s+/).every((t) => hay.includes(t));
  };

  const KEYED = {
    score: (p) => p.followup_score || 0,
    value: (p) => (typeof p.approved_total === "number" ? p.approved_total : null),
    quiet: (p) => days(p.last_activity_at),
    name: (p) => (p.project_name || "").toLowerCase(),
    // Nulls are meaningful in these two, and they mean OPPOSITE things: no next reminder
    // is "nothing coming", never chased is "the worst case". So they sort differently.
    due: (p) => p.next_followup_at || null,
    chased: (p) => p.last_followup_at || null,
  };

  function sorted(rows) {
    const dir = DIR === "asc" ? 1 : -1;
    const get = KEYED[SORT] || KEYED.score;
    return rows.slice().sort((a, b) => {
      let x = get(a), y = get(b);
      // Never chased sorts as the most urgent thing on the page, not as a blank.
      if (SORT === "chased") { x = x || ""; y = y || ""; }
      if (x == null && y == null) return 0;
      if (x == null) return 1;                       // blanks last in BOTH directions
      if (y == null) return -1;
      if (typeof x === "number") return dir * (x - y);
      return dir * String(x).localeCompare(String(y));
    });
  }

  function visible() {
    // The board ignores TAB on purpose: its COLUMNS are those tabs. Honouring a "In play"
    // tab there would leave Paused, Approved and Closed lost permanently empty and make the
    // board look broken. Search and estimator still apply to both views, so a narrowed list
    // stays narrowed when you switch.
    const inTab = (VIEW === "board")
      ? ALL
      : ALL.filter((p) => TAB === "all" || bucket(p) === TAB);
    const byEst = EST ? inTab.filter((p) => C.estimatorOf(p).toLowerCase() === EST) : inTab;
    return sorted(byEst.filter(matches));
  }

  // ── render ─────────────────────────────────────────────────────────────────
  const COLS = [
    { label: "Project", sort: "name" },
    { label: "Customer", sort: null },
    { label: "Estimator", sort: null },
    { label: "Stage", sort: null },
    { label: "Status", sort: null },
    { label: "Last chased", sort: "chased" },
    { label: "Quiet for", sort: "quiet" },
    { label: "Next reminder", sort: "due" },
    { label: "Why it's here", sort: "score" },
    { label: "Value", sort: "value", num: true },
    { label: "", sort: null },
  ];

  function head() {
    return COLS.map((c) => {
      const cls = c.num ? "num" : "";
      if (!c.sort) return `<th class="${cls}">${esc(c.label)}</th>`;
      const on = SORT === c.sort;
      return `<th class="${cls} th-sort${on ? " is-sorted" : ""}" aria-sort="${
        on ? (DIR === "asc" ? "ascending" : "descending") : "none"}">` +
        `<button type="button" data-sortby="${c.sort}">${esc(c.label)}${
          on ? (DIR === "asc" ? " ↑" : " ↓") : ""}</button></th>`;
    }).join("");
  }

  function row(p) {
    const email = C.estimatorOf(p);
    const st = stateOf(p);
    const due = dueLabel(p);
    const chased = days(p.last_followup_at);
    const quiet = days(p.last_activity_at);
    return `<tr data-id="${esc(p.proposal_id)}" tabindex="0">
      <td class="t-name">${esc(p.project_name || "Proposal")}${
        p.unread ? ` <span class="st st-lost">${p.unread} unread</span>` : ""}</td>
      <td>${esc(p.customer_name || p.customer_email || "")}</td>
      <td${C.isAssigned(p) ? "" : ' class="soft"'} title="${esc(email)}${
        C.isAssigned(p) ? "" : " — nobody is assigned, this is whoever built the estimate"}">${
        email ? C.avatarHtml(email, !C.isAssigned(p)) + esc(C.nameOf(email)) + (C.isAssigned(p) ? "" : "?") : "—"}</td>
      <td>${esc(C.stage(p))}</td>
      <td><span class="st ${st.cls}">${esc(st.label)}</span></td>
      <td class="${chased == null ? "never" : ""}">${
        chased == null ? "never" : chased === 0 ? "today" : chased + "d ago"}</td>
      <td>${quiet == null ? "—" : quiet + "d"}</td>
      <td class="${due.cls}"${due.title ? ` title="${esc(due.title)}"` : ""}>${esc(due.text)}</td>
      <td class="t-why">${esc(p.reason || "")}</td>
      <td class="num">${money(p.approved_total)}</td>
      <td><div class="acts">
        ${B.column(p) === "approved" || B.column(p) === "lost" ? "" :
          `<button type="button" class="go-send" data-act="send"
            title="Email the customer and add it to their message thread">Send</button>`}
        <button type="button" data-act="log"
          title="Record a call, text or email you sent yourself. Does NOT email the customer.">Log a call</button>
        <button type="button" data-act="open" title="Open in the Customer Portal CRM">Open</button>
      </div></td>
    </tr>`;
  }

  // ── the board ───────────────────────────────────────────────────────────────
  // A second VIEW of the same rows, not a replacement: the board answers "where does
  // everything stand", the ranked list answers "what do I do next", and the list is better
  // at the second. Columns, drop rules and what a drag actually DOES all live in
  // followups-core.js (window.TWFu) so they can be tested without a browser.
  const B = window.TWFu;

  /** One card. Ours-to-move renders as a <button> (draggable, keyboard-reachable); a
   *  customer-owned one renders as a plain div, so there is no affordance on something a
   *  drag could not honestly change. */
  function cardHtml(p, today, nowMs) {
    const colId = B.column(p, today);
    const col = B.columnById(colId);
    // `mine` now means only one thing: this card sits in Closed lost, the single column we
    // decide. Everything else records what the customer did, so it is not draggable — but it
    // still gets ACTION BUTTONS, because Pause and Resume stopped being columns and the buttons
    // are now the only way to reach them.
    const mine = !!(col && col.ours);
    const acts = B.actionsFor(p, today);
    const canDrag = B.canMove(p, "lost", today);
    const neg = B.neglect(p, nowMs);
    const est = C.estimatorOf(p);
    const due = dueLabel(p);
    const quiet = days(p.last_activity_at);
    const chased = days(p.last_followup_at);
    const val = typeof p.approved_total === "number" ? money(p.approved_total) : "";
    // A DIV with role=button, NOT a <button>. `button` only permits PHRASING content, and
    // this card contains <p> and <div> — so the parser closed the button early, which closed
    // the enclosing .fu-board with it and dumped Paused/Approved/Closed-lost outside the grid
    // as full-width rows. Found by measuring the rendered DOM on staging; the source-text
    // tests could not see it because the strings were all correct.
    return `<div class="fu-card ${neg}${mine ? "" : " theirs"}"${
        canDrag ? ' role="button" tabindex="0" draggable="true"' : ""} data-id="${esc(p.proposal_id)}"${
        canDrag ? ' aria-label="' + esc(p.project_name || "Proposal") + ' — drag to Closed lost, or use the buttons"' : ""}>
      <p class="fu-name">${esc(p.project_name || "(untitled)")}</p>
      <p class="fu-cust">${esc(p.customer_name || p.customer_email || "")}</p>
      <div class="fu-meta">${est ? C.avatarHtml(est) + esc(C.nameOf(est).split(/\s+/)[0])
                                 : '<span class="tw-av av-none" title="No estimator">?</span>Unassigned'}
        ${autoBadge(p, today)}
        ${Number(p.unread) > 0 ? `<span class="fu-unread">${Number(p.unread)} unread</span>`
                               : (val ? `<span class="amt">${val}</span>` : "")}</div>
      <p class="fu-quiet">${chased === null ? "<b>never chased</b>"
          : "chased " + chased + "d ago"}${quiet !== null ? " · quiet " + quiet + "d" : ""}${
          due.text !== "—" ? " · next " + esc(due.text) : ""}</p>
      ${seenLine(p, colId)}
      ${p.reason ? `<p class="fu-why">${esc(p.reason)}</p>` : ""}
      <div class="fu-acts">${sendButton(p, colId)}${actionButtons(p, acts)}
        <button type="button" data-act="log" data-id="${esc(p.proposal_id)}"
          title="Record a call, text or email you sent yourself. Does NOT email the customer.">Log a call</button></div>
    </div>`;
  }

  /** The reason you came to this page: chase somebody.
   *
   *  Hidden once a proposal is approved or closed lost — there is nothing to chase, and offering
   *  it would invite emailing a customer about a decision they have already made. */
  function sendButton(p, colId) {
    if (colId === "approved" || colId === "lost") return "";
    return `<button type="button" class="go-send" data-act="send" data-id="${esc(p.proposal_id)}"
      title="Email the customer and add it to their message thread">Send follow-up</button>`;
  }

  /** What WE are doing about it — chasing, paused, or automation off.
   *
   *  This used to be a column, which is what made the old board ambiguous: a proposal could be
   *  "not opened" AND "paused three months" at once, so the code had to rank two independent
   *  facts and the table and the board could disagree. It is an attribute of a proposal, not a
   *  place a proposal lives, so it belongs on the card. */
  function autoBadge(p, today) {
    const a = B.automation(p, today);
    if (!a) return "";                                  // approved / lost — nothing is going out
    const label = a === "chasing" ? "Chasing" : a === "paused" ? "Paused" : "Not automated";
    const until = a === "paused" ? B.pausedUntil(p, today) : "";
    const title = a === "chasing" ? "Automatic reminders are going out."
      : a === "paused" ? ("Reminders held until " + until + ".")
      : "No automatic reminders. Chase it by hand, or press Resume.";
    return `<span class="fu-auto is-${a}" title="${esc(title)}">${esc(label)}</span>`;
  }

  /** How the customer saw it, and when.
   *
   *  Only on the Seen column, where it is the whole question. A portal view means a person
   *  definitely looked; an email link click is weaker — that page serves before anyone signs in
   *  and mail scanners follow links — so the wording never says "seen by" and the tooltip says
   *  so outright. On a card in "Not opened" it would be a contradiction, and past Seen the
   *  question is already answered. */
  function seenLine(p, colId) {
    if (colId !== "seen") return "";
    const how = B.seenHow(p);
    if (!how) return "";
    if (how === "portal") {
      const d = days(p.last_viewed_at || p.viewed_at);
      const when = d === null ? "" : (d === 0 ? " today" : " " + d + "d ago");
      return `<p class="fu-seen is-portal" title="They opened the proposal in the portal.">` +
             `opened the portal${esc(when)}</p>`;
    }
    const d = days(p.last_link_clicked_at || p.link_clicked_at);
    const when = d === null ? "" : (d === 0 ? " today" : " " + d + "d ago");
    return `<p class="fu-seen is-email" title="Somebody followed the link in the notification` +
           ` email, so the email is getting through. It is not proof the proposal was read —` +
           ` that page loads before anyone signs in, and mail scanners follow links too.">` +
           `email link opened${esc(when)}</p>`;
  }

  /** The actions available on this card.
   *
   *  Keyboard/click parity for the drag, and the ONLY route to Pause and Resume now that they
   *  are not columns. A drag-only control would be the first unreachable thing on this page. */
  function actionButtons(p, acts) {
    return (acts || []).map((a) => `<button type="button" data-do="${a.id}"
        data-id="${esc(p.proposal_id)}" title="${esc(a.label)}">${esc(a.label)}</button>`).join("");
  }

  function paintBoard() {
    const rows = visible();
    const today = TW.bizToday();
    const nowMs = Date.now();
    const cols = B.group(rows, today);
    const el = $("list");
    el.className = "boardwrap";
    el.innerHTML = `<div class="fu-board">` + B.COLUMNS.map((c) => {
      const items = cols[c.id] || [];
      const load = B.load(items);
      return `<div class="fu-col${c.ours ? "" : " theirs"}" data-col="${c.id}"${
          c.ours ? ' data-drop="1"' : ""}>
        <div class="fu-chead"><span class="fu-dot" style="background:${c.dot}"></span>
          <b>${esc(c.label)}</b><span class="n">${load.count}</span>${
          load.value ? `<span class="v">${money(load.value)}</span>` : ""}</div>
        <p class="fu-csub">${c.ours ? '<span class="fu-lock">You set this</span> ' : ""}${
          esc(c.sub)}</p>
        ${items.map((p) => cardHtml(p, today, nowMs)).join("")}
      </div>`;
    }).join("") + `</div>
      <div class="fu-legend">
        <span><i style="background:#b3261e"></i>Nobody has chased this</span>
        <span><i style="background:#9a5b00"></i>Going quiet</span>
        <span><i style="background:#4a6b8a"></i>On cadence</span>
        <span><span class="fu-lock">You set this</span> the only column you can drag into</span>
        <span>Column header shows count · total value</span>
      </div>`;
  }

  /** Toolbar, tab strip and count — shared by both views.
   *
   *  The tab strip is hidden on the board because the COLUMNS are those tabs: showing both
   *  invites "In play" + a Paused column, which contradict each other. Search, estimator
   *  and sort still apply to both, so a filtered list stays filtered when you switch. */
  function paintChrome() {
    const rows = visible();
    const counts = {};
    TABS.forEach(([k]) => { counts[k] = k === "all" ? ALL.length : ALL.filter((p) => bucket(p) === k).length; });
    const f = $("filters");
    f.hidden = !ALL.length || VIEW === "board";
    if (!f.hidden) {
      f.innerHTML = TABS.map(([k, label]) =>
        `<button type="button" class="chip ${k === TAB ? "sel" : ""}" data-tab="${k}">${
          esc(label)}<span class="n">${counts[k]}</span></button>`).join("");
    }
    $("toolbar").hidden = !ALL.length;
    // Sorting a board makes no sense — the columns are the order, and within a column the
    // feed's own digest ranking is what you want.
    $("sort").hidden = VIEW === "board";
    $("dir").hidden = VIEW === "board";
    populateEstimators();
    syncToolbar();
    $("count").textContent = ALL.length ? rows.length + " of " + ALL.length : "";
    ["list", "board"].forEach((v) => {
      const b = $("v-" + v);
      if (b) b.setAttribute("aria-pressed", String(VIEW === v));
    });
    return rows;
  }

  // What the page currently shows. Both painters below replace their container's whole
  // innerHTML, so repainting unchanged data rebuilds every column and card for nothing — which
  // the eye sees as the board blinking. This one polls every 45s, so it did that all day.
  //
  // Same guard as the Bid Pipeline (crm.js), the Lead Inbox (leads.js), the Bid Calendar
  // (calendar.js) and the Customer Portal CRM (portal.js). Every piece of view state is in the
  // signature so switching tab, filtering, sorting, searching or changing view still repaints.
  let LAST_SIG = "";

  function paint() {
    const sig = JSON.stringify([ALL, TAB, EST, SORT, DIR, Q, VIEW]);
    if (sig === LAST_SIG) return;
    LAST_SIG = sig;

    const rows = paintChrome();
    if (VIEW === "board") return paintBoard();

    const el = $("list");
    if (!rows.length) {
      el.className = "empty";
      el.textContent = !ALL.length
        ? "No proposals have been sent to a customer yet."
        : "Nothing in this view.";
      return;
    }
    el.className = "tablewrap";
    el.innerHTML = `<table><thead><tr>${head()}</tr></thead><tbody>${rows.map(row).join("")}</tbody></table>`;
  }

  function populateEstimators() {
    const sel = $("est");
    if (!sel) return;
    const counts = {};
    ALL.forEach((p) => {
      const e = C.estimatorOf(p).toLowerCase();
      if (e) counts[e] = (counts[e] || 0) + 1;
    });
    if (EST && !counts[EST]) { EST = ""; ssSet(K.est, ""); }     // stale pick → don't blank the page
    const emails = Object.keys(counts).sort((a, b) => C.nameOf(a).localeCompare(C.nameOf(b)));
    sel.innerHTML = '<option value="">Any estimator</option>'
      + emails.map((e) => `<option value="${esc(e)}">${esc(C.nameOf(e))} (${counts[e]})</option>`).join("");
    sel.value = EST;
  }

  function syncToolbar() {
    const s = $("sort"), d = $("dir"), q = $("q");
    if (s) s.value = SORT;
    if (q && q.value !== Q) q.value = Q;
    if (d) {
      d.textContent = DIR === "asc" ? "↑ Asc" : "↓ Desc";
      d.setAttribute("aria-pressed", DIR === "asc" ? "true" : "false");
    }
  }

  // ── logging a follow-up, without leaving the page ───────────────────────────
  // The whole point of this screen is working down a list, so making somebody open the
  // CRM drawer to record a call would put the friction back where it was.
  function logDialog(p) {
    return new Promise((resolve) => {
      const ov = document.createElement("div");
      ov.className = "ov";
      ov.innerHTML = `<div class="dlg" role="dialog" aria-modal="true" aria-label="Log a follow-up">
        <div class="dlg-h">Log a follow-up</div>
        <p class="dlg-sub">${esc(p.project_name || "This proposal")} — takes it off tomorrow
          morning's digest. The customer is not emailed.</p>
        <label for="fk">What you did</label>
        <select id="fk" data-kind>
          <option value="call">Call</option><option value="email">Email</option>
          <option value="text">Text</option><option value="note">Note</option>
        </select>
        <label for="fn">Note (optional)</label>
        <input id="fn" type="text" data-note maxlength="2000"
               placeholder="Left a voicemail with Dave — will try Thursday" />
        <div class="dlg-act">
          <button type="button" class="chip" data-x>Cancel</button>
          <button type="button" class="go" data-go>Log it</button>
        </div></div>`;
      document.body.appendChild(ov);
      const close = (v) => { ov.remove(); document.removeEventListener("keydown", onKey); resolve(v); };
      const onKey = (e) => {
        if (e.key === "Escape") close(null);
        if (e.key === "Enter") ov.querySelector("[data-go]").click();
      };
      document.addEventListener("keydown", onKey);
      ov.querySelector("[data-x]").addEventListener("click", () => close(null));
      ov.addEventListener("mousedown", (e) => { if (e.target === ov) close(null); });
      ov.querySelector("[data-go]").addEventListener("click", () => close({
        kind: ov.querySelector("[data-kind]").value,
        note: ov.querySelector("[data-note]").value.trim(),
      }));
      ov.querySelector("[data-note]").focus();
    });
  }

  /** Compose a follow-up to the customer.
   *
   *  Deliberately a plain message box and nothing more. A template picker would be the obvious
   *  next thing, and the wrong one to add first: the automated cadence already sends the
   *  templated nudges, so what an estimator needs from here is the sentence a template cannot
   *  write — "Dave, we can still hit your March start if we hear back this week".
   *
   *  Says exactly who it reaches, because this one DOES email the customer and Log does not, and
   *  those two buttons sit next to each other. */
  function sendDialog(p) {
    const who = esc(p.customer_name || p.customer_email || "the customer");
    return new Promise((resolve) => {
      const ov = document.createElement("div");
      ov.className = "ov";
      ov.innerHTML = `<div class="dlg" role="dialog" aria-modal="true" aria-label="Send a follow-up">
        <div class="dlg-h">Send a follow-up</div>
        <p class="dlg-sub">${esc(p.project_name || "This proposal")} — emails ${who} and adds it
          to their message thread. They can reply straight to it.</p>
        <label for="sm">Message</label>
        <textarea id="sm" data-msg rows="5" maxlength="4000"
          placeholder="Hi ${who} — just checking whether you had any questions on the proposal. Happy to walk through it whenever suits."></textarea>
        <div class="dlg-act">
          <button type="button" class="chip" data-x>Cancel</button>
          <button type="button" class="go" data-go>Send email</button>
        </div></div>`;
      document.body.appendChild(ov);
      const close = (v) => { ov.remove(); document.removeEventListener("keydown", onKey); resolve(v); };
      const onKey = (e) => {
        // No Enter-to-send: this one leaves the building. Enter inside a textarea should make a
        // new line, and a stray keystroke must not email a customer a half-written sentence.
        if (e.key === "Escape") close(null);
      };
      document.addEventListener("keydown", onKey);
      ov.querySelector("[data-x]").addEventListener("click", () => close(null));
      ov.addEventListener("mousedown", (e) => { if (e.target === ov) close(null); });
      ov.querySelector("[data-go]").addEventListener("click", () => {
        const body = ov.querySelector("[data-msg]").value.trim();
        if (!body) { ov.querySelector("[data-msg]").focus(); return; }   // never send an empty one
        close({ body: body });
      });
      ov.querySelector("[data-msg]").focus();
    });
  }

  /** Ask for the extra input a cadence change needs. `needs` comes from the core's plan, so
   *  the dialog and the API call can't drift apart. */
  function askFor(needs, p) {
    if (!needs) return Promise.resolve({});
    const monthsUi = `<label for="mm">Wait how long?</label>
        <select id="mm" data-months>
          <option value="1">1 month</option><option value="2">2 months</option>
          <option value="3" selected>3 months</option><option value="4">4 months</option>
        </select>
        <p class="dlg-sub">Reminders stop until then, and this drops off the morning digest.
          The customer is not emailed.</p>`;
    // Kyle's list, from the drawer — same six the portal accepts, so a reason can't 400.
    const reasonUi = `<label for="rr">Why did we lose it?</label>
        <select id="rr" data-reason>
          <option value="price">Price</option>
          <option value="another_contractor">Another contractor</option>
          <option value="canceled">Project canceled</option>
          <option value="scope_changed">Scope changed</option>
          <option value="timing">Timing</option>
          <option value="other">Other</option>
        </select>
        <p class="dlg-sub">Stops the reminders for good. You can reopen it later from the
          project drawer.</p>`;
    return new Promise((resolve) => {
      const ov = document.createElement("div");
      ov.className = "ov";
      ov.innerHTML = `<div class="dlg" role="dialog" aria-modal="true" aria-label="Change follow-ups">
        <div class="dlg-h">${needs === "months" ? "Pause reminders" : "Close this out"}</div>
        <p class="dlg-sub">${esc(p.project_name || "This proposal")}</p>
        ${needs === "months" ? monthsUi : reasonUi}
        <div class="dlg-act">
          <button type="button" class="chip" data-x>Cancel</button>
          <button type="button" class="go" data-go>${
            needs === "months" ? "Pause" : "Close lost"}</button>
        </div></div>`;
      document.body.appendChild(ov);
      const close = (v) => { ov.remove(); document.removeEventListener("keydown", onKey); resolve(v); };
      const onKey = (e) => {
        if (e.key === "Escape") close(null);
        if (e.key === "Enter") ov.querySelector("[data-go]").click();
      };
      document.addEventListener("keydown", onKey);
      ov.querySelector("[data-x]").addEventListener("click", () => close(null));
      ov.addEventListener("mousedown", (e) => { if (e.target === ov) close(null); });
      ov.querySelector("[data-go]").addEventListener("click", () => close(
        needs === "months" ? { months: Number(ov.querySelector("[data-months]").value) }
                           : { reason: ov.querySelector("[data-reason]").value }));
    });
  }

  /** Move a proposal into one of OUR columns, changing the cadence for real.
   *
   *  The plan (which endpoint, what payload, whether a second write is needed) comes from
   *  followups-core so it is tested; this function only performs it. */
  async function moveTo(id, action) {
    const p = ALL.find((x) => x.proposal_id === id);
    if (!p) return;
    const plan = B.actionPlan(p, action, TW.bizToday());
    if (!plan) return;                       // refused — not ours to change, or already there
    const extra = await askFor(plan.needs, p);
    if (extra === null) return;
    $("alert").textContent = "";
    const post = (path, body) => api("/api/portal/proposal/" + encodeURIComponent(id) + path,
      { method: "POST", body: JSON.stringify(body) });
    try {
      const r = await post("/status", Object.assign({ status: plan.status }, extra));
      const j = await r.json().catch(() => ({}));
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      // Resuming is TWO writes when automation was also switched off: the portal's
      // resume_followups() clears the pause but not followup_disabled_at, so without this
      // the card would land in Chasing with nothing actually sending.
      for (const step of (plan.then || [])) {
        if (step === "enable_automation") {
          const r2 = await post("/followup-automation", { enabled: true });
          if (!r2.ok) throw new Error("Reminders resumed but automation stayed off — "
                                    + "open the project and switch it on.");
        }
      }
      await load();
    } catch (err) {
      $("alert").textContent = "Couldn't change that: " + (err.message || "try again");
    }
  }

  /** Email the customer, and log it as outreach in one go.
   *
   *  Reuses the same endpoint the Customer Portal CRM chat uses, so a follow-up sent from here
   *  lands in the same thread the customer already replies into — rather than becoming a second,
   *  invisible channel. The `staff_email` log is what takes it off tomorrow's digest; without it
   *  the estimator would send a chase and still be told to chase.
   */
  async function sendFollowup(id) {
    const p = ALL.find((x) => x.proposal_id === id);
    if (!p) return;
    const out = await sendDialog(p);
    if (!out) return;
    $("alert").textContent = "";
    const post = (path, body) => api("/api/portal/proposal/" + encodeURIComponent(id) + path,
      { method: "POST", body: JSON.stringify(body) });
    try {
      const r = await post("/reply", { body: out.body });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      // The email is away. A failure to LOG it must not read as a failure to send — the customer
      // already has it — so this is reported separately and does not undo anything.
      try {
        await post("/followups", { kind: "email", note: out.body.slice(0, 300) });
      } catch (logErr) {
        $("alert").textContent = "Sent, but couldn't log it — it may still show as needing a chase.";
      }
      await load();
    } catch (err) {
      $("alert").textContent = "Couldn't send that: " + (err.message || "try again");
    }
  }

  async function logFollowup(id) {
    const p = ALL.find((x) => x.proposal_id === id);
    if (!p) return;
    const out = await logDialog(p);
    if (!out) return;
    $("alert").textContent = "";
    try {
      const r = await api("/api/portal/proposal/" + encodeURIComponent(id) + "/followups",
                          { method: "POST", body: JSON.stringify(out) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      await load();          // re-read, so the row's score and reason reflect the log
    } catch (err) {
      $("alert").textContent = "Couldn't log that: " + (err.message || "try again");
    }
  }

  // One delegated listener. The table is replaced wholesale on every paint and on the
  // poll, so per-row handlers would be re-bound continuously and leak.
  $("list").addEventListener("click", (e) => {
    const th = e.target.closest("[data-sortby]");
    if (th) {
      const f = th.dataset.sortby;
      DIR = SORT === f ? (DIR === "asc" ? "desc" : "asc") : (NATURAL[f] || "desc");
      SORT = f;
      ssSet(K.sort, SORT); ssSet(K.dir, DIR);
      paint();
      return;
    }
    // Board: the per-card "→ Paused / → Chasing / → Closed lost" buttons. These are the
    // KEYBOARD path for the drag — a drag-only control would be the only thing on this page
    // you couldn't reach without a mouse.
    const mv = e.target.closest("[data-do]");
    if (mv) { e.stopPropagation(); moveTo(mv.dataset.id, mv.dataset.do); return; }

    const holder = e.target.closest("tr[data-id], .fu-card[data-id]");
    if (!holder) return;
    const id = holder.dataset.id;
    if (e.target.closest('[data-act="send"]')) { e.stopPropagation(); sendFollowup(id); return; }
    if (e.target.closest('[data-act="log"]')) { e.stopPropagation(); logFollowup(id); return; }
    // Anything else on the row opens the full drawer, where the automation toggle,
    // the history and the chat live. This page is the list; that is the detail.
    window.location.assign("/portal.html?open=" + encodeURIComponent(id) + "&sec=followup");
  });

  // A div[role=button] does not fire on Enter/Space the way a real button does, and the card
  // has to stay a div (see cardHtml — `button` cannot legally contain <p>/<div>). So wire the
  // keyboard explicitly, or the board's cards become mouse-only.
  $("list").addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const card = e.target.closest('.fu-card[role="button"]');
    if (!card || e.target.closest("button")) return;   // let the inner buttons speak for themselves
    e.preventDefault();
    card.click();
  });

  // ── drag and drop ───────────────────────────────────────────────────────────
  // Delegated on the container, because the board is replaced wholesale on every paint and
  // on the 45s poll — per-card handlers would be rebound continuously and leak.
  let DRAG_ID = null;

  $("list").addEventListener("dragstart", (e) => {
    const card = e.target.closest(".fu-card[data-id]");
    if (!card || card.classList.contains("theirs")) return;
    DRAG_ID = card.dataset.id;
    DRAGGING = true;
    card.classList.add("dragging");
    try { e.dataTransfer.setData("text/plain", DRAG_ID); e.dataTransfer.effectAllowed = "move"; } catch {}
  });

  $("list").addEventListener("dragend", () => {
    DRAGGING = false;
    DRAG_ID = null;
    document.querySelectorAll(".fu-card.dragging").forEach((c) => c.classList.remove("dragging"));
    document.querySelectorAll(".fu-col.over").forEach((c) => c.classList.remove("over"));
  });

  $("list").addEventListener("dragover", (e) => {
    const col = e.target.closest(".fu-col[data-drop]");
    if (!col || !DRAG_ID) return;
    const p = ALL.find((x) => x.proposal_id === DRAG_ID);
    // Ask the core, not the DOM: a customer-owned column has no data-drop at all, and an
    // approved card can't be closed-lost, so neither should light up as droppable.
    if (!p || !B.canMove(p, col.dataset.col, TW.bizToday())) return;   // only Closed lost
    e.preventDefault();                       // preventDefault IS what permits the drop
    try { e.dataTransfer.dropEffect = "move"; } catch {}
    document.querySelectorAll(".fu-col.over").forEach((c) => c.classList.remove("over"));
    col.classList.add("over");
  });

  $("list").addEventListener("drop", (e) => {
    const col = e.target.closest(".fu-col[data-drop]");
    if (!col || !DRAG_ID) return;
    e.preventDefault();
    const id = DRAG_ID;
    DRAGGING = false;
    DRAG_ID = null;
    col.classList.remove("over");
    // The column id doubles as the action id, and only for "lost" — the sole column that is
    // ours to set. That overlap is deliberate (see actionPlan) and pinned by the core tests:
    // canMove has already refused every other column, so nothing else can arrive here.
    moveTo(id, col.dataset.col);
  });

  // ── List | Board ────────────────────────────────────────────────────────────
  ["list", "board"].forEach((v) => {
    const b = $("v-" + v);
    if (b) b.addEventListener("click", () => {
      if (VIEW === v) return;
      VIEW = v;
      ssSet(K.view, v === "board" ? "board" : "");
      $("hint").textContent = v === "board"
        ? "Every proposal that has been sent, grouped by where its chase stands. Drag a card to"
          + " pause the reminders or close it out — the first three columns are the customer's"
          + " to move."
        : "Every proposal that has been sent to a customer, and where its chase stands."
          + " Logging a call here takes it off tomorrow morning's digest.";
      paint();
    });
  });
  $("list").addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const tr = e.target.closest && e.target.closest("tr[data-id]");
    if (!tr) return;
    e.preventDefault();
    window.location.assign("/portal.html?open=" + encodeURIComponent(tr.dataset.id) + "&sec=followup");
  });

  $("filters").addEventListener("click", (e) => {
    const b = e.target.closest("[data-tab]");
    if (!b) return;
    TAB = b.dataset.tab; ssSet(K.tab, TAB); paint();
  });

  (function wireToolbar() {
    let t;
    $("q").addEventListener("input", (e) => {
      clearTimeout(t);
      t = setTimeout(() => { Q = e.target.value; ssSet(K.q, Q); paint(); }, 180);
    });
    $("q").addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.target.value = ""; Q = ""; ssSet(K.q, ""); paint(); }
    });
    $("est").addEventListener("change", (e) => { EST = e.target.value; ssSet(K.est, EST); paint(); });
    $("sort").addEventListener("change", (e) => {
      SORT = e.target.value; DIR = NATURAL[SORT] || "desc";
      ssSet(K.sort, SORT); ssSet(K.dir, DIR); paint();
    });
    $("dir").addEventListener("click", () => {
      DIR = DIR === "asc" ? "desc" : "asc"; ssSet(K.dir, DIR); paint();
    });
  })();

  async function load() {
    try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch {}
    for (let i = 0; i < 200 && !window.__TW_TOKEN; i++) await new Promise((r) => setTimeout(r, 40));
    try {
      const r = await api("/api/portal/followups");
      const j = await r.json();
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      ALL = j.proposals || [];
      paint();
    } catch (err) {
      // Only when there is nothing to keep. This runs on a 45s timer, so one blip would
      // otherwise throw away a board somebody was working from and replace it with an error.
      if (!ALL.length) {
        $("list").className = "empty";
        $("list").textContent = "Couldn't load follow-ups: " + (err.message || "") +
          ". Check that the customer portal is reachable.";
        // The error is not what the signature describes: without this, a recovery carrying
        // identical data is skipped as unchanged and the message stays up for good.
        LAST_SIG = "";
      }
    }
  }

  load();
  // Somebody else logging a call should show up here without an F5 — filters and sort
  // survive a repaint (they live in module state and sessionStorage).
  const busy = () => {
    if (DRAGGING) return true;      // a repaint mid-drag pulls the card out from under you
    if (document.querySelector(".ov")) return true;                 // a dialog is open
    const a = document.activeElement;
    return !!a && ["INPUT", "SELECT", "TEXTAREA"].includes(a.tagName);
  };
  setInterval(() => { if (!document.hidden && !busy()) load(); }, 45000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !busy()) load(); });
})();
