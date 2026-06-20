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
  if (filesMode && (state.proposal_payload || state.project_name || state.job_name)) {
    viewFiles();                       // generate fresh + show downloads
  } else if (result) {
    // Already generated — show download buttons
    showPostGenerate(result);
  } else if (state.proposal_payload && state.project_name) {
    // Ready to generate — show review card with Generate button
    showPreGenerate();
  } else {
    // No project in flight
    emptyEl.style.display = "";
  }

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
      window.location.assign("/proposal-review.html");
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

    document.getElementById("restart-btn").addEventListener("click", () => {
      TW.clearState();
      window.location.assign("/");
    });
  }
