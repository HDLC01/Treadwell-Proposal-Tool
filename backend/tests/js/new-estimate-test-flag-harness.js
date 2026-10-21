"use strict";
/* X1: A NEW v2 ESTIMATE IS FILED UNDER TEST, HOWEVER FAST THE ESTIMATOR LEAVES THE INTAKE.
 *
 * The v2 board's "New estimate" opens the v2 intake for a NEW project, and the intake says so ("saved as a NEW
 * test project, under the Test tab"). The promise is kept by an INTENT, not by the save: polish-sandbox.js
 * (markNewProjectAsTest) writes treadwell.proposal_tool.new_is_test = "<id>:1" while the page opens, and
 * shared.js (applyPendingTestIntent) POSTs /api/draft/<id>/test the moment the project's FIRST PUT comes back
 * stored, because the server has no row to file before that.
 *
 * "The moment the PUT comes back" needs a page that is still there. Press Continue within about three seconds of
 * the last edit and there is not one: onSubmit saved and sent the browser to the estimate page in the same
 * breath, so the first PUT left through shared.js's pagehide handler (keepalive), and its reply went to a page
 * that no longer existed. The row was created, nothing filed it, and it sat on the Direct Projects board where
 * staff work. The estimate page then found a real, unfiled project and forked a "(beta test)" copy of it, which
 * is what its sandbox does with a real bid. Walked on staging 59922bd, 2026-10-21: 2 of 2 fast flows did this,
 * 3 of 3 slow ones (a pause of three seconds or more, which lets the 2.5 s autosave PUT land on the live
 * intake) filed correctly.
 *
 * WHAT RUNS. The REAL shared.js, js/polish-sandbox.js and js/polish-intake.js, whole, in the browser model of
 * _world.js (virtual time; a page's timers and replies die with it; a keepalive request survives its page and
 * its reply is never seen). The intake is driven as a person drives it: the board's "+ New estimate", a few
 * typed boxes, Continue (its form's own submit handler). The estimate page is the first lines of
 * polish-estimate.js init(): shared.js settles the draft, then the REAL sandbox decides which draft to write to.
 * Nothing is lifted by name and nothing is stubbed that the bug passes through.
 *
 * Every fact is read OFF THE SERVER and off the pages after everything has settled: which rows exist, whether
 * each is filed, which draft the estimate page ended on and what it told the estimator, which requests went
 * and whether anybody saw the reply. test_v2_new_estimate_test_flag.py holds each to what the product promises,
 * and breaks a copy of each source one line at a time to prove the check can go red.
 *
 *   model               the browser model itself: a request that has arrived is finished by the server whatever
 *                       happens to the page, a keepalive request sent as the page goes survives it, a plain one does
 *                       not, a reply to a page that is gone is seen by nobody, the old page runs until the new
 *                       document commits, and its timers never fire after it has gone. (If any of these were
 *                       wrong the bug could not be reproduced here, or could be reproduced for the wrong reason.)
 *   fast                Continue pressed 100 ms after the last edit: nothing has been saved yet.
 *   fastAfterAutosave   Continue at 700 ms: the 600 ms autosave has run, and the 2.5 s timer that sends it is armed.
 *   slow                Continue at 3.3 s: the autosave PUT has landed on the live page. The path that always worked.
 *   slowFiling          a fast Continue with a server that takes 600 ms to file the project (the filing is a second
 *                       request, so a page that leaves while it is in flight races the estimate page's first read).
 *   sweep               the fast flows over eight sets of latencies (a slow save, a slow filing, a slow link, a page
 *                       that boots at once or late): the answer must not depend on who is faster.
 *   hang                the first PUT is never answered: Continue must not trap the estimator on the page.
 *   offline             the first PUT fails at once (no network): Continue must not wait for anything.
 *   failedFiling        the server will not file the project, three ways (HTTP 500, a 200 carrying {"ok": false}, no
 *                       network): the project is left unfiled and is not claimed to be filed.
 *   hangFiling          the filing is never answered: Continue must not trap the estimator waiting for it either.
 *   realThroughIntake   a REAL project opened in the v2 intake: it is copied (the sandbox's whole job) and the real
 *                       row is never written to or filed, through Continue and onto the estimate page.
 *
 * Usage: node new-estimate-test-flag-harness.js <frontend-dir>   ->   one line of JSON
 */
const path = require("path");
const W = require("./_world.js");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2] || path.join(__dirname, "..", "..", "..", "frontend"));

const clone = (v) => JSON.parse(JSON.stringify(v));

/** The seconds Continue will wait for the save, read off the page so the test does not restate it. */
function saveWaitMs() {
  const m = /var SAVE_WAIT_MS = (\d+);/.exec(L.read(path.join(ROOT, "js", "polish-intake.js")));
  return m ? Number(m[1]) : null;
}

/** What a run leaves behind, as the tests read it. */
function summary(w, id, extra) {
  const rep = w.report();
  return Object.assign({
    id: id,
    x: rep.rows[id] || null,
    beta: rep.rows[id + "-beta"] || null,
    rowIds: Object.keys(rep.rows),
    intent: rep.intent,
    estimate: w.pageReport(w.pageOf("estimate")),
    requests: rep.requests,
    navs: rep.navs,
    pages: rep.pages.map((p) => ({ label: p.label, bornAt: p.bornAt, diedAt: p.diedAt, crashed: p.crashed })),
    console: rep.console,
    unmocked: rep.unmocked,
  }, extra || {});
}

/** The board's "+ New estimate" on the Direct tab: the intake on a fresh draft, a name and an address typed,
 *  Continue pressed `waitMs` after the last edit, then everything is left to finish. */
async function newEstimate(opts) {
  const o = Object.assign({ waitMs: 100, world: {}, faults: [] }, opts || {});
  const w = W.createWorld(Object.assign({ frontend: ROOT }, o.world));
  const intake = await w.startNewEstimate();
  const id = intake.draftId();
  const pendingAtOpen = w.localKey("intent");
  const noteAtOpen = intake.text("sandbox-note");
  o.faults.forEach((f) => w.fault(f));
  intake.type("project_name", "Fast Job");
  intake.type("address", "100 Main St");
  await w.advance(o.waitMs);
  const continueAt = w.now();
  intake.pressContinue();
  await w.settle();
  return summary(w, id, { continueAt: continueAt, pendingAtOpen: pendingAtOpen, noteAtOpen: noteAtOpen, name: o.name || null });
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
  return {
    commitMs: w.net.commitMs,
    pageDiedAt: page.diedAt,
    earlyStored: w.rows.has("early"), earlyReplySeen: !!seen.early, earlyOutcome: outcome("early"),
    lateStored: w.rows.has("late"), lateReplySeen: !!seen.late, lateOutcome: outcome("late"),
    keepaliveStored: w.rows.has("keepalive"), keepaliveReplySeen: !!seen.keepalive, keepaliveOutcome: outcome("keepalive"),
    plainStored: w.rows.has("plain"), plainReplySeen: !!seen.plain, plainOutcome: outcome("plain"),
    timerOfAGonePageFired: fired,
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

// ── a REAL project through the v2 intake ──────────────────────────────────────────────────────────────────
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

(async () => {
  const out = {};
  out.saveWaitMs = saveWaitMs();
  out.model = await modelChecks();
  out.fast = await newEstimate({ waitMs: 100 });
  out.fastAfterAutosave = await newEstimate({ waitMs: 700 });
  out.slow = await newEstimate({ waitMs: 3300 });
  out.slowFiling = await newEstimate({ waitMs: 100, world: { proc: { TEST: 600 } } });
  out.sweep = await sweep();
  out.hang = await newEstimate({ waitMs: 100, faults: [{ route: "PUT", mode: "hang", times: 1 }] });
  out.offline = await newEstimate({ waitMs: 100, faults: [{ route: "PUT", mode: "network", times: 1 }] });
  out.failedFiling = {};
  for (const mode of ["http500", "okfalse", "network"]) {
    out.failedFiling[mode] = await newEstimate({ waitMs: 100, faults: [{ route: "TEST", mode: mode }] });
  }
  out.hangFiling = await newEstimate({ waitMs: 100, faults: [{ route: "TEST", mode: "hang", times: 1 }] });
  out.realThroughIntake = await realThroughIntake();
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e && e.stack || e); process.exit(1); });
