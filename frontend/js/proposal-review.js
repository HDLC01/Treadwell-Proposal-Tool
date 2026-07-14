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
  // Every default value for `field` across all work-types in `audience` — used to
  // recognise (and only then re-seed) untouched machine boilerplate.
  function audienceFieldDefaults(audience, field) {
    const cat = String(audience).toUpperCase() === "GC" ? NARRATIVE_DEFAULTS.GC : NARRATIVE_DEFAULTS.Direct;
    return new Set(Object.values(cat).map(row => row[field]));
  }

  // Seed the narrative fields: fill blanks with the current audience's default, AND
  // if a field still holds a verbatim default from the OTHER audience (untouched
  // boilerplate), re-seed it for the current audience — so a mid-draft Direct⇄GC
  // switch swaps the machine text but any hand edit (even 1 char) survives.
  (function seedNarrative() {
    const cur = narrativeDefaults(_audience, _wt);
    const otherAudience = String(_audience).toUpperCase() === "GC" ? "Direct" : "GC";
    for (const nm of ["scope_notes", "schedule_notes", "exclusions"]) {
      const el = form.querySelector(`[name="${nm}"]`);
      if (!el) continue;
      const val = String(el.value || "");
      if (!val.trim()) { el.value = cur[nm]; continue; }
      if (audienceFieldDefaults(otherAudience, nm).has(val)) el.value = cur[nm];
    }
  })();

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

  (function prefillNotes() {
    const ta = document.getElementById("notes-text");
    if (!ta) return;
    const applyAndPreview = (text) => { ta.value = text; syncPhaseNote(); try { renderNotesPreview(); } catch {} };
    if (Array.isArray(state.notes) && state.notes.length) { applyAndPreview(state.notes.join("\n")); return; }
    if (String(ta.value || "").trim()) { syncPhaseNote(); return; }
    fetch("/api/default-notes?work_type=" + encodeURIComponent(_wt), { headers: TW.authHeaders() })
      .then(r => r.json())
      .then(j => { if (!String(ta.value || "").trim() && Array.isArray(j.notes)) applyAndPreview(j.notes.join("\n")); })
      .catch(() => {});
  })();

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
  (function adaptToWorkType() {
    const wt = (state.work_type || "epoxy").toLowerCase();
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
  })();

  // Texture is a fixed dropdown (epoxy/combo only — polish hides the row above).
  (function buildTextureControl() {
    const _twt = (state.work_type || "epoxy").toLowerCase();
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
  })();

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

  document.getElementById("doc-name").textContent =
    (state.project_name || "Untitled") + " - " +
    (state.work_type || "Epoxy").charAt(0).toUpperCase() +
    (state.work_type || "Epoxy").slice(1).toLowerCase() + " Proposal.docx";

  // Format helpers
  const fmtUSD = (n) => "$" + Number(n || 0).toLocaleString(undefined,
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtSF = (n) => "~" + Number(n || 0).toLocaleString() + " sf";
  // Like fmtUSD but strips a trailing ".00" so preview PRICE amounts byte-match
  // the backend's _fmt_usd (e.g. "$36,763" not "$36,763.00"); fractional cents
  // keep their decimals ("$36,763.50").
  const fmtUSDdoc = (n) => { const s = fmtUSD(n); return s.endsWith(".00") ? s.slice(0, -3) : s; };

  // ─── Editable PRICE-line DISPLAY overrides (state.price_overrides) ──────
  // The base bid line, each priced option line, and each manual price line
  // render their amount + label as editable islands. An edit is stored as a
  // DISPLAY override (never touches cell_values / pricing — see backend
  // _sanitize_price_overrides); an emptied / back-to-computed island reverts.
  // Shape mirrors the backend: { options:{<id>:{label?,amount?}},
  // manual:[{label?,amount?}...], single_bid:{amount?,tax_phrase?} }.
  function poOverride(kind, key) {
    const pov = (state.price_overrides && typeof state.price_overrides === "object") ? state.price_overrides : null;
    if (!pov) return null;
    if (kind === "option")     return (pov.options && typeof pov.options === "object") ? pov.options[key] : null;
    if (kind === "manual")     return Array.isArray(pov.manual) ? pov.manual[key] : null;
    if (kind === "single_bid") return (pov.single_bid && typeof pov.single_bid === "object") ? pov.single_bid : null;
    return null;
  }
  // Current shown value for an override field: the saved override text if present
  // and non-blank, else the computed value (same resolution as renderSystemPreview).
  function poValue(kind, key, field, computed) {
    const ov = poOverride(kind, key);
    return (ov && typeof ov[field] === "string" && ov[field].trim()) ? ov[field] : computed;
  }
  // A contenteditable .tw-fill-edit island for a PRICE line's amount/label. The
  // data-po-* attrs carry the addressing the delegated input handler uses;
  // data-computed is the engine value an emptied island reverts to (see poValue).
  function poIsland(kind, key, field, computed, opts) {
    const e = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
      c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const tag = (opts && opts.strong) ? "strong" : "span";
    const keyAttr = kind === "option" ? ` data-po-id="${e(String(key))}"`
                  : kind === "manual" ? ` data-po-index="${key}"` : "";
    return `<${tag} class="tw-fill tw-fill-edit" contenteditable="true" spellcheck="false"` +
           ` data-po-kind="${kind}"${keyAttr} data-po-field="${field}"` +
           ` data-computed="${e(computed)}">${e(poValue(kind, key, field, computed))}</${tag}>`;
  }

  // Recompute the base bid + priced options from the per-tab totals snapshotted on
  // the Estimate screen (state.priced_tabs). This lets the base-bid picker + the
  // per-option total/deduct toggles work HERE too, without the sheet engine. It
  // MIRRORS estimate-review.js:snapshotLumpSumsToState — keep the two in sync.
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
      !(!state.base_tab_id && wt === "combo" && t.kind === "base"));
    const shown = optionTabs.map(t => mkRoom(t, false)).filter(o => o.bid.total > 0);
    state.rooms = (shown.length && baseTab) ? [mkRoom(baseTab, true), ...shown] : [];
    const el = document.querySelector("#tb-total");
    if (el) el.textContent = fmtUSD(shownBase);
    TW.setState({ rooms: state.rooms, base_tab_id: state.base_tab_id, tab_opts: state.tab_opts,
      proposal_lump_sum: shownBase, proposal_sales_tax: salesTax, proposal_remodel_tax: remodelTax });
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
    const pushSys = (sys, noun) => {
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
        lines.push({ amount_formatted: fmtUSD(flooring), label: `${optLabel}: ${noun} as described above` });
        if (salesTax > 0) lines.push({ amount_formatted: fmtUSD(salesTax), label: "Material Sales Tax" });
        if (remodel > 0) lines.push({ amount_formatted: fmtUSD(remodel), label: "Kansas Remodel Tax" });
      } else if (exempt) {
        // Tax exempt: the full total carries the "(tax exempt)" phrase — no sales
        // tax is baked in to strip out. Remodel line only if the snapshot actually
        // has one (normally zero on an exempt job).
        lines.push({ amount_formatted: fmtUSD(total), label: `${optLabel}: ${noun} as described above (tax exempt)` });
        if (remodel > 0) lines.push({ amount_formatted: fmtUSD(remodel), label: "Kansas Remodel Tax" });
      } else {
        // Included (default): one all-in flooring line + a separate remodel line
        // when it applies — this is the pre-existing combo wording.
        const flooring = total - remodel;
        lines.push({ amount_formatted: fmtUSD(flooring),
          label: `${optLabel}: ${noun} as described above (material sales tax INCLUDED)` });
        if (remodel > 0) lines.push({ amount_formatted: fmtUSD(remodel), label: "Kansas Remodel Tax" });
      }
      lines.push({ amount_formatted: fmtUSD(total), label: "Total" });
    };
    pushSys(eB, "Epoxy flooring");
    pushSys(pB, "Polished Concrete flooring");
    return lines;
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
    const wt = (state.work_type || "epoxy").toLowerCase();
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
    const phraseEl   = document.getElementById("base-tax-phrase-display");
    const comboBlock = document.getElementById("combo-price-block");
    const baseBidRow = document.getElementById("base-bid-row");
    const baseBidHeading = document.getElementById("base-bid-heading");
    const comboLines = comboSystemLines();

    if (comboLines.length && comboBlock) {
      // Combo: show Option 1 (Epoxy) + Option 2 (Polish), each with its own
      // flooring / tax line(s) / Total; hide the single combined base line AND
      // the static "Base Bid" heading above it — the Direct combo template keeps
      // that heading INSIDE {{#single_bid}}, so a generated combo doc starts
      // straight at "$X – Option 1: …" with no heading at all.
      const escP = (s) => String(s == null ? "" : s).replace(/[&<>"]/g,
        c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
      comboBlock.style.display = "";
      comboBlock.innerHTML = comboLines.map(l =>
        `<p class="tw-li" style="margin:0 0 2pt;"><strong class="tw-fill">${escP(l.amount_formatted)}</strong> – ${escP(l.label)}</p>`).join("");
      if (baseBidHeading) baseBidHeading.style.display = "none";
      if (baseBidRow) baseBidRow.style.display = "none";
      if (salesRow)   salesRow.style.display = "none";
      if (remodelRow) remodelRow.style.display = "none";
      if (totalRow)   totalRow.style.display = "none";
    } else {
      if (comboBlock) comboBlock.style.display = "none";
      if (baseBidHeading) baseBidHeading.style.display = "";
      if (baseBidRow) baseBidRow.style.display = "";
      // The base amount + tax phrase are editable override islands. Don't repaint
      // them while the caret is inside #base-bid-row (it would be destroyed) —
      // self-heals on focusout (which re-runs refreshPriceDisplay). The Total /
      // Material Sales Tax / Remodel rows stay engine-owned (plain, read-only).
      const editingBase = focusInside(baseBidRow);
      const baseDisp = document.getElementById("base-bid-display");
      if (broken) {
        if (!editingBase) {
          // Base line keeps cents (fmtUSD): the docx fills it from
          // base_bid_formatted / total_formatted, both produced by fmtUSD (.00),
          // NOT through _fmt_usd. Only the option/manual lines (which DO go
          // through _fmt_usd) use fmtUSDdoc's trailing-.00 strip.
          const computedBase = fmtUSD(baseBid);
          if (baseDisp) { baseDisp.dataset.computed = computedBase; baseDisp.textContent = poValue("single_bid", null, "amount", computedBase); }
          if (phraseEl) { phraseEl.dataset.computed = ""; phraseEl.textContent = poValue("single_bid", null, "tax_phrase", ""); }
        }
        document.getElementById("sales-tax-display").textContent = fmtUSD(salesTax);
        if (salesRow)   salesRow.style.display = "";
        if (remodelRow) remodelRow.style.display = remodelTax > 0 ? "" : "none";
        document.getElementById("tax-amount-display").textContent = fmtUSD(remodelTax);
        if (totalRow)   totalRow.style.display = "";
        document.getElementById("total-display").textContent = fmtUSD(lumpSumN);
      } else {
        const computedPhrase = exempt ? "(tax exempt)"
          : remodelTax > 0 ? "(Remodel Tax AND material sales tax INCLUDED)"
          : "(material sales tax INCLUDED)";
        if (!editingBase) {
          // Base line keeps cents (fmtUSD) to match the docx (total_formatted).
          const computedBase = fmtUSD(lumpSumN);
          if (baseDisp) { baseDisp.dataset.computed = computedBase; baseDisp.textContent = poValue("single_bid", null, "amount", computedBase); }
          if (phraseEl) { phraseEl.dataset.computed = computedPhrase; phraseEl.textContent = poValue("single_bid", null, "tax_phrase", computedPhrase); }
        }
        if (salesRow)   salesRow.style.display = "none";
        if (remodelRow) remodelRow.style.display = "none";
        if (totalRow)   totalRow.style.display = "none";
      }
      // Base description island (work-type noun) — mirror the docx base line so
      // the preview matches, and honor a single_bid.desc override. Guarded like
      // the amount/phrase so mid-edit typing isn't clobbered by a repaint.
      if (!editingBase) {
        const _bd = document.getElementById("base-desc-display");
        if (_bd) { const _c = baseDescLabel(); _bd.dataset.computed = _c; _bd.textContent = poValue("single_bid", null, "desc", _c); }
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
      const wt = (state.work_type || "epoxy").toLowerCase();
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
      // Amounts/labels are editable .tw-fill-edit override islands (display-only).
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
          return `<p class="tw-li" style="margin:0 0 2pt;">` +
                 poIsland("option", r.id, "amount", amount, { strong: true }) + ` – ` +
                 poIsland("option", r.id, "label", label) + `</p>`;
        }).join("");
        // Manual {{#price_line}} rows AFTER the options. data-po-index is the
        // ORIGINAL price_lines index (not the filtered one) so a skipped/blank row
        // can't shift a later override — matches the backend's positional apply.
        const pls = Array.isArray(state.price_lines) ? state.price_lines : [];
        html += pls.map((l, i) => {
          const amt = Number(l.amount || 0);
          const label = (l.label || "").trim();
          if (!amt || !label) return "";
          return `<p class="tw-li" style="margin:0 0 2pt;">` +
                 poIsland("manual", i, "amount", fmtUSDdoc(amt), { strong: true }) + ` – ` +
                 poIsland("manual", i, "label", label) + `</p>`;
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
          const baseId = state.base_tab_id;
          const autoLabel = wt === "combo" ? "Epoxy + Polish (combined)" : "Auto (work-type default)";
          // gyp is a priced role, so allTabs carries epoxy/polish + all 5 gyp
          // variants on every job. Show only the tabs relevant to this work type
          // (mirrors estimate-review.js's chipVisible filter).
          // "Engaged" = the estimator explicitly made it the base or an option.
          // Not "non-zero total" — every sheet carries fixed overhead at 0 SF, so
          // that would never hide the cross-work-type rows (mirrors estimate-review).
          const engaged = (t) => t.id === baseId || (opts[t.id] && opts[t.id].is_option);
          const visTabs = allTabs.filter(t => (wt === "gyp") ? (t.role === "gyp" || engaged(t))
                                                             : (t.role !== "gyp" || engaged(t)));
          // Auto base = epoxy/polish base-kind tab(s); on gyp jobs, only the gyp base.
          const isPartOfAutoBase = (t) => {
            if (baseId) return false;
            if (wt === "gyp") return t.id === GYP_BASE;
            return t.kind === "base" && t.role !== "gyp";
          };
          optsPanel.hidden = false;
          // A "Base bid" radio toggle per sheet (plus an Auto/combined row). The base
          // row hides its option controls; the others keep show + total/deduct.
          let h = `<h3>Pricing options</h3>` +
            `<p class="op-hint">Turn on which sheet is the <strong>Base bid</strong>; mark the others as options (show + total / add/deduct).</p>` +
            `<label class="pr-baserow"><input type="radio" name="pr-base" class="pr-base" value=""${!baseId ? " checked" : ""}> ${esc(autoLabel)}</label>`;
          h += visTabs.map(t => {
            const o = opts[t.id] || {};
            const isBase = baseId === t.id;
            const isOpt = !!o.is_option, show = o.show !== false, mode = o.price_mode === "deduct" ? "deduct" : "total";
            const manual = ((state.tab_notes && state.tab_notes[t.id]) || []).join("\n");
            let r = `<div class="op-row" data-id="${esc(t.id)}">`;
            r += `<label class="pr-baserow"><input type="radio" name="pr-base" class="pr-base" value="${esc(t.id)}"${isBase ? " checked" : ""}> ` +
                 `<span class="op-name">${esc(t.name)} <span class="op-price">${fmtUSD(N(t.total))}</span></span></label>`;
            if (isBase) {
              r += `<div class="pr-optsub"><span class="op-hint">This sheet is the Base bid.</span></div>`;
            } else if (isPartOfAutoBase(t)) {
              r += `<div class="pr-optsub"><span class="op-hint">Part of the combined base bid.</span></div>`;
            } else {
              r += `<label><input type="checkbox" class="pr-isopt" ${isOpt ? "checked" : ""}> Show as a proposal option</label>`;
              r += `<div class="pr-optsub"${isOpt ? "" : ' style="display:none"'}>`;
              r += `<label><input type="checkbox" class="pr-show" ${show ? "checked" : ""}> Show in proposal</label>`;
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
          optsPanel.innerHTML = h;

          const ensureOpt = (id) => { if (!opts[id]) opts[id] = { show_system: true, show_diff: false, is_option: false, show: true, price_mode: "total" }; return opts[id]; };
          const applyAndRefresh = () => { rebuildPricing(); refreshPriceDisplay(); };
          // Base-bid radios (Auto + one per sheet) — turning one on sets the base.
          optsPanel.querySelectorAll("input.pr-base").forEach(rb => rb.addEventListener("change", () => {
            if (!rb.checked) return;
            state.base_tab_id = rb.value || null;
            if (rb.value && opts[rb.value]) opts[rb.value].is_option = false;   // base can't also be an option
            applyAndRefresh();
          }));
          optsPanel.querySelectorAll(".op-row").forEach(row => {
            const id = row.dataset.id;
            const sub = row.querySelector(".pr-optsub");
            const iso = row.querySelector(".pr-isopt");
            if (iso) iso.addEventListener("change", () => {
              const o = ensureOpt(id); o.is_option = iso.checked;
              if (o.is_option) { if (o.show === undefined) o.show = true; if (!o.price_mode) o.price_mode = "total"; }
              if (sub) sub.style.display = iso.checked ? "" : "none";
              applyAndRefresh();
            });
            const sh = row.querySelector(".pr-show");
            if (sh) sh.addEventListener("change", () => { ensureOpt(id).show = sh.checked; applyAndRefresh(); });
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
    if (!altFb || typeof altFb.total_base_bid !== "number") { altBlock.innerHTML = ""; return; }
    const altTotal   = altFb.total_base_bid;
    const altRemodel = Number(altFb.remodel_tax || 0);
    const altFloor   = altTotal - altRemodel;
    const altLabel   = (state.alternate && state.alternate.label)
                       || (acb.alternate && acb.alternate.label) || "Alternate System";
    // Mirrors the .docx {{#alternate}} block literally: header carries the system
    // name, the price line reads "Flooring as described above (material sales tax
    // INCLUDED)", and the tax line is just "Remodel Tax" (no state name). All
    // rows are real bullets in the template.
    altBlock.innerHTML =
      `<p class="tw-li" style="margin:6pt 0 2pt;font-weight:bold;">` +
      `ALTERNATE SYSTEM — <span class="tw-fill">${esc(altLabel)}</span></p>` +
      `<p class="tw-li" style="margin:0 0 2pt;"><strong class="tw-fill">${fmtUSD(altFloor)}</strong> – Flooring as described above ` +
      `(material sales tax INCLUDED)</p>` +
      (altRemodel > 0
        ? `<p class="tw-li" style="margin:0 0 2pt;"><strong class="tw-fill">${fmtUSD(altRemodel)}</strong> – Remodel Tax</p>`
        : "") +
      `<p class="tw-li" style="margin:0 0 2pt;"><strong class="tw-fill">${fmtUSD(altTotal)}</strong> – Total</p>`;
  }

  // ─── Token values (shared by the document fills + the generate payload) ──
  // One assembly of the {{token}} vocabulary (see proposal_writer.py's notes),
  // used BOTH to substitute values into the on-page document (highlighted
  // .tw-fill spans) and to build the generate payload — so the page shows the
  // exact strings the .docx will carry.
  function computeTokenValues(mergedValues) {
    const workType = (state.work_type || "epoxy").toLowerCase();
    const polishSF = Number(mergedValues.polish_sf || mergedValues.system_1_sf || 0);
    const epoxySF  = Number(mergedValues.system_1_sf || 0);
    const coveLF   = Number(mergedValues.cove_1_lf  || 0);
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

    const tokenValues = {
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
      ...mergedValues,
    };

    // Gyp-only tokens. The gyp template prints {{gyp_*_sf}} directly and the
    // backend only backfills BLANK ones, so the frontend must supply them here
    // comma-formatted (a raw number from mergedValues would show "27825"). Also
    // seed the thickness / mobilization / work_description defaults so the doc
    // editor never shows a raw {{token}} before the estimator touches anything —
    // byte-identical to main.py:_ensure_value_aliases' gyp branch.
    if (workType === "gyp") {
      const gN = (v) => Number(String(v == null ? "" : v).replace(/,/g, "")) || 0;
      const fmtInt = (n) => Number(n || 0).toLocaleString("en-US");
      const soft = gN(mergedValues.gyp_soft_sf), hard = gN(mergedValues.gyp_hard_sf), corr = gN(mergedValues.gyp_corridor_sf);
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
  const _termsBandCache = new Map();   // media name -> reserved top band (pt)

  // True when the keyboard focus is inside `el` — used to skip any re-render
  // that would rebuild `el`'s innerHTML (and destroy the caret) while the
  // estimator is typing in one of its editable islands. Skipped repaints
  // self-heal on the next focusout re-render / refreshDocumentFills.
  const focusInside = (el) => !!(el && document.activeElement && el.contains(document.activeElement));

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

  // Region badge wording by the region's leading block name.
  const REGION_LABELS = {
    system: "Systems — from the estimate & the fields sidebar",
    notes:  "Notes — edit in the fields sidebar (one per line)",
  };
  const REGION_LABEL_DEFAULT = "Priced content — edit via the Pricing options & fields sidebars";

  // Read-only preview elements mounted into each region, by block name. The
  // single_bid mount carries the whole base-bid group (incl. the combo
  // breakout + the nested tax_breakout/remodel/has_options rows).
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
    price_line: () => [document.getElementById("price-lines-block")],
    alternate:  () => [document.getElementById("alternate-block")],
  };

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

  function renderBlock(b, tokens) {
    const el = document.createElement("div");
    el.className = "tw-block";
    el.dataset.id = String(b.id);
    el.contentEditable = "true";
    el.spellcheck = false;
    if (b.list) el.classList.add("tw-li");                       // real Word bullet
    else if (b.style && b.style.name === "List Paragraph") el.classList.add("tw-list");
    if (b.align) el.style.textAlign = b.align;
    if (b.style && b.style.bold && !(Array.isArray(b.runs) && b.runs.length)) {
      el.classList.add("tw-bold");                               // run-less fallback only
    }
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
    // No card chrome — the region flows inline as part of the continuous
    // document; the hover tooltip says where its content is edited.
    const first = names.values().next().value;
    wrap.title = REGION_LABELS[first] || REGION_LABEL_DEFAULT;
    for (const name of names) {
      const mount = REGION_MOUNTS[name];
      if (mount) mount().forEach(el => { if (el) wrap.appendChild(el); });
    }
  }

  // Render one ordered slice of blocks into `container`: editable .tw-blocks
  // for free paragraphs; contiguous {{#block}} regions collapse into ONE
  // read-only .tw-priced-region carrying the matching live previews.
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

  // Saved document edits (persisted in state as they're typed, so a reload /
  // device switch keeps them) — reapplied only when they were made against
  // THIS template file (version + type/audience), otherwise the ids could
  // point at the wrong paragraphs.
  function restoreSavedOverrides(wt, audience) {
    const meta = state.paragraph_overrides_meta || {};
    if (String(meta.template_version || "") !== templateVersion ||
        meta.work_type !== wt || meta.audience !== audience) return;
    for (const o of (Array.isArray(state.paragraph_overrides) ? state.paragraph_overrides : [])) {
      if (!o || typeof o.text !== "string") continue;
      const el = docSurface.querySelector(`.tw-block[data-id="${Number(o.id)}"]`);
      if (!el) continue;
      el.textContent = o.text;   // pre-wrap CSS renders the \n line breaks
      el.classList.add("tw-dirty");
      el.classList.toggle("tw-empty", !o.text.trim());
    }
  }

  // Every hand-edited paragraph, as the generate payload's paragraph_overrides.
  // Falls back to the state-persisted list when the editor never loaded (e.g.
  // template fetch failed) so earlier edits still reach the docx.
  function collectOverrides() {
    if (!templateBlocks) {
      return Array.isArray(state.paragraph_overrides) ? state.paragraph_overrides : [];
    }
    const out = [];
    docSurface.querySelectorAll(".tw-block").forEach(el => {
      const id = Number(el.dataset.id);
      const cur = serializeBlock(el);
      if (cur !== pristineById.get(id)) out.push({ id, text: cur });
    });
    return out;
  }

  let _overridesTimer = null;
  function schedulePersistOverrides() {
    if (_overridesTimer) clearTimeout(_overridesTimer);
    _overridesTimer = setTimeout(() => {
      try {
        TW.setState({
          paragraph_overrides: collectOverrides(),
          paragraph_overrides_meta: {
            template_version: templateVersion,
            work_type: (state.work_type || "epoxy").toLowerCase(),
            audience: state.audience || "Direct",
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
      docSurface.querySelectorAll(".tw-block").forEach(el => {
        if (el.classList.contains("tw-dirty")) return;
        // Don't re-fill the block the caret is currently in (a sidebar edit
        // landing within the 150ms window would otherwise clobber it).
        if (el.contains(document.activeElement)) return;
        const b = blockById.get(Number(el.dataset.id));
        if (b) setBlockContent(el, b, tokens);
      });
      renderSystemPreview();
      renderNotesPreview();
      scheduleRepaginate();
    }, 150);
  }

  // WORK systems preview — mirrors main._build_epoxy_systems + the template's
  // {{#system}} rows (grid picks from Epoxy!A22/A26, else the flat fields).
  function renderSystemPreview() {
    // Don't rebuild while the estimator is editing one of the fill islands.
    if (focusInside(systemPreviewEl)) return;
    const merged = Object.assign({}, state, TW.readForm(form));
    const cells = state.cell_values || {};
    const num = (v) => Number(String(v == null ? "" : v).replace(/[$,]/g, "")) || 0;
    const fmt = (n) => Math.round(n).toLocaleString("en-US");
    const picks = [];
    [["Epoxy!A22", "Epoxy!E20", "Epoxy!E34"], ["Epoxy!A26", "Epoxy!E24", "Epoxy!E37"]].forEach(([na, sa, la]) => {
      const name = String(cells[na] || "").trim();
      if (name && !name.includes("Options")) picks.push({ name, sf: num(cells[sa]), lf: num(cells[la]) });
    });
    if (!picks.length) {
      picks.push({ name: String(merged.system_name || "").trim() || "Epoxy System",
                   sf: num(merged.system_1_sf), lf: num(merged.cove_1_lf) });
    }
    const texture = String(merged.texture || "").trim();
    const coveH = String(merged.cove_height || "6").trim() || "6";
    const multi = picks.length > 1;
    const ovs = Array.isArray(state.system_overrides) ? state.system_overrides : [];
    // An estimate-sourced value rendered as an editable, highlighted island.
    // The yellow .tw-fill stays as a provenance cue; the text is freely
    // editable in place. `data-computed` is the value the estimate/fields
    // produce, so the input handler can revert an override that's been
    // emptied or re-typed back to the computed value. Display-only — never
    // written to cell_values / pricing (see the systemPreviewEl input handler
    // and backend system_overrides).
    const editSpan = (i, field, computed) => {
      const ov = ovs[i] || {};
      const v = (typeof ov[field] === "string" && ov[field].trim()) ? ov[field] : computed;
      return `<span class="tw-fill tw-fill-edit" contenteditable="true" spellcheck="false"` +
             ` data-sys-index="${i}" data-sys-field="${field}"` +
             ` data-computed="${escHtml(computed)}">${escHtml(v)}</span>`;
    };
    systemPreviewEl.innerHTML = picks.map((s, i) => {
      const prefix = multi ? `Option ${i + 1}:` : "System:";
      const lf = s.lf > 0 ? ` and ${fmt(s.lf)} LF of ${coveH}" epoxy cove base` : "";
      // Bullet shape mirrors the template's rows: System + Area are real
      // Word bullets; Texture is an indented (bullet-less) List Paragraph.
      return `<p class="tw-li" style="margin:0 0 1pt;"><strong>${escHtml(prefix)}</strong>   ${editSpan(i, "name", s.name)}</p>` +
             `<p class="tw-list" style="margin:0 0 1pt;padding-left:9pt;">Texture:  ${editSpan(i, "texture", texture)}</p>` +
             `<p class="tw-li" style="margin:0 0 4pt;"><strong>Area: ~${editSpan(i, "sqft", fmt(s.sf))} SF of epoxy flooring${escHtml(lf)}</strong></p>`;
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
        return `<p class="tw-note-edit tw-note-blank" contenteditable="true" spellcheck="false"` +
               ` data-note-index="${i}" style="margin:0 0 1pt;"></p>`;
      return `<p class="tw-li tw-note-edit" contenteditable="true" spellcheck="false"` +
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
  function fitNotesBox() {
    const box = notesPreviewEl.closest(".tw-txbx");
    if (!box || !box.dataset.boxHPt) return;
    box.style.fontSize = "";                                   // reset to the design size
    const target = parseFloat(box.dataset.boxHPt) * 96 / 72 + 1;   // design height in px (+1 slack)
    if (!(target > 0)) return;
    if (box.offsetHeight <= target) {                          // fits at full size — no inline size
      box.classList.remove("tw-notes-overflow");
      box.title = "";
      return;
    }
    for (let k = 0.95; k >= 0.60 - 1e-9; k -= 0.05) {
      box.style.fontSize = Math.round(k * 100) + "%";
      if (box.offsetHeight <= target) {
        box.classList.remove("tw-notes-overflow");
        box.title = "";
        return;
      }
    }
    // Still over at the 60% floor: keep the floor and flag the collision so the
    // estimator sees it may print over the acceptance area.
    box.classList.add("tw-notes-overflow");
    box.title = "Notes exceed the box and may overlap the acceptance area in print";
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
    if (!artUrlCache.has(name)) {
      const wt = (state.work_type || "epoxy").toLowerCase();
      const audience = state.audience || "Direct";
      const url = `/api/proposal-template/media?work_type=${encodeURIComponent(wt)}` +
                  `&audience=${encodeURIComponent(audience)}&name=${encodeURIComponent(name)}`;
      const p = fetch(url, { headers: TW.authHeaders() })
        .then(r => (r.ok ? r.blob() : null))
        .then(b => (b ? blobToDataUrl(b) : null))
        .catch(() => null)
        .then(u => {
          if (!u) artUrlCache.delete(name);   // don't cache a failure — allow retry
          return u;
        });
      artUrlCache.set(name, p);
    }
    return artUrlCache.get(name);
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
    docSurface.innerHTML = "";

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
    for (const box of (geo.boxes || [])) {
      const list = byBox.get(box.id);
      if (!list || box.x_pt == null) continue;
      const el = document.createElement("div");
      el.className = "tw-txbx";
      el.style.left = box.x_pt + "pt";
      el.style.top = box.y_pt + "pt";
      el.style.width = (box.w_pt || 200) + "pt";
      el.style.minHeight = (box.h_pt || 0) + "pt";
      el.dataset.boxHPt = box.h_pt || "";          // inert metadata for fitNotesBox()
      renderBlockList(el, list, tokens);
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
  // on no ink or any error (canvas taint, decode failure). Cached per media
  // name so a work-type switch reuses the result instead of re-scanning.
  function measureTermsBand(dataUrl, mediaName) {
    const key = mediaName || dataUrl;
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
  docSurface.addEventListener("focusout", (e) => {
    if (!_repagPending) return;
    const to = e.relatedTarget;
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
    docSurface.innerHTML = "";
    const pg = document.createElement("div");
    pg.className = "tw-page tw-flow";
    pg.style.width = pageWpt + "pt";
    docSurface.appendChild(pg);
    renderBlockList(pg, templateBlocks.filter(b => b.txbx != null), tokens);
    renderBlockList(pg, templateBlocks.filter(b => b.txbx == null), tokens);
  }

  async function initDocumentEditor() {
    const wt = (state.work_type || "epoxy").toLowerCase();
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

      const tokens = computeTokenValues(Object.assign({}, state, TW.readForm(form)));
      const geo = j.geometry || {};
      const hasBoxes = Array.isArray(geo.boxes) && geo.boxes.some(b => b.x_pt != null)
        && templateBlocks.some(b => b.txbx != null);
      if (hasBoxes) renderPositioned(geo, tokens);
      else renderFlow(tokens);

      restoreSavedOverrides(wt, audience);
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
      // Degraded fallback: surface the price preview alone so the estimator
      // can still verify pricing and continue; previously saved document
      // edits still ship via collectOverrides()'s state fallback.
      const loading = document.getElementById("doc-loading");
      if (loading) {
        loading.textContent = "Couldn't load the document preview — showing the price summary instead. You can still continue.";
        stagingPanel.hidden = false;
        loading.appendChild(stagingPanel);
      }
      refreshPriceDisplay();
      applyZoom();
    }
  }

  // Mark blocks dirty as they're edited (delegated — blocks re-render freely).
  docSurface.addEventListener("input", (e) => {
    const el = e.target && e.target.closest ? e.target.closest(".tw-block") : null;
    if (!el) return;
    const cur = serializeBlock(el);
    el.classList.toggle("tw-dirty", cur !== pristineById.get(Number(el.dataset.id)));
    el.classList.toggle("tw-empty", !cur.trim());
    schedulePersistOverrides();
    // A terms-page block can change height as it's edited; repaginate once
    // the caret leaves the terms flow (scheduleRepaginate defers on focus).
    if (el.closest(".tw-terms-page")) scheduleRepaginate();
  });

  // ── Editable estimate-sourced fills: WORK systems ──────────────────────
  // systemPreviewEl is a stable element (its children are rewritten, but it
  // itself is never replaced), so one delegated listener survives every
  // rebuild. Edits write display-only overrides into state.system_overrides
  // (dense, by option index); they never touch cell_values or pricing.
  let _sysOvTimer = null;
  systemPreviewEl.addEventListener("input", (e) => {
    const sp = e.target && e.target.closest ? e.target.closest("[data-sys-field]") : null;
    if (!sp) return;
    const i = Number(sp.dataset.sysIndex);
    const field = sp.dataset.sysField;
    if (!Number.isInteger(i) || i < 0 || !field) return;
    const ovs = Array.isArray(state.system_overrides) ? state.system_overrides : (state.system_overrides = []);
    while (ovs.length <= i) ovs.push({});          // keep dense — no sparse nulls in JSON
    if (!ovs[i] || typeof ovs[i] !== "object") ovs[i] = {};
    const v = serializeBlock(sp).replace(/\s*\n+\s*/g, " ").trim();
    if (!v || v === (sp.dataset.computed || "")) delete ovs[i][field];   // empty / back-to-computed -> revert
    else ovs[i][field] = v;
    if (_sysOvTimer) clearTimeout(_sysOvTimer);
    _sysOvTimer = setTimeout(() => { try { TW.setState({ system_overrides: state.system_overrides }); } catch {} }, 500);
  });
  systemPreviewEl.addEventListener("focusout", (e) => {
    if (!systemPreviewEl.contains(e.relatedTarget)) renderSystemPreview();   // normalize + apply reverts
  });

  // ── Editable estimate-sourced fills: NOTES bullets ─────────────────────
  // Two-way bound to the sidebar #notes-text textarea (single source of
  // truth). Writing textarea.value programmatically fires NO form 'input'
  // event, so this never loops back through refreshDocumentFills.
  let _notesOvTimer = null;
  notesPreviewEl.addEventListener("input", () => {
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
    // Re-fit the font as bullets are typed. This only changes the box's
    // font-size (never rebuilds the bullets), so the caret is preserved.
    try { fitNotesBox(); } catch {}
    if (_notesOvTimer) clearTimeout(_notesOvTimer);
    _notesOvTimer = setTimeout(() => { try { TW.setState({ notes_text: ta.value }); } catch {} }, 300);
  });
  notesPreviewEl.addEventListener("focusout", (e) => {
    if (!notesPreviewEl.contains(e.relatedTarget)) renderNotesPreview();   // re-split Enter'd lines
  });

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
    return pov;
  }
  function _handlePoInput(e) {
    const sp = e.target && e.target.closest ? e.target.closest("[data-po-field]") : null;
    if (!sp) return;
    const kind = sp.dataset.poKind, field = sp.dataset.poField;
    if (!kind || !field) return;
    const v = serializeBlock(sp).replace(/\s*\n+\s*/g, " ").trim();
    const revert = !v || v === (sp.dataset.computed || "");   // empty / back-to-computed
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
    } else { return; }
    if (_povTimer) clearTimeout(_povTimer);
    _povTimer = setTimeout(() => { try { TW.setState({ price_overrides: state.price_overrides }); } catch {} }, 500);
  }
  const _plBlockEl = document.getElementById("price-lines-block");
  const _baseBidRowEl = document.getElementById("base-bid-row");
  if (_plBlockEl) {
    _plBlockEl.addEventListener("input", _handlePoInput);
    _plBlockEl.addEventListener("focusout", (e) => {
      if (!_plBlockEl.contains(e.relatedTarget)) { try { refreshPriceDisplay(); } catch {} }  // normalize + reverts
    });
  }
  if (_baseBidRowEl) {
    _baseBidRowEl.addEventListener("input", _handlePoInput);
    _baseBidRowEl.addEventListener("focusout", (e) => {
      if (!_baseBidRowEl.contains(e.relatedTarget)) { try { refreshPriceDisplay(); } catch {} }  // normalize + reverts
    });
  }

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
    _persistTimer = setTimeout(() => { try { TW.setState(TW.readForm(form)); } catch {} }, 300);
  });

  document.getElementById("back-btn").addEventListener("click", () => {
    TW.setState(TW.readForm(form));
    window.location.assign(TW.withDraft("/estimate-review.html"));
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
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

    // We no longer call /api/generate here. The actual file generation
    // moved to the Done page so the user has one final review screen before
    // anything customer-facing happens. Stash the payload that Done.html
    // will POST when the user clicks Generate.
    TW.setState({
      ...mergedValues,
      paragraph_overrides: paragraphOverrides,
      paragraph_overrides_meta: {
        template_version: templateVersion,
        work_type: (state.work_type || "epoxy").toLowerCase(),
        audience: state.audience || "Direct",
      },
      proposal_payload: {
        work_type: state.work_type || "epoxy",
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
        combo_options: comboSystemLines(),
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
        // Doc-editor per-option DISPLAY overrides for the WORK {{#system}}
        // rows (epoxy only) — edit the shown system name/texture/area without
        // touching cell_values or the price.
        system_overrides: Array.isArray(state.system_overrides) ? state.system_overrides : [],
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
  });
