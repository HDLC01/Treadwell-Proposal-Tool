# Adding a 3rd & 4th Flooring System to the Estimate Sheet (by hand, in Excel)

**File:** `backend/templates/estimate_sheet_5.7.xlsx`
**Tab:** `Epoxy` (do this on the `Epoxy` tab only; the other tabs are separate)
**Audience:** Kyle — no coding needed, just Excel.
**Last verified against the file:** 2026-06-02 (every coordinate below was read straight out of the workbook, not guessed).

---

## 1. Read this first (plain English)

Today the Epoxy sheet quotes **two** flooring systems on one bid:

- **System 1** — its square footage goes in cell **E20**, its cove (linear feet) in **E34**.
- **System 2** — square footage in **E24**, cove in **E37**.

You want to be able to put **up to four** systems on a single bid (System 3 and System 4),
so a project that has, say, an epoxy floor in the kitchen, a different epoxy in the
walk-in, plus two more areas all land on one estimate and one Total Base Bid.

**The key safety fact:** an *empty* system adds **$0** to the bid. Every cell you'll touch
multiplies a square-footage number by a cost. If the square footage is blank (0), the math
is 0 × cost = **$0**. So it is completely safe to "over-build" the sheet — wire up System 3
and System 4 now, leave them blank, and they'll just sit there contributing nothing until a
future bid actually needs them. **Nothing you do here can raise an existing 2-system bid**,
because you're only *adding* terms that are zero when unused.

**One thing this recipe does NOT try to do.** Systems 1 and 2 each have a fancy
**dropdown** (cell A22 / A26) that auto-looks-up the material cost from big hidden pricing
tables further down the sheet (around rows 124–340). Those pricing tables physically exist
for **only two systems** — System 1 reads the left-hand tables (columns A–Y), System 2 reads
the right-hand tables (columns AA–AS). **There is no third set of tables**, and hand-copying
220+ rows of interlinked pricing formulas into fresh columns is exactly the kind of thing that
breaks a workbook. So System 3 and System 4 will use a **simple typed cost per square foot**
instead of the dropdown. You lose the auto-pricing convenience for systems 3 & 4; you keep a
correct Total Base Bid. (Section 2 has an *optional* add-on if you ever want a cosmetic
dropdown that doesn't auto-price.)

When you're done, the only difference at the top of the sheet is two more square-footage
boxes and two more cove boxes feeding the same grand total. Save it as a **copy** first.

> **Before you start:** File → Save a Copy → name it `estimate_sheet_5.7_WIP.xlsx`.
> Do all the work in the copy. Only swap it in once Section 5's checklist passes.

---

## 2. Step-by-step in Excel

### Where things will go (the four input boxes you're adding)

| System | Square-Footage box | Cove (LF) box | Material cost box | Cost-per-SF box |
|---|---|---|---|---|
| 1 (exists) | E20 | E34 | C18 (patch $/sf) | dropdown A22 |
| 2 (exists) | E24 | E37 | C19 (patch $/sf) | dropdown A26 |
| **3 (new)** | **E22** | **E36** | **B23 × C23** (row 23) | **C23** |
| **4 (new)** | **E26** | **E39** | **B27 × C27** (row 27) | **C27** |

Those new boxes (E22, E36, E26, E39) and the cost rows (23, 27) are all **currently empty
on the sheet** — rows 23 and 27 already contain harmless `=B23*C23` / `=B27*C27` formulas
that equal $0 today because B/C are blank. You are filling in blanks, not overwriting
anything.

### Step 2a — Label the new input boxes (optional but recommended)

So nobody is confused about which box is which, type labels in the empty cells to the right:

1. Click **F22**, type `SF -- System 3`, Enter.
2. Click **F26**, type `SF -- System 4`, Enter.
3. Click **F36**, type `LF -- System 3` (cove), Enter.
4. Click **F39**, type `LF -- System 4` (cove), Enter.

(These are just notes for humans; they don't affect any math.)

### Step 2b — Set the System 3 & 4 material cost rows

Systems 1 and 2 charge a patch/prep cost of **$0.10 per square foot** (that's the `0.1` in
cell C18). Give 3 and 4 the same default:

1. Click **C23**, type `=C18`, Enter. *(System 3 inherits System 1's $/sf — change later if needed.)*
2. Click **B23**, type `=E22`, Enter. *(System 3's quantity = its square footage.)*
3. Click **C27**, type `=C18`, Enter.
4. Click **B27**, type `=E26`, Enter. *(System 4's quantity = its square footage.)*

Now `D23` (which already holds `=B23*C23`) becomes System 3's material dollars, and `D27`
(already `=B27*C27`) becomes System 4's. **Both feed the Material Sub-Total automatically**
— see the note in Section 3 about D40.

> If a system needs a richer material cost than "$/sf × area" (e.g. a quoted lump material
> figure), just type the dollar amount straight into **D23** (or **D27**) instead of using the
> B/C formula. It still rolls up the same way.

### Step 2c — Wire the System 3 & 4 cove into the cove material rows

Systems 1 & 2 cove material lives in rows 35–38 and is driven by the cove dropdowns. For
systems 3 & 4, the simplest correct approach is to fold their cove **linear footage** into the
floor/cove rollups (Section 3) and, if there's a cove material cost, type it into a free
material scratch row:

1. Click **D32**, type `=E36*0.1` *(System 3 cove material at a placeholder $0.10/lf — adjust the rate, or type a flat dollar amount instead)*, Enter.
2. Click **D33**, type `=E39*0.1` *(System 4 cove material)*, Enter.

`D32` and `D33` are empty material scratch rows that already roll into the Material Sub-Total.
(If a system has no cove, leave its SF/cove boxes blank and these stay $0.)

### Step 2d — Turn on the System 3 & 4 labor rows (this is the important one)

Good news: the labor section was **already built for four systems**. Rows 47–50 are the four
labor lines, and the man-hour totals (A52, H64, F73 — see Section 3) **already add up all four
rows**. Today rows 49 and 50 are dormant because (a) their crew/days are blank and (b) their
square-footage references point at empty scratch cells (`=H26`, `=H36`). You just need to
point them at System 3 and System 4 and give them a crew.

System 1 labor (row 47) is **3 guys × 5 days** at rate **$32.20/hr** (cells A47/B47/C47).
Mirror that onto rows 49 and 50:

1. Click **I49**, type `=E22`, Enter.  *(was `=H26`; now reads System 3's square footage)*
2. Click **J49**, type `=E36`, Enter.  *(was `=H36`; now reads System 3's cove)*
3. Click **I50**, type `=E26`, Enter.  *(now reads System 4's square footage)*
4. Click **J50**, type `=E39`, Enter.  *(now reads System 4's cove)*
5. Click **E49**, type `System 3`, Enter.  *(label, matches E47/E48)*
6. Click **E50**, type `System 4`, Enter.
7. Leave **A49, B49, A50, B50 blank for now.** A blank crew = 0 labor dollars = $0 added.
   When a real System 3 bid comes in, type the crew size in A49 and days in B49 (and A50/B50
   for System 4), exactly like A47/B47. C49 and C50 already inherit the rate via `=C47`.

> Why this is safe: with A49/B49 blank, row 49's labor formula `=(A49*B49*C49)*...` is 0, and
> the new `=E22` reference is also 0 until you type a square footage. Zero added either way.

### Step 2e (OPTIONAL) — A cosmetic dropdown for System 3 / System 4

If you want a dropdown in the System 3/4 rows *just so the system name shows up on screen*
(it will **not** auto-price — see Section 1), here's how to recreate one that reuses System
1's existing list:

1. Click the cell you want the dropdown in — e.g. **A23** for System 3 (an empty label cell).
2. Ribbon → **Data** → **Data Validation** → **Data Validation…**.
3. **Allow:** `List`.
4. **Source:** type `=$R$180:$R$195` (this is the exact same source list System 1's dropdown
   in A22 uses — verified). Click **OK**.
5. For System 4, repeat in **A27** with the same source `=$R$180:$R$195` (or use System 2's
   wider list `=$AR$180:$AR$205` if you want the wall options too).

The list values (verified, in cells R180:R195) are: *System 1 Options* (header), 3/16" Urethane
Cement SLB, 3/16" Urethane Cement Shop Floor + Armor Top, 1/4" Urethane Cement MDB, MACRO Flake
Single Broadcast, micro Flake Double Broadcast, Hybrid MACRO Flake, Hybrid micro Flake, Fast
Cure MACRO Flake, 40-S Quartz Double Broadcast, Hybrid Quartz Double Broadcast, Trowel Hybrid
Quartz, Shop Floor Double Broadcast, Shop Floor Single Broadcast, Dur-A-Gard, Dur-A-Gard Novolac.

> Reminder: this dropdown is a **label only** for systems 3 & 4. The dollar value still comes
> from the C23/C27 cost you typed in Step 2b — picking a name here does NOT change the price.

---

## 3. The rollup formulas you MUST edit (exact before → after)

These are the **hand-enumerated** rollups — the ones that list each system by name instead of
summing a range. Each needs the new system's term added. **Edit these exactly.** Coordinates
and "before" text were read straight from the file.

| Cell | What it is | BEFORE (current) | AFTER (type this) |
|---|---|---|---|
| **B44** | Floor-ONLY square footage | `=E20+E24` | `=E20+E24+E22+E26` |
| **B45** | Total Square Footage (drives almost everything) | `=E20+E24` | `=E20+E24+E22+E26` |
| **D45** | Total Cove Linear Footage | `=E34+E37` | `=E34+E37+E36+E39` |

That's it for the SF/cove side. **Everything else is already correct** — confirmed by reading
the file:

- **A52** (`=(A47*B47)+(A48*B48)+(A49*B49)+(A50*B50)`) — already enumerates rows 47–50, so it
  already covers Systems 3 & 4. **No edit needed.**
- **H64** "Total Man Hours"
  (`=(((A47*B47)+(A48*B48)+(A49*B49)+(A50*B50))*IF($E$45="8 hour days",8,10))+(A52*B52)`) —
  already covers rows 47–50. **No edit needed.**
- **F73** "Man Hour Budget (Raken)" (same formula as H64) — already covers rows 47–50.
  **No edit needed.**
- **D40** Material Sub-Total (`=ROUNDUP(SUM(D18:D39),0)`) — this is a **range** sum over rows
  18–39, so the System 3/4 material in D23, D27, D32, D33 is **absorbed automatically.**
  **No edit needed.**
- **D43** Material Total (`=SUM(D40:D42)`) — range-based off D40. **No edit needed.**
- **D88** TOTAL Base Bid (`=SUM(D70,D73:D77,D82,D85)`) — sums the cost subtotals, which trace
  back to D40/B45/labor. **No edit needed.**
- **C88** $/SF (`=D88/C87`, and C87 = `=B45`) — recomputes from B45 automatically. **No edit
  needed.**
- **B16 / D16** (the Total Base Bid + $/SF shown at the top, `=D88` and `=C88`) — mirror D88/C88.
  **No edit needed.**

> **Why so few edits?** Most of the sheet already totals by *range* (SUM over a block of rows)
> or already lists rows 47–50 by name. Only three cells (B44, B45, D45) hard-code
> `=E20+E24` style sums that physically name only Systems 1 & 2. Those three are the entire job.

**Double-check after typing:** B45 must read exactly `=E20+E24+E22+E26` and D45 exactly
`=E34+E37+E36+E39`. A typo here is the one thing that would throw the total off.

---

## 4. New cell coordinates for the developer (`estimate_writer.py` cell map)

These are the cells the backend should write so the tool can push System 3 / System 4 values
into the sheet. Add to `EPOXY_CELL_MAP` in `backend/estimate_writer.py` (it currently has
`system_1_sf → E20`, `system_2_sf → E24`, `cove_1_lf → E34`, `cove_2_lf → E37`):

```python
    # System 3 (new — manual $/sf, no auto-pricing dropdown)
    "system_3_sf":          "E22",   # square footage input
    "system_3_cost_per_sf": "C23",   # $/sf (defaults to =C18 if untouched)
    "cove_3_lf":            "E36",   # cove linear feet
    "system_3_labor_crew":  "A49",   # guys  (row 49 labor line)
    "system_3_labor_days":  "B49",   # days

    # System 4 (new)
    "system_4_sf":          "E26",   # square footage input
    "system_4_cost_per_sf": "C27",   # $/sf (defaults to =C18 if untouched)
    "cove_4_lf":            "E39",   # cove linear feet
    "system_4_labor_crew":  "A50",   # guys  (row 50 labor line)
    "system_4_labor_days":  "B50",   # days
```

**Notes for the dev:**
- These coordinates are only valid **after** Kyle applies Sections 2–3 to the template and the
  edited workbook is committed. The labor rows (A49/B49/A50/B50) and the I49/J49/I50/J50
  re-points must be in the template first, or writing A49/B49 alone won't flow into the totals
  (rows 49/50 already enumerate in A52/H64/F73, but their SF refs I49/J49 must point at
  E22/E36, not the stale `=H26`/`=H36`).
- Writing only SF (E22/E26) + cove (E36/E39) is enough for a correct **Total Base Bid**, because
  B45/D45 (Section 3) and the range-based D40 pull them in. Labor crew/days are optional refinements.
- Do **not** write to A22/A26-style dropdowns for systems 3/4 — there is no auto-pricing table
  behind them. Cost comes from C23/C27.
- The existing `compute_estimate_totals()` preview in `estimate_writer.py` mirrors B45 etc.;
  if you rely on it for the on-screen Screen-2 total, update its SF sum to include the System
  3/4 fields too (otherwise the live preview under-counts, though the saved xlsx will be right
  once Excel recalculates).

---

## 5. Verification checklist (do this in the copy before swapping it in)

Run through this top-to-bottom. If any step fails, undo and re-check the matching section.

**A. Baseline — empty systems add nothing**
- [ ] Open the edited copy with E22, E26, E36, E39 all **blank**.
- [ ] Note the current **Total Base Bid** (cell B16 / D88) and **$/SF** (D16 / C88).
- [ ] Confirm they match the ORIGINAL 2-system sheet's total for the same inputs. (Adding the
      systems while blank must change the total by **$0**.)

**B. System 3 raises the total**
- [ ] Type a test square footage into **E22** (e.g. `1000`).
- [ ] **Total Base Bid (D88 / B16) goes UP.** ✔
- [ ] **Total Square Footage (B45) increased by 1000** and now reads `=E20+E24+E22+E26`.
- [ ] **Floor-ONLY SF (B44)** also went up by 1000.
- [ ] **$/SF (C88 / D16)** recalculated (didn't error).
- [ ] Material Sub-Total (D40) rose (System 3's D23 material flowed in).

**C. System 3 cove**
- [ ] Type a test cove into **E36** (e.g. `200`).
- [ ] **Total Cove LF (D45)** increased by 200 and reads `=E34+E37+E36+E39`.

**D. System 4**
- [ ] Repeat B & C using **E26** (SF) and **E39** (cove). Total rises again; B45 and D45 both
      reflect System 4.

**E. Labor (optional rows)**
- [ ] Type a crew into **A49** (e.g. `3`) and days into **B49** (e.g. `5`).
- [ ] **Total Man Hours (H64)** and **Man Hour Budget (F73)** both rose. Labor dollars (D49)
      went from $0 to a real number, and the Base Bid rose accordingly.
- [ ] Clear A49/B49 again → man hours drop back, total returns to the Step-B value.

**F. Dropdowns (only if you added the optional Step 2e)**
- [ ] Click the System 3 dropdown cell (A23) — the list opens and shows the system names.
- [ ] Picking a name does **not** change the dollar total (expected — it's label-only).

**G. No errors anywhere**
- [ ] Ctrl+` (or Formulas → Show Formulas off) and scan: **no `#REF!`, `#VALUE!`, `#NAME?`,
      `#DIV/0!`** appear anywhere on the Epoxy tab. Pay special attention to B44, B45, D45,
      C88, D40, H64, F73.
- [ ] Press **F9** (or Formulas → Calculate Now) to force a full recalc; re-scan for errors.

**H. Cleanup**
- [ ] Clear all the test values (E22, E26, E36, E39, A49, B49, A50, B50) so the template ships
      blank.
- [ ] Confirm Total Base Bid is back to the Step-A baseline.
- [ ] Save. This file is now the new template — hand it to the dev to commit as
      `backend/templates/estimate_sheet_5.7.xlsx`.

---

### Quick reference — every cell touched

| Action | Cells |
|---|---|
| New SF inputs | E22 (Sys3), E26 (Sys4) |
| New cove inputs | E36 (Sys3), E39 (Sys4) |
| New material cost | B23/C23/D23 (Sys3), B27/C27/D27 (Sys4); cove material D32/D33 |
| Labor re-points | I49=`=E22`, J49=`=E36`, I50=`=E26`, J50=`=E39`; crew A49/B49, A50/B50 |
| Labels (optional) | F22, F26, F36, F39, E49, E50 |
| **Rollups to EDIT** | **B44, B45** → `=E20+E24+E22+E26`; **D45** → `=E34+E37+E36+E39` |
| Already correct (do NOT touch) | A52, H64, F73, D40, D43, D88, C88, B16, D16 |
