// Customer Portal admin page — proxies to the portal's admin API via the
// proposal-tool backend (/api/portal/*). Externalized (no inline scripts; CSP).
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const nameOf = (email) => String(email || "").split("@")[0].split(/[._-]+/)
    .filter(Boolean).map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ") || String(email || "");
  const money = (n) => (n == null ? "" : "$" + Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  // Central, not viewer-local: "submitted 7/27 10:04 PM" must mean the same day to
  // Kyle in Kansas and to anyone testing from another timezone. Falls back to the
  // old local rendering only if shared.js somehow hasn't loaded.
  const when = (s) => (s
    ? ((window.TW && TW.fmtBizDateTime) ? TW.fmtBizDateTime(s) : new Date(s).toLocaleString())
    : "");
  // The customer has sent money but nobody has confirmed it landed — its own
  // column, so a paid deal never sits in "Approved" looking like an unpaid one.
  const STAGE_SUBMITTED = "Deposit submitted";
  const STAGES = ["Sent", "Viewed", "Approved", STAGE_SUBMITTED, "Deposit received", "Contact info", "Scheduled"];
  const ROLE_LABEL = { primary: "Primary", accounts_payable: "Accounts payable", other: "Other" };
  let ALL = [];

  // ── what a card says about time ────────────────────────────────────────────
  // The newest milestone that actually happened. `sent_at` is never null (a
  // proposal row can't exist before the email goes out), so every card dates.
  // Note "Viewed" is the FIRST view — the portal coalesces viewed_at and never
  // moves it, so a customer re-reading the proposal doesn't refresh this.
  const MILESTONES = [
    ["sent_at", "Sent"],
    ["viewed_at", "Viewed"],
    ["approved_at", "Approved"],
    ["deposit_requested_at", "Invoiced"],
  ];
  function lastActivity(p) {
    let best = null;
    for (const [key, label] of MILESTONES) {
      const ts = p[key];
      if (ts && (!best || String(ts) > String(best.ts))) best = { ts: ts, label: label };
    }
    return best;
  }
  const activityTs = (p) => { const a = lastActivity(p); return a ? a.ts : ""; };

  // ── filter / sort state ────────────────────────────────────────────────────
  // Module-level and mirrored to sessionStorage: renderBoard re-runs after every
  // staff action (act() calls load()), and the controls live in static HTML, so
  // a scan survives both a re-render and a return visit.
  const EST_KEY = "tw_crm_est", MONTH_KEY = "tw_crm_month";
  const SORTFIELD_KEY = "tw_crm_sortfield", SORTDIR_KEY = "tw_crm_sortdir";
  const ss = (k, d) => { try { const v = sessionStorage.getItem(k); return v == null ? d : v; } catch { return d; } };
  const ssSet = (k, v) => { try { v ? sessionStorage.setItem(k, v) : sessionStorage.removeItem(k); } catch {} };
  const SORT_FIELDS = ["activity", "estimator", "total"];
  // Each field opens the way you'd want to read it first.
  const NATURAL_DIR = { activity: "desc", estimator: "asc", total: "desc" };
  let EST = ss(EST_KEY, "");
  let MONTH = ss(MONTH_KEY, "");
  let SORTFIELD = SORT_FIELDS.includes(ss(SORTFIELD_KEY, "")) ? ss(SORTFIELD_KEY, "") : "activity";
  let SORTDIR = ss(SORTDIR_KEY, "") === "asc" ? "asc" : (ss(SORTDIR_KEY, "") === "desc" ? "desc" : NATURAL_DIR[SORTFIELD]);

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

  function stageOf(p) {
    if (p.schedule_status === "scheduled") return "Scheduled";
    // Deposit is a prerequisite for advancing past it: a customer may submit
    // contacts right after approval (portal allows it), but an unpaid deal must
    // NOT read as further along than a paid one, so gate "Contact info" on deposit.
    if (p.deposit_status === "received" && p.contacts_status === "received") return "Contact info";
    if (p.deposit_status === "received") return "Deposit received";
    // Checked AFTER "received" so a confirmed deposit can never fall back into
    // the submitted column if the portal ever sends both signals.
    if (p.deposit_status === "submitted") return STAGE_SUBMITTED;
    if (p.proposal_status === "approved") return "Approved";
    if (p.proposal_status === "viewed") return "Viewed";
    return "Sent";
  }

  // Pure, composed in renderBoard. Search is read live from the DOM (the input
  // is static markup, so it survives every re-render) — the rest read state.
  const applySearch = (list) => {
    const q = ($("search").value || "").toLowerCase().trim();
    if (!q) return list;
    const tokens = q.split(/\s+/);
    return list.filter((p) => {
      const hay = [p.project_name, p.customer_email, p.customer_name, p.estimator_email]
        .filter(Boolean).join(" ").toLowerCase();
      return tokens.every((t) => hay.includes(t));
    });
  };
  const applyEstimator = (list) => (EST
    ? list.filter((p) => String(p.estimator_email || "").toLowerCase() === EST)
    : list);
  const applyMonth = (list) => (MONTH
    ? list.filter((p) => TW.bizYM(activityTs(p)) === MONTH)   // the month the card shows
    : list);

  function applySort(list) {
    const a = list.slice();
    const dir = SORTDIR === "asc" ? 1 : -1;
    // The dir multiplier never touches the null branches, so blanks stay last in
    // BOTH directions — flipping the sort must not surface empty cards first.
    if (SORTFIELD === "estimator") a.sort((x, y) => {
      const nx = nameOf(x.estimator_email || "").toLowerCase();
      const ny = nameOf(y.estimator_email || "").toLowerCase();
      if (!nx && !ny) return 0; if (!nx) return 1; if (!ny) return -1;
      return dir * nx.localeCompare(ny);
    });
    else if (SORTFIELD === "total") a.sort((x, y) => {
      const tx = typeof x.approved_total === "number" ? x.approved_total : null;
      const ty = typeof y.approved_total === "number" ? y.approved_total : null;
      if (tx == null && ty == null) return 0; if (tx == null) return 1; if (ty == null) return -1;
      return dir * (tx - ty);
    });
    else a.sort((x, y) => {                                   // activity (default)
      const tx = activityTs(x), ty = activityTs(y);
      if (!tx && !ty) return 0; if (!tx) return 1; if (!ty) return -1;
      return dir * String(tx).localeCompare(String(ty));
    });
    return a;
  }

  function renderBoard() {
    const items = applySort(applyMonth(applySearch(applyEstimator(ALL))));
    populateEstimators();
    populateMonths();
    $("count").textContent = items.length === ALL.length
      ? ALL.length + " proposal" + (ALL.length === 1 ? "" : "s")
      : items.length + " of " + ALL.length;
    const clear = $("crm-clear");
    if (clear) clear.hidden = !(EST || MONTH || SORTFIELD !== "activity" || SORTDIR !== "desc");
    const byStage = {};
    STAGES.forEach((s) => (byStage[s] = []));
    items.forEach((p) => byStage[stageOf(p)].push(p));
    $("board").innerHTML = STAGES.map((s) => {
      const cards = byStage[s].map((p) => {
        const act = lastActivity(p);
        // Who owns it and when it last moved, on one line — the column is only
        // 224px of usable width, so this is the whole budget for both facts.
        // Labelled, on its own line each: a bare "Hanz · Invoiced 7/27" reads as
        // one fact, and it isn't obvious which name that is on a board where the
        // line above is already an email.
        const who = p.estimator_email ? esc(nameOf(p.estimator_email)) : "—";
        const lines = '<div class="meta who"><span class="k">Estimator:</span> ' + who + "</div>"
          + (act ? '<div class="meta act"><span class="k">' + esc(act.label)
                 + ':</span> ' + esc(TW.fmtBizDate(act.ts)) + "</div>" : "");
        return `
        <div class="deal" data-id="${esc(p.proposal_id)}">
          ${p.unread ? `<span class="unread" title="${p.unread} customer message${p.unread === 1 ? "" : "s"} awaiting a reply">${p.unread}</span>` : ""}
          <div class="name">${esc(p.project_name || "Proposal")}</div>
          <div class="meta">${esc(p.customer_email || "")}</div>
          ${lines}
          ${p.approved_total != null ? `<div class="val">${money(p.approved_total)}</div>` : ""}
        </div>`;
      }).join("") || '<div class="empty">—</div>';
      // Money is in and unconfirmed → flag the column, it's the one needing a human.
      const attn = s === STAGE_SUBMITTED && byStage[s].length ? " col-attn" : "";
      return `<div class="col${attn}"><h2>${s}<span>${byStage[s].length}</span></h2>${cards}</div>`;
    }).join("");
    $("board").querySelectorAll(".deal").forEach((el) =>
      el.addEventListener("click", () => openDetail(el.dataset.id)));
  }

  /** Options come from the data, so the list can't offer an estimator with no
   *  cards. A stale selection is dropped rather than leaving the board blank. */
  function populateEstimators() {
    const sel = $("crm-est");
    if (!sel) return;
    const counts = {};
    ALL.forEach((p) => {
      const e = String(p.estimator_email || "").toLowerCase();
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
    ALL.forEach((p) => {
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
      $("board").innerHTML = '<div class="empty">Could not load the portal pipeline: ' + esc(err.message) +
        '. Check that the portal is configured (PORTAL_ADMIN_URL / SERVICE_TOKEN).</div>';
    }
    // Deep-link from a staff notification email: ?open=<proposal_id>.
    const openId = new URLSearchParams(location.search).get("open");
    if (openId) openDetail(openId);
  }

  // ── modal pop-up (detail drawer) ────────────────────────────────────────────
  function syncScrim() {
    $("scrim").style.display = $("drawer").classList.contains("open") ? "block" : "none";
  }
  function closeDrawer() {
    $("drawer").classList.remove("open"); syncScrim();
    // Clear the tab so the NEXT open routes by what needs attention again.
    CUR_PID = null; ACTIVE_SEC = null;
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
    d.innerHTML = '<div class="dbody"><p class="note">Loading…</p></div>';
    let data;
    try {
      const r = await api("/api/portal/proposal/" + encodeURIComponent(pid));
      data = await r.json();
      if (!r.ok || data.ok === false) throw new Error(data.error || data.detail || ("HTTP " + r.status));
    } catch (err) {
      d.innerHTML = '<div class="dhead"><h2>Error</h2><button class="dclose">&times;</button></div>' +
        '<div class="dbody"><p class="note">' + esc(err.message) + '</p></div>';
      d.querySelector(".dclose").addEventListener("click", closeDrawer);
      return;
    }
    renderDetail(pid, data);
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
    proposal: ["dsec-customer", "dsec-approved", "dsec-notify"],
    deposit:  ["dsec-deposit"],
    contacts: ["dsec-contacts"],
    schedule: ["dsec-schedule"],
    chat:     ["dsec-chat"],
  };
  const ALL_SEC_CARDS = Object.values(SEC_TABS).flat();
  const SEC_ELIGIBLE = new Set();
  const setSecEligible = (id, on) => { on ? SEC_ELIGIBLE.add(id) : SEC_ELIGIBLE.delete(id); };

  // Module-level, because renderDetail re-runs after every action (act() calls
  // openDetail again) and a local would be wiped each time.
  let ACTIVE_SEC = null;
  let CUR_PID = null;            // the drawer is reused across projects
  const REPLY_DRAFT = {};        // unsent text survives the post-action re-render
  const NT_CACHE = {};           // chips fetch once per render, not per action
  let RENDER_GEN = 0;
  let DEEPLINK_USED = false;

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
      if (t) t.scrollTop = t.scrollHeight;                 // land on the newest message
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
    if (p.proposal_status === "approved" && !p.deposit_requested_at) return "deposit";
    if (p.contacts_status === "received" && p.schedule_status !== "scheduled") return "schedule";
    return "proposal";
  }

  /** Per-project notification chips: who receives THIS project's emails.
   *  Effective state = global roster toggle, overridden per-project (add/mute).
   *  Admins may toggle anyone; other staff only their own address (the server
   *  enforces it too). Loaded only when the Proposal tab is actually on screen,
   *  so replying to a customer no longer costs a round-trip. */
  async function loadNotifyChips(pid, gen) {
    const key = pid + "|" + gen;
    if (!pid || NT_CACHE[key]) return;
    NT_CACHE[key] = 1;
    const me = (window.TWAuth && window.TWAuth.user && window.TWAuth.user()) || {};
    const isAdmin = me.role === "admin" || me.role === "super_admin";
    const myEmail = (me.email || "").toLowerCase();
    try {
      const r = await api("/api/portal/proposal/" + encodeURIComponent(pid) + "/notify-overrides");
      const j = await r.json();
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      // Re-read the node AFTER the await: a re-render mid-fetch would otherwise
      // leave us writing into a detached element.
      const wrap = $("nt-chips");
      if (!wrap || gen !== RENDER_GEN) return;
      const ov = {};                                        // email -> 'add' | 'mute'
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
             + `${canEdit ? "" : " disabled"} title="${canEdit ? esc(p.email) : "Only admins can change others"}">${esc(nameOf(p.email))}</button>`;
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
          openDetail(pid);   // refresh chips
        } catch (err) {
          const al = $("nt-alert");
          if (al) al.textContent = "Could not update: " + (err.message || "retry");
          b.disabled = false;
        }
      }));
    } catch (err) {
      const wrap = $("nt-chips");
      if (wrap && gen === RENDER_GEN) wrap.innerHTML = '<span class="note">Could not load notifications: ' + esc(err.message) + "</span>";
    }
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
    const dep = s.depositDone ? { done: true, val: "Received" }
      : s.depositSubmitted ? { needs: true, val: "Confirm it" }
      : (s.approved && !s.requested) ? { needs: true, val: "Send request" }
      : { val: s.requested ? "Requested" : "Pending" };
    return `<div class="dtabs" role="tablist" aria-label="Project sections">` +
      secTab("proposal", "Proposal", { done: s.approved, val: s.approved ? "Approved" : "Awaiting",
        hint: "Customer, approval, notification recipients" }) +
      secTab("deposit", "Deposit", Object.assign({ hint: "Invoice, what the customer submitted, mark received" }, dep)) +
      secTab("contacts", "Contacts", { done: s.contactsDone, val: s.contactsDone ? "Received" : "Pending",
        hint: "Project contacts the customer supplied" }) +
      secTab("schedule", "Schedule", { done: s.scheduledDone, val: s.scheduledDone ? "Scheduled" : "Pending",
        hint: "Book the job once the deposit clears" }) +
      secTab("chat", "Chat", { needs: s.unread > 0, val: s.unread > 0 ? s.unread + " unread" : "Open",
        badge: s.unread > 0 ? s.unread : "", hint: "Conversation with the customer" }) +
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
      return `<div class="chat-card proposal ${sideOf(m)}"><div class="cc-title">Your proposal is ready</div>
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
    return `<div class="msg ${staff ? "staff" : "customer"}">
      <div class="who">${staff ? "Treadwell" : "Customer"}${viaEmail ? ' <span class="via-email">via email</span>' : ""}</div>
      <div>${esc(m.body)}</div>
      <div class="when">${t}</div>
    </div>`;
  }

  function renderDetail(pid, data) {
    const p = data.proposal, a = data.approval;
    const approved = p.proposal_status === "approved";
    const depositDone = p.deposit_status === "received";
    const depositSubmitted = p.deposit_status === "submitted";
    const contactsDone = p.contacts_status === "received";
    const scheduledDone = p.schedule_status === "scheduled";

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
      ${renderSecTabs({ approved, depositDone, depositSubmitted, contactsDone, scheduledDone,
                        requested: !!p.deposit_requested_at, unread })}
      <div class="dbody">
       <div class="dpanel" id="dpanel-proposal" role="tabpanel" aria-labelledby="dtab-proposal" tabindex="-1">
        <div class="sec" id="dsec-customer"><div class="lbl">Customer</div>${esc(p.customer_name || "")} &lt;${esc(p.customer_email)}&gt;<br>
          <a class="link" href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.url)}</a></div>
        ${a ? `<div class="sec" id="dsec-approved"><div class="lbl">Approved</div>${esc(a.name)}${a.title ? ", " + esc(a.title) : ""}
          on ${esc(a.date || "")} — <strong>${esc(approvedOpts || "")}</strong> at <strong>${money(a.total)}</strong></div>` : ""}

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
          <div class="note">Auto-calculated (25%): <strong>${depAmt != null ? money(depAmt) : "—"}</strong>${data.deposit_ref ? ` · match ref <strong>${esc(data.deposit_ref)}</strong> on the statement` : ""}${p.deposit_requested_at ? ` · requested ${when(p.deposit_requested_at)}` : ""}</div>
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

       <div class="dpanel" id="dpanel-schedule" role="tabpanel" aria-labelledby="dtab-schedule" tabindex="-1">
        <div class="sec" id="dsec-schedule">
          <div class="lbl">Schedule</div>
          <p class="note">${scheduledDone ? "This job is booked."
            : "Treadwell books the date once the deposit has cleared. Mark it here when the crew is scheduled — the customer is told."}</p>
          <div class="row3" style="margin-top:8px">
            <button class="btn btn-s" id="mark-scheduled" ${scheduledDone ? "disabled" : ""}>Mark scheduled</button>
          </div>
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
      </div>`;

    const gen = ++RENDER_GEN;
    // Which cards APPLY. Every id in SEC_TABS must appear here or it can never
    // render — the portal shipped two bugs from exactly this omission.
    setSecEligible("dsec-customer", true);
    setSecEligible("dsec-approved", !!a);
    setSecEligible("dsec-notify", true);
    setSecEligible("dsec-deposit", true);
    setSecEligible("dsec-contacts", true);
    setSecEligible("dsec-schedule", true);
    setSecEligible("dsec-chat", true);

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
    $("mark-scheduled").addEventListener("click", (e) => act("/api/portal/proposal/" + encodeURIComponent(pid) + "/scheduled", e.target));

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

  // Wired ONCE — the controls live in static markup, not in renderBoard, so they
  // keep their focus and value while the board repaints after a staff action.
  (function wireToolbar() {
    const est = $("crm-est"), month = $("crm-month");
    const sort = $("crm-sort"), dir = $("crm-dir"), clear = $("crm-clear");
    const syncDir = () => {
      if (!dir) return;
      dir.textContent = SORTDIR === "asc" ? "↑ Asc" : "↓ Desc";
      dir.setAttribute("aria-pressed", SORTDIR === "asc" ? "true" : "false");
      dir.title = SORTDIR === "asc"
        ? "Ascending (oldest · A→Z · low→high) — click for descending"
        : "Descending (newest · Z→A · high→low) — click for ascending";
    };
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
    if (clear) clear.addEventListener("click", () => {
      EST = ""; MONTH = ""; SORTFIELD = "activity"; SORTDIR = "desc";
      [EST_KEY, MONTH_KEY, SORTFIELD_KEY, SORTDIR_KEY].forEach((k) => ssSet(k, ""));
      $("search").value = "";
      if (sort) sort.value = "activity";
      syncDir(); renderBoard();
    });
  })();
  load();
})();
