// The BETA polish intake form. Externalized (CSP: no inline scripts). Do not add inline scripts.
//
// WHY THERE ARE TWO INTAKE FORMS.
//
// Hanz, 2026-08-17: "The conditions we move them to the intake form (For Beta Only). Intake form
// of Beta and Active projects should be separate for now, since this is for testing." So this is
// not a replacement for index.html — it is a deliberately small test harness for the beta polish
// calculator, carrying the fields that calculator needs plus the five job-condition toggles that
// used to be its step 2.
//
// It is TRIMMED on purpose. The live intake asks for work type, audience, two systems' worth of
// SF, gyp buckets, phones, architect and notes; a beta that reproduced all of that would have to
// be kept in step with it for no benefit, and half those fields mean nothing to a polish-only
// test. Anything typed on the live form still arrives here — the field NAMES are the live form's,
// so both write the same keys on the same draft.
//
// WHAT IT WRITES, AND WHAT IT MUST NOT WRITE.
//
// The five toggles land in `state.polish_estimate.conditions`, where js/polish-bid-core.js's
// markupChain() reads them by key to decide the hard-bid discount, the labour escalation and the
// two taxes. The takeoff and labor rows live under the SAME key, so every save merges — see save().
//
// The model it writes is always a WELL-FORMED v2 (migrateModel stamps the version), and that
// matters twice over: an unversioned blob used to have its conditions discarded by the calculator
// on the very next page, and backend/drafts.py reads `polish_estimate.version` to decide that a
// project resumes on THIS intake rather than the spreadsheet one.
//
// And it never writes any of that onto a live customer bid: js/polish-sandbox.js settles which
// draft this page may touch before a single value is rendered, let alone typed.
(function () {
  "use strict";

  var SB = window.TWPolishSandbox;
  var B = window.TWPolishBid;      // owns the model shape, and the keys markupChain reads
  var $ = function (id) { return document.getElementById(id); };

  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  };

  // The five job conditions, as they read in the beta calculator's old step 2 — same labels, same
  // plain-English "what this does" line, same toggle shape.
  //
  // The cell chips (B4, B5, D5, B6, D6) are deliberately NOT here. They came off the calculator's
  // panel, where Kyle could check a field against the workbook he already trusts. This page writes
  // the draft, not the workbook, so a cell name here would point at a cell it never touches.
  //
  // THE KEYS ARE THE CONTRACT. They have to match the conditions in js/polish-bid-core.js exactly:
  // markupChain() looks each one up BY KEY and a miss reads as `false`, so a typo here is a
  // prevailing-wage job quietly priced at standard rates with nothing on screen to show it.
  // Pinned by test_polish_intake_page.py, which compares the two lists.
  var CONDITIONS = [
    { key: "local", label: "Local job",
      why: "Under 70 miles. Off means travel and lodging get added." },
    { key: "hard_bid", label: "Hard bid",
      why: "Competitive bid. Tightens the margin the sheet applies." },
    { key: "prevailing_wage", label: "Prevailing wage",
      why: "Raises every labour line to the prevailing rate." },
    { key: "taxable", label: "Taxable",
      why: "Adds sales tax. The bid you see already includes it." },
    { key: "remodel_tax", label: "Remodel tax",
      why: "Occupied remodel. Adds the county remodel rate on top." }
  ];

  // Taken FROM the pricing engine rather than restated: most jobs are local and taxable, and the
  // other three are the exceptions somebody has to know about. Sourcing them here means this page
  // and the calculator cannot open a new project on two different sets of defaults.
  var DEFAULT_CONDITIONS = B.freshModel().conditions;

  // The draft this page is working ON, and the model derived from it. Reassigned together by
  // adoptModel(), because the page can switch drafts mid-boot: opening a real bid here works on a
  // test copy instead (see enterSandbox), and rendering the copy with the real project's values
  // still in the boxes is the same silent mix-up in a different direction.
  var state = {};
  var M = null;
  var form = null;

  /** Point the page at one draft's blob.
   *
   *  Handed to enterSandbox as its adopt callback, so it also runs when the sandbox moves the page
   *  onto a test copy. NOTHING is rendered until it has.
   *
   *  A v1 model — {areas: […]} with no `version` — carries `conditions` in this same shape, so it
   *  is read as-is; the defaults only fill what a model does not state. */
  function adoptModel(blob) {
    state = blob || {};
    M = B.migrateModel(state.polish_estimate);
    M.conditions = Object.assign({}, DEFAULT_CONDITIONS, M.conditions || {});
  }

  function isCondition(key) {
    for (var i = 0; i < CONDITIONS.length; i++) if (CONDITIONS[i].key === key) return true;
    return false;
  }

  // ── the toggles ─────────────────────────────────────────────────────────────
  function switchHtml(c) {
    var on = !!M.conditions[c.key];
    return '<div class="sw' + (on ? " on" : "") + '" id="cond-' + esc(c.key) +
      '" data-cond="' + esc(c.key) + '" role="switch" tabindex="0" aria-checked="' +
      (on ? "true" : "false") + '">' +
      '<span class="track"></span><span><span class="t">' + esc(c.label) + '</span>' +
      '<span class="c">' + esc(c.why) + '</span></span></div>';
  }

  function renderConditions() {
    $("conditions").innerHTML = CONDITIONS.map(switchHtml).join("");
  }

  /** Repaint ONE switch rather than the block.
   *
   *  Re-rendering the whole list would work here, but it throws away focus — and these are
   *  keyboard-reachable (role="switch", tabindex), so tabbing through them would dump the caret
   *  back to the top of the page on every flip. */
  function paintCondition(key) {
    var el = $("cond-" + key);
    if (!el) return;
    var on = !!M.conditions[key];
    el.className = "sw" + (on ? " on" : "");
    el.setAttribute("aria-checked", on ? "true" : "false");
  }

  function toggleCondition(key) {
    if (!isCondition(key)) return;          // only the five; a stray data-cond invents nothing
    M.conditions[key] = !M.conditions[key];
    paintCondition(key);
    saveSoon();
  }

  // ── saving ──────────────────────────────────────────────────────────────────
  var saveTimer = null;

  /** Debounced, same 600ms the calculator uses: a toggle is one click, but the text boxes above
   *  are typed into and every save is a PUT of the whole blob. */
  function saveSoon() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(function () { saveTimer = null; save(); }, 600);
  }

  function save() {
    if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; }
    var values = form ? TW.readForm(form) : {};
    // Same combined "City, ST" the live intake keeps, because the estimate sheet (C3), the
    // proposal's {{city_state}} and the tax lookup all read that one field.
    var cs = [values.city, (values.state || "").toUpperCase()].filter(Boolean).join(", ");

    var cur = TW.getState();
    var existing = cur.polish_estimate || {};
    // MERGE, NEVER REPLACE. The calculator's takeoff and labor rows live under this same key.
    // Writing { conditions: … } over the top of it to record one toggle would silently delete a
    // finished takeoff — and the estimator would not find out until the bid came back at zero.
    // Only `conditions` is this page's to state.
    //
    // Through migrateModel, so what lands is a well-formed v2 model with its version stamped: a
    // brand-new project has no polish_estimate at all, and a bare { conditions } blob was read as
    // "unversioned, unrecognised" — the calculator replaced it with defaults and the Projects page
    // sent the project back to the spreadsheet intake. Both of those were silent.
    var model = B.migrateModel(existing);
    model.conditions = Object.assign({}, model.conditions, M.conditions);

    TW.setState(Object.assign({}, values, {
      city_state: cs,
      // The beta calculator is polish-only, so intake here says so rather than asking.
      work_type: "polish",
      // Mirrored the way the live intake mirrors it: the Projects list, the bell's due-date
      // reminders and the Dropbox folder date all read `deadline`.
      deadline: values.bid_date || cur.deadline || "",
      polish_estimate: model,
    }));
  }

  // ── the form ────────────────────────────────────────────────────────────────
  function hydrate() {
    TW.writeForm(form, state);
    var bid = form.querySelector("[name='bid_date']");
    if (bid && !bid.value) {
      // Today, so nobody has to think about it. Same default as the live intake.
      var now = new Date();
      var m = String(now.getMonth() + 1);
      var d = String(now.getDate());
      bid.value = now.getFullYear() + "-" + (m.length < 2 ? "0" + m : m) + "-" +
        (d.length < 2 ? "0" + d : d);
    }
    renderConditions();
    $("proj-line").textContent = [state.project_name, state.city && state.state
      ? state.city + ", " + state.state : ""].filter(Boolean).join(" · ") || "Untitled project";
  }

  function onClick(e) {
    var t = e.target;
    var sw = t && t.closest ? t.closest("[data-cond]") : null;
    if (!sw) return;
    toggleCondition(sw.getAttribute("data-cond"));
  }

  function onSubmit(e) {
    if (e && e.preventDefault) e.preventDefault();
    save();                                  // synchronously, not on the 600ms timer
    // withDraft, not a bare path: on a test copy the id shared.js has stored may still be the
    // REAL project's, and this button must carry the draft the page was actually editing.
    window.location.assign(TW.withDraft("/polish-estimate.html"));
  }

  /** Listeners go on only after the sandbox has settled. A toggle flipped before the page knows
   *  which draft it may write to is the live-bid write the sandbox exists to prevent, arrived at
   *  by racing it instead of by skipping it. */
  function wire() {
    document.addEventListener("click", onClick);
    if (form) form.addEventListener("submit", onSubmit);
  }

  // ── boot ────────────────────────────────────────────────────────────────────
  async function boot() {
    try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch (e) {}
    // shared.js is still deciding which draft this page is on (it can even hydrate and reload),
    // and every decision below turns on that id.
    try { await TW.draftReady; } catch (e) {}
    adoptModel(TW.getState());

    // Before the form, before the toggles, before anything can be typed: whatever happens after
    // this line writes to a test project. It returns false when it could not settle that safely,
    // and then the page stays on its loading message rather than risk a real bid.
    if (!(await SB.enterSandbox(adoptModel))) return;

    form = $("intake-form");
    hydrate();
    // shared.js's _WIZARD_PATH excludes the beta pages, so "2 · Estimate" out of this page never
    // gets a ?d= from it at all.
    SB.repointWizardLinks();
    wire();

    $("loading").hidden = true;
    $("main").hidden = false;
  }

  boot();
})();
