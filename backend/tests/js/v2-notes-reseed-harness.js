"use strict";
/* THE NOTES BOX AFTER THE BASE WAS PICKED ON THE ESTIMATE, run rather than read.
 *
 * Sheets phase 4 follow-up. On a v2 draft the Proposal step only READS the base (its radios are read-only), so a
 * base switch happens on the estimate and the Proposal step opens on the new base. The page's own re-seed of the
 * notes (reseedNotesForWorkType) only ran when a radio changed on this very page, so the NOTES kept the old work type's
 * boilerplate: an Epoxy base printed the Polish notes and left out the Epoxy warranty line.
 *
 * What runs here is the page's own code, lifted from js/proposal-review.js by name: the notes prefill (the `_notesReady`
 * IIFE, as the page runs it at load), reseedNotesIfBaseChangedElsewhere, reseedNotesForWorkType, fetchDefaultNotes,
 * syncPhaseNote and effectiveWorkType. The two collaborators faked are the network (answering what /api/default-notes
 * answers, from backend/default_notes.json) and the draft store (TW.setState merges, as the real one does). A "visit" is
 * one page load: it reads the draft as saved, runs the prefill, waits for `_notesReady`, and hands back what the notes box
 * holds and what the draft was left holding. The drafts are the real model's (v2-proposal-snapshot-harness.js).
 *
 * Usage: node v2-notes-reseed-harness.js <frontend-dir>   ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const SRC = L.read(path.join(ROOT, "js", "proposal-review.js"));
const B = require(path.join(ROOT, "js", "bid-model.js"));
const SNAPSHOTS = require("./v2-proposal-snapshot-harness.js").build(B);
// What /api/default-notes answers: the work type's list, else the epoxy one (backend/main.py api_default_notes).
const DEFAULTS = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "default_notes.json"), "utf8"));

const clone = (x) => (x === undefined ? undefined : JSON.parse(JSON.stringify(x)));
const NL = "\n";
const fn = (name) => L.liftSource(SRC, name, { indent: "  ", where: "proposal-review.js" });
const top = (name) => L.grabConst(SRC, name, { indent: "  ", where: "proposal-review.js" });

const UNITS = [
  top("_seededNotes"), fn("effectiveWorkType"), fn("syncPhaseNote"), fn("fetchDefaultNotes"), fn("reseedNotesForWorkType"),
  fn("reseedNotesIfBaseChangedElsewhere"), top("_notesReady"),
].join(NL);

/** One page load on the draft `store` (the saved blob; the page's setState merges into it). */
function visit(store, opts) {
  const o = opts || {};
  const state = clone(store);                                   // the page's one-shot snapshot
  const ta = { value: state.notes_text == null ? "" : state.notes_text };   // TW.writeForm puts the saved notes in the box
  const asked = [];
  const sets = [];
  const TW = {
    setState: (patch) => { sets.push(Object.keys(patch)); Object.assign(store, clone(patch)); },
    authHeaders: () => ({}),
  };
  const answer = (url) => {
    const wt = decodeURIComponent(/work_type=([^&]*)/.exec(url)[1]);
    asked.push(wt);
    return Promise.resolve({ json: () => Promise.resolve({ work_type: wt, notes: DEFAULTS[wt] || DEFAULTS.epoxy }) });
  };
  const doc = { getElementById: (id) => (id === "notes-text" ? ta : null) };
  let renders = 0;
  const body = UNITS + NL + "return { ready: _notesReady, seeded: () => _seededNotes };";
  const api = new Function("state", "document", "TW", "window", "fetch", "renderNotesPreview", "scheduleFit", body)(
    state, doc, TW, {}, answer, () => { renders++; }, () => {});
  return {
    state, ta, asked, sets, ready: api.ready, renders: () => renders,
    /** After the visit settled: the box, and what the draft holds now. */
    done: async () => { await api.ready; await new Promise((r) => setImmediate(r)); return { text: ta.value, asked: asked.slice(), sets: sets.slice() }; },
  };
}

const lines = (s) => String(s).split(NL);
const hasLine = (text, start) => lines(text).some((l) => l.indexOf(start) === 0);
const WARRANTY = "Excludes warranty for floor failure due to hydrostatic pressure";   // epoxy and combo only
const FLATNESS = "Concrete flatness, mix design";                                    // polish and combo only
/** What the notes box holds, as the facts a test cares about. */
function facts(text, extra) {
  return Object.assign({
    warranty: hasLine(text, WARRANTY), flatness: hasLine(text, FLATNESS),
    phase: lines(text).filter((l) => /^Add \$[\d,]+ for each additional phase/.test(l)),
    lines: lines(text).length,
  }, extra || {});
}

/** The estimate switching the base: its save lands on the draft whole (the model's own snapshot plus what pickBase answered). */
function baseSwitchedOnTheEstimate(store, scenario) {
  const next = clone(SNAPSHOTS[scenario].state);
  Object.keys(next).forEach((k) => { store[k] = next[k]; });
}

const out = {};
const defaultsOf = (wt) => DEFAULTS[wt].join(NL);
/** The amounts taken out, so a line is compared by its words (the phase line's figure is the estimate's to set). */
const words = (s) => String(s).replace(/\$(?:xxxx|[\d,]+)/g, "$");

(async () => {
  // 1. THE FINDING. A Polish-base bid is opened once (its notes are seeded), the base is made Epoxy on the estimate, and the
  //    Proposal step is opened again: the notes are the Epoxy boilerplate, not the Polish one it kept.
  {
    const store = clone(SNAPSHOTS.polish.state);
    const first = await visit(store).done();
    const seeded = clone(store);
    baseSwitchedOnTheEstimate(store, "epoxy");
    const second = await visit(store).done();
    const third = await visit(store).done();               // and a third visit changes nothing
    out.switched = {
      first: facts(first.text, { asked: first.asked }),
      seed: seeded.notes_seed ? { work_type: seeded.notes_seed.work_type, savedText: seeded.notes_text === seeded.notes_seed.text } : null,
      second: facts(second.text, { asked: second.asked }),
      saved: { work_type: store.notes_seed && store.notes_seed.work_type, textIsTheBox: store.notes_text === second.text,
               seedIsTheBox: !!store.notes_seed && store.notes_seed.text === second.text },
      third: facts(third.text, { asked: third.asked, same: third.text === second.text }),
    };
  }

  // 2. THE WAY BACK: Epoxy to Polish again reseeds the Polish words.
  {
    const store = clone(SNAPSHOTS.polish.state);
    await visit(store).done();
    baseSwitchedOnTheEstimate(store, "epoxy");
    await visit(store).done();
    baseSwitchedOnTheEstimate(store, "copy");               // a Polish copy as the base: the effective work type is polish again
    const back = await visit(store).done();
    out.backToPolish = facts(back.text, { asked: back.asked });
  }

  // 3. THE PAIR: the combined base is "combo", whose boilerplate holds both lines.
  {
    const store = clone(SNAPSHOTS.polish.state);
    await visit(store).done();
    baseSwitchedOnTheEstimate(store, "combined");
    const combo = await visit(store).done();
    out.combined = facts(combo.text, { asked: combo.asked, exactlyTheComboNotes: words(combo.text) === words(defaultsOf("combo")) });
  }

  // 4. A HAND EDIT IS KEPT. One typed line (the form saves the box as it is typed) and the base switched: the notes stay.
  {
    const store = clone(SNAPSHOTS.polish.state);
    const first = await visit(store).done();
    const typed = first.text + NL + "Call the owner before the crew arrives.";
    store.notes_text = typed;                               // what the form's persist writes
    baseSwitchedOnTheEstimate(store, "epoxy");
    const after = await visit(store).done();
    out.handEdited = facts(after.text, { asked: after.asked, kept: after.text === typed });
  }

  // 5. THE SAME BASE: reopening changes nothing and asks the server for nothing.
  {
    const store = clone(SNAPSHOTS.polish.state);
    const first = await visit(store).done();
    const again = await visit(store).done();
    out.sameBase = { first: first.asked, again: again.asked, same: again.text === first.text };
  }

  // 6. A DRAFT FROM BEFORE THE RECORD: notes saved, no seed. The base switched. Left exactly as it was.
  {
    const store = clone(SNAPSHOTS.polish.state);
    const first = await visit(store).done();
    delete store.notes_seed;
    baseSwitchedOnTheEstimate(store, "epoxy");
    const after = await visit(store).done();
    out.noRecord = facts(after.text, { asked: after.asked, kept: after.text === first.text });
  }

  // 7. TYPING WHILE THE NEW WORDS ARE ON THEIR WAY: the box is the estimator's, the fetch does not write over it.
  {
    const store = clone(SNAPSHOTS.polish.state);
    await visit(store).done();
    baseSwitchedOnTheEstimate(store, "epoxy");
    const v = visit(store);                                 // the re-seed is waiting on the network...
    v.ta.value = v.ta.value + NL + "Typed a moment after the page opened.";
    const typed = v.ta.value;
    const after = await v.done();
    out.typedMeanwhile = { kept: after.text === typed, hasWarranty: facts(after.text).warranty };
  }

  // 8. THE FILES PAGE'S DOOR WAITS ON THE PREFILL (`_notesReady`): by the time it resolves the box already holds the new words.
  {
    const store = clone(SNAPSHOTS.polish.state);
    await visit(store).done();
    baseSwitchedOnTheEstimate(store, "epoxy");
    const v = visit(store);
    const before = facts(v.ta.value).warranty;
    await v.ready;
    out.doorWaits = { warrantyBefore: before, warrantyAtReady: facts(v.ta.value).warranty };
  }

  // 9. A BRAND-NEW PROJECT still seeds once and writes the record with the notes.
  {
    const store = clone(SNAPSHOTS.epoxy.state);
    delete store.notes_text; delete store.notes_seed;
    const r = await visit(store).done();
    out.fresh = facts(r.text, { asked: r.asked, seed: store.notes_seed ? store.notes_seed.work_type : null, saved: store.notes_text === r.text });
  }

  process.stdout.write(JSON.stringify(out));
})().catch((e) => { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
