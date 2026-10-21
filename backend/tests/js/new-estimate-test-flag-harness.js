"use strict";
/* X1: A NEW v2 ESTIMATE IS FILED UNDER TEST FROM THE INSTANT IT EXISTS, HOWEVER THE ESTIMATOR LEAVES THE INTAKE.
 *
 * The v2 board's "New estimate" opens the v2 intake for a NEW project, and the intake says so ("saved as a NEW
 * test project, under the Test tab"). Round 1 kept that promise with an INTENT that shared.js applied after the
 * project's first PUT came back: a second request, sent from a page that had to still be there to see the first
 * one answered. Every way of leaving the intake that did not wait (a double press, a press while the autosave was
 * in flight, a link, Back, a closed tab) left a row BORN UNFILED on the board where staff work, and the estimate
 * page then forked a "(beta test)" copy of the estimator's own project. The audit of round 1 named the cause:
 * the filing was a separate request.
 *
 * THE SEED. shared.js's setState says, in the project's own blob, what the browser started it as: is_test true
 * for a project started as a test (the v2 board's New estimate, the Projects page's Test tab), false for one
 * started from the Active tab, from the project's FIRST WRITE. The backend inserts a new row as sent, and on an
 * update keeps a server-owned key the stored row already has, so the first PUT, by whatever path it leaves, creates
 * the row already filed, and a project somebody has since filed as real is never re-flagged by a stale blob. There
 * is no second request, so there is nothing to lose, to get wrong, to leave unanswered or to wait for.
 *
 * WHAT RUNS. The REAL shared.js, js/polish-sandbox.js, js/polish-intake.js and js/index.js (the live intake), whole,
 * in the browser model of _world.js (virtual time; a page's timers and replies die with it; a keepalive request
 * survives its page and its reply is never seen), and the body of js/projects.js's "+ New project" click handler.
 * The intake is driven as a person drives it: the board's "+ New estimate", typed boxes, Continue (its form's own
 * submit handler), a link, a closed tab. The estimate page is the first lines of polish-estimate.js init(): shared.js
 * settles the draft, then the REAL sandbox decides which draft to write to. Nothing is lifted by name and nothing is
 * stubbed that the bug passes through.
 *
 * Every fact is read OFF THE SERVER and off the pages after everything has settled: which rows exist, what each
 * was BORN as, what it is now, which draft the estimate page ended on and what it told the estimator, which requests
 * went and whether anybody saw the reply. test_v2_new_estimate_test_flag.py holds each to what the product promises
 * and breaks a copy of each source one line at a time to prove the check can go red.
 *
 *   model               the browser model itself (and the two server rules the seed leans on). See the test.
 *   fast, fastAfterAutosave, slow   Continue at 100 ms, 700 ms and 3.3 s after the last edit.
 *   gcTab               "+ New" from the GC tab, which starts the bid with { audience: "GC" } already in the draft.
 *   sweep               the fast flows over eight sets of latencies (a slow save, a slow /test, both, a slow link, a page
 *                       that boots at once or late, everything fast): sixteen runs.
 *   doublePress         Continue pressed twice 60 ms apart, at 100 ms and at 700 ms.
 *   pressDuringAutosave Continue pressed while the 2.5 s autosave PUT is in flight (a slow server).
 *   overlappingSaves    typing goes on while the autosave PUT is in flight, then Continue: two saves overlap.
 *   exits               every other way out, at 0.1 to 3.2 s after the last edit: the "2 · Estimate" link, Back (the
 *                       Projects page) and a closed tab; the project is reopened a minute later when the estimate page
 *                       was not where the estimator went.
 *   overtaken           a closed tab at 700 ms, and then ANOTHER new estimate is started and left: the one localStorage
 *                       slot of round 1 is overwritten, and the first project must not be left behind unfiled.
 *   closedThenReopened  the tab goes at 700 ms (a keepalive PUT whose reply nobody sees), and the board's link to the
 *                       project is followed a minute later.
 *   filingFaults        a /test that fails or never answers, six ways, under Continue at 100 ms and the step link at 700 ms:
 *                       nothing needs /test any more, so nothing may depend on it.
 *   bootWhileFilingHangs the estimator leaves a new project for ANOTHER project's page while /test never answers, and that
 *                       page must boot (round 1's putDraft waited on the filing, and the next page's boot on putDraft).
 *   saveFaults          the save itself fails: once (the next save must carry the project's flag) and for good (nothing may
 *                       be claimed filed, and the estimate page must say it is not saved).
 *   feedback            Continue's button while it waits: disabled and relabelled, ignored on a second press, and given back
 *                       when the browser does not go.
 *   synced              the record of what the server holds, written as the first save is stored.
 *   v1                  the Projects page's "+ New project" on each tab, through the LIVE intake's Continue.
 *   realThroughIntake, realProject, anotherProjects, saidReal, filingAsReal, aCopy, staleStart
 *                       projects that are NOT a new test project of this browser's: copied as ever, never flagged.
 *
 * Usage: node new-estimate-test-flag-harness.js <frontend-dir>   ->   one line of JSON
 */
const path = require("path");
const W = require("./_world.js");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2] || path.join(__dirname, "..", "..", "..", "frontend"));

/** The milliseconds Continue will wait for the save, read off the page so the test does not restate it. */
function saveWaitMs() {
  const m = /var SAVE_WAIT_MS = (\d+);/.exec(L.read(path.join(ROOT, "js", "polish-intake.js")));
  return m ? Number(m[1]) : null;
}

/** What a run leaves behind, as the tests read it. */
function summary(w, id, extra) {
  const rep = w.report();
  const row = w.rows.get(id);
  return Object.assign({
    id: id,
    x: rep.rows[id] || null,
    xData: row ? { project_name: row.data.project_name, address: row.data.address } : null,
    beta: rep.rows[id + "-beta"] || null,
    rowIds: Object.keys(rep.rows),
    rows: rep.rows,
    intent: rep.intent,
    synced: rep.synced,
    blob: rep.blob,
    estimate: w.pageReport(w.pageOf("estimate")),
    requests: rep.requests,
    navs: rep.navs,
    pages: rep.pages.map((p) => ({ label: p.label, bornAt: p.bornAt, diedAt: p.diedAt, settled: p.settled, crashed: p.crashed })),
    console: rep.console,
    unmocked: rep.unmocked,
    runaway: rep.runaway,
  }, extra || {});
}

/** The Continue button as a person sees it right now. */
const button = (page) => { const b = page.el("continue-btn"); return { disabled: !!b.disabled, label: b.textContent }; };

/** The board's "+ New estimate" on the Direct tab, driven by a script of timed steps (`at` is ms after the page opened):
 *    { at, type: [name, value] }   a box is typed into
 *    { at, press: true }           Continue is pressed (the answer says whether the page was asked, and the button after)
 *    { at, follow: true | href }   the intake is left by a link (true: the "2 · Estimate" step link; "/blank.html" for a
 *                                  closed tab, "/projects.html" for Back)
 *    { at, sample: "name" }        the Continue button is read
 *  Everything is left to finish afterwards. */
async function drive(opts) {
  const o = Object.assign({ steps: [], world: {}, faults: [], gc: false, blocked: false, settleMs: undefined }, opts || {});
  const w = W.createWorld(Object.assign({ frontend: ROOT }, o.world));
  const intake = await w.startNewEstimate({ gc: o.gc });
  const id = intake.draftId();
  const pendingAtOpen = w.localKey("intent");
  const noteAtOpen = intake.text("sandbox-note");
  const labelAtOpen = button(intake).label;
  o.faults.forEach((f) => w.fault(f));
  if (o.blocked) w.navigationBlocked = true;
  const t0 = w.now();
  const presses = [];
  const samples = {};
  let continueAt = null;
  for (const s of o.steps.slice().sort((a, b) => a.at - b.at)) {
    const dt = t0 + s.at - w.now();
    if (dt > 0) await w.advance(dt);
    if (s.type) intake.type(s.type[0], s.type[1]);
    if (s.press) {
      if (continueAt === null) continueAt = w.now();
      const accepted = intake.pressContinue() !== false;
      presses.push({ at: w.now() - t0, accepted: accepted, button: button(intake) });
    }
    if (s.follow) intake.follow(s.follow === true ? "/polish-estimate.html?d=" + id : s.follow);
    if (s.sample) samples[s.sample] = Object.assign({ at: w.now() - t0 }, button(intake));
  }
  await w.settle(o.settleMs);
  return { w: w, id: id, intake: intake, result: summary(w, id, {
    continueAt: continueAt, presses: presses, samples: samples, pendingAtOpen: pendingAtOpen, noteAtOpen: noteAtOpen,
    labelAtOpen: labelAtOpen, startedAt: t0, name: o.name || null }) };
}

const TYPED = [{ at: 0, type: ["project_name", "Fast Job"] }, { at: 0, type: ["address", "100 Main St"] }];

/** A fast or slow Continue: the typed boxes, then one press `waitMs` after the last edit. */
async function newEstimate(opts) {
  const o = Object.assign({ waitMs: 100 }, opts || {});
  const run = await drive(Object.assign({}, o, { steps: TYPED.concat([{ at: o.waitMs, press: true }]) }));
  return run.result;
}

// ── the browser model, checked on its own ─────────────────────────────────────────────────────────────────
async function modelChecks() {
  const w = W.createWorld({ frontend: ROOT });
  const page = w.load("/blank.html");
  const seen = {};
  let fired = false;
  const put = (id, keepalive) => page.win.fetch("/api/draft/" + id, {
    method: "PUT", body: JSON.stringify({ data: { n: id } }), keepalive: keepalive,
  }).then(() => { seen[id] = true; });
  put("early", false);                                            // sent at once, back long before the page goes
  page.win.setTimeout(() => { put("late", false); }, 120);        // arrives before the page goes, comes back after
  page.win.setTimeout(() => { fired = true; }, 400);              // a timer that outlives the page
  page.win.addEventListener("pagehide", () => {
    put("keepalive", true);                                       // sent as the page goes
    put("plain", false);
  });
  w.navigate(page, "/blank.html");
  await w.settle();
  const outcome = (id) => (w.requestsLog().filter((r) => r.id === id)[0] || {}).outcome || null;
  // A page that does not go (the load was stopped), and a Continue that is disabled.
  const stay = await (async () => {
    const v = W.createWorld({ frontend: ROOT });
    const p = v.load("/blank.html");
    v.navigationBlocked = true;
    v.navigate(p, "/blank.html");
    await v.settle();
    return { dead: p.dead, leaving: p.leaving, blockedNavs: v.navs.filter((n) => n.blocked).length, pages: v.pages.length };
  })();
  return {
    commitMs: w.net.commitMs,
    pageDiedAt: page.diedAt,
    earlyStored: w.rows.has("early"), earlyReplySeen: !!seen.early, earlyOutcome: outcome("early"),
    lateStored: w.rows.has("late"), lateReplySeen: !!seen.late, lateOutcome: outcome("late"),
    keepaliveStored: w.rows.has("keepalive"), keepaliveReplySeen: !!seen.keepalive, keepaliveOutcome: outcome("keepalive"),
    plainStored: w.rows.has("plain"), plainReplySeen: !!seen.plain, plainOutcome: outcome("plain"),
    timerOfAGonePageFired: fired,
    stay: stay,
    serverOwnedKeys: W.SERVER_OWNED.slice(),
    savingKeepsServerOwnedKeys: await (async () => {
      const v = W.createWorld({ frontend: ROOT });
      const p = v.load("/blank.html");
      v.seed("owned", { is_test: true, archived: false, assigned_estimator: "kyle@x.test", project_name: "A" });
      p.win.fetch("/api/draft/owned", { method: "PUT", body: JSON.stringify({ data: { project_name: "B", is_test: false } }) });
      await v.settle();
      const d = v.rows.get("owned").data;
      return { is_test: d.is_test, archived: d.archived, assigned_estimator: d.assigned_estimator, project_name: d.project_name };
    })(),
    // The two rules the seed leans on, as the model has them: a first save is inserted as sent (so a blob that says
    // is_test creates the row filed, or filed as real), and a save of a row that has never said keeps what the blob says.
    firstSaveIsInsertedAsSent: await (async () => {
      const v = W.createWorld({ frontend: ROOT });
      const p = v.load("/blank.html");
      p.win.fetch("/api/draft/seeded", { method: "PUT", body: JSON.stringify({ data: { project_name: "A", is_test: true } }) });
      p.win.fetch("/api/draft/seeded-real", { method: "PUT", body: JSON.stringify({ data: { project_name: "A", is_test: false } }) });
      p.win.fetch("/api/draft/plain", { method: "PUT", body: JSON.stringify({ data: { project_name: "A" } }) });
      await v.settle();
      return { seeded: v.row("seeded"), seededReal: v.row("seeded-real"), plain: v.row("plain") };
    })(),
    aSaveSeedsAKeyTheRowNeverHad: await (async () => {
      const v = W.createWorld({ frontend: ROOT });
      const p = v.load("/blank.html");
      v.seed("keyless", { project_name: "A" });
      p.win.fetch("/api/draft/keyless", { method: "PUT", body: JSON.stringify({ data: { project_name: "A", is_test: true } }) });
      await v.settle();
      return v.row("keyless");
    })(),
    // What the model answers on each route the fix touches, so the driver can put the real routes beside it.
    routeAnswers: await (async () => {
      const v = W.createWorld({ frontend: ROOT });
      const p = v.load("/blank.html");
      const out = {};
      const ask = async (key, url, init) => {
        let got = null;
        p.win.fetch(url, init).then(async (r) => { const j = await r.json(); got = { status: r.status, keys: Object.keys(j).sort(), body: j }; });
        await v.settle();
        out[key] = got;
      };
      await ask("getMissing", "/api/draft/m1");
      await ask("putNew", "/api/draft/m1", { method: "PUT", body: JSON.stringify({ data: { project_name: "A" } }) });
      await ask("getThere", "/api/draft/m1");
      await ask("fileThere", "/api/draft/m1/test", { method: "POST", body: JSON.stringify({ is_test: true }) });
      await ask("fileMissing", "/api/draft/m2/test", { method: "POST", body: JSON.stringify({ is_test: true }) });
      await ask("putSeeded", "/api/draft/m3", { method: "PUT", body: JSON.stringify({ data: { project_name: "A", is_test: true } }) });
      await ask("getSeeded", "/api/draft/m3");
      return out;
    })(),
    fileMissingRow: await (async () => {
      const v = W.createWorld({ frontend: ROOT });
      const p = v.load("/blank.html");
      let body = null;
      p.win.fetch("/api/draft/nobody/test", { method: "POST", body: JSON.stringify({ is_test: true }) })
        .then((r) => r.json()).then((j) => { body = j; });
      await v.settle();
      return body;
    })(),
  };
}

// ── latencies ─────────────────────────────────────────────────────────────────────────────────────────────
const COMBOS = [
  { name: "defaults", world: {} },
  { name: "a slow save", world: { proc: { PUT: 1500 } } },
  { name: "a slow filing", world: { proc: { TEST: 900 } } },
  { name: "a slow save and a slow filing", world: { proc: { PUT: 800, TEST: 800 } } },
  { name: "a slow link", world: { net: { up: 120, down: 120 } } },
  { name: "the next page boots at once", world: { net: { bootMs: 0, commitMs: 10 } } },
  { name: "the next page boots late", world: { net: { bootMs: 900, commitMs: 600 } } },
  { name: "everything fast", world: { proc: { PUT: 5, TEST: 5, GET: 1 }, net: { up: 5, down: 5, commitMs: 40, bootMs: 20 } } },
];

async function sweep() {
  const runs = [];
  for (const combo of COMBOS) {
    for (const waitMs of [100, 700]) {
      const r = await newEstimate({ waitMs: waitMs, world: combo.world });
      runs.push({ combo: combo.name, waitMs: waitMs, x: r.x, beta: r.beta, intent: r.intent,
        note: r.estimate && r.estimate.note, estimateDraft: r.estimate && r.estimate.draftId, id: r.id });
    }
  }
  return runs;
}

// ── overlapping saves and repeated presses ────────────────────────────────────────────────────────────────
async function doublePress(waitMs) {
  const run = await drive({ steps: TYPED.concat([{ at: waitMs, press: true }, { at: waitMs + 60, press: true }]) });
  return run.result;
}

/** The autosave PUT goes at 3.1 s (600 ms of debounce, then 2.5 s) and a slow server keeps it in flight for a second. */
async function pressDuringAutosave() {
  const run = await drive({ world: { proc: { PUT: 800 } }, steps: TYPED.concat([{ at: 3300, press: true }]) });
  return run.result;
}

async function overlappingSaves() {
  const run = await drive({ world: { proc: { PUT: 800 } },
    steps: TYPED.concat([{ at: 3300, type: ["address", "200 Main St"] }, { at: 3400, press: true }]) });
  return run.result;
}

// ── every other way out of the intake ─────────────────────────────────────────────────────────────────────
const DOORS = { link: true, back: "/projects.html", close: "/blank.html" };
const EXIT_WAITS = [100, 600, 700, 1500, 3000, 3100, 3200];

/** The new estimate typed into, then left by a door that is not Continue, `waitMs` after the last edit. When the estimator
 *  did not go to the estimate page, the project is reopened in the v2 intake a minute later. */
async function exit(door, waitMs, opts) {
  const o = Object.assign({ faults: [], reopen: door !== "link" }, opts || {});
  const run = await drive({ faults: o.faults, steps: TYPED.concat([{ at: waitMs, follow: DOORS[door] }]) });
  const w = run.w;
  const out = run.result;
  if (!o.reopen) return Object.assign(out, { door: door, waitMs: waitMs });
  const before = { x: out.x, beta: out.beta };
  await w.advance(60000);
  const intake = w.load("/polish-intake.html?d=" + run.id);
  await w.settle();
  return Object.assign(summary(w, run.id, { door: door, waitMs: waitMs, before: before,
    intakeNote: intake.text("sandbox-note"), intakeDraft: intake.draftId(), intakeLoading: intake.text("loading") }));
}

async function exits() {
  const out = [];
  for (const door of Object.keys(DOORS)) for (const waitMs of EXIT_WAITS) out.push(await exit(door, waitMs));
  return out;
}

/** F2's own words: the first project is left unfiled by a closed tab, and the NEXT new estimate overwrites the one slot
 *  round 1 kept its filing in. The first project must already be filed by then. */
async function overtaken() {
  const first = await drive({ steps: TYPED.concat([{ at: 700, follow: "/blank.html" }]) });
  const w = first.w;
  await w.advance(30000);
  const second = await w.startNewEstimate();
  const secondId = second.draftId();
  second.type("project_name", "Second Job");
  await w.advance(700);
  second.follow("/blank.html");
  await w.settle();
  return summary(w, first.id, { secondId: secondId, second: w.row(secondId) });
}

async function closedThenReopened() {
  const run = await exit("close", 700);
  return run;
}

// ── a /test that goes wrong, and a /test that never answers ───────────────────────────────────────────────
const FILING_FAULTS = ["http500", "okfalse", "network", "hang", "html", "gone"];

async function filingFaults() {
  const out = { continue: {}, link: {} };
  for (const mode of FILING_FAULTS) {
    out.continue[mode] = await newEstimate({ waitMs: 100, faults: [{ route: "TEST", mode: mode }] });
    out.link[mode] = await exit("link", 700, { faults: [{ route: "TEST", mode: mode }] });
  }
  return out;
}

/** The estimator leaves a new project (a link to ANOTHER project's estimate page, 100 ms after the last edit) while /test
 *  never answers. shared.js hydrates the other project, and first flushes the blob of the one it is evicting: on round 1
 *  that flush waited for the filing, and the other page never booted. With a control run that has no fault. */
const OTHER = "real-2";
async function bootWhileFilingHangs(faults) {
  const w = W.createWorld({ frontend: ROOT });
  w.seed(OTHER, { project_name: "Overland Park Lab", address: "9 Metcalf Ave", city: "Overland Park", state: "KS", zip: "66212",
    work_type: "polish", audience: "Direct", polish_sf: 4000,
    polish_estimate: { version: 2, conditions: { local: true, prevailing_wage: false, taxable: true, remodel_tax: false } } });
  const intake = await w.startNewEstimate();
  const id = intake.draftId();
  (faults || []).forEach((f) => w.fault(f));
  intake.type("project_name", "Fast Job");
  intake.type("address", "100 Main St");
  // 100 ms after the last edit: nothing of the new project has reached the server (the page's own save here is a plain
  // request, dropped with the page), so the page that boots next finds the new project's blob in the one slot and
  // saves it itself before it takes the other project's place.
  await w.advance(100);
  intake.follow("/polish-estimate.html?d=" + OTHER);
  await w.settle();
  const last = w.pages[w.pages.length - 1];
  return summary(w, id, { other: w.row(OTHER), lastPage: w.pageReport(last), lastKind: last.kind, lastDraft: last.win.TW.getDraftId(),
    requestsToOther: w.requestsLog().filter((r) => r.id === OTHER).map((r) => r.method) });
}

// ── the save itself goes wrong ────────────────────────────────────────────────────────────────────────────
async function saveFaults() {
  const out = {};
  for (const mode of ["http500", "okfalse", "network"]) {
    // the first save fails once: Continue leaves, the estimate page saves the project itself
    out["once_" + mode] = await newEstimate({ waitMs: 100, faults: [{ route: "PUT", mode: mode, times: 1 }] });
  }
  for (const mode of ["http500", "okfalse", "network"]) {
    // the server will not take any save for the whole run, and comes back at the end
    const run = await drive({ faults: [{ route: "PUT", mode: mode }], steps: TYPED.concat([{ at: 100, press: true }]) });
    const w = run.w;
    const during = summary(w, run.id, { name: "down_" + mode });
    const page = w.pageOf("estimate");
    w.faults.length = 0;                                                // the server is back
    page.win.TW.setState({ address: "300 Main St" });                   // the estimator carries on: the next autosave
    await w.settle();
    out["down_" + mode] = Object.assign(during, { afterRecovery: summary(w, run.id) });
  }
  return out;
}

// ── Continue's button ─────────────────────────────────────────────────────────────────────────────────────
async function feedback() {
  const out = {};
  // while the save is out: a server that takes 1.5 s, read at 50 ms and at 1 s, and after the page has gone
  out.saving = (await drive({ world: { proc: { PUT: 1500 } },
    steps: TYPED.concat([{ at: 100, press: true }, { at: 150, sample: "early" }, { at: 1100, sample: "late" }]) })).result;
  // a second press while it waits, and one a moment after the first
  out.pressedTwice = (await drive({ world: { proc: { PUT: 1500 } },
    steps: TYPED.concat([{ at: 100, press: true }, { at: 160, press: true }, { at: 600, press: true }]) })).result;
  // a server that never answers: the button says so for the whole wait and the page leaves at the bound
  out.hung = (await drive({ faults: [{ route: "PUT", mode: "hang", times: 1 }],
    steps: TYPED.concat([{ at: 100, press: true }, { at: 4000, sample: "midway" }]) })).result;
  // the browser does not go: the button is given back, and Continue works again
  const blocked = await drive({ blocked: true, steps: TYPED.concat([{ at: 100, press: true }]) });
  const w = blocked.w;
  const stillThere = w.pages[w.pages.length - 1];
  out.blocked = Object.assign(blocked.result, { restored: button(blocked.intake), pageAlive: !stillThere.dead });
  blocked.intake.pressContinue();
  await w.settle();
  out.blocked.pressedAgain = { navs: w.navs.length, button: button(blocked.intake) };
  // a save that fails at once does not leave the button stuck either (and the browser still does not go)
  const failed = await drive({ faults: [{ route: "PUT", mode: "network", times: 1 }], blocked: true,
    steps: TYPED.concat([{ at: 100, press: true }]) });
  out.failedSave = Object.assign(failed.result, { restored: button(failed.intake) });
  return out;
}

/** The shape round 1 kept the flag out of the blob to avoid: a human files the new project as a REAL bid after it was born
 *  filed as a test, while the estimator's tab still holds a blob that says is_test true and goes on saving. The server keeps
 *  what the row has (drafts.save_draft keep_server_owned), so the tab's next save must not undo the human's answer. */
async function staleTab() {
  const run = await drive({ steps: TYPED.concat([{ at: 100, press: true }]) });
  const w = run.w;
  const page = w.pageOf("estimate");
  const admin = w.load("/blank.html");                       // the Projects page's "Test?" button, pressed by somebody
  admin.win.fetch("/api/draft/" + run.id + "/test", { method: "POST", body: JSON.stringify({ is_test: false }) });
  await w.settle();
  const filedReal = w.row(run.id);
  page.win.TW.setState({ address: "300 Main St" });          // the tab goes on working
  await w.settle();
  return summary(w, run.id, { filedReal: filedReal, blobFlag: (w.blob() || {}).is_test });
}

// ── the record of what the server holds ───────────────────────────────────────────────────────────────────
async function synced() {
  const run = await drive({ steps: TYPED.concat([{ at: 100, press: true }]) });
  const page = run.w.pageOf("estimate");
  return Object.assign(run.result, { digestNow: page.win.TW.draftDigest(page.win.TW.getState()) });
}

// ── the live intake, through the Projects page's "+ New project" ──────────────────────────────────────────
/** "+ New project" on `tab`, a name and an address typed into the LIVE intake, its Continue pressed, and the Estimate step
 *  that follows (the spreadsheet's, which writes the draft as it loads). `closeAfterMs`: the estimator closes the Estimate
 *  step's tab that long after it opened, before its own first save has landed. */
async function v1Start(tab, opts) {
  const o = Object.assign({ closeAfterMs: null }, opts || {});
  const w = W.createWorld({ frontend: ROOT });
  const intake = await w.pressNewProject({ tab: tab });
  const id = intake.draftId();
  const intentOnArrival = w.localKey("intent");
  intake.type("project_name", "Walk-in Job");
  intake.type("address", "5 Elm St");
  await w.advance(1500);
  const pressedAt = w.now();
  intake.pressContinue();
  if (o.closeAfterMs !== null) {
    await w.advance(150 + 120 + o.closeAfterMs);           // the commit, the next page's boot, then the wait
    w.pageOf("review").follow("/blank.html");
  }
  await w.settle();
  return summary(w, id, { tab: tab, intentOnArrival: intentOnArrival, pressedAt: pressedAt,
    nextPage: (w.pageOf("review") || {}).label || null });
}

async function v1() {
  const out = {};
  for (const tab of ["test", "active", "all"]) {
    out[tab] = await v1Start(tab);
    out[tab + "Closed"] = await v1Start(tab, { closeAfterMs: 600 });
  }
  return out;
}

// ── projects that are NOT a new test project of this browser's ────────────────────────────────────────────
const REAL = "real-1";
const realData = () => ({
  project_name: "Nearman Creek", address: "1 Water Works Dr", city: "Kansas City", state: "KS", zip: "66101",
  bid_date: "2026-09-01", work_type: "polish", audience: "Direct", polish_sf: 8000,
  polish_estimate: { version: 2, conditions: { local: true, prevailing_wage: false, taxable: true, remodel_tax: false } },
});

async function realThroughIntake() {
  const w = W.createWorld({ frontend: ROOT });
  w.seed(REAL, realData());
  w.holdLocally(REAL, realData());          // this browser has been working on it, so opening it hydrates nothing
  const intake = w.load("/polish-intake.html?d=" + REAL);
  await w.settle();
  const noteOnOpen = intake.text("sandbox-note");
  const draftOnOpen = intake.draftId();
  intake.type("address", "2 Water Works Dr");
  await w.advance(100);
  intake.pressContinue();
  await w.settle();
  return summary(w, REAL, { noteOnOpen: noteOnOpen, draftOnOpen: draftOnOpen, real: w.row(REAL),
    realAddress: (w.rows.get(REAL).data || {}).address });
}

/** A project the server holds, opened on the estimate page by a browser that has been working on it. */
const PROJECT = "proj-9";
const projectData = (over) => Object.assign({
  project_name: "Wichita Warehouse", address: "100 Main St", city: "Wichita", state: "KS", zip: "67202",
  work_type: "polish", audience: "Direct", polish_sf: 6000,
  polish_estimate: { version: 2, conditions: { local: true, prevailing_wage: false, taxable: true, remodel_tax: false } },
}, over || {});

async function openProject(opts) {
  const o = Object.assign({ row: {}, intent: undefined }, opts || {});
  const w = W.createWorld({ frontend: ROOT });
  w.seed(PROJECT, projectData(o.row));
  w.holdLocally(PROJECT, projectData());
  if (o.intent !== undefined) w.local.setItem(W.KEYS.intent, o.intent);
  w.load("/polish-estimate.html?d=" + PROJECT);
  await w.settle();
  return summary(w, PROJECT, { pendingBefore: o.intent === undefined ? null : o.intent });
}

(async () => {
  const out = {};
  out.saveWaitMs = saveWaitMs();
  out.model = await modelChecks();
  out.fast = await newEstimate({ waitMs: 100 });
  out.fastAfterAutosave = await newEstimate({ waitMs: 700 });
  out.slow = await newEstimate({ waitMs: 3300 });
  out.gcTab = await newEstimate({ waitMs: 100, gc: true });
  out.sweep = await sweep();
  out.doublePress = { fast: await doublePress(100), afterAutosave: await doublePress(700) };
  out.pressDuringAutosave = await pressDuringAutosave();
  out.overlappingSaves = await overlappingSaves();
  out.exits = await exits();
  out.overtaken = await overtaken();
  out.closedThenReopened = await closedThenReopened();
  out.filingFaults = await filingFaults();
  out.bootWhileFilingHangs = {
    control: await bootWhileFilingHangs([]),
    hang: await bootWhileFilingHangs([{ route: "TEST", mode: "hang" }]),
    http500: await bootWhileFilingHangs([{ route: "TEST", mode: "http500" }]),
  };
  out.saveFaults = await saveFaults();
  out.feedback = await feedback();
  out.staleTab = await staleTab();
  out.synced = await synced();
  out.v1 = await v1();
  out.realThroughIntake = await realThroughIntake();
  out.realProject = await openProject({});
  out.anotherProjects = await openProject({ intent: "other-1:1" });
  out.saidReal = await openProject({ row: { is_test: false }, intent: PROJECT + ":1" });
  out.filingAsReal = await openProject({ intent: PROJECT + ":0" });
  out.aCopy = await openProject({ row: { beta_sandbox_of: "some-real-project", project_name: "Wichita Warehouse (beta test)" },
    intent: PROJECT + ":1" });
  // A pending start for a project that has been worked on and SENT since (the stale case): it has files, a sent proposal.
  out.staleStart = await openProject({ row: { generate_result: { files: ["a.xlsx"] }, proposal_payload: { sent: true } },
    intent: PROJECT + ":1" });
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e && e.stack || e); process.exit(1); });
