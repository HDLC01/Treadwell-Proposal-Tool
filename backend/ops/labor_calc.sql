-- THE LABOR CALCULATOR'S PER-LINE MODES, 2026-10-06 (Kyle's notes B7b; Hanz 2026-10-05).
--
-- One row per default labor line, keyed by the line's id: the built-in crew rows (`polishing`,
-- `mockup`, `jointfill`) or a library_labor row's uuid. No row = the line behaves as it always has.
-- `mode` is 'sf' (crew + sf_per_day; days = ceil(job SF / sf_per_day)) or 'fixed' (guys + days).
-- `rate` NULL = the company labor rate (Markups -> Global).
--
-- The code reads an absent table as "no line has a mode", so this file can be applied after the
-- code is live. Safe to re-run. Prod (Supabase SQL editor) and staging (psql -d treadwell) are
-- separate databases: run it on BOTH.

create table if not exists public.library_labor_calc (
  line_id        text primary key,
  mode           text not null check (mode in ('sf', 'fixed')),
  crew           numeric(8,2),
  sf_per_day     numeric(12,2),
  hours_per_day  integer not null default 8 check (hours_per_day in (8, 10)),
  guys           numeric(8,2),
  days           numeric(8,2),
  rate           numeric(10,2),
  updated_at     timestamptz not null default now()
);

alter table public.library_labor_calc enable row level security;
grant select, insert, update, delete on public.library_labor_calc to service_role;

-- PostgREST caches the schema; without this the first write errors until the cache refreshes.
notify pgrst, 'reload schema';
