"use strict";
/* THE JOB'S ONE DRIVE, OVER EVERY SEQUENCE OF SWITCHES: js/polish-estimate.js, whole, booted the way polish-estimate-harness.js boots it, with the REAL
 * js/bid-model.js beneath it. A hand-picked scenario can only hold the switches somebody thought of; the 2026-10-20 audits of the "far distance fills Travel
 * Labor" work each found that the scenarios held every switch but the next one (Epoxy to Polish to Combo priced the drive twice, $1,716 where Kyle types $858),
 * so this walks EVERY sequence of job types (Polish, Epoxy, Combo, Gyp) and Sheets base changes up to a depth, on a NEW far bid (Wichita, 190 miles), on a local one
 * (40 miles) and on one whose distance is unknown, and judges the page after every step. A step is the intake's job type reaching the estimate page (the saved draft
 * is reopened as that type, which is how the page meets it), optionally followed by the crew typed on the new carrier; or a base change made on the Sheets panel.
 *
 * THE RULE (Hanz, 2026-10-20): on a job 70 or more miles from the Olathe office there is EXACTLY ONE priced drive for the job: the Travel Labor row of the section that
 * carries the job's travel, crew size (the most guys on any labor line of the base sections, a Combo's both) x one round trip's hours x rate. Hotel and Per Diem as
 * they were. A figure the estimator typed, a box they cleared and a row they switched off are theirs: never refilled, and they FOLLOW the job's drive when the
 * carrier changes. A box they are standing in is never written. A plain reopen changes nothing.
 *
 * WHAT IS CHECKED AFTER EVERY STEP (the code in the report is the one the test file names):
 *   ONE_DRIVE        no more than one priced Travel Labor row on the sections that are a BASE of the bid (an option is priced apart and carries its own).
 *   MAN_DAYS         no Travel Labor row on a live section that the tool filled and that is priced on the MAN-DAYS (the older auto: 49.5 x 6.5 x $33 = $10,617.75).
 *   FAR_CARRIER      a far job's carrier (a Gyp carrier excepted: its drive is typed) has a Travel Labor row, and one nobody touched is exactly the rule:
 *                    the crew's size on auto, the round trip's hours, the markers that say so.
 *   GYP_UNFILLED     a Gyp carrier's row the estimator did not touch is empty.
 *   LOCAL            a job under 70 miles, or with no distance, prices no Travel Labor row nobody touched.
 *   OWNED            (a typed / cleared / switched-off row) it is on the carrier, with what was typed, and no other section's row prices anything (a copy of the
 *                    carrier's sheet made a base beside it holds a repeat of the row, which is given back: the drive is typed once and charged once).
 *   STALE            a Travel Labor row nobody touched, on a section that is not the carrier and is not an option, is empty and carries none of the fill's markers
 *                    (the old carrier gave it back; an off section's row waits empty for the day its job type returns).
 *   ONE_ROW          no section holds two Travel Labor rows.
 *   PLAIN_REOPEN     a step that is only a reopen (the job type the draft already is) arms no save, writes nothing, and leaves every row and the price as saved.
 *   REOPEN_AGREES    the price the draft saved (proposal_lump_sum, or computed_bid.lump_sum) is the price a plain reopen of it shows, and the rows are the same.
 *   CRASH            the page threw.
 *
 * MODES (argv[3]): far | farplain | local | unknown | typed | clearHours | clearGuys | off | mixed | sheets | sheetsTyped | sheetsClearHours | sheetsClearGuys | sheetsOff |
 *   audit54.
 *   far, local, unknown   steps are the four job types, each plain or with the crew typed on the new carrier.
 *   farplain              the same far job, with the four job types only (no crew typed): the deeper walk.
 *   typed, clearHours, clearGuys, off   the estimator's variant is applied to the carrier's Travel Labor row first, then the steps are the four job types.
 *   mixed                 the steps are the four job types and, once on any path, ONE of the four variants (anywhere in the sequence).
 *   sheets                the steps are the four job types, and the Sheets panel's base changes, and a copy of the carrier, whatever the panel offers.
 *   sheetsTyped, sheetsClearHours, sheetsClearGuys, sheetsOff   the same steps, with the estimator's variant applied to the carrier's row first.
 *   audit54               the 54 sequences the 2026-10-20 audit found pricing the drive twice at 7d32336, with their exact dollars.
 * Any mode but audit54 takes a distance after an at-sign (typed@local, sheetsOff@unknown, mixed@local): the same walk on a 40 mile job or one with no distance.
 * argv[4] is the depth (the number of steps after the start).
 *
 * Usage: node travel-sequence-harness.js <frontend-dir> <mode> [depth]   ->  one line of JSON
 */
const path = require("path");
const Module = require("module");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const RAW_MODE = process.argv[3] || "far";
const MODE = RAW_MODE.split("@")[0];
const DIST_MODE = RAW_MODE.indexOf("@") >= 0 ? RAW_MODE.split("@")[1] : "";     // "typed@local": the same walk on a job of that distance
const DEPTH = Number(process.argv[4] || 3);
const B = require(path.join(ROOT, "js", "bid-model.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));

function loadPrelude(file, exportNames) {
  const base = path.join(__dirname, file);
  const code = L.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in travel-sequence-harness.js");
  const m = new Module(base, module);
  m.filename = base;
  m.paths = Module._nodeModulePaths(path.dirname(base));
  m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
  return m.exports;
}

const P = loadPrelude("polish-estimate-harness.js", ["build", "blob", "typeInto", "clickEl", "clickOn", "need", "changeTo", "MODEL"]);

// The library's labor lines: Travel (built in), one Epoxy crew line, one Gyp pour. The Polish crew is the shipped fallback the page adds.
const TRAVEL_ROW = { id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true, sort: -1, favorite: true, default_work_types: [], default_on: true };
const EPOXY_ROW = { id: "epoxy-install", name: "Epoxy install", rate: 33, unit: "days", guys_auto: false, sort: 1, favorite: true, default_work_types: ["epoxy"], default_on: true };
const GYP_ROW = { id: "gyp-pour", name: "Gyp pour", rate: 33, unit: "hours", guys_auto: false, sort: 2, favorite: true, default_work_types: ["gyp"], default_on: true };
const LABOR = [TRAVEL_ROW, EPOXY_ROW, GYP_ROW];
const GYP_TAB = 'Gyp (USG 1-8")';

const ADDR = { address: "100 Main St", city: "Wichita", state: "KS", zip: "67202" };
const DISTANCES = { far: { ok: true, miles: 190, reason: "" }, local: { ok: true, miles: 40, reason: "" }, unknown: { ok: false, miles: null, reason: "not_found" } };
const CONDITIONS = { taxable: true, prevailing_wage: false, remodel_tax: false };
const draftOf = (workType, extra) => P.blob(Object.assign({ work_type: workType, polish_estimate: { version: 2, conditions: CONDITIONS } }, ADDR, extra || {}));
const DRAFTS = {
  epoxy: () => draftOf("epoxy", { system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "" }),
  polish: () => draftOf("polish", { polish_sf: 5000 }),
  combo: () => draftOf("combo", { polish_sf: 5000, system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "" }),
  gyp: () => draftOf("gyp", { gyp_soft_sf: 9000, gyp_hard_sf: 6000, gyp_corridor_sf: 2000 }),
};
const TYPES = ["epoxy", "polish", "combo", "gyp"];
// The crew a new bid is given on its first carrier, and the (bigger) one typed by a "+crew" step on the carrier a job type leaves it with.
const START_CREW = { epoxy: ["Epoxy", "epoxy-install", "4", "12"], polish: ["Polish", "polishing", "4", "12"], combo: ["Polish", "polishing", "4", "12"], gyp: [GYP_TAB, "gyp-pour", "4", "12"] };
const STEP_CREW = { epoxy: ["Epoxy", "epoxy-install", "5", "12"], polish: ["Polish", "polishing", "6", "12"], combo: ["Polish", "polishing", "6", "12"], gyp: [GYP_TAB, "gyp-pour", "5", "12"] };
const VARIANTS = ["typed", "clearHours", "clearGuys", "off"];
/** The variant a mode starts from, or "": the four variant modes, and the sheets modes that name one (sheetsTyped, sheetsOff, ...). */
const MODE_VARIANT = (function () {
  if (VARIANTS.indexOf(MODE) >= 0) return MODE;
  const m = /^sheets(Typed|ClearHours|ClearGuys|Off)$/.exec(MODE);
  return m ? m[1].charAt(0).toLowerCase() + m[1].slice(1) : "";
})();
const SHEETS = MODE === "sheets" || /^sheets(Typed|ClearHours|ClearGuys|Off)$/.test(MODE);

const flush = () => new Promise((r) => setImmediate(r));
const settle = async () => { for (let i = 0; i < 10; i++) await flush(); };

/** A page on a draft. `extra.distance` is what the lookup answers (a NEW bid asks by itself, a saved one does not). */
async function open(blob, extra) {
  const b = P.build(Object.assign({ blob: blob, labor: LABOR }, extra || {}));
  await b.api.init();
  await settle();
  return b;
}

const secOf = (m, tab) => (tab === B.ROOT_TAB ? m : (m.tabs || {})[tab]);
const travelRows = (sec) => ((sec && sec.labor) || []).filter((r) => r && r.id === "travel");
const idxIn = (sec, id) => (sec && sec.labor ? sec.labor.findIndex((r) => r && r.id === id) : -1);
const blank = (v) => v === undefined || v === null || String(v).trim() === "";
const cost = (r) => B.laborCost(r);
/** Whose row is it? The estimator's when it is switched off, or a box was typed in or cleared (the markers saved with the row). Written out here and not
 *  asked of the model, so the check does not agree with a model that has the same mistake in it. */
const owned = (r) => !!r && (r.enabled === false || r.guys_typed === true || r.hours_typed === true);
const fmtRow = (r) => (r ? r.guys + "x" + r.days + (r.enabled === false ? " OFF" : "") + (r.guys_typed ? " Tg" : "") + (r.hours_typed ? " Th" : "") +
  (r.guys_follow ? " crew" : "") + " =$" + cost(r) : "none");
const lumpOf = (blob) => {
  if (blob && blob.proposal_lump_sum !== undefined && blob.proposal_lump_sum !== null) return blob.proposal_lump_sum;
  return blob && blob.computed_bid ? blob.computed_bid.lump_sum : null;
};
const typeOfBlob = (blob) => {
  try { return B.baseOf(B.migrateModel(blob.polish_estimate)).jobType; } catch (e) { return null; }
};

/** What the page holds, read off its WHOLE model. */
function facts(b) {
  const m = b.api.root();
  const entries = B.sectionsOf(m);
  const miles = m.distance ? B.milesOrNull(m.distance.miles) : null;
  return { m: m, entries: entries, carrier: B.travelCarrier(m), miles: miles, far: miles !== null && miles >= B.LOCAL_MILES,
    jobType: B.baseOf(m).jobType };
}

/** A Travel Labor row with nothing in it: no hours, no marker of a fill, nobody's box. migrateModel puts one back on a section whose draft was saved without
 *  (a Combo's off root, after its row went with the carrier to Epoxy), and it prices nothing and says nothing, so "as it was" does not count it. */
const emptyRow = (r) => !owned(r) && blank(r.days) && !r.guys_follow && typeof r.hours_seed !== "number";

/** The same facts as a string, for "is it as it was". */
function shape(b) {
  const f = facts(b);
  return JSON.stringify({ car: f.carrier, kinds: f.entries.map((e) => [e.tab, e.kind]),
    rows: f.entries.map((e) => [e.tab, travelRows(e.section).filter((r) => !emptyRow(r)).map((r) => [r.guys, r.days, !!r.guys_auto, r.guys_follow === undefined ? null : r.guys_follow,
      r.hours_seed === undefined ? null : r.hours_seed, r.guys_typed === true, r.hours_typed === true, r.enabled === false, cost(r)])]) });
}

function typeCrew(b, tab, rowId, guys, days) {
  const i = idxIn(secOf(b.api.root(), tab), rowId);
  [["guys", guys], ["days", days]].forEach((kv) => {
    const sel = '[data-lab="' + i + '"][data-k="' + kv[0] + '"]';
    if (i >= 0 && b.doc.querySelector(sel)) P.typeInto(b, sel, kv[1]);
  });
}

/** The estimator's own say on the carrier's Travel Labor row, through its boxes and slider on the Labor step. False when there is no row to say it on. */
function applyVariant(b, name) {
  const m = b.api.root();
  const car = B.travelCarrier(m);
  const i = idxIn(secOf(m, car), "travel");
  if (i < 0) return false;
  b.api.show(car);
  b.api.go(1);
  const sel = (k) => '[data-lab="' + i + '"][data-k="' + k + '"]';
  if (name === "typed") { P.typeInto(b, sel("guys"), "3"); P.typeInto(b, sel("days"), "5"); }
  else if (name === "clearHours") P.typeInto(b, sel("days"), "");
  else if (name === "clearGuys") P.typeInto(b, sel("guys"), "");
  else if (name === "off") P.clickOn(b, '[data-on-lab="' + i + '"]');
  else throw new Error("no such variant " + name);
  return true;
}

/** What the carrier's row must read for each variant, wherever the carrier is. */
function variantHolds(name, r) {
  if (!r) return false;
  if (name === "typed") return r.guys === "3" && r.days === "5" && r.guys_typed === true && r.hours_typed === true && r.guys_auto === false && r.enabled !== false;
  if (name === "clearHours") return r.days === "" && r.hours_typed === true;
  if (name === "clearGuys") return r.guys === "" && r.guys_typed === true;
  if (name === "off") return r.enabled === false;
  return false;
}

/** Every rule above, asked of one page. `ctx.variant` is the estimator's variant on this path, if any. Returns [[code, detail], ...]. */
function judge(b, ctx) {
  const bad = [];
  const f = facts(b);
  const m = f.m;
  const live = f.entries.filter((e) => e.kind !== "off");
  const carrierEntry = f.entries.filter((e) => e.tab === f.carrier)[0];
  const note = (code, detail) => bad.push([code, detail]);

  f.entries.forEach((e) => { if (travelRows(e.section).length > 1) note("ONE_ROW", e.tab + " holds " + travelRows(e.section).length + " Travel Labor rows"); });

  const priced = [];
  f.entries.filter((e) => e.kind === "base").forEach((e) => travelRows(e.section).forEach((r) => { if (cost(r) > 0) priced.push(e.tab + " " + fmtRow(r)); }));
  if (priced.length > 1) note("ONE_DRIVE", priced.join(" + ") + " (carrier " + f.carrier + ")");

  live.forEach((e) => travelRows(e.section).forEach((r) => {
    if (cost(r) > 0 && r.guys_auto === true && !r.guys_follow && !owned(r)) note("MAN_DAYS", e.tab + " " + fmtRow(r) + " is on the man-days");
  }));

  const crow = travelRows(carrierEntry && carrierEntry.section)[0] || null;
  if (f.far && carrierEntry && carrierEntry.layout !== "gyp") {
    if (!crow) note("FAR_CARRIER", "carrier " + f.carrier + " has no Travel Labor row at " + f.miles + " miles");
    else if (!owned(crow)) {
      const hours = B.driveHoursFor(f.miles);
      const ok = crow.guys_follow === "crew" && crow.guys_auto === true && crow.days === hours && crow.hours_seed === hours && crow.guys === B.crewSize(m);
      if (!ok) note("FAR_CARRIER", "carrier " + f.carrier + " row " + fmtRow(crow) + " is not the crew (" + B.crewSize(m) + ") x " + hours + " hours");
    }
  }
  if (f.far && carrierEntry && carrierEntry.layout === "gyp" && crow && !owned(crow) && (!blank(crow.days) || !blank(crow.guys) || crow.guys_follow || cost(crow) > 0)) {
    note("GYP_UNFILLED", "Gyp carrier row " + fmtRow(crow) + " was filled");
  }
  if (!f.far) {
    live.forEach((e) => travelRows(e.section).forEach((r) => { if (!owned(r) && cost(r) > 0) note("LOCAL", e.tab + " " + fmtRow(r) + " prices a drive on a " + (f.miles === null ? "job with no distance" : f.miles + " mile job")); }));
  }

  f.entries.filter((e) => e.tab !== f.carrier && e.kind !== "option").forEach((e) => travelRows(e.section).forEach((r) => {
    if (!owned(r) && (!blank(r.days) || r.guys_follow || typeof r.hours_seed === "number")) note("STALE", e.tab + " (" + e.kind + ") still holds the filled row " + fmtRow(r));
  }));

  if (ctx && ctx.variant) {
    if (!crow || !variantHolds(ctx.variant, crow)) note("OWNED", ctx.variant + " is not what carrier " + f.carrier + " holds: " + fmtRow(crow) + " " + JSON.stringify(crow));
    f.entries.filter((e) => e.tab !== f.carrier && e.kind !== "option").forEach((e) => travelRows(e.section).forEach((r) => {
      if (cost(r) > 0) note("OWNED", ctx.variant + " was left priced on " + e.tab + " (" + e.kind + "): " + fmtRow(r));
    }));
  }
  return bad;
}

/** The price the page would save for the model it holds, by forcing a save. Run after everything else is read: it arms and fires a timer. */
function lumpNow(b) {
  b.api.saveSoon();
  b.clock.fire();
  return lumpOf(b.store.blob);
}

const report = { mode: RAW_MODE, depth: DEPTH, runs: 0, reopens: 0, plain: 0, violations: {}, samples: {}, crashes: [] };
function record(code, label, detail) {
  const v = (report.violations[code] = (report.violations[code] || 0) + 1);
  const s = (report.samples[code] = report.samples[code] || []);
  if (s.length < 12 || label.length < s[s.length - 1][0].length) { s.push([label, detail]); s.sort((x, y) => x[0].length - y[0].length || (x[0] < y[0] ? -1 : 1)); if (s.length > 12) s.pop(); }
  return v;
}

/** Take a step from the draft `saved`: returns the page after it, saved, plus the label's piece. `step` is { job, crew } | { variant } | { base } | { copy }. */
async function take(saved, step, distanceAnswer) {
  const here = typeOfBlob(saved);
  const answer = { distance: Object.assign({}, distanceAnswer, { miles: distanceAnswer.miles === null ? null : 300 }) };
  if (step.job) {
    const b = await open(Object.assign(clone(saved), { work_type: step.job }), answer);
    b.api.go(1);
    await settle();
    const plain = step.job === here && !step.crew;
    const quiet = { armed: b.clock.armed(), saves: b.rec.saves.length, asked: (b.rec.distanceBodies || []).length };
    if (step.crew) { const c = STEP_CREW[step.job]; typeCrew(b, c[0], c[1], c[2], c[3]); }
    const was = plain ? shape(b) : null;
    if (!plain) b.clock.fire();
    return { b: b, plain: plain, quiet: quiet, was: was, piece: step.job + (step.crew ? "+crew" : "") };
  }
  const b = await open(Object.assign(clone(saved), { work_type: here }), answer);
  b.api.go(1);
  await settle();
  if (step.variant) {
    if (!applyVariant(b, step.variant)) return null;
    b.clock.fire();
    return { b: b, plain: false, piece: "[" + step.variant + "]" };
  }
  if (step.copy) {
    const sel = '[data-sh-act="copy"]';
    if (!b.doc.querySelector(sel)) return null;
    P.clickOn(b, sel);
    await settle();
    b.clock.fire();
    return { b: b, plain: false, piece: "copy" };
  }
  b.doc.fire("change", { target: P.need(b, '[data-sh-base="' + step.base + '"]') });
  if (!b.doc.querySelector('[data-sh-act="base-yes"]')) return null;
  P.clickOn(b, '[data-sh-act="base-yes"]');
  await settle();
  b.clock.fire();
  return { b: b, plain: false, piece: "base:" + step.base };
}

/** The base changes the Sheets panel of this page offers (one to a radio), other than the base it already has. */
function basePicks(b) {
  const html = String((b.doc.getElementById("sheets-panel") || {}).innerHTML || "");
  const out = [];
  const have = B.baseOf(b.api.root()).ids;
  [...html.matchAll(/data-sh-base="([^"]*)"/g)].forEach((mm) => {
    const v = mm[1].replace(/&quot;/g, '"').replace(/&amp;/g, "&");
    const ids = v === "combined" ? B.combinedPair(b.api.root()) : [v];
    if (!ids || (ids.length === have.length && ids.every((id) => have.indexOf(id) >= 0))) return;
    if (out.indexOf(mm[1]) < 0) out.push(mm[1]);
  });
  return out;
}

function stepsFor(page, path) {
  const used = path.some((p) => p.variant);
  const out = [];
  if (MODE === "far" || MODE === "local" || MODE === "unknown") {
    TYPES.forEach((t) => { out.push({ job: t }); out.push({ job: t, crew: true }); });
  } else if (MODE === "mixed") {
    TYPES.forEach((t) => out.push({ job: t }));
    if (!used) VARIANTS.forEach((v) => out.push({ variant: v }));
  } else if (SHEETS) {
    TYPES.forEach((t) => out.push({ job: t }));
    basePicks(page).forEach((v) => out.push({ base: v }));
    out.push({ copy: true });
  } else {
    TYPES.forEach((t) => out.push({ job: t }));
  }
  return out;
}

async function judgeStep(label, got, parent, ctx, leaf) {
  const b = got.b;
  report.runs++;
  judge(b, ctx).forEach(([code, detail]) => record(code, label, detail));
  if (got.plain) {
    report.plain++;
    if (got.quiet.armed !== 0 || got.quiet.saves !== 0 || got.quiet.asked !== 0) {
      record("PLAIN_REOPEN", label, "armed " + got.quiet.armed + " saves " + got.quiet.saves + " lookups " + got.quiet.asked);
    }
    if (parent && got.was !== parent.shape) record("PLAIN_REOPEN", label, "the rows moved: " + got.was.slice(0, 160) + " VS " + parent.shape.slice(0, 160));
    if (parent && lumpNow(b) !== parent.lump) record("REOPEN_AGREES", label, "the plain reopen prices " + lumpOf(b.store.blob) + ", the draft saved " + parent.lump);
  } else if (leaf) {
    // A step that ended the path is reopened plain too (every other step has a plain child, which holds the same question).
    const saved = clone(b.store.blob);
    const again = await open(clone(saved), { distance: DISTANCES.far });
    again.api.go(1);
    await settle();
    report.reopens++;
    const quiet = again.clock.armed() === 0 && again.rec.saves.length === 0;
    const same = shape(again) === shape(b);
    const lump = lumpNow(again);
    if (!quiet || !same || lump !== lumpOf(saved)) {
      record("REOPEN_AGREES", label, (quiet ? "" : "the reopen armed a save; ") + (same ? "" : "the rows moved on reopen: " + shape(b).slice(0, 150) + " VS " + shape(again).slice(0, 150) + "; ") +
        (lump === lumpOf(saved) ? "" : "saved " + lumpOf(saved) + " reopened " + lump));
    }
  }
}

async function walk(label, got, path, depth, ctx, distanceAnswer) {
  const b = got.b;
  const saved = clone(b.store.blob);
  const node = { shape: shape(b), lump: lumpOf(saved) };
  if (depth === 0) return;
  const steps = stepsFor(b, path);
  for (const step of steps) {
    let child = null;
    const childLabel = label + " -> " + (step.job ? step.job + (step.crew ? "+crew" : "") : step.variant ? "[" + step.variant + "]" : step.copy ? "copy" : "base:" + step.base);
    try { child = await take(saved, step, distanceAnswer); } catch (e) {
      report.crashes.push([childLabel, String((e && e.stack) || e).slice(0, 400)]);
      record("CRASH", childLabel, String((e && e.message) || e).slice(0, 200));
      continue;
    }
    if (!child) continue;
    const ctx2 = step.variant ? { variant: step.variant } : ctx;
    try { await judgeStep(childLabel, child, node, ctx2, depth === 1); } catch (e) {
      report.crashes.push([childLabel, String((e && e.stack) || e).slice(0, 400)]);
      record("CRASH", childLabel, "while judging: " + String((e && e.message) || e).slice(0, 200));
      continue;
    }
    await walk(childLabel, child, path.concat([step]), depth - 1, ctx2, distanceAnswer);
  }
}

/** The 54 sequences the audit of 7d32336 found pricing the drive twice: start type, then steps (a "+" is the crew typed on the new carrier). */
const AUDIT54 = [
  "epoxy epoxy polish combo", "epoxy epoxy polish combo+", "epoxy epoxy polish+ combo", "epoxy epoxy polish+ combo+", "epoxy epoxy+ polish combo", "epoxy epoxy+ polish combo+",
  "epoxy epoxy+ polish+ combo", "epoxy epoxy+ polish+ combo+", "epoxy polish polish combo", "epoxy polish polish combo+", "epoxy polish polish+ combo", "epoxy polish polish+ combo+",
  "epoxy polish combo", "epoxy polish combo combo", "epoxy polish combo combo+", "epoxy polish combo+", "epoxy polish combo+ combo", "epoxy polish combo+ combo+",
  "epoxy polish+ polish combo", "epoxy polish+ polish combo+", "epoxy polish+ polish+ combo", "epoxy polish+ polish+ combo+", "epoxy polish+ combo", "epoxy polish+ combo combo",
  "epoxy polish+ combo combo+", "epoxy polish+ combo+", "epoxy polish+ combo+ combo", "epoxy polish+ combo+ combo+", "epoxy gyp polish combo", "epoxy gyp polish combo+",
  "epoxy gyp polish+ combo", "epoxy gyp polish+ combo+", "epoxy gyp+ polish combo", "epoxy gyp+ polish combo+", "epoxy gyp+ polish+ combo", "epoxy gyp+ polish+ combo+",
  "polish epoxy polish combo+", "polish epoxy polish+ combo+", "polish epoxy+ polish combo", "polish epoxy+ polish combo+", "polish epoxy+ polish+ combo", "polish epoxy+ polish+ combo+",
  "combo epoxy polish combo+", "combo epoxy polish+ combo+", "combo epoxy+ polish combo", "combo epoxy+ polish combo+", "combo epoxy+ polish+ combo", "combo epoxy+ polish+ combo+",
  "gyp epoxy polish combo+", "gyp epoxy polish+ combo+", "gyp epoxy+ polish combo", "gyp epoxy+ polish combo+", "gyp epoxy+ polish+ combo", "gyp epoxy+ polish+ combo+",
];

async function newBid(start, distanceAnswer) {
  const c = START_CREW[start];
  const b = await open(DRAFTS[start](), { distance: distanceAnswer });
  b.api.go(1);
  await settle();
  typeCrew(b, c[0], c[1], c[2], c[3]);
  b.clock.fire();
  return { b: b };
}

async function main() {
  const distanceKey = DIST_MODE || (MODE === "local" ? "local" : MODE === "unknown" ? "unknown" : "far");
  if (!DISTANCES[distanceKey]) throw new Error("no such distance " + distanceKey);
  const distanceAnswer = DISTANCES[distanceKey];
  if (MODE === "audit54") {
    const exact = {};
    for (const line of AUDIT54) {
      const words = line.split(" ");
      let got = await newBid(words[0], DISTANCES.far);
      let label = "start:" + words[0];
      let parent = { shape: shape(got.b), lump: lumpOf(got.b.store.blob) };
      judge(got.b, null).forEach(([code, detail]) => record(code, label, detail));
      for (const w of words.slice(1)) {
        const step = { job: w.replace("+", ""), crew: w.indexOf("+") >= 0 };
        label += " -> " + w;
        got = await take(clone(got.b.store.blob), step, DISTANCES.far);
        await judgeStep(label, got, parent, null, false);
        parent = { shape: shape(got.b), lump: lumpOf(got.b.store.blob) };
      }
      const f = facts(got.b);
      exact[line] = { dollars: f.entries.filter((e) => e.kind === "base").reduce((t, e) => t + travelRows(e.section).reduce((s, r) => s + cost(r), 0), 0),
        carrier: f.carrier, jobType: f.jobType };
    }
    report.exact = exact;
    report.sequences = AUDIT54.length;
    return;
  }
  const starts = TYPES;
  for (const start of starts) {
    let first = await newBid(start, distanceAnswer);
    let ctx = null;
    const label0 = "start:" + start;
    if (MODE_VARIANT) {
      const reopened = await open(clone(first.b.store.blob), { distance: distanceAnswer });
      reopened.api.go(1);
      await settle();
      if (!applyVariant(reopened, MODE_VARIANT)) { report.skipped = (report.skipped || 0) + 1; continue; }
      reopened.clock.fire();
      first = { b: reopened };
      ctx = { variant: MODE_VARIANT };
    }
    const label = label0 + (ctx ? "[" + MODE_VARIANT + "]" : "");
    report.runs++;
    judge(first.b, ctx).forEach(([code, detail]) => record(code, label, detail));
    await walk(label, first, [], DEPTH, ctx, distanceAnswer);
  }
}

main().then(() => {
  report.crashes = report.crashes.slice(0, 5);
  console.log(JSON.stringify(report));
}).catch((e) => { console.error(e && e.stack || e); process.exit(1); });
