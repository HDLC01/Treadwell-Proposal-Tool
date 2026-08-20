// Externalized from dropbox.html (CSP: drop script-src 'unsafe-inline'). Do not add inline scripts.
// Wrapped in an IIFE: this now loads on done.html ALONGSIDE done.js, and both
// declare top-level `const state` / `const result`. Sharing global scope threw
// "Identifier 'state' has already been declared", so this file never ran and
// the Dropbox section stayed hidden.
(function () {
  // Local to this IIFE on purpose — done.js is a separate scope and may own its own $.
  const $ = (id) => document.getElementById(id);
  const state = TW.getState();
  // Something must have been estimated/generated before there's anything to file:
  // a Screen-3 proposal_payload, a prior generate_result, OR estimate cell_values
  // (existing/older projects — the backend reconstructs the payload from them).
  const hasProposal = !!(state && (
    (state.proposal_payload && state.proposal_payload.values) ||
    state.generate_result ||
    (state.cell_values && Object.keys(state.cell_values).length)
  ));

  // ── the project-folder chooser ──────────────────────────────────────────────
  // Step 5 used to ask only WHICH CATEGORY to file into and then invent a
  // "YY.MM.DD Project name" folder inside it. Kyle's team already makes the job's
  // folder — often weeks before the estimate exists — so the destination ended up
  // holding two folders for one job. The estimator now PICKS the existing folder and
  // creating one is the last, deliberate option.
  //
  // A radio group and not a <select>: the candidates differ by a date prefix and a
  // word ("26.06.12 Trabon Office Polish" vs "26.08.02 Trabon Group"), and choosing
  // between those needs them all on screen at once, each with the parent it lives in.
  const DBX_MIN_SCORE = 0.72;   // below this the server's best guess is only a guess
  const DBX_MIN_LEAD = 0.15;    // ...and neither of two near-identical names may be armed
  // Filing an estimate into the wrong customer's folder is far worse than one extra
  // click, so a weak or a contested match preselects NOTHING and leaves Upload disabled.

  /** One chooser's worth of state.
   *  `choice`: null = nothing chosen (Upload stays disabled), "" = create a new folder,
   *  anything else = the absolute Dropbox path of an existing folder. */
  function dbxState() {
    return { folders: [], suggested: "", error: "", previous: "", destLabel: "",
             filter: "", choice: null, loading: false, open: false, uploaded: false };
  }
  const DBX = dbxState();

  /** What, if anything, may be preselected.
   *
   *  previous_path first: this project was filed there last time, which beats any
   *  similarity score. Then the server's ranking, but only when its best candidate is
   *  both strong on its own AND clear of the runner-up — "Trabon Group" scoring 0.80
   *  against "Trabon Office" at 0.78 is exactly the pair a human must resolve.
   *  A category with no candidates at all arms the create option: there is nothing
   *  left to get wrong, and step 5 must never dead-end. */
  function dbxPreselect(folders, previousPath) {
    const list = folders || [];
    if (!list.length) return "";
    if (previousPath && list.some((f) => f && f.path === previousPath)) return previousPath;
    const top = Number((list[0] || {}).score || 0);
    // No runner-up means no contest — -1 keeps the lead test true for a lone candidate.
    const next = list.length > 1 ? Number((list[1] || {}).score || 0) : -1;
    if (top >= DBX_MIN_SCORE && (top - next) >= DBX_MIN_LEAD) return list[0].path;
    return null;
  }

  /** Filter on the text the row actually SHOWS (name + parent), because that is what the
   *  estimator is reading when they type. */
  function dbxMatches(f, q) {
    const needle = String(q || "").trim().toLowerCase();
    if (!needle) return true;
    return (String((f && f.name) || "") + " " + String((f && f.parent) || ""))
      .toLowerCase().indexOf(needle) >= 0;
  }
  function dbxVisible(folders, q) {
    return (folders || []).filter((f) => dbxMatches(f, q));
  }

  /** The chosen folder's record, looked up in the FULL list rather than the filtered one:
   *  a choice must keep its name in the note even while the filter hides its row. */
  function dbxChosenFolder(st) {
    if (!st.choice) return null;
    return (st.folders || []).filter((f) => f && f.path === st.choice)[0] || null;
  }

  function dbxFolderRow(f, st) {
    // The parent only earns a line when it differs from the category the estimator picked —
    // "in *Kyle" is the whole point of showing it, "in Gyp Estimates" is noise.
    const parent = (f.parent && f.parent !== st.destLabel)
      ? '<span class="dbx-folder-parent">in ' + esc(f.parent) + '</span>' : "";
    const badge = (st.folders.length && f.path === st.folders[0].path)
      ? '<span class="dbx-badge">closest match</span>' : "";
    // The full path as the title: two folders one word apart are told apart by a hover.
    return '<label class="dbx-folder" title="' + esc(f.path) + '">'
      + '<input type="radio" name="dbx-folder" class="dbx-radio" value="' + esc(f.path) + '"'
      + (st.choice === f.path ? " checked" : "") + '>'
      + '<span class="dbx-folder-text"><span class="dbx-folder-name">' + esc(f.name) + '</span>'
      + parent + '</span>' + badge + '</label>';
  }

  /** Always the LAST row, and never filtered away. */
  function dbxNewRow(st) {
    const name = st.suggested || "";
    return '<label class="dbx-folder dbx-folder-new" title="'
      + esc(name ? "Creates " + name : "Creates a new project folder") + '">'
      + '<input type="radio" name="dbx-folder" class="dbx-radio" value="" data-new="1"'
      + (st.choice === "" ? " checked" : "") + '>'
      + '<span class="dbx-folder-text"><span class="dbx-folder-name">＋ Create a new folder</span>'
      + (name ? '<span class="dbx-folder-parent">named ' + esc(name) + '</span>' : "")
      + '</span></label>';
  }

  function dbxFoldersHtml(st) {
    if (st.loading) return '<p class="dbx-none">Looking for this project’s folder…</p>';
    const shown = dbxVisible(st.folders, st.filter);
    const rows = shown.map((f) => dbxFolderRow(f, st));
    if (st.folders.length && !shown.length) {
      rows.push('<p class="dbx-none">No folder here matches “' + esc(st.filter) + '”.</p>');
    }
    rows.push(dbxNewRow(st));          // appended AFTER the filter, on purpose
    return rows.join("");
  }

  /** The one line under the list. Plain text (written with textContent), and it names the
   *  chosen folder even when the filter is hiding its row — a "File into this folder"
   *  button with no visible selection is how an estimate lands in the wrong customer's job. */
  function dbxNote(st) {
    if (!st.open) return "";          // no destination chosen yet — the whole field is hidden
    if (st.loading) return "Looking for this project’s folder in Dropbox…";
    if (st.choice) {
      const f = dbxChosenFolder(st);
      return "Filing into " + (f ? f.name + (f.parent ? " (in " + f.parent + ")" : "") : st.choice);
    }
    // Ahead of the create branch on purpose: an outage arms create by itself, and an estimator
    // must be told the list is missing rather than shown a silent "a new folder will be created".
    if (st.error) {
      return "Couldn’t read the Dropbox folders (" + st.error + "). You can still create "
        + (st.suggested || "a new folder") + ".";
    }
    if (st.choice === "") {
      return "A new folder will be created: " + (st.suggested || "YY.MM.DD Project name");
    }
    if (!st.folders.length) return "No folders came back for this destination.";
    return "Pick the folder this project is already in — or create a new one.";
  }

  function dbxGoLabel(st) {
    if (st.choice) return "File into this folder";
    if (st.choice === "") return "Create folder & upload";
    return "Choose a folder above";
  }
  function dbxGoDisabled(st) { return !st.open || st.loading || st.choice === null; }

  /** Note + button only. A radio `change` must NOT re-render the list: the re-render throws
   *  away the focus the estimator just tabbed into (the CRM board learned this), and the
   *  checked mark comes from CSS off :checked anyway. */
  function dbxSyncGo(st) {
    const note = $("dbx-folder-note");
    if (note) note.textContent = dbxNote(st);
    const go = $("dbx-go");
    if (!go) return;
    // `disabled` is ALWAYS honoured, uploaded or not. It used to be skipped while
    // the green "already filed" state stood, which left the button live across a
    // destination change: dbxBeginLoad had cleared the choice, nothing was
    // selected, and the click posted folder_path:"" — creating exactly the second
    // folder this picker exists to prevent (review 2026-08-20).
    go.disabled = dbxGoDisabled(st);
    // Only the LABEL defers to the green state, so "✓ Uploaded — click to
    // re-upload" survives a re-render instead of flipping back to "File into…".
    if (!st.uploaded) go.textContent = dbxGoLabel(st);
  }

  function dbxChoose(value) {
    DBX.choice = (value == null) ? null : String(value);
    dbxSyncGo(DBX);
  }

  function dbxWireRadios() {
    const box = $("dbx-folders");
    if (!box) return;
    const radios = box.querySelectorAll(".dbx-radio");
    for (let i = 0; i < radios.length; i++) {
      const node = radios[i];
      node.addEventListener("change", () => dbxChoose(node.value));
    }
  }

  function dbxRenderFolders(st) {
    const field = $("dbx-folder-field");
    if (field) field.style.display = st.open ? "" : "none";
    const box = $("dbx-folders");
    if (box) {
      box.innerHTML = st.open ? dbxFoldersHtml(st) : "";
      dbxWireRadios();                 // fresh markup, fresh handlers
    }
    dbxSyncGo(st);
  }

  /** The state as it stands the moment a destination is chosen and the request goes out.
   *  `previous` is deliberately NOT cleared: it comes off the draft, not off the response. */
  function dbxBeginLoad(st, destKey, label) {
    st.open = !!destKey;
    st.destLabel = label || "";
    st.folders = []; st.suggested = ""; st.error = "";
    st.filter = ""; st.choice = null;
    st.loading = st.open;
    return st;
  }

  /** Fold one /api/dropbox/project-folders response into the state and render it.
   *  An error (or an empty list) degrades to the old behaviour — create-only, button
   *  usable — rather than blocking the upload. */
  function dbxApply(j) {
    const r = j || {};
    DBX.loading = false;
    DBX.folders = Array.isArray(r.folders) ? r.folders.filter((f) => f && f.path) : [];
    DBX.suggested = r.suggested_new_name || "";
    DBX.error = r.error || "";
    DBX.previous = r.previous_path || DBX.previous || "";
    DBX.choice = dbxPreselect(DBX.folders, DBX.previous);
    dbxRenderFolders(DBX);
  }

  function dbxWireSearch() {
    const search = $("dbx-search");
    if (!search) return;
    search.addEventListener("input", () => {
      DBX.filter = search.value || "";
      dbxRenderFolders(DBX);           // focus stays in the box being typed into
    });
  }

  const main = $("dbx-main");
  const empty = $("dbx-empty");

  if (!hasProposal) {
    empty.style.display = "";
  } else {
    main.style.display = "";
    const projEl = $("dbx-project");
    if (projEl) projEl.textContent = (state.project_name || "This project")
      + (state.work_type ? " · " + String(state.work_type).toUpperCase() : "");

    const dest = $("dbx-dest");
    const go = $("dbx-go");
    const result = $("dbx-result");
    const owner = $("dbx-owner");
    const ownerField = $("dbx-owner-field");

    // The per-person "Store in" picker only applies to Commercial Sales.
    let COMMERCIAL_KEY = "commercial";
    function syncOwner() {
      if (ownerField) ownerField.style.display = (dest.value === COMMERCIAL_KEY) ? "" : "none";
    }
    function ownerValue() {
      return (dest.value === COMMERCIAL_KEY && owner) ? owner.value : "";
    }
    function destLabel() {
      const opt = dest.options ? dest.options[dest.selectedIndex] : null;
      return opt ? String(opt.text || "").trim() : "";
    }

    /** Fill both pickers from the LIVE Dropbox listing, so a folder added or
     *  removed there shows up without a deploy. The endpoint falls back to the
     *  server's constants if Dropbox is unreachable, so this never empties the
     *  form; on a total failure we simply keep the markup's defaults. */
    async function loadFolders() {
      try {
        const r = await fetch("/api/dropbox/folders", { headers: TW.authHeaders() });
        const j = await r.json();
        if (!j || !j.ok || !Array.isArray(j.destinations) || !j.destinations.length) return;
        COMMERCIAL_KEY = j.commercial_key || COMMERCIAL_KEY;
        const keep = dest.value;
        dest.innerHTML = '<option value="">Choose a folder…</option>'
          + j.destinations.map((d) => `<option value="${esc(d.key)}">${esc(d.label)}</option>`).join("");
        if (keep && dest.querySelector(`option[value="${CSS.escape(keep)}"]`)) dest.value = keep;
        if (owner) {
          const keepOwner = owner.value;
          const catLabel = (j.destinations.find((d) => d.key === COMMERCIAL_KEY) || {}).label
            || "Commercial Sales Estimates";
          owner.innerHTML = `<option value="">${esc(catLabel)}</option>`
            + (j.owners || []).map((o) => `<option value="${esc(o.key)}">${esc(o.label)}</option>`).join("");
          if (keepOwner && owner.querySelector(`option[value="${CSS.escape(keepOwner)}"]`)) owner.value = keepOwner;
        }
        syncOwner();
      } catch { /* keep the markup defaults */ }
      // Only now is the destination key final (the listing can rename or drop one), so this
      // is where a restored destination gets its candidate folders.
      if (dest.value) loadProjectFolders();
    }

    // Two fast destination changes can come back out of order; only the newest may render.
    let dbxSeq = 0;
    async function loadProjectFolders() {
      dbxBeginLoad(DBX, dest.value, destLabel());
      const search = $("dbx-search");
      if (search) search.value = "";
      dbxRenderFolders(DBX);
      if (!DBX.open) return;
      const seq = ++dbxSeq;
      let j = {};
      try {
        const qs = "?destination=" + encodeURIComponent(dest.value)
          + "&folder_owner=" + encodeURIComponent(ownerValue())
          + "&draft_id=" + encodeURIComponent(TW.getDraftId() || "");
        const r = await fetch(TW.resolveApiBase() + "/api/dropbox/project-folders" + qs,
                              { headers: TW.authHeaders() });
        j = (await r.json().catch(() => ({}))) || {};   // a null body is still an object here
        if (!r.ok && !j.error) j = { error: "HTTP " + r.status };
      } catch (err) {
        j = { error: (err && err.message) || "Dropbox is unreachable" };
      }
      if (seq !== dbxSeq) return;
      dbxApply(j);
    }

    function renderResult(j) {
      const link = (url, label) => url
        ? '<a href="' + esc(url) + '" target="_blank" rel="noopener">' + label + '</a>' : "";
      const links = [
        link(j.folder_url, "📁 Open the Dropbox folder"),
        link(j.xlsx_url, "Estimate (.xlsx)"),
        link(j.docx_url, "Proposal (.docx)"),
        link(j.pdf_url, "Proposal (PDF)"),
      ].filter(Boolean);
      // Dropbox will not overwrite blindly when we file into a folder the team already owns,
      // so a name clash comes back as an autorename. Say it plainly — the estimator has to know
      // there are now two files and which one is theirs.
      const renamed = (Array.isArray(j.renamed) ? j.renamed : []).filter(Boolean);
      const clash = renamed.length
        ? '<div class="dbx-warn">A file named ' + renamed.map(esc).join(", ")
          + ' was already in that folder, so this upload was saved under a new name. '
          + 'The existing file was not touched.</div>'
        : "";
      result.style.display = "";
      result.innerHTML = '<div class="ok">✓ Filed to ' + esc(j.folder_path || "the project folder")
        + (j.existing ? " (the folder you picked)" : "") + '</div>' + clash
        + '<div style="margin-top:10px;display:flex;flex-direction:column;gap:6px;">' + links.join("") + '</div>';
    }
    function showUploaded() {
      DBX.uploaded = true;          // stops a later re-render from repainting the button
      go.textContent = "✓ Uploaded — click to re-upload";
      go.classList.add("dbx-ok");   // green
      go.disabled = false;          // allow re-upload (idempotent — overwrites the folder)
    }

    // Restore the "already filed" (green) state if this project was uploaded
    // before — persisted on the draft, so it survives leaving + returning.
    const prev = state.dropbox_result;
    if (prev && prev.folder_url) {
      if (prev.destination) dest.value = prev.destination;
      if (owner && prev.folder_owner != null) owner.value = prev.folder_owner;
      // Where it went last time. loadProjectFolders() preselects this row again once the
      // candidates arrive, so a re-upload defaults to the same folder rather than a new one.
      if (prev.folder_path) DBX.previous = prev.folder_path;
      renderResult(prev);
      showUploaded();
    }
    syncOwner();
    dbxWireSearch();
    dbxRenderFolders(DBX);          // hidden until a destination is chosen

    dest.addEventListener("change", () => { syncOwner(); loadProjectFolders(); });
    // The owner narrows WHICH folders exist (*Kyle's are not *RJ's), so it re-queries too.
    if (owner) owner.addEventListener("change", () => { if (dest.value) loadProjectFolders(); });

    loadFolders();

    go.addEventListener("click", async () => {
      const draftId = TW.getDraftId();
      if (!draftId) { alert("Open this project from Projects first, then send."); return; }
      if (!dest.value) return;
      // No escape hatch for the already-uploaded state. A re-upload is fine — the
      // choice is still set after a success, so this guard passes — but "I filed
      // once" must not stand in for "a folder is chosen NOW": after a destination
      // change the choice is null and this is the last thing between a stale click
      // and a duplicate folder (review 2026-08-20).
      if (dbxGoDisabled(DBX)) return;                    // no folder chosen yet
      DBX.uploaded = false;                      // the button is ours again until it succeeds
      go.classList.remove("dbx-ok");             // reset from a prior success
      go.disabled = true; go.textContent = "Uploading to Dropbox…";
      result.style.display = "none";
      const chosenPath = DBX.choice || "";
      try {
        const body = { draft_id: draftId, destination: dest.value, folder_owner: ownerValue() };
        // Sent even when it is EMPTY. "" is the estimator deliberately choosing the
        // "＋ Create a new folder" row, and the server has a fallback that re-files into
        // whatever folder this project went to last time whenever folder_path is absent —
        // so omitting it here would quietly ignore that choice and report success as
        // "(the folder you picked)". It also un-sticks the case where the recorded folder
        // has since been renamed in Dropbox: the fallback fails validation and step 5
        // dead-ends on "couldn't find that folder" with no way forward.
        //
        // The field is omitted ONLY when the folder list could not be read at all: there
        // was no choice to make then, and the recorded folder is the safer answer (it is
        // the one thing standing between a Dropbox outage and a duplicate folder).
        if (chosenPath || !DBX.error) body.folder_path = chosenPath;
        const resp = await fetch(TW.resolveApiBase() + "/api/to-dropbox", {
          method: "POST",
          headers: TW.authHeaders(),
          body: JSON.stringify(body),
        });
        const j = await resp.json().catch(() => ({}));
        if (!resp.ok || j.ok === false) throw new Error(j.error || j.detail || ("HTTP " + resp.status));
        showUploaded();
        renderResult(j);
        // Remember it locally too, so returning to this page shows the green
        // state immediately (the backend also persisted it on the draft).
        //
        // EVERY key the server put on `dropbox_result` has to be mirrored here, not
        // just the ones this page renders. shared.js PUTs the WHOLE state blob and
        // drafts.save_draft replaces `data` outright (only _SERVER_OWNED_KEYS survive),
        // so a partial object here DELETES the rest from the draft on the next autosave.
        // `written_paths` is the one that costs: backend/main.py reads it back on the
        // NEXT filing to know which files in Kyle's folder are ours to overwrite —
        // without it our own estimate sheet looks like a human's and gets saved beside
        // itself as "… (1).xlsx", every single send.
        try {
          TW.setState({ dropbox_result: {
            destination: dest.value,
            folder_owner: ownerValue(),
            folder_path: j.folder_path || chosenPath, folder_url: j.folder_url,
            xlsx_url: j.xlsx_url, docx_url: j.docx_url, pdf_url: j.pdf_url,
            existing: !!j.existing,
            written_paths: Array.isArray(j.written_paths) ? j.written_paths : [],
            renamed: Array.isArray(j.renamed) ? j.renamed : [] } });
        } catch {}
      } catch (err) {
        result.style.display = "";
        result.innerHTML = '<div class="dbx-err">' + esc(err.message || "Upload failed — please try again.") + '</div>';
        go.disabled = false; go.textContent = dbxGoLabel(DBX);
      }
    });
  }

  function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
})();
