// Appended to polish-intake-harness.js's prelude by condition-cells-intake-harness.js: `build`, `blob`,
// `readSwitches`, `clickSwitch`, `W`, `P`, `ROOT`, `read` and the rest are in scope.
//
// A TEST COPY OF A SPLIT PROJECT ON THE V2 INTAKE. The source is a spreadsheet draft the estimate screen has
// split per sheet (`tax_flags_per_sheet`), whose Leveling and Gypsum (FR) sheets are tax-exempt while Epoxy is
// taxable. It goes through the REAL polish-sandbox.js buildCopy, then the REAL intake page boots on the copy,
// shows its switches, and saves because the estimator touched an UNRELATED switch (the realistic visit: they
// came back to set Prevailing wage, not to re-answer tax).
const vm = require("vm");

const TAX = ["Epoxy!B6", "Leveling!B6", 'Gyp (USG 1-8")!B8', "Gyp (FR)!B8", "Polish!B6",
             "Epoxy!D6", "Polish!D6", 'Gyp (USG 1-8")!D8'];
const SPLIT_CELLS = {
  "Epoxy!B6": "Yes", "Epoxy!D6": "No", "Polish!B6": "Yes", "Polish!D6": "No",
  "Leveling!B6": "No", "Gyp (FR)!B8": "No", 'Gyp (USG 1-8")!B8': "Yes", 'Gyp (USG 1-8")!D8': "Yes",
};
const pickCells = (cv, cells) => Object.fromEntries(cells.map((c) => [c,
  cv && Object.prototype.hasOwnProperty.call(cv, c) ? cv[c] : null]));
const without = (obj, keys) => Object.fromEntries(Object.entries(obj).filter(([k]) => keys.indexOf(k) < 0));

const sandboxWin = { TWWorkTypes: W };
vm.runInNewContext(read(path.join(ROOT, "js", "polish-sandbox.js")),
  { window: sandboxWin, document: { getElementById: () => null }, console });
const SB = sandboxWin.TWPolishSandbox;

function source(cells, over) {
  const full = Object.assign({
    project_name: "Nearman Creek", work_type: "polish", audience: "Direct", polish_sf: 2875,
    address: "1 Water Works Dr", city: "Kansas City", state: "KS", zip: "66101",
    tax_flags_per_sheet: true, base_tab_id: "Polish",
    priced_tabs: [{ id: "Polish", total: 13265, flag_cells: { taxable: "Polish!B6", remodel: "Polish!D6" } }],
    proposal_lump_sum: 13265,
    cell_values: Object.assign({ "Epoxy!B4": "Yes", "Polish!B4": "Yes", "Epoxy!D5": "No", "Epoxy!B10": "New",
                                 "Polish!B10": "New", "Polish!E25": "No", "Polish!E29": "No", "Polish!F29": "No",
                                 "Epoxy!E20": 4000 }, cells),
  }, over || {});
  // a key handed in as undefined is a key the draft does not have
  return Object.fromEntries(Object.entries(full).filter(([, v]) => v !== undefined));
}

/** The copy of `src` on the real intake page: what it shows, then what the save after a click writes. */
async function visit(src, clicks) {
  const copy = SB.buildCopy(src, "src-1");
  const b = build({ blob: copy });
  await b.api.boot();
  const savesOnOpen = b.rec.saves.length;
  const shown = Object.fromEntries(readSwitches(b.dom.nodes["conditions"].innerHTML).map((s) => [s.key, s.on]));
  (clicks || ["prevailing_wage"]).forEach((k) => clickSwitch(b, k));
  b.clock.fire();
  const last = b.rec.saves[b.rec.saves.length - 1];
  // the page saves on every edit: once more, on top of the first
  b.api.saveSoon();
  b.clock.fire();
  const again = b.rec.saves[b.rec.saves.length - 1];
  return {
    marker: copy.tax_flags_per_sheet === undefined ? null : copy.tax_flags_per_sheet,
    savesOnOpen: savesOnOpen,
    shown: shown,
    taxable: last.polish_estimate.conditions.taxable, remodel: last.polish_estimate.conditions.remodel_tax,
    cells: pickCells(last.cell_values, TAX),
    cellsAgain: pickCells(again.cell_values, TAX),
    reno: pickCells(last.cell_values, ["Epoxy!B10", "Polish!B10"]),
    renoAgain: pickCells(again.cell_values, ["Epoxy!B10", "Polish!B10"]),
  };
}

(async function () {
  const out = {};
  // THE TASK'S CASE: Leveling and Gypsum (FR) tax-exempt, Epoxy taxable, the draft split.
  out.split = await visit(source(without(SPLIT_CELLS, ["Polish!B6", "Polish!D6"])));
  // the base sheet's own answer is in the draft: Polish is tax-exempt and remodel is on. The switches must
  // show THOSE (not Epoxy's Yes and No), and a save must put them back as they were.
  out.baseOwn = await visit(source(Object.assign({}, SPLIT_CELLS, { "Polish!B6": "No", "Polish!D6": "Yes" })));
  // the estimator flips Taxable on this page: the base sheet's answer moves and the options' do not
  out.flipped = await visit(source(SPLIT_CELLS), ["taxable"]);
  // a draft that is NOT split keeps the fan-out
  out.unsplit = await visit(source(SPLIT_CELLS, { tax_flags_per_sheet: undefined }), ["taxable"]);
  // Renovation answered on the second of its two cells only
  out.reno = await visit(source(Object.assign({}, SPLIT_CELLS, { "Epoxy!B10": "", "Polish!B10": "Reno" })));
  // A copy that ALREADY HAS a v2 estimate: nothing is seeded onto it, so the read the page makes as it adopts
  // the draft is the only one. The model says taxable and no remodel, the base sheet's own cells say tax-exempt
  // and remodel, and Epoxy's say the opposite of both. The cell wins, and it is Polish's.
  out.savedV2 = await visit(source(Object.assign({}, SPLIT_CELLS, { "Polish!B6": "No", "Polish!D6": "Yes" }), {
    polish_estimate: { version: 2, takeoff: [], conditions: { local: true, prevailing_wage: false, taxable: true,
      remodel_tax: false, bond: false, dye: false, joint_filler: false, remove_existing_jf: false } } }));
  console.log(JSON.stringify(out));
})().catch((err) => { console.error(err && err.stack || err); process.exit(1); });
