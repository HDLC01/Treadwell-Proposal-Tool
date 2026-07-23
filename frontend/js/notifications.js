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
  // Display label from an email local-part with each word capitalized (john.doe → John Doe).
  const nameOf = (email) => String(email || "").split("@")[0].split(/[._-]+/)
    .filter(Boolean).map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ") || String(email || "");

  let ADMIN = false, MY_EMAIL = "";
  let ROSTER = [];                 // [{email, enabled}] — the global base
  let PROJECTS = [];               // [{proposal_id, project_name, customer_email, ...}]
  let OVERRIDES = {};              // { proposal_id: { emailLower: 'add'|'mute' } }

  async function boot() {
    try { await window.TWAuth.ready; } catch (e) { /* auth.js handles redirect */ }
    const me = (window.TWAuth && window.TWAuth.user && window.TWAuth.user()) || {};
    ADMIN = me.role === "admin" || me.role === "super_admin";
    MY_EMAIL = (me.email || "").toLowerCase();
    render();
    await load();          // global roster (also fills ROSTER)
    await loadProjects();  // per-project card
  }

  function render() {
    $("root").innerHTML =
      '<h1>Notification Sending</h1>' +
      '<p class="sub">Who gets emailed when a customer approves, replies, asks a question, or submits a deposit or contacts. ' +
      'Green = receives; gray = off. <strong>Toggling a name never sends an email.</strong> It only sets who gets ' +
      'notified the next time a customer replies, approves, or pays.</p>' +
      '<div class="card">' +
        '<div class="lbl">Team — global default (all projects)</div>' +
        '<div id="nn-alert" class="alert"></div>' +
        '<div id="nn-chips" class="chips"><span class="note">Loading…</span></div>' +
        (ADMIN
          ? '<div style="margin-top:16px"><div class="lbl">Add someone</div>' +
            '<div class="addrow"><input id="nn-email" type="email" placeholder="name@wetreadwell.com" autocomplete="off" />' +
            '<button class="btn btn-p" id="nn-add" type="button">Add</button></div></div>'
          : '<p class="note" style="margin-top:12px">Only admins can change the list — ask an admin to add or toggle someone.</p>') +
      '</div>' +
      '<div class="card">' +
        '<div class="lbl">Per-project — assign specific people</div>' +
        '<p class="note" style="margin:0 0 8px">Green = receives THIS project’s emails. Overrides the global default above for that project only. ' +
        (ADMIN ? "Toggle anyone." : "You can toggle only yourself.") + '</p>' +
        '<input id="pp-search" type="search" class="pp-search" placeholder="Filter by project or customer…" />' +
        '<div id="pp-alert" class="alert"></div>' +
        '<div id="pp-list"><span class="note">Loading…</span></div>' +
      '</div>';
    if (ADMIN) {
      $("nn-add").addEventListener("click", addEmail);
      $("nn-email").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addEmail(); } });
    }
    $("pp-search").addEventListener("input", renderProjects);
  }

  function alert(kind, msg) { const a = $("nn-alert"); if (a) { a.className = "alert " + kind; a.textContent = msg || ""; } }
  function ppAlert(kind, msg) { const a = $("pp-alert"); if (a) { a.className = "alert " + kind; a.textContent = msg || ""; } }

  // ── Global roster card ────────────────────────────────────────────────────
  async function load() {
    const wrap = $("nn-chips");
    try {
      const r = await api("/api/portal/notify-recipients");
      const j = await r.json();
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      const list = (j.recipients || []).filter((x) => x.kind === "general");
      ROSTER = list.map((x) => ({ email: x.email, enabled: x.enabled !== false }));
      wrap.innerHTML = list.map((x) => {
        const on = x.enabled !== false;
        return '<span class="chip ' + (on ? "on " : "") + (ADMIN ? "can" : "") + '" data-id="' + esc(x.id) + '" data-on="' + (on ? 1 : 0) + '"'
             + (ADMIN ? ' role="button" tabindex="0"' : "") + '>'
             + esc(nameOf(x.email)) + ' <span class="em">' + esc(x.email) + '</span>'
             + (ADMIN ? ' <button class="x" title="Remove" aria-label="Remove">&times;</button>' : "")
             + '</span>';
      }).join("") || '<span class="note">No one on the list yet' + (ADMIN ? " — add someone below." : ".") + '</span>';
      if (ADMIN) {
        wrap.querySelectorAll(".chip").forEach((c) => {
          const id = c.dataset.id, on = c.dataset.on === "1";
          c.addEventListener("click", (e) => { if (e.target.classList.contains("x")) return; toggle(id, !on, c); });
          const x = c.querySelector(".x");
          if (x) x.addEventListener("click", (e) => { e.stopPropagation(); removeOne(id, c); });
        });
      }
      alert("", "");
    } catch (err) {
      wrap.innerHTML = '<span class="note">Could not load: ' + esc(err.message) + '</span>';
    }
  }

  async function toggle(id, enabled, chip) {
    if (chip) chip.style.opacity = ".5";
    try {
      const r = await api("/api/portal/notify-recipients/" + encodeURIComponent(id),
        { method: "PATCH", body: JSON.stringify({ enabled }) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      await load(); renderProjects();   // roster base changed → per-project effective states shift
    } catch (err) { alert("err", "Could not update: " + (err.message || "retry")); if (chip) chip.style.opacity = ""; }
  }

  async function addEmail() {
    const email = ($("nn-email").value || "").trim().toLowerCase();
    if (!email) { alert("err", "Enter an email address."); return; }
    const btn = $("nn-add"); btn.disabled = true; btn.textContent = "Adding…";
    try {
      const r = await api("/api/portal/notify-recipients",
        { method: "POST", body: JSON.stringify({ email, kind: "general" }) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      $("nn-email").value = "";
      await load(); renderProjects();
      alert("ok", "Added " + email + " — it's off (gray). Click it to turn green and start sending.");
    } catch (err) { alert("err", "Could not add: " + (err.message || "retry")); }
    finally { btn.disabled = false; btn.textContent = "Add"; }
  }

  async function removeOne(id, chip) {
    const em = chip.querySelector(".em");
    const who = em ? em.textContent : "this person";
    const ok = await TW.confirmDanger({
      title: "Remove from notifications?", before: "Stop sending Customer Portal notifications to ",
      name: who, after: "?", confirmText: "Remove", tone: "danger",
    });
    if (!ok) return;
    try {
      const r = await api("/api/portal/notify-recipients/" + encodeURIComponent(id), { method: "DELETE" });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      await load(); renderProjects();
    } catch (err) { alert("err", "Could not remove: " + (err.message || "retry")); }
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
  function peopleFor(pid) {
    const ov = OVERRIDES[pid] || {};
    const seen = {}, people = [];
    ROSTER.forEach((m) => { const e = m.email.toLowerCase(); seen[e] = 1; people.push({ email: m.email, base: m.enabled }); });
    Object.keys(ov).forEach((e) => { if (!seen[e]) people.push({ email: e, base: false }); });
    return people;
  }

  function renderProjects() {
    const list = $("pp-list");
    if (!list) return;
    const q = ($("pp-search").value || "").toLowerCase().trim();
    const rows = PROJECTS.filter((p) => !q ||
      String(p.project_name || "").toLowerCase().includes(q) ||
      String(p.customer_email || "").toLowerCase().includes(q));
    if (!rows.length) { list.innerHTML = '<span class="note">No published proposals' + (q ? " match your search." : " yet.") + '</span>'; return; }
    list.innerHTML = rows.map((p) => {
      const pid = p.proposal_id;
      const ov = OVERRIDES[pid] || {};
      const custom = Object.keys(ov).length;
      const chips = peopleFor(pid).map((person) => {
        const e = person.email.toLowerCase();
        const mode = ov[e];
        const eff = mode === "add" ? true : mode === "mute" ? false : person.base;
        const canEdit = ADMIN || e === MY_EMAIL;
        return '<button class="nt-chip ' + (eff ? "on" : "") + '" data-pid="' + esc(pid) + '" data-email="' + esc(person.email) + '"'
             + ' data-base="' + (person.base ? 1 : 0) + '" data-eff="' + (eff ? 1 : 0) + '"'
             + (canEdit ? "" : " disabled") + ' title="' + esc(person.email) + '">' + esc(nameOf(person.email)) + '</button>';
      }).join("");
      return '<div class="pp-row">' +
        '<div class="pp-head"><span class="pp-name">' + esc(p.project_name || "Proposal") + '</span>' +
        '<span class="pp-cust">' + esc(p.customer_email || "") + '</span>' +
        (custom ? '<span class="pp-badge">' + custom + ' custom</span>' : "") +
        (ADMIN && custom ? '<button class="pp-reset" data-pid="' + esc(pid) + '" type="button">Reset to global</button>' : "") +
        '</div><div class="nt-chips">' + chips + '</div></div>';
    }).join("");
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
