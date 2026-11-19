# BD CRM API contract

> Moved here from the BD CRM repo for the move into the proposal tool (#802). It still describes
> BD as it stood there: the routes move under `/api/bd/` and mock mode goes as each ticket of #802
> lands, and this file is updated with them. `backend/tests/test_bd_serialize.py` parses its JSON
> examples. Every person and email in it is fictional.

The frontend is built first against `frontend/js/mock-data.js` (`const MOCK = true` in `js/api.js`).
The backend (Phase 2 on) must answer **these routes with these shapes**, so flipping `MOCK = false`
changes nothing on screen. A change to this file is a change to both sides.

Every example below is real JSON (a test parses each fenced `json` block). Example values come from
the mock data, so the fictional names, `555-01xx` numbers and `example.com` emails match it.

## Ground rules

- **Base path** `/api`. JSON in, JSON out, UTF-8. Signed-in calls send `Authorization: Bearer <Supabase
  access token>` (Google sign-in, `@wetreadwell.com` only). The only routes without a user token are
  `/api/health`, `/api/public-config`, `/api/webhooks/telephony/{provider}` (signature-checked) and
  `/api/admin/bd-candidates` (proposal-tool service token).
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
| 401 | `unauthenticated` | No token, expired token, or not a `@wetreadwell.com` Google account. |
| 403 | `forbidden` | Signed in but the role may not do this. |
| 404 | `not_found` | Unknown id. |
| 409 | `conflict` | The action is not possible in the current state (task already done, candidate already added, batch already built this week, send outside 8 am–6 pm Central). |
| 429 | `rate_limited` | Too many AI calls in a minute. |
| 503 | `unavailable` | AI or the phone provider is down. AI routes return a fallback instead of this where they can. |

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
  taken off by hand** while the contact is still due: `POST /api/tasks/{id}/snooze` and
  `POST /api/tasks/{id}/done` answer `409` on it. It closes when a call (any outcome), voicemail,
  meeting, hosted event, **email or text** is logged for the contact (a note does not) **and that
  leaves the contact no longer due**: it closes on this week's list **and on a later week's** (the
  Friday build has already made next week's, so a text sent on the Saturday clears it there too).
  An entry dated so long ago (or in the future) that the contact is still due closes nothing. A
  maintenance task whose contact is no longer due (a stale one: reopened after its follow-up, or the
  contact became a BD contact) is not pinned and can be skipped or marked done like any task. When a
  contact changes hands (`PATCH /api/contacts/{id}` with a new `owner_id`) the previous owner's open
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
| `quotes_from_bd` | Proposal-tool quotes dated in the range to contacts on the BD list (and of `owner`, when given): count, sum of totals. The mock reads them from `BDMock.bd_quotes`. |
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
Monday a missed week is built by an admin (`POST /api/admin/weekly/run` with that Monday). The
worker runs only where the server's `WEEKLY_ENABLED` is on (off on the preview). `run_day` is
`friday`, `saturday` or `sunday` only: the run builds NEXT week's list and closes this week's open
tasks, so an earlier day would snooze the list while it is still being worked. Each salesperson's
batch is built and committed on its own: one that fails is logged and tried again on the next
tick, and never costs the others their list.

## Routes

### Meta

#### `GET /api/health` — public

```json
{ "status": "ok", "db": "ok", "version": "sha-3f9c2a1" }
```

#### `GET /api/public-config` — public

What `auth.js` needs before sign-in. Only public values.

```json
{ "supabase_url": "https://example.supabase.co", "supabase_anon_key": "public-anon-key", "allowed_domain": "wetreadwell.com", "mock": false, "preview_mock": false }
```

`preview_mock` is the server's `BD_PREVIEW_MOCK` (default `false`). It only matters behind **the
sign-in gate** (added 2026-11-05 for the deployed preview on `bd.wetreadwell.com`):

- A page served from **any host other than `localhost` / `127.0.0.1`** (or a file) renders nothing
  until a real Google sign-in has a session (`auth.js`, Supabase) **and** `GET /api/me` on this
  server answers 200 (an active `users` row; `auth.resolve_user` is unchanged, so an unknown
  `@wetreadwell.com` account gets its 403 sentence and nothing else). No API call, mock or live, is
  answered before that (`js/api.js` holds them until `BDApi.openGate`).
- Then the mode: `preview_mock: true` -> the fictional mock data (`?as=troy` etc. picks the mock's
  persona, `?mock=0` switches to this server's data with the user's real role); `preview_mock:
  false` -> this server's data, and no URL flag can switch the page to the mock.
- On `localhost` / `127.0.0.1` nothing changed: mock mode needs no sign-in and `?as=` / `?mock=`
  work as before.
- **The gate is not a confidentiality control.** It runs in the browser: the static files are
  served to anyone without a session (every page, every script, and `js/mock-data.js` with its
  invented contacts and the staff addresses and roles it uses), and the gate can be skipped from
  the browser's developer tools. The server's own data stays protected by the bearer check on
  every non-public `/api/*` route. So everything under `frontend/` must stay fictional.

#### `GET /api/me` — any

```json
{
  "ok": true,
  "user": { "id": 1, "name": "Troy", "email": "troy@example.com", "role": "salesperson", "active": true, "last_seen_at": "2026-11-04T08:12:00-06:00" },
  "today": "2026-11-04",
  "timezone": "America/Chicago",
  "can": { "send": true, "analytics": false, "admin": false, "admin_area": false, "import": false, "run_batch": false, "week": true }
}
```

`can` drives which buttons and nav items show. The server still checks every call.

| Key | True for | Drives |
|---|---|---|
| `week` | salesperson, manager, admin | This Week in the menu, and `/index.html` as the home page. Without it (the assistant) the home page is Contacts. |
| `send` | salesperson, admin | Send follow-up, log calls. |
| `analytics` | manager, admin | Analytics. |
| `admin` | admin, super_admin | The full Admin page: users, settings, Friday list, telephony. |
| `admin_area` | assistant, admin | Opening `/admin.html` at all; the assistant sees only unmatched calls and import history. |
| `import` | salesperson, assistant, admin | Import workbook. |
| `run_batch` | admin | Make this week's list now. |

While mock data is on, `/api/me` (and `/api/public-config`) also carry `"mock": true`.

#### `GET /api/settings` — any

```json
{ "ok": true, "settings": { "bd_cadence": "quarterly", "default_frequency": { "maintenance": 3 }, "maintenance_touch_days": 120, "lead_sources": ["Current Account", "DSBC Sales", "Website Lead", "Other/Misc"], "timezone": "America/Chicago" } }
```

(Full object: see Settings.)

#### `GET /api/users` — any

The compact list of active users, for owner pickers on any role's screen (`/api/admin/users`, with
emails and sign-in times, stays admin only). Paged by `limit` and `offset` like every other list.

```json
{ "ok": true, "items": [{ "id": 1, "name": "Troy", "role": "salesperson" }, { "id": 2, "name": "Marisol", "role": "assistant" }], "total": 2 }
```

### This Week

#### `GET /api/week` — salesperson (own); manager, admin (any owner)

Query: `owner` (user id), `week_start` (a Monday, default this week in Central). `owner` defaults to
me for a salesperson; for a manager or admin (who has no week of their own) it defaults to the first
active salesperson (with none, the caller's own empty week). `owner` is a user id: a whole number
or digit text (spaces around it are ignored); anything else (`true`, `[1]`, `1.5`, `"1e0"`) is the
`404` "That user does not exist.". `week_start` is exactly "YYYY-MM-DD" (nothing around it, years
1–9998) and a Monday, else `400`; an empty one means this week. An assistant gets `403` ("The weekly list is the salesperson's."); her pages never
call it. Only a salesperson has a weekly list: an `owner` who does not exist, or who is not a
salesperson (an assistant, manager or admin), is `404` here and on `ten-more` and `weekly/run`.
`ten-more` and `weekly/run` never fall back to the caller: when nobody active is a salesperson they
are the same `404` ("Hanz has no weekly list. Only salespeople do.").

```json
{
  "ok": true,
  "week": {
    "week_start": "2026-11-02",
    "week_end": "2026-11-08",
    "owner": { "id": 1, "name": "Troy" },
    "batch": { "id": 41, "kind": "friday", "owner": { "id": 1, "name": "Troy" }, "week_start": "2026-11-02", "generated_at": "2026-10-30T16:00:00-05:00" },
    "batches": [{ "id": 41, "kind": "friday", "owner": { "id": 1, "name": "Troy" }, "week_start": "2026-11-02", "generated_at": "2026-10-30T16:00:00-05:00" }],
    "tasks": [
      {
        "id": 403, "batch_id": 41,
        "contact": { "id": 17, "name": "Megan Tully", "title": "Senior Estimator", "company": { "id": 17, "name": "Halvorsen & Pike Contractors" }, "phone": "913.555.0117", "phone_e164": "+19135550117", "email": "megan.tully@halvorsenpikec.example.com", "category": "bd", "confirmed": true, "lead_source": "Current Account", "last_live_at": "2026-11-02T09:20:00-06:00", "cadence_status": "complete" },
        "kind": "followup", "reason": "Promised a call by Tue, Nov 3. Key account.", "reasons": ["Promised a call by Tue, Nov 3", "Key account"],
        "score": 73, "status": "done", "done_at": "2026-11-02T09:30:00-06:00", "snoozed_until": null
      }
    ],
    "done_count": 4,
    "total": 10,
    "due_count": 0,
    "pace": { "year": 2026, "as_of": "2026-11-04", "required_to_date": 127.4, "completed": 61, "target_total": 151, "pct": 40, "delta": -66, "label": "2026 BD Pace: 40% — 66 interactions behind pace" },
    "weekly_meetings": { "count": 1, "goal": 5, "non_dsbc_website": 1, "min": 1 },
    "touches_this_week": 2
  }
}
```

#### `POST /api/week/ten-more` — salesperson

"Give Me 10 More". Builds a `ten_more` batch of the next 10 of the weekly ranking (due maintenance
contacts first, then by score; a maintenance contact that is not due is never suggested), skipping **anyone already on
this week's list in any state** (open, done or snoozed), so "the next 10" never repeats a name the
salesperson has seen this week, and anyone still open on a later week's list (next week's Friday
batch exists from Friday 16:00, so a press on Friday evening or the weekend never doubles a name);
anyone tried in the last 3 days is skipped too. Works any day; can be
pressed again; never changes the Friday 10's `done_count`/`total`. Returns the whole week.

Request:

```json
{ "owner": 1 }
```

Response: `{ "ok": true, "week": WeekView }` with the new batch last in `batches` and its tasks
appended. If nobody is left to suggest, `409 conflict` with message "Everyone on your list is already
covered this week."

`owner` is optional: a salesperson's own list by default, or (for an admin) the first active
salesperson, as on `GET /api/week`. The checks run in this order: an assistant or manager is `403`
("Your role can't do that."); an `owner` who does not exist or is not a salesperson is `404`; a
salesperson naming someone else's list is `403` ("You can ask for more only on your own list.");
then the `409`. The batch belongs to this Central week. `GET /api/week` itself never builds a batch:
a week with none is the empty state.

#### `POST /api/tasks/{id}/done` — salesperson (task owner)

Marks the task done. Does not log anything by itself (logging a call on that contact while the task is
open marks it done automatically). `done_count`/`total` in the answer are the Friday batch's BD tasks,
as in WeekView.

A `maintenance` task whose contact is still due cannot be marked done by hand: `409 conflict`, message "A maintenance follow-up stays on the list until you log a call, meeting, email or text." (the
rule is about the task's kind and the contact's due state, so a done or snoozed task of a still-due contact gets it too; one whose contact is no longer due is an ordinary task). The checks run in
this order: task `404`, role `403`, own list `403`, body `400`, then this `409`, then the
state `409` ("That task is already done.").

```json
{ "ok": true, "task": { "id": 404, "batch_id": 41, "status": "done", "done_at": "2026-11-04T10:15:00-06:00" }, "done_count": 5, "total": 10 }
```

#### `POST /api/tasks/{id}/snooze` — salesperson

"Not this week." The slot is **not refilled**. The contact is scored again on Friday.

A `maintenance` task whose contact is still due cannot be skipped: `409 conflict`, message "A maintenance follow-up stays on the list until you log a call, meeting, email or text.", checked after the
task (`404`), role and own-list (`403`) and body (`400`) checks and before the state `409` ("Only an
open task can be skipped."). A maintenance task leaves the list only by logging a call, meeting,
email or text.

```json
{ "reason": "Out of office until the 16th" }
```

```json
{ "ok": true, "task": { "id": 406, "status": "snoozed", "snoozed_until": "2026-11-09" }, "done_count": 4, "total": 10 }
```

#### `POST /api/tasks/{id}/reopen` — salesperson

Undo for done or snoozed.

```json
{ "ok": true, "task": { "id": 404, "status": "open", "done_at": null, "snoozed_until": null } }
```

#### `POST /api/tasks/{id}/not-right-person` — salesperson, assistant

Sets the contact's `confirmed` to false, notes who said so, and closes the task as done (the work was
the check). The contact stays on the list.

```json
{ "note": "Laura moved to the Wichita plant. Ask for her replacement." }
```

```json
{ "ok": true, "task": { "id": 408, "status": "done", "done_at": "2026-11-04T10:20:00-06:00" }, "contact": { "id": 13, "confirmed": false, "notes": "Laura moved to the Wichita plant. Ask for her replacement." } }
```

### Contacts

#### `GET /api/contacts` — any

Query (all optional, combine with AND): `q` (name, company, email, title, city, or 3+ phone digits;
case-insensitive, company also matched by its normalized name), `category`
(`bd`|`maintenance`), `owner` (user id), `industry`, `lead_source`, `stage`, `confirmed`
(`true`|`false`), `cadence` (`never`|`behind`|`on_track`|`complete`), `company` (company id),
`duplicates` (`true` = only flagged), `sort` (`name`|`company`|`last_live_at`|`next_due_date`, default
`company`), `limit`, `offset`. Archived contacts are left out unless `archived=true`.

```json
{
  "ok": true,
  "total": 1,
  "items": [
    {
      "id": 30,
      "company": { "id": 30, "name": "Pinecrest Surgical Center" },
      "name": "Andre Fontaine",
      "title": "Facilities Manager",
      "email": "andre.fontaine@pinecrestsurgi.example.com",
      "phone": "816.555.0130",
      "phone_e164": "+18165550130",
      "city": "Olathe, KS",
      "industry": "Healthcare",
      "lead_source": "DSBC Sales",
      "stage": null,
      "category": "bd",
      "account_type": null,
      "owner": { "id": 1, "name": "Troy" },
      "co_owner": null,
      "frequency_per_year": 4,
      "cadence": "quarterly",
      "cadence_source": "global",
      "cadence_override": null,
      "cadence_override_until": null,
      "confirmed": false,
      "importance": 2,
      "next_step": null,
      "next_step_date": null,
      "promised_date": null,
      "last_quote_date": null,
      "last_live_at": null,
      "last_attempt_at": "2026-09-23T09:30:00-05:00",
      "last_followup_at": "2026-09-23T09:30:00-05:00",
      "attempts_since_live": 2,
      "touches_this_year": 0,
      "next_due_date": null,
      "cadence_status": "never",
      "maintenance_due_date": null,
      "maintenance_due": false,
      "duplicate_of": null,
      "source": "workbook",
      "tags": [],
      "notes": "",
      "created_at": "2026-01-12T09:00:00-06:00"
    }
  ]
}
```

#### `GET /api/contacts/duplicates` — any

The "search before you add" check. Query: `company` and/or `email` and/or `phone`, and `except` (a
contact id to leave out, for the contact being edited).

```json
{
  "ok": true,
  "items": [
    { "contact_id": 1, "name": "Dana Whitfield", "company": "Ridgecrest Fabrication Works", "city": "Lenexa, KS", "reason": "Same company name" }
  ]
}
```

`reason`: `Same company name` | `Same email` | `Same phone`.

#### `POST /api/contacts` — salesperson, assistant, admin

`company` is either `{ "id": 1 }` (existing) or `{ "name": "…" }` (found by normalized name or
created). Missing optional fields take the settings defaults. A possible duplicate is saved anyway
(**201**) with `duplicate_of` set; the page shows the banner.

A **BD** contact follows the BD cadence (`settings.bd_cadence`): its stored `frequency_per_year` is
the cadence's number (52 / 12 / 4) and it **cannot be sent**: a BD `frequency_per_year` is `400`
"BD contacts follow the BD cadence. Set a follow-up override instead." (`fields.frequency_per_year`).
The key is refused even as `null`. A **maintenance** contact takes `frequency_per_year` (1 to 52) or `settings.default_frequency.maintenance`.

```json
{
  "company": { "name": "Ridgecrest Fabrication Works" },
  "name": "Corey Lund",
  "title": "Site Supervisor",
  "email": "corey.lund@ridgecrestfabr.example.com",
  "phone": "913.555.0131",
  "city": "Topeka, KS",
  "industry": "Manufacturing",
  "lead_source": "Current Account",
  "category": "bd",
  "owner_id": 1,
  "notes": "Second plant."
}
```

```json
{
  "ok": true,
  "contact": {
    "id": 31,
    "company": { "id": 1, "name": "Ridgecrest Fabrication Works" },
    "name": "Corey Lund",
    "confirmed": false,
    "source": "manual",
    "frequency_per_year": 4,
    "cadence": "quarterly",
    "cadence_source": "global",
    "cadence_status": "never",
    "duplicate_of": { "contact_id": 1, "name": "Dana Whitfield", "company": "Ridgecrest Fabrication Works", "reason": "Same company name" }
  },
  "possible_duplicates": [
    { "contact_id": 1, "name": "Dana Whitfield", "company": "Ridgecrest Fabrication Works", "city": "Lenexa, KS", "reason": "Same company name" }
  ]
}
```

(`contact` is the full Contact object; trimmed here.) A new contact starts `confirmed: false` unless
the request says `"confirmed": true`.

#### `GET /api/contacts/{id}` — any

The contact page in one call.

```json
{
  "ok": true,
  "contact": { "id": 8, "name": "Ray Duchene", "company": { "id": 8, "name": "Meridale Fleet Services" }, "cadence_status": "never", "attempts_since_live": 3 },
  "open_task": { "id": 407, "batch_id": 41, "kind": "new", "status": "done", "reason": "Never reached after 2 tries. Needs confirming: still the right person?" },
  "pending_recommendation": { "id": 72, "contact_id": 8, "interaction_id": 1074, "action": "Try Ray again", "due_date": "2026-11-09", "reason": "Voicemail, no live talk yet. Try again in a week.", "source": "fallback", "status": "pending", "created_at": "2026-11-02T14:35:00-06:00", "decided_at": null, "decided_by": null },
  "missed_call": { "interaction_id": 1074, "occurred_at": "2026-11-02T14:30:00-06:00", "followup_sent": false }
}
```

(`contact` is the full Contact object.) `open_task` is this week's task for the contact or `null`.
`missed_call` is the latest voicemail or no-answer call with no follow-up sent and no live talk since,
**made in the last 14 days** (an older call gets no card), else `null`; it drives the "Send follow-up:
Email | Text | Nothing" card.

#### `PATCH /api/contacts/{id}` — salesperson, assistant, admin; manager for the cadence fields only

Any subset of the editable fields: `company`, `name`, `title`, `email`, `phone`, `city`, `industry`,
`lead_source`, `stage`, `category`, `account_type`, `owner_id`, `co_owner_id`, `frequency_per_year`,
`cadence_override`, `cadence_override_until`, `importance`, `next_step`, `next_step_date`,
`promised_date`, `tags`, `notes`. Derived fields are ignored.

**Size limits** (the same on `POST /api/contacts`): `notes` 20,000 characters, `next_step` 500, `email`
254, every other text field and the contact's `name` (and a new company's name) 200; at most 50 `tags`
of 60 characters each. Over a limit is `400` with `fields.<name>` "Keep this to N characters or fewer."
(`tags`: "Use at most 50 tags of 60 characters or fewer.").

**How often to follow up.**

- `frequency_per_year` belongs to **maintenance** contacts (1 to 52). On a BD contact (or when the
  same request makes the contact BD) it is `400` with `fields.frequency_per_year` "BD contacts follow
  the BD cadence. Set a follow-up override instead."
- A BD contact's override is `cadence_override` (`weekly`, `monthly` or `quarterly`) with
  `cadence_override_until` (a date, today or later; it is the last day of the override). They are set
  together, or both left alone: a word without a day is `400` "Pick the last day of the override.", a day
  without a word is `400` "Pick how often first.", a day before today is `400` "Pick a day from today
  on.", and any other word is `400` "Pick weekly, monthly or quarterly." (each under its own field).
  A key left out keeps what is stored. `{ "cadence_override": null }` clears both.
  Only `null` clears: an empty string is not "nothing" (`""` for the word is the "Pick weekly, monthly or
  quarterly." `400`, `""` for the day is `400` "Use a date (YYYY-MM-DD).") and the day must be exactly
  `YYYY-MM-DD` with no spaces or line break around it.
- A PATCH that changes `category` without sending `frequency_per_year` resets the stored number to the
  new category's default (maintenance: `settings.default_frequency.maintenance`; BD: the cadence's
  number), so a BD contact's 52 or 12 never becomes a maintenance contact's target.
- **Manager:** may send only `cadence_override`, `cadence_override_until` and `frequency_per_year`;
  any other key is `403` "Managers can change only how often to follow up." (and nothing is saved).
  The salesperson, assistant and admin may set the override too.
- Both log a `frequency_changed` event (the timeline reads "Cadence changed") with the change in words:
  "Every quarter to every month until Sun, Jan 31", "Back to the BD cadence, every quarter",
  "3 a year to 2 a year". Saving what is already stored logs nothing.

`"duplicate_of": null` clears a duplicate flag ("Not a duplicate"): **assistant and admin only**
(`403` for a salesperson); any other value is `400`. It logs a `duplicate_cleared` event.

When the edit changes the company, email or phone, the duplicate check runs again for the changed
fields (as `POST /api/contacts` does): matches come back in `possible_duplicates`, and an unflagged
contact gets `duplicate_of` set (a flag, not a block; the edit is saved). Otherwise
`possible_duplicates` is `[]`.

```json
{ "cadence_override": "monthly", "cadence_override_until": "2027-01-31", "importance": 3 }
```

```json
{ "ok": true, "contact": { "id": 2, "frequency_per_year": 12, "cadence": "monthly", "cadence_source": "override", "cadence_override": "monthly", "cadence_override_until": "2027-01-31", "importance": 3, "next_due_date": "2026-10-15", "cadence_status": "behind" }, "possible_duplicates": [] }
```

#### `POST /api/contacts/{id}/confirm` — salesperson, assistant

```json
{ "confirmed": true }
```

```json
{ "ok": true, "contact": { "id": 30, "confirmed": true } }
```

#### `POST /api/contacts/{id}/archive` — salesperson, assistant, admin

Takes the contact off every list and batch. Interactions are kept. An open task on a weekly list
closes as `snoozed`. `{"archived": false}` restores, and it undoes that: a task the archive closed on
**this** week's list, or on a later one (next week's Friday batch, built on Friday at 16:00), opens
again (an earlier week's stays closed, and a task that was already done or
skipped before the archive is left as it was).

```json
{ "archived": true, "reason": "Company closed" }
```

```json
{ "ok": true, "contact": { "id": 22, "archived_at": "2026-11-04T10:30:00-06:00" } }
```

#### `POST /api/contacts/{id}/merge` — assistant, admin (later)

Moves interactions, tasks and tags of `{id}` onto `into_id`, archives `{id}`, logs an event.

```json
{ "into_id": 1 }
```

```json
{ "ok": true, "contact": { "id": 1, "name": "Dana Whitfield" }, "merged_id": 31 }
```

### Companies

#### `GET /api/companies` — any

Query: `q` (type-ahead on name), `limit`, `offset`.

```json
{ "ok": true, "total": 1, "items": [{ "id": 10, "name": "Prairiefold Foods", "city": "Topeka, KS", "industry": "Food Processing", "contact_count": 1, "created_at": "2026-01-12T09:00:00-06:00" }] }
```

#### `GET /api/companies/{id}` — any

```json
{
  "ok": true,
  "company": { "id": 1, "name": "Ridgecrest Fabrication Works", "city": "Lenexa, KS", "industry": "Manufacturing", "contact_count": 2, "created_at": "2026-01-12T09:00:00-06:00" },
  "contacts": [
    { "id": 1, "name": "Dana Whitfield", "title": "Plant Manager", "company": { "id": 1, "name": "Ridgecrest Fabrication Works" }, "phone": "913-555-0101", "phone_e164": "+19135550101", "email": "dana.whitfield@ridgecrestfabr.example.com", "category": "bd", "confirmed": true, "lead_source": "Current Account", "last_live_at": "2026-07-22T11:05:00-05:00", "cadence_status": "behind" }
  ]
}
```

#### `POST /api/companies` — salesperson, assistant, admin

```json
{ "name": "Brightwater Cider House", "city": "Kansas City, MO", "industry": "Restaurant" }
```

```json
{ "ok": true, "company": { "id": 37, "name": "Brightwater Cider House", "city": "Kansas City, MO", "industry": "Restaurant", "contact_count": 0, "created_at": "2026-11-04T10:40:00-06:00" }, "possible_duplicates": [] }
```

#### `PATCH /api/companies/{id}` — salesperson, assistant, admin

```json
{ "name": "Prairiefold Foods", "city": "Topeka, KS" }
```

```json
{ "ok": true, "company": { "id": 10, "name": "Prairiefold Foods", "city": "Topeka, KS", "industry": "Food Processing", "contact_count": 1, "created_at": "2026-01-12T09:00:00-06:00" } }
```

### Interactions (timeline and logging)

#### `GET /api/contacts/{id}/interactions` — any

Newest first. Includes `events` (created, confirmed, owner changed, merged) so the timeline is one list.

```json
{
  "ok": true,
  "items": [
    { "type": "interaction", "at": "2026-11-02T09:20:00-06:00", "interaction": { "id": 1073, "contact_id": 17, "kind": "call", "direction": "out", "counts_as_touch": true, "occurred_at": "2026-11-02T09:20:00-06:00", "duration_s": 480, "outcome": "answered", "summary": "Spring bid list is out in January. Wants us on three bids.", "transcript": null, "recording_url": null, "provider": "manual", "external_id": null, "user": { "id": 1, "name": "Troy" } } },
    { "type": "event", "at": "2026-01-12T09:00:00-06:00", "event": { "action": "created", "by": { "id": 4, "name": "Hanz" }, "detail": "Imported from the workbook" } }
  ]
}
```

`event.action` words are labelled by the frontend VERB map (`created`, `confirmed`, `unconfirmed`,
`duplicate_cleared`, `owner_changed`, `frequency_changed` ("Cadence changed"), `merged`, `archived`, `restored`,
`added_from_quote`). `unconfirmed` reads "marked this contact as not confirmed": it is logged both by
the "Still the right person?" switch and by the weekly list's "Not the right person".

#### `POST /api/contacts/{id}/interactions` — salesperson, assistant (notes only), admin

Log a call, meeting, note, etc. by hand. The server sets `counts_as_touch`, updates the contact's
derived fields, marks this week's open task done **for a call (any outcome), voicemail, meeting or
hosted event only** (a note, an email or a text never closes a new or follow-up task: they are not
touches), with one exception: a **`maintenance` task closes on any kind but a note** (call of any
outcome, voicemail, meeting, hosted event, email or text), because any of them is the follow-up it
asks for, **when that leaves the contact no longer due**, on this week's list or a later week's (an
entry dated so far back that the contact is still due closes nothing). Editing a note into one of
those kinds (`PATCH /api/interactions/{id}`) and attaching an unmatched call close it the same way. It also clears a kept `promised_date`, and, for a call, voicemail, meeting or hosted event,
creates a pending Recommendation (an email or text gets none). `task` in the answer is `null` when
no task was closed.

```json
{
  "kind": "call",
  "outcome": "voicemail",
  "occurred_at": "2026-11-04T10:05:00-06:00",
  "duration_s": 40,
  "summary": "Left a voicemail about the dock coating."
}
```

(`kind: "call"` with `outcome: "voicemail"` is stored as `kind: "voicemail"`.)

```json
{
  "ok": true,
  "interaction": { "id": 1077, "contact_id": 16, "kind": "voicemail", "direction": "out", "counts_as_touch": false, "occurred_at": "2026-11-04T10:05:00-06:00", "duration_s": 40, "outcome": "voicemail", "summary": "Left a voicemail about the dock coating.", "transcript": null, "recording_url": null, "provider": "manual", "external_id": null, "user": { "id": 1, "name": "Troy" } },
  "contact": { "id": 16, "last_attempt_at": "2026-11-04T10:05:00-06:00", "attempts_since_live": 1, "cadence_status": "never" },
  "task": { "id": 409, "status": "done", "done_at": "2026-11-04T10:05:00-06:00" },
  "recommendation": { "id": 75, "contact_id": 16, "interaction_id": 1077, "action": "Try Phil again", "due_date": "2026-11-11", "reason": "Voicemail. Try again in a week.", "source": "fallback", "status": "pending", "created_at": "2026-11-04T10:05:00-06:00", "decided_at": null, "decided_by": null },
  "missed_call": true
}
```

`missed_call: true` tells the page to show "Send follow-up: Email | Text | Nothing".

#### `PATCH /api/interactions/{id}` — the user who logged it, admin

Fix a summary, outcome or time. Changing `kind`/`outcome` recomputes `counts_as_touch` and the contact.
An edit that makes it a touch, or moves a touch to another time, meets the contact's `promised_date`
and next step on or before its Central date (both cleared), as a newly logged touch does. A `kind`
change sets `direction` to `null` for a meeting, hosted event or note, and otherwise keeps the old
one (`out` when there is none). An assistant may only keep it a note: a `kind`/`outcome` that makes it
anything else is `403` "Assistants can add notes only." (after the `400` for a bad kind or outcome).

```json
{ "outcome": "answered", "summary": "Picked up after all. Wants a price in December." }
```

```json
{ "ok": true, "interaction": { "id": 1077, "kind": "call", "outcome": "answered", "counts_as_touch": true } }
```

#### `DELETE /api/interactions/{id}` — admin

```json
{ "ok": true, "deleted": 1077 }
```

### AI next action

#### `POST /api/interactions/{id}/recommend` — salesperson

Ask (again) for a suggestion. Runs the AI when `AI_ENABLED`, else the fallback table. Never fails just
because the AI is down: it returns `source: "fallback"`.

```json
{}
```

```json
{ "ok": true, "recommendation": { "id": 73, "contact_id": 3, "interaction_id": 1075, "action": "Call about the clean room quote", "due_date": "2027-01-11", "reason": "Priya said the quote is in their January budget. Call early in January.", "source": "ai", "status": "pending", "created_at": "2026-11-03T12:06:00-06:00", "decided_at": null, "decided_by": null } }
```

#### `POST /api/recommendations/{id}/confirm` — salesperson

Accept as is (`{}`) or with changes. Sets the contact's `next_step` / `next_step_date`; if the customer
asked for a date, send `"promised": true` to also set `promised_date`.

```json
{ "action": "Call about the clean room quote", "due_date": "2027-01-06", "promised": true }
```

```json
{
  "ok": true,
  "recommendation": { "id": 73, "status": "changed", "due_date": "2027-01-06", "decided_at": "2026-11-04T10:50:00-06:00", "decided_by": { "id": 1, "name": "Troy" } },
  "contact": { "id": 3, "next_step": "Call about the clean room quote", "next_step_date": "2027-01-06", "promised_date": "2027-01-06" }
}
```

#### `POST /api/recommendations/{id}/dismiss` — salesperson

```json
{ "ok": true, "recommendation": { "id": 74, "status": "dismissed", "decided_at": "2026-11-04T10:52:00-06:00", "decided_by": { "id": 1, "name": "Troy" } } }
```

### Missed-call follow-up

#### `POST /api/interactions/{id}/draft-followup` — salesperson

`{id}` is the voicemail or no-answer call. Drafts from the contact, recent history and the attempt.

```json
{ "channel": "sms" }
```

```json
{ "ok": true, "draft": { "id": 82, "contact_id": 8, "interaction_id": 1074, "channel": "sms", "to": "+18165550108", "subject": null, "body": "Hi Ray, Troy at Treadwell. Just left you a voicemail about the shop floor. Is there a good time to talk this week?", "source": "fallback", "status": "draft" } }
```

#### `POST /api/interactions/{id}/send-followup` — salesperson

Sends the (possibly edited) draft, by Resend for email or the phone provider for SMS, and logs it as an
`email`/`sms` interaction with `counts_as_touch: false`. Email sends only 8 am–6 pm Central (`409`
otherwise). `{"channel": "none"}` records "Nothing" and hides the card.

```json
{ "draft_id": 81, "channel": "email", "subject": "Shop floor at Meridale Fleet Services", "body": "Hi Ray,\n\nI tried you by phone on Monday about the shop floor. Is there a good time this week or next?\n\nThanks,\nTroy\nTreadwell" }
```

```json
{
  "ok": true,
  "draft": { "id": 81, "status": "sent" },
  "interaction": { "id": 1078, "contact_id": 8, "kind": "email", "direction": "out", "counts_as_touch": false, "occurred_at": "2026-11-04T10:55:00-06:00", "duration_s": null, "outcome": null, "summary": "Shop floor at Meridale Fleet Services", "transcript": null, "recording_url": null, "provider": "resend", "external_id": "re_7d1f2c", "user": { "id": 1, "name": "Troy" } }
}
```

`{"channel": "none"}` answers with nothing sent:

```json
{ "ok": true, "draft": null, "interaction": null }
```

A second send for the same call is `409` ("A follow-up was already handled for this call."). A
follow-up never counts toward pace and never closes a new or follow-up weekly task; the one
exception is a `maintenance` task, which the email or text it logs closes (any logged follow-up
does; see `POST /api/contacts/{id}/interactions`).

### Potential BD Contacts (review)

#### `GET /api/review/candidates` — salesperson, assistant, manager, admin

Query: `status` (`new` (default) | `added` | `ignored` | `all`), `since` (date, default 90 days ago). Pulls fresh Direct quotes from the
proposal tool, adds pushed ones, and leaves out anyone already on the list by
`(normalized company, lower-case email)`.

```json
{
  "ok": true,
  "total": 1,
  "items": [
    { "id": 91, "project_id": "3f1c9a2e-0b6d-4c1e-9a77-1d2e3f4a5b60", "project_name": "Tasting Room Floor", "company": "Brightwater Cider House", "contact_name": "Eli Marchetti", "email": "eli.marchetti@brightwater.example.com", "phone": "816.555.0181", "quote_total": 18450.0, "quote_date": "2026-10-09", "status": "new", "possible_duplicate": null }
  ]
}
```

#### `POST /api/review/candidates/{id}/add` — salesperson, assistant, admin

One-click add. Creates the company (if new) and the contact with `source: "proposal_tool"`,
`last_quote_date` = the quote date. Optional overrides:

```json
{ "category": "bd", "owner_id": 1, "lead_source": "Current Account" }
```

```json
{ "ok": true, "candidate": { "id": 91, "status": "added" }, "contact": { "id": 37, "name": "Eli Marchetti", "company": { "id": 37, "name": "Brightwater Cider House" }, "source": "proposal_tool", "last_quote_date": "2026-10-09", "duplicate_of": null } }
```

#### `POST /api/review/candidates/{id}/ignore` — salesperson, assistant, admin

```json
{ "ok": true, "candidate": { "id": 96, "status": "ignored" } }
```

Add or ignore on a candidate that is no longer `new` is `409` with the page's own words: "Already
added to BD." or "Already marked as not a BD contact." An unknown id is `404` ("That person is not on
the review list.").

#### `POST /api/admin/bd-candidates` — proposal-tool service token only

The proposal tool's "Add to BD" button. Header `Authorization: Bearer <BD_SERVICE_TOKEN>` (its own
token, never the portal's). `add_now: true` adds the contact straight away (the button); `false` just
queues it for the review.

```json
{ "project_id": "8a4b2c1d-5e6f-4a7b-8c9d-0e1f2a3b4c5d", "project_name": "Warehouse 2 Sealer", "company": "Switchgrass Construction", "contact_name": "Mia Thornton", "email": "mia.thornton@switchgrass.example.com", "phone": "816-555-0182", "quote_total": 42800.0, "quote_date": "2026-10-16", "added_by_email": "troy@example.com", "add_now": true }
```

```json
{ "ok": true, "candidate_id": 92, "status": "added", "contact_id": 38, "possible_duplicate": { "contact_id": 15, "name": "Angela Ruiz", "company": "Switchgrass Construction" } }
```

Idempotent on `(project_id, email)`: a repeat returns the same ids with `"status": "added"`.

### Analytics

#### `GET /api/analytics` — manager, admin

Query: `from`, `to` (dates, default 1 Jan this year to today), `owner` (user id, default all).

Response: `{ "ok": true, "analytics": Analytics }` (see the object above).

#### `GET /api/analytics/export.csv` — manager, admin

Same query. Returns `text/csv`, one row per contact: company, name, owner, category, lead source,
frequency, touches this year, last live, cadence status, confirmed. Not JSON.

### Admin

#### `GET /api/admin/users` — admin

Paged by `limit` and `offset` like every other list.

```json
{ "ok": true, "items": [{ "id": 2, "name": "Marisol", "email": "marisol@example.com", "role": "assistant", "active": true, "last_seen_at": "2026-11-04T09:03:00-06:00" }], "total": 1 }
```

#### `POST /api/admin/users` — admin

```json
{ "email": "greg@example.com", "name": "Greg", "role": "salesperson" }
```

```json
{ "ok": true, "user": { "id": 6, "name": "Greg", "email": "greg@example.com", "role": "salesperson", "active": true, "last_seen_at": null } }
```

Only a `super_admin` may add an `admin` or `super_admin` (`403` otherwise: an admin a plain admin
made could never be changed again).

#### `PATCH /api/admin/users/{id}` — admin (`super_admin` to change an admin)

**You cannot change your own role or sign-in** (`role` or `active` on your own id is `403`, "You
can't change your own role or sign-in."; your own `name` is fine). Changing a user who is an admin,
or making someone an admin, needs `super_admin` (`403` "Only a super admin can change an admin.").

```json
{ "role": "manager", "active": true }
```

```json
{ "ok": true, "user": { "id": 3, "name": "Will", "email": "will@example.com", "role": "manager", "active": true, "last_seen_at": "2026-11-03T16:40:00-06:00" } }
```

#### `PUT /api/admin/settings` — admin

Send only the keys to change. `weekly` and `default_frequency` are **merged** into what is there (send
`{"weekly": {"new_count": 6, "followup_count": 4}}` and the run day, hour and on/off stay). The result
is checked as a whole before anything is kept; a bad PUT changes nothing and is `400` with `fields`:

- `weekly.new_count` and `weekly.followup_count` whole numbers 0–10 that **add up to 10**;
  `run_day` `friday`, `saturday` or `sunday` (the run builds next week's list), `run_hour` 0–23,
  `enabled` true/false; else "Pick Friday, Saturday or Sunday, an hour from 0 to 23, and on or off."
- `bd_cadence` `weekly`, `monthly` or `quarterly`, else "Pick weekly, monthly or quarterly.";
  `default_frequency.maintenance` 1–52 (a sent `default_frequency.bd` is ignored);
  `weekly_meeting_goal` 0–50;
  `non_dsbc_website_min` 0 up to the goal; `ai_enabled` true/false.
- `lead_sources`, `industries`, `stages`, `account_types`: at least one value, no blanks, no repeats
  (case-insensitive). `lead_sources` must keep every `system_lead_sources` value.
  Each list holds at most 100 values of 120 characters or fewer, else "Keep at most 100 values of 120
  characters or fewer."
- Read-only keys (`system_lead_sources`, `interaction_kinds`, `touch_kinds`, `call_outcomes`,
  `timezone`, `maintenance_touch_days`) are ignored.

```json
{ "bd_cadence": "monthly", "default_frequency": { "maintenance": 3 }, "lead_sources": ["Current Account", "DSBC Sales", "Website Lead", "Other/Misc", "Trade Show"] }
```

Response: `{ "ok": true, "settings": Settings }`.

```json
{ "ok": false, "error": "bad_request", "message": "New people and follow-ups must add up to 10.", "fields": { "weekly": "New people and follow-ups must add up to 10." } }
```

#### `POST /api/admin/import` — salesperson, assistant, admin

A manager gets `403` (and `can.import` is false for them). A **salesperson's** upload gives every
contact it adds to that salesperson, whatever the Owner column says, and makes nobody a co-owner, so
a salesperson can never hand contacts to someone else (Hanz, 2026-11-16). A known contact that
already has an owner keeps it (one with no owner gets the uploader), the meetings the file logs are
in the uploader's name, never credited to the contact's owner, and the import history lists
everyone's imports, for a salesperson too (the code review, 2026-11-16). An assistant's or admin's
upload follows the Owner column (a blank or unknown owner goes to the first active salesperson).

`multipart/form-data`: `file` (the workbook `.xlsx` or a `.csv`), `dry_run` (`true` first, then
`false` for "Import now"). Reads
"Business Development Accounts" (header row 5) and "Maintenance Accounts" (header row 5). Trims spaces
and non-breaking spaces from company names, splits `Troy/Greg`, turns Maintenance touch dates into
`meeting` interactions. Idempotent on `(normalized company, lower-case email)`.

Re-importing keeps edits made in the app. The server remembers what the import last wrote to each
field. A field changes only when the file differs from the contact and either the import never wrote
that field or the sheet now holds a different value than last time. A next step (or its date) that a
touch on or after that date already met is never brought back. So the same file imported twice
updates nothing the second time.

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

While mock data is on, the record also has `"mock": true`. The mock really reads a `.csv` (a header
row with at least Company and Name; Email, Phone, Title, City, Industry, Lead Source, Category are
optional): the dry run counts its rows, and "Import now" adds and updates contacts (`source:
"import"`). It cannot open an `.xlsx`, so for the workbook it reports what re-importing the current
list would do (every row already matches).

#### `GET /api/admin/imports` — salesperson, assistant, admin

`{ "ok": true, "items": [Import], "total": N }`, newest first.

#### `POST /api/admin/weekly/run` — admin

"Run Friday batch now." Builds the Friday batch for next week (or this week with `"week_start"`).
`409` if one exists for that owner and week unless `"force": true` (which snoozes the old open tasks).

One salesperson per call: `owner` (default: the first active salesperson, as on `GET /api/week`).
The checks run in this order: not an admin `403`; an `owner` who does not exist or is not a
salesperson `404` (and when nobody active is a salesperson: the build never falls back to the
admin); a `week_start` that is not a Monday "YYYY-MM-DD" `400` (`week_start must be a Monday.`,
fields `{"week_start": "Pick a Monday."}`); a Monday other than this one or next one `400`
(`week_start must be this Monday or next Monday.`, fields `{"week_start": "Pick this Monday or next
Monday."}`: a later week would roll this week's open tasks over to it); then the `409` ("A Friday batch already exists
for Troy that week."). An empty `week_start` means next week; `force` counts when it is truthy. It is
the same build as the Friday worker's: the rollover (see Task) first, then the split from
`settings.weekly`. With `force`, the old batch stays in `batches` (no longer in
`done_count`/`total`) with its open tasks snoozed, and the new one comes after it. Every due
maintenance contact of that salesperson gets a `maintenance` task first (the batch grows past 10 when
many are due), then the BD split is made over the BD contacts only, so `tasks_created` is the
maintenance count plus the BD picks.

```json
{ "owner": 1, "week_start": "2026-11-02", "force": false }
```

```json
{ "ok": true, "batches": [{ "id": 41, "kind": "friday", "owner": { "id": 1, "name": "Troy" }, "week_start": "2026-11-02", "generated_at": "2026-10-30T16:00:00-05:00" }], "tasks_created": 12 }
```

#### `GET /api/admin/telephony` — admin

```json
{ "ok": true, "telephony": { "provider": "null", "connected": false, "last_event_at": null, "unmatched_open": 1, "message": "No phone system connected yet." } }
```

#### `GET /api/admin/unmatched-calls` — assistant, admin

Calls and texts whose number matched no contact. Query: `status` (`open` (default) | `attached` |
`dismissed` | `all`).

```json
{ "ok": true, "items": [{ "id": 61, "provider": "quo", "external_id": "AC990011", "direction": "in", "from_e164": "+19135550199", "occurred_at": "2026-11-03T16:42:00-06:00", "duration_s": 95, "summary": "Caller asked about a quote for a shop floor.", "status": "open" }], "total": 1 }
```

#### `POST /api/admin/unmatched-calls/{id}/attach` — assistant, admin

Attaches the call to a contact (and, with `"save_number": true`, stores the number on the contact).
`outcome` (optional): how the call went, `answered` | `voicemail` | `no_answer`, as the assistant
says. Without it, a call counts as `answered` only when it lasted **60 seconds or more**, else
`no_answer`: a 40-second voicemail must never count as a live conversation.

```json
{ "contact_id": 24, "save_number": true, "outcome": "answered" }
```

```json
{ "ok": true, "unmatched_call": { "id": 61, "status": "attached" }, "interaction": { "id": 1079, "contact_id": 24, "kind": "call", "direction": "in", "counts_as_touch": true, "occurred_at": "2026-11-03T16:42:00-06:00", "duration_s": 95, "outcome": "answered", "summary": "Caller asked about a quote for a shop floor.", "transcript": null, "recording_url": null, "provider": "quo", "external_id": "AC990011", "user": null } }
```

#### `POST /api/admin/unmatched-calls/{id}/dismiss` — assistant, admin

```json
{ "ok": true, "unmatched_call": { "id": 61, "status": "dismissed" } }
```

### Webhooks

#### `POST /api/webhooks/telephony/{provider}` — public, provider signature required

Body is the provider's own payload (Quo first). The server verifies the signature, stores the event
once (`integration_events`, keyed on provider + event id), matches the number by its last 10 digits,
and creates or updates the interaction on `(provider, external_id)`. A later transcript or summary
event updates the same row. Unknown numbers go to the unmatched queue. Bad signature: `401`.

```json
{ "ok": true, "event_id": "EVa1b2c3", "result": "interaction_updated", "interaction_id": 1073 }
```

`result`: `interaction_created` | `interaction_updated` | `unmatched` | `duplicate` | `ignored`.
