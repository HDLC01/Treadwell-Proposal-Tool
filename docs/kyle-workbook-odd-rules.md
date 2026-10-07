# Odd rules in Kyle's estimate workbook

Written for Kyle. These are the places where the estimate workbook (`estimate sheet 5.7`) does something
surprising. The new estimating tool (v2) will copy every one of them exactly, so that its numbers match your
sheet to the dollar. This is not a bug report. Tell us which rules are on purpose and which you would like
fixed, and v2 changes only on your word.

**How we checked.** We ran your workbook through the same calculation engine the Estimate Review page uses.
We typed numbers into the places where a job's material, labor, tooling, travel and fees come in, answered
the job questions every way they can be answered, and wrote down what came out: about 2,000 test jobs
across the eleven tabs that price a job. Each rule below was confirmed against those recorded numbers, and
the figures quoted are from that run. The test jobs are kept in the tool's code, so if the workbook changes
they are run again.

**Reading a cell name.** `Polish!D78` is cell D78 on the Polish tab. The five Gyp tabs share one layout, so
where a rule is on a Gyp tab it is on all five unless it says otherwise.

## The eleven rules

### 1. The bond counts the taxes twice

Cells: `Polish!D78`, `Seal!D78`, `Seal (+Jnts)!D78`, `Epoxy!D84`, `Epoxy blank!D81`, `Leveling!D80`,
`Gyp (USG 1-8")!E83` (the other four Gyp tabs match the first).

The bond is a percentage of a total that adds up the sub-total, the markups, the sales tax, the remodel tax,
the "Total Taxes" line and the fees. "Total Taxes" is already the sales tax plus the remodel tax, so both
taxes are in the total twice.

Example: a Polish job with a $19,660 sub-total, $500 of fees, $250 of contingency, sales tax and a 7.975%
remodel tax. The taxes come to $3,232. A 2% bond comes to $894. If the taxes were counted once it would be
$829.

The bond rate is 0 in your template, so today this changes nothing. It matters only when someone types a
rate. v2 has no bond line yet. When it gets one, it will count the taxes twice like the sheet does.

### 2. Leveling divides lodging by 8 although its days are 10 hours

Cells: `Leveling!B61`, `Leveling!E42`, `Gyp (USG 1-8")!B64`, `Polish!B58`.

Nights of lodging are worked out from labor dollars: labor minus travel labor, divided by the labor rate,
divided by 8. The Leveling tab's days are 10 hours (cell E42 says "10 hour days"), but the 8 is typed into
the formula and never looks at E42. We changed E42 to "8 hour days" and the answer did not move.

Example: a crew of 3 for 5 days is 15 person-days. Leveling charges lodging for 18.75 nights, a quarter too
many. The Gyp tabs divide by 10 and Polish divides by 8 on 8 hour days, so both come out at 15.

### 3. Leveling's sub-total leaves out the labor escalation

Cells: `Leveling!D66`, `Leveling!D50`, `Leveling!D51`, `Polish!D64`.

With Prevailing Wage set to Yes, Leveling works out the 5% labor escalation (D50) and shows it. The
sub-total (D66) adds material, labor, tooling, travel and burden and never adds D50. The escalation reaches
the bid only through the burden, which is 12% of labor plus escalation. Polish, Epoxy and the other tabs add
the escalation into the sub-total.

Example: $7,000 of material, $6,000 of labor, $220 of tooling and $400 of travel, Prevailing Wage Yes. The
escalation is $300. The sub-total is $15,146. With the escalation added it would be $15,446.

### 4. Epoxy's gross profit leaves the fees out of the amount it subtracts

Cells: `Epoxy!D73`, `Polish!D67`, `Epoxy blank!D70`, `Leveling!D69`, `Gyp (USG 1-8")!E72`.

Gross profit is worked out as (cost + sales tax + fees) divided by (1 minus the GP rate), then the cost and
tax that went in are subtracted. Every tab subtracts the same things it divided, fees included. Epoxy (D73)
divides the fees but subtracts without them, so the fee comes back as extra gross profit on top of the fee
itself.

Example: the Epoxy tab with a $15,110 sub-total and $1,200 of fees shows a gross profit of $10,380. Subtracting
the fees the way the other tabs do would give $9,180. The difference is the fee.

### 5. Gyp's labor escalation is always 5%

Cells: `Gyp (USG 1-8")!C53`, `Gyp (USG 1-8")!E53`, `Gyp (USG 1-8")!D7`, `Polish!C46`.

On the other tabs the 5% is added only when Prevailing Wage is Yes (`=IF(D5="Yes",5%,0)`). On the Gyp tabs the
5% is a typed number (C53) and the Prevailing Wage answer never touches it. A Gyp job with $15,000 of labor
carries $750 of escalation whatever the answer. The other four Gyp tabs read the 5% from the first one.

### 6. Gyp's sound-mat shipping is waived once the order reaches a truckload

Cells: `Gyp (USG 1-8")!E40`, `Gyp (USG 1-8")!B36`, `Gyp (USG 1-8")!H36`.

Shipping is 20% on the gypsum bags and 10% on the other materials. The sound mat joins the 10% only while
the number of rolls (B36) is below a truckload (H36). At exactly a truckload the mat ships free.

Example: $10,000 of sound mat on the first Gyp tab, where a truckload is 280 rolls. At 279 rolls the sheet
charges $1,000 to ship it. At 280 rolls it charges $0. Each Gyp tab has its own truckload size: 280, 260,
208, 384 and 448 rolls.

### 7. Gyp's bags are fractional and the sand is worked out from them

Cells: `Gyp (USG 1-8")!B23`, `Gyp (USG 1-8")!B24`, `Gyp (USG 1-8")!B25`, `Gyp (USG 1-8")!H33`,
`Gyp (USG 1-8")!B33`.

Bags of gypsum are the square feet divided by the square feet one bag covers, plus 3% waste. They are never
rounded up, so 1,000 SF of soft surface is 25.75 bags, not 26. The sand is then worked out from the total of
those fractional bags: pounds of sand per bag times the bags, divided by 2,000, plus 10% waste. With 1,000,
2,000 and 500 SF in the three areas the sand comes to 8.68 tons.

### 8. Leveling charges an hour of travel even on a local job

Cells: `Leveling!A48`, `Leveling!B48`, `Leveling!D48`, `Epoxy!B52`, `Polish!B44`.

The Leveling tab ships with 1 typed into the travel hours cell (B48), and nothing there looks at the Local
answer. The travel line is person-days times those hours times the travel rate ($33.66 an hour). Person-days
(A48) is not a head count. It is the guys times the days of every crew row in the labor table above it, added
up: 3 guys for 4 days and 2 guys for 3 days is 18 person-days.

The tab ships with one crew row, 6 guys for 1 day, so a job next door carries 6 person-days: $201.96 of travel
labor. A crew of 6 for 5 days is 30 person-days, and the same local job carries $1,009.80. It goes into Install
Labor (D49). Epoxy and Polish ship with 0 travel hours.

### 9. Leveling's overage is taken on the powders only

Cells: `Leveling!D38`, `Epoxy blank!D38`.

Discount / Overage (B38, 0 as shipped) is applied to the powder rows only (D21 to D27). A 10% overage on $1,000
of powder is $100. The same 10% on $1,000 of sand and aggregate is $0. The Epoxy blank tab takes its 6% on
every material row: $60 on $1,000 of liquids or of cove.

### 10. The shipping tiers include the edge, the gross profit bands do not

Cells: `Epoxy!B42`, `Epoxy!B73`, `Epoxy blank!B39`, `Epoxy blank!B70`, `Leveling!B39`, `Leveling!B69`.

Shipping and material escalation is 15% when the material is $5,000 or less, 11% up to $10,000 and 9% above
that. Gross profit is 52% below a $6,500 sub-total and 45% from $6,500. So exactly $5,000 of material is still
on the 15% tier, but exactly $6,500 of sub-total is already on the 45% band. The tiers count their edge and the
bands do not.

One result: $5,000 of material pays $750 to ship and $5,001 pays $551, because the whole order drops to the
11% tier.

### 11. The cove aggregate price follows System 1, even in System 2's block

Cells: `Epoxy!AF126`, `Epoxy!AF131`, `Epoxy!AF136`, `Epoxy!AF142`, `Epoxy!AF148`, `Epoxy!AF153`, `Epoxy!F126`.

System 2's cove blocks price the aggregate with `IF($A$22=$R$189, Q28_40s, ... , Silica)`. `$A$22` is System 1's
choice. System 2's own choice (`$A$26`) is never looked at. So when System 2 is one of the quartz systems and
System 1 is not, System 2's cove aggregate is priced as silica.

Example with 100 pounds of aggregate, quartz at $3 and silica at $1: System 2 is the quartz system and System 1
is something else. The sheet prices it at $100. Following System 2 it would be $300.

## Other things we found

### The values saved in the template are from an older labor rate

Cells: `Polish!C37`, `Polish!C38`, `Leveling!C44`, `Leveling!C45`.

The template file stores the last answer Excel calculated next to each formula. Those answers were calculated
with a labor rate of $32.20 on five tabs (Polish, Epoxy, Epoxy blank, Seal and Seal (+Jnts)) and $32.52 on six
(Leveling and the five Gyp tabs). The cells now hold $33 and $33.66 (Seal (+Jnts) reads its rate from Seal). So a
number read from the file without recalculating is a few dollars off what Excel shows after a recalculation. The estimating tool always calculates, so it is not affected. For our check we put the old
rates back for a moment, and every one of the roughly 17,000 saved answers in the workbook then matched the
engine to the cent.

### On the Gyp tabs the Hard Bid question does nothing

Cells: `Gyp (USG 1-8")!B7`, `Gyp (USG 1-8")!B73`, `Gyp (USG 1-8")!E73`.

The Hard Bid? question is there (B7), but the hard-bid rate (B73) is empty, so the line (E73) is always 0.
Answering Yes or No changes nothing on any Gyp tab.

### Gyp (FR) keeps its own answers; the other Gyp tabs follow the first

Cells: `Gyp (FR)!B5`, `Gyp (FR)!B8`, `Gyp (USG N12ULTRA)!B5`, `Gyp (USG N12ULTRA)!B8`.

Gyp (USG N12ULTRA), Gyp (USG N25 1-4") and Gyp (GWorx SC190) read Local, Taxable, Prevailing Wage and Remodel Tax
from the first Gyp tab. Gyp (FR) has its own typed Local and Taxable answers, so changing Local on the first Gyp
tab does not move it.

### Seal's gross profit ladder has one more rung than Polish's

Cells: `Seal!B67`, `Polish!B67`.

Polish and Seal share the same ladder up to $32,500. Polish pays 30% from there. Seal pays 30% up to $42,500 and
28% from $42,500.

## What we need from you

For each rule above: is it on purpose? If yes, v2 keeps it. If it is a leftover you would like fixed, say so and
we will fix it in the workbook and in v2 together, so the two keep matching.
