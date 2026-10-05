-- THE DEFAULTS-TAB SLIDER, 2026-10-05 (Kyle's notes, Hanz's call: the slider is the STARTING state
-- of a default in a NEW bid; OFF shows the row grayed on the estimate, priced at $0).
--
-- One nullable boolean on each table a default can come from. NULL reads ON -- every default that
-- exists today keeps starting on, so nothing changes until somebody flips a slider. The code reads
-- an absent column the same way, so this file can be applied after the code is live.
--
-- Safe to re-run (ADD COLUMN IF NOT EXISTS). No backfill, no data change.
-- Prod (Supabase SQL editor) and staging (psql -d treadwell) are separate databases: run it on BOTH.

alter table public.library_items       add column if not exists default_on boolean;
alter table public.library_assemblies  add column if not exists default_on boolean;
alter table public.library_labor       add column if not exists default_on boolean;

-- PostgREST caches the schema; without this a write that carries the new column errors until the
-- cache refreshes. (Staging needs it; harmless on Supabase.)
notify pgrst, 'reload schema';
