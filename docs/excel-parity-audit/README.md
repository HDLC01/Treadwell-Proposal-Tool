# Excel parity audit

Proves that the number on screen equals the number in the workbook, cell by cell, to the cent.

It exists because that was not true. The estimate screen recomputes Kyle's workbook in the
browser with HyperFormula, and HyperFormula's `ROUNDUP` does not behave like Excel's. Excel
quietly cleans a value sitting a hair off a round number before rounding it; HyperFormula rounds
the noise up. The workbook wraps nearly every subtotal in `ROUNDUP(...,0)` — 1,570 calls, plus 78
`CEILING`s — so the error compounds up the chain, and it only ever goes one way: **up**.

## What it found

Six real estimates from the Treadwell Dropbox folder. Every rounding cell and every headline
total, compared against Excel itself after a full recalculation. **10,208 cells.**

| engine configuration | cells disagreeing with Excel |
|---|---|
| what shipped before | **98** |
| `smartRounding: false` | 97 |
| `precisionRounding: 10` | 97 |
| `js/xl-excel-rounding.js` (now shipped) | **0** |

The worst were not polish:

```
Epoxy!D88   workbook 15,213   screen 15,219   +$6      <- epoxy total base bid
Epoxy!D88   workbook 11,029   screen 11,033   +$4
Polish!D82  workbook 23,301   screen 23,303   +$2      <- Project Jayhawk
```

Note the middle two rows of that table. Both are one-line changes, both look like the obvious
fix, and both move exactly **one** cell out of ninety-eight. Only overriding the two functions
closes it. `backend/tests/test_excel_rounding_parity.py` fails if anybody reaches for them again.

## Running it

Needs Excel installed (it is the authority — the application Troy opens the file in) and
`hyperformula` available to node.

```powershell
# 1. Put workbooks in this folder as job01.xlsx, job02.xlsx, ...
#    Copy them OUT of Dropbox; never work on the originals. Prefer files already stored
#    locally, or the copy triggers a download:
#      Get-ChildItem $dropbox -Recurse -Include "*estimate sheet*.xlsx" |
#        Where-Object { -not ($_.Attributes -band [IO.FileAttributes]::Offline) }

python extract.py            # 2. workbook -> JSON, in the shape /api/sheet serves
./excel-read.ps1             # 3. Excel's own answers, after CalculateFullRebuild
npm i --no-save --prefix $env:TEMP\hf hyperformula@2.7.1    # once: into a scratch folder OUTSIDE the repo
$env:NODE_PATH = "$env:TEMP\hf\node_modules"
node one-config.js roundup   # 4. the engine's answers, and the diff
```

Install hyperformula with that `npm i --no-save --prefix <scratch dir> hyperformula@2.7.1` form and point node
at the result with `NODE_PATH=<scratch dir>/node_modules`. Do not run a plain `npm install hyperformula@2.7.1`
inside this folder: it writes a `node_modules` folder, a `package.json` and a `package-lock.json` here. This
repository has no `package.json` on purpose (nothing in it depends on a node package), so all three are
gitignored, along with the `job*` files and `*.excel.json`, because this repository is public and none of that
belongs in it.

`one-config.js` takes `was`, `nosmart`, `precision` or `roundup`. **One config per process, and
that matters:** an earlier version ran all four in one process, and
`unregisterFunctionPlugin` silently failed to remove the custom `ROUNDUP` — so every
configuration measured after the plugin one took credit for a fix it did not have. That is how
the first run of this audit reported 15 wrong cells instead of 98. If you add a configuration,
give it its own process.

## The engine is shared: `engine.js`

`one-config.js` is only the comparison. The engine itself lives in `engine.js`, which
`backend/tests/js/workbook-oracle.js` (the answer key for the v2 estimating tool) uses too, so there is one
way to build Kyle's workbook outside a browser:

- it loads `hyperformula/dist/hyperformula.full.min.js`, the file the page pins, and refuses to go on unless
  its sha384 is the one `frontend/estimate-review.html` pins;
- it registers `frontend/js/xl-excel-rounding.js` exactly as it ships, through a two-line shim (a global
  `HyperFormula` and a global `window`). The audit used to carry its own copy of that plugin, which could
  drift from the shipped one; it no longer does. The `roundup` configuration IS the shipped plugin;
- it builds the workbook in the page's order: every sheet, then the named expressions with the page's alias
  rule (`Glaze4` becomes `Glaze_4`), then each sheet's cells.

`backend/tests/js/oracle-engine-harness.js` is what keeps the claim "same engine as the screen" from going quietly
stale. It lifts the page's own `HF.init`, its alias rule, `HF.rewriteNames`, its named-expression block and
`HF.loadSheet` out of `frontend/js/estimate-review.js` and RUNS them, and runs this module's `build()` beside
them, against a recording stand-in for HyperFormula on a small fixture that takes every branch of the page's
name block (a name that is refused and aliased, a scope on the first sheet, a scope that does not exist, a name
that throws, an alias that throws, a sheet with no cells). Every call each one makes to the engine is kept in
order and `backend/tests/test_workbook_oracle.py` requires the two lists to be equal. The page's boot order
(add the sheets, register the names, only then load cells) is read from its source. The same test changes one
line of the page or of `engine.js` in a scratch copy, ten different ways, and requires each to go red.

What is NOT claimed: the oracle types its numbers into the engine with `setCellContents`. The page's own door
for an edit, `HF.setCellValue`, also turns numeric text into a number and refuses to write a Hard Bid? cell.
The oracle goes round it on purpose (it records what the workbook does when that cell says Yes, which the page
can never produce), so what is compared is how the workbook is BUILT, not how a keystroke is applied.

## Reading the output

```json
{"config":"roundup","numeric":10208,"match":10208,"wrong":0,"pct":100,"worst":[]}
```

`worst` lists the largest disagreements with the workbook value, the engine value and the
difference. Anything non-empty means the screen and the file no longer agree, and the bid a
customer sees is not the bid the workbook computes.

## What it deliberately does not compare

Text, dates and error cells — only numbers can agree to the cent. Cells where Excel itself
reports an error are skipped rather than counted as agreement, so a workbook full of `#DIV/0!`
cannot score 100%.
