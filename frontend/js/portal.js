// Customer Portal admin page — proxies to the portal's admin API via the
// proposal-tool backend (/api/portal/*). Externalized (no inline scripts; CSP).
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (n) => (n == null ? "" : "$" + Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  const when = (s) => (s ? new Date(s).toLocaleString() : "");
  const STAGES = ["Sent", "Viewed", "Approved", "Deposit received", "Contact info", "Scheduled"];
  const ROLE_LABEL = { primary: "Primary", accounts_payable: "Accounts payable", other: "Other" };
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
    // Deposit is a prerequisite for advancing past it: a customer may submit
    // contacts right after approval (portal allows it), but an unpaid deal must
    // NOT read as further along than a paid one, so gate "Contact info" on deposit.
    if (p.deposit_status === "received" && p.contacts_status === "received") return "Contact info";
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
    // Deep-link from a staff notification email: ?open=<proposal_id>.
    const openId = new URLSearchParams(location.search).get("open");
    if (openId) openDetail(openId);
  }

  // ── modal pop-ups (detail drawer + recipients) ──────────────────────────────
  function syncScrim() {
    const anyOpen = $("drawer").classList.contains("open") || $("recips").classList.contains("open");
    $("scrim").style.display = anyOpen ? "block" : "none";
  }
  function closeDrawer() { $("drawer").classList.remove("open"); syncScrim(); }
  function closeRecips() { $("recips").classList.remove("open"); syncScrim(); }
  function closeAll() { closeDrawer(); closeRecips(); }
  $("scrim").addEventListener("click", closeAll);              // click the backdrop to close
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeAll(); });  // Esc to close

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

  function msgHtml(m) {
    const t = when(m.created_at);
    if (m.msg_type === "system") return `<div class="note sys">${esc(m.body)}</div>`;
    if (m.msg_type === "proposal_card") return `<div class="note sys">📄 Proposal shared — ${esc(m.body)}</div>`;
    if (m.msg_type === "deposit_request") {
      const amt = m.meta && m.meta.amount != null ? " " + money(m.meta.amount) : "";
      return `<div class="note sys">💳 Deposit requested${amt}</div>`;
    }
    const staff = m.author_kind === "staff";
    return `<div class="msg ${staff ? "staff" : "customer"}">
      <div class="who">${staff ? "Treadwell" : "Customer"}</div>
      <div>${esc(m.body)}</div>
      <div class="when">${t}</div>
    </div>`;
  }

  function renderDetail(pid, data) {
    const p = data.proposal, a = data.approval;
    const approved = p.proposal_status === "approved";
    const depositDone = p.deposit_status === "received";
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

    const deposits = (data.deposits || []).map((x) => `
      <div class="note" style="margin-bottom:6px;">${esc(x.method.toUpperCase())} · ${esc(x.account_name || "—")} ·
      ${esc(x.bank_name || "—")} · ${esc(x.masked_ref || "—")}${x.note ? " · " + esc(x.note) : ""}</div>`).join("");

    const approvedOpts = a && a.options && a.options.length ? a.options.join(", ") : (a ? a.option : "");
    const depAmt = p.deposit_amount != null ? p.deposit_amount : (a ? a.total * 0.25 : null);

    $("drawer").innerHTML = `
      <div class="dhead">
        <h2>${esc(p.project_name || "Proposal")}</h2>
        <button class="dclose" aria-label="Close">&times;</button>
      </div>
      <div class="dbody">
        <div class="sec row3">
          ${pill("Proposal", approved, "Approved", "Awaiting")}
          ${pill("Deposit", depositDone, "Received", "Pending")}
          ${pill("Contacts", contactsDone, "Received", "Pending")}
          ${pill("Schedule", scheduledDone, "Scheduled", "Pending")}
        </div>
        <div class="sec"><div class="lbl">Customer</div>${esc(p.customer_name || "")} &lt;${esc(p.customer_email)}&gt;<br>
          <a class="link" href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.url)}</a></div>
        ${a ? `<div class="sec"><div class="lbl">Approved</div>${esc(a.name)}${a.title ? ", " + esc(a.title) : ""}
          on ${esc(a.date || "")} — <strong>${esc(approvedOpts || "")}</strong> at <strong>${money(a.total)}</strong></div>` : ""}

        <div class="sec">
          <div class="lbl">Deposit</div>
          <div class="note">Auto-calculated (25%): <strong>${depAmt != null ? money(depAmt) : "—"}</strong>${p.deposit_requested_at ? ` · Requested ${when(p.deposit_requested_at)}` : ""}</div>
          <div class="row3" style="margin-top:8px">
            <button class="btn btn-p" id="send-deposit-req" ${approved ? "" : "disabled"} title="${approved ? "" : "Available once the customer approves"}">${p.deposit_requested_at ? "Resend deposit request" : "Send deposit request"}</button>
            <button class="btn btn-s" id="mark-deposit" ${depositDone ? "disabled" : ""}>Mark deposit received</button>
          </div>
        </div>

        <div class="sec">
          <div class="lbl">Project contacts</div>
          ${contacts}
          <div class="row3" style="margin-top:8px">
            <button class="btn btn-s" id="mark-scheduled" ${scheduledDone ? "disabled" : ""}>Mark scheduled</button>
          </div>
        </div>

        ${deposits ? `<div class="sec"><div class="lbl">Deposit submissions</div>${deposits}</div>` : ""}

        <div class="sec">
          <div class="lbl">Conversation</div>
          <div id="thread">${thread}</div>
          <div id="reply-alert" class="note" style="margin:6px 0;"></div>
          <textarea id="reply-body" placeholder="Reply to the customer…"></textarea>
          <div style="margin-top:8px;"><button class="btn btn-p" id="reply-btn">Send reply</button></div>
        </div>
      </div>`;

    const d = $("drawer");
    d.querySelector(".dclose").addEventListener("click", closeDrawer);

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

    $("send-deposit-req").addEventListener("click", (e) => {
      if (e.target.disabled) return;
      const amt = depAmt != null ? money(depAmt) : "the deposit";
      if (!window.confirm(`Send a deposit request for ${amt} to the customer? They'll get a chat message and an email.`)) return;
      act("/api/portal/proposal/" + encodeURIComponent(pid) + "/deposit-request", e.target);
    });
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

  // ── team-notification recipients ────────────────────────────────────────────
  async function openRecips() {
    $("recips").classList.add("open"); syncScrim();
    const m = $("recips");
    m.innerHTML = '<div class="dbody"><p class="note">Loading…</p></div>';
    await tokenReady();
    try {
      const r = await api("/api/portal/notify-recipients");
      const j = await r.json();
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      renderRecips(j.recipients || []);
    } catch (err) {
      m.innerHTML = '<div class="dhead"><h2>Team notifications</h2><button class="dclose">&times;</button></div>' +
        '<div class="dbody"><p class="note">' + esc(err.message) + '</p></div>';
      m.querySelector(".dclose").addEventListener("click", closeRecips);
    }
  }

  function renderRecips(list) {
    const rows = list.map((x) => `
      <div class="recip-row">
        <span><strong>${esc(x.email)}</strong> <span class="pill ${x.kind === "deposit" ? "warn" : "pend"}">${esc(x.kind)}</span></span>
        <button class="btn btn-s recip-del" data-id="${esc(x.id)}">Remove</button>
      </div>`).join("") || '<p class="note">No custom recipients — notifications use the server defaults.</p>';
    $("recips").innerHTML = `
      <div class="dhead"><h2>Team notifications</h2><button class="dclose" aria-label="Close">&times;</button></div>
      <div class="dbody">
        <p class="note">Who's emailed when a customer asks a question, approves, submits a deposit, or sends contacts.
          Leave the list empty to use the server defaults (Kyle, Kylene &amp; RJ are re-seeded on restart).
          "Deposit" recipients receive deposit alerts specifically; "general" get everything else.</p>
        <div class="sec"><div class="lbl">Recipients</div><div id="recip-list">${rows}</div></div>
        <div class="sec">
          <div class="lbl">Add recipient</div>
          <div id="recip-alert" class="note" style="margin:4px 0"></div>
          <div class="recip-add">
            <input id="recip-email" type="email" placeholder="name@wetreadwell.com" />
            <select id="recip-kind"><option value="general">General</option><option value="deposit">Deposit</option></select>
            <button class="btn btn-p" id="recip-add-btn" type="button">Add</button>
          </div>
        </div>
      </div>`;
    const m = $("recips");
    m.querySelector(".dclose").addEventListener("click", closeRecips);
    m.querySelectorAll(".recip-del").forEach((b) => b.addEventListener("click", () => delRecip(b.dataset.id)));
    $("recip-add-btn").addEventListener("click", addRecip);
    $("recip-email").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addRecip(); } });
  }

  async function addRecip() {
    const email = ($("recip-email").value || "").trim().toLowerCase();
    const kind = $("recip-kind").value;
    if (!email) { $("recip-alert").textContent = "Enter an email address."; return; }
    const btn = $("recip-add-btn"); btn.disabled = true; btn.textContent = "Adding…";
    try {
      const r = await api("/api/portal/notify-recipients", { method: "POST", body: JSON.stringify({ email, kind }) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      openRecips();
    } catch (err) {
      $("recip-alert").textContent = "Could not add: " + (err.message || "retry");
      btn.disabled = false; btn.textContent = "Add";
    }
  }

  async function delRecip(id) {
    try {
      const r = await api("/api/portal/notify-recipients/" + encodeURIComponent(id), { method: "DELETE" });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
      openRecips();
    } catch (err) {
      const a = $("recip-alert"); if (a) a.textContent = "Could not remove: " + (err.message || "retry");
    }
  }

  $("recips-btn").addEventListener("click", openRecips);
  $("search").addEventListener("input", renderBoard);
  load();
})();
