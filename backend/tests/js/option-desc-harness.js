"use strict";
/* An option's own description, as BOTH pages put it on the room, EXECUTED.
 *
 * Hanz: options "would want to have it where you could put a long description instead of just the
 * title of the worksheet". The estimator types it in the Proposal step's Pricing options sidebar
 * (state.tab_opts[<tab>].desc); the room that carries it to the document, the customer portal and the
 * editor's preview is built TWICE -- proposal-review.js's rebuildPricing.mkRoom and estimate-review.js's
 * snapshotLumpSumsToState.mkRoom -- and the two must mirror each other, or the words depend on which
 * page saved last. Source text cannot show that a branch is taken, so this lifts each `mkRoom` out of
 * its file verbatim, binds it to stand-ins for what it closes over (by name: a name it reaches for
 * that is not stood in for fails loudly with a ReferenceError, rather than quietly reading undefined)
 * and runs it over the same tabs.
 *
 * Usage: node option-desc-harness.js <frontend-dir> < scenarios.json   ->   one line of JSON
 *   scenarios: [{ name, tab: {id,name,total,sales_tax,remodel,system_desc,notes_auto,taxable,
 *                 remodel_on}, opt: {...tab_opts entry...}, is_base?, base_total?, notes_manual? }]
 *   result:    [{ name, proposal: <room>, estimate: <room> }]
 */
const fs = require("fs");
const path = require("path");

const read = (f) => fs.readFileSync(path.join(process.argv[2], "js", f), "utf8").replace(/\r\n/g, "\n");
const PROPOSAL = read("proposal-review.js");
const ESTIMATE = read("estimate-review.js");

/** The `const mkRoom = (t, isBase) => {…};` of `src`, by brace depth (no brace of its own sits in a
 *  string or a comment, and a miscount would make the lifted text a syntax error, loudly). */
function liftMkRoom(src, where) {
  const head = "const mkRoom = (t, isBase) => {";
  const at = src.indexOf(head);
  if (at < 0) throw new Error("mkRoom is gone from " + where + " — rewrite this harness, don't delete it");
  if (src.indexOf(head, at + 1) >= 0) throw new Error("two mkRooms in " + where);
  let depth = 0;
  for (let j = at + head.length - 1; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return src.slice(at, j + 1);
  }
  throw new Error("unbalanced braces reading mkRoom in " + where);
}
const PROPOSAL_MKROOM = liftMkRoom(PROPOSAL, "proposal-review.js");
const ESTIMATE_MKROOM = liftMkRoom(ESTIMATE, "estimate-review.js");

const N = (v) => Number(v) || 0;

function proposalRoom(sc) {
  const t = sc.tab;
  const state = { tab_notes: { [t.id]: sc.notes_manual || [] } };
  const opts = { [t.id]: sc.opt || undefined };
  const tFlag = (tab, k) => (tab && typeof tab[k] === "boolean") ? tab[k] : undefined;
  const mk = new Function("opts", "N", "shownBase", "tFlag", "baseTaxable", "baseRemodelOn", "baseDesc", "state",
    PROPOSAL_MKROOM + "\nreturn mkRoom;")(opts, N, N(sc.base_total), tFlag, true, false, "BASE DESC", state);
  return mk(t, !!sc.is_base);
}

function estimateRoom(sc) {
  const t = sc.tab;
  const state = { tab_opts: { [t.id]: sc.opt || undefined }, tab_notes: { [t.id]: sc.notes_manual || [] },
                  proposal_taxable: true, proposal_remodel_on: false };
  // The sheet engine's stand-ins: the same figures the Proposal step's priced_tabs snapshot.
  const totalCellsFor = () => ({ total: "T", sales_tax: "S", remodel: "R" });
  const num = (_id, cell) => ({ T: t.total, S: t.sales_tax, R: t.remodel })[cell];
  const taxFlagsFor = () => ({ taxable: t.taxable, remodel_on: t.remodel_on });
  const mk = new Function("totalCellsFor", "num", "state", "shownBase", "deriveSystemNameFor", "labelFor",
    "taxFlagsFor", "baseDesc", "deriveNotes",
    ESTIMATE_MKROOM + "\nreturn mkRoom;")(
    totalCellsFor, num, state, N(sc.base_total), () => t.system_desc, () => t.name, taxFlagsFor,
    "BASE DESC", () => t.notes_auto || []);
  return mk(t, !!sc.is_base);
}

const scenarios = JSON.parse(fs.readFileSync(0, "utf8"));
const out = scenarios.map((sc) => ({ name: sc.name, proposal: proposalRoom(sc), estimate: estimateRoom(sc) }));
console.log(JSON.stringify(out));
