-- PLAN VS ACTUAL SNAPSHOTS (#784): one row per listed Project per Central day.
--
-- After every good refresh (the 5:00 AM Central daily run, backend/pva_refresh_worker.py, or
-- "Refresh now") backend/pva_snapshots.py upserts each listed Project's figures here; a second good
-- run the same day REPLACES that day's row (the primary key). Kept so trends can be shown later.
--
-- The code reads an absent table as "keep no snapshots" (one log line, the page unchanged), so this
-- file can be applied after the code is live. Safe to re-run. Prod (Supabase SQL editor) and
-- staging (psql -d treadwell) are separate databases: run it on BOTH, staging before the code
-- merges to staging, prod (with Hanz's go) before it ships to prod.

create table if not exists public.pva_snapshots (
  -- The row's own key: "job:<Job number>", "name:<name>" or "punch:...", as the page uses it.
  project_key text not null,
  -- The day in Central the run belongs to.
  snap_date   date not null,
  -- The row's computed figures: the plan, and the Raken side with its statuses.
  figures     jsonb not null,
  -- When Raken was read (Central, with its offset).
  ran_at      timestamptz,
  primary key (project_key, snap_date)
);

-- Same posture as drafts/events/condition_defaults: RLS on, no policies; the proposal tool holds
-- the service-role key. The grant goes beside the table: a blanket grant only covers the tables
-- that existed when it ran, so a table added later reads fine and every write fails.
alter table public.pva_snapshots enable row level security;
grant select, insert, update, delete on public.pva_snapshots to service_role;

-- PostgREST caches the schema; without this the first upsert errors until the cache refreshes.
-- (Staging needs it; harmless on Supabase.)
notify pgrst, 'reload schema';
