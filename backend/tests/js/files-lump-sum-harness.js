// Lifts the Files page's price logic out of frontend/js/done.js and drives it.
//
// EXECUTED, NOT READ. The bodies below are taken verbatim out of the shipped file and run in a
// bare scope with every collaborator bound explicitly, so an identifier this page expects to find
// on `window` and does not is a thrown error here rather than a green suite and a blank card. A
// source-text assertion cannot tell the difference; this file exists because that lesson was
// learned on prod.
//
// WHAT IS PINNED, and why each one:
//
//   * THE STAMP IS THE DOCUMENT'S OWN FIGURE. `builtAt` reads `values.total_formatted` off the
//     payload being sent, not the draft's `proposal_lump_sum`. Reading the draft would stamp what
//     the sidebar believed at that moment — the thing being checked, not the thing to check it
//     against — and the comparison would be true by construction forever.
//   * A MOVED PRICE HIDES THE DOWNLOADS. `generate_result` is persisted and never cleared, so a
//     project generated once lands straight on the old files. That was survivable while the card
//     named no figure. Naming one makes it a claim, and the claim would be wrong.
//   * AN UNSTAMPED DRAFT KEEPS ITS FILES. Every project generated before this shipped has no
//     stamp. Unknown is not changed, and treating it as changed would make every one of them
//     demand a regenerate on the day it lands.
//   * NO FIGURE MEANS NO ROW, via `hidden` and not a style write.
"use strict";

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..", "..");
const SRC = fs.readFileSync(path.join(ROOT, "frontend", "js", "done.js"), "utf8");

function balanced(startIndex, open, close) {
  let depth = 1;
  for (let j = startIndex; j < SRC.length; j++) {
    if (SRC[j] === open) depth++;
    else if (SRC[j] === close) {
      depth--;
      if (depth === 0) return SRC.slice(startIndex, j);
    }
  }
  return "";
}

function gone(what, why) {
  throw new Error(what + " could not be lifted out of done.js. " + why
    + " Repoint this harness; do not delete the scenarios.");
}

/** The body of a declared `function NAME(args) { ... }`. */
function liftDecl(name, why) {
  const m = new RegExp("function " + name + "\\s*\\(([^)]*)\\)\\s*\\{").exec(SRC);
  if (!m) gone(name, why);
  return { args: m[1].split(",").map((s) => s.trim()).filter(Boolean),
           body: balanced(m.index + m[0].length, "{", "}") };
}

const MONEY = liftDecl("money",
  "It is the one parser both the staleness check and the card read money through.");
const BUILT_AT = liftDecl("builtAt",
  "It is what records the figure the customer's document was filled with.");
const MOVED = liftDecl("priceMovedSinceGenerate",
  "It is the only thing standing between a moved price and a card that names the wrong one.");
const PAINT = liftDecl("paintLumpSum",
  "It is the row that shows an estimator the price before they send it.");

// The mode decider is an anonymous async IIFE, so it is anchored on its own heading comment
// rather than a name. Losing the anchor must be loud: the decider is what keeps a priced-out
// project away from its stale downloads.
const DECIDER = (function () {
  const anchor = SRC.indexOf("─── Decide which mode to show");
  if (anchor < 0) gone("the mode decider", "Its heading comment is gone.");
  const m = /\(async \(\) => \{/.exec(SRC.slice(anchor));
  if (!m) gone("the mode decider", "It is no longer an async arrow IIFE after its heading.");
  return balanced(anchor + m.index + m[0].length, "{", "}");
})();

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const build = (lifted, extra) => new Function(
  ...lifted.args, ...(extra || []),
  '"use strict"; ' + lifted.body);

const money = build(MONEY);
const builtAt = build(BUILT_AT);
// `money` is bound in, exactly as the module scope provides it — so a rename that breaks the
// reference is an error here and not a silently-never-stale check.
const priceMoved = new Function("st", "money",
  '"use strict"; ' + MOVED.body);
const paint = new Function("TW", "document", "money",
  '"use strict"; ' + PAINT.body);

// `composedHere` and `location` belong to the page's DOOR, which runs first: a draft whose document
// is not current is sent through the Proposal step before any of the choices below are made. That
// branch is driven end to end in files-door-harness.js; here every scenario has just come back
// through it (`composedHere` true), so what is under test is the choice AFTER the door. `location`
// is bound to a stub that records a navigation, so a scenario that reached the door would show it.
const runDecider = new AsyncFunction(
  "TW", "filesMode", "composedHere", "location", "viewFiles", "showPostGenerate",
  "showPreGenerate", "emptyEl", "priceMovedSinceGenerate",
  '"use strict";\n' + DECIDER);

// ── the smallest DOM this touches ───────────────────────────────────────────
function el(id) {
  return { id: id, hidden: "<untouched>", textContent: "<untouched>",
           style: { display: "<untouched>" } };
}
function doc(ids) {
  const nodes = {};
  (ids || ["lump-row", "lump-sum"]).forEach((i) => { nodes[i] = el(i); });
  return { nodes: nodes, getElementById: (i) => nodes[i] || null };
}
const store = (s) => ({ getState: () => s });

const out = {};

// ── A. money parses what both callers hand it ───────────────────────────────
out.money = {
  plain: money("$36,700.00"),
  commas: money("$1,234,567.89"),
  bare: money("36700"),
  negative: money("-$500.00"),
  empty: money(""),
  nul: money(null),
  undef: money(undefined),
  dash: money("—"),
  junk: money("not a price"),
};

// ── B. the stamp is the DOCUMENT's figure ───────────────────────────────────
out.builtAt = {
  // The real shape: /api/generate is handed {work_type, audience, values: {...}, ...}.
  fromValues: builtAt({ work_type: "epoxy", values: { total_formatted: "$36,700.00",
                                                      base_bid_formatted: "$34,000.00" } }),
  // The draft's own number is NOT what gets stamped, even when it is sitting right there.
  ignoresDraftNumber: builtAt({ values: { proposal_lump_sum: 99999 } }),
  noValues: builtAt({ work_type: "epoxy" }),
  nothing: builtAt(null),
  notAString: builtAt({ values: { total_formatted: 36700 } }),
};

// ── C. has the price moved since these files were built ─────────────────────
const moved = (built, now) =>
  priceMoved({ generated_lump_sum: built, lump_sum_display: now }, money);
out.moved = {
  same: moved("$36,700.00", "$36,700.00"),
  // The two are formatted by DIFFERENT functions off the same number — fmtUSDdoc for the payload,
  // #tb-total's own text for the display. A string compare would call this drift on every single
  // project and send everybody back to Generate forever.
  sameNumberOtherFormat: moved("$36,700.00", "$36,700"),
  changed: moved("$36,700.00", "$41,250.00"),
  changedDown: moved("$41,250.00", "$36,700.00"),
  // Rounding noise is not an edit.
  aHalfCent: moved("$36,700.00", "$36,700.005"),
  aWholeCent: moved("$36,700.00", "$36,700.01"),
  // A draft generated before the stamp existed. Unknown is not changed.
  noStamp: moved(null, "$36,700.00"),
  noDisplay: moved("$36,700.00", null),
  neither: moved(null, null),
};

// ── D. the mode decider sends a priced-out project back to Generate ─────────
async function decide(st, opts) {
  const calls = [];
  const emptyEl = { style: { display: "<untouched>" } };
  await runDecider(
    Object.assign({ draftReady: Promise.resolve() }, store(st)),
    !!(opts || {}).filesMode,
    true,
    { replace: (u) => calls.push("door " + u), assign: (u) => calls.push("door " + u) },
    () => calls.push("viewFiles"),
    () => calls.push("showPostGenerate"),
    () => calls.push("showPreGenerate"),
    emptyEl,
    (s) => priceMoved(s, money));
  return { calls: calls, emptyShown: emptyEl.style.display };
}

const RES = { work_type: "epoxy", docx_download_url: "/api/file/abc" };
const PAYLOAD = { values: { total_formatted: "$36,700.00" } };

(async function () {
out.decider = {
  agrees: await decide({ generate_result: RES, proposal_payload: PAYLOAD,
                         project_name: "Niagara", generated_lump_sum: "$36,700.00",
                         lump_sum_display: "$36,700.00" }),
  // THE CASE THIS EXISTS FOR: the estimator changed the price and came back. The files on this
  // page are the old ones, so the page must not offer them under the new number.
  priceMoved: await decide({ generate_result: RES, proposal_payload: PAYLOAD,
                             project_name: "Niagara", generated_lump_sum: "$36,700.00",
                             lump_sum_display: "$41,250.00" }),
  // Generated before the stamp existed: nothing to compare, so nothing changes for them.
  unstamped: await decide({ generate_result: RES, proposal_payload: PAYLOAD,
                            project_name: "Niagara", lump_sum_display: "$41,250.00" }),
  // A moved price with nothing to regenerate FROM still has to land somewhere useful, and the
  // stale files beat the empty state.
  movedButNoPayload: await decide({ generate_result: RES, project_name: "Niagara",
                                    generated_lump_sum: "$36,700.00",
                                    lump_sum_display: "$41,250.00" }),
  // files-mode regenerates regardless — it is the one route that always rebuilds.
  filesMode: await decide({ generate_result: RES, proposal_payload: PAYLOAD,
                            project_name: "Niagara", generated_lump_sum: "$36,700.00",
                            lump_sum_display: "$41,250.00" }, { filesMode: true }),
  notGeneratedYet: await decide({ proposal_payload: PAYLOAD, project_name: "Niagara" }),
  nothingInFlight: await decide({}),
};

// ── E. the row itself ───────────────────────────────────────────────────────
function painted(st, ids) {
  const d = doc(ids);
  paint(store(st), d, money);
  return { row: d.nodes["lump-row"], val: d.nodes["lump-sum"] };
}

const stamped = painted({ generated_lump_sum: "$36,700.00", lump_sum_display: "$41,250.00" });
out.row = {
  // THE STAMP WINS. Both are present here and they disagree on purpose: the figure shown has to
  // be the one inside the files, never the draft's newer idea of it.
  showsTheStamp: { text: stamped.val.textContent, hidden: stamped.row.hidden },
  fallsBackToDisplay: (function () {
    const p = painted({ lump_sum_display: "$36,700.00" });
    return { text: p.val.textContent, hidden: p.row.hidden };
  })(),
  noFigure: (function () {
    const p = painted({});
    return { text: p.val.textContent, hidden: p.row.hidden };
  })(),
  zeroIsAFigure: (function () {
    const p = painted({ generated_lump_sum: "$0.00" });
    return { text: p.val.textContent, hidden: p.row.hidden };
  })(),
  dashIsNot: (function () {
    const p = painted({ generated_lump_sum: "—" });
    return { hidden: p.row.hidden };
  })(),
  // Never a style write — .fp-money's own [hidden] rule is what makes the attribute work, and a
  // display write here would be a second opinion that beats it.
  touchedNoStyle: stamped.row.style.display,
  // A page whose row is missing entirely must not throw on the way past.
  survivesAMissingRow: (function () {
    try { painted({ generated_lump_sum: "$1.00" }, []); return true; }
    catch (e) { return String(e); }
  })(),
};

process.stdout.write(JSON.stringify(out));
})().catch((e) => { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
