# Treadwell Proposal Tool

How Treadwell turns an inbound opportunity into a priced, customer-approved proposal for floor-coating and concrete-floor work, and tracks it until it is won, handed off or lost.

## Language

### Work

**Project**:
Everything Treadwell is pricing under one name and one address. A Project has at least one Scope.
_Avoid_: Draft, group, bid (as the unit)

**Scope**:
One separately priced, separately approvable piece of a Project, with its own Estimate and its own Proposal. An ordinary bid is a Project with a single Scope.
_Avoid_: Sibling, draft, room (a Scope may cover several rooms), option

**Work type**:
What kind of work a Scope's Base bid is: Polish, Epoxy, Combo (Epoxy and Polish together) or Gyp. Seal and Leveling are not Work types; they are only ever Options.
_Avoid_: Job type

### Pricing and paperwork

**Estimate**:
The internal pricing of one Scope, whatever file it is kept in. Several Scopes' Estimates may share one workbook.
_Avoid_: Takeoff, sheet

**Base bid**:
The main work a Proposal prices. Each Scope has exactly one; a Combo Base bid is Epoxy and Polish priced as one.

**Option**:
An extra priced on the same Proposal that the Customer may add to the Base bid. An Option is never approved on its own; anything approved on its own is a Scope.
_Avoid_: Alternate, add-on

**Scope of work**:
The part of a Proposal that describes the work Treadwell will do.
_Avoid_: Scope (on its own), scope notes

**Proposal**:
The customer-facing document for one Scope, sent to the Customer through the portal.
_Avoid_: Quote

**Bid**:
The tax-inclusive price a Proposal offers for its Scope.
_Avoid_: Quote, lump sum

### People and pipelines

**Customer**:
Whoever receives and approves a Proposal: the owner on a Direct job, the general contractor on a GC job.
_Avoid_: Client

**Lead**:
An inbound opportunity that has not yet become a Project.
_Avoid_: Prospect

**Direct**:
The pipeline for Projects where the Customer is the owner.

**GC**:
The pipeline for Projects where the Customer is a general contractor.

### Scheduling

**Project Analytics**:
Treadwell's per-job view of what the crews' schedule planned against what Raken recorded, and of labor against budget.
_Avoid_: Project Calendar (its old name), ops calendar, schedule (that is only its calendar tab)

**Plan vs Actual**:
The Project Analytics view that sets each job's plan from the Treadwell Projects calendar beside what Raken recorded for it.
_Avoid_: Dashboard, report

**Schedule**:
The Project Analytics tab that shows the Treadwell Projects calendar itself. Not a name for Project Analytics as a whole.
_Avoid_: Calendar view

**Duration**:
The stretch of days a job is booked for on the Treadwell Projects calendar, from its start date through its last day. Every bar on that calendar is one, coloured by its job's Work type.

**Deadline**:
The end of the last day of a job's Duration: the work must be finished by then. The calendar's Deadlines are the only deadlines a job has.
_Avoid_: Due date, end date

**Job number**:
The number a Project receives once it is going ahead, such as 26.125, used to name it on the Treadwell Projects calendar and in accounting.
_Avoid_: Project number, project #, job no.

**Mobilization**:
One continuous stretch of a crew on site for a job. A job may take several Mobilizations ("1st Mob", "2nd Mob").
_Avoid_: Mob (in writing), phase, visit

**Punch**:
A short Mobilization after the main work to fix or finish items on the Customer's punch list. A Punch always belongs to an earlier job.
_Avoid_: Touch-up

**Crew size**:
How many people a Mobilization puts on site each workday.
_Avoid_: Headcount, guys

**Foreman**:
The person running a job on site.
_Avoid_: Crew lead, lead (that is an inbound opportunity)

### Labor

**Workday**:
A Monday to Friday day inside a Duration. Weekends are never workdays.
_Avoid_: Business day, working day

**Budgeted hours**:
The labor hours a job is allowed: Raken's budget for the job. A job with no Raken budget has no Budgeted hours.
_Avoid_: Labor budget (the budget report's dollar column), allotted hours

**Planned hours**:
The labor hours the schedule implies for a job so far: each Mobilization's Workdays up to yesterday, times that Mobilization's Crew size, times the hours in a workday, added up. Compared against Actual hours to tell whether a job is on plan.
_Avoid_: Scheduled hours, expected hours

**Actual hours**:
The labor hours recorded against a job on Raken time cards so far.
_Avoid_: Spent hours, logged hours

**Days clocked in**:
The Workdays the calendar booked for a job so far on which Raken time cards recorded any hours for it. Set against the Workdays booked so far to tell whether a job is Behind.
_Avoid_: Days worked, attendance

**On site**:
How many people Raken time cards put on a job on an average day clocked in: the distinct people with hours on each of those days, added up, divided by the Days clocked in. Set against the planned Crew size.
_Avoid_: Headcount, guys, crew on site

**Projected total hours**:
Raken's own projection of the labor hours a job will take in all, across the work in its Raken budget. Treadwell never works it out itself, and a job with no Raken budget has none.
_Avoid_: Forecast, estimated hours

**Over/under**:
Budgeted hours minus Projected total hours for a job. Below zero, the job is projected to go over budget.
_Avoid_: Variance, gain or loss

**Behind**:
A job on which crews clocked in on fewer days than the calendar booked for it so far: a booked Workday was missed. Fewer hours than planned on its own does not make a job Behind. A job can be Behind and Over budget at once.
_Avoid_: Late, slipping

**Over budget**:
A job whose Projected total hours are above its Budgeted hours, so its Over/under is below zero.
_Avoid_: In the red, overrun

**On plan**:
A job linked to Raken that is neither Behind nor Over budget. A job whose Raken budget could not be read is not On plan: whether it is Over budget is unknown. A job with no Raken budget can be On plan.

**Not linked**:
A job on the calendar with no Raken project carrying its Job number, so there is nothing to compare its plan with.
_Avoid_: Unmatched, missing

**In Raken, not on the calendar**:
A Raken project with time cards in the last two weeks whose Job number belongs to no job on the Treadwell Projects calendar: crews are clocking in to work the schedule does not show. Listed apart in Plan vs Actual and never counted with the jobs.
_Avoid_: Orphan, unscheduled job

### Outcomes

Each outcome belongs to one Scope. A Project has no outcome of its own.

**Approved**:
The Customer has approved a Scope's Proposal.

**Won**:
A Scope that was marked won by hand, or approved with its deposit settled. A won job stays on the Active board until it is Handed off. Won is the stronger state: Approved alone does not make a Scope Won.

**Handed off**:
A won job that has been given to operations. This is the only outcome that takes a Won job off the Active board.

**Lost**:
A dead deal, whatever stage it died at. A job that was Won and then cancelled counts as Lost only. A Scope becomes Lost only when a person decides it, never because another Scope of its Project was Approved.
