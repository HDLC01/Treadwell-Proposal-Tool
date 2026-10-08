// Appended to polish-estimate-harness.js's prelude by condition-cells-takeoff-harness.js: `build`, `blob`,
// `clone`, `B`, `W`, `ROOT`, `read` and the rest are in scope.
//
// WHAT HAPPENS TO A SPLIT PROJECT WHEN IT IS COPIED INTO ESTIMATING TOOL V2. The source is a spreadsheet draft
// the estimate screen has split per sheet (`tax_flags_per_sheet`), whose Leveling and Gypsum (FR) sheets are
// tax-exempt while Epoxy is taxable. It goes through the REAL polish-sandbox.js buildCopy, then the REAL
// Takeoff page opens the copy, and the page's own save (saveSoon -> buildSavePatch) is read back.
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

/** The copy the sandbox makes of `src`, opened on the real Takeoff page: what the page read off the draft,
 *  what opening wrote, and what its first save wrote into the cells. */
async function open(src, press) {
  const copy = SB.buildCopy(src, "src-1");
  const b = build({ blob: copy });
  await b.api.init();
  const savesOnOpen = b.rec.saves.length;
  const read = clone(b.api.model().conditions);
  if (press) Object.assign(b.api.model().conditions, press);
  b.api.saveSoon();
  b.clock.fire();
  const last = b.rec.saves[b.rec.saves.length - 1];
  // and the second save, on top of the first (the page saves on every edit)
  b.api.saveSoon();
  b.clock.fire();
  const again = b.rec.saves[b.rec.saves.length - 1];
  return {
    marker: copy.tax_flags_per_sheet === undefined ? null : copy.tax_flags_per_sheet,
    savesOnOpen: savesOnOpen,
    taxableRead: read.taxable, remodelRead: read.remodel_tax,
    cells: pickCells(last.cell_values, TAX),
    cellsAgain: pickCells(again.cell_values, TAX),
    reno: pickCells(last.cell_values, ["Epoxy!B10", "Polish!B10"]),
    renoAgain: pickCells(again.cell_values, ["Epoxy!B10", "Polish!B10"]),
    total: last.computed_bid.lump_sum,
  };
}

(async function () {
  const out = {};
  // THE TASK'S CASE: Leveling and Gypsum (FR) tax-exempt, Epoxy taxable, the draft split.
  out.split = await open(source(without(SPLIT_CELLS, ["Polish!B6", "Polish!D6"])));
  // the base sheet's own answer is in the draft: Polish is tax-exempt, so the page must read it (and not Epoxy's Yes)
  out.baseExempt = await open(source(Object.assign({}, SPLIT_CELLS, { "Polish!B6": "No" })));
  // the estimator flips Taxable in v2: the base sheet's answer moves and the options' do not
  out.flipped = await open(source(SPLIT_CELLS), { taxable: false, remodel_tax: true });
  // a draft that is NOT split keeps the fan-out: every literal follows the one answer
  out.unsplit = await open(source(SPLIT_CELLS, { tax_flags_per_sheet: undefined }), { taxable: false });
  // Renovation answered on the second of its two cells only: it survives opening and two saves
  out.reno = await open(source(Object.assign({}, SPLIT_CELLS, { "Epoxy!B10": "", "Polish!B10": "Reno" })));
  // A copy that ALREADY HAS a v2 estimate (opened and saved before). Nothing is seeded onto it, so the read
  // the page makes as it parses is the only one: the model says taxable and no remodel, the base sheet's own
  // cells say tax-exempt and remodel, and Epoxy's say the opposite of both. The cell wins, and it is Polish's.
  out.savedV2 = await open(source(Object.assign({}, SPLIT_CELLS, { "Polish!B6": "No", "Polish!D6": "Yes" }), {
    polish_estimate: { version: 2, takeoff: [], conditions: { local: true, prevailing_wage: false, taxable: true,
      remodel_tax: false, bond: false, dye: false, joint_filler: false, remove_existing_jf: false } } }));
  console.log(JSON.stringify(out));
})().catch((err) => { console.error(err && err.stack || err); process.exit(1); });
