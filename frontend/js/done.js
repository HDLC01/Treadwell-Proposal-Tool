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
      notes: String(s.notes_text || "").replace(/\n+$/, "").split("\n").map(t => t.trim()),
      system_overrides: Array.isArray(s.system_overrides) ? s.system_overrides : [],
      // Boxes the estimator dragged or resized. Carried here as well as on the primary path,
      // because this rebuild is what "View files" re-generates from: without it, a project whose
      // boxes were laid out by hand would come back with them at the template's size, and the
      // second download would disagree with the first one the estimator already checked.
      // The version comes along so the backend can still drop a layout captured against an
      // older .docx — an empty template_version means "legacy caller, apply unchanged", which is
      // exactly the wrong answer for ids that may have shifted.
      box_overrides: (s.box_overrides && typeof s.box_overrides === "object"
                      && !Array.isArray(s.box_overrides)) ? s.box_overrides : {},
      template_version: String((s.box_overrides_meta || {}).template_version || ""),
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

  // Inline recipients editor on the Files page — shown BEFORE sending (no popup).
  // The intake email is a fixed row; the estimator adds/removes extra recipients;
  // the "Send to customer portal" button sends to the whole list. Every recipient
  // gets a secure link + full portal access (view / ask / approve). Exposes a few
  // methods on `portalRecip` for the button handler below.
  // `noFollowups` is the set of addresses the sender un-ticked. Hanz, 2026-08-12: "just like the
  // 25% deposit creat a checkbox for each contact if they will be able to receive the automated
  // follow ups or no". Stored as an opt-OUT set rather than an opt-in list so the default — chase
  // everybody, which is how it has always worked — needs no entry at all.
  const portalRecip = { intake: "", hasIntake: false, extras: [], noFollowups: [], ready: false };

  // ── Require deposit ─────────────────────────────────────────────────────────
  // Ticked → the customer must pay the 25% deposit after approving (today's
  // behaviour). Unticked → the portal requests no deposit at all: no invoice, no
  // Deposit step. Direct work defaults to requiring one, GC work does not, but
  // either can be overridden per send for edge cases.
  //
  // Read state fresh rather than trusting a module-level snapshot: the Files page
  // is reachable both straight after generating and via ?files=1 on a reload.
  function mountRequireDeposit() {
    const el = document.getElementById("portal-require-deposit");
    if (!el) return;
    let st = {};
    try { st = TW.getState() || {}; } catch {}
    const isGC = String(st.audience || "Direct").trim().toUpperCase() === "GC";
    // A previously-sent choice wins over the audience default.
    el.checked = (typeof st.require_deposit === "boolean") ? st.require_deposit : !isGC;
    const hint = document.getElementById("portal-require-deposit-hint");
    if (hint) hint.textContent = isGC ? "(off by default for GC work)" : "(25% on approval)";
  }

  // ── Sent versions (revisions) ───────────────────────────────────────────────
  // Each send snapshots the estimate, so a revised price reuses this project rather
  // than forcing a duplicate — and every version stays downloadable. Documents are
  // rebuilt from the snapshot on demand (nothing binary is stored per revision).
  async function mountRevisions() {
    const box = document.getElementById("revisions-box");
    const list = document.getElementById("revisions-list");
    if (!box || !list) return;
    const draftId = TW.getDraftId();
    if (!draftId) return;
    let revs = [];
    try {
      const r = await fetch(TW.absoluteUrl("/api/draft/" + encodeURIComponent(draftId) + "/revisions"),
                            { headers: TW.authHeaders() });
      if (!r.ok) return;                       // never block the page on history
      revs = (await r.json()).revisions || [];
    } catch { return; }
    if (!revs.length) { box.style.display = "none"; return; }
    const fmtDate = (s) => (window.TW && TW.fmtBizDate) ? TW.fmtBizDate(s)
      : new Date(s).toLocaleDateString("en-US");
    const money = (n) => n == null ? "—"
      : "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    // Classes, not inline styles: this row lives in the send screen's right-hand rail now, where
    // it is ~380px wide, and the three download buttons have to WRAP onto their own line rather
    // than crush the price. `.rev-acts` carries the flex-basis that does it — a rule an inline
    // style could never hold, because an inline style has no media query and no container.
    list.innerHTML = revs.map((rv, i) => `
      <div class="rev-row">
        <span class="rev-no">Rev ${rv.revision_no}</span>
        ${i === 0 ? '<span class="rev-cur">current</span>' : ""}
        <span class="hint">${fmtDate(rv.created_at)}</span>
        <span class="hint">${rv.created_by
          ? window.TWCrm.avatarHtml(rv.created_by) + esc(window.TWCrm.nameOf(rv.created_by))
          : "—"}</span>
        <strong class="rev-money">${money(rv.total)}</strong>
        ${rv.has_documents ? `
          <span class="rev-acts">
            <button class="btn-secondary rev-dl" type="button" data-rev="${rv.revision_no}" data-kind="xlsx">.xlsx</button>
            <button class="btn-secondary rev-dl" type="button" data-rev="${rv.revision_no}" data-kind="docx">.docx</button>
            <button class="btn-secondary rev-dl" type="button" data-rev="${rv.revision_no}" data-kind="pdf">PDF</button>
          </span>`
        : '<span class="hint">no documents</span>'}
      </div>`).join("");
    box.style.display = "";
    // Delegated: the list is re-rendered after every send.
    if (!list.dataset.wired) {
      list.dataset.wired = "1";
      list.addEventListener("click", (e) => {
        const b = e.target.closest(".rev-dl");
        if (b) downloadRevision(b.dataset.rev, b.dataset.kind, b);
      });
    }
  }

  /** Rebuild one revision's documents and download the requested one. Separate
   *  from the main downloadAs(): that one reads generate_result off the live draft,
   *  which is exactly what an old revision must NOT be rendered from. */
  async function downloadRevision(revNo, kind, button) {
    const draftId = TW.getDraftId();
    if (!draftId) return;
    const orig = button.textContent;
    button.disabled = true; button.textContent = "…";
    try {
      const out = await TW.postJSON(
        "/api/draft/" + encodeURIComponent(draftId) + "/revisions/" + encodeURIComponent(revNo) + "/files", {});
      const key = kind === "xlsx" ? "xlsx_download_url"
        : kind === "docx" ? "docx_download_url" : "pdf_download_url";
      const url = out && out[key];
      if (!url) throw new Error("That document isn't available for this revision.");
      const resp = await fetch(TW.absoluteUrl(url), { headers: TW.authHeaders() });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const safe = String((out.project_name || TW.getState().project_name || "proposal"))
        .replace(/[^A-Za-z0-9._-]+/g, "_").slice(0, 60);
      const ext = kind === "pdf" ? "pdf" : kind;
      const name = `${safe}_rev${revNo}_${kind === "xlsx" ? "estimate" : "proposal"}.${ext}`;
      // octet-stream so the browser saves under our name instead of letting the
      // inline PDF viewer hijack the click (same reason as the main downloads).
      const blobUrl = URL.createObjectURL(new Blob([await resp.arrayBuffer()],
                                                  { type: "application/octet-stream" }));
      const a = document.createElement("a");
      a.href = blobUrl; a.download = name;
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(blobUrl), 1500);
      button.textContent = "✓";
    } catch (err) {
      console.error("Revision download failed", err);
      button.textContent = "failed";
    }
    setTimeout(() => { button.textContent = orig; button.disabled = false; }, 1800);
  }

  // ── Assigned estimator ──────────────────────────────────────────────────────
  // Required at send: the assignee owns the follow-up cadence, gets the "not viewed"
  // and "make it personal" notes, and appears in their morning digest. Unassigned
  // means nobody chases it, which is the failure this whole system exists to fix.
  let _estimatorsPromise = null;

  // Names come from `profiles`, i.e. from whatever people typed into SSO — escape
  // before building option markup.
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  async function mountEstimatorPicker() {
    const sel = document.getElementById("portal-estimator");
    if (!sel) return;
    // Somebody may have assigned this project from the CRM drawer while this machine still held
    // an older copy of the blob — the full hydrate only runs for a DIFFERENT draft id, so that
    // change would otherwise be invisible here and the picker would read blank. Hanz, 2026-08-13:
    // "that estimator picker should also reflect in the Section 4 of the estimate."
    try { await TW.refreshServerOwned(); } catch {}
    let st = {};
    try { st = TW.getState() || {}; } catch {}
    // Memoised: showPostGenerate can run more than once per page.
    if (!_estimatorsPromise) {
      _estimatorsPromise = fetch(TW.absoluteUrl("/api/estimators"), { headers: TW.authHeaders() })
        .then(r => r.ok ? r.json() : { estimators: [] })
        .catch(() => ({ estimators: [] }));
    }
    const list = ((await _estimatorsPromise) || {}).estimators || [];
    const prev = String(st.assigned_estimator || "").toLowerCase();
    // A native <option> can't hold a coloured chip, so the initials ride in the label
    // instead — "KL · Kyle Loseke". Same names and the same initials as the chips
    // everywhere else; the colour is the one thing a select can't carry.
    sel.innerHTML = '<option value="">Choose the estimator…</option>'
      + list.map(e => `<option value="${esc(e.email)}">${esc(window.TWCrm.initialsOf(e.name || e.email))} · ${esc(e.name)}</option>`).join("");
    // A re-send remembers the last explicit choice, and so does a first send whose project was
    // assigned in the CRM — both are somebody's decision, which is the bar. What still starts
    // blank is a project nobody has assigned at all: the "Kyle?" guess on a card is the draft's
    // AUTHOR, not an assignment, and pre-selecting it would let one click promote a guess.
    if (prev && list.some(e => String(e.email).toLowerCase() === prev)) sel.value = prev;
    if (!list.length) {
      // Couldn't reach the list. Fail visibly rather than letting the send 400 with
      // a bare error the estimator can't act on.
      sel.innerHTML = '<option value="">Estimator list unavailable — reload the page</option>';
    }
  }

  const readAssignedEstimator = () =>
    (document.getElementById("portal-estimator") || {}).value || "";

  /** Who on the team hears about THIS send, chosen before pressing Send.
   *
   *  Hanz, 2026-08-19: "we need that notifcation sending selection in the Files. so we can select
   *  who receives it first." The Notification Sending page sets the standing default; this picks
   *  the exceptions for one job, next to the recipients it is being sent to.
   *
   *  HELD IN MEMORY, SENT WITH THE PUBLISH. Nothing is written when a chip is clicked, for a
   *  reason that is not stylistic: the per-project override table has a foreign key onto the
   *  proposal row, and on a FIRST send that row does not exist until the publish creates it — a
   *  write beforehand is refused by the portal. So the picks travel in the publish body and the
   *  portal applies them after it creates the row and before it decides who to notify. It also
   *  keeps the send a single request, which is what the flush-then-publish ordering depends on.
   *
   *  Deliberately NOT part of the draft blob: `refreshServerOwned` would overwrite in-progress
   *  picks, and this is a decision about one send rather than a property of the project. */
  // `isAdmin` / `me` decide which chips are toggleable — see paintNotifyChips. Both are filled in
  // from TWAuth when the roster loads; until then nothing is painted, so the defaults here only ever
  // apply to an unmounted control. Defaulting isAdmin to FALSE is the safe direction: the worst case
  // is a chip that looks read-only for a moment, not one that offers a change the server will refuse.
  const notifyPick = { roster: [], changed: {}, ready: false, isAdmin: false, me: "" };

  notifyPick.effective = (email) => {
    const person = notifyPick.roster.find(p => p.email.toLowerCase() === email.toLowerCase());
    if (!person) return false;
    const override = notifyPick.changed[email.toLowerCase()];
    return override === undefined ? person.base : override;
  };

  // Only what the estimator actually changed. Anybody left alone follows the roster, so an
  // untouched send forwards nothing and the request stays byte-for-byte the legacy one.
  notifyPick.adds = () => Object.keys(notifyPick.changed)
    .filter(e => notifyPick.changed[e] === true && !baseOf(e));
  notifyPick.mutes = () => Object.keys(notifyPick.changed)
    .filter(e => notifyPick.changed[e] === false && baseOf(e));

  function baseOf(email) {
    const person = notifyPick.roster.find(p => p.email.toLowerCase() === email.toLowerCase());
    return !!(person && person.base);
  }

  async function mountNotifyRoster() {
    const box = document.getElementById("notify-pick");
    const chips = document.getElementById("notify-pick-chips");
    if (!box || !chips) return;
    let list = [];
    try {
      const r = await fetch(TW.absoluteUrl("/api/portal/notify-recipients"),
                            { headers: TW.authHeaders() });
      const j = r.ok ? await r.json() : {};
      // 'general' only: a deposit-kind row is for deposit alerts, not for "we sent a proposal".
      list = (j.recipients || []).filter(x => x.kind === "general");
    } catch { list = []; }
    // Nobody configured, or the roster is unreachable: say nothing rather than showing an empty
    // control that implies the send tells no one. The standing roster still applies server-side.
    if (!list.length) { box.hidden = true; return; }
    notifyPick.roster = list.map(x => ({ email: x.email, base: x.enabled !== false }));
    // Whatever was chosen in the CRM drawer before this project was sent. That control writes the
    // draft (an unsent project has no portal row to override against), and this is the screen that
    // carries the decision into the send — so it has to open showing what was already decided
    // rather than silently discarding it.
    notifyPick.changed = {};
    try {
      const saved = (TW.getState() || {}).notify_picks || {};
      (saved.add || []).forEach(e => { notifyPick.changed[String(e).toLowerCase()] = true; });
      (saved.mute || []).forEach(e => { notifyPick.changed[String(e).toLowerCase()] = false; });
    } catch {}
    // Who is looking, so paintNotifyChips knows which chips they may touch. Read the same way the
    // Notification Sending page reads it, off TWAuth rather than from a role guessed here.
    try {
      const who = (window.TWAuth && window.TWAuth.user && window.TWAuth.user()) || {};
      notifyPick.me = String(who.email || "").toLowerCase();
      notifyPick.isAdmin = who.role === "admin" || who.role === "super_admin";
    } catch { notifyPick.isAdmin = false; notifyPick.me = ""; }
    notifyPick.ready = true;
    box.hidden = false;
    paintNotifyChips();
  }

  function paintNotifyChips() {
    const chips = document.getElementById("notify-pick-chips");
    const why = document.getElementById("notify-pick-why");
    if (!chips) return;
    const estimator = String(readAssignedEstimator() || "").toLowerCase();
    chips.innerHTML = notifyPick.roster.map(person => {
      const on = notifyPick.effective(person.email);
      // The assigned estimator hears about the job whether or not they sit on the roster (the
      // portal folds them in), so the chip says so instead of offering to add somebody who is
      // already coming. A mute still wins, so it stays clickable.
      const owns = person.email.toLowerCase() === estimator;
      // Only an admin may toggle somebody else, exactly as the Notification Sending page has always
      // had it — and now enforced server-side too, so an ungated chip would just 403. Rendered as a
      // plain span rather than a disabled button: a disabled control invites clicking and explains
      // nothing, and the sentence below says who may change what.
      const mayToggle = notifyPick.isAdmin || person.email.toLowerCase() === notifyPick.me;
      const cls = 'nt-chip' + ((on || owns) ? ' on' : '') + (mayToggle ? '' : ' nt-chip-ro');
      const label = '<span class="nt-av">' + esc(window.TWCrm.initialsOf(person.email)) + "</span>"
        + esc(window.TWCrm.nameOf(person.email));
      const title = esc(person.email + (owns ? " — owns this job, so always told" : "")
        + (mayToggle ? "" : " — only an admin can change this"));
      if (!mayToggle) return '<span class="' + cls + '" title="' + title + '">' + label + "</span>";
      return '<button type="button" class="' + cls + '"'
        + ' data-notify="' + esc(person.email) + '"'
        + ' title="' + title + '">' + label + "</button>";
    }).join("");
    if (why) {
      const n = notifyPick.roster.filter(p => notifyPick.effective(p.email)).length;
      const how = notifyPick.isAdmin ? "Click to change." : "You can change only your own.";
      why.textContent = n
        ? n + " of " + notifyPick.roster.length + " will be told this went out. " + how
        : "Nobody will be told this went out. " + how;
    }
  }

  // Delegated, because the chips are rebuilt whenever the estimator changes.
  document.addEventListener("click", (e) => {
    const chip = e.target.closest && e.target.closest("[data-notify]");
    if (!chip) return;
    const email = chip.getAttribute("data-notify").toLowerCase();
    const now = notifyPick.effective(email);
    // Back to the roster's own answer → forget the deviation entirely, so an untouched-in-effect
    // send sends nothing rather than an override that happens to agree.
    if (!now === baseOf(email)) delete notifyPick.changed[email];
    else notifyPick.changed[email] = !now;
    paintNotifyChips();
  });

  function readRequireDeposit() {
    const el = document.getElementById("portal-require-deposit");
    // Missing element (older cached page) → fall back to the audience default so a
    // Direct customer never silently loses their deposit requirement.
    if (el) return !!el.checked;
    try { return String((TW.getState() || {}).audience || "Direct").trim().toUpperCase() !== "GC"; }
    catch { return true; }
  }

  function mountPortalRecipients() {
    const box = document.getElementById("portal-recipients");
    if (!box) return;
    const st = TW.getState();
    const intake = String(st.contact_email || "").trim();
    portalRecip.intake = intake;
    portalRecip.hasIntake = !!intake && EMAIL_RE.test(intake);
    const saved = Array.isArray(st.portal_emails) ? st.portal_emails : [];
    portalRecip.extras = saved
      .map(e => String(e || "").trim())
      .filter(e => e && EMAIL_RE.test(e) && (!portalRecip.hasIntake || e.toLowerCase() !== intake.toLowerCase()));

    box.innerHTML =
      '<div class="tw-em-label">Recipients</div>' +
      '<div class="tw-em-list"></div>' +
      '<div class="tw-em-add"><input type="email" placeholder="Add another email — name@company.com" autocomplete="off">' +
      '<button type="button" class="tw-em-addbtn">Add</button></div>' +
      '<p class="tw-em-err"></p>';

    const listEl = box.querySelector(".tw-em-list");
    const addInput = box.querySelector(".tw-em-add input");
    const addBtn = box.querySelector(".tw-em-addbtn");
    const errEl = box.querySelector(".tw-em-err");

    const setErr = (m) => { errEl.textContent = m || ""; };
    const allEmails = () => (portalRecip.hasIntake ? [portalRecip.intake] : []).concat(portalRecip.extras);
    // Only the un-ticked ones that are actually being SENT to. An address removed after being
    // un-ticked, or an intake edited to something else, must not travel as an opt-out for a
    // recipient that no longer exists.
    portalRecip.noFollowupsToSend = () => {
      const on = allEmails();
      return portalRecip.noFollowups.filter((e) => on.indexOf(e) >= 0);
    };

    // The intake email starts locked (it came from the customer's lead). "Edit"
    // unlocks it inline so the estimator can retarget the send — e.g. to their own
    // address for a test. The edit is a TRANSIENT send-target override only: it
    // changes who this send goes to, and deliberately does NOT persist back to the
    // draft's contact_email, so a test send can never overwrite the customer's real
    // email of record (which also feeds the estimate sheet + portal identity).
    let editingIntake = false;
    let editInput = null;   // the live <input> while the intake row is being edited
    let intakeDraft = null; // typed-but-unsaved value, preserved across re-renders
    let editJustOpened = false; // focus the editor only on first open, not every rebuild
    let intakeEdited = false;   // once retargeted, the row is no longer the raw intake

    // Commit an edited intake address into the in-memory send target. Validates and
    // folds a duplicate extra into the intake slot. Does NOT touch contact_email —
    // the send uses the emails list, and persisting would corrupt customer data.
    // Returns true on success, false (+ inline error) on an invalid address so the
    // caller can block — the send guard relies on this.
    function saveIntake(val) {
      const v = String(val || "").trim();
      if (!EMAIL_RE.test(v)) { setErr("That doesn’t look like an email address."); return false; }
      const lc = v.toLowerCase();
      portalRecip.extras = portalRecip.extras.filter(e => e.toLowerCase() !== lc);
      portalRecip.intake = v;
      portalRecip.hasIntake = true;
      intakeEdited = true;
      editingIntake = false; editInput = null; intakeDraft = null; setErr(""); renderList();
      return true;
    }

    function renderList() {
      // Preserve an in-progress intake edit across incidental rebuilds (e.g. the
      // user adds/removes another recipient mid-edit) so Send can't silently revert
      // to the original address. A detached <input> keeps its .value.
      if (editingIntake && editInput) intakeDraft = editInput.value;
      listEl.textContent = "";
      const rows = (portalRecip.hasIntake ? [{ email: portalRecip.intake, fixed: true }] : [])
        .concat(portalRecip.extras.map(e => ({ email: e, fixed: false })));
      if (!rows.length) {
        const empty = document.createElement("div");
        empty.className = "tw-em-empty";
        empty.textContent = "No customer email on file — add one below.";
        listEl.appendChild(empty);
      }
      rows.forEach((r) => {
        // Hanz, 2026-08-13: "ccan you put the follow up checkbox to the right of edit outside
        // the container?" Each entry is a WRAPPER holding two things side by side: the bordered
        // row (email · tag · Edit/×) and, outside that border, the Follow-ups checkbox. The
        // checkbox is visibly not part of the recipient, which is the point — it is a decision
        // ABOUT the recipient, not one of its fields.
        const wrap = document.createElement("div");
        wrap.className = "tw-em-rowwrap";
        const row = document.createElement("div");
        row.className = "tw-em-row";

        // Intake row in edit mode: swap the locked label for an input + Save/Cancel.
        if (r.fixed && editingIntake) {
          const input = document.createElement("input");
          input.type = "email"; input.className = "em";
          input.value = (intakeDraft != null) ? intakeDraft : portalRecip.intake;
          input.setAttribute("aria-label", "Edit the recipient email");
          editInput = input;
          const save = document.createElement("button");
          save.type = "button"; save.className = "tw-em-editbtn"; save.textContent = "Save";
          const cancel = document.createElement("button");
          cancel.type = "button"; cancel.className = "tw-em-editbtn"; cancel.textContent = "Cancel";
          cancel.setAttribute("aria-label", "Cancel editing");
          const cancelEdit = () => { editingIntake = false; editInput = null; intakeDraft = null; setErr(""); renderList(); };
          save.addEventListener("click", () => saveIntake(input.value));
          cancel.addEventListener("click", cancelEdit);
          input.addEventListener("input", () => { intakeDraft = input.value; });
          input.addEventListener("keydown", (e) => {
            if (e.key === "Enter") { e.preventDefault(); saveIntake(input.value); }
            else if (e.key === "Escape") { e.preventDefault(); cancelEdit(); }
          });
          row.appendChild(input); row.appendChild(save); row.appendChild(cancel);
          // No Follow-ups control while the address is being edited: the checkbox belongs to a
          // recipient, and mid-edit there is not a settled one to attach it to.
          wrap.appendChild(row);
          listEl.appendChild(wrap);
          // Focus only when the editor first opens — not on every incidental rebuild,
          // which would otherwise steal focus + reselect while the user is elsewhere.
          if (editJustOpened) { editJustOpened = false; setTimeout(() => { input.focus(); input.select(); }, 0); }
          return;
        }

        const em = document.createElement("span");
        em.className = "em"; em.textContent = r.email;
        row.appendChild(em);

        // Follow-ups for THIS contact. On the intake row too: the person the lead came from is
        // exactly who somebody might not want chased four times.
        const fu = document.createElement("label");
        fu.className = "tw-em-fu";
        fu.title = "Automated follow-up emails. Un-tick and this contact still gets the proposal, "
                 + "the invoice and every reply — just not the chasing.";
        const fuBox = document.createElement("input");
        fuBox.type = "checkbox";
        fuBox.checked = portalRecip.noFollowups.indexOf(r.email) < 0;
        fuBox.addEventListener("change", () => {
          const k = portalRecip.noFollowups.indexOf(r.email);
          if (fuBox.checked) { if (k >= 0) portalRecip.noFollowups.splice(k, 1); }
          else if (k < 0) portalRecip.noFollowups.push(r.email);
        });
        fu.appendChild(fuBox);
        fu.appendChild(document.createTextNode(" Follow-ups"));
        // NOT row.appendChild — it goes on the wrapper, after the row closes, so it renders
        // outside the bordered container and to the right of Edit.

        if (r.fixed) {
          const tag = document.createElement("span");
          tag.className = "tw-em-tag"; tag.textContent = intakeEdited ? "custom" : "intake";
          row.appendChild(tag);
          const edit = document.createElement("button");
          edit.type = "button"; edit.className = "tw-em-editbtn"; edit.textContent = "Edit";
          edit.setAttribute("aria-label", "Edit this recipient email to send to a different address");
          edit.addEventListener("click", () => {
            editingIntake = true; intakeDraft = portalRecip.intake; editJustOpened = true; setErr(""); renderList();
          });
          row.appendChild(edit);
        } else {
          const x = document.createElement("button");
          x.type = "button"; x.className = "tw-em-x"; x.textContent = "\u00d7";
          x.setAttribute("aria-label", "Remove " + r.email);
          x.addEventListener("click", () => {
            const k = portalRecip.extras.indexOf(r.email);
            if (k >= 0) portalRecip.extras.splice(k, 1);
            // Drop any opt-out with it. Otherwise removing an address and adding it back gives a
            // ticked box that is a lie: the stale entry would still suppress its follow-ups.
            const f = portalRecip.noFollowups.indexOf(r.email);
            if (f >= 0) portalRecip.noFollowups.splice(f, 1);
            setErr(""); renderList();
          });
          row.appendChild(x);
        }
        wrap.appendChild(row);
        wrap.appendChild(fu);      // outside the border, right of Edit / ×
        listEl.appendChild(wrap);
      });
    }

    // Add whatever is typed. Returns false (+ shows an error) on invalid residual
    // text so the send can block instead of silently dropping it.
    function tryAdd() {
      const v = addInput.value.trim();
      if (!v) return true;
      if (!EMAIL_RE.test(v)) { setErr("That doesn\u2019t look like an email address."); return false; }
      const lc = v.toLowerCase();
      if (allEmails().some(e => e.toLowerCase() === lc)) { setErr("That email is already in the list."); return false; }
      if (allEmails().length >= MAX_PORTAL_EMAILS) { setErr("Maximum " + MAX_PORTAL_EMAILS + " recipients."); return false; }
      portalRecip.extras.push(v); addInput.value = ""; setErr(""); renderList(); addInput.focus();
      return true;
    }

    addBtn.addEventListener("click", () => tryAdd());
    addInput.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); tryAdd(); } });

    portalRecip.allEmails = allEmails;
    portalRecip.tryAdd = tryAdd;
    // Flush a pending intake edit before a send, so clicking "Send" without first
    // clicking "Save" still uses the edited address (returns false to block on an
    // invalid in-progress edit).
    portalRecip.commitEdit = () => (!editingIntake) ? true : saveIntake(editInput ? editInput.value : portalRecip.intake);
    portalRecip.setErr = setErr;
    portalRecip.setBusy = (b) => { addInput.disabled = addBtn.disabled = !!b; };
    portalRecip.ready = true;
    renderList();
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

  /** The files going out WITH this proposal.
   *
   *  Held in the browser until Send, unlike the chat's attachments which upload the moment they
   *  are picked. That difference is forced: the chat always has a proposal row to hang an upload
   *  off, and a first send does not have one until the publish creates it.
   *
   *  So the cost is paid at Send instead — which is why the total is capped at 10 MB and said out
   *  loud on the page. Resend would take four times that; the customer's own mail server is the
   *  one that would bounce it, and they would find out from the customer.
   */
  const sendAtts = (() => {
    const MAX_TOTAL = 10 * 1024 * 1024;
    const MAX_ONE = 15 * 1024 * 1024;
    let items = [];
    const size = (n) => (n < 1024 ? n + " B"
      : n < 1024 * 1024 ? Math.round(n / 1024) + " KB"
      : (n / 1024 / 1024).toFixed(n < 10 * 1024 * 1024 ? 1 : 0) + " MB");
    const total = () => items.reduce((a, b) => a + (b.size || 0), 0);

    function draw() {
      const strip = document.getElementById("send-atts");
      const note = document.getElementById("send-att-note");
      if (!strip) return;
      strip.innerHTML = items.map((a, i) => `
        <span class="att-chip">
          ${a.preview ? `<img src="${a.preview}" alt="">` : ""}
          <span class="att-name"></span>
          <span class="att-size">${size(a.size)}</span>
          <button type="button" class="att-x" data-att-remove="${i}" aria-label="Remove">&times;</button>
        </span>`).join("");
      // Names go in as TEXT, never as markup: a filename is the one string on this page that
      // came from outside it.
      strip.querySelectorAll(".att-name").forEach((el, i) => { el.textContent = items[i].name; });
      strip.hidden = !items.length;
      if (note) {
        note.textContent = items.length
          ? `${items.length} file${items.length > 1 ? "s" : ""} · ${size(total())} of 10 MB`
          : "";
      }
    }

    function add(files) {
      for (const f of Array.from(files || [])) {
        if (items.length >= 10) break;
        if (f.size > MAX_ONE) { alert(`${f.name} is larger than 15 MB.`); continue; }
        if (total() + f.size > MAX_TOTAL) {
          alert(`${f.name} would take this over 10 MB. Send the large files in the chat instead — `
                + `the customer gets them the same way, without risking the email bouncing.`);
          continue;
        }
        const image = /^image\//.test(f.type || "");
        items.push({ file: f, name: f.name || "attachment", size: f.size,
                     mime: f.type || "application/octet-stream",
                     preview: image ? URL.createObjectURL(f) : "" });
      }
      draw();
    }

    document.addEventListener("click", (e) => {
      if (e.target.closest("#send-attach")) {
        e.preventDefault();
        const inp = document.getElementById("send-file");
        if (inp) inp.click();
        return;
      }
      const rm = e.target.closest("#send-atts [data-att-remove]");
      if (!rm) return;
      const i = Number(rm.dataset.attRemove);
      if (items[i] && items[i].preview) URL.revokeObjectURL(items[i].preview);
      items.splice(i, 1);
      draw();
    });
    const inp = document.getElementById("send-file");
    if (inp) inp.addEventListener("change", (e) => { add(e.target.files); e.target.value = ""; });

    return {
      /** Read every file as base64, in parallel, at Send time.
       *
       *  Not at pick time: an estimator who attaches four photos and then removes three should
       *  not have paid to encode all four, and holding the encoded copies as well as the File
       *  objects doubles the memory for no gain.
       */
      payload: () => Promise.all(items.map((a) => new Promise((res) => {
        const r = new FileReader();
        r.onload = () => res({ name: a.name, mime: a.mime,
                               // readAsDataURL gives "data:<mime>;base64,<data>" — the server
                               // wants the data only.
                               b64: String(r.result || "").split(",")[1] || "" });
        r.onerror = () => res(null);
        r.readAsDataURL(a.file);
      }))).then((all) => all.filter(Boolean)),
      clear: () => {
        items.forEach((a) => { if (a.preview) URL.revokeObjectURL(a.preview); });
        items = [];
        draw();
      },
      count: () => items.length,
    };
  })();

  /** The two halves of THIS project's pricing, read out of the draft the browser is holding.
   *
   *  A DELIBERATE MIRROR of `_publish_digest` in backend/main.py. That function decides what a
   *  customer was quoted, from the blob the publish route snapshots; this one reaches the same
   *  verdict from the same fields, in the same shape, BEFORE any request goes out. Same keys,
   *  same `show !== false` option rule, same base-only fallback, so the pre-send check and the
   *  post-send check can share one comparison and cannot disagree about what counts as drift.
   *
   *  IT READS `proposal_payload.rooms`, NOT `proposal_payload.values.rooms`. The first is what
   *  the document renderer prints; the second is an inert echo of the page state that travels
   *  alongside it. Reading the echo would report the pricing the estimator was LOOKING at
   *  instead of the pricing the customer's PDF prints, which is this bug wearing a disguise.
   *  backend/tests/test_publish_race.py pins the server side of the pair. */
  function localPublishDigest(s) {
    const st = (s && typeof s === "object") ? s : {};
    const list = (v) => (Array.isArray(v) ? v : []);
    const baseOf = (rs) => rs.find(r => r && typeof r === "object" && r.is_base) || {};
    // Only the options a customer can actually pick. An option the estimator deliberately hid
    // reaches neither the portal nor the document, so counting it here would cry drift on a
    // correct send, and a warning that fires on correct sends is one nobody reads.
    const opts = (rs) => rs.filter(r => r && typeof r === "object"
                                     && !r.is_base && r.show !== false).length;
    const num = (v) => (typeof v === "number" && isFinite(v)) ? v : null;

    const rooms = list(st.rooms);
    const pp = (st.proposal_payload && typeof st.proposal_payload === "object")
      ? st.proposal_payload : {};
    const pv = (pp.values && typeof pp.values === "object") ? pp.values : null;
    const prooms = list(pp.rooms);
    const pbase = baseOf(prooms);
    // The base room's own total, falling back to the payload's mirror of the lump sum: a
    // base-only proposal carries no rooms at all (rooms exist only once there is an option).
    let docLump = num(pbase.bid && typeof pbase.bid === "object" ? pbase.bid.total : null);
    if (docLump == null) docLump = num(pv ? pv.proposal_lump_sum : null);

    return {
      base_label: baseOf(rooms).name || null,
      lump_sum: num(st.proposal_lump_sum),
      option_count: opts(rooms),
      // False on a project that has never been through the Proposal step. There is no document
      // to be stale, so every check downstream stays silent instead of blocking a first send.
      has_document: !!pv,
      doc_base_label: pbase.name || null,
      doc_lump_sum: docLump,
      doc_option_count: prooms.length ? opts(prooms) : (pv ? 0 : null),
    };
  }

  /** What the DOCUMENT half of a digest gets wrong, one row per difference, or [] when it
   *  agrees. `{ k: "Price", pdf: "$13,265", now: "$18,670", say: "a price of $13,265, not …" }`
   *  — the first three for the panel's three columns, `say` for the one-line warning, so the
   *  prose and the table can never quote different figures at each other.
   *
   *  ONE COMPARISON, THREE CALLERS: the pre-send gate (fed a digest of local state), the
   *  post-send warning (fed the server's own snapshot), and the panel that renders either.
   *  A second copy of these three rules is how the two checks would start disagreeing about
   *  whether a send is safe.
   *
   *  Silent on anything it cannot read. An absent doc figure is not evidence of drift, and
   *  every revision minted before this existed carries none of these keys. */
  function docDriftRows(d) {
    if (!d || typeof d !== "object" || !d.has_document) return [];
    // TW.fmtUsd, not the `money` in mountRevisions — that one is scoped to its own function,
    // and reaching for it here would be a ReferenceError at the moment somebody most needs
    // to be told their customer is about to get the wrong price.
    const usd = (n) => (window.TW && TW.fmtUsd) ? TW.fmtUsd(n) : String(n);
    const near = (a, b) => (a == null || b == null) ? a === b
      : Math.abs(Number(a) - Number(b)) < 0.01;   // sub-cent is the same money, not drift
    const rows = [];
    // Price first: it is the number a customer signs. BOTH figures have to be there — a page
    // that has somehow lost its own lump sum is not evidence that the document is wrong, and
    // refusing the send over it would put "not $—" on the estimator's screen.
    if (d.doc_lump_sum != null && d.lump_sum != null && !near(d.doc_lump_sum, d.lump_sum)) {
      const pdf = usd(d.doc_lump_sum), now = usd(d.lump_sum);
      rows.push({ k: "Price", pdf: pdf, now: now, say: "a price of " + pdf + ", not " + now });
    }
    // A base-only document has no base ROOM, so doc_base_label is null on the most common
    // shape this tool produces. Comparing that against a real name would warn on every one.
    if (d.doc_base_label && d.base_label && d.doc_base_label !== d.base_label) {
      rows.push({ k: "Base bid", pdf: d.doc_base_label, now: d.base_label,
                  say: d.doc_base_label + " as the base bid, not " + d.base_label });
    }
    if (typeof d.doc_option_count === "number" && typeof d.option_count === "number"
        && d.doc_option_count !== d.option_count) {
      const n = d.doc_option_count;
      rows.push({ k: "Options", pdf: String(n), now: String(d.option_count),
                  say: n + " option" + (n === 1 ? "" : "s") + ", not " + d.option_count });
    }
    return rows;
  }

  /** Put the stop sign on screen, or take it away.
   *
   *  `mode` only changes the opening line, and the opening line is the whole point: the same
   *  three numbers mean "do not send this" before a send and "the customer already has this"
   *  after one, and an estimator reading it at 11pm should not have to work out which. */
  function showStaleDoc(rows, mode) {
    const box = document.getElementById("stale-doc");
    if (!box) return;
    if (!rows || !rows.length) { box.hidden = true; return; }
    const lede = document.getElementById("stale-doc-lede");
    if (lede) {
      lede.textContent =
        mode === "blocked" ? "Nothing was sent. Your changes are saved, but the document the "
                           + "customer would open was built before them."
      : mode === "sent"    ? "This one has already gone to the customer, and the document they "
                           + "can open was built before this pricing."
      :                      "Your changes are saved, but the document the customer would open "
                           + "was built before them. Sending now gives them the old figures.";
    }
    const tab = document.getElementById("stale-doc-rows");
    if (tab) {
      tab.textContent = "";
      // textContent throughout, never markup: a base bid's name is a worksheet label the
      // estimator typed, which makes it the one string in this panel from outside the page.
      const cell = (cls, text) => {
        const el = document.createElement("span");
        el.className = cls;
        el.textContent = text;
        tab.appendChild(el);
      };
      cell("sd-h", "");
      cell("sd-h", "The PDF says");
      cell("sd-h", "It should say");
      rows.forEach((r) => { cell("sd-k", r.k); cell("sd-was", r.pdf); cell("sd-now", r.now); });
    }
    box.hidden = false;
    if (mode === "blocked" || mode === "sent") {
      try { box.scrollIntoView({ block: "center", behavior: "smooth" }); } catch {}
    }
  }

  /** Compare the pricing the server just SENT against the pricing this page is showing.
   *  Returns a human sentence naming the difference, or "" when they agree.
   *
   *  The publish flush closes the same-tab race. This closes the rest: a second tab, another
   *  device, a colleague editing while you send. Only ever warns — the send has already
   *  happened and the portal is pinned, so the useful thing is to say WHAT differs.
   *
   *  Compares base label + lump sum + how many options a customer can pick, because those
   *  are the three things a wrong version gets wrong in a way that costs money. */
  function publishDrift(sent) {
    if (!sent || typeof sent !== "object") return "";     // older backend — nothing to compare
    const s = TW.getState() || {};
    const rooms = Array.isArray(s.rooms) ? s.rooms : [];
    const localBase = (rooms.find(r => r && r.is_base) || {}).name || null;
    const localOpts = rooms.filter(r => r && !r.is_base && r.show !== false).length;
    const localLump = s.proposal_lump_sum;
    const bits = [];
    if (sent.base_label && localBase && sent.base_label !== localBase) {
      bits.push("the base bid sent was " + sent.base_label + ", not " + localBase);
    }
    // TW.fmtUsd, not the local `money` in mountRevisions — that one is scoped to its own
    // function, and reaching for it here would be a ReferenceError at the moment somebody
    // most needs the warning.
    const usd = (n) => (window.TW && TW.fmtUsd) ? TW.fmtUsd(n) : String(n);
    const near = (a, b) => (a == null || b == null) ? a === b : Math.abs(Number(a) - Number(b)) < 0.01;
    if (!near(sent.lump_sum, localLump)) {
      bits.push("the price sent was " + usd(sent.lump_sum) + ", not " + usd(localLump));
    }
    if (typeof sent.option_count === "number" && sent.option_count !== localOpts) {
      bits.push("it sent " + sent.option_count + " option" + (sent.option_count === 1 ? "" : "s")
                + ", not " + localOpts);
    }
    // ── The DOCUMENT half of the same snapshot ────────────────────────────────────────────
    // BELT AND BRACES, AND BOTH ARE NEEDED. The pre-send gate in the Send handler refuses a
    // drifted publish before a request leaves this browser, and the server refuses one that
    // gets past it. This is the third layer: it reads the snapshot the server ACTUALLY took,
    // so it still speaks up when the drift arrived between the flush and the write, or from a
    // second tab, another device, or a colleague editing while you sent. The gate cannot see
    // any of those, and a send that lands drifted must never land silently.
    //
    // The rows come from the same docDriftRows the gate and the panel use, so what a warning
    // calls drift and what a gate calls drift can never come apart.
    const rows = docDriftRows(sent);
    if (rows.length) {
      bits.push("the PDF they can open was built before this pricing, and shows "
                + rows.map(r => r.say).join(", and ")
                + ". Press Update the PDF above, then send it again");
    }
    return bits.join("; ");
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

    // Carry the draft across so the info sheet opens on THIS project rather than
    // whichever one the browser last held.
    const infoLink = document.getElementById("info-sheet-link");
    if (infoLink) infoLink.href = TW.withDraft("/info-sheet.html");

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

    // Send to the inline recipient list shown above (no popup). Every recipient
    // gets a secure link + full portal access (view / ask / approve).
    mountPortalRecipients();
    // Restore a previously-typed customer message (so a re-send keeps it).
    const _msgEl = document.getElementById("portal-message");
    if (_msgEl) { try { _msgEl.value = TW.getState().portal_message || ""; } catch {} }
    mountRequireDeposit();
    // Awaited so the chips can mark whoever ends up assigned as already-included; the estimator
    // picker is what decides that, and it resolves the roster from the server.
    mountEstimatorPicker().then(paintNotifyChips).catch(() => {});
    mountNotifyRoster();
    // Changing the estimator changes who is implicitly told, so the chips follow the select.
    const _estSel = document.getElementById("portal-estimator");
    if (_estSel) _estSel.addEventListener("change", paintNotifyChips);
    mountRevisions();
    // Look at the document BEFORE the estimator has typed a message or picked recipients. The
    // gate on the Send button is the thing that actually refuses; this is only so the news does
    // not arrive as a surprise at the last click, and so the one button that fixes it is on
    // screen from the moment the page settles.
    try { showStaleDoc(docDriftRows(localPublishDigest(TW.getState())), "mount"); } catch {}
    const fixBtn = document.getElementById("stale-doc-fix");
    if (fixBtn) {
      fixBtn.addEventListener("click", () => {
        // THE PROPOSAL STEP IS WHERE THE FIX LIVES, and it cannot be done from here. The
        // document payload is written by exactly one line of code, in that step's Continue
        // handler, from machinery that only exists on that page: computeTokenValues, the
        // paragraph and box overrides, the system picks. Re-deriving any of it here would be a
        // second copy of the token mapping, which is how the two halves drifted in the first
        // place. So this takes them there, one press, carrying the draft id.
        //
        // `resync=1` is the hook for making that step's Continue run by itself, so this becomes
        // one press end to end. Nothing reads it yet: it is a query parameter proposal-review
        // ignores, and it costs nothing to send until that half is approved.
        window.location.assign(TW.withDraft("/proposal-review.html?resync=1"));
      });
    }
    const portalBtn = document.getElementById("portal-btn");
    if (portalBtn) {
      portalBtn.addEventListener("click", async () => {
        const requireDeposit = readRequireDeposit();
        const assignedEstimator = readAssignedEstimator();
        const draftId = TW.getDraftId();
        if (!draftId) { alert("Save the project first (open it from Projects), then send."); return; }
        if (portalRecip.commitEdit && !portalRecip.commitEdit()) return;   // flush a pending intake edit
        if (portalRecip.tryAdd && !portalRecip.tryAdd()) return;   // invalid residual text blocks the send
        const emails = portalRecip.allEmails ? portalRecip.allEmails() : [];
        if (!emails.length) { if (portalRecip.setErr) portalRecip.setErr("Add at least one recipient email."); return; }
        if (!assignedEstimator) {
          if (portalRecip.setErr) portalRecip.setErr("Choose the assigned estimator before sending.");
          const sel = document.getElementById("portal-estimator");
          if (sel) sel.focus();
          return;
        }
        const orig = portalBtn.textContent;
        portalBtn.disabled = true; portalBtn.textContent = "Sending\u2026";
        if (portalRecip.setBusy) portalRecip.setBusy(true);
        if (portalRecip.setErr) portalRecip.setErr("");
        const msgEl = document.getElementById("portal-message");
        const message = (msgEl && msgEl.value || "").trim();
        try {
          // WAIT for this page's edits to reach the server before publishing. The publish
          // route snapshots the SERVER's copy of the draft (main.py create_revision) and the
          // portal pins the customer's view to that snapshot for good — so a debounced save
          // still in flight means the customer is shown the version BEFORE the change that
          // prompted the send.
          //
          // Hanz, 2026-08-13, on a resend of "Hanz Company 123": "I have made changes and
          // resent the proposal but the new proposal does not appear correctly." Revision 2
          // was stamped 16:00:28 with base_tab_id=Epoxy; his draft said Room 1 at 16:02:14.
          // The portal showed the old base, the PDF (built from the live draft) showed the
          // new one, and neither was wrong — the send had simply raced the autosave.
          portalBtn.textContent = "Saving your changes…";
          if (!await TW.flushState()) {
            throw new Error("Couldn't save your latest changes, so nothing was sent — "
                            + "check your connection and try again.");
          }
          // ── THE SEND STOPS HERE IF THE PDF WOULD BE THE OLD ONE ──────────────────────
          // Checked AFTER the flush and BEFORE the publish, and that order is the whole
          // trick. The flush has just made this browser's blob and the server's copy the
          // same blob, so a verdict taken now is a verdict about what the publish would
          // snapshot — no extra round trip, and nothing to read that the page does not
          // already hold. Both halves are in that blob: `rooms` is what the customer's
          // portal page renders, `proposal_payload` is what their PDF is rebuilt from.
          //
          // Until now this was only ever caught AFTERWARDS, from the publish response, by
          // which point the email had gone and the revision was pinned. A teammate hit it
          // at 11:47pm and could not tell what the yellow message meant, which is fair: it
          // was an apology with a four-step manual dance attached. Refusing costs a send
          // that was going to be wrong anyway.
          const stale = docDriftRows(localPublishDigest(TW.getState()));
          if (stale.length) {
            showStaleDoc(stale, "blocked");
            portalBtn.disabled = false; portalBtn.textContent = orig;
            if (portalRecip.setBusy) portalRecip.setBusy(false);
            const fix = document.getElementById("stale-doc-fix");
            if (fix) fix.focus();
            return;                            // NOTHING is posted. No portal row, no email.
          }
          portalBtn.textContent = "Sending…";
          // AWAITED, and read here rather than at pick time: an estimator who attaches four
          // photos and removes three should not have paid to encode all four, and holding the
          // encoded copies alongside the File objects doubles the memory for nothing.
          const attachments = await sendAtts.payload();
          const j = await TW.postJSON("/api/portal/publish?draft_id=" + encodeURIComponent(draftId),
                                      { emails, message, require_deposit: requireDeposit,
                                        // They travel in this body rather than being uploaded
                                        // first because on a FIRST send the portal proposal row
                                        // does not exist until this request creates it — there is
                                        // nothing yet for an upload to hang off.
                                        attachments,
                                        assigned_estimator: assignedEstimator,
                                        // Which of those contacts should not be chased. Filtered
                                        // to the addresses actually being sent to, so a removed
                                        // or retargeted one cannot travel as a stale opt-out.
                                        no_followups: portalRecip.noFollowupsToSend(),
                                        // Which STAFF hear about this send — only the deviations
                                        // from the standing roster, so an untouched send carries
                                        // nothing and behaves exactly as it always has.
                                        notify_add: notifyPick.adds(),
                                        notify_mute: notifyPick.mutes() });
          if (j && j.ok === false) throw new Error(j.error || j.detail || "Send failed.");
          // Only now. Clearing before the request would lose the files on a failed send and leave
          // the estimator re-picking them with no idea they had gone.
          sendAtts.clear();
          // Remember both for a re-send. require_deposit persists so a deliberate
          // GC-with-deposit (or Direct-without) choice survives a reload instead of
          // snapping back to the audience default.
          TW.setState({ portal_message: message, require_deposit: requireDeposit,
                        assigned_estimator: assignedEstimator });
          // Persist only the EXTRAS (never the intake row) so they pre-fill next time.
          // The intake is restored from contact_email on the next mount; persisting it
          // here would re-add an edited/retargeted intake as a stray extra on reload.
          const persistExtras = emails.filter(e => !portalRecip.hasIntake || e.toLowerCase() !== String(portalRecip.intake || "").toLowerCase());
          TW.setState({ portal_emails: persistExtras });
          if (portalRecip.setBusy) portalRecip.setBusy(false);
          portalBtn.textContent = "\u2713 Sent to customer portal";
          mountRevisions();   // the send just created a new version \u2014 show it
          const r = document.getElementById("portal-result");
          if (r) {
            r.style.display = "";
            r.textContent = "";
            // NO LINK AND NO RECIPIENT LIST. Removed on Hanz's ask (2026-08-26). The URL is a
            // secret token that opens the customer's proposal, and there is no reason for it to
            // sit on screen after a send — the CRM drawer copies it on demand when somebody
            // actually wants it. "Sent to customer portal" on the button is the confirmation.
            //
            // The element stays, because the DRIFT WARNING below still needs somewhere to land,
            // and that one must never be dropped: it is the only thing that says the customer
            // received different numbers from the ones on this screen.
            const drift = publishDrift(j.sent_snapshot);
            if (drift) {
              const w = document.createElement("p");
              w.className = "portal-drift";
              w.textContent = "This one has gone to the customer, and it is not what this "
                + "page is showing: " + drift + ".";
              r.appendChild(w);
              // And raise the panel on the server's OWN numbers, so a send that landed
              // drifted offers the same one press as one that was stopped. The paragraph is
              // the notice; the panel is the way out of it.
              showStaleDoc(docDriftRows(j.sent_snapshot), "sent");
            }
          }
          setTimeout(() => { portalBtn.textContent = "\u2197 Re-send to customer portal"; portalBtn.disabled = false; }, 2500);
        } catch (err) {
          portalBtn.disabled = false; portalBtn.textContent = orig;
          if (portalRecip.setBusy) portalRecip.setBusy(false);
          const msg = portalErrMsg(err);
          if (portalRecip.setErr) portalRecip.setErr(msg === "no_contact_email"
            ? "This proposal has no customer email — add a recipient above." : msg);
        }
      });
    }

    document.getElementById("restart-btn").addEventListener("click", () => {
      TW.clearState();
      window.location.assign("/?new=1");   // start a fresh project (home is Projects)
    });
  }
