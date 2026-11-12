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

**Project Calendar**:
The schedule of crews on Treadwell's jobs, and the deadlines those jobs must meet.
_Avoid_: Schedule, ops calendar

**Duration**:
The stretch of days a job is booked for on the Project Calendar, marked in red.

**Deadline**:
The last day of a job's Duration: the day the work must be finished.
_Avoid_: Due date, end date

**Job number**:
The number a Project receives once it is going ahead, such as 26.125, used to name it on the Project Calendar and in accounting.
_Avoid_: Project number, job no.

**Mobilization**:
One continuous stretch of a crew on site for a job. A job may take several Mobilizations ("1st Mob", "2nd Mob").
_Avoid_: Mob (in writing), phase, visit

**Punch**:
A short Mobilization after the main work to fix or finish items on the Customer's punch list.
_Avoid_: Touch-up

**Crew size**:
How many people a Mobilization puts on site each workday.
_Avoid_: Headcount, guys

**Crew lead**:
The person in charge of a crew on site, named on its Mobilization.
_Avoid_: Lead (that is an inbound opportunity), foreman

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
