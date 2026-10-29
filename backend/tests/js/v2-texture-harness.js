"use strict";
/* AN EPOXY SHEET'S TEXTURE ON THE REAL ESTIMATE PAGE (Hanz, 2026-10-27: "please put a texture setting in this").
 *
 * js/polish-estimate.js runs whole, booted the way polish-estimate-harness.js boots it, with the REAL js/bid-model.js. Every fact is
 * read off what the page drew, held and saved: the Texture select on the Material step of an Epoxy sheet (and of a Combo's Epoxy
 * sheet), none on any other sheet, a change kept on the SECTION and carried through a save and a jsonb reload, and the Proposal
 * step's `texture` filled from the pricing base's Epoxy sheet only while nobody has picked one there.
 *
 * Usage: node v2-texture-harness.js <frontend-dir>   ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");
const Module = require("module");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const B = require(path.join(ROOT, "js", "bid-model.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));
const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

function loadPrelude(file, exportNames) {
  const base = path.join(__dirname, file);
  const code = L.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in v2-texture-harness.js");
  const m = new Module(base, module);
  m.filename = base;
  m.paths = Module._nodeModulePaths(path.dirname(base));
  m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
  return m.exports;
}

const P = loadPrelude("polish-estimate-harness.js", ["build", "blob", "changeTo", "clickEl", "MODEL"]);

const flush = () => new Promise((r) => setImmediate(r));
const panels = (b) => b.doc.getElementById("panels");

const EPOXY = (over) => Object.assign({
  layout: "epoxy", kind: "base", profile: "epoxy@1",
  takeoff: [{ assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: 4000, unit: "SF" }],
  labor: [{ id: "epoxy-install", label: "Epoxy install", guys: 3, days: 4, rate: 33, unit: "days" }],
  contingency: 0, fees: 0, totals: {},
}, over || {});
const SEAL = () => ({ layout: "seal", kind: "option", profile: "seal@1", takeoff: [], labor: [], contingency: 0, fees: 0, totals: {} });

/** An Epoxy job: the Polish root off and an Epoxy base (`epoxy` laid over it), with `extra` on the draft. */
function epoxyJob(epoxy, extra, tabsExtra) {
  const model = Object.assign(clone(P.MODEL), { kind: "off", tabs: Object.assign({ Epoxy: EPOXY(epoxy) }, tabsExtra || {}) });
  return P.blob(Object.assign({ work_type: "epoxy", polish_estimate: model }, extra || {}));
}

/** A Combo job: the Polish root and an Epoxy sheet, both bases. */
function comboJob(epoxy, extra) {
  const model = Object.assign(clone(P.MODEL), { tabs: { Epoxy: EPOXY(epoxy) } });
  return P.blob(Object.assign({ work_type: "combo", polish_estimate: model }, extra || {}));
}

/** A Polish job with an Epoxy sheet as an OPTION. */
function polishWithEpoxyOption(epoxy) {
  const model = Object.assign(clone(P.MODEL), { tabs: { Epoxy: EPOXY(Object.assign({ kind: "option" }, epoxy || {})) } });
  return P.blob({ work_type: "polish", polish_estimate: model });
}

async function open(draft, opts) {
  const b = P.build(Object.assign({ blob: draft }, opts || {}));
  await b.api.init();
  await flush();
  return b;
}

/** What the Texture select on the panel says, or null when the panel has none. */
function select(b) {
  const sel = b.doc.querySelector("[data-texture]");
  if (!sel) return null;
  const opts = [];
  const re = /<option value="([^"]*)"( selected)?>([^<]*)<\/option>/g;
  const htmlOf = panels(b).innerHTML;
  const start = htmlOf.indexOf("data-texture=");
  const body = htmlOf.slice(start, htmlOf.indexOf("</select>", start));
  let m;
  while ((m = re.exec(body))) opts.push({ value: m[1], text: m[3], selected: !!m[2] });
  return { value: sel.value, options: opts, aria: sel.getAttribute("aria-label") };
}

function openTab(b, tab) {
  const btn = b.doc.querySelector('[data-section-tab="' + tab + '"]');
  if (!btn) throw new Error("the Sheets panel has no " + tab);
  P.clickEl(b, btn);
}

/** Pick `value` on the Texture select the way a person does (the value set, then `change`), and save. */
function pick(b, value) {
  const writes = panels(b).htmlWrites;
  P.changeTo(b, "[data-texture]", value);
  const rebuilt = panels(b).htmlWrites !== writes;
  b.clock.fire();
  return rebuilt;
}

const lastSave = (b) => b.rec.saves[b.rec.saves.length - 1];
const proposalTexture = (b) => ({ texture: has(b.store.blob, "texture") ? b.store.blob.texture : "absent",
                                  from: has(b.store.blob, "texture_from_estimate") ? b.store.blob.texture_from_estimate : "absent" });

async function main() {
  const out = {};

  // ── 1. an Epoxy job: the select is on the Material step, with the Proposal step's options, and a pick saves on the section ──
  const b = await open(epoxyJob());
  b.api.go(0);
  out.epoxy = { step: b.api.at(), select: select(b) };
  out.epoxy.rebuiltOnPick = pick(b, "Orange Peel");
  out.epoxy.sectionTexture = b.api.root().tabs.Epoxy.texture;
  out.epoxy.savedSectionTexture = lastSave(b).polish_estimate.tabs.Epoxy.texture;
  out.epoxy.rootTexture = has(lastSave(b).polish_estimate, "texture") ? lastSave(b).polish_estimate.texture : "absent";
  out.epoxy.proposal = proposalTexture(b);
  out.epoxy.selectAfter = select(b);

  // ── 2. it survives a reload of what the server hands back (jsonb re-keys every object) ──
  const r = await open(clone(b.store.blob), { reloaded: true });
  r.api.go(0);
  out.reload = { select: select(r), sectionTexture: r.api.root().tabs.Epoxy.texture, savesOnOpen: r.rec.saves.length,
                 proposal: proposalTexture(r) };
  // the sheet's texture moved again: the Proposal step's follows, because nobody picked one there
  pick(r, "Heavy");
  out.reload.afterRepick = proposalTexture(r);
  // cleared on the sheet: the key is gone from the section, and the Proposal step's empties with it
  pick(r, "");
  out.reload.cleared = { hasKey: has(r.api.root().tabs.Epoxy, "texture"), saved: has(lastSave(r).polish_estimate.tabs.Epoxy, "texture"),
                         proposal: proposalTexture(r) };

  // ── 3. a texture picked on the Proposal step is never overwritten ──
  const typed = await open(epoxyJob({}, { texture: "Medium" }));
  typed.api.go(0);
  pick(typed, "Smooth");
  out.typed = { proposal: proposalTexture(typed), section: typed.api.root().tabs.Epoxy.texture };
  // filled from the sheet once, then changed on the Proposal step: the sheet moving again leaves it alone
  const moved = await open(epoxyJob({ texture: "Smooth" }, { texture: "Light", texture_from_estimate: "Smooth" }));
  moved.api.go(0);
  pick(moved, "Heavy");
  out.movedOnProposal = { proposal: proposalTexture(moved), section: moved.api.root().tabs.Epoxy.texture };
  // emptied on the Proposal step: the sheet's fills it again on the next save
  const emptied = await open(epoxyJob({ texture: "Smooth" }, { texture: "", texture_from_estimate: "Light" }));
  emptied.api.go(0);
  pick(emptied, "Light");
  out.emptiedOnProposal = { proposal: proposalTexture(emptied) };

  // ── 4. an off-list value saved on the sheet is kept as its own option, escaped ──
  const odd = await open(epoxyJob({ texture: 'Satin <b>"glow"</b>' }));
  odd.api.go(0);
  const raw = panels(odd).innerHTML;
  out.offList = { select: select(odd), rawTag: raw.indexOf("<b>") >= 0 };

  // ── 5. a Combo: the Polish sheet has no select, the Epoxy sheet has it, and its texture reaches the Proposal step ──
  const c = await open(comboJob());
  c.api.go(0);
  openTab(c, "Polish");
  out.combo = { polishSelect: select(c) };
  openTab(c, "Epoxy");
  c.api.go(0);
  out.combo.epoxySelect = select(c) !== null;
  pick(c, "Light");
  out.combo.proposal = proposalTexture(c);
  out.combo.section = c.api.root().tabs.Epoxy.texture;
  out.combo.rootHasTexture = has(c.api.root(), "texture");

  // ── 6. a Polish job has no select; an Epoxy OPTION has one, but the base is Polish, so nothing reaches the Proposal step ──
  const pol = await open(P.blob({ work_type: "polish" }));
  pol.api.go(0);
  out.polish = { select: select(pol) };
  const opt = await open(polishWithEpoxyOption());
  opt.api.go(0);
  openTab(opt, "Epoxy");
  opt.api.go(0);
  out.option = { select: select(opt) !== null };
  pick(opt, "Medium");
  out.option.section = opt.api.root().tabs.Epoxy.texture;
  out.option.proposal = proposalTexture(opt);

  // ── 7. a Seal option beside an Epoxy base has no select ──
  const s = await open(epoxyJob({}, {}, { Seal: SEAL() }));
  openTab(s, "Seal");
  s.api.go(0);
  out.seal = { select: select(s), panelIsSeal: panels(s).innerHTML.indexOf("data-seal-patch") >= 0 };

  // ── 8. the model's own rule, alone ──
  const m = clone(epoxyJob({ texture: "Smooth" }).polish_estimate);
  out.model = {
    choices: B.textureChoices("Medium"), offList: B.textureChoices("Velvet"), none: B.textureChoices(""),
    base: B.baseTextureOf(m),
    fillEmpty: B.textureFill(m, {}), fillTyped: B.textureFill(m, { texture: "Heavy" }),
    fillSame: B.textureFill(m, { texture: "Smooth", texture_from_estimate: "Smooth" }),
    fillNothing: B.textureFill(clone(P.MODEL), {}),
    fillCleared: B.textureFill(clone(P.MODEL), { texture: "Smooth", texture_from_estimate: "Smooth" }),
  };
  return out;
}

main().then((o) => console.log(JSON.stringify(o))).catch((e) => { console.error(e && e.stack || e); process.exit(1); });
