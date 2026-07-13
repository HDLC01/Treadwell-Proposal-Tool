// Externalized from done.html (CSP: drop script-src 'unsafe-inline'). Do not add inline scripts.
  const state = TW.getState();
  const result = state.generate_result;

  const preEl   = document.getElementById("pre-generate");
  const postEl  = document.getElementById("post-generate");
  const emptyEl = document.getElementById("empty-state");

  // "View files" entry from the Projects list: /done.html?d=<id>&files=1 —
  // skip the intake→estimate→proposal walk and just produce + show the
  // downloads for this saved project (initDraftSync already hydrated its state).
  const filesMode = (() => {
    try { return new URLSearchParams(location.search).get("files") === "1"; }
    catch { return false; }
  })();

  // ─── Decide which mode to show ────────────────────────────────────
  // Wait for initDraftSync to settle draft ownership first: for a foreign /
  // mis-keyed blob it reloads the page (and this promise never resolves), so
  // files-mode can't POST /api/generate from the previous draft's data.
  (async () => {
    try { await (TW.draftReady || Promise.resolve()); } catch {}
    const st = TW.getState();
    const res = st.generate_result;
    if (filesMode && (st.proposal_payload || st.project_name || st.job_name)) {
      viewFiles();                       // generate fresh + show downloads
    } else if (res) {
      showPostGenerate(res);             // already generated — show download buttons
    } else if (st.proposal_payload && st.project_name) {
      showPreGenerate();                 // ready to generate — show review card
    } else {
      emptyEl.style.display = "";        // no project in flight
    }
  })();

  // Generate the files for a saved project and jump straight to downloads.
  async function viewFiles() {
    emptyEl.style.display = "";
    emptyEl.querySelector("h1").textContent = "Preparing files…";
    const lede = emptyEl.querySelector(".lede");
    if (lede) lede.textContent = "Generating the estimate, proposal, and PDF for this project — a few seconds.";
    // viewFiles auto-runs on load; auth.js sets the bearer token asynchronously,
    // so wait for it before the (auth-gated) /api/generate or we'd 401.
    try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch {}
    const s = TW.getState();
    // Prefer the exact payload this project was generated from; otherwise
    // rebuild one from the saved values (backend backfills job_name etc.).
    const pp = s.proposal_payload;
    const payload = (pp && pp.values) ? pp : {
      work_type: s.work_type || "epoxy",
      audience:  s.audience  || "Direct",
      values: s,
      cell_values: s.cell_values || {},
      extras: Array.isArray(s.extras) ? s.extras : [],
      price_lines: Array.isArray(s.price_lines) ? s.price_lines : [],
      computed_bid: s.computed_bid || null,
      alternate_computed_bid: s.alternate_computed_bid || null,
      alternate_label: (s.alternate && s.alternate.label) || s.alternate_label || "",
      // Mirror the user's worksheet copies + tab renames + order into the .xlsx.
      tab_copies: Array.isArray(s.tab_copies) ? s.tab_copies : [],
      tab_labels: (s.tab_labels && typeof s.tab_labels === "object") ? s.tab_labels : {},
      tab_order: Array.isArray(s.tab_order) ? s.tab_order : [],
      // Structural edits + per-cell lock overrides into the .xlsx.
      tab_structs: Array.isArray(s.tab_structs) ? s.tab_structs : [],
      lock_overrides: (s.lock_overrides && typeof s.lock_overrides === "object") ? s.lock_overrides : {},
      // Editable NOTES (one bullet per line) — carry them so the "View files"
      // rebuild keeps the estimator's notes AND the substituted phase-price
      // bullet (empty → backend uses the standard list, phase price from
      // values.phase_price). NOTE: this fallback still drops paragraph_overrides
      // / remodel / rooms — pre-existing lossiness; the primary path
      // (proposal_payload above) carries them all.
      notes: String(s.notes_text || "").split("\n").map(t => t.trim()).filter(Boolean),
      system_overrides: Array.isArray(s.system_overrides) ? s.system_overrides : [],
      // Doc-editor per-line PRICE display overrides (base amount / tax phrase,
      // option + manual line label/amount). Display-only — never affects pricing.
      price_overrides: (s.price_overrides && typeof s.price_overrides === "object") ? s.price_overrides : {},
    };
    try {
      const out = await TW.postJSON("/api/generate", payload);
      TW.setState({ generate_result: out });
      emptyEl.style.display = "none";
      showPostGenerate(out);
    } catch (err) {
      emptyEl.querySelector("h1").textContent = "Couldn't load files";
      if (lede) lede.textContent = "Generating failed: " + (err.message || err) +
        ". Try “Open / Edit” from Projects instead.";
    }
  }

  function fmtUSD(n) {
    return "$" + Number(n || 0).toLocaleString(undefined,
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  // ─── "Send to customer portal" recipients modal ───────────────────────
  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
  const MAX_PORTAL_EMAILS = 10;

  // TW.postJSON flattens a non-2xx into Error("POST … → 400: {\"detail\":\"…\"}").
  // Pull the human message back out for the modal's inline error line.
  function portalErrMsg(err) {
    const s = String((err && err.message) || err || "");
    const m = /"(?:detail|error)"\s*:\s*"([^"]+)"/.exec(s);
    if (m) return m[1];
    return s || "Send failed — try again.";
  }

  // Confirm dialog: shows the FIXED intake email + lets the user add extra
  // recipients, then sends (the send happens inside so the dialog owns the
  // loading/error state — on failure it stays open, retry-able). Resolves
  // {emails, result} on success, or null on cancel. Reuses shared.js's
  // .tw-ov/.tw-dlg base via TW.injectModalCss (CSP: no inline scripts).
  function portalSendDialog(intakeEmail, initialExtras, doSend) {
    return new Promise((resolve) => {
      TW.injectModalCss();
      const intake = (intakeEmail || "").trim();
      const hasIntake = !!intake && EMAIL_RE.test(intake);
      const extras = (initialExtras || [])
        .map(e => (e || "").trim())
        .filter(e => e && EMAIL_RE.test(e) && (!hasIntake || e.toLowerCase() !== intake.toLowerCase()));
      const prevFocus = document.activeElement;

      const ov = document.createElement("div");
      ov.className = "tw-ov";
      ov.setAttribute("role", "dialog");
      ov.setAttribute("aria-modal", "true");
      const dlg = document.createElement("div");
      dlg.className = "tw-dlg tw-dlg--portal";
      dlg.innerHTML =
        '<h2 class="tw-dlg-h">Send to customer portal</h2>' +
        '<p class="tw-dlg-m">Each person gets an email with a secure link to view, ask questions, and approve this proposal.</p>' +
        '<div class="tw-em-list"></div>' +
        '<div class="tw-em-add"><input type="email" placeholder="name@company.com" autocomplete="off">' +
        '<button type="button" class="tw-em-addbtn">Add</button></div>' +
        '<p class="tw-em-err"></p>' +
        '<div class="tw-dlg-act"><button type="button" class="tw-dlg-no">Cancel</button>' +
        '<button type="button" class="tw-dlg-go">Send</button></div>';
      ov.appendChild(dlg);

      const listEl = dlg.querySelector(".tw-em-list");
      const addInput = dlg.querySelector(".tw-em-add input");
      const addBtn = dlg.querySelector(".tw-em-addbtn");
      const errEl = dlg.querySelector(".tw-em-err");
      const noBtn = dlg.querySelector(".tw-dlg-no");
      const goBtn = dlg.querySelector(".tw-dlg-go");
      let busy = false, settled = false;

      const allEmails = () => (hasIntake ? [intake] : []).concat(extras);
      const setErr = (m) => { errEl.textContent = m || ""; };

      function renderList() {
        listEl.textContent = "";
        const rows = (hasIntake ? [{ email: intake, fixed: true }] : [])
          .concat(extras.map(e => ({ email: e, fixed: false })));
        rows.forEach((r) => {
          const row = document.createElement("div");
          row.className = "tw-em-row";
          const em = document.createElement("span");
          em.className = "em"; em.textContent = r.email;
          row.appendChild(em);
          if (r.fixed) {
            const tag = document.createElement("span");
            tag.className = "tw-em-tag"; tag.textContent = "intake";
            row.appendChild(tag);
          } else {
            const x = document.createElement("button");
            x.type = "button"; x.className = "tw-em-x"; x.textContent = "×";
            x.setAttribute("aria-label", "Remove " + r.email);
            x.addEventListener("click", () => {
              const i = extras.indexOf(r.email);
              if (i >= 0) extras.splice(i, 1);
              setErr(""); renderList();
            });
            row.appendChild(x);
          }
          listEl.appendChild(row);
        });
        goBtn.disabled = allEmails().length === 0;
        if (goBtn.disabled) setErr("Add at least one email address.");
      }

      // Add whatever is typed in the input. Returns false (and shows an error)
      // when the residual text is present but invalid — callers must not proceed.
      function tryAdd() {
        const v = addInput.value.trim();
        if (!v) return true;
        if (!EMAIL_RE.test(v)) { setErr("That doesn’t look like an email address."); return false; }
        const lc = v.toLowerCase();
        if (allEmails().some(e => e.toLowerCase() === lc)) { setErr("That email is already in the list."); return false; }
        if (allEmails().length >= MAX_PORTAL_EMAILS) { setErr("Maximum " + MAX_PORTAL_EMAILS + " recipients."); return false; }
        extras.push(v);
        addInput.value = ""; setErr(""); renderList(); addInput.focus();
        return true;
      }

      function close(val) {
        if (settled) return; settled = true;
        document.removeEventListener("keydown", onKey, true);
        ov.classList.remove("tw-in");
        setTimeout(() => { ov.remove(); try { prevFocus && prevFocus.focus && prevFocus.focus(); } catch {} }, 170);
        resolve(val);
      }

      const focusables = () => Array.from(dlg.querySelectorAll("input, button:not([disabled])"));
      function onKey(e) {
        if (e.key === "Escape") { if (!busy) { e.preventDefault(); close(null); } return; }
        if (e.key === "Tab") {
          const f = focusables(); if (!f.length) { e.preventDefault(); return; }
          let i = f.indexOf(document.activeElement); if (i < 0) i = 0;
          e.preventDefault();
          f[(i + (e.shiftKey ? f.length - 1 : 1)) % f.length].focus();
        }
      }

      async function send() {
        if (busy) return;
        if (!tryAdd()) return;                    // residual invalid text blocks the send
        const emails = allEmails();
        if (!emails.length) { setErr("Add at least one email address."); return; }
        busy = true; setErr("");
        noBtn.disabled = addBtn.disabled = addInput.disabled = goBtn.disabled = true;
        goBtn.textContent = "Sending…";
        try {
          const result = await doSend(emails);
          close({ emails, result });
        } catch (err) {
          busy = false;
          noBtn.disabled = addBtn.disabled = addInput.disabled = goBtn.disabled = false;
          goBtn.textContent = "Send";
          setErr(portalErrMsg(err));
        }
      }

      addBtn.addEventListener("click", () => tryAdd());
      addInput.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); tryAdd(); } });
      noBtn.addEventListener("click", () => { if (!busy) close(null); });
      goBtn.addEventListener("click", send);
      ov.addEventListener("mousedown", (e) => { if (e.target === ov && !busy) close(null); });
      document.addEventListener("keydown", onKey, true);
      document.body.appendChild(ov);
      renderList();
      requestAnimationFrame(() => {
        ov.classList.add("tw-in");
        (allEmails().length === 0 ? addInput : goBtn).focus();
      });
    });
  }

  function showPreGenerate() {
    preEl.style.display = "";
    // Show the project deadline as a compact YY.MM.DD due date.
    const dueDate = (iso) => {
      const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
      return m ? `${m[1].slice(2)}.${m[2]}.${m[3]}` : "—";
    };
    document.getElementById("rv-folder").textContent   = state.deadline ? dueDate(state.deadline) : "—";
    document.getElementById("rv-project").textContent  = state.project_name || "—";
    document.getElementById("rv-location").textContent = [state.address, state.city_state, state.zip].filter(Boolean).join(" · ") || "—";
    document.getElementById("rv-worktype").textContent = (state.work_type || "epoxy").toUpperCase();
    document.getElementById("rv-audience").textContent = state.audience || "Direct";
    document.getElementById("rv-lump").textContent     = state.lump_sum_display || "—";

    document.getElementById("back-btn-done").addEventListener("click", () => {
      window.location.assign(TW.withDraft("/proposal-review.html"));
    });
    document.getElementById("gen-btn").addEventListener("click", doGenerate);
  }

  async function doGenerate() {
    const btn = document.getElementById("gen-btn");
    btn.disabled = true;
    btn.textContent = "Generating…";
    try {
      const out = await TW.postJSON("/api/generate", state.proposal_payload);
      TW.setState({ generate_result: out });
      // Swap views — pre → post
      preEl.style.display = "none";
      showPostGenerate(out);
    } catch (err) {
      btn.disabled = false;
      btn.textContent = "Generate Files →";
      alert("Generate failed: " + err.message);
    }
  }

  function showPostGenerate(result) {
    postEl.style.display = "";

    const wt = (state.work_type || "epoxy").toUpperCase();
    const audience = state.audience || "Direct";
    document.getElementById("project-line").textContent =
      `${state.project_name} · ${wt} · ${audience}`;

    const safeName = (state.project_name || "proposal")
      .replace(/[^A-Za-z0-9._-]+/g, "_")
      .slice(0, 60);

    async function downloadAs(urlKey, filename, button) {
      const orig = button.textContent;
      button.disabled = true;
      button.textContent = "Downloading…";
      const latestUrl = () => TW.absoluteUrl(TW.getState().generate_result[urlKey]);
      try {
        // Downloads now require the Supabase bearer (no longer a public
        // capability URL) — TW.authHeaders() carries Authorization: Bearer.
        let resp = await fetch(latestUrl(), { headers: TW.authHeaders() });
        // Download links live in server memory; a restart (deploy/crash/reboot)
        // expires them with a 404. Self-heal: re-generate fresh files from the
        // stashed payload, then retry — invisible to the user (no dead-end).
        if (resp.status === 404 && state.proposal_payload) {
          button.textContent = "Refreshing…";
          const fresh = await TW.postJSON("/api/generate", state.proposal_payload);
          TW.setState({ generate_result: fresh });
          resp = await fetch(latestUrl(), { headers: TW.authHeaders() });
        }
        if (!resp.ok) throw new Error(resp.statusText || ("HTTP " + resp.status));
        // Force a generic type so the browser DOWNLOADS the file under our
        // `a.download` name. If we kept the real type (application/pdf), Chrome's
        // inline PDF viewer hijacks the click, ignores the filename, and saves
        // it as the blob URL's UUID. octet-stream sidesteps that for every type.
        const blob = new Blob([await resp.arrayBuffer()], { type: "application/octet-stream" });
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = blobUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(blobUrl), 1500);
        button.textContent = "✓ Downloaded";
        setTimeout(() => { button.textContent = orig; button.disabled = false; }, 1800);
      } catch (err) {
        console.error("Download failed", err);
        button.textContent = "Failed — try again";
        setTimeout(() => { button.textContent = orig; button.disabled = false; }, 2200);
      }
    }

    const xlsxBtn = document.getElementById("dl-xlsx");
    const docxBtn = document.getElementById("dl-docx");
    const pdfBtn  = document.getElementById("dl-pdf");
    xlsxBtn.addEventListener("click", () => downloadAs(
      "xlsx_download_url", `${safeName}_estimate.xlsx`, xlsxBtn));
    docxBtn.addEventListener("click", () => downloadAs(
      "docx_download_url", `${safeName}_proposal.docx`, docxBtn));
    // PDF is rendered on demand from the .docx (LibreOffice). Only wire the
    // button when the backend returned a pdf url (older cached results won't).
    if (result.pdf_download_url) {
      pdfBtn.addEventListener("click", () => downloadAs(
        "pdf_download_url", `${safeName}_proposal.pdf`, pdfBtn));
    } else {
      pdfBtn.style.display = "none";
    }

    // Send to customer portal — opens a confirm modal (shows the intake email +
    // lets the estimator ADD extra recipients) BEFORE sending. Every recipient
    // gets a secure link + full portal access (view / ask / approve).
    const portalBtn = document.getElementById("portal-btn");
    if (portalBtn) {
      portalBtn.addEventListener("click", async () => {
        const draftId = TW.getDraftId();
        if (!draftId) { alert("Save the project first (open it from Projects), then send."); return; }
        const st = TW.getState();                       // fresh — not the load-time snapshot
        const intake = (st.contact_email || "").trim();
        // Extras = recipients saved from a previous send, minus the intake email.
        const savedExtras = Array.isArray(st.portal_emails) ? st.portal_emails : [];
        const extras = savedExtras.filter(e =>
          e && (!intake || String(e).trim().toLowerCase() !== intake.toLowerCase()));

        const out = await portalSendDialog(intake, extras, (emails) =>
          TW.postJSON("/api/portal/publish?draft_id=" + encodeURIComponent(draftId), { emails }));
        if (!out) return;                               // cancelled — button untouched
        const j = out.result || {};
        if (j.ok === false) {                           // defensive (publish 4xx already threw in the modal)
          alert(j.error === "no_contact_email"
            ? "This proposal has no customer email — add one on the Intake screen first."
            : (j.error || j.detail || "Send failed."));
          return;
        }
        TW.setState({ portal_emails: out.emails });     // persist → next send pre-fills the same list

        portalBtn.disabled = true;
        portalBtn.textContent = "✓ Sent to customer portal";
        const r = document.getElementById("portal-result");
        if (r) {
          r.style.display = "";
          r.textContent = "";
          const recips = (j.recipients && j.recipients.length) ? j.recipients
                        : [j.customer_email || "the customer"];
          const a = document.createElement("a");
          a.href = j.url || "#"; a.target = "_blank"; a.rel = "noopener";
          a.textContent = j.url || "(link)";
          r.appendChild(document.createTextNode("Customer link: "));
          r.appendChild(a);
          r.appendChild(document.createElement("br"));
          r.appendChild(document.createTextNode("Emailed to "));
          const strong = document.createElement("strong");
          strong.textContent = recips.join(", ");
          r.appendChild(strong);
          r.appendChild(document.createTextNode("."));
        }
        // Re-send is a first-class flow now (pre-fills the saved recipients).
        setTimeout(() => { portalBtn.textContent = "↗ Re-send to customer portal"; portalBtn.disabled = false; }, 2500);
      });
    }

    document.getElementById("restart-btn").addEventListener("click", () => {
      TW.clearState();
      window.location.assign("/?new=1");   // start a fresh project (home is Projects)
    });
  }
