// Externalized from proposal-review.html (CSP: drop script-src 'unsafe-inline'). Do not add inline scripts.
  const state = TW.getState();
  if (!state.project_name) {
    document.querySelector(".word-canvas").innerHTML = `
      <div style="background:white;padding:40pt 30pt;border-radius:4px;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,0.15);">
        <h1 style="color:#605e5c;">No project started</h1>
        <p>Start an intake first to enable the Proposal step.</p>
        <a href="/?edit=1" style="background:#2b579a;color:white;text-decoration:none;padding:8px 16px;border-radius:2px;">← Go to Intake</a>
      </div>
    `;
    throw new Error("proposal-review: no project in state");
  }

  const form = document.getElementById("proposal-form");
  TW.writeForm(form, state);

  // Bind the ribbon action before document-template initialization. The
  // function declaration below is hoisted, so this remains safe while ensuring
  // a template-load failure cannot leave the visible Continue button inert.
  const earlyGenerateBtn = document.getElementById("generate-btn");
  if (earlyGenerateBtn) earlyGenerateBtn.onclick = continueToDone;

  /** Why the estimator is standing on this page.
   *
   *  The Files page refuses a send whose PDF is older than the pricing and offers one button,
   *  "Update the PDF", which lands here with `?resync=1`. This says what that button was about,
   *  in the same words and with the same figures, because somebody who followed a control across
   *  a page boundary should not have to remember what the last page told them.
   *
   *  IT DOES NOT PRESS CONTINUE FOR THEM, and that is the design, not a shortcut not yet taken.
   *  Auto-submitting and bouncing them back to Files would hand the customer a document nobody
   *  had looked at, which is the same failure this whole fix exists to stop, wearing better
   *  clothes. Landing here is CORRECT precisely because the document is on the screen. So:
   *  Continue is focused and named, never fired.
   *
   *  The comparison itself is TW.docDrift, the same function the Files page gates the send on.
   *  A second copy here would be exactly the two-halves-of-one-truth mistake that caused the
   *  bug in the first place. */
  (function explainWhyYouAreHere() {
    let armed = false;
    try { armed = new URLSearchParams(location.search).get("resync") === "1"; } catch { return; }
    if (!armed) return;
    const note = document.getElementById("resync-note");
    const what = document.getElementById("resync-note-what");
    if (!note || !what) return;

    const paint = () => {
      // Fresh, never the module's one-shot `state` snapshot: this runs during init and again
      // after the draft settles, and the whole point is to read what is true NOW.
      const rows = TW.docDrift(TW.publishDigest(TW.getState()));
      if (!rows.length) { note.hidden = true; return; }   // already fixed, or nothing to fix
      what.textContent = "It shows " + rows.map(r => r.say).join(", and ") + ".";
      note.hidden = false;
      // Named in the copy AND focused, so a keyboard user is already on it. Belt and braces:
      // the doc-template init below can take the focus back, and if it does the sentence still
      // says which button to press.
      const go = document.getElementById("generate-btn");
      if (go) { try { go.scrollIntoView({ block: "nearest" }); go.focus(); } catch {} }
    };

    paint();
    // Init reads localStorage synchronously, but a draft arriving from the server a moment later
    // can change both halves. Repaint rather than leave a figure on screen that has moved.
    try { if (TW.draftReady && TW.draftReady.then) TW.draftReady.then(paint).catch(() => {}); }
    catch {}
  })();

  // The "Proposal fields" sidebar is hidden (redundant with inline editing), but
  // tax treatment has no inline equivalent and drives the price line, so a
  // compact selector lives in the ribbon. Mirror it into the hidden form's
  // tax_inclusion field and fire a bubbling 'input' so the form's existing
  // listeners (refreshPriceDisplay + debounced persist) run — no duplicated logic.
  (function wireRibbonTax() {
    const sel = document.getElementById("tax-treatment-select");
    const hidden = form && form.querySelector("[name='tax_inclusion']");
    if (!sel || !hidden) return;
    const norm = (v) => {
      const u = String(v || "INCLUDED").trim().toUpperCase();
      if (["EXCLUDED", "EXEMPT", "NOT INCLUDED", "NONE", "NO", "N/A"].includes(u)) return "EXEMPT";
      if (["BROKEN_OUT", "BROKEN OUT", "BROKENOUT", "ITEMIZED", "BREAKOUT"].includes(u)) return "BROKEN_OUT";
      return "INCLUDED";
    };
    sel.value = norm(hidden.value);                       // reflect the saved/default treatment
    sel.addEventListener("change", () => {
      hidden.value = sel.value;
      hidden.dispatchEvent(new Event("input", { bubbles: true }));   // → form input listeners
    });
  })();

  // Proposal boilerplate as REAL default values (these used to be placeholders,
  // which never made it into the generated doc — that's why Schedule came out
  // blank). writeForm above already applied any saved / AI-autofilled values, so
  // we only fill fields that are still blank: autofill and manual edits win, but
  // a proposal generated without autofill still carries the standard text.
  const _wt = (state.work_type || "epoxy").toLowerCase();
  const _audience = state.audience || "Direct";
  // The gyp base tab id (must match estimate-review.js GYP_BASE) — the default
  // priced base for gyp jobs; other gyp variants are options.
  const GYP_BASE = 'Gyp (USG 1-8")';

  // ─── Phase B: the base-bid tab's ROLE drives the whole proposal ─────────
  // The estimator can pick which sheet is the base bid on this screen. When the
  // chosen base is a DIFFERENT work type than the intake `work_type` (e.g. a
  // polish sheet on an epoxy job), the ENTIRE proposal should follow the base —
  // template + artwork, area/noun, scope/schedule/exclusions, notes, and the
  // generate payload — so we're "really pulling the right data" (Hanz).
  //   • combo stays "combo" (the base switch there picks which sub-bid LEADS,
  //     handled inside the combo layout — the template itself doesn't change).
  //   • No explicit base, or a role we don't render (sealer/leveling) → fall
  //     back to the intake work_type (byte-identical to the old behavior).
  // `state` is a live object (the base radios mutate state.base_tab_id in place),
  // so this re-resolves correctly whenever it's called.
  function effectiveWorkType() {
    const wt = (state.work_type || "epoxy").toLowerCase();
    if (wt === "combo") return "combo";
    const all = Array.isArray(state.priced_tabs) ? state.priced_tabs : [];
    const base = state.base_tab_id ? all.find(t => t && t.id === state.base_tab_id) : null;
    const role = base && base.role ? String(base.role).toLowerCase() : "";
    return (role === "epoxy" || role === "polish" || role === "gyp") ? role : wt;
  }
  // The effective work type currently reflected on screen — reloadForWorkType()
  // compares against this to know when a base switch actually changed the type.
  let _lastEffWt = effectiveWorkType();

  // ─── Audience + work-type narrative catalog ─────────────────────────
  // Scope/Schedule/Exclusions boilerplate. These strings are BYTE-IDENTICAL to
  // the backend fallbacks in backend/main.py (_DEFAULT_SCOPE_*/_DEFAULT_SCHEDULE*/
  // _DEFAULT_EXCLUSIONS*) — edit BOTH files together. GC has no dedicated combo
  // template (it uses the GC Resinous doc, mirroring proposal_writer.pick_template),
  // so combo -> Resinous defaults; sealer exists only under GC. ’ is the curly
  // apostrophe in the GC Resinous exclusions ("reqr’d"), matching the template.
  const SCOPE_EPOXY = "Demo (one layer of) existing flooring and place in a dumpster provided by the owner. Prepare substrate surface profile utilizing mechanical means (grinding or shot blasting). Prep substrate cracks and non-moving joints (includes minor floor prep, patching of minor substrate defects, spalls and divots). Install Epoxy System. Assumes installation over: clean, sound & solid concrete substrate.";
  const SCOPE_POLISH = "Demo existing flooring and place in a dumpster. Fill concrete joints with backer rod and polyurea caulking. Patch minor divots. Grind and polish concrete with successive passes using finer grit pads for each pass. Apply hardener/densifier & topical sealer. Perform high-speed burnish. Assumes polish over: clean, sound & solid concrete substrate.";
  const SCHED_DIRECT = "Assumes all areas available at one time, approx. 1 week to complete full scope";
  const EXCL_DIRECT = "Multiple layers of floor to be removed (change order is necessary), Moving of Furniture/Fixtures, Touch-Up Paint, Excessive Patching (i.e., skim coating & more than 1 bag of patch material per 1,000 sf, see notes below), Demo of Existing Floor/Glue/Etc., Weekend or night work, Credit for Unused mobilizations";
  const SCOPE_GC_RESINOUS = "Perform relative humidity test on concrete slab prior to installation (if required)\nPrepare substrate surface profile utilizing mechanical means (grinding or shot blasting)\nPrep substrate (includes patch of minor substrate defects i.e., cracks, non-moving joints, divots, & spalls*)\nInstall Resinous System  ^Patch material included:  xx gallons/kits.\nAssumes installation over: clean, sound & solid concrete substrate";
  const SCOPE_GC_POLISH = "Prep substrate (includes patching of minor substrate defects i.e., cracks, divots, & spalls*)\nGrind and polish concrete with successive passes using finer grit pads for each pass\nApply hardener/densifier & topical sealer\nApply joint filler\nAssumes polish over: clean, sound & solid NEW concrete substrate";
  const SCOPE_GC_SEALER = "Prep substrate (includes patching of minor substrate defects i.e., cracks, divots, & spalls*)\nClean Concrete; -or- Perform 1-2 passes with planetary grinder -or- auto scrubber\nApply [1 coat -or- up to 2 coats of clear concrete sealer\nAssumes sealer over: clean, sound & solid concrete substrate";
  const SCHED_GC = "[ 1 mob/phase ] Assumes all areas available at one time, approx. 1week to complete full scope";
  const EXCL_GC_RESINOUS = "Epoxy Paint Walls, Wall Patching (as may be reqr’d for new base), Demo of Existing Floor/Glue/Etc. (new slab), Excessive Patching (see exclusion detail below*), Nights & Weekends";
  const EXCL_GC_POLISH = "Cove Base, Dye, Demo of Existing Floor/Glue/Etc. (new slab), Excessive Patching (no more than 1 bag per 1,000 sf, see exclusion detail below*), Removal of Existing Joint Filler (if any), Nights & Weekends";
  const EXCL_GC_SEALER = "Patching, Grinding, Joint Filler (see option), Polishing of Concrete, Cove Base, Dye, Demo of Existing Floor/Glue/Etc. (new slab), Excessive Patching / Grinding (no more than 1 bag per 1,000 sf, see exclusion detail below*), Mock-Up, Nights & Weekends, Removal of Existing Joint Filler (if any)";
  // Gyp underlayment: {{scope_notes}}/{{schedule_notes}} aren't tokens in the gyp
  // template (sidebar-coherence only), but {{exclusions}} IS — EXCL_GYP prints.
  // Backend uses _DEFAULT_SCHEDULE (== SCHED_DIRECT) for gyp regardless of audience.
  const SCOPE_GYP = "Pour USG Levelrock 2500 Gypsum Floor Topping at 2,500 psi over plywood subfloor / sound mat as described above, at a uniform thickness & finished to a smooth surface.";
  const EXCL_GYP = "Sealer, Removal of ISO after pour, Credit for unused Mobs, water hook-up, form work, work on podium level or below, pour stops, pre-pours of tubs/showers or party walls, metal lath or mesh reinforcements, gyp under any thresholds, stair treads, lightweight conc., mechanical ventilation, any caulking, any leveling, P&P Bonds, traffic control (provided by others).";
  const NARRATIVE_DEFAULTS = {
    Direct: {
      epoxy:  { scope_notes: SCOPE_EPOXY,  schedule_notes: SCHED_DIRECT, exclusions: EXCL_DIRECT },
      polish: { scope_notes: SCOPE_POLISH, schedule_notes: SCHED_DIRECT, exclusions: EXCL_DIRECT },
      combo:  { scope_notes: SCOPE_EPOXY,  schedule_notes: SCHED_DIRECT, exclusions: EXCL_DIRECT },
      gyp:    { scope_notes: SCOPE_GYP,    schedule_notes: SCHED_DIRECT, exclusions: EXCL_GYP },
    },
    GC: {
      epoxy:  { scope_notes: SCOPE_GC_RESINOUS, schedule_notes: SCHED_GC, exclusions: EXCL_GC_RESINOUS },
      combo:  { scope_notes: SCOPE_GC_RESINOUS, schedule_notes: SCHED_GC, exclusions: EXCL_GC_RESINOUS },
      polish: { scope_notes: SCOPE_GC_POLISH,   schedule_notes: SCHED_GC, exclusions: EXCL_GC_POLISH },
      sealer: { scope_notes: SCOPE_GC_SEALER,   schedule_notes: SCHED_GC, exclusions: EXCL_GC_SEALER },
      gyp:    { scope_notes: SCOPE_GYP,         schedule_notes: SCHED_DIRECT, exclusions: EXCL_GYP },
    },
  };
  // Resolve (audience, work_type) -> {scope_notes, schedule_notes, exclusions},
  // mirroring the backend's _ensure_value_aliases (GC: polish/sealer/else-Resinous;
  // Direct: polish-or-epoxy). Falls back within the audience so an unmapped
  // work_type still yields that audience's sensible boilerplate.
  function narrativeDefaults(audience, wt) {
    const isGC = String(audience || "").trim().toUpperCase() === "GC";
    wt = String(wt || "epoxy").toLowerCase();
    const cat = isGC ? NARRATIVE_DEFAULTS.GC : NARRATIVE_DEFAULTS.Direct;
    return cat[wt] || (isGC ? cat.epoxy : (wt === "polish" ? cat.polish : cat.epoxy));
  }
  // Every default value for `field` across BOTH audiences and ALL work-types —
  // used to recognise (and only then re-seed) untouched machine boilerplate,
  // whichever audience/work-type it was originally seeded from.
  function allFieldDefaults(field) {
    const out = new Set();
    for (const cat of [NARRATIVE_DEFAULTS.Direct, NARRATIVE_DEFAULTS.GC])
      for (const row of Object.values(cat))
        if (row[field] != null) out.add(row[field]);
    return out;
  }

  // Seed the narrative fields: fill blanks with the current audience + EFFECTIVE
  // work type's default, AND if a field still holds a verbatim default from any
  // OTHER audience/work-type (untouched boilerplate), re-seed it — so a mid-draft
  // Direct⇄GC audience switch OR a base-bid work-type switch (Phase B) swaps the
  // machine text, but any hand edit (even 1 char) survives. Re-runnable: called
  // once at init and again from reloadForWorkType when the base's role changes.
  function seedNarrative(fireInput) {
    const cur = narrativeDefaults(_audience, effectiveWorkType());
    for (const nm of ["scope_notes", "schedule_notes", "exclusions"]) {
      const el = form.querySelector(`[name="${nm}"]`);
      if (!el) continue;
      const val = String(el.value || "");
      let next = null;
      if (!val.trim()) next = cur[nm];
      else if (val !== cur[nm] && allFieldDefaults(nm).has(val)) next = cur[nm];
      if (next == null || next === val) continue;
      el.value = next;
      // On a base-switch re-seed, fire input so the form's persistence + doc-fill
      // listeners pick up the swap (a programmatic value set doesn't dispatch on
      // its own). Omitted at init to stay byte-identical to the old behavior (the
      // seeded default flows to the doc/generate via readForm, no early autosave).
      if (fireInput) { try { el.dispatchEvent(new Event("input", { bubbles: true })); } catch {} }
    }
  }
  seedNarrative();

  // Cove base height: intake/estimate capture cove LENGTH only, never height, so
  // a saved empty-string can blank the inline 6" default (writeForm overwrites
  // any non-null state value). Keep the standard 6" visible when nothing real was
  // saved (Kyle: "can't see cove base height value on Proposal sheet").
  (function guardCoveHeight() {
    const ch = form.querySelector('[name="cove_height"]');
    if (ch && !String(ch.value).trim()) ch.value = "6";
  })();

  // Pre-fill the editable NOTES box: saved edits if any, else the standard
  // per-work-type boilerplate (fetched) so the estimator can tweak it per job.
  // (The try{} around renderNotesPreview: during the synchronous init path the
  // editor's consts below aren't initialized yet — initDocumentEditor repaints
  // the notes preview itself, so a skipped early paint costs nothing.)
  // Sync the "Add $X for each additional phase…" NOTES bullet to the estimate's
  // phase-price cell (state.phase_price, from Epoxy!C91 / Polish!C85). The cell
  // is the source of truth: a literal "$xxxx" placeholder is always filled; a
  // numeric amount is re-synced ONLY when the estimate actually snapshotted a
  // price (phase_price > 0), so old drafts / hand-typed amounts aren't clobbered
  // when no cell value exists. Any OTHER wording edit on the line is left alone.
  function syncPhaseNote() {
    const ta = document.getElementById("notes-text");
    if (!ta) return;
    const usd = (n) => {   // self-contained: runs before fmtUSDdoc's const is initialized
      const s = "$" + Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      return s.endsWith(".00") ? s.slice(0, -3) : s;
    };
    const p = Number(state.phase_price);
    const hasCell = isFinite(p) && p > 0;
    const target = `Add ${usd(hasCell ? p : 4500)} for each additional phase beyond the above stated schedule.`;
    const RE = /^Add \$(xxxx|[\d,]+(?:\.\d{1,2})?) for each additional phase beyond the above stated schedule\.$/;
    let changed = false;
    const out = String(ta.value || "").split("\n").map((line) => {
      const t = line.trim();
      const m = RE.exec(t);
      if (!m || t === target) return line;
      if (m[1] !== "xxxx" && !hasCell) return line;   // legacy hand-set amount, no cell snapshot → keep
      changed = true;
      return target;
    });
    if (!changed) return;
    ta.value = out.join("\n");
    try { renderNotesPreview(); } catch {}
    try { TW.setState({ notes_text: ta.value }); } catch {}
  }

  // Tracks the exact notes text last AUTO-SEEDED from /api/default-notes, so a
  // base-bid work-type switch (Phase B) can distinguish untouched boilerplate
  // (re-seed for the new work type) from a hand edit or saved notes (leave alone).
  let _seededNotes = "";

  // Fetch the EFFECTIVE work type's default notes (auth-gated — wait for the
  // Supabase token, else authHeaders() has no Bearer yet and it 401s) and hand
  // the joined text to `onText`. Shared by the initial prefill + the base re-seed.
  function fetchDefaultNotes(onText) {
    return (async () => {
      try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch {}
      try {
        const r = await fetch("/api/default-notes?work_type=" + encodeURIComponent(effectiveWorkType()),
                              { headers: TW.authHeaders() });
        const j = await r.json();
        if (Array.isArray(j.notes)) onText(j.notes.join("\n"));
      } catch {}
    })();
  }

  (function prefillNotes() {
    const ta = document.getElementById("notes-text");
    if (!ta) return;
    const applyAndPreview = (text) => { ta.value = text; syncPhaseNote(); try { renderNotesPreview(); } catch {} };
    if (Array.isArray(state.notes) && state.notes.length) { applyAndPreview(state.notes.join("\n")); return; }
    if (String(ta.value || "").trim()) { syncPhaseNote(); return; }
    // Brand-new project: pull this work type's boilerplate scope/schedule/exclusions.
    fetchDefaultNotes((text) => {
      if (String(ta.value || "").trim()) return;   // user typed during the fetch
      applyAndPreview(text);
      _seededNotes = text;
    });
  })();

  // Base-switch (Phase B): re-fetch default notes for the new effective work type
  // ONLY when the current notes are still the auto-seeded boilerplate (or blank);
  // hand-edited or saved notes are preserved.
  function reseedNotesForWorkType() {
    const ta = document.getElementById("notes-text");
    if (!ta) return;
    const cur = String(ta.value || "");
    if (cur.trim() && cur !== _seededNotes) return;   // hand-edited / saved → keep
    fetchDefaultNotes((text) => {
      ta.value = text; _seededNotes = text; syncPhaseNote();
      try { renderNotesPreview(); } catch {}
      try { TW.setState({ notes_text: ta.value }); } catch {}
    });
  }

  // Pre-fill the Estimator (signature) with the signed-in user's name unless
  // the project already carries one. Editable — they can change who signs.
  (function prefillEstimator() {
    const el = document.getElementById("estimator-name");
    if (!el || el.value) return;
    const apply = () => {
      if (el.value) return;
      const u = (window.TWAuth && TWAuth.user && TWAuth.user()) || null;
      let name = (state.estimator_name || "").trim() || (u && u.name) || "";
      if (!name && u && u.email) {
        name = u.email.split("@")[0].replace(/[._]+/g, " ").replace(/\b\w/g, c => c.toUpperCase());
      }
      if (name) { el.value = name; try { refreshDocumentFills(); } catch {} }
    };
    apply();
    try { if (window.TWAuth && window.TWAuth.ready) window.TWAuth.ready.then(apply); } catch {}
  })();

  // ─── Work-type-aware UI ────────────────────────────────────────
  // The proposal fields differ per work_type:
  //   epoxy  → "Epoxy Flooring" + Epoxy area row + texture row
  //   polish → "Polished Concrete Flooring" + Polish area row, no texture
  //   combo  → "Epoxy + Polished Concrete Flooring" + BOTH area rows + texture
  function adaptToWorkType() {
    const wt = effectiveWorkType();
    const label = wt === "polish" ? "Polished Concrete Flooring"
                : wt === "combo"  ? "Epoxy & Polished Concrete Flooring"
                : wt === "gyp"    ? "Gypsum Underlayment"
                :                   "Epoxy Flooring";
    document.getElementById("work-type-label").value = label;

    // Toggle area rows by work_type
    const epoxyRow  = document.getElementById("area-row-epoxy");
    const polishRow = document.getElementById("area-row-polish");
    const gypRow    = document.getElementById("area-row-gyp");
    const textureRow = document.getElementById("texture-row");
    if (wt === "gyp") {
      // Gyp: only the 3-bucket gyp area row; no epoxy/polish rows, no texture.
      epoxyRow.style.display  = "none";
      polishRow.style.display = "none";
      if (gypRow) gypRow.style.display = "";
      textureRow.style.display = "none";
    } else if (wt === "polish") {
      epoxyRow.style.display  = "none";
      polishRow.style.display = "";
      if (gypRow) gypRow.style.display = "none";
      textureRow.style.display = "none"; // polish doesn't have texture
    } else if (wt === "epoxy") {
      epoxyRow.style.display  = "";
      polishRow.style.display = "none";
      if (gypRow) gypRow.style.display = "none";
      textureRow.style.display = "";
    } else { // combo
      epoxyRow.style.display  = "";
      polishRow.style.display = "";
      if (gypRow) gypRow.style.display = "none";
      textureRow.style.display = "";
      // For combo, clarify which area is which in the key
      epoxyRow.querySelector(".key").textContent  = "Epoxy Area:";
      polishRow.querySelector(".key").textContent = "Polish Area:";
    }
    // For pure single-type, simplify the key back to just "Area:"
    if (wt === "epoxy")  epoxyRow.querySelector(".key").textContent  = "Area:";
    if (wt === "polish") polishRow.querySelector(".key").textContent = "Area:";
  }
  adaptToWorkType();

  // Texture is a fixed dropdown (epoxy/combo only — polish hides the row above).
  // Re-runnable: after the first call the field is already a <select>, so the
  // `input[name=texture]` lookup misses and it no-ops (safe on a base switch).
  function buildTextureControl() {
    const _twt = effectiveWorkType();
    if (_twt === "polish" || _twt === "gyp") return;   // no texture row for these
    const input = document.querySelector('#texture-row input[name="texture"]');
    if (!input) return;
    const cur = (state.texture || input.value || "").trim();
    const OPTS = ["Smooth", "Orange Peel", "Light", "Medium", "Heavy"];
    const opts = OPTS.slice();
    if (cur && !opts.includes(cur)) opts.unshift(cur);   // keep an off-list value
    const sel = document.createElement("select");
    sel.name = "texture"; sel.className = input.className;
    sel.innerHTML = '<option value="">—</option>' +
      opts.map(o => `<option value="${o.replace(/"/g, "&quot;")}">${o}</option>`).join("");
    sel.value = cur;
    input.replaceWith(sel);
  }
  buildTextureControl();

  // Editing the System name here marks it manual, so returning to the Estimate
  // screen won't re-derive over the estimator's wording.
  (function trackManualSystemName() {
    const el = form.querySelector('[name="system_name"]');
    if (!el) return;
    el.addEventListener("input", () => {
      const st = TW.getState();
      TW.setState({ ...st, system_name: el.value, system_name_manual: el.value.trim() !== "" });
    });
  })();

  function updateDocName() {
    const wt = effectiveWorkType();
    document.getElementById("doc-name").textContent =
      (state.project_name || "Untitled") + " - " +
      wt.charAt(0).toUpperCase() + wt.slice(1).toLowerCase() + " Proposal.docx";
  }
  updateDocName();

  // Format helpers
  const fmtUSD = (n) => "$" + Number(n || 0).toLocaleString(undefined,
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtSF = (n) => "~" + Number(n || 0).toLocaleString() + " sf";
  // Like fmtUSD but strips a trailing ".00" so preview PRICE amounts byte-match
  // the backend's _fmt_usd (e.g. "$36,763" not "$36,763.00"); fractional cents
  // keep their decimals ("$36,763.50").
  const fmtUSDdoc = (n) => { const s = fmtUSD(n); return s.endsWith(".00") ? s.slice(0, -3) : s; };

  // ─── Editable DISPLAY overrides (state.price_overrides) ─────────────────
  // EVERY generated line on this page is edited as ONE line: click anywhere in
  // it and rewrite the whole thing, static words included. There are no locked
  // token islands left — the last of them (the WORK {{#system}} rows) moved to
  // this model on 2026-08-24. Kyle, for the third time: "every line in the
  // proposal must be editable as one line, the way the base bid is ... I cannot
  // delete SF of epoxy flooring."
  //
  // A stored line is a DISPLAY override: it never touches cell_values, the
  // .xlsx, or the pricing (see the backend's _sanitize_price_overrides /
  // _sanitize_system_overrides). Blank it and the computed line comes back.
  // Tooltip on an edited (overridden) line. Plain text (no &, <, >, ") so it's
  // safe both inside an HTML title="" attribute and as an .title DOM property.
  const _OVERRIDE_TITLE = "Edited — the printed proposal differs from the computed estimate; the estimate sheet and totals are unchanged.";

  // ── WHOLE-LINE display overrides (state.price_overrides.lines) ─────────────
  // Every PRICE line is edited as ONE contenteditable line (click anywhere,
  // rewrite the whole thing, keep spaces). Stored keyed by a stable line key:
  //   base · heading_base · sales_tax · remodel · total · heading_options
  //   combo:<role.line> · option:<id> · manual:<idx> · alt_name/alt_flooring/…
  // Display-only (backend price_overrides.lines) — never touches the .xlsx/totals.
  function lineOverride(key) {
    const pov = state.price_overrides;
    const lines = (pov && typeof pov === "object" && pov.lines && typeof pov.lines === "object") ? pov.lines : null;
    const v = lines ? lines[key] : null;
    return (typeof v === "string" && v.trim()) ? v : null;
  }
  function lineValue(key, computed) {
    const ov = lineOverride(key);
    return ov != null ? ov : computed;
  }
  // Markup for a JS-rendered whole-line (combo / option / manual / alternate).
  function lineEl(key, computed, opts) {
    const e = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
      c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const shown = lineValue(key, computed);
    const ov = String(shown) !== String(computed);
    const style = (opts && opts.style) || "margin:0 0 2pt;";
    const bold = (opts && opts.bold) ? "font-weight:bold;" : "";
    // No contenteditable of its own -- see renderBlock. The box is the host; this inherits.
    return `<p class="tw-priceline tw-line-edit${ov ? " tw-overridden" : ""}" spellcheck="false"` +
           ` data-po-kind="line" data-po-linekey="${e(key)}" data-computed="${e(computed)}"` +
           (ov ? ` title="${_OVERRIDE_TITLE}"` : "") +
           ` style="${style}${bold}">${e(shown)}</p>`;
  }
  // Repaint a static whole-line element (the base/tax/total/heading <p>s in the
  // HTML staging): show the override or the freshly-computed line, flag ⚠, set
  // data-computed for revert. Skip while the caret is inside (self-heals on blur).
  function paintLine(el, key, computed) {
    if (!el || focusInside(el)) return;
    el.dataset.computed = computed;
    const shown = lineValue(key, computed);
    el.textContent = shown;
    const ov = String(shown) !== String(computed);
    el.classList.toggle("tw-overridden", ov);
    if (ov) el.title = _OVERRIDE_TITLE; else el.removeAttribute("title");
  }

  // Recompute the base bid + priced options from the per-tab totals snapshotted on
  // the Estimate screen (state.priced_tabs). This lets the base-bid picker + the
  // per-option total/deduct toggles work HERE too, without the sheet engine. It
  // MIRRORS estimate-review.js:snapshotLumpSumsToState — keep the two in sync.
  // Sum the Area buckets (SF / cove LF) from the BASE tab(s) ONLY — options
  // never contribute. MIRRORS estimate-review.js:baseAreaFrom. Stale snapshots
  // (priced_tabs without .sf) contribute nothing → callers fall back to intake.
  // Must agree with estimate-review.js. Both sets are asserted present in BOTH files by
  // test_seal_option.py, because two screens disagreeing about which sheets are base-eligible is
  // how a sealed-concrete option ends up listed on one and dropped from the other.
  const OPTION_ONLY_ROLES = new Set(["seal"]);
  const COMBINED_BASE_ROLES = new Set(["epoxy", "polish"]);
  const roleOfTab = (t) => String((t && t.role) || "").toLowerCase();
  const isOptionOnlyTab = (t) => OPTION_ONLY_ROLES.has(roleOfTab(t));
  /** Mirrors estimate-review.js:isInCombinedBase. `t.kind === "base"` ALONE was the bug: both seal
   *  sheets are base-kind template tabs, so a Seal option was silently dropped from every combo
   *  proposal while the Estimate screen went on listing it. */
  const inCombinedBase = (t) => !state.base_tab_id
    && (state.work_type || "epoxy").toLowerCase() === "combo"
    && t.kind === "base" && COMBINED_BASE_ROLES.has(roleOfTab(t));

  function baseAreaFrom(tabsSnap, baseIds) {
    const acc = {};
    const ids = new Set((baseIds || []).filter(Boolean));
    for (const t of tabsSnap || []) {
      if (!ids.has(t.id) || !t.sf) continue;
      for (const k in t.sf) acc[k] = (acc[k] || 0) + (Number(t.sf[k]) || 0);
    }
    return acc;
  }
  function rebuildPricing() {
    const all = Array.isArray(state.priced_tabs) ? state.priced_tabs : [];
    if (!all.length) return;   // older draft w/o the snapshot — leave state.rooms as-is
    // Reconcile per-option PRICE overrides against the live tabs: drop any
    // price_overrides.options[id] whose tab no longer exists (deleted, or a
    // "Copy<N>" id freed then reused by a different copy). Belt-and-suspenders
    // to deleteTab's own delete — also catches an option that was un-marked and
    // its tab later removed — so a stale override can never print on an
    // unrelated option's customer proposal.
    const _pov = state.price_overrides;
    if (_pov && _pov.options && typeof _pov.options === "object" && !Array.isArray(_pov.options)) {
      const liveIds = new Set(all.map(t => t.id));
      let _pruned = false;
      for (const oid of Object.keys(_pov.options)) if (!liveIds.has(oid)) { delete _pov.options[oid]; _pruned = true; }
      if (_pruned) TW.setState({ price_overrides: _pov });
    }
    const wt = (state.work_type || "epoxy").toLowerCase();
    const opts = (state.tab_opts && typeof state.tab_opts === "object") ? state.tab_opts : (state.tab_opts = {});
    const N = (v) => Number(v) || 0;
    const byId = (id) => all.find(t => t.id === id);
    let baseTab = state.base_tab_id ? byId(state.base_tab_id) : null;
    // Refuse an option-only base before anything is priced off it. effectiveWorkType has no seal
    // branch by design, so honouring one would price the bid off a seal sheet and then print the
    // template the intake work type picked. Nulling it lets the migration below resolve a real base.
    if (baseTab && String(baseTab.role || "").toLowerCase() === "seal") {
      baseTab = null;
      state.base_tab_id = null;
    }
    // A non-Combo proposal must always name an actual worksheet as its base.
    // This migrates older null-base drafts before any total is displayed.
    if (!baseTab && wt !== "combo") {
      const defaultRole = wt === "polish" ? "polish" : wt === "gyp" ? "gyp" : "epoxy";
      const defaultId = defaultRole === "gyp" ? GYP_BASE : null;
      const resolved = all.find(t => t.id === defaultId)
        || all.find(t => t.role === defaultRole && t.kind === "base")
        || all.find(t => t.role === defaultRole);
      if (resolved) {
        baseTab = resolved;
        state.base_tab_id = resolved.id;
      }
    }
    let shownBase, salesTax, remodelTax;
    if (baseTab) {
      shownBase = N(baseTab.total); salesTax = N(baseTab.sales_tax); remodelTax = N(baseTab.remodel);
    } else {
      // No explicit base: work_type fallback (combo = Epoxy + Polish base tabs;
      // gyp = the single gyp base tab).
      const eB = all.find(t => t.role === "epoxy" && t.kind === "base") || all.find(t => t.role === "epoxy");
      const pB = all.find(t => t.role === "polish" && t.kind === "base") || all.find(t => t.role === "polish");
      if (wt === "gyp") {
        const gB = all.find(t => t.role === "gyp" && t.id === GYP_BASE)
                || all.find(t => t.role === "gyp" && t.kind === "base")
                || all.find(t => t.role === "gyp");
        baseTab = gB || null; shownBase = N(gB && gB.total); salesTax = N(gB && gB.sales_tax); remodelTax = N(gB && gB.remodel);
      }
      else if (wt === "polish") { baseTab = pB || null; shownBase = N(pB && pB.total); salesTax = N(pB && pB.sales_tax); remodelTax = N(pB && pB.remodel); }
      else if (wt === "combo") { baseTab = eB || null; shownBase = N(eB && eB.total) + N(pB && pB.total); salesTax = N(eB && eB.sales_tax) + N(pB && pB.sales_tax); remodelTax = N(eB && eB.remodel) + N(pB && pB.remodel); }
      else { baseTab = eB || null; shownBase = N(eB && eB.total); salesTax = N(eB && eB.sales_tax); remodelTax = N(eB && eB.remodel); }
    }
    state.proposal_lump_sum = shownBase;
    state.proposal_sales_tax = salesTax;
    state.proposal_remodel_tax = remodelTax;
    const baseDesc = baseTab ? (baseTab.system_desc || "") : "";
    const mkRoom = (t, isBase) => {
      const total = isBase ? shownBase : N(t.total);
      const o = opts[t.id] || {};
      const desc = t.system_desc || t.name;
      return {
        id: t.id, name: t.name, is_base: !!isBase,
        bid: { total, sales_tax: N(t.sales_tax), remodel: N(t.remodel) },
        base_total: shownBase, deduct_amount: shownBase - total,
        price_mode: isBase ? "total" : (o.price_mode === "deduct" ? "deduct" : "total"),
        show: isBase ? true : (o.show !== false),
        system_desc: desc, option_desc: desc, base_desc: baseDesc,
        show_system: o.show_system !== undefined ? o.show_system : true,
        show_diff: o.show_diff !== undefined ? o.show_diff : false,
        notes_auto: Array.isArray(t.notes_auto) ? t.notes_auto : [],
        notes_manual: (state.tab_notes && state.tab_notes[t.id]) || [],
      };
    };
    const optionTabs = all.filter(t => (!baseTab || t.id !== baseTab.id) &&
      opts[t.id] && opts[t.id].is_option && opts[t.id].show !== false &&
      !inCombinedBase(t));
    const shown = optionTabs.map(t => mkRoom(t, false)).filter(o => o.bid.total > 0);
    state.rooms = (shown.length && baseTab) ? [mkRoom(baseTab, true), ...shown] : [];
    // Recompute Area from the base tab(s) so a base switch / option toggle HERE
    // re-derives the proposal's SF without the sheet engine (mirrors the
    // estimate snapshot; combo default = the epoxy + polish base-kind tabs).
    const _baseKindId = (role) => {
      const t = all.find(x => x.role === role && x.kind === "base") || all.find(x => x.role === role);
      return t ? t.id : null;
    };
    let _areaBaseIds;
    if (state.base_tab_id && baseTab) _areaBaseIds = [baseTab.id];
    else if (wt === "combo")         _areaBaseIds = [_baseKindId("epoxy"), _baseKindId("polish")];
    else                             _areaBaseIds = [baseTab ? baseTab.id : null];
    state.sheet_area = baseAreaFrom(all, _areaBaseIds);
    const el = document.querySelector("#tb-total");
    if (el) el.textContent = fmtUSD(shownBase);
    // The DOCUMENT payload must move with the pricing, not just the page's own keys — see
    // syncPayloadPricing. Runs after #tb-total is written, because computeTokenValues reads the
    // lump sum from that element.
    const _pp = syncPayloadPricing();
    TW.setState({ rooms: state.rooms, base_tab_id: state.base_tab_id, tab_opts: state.tab_opts,
      proposal_lump_sum: shownBase, proposal_sales_tax: salesTax, proposal_remodel_tax: remodelTax,
      sheet_area: state.sheet_area, ...(_pp ? { proposal_payload: _pp } : {}) });
  }

  // ── the document payload's pricing must follow the sidebar ────────────────────
  // THE 2026-08-13 INCIDENT. Hanz inverted the base bid here (Epoxy became the base at $18,670,
  // Polish the option at $13,265), left via the "4 · Files" step pill, and re-sent. The portal PAGE
  // showed the new arrangement; the customer's PDF showed the old one. Both were reading the SAME
  // pinned revision — but two different halves of it. The page renders top-level `rooms`; the PDF
  // is rebuilt from `proposal_payload`, and that sub-object was written by exactly ONE line of code:
  // the Continue handler. A sidebar flip updated `rooms`/`base_tab_id`/`proposal_lump_sum` and left
  // the payload frozen, so the revision snapshot was internally inconsistent and nothing noticed:
  // the drift warning compares the page's fields to the page's fields.
  //
  // ONE MAPPING, USED TWICE. This deliberately calls `computeTokenValues` — the same function
  // Continue uses — rather than re-deriving the money. A second copy of the token mapping is how
  // the two halves drift again. What keeps a pricing flip from rewriting the narrative is the
  // WHITELIST below, not a separate code path: only these keys are copied over.
  const PAYLOAD_PRICING_KEYS = [
    // The PRICE block's own three lines, plus the itemised breakdown the epoxy layout adds up.
    "total_label", "lump_sum_label", "lump_sum_formatted", "tax_amount_formatted",
    "total_formatted", "base_bid_formatted", "material_tax_formatted",
    // The parenthetical after the base-bid line — changes with the tax treatment.
    "base_tax_phrase", "tax_phrase", "sales_tax_handling", "tax_inclusion",
    // Area tokens: rebuildPricing re-derives state.sheet_area from the base tab, so a flip
    // changes the SF the proposal quotes.
    "epoxy_sf", "polish_sf", "cove_lf", "lf", "sqft", "area_description",
    "gyp_soft_sf", "gyp_hard_sf", "gyp_corridor_sf",
    "gyp_soft_sf_formatted", "gyp_hard_sf_formatted", "gyp_corridor_sf_formatted",
  ];

  /** Patch the stored generate payload's PRICING slice from current state. Returns the patched
   *  payload, or null when there is nothing to patch.
   *
   *  No-op before the first Continue: with no payload there is nothing stale to correct, and the
   *  Done page builds a fresh one from raw state in that case.
   *
   *  Narrative keys (scope/schedule/exclusions/work_notes/system names/dates/estimator) are NOT in
   *  the whitelist and are never touched here — a base flip must not silently rewrite the words. */
  function syncPayloadPricing() {
    const pp = state.proposal_payload;
    if (!pp || typeof pp !== "object" || !pp.values || typeof pp.values !== "object") return null;
    // NEVER WRITE MONEY WE CANNOT CORROBORATE. computeTokenValues reads the lump sum from
    // #tb-total — and that element does not exist in proposal-review.html at all: the init block
    // near the bottom of this file CREATES it, which happens AFTER the page-init rebuildPricing()
    // call. computeTokenValues falls back to "$0.00" when it is missing, so syncing at that moment
    // wrote a $0.00 total — and a NEGATIVE flooring line, (0 − remodel tax) — into the customer's
    // document and persisted it, just for opening the screen. Refusing to sync leaves the payload
    // exactly as stale as it was, which the publish digest now warns about; a zero would be a
    // $0.00 proposal on a real bid, which is strictly worse than the bug this function fixes.
    let fresh;
    try {
      const _tb = document.querySelector("#tb-total");
      if (!_tb) return null;
      const _tbNum = Number(String(_tb.textContent || "").replace(/[^0-9.-]/g, ""));
      const _stateLump = Number(state.proposal_lump_sum) || 0;
      // rebuildPricing assigns state.proposal_lump_sum (line ~556) and paints #tb-total before
      // calling this, so in the normal path they agree to the cent. A disagreement means the
      // element has not caught up with the pricing — the same hazard as it being absent.
      if (!Number.isFinite(_tbNum) || Math.abs(_tbNum - _stateLump) > 0.01) return null;
      fresh = computeTokenValues(Object.assign({}, state, TW.readForm(form)));
    } catch { return null; }                     // never let a persist fail over this
    PAYLOAD_PRICING_KEYS.forEach((k) => { if (k in fresh) pp.values[k] = fresh[k]; });
    // ── the TEMPLATE, not just the numbers ───────────────────────────────────────────────
    // `work_type` picks which .docx the customer receives, and it is DERIVED from the base tab's
    // role (effectiveWorkType) — so inverting an Epoxy/Polish base doesn't just move money, it
    // changes the document. A frozen `polish` here is why his PDF still said "Polished Concrete
    // Flooring" as the base line: the old template, rendered with its old prices.
    const wt = effectiveWorkType();
    const audience = state.audience || "Direct";
    // Paragraph/box overrides are captured against ONE template's block ids, so when the template
    // changes they cannot be replayed onto the new one — the backend already drops them on a
    // template_version mismatch. Re-collect from the live editor (reloadForWorkType has already
    // swapped it) so the estimator's edits to the NEW template travel; an editor that hasn't
    // loaded yields [], which renders the pristine new template. Either beats old-template text.
    // Guarded on an actual change, so a plain re-price never goes near the narrative.
    // ONLY once the editor has actually loaded a template. `templateVersion` is "" until then —
    // and rebuildPricing runs at page init, before it resolves. Writing "" would be worse than
    // doing nothing: the backend reads an EMPTY version as "legacy caller, apply the overrides",
    // so it would land the old template's edits on the new template's paragraphs. Leaving the
    // stored (non-empty, now-mismatched) version is what makes it drop them instead.
    if (pp.work_type !== wt || pp.audience !== audience) {
      pp.work_type = wt;
      pp.audience = audience;
      try {
        if (templateVersion) {
          pp.template_version = templateVersion;
          pp.paragraph_overrides = collectOverrides();
          pp.box_overrides = collectBoxOverrides();
        }
      } catch { /* editor not mounted — leave what's there for the backend's version guard */ }
    }
    // `values` is also a spread of state (Continue builds it that way), so its mirrors of the
    // pricing state have to move too — anything reading values.rooms must not see the old bid.
    pp.values.work_type = wt;
    pp.values.rooms = Array.isArray(state.rooms) ? state.rooms : [];
    pp.values.base_tab_id = state.base_tab_id;
    pp.values.proposal_lump_sum = state.proposal_lump_sum;
    pp.values.proposal_sales_tax = state.proposal_sales_tax;
    pp.values.proposal_remodel_tax = state.proposal_remodel_tax;
    pp.values.sheet_area = state.sheet_area;
    // Payload-level pricing structures, mirroring continueToDone's own construction.
    const remodelTax = Number(state.proposal_remodel_tax) || 0;
    pp.rooms = Array.isArray(state.rooms) ? state.rooms : [];
    pp.remodel = remodelTax > 0 ? [{ amount_formatted: fmtUSD(remodelTax) }] : [];
    // Clears itself when a combo is narrowed to one base — comboLinesForPayload returns [] then.
    pp.combo_options = comboLinesForPayload();
    // The WORK section's system rows are resolved from the BASE tab's own cells, so they follow a
    // base flip as much as the price does. Same filter as continueToDone.
    try {
      pp.sheet_systems = (sheetSystems() || [])
        .filter(s => (s.name && !s.name.includes("Options")) || s.sf > 0 || s.lf > 0);
    } catch { /* leave the previous resolution rather than emptying the WORK rows */ }
    pp.price_overrides = (state.price_overrides && typeof state.price_overrides === "object")
      ? state.price_overrides : {};
    return pp;
  }

  // Tax-treatment mode, read from the sidebar's dropdown. Shared by the
  // single-bid layout (refreshPriceDisplay) and the combo per-option breakout
  // (comboSystemLines) so BOTH branches honor the same estimator choice — the
  // combo branch used to hardcode "INCLUDED" wording and ignore this entirely.
  function taxTreatmentMode() {
    const incl = String((form.querySelector("[name='tax_inclusion']") || {}).value || "INCLUDED").trim().toUpperCase();
    const exempt = ["EXCLUDED", "EXEMPT", "NOT INCLUDED", "NONE", "NO", "N/A"].includes(incl);
    const broken = ["BROKEN_OUT", "BROKEN OUT", "BROKENOUT", "ITEMIZED", "BREAKOUT"].includes(incl);
    return { incl, exempt, broken };
  }

  // Combo per-option price breakout: Option 1 (Epoxy) + Option 2 (Polish), each
  // with its own flooring / tax line(s) / Total — from the per-tab totals
  // snapshotted on the Estimate screen. Only for the combined-combo default (no
  // single base picked). Options are numbered by RENDER ORDER (not a fixed
  // epoxy=1/polish=2) so a zeroed-out epoxy tab doesn't leave a doc that jumps
  // straight to "Option 2" with no "Option 1" anywhere. Returns pre-formatted
  // {amount_formatted, label} lines.
  function comboSystemLines() {
    const wt = (state.work_type || "epoxy").toLowerCase();
    if (wt !== "combo" || state.base_tab_id) return [];
    const all = Array.isArray(state.priced_tabs) ? state.priced_tabs : [];
    const eB = all.find(t => t.role === "epoxy" && t.kind === "base") || all.find(t => t.role === "epoxy");
    const pB = all.find(t => t.role === "polish" && t.kind === "base") || all.find(t => t.role === "polish");
    const N = (v) => Number(v) || 0;
    const { exempt, broken } = taxTreatmentMode();
    const lines = [];
    let optionNum = 0;
    // `role` ("epoxy"/"polish") gives each line a STABLE semantic key
    // (role.flooring|sales_tax|remodel|total) so a display override never lands on
    // the wrong line when the tax mode changes or a tab is zeroed.
    const pushSys = (sys, noun, role) => {
      if (!sys) return;
      const total = N(sys.total); if (total <= 0) return;
      const remodel = N(sys.remodel);
      const salesTax = N(sys.sales_tax);
      optionNum += 1;
      const optLabel = `Option ${optionNum}`;
      if (broken) {
        // Broken out: base (pre-tax) + Material Sales Tax + Remodel Tax = Total —
        // mirrors the non-combo broken-out layout, no "(…INCLUDED)" phrase.
        const flooring = total - remodel - salesTax;
        lines.push({ key: `${role}.flooring`, amount_formatted: fmtUSD(flooring), label: `${optLabel}: ${noun} as described above` });
        if (salesTax > 0) lines.push({ key: `${role}.sales_tax`, amount_formatted: fmtUSD(salesTax), label: "Material Sales Tax" });
        if (remodel > 0) lines.push({ key: `${role}.remodel`, amount_formatted: fmtUSD(remodel), label: "Kansas Remodel Tax" });
      } else if (exempt) {
        // Tax exempt: the full total carries the "(tax exempt)" phrase — no sales
        // tax is baked in to strip out. Remodel line only if the snapshot actually
        // has one (normally zero on an exempt job).
        lines.push({ key: `${role}.flooring`, amount_formatted: fmtUSD(total), label: `${optLabel}: ${noun} as described above (tax exempt)` });
        if (remodel > 0) lines.push({ key: `${role}.remodel`, amount_formatted: fmtUSD(remodel), label: "Kansas Remodel Tax" });
      } else {
        // Included (default): one all-in flooring line + a separate remodel line
        // when it applies — this is the pre-existing combo wording.
        const flooring = total - remodel;
        lines.push({ key: `${role}.flooring`, amount_formatted: fmtUSD(flooring),
          label: `${optLabel}: ${noun} as described above (material sales tax INCLUDED)` });
        if (remodel > 0) lines.push({ key: `${role}.remodel`, amount_formatted: fmtUSD(remodel), label: "Kansas Remodel Tax" });
      }
      lines.push({ key: `${role}.total`, amount_formatted: fmtUSD(total), label: "Total" });
    };
    pushSys(eB, "Epoxy flooring", "epoxy");
    pushSys(pB, "Polished Concrete flooring", "polish");
    return lines;
  }

  // Combo lines for the GENERATE payload. A whole-line override replaces the entire
  // line: send it as the label with an empty amount so the backend's
  // _strip_leading_separator drops the orphaned " – " and prints the exact line
  // (combo docx lines come straight from payload.combo_options — see main._combo_lines
  // — so preview and generated doc match).
  function comboLinesForPayload() {
    return comboSystemLines().map(l => {
      const ov = lineOverride("combo:" + l.key);
      return ov != null ? { label: ov, amount_formatted: "" }
                        : { amount_formatted: l.amount_formatted, label: l.label };
    });
  }

  // Live update the inline $ amounts in the price preview. This preview MIRRORS
  // the .docx single_bid block exactly (Base Bid + Remodel Tax = Total), using
  // the same figures + tax wording the generate payload sends, so what the
  // estimator sees on screen is what the customer gets. The preview elements
  // live inside the document's read-only priced region once the template loads
  // (see initDocumentEditor); until then they sit in the hidden staging div.
  // The base-bid line's description noun, work-type aware — mirrors each Direct
  // template's base line so the on-screen preview matches the generated doc. (GC/
  // Gyp audiences word it slightly differently; the doc keeps its OWN wording
  // unless the estimator overrides it, so this is just the preview/override default.)
  function baseDescLabel() {
    const wt = effectiveWorkType();
    const noun = wt === "polish" ? "Polished Concrete Flooring"
               : wt === "combo"  ? "Epoxy & Polished Concrete flooring"
               : wt === "sealer" ? "Sealed Concrete"
               : wt === "gyp"    ? "Gypsum Underlayment System"
               : "Epoxy flooring";
    return noun + " as described above";
  }

  function refreshPriceDisplay() {
    const lumpSumText = document.querySelector("#tb-total")?.textContent || "$0.00";
    const lumpSumN = Number(String(lumpSumText).replace(/[^0-9.-]/g, "")) || 0;
    // The Total Base Bid is TAX-INCLUSIVE — Kyle's sheet bakes sales tax (on
    // materials) and remodel tax (on labor/service) into D88. The .docx itemizes
    // it as: Base Bid (flooring, sales-tax incl) + Remodel Tax = Total, so the
    // three lines sum to the lump. Prefer the sheet's own snapshotted tax cells
    // (same precedence as the generate payload), fall back to the engine.
    const fb = (state.computed_bid && state.computed_bid.full_bid) || {};
    const remodelTax = Number((state.proposal_remodel_tax != null ? state.proposal_remodel_tax : fb.remodel_tax) || 0);
    const salesTax   = Number((state.proposal_sales_tax   != null ? state.proposal_sales_tax   : fb.sales_tax)   || 0);
    const baseBid    = Math.max(0, lumpSumN - salesTax - remodelTax);

    // PRICE layout — mirror the .docx. Default (INCLUDED): ONE all-in line, the
    // flooring price = the full total + "(material sales tax INCLUDED)", with the
    // Material Sales Tax / Remodel / Total lines hidden. "Sales tax broken out":
    // base (pre-tax) + Material Sales Tax + Remodel + Total, no INCLUDED label.
    const { exempt, broken } = taxTreatmentMode();

    const salesRow   = document.getElementById("sales-tax-row");
    const remodelRow = document.getElementById("remodel-tax-row");
    const totalRow   = document.getElementById("total-row");
    // The template blocks are mounted asynchronously. A tax-mode change can
    // arrive before its breakout rows are in the document, so retain the state
    // and paint those rows once mounted instead of throwing and blocking Done.
    const comboBlock = document.getElementById("combo-price-block");
    const baseBidRow = document.getElementById("base-bid-row");
    const baseBidHeading = document.getElementById("base-bid-heading");
    const comboLines = comboSystemLines();

    if (comboLines.length && comboBlock) {
      // Combo: Option 1 (Epoxy) + Option 2 (Polish) as WHOLE-LINE rows; hide the
      // single base line + "Base Bid" heading (a combo doc starts at the options).
      // Don't rebuild mid-edit — self-heals on the block's focusout re-render.
      comboBlock.style.display = "";
      if (!focusInside(comboBlock)) {
        comboBlock.innerHTML = comboLines.map(l =>
          lineEl("combo:" + l.key, `${l.amount_formatted} – ${l.label}`)).join("");
      }
      if (baseBidHeading) baseBidHeading.style.display = "none";
      if (baseBidRow) baseBidRow.style.display = "none";
      if (salesRow)   salesRow.style.display = "none";
      if (remodelRow) remodelRow.style.display = "none";
      if (totalRow)   totalRow.style.display = "none";
    } else {
      if (comboBlock) comboBlock.style.display = "none";
      if (baseBidHeading) { baseBidHeading.style.display = ""; paintLine(baseBidHeading, "heading_base", "Base Bid"); }
      if (baseBidRow) baseBidRow.style.display = "";
      const desc = baseDescLabel();
      if (broken) {
        // Broken out: base (pre-tax) + Material Sales Tax + Remodel + Total. fmtUSD
        // keeps cents to match the docx (base_bid_formatted / total_formatted).
        paintLine(baseBidRow, "base", `${fmtUSD(baseBid)} – ${desc}`);
        if (salesRow)   salesRow.style.display = "";
        paintLine(salesRow, "sales_tax", `${fmtUSD(salesTax)} – Material Sales Tax`);
        if (remodelRow) remodelRow.style.display = remodelTax > 0 ? "" : "none";
        paintLine(remodelRow, "remodel", `${fmtUSD(remodelTax)} – Remodel Tax`);
        if (totalRow)   totalRow.style.display = "";
        paintLine(totalRow, "total", `${fmtUSD(lumpSumN)} – Total`);
      } else {
        // Included / exempt: ONE all-in base line; tax rows hidden.
        const computedPhrase = exempt ? "(tax exempt)"
          : remodelTax > 0 ? "(Remodel Tax AND material sales tax INCLUDED)"
          : "(material sales tax INCLUDED)";
        paintLine(baseBidRow, "base", `${fmtUSD(lumpSumN)} – ${desc} ${computedPhrase}`);
        if (salesRow)   salesRow.style.display = "none";
        if (remodelRow) remodelRow.style.display = "none";
        if (totalRow)   totalRow.style.display = "none";
      }
    }
    renderProposalExtras();
  }

  // Render the structured price lines + the recommended ALTERNATE system into
  // the visible PRICE preview, mirroring the {{#price_line}} / {{#alternate}}
  // blocks the backend writes into the .docx. Driven by state (set on the
  // Estimate screen), so the estimator sees the alternate BEFORE generating.
  function renderProposalExtras() {
    const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
      c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

    // (rooms) Per-sheet priced options: base bid first, then each copy. The
    // DOCUMENT (#rooms-block) shows the read-only preview; the CONTROLS (toggles +
    // notes) live in the right #options-panel. state.rooms[] is snapshotted on
    // Estimate Review (≥2 epoxy sheets → options; else single bid).
    const roomsBlock = document.getElementById("rooms-block");
    const optsPanel  = document.getElementById("options-panel");
    {
      const wt = effectiveWorkType();
      const N = (v) => Number(v) || 0;
      const floorNoun = wt === "polish" ? "Polished Concrete Flooring"
                      : wt === "sealer" ? "Sealed Concrete"
                      : wt === "gyp"    ? "Gypsum Underlayment System" : "Epoxy flooring";
      const taxPhrase = (r) => N(r.bid && r.bid.remodel) > 0
        ? "(Remodel Tax AND material sales tax INCLUDED)"
        : "(material sales tax INCLUDED)";

      // DOCUMENT preview — mirrors backend api_generate EXACTLY: the base bid is
      // shown ONLY by the single_bid group (#base-bid-row), so #rooms-block renders
      // NOTHING; the priced OPTION lines (from _build_options) + the manual
      // {{#price_line}} rows both render into #price-lines-block, in that order,
      // under the "Options:" heading. (The old renderRoomsPreview painted a
      // duplicate "Base Bid:" + the options into #rooms-block, which mounts BEFORE
      // single_bid — showing the base twice and never showing "Options:".)
      // Each line is ONE whole-line editable override (display-only) — see lineEl.
      function renderOptionLinesPreview() {
        if (roomsBlock) roomsBlock.innerHTML = "";      // base shows via single_bid only
        const plBlock = document.getElementById("price-lines-block");
        if (!plBlock) return;
        // Bail while the caret is inside — a repaint would destroy the edit;
        // self-heals on the container's focusout re-render.
        if (focusInside(plBlock)) return;
        // Combo breakout leads PRICE with its own Option 1/Option 2 total lines,
        // so the synthetic combined base room is dropped (kept guard) — plus all
        // is_base rows (base shows via single_bid), hidden rows, and empty totals.
        const comboBreakoutActive = comboSystemLines().length > 0;
        const rooms = (Array.isArray(state.rooms) ? state.rooms : [])
          .filter(r => r && r.bid && N(r.bid.total) > 0 && !r.is_base
                       && r.show !== false && !(comboBreakoutActive && r.is_base));
        // OPTION lines — same mode/label rules as main._build_options.
        let html = rooms.map((r) => {
          let label, amount;
          if (r.price_mode === "deduct") {
            // Auto add/deduct by sign: diff = option − base (Will's formula).
            // Negative → "Deduct ($3,200)"; positive/zero → "Add $2,232". The
            // Add/Deduct word rides inside the amount island (docx parity).
            const diff = N(r.bid.total) - N(r.base_total);
            if (diff < 0) {
              label = `VE for ${r.option_desc || r.name}, in lieu of ${r.base_desc || "the base bid"}.`;
              amount = `Deduct (${fmtUSDdoc(Math.abs(diff))})`;
            } else {
              label = r.option_desc || r.system_desc || r.name || floorNoun;
              amount = `Add ${fmtUSDdoc(diff)}`;
            }
          } else {
            const desc = r.system_desc || r.option_desc || floorNoun;
            const notes = (Array.isArray(r.notes_auto) ? r.notes_auto : [])
              .concat(Array.isArray(r.notes_manual) ? r.notes_manual : []);
            label = `${desc} as described above ${taxPhrase(r)}`;
            if (notes.length) label += " — " + notes.join("; ");   // inline, matches main.py
            amount = fmtUSDdoc(r.bid.total);
          }
          return lineEl("option:" + r.id, `${amount} – ${label}`);
        }).join("");
        // Manual {{#price_line}} rows AFTER the options. data-po-index is the
        // ORIGINAL price_lines index (not the filtered one) so a skipped/blank row
        // can't shift a later override — matches the backend's positional apply.
        const pls = Array.isArray(state.price_lines) ? state.price_lines : [];
        html += pls.map((l, i) => {
          const amt = Number(l.amount || 0);
          const label = (l.label || "").trim();
          if (!amt || !label) return "";
          return lineEl("manual:" + i, `${fmtUSDdoc(amt)} – ${label}`);
        }).join("");
        plBlock.innerHTML = html;
        // "Options:" heading visible iff there's ≥1 option or manual price line.
        const oh = document.getElementById("options-heading");
        if (oh) oh.style.display = html.trim() ? "" : "none";
      }
      renderOptionLinesPreview();

      // RIGHT controls panel: base-bid picker + per-tab option toggles — mirrors the
      // Estimate screen's #bid-bar (both edit state.base_tab_id + state.tab_opts).
      // Interactive when we have the per-tab snapshot (state.priced_tabs); otherwise
      // the panel hides and the preview above stays read-only.
      const allTabs = Array.isArray(state.priced_tabs) ? state.priced_tabs : [];
      if (optsPanel) {
        if (!allTabs.length) { optsPanel.hidden = true; optsPanel.innerHTML = ""; }
        else {
          const opts = (state.tab_opts && typeof state.tab_opts === "object") ? state.tab_opts : (state.tab_opts = {});
          let baseId = state.base_tab_id;
          // Keep Combo's named combined base. Every other work type resolves
          // directly to a real sheet, so the misleading Auto row is gone.
          if (!baseId && wt !== "combo") {
            const role = wt === "polish" ? "polish" : wt === "gyp" ? "gyp" : "epoxy";
            const resolved = allTabs.find(t => t.id === (role === "gyp" ? GYP_BASE : null))
              || allTabs.find(t => t.role === role && t.kind === "base")
              || allTabs.find(t => t.role === role);
            if (resolved) {
              state.base_tab_id = resolved.id;
              baseId = resolved.id;
              TW.setState({ base_tab_id: baseId });
            }
          }
          const effectiveBaseId = baseId;
          // gyp is a priced role, so allTabs carries epoxy/polish + all 5 gyp
          // variants on every job. By default show only the tabs relevant to this
          // work type (mirrors estimate-review.js's chipVisible filter); the
          // "+ Add another system" toggle (state.reveal_systems, shared with the
          // estimate bid bar) reveals the cross-type rows for a multi-system bid.
          // "Engaged" = the estimator explicitly made it the base or an option.
          const engaged = (t) => t.id === baseId || (opts[t.id] && opts[t.id].is_option);
          const defaultVis = (t) => (wt === "gyp") ? (t.role === "gyp" || engaged(t))
                                                    : (t.role !== "gyp" || engaged(t));
          const revealSystems = !!state.reveal_systems;
          const visTabs = revealSystems ? allTabs.slice() : allTabs.filter(defaultVis);
          const hasHiddenSystems = allTabs.some(t => !defaultVis(t));
          // Auto base = epoxy/polish base-kind tab(s). For gyp the base is shown
          // explicitly (via effectiveBaseId), so nothing is "part of" a hidden auto-base.
          // Same rule as rebuildPricing's inCombinedBase, and for the same reason: `role !== "gyp"`
          // would tag both seal sheets as part of a combo's combined base bid.
          const isPartOfAutoBase = (t) => {
            if (baseId || wt !== "combo") return false;
            return t.kind === "base" && ["epoxy", "polish"].includes(String(t.role || "").toLowerCase());
          };
          optsPanel.hidden = false;
          // A "Base bid" radio toggle per sheet. Combo additionally retains its
          // explicit named combined base. The base row hides its option controls; the
          // others keep show + total/deduct.
          let h = `<div class="op-drag" title="Drag to move">Pricing options</div>` +
            `<p class="op-hint">Turn on which sheet is the <strong>Base bid</strong>; mark the others as options (show + total / add/deduct).</p>` +
            (wt === "combo" ? `<label class="pr-baserow"><input type="radio" name="pr-base" class="pr-base" value=""${!baseId ? " checked" : ""}> Epoxy + Polish (combined)</label>` : "");
          h += visTabs.map(t => {
            const o = opts[t.id] || {};
            const isBase = effectiveBaseId === t.id;
            const isOpt = !!o.is_option, show = o.show !== false, mode = o.price_mode === "deduct" ? "deduct" : "total";
            const manual = ((state.tab_notes && state.tab_notes[t.id]) || []).join("\n");
            let r = `<div class="op-row" data-id="${esc(t.id)}">`;
            // No Base-bid radio on an option-only sheet — the same suppression the Estimate strip
            // applies, so the two screens cannot offer different answers to "can this be the base?".
            const nameRow = `<span class="op-name">${esc(t.name)} <span class="op-price">${fmtUSD(N(t.total))}</span></span>`;
            r += isOptionOnlyTab(t)
              ? `<div class="pr-baserow" title="Priced as an option only, never as the base bid">${nameRow}</div>`
              : `<label class="pr-baserow"><input type="radio" name="pr-base" class="pr-base" value="${esc(t.id)}"${isBase ? " checked" : ""}> ` +
                nameRow + `</label>`;
            if (isBase) {
              r += `<div class="pr-optsub"><span class="op-hint">This sheet is the Base bid.</span></div>`;
            } else if (isPartOfAutoBase(t)) {
              r += `<div class="pr-optsub"><span class="op-hint">Part of the combined base bid.</span></div>`;
            } else {
              r += `<label><input type="checkbox" class="pr-isopt" ${isOpt ? "checked" : ""}> Show as a proposal option</label>`;
              r += `<div class="pr-optsub"${isOpt ? "" : ' style="display:none"'}>`;
              r += `<label><input type="checkbox" class="pr-show" ${show ? "checked" : ""}> Show in proposal</label>`;
              // An option marked as an option but not shown is configured into thin air:
              // rebuildPricing drops `show === false` rows, so it appears in NEITHER the PDF
              // nor the customer portal. That combination used to be completely silent — the
              // estimator sees a ticked "Show as a proposal option" and reasonably concludes
              // the option exists. Say so where the mistake is made.
              if (isOpt && !show) {
                r += `<span class="op-hint pr-inert-warn">Not shown anywhere — this option `
                   + `appears in neither the PDF nor the customer portal until “Show in `
                   + `proposal” is ticked.</span>`;
              }
              r += `<label>Price as <select class="pr-mode"><option value="total"${mode === "total" ? " selected" : ""}>total amount</option><option value="deduct"${mode === "deduct" ? " selected" : ""}>add/deduct (VE)</option></select></label>`;
              // Deduct only reads as a "($savings) – Deduct VE …" line when it SAVES
              // vs the base; add/deduct now self-labels by sign (option − base):
              // cheaper prints "Deduct ($X)", costlier prints "Add $X" — surface
              // which one this option will be so the estimator isn't surprised.
              const savings = N(state.proposal_lump_sum) - N(t.total);
              r += `<span class="op-hint pr-deduct-hint"${(mode === "deduct" && savings <= 0) ? "" : ' style="display:none"'}>Costs more than the base — will print as an Add.</span>`;
              r += `<label class="op-notes">Notes (one per line)<textarea class="room-notes" rows="2">${esc(manual)}</textarea></label>`;
              r += `</div>`;
            }
            r += `</div>`;
            return r;
          }).join("");
          // "+ Add another system" — reveals cross-work-type rows (mirrors the
          // estimate bid bar) so a multi-system bid can be built here too.
          if (hasHiddenSystems) {
            const lbl = revealSystems ? "− Fewer systems" : "+ Add another system";
            h += `<button type="button" class="pr-addsys-btn">${esc(lbl)}</button>`;
          }
          optsPanel.innerHTML = h;
          const addsysBtn = optsPanel.querySelector(".pr-addsys-btn");
          if (addsysBtn) addsysBtn.addEventListener("click", () => {
            state.reveal_systems = !state.reveal_systems;
            try { TW.setState({ reveal_systems: state.reveal_systems }); } catch {}
            renderProposalExtras();
          });

          const ensureOpt = (id) => { if (!opts[id]) opts[id] = { show_system: true, show_diff: false, is_option: false, show: true, price_mode: "total" }; return opts[id]; };
          const applyAndRefresh = () => { rebuildPricing(); refreshPriceDisplay(); };
          // Base-bid radios — turning one on sets the base.
          optsPanel.querySelectorAll("input.pr-base").forEach(rb => rb.addEventListener("change", () => {
            if (!rb.checked) return;
            const priorBaseId = state.base_tab_id;
            state.base_tab_id = rb.value || null;
            if (rb.value && opts[rb.value]) opts[rb.value].is_option = false;   // base can't also be an option
            if (state.base_tab_id !== priorBaseId) {
              // A base/work-type change re-derives the base + tax rows + combo
              // breakout, so their display overrides are stale — clear them (the
              // base-independent alternate block's overrides are kept).
              const pov = state.price_overrides;
              if (pov && typeof pov === "object" && !Array.isArray(pov)) {
                pov.single_bid = {}; pov.rows = {}; pov.combo = {};
                // Clear base-dependent whole-line overrides; keep the base-independent
                // alternate block (alt_*).
                if (pov.lines && typeof pov.lines === "object") {
                  for (const k of Object.keys(pov.lines)) if (!k.startsWith("alt_")) delete pov.lines[k];
                }
              }
            }
            applyAndRefresh();
            reloadForWorkType();   // Phase B: reload template/narrative/notes if the base changed the work type
          }));
          optsPanel.querySelectorAll(".op-row").forEach(row => {
            const id = row.dataset.id;
            const sub = row.querySelector(".pr-optsub");
            const iso = row.querySelector(".pr-isopt");
            if (iso) iso.addEventListener("change", () => {
              const o = ensureOpt(id); o.is_option = iso.checked;
              // Turning an option ON resets `show` to true — it used to only default an
              // UNDEFINED show, so an option un-shown earlier stayed un-shown when it was
              // re-enabled, and "Show as a proposal option" did nothing at all: rebuildPricing
              // drops `show === false` rows, so the option reached neither the PDF nor the
              // portal. Hanz, 2026-08-13: "There are two options but the PDF Shows one."
              // Ticking the outer box is somebody saying "put this in the proposal"; honour it.
              if (o.is_option) { o.show = true; if (!o.price_mode) o.price_mode = "total"; }
              if (sub) sub.style.display = iso.checked ? "" : "none";
              const shBox = row.querySelector(".pr-show");
              if (shBox) shBox.checked = o.show !== false;
              applyAndRefresh();
              renderProposalExtras();   // repaint so the inert-option warning reflects the change
            });
            const sh = row.querySelector(".pr-show");
            if (sh) sh.addEventListener("change", () => {
              ensureOpt(id).show = sh.checked;
              applyAndRefresh();
              renderProposalExtras();   // show/hide the inert-option warning immediately
            });
            const md = row.querySelector(".pr-mode");
            if (md) md.addEventListener("change", () => {
              ensureOpt(id).price_mode = md.value === "deduct" ? "deduct" : "total";
              const hint = row.querySelector(".pr-deduct-hint");
              if (hint) {
                const t = allTabs.find(x => x.id === id);
                const savings = N(state.proposal_lump_sum) - N(t ? t.total : 0);
                hint.style.display = (md.value === "deduct" && savings <= 0) ? "" : "none";
              }
              applyAndRefresh();
            });
            const ta = row.querySelector(".room-notes");
            if (ta) ta.addEventListener("input", () => {
              if (!state.tab_notes) state.tab_notes = {};
              state.tab_notes[id] = ta.value.split("\n").map(s => s.trim()).filter(Boolean);
              rebuildPricing();             // refresh state.rooms (notes) …
              renderOptionLinesPreview();   // … then update ONLY the preview (keep textarea focus)
              TW.setState({ tab_notes: state.tab_notes });
            });
          });
        }
      }
    }

    // (a) The priced OPTION lines + manual price lines now render into
    // #price-lines-block via renderOptionLinesPreview() (above) so the option
    // lines can precede the manual lines and share the editable-island path.

    // (b) Recommended alternate system — a 2nd, independent priced bid.
    const altBlock = document.getElementById("alternate-block");
    if (!altBlock) return;
    const acb   = state.alternate_computed_bid;
    const altFb = acb && acb.alternate_full_bid;
    if (!altFb || typeof altFb.total_base_bid !== "number") { if (!focusInside(altBlock)) altBlock.innerHTML = ""; return; }
    // Don't rebuild while the caret is inside one of the alternate islands.
    if (focusInside(altBlock)) return;
    const altTotal   = altFb.total_base_bid;
    const altRemodel = Number(altFb.remodel_tax || 0);
    const altFloor   = altTotal - altRemodel;
    const altLabel   = (state.alternate && state.alternate.label)
                       || (acb.alternate && acb.alternate.label) || "Alternate System";
    // Mirrors the .docx {{#alternate}} block literally, each row a WHOLE-LINE
    // editable: header (system name), "$X – Flooring as described above (…)",
    // optional "$X – Remodel Tax", "$X – Total".
    altBlock.innerHTML =
      lineEl("alt_name", `ALTERNATE SYSTEM — ${altLabel}`, { bold: true, style: "margin:6pt 0 2pt;" }) +
      lineEl("alt_flooring", `${fmtUSD(altFloor)} – Flooring as described above (material sales tax INCLUDED)`) +
      (altRemodel > 0 ? lineEl("alt_remodel", `${fmtUSD(altRemodel)} – Remodel Tax`) : "") +
      lineEl("alt_total", `${fmtUSD(altTotal)} – Total`);
  }

  // ─── Token values (shared by the document fills + the generate payload) ──
  // One assembly of the {{token}} vocabulary (see proposal_writer.py's notes),
  // used BOTH to substitute values into the on-page document (highlighted
  // .tw-fill spans) and to build the generate payload — so the page shows the
  // exact strings the .docx will carry.
  function computeTokenValues(mergedValues) {
    const workType = effectiveWorkType();
    // Area SF/LF are SHEET-FIRST: the resolved base tab's cells (snapshotted into
    // state.sheet_area — system-1 bucket for the flat tokens, matching today's
    // semantics) win when > 0, else fall back to the intake fields. This makes a
    // copy-base's SF flow to the proposal instead of only the intake number.
    const sa = (state.sheet_area && typeof state.sheet_area === "object") ? state.sheet_area : {};
    const sheetFirst = (sheetV, intakeV) => (Number(sheetV) > 0 ? Number(sheetV) : (Number(intakeV) || 0));
    const polishSF = sheetFirst(sa.polish_sf, mergedValues.polish_sf || mergedValues.system_1_sf);
    const epoxySF  = sheetFirst(sa.epoxy_sf,  mergedValues.system_1_sf);
    const coveLF   = sheetFirst(sa.cove_lf,   mergedValues.cove_1_lf);
    const lumpSumText = document.querySelector("#tb-total")?.textContent || "$0.00";
    const lumpSumNumber = Number(String(lumpSumText).replace(/[^0-9.-]/g, "")) || 0;
    // Tax-inclusive bid. Kyle's .docx itemizes KS remodel tax on its own
    // line, so we fill the template's 3 lines so they ADD UP:
    //   flooring (sales tax incl) = Total Base Bid − remodel tax
    //   + KS remodel tax
    //   = Total
    // (Sales tax stays inside the flooring figure, matching the template's
    //  "(material sales tax INCLUDED)" label. No tax is added on top.)
    const _fb = (state.computed_bid && state.computed_bid.full_bid) || {};
    // Prefer the SHEET's own tax cells (snapshotted on the Estimate screen) so the
    // breakdown matches the Total Lump Sum exactly; fall back to the engine figures.
    const remodelTax = Number((state.proposal_remodel_tax != null ? state.proposal_remodel_tax : _fb.remodel_tax) || 0);
    const salesTax   = Number((state.proposal_sales_tax   != null ? state.proposal_sales_tax   : _fb.sales_tax)   || 0);
    const flooringPortion = lumpSumNumber - remodelTax;
    // Itemized breakdown (Base Bid + Material Sales Tax [+ Remodel Tax] = Total).
    // Base Bid is the remainder so the three lines sum to the sheet's lump sum.
    const baseBid = Math.max(0, lumpSumNumber - salesTax - remodelTax);
    const safe = (v) => (v === undefined || v === null || v === "" ? "0" : v);

    // A generated proposal is persisted back into `mergedValues`.  Seed those
    // fields first, then let the current screen's computed values win below.
    // In particular, a previously saved `(tax exempt)` phrase or total must not
    // overwrite a newly selected "Sales tax broken out" preview.  The live
    // proposal must show the selected base bid, its sales-tax row, and Total.
    const tokenValues = {
      ...mergedValues,
      job_name:           safe(mergedValues.project_name),
      project_name:       safe(mergedValues.project_name),
      // Signs the proposal — the field (pre-filled from the signed-in user),
      // else the signed-in user's name. Replaces the old hardcoded "Troy Holmes".
      estimator_name:     (String(mergedValues.estimator_name || "").trim()
                           || ((window.TWAuth && TWAuth.user() && TWAuth.user().name) || "")),
      city_state:         safe(mergedValues.city_state),
      address:            safe(mergedValues.address),
      work_description:   safe(mergedValues.work_description || mergedValues.address || "0"),
      proposal_date:      new Date().toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" }),
      bid_date:           safe(mergedValues.bid_date),
      // M/D/YY for the header date that the template hardcoded as 1/1/26
      bid_date_formatted: (() => {
        const raw = mergedValues.bid_date;
        if (!raw) return new Date().toLocaleDateString("en-US", { month:"numeric", day:"numeric", year:"2-digit" });
        const d = new Date(String(raw) + "T00:00:00");
        if (isNaN(d)) return safe(raw);
        return `${d.getMonth()+1}/${d.getDate()}/${String(d.getFullYear()).slice(-2)}`;
      })(),
      site_visit_date:    safe(mergedValues.site_visit_date_display || mergedValues.bid_date),
      system_name:        safe(mergedValues.system_name),
      system_name_epoxy:  safe(mergedValues.system_name),
      system_name_polish: safe(mergedValues.system_name),
      texture:            safe(mergedValues.texture),
      epoxy_sf:           epoxySF ? Number(epoxySF).toLocaleString("en-US") : "0",
      polish_sf:          polishSF ? Number(polishSF).toLocaleString("en-US") : "0",
      cove_lf:            coveLF  ? Number(coveLF).toLocaleString("en-US")  : "0",
      sqft:               (workType === "polish" ? Number(polishSF || 0) : Number(epoxySF || 0)).toLocaleString("en-US"),
      lf:                 coveLF  ? Number(coveLF).toLocaleString("en-US")  : "0",
      disposal:           mergedValues.disposal || "a dumpster provided by the owner",
      area_description:   workType === "polish"
        ? `${fmtSF(polishSF)} of polished concrete flooring`
        : `${fmtSF(epoxySF)} of epoxy flooring`,
      // Template's native 3-line price block, filled so it sums to the bid:
      //   flooring (sales tax incl)  +  KS remodel tax  =  Total
      total_label:        `${fmtUSD(lumpSumNumber)} – Total`,
      lump_sum_label:     `${fmtUSD(flooringPortion)} – ${workType === "polish" ? "Polished Concrete Flooring" : "Epoxy Flooring"} as described above`,
      lump_sum_formatted: fmtUSD(flooringPortion),  // (combo/polish templates) flooring incl sales tax
      tax_amount_formatted: fmtUSD(remodelTax),     // legacy remodel-tax token (combo/polish)
      total_formatted:    fmtUSD(lumpSumNumber),    // the tax-inclusive Total Base Bid
      // Epoxy PRICE breakdown (Base Bid + Material Sales Tax [+ Kansas Remodel Tax] = Total):
      base_bid_formatted:    fmtUSD(baseBid),
      material_tax_formatted: fmtUSD(salesTax),
      scope_notes:        safe(mergedValues.scope_notes),
      schedule_notes:     safe(mergedValues.schedule_notes),
      exclusions:         safe(mergedValues.exclusions),
      // WORK "Notes:" line — editable per-job note (empty until the estimator
      // fills it; NOT `safe()` which would render "0"). The backend coerces the
      // same way so a blank never prints a raw {{work_notes}} token.
      work_notes:         String(mergedValues.work_notes || ""),
      sales_tax_handling: mergedValues.sales_tax_handling || "INCLUDED",
      tax_phrase: (mergedValues.sales_tax_handling || "INCLUDED") === "INCLUDED"
        ? "Sales and KS remodel tax are included in the lump sum above."
        : "Tax is NOT included and will be added at invoice.",
      // Base-bid line's parenthetical tax phrase. Templates WITHOUT a
      // {{#single_bid}} base-bid island (polish Direct, every GC template) use
      // {{base_tax_phrase}} as a plain token — without this the on-page preview
      // showed a raw "{{base_tax_phrase}}" even though the generated doc was
      // correct (the backend fills it at generate time). Mirror that backend
      // logic (broken out → no label; exempt → "(tax exempt)"; else INCLUDED,
      // with the remodel note when remodel tax applies).
      base_tax_phrase: (() => {
        const m = taxTreatmentMode();
        if (m.broken) return "";
        if (m.exempt) return "(tax exempt)";
        return remodelTax > 0 ? "(Remodel Tax AND material sales tax INCLUDED)"
                              : "(material sales tax INCLUDED)";
      })(),
    };

    // Area (SF / cove LF) tokens are sheet-first. Non-gyp only; the gyp block
    // below owns the gyp buckets.
    if (workType !== "gyp") {
      tokenValues.epoxy_sf  = epoxySF ? Number(epoxySF).toLocaleString("en-US") : "0";
      tokenValues.polish_sf = polishSF ? Number(polishSF).toLocaleString("en-US") : "0";
      tokenValues.cove_lf   = coveLF ? Number(coveLF).toLocaleString("en-US") : "0";
      tokenValues.lf        = tokenValues.cove_lf;
      tokenValues.sqft      = (workType === "polish" ? Number(polishSF || 0) : Number(epoxySF || 0)).toLocaleString("en-US");
      tokenValues.area_description = workType === "polish"
        ? `${fmtSF(polishSF)} of polished concrete flooring`
        : `${fmtSF(epoxySF)} of epoxy flooring`;
    }

    // Gyp-only tokens. The gyp template prints {{gyp_*_sf}} directly and the
    // backend only backfills BLANK ones, so the frontend must supply them here
    // comma-formatted (a raw number from mergedValues would show "27825"). Also
    // seed the thickness / mobilization / work_description defaults so the doc
    // editor never shows a raw {{token}} before the estimator touches anything —
    // byte-identical to main.py:_ensure_value_aliases' gyp branch.
    if (workType === "gyp") {
      const gN = (v) => Number(String(v == null ? "" : v).replace(/,/g, "")) || 0;
      const fmtInt = (n) => Number(n || 0).toLocaleString("en-US");
      // Sheet-first: base gyp tab's G9/I9/K9 (state.sheet_area) win over intake.
      const soft = sheetFirst(sa.gyp_soft_sf, gN(mergedValues.gyp_soft_sf));
      const hard = sheetFirst(sa.gyp_hard_sf, gN(mergedValues.gyp_hard_sf));
      const corr = sheetFirst(sa.gyp_corridor_sf, gN(mergedValues.gyp_corridor_sf));
      tokenValues.gyp_soft_sf     = fmtInt(soft);
      tokenValues.gyp_hard_sf     = fmtInt(hard);
      tokenValues.gyp_corridor_sf = fmtInt(corr);
      tokenValues.gyp_soft_sf_formatted     = tokenValues.gyp_soft_sf;
      tokenValues.gyp_hard_sf_formatted     = tokenValues.gyp_hard_sf;
      tokenValues.gyp_corridor_sf_formatted = tokenValues.gyp_corridor_sf;
      if (!String(tokenValues.gyp_soft_thickness || "").trim())     tokenValues.gyp_soft_thickness = '3/4"';
      if (!String(tokenValues.gyp_hard_thickness || "").trim())     tokenValues.gyp_hard_thickness = '1"';
      if (!String(tokenValues.gyp_corridor_thickness || "").trim()) tokenValues.gyp_corridor_thickness = '3/4"';
      if (!String(tokenValues.mobilizations_line || "").trim())     tokenValues.mobilizations_line = "1 Mobilization to Site.";
      // Gyp has no work_description input; backend forces this spec-line default.
      if (!String(mergedValues.work_description || "").trim())      tokenValues.work_description = "per plans & specifications provided";
      const gypTotal = soft + hard + corr;
      tokenValues.sqft = fmtInt(gypTotal);
      tokenValues.area_description = `${fmtSF(gypTotal)} of gypsum underlayment`;
    }

    // Editor-only extras the backend derives inside api_generate — resolved
    // here with the SAME rules so the on-page fills match the generated doc
    // (the backend recomputes site_visit_phrase itself on generate, so parity
    // is by construction, not by trusting this echo).
    const _sv = String(tokenValues.site_visit_date || "").trim();
    tokenValues.site_visit_phrase = (mergedValues.no_site_visit || !_sv || _sv.toUpperCase() === "N/A")
      ? "per plans and specifications provided"
      : `per site visit on ${_sv}`;
    if (!String(tokenValues.epoxy_system_name || "").trim()) {
      const a22 = String((state.cell_values || {})["Epoxy!A22"] || "").trim();
      tokenValues.epoxy_system_name = (a22 && !a22.includes("Options")) ? a22 : "Epoxy System";
    }
    if (!String(tokenValues.state_name || "").trim()) tokenValues.state_name = "Kansas";
    return tokenValues;
  }

  // ─── Document editor: the REAL template, paragraph by paragraph ──────────
  // GET /api/proposal-template returns the picked .docx's paragraphs in the
  // backend's id order (proposal_writer.iter_editable_blocks — the SAME walk
  // /api/generate later uses to apply overrides, so ids can't drift). Each
  // paragraph outside a {{#block}} region renders as a contenteditable
  // .tw-block; every {{token}} in it becomes a highlighted .tw-fill span
  // holding the resolved value (screen-only — serialization emits plain text,
  // and the backend writes plain run text, so no highlight/HTML can reach the
  // .docx). A block whose serialized text differs from its pristine rendering
  // ships as an {id, text} paragraph_override on generate.
  const docSurface   = document.getElementById("doc-surface");
  const docZoom      = document.getElementById("doc-zoom");
  const docZoomOuter = document.getElementById("doc-zoom-outer");
  const stagingPanel = document.getElementById("price-preview-staging");

  let templateBlocks  = null;   // blocks from the endpoint (null until loaded)
  let templateVersion = "";
  let pageWpt         = 612;    // page width in pt, drives the zoom fit
  let flowMode        = false;  // true = geometry-less fallback rendering
  const blockById     = new Map();   // id -> block record
  const pristineById  = new Map();   // id -> plain-text pristine rendering
  const artUrlCache   = new Map();   // media name -> object-URL promise
  // Paragraph properties the estimator has changed: id -> {bullet, indent} in TWIPS, the same
  // unit the backend reads. Only DIFFERENCES live here; the template's own state comes from
  // blockById.get(id).para, so an untouched paragraph ships nothing and generates the file it
  // always generated.
  const paraById      = new Map();   // id -> {bullet, indent} the estimator set

  // Box layout the estimator dragged — see "dragging and resizing a text box" below.
  // boxDesign is the template's own geometry (the thing Reset goes back to); boxOverrides holds
  // only what DIFFERS from it, which is also what ships as `box_overrides`.
  const boxDesign    = new Map();    // box id -> {x_pt, y_pt, w_pt, h_pt} from the template
  let   boxOverrides = new Map();    // box id -> {x_pt?, y_pt?, w_pt?, h_pt?}
  let   boxLimits    = null;         // {pageW, pageH, maxW, maxH, minPt}, from geometry.page

  // Terms & Conditions pagination state (Feature C): the ordered terms block
  // elements (identity preserved across repaginations), the page geometry to
  // paginate against, and the resolved terms-letterhead art URL.
  let _termsUnits  = null;
  let _termsGeom   = null;
  let _termsArtUrl = null;
  // Measured top-band reservation (pt) per terms-art media name — how far the
  // continuation letterhead's logo ink reaches into the text column, scanned
  // from the art itself (never a hardcoded offset, so every template's art
  // works). Cached so switching work-types doesn't re-scan the same PNG.
  const _termsBandCache = new Map();   // work_type:media name -> reserved top band (pt)

  // True when the estimator is typing inside `el` — used to skip any re-render that would rebuild
  // `el`'s innerHTML (and destroy the caret) mid-word. Skipped repaints self-heal on the next
  // focusout re-render / refreshDocumentFills.
  //
  // TWO QUESTIONS, because one of them stopped being enough. `document.activeElement` was the
  // right answer while every editable line carried its own contenteditable: focus landed on the
  // line, so a container holding the caret contained the focus. Now the BOX is the editing host,
  // focus lands on it once and stays there while the caret moves between the paragraphs inside
  // it — so activeElement is an ANCESTOR of the line being typed in, and
  // `el.contains(activeElement)` is false exactly when this guard matters most. The caret's own
  // line answers it directly, and nothing about it depends on where focus happens to sit.
  const focusInside = (el) => {
    if (!el) return false;
    const a = document.activeElement;
    if (a && el.contains && el.contains(a)) return true;
    const line = lineAtSelection();
    return !!(line && el.contains && el.contains(line));
  };

  const escHtml = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // Flat tokens only — dotted per-item tokens ({{price_line.label}}) live in
  // read-only regions and are never substituted here.
  const DOC_TOKEN_RE = /\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}/g;

  // Captions for front-page blocks that are a bare token — the real template
  // labels these in its letterhead graphic, which the text walk can't carry.
  const TOKEN_HINTS = {
    job_name: "Job name", work_description: "Work description",
    city_state: "City / State", bid_date_formatted: "Date",
    estimator_name: "Estimator",
  };

  // Live preview elements mounted into each region, by block name. Their content is
  // engine-generated but NOT read-only: every line inside them is one editable line
  // (see lineEl / renderSystemPreview / renderNotesPreview). The single_bid mount
  // carries the whole base-bid group (incl. the combo breakout + the nested
  // tax_breakout/remodel/has_options rows).
  const systemPreviewEl = document.createElement("div");
  systemPreviewEl.id = "system-preview-block";
  const notesPreviewEl = document.createElement("div");
  notesPreviewEl.id = "notes-preview-block";
  const REGION_MOUNTS = {
    system:     () => [systemPreviewEl],
    notes:      () => [notesPreviewEl],
    room:       () => [document.getElementById("rooms-block")],
    single_bid: () => ["base-bid-heading", "combo-price-block", "base-bid-row",
                       "sales-tax-row", "remodel-tax-row", "total-row", "options-heading"]
                       .map(id => document.getElementById(id)),
    // Polish / GC templates DON'T wrap the base bid in {{#single_bid}} — "Base Bid"
    // + the base line are plain template blocks (already shown), and the tax lines
    // live in separate {{#tax_breakout}} / {{#remodel}} / {{#has_options}} regions.
    // Mount the SAME live staging rows there — in the doc's Material Sales Tax →
    // Remodel → Total → Options order — so the on-screen preview itemizes exactly
    // like the generated .docx (refreshPriceDisplay show/hides them by tax mode).
    // remodel-tax-row rides under tax_breakout for ordering; the {{#remodel}}
    // region itself mounts nothing to avoid a duplicate.
    tax_breakout: () => ["sales-tax-row", "remodel-tax-row", "total-row"]
                       .map(id => document.getElementById(id)),
    remodel:      () => [],
    has_options:  () => [document.getElementById("options-heading")],
    price_line: () => [document.getElementById("price-lines-block")],
    alternate:  () => [document.getElementById("alternate-block")],
  };

  // ── keeping the mounted islands alive across a re-render ──────────────────
  // Every id above is a REAL NODE that lives in #price-preview-staging and is
  // MOVED into the document by mountRegionPreviews (appendChild moves, it does
  // not copy). So `docSurface.innerHTML = ""` at the top of a re-render DESTROYS
  // them, and the next getElementById returns null — at which point
  // mountRegionPreviews mounts nothing at all, silently, because of its
  // `if (el)` guard.
  //
  // That is what broke switching the base bid back to an epoxy sheet. Epoxy's
  // PRICE box is entirely region-mounted, so every line of it — Base Bid, the
  // price, the tax rows, Total, "Options:" — came from these nodes and the box
  // rendered empty. Polish survives the same trip only because its base bid is
  // a plain template paragraph, which is why the bug looked one-directional.
  //
  // systemPreviewEl / notesPreviewEl never had this problem: they are held in
  // consts above, so `innerHTML = ""` detaches them but the references live on.
  // These are id-addressed instead, so they need somewhere to be detached TO —
  // their original home. Reclaiming is idempotent: on a first render they are
  // already in staging and moving them there again is a no-op.
  const ISLAND_IDS = ["rooms-block", "base-bid-heading", "combo-price-block",
                      "base-bid-row", "sales-tax-row", "remodel-tax-row", "total-row",
                      "options-heading", "price-lines-block", "alternate-block"];
  const stagingHome = stagingPanel && stagingPanel.parentNode;

  /** Empty the document surface WITHOUT destroying the live price previews.
   *
   *  Always use this instead of touching docSurface.innerHTML directly — the two
   *  render paths (positioned + flow) and the error path all clear the surface,
   *  and a clear that skips the reclaim reintroduces the blank-preview bug. */
  function clearDocSurface() {
    for (const id of ISLAND_IDS) {
      const el = document.getElementById(id);
      if (el && stagingPanel && el.parentNode !== stagingPanel) stagingPanel.appendChild(el);
    }
    // The panel itself gets re-parented into the surface by the error path below,
    // so put it back too — otherwise the next successful render deletes the whole
    // staging area and every island with it.
    if (stagingPanel && stagingHome && stagingPanel.parentNode !== stagingHome) {
      stagingPanel.hidden = true;
      stagingHome.appendChild(stagingPanel);
    }
    docSurface.innerHTML = "";
    // AND THE UNDO HISTORY, which described those same paragraphs. Every entry names its lines by
    // the backend walk's paragraph id, and those ids belong to the template that was on screen — a
    // work-type switch or an audience switch loads a DIFFERENT one, where the same number is a
    // different paragraph. Replaying an entry across that boundary would write the estimator's
    // words into the wrong clause of a document a customer signs, so the history goes with the
    // document it described.
    undoForget();
    // The formatting ribbon's remembered block was one of the paragraphs just destroyed. Since
    // 2026-08-24 that target deliberately outlives focus ("keep it static like a ribbon in a word
    // document"), so nothing else takes it away: `fmtTargetBlock` would notice, but not until the
    // next press, leaving a ribbon that looks live and does nothing for as long as the estimator
    // does not try it. Grey it out here, where the paragraphs actually go.
    idleFmtBar();
  }

  // Substituted HTML for one template paragraph: text escaped, each known
  // {{token}} replaced by a highlighted span. Unknown tokens keep their
  // literal {{token}} text (still inside a span so the estimator sees what
  // wasn't auto-filled); the backend's flat pass resolves or leaves them the
  // exact same way, so pristine tracking stays consistent.
  function fillHtml(templText, tokens) {
    DOC_TOKEN_RE.lastIndex = 0;
    let html = "", last = 0, m;
    while ((m = DOC_TOKEN_RE.exec(templText))) {
      html += escHtml(templText.slice(last, m.index));
      const name = m[1];
      const known = Object.prototype.hasOwnProperty.call(tokens, name);
      html += `<span class="tw-fill" data-token="${escHtml(name)}">` +
              escHtml(known ? String(tokens[name]) : m[0]) + `</span>`;
      last = m.index + m[0].length;
    }
    return html + escHtml(templText.slice(last));
  }

  // The same substitution as plain text — the block's PRISTINE rendering, the
  // baseline an edit is detected against.
  function fillPlain(templText, tokens) {
    DOC_TOKEN_RE.lastIndex = 0;
    return String(templText).replace(DOC_TOKEN_RE, (m0, name) =>
      Object.prototype.hasOwnProperty.call(tokens, name) ? String(tokens[name]) : m0);
  }

  // Serialize a contenteditable block back to plain text: .tw-fill spans
  // contribute their TEXT VALUE (never the token), <br>/nested divs become
  // newlines, NBSPs normalize to spaces.
  function serializeBlock(el) {
    const walk = (node) => {
      let out = "";
      node.childNodes.forEach(n => {
        if (n.nodeType === Node.TEXT_NODE) { out += n.nodeValue; return; }
        if (n.nodeType !== Node.ELEMENT_NODE) return;
        if (n.tagName === "BR") { out += "\n"; return; }
        if (/^(DIV|P)$/.test(n.tagName) && out && !out.endsWith("\n")) out += "\n";
        out += walk(n);
      });
      return out;
    };
    return walk(el).replace(/\u00a0/g, " ");
  }

  // \u2500\u2500 capturing FORMATTING, not just text \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  // serializeBlock above walks INTO the style spans blockHtml wrote, keeps their text and
  // throws the styling away. That made a formatting-only edit lose twice over: it never
  // reached the backend, and because the text was unchanged the block wasn't marked dirty, so
  // the next refreshDocumentFills() rewrote innerHTML and wiped it off the screen too.
  //
  // serializeRuns is the inverse of blockHtml: read the spans back out as runs. Kyle's
  // templates genuinely mix formats inside one paragraph \u2014 GC Resinous block 112 is 20
  // segments mixing 9pt and 8pt with italic and underline \u2014 so flattening was never
  // acceptable, it just wasn't visible until somebody tried to edit one.
  const F = window.TWFmt;                       // run algebra (proposal-format-core.js)
  const RUN_KEYS = F.RUN_KEYS;

  /** The computed run format of a node, walking up to (not past) the block. */
  function fmtAt(node, stop) {
    const out = { bold: null, italic: null, underline: null, size_pt: null };
    let el = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
    // Read the nearest declaration for each property. Inline styles only \u2014 the block's own
    // inherited size is the template's and must stay null so the docx keeps inheriting it,
    // rather than being pinned to whatever the browser computed.
    while (el && el !== stop && el !== document.body) {
      const s = el.style;
      if (out.bold === null && s.fontWeight) out.bold = Number(s.fontWeight) >= 600;
      if (out.italic === null && s.fontStyle) out.italic = s.fontStyle === "italic";
      if (out.underline === null && s.textDecorationLine) {
        out.underline = s.textDecorationLine.includes("underline");
      }
      if (out.underline === null && s.textDecoration) {
        out.underline = String(s.textDecoration).includes("underline");
      }
      if (out.size_pt === null && s.fontSize && s.fontSize.endsWith("pt")) {
        out.size_pt = parseFloat(s.fontSize);
      }
      el = el.parentElement;
    }
    return out;
  }

  const sameFmt = (a, b) => RUN_KEYS.every(k => a[k] === b[k]);

  /** Every text position in the block, in document order \u2014 the ONE walker behind both the
   *  serialised runs and the toolbar's selection offsets.
   *
   *  Those two have to agree on what "character 12" means, or the toolbar formats different
   *  words than the estimator selected. Deriving both from a single traversal makes that
   *  agreement structural instead of two similar-looking walkers promising to stay in step.
   *
   *  Synthetic newlines (a BR, and the break before a nested DIV/P) carry `node: null`: they
   *  are real characters to the serialiser, but there is no text node to put a caret in.
   *  `tok` is the nearest enclosing token fill, so a format can be re-rendered without
   *  dissolving `.tw-fill` spans back into plain text. */
  function segmentsOf(el) {
    const segs = [];
    const push = (text, node, n2) => {
      if (!text) return;
      const fill = n2 && n2.parentElement ? n2.parentElement.closest(".tw-fill[data-token]") : null;
      segs.push({ text: text, fmt: fmtAt(n2, el), node: node,
                  tok: fill && el.contains(fill) ? fill.dataset.token : null });
    };
    const walk = (node) => {
      node.childNodes.forEach(n => {
        if (n.nodeType === Node.TEXT_NODE) {
          push(String(n.nodeValue).replace(/\u00a0/g, " "), n, n);
          return;
        }
        if (n.nodeType !== Node.ELEMENT_NODE) return;
        if (n.tagName === "BR") { push("\n", null, n); return; }
        if (/^(DIV|P)$/.test(n.tagName)) {
          const last = segs[segs.length - 1];
          if (last && !last.text.endsWith("\n")) push("\n", null, n);
        }
        walk(n);
      });
    };
    walk(el);
    return segs;
  }

  /** Merge adjacent segments that agree on `keyOf`, then drop the internals. */
  function mergeSegs(segs, alsoToken) {
    const out = [];
    for (const s of segs) {
      const prev = out[out.length - 1];
      if (prev && sameFmt(prev._f, s.fmt) && (!alsoToken || prev._tok === s.tok)) {
        prev.text += s.text;
        continue;
      }
      out.push({ text: s.text, _f: s.fmt, _tok: s.tok });
    }
    return out;
  }

  /** A block's content as runs: [{text, bold?, italic?, underline?, size_pt?}].
   *
   *  Adjacent identical formats are merged, so a paragraph the estimator never formatted
   *  comes back as ONE run and the override stays as small as the old text-only one.
   *  Deliberately merges on format ALONE, ignoring token boundaries: splitting there would
   *  push every fill-carrying block onto the richer payload shape and past `runsArePlain`,
   *  changing what gets sent for blocks nobody formatted. */
  function serializeRuns(el) {
    return mergeSegs(segmentsOf(el), false).map(r => {
      const out = { text: r.text };
      for (const k of RUN_KEYS) if (r._f[k] !== null) out[k] = r._f[k];
      return out;
    });
  }

  /** The editing view of the same content: also split at token boundaries, so re-rendering
   *  after a format can put the `.tw-fill` spans back exactly where they were. */
  function editRuns(el) {
    return mergeSegs(segmentsOf(el), true).map(r => {
      const out = { text: r.text, tok: r._tok };
      for (const k of RUN_KEYS) if (r._f[k] !== null) out[k] = r._f[k];
      return out;
    });
  }

  /** The runs to STORE in the draft: `editRuns` shape, with each run's token recorded when —
   *  and only when — replaying that token's CURRENT value into it is provably safe.
   *
   *  WHY A TOKEN NAME IS SAVED AT ALL. A stored run carries the RESOLVED text ("5,200 SF"),
   *  because that is what the writer puts in the .docx and there is no new way for a raw
   *  `{{token}}` to reach a customer. But a reload has to rebuild the paragraph from this
   *  entry, and rebuilding it from resolved text alone freezes whatever the estimate said when
   *  the formatting was applied: bold one word of a WORK row, then correct the square footage
   *  on Estimate Review, and the proposal would print the OLD number for good. The token name
   *  is what lets the restore re-substitute, and it is also what puts the `.tw-fill` span back
   *  in one piece — one span per tagged run, so no fill is orphaned and none is duplicated.
   *
   *  THE TWO CASES WHERE REPLAYING WOULD DESTROY SOMETHING, both refused here rather than at
   *  restore time, because this is where the evidence is:
   *
   *   1. `textChanged` — the estimator typed somewhere in this paragraph. `{{scope_notes}}`
   *      renders as an editable fill, and rewording the scope straight in the document is a
   *      first-class use of this editor, so their characters may live INSIDE a fill span. Once
   *      the words differ from the pristine rendering the text belongs to them and no run may
   *      be replaced by a sidebar value. Untouched words mean untouched fills, by definition.
   *   2. A token that appears in more than one run — formatting HALF a value splits its fill.
   *      Writing the whole value into each half would duplicate it on screen and in the
   *      document, so both halves keep their stored text.
   *
   *  Refusing is never worse than today: an untagged run restores to exactly the text the old
   *  code restored. */
  function storedRuns(el, textChanged) {
    const runs = editRuns(el).map(r => {
      const out = { text: r.text };
      for (const k of RUN_KEYS) if (r[k] !== undefined) out[k] = r[k];
      if (!textChanged && r.tok) out.tok = r.tok;
      return out;
    });
    const seen = new Map();
    for (const r of runs) if (r.tok) seen.set(r.tok, (seen.get(r.tok) || 0) + 1);
    for (const r of runs) if (r.tok && seen.get(r.tok) !== 1) delete r.tok;
    // Coalesce AFTER the token pass: dropping a token merges the run back into its neighbours,
    // so a paragraph nobody could safely tag ships the same run list it always did.
    return F.coalesce(runs);
  }

  // ── Word-like formatting on the focused block ──────────────────────────────
  //
  // Bold / italic / underline / size, applied by rebuilding the block from its runs — NOT via
  // execCommand. execCommand emits <b>/<i>/<u> TAGS, and `fmtAt` reads inline STYLES only, so
  // an execCommand bold would look applied on screen and arrive in the .docx as nothing at
  // all. Rendering from runs makes what is on screen and what gets sent the same object.

  const SIZE_CHOICES = [6, 7, 8, 9, 10, 11, 12, 14, 16, 18];
  const MARK_A = "\u0001", MARK_B = "\u0002";   // never occur in proposal text
  let _fmtBusy = false;                          // re-entrancy guard for selectionchange

  /** Like `runStyleCss`, but writes the explicit OFF switches too.
   *
   *  `runStyleCss` emits italic/underline only when true, which is right for the initial
   *  render but makes "turn italic off" unrepresentable: with no inline style `fmtAt` reads
   *  null = inherit, and the paragraph silently keeps the template's italic. Kept separate so
   *  the initial render from the backend's runs is untouched. */
  function runEditCss(s) {
    let css = runStyleCss(s);
    if (s.italic === false) css += "font-style:normal;";
    if (s.underline === false) css += "text-decoration-line:none;";
    return css;
  }

  // The run algebra lives in proposal-format-core.js so the tests drive the same code the
  // page does, rather than a copy of it that can drift.
  const coalesce = F.coalesce, patchRuns = F.patchRuns, runsLength = F.runsLength;

  /** Runs → the block's innerHTML. Inverse of `editRuns`.
   *
   *  A newline stays a NEWLINE CHARACTER rather than becoming a `<br>`, because `.tw-block` is
   *  `white-space: pre-wrap` and that is the shape the caret can be put after. `pointAt` can
   *  only place a caret in a TEXT node — a `<br>` is a synthetic newline it has to skip — so a
   *  break rendered as `<br>` at the end of a paragraph left the caret at the end of the
   *  PREVIOUS line, and the next character typed went in above the break instead of after it.
   *  Blink makes the same choice for the same reason: its own editor inserts "\n" rather than a
   *  break element when the enclosing style preserves newlines.
   *
   *  This also makes a re-render agree with the FIRST render: `blockHtml`/`fillHtml` never
   *  converted newlines either, so a block that came from the backend with a break in it and
   *  the same block after a format were built differently. */
  function renderRuns(el, runs) {
    let html = "";
    for (const r of runs) {
      let inner = escHtml(String(r.text));
      if (r.tok) inner = `<span class="tw-fill" data-token="${escHtml(r.tok)}">${inner}</span>`;
      const css = runEditCss(r);
      html += css ? `<span style="${css}">${inner}</span>` : inner;
    }
    el.innerHTML = html || "<br>";
  }

  /** Character offset → a caret position, skipping synthetic newlines (no text node to sit in). */
  function pointAt(el, offset) {
    let pos = 0, last = null;
    for (const s of segmentsOf(el)) {
      if (s.node) {
        if (offset <= pos + s.text.length) return { node: s.node, offset: offset - pos };
        last = { node: s.node, offset: s.text.length };
      }
      pos += s.text.length;
    }
    return last;
  }

  function placeSelection(el, start, end) {
    const a = pointAt(el, start), b = pointAt(el, end);
    if (!a || !b) return;
    const r = document.createRange();
    try {
      r.setStart(a.node, Math.max(0, Math.min(a.offset, a.node.length)));
      r.setEnd(b.node, Math.max(0, Math.min(b.offset, b.node.length)));
    } catch { return; }
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(r);
  }

  /** The selection as [start, end] character offsets into the block, or null if it is elsewhere.
   *
   *  Two control-character markers are dropped at the boundaries and the offsets read back out
   *  of the serialised text. Letting the browser's own Range place them beats re-deriving
   *  offsets from container/offset pairs across nested spans and half-selected fills. The
   *  markers are removed and the selection restored before returning, so this reads as a pure
   *  query — `_fmtBusy` keeps the restore from re-entering through `selectionchange`. */
  function selectionRange(el) {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount) return null;
    const r = sel.getRangeAt(0);
    if (!el.contains(r.startContainer) || !el.contains(r.endContainer)) return null;
    const prev = _fmtBusy;
    _fmtBusy = true;
    try {
      const a = document.createTextNode(MARK_A), b = document.createTextNode(MARK_B);
      const rb = r.cloneRange(); rb.collapse(false); rb.insertNode(b);
      const ra = r.cloneRange(); ra.collapse(true); ra.insertNode(a);
      const text = segmentsOf(el).map(s => s.text).join("");
      a.remove(); b.remove();
      el.normalize();
      let i = text.indexOf(MARK_A), j = text.indexOf(MARK_B);
      if (i < 0 || j < 0) return null;
      if (j > i) j -= 1;                    // MARK_A shifted everything after it along by one
      const out = [Math.min(i, j), Math.max(i, j)];
      placeSelection(el, out[0], out[1]);   // put back what the markers disturbed
      return out;
    } catch {
      return null;
    } finally {
      _fmtBusy = prev;
    }
  }

  /** What the selection currently looks like. A key is `undefined` when the selection spans
   *  more than one value ("mixed"), so a toggle can decide between on and off honestly.
   *
   *  `fallback` is the range to use when the live selection is NOT inside `el`; `live` reports
   *  which of the two was used. Kyle, 2026-08-24, on the format bar that floated beside the
   *  caret: "Can we move this editable box on top as well but keep it static like a ribbon in a
   *  word document." A ribbon at the top of the page gets pressed at moments a bar beside the
   *  caret never was — after focus has gone to the Tax select, the pricing rail, the ribbon's own
   *  size dropdown — and the widening below then reads as "the whole paragraph" and silently
   *  reformats every word in it instead of the three that were highlighted. So the ribbon's
   *  remembered range (`fmtRange`) is passed in, and the press lands where the estimator was
   *  looking.
   *
   *  The clamp is for the fallback: a remembered range can outlive the edit that shortened the
   *  paragraph it points into. A live range is in bounds by construction. */
  function selectionFormat(el, fallback) {
    const runs = editRuns(el);
    const total = runsLength(runs);
    const live = selectionRange(el);
    const sel = live || fallback || null;
    let start = sel ? sel[0] : 0, end = sel ? sel[1] : total;
    start = Math.max(0, Math.min(start, total));
    end = Math.max(start, Math.min(end, total));
    // A collapsed caret means "this whole paragraph". The estimator asked for a section to
    // change size; a pending style that only affects the next keystroke would read as nothing
    // having happened. A remembered caret means the same thing for the same reason.
    if (start === end) { start = 0; end = total; }
    const f = F.summarize(runs, start, end);
    return { bold: f.bold, italic: f.italic, underline: f.underline, size_pt: f.size_pt,
             range: [start, end], empty: total === 0, live: !!live };
  }

  function markEdited(el, formatted) {
    if (formatted) el.classList.add("tw-fmt");
    // Reuse the one input handler: dirty flags, the $/SF warning, override persistence and
    // terms repagination all already hang off it.
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }

  /** Replace [start, end) with ONE newline, through the same run algebra as a paste.
   *
   *  Kyle, 2026-08-19: "when he pressed enter to add spacing it did not generate in the
   *  proposal." Two separate things were wrong. The server half is fixed in
   *  proposal_writer._normalize_work_label_formatting (it was joining the run's `<w:br/>`s away
   *  while re-bolding the WORK labels). This is the browser half: what the BROWSER does to a
   *  contenteditable on Enter is not one thing. Depending on the engine and on `white-space`
   *  it inserts a `<br>`, a bare "\n", or a wrapper `<div>` carrying its own placeholder
   *  `<br>` — and serializeBlock reads that last shape as TWO newlines, so one Enter could
   *  become a blank line and two could become three. Splicing the newline in ourselves makes
   *  one Enter exactly one line break, on every engine.
   *
   *  A line break, not a paragraph break, is also the only thing this editor can honestly
   *  represent: a `.tw-block` IS one Word paragraph, identified by an id from the backend's
   *  walk over the template, and the editor cannot invent a second one. `<w:br/>` inside the
   *  run is what the writer emits for a "\n" (_write_t_text), which is the same line break.
   *
   *  Returns the caret offset the break leaves behind, or -1 when there was nothing to do. */
  function insertBreakAt(el, start, end) {
    if (!el || !(start >= 0) || !(end >= start)) return -1;
    renderRuns(el, F.spliceRuns(editRuns(el), start, end, [{ text: "\n", tok: null }]));
    return start + 1;
  }

  /** Are these two run lists the same text carrying the same formatting?
   *
   *  Field by field rather than JSON.stringify: both are plain objects, but they come from
   *  different producers (editRuns and patchRuns) and key ORDER is not part of what makes two runs
   *  equal. */
  function runsEqual(a, b) {
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) {
      if (String(a[i].text) !== String(b[i].text)) return false;
      for (const k of RUN_KEYS) if (a[i][k] !== b[i][k]) return false;
    }
    return true;
  }

  /** Is the live selection inside the document at all?
   *
   *  Read BEFORE renderRuns, because that rewrites the innerHTML the selection points into. */
  function selectionInSurface() {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount || !docSurface) return false;
    const r = sel.getRangeAt(0);
    return !!r && docSurface.contains(r.startContainer);
  }

  function applyFormat(el, patch, range) {
    const runs = editRuns(el);
    let start, end;
    if (range) { start = range[0]; end = range[1]; }
    else {
      const f = selectionFormat(el);
      start = f.range[0]; end = f.range[1];
    }
    if (end <= start) return false;
    const next = patchRuns(runs, start, end, patch);
    // A PRESS THAT CHANGES NOTHING IS NOT AN EDIT. Reset on a paragraph carrying no formatting
    // deletes nothing; Bold on already-bold words adds nothing. markEdited ran regardless, which
    // set tw-fmt, which the input handler reads as dirty, which persists an override for a
    // paragraph nobody touched — breaking the guarantee paraPatch's own docstring states, that an
    // untouched document ships no overrides and the generated .docx stays byte-identical. It also
    // routes the block permanently onto the refreshFillsInPlace branch.
    //
    // It matters MORE now the bar is a ribbon. fmtBlock outlives focus and is cleared only by a
    // non-block editable or a template reload, so the row stays aimed at the last paragraph
    // touched for the rest of the session, and one stray press on Reset writes an override for a
    // paragraph the estimator has visually left.
    if (runsEqual(runs, next)) return false;
    const hadDocSelection = selectionInSurface();
    renderRuns(el, next);
    // Only put the selection back if it was in the document to begin with. A ribbon press made
    // with the caret in a sidebar field would otherwise paint a highlight the estimator never
    // made, over the .tw-fmt-target background — and in an engine that focuses the editing host on
    // a programmatic selection, pull their caret out of that field mid-entry so the next digits
    // they type land in the proposal paragraph.
    if (hadDocSelection) placeSelection(el, start, end);
    markEdited(el, true);
    return true;
  }

  function toggleFormat(el, key, fallback) {
    const f = selectionFormat(el, fallback);
    if (f.empty) return;
    const patch = {};
    patch[key] = F.nextToggle(f[key]);
    applyFormat(el, patch, f.range);
    showFmtBar(el);
  }

  // ── Paste ──────────────────────────────────────────────────────────────────
  // There was no paste handler at all: Word's HTML landed in the DOM as arbitrary markup —
  // classes, mso-* styles, font tags, tables — and `fmtAt` silently dropped nearly all of it.
  // Pasted content is now reduced to the four switches we can actually carry into the .docx.

  function runsFromHtml(html) {
    const box = document.createElement("div");
    box.innerHTML = String(html);
    box.querySelectorAll("script,style,meta,link,title,object,iframe,svg,img").forEach(n => n.remove());
    const runs = [];
    const walk = (node, inherited) => {
      node.childNodes.forEach(n => {
        if (n.nodeType === Node.TEXT_NODE) {
          const t = String(n.nodeValue).replace(/\u00a0/g, " ").replace(/[\r\t]/g, "");
          if (t) runs.push(Object.assign({}, inherited, { text: t }));
          return;
        }
        if (n.nodeType !== Node.ELEMENT_NODE) return;
        const tag = n.tagName;
        if (tag === "BR") { runs.push(Object.assign({}, inherited, { text: "\n" })); return; }
        const f = F.fmtFromPasted(tag, n.style || {}, inherited);
        walk(n, f);
        if (/^(P|DIV|LI|TR|H[1-6]|BLOCKQUOTE)$/.test(tag)) {
          const last = runs[runs.length - 1];
          if (last && !last.text.endsWith("\n")) runs.push({ text: "\n" });
        }
      });
    };
    walk(box, {});
    while (runs.length && runs[runs.length - 1].text === "\n") runs.pop();   // trailing block break
    return coalesce(runs.map(r => {
      const out = { text: r.text, tok: null };
      for (const k of RUN_KEYS) if (r[k] !== undefined) out[k] = r[k];
      return out;
    }));
  }

  // ── Paragraph properties: the bullet, and the indent ───────────────────────
  // Kyle, 2026-08-20, on the proposal editor:
  //   "I cant dletet the bullet points"
  //   "There is indentation in this but I cant remove tat if I want to to be aligned on the
  //    polished concrete?"
  //
  // Both are Word PARAGRAPH properties (w:numPr and w:ind), which the format bar has never been
  // able to reach: it rewrites RUNS. The backend half is proposal_writer.para_props /
  // apply_para_props; this is the toolbar, and the state it has to keep honest.
  //
  // INDENTS ARE TWIPS, absolute, exactly as the backend stores them. One step is 288 twips,
  // which is the WORK/NOTES list level's own indent in Kyle's templates, so one outdent on an
  // untouched WORK row lands at 0 and the row aligns with its neighbours. That is literally the
  // second complaint.
  const INDENT_STEP_TW = 288;
  const INDENT_MAX_TW = 2880;      // 2 inches, same clamp as sanitize_para_props
  const TWIPS_PER_PT = 20;

  /** The template's own paragraph properties for a block, or null when we cannot tell.
   *
   *  Null is the answer for a block whose record carries no `para` — a browser replaying a
   *  pre-v5 cached /api/proposal-template response. Without it there is no `locked`, and
   *  offering an un-bullet on a numbered TERMS AND CONDITIONS clause renumbers the contract.
   *  So no metadata means no controls; _BLOCK_SCHEMA_VERSION was bumped so it never comes up. */
  function paraBase(id) {
    const b = blockById.get(Number(id));
    const p = b && b.para;
    if (!p || typeof p !== "object") return null;
    return { bullet: !!p.bullet, indent: Math.max(0, Number(p.indent) || 0), locked: !!p.locked };
  }

  /** Where the paragraph is NOW: what the estimator set, else the template's own state. */
  function paraNow(id) {
    const base = paraBase(id);
    if (!base) return null;
    const set = paraById.get(Number(id));
    return set ? { bullet: !!set.bullet, indent: Math.max(0, Number(set.indent) || 0), locked: base.locked }
               : { bullet: base.bullet, indent: base.indent, locked: base.locked };
  }

  /** The `para` patch for one block, or null when it still matches the template.
   *
   *  Comparing against the template rather than persisting every paragraph keeps an untouched
   *  document shipping an empty paragraph_overrides list, which is what makes the generated
   *  .docx byte-identical to the one this feature did not exist for. */
  function paraPatch(id) {
    const base = paraBase(id), now = paraNow(id);
    if (!base || !now) return null;
    if (now.bullet === base.bullet && now.indent === base.indent) return null;
    return { bullet: now.bullet, indent: now.indent };
  }

  /** Coerce a `para` field read back off a saved draft. Mirrors sanitize_para_props: unknown
   *  keys dropped, indent clamped, and an unusable value means "no paragraph change". */
  function sanitizeParaPatch(raw) {
    if (!raw || typeof raw !== "object") return null;
    const out = {};
    if (typeof raw.bullet === "boolean") out.bullet = raw.bullet;
    const n = Number(raw.indent);
    if (raw.indent !== undefined && raw.indent !== null && Number.isFinite(n)) {
      out.indent = Math.max(0, Math.min(INDENT_MAX_TW, Math.round(n)));
    }
    return ("bullet" in out || "indent" in out) ? out : null;
  }

  /** Show one paragraph's properties on screen, so the preview matches what prints.
   *
   *  Inline styles, and only ever on a paragraph the estimator changed: an untouched block keeps
   *  the class-driven look it has always had, and this surface is a to-scale preview registered
   *  against baked page artwork, so a stray pixel of reflow is a worse bug than a plain toolbar. */
  /** Put one paragraph where the FILE says it goes, not where a class guessed.
   *
   *  Hanz, 2026-08-25: "is this really the spacing format for the epoxy? Because it doesnt follow
   *  the exact font size and spacing on the editor in which it should."
   *
   *  He was right, and the generated document was the honest one. In the epoxy template every WORK
   *  row — System, Area, Scope, Schedule, Exclusions, Notes — is the same list level
   *  (`left=288 hanging=288`), all 8pt, with NO before/after spacing at all. The editor showed an
   *  indented sub-group that exists nowhere in the file, because geometry came from hand-picked
   *  class values (`.tw-li { margin-left: 14pt; padding-left: 9pt }`) rather than from the record.
   *
   *  THE HANGING INDENT IS THE WHOLE TRICK. Word puts the TEXT at `left` and the marker at
   *  `left - hanging`. Reading only `left` — which is all the editor had — draws the bullet where
   *  the text belongs and pushes the row in by the hanging distance. So: margin-left carries
   *  `left - hanging` and padding-left carries `hanging`, which is the gap `.tw-li::before` sits
   *  in at `left: 0`. For the WORK rows that is margin 0 / padding 14.4pt: text at 14.4pt, bullet
   *  hard against the margin, exactly as it prints.
   *
   *  `line` is 240ths of a line under `lineRule="auto"` (240 single, 276 = 1.15, 300 = 1.25) and
   *  twips under `exact`/`atLeast`, so the rule decides the unit. Absent stays absent — the
   *  stylesheet's own default then applies, rather than this asserting a number the file never
   *  gave.
   *
   *  `st` is the LIVE state (what the estimator has set); `tpl` is the template's record, which is
   *  where hanging, first-line and spacing come from since the toolbar cannot change them. */
  function applyParaGeom(el, st, tpl) {
    const leftTw = Math.max(0, Number((st && st.indent) || 0));
    const hangTw = Math.max(0, Number((tpl && tpl.hanging) || 0));
    const pt = (tw) => (tw / TWIPS_PER_PT) + "pt";
    // Never negative: a paragraph whose hanging exceeds its left indent would pull the marker off
    // the page. Word clamps at the margin and so does this.
    el.style.marginLeft = pt(Math.max(0, leftTw - hangTw));
    el.style.paddingLeft = hangTw ? pt(hangTw) : "0";
    const firstTw = Number((tpl && tpl.first_line) || 0);
    el.style.textIndent = firstTw ? pt(firstTw) : "";
    const sp = (tpl && tpl.spacing) || {};
    el.style.marginTop = sp.before ? pt(Number(sp.before)) : "0";
    el.style.marginBottom = sp.after ? pt(Number(sp.after)) : "0";
    if (sp.line && sp.line_rule === "auto") el.style.lineHeight = String(Number(sp.line) / 240);
    else if (sp.line) el.style.lineHeight = pt(Number(sp.line));
    else el.style.lineHeight = "";
  }

  function applyParaToEl(el, st) {
    if (!el || !st) return;
    const bullet = !!st.bullet;
    el.classList.toggle("tw-li", bullet);
    // The template's own record, for the measurements the toolbar cannot change. Without it an
    // indent press would rebuild the geometry from `left` alone and undo the hanging indent.
    const rec = blockById.get(Number(el.dataset.id));
    applyParaGeom(el, st, (rec && rec.para) || null);
  }

  /** Record a paragraph's new properties and repaint it. Refuses a locked paragraph. */
  function setParaState(id, patch, el) {
    const base = paraBase(id);
    if (!base || base.locked) return false;
    const clean = sanitizeParaPatch(patch);
    if (!clean) return false;
    const now = paraNow(id);
    const next = { bullet: "bullet" in clean ? clean.bullet : now.bullet,
                   indent: "indent" in clean ? clean.indent : now.indent };
    paraById.set(Number(id), next);
    applyParaToEl(el, next);
    return true;
  }

  /** One toolbar press: the bullet on/off, or one step of indent either way.
   *
   *  Outdent reaches 0 — not "one level in from where the template put it". A WORK row inherits
   *  288 twips from its list level and Kyle wants it flush with the rows around it, so the floor
   *  has to be the margin itself. Indent puts it back. */
  function paraAction(el, action) {
    if (!el) return false;
    const id = Number(el.dataset.id);
    const now = paraNow(id);
    if (!now || now.locked) return false;
    let next;
    if (action === "bullet") next = { bullet: !now.bullet, indent: now.indent };
    else if (action === "indent") next = { bullet: now.bullet, indent: Math.min(INDENT_MAX_TW, now.indent + INDENT_STEP_TW) };
    else if (action === "outdent") next = { bullet: now.bullet, indent: Math.max(0, now.indent - INDENT_STEP_TW) };
    else return false;
    if (!setParaState(id, next, el)) return false;
    // Persist through the same debounce every other edit uses, and repaginate: an indent
    // changes how the line wraps, so the terms flow can need a different page break.
    schedulePersistOverrides();
    if (el.closest && el.closest(".tw-terms-page")) scheduleRepaginate();
    return true;
  }

  // ── The ribbon ─────────────────────────────────────────────────────────────
  // Kyle, 2026-08-24, on the format bar that floated beside the caret:
  //   "Can we move this editable box on top as well but keep it static like a ribbon in a word
  //    document."
  //
  // So it is one row of page chrome — #fmt-ribbon in proposal-review.html, between the step-pill
  // ribbon and the scrolling canvas — always on screen, never moving. Three things that were true
  // of a bar placed next to the block stop being true, and each one is a way to ship a row of
  // buttons that quietly does nothing:
  //
  //  1. IT NO LONGER KNOWS ITS TARGET BY WHERE IT IS. `fmtBlock` used to be set on focusin and
  //     thrown away on focusout, so "visible" and "has a target" were ONE state and the
  //     `!fmtBlock` guard on every button never had to fire. It is now a REMEMBERED target that
  //     outlives the block losing focus — that is what "static" means — and the ribbon goes
  //     INERT when there is genuinely nothing to act on rather than vanishing. That is Word's
  //     own answer, and it is the right one here: a toolbar that disappears is the floating bar
  //     again under a different name.
  //  2. IT NO LONGER KNOWS THE SELECTION EITHER. `fmtRange` keeps the last selection that really
  //     was inside `fmtBlock`, because `selectionFormat` widens to the WHOLE paragraph when it
  //     cannot read one. Beside the caret that was a rare path; from a ribbon it is what happens
  //     every time focus went somewhere else first, and the wrong result is invisible — the
  //     paragraph simply comes out of the generator bold from end to end.
  //  3. IT IS NO LONGER POSITIONED. The old bar was `position: fixed`, placed from the block's
  //     `getBoundingClientRect()`, precisely BECAUSE #doc-zoom scales the document: viewport
  //     coordinates are already post-transform, so there was no scale factor to divide out. The
  //     ribbon sits in the normal flow OUTSIDE that transform, so the zoom cannot scale it and
  //     there is nothing left to compute. The capture-phase `scroll` listener that re-placed it
  //     is gone with it, and it was not free — it re-ran `selectionFormat`, which inserts and
  //     removes marker text nodes inside the paragraph, on every scroll event.
  let fmtBar = null, fmtBlock = null, fmtRange = null, fmtRangeText = null;

  function ensureFmtBar() {
    if (fmtBar) return fmtBar;
    fmtBar = document.createElement("div");
    fmtBar.className = "tw-fmtbar";
    fmtBar.setAttribute("role", "toolbar");
    fmtBar.setAttribute("aria-label", "Text formatting");
    fmtBar.innerHTML =
      '<button type="button" data-fmt="bold" aria-label="Bold" title="Bold (Ctrl+B)"><b>B</b></button>' +
      '<button type="button" data-fmt="italic" aria-label="Italic" title="Italic (Ctrl+I)"><i>I</i></button>' +
      '<button type="button" data-fmt="underline" aria-label="Underline" title="Underline (Ctrl+U)"><u>U</u></button>' +
      '<span class="tw-fmtsep" aria-hidden="true"></span>' +
      // A COMBOBOX, not a dropdown. Hanz, 2026-08-25: "Make this dropdown menu smaller please.
      // ALso make it so that we could type in it."
      //
      // It was a <select> whose width was set by its widest option -- "Template size" -- which is
      // why it dwarfed the buttons beside it. As an input it is 54px and takes any size the
      // document can actually carry, including the half-points the writer supports (10.5pt is a
      // real Word size and there was no way to ask for it).
      //
      // The empty value still means "whatever the template says" -- the placeholder carries that
      // now, and clearing the box restores it. The datalist keeps every size that used to be in
      // the list, so nothing became harder to reach by becoming typeable.
      '<input data-fmt="size" list="tw-size-list" class="tw-fmtsize" type="text"' +
      ' inputmode="decimal" autocomplete="off" placeholder="Size" size="4"' +
      ' aria-label="Text size in points" title="Text size in points — type one or pick from the list">' +
      '<datalist id="tw-size-list">' +
      SIZE_CHOICES.map(n => `<option value="${n}">${n} pt</option>`).join("") +
      '</datalist>' +
      '<span class="tw-fmtsep" data-para="sep" aria-hidden="true"></span>' +
      '<button type="button" data-para="bullet" aria-label="Bullet point"' +
      ' title="Bullet point on or off">▪</button>' +
      '<button type="button" data-para="outdent" aria-label="Decrease indent"' +
      ' title="Less indent (moves left, all the way to the margin)">⇤</button>' +
      '<button type="button" data-para="indent" aria-label="Increase indent"' +
      ' title="More indent (moves right)">⇥</button>' +
      '<span class="tw-fmtsep" aria-hidden="true"></span>' +
      '<button type="button" data-fmt="reset" title="Back to the template’s own formatting">Reset</button>';
    // The ribbon's own row. `document.body` is the last resort only: a page without the host
    // still gets a working toolbar at the end of the document, which beats what the old CSS
    // would have done to an unplaced `position: fixed` element — park it over the top corner.
    (document.getElementById("fmt-ribbon") || document.body).appendChild(fmtBar);

    // Never let the ribbon take focus: the block has to keep its selection for the format to
    // land on the words the estimator actually highlighted. This matters MORE than it did when
    // the bar floated beside the caret — the ribbon is page chrome outside the document, so a
    // click on it that was allowed to focus would move focus clean out of the editor and there
    // would be no caret left to format. The size `select` cannot be covered this way
    // (preventDefault on its mousedown stops it opening at all), which is what `fmtRange` is for.
    fmtBar.addEventListener("mousedown", (e) => {
      // The size box is exempt for the same reason the <select> was: a control you have to put a
      // caret in cannot have its mousedown cancelled, or it can never be focused at all. Focus
      // therefore genuinely leaves the paragraph when it is used, which is precisely what the
      // remembered range (`fmtRange`) exists to survive -- and it does, because the focusin
      // listener that clears the ribbon's target is scoped to docSurface and this row is not in it.
      if (!e.target.closest("select, input")) e.preventDefault();
    });
    fmtBar.addEventListener("click", (e) => {
      // The REMEMBERED block, re-checked against the live document — not whatever had focus,
      // because from a ribbon there is frequently nothing focused at all.
      const el = fmtTargetBlock();
      // Nothing to act on. Re-render rather than just returning: the ribbon has to LOOK dead
      // from here on, and a press is where an orphaned target gets discovered if some future path
      // empties the surface without going through clearDocSurface.
      if (!el) { renderFmtBar(); return; }
      // Paragraph properties first: they are a different channel from the run formatting below
      // (the `para` field on the override, not `runs`), and they act on the whole paragraph
      // regardless of what is selected inside it — so they need no range and work unchanged
      // from a ribbon.
      const pbtn = e.target.closest("button[data-para]");
      if (pbtn) {
        e.preventDefault();
        paraAction(el, pbtn.dataset.para);
        showFmtBar(el);
        return;
      }
      const btn = e.target.closest("button[data-fmt]");
      if (!btn) return;
      e.preventDefault();
      // A box selection means the press is about every line in it, not just the caret's own. Each
      // block is formatted over its whole length -- there is no per-block range to remember,
      // because the estimator selected lines rather than characters.
      if (boxSel && boxSel.length > 1) {
        // TEMPLATE PARAGRAPHS ONLY, for now. A computed line's channel stores its TEXT and
        // nothing else, so a bold applied here would show on screen and reach the customer's
        // document as plain text -- the formatting silently dropped somewhere between the two.
        // Better to leave those rows visibly untouched than to lie about them; carrying runs
        // through the three computed-line channels is the next piece of work.
        const els = boxSel.filter(one => one.classList.contains("tw-block"));
        els.forEach(one => {
          const total = runsLength(editRuns(one));
          if (!total) return;
          if (btn.dataset.fmt === "reset") {
            applyFormat(one, { bold: null, italic: null, underline: null, size_pt: null }, [0, total]);
          } else {
            toggleFormat(one, btn.dataset.fmt, [0, total]);
          }
        });
        showFmtBar(el);
        return;
      }
      if (btn.dataset.fmt === "reset") {
        const f = selectionFormat(el, fmtRangeFor(el));
        applyFormat(el, { bold: null, italic: null, underline: null, size_pt: null }, f.range);
        showFmtBar(el);
        return;
      }
      toggleFormat(el, btn.dataset.fmt, fmtRangeFor(el));
    });
    /** The typed size, or undefined when the box does not hold a usable one.
     *
     *  A <select> could only ever offer valid values; an input cannot, so the validation the
     *  client never needed is needed now. `Number("abc")` is NaN, and NaN is the one value that
     *  defeats `runsEqual` -- NaN !== NaN, so every press would look like a change, mark the
     *  paragraph edited and persist an override for a no-op. It also serialises as null and is
     *  dropped by the server, so the estimator would see a dirty document and no effect.
     *
     *  Bounds and granularity mirror the backend deliberately (main.py's sanitizer and
     *  proposal_writer's own copy both take 1..200, and the writer stores half-points), so the box
     *  cannot ask for something the document will silently refuse. */
    function typedSize(raw) {
      const t = String(raw == null ? "" : raw).trim().replace(/\s*pt$/i, "");
      if (t === "") return null;                        // empty = back to the template's own size
      const n = Number(t);
      if (!Number.isFinite(n)) return undefined;
      const half = Math.round(n * 2) / 2;               // the writer's real granularity
      if (half < 1 || half > 200) return undefined;
      return half;
    }

    /** Apply whatever the size box holds to the remembered range.
     *
     *  A named function rather than a listener both paths reach: Enter has to commit without
     *  waiting for a blur, and synthesizing a change event to reuse the listener would work in a
     *  browser while making the behaviour unreachable to anything that drives the code directly.
     */
    function commitSize(box) {
      const el = fmtTargetBlock();
      if (!el) { renderFmtBar(); return; }
      const v = typedSize(box.value);
      // `fmtRange` and not whatever the selection is NOW: the size box is one of the two controls
      // the mousedown guard cannot cover, so focus has genuinely left the paragraph by the time
      // this runs. Without the remembered range the size would land on the whole paragraph
      // instead of the highlighted words.
      const f = selectionFormat(el, fmtRangeFor(el));
      if (v === undefined) {
        // REFUSED, and the refusal has to be visible. renderFmtBar's write-back deliberately
        // skips a focused box (or it would eat half-typed text) and Enter commits without
        // blurring -- so the rejected text would otherwise just sit there looking accepted.
        // Putting the paragraph's real size back is the whole signal the estimator gets.
        box.value = f.size_pt ? String(f.size_pt) : "";
        return;
      }
      applyFormat(el, { size_pt: v }, f.range);
      showFmtBar(el);
    }

    fmtBar.addEventListener("change", (e) => {
      const box = e.target.closest && e.target.closest("input[data-fmt='size']");
      if (!box) return;
      commitSize(box);
    });
    // Enter commits without leaving the box, Escape puts back what the paragraph says. Both stop
    // propagating: the window-level Escape handler collapses an expanded text box, which is not
    // what somebody abandoning a typed size is asking for.
    fmtBar.addEventListener("keydown", (e) => {
      const box = e.target.closest && e.target.closest("input[data-fmt='size']");
      if (!box) return;
      if (e.key === "Enter") {
        e.preventDefault();
        commitSize(box);
      } else if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        renderFmtBar();
      }
    });
    return fmtBar;
  }

  // ── selecting a whole text box ─────────────────────────────────────────────
  //
  // Hanz, 2026-08-26: "When I control A it doesnt select everything in Work."
  //
  // ONE PRESS, THE WHOLE BOX. The two-press ladder that shipped first (line, then box) is gone:
  // its first rung cancelled the browser's own select-all -- which, with the box as the single
  // editing host, would already have selected every line in it -- and replaced it with a
  // one-line selection. So the feature's own first press was what made Ctrl+A look broken, and
  // the widen that put the box back had nothing on screen to advertise it.
  //
  // Scope is one text box. The box is a real container -- `.tw-txbx[data-box-id]`, the
  // absolutely-positioned div registered against the baked page artwork -- so this is a
  // `closest()` call rather than a guess about which paragraphs look grouped. On the terms pages
  // there is no box, so the page is the unit.
  //
  // `boxSel` is the PAINTED cue, and it is kept alongside the native range rather than replaced by
  // it: the range is gone the moment the caret moves, while the class is what the ribbon and the
  // delete key read to know they are acting on a whole box.
  let boxSel = null;

  /** Every editable LINE inside `el`'s box, in document order.
   *
   *  Two families, and they are not interchangeable. `.tw-block` is a real template paragraph with
   *  an id and a para record. `.tw-line-edit` is a COMPUTED line -- the PRICE rows, the
   *  {{#system}} rows, the NOTES bullets -- which the page rebuilds from the estimate and which
   *  persists through its own channel keyed by `data-po-linekey` / `data-sys-line` rather than by
   *  block id.
   *
   *  Both are collected, because "highlight everything in this box" is a claim about what the
   *  estimator can see, not about which save channel a row happens to use. What differs is what a
   *  press can then DO to each -- see clearBoxLine and the format handler. */
  function boxLines(el) {
    const box = editingBox(el);
    if (!box) return [];
    return Array.from(box.querySelectorAll(LINE_SEL));
  }

  /** Every editable line family, in one place so no selector can drift from another.
   *
   *  .tw-note-edit used to be missing from these lists, which is why a NOTES bullet answered none
   *  of the box-wide gestures: it is the one family that does not also carry .tw-line-edit. */
  const LINE_SEL = ".tw-block, .tw-line-edit, .tw-note-edit";

  /** The editable line the caret is in, whichever family it belongs to. */
  function lineAt(node) {
    if (!node || !node.closest) return null;
    return node.closest(LINE_SEL);
  }

  /** The line the SELECTION is in. This is the one that matters now.
   *
   *  With the box as the editing host, an input or focusin event's target is the BOX -- the
   *  browser fires editing events at the host, not at the node the caret happens to sit in -- so
   *  asking the target for its .tw-block resolves to nothing. The caret's own position is the
   *  only thing left that says which line was edited. */
  function lineAtSelection() {
    const sel = typeof window !== "undefined" && window.getSelection ? window.getSelection() : null;
    if (!sel || !sel.rangeCount) return null;
    let n = sel.getRangeAt(0).startContainer;
    if (n && n.nodeType !== 1) n = n.parentNode;
    return lineAt(n);
  }

  /** The line an editing event is about: its own target when it has one, else the caret's.
   *
   *  Both paths are kept deliberately. A synthesized event that names a line still resolves to
   *  that line, which is how every scenario in the harnesses reads -- and how clearBoxLine's own
   *  dispatch reaches the right channel. A real browser event names the box, and falls through to
   *  the selection. */
  function lineTarget(e) {
    const t = e && e.target && e.target.closest ? lineAt(e.target) : null;
    return t || lineAtSelection();
  }

  /** The editing host a node sits in: its text box, or the terms page when there is no box.
   *
   *  Order matters. Page 1 CONTAINS every box, so .tw-txbx has to be asked first or every box
   *  edit would resolve to the page and sweep the whole sheet. */
  function editingBox(node) {
    let n = node;
    if (n && n.nodeType != null && n.nodeType !== 1) n = n.parentNode;
    if (!n || !n.closest) n = lineAtSelection();
    if (!n || !n.closest) return null;
    const host = n.closest(".tw-txbx") || n.closest(".tw-terms-page") || n.closest(".tw-page");
    if (host) return host;
    // Nothing above it claims to be a host, but it IS in the document: the surface is the unit.
    // Reached by the geometry-less fallback layout and by any future path that mounts a paragraph
    // without a page around it -- and returning null there would mean an edit that saves nothing,
    // silently, which is the failure this whole change exists to avoid.
    return docSurface && docSurface.contains && docSurface.contains(n) ? docSurface : null;
  }

  /** The selection, broken down per line: [{el, start, end}] in document order.
   *
   *  The same trick selectionRange has used in production since the ribbon shipped -- drop two
   *  control-character markers at the range's boundaries and read the offsets back out of the
   *  serialised text -- generalised from one block to every line the range touches. Deriving
   *  offsets from container/offset pairs across nested .tw-fill spans and half-selected runs is
   *  the thing that trick exists to avoid, and it does not get easier with more elements in play.
   *
   *  A line the range covers ENTIRELY holds neither marker and reports its whole length. That is
   *  the case that matters: it is how "these four lines are selected" becomes four splices.
   *
   *  WHICH lines are covered is decided by the markers too, not by `Range.intersectsNode`. That
   *  predicate answers "yes" for a node the range merely TOUCHES, and the two cases are
   *  indistinguishable once you have the offsets: a fully covered empty line reports start == end
   *  == 0, and so does a line the range only abutted. The marker positions say it exactly -- the
   *  line holding MARK_A, the line holding MARK_B, and everything between them in document
   *  order -- and a marker that lands outside any line at all (directly between two paragraphs)
   *  falls back to that end of the box, which is where the selection visibly reaches. */
  /** What one line reports, given its serialised text with the two markers still in it.
   *
   *  Pure arithmetic, split out on purpose. selectionLines can only run against a live browser
   *  Range, so nothing executes it -- and this is the half where the off-by-ones live, so it is
   *  the half that has to be executable on its own. Four arrangements, and every one of them
   *  happens in practice:
   *
   *    both markers   a selection that starts and ends inside this line
   *    MARK_A only    the selection starts here and runs on into the next line
   *    MARK_B only    the selection started above and ends here
   *    neither        this line is covered end to end
   *
   *  The -1 is the whole subtlety: MARK_A is inserted after MARK_B (the range's end is filled in
   *  first), so within a line that holds BOTH, A has pushed B one character along. Across lines it
   *  has pushed nothing, which is why the correction is conditional on A being in this line and
   *  before B. */
  function markedRange(raw) {
    const text = String(raw == null ? "" : raw);
    const iA = text.indexOf(MARK_A), iB = text.indexOf(MARK_B);
    const clean = text.split(MARK_A).join("").split(MARK_B).join("");
    let start = 0, end = clean.length;
    if (iA >= 0) start = iA;
    if (iB >= 0) end = iA >= 0 && iB > iA ? iB - 1 : iB;
    start = Math.max(0, Math.min(start, clean.length));
    end = Math.max(0, Math.min(end, clean.length));
    return [Math.min(start, end), Math.max(start, end)];
  }

  function selectionLines() {
    const sel = typeof window !== "undefined" && window.getSelection ? window.getSelection() : null;
    if (!sel || !sel.rangeCount) return [];
    const r = sel.getRangeAt(0);
    const box = editingBox(r.commonAncestorContainer);
    if (!box) return [];
    // A CARET IS ALWAYS ONE LINE. Asking a range predicate about a collapsed caret sitting at the
    // end of a paragraph gets "both of them", because it touches the start of the next -- which
    // would turn a single Enter at the end of a line into a two-line splice that empties the line
    // below it. Answered here, before any of the arithmetic can see it.
    if (r.collapsed) {
      const el = lineAtSelection();
      if (!el) return [];
      const one = selectionRange(el);
      return one ? [{ el: el, start: one[0], end: one[1] }] : [];
    }
    const lines = boxLines(box);
    if (!lines.length) return [];
    const prev = _fmtBusy;
    _fmtBusy = true;
    try {
      const a = document.createTextNode(MARK_A), b = document.createTextNode(MARK_B);
      const rb = r.cloneRange(); rb.collapse(false); rb.insertNode(b);
      const ra = r.cloneRange(); ra.collapse(true); ra.insertNode(a);
      const raws = lines.map(el => segmentsOf(el).map(seg => seg.text).join(""));
      let first = raws.findIndex(t => t.indexOf(MARK_A) >= 0);
      let last = raws.findIndex(t => t.indexOf(MARK_B) >= 0);
      if (first < 0) first = 0;                     // the selection began above the first line
      if (last < 0) last = lines.length - 1;        // ...or ran past the last
      if (last < first) { const t = first; first = last; last = t; }
      const out = [];
      for (let k = first; k <= last; k++) {
        const span = markedRange(raws[k]);
        out.push({ el: lines[k], start: span[0], end: span[1] });
      }
      a.remove(); b.remove();
      lines.forEach(el => { try { el.normalize(); } catch {} });
      // Put back what the markers disturbed, across the whole span rather than one line.
      const head = out[0], tail = out[out.length - 1];
      try {
        const pa = pointAt(head.el, head.start), pb = pointAt(tail.el, tail.end);
        if (pa && pb) {
          const back = document.createRange();
          back.setStart(pa.node, Math.max(0, Math.min(pa.offset, pa.node.length)));
          back.setEnd(pb.node, Math.max(0, Math.min(pb.offset, pb.node.length)));
          sel.removeAllRanges();
          sel.addRange(back);
        }
      } catch {}
      return out.length ? out : [];
    } catch {
      return [];
    } finally {
      _fmtBusy = prev;
    }
  }

  /** One native selection spanning several lines: from before the first to after the last. What
   *  Ctrl+A produces now that a range is allowed to cross a paragraph.
   *
   *  ELEMENT BOUNDARIES, not text offsets, and that is the whole fix. This used to ask `pointAt`
   *  for a caret position inside the first and last lines -- and `pointAt` can only land in a TEXT
   *  node, while a BR is a synthetic newline it skips. So an EMPTY endpoint line returned null and
   *  the function bailed with no range created at all: Ctrl+A painted the box and selected
   *  nothing. Empty endpoints are ordinary here -- a Word anchor paragraph, a line the estimator
   *  emptied (`renderRuns` writes `<br>`), a `.tw-note-blank` spacer between notes bullets.
   *  `setStartBefore` / `setEndAfter` need no node inside the line at all.
   *
   *  NOT `selectNodeContents(box)`, which reads as the obvious one-liner: `.tw-box-tools` is the
   *  box's LAST child (see addBoxTools), so its button labels -- "Collapse", "Reset box",
   *  "Fit to text" -- would land inside the selection and inside anything copied out of it. */
  function selectRangeAcross(lines) {
    if (!lines || !lines.length) return;
    try {
      const r = document.createRange();
      r.setStartBefore(lines[0]);
      r.setEndAfter(lines[lines.length - 1]);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(r);
    } catch {}
  }

  /** Apply one structural edit across N lines WITHOUT losing a paragraph.
   *
   *  This is the whole reason the box can be one editing host safely. The browser's own answer to
   *  "type over these three selected lines" is to merge them into one element, and a .tw-block
   *  that stops existing takes its id with it -- the backend applies overrides to a pristine
   *  template BY id, so the next Generate would put the estimator's words in the wrong paragraph
   *  of the customer's document. Here every element survives: the covered text goes, the typed
   *  text lands in the first line, and the lines that were emptied stay as empty paragraphs,
   *  which is exactly what an emptied override already means everywhere else in this editor. */
  function spliceLines(lines, ins) {
    if (!lines.length) return;
    lines.forEach((part, k) => {
      const put = k === 0 ? ins : [];
      if (part.start === part.end && !put.length) return;       // nothing to do on this line
      renderRuns(part.el, F.spliceRuns(editRuns(part.el), part.start, part.end, put));
    });
    const first = lines[0];
    const caret = first.start + runsLength(ins);
    placeSelection(first.el, caret, caret);
    // ONE dispatch. Every persistence sweep below is box-wide, so a single event carries all N
    // lines -- and N events would each re-do the same sweep.
    first.el.dispatchEvent(new Event("input", { bubbles: true }));
  }

  /** Empty one selected line through ITS OWN channel.
   *
   *  A template paragraph is cleared through the run algebra and then dispatches the page's own
   *  `input`, so the dirty flag, the override and the emptied-clause protection all run exactly as
   *  they would for a hand-delete.
   *
   *  A COMPUTED line cannot be "emptied" in the same sense: its channel reads an empty value as
   *  "no override", which restores the figure the estimate computed. That is the honest behaviour
   *  for a line the page derives -- blanking a price permanently would need the channel to carry
   *  an explicit empty, which it does not yet -- so clearing one resets it rather than voiding it.
   *  Reported by the caller so nobody has to guess which happened. */
  function clearBoxLine(el) {
    if (el.classList.contains("tw-block")) {
      if (!runsLength(editRuns(el))) return "already-empty";
      renderRuns(el, [{ text: "", tok: null }]);
      markEdited(el, false);
      return "cleared";
    }
    el.textContent = "";
    el.dispatchEvent(new Event("input", { bubbles: true }));
    return "reset-to-computed";
  }

  function paintBoxSel() {
    docSurface.querySelectorAll(".tw-boxsel").forEach(n => n.classList.remove("tw-boxsel"));
    (boxSel || []).forEach(n => n.classList.add("tw-boxsel"));
  }

  /** Drop the box selection. Called by anything that means "I am doing something else now". */
  function clearBoxSel() {
    if (!boxSel) return false;
    boxSel = null;
    paintBoxSel();
    return true;
  }

  /** The block the ribbon acts on, or null.
   *
   *  Re-checked against the live document rather than trusted. `clearDocSurface` empties the
   *  whole surface on every template reload, work-type switch and repagination, so a remembered
   *  block can be a detached orphan — and a format applied to an orphan lands nowhere while every
   *  button still looks like it worked. The floating bar could not hit this: it only existed while
   *  its block had focus, and a detached node has none. */
  function fmtTargetBlock() {
    if (fmtBlock && docSurface && !docSurface.contains(fmtBlock)) {
      fmtBlock = null;
      fmtRange = null;
      fmtRangeText = null;
    }
    return fmtBlock;
  }

  /** The exact string `fmtRange`'s offsets index into.
   *
   *  The runs, not `serializeBlock`, because the offsets are character positions into
   *  `runsLength(editRuns(el))` and nothing else — a fingerprint taken from a different
   *  serialisation would be comparing the range against a string it was never measured in. */
  function fmtRangeSource(el) {
    return editRuns(el).map(r => r.text).join("");
  }

  /** The remembered range, but ONLY if the paragraph still says what it said when it was taken.
   *
   *  A range is a pair of character offsets, and offsets are meaningless the moment the text
   *  underneath them is rewritten. That could not happen while the bar floated beside the caret:
   *  the bar existed only while its block had focus, and `refreshDocumentFills` skips the block
   *  containing `document.activeElement` precisely so a sidebar edit cannot clobber what is being
   *  typed. A ribbon that REMEMBERS its target past blur walks straight out of that protection —
   *  the remembered block usually is not the focused one, so it is re-filled like any other, and
   *  the offsets survive the rewrite pointing at whatever characters now happen to sit there.
   *
   *  The sequence costs a customer real money: select "1,500" in a WORK row, click into the
   *  sidebar, correct the square footage, press Bold. The row is re-filled with the new number at
   *  a different length, and Bold lands on a window of characters nobody highlighted — into the
   *  runs, into the override, into the generated .docx, with the estimator's eyes on the sidebar
   *  the whole time.
   *
   *  VALIDATED AT USE, NOT INVALIDATED AT THE REWRITE. Telling `refreshDocumentFills` to notify
   *  the ribbon would fix the one path that is known to do this today and quietly not fix the
   *  next one; `setBlockContent` alone already has four call sites. Checking here means every
   *  rewrite, from every path, present or future, is covered by construction — there is no call
   *  site left to forget.
   *
   *  Falling back to null is not a lesser bug, it is the model this file already documents: no
   *  usable range means the whole paragraph, the same rule `selectionFormat` applies to a
   *  collapsed caret. The estimator sees the entire row change on screen and can undo it. The
   *  alternative — keeping the block out of the re-fill to protect the range — would leave last
   *  week's square footage in a paragraph that prints, which is the worse of the two by far. */
  /** Is there a highlight on screen that is NOT the one on record?
   *
   *  `selectionRange` returns null unless BOTH endpoints are inside the block, which makes "there
   *  is no readable selection" and "the estimator is highlighting something else" the same answer
   *  — and the remembered range used to survive both. It must not survive the second.
   *
   *  THE SEQUENCE THIS CLOSES, which the text stamp alone does not: highlight "epoxy flooring" in
   *  a WORK row, then drag from inside that row down past its end — onto the canvas, or into the
   *  next paragraph. `selectionRange` cannot read that (one endpoint is outside), so nothing
   *  re-stamps the range, and the paragraph's TEXT never changed, so the stamp still matches. The
   *  ribbon lights up for the old [12, 26) while a different span is visibly highlighted, and Bold
   *  lands on fourteen characters nobody selected. Dragging UPWARD out of the row is worse: the
   *  selectionchange handler returns early on the startContainer check, so nothing is touched at
   *  all. Same failure class as the re-fill bug, reached by moving the selection instead of
   *  rewriting the words — and the whole-paragraph fallback's justification ("the estimator sees
   *  the entire row change and can undo it") does not cover a stale window mid-paragraph.
   *
   *  A COLLAPSED CARET IS NOT A CLAIM, and neither is a highlight in the sidebar. Dropping the
   *  range for either would undo the entire point of a ribbon that outlives focus — click into the
   *  Tax field, come back, press Bold — so this fires only for a real highlight that touches the
   *  document surface. */
  function selectionLeftBlock(el) {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount) return false;
    const r = sel.getRangeAt(0);
    if (!r) return false;
    if (r.collapsed) return false;
    if (el.contains(r.startContainer) && el.contains(r.endContainer)) return false;
    if (!docSurface) return false;
    return docSurface.contains(r.startContainer) || docSurface.contains(r.endContainer);
  }

  function fmtRangeFor(el) {
    if (!fmtRange) return null;
    // FAILS CLOSED. The previous shape was `fmtRangeText !== null && …`, which returned the range
    // UNVALIDATED when there was no stamp — a safety net whose actual behaviour was to wave the
    // range through, so the first future path that set fmtRange without stamping it would have
    // silently reinstated the original bug. An unstampable range is an unusable range.
    if (fmtRangeText === null
        || fmtRangeSource(el) !== fmtRangeText
        || selectionLeftBlock(el)) {
      fmtRange = null;
      fmtRangeText = null;
      return null;
    }
    return fmtRange;
  }

  /** Say ON THE PAGE which paragraph the ribbon is aimed at.
   *
   *  A bar beside the caret answered that by being there. A ribbon cannot, and its target now
   *  outlives the focus ring, so the paragraph has to say so itself or Bold is a press into the
   *  dark. `background` and nothing else — see `.tw-block.tw-fmt-target` in styles.css: this
   *  surface is a to-scale preview of a printed page registered against baked artwork, and a cue
   *  that reflowed the text by a pixel would be the worse bug. */
  function markFmtTarget(el) {
    if (fmtBlock && fmtBlock !== el) fmtBlock.classList.remove("tw-fmt-target");
    if (el) el.classList.add("tw-fmt-target");
  }

  /** Sync the ribbon's controls to the remembered block.
   *
   *  Also the ONLY place `fmtRange` is captured. Every path that refreshes the ribbon — focusin,
   *  selectionchange, each press — comes through here, so by the time a press needs a range, the
   *  last selection that was genuinely inside the block is already on record. */
  function renderFmtBar() {
    const bar = ensureFmtBar();
    const el = fmtTargetBlock();
    // INERT, NOT GONE. `disabled` rather than a dimming class alone, because a dimmed button is
    // still a live button: this repo has already shipped an `opacity: 0` element that went on
    // stealing the click underneath it. The blanket enable comes FIRST so the per-paragraph
    // refusals below — outdent at the margin, indent at the clamp, a locked contract clause —
    // are what the estimator is actually left looking at.
    bar.classList.toggle("tw-fmtbar-idle", !el);
    // `input` included: an input matches neither `button` nor `select`, so without it the size box
    // would stay live on an inert ribbon -- and this repo has already shipped a control that was
    // invisible and still took the click.
    bar.querySelectorAll("button,select,input").forEach(n => { n.disabled = !el; });
    if (!el) {
      bar.querySelectorAll("button[data-fmt]").forEach(b => {
        b.classList.remove("on");
        b.setAttribute("aria-pressed", "false");
      });
      const idleSize = bar.querySelector("input[data-fmt='size']");
      if (idleSize) idleSize.value = "";
      // THE PARAGRAPH HALF TOO, and this `return` used to be above it. The ribbon is one memoized
      // element that now lives for the whole session, so whatever is not cleared here is the LAST
      // target's leftovers sitting on a dead control: Bullet stayed lit and went on announcing
      // aria-pressed="true" — a screen reader reads "pressed" on a disabled button, which is a
      // claim about a paragraph that is no longer the target — and the whole `[data-para]` group
      // stayed `visibility: hidden` if the last target happened to be a locked contract clause,
      // so the idle ribbon was a different shape depending on what preceded it.
      bar.querySelectorAll("[data-para]").forEach(n => { n.style.visibility = ""; });
      const idleBul = bar.querySelector("button[data-para='bullet']");
      if (idleBul) {
        idleBul.classList.remove("on");
        idleBul.setAttribute("aria-pressed", "false");
      }
      return;
    }
    const f = selectionFormat(el, fmtRangeFor(el));
    // Stamped with the text it was measured in, so `fmtRangeFor` can tell later whether the
    // paragraph is still the one this range describes. See its note for what goes wrong without.
    if (f.live) { fmtRange = f.range; fmtRangeText = fmtRangeSource(el); }
    bar.querySelectorAll("button[data-fmt]").forEach(b => {
      const k = b.dataset.fmt;
      if (k !== "reset") b.classList.toggle("on", f[k] === true);
      b.setAttribute("aria-pressed", k === "reset" ? "false" : String(f[k] === true));
    });
    const sizeSel = bar.querySelector("input[data-fmt='size']");
    // NOT while it has focus. renderFmtBar runs on every focusin, every selectionchange and after
    // every press; with a <select> writing the value back was invisible, but an input being typed
    // into would have half-typed text overwritten mid-keystroke. The `fmtRange` capture above this
    // line still happens either way -- that is the reason renderFmtBar is on the hot path at all.
    if (sizeSel && document.activeElement !== sizeSel) {
      sizeSel.value = f.size_pt ? String(f.size_pt) : "";
    }
    // The paragraph controls, reflecting THIS paragraph. A locked one (a numbered TERMS AND
    // CONDITIONS clause) is offered nothing at all: un-bulleting it renumbers every clause below
    // it, in legal boilerplate, and a disabled-looking button still invites the click.
    //
    // `visibility`, not `display`, since the bar became a ribbon: a row that reflowed every time
    // the caret crossed from a WORK row to a contract clause would not be static, and Reset would
    // jump out from under the pointer. visibility:hidden keeps the space AND — unlike `opacity: 0`
    // — takes the element out of hit-testing and out of the tab order. `disabled` is set as well,
    // so the refusal survives even if that rule ever loses a cascade: a numbered contract clause
    // is worth two independent noes.
    const pst = paraNow(Number(el.dataset.id));
    const showPara = !!pst && !pst.locked;
    bar.querySelectorAll("[data-para]").forEach(n => {
      n.style.visibility = showPara ? "" : "hidden";
      if (n.tagName === "BUTTON") n.disabled = !showPara;
    });
    const bul = bar.querySelector("button[data-para='bullet']");
    if (bul) {
      // Cleared, not left alone, when the paragraph is offered nothing. The ribbon is one
      // memoized element that now lives for the whole session, so a pressed state carried over
      // from the last WORK row would sit on a hidden button waiting for the day the visibility
      // rule loses a cascade — and then read as "this contract clause is bulleted, press to
      // un-bullet it".
      bul.classList.toggle("on", showPara && pst.bullet);
      bul.setAttribute("aria-pressed", String(showPara && pst.bullet));
    }
    if (showPara) {
      const outd = bar.querySelector("button[data-para='outdent']");
      if (outd) outd.disabled = pst.indent <= 0;
      const inn = bar.querySelector("button[data-para='indent']");
      if (inn) inn.disabled = pst.indent >= INDENT_MAX_TW;
    }
  }

  /** Aim the ribbon at `el`.
   *
   *  Kept under its old name because every one of its call sites means what it always meant —
   *  "this block, refresh the buttons" — but it no longer shows or places anything: the ribbon is
   *  always shown, and a normal-flow row has nowhere to be put. Everything the old body did after
   *  `bar.style.display = "flex"` was the `getBoundingClientRect()` arithmetic, which is deleted
   *  rather than moved; see the note above `fmtBar` for why the zoom no longer needs it. */
  function showFmtBar(el) {
    // A different paragraph: the remembered range is character offsets into the OLD one and would
    // land on arbitrary words of this one.
    if (el !== fmtBlock) { fmtRange = null; fmtRangeText = null; }
    markFmtTarget(el);
    fmtBlock = el;
    renderFmtBar();
  }

  /** The ribbon stays; it just has nothing to act on.
   *
   *  Replaces `hideFmtBar`, whose behaviour is the thing Kyle asked to be rid of. Reached when
   *  focus lands on something in the document that run formatting cannot reach — a `.tw-line-edit`
   *  price line, a box tool — because a ribbon left aiming at whichever paragraph happened to be
   *  last is how a press silently rewrites a paragraph nobody was looking at. It is also the
   *  state the ribbon is built in: on page load nothing is selected. */
  function idleFmtBar() {
    markFmtTarget(null);
    fmtBlock = null;
    fmtRange = null;
    fmtRangeText = null;
    renderFmtBar();
  }

  /** True when the runs carry no formatting at all \u2014 one plain run.
   *
   *  Used to keep sending the old `{id, text}` shape in that case: most edits are plain, and a
   *  smaller payload keeps the 500-override cap and the draft blob where they were. */
  function runsArePlain(runs) {
    return runs.length <= 1 && (!runs[0] || RUN_KEYS.every(k => runs[0][k] === undefined));
  }

  function singleTokenHint(templText) {
    const m = String(templText).trim().match(/^\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}$/);
    return m ? (TOKEN_HINTS[m[1]] || null) : null;
  }

  // Inline CSS for one formatted run segment (backend-resolved: run font,
  // else the paragraph-style chain; null = inherit the page default).
  function runStyleCss(s) {
    let css = "";
    if (s.bold === true) css += "font-weight:700;";
    else if (s.bold === false) css += "font-weight:400;";
    if (s.italic === true) css += "font-style:italic;";
    if (s.underline === true) css += "text-decoration:underline;";
    if (s.size_pt) css += `font-size:${Number(s.size_pt)}pt;`;
    if (s.font) css += `font-family:'${String(s.font).replace(/['";]/g, "")}', Georgia, 'Times New Roman', serif;`;
    if (s.color && /^[0-9A-Fa-f]{6}$/.test(String(s.color))) css += `color:#${s.color};`;
    return css;
  }

  // Substituted HTML for one block. Preferred path: the backend's formatted
  // run segments (bold lead-ins, real faces/sizes/colors; each {{token}}
  // isolated as its own segment so its value inherits the exact formatting
  // the docx fill will give it). Falls back to flat fillHtml when the
  // segments don't re-join to the block text (hyperlink runs etc.).
  function blockHtml(b, tokens) {
    const runs = Array.isArray(b.runs) && b.runs.length ? b.runs : null;
    if (runs && runs.map(s => String(s.text)).join("") === b.text) {
      let html = "";
      for (const s of runs) {
        const m = String(s.text).match(/^\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}$/);
        let inner;
        if (m) {
          const known = Object.prototype.hasOwnProperty.call(tokens, m[1]);
          inner = `<span class="tw-fill" data-token="${escHtml(m[1])}">` +
                  escHtml(known ? String(tokens[m[1]]) : s.text) + `</span>`;
        } else {
          inner = fillHtml(String(s.text), tokens);   // safety: never show a raw known token
        }
        const css = runStyleCss(s);
        html += css ? `<span style="${css}">${inner}</span>` : inner;
      }
      return html;
    }
    return fillHtml(b.text, tokens);
  }

  // Fill a block element from its template record + current token values,
  // and record the pristine rendering. Only ever called on non-dirty blocks
  // (a hand-edited paragraph belongs to the estimator until they revert it).
  function setBlockContent(el, b, tokens) {
    el.innerHTML = blockHtml(b, tokens);
    const plain = fillPlain(b.text, tokens);
    pristineById.set(Number(el.dataset.id), plain);
    el.classList.toggle("tw-empty", !plain.trim());
  }

  /** Is this block one of the NUMBERED Terms and Conditions clauses?
   *
   *  Asked of the block record, not the element: `para.marker` is the number the level prints
   *  ("1." to "27."), so a paragraph that has one is a clause whose number carries the identity
   *  of the clause. A block with no `para` (a pre-v6 cached response) answers false, which is
   *  the same "no metadata means no special handling" the controls already take. */
  function isNumberedClause(id) {
    const b = blockById.get(Number(id));
    return !!(b && b.para && b.para.marker);
  }

  /** Would this override entry leave a numbered clause with no words in it?
   *
   *  Tests what would actually be RENDERED (or written to the .docx): a non-empty `runs` array
   *  wins over `text`, exactly as `restoreSavedOverrides` and `_set_paragraph_runs` treat it.
   *  `runs: [{text: ""}]` is the shape that matters and the one a length check misses: it is a
   *  non-empty array of nothing, so it survives every "did we lose the formatting" guard in this
   *  file while blanking the paragraph.
   *
   *  A `para`-only entry is NOT blank by this test — it carries no text at all, so it is not
   *  trying to empty anything, and `setParaState` refuses a locked paragraph on its own. */
  function blanksANumberedClause(o) {
    if (!o || !isNumberedClause(o.id)) return false;
    const runs = Array.isArray(o.runs) && o.runs.length ? o.runs : null;
    if (runs) return !runs.map(r => String((r && r.text) || "")).join("").trim();
    return typeof o.text === "string" && !o.text.trim();
  }

  // Kyle's contract, 2026-08-20: the clause COUNT must never move. The backend guarantees it by
  // keeping the numbering on a paragraph whose text was deleted, which prints "1." followed by
  // nothing. So emptying a clause is refused, here and at the API, and this is the sentence that
  // says why. Told the moment it happens: the paragraph controls are hidden on a clause row, so
  // without this the estimator gets no signal at all until a customer reads the contract.
  const _CLAUSE_KEPT_MSG =
    "This is a numbered Terms and Conditions clause, so it cannot be emptied: the numbers "
    + "below it would all shift, and the document would print a bare clause number with nothing "
    + "after it. The wording has been put back. Edit the words instead.";

  /** Put a numbered clause back the moment it is emptied, and say why. No-op for every other
   *  paragraph, and no-op on a clause that still has words in it.
   *
   *  Restores from the TEMPLATE record (`setBlockContent`), which is the only rendering that is
   *  guaranteed to still exist: the estimator just deleted everything they had typed. That also
   *  resets the pristine baseline, so the block comes out of this clean rather than dirty, and
   *  `collectOverrides` ships nothing for it.
   *
   *  The notice clears itself on the next keystroke in that paragraph rather than on a timer:
   *  a timer would be a race in the harness that executes this, and "it goes when you carry on
   *  typing" is the moment it has stopped being true. */
  function restoreEmptiedClause(el) {
    const id = Number(el.dataset.id);
    if (!isNumberedClause(id)) return false;
    if (serializeBlock(el).trim()) {
      el.classList.remove("tw-clause-kept");
      if (el.title === _CLAUSE_KEPT_MSG) el.title = "";
      return false;
    }
    // tw-dirty / tw-empty are not touched here: the caller (the delegated `input` handler)
    // recomputes both from the restored DOM on the very next line, and a paragraph that matches
    // the template again is not dirty. Two owners of one class is how a stale badge happens.
    setBlockContent(el, blockById.get(id), computeTokenValues());
    el.classList.add("tw-clause-kept");
    el.title = _CLAUSE_KEPT_MSG;
    return true;
  }

  function renderBlock(b, tokens) {
    const el = document.createElement("div");
    el.className = "tw-block";
    el.dataset.id = String(b.id);
    // NO contentEditable HERE ANY MORE. A paragraph with its own contenteditable is its own
    // editing host, and a selection cannot cross a host boundary -- which is what made Ctrl+A
    // stop at one line and drew a little outline round whichever line had the caret. The box
    // (or, for the terms flow, the page) carries it now, and this inherits editability from it.
    el.spellcheck = false;
    // PRICE-list rows (numId=3) are flattened to flush, bullet-less lines in the
    // generated .docx (_flatten_price_bullets) — mirror that here so the on-screen
    // editor matches (Kyle: no bullet points in the pricing).
    if (b.price_flat) el.classList.add("tw-priceline");
    // A NUMBERED CLAUSE SHOWS ITS NUMBER, not a red square. `b.list` only says the paragraph
    // carries Word numbering, which is true of a bulleted WORK row and of all 27 numbered TERMS
    // AND CONDITIONS clauses alike — so trusting it painted a Wingdings square in front of every
    // clause that prints "1." to "27." in the signed contract. `para.marker` is what the level
    // actually prints (backend: proposal_writer._para_marker), and it is empty for a bullet row.
    // Still falls back to the square when there is no marker to show: a list level whose
    // definition cannot be read is the one case where the old behaviour is the best guess left.
    else if (b.list && b.para && b.para.marker) {
      el.classList.add("tw-num");
      el.dataset.marker = String(b.para.marker);
    }
    else if (b.list) el.classList.add("tw-li");                  // real Word bullet
    else if (b.style && b.style.name === "List Paragraph") el.classList.add("tw-list");
    if (b.align) el.style.textAlign = b.align;
    if (b.style && b.style.bold && !(Array.isArray(b.runs) && b.runs.length)) {
      el.classList.add("tw-bold");                               // run-less fallback only
    }
    // GEOMETRY FROM THE RECORD, on the first paint rather than only after a toolbar press. This is
    // what made the editor disagree with the document until somebody happened to press indent:
    // `renderBlock` set classes and nothing else, so `.tw-li`'s hand-picked 14pt/9pt stood in for
    // the file's real numbers. Blocks with no `para` (a pre-v5 cached response) keep the class
    // fallback, which is what it was always for.
    if (b.para) applyParaGeom(el, b.para, b.para);
    if (flowMode) {
      // The positioned view's letterhead artwork carries the real DATE:/JOB
      // NAME: labels; only the flow fallback needs synthetic captions.
      const hint = singleTokenHint(b.text);
      if (hint) el.dataset.hint = hint;
    }
    setBlockContent(el, b, tokens);
    return el;
  }

  // Tag each block with its TOP-LEVEL region name (client-side mirror of the
  // backend's marker stack — in_block reports the innermost block, but the
  // previews mount per outermost region: e.g. the tax_breakout rows belong to
  // the single_bid group).
  function annotateRegions(blocks) {
    const stack = [];
    for (const b of blocks) {
      const t = String(b.text || "");
      const sm = t.match(/\{\{\s*#\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}/);
      if (sm) stack.push(sm[1]);
      b._region = stack.length ? stack[0] : null;
      const em = t.match(/\{\{\s*\/\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}/);
      if (em && stack.length && stack[stack.length - 1] === em[1]) stack.pop();
    }
  }

  function mountRegionPreviews(wrap, names) {
    // NO CHROME OF ANY KIND: no card, no hover tint (see `.tw-priced-region` in styles.css) and no
    // tooltip. The region flows inline as part of one continuous document, and the tooltip that
    // used to name it ("Systems — from the estimate & the fields sidebar…") was the last thing
    // announcing this group of lines as a thing of its own. Hanz, 2026-08-26: "why do we still
    // have subboxes for the main text box?" Every line in here takes a caret and is rewritten
    // whole, which is what that tooltip was explaining; the lines say it better by behaving.
    for (const name of names) {
      const mount = REGION_MOUNTS[name];
      if (mount) mount().forEach(el => { if (el) wrap.appendChild(el); });
    }
  }

  // Render one ordered slice of blocks into `container`: editable .tw-blocks for free
  // paragraphs; contiguous {{#block}} regions collapse into ONE .tw-priced-region
  // carrying the matching live previews. The region is not editable as a paragraph —
  // its ids stop meaning anything once it is expanded per priced system — but every
  // LINE the preview renders inside it is editable, whole, in place.
  function renderBlockList(container, list, tokens) {
    let regionWrap = null, regionNames = null;
    const flush = () => {
      if (regionWrap) { mountRegionPreviews(regionWrap, regionNames); regionWrap = null; regionNames = null; }
    };
    for (const b of list) {
      if (b._region) {
        if (!regionWrap) {
          regionWrap = document.createElement("div");
          regionWrap.className = "tw-priced-region";
          container.appendChild(regionWrap);
          regionNames = new Set();
        }
        regionNames.add(b._region);
      } else {
        flush();
        container.appendChild(renderBlock(b, tokens));
      }
    }
    flush();
  }

  // ── hand-edited paragraphs, stored PER TEMPLATE ───────────────────────────
  // There used to be exactly one slot: `paragraph_overrides` + one `_meta`. Every
  // save overwrote it with the currently rendered template's edits, so an
  // epoxy → polish → epoxy round trip silently threw the epoxy edits away — the
  // estimator's own typing, gone with no warning and no undo. The single slot also
  // meant `restoreSavedOverrides` had nothing to restore FROM after a switch, which
  // is why it looked like the edits "didn't stick".
  //
  // Now every template gets its own entry, keyed by work type + audience (the two
  // things that pick the file), each carrying the template version its paragraph
  // ids were captured against. The flat `paragraph_overrides` field is still
  // written for the CURRENT template because that is what /api/generate reads
  // (main.py:326) and what collectOverrides() falls back to when the editor never
  // loaded — this adds a store, it does not change that contract.
  const overrideKey = (wt, audience) => String(wt || "") + ":" + String(audience || "Direct");

  /** The per-template store with ONE template's entry replaced, as a new object.
   *
   *  Pure on purpose: the merge is the entire fix — `Object.assign({}, existing)` then
   *  setting one key is what keeps the sibling templates' edits alive, and building a
   *  fresh object here instead would silently recreate the bug. Kept as its own function
   *  so the test can exercise the real thing rather than a copy of it that can drift. */
  function mergeOverrideEntry(all, wt, audience, templateVersion, items) {
    const next = Object.assign({}, (all && typeof all === "object") ? all : null);
    next[overrideKey(wt, audience)] = { template_version: templateVersion, items: items };
    return next;
  }

  /** One key out of the CURRENT stored blob, not out of the page's load-time snapshot.
   *
   *  `state` (line 2) is a one-shot `TW.getState()`. `TW.setState` re-reads localStorage into a
   *  NEW object, merges, and writes it back — it never touches the caller's snapshot. Everything
   *  else on this page gets away with that because it mutates a NESTED object in place
   *  (`state.tab_notes`, `state.price_overrides`, `state.base_tab_id`), which the next persist
   *  picks up. A top-level key REPLACED by setState does not propagate, so the keyed override
   *  stores were frozen at page load.
   *
   *  What that cost, before this helper existed: drag a box on an epoxy job, switch the base bid
   *  to a polish tab — which re-runs initDocumentEditor in place, with no page load — and come
   *  back. The reader saw the load-time value and mounted Kyle's geometry, and the persist merged
   *  onto that same stale value, so the store was REPLACED by a single-key object and the sibling
   *  template's layout was dropped from the draft. Continue then shipped `box_overrides = {}` and
   *  the customer's document carried the template's own geometry with the estimator's resize
   *  silently discarded, which is the exact failure this feature exists to prevent.
   *
   *  The same flaw applied to the paragraph overrides, where the loss is typed text. */
  const liveKey = (name) => {
    try { return (TW.getState() || {})[name]; } catch { return undefined; }
  };

  /** The saved override entry for one template, or null.
   *
   *  Falls back to the legacy single slot when the keyed store has no entry — that
   *  is the migration path for drafts saved before this change, and it must stay:
   *  a draft in progress right now has edits only in the old shape. */
  function savedOverridesFor(wt, audience) {
    const all = liveKey("paragraph_overrides_all");
    const hit = all && typeof all === "object" ? all[overrideKey(wt, audience)] : null;
    if (hit && Array.isArray(hit.items)) return hit;
    const meta = liveKey("paragraph_overrides_meta") || {};
    if (meta.work_type === wt && meta.audience === audience) {
      return { template_version: String(meta.template_version || ""),
               items: Array.isArray(liveKey("paragraph_overrides")) ? liveKey("paragraph_overrides") : [] };
    }
    return null;
  }

  // Saved document edits (persisted in state as they're typed, so a reload /
  // device switch keeps them) — reapplied only when they were made against
  // THIS template file (version + type/audience), otherwise the ids could
  // point at the wrong paragraphs.
  function restoreSavedOverrides(wt, audience, tokens) {
    const saved = savedOverridesFor(wt, audience);
    if (!saved || String(saved.template_version || "") !== templateVersion) return;
    const tk = tokens && typeof tokens === "object" ? tokens : {};
    for (const o of saved.items) {
      if (!o) continue;
      const el = docSurface.querySelector(`.tw-block[data-id="${Number(o.id)}"]`);
      if (!el) continue;
      const runs = Array.isArray(o.runs) && o.runs.length ? o.runs : null;
      // A SAVED ENTRY THAT EMPTIES A NUMBERED CLAUSE IS NOT REPLAYED. Drafts saved while that
      // was possible still carry one, and replaying it would show a blank clause on screen while
      // the .docx (which refuses it) prints the wording — the same screen-versus-document lie as
      // the red squares, pointed the other way. Skipping it renders the template's own clause and
      // leaves the block clean; `collectOverrides` then drops the stale entry on the next persist.
      if (blanksANumberedClause(o)) continue;
      if (runs) {
        // THE RUNS, not just the words. This branch used to not exist: every reload — F5,
        // re-opening the draft, a trip to Done and back, a base-bid switch that re-runs
        // initDocumentEditor in place — replayed the entry as `el.textContent = o.text` and
        // rebuilt the paragraph as ONE plain text node. So the estimator's bold, italic,
        // underline and font size were not merely hidden: `collectOverrides` re-serialised the
        // flattened paragraph, `runsArePlain` agreed it was plain, and the 800ms persist wrote
        // `{id, text}` back over the good `{id, text, runs}`. The formatting was destroyed in
        // the saved draft, live on production.
        //
        // `tw-fmt` goes back on for the same reason it went on when the format was applied: it
        // is the only record that this paragraph is formatted, and `collectOverrides` reads it
        // to decide whether to send runs at all. Without it the very next keystroke would
        // degrade the entry again — the restore would look right and still lose the work.
        renderRuns(el, runs.map(r => {
          const one = Object.assign({}, r);
          // A tagged run's value comes from the ESTIMATE, so it is re-read here rather than
          // replayed: an estimator who corrects the square footage must not find the old
          // number frozen into a paragraph they once formatted. `storedRuns` only tags a run
          // when replacing its text cannot destroy anything (see there).
          if (r.tok && Object.prototype.hasOwnProperty.call(tk, r.tok)) one.text = String(tk[r.tok]);
          return one;
        }));
        el.classList.add("tw-dirty");
        el.classList.add("tw-fmt");
        el.classList.toggle("tw-empty", !serializeBlock(el).trim());
      } else if (typeof o.text === "string") {
        el.textContent = o.text;   // pre-wrap CSS renders the \n line breaks
        el.classList.add("tw-dirty");
        el.classList.toggle("tw-empty", !o.text.trim());
      }
      // The bullet / indent the estimator set. Restored even on an entry with NO text — a
      // formatting-only change is a whole override entry of its own (see collectOverrides), and
      // an override saved before this feature existed simply has no `para` and is unaffected.
      //
      // NOT marked tw-dirty by itself: the words were not touched, so refreshDocumentFills
      // should keep re-substituting this paragraph's {{token}} values as the sidebar changes.
      // That is safe because setBlockContent only rewrites innerHTML — it leaves the class and
      // the inline margin this puts on the element alone.
      setParaState(Number(o.id), o.para, el);
    }
  }

  // Every hand-edited paragraph, as the generate payload's paragraph_overrides.
  // Falls back to the state-persisted list when the editor never loaded (e.g.
  // template fetch failed) so earlier edits still reach the docx.
  function collectOverrides() {
    if (!templateBlocks) {
      return Array.isArray(liveKey("paragraph_overrides")) ? liveKey("paragraph_overrides") : [];
    }
    const out = [];
    docSurface.querySelectorAll(".tw-block").forEach(el => {
      const id = Number(el.dataset.id);
      const cur = serializeBlock(el);
      const runs = serializeRuns(el);
      const textChanged = cur !== pristineById.get(id);
      const fmtChanged = el.classList.contains("tw-fmt");
      const para = paraPatch(id);
      if (!textChanged && !fmtChanged && !para) return;
      // A BULLET SWITCHED OFF IS NOT AN EDIT TO THE WORDS, so a paragraph whose text is
      // untouched ships `para` and NO text. Sending the text as well would look harmless and
      // would not be: a `text` override rebuilds the paragraph as one plain run, throwing away
      // the template's own bold lead-in and font sizes on a paragraph nobody typed in.
      let entry;
      if (!textChanged && !fmtChanged) entry = { id: id };
      // Send the plain shape whenever nothing is formatted: most edits are plain, the payload
      // stays as small as it was, and the writer keeps its simpler path. Runs only appear when
      // the estimator has actually applied formatting.
      else entry = runsArePlain(runs) && !fmtChanged
        ? { id: id, text: cur }
        : { id: id, text: cur, runs: storedRuns(el, textChanged) };
      if (para) entry.para = para;
      out.push(entry);
    });
    // Never hand back less than what is already saved. Here rather than at the persist, so the
    // guard also covers the list Continue puts straight into the generate payload.
    //
    // AN ENTRY THAT EMPTIES A NUMBERED CLAUSE IS DROPPED, and it has to be dropped AFTER
    // preserveRichOverrides rather than inside the loop above: a stale `runs: [{text: ""}]` entry
    // is a non-empty array, so the rich-override rescue treats it as formatting worth keeping and
    // pushes it back in for an id the DOM never reported. Without this the draft never heals — it
    // re-sends the blank clause on every persist for the life of the project, and only the
    // writer's own refusal keeps it out of the customer's document.
    return preserveRichOverrides(out).filter(o => !blanksANumberedClause(o));
  }

  /** `next`, but never poorer than the entry already stored for this template.
   *
   *  THE FAILURE THIS EXISTS FOR. `collectOverrides` serialises the DOM, so whatever the DOM
   *  has lost is missing from the payload too — and the 800ms persist then writes that loss
   *  over the good copy. That is how run formatting was DESTROYED rather than merely hidden.
   *
   *  `restoreSavedOverrides` rebuilding the runs is the fix; this is the guard, and it is
   *  deliberately independent of it. A guard that only holds while the restore is correct is
   *  not a guard: the next edit to either function would put the data loss straight back, and
   *  the symptom is silent and permanent.
   *
   *  NARROW ON PURPOSE — it only refuses to drop a non-empty `runs` ARRAY, and only for an id
   *  whose new entry has no `runs` key at all. Every deliberate way to end up with less
   *  formatting still gets through, because they all still SEND an array: Reset sends one plain
   *  run (`tw-fmt` is never removed once set, so `collectOverrides` keeps taking the runs
   *  branch), and emptying a paragraph sends `runs: []`. So a rescue can only fire on the
   *  signature of the bug — an id that had runs coming back with the key absent.
   *
   *  Only ever merged against a store entry captured against the SAME template file: paragraph
   *  ids belong to one template, so a version mismatch means the stored entry describes
   *  different paragraphs and must be left alone. */
  function preserveRichOverrides(next) {
    let prev = null;
    try {
      const all = liveKey("paragraph_overrides_all");
      const hit = all && typeof all === "object"
        ? all[overrideKey(effectiveWorkType(), state.audience || "Direct")] : null;
      if (hit && String(hit.template_version || "") === String(templateVersion)
          && Array.isArray(hit.items)) prev = hit.items;
    } catch { return next; }
    if (!prev || !prev.length) return next;
    const rich = new Map();
    for (const o of prev) {
      if (o && Array.isArray(o.runs) && o.runs.length) rich.set(Number(o.id), o);
    }
    if (!rich.size) return next;
    const out = next.map(o => {
      if (!o || Array.isArray(o.runs)) return o;
      const keep = rich.get(Number(o.id));
      if (!keep) return o;
      rich.delete(Number(o.id));
      return Object.assign({}, o, { runs: keep.runs });
    });
    // An id that dropped out of the list entirely keeps its whole stored entry — `para` and
    // all. Nothing should reach this today (a formatted block still reports itself), which is
    // exactly why it must not be the difference between keeping the work and losing it.
    for (const o of next) if (o) rich.delete(Number(o.id));
    for (const o of rich.values()) out.push(o);
    return out;
  }

  let _overridesTimer = null;
  function schedulePersistOverrides() {
    if (_overridesTimer) clearTimeout(_overridesTimer);
    _overridesTimer = setTimeout(() => {
      try {
        const wt = effectiveWorkType();
        const audience = state.audience || "Direct";
        const items = collectOverrides();
        const boxes = collectBoxOverrides();
        // Merge, never replace. Reading state fresh here (rather than closing over an
        // earlier copy) matters because the 800ms debounce can straddle a template
        // switch that rewrote it.
        TW.setState({
          paragraph_overrides_all:
            mergeOverrideEntry(liveKey("paragraph_overrides_all"), wt, audience, templateVersion, items),
          // Kept in lockstep for the CURRENT template: /api/generate reads these two,
          // and so does collectOverrides()'s no-editor fallback.
          paragraph_overrides: items,
          paragraph_overrides_meta: {
            template_version: templateVersion,
            work_type: wt,
            audience: audience,
          },
          // The dragged box layout, through the SAME merge for the same reason: one store per
          // template, so switching the base bid and coming back keeps each one's layout.
          box_overrides_all:
            mergeOverrideEntry(liveKey("box_overrides_all"), wt, audience, templateVersion, boxes),
          box_overrides: boxes,
          box_overrides_meta: {
            template_version: templateVersion,
            work_type: wt,
            audience: audience,
          },
        });
      } catch {}
    }, 800);
  }

  // Re-substitute the highlighted values in every UNTOUCHED block after a
  // sidebar field changes (hand-edited blocks keep the estimator's text).
  let _fillsTimer = null;
  function refreshDocumentFills() {
    if (!templateBlocks) return;
    if (_fillsTimer) clearTimeout(_fillsTimer);
    _fillsTimer = setTimeout(() => {
      const tokens = computeTokenValues(Object.assign({}, state, TW.readForm(form)));
      const caretLine = lineAtSelection();
      docSurface.querySelectorAll(".tw-block").forEach(el => {
        // Don't re-fill the block the caret is currently in (a sidebar edit
        // landing within the 150ms window would otherwise clobber it).
        // BOTH TESTS. activeElement is the BOX now, an ancestor of this paragraph, so the
        // containment test below can no longer see the caret — see the note on focusInside.
        // `caretLine` is the paragraph the caret is actually in, which is what was meant.
        if (el === caretLine) return;
        if (el.contains(document.activeElement)) return;
        const b = blockById.get(Number(el.dataset.id));
        if (!b) return;
        if (el.classList.contains("tw-dirty")) {
          if (el.classList.contains("tw-fmt") && refreshFillsInPlace(el, b, tokens)) {
            schedulePersistOverrides();   // the stored runs carry the value; it just changed
          }
          return;
        }
        setBlockContent(el, b, tokens);
      });
      renderSystemPreview();
      renderNotesPreview();
      scheduleRepaginate();
      // The ribbon's buttons are read off the remembered range, and the loop above may have just
      // rewritten the paragraph that range was measured in. `fmtRangeFor` already makes the PRESS
      // safe wherever the rewrite came from; this is the cosmetic other half, so the lit state
      // stops describing a selection that no longer exists. Cheap here — 150ms debounced, once —
      // and deliberately not the thing correctness depends on.
      renderFmtBar();
    }, 150);
  }

  /** Re-substitute the estimate-sourced fills of a block the estimator only FORMATTED.
   *
   *  A formatted block is `tw-dirty`, and dirty blocks are skipped above — which is right for a
   *  block somebody typed in, and wrong for one where only the styling changed: its words are
   *  still the template's, so its `{{token}}` fills still owe the sidebar their live values. A
   *  bolded WORK row that kept last week's square footage is the same wrong number whether the
   *  page has been reloaded or not, so it is fixed on both paths.
   *
   *  Updates each fill span's own text rather than rewriting `innerHTML`, because the innerHTML
   *  IS the formatting. Refuses in two cases, for the reasons `storedRuns` gives: a paragraph
   *  whose text no longer matches its pristine rendering (the estimator typed, so the words are
   *  theirs), and a token appearing in more than one span (its fill was split by formatting
   *  half of it, and writing the value into each half would duplicate it).
   *
   *  Moves the pristine baseline with the value it just wrote — without that, the next
   *  serialise would read the fresh number as a hand edit and freeze it after all. */
  function refreshFillsInPlace(el, b, tokens) {
    const id = Number(el.dataset.id);
    if (serializeBlock(el) !== pristineById.get(id)) return false;
    const spans = el.querySelectorAll(".tw-fill[data-token]");
    const counts = new Map();
    spans.forEach(sp => counts.set(sp.dataset.token, (counts.get(sp.dataset.token) || 0) + 1));
    let touched = false;
    spans.forEach(sp => {
      const name = sp.dataset.token;
      if (counts.get(name) !== 1) return;
      if (!Object.prototype.hasOwnProperty.call(tokens, name)) return;
      const next = String(tokens[name]);
      if (sp.textContent === next) return;
      sp.textContent = next;
      touched = true;
    });
    if (touched) pristineById.set(id, fillPlain(b.text, tokens));
    return touched;
  }

  // WORK {{#system}} picks sourced from the resolved EPOXY BASE tab's sheet cells
  // (system 1 = E20/E34, system 2 = E24/E37) + its A22/A26 names — via the
  // priced_tabs snapshot, so a copy base works. Options never contribute (base
  // only, per Hanz). Returns null for a stale snapshot (no per-tab .sf) so
  // renderSystemPreview keeps the legacy hardcoded-cell fallback.
  function sheetSystems() {
    // The {{#system}} WORK block exists only in the epoxy/combo templates, and
    // the backend consumes sheet_systems only for work_type=="epoxy" — so when
    // the base's role makes the proposal polish/gyp (Phase B), don't resolve (or
    // ship) epoxy systems at all.
    const _ewt = effectiveWorkType();
    if (_ewt !== "epoxy" && _ewt !== "combo") return null;
    const all = Array.isArray(state.priced_tabs) ? state.priced_tabs : [];
    if (!all.length || !all.some(t => t.sf)) return null;
    const byId = (id) => all.find(t => t.id === id);
    let base = state.base_tab_id ? byId(state.base_tab_id) : null;
    if (!base || base.role !== "epoxy")
      base = all.find(t => t.role === "epoxy" && t.kind === "base") || all.find(t => t.role === "epoxy") || base;
    if (!base || !base.sf) return null;
    const names = Array.isArray(base.sys_names) ? base.sys_names : [];
    const out = [];
    [["epoxy_sf", "cove_lf"], ["epoxy_sf_2", "cove_lf_2"]].forEach(([sfK, lfK], i) => {
      const nm = String(names[i] || "").trim();
      if (nm && !nm.includes("Options")) out.push({ name: nm, sf: Number(base.sf[sfK]) || 0, lf: Number(base.sf[lfK]) || 0 });
    });
    if (!out.length) out.push({ name: "", sf: Number(base.sf.epoxy_sf) || 0, lf: Number(base.sf.cove_lf) || 0 });
    return out;
  }

  // The three {{#system}} WORK rows, each stored as ONE whole line under this key in
  // state.system_overrides[i]. The row is identified in the template by the token it
  // carries — name / texture / sqft — which is how the writer finds it too
  // (proposal_writer._SYSTEM_ROW_LINES). Keep the two tuples in step.
  const _SYS_ROW_LINE_FIELDS = ["name_line", "texture_line", "area_line"];
  // A line whose WORDING changed but whose numbers did not is not a pricing-review
  // risk, so it gets its own tooltip. Plain text only (no & < > ") — it is
  // interpolated into a title="" attribute.
  const _SYS_LINE_TITLE = "Reworded — the proposal prints this line instead of the "
                        + "template's. Clear the line to go back to the template wording.";
  // Mirrors proposal_writer._normalize_work_label_formatting, which is what actually
  // decides the weight in the generated .docx: a WORK row prints BOLD through its first
  // colon and normal after it. Same guards (a label must be non-empty, at most 48
  // characters and free of sentence punctuation) so a colon buried in prose is not
  // mistaken for a label. Screen and document therefore agree on the bold lead-in even
  // after the estimator has rewritten the line.
  //
  // `boldFallback` is what the row looks like when there is NO label to find — i.e. when
  // the estimator deleted the colon. The normalizer stands down in that case and the row
  // keeps its template run weight, which for the System and Area rows is bold and for the
  // Texture row is not (the writer rewrites the line into the row's first run). Without
  // this the page would show a plain line and the customer would receive a bold one.
  /** The template paragraph a synthesized {{#system}} row stands in for.
   *
   *  Matched on the token that paragraph carries, which is how the writer finds them too
   *  (proposal_writer._SYSTEM_ROW_LINES). Without this the rows were styled by hand-written inline
   *  margins with no relationship to the paragraphs they represent -- and those margins are where
   *  the phantom "sub group" came from: `margin:0 0 1pt` zeroes margin-left, so it silently
   *  overrode .tw-li's own indent and left these three rows sitting further left than every real
   *  block beside them.
   */
  function sysRowTemplate(field) {
    const token = { name_line: "system.name", texture_line: "system.texture",
                    area_line: "system.sqft" }[field];
    if (!token) return null;
    for (const b of (templateBlocks || [])) {
      if (String(b.text || "").indexOf(token) !== -1) return b;
    }
    return null;
  }

  /** Put a synthesized row exactly where its template paragraph goes, at its real size.
   *
   *  Same arithmetic as applyParaGeom -- text at `left`, marker at `left - hanging` -- expressed as
   *  an inline style because these rows are built as an HTML string. The explicit font-size is the
   *  other half of the fidelity fix: without it the row inherits `.tw-page { font-size: 9pt }`
   *  while every real block beside it carries 8pt from its runs, so System, Texture and Area
   *  rendered 12.5% larger than the rows underneath them.
   */
  function sysRowStyle(field) {
    const b = sysRowTemplate(field);
    if (!b || !b.para) return "margin:0;";
    const p = b.para, sp = p.spacing || {};
    const tw = (n) => (Math.max(0, Number(n) || 0) / TWIPS_PER_PT);
    const left = tw(p.indent), hang = tw(p.hanging), first = tw(p.first_line);
    const out = ["margin:" + tw(sp.before) + "pt 0 " + tw(sp.after) + "pt "
                 + Math.max(0, left - hang) + "pt",
                 "padding-left:" + hang + "pt"];
    if (first) out.push("text-indent:" + first + "pt");
    if (sp.line && sp.line_rule === "auto") out.push("line-height:" + (Number(sp.line) / 240));
    const size = sysRowSizePt(b.id);
    if (size) out.push("font-size:" + size + "pt");
    return out.join(";") + ";";
  }

  /** The explicit run size for a synthesized row, from the template block it stands in for.
   *
   *  Without this the row inherits `.tw-page { font-size: 9pt }` while every real block beside it
   *  carries an explicit 8pt from its runs — so System, Texture and Area rendered 12.5% larger
   *  than the rows underneath them, which is half of what Hanz saw as a "sub group". It is also
   *  what `fitTxbx`'s percentage shrink was silently singling out: a % only scales INHERITED
   *  sizes, so the box-overflow shrink hit these three rows and left the rest alone. */
  function sysRowSizePt(id) {
    const rec = blockById.get(Number(id));
    const runs = (rec && rec.runs) || [];
    for (const r of runs) if (r && r.size_pt) return Number(r.size_pt);
    return null;
  }

  function workLabelHtml(text, boldFallback) {
    const s = String(text == null ? "" : text);
    const colon = s.indexOf(":");
    if (colon >= 0) {
      const label = s.slice(0, colon).trim();
      if (label && label.length <= 48 && !/[.?!]/.test(label))
        return `<strong>${escHtml(s.slice(0, colon + 1))}</strong>${escHtml(s.slice(colon + 1))}`;
    }
    return boldFallback ? `<strong>${escHtml(s)}</strong>` : escHtml(s);
  }

  // WORK systems preview — mirrors main._build_epoxy_systems + the template's
  // {{#system}} rows. Sourced from the resolved BASE tab's sheet cells
  // (sheetSystems), with the legacy Epoxy!-cell reads as a stale-draft fallback.
  function renderSystemPreview() {
    // Don't rebuild while the estimator has the caret in one of these lines.
    if (focusInside(systemPreviewEl)) return;
    const merged = Object.assign({}, state, TW.readForm(form));
    const cells = state.cell_values || {};
    const num = (v) => Number(String(v == null ? "" : v).replace(/[$,]/g, "")) || 0;
    const fmt = (n) => Math.round(n).toLocaleString("en-US");
    let picks;
    const ss = sheetSystems();
    if (ss) {
      picks = ss.map(s => ({ name: s.name || (String(merged.system_name || "").trim() || "Epoxy System"), sf: s.sf, lf: s.lf }));
    } else {
      picks = [];
      [["Epoxy!A22", "Epoxy!E20", "Epoxy!E34"], ["Epoxy!A26", "Epoxy!E24", "Epoxy!E37"]].forEach(([na, sa, la]) => {
        const name = String(cells[na] || "").trim();
        if (name && !name.includes("Options")) picks.push({ name, sf: num(cells[sa]), lf: num(cells[la]) });
      });
      if (!picks.length) {
        picks.push({ name: String(merged.system_name || "").trim() || "Epoxy System",
                     sf: num(merged.system_1_sf), lf: num(merged.cove_1_lf) });
      }
    }
    const texture = String(merged.texture || "").trim();
    const coveH = String(merged.cove_height || "6").trim() || "6";
    const multi = picks.length > 1;
    const ovs = Array.isArray(state.system_overrides) ? state.system_overrides : [];
    // ONE LINE, ONE EDITABLE REGION. Kyle asked three times, and the first two answers
    // both handed him more islands, which is what he was objecting to: "do not make them
    // as subsections to edit but as a whole section you could edit ... I cannot delete SF
    // of epoxy flooring." The template's Area row is
    //     Area: ~{{system.sqft}} SF of epoxy flooring{{system.lf_clause}}
    // so under the old island model the "~", the words " SF of epoxy flooring" and the
    // whole cove clause were escaped dead text between two contenteditable spans: there
    // was nowhere to put a caret. They are now ordinary characters in one editable line,
    // exactly like the base-bid line (lineEl / paintLine).
    //
    // These three rows are the LAST surface on the page to move to this model; there are
    // no token islands left anywhere. The rows have to be synthesized here rather than
    // rendered as .tw-block paragraphs because they live inside the template's
    // {{#system}} region, which is expanded once per priced system at generate time — so
    // their paragraph ids stop describing anything the estimator saw, and
    // _apply_paragraph_overrides refuses any id with in_block set. The per-index
    // `system_overrides` channel reaches inside that region, so the whole line rides
    // there (proposal_writer._apply_system_row_line).
    //
    // UNTOUCHED TRACKS, TOUCHED FREEZES. A row with no stored line is rebuilt from the
    // estimate on every refresh, so a changed square footage still flows in. Once the
    // estimator types, their words win and that row stops tracking the sheet — the same
    // trade already accepted for every PRICE line, including the base bid, which is
    // money. Clearing the line reverts it to the computed text.
    //
    // The per-FIELD keys (name / texture / sqft / prefix / texture_label / area_label) are
    // still READ here so a draft saved under the old island model still shows, and still
    // prints, what the estimator typed into it. Nothing writes them any more.
    const legacy = (i, field, computed) => {
      const ov = ovs[i] || {};
      return (typeof ov[field] === "string" && ov[field].trim()) ? ov[field] : computed;
    };
    // One whole editable WORK row. `data-computed` is the line the estimate/fields
    // produce, so the input handler can revert a line that has been emptied or re-typed
    // back to the computed text. Display-only — never written to cell_values / pricing.
    const lineRow = (i, field, computed, cls, style, boldFallback) => {
      const ov = ovs[i] || {};
      const has = (typeof ov[field] === "string" && ov[field].trim());
      const shown = has ? ov[field] : computed;
      const overridden = String(shown) !== String(computed);
      // ⚠ + tooltip. A line whose DIGITS moved off the estimate is a pricing-review risk;
      // a line that was only reworded is not, so it says so instead. One visual state
      // either way, because two would be the island model again in another costume.
      // Digits are counted AFTER the row's label, so renaming "Option 1:" to "Base
      // System:" is not reported as a re-priced square footage.
      const digits = (t) => {
        const str = String(t);
        const c = str.indexOf(":");
        return (c >= 0 ? str.slice(c + 1) : str).replace(/[^0-9]/g, "");
      };
      const numMoved = overridden && digits(shown) !== digits(computed);
      const titleAttr = overridden
        ? ` title="${numMoved ? _OVERRIDE_TITLE : _SYS_LINE_TITLE}"` : "";
      return `<p class="${cls} tw-line-edit${overridden ? " tw-overridden" : ""}"${titleAttr}` +
             ` spellcheck="false"` +
             ` data-sys-index="${i}" data-sys-line="${field}"` +
             ` data-computed="${escHtml(computed)}" style="${style}">` +
             `${workLabelHtml(shown, boldFallback)}</p>`;
    };
    systemPreviewEl.innerHTML = picks.map((s, i) => {
      // NUMBERING IS PER ROW, and an edited row does NOT switch it off for the others.
      // Each row's computed prefix is a DEFAULT for that index only, and every override in this
      // preview is per-index. So rewriting row 1 as "Base System:   Quartz" leaves rows 2 and 3
      // reading "Option 2:" / "Option 3:" — the row the estimator did not touch keeps the number
      // of the row it is on. The alternative, letting one manual label suppress numbering for the
      // whole list, would silently rewrite a row nobody edited in a customer-facing document; it
      // can also read oddly ("Base System:" then "Option 2:"), but that is visible on screen
      // before Generate and is one more edit to fix.
      const prefix = legacy(i, "prefix", multi ? `Option ${i + 1}:` : "System:");
      const coveClause = `${fmt(s.lf)} LF of ${coveH}" epoxy cove base`;
      const lfClause = s.lf > 0 ? ` and ${coveClause}` : "";
      // Resolve the shown SF (a legacy per-field sqft override wins) so the cove-only
      // case is detected on the DISPLAYED value, not just the computed one.
      const sqft = legacy(i, "sqft", fmt(s.sf));
      // Cove-only system (0 SF but cove present): drop the meaningless
      // "~0 SF of epoxy flooring and " prefix and show just the cove clause.
      // Mirrors proposal_writer._drop_zero_sf_prefix.
      const areaLabel = legacy(i, "area_label", "Area:");
      const areaLine = (num(sqft) === 0 && s.lf > 0)
        ? `${areaLabel} ${coveClause}`
        : `${areaLabel} ~${sqft} SF of epoxy flooring${lfClause}`;
      // Bullet shape mirrors the template's rows: System + Area are real
      // Word bullets; Texture is an indented (bullet-less) List Paragraph.
      return lineRow(i, "name_line", `${prefix}   ${legacy(i, "name", s.name)}`,
                     "tw-li", sysRowStyle("name_line"), true)
           + lineRow(i, "texture_line",
                     `${legacy(i, "texture_label", "Texture:")}  ${legacy(i, "texture", texture)}`,
                     "tw-list", sysRowStyle("texture_line"), false)
           + lineRow(i, "area_line", areaLine, "tw-li", sysRowStyle("area_line"), true);
    }).join("");
  }

  // NOTES preview — one bullet per non-blank sidebar line ({{#notes}} block;
  // the template's notes rows are real Word bullets).
  // Highlight the sheet-pulled additional-phase amount as a .tw-fill provenance
  // island (screen-only, like the other estimate-sourced fills) — it tracks the
  // "Add for additional phase" estimate cell. Only the exact phase-note line
  // matches, so no stray number gets highlighted.
  function noteLineHtml(l) {
    const m = l.match(/^(Add\s+)(\$[\d,]+(?:\.\d{1,2})?)(\s+for each additional phase beyond the above stated schedule\.)$/i);
    if (m) return escHtml(m[1]) + `<span class="tw-fill">${escHtml(m[2])}</span>` + escHtml(m[3]);
    return escHtml(l);
  }

  function renderNotesPreview() {
    // Don't rebuild the bullets while the estimator is typing in one.
    if (focusInside(notesPreviewEl)) return;
    const ta = document.getElementById("notes-text");
    // Preserve blank lines (Word-style spacing) — a blank line renders as an
    // empty, bullet-less spacer paragraph (kept clickable via .tw-note-blank's
    // min-height) and round-trips through the textarea + generate payload + the
    // docx (see _notes_for + the notes block's blank handling). One trailing
    // newline (a common textarea artifact) is dropped so it can't creep.
    const lines = String((ta && ta.value) || "").replace(/\n$/, "").split("\n");
    // Bullets are editable in place and two-way bound to the #notes-text
    // textarea (the single source of truth; the generate payload's `notes`
    // still derives from it).
    notesPreviewEl.innerHTML = lines.map((l, i) => {
      if (l.trim() === "")
        return `<p class="tw-note-edit tw-note-blank" spellcheck="false"` +
               ` data-note-index="${i}" style="margin:0 0 1pt;"></p>`;
      return `<p class="tw-li tw-note-edit" spellcheck="false"` +
             ` data-note-index="${i}" style="margin:0 0 1pt;">${noteLineHtml(l.trim())}</p>`;
    }).join("");
    try { fitNotesBox(); } catch {}
  }

  // Shrink the NOTES text box's font just enough to fit its DESIGN height so a
  // long notes list ({{#notes}}, ~12 bullets) can't overflow onto the
  // ACCEPTANCE frame baked into the page-1 letterhead PNG below it (that frame
  // is part of the art and can't move in the DOM). The real docx fits every
  // bullet at full size on tighter Word metrics; the preview's looser metrics
  // overflow, so we step the font down until the measured box fits. Every
  // bullet stays visible + editable (clipping would hide bullets that really
  // print). Short notes get NO inline font-size — byte-identical to today and
  // the generated docx is untouched (this only styles the preview wrapper).
  // Box id differs per template (epoxy 3, polish 5), so we never hardcode it —
  // we find the box from the mounted notes element. offsetHeight is used (like
  // applyZoom) so the #doc-zoom transform doesn't skew the measurement.
  // Shrink ONE positioned text box's font until its content fits the box's
  // design height (mirrors the .docx normAutofit "shrink text on overflow").
  // Boxes that already fit get NO inline font-size (byte-identical to the design
  // + the generated docx). Applies to EVERY box — WORK, PRICE, NOTES — so long
  // content (e.g. gyp's verbose WORK scope) can't grow past its region and
  // overlap the next box / the baked page-frame art.
  function fitTxbx(box) {
    if (!box || !box.dataset.boxHPt) return;
    // Reset EVERYTHING this function can set. fitTxbx re-runs after every edit and
    // repagination, so a property left behind would keep a box clipped (or shrunk) after
    // the estimator had already trimmed the text that caused it.
    box.style.fontSize = "";                                   // reset to the design size
    box.style.transform = "";
    box.style.transformOrigin = "";
    box.style.maxHeight = "";
    box.style.overflow = "";
    box.style.zIndex = "";
    box.classList.remove("tw-notes-open");
    const target = parseFloat(box.dataset.boxHPt) * 96 / 72 + 1;   // design height in px (+1 slack)
    if (!(target > 0)) return;
    // Clearing the two GROWTH markers is part of clearing the overflow, and it has to happen on
    // every pass. They are recomputed below from a live measurement, so a box that was blocked and
    // has since been dragged taller — or trimmed — must not keep a badge and a tooltip describing
    // the page it used to be on. (This is exactly the stale badge the review caught: the old code
    // set `tw-grow-blocked` from a different function and nothing anywhere took it off again.)
    const clear = () => {
      box.classList.remove("tw-notes-overflow");
      box.classList.remove("tw-grow-blocked");
      box.classList.remove("tw-can-grow");
      box.title = "";
    };
    if (box.offsetHeight <= target) { clear(); return; }       // fits at full size — no inline size
    // 1) Font-size shrink first — keeps the full box width and matches the .docx
    //    normAutofit "shrink text on overflow". Handles the common moderate case.
    //
    //    The floor is 75%, not 60%. Below about three-quarters this stops being a
    //    preview: the GC templates carry a long "Options & Unit Prices" block and a
    //    dozen exclusion lines, and at 60% — then scaled again by the step that used
    //    to follow — the result was genuinely unreadable on screen. The old code
    //    scaled to 45% and its comment claimed that "never becomes unreadable",
    //    which was simply wrong.
    for (let k = 0.95; k >= 0.75 - 1e-9; k -= 0.05) {
      box.style.fontSize = Math.round(k * 100) + "%";
      if (box.offsetHeight <= target) { clear(); return; }
    }
    // 2) Still over at 75%, so shrinking has failed — and shrinking that fails is the
    //    worst of both worlds: it clips ANYWAY and makes what's left hard to read.
    //    Measured on a real GC proposal, three boxes were 45-80% over capacity; the old
    //    code scaled them to 0.556-0.676, i.e. 6.7-8.1px text, and a 75% floor only got
    //    that to 9px while still clipping.
    //
    //    So go back to the DESIGN size (12px, readable), clip to the box, and say so.
    //    The estimator gets a legible preview of as much as fits, an obvious marker where
    //    it stops, and a click to see the rest. Clipping also keeps the box in register
    //    with the page frame, which is baked into the artwork at full size — a scaled box
    //    drifted out of alignment with it, which is what made the old rendering look
    //    like overlapping garbage.
    //
    //    The underlying fact is a content problem, not a rendering one: this text does not
    //    fit the box Kyle designed, and Word's own normAutofit will cramp the generated
    //    .docx too. Saying so beats hiding it behind a scale transform.
    box.style.fontSize = "";
    // Measured HERE, and only here: the design font size is back and the clip below has not been
    // applied yet, so this is the one moment `offsetHeight` is the box's real content height.
    // fitOffer sets classes, never geometry — it decides whether the "Fit to text" button is
    // offered on this box and, when it is not, which of the two reasons to say out loud.
    const offer = fitOffer(box);
    box.style.maxHeight = Math.round(target) + "px";
    box.style.overflow = "hidden";
    box.classList.add("tw-notes-overflow");
    // Say what can be done about it, which is not the same sentence on every box. Without this
    // the estimator sees a box that offers to grow on one job and refuses on the next with no
    // explanation.
    const advice =
      offer === "grow"
        ? " Fit to text will make the box taller — the generated document gets that size too, and "
          + "you can drag it back or press Reset box."
        : offer === "box"
        ? " Making the box taller is not an option here: the next box on the page starts where "
          + "this one ends, so a bigger box would print over it."
        : offer === "art"
        ? " Making the box taller is not an option here: there is no box below this one to measure "
          + "against, and what sits under it is part of the letterhead picture — so a bigger box "
          + "would print over artwork that cannot move."
        : "";
    box.title = "This section is longer than the box on the template, so the rest is hidden "
              + "here — and Word will cramp it in the generated document too. Click to see "
              + "all of it; trim it to fix it properly." + advice;
  }

  /** Let a clipped box be opened to read the hidden part — and let it be closed again.
   *
   *  Delegated on the surface, because boxes are re-created on every render. Opening
   *  breaks the page layout on purpose — you are looking past the design to check content,
   *  and the marker stays so it is obvious this is not how it prints.
   *
   *  NEITHER GESTURE IS A CLICK ON THE BOX ANY MORE, and that is the change of 2026-08-26.
   *
   *  Kyle, 2026-08-19: "He is confused on how to get out of that Textbox view." That was answered
   *  with a labelled Collapse button, Escape, and a click outside — three ways out, none of them a
   *  click on the text. Opening, though, stayed a click on the box, guarded by "unless the click
   *  landed on a line". Hanz, 2026-08-26: "Editing from one text box to another is a bit clunky,
   *  it doesnt automatically transfer to the next text box when I click to edit a section." The
   *  guard was the fault: everything that is not a line — the box's padding, the gap between two
   *  paragraphs, the strip under the last one, a priced region's padding — is exactly where a Word
   *  user clicks to start typing, and there it expanded the box instead of placing a caret.
   *
   *  So the ways IN and OUT are now:
   *    * the "Show all" button in `.tw-box-tools` opens a clipped box;
   *    * the Collapse button in the same layer closes it;
   *    * Escape, from anywhere on the page;
   *    * a click on the page outside the box.
   *  and any other click inside a box only has to land a caret (`caretIntoBox`).
   *
   *  Escape and the outside click are bound on `window` rather than on `document` so this
   *  function stays reachable with the same collaborators the drag gestures already use. */
  function wireOverflowExpand() {
    if (docSurface.dataset.expandWired) return;
    docSurface.dataset.expandWired = "1";

    /** Open or clip ONE box. The clipped height is re-derived from dataset.boxHPt (which
     *  applyBoxGeom keeps current through a resize), so collapsing restores exactly the height
     *  fitTxbx clipped to rather than a height remembered from before a drag. */
    const setOpen = (box, open) => {
      if (!box) return;
      box.classList.toggle("tw-notes-open", !!open);
      box.style.maxHeight = open ? "none" : Math.round(
        parseFloat(box.dataset.boxHPt) * 96 / 72 + 1) + "px";
      box.style.overflow = open ? "visible" : "hidden";
      box.style.zIndex = open ? "30" : "";
    };
    /** Make sure a click inside `box` leaves a caret in it. Nothing else: no geometry, no
     *  expansion, no formatting, and no `preventDefault` -- where the browser is already right
     *  this must not overrule it.
     *
     *  A click that lands ON a line needs nothing from us; the browser puts the caret under the
     *  pointer, which is the whole reason this editor lets it. What needs answering is the click
     *  that lands on the box's padding, on the gap between two paragraphs, on the strip under the
     *  last one, or on a `.tw-priced-region`'s own padding -- the pixels a Word user aims at, and
     *  the ones that used to expand the box instead. `caretRangeFromPoint` resolves the point the
     *  way the browser would; when it resolves to nothing (or to something outside this box) the
     *  nearest line by vertical distance takes the caret.
     *
     *  Declared INSIDE wireOverflowExpand deliberately: three harnesses lift this function whole,
     *  and a helper declared beside it at the top level would be an unbound name in every one of
     *  them until each lift list was updated -- the ReferenceError this repo has paid for six
     *  times. Kept small enough to live here honestly. */
    const caretIntoBox = (box, e) => {
      if (e.target.closest && e.target.closest(".tw-box-tools")) return;   // a grip release is
                                                    // not a click for text: it just resized this
      const sel = typeof window !== "undefined" && window.getSelection ? window.getSelection() : null;
      if (!sel || !document.createRange) return;
      // The ordinary case, and it must be cheap: the browser placed the caret on mousedown, before
      // this ever ran.
      if (sel.rangeCount && box.contains(sel.getRangeAt(0).startContainer)) return;
      let r = null;
      try {
        if (document.caretRangeFromPoint) r = document.caretRangeFromPoint(e.clientX, e.clientY);
        else if (document.caretPositionFromPoint) {
          const p = document.caretPositionFromPoint(e.clientX, e.clientY);
          if (p && p.offsetNode) { r = document.createRange(); r.setStart(p.offsetNode, p.offset); }
        }
      } catch { r = null; }
      if (r && !box.contains(r.startContainer)) r = null;      // resolved outside: not ours to use
      if (!r) {
        const lines = box.querySelectorAll(LINE_SEL);
        if (!lines.length) return;
        let best = lines[0], bestGap = Infinity;
        for (const line of lines) {
          const rect = line.getBoundingClientRect ? line.getBoundingClientRect() : null;
          const gap = rect ? Math.abs((rect.top + rect.bottom) / 2 - e.clientY) : 0;
          if (gap < bestGap) { bestGap = gap; best = line; }
        }
        r = document.createRange();
        // OFFSET 0 IN THE ELEMENT, not a text offset: an emptied line holds a lone `<br>` and no
        // text node at all, and asking for a position inside one is what left Ctrl+A with no range
        // (see selectRangeAcross). A collapsed range on the element needs nothing inside it.
        r.setStart(best, 0);
      }
      r.collapse(true);
      sel.removeAllRanges();
      sel.addRange(r);
    };
    const openBoxes = () => docSurface.querySelectorAll(".tw-txbx.tw-notes-open");
    // Every open box, not just one: WORK and NOTES can both be expanded, and one left behind
    // keeps a deliberately broken layout on a page the estimator has stopped looking at.
    const collapseAll = () =>
      Array.prototype.forEach.call(openBoxes(), (box) => setOpen(box, false));

    docSurface.addEventListener("click", (e) => {
      const box = e.target.closest(".tw-txbx");
      if (!box) return;
      // The two explicit gestures, tested BEFORE anything else -- both buttons live in the tools
      // layer, so an exclusion for that layer would otherwise swallow its own controls.
      const peek = e.target.closest("[data-box-peek]");
      if (peek || e.target.closest("[data-box-collapse]")) {
        e.preventDefault();
        e.stopPropagation();
        setOpen(box, !!peek);
        return;
      }
      // EVERY OTHER CLICK INSIDE A BOX IS A CLICK FOR THE TEXT. Hanz, 2026-08-26: a click meant to
      // start editing a section must not do something else instead.
      //
      // This used to toggle the box open whenever the click missed a line -- the padding, the gap
      // between two paragraphs, the strip under the last one, a priced region's own padding -- and
      // those are the pixels a Word user aims at. Expanding is now the "Show all" button above,
      // Collapse/Esc/an outside click are the ways back, and this handler's only remaining job is
      // to make sure the click lands a caret.
      caretIntoBox(box, e);
    });

    window.addEventListener("keydown", (e) => {
      if (e.key !== "Escape" && e.key !== "Esc") return;
      const boxes = openBoxes();
      if (!boxes.length) return;
      // Blur BEFORE collapsing, and only when the caret really is inside one of these boxes.
      // A collapsed box is `overflow: hidden`, so leaving the caret in the clipped part makes
      // the browser scroll the box back to it — which reads as the collapse not working. The
      // edit itself is already in the DOM and already marked dirty, so blurring loses nothing.
      const a = document.activeElement;
      if (a && typeof a.blur === "function"
          && Array.prototype.some.call(boxes, (box) => box.contains(a))) {
        try { a.blur(); } catch { /* a detached node mid-render */ }
      }
      collapseAll();
      e.preventDefault();
    });

    window.addEventListener("click", (e) => {
      // Inside a box, its own handler above already decided. Outside one, the estimator has
      // moved on: put every expanded box back.
      const t = e.target;
      if (!t || !t.closest) return;
      if (t.closest(".tw-txbx")) return;
      // …except the formatting ribbon, which lives in the page's top chrome (#fmt-ribbon) and
      // never inside the box — it has to escape the box's clipping to be visible at all, and
      // since 2026-08-24 it does not move at all. It is chrome FOR the paragraph being edited,
      // so bolding a word inside an expanded box must not close the box out from under the
      // selection.
      if (t.closest(".tw-fmtbar")) return;
      collapseAll();
    });
  }
  wireOverflowExpand();

  // Fit every mounted positioned text box (WORK / PRICE / NOTES / …).
  //
  // THIS CHANGES NO GEOMETRY, and that is the whole point of the function. It runs on first paint,
  // on every repagination and on every NOTES keystroke — i.e. with no gesture behind it — so all
  // it is allowed to do is what fitTxbx does: pick a font size, clip, and mark the box. A box gets
  // TALLER only when somebody presses "Fit to text" (growBoxToFit), drags a resize grip, or the
  // saved layout is loaded. An earlier version of this function grew an overflowing box here and
  // persisted the new height into box_overrides — from where proposal_writer writes it into the
  // customer's .docx — off the browser measurement the comment above fitTxbx records as wrong in
  // the growing direction, and past artwork no DOM measurement can see. Typing is not consent to
  // resize a printed page.
  function fitNotesBox() {
    document.querySelectorAll(".tw-txbx").forEach(box => {
      releaseAutoGrownHeight(box);
      fitTxbx(box);
    });
  }

  /** Give back height WE added, once the text no longer needs it.
   *
   *  The one automatic geometry change that is allowed here, and it is allowed because it only
   *  ever goes DOWN: shrinking a box back toward the template can neither print over artwork nor
   *  over the next box, which is the whole reason growing automatically is not allowed. Without
   *  it, one long paste followed by a trim would leave the box permanently enlarged wearing a
   *  "Grown to fit" note about text that now fits anyway, and the only cure would be knowing to
   *  press Reset box.
   *
   *  Strictly limited to a height growBoxToFit produced (isAutoGrown). A height the estimator
   *  dragged is theirs and is never touched — same rule as growBoxToFit's own first guard. */
  function releaseAutoGrownHeight(box) {
    if (!box || !box.dataset || !box.dataset.boxHPt) return false;
    if (!isAutoGrown(box)) return false;
    const id = Number(box.dataset.boxId);
    const design = boxDesign.get(id);
    if (!design) return false;
    // PUT THE TEMPLATE'S GEOMETRY BACK BEFORE MEASURING, the same order growBoxToFit uses.
    // applyBoxGeom writes the override height into style.minHeight, so offsetHeight is floored by
    // the grown height — measure without dropping it first and the content can never look like it
    // fits, and the box would stay enlarged forever.
    const prev = boxOverrides.get(id);
    const prevEntry = prev ? Object.assign({}, prev) : null;
    if (!dropAutoGrownHeight(box, id)) return false;
    box.classList.remove("tw-box-grown");
    applyBoxGeom(box);
    box.style.fontSize = ""; box.style.maxHeight = ""; box.style.overflow = "";
    if (box.offsetHeight > (Number(design.h_pt) * 96 / 72) + 1) {
      // Still does not fit at the template's size, so the height was doing a job. Put it back
      // exactly as it was — releasing it here would silently undo the estimator's Fit to text.
      if (prevEntry) boxOverrides.set(id, prevEntry); else boxOverrides.delete(id);
      box.classList.add("tw-box-grown");
      applyBoxGeom(box);
      return false;
    }
    schedulePersistOverrides();     // the .docx must lose the height too, not just the screen
    return true;
  }

  // ── dragging and resizing a text box ──────────────────────────────────────
  // Hanz, 2026-08-13: "Allow me to drag and resize the text box for the proposal please."
  //
  // Until now the estimator could edit the WORDS in a box but not the box, so a long WORK scope
  // shrank its own font to fit (fitTxbx above, and _shrink_overflowing_text_boxes on the server)
  // instead of the obvious human answer: make the box taller. The backend could already resize;
  // nothing in the browser ever asked it to, and nothing anywhere could move a box.
  //
  // THE ARITHMETIC, once, because getting it wrong is silent. The page renders at TRUE point
  // sizes and #doc-zoom carries `transform: scale(k)`, so a pointer travels k CSS px on screen
  // for every 1 px of layout. Points are what the document is measured in, and 1pt = 96/72 CSS
  // px. So a client-px delta becomes document points by dividing by BOTH: (72/96)/k. Skip the k
  // and the box drifts away from the cursor at every zoom but 1 — and the zoom here is automatic
  // (0.45-1.7, fitted to the canvas), so 1 is the case nobody actually has.
  //
  // k is MEASURED rather than remembered: getBoundingClientRect is scaled by the transform and
  // offsetWidth is not, so their ratio is the live factor. applyZoom can run between a pointerdown
  // and the pointerup (a window resize, a font swap, the terms repaginating) and a remembered k
  // would then be describing the previous zoom.
  const PT_PER_CSS_PX = 72 / 96;
  // Below this a drag is a click — the box must not be marked as moved just because somebody
  // grabbed a grip and let go, or every box they touched would show a Reset button.
  const BOX_DRAG_SLOP_PT = 0.4;
  // Rounded to the template's own precision. Kyle's boxes are authored to 2dp (162.35pt), and
  // full float noise would make every payload look edited.
  const BOX_EPS_PT = 0.05;

  function zoomScale() {
    if (!docZoom) return 1;
    const laid = docZoom.offsetWidth;
    if (!laid) return 1;
    const k = docZoom.getBoundingClientRect().width / laid;
    return (k > 0.01 && k < 100) ? k : 1;
  }

  /** A pointer delta in CLIENT px as document points, through the zoom transform. */
  function ptFromClientPx(dPx, k) {
    const scale = (Number(k) > 0.01 && Number(k) < 100) ? Number(k) : 1;
    return (Number(dPx) || 0) * PT_PER_CSS_PX / scale;
  }

  /** clamp, biased to the FLOOR when the window is inverted.
   *
   *  An inverted window (hi < lo) means a box so close to the right or bottom edge that the
   *  12pt minimum and the sheet disagree. Returning `lo` keeps the result something the server's
   *  sanitiser accepts; returning `hi` would send a 5pt box that is silently refused, which the
   *  estimator reads as the drag not working. */
  function clampPt(v, lo, hi) {
    return Math.max(lo, Math.min(Number(v), hi));
  }

  /** The rect a drag lands on: pure, so the harness can drive it directly.
   *
   *  `mode` is "move" | "e" | "s" | "se"; `start` is the rect at pointerdown; `dPt` is the
   *  pointer delta already converted to points; `lim` is the page + max_box the server stated.
   *
   *  The two bounds are DIFFERENT rectangles, on purpose, and match the server exactly:
   *    * SIZE is bounded by the printable area (max_box), because a box taller than that cannot
   *      fit from any position — so accepting one guarantees text outside the margins.
   *    * POSITION is bounded by the SHEET, because Kyle designs into the margins: every box in
   *      every template already sits outside the printable area (the DATE/JOB NAME header at
   *      y=36pt against a 72pt margin, the logo at x=27pt against a 90pt one). Bounding position
   *      by the printable area would refuse to move any box in any template.
   *  Both are the same numbers proposal_writer bounds with, so a drag that stops here is never a
   *  request the server then throws away. */
  function dragBoxRect(mode, start, dPt, lim) {
    const L = lim || {};
    const pageW = Number(L.pageW) || 612, pageH = Number(L.pageH) || 792;
    const minPt = Number(L.minPt) || 12;
    const maxW = Number(L.maxW) || pageW, maxH = Number(L.maxH) || pageH;
    let x = Number(start.x), y = Number(start.y);
    let w = Number(start.w), h = Number(start.h);
    if (mode === "move") {
      x = clampPt(x + dPt.x, 0, Math.max(0, pageW - w));
      y = clampPt(y + dPt.y, 0, Math.max(0, pageH - h));
    } else {
      if (mode === "e" || mode === "se") w = clampPt(w + dPt.x, minPt, Math.min(maxW, pageW - x));
      if (mode === "s" || mode === "se") h = clampPt(h + dPt.y, minPt, Math.min(maxH, pageH - y));
    }
    return { x: x, y: y, w: w, h: h };
  }

  /** The override entry for a rect, holding ONLY what differs from the template. Null = nothing.
   *
   *  Storing differences rather than the whole rect is what makes three things fall out for free:
   *  the payload stays empty when nobody dragged (so generation is byte-identical), dragging a
   *  box back to where Kyle put it is an undo, and an axis the estimator never touched keeps
   *  following the template if Kyle ever edits it. */
  function boxOverrideEntry(design, rect) {
    const out = {};
    const d = design || {};
    const pairs = [["x_pt", rect.x, d.x_pt], ["y_pt", rect.y, d.y_pt],
                   ["w_pt", rect.w, d.w_pt], ["h_pt", rect.h, d.h_pt]];
    for (const [key, got, was] of pairs) {
      if (!Number.isFinite(Number(got))) continue;
      if (Math.abs(Number(got) - Number(was)) <= BOX_EPS_PT) continue;
      out[key] = Math.round(Number(got) * 100) / 100;
    }
    return Object.keys(out).length ? out : null;
  }

  /** What the estimator reads while dragging. Numbers, because "bigger" is not a size. */
  function boxReadout(mode, rect) {
    const n = (v) => String(Math.round(Number(v)));
    return mode === "move"
      ? "x " + n(rect.x) + " · y " + n(rect.y) + " pt"
      : n(rect.w) + " × " + n(rect.h) + " pt";
  }

  /** The box's live rect: the template's geometry with any override laid over it. */
  function effectiveBoxRect(id) {
    const d = boxDesign.get(id) || { x_pt: 0, y_pt: 0, w_pt: 0, h_pt: 0 };
    const o = boxOverrides.get(id) || {};
    const pick = (a, b) => (Number.isFinite(Number(a)) ? Number(a) : Number(b) || 0);
    return { x: pick(o.x_pt, d.x_pt), y: pick(o.y_pt, d.y_pt),
             w: pick(o.w_pt, d.w_pt), h: pick(o.h_pt, d.h_pt) };
  }

  /** Paint one box's live rect onto its element. */
  function applyBoxGeom(el) {
    const id = Number(el.dataset.boxId);
    const r = effectiveBoxRect(id);
    el.style.left = r.x + "pt";
    el.style.top = r.y + "pt";
    el.style.width = r.w + "pt";
    el.style.minHeight = r.h + "pt";
    // fitTxbx and the overflow-expand toggle both read the height from here, and neither knows
    // anything about dragging. Writing it means a box the estimator enlarged stops being reported
    // as overflowing, and stops having its font shrunk on screen — which is the whole point.
    el.dataset.boxHPt = String(r.h);
    el.classList.toggle("tw-box-moved", boxOverrides.has(id));
    return r;
  }

  /** The grips + the size readout + the "Grown to fit" note + Reset + Collapse. Absolutely
   *  positioned, so they add no
   *  height: fitTxbx measures offsetHeight to decide what overflows, and a grip in the flow
   *  would make every box look taller than its text.
   *
   *  Collapse is the way OUT of an expanded box. Kyle, 2026-08-19: "He is confused on how to
   *  get out of that Textbox view." Expanding was a click on the box, but the click handler
   *  ignores clicks that land on editable content (see wireOverflowExpand) — and an expanded
   *  box is almost entirely editable content, so there was often nothing left to click. A
   *  labelled button that is NOT inside the editable text is the only way out that cannot be
   *  swallowed by the paragraph editor. It is a word, not a grip, so it does not read as a
   *  drag handle; CSS shows it only while the box is open. */
  function addBoxTools(el) {
    const tools = document.createElement("div");
    tools.className = "tw-box-tools";
    // NOT EDITABLE. The box is a contenteditable host now, so anything appended to it would
    // otherwise be typed into, dragged through and selected by Ctrl+A along with the text -- and
    // the grips and buttons in here are chrome, not content.
    tools.contentEditable = "false";
    tools.innerHTML =
      '<span class="tw-grip tw-grip-move" data-grip="move" title="Drag to move this box"></span>' +
      '<span class="tw-box-size"></span>' +
      // Says out loud that the box on screen is NOT the size the template gives it, because
      // growBoxToFit made it fit. Silent geometry in a document the customer receives is the
      // thing to avoid; the dashed .tw-box-moved outline and "Reset box" already come with it.
      '<span class="tw-box-grown-note" title="This box was made taller so all of its text ' +
        'fits. The generated document uses this size too. Reset box puts it back.">' +
        'Grown to fit</span>' +
      // Offered ONLY on a box fitOffer marked .tw-can-grow, i.e. one whose text fits in room
      // bounded by a real box below it. Kyle, 2026-08-20: "instead of it being a textbox why not
      // make it editable like a word document?" — a Word user expects the text to fit. This is
      // the closest safe answer: a press, a visible result, and Reset box to undo. It is NOT
      // automatic, because the height it writes goes into the .docx the customer receives and
      // the browser's own measurement overstates overflow (see the note above fitTxbx).
      '<button type="button" class="tw-box-fit" data-box-fit="1" ' +
        'title="Make this box tall enough for all of its text. The generated document gets the ' +
        'same size; drag the bottom edge or press Reset box to undo.">Fit to text</button>' +
      // THE WAY IN, and it is a labelled control for the same reason Collapse is one.
      // Hanz, 2026-08-26: "Editing from one text box to another is a bit clunky, it doesnt
      // automatically transfer to the next text box when I click to edit a section." Opening a
      // clipped box used to be a click on the box itself, and the exclusion that kept such a
      // click for the paragraph editor had been narrowed to "did it land on a LINE" -- so a click
      // on the box's padding, on the gap between two paragraphs, or on the strip under the last
      // one expanded the box instead of putting a caret in it. That is exactly where a Word user
      // clicks to start typing. A button in the tools layer cannot be confused with the text.
      '<button type="button" class="tw-box-peek" data-box-peek="1" ' +
        'title="Show the text this box is too small to fit. Nothing is changed: the box goes ' +
        'back with Collapse, Esc, or a click outside it.">Show all</button>' +
      '<button type="button" class="tw-box-collapse" data-box-collapse="1" ' +
        'title="Put this box back to the size the template gives it. Esc does the same, and so ' +
        'does clicking the page outside the box.">Collapse</button>' +
      '<button type="button" class="tw-box-reset" data-box-reset="1" ' +
        'title="Put this box back where the template has it">Reset box</button>' +
      '<span class="tw-grip tw-grip-e" data-grip="e" title="Drag to change the width"></span>' +
      '<span class="tw-grip tw-grip-s" data-grip="s" title="Drag to change the height"></span>' +
      '<span class="tw-grip tw-grip-se" data-grip="se" title="Drag to resize this box"></span>';
    el.appendChild(tools);
    return tools;
  }

  function showBoxReadout(el, mode, rect) {
    const out = el.querySelector(".tw-box-size");
    if (out) out.textContent = rect ? boxReadout(mode, rect) : "";
  }

  /** Record a dragged rect, dropping the entry entirely when it matches the template again. */
  function setBoxOverride(id, rect) {
    const entry = boxOverrideEntry(boxDesign.get(id), rect);
    if (entry) boxOverrides.set(id, entry);
    else boxOverrides.delete(id);
    return entry;
  }

  // ── a box that GROWS instead of clipping ─────────────────────────────────────
  // Kyle, 2026-08-19: "instead of it being a textbox why not make it editable like a word
  // document?" A Word user who types more than fits expects the box to get bigger. Until now
  // over-long content shrank its own font (fitTxbx's ladder) and, when that failed, was CLIPPED
  // behind a "Too long for this box" badge — a preview that hides text the .docx also cramps.
  // Growing is the honest answer, and the plumbing already existed: a dragged height reaches the
  // .docx through box_overrides → proposal_writer._apply_box_overrides, which runs BEFORE
  // _shrink_overflowing_text_boxes and therefore stops the server shrinking a box that is now
  // big enough.
  //
  // WHAT STOPS IT, and why the warning path is not a cop-out. The page renders at true point
  // sizes and every box is registered against baked letterhead PNGs — the red WORK/PRICE/NOTES
  // frames are ARTWORK, not DOM, so nothing can move them. Growth is therefore bounded by the
  // geometry we can actually see: the next box below (with x overlap) and the bottom margin.
  // Measured against the shipped templates (template_geometry output, 2026-08-19) that room is
  // small and often zero — Direct epoxy's WORK box is 171pt tall and PRICE starts 168.3pt below
  // its top, so WORK cannot grow by even a point, while the last box on each page has 25-63pt
  // spare. Where there is no room the box keeps today's clip-and-warn and the badge says growth
  // was blocked, because a preview that quietly overlapped the next frame would be lying about
  // what prints.
  //
  // Boxes that FIT are never touched: growBoxToFit returns before it can write anything, so
  // their generated geometry stays byte-identical.

  // WHO SET THIS HEIGHT lives on the ELEMENT, not in a module-level Set, and that is deliberate
  // twice over. It is the honest lifetime — renderPositioned recreates every box element, so both
  // flags below reset exactly when the layout is rebuilt, which is when they should. And a Set
  // here would be a new free variable inside `wireBoxDrag` / `loadBoxOverrides`, which
  // tests/js/box-drag-harness.js lifts out of this file and runs on their own; a name it does not
  // bind is a ReferenceError in a passing-looking test file.
  //
  //   .tw-box-grown     — growBoxToFit set this height, so it may recompute it. A height the
  //                       ESTIMATOR dragged is never marked, and is therefore never overwritten:
  //                       they said how tall the box should be.
  //   data-grow-off     — "Reset box" was pressed. Reset means "put it back where the template
  //                       has it", and an auto-grow firing again on the next repaint would make
  //                       the button look broken.
  const isAutoGrown = (box) => !!(box && box.classList.contains("tw-box-grown"));

  /** Drop the height WE added, keeping any x/y/w the estimator dragged. */
  function dropAutoGrownHeight(box, id) {
    if (box) box.classList.remove("tw-box-grown");
    const o = boxOverrides.get(id);
    if (!o || o.h_pt === undefined) return false;
    delete o.h_pt;
    if (!Object.keys(o).length) boxOverrides.delete(id);
    return true;
  }

  /** The tallest `rect` may become before it hits something. Pure, so a test can drive it with
   *  the templates' real geometry rather than with numbers invented to make it pass.
   *
   *  `others` are the OTHER boxes' live rects. A box counts as "below" when its TOP is below this
   *  box's TOP — not when it is below this box's BOTTOM, which is the trap: Kyle's shapes already
   *  overlap (Direct epoxy's WORK ends at 323.65pt and PRICE starts at 320.95pt), so a
   *  bottom-based test would classify the one box we must not grow into as "not below me" and
   *  cheerfully grow straight through it. */
  /** The Y of the nearest box that sits UNDER `rect` and overlaps it horizontally, or null when
   *  nothing does. Null is the important answer: see growRoomPt. */
  function boxCeilingPt(rect, others) {
    let bottom = null;
    for (const o of (others || [])) {
      if (!o) continue;
      if (o.x + o.w <= rect.x || o.x >= rect.x + rect.w) continue;   // beside it, not under it
      if (!(o.y > rect.y)) continue;                                 // level/above: not a ceiling
      if (bottom === null || o.y < bottom) bottom = o.y;
    }
    return bottom;
  }

  /** How much taller this box may become, in points. Zero means "not at all".
   *
   *  BOUNDED BY A REAL BOX, AND BY NOTHING ELSE. There is no fallback to the page margin, and
   *  that is the whole point of this function rather than an oversight to tidy up later.
   *
   *  The page frame — the red rails, the rotated WORK/PRICE captions, the ACCEPTANCE and
   *  signature block, the logo — is a full-page PNG baked into the template. It is invisible to
   *  the DOM: there is no element to measure and no rect to avoid. So the only thing this code
   *  can see under a box is ANOTHER BOX, and "the page's bottom margin is still far away" says
   *  nothing whatsoever about whether the space is empty.
   *
   *  Bounding by printBottom instead (review 2026-08-20) let Direct/epoxy NOTES — design 162pt
   *  at y=494.6, content measuring ~220pt — grow its bottom edge from 656.6pt to 714.35pt, i.e.
   *  57.75pt straight down over the baked signature frame. And because a grown box DISARMS the
   *  server-side shrink (backend/proposal_writer.py, _shrink_overflowing_text_boxes) nothing
   *  downstream catches it: the customer receives a proposal with the terms printed over the
   *  artwork. Four of the six Direct/epoxy boxes are bounded by artwork rather than by a box,
   *  so this was the common case, not the corner.
   *
   *  The honest consequence: on this template only WORK can grow, because PRICE genuinely sits
   *  under it. Every other box reports zero room and keeps the clip-and-warn. Growing into
   *  artwork needs the artwork MEASURED (measureTermsBand is the precedent for reading ink off
   *  the baked page) and that is a separate piece of work, not a constant to relax here. */
  function growRoomPt(rect, others, lim) {
    const L = lim || {};
    const bottom = boxCeilingPt(rect, others);
    if (bottom === null) return 0;                  // nothing below we can prove is empty
    let room = bottom - rect.y;
    const maxH = Number(L.maxH);
    if (Number.isFinite(maxH) && maxH > 0) room = Math.min(room, maxH);
    // Never past the printable area even when a box below says there is space — a box that
    // overlaps the bottom margin is one the server's own clamp would refuse.
    const floorY = Number(L.printBottom);
    if (Number.isFinite(floorY)) room = Math.min(room, Math.max(0, floorY - rect.y));
    return Math.max(0, room);
  }

  /** Whether this box can be offered a "Fit to text", and when it cannot, WHY.
   *
   *  Classes only — this function never writes geometry, so it is safe to call from inside
   *  fitTxbx on every render and every keystroke. Growing is a deliberate press of the button
   *  (growBoxToFit); nothing here changes what the generated document looks like.
   *
   *  Returns one of:
   *    "grow" — there is room for all of the text; the button is offered.
   *    "box"  — the next box on the page starts too soon; a taller box would print over it.
   *    "art"  — nothing below to measure against, so what sits there is letterhead picture.
   *
   *  Called with the design font size restored and before the clip is applied, which is the one
   *  moment offsetHeight is the real content height. Do not move the call. */
  function fitOffer(box) {
    box.classList.remove("tw-can-grow", "tw-grow-blocked");
    if (!box || !box.dataset || !box.dataset.boxHPt) return "";
    if (box.dataset.growOff === "1") return "";
    const id = Number(box.dataset.boxId);
    if (!boxDesign.has(id)) return "";
    // A height the estimator set by hand is theirs; offering to overwrite it is not help.
    const ov = boxOverrides.get(id);
    if (ov && typeof ov.h_pt === "number" && !isAutoGrown(box)) return "";
    const rect = effectiveBoxRect(id);
    const others = otherBoxRects(id);
    const needPt = Math.ceil(box.offsetHeight * PT_PER_CSS_PX * 100) / 100;
    const room = growRoomPt(rect, others, boxLimits);
    if (needPt <= room + BOX_EPS_PT) {
      box.classList.add("tw-can-grow");
      return "grow";
    }
    box.classList.add("tw-grow-blocked");
    // Which sentence to say. A real box below means the geometry is genuinely taken; no box
    // below means we simply cannot see what is there, and the two are not the same excuse.
    return boxCeilingPt(rect, others) === null ? "art" : "box";
  }

  /** Every OTHER mounted box's live rect (boxDesign holds exactly the mounted boxes). */
  function otherBoxRects(id) {
    const out = [];
    boxDesign.forEach((_d, other) => { if (other !== id) out.push(effectiveBoxRect(other)); });
    return out;
  }

  /** Grow ONE box so its content fits at the DESIGN font size, if there is room for all of it.
   *
   *  Partial growth is deliberately not a thing: geometry changes only when it actually solves
   *  the problem, so a box is either at the template's size, or at a size its text fits in, or at
   *  the template's size with an honest warning — never at some third size that still clips.
   *  Returns true when the height changed. */
  function growBoxToFit(box) {
    if (!box || !box.dataset || !box.dataset.boxHPt) return false;
    if (box.dataset.growOff === "1") return false;
    const id = Number(box.dataset.boxId);
    if (!boxDesign.has(id)) return false;
    const ov = boxOverrides.get(id);
    const prevH = (ov && typeof ov.h_pt === "number") ? ov.h_pt : null;
    const wasAuto = isAutoGrown(box);
    if (prevH !== null && !wasAuto) return false;                    // their own drag wins
    if (wasAuto && dropAutoGrownHeight(box, id)) applyBoxGeom(box);
    box.classList.remove("tw-box-grown");
    // Measure the CONTENT, not the last fit: fitTxbx may have left a font-size and a clip on it.
    box.style.fontSize = "";
    box.style.maxHeight = "";
    box.style.overflow = "";
    const rect = effectiveBoxRect(id);
    const target = rect.h / PT_PER_CSS_PX + 1;            // the same +1px slack fitTxbx allows
    if (!(target > 0)) return false;
    if (box.offsetHeight <= target) { box.classList.remove("tw-grow-blocked"); return false; }
    const needPt = Math.ceil(box.offsetHeight * PT_PER_CSS_PX * 100) / 100;
    const room = growRoomPt(rect, otherBoxRects(id), boxLimits);
    if (needPt > room + BOX_EPS_PT) {
      box.classList.add("tw-grow-blocked");               // fitTxbx clips; the badge says why
      return false;
    }
    // Through the drag's own clamp, so an auto-grown rect is never one the server would refuse.
    const grown = dragBoxRect("s", rect, { x: 0, y: needPt - rect.h }, boxLimits);
    setBoxOverride(id, grown);
    applyBoxGeom(box);
    if (box.offsetHeight > grown.h / PT_PER_CSS_PX + 1.5) {
      // The clamp gave back less than the content needs. Don't leave the box at a third size
      // that neither fits nor matches the template — put it back and warn.
      if (dropAutoGrownHeight(box, id)) applyBoxGeom(box);
      box.classList.add("tw-grow-blocked");
      return false;
    }
    box.classList.remove("tw-grow-blocked");
    box.classList.add("tw-box-grown");
    if (prevH === null || Math.abs(prevH - grown.h) > BOX_EPS_PT) schedulePersistOverrides();
    return true;
  }

  /** Delegated pointer gesture on the grips.
   *
   *  pointerdown is delegated on the surface because boxes are re-created on every render (same
   *  reason as wireOverflowExpand). move/up are on the WINDOW, not the surface: a fast drag
   *  leaves the box, and if setPointerCapture is unavailable those events would never reach a
   *  surface-scoped listener — the box would stick mid-drag. */
  function wireBoxDrag() {
    if (docSurface.dataset.boxDragWired) return;
    docSurface.dataset.boxDragWired = "1";
    let drag = null;

    docSurface.addEventListener("pointerdown", (e) => {
      const grip = e.target.closest("[data-grip]");
      if (!grip) return;
      const box = grip.closest(".tw-txbx");
      if (!box) return;
      const id = Number(box.dataset.boxId);
      if (!boxDesign.has(id)) return;
      // Not a text edit: no caret, no selection, and no overflow-peek toggle.
      e.preventDefault();
      e.stopPropagation();
      drag = { id: id, box: box, grip: grip, mode: grip.dataset.grip,
               start: effectiveBoxRect(id), x0: e.clientX, y0: e.clientY, moved: false };
      box.classList.add("tw-box-dragging");
      box.style.zIndex = "40";      // over the neighbouring boxes while being dragged
      try { grip.setPointerCapture(e.pointerId); } catch { /* mouse fallback below */ }
      showBoxReadout(box, drag.mode, drag.start);
    });

    window.addEventListener("pointermove", (e) => {
      if (!drag) return;
      // Re-measured every move: applyZoom can fire mid-drag.
      const k = zoomScale();
      const d = { x: ptFromClientPx(e.clientX - drag.x0, k),
                  y: ptFromClientPx(e.clientY - drag.y0, k) };
      if (Math.abs(d.x) > BOX_DRAG_SLOP_PT || Math.abs(d.y) > BOX_DRAG_SLOP_PT) drag.moved = true;
      const rect = dragBoxRect(drag.mode, drag.start, d, boxLimits);
      setBoxOverride(drag.id, rect);
      applyBoxGeom(drag.box);
      showBoxReadout(drag.box, drag.mode, rect);
    });

    const endDrag = () => {
      if (!drag) return;
      const { box, moved, mode } = drag;
      drag = null;
      box.classList.remove("tw-box-dragging");
      box.style.zIndex = "";
      showBoxReadout(box, "", null);
      // A height the estimator set by hand stops being ours to recompute — growBoxToFit will
      // leave it alone from here, even if the text still overflows (it clips and warns instead).
      if (moved && (mode === "s" || mode === "se")) box.classList.remove("tw-box-grown");
      // Re-measure the overflow badge against the new height: a box just made big enough must
      // stop saying its text is cut off, and one made smaller must start.
      fitTxbx(box);
      if (moved) schedulePersistOverrides();
    };
    window.addEventListener("pointerup", endDrag);
    window.addEventListener("pointercancel", endDrag);

    // Reset is a click, not a gesture. An estimator who has nudged three boxes needs a way back
    // that is not "reload the page and lose the text you typed".
    docSurface.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-box-reset]");
      if (!btn) return;
      e.preventDefault();
      e.stopPropagation();
      const box = btn.closest(".tw-txbx");
      if (!box) return;
      boxOverrides.delete(Number(box.dataset.boxId));
      // "Put this box back where the template has it" has to STAY put. Without this the next
      // repaint's growBoxToFit would re-grow an overflowing box and the button would look
      // broken. The estimator gets the template's geometry plus the honest overflow warning.
      // On the element, so it lasts exactly as long as this layout does.
      box.classList.remove("tw-box-grown");
      box.dataset.growOff = "1";
      applyBoxGeom(box);
      fitTxbx(box);
      schedulePersistOverrides();
    });

    // "Fit to text" — the human gesture that is allowed to change geometry. growBoxToFit does
    // the arithmetic, persists the height and sets .tw-box-grown, so this is only the trigger.
    //
    // It clears growOff, deliberately: that flag exists so a repaint cannot silently undo a
    // "Reset box", and pressing Fit to text is the estimator changing their mind out loud.
    docSurface.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-box-fit]");
      if (!btn) return;
      e.preventDefault();
      e.stopPropagation();      // never let this reach wireOverflowExpand and open the box too
      const box = btn.closest(".tw-txbx");
      if (!box) return;
      delete box.dataset.growOff;
      growBoxToFit(box);
      // Re-fit either way: on success to drop the clip now the text fits, and on failure to put
      // the warning and its advice back rather than leaving a box that looks like it worked.
      fitTxbx(box);
    });
  }
  wireBoxDrag();

  // ── box layout, saved PER TEMPLATE ────────────────────────────────────────
  // Same shape and the same shared merge as the paragraph overrides: a keyed store so an
  // epoxy → polish → epoxy round trip keeps each template's layout, plus the flat field
  // /api/generate actually reads. The version guard is the load-bearing part — a box id is a
  // position in the backend's walk over one specific template file, so replaying an id captured
  // against another version would resize a box the estimator never touched.
  function savedBoxOverridesFor(wt, audience) {
    const isPlain = (v) => !!v && typeof v === "object" && !Array.isArray(v);
    const all = liveKey("box_overrides_all");
    const hit = isPlain(all) ? all[overrideKey(wt, audience)] : null;
    if (hit && isPlain(hit.items)) return hit;
    const meta = liveKey("box_overrides_meta") || {};
    if (meta.work_type === wt && meta.audience === audience) {
      return { template_version: String(meta.template_version || ""),
               items: isPlain(liveKey("box_overrides")) ? liveKey("box_overrides") : {} };
    }
    return null;
  }

  /** Load this template's saved box layout into `boxOverrides`. Called BEFORE the render, so a
   *  restored box is created at its saved size instead of jumping there a frame later. */
  function loadBoxOverrides(wt, audience) {
    boxOverrides = new Map();
    // A RESTORED height is treated as the estimator's, even if growBoxToFit produced it in an
    // earlier session: the store keeps rects, not who set them, and the safe reading of an
    // unknown height is "somebody chose this size". Nothing to clear here — the "we grew this"
    // mark lives on the box element (see isAutoGrown), and renderPositioned builds new elements.
    const saved = savedBoxOverridesFor(wt, audience);
    if (!saved || String(saved.template_version || "") !== templateVersion) return;
    for (const key of Object.keys(saved.items || {})) {
      const id = Number(key);
      const spec = saved.items[key];
      if (!Number.isFinite(id) || !spec || typeof spec !== "object") continue;
      const one = {};
      for (const f of ["x_pt", "y_pt", "w_pt", "h_pt"]) {
        // typeof, not Number(): `Number(null)` and `Number("")` are both 0, and 0 is a LEGAL
        // position, so coercing here would read a corrupt entry as "this box belongs against the
        // top-left edge of the page" and move it there. Every value we write is a number.
        if (typeof spec[f] === "number" && Number.isFinite(spec[f])) one[f] = spec[f];
      }
      if (Object.keys(one).length) boxOverrides.set(id, one);
    }
  }

  /** The dragged layout as the generate payload's `box_overrides`.
   *  Falls back to the state-persisted dict when the editor never loaded, exactly as
   *  collectOverrides does for paragraphs, so an earlier drag still reaches the .docx. */
  function collectBoxOverrides() {
    if (!templateBlocks) {
      const flat = liveKey("box_overrides");
      return (flat && typeof flat === "object" && !Array.isArray(flat)) ? flat : {};
    }
    const out = {};
    boxOverrides.forEach((spec, id) => { out[String(id)] = spec; });
    return out;
  }

  // Letterhead artwork, fetched WITH the auth header (a plain <img src>
  // can't carry the bearer token through the /api/* gate) and cached as a
  // data: URI per media name.
  //
  // A data: URI (not a blob: object URL) is deliberate: the production/staging
  // nginx sends `Content-Security-Policy: … img-src 'self' data:` — blob: is
  // NOT allowed, so an <img src="blob:…"> is silently blocked and the whole
  // letterhead disappears (only visible behind the CSP, i.e. never in local
  // dev). data: is on the allowlist, so it renders without any server change.
  //
  // A failed fetch is NOT cached: we delete the cache entry before resolving
  // null so a transient failure (e.g. the page-load auth race) retries on the
  // next render instead of blanking the letterhead for the whole session.
  function artUrl(name) {
    const wt = effectiveWorkType();
    // Key by work type: a base-switch template reload can load a DIFFERENT
    // work type whose PNGs share a name (image1.png) with the previous one — a
    // name-only cache would then serve the stale (wrong) letterhead.
    const key = wt + ":" + name;
    if (!artUrlCache.has(key)) {
      const audience = state.audience || "Direct";
      const url = `/api/proposal-template/media?work_type=${encodeURIComponent(wt)}` +
                  `&audience=${encodeURIComponent(audience)}&name=${encodeURIComponent(name)}`;
      const p = fetch(url, { headers: TW.authHeaders() })
        .then(r => (r.ok ? r.blob() : null))
        .then(b => (b ? blobToDataUrl(b) : null))
        .catch(() => null)
        .then(u => {
          if (!u) artUrlCache.delete(key);   // don't cache a failure — allow retry
          return u;
        });
      artUrlCache.set(key, p);
    }
    return artUrlCache.get(key);
  }

  // Blob -> data: URI. Used for letterhead artwork so the <img> passes the
  // CSP img-src allowlist (data:, not blob:). ~33% base64 overhead on ~130KB
  // of PNGs fetched once per template per session — negligible.
  function blobToDataUrl(blob) {
    return new Promise((resolve) => {
      const fr = new FileReader();
      fr.onload = () => resolve(fr.result);
      fr.onerror = () => resolve(null);
      fr.readAsDataURL(blob);
    });
  }

  // Word-zoom: the page renders at TRUE point sizes (8-9pt Zetta Serif), and
  // the whole surface scales to fill the canvas — like the ~150% zoom the
  // estimators read the real file at. The outer div takes the scaled bounds
  // so the canvas scrolls normally.
  // Size the outer to #doc-zoom's SCALED bounds so the canvas reserves the right
  // scroll height. transform:scale doesn't change the layout box, so the outer
  // must be told the scaled size explicitly — and kept in sync (see the observer
  // below), or a late height change leaves it too short and the bottom of the
  // page (NOTES / ACCEPTANCE) can't be scrolled to.
  function syncZoomOuter() {
    if (!docZoom || !docZoomOuter) return;
    const r = docZoom.getBoundingClientRect();
    docZoomOuter.style.width = r.width + "px";
    docZoomOuter.style.height = r.height + "px";
  }
  let _zoomRO = null;
  function applyZoom() {
    if (!docZoom || !docZoomOuter) return;
    const canvas = document.querySelector(".word-canvas");
    if (!canvas) return;
    const cs = getComputedStyle(canvas);
    const avail = canvas.clientWidth - parseFloat(cs.paddingLeft || 0) - parseFloat(cs.paddingRight || 0) - 24;
    const pagePx = pageWpt * (96 / 72);                    // CSS pt -> px
    const k = Math.min(1.7, Math.max(0.45, avail / pagePx));
    // Pin the zoom div to the page width (a block div would stretch to its
    // parent, making the scaled bounds feed back on themselves), then size
    // the outer to the transformed bounds so the canvas scrolls correctly.
    docZoom.style.width = pageWpt + "pt";
    docZoom.style.transform = `scale(${k})`;
    syncZoomOuter();
    // Re-sync the reserved height whenever the document's own height changes
    // AFTER this pass — font swap (Zetta Serif), price/notes island re-render,
    // repagination — none of which necessarily re-call applyZoom. Without this
    // the one-shot measure above goes stale and clips the bottom. Setting the
    // outer's height never resizes #doc-zoom, so there's no feedback loop.
    if (!_zoomRO && window.ResizeObserver) {
      _zoomRO = new ResizeObserver(() => syncZoomOuter());
      _zoomRO.observe(docZoom);
    }
  }
  window.addEventListener("resize", applyZoom);

  // The Word-faithful view: the template's own full-page letterhead artwork
  // behind the floating text boxes at their real anchor positions — page 1 —
  // then the Terms & Conditions body flowing beneath as pages 2+ (tiled with
  // the terms-page letterhead). ONE continuous document, no app sections.
  function renderPositioned(geo, tokens) {
    const page = geo.page || {};
    pageWpt = Number(page.w_pt) || 612;
    const pageH = Number(page.h_pt) || 792;
    const margin = page.margin || { top: 72, left: 90, right: 90, bottom: 72 };
    flowMode = false;
    docSurface.classList.remove("tw-flow");
    clearDocSurface();

    // What a drag is allowed to do, taken from the server's own statement of it. max_box is only
    // re-derived from the margins for a browser holding a pre-v4 cached response, which is the
    // one case where the field can be missing — two independent subtractions of the same margins
    // is otherwise exactly how a handle ends up offering a size the server refuses.
    //
    // Set AFTER the clear, not before: test_preview_survives_rerender pins clearDocSurface() as
    // the FIRST thing this function does, because a surface clear that skips the island reclaim
    // is what made the Epoxy price box render empty.
    const maxBox = page.max_box || {};
    boxLimits = {
      pageW: pageWpt, pageH: pageH,
      maxW: Number(maxBox.w_pt) || (pageWpt - (margin.left || 0) - (margin.right || 0)),
      maxH: Number(maxBox.h_pt) || (pageH - (margin.top || 0) - (margin.bottom || 0)),
      minPt: Number(maxBox.min_pt) || 12,
      // The last y an AUTO-grown box may reach (growRoomPt). Not a drag bound — a drag is bounded
      // by the sheet, because Kyle designs into the margins and every template already has boxes
      // outside the printable area. Auto-growth is different: nobody is watching the pointer, so
      // it stops at the bottom margin, past which Word does not print the text anyway.
      printBottom: pageH - (Number(margin.bottom) || 0),
    };

    const arts = (geo.images || []).slice().sort((a, b) => (a.para_index || 0) - (b.para_index || 0));

    // Page 1 — fixed page-size sheet, artwork behind, boxes on top.
    const p1 = document.createElement("div");
    p1.className = "tw-page";
    p1.style.width = pageWpt + "pt";
    p1.style.height = pageH + "pt";
    p1.style.overflow = "hidden";
    docSurface.appendChild(p1);
    if (arts.length) {
      const im = arts[0];
      artUrl(im.name).then(u => {
        if (!u) return;
        const img = document.createElement("img");
        img.className = "tw-page-art";
        img.style.left = Math.max(0, im.x_pt || 0) + "pt";
        img.style.top = Math.max(0, im.y_pt || 0) + "pt";
        img.style.width = (im.w_pt || pageWpt) + "pt";
        img.style.height = (im.h_pt || pageH) + "pt";
        img.alt = "";
        img.src = u;
        p1.prepend(img);
        applyZoom();
      });
    }

    const byBox = new Map();
    templateBlocks.forEach(b => {
      if (b.txbx == null) return;
      if (!byBox.has(b.txbx)) byBox.set(b.txbx, []);
      byBox.get(b.txbx).push(b);
    });
    boxDesign.clear();
    for (const box of (geo.boxes || [])) {
      const list = byBox.get(box.id);
      if (!list || box.x_pt == null) continue;
      const el = document.createElement("div");
      el.className = "tw-txbx";
      el.dataset.boxId = String(box.id);
      // THE EDITING HOST. One box, one editable region, the way a Word text box behaves: click in
      // and drag through every paragraph it holds. Everything inside inherits this, so nothing
      // else on the page needs a contenteditable of its own.
      el.contentEditable = "true";
      el.spellcheck = false;
      // The template's own geometry, kept so Reset has somewhere to go back TO and so an
      // override can be stored as a difference from it rather than as an absolute rect.
      boxDesign.set(box.id, { x_pt: Number(box.x_pt) || 0, y_pt: Number(box.y_pt) || 0,
                              w_pt: Number(box.w_pt) || 200, h_pt: Number(box.h_pt) || 0 });
      // Writes left/top/width/minHeight AND dataset.boxHPt, laying any saved drag over the
      // design — so a restored box is created at its saved size rather than jumping there.
      applyBoxGeom(el);
      renderBlockList(el, list, tokens);
      addBoxTools(el);
      p1.appendChild(el);
    }

    // Pages 2+ — the plain-body flow (Terms & Conditions). The blank body
    // paragraphs BEFORE the first real one are page 1's invisible anchor
    // lines behind the artwork — not meaningful content, so they aren't
    // rendered (and therefore can't be overridden; they stay untouched in
    // the generated file). The terms are PAGINATED into fixed-height pages
    // (see repaginateTerms) rather than one continuous div, so text never
    // flows across the letterhead's red band / next-page logo.
    const bodyBlocks = templateBlocks.filter(b => b.txbx == null);
    const firstReal = bodyBlocks.findIndex(b => String(b.text).trim());
    const flowBlocks = firstReal >= 0 ? bodyBlocks.slice(firstReal) : [];
    if (flowBlocks.length) {
      // Render the units ONCE into a detached div so their element identity
      // (dataset.id, tw-dirty, pristine tracking, collectOverrides) is created
      // a single time; repaginateTerms only ever MOVES them between pages.
      const flow = document.createElement("div");
      renderBlockList(flow, flowBlocks, tokens);
      _termsUnits = Array.from(flow.children);
      _termsGeom  = { pageH, margin, topReservePt: 0 };
      repaginateTerms();
      const contArt = arts.find(a => (a.para_index || 0) > 0) || arts[0];
      if (contArt) {
        artUrl(contArt.name).then(u => {
          if (!u) return;
          _termsArtUrl = u;
          docSurface.querySelectorAll(".tw-terms-page").forEach(applyTermsArt);
          // Reserve a measured top band so packed terms text starts below the
          // continuation logo's ink (once per art; deferred while the caret is
          // in a terms page, so no repagination loop).
          measureTermsBand(u, contArt.name).then(band => {
            if (!_termsGeom) return;
            if (band !== (_termsGeom.topReservePt || 0)) {
              _termsGeom.topReservePt = band;
              scheduleRepaginate(0);
            }
          });
        });
      }
    } else {
      _termsUnits = null; _termsGeom = null;
    }
  }

  // Paint the terms-page letterhead onto one page div: the SAME art, sized to
  // exactly one page and NOT repeated (each page is its own sheet), so no page
  // shows a second page's logo / red band bleeding in.
  function applyTermsArt(pg) {
    if (!_termsArtUrl || !_termsGeom) return;
    pg.style.backgroundImage = `url("${_termsArtUrl}")`;
    pg.style.backgroundSize = `${pageWpt}pt ${_termsGeom.pageH}pt`;
    pg.style.backgroundRepeat = "no-repeat";
  }

  // Measure how far the continuation letterhead's ink reaches into the TOP band
  // of the text column, so repaginateTerms can reserve that as extra padding-
  // top (the buffalo logo sits top-right, ~y 54-120pt in Kyle's art, and the
  // real docx clears it with blank leading paragraphs). Fully data-driven — we
  // scan the art the SAME way it's painted (as a full-page background covering
  // pageWpt x pageH), so a different template's art yields a different reserve;
  // NO pixel constant is baked in. Returns a Promise<pt> in [0,120]; resolves 0
  // on no ink or any error (canvas taint, decode failure).
  //
  // Cached per WORK TYPE + media name, for the same reason artUrl() is: templates
  // reuse PNG filenames (image1.png), so a name-only key made a base-bid switch
  // reserve the previous template's top band on the T&C page. Same class of bug as
  // the stale-letterhead one that comment already warns about.
  function measureTermsBand(dataUrl, mediaName) {
    const key = mediaName ? (effectiveWorkType() + ":" + mediaName) : dataUrl;
    if (_termsBandCache.has(key)) return Promise.resolve(_termsBandCache.get(key));
    if (!dataUrl || !_termsGeom) return Promise.resolve(0);
    const { pageH, margin } = _termsGeom;
    const pageW = pageWpt || 612;
    return new Promise((resolve) => {
      let done = false;
      const finish = (v, cache) => {
        if (done) return; done = true;
        if (cache) _termsBandCache.set(key, v);
        resolve(v);
      };
      try {
        const img = new Image();
        img.onerror = () => finish(0, false);           // don't cache a decode failure — allow retry
        img.onload = () => {
          try {
            // Downscale the full page to a small canvas; s = page pt -> canvas px.
            const s = 300 / pageW;
            const cw = Math.max(1, Math.round(pageW * s));
            const ch = Math.max(1, Math.round((pageH || 792) * s));
            const cnv = document.createElement("canvas");
            cnv.width = cw; cnv.height = ch;
            const ctx = cnv.getContext("2d", { willReadFrequently: true });
            if (!ctx) return finish(0, false);
            ctx.drawImage(img, 0, 0, cw, ch);            // art covers the whole page box, same as the bg
            // Scan the TOP strip (margin.top .. margin.top+120pt) across the
            // text column (margin.left .. pageW-margin.right), all in canvas px.
            const x0 = Math.max(0, Math.floor(margin.left * s));
            const x1 = Math.min(cw, Math.ceil((pageW - margin.right) * s));
            const y0 = Math.max(0, Math.floor(margin.top * s));
            const y1 = Math.min(ch, Math.ceil((margin.top + 120) * s));
            const sw = Math.max(1, x1 - x0), sh = Math.max(1, y1 - y0);
            const data = ctx.getImageData(x0, y0, sw, sh).data;   // throws if tainted
            let maxRow = -1;
            for (let ry = 0; ry < sh; ry++) {
              for (let rx = 0; rx < sw; rx++) {
                const p = (ry * sw + rx) * 4;
                const r = data[p], g = data[p + 1], b = data[p + 2], a = data[p + 3];
                if (a > 20 && (r < 245 || g < 245 || b < 245)) { if (ry > maxRow) maxRow = ry; break; }
              }
            }
            let band = 0;
            if (maxRow >= 0) {
              const inkYpt = (y0 + maxRow) / s;          // canvas px -> page pt
              band = Math.min(120, Math.max(0, inkYpt + 6 - margin.top));
            }
            finish(band, true);
          } catch { finish(0, false); }                  // e.g. canvas taint — retry next time
        };
        img.src = dataUrl;
      } catch { finish(0, false); }
    });
  }

  // Pack the terms blocks into fixed-height page sheets by MEASURED height, so
  // content never crosses a page boundary (where the letterhead's red band and
  // next-page logo live). Uses layout metrics (offsetTop/offsetHeight/
  // clientHeight) which are immune to the #doc-zoom CSS transform — never
  // getBoundingClientRect, which the transform scales. Blocks are MOVED
  // (appendChild), never recreated, so their identity/dataset/dirty state and
  // collectOverrides() all keep working.
  function repaginateTerms() {
    if (flowMode || !_termsUnits || !_termsUnits.length || !_termsGeom) return;
    const { pageH, margin, topReservePt } = _termsGeom;
    docSurface.querySelectorAll(".tw-terms-page").forEach(p => p.remove());  // units survive via _termsUnits
    let page = null;
    const newPage = () => {
      page = document.createElement("div");
      page.className = "tw-page tw-terms-page";
      // The terms flow has no text box, so the PAGE is the host -- the same unit boxLines and the
      // box-wide gestures already treat it as.
      page.contentEditable = "true";
      page.spellcheck = false;
      page.style.width = pageWpt + "pt";
      page.style.height = pageH + "pt";     // border-box: padding lives inside the page
      page.style.overflow = "hidden";
      // Reserve the measured logo band on top of the normal top margin; the
      // padded box drives roomBottom()/packing/backgroundSize automatically.
      page.style.padding = `${margin.top + (topReservePt || 0)}pt ${margin.right}pt ${margin.bottom}pt ${margin.left}pt`;
      applyTermsArt(page);
      docSurface.appendChild(page);
    };
    newPage();
    const roomBottom = () => page.clientHeight - parseFloat(getComputedStyle(page).paddingBottom || "0");
    for (const el of _termsUnits) {
      page.appendChild(el);                                     // MOVE — identity preserved
      if (el.offsetTop + el.offsetHeight > roomBottom()) {
        if (page.children.length > 1) { newPage(); page.appendChild(el); }
        // A single block taller than a page: let THIS page grow rather than
        // clip contract text (overflow:hidden would silently hide it).
        if (el.offsetTop + el.offsetHeight > roomBottom()) {
          page.style.height = "auto";
          page.style.minHeight = pageH + "pt";
        }
      }
    }
    applyZoom();                                                // total height changed
  }

  // Repaginate off the critical path, but NEVER while the caret is inside a
  // terms page (it would destroy the selection). If deferred, a docSurface
  // focusout that leaves the terms flow runs it.
  let _repagTimer = null, _repagPending = false;
  const focusInTerms = () => {
    const a = document.activeElement;
    return !!(a && a.closest && a.closest(".tw-terms-page"));
  };
  function scheduleRepaginate(delay = 600) {
    if (_repagTimer) clearTimeout(_repagTimer);
    _repagTimer = setTimeout(() => {
      if (focusInTerms()) { _repagPending = true; return; }
      repaginateTerms();
    }, delay);
  }
  /** The computed previews normalise themselves when the caret leaves: an emptied line goes back
   *  to its computed value, an Enter'd notes bullet is re-split into real bullets. They used to
   *  hear that on their own containers, which no longer receive focus events at all -- the box
   *  does -- so the surface hands it down.
   *
   *  Guarded on the caret really having left the BOX the preview lives in. Each of these rebuilds
   *  its children, and rebuilding while the caret is still in a sibling line of the same box would
   *  drop it mid-edit. */
  docSurface.addEventListener("focusout", (e) => {
    const from = editingBox(e.target);
    const to = e.relatedTarget;
    if (from) {
      const left = (node) => node && node.isConnected !== false && from.contains(node)
                             && !(to && from.contains(to));
      if (left(systemPreviewEl)) renderSystemPreview();
      if (left(notesPreviewEl)) renderNotesPreview();
      // EVERY PRICE ROW, not the two containers that used to be named here. The other eight rows
      // normalised on their own `focusout` while each of them was its own editing host -- which is
      // exactly what made moving the caret from one price line to the next re-render the rest of
      // the box under the estimator. They have no host now, so this is where they are normalised:
      // once, when the caret leaves the box they live in.
      if (from.querySelector && from.querySelector("[data-po-kind=\"line\"][data-po-linekey]")
          && !(to && from.contains(to))) {
        try { refreshPriceDisplay(); } catch {}
      }
    }
    if (!_repagPending) return;
    if (to && to.closest && to.closest(".tw-terms-page")) return;   // still in terms — wait
    _repagPending = false;
    repaginateTerms();
  });

  // Geometry-less fallback (a template with no floating boxes, or older
  // cached payloads): the same continuous flow — text boxes' content first,
  // then the body — on one white page with synthetic field captions.
  function renderFlow(tokens) {
    flowMode = true;
    pageWpt = 612;
    docSurface.classList.add("tw-flow");
    clearDocSurface();
    const pg = document.createElement("div");
    pg.className = "tw-page tw-flow";
    // The fallback layout has no floating boxes, so the PAGE is the editing host -- the same role
    // a .tw-txbx plays on a template that has them. Without this the flow renders as plain text
    // nobody can type in, because the paragraphs stopped carrying contenteditable of their own.
    pg.contentEditable = "true";
    pg.spellcheck = false;
    pg.style.width = pageWpt + "pt";
    docSurface.appendChild(pg);
    renderBlockList(pg, templateBlocks.filter(b => b.txbx != null), tokens);
    renderBlockList(pg, templateBlocks.filter(b => b.txbx == null), tokens);
  }

  async function initDocumentEditor() {
    const wt = effectiveWorkType();
    const audience = state.audience || "Direct";
    // The endpoint is auth-gated; wait for the Supabase token like the other
    // pull-on-load fetches do, so a slow login doesn't 401 the template.
    try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch {}
    try {
      const res = await fetch(
        `/api/proposal-template?work_type=${encodeURIComponent(wt)}&audience=${encodeURIComponent(audience)}`,
        { headers: TW.authHeaders() });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const j = await res.json();
      templateBlocks = Array.isArray(j.blocks) ? j.blocks : [];
      templateVersion = String(j.template_version || "");
      annotateRegions(templateBlocks);
      blockById.clear();
      templateBlocks.forEach(b => blockById.set(b.id, b));
      // Ids belong to ONE template file. Carrying a bullet/indent across a base-bid switch
      // would land it on whatever paragraph happens to hold that id in the other template;
      // restoreSavedOverrides re-reads the new template's own saved entry below.
      paraById.clear();

      const tokens = computeTokenValues(Object.assign({}, state, TW.readForm(form)));
      const geo = j.geometry || {};
      const hasBoxes = Array.isArray(geo.boxes) && geo.boxes.some(b => b.x_pt != null)
        && templateBlocks.some(b => b.txbx != null);
      // BEFORE the render, and after templateVersion is known (the guard reads it): every box is
      // then created at its saved size and position instead of appearing at the template's and
      // moving a frame later.
      loadBoxOverrides(wt, audience);
      if (hasBoxes) renderPositioned(geo, tokens);
      else renderFlow(tokens);

      // `tokens` so a restored run tagged with a token gets the CURRENT estimate value rather
      // than the one that was on screen when the estimator formatted it.
      restoreSavedOverrides(wt, audience, tokens);
      renderSystemPreview();
      renderNotesPreview();
      // restoreSavedOverrides changed some terms blocks' text (heights), so
      // repaginate once more against the edited content.
      repaginateTerms();
      refreshPriceDisplay();   // repaint now that the preview els live in the page
      applyZoom();
      // Cheap insurance: if a locally-installed proposal font activates late,
      // re-measure once fonts settle.
      try { if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { scheduleRepaginate(0); try { fitNotesBox(); } catch {} }); } catch {}
    } catch (err) {
      // Say something, always. This was silent: the only user-facing hook was
      // #doc-loading, which lives INSIDE #doc-surface and is therefore destroyed
      // by the first successful render — so a failure on any LATER render (i.e.
      // every base-bid switch) showed nothing, logged nothing, and left a blank
      // page that looked identical to a rendering bug. That cost real debugging
      // time, so the error now reaches the console and the screen either way.
      console.error("Proposal preview failed to render:", err);
      let loading = document.getElementById("doc-loading");
      if (!loading) {
        clearDocSurface();          // reclaims the islands before wiping
        loading = document.createElement("div");
        loading.id = "doc-loading";
        loading.className = "tw-page";
        loading.style.padding = "72pt 90pt";
        docSurface.appendChild(loading);
      }
      // Degraded fallback: surface the price preview alone so the estimator can
      // still verify pricing and continue; previously saved document edits still
      // ship via collectOverrides()'s state fallback.
      loading.textContent = "Couldn't load the document preview — showing the price summary instead. You can still continue.";
      stagingPanel.hidden = false;
      loading.appendChild(stagingPanel);
      refreshPriceDisplay();
      applyZoom();
    }
  }

  // Phase B: when a base-bid switch changes the EFFECTIVE work type (e.g. an
  // epoxy job whose base is now a polish sheet), re-derive the whole proposal
  // from the new role: adapt the sidebar rows/labels, re-seed untouched
  // narrative + notes boilerplate (hand edits survive), and reload the template
  // + artwork. No-op when the type is unchanged (same-role base switches — the
  // common case — only re-price, via applyAndRefresh).
  //
  // NB: this used to claim initDocumentEditor was "idempotent and safe to re-run".
  // It was not, and that assumption is what broke switching back to an epoxy base:
  // re-running it wiped the document surface, which destroyed the live price rows
  // that had been MOVED into it, and epoxy's PRICE box is built entirely from
  // those. It is safe now only because clearDocSurface() reclaims them first — if
  // you add another surface clear, route it through there too.
  function reloadForWorkType() {
    const cur = effectiveWorkType();
    if (cur === _lastEffWt) return;
    _lastEffWt = cur;
    adaptToWorkType();
    buildTextureControl();
    updateDocName();
    seedNarrative(true);          // scope/schedule/exclusions (sync fields + persist)
    reseedNotesForWorkType();     // default notes (async re-fetch, self-repaints)
    initDocumentEditor();         // template + artwork reload, token recompute, re-render
  }

  // Mark blocks dirty as they're edited (delegated — blocks re-render freely).
  /** One paragraph's dirty / empty / warning state, recomputed from what is in the DOM now. */
  function syncBlock(el) {
    // A NUMBERED TERMS CLAUSE CANNOT BE EMPTIED. Refused right here, so the estimator sees the
    // refusal instead of discovering it as a bare "1." in a signed contract. Everything below
    // then runs against the restored paragraph, which is why this is not an early return.
    restoreEmptiedClause(el);
    const cur = serializeBlock(el);
    // `tw-fmt` marks "the estimator formatted this", which the text comparison cannot see.
    // Without it a formatting-only edit stayed un-dirty, so refreshDocumentFills() rewrote the
    // block's innerHTML on the next sidebar change and silently erased the work.
    const changed = cur !== pristineById.get(Number(el.dataset.id)) || el.classList.contains("tw-fmt");
    el.classList.toggle("tw-dirty", changed);
    el.classList.toggle("tw-empty", !cur.trim());
    // ⚠ reminder when an edited free paragraph carries a price ($) or an SF/LF
    // area measure (covers the gyp/GC price rows, which edit as plain paragraphs).
    el.classList.toggle("tw-dirty-warn", changed && /\$\s?\d|\bSF\b|\bLF\b/i.test(cur));
  }

  /** ONE EDIT, THE WHOLE BOX. Because the box is the editing host, a single keystroke can change
   *  more than one line -- a Delete over a three-line selection is one `input` event -- and a
   *  handler that only looked at the caret's own line would leave the other two edited on screen
   *  and unedited in the draft.
   *
   *  The caret's line is always synced. The box's OTHER paragraphs are synced too, but only where
   *  a pristine text was recorded for them: without one, the `cur !== pristine` test compares
   *  against `undefined` and would paint every untouched paragraph in the box as dirty. That
   *  guard is what keeps the sweep from inventing edits. */
  docSurface.addEventListener("input", (e) => {
    const box = editingBox(e.target);
    if (!box) return;
    const el = lineTarget(e);
    const caretBlock = el && el.classList.contains("tw-block") ? el : null;
    if (caretBlock) syncBlock(caretBlock);
    box.querySelectorAll(".tw-block").forEach(b => {
      if (b !== caretBlock && pristineById.has(Number(b.dataset.id))) syncBlock(b);
    });
    // The three computed families, each through its own channel, and only when this box actually
    // holds one of them -- a WORK-box edit has no business rewriting the price overrides.
    if (systemPreviewEl.isConnected && box.contains(systemPreviewEl)) syncSystemRows();
    if (notesPreviewEl.isConnected && box.contains(notesPreviewEl)) syncNotesFromDom();
    // EVERY WHOLE-LINE PRICE ROW IN THIS BOX, which is what the sweep has to be now that the rows
    // declare no editing host of their own. It used to name two containers by id, and that was
    // survivable only because six rows carried `contenteditable` and therefore heard their own
    // `input` events. They do not any more -- a keystroke arrives at the box -- so anything this
    // sweep cannot see is an edit that reaches no channel and is silently lost on the next
    // repaint. It also closes a gap that was already open: the combo breakout, the per-room lines
    // and the ALTERNATE block are rendered into containers that NEVER had a host, so typing in
    // one of those lines had nowhere to persist to.
    if (box.querySelector("[data-po-kind=\"line\"][data-po-linekey]")) syncPriceLinesIn(box);
    schedulePersistOverrides();
    // A terms-page block can change height as it's edited; repaginate once
    // the caret leaves the terms flow (scheduleRepaginate defers on focus).
    if (box.classList.contains("tw-terms-page")) scheduleRepaginate();
  });


  // ══ UNDO AND REDO, over the editor's OWN model ═══════════════════════════════════════════
  /** Hanz, 2026-08-27, on the Proposal Editor: "I cant use Keyboard shortcuts. I wanted to
   *  control z but didnt work. when I deleted all in the textbox."
   *
   *  CTRL+Z WAS NEVER SWALLOWED. The Ctrl handler below returns for anything that is not a/b/i/u,
   *  so the browser's native undo really did run -- it had nothing to undo. Every edit this editor
   *  makes is a PROGRAMMATIC DOM mutation, and programmatic mutation does not go on a
   *  contenteditable's native undo stack: the box-wide delete is els.forEach(clearBoxLine), Enter
   *  is insertBreakAt, Tab is paraAction, B/I/U is toggleFormat, and each one preventDefault()s
   *  the browser's own version for a reason written above it (execCommand emits b/i/u TAGS that
   *  fmtAt cannot read; a browser Enter merges two paragraphs and destroys an id the customer's
   *  document is filled BY POSITION with). On top of that, any repaint or repagination moves the
   *  nodes, and moving a node throws the native stack away outright -- so even ordinary typing
   *  stopped being undoable the moment a repagination ran.
   *
   *  So the editor keeps its own stack. AN ENTRY IS A PRE-IMAGE OF ONE EDITING HOST -- the box, or
   *  the terms page, the same unit boxLines and every box-wide gesture already work in. Per box
   *  rather than per document because that is what bounds it: a box is tens of lines, the sheet is
   *  hundreds, and a stack of whole-document snapshots on a long editing session is the memory
   *  growth the depth limit exists to prevent.
   *
   *  EVERY LINE IS STORED THROUGH ITS OWN CHANNEL, never as innerHTML. A .tw-block is stored as
   *  RUNS (editRuns) and restored with renderRuns, which is the same round trip a format press
   *  makes, so the formatting and the .tw-fill spans come back intact. The three computed families
   *  store TEXT and are restored by writing textContent and dispatching the page's own input
   *  event -- character for character what clearBoxLine already does to them, so the dirty flags,
   *  the override persistence and the emptied-clause protection all run on the way back exactly as
   *  they ran on the way out.
   *
   *  WHAT IS DELIBERATELY NOT ON THE STACK:
   *
   *   * BOX GEOMETRY -- drag-resize, Fit to text, Reset box. It has its own affordance already
   *     ("Reset box" in the box tools), and this surface is a to-scale preview of a printed page
   *     registered against baked artwork: a Ctrl+Z aimed at a word that silently moved a text box
   *     by a few points would be a worse bug than the one it fixed.
   *   * THE SIDEBAR. This is bound to docSurface, so a Ctrl+Z with the caret in the notes textarea
   *     or a pricing field is the browser's own undo, which is the right one for a plain input.
   *   * ANYTHING ACROSS A TEMPLATE RELOAD. clearDocSurface() drops both stacks: the ids an entry
   *     names belong to the template that was on screen, and replaying them into a different one
   *     would write the estimator's words into the wrong paragraph of a document a customer signs.
   *   * A LOCKED NUMBERED TERMS CLAUSE's paragraph properties. The para half of a restore goes
   *     through setParaState, which refuses a locked paragraph, so no undo can renumber the
   *     contract. Its TEXT is restorable, because editing that text was allowed in the first
   *     place and the payload filter (blanksANumberedClause) is the same in both directions. */
  const UNDO_DEPTH = 60;
  /** How long a burst of typing stays ONE undo. Long enough that an ordinary sentence is not
   *  chopped into keystrokes, short enough that a pause reads as "I finished that thought". */
  const UNDO_COALESCE_MS = 700;
  let _undoStack = [];
  let _redoStack = [];
  let _undoUnit = null;         // the gesture the open unit belongs to
  let _undoUnitAt = 0;
  let _undoBusy = false;        // a restore is running: nothing it does may open a new unit

  /** A stable name for one editable line, so an entry survives its nodes being replaced.
   *
   *  Element identity is not enough. repaginateTerms moves blocks between pages, renderSystemPreview
   *  and renderNotesPreview rebuild their children outright, and a restore that held references
   *  would write into detached orphans and report success. Each family already has an identity the
   *  rest of the page persists it by, and this is that identity and nothing new. */
  function undoLineKey(el) {
    if (!el || !el.classList) return null;
    const d = el.dataset || {};
    if (el.classList.contains("tw-block"))
      return d.id == null || d.id === "" ? null : "b:" + d.id;
    if (d.poLinekey != null && d.poLinekey !== "") return "p:" + d.poLinekey;
    if (d.sysLine != null && d.sysLine !== "") return "s:" + d.sysIndex + ":" + d.sysLine;
    if (d.noteIndex != null && d.noteIndex !== "") return "n:" + d.noteIndex;
    return null;
  }

  /** Every editable line on the surface, by key. Rebuilt at each restore rather than cached: a
   *  repagination between the push and the pop is the normal case, not the exception. */
  function undoLiveLines() {
    const map = new Map();
    if (!docSurface || !docSurface.querySelectorAll) return map;
    docSurface.querySelectorAll(LINE_SEL).forEach((el) => {
      const k = undoLineKey(el);
      if (k && !map.has(k)) map.set(k, el);
    });
    return map;
  }

  /** One line as an entry records it. */
  function undoLineRec(el, key) {
    if (el.classList.contains("tw-block")) {
      const set = paraById.get(Number(el.dataset.id));
      return { key: key, runs: editRuns(el), fmt: el.classList.contains("tw-fmt"),
               para: set ? { bullet: !!set.bullet, indent: Number(set.indent) || 0 } : null };
    }
    return { key: key, text: serializeBlock(el) };
  }

  /** The line the caret is in, by key. Cheap -- one closest() off the range's start container, no
   *  offsets and no markers -- which is what lets every keystroke ask for it. */
  function undoCaretLine() {
    const el = lineAtSelection();
    return (el && docSurface.contains(el) && undoLineKey(el)) || "?";
  }

  /** Where the caret is, as an entry records it, or null when it cannot be read safely.
   *
   *  READ LIVE, and only when a unit is actually opening -- at most once per word typed. The
   *  obvious alternative, keeping it current on a selectionchange listener, costs a marker round
   *  trip through selectionRange on every caret movement in the document, including on the notes
   *  bullets and the price rows, which have never had one taken on them.
   *
   *  `safe` is false on the beforeinput path and only there. selectionRange drops two control
   *  characters into the text and takes them out again, and doing that inside beforeinput moves the
   *  very range the browser is about to edit with. An entry from that path carries no caret, and
   *  the restore puts one on the first line it touched instead -- which for a single-line edit is
   *  the same line, at its start. */
  function undoCaretRec(safe) {
    if (!safe) return null;
    const el = lineAtSelection();
    if (!el || !docSurface.contains(el)) return null;
    const key = undoLineKey(el);
    if (!key) return null;
    const r = selectionRange(el);
    return r ? { key: key, start: r[0], end: r[1] } : null;
  }

  /** The current caret and box selection, as an entry records them.
   *
   *  An undo that restores the text and drops the caret somewhere else reads as a bug even when
   *  every character is right, so both go on the stack. */
  function undoSelectionRec(safe) {
    return {
      caret: undoCaretRec(safe),
      boxSel: boxSel && boxSel.length ? boxSel.map(undoLineKey).filter(Boolean) : null,
    };
  }

  /** The pre-image of one editing host. */
  function undoSnapshot(box, safe) {
    if (!box || !box.querySelectorAll) return null;
    const lines = [];
    box.querySelectorAll(LINE_SEL).forEach((el) => {
      const key = undoLineKey(el);
      if (key) lines.push(undoLineRec(el, key));
    });
    if (!lines.length) return null;
    const ta = document.getElementById("notes-text");
    // THE NOTES TEXTAREA IS THE BULLETS' SINGLE SOURCE OF TRUTH, so a notes box carries it too.
    // The bullets are rebuilt from it and their count changes with the text, which makes restoring
    // a deleted bullet by key alone impossible once its element is gone.
    const holdsNotes = !!(ta && notesPreviewEl && box.contains && box.contains(notesPreviewEl));
    const snap = undoSelectionRec(safe);
    snap.lines = lines;
    snap.notes = holdsNotes ? String(ta.value || "") : null;
    snap.sig = JSON.stringify([lines, snap.notes]);
    return snap;
  }

  /** The document as an existing entry describes it, read LIVE.
   *
   *  Two jobs, and both matter. It is the redo entry an undo leaves behind, and its signature is
   *  how a unit that turned out to change nothing is recognised -- a Backspace refused at the start
   *  of a paragraph, a ribbon press on a locked clause, a mousedown that never became a click.
   *  Those are skipped at the pop rather than filtered at the push, because at push time the edit
   *  has not happened yet and nobody can know. */
  function undoMirror(snap) {
    const live = undoLiveLines();
    const lines = [];
    for (const rec of snap.lines) {
      const el = live.get(rec.key);
      if (el) lines.push(undoLineRec(el, rec.key));
    }
    const ta = document.getElementById("notes-text");
    // SAFE: a mirror is only ever taken from undoStep, which runs on the Ctrl+Z keydown -- never
    // from inside a beforeinput.
    const out = undoSelectionRec(true);
    out.lines = lines;
    out.notes = snap.notes == null ? null : String((ta && ta.value) || "");
    out.sig = JSON.stringify([lines, out.notes]);
    return out;
  }

  /** Open a new undo unit, unless this gesture belongs to the one already open.
   *
   *  WHAT ONE UNDO UNIT IS: a gesture, not a mutation. Enter, Tab, a box-wide delete, a paste and
   *  a ribbon press are each named uniquely and are therefore always their own unit. Typing and
   *  deleting coalesce, and the run is closed by any of four boundaries -- an idle gap of
   *  UNDO_COALESCE_MS, the caret moving to a different line, the direction changing (typing then
   *  deleting is two units, not one), and a typed SPACE, which is what makes an undo give back the
   *  word just typed rather than the paragraph. An idle gap alone would make undo depend on how
   *  fast somebody types; boundaries alone would make one uninterrupted sentence a single,
   *  unusable unit. */
  function undoPush(unit, node, safe) {
    if (_undoBusy) return false;
    const now = Date.now();
    if (typeof unit === "string" && unit.indexOf("type:") === 0
        && unit === _undoUnit && now - _undoUnitAt < UNDO_COALESCE_MS) {
      _undoUnitAt = now;
      return false;                     // still the same burst -- the open unit already covers it
    }
    const box = editingBox(node) || editingBox(lineAtSelection());
    const snap = box ? undoSnapshot(box, safe !== false) : null;
    _undoUnit = unit;
    _undoUnitAt = now;
    if (!snap) return false;
    const top = _undoStack[_undoStack.length - 1];
    // A KEYSTROKE REACHES HERE TWICE -- once on keydown, once on the beforeinput the browser
    // raises for the same key -- and the second arrival finds the document byte for byte as the
    // first left it. One signature comparison de-duplicates that, and every other harmless
    // double-push with it, without a single timer.
    if (top && top.sig === snap.sig) return false;
    _undoStack.push(snap);
    if (_undoStack.length > UNDO_DEPTH) _undoStack.shift();
    _redoStack.length = 0;              // a new edit forks the history
    return true;
  }

  /** The bullet and the indent, back to what they were -- through setParaState, which refuses a
   *  locked paragraph, so this route cannot renumber a contract clause any more than Tab or the
   *  ribbon can. A null para means the estimator had set nothing and the template's own properties
   *  applied, which is a delete rather than a write. */
  function undoRestorePara(el, para) {
    const id = Number(el.dataset.id);
    const now = paraNow(id);
    if (!now) return false;
    if (!para) {
      if (!paraById.has(id) || now.locked) return false;
      paraById.delete(id);
      applyParaToEl(el, paraNow(id));
      return true;
    }
    const indent = Number(para.indent) || 0;
    if (now.bullet === !!para.bullet && now.indent === indent) return false;
    return setParaState(id, { bullet: !!para.bullet, indent: indent }, el);
  }

  /** Put one entry back on the page. */
  function undoRestore(snap) {
    const prevBusy = _undoBusy;
    _undoBusy = true;
    try {
      // THE CARET GOES FIRST, out of the way. renderNotesPreview refuses to rebuild the bullets
      // while the selection is inside them (focusInside reads the caret, not just activeElement),
      // and an undo of a deleted bullet is exactly the case that has to rebuild them. It is put
      // back at the end of this function, from the entry, which is where it was before the edit.
      try { const s = window.getSelection(); if (s && s.removeAllRanges) s.removeAllRanges(); } catch {}
      const ta = document.getElementById("notes-text");
      if (snap.notes != null && ta && String(ta.value || "") !== snap.notes) {
        ta.value = snap.notes;
        try { renderNotesPreview(); } catch {}
        try { TW.setState({ notes_text: ta.value }); } catch {}
      }
      const live = undoLiveLines();
      const fire = new Map();             // one editing host -> one line in it to dispatch from
      for (const rec of snap.lines) {
        const el = live.get(rec.key);
        if (!el) continue;                // that line is not on the page any more; skip it
        let touched = false;
        if (rec.runs) {
          if (!runsEqual(editRuns(el), rec.runs)) { renderRuns(el, rec.runs); touched = true; }
          if (el.classList.contains("tw-fmt") !== !!rec.fmt) {
            el.classList.toggle("tw-fmt", !!rec.fmt);
            touched = true;
          }
          if (undoRestorePara(el, rec.para)) touched = true;
        } else if (serializeBlock(el) !== rec.text) {
          el.textContent = rec.text;      // the computed families' own channel: see clearBoxLine
          touched = true;
        }
        if (!touched) continue;
        const host = editingBox(el) || docSurface;
        if (!fire.has(host)) fire.set(host, el);
      }
      // ONE dispatch per host, because every persistence sweep hanging off input is box-wide: N
      // events would each re-do the same sweep. This is what carries the restored text back into
      // the draft -- the dirty flags, the paragraph overrides, the three computed channels.
      fire.forEach((el) => { el.dispatchEvent(new Event("input", { bubbles: true })); });
      schedulePersistOverrides();
      // AND THE SELECTION, from the same entry. A box-wide selection is put back as a selection,
      // so undoing a Ctrl+A delete leaves the estimator looking at exactly what they were looking
      // at when they pressed Delete.
      const after = undoLiveLines();
      const selEls = (snap.boxSel || []).map((k) => after.get(k)).filter(Boolean);
      if (selEls.length) {
        boxSel = selEls;
        paintBoxSel();
        selectRangeAcross(selEls);
      } else {
        // AND A CARET EVEN WHEN THE ENTRY DOES NOT NAME ONE. The selection was dropped at the top
        // of this function so the previews could rebuild, so leaving here without placing one
        // takes the estimator's caret away entirely -- an undo they then have to click to recover
        // from. The first line the restore touched is where they were, near enough.
        const el = (snap.caret && after.get(snap.caret.key))
                   || (fire.size ? fire.values().next().value : null);
        if (el) {
          const host = editingBox(el);
          if (host && host.focus) { try { host.focus(); } catch {} }
          const total = el.classList.contains("tw-block")
            ? runsLength(editRuns(el)) : serializeBlock(el).length;
          const named = snap.caret && after.get(snap.caret.key) === el;
          const a = Math.max(0, Math.min(named ? (Number(snap.caret.start) || 0) : 0, total));
          const b = Math.max(a, Math.min(named ? (Number(snap.caret.end) || 0) : 0, total));
          placeSelection(el, a, b);
        }
      }
      return true;
    } finally {
      _undoBusy = prevBusy;
    }
  }

  /** One step in either direction. An entry that changes nothing is discarded rather than spent:
   *  a Ctrl+Z that visibly does nothing is the same complaint this whole section exists to fix. */
  function undoStep(from, to) {
    let guard = UNDO_DEPTH + 2;
    while (from.length && guard-- > 0) {
      const snap = from.pop();
      const mirror = undoMirror(snap);
      if (mirror.sig === snap.sig) continue;
      to.push(mirror);
      if (to.length > UNDO_DEPTH) to.shift();
      undoRestore(snap);
      _undoUnit = null;                   // whatever is typed next opens a fresh unit
      _undoUnitAt = 0;
      return true;
    }
    return false;
  }
  function undoOnce() { return undoStep(_undoStack, _redoStack); }
  function redoOnce() { return undoStep(_redoStack, _undoStack); }

  /** A template reload, a work-type switch, a rebuild: the history described paragraphs that no
   *  longer exist. Called from clearDocSurface, which cannot run before this module has been
   *  evaluated -- initDocumentEditor is invoked at the very bottom of this file. */
  function undoForget() {
    _undoStack.length = 0;
    _redoStack.length = 0;
    _undoUnit = null;
    _undoUnitAt = 0;
  }

  /** Which undo unit a keystroke belongs to, or null when it cannot change anything.
   *
   *  Ctrl+A, Ctrl+C, the arrows, Home/End, the function keys and the modifiers themselves all
   *  return null: an entry for a keystroke that moves nothing is a dead press of Ctrl+Z later. */
  function undoUnitForKey(e) {
    const k = String(e.key || "");
    const line = undoCaretLine();
    if (e.ctrlKey || e.metaKey) {
      const low = k.toLowerCase();
      if (low === "b" || low === "i" || low === "u") return "fmt:" + low;
      if (low === "v") return "paste";
      if (low === "x") return "cut";
      return null;
    }
    if (e.altKey) return null;
    if (k === "Enter") return "enter";
    if (k === "Tab") return "indent";
    if (k === "Backspace" || k === "Delete")
      return boxSel && boxSel.length ? "boxclear" : "type:delete:" + line;
    if (k.length !== 1) return null;
    return "type:insert:" + line;
  }

  // CAPTURE PHASE, so the pre-image is taken before any of the handlers below have run and before
  // the browser has applied its own default. Every one of them mutates.
  docSurface.addEventListener("keydown", (e) => {
    if (e.isComposing) return;            // an IME owns the keystroke; its commit lands on beforeinput
    const low = String(e.key || "").toLowerCase();
    if ((e.ctrlKey || e.metaKey) && !e.altKey && (low === "z" || low === "y")) {
      // BOTH SPELLINGS OF REDO. Ctrl+Y is Word's and Ctrl+Shift+Z is everything else's, and the
      // people using this come from both; honouring one of them is refusing half the office.
      e.preventDefault();
      if (low === "y" || e.shiftKey) redoOnce(); else undoOnce();
      return;
    }
    const unit = undoUnitForKey(e);
    if (unit) undoPush(unit, e.target);
  }, true);

  /** THE EDITS THAT ARRIVE WITHOUT A KEYSTROKE: a context-menu Delete, a drag-and-drop inside the
   *  box, an IME commit, a spell-check replacement. Each of them mutates the document and none of
   *  them is visible to a keydown handler. A keyboard-driven edit reaches here too, one beat after
   *  the keydown above already pushed -- and finds the document unchanged, so the signature check
   *  in undoPush drops it. */
  docSurface.addEventListener("beforeinput", (e) => {
    const type = String(e.inputType || "");
    if (type === "insertCompositionText") return;
    // NOT SAFE TO READ THE CARET HERE -- see undoCaretRec. A keyboard-driven edit has already been
    // pushed by the keydown above, caret and all, so the only entries this leaves without one are
    // the mouse-driven and IME edits, which no keydown ever sees.
    undoPush("type:" + (type.indexOf("delete") === 0 ? "delete" : "insert") + ":" + undoCaretLine(),
             e.target, false);
    // A SPACE CLOSES THE WORD -- not by pushing anything, since the space belongs to the unit that
    // is open, but by making whatever comes next open a new one. That is what turns Ctrl+Z into
    // "give me back the word I just typed" rather than "give me back the paragraph".
    //
    // Read off the TEXT BEING INSERTED rather than off the key, and read here rather than on the
    // keydown above, for the same two reasons. The keydown fires BEFORE this event, so closing the
    // unit there would leave this very space opening the next one -- the pre-image would be taken
    // from before the space, and an undo would take the space away with the word after it. And a
    // space arrives by more routes than the spacebar: an IME commit, a pasted phrase, a
    // spell-check replacement all end a word just as squarely.
    if (type.indexOf("delete") !== 0 && /\s/.test(String(e.data == null ? "" : e.data))) {
      _undoUnit = null;
      _undoUnitAt = 0;
    }
  }, true);

  /** A paste is its own unit and needs its own listener: the page's paste handler cancels the
   *  event, so the browser never raises the beforeinput that would otherwise cover it. */
  docSurface.addEventListener("paste", (e) => { undoPush("paste", e.target); }, true);

  /** THE RIBBON'S PRESSES, captured from the ribbon's container rather than from inside
   *  ensureFmtBar -- the bar is built lazily and this row is in the page from the start, and a
   *  capture listener here runs before the bar's own mousedown handler.
   *
   *  On mousedown, not click: by the time a click fires the ribbon has already preventDefault()ed
   *  its way around the selection, and the pre-image wants the document as it was when the
   *  estimator reached for the button. A mousedown that never becomes a click leaves an entry that
   *  changes nothing, which undoStep discards on the way past. */
  (function wireRibbonUndo() {
    const host = document.getElementById("fmt-ribbon");
    if (!host || !host.addEventListener) return;
    const mark = (name) => undoPush("ribbon:" + name + ":" + Date.now(),
                                    lineAtSelection() || fmtTargetBlock());
    host.addEventListener("mousedown", (e) => {
      const btn = e.target && e.target.closest
        ? e.target.closest("button[data-fmt], button[data-para]") : null;
      if (btn) mark(String(btn.dataset.fmt || btn.dataset.para || "press"));
    }, true);
    host.addEventListener("change", (e) => {
      const sizeBox = e.target && e.target.closest ? e.target.closest("[data-fmt]") : null;
      if (sizeBox) mark("size");
    }, true);
  })();

  // ── Wire the formatting ribbon to the focused block ───────────────────────
  // On screen before anything is focused, in its inert state. That IS the "static like a ribbon
  // in a word document" part: building the bar lazily on the first focusin is what made the old
  // one appear out of nowhere and vanish again.
  idleFmtBar();

  // Typing, clicking or moving the caret means the box selection is over. Registered before the
  // focusin handler below so the class is gone by the time the ribbon re-renders.
  docSurface.addEventListener("mousedown", () => { clearBoxSel(); });
  docSurface.addEventListener("input", () => { clearBoxSel(); });
  window.addEventListener("keydown", (e) => {
    // ESCAPE IS THE WAY OUT, and it has to be, because Tab now indents instead of moving focus.
    // Taking the keyboard's only exit from the text box away would be a real regression for
    // anybody not using a mouse, so once Escape's first job below has nothing to do, its second
    // is to let go of the editing host.
    if (e.key === "Escape" && !boxSel) {
      const host = document.activeElement;
      if (host && host.classList && host.classList.contains("tw-txbx") && host.blur) {
        host.blur();
        return;
      }
    }
    if (e.key !== "Escape" || !boxSel) return;
    // Stop here: the window handler below this one collapses an expanded text box, and somebody
    // dismissing a selection is not asking for the box they are reading to fold shut.
    e.stopPropagation();
    clearBoxSel();
  }, true);

  docSurface.addEventListener("focusin", (e) => {
    // From the CARET, not the focused element. Focus now lands on the box, once, and then stays
    // there while the estimator moves between its paragraphs -- so the focused element says
    // nothing about which paragraph the ribbon should act on. (selectionchange, below, is what
    // keeps it aimed as the caret moves within a box that already has focus.)
    const line = lineTarget(e);
    const el = line && line.classList.contains("tw-block") ? line : null;
    // A non-block editable inside the document — a `.tw-line-edit` price line, a box tool — is a
    // channel the run formatting cannot reach, so the ribbon lets go of its target rather than
    // staying aimed at whichever paragraph came before it.
    if (el) showFmtBar(el);
    else idleFmtBar();
  });

  // NO `focusout` HANDLER, deliberately. It called hideFmtBar(), which is exactly the behaviour
  // Kyle asked to be rid of. Focus leaving the paragraph — for the Tax select, the pricing rail,
  // another window, this ribbon's own size dropdown — now changes nothing: the ribbon keeps its
  // target and keeps the range it acts on, and the paragraph says which one it is on screen
  // (`.tw-fmt-target`). Both guards that handler carried went with it, including the load-bearing
  // one ("focus moved into the toolbar, so do not hide"), which has nothing left to guard.

  // Keep the button states honest as the estimator drags across differently-formatted words —
  // and RECORD the selection while it can still be read. That recording is what makes a press on
  // a ribbon at the top of the page land on the words highlighted down in the document.
  document.addEventListener("selectionchange", () => {
    if (_fmtBusy) return;
    // MOVING THE CARET BETWEEN PARAGRAPHS IS NOW A SELECTION CHANGE AND NOTHING ELSE. It used to
    // be a focusin per paragraph, because each one was its own editing host; with one host per box
    // no focus event fires at all, so this is the only place that can re-aim the ribbon. It aims
    // at the caret's own paragraph rather than re-checking the remembered one.
    const line = lineAtSelection();
    if (line && line.classList.contains("tw-block") && docSurface.contains(line)) {
      showFmtBar(line);
      return;
    }
    const el = fmtTargetBlock();
    if (!el) return;
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount) return;
    if (!el.contains(sel.getRangeAt(0).startContainer)) return;
    showFmtBar(el);
  });

  docSurface.addEventListener("keydown", (e) => {
    if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
    if (String(e.key).toLowerCase() === "a") {
      // ONE PRESS TAKES THE WHOLE BOX. Hanz, 2026-08-26: "When I control A it doesnt select
      // everything in Work."
      //
      // It used to be a ladder -- press once for the line, again to widen -- and the first press
      // was the problem, not the second: it preventDefault()ed the browser's own select-all and
      // put a one-LINE selection there instead. Under one editing host per box the browser would
      // already have selected the box, so the ladder's first rung actively took away the
      // behaviour asked for, and the widen that put it back was undiscoverable.
      //
      // EITHER FAMILY, still: a `.tw-block`, a `.tw-line-edit` price/system row, a `.tw-note-edit`
      // bullet. Ctrl+A anywhere in the PRICE box used to find nothing and look broken.
      const el = lineTarget(e);
      if (!el) return;
      e.preventDefault();
      boxSel = boxLines(el);
      paintBoxSel();
      // A REAL BROWSER SELECTION over the whole box, not just a painted class. This is what the
      // one-host change buys: the range can span every paragraph, so Delete, a paste, a typed
      // character and a ribbon press all act on the box through the ordinary paths instead of
      // each needing to know about `boxSel`. The class stays as the cue that survives the caret
      // moving on.
      selectRangeAcross(boxSel);
      if (el.classList.contains("tw-block")) showFmtBar(el);
      return;
    }
    const key = { b: "bold", i: "italic", u: "underline" }[String(e.key).toLowerCase()];
    if (!key) return;
    const line = lineTarget(e);
    const el = line && line.classList.contains("tw-block") ? line : null;
    if (!el) return;
    // Stop the browser's own handler: it runs execCommand, which emits <b>/<i>/<u> tags that
    // `fmtAt` cannot read — the formatting would show on screen and reach the .docx as nothing.
    e.preventDefault();
    toggleFormat(el, key);
  });

  // Enter inside a template paragraph = ONE line break, ours rather than the browser's.
  // See insertBreakAt for why: the browser's own Enter in a contenteditable can arrive as a
  // wrapper <div> whose placeholder <br> serializeBlock counts as a second newline, so the
  // blank line the estimator typed was not the blank line that got sent.
  //
  // shiftKey is deliberately NOT excluded: Shift+Enter is the line break everywhere else, and
  // a line break is the only thing this editor can represent, so both spellings do the same
  // thing. Ctrl/Cmd/Alt+Enter belong to other people and are left alone.
  docSurface.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
    // EVERY FAMILY NOW, not just template paragraphs. The computed lines used to let the browser
    // handle Enter, which was survivable while each of them was its own editing host: the worst it
    // could do was leave a stray <div> inside one line. Inside a box-wide host the browser's Enter
    // SPLITS the paragraph into two elements instead -- and a second `<p data-sys-line="area">` is
    // a row the writer has no channel for, so half the estimator's line would reach the customer
    // and half would vanish. One break inside one element is the only shape this editor can send.
    const el = lineTarget(e);
    if (!el) return;
    const lines = selectionLines();
    if (lines.length > 1) {                 // a break replacing a multi-line selection
      e.preventDefault();
      spliceLines(lines, [{ text: "\n", tok: null }]);
      return;
    }
    const sel = selectionRange(el);
    if (!sel) { e.preventDefault(); return; }   // caret unreadable: refuse rather than let the
                                                // browser split the paragraph
    e.preventDefault();
    const caret = insertBreakAt(el, sel[0], sel[1]);
    placeSelection(el, caret, caret);
    if (el.classList.contains("tw-block")) markEdited(el, false);   // a break is text, not format
    else el.dispatchEvent(new Event("input", { bubbles: true }));
  });

  /** Backspace at the very start of a line takes the LIST FORMATTING off, one rung at a time.
   *
   *  Hanz, 2026-08-25: "When I back space, it doesnt remove the bullet point."
   *
   *  It did nothing at all, and the reason is structural rather than a missing branch. Every
   *  `.tw-block` is its own editing host (`renderBlock` sets contentEditable per block;
   *  #doc-surface has none), so a browser cannot merge or delete across the boundary — Backspace
   *  at offset 0 has nowhere to go and is silently dropped. That same structure is what stops two
   *  paragraphs ever merging into one, which is worth keeping: a `.tw-block` IS one Word
   *  paragraph, identified by an id from the backend's walk, and the editor cannot invent a
   *  second one.
   *
   *  So Backspace at offset 0 does what Word does with the space it has: removes the bullet
   *  first, then walks the indent back to the margin, and only then gives up. The ladder is
   *  deliberate — in Word, Backspace on a bulleted line un-bullets it before it starts eating the
   *  indent, and an estimator pressing Backspace on a bullet is asking for the bullet to go.
   *
   *  Everything here is `paraAction`, the same call the ribbon's Bullet and Outdent buttons make,
   *  so this route cannot drift from them: it inherits the locked-clause refusal (un-bulleting a
   *  numbered TERMS clause renumbers the contract), the override persistence, and the terms
   *  repagination. The only thing it adds is the keystroke.
   *
   *  NOT handled, on purpose: the synthesized `{{#system}}` rows and the notes/price lines have no
   *  paragraph record at all (no `dataset.id`, no `paraNow` state), so there is no bullet state to
   *  turn off — `paraNow` misses and this returns without preventing the default, leaving them
   *  exactly as they were. */
  /** Delete or Backspace with a box selected: empty every line in it, in one go.
   *
   *  Each block is cleared through the same run algebra a hand-delete uses and then dispatches the
   *  page's own `input` event, so the dirty flags, the override persistence and the emptied-clause
   *  protection all run per block exactly as they would if somebody had cleared them one at a
   *  time. `collectOverrides` already handles N emptied blocks -- it emits one entry each -- and
   *  `blanksANumberedClause` still filters a numbered TERMS clause out of the payload, so a
   *  box-wide delete cannot renumber the contract. */
  docSurface.addEventListener("keydown", (e) => {
    if (!boxSel || e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
    if (e.key !== "Backspace" && e.key !== "Delete") return;
    e.preventDefault();
    const els = boxSel.slice();
    clearBoxSel();
    els.forEach(clearBoxLine);
    if (els.length) scheduleRepaginate();
  });

  /** TAB INDENTS THE PARAGRAPH. Shift+Tab takes the indent back.
   *
   *  Hanz, 2026-08-26: "is it possible when I click tab it indents the line? instead of scrolling
   *  down?" Nothing handled Tab before, so the browser moved focus to the next focusable thing and
   *  the page scrolled to reveal it.
   *
   *  Straight through `paraAction`, which is what the ribbon's indent buttons call -- so the
   *  locked-clause refusal, the override persistence and the terms repagination are the same ones,
   *  reached by a different key. A numbered contract clause still refuses, silently, and the
   *  keystroke is then NOT consumed: if the editor is not going to indent the line, moving the
   *  focus is better than doing nothing at all.
   *
   *  A tab CHARACTER is deliberately not an option. The paragraph's indent is a `w:ind` property
   *  on the whole paragraph and there is no tab-stop model underneath it, so a literal tab would
   *  travel into the customer's document as whitespace that no ribbon indent could ever line up
   *  with. Indenting the paragraph is what this document can represent.
   *
   *  Over a multi-line selection every template paragraph in it moves together, which is what the
   *  ribbon already does for a box selection -- one press, one visible result. */
  docSurface.addEventListener("keydown", (e) => {
    if (e.key !== "Tab" || e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
    const rung = e.shiftKey ? "outdent" : "indent";
    // WOULD THIS ACTUALLY MOVE THE LINE? `paraAction` reports that it wrote a state, not that the
    // state differs -- so at the margin it returned true having changed nothing, and Tab was
    // swallowed while appearing to do nothing at all. Asked here instead, for the same reason
    // Backspace hands the keystroke back at the margin: a key the editor will not act on belongs
    // to the browser. (A test caught this; the handler shipped it.)
    const canMove = (one) => {
      const now = paraNow(Number(one.dataset.id));
      if (!now || now.locked) return false;
      const want = rung === "indent"
        ? Math.min(INDENT_MAX_TW, now.indent + INDENT_STEP_TW)
        : Math.max(0, now.indent - INDENT_STEP_TW);
      return want !== now.indent;
    };
    // A box selection, or a native drag across paragraphs: move all of them.
    const many = (boxSel && boxSel.length > 1)
      ? boxSel.slice()
      : selectionLines().length > 1 ? selectionLines().map(p => p.el) : null;
    if (many) {
      // Computed lines (the PRICE rows, the {{#system}} rows, the NOTES bullets) have no para
      // record to move, and a locked contract clause refuses -- both are passed over rather than
      // pretended at, so a selection that mixes them indents what it can.
      const blocks = many.filter(one => one.classList.contains("tw-block") && canMove(one));
      const moved = blocks.filter(one => paraAction(one, rung));
      if (!moved.length) return;                 // nothing could move: let Tab do its normal job
      e.preventDefault();
      scheduleRepaginate();
      return;
    }
    const el = lineTarget(e);
    if (!el || !el.classList.contains("tw-block")) return;
    if (!canMove(el)) return;                    // locked, at the margin, or already at the max
    if (!paraAction(el, rung)) return;
    e.preventDefault();
    showFmtBar(el);                              // the indent buttons reflect where the line now is
  });

  docSurface.addEventListener("keydown", (e) => {
    const back = e.key === "Backspace", fwd = e.key === "Delete";
    if ((!back && !fwd) || e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
    const el = lineTarget(e);
    if (!el) return;
    const sel = selectionRange(el);
    if (!sel) return;
    // A selection means "delete these characters" and mid-line is the browser's job; both fall
    // through. What must NOT fall through is a collapsed caret at a line BOUNDARY, which is where
    // the browser would merge this paragraph into its neighbour.
    if (sel[0] !== sel[1]) return;
    const atStart = sel[0] === 0;
    const atEnd = sel[1] >= runsLength(editRuns(el));
    if (back && atStart && el.classList.contains("tw-block")) {
      const now = paraNow(Number(el.dataset.id));
      // The ladder: bullet first, then the indent, then stop. `paraAction` decides whether the
      // change is allowed and reports it; only a change consumes the keystroke.
      const rung = now && !now.locked ? (now.bullet ? "bullet" : (now.indent > 0 ? "outdent" : null)) : null;
      if (rung && paraAction(el, rung)) { e.preventDefault(); return; }
    }
    // NO MERGE, EVER, and this is the load-bearing line of the whole change. A .tw-block IS one
    // Word paragraph, identified by an id the backend's walk produced and applied by POSITION to a
    // pristine template at generate time. Merging two of them destroys an id, and every override
    // after it in the box lands on the wrong paragraph of the document the customer signs. While
    // each paragraph was its own editing host the browser could not do it; now that the box is the
    // host it can, so the keystroke is refused instead. (Refusing is also what the estimator
    // already sees today, so nothing he relies on changes.)
    if ((back && atStart) || (fwd && atEnd)) e.preventDefault();
  });

  docSurface.addEventListener("paste", (e) => {
    const line = lineTarget(e);
    const el = line && line.classList.contains("tw-block") ? line : null;
    if (!el) return;
    e.preventDefault();
    const dt = e.clipboardData;
    let ins = [];
    const html = dt ? dt.getData("text/html") : "";
    if (html) ins = runsFromHtml(html);
    if (!ins.length) {
      const plain = String((dt && dt.getData("text/plain")) || "").replace(/\r\n?/g, "\n");
      if (plain) ins = [{ text: plain, tok: null }];
    }
    if (!ins.length) return;
    const sel = selectionRange(el);
    if (!sel) return;
    const across = selectionLines();
    if (across.length > 1) {
      // Pasted over several paragraphs at once: the content lands in the first and the rest are
      // emptied, every element intact. See spliceLines for why a merge is not an option.
      spliceLines(across, ins);
      showFmtBar(el);
      return;
    }
    const merged = F.spliceRuns(editRuns(el), sel[0], sel[1], ins);
    renderRuns(el, merged);
    const caret = sel[0] + runsLength(ins);
    placeSelection(el, caret, caret);
    // Only claim "formatted" when the pasted content actually carries formatting; a plain-text
    // paste is an ordinary text edit and the text comparison already catches it.
    markEdited(el, ins.some(r => RUN_KEYS.some(k => r[k] !== undefined)));
    showFmtBar(el);
  });

  /** THE MERGE GUARD, for every edit that does not arrive as a keystroke.
   *
   *  Typing a character over a three-line selection, an IME commit, a drag-and-drop inside the
   *  box, a spell-check replacement, a context-menu Delete: none of those are visible to a keydown
   *  handler, and all of them would have the browser collapse the selected paragraphs into one
   *  element. See spliceLines for why that corrupts the customer's document. So the browser's own
   *  version is refused and the same edit is applied by hand, every paragraph left standing.
   *
   *  A COLLAPSED caret short-circuits immediately, which is the common case -- ordinary typing
   *  pays nothing for this. The only collapsed edits examined are the two that would merge a
   *  paragraph into its neighbour, and those are already refused on keydown; this is the same
   *  refusal for the routes that never touch the keyboard. */
  docSurface.addEventListener("beforeinput", (e) => {
    if (!editingBox(e.target)) return;
    const type = String(e.inputType || "");
    // An IME owns its range while composing; the commit lands as a separate event and is handled
    // there like any other insert.
    if (type === "insertCompositionText") return;
    const sel = typeof window !== "undefined" && window.getSelection ? window.getSelection() : null;
    if (!sel || !sel.rangeCount) return;
    const r = sel.getRangeAt(0);
    if (r.collapsed) {
      if (type !== "deleteContentBackward" && type !== "deleteContentForward") return;
      const el = lineAtSelection();
      if (!el) return;
      const one = selectionRange(el);
      if (!one) return;
      const total = runsLength(editRuns(el));
      if ((type === "deleteContentBackward" && one[0] === 0)
          || (type === "deleteContentForward" && one[1] >= total)) e.preventDefault();
      return;
    }
    // BOTH ENDS IN THE SAME LINE means the browser's own edit cannot cross a paragraph, so it is
    // left alone -- and, more importantly, left alone WITHOUT reading the selection first. Reading
    // it means inserting and removing the two markers and then re-placing the range, and doing
    // that inside `beforeinput` -- before the browser has applied the edit it is asking about --
    // moves the very range that edit is about to use. Two `closest()` calls answer the question
    // without touching anything.
    const startEl = r.startContainer && r.startContainer.nodeType === 1
      ? r.startContainer : (r.startContainer && r.startContainer.parentNode);
    const endEl = r.endContainer && r.endContainer.nodeType === 1
      ? r.endContainer : (r.endContainer && r.endContainer.parentNode);
    const oneLine = lineAt(startEl);
    if (oneLine && oneLine === lineAt(endEl)) return;
    let lines;
    try { lines = selectionLines(); } catch { lines = []; }
    if (lines.length <= 1) return;
    e.preventDefault();
    const data = e.data != null ? String(e.data)
                 : (e.dataTransfer ? String(e.dataTransfer.getData("text/plain") || "") : "");
    const ins = type.indexOf("delete") === 0 || !data ? [] : [{ text: data, tok: null }];
    spliceLines(lines, ins);
  });

  // ── Editable estimate-sourced fills: WORK systems ──────────────────────
  // systemPreviewEl is a stable element (its children are rewritten, but it
  // itself is never replaced), so one delegated listener survives every
  // rebuild. Each {{#system}} row is ONE whole editable line; an edit writes
  // that whole line as a display-only override into state.system_overrides
  // (dense, by option index). It never touches cell_values or pricing.
  let _sysOvTimer = null;
  /** Every {{#system}} row in the WORK box -> its display-only override.
   *
   *  Whole-container, because the box is one editing host: a Delete across three rows is a single
   *  `input` event, and a handler that only read the caret's own row would leave the other two
   *  edited on screen and unedited in the draft. Reading the DOM makes it idempotent, so running
   *  it twice for one keystroke -- once from the surface, once from the container listener a
   *  harness scenario drives -- costs nothing and changes nothing. */
  function syncSystemRows() {
    if (!systemPreviewEl || !systemPreviewEl.querySelectorAll) return;
    systemPreviewEl.querySelectorAll("[data-sys-line]").forEach(syncSystemRow);
    queueSysOvSave();
  }

  function queueSysOvSave() {
    if (_sysOvTimer) clearTimeout(_sysOvTimer);
    _sysOvTimer = setTimeout(() => { try { TW.setState({ system_overrides: state.system_overrides }); } catch {} }, 500);
  }

  function syncSystemRow(sp) {
    const i = Number(sp.dataset.sysIndex);
    const field = sp.dataset.sysLine;
    // The field whitelist, mirroring the backend's. An unrecognized key would be
    // persisted to the draft, shown back after a reload, and then dropped server-side —
    // positive confirmation of an edit the customer never receives.
    if (!Number.isInteger(i) || i < 0 || _SYS_ROW_LINE_FIELDS.indexOf(field) < 0) return;
    const ovs = Array.isArray(state.system_overrides) ? state.system_overrides : (state.system_overrides = []);
    while (ovs.length <= i) ovs.push({});          // keep dense — no sparse nulls in JSON
    if (!ovs[i] || typeof ovs[i] !== "object") ovs[i] = {};
    // Spaces preserved, not trimmed. Kyle, 2026-08-20: editing must reflect 1 to 1 in the
    // customer's copy. The template writes a WORK row's label and value with real spaces
    // between them, so a space the estimator adds or removes anywhere in the line is a
    // real edit. Emptiness is tested with .trim(), so a blank line still reverts to the
    // computed value without mangling what gets stored.
    const v = serializeBlock(sp);
    if (!v.trim() || v === (sp.dataset.computed || "")) delete ovs[i][field];   // empty / back-to-computed -> revert
    else ovs[i][field] = v;
  }

  systemPreviewEl.addEventListener("input", (e) => {
    const sp = e.target && e.target.closest ? e.target.closest("[data-sys-line]") : null;
    if (sp) { syncSystemRow(sp); queueSysOvSave(); return; }
    syncSystemRows();
  });

  // ── Editable estimate-sourced fills: NOTES bullets ─────────────────────
  // Two-way bound to the sidebar #notes-text textarea (single source of
  // truth). Writing textarea.value programmatically fires NO form 'input'
  // event, so this never loops back through refreshDocumentFills.
  let _notesOvTimer = null;
  /** The NOTES bullets -> the sidebar textarea, which is their single source of truth.
   *
   *  Already whole-container (it re-reads every bullet), which is exactly the shape the other two
   *  families needed; named so the surface-level handler can call it. */
  function syncNotesFromDom() {
    const ta = document.getElementById("notes-text");
    if (!ta) return;
    const lines = [];
    notesPreviewEl.querySelectorAll("[data-note-index]").forEach(p =>
      serializeBlock(p).split("\n").forEach(s => lines.push(s.trim())));
    // Preserve blank lines (spacing). Collapse only 3+ consecutive blanks to 2
    // (guards against contenteditable "bogus <br>" doubling during editing) and
    // trim a trailing blank so blanks can't creep across edits.
    while (lines.length && lines[lines.length - 1] === "") lines.pop();
    const kept = [];
    let run = 0;
    for (const s of lines) { if (s === "") { if (++run > 2) continue; } else run = 0; kept.push(s); }
    ta.value = kept.join("\n");
    // Re-fit the font as bullets are typed -- THE NOTES BOX, and nothing else on the page.
    //
    // This used to call fitNotesBox(), which loops every `.tw-txbx` and hands each one to fitTxbx
    // -- and fitTxbx resets fontSize, transform, maxHeight, overflow and zIndex and takes
    // `tw-notes-open` off. So one character typed in a notes bullet re-ran the shrink ladder on
    // WORK and PRICE and folded shut any box the estimator had expanded to read (Hanz,
    // 2026-08-26, on the editor being clunky between sections). The notes box is the only one
    // whose content just changed, so it is the only one re-measured. fitTxbx returns immediately
    // when handed null, which is the honest answer before the preview is mounted into a box.
    // Only the box's own font-size changes (the bullets are never rebuilt), so the caret survives.
    try { fitTxbx(notesPreviewEl.closest(".tw-txbx")); } catch {}
    if (_notesOvTimer) clearTimeout(_notesOvTimer);
    _notesOvTimer = setTimeout(() => { try { TW.setState({ notes_text: ta.value }); } catch {} }, 300);
  }
  notesPreviewEl.addEventListener("input", syncNotesFromDom);

  // ── Editable PRICE-line DISPLAY overrides (state.price_overrides) ───────
  // Delegated on the STABLE containers: #price-lines-block (option + manual
  // line islands) and #base-bid-row (the single_bid base amount / tax phrase).
  // An emptied / back-to-computed island reverts; otherwise it's stored. These
  // are display-only — the .xlsx, totals, and the math rows (Total / Material
  // Sales Tax / Remodel) are never touched (see backend _sanitize_price_overrides).
  let _povTimer = null;
  function _ensurePov() {
    let pov = state.price_overrides;
    if (!pov || typeof pov !== "object" || Array.isArray(pov)) pov = state.price_overrides = {};
    if (!pov.options || typeof pov.options !== "object" || Array.isArray(pov.options)) pov.options = {};
    if (!Array.isArray(pov.manual)) pov.manual = [];
    if (!pov.single_bid || typeof pov.single_bid !== "object" || Array.isArray(pov.single_bid)) pov.single_bid = {};
    if (!pov.rows || typeof pov.rows !== "object" || Array.isArray(pov.rows)) pov.rows = {};
    if (!pov.combo || typeof pov.combo !== "object" || Array.isArray(pov.combo)) pov.combo = {};
    if (!pov.alternate || typeof pov.alternate !== "object" || Array.isArray(pov.alternate)) pov.alternate = {};
    if (!pov.lines || typeof pov.lines !== "object" || Array.isArray(pov.lines)) pov.lines = {};
    return pov;
  }
  /** Every whole-line PRICE row in a container -> state.price_overrides.lines.
   *
   *  The legacy per-field islands are deliberately not swept: the current UI does not emit them,
   *  and they key off the event target rather than the DOM, so there is nothing to re-read. */
  function syncPriceLinesIn(root) {
    if (!root || !root.querySelectorAll) return;
    let touched = false;
    root.querySelectorAll("[data-po-kind=\"line\"][data-po-linekey]").forEach(lineNode => {
      const key = lineNode.dataset.poLinekey;
      if (!key) return;
      const v = serializeBlock(lineNode);
      const pov = _ensurePov();
      if (v.trim() === "" || v === (lineNode.dataset.computed || "")) delete pov.lines[key];
      else pov.lines[key] = v;
      touched = true;
    });
    if (touched) queuePovSave();
  }

  function queuePovSave() {
    if (_povTimer) clearTimeout(_povTimer);
    _povTimer = setTimeout(() => { try { TW.setState({ price_overrides: state.price_overrides }); } catch {} }, 500);
  }

  function _handlePoInput(e) {
    // WHOLE-LINE edit: the whole <p> is contenteditable (base / tax / total /
    // combo / option / manual / alternate / headings). Store the full line text
    // keyed by data-po-linekey, EXACTLY AS TYPED — no trim, no collapse, nothing.
    //
    // It used to collapse every newline to a single space, on the reasoning that "a
    // price line is one line". Hanz, 2026-08-21: "if they enter two blank lines then it
    // should also be 2 blank lines. Im tellign you whatever the update is in the
    // proposal tool it should be one to one, spacing, font size, indentation ETC."
    // The writer was never the obstacle — posting a newline straight to /api/generate
    // has always produced a real <w:br/> — so this was the editor overruling the
    // estimator about his own document. It no longer does.
    //
    // A line that now overflows its box is handled the way every other overflow is:
    // fitTxbx shrinks, then clips and says so, and "Fit to text" offers the room when
    // there is any. An honest warning beats silently flattening what he typed.
    const lineNode = e.target && e.target.closest ? e.target.closest('[data-po-kind="line"][data-po-linekey]') : null;
    if (lineNode) {
      const key = lineNode.dataset.poLinekey;
      if (!key) return;
      const v = serializeBlock(lineNode);
      const pov = _ensurePov();
      if (v.trim() === "" || v === (lineNode.dataset.computed || "")) delete pov.lines[key];
      else pov.lines[key] = v;
      queuePovSave();
      return;
    }
    // Legacy per-field islands (retained for back-compat; not emitted by the
    // current whole-line UI).
    const sp = e.target && e.target.closest ? e.target.closest("[data-po-field]") : null;
    if (!sp) return;
    const kind = sp.dataset.poKind, field = sp.dataset.poField;
    if (!kind || !field) return;
    // SPACES ARE PRESERVED, exactly as the whole-line branch above preserves them.
    // Kyle, 2026-08-20: "everything in the Proposals when editing should refelect 1 to 1
    // in the customer side." This used to .trim(), and an option line renders as three
    // adjacent islands - amount, desc, tax_phrase - so the seam between them is exactly
    // where a person adds a space, and exactly what got eaten. The Base Bid line kept its
    // space because it is a whole-line edit; the Options rows lost theirs because they are
    // islands. Newlines still collapse to one space: a price line is one line.
    // `revert` tests .trim() rather than the raw value, so a whitespace-only edit still
    // means 'put the computed value back' without mangling what gets stored.
    const v = serializeBlock(sp);
    const revert = !v.trim() || v === (sp.dataset.computed || "");   // empty / back-to-computed
    const pov = _ensurePov();
    if (kind === "option") {
      const id = sp.dataset.poId || "";
      if (!id) return;
      if (revert) {
        if (pov.options[id]) { delete pov.options[id][field]; if (!Object.keys(pov.options[id]).length) delete pov.options[id]; }
      } else { (pov.options[id] = pov.options[id] || {})[field] = v; }
    } else if (kind === "manual") {
      const idx = Number(sp.dataset.poIndex);
      if (!Number.isInteger(idx) || idx < 0) return;
      while (pov.manual.length <= idx) pov.manual.push({});    // keep dense — index-preserving
      if (!pov.manual[idx] || typeof pov.manual[idx] !== "object") pov.manual[idx] = {};
      if (revert) delete pov.manual[idx][field]; else pov.manual[idx][field] = v;
    } else if (kind === "single_bid") {
      if (revert) delete pov.single_bid[field]; else pov.single_bid[field] = v;
    } else if (kind === "row") {
      const rk = sp.dataset.poRow || "";
      if (!["sales_tax", "remodel", "total"].includes(rk)) return;
      if (revert) { if (pov.rows[rk]) { delete pov.rows[rk][field]; if (!Object.keys(pov.rows[rk]).length) delete pov.rows[rk]; } }
      else { (pov.rows[rk] = pov.rows[rk] || {})[field] = v; }
    } else if (kind === "combo") {
      const ck = sp.dataset.poKey || "";
      if (!ck) return;
      if (revert) { if (pov.combo[ck]) { delete pov.combo[ck][field]; if (!Object.keys(pov.combo[ck]).length) delete pov.combo[ck]; } }
      else { (pov.combo[ck] = pov.combo[ck] || {})[field] = v; }
    } else if (kind === "alt") {
      if (revert) delete pov.alternate[field]; else pov.alternate[field] = v;
    } else { return; }
    if (_povTimer) clearTimeout(_povTimer);
    _povTimer = setTimeout(() => { try { TW.setState({ price_overrides: state.price_overrides }); } catch {} }, 500);
  }
  // Every whole-line PRICE element: the base bid and its option/manual lines, the tax rows, the
  // Base Bid / Options headings, the combo breakout, the per-room block and the ALTERNATE SYSTEM
  // block. Named in one place so nothing can be wired half-way.
  const PRICE_PREVIEW_IDS = ["price-lines-block", "base-bid-row", "sales-tax-row",
    "remodel-tax-row", "total-row", "base-bid-heading", "options-heading",
    "combo-price-block", "rooms-block", "alternate-block"];
  const pricePreviewEls = () => PRICE_PREVIEW_IDS
    .map(id => document.getElementById(id)).filter(el => el);
  // INPUT ONLY. There is no per-element `focusout` here any more, and its absence is the fix.
  //
  // Three of these used to normalise on their OWN focusout -- and each of those handlers called
  // refreshPriceDisplay(), whose paintLine rewrites `textContent` on every price row that is not
  // holding the caret. While each row was its own editing host, clicking from one price line to
  // the next really did move focus between two hosts, so moving the caret between two lines OF
  // THE SAME BOX re-rendered the others under the estimator (Hanz, 2026-08-26: "Editing from one
  // text box to another is a bit clunky"). The rows no longer declare a host, so focus stays on
  // the box and there is nothing to hear -- the box-scoped `focusout` on #doc-surface normalises
  // them when the caret leaves the BOX, which is the only moment a re-render is safe.
  //
  // The `input` listeners stay exactly as they were: these are the channels that put an edit in
  // the right place in the customer's document. They now fire only for the synthesized events
  // clearBoxLine / the Enter handler dispatch AT a line; a real keystroke arrives at the box and
  // is swept by syncPriceLinesIn there.
  pricePreviewEls().forEach(el => el.addEventListener("input", _handlePoInput));

  // Pricing options is a FLOATING, MOVABLE widget: drag its header to reposition
  // it (so it never has to sit over the document or the top controls). One-time
  // init — the panel element is stable; its .op-drag header is rebuilt on each
  // render, so pointerdown is delegated. Position persists in localStorage.
  (function initOptionsPanelDrag() {
    const panel = document.getElementById("options-panel");
    if (!panel) return;
    try {
      const p = JSON.parse(localStorage.getItem("tw_opts_pos") || "null");
      if (p && Number.isFinite(p.left) && Number.isFinite(p.top)) {
        panel.style.left = p.left + "px"; panel.style.top = p.top + "px"; panel.style.right = "auto";
      }
    } catch {}
    let dragging = false, sx = 0, sy = 0, ox = 0, oy = 0;
    panel.addEventListener("pointerdown", (e) => {
      const h = e.target.closest && e.target.closest(".op-drag");
      if (!h || !panel.contains(h)) return;
      const r = panel.getBoundingClientRect();
      dragging = true; ox = r.left; oy = r.top; sx = e.clientX; sy = e.clientY;
      panel.style.left = ox + "px"; panel.style.top = oy + "px"; panel.style.right = "auto";
      panel.classList.add("op-dragging");
      try { h.setPointerCapture(e.pointerId); } catch {}
      e.preventDefault();
    });
    panel.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      const w = panel.offsetWidth || 240;
      let nl = ox + (e.clientX - sx), nt = oy + (e.clientY - sy);
      nl = Math.max(4, Math.min(nl, window.innerWidth - w - 4));
      nt = Math.max(4, Math.min(nt, window.innerHeight - 40));      // keep the drag header on-screen
      panel.style.left = nl + "px"; panel.style.top = nt + "px";
    });
    const end = () => {
      if (!dragging) return;
      dragging = false; panel.classList.remove("op-dragging");
      try {
        localStorage.setItem("tw_opts_pos", JSON.stringify({
          left: parseFloat(panel.style.left) || 0, top: parseFloat(panel.style.top) || 0 }));
      } catch {}
    };
    panel.addEventListener("pointerup", end);
    panel.addEventListener("pointercancel", end);
  })();

  initDocumentEditor();

  // Recompute base + options from the per-tab snapshot first (no-op for older
  // drafts without it), so the price display below reflects the current base.
  rebuildPricing();

  // Lump sum = the estimate sheet's own TOTAL LUMP SUM (D88/D82, snapshotted
  // into state.proposal_lump_sum when leaving the Estimate screen). That cell
  // already reflects EVERYTHING the estimator entered in the grid — crew/days,
  // demo, and hand-typed markup overrides like a -17% hard-bid discount — so
  // the proposal price always matches the sheet the estimator is looking at.
  // The Computed Bid engine is the FALLBACK only (e.g. older drafts saved
  // before the sheet total computed reliably in the browser).
  (() => {
    const cb = state.computed_bid;
    let lump = null;
    if (typeof state.proposal_lump_sum === "number" && state.proposal_lump_sum > 0) {
      lump = state.proposal_lump_sum;              // sheet's Total Lump Sum (D88/D82)
    } else if (cb && cb.full_bid && typeof cb.full_bid.total_base_bid === "number") {
      lump = cb.full_bid.total_base_bid;           // engine Total Base Bid
    } else if (cb && typeof cb.grand_total === "number") {
      lump = cb.grand_total;                       // material-only mode
    } else {
      lump = 0;
    }
    // Stash into a hidden "tb-total" so refreshPriceDisplay finds it
    let el = document.querySelector("#tb-total");
    if (!el) {
      el = document.createElement("span");
      el.id = "tb-total";
      el.style.display = "none";
      document.body.appendChild(el);
    }
    el.textContent = fmtUSD(lump);
    refreshPriceDisplay();
  })();

  // Default the bid date to today if intake didn't carry one through.
  // Use the local timezone so the displayed date matches what the user
  // sees in their calendar (UTC-based ISO strings drift by ±1 day).
  const bidInput = form.querySelector("[name='bid_date']");
  const visitInput = form.querySelector("[name='site_visit_date_display']");
  if (bidInput && !bidInput.value) {
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, "0");
    const d = String(now.getDate()).padStart(2, "0");
    bidInput.value = `${y}-${m}-${d}`;
    state.bid_date = bidInput.value;
  }
  if (bidInput && bidInput.value && !visitInput.value) {
    const d = new Date(bidInput.value + "T00:00:00");
    if (!isNaN(d)) visitInput.value = `${d.getMonth()+1}/${d.getDate()}/${String(d.getFullYear()).slice(-2)}`;
  }
  bidInput?.addEventListener("change", () => {
    if (bidInput.value && !visitInput.value) {
      const d = new Date(bidInput.value);
      if (!isNaN(d)) visitInput.value = `${d.getMonth()+1}/${d.getDate()}/${String(d.getFullYear()).slice(-2)}`;
    }
  });

  // Recalc the price preview AND the document's highlighted values on any
  // sidebar field change (hand-edited paragraphs are left alone).
  form.addEventListener("input", () => { refreshPriceDisplay(); refreshDocumentFills(); });

  // Persist EVERY edit as it's typed (debounced). Previously the narrative
  // textareas (Scope/Schedule/Exclusions) + cove height were committed to state
  // only on Back/Submit — so any mid-flow re-hydration (draft-sync reload, manual
  // refresh, Back/Forward) re-ran init, writeForm restored the blank value, and
  // the PROPOSAL_DEFAULTS loop re-seated the boilerplate. That stale default then
  // got submitted instead of the estimator's edit — Kyle's "my updates on the
  // proposal tab aren't carrying over to the final proposal". setState merges, so
  // this only overwrites the scalar form fields and leaves rooms/price_lines/etc.
  // intact; it also schedules the debounced server save so the draft round-trips.
  let _persistTimer = null;
  form.addEventListener("input", () => {
    if (_persistTimer) clearTimeout(_persistTimer);
    _persistTimer = setTimeout(() => {
      try {
        // The tax treatment lives in this form and changes the PRICE block's own wording and
        // layout (base_tax_phrase, and which of the three lines the backend fills), so it has to
        // reach the document payload too — same reason as a base flip.
        const _pp = syncPayloadPricing();
        TW.setState(Object.assign(TW.readForm(form), _pp ? { proposal_payload: _pp } : {}));
      } catch {}
    }, 300);
  });

  document.getElementById("back-btn").addEventListener("click", () => {
    TW.setState(TW.readForm(form));
    window.location.assign(TW.withDraft("/estimate-review.html"));
  });

  // The visible Continue button sits in the ribbon, outside the intentionally
  // hidden fields form. Wire it directly instead of relying on the browser's
  // cross-form submit behavior, which can be skipped when the hidden template
  // is still mounting. Keep the form listener too for keyboard submission.
  async function continueToDone(e) {
    e?.preventDefault();
    const btn = document.getElementById("generate-btn");
    btn.disabled = true;
    btn.textContent = "Generating…";

    const mergedValues = Object.assign({}, state, TW.readForm(form));
    const tokenValues = computeTokenValues(mergedValues);
    const lumpSumText = document.querySelector("#tb-total")?.textContent || "$0.00";
    const _fb = (state.computed_bid && state.computed_bid.full_bid) || {};
    const remodelTax = Number((state.proposal_remodel_tax != null ? state.proposal_remodel_tax : _fb.remodel_tax) || 0);

    // Document edits: every paragraph whose text differs from its pristine
    // rendering, as {id, text} against the pristine template's ids. Persisted
    // too so re-opening this screen restores the edits.
    const paragraphOverrides = collectOverrides();
    // Boxes the estimator dragged or resized, as {id: {x_pt?, y_pt?, w_pt?, h_pt?}}.
    const boxOverridesOut = collectBoxOverrides();

    // We no longer call /api/generate here. The actual file generation
    // moved to the Done page so the user has one final review screen before
    // anything customer-facing happens. Stash the payload that Done.html
    // will POST when the user clicks Generate.
    // Also file them under this template in the per-template store, so hitting
    // Continue counts as a save. Otherwise an edit made inside the last 800ms —
    // the debounce window — would be preserved for generation but lost from the
    // store, and would vanish on the next template switch.
    const _allOverrides = mergeOverrideEntry(
      liveKey("paragraph_overrides_all"), effectiveWorkType(), state.audience || "Direct",
      templateVersion, paragraphOverrides);
    const _allBoxOverrides = mergeOverrideEntry(
      liveKey("box_overrides_all"), effectiveWorkType(), state.audience || "Direct",
      templateVersion, boxOverridesOut);

    TW.setState({
      ...mergedValues,
      paragraph_overrides_all: _allOverrides,
      paragraph_overrides: paragraphOverrides,
      paragraph_overrides_meta: {
        template_version: templateVersion,
        work_type: effectiveWorkType(),
        audience: state.audience || "Direct",
      },
      box_overrides_all: _allBoxOverrides,
      box_overrides: boxOverridesOut,
      box_overrides_meta: {
        template_version: templateVersion,
        work_type: effectiveWorkType(),
        audience: state.audience || "Direct",
      },
      proposal_payload: {
        work_type: effectiveWorkType(),
        audience:  state.audience  || "Direct",
        // The template version the paragraph_overrides ids were captured against.
        // The backend drops the overrides if this no longer matches the current
        // template (annotation shifts editable-block ids) — see api_generate.
        template_version: templateVersion,
        values:    { ...mergedValues, ...tokenValues },
        cell_values: state.cell_values || {},
        // Custom material lines (Super Stick / edge-case adds) -> Epoxy spare rows
        extras: Array.isArray(state.extras) ? state.extras : [],
        // Structured proposal price lines (options / unit prices) -> {{#price_line}} rows
        price_lines: Array.isArray(state.price_lines) ? state.price_lines : [],
        // Combo per-option breakout (Option 1 Epoxy / Option 2 Polish, each w/ tax +
        // total) -> leads the PRICE section, suppresses the combined single-bid line.
        // Display overrides pre-applied to the line strings (see comboLinesForPayload).
        combo_options: comboLinesForPayload(),
        // Authoritative bid from the 5.7-recipe engine — the generate
        // response echoes this so nothing downstream shows a stale total.
        computed_bid: state.computed_bid || null,
        // Recommended alternate system (2nd bid) -> {{#alternate}} block + 2nd estimate tab
        alternate_computed_bid: state.alternate_computed_bid || null,
        alternate_label: (state.alternate && state.alternate.label) || "",
        // Conditional Kansas Remodel Tax line — only when remodel tax applies.
        remodel: remodelTax > 0 ? [{ amount_formatted: fmtUSD(remodelTax) }] : [],
        // Optional per-sheet priced options -> {{#room}} block (empty unless the
        // estimate side opts in; copy/rename itself is a pure sheet operation).
        rooms: Array.isArray(state.rooms) ? state.rooms : [],
        // Duplicated worksheets + display labels + drag order -> the downloaded
        // .xlsx mirrors the user's copies, tab renames, and tab order.
        tab_copies: Array.isArray(state.tab_copies) ? state.tab_copies : [],
        tab_labels: (state.tab_labels && typeof state.tab_labels === "object") ? state.tab_labels : {},
        tab_order: Array.isArray(state.tab_order) ? state.tab_order : [],
        // Structural edits (insert/delete rows & columns) -> replayed onto the
        // downloaded .xlsx with formula/merge/lock translation.
        tab_structs: Array.isArray(state.tab_structs) ? state.tab_structs : [],
        // Per-sheet cell-lock overrides ("Lock cell" toolbar) -> merged over the
        // default rate/markup/tax locks in the generated .xlsx sheet protection.
        lock_overrides: (state.lock_overrides && typeof state.lock_overrides === "object") ? state.lock_overrides : {},
        // Editable NOTES (one bullet per line); empty -> backend uses the standard list.
        notes: String(mergedValues.notes_text || "").replace(/\n+$/, "").split("\n").map(s => s.trim()),
        // Document-editor edits -> proposal_writer paragraph overrides,
        // applied to the pristine template BEFORE block expansion (id-safe).
        paragraph_overrides: paragraphOverrides,
        // Boxes the estimator dragged or resized -> proposal_writer._apply_box_overrides, which
        // writes size and anchor offset into BOTH the DrawingML anchor and its VML fallback.
        // Guarded by the same template_version as the paragraph overrides above: a box id is a
        // position in the same walk over the same file.
        box_overrides: boxOverridesOut,
        // Doc-editor per-option DISPLAY overrides for the WORK {{#system}}
        // rows (epoxy only) — edit the shown system name/texture/area without
        // touching cell_values or the price.
        system_overrides: Array.isArray(state.system_overrides) ? state.system_overrides : [],
        // WORK {{#system}} picks resolved from the BASE tab's sheet cells (name +
        // SF + cove LF per system) so the docx Area matches the on-screen preview
        // even when the base is a copy tab. Empty -> backend keeps its legacy
        // Epoxy!-cell reads (stale drafts / fallback path).
        sheet_systems: (sheetSystems() || []).filter(s => (s.name && !s.name.includes("Options")) || s.sf > 0 || s.lf > 0),
        // Doc-editor per-line DISPLAY overrides for the PRICE section (base bid
        // amount / tax phrase, option + manual line label/amount). Display-only —
        // never affects pricing or the .xlsx (see backend _sanitize_price_overrides).
        price_overrides: (state.price_overrides && typeof state.price_overrides === "object") ? state.price_overrides : {},
      },
      // Also persist the lump sum string so Done can show it without
      // re-reading from HF (which lives on the Estimate Review page).
      lump_sum_display: lumpSumText,
    });
    window.location.assign(TW.withDraft("/done.html"));
  }

  form.addEventListener("submit", continueToDone);

  // The "4 · Files" step pill was a bare <a href="/done.html">, so it reached the Done page
  // WITHOUT ever running this handler — and this handler is the only thing that rebuilds the
  // document payload. Flip the base bid, click the pill, press Re-send, and the customer received a
  // PDF built from the state as of the previous Continue. syncPayloadPricing now keeps the PRICING
  // slice honest on its own, but the narrative half (scope, schedule, exclusions, notes) is only
  // rebuilt here, so the pill has to come through the same door as the button.
  const _filesPill = document.querySelector('a.step[href="/done.html"]');
  if (_filesPill) _filesPill.addEventListener("click", (e) => { e.preventDefault(); continueToDone(e); });
