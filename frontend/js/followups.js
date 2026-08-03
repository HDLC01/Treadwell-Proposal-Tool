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
  const K = { tab: "tw_fu_tab", est: "tw_fu_est", sort: "tw_fu_sort", dir: "tw_fu_dir", q: "tw_fu_q" };
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
    const inTab = ALL.filter((p) => TAB === "all" || bucket(p) === TAB);
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
        <button type="button" data-act="log" title="Log a call, email, text or note">Log</button>
        <button type="button" data-act="open" title="Open in the Customer Portal CRM">Open</button>
      </div></td>
    </tr>`;
  }

  function paint() {
    const rows = visible();
    const counts = {};
    TABS.forEach(([k]) => { counts[k] = k === "all" ? ALL.length : ALL.filter((p) => bucket(p) === k).length; });
    const f = $("filters");
    f.hidden = !ALL.length;
    f.innerHTML = TABS.map(([k, label]) =>
      `<button type="button" class="chip ${k === TAB ? "sel" : ""}" data-tab="${k}">${
        esc(label)}<span class="n">${counts[k]}</span></button>`).join("");
    $("toolbar").hidden = !ALL.length;
    populateEstimators();
    syncToolbar();
    $("count").textContent = ALL.length ? rows.length + " of " + ALL.length : "";

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
    const tr = e.target.closest("tr[data-id]");
    if (!tr) return;
    const id = tr.dataset.id;
    if (e.target.closest('[data-act="log"]')) { e.stopPropagation(); logFollowup(id); return; }
    // Anything else on the row opens the full drawer, where the automation toggle,
    // the history and the chat live. This page is the list; that is the detail.
    window.location.assign("/portal.html?open=" + encodeURIComponent(id) + "&sec=followup");
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
      $("list").className = "empty";
      $("list").textContent = "Couldn't load follow-ups: " + (err.message || "") +
        ". Check that the customer portal is reachable.";
    }
  }

  load();
  // Somebody else logging a call should show up here without an F5 — filters and sort
  // survive a repaint (they live in module state and sessionStorage).
  const busy = () => {
    if (document.querySelector(".ov")) return true;                 // a dialog is open
    const a = document.activeElement;
    return !!a && ["INPUT", "SELECT", "TEXTAREA"].includes(a.tagName);
  };
  setInterval(() => { if (!document.hidden && !busy()) load(); }, 45000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !busy()) load(); });
})();
