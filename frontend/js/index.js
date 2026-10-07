// Externalized from index.html (CSP: drop script-src 'unsafe-inline'). Do not add inline scripts.

  // ── a v2 draft does not open on this form ─────────────────────────────────────
  // Estimating Tool v2 has its own intake (polish-intake.html), and a project priced there has no
  // spreadsheet behind it. This form's Continue goes to the spreadsheet, so a v2 draft opened here
  // and continued from here walked into the Excel grid. Every link that opens a project on this form
  // (the board and the Projects page, the bell, Leads, the step pills, Back from the estimate step)
  // ends at this page, so the guard stands HERE, at the destination, and not at each of them.
  //
  // ONLY WHEN THE LOAD NAMES A PROJECT (?d= or ?edit=). "?new=1" on its own is somebody starting a
  // project on this form, and gets it. (shared.js then puts the new project's id in the address bar,
  // so a RELOAD of that page names a project, and a project that has become v2 since goes on to v2.)
  // And only a blob that is THIS project's (TW.isThisDraft): a link opened on a machine whose storage
  // holds another project runs this once on that blob while shared.js fetches the right one and
  // reloads, and the reload runs this again.
  //
  // `replace`, so Back does not return to a page that would only bounce again, and the throw stops the
  // rest of this script, so nothing below runs or saves on a page that is already leaving.
  {
    const q = new URLSearchParams(window.location.search || "");
    const here = TW.getState();
    if ((q.has("d") || q.has("edit")) && TW.isV2Draft(here) && TW.isThisDraft(here)) {
      window.location.replace(TW.withDraft("/polish-intake.html"));
      throw new Error("index: a v2 draft belongs on polish-intake.html");
    }
  }

  // Restore previous state if user clicked Back from screen 2
  const form = document.getElementById("intake-form");

  // ── Per-system Scope fields (fixed at two) ────────────────────────
  // The estimate sheet is a two-system model, so we always render exactly
  // two {Epoxy SF, Polish SF, Cove LF} groups. System 1 keeps the legacy
  // field names so the existing estimate-cell mappings keep working;
  // System 2 uses suffixed names and is optional (leave blank to skip it).
  const systemsContainer = document.getElementById("systems-container");

  function systemFieldNames(k) {
    return k === 1
      ? { epoxy: "system_1_sf", polish: "polish_sf",      cove: "cove_1_lf" }
      : { epoxy: `system_${k}_sf`, polish: `polish_${k}_sf`, cove: `cove_${k}_lf` };
  }

  function renderSystems(n) {
    n = Math.max(1, Math.min(6, parseInt(n, 10) || 1));
    // Preserve anything already typed before we rebuild the markup.
    const prev = {};
    systemsContainer.querySelectorAll("input[name]").forEach(i => { prev[i.name] = i.value; });
    let html = "";
    for (let k = 1; k <= n; k++) {
      const f = systemFieldNames(k);
      const label = k === 2 ? `System ${k} (optional)` : `System ${k}`;
      const tag = n > 1 ? `<div class="system-tag">${label}</div>` : "";
      // data-scope drives which work types each field belongs to (see
      // syncScopeToWorkType). Asking an epoxy job for Polish floor SF, or a polish
      // job for cove, is how an intake form teaches people to ignore it.
      html += `
        <div class="system-block">
          ${tag}
          <div class="row">
            <label data-scope="epoxy">Epoxy floor SF
              <input type="number" name="${f.epoxy}" min="0" step="1" value="0">
            </label>
            <label data-scope="polish">Polish floor SF
              <input type="number" name="${f.polish}" min="0" step="1" value="0">
            </label>
          </div>
          <div class="row">
            <label data-scope="cove">Cove LF (epoxy)
              <input type="number" name="${f.cove}" min="0" step="1" value="0">
            </label>
          </div>
        </div>`;
    }
    systemsContainer.innerHTML = html;
    // Restore preserved values into the rebuilt fields.
    systemsContainer.querySelectorAll("input[name]").forEach(i => {
      if (prev[i.name] != null && prev[i.name] !== "") i.value = prev[i.name];
    });
  }

  // Always two systems (System 2 optional), then hydrate the whole form.
  renderSystems(2);
  TW.writeForm(form, TW.getState());

  // Gyp jobs use 3 SF buckets instead of the epoxy/polish system fields — show
  // the right scope inputs for the selected work type (and on a restored draft).
  const gypBox = document.getElementById("gyp-sf-container");
  // The SECOND Continue — the one that goes to the polish beta calculator instead of the
  // spreadsheet. Shown for polish jobs only; see the comment on the button in index.html.
  const betaBtn = document.getElementById("beta-continue");
  const thicknessRow = document.getElementById("thickness-row");

  // Which quantity fields belong to which work type. Cove is an epoxy detail, so a
  // polish-only job never shows it (Hanz, 2026-08-06).
  const SCOPE_BY_WORK_TYPE = {
    epoxy:  ["epoxy", "cove"],
    polish: ["polish"],
    combo:  ["epoxy", "polish", "cove"],
    gyp:    [],                     // gyp uses its own three SF buckets instead
  };

  function syncScopeToWorkType() {
    const wt = (form.querySelector("[name='work_type']:checked") || {}).value || "epoxy";
    const isGyp = wt === "gyp";
    if (gypBox) gypBox.style.display = isGyp ? "" : "none";
    if (systemsContainer) systemsContainer.style.display = isGyp ? "none" : "";

    // Hide, never remove: the field names are what saved drafts and the estimate-cell
    // mappings key on, and a value typed under Combo should still be there if somebody
    // switches back. Keeping it out of the SHEET is estimate-review's job, which seeds
    // only the fields that apply to the chosen work type.
    const allowed = SCOPE_BY_WORK_TYPE[wt] || SCOPE_BY_WORK_TYPE.epoxy;
    (systemsContainer ? systemsContainer.querySelectorAll("[data-scope]") : []).forEach((el) => {
      el.style.display = allowed.includes(el.getAttribute("data-scope")) ? "" : "none";
    });
    // A row whose every field is hidden would otherwise leave an empty gap.
    (systemsContainer ? systemsContainer.querySelectorAll(".row") : []).forEach((row) => {
      const fields = row.querySelectorAll("[data-scope]");
      const anyShown = [...fields].some((el) => el.style.display !== "none");
      if (fields.length) row.style.display = anyShown ? "" : "none";
    });
    // The beta calculator prices POLISH and nothing else, so its door only exists on a polish
    // job. Toggled from here rather than from a listener of its own so it can never disagree
    // with the fields on screen, and hidden rather than removed for the same reason as those
    // fields: switching work type away and back has to bring the same door back, listener and
    // all. Deliberately the LAST thing in this function — test_intake_work_type_scope.py reads
    // a fixed-length window from the top of it.
    if (betaBtn) betaBtn.style.display = wt === "polish" ? "" : "none";
    // Thickness is a RESIN question. Polish has a grind and a sheen, not a thickness, and gyp
    // carries its own three thicknesses on the proposal screen -- so asking here would put a
    // number on the cover letter that describes neither job. Appended after the beta button
    // rather than beside the gyp box for the reason the comment above gives: this function's
    // opening is read as a fixed-length window by test_intake_work_type_scope.py.
    if (thicknessRow) thicknessRow.style.display = (wt === "epoxy" || wt === "combo") ? "" : "none";
  }
  form.querySelectorAll("[name='work_type']").forEach(r => r.addEventListener("change", syncScopeToWorkType));
  syncScopeToWorkType();

  // == Job conditions =========================================================
  // The polish beta's step 2, moved onto the live intake and grown from five
  // switches to ten. Hanz, 2026-09-02: "For the polish beta we want to use the
  // existing intake form v1 (not the beta). The v2 is just add it with the
  // toggle buttons."
  //
  // WHY THESE WRITE cell_values AND NOT polish_estimate. `polish_estimate.version
  // == 2` is the ONLY flag that routes a project to the beta calculator
  // (drafts.py:857 -> projects.js:538), so a form writing conditions in there faces
  // a fork with no safe default: stamp the version and every spreadsheet polish bid
  // starts resuming on the beta intake, or leave it off and migrateModel's
  // unversioned branch discards the conditions on arrival. Writing cell_values
  // sidesteps the fork entirely -- and it is where these flags already live: the AI
  // autofill has written the same keys since it shipped (estimate-review.js:3601 ->
  // main.py:4776), and estimate-review's grid reads and writes them. One store, and
  // the sheet the customer is billed from is the thing being set rather than a copy.
  //
  // AND WHY NEITHER Continue HANDLER IS TOUCHED. Flipping a switch calls
  // TW.setState({cell_values}) on the spot. setState merges by top-level key, so the
  // two handlers' `TW.setState({...values, ...})` leaves cell_values alone without
  // mentioning it. That matters more than it looks: test_beta_intake_routing.py runs
  // BOTH handlers on one form and compares the saved blob key for key precisely
  // because they are duplicated copies of one composition -- so the cheapest way to
  // keep them identical is to give them nothing new to say.
  //
  // Data, not markup, exactly as the beta had it (polish-intake.js:59-70). Four of
  // these are new questions, and that shape is why they cost four lines not forty.
  //
  // EVERY CONDITION WRITES BOTH STATES, never a blank for "off". Polish!C17 is
  // IF(B10="New",0.05,0.15), so an empty B10 takes the Reno branch and triples the
  // patch material rate with nothing on screen to show it. Same discipline applied
  // to all ten so no future one gets it wrong.
  const CONDITIONS = [
    { key: "local", label: "Local job", scope: ["epoxy", "polish", "combo", "gyp"],
      why: "Under 70 miles. Off means travel and lodging get added.",
      def: true,  cells: ["Epoxy!B4", "Polish!B4"], on: "Yes", off: "No" },
    // NO HARD BID. Hanz, 2026-10-03: "We also need to remove the hard bid discount. Even on
    // active projects and direct projects." The switch wrote Epoxy!B5/Polish!B5, the cell Kyle's
    // automatic 2.5% / 4% give-back reads; nothing may set it now (estimate_writer
    // HARD_BID_FLAG_CELLS). A discount the estimator types into the sheet's own row still works.
    { key: "prevailing_wage", label: "Prevailing wage", scope: ["epoxy", "polish", "combo", "gyp"],
      why: "Raises every labor line to the prevailing rate.",
      def: false, cells: ["Epoxy!D5"], on: "Yes", off: "No" },
    { key: "taxable", label: "Taxable", scope: ["epoxy", "polish", "combo", "gyp"],
      why: "Adds sales tax. The bid you see already includes it.",
      // FOUR cells, not one, and this is the whole of Kyle's tax-exempt bug on the
      // base tabs. The sales-tax rate is `=IF($B$6="no",0,0.09475)` on every priced
      // sheet — SHEET-relative, so each sheet reads its OWN flag. Polish, Seal,
      // 'Seal (+Jnts)' and 'Epoxy blank' mirror Epoxy!B6 and are handled by writing
      // it; Leveling!B6, 'Gyp (USG 1-8")'!B8 and 'Gyp (FR)'!B8 are independent
      // LITERALS and were never written at all, so every tax-exempt gypsum and
      // Leveling bid carried 9.475% it should not have. The other three gyp variants
      // mirror the gyp base, so writing that one carries them — and they stay out of
      // this list for the same reason Polish!B6 does. Epoxy!B6 stays FIRST:
      // hydrateConditions reads cells[0] to paint the switch.
      def: true,  cells: ["Epoxy!B6", "Leveling!B6", 'Gyp (USG 1-8")!B8', "Gyp (FR)!B8"],
      on: "Yes", off: "No" },
    { key: "remodel_tax", label: "Remodel tax", scope: ["epoxy", "polish", "combo", "gyp"],
      why: "Occupied remodel. Taxed at the county rate — pick the county below.",
      def: false, cells: ["Epoxy!D6"], on: "Yes", off: "No" },
    { key: "reno", label: "Renovation", scope: ["epoxy", "polish", "combo"],
      why: "Existing floor, not new construction. Triples the patch material rate.",
      def: false, cells: ["Epoxy!B10", "Polish!B10"], on: "Reno", off: "New" },
    { key: "dye", label: "Dye", scope: ["polish", "combo"],
      why: "Two coats of dye across the polished area.",
      def: false, cells: ["Polish!E25"], on: "Yes", off: "No" },
    { key: "joint_filler", label: "Joint filler", scope: ["polish", "combo"],
      // OFF BY DEFAULT SINCE 2026-09-19, and it was `def: true` until then -- "On by default,
      // which is how the sheet ships", which was a faithful reading of Kyle's template
      // (Polish!E29 ships "Yes") and the wrong default for a tool that prices the line itself.
      // The beta charges a $500 kit per 3,500 sq ft for it, so on a 17,500 SF floor "on by
      // default" was $2,500 nobody had chosen. Hanz's call was all three of these start off.
      //
      // FLIPPED HERE TOO, AND THAT IS THE POINT. bid-model's freshModel() is the other
      // place this answer is stated, and the two must agree: this screen writes Polish!E29 the
      // instant any of the ten switches is touched, so a `true` left here would put the $2,500
      // back into Kyle's workbook on the live intake path while the beta showed it off. Two
      // copies of one fact is what this repo keeps paying for; they are kept in step by hand
      // because the two screens' condition lists are genuinely different shapes -- this one
      // carries ten questions with per-job answers, that one carries nine model keys.
      why: "One kit per 3,500 sq ft. Off until the job needs it.",
      def: false, cells: ["Polish!E29"], on: "Yes", off: "No" },
    { key: "remove_existing_jf", label: "Remove existing joint filler", scope: ["polish", "combo"],
      why: "Adds a fourth hand to the joint-filler crew.",
      def: false, cells: ["Polish!F29"], on: "Yes", off: "No", needs: "joint_filler" },
    { key: "bulk_discount", label: "Bulk material discount", scope: ["epoxy", "combo"],
      why: "Swaps six epoxy material rows onto bulk pricing.",
      def: false, cells: ["Epoxy!D41"], on: "BULK Discount ON", off: "Bulk Discount OFF" },
  ];

  // Four traps, all read out of the template rather than assumed:
  //
  //  * Polish!B4 holds its OWN Yes/No, so local has to be written to both tabs or
  //    the polish side keeps the template default.
  //  * Polish!D5, B6 and D6 are the formulas =Epoxy!D5 / =Epoxy!B6 / =Epoxy!D6.
  //    Writing those three would replace a live reference with a literal and
  //    decouple the tabs for good, so the POLISH tab is never written for them and
  //    follows on its own. That is not the same as "Epoxy-only": Taxable is a
  //    literal on Leveling!B6, 'Gyp (USG 1-8")'!B8 and 'Gyp (FR)'!B8 as well, and
  //    writing Epoxy alone left every tax-exempt gyp and Leveling bid carrying
  //    9.475%. See the taxable row above. Prevailing wage and remodel tax really are
  //    Epoxy-only: Epoxy!D5 / Epoxy!D6 are the only literals either one has, and
  //    every other sheet's — including both gyp D7/D8 and Leveling's — is =Epoxy!.
  //  * Epoxy!D41 is compared against V136 / V137 by all six of its consumers
  //    (IF($D$41=$V$136,...)), and those two cells read "BULK Discount ON" and
  //    "Bulk Discount OFF" -- mixed case, and inconsistent with each other. Any
  //    other casing silently takes the OFF branch, with no error anywhere.
  //  * Polish!H36 is NOT the second dye switch it was taken for: it holds the label
  //    "Dye?". Dye writes the material cell E25 only; the crew days stay the
  //    estimator's call, which is the decision already recorded for this.
  const condBox = document.getElementById("conditions");
  const condState = {};

  // ── The admin-set answers for three of these same ten questions ────────────
  //
  // dye / joint_filler / remove_existing_jf ALSO ship on the Polish beta's own Takeoff step
  // (frontend/js/bid-model.js CONDITION_CELLS), where their default is no longer the
  // literal below but GET /api/condition-defaults (backend/condition_defaults.py) -- Hanz,
  // twice: "I told you to remove the built-in and keep and make everything editable in the
  // takeoff." THIS PAGE carried its own hardcoded c.def for the same three keys and never
  // asked that endpoint, so the moment an estimator touched ANY of the ten switches below,
  // conditionCells() wrote EVERY in-scope condition's cells from condState -- baking the stale
  // hardcoded default into Kyle's workbook, even though the Defaults tab showed the admin's
  // real choice as saved. Fixed by threading the same admin answer into hydrateConditions()
  // below, for these three keys and no others -- the other seven are answered per job from the
  // lead notes and the AI autofill, not a company-wide setting, and stay exactly as they were.
  const ADMIN_CONDITION_KEYS = { dye: true, joint_filler: true, remove_existing_jf: true };

  /** The library's admin-set answer for each of the three keys above, as { key: boolean },
   *  or {} when the read cannot answer. NEVER THROWS.
   *
   *  The SAME posture loadConditionDefaults already has on the Polish beta pages
   *  (polish-intake.js, polish-estimate.js): `condition_defaults` is unapplied on both
   *  databases as of this commit (see condition_defaults.py), so today this answers with {}
   *  everywhere and every one of the three falls back to its own c.def below, exactly as it
   *  does today. An unreachable endpoint must not block or break this screen -- every work
   *  type's estimator opens it every day. */
  async function loadConditionDefaults() {
    try {
      // Awaited BEFORE the fetch: at script load the sign-in has not settled, so the request went
      // out without its auth header, took a 401, and the admin's answers were silently ignored
      // (the same race PR #124 closed for /api/default-notes).
      if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready;
      const res = await fetch(TW.resolveApiBase() + "/api/condition-defaults",
                              { headers: TW.authHeaders() });
      const body = await res.json();
      const rows = (body && body.conditions instanceof Array) ? body.conditions : [];
      const out = {};
      for (let i = 0; i < rows.length; i++) {
        const r = rows[i];
        if (r && r.key) out[r.key] = !!r.on;
      }
      return out;
    } catch (e) {
      return {};
    }
  }
  // KICKED OFF HERE, well before hydrateConditions() first runs near the bottom of this
  // section, so this request overlaps the rest of this script's synchronous setup instead of
  // queueing behind it -- the same "fetch early, non-blocking" shape loadLaborDefaults and
  // loadConditionDefaults already use on the Polish beta pages.
  const conditionDefaultsPromise = loadConditionDefaults();

  function condScope() {
    return (form.querySelector("[name='work_type']:checked") || {}).value || "epoxy";
  }
  function condApplies(c) { return c.scope.indexOf(condScope()) !== -1; }

  /** Where Taxable / Remodel tax are read and written, once the estimate screen has split them.
   *
   *  A NEW project starts every sheet with this page's two answers: the cells listed above, which
   *  the estimate screen then copies onto every flag-block sheet the first time it opens the draft
   *  (estimate-review.js init() step 3c). From then on each sheet keeps its own answers (Hanz,
   *  2026-09-30, "Stay independent"), and `state.tax_flags_per_sheet` says so. So on a split draft
   *  these two switches are the BASE bid's: its own two cells, as the estimate screen snapshots
   *  them on state.priced_tabs[].flag_cells. Writing the four literal cells instead would reset
   *  Leveling and 'Gyp (FR)' -- options -- to Epoxy's answer on every flip of any switch here.
   *
   *  null means "not split": use c.cells. An empty list means split but no base cell is known:
   *  write nothing rather than guess. */
  function splitFlagCells(c) {
    if (c.key !== "taxable" && c.key !== "remodel_tax") return null;
    const s = TW.getState() || {};
    if (!s.tax_flags_per_sheet) return null;
    const flag = c.key === "taxable" ? "taxable" : "remodel";
    const tabs = s.priced_tabs instanceof Array ? s.priced_tabs : [];
    const byId = new Map();
    tabs.forEach((t) => { if (t && t.id) byId.set(t.id, t); });
    const wt = condScope();
    const ids = byId.has(s.base_tab_id) ? [s.base_tab_id]
      : wt === "gyp" ? ['Gyp (USG 1-8")'] : wt === "polish" ? ["Polish"]
      : wt === "combo" ? ["Epoxy", "Polish"] : ["Epoxy"];
    const out = [];
    ids.forEach((id) => {
      const fc = byId.has(id) && byId.get(id).flag_cells;
      // Only a real "Sheet!A1" address: this string becomes a key in cell_values.
      if (fc && typeof fc[flag] === "string" && /^[^!]+![A-Z]{1,3}[0-9]{1,5}$/.test(fc[flag])) {
        out.push(fc[flag]);
      }
    });
    return out;
  }
  function condCells(c) { return splitFlagCells(c) || c.cells; }

  /** On means "the ON literal is sitting in the first cell". Read back off cell_values
   *  rather than off a key of our own, so a flag set by the AI autofill or typed
   *  straight into the estimate grid shows up here as the switch it is -- and a draft
   *  returning through Back shows what the sheet actually says, not what this page
   *  last thought. */
  function hydrateConditions(adminDefaults) {
    const ad = adminDefaults || {};
    const cv = (TW.getState() || {}).cell_values || {};
    for (let i = 0; i < CONDITIONS.length; i++) {
      const c = CONDITIONS[i];
      const cell = cv[condCells(c)[0]];
      if (cell == null || cell === "") {
        // Admin default only for the three it exists for, and only when nobody -- the AI
        // autofill, the estimate grid, or a previous visit -- has already answered this cell.
        condState[c.key] = (ADMIN_CONDITION_KEYS[c.key] &&
          Object.prototype.hasOwnProperty.call(ad, c.key)) ? ad[c.key] : c.def;
      } else {
        condState[c.key] = String(cell).trim().toLowerCase() === String(c.on).trim().toLowerCase();
      }
    }
  }

  /** The two split tax switches only, re-read off the cells they now write. With no explicit base
   *  the base moves with the work type (a combo's Epoxy + Polish, a polish job's Polish, a gyp
   *  job's gyp base), and condState would keep the last base's answer: the switch shows it, and
   *  the next flip writes it onto the new base's own sheet. The same read hydrateConditions makes,
   *  so a work-type change shows what a reload would. Unsplit drafts and the other switches are
   *  left exactly as they are. */
  function rehydrateSplitFlags() {
    const cv = (TW.getState() || {}).cell_values || {};
    for (let i = 0; i < CONDITIONS.length; i++) {
      const c = CONDITIONS[i];
      const split = splitFlagCells(c);
      if (!split) continue;
      const cell = cv[split[0]];
      condState[c.key] = (cell == null || cell === "") ? c.def
        : String(cell).trim().toLowerCase() === String(c.on).trim().toLowerCase();
    }
  }

  function switchHtml(c) {
    const on = !!condState[c.key];
    const inert = !!(c.needs && !condState[c.needs]);
    const why = inert
      ? c.why + " Not affecting the price while Joint filler is off."
      : c.why;
    return '<div class="sw' + (on ? " on" : "") + (inert ? " inert" : "") +
      '" id="cond-' + c.key + '" data-cond="' + c.key + '" role="switch" tabindex="0"' +
      ' aria-checked="' + (on ? "true" : "false") + '">' +
      '<span class="track"></span><span><span class="t">' + c.label + '</span>' +
      '<span class="c">' + why + '</span></span></div>';
  }

  function renderConditions() {
    if (condBox) condBox.innerHTML = CONDITIONS.filter(condApplies).map(switchHtml).join("");
    // Painted from here rather than from its own listeners: every caller of this
    // function -- a toggle flip, a work-type change, the boot -- is a moment the
    // county's own sentence can have stopped being true, since it quotes the Remodel
    // tax toggle by name. One choke point, so the two cannot disagree.
    paintCounty();
  }

  /** The cells for the conditions ON SCREEN, merged over whatever cell_values holds.
   *
   *  MERGE, never replace. cell_values also carries the AI autofill's flags and every
   *  cell the estimator edited by hand on the grid; a fresh object would drop all of it.
   *
   *  Out-of-scope cells are DELETED, not left behind. A job typed as polish and then
   *  switched to epoxy would otherwise carry Polish!E25 = "Yes" into a bid with no
   *  polish in it -- the same reasoning the two Continue handlers already apply to the
   *  gyp SF buckets, and the reason this runs on a work-type change and not just a flip. */
  function conditionCells(flipped) {
    const out = Object.assign({}, (TW.getState() || {}).cell_values || {});
    for (let i = 0; i < CONDITIONS.length; i++) {
      const c = CONDITIONS[i];
      const applies = condApplies(c);
      // On a split draft the base's two tax answers are written by their OWN switch only: every
      // other save here would restate them, and on a combo that restates Epoxy's onto Polish.
      const split = splitFlagCells(c);
      if (split && c.key !== flipped) continue;
      const cells = split || c.cells;
      for (let j = 0; j < cells.length; j++) {
        const k = cells[j];
        if (k === "__proto__" || k === "constructor" || k === "prototype") continue;
        if (applies) out[k] = condState[c.key] ? c.on : c.off;
        else delete out[k];
      }
    }
    return out;
  }

  function saveConditions(flipped) { TW.setState({ cell_values: conditionCells(flipped) }); }

  /** Has anything written one of these cells yet -- this page, the grid, or the AI
   *  autofill? Asked off cell_values rather than tracked in a flag of our own, so a
   *  draft coming back through Back answers it correctly on the first render. */
  function conditionsTouched() {
    const cv = (TW.getState() || {}).cell_values || {};
    for (let i = 0; i < CONDITIONS.length; i++) {
      const cells = CONDITIONS[i].cells;
      for (let j = 0; j < cells.length; j++) if (cells[j] in cv) return true;
    }
    return false;
  }

  function toggleCondition(key) {
    let found = null;
    for (let i = 0; i < CONDITIONS.length; i++) if (CONDITIONS[i].key === key) found = CONDITIONS[i];
    if (!found || !condApplies(found)) return;   // a stray data-cond invents nothing
    condState[key] = !condState[key];
    // Re-render rather than repaint the one switch: turning Joint filler off has to
    // grey out Remove existing joint filler and say why, and that is a second row.
    renderConditions();
    const again = document.getElementById("cond-" + key);
    if (again && again.focus) again.focus();     // the re-render threw the caret away
    saveConditions(key);
  }

  if (condBox) {
    condBox.addEventListener("click", (e) => {
      const sw = e.target.closest ? e.target.closest("[data-cond]") : null;
      if (sw) toggleCondition(sw.getAttribute("data-cond"));
    });
    // KEYBOARD, which the beta advertised and never wired: its switches carried
    // role="switch" tabindex="0" and a comment about being keyboard-reachable, and
    // wire() bound a delegated click and nothing else -- so Space and Enter on a
    // focused toggle did nothing at all. A control that announces itself to a screen
    // reader as a switch and then ignores the two keys that operate one is worse
    // than a plain checkbox would have been.
    condBox.addEventListener("keydown", (e) => {
      if (e.key !== " " && e.key !== "Enter" && e.key !== "Spacebar") return;
      const sw = e.target.closest ? e.target.closest("[data-cond]") : null;
      if (!sw) return;
      e.preventDefault();                        // Space would scroll the page
      toggleCondition(sw.getAttribute("data-cond"));
    });
  }

  /** Work type changed, so a different set of questions applies.
   *
   *  Its own listener rather than a call inside syncScopeToWorkType(): that
   *  function's last line is deliberately last because test_intake_work_type_scope.py
   *  reads a fixed-length window from the top of it. Running second is also the
   *  better failure order -- if this throws, the scope fields and the beta button
   *  have already been set correctly. */
  function syncConditionsToWorkType() {
    rehydrateSplitFlags();
    renderConditions();
    // Save ONLY if these cells are already in play -- because the alternative is
    // that merely picking a work type on a blank form starts writing to the draft.
    // Ten flags on a project with no name yet is a row nobody asked to create, and
    // test_beta_intake_routing.py counts saves to prove the beta button is not a way
    // round the required-field check; an ambient write from a radio would read as
    // exactly that. Once anything HAS been written -- a switch flipped here, or the
    // seven flags the AI autofill sets -- the cleanup has to run, or a job typed as
    // polish and then switched to epoxy carries Polish!E25 = "Yes" into a bid with no
    // polish in it.
    if (conditionsTouched()) saveConditions();
  }
  // ── The county, which is a job condition because Remodel tax is ────────────
  //
  //  Kyle's workbook charges a flat 10% for remodel tax, which is not a real rate
  //  anywhere. Kansas charges the state 6.5% plus the county portion -- 7.975% in
  //  Johnson County -- so the bid has to know WHICH county. Hanz, 2026-08-18:
  //  "For the Remodel tax please use the real state tax or city tax, DONT USE 10%".
  //
  //  SHARED, NOT COPIED. js/county-picker.js is the polish beta's own picker lifted
  //  out of a page that is being retired; the estimate screen has a third copy welded
  //  to the workbook-cell machinery, deliberately left alone. This mount is what stops
  //  a fourth being written.
  //
  //  A pick writes the four top-level draft keys the estimate screen already reads, so
  //  neither Continue handler is touched: TW.setState merges at the top level, and
  //  #county-input carries no `name`, so TW.readForm never sweeps the search text into
  //  the answers. test_beta_intake_routing.py compares what the two handlers save key
  //  for key, and this change is invisible to both of them.
  const county = window.TWCounty ? window.TWCounty.mount({
    remodelTaxOn: () => !!condState.remodel_tax,
    // The picker owns the four keys; the page owns when they are saved. Same discipline
    // as saveConditions(): setState merges, so nothing else in the draft moves.
    //
    // Repainted here as well, because choose() and clear() are the two moments hasPick()
    // changes -- and hasPick() is half of what decides whether the field is on screen.
    // Without this, clearing a county while Remodel tax is off would leave the field
    // showing an empty search box with nothing left to account for.
    onChange: () => { TW.setState(county.keys()); paintCounty(); },
  }) : null;

  /** Show the field when it can matter, and when it already holds an answer.
   *
   *  The second half is the one that is easy to miss: hiding a picked county because
   *  somebody turned Remodel tax off would leave a rate in the draft with nothing on
   *  screen to show it, which is how a bid gets a county nobody remembers choosing.
   *  So a set county stays visible and the note says plainly that it is not affecting
   *  the price -- the same rule the picker's own wording follows. */
  function paintCounty() {
    const field = document.getElementById("county-field");
    if (!field) return;
    // No module means the script did not load; the field stays hidden rather than
    // showing an inert search box that can never return a row.
    field.hidden = !county || !(condState.remodel_tax || county.hasPick());
    if (county) county.renderNote();
  }

  form.querySelectorAll("[name='work_type']").forEach(
    r => r.addEventListener("change", syncConditionsToWorkType));
  // SEQUENCED, not just started: conditionDefaultsPromise never throws (see
  // loadConditionDefaults above), so this await settles quickly either way, and it is what
  // keeps the very first paint of dye / joint filler / remove-existing joint filler correct --
  // rather than correct only by the time something gets saved. Nothing else in this script
  // waits on it: the work-type listener above is already live, and everything below this IIFE
  // keeps running immediately.
  (async function hydrateAndRenderConditions() {
    const adminDefaults = await conditionDefaultsPromise;
    hydrateConditions(adminDefaults);
    renderConditions();
    if (county) {
      county.hydrate(TW.getState() || {});   // a county chosen on the estimate screen shows here
      county.wire(true);                     // true: this page has no delegated click router
      county.load();                         // async; a failed fetch costs the rows, not the form
      paintCounty();                         // hydrate() may have found a pick to reveal
    }
  })();

  // Default the bid date to today so users don't have to think about it.
  const bidInput = form.querySelector("[name='bid_date']");
  if (bidInput && !bidInput.value) {
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, "0");
    const d = String(now.getDate()).padStart(2, "0");
    bidInput.value = `${y}-${m}-${d}`;
  }

  // ── Address autocomplete (keyless — OpenStreetMap via Photon) ──────
  // Moved to js/address-lookup.js so the beta polish intake shares it. Same behaviour.
  window.TWAddress.mount({
    address:  document.getElementById("address-input"),
    business: document.getElementById("business-input"),
    city:     document.getElementById("city-input"),
    state:    document.getElementById("state-input"),
    zip:      document.getElementById("zip-input"),
  });

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    // A draft that became v2 while this page sat open (another tab priced it in Estimating Tool v2)
    // has no spreadsheet to go to, and this form is older than the draft: saving it would put these
    // values, work type included, over the v2 project. So nothing is saved, and the draft goes to the
    // v2 intake, where it lives. The load guard at the top cannot see this case, the draft was not v2
    // when the page loaded.
    const nowHere = TW.getState();
    if (TW.isV2Draft(nowHere) && TW.isThisDraft(nowHere)) {
      window.location.assign(TW.withDraft("/polish-intake.html"));
      return;
    }
    const values = TW.readForm(form);
    // Keep a combined "City, ST" so the estimate sheet (C3), proposal
    // ({{city_state}}) and tax lookup keep working unchanged. Zip is new
    // and stored separately.
    const cs = [values.city, (values.state || "").toUpperCase()].filter(Boolean).join(", ");
    // Non-gyp jobs clear the gyp SF buckets to "" (NOT delete — setState merges,
    // and "" is skipped by the estimate seeds + the .xlsx writer). Keeps a draft
    // toggled off Gyp from carrying stale gyp SFs into an epoxy/polish estimate.
    if ((values.work_type || "epoxy") !== "gyp") {
      values.gyp_soft_sf = ""; values.gyp_hard_sf = ""; values.gyp_corridor_sf = "";
    }
    // Bid date is now the single project date. Mirror it into `deadline` so the
    // Projects list, the notification bell's due-date reminders, and the Dropbox
    // folder date (all of which read `deadline`) keep tracking the bid date.
    // Fixed at two systems — the estimate sheet's model.
    TW.setState({
      ...values,
      city_state: cs,
      work_type: values.work_type || "epoxy",
      deadline: values.bid_date || values.deadline || "",
      num_systems: 2,
    });
    window.location.assign(TW.withDraft("/estimate-review.html"));
  });

  // ── the beta door: same save, different step 2 ────────────────────────────
  // The handler above belongs to the SPREADSHEET workflow and keeps /estimate-review.html for
  // every work type. This one saves the identical state and then walks into the polish beta.
  //
  // Its own copy of the composition, deliberately: the submit handler is the live path for
  // epoxy, combo and gyp bids and is not being restructured for the sake of the beta.
  // test_beta_intake_routing.py runs BOTH handlers on one form and compares the saved state key
  // for key, so the two cannot drift apart quietly.
  if (betaBtn) betaBtn.addEventListener("click", () => {
    // type="button" never triggers the browser's required-field check, which is the only thing
    // making Continue refuse a project with no name and no bid date. Without this the beta door
    // would be the way to skip validation the spreadsheet path enforces.
    if (form.reportValidity && !form.reportValidity()) return;
    const values = TW.readForm(form);
    const cs = [values.city, (values.state || "").toUpperCase()].filter(Boolean).join(", ");
    // A no-op on a polish job (the only work type that sees this button), kept so the two
    // handlers save byte-for-byte the same blob.
    if ((values.work_type || "epoxy") !== "gyp") {
      values.gyp_soft_sf = ""; values.gyp_hard_sf = ""; values.gyp_corridor_sf = "";
    }
    TW.setState({
      ...values,
      city_state: cs,
      work_type: values.work_type || "epoxy",
      deadline: values.bid_date || values.deadline || "",
      num_systems: 2,
    });
    // withDraft, not a bare path: shared.js's anchor rewriter only covers the four wizard pages
    // (_WIZARD_PATH), so a literal href would open the beta with no project.
    window.location.assign(TW.withDraft("/polish-intake.html"));
  });
