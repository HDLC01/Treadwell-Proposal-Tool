# Estimating Tool v2: how the code is laid out

This is the map for the v2 estimating program: what the modules are, how they depend on each
other, the rules every change follows, and a table of every place the same fact is written down
today, with what happens to each copy.

**What exists today, and what does not.** The tests and the golden files described in section 6
exist now, and so does the workbook oracle (Phase 6, also section 6). Every module in section 3 exists
except the v2 intake's use of `intake-scope.js`, which Phase 9 finishes (9a created the module and moved the live intake onto it). `js/bid-profiles.js` was created by Phase 6
with only the cell maps of the eleven priced tabs in it, and Phase 8 added its second half (the profiles, the
global defaults and the table of Markups lines) and created `js/bid-engine.js`, which prices a bid from a profile
(see "The engine and the profiles" below). The estimate page calls the engine through `markupChain`, a thin wrapper over it,
and, since Phase 10, through `priceSection` for any section beyond the Polish one, which no saved bid has yet
(see 7.10).
`bid-model.js` is the old `polish-bid-core.js` under its new name, and `excel-math.js` is the leaf
Phase 5 took the model's number helpers out into, both with no change to what any of it does (see
"Module names" and "The leaf" below). Phase 4 added `patchModel`, `buildSavePatch` and `MODEL_KEYS`
to the model (see 7.10 and the model-safety paragraph of section 6). Line numbers in this document
are on `origin/staging` at commit `3f94ed2` (2026-10-07), except where a paragraph says they are on
the Phase 4 change, and except every line number in `js/excel-math.js`, which is on the Phase 5 change.
The citations that Phase 7 wrote or rewrote (in 7.1, 7.3 and the vocabulary paragraph below) are on the
Phase 7 change. Phase 7 also moved lines in `js/bid-model.js`, `js/library.js`, `js/polish-intake.js`,
`js/polish-estimate.js` and `js/polish-sandbox.js`, and the older citations to those five files in the
other subsections were not recounted. They will drift; the file and the name are what to search for.

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

**The vocabulary (Phase 7).** `js/work-types.js` is a leaf in the same sense `excel-math.js` is. It is data and a few readers, with no
dependency, and it holds four tables: the four job types (epoxy, polish, combo, gyp, each with the tabs it
is priced on, whether v2 prices it yet, its proposal template key and the audiences that have one), the
five tabs of the workbook (polish, seal, epoxy, leveling, gyp, each with its sheets, role, markup layout
and whether it is option-only, which Seal and Leveling are, and whether v2 offers it as an option yet, which Seal does since Phase 15), the nine intake quantity fields with the key
each is filed under on the estimate screen, and ONE table of the job conditions. A condition row says what
the question is called and how it is worded, what a new job answers, which job types are asked it, which
workbook cells the answer is written to and with which two words, what it needs, which of three screens
ask it (the live intake, v2's intake and v2's Takeoff step) and in what position, whether the v2 model
carries the answer, and which reserved library row prices it. The readers are `tabsFor` (a job type's
tabs, and a throw for anything that is not a job type), `appliesTo` (does a default scoped to these tabs
apply to this tab: an empty list is every tab, and a job type such as combo is refused by name),
`conditionsFor`, `cellsFor`, `copyableCells`, `modelDefaults` and a few lookups.

What reads it now: `js/bid-model.js` derives `CONDITION_CELLS` (`js/bid-model.js:1479`) and the conditions
of a fresh model from it, and answers `workTypeApplies` (`js/bid-model.js:1387`) and the default takeoff
through `tabsFor` and `appliesTo`, so a combo job reads the Epoxy defaults and the Polish defaults where it
used to read neither. `js/polish-intake.js` takes its `CONDITIONS` (`js/polish-intake.js:77`), `js/polish-estimate.js`
its `CONDITION_CARDS` (`js/polish-estimate.js:910`; the page keeps what each card says), `js/library.js` its
`WORK_TYPES` (`js/library.js:2988`), its reserved rows and its Takeoff conditions, and `js/polish-sandbox.js`
its `COPYABLE_CELLS` (`js/polish-sandbox.js:269`). Each of those pages loads `work-types.js` before the
script that reads it, and `bid-model.js` names the file in its error if it is missing. The live intake
(`js/index.js`) and the estimate and proposal screens keep their own copies for now, and 7.1 to 7.8 say which
and why. Since Phase 7b the live intake also reads the file, for one thing only: which cells the two tax
switches write on a split draft (`index.html` loads `js/work-types.js` before it, and the page throws by name
without it).

Two things a save writes into the workbook cells changed, and no price did. A job type now writes exactly the
cells the live intake writes for it, so a v2 save writes the Taxable answer to Leveling!B6 and to the two
Gyp sheets as well as Epoxy!B6, which it used to leave out (a tax-exempt option on a v2 bid kept charging
9.475%). And a v2 save writes the Renovation cells, Epoxy!B10 and Polish!B10, which the live intake writes for
every polish job and v2 never did: whatever is there stays (a "Reno" the live intake or the autofill put
there survives), and a blank becomes "New", because Kyle's template ships both blank and a blank B10 is not
"New" to the formula that sets the patch material rate, it takes the Reno branch. The chain golden moved by
exactly the 48 vectors that record those cells (section 6), and the saved-bid ratchet's totals did not move.
The model does not carry a Renovation answer, so nothing on a v2 screen can change it yet.

**The engine and the profiles (Phase 8).** `js/bid-engine.js` holds one function that prices any tab,
`priceChain(profile, input, rates)`, and `js/bid-profiles.js` (its part two) holds what makes one tab differ from
another as data. A profile is plain JSON: an `extends` link, a closed set of thirteen named quirk flags, and rates as
Markups formula text. There are eight: `polish` (Kyle's Polish tab exactly), `polish-rev2` (Phase 17: `polish-legacy` with
the tooling line in the sub-total and the remodel tax on the sheet's base; the profile a NEW bid's Polish section is
priced by, see 7.12), `polish-legacy` (what the v2 model has
always charged: polish with six quirks turned the other way, four of which are the chain departures of
`departures.json` and two of which are the model's own: the Kansas floor for a missing remodel rate and no travel
taken from lodging), `seal`
(polish plus a sixth GP rung), `epoxy`, `epoxy-blank`, `leveling` (epoxy blank with ten hour days and the
escalation left out of the sub-total) and `gyp` (seven GP tiers, a split shipping rule, an expression for soft
costs). Each of the eleven priced tabs names its profile in a table, and a Gyp tab also names its truckload. A rate
is text in the Markups vocabulary (`2.7%`, `MARKUP(BAND(subtotal, ...))`), read by `markup-core.js` and snapped to
twelve significant figures, so a rate built in and a rate filed on the Markups page are one kind of thing and
one reader serves both. `compileRates(profile, rules)` reads the filed rules into the text a section would save,
`ruleNumber(rules, layout, line)` reads one, and a rule that cannot be read, cannot be worked out or comes to a
dollar figure where a rate belongs makes the line unpriceable with a reason, never $0. `combine(tabs)` adds the
tabs of a Combo job after each has taken its own gross profit, because pooling the sub-totals lands the job on a
lower rung than either part. The global defaults (labor rate, lodging, per diem, fees, sales tax, the bond, the two
remodel rates) have one home, `defaults`, and `bid-model.js` reads its `RATES`, `GP_BANDS` and shipped figures off
it. `markupChain` returns the keys and values it always did: `polish_chain_golden.json` has no change, and neither
do the saved-bid totals. Layout is a required argument everywhere, and a call without one throws. Two things are
left on purpose. No page prices with the engine itself yet, so no bid moved. And the odd rules that live before the
chain (the fractional bags, the travel hours, the overage rows, the cove aggregate) are the takeoff's: the chain is
handed their dollars.

**Epoxy end to end (Phase 12).** An Epoxy job is priced in v2 and `ready` is `true` for it. The library gets Kyle's Epoxy
and Gyp materials from a one-time script, `backend/ops/seed_library_from_workbook.py` (dry run by default, `--apply
--target staging` only, insert-only), and `js/epoxy-takeoff.js` carries the four things the Epoxy sheet does before its
chain that a library row cannot say. An Epoxy job is an Epoxy SECTION of the bid with the Polish root marked off
(`sectionsForJob`), and the estimate page's Material, Labor and Review panels edit whichever section is on show
(`sectionView`). The proof is in section 6 ("The Epoxy proof") and the named modelling gaps are in the Phase 12 row of
section 8. v2 Epoxy bids stay test copies until Kyle signs the work type off.

**Combo end to end (Phase 13).** A Combo job is priced in v2 and `ready` is `true` for it. It is TWO base sections of one
bid, the Polish root and an Epoxy section (`sectionsForJob`), each priced on its own profile; the bid is `combine` (each
section's total after its own gross profit, summed), and the job's Hotel and Per Diem are charged once, on the section that
carries them (the first base, Polish). The estimate page's strip switches between the two, a section that does not carry the
travel says where it is charged, and the Review step shows both sections and the combined base bid. A save writes both as
base tabs of `priced_tabs` and the combined lump sum, so the Combo proposal reads the keys it always has. The proof is a
pairing of the Polish and Epoxy workbook runs in the oracle, added the way the live proposal adds them
(`tests/js/combo-v2-proof-harness.js`).

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
| leaf (data) | `js/work-types.js` | Exists since Phase 7. The one vocabulary: job types (polish, epoxy, combo, gyp) and tabs (polish, epoxy, gyp, seal, leveling; seal and leveling are option-only). For each: label, which tabs a job type prices (combo is Epoxy plus Polish), workbook tab ids, role, quantity fields and snapshot keys, proposal template keys, whether it is ready. Also the one job-conditions table. | nothing |
| leaf (data) | `js/bid-profiles.js` | Part one (Phase 6): the cell maps of the eleven priced tabs. Part two (Phase 8): one profile per kind of tab as plain data, with rates and GP ladders as Markups formula text, a closed set of quirk flags and an `extends` link (Seal is Polish plus one ladder). The one home of the global defaults: labor rate, lodging, per diem, fees, sales tax, bond and the two remodel rates. `builtinRules()` is what the Markups page shows as built-ins. | nothing |
| model | `js/bid-model.js` (Phase 5 renamed it from `js/polish-bid-core.js`, with no logic change) | The saved estimate: fresh, migrate, seed a new bid, labor, travel, distance, conditions per section; building the save patch; composing the price snapshot the proposal reads. Since Phase 8 `markupChain` is a wrapper over the engine on `polish-legacy`, and `RATES` and `GP_BANDS` are read off the profile. | excel-math, work-types and bid-engine |
| engine | `js/bid-engine.js` (Phase 8) | `priceChain(profile, input, rates)`: the markup chain for any profile. `resolveProfile`, `forTab`, `compileRates` and `ruleNumber` turn the filed Markups rules into numbers or into an unpriceable line with a reason. `combine` adds the tabs of a combo job after each tab has had its own gross profit. `snapshotRates` and `ratesOf` (Phase 10) say what rates a section keeps when it is first used. | excel-math, bid-profiles, markup-core |
| takeoff | `js/epoxy-takeoff.js` (Phase 12) | What the Epoxy tab does before its chain that a library row cannot say: the patch, the cove (two ROUNDUPs deep, aggregate following System 1) and the tooling. The formulas are code; the prices they read are editable library rows (`PRICE_ROWS`) with a constant as the fallback, and a test holds each constant equal to the row the seed plans. | excel-math, library-core |
| takeoff | `js/gyp-takeoff.js` (Phase 14) | What the five Gyp tabs do before their chain that a library row cannot say: the three areas (soft, hard, corridor) and a bag's yield by thickness and mix (fractional bags, never rounded up: odd rule 7), the primer, ISO strip and tape bought from the areas, the sand worked out from the fractional bags, the sound mat in whole rolls with the truckload that waives its shipping (odd rule 6), the tooling, and the five presets (the five Gyp tabs: bag, primer, ISO strip, sound mat catalogue, default thickness, truckload). Same contract as the Epoxy takeoff: formulas are code, prices are editable library rows with a fallback pinned to the template cell. | excel-math, library-core |
| takeoff | `js/seal-takeoff.js` (Phase 15) | What the two Seal tabs do before their chain that a library row cannot say: the patch (a price a square foot of the whole area, always charged, at the new-concrete price or the renovation price by the job's Renovation answer, `Seal!C17`), the tooling ($0.27 a square foot with a $150 floor, rounded up, `Seal!D51`) and the default takeoff a new option opens with (`wb-seal-2-coats`, or `wb-seal-jnts-2-coats` for Seal (+Jnts)). The sealer and the joint filler kit are ordinary library materials. Same contract as the other takeoffs: formulas are code, prices are editable library rows with a fallback pinned to the template cell. | excel-math, library-core |
| render | `js/intake-scope.js` | Draws and shows the quantity fields of the intake from `work-types.js`. Extracted from `js/index.js` in Phase 9a; the live intake calls it (`renderSystems`, `applyScope`) and holds no copy. | work-types |

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

`js/bid-model.js` carries this header with three dependencies, `excel-math.js`, `work-types.js` (Phase 7) and
`bid-engine.js` (Phase 8), checked in that order, each with its own error that names the file. `js/bid-engine.js`
carries it with three more, `excel-math.js`, `bid-profiles.js` and `markup-core.js`. Every page that loads
`bid-model.js` therefore loads `markup-core.js`, `bid-profiles.js` and `bid-engine.js` ahead of it, and
`markup.html` loads `bid-profiles.js` ahead of `markup.js`, which reads `window.TWBidProfiles` as it loads. A page that reads
`window.TWWorkTypes` itself as it parses (`js/library.js`, `js/polish-intake.js`, `js/polish-estimate.js`,
`js/polish-sandbox.js`) has no header to read, so `test_work_types.py` finds those scripts and checks that
every page which loads one loads the vocabulary first, and `library.js` and `polish-sandbox.js` throw a
named error of their own if it is missing.

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

- `backend/tests/fixtures/polish_chain_golden.json`: 2,247 vectors over the Polish maths. The whole bid (every gross-profit edge from a dollar either side, all 256 settings of the eight job conditions, every shape the remodel rate arrives in, dirty values like `"12,500"` and `"$1,200"`), the number helpers, labor and travel, the takeoff, the conditions and what they write into the workbook, the model, the labor calculator, what a new bid is started with, the exported data (`RATES`, `GP_BANDS`, `CONDITION_CELLS`), and the type of every name the module exports today. A name that goes missing or changes type fails. A new export does not, because adding a helper is not a pricing change.
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
  `oracle-engine-harness.js` lifts the page's `HF.init`, its alias rule, its named-expression block and
  `HF.loadSheet` out of `estimate-review.js` and runs them, and `engine.build()` beside them, against recording
  stand-ins for HyperFormula on one small fixture. `test_workbook_oracle.py` requires every call each of them
  made, in order, to be equal, reads the page's boot order (sheets, then names, then cells) from its source, and
  shows the comparison go red for each of the ten one-line changes listed in `LOAD_BREAKS` (each made to a scratch
  copy of the page or of `engine.js`). What it
  does not cover is the page's edit door, `HF.setCellValue`, which the oracle goes round on purpose (it records
  what the sheet does when Hard Bid? says Yes). HyperFormula is not a dependency of the repo (no
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
  formula or constant) of the priced tabs and of every defined name in the workbook says "re-run the oracle"
  when Kyle changes a formula, a number or what a name points at (a formula that uses `Silica` keeps the same
  text when Silica is redefined), and does not fire when the file is merely re-saved, its names come out in
  another order, or an unpriced tab is edited. The page's pinned HyperFormula and the rounding plugin are held
  to the recorded ones the same way. `meta.json` also records, under `integrity`, a sha256 of every recorded
  sheet file and of the cell-map data in `bid-profiles.js` the answers came from (`oracle-integrity.js` is the
  one place that says which fields are hashed and how), and CI recomputes them: a
  recorded value edited by hand is caught even when it still adds up (gp and total both raised by 1,000 satisfy
  every arithmetic check and fail the hash). A reworded comment in `bid-profiles.js` does not move the hash;
  a changed cell or rate does. The recorded cases are checked to straddle every edge on the right side, to add
  up the way the sheet's total does, and to hold every kind of case. Where HyperFormula is installed, one more
  test recomputes everything and requires the recorded files byte for byte. What the hashes cannot do is stop
  someone who edits a file and its hash together; the diff of `meta.json` is where that shows, and so is the
  recompute test on any machine that has HyperFormula.
- *Regenerating.* `node backend/tests/js/workbook-oracle.js --write`, then read the fixture diff: one case is
  one line, and the hashes in `meta.json` are rewritten by the same run. A run with no flag compares and exits
  non-zero on any difference.
- *First user: Polish.* `oracle-polish-harness.js` runs today's model on every Polish case and requires it to
  equal the sheet except for the declared departures in `fixtures/oracle/departures.json` (no tooling line,
  a narrower remodel tax base, lodging counted in people-days, no hard bid, no bond). Two are predicted to the
  dollar from the model plus exactly what their reason says; all are seen on at least one case; a model change
  that closes one turns the test red until the list says so. Phase 17 closes three of them for new bids (the
  tooling line, the remodel tax base and lodging by labor hours). The hard bid and the bond are decisions and
  not gaps: Hanz removed hard bids on purpose (2026-09-22, and the Hard Bid? switch held at No since
  2026-10-03) and the bond is 0 by design, so neither is to be fixed.
- *Kyle's odd rules.* `docs/kyle-workbook-odd-rules.md` lists the eleven places the sheet does something
  surprising (the bond counts the taxes twice, Leveling lodging divides by 8 on 10 hour days, and so on). v2
  reproduces them on purpose. `test_kyle_odd_rules.py` ties each to its cells, to recorded evidence and to the
  figures the document quotes, and runs each check on falsified evidence to prove it can fail.

**The bid engine's proof (Phase 8).** `backend/tests/test_bid_engine.py` runs `tests/js/bid-engine-harness.js`, which
prices every recorded oracle case with the profile of its tab: 1,993 chain and lodging cases over the eleven priced
tabs, and every answer the two share is equal to the dollar (Seal (+Jnts) reads its remodel rate from Seal, which the
oracle's cases never set, so those cases are handed the rate the sheet read; the harness says so where it does it).
The profile `polish-legacy` is the one with departures, and it is held to them differently: its answers are set
beside the sheet's own `polish` profile case by case, and every difference has to be one that `departures.json`
declares for that case, and every declared departure has to be seen. Four more things make "equal" mean something.
Every one of the thirteen quirk flags is turned the other way on every tab, and answers go red somewhere (all but
`dayHours`, which the chain never reads and which is pinned to each tab's own "8 hour days" cell instead). Seven of
the eleven odd rules live in the chain and each is shown on recorded cases where the ordinary reading would have
charged something else; the other four are before the chain and the test says why. Every rate, ladder, tier
table, hard bid and the Gyp soft cost expression is evaluated beside the workbook's own cell formula over every edge
of that formula, one either side, and the two agree. And the oracle's own probes at the chain's boundary (the sound
mat at a truckload minus one, at it and over it; Leveling's lodging nights with the day length changed) are answered
by the engine as the sheet answers them. `bid-engine-units-harness.js` is the engine's own behaviour: `extends`,
reading a filed rule, what is unpriceable, combining tabs, every call that must throw, and bad profile data
refused. The last section of the test file breaks twenty-five lines of a scratch copy of the engine or the
profiles and requires the same checks to go red by name. The cell maps of part one are untouched, so the oracle's
integrity hash did not move and no answer was recorded again. `backend/tests/test_polish_chain_golden.py` is unchanged
apart from where two of its breakages now land (the GP band in `bid-profiles.js`, the Missouri zero in
`bid-engine.js`), and the chain golden file has no diff.

**The vocabulary tests (Phase 7).** `backend/tests/test_work_types.py`, with `tests/js/work-types-harness.js`,
runs the real `js/work-types.js` and the real `js/bid-model.js` that derives from it, and the copies the table
has to stay equal to, lifted out of the page files and evaluated: the live intake's `CONDITIONS`
(`js/index.js`), `scopesFor` and `systemFieldNames` out of `js/intake-scope.js`, and the estimate screen's sheet map, role map,
area cells and role sets (`js/estimate-review.js`). The cells are read back out of Kyle's template (each is a
literal there, or one of the two Renovation cells and blank). Its last section breaks one line of the module or
of the model in a scratch copy, runs the harness against it, and requires the named check to fail, and a test
requires every check to be in that table. `backend/tests/test_work_types_python_pin.py` is the one test that
runs node and holds the Python lists to the table (7.2). The page harnesses were moved onto the real module
(`polish-intake-harness.js`, `polish-estimate-harness.js`, `library-ui-harness.js`, `tab-memo-harness.js`,
`v2-routing-harness.js`, `v2-names-harness.js`), and `test_polish_intake_page.py` gained a check that does not
read any list: it prices one job with each of the questions the v2 intake asks answered both ways, so a key
the table misspells for everyone still shows up as a toggle that moves nothing.

Phase 7 re-cut the chain golden and 48 of its 2,228 vectors moved: `const/CONDITION_CELLS` (Taxable is four
cells) and the 47 `cond/cells/*` and `cond/library/*` vectors, each of which gains the same five cells
(Leveling!B6, the two Gyp B8 cells, Epoxy!B10 and Polish!B10) and nothing else. No `chain/*` vector moved, so no
price did, and the library golden and the saved-bid ratchet's totals are as they were. Phase 7 said of this that
a save of an existing v2 estimate "gains exactly those five cells and loses or changes none". That was true of a
draft that is not split, and false of two other kinds, which Phase 7b (next) fixed. What is true now is below.

**The split rule and the condition read-back (Phase 7b).** Review of Phase 7 found two ways a v2 save changed a
cell it should have left alone.

1. *A draft the estimate screen has split per sheet.* The first time the estimate screen opens a draft it gives
   every flag-block sheet its own Taxable and Remodel answer and marks the draft `tax_flags_per_sheet` (Hanz,
   2026-09-30, "Stay independent": an option follows its own sheet's answer and never the base's). The live
   intake respected that, through `splitFlagCells`: the two tax switches become the base bid's own cell and no
   other sheet's is restated. The v2 save did not. It wrote the job's answer to all four Taxable cells, so
   `Leveling!B6`, `Gyp (USG 1-8")!B8` and `Gyp (FR)!B8` took the base's answer over their own, and it read the
   job's answer off `Epoxy!B6`, which on a polish job is not the base sheet. A v2 test copy made it worse: the
   copy dropped the `tax_flags_per_sheet` mark, so a split project arrived looking unsplit.
2. *A condition with several cells.* The read-back took the first cell only. Renovation is two cells
   (`Epoxy!B10`, `Polish!B10`), so a "Reno" in `Polish!B10` with `Epoxy!B10` blank read as nothing and the next
   save wrote "New" into both. Local (two cells) and Taxable (four) had the same read.

Now: the rule is in `js/work-types.js`. Taxable and Remodel tax carry `perSheet` (the cell on the base sheet of
each tab a job can be priced on, the same addresses as `FLAG_BLOCK_CELLS` in `backend/estimate_writer.py`), and
`writeCellsFor(condition, jobType, split, own)` answers which cells an answer is written to and read from: all of
the condition's `cells` when the draft is not split, the base sheets' own cell when it is. `isSplit(draft)`,
`isPerSheet(condition)` and `baseSheets(jobType)` are its helpers. Two callers use it and nothing else decides:
the live intake's `splitFlagCells` (which adds only the estimate screen's own snapshot of each tab's cells, and
its job-type ladder is gone), and the model's `conditionCellWrites` and `conditionsFromCells` (each takes `split`;
`buildSavePatch` reads it off the draft). The v2 intake and the Takeoff step pass `isSplit(state)`, and
`polish-intake.js` no longer carries a read-back loop of its own. A test copy keeps `tax_flags_per_sheet` and the
base sheets' own tax cells (`copyableCells` includes them), so a copy of a split project arrives split with its
answers. A condition with several cells is read back from the first cell that holds an answer.

So a save of an existing v2 estimate on a draft that is not split gains the five cells above and changes no other.
On a split draft it writes the base sheet's own Taxable and Remodel cell (`Polish!B6`, `Polish!D6` for a polish job)
and leaves every other sheet's tax cell as the draft has it. On any draft a "Reno" in either B10 cell survives. No
`chain/*` vector moved, so no price did. The chain golden changed on purpose: one vector was renamed and its
answer moved (`cond/fromCells/polishB4IsNotRead` became `cond/fromCells/polishB4IsReadWhenEpoxyB4IsBlank`, with the
answer the other way) and nineteen were added, 2,228 vectors to 2,247. `backend/tests/test_v2_condition_cells.py` pins all of it, executes it through
the real Takeoff step and the real v2 intake as well as the modules, and scans every priced sheet of Kyle's
template for its own literal flag cells (Local, Taxable, Prevailing wage, Remodel tax, New or Reno). Each must be
written by the table or sit on a list of known gaps that names the phase that will close it: the Seal ones
(Phase 15, closed: Local writes Seal!B4 and Renovation writes Seal!B10), the Leveling ones (Phase 16) and the Gyp Local and New or Reno ones (Phase 14). The live intake does
not write those either, and a new literal flag cell that is on neither list fails the test.

**The Epoxy proof (Phase 12).** `tests/js/epoxy-jobs-recorder.js` types 440 jobs into the Epoxy tab of the template (a
system for System 1 and for System 2, a primer, a cove and its length, the job questions, a crew) in the same engine the
oracle uses, and records what its cells answer (`tests/fixtures/epoxy_jobs_golden.json`, guarded by a hash of the Epoxy tab
and of every defined name, so a template edit says "re-run the recorder"). `tests/js/epoxy-v2-proof-harness.js` builds each
job as a v2 Epoxy section over the library the seed script plans and prices it the way the estimate page does, and
`tests/test_epoxy_v2_proof.py` requires material before D40, D40, tooling, sub-total, gross profit, taxes and total to equal
the workbook's, to the dollar, for every job outside the declared departures, and requires every declared departure to
really differ. The same harness prices every Epoxy vector of the workbook oracle through a v2 section (105 of the 185; the
other 80 are the hard bid, the bond and the lodging cases that v2 does not carry) and every figure equals the oracle's.
`tests/test_epoxy_takeoff.py` holds each constant in `js/epoxy-takeoff.js` to the cell of the template it was copied from and
each price fallback to the row the seed plans. `tests/test_epoxy_estimate_page.py` boots the real estimate page on an Epoxy
job and sets the price it shows beside the same job priced with no page in it. `tests/test_seed_library.py` runs the seed's
statements against a database and shows that a row somebody edited is still as they left it.

## 7. Every concept, where it is copied today, and what happens to each copy

Line numbers are on `origin/staging` at `3f94ed2`, except those in `js/bid-model.js` and
`js/excel-math.js`, which are on the Phase 5 change, and those Phase 7 wrote (see the top). "Planned" means the phase in the program plan,
not something that has been done. The summary first, then the evidence for each row.

| | Concept | Copies today | Disposition | Phase |
|---|---|---|---|---|
| 7.1 | Work-type list, JavaScript | 9 places in 7 files | Done in Phase 7: `js/library.js` reads `js/work-types.js` (`WORK_TYPES`, `appliesToWorkType`), and so does the model's default scoping. Left: the live intake's map (held equal by a test until Phase 9) and the estimate and proposal screens' lists | 7 (in part), 9 |
| 7.2 | Work-type list, Python | 7 files | Done: pinned to `js/work-types.js` by `test_work_types_python_pin.py`, which runs node | 7 (done) |
| 7.3 | Job-condition tables | 10 places | Done in Phase 7: one conditions table in `js/work-types.js`, and the model's `CONDITION_CELLS` and fresh conditions, v2's intake `CONDITIONS`, the Takeoff `CONDITION_CARDS`, the Defaults tab's list and the test copy's `COPYABLE_CELLS` read it. The Taxable cells are right by construction. Which cells the two tax switches write on a split draft is the table's too since Phase 7b (`perSheet` and `writeCellsFor`), for the live intake and for a v2 save. Left: the live intake's `CONDITIONS` (held equal by a test until Phase 9) and the estimate screen's per-sheet tax addresses (`JOB_FLAG_ADDR`) | 7 (in part), 7b, 9 |
| 7.4 | Built-in markup rates | 4 places (was) | Done in Phase 8: one home, the profiles and `defaults` in `js/bid-profiles.js`. `bid-model.js` and `markup.js` read it, so there is no pinned pair. Left: `pricing.py` and the docstring audit in `markup.py`, which Phase 17 retires | 8 (done), 17 |
| 7.5 | ROUNDUP | 3 implementations (the leaf, `markup-core.js`, `pricing.py`), the workbook engine's plugin, 2 guards | Done: the model's copy is the leaf's `roundUp`, with a row in the parity test. `excelRoundUp`, the pack CEIL and `_roundup` stay, held equal by tests | 5 (done), 8, 17 |
| 7.6 | Intake scope maps | 4 places | Done in Phase 9a: the quantity fields and their snapshot keys live in `js/work-types.js`, and `js/intake-scope.js` draws and shows them, one source. The live intake delegates (its `SCOPE_BY_WORK_TYPE` and `systemFieldNames` are deleted), proven byte for byte against golden captures. Left: the estimate screen's area keys, held equal to the table by tests | 7 (done), 9a (done) |
| 7.7 | Role sets | 4 sets in 3 files | Each tab carries its `role` and `optionOnly` in `js/work-types.js` (done). The sets are not yet computed from it: one difference is pinned (Leveling), see 7.7 | 7 (in part) |
| 7.8 | Job type to tab | 4 places | Each job type lists its tabs in `js/work-types.js` and the model reads them through `tabsFor` (done). The intake's and the two screens' copies stay | 7 (in part) |
| 7.9 | The v2 intake's county picker | 1 copy, about 295 lines (was) | Done in Phase 9b: the v2 intake mounts `js/county-picker.js` and its copy is deleted. A golden captured from the old copy pins every row, key, note and rate | 9b (done) |
| 7.10 | The estimate page's two save blobs | 1 composition (was 2) | Done: one `buildSavePatch` used by both, and the intake's merge is one `patchModel` | 4 (done) |
| 7.11 | "Is this draft a v2 estimate" | 2 places, in two languages | Held equal by one test over one table. The JavaScript one stays in `js/shared.js` (Phase 5 left it there, see 7.11) | 2 (added) |
| 7.13 | A bid made of sheets: copy, add, rename, delete, the base | 0 (new) | Done in Sheets phase 1, in the model only: one home, `js/bid-model.js`. Nothing is copied from the live estimate's `copyTab`, `renameTab`, `deleteTab` and base pickers; the live ones stay the spreadsheet's own | Sheets 1 |

### 7.1 The work-type list, in JavaScript

| Copy | What it is |
|---|---|
| `js/intake-scope.js` | Was `SCOPE_BY_WORK_TYPE` in `js/index.js`: now `scopesFor`, read off the table (Phase 9a) |
| `js/index.js:147-199` | A `scope: [...]` list of work types on each of the nine intake conditions |
| `js/library.js:2988` | `WORK_TYPES`: polish, seal, epoxy, leveling, gyp (the tab list, not the job types). Replaced in Phase 7: it is the table's `tabKeys()` now, and `appliesToWorkType` is a wrapper over `appliesTo` (`js/library.js:3000`) |
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

**Done (Phase 7).** The vocabulary exists and `js/library.js` reads it: `WORK_TYPES` is `tabKeys()` and
`appliesToWorkType` is a wrapper over `appliesTo`, which also fixes the model's own scoping (a combo job
reads the Epoxy and the Polish defaults, and a job type handed to `appliesTo` throws, where it used to be
answered "no" quietly). **Left where they are, and why.** The `scope` lists in `js/index.js` stay until Phase 9 moves the
conditions of the live intake; until then `test_work_types.py` executes them and requires them equal to
the table, so a second home cannot drift unseen. (`SCOPE_BY_WORK_TYPE` moved in Phase 9a: `applyScope` in
`js/intake-scope.js` reads the table.) `BASE_ROLE` in `js/estimate-review.js` stays and is held equal to the table's roles by the same
test. `effectiveWorkType` and the default narrative in `js/proposal-review.js`, the phrase in
`js/price-lines-core.js` and the letter kinds in `js/coverletter-editor.js` stay: they belong to the
spreadsheet's proposal path, which this phase does not touch, and each is a sentence or a document chosen
by work type, which the table does not hold yet. `js/polish-intake.js` still writes `work_type: "polish"`
and nothing else, until Phase 9.

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

**Done (Phase 7).** `test_work_types_python_pin.py` is that test. It compares `markup.TABS`,
`library.WORK_TYPES`, `leads._WORK_TYPES` and `leads._QUANTITY_KEYS`, the key sets of both
`TEMPLATE_PICKER` tables (the proposal one also holds the two documents that are no job type, a sealer
proposal and a budget sheet, named in the test), `info_sheet_writer`'s `_SF_KEYS`, `_LF_KEYS` and
`_COVE_ROLES`, `condition_defaults.KEYS`, `library.RESERVED_ITEM_IDS` and `detect_work_type` against the
table, and each check is shown to fail when its list drifts. Left: the option price phrase by work type in
`backend/main.py`, which is a sentence and not a list of work types.

### 7.3 The job-condition tables

| Copy | What it holds |
|---|---|
| `js/index.js:146-202` | `CONDITIONS` on the live intake: key, label, scope, default, the cells it writes, the on and off words, `needs`. Nine rows. Taxable writes four cells (Epoxy, Leveling and two Gyp tabs) |
| `js/polish-intake.js:77` | `CONDITIONS` on the v2 intake: four rows (prevailing wage, taxable, remodel tax, bond), keys only. Replaced in Phase 7: it is the table's rows that the v2 intake asks |
| `js/bid-model.js:1479` | `CONDITION_CELLS`: seven rows with the cells they write. Taxable writes only `Epoxy!B6`. Replaced in Phase 7: it is the table cut for polish, so Taxable writes four cells, and `CARRIED_CELLS` (`js/bid-model.js:1491`) carries the one condition the model has no answer for (Renovation) |
| `js/bid-model.js:1783` | The conditions of a fresh model, eight keys including `bond`. Replaced in Phase 7: `modelDefaults()` of the table |
| `js/polish-estimate.js:857-920` | `CONDITION_CARDS`: the Takeoff step's three cards (dye, joint filler, remove existing). Replaced in Phase 7: which cards, their order, cell, library row and dependency are the table's, and `CARD_VIEWS` keeps what each card says |
| `js/library.js:2608-2671` | The Defaults tab's condition list, and `backend/condition_defaults.py:61` (`KEYS`). Replaced in Phase 7: the list is the table's (`takeoffConditionDefaults`), and `KEYS` is pinned to it by `test_work_types_python_pin.py` |
| `js/estimate-review.js:4032-4077` | `JOB_FLAG_ADDR`, `JOB_FLAG_LITERAL_LAYOUTS`, `JOB_FLAG_LAYOUTS`, `JOB_FLAG_TEMPLATE`: where the tax answers sit on each sheet layout |
| `backend/estimate_writer.py:394-406` | `POLISH_CELL_MAP` and its Epoxy sibling: key to cell letter |
| `js/polish-sandbox.js:269` | `COPYABLE_CELLS`: the live intake's fourteen condition cells again. A v2 test copy keeps these from its source (and no other cell), so it opens with the job's answers. Added in Phase 2 and held equal to the intake's table by `test_v2_routing_guard.py`, which lifts `CONDITIONS` out of `index.js` and compares Replaced in Phase 7: `copyableCells()` of the table. Phase 7b added the three base-sheet tax cells a split draft holds (`Polish!B6`, `Polish!D6`, `Gyp (USG 1-8")!D8`), so the list is those fourteen and three more, and a copy of a split project keeps its answers |

**Problem.** The two Taxable tables disagree today: the live intake writes four cells and the v2 model
writes one, so a v2 bid never writes the Leveling or Gyp Taxable cell. The intake's comment records
the same fact kept in step by hand: "two copies of one fact is what this repo keeps paying for".
**Planned (Phase 7):** one table in `js/work-types.js` with key, label, why, default, scope, the cells
per tab, on and off words, `needs` and where it is asked. The live intake, the v2 intake, the Takeoff
cards, the Defaults tab and the test copy read it. The Taxable cells are right by construction because they come
from the same row. The per-layout addresses in `estimate-review.js` are checked against the workbook
by the test that already re-reads it (`test_taxable_flag_reaches_every_sheet.py`).

**Done (Phase 7).** The table is `CONDITIONS` in `js/work-types.js`, and the rows marked replaced above read
it. Taxable is four cells in it, so v2 writes the Leveling and Gyp Taxable cells by construction. Two
things the table says that the old copies did not: a condition the v2 model does not carry (Renovation,
asked on the live intake alone) is still written, with its default while its cell is blank and otherwise
left as it is, and the three screens' orders and the v2 intake's one different sentence are data (`asked_on`
and `wording`). **Left, and why.** The live intake's `CONDITIONS` in `js/index.js` stays until Phase 9, and
`test_work_types.py` executes it and requires its nine rows equal to the table's rows asked on the live
screen. `JOB_FLAG_*` in `js/estimate-review.js` (where each sheet's tax answers sit, after the estimate
screen splits them) and `POLISH_CELL_MAP` in `backend/estimate_writer.py` (a key to a cell letter) stay: they
are the spreadsheet's own, and `test_taxable_flag_reaches_every_sheet.py` re-reads the workbook for them.

### 7.4 The built-in markup rates

| Copy | What it holds |
|---|---|
| `js/bid-profiles.js` (the home since Phase 8) | `defaults` (labor rate 33, lodging 70, per diem 45, fees, bond, sales tax 9.475%, the sheet's 10% and the Kansas 6.5% remodel rates) and `profiles`: every rate as Markups formula text, with the GP ladders (five rungs on Polish, Epoxy and Leveling, six on Seal, seven on Gyp) and Gyp's soft costs expression |
| `js/bid-model.js` `RATES` and `GP_BANDS` | Read off the `polish-legacy` profile and `defaults` as it loads (`engine.rateNumber`, `engine.bandsOf`), and exported under the names they always had. The shipped labor, lodging and per diem figures are read the same way |
| `js/markup.js` `BUILTIN` | `builtinRules()` of the profiles. `GP_5_BANDS` and `GYP_SOFT_COSTS` are gone from it, and Seal's and Gyp's GP now show their ladders where they used to show an empty box |
| `backend/pricing.py` `_gp_pct` and `compute_full_bid` | Left. The same ladder and the defaults of `compute_full_bid` (33, 12%, 70, 45, 3%, 13%, 9.475%, a 10% remodel). Retired in Phase 17 |
| `backend/markup.py` docstring | Left. The same rates, written as an audit of the workbook |

**Problem, as it was.** `markup.js` said its numbers were transcribed from `bid-model.js` and from
`markup.py`'s audit of the workbook, "and from nowhere else", and a test (`test_markup_page.py` with
`markup-rate-harness.js`) kept the pair equal, which is a pinned pair and not one value. Seal's and Gyp's GP
ladders were "not on record", so those two cells rendered an empty rate box. `pricing.py` only serves
`/api/price` (`backend/main.py:3725`), which nothing in the frontend calls, and the program plan records it as wrong
on whipped-resin cove and on quartz and flake price breaks.

**Done (Phase 8).** The rates moved into `js/bid-profiles.js` as formula text and the engine reads them, so a
rate built in and a rate filed on the Markups page are the same kind of thing. `bid-model.js` and `markup.js` read
the profiles and there is no pair to keep equal. Seal's sixth rung (42,500) and Gyp's seven tiers were taken from
the workbook's formula text, and `test_bid_engine.py` evaluates each profile ladder beside the cell formula over
every edge, one either side. The Markups page now shows them as built-ins, and a filed ladder still overrides them.
`markup-rate-harness.js` lifts the one line of `markup.js` that reads the profiles and runs it with the real module,
and the Markups page tests carry `bid-profiles.js` into every scratch copy. **Left on purpose:** `pricing.py` and
`/api/price`, until Phase 17, and the `markup.py` docstring.

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

**Done (Phase 7).** `FIELDS` in `js/work-types.js` is the nine quantity fields in the live intake's order, each
with its scope token, its unit, its system and the key the estimate screen files it under (`snapshot`, or
null where the sheet has no cell: a second polish system), and each job type and tab says which of them it
uses. The python keys are pinned (7.2). `test_work_types.py` executes `scopesFor` and
`systemFieldNames` out of `js/intake-scope.js` and `AREA_SF_CELLS` and `GYP_SF_CELLS` out of `js/estimate-review.js`
and requires each equal to what the table derives, so the three copies cannot drift while they stay.
**Done (Phase 9a).** The renderer is `js/intake-scope.js`: `renderSystems` draws the system blocks,
`applyScope` shows what a job type asks for and hides the rest, and both take the job type from the caller
(none is a throw). The live intake delegates in the same change and its old code is deleted.
`test_intake_scope_module.py` runs the real page against `tests/fixtures/intake_scope_golden.json`, captured
from the unchanged code, for every job type and both audiences. **Left:** the estimate cell each quantity
lands in, which is the spreadsheet's.

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

**Done in part (Phase 7).** Each tab carries its `role` and `optionOnly`, and a combo job's two tabs are the
combined base roles. The two screens' sets are NOT computed from them yet, on purpose, because the table and
the spreadsheet disagree about one tab: the table says Leveling is an option-only tab with the role
`leveling`, and `js/estimate-review.js` gives Leveling and Epoxy blank the role `other`, which is why
`OPTION_ONLY_ROLES` there is only seal. Computing the set from the table would change what the spreadsheet
does with a Leveling tab, and that is its own change. `test_work_types.py` holds the rest equal (every
sheet the spreadsheet gives a role agrees with the table, `PRICED_ROLES` and `COMBINED_BASE_ROLES` match)
and pins the one difference, so closing it or widening it has to be done on purpose. `_COVE_ROLES` is
pinned to the table by the Python test (7.2).

### 7.8 Job type to tab

| Copy | What it is |
|---|---|
| `js/index.js:303-305` | Job type to the tabs the split tax flags go to. Gone in Phase 7b: it reads `baseSheets` of the table |
| `js/estimate-review.js:4336-4342` | `baseFlagSheets`: Polish to `["Polish"]`, combo to Epoxy and Polish, else Epoxy |
| `js/estimate-review.js:5203-5208` | `_areaBaseIds`: the tabs the proposal's area line is read from |
| `js/proposal-review.js:1140-1144` | The same, with fewer branches |

**Planned (Phase 7):** each job type in `js/work-types.js` lists its tabs (combo is Epoxy plus Polish),
and `appliesTo(defaultWorkTypes, layout)` answers "does this default apply to this tab". It throws when
asked about "combo", because a combo job has no tab of its own and a rate filed under that name could
never be read (the Markups page already refuses it by name).

**Done in part (Phase 7).** Each job type lists its tabs, `tabsFor` returns them and refuses anything that is
not a job type, and the model's `workTypeApplies` and the default takeoff read them (that is the combo fix
in 7.1). **Done in Phase 7b:** the live intake's tab list for the split tax flags is `baseSheets(jobType)`
of the table, the sheet each of a job type's tabs is priced on. **Left:** the screens' `baseFlagSheets` and
`_areaBaseIds` stay, because they are the spreadsheet path's.

### 7.9 The v2 intake's own county picker

| Copy | What it is |
|---|---|
| `js/county-picker.js` | The one control. The live intake and the v2 intake both mount it |

**Done in Phase 9b.** The v2 intake used to carry about 295 lines of its own (`loadCounties`, `filterCounties`,
`renderCountyResults`, keyboard handling, `pickCounty`, `clearCounty`, the note under the box and `hydrateCounty`).
They are deleted. The page now holds three small functions that are its own: `mountCounty`, `renderCountyNote` and
`countyKeys`. `backend/tests/fixtures/county_picker_golden.json` was captured from the old copy before it went: for
a sample of searches, every row the box offers and, for each row, the four keys a click writes (`county`,
`county_tax_rate`, `county_remodel_rate`, `county_notes`), the note with Remodel tax off and on, and what the real
engine charges. The shared control must reproduce all of it.

The same change gave the v2 intake a Job type choice. It is drawn from `js/work-types.js` by `js/intake-scope.js`
(`jobTypesMarkup`), so there is no list of job types on the page. Polish was the only type `ready` when this was
written; Epoxy, Combo and Gyp were shown and disabled with a plain note, and a later phase enables one by setting
`ready` in the vocabulary (Phase 12 did that for Epoxy, Phase 13 for Combo and Phase 14 for Gyp: every type is ready, so
nothing is disabled and there is no note, and a draft whose job type is Epoxy, Combo or Gyp opens as that bid; the greyed
out choice and its note are kept for the next type that waits, and tested on a vocabulary that marks Gyp not ready). The
quantity fields on the page are drawn by the same renderer as the live intake, and a Gyp job also shows the live intake's
gypsum box (soft, hard and corridor SF).

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

**Done (Phase 10): a bid priced on several workbook tabs.** The data model is the program plan's, unchanged on disk
for every saved bid. `polish_estimate` stays at `version: 2`; the root keys keep their meaning (the job-level keys and
the Polish section); new `tabs: { <workbook tab id>: Section }` holds every other section, where a section is
`{ layout, kind: base | option | off, profile: "<id>@<rev>", takeoff, labor, contingency, fees, rates, totals }`.
The job-level keys (`conditions`, `conditions_shown`, `cond_cov`, `travel`, `distance`, `fees_default`,
`no_travel_labor`) stay at the root and are shared. What is in `js/bid-model.js` and `js/bid-engine.js`:

| Piece | What it does |
|---|---|
| `sectionsOf(model)` | The one place that knows the root from `tabs`. Every section, root first and then the sections under `tabs` in the order each one's `seq` gives (see below), by reference. Refuses a section with no layout, a wrong layout for its tab, a kind or profile stamp that is not one, or a profile of another layout. No default layout, "polish" included. `activeSections` leaves out `kind: "off"` (an Epoxy-only job holds an off Polish section). |
| `priceSection`, `priceTabs` | One section's bid through the engine, with the profile it was SAVED with (the stamp) and the rates it kept. The page hands in `ctx.material` (the library is its). A rev that has moved, or an unknown profile, is unpriceable with the reason, never repriced. The job's travel and the fees default belong to one carrier section (the first base). |
| `activateSection` | The first use of a tab: a blank section, its profile stamped, and `snapshotRates` of the Markups rules filed at that moment kept as text. |
| `snapshotRates`, `ratesOf` (engine) | The snapshot is `{ version, profile, rates: { line: formula }, fees_default, notes }`. Filed rules are honoured and kept. A blank, unreadable or out-of-range rule is left out with a note and the built-in stands, never $0. A bond rule is not taken (bond is 0 and unwired until Kyle decides). |
| `isNewSection`, `seedNewSections`, `syncAutoGuys` | The estimate page's new-bid seeding, moved out of `init()`, per section and behind the same gates. The page collects what the library answered and makes one call. |
| `composePricingSnapshot` | The one pure composition of the derived keys the proposal side reads. `buildSavePatch` is its only caller, so the autosave and the `pagehide` flush write the same thing. |
| `sectionSwitcherHtml`, the page's strip | Drawn only when the bid has more than one section. |

**The order of the sheets is kept in the sheets, not in the keys (round 6).** `tabs` is an object and `drafts.data` is a jsonb
column, which keeps no key order: Postgres returns every object with its keys sorted by length in bytes and then by the bytes (so
"Copy1" sorts before `Gyp (USG 1-8")`, and a bid saved as [Gyp, Polish 2] came back as [Polish 2, Gyp]). The first base carries the job's
travel, so two bases under `tabs` could change carrier, crew, nights and price on a reload, and the sheet bar, the sheet a bid opens on
and the options the customer's document lists (`priced_tabs`, which a save writes in this order) went with it. Every section under
`tabs` now carries `seq`, its place in the bid: a number that only grows, so a new, copied or added sheet is last (`withSectionPut`;
`copySection` never takes its source's place) and a rename, a kind change, a Gyp preset moving the key or a delete beside it moves
nothing. `sectionsOf` lists the root and then the sections by `seq` (`tabIdsInOrder`). A bid saved before this has no `seq`: `adopt()`
stamps it in memory when it opens (`withSectionOrder`: nothing is written on open and no price moves) and every save carries the stamps.
It is stamped in the order its saved price was computed in, which is the order of its `priced_tabs` (an array, which jsonb keeps in order,
written in the same save as the model and the lump sum) when that names two or more of the sheets under `tabs`: the sheets it does not
name (an `off` one is never priced) go after them, in key order. A list that names fewer than two says nothing about the order, and the
bid is stamped in its keys' order. Without that, a far Combo with Epoxy and a Polish copy both bases, saved at $78,628, opened on the
copy as the carrier (it sorts first in jsonb) and its first save wrote $81,086 for good. A section with no place is newer than one that
has one, and a tie is settled by the sheet's id, never by key order. `tests/js/_jsonb.js` re-keys a reopened blob the way jsonb does, and the harnesses that reopen a saved
estimate (the travel walks, the round-5 harness, the estimate page harness's reopens and the sheet-order harness) go through it
(`tests/test_v2_sheet_order.py`, `tests/test_jsonb_key_order.py`, `tests/test_polish_travel_sequences_session.py`).

**How a saved bid is kept from repricing.** The live Markups rules are never read when a section is priced. A section
with no snapshot (every saved bid, and the Polish root always) prices at its profile's built-ins; a section
activated after a rule was filed keeps that rule as text and is not moved by a later edit. The data dump of
2026-10-12 had one production rule, `(polish, bond, '1%')`, and none the engine reads (bond is not taken, and a
polish-layout bond rule is not a line the engine reads: its home is Global). The root has no snapshot. Its `profile` key is read
since Phase 17 (Polish rev 2 for new bids) and only when it is exactly `polish-rev2@1`; `rates` and a `kind` of base
or option at the root are still reserved and not read, so no saved bid's total can move.

**What a save writes.** A bid with only the root section writes exactly what the page always wrote, in the same
order (`polish_estimate` with its totals stamped, `polish_sf`, `polish_2_sf`, `computed_bid`, then the condition
cells). `tests/fixtures/save_patch_golden.json` is that, byte for byte, cut from `28a5d1f` before this phase
changed a line, over every saved-bid fixture and seven new or part-saved bids, with the model each new bid holds
after `init()`. A bid with several sections also writes `priced_tabs` (every tab marked `v2: true`),
`proposal_lump_sum`, `proposal_sales_tax`, `proposal_remodel_tax`, `proposal_taxable`, `proposal_remodel_on`,
`sheet_area`, `cost_snapshot`, `phase_price` and a combined `computed_bid`. The lump sum is each BASE section's own
total summed after its own gross profit (`engine.combine`), never one pooled chain, and an option-only tab (Seal,
Leveling) is never in it. A section that cannot price takes the combined price with it: those keys are null, and the
tab lists the reason. **Phase 12 wrote the first second section** (Epoxy, below): the page's own panels edit it. A section
whose work type is not `ready` (Leveling) still shows the summary until its phase. `rooms` and
`base_tab_id` are not written (the Proposal step rebuilds rooms from `priced_tabs`).

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

### 7.12 Polish rev 2 (Phase 17)

**Problem, as it was.** The v2 Polish model differed from Kyle's Polish tab in five places (`departures.json`): no
tooling line (the tab's D55 is at least $150 and counts slurry hardener and plastic), a remodel tax base that left out
tooling and travel, lodging nights counted in people-days, no hard bid and no bond. Hanz decided on 2026-10-07 that the
fixes apply to NEW bids only and that a saved bid keeps its total, and on 2026-10-12 that a new bid's Lodging nights and
Per Diem days start empty and are typed. On 2026-10-20 he chose, for Travel Labor alone, that a job 70 miles or more from
the office fills the line by itself, and a scan of the estimate workbooks in Kyle's Dropbox (276 out-of-town jobs) set how:
the hours are one round trip at 60 mph to the half hour and the guys are the crew's size (the most guys on any labor line,
over both base sheets of a Combo), so each guy is charged one round trip, as Kyle types it on 9 of 10 out-of-town sheets.
A figure the estimator typed, or cleared, always wins; a switched-off row is left as it is; a bid saved before 2026-10-12
that is on the old man-days auto keeps them while it merely opens; and a saved bid never moves on open (`followDistanceHours`
in `js/bid-model.js`, held by `tests/test_polish_travel_hours.py`). An answer applied in a session puts every Travel Labor row
it FILLS on the crew's size, the older man-days auto row included (leaving it on the man-days charged 49.5 man-days x 6.5 x $33
= $10,617.75 for an Epoxy job switched to Polish, where Kyle types $858).

The job's drive is one trip, so ONE Travel Labor row is priced for it, on the section that carries the job's travel. EVERY time the
job restructures (the job type is switched in the session, or the Sheets panel makes another sheet the base) the page calls
`followDistance(model, fromTab)` (it names the old carrier in `fromTab`; left out, the stranded row is looked for), whether or not
the carrier moved, and the rows are settled in this order: the old carrier's row goes with the carrier when the new carrier has
none (Combo to Epoxy); what the estimator said on the old carrier's row (typed figures, a cleared box, a rate typed over the line's
default, a switch turned off) follows the job's drive to a new carrier whose own row nobody touched (the two rows change places,
so every section keeps its one row; if both are the estimator's both stay); a row nobody touched is filled by the rule, only when
the carrier moved (a Combo made Polish fills nothing); the guys follow the crew of the bid as it is now (a Combo made Polish saved
a price a plain reopen contradicted until they did); and then every Travel Labor row the distance filled and nobody touched, on
any section that is not the carrier and is not an option, off sections included, is emptied with its fill markers (Epoxy to Polish
to Combo priced the drive twice until off sections were included). The give-back comes after the guys because "a copy of the
carrier's row" is told by comparing them. A Gyp carrier is never filled, whatever row lands on it. A plain reopen is not a
restructure and moves nothing. A distance lookup that is still on its way lands on the whole model whatever section is on show or
whatever a Sheets action has replaced since. An option is priced apart: its Travel Labor row is its own, its guys follow its own labor
lines (`ownCrewSize`), and it follows every distance ANSWER (`followDistanceOptions`, called by `applyDistance` and `clearDistance`)
by the carrier's rule: a box nobody typed in takes the answer (an empty row too), what the estimator typed in or cleared and a row
switched off are left alone, and the fill is taken back whole when the job goes local or the miles are cleared (a Gyp option is left
alone, as a Gyp carrier is). Corrected to 50 miles, a far bid's copy no longer keeps pricing the 6.5 hour drive the base dropped, and
at 300 miles it moves to 10 hours with the base's. Held by `tests/test_polish_travel_switch.py` and `tests/test_polish_travel_hours.py`,
and over every sequence of switches (job types, the estimator's own say, the Sheets panel's base changes, the miles corrected after
any of them, a local job, no distance) by `tests/js/travel-sequence-harness.js` through `tests/test_polish_travel_sequences*.py`.

A base the Sheets panel DEMOTES keeps its Travel Labor row (the fifth audit, 2026-10-20): `moveTravelLabor` gives the new carrier a copy and leaves the old carrier,
an option now, the row it had, so the option prices its own drive from the moment of the pick and follows every later answer on its own crew. Before, the row MOVED, and the
demoted sheet priced no drive until the draft was reloaded (`migrateModel` then gives a root a blank row, which the next answer filled): far Polish 4 x 12, an Epoxy sheet added and
made the base, the miles typed as 300 and then 299, was $40,988 in the session and $41,771 after a reload. A pick followed by its undo no longer returns the model byte for byte (the
Epoxy option keeps the row it took as the base). The walk of the fifth audit judges the session against a reload after every Sheets action (`RELOAD_AGREES`,
`tests/test_polish_travel_sequences_reload*.py`), which no earlier walk could: each step of a walk starts from the draft the step before saved.

**Nights and per diem days fill on a far job (Hanz, 2026-10-20: "Fill them automatically").** Kyle's sheet counts them off the labor (Polish!B65 is
`=IF(Local="No", (labor$ - travel$)/rate/8)`, one night and one day of per diem for every man-day), and a far answer used to switch Lodging and Per Diem ON and leave their
quantities empty, by the 2026-10-12 rule that a new bid starts empty. Now a far answer (typed miles, the lookup, a carrier that moves under a far distance on file) fills a
quantity nobody has typed with the sheet's count of the carrier's labor (`followDistanceNights`, called by `applyDistance`, `clearDistance` and `followDistance`): the line goes on auto
and carries `qty_follow: "labor"`, `syncAutoGuys` keeps its figure current like the crew-following Travel guys, and it is charged what the price charges (`travelQty`: `sheetNights` on a
Polish section priced the sheet's way, the man-days on the others). Wichita, four guys for twelve days: 48 nights x $70 = $3,360 and 48 days x $45 = $2,160. TYPING IN THE BOX, OR CLEARING
IT, MAKES IT THEIRS (`markTravelQtyTyped`, `qty_typed`, saved with the line): no answer fills it again, and a figure sitting in a box that is off auto is theirs without the mark (a bid saved since
2026-10-12). Going local, or clearing the miles, takes a following figure back to empty and leaves a typed one (greyed while its line is off). A line on auto WITHOUT the marker, the older
bid's, is never converted in either direction, and a saved bid never moves on open. An OPTION is untouched: it charges its own nights for its own labor (`optionTravelCosts`). The Labor step
says it under each box (`travelQtyHint`), in the how-note (one sentence, "Nights and per diem days follow the man-days ..., Kyle's way"), and the Review's Hotel and Per Diem rows say it under
the line's name. Held by `tests/test_polish_travel_round5.py`, and by `NIGHTS`, judged after every step of every walk. The Travel Labor card's x can be undone: with no Travel Labor line on the
carrier the travel block draws an Add Travel Labor control (`addTravelLabor`: the row a new bid is seeded with, filled by the rule on a far job), and the summary no longer says Travel Labor
"comes on" over a job with no line.

**Done.**

| What | Where |
|---|---|
| The profile `polish-rev2@1`: `polish-legacy` with `toolingInSubTotal: true` and `remodelBase: "sheet"`. No new quirk, no new rate | `js/bid-profiles.js` |
| Who is priced by it: a root whose own `profile` key is exactly `polish-rev2@1`. Written once, when a new bid is seeded (the same gate as `pool_packs`) and when a Polish section that never held a takeoff is brought into a bid by a job type change. Never on a saved bid, never on an Epoxy-only bid's off root. Any other value of the key, or none, is `polish-legacy@1` | `rootProfile`, `seedNewSections`, `sectionsForJob` in `js/bid-model.js` |
| The tooling: `polishTooling(sf, lf, {dye, reno, system, traditional})`. $150 minimum on D51, the validation tab's cost per square foot by size and polish system (+$0.20 traditional, +8%), slurry hardener by the bag, plastic by the foot. Held to the real workbook on 1,056 recorded cases | `js/bid-model.js`, `backend/tests/fixtures/polish_tooling_oracle.json` (recorded by `backend/tests/js/polish-tooling-oracle.js`, which needs hyperformula@2.7.1) |
| The lodging nights, the sheet's way: `sheetNights` = (labor dollars less travel labor) / the first crew row's rate / the profile's `lodgingDivisor`. The engine's `lodgingNights` is the one formula, and `priceChain` calls it | `js/bid-engine.js`, `js/bid-model.js` |
| The page prices the root with `B.markupChain(input, B.rootProfile(ROOT).stamp)`, passes `tooling: B.rootTooling(ROOT)`, counts auto nights through `B.travelOpts`, and shows the Lodging and Per Diem hint through `B.lodgingHint` | `js/polish-estimate.js` |
| The proof: `oracle-polish-harness.js --rev2` requires equality with the oracle's Polish vectors on every case the three closed departures applied to; `departures.json` marks them `closedBy: polish-rev2@1` and keeps all five for the legacy profile, because saved bids still depart | `backend/tests/test_polish_rev2.py` |

**What rev 2 still does differently, on purpose** (`decisions` in `departures.json`): the Lodging and Per Diem
quantity is typed, not derived; a bid with no area has no tooling (the tab charges its $150 anyway, as Epoxy's tooling
does not); the polish system and kind are read from the takeoff's assembly names, where the tab asks F36 and G36; plastic's
renovation leg cannot be reached because the model carries no Renovation answer; and a remodel job with no rate typed
pays the Kansas floor. The hard bid and the bond stay out.

**`pricing.py` and `/api/price` are not retired, and why.** Nothing in `frontend/` posts to `/api/price` (the Reference Bid
engine was removed from Estimate Review; `estimate-review.js` nulls `computed_bid` and `alternate_computed_bid`), so the
route could go. But `backend/pricing.py` is still imported by `main.py` and `GET /api/pricing/systems` is called live by
`estimate-review.js` (the epoxy system and cove lists), and six test modules use `/api/price` as a handy authenticated
route. Removing the route and the functions only it uses (`compute_full_bid`, `compute_polish`, `compute_system`,
`compute_cove`, `roll_up`) while keeping `list_systems`, `list_cove_options` and `recipes_version` is its own change.

### 7.13 A bid made of sheets (Sheets phase 1)

The live estimate can copy a sheet, rename it, delete it and pick the base bid. Estimating Tool v2 could not. Sheets
phase 1 gives the v2 MODEL all of it, with no new screen (the widget is phase 3). The model lives in `js/bid-model.js`
and nothing is copied from the live estimate's code: the rules (twelve copies, a name of 31 characters with none of
`! : \ / ? * [ ] "`, `Copy<N>` ids that are handed out again) are the same, and the model writes them once.

| What | Where |
|---|---|
| A section's key is its workbook sheet (the form every saved bid uses) or a `Copy<N>` id that names its sheet in `sheet`, what it is called in `label` and what it came from in `source`. Code that means the workbook sheet reads the entry's `sheet`, code that means the section reads its `tab` (the key). A label is a value and never a key | `sectionsOf` |
| The root's `kind` is read in full: base (a missing key, so a saved bid is unchanged), option, off | `sectionsOf` |
| `polishBid(model, tabId, ctx)` prices ANY Polish section as the root is priced: `markupChain` over the section's own rows, with the profile the section was made with, its tooling on rev 2, and its travel by role. The page's `bid()` is one call to it for the root, and `priceSection` hands every other Polish section to it, so a copy of the Polish sheet, and a Polish sheet added to the bid, are exactly the root's price | `polishBid` |
| `copySection`: a copy keeps its source's takeoff, labor, contingency, fees and settings, its profile stamp and its `pool_packs` stamp (and the rates it kept, for a section under `tabs`), so it prices exactly as its source does, a bid saved before rev 2 or before the purchase pool included. It is an OPTION that starts OFF the proposal. `addSheet` adds a fresh Polish, Epoxy, Gyp, Seal or Seal (+Jnts) sheet (Leveling when it is priced), stamped rev 2 for Polish and `pool_packs` for all, as an option that starts ON the proposal as a total, with the library's defaults for the new section only. `renameSection`, `deleteSection` and `validateLabel` are the rest | `copySection`, `addSheet`, `renameSection`, `deleteSection` |
| `pickBase(model, ids)`: one sheet, or the combined Epoxy and Polish pair. Seal and Leveling are refused. The prior base becomes an option that is ON the proposal as a total. `baseOf(model)` answers `{ ids, jobType }` and a combined base is `combo` | `pickBase`, `baseOf` |
| The job's travel goes by role: the carrier (the first base) takes the job's Lodging and Per Diem, an option takes its own for its own crew, any other base takes none. When the carrier moves, the job's Travel Labor row moves with it | `polishBid`, `priceSection`, `pickBase` |
| `sectionsForJob` is base-aware: a bid whose base already is the job type is left as it is, and when the job type really moved the sections the bid has (by sheet, a copy included) become the base, the leaving bases are marked off as since Phase 12, and an option stays an option | `sectionsForJob` |
| A save also writes `base_tab_id` (null for a combined base) and names each priced tab by its label | `composePricingSnapshot` |
| What the draft keeps around the model comes back as a `patch` for `TW.setState` (the proposal's settings in `tab_opts`, and the words typed over an option's line), built from the draft the caller hands in. A delete always forgets what the draft kept under the id, and a new sheet scrubs it too, because a `Copy<N>` id is reused | `optionLeftoverPatch`, `copySection`, `deleteSection` |

**What the page changed, and why nothing it does today moved.** Its `bid()` calls `polishBid`, a Polish section under `tabs`
is bought like the root (`polishMaterial`, which the root's `rootMaterial` calls), and the places that mean the workbook
sheet (the Gyp card, the Seal takeoff, the Gyp preset) read the entry's `sheet`. The save golden is byte for byte what it was,
and so is the chain golden and every saved-bid fixture. **Left for the next phases:** the floating widget and its handlers
(phase 3), the shared panel (phase 2) and the proposal side (phase 4). **Named, for Hanz:** the root cannot be deleted
(deleting the Polish sheet when something else is the base would need a decision: take it off the proposal is what the model
says today), and a copy is an option, so on a job that is not local it is charged its own travel until it is made the base,
where it prices exactly as its source did.

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
| 8 | `js/bid-profiles.js` (part two) and `js/bid-engine.js`; Polish runs through a profile and its golden does not move; every tab's profile proven on the workbook's recorded answers |
| 9 | `js/intake-scope.js`; the live intake delegates to it; the v2 intake for the four job types; the shared county picker |
| 10 | Multi-section estimates, the price snapshot the proposal reads, per-tab rates snapshotted |
| 11 | Library columns (price breaks, bulk cost, coverage basis) |
| 12 | The seed script, and Epoxy end to end |
| 13 | Combo end to end |
| 14 | Gyp end to end: the five presets, the three areas, labor by the hour, the seven GP tiers |
| 15 and 16 | the Seal option, the Leveling option |
| 17 | Done for Polish rev2 (new bids only, 7.12). `pricing.py` and `/api/price` are NOT retired: see 7.12 |

v2 bids stay test copies until Kyle signs off each work type. Where each phase touches this document:

| Phase | What changes here |
|---|---|
| 1b | The Names paragraph under the title. Section 7 is unchanged: no copy in it is about a name. |
| 2 | 7.3 and 7.11. The test copy's cell list is one more copy of the intake's condition cells until Phase 7. `isV2Draft` is a second copy of `_polish_beta`, held equal by a test. |
| 3 (this one) | Sections 3 to 7 are written. Goldens, ratchet, strict node, shared helpers. |
| 4 | 7.10. The model keeps unknown keys; one save patch. Done. |
| 5 | Done. The module rename and the leaf in section 3 (with the paragraphs "Module names" and "The leaf"), the header in section 4, 7.5 (the model's ROUNDUP is the leaf's, and what was left where it is), and 7.11 (the move that did not happen). |
| 6 | Done. Section 6, the workbook oracle, and the `js/bid-profiles.js` row of section 3 (the file exists, with only the cell maps in it). Nothing in section 7 changes: none of its copies is about the workbook's own cells. |
| 7 | Done, with some copies left on purpose. 7.1, 7.2, 7.3, 7.6, 7.7 and 7.8 each say what was replaced and what stays and why. `js/work-types.js` and the Python pin, the vocabulary paragraph near the top, the header in section 4 and the tests in section 6. |
| 8 | Done. 7.4 and its row in the summary table (built-in rates now one source), the paragraph "The engine and the profiles", the rows of the engine, the model and `bid-profiles.js` in section 3, the header in section 4, and "The bid engine's proof" in section 6. Nothing is wired into a new screen: no bid changed price. |
| 9 | 7.6, 7.9. `js/intake-scope.js`; the v2 intake for the four job types. |
| 10 | Done. 7.10 (sections, the rates a section keeps, the one composition of what a save writes) and the module rows of section 3. No screen shows a second section yet and no saved bid changed: the save golden is byte for byte. |
| 11 | Done. A material can carry `price_breaks` (a list of `{min_qty, unit_cost}`, each break applying FROM its quantity, inclusive, as Kyle's flake line `IF(O194<240, ...)` does), a `bulk_cost` (the pack cost when the bid has Bulk Discount on, passed to `priceLine` as `{bulk: true}`) and a `coverage_basis` (`sf`, `lf` or `each`, which measure of a whole takeoff the material is priced against). All three are nullable and a material without them prices exactly as before (the library golden is unchanged). A price break beats the bulk cost. Admin only on the Items tab's More panel and on the API. Staging has the columns (`backend/ops/library_price_breaks.sql`); production does not until Hanz approves. Named modelling gap: microFlake's break is judged on the TWO flake lines added together in the sheet (`O201+O202`), and the library judges each line on its own. |
| 12 | Done. The seed script (`backend/ops/seed_library_from_workbook.py`: 60 materials, 39 assemblies and one crew line; dry run by default, staging only, insert-only), `js/epoxy-takeoff.js`, an Epoxy job as a section of the bid (`sectionsForJob`, `sectionView`), the estimate page's panels for any section it edits, the proof (section 6), and `ready: true` for Epoxy in `js/work-types.js`. Saved Polish bids are unchanged (the goldens have no diff). **Declared departures from the workbook, each a named modelling gap for Kyle:** (1) SUPERSEDED BY THE PURCHASE POOL (see "Buy packs for the whole job" below): this said a flake or quartz price break is judged on the two broadcast lines of a system added together in the sheet and on each line alone in the library, so v2 was over the workbook by $10 to $40 on 83 of the 440 recorded jobs. The estimate now buys each material once for the section and reads the break as the sheet reads it, and no recorded job is over the workbook; (2) a coverage is kept to three places (a 40 lb bag of flake covers 266.66667 SF and is stored as 266.667, rounded UP so that a whole number of square feet can never buy a bag the sheet does not); an area typed to two decimals within 0.003 SF past a bag edge does buy one bag fewer (2,666.67 SF of MACRO flake is $90 under), because the sheet would round that up to a bag; (3) a library cost is kept to four places, so a sum can land a hair either side of a whole dollar (5 jobs in about 1,500 scanned, a dollar apart in material and one to three dollars in the bid, mostly large jobs or ones with a cove: 40-S quartz at 3,000 SF is $2 under, Shop Floor Single Broadcast at 15,500 SF is $2 over); (4) the cove is two ROUNDUPs deep and its aggregate follows System 1 (odd rule 11), so it is priced by a formula in code from editable price rows (`wb-epoxy-cove-*`), with a constant as the fallback; (5) tooling is moisture tests and $0.33 a square foot with a $150 floor, in code, and a section with no area charges none (the sheet charges its minimums); demo tooling and plastic are typed quantities v2 does not carry; (6) the patch is $0.10 a square foot of the whole area, always, from `wb-epoxy-patch`; (7) Bulk Discount is stored on the material and not used, because the v2 model has no switch for it; (8) no hard bid, no bond input, and travel from the model's Lodging and Per Diem lines, not the sheet's local switch (the oracle vectors that need them are left out of the proof and counted); (9) System 1 is the first seeded floor system row that is on, and a system Kyle composes himself is not read as quartz; (10) a square-foot row added beside a measured one in a section other than the root starts as the same floor. **Left for Kyle:** the one seeded crew line (3 guys, $33, days blank, from `Epoxy!A47` and `C47`), which primers go with which system (the sheet lists four for System 1 and two more for System 2, v2 offers them all), and the remodel rate when no county is picked (the Epoxy profile charges the sheet's 10%, where Polish charges the Kansas state rate). |
| 13 | Done. A Combo job is the Polish root and an Epoxy section, both bases; `ready: true` for Combo in `js/work-types.js`; the page's whole-bid card on Review and the one-carrier travel note; the proof pairs 168 Polish and Epoxy workbook runs (`tests/js/combo-v2-proof-harness.js`) and the Combo proposal is rendered from the v2 save (`tests/test_v2_combo.py`). **Plan defaults, for Kyle to confirm:** (1) Hotel and Per Diem are charged ONCE per job, on the Polish section, and Lodging and Per Diem count the nights from that section's own crew, so a Combo whose Epoxy crew stays out longer than its Polish crew counts the Polish nights only; (2) the job's questions (Taxable?, Prevailing wage, Remodel tax) are answered once and apply to both sections, where the workbook has a cell on each tab; (3) Fees and Textura and the contingency are each section's own, the Fees default going to the carrier. **Not proved, named:** Epoxy runs with their own travel typed in are not paired (the combo charges travel on one section), and the intake's Epoxy square-foot boxes seed the Epoxy section once but do not follow a later edit, as for an Epoxy-only job. |
| 13a | Done. **Buy packs for the whole job, round each coat like Kyle** (Hanz, 2026-10-13). Within one priced section (one tab of a bid) the same COAT used on several takeoff rows is bought once. A coat is one line of one assembly (the same assembly id and line index, or the same material row): `pricePool` in `js/library-core.js` adds the fractional quantity of that coat across every row first, then applies waste, roundup to whole packs and the price break once, and hands the pooled cost back to the rows in proportion to what each needed, in whole ten-thousandths of a dollar by the largest remainder, so every row still shows a cost and the rows add up to the pooled total. `priceAssembly` stamps its answer with the assembly id so the pool can tell one coat from another. **Two different lines of one assembly that buy the same item are two coats**, each rounded up to its own whole packs exactly as Kyle's sheet rounds each line (Shop Floor Double Broadcast is three lines of Shop Floor, 100 SF/Gallon: 250 SF is 3 + 3 + 3 gallons and $1,270.01 of system, the workbook's figure), so a single-area, single-system job prices to the workbook to the cent. The earlier cut of this row (#662) pooled by ITEM and priced those jobs up to $476 of material below the sheet; Hanz decided "Round each coat like Kyle" and the key is now the coat. Different materials on one price ladder (identical price breaks, pack cost, bulk cost, pack size, unit and roundup, which is how the sheet reads a system's two flake lines), and two coats of one item, have the break judged on every pack bought across the ladder while each keeps its own packs. The ladder is derived and not stored, so it needs no column and no reseed. Dye, Joint Filler and Remove Existing are never pooled, a cove keeps its own formula (and is pooled by length, see below), an off row buys nothing, and a coverage typed on one bid is the same material. The estimate page prices every row through one wrapper (`rowPrice` over `pooledRows`) and the Epoxy section through `E.sectionMaterial`, so the cost box, the material sum and the save cannot disagree. **Saved bids do not move:** only a section stamped `pool_packs: true` pools, the stamp is written when a section is made (`activateSection`) or a new bid's root is seeded (`seedNewSections`), and a saved one never gets it (the 26 saved records of `save_patch_golden.json` are byte-identical; the seven new-bid records differ by that one key). **Measured on the real library:** System 1 5,000 + System 2 3,000 and 1,000 + 1,000 still cost exactly what one 8,000 and one 2,000 SF floor cost, with and without cove (the polish fixture that read $26,742 against $25,162 reads $25,162 for both). **Against the workbook (the Epoxy proof, 440 jobs):** the sheet's own way of buying, each line to its own packs and the break judged on a system's lines added together, is the workbook on every job, and the pool now prices every job at that figure: the one-purchase departure set went from 110 jobs (#662) to 0, and the 83 jobs that were over the workbook before the pool are all exactly equal (#662's item pool left 54 of them equal and 29 below it). The declared departures that remain are the four-place sums, the three-place coverage window and the no-area job, which existed before the pool. What the workbook cannot say, and v2 does on purpose, is the same coat on two areas as one purchase (a system or primer in both System 1 and System 2); the recorded jobs hold one such job and it lands on the workbook's figure. **The cove is pooled the same way** (`poolCoves` in `js/epoxy-takeoff.js`): the same cove assembly on two or more rows is priced once at the lengths added together and each line of it goes back to the rows by length, so 100 + 100 LF of 4 inch epoxy cove costs what 200 LF costs ($354.49, not $443.32). Two different cove assemblies stay two purchases. |
| 14 | Done. A Gyp job is a Gyp section of the bid with the Polish root off, filed under the workbook tab of the PRESET the estimator chose (`Gyp (USG 1-8")`, USG N12 1/8", is the default; the other four are `Gyp (USG N12ULTRA)`, `Gyp (USG N25 1-4")`, `Gyp (GWorx SC190)` and `Gyp (FR)`), so the proposal names the sheet that was priced, as the spreadsheet does. `js/gyp-takeoff.js` splits the takeoff into the five figures the engine's gyp-split chain takes (gypsum, extras, sand, sound mat and its rolls) and the tooling, and this REPLACES the stop-gap from Phase 10, where the page put the whole library sum on the gypsum line. The takeoff is one row for each area (three library assemblies, `wb-gyp-area-*`) and the section's `gyp` block holds what the estimator typed: a thickness for each area (blank is the sheet's own), the mix, the sound mat, ISO strip at all areas, moisture tests and mobilizations. Labor is five crew lines priced by the hour at the Gyp sheets' $33.66, typed as guys and hours (the sheet derives the hours from the takeoff; v2 quotes the sheet's figure beside the boxes), and escalation is always 5% (odd rule 5). The seed script adds the Gyp materials (20: the USG and GrassWorx table's and Gyp (FR)'s own), the three area assemblies and the five crew lines (insert-only; the USG primer is now bought by the 53 gallon drum so a gallon is exactly the sheet's `=891/53`; the plain per gallon row Phase 12 planned is gone from the plan). The Gyp tabs' Local cell (`B5` on the base and on Gyp (FR)) is written from the Local condition, closing that known gap of Phase 7b, and `ready: true` turns Gyp on in the intake, which draws the live intake's three area boxes for a Gyp job. **The proof (`tests/test_gyp_v2_proof.py`) has no declared departures:** 795 oracle vectors of the five tabs equal to the cent through a v2 section (including the sound mat at 279 against 280 rolls and every tab's own truckload, the soft costs' edges at 234,450 and 334,900, and all seven GP tiers), and 401 jobs typed into the five tabs equal to the dollar on the material split, the rolls, the tooling and every line down to the total (`tests/js/gyp-jobs-recorder.js`; the recorder needs HyperFormula and CI only compares). **Plan defaults, for Kyle to confirm:** (1) Gyp opens on USG N12 1/8"; (2) labor rate $33.66 like the sheet, and the sheet's crews of 8, 8, 7, 8 and 2 are quoted, not seeded; (3) mobilizations are an input the estimator types, which today only sets the hours the sheet would suggest; (4) a takeoff row that is not an area is an extra (it takes the extras' 8% escalation and 10% shipping, like the sheet's blank lines); (5) the truckload follows the sound mat on the first four tabs and is a typed 448 on Gyp (FR), as in the sheet. **Not proved, named:** the sheet's lodging (v2 takes Hotel and Per Diem from the lines the estimator types: 40 oracle vectors are left out and counted), a typed bond rate (60 vectors), and the proposal's thickness words, which the proposal side fills with its own defaults for every Gyp bid, spreadsheet or v2. The intake's three area boxes seed the Gyp section once and do not follow a later edit, as for an Epoxy job. |
| 15 | Done. **A Seal option on any v2 bid** (Hanz, 2026-10-07: Seal and Leveling are options on a bid, never job types). The estimate page has a `+ Add option` button under the section strip that offers the two Seal sheets (`optionsToOffer`, `addOption` and `removeOption` in `js/bid-model.js`; `optionSheets()` and the tab's `offered` flag in `js/work-types.js`, true for Seal and false for Leveling until Phase 16). An option is a section of kind `option` filed under its sheet (`Seal` or `Seal (+Jnts)`), on the `seal` profile with its own rates snapshot, its own takeoff and its own crew. `addOption` makes the section as `activateSection` does and gives it the library's defaults as `seedNewSections` gives a new section, and takes ONLY that section from the seeding, so nothing the estimator typed anywhere else can be reseeded (a root that had stated nothing included). A new option opens on the sheet's own default assembly over what the base measures (`wb-seal-2-coats`, or `wb-seal-jnts-2-coats` for Seal (+Jnts): both sheets ship with both sealer lines filled in, and Seal (+Jnts) adds a kit of joint filler for every 3,500 SF), and on three crew lines filed under the Seal pill (`seal-install`, `seal-mockup`, `seal-jointfill`). `js/seal-takeoff.js` adds what the sheet does before its chain and a library row cannot say: the patch (a price a square foot of the whole area, always, `IF(B10="New", 0.05, 0.15)`: the renovation price when the draft's Renovation cell says Reno, and a job that never said is a new floor) and the tooling ($0.27 a square foot with a $150 floor, rounded up). The prices are editable library rows (`wb-seal-patch-new`, `wb-seal-patch-reno`, `wb-seal-sealer`, `wb-seal-joint-filler-kit`) with the template's figures as fallbacks, pinned by `tests/test_seal_takeoff.py`. **What a save writes for an option:** the section's totals are stamped from its own bid, and the proposal side's keys are the same ones a live-estimate option has, so the option prints under Options & Unit Prices in the same words and money. `priced_tabs` holds a tab for it (role `seal`, kind `option`, marked `v2`, named "Sealed Concrete" or "Sealed Concrete with Joint Filler", its total and its own two taxes), and `tab_opts[<sheet>]` says `is_option` and `show` (`price_mode` total), which is the key `proposal-review.js` reads to put a priced tab under the options. An entry the draft already holds is never rewritten, so what the estimator did in the Proposal step's sidebar survives the next save; removing an option takes its entry out of the draft. **An option is never in the lump sum:** `combine` sums the base sections only (an option-only tab is never a base), the area and cost snapshot are the bases', and the Review step draws each option as a card of its own in a clay tint (`data-rev="option"`) with its own total and the words "Option, not in the lump sum", while the bar says "Polish $17,666 · Seal $18,161 option (not in the lump sum)". A bid whose model holds a `tabs` object is never "single", even with no option left, so the save that removes the last option still overwrites the price snapshot the option was in. **The Phase 7b known gap is closed for Seal:** Local writes `Seal!B4` and Renovation writes `Seal!B10` (`Seal (+Jnts)` mirrors both), so the Seal tab answers the job's questions as the base does; this changes the LIVE intake too, which shares the table (see the plan note below). **The proof (`tests/test_seal_v2_proof.py`):** 204 oracle vectors of the two Seal tabs (102 each) equal to the cent through a v2 option section, including Seal's sixth gross profit rung on its edge (30% at a sub-total of 42,499, 28% from 42,500; Polish steps to 30% at 32,500 and stays), and 80 jobs typed into the two tabs (`tests/js/seal-jobs-recorder.js`: the area either side of 3,500 SF and the $150 tooling floor, a new floor and a renovation, one coat of sealer or two, joint filler on and off, the crew's days; the recorder needs HyperFormula and CI only compares) equal to the dollar on the material before it is rounded, the patch, the tooling, the labor, the sub-total, the sales tax and the total. A base plus a Seal option has the lump sum of the base alone (`tests/test_v2_seal_option.py`), and the generated proposal prints the option line with the option's price, in the same words as a live-estimate option. **Seeded for Seal (`--only seal`, insert-only):** 4 materials, 4 assemblies, 3 crew lines and their calculator rows; applied to STAGING only (Hanz, 2026-10-12), not to production. **Named gaps, for Kyle:** (1) the Seal sheets charge their OWN lodging, per diem and travel labor (the drive hours are copied from the Polish tab), and v2 charges the job's travel once, on the base, so a Seal option on a job that is not local is under the sheet by the nights it would add (16 oracle vectors left out and counted); (2) a Hard Bid answer (120 vectors) and a typed bond rate (24) have no box in v2 and are left out and counted; (3) the patch is always charged, and the sheet's "Exclude Patching" is a typed edit of the price that v2 does not carry; (4) the sheet's demo tooling, slurry hardener and plastic are typed quantities v2 does not carry, and an option with no area charges no tooling where the sheet charges its $150 minimum; (5) the joint filler crew's days are typed (the sheet works them out of the area); (6) the live spreadsheet's Seal option, on a bid saved after this ships, now follows Local and New or Reno: Seal!B10 was blank on every live bid, and a blank answers the Reno branch of the patch, so the live Seal option's patch drops from $0.15 to $0.05 a square foot on a new floor, as Polish's already did. |
| 16 and later | The Leveling option, Polish rev 2. v2 bids stay test copies until Kyle signs each work type off. |
| Sheets 1 | Done. The model for copying, adding, renaming and deleting a sheet and for picking the base bid (7.13): section identity, `polishBid`, `copySection`, `addSheet`, `renameSection`, `deleteSection`, `pickBase`, `baseOf`, travel by role, a base-aware `sectionsForJob`, and `base_tab_id` and label names in the save. No new screen. `backend/tests/test_v2_sheets_model.py` with `tests/js/sheets-model-harness.js` |
| Sheets 4 | Done. The Proposal step reads the base, the options and the deducts a v2 estimate saved. It already priced from `priced_tabs`, `tab_opts` and `base_tab_id` (`rebuildPricing`) and printed the rooms that makes through `main._build_options`, so options and deducts need no new code. The one change: **the base is picked on the estimate.** Each v2 option is priced with its own travel beside the base it was priced against, so a base switched on the Proposal step would print a price nobody worked out. When every priced tab is marked `v2: true` (`TWPrice.allV2`, `js/price-lines-core.js`, the same test as `v2PricingView` in `shared.js`), the Pricing options panel draws its base radios read-only (the combined Epoxy and Polish one included), says "Pick the base bid on the estimate" and links to the estimate. An option on or off, total or add / deduct, the description and the notes stay editable and write the same `tab_opts` keys, and a Seal option stays a total (a stale "deduct" on it is read as a total). A v2 draft lists every sheet it holds, with no "+ Add another system". A draft from the spreadsheet is untouched. `backend/tests/test_v2_sheets_proposal.py` with `tests/js/v2-proposal-snapshot-harness.js` (drafts built by the real model) and `tests/js/v2-options-panel-harness.js` (the page's own panel and pricing, run). Three follow-ups from its review. The notes: the boilerplate is written down when it is seeded (`notes_seed`: its work type and exact text), so a Proposal step opened after the base was picked on the estimate re-seeds notes nobody edited (`tests/js/v2-notes-reseed-harness.js`). A combined base's Deduct reads "in lieu of" both systems. A base the estimate could not price (`total: null`, an `unpriceable` reason) keeps no price on the Proposal step: no option prints against it, the page says so and Continue stops, and the document the draft already held is not rewritten to $0 (`TWPrice.noBasePrice`; the Files-door harness runs Continue) |
