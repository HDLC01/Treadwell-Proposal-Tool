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
  (function prefillNotes() {
    const ta = document.getElementById("notes-text");
    if (!ta) return;
    if (Array.isArray(state.notes) && state.notes.length) { ta.value = state.notes.join("\n"); return; }
    if (String(ta.value || "").trim()) return;
    fetch("/api/default-notes?work_type=" + encodeURIComponent(_wt), { headers: TW.authHeaders() })
      .then(r => r.json())
      .then(j => { if (!String(ta.value || "").trim() && Array.isArray(j.notes)) ta.value = j.notes.join("\n"); })
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
      if (name) el.value = name;
    };
    apply();
    try { if (window.TWAuth && window.TWAuth.ready) window.TWAuth.ready.then(apply); } catch {}
  })();

  // ─── Work-type-aware UI ────────────────────────────────────────
  // The proposal layout differs per work_type:
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

  // Live update the inline $ amounts in the price section. This preview MIRRORS
  // the .docx single_bid block exactly (Base Bid + Remodel Tax = Total), using
  // the same figures + tax wording the generate payload sends, so what the
  // estimator sees on screen is what the customer gets.
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
    const incl = String((form.querySelector("[name='tax_inclusion']") || {}).value || "INCLUDED").trim().toUpperCase();
    const exempt = ["EXCLUDED", "EXEMPT", "NOT INCLUDED", "NONE", "NO", "N/A"].includes(incl);
    const broken = ["BROKEN_OUT", "BROKEN OUT", "BROKENOUT", "ITEMIZED", "BREAKOUT"].includes(incl);

    const salesRow   = document.getElementById("sales-tax-row");
    const remodelRow = document.getElementById("remodel-tax-row");
    const totalRow   = document.getElementById("total-row");
    const phraseEl   = document.getElementById("base-tax-phrase-display");

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
    renderProposalExtras();
  }

  // Render the structured price lines + the recommended ALTERNATE system into
  // the visible PRICE section, mirroring the {{#price_line}} / {{#alternate}}
  // blocks the backend writes into the .docx. Driven by state (set on the
  // Estimate screen), so the estimator sees the alternate BEFORE generating.
  function renderProposalExtras() {
    const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
      c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

    // (rooms) Per-sheet priced options: base bid first, then each copy. The
    // DOCUMENT (#rooms-block) shows the read-only preview; the CONTROLS (toggles +
    // notes) live in the left #options-panel. state.rooms[] is snapshotted on
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
        const rooms = (Array.isArray(state.rooms) ? state.rooms : []).filter(r => r && r.bid && N(r.bid.total) > 0);
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

      // LEFT controls panel: base-bid picker + per-tab option toggles — mirrors the
      // Estimate screen's #bid-bar (both edit state.base_tab_id + state.tab_opts).
      // Interactive when we have the per-tab snapshot (state.priced_tabs); otherwise
      // the panel hides and the preview above stays read-only.
      const allTabs = Array.isArray(state.priced_tabs) ? state.priced_tabs : [];
      if (optsPanel) {
        if (!allTabs.length) { optsPanel.hidden = true; optsPanel.innerHTML = ""; }
        else {
          const opts = (state.tab_opts && typeof state.tab_opts === "object") ? state.tab_opts : (state.tab_opts = {});
          const baseId = state.base_tab_id;
          const autoLabel = wt === "combo" ? "Epoxy + Polish (combined)" : "Auto";
          const others = allTabs.filter(t => t.id !== baseId &&
            !(!baseId && wt === "combo" && t.kind === "base"));
          optsPanel.hidden = false;
          let h = `<h3>Pricing options</h3>` +
            `<p class="op-hint">Pick the Base bid; mark other sheets as options (show + total / deduct).</p>` +
            `<label class="op-notes">Base bid<select id="pr-base-select">` +
            `<option value=""${!baseId ? " selected" : ""}>${esc(autoLabel)}</option>` +
            allTabs.map(t => `<option value="${esc(t.id)}"${baseId === t.id ? " selected" : ""}>${esc(t.name)} — ${fmtUSD(N(t.total))}</option>`).join("") +
            `</select></label>`;
          h += others.map(t => {
            const o = opts[t.id] || {};
            const isOpt = !!o.is_option, show = o.show !== false, mode = o.price_mode === "deduct" ? "deduct" : "total";
            const manual = ((state.tab_notes && state.tab_notes[t.id]) || []).join("\n");
            let r = `<div class="op-row" data-id="${esc(t.id)}">`;
            r += `<div class="op-name">${esc(t.name)} <span class="op-price">${fmtUSD(N(t.total))}</span></div>`;
            r += `<label><input type="checkbox" class="pr-isopt" ${isOpt ? "checked" : ""}> Show as a proposal option</label>`;
            r += `<div class="pr-sub"${isOpt ? "" : ' style="display:none"'}>`;
            r += `<label><input type="checkbox" class="pr-show" ${show ? "checked" : ""}> Show in proposal</label>`;
            r += `<label>Price as <select class="pr-mode"><option value="total"${mode === "total" ? " selected" : ""}>total amount</option><option value="deduct"${mode === "deduct" ? " selected" : ""}>deduct (VE)</option></select></label>`;
            r += `<label class="op-notes">Notes (one per line)<textarea class="room-notes" rows="2">${esc(manual)}</textarea></label>`;
            r += `</div></div>`;
            return r;
          }).join("");
          optsPanel.innerHTML = h;

          const ensureOpt = (id) => { if (!opts[id]) opts[id] = { show_system: true, show_diff: false, is_option: false, show: true, price_mode: "total" }; return opts[id]; };
          const applyAndRefresh = () => { rebuildPricing(); refreshPriceDisplay(); };
          const baseSel = document.getElementById("pr-base-select");
          if (baseSel) baseSel.addEventListener("change", () => {
            state.base_tab_id = baseSel.value || null;
            if (baseSel.value && opts[baseSel.value]) opts[baseSel.value].is_option = false;
            applyAndRefresh();
          });
          optsPanel.querySelectorAll(".op-row").forEach(row => {
            const id = row.dataset.id;
            const sub = row.querySelector(".pr-sub");
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

  // Recalc on input changes
  form.addEventListener("input", refreshPriceDisplay);

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

    // We no longer call /api/generate here. The actual file generation
    // moved to the Done page so the user has one final review screen before
    // anything customer-facing happens. Stash the payload that Done.html
    // will POST when the user clicks Generate.
    TW.setState({
      ...mergedValues,
      proposal_payload: {
        work_type: state.work_type || "epoxy",
        audience:  state.audience  || "Direct",
        values:    { ...mergedValues, ...tokenValues },
        cell_values: state.cell_values || {},
        // Custom material lines (Super Stick / edge-case adds) -> Epoxy spare rows
        extras: Array.isArray(state.extras) ? state.extras : [],
        // Structured proposal price lines (options / unit prices) -> {{#price_line}} rows
        price_lines: Array.isArray(state.price_lines) ? state.price_lines : [],
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
        // Editable NOTES (one bullet per line); empty -> backend uses the standard list.
        notes: String(mergedValues.notes_text || "").split("\n").map(s => s.trim()).filter(Boolean),
      },
      // Also persist the lump sum string so Done can show it without
      // re-reading from HF (which lives on the Estimate Review page).
      lump_sum_display: lumpSumText,
    });
    window.location.assign("/done.html");
  });
