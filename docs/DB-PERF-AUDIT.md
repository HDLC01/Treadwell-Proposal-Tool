# Database performance audit

**Read this first: nothing in here has been applied.** No DDL, no migration, no index, no schema
change of any kind was run against either database. Every number below comes from a read-only
query or an `EXPLAIN` I ran against **production Supabase** on 2026-09-16. The recommendations
are for Hanz to accept or reject; two of them need DDL on two separate databases, which is the
one thing that turns a good idea into a 502.

What the numbers are measured against:

| | |
|---|---|
| Database | PostgreSQL 17.6 (Supabase), `max_connections` 60, 16 connections in use at audit time |
| Stats window | `pg_stat_statements` / `pg_stat_user_tables` since 2026-05-22 15:13 UTC — **117 days** |
| Live size | Every table in `public` fits in 1.6 MB or less. The whole schema is smaller than one photo. |
| Biggest tables | `events` 1560 kB (3,635 rows) · `drafts` 1408 kB (51 rows) · `draft_revisions` 1000 kB (40 rows) · `leads` 448 kB (175 rows) |

The headline, before the detail: **the Projects-list query is 39.6% of all database execution
time on this project** — 328 seconds of the 829 seconds Postgres has spent executing anything
since May. It is not slow because of a missing index. It is slow because of how it reads the
draft blob, and that is fixable.

---

## Ranked findings

| # | Finding | Value | Effort | Risk | Needs DDL |
|---|---|---|---|---|---|
| 1 | Projects list detoasts each draft blob 20 times per load | **High** | Medium | Medium | Yes (a view) |
| 2 | How the intake form's answers are stored and read | *(answer, not a defect)* | — | — | No |
| 3 | Portal's connection pool has no liveness check | **Medium** | One keyword | Low | No |
| 4 | Indexes on the hot paths | *(already correct)* | — | — | No |
| 5 | Unread-message count is the only quadratic query | Low *(later)* | Small | Low | No |
| 6 | Things that are already right | *(no action)* | — | — | No |

---

## 1. The Projects list reads every draft blob twenty times over — High

### What it is

`_build_summaries` in `backend/drafts.py` selects ~20 named paths out of the `data` jsonb rather
than the whole blob, to keep the payload small as projects accumulate. The comment there explains
the reasoning and the reasoning is sound — the wire payload really is 19 kB instead of 1,585 kB.

But each `data->>'key'` is a **separate** expression, and `data` is TOASTed on every row. Postgres
detoasts and re-parses the entire jsonb document once per expression. Twenty named paths means
twenty full decompressions of a 38 kB (average) JSON document, per row, per page load.

### The evidence

Same query, same 41 active rows, only the number of JSON expressions changing.
`EXPLAIN (ANALYZE, BUFFERS, SERIALIZE TEXT)` on production:

| Projection | Exec time | Shared buffers | Output |
|---|---|---|---|
| Raw blob, no extraction | 15.9 ms | 234 | 1,585 kB |
| 1 JSON expression | 3.6 ms | 234 | — |
| 5 JSON expressions | 16.1 ms | 1,038 | 5 kB |
| 10 JSON expressions | 35.3 ms | 2,043 | 7 kB |
| **20 JSON expressions (what runs today)** | **62.4 / 64.4 ms** | **3,852** | 19 kB |
| `jsonb_to_record`, same 20 fields | **4.11 / 4.21 ms** | **234** | 19 kB |

The cost is dead linear: about 200 buffers per expression per 41 rows, which is one detoast of one
row's blob. That is the mechanism, proved rather than assumed.

Production agrees. From `pg_stat_statements`, across the **20 distinct normalized shapes** this
query has taken as fields were added release by release:

- 10,989 calls, **328.1 seconds**, 29.9 ms mean
- worst single shape: 2,800 calls, 150.4 s, **53.7 ms mean, 173.9 ms max**, 8,614,349 buffer hits — **3,076 buffers per call** against a table whose heap is six pages
- another shape has already been seen at **320.2 ms**

For scale: pooler authentication (`pgbouncer.get_auth`) is 18.3% of database time, and the
Supabase dashboard plus backups are 8.5%. The Projects list alone is bigger than both together.

### What the fix would be

Detoast once per row and read the fields out of that one copy. `jsonb_to_record` does exactly
this — one function call receives `data` once:

```sql
select d.id, d.owner_email, d.created_at, d.updated_at, d.deleted_at,
       r.project_name, r.work_type, r.deadline, r.archived, r.is_test,
       r.assigned_estimator, r.contact_email, r.proposal_lump_sum, r.computed_bid,
       r.polish_estimate->>'version'   as polish_beta,
       r.generate_result->>'work_type' as has_files,
       r.closed_lost->>'reason' , r.closed_lost->>'at' , r.closed_lost->>'note',
       r.on_hold->>'reason'     , r.on_hold->>'until'  , r.on_hold->>'note',
       r.won->>'at'             , r.handed_off->>'at'
from drafts d
cross join lateral jsonb_to_record(d.data) as r(
  project_name text, work_type text, deadline text, archived text, is_test text,
  assigned_estimator text, contact_email text, proposal_lump_sum text, computed_bid jsonb,
  polish_estimate jsonb, generate_result jsonb, closed_lost jsonb, on_hold jsonb,
  won jsonb, handed_off jsonb)
where d.deleted_at is null
order by d.updated_at desc limit 300;
```

The nested paths still read fine, because by then `polish_estimate` and `closed_lost` are ordinary
in-memory datums rather than TOAST pointers — extracting from them is free.

**I checked that it returns the same answers rather than assuming it.** All 51 rows, every field
compared with `IS DISTINCT FROM`:

- `project_name`, `work_type`, `deadline`, `archived`, `is_test`, `assigned_estimator`,
  `contact_email`, `proposal_lump_sum`, `polish_beta`, `has_files` — **0 differences**
- `computed_bid` — **33 rows differ**, and only in one specific way: where the stored value is
  JSON `null`, `data->'computed_bid'` returns a jsonb `null` while `jsonb_to_record` returns SQL
  NULL. Over PostgREST both serialize to JSON `null`, so `_bid_total` receives Python `None`
  either way. The 10 rows holding a real object are identical; the 8 rows missing the key are
  identical.

### What it would cost, and the risk

PostgREST cannot express `jsonb_to_record` in a `select=` parameter, so this needs a **view**
(`drafts_card`) that `drafts.py` selects from, or an RPC. That is DDL, and it has to land on
**both** databases — production Supabase and the separate staging Postgres — or staging 502s.
Staging also needs `notify pgrst, 'reload schema'` afterwards.

**The failure mode you must guard.** `jsonb_to_record` raises on a non-object:

```
ERROR: 22023: cannot call populate_composite on an array
```

Today 0 of 51 rows are anything but an object, and there is **no CHECK constraint** on
`drafts.data` stopping one from being written. So the view must read
`case when jsonb_typeof(data) = 'object' then data else '{}'::jsonb end`, or the column needs
`CHECK (jsonb_typeof(data) = 'object')`. A SQL NULL is already safe — I confirmed that
`jsonb_to_record(NULL)` returns one all-NULL row rather than dropping the project off the board.

The existing full-blob fallback in `_build_summaries` should stay exactly as it is; it already
covers "PostgREST refused this select", which is what a missing view looks like.

### Is it urgent?

**No, and I would rather say so than oversell it.** 51 drafts and a 60-second list cache mean only
about 93 uncached list reads reach the database per day — roughly 2.8 seconds of database time a
day. Nobody is suffering.

The reason to do it is the slope. Cost is `rows x expressions`, the `limit` is already 300, and
every new card field adds another full pass over every blob. At 150 drafts today's 62 ms becomes
roughly 190 ms of pure server time before a byte moves. The 320 ms maximum already recorded is
what that feels like. Fixing it now is cheap; fixing it at 300 drafts is the same work under
pressure.

---

## 2. How the intake form's answers are stored and read — the answer to the question

### The write path

The browser holds the whole project as one state blob and PUTs **all of it** 2.5 seconds after the
last keystroke (`frontend/shared.js`, the `scheduleServerSave` debounce). `save_draft` then runs
two statements: a `SELECT id,data` to carry forward the three server-owned keys (`is_test`,
`archived`, `assigned_estimator` — the comment in `drafts.py` explains why the server must own
them), and an `UPDATE`.

Measured over 117 days:

| Statement | Calls | Mean | Max |
|---|---|---|---|
| `select id,data where id=$1` (the pre-read) | 1,831 | 0.613 ms | 15.3 ms |
| `update drafts set data=..., updated_at=...` | 2,456 | 4.694 ms | 42.7 ms |
| `select id,data,owner_email,... where id=$1` (opening a project) | 1,063 | 0.997 ms | 13.6 ms |

About 21 autosaves a day. This is not costing anything.

### What is actually in the blob

Across all 51 drafts:

| | |
|---|---|
| Uncompressed JSON | 1,929 kB |
| Stored on disk (TOAST, compressed) | 822 kB — 2.35x compression |
| Per draft | average 38 kB · median 14 kB · **max 285 kB** · 3 drafts over 100 kB |
| `proposal_payload` | **1,528 kB — 79% of everything** |
| `priced_tabs` | 75 kB |
| `cell_values` | **30 kB — 1.6%** |

### The verdict

**The intake form's own answers are not costing anything, and their access pattern is right.** A
project is read by primary key, whole, in one round trip — which is correct, because the form
genuinely needs all of it. `cell_values`, the estimate-grid answers, are 1.6% of the blob. Nothing
here is worth restructuring.

What matters is the second-order effect. `proposal_payload` — the frozen render payload the
customer's PDF is rebuilt from — is 79% of the blob, and it is what pushes **every** row past the
TOAST threshold. TOASTing is what makes finding 1 expensive. The intake data is the victim here,
not the cause.

**Splitting `proposal_payload` into its own column would not fix that**, and I checked before
suggesting it: without it the average blob is (1,929 - 1,528) kB over 51 rows ≈ **7.9 kB**, still
well above the ~2 kB TOAST threshold. Every row would still be TOASTed and finding 1 would be just
as expensive. Do not do that migration for performance reasons; it would buy nothing.

One small, no-DDL improvement is available if you want it: `save_draft`'s pre-read could select
only `is_test,archived,assigned_estimator` instead of the whole blob, saving a 38 kB download on
every autosave. It saves wire time, not database time (0.613 ms either way), on 21 calls a day.
Genuinely marginal — listed for completeness, not recommended.

---

## 3. The portal's connection pool hands out dead connections — Medium

This was already known and unfixed. I confirmed it in the code and can name the line.

`treadwell-portal/backend/db.py:25`:

```python
_pool = ConnectionPool(config.DATABASE_URL, min_size=1, max_size=8, kwargs={"row_factory": dict_row})
```

There is no `check=`. `psycopg_pool` defaults to checking nothing, so when the server closes a
connection underneath the pool — Supabase maintenance, a pooler reset, a database restart — the
pool hands that dead connection to the next request and the request 500s. It keeps doing so until
the connection is finally discarded.

**Fix:** add one keyword.

```python
_pool = ConnectionPool(config.DATABASE_URL, min_size=1, max_size=8,
                       check=ConnectionPool.check_connection,
                       kwargs={"row_factory": dict_row})
```

It costs a `SELECT 1` on checkout, which on this workload is noise. Risk is low. It lives in the
**portal** repo, which ships by hand (`deploy/ship.sh` / `ship-prod.sh`) and has no CD, so merging
alone changes nothing on the box.

`max_size=8` against `max_connections=60` is fine — 16 connections were in use during this audit.

---

## 4. Indexes — the hot paths are already indexed correctly

This is a genuine "no action" finding, and worth stating plainly, because the intuitive fix for
finding 1 is "add an index" and that would be wasted work.

**The index the Projects list needs already exists** and is correct:

```sql
CREATE INDEX drafts_active_idx ON drafts USING btree (updated_at DESC) WHERE (deleted_at IS NULL)
```

Postgres deliberately ignores it — 67 index scans against 21,913 sequential scans — and it is
right to. The plan shows `Seq Scan` plus a quicksort because the heap is six pages; reading it
whole beats walking an index. It will start being chosen somewhere in the low thousands of rows.
Adding another index changes nothing, because the cost is detoast, not row access.

Other hot-path indexes, all doing their job:

| Index | Scans | Serves |
|---|---|---|
| `events_created_idx` | 31,405 | the History feed |
| `drafts_pkey` | 113,891 | opening and saving one project |
| `draft_revisions_project_idx (project_id, revision_no DESC)` | 7,769 | `_sent_revisions` |
| `portal_questions_proposal_idx` | 513,878 | the chat thread |
| `portal_followups_rule_uidx` (partial unique) | 32,470 | follow-up dedupe |

**No GIN index on `drafts.data` is needed**, and I checked rather than guessed: every filter in
every normalized query text is on `id` or `deleted_at`. Nothing filters on a JSON key. A GIN index
would be write amplification with no reader.

**Eight non-unique indexes have had zero scans in 117 days**: `leads_status_idx`,
`leads_draft_idx`, `leads_updated_idx`, `portal_sessions_email_idx`, `portal_proposals_live_idx`,
`calendar_events_estimator_idx`, `calendar_events_project_idx`, `portal_feedback_created_idx`.
They are 8-16 kB each. I would **leave them**: they cost almost nothing, and `leads` and
`calendar_events` are young tables whose query patterns have not arrived yet. Dropping them is
churn with a migration attached.

---

## 5. The unread-message count is the only quadratic query — Low, revisit later

`treadwell-portal/backend/db.py:410` counts unread customer messages with a correlated subquery:

```sql
select q.proposal_id as pid, count(*) as n
from public.portal_questions q
where q.author_kind='customer' and q.msg_type='text'
  and q.id > coalesce((select max(s.id) from public.portal_questions s
                       where s.proposal_id=q.proposal_id
                         and s.author_kind='staff' and s.msg_type='text'), 0)
group by q.proposal_id
```

The subquery runs once per candidate row. That is where `portal_questions`' **302,056 sequential
scans and 20.7 M tuples read** come from — by far the largest such figure in the schema, from a
table with 257 rows.

A one-pass window function does the same job:

```sql
select proposal_id as pid, count(*) as n from (
  select proposal_id, id, author_kind,
         max(id) filter (where author_kind='staff') over (partition by proposal_id) as last_staff
  from public.portal_questions where msg_type='text') t
where author_kind='customer' and id > coalesce(last_staff, 0)
group by proposal_id
```

Measured warm, and checked for equivalence:

| | Exec time | Buffers | Rows |
|---|---|---|---|
| Correlated subquery (live) | 0.465 ms | 188 | 7 |
| Window function | **0.325 ms** | **14** | 7 |

`EXCEPT` in both directions: 0 differences.

**My recommendation is to leave it alone for now.** It saves 0.14 ms on a query called about 174
times a day. The number that matters is the 13x buffer ratio, because both factors grow — messages
per proposal *and* proposals. Worth revisiting when `portal_questions` passes roughly 10,000 rows;
today it is 257.

---

## 6. Things that are already right

Worth recording so nobody spends a day re-deciding them.

- **`_sent_revisions` is a textbook avoided N+1.** One `in.(...)` query fetches the revision
  numbers for the whole page instead of one per card, and it degrades gracefully when
  `draft_revisions` is missing.
- **The 60-second list cache is doing real work.** Browsers poll on several pages (board 25 s,
  follow-ups 45 s, projects/leads/polish 60 s, calendar 120 s, notification bell 60 s), and only
  about 93 list reads a day actually reach the database. Without it, finding 1 would already be a
  problem.
- **No N+1 in the enrichment paths.** `/api/portal/pipeline` and the Follow-ups page each call
  `list_drafts()` **once** and index the result into a dict. They do pay the full 20-field
  projection to read one scalar (`is_test`), which is a reason to like finding 1's fix, but the
  loop itself is correct.
- **The Supabase client is reused.** `get_client()` is `lru_cache(maxsize=1)`, so supabase-py's
  httpx connection pool is shared rather than rebuilt per request.
- **`reserve_followup` firing 32,470 inserts to land 108 rows is correct by design**, not a bug.
  The partial unique index *is* the dedupe, and `on conflict do nothing` is the cheapest way to
  ask. 0.402 ms each, about 0.11 s of database time per day. Leave it.
- **Autovacuum is keeping up.** `drafts` has been autovacuumed 45 times, most recently
  2026-09-15, and carries 4 dead tuples against 51 live. No bloat problem anywhere.
- **Nothing has grown unexpectedly.** The largest table is 1.6 MB. `events` grows ~40 rows/day and
  its `created_at DESC` index serves the feed, so no retention policy is needed yet.

---

## Appendix: reproducing any of this

Everything above came from read-only SQL. To re-measure the headline finding:

```sql
-- what the list costs today
explain (analyze, buffers, serialize text)
select id, owner_email, created_at, updated_at, deleted_at,
       data->>'project_name', data->>'work_type', data->>'deadline', data->>'archived',
       data->>'is_test', data->'polish_estimate'->>'version', data->>'assigned_estimator',
       data->>'contact_email', data->'generate_result'->>'work_type',
       data->>'proposal_lump_sum', data->'computed_bid',
       data->'closed_lost'->>'reason', data->'closed_lost'->>'at', data->'closed_lost'->>'note',
       data->'on_hold'->>'reason', data->'on_hold'->>'until', data->'on_hold'->>'note',
       data->'won'->>'at', data->'handed_off'->>'at'
from drafts where deleted_at is null order by updated_at desc limit 300;

-- where database time goes
select round(sum(total_exec_time)::numeric/1000,1) seconds, sum(calls) calls
from pg_stat_statements
where query like '%pgrst_source%"drafts"%' and query like '%project_name%'
  and query not like '%UPDATE%';

-- what is being sequentially scanned
select relname, seq_scan, seq_tup_read, idx_scan, n_live_tup
from pg_stat_user_tables where schemaname='public' order by seq_tup_read desc;
```

`SERIALIZE` needs PostgreSQL 17, and it matters here: without it `EXPLAIN ANALYZE` never converts
the output rows, so reading the whole blob looks 90x faster than it really is. The first table in
finding 1 would be misleading without it.
