// Lifts grantsPanelHtml out of frontend/js/admin.js and renders it, so the Admin page's Special
// permissions card is checked by executing the real renderer rather than by reading its source.
// Usage: node special-permissions-harness.js <frontend dir>   -> prints JSON on stdout.
"use strict";
const fs = require("fs");
const path = require("path");

const src = fs.readFileSync(path.join(process.argv[2], "js", "admin.js"), "utf8");
const start = src.indexOf("    function grantsPanelHtml(");
const end = src.indexOf("    function renderGrants(");
if (start < 0 || end < 0 || end < start) throw new Error("grantsPanelHtml not found in admin.js");
const grantsPanelHtml = new Function(src.slice(start, end) + "\nreturn grantsPanelHtml;")();

const store = {
  grants_catalog: [
    { key: "items_pricing", label: "Items: price breaks", description: "Edit price breaks." },
    { key: "markup", label: "Markup rules", description: "Edit markup rules." },
  ],
  grants: { "marisol@wetreadwell.com": ["items_pricing"] },
  updated_at: "2026-10-27T15:00:00Z", updated_by: "hanz@wetreadwell.com",
};
const users = [
  { email: "Marisol@WeTreadwell.com", full_name: "Marisol", role: "user" },
  { email: "kyle@wetreadwell.com", full_name: "Kyle", role: "user" },
  { email: "boss@wetreadwell.com", full_name: "Boss", role: "admin" },
  { email: "hanz@wetreadwell.com", full_name: "Hanz", role: "super_admin" },
];

const html = grantsPanelHtml(users, store, "Saved.");
const boxes = [...html.matchAll(/<input type="checkbox"([^>]*)>/g)].map((m) => {
  const a = m[1];
  const attr = (k) => { const r = new RegExp(" " + k + '="([^"]*)"').exec(a); return r ? r[1] : null; };
  return { email: attr("data-email"), key: attr("data-key"),
           checked: / checked(\s|$)/.test(a), disabled: / disabled(\s|$)/.test(a) };
});
const rows = [...html.matchAll(/<tr data-email="([^"]*)"/g)].map((m) => m[1]);
const heads = [...html.matchAll(/<th class="rv-h" title="([^"]*)">([^<]*)<\/th>/g)]
  .map((m) => ({ title: m[1], label: m[2] }));
const failed = grantsPanelHtml(users, null, "");

// A tick while a save is in flight: renderGrants + toggleGrant run against a stub page whose PUT
// never answers, so what the boxes look like DURING the save is what a second click would meet.
const wStart = src.indexOf("    function renderGrants(");
const wEnd = src.indexOf("    async function refresh(");
if (wStart < 0 || wEnd < wStart) throw new Error("renderGrants/toggleGrant not found in admin.js");
const liveBoxes = [{ disabled: false, addEventListener() {}, dataset: {} },
                   { disabled: false, addEventListener() {}, dataset: {} }];
const page = { getElementById: () => ({ set outerHTML(v) {} }), querySelectorAll: () => liveBoxes };
const puts = [];
const wiring = new Function("document", "grantsPanelHtml", "USERS", "GRANTS", "apiFull", "errText",
  src.slice(wStart, wEnd) + "\nreturn { toggleGrant };")(
  page, grantsPanelHtml, users, store, (url, opts) => { puts.push(opts); return new Promise(() => {}); }, () => "");
wiring.toggleGrant("kyle@wetreadwell.com", "markup", true);
const inFlight = { puts: puts.length, allDisabled: liveBoxes.every((b) => b.disabled) };

process.stdout.write(JSON.stringify({
  rows, heads, boxes, inFlight,
  status: /id="sp-status"[^>]*>Saved\.</.test(html),
  adminNote: (html.match(/Admins have all of these<\/span>/g) || []).length,
  failedSaysSo: /didn't load/.test(failed) && !/type="checkbox"/.test(failed),
}));
