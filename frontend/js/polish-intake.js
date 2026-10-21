// The BETA polish intake form. Externalized (CSP: no inline scripts). Do not add inline scripts.
//
// WHY THERE ARE TWO INTAKE FORMS.
//
// Hanz, 2026-08-17: "The conditions we move them to the intake form (For Beta Only). Intake form
// of Beta and Active projects should be separate for now, since this is for testing." So this is
// not a replacement for index.html — it is a deliberately small test harness for the beta polish
// calculator, carrying the fields that calculator needs plus the job-condition toggles that
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
// The toggles land in `state.polish_estimate.conditions`, where js/bid-model.js's
// markupChain() reads them by key to decide the labor escalation and the two taxes. The takeoff
// and labor rows live under the SAME key, so every save merges — see save().
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
  var B = window.TWBidModel;      // owns the model shape, and the keys markupChain reads
  var T = window.TWWorkTypes;     // the one vocabulary: which questions this form asks, and how it words them
  var S = window.TWIntakeScope;   // the intake's quantity fields and the Job type choice, drawn from that vocabulary
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
  // THE KEYS ARE THE CONTRACT. They have to match the conditions in js/bid-model.js exactly:
  // markupChain() looks each one up BY KEY and a miss reads as `false`, so a typo here is a
  // prevailing-wage job quietly priced at standard rates with nothing on screen to show it.
  // Pinned by test_polish_intake_page.py, which compares the two lists.
  //
  // NO "LOCAL JOB" SWITCH (Kyle, 9/18 notes; Hanz, 2026-10-05). Distance decides it now: the Labor
  // step works the driving miles out from the job address and sets the hidden `conditions.local`
  // answer from them (< 70 miles is local). That key is still on the model and still written to
  // Polish!B4 / Epoxy!B4 by conditionCells() -- it is only no longer ASKED here. Because it is not
  // in this list, isCondition("local") is false and a spoken "it is not local" in the verbal panel
  // changes nothing: a person's word does not outrank the miles.
  //
  // READ FROM THE TABLE (js/work-types.js, Phase 7), not typed here: the questions a polish job is asked on
  // this form, in this form's order, with the wording this form uses (`wording.v2Intake` where it words one
  // differently from the live intake: the county box is not "below" here). A row is { key, label, why,
  // ... } and this page reads only those three. NO HARD BID. Hanz, 2026-09-22: "remove all hard bids from
  // the polish intake form. And also on the markups" -- confirmed to mean the Polish beta specifically
  // (its intake, Review step and the Markup admin page), leaving the live v1 Intake, the AI Autofill flag,
  // the verbal-AI parser and pricing.py's own engine untouched; those never read this list. The keys are
  // still the contract with bid-model.js's markupChain(), which no longer offers hard_bid either -- see
  // that file's own note on the removal.
  var CONDITIONS = T.conditionsFor("polish", "v2Intake");

  // Taken FROM the pricing engine rather than restated: most jobs are local and taxable, and the
  // other three are the exceptions somebody has to know about. Sourcing them here means this page
  // and the calculator cannot open a new project on two different sets of defaults.
  var DEFAULT_CONDITIONS = B.freshModel().conditions;

  // NO CARRIED CONDITIONS. Dye, joint filler and remove-existing left this list on 2026-09-16 for
  // the Takeoff step, where the work they describe is described. Renovation was the last one --
  // it never described the work, only a fact about the building ("existing floor, not new
  // construction"), which is why it stayed here rather than moving with them -- and it left
  // entirely on 2026-09-23: Hanz, "Remove Renovation Toggle button from the polish beta intake
  // form," confirmed to mean the toggle AND the cell-write, not a relocation. Every future beta
  // job's downloaded .xlsx now writes Polish!B10 / Epoxy!B10 as "New" unconditionally -- the same
  // literal an untouched Renovation switch already defaulted to, so no download that was correct
  // yesterday becomes wrong today; a job that IS a renovation simply has no way to say so from
  // this screen any more. js/bid-model.js still has no notion of renovation and never did.
  //
  // If a carry-only condition is ever needed again, CARRY_CONDITIONS existed as a parallel array
  // to CONDITIONS with its own `cells`/`on`/`off`/`def` shape (see git history) -- do not
  // reintroduce it as a single-purpose special case a second time.

  /** The spreadsheet cells these five conditions ARE, so this page and the live intake
   *  cannot answer the same question two different ways.
   *
   *  WHY THIS EXISTS AT ALL. As of 2026-09-03 the five toggles also live on the live
   *  intake form (js/index.js), which is now the beta's step 1 -- Hanz: "For the polish
   *  beta we want to use the existing intake form v1 (not the beta). The v2 is just add
   *  it with the toggle buttons." Until this page is retired it still asks the same five
   *  questions one screen later, and without this it answered them from
   *  polish_estimate.conditions -- which a fresh v1 project does not have -- so an
   *  estimator who set Prevailing wage on intake arrived here to find it off.
   *
   *  EXTRACTED AS OF 2026-09-15, having been a deliberate duplicate before that. The old note
   *  here said one shared module was not worth it because test_polish_intake_page.py pins this
   *  page's <script src> list as an exact seven-item sequence, so a sixth file would be a test
   *  move dressed up as a refactor. That trade changed twice over: bid-model.js is ALREADY
   *  in both pages' script lists so nothing new is loaded, and the Review step became a second
   *  writer of these conditions — at which point two copies stopped being a tidiness question and
   *  became the mechanism by which the two screens would disagree about a price.
   *
   *  The live intake (js/index.js) still keeps its own copy and remains the one to edit first;
   *  this page and the Review step now follow it through ONE shared definition rather than two.
   *
   *  THE LOOP THAT READ THEM BACK IS NOT HERE ANY MORE: adoptModel calls B.conditionsFromCells, which
   *  also knows a condition with several cells and a draft split per sheet. This alias is what the page's
   *  harness lifts, and it is the same map that function reads. */
  var CONDITION_CELLS = B.CONDITION_CELLS;

  /** cell_values with every condition's literal written into it, MERGED over what is already
   *  there.
   *
   *  Never a fresh object: cell_values also carries the AI autofill's flags and every
   *  cell the estimator edited by hand on the estimate grid. And never a blank for
   *  "off" -- both literals are written explicitly, because a blank Yes/No cell is not
   *  "No" to Kyle's formulas, it is whatever the IF() defaults to. */
  function conditionCells() {
    // EVERYTHING ON THE MODEL, through the shared writer, so no two screens write the same cell
    // two different ways. That is the engine five AND the three this form no longer renders --
    // dye, joint filler and remove-existing, which moved to the Takeoff step on 2026-09-16.
    //
    // THE SECOND HALF OF THAT SENTENCE IS THE ONE THAT MATTERS HERE. Those three are not asked on
    // this screen any more, and they are still written by it, on every save, because cell_values
    // is what the generated .xlsx is filled from and a save that left them out would blank them.
    // That includes remove_existing_jf's literal while Joint filler is off: it greys out over
    // there because it changes no price, not because its answer stopped existing.
    //
    // `split`: once the estimate screen has split the tax answers per sheet, Taxable and Remodel tax go to
    // the base sheet's own cell and the options' stay as the draft has them (js/work-types.js writeCellsFor).
    var draft = TW.getState() || {};
    return B.conditionCellWrites(M.conditions, draft.cell_values, undefined, T.isSplit(draft));
  }

  // The draft this page is working ON, and the model derived from it. Reassigned together by
  // adoptModel(), because the page can switch drafts mid-boot: opening a real bid here works on a
  // test copy instead (see enterSandbox), and rendering the copy with the real project's values
  // still in the boxes is the same silent mix-up in a different direction.
  var state = {};
  var M = null;
  var form = null;
  // The job type this bid is. Set from the draft by adoptModel (a draft with none, or one v2 cannot price yet,
  // reads as the default) and changed only by pickJobType, which refuses a type the vocabulary has not marked
  // ready. `county` is the shared county control, mounted at boot (mountCounty).
  var JOB = "polish";
  var county = null;

  // WHICH OF THE FIVE THE ESTIMATOR SETTLED THEMSELVES. Hanz, 2026-08-27: the verbal panel must
  // respect the human. The panel is allowed to fill an empty form; it is not allowed to argue with
  // a person. A key that got here by a real click is REPORTED back on the next run ("you set this
  // yourself — left alone") instead of being flipped a second time, because the estimator who
  // corrected the AI once should not have to correct it again after every re-ask.
  //
  // Deliberately NOT persisted to the draft. It is one page visit's worth of "who touched this",
  // and a stale flag on tomorrow's draft would block a fill nobody had objected to.
  //
  // There is deliberately NO matching ledger of what the panel itself set. Its own record is the
  // `applied` list it returns, and a second run is allowed to correct its own first reading — so a
  // stored copy would have had no reader, and freezing keys the AI had touched would make the
  // re-ask pointless.
  var humanConditions = {};

  /** Point the page at one draft's blob.
   *
   *  Handed to enterSandbox as its adopt callback, so it also runs when the sandbox moves the page
   *  onto a test copy. NOTHING is rendered until it has.
   *
   *  A v1 model — {areas: […]} with no `version` — carries `conditions` in this same shape, so it
   *  is read as-is; the defaults only fill what a model does not state. */
  function adoptModel(blob) {
    state = blob || {};
    JOB = S.chosenJobType(state.work_type);
    M = B.migrateModel(state.polish_estimate);
    M.conditions = Object.assign({}, DEFAULT_CONDITIONS, M.conditions || {});
    // THE CELL WINS WHERE THERE IS ONE. A project that came through the live intake has
    // no polish_estimate yet, so migrateModel just handed back the defaults -- and the
    // five choices the estimator actually made are sitting in cell_values. Reading them
    // back here is what stops this screen contradicting the one before it. After this
    // change every write to a condition writes its cell too (see save()), so the cell
    // can never be the staler of the two.
    //
    // THE SHARED READER, not a loop of this page's own: a condition with several cells is answered by the
    // first one that holds an answer, and on a draft the estimate screen has split per sheet the two tax
    // answers are the base sheet's own cell. Both rules live beside the writer (B.conditionsFromCells),
    // because a page that read one way while a save wrote the other would put the wrong answer back.
    M.conditions = B.conditionsFromCells(M.conditions, state.cell_values, T.isSplit(state));
  }

  function isCondition(key) {
    for (var i = 0; i < CONDITIONS.length; i++) if (CONDITIONS[i].key === key) return true;
    return false;
  }

  // ── the toggles ─────────────────────────────────────────────────────────────

  function condOn(key) {
    return !!M.conditions[key];
  }

  // NO `needs`/inert HANDLING. It existed only for remove_existing_jf's dependency on Joint
  // filler while both were carry conditions; that pair moved to the Takeoff step on 2026-09-16
  // and Renovation -- the one entry ever left behind -- named no `needs` of its own. Nothing on
  // CONDITIONS uses it today, pinned by test_polish_intake_page.py, and there is no longer a
  // carry list to justify keeping the machinery for a future entry that has not been written.
  function switchHtml(c) {
    var on = condOn(c.key);
    return '<div class="sw' + (on ? " on" : "") + '" id="cond-' +
      esc(c.key) + '" data-cond="' + esc(c.key) + '" role="switch" tabindex="0" aria-checked="' +
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
    var on = condOn(key);
    el.className = "sw" + (on ? " on" : "");
    el.setAttribute("aria-checked", on ? "true" : "false");
  }

  /** Flip one of the five, and record WHO flipped it.
   *
   *  `fromVerbal` is passed only by applyVerbal. Every other caller — the delegated click, the
   *  keyboard, anything added later — counts as the estimator, which is the safe default in both
   *  directions: forgetting the flag costs the panel one re-fill, while getting it wrong the other
   *  way would let the AI overwrite a decision a person had already made. */
  function toggleCondition(key, fromVerbal) {
    // Only the five this page renders; a stray data-cond invents nothing.
    if (!isCondition(key)) return;
    if (!fromVerbal) humanConditions[key] = true;
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
   *  touches a county key — the picker below is the only thing allowed to write those four.
   *
   *  IT SAVES ITS OWN FILLS, AND STILL HAS TO. wire() now binds an `input` listener that saves any
   *  named field a human types into — but setting `el.value` from script fires no `input` event, so
   *  that listener does not see a single thing this function writes. Do not delete the saveSoon()
   *  below on the grounds that typing is covered now; it is not the same path. Before either
   *  existed, the eight text boxes this fills reached the draft only by accident, when a condition
   *  happened to flip in the same run and its save swept them up.
   *
   *  Returns three lists, and the third one is the point: `respected` names the conditions the
   *  estimator had already settled by hand, which this LEAVES ALONE and asks the panel to say so. */
  function applyVerbal(res) {
    var filled = [], applied = [], respected = [];
    var fields = (res && res.fields) || {};
    Object.keys(fields).forEach(function (key) {
      var el = form ? form.querySelector('[name="' + key + '"]') : null;
      if (!el) return;
      el.value = fields[key];
      // Fired because a programmatic fill should look like a keystroke to anything that IS
      // listening — a later handler, an autofill extension, a test driving the page. It is not
      // what saves the draft: see the note above.
      el.dispatchEvent(new Event("input", { bubbles: true }));
      filled.push(key);
    });
    var conditions = (res && res.conditions) || {};
    Object.keys(conditions).forEach(function (key) {
      // ONLY THE FIVE THIS PAGE RENDERS. Renovation was accepted here too until 2026-09-23, back
      // when it was the one carried key this form still asked; it never actually arrived --
      // backend/verbal_intake.py builds its `conditions` by looping over MONEY_CONDITIONS, four
      // literals, and its prompt never asked for `reno` by name. That gap is moot now: the switch
      // is gone from this page, so there is nothing left to widen the gate for.
      if (!isCondition(key)) return;
      var item = conditions[key];
      if (!item || typeof item.value !== "boolean") return;
      // THE HUMAN WINS. An estimator who corrected this switch after the first run is not asked to
      // correct it again after the re-ask — the panel reports the disagreement instead of settling
      // it. Reported rather than silently skipped, so the words the transcript rests on still
      // reach the screen and the estimator can change their own mind on the evidence.
      if (humanConditions[key]) { respected.push(key); return; }
      // Toggled only when it DIFFERS. Calling toggleCondition unconditionally would flip a switch
      // that was already right, which is the one way this could turn a correct form wrong.
      //
      // condOn, NOT M.conditions, AND THIS HALF IS NOT OPTIONAL. A carried key never lives on
      // the model -- migrateModel whitelists condition keys against freshModel().conditions and
      // drops the rest -- so reading one there is `undefined`, so every carried flag would read
      // as a change from off: a spoken "new construction" would leave Renovation exactly where
      // it was, because `!!undefined !== false` is false. condOn is the one function that knows
      // which of the two bindings a key lives in, and for the engine six it returns exactly
      // `!!M.conditions[key]`, so nothing about those changes here.
      if (condOn(key) !== item.value) toggleCondition(key, true);
      applied.push(key);
    });
    if (filled.length) {
      // The caption above the form names the project and the town, and both of those are boxes
      // this just filled. Written in hydrate() and nowhere else until now, so a verbal fill left
      // it reading "Untitled project" over a form with the name in it.
      paintProjLine();
      // One extra call, not one extra PUT: saveSoon clears its own pending timer, so this and any
      // toggle in the same run land on the single 600ms save.
      saveSoon();
    }
    return { filled: filled, applied: applied, respected: respected };
  }

  window.TWPolishIntake = { applyVerbal: applyVerbal };

  // ── the county, and the real remodel-tax rate ────────────────────────────────
  //
  // THE CONTROL IS NOT THIS PAGE'S. It is js/county-picker.js, the same module the live intake mounts: the
  // search, the rows and their rates, the keyboard, the note that says what the pick does to the price, and
  // the four draft keys it writes (`county`, `county_tax_rate`, `county_remodel_rate`, `county_notes`, the live
  // estimate screen's own). This page used to carry its own copy of all of that, about 300 lines, and the two
  // had already drifted once; Phase 9b deleted it. What is left here is the part that is genuinely this
  // page's: when the Remodel tax toggle is on, and that a pick is saved through this page's own debounced
  // save, which merges.
  //
  // The list is never hardcoded. It comes from /api/reference/counties, which serves backend/reference_tax.py.

  /** Mount the shared control. Null when js/county-picker.js did not load: the field then does nothing and the
   *  rest of the form works, which is the same guard the live intake has. */
  function mountCounty() {
    if (!window.TWCounty) return null;
    return window.TWCounty.mount({
      remodelTaxOn: function () { return !!(M && M.conditions && M.conditions.remodel_tax); },
      onChange: function () { saveSoon(); },
      pct: B.pct,
      ksState: B.RATES.KS_STATE
    });
  }

  /** The note quotes the Remodel tax toggle by name, so it is repainted whenever one of the five flips. */
  function renderCountyNote() {
    if (county) county.renderNote();
  }

  /** The four keys a save writes: the picked county's, or the empty ones when nobody has picked. Nothing at
   *  all when the control is not mounted, so a page without it cannot blank a county another screen set. */
  function countyKeys() {
    return county ? county.keys() : {};
  }

  /** The library's stored answers for the three Takeoff conditions, or [] when the read cannot
   *  answer. NEVER THROWS, and never blocks the form.
   *
   *  WHY THIS PAGE SEEDS THEM AT ALL, when the three moved to the Takeoff step on 2026-09-16 and
   *  this form no longer shows any of them. THIS PAGE IS WHAT MINTS THE MODEL. A brand-new project
   *  has no polish_estimate; the first save here writes a well-formed v2 through migrateModel, and
   *  that fills all nine conditions in from freshModel -- so by the time polish-estimate.html
   *  opens, the three are STATED, and its own gate (conditionsUnstated) correctly refuses to touch
   *  them. Seeding only there would make the Defaults tab reach nothing but a project that skipped
   *  intake, which is not the normal flow and is barely any flow at all.
   *
   *  So the default is applied where the model is CREATED, which is here, and the answer this page
   *  saves is the company's answer rather than freshModel's. After that it is the bid's, and
   *  nothing reaches back into it -- which is the whole of Hanz's rule for this feature.
   *
   *  `condition_defaults` is applied to NEITHER database as of 2026-09-18, so today this answers
   *  with nothing everywhere and the shipped literals stand, exactly as they do now. */
  async function loadConditionDefaults() {
    try {
      var res = await fetch(TW.resolveApiBase() + "/api/condition-defaults",
                            { headers: TW.authHeaders() });
      var body = await res.json();
      return (body && body.conditions instanceof Array) ? body.conditions : [];
    } catch (e) {
      return [];
    }
  }

  // ── saving ──────────────────────────────────────────────────────────────────
  var saveTimer = null;

  /** Debounced, same 600ms the calculator uses, because every save is a PUT of the WHOLE draft
   *  blob and a run of the verbal panel schedules one per condition plus one for the fields.
   *
   *  WHO CALLS IT, exactly: toggleCondition, pickJobType, the county control's onChange, applyVerbal, and — since
   *  the Sept 2026 data-loss fix — an `input` listener on any NAMED field in the form (wire()).
   *  That listener is the whole of Will's bug: until it existed the eight text boxes were pure
   *  DOM until Continue, so a step-nav click or a reload threw away everything typed. #county-input
   *  is excluded by that `name` guard on purpose — its keystrokes are a live search, not a draft
   *  edit, and saving per keystroke there would PUT the whole blob on every letter. */
  function saveSoon() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(function () { saveTimer = null; save(); }, 600);
  }

  /** Has any section of the bid been measured, so that a quantity box mirrors its takeoff? Then the takeoff,
   *  not the box, is where that figure lives.
   *
   *  Asked of a MODEL, so save() can ask it of the freshest saved one. Which section owns which box is
   *  B.boxValue's business (one mapping, work-types.js fieldHome): the Polish boxes belong to the Polish
   *  section, System 1 and 2 and the cove boxes to the Epoxy section, the three gypsum boxes to the Gyp
   *  section. A section counts once it holds a measured SF row, on or off (F5: switching the only SF row
   *  OFF must not hand the figure back to the box), and a takeoff of linear-foot rows alone has no SF to
   *  disagree about, so it does not.
   *
   *  The boxes are NEVER read-only (Hanz, 2026-10-12). What keeps the two places from disagreeing is
   *  save(): while a box is mirrored, its value reaches the draft only through the takeoff (patchModel's
   *  `boxes`), and only for a box the estimator actually typed in. A box that was merely painted, or
   *  painted from a takeoff another tab has since changed, writes nothing. TW.readForm (shared.js) takes
   *  every NAMED input, so the guard has to be the keys save() drops, not anything about the DOM. */
  function sfMeasured(model) {
    return !!model && B.boxNames().some(function (name) { return B.boxValue(model, name) !== null; });
  }

  /** Paint the quantity boxes from the takeoff. Always editable. A box whose section has nothing measured
   *  keeps what the draft holds and seeds the takeoff on step 2. Once its section is measured, System 1
   *  shows the FIRST measured SF row of that section and System 2 the SECOND (blank when there is none),
   *  the cove boxes the first and second measured length, and each gypsum box its own area; typing in one
   *  changes that row (System 2 adds the row when there is none). A third area and beyond is not reachable
   *  from two boxes, so a plain line says how many there are and a link goes to the Takeoff. */
  function paintSfBoxes() {
    B.boxNames().forEach(function (name) {
      // By NAME, because the boxes are drawn by js/intake-scope.js, which gives a field its name and no id.
      var box = form ? form.querySelector('[name="' + name + '"]') : null;
      var shown = M ? B.boxValue(M, name) : null;
      if (box && shown !== null) box.value = shown;
    });
    var note = $("sf-areas-note");
    var row = $("sf-takeoff-row");
    var link = $("sf-takeoff-link");
    var extra = M ? B.boxExtras(M)[0] : null;
    var more = !!extra;
    if (note) {
      if (more) {
        note.textContent = "The takeoff has " + extra.areas + " measured areas, " +
          B.fmtSf(extra.total) + " SF in total. Areas 3 and on are changed on the Takeoff.";
      }
      note.hidden = !more;
    }
    if (row) row.hidden = !more;
    if (link && more) link.href = TW.withDraft("/polish-estimate.html");
  }

  function save() {
    if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; }
    var values = form ? TW.readForm(form) : {};
    // Same combined "City, ST" the live intake keeps, because the estimate sheet (C3), the
    // proposal's {{city_state}} and the tax lookup all read that one field.
    var cs = [values.city, (values.state || "").toUpperCase()].filter(Boolean).join(", ");

    var cur = TW.getState();
    // MERGE, NEVER REPLACE. The calculator's takeoff and labor rows -- and whatever else a saved
    // model holds, `tabs` included -- live under this same key. Writing { conditions: … } over the
    // top of it to record one toggle would silently delete a finished takeoff, and the estimator
    // would not find out until the bid came back at zero. Only `conditions` and `conditions_shown`
    // are this page's to state, and B.patchModel is where that is decided (bid-model.js):
    // it lays those two over the saved model and leaves every other key exactly as it was saved.
    //
    // It reads the saved model through migrateModel, so what lands is a well-formed v2 with its
    // version stamped: a brand-new project has no polish_estimate at all, and a bare
    // { conditions } blob was read as "unversioned, unrecognised" -- the calculator replaced it
    // with defaults and the Projects page sent the project back to the spreadsheet intake. Both of
    // those were silent.
    //
    // The card map seeded on this page's first load rides along; a later save carries the same map
    // back, since M was read through migrateModel from what was saved.
    //
    // LABOR IS NOT THIS PAGE'S TO STATE, which patchModel also enforces: this page has no labor UI
    // at all, and migrateModel fills a missing `labor` in from freshModel(), so the FIRST save on a
    // brand-new project used to persist four crew rows nobody had been shown. That made the Labor
    // step's own defaults unreachable (B.laborUnstated is the gate they are seeded behind), so
    // patchModel takes the key back off -- ONLY when what is already saved never stated it.
    //
    // THE ONE NARROW WAY THE BOXES REACH THE TAKEOFF (Hanz, 2026-10-12: the boxes stay editable once the takeoff
    // is measured; 2026-10-13: for EVERY section, not the Polish one alone). Once a section is measured, a figure
    // the estimator TYPED into one of its boxes goes to the row that box mirrors, as `boxes`; which section owns
    // which box is B.boxValue's business, not this page's. "Typed" is a mark the input listener in wire() puts
    // on the box: a box merely PAINTED, or painted from a takeoff another tab has since changed, is stale and
    // writes nothing. A blank or zero is not a figure and writes nothing either, so clearing a box never
    // deletes a row. The takeoff is read off the saved model (as patchModel reads it), never off the DOM.
    var patch = { conditions: M.conditions, conditions_shown: M.conditions_shown };
    var boxOf = function (name) { return form ? form.querySelector('[name="' + name + '"]') : null; };
    var typedOf = function (name) {
      var box = boxOf(name), v = B.num(values[name]);
      return box && box.sfTyped && v > 0 ? [name, v] : null;
    };
    var typedBoxes = Object.fromEntries(B.boxNames().map(typedOf).filter(Boolean));
    patch.boxes = typedBoxes;
    // A MARK IS GOOD FOR ONE SAVE. Whatever the box held was just read, and from here the draft holds it, so the
    // box is PAINTED again, not typed. A mark that outlived this save was the stale-number trap: typed while the
    // takeoff was empty, the mark stayed on; the takeoff was then measured elsewhere, and the next unrelated
    // save from this page wrote the old number over the first row.
    B.boxNames().forEach(function (name) {
      var box = boxOf(name);
      if (box) box.sfTyped = false;
    });
    var model = B.patchModel(cur.polish_estimate, patch);

    // ONE SOURCE OF TRUTH FOR EACH FIGURE. Once a section's takeoff holds a measurement, its figure is the
    // takeoff's (js/polish-estimate.js writes it) and is not this page's to state -- see sfMeasured(). A box
    // nobody typed in is deleted from `values`, so the merge in setState leaves the saved key as the takeoff wrote
    // it. A GROUP with a typed box is written whole (a Polish pair is one area cell: the first box holds the
    // priced area, the second is blank; Epoxy's boxes hold their own areas), so the draft says what the takeoff
    // now says, as the estimate page's own save does.
    if (sfMeasured(model)) {
      B.boxNames().forEach(function (name) {
        var now = B.boxDraftValue(model, name);
        if (now === null) return;                    // not mirrored: the draft keeps what the box holds
        var written = B.boxGroup(name).some(function (n) { return Object.prototype.hasOwnProperty.call(typedBoxes, n); });
        if (written) Object.assign(values, Object.fromEntries([[name, now]]));
        else delete values[name];
      });
      // paintSfBoxes reads M; keep it the takeoffs that were just saved, but only after a typed figure moved them:
      // a save with nothing typed leaves M as the page loaded it, so a stale paint stays visibly stale.
      if (Object.keys(typedBoxes).length) { M.takeoff = model.takeoff; M.tabs = model.tabs; }
    }
    // A quantity the job type does not ask for is drawn (hidden, never removed) and so is swept into `values`
    // with its 0. Left off unless the draft already holds it: opening a bid and saving it must not add a
    // quantity the bid never had.
    S.hiddenNames(JOB).forEach(function (name) {
      if (!Object.prototype.hasOwnProperty.call(cur, name)) delete values[name];
    });

    // The county's four keys ride along as TOP-LEVEL draft keys, not inside polish_estimate: they
    // are the live estimate screen's own, and js/polish-estimate.js reads county_remodel_rate off
    // the draft root. countyKeys() is hydrated from the draft on load, so a project that picked its
    // county on the other screen writes the same values back rather than losing them here.
    TW.setState(Object.assign({}, values, {
      city_state: cs,
      // The chosen job type: any the vocabulary marks ready (all four now); a draft opened here with no job
      // type, or one v2 cannot price, saves as the default.
      work_type: JOB,
      // Mirrored the way the live intake mirrors it: the Projects list, the bell's due-date
      // reminders and the Dropbox folder date all read `deadline`.
      deadline: values.bid_date || cur.deadline || "",
      polish_estimate: model,
      // Both homes, from one place. polish_estimate.conditions is what the beta
      // calculator prices from; cell_values is what the generated .xlsx -- and so the
      // customer's bid -- is filled from, and what the live intake and the estimate
      // grid read. Writing only the first would price the beta correctly and hand out
      // a workbook that disagreed with it.
      cell_values: conditionCells(),
    }, countyKeys()));
    paintSaveBlocked();
  }

  /** Fault 2 in the Sept 2026 "switches to a different tab and it doesn't save" report: one
   *  global localStorage blob, and shared.js REFUSES a write silently (a console.warn only) when
   *  another tab has re-stamped it onto a different draft. The toggle paints, the field fills --
   *  nothing is written, locally or to the server -- and nobody is told. TW.saveBlocked() is a
   *  read-only check built for exactly this; separate element from #sandbox-note, which is the
   *  test-copy identity banner and must not be clobbered by a transient warning. */
  function paintSaveBlocked() {
    var el = $("save-note");
    if (!el) return;
    var reason = TW.saveBlocked ? TW.saveBlocked() : null;
    if (reason === "foreign-blob") {
      el.textContent = "This project is open in another tab, and that tab has taken over the " +
        "shared draft. What you just entered here has NOT been saved -- switch back to the other " +
        "tab, or reopen this project from Projects.";
      el.hidden = false;
    } else {
      el.hidden = true;
    }
  }

  // ── the form ────────────────────────────────────────────────────────────────

  /** The caption above the form: which project this is, and where.
   *
   *  Its own function because TWO things change it now — hydrate on load, and a verbal fill that
   *  types the name and the town into the boxes. While it lived inline in hydrate, the panel could
   *  fill "Blue Valley West, Overland Park" into the form and leave the heading reading
   *  "Untitled project" above it.
   *
   *  READS THE BOXES FIRST, then the draft. The boxes are what the estimator can see, and a verbal
   *  fill reaches them 600ms before the save reaches `state`. On load the two agree, writeForm
   *  having just put one into the other. */
  function paintProjLine() {
    var el = $("proj-line");
    if (!el) return;
    var boxed = function (name) {
      var f = form ? form.querySelector('[name="' + name + '"]') : null;
      return String((f && f.value) || "").trim();
    };
    var name = boxed("project_name") || state.project_name || "";
    var city = boxed("city") || state.city || "";
    var st = boxed("state") || state.state || "";
    el.textContent = [name, city && st ? city + ", " + st : ""]
      .filter(Boolean).join(" · ") || "Untitled project";
  }

  /** Draw the Job type choice from the vocabulary. Rewritten whole, so the checked radio is always JOB. */
  function renderJobTypes() {
    var box = $("job-type");
    if (box) box.innerHTML = S.jobTypesMarkup(JOB);
    var note = $("job-type-note");
    if (note) {
      note.textContent = S.jobTypeNote();
      note.hidden = !note.textContent;
    }
  }

  /** Draw the quantity fields (js/intake-scope.js, the live intake's own renderer) and show the ones JOB asks
   *  for. Every field is drawn and the rest are hidden, never removed. */
  function renderScope() {
    var box = $("systems-container");
    if (!box) return;
    S.renderSystems(box, S.systemCount());
    S.applyScope(JOB, { systems: box, gyp: $("gyp-sf-container") });
  }

  /** Pick a job type. A type the vocabulary has not marked ready does nothing: not changed, not saved. The
   *  disabled radio already stops a person; this stops a script, and a keyboard event that reached it. */
  function pickJobType(key) {
    if (!S.isPickable(key) || key === JOB) return;
    JOB = key;
    renderJobTypes();
    var box = $("systems-container");
    if (box) S.applyScope(JOB, { systems: box, gyp: $("gyp-sf-container") });
    saveSoon();
  }

  function hydrate() {
    renderScope();                          // before writeForm: the boxes have to exist to be filled
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
    paintSfBoxes();                         // after writeForm: the boxes show the takeoff's measured areas
    renderJobTypes();                       // after writeForm, which would tick a radio the draft names
    renderConditions();
    if (county) county.hydrate(state);      // after the toggles: the note quotes Remodel tax
    paintProjLine();
    // After writeForm, which ticks the Audience radio the draft names: the Drawings & specs box shows
    // for a GC only (js/audience-box.js). A page served without that script has nothing to repaint.
    if (window.TWAudienceBox) window.TWAudienceBox.sync();
  }

  function onClick(e) {
    var t = e && e.target;
    var near = function (sel) { return t && t.closest ? t.closest(sel) : null; };

    var sw = near("[data-cond]");
    if (sw) { toggleCondition(sw.getAttribute("data-cond")); return; }

    var jt = near("[data-jobtype]");
    if (jt) { pickJobType(jt.getAttribute("data-jobtype")); return; }

    // The county control owns its own clicks: a row (by INDEX into what was rendered, not by name, because
    // two counties are called Johnson and charge different rates), Clear, and a click anywhere else, which
    // closes the list unless it landed inside the field.
    if (county) county.onDocumentClick(e);
  }

  // Set from the moment Continue is pressed until the browser has gone (or has not): a second press does nothing.
  var leaving = false;

  async function onSubmit(e) {
    var SAVE_WAIT_MS = 8000;                 // local, so that whatever lifts onSubmit by name takes it along
    var GIVE_BACK_MS = 10000;
    if (e && e.preventDefault) e.preventDefault();
    // A DISABLED BUTTON IS NOT ALL THAT STOPS A SECOND PRESS: Enter in a box and a script go round it. One press is one
    // save and one wait, so the page is never left with two of them in flight.
    if (leaving) return;
    leaving = true;
    // THE BUTTON SAYS WHAT IT IS DOING (F5 of the audit of X1). The wait below can be eight seconds on a slow server, and an
    // estimator who sees nothing happen presses again. It is given back, with its own label, if the browser does not go.
    var btn = $("continue-btn");
    var label = btn ? btn.textContent : "";
    var say = function (text, off) { if (btn) { btn.disabled = off; btn.textContent = text; } };
    var givenBack = false;
    var giveBack = function () { if (givenBack) return; givenBack = true; leaving = false; say(label, false); };
    try {
      say("Saving…", true);
      save();                                  // synchronously, not on the 600ms timer
      // WAIT FOR THE SAVE, ON THIS PAGE, BEFORE LEAVING (X1, staging 2026-10-21). save() only queues the draft's server
      // save, and the assign() below used to follow it at once, so a project's first PUT went out through shared.js's
      // pagehide handler (keepalive) and its reply reached no page. flushState sends the save now and resolves once it
      // has been answered. What the wait buys is that the save is on the server before the browser leaves, answered to a
      // page that is still there (a save sent as a page goes is a keepalive request: capped at about 64KiB, and its reply
      // is seen by nobody). It is not what files a new project under Test: the project's own blob says it is a test
      // (shared.js sayWhatItWasStartedAs), so the first save creates the row filed whichever way the page is left.
      // BOUNDED: a server that never answers must not leave the button doing nothing, and past the bound this is what
      // Continue always did. A save that FAILS answers false at once and is not waited out.
      var timer = null;
      try {
        await Promise.race([
          TW.flushState(),
          new Promise(function (resolve) { timer = setTimeout(resolve, SAVE_WAIT_MS); })
        ]);
      } catch (err) { /* flushState reports a failed save as false; it does not throw */ }
      if (timer) clearTimeout(timer);
      say("Opening the estimate…", true);
      // withDraft, not a bare path: on a test copy the id shared.js has stored may still be the
      // REAL project's, and this button must carry the draft the page was actually editing.
      window.location.assign(TW.withDraft("/polish-estimate.html"));
    } catch (err) {
      giveBack();                              // nothing was asked of the browser: the button works again at once
      throw err;
    }
    // The browser may not go (the load was stopped, a prompt was answered no). Then this page is still here, and a
    // button left saying "Opening the estimate..." would be a dead end.
    setTimeout(giveBack, GIVE_BACK_MS);
  }

  /** Listeners go on only after the sandbox has settled. A toggle flipped before the page knows
   *  which draft it may write to is the live-bid write the sandbox exists to prevent, arrived at
   *  by racing it instead of by skipping it. */
  function wire() {
    document.addEventListener("click", onClick);
    if (form) form.addEventListener("submit", onSubmit);
    // NAMED FIELDS ONLY. #county-input has no `name` -- its keystrokes are a search, not a draft
    // edit, and the county control's onChange is what saves a PICKED county. Before this, nothing typed into
    // the eight text boxes reached the draft until Continue: saveSoon()'s own docstring named this
    // exact gap, and a step-nav tab or a reload in between silently lost everything typed.
    if (form) form.addEventListener("input", function (e) {
      if (e.target && e.target.name) {
        // Marks an SF box as TYPED IN, which is what lets save() send it to the takeoff. A mark on
        // the element, not a page variable: only an `input` event, never a repaint or a reload,
        // puts it there.
        if (T.fieldHome(e.target.name)) e.target.sfTyped = true;
        saveSoon();
      }
    });
    // THE "0" TRAP. The two SF boxes ship with value="0". A programmatic focus (a test driver, a
    // screen reader jump) leaves the caret at position 0, so typing 8000 gives "8000"+"0" = 80000.
    // Selecting a lone "0" on focus makes the first keystroke replace it, as a click or Tab would.
    if (form) form.addEventListener("focusin", function (e) {
      var t = e.target;
      if (t && t.type === "number" && t.value === "0" && t.select) t.select();
    });
    // A box left blank (or at 0) while it mirrors a takeoff row writes nothing, so on blur it shows
    // that row's figure back rather than sitting empty over a row that still holds a number.
    // A FIGURE JUST TYPED IS STILL WAITING ON THE 600ms SAVE when the box loses focus (typing a number and
    // tabbing away takes well under that). Repainting first would put the OLD row figure back over it, and the
    // save would then read the old figure from the box. So a pending save runs first: the typed figure reaches
    // the takeoff, and the repaint shows the takeoff.
    if (form) form.addEventListener("change", function (e) {
      if (e.target && T.fieldHome(e.target.name)) {
        if (saveTimer) save();
        paintSfBoxes();
      }
    });
    // The address / business lookup, shared with the live intake (js/address-lookup.js). A picked
    // row fires `input` on City, State and Zip, which the listener above turns into a save. The
    // guard is for a page served without the script; the lookup is a convenience, not a gate.
    if (window.TWAddress && form) {
      // The county box fills from the address (js/county-autofill.js); null when a script is missing.
      var countyAuto = (county && window.TWCountyAutofill) ? window.TWCountyAutofill.mount({
        county: county, address: $("address-input"), city: $("city-input"),
        state: $("state-input"), zip: $("zip-input") }) : null;
      window.TWAddress.mount({
        address:  $("address-input"),
        business: $("business-input"),
        city:     $("city-input"),
        state:    $("state-input"),
        zip:      $("zip-input"),
        onPick:   countyAuto ? countyAuto.onPick : undefined
      });
    }
    if (county) county.wire(false);         // the search box's own listeners; the click is onClick's
    // The 600ms debounce only reaches the server if something outlives it. Continue's onSubmit
    // does that synchronously; leaving through a step-nav tab, closing the tab, or switching tabs
    // did not -- and shared.js's own pagehide net (shared.js:513) only flushes a timer THIS page
    // armed, which before the listener above was never armed by typing at all.
    window.addEventListener("pagehide", function () {
      if (!saveTimer) return;
      save();            // clears the 600ms timer, runs TW.setState synchronously
      TW.flushState();   // fires the keepalive PUT now instead of waiting on the 2.5s debounce
    });
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

    // THE TAKEOFF CONDITIONS' COMPANY ANSWERS, on a brand-new project and on nothing else.
    //
    // ASKED OF THE SAVED BLOB, AFTER THE SANDBOX HAS SETTLED which draft this page is on, and
    // before anything can be typed. B.conditionsUnstated is true only when NOTHING has ever been
    // saved for this estimate -- Hanz's rule is that changing a default must not change any
    // estimate that already exists, and an estimator's saved answers are their work.
    //
    // THE CELL STILL WINS, so the read-back runs again over the seeded answers rather than the
    // seed running last. A project that reached this page from the live intake has its answers in
    // cell_values and no polish_estimate at all, which is exactly the blob conditionsUnstated
    // calls seedable; seeding last would put a company default over an answer the AI autofill or a
    // previous visit had already written into Kyle's workbook.
    //
    // AWAITED, unlike the county list's load. This decides what the first save writes, and that save can be
    // triggered by the first keystroke -- a seed that landed after it would either be lost or
    // arrive as a second, different answer on a bid already in flight.
    if (B.conditionsUnstated(state.polish_estimate)) {
      var condRows = await loadConditionDefaults();
      M.conditions = B.conditionsFromCells(
        B.seedConditionDefaults(M.conditions, condRows),
        state.cell_values, T.isSplit(state));
      // Which condition cards this new bid shows on the estimate (seedConditionsShown). This page
      // mints the model, so the estimate never sees it unstated and cannot seed this itself.
      M.conditions_shown = B.seedConditionsShown(condRows);
    }

    form = $("intake-form");
    county = mountCounty();                 // before hydrate, which hands it the draft's county
    hydrate();
    // shared.js's _WIZARD_PATH excludes the beta pages, so "2 · Estimate" out of this page never
    // gets a ?d= from it at all.
    SB.repointWizardLinks();
    wire();

    $("loading").hidden = true;
    $("main").hidden = false;

    // NOT awaited, and after the reveal: it is reference data for one search box, and the other
    // eight fields must not wait on it. the county control has already shown whatever county the draft
    // carries — that comes off the draft, not out of this list — and its load repaints the
    // rows if the estimator started typing while it was in flight.
    if (county) county.load();
  }

  boot();
})();
