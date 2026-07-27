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
          ${p.unread ? `<span class="unread" title="${p.unread} customer message${p.unread === 1 ? "" : "s"} awaiting a reply">${p.unread}</span>` : ""}
          <div class="name">${esc(p.project_name || "Proposal")}</div>
          <div class="meta">${esc(p.customer_email || "")}</div>
          ${p.approved_total != null ? `<div class="val">${money(p.approved_total)}</div>` : ""}
        </div>`).join("") || '<div class="empty">—</div>';
      // Money is in and unconfirmed → flag the column, it's the one needing a human.
      const attn = s === STAGE_SUBMITTED && byStage[s].length ? " col-attn" : "";
      return `<div class="col${attn}"><h2>${s}<span>${byStage[s].length}</span></h2>${cards}</div>`;
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

  // ── modal pop-up (detail drawer) ────────────────────────────────────────────
  function syncScrim() {
    $("scrim").style.display = $("drawer").classList.contains("open") ? "block" : "none";
  }
  function closeDrawer() { $("drawer").classList.remove("open"); syncScrim(); }
  function closeAll() { closeDrawer(); }
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
  // Deposit is no longer two-state — it can sit between pending and received.
  function pillState(label, cls, text) {
    return `<span class="pill ${cls}">${esc(label)}: ${esc(text)}</span>`;
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
                   x.trace_ref ? "trace " + x.trace_ref : "",
                   x.masked_ref || ""].filter(Boolean).map(esc).join(" · ");

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
    const today = new Date();
    // Prefilled, not blank: an existing job number bumps its own sequence,
    // otherwise fall back to the number the portal would assign anyway.
    const prior = splitInvoiceNo(p.deposit_invoice_no);
    const invoiceNo = jobInvoiceNo(prior.job, prior.seq)
      || p.deposit_invoice_no || (data && data.next_invoice_no) || "";
    const f = [
      ["invoice_no", "Invoice no.", invoiceNo],
      ["invoice_date_text", "Date", `${today.getMonth() + 1}/${today.getDate()}/${today.getFullYear()}`],
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

  function msgHtml(m) {
    const t = when(m.created_at);
    // These three render as CARDS, matching the customer portal exactly, so staff
    // see the thread the same way the customer does.
    // 'deposit_submitted' is customer-authored (that's what routes it to the bell),
    // but it's a status line, not something they typed — card it like the portal
    // does, or it renders as a speech bubble putting our words in their mouth.
    if (m.msg_type === "system" || m.msg_type === "deposit_submitted") {
      const s = splitSystem(m.body);
      return `<div class="chat-card system"><div class="cc-title">${esc(s.title)}</div>
        <div class="cc-body">${esc(s.body)}</div></div>`;
    }
    if (m.msg_type === "proposal_card") {
      return `<div class="chat-card proposal"><div class="cc-title">Your proposal is ready</div>
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
      return `<div class="chat-card deposit${dead ? " is-superseded" : ""}">
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

    $("drawer").innerHTML = `
      <div class="dhead">
        <h2>${esc(p.project_name || "Proposal")}</h2>
        <button class="dclose" aria-label="Close">&times;</button>
      </div>
      <div class="dbody">
        <div class="sec row3">
          ${pill("Proposal", approved, "Approved", "Awaiting")}
          ${depositSubmitted && !depositDone
            ? pillState("Deposit", "warn", "Submitted — not confirmed")
            : pill("Deposit", depositDone, "Received", "Pending")}
          ${pill("Contacts", contactsDone, "Received", "Pending")}
          ${pill("Schedule", scheduledDone, "Scheduled", "Pending")}
        </div>
        <div class="sec"><div class="lbl">Customer</div>${esc(p.customer_name || "")} &lt;${esc(p.customer_email)}&gt;<br>
          <a class="link" href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.url)}</a></div>
        ${a ? `<div class="sec"><div class="lbl">Approved</div>${esc(a.name)}${a.title ? ", " + esc(a.title) : ""}
          on ${esc(a.date || "")} — <strong>${esc(approvedOpts || "")}</strong> at <strong>${money(a.total)}</strong></div>` : ""}

        <div class="sec">
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

        <div class="sec">
          <div class="lbl">Project contacts</div>
          ${contacts}
          <div class="row3" style="margin-top:8px">
            <button class="btn btn-s" id="mark-scheduled" ${scheduledDone ? "disabled" : ""}>Mark scheduled</button>
          </div>
        </div>

        <div class="sec">
          <div class="lbl">Notifications for this project</div>
          <p class="note" id="nt-help" style="margin:0 0 4px">Green = receives this project's emails. Overrides the global roster for this project only. Toggling never sends an email; it only sets who's notified when a customer next replies, approves, or pays.</p>
          <div id="nt-alert" class="note" style="margin:4px 0"></div>
          <div id="nt-chips" class="nt-chips"><span class="note">Loading…</span></div>
        </div>

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

    // Per-project notification chips: who receives THIS project's emails. Effective
    // state = global roster toggle, overridden per-project (add/mute). Admins may
    // toggle anyone; other staff only their own address (server-enforced too).
    (async () => {
      const me = (window.TWAuth && window.TWAuth.user && window.TWAuth.user()) || {};
      const isAdmin = me.role === "admin" || me.role === "super_admin";
      const myEmail = (me.email || "").toLowerCase();
      const wrap = $("nt-chips");
      try {
        const r = await api("/api/portal/proposal/" + encodeURIComponent(pid) + "/notify-overrides");
        const j = await r.json();
        if (!r.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + r.status));
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
            $("nt-alert").textContent = "Could not update: " + (err.message || "retry");
            b.disabled = false;
          }
        }));
      } catch (err) {
        if (wrap) wrap.innerHTML = '<span class="note">Could not load notifications: ' + esc(err.message) + "</span>";
      }
    })();

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

  // (The global notification roster moved to its own page — /notifications.html.
  //  Per-project overrides live in the detail drawer above.)

  $("search").addEventListener("input", renderBoard);
  load();
})();
