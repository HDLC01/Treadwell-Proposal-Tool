// Externalized from proposal-review.html (CSP: drop script-src 'unsafe-inline'). Do not add inline scripts.
  const state = TW.getState();
  if (!state.project_name) {
    document.querySelector(".word-canvas").innerHTML = `
      <div style="background:white;padding:40pt 30pt;border-radius:4px;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,0.15);">
        <h1 style="color:#605e5c;">No project started</h1>
        <p>Start an intake first to enable the Proposal step.</p>
        <a href="/" style="background:#2b579a;color:white;text-decoration:none;padding:8px 16px;border-radius:2px;">← Go to Intake</a>
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

  // Live update the inline $ amounts in the price section
  function refreshPriceDisplay() {
    const lumpSumText = document.querySelector("#tb-total")?.textContent || "$0.00";
    const lumpSumN = Number(String(lumpSumText).replace(/[^0-9.-]/g, "")) || 0;
    // The Total Base Bid is TAX-INCLUSIVE — Kyle's sheet bakes sales tax
    // (on materials) and KS remodel tax (on labor/service) into D88. So the
    // customer total IS the lump sum; we must NOT add tax on top (the old
    // code did `lump + county_rate*lump`, which double-counted tax and used
    // the wrong base + rate). One price, tax included.
    const fb = (state.computed_bid && state.computed_bid.full_bid) || {};
    const includedTax = Number(fb.total_taxes || 0);
    document.getElementById("lump-sum-display").textContent = fmtUSD(lumpSumN);
    document.getElementById("tax-amount-display").textContent = fmtUSD(includedTax);
    document.getElementById("total-display").textContent = fmtUSD(lumpSumN);
    // Single-price presentation: remodel tax is folded into the lump sum,
    // so keep the separate remodel-tax line hidden.
    const rr = document.getElementById("remodel-tax-row");
    if (rr) rr.style.display = "none";
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
      const rooms = Array.isArray(state.rooms) ? state.rooms : [];
      const priced = rooms.filter(r => r && r.bid && Number(r.bid.total) > 0);
      const stateName = ((form.querySelector("[name='state_name']") || {}).value || "Kansas").trim() || "Kansas";
      const meta = (r) => {
        const total = Number(r.bid.total) || 0;
        const remodel = Number(r.bid.remodel) || 0;
        const isBase = !!r.is_base;
        const diff = total - (Number(r.base_total) || 0);
        return {
          total, isBase,
          taxPhrase: remodel > 0
            ? `(${esc(stateName)} Remodel Tax AND material sales tax INCLUDED)`
            : "(material sales tax INCLUDED)",
          heading: isBase ? "Base Bid" : String(r.name || "").replace(/[: ]+$/, ""),
          sysOn: r.show_system !== false,
          diffOn: !!r.show_diff,
          diffText: diff > 0 ? `+${fmtUSD(diff)} more than the base bid`
                  : diff < 0 ? `${fmtUSD(-diff)} less than the base bid` : "",
        };
      };

      // DOCUMENT preview (read-only) — re-rendered when a control changes.
      function renderRoomsPreview() {
        if (!roomsBlock) return;
        roomsBlock.innerHTML = !priced.length ? "" :
          `<p style="margin:10pt 0 4pt;font-weight:bold;">Pricing options (per sheet)</p>` +
          priced.map((r) => {
            const m = meta(r);
            const autoNotes = Array.isArray(r.notes_auto) ? r.notes_auto : [];
            const manual = Array.isArray(r.notes_manual) ? r.notes_manual : [];
            let h = `<div style="margin:0 0 10pt;border-left:3px solid #c8102e;padding-left:8px;">`;
            h += `<p style="margin:0;"><strong>${esc(m.heading)}:</strong></p>`;
            h += `<p style="margin:0;"><strong>${fmtUSD(m.total)}</strong> – Epoxy flooring as described above <em>${m.taxPhrase}</em></p>`;
            if (m.sysOn && r.system_desc) h += `<p style="margin:0 0 0 14px;color:#555;">• ${esc(r.system_desc)}</p>`;
            if (!m.isBase && m.diffOn && m.diffText) h += `<p style="margin:0 0 0 14px;color:#555;">• ${esc(m.diffText)}</p>`;
            h += autoNotes.concat(manual).map(n => `<p style="margin:0 0 0 14px;color:#555;">• ${esc(n)}</p>`).join("");
            h += `</div>`;
            return h;
          }).join("");
      }
      renderRoomsPreview();

      // LEFT controls panel (toggles + notes)
      if (optsPanel) {
        if (!priced.length) {
          optsPanel.hidden = true;
          optsPanel.innerHTML = "";
        } else {
          optsPanel.hidden = false;
          optsPanel.innerHTML =
            `<h3>Pricing options</h3>` +
            `<p class="op-hint">Choose what prints for each sheet.</p>` +
            priced.map((r, i) => {
              const m = meta(r);
              const manual = (Array.isArray(r.notes_manual) ? r.notes_manual : []).join("\n");
              let h = `<div class="op-row">`;
              h += `<div class="op-name">${esc(m.heading)} <span class="op-price">${fmtUSD(m.total)}</span></div>`;
              h += `<label><input type="checkbox" class="opt-system" data-room-idx="${i}" ${m.sysOn ? "checked" : ""}> Show system &amp; scope</label>`;
              if (!m.isBase) h += `<label><input type="checkbox" class="opt-diff" data-room-idx="${i}" ${m.diffOn ? "checked" : ""}> Show difference vs. base bid</label>`;
              h += `<label class="op-notes">Notes (one per line)` +
                   `<textarea data-room-idx="${i}" class="room-notes" rows="2">${esc(manual)}</textarea></label>`;
              h += `</div>`;
              return h;
            }).join("");

          const persistOpt = (r) => {
            if (!state.tab_opts || typeof state.tab_opts !== "object") state.tab_opts = {};
            if (r.id) state.tab_opts[r.id] = { show_system: r.show_system !== false, show_diff: !!r.show_diff };
            TW.setState({ rooms: state.rooms, tab_opts: state.tab_opts });
          };
          optsPanel.querySelectorAll("textarea.room-notes").forEach(ta => {
            ta.addEventListener("input", () => {
              const r = priced[Number(ta.dataset.roomIdx)];
              if (r) { r.notes_manual = ta.value.split("\n").map(s => s.trim()).filter(Boolean); TW.setState({ rooms: state.rooms }); renderRoomsPreview(); }
            });
          });
          optsPanel.querySelectorAll("input.opt-system").forEach(cb => {
            cb.addEventListener("change", () => {
              const r = priced[Number(cb.dataset.roomIdx)];
              if (r) { r.show_system = cb.checked; persistOpt(r); renderRoomsPreview(); }
            });
          });
          optsPanel.querySelectorAll("input.opt-diff").forEach(cb => {
            cb.addEventListener("change", () => {
              const r = priced[Number(cb.dataset.roomIdx)];
              if (r) { r.show_diff = cb.checked; persistOpt(r); renderRoomsPreview(); }
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
    const stateName  = (form.querySelector("[name='state_name']") || {}).value || "Kansas";
    altBlock.innerHTML =
      `<p style="margin:14pt 0 6pt;font-weight:bold;color:#c8102e;border-top:1px solid #c8102e;padding-top:10pt;">` +
      `ALTERNATE SYSTEM — ${esc(altLabel)}</p>` +
      `<p style="margin:0 0 6pt;"><strong>${fmtUSD(altFloor)}</strong> – ${esc(altLabel)} ` +
      `<em>(sales &amp; ${esc(stateName)} remodel tax INCLUDED)</em></p>` +
      (altRemodel > 0
        ? `<p style="margin:0 0 6pt;"><strong><mark>${fmtUSD(altRemodel)}</mark></strong> – ${esc(stateName)} Remodel Tax</p>`
        : "") +
      `<p style="margin:0 0 6pt;"><strong>${fmtUSD(altTotal)}</strong> – Total</p>`;
  }

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

  // Resolve the proposal's state name (fills the Direct-Epoxy template's
  // "{{state_name}} Remodel Tax" line). Priority: a trailing 2-letter code
  // in city_state -> the intake `state` field -> default Kansas. The KS
  // remodel tax is Kansas-specific and Treadwell is KC-based, so Kansas is
  // the safe last resort rather than leaving the line as "– Remodel Tax".
  const stateField = form.querySelector("[name='state_name']");
  if (stateField && !stateField.value) {
    const map = {"MO":"Missouri","KS":"Kansas","IA":"Iowa","NE":"Nebraska",
                 "OK":"Oklahoma","AR":"Arkansas","IL":"Illinois"};
    const m = String(state.city_state || "").match(/[,\s]+([A-Za-z]{2})\s*$/);
    const code = (m ? m[1] : (state.state || "KS")).toUpperCase();
    stateField.value = map[code] || code;
  }

  // Recalc on input changes
  form.addEventListener("input", refreshPriceDisplay);

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
      state_name:         safe(mergedValues.state_name),
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
