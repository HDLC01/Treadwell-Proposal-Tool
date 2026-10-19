"use strict";
/* THE 2026-10-20 BROWSER WALK'S FINDINGS ON THE v2 SHEET TABS, held by the real panel builder (js/bid-model.js).
 *
 *   node tabs-walk-fixes-harness.js <frontend dir>
 */
const path = require("path");
const B = require(path.join(path.resolve(process.argv[2]), "js", "bid-model.js"));

// a combo job with Epoxy alone as the base, so Polish is an option beside it
const m = B.pickBase(B.sectionsForJob(B.freshModel(), "combo", {}), ["Epoxy"], { state: {} }).model;
const tabs = B.sectionsOf(m).map((e) => e.tab);
const base = B.baseOf(m).ids;
const other = tabs.filter((t) => base.indexOf(t) < 0)[0] || tabs[0];
const shut = B.sheetsPanelHtml(m, { open: other, bids: {} });
const open = B.sheetsPanelHtml(m, { open: other, bids: {}, pick: true });
const tabOf = (h, t) => { const i = h.indexOf('data-sh-row="' + t + '"'); return i < 0 ? "" : h.slice(h.lastIndexOf("<li", i), h.indexOf("</li>", i)); };
const addBtn = (h) => (/<button[^>]*class="sh-addbtn[^"]*"[^>]*>/.exec(h) || [""])[0];
console.log(JSON.stringify({
  tabs: tabs, base: base, other: other,
  addShut: addBtn(shut), addOpen: addBtn(open),
  baseTab: tabOf(shut, base[0]), otherTab: tabOf(shut, other),
}));
