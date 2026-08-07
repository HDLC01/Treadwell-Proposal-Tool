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
npm install hyperformula@2.7.1
node one-config.js roundup   # 4. the engine's answers, and the diff
```

`one-config.js` takes `was`, `nosmart`, `precision` or `roundup`. **One config per process, and
that matters:** an earlier version ran all four in one process, and
`unregisterFunctionPlugin` silently failed to remove the custom `ROUNDUP` — so every
configuration measured after the plugin one took credit for a fix it did not have. That is how
the first run of this audit reported 15 wrong cells instead of 98. If you add a configuration,
give it its own process.

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
