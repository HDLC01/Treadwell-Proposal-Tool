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
 *   bareLink, bareLinkAfterAutosave   the same Continue at 100 ms and 700 ms on the v2 intake opened by a BARE link on a project nobody started
 *                       (no start under its id): the page's own word is the only thing that says test (round 4; the board now leaves a start).
 *   gcTab               "+ New" from the GC tab, which starts the bid with { audience: "GC" } already in the draft.
 *   sweep               the fast flows over eight sets of latencies (a slow save, a slow /test, both, a slow link, a page
 *                       that boots at once or late, everything fast): sixteen runs.
 *   doublePress         Continue pressed twice 60 ms apart, at 100 ms and at 700 ms.
 *   pressDuringAutosave Continue pressed while the 2.5 s autosave PUT is in flight (a slow server).
 *   overlappingSaves    typing goes on while the autosave PUT is in flight, then Continue: two saves overlap.
 *   exits               every other way out, at 0.1 to 3.2 s after the last edit: the "2 · Estimate" link, Back (the
 *                       Projects page), a closed tab and a reload; the project is reopened a minute later when the
 *                       estimate page was not where the estimator went.
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
 *   stampRules          shared.js's stamp on its own: which start it applies (a project's own key, or a v2 page's own word held in
 *                       memory), to which project, on which write, what it leaves behind, what New project mints, and that a copy
 *                       with nothing in it is sent as it is.
 *   synced              the record of what the server holds, written as the first save is stored.
 *   v1                  the Projects page's "+ New project" on each tab, through the LIVE intake's Continue.
 *   realThroughIntake, realProject, anotherProjects, saidReal, filingAsReal, aCopy, staleStart
 *                       projects that are NOT a new test project of this browser's: copied as ever, never flagged.
 *   bigDraft            a saved test project too big for a keepalive request: Continue's wait is what gets its last edit to
 *                       the server, because the save that goes as the page leaves is refused by the browser.
 *   v1Real              a real spreadsheet bid opened in the LIVE intake from the Projects page and saved, with another
 *                       project's start (or the bare "1" an abandoned "+ New project" leaves) in the one slot: saved as
 *                       the real bid it is.
 *
 * ROUND 3 (the audit of round 2: a project's start is its own, and a look at a page starts nothing):
 *   looks               "+ New project" on each Projects tab, a LOOK at the v2 intake and at the v2 estimate page (the sidebar's
 *                       link), Back to the live intake, the bid typed there: born as its tab said, and nothing left by the look (F1).
 *   activeThenTypedInV2 the look that is not a look: typed into on a v2 page, a project is a test whichever tab started it (pinned).
 *   gcBoardThenLook     the GC board's New proposal from each tab, then a look at the v2 intake: no test row for a real bid (F1).
 *   abandonedBoardStart a board's New proposal (the real startNewProposal), nothing typed, another project opened: the abandoned
 *                       blob is flushed under what it was started as; with its save refused, with its own word, Direct (F2).
 *   twoTabs             two tabs each starting a project (the v2 board, or the Projects page's Test and Active tabs), either one
 *                       typing first: each keeps its own start (F3).
 *   bigDraftLeftEarly   a draft too big for keepalive, left inside the debounce: no keepalive request the browser will refuse (F5).
 *
 * ROUND 4 (the audit of round 3, F1 to F6):
 *   bytesNotCharacters  a draft under the keepalive limit as characters and over it as UTF-8 bytes (2-, 3- and 4-byte characters),
 *                       left inside the debounce: sent as a plain request, never a keepalive one the browser refuses (F6).
 *   foreignBlob         tab A's project in the shared slot while tab B's page (the v2 intake, then the v2 estimate page) is on its own id:
 *                       the page must stop, and nothing may be saved under B's id (F5).
 *   savingAnotherProjectsBlob  the sandbox's own save asked to write a blob stamped for another project under this id (F5).
 *   abandonedV2Start    the v2 board's New estimate (the real startNew), Direct and GC, and the estimator opens another project: the GC
 *                       tab's first save refused, and the page left before it heard from the server (F2).
 *   v2BoardThenLiveIntake  a project the v2 board started, written first by the LIVE intake (F2).
 *   staleNewPage        a v2 page that decided its project was NEW, and another tab (the live intake) that has since written it: the stale
 *                       page must stop saving and say so, never emptying what the other tab saved (F1).
 *   staleQueuedCopy     two v2 tabs on one new project: the first tab's queued save, of its older copy, must not fire over what the second
 *                       tab has saved since (F1).
 *   twoSavesPending     the v2 intake left with both its own timer and shared.js's pending (a small draft; the first save sent slow; a ~36 KiB
 *                       draft that fits one keepalive request and not two): ONE save is sent as the page goes, carrying the newest edit (F4).
 *   betaDoor            the live intake's "Continue with Estimating Tool v2" on a new bid from each Projects tab, fast and slow server: the v2
 *                       page must find the saved project (copy a real one, edit a test one), never stop for a row that is on its way (F3).
 *   betaDoorFeedback    the door while it waits (disabled, "Saving..."), on a server that hangs, on a save that fails, and in a browser that
 *                       does not go (F3).
 *   abandonedWithWork   a board's New proposal whose blob holds work that never went through setState: flushed, born as its tab said.
 *                       (abandonedBoardStart, with nothing typed, is never flushed.)
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

/** The milliseconds the live intake's beta door will wait for the save, and how long it takes to give itself back, read off the page. */
function betaDoorMs() {
  const src = L.read(path.join(ROOT, "js", "index.js"));
  const wait = /const SAVE_WAIT_MS = (\d+);/.exec(src);
  const back = /const GIVE_BACK_MS = (\d+);/.exec(src);
  return { wait: wait ? Number(wait[1]) : null, giveBack: back ? Number(back[1]) : null };
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
    starts: rep.starts,
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

/** The board's "+ New estimate" on the Direct tab (`bare`: the v2 intake opened by a bare link on a project with no start), driven by a script of timed steps (`at` is ms after the page opened):
 *    { at, type: [name, value] }   a box is typed into
 *    { at, press: true }           Continue is pressed (the answer says whether the page was asked, and the button after)
 *    { at, follow: true | href }   the intake is left by a link (true: the "2 · Estimate" step link; "/blank.html" for a
 *                                  closed tab, "/projects.html" for Back)
 *    { at, sample: "name" }        the Continue button is read
 *  Everything is left to finish afterwards. */
async function drive(opts) {
  const o = Object.assign({ steps: [], world: {}, faults: [], faultsAtOpen: [], gc: false, blocked: false, settleMs: undefined }, opts || {});
  const w = W.createWorld(Object.assign({ frontend: ROOT }, o.world));
  o.faultsAtOpen.forEach((f) => w.fault(f));                     // a server that is already down as the intake opens
  const intake = o.bare ? await w.openBareV2Intake({ gc: o.gc }) : await w.startNewEstimate({ gc: o.gc });
  const id = intake.draftId();
  const startAtOpen = w.startOf(id);
  const noteAtOpen = intake.text("sandbox-note");
  const rowAtOpen = w.row(id);
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
    if (s.follow) intake.follow(typeof s.follow === "function" ? s.follow(id) : s.follow === true ? "/polish-estimate.html?d=" + id : s.follow);
    if (s.sample) samples[s.sample] = Object.assign({ at: w.now() - t0 }, button(intake));
  }
  await w.settle(o.settleMs);
  return { w: w, id: id, intake: intake, result: summary(w, id, {
    continueAt: continueAt, presses: presses, samples: samples, startAtOpen: startAtOpen, noteAtOpen: noteAtOpen, rowAtOpen: rowAtOpen,
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
  // The one size rule: a keepalive body over 64 KiB is refused on the spot, a plain one of that size and a small keepalive one are not.
  const cap = await (async () => {
    const v = W.createWorld({ frontend: ROOT });
    const p = v.load("/blank.html");
    const big = JSON.stringify({ data: { n: "x".repeat(70 * 1024) } });
    const small = JSON.stringify({ data: { n: "x" } });
    const out = {};
    const send = (key, id, body, keepalive) => p.win.fetch("/api/draft/" + id, { method: "PUT", body: body, keepalive: keepalive })
      .then(() => { out[key] = "sent"; }, (e) => { out[key] = String(e && e.message); });
    const sent = [send("keepaliveBig", "ka-big", big, true), send("plainBig", "plain-big", big, false),
                  send("keepaliveSmall", "ka-small", small, true)];
    await v.settle();                                  // virtual time moves only when the model is asked to run it
    await Promise.all(sent);
    out.stored = Array.from(v.rows.keys()).sort();
    out.outcomes = v.requestsLog().map((r) => r.id + ":" + r.outcome);
    return out;
  })();
  // The budget is shared: two keepalive bodies that each fit but not together are not both sent (the second is refused on the spot while
  // the first is in flight), a plain request has no share of it, the size is counted in UTF-8 BYTES (3-byte characters), and a share comes
  // back once its request has been answered.
  const budget = await (async () => {
    const v = W.createWorld({ frontend: ROOT });
    const p = v.load("/blank.html");
    const out = {};
    const body = (n, ch) => JSON.stringify({ data: { n: (ch || "x").repeat(n) } });
    const send = (key, id, text, keepalive) => p.win.fetch("/api/draft/" + id, { method: "PUT", body: text, keepalive: keepalive })
      .then(() => { out[key] = "sent"; }, (e) => { out[key] = String(e && e.message); });
    const early = [send("first", "b1", body(40 * 1024), true), send("second", "b2", body(40 * 1024), true),
                   send("plain", "b3", body(40 * 1024), false)];
    // 30,000 three-byte characters are 30,000 characters long and 90,000 bytes: over the cap for the browser, under it for `.length`
    const wide = body(30000, "€");
    out.wideChars = wide.length;
    out.wideBytes = Buffer.byteLength(wide, "utf8");
    early.push(send("wide", "b4", wide, true));
    await v.settle();
    await Promise.all(early);
    out.heldAfterReplies = p.keepaliveBytes;
    const later = send("afterReply", "b5", body(40 * 1024), true);
    await v.settle();
    await later;
    out.stored = Array.from(v.rows.keys()).sort();
    return out;
  })();
  // A request the server is slow over finishes after one sent later (what "slow" is for).
  const slow = await (async () => {
    const v = W.createWorld({ frontend: ROOT });
    const p = v.load("/blank.html");
    v.fault({ route: "PUT", mode: "slow", ms: 500, times: 1 });
    p.win.fetch("/api/draft/s1", { method: "PUT", body: JSON.stringify({ data: { n: 1 } }) });
    p.win.fetch("/api/draft/s2", { method: "PUT", body: JSON.stringify({ data: { n: 2 } }) });
    await v.settle();
    const log = v.requestsLog();
    return { doneAt: { s1: log[0].doneAt, s2: log[1].doneAt }, outcomes: [log[0].outcome, log[1].outcome] };
  })();
  return {
    keepaliveCap: cap,
    sharedBudget: budget,
    slowRequest: slow,
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
// Where each door leads, given the project's id: the "2 · Estimate" step link, Back (the Projects page), a closed tab (a page that
// runs nothing) and a reload (the intake asked for again at the address shared.js put the project's id in).
const DOORS = {
  link: (id) => "/polish-estimate.html?d=" + id,
  back: () => "/projects.html",
  close: () => "/blank.html",
  reload: (id) => "/polish-intake.html?d=" + id,
};
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
  // The GC tab starts the bid with something in the draft, so the sandbox saves it as the intake opens: with the server
  // already down. The blob holds no flag of its own yet (nothing has been written through setState), so the sandbox has to arm the
  // start again, or the first write after the server is back creates the project unfiled.
  {
    const run = await drive({ gc: true, faultsAtOpen: [{ route: "PUT", mode: "http500" }],
      steps: TYPED.concat([{ at: 100, press: true }]) });
    const w = run.w;
    const during = summary(w, run.id, { name: "gcDown" });
    const page = w.pageOf("estimate");
    w.faults.length = 0;
    page.win.TW.setState({ address: "300 Main St" });
    await w.settle();
    out.gcDown_http500 = Object.assign(during, { noteAtOpen: run.result.noteAtOpen, afterRecovery: summary(w, run.id) });
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

/** The rules of the stamp in shared.js's setState, executed on the real file (a page that has shared.js and nothing else, on the
 *  draft id it minted): which start it applies, to which project, on which write, and what it leaves in the one slot. */
async function stampRules() {
  const fresh = async () => {
    const w = W.createWorld({ frontend: ROOT });
    const page = w.load("/projects.html");
    await w.settle();
    return { w: w, TW: page.win.TW, id: page.win.TW.getDraftId() };
  };
  // `starts` is every start the browser holds, { id: "1" | "0" }: each project's own key.
  const seen = (w, id) => ({ id: id, blob: w.blob(), starts: w.starts(), bare: w.localKey("intent"), draftId: w.localKey("draftId") });
  const out = {};
  // a start for THIS project: said by the first write that has content, and used up by it
  { const r = await fresh(); r.w.setStart(r.id, "1"); r.TW.setState({ project_name: "A" }); out.test = seen(r.w, r.id); }
  { const r = await fresh(); r.w.setStart(r.id, "0"); r.TW.setState({ project_name: "A" }); out.real = seen(r.w, r.id); }
  {
    const r = await fresh();
    r.w.setStart(r.id, "1");
    r.TW.setState({});                                                  // nothing in it yet
    out.empty = seen(r.w, r.id);
    r.TW.setState({ project_name: "A" });                               // the first write that has something in it
    out.emptyThenContent = seen(r.w, r.id);
  }
  { const r = await fresh(); r.w.setStart(r.id, "1"); r.TW.setState({ project_name: "A", is_test: false }); out.says = seen(r.w, r.id); }
  // another project's start is under that project's own key: not read here, not used up here
  { const r = await fresh(); r.w.setStart("someone-else", "1"); r.TW.setState({ project_name: "A" }); out.other = seen(r.w, r.id); }
  // the ONE SLOT of an earlier version is read by nothing, whatever it holds
  {
    const r = await fresh();
    r.w.local.setItem(W.KEYS.intent, "1");
    r.TW.setState({ project_name: "A" });
    out.legacyBare = seen(r.w, r.id);
    r.w.local.setItem(W.KEYS.intent, r.id + ":1");
    r.TW.setState({ project_name: "B" });
    out.legacyBound = seen(r.w, r.id);
  }
  {
    const r = await fresh();
    r.w.setStart(r.id, "1");
    r.TW.setState({ project_name: "A" });
    r.TW.setState({ project_name: "B" });                               // a later write: nothing left to say
    out.later = seen(r.w, r.id);
  }
  // THIS PAGE'S OWN WORD (a v2 page's sandbox found no row for the project: TW.startsAsTest), held in memory, said by the first
  // write that has content, over the Active tab's start and never over a word the blob already holds
  { const r = await fresh(); r.TW.startsAsTest(r.id); r.TW.setState({ project_name: "A" }); out.mark = seen(r.w, r.id); }
  { const r = await fresh(); r.w.setStart(r.id, "0"); r.TW.startsAsTest(r.id); r.TW.setState({ project_name: "A" }); out.markOverReal = seen(r.w, r.id); }
  {
    const r = await fresh();
    r.TW.startsAsTest(r.id);
    r.TW.setState({});                                                  // nothing in it yet: the word is not spent
    out.markEmpty = seen(r.w, r.id);
    r.TW.setState({ project_name: "A" });
    out.markEmptyThenContent = seen(r.w, r.id);
  }
  { const r = await fresh(); r.TW.startsAsTest(r.id); r.TW.setState({ project_name: "A", is_test: false }); out.markSaysFalse = seen(r.w, r.id); }
  { const r = await fresh(); r.TW.startsAsTest("someone-else"); r.TW.setState({ project_name: "A" }); out.markOther = seen(r.w, r.id); }
  // ... and never over WORK this page did not write: the blob already holds work with no word when the page decides, so nothing says the project
  // was created by this page. (The sandbox stops on such a project, so no page reaches this; the rule is held here, where it can be asked.)
  { const r = await fresh(); r.w.holdLocally(r.id, { project_name: "Written elsewhere" }); r.TW.startsAsTest(r.id); r.TW.setState({ address: "A" }); out.markOverWork = seen(r.w, r.id); }
  // A START IS SPENT WHEN THE SERVER HAS STORED A COPY THAT CARRIES IT, not when a write says it. A write only says it (the blob carries
  // it), so a blob that another tab's New project wipes before the save went does not take the start with it: the next write says it again.
  {
    const r = await fresh();
    r.w.setStart(r.id, "1");
    r.TW.setState({ project_name: "A" });
    out.stampKeepsTheStart = seen(r.w, r.id);
    r.w.local.removeItem(W.KEYS.state);                                 // the shared blob is wiped before the queued save went
    r.TW.setState({ project_name: "B" });
    out.saidAgainAfterAWipe = seen(r.w, r.id);
    const sent = r.TW.flushState();
    await r.w.settle();
    await sent;
    out.spentOnceStored = Object.assign(seen(r.w, r.id), { puts: r.w.requestsLog().filter((q) => q.route === "PUT").map((q) => q.sentIsTest) });
  }
  {
    const r = await fresh();
    r.w.setStart(r.id, "0");
    r.w.fault({ route: "PUT", mode: "http500", times: 1 });
    r.TW.setState({ project_name: "A" });
    const refused = r.TW.flushState();
    await r.w.settle();
    await refused;
    out.refusedSpendsNothing = Object.assign(seen(r.w, r.id), { puts: r.w.requestsLog().filter((q) => q.route === "PUT").map((q) => q.sentIsTest) });
    r.TW.setState({ project_name: "A2" });                              // the next save, which the server takes, carries it again
    const taken = r.TW.flushState();
    await r.w.settle();
    await taken;
    out.takenSpends = Object.assign(seen(r.w, r.id), { puts: r.w.requestsLog().filter((q) => q.route === "PUT").map((q) => q.sentIsTest) });
  }
  {
    const r = await fresh();                                            // the page's own word, spent the same way
    r.TW.startsAsTest(r.id);
    r.TW.setState({ project_name: "A" });
    out.markKeptAfterSaying = seen(r.w, r.id);
    r.w.local.removeItem(W.KEYS.state);
    r.TW.setState({ project_name: "B" });
    out.markSaidAgainAfterAWipe = seen(r.w, r.id);
    const sent = r.TW.flushState();
    await r.w.settle();
    await sent;
    r.w.local.removeItem(W.KEYS.state);
    r.TW.setState({ project_name: "C" });                               // stored: the word is spent, a later blob is not stamped again
    out.markSpentOnceStored = seen(r.w, r.id);
  }
  // what "+ New project" leaves: a position mints the project's id and its start; All and Inactive say nothing
  {
    const r = await fresh();
    r.w.local.setItem(W.KEYS.intent, "1");                              // the earlier version's slot, still in this browser
    const before = r.w.localKey("draftId");
    r.TW.setNewProjectTestIntent(true);
    out.newTest = Object.assign(seen(r.w, r.id), { before: before });
    r.TW.setNewProjectTestIntent(false);
    out.newReal = Object.assign(seen(r.w, r.id), { before: out.newTest.draftId });
    r.w.local.setItem(W.KEYS.intent, "0");
    r.TW.setNewProjectTestIntent(null);
    out.newSaidNothing = Object.assign(seen(r.w, r.id), { before: out.newReal.draftId });
  }
  // a blob with nothing in it is sent as it is: putDraft does not put a start on it, and does not spend it
  {
    const r = await fresh();
    r.w.setStart(r.id, "1");
    r.TW.setState({});
    const flushed = r.TW.flushState();
    await r.w.settle();
    await flushed;
    out.emptyPut = Object.assign(seen(r.w, r.id), { puts: r.w.requestsLog().filter((q) => q.route === "PUT").map((q) => q.sentIsTest) });
  }
  return out;
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
  const startOnArrival = w.startOf(id);
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
  return summary(w, id, { tab: tab, startOnArrival: startOnArrival, pressedAt: pressedAt,
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

/** A REAL spreadsheet bid, opened in the LIVE intake from the Projects page (js/projects.js open(): "/?d=<id>&edit=1"), its address
 *  changed and Continue pressed. It has no start of its own, whatever else this browser holds: nothing at all (`clean`);
 *  ANOTHER project's start (`anotherStart`); or the start of a "+ New project" pressed on the Test tab and abandoned for this
 *  bid (`abandonedNew`: the REAL click, then the bid opened from the new project's own page). It must be saved as the real bid it
 *  is: no is_test in what is sent, none on the row, and no filing request. `startsBeforeContinue` and `starts` are what the browser
 *  holds at Continue and at the end: another project's start is neither applied to this bid nor used up by it. */
const SHEET = "sheet-3";
async function v1RealOpen(how) {
  const w = W.createWorld({ frontend: ROOT });
  w.seed(SHEET, { project_name: "Nearman Creek Epoxy", address: "1 Water Works Dr", city: "Kansas City", state: "KS", zip: "66101",
    bid_date: "2026-09-01", work_type: "epoxy", audience: "Direct", system_1_sf: 8000 });
  let abandoned = null;
  if (how === "anotherStart") {
    w.setStart("other-1", "1");
    w.load("/?d=" + SHEET + "&edit=1");
  } else if (how === "abandonedNew") {
    const fresh = await w.pressNewProject({ tab: "test" });
    abandoned = fresh.draftId();
    fresh.follow("/?d=" + SHEET + "&edit=1");
  } else {
    w.load("/?d=" + SHEET + "&edit=1");
  }
  await w.settle();                                  // shared.js reads the project, adopts it and reloads the page
  const intake = w.pageOf("v1intake");
  intake.type("address", "9 New Address");
  await w.advance(100);
  const startsBefore = w.starts();
  intake.pressContinue();
  await w.settle();
  return summary(w, SHEET, { how: how, abandoned: abandoned, startsBeforeContinue: startsBefore, draftOnIntake: intake.draftId(),
    address: (w.rows.get(SHEET).data || {}).address });
}

/** A saved TEST project whose draft is too big for a keepalive request (a real bid has measured about 89 KB: shared.js putDraft),
 *  opened in the v2 intake, its address changed and Continue pressed. The save that goes as the page leaves is refused by the
 *  browser outright, so the last edits reach the server only if Continue's own wait has sent them first. */
const BIG = "big-4";
async function bigDraft() {
  const w = W.createWorld({ frontend: ROOT });
  const data = Object.assign({ is_test: true, notes_text: "x".repeat(90 * 1024) }, {
    project_name: "Overland Park Warehouse", address: "100 Main St", city: "Overland Park", state: "KS", zip: "66212",
    work_type: "polish", audience: "Direct", polish_sf: 6000,
    polish_estimate: { version: 2, conditions: { local: true, prevailing_wage: false, taxable: true, remodel_tax: false } } });
  w.seed(BIG, data);
  w.holdLocally(BIG, data);
  const intake = w.load("/polish-intake.html?d=" + BIG);
  await w.settle();
  const noteOnOpen = intake.text("sandbox-note");
  intake.type("address", "9 Big Address");
  await w.advance(100);
  intake.pressContinue();
  await w.settle();
  return summary(w, BIG, { noteOnOpen: noteOnOpen, address: (w.rows.get(BIG).data || {}).address });
}

/** A project the server holds, opened on the estimate page by a browser that has been working on it. */
const PROJECT = "proj-9";
const projectData = (over) => Object.assign({
  project_name: "Wichita Warehouse", address: "100 Main St", city: "Wichita", state: "KS", zip: "67202",
  work_type: "polish", audience: "Direct", polish_sf: 6000,
  polish_estimate: { version: 2, conditions: { local: true, prevailing_wage: false, taxable: true, remodel_tax: false } },
}, over || {});

async function openProject(opts) {
  const o = Object.assign({ row: {}, starts: {} }, opts || {});
  const w = W.createWorld({ frontend: ROOT });
  w.seed(PROJECT, projectData(o.row));
  w.holdLocally(PROJECT, projectData());
  Object.keys(o.starts).forEach((id) => w.setStart(id, o.starts[id]));
  w.load("/polish-estimate.html?d=" + PROJECT);
  await w.settle();
  return summary(w, PROJECT, { startsBefore: o.starts });
}

// ══ ROUND 3: the start of a project is its own, and a look at a page starts nothing ══════════════════════════
// The audit of round 2 found that ONE localStorage slot held every project's start, and that a page that only LOOKED at a project
// could overwrite it. These scenarios run the real Projects-page and board starts and the real v2 pages through the model's tabs.

/** The sidebar's doors to the v2 pages: bare links, which carry no ?d= and so resume whatever project this browser is on. */
const LOOK_DOORS = { intake: "/polish-intake.html", estimate: "/polish-estimate.html" };

/** F1. "+ New project" on the Projects page's `tab` opens the live intake on a new project. The estimator LOOKS at a v2 page
 *  (follows its sidebar link and types nothing there), then goes Back to the live intake's own address (it carries the
 *  project's id) and types the bid THERE and presses Continue. A look is not a write: the project must be born what the tab
 *  said ("test", a real bid, or nothing for All), and nothing may be left on the server by the look. */
async function startThenLook(tab, door) {
  const w = W.createWorld({ frontend: ROOT });
  const v1 = await w.pressNewProject({ tab: tab });
  const id = v1.draftId();
  const startAtArrival = w.startOf(id);
  await w.advance(2000);                                   // the estimator reads the form
  v1.follow(LOOK_DOORS[door]);
  await w.settle();
  const look = w.pages[w.pages.length - 1];
  const looked = { kind: look.kind, draft: look.win.TW.getDraftId(), report: w.pageReport(look) };
  const afterLook = { start: w.startOf(id), starts: w.starts(), rows: Object.keys(w.report().rows) };
  look.follow("/?new=1&d=" + id);                          // Back
  await w.settle();
  const back = w.pageOf("v1intake");
  back.type("project_name", "Walk-in Job");
  back.type("address", "5 Elm St");
  await w.advance(1500);
  back.pressContinue();
  await w.settle();
  return summary(w, id, { tab: tab, door: door, startAtArrival: startAtArrival, looked: looked, afterLook: afterLook, backDraft: back.draftId() });
}

/** The look that is NOT a look: a project started on the Active tab and then TYPED INTO on a v2 page. Whatever a v2 page
 *  writes is a test project (Hanz, 2026-08-11), so this one is born a test. Pinned so that it is a decision and not an accident. */
async function activeThenTypedInV2() {
  const w = W.createWorld({ frontend: ROOT });
  const v1 = await w.pressNewProject({ tab: "active" });
  const id = v1.draftId();
  await w.advance(2000);
  v1.follow(LOOK_DOORS.intake);
  await w.settle();
  const v2 = w.pageOf("intake");
  v2.type("project_name", "Beta Job");
  v2.type("address", "100 Main St");
  await w.advance(100);
  v2.pressContinue();
  await w.settle();
  return summary(w, id, { startAtArrival: "0" });
}

/** F1's other door: a GC board's "+ New proposal" from the Active tab starts the bid with { audience: "GC" } already in the draft,
 *  so the v2 intake's sandbox sees a project with content and no row. Looking at it there must not create a test row. */
async function gcBoardThenLook(tab) {
  const w = W.createWorld({ frontend: ROOT });
  const v1 = await w.pressNewProposal({ pipeline: "gc", tab: tab });
  const id = v1.draftId();
  const startAtArrival = w.startOf(id);
  await w.advance(2000);
  v1.follow(LOOK_DOORS.intake);
  await w.settle();
  const look = w.pageOf("intake");
  const afterLook = { start: w.startOf(id), rows: Object.keys(w.report().rows), report: w.pageReport(look) };
  look.follow("/?new=1&d=" + id);
  await w.settle();
  const back = w.pageOf("v1intake");
  back.type("project_name", "Walk-in GC Job");
  back.type("address", "5 Elm St");
  await w.advance(1500);
  back.pressContinue();
  await w.settle();
  return summary(w, id, { tab: tab, startAtArrival: startAtArrival, afterLook: afterLook });
}

/** A project that has WRITTEN something (a condition flipped on the live intake: its first write, under its tab's start, so the blob says
 *  is_test false from the Active tab, true from Test and nothing from All) and is then looked at on a v2 page. By default the save the
 *  live intake sends as it goes has landed by then and the v2 page finds a project with a row, which it copies (a test is edited
 *  directly). With a slow server (`world.proc.PUT`) the save has NOT reached the server when the v2 page asks: it finds no row. */
async function writtenThenLook(opts) {
  const o = Object.assign({ world: {}, door: "intake", tab: "active" }, opts || {});
  const w = W.createWorld(Object.assign({ frontend: ROOT }, o.world));
  const v1 = await w.pressNewProject({ tab: o.tab });
  const id = v1.draftId();
  v1.win.TW.setState({ cell_values: { "Epoxy!B4": "Yes" } });
  const blobAfterWrite = w.blob();
  await w.advance(300);
  v1.follow(LOOK_DOORS[o.door]);
  await w.settle();
  const look = w.pages[w.pages.length - 1];
  return summary(w, id, { blobAfterWrite: blobAfterWrite, look: Object.assign(w.pageReport(look), { kind: look.kind }) });
}

/** F2 (round 3). A board's "+ New proposal" (the REAL startNewProposal of js/portal.js) opens the live intake. Nothing is typed and the
 *  estimator opens ANOTHER project from the Projects page, so shared.js decides what to do with the abandoned blob under its own id
 *  before it takes the other project's place. The GC board writes { audience: "GC" } into it before the page exists, which is no work
 *  (round 4, F2: it is never flushed, so it never becomes a nameless row). `opts.work` puts something that IS work into the blob, written
 *  without going through setState (as a page that did not say what the project was started as would leave it), which is flushed, and
 *  what the project was started as can then only travel in the PUT itself (withStart). */
const ELSEWHERE = "sheet-7";
async function abandonedBoardStart(pipeline, tab, opts) {
  const o = Object.assign({ faults: [], blobSays: undefined, work: null }, opts || {});
  const w = W.createWorld({ frontend: ROOT });
  w.seed(ELSEWHERE, { project_name: "Nearman Creek Epoxy", address: "1 Water Works Dr", city: "Kansas City", state: "KS", zip: "66101",
    bid_date: "2026-09-01", work_type: "epoxy", audience: "Direct", system_1_sf: 8000 });
  const v1 = await w.pressNewProposal({ pipeline: pipeline, tab: tab });
  const id = v1.draftId();
  o.faults.forEach((f) => w.fault(Object.assign({ id: id }, f)));          // the abandoned project's own save goes wrong
  if (o.work) w.local.setItem(W.KEYS.state, JSON.stringify(Object.assign({}, w.blob(), o.work)));   // work that never went through setState
  // a blob that already holds a word of its own (a hydrate wrote what the server says), which the start must not overrule
  if (o.blobSays !== undefined) w.local.setItem(W.KEYS.state, JSON.stringify(Object.assign({}, w.blob(), { is_test: o.blobSays })));
  const blobAtArrival = w.blob();
  const startAtArrival = w.startOf(id);
  await w.advance(3000);
  v1.follow("/?d=" + ELSEWHERE + "&edit=1");
  await w.settle();
  const last = w.pages[w.pages.length - 1];
  return summary(w, id, { pipeline: pipeline, tab: tab, blobAtArrival: blobAtArrival, startAtArrival: startAtArrival,
    other: w.row(ELSEWHERE), lastDraft: last.win.TW.getDraftId(), lastKind: last.kind, startAfter: w.startOf(id) });
}

/** F3. Two tabs of one browser, each starting its own project: one localStorage, two sessionStorages. `how` is how each tab
 *  starts ("v2": the v2 board's "+ New estimate"; "projects": the Projects page's "+ New project", the first on the Test tab and
 *  the second on the Active tab), and `first` is which tab's estimator types and presses Continue first. The project of the tab
 *  that is NOT the second one started is the one that round 2 left unfiled: its start was overwritten before its first write. */
async function twoTabs(how, first) {
  const w = W.createWorld({ frontend: ROOT });
  const tabA = w.mainTab;
  const tabB = w.openTab();
  let a, b;
  if (how === "v2") {
    a = await w.startNewEstimate({ tab: tabA });
    b = await w.startNewEstimate({ tab: tabB });
  } else {
    a = await w.pressNewProject({ tab: "test", browserTab: tabA });
    b = await w.pressNewProject({ tab: "active", browserTab: tabB });
  }
  const ids = { A: a.draftId(), B: b.draftId() };
  const startsAtOpen = w.starts();
  const typist = first === "A" ? a : b;
  typist.type("project_name", "Tab " + first + " Job");
  typist.type("address", "100 Main St");
  await w.advance(700);
  typist.pressContinue();
  await w.settle();
  const rep = w.report();
  return { how: how, first: first, ids: ids, startsAtOpen: startsAtOpen, rows: rep.rows, rowIds: Object.keys(rep.rows),
    requests: rep.requests, console: rep.console, unmocked: rep.unmocked, runaway: rep.runaway,
    pages: rep.pages.map((p) => ({ label: p.label, settled: p.settled, crashed: p.crashed, note: p.note })) };
}

/** THE ONE SHARED BLOB (found by random walks over the model, with a latency sweep, while checking F3). The browser has one copy of the draft in
 *  localStorage, and another tab's New project / New estimate WIPES it. The estimator's own page still has its 2.5 s save queued (its timer
 *  holds a copy of what it wrote), and when that page goes inside the window shared.js used to re-read the shared blob, find it empty, and PUT
 *  the empty object: it created the project's row EMPTY and UNFILED, or emptied a project that was saved. `kind`: "saved" (a saved test
 *  project open in the v2 intake, an address changed), "new" (a new test project typed into on the v2 intake) or "v1" (a project started
 *  on the Projects page's Active tab, Continue pressed on the live intake, whose save goes as the page goes). `startB` is the other tab's
 *  start ("v2": the v2 board's New estimate, "projects": the Projects page's New project on the Test tab). */
const WIPED = "wiped-1";
async function wipedByAnotherTab(kind, startB, opts) {
  const o = Object.assign({ bTypes: false, leave: "close", aTypesAgain: false }, opts || {});
  const w = W.createWorld({ frontend: ROOT });
  const tabA = w.mainTab;
  const tabB = w.openTab();
  let pageA, id;
  if (kind === "saved") {
    const data = { is_test: true, project_name: "Saved Test Job", address: "100 Main St", city: "Wichita", state: "KS", zip: "67202",
      work_type: "polish", audience: "Direct", polish_sf: 6000,
      polish_estimate: { version: 2, conditions: { local: true, prevailing_wage: false, taxable: true, remodel_tax: false } } };
    w.seed(WIPED, data);
    w.holdLocally(WIPED, data);
    pageA = w.load("/polish-intake.html?d=" + WIPED, { tab: tabA });
    await w.settle();
    id = WIPED;
    pageA.type("address", "999 New Address");
    await w.advance(700);                                  // the page's own 600 ms save has run; the 2.5 s server save is queued
  } else if (kind === "new") {
    pageA = await w.startNewEstimate({ tab: tabA });
    id = pageA.draftId();
    pageA.type("project_name", "Wiped New Job");
    pageA.type("address", "100 Main St");
    await w.advance(700);
  } else {
    pageA = await w.pressNewProject({ tab: "active", browserTab: tabA });
    id = pageA.draftId();
    pageA.type("project_name", "Wiped Walk-in");
    pageA.type("address", "5 Elm St");
    await w.advance(300);
    pageA.pressContinue();                                 // setState and location.assign in one breath: the save goes as the page goes
    await w.advance(20);
  }
  const blobBefore = w.blob();
  let pageB;
  if (startB === "v2") pageB = await w.startNewEstimate({ tab: tabB, hold: 100 });
  else pageB = await w.pressNewProject({ tab: "test", browserTab: tabB, hold: 100 });
  // as the other tab's press left it (the board's own press is followed by a navigation, a commit and a boot before its page exists)
  const blobWiped = startB === "v2" ? pageB.blobAtStart : w.blob();
  // this page's own estimator edits again after the wipe: nobody has written THIS project, so the edit is written, into the wiped blob
  if (o.aTypesAgain) {
    pageA.type("address", "200 Main St");
    await w.advance(700);
  }
  // the other tab's estimator goes on to TYPE, so the shared blob is no longer empty: it is now ANOTHER project's, and this page's queued save
  // must not write it under this project's id (the page's own copy is lost with it, as it has always been when another tab has the keys)
  if (o.bTypes) {
    pageB.type("project_name", "Tab B Typed");
    await w.advance(700);
  }
  // the estimator leaves this tab inside the queued save's window: closes it, or presses Continue (a flush, not the page going)
  if (kind !== "v1") {
    if (o.leave === "continue") pageA.pressContinue();
    else if (o.leave === "flush") pageA.win.TW.flushState();                // Ctrl+S, Send, the Files page's read: a flush with nothing written first
    else if (o.leave === "stay") { /* this page stays open: its own queued save fires when its timer does */ }
    else pageA.follow("/blank.html");
  }
  await w.settle();
  const row = w.rows.get(id);
  const idB = tabB.page && tabB.page.draftId ? tabB.page.draftId() : null;      // the page the other tab ended on
  const rowB = idB ? w.rows.get(idB) : null;
  return summary(w, id, { kind: kind, startB: startB, blobBeforeKeys: Object.keys(blobBefore || {}).length, blobWipedKeys: Object.keys(blobWiped || {}).length,
    rowData: row ? { project_name: row.data.project_name || null, address: row.data.address || null, keys: Object.keys(row.data).length } : null,
    idB: idB, rowB: rowB ? { project_name: rowB.data.project_name || null, is_test: rowB.data.is_test === undefined ? null : rowB.data.is_test } : null });
}

/** TWO PAGES, ONE PROJECT (found by the same random walks). The sidebar's bare link to a v2 page resumes the browser's CURRENT draft, which
 *  is whatever project was started last, in whichever tab. Tab B starts a project from the Projects page's `tab` and the live intake opens on
 *  it; tab A follows the sidebar link to the v2 intake and lands on that same project, finding no row (nobody has written anything). Then tab
 *  B's estimator writes the project (Continue) and its save creates the row; then tab A's estimator types. The v2 page decided "this is
 *  a project nobody has written" when it opened, and that has stopped being true: it must not make the project a test. */
async function twoPagesOneProject(tab) {
  const w = W.createWorld({ frontend: ROOT });
  const tabA = w.mainTab;
  const tabB = w.openTab();
  const live = await w.pressNewProject({ tab: tab, browserTab: tabB });
  const id = live.draftId();
  const v2 = w.load("/polish-intake.html", { tab: tabA });             // the sidebar's bare link: resumes the browser's current draft
  await w.settle();
  const v2Id = v2.draftId();
  const noteAtOpen = v2.text("sandbox-note");
  live.type("project_name", "Live Intake Bid");
  live.type("address", "5 Elm St");
  await w.advance(300);
  live.pressContinue();                                                // the live intake writes the project: its save creates the row
  await w.advance(1500);
  v2.type("address", "100 Main St");                                   // and now the v2 page's estimator types into it
  await w.advance(4000);
  await w.settle();
  return summary(w, id, { tab: tab, v2Id: v2Id, noteAtOpen: noteAtOpen });
}

/** F5 with a draft that is too big for a keepalive request: a saved TEST project of about 90 KB is edited on the v2 intake and
 *  left by a link inside the 600 ms debounce. The page must not ask the browser for a keepalive request that it will refuse. */
async function bigDraftLeftEarly() {
  const w = W.createWorld({ frontend: ROOT });
  const data = { is_test: true, notes_text: "x".repeat(90 * 1024), project_name: "Overland Park Warehouse", address: "100 Main St",
    city: "Overland Park", state: "KS", zip: "66212", work_type: "polish", audience: "Direct", polish_sf: 6000,
    polish_estimate: { version: 2, conditions: { local: true, prevailing_wage: false, taxable: true, remodel_tax: false } } };
  w.seed(BIG, data);
  w.holdLocally(BIG, data);
  const intake = w.load("/polish-intake.html?d=" + BIG);
  await w.settle();
  intake.type("address", "9 Big Address");
  await w.advance(100);
  intake.follow("/polish-estimate.html?d=" + BIG);
  await w.settle();
  return summary(w, BIG, { address: (w.rows.get(BIG).data || {}).address });
}

// ══ ROUND 4: the audit of round 3 (F1 to F6) ═══════════════════════════════════════════════════════════════
/** F6. shared.js keepaliveFits counts a body's size in UTF-8 BYTES, as the browser does against its 64 KiB keepalive limit. Nothing
 *  pinned that: a body of `count` characters of `fill` is under the limit as `.length` says it and over it in bytes, so a page that
 *  counted characters would ask for a keepalive request the browser refuses on the spot ("TypeError: Failed to fetch": nothing sent).
 *  A saved TEST project holding such a draft is edited on the v2 intake and left within the 600 ms debounce. */
async function bytesNotCharacters(fill, count) {
  const w = W.createWorld({ frontend: ROOT });
  const data = { is_test: true, notes_text: fill.repeat(count), project_name: "Overland Park Warehouse", address: "100 Main St",
    city: "Overland Park", state: "KS", zip: "66212", work_type: "polish", audience: "Direct", polish_sf: 6000,
    polish_estimate: { version: 2, conditions: { local: true, prevailing_wage: false, taxable: true, remodel_tax: false } } };
  w.seed(BIG, data);
  w.holdLocally(BIG, data);
  const intake = w.load("/polish-intake.html?d=" + BIG);
  await w.settle();
  intake.type("address", "9 Big Address");
  await w.advance(100);
  intake.follow("/polish-estimate.html?d=" + BIG);
  await w.settle();
  return summary(w, BIG, { fill: fill, count: count });
}

/** F1. A v2 page decides a project is NEW when it opens (no row, nothing written) and says so on its banner ("saved as a NEW test project").
 *  ANOTHER tab then writes the project: the live intake, which resumes the browser's current draft, with a real bid typed and Continue pressed,
 *  so its save creates the row. The v2 page's estimator then types one character in a v2 box. Its `save()` reads the WHOLE form, which still
 *  holds nothing (it was never told the project had been written), and wrote that over the blob: the real bid's name and address were emptied
 *  on the server and a v2 model put in their place, by a page that still said "NEW test project". `how` is how the project was started
 *  ("board": the v2 board's New estimate in tab A; "projects": the Projects page's New project on `opts.tab` in tab B, then a bare link to the
 *  v2 intake in tab A). `opts.continueStale`: the stale page's Continue is pressed after its edit. (The v2 page cannot have typed first here:
 *  once it has written, the live intake's Continue sends the draft to the v2 intake instead of saving it, js/index.js. See staleQueuedCopy.) */
const rowOf = (w, id) => {
  const r = w.rows.get(id);
  if (!r) return null;
  const d = r.data;
  return { project_name: d.project_name === undefined ? null : d.project_name, address: d.address === undefined ? null : d.address,
           zip: d.zip === undefined ? null : d.zip, has_v2_model: !!d.polish_estimate, is_test: flagOf(d) };
};
async function staleNewPage(how, opts) {
  const o = Object.assign({ tab: "all", continueStale: false, wipeAfterFirstEdit: false }, opts || {});
  const w = W.createWorld({ frontend: ROOT });
  const tabA = w.mainTab;                                       // the v2 page's tab
  const tabB = w.openTab();                                     // the live intake's tab
  let live, v2, id;
  if (how === "board") {
    v2 = await w.startNewEstimate({ tab: tabA });
    id = v2.draftId();
    live = w.load("/?new=1", { tab: tabB });                    // the sidebar's link to the live intake: resumes the browser's current draft
    await w.settle();
  } else {
    live = await w.pressNewProject({ tab: o.tab, browserTab: tabB });
    id = live.draftId();
    v2 = w.load("/polish-intake.html", { tab: tabA });          // a bare link to the v2 intake: resumes the same draft
    await w.settle();
  }
  const noteAtOpen = v2.text("sandbox-note");
  const sameProject = v2.draftId() === id && live.draftId() === id;
  live.type("project_name", "Real Customer Bid");
  live.type("address", "1 Main St");
  await w.advance(300);
  live.pressContinue();                                         // the live intake writes the project: its save creates the row
  await w.advance(3500);
  const rowAfterLive = rowOf(w, id);
  v2.type("zip", "66101");                                      // the v2 page's estimator types one character
  await w.advance(1000);
  if (o.wipeAfterFirstEdit) {
    // a THIRD tab's New project wipes the shared blob: nobody has written the project now, but this page's copy is still older than it
    await w.pressNewProject({ tab: "test", browserTab: w.openTab(), hold: 100 });
  }
  v2.type("city", "Kansas City");                               // and another: a refused page stays refused
  await w.advance(9000);
  const noteAfterTyping = v2.text("sandbox-note");
  if (o.continueStale) {
    v2.pressContinue();
    await w.settle();
  }
  await w.settle();
  return summary(w, id, { how: how, tab: o.tab, noteAtOpen: noteAtOpen, sameProject: sameProject,
    rowAfterLive: rowAfterLive, noteAfterTyping: noteAfterTyping, final: rowOf(w, id),
    staleNavs: w.navs.filter((n) => n.from === v2.label).map((n) => n.to) });
}

/** F1, the queued copy. TWO v2 tabs on one new project. Tab A's page types (its own save has run, so its server save of that copy is queued for
 *  2.5 s later); tab B opens the v2 intake by a bare link, which resumes the same draft: it finds the blob tab A wrote, saves it as a test (so the
 *  row now exists), adopts what is in it, and its estimator adds an address and presses Continue, which saves at once. Tab A's queued save then
 *  fires with ITS older copy, which has no address, over the row tab B just saved. The page that thought it was creating the project was
 *  overwriting a newer row with its own older copy, though it had typed nothing since. */
async function staleQueuedCopy() {
  const w = W.createWorld({ frontend: ROOT });
  const tabA = w.mainTab;
  const tabB = w.openTab();
  const p1 = await w.startNewEstimate({ tab: tabA });
  const id = p1.draftId();
  p1.type("project_name", "First Tab Job");
  await w.advance(700);                                         // tab A's own save has run: its server save is queued
  const p2 = w.load("/polish-intake.html", { tab: tabB });      // a bare link: resumes the same draft, whose row does not exist yet
  await w.advance(500);                                         // its sandbox finds no row, saves the blob it found as a test, and opens
  const p2NoteAtOpen = p2.text("sandbox-note");
  const p2Draft = p2.draftId();
  p2.type("address", "2 Second Tab St");
  await w.advance(100);
  p2.pressContinue();                                           // its save is awaited and goes now
  await w.advance(1000);
  const rowAfterP2 = rowOf(w, id);
  await w.settle();                                             // tab A's queued save fires (or is not sent)
  return summary(w, id, { p2NoteAtOpen: p2NoteAtOpen, p2Draft: p2Draft, rowAfterP2: rowAfterP2, final: rowOf(w, id),
    p1Note: p1.text("sandbox-note"), p1Label: p1.label });
}

/** F4. The v2 intake is left with TWO saves pending: the page's own 600 ms save has run (so shared.js's 2.5 s save of that copy is queued) and
 *  the estimator edits once more (so the page's own 600 ms timer is pending too). Both pagehide handlers have something to send, and they used to
 *  send it BOTH: shared.js's, as the shared blob stood (the older copy), and then the page's, which saves and sends the newest, two keepalive
 *  PUTs of one draft. A server that finishes them out of order keeps the older copy, and the browser counts keepalive bodies against ONE
 *  64 KiB budget, so for a draft of half that size the second (the newest) is refused outright. `opts.slowFirst`: the server takes that many
 *  ms longer over the first save sent as the page goes, so it finishes last. `opts.big`: a saved Test project of about 36 KiB. */
async function twoSavesPending(opts) {
  const o = Object.assign({ big: false, slowFirst: 0 }, opts || {});
  const w = W.createWorld({ frontend: ROOT });
  let intake, id;
  if (o.big) {
    const data = { is_test: true, notes_text: "x".repeat(36 * 1024), project_name: "Overland Park Warehouse", address: "100 Main St",
      city: "Overland Park", state: "KS", zip: "66212", work_type: "polish", audience: "Direct", polish_sf: 6000,
      polish_estimate: { version: 2, conditions: { local: true, prevailing_wage: false, taxable: true, remodel_tax: false } } };
    w.seed(BIG, data);
    w.holdLocally(BIG, data);
    intake = w.load("/polish-intake.html?d=" + BIG);
    await w.settle();
    id = BIG;
  } else {
    intake = await w.startNewEstimate();
    id = intake.draftId();
    intake.type("project_name", "Two Saves");
  }
  intake.type("address", "1 First St");
  await w.advance(900);                                       // the page's 600 ms save has run: shared.js's 2.5 s save of that copy is queued
  intake.type("address", NEWEST_ADDRESS);
  await w.advance(150);                                       // the page's own 600 ms timer is pending
  if (o.slowFirst) w.fault({ route: "PUT", mode: "slow", ms: o.slowFirst, times: 1 });   // the first save sent as the page goes finishes last
  intake.follow("/projects.html");
  const pagehideAt = w.now() + w.net.commitMs;
  await w.settle();
  return summary(w, id, { big: o.big, slowFirst: o.slowFirst, pagehideAt: pagehideAt });
}
const NEWEST_ADDRESS = "2 SECOND St (newest)";

/** F3. The live intake's "Continue with Estimating Tool v2" (the beta door), pressed on a NEW bid started from the Projects page's `tab`. The door
 *  saves the project and opens the v2 intake on it, which asks the server whether the project has a row: a project that is not a test is
 *  COPIED (the real bid left alone), one that is a test is edited directly, and one that has been written into and has no row yet cannot be
 *  told from a project the server never heard of, so the page STOPS. The door used to leave at once, so with a slow server the page asked
 *  before the row was there. `opts.steps` are timed presses and samples of the door (`at` is ms after the first press may be made),
 *  `opts.world` the model's latencies, `opts.faults` its faults (after the project is typed), `opts.blocked` a browser that does not go. */
async function betaDoor(tab, opts) {
  const o = Object.assign({ world: {}, faults: [], blocked: false, steps: [{ at: 0, press: true }], settleMs: undefined }, opts || {});
  const w = W.createWorld(Object.assign({ frontend: ROOT }, o.world));
  const live = await w.pressNewProject({ tab: tab });
  const id = live.draftId();
  const shipped = live.betaDoor().html;
  live.type("project_name", "Real Polish Bid");
  live.type("address", "1 Main St");
  o.faults.forEach((f) => w.fault(f));
  if (o.blocked) w.navigationBlocked = true;
  const t0 = w.now();
  const presses = [];
  const forced = [];
  const samples = {};
  for (const s of o.steps.slice().sort((a, b) => a.at - b.at)) {
    const dt = t0 + s.at - w.now();
    if (dt > 0) await w.advance(dt);
    if (s.press) presses.push({ at: w.now() - t0, accepted: live.pressBetaDoor() !== false, door: live.betaDoor() });
    if (s.force) { live.nodes["beta-continue"].fire("click"); forced.push(w.now() - t0); }   // goes round a disabled button, as a script does
    if (s.sample) samples[s.sample] = Object.assign({ at: w.now() - t0 }, live.betaDoor());
  }
  await w.settle(o.settleMs);
  const v2 = w.pageOf("intake");
  const puts = w.requestsLog().filter((q) => q.route === "PUT" && q.id === id && q.page.startsWith("v1intake"));
  return summary(w, id, { tab: tab, shipped: shipped, t0: t0, presses: presses, forced: forced, samples: samples, doorAtEnd: live.betaDoor(),
    v2: v2 ? Object.assign(w.pageReport(v2), { kind: v2.kind }) : null,
    asked: w.navs.filter((n) => n.from.indexOf("v1intake") === 0).map((n) => ({ at: n.askedAt - t0, to: n.to, blocked: !!n.blocked })),
    livePuts: puts.map((q) => ({ at: q.at - t0, repliedAt: q.repliedAt === null ? null : q.repliedAt - t0, keepalive: q.keepalive, status: q.status })) });
}

/** F2. The v2 board's "+ New estimate" (the REAL startNew of js/v2-board.js) opens the v2 intake on a new project, and the estimator opens
 *  ANOTHER project before anything has been typed. From the GC tab the board leaves { audience: "GC" } in the draft, which the sandbox saves at
 *  once as a test so that its row exists: unless that first save does not land (it is refused, or the page is left before it has heard from
 *  the server), in which case the blob is all that is left, and shared.js decides what to do with it as the other project's page opens.
 *  `opts.faults` are the model's faults, set before the press (the first PUT of the run is the page's own save), `opts.world` its latencies,
 *  `opts.leaveAt` how long after the intake booted the estimator goes. */
const elsewhereRow = () => ({ project_name: "Nearman Creek Epoxy", address: "1 Water Works Dr", city: "Kansas City", state: "KS", zip: "66101",
  bid_date: "2026-09-01", work_type: "epoxy", audience: "Direct", system_1_sf: 8000 });
async function abandonedV2Start(gc, opts) {
  const o = Object.assign({ faults: [], world: {}, leaveAt: 800 }, opts || {});
  const w = W.createWorld(Object.assign({ frontend: ROOT }, o.world));
  w.seed(ELSEWHERE, elsewhereRow());
  o.faults.forEach((f) => w.fault(f));
  const intake = await w.startNewEstimate({ gc: gc, hold: o.leaveAt });
  const id = intake.draftId();
  const startAtArrival = w.startOf(id);
  const noteAtLeaving = intake.text("sandbox-note");
  intake.follow("/?d=" + ELSEWHERE + "&edit=1");
  await w.settle();
  const last = w.pages[w.pages.length - 1];
  return summary(w, id, { gc: gc, startAtArrival: startAtArrival, blobAtStart: intake.blobAtStart, noteAtLeaving: noteAtLeaving,
    other: w.row(ELSEWHERE), lastDraft: last.win.TW.getDraftId(), lastKind: last.kind, startAfter: w.startOf(id) });
}

/** F2, the other half. What a project is STARTED AS follows the project, not the page: a project the v2 board started and that the estimator
 *  then takes to the LIVE intake (the sidebar's link resumes the browser's current draft) is written there by a page that said nothing of it. */
async function v2BoardThenLiveIntake() {
  const w = W.createWorld({ frontend: ROOT });
  const v2 = await w.startNewEstimate({});
  const id = v2.draftId();
  v2.follow("/?new=1");
  await w.settle();
  const live = w.pageOf("v1intake");
  const liveDraft = live.draftId();
  live.type("project_name", "Walk-in Job");
  live.type("address", "5 Elm St");
  await w.advance(1500);
  live.pressContinue();
  await w.settle();
  return summary(w, id, { liveDraft: liveDraft });
}

/** F5. The browser has ONE copy of the draft in localStorage, and it can hold ANOTHER tab's project while this tab's page is on its own id.
 *  Tab A: the v2 board's New estimate, a name and an address typed. Tab B: the Projects page's New project (the All tab), which wipes the shared
 *  blob and makes B's own project the browser's current draft. Tab A types once more: its write lands in the wiped blob, stamped for A.
 *  Tab B then opens a v2 page by its bare link, which resumes B's own project (the current draft) with the shared blob stamped for A. The sandbox
 *  found no row for B and used to save that blob under B's id, as a test: B's project became a Test project holding tab A's project. */
async function foreignBlob(door) {
  const w = W.createWorld({ frontend: ROOT });
  const tabA = w.mainTab;
  const tabB = w.openTab();
  const a = await w.startNewEstimate({ tab: tabA });
  const idA = a.draftId();
  a.type("project_name", "Tab A Estimate");
  a.type("address", "1 A Street");
  await w.advance(800);                                           // A's own 600 ms save has run; its 2.5 s server save is queued
  const b = await w.pressNewProject({ tab: "all", browserTab: tabB, hold: 400 });
  const idB = b.draftId();
  const blobAfterB = w.blob();
  a.type("zip", "66101");                                         // A's write lands in the wiped blob
  await w.advance(1300);
  const blobAfterA = w.blob() || {};
  b.follow(LOOK_DOORS[door]);                                     // B's bare link: resumes the current draft, which is B's
  await w.settle();
  const v2 = w.pageOf(door, tabB);
  const rowB = w.rows.get(idB);
  const rowA = w.rows.get(idA);
  return summary(w, idB, { door: door, idA: idA, idB: idB, blobAfterBKeys: Object.keys(blobAfterB || {}).length,
    blobAfterA: { stamp: blobAfterA.__draft_id || null, name: blobAfterA.project_name || null }, blobEnd: { stamp: (w.blob() || {}).__draft_id || null },
    v2: Object.assign(w.pageReport(v2), { kind: v2.kind }),
    rowBData: rowB ? { project_name: rowB.data.project_name || null, stamp: rowB.data.__draft_id || null, is_test: flagOf(rowB.data) } : null,
    rowAData: rowA ? { project_name: rowA.data.project_name || null, address: rowA.data.address || null, is_test: flagOf(rowA.data) } : null });
}
const flagOf = (data) => (Object.prototype.hasOwnProperty.call(data, "is_test") && data.is_test !== undefined ? data.is_test : null);

/** F5, the other half: a save made for one project never carries a blob stamped for another, whoever asks. The sandbox's own save is the one
 *  that writes the page's blob under an id it names; asked to write another project's blob under this project's id it must refuse. */
async function savingAnotherProjectsBlob() {
  const w = W.createWorld({ frontend: ROOT });
  w.load("/polish-intake.html?d=mine-1");
  await w.settle();                                               // shared.js reads the project (none), adopts it and reloads the page
  const api = w.pageOf("intake").win.TWPolishSandbox;
  const out = { threw: null };
  const asked = api.saveThenFileAsTest("mine-1", { __draft_id: "other-1", project_name: "Not this project's", address: "9 Other St" })
    .then(() => { out.threw = false; }, (e) => { out.threw = String((e && e.message) || e); });
  await w.settle();
  await asked;
  const own = api.saveThenFileAsTest("mine-1", { __draft_id: "mine-1", project_name: "This project's" })
    .then(() => true, () => false);
  await w.settle();
  out.ownStored = await own;
  out.puts = w.requestsLog().filter((r) => r.route === "PUT").map((r) => ({ id: r.id, name: r.sentName }));
  out.rowIds = Array.from(w.rows.keys());
  return out;
}

// VIRTUAL TIME MOVES ONLY WHEN THE MODEL IS ASKED TO RUN IT (world.advance / world.settle). A harness that awaits a request
// before doing so waits for an event nobody will run, node finds nothing left to do and exits 0 with nothing printed, which
// reads as "the harness printed nothing". Say so instead.
let answered = false;
process.on("exit", (code) => {
  if (code === 0 && !answered) {
    console.error("the harness ended without an answer: it is awaiting something on virtual time that nothing advanced "
      + "(call world.settle() or world.advance() before awaiting a request)");
    process.exitCode = 2;
  }
});

(async () => {
  const out = {};
  out.saveWaitMs = saveWaitMs();
  out.model = await modelChecks();
  out.fast = await newEstimate({ waitMs: 100 });
  out.fastAfterAutosave = await newEstimate({ waitMs: 700 });
  out.bareLink = await newEstimate({ waitMs: 100, bare: true });
  out.bareLinkAfterAutosave = await newEstimate({ waitMs: 700, bare: true });
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
  out.stampRules = await stampRules();
  out.synced = await synced();
  out.v1 = await v1();
  out.realThroughIntake = await realThroughIntake();
  out.v1Real = { clean: await v1RealOpen("clean"), anotherStart: await v1RealOpen("anotherStart"), abandonedNew: await v1RealOpen("abandonedNew") };
  out.bigDraft = await bigDraft();
  out.looks = {};
  for (const tab of ["test", "active", "all"]) {
    for (const door of ["intake", "estimate"]) out.looks[tab + "/" + door] = await startThenLook(tab, door);
  }
  out.activeThenTypedInV2 = await activeThenTypedInV2();
  const SLOW = { proc: { PUT: 1500 } };
  out.writtenThenLook = { saved: await writtenThenLook(), notSavedYet: await writtenThenLook({ world: SLOW }),
                          notSavedYetEstimate: await writtenThenLook({ world: SLOW, door: "estimate" }),
                          allSaved: await writtenThenLook({ tab: "all" }), allNotSavedYet: await writtenThenLook({ tab: "all", world: SLOW }),
                          allNotSavedYetEstimate: await writtenThenLook({ tab: "all", world: SLOW, door: "estimate" }),
                          testNotSavedYet: await writtenThenLook({ tab: "test", world: SLOW }) };
  out.gcBoardThenLook = { test: await gcBoardThenLook("test"), active: await gcBoardThenLook("active") };
  out.abandonedBoardStart = {};
  for (const pipeline of ["gc", "direct"]) {
    for (const tab of ["test", "active"]) out.abandonedBoardStart[pipeline + "/" + tab] = await abandonedBoardStart(pipeline, tab);
  }
  // the same, with work in the blob that never went through setState: it is flushed, and the start travels in the PUT itself
  const WORK = { project_name: "Typed Before Leaving" };
  out.abandonedWithWork = {
    "gc/test": await abandonedBoardStart("gc", "test", { work: WORK }),
    "gc/active": await abandonedBoardStart("gc", "active", { work: WORK }),
    "gc/test, its save refused": await abandonedBoardStart("gc", "test", { work: WORK, faults: [{ route: "PUT", mode: "http500" }] }),
    "gc/test, its blob says real": await abandonedBoardStart("gc", "test", { work: WORK, blobSays: false }),
  };
  // F2 of the audit of round 3: the v2 board's own New estimate
  out.abandonedV2Start = {
    "direct": await abandonedV2Start(false),
    "gc": await abandonedV2Start(true),
    "gc, first save refused": await abandonedV2Start(true, { faults: [{ route: "PUT", mode: "network", times: 1 }] }),
    "gc, left before the page heard from the server": await abandonedV2Start(true, { world: { net: { up: 150, down: 150 } }, leaveAt: 100 }),
  };
  out.v2BoardThenLiveIntake = await v2BoardThenLiveIntake();
  out.twoTabs = { v2A: await twoTabs("v2", "A"), v2B: await twoTabs("v2", "B"),
                  projectsA: await twoTabs("projects", "A"), projectsB: await twoTabs("projects", "B") };
  out.bigDraftLeftEarly = await bigDraftLeftEarly();
  out.foreignBlob = { intake: await foreignBlob("intake"), estimate: await foreignBlob("estimate") };
  out.savingAnotherProjectsBlob = await savingAnotherProjectsBlob();
  out.bytesNotCharacters = {
    "2-byte": await bytesNotCharacters("é", 36000),            // é: two bytes, one UTF-16 unit
    "3-byte": await bytesNotCharacters("€", 24000),            // the euro sign: three bytes, one UTF-16 unit
    "4-byte": await bytesNotCharacters("😀", 18000),      // an emoji: four bytes, TWO UTF-16 units (a surrogate pair)
  };
  out.staleNewPage = {
    "board": await staleNewPage("board"),
    "board, Continue pressed on the stale page": await staleNewPage("board", { continueStale: true }),
    "board, the blob wiped by a third tab after the first refusal": await staleNewPage("board", { wipeAfterFirstEdit: true }),
    "projects/all": await staleNewPage("projects", { tab: "all" }),
    "projects/active": await staleNewPage("projects", { tab: "active" }),
    "projects/test": await staleNewPage("projects", { tab: "test" }),
  };
  out.staleQueuedCopy = await staleQueuedCopy();
  out.twoSavesPending = {
    "small": await twoSavesPending(),
    "small, the first save slow": await twoSavesPending({ slowFirst: 400 }),
    "big": await twoSavesPending({ big: true }),
  };
  out.betaDoorMs = betaDoorMs();
  const SLOW_SAVE = { proc: { PUT: 1500 } };
  out.betaDoor = {};
  for (const tab of ["test", "active", "all"]) {
    out.betaDoor[tab + "/fast"] = await betaDoor(tab);
    out.betaDoor[tab + "/slow"] = await betaDoor(tab, { world: SLOW_SAVE });
  }
  out.betaDoorFeedback = {
    // a slow server: the door says what it is doing and a second press does nothing
    saving: await betaDoor("active", { world: SLOW_SAVE, steps: [{ at: 0, press: true }, { at: 50, sample: "early" }, { at: 300, press: true },
                                                                  { at: 400, force: true }, { at: 1000, sample: "late" }] }),
    // a server that never answers: the door leaves when its wait is over
    hung: await betaDoor("active", { faults: [{ route: "PUT", mode: "hang", times: 1 }], steps: [{ at: 0, press: true }, { at: 4000, sample: "midway" }] }),
    // a save that fails at once is not waited out
    failed: await betaDoor("active", { faults: [{ route: "PUT", mode: "network", times: 1 }], steps: [{ at: 0, press: true }] }),
    // the browser does not go: the door is given back, with its own markup, and works again
    blocked: await betaDoor("active", { blocked: true, steps: [{ at: 0, press: true }, { at: 5000, sample: "waiting" }, { at: 12000, sample: "afterGiveBack" },
                                                                { at: 12000, press: true }] }),
  };
  out.twoPagesOneProject = {};
  for (const tab of ["all", "active", "test"]) out.twoPagesOneProject[tab] = await twoPagesOneProject(tab);
  out.wiped = {};
  for (const kind of ["saved", "new", "v1"]) {
    for (const startB of ["v2", "projects"]) out.wiped[kind + "/" + startB] = await wipedByAnotherTab(kind, startB);
  }
  out.wiped["new/v2, Continue pressed after the wipe"] = await wipedByAnotherTab("new", "v2", { leave: "continue" });
  out.wiped["new/v2, flushed after the wipe"] = await wipedByAnotherTab("new", "v2", { leave: "flush" });
  out.wiped["new/v2, the other tab types"] = await wipedByAnotherTab("new", "v2", { bTypes: true });
  out.wiped["saved/v2, the other tab types"] = await wipedByAnotherTab("saved", "v2", { bTypes: true });
  out.wiped["new/v2, the other tab types, this page stays"] = await wipedByAnotherTab("new", "v2", { bTypes: true, leave: "stay" });
  out.wiped["new/v2, this page types again after the wipe"] = await wipedByAnotherTab("new", "v2", { aTypesAgain: true });
  out.realProject = await openProject({});
  out.anotherProjects = await openProject({ starts: { "other-1": "1" } });
  out.saidReal = await openProject({ row: { is_test: false }, starts: { [PROJECT]: "1" } });
  out.filingAsReal = await openProject({ starts: { [PROJECT]: "0" } });
  out.aCopy = await openProject({ row: { beta_sandbox_of: "some-real-project", project_name: "Wichita Warehouse (beta test)" },
    starts: { [PROJECT]: "1" } });
  // A pending start for a project that has been worked on and SENT since (the stale case): it has files, a sent proposal.
  out.staleStart = await openProject({ row: { generate_result: { files: ["a.xlsx"] }, proposal_payload: { sent: true } },
    starts: { [PROJECT]: "1" } });
  console.log(JSON.stringify(out));
  answered = true;
})().catch((e) => { console.error(e && e.stack || e); process.exit(1); });
