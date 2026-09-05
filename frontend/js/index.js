// Externalized from index.html (CSP: drop script-src 'unsafe-inline'). Do not add inline scripts.
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
    { key: "hard_bid", label: "Hard bid", scope: ["epoxy", "polish", "combo", "gyp"],
      why: "Competitive bid. Tightens the margin the sheet applies.",
      def: false, cells: ["Epoxy!B5", "Polish!B5"], on: "Yes", off: "No" },
    { key: "prevailing_wage", label: "Prevailing wage", scope: ["epoxy", "polish", "combo", "gyp"],
      why: "Raises every labour line to the prevailing rate.",
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
      why: "One kit per 3,500 sq ft. On by default, which is how the sheet ships.",
      def: true,  cells: ["Polish!E29"], on: "Yes", off: "No" },
    { key: "remove_existing_jf", label: "Remove existing joint filler", scope: ["polish", "combo"],
      why: "Adds a fourth hand to the joint-filler crew.",
      def: false, cells: ["Polish!F29"], on: "Yes", off: "No", needs: "joint_filler" },
    { key: "bulk_discount", label: "Bulk material discount", scope: ["epoxy", "combo"],
      why: "Swaps six epoxy material rows onto bulk pricing.",
      def: false, cells: ["Epoxy!D41"], on: "BULK Discount ON", off: "Bulk Discount OFF" },
  ];

  // Four traps, all read out of the template rather than assumed:
  //
  //  * Polish!B4 and Polish!B5 hold their OWN Yes/No, so local and hard bid have to
  //    be written to both tabs or the polish side keeps the template default.
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

  function condScope() {
    return (form.querySelector("[name='work_type']:checked") || {}).value || "epoxy";
  }
  function condApplies(c) { return c.scope.indexOf(condScope()) !== -1; }

  /** On means "the ON literal is sitting in the first cell". Read back off cell_values
   *  rather than off a key of our own, so a flag set by the AI autofill or typed
   *  straight into the estimate grid shows up here as the switch it is -- and a draft
   *  returning through Back shows what the sheet actually says, not what this page
   *  last thought. */
  function hydrateConditions() {
    const cv = (TW.getState() || {}).cell_values || {};
    for (let i = 0; i < CONDITIONS.length; i++) {
      const c = CONDITIONS[i];
      const cell = cv[c.cells[0]];
      condState[c.key] = (cell == null || cell === "")
        ? c.def
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
  function conditionCells() {
    const out = Object.assign({}, (TW.getState() || {}).cell_values || {});
    for (let i = 0; i < CONDITIONS.length; i++) {
      const c = CONDITIONS[i];
      const applies = condApplies(c);
      for (let j = 0; j < c.cells.length; j++) {
        if (applies) out[c.cells[j]] = condState[c.key] ? c.on : c.off;
        else delete out[c.cells[j]];
      }
    }
    return out;
  }

  function saveConditions() { TW.setState({ cell_values: conditionCells() }); }

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
    saveConditions();
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

  hydrateConditions();
  form.querySelectorAll("[name='work_type']").forEach(
    r => r.addEventListener("change", syncConditionsToWorkType));
  renderConditions();
  if (county) {
    county.hydrate(TW.getState() || {});   // a county chosen on the estimate screen shows here
    county.wire(true);                     // true: this page has no delegated click router
    county.load();                         // async; a failed fetch costs the rows, not the form
    paintCounty();                         // hydrate() may have found a pick to reveal
  }

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
  // Photon is a free public address database; we query it as the user
  // types and fill Address / City / State / Zip. No API key, nothing to
  // host, no scraping — just a fetch to a public endpoint.
  const addrInput   = document.getElementById("address-input");
  const addrResults = document.getElementById("address-results");
  const businessInput = document.getElementById("business-input");
  const businessResults = document.getElementById("business-results");
  const cityInput   = document.getElementById("city-input");
  const stateInput  = document.getElementById("state-input");
  const zipInput    = document.getElementById("zip-input");

  const STATE_ABBR = {Alabama:"AL",Alaska:"AK",Arizona:"AZ",Arkansas:"AR",California:"CA",
    Colorado:"CO",Connecticut:"CT",Delaware:"DE","District of Columbia":"DC",Florida:"FL",
    Georgia:"GA",Hawaii:"HI",Idaho:"ID",Illinois:"IL",Indiana:"IN",Iowa:"IA",Kansas:"KS",
    Kentucky:"KY",Louisiana:"LA",Maine:"ME",Maryland:"MD",Massachusetts:"MA",Michigan:"MI",
    Minnesota:"MN",Mississippi:"MS",Missouri:"MO",Montana:"MT",Nebraska:"NE",Nevada:"NV",
    "New Hampshire":"NH","New Jersey":"NJ","New Mexico":"NM","New York":"NY","North Carolina":"NC",
    "North Dakota":"ND",Ohio:"OH",Oklahoma:"OK",Oregon:"OR",Pennsylvania:"PA","Rhode Island":"RI",
    "South Carolina":"SC","South Dakota":"SD",Tennessee:"TN",Texas:"TX",Utah:"UT",Vermont:"VT",
    Virginia:"VA",Washington:"WA","West Virginia":"WV",Wisconsin:"WI",Wyoming:"WY"};

  const fmtLine1 = p => [p.housenumber, p.street || p.name].filter(Boolean).join(" ") || p.name || "";

  function showAddrMsg(text) {
    addrResults.innerHTML = `<div class="addr-row addr-msg">${text}</div>`;
    addrResults.classList.add("open");
  }

  function renderAddr(features) {
    const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]));
    // Photon often returns several OSM objects for the same address — dedupe
    // on the displayed text so we don't show identical rows.
    const seen = new Set(), items = [];
    for (const f of features) {
      const p = f.properties;
      const l1 = fmtLine1(p);
      const l2 = [p.city || p.county, STATE_ABBR[p.state] || p.state, p.postcode].filter(Boolean).join(", ");
      if (!l1 && !l2) continue;
      const key = (l1 + "|" + l2).toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      items.push({ f, l1, l2 });
    }
    if (!items.length) { showAddrMsg("No matches — keep typing the address"); return; }
    addrResults.innerHTML = items.map((it, i) =>
      `<div class="addr-row" data-idx="${i}"><div class="addr-l1">${esc(it.l1)}</div><div class="addr-l2">${esc(it.l2)}</div></div>`
    ).join("");
    addrResults.classList.add("open");
    addrResults.querySelectorAll(".addr-row").forEach(row =>
      row.addEventListener("click", () => pickAddr(items[+row.dataset.idx].f)));
  }

  function pickAddr(f) {
    const p = f.properties;
    addrInput.value  = fmtLine1(p);
    cityInput.value  = p.city || p.county || "";
    stateInput.value = STATE_ABBR[p.state] || (p.state || "").slice(0, 2).toUpperCase();
    zipInput.value   = p.postcode || "";
    addrResults.classList.remove("open");
  }

  function fillLocation(p) {
    addrInput.value  = fmtLine1(p);
    cityInput.value  = p.city || p.county || "";
    stateInput.value = STATE_ABBR[p.state] || (p.state || "").slice(0, 2).toUpperCase();
    zipInput.value   = p.postcode || "";
  }

  function renderBusinesses(features) {
    const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]));
    const seen = new Set(), items = [];
    for (const f of features) {
      const p = f.properties || {};
      const name = (p.name || "").trim();
      const address = fmtLine1(p);
      const locality = [p.city || p.county, STATE_ABBR[p.state] || p.state, p.postcode].filter(Boolean).join(", ");
      if (!name || (!address && !locality)) continue;
      const key = (name + "|" + address + "|" + locality).toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      items.push({ f, name, address: [address, locality].filter(Boolean).join(", ") });
    }
    if (!items.length) {
      businessResults.innerHTML = '<div class="addr-row addr-msg">No business matches — enter the address manually</div>';
      businessResults.classList.add("open");
      return;
    }
    businessResults.innerHTML = items.map((it, i) =>
      `<div class="addr-row" data-idx="${i}"><div class="addr-l1">${esc(it.name)}</div><div class="addr-l2">${esc(it.address)}</div></div>`
    ).join("");
    businessResults.classList.add("open");
    businessResults.querySelectorAll(".addr-row").forEach(row => row.addEventListener("click", () => {
      // Keep the name Kyle entered (it can include a job description); this is
      // only a location lookup, not a replacement for the project name.
      fillLocation(items[+row.dataset.idx].f.properties || {});
      businessResults.classList.remove("open");
    }));
  }

  let addrTimer = null, addrSeq = 0;
  addrInput.addEventListener("input", () => {
    const q = addrInput.value.trim();
    if (addrTimer) clearTimeout(addrTimer);
    if (q.length < 4) { addrResults.classList.remove("open"); return; }
    addrTimer = setTimeout(async () => {
      const seq = ++addrSeq;
      try {
        // Bias toward the Kansas City metro (lat/lon); filter to US results.
        const url = `https://photon.komoot.io/api/?q=${encodeURIComponent(q)}&limit=6&lang=en&lat=39.0997&lon=-94.5786`;
        const data = await (await fetch(url)).json();
        if (seq !== addrSeq) return;  // a newer keystroke already fired
        const feats = (data.features || []).filter(f => (f.properties.countrycode || "US") === "US");
        renderAddr(feats);
      } catch { addrResults.classList.remove("open"); }
    }, 300);  // debounce
  });
  let businessTimer = null, businessSeq = 0;
  if (businessInput && businessResults) businessInput.addEventListener("input", () => {
    const q = businessInput.value.trim();
    if (businessTimer) clearTimeout(businessTimer);
    if (q.length < 3) { businessResults.classList.remove("open"); return; }
    businessTimer = setTimeout(async () => {
      const seq = ++businessSeq;
      try {
        // Free OSM business/location search, biased toward the Kansas City metro.
        const url = `https://photon.komoot.io/api/?q=${encodeURIComponent(q)}&limit=6&lang=en&lat=39.0997&lon=-94.5786`;
        const data = await (await fetch(url)).json();
        if (seq !== businessSeq) return;
        renderBusinesses((data.features || []).filter(f => (f.properties.countrycode || "US") === "US"));
      } catch { businessResults.classList.remove("open"); }
    }, 300);
  });
  document.addEventListener("click", e => {
    if (!addrInput.contains(e.target) && !addrResults.contains(e.target))
      addrResults.classList.remove("open");
    if (businessInput && businessResults && !businessInput.contains(e.target) && !businessResults.contains(e.target))
      businessResults.classList.remove("open");
  });

  form.addEventListener("submit", (e) => {
    e.preventDefault();
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
