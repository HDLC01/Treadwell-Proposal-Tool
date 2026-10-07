# Estimating Tool v2: how the code is laid out

This is the map for the v2 estimating program: what the modules are, how they depend on each
other, the rules every change follows, and a table of every place the same fact is written down
today, with what happens to each copy.

**What exists today, and what does not.** The tests and the golden files described in section 6
exist now, and so does the workbook oracle (Phase 6, also section 6). The modules in section 3 other
than `bid-model.js`, `excel-math.js`, `library-core.js` and `markup-core.js` do not exist yet: they
are the design the phases build toward. The one exception is `js/bid-profiles.js`, which Phase 6
created with only the cell maps of the eleven priced tabs in it; the rates and rules come in Phase 8.
`bid-model.js` is the old `polish-bid-core.js` under its new name, and `excel-math.js` is the leaf
Phase 5 took the model's number helpers out into, both with no change to what any of it does (see
"Module names" and "The leaf" below). Phase 4 added `patchModel`, `buildSavePatch` and `MODEL_KEYS`
to the model (see 7.10 and the model-safety paragraph of section 6). Line numbers in this document
are on `origin/staging` at commit `3f94ed2` (2026-10-07), except where a paragraph says they are on
the Phase 4 change, and except every line number in `js/bid-model.js` or `js/excel-math.js`, which is
on the Phase 5 change. They will drift; the file and the name are what to search for.

**Names.** The tool people called the Polish beta is now **Estimating Tool v2**, and its database
page, which was the Polish Estimate Database, is now **v2 Estimates** (Phase 1b, 2026-10-07). Only
the words a person reads changed: the two sidebar rows, the page titles and headings, the two doors
into the tool (Estimate Review and the live intake), the Proposals Database tab that was called Beta
Polish, and the sentences on the Items and Assemblies, Markup and Admin pages that name the tool.
File names and addresses (`polish-intake.html`, `polish-estimate.html`, `polish-estimates.html`),
element ids, the `polish_estimate` key with `version: 2`, the `polish_beta` flag on a project
summary, the `beta` tab key, and the "(beta test)" ending on the name of a test copy all keep their
names, because saved projects, permissions and bookmarks are keyed on them. Comments and tests
written before the rename still say "Polish beta" and mean this tool. `backend/tests/test_v2_names.py`
holds the new names in place and fails if an old one comes back in anything a person can read.

**Module names (Phase 5, 2026-10-07).** The model module `js/polish-bid-core.js` is now
`js/bid-model.js`, and its browser global `TWPolishBid` is now `TWBidModel`. Every exported name is the
same, so a page changes its script tag and its one `window.TWBidModel` line and nothing else. No file
is left under the old name and nothing answers to the old global: a page that still asked for either
would fail at once, where an alias would let it read a stale copy. Saved projects, routes and
permissions are untouched, because none of them is keyed on the module's name (`polish_estimate`,
`polish_beta`, the page file names and `/api/polish/verbal-intake` all keep theirs).
`backend/tests/test_bid_model_rename.py` fails if the old file, the old global or either old name
comes back anywhere under `frontend/` or `backend/`. This document is outside that scan on purpose: it
is where the old names are allowed to appear, as history.

**The leaf (Phase 5).** `js/excel-math.js` holds the helpers that were at the top of the model: `num`,
`copyInto`, `roundUp`, `money`, `money2`, `pct`, `fmtSf` and `isBlank`, moved byte for byte, plus one new
function, `ceiling` (Excel's CEILING, the workbook engine's own arithmetic). Nothing on the bid side
calls `ceiling` yet: the Epoxy tab has 78 CEILING formulas and Phase 8 is where they are priced. The
model reads the leaf through the header in section 4 and binds each helper to its old name, so every
line of the model and every caller (`B.roundUp`, `B.money` and the rest) is unchanged, and `B.roundUp` is
the very same function as `TWExcelMath.roundUp`. Three things were looked at and left where they are,
each for a reason written in 7.5 and 7.11: `markup-core.js` keeps its own `excelRoundUp`,
`library-core.js` keeps its own pack count, and `isV2Draft` stays in `shared.js`. `isObject` also stayed
in the model, because only the model uses it, and a helper moves into the leaf when two modules need it.

## 1. Why this exists

Estimating Tool v2 (first called the Polish beta) was built one screen at a time, and the same fact ended up in many files. The list
of work types is written down more than ten times across JavaScript and Python. The job conditions
(prevailing wage, taxable, dye and so on) are described in nine places. ROUNDUP is written three
times for the bid and once more inside the workbook engine. The v2 intake carries its own 300-line
copy of the county picker. The estimate page builds the blob it saves in two places, and the two
have already drifted apart.

Making v2 work for every work type (Polish, Epoxy, Combo, Gyp, with Seal and Leveling as options)
would copy all of that again for each type. So the program replaces the copies first. A fact gets
one home, everything else reads from it, and a test fails if a second home appears.

## 2. The idea in four lines

- **One source per concept.** A work type, a condition, a rate, a rounding rule each live in one file.
- **Data, not code.** A work type or a rate is a row in a table. Adding one is adding a row.
- **One engine.** The markup chain is one function that walks a profile. It does not know which sheet it is pricing.
- **A profile per sheet tab.** Polish, Epoxy, Gyp, Seal and Leveling are each a profile (a block of data), not a copy of the engine.

## 3. The modules and their layers

Each layer may use the layers above it in this table and nothing below it. A leaf uses nothing.

| Layer | File | What it owns | Uses |
|---|---|---|---|
| leaf | `js/excel-math.js` | `num`, `roundUp`, `ceiling`, `copyInto`, `isBlank`, and the text helpers `money`, `money2`, `pct` and `fmtSf`. The one bid-side ROUNDUP. Exists since Phase 5, with functions only: no rate and no table | nothing |
| leaf (data) | `js/work-types.js` | The one vocabulary: job types (polish, epoxy, combo, gyp) and tabs (polish, epoxy, gyp, seal, leveling; seal and leveling are option-only). For each: label, which tabs a job type prices (combo is Epoxy plus Polish), workbook tab ids, role, quantity fields and snapshot keys, proposal template keys, whether it is ready. Also the one job-conditions table. | nothing |
| leaf (data) | `js/bid-profiles.js` | One profile per sheet tab as plain data: rates and GP ladders as formula strings, cell maps, labor built-ins. A profile can extend another (Seal is Polish plus a few changes). The one home of the global defaults: labor rate, lodging, per diem, fees, sales tax. | nothing |
| model | `js/bid-model.js` (Phase 5 renamed it from `js/polish-bid-core.js`, with no logic change) | The saved estimate: fresh, migrate, seed a new bid, labor, travel, distance, conditions per section; building the save patch; composing the price snapshot the proposal reads. | excel-math today; work-types and bid-profiles when they exist |
| engine | `js/bid-engine.js` | `priceChain(profile, input, rates)`: the markup chain for any profile. Turns the filed Markups rules into numbers. Adds the tabs of a combo job after each tab has had its own gross profit. | excel-math, bid-profiles, markup-core |
| render | `js/intake-scope.js` | Draws and shows the quantity fields of the intake from `work-types.js`. Extracted from `js/index.js`; the live intake then calls it. | work-types |

Already shared and kept as they are: `js/library-core.js` (priceLine and priceAssembly, every
material), `js/markup-core.js` (reads and evaluates the Markups formulas), `js/xl-excel-rounding.js`
(the workbook engine's ROUNDUP and CEILING), `js/county-picker.js`, `js/address-lookup.js`,
`js/tab-memo.js`.

Pages (`polish-estimate.js`, `polish-intake.js`, `index.js`, `estimate-review.js`, `proposal-review.js`)
sit on top of all of this and hold only what is about the screen.

## 4. The header every module carries

Every shared module is one file that works in two places: a browser (a script tag defines a global
such as `TWLib`) and node (the tests `require` it). Most modules that exist today have no
dependencies, so their header is short:

```js
(function (root, factory) {
  var api = factory();
  root.TWLib = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;   // node, for tests
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  // ... pure functions, no DOM, no fetch ...
  return { /* the public names */ };
});
```

A module that depends on another one declares it in the header and fails loudly if it is missing:

```js
(function (root, factory) {
  var isNode = typeof module !== "undefined" && module.exports;
  var deps = {
    math: isNode ? require("./excel-math.js") : root.TWExcelMath,
    types: isNode ? require("./work-types.js") : root.TWWorkTypes
  };
  if (!deps.math) throw new Error("bid-model.js needs excel-math.js loaded before it");
  if (!deps.types) throw new Error("bid-model.js needs work-types.js loaded before it");
  var api = factory(deps);
  root.TWBidModel = api;
  if (isNode) module.exports = api;
})(typeof self !== "undefined" ? self : this, function (deps) {
  "use strict";
  // ...
});
```

`js/bid-model.js` carries this header today with `excel-math.js` as its one dependency. The line for
`work-types.js`, and its error, are added the day that module exists.

Rules that go with it:

- The error names the file to load first. A missing dependency must not show up later as "undefined is not a function" in the middle of a price.
- Script tags in a page load in layer order: leaves, then data, then model, then engine, then the page.
- Every page that loads a module runs what its header declares first, and the browser runs it first (a `defer`red leaf is too late for a plain module). `backend/tests/test_core_boot_order.py` finds the modules and the pages by reading the headers and the HTML, checks the order, and runs each page's modules the way a browser does, so a new leaf needs no edit to any test.
- No inline scripts anywhere (the site's content security policy forbids them).
- A core module never touches the DOM, never calls `fetch`, and never reads the clock.

## 5. The rules every change follows

1. **Replace, do not run in parallel.** A change that adds the new home removes the old copies in the same change, or says in its description which rows of the table in section 7 it leaves and why. Two sources for one fact is the defect this program removes.
2. **Data, not code.** A work type, a condition, a rate or a cell address is a row in a table. An `if` chain on a work type name is a sign the row is missing.
3. **No hard-coded line items.** Materials are library rows. When the library cannot express a formula (for example a cove that rounds twice, or gypsum bags by thickness), the contract is the one Dye and Joint Filler already follow: an editable reserved library row is the price source, the formula lives in code, a constant is only the fallback, and a test pins the row to the fallback. Each such case is listed for Hanz and Kyle as a named modelling gap.
4. **A layout or profile is a required argument.** A new function that needs to know the sheet takes it as an argument and throws when it is missing. It never quietly assumes Polish.
5. **User data is never used as a property name.** No `obj[userKey] = value` on draft or user data. Use a `Map`, or `copyInto`. CodeQL flags the first.
6. **No regex for stripping markup in tests.** Use `stripTags` from `backend/tests/js/_lib.js`, which repeats until nothing changes. A single pass can build a tag out of two others. Build a regex from a variable only through `escapeRegExp`.
7. **Functions that a test lifts by name keep their name.** The node harnesses in `backend/tests/js` pull functions out of the page files by name. A new helper that a lifted function calls goes into a core module, which the harness loads whole. Put it in the page file and the lifted copy fails with a ReferenceError. Search for `fn("` and `lift(` in `backend/tests/js` before renaming or splitting a function.
8. **Tests run the code and fail without the change.** Prove it once by breaking a scratch copy of the code and watching the test go red. `backend/tests/_golden_support.py` has `break_source` for this, and it refuses a change that applied nowhere.
9. **Money moves only on purpose, and in view.** Every number a bid prints is behind a golden file or the saved-bid ratchet (section 6). A change either leaves those alone or changes them in the same pull request, and the diff is the review.
10. **Edit files without changing their line endings.** The Windows dev machine checks files out with CRLF while the repository keeps LF. Use the editor tool, never `sed -i`, and look at `git diff --stat` afterwards: a whole-file rewrite is a mistake.
11. **New words for users are plain.** Short words, no em dashes. Tests pin this for the pages that have it.
12. **Review.** Each phase gets an adversarial review, and CodeQL has a pre-flight grep before every push.

## 6. How we know a change did not move a price

Phase 3 added the instruments. None of them change product code.

**Golden masters.** A golden master is a file of inputs and the answers today's code gives for them,
cut once from a clean export of `origin/staging`.

- `backend/tests/fixtures/polish_chain_golden.json`: 2,228 vectors over the Polish maths. The whole bid (every gross-profit edge from a dollar either side, all 256 settings of the eight job conditions, every shape the remodel rate arrives in, dirty values like `"12,500"` and `"$1,200"`), the number helpers, labor and travel, the takeoff, the conditions and what they write into the workbook, the model, the labor calculator, what a new bid is started with, the exported data (`RATES`, `GP_BANDS`, `CONDITION_CELLS`), and the type of every name the module exports today. A name that goes missing or changes type fails. A new export does not, because adding a helper is not a pricing change.
- `backend/tests/fixtures/library_pricing_golden.json`: 874 vectors over `priceLine` and `priceAssembly`: waste, roundup, pack size, coverage, cost, every area, rows older than those columns, whole assemblies, Kyle's printed flake system.

Each is generated by a recipe (`tests/js/gen-chain-golden.js`, `tests/js/gen-library-golden.js`) that lists inputs only. The answers come from running the real functions, never from a second copy of the formulas. The recipes use no random numbers, so they regenerate byte for byte.

The comparison runs in node with `assert.deepStrictEqual`. JSON cannot hold `-0`, `NaN`, `Infinity` or `undefined`, so the files store them as tagged values and the comparison reads them back as real values. A change that turns `-0` into `0`, or `NaN` into `null`, fails. The tests prove this by breaking a copy of the module on purpose.

A function that edits its own argument in place and returns nothing (`setMeasurement` is one) has no answer to compare, so its vector also stores the arguments as the call left them (`after`). That pins what it wrote, not only that it wrote.

When a golden test is red it prints the first vectors that differ, with the path inside the answer:

```
chain/dirty/material/11/1000000000000000   markupChain({ material: 1000000000000000, ... })
    at .out.sub_total: golden 1020000000020000, now 1020000000019000
```

Decide whether that is the change you meant. If it is, regenerate with the command the failure prints
(`--write <file> --commit <sha>`), from a clean `git archive` of the commit you are changing from, and
review the fixture diff line by line. One vector is one line.

**The saved-bid ratchet.** `backend/tests/test_polish_saved_bid_safety.py` opens bids saved by older
and by today's page and requires the same total, no save on open, and no server call on open. The
newest shapes are pinned: the Lodging and Per Diem block, a saved distance, labor calculator rows,
rows saved switched off, `same_floor` rows, the bid's own coverage, Fees plus Textura, a library that
said no Travel Labor, and a stale `totals` snapshot the page must never price from. Each is opened
plain, opened beside a library full of defaults (a saved bid ignores it), and saved then reopened.

**The model's safety (Phase 4).** `backend/tests/test_v2_model_safety.py`, with
`tests/js/model-safety-harness.js`, holds the laws Phase 4 put in place. They run over every bid the
ratchet saves (lifted from its own scenarios, so a new fixture there is covered here) and over
synthetic models that carry `work_type`, `tabs`, a rates snapshot and a profile stamp.
`migrateModel` keeps every key it is given. `migrateModel` twice gives what `migrateModel` once does.
Reading a saved model never edits it. A key the model does not know comes back as saved, and `tabs`
comes back byte for byte. The estimate page is saved twice from identical drafts, once by its timer
and once by `pagehide`, and the two writes must be equal. An intake save after an estimate save
leaves `tabs` byte for byte as it was. The v1 upgrade is deliberately not a passthrough (it consumes
`areas` and `labour`), and the tests pin that too. The file ends with a table of twelve breaks of a
scratch copy, each of which must turn a law red.

**Strict node.** About 170 older test files skip when node is missing. On a CI runner that would
pass a run that tested none of the frontend. `tests/test_node_strict.py` fails under GitHub Actions
when node is absent, and runs the new golden tests with node taken off the path to prove they fail
there and skip on a laptop. New harness tests call `require_node()` from `tests/_node.py`.

**Shared harness helpers.** `backend/tests/js/_lib.js` (read with line endings fixed, `balanced`,
`lift`, `liftSource`, `grab`, `grabConst`, `stripTags`, `escapeRegExp`) and `backend/tests/js/_golden.js`
(the codec, the recorder, the comparison). Older harnesses keep their own copies and are not
converted. New harnesses use these.

**Loading scripts the way a page does (Phase 5).** Every other harness reaches a module with `require`,
and the dependency line in the module's header hides behind it. `backend/tests/js/core-boot-harness.js`
runs scripts in one fresh context with no `require` and no `module`, `self` and `window` the global, in
the order it is given, and reports what each published and what it threw. `backend/tests/_page_scripts.py`
is the one reader of a page's script tags and of the order a browser runs them in.
`backend/tests/_golden_support.py` carries whatever a module declares it needs into a scratch tree
(`break_source` and `copy_unmodified`), so a test that breaks a copy of the model gets the leaf beside it,
and a leaf added later needs no edit.

**Not covered, on purpose.** Words and pixels (`travelHow`, `distanceNote`, `sliderHtml`), the distance
lookup, and the page's rendering have their own harnesses. They are not what the program restructures.
One thing the golden recorded as it is today and nobody has decided to fix: `seedTakeoffSf` throws a
TypeError when the takeoff holds a null row. A second one, that the model dropped any saved key it
did not know, Phase 4 fixed, and the diff showed it: the chain golden moved by exactly one vector,
`model/migrate/unknownKeys`, which now keeps `tabs` and `custom_key`. The other 2,227 are as they
were, and so are the library golden and the saved-bid ratchet.

**The workbook oracle (Phase 6).** The goldens above pin what the code does today. The oracle pins what
Kyle's workbook does, which is what the code is supposed to do: `backend/templates/estimate_sheet_5.7.xlsx`,
evaluated by the same HyperFormula the Estimate Review page runs, is the answer key every v2 tab is checked
against.

- *The engine.* `docs/excel-parity-audit/engine.js` loads the exact bytes the page pins (it hashes the
  installed `hyperformula.full.min.js` and refuses to go on unless the sha384 is the one in
  `estimate-review.html`), registers `frontend/js/xl-excel-rounding.js` as it ships, uses the page's options
  and its alias rule for the names HyperFormula refuses, and loads all sixteen tabs. The Excel parity audit
  next to it uses the same module, so there is one way to build the workbook outside a browser.
  `test_workbook_oracle.py` lifts `HF.init` and the alias rule out of `estimate-review.js` and runs them to
  prove the options and the rule are the page's. HyperFormula is not a dependency of the repo (no
  `package.json`): install it outside (`npm i --no-save --prefix <dir> hyperformula@2.7.1`, then
  `NODE_PATH=<dir>/node_modules`).
- *The cell maps.* `js/bid-profiles.js` names, for each of the eleven priced tabs (Epoxy, Polish, Seal,
  Seal (+Jnts), Epoxy blank, Leveling, five Gyp), the cells at the edges of the markup chain: where material,
  labor, tooling, travel, fees and contingency come in, the five job questions, the rates, and where the bid
  comes out. Each entry carries what the template holds there. `test_workbook_formula_pins.py` reads every
  entry back out of the template (about 580 of them) and checks the copies of a layout against each other:
  the five Gyp tabs, Seal (+Jnts) against Seal, Seal against Polish, each difference listed with its reason.
- *The recorded answers.* `backend/tests/js/workbook-oracle.js` types numbers into the boundary cells of each
  tab (a dollar either side of every gross profit band, shipping tier and hard-bid threshold, all 32 settings of
  the five questions at three sizes, remodel rates, fees, contingency, bond, small and huge jobs, lodging) and
  writes what the chain answers into `backend/tests/fixtures/oracle/<tab>.json`, one file per tab, plus
  `meta.json`. About 2,000 cases. It also runs probes that start upstream of the boundary, for the odd rules.
  It checks itself first: every formula cell of all sixteen tabs must equal the value Excel saved in the
  file (about 17,000 cells), after putting back the labor rates the file was last calculated with (the
  template's rate cells were edited after its last calculation, see `docs/kyle-workbook-odd-rules.md`).
- *What CI does.* CI has no HyperFormula, so it only compares. A hash of the normalised (tab, address,
  formula or constant) of the priced tabs says "re-run the oracle" when Kyle changes a formula or a number,
  and does not fire when the file is merely re-saved or an unpriced tab is edited. The page's pinned
  HyperFormula and the rounding plugin are held to the recorded ones the same way. The recorded cases are
  checked to straddle every edge on the right side, to add up the way the sheet's total does, and to hold
  every kind of case. Where HyperFormula is installed, one more test recomputes everything and requires the
  recorded files byte for byte.
- *Regenerating.* `node backend/tests/js/workbook-oracle.js --write`, then read the fixture diff: one case is
  one line. A run with no flag compares and exits non-zero on any difference.
- *First user: Polish.* `oracle-polish-harness.js` runs today's model on every Polish case and requires it to
  equal the sheet except for the declared departures in `fixtures/oracle/departures.json` (no tooling line,
  a narrower remodel tax base, lodging counted in people-days, no hard bid, no bond). Two are predicted to the
  dollar from the model plus exactly what their reason says; all are seen on at least one case; a model change
  that closes one turns the test red until the list says so.
- *Kyle's odd rules.* `docs/kyle-workbook-odd-rules.md` lists the eleven places the sheet does something
  surprising (the bond counts the taxes twice, Leveling lodging divides by 8 on 10 hour days, and so on). v2
  reproduces them on purpose. `test_kyle_odd_rules.py` ties each to its cells, to recorded evidence and to the
  figures the document quotes, and runs each check on falsified evidence to prove it can fail.

## 7. Every concept, where it is copied today, and what happens to each copy

Line numbers are on `origin/staging` at `3f94ed2`, except those in `js/bid-model.js` and
`js/excel-math.js`, which are on the Phase 5 change. "Planned" means the phase in the program plan,
not something that has been done. The summary first, then the evidence for each row.

| | Concept | Copies today | Disposition | Phase |
|---|---|---|---|---|
| 7.1 | Work-type list, JavaScript | 9 places in 7 files | Each reads `js/work-types.js` | 7 (the v2 intake in 9) |
| 7.2 | Work-type list, Python | 7 files | Pinned to `js/work-types.js` by one test that runs node | 7 |
| 7.3 | Job-condition tables | 10 places | One conditions table in `js/work-types.js`. The Taxable cells are right by construction. The test copy's cell list reads it too | 7 |
| 7.4 | Built-in markup rates | 4 places | Profile data in `js/bid-profiles.js`. `markup.js` reads it. `pricing.py` is retired | 8, then 17 |
| 7.5 | ROUNDUP | 3 implementations (the leaf, `markup-core.js`, `pricing.py`), the workbook engine's plugin, 2 guards | Done: the model's copy is the leaf's `roundUp`, with a row in the parity test. `excelRoundUp`, the pack CEIL and `_roundup` stay, held equal by tests | 5 (done), 8, 17 |
| 7.6 | Intake scope maps | 4 places | Quantity fields live in `js/work-types.js`. `js/intake-scope.js` draws them | 7, then 9 |
| 7.7 | Role sets | 4 sets in 3 files | Computed from each tab's role in `js/work-types.js` | 7 |
| 7.8 | Job type to tab | 4 places | Each job type lists its tabs in `js/work-types.js` | 7 |
| 7.9 | The v2 intake's county picker | 1 copy, about 295 lines | Mount `js/county-picker.js` and delete the copy | 9 |
| 7.10 | The estimate page's two save blobs | 1 composition (was 2) | Done: one `buildSavePatch` used by both, and the intake's merge is one `patchModel` | 4 (done) |
| 7.11 | "Is this draft a v2 estimate" | 2 places, in two languages | Held equal by one test over one table. The JavaScript one stays in `js/shared.js` (Phase 5 left it there, see 7.11) | 2 (added) |

### 7.1 The work-type list, in JavaScript

| Copy | What it is |
|---|---|
| `js/index.js:70-75` | `SCOPE_BY_WORK_TYPE`: epoxy, polish, combo, gyp |
| `js/index.js:147-199` | A `scope: [...]` list of work types on each of the nine intake conditions |
| `js/library.js:2974` | `WORK_TYPES`: polish, seal, epoxy, leveling, gyp (the tab list, not the job types) |
| `js/estimate-review.js:671-673` | `BASE_ROLE`: workbook tab id to role |
| `js/proposal-review.js:226-232` | `effectiveWorkType`: which roles decide the document |
| `js/proposal-review.js:262-272` | The default narrative (scope, schedule, exclusions) keyed by audience and work type |
| `js/price-lines-core.js:472-476` | Work type to the generic flooring phrase |
| `js/coverletter-editor.js:93-97` | Work type to letter kind |
| `js/polish-intake.js:744` | The v2 intake writes `work_type: "polish"` and cannot write any other |

**Problem.** Adding a work type means finding every list. A list that misses it falls back to a
default without any error (the proposal falls back to the intake work type, a lookup falls back to
Epoxy). **Planned (Phase 7):** `js/work-types.js` is the one vocabulary, and each of these reads it.
The v2 intake gets the four job types in Phase 9, with types that are not ready shown disabled.

### 7.2 The work-type list, in Python

| Copy | What it is |
|---|---|
| `backend/markup.py:118` | `TABS`: polish, seal, epoxy, leveling, gyp. `backend/library.py:68` is `WORK_TYPES = markup.TABS`, one list in two names |
| `backend/leads.py:726` | `_WORK_TYPES`: epoxy, polish, combo, gyp |
| `backend/proposal_writer.py:61-71` | `TEMPLATE_PICKER`: (work type, audience) to proposal template |
| `backend/cover_letter_writer.py:99-106` | `TEMPLATE_PICKER`: (work type, audience) to cover letter |
| `backend/info_sheet_writer.py:263`, `:326-337`, `:366` | Which work types have a tab, `_SF_KEYS` and `_LF_KEYS` (snapshot keys per role), the label map |
| `backend/main.py:673-681` | `detect_work_type`: the rule that turns Epoxy and Polish square feet into epoxy, polish or combo |
| `backend/main.py:4561-4567`, `:6455` | The option price phrase by work type, and a tuple of work types that get the price rows |

**Planned (Phase 7):** Python is not generated from JavaScript. One test runs node, dumps the
vocabulary from `js/work-types.js` as JSON, and compares `markup.TABS`, `leads._WORK_TYPES`, the keys
of both `TEMPLATE_PICKER` tables and the info-sheet keys against it. A list that drifts fails the test.

### 7.3 The job-condition tables

| Copy | What it holds |
|---|---|
| `js/index.js:146-202` | `CONDITIONS` on the live intake: key, label, scope, default, the cells it writes, the on and off words, `needs`. Nine rows. Taxable writes four cells (Epoxy, Leveling and two Gyp tabs) |
| `js/polish-intake.js:66-82` | `CONDITIONS` on the v2 intake: four rows (prevailing wage, taxable, remodel tax, bond), keys only |
| `js/bid-model.js:1442-1469` | `CONDITION_CELLS`: seven rows with the cells they write. Taxable writes only `Epoxy!B6` |
| `js/bid-model.js:1745-1747` | The conditions of a fresh model, eight keys including `bond` |
| `js/polish-estimate.js:897-957` | `CONDITION_CARDS`: the Takeoff step's three cards (dye, joint filler, remove existing) |
| `js/library.js:2640-2657` | The Defaults tab's condition list, and `backend/condition_defaults.py:61` (`KEYS`) |
| `js/estimate-review.js:4032-4077` | `JOB_FLAG_ADDR`, `JOB_FLAG_LITERAL_LAYOUTS`, `JOB_FLAG_LAYOUTS`, `JOB_FLAG_TEMPLATE`: where the tax answers sit on each sheet layout |
| `backend/estimate_writer.py:394-406` | `POLISH_CELL_MAP` and its Epoxy sibling: key to cell letter |
| `js/polish-sandbox.js` | `COPYABLE_CELLS`: the live intake's fourteen condition cells again. A v2 test copy keeps these from its source (and no other cell), so it opens with the job's answers. Added in Phase 2 and held equal to the intake's table by `test_v2_routing_guard.py`, which lifts `CONDITIONS` out of `index.js` and compares |

**Problem.** The two Taxable tables disagree today: the live intake writes four cells and the v2 model
writes one, so a v2 bid never writes the Leveling or Gyp Taxable cell. The intake's comment records
the same fact kept in step by hand: "two copies of one fact is what this repo keeps paying for".
**Planned (Phase 7):** one table in `js/work-types.js` with key, label, why, default, scope, the cells
per tab, on and off words, `needs` and where it is asked. The live intake, the v2 intake, the Takeoff
cards, the Defaults tab and the test copy read it. The Taxable cells are right by construction because they come
from the same row. The per-layout addresses in `estimate-review.js` are checked against the workbook
by the test that already re-reads it (`test_taxable_flag_reaches_every_sheet.py`).

### 7.4 The built-in markup rates

| Copy | What it holds |
|---|---|
| `js/bid-model.js:99-130` | `RATES` (shipping 2%, escalation 5%, burden 12%, super and PTO 2.7%, soft costs 16%, sales tax 9.475%, bond 0, the Kansas remodel floor 6.5%) and `GP_BANDS` |
| `js/markup.js:215-253` | `GP_5_BANDS` and `BUILTIN`: the same for Polish, plus Seal, Epoxy (3% and 13%), Leveling, Gyp (4.1% and an expression), and the Global lines (labor rate 33, lodging 70, per diem 45) |
| `backend/pricing.py:272-292` | `_gp_pct` (the same ladder) and the defaults of `compute_full_bid` (33, 12%, 70, 45, 3%, 13%, 9.475%, a 10% remodel) |
| `backend/markup.py:20-24` | The same rates, written in the docstring as an audit of the workbook |

**Problem.** `markup.js` says its numbers are transcribed from `bid-model.js` and from
`markup.py`'s audit of the workbook, "and from nowhere else". A test (`test_markup_page.py` with
`markup-rate-harness.js`) keeps the pair equal, which is a pinned pair and not one value. `pricing.py`
only serves `/api/price` (`backend/main.py:3725`), which nothing in the frontend calls, and the
program plan records it as wrong on whipped-resin cove and on quartz and flake price breaks.
**Planned:** rates and ladders move into `js/bid-profiles.js` as formula strings (Phase 8).
`markup.js` reads them, so there is no pinned pair. `pricing.py` and `/api/price` are retired
(Phase 17). Until then `test_polish_markup_parity.py` and the goldens hold the numbers.

### 7.5 ROUNDUP, and rounding up generally

| Copy | What it is |
|---|---|
| `js/excel-math.js:65` | `roundUp`: away from zero, snapped to twelve significant figures first. The one bid-side ROUNDUP. It sat in the model until Phase 5, and `js/bid-model.js` now exports this very function |
| `js/excel-math.js:87` | `ceiling(n, significance)`: Excel's CEILING with the same guard. New in Phase 5, no caller yet |
| `js/markup-core.js:283` | `excelRoundUp(n, digits)`: the same, with a digits argument. Not exported |
| `backend/pricing.py:78` | `_roundup`: the same in Python (`"%.12g"`) |
| `js/xl-excel-rounding.js:64-90` | The workbook engine's ROUNDUP and CEILING (a HyperFormula plugin). A different job: it makes the sheet engine agree with Excel |
| `js/library-core.js:166` | The pack count is a CEIL with the same twelve-figure guard |
| `js/markup.js:501` | `round12`, the guard on its own |

`backend/tests/test_roundup_parity_js.py` compares the Python copy, the leaf, the model's re-export and
`markup-core.js` on the same 24,004 inputs. **Done (Phase 5):** the model's `roundUp` is the leaf's. The
parity test has a row for the leaf, and `backend/tests/test_excel_math.py` checks that the model's
`roundUp` is the very same function and not a copy. Three things were decided here, and one of them
corrects what this section said before:

1. **`markup-core.js` keeps `excelRoundUp(n, digits)`.** This section used to say it would call the leaf.
   It cannot without a change in behaviour. It takes a digits argument that the leaf's `roundUp(n)` does
   not, and a value that is not a number is an error there (`MarkupEvalError: ROUNDUP: expected a
   number`) where the leaf reads it as 0. Merging them means giving the leaf a digits argument and
   deciding what a non-number does in a Markups formula, which is a decision about the Markups page. It
   waits for Phase 8, when the bid engine uses both. The parity test holds the pair equal until then.
2. **`library-core.js` keeps its own pack CEIL.** The question this section left for Phase 5 was whether
   it calls the leaf's `ceiling`. It does not. `library-core.js` is dependency-free, several tests load it
   standalone, and its pack count is one line. What that costs is a pair that must not drift, so
   `test_excel_math.py` takes a grid of over a thousand real pack counts through `priceLine` and
   through `ceiling(needed / pack, 1)` and requires them equal. The grid is checked to hold cases where a
   bare ceil gives a different count, so it cannot pass by agreeing on easy numbers.
3. **The workbook plugin stays,** because it is the sheet engine's, not a bid-side copy.

`pricing.py`'s copy goes when `pricing.py` does (Phase 17).

### 7.6 The intake scope maps

| Copy | What it is |
|---|---|
| `js/index.js:70-75`, and the `data-scope` fields built at `:28-43` | Which quantity fields (epoxy SF, polish SF, cove LF) show for which job type |
| `js/estimate-review.js:363` and `:371-374` | `GYP_SF_CELLS` and `AREA_SF_CELLS`: the estimate cell each quantity lands in, per layout |
| `js/estimate-review.js:835-843` | `sfFieldsFor`: role to that map, with Seal sent to Polish's cell |
| `backend/info_sheet_writer.py:326-337` | `_SF_KEYS` and `_LF_KEYS`: the same fields by their saved names. A comment records that a missing Seal row once read Epoxy keys without complaint |

**Planned:** `js/work-types.js` carries the quantity fields and the snapshot keys for each work type
(Phase 7). `js/intake-scope.js` draws and shows them (Phase 9). The live intake delegates to it in the
same change that creates it, and a test proves the HTML is byte for byte what it is today, using
captures taken from the base commit. There are never two renderers. The Python keys are pinned to the
table by the same test as 7.2.

### 7.7 The role sets

| Copy | What it is |
|---|---|
| `js/estimate-review.js:797`, `:806`, `:922` | `PRICED_ROLES` (epoxy, polish, gyp, seal), `OPTION_ONLY_ROLES` (seal), `COMBINED_BASE_ROLES` (epoxy, polish) |
| `js/proposal-review.js:990-991`, `:1780` | The last two again, and an inline `["epoxy", "polish"]` |
| `backend/info_sheet_writer.py:348` | `_COVE_ROLES`: epoxy, combo |

**Problem.** The comment on `OPTION_ONLY_ROLES` explains why this is not cosmetic: a Seal base bid
once printed the Epoxy document with Seal's money. The two JavaScript copies are kept equal by a test
that greps both. **Planned (Phase 7):** each tab in `js/work-types.js` carries its role and an
`optionOnly` flag, and the sets are computed from it.

### 7.8 Job type to tab

| Copy | What it is |
|---|---|
| `js/index.js:303-305` | Job type to the tabs the split tax flags go to |
| `js/estimate-review.js:4336-4342` | `baseFlagSheets`: Polish to `["Polish"]`, combo to Epoxy and Polish, else Epoxy |
| `js/estimate-review.js:5203-5208` | `_areaBaseIds`: the tabs the proposal's area line is read from |
| `js/proposal-review.js:1140-1144` | The same, with fewer branches |

**Planned (Phase 7):** each job type in `js/work-types.js` lists its tabs (combo is Epoxy plus Polish),
and `appliesTo(defaultWorkTypes, layout)` answers "does this default apply to this tab". It throws when
asked about "combo", because a combo job has no tab of its own and a rate filed under that name could
never be read (the Markups page already refuses it by name).

### 7.9 The v2 intake's own county picker

| Copy | What it is |
|---|---|
| `js/polish-intake.js:333-628` | About 295 lines: `loadCounties`, `filterCounties`, `renderCountyResults`, keyboard handling, `pickCounty`, `clearCounty`, the note under the box, `hydrateCounty` from the draft |
| `js/county-picker.js` (394 lines) | The shared control the live intake already mounts (`index.html` loads it) |

Both write the same four keys: `county`, `county_tax_rate`, `county_remodel_rate`, `county_notes`.
**Planned (Phase 9):** the v2 intake mounts `county-picker.js` and its copy is deleted.

### 7.10 The estimate page's save, now one composition

Line numbers in this subsection are on the Phase 4 change, except those in `js/bid-model.js`, which are on the Phase 5 change.

| Copy | What it writes |
|---|---|
| `js/bid-model.js:2098` (`buildSavePatch`) | The one composition: `polish_estimate` (the model, every key it holds, with `totals` stamped from the bid), `cell_values` (the conditions merged over the draft's own, plus the library's figures for dye and joint filler), `polish_sf` (the priced area, else the measured floor), `polish_2_sf`, `computed_bid` |
| `js/polish-estimate.js:447` (`saveSoon`, the 600 ms autosave) and `:459` (the `pagehide` flush) | One call each: `B.buildSavePatch(M, draft, { bid: bid(), library: conditionLibrary() })`, laid over the draft |
| `js/bid-model.js:2050` (`patchModel`) and `js/polish-intake.js:716` (its one call) | The intake's merge: its `conditions` and `conditions_shown` laid over the saved model, every other key left as saved |

**Problem, as it was.** The autosave and the `pagehide` flush composed the blob by hand in two
places, and the two had drifted. A tab closed inside the debounce window did not refresh the
condition cells, and when the only SF row was switched off the flush saved a polish SF of 0 where the
autosave kept the measured floor. It was worse than the debounce window suggests: the page never
clears its timer handle once the timer has fired, so the `pagehide` handler ran on every page exit
after any edit, and with the only SF row off it overwrote the autosave's correct figure with 0. That
handle is left as it is, because both saves write the same patch now and the extra flush writes
nothing new. Separately, `migrateModel` rebuilt the model from a fixed key list, so any key it did
not name was erased by the next save.

**Done (Phase 4).** `buildSavePatch` is a pure function in the model, called by both saves, and it
throws when it is not handed the bid, because a save with no price is a save of zero. `patchModel`
states only `conditions` and `conditions_shown`, ignores any other key of its patch, and never states
`labor` on a bid that never stated it. `migrateModel`'s v2 branch carries every key it does not
normalise (`MODEL_KEYS` is the list it does), `tabs` included, through `copyInto`, which refuses
`__proto__`, `constructor` and `prototype`. The v1 branch is a one-way upgrade and stays as it was.
Nothing writes `tabs` yet: this change only makes it survive. The golden moved by one vector for
it (section 6), and `test_v2_model_safety.py` holds the laws.

### 7.11 "Is this draft a v2 estimate"

| Copy | What it is |
|---|---|
| `backend/drafts.py:958` | `_polish_beta`: `polish_estimate.version` is the number 2, or text that Python's `float()` reads as 2. Feeds the Projects page's `polish_beta`, which decides which intake a card opens on |
| `js/shared.js` | `isV2Draft`: the same rule in the browser. The two routing guards (`estimate-review.js`, `index.js`) and the Proposal step's pricing view (`v2PricingView`) ask it |

Two languages, so two copies, and that is the point of the table: a rule that differs by a spelling
sends a project to the wrong screen "but only sometimes". `test_v2_routing_guard.py` runs both on one
table of cases (`tests/_v2_cases.py`, which `test_beta_intake_routing.py` also uses), so a spelling that
one reads as v2 and the other does not fails there. **Not moved in Phase 5, on purpose:** the JavaScript copy
stays in `js/shared.js`. Its callers are `shared.js` itself (`v2PricingView`) and the two routing guards
on the spreadsheet step and the live intake, and neither of those pages loads `js/bid-model.js`. Moving it
would make them load the whole model for one comparison, and `shared.js` loads before every module, so it
cannot depend on one. It moves when the model is split or the guards read a small leaf. The two guards stand at the destinations, the spreadsheet step
and the live intake, and not at each link into them; `test_v2_routing_guard.py` scans the frontend for
links and fails on one it has not been told about.

A v2 test copy made before the copy was an allowlist still holds twelve keys the spreadsheet's Estimate step
writes (`SHEET_PRICING_KEYS` in `js/shared.js`). Two functions deal with them, and both are needed. The
Proposal step reads the draft through `v2PricingView`, which hides those keys and writes nothing. Continue
then takes them off the stored draft with `v2SheetKeysOut`. With the view alone, a copy whose source bid had
an option kept its `rooms` in storage: the customer's portal prices a proposal from the stored `rooms`
before it looks at `computed_bid`, the PDF is built from the document, and the send gate (`docDrift`) and the
server's publish route both refused the draft, with nothing on any page to clear it. The digest
(`publishDigest`, `_publish_digest`) is deliberately not read through the view: that would pass the draft
while the portal went on pricing the spreadsheet's rooms. A later phase that writes its own `priced_tabs`
(every tab marked `v2: true`) is handed back whole by both functions.

## 8. The phases, and where each touches this document

The phases, as the program plan numbers them. Each is its own pull request to staging.

| Phase | What it is |
|---|---|
| 0 | Finish the approved removal of "Type my own" |
| 1a | Audience first on both intake forms |
| 1b | The names "Estimating Tool v2" and "v2 Estimates", and the table of copies (section 7) |
| 2 | A routing guard so a v2 draft cannot open in the spreadsheet, and the test-copy allowlist that fixes the stale total |
| 3 | Characterization: the goldens, the saved-bid ratchet, the shared harness helpers, strict node |
| 4 | Model safety: `migrateModel` keeps unknown keys, round-trip tests, one `buildSavePatch` |
| 5 | Rename `polish-bid-core.js` to `bid-model.js` with no logic change, and add the `excel-math.js` leaf |
| 6 | The workbook oracle and per-sheet goldens, Polish first |
| 7 | `js/work-types.js` replaces the JavaScript copies; the Python pin; Taxable cells right by construction |
| 8 | `js/bid-profiles.js` and `js/bid-engine.js`; Polish runs through a profile and its golden does not move; an Epoxy profile proven on goldens |
| 9 | `js/intake-scope.js`; the live intake delegates to it; the v2 intake for the four job types; the shared county picker |
| 10 | Multi-section estimates, the price snapshot the proposal reads, per-tab rates snapshotted |
| 11 | Library columns (price breaks, bulk cost, coverage basis) |
| 12 | The seed script, and Epoxy end to end |
| 13 to 16 | Combo, Gyp, the Seal option, the Leveling option |
| 17 | Polish rev2 for new bids only; retire `pricing.py` and `/api/price` |

v2 bids stay test copies until Kyle signs off each work type. Where each phase touches this document:

| Phase | What changes here |
|---|---|
| 1b | The Names paragraph under the title. Section 7 is unchanged: no copy in it is about a name. |
| 2 | 7.3 and 7.11. The test copy's cell list is one more copy of the intake's condition cells until Phase 7. `isV2Draft` is a second copy of `_polish_beta`, held equal by a test. |
| 3 (this one) | Sections 3 to 7 are written. Goldens, ratchet, strict node, shared helpers. |
| 4 | 7.10. The model keeps unknown keys; one save patch. Done. |
| 5 | Done. The module rename and the leaf in section 3 (with the paragraphs "Module names" and "The leaf"), the header in section 4, 7.5 (the model's ROUNDUP is the leaf's, and what was left where it is), and 7.11 (the move that did not happen). |
| 6 | Done. Section 6, the workbook oracle, and the `js/bid-profiles.js` row of section 3 (the file exists, with only the cell maps in it). Nothing in section 7 changes: none of its copies is about the workbook's own cells. |
| 7 | 7.1, 7.2, 7.3, 7.6, 7.7, 7.8. `js/work-types.js` and the Python pin. |
| 8 | 7.4. `js/bid-profiles.js` and `js/bid-engine.js`; Polish runs through a profile and its golden does not move. |
| 9 | 7.6, 7.9. `js/intake-scope.js`; the v2 intake for the four job types. |
| 10 and later | Multi-section estimates, and the work types one at a time. v2 bids stay test copies until Kyle signs each work type off. |
