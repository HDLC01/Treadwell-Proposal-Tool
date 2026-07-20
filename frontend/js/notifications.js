// Externalized (CSP: no inline scripts). "Notification Sending" — the global roster
// of who receives Customer Portal notification emails (approvals, replies, questions,
// deposits, contacts, and customer email replies). Green = receives, gray = off.
// Admins edit; other staff see it read-only (server enforces this too). Per-project
// exceptions live in the Customer Portal detail drawer, not here.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const api = (path, opts) => fetch(path, Object.assign({ headers: TW.authHeaders() }, opts || {}));

  let ADMIN = false;

  async function boot() {
    try { await window.TWAuth.ready; } catch (e) { /* auth.js handles redirect */ }
    const me = (window.TWAuth && window.TWAuth.user && window.TWAuth.user()) || {};
    ADMIN = me.role === "admin" || me.role === "super_admin";
    render();
    await load();
  }

  function render() {
    $("root").innerHTML =
      '<h1>Notification Sending</h1>' +
      '<p class="sub">Who gets emailed when a customer approves, replies, asks a question, or submits a deposit or contacts. ' +
      'Green = receives; gray = off. Set exceptions for a single project in the Customer Portal drawer.</p>' +
      '<div class="card">' +
        '<div class="lbl">Team</div>' +
        '<div id="nn-alert" class="alert"></div>' +
        '<div id="nn-chips" class="chips"><span class="note">Loading…</span></div>' +
        (ADMIN
          ? '<div style="margin-top:16px"><div class="lbl">Add someone</div>' +
            '<div class="addrow"><input id="nn-email" type="email" placeholder="name@wetreadwell.com" autocomplete="off" />' +
            '<button class="btn btn-p" id="nn-add" type="button">Add</button></div></div>'
          : '<p class="note" style="margin-top:12px">Only admins can change the list — ask an admin to add or toggle someone.</p>');
    if (ADMIN) {
      $("nn-add").addEventListener("click", addEmail);
      $("nn-email").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addEmail(); } });
    }
  }

  function alert(kind, msg) { const a = $("nn-alert"); if (a) { a.className = "alert " + kind; a.textContent = msg || ""; } }

  async function load() {
    const wrap = $("nn-chips");
    try {
      const r = await api("/api/portal/notify-recipients");
      const j = await r.json();
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      // The roster is managed as 'general' recipients; deposit alerts follow the same list.
      const list = (j.recipients || []).filter((x) => x.kind === "general");
      wrap.innerHTML = list.map((x) => {
        const on = x.enabled !== false;
        return '<span class="chip ' + (on ? "on " : "") + (ADMIN ? "can" : "") + '" data-id="' + esc(x.id) + '" data-on="' + (on ? 1 : 0) + '"'
             + (ADMIN ? ' role="button" tabindex="0"' : "") + '>'
             + esc(String(x.email).split("@")[0]) + ' <span class="em">' + esc(x.email) + '</span>'
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
      await load();
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
      await load();
      alert("ok", "Added " + email + " — green (receiving).");
    } catch (err) { alert("err", "Could not add: " + (err.message || "retry")); }
    finally { btn.disabled = false; btn.textContent = "Add"; }
  }

  async function removeOne(id, chip) {
    const em = chip.querySelector(".em");
    const who = em ? em.textContent : "this person";
    if (!window.confirm("Remove " + who + " from the notification list?")) return;
    try {
      const r = await api("/api/portal/notify-recipients/" + encodeURIComponent(id), { method: "DELETE" });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      await load();
    } catch (err) { alert("err", "Could not remove: " + (err.message || "retry")); }
  }

  boot();
})();
