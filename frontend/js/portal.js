// Customer Portal admin page — proxies to the portal's admin API via the
// proposal-tool backend (/api/portal/*). Externalized (no inline scripts; CSP).
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (n) => (n == null ? "" : "$" + Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  const STAGES = ["Sent", "Viewed", "Approved", "Deposit received", "Scheduled"];
  let ALL = [];

  function api(path, opts) {
    return fetch(TW.resolveApiBase() + path, Object.assign({ headers: TW.authHeaders() }, opts || {}));
  }
  async function tokenReady() {
    try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch {}
    for (let i = 0; i < 200 && !window.__TW_TOKEN; i++) await new Promise((r) => setTimeout(r, 40));
  }

  function stageOf(p) {
    if (p.schedule_status === "scheduled") return "Scheduled";
    if (p.deposit_status === "received") return "Deposit received";
    if (p.proposal_status === "approved") return "Approved";
    if (p.proposal_status === "viewed") return "Viewed";
    return "Sent";
  }

  function renderBoard() {
    const q = ($("search").value || "").toLowerCase().trim();
    const items = ALL.filter((p) => !q ||
      (p.project_name || "").toLowerCase().includes(q) || (p.customer_email || "").toLowerCase().includes(q));
    $("count").textContent = items.length + " proposal" + (items.length === 1 ? "" : "s");
    const byStage = {};
    STAGES.forEach((s) => (byStage[s] = []));
    items.forEach((p) => byStage[stageOf(p)].push(p));
    $("board").innerHTML = STAGES.map((s) => {
      const cards = byStage[s].map((p) => `
        <div class="deal" data-id="${esc(p.proposal_id)}">
          <div class="name">${esc(p.project_name || "Proposal")}</div>
          <div class="meta">${esc(p.customer_email || "")}</div>
          ${p.approved_total != null ? `<div class="val">${money(p.approved_total)}</div>` : ""}
        </div>`).join("") || '<div class="empty">—</div>';
      return `<div class="col"><h2>${s}<span>${byStage[s].length}</span></h2>${cards}</div>`;
    }).join("");
    $("board").querySelectorAll(".deal").forEach((el) =>
      el.addEventListener("click", () => openDetail(el.dataset.id)));
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
  }

  // ── detail drawer ───────────────────────────────────────────────────────────
  function closeDrawer() { $("drawer").classList.remove("open"); $("scrim").style.display = "none"; }
  $("scrim").addEventListener("click", closeDrawer);

  async function openDetail(pid) {
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

  function pill(label, done, doneText, pendText) {
    return `<span class="pill ${done ? "done" : "pend"}">${label}: ${done ? doneText : pendText}</span>`;
  }

  function renderDetail(pid, data) {
    const p = data.proposal, a = data.approval;
    const approved = p.proposal_status === "approved";
    const depositDone = p.deposit_status === "received";
    const scheduledDone = p.schedule_status === "scheduled";
    const thread = (data.questions || []).map((q) => `
      <div class="msg ${q.author_kind === "staff" ? "staff" : "customer"}">
        <div class="who">${q.author_kind === "staff" ? "Treadwell" : "Customer"}</div>
        <div>${esc(q.body)}</div>
        <div class="when">${q.created_at ? new Date(q.created_at).toLocaleString() : ""}</div>
      </div>`).join("") || '<p class="note">No questions yet.</p>';
    const deposits = (data.deposits || []).map((x) => `
      <div class="note" style="margin-bottom:6px;">${esc(x.method.toUpperCase())} · ${esc(x.account_name || "—")} ·
      ${esc(x.bank_name || "—")} · ${esc(x.masked_ref || "—")}${x.note ? " · " + esc(x.note) : ""}</div>`).join("");

    $("drawer").innerHTML = `
      <div class="dhead">
        <h2>${esc(p.project_name || "Proposal")}</h2>
        <button class="dclose" aria-label="Close">&times;</button>
      </div>
      <div class="dbody">
        <div class="sec row3">
          ${pill("Proposal", approved, "Approved", "Awaiting")}
          ${pill("Deposit", depositDone, "Received", "Pending")}
          ${pill("Schedule", scheduledDone, "Scheduled", "Pending")}
        </div>
        <div class="sec"><div class="lbl">Customer</div>${esc(p.customer_name || "")} &lt;${esc(p.customer_email)}&gt;<br>
          <a class="link" href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.url)}</a></div>
        ${a ? `<div class="sec"><div class="lbl">Approved</div>${esc(a.name)}${a.title ? ", " + esc(a.title) : ""}
          on ${esc(a.date || "")} — <strong>${esc(a.option || "")}</strong> at <strong>${money(a.total)}</strong></div>` : ""}
        <div class="sec row3">
          <button class="btn btn-s" id="mark-deposit" ${depositDone ? "disabled" : ""}>Mark deposit received</button>
          <button class="btn btn-s" id="mark-scheduled" ${scheduledDone ? "disabled" : ""}>Mark scheduled</button>
        </div>
        ${deposits ? `<div class="sec"><div class="lbl">Deposit submissions</div>${deposits}</div>` : ""}
        <div class="sec">
          <div class="lbl">Questions</div>
          <div id="thread">${thread}</div>
          <div id="reply-alert" class="note" style="margin:6px 0;"></div>
          <textarea id="reply-body" placeholder="Reply to the customer…"></textarea>
          <div style="margin-top:8px;"><button class="btn btn-p" id="reply-btn">Send reply</button></div>
        </div>
      </div>`;

    const d = $("drawer");
    d.querySelector(".dclose").addEventListener("click", closeDrawer);

    const act = async (path, btn, okMsg) => {
      btn.disabled = true; const orig = btn.textContent; btn.textContent = "Working…";
      try {
        const r = await api(path, { method: "POST" });
        const j = await r.json().catch(() => ({}));
        if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
        await openDetail(pid);   // refresh drawer
        load();                  // refresh board
      } catch (err) {
        btn.textContent = "Failed — " + (err.message || "retry"); btn.disabled = false;
        setTimeout(() => { btn.textContent = orig; }, 2600);
      }
    };
    $("mark-deposit").addEventListener("click", (e) => act("/api/portal/proposal/" + encodeURIComponent(pid) + "/deposit-received", e.target));
    $("mark-scheduled").addEventListener("click", (e) => act("/api/portal/proposal/" + encodeURIComponent(pid) + "/scheduled", e.target));

    $("reply-btn").addEventListener("click", async () => {
      const body = $("reply-body").value.trim();
      if (!body) return;
      const btn = $("reply-btn"); btn.disabled = true; btn.textContent = "Sending…";
      try {
        const r = await api("/api/portal/proposal/" + encodeURIComponent(pid) + "/reply",
          { method: "POST", body: JSON.stringify({ body }) });
        const j = await r.json().catch(() => ({}));
        if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
        await openDetail(pid);
      } catch (err) {
        $("reply-alert").textContent = "Could not send: " + (err.message || "retry");
        btn.disabled = false; btn.textContent = "Send reply";
      }
    });
  }

  $("search").addEventListener("input", renderBoard);
  load();
})();
