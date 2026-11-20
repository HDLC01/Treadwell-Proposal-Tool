# BD CRM API contract

> Moved here from the BD CRM repo for the move into the proposal tool (#802). #805 brought the ground
> rules and the **core objects** that `backend/bd/serialize.py` builds and
> `backend/tests/test_bd_serialize.py` checks against the JSON examples below; #806 to #809 moved
> BD's routes under `/api/bd/`. Since #809 this lists **every** BD route, the unbuilt ones too:
> `backend/tests/test_bd_contract_routes.py` checks each one is registered and nothing else is,
> `backend/tests/test_bd_contract_json.py` that the BD pages call only these, and
> `backend/tests/test_bd_authz_matrix.py` that each route lets in exactly the BD roles its heading
> names.

The BD pages and the backend agree on **these shapes**. A change to this file is a change to both
sides.

Every example below is real JSON (a test parses each fenced `json` block). The names, `555-01xx`
numbers and `example.com` emails are made up.

## Ground rules

- **Base path** `/api/bd`. JSON in, JSON out, UTF-8. BD's routes sit behind the proposal tool's own
  sign-in and permission gate; BD adds its own role on top (below).
- **Dates** are ISO dates `YYYY-MM-DD`. **Timestamps** are ISO 8601 with the Central offset the moment
  had, e.g. `2026-10-30T16:00:00-05:00` (CDT) and `2026-11-04T10:00:00-06:00` (CST). The server stores
  UTC; it renders in `America/Chicago`.
- **"Today", "this week", "this year"** are always Central (`America/Chicago`), never the server clock's
  zone. A week is **Monday to Sunday**. The Friday batch runs Friday at or after 16:00 Central for the
  week that starts the next Monday.
- **Ids** are integers, except `project_id` (the proposal tool's draft uuid).
- **Lists** return `{ "ok": true, "items": [...], "total": N }`. Single objects return
  `{ "ok": true, "<name>": {...} }`. `limit` (default 100, max 500) and `offset` page a list.
- **Errors** always look like this, with an HTTP status that matches:

```json
{ "ok": false, "error": "not_found", "message": "That contact does not exist." }
```

| HTTP | `error` | When |
|---|---|---|
| 400 | `bad_request` | Malformed JSON or a field of the wrong type. FastAPI's 422 is rewrapped into this shape with `"fields": {"name": "plain sentence"}`. |
| 401 | `unauthenticated` | Not signed in to the proposal tool. The proposal tool's gate answers this one in its own shape, `{ "ok": false, "error": "<sentence>" }` with no `message`; a page shows `error`. |
| 403 | `forbidden` | Signed in but the role may not do this. |
| 404 | `not_found` | Unknown id. |
| 409 | `conflict` | The action is not possible in the current state (task already done, candidate already added, batch already built this week, send outside 8 am–6 pm Central). |
| 429 | `rate_limited` | Too many AI calls in a minute. |
| 503 | `unavailable` | The BD CRM is not turned on (`BD_ENABLED`), BD's database is not up to date or not answering, a route is not built yet, or AI or the phone provider is down. AI routes return a fallback instead of this where they can. |

### The one counting rule

A **meaningful touch** (`counts_as_touch: true`) is only:
- `kind: "call"` with `outcome: "answered"` or `"meeting_set"` (a live conversation),
- `kind: "meeting"` (lunch, coffee, job walk, site visit),
- `kind: "hosted"` (a hosted event, e.g. sim suite golf).

`email`, `sms`, `note`, `voicemail` and a call with `outcome: "no_answer"` **never** count. The server
sets `counts_as_touch`; a client cannot override it. Pace, cadence, "last live" and analytics all
read only touches.

### Roles

| Role | Who | May |
|---|---|---|
| `salesperson` | Troy (Greg as co-owner) | Own week and tasks, log interactions, confirm next actions, send follow-ups, add and edit contacts, import a workbook (everything it adds is theirs). |
| `assistant` | Marisol | Add, edit and import contacts, resolve duplicates (clear a duplicate flag, merge), review candidates, attach unmatched calls (her part of the Admin page: unmatched calls and import history). Logs notes. **No** weekly list, **no** sending, **no** analytics, **no** batches. |
| `manager` | Will, Kyle | Read everything, analytics, see any owner's week, and change how often a contact is followed up (a BD contact's cadence override, a maintenance contact's frequency). Nothing else on a contact. |
| `admin` | Hanz | Everything, plus users, settings, run the batch, telephony. (`super_admin` is an admin who can also add and change other admins; Hanz is the super admin.) |

"any" below means any signed-in role. A route marked salesperson is also open to admin.

## Core objects

Every object is defined once here; routes refer to them by name.

### UserRef and User

`UserRef` is the compact form used inside other objects: `{ "id": 1, "name": "Troy" }`. A co-owner
named in the workbook who has no login yet has `"id": null` until an admin creates the user.

```json
{
  "id": 1,
  "name": "Troy",
  "email": "troy@example.com",
  "role": "salesperson",
  "active": true,
  "last_seen_at": "2026-11-04T08:12:00-06:00"
}
```

`role`: `salesperson` | `assistant` | `manager` | `admin` | `super_admin`.

### Company

```json
{
  "id": 10,
  "name": "Prairiefold Foods",
  "city": "Topeka, KS",
  "industry": "Food Processing",
  "contact_count": 1,
  "created_at": "2026-01-12T09:00:00-06:00"
}
```

`name` is stored trimmed (leading spaces and non-breaking spaces removed); the server also keeps a
`normalized_name` (lower case, punctuation and "inc/llc/co" dropped) for duplicate checks. It is not
sent to the browser.

### Contact

The central object. One row per person at a company. Fields marked *derived* are computed by the
server from interactions (the `contacts_summary` view) and are read-only.

```json
{
  "id": 10,
  "company": { "id": 10, "name": "Prairiefold Foods" },
  "name": "Victor Almeida",
  "title": "Sanitation Manager",
  "email": "victor.almeida@prairiefoldfoo.example.com",
  "phone": "816-555-0110",
  "phone_e164": "+18165550110",
  "city": "Topeka, KS",
  "industry": "Food Processing",
  "lead_source": "Current Account",
  "stage": "Proposal",
  "category": "bd",
  "account_type": null,
  "owner": { "id": 1, "name": "Troy" },
  "co_owner": null,
  "frequency_per_year": 12,
  "cadence": "monthly",
  "cadence_source": "override",
  "cadence_override": "monthly",
  "cadence_override_until": "2026-11-04",
  "confirmed": true,
  "importance": 3,
  "next_step": "Call back with the coving price",
  "next_step_date": "2026-11-05",
  "promised_date": "2026-11-05",
  "last_quote_date": null,
  "last_live_at": "2026-10-22T11:20:00-05:00",
  "last_attempt_at": "2026-10-22T11:20:00-05:00",
  "last_followup_at": "2026-10-22T11:20:00-05:00",
  "attempts_since_live": 0,
  "touches_this_year": 4,
  "next_due_date": "2026-11-21",
  "cadence_status": "on_track",
  "maintenance_due_date": null,
  "maintenance_due": false,
  "duplicate_of": null,
  "source": "workbook",
  "tags": ["food-safe"],
  "notes": "",
  "created_at": "2026-01-12T09:00:00-06:00"
}
```

| Field | Type | Notes |
|---|---|---|
| `company` | `{id, name}` | Required. |
| `phone` | string\|null | As typed or imported (`816.555.0110`, `913-555-0117`). |
| `phone_e164` | string\|null | *derived* `+1XXXXXXXXXX`; used to match calls. |
| `industry` | string\|null | One of `settings.industries`. |
| `lead_source` | string | `Current Account` \| `DSBC Sales` \| `Website Lead` \| `Other/Misc`. |
| `stage` | string\|null | `Meeting Set` \| `Met` \| `Proposal` \| `Won` (workbook values). |
| `category` | string | `bd` \| `maintenance`. |
| `account_type` | string\|null | Maintenance only (workbook "Account Type"). |
| `owner` / `co_owner` | UserRef / UserRef\|null | Workbook `Troy/Greg` → owner Troy, co-owner Greg. |
| `frequency_per_year` | int | Live touches needed a year. **BD: derived** from `cadence` (`weekly` 52, `monthly` 12, `quarterly` 4); it cannot be set on a BD contact (see PATCH). **Maintenance: stored**, default 3, 1 to 52. |
| `cadence` | string\|null | *derived* BD only: how often to follow up, `weekly`, `monthly` or `quarterly`. The active override, else the global `settings.bd_cadence`. `null` for maintenance. |
| `cadence_source` | string\|null | *derived* BD only: `override` (a per-contact override is active) or `global`. `null` for maintenance. |
| `cadence_override`, `cadence_override_until` | string\|null, date\|null | The per-contact override, "follow up every `weekly`\|`monthly`\|`quarterly` until this date": both set or both `null`. Shown as stored, also after the date has passed. It is **active while `cadence_override_until` is today or later** (the last day counts); after that the contact falls back to the global cadence and `cadence_source` is `global`. |
| `confirmed` | bool | Still the right person? Unconfirmed contacts stay on the list. |
| `importance` | int | 1 normal, 2 important, 3 key account. |
| `next_step`, `next_step_date` | string\|null, date\|null | The confirmed next action. |
| `promised_date` | date\|null | A date we promised the customer ("call me next month"). Cleared when a touch happens on or after it. |
| `last_quote_date` | date\|null | Latest quote from the proposal tool for this contact. |
| `last_live_at` | timestamp\|null | *derived* latest touch. |
| `last_attempt_at` | timestamp\|null | *derived* latest call or voicemail, any outcome. |
| `last_followup_at` | timestamp\|null | *derived* latest logged follow-up: a call (any outcome), voicemail, meeting, hosted event, email or text, dated today or earlier. **A note is not one.** |
| `attempts_since_live` | int | *derived* calls/voicemails with no live talk since `last_live_at`. |
| `touches_this_year` | int | *derived* touches in the current Central calendar year. |
| `next_due_date` | date\|null | *derived* `last_live_at` (its Central date) + `floor(365 / frequency)` days (4 a year: + 91, 12: + 30, 52: + 7), where `frequency` is the derived `frequency_per_year`; maintenance: + 120 days. Null if never reached. |
| `cadence_status` | string | *derived* `never` (no touch ever) → `complete` (touches this year ≥ frequency; **maintenance: ≥ 3, whatever its frequency**) → `behind` (`next_due_date` is before today) → else `on_track`. Checked in that order. |
| `maintenance_due_date` | date\|null | *derived* maintenance only: the Central date of `last_followup_at` + 120 days. `null` for BD and for a maintenance contact never followed up. |
| `maintenance_due` | bool | *derived* `true` for a maintenance contact never followed up, or whose `maintenance_due_date` is today or earlier; always `false` for BD. An email or text clears it as a call does. |
| `duplicate_of` | object\|null | `{contact_id, name, company, reason}`. A flag, not a block. Set when a contact is added, or when an edit changes its company, email or phone to match another; cleared by the assistant or an admin (`PATCH {"duplicate_of": null}`) or by a merge. |
| `source` | string | `workbook` \| `manual` \| `proposal_tool` \| `import`. |
| `tags` | string[] | Free text chips. |

### ContactCompact

Used inside tasks and lists that need just enough to act (call button, chips):

```json
{
  "id": 2,
  "name": "Marcus Ebner",
  "title": "Facilities Manager",
  "company": { "id": 2, "name": "Kestrelwood Gear Co." },
  "phone": "816.555.0102",
  "phone_e164": "+18165550102",
  "email": "marcus.ebner@kestrelwoodgea.example.com",
  "category": "bd",
  "confirmed": true,
  "lead_source": "DSBC Sales",
  "last_live_at": "2026-09-15T15:30:00-05:00",
  "cadence_status": "on_track"
}
```

### Interaction

Every call, voicemail, meeting, email, text, note and hosted event. The contact timeline is these,
newest first.

```json
{
  "id": 1073,
  "contact_id": 17,
  "contact": { "id": 17, "name": "Megan Tully", "company": { "id": 17, "name": "Halvorsen & Pike Contractors" } },
  "kind": "call",
  "direction": "out",
  "counts_as_touch": true,
  "occurred_at": "2026-11-02T09:20:00-06:00",
  "duration_s": 480,
  "outcome": "answered",
  "summary": "Spring bid list is out in January. Wants us on three bids.",
  "transcript": "Troy: Hi Megan, it's Troy at Treadwell. You said to check on the spring bid list.\nMegan: Yes, thanks for calling. The list goes out in January.",
  "recording_url": "https://example.com/recordings/AC002701.mp3",
  "provider": "quo",
  "external_id": "AC002701",
  "user": { "id": 1, "name": "Troy" }
}
```

| Field | Values |
|---|---|
| `kind` | `call` \| `voicemail` \| `meeting` \| `email` \| `sms` \| `note` \| `hosted` |
| `direction` | `out` \| `in` \| `null` (meetings, hosted, notes) |
| `outcome` | calls: `answered` \| `no_answer` \| `meeting_set`; voicemails: `voicemail`; everything else `null` |
| `counts_as_touch` | server-set, see the counting rule |
| `duration_s` | seconds or `null` |
| `transcript`, `recording_url` | from the phone provider, else `null` |
| `provider` | `manual` (typed in) \| `workbook` (imported) \| `quo` \| `resend` \| other provider names later |
| `external_id` | the provider's id; `(provider, external_id)` is unique so replays never double-log |

### Task, TaskBatch

A task is one slot in a weekly 10. **Tasks have no due date and can never be overdue.**

```json
{
  "id": 401,
  "batch_id": 41,
  "contact": {
    "id": 2,
    "name": "Marcus Ebner",
    "title": "Facilities Manager",
    "company": { "id": 2, "name": "Kestrelwood Gear Co." },
    "phone": "816.555.0102",
    "phone_e164": "+18165550102",
    "email": "marcus.ebner@kestrelwoodgea.example.com",
    "category": "bd",
    "confirmed": true,
    "lead_source": "DSBC Sales",
    "last_live_at": "2026-09-15T15:30:00-05:00",
    "cadence_status": "on_track"
  },
  "kind": "followup",
  "reason": "Promised a call by Fri, Nov 6.",
  "reasons": ["Promised a call by Fri, Nov 6"],
  "score": 75,
  "status": "open",
  "done_at": null,
  "snoozed_until": null
}
```

- `kind`: `maintenance` (a **due** maintenance contact: `category` is `maintenance` and
  `maintenance_due` is true) | `new` (never had a live talk: `last_live_at` is null) | `followup`
  (everyone else). Whether the contact is confirmed does **not** change the kind: an unconfirmed
  contact gets +8 points and a "Needs confirming" reason instead (`BDCore.taskKind`, and the
  `unconfirmed_with_live_talk_is_followup` case in `backend/tests/test_bd_core_js.py`).
- **A maintenance task is pinned.** It is on the list only while the contact's follow-up is due
  (`maintenance_due`); it is made first in every Friday batch, sits above the business-development
  picks, is **not** one of the 10 (see WeekView `done_count`/`total`/`due_count`), and **cannot be
  taken off by hand** while the contact is still due: the task's snooze and done routes
  answer `409` on it. It closes when a call (any outcome), voicemail,
  meeting, hosted event, **email or text** is logged for the contact (a note does not) **and that
  leaves the contact no longer due**: it closes on this week's list **and on a later week's** (the
  Friday build has already made next week's, so a text sent on the Saturday clears it there too).
  An entry dated so long ago (or in the future) that the contact is still due closes nothing. A
  maintenance task whose contact is no longer due (a stale one: reopened after its follow-up, or the
  contact became a BD contact) is not pinned and can be skipped or marked done like any task. When a
  contact changes hands (an edit with a new `owner_id`) the previous owner's open
  maintenance tasks for it are snoozed to the following Monday, so the pin sits on one list; the new
  owner gets it at the next Friday build or from Give Me 10 More. The rollover still snoozes last
  week's open one, and the next Friday's build makes a new one while the contact is still due. `not-right-person`, archiving and
  `reopen` work on it as on any task. Its `score` is the normal priority score; its `reasons` start
  with why it is due, then the scored reasons: `No follow-up logged yet` (never followed up) |
  `Follow-up due today` | `Follow-up was due Fri, Nov 6` (the `maintenance_due_date`); `reason` is
  still the top two of `reasons`.
- `reason`: the plain-English "why this one", shown as a chip on the card (top two reasons).
  `reasons` is the full list for a tooltip.
- `score`: the priority points (see the build plan's factor table; `BDCore.scoreContact` is the
  reference). Shown to managers only. The cadence part is `min(40, round(30 × days_since_live ÷ interval))`
  rounded half up, where `interval` is the **unfloored** `365 / frequency` (91.25 days for 4 a year) or
  120 for maintenance; only `next_due_date` floors it.
- `status`: `open` | `done` | `snoozed`. Unfinished tasks are closed as `snoozed` when the next Friday
  batch is built, and the contact is simply scored again. Nothing carries over as overdue.
  Precisely (the rollover, `api.js runWeekly` and `backend/weekly.py`): building the Friday batch
  for the week of Monday W turns every `open` task of that salesperson in any batch of an earlier
  week (Friday or Give Me 10 More), and with `force` every open task of every Friday batch of week W
  (the one being replaced, and one replaced earlier whose task was reopened since), into `snoozed`
  with `snoozed_until` = W. It happens when the batch is built (Friday 16:00 for next
  week), not on Monday. `done` tasks never change.

TaskBatch: `{ "id": 41, "kind": "friday", "owner": {"id": 1, "name": "Troy"}, "week_start": "2026-11-02", "generated_at": "2026-10-30T16:00:00-05:00" }`.
`kind`: `friday` | `ten_more`.

How a batch is filled (not AI; `BDCore.rankContacts` / `pickWeekly` / `pickNext`, ported to
`backend/weekly.py`): every contact the salesperson owns and has not archived is scored; the ones
the rules leave out (archived, already on this week's list, tried in the last 3 days, and a
**maintenance contact that is not due yet**, reason "maintenance, not due yet", checked last) are
dropped, in a Friday batch and in Give Me 10 More alike, so a maintenance contact is on a list only
when due. The rest are ranked in two tiers: first the **due maintenance** contacts, most overdue
first (`maintenance_due_date` ascending, a contact never followed up before any date, then contact
id), then everyone else (business development) by score, highest first, then by contact id.

A Friday batch makes one `maintenance` task per due maintenance contact first, **then** the BD split:
the best `weekly.new_count` `new` and the best `weekly.followup_count` `followup` among the BD
contacts only; when one side is short the other fills its slots (new first), and the BD picks are
listed best first. So the batch is the maintenance tasks followed by the BD picks (task ids ascend in
that order), and with more than 10 maintenance contacts due the batch simply grows (maintenance count
plus the BD picks). "Give Me 10 More" takes the top `n` of the same ranking, so a contact that fell
due mid-week heads the extra 10 as a `maintenance` task. A batch is made even when nobody is left
(`tasks_created: 0`). There is one Friday batch per salesperson and week; a forced re-run keeps the
old one (still listed, no longer counted in `done_count`/`total`) and adds the new one after it.

### WeekView

What the This Week page draws.

```json
{
  "week_start": "2026-11-02",
  "week_end": "2026-11-08",
  "owner": { "id": 1, "name": "Troy" },
  "batch": { "id": 41, "kind": "friday", "owner": { "id": 1, "name": "Troy" }, "week_start": "2026-11-02", "generated_at": "2026-10-30T16:00:00-05:00" },
  "batches": [
    { "id": 41, "kind": "friday", "owner": { "id": 1, "name": "Troy" }, "week_start": "2026-11-02", "generated_at": "2026-10-30T16:00:00-05:00" }
  ],
  "tasks": [],
  "done_count": 4,
  "total": 10,
  "due_count": 0,
  "pace": {
    "year": 2026,
    "as_of": "2026-11-04",
    "required_to_date": 127.4,
    "completed": 61,
    "target_total": 151,
    "pct": 40,
    "delta": -66,
    "label": "2026 BD Pace: 40% — 66 interactions behind pace"
  },
  "weekly_meetings": { "count": 1, "goal": 5, "non_dsbc_website": 1, "min": 1 },
  "touches_this_week": 2
}
```

- `batch` is the latest batch this week; `batches` is every batch this week (the Friday one, then each
  "Give Me 10 More"). `tasks` holds the tasks of **all** of them in that order (the example leaves it
  empty to keep it short; it holds Task objects).
- `done_count`/`total` are the **live Friday batch's business-development tasks only** (the latest
  Friday batch of the week, leaving out its `maintenance` tasks; one a forced re-run replaced is still
  listed but not counted): the headline "did I do my 10?". Asking for more never makes the 10 look
  half done; each `ten_more` batch's count is worked out by the page from its own tasks. A snoozed
  task stays in `total` (a slot is never refilled). `task_done`/`task_snooze` answer with the same
  BD-only numbers. `tasks` still lists the maintenance tasks, so it can hold more than `total`.
- `due_count` is the number of **open** `maintenance` tasks on this week's lists, any batch (the
  "Due now: N" line beside the headline). It drops when a call, meeting, email or text is logged for
  the contact (or the task is closed with "not the right person"). It is `0` before the first batch.
- Before the first Friday batch exists, `batch` is `null`, `batches` and `tasks` are `[]`, `total` is 0.
- `pace` covers every contact the owner owns (bd and maintenance):
  `target_total = Σ frequency_per_year` (the derived one: a BD contact counts its cadence's 52, 12 or 4); `required_to_date = target_total × day_of_year ÷ days_in_year`
  (one decimal, Central day); `completed` = touches this year; `pct = round(100 × completed ÷ target_total)`;
  `delta = round(completed − required_to_date)`. **Every `round` here rounds half up** (JavaScript
  `Math.round`: a half goes towards +infinity, so −14.5 becomes −14). Python must use `floor(x + 1/2)`
  on exact values (`backend/pace.py` `js_round`), never `round()` (half to even) or `ROUND_HALF_UP`
  (which sends −14.5 to −15). A missing, 0 or bad frequency counts as the category default. `label` is built by the server:
  `"<year> BD Pace: <pct>% — <|delta|> interaction(s) ahead of pace"`, `"… behind pace"`, or
  `"<year> BD Pace: <pct>% — right on pace"` when delta is 0.
- `weekly_meetings` is the workbook's top box: `count` = meetings, hosted events and calls that set a
  meeting this week; `non_dsbc_website` = those whose contact's lead source is not one of
  `settings.system_lead_sources` (DSBC Sales, Website Lead: the "at least 1 initiated by Troy" rule).

### Recommendation

The AI (or the fallback table) suggests; a person decides. Nothing changes on the contact until
it is confirmed.

```json
{
  "id": 72,
  "contact_id": 8,
  "interaction_id": 1074,
  "action": "Try Ray again",
  "due_date": "2026-11-09",
  "reason": "Voicemail, no live talk yet. Try again in a week.",
  "source": "fallback",
  "status": "pending",
  "created_at": "2026-11-02T14:35:00-06:00",
  "decided_at": null,
  "decided_by": null
}
```

`source`: `ai` | `fallback`. `status`: `pending` | `confirmed` (accepted as is) | `changed` (accepted
with an edited action or date) | `dismissed`. Fallback table: live call, meeting or hosted event → +105
days; voicemail or no answer → +7 days; "call me next month" / "in N weeks" in the summary → that date.

### FollowupDraft

The missed-call follow-up. Drafted, shown, edited, then sent by a person.

```json
{
  "id": 81,
  "contact_id": 8,
  "interaction_id": 1074,
  "channel": "email",
  "to": "ray.duchene@meridalefleets.example.com",
  "subject": "Shop floor at Meridale Fleet Services",
  "body": "Hi Ray,\n\nI tried you by phone on Monday about the shop floor. Is there a good time this week or next?\n\nThanks,\nTroy\nTreadwell",
  "source": "ai",
  "status": "draft"
}
```

`channel`: `email` | `sms` (`subject` is `null` for sms). `source`: `ai` | `fallback`.
`status`: `draft` | `sent` | `discarded`. `to` is the email address, or the number in E.164 for sms
(the page shows the contact's own `phone`, not `to`). The wording names the attempt by its own
date, never "today" for an older call: `BDCore.whenPhrase` gives "today", "yesterday", "on Monday"
(within the past week) or "on Jun 25".

### Candidate

A Direct-sales quote from the proposal tool (last 90 days) whose contact is not yet on the BD list.
Shown on the monthly **Potential BD Contacts** review.

```json
{
  "id": 92,
  "project_id": "8a4b2c1d-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
  "project_name": "Warehouse 2 Sealer",
  "company": "Switchgrass Construction",
  "contact_name": "Mia Thornton",
  "email": "mia.thornton@switchgrass.example.com",
  "phone": "816-555-0182",
  "quote_total": 42800.0,
  "quote_date": "2026-10-16",
  "status": "new",
  "possible_duplicate": { "contact_id": 15, "name": "Angela Ruiz", "company": "Switchgrass Construction" }
}
```

`status`: `new` | `added` | `ignored`. `possible_duplicate` is `null` or the closest existing contact
(same normalized company, or same email). It is a hint; Add still works. It is kept on `ignored`
candidates too: one whose match has the same name and company was ignored as "Already on the list",
and the Not added view shows it that way (with a link to that contact) instead of offering to add them.

### Analytics

Will's metric list, for a date range and optionally one owner.

```json
{
  "from": "2026-01-01",
  "to": "2026-11-04",
  "owner": null,
  "weekly_tasks": {
    "done": 20,
    "total": 30,
    "weeks": [
      { "week_start": "2026-10-19", "done": 9, "total": 10 },
      { "week_start": "2026-10-26", "done": 7, "total": 10 },
      { "week_start": "2026-11-02", "done": 4, "total": 10 }
    ]
  },
  "live_conversations": 61,
  "call_attempts": 52,
  "live_conversation_rate": 0.77,
  "interactions_vs_target": { "completed": 61, "required_to_date": 127.4, "target_total": 151 },
  "contacts_total": 37,
  "contacts_meeting_cadence": 14,
  "contacts_behind_cadence": 15,
  "contacts_never_reached": 8,
  "contacts_needing_confirmation": 8,
  "new_contacts_added": 1,
  "contacts_added_from_quotes": 1,
  "calls": 52,
  "emails": 4,
  "texts": 1,
  "meetings": 21,
  "meetings_generated": 2,
  "quotes_from_bd": { "count": 4, "total": 138400.0 },
  "revenue_from_bd": { "won_count": 1, "total": 31175.0 }
}
```

| Metric | Definition |
|---|---|
| `weekly_tasks` | The **live Friday batch's BD tasks only** (the latest of each salesperson and week, without its `maintenance` tasks; the same "did I do my 10?" as This Week's headline; Give Me 10 More work shows in the activity counts): `done`/`total` summed over every week that overlaps the range, plus one row per such week. A range with no weekly list gives `0`/`0` and `weeks: []`. |
| `live_conversations` | Touches in the range (calls answered or meeting set + meetings + hosted). |
| `call_attempts` | Calls and voicemails in the range, any outcome. |
| `live_conversation_rate` | Calls answered or meeting set ÷ `call_attempts` (0–1, two decimals). |
| `interactions_vs_target` | Same numbers as `pace`, for the range's year. |
| `contacts_meeting_cadence` | `cadence_status` `on_track` or `complete`, today. |
| `contacts_behind_cadence` / `contacts_never_reached` | `behind` / `never`, today. |
| `contacts_needing_confirmation` | `confirmed = false`, today. |
| `new_contacts_added` / `contacts_added_from_quotes` | Contacts created in the range / of those, `source = proposal_tool`. |
| `calls`, `emails`, `texts`, `meetings` | Counts by kind (`calls` includes voicemails; `meetings` includes hosted). |
| `meetings_generated` | Calls with `outcome = meeting_set`. |
| `quotes_from_bd` | Proposal-tool quotes dated in the range to contacts on the BD list (and of `owner`, when given): count, sum of totals. |
| `revenue_from_bd` | Of those, won jobs (count, sum of `total`). |

### Settings

```json
{
  "bd_cadence": "quarterly",
  "default_frequency": { "maintenance": 3 },
  "maintenance_touch_days": 120,
  "weekly": { "new_count": 5, "followup_count": 5, "run_day": "friday", "run_hour": 16, "enabled": true },
  "weekly_meeting_goal": 5,
  "non_dsbc_website_min": 1,
  "lead_sources": ["Current Account", "DSBC Sales", "Website Lead", "Other/Misc"],
  "system_lead_sources": ["DSBC Sales", "Website Lead"],
  "industries": ["Manufacturing", "Other", "Food Processing", "GC", "Life Science", "Restaurant", "Education", "Warehouse", "Retail", "Healthcare"],
  "stages": ["Meeting Set", "Met", "Proposal", "Won"],
  "account_types": ["Utility", "Manufacturing", "Pharma", "GC"],
  "interaction_kinds": ["call", "voicemail", "meeting", "email", "sms", "note", "hosted"],
  "touch_kinds": ["call (answered or meeting set)", "meeting", "hosted"],
  "call_outcomes": ["answered", "voicemail", "no_answer", "meeting_set"],
  "ai_enabled": false,
  "timezone": "America/Chicago"
}
```

`bd_cadence` is how often every BD contact is followed up unless it has an active override:
`weekly` (52 a year), `monthly` (12) or `quarterly` (4, the default). Changing it moves every BD
contact at once (their `frequency_per_year`, `next_due_date` and `cadence_status` follow). There is
no `default_frequency.bd`: a stored one is dropped. `default_frequency.maintenance` is the number a
new maintenance contact starts with.

`system_lead_sources` are the lead sources that do **not** count as the salesperson's own outreach
(the weekly meeting box's "at least 1 not from DSBC or the website"). They are read-only and must
always stay in `lead_sources`. `weekly.new_count + weekly.followup_count` is always 10.

`weekly.run_day` / `run_hour` / `enabled` drive the server's Friday worker: once the run moment of
the current Central week has passed (Friday 16:00 by default) it builds next week's batch for every
active salesperson who has none yet, and catches up on Saturday or Sunday if it was down; from
Monday a missed week is built by an admin (the admin's weekly-run route, with that Monday). The
worker runs only where the server's `BD_WEEKLY_ENABLED` is on (off unless set). `run_day` is
`friday`, `saturday` or `sunday` only: the run builds NEXT week's list and closes this week's open
tasks, so an earlier day would snooze the list while it is still being worked. Each salesperson's
batch is built and committed on its own: one that fails is logged and tried again on the next
tick, and never costs the others their list.

### Import

One workbook (or `.csv`) import, a dry run or a real one, as the import routes return it:

```json
{
  "ok": true,
  "import": {
    "id": 4,
    "file_name": "BD workbook.xlsx",
    "dry_run": true,
    "started_at": "2026-11-04T11:00:00-06:00",
    "by": { "id": 4, "name": "Hanz" },
    "rows_read": 36,
    "created": 0,
    "updated": 2,
    "skipped": 34,
    "possible_duplicates": 1,
    "errors": [{ "sheet": "Business Development Accounts", "row": 41, "message": "No company name." }]
  }
}
```

### UnmatchedCall

A call or text whose number matched no contact, as the unmatched-calls list returns it:

```json
{ "ok": true, "items": [{ "id": 61, "provider": "quo", "external_id": "AC990011", "direction": "in", "from_e164": "+19135550199", "occurred_at": "2026-11-03T16:42:00-06:00", "duration_s": 95, "summary": "Caller asked about a quote for a shop floor.", "status": "open" }], "total": 1 }
```

## Routes

Every BD route, one heading each, in the one form the tests read:

    #### `METHOD /api/bd/path` (who)

`who` names the BD roles the route lets in (`any BD role`, or roles such as `salesperson, assistant`;
BD admins and super admins pass every role check), `whoever logged it` for the one route an entry's
author owns, or `public` for the telephony webhook. Words after a `;` qualify the door ("an assistant
logs notes only") and may let a role in for part of the route ("a manager the cadence only"). A route
that answers 503 says `not built yet`. A new BD route gets its heading here and its line in
`backend/tests/_bd_routes.py` in the same change.

Every route below answers 503 `"The BD CRM is not turned on."` while `BD_ENABLED` is off, before any
other check. Every route but the telephony webhook needs the proposal tool's sign-in (401, the tool's
shape) and an active BD login (403 `"You don't have a BD role. Ask a BD admin to add you."`, or
`"Your BD login is turned off. ..."`). A proposal-tool admin has no BD role unless BD's people table
gives them one. A database behind the code answers 503 `"The BD CRM's database is not up to date. ..."`.
Any other path under `/api/bd/` is 404 `not_found`, or 400 `"<METHOD> is not allowed on <path>."` when a
BD route serves that path with another method.

#### `GET /api/bd/me` (any BD role)

```json
{
  "ok": true,
  "user": { "id": 1, "name": "Avery Quill", "email": "avery.quill@example.com", "role": "salesperson", "active": true, "last_seen_at": "2026-11-04T08:12:00-06:00" },
  "can": { "send": true, "analytics": false, "admin": false, "admin_area": false, "import": true, "run_batch": false, "week": true, "pick_owner": false,
           "add_contact": true, "edit_contact": true, "clear_duplicate": false, "cadence": true, "manage_entries": false,
           "manage_admins": false, "move_company": true },
  "today": "2026-11-04",
  "timezone": "America/Chicago"
}
```

`can` per BD role:

| Role | send | analytics | admin | admin_area | import | run_batch | week | pick_owner | add_contact | edit_contact | clear_duplicate | cadence | manage_entries | manage_admins | move_company |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| salesperson | yes | | | | yes | | yes | | yes | yes | | yes | | | yes |
| assistant | | | | yes | yes | | | | yes | yes | yes | yes | | | |
| manager | | yes | | | | | yes | yes | | | | yes | | | yes |
| admin | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | | yes |
| super_admin | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes |

`pick_owner`: may look at any salesperson's week (`GET /api/bd/week?owner=`); This Week shows the
"Whose week?" picker. A salesperson sees only their own week. This Week and the contact page show
this week's priority score to a person with `pick_owner`.

The contact page and Add contact (#808) read these five; each is what one route's check lets in, so a
page never offers what the server would refuse (tests/test_bd_contact_page_roles.py checks each key
against its route, person by person):

- `add_contact`: `POST /api/bd/contacts`. The sidebar's Add contact section and the contact page's
  "Add someone".
- `edit_contact`: `PATCH /api/bd/contacts/{id}` with any field, confirm, archive, a note, "Not the right
  person". The contact page's Edit details, the note box, the "Still the right person?" switch and
  Archive.
- `clear_duplicate`: `PATCH {"duplicate_of": null}`. "Not a duplicate" on the contact page; Add contact
  clears the flag it just made only for this person.
- `cadence`: how often to follow up (a manager's only edit). A person with `cadence` and no
  `edit_contact` (the manager) gets the cadence sheet alone.
- `manage_entries`: `DELETE /api/bd/interactions/{id}`, and `PATCH` of an entry somebody else logged.
  Each logged entry's Delete, and its Edit when it is not this person's own.

BD's Admin page (#809) reads `admin` (People, the Friday list, goals, pick lists, the phone status),
`admin_area` (the unmatched calls), `import` (the workbook import and past imports) and one more
(tests/test_bd_admin_roles.py checks each key against its route, person by person):

- `manage_admins`: `POST /api/bd/admin/users` with an admin role, and `PATCH /api/bd/admin/users/{id}`
  of an admin's login or to an admin role (Q29, the super admin alone). The People table offers the
  admin roles, and unlocks an admin's row, only to this person; a plain admin's locked row says why.

The Contacts page (#810) reads one more (tests/test_bd_accounts_roles.py checks it against its route,
person by person):

- `move_company`: `POST /api/bd/contacts/accounts/{id}/move` and undoing your own move (Q5: salesperson,
  manager, admins; never the assistant). A company row's "..." menu offers **Make maintenance account**
  or **Move back to BD** only to this person.

#### `GET /api/bd/settings` (any BD role)

`{ "ok": true, "settings": Settings }`.

#### `GET /api/bd/users` (any BD role)

The active BD logins, compact, for owner pickers: `{ "ok": true, "items": [{ "id", "name", "role" }], "total": N }`,
paged by `limit` / `offset`.

### This Week (#807)

The week, the task buttons and "Give Me 10 More". BD admins and super admins pass every role check
below. Every date is Central.

#### `GET /api/bd/week` (salesperson, manager)

`{ "ok": true, "week": WeekView }`. Query: `owner` (a salesperson's id; default: the caller when they
are a salesperson, else the first active salesperson) and `week_start` (a Monday, `YYYY-MM-DD`;
default: this week). It never builds anything: a week with no batch is the empty WeekView. Checks in
this order: an `owner` that is no user is 404 `"That user does not exist."`, one who is not a
salesperson 404 `"<name> has no weekly list. Only salespeople do."`; an assistant is 403
`"The weekly list is the salesperson's."`; a salesperson asking for someone else's week is 403
`"You can see only your own week."`; a `week_start` that is not a Monday is 400 (`fields.week_start`).

#### `POST /api/bd/week/ten-more` (salesperson)

Body `{ "owner"? }`. A `ten_more` batch of this week with the next 10 by the ranking (due maintenance
first, then by score), leaving out anyone on this week's lists in any state and anyone still open on a
later week's list. Answers `{ "ok": true, "week": WeekView }` for the week it was built in. A
salesperson asks on their own list only (403 `"You can ask for more only on your own list."`); nobody
left is 409 `"Everyone on your list is already covered this week."`.

#### `POST /api/bd/tasks/{id}/done` (salesperson, own list)

#### `POST /api/bd/tasks/{id}/snooze` (salesperson, own list)

#### `POST /api/bd/tasks/{id}/reopen` (salesperson, own list)

For all three: the task is looked up first (404 `"That task does not exist."`), then the role (403),
then the list (403 `"That task is on someone else's list."`). `snooze` takes `{ "reason"? }` (text,
500 characters at most) and runs to the Monday after the task's week. A maintenance task whose contact is still due
cannot be marked done or skipped: 409 `"A maintenance follow-up stays on the list until you log a
call, meeting, email or text."`. Done twice is 409 `"That task is already done."`; only an open task
can be skipped; reopening an open task is 409 `"That task is already open."`.

- done: `{ "ok": true, "task": { "id", "batch_id", "status": "done", "done_at" }, "done_count", "total" }`
- snooze: `{ "ok": true, "task": { "id", "status": "snoozed", "snoozed_until" }, "done_count", "total" }`
- reopen: `{ "ok": true, "task": { "id", "status": "open", "done_at": null, "snoozed_until": null } }`

#### `POST /api/bd/tasks/{id}/not-right-person` (salesperson, assistant; any list)

Body `{ "note"? }` (text, 2000 characters at most). The role is checked before the task is looked up.
The contact becomes unconfirmed (the note is added to its notes, an `unconfirmed` event is logged) and
the task is marked done: `{ "ok": true, "task": { "id", "status": "done", "done_at" },
"contact": { "id", "confirmed": false, "notes" } }`.

#### `POST /api/bd/admin/weekly/run` (admin)

"Run Friday batch now". Body `{ "owner"?, "week_start"?, "force"? }`: one salesperson's Friday batch
for next week, or for `week_start` when it is this Monday or next Monday (400 otherwise). The same
build as the Friday worker (the rollover first). A week that already has a Friday batch is 409
`"A Friday batch already exists for <name> that week."` unless `force`. Answers
`{ "ok": true, "batches": [TaskBatch], "tasks_created": N }`.

### Interactions (#807)

#### `GET /api/bd/contacts/{id}/interactions` (any BD role)

The contact's timeline, newest first: `{ "ok": true, "items": [{ "type": "interaction", "at",
"interaction": Interaction } | { "type": "event", "at", "event": { "action", "by": UserRef|null,
"detail" } }] }`. A workbook contact with no logged `created` event gets one at its `created_at`.

#### `POST /api/bd/contacts/{id}/interactions` (salesperson; an assistant logs notes only)

Body `{ "kind", "outcome"?, "occurred_at"?, "direction"?, "duration_s"?, "summary"?, "transcript"? }`.
`occurred_at` defaults to now and may not be after today (Central). A call, voicemail, meeting or
hosted event closes this week's new or follow-up task for the contact; anything but a note closes its
maintenance tasks once the contact is no longer due. Answers `{ "ok": true, "interaction": Interaction,
"contact": Contact, "task": { "id", "status", "done_at" } | null, "recommendation": Recommendation |
null, "missed_call": bool }`. A manager is 403; an assistant logging anything but a note is 403
`"Assistants can add notes only."`.

#### `PATCH /api/bd/interactions/{id}` (whoever logged it; admin)

Any of `kind`, `outcome`, `occurred_at`, `duration_s`, `summary`, `transcript`. Someone else's entry
is 403 `"Only the person who logged this can change it."`. Answers `{ "ok": true, "interaction": Interaction }`.

#### `DELETE /api/bd/interactions/{id}` (admin)

`{ "ok": true, "deleted": id }`. An `interaction_deleted` audit row is logged with no contact.

### Contacts (#807, #808)

#807 moved one contact (get, patch, confirm) for This Week; #808 moves the rest with the contact page
and Add contact. Merge is not built yet (below). A body that is not a JSON object is 400
`{"body": "Send a JSON object."}` on every route here that takes one. The examples use the made-up
fixture seed (`bd/ops/fixture_seed.py`) on its day, Wednesday 2026-11-04.

#### `GET /api/bd/contacts` (any BD role)

Query (all optional, combined with AND): `q` (name, company, email, title or city, any case; the
company also by its cleaned name; 3 or more digits also match the phone's digits), `category`
(`bd`|`maintenance`), `owner` (user id), `industry`, `lead_source`, `stage`, `confirmed`
(`true`|`false`), `cadence` (`never`|`behind`|`on_track`|`complete`), `company` (company id),
`duplicates` (`true` = only flagged), `sort` (`name`|`company`|`last_live_at`|`next_due_date`, default
`company`; an unknown one is 400 `"Unknown sort."`), `limit`, `offset`. Archived contacts are left
out unless `archived=true`. `q` is text, never a pattern. Answers `{ "ok": true, "total": N,
"items": [Contact] }`; a bad value is 400 with `fields` naming it.

#### `GET /api/bd/contacts/duplicates` (any BD role)

Add contact's "this person may already exist" check. Query: `company` and/or `email` and/or `phone`,
and `except` (a contact id to leave out, for the contact being edited). Every contact that is not
archived at a company with the same cleaned name, else with the same email (any case), else the same
phone (any format), in id order, each once with the first reason that matches.

```json
{
  "ok": true,
  "items": [
    { "contact_id": 25, "name": "Priya Nandan", "company": "Cedar Creek Concrete", "city": null, "reason": "Same company name" },
    { "contact_id": 26, "name": "Owen Pratt", "company": "Cedar Crest Concrete", "city": null, "reason": "Same phone" }
  ]
}
```

That is `?company=Cedar Creek Concrete&phone=785.555.0105`. `reason`: `Same company name` |
`Same email` | `Same phone`.

#### `POST /api/bd/contacts` (salesperson, assistant)

Add contact. `company` is `{ "id" }` (an existing one; 404 `"That company does not exist."`) or
`{ "name" }` (the company with the same cleaned name, else a new one with the contact's `city` and
`industry`). The owner defaults to the caller when they are a salesperson, else the first active
salesperson. Text is trimmed; a client never sets `source` (always `manual`) or a derived field. A
possible duplicate is saved anyway (**201**) with `duplicate_of` set to the first match, and the
matches come back as `possible_duplicates`.

A **BD** contact follows the BD cadence (`settings.bd_cadence`): its stored `frequency_per_year` is
the cadence's number (52 / 12 / 4) and it **cannot be sent**, even as `null` (400 `fields.frequency_per_year`
`"BD contacts follow the BD cadence. Set a follow-up override instead."`). A **maintenance** contact
takes `frequency_per_year` (kept between 1 and 52, rounded half up; 0, less or `null` takes
`settings.default_frequency.maintenance`). A new contact starts `confirmed: false` unless the request
says `"confirmed": true`. The size limits are PATCH's.

```json
{
  "company": { "name": "Juniper Hollow Dental" },
  "name": "Ari Mendel",
  "title": "Office Manager",
  "email": "ari@juniperhollow.example.com",
  "phone": "913.555.0113",
  "lead_source": "Referral",
  "notes": "Met at the dental expo."
}
```

```json
{
  "ok": true,
  "contact": {
    "id": 34,
    "company": { "id": 19, "name": "Juniper Hollow Dental" },
    "name": "Ari Mendel",
    "owner": { "id": 2, "name": "Blair Fenn" },
    "confirmed": false,
    "source": "manual",
    "frequency_per_year": 4,
    "cadence": "quarterly",
    "cadence_source": "global",
    "cadence_status": "never",
    "duplicate_of": null
  },
  "possible_duplicates": []
}
```

(`contact` is the full Contact; trimmed here.) A `created` event `"Added by hand"` is logged.

#### `GET /api/bd/contacts/{id}` (any BD role)

`{ "ok": true, "contact": Contact, "open_task": Task | null, "pending_recommendation":
Recommendation | null, "missed_call": { "interaction_id", "occurred_at", "followup_sent": false } |
null }`. `open_task` is this week's latest task for the contact, in any state. `missed_call` is the
latest voicemail or no-answer call when nobody has talked live since, it is at most 14 Central days
old and nobody has sent a follow-up for it.

#### `PATCH /api/bd/contacts/{id}` (salesperson, assistant; a manager the cadence only)

Any editable Contact field, `company` (`{ "id" }` or `{ "name" }`), `owner_id`, `co_owner_id`,
`cadence_override` with `cadence_override_until`, and `duplicate_of: null` (the assistant clears a
flag). A manager may send only `cadence_override`, `cadence_override_until` and a maintenance
contact's `frequency_per_year` (403 `"Managers can change only how often to follow up."`). Size
limits: `notes` 20000 characters, `next_step` 500, `email` 254, the name and every other text field
200, at most 50 tags of 60 characters, and a `company` `name` 200 (400 `"Keep this to N characters or
fewer."`). Answers `{ "ok": true, "contact": Contact, "possible_duplicates": [...] }`.

#### `POST /api/bd/contacts/{id}/confirm` (salesperson, assistant)

Body `{ "confirmed"? }` (default true). `{ "ok": true, "contact": { "id", "confirmed" } }`; a change is
logged as a `confirmed` or `unconfirmed` event.

#### `POST /api/bd/contacts/{id}/archive` (salesperson, assistant)

Takes the contact off every list and batch; the history is kept. An open task on any weekly list
closes as `snoozed`. `{ "archived": false }` restores, and undoes that: a task the archive closed on
**this** week's list, or on a later one, opens again; an earlier week's stays closed, and a task that
was already done or skipped is left as it was. An `archived` (with the `reason`, at most 200
characters: 400 `"Keep this to 200 characters or fewer."`) or `restored` event is logged.

```json
{ "archived": true, "reason": "Moved firms" }
```

```json
{ "ok": true, "contact": { "id": 21, "archived_at": "2026-11-04T10:30:00-06:00" } }
```

### BD accounts (#810)

The Contacts page lists **BD accounts**: the `companies` rows, under the page's name for them (the table
keeps its name; nothing is reshaped, and every contact still has exactly one company). A person is on the
**BD** tab or the **Maintenance** tab by their own `category`, so an account is on a tab when at least one
of its people who is not archived is (an account holding only maintenance people is not on the BD tab).
The paths sit under `/api/bd/contacts/`, so the proposal tool's audit log records each read as a read of
people (by its path alone: a search term is `?q=` and never reaches it). The examples use the fixture
seed on its day, Wednesday 2026-11-04.

**Account** (one tab's row):

| Field | Type | Notes |
|---|---|---|
| `id`, `name`, `city`, `industry` | | the company |
| `category` | string | the tab: `bd` or `maintenance` |
| `people_count` | int | that tab's people at the account, archived people left out |
| `owner` | UserRef or null | whoever owns the most of those people. **A tie** goes to the tied owner who logged the most recent live talk at the account (Q41), else to the tied owner first by name. `null` when nobody owns any of them |
| `other_owners` | int | the "+N": how many other people own someone there |
| `last_live_at` | timestamp or null | the latest live touch (the one counting rule: a call where someone talked, a meeting, a hosted event) with **anyone** at the account who is not archived, BD or maintenance (Q34), dated on or before today |
| `people` | [AccountPerson] | that tab's people, by name (any case), then id |

**AccountPerson**: `id` (the contact page is `/bd/contact.html?id=`), `name`, `title`, `phone`,
`phone_e164`, `email`, `category`, `owner` (UserRef or null), `lead_source`, and what the status and
cadence pills read: `confirmed`, `importance`, `duplicate_of` (as on a Contact), `cadence_status`,
`cadence`, `cadence_source`, `cadence_override_until`, `maintenance_due`, `maintenance_due_date`,
`last_live_at`, `last_followup_at` (each as on a Contact).

#### `GET /api/bd/contacts/accounts` (any BD role)

Query: `category` (`bd`, the default, or `maintenance`), `sort` (`name`, the default; `people`, most
first; `last_live_at`, latest first and never-talked last; ties by name, then id; an unknown one is 400
`"Unknown sort."`), `limit`, `offset`. `{ "ok": true, "category", "total": N, "items": [Account] }`.

```json
{
  "ok": true,
  "category": "bd",
  "total": 8,
  "items": [
    {
      "id": 16, "name": "Bluestem Logistics", "city": "Lenexa", "industry": "Warehousing", "category": "bd",
      "people_count": 3, "owner": { "id": 1, "name": "Avery Quill" }, "other_owners": 2, "last_live_at": null,
      "people": [
        { "id": 29, "name": "Ines Varga", "title": "Purchasing", "phone": "913-555-0109", "phone_e164": "+19135550109",
          "email": "ines.varga@bluestem.example.com", "category": "bd", "confirmed": false, "importance": 1,
          "owner": { "id": 4, "name": "Devon Hale" }, "duplicate_of": null, "lead_source": "Other/Misc",
          "last_live_at": null, "last_followup_at": null, "cadence_status": "never", "cadence": "quarterly",
          "cadence_source": "global", "cadence_override_until": null, "maintenance_due": false,
          "maintenance_due_date": null }
      ]
    }
  ]
}
```

(Trimmed to one account and one person.) Bluestem's three people have three owners, one each, and
nobody there has had a live talk, so the tie goes to the first by name.

#### `GET /api/bd/contacts/search` (any BD role)

`q` (required, at most 200 characters; blank is 400 `fields.q` `"Type something to search for."`)
matches, among people who are not archived: an **account name** (any case; also by its cleaned name,
unless the term cleans to nothing), a **person's name** (any case), a **phone in any format** (a term
with 10 or more digits, on the last 10: `(913) 555-0108`, `+1 913 555 0108` and `9135550108` are one
number; fewer digits never match a phone) and an **email** (any case, any part). `q` is text, never a
pattern. One item per account and tab it is found on, in name order, BD before maintenance; `people`
are the people who matched there (by name, then id), empty when only the account's name did. The page
opens that account on that tab and highlights them. At most 100 items. Nothing is written anywhere: no
event, and the audit log keeps the path only.

```json
{ "ok": true, "total": 1, "items": [{ "tab": "bd", "account": { "id": 16, "name": "Bluestem Logistics" }, "account_match": false, "people": [{ "id": 28, "name": "Sam Achebe" }] }] }
```

That is `?q=(913) 555-0108`. A maintenance person's hit has `"tab": "maintenance"`.

#### `POST /api/bd/contacts/accounts/{id}/move` (salesperson, manager)

Body `{ "to": "maintenance" | "bd" }` (else 400 `fields.to` `"Use maintenance or bd."`). Makes the whole
company a maintenance account, or moves it back to BD (2026-11-20, Q1-Q11): every person at it in the
other category, archived people too, changes; nothing else does. An unknown company is 404 `"That company
does not exist."`; nobody to move (no person of the other category who is not archived) is 409
`"Nobody at this company is a BD contact."` or `"Nobody at this company is a maintenance contact."`. It
takes effect at once:

- **To maintenance.** Each person's open BD call (`new` or `followup`) on this week's list, or on next
  week's once the Friday run has made it, comes off as "Not this week" does (`snoozed` until the Monday
  after its week). Nothing is added to the 10: calls already logged still count, the list is never
  refilled, and it never holds more than 10 BD calls. A person whose maintenance follow-up is due (120
  days or more since their last follow-up, or never followed up: `maintenance_due`) gets the pinned
  maintenance follow-up on their owner's list at once, made by the Friday batch's rules, when the owner
  is an active salesperson. It goes on the owner's live Friday list of that week when the person has no
  task there; otherwise on a list of its own for that week (a `ten_more` batch holding only pinned
  follow-ups, which are never part of the 10).
- **To BD.** Each person's open pinned maintenance follow-up comes off (`snoozed`), and nothing is added
  to any list: they wait for Friday's batch like everyone else.
- Each person's stored `frequency_per_year` becomes the new category's default, as a contact edit's
  category change sets it.
- One event, `company_moved`, by the caller, with no contact: `{ "company_id", "to", "people", "contacts":
  [[id, frequency before]], "tasks_off": [task ids], "pins": [task ids], "batches": [batch ids] }`. Ids
  and counts only, never a name, phone, email or note.

```json
{ "to": "maintenance" }
```

```json
{ "ok": true, "move": { "id": 9, "company": { "id": 16, "name": "Bluestem Logistics" }, "to": "maintenance", "people": 3, "calls_off": 0, "pinned": 1, "undo_until": "2026-11-04T10:32:00-06:00" } }
```

`people` counts the people who are not archived, `calls_off` the calls that came off, `pinned` the
follow-ups pinned; `undo_until` is two minutes after the move.

#### `POST /api/bd/contacts/accounts/moves/{id}/undo` (salesperson, manager; your own move only)

`{id}` is the move's `id`. Puts back exactly what that one move changed: each person's category and
frequency, each call it took off (open again) and each follow-up it pinned (gone, with any list made
for them). `{ "ok": true, "undone": { "id", "company": { "id", "name" }, "to", "people" } }`, and one
`company_move_undone` event `{ "move_id", "company_id", "to", "people" }`. Refused, changing nothing:
404 `"That move does not exist."`; 403 `"Only the person who made this move can undo it."` (an admin
too); 409 `"This move is already undone."`; 409 `"It's too late to undo this move."` (more than two
minutes after it); 409 `"Something changed since this move, so it can't be undone."` (a later move of
the company, a person's category changed by hand, a call it took off put back, or a follow-up it pinned
done).

### Companies (#808)

#### `GET /api/bd/companies` (any BD role)

Add contact's company type-ahead. Query: `q`, `limit`, `offset`. A company matches when its cleaned
name starts with the cleaned `q`, or one of its later words does (`ridge` finds Prairie Ridge, `idge`
finds nothing; a `q` that cleans to nothing lists every company). Ordered by name, any case.
`contact_count` counts the people who are not archived.

```json
{ "ok": true, "total": 1, "items": [{ "id": 16, "name": "Bluestem Logistics", "city": "Lenexa", "industry": "Warehousing", "contact_count": 3, "created_at": "2026-11-04T09:00:00-06:00" }] }
```

#### `GET /api/bd/companies/{id}` (any BD role)

The company and its people who are not archived, in id order, as ContactCompact:
`{ "ok": true, "company": Company, "contacts": [ContactCompact] }`. An unknown id is 404
`"That company does not exist."`.

#### `POST /api/bd/companies` (salesperson, assistant)

`{ "name", "city"?, "industry"? }`. Always a new company (merging accounts is a later ticket); the
people already at a company with the same cleaned name come back as `possible_duplicates`. A blank
name is 400 `"Type the company name."`. The name, `city` and `industry` stop at 200 characters, as through
Add contact (400 `"Keep this to 200 characters or fewer."`).

```json
{ "ok": true, "company": { "id": 19, "name": "Juniper Hollow Dental", "city": "Lenexa", "industry": "Healthcare", "contact_count": 0, "created_at": "2026-11-04T10:40:00-06:00" }, "possible_duplicates": [] }
```

#### `PATCH /api/bd/companies/{id}` (salesperson, assistant)

Any of `name` (blank is 400 `"A company needs a name."`), `city`, `industry` (text or `null`). A
rename moves the cleaned name with it, so the duplicate check and Add contact find the new name.
The same 200-character limits as `POST`. `{ "ok": true, "company": Company }`.

### Admin (#809)

BD's Admin page, separate from the proposal tool's own Admin page. Its People table is **BD's logins
only** (`bd.users`): adding, changing or turning off a BD login never touches the proposal tool's
profiles, roles, sidebar settings or Special permissions, and the tool's Admin page never touches a BD
login. A proposal-tool admin has no BD role until a BD admin adds them here, like anyone else.
"Run Friday batch now" (`POST /api/bd/admin/weekly/run`) is under This Week above.

#### `GET /api/bd/admin/users` (admin)

Every BD login, turned-off ones too, in id order. Paged by `limit` and `offset` like every other list.

```json
{ "ok": true, "items": [{ "id": 3, "name": "Casey Moret", "email": "casey.moret@example.com", "role": "assistant", "active": true, "last_seen_at": "2026-11-02T08:30:00-06:00" }], "total": 1 }
```

#### `POST /api/bd/admin/users` (admin; a super admin to add an admin)

`{ "email", "role", "name"? }`. The email is trimmed and lower-cased and must be an address the
proposal tool's sign-in lets in (its allowed domain), else 400 `{"email": "Use a @<domain> address."}`;
one longer than 254 characters is 400 `{"email": "Use at most 254 characters."}` (#809).
`role` is one of the five BD roles (400 `"Pick a role."`). `name` is optional text of at most 120
characters; without it the name comes from the email (`nell.ash@...` is "Nell Ash"). Someone who
already has a BD login, turned off or not, is 409 `"That person already has a login."`. Only a
`super_admin` may add an `admin` or `super_admin` (403 `"Only a super admin can add an admin."`: an
admin a plain admin made could never be changed again).

```json
{ "email": "nell.ash@example.com", "name": "Nell Ash", "role": "salesperson" }
```

```json
{ "ok": true, "user": { "id": 8, "name": "Nell Ash", "email": "nell.ash@example.com", "role": "salesperson", "active": true, "last_seen_at": null } }
```

#### `PATCH /api/bd/admin/users/{id}` (admin; a super admin to change an admin)

Any of `role`, `active` (true or false; false turns the BD login off, and every BD route then answers
403 "Your BD login is turned off. ..."), `name` (1 to 120 characters). **Nobody changes their own role
or sign-in** (403 `"You can't change your own role or sign-in."`; your own name is fine). Changing a
login that is an admin's, or making someone an admin, needs a `super_admin` (403 `"Only a super admin
can change an admin."`). An unknown id is 404 `"That user does not exist."`. A field that does not
change is not logged.

```json
{ "role": "manager", "active": true }
```

```json
{ "ok": true, "user": { "id": 4, "name": "Devon Hale", "email": "devon.hale@example.com", "role": "manager", "active": true, "last_seen_at": "2026-10-30T16:15:00-05:00" } }
```

#### `PUT /api/bd/admin/settings` (admin)

Send only the keys to change. `weekly` and `default_frequency` are **merged** into what is there (send
`{"weekly": {"new_count": 6, "followup_count": 4}}` and the run day, hour and on/off stay). The result
is checked as a whole before anything is kept; a bad PUT changes nothing and is 400 with `fields`
(one field: its own sentence as the message; several: `"Some settings need fixing."`):

- `weekly.new_count` and `weekly.followup_count` whole numbers 0 to 10 that **add up to 10**;
  `run_day` `friday`, `saturday` or `sunday` (the run builds next week's list), `run_hour` 0 to 23,
  `enabled` true or false; else "Pick Friday, Saturday or Sunday, an hour from 0 to 23, and on or off."
- `bd_cadence` `weekly`, `monthly` or `quarterly`, else "Pick weekly, monthly or quarterly.";
  `default_frequency.maintenance` 1 to 52 (a sent `default_frequency.bd` is ignored);
  `weekly_meeting_goal` 0 to 50; `non_dsbc_website_min` 0 up to the goal; `ai_enabled` true or false.
- `lead_sources`, `industries`, `stages`, `account_types`: at least one value, no blanks, no repeats
  (any case) ("Keep at least one value, each one different."). `lead_sources` must keep every
  `system_lead_sources` value. Each list holds **at most 100 values of 120 characters or fewer**, else
  "Keep at most 100 values of 120 characters or fewer." (every role loads these on every page).
- Read-only keys (`system_lead_sources`, `interaction_kinds`, `touch_kinds`, `call_outcomes`,
  `timezone`, `maintenance_touch_days`) and unknown keys are ignored.

The Friday worker reads the same settings, so a new `weekly.run_day` or `run_hour` moves the next
Friday batch at once (it still runs only where `BD_WEEKLY_ENABLED` is on).

```json
{ "bd_cadence": "monthly", "default_frequency": { "maintenance": 3 }, "lead_sources": ["Current Account", "DSBC Sales", "Website Lead", "Other/Misc", "Trade Show"] }
```

Response: `{ "ok": true, "settings": Settings }`.

```json
{ "ok": false, "error": "bad_request", "message": "New people and follow-ups must add up to 10.", "fields": { "weekly": "New people and follow-ups must add up to 10." } }
```

#### `GET /api/bd/admin/telephony` (admin)

Whether a phone system is connected. It reads only **whether** `BD_TELEPHONY_PROVIDER`,
`BD_QUO_API_KEY` and `BD_QUO_WEBHOOK_SECRET` are set, the time of the provider's latest integration
event, the provider's count of integration events (`events`) and the count of open unmatched calls.
It never answers a key or a secret. `provider` is
`"null"` when none is set (`"No phone system connected yet."`); `quo` is connected when both its key
and its webhook secret are set (`"Quo is connected."`, else `"Quo is picked, but its API key or webhook
secret is not set."`); any other provider is `"This phone system is not supported yet."`.

```json
{ "ok": true, "telephony": { "provider": "null", "connected": false, "last_event_at": null, "events": 0, "unmatched_open": 1, "message": "No phone system connected yet." } }
```

#### `GET /api/bd/admin/unmatched-calls` (assistant, admin)

Calls and texts whose number matched no contact, as UnmatchedCall, in id order. Query: `status`
(`open` (default) | `attached` | `dismissed` | `all`; anything else is 400), `limit`, `offset`.

#### `POST /api/bd/admin/unmatched-calls/{id}/attach` (assistant, admin)

Puts the call on a contact's timeline (and, with `"save_number": true`, stores the number on the
contact). `contact_id` is required (400 `"Pick a contact."`; an unknown one is 404 `"That contact does
not exist."`). `outcome` (optional): how the call went, `answered` | `voicemail` | `no_answer`, as the
assistant says (400 `"Pick how the call went."` otherwise). Without it, a call counts as `answered`
only when it lasted **60 seconds or more**, else `no_answer`: a 40-second voicemail must never count
as a live conversation. A text keeps no outcome. The attach closes no weekly task and suggests no next
step, except that a due maintenance contact's pinned task closes with the follow-up. An unknown call
is 404 `"That call does not exist."`; one already attached or dismissed is 409 `"That call was already
handled."`; one the phone system has already put on a timeline is 409 `"That call is already on a
contact's timeline."`.

```json
{ "contact_id": 32, "save_number": true, "outcome": "answered" }
```

```json
{ "ok": true, "unmatched_call": { "id": 801, "status": "attached" }, "interaction": { "id": 109, "contact_id": 32, "contact": { "id": 32, "name": "Wes Calder", "company": { "id": 18, "name": "Osage Plains Brewing" } }, "kind": "call", "direction": "in", "counts_as_touch": true, "occurred_at": "2026-11-03T16:42:00-06:00", "duration_s": 95, "outcome": "answered", "summary": "Caller asked about a quote for a shop floor.", "transcript": null, "recording_url": null, "provider": "quo", "external_id": "QX-0002", "user": null } }
```

#### `POST /api/bd/admin/unmatched-calls/{id}/dismiss` (assistant, admin)

The same 404 and 409 as attach.

```json
{ "ok": true, "unmatched_call": { "id": 801, "status": "dismissed" } }
```

#### `POST /api/bd/admin/import` (salesperson, assistant, admin)

A manager gets 403 (and `can.import` is false for them). A **salesperson's** upload gives every
contact it adds to that salesperson, whatever the Owner column says, and makes nobody a co-owner, so
a salesperson can never hand contacts to someone else. A known contact that already has an owner keeps
it (one with no owner gets the uploader), and the meetings the file logs are in the uploader's name.
An assistant's or admin's upload follows the Owner column (a blank or unknown owner goes to the first
active salesperson). The history lists everyone's imports.

`multipart/form-data`: `file` (the workbook `.xlsx` or a `.csv`) and `dry_run` (`true` first, then
`false` for "Import now"; anything but `false`, `0`, `no` or `off` is a dry run). Reads "Business
Development Accounts" and "Maintenance Accounts" (header row 5, or the first of rows 1 to 15 that
names the company and the contact), trims spaces and non-breaking spaces from company names, splits
`Avery/Greg` into owner and co-owner, and turns meeting and Maintenance touch dates into `meeting`
interactions. Idempotent on (normalized company, lower-case email). Re-importing keeps edits made in
the app: the server remembers what the import last wrote to each field, and a field changes only
when the file differs from the contact and either the import never wrote that field or the sheet now
holds a different value than last time. A next step that a touch on or after its date already met is
never brought back.

**Limits.** The file is at most **10 MB**: 413 `{"error": "bad_request", "message": "That file is too
big. The limit is 10 MB.", "fields": {"file": "Pick a smaller file."}}`, refused while the upload
streams, before it is parsed. An `.xlsx` is a zip, and its own directory is checked before it is
opened: at most 200 MB unpacked in all, at most 20 MB in any one part, and a part over 1 MB at most
100 times its packed size, else 413 `"That workbook is too big to read."`. Another file type is 400
`"Pick an .xlsx or .csv file."`; a file that cannot be read is 400 `"That file could not be read. Save
it as an .xlsx workbook or a .csv and try again."`; no file is 400 `"Pick a file to import."`. A bad
upload records nothing.

A dry run and a real run both record an Import (see Import above) and answer `{ "ok": true, "import":
Import }`; only a real run keeps the contacts and interactions it adds.

#### `GET /api/bd/admin/imports` (salesperson, assistant, admin)

`{ "ok": true, "items": [Import], "total": N }`, newest first, paged by `limit` and `offset`.

### Not built yet (503 after the role check)

These routes come over from BD as placeholders (#802, Q1, Q32): each checks the caller's access
exactly as the finished route will (no sign-in 401, no BD login or the wrong BD role 403), then
answers 503 `"unavailable"` with `"This part is not built yet (Phase N)."` (`"(a later phase)."` for
merge). They live in `backend/bd/routers/pending.py`. The rules below are BD's, kept here for when
each route is built; a route that gets built loses "not built yet" from its heading and its line in
`pending.py` in the same change. BD's service-token route (bd-candidates, the proposal tool's "Add to
BD" button) is not carried over; Add to BD comes back as a direct in-app call (#816).

#### `POST /api/bd/contacts/{id}/merge` (assistant, admin; not built yet)

Moves interactions, tasks and tags of `{id}` onto `into_id`, archives `{id}`, logs an event.

```json
{ "into_id": 21 }
```

```json
{ "ok": true, "contact": { "id": 21, "name": "Dana Whitlow" }, "merged_id": 33 }
```

#### `POST /api/bd/interactions/{id}/recommend` (salesperson; not built yet)

AI next action. Ask (again) for a suggestion on a logged entry. Runs the AI when `ai_enabled`, else the
fallback table. Never fails just because the AI is down: it answers `source: "fallback"`.

```json
{}
```

```json
{ "ok": true, "recommendation": { "id": 73, "contact_id": 25, "interaction_id": 104, "action": "Call about the clean room quote", "due_date": "2027-01-11", "reason": "Priya said the quote is in their January budget. Call early in January.", "source": "ai", "status": "pending", "created_at": "2026-11-03T12:06:00-06:00", "decided_at": null, "decided_by": null } }
```

#### `POST /api/bd/recommendations/{id}/confirm` (salesperson; not built yet)

Accept as is (`{}`) or with changes. Sets the contact's `next_step` / `next_step_date`; if the customer
asked for a date, send `"promised": true` to also set `promised_date`.

```json
{ "action": "Call about the clean room quote", "due_date": "2027-01-06", "promised": true }
```

```json
{
  "ok": true,
  "recommendation": { "id": 73, "status": "changed", "due_date": "2027-01-06", "decided_at": "2026-11-04T10:50:00-06:00", "decided_by": { "id": 1, "name": "Avery Quill" } },
  "contact": { "id": 25, "next_step": "Call about the clean room quote", "next_step_date": "2027-01-06", "promised_date": "2027-01-06" }
}
```

#### `POST /api/bd/recommendations/{id}/dismiss` (salesperson; not built yet)

```json
{ "ok": true, "recommendation": { "id": 74, "status": "dismissed", "decided_at": "2026-11-04T10:52:00-06:00", "decided_by": { "id": 1, "name": "Avery Quill" } } }
```

#### `POST /api/bd/interactions/{id}/draft-followup` (salesperson; not built yet)

The missed-call follow-up. `{id}` is the voicemail or no-answer call. Drafts from the contact, recent
history and the attempt.

```json
{ "channel": "sms" }
```

```json
{ "ok": true, "draft": { "id": 82, "contact_id": 26, "interaction_id": 108, "channel": "sms", "to": "+17855550105", "subject": null, "body": "Hi Owen, Avery at Treadwell. Just left you a voicemail about the shop floor. Is there a good time to talk this week?", "source": "fallback", "status": "draft" } }
```

#### `POST /api/bd/interactions/{id}/send-followup` (salesperson; not built yet)

Sends the (possibly edited) draft, by email or by the phone provider for a text, and logs it as an
`email`/`sms` interaction with `counts_as_touch: false`. Email sends only 8 am–6 pm Central (409
otherwise). `{"channel": "none"}` records "Nothing" and hides the card.

```json
{ "draft_id": 81, "channel": "email", "subject": "Shop floor at Cedar Creek Concrete", "body": "Hi Priya,\n\nI tried you by phone on Monday about the shop floor. Is there a good time this week or next?\n\nThanks,\nAvery\nTreadwell" }
```

```json
{
  "ok": true,
  "draft": { "id": 81, "status": "sent" },
  "interaction": { "id": 1078, "contact_id": 25, "kind": "email", "direction": "out", "counts_as_touch": false, "occurred_at": "2026-11-04T10:55:00-06:00", "duration_s": null, "outcome": null, "summary": "Shop floor at Cedar Creek Concrete", "transcript": null, "recording_url": null, "provider": "resend", "external_id": "re_7d1f2c", "user": { "id": 1, "name": "Avery Quill" } }
}
```

`{"channel": "none"}` answers with nothing sent:

```json
{ "ok": true, "draft": null, "interaction": null }
```

A second send for the same call is 409 ("A follow-up was already handled for this call."). A
follow-up never counts toward pace and never closes a new or follow-up weekly task; the one exception
is a `maintenance` task, which the email or text it logs closes (any logged follow-up does; see
`POST /api/bd/contacts/{id}/interactions`).

#### `GET /api/bd/review/candidates` (salesperson, assistant, manager; not built yet)

Potential BD Contacts. Query: `status` (`new` (default) | `added` | `ignored` | `all`), `since` (a date,
default 90 days ago, Central). Pulls fresh Direct quotes from the proposal tool and leaves out anyone
already on the list by (normalized company, lower-case email). The page asks `?status=all` once and
splits the answer into its three tabs.

```json
{
  "ok": true,
  "total": 1,
  "items": [
    { "id": 601, "project_id": "00000000-0000-4000-8000-000000000601", "project_name": "Tasting Room Floor", "company": "Brightwater Cider House", "contact_name": "Eli Marchetti", "email": "eli.marchetti@brightwater.example.com", "phone": "816-555-0181", "quote_total": 18450.0, "quote_date": "2026-10-09", "status": "new", "possible_duplicate": null }
  ]
}
```

#### `POST /api/bd/review/candidates/{id}/add` (salesperson, assistant; not built yet)

One-click add. Creates the company (if new) and the contact with `source: "proposal_tool"` and
`last_quote_date` = the quote date. Optional overrides:

```json
{ "category": "bd", "owner_id": 1, "lead_source": "Current Account" }
```

```json
{ "ok": true, "candidate": { "id": 601, "status": "added" }, "contact": { "id": 37, "name": "Eli Marchetti", "company": { "id": 37, "name": "Brightwater Cider House" }, "source": "proposal_tool", "last_quote_date": "2026-10-09", "duplicate_of": null } }
```

#### `POST /api/bd/review/candidates/{id}/ignore` (salesperson, assistant; not built yet)

```json
{ "ok": true, "candidate": { "id": 602, "status": "ignored" } }
```

Add or ignore on a candidate that is no longer `new` is 409 with the page's own words: "Already added
to BD." or "Already marked as not a BD contact." An unknown id is 404 ("That person is not on the
review list.").

#### `GET /api/bd/analytics` (manager; not built yet)

Query: `from`, `to` (dates, default 1 Jan this year to today, Central), `owner` (user id, default
all). A range whose start is after its end is 400. Response: `{ "ok": true, "analytics": Analytics }`
(see the object above), counted as its metric table says.

#### `GET /api/bd/analytics/export.csv` (manager; not built yet)

Same query. Answers `text/csv`, one row per contact: company, name, owner, category, lead source,
frequency, touches this year, last live, cadence status, confirmed. Not JSON.

#### `POST /api/bd/webhooks/telephony/quo` (public: the provider's signature, once built; not built yet)

The one BD route with no sign-in, at this exact path only (`main._AUTH_PUBLIC_PATHS` lists it; nothing
else under `/api/bd/webhooks/` is public). Body is the provider's own payload (Quo first). Once built,
the server verifies the signature (a bad one is 401), stores the event once (`integration_events`,
keyed on provider + event id), matches the number by its last 10 digits, and creates or updates the
interaction on `(provider, external_id)`. A later transcript or summary event updates the same row.
Unknown numbers go to the unmatched calls.

```json
{ "ok": true, "event_id": "EVa1b2c3", "result": "interaction_updated", "interaction_id": 109 }
```

`result`: `interaction_created` | `interaction_updated` | `unmatched` | `duplicate` | `ignored`.
