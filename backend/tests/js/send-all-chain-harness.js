// SEND ALL BUILDS WHAT WAS NEVER BUILT (Hanz, 2026-10-28), driven through the real pages.
//
// "When I add a new base bid, and add a new proposal in this set of proposals, I'm not able to send
// it." The project's one press now answers `needs_build` for a proposal that never had a document,
// and the page that pressed walks the tab through that proposal's own Proposal-step door
// (`?compose=files`, proposal-review.js composeForFiles -> continueToDone), then back, and presses
// again (send-all-chain.js).
//
// WHAT THIS PROVES, EXECUTED:
//   * PARITY BY CONSTRUCTION. The same never-built proposal, composed (a) by the plain door the
//     Files page uses, (b) by a door on Send all's walk, and (c) by the estimator opening its tab and
//     pressing Continue, saves the SAME draft: the same proposal_payload, the same composeKey stamp,
//     the same top-level fields. Only where the page goes next differs. Several fixtures, one clock
//     and one signed-in viewer, so a difference is a difference in the code path.
//   * THE WALK: member 1's door goes to member 2's door, and the last back to the page that pressed
//     with `sendall_resume`; that page takes it once, for its own project, within ten minutes.
//   * A DOOR THAT STOPS (no template; a copy saved elsewhere) ends the walk: the page says Send all
//     stopped and nothing was sent, and the page that pressed has nothing to resume.
//
// THE WORLD IS files-door-harness.js's, run from its own source (everything above its scenarios):
// the real shared.js per page load, the real rebuildPricing / computeTokenValues / continueToDone /
// composeForFiles over the page's own form markup, the real done.js mode decider and freshDocuments.
// The only seams are that harness's (the mounted template's editor collectors).
//
// Usage: node send-all-chain-harness.js [frontend-dir]  (a dir holding only SOME files: the rest are
// read from the real frontend, which is how test_send_all_chain.py breaks one file and goes red).
"use strict";

const fs = require("fs");
const path = require("path");

const REAL_FRONT = path.resolve(__dirname, "..", "..", "..", "frontend");
const FRONT = process.argv[2] ? path.resolve(process.argv[2]) : REAL_FRONT;
const pick = (p) => (fs.existsSync(path.join(FRONT, p)) ? path.join(FRONT, p) : path.join(REAL_FRONT, p));

// ONE CLOCK, so proposal_date and every other "today" agree between the runs being compared.
const RealDate = Date;
const FIXED = RealDate.UTC(2026, 9, 28, 15, 0, 0);
class FixedDate extends RealDate {
  constructor(...a) { if (a.length) super(...a); else super(FIXED); }
  static now() { return FIXED; }
}
global.Date = FixedDate;

// files-door-harness.js's world, from its own text, reading the same (possibly scratch) frontend.
const DOOR = fs.readFileSync(path.join(__dirname, "files-door-harness.js"), "utf8").replace(/\r\n/g, "\n");
const CUT = DOOR.indexOf("\n(async function () {");
if (CUT < 0) throw new Error("files-door-harness.js's scenarios moved; repoint this harness");
const W = new Function("require", "__dirname", "process",
  DOOR.slice(0, CUT) + "\nreturn { browser, local, openProposal, openDone, draft, tabs, copy };")(
  require, __dirname, { argv: ["node", "files-door-harness.js", process.argv[2]] });

// The walk's module, from the (possibly scratch) frontend, fresh for each page that loads it.
const CHAIN_SRC = fs.readFileSync(pick(path.join("js", "send-all-chain.js")), "utf8");
function chainFor(root) {
  const mod = { exports: {} };
  new Function("module", "window", CHAIN_SRC)(mod, undefined);
  return mod.exports.create(root);
}
const crypto = require("crypto").webcrypto;
/** The walk module as a page of browser `b` would have it, at `loc`. */
function pageChain(b, loc, history, clock) {
  return chainFor({ sessionStorage: b.ss, location: loc, history: history || { replaceState() {} },
                    crypto, Date: clock || FixedDate });
}
const KEY = "treadwell.sendall.chain";
const record = (b) => JSON.parse(b.ss.getItem(KEY) || "null");

/** Canonical JSON: keys sorted at every level, so two saves compare by content. */
function canon(x) {
  if (Array.isArray(x)) return "[" + x.map(canon).join(",") + "]";
  if (x && typeof x === "object") {
    return "{" + Object.keys(x).sort().map((k) => JSON.stringify(k) + ":" + canon(x[k])).join(",") + "}";
  }
  return JSON.stringify(x);
}
function firstDiff(a, b, at) {
  if (canon(a) === canon(b)) return null;
  if (a && b && typeof a === "object" && typeof b === "object") {
    for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) {
      const d = firstDiff(a[k], b[k], (at ? at + "." : "") + k);
      if (d) return d;
    }
  }
  return { at: at || "(root)", a: JSON.stringify(a === undefined ? null : a).slice(0, 200),
           b: JSON.stringify(b === undefined ? null : b).slice(0, 200) };
}

// ── the never-built proposals ────────────────────────────────────────────────────────────────
/** A proposal Create Multiple Proposals made: its estimate and its base sheet's money, no words of
 *  its own, no document and no files (drafts._proposal_copy). */
function child(patch) {
  const d = W.draft();
  delete d.proposal_payload;
  delete d.generate_result;
  delete d.dropbox_result;
  Object.assign(d, { system_name: "", rooms: [], computed_bid: null,
                     scope_group: { id: "G1", label: "Room 2" }, proposal_of: "d0" }, patch || {});
  return d;
}
const FIXTURES = {
  epoxyDirect: () => child(),
  polishGC: () => child({ audience: "GC", base_tab_id: "Polish", work_type: "polish",
                          tax_inclusion: "BROKEN_OUT" }),
  remodelTaxed: () => {
    const t = W.tabs(14000, 450);
    t[0].remodel = 900;
    return child({ priced_tabs: t, proposal_lump_sum: 14000, proposal_sales_tax: 450,
                   proposal_remodel_tax: 900, tax_inclusion: "BROKEN_OUT" });
  },
  phasePrice: () => child({ phase_price: 3000, notes_text: "" }),
};

const ORIGIN = "/done.html?d=d0&files=1";
/** The page that pressed: starts the walk over `build`, as done.js does on `needs_build`. */
function startWalk(b, build, returnUrl) {
  const nav = [];
  const started = pageChain(b, { pathname: "/done.html", search: "?d=d0&files=1",
                                 assign: (u) => nav.push(String(u)) })
    .start({ group: "G1", build, returnUrl: returnUrl || ORIGIN,
             stash: { message: "All three.", emails: ["buyer@acme.test"], attachments: 0 } });
  return { started, door: nav[0] || null, nav };
}

/** One door: the Proposal step at `href`, with the walk module loaded as the page loads it. */
async function door(b, href, opts) {
  const p = await W.openProposal(b, href, opts);
  p.page.window.TWSendAll = pageChain(b, p.page.loc, p.page.history);
  // Every text the button shows while the door works (the one line this page shows).
  const btn = p.nodes["generate-btn"];
  const said = [];
  let text = btn.textContent;
  Object.defineProperty(btn, "textContent", { get: () => text,
                                              set: (v) => { text = v; said.push(v); } });
  await p.scope.composeForFiles();
  return { nav: p.page.nav.slice(), note: p.nodes["resync-note-head"].textContent,
           button: text, said };
}

(async function () {
  const out = { parity: {}, walk: {}, stops: {}, take: {} };

  // ── PARITY ────────────────────────────────────────────────────────────────────────────────
  for (const [name, make] of Object.entries(FIXTURES)) {
    // (a) the Files page's own door
    const ba = W.browser(make());
    const a = await door(ba, "/proposal-review.html?compose=files&d=d1");
    // (b) the same door, on Send all's walk
    const bb = W.browser(make());
    const w = startWalk(bb, [{ id: "d1", label: "Room 2" }]);
    const bdoor = await door(bb, w.door.replace(/^https?:\/\/[^/]+/, ""));
    // (c) the estimator: opens the proposal's tab, presses Continue, then the Files page builds it
    const bc = W.browser(make());
    const manual = await W.openProposal(bc, "/proposal-review.html?d=d1");
    await manual.scope.continueToDone(null);
    const files = await W.openDone(bc, "/done.html?composed=1&d=d1");
    await files.scope.freshDocuments();
    const rendered = bc.server.rendered[bc.server.rendered.length - 1] || null;

    const A = ba.server.d1, B = bb.server.d1, C = bc.server.d1;
    // WHO BUILT IT is the one field allowed to differ (`proposal_auto_built`, Hanz 2026-10-28: the
    // press holds a walk-built document that still prints Kyle's placeholders). Compared apart.
    const MARK = "proposal_auto_built";
    const unmarked = (d) => { const x = Object.assign({}, d); delete x[MARK]; return x; };
    out.parity[name] = {
      composed: { a: !!(A.proposal_payload && A.proposal_payload.values),
                  b: !!(B.proposal_payload && B.proposal_payload.values),
                  c: !!(C.proposal_payload && C.proposal_payload.values) },
      keyed: !!B.proposal_payload_key && B.proposal_payload_key === A.proposal_payload_key,
      marks: { a: A[MARK] === undefined ? null : A[MARK], b: B[MARK] === undefined ? null : B[MARK],
               c: C[MARK] === undefined ? null : C[MARK] },
      doorVsWalk: firstDiff(unmarked(A), unmarked(B)),
      walkVsManual: firstDiff(unmarked(B), unmarked(C)),
      payloadWalkVsGenerated: firstDiff(B.proposal_payload, rendered),
      total: B.proposal_payload && B.proposal_payload.values && B.proposal_payload.values.total_formatted,
      navA: a.nav, navB: bdoor.nav, walkButton: bdoor.button,
      recordAfter: record(bb),
      token: w.door && /sendall=([0-9a-f]+)/.exec(w.door)[1],
    };
  }

  // ── THE MARK'S LIFE: the walk sets it, the Files page's door keeps it, a person's Continue clears it
  {
    const MARK = "proposal_auto_built";
    const b = W.browser(child({ audience: "GC" }));
    const w = startWalk(b, [{ id: "d1", label: "Room 2" }]);
    await door(b, w.door);
    const afterWalk = b.server.d1[MARK];
    await door(b, "/proposal-review.html?compose=files&d=d1");
    const afterDoor = b.server.d1[MARK];
    const p = await W.openProposal(b, "/proposal-review.html?d=d1");
    await p.scope.continueToDone(null);
    out.mark = { afterWalk: afterWalk === undefined ? null : afterWalk, afterDoor, afterPerson: b.server.d1[MARK] === undefined ? null
                                                     : b.server.d1[MARK] };
  }

  // ── WHO SIGNS: a proposal of Create Multiple Proposals is signed as Base Bid 1 is ──────────────
  // drafts._parent_signer copies Base Bid 1's `estimator_name` and `estimator_signer` onto the child.
  // Troy presses Send all; the walk builds Kyle's project's new proposal on Troy's machine.
  {
    const TROY = { name: "Troy Holmes", email: "troy@wetreadwell.com" };
    const KYLE_SIGNS = { estimator_name: "Kyle Loseke",
                         estimator_signer: { name: "Kyle Loseke", email: "kyle@wetreadwell.com" } };
    const signed = async (patch) => {
      const b = W.browser(child(patch));
      b.user = TROY;
      const w = startWalk(b, [{ id: "d1", label: "Room 2" }]);
      await door(b, w.door);
      const v = ((b.server.d1.proposal_payload || {}).values) || {};
      return { name: v.estimator_name, email: v.estimator_email };
    };
    out.signer = {
      seeded: await signed(KYLE_SIGNS),
      unseeded: await signed({ estimator_name: "" }),
      typedOver: await signed(Object.assign({}, KYLE_SIGNS, { estimator_name: "Will Smith" })),
    };
  }

  // ── THE WALK: two proposals, then back ──────────────────────────────────────────────────────
  {
    const b = W.browser(child());
    const w = startWalk(b, [{ id: "d1", label: "Room 2" }, { id: "d2", label: "Room 3" }]);
    const tok = /sendall=([0-9a-f]+)/.exec(w.door)[1];
    const first = await door(b, w.door);
    // Member 2's door, reached: its Continue asks the walk where to go next.
    const at2 = new URLSearchParams((first.nav[0] && first.nav[0][1] || "").split("?")[1] || "");
    const second = pageChain(b, { pathname: "/proposal-review.html", search: "?" + at2.toString() });
    const progress2 = second.progress(at2);
    const last = second.nextHop(at2);
    // A Continue on member 2 pressed AGAIN with the same URL (Back, then Continue) goes nowhere new.
    const replay = pageChain(b, {}).nextHop(at2);
    out.walk = { started: w.started, firstDoor: w.door, tok, firstNav: first.nav,
                 firstSaid: first.said, progress2, last, replay, recordDone: (record(b) || {}).done };
    // The page that pressed, back: takes it once, for its own project.
    const hist = [];
    const back = pageChain(b, { pathname: "/done.html", search: "?d=d0&files=1&sendall_resume=" + tok },
                           { replaceState: (s, t, u) => hist.push(u) });
    const params = new URLSearchParams("?d=d0&files=1&sendall_resume=" + tok);
    out.take.own = back.take(params, "G1");
    out.take.addressBar = hist;
    out.take.again = back.take(params, "G1");
    // A page that took a walk never starts another (the same press answering needs_build again).
    out.take.restartRefused = back.start({ group: "G1", build: [{ id: "d1", label: "Room 2" }],
                                           returnUrl: ORIGIN }) === false;
    out.take.recordAfterRefusal = record(b);
  }
  // Another project's page, an expired walk, an unfinished one: nothing to take, record gone.
  {
    const finished = async (clock) => {
      const b = W.browser(child());
      const w = startWalk(b, [{ id: "d1", label: "Room 2" }]);
      await door(b, w.door);
      const tok = /sendall=([0-9a-f]+)/.exec(w.door)[1];
      return { b, tok, page: pageChain(b, { pathname: "/done.html", search: "" }, null, clock) };
    };
    const f1 = await finished();
    out.take.otherGroup = f1.page.take(new URLSearchParams("?sendall_resume=" + f1.tok), "G2");
    out.take.otherGroupRecord = record(f1.b);
    const late = { now: () => FIXED + 11 * 60 * 1000 };
    const f2 = await finished(late);
    out.take.expired = f2.page.take(new URLSearchParams("?sendall_resume=" + f2.tok), "G1");
    out.take.forged = (await finished()).page.take(new URLSearchParams("?sendall_resume=feedface"), "G1");
    const b = W.browser(child());
    const w = startWalk(b, [{ id: "d1", label: "Room 2" }, { id: "d2", label: "Room 3" }]);
    const tok = /sendall=([0-9a-f]+)/.exec(w.door)[1];
    out.take.unfinished = pageChain(b, {}).take(new URLSearchParams("?sendall_resume=" + tok), "G1");
    // An id that is not an id never starts anything.
    out.take.badId = startWalk(W.browser(child()), [{ id: "../x", label: "x" }]).started;
  }

  // ── A DOOR THAT STOPS ENDS THE WALK ─────────────────────────────────────────────────────────
  {
    // The template did not load: the door hands the page over and says why.
    const b = W.browser(child());
    const w = startWalk(b, [{ id: "d1", label: "Room 2" }, { id: "d2", label: "Room 3" }]);
    const tok = /sendall=([0-9a-f]+)/.exec(w.door)[1];
    const d = await door(b, w.door, { tpl: "" });
    out.stops.noTemplate = { nav: d.nav, note: d.note, record: record(b),
                             resume: pageChain(b, {}).take(new URLSearchParams("?sendall_resume=" + tok), "G1"),
                             composed: !!(b.server.d1.proposal_payload) };
  }
  {
    // The server holds a copy this browser did not load (saved from elsewhere): back to Files.
    const mine = child();
    const theirs = child({ texture: "Knockdown (saved by RJ)" });
    const b = W.browser(theirs, mine);
    const w = startWalk(b, [{ id: "d1", label: "Room 2" }]);
    const tok = /sendall=([0-9a-f]+)/.exec(w.door)[1];
    const d = await door(b, w.door);
    out.stops.notTheSavedCopy = { nav: d.nav, record: record(b),
                                  resume: pageChain(b, {}).take(new URLSearchParams("?sendall_resume=" + tok), "G1") };
  }

  process.stdout.write(JSON.stringify(out));
})().catch((e) => { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
