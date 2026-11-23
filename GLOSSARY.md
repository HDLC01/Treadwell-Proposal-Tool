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

**Last week**:
The Monday to Friday of the week before this one, in Central time. Plan vs Actual sets its Planned hours against its Actual hours, each added up over the jobs linked to Raken: the two figures for one window across those jobs, not one job so far.
_Avoid_: Past 7 days, the last five workdays

**Summary strip**:
The row above the Plan vs Actual list: how many jobs are On plan, Behind, Over budget and Not linked (a job Behind and Over budget is counted under both), Last week's hours, and the Budgeted hours and Projected total hours added up over the linked jobs with a Raken budget. Pressing a count shows only its jobs. Until Raken is read, the counts are not known.
_Avoid_: Dashboard, KPI bar, scorecard

**Daily refresh**:
The "Refresh now" step run by the tool itself once a day at 5:00 AM Central: it reads the Treadwell Projects calendar and Raken. A run that fails keeps the last good numbers on screen with their "as of" time.
_Avoid_: Sync, cron job, nightly import

**Snapshot**:
One listed Plan vs Actual row's figures (a Project, or its Punch) as a good refresh worked them out, kept once per row per day in Central; a later good refresh the same day replaces it. Kept so trends can be shown later.
_Avoid_: History, backup, log

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

**BD CRM**:
The business-development section of the proposal tool, where salespeople keep their contacts and work their weekly calls. It is in beta.
_Avoid_: BD tool, bd.wetreadwell.com (its old separate home), Troy's list

**BD role**:
What a person can do inside the BD CRM: salesperson, assistant, manager, admin or super admin. It is separate from whether they can see the BD CRM at all.
_Avoid_: BD permission, BD access

**BD login**:
A person's account inside the BD CRM, one row in its people table, which carries their BD role. It is active or turned off; a turned-off BD login opens nothing in the BD CRM. A proposal-tool admin has no BD login unless the BD CRM's people table gives them one, and only a BD super admin changes an admin's BD login.
_Avoid_: BD user, BD account (that is a company)

**BD account**:
A company Treadwell is developing business with, holding every person we can reach there. Several people at one company are one BD account.
_Avoid_: Customer (that is who approves a Proposal), client, company record

**BD contact**:
One person under a BD account, with the name, phone and email a salesperson reaches them by.
_Avoid_: Lead (that is an incoming request for a bid), prospect

**Account owner**:
The salesperson who owns the most BD contacts at a BD account, shown on its Contacts row with "+N" when N other salespeople own someone there too. Contacts owned by a manager or an admin are counted at the account but do not make that person its owner. On a tie it is whichever of them logged the latest live talk at the account.
_Avoid_: Account manager, main contact (that is a person at the company)

**Last live talk**:
The latest call where someone talked, meeting or hosted event with anyone at a BD account, BD or maintenance contact. Voicemails, missed calls, emails, texts and notes never count.
_Avoid_: Last contact, last touch, last activity

**Possible duplicate**:
A BD contact who may be the same person as one already in the BD CRM, because they share a company name (once cleaned of endings such as LLC), an email or a phone number. Add contact warns about them before saving; the new contact is saved anyway, flagged with the first match, and an assistant or BD admin clears the flag.
_Avoid_: Duplicate contact, likely duplicate (that is two BD accounts that may be one company)

**Likely duplicate accounts**:
Two BD accounts whose names are the same once cleaned of endings such as LLC, of punctuation and of short forms such as "Const.", so they may be one company. An assistant or BD admin merges them into one, or keeps them separate for good. A phone or email domain they share is shown as a hint, but never makes a pair on its own.
_Avoid_: Possible duplicate (that is one person), duplicate company

**Merged account**:
A BD account whose people were all moved into another BD account by a merge, each keeping their owner. It is kept, marked with who merged it and when, and hidden from the Contacts page, its search and Add contact, and nobody can edit it. Every merge can be undone, which brings it back as it was. The code and its event log call this a company merge (company_merged, merge_companies), the database table's word.
_Avoid_: Deleted account, duplicate account

**Cut-over copy**:
The one command that moves BD's data from the old BD CRM's own database into the proposal tool on cut-over day, and back again for a rollback. It proves with each table's row count and checksum that nothing was lost, and that the old database did not change while it ran.
_Avoid_: Migration (that is a change to the schema), import (that is a Workbook import), sync

**Cut-over record**:
The file the cut-over copy writes when it moves BD's data in: each table's row count and checksum in the old database, and the time. The way back first checks the old database still matches it. It holds no contact's details.
_Avoid_: Backup (that is a database dump), log

**Carried BD-only state**:
What the proposal tool knows about BD accounts that the old BD CRM has no place for: which accounts were merged away, into which, by whom and when, and which pairs were kept separate. A rollback saves it next to the old BD CRM's data, where the old app never looks, and the next move back into the proposal tool puts it back. An account that gained people in the old app meanwhile is not marked merged again, so nobody is hidden; it is listed instead. The database calls it bd_carry.
_Avoid_: Backup, leftover data

**Logged entry**:
A call, voicemail, meeting, hosted event, email, text or note in a BD contact's history. The person who logged it can change its words; a BD admin can change or delete any.
_Avoid_: Activity, interaction (the API's word for it), log

**Archived contact**:
A BD contact taken off every list, the Weekly 10 included, with their history kept. Restoring them puts back what the archive closed on this week's list or a later one.
_Avoid_: Deleted contact, inactive contact

**Maintenance account**:
A company Treadwell already works for, kept in touch with a follow-up every 120 days instead of the weekly BD calls. A whole BD account becomes one, or goes back, with every person at it. The code and its event log call this a company move (company_moved, move_company), the database table's word; a company move moves a BD account.
_Avoid_: maintenance contact (that is one person at it), customer

**This Week**:
A salesperson's BD home page: their Weekly 10, their Maintenance follow-ups that are due, any companies from Give Me 10 More, and their pace for the year. It shows one row per company, which opens to the people there that the salesperson owns, with the person to call first on top. A BD manager or admin chooses whose week to look at; an assistant's BD home is Contacts instead.
_Avoid_: Home page, dashboard, the list

**Contacts page**:
The BD CRM page that lists BD accounts on two tabs, BD and Maintenance, each company row opening to its people. A search opens the account a person is at, on the right tab, with them highlighted. A company's menu makes it a Maintenance account or moves it back. It is an assistant's BD home.
_Avoid_: Contact list, people list, address book

**Weekly 10**:
The ten companies a salesperson is given to call in one Monday-to-Sunday week, five new and five follow-ups, best score first. A company takes at most one of the ten, led by its best-scoring person, and it is new only while nobody there has had a live talk. A row is done once a call, voicemail, meeting or hosted event is logged with anyone there. "N of 10 done" counts these ten companies only, and the list never refills itself when one is done or taken off.
_Avoid_: The 10, weekly list, weekly-10, Troy's list

**Friday batch**:
How a Weekly 10 is made: every Friday at 4 PM the BD CRM builds each salesperson's list for the next week, with their due Maintenance follow-ups above it, and closes what was left open on this week's list. A BD admin can also make one by hand from This Week. A salesperson has one Friday batch a week.
_Avoid_: Weekly run (that is the job that makes it), weekly list

**Give Me 10 More**:
The This Week button that adds up to ten more companies, the next by score, to this week's list, after the Weekly 10. It never changes "N of 10 done", and it never adds a company already on this week's lists in any state, or one where anyone was tried in the last 3 days. A company made a Maintenance account can also leave a small list of the same kind on This Week holding only pinned maintenance follow-ups; that list is not a Give Me 10 More, and its follow-ups show under "Due now".
_Avoid_: Extra 10, ten more, refill

**Maintenance follow-up**:
A task on This Week for one person at a Maintenance account whose follow-up is due. The follow-ups of one company are one row under "Due now", above the Weekly 10 and outside it, and "Due now: N" counts companies. Each stays until a call, meeting, email or text is logged for that person, and the row stays while anyone on it is still due.
_Avoid_: Pinned task, maintenance task

**Miss**:
A call to someone at a BD account that reached nobody: a voicemail, or a call nobody answered. Misses count for the whole BD account, whoever was called, by their Central date, and go back to 0 after a live talk with anyone there. A BD account's misses are the tries part of its score.
_Avoid_: Missed call (that is the "Send follow-up" card on one contact), attempt, try (that also counts answered calls)

**BD Admin page**:
The BD CRM's own Admin page, where a BD admin sets each person's BD login and BD role and the BD settings, and an assistant or BD admin handles Unmatched calls and sees past Workbook imports. It is separate from the proposal tool's Admin page: neither changes what the other holds. Only a BD admin has it in the sidebar; an assistant reaches it from the Contacts page.
_Avoid_: Admin (on its own, that is the proposal tool's), settings page

**Workbook import**:
Bringing BD contacts in from a workbook (.xlsx) or a .csv, from the Contacts page (a salesperson, an assistant or a BD admin) or the BD Admin page. A practice run shows what the file would add or change and keeps nothing; Import now keeps it. Importing the same file again keeps the edits made in the BD CRM since.
_Avoid_: Upload, sync, dry run (the API's word for a practice run)

**Unmatched call**:
A call or text the phone system recorded whose number matched no BD contact. An assistant or BD admin puts it on a BD contact's history or dismisses it. The pages call them Unknown calls, as BD's did (the Contacts page shows the newest three and links to the BD Admin page to attach them); the API and the code say unmatched.
_Avoid_: Missed call (that is one nobody answered), Not linked (that is a job with no Raken project)

**Potential BD Contacts**:
The monthly review of people on the proposal tool's recent Direct quotes who are not BD contacts yet, each added to the BD CRM or set aside. The page is in the BD CRM; the review itself is not built yet.
_Avoid_: Candidates (the API's word), review list, leads
