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
// The county is the sixth thing that moves the price and the only one that is not a toggle. It
// writes FOUR TOP-LEVEL keys — `county`, `county_tax_rate`, `county_remodel_rate`, `county_notes` —
// which are the live estimate screen's own, deliberately, so a project that picked its county on
// either screen is understood by both. See the county block for why the field is here at all.
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
    // The county note quotes the Remodel tax toggle by name, so it is stale the moment one of these
    // flips. Repainted for any of the five rather than just that one: it costs a string, and a
    // note that describes the price has to describe the price as it is now.
    renderCountyNote();
    saveSoon();
  }

  /** Fill this form from a verbal-intake extraction, and report what was actually applied.
   *
   *  PUBLISHED RATHER THAN REACHED INTO. js/polish-verbal.js owns the panel and the dictation; the
   *  conditions live here, behind toggleCondition, which also repaints the switch, refreshes the
   *  county note that quotes it by name, and schedules the save. A panel that flipped
   *  M.conditions directly would leave all three of those undone and the screen disagreeing with
   *  the model it just changed.
   *
   *  Only ever sets what the SERVER accepted. Everything it hands over has already cleared the
   *  evidence gate in backend/verbal_intake.py; nothing here re-decides that, and nothing here
   *  touches a county key — the picker below is the only thing allowed to write those four. */
  function applyVerbal(res) {
    var filled = [], applied = [];
    var fields = (res && res.fields) || {};
    Object.keys(fields).forEach(function (key) {
      var el = form ? form.querySelector('[name="' + key + '"]') : null;
      if (!el) return;
      el.value = fields[key];
      // Through a real input event, so the form's own change handling runs — the same path a
      // keystroke takes. Setting .value alone leaves the draft unsaved and the page unaware.
      el.dispatchEvent(new Event("input", { bubbles: true }));
      filled.push(key);
    });
    var conditions = (res && res.conditions) || {};
    Object.keys(conditions).forEach(function (key) {
      if (!isCondition(key)) return;
      var item = conditions[key];
      if (!item || typeof item.value !== "boolean") return;
      // Toggled only when it DIFFERS. Calling toggleCondition unconditionally would flip a switch
      // that was already right, which is the one way this could turn a correct form wrong.
      if (!!M.conditions[key] !== item.value) toggleCondition(key);
      applied.push(key);
    });
    return { filled: filled, applied: applied };
  }

  window.TWPolishIntake = { applyVerbal: applyVerbal };

  // ── the county, and the real remodel-tax rate ────────────────────────────────
  //
  // WHY THIS FIELD EXISTS. Kyle's workbook hardcodes the remodel tax at 10% (Polish!B75). That is
  // not a real rate anywhere. Kansas charges sales tax on commercial remodel LABOUR at the state
  // rate plus the COUNTY portion only — 6.5% + 1.475% = 7.975% in Johnson County, less in most
  // others. Hanz, 2026-08-18: "For the Remodel tax please use the real state tax or city tax, DONT
  // USE 10%". The live estimating tool has looked this up per county since 2026-06-02, and
  // markupChain() now takes `remodel_rate` as an input, so the beta needs somewhere to capture it.
  //
  // THE FOUR KEYS ARE THE CONTRACT, and they are the live estimate screen's own (see the county
  // picker in js/estimate-review.js): `county`, `county_tax_rate`, `county_remodel_rate`,
  // `county_notes`. Written under the same names and in the same "<Name> County, ST" shape so a
  // project that picked its county on either screen is understood by both — js/polish-estimate.js
  // reads `county_remodel_rate` off the draft without caring which screen set it, and the live
  // screen parses `county` back apart to restore its own pill.
  //
  // The list is NEVER hardcoded here. It comes from /api/reference/counties, which serves
  // backend/reference_tax.py — rates pulled one by one from the KS DOR Address Tax Rate Locator.
  // A copy in this file would be a second table to keep in step with the DOR, silently wrong.
  var COUNTY_LIMIT = 12;               // rows offered at once; the estimator types, not scrolls
  var counties = [];                   // from the API, at runtime
  var countyMatches = [];              // what the current search text matched, in rendered order
  var countyHighlight = -1;            // keyboard cursor into countyMatches, -1 for none
  // The pick, held as the four DRAFT keys rather than as an API row: hydration reads exactly these
  // four off the draft, so what a reopened project shows is what a fresh pick would have written.
  var countyPick = null;

  async function loadCounties() {
    try {
      if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready;
      var res = await fetch(TW.resolveApiBase() + "/api/reference/counties",
                            { headers: TW.authHeaders() });
      var body = await res.json();
      counties = (body && body.counties) || [];
    } catch (e) {
      // Reference data, not the draft. A failed load costs the search box its rows; it must not
      // stop an estimator filling in the rest of the form.
      counties = [];
    }
    // A list that arrived while somebody was already typing has to reach the rows they are looking
    // at, or the box keeps saying "no county matches" until the next keystroke.
    var input = $("county-input");
    if (!countyPick && input && input.value) renderCountyResults(input.value);
    return counties;
  }

  /** The two-letter state out of "Johnson County, KS".
   *
   *  Read off the name rather than inferred from the rate: BOTH states have a Johnson County, and
   *  "this row carries no remodel_rate" is not the same claim as "this job is in Missouri". */
  function countyStateOf(pick) {
    var m = /,\s*([A-Za-z]{2})\s*$/.exec(String((pick && pick.county) || ""));
    return m ? m[1].toUpperCase() : "";
  }

  /** What one row charges, in the picker. B.pct is the estimate page's own formatter, so the rate
   *  promised here and the rate shown on the markup row read identically. */
  function countyRowRate(c) {
    return c && c.remodel_rate != null
      ? "remodel " + B.pct(c.remodel_rate)
      : "remodel labour exempt";
  }

  function filterCounties(query) {
    var q = String(query == null ? "" : query).trim().toLowerCase();
    if (!q) return [];
    var hits = [];
    for (var i = 0; i < counties.length && hits.length < COUNTY_LIMIT; i++) {
      var c = counties[i];
      // Name, state, "Johnson County, KS" and the notes, which is where the cities are: an
      // estimator types the town on the drawing set, not the county nobody puts on a plan.
      var hay = (c.name + " county, " + c.state + " " + (c.notes || "")).toLowerCase();
      if (hay.indexOf(q) >= 0) hits.push(c);
    }
    return hits;
  }

  /** Close the list AND put the box back to what is actually saved.
   *
   *  The restore is the load-bearing half. The chosen county is shown IN the input, so a search the
   *  estimator abandoned half-typed — Escape, or a click somewhere else on the page — would leave
   *  "wyando" sitting in a field whose draft says Johnson County. The field would be telling them
   *  the wrong county, which is the one thing this whole control exists to get right.
   *
   *  Deliberately NOT called from renderCountyResults: emptying the box to type a different county
   *  must not have the old one typed back in on top of them. */
  function closeCountyResults() {
    var box = $("county-results");
    if (box) box.hidden = true;
    countyHighlight = -1;
    var input = $("county-input");
    if (input) input.value = countyPick ? countyPick.county : "";
  }

  function renderCountyResults(query) {
    var box = $("county-results");
    if (!box) return;
    var typed = String(query == null ? "" : query).trim();
    countyMatches = filterCounties(typed);
    countyHighlight = -1;
    if (!countyMatches.length) {
      box.innerHTML = typed
        ? '<div class="c-empty">No county matches &ldquo;' + esc(typed) + '&rdquo;</div>' : "";
      box.hidden = !typed;
      return;
    }
    box.innerHTML = countyMatches.map(function (c, i) {
      return '<div class="c-row" id="county-row-' + i + '" data-county="' + i + '">' +
        '<span class="c-name">' + esc(c.name) + ' County, ' + esc(c.state) + '</span>' +
        '<span class="c-rate">' + esc(countyRowRate(c)) + '</span></div>';
    }).join("");
    box.hidden = false;
  }

  /** Move the keyboard cursor. Class-only, like paintCondition: re-rendering the list would throw
   *  away the caret in the box the estimator is still typing in. */
  function paintCountyHighlight() {
    for (var i = 0; i < countyMatches.length; i++) {
      var el = $("county-row-" + i);
      if (el) el.className = "c-row" + (i === countyHighlight ? " on" : "");
    }
  }

  /** The four keys a save writes. Nulls when nobody has picked, which is also what Clear means. */
  function countyKeys() {
    if (!countyPick) {
      return { county: "", county_tax_rate: null, county_remodel_rate: null, county_notes: "" };
    }
    return { county: countyPick.county,
             county_tax_rate: countyPick.county_tax_rate,
             county_remodel_rate: countyPick.county_remodel_rate,
             county_notes: countyPick.county_notes };
  }

  function pickCounty(c) {
    if (!c || !c.name) return;
    countyPick = {
      // The live screen's shape, because its own restore path parses this string back apart.
      county: c.name + " County, " + c.state,
      county_tax_rate: c.rate == null ? null : c.rate,
      // MISSOURI ROWS HAVE NO remodel_rate, and that is correct rather than missing data: Missouri
      // remodel labour is generally exempt. Left null instead of filled in with something.
      county_remodel_rate: c.remodel_rate == null ? null : c.remodel_rate,
      county_notes: c.notes || "",
    };
    // closeCountyResults is what puts the chosen county in the box — one place owns what the field
    // shows, so a pick and an abandoned search cannot disagree about it.
    closeCountyResults();
    renderCountyNote();
    saveSoon();                            // the page's own debounced save, which MERGES
  }

  function clearCounty() {
    countyPick = null;
    countyMatches = [];
    closeCountyResults();                  // which now empties the box, countyPick being null
    renderCountyNote();
    saveSoon();
  }

  /** What the county does to THIS bid, in plain words.
   *
   *  Said out loud because the number is not the one the workbook shows. An estimator who knows
   *  Kyle's sheet expects a flat 10% on this line; naming the real rate, the county it came from,
   *  and the fallback when there is no county is what stops the difference reading as a bug. */
  function countyNoteText() {
    var on = !!(M && M.conditions && M.conditions.remodel_tax);
    var ksRate = "the Kansas state rate of " + B.pct(B.RATES.KS_STATE);
    if (!countyPick) {
      if (!on) {
        return "Remodel tax is off, so the county is not affecting the price yet — it only " +
          "changes the bid on an occupied remodel.";
      }
      return "Remodel tax is on with no county picked, so this bid falls back to " + ksRate +
        " until you choose one.";
    }
    // MISSOURI. The row carries no remodel rate on purpose — MO taxes the contractor on materials
    // and leaves the labour exempt — so this says the rule and then says what to DO, rather than
    // promising a number. Which number a Missouri job would land on if Remodel tax were left on is
    // decided in markupChain and in how js/polish-estimate.js hands it the rate, not here; the one
    // instruction this page can honestly give is to turn the toggle off.
    if (countyStateOf(countyPick) === "MO") {
      return countyPick.county + " — Missouri remodel labour is generally exempt, so no remodel " +
        "tax applies." + (on
          ? " Remodel tax is on anyway: turn it off for a Missouri job unless you know this " +
            "labour is taxable."
          : " Remodel tax is off, so it is not affecting the price either way.");
    }
    var rate = countyPick.county_remodel_rate;
    if (rate == null || !(Number(rate) > 0)) {
      return countyPick.county + " has no remodel rate on file, so " + (on
        ? "this bid uses " + ksRate + "."
        : "Remodel tax would use " + ksRate + " — and the toggle is off, so nothing is added yet.");
    }
    return "Remodel tax " + B.pct(rate) + " · " + countyPick.county + (on
      ? ", on the labour and the markups. Never on materials."
      : " — but the Remodel tax toggle is off, so it is not affecting the price yet.");
  }

  /** Text, not markup: every word of this is composed here, and the only variable in it is a
   *  county name from the server's own table. Nothing to escape and nothing to get wrong. */
  function renderCountyNote() {
    var note = $("county-note");
    if (note) note.textContent = countyNoteText();
    var clear = $("county-clear");
    if (clear) clear.hidden = !countyPick;
  }

  function hydrateCounty() {
    // Straight off the draft, under the live screen's keys: a project that picked its county on
    // the estimate screen has to show that county HERE, or the estimator picks it twice and the
    // second pick is the one that counts.
    countyPick = state.county
      ? { county: String(state.county),
          county_tax_rate: state.county_tax_rate == null ? null : state.county_tax_rate,
          county_remodel_rate:
            state.county_remodel_rate == null ? null : state.county_remodel_rate,
          county_notes: state.county_notes || "" }
      : null;
    countyMatches = [];
    closeCountyResults();                  // which puts the hydrated county into the box
    renderCountyNote();
  }

  function onCountyInput() {
    var input = $("county-input");
    renderCountyResults(input ? input.value : "");
  }

  function onCountyKeydown(e) {
    var key = e && e.key;
    if (!key) return;
    var box = $("county-results");
    var open = !!box && box.hidden === false;
    if (key === "Escape") { if (open) closeCountyResults(); return; }
    if (!open) return;
    if (key === "Enter") {
      // Swallowed whenever the list is open, ALWAYS. This input lives inside the form, and the
      // form's submit handler navigates to the estimate — so an un-prevented Enter would leave the
      // page while the estimator was choosing the row in front of them.
      if (e.preventDefault) e.preventDefault();
      // Nothing highlighted takes the top match: on a list narrowed to one row, Enter means that
      // row rather than "arrow down first".
      if (countyMatches.length) {
        pickCounty(countyMatches[countyHighlight >= 0 ? countyHighlight : 0]);
      }
      return;
    }
    if (key === "ArrowDown") {
      if (e.preventDefault) e.preventDefault();
      countyHighlight = Math.min(countyHighlight + 1, countyMatches.length - 1);
    } else if (key === "ArrowUp") {
      if (e.preventDefault) e.preventDefault();
      countyHighlight = Math.max(countyHighlight - 1, 0);
    } else {
      return;
    }
    paintCountyHighlight();
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

    // The county's four keys ride along as TOP-LEVEL draft keys, not inside polish_estimate: they
    // are the live estimate screen's own, and js/polish-estimate.js reads county_remodel_rate off
    // the draft root. countyKeys() is hydrated from the draft on load, so a project that picked its
    // county on the other screen writes the same values back rather than losing them here.
    TW.setState(Object.assign({}, values, {
      city_state: cs,
      // The beta calculator is polish-only, so intake here says so rather than asking.
      work_type: "polish",
      // Mirrored the way the live intake mirrors it: the Projects list, the bell's due-date
      // reminders and the Dropbox folder date all read `deadline`.
      deadline: values.bid_date || cur.deadline || "",
      polish_estimate: model,
    }, countyKeys()));
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
    hydrateCounty();                        // after the toggles: the note quotes Remodel tax
    $("proj-line").textContent = [state.project_name, state.city && state.state
      ? state.city + ", " + state.state : ""].filter(Boolean).join(" · ") || "Untitled project";
  }

  function onClick(e) {
    var t = e && e.target;
    var near = function (sel) { return t && t.closest ? t.closest(sel) : null; };

    var sw = near("[data-cond]");
    if (sw) { toggleCondition(sw.getAttribute("data-cond")); return; }

    var row = near("[data-county]");
    if (row) {
      // By INDEX into what was rendered, not by name: two counties are called Johnson and they
      // charge different rates.
      pickCounty(countyMatches[parseInt(row.getAttribute("data-county"), 10)]);
      return;
    }

    if (near("#county-clear")) { clearCounty(); return; }

    // Anything else closes the search list — except a click inside the field itself, which is the
    // estimator putting the caret back in the box they are typing into. Marked with an attribute
    // rather than measured against the input: `closest` walks up out of the rendered rows too.
    if (!near("[data-county-keep]")) closeCountyResults();
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
    var input = $("county-input");
    if (input) {
      input.addEventListener("input", onCountyInput);
      input.addEventListener("keydown", onCountyKeydown);
    }
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

    // NOT awaited, and after the reveal: it is reference data for one search box, and the other
    // eight fields must not wait on it. hydrateCounty has already shown whatever county the draft
    // carries — that comes off the draft, not out of this list — and loadCounties repaints the
    // rows if the estimator started typing while it was in flight.
    loadCounties();
  }

  boot();
})();
