// Externalized from dropbox.html (CSP: drop script-src 'unsafe-inline'). Do not add inline scripts.
  const state = TW.getState();
  // Something must have been estimated/generated before there's anything to file:
  // a Screen-3 proposal_payload, a prior generate_result, OR estimate cell_values
  // (existing/older projects — the backend reconstructs the payload from them).
  const hasProposal = !!(state && (
    (state.proposal_payload && state.proposal_payload.values) ||
    state.generate_result ||
    (state.cell_values && Object.keys(state.cell_values).length)
  ));

  const main = document.getElementById("dbx-main");
  const empty = document.getElementById("dbx-empty");

  if (!hasProposal) {
    empty.style.display = "";
  } else {
    main.style.display = "";
    const projEl = document.getElementById("dbx-project");
    if (projEl) projEl.textContent = (state.project_name || "This project")
      + (state.work_type ? " · " + String(state.work_type).toUpperCase() : "");

    const dest = document.getElementById("dbx-dest");
    const go = document.getElementById("dbx-go");
    const result = document.getElementById("dbx-result");

    dest.addEventListener("change", () => { go.disabled = !dest.value; });

    go.addEventListener("click", async () => {
      const draftId = TW.getDraftId();
      if (!draftId) { alert("Open this project from Projects first, then send."); return; }
      if (!dest.value) return;
      go.classList.remove("dbx-ok");             // reset from a prior success
      go.disabled = true; go.textContent = "Uploading to Dropbox…";
      result.style.display = "none";
      try {
        const resp = await fetch(TW.resolveApiBase() + "/api/to-dropbox", {
          method: "POST",
          headers: TW.authHeaders(),
          body: JSON.stringify({ draft_id: draftId, destination: dest.value }),
        });
        const j = await resp.json().catch(() => ({}));
        if (!resp.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + resp.status));
        go.textContent = "✓ Uploaded — click to re-upload";
        go.classList.add("dbx-ok");                // turn the button green
        go.disabled = false;                       // allow re-upload (idempotent — overwrites the folder)
        const link = (url, label) => url
          ? '<a href="' + esc(url) + '" target="_blank" rel="noopener">' + label + '</a>' : "";
        const links = [
          link(j.folder_url, "📁 Open the Dropbox folder"),
          link(j.xlsx_url, "Estimate (.xlsx)"),
          link(j.docx_url, "Proposal (.docx)"),
          link(j.pdf_url, "Proposal (PDF)"),
        ].filter(Boolean);
        result.style.display = "";
        result.innerHTML = '<div class="ok">✓ Filed to ' + esc(j.folder_path || "the project folder") + '</div>'
          + '<div style="margin-top:10px;display:flex;flex-direction:column;gap:6px;">' + links.join("") + '</div>';
      } catch (err) {
        result.style.display = "";
        result.innerHTML = '<div class="dbx-err">' + esc(err.message || "Upload failed — please try again.") + '</div>';
        go.disabled = false; go.textContent = "Create folder & upload";
      }
    });
  }

  function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
