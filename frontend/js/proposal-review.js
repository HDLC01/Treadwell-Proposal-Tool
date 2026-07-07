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

  // Proposal boilerplate as REAL default values (these used to be placeholders,
  // which never made it into the generated doc — that's why Schedule came out
  // blank). writeForm above already applied any saved / AI-autofilled values, so
  // we only fill fields that are still blank: autofill and manual edits win, but
  // a proposal generated without autofill still carries the standard text.
  const _wt = (state.work_type || "epoxy").toLowerCase();
  const _scopeDefault = _wt === "polish"
    ? "Demo existing flooring and place in a dumpster. Fill concrete joints with backer rod and polyurea caulking. Patch minor divots. Grind and polish concrete with successive passes using finer grit pads for each pass. Apply hardener/densifier & topical sealer. Perform high-speed burnish. Assumes polish over: clean, sound & solid concrete substrate."
    : "Demo (one layer of) existing flooring and place in a dumpster provided by the owner. Prepare substrate surface profile utilizing mechanical means (grinding or shot blasting). Prep substrate cracks and non-moving joints (includes minor floor prep, patching of minor substrate defects, spalls and divots). Install Epoxy System. Assumes installation over: clean, sound & solid concrete substrate.";
  const PROPOSAL_DEFAULTS = {
    scope_notes: _scopeDefault,
    schedule_notes: "Assumes all areas available at one time, approx. 1 week to complete full scope",
    exclusions: "Multiple layers of floor to be removed (change order is necessary), Moving of Furniture/Fixtures, Touch-Up Paint, Excessive Patching (i.e., skim coating & more than 1 bag of patch material per 1,000 sf, see notes below), Demo of Existing Floor/Glue/Etc., Weekend or night work, Credit for Unused mobilizations",
  };
  for (const [nm, def] of Object.entries(PROPOSAL_DEFAULTS)) {
    const el = form.querySelector(`[name="${nm}"]`);
    if (el && !String(el.value || "").trim()) el.value = def;
  }

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
  (function prefillNotes() {
    const ta = document.getElementById("notes-text");
    if (!ta) return;
    const applyAndPreview = (text) => { ta.value = text; try { renderNotesPreview(); } catch {} };
    if (Array.isArray(state.notes) && state.notes.length) { applyAndPreview(state.notes.join("\n")); return; }
    if (String(ta.value || "").trim()) return;
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
                :                   "Epoxy Flooring";
    document.getElementById("work-type-label").value = label;

    // Toggle area rows by work_type
    const epoxyRow  = document.getElementById("area-row-epoxy");
    const polishRow = document.getElementById("area-row-polish");
    const textureRow = document.getElementById("texture-row");
    if (wt === "polish") {
      epoxyRow.style.display  = "none";
      polishRow.style.display = "";
      textureRow.style.display = "none"; // polish doesn't have texture
    } else if (wt === "epoxy") {
      epoxyRow.style.display  = "";
      polishRow.style.display = "none";
      textureRow.style.display = "";
    } else { // combo
      epoxyRow.style.display  = "";
      polishRow.style.display = "";
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
    if ((state.work_type || "epoxy").toLowerCase() === "polish") return;
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

  // Recompute the base bid + priced options from the per-tab totals snapshotted on
  // the Estimate screen (state.priced_tabs). This lets the base-bid picker + the
  // per-option total/deduct toggles work HERE too, without the sheet engine. It
  // MIRRORS estimate-review.js:snapshotLumpSumsToState — keep the two in sync.
  function rebuildPricing() {
    const all = Array.isArray(state.priced_tabs) ? state.priced_tabs : [];
    if (!all.length) return;   // older draft w/o the snapshot — leave state.rooms as-is
    const wt = (state.work_type || "epoxy").toLowerCase();
    const opts = (state.tab_opts && typeof state.tab_opts === "object") ? state.tab_opts : (state.tab_opts = {});
    const N = (v) => Number(v) || 0;
    const byId = (id) => all.find(t => t.id === id);
    let baseTab = state.base_tab_id ? byId(state.base_tab_id) : null;
    let shownBase, salesTax, remodelTax;
    if (baseTab) {
      shownBase = N(baseTab.total); salesTax = N(baseTab.sales_tax); remodelTax = N(baseTab.remodel);
    } else {
      // No explicit base: work_type fallback (combo = Epoxy + Polish base tabs).
      const eB = all.find(t => t.role === "epoxy" && t.kind === "base") || all.find(t => t.role === "epoxy");
      const pB = all.find(t => t.role === "polish" && t.kind === "base") || all.find(t => t.role === "polish");
      if (wt === "polish") { baseTab = pB || null; shownBase = N(pB && pB.total); salesTax = N(pB && pB.sales_tax); remodelTax = N(pB && pB.remodel); }
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
        `<p style="margin:0 0 6pt;"><strong>${escP(l.amount_formatted)}</strong> – ${escP(l.label)}</p>`).join("");
      if (baseBidHeading) baseBidHeading.style.display = "none";
      if (baseBidRow) baseBidRow.style.display = "none";
      if (salesRow)   salesRow.style.display = "none";
      if (remodelRow) remodelRow.style.display = "none";
      if (totalRow)   totalRow.style.display = "none";
    } else {
      if (comboBlock) comboBlock.style.display = "none";
      if (baseBidHeading) baseBidHeading.style.display = "";
      if (baseBidRow) baseBidRow.style.display = "";
      if (broken) {
        document.getElementById("base-bid-display").textContent = fmtUSD(baseBid);
        phraseEl.textContent = "";
        document.getElementById("sales-tax-display").textContent = fmtUSD(salesTax);
        if (salesRow)   salesRow.style.display = "";
        if (remodelRow) remodelRow.style.display = remodelTax > 0 ? "" : "none";
        document.getElementById("tax-amount-display").textContent = fmtUSD(remodelTax);
        if (totalRow)   totalRow.style.display = "";
        document.getElementById("total-display").textContent = fmtUSD(lumpSumN);
      } else {
        document.getElementById("base-bid-display").textContent = fmtUSD(lumpSumN);
        phraseEl.textContent = exempt ? "(tax exempt)"
          : remodelTax > 0 ? "(Remodel Tax AND material sales tax INCLUDED)"
          : "(material sales tax INCLUDED)";
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
      const wt = (state.work_type || "epoxy").toLowerCase();
      const N = (v) => Number(v) || 0;
      const floorNoun = wt === "polish" ? "Polished Concrete Flooring"
                      : wt === "sealer" ? "Sealed Concrete" : "Epoxy flooring";
      const taxPhrase = (r) => N(r.bid && r.bid.remodel) > 0
        ? "(Remodel Tax AND material sales tax INCLUDED)"
        : "(material sales tax INCLUDED)";

      // DOCUMENT preview (read-only) — base as a total line; each option as a total
      // line or a "($savings) – Deduct VE for … in lieu of <base>" line, mirroring
      // the .docx {{#room}} block. Re-reads state.rooms fresh on each call.
      function renderRoomsPreview() {
        if (!roomsBlock) return;
        // Combo breakout leads PRICE with its own Option 1/Option 2 total lines —
        // there's no "combined base" concept in the docx (rooms_arg is always []
        // and _build_options excludes is_base rows), so the synthetic combined
        // "Base Bid: $<epoxy+polish>" room built by rebuildPricing() for the combo
        // fallback must be dropped here too, or the preview shows a line the
        // generated .docx never prints.
        const comboBreakoutActive = comboSystemLines().length > 0;
        const rooms = (Array.isArray(state.rooms) ? state.rooms : [])
          .filter(r => r && r.bid && N(r.bid.total) > 0 && !(comboBreakoutActive && r.is_base));
        if (!rooms.length) { roomsBlock.innerHTML = ""; return; }
        let html = `<p style="margin:10pt 0 4pt;font-weight:bold;">Pricing options</p>`;
        html += rooms.map((r) => {
          const desc = r.system_desc || r.option_desc || floorNoun;
          const autoNotes = Array.isArray(r.notes_auto) ? r.notes_auto : [];
          const manual = Array.isArray(r.notes_manual) ? r.notes_manual : [];
          const isDeduct = !r.is_base && r.price_mode === "deduct" && N(r.deduct_amount) > 0;
          let h = `<div style="margin:0 0 10pt;border-left:3px solid #c8102e;padding-left:8px;">`;
          if (r.is_base) {
            h += `<p style="margin:0;"><strong>Base Bid:</strong></p>`;
            h += `<p style="margin:0;"><strong>${fmtUSD(r.bid.total)}</strong> – ${esc(desc)} as described above <em>${taxPhrase(r)}</em></p>`;
          } else if (isDeduct) {
            h += `<p style="margin:0;"><strong>(${fmtUSD(r.deduct_amount)})</strong> – Deduct VE for ${esc(r.option_desc || r.name)}, in lieu of ${esc(r.base_desc || "the base bid")}.</p>`;
          } else {
            h += `<p style="margin:0;"><strong>${fmtUSD(r.bid.total)}</strong> – ${esc(desc)} as described above <em>${taxPhrase(r)}</em></p>`;
          }
          // (No separate system bullet: the price line above already names the
          // system via option_desc, and the generated .docx doesn't add one either.)
          h += autoNotes.concat(manual).map(n => `<p style="margin:0 0 0 14px;color:#555;">• ${esc(n)}</p>`).join("");
          h += `</div>`;
          return h;
        }).join("");
        roomsBlock.innerHTML = html;
      }
      renderRoomsPreview();

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
          const isPartOfAutoBase = (t) => !baseId && t.kind === "base";   // Auto base = the base-kind tab(s)
          optsPanel.hidden = false;
          // A "Base bid" radio toggle per sheet (plus an Auto/combined row). The base
          // row hides its option controls; the others keep show + total/deduct.
          let h = `<h3>Pricing options</h3>` +
            `<p class="op-hint">Turn on which sheet is the <strong>Base bid</strong>; mark the others as options (show + total / deduct).</p>` +
            `<label class="pr-baserow"><input type="radio" name="pr-base" class="pr-base" value=""${!baseId ? " checked" : ""}> ${esc(autoLabel)}</label>`;
          h += allTabs.map(t => {
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
              r += `<label>Price as <select class="pr-mode"><option value="total"${mode === "total" ? " selected" : ""}>total amount</option><option value="deduct"${mode === "deduct" ? " selected" : ""}>deduct (VE)</option></select></label>`;
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
            if (md) md.addEventListener("change", () => { ensureOpt(id).price_mode = md.value === "deduct" ? "deduct" : "total"; applyAndRefresh(); });
            const ta = row.querySelector(".room-notes");
            if (ta) ta.addEventListener("input", () => {
              if (!state.tab_notes) state.tab_notes = {};
              state.tab_notes[id] = ta.value.split("\n").map(s => s.trim()).filter(Boolean);
              rebuildPricing();       // refresh state.rooms (notes) …
              renderRoomsPreview();   // … then update ONLY the preview (keep textarea focus)
              TW.setState({ tab_notes: state.tab_notes });
            });
          });
        }
      }
    }

    // (a) Structured price lines (options / unit prices listed under PRICE)
    const plBlock = document.getElementById("price-lines-block");
    if (plBlock) {
      const pls = Array.isArray(state.price_lines) ? state.price_lines : [];
      plBlock.innerHTML = pls.map(l => {
        const amt = Number(l.amount || 0);
        const label = (l.label || "").trim();
        if (!amt || !label) return "";
        return `<p style="margin:0 0 6pt;"><strong>${fmtUSD(amt)}</strong> – ${esc(label)}</p>`;
      }).join("");
    }

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
    // INCLUDED)", and the tax line is just "Remodel Tax" (no state name).
    altBlock.innerHTML =
      `<p style="margin:14pt 0 6pt;font-weight:bold;color:#c8102e;border-top:1px solid #c8102e;padding-top:10pt;">` +
      `ALTERNATE SYSTEM — ${esc(altLabel)}</p>` +
      `<p style="margin:0 0 6pt;"><strong>${fmtUSD(altFloor)}</strong> – Flooring as described above ` +
      `<em>(material sales tax INCLUDED)</em></p>` +
      (altRemodel > 0
        ? `<p style="margin:0 0 6pt;"><strong><mark>${fmtUSD(altRemodel)}</mark></strong> – Remodel Tax</p>`
        : "") +
      `<p style="margin:0 0 6pt;"><strong>${fmtUSD(altTotal)}</strong> – Total</p>`;
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
      ...mergedValues,
    };

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
  const docFront     = document.getElementById("doc-front");
  const docBody      = document.getElementById("doc-body");
  const docLoading   = document.getElementById("doc-loading");
  const termsToggle  = document.getElementById("terms-toggle");
  const stagingPanel = document.getElementById("price-preview-staging");

  let templateBlocks  = null;   // blocks from the endpoint (null until loaded)
  let templateVersion = "";
  const blockById     = new Map();   // id -> block record
  const pristineById  = new Map();   // id -> plain-text pristine rendering

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
                       "sales-tax-row", "remodel-tax-row", "total-row"]
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

  // Fill a block element from its template text + current token values, and
  // record the pristine rendering. Only ever called on non-dirty blocks (a
  // hand-edited paragraph belongs to the estimator until they revert it).
  function setBlockContent(el, templText, tokens) {
    el.innerHTML = fillHtml(templText, tokens);
    const plain = fillPlain(templText, tokens);
    pristineById.set(Number(el.dataset.id), plain);
    el.classList.toggle("tw-empty", !plain.trim());
  }

  function renderBlock(b, tokens) {
    const el = document.createElement("div");
    el.className = "tw-block";
    el.dataset.id = String(b.id);
    el.contentEditable = "true";
    el.spellcheck = false;
    if (b.style && b.style.bold) el.classList.add("tw-bold");
    if (b.style && b.style.name === "List Paragraph") el.classList.add("tw-list");
    const hint = singleTokenHint(b.text);
    if (hint) el.dataset.hint = hint;
    setBlockContent(el, b.text, tokens);
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
    const first = names.values().next().value;
    const badge = wrap.querySelector(".tw-region-badge");
    if (badge) {
      badge.textContent = REGION_LABELS[first] ? REGION_LABELS[first].split(" — ")[0] : "Priced content";
      badge.title = REGION_LABELS[first] || REGION_LABEL_DEFAULT;
    }
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
          const badge = document.createElement("span");
          badge.className = "tw-region-badge";
          regionWrap.appendChild(badge);
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
        const b = blockById.get(Number(el.dataset.id));
        if (b) setBlockContent(el, b.text, tokens);
      });
      renderSystemPreview();
      renderNotesPreview();
    }, 150);
  }

  // WORK systems preview — mirrors main._build_epoxy_systems + the template's
  // {{#system}} rows (grid picks from Epoxy!A22/A26, else the flat fields).
  function renderSystemPreview() {
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
    systemPreviewEl.innerHTML = picks.map((s, i) => {
      const prefix = multi ? `Option ${i + 1}:` : "System:";
      const lf = s.lf > 0 ? ` and ${fmt(s.lf)} LF of ${coveH}" epoxy cove base` : "";
      return `<p style="margin:0 0 2pt;"><strong>${escHtml(prefix)}</strong>   <span class="tw-fill">${escHtml(s.name)}</span></p>` +
             `<p style="margin:0 0 2pt;"><strong>Texture:</strong>  <span class="tw-fill">${escHtml(texture)}</span></p>` +
             `<p style="margin:0 0 6pt;"><strong>Area:</strong> ~<span class="tw-fill">${escHtml(fmt(s.sf))}</span> SF of epoxy flooring${escHtml(lf)}</p>`;
    }).join("");
  }

  // NOTES preview — one line per non-blank sidebar bullet ({{#notes}} block).
  function renderNotesPreview() {
    const ta = document.getElementById("notes-text");
    const lines = String((ta && ta.value) || "").split("\n").map(s => s.trim()).filter(Boolean);
    notesPreviewEl.innerHTML = lines.map(l => `<p style="margin:0 0 2pt;">${escHtml(l)}</p>`).join("");
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
      docFront.innerHTML = "";
      docBody.innerHTML = "";
      // Front page (floating-text-box content) first — that's how the printed
      // page reads; the body boilerplate (Terms & Conditions) collapses below.
      renderBlockList(docFront, templateBlocks.filter(b => b.in_txbx), tokens);
      renderBlockList(docBody, templateBlocks.filter(b => !b.in_txbx), tokens);
      docLoading.hidden = true;
      termsToggle.hidden = !docBody.childElementCount;

      restoreSavedOverrides(wt, audience);
      renderSystemPreview();
      renderNotesPreview();
      refreshPriceDisplay();   // repaint now that the preview els live in the page
    } catch (err) {
      // Degraded fallback: surface the price preview alone so the estimator
      // can still verify pricing and continue; previously saved document
      // edits still ship via collectOverrides()'s state fallback.
      docLoading.textContent = "Couldn't load the document preview — showing the price summary instead. You can still continue.";
      stagingPanel.hidden = false;
      docFront.appendChild(stagingPanel);
      refreshPriceDisplay();
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
  });

  termsToggle.addEventListener("click", () => {
    const open = docBody.hidden;
    docBody.hidden = !open;
    document.getElementById("terms-caret").textContent = open ? "▾" : "▸";
  });

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
    window.location.assign("/estimate-review.html");
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
        // Editable NOTES (one bullet per line); empty -> backend uses the standard list.
        notes: String(mergedValues.notes_text || "").split("\n").map(s => s.trim()).filter(Boolean),
        // Document-editor edits -> proposal_writer paragraph overrides,
        // applied to the pristine template BEFORE block expansion (id-safe).
        paragraph_overrides: paragraphOverrides,
      },
      // Also persist the lump sum string so Done can show it without
      // re-reading from HF (which lives on the Estimate Review page).
      lump_sum_display: lumpSumText,
    });
    window.location.assign("/done.html");
  });
