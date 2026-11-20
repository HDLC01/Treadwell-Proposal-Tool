-- Treadwell staging DATA store — plain Postgres + PostgREST (VPS only).
-- Mirrors supabase_schema.sql MINUS the Supabase-auth coupling: no FK to
-- auth.users and no signup trigger (profiles are upserted by /api/me on login).
-- Runs once via /docker-entrypoint-initdb.d on first `docker compose up`.

create extension if not exists pgcrypto;

-- ── PostgREST roles ────────────────────────────────────────────────────
-- 'authenticator' is the login role PostgREST connects as; it switches to
-- 'service_role' (the configured anon role) per request. service_role bypasses
-- RLS and has full table access — fine here, the db is bound to the internal
-- docker network only (no published port).
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'service_role') then
    create role service_role nologin bypassrls;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticator') then
    create role authenticator noinherit login password 'staging_auth_pw';
  end if;
end $$;
grant service_role to authenticator;

-- ── Tables (same shape as prod) ─────────────────────────────────────────
create table if not exists public.drafts (
  id           text primary key,
  data         jsonb not null default '{}'::jsonb,
  owner_email  text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  deleted_at   timestamptz                        -- NULL = active; set = in Trash
);
alter table public.drafts add column if not exists deleted_at timestamptz;
create index if not exists drafts_updated_idx on public.drafts (updated_at desc);
create index if not exists drafts_active_idx  on public.drafts (updated_at desc) where deleted_at is null;
create index if not exists drafts_trashed_idx on public.drafts (deleted_at desc) where deleted_at is not null;

create table if not exists public.events (
  id           bigint generated always as identity primary key,
  project_id   text,
  actor_email  text,
  action       text not null,
  detail       jsonb not null default '{}'::jsonb,
  created_at   timestamptz not null default now()
);
create index if not exists events_created_idx on public.events (created_at desc);

create table if not exists public.profiles (
  id           uuid primary key,                 -- Supabase auth user id (no FK here)
  email        text,
  full_name    text,
  role         text not null default 'user'   check (role   in ('user','admin','super_admin')),
  status       text not null default 'active' check (status in ('active','paused','banned')),
  banned_at    timestamptz,
  banned_until timestamptz,
  ban_reason   text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create index if not exists profiles_role_idx  on public.profiles (role);
create index if not exists profiles_email_idx on public.profiles (email);

create or replace function public.set_updated_at() returns trigger as $$
begin new.updated_at = now(); return new; end; $$ language plpgsql;
drop trigger if exists drafts_updated_at on public.drafts;
create trigger drafts_updated_at before update on public.drafts
  for each row execute function public.set_updated_at();
drop trigger if exists profiles_updated_at on public.profiles;
create trigger profiles_updated_at before update on public.profiles
  for each row execute function public.set_updated_at();

-- ⚠ AFTER APPLYING ANY DDL TO A RUNNING STAGING STACK, RELOAD POSTGREST'S SCHEMA CACHE:
--     docker exec treadwell-staging-db psql -U postgres -d treadwell --       -c "notify pgrst, 'reload schema';"
--
-- This file only runs on a FRESH database (docker-entrypoint-initdb.d), so a new table
-- added to an existing staging stack has to be applied by hand — and PostgREST caches the
-- schema at start-up. The failure is genuinely confusing: reads of the new table return
-- 200 while writes return 404 with an empty body, which reads like a routing or
-- permissions problem rather than a stale cache. Cost a round of debugging on
-- 2026-08-03 with calendar_events. Cloud Supabase reloads automatically on migration, so
-- this is a staging-only trap.

-- ── Bid Calendar: Treadwell's own entries ───────────────────────────────
-- Mirror of the prod table in supabase_schema.sql. Staging keeps DATA in this
-- self-hosted Postgres (cloud Supabase is AUTH only), so the DDL has to be applied
-- here too — it is a genuinely separate database, not a copy.
create table if not exists public.calendar_events (
  id               text primary key,
  title            text not null,
  deadline_at      timestamptz,          -- UTC instant; rendered Central by the frontend
  kind             text not null default 'bid',
  customer         text,
  location         text,
  value            numeric(14,2),        -- dollars, never cents
  estimator_email  text,
  stage            text,
  notes            text,
  project_id       text,                 -- optional link to drafts.id; deliberately not an FK
  owner_email      text,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  deleted_at       timestamptz           -- soft delete: a lost bid deadline costs a job
);
create index if not exists calendar_events_live_deadline_idx
  on public.calendar_events (deadline_at) where deleted_at is null;
create index if not exists calendar_events_estimator_idx
  on public.calendar_events (estimator_email) where deleted_at is null;
create index if not exists calendar_events_project_idx
  on public.calendar_events (project_id)
  where deleted_at is null and project_id is not null;

-- ── Item Library ────────────────────────────────────────────────────────
-- Materials, and the assemblies built out of them. Standalone: nothing in the
-- estimate/proposal path reads these. Mirrors supabase_schema.sql; see
-- backend/library.py for the reasoning behind the JSONB lines and the missing FK.
create table if not exists public.library_items (
  id           text primary key,
  name         text not null,
  unit         text not null default 'Gal',   -- Gal / Kit / Pint / Each / … freeform
  unit_cost    numeric(12,4),                 -- four places: $85.3827 back-solves from the sheet
  coverage     numeric(12,3),                 -- SF one unit covers; a line may override it
  category     text,
  sku          text,
  vendor       text,
  notes        text,
  owner_email  text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  deleted_at   timestamptz                    -- soft delete: a hand-typed price list
);
create index if not exists library_items_live_name_idx
  on public.library_items (name) where deleted_at is null;
create index if not exists library_items_category_idx
  on public.library_items (category) where deleted_at is null;
-- Item categories per work type (2026-10-28): {work type: Admin category id}. backend/ops/item_categories.sql.
alter table public.library_items add column if not exists material_categories jsonb;
-- The Items tab's Cost Comment (2026-11-04): a free-text note on the price. backend/ops/library_cost_comment.sql.
alter table public.library_items add column if not exists cost_comment text;

create table if not exists public.library_assemblies (
  id           text primary key,
  name         text not null,
  unit         text not null default 'SF',
  -- [{role, item_id, coverage, note}]. item_id is deliberately NOT an FK: a material must stay
  -- deletable while an assembly still references it, and the pricing layer reports that line
  -- as broken rather than the database forbidding the delete or cascading a silent rewrite.
  lines        jsonb not null default '[]'::jsonb,
  category     text,
  description  text,
  owner_email  text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  deleted_at   timestamptz
);
create index if not exists library_assemblies_live_name_idx
  on public.library_assemblies (name) where deleted_at is null;

-- Granted explicitly, NOT left to the blanket grant below.
--
-- Measured on staging 2026-08-05: creating these two tables and re-running the blanket
-- `grant all on all tables` left service_role with ZERO privileges on them — that statement
-- only covers tables that exist when it runs, and the `alter default privileges` line did not
-- cover them either. PostgREST connects as service_role, so the tables read fine and every
-- write failed. A per-table grant beside the table it belongs to cannot be missed when the
-- next table is added.
-- Vendors, so the Items tab offers a dropdown rather than a free-text box that grows three
-- spellings of one supplier. The item keeps `vendor` as TEXT (not an FK) — see supabase_schema.sql
-- for why. Managing this list is admin-only; picking from it is not.
create table if not exists public.library_vendors (
  id           text primary key,
  name         text not null,
  notes        text,
  owner_email  text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  deleted_at   timestamptz
);
create index if not exists library_vendors_live_name_idx
  on public.library_vendors (name) where deleted_at is null;

create table if not exists public.library_divisions (
  id           text primary key,
  name         text not null,
  notes        text,
  owner_email  text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  deleted_at   timestamptz
);
create index if not exists library_divisions_live_name_idx
  on public.library_divisions (name) where deleted_at is null;

create table if not exists public.library_units (
  id           text primary key,
  name         text not null,
  notes        text,
  owner_email  text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  deleted_at   timestamptz
);
create index if not exists library_units_live_name_idx
  on public.library_units (name) where deleted_at is null;

-- Custom labor defaults, 2026-09-17. The "+ Add a labor line" button on the Defaults tab had
-- no handler because there was nowhere to put one: renderDefaultLabor drew a single built-in
-- row out of travelSeed() and nothing stored anything else.
--
-- TRAVEL IS IN HERE, AS ONE RESERVED ROW, since 2026-09-19. Hanz, on the BUILT IN chip the
-- Defaults tab drew beside it: "again this too how can we edit this?" -- and twice before that,
-- "don't put in a hard coded or built in line items". Its rate was a literal in travelSeed() and
-- there was no row to address, so nothing on the page could change it.
--
-- NOBODY CAN DELETE IT, which is what the earlier note here was protecting and what is still
-- true. `travel` is the id migrateModel finds Travel by, and freshModel() seeds a Travel row into
-- every new bid whether or not this table answers -- so a row here OVERRIDES the shipped rate, it
-- does not supply it. list_labor() answering nothing (a soft-deleted row, or a database where
-- this table does not exist at all) puts Travel back on the $33.00/hr in travelSeed() rather than
-- taking it off anybody's estimate. That is why the Defaults tab labels the control Reset and not
-- Remove: Remove is not a thing this row can do.
--
-- SEEDED HERE RATHER THAN CREATED THROUGH THE API on purpose. POST /api/library/labor mints a
-- uuid and `LibraryLaborIn` has no id field, deliberately -- letting a caller name a row is how
-- a second row would come to hold the reserved id. Naming a row is the schema's job, once.
--
-- Soft delete like every other library table, so removing a default cannot take it out of the
-- bids already holding it. rate is numeric(10,2) and NOT NULL: a labor line without a rate is
-- a line that prices at nothing, which is worse than one that refuses to be saved.
create table if not exists public.library_labor (
  id           text primary key,
  name         text not null,
  rate         numeric(10,2) not null default 0,
  unit         text not null default 'hours',
  guys_auto    boolean not null default false,
  sort         integer not null default 0,
  notes        text,
  owner_email  text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  deleted_at   timestamptz
);
create index if not exists library_labor_live_name_idx
  on public.library_labor (name) where deleted_at is null;

-- The one row this table ships with. `on conflict (id) do nothing` so re-running the file leaves
-- an edited rate alone -- the whole point of the row is that somebody can change it. sort = -1
-- puts it first in list_labor()'s order, which is where the Defaults tab has always drawn it.
insert into public.library_labor (id, name, rate, unit, guys_auto, sort)
values ('travel', 'Travel', 33.00, 'hours', true, -1)
on conflict (id) do nothing;

-- WHICH WORK TYPES A DEFAULT BELONGS TO, 2026-09-17. `favorite` says a row IS a default;
-- this says which of the five sheet tabs it opens on.
--
-- EMPTY MEANS EVERY ONE, and that is what makes this additive rather than a migration: every
-- row written before the column existed comes back [] and still applies everywhere, exactly as
-- it did when favorite was the whole story. Nobody wakes up to defaults that stopped appearing.
--
-- The vocabulary is markup.TABS (polish, seal, epoxy, leveling, gyp), imported in library.py
-- rather than retyped. `combo` is NOT one of them: a combo job runs on the epoxy AND polish
-- tabs, so it inherits both lists instead of keeping a third that has to agree with two others.
alter table public.library_items      add column if not exists default_work_types jsonb not null default '[]'::jsonb;
alter table public.library_assemblies add column if not exists default_work_types jsonb not null default '[]'::jsonb;
alter table public.library_labor      add column if not exists default_work_types jsonb not null default '[]'::jsonb;

-- THE LABOR TAB'S OWN FAVORITE, 2026-09-24 -- mirrors supabase_schema.sql exactly (see the note
-- there for the two-step reasoning). Two databases, DDL twice, or one drifts.
alter table public.library_labor add column if not exists favorite boolean not null default true;
alter table public.library_labor alter column favorite set default false;

-- THE DEFAULTS-TAB SLIDER, 2026-10-05 -- one nullable boolean (NULL reads ON); same file as
-- backend/ops/default_on.sql, which is how an already-running database gets it.
alter table public.library_items      add column if not exists default_on boolean;
alter table public.library_assemblies add column if not exists default_on boolean;
alter table public.library_labor      add column if not exists default_on boolean;

-- PHASE 11 (2026-10-12): price breaks, a bulk cost and a coverage basis on a material -- same columns
-- as backend/ops/library_price_breaks.sql, which is how an already-running database gets them. All
-- nullable, no default: a row with none of them prices exactly as before.
alter table public.library_items add column if not exists price_breaks    jsonb;
alter table public.library_items add column if not exists bulk_cost       numeric(12,4);
alter table public.library_items add column if not exists coverage_basis  text
  check (coverage_basis in ('sf', 'lf', 'each'));

-- THE LABOR CALCULATOR'S PER-LINE MODES, 2026-10-06 -- same table as backend/ops/labor_calc.sql,
-- which is how an already-running database gets it. One row per default labor line (a built-in
-- crew id or a library_labor uuid); `mode` is 'sf' (crew + sf_per_day) or 'fixed' (guys + days);
-- `rate` NULL = the company labor rate. The code reads an absent table as "no modes".
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
grant select, insert, update, delete on public.library_labor_calc to service_role;

-- Items and Assemblies, 2026-08-15. Additive, and safe against a volume already holding BETA
-- rows. buy_qty is the "5" of "5 Gal" (so unit_cost can mean what the pail costs); existing rows
-- get 1, which prices exactly as they did before the column existed. cost_updated_at marks a
-- price revision, unlike updated_at which moves on every patch.
alter table public.library_items add column if not exists buy_qty numeric(10,3) not null default 1;
alter table public.library_items add column if not exists divisions jsonb not null default '[]'::jsonb;

-- COVERAGE, WASTE AND ROUNDUP LIVE ON THE MATERIAL (Hanz, 2026-09-21; applied to BOTH databases that
-- day, recorded here 2026-09-30). NULL waste_pct reads as 5 and NULL roundup as true, which were the
-- assembly line's old defaults. Assemblies stopped holding their own copy; see
-- backend/ops/backfill_material_coverage.sql, run before this code reaches a database.
alter table public.library_items add column if not exists waste_pct numeric(5,2);
alter table public.library_items add column if not exists roundup   boolean;
alter table public.library_items add column if not exists cost_updated_at timestamptz;

insert into public.library_divisions (id, name)
values
  ('default-polished-concrete', 'Polished Concrete'),
  ('default-epoxy', 'Epoxy'),
  ('default-gypsum-underlayment', 'Gypsum Underlayment')
on conflict (id) do nothing;

insert into public.library_units (id, name)
values
  ('default-gallon', 'Gallon'),
  ('default-kit', 'Kit'),
  ('default-bag', 'Bag')
on conflict (id) do nothing;

-- Who edited it, 2026-09-04 (Hanz: "in the items tab we must put the name of who created it and
-- who edited it"). Mirrors supabase_schema.sql; owner_email already answered who created it.
-- NULLABLE and never backfilled — a row predating this column was changed by somebody nobody
-- recorded, and the tab shows that as "—" rather than naming the creator. Server-set from the
-- authenticated request, never from the body. Not cost_updated_at, which is a PRICE revision;
-- this moves on any edit, an assembly LINE change included.
alter table public.library_items add column if not exists updated_by text;
alter table public.library_assemblies add column if not exists updated_by text;

-- Dye and the Joint Filler kit, 2026-09-30. Mirrors supabase_schema.sql; see the note there. Two
-- RESERVED rows at literal ids, `on conflict (id) do nothing` so an edited price survives a
-- re-run; delete_item refuses both ids. Kyle's C29/C25 figures (dye is ONE coat; the bid buys
-- two, rows 25 and 26), which price to the cent what the engine's fallback does. Waste is a literal 0 -- a null would read as 5% and raise both prices.
-- waste_pct and roundup are added above, with the other material columns. The third row,
-- remove-existing-jf (2026-10-01), buys nothing: NULL cost and coverage, nothing prices off it.
insert into public.library_items (id, name, unit, buy_qty, unit_cost, coverage, waste_pct, roundup)
values
  ('joint-filler-kit', 'Joint filler, 10 gal kit', 'Kit', 1, 500.00, 3500, 0, true),
  ('dye', 'Dye, per coat', 'SF', 1, 0.14, 1, 0, false),
  ('remove-existing-jf', 'Remove existing joint filler', 'SF', 1, null, null, 0, false)
on conflict (id) do nothing;

-- ── Markup rules ────────────────────────────────────────────────────────
-- The markup chain's rates as editable expressions, one row per line per sheet LAYOUT. Mirrors
-- supabase_schema.sql; see backend/markup.py for why the key is the TAB (Seal / Epoxy blank /
-- Leveling are tabs no work type names), why there is no 'combo', and why `applies` is not the
-- same as a zero formula (the Gyp tabs have NO hard-bid rate — the cell is empty).
--
-- 'global' IS A LAYOUT AND IS NOT A TAB. The four lines that are the same rule on every sheet —
-- hard_bid, bond, travel_lodging ($70 a night), travel_per_diem ($45 a day) — are filed once under
-- it and read BY every tab. ONE HOME PER LINE, not a default a tab may override: two rows for one
-- line is a precedence question, and that question decides a price. Enforced in markup.py, not by
-- a CHECK here, for the reason the layout comment already gives.
create table if not exists public.markup_rules (
  id           text primary key,
  layout       text not null,                 -- polish | seal | epoxy | leveling | gyp | global
  line_key     text not null,                 -- gp | hard_bid | … | travel_lodging (global-only)
  -- An EXPRESSION, not a rate: Gyp's soft-costs cell is a whole IF(OR(...)) that returns the
  -- string "error" rather than guess. NULL when the line does not apply.
  formula      text,
  applies      boolean not null default true, -- false = this tab has no such line at all
  notes        text,
  sort         integer not null default 0,    -- the chain order; it compounds
  owner_email  text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz,
  deleted_at   timestamptz                    -- soft delete: hand-typed rules that move a bid
);
-- One LIVE rule per (layout, line_key). Partial, so a soft-deleted row does not reserve the key.
create unique index if not exists markup_rules_live_key_idx
  on public.markup_rules (layout, line_key) where deleted_at is null;
create index if not exists markup_rules_live_layout_idx
  on public.markup_rules (layout, sort) where deleted_at is null;
-- Beside the table, per the measured lesson above: the blanket grant only covers tables that
-- exist when it runs, so a table added later reads fine and every write fails.
grant select, insert, update, delete on public.markup_rules to service_role;

-- ── The exact files each sent revision's customer was given ─────────────────
-- Mirrors supabase_schema.sql (section 6b), which explains the table and why the files are base64
-- text rather than bytea. Needs the notify-pgrst reload above when applied to a running stack, and
-- the rest proxy's client_max_body_size (rest-proxy.conf): one row carries a .docx and a PDF, and
-- nginx's 1 MB default is close to that.
create table if not exists public.draft_revision_documents (
  project_id     text not null references public.drafts(id) on delete cascade,
  revision_no    int  not null,
  payload_sha256 text not null,
  docx_b64       text not null,
  docx_sha256    text not null,
  pdf_b64        text not null,
  pdf_sha256     text not null,
  created_by     text,
  created_at     timestamptz not null default now(),
  primary key (project_id, revision_no)
);
grant select, insert, update, delete on public.draft_revision_documents to service_role;

grant select, insert, update, delete on public.library_items to service_role;
grant select, insert, update, delete on public.library_assemblies to service_role;
grant select, insert, update, delete on public.library_vendors to service_role;
grant select, insert, update, delete on public.library_divisions to service_role;
grant select, insert, update, delete on public.library_units to service_role;

-- ── Grants so PostgREST (service_role) can read/write ───────────────────
grant usage on schema public to service_role;
grant all on all tables in schema public to service_role;
grant all on all sequences in schema public to service_role;
alter default privileges in schema public grant all on tables to service_role;
alter default privileges in schema public grant all on sequences to service_role;

-- ── Takeoff condition defaults ──────────────────────────────────────────
-- What a NEW Polish estimate opens ANSWERED for the three Yes/No questions the Takeoff step
-- carries. Mirrors supabase_schema.sql; see backend/condition_defaults.py for why the key
-- vocabulary is closed and checked in Python rather than by a CHECK constraint, and why the
-- workbook CELL each answer writes is not editable.
--
-- NOT APPLIED on either database as of 2026-09-18 — it needs Hanz's go, and it has to land on
-- BOTH or the one that misses it answers 502 on the first save. Until then list_defaults()
-- answers empty by design and every estimate opens with the literals in bid-model.js.
--
-- A row is an OVERRIDE of a shipped constant, and it reaches a BRAND-NEW bid only: a saved
-- estimate keeps the answers it was saved with whatever this table later says.
create table if not exists public.condition_defaults (
  id            text primary key,
  condition_key text not null,                   -- joint_filler | remove_existing_jf | dye
  on_by_default boolean not null default false,  -- the whole of what is editable
  owner_email   text,
  updated_by    text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz
);
-- One row per condition. PLAIN, not partial: there is deliberately no deleted_at here, because a
-- row is one boolean in front of a constant that is still in the source — the undo is the switch.
create unique index if not exists condition_defaults_key_idx
  on public.condition_defaults (condition_key);
-- LISTED, 2026-10-01 (Hanz: "Everything that is in the defaults and labor tab in the Items and
-- Assemblies appear as grayed out options that can be enabled or not"). Whether a NEW Polish
-- estimate shows this condition's card at all, apart from whether it starts switched on
-- (on_by_default). NULL reads as listed, so a row written before this column existed, and every
-- key with no row, keeps showing its card exactly as before. Additive, no default, no backfill.
alter table public.condition_defaults add column if not exists listed boolean;
-- Beside the table, per the measured lesson this file already records: the blanket grant above
-- only covers tables that existed when it ran, so a table added later reads fine and every write
-- fails.
grant select, insert, update, delete on public.condition_defaults to service_role;

-- PLAN VS ACTUAL SNAPSHOTS (#784). Mirrors supabase_schema.sql; see backend/pva_snapshots.py. One
-- row per listed Project per Central day; a second good run the same day replaces the row.
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
-- Beside the table, per the measured lesson this file already records: the blanket grant above
-- only covers tables that existed when it ran, so a table added later reads fine and every write
-- fails.
grant select, insert, update, delete on public.pva_snapshots to service_role;

-- >>> BD CRM: schema bd. GENERATED by backend/bd/ops/staging_schema.py; do not edit by hand. >>>
-- The BD CRM's private schema (#802, #805), made from backend/bd/migrations/:
-- tests/test_bd_staging_schema.py fails when this part and those files differ. Regenerate it
-- from backend/ with `python -m bd.ops.staging_schema` after changing a migration or grants.sql.
-- On every deploy: bd_app is made if missing; under the runner's advisory lock, schema bd and
-- its ledger are made if missing, each numbered file is applied ONLY IF the ledger lacks it
-- (with its ledger row and grants.sql, in one transaction), and grants.sql is re-applied.
-- Prod never reads this file: there the runner (python -m bd.migrate) is run by hand on
-- Hanz's go.
-- Schema bd is not in PostgREST's schemas, and service_role has no rights in it.

-- bd_app, the BD CRM's own login. Its password here is STAGING-ONLY: never reused anywhere
-- else (prod's bd_app is made by hand and its password lives only in the prod env file).
do $bd_role$
begin
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'bd_app') then
    begin
      create role bd_app login password 'staging_only_bd_app_pw';
      -- Set with the role, so no later run ever has to write this cluster-wide setting.
      alter role bd_app set search_path = bd, pg_catalog;
    exception when duplicate_object or unique_violation then
      null;  -- made a moment ago by another session
    end;
  end if;
end
$bd_role$;

-- The runner's lock (backend/bd/migrate.py LOCK_KEY), held to the end of this part.
do $bd_lock$ begin perform pg_advisory_lock(198967297); end $bd_lock$;
create schema if not exists bd;
create table if not exists bd.schema_migrations (
  name        text primary key,
  applied_at  timestamptz not null default now()
);

-- 001_schema.sql
do $bd_migration$
begin
  if not exists (select 1 from bd.schema_migrations where name = '001_schema.sql') then
    execute $bd_sql$
-- PLACED IN SCHEMA bd (#805). Ported from BD's backend/migrations at BD staging 14ff0d5.
-- Applied only by backend/bd/migrate.py or by the generated BD part of
-- backend/staging/schema_pg.sql, each inside ONE transaction, so the SET LOCAL below puts every
-- object this file creates in schema bd. Schema public is not on that path, so nothing here can
-- create in it or resolve a name to it by accident.
-- Changed in the move, and nothing else: every function pins its search_path to bd, pg_catalog,
-- and contacts_summary is created with security_invoker on (it reads as the caller, so row level
-- security on the tables it joins still applies).
set local search_path = bd, pg_catalog;

-- 001: the BD CRM's data model (docs/bd/api-contract.md).
--
-- Conventions
--   * ids are bigint identity columns ("by default", so the fictional seed can keep the mock's ids;
--     a seed must setval() the sequences afterwards, the fixture seed in backend/bd/ops does).
--   * every timestamp is timestamptz (stored UTC); every business DATE is a plain date that is
--     already a Central (America/Chicago) date.
--   * enums are text + CHECK constraints, so a bad value fails at the database too.
--   * "today" and "now" in SQL come from bd_today() / bd_now(), which read the session settings
--     BD's pool copies from backend/bd/bizdate.py on every checkout (and so honour the BD_TODAY test override).
--     Never use now()/current_date for a business date in this schema or in a router's SQL.
--   * DERIVED VALUES THE SERVER OWNS are generated columns, so no client and no router can set
--     them wrongly: contacts.phone_e164, contacts.email_lower, interactions.counts_as_touch.
--     Do not list them in an INSERT or UPDATE (Postgres refuses).

-- ── the business clock ────────────────────────────────────────────────────────────────────────
create or replace function bd_today() returns date
language sql stable
set search_path = bd, pg_catalog
as $$
  select coalesce(nullif(current_setting('bd.today', true), '')::date,
                  (now() at time zone 'America/Chicago')::date)
$$;

create or replace function bd_now() returns timestamptz
language sql stable
set search_path = bd, pg_catalog
as $$
  select coalesce(nullif(current_setting('bd.now', true), '')::timestamptz, now())
$$;

-- The Central calendar date of a moment.
create or replace function bd_date(ts timestamptz) returns date
language sql immutable parallel safe
set search_path = bd, pg_catalog
as $$
  select (ts at time zone 'America/Chicago')::date
$$;

-- "+1XXXXXXXXXX" or null: the same rule as backend/bd/phone.py to_e164 and BD's shared.js e164.
create or replace function bd_e164(phone text) returns text
language sql immutable parallel safe
set search_path = bd, pg_catalog
as $$
  select case
    when d ~ '^1[0-9]{10}$' then '+' || d
    when d ~ '^[0-9]{10}$' then '+1' || d
    else null end
  from (select regexp_replace(coalesce(phone, ''), '[^0-9]', '', 'g') as d) x
$$;

-- ── people who sign in ────────────────────────────────────────────────────────────────────────
create table users (
  id            bigint generated by default as identity primary key,
  email         text not null check (email = lower(btrim(email)) and email like '%@%'),
  name          text not null check (btrim(name) <> ''),
  role          text not null check (role in ('salesperson', 'assistant', 'manager', 'admin', 'super_admin')),
  active        boolean not null default true,
  auth_sub      text,                       -- the Supabase user id (`sub`), set on first sign-in
  last_seen_at  timestamptz,
  created_at    timestamptz not null default bd_now()
);
create unique index users_email_key on users (email);

-- ── companies ─────────────────────────────────────────────────────────────────────────────────
create table companies (
  id               bigint generated by default as identity primary key,
  name             text not null check (btrim(name) <> ''),
  -- normalize.normalize_company(name): set by every insert/rename (NOT NULL on purpose).
  normalized_name  text not null,
  city             text,
  industry         text,
  created_at       timestamptz not null default bd_now()
);
create index companies_normalized_name_idx on companies (normalized_name);

-- ── contacts: one row per person at a company ─────────────────────────────────────────────────
create table contacts (
  id                   bigint generated by default as identity primary key,
  company_id           bigint not null references companies (id),
  name                 text not null check (btrim(name) <> ''),
  title                text,
  email                text,
  email_lower          text generated always as (nullif(lower(btrim(email)), '')) stored,
  phone                text,                 -- as typed or imported ("816.555.0110")
  phone_e164           text generated always as (bd_e164(phone)) stored,
  city                 text,
  industry             text,
  lead_source          text not null default 'Other/Misc',
  stage                text,
  category             text not null default 'bd' check (category in ('bd', 'maintenance')),
  account_type         text,                 -- maintenance only (workbook "Account Type")
  owner_id             bigint references users (id),
  co_owner_id          bigint references users (id),
  -- A workbook co-owner with no login yet ("Troy/Greg" before Greg has a user): the contract's
  -- UserRef {"id": null, "name": "Greg"}. Ignored once co_owner_id is set.
  co_owner_name        text,
  -- Live touches needed a year. Left out on insert it becomes 4 (bd) / 3 (maintenance): see the
  -- trigger below. Routers should still apply settings.default_frequency.
  frequency_per_year   integer not null check (frequency_per_year between 1 and 52),
  confirmed            boolean not null default false,
  importance           integer not null default 1 check (importance between 1 and 3),
  next_step            text,
  next_step_date       date,
  promised_date        date,
  last_quote_date      date,
  -- The duplicate FLAG (never a block): the contact this one may duplicate, and why.
  duplicate_of         bigint references contacts (id) on delete set null,
  duplicate_reason     text check (duplicate_reason in ('Same company name', 'Same email', 'Same phone')),
  source               text not null default 'manual' check (source in ('workbook', 'manual', 'proposal_tool', 'import')),
  tags                 text[] not null default '{}',
  notes                text not null default '',
  archived_at          timestamptz,
  created_at           timestamptz not null default bd_now(),
  check (duplicate_of is null or duplicate_of <> id)
);
create index contacts_company_idx on contacts (company_id);
create index contacts_owner_idx on contacts (owner_id);
create index contacts_email_lower_idx on contacts (email_lower);
create index contacts_phone_e164_idx on contacts (phone_e164);
create index contacts_right10_idx on contacts (right(phone_e164, 10));

create or replace function contacts_default_frequency() returns trigger
language plpgsql
set search_path = bd, pg_catalog
as $$
begin
  if new.frequency_per_year is null then
    new.frequency_per_year := case when new.category = 'maintenance' then 3 else 4 end;
  end if;
  return new;
end
$$;
create trigger contacts_default_frequency
  before insert or update of frequency_per_year, category on contacts
  for each row execute function contacts_default_frequency();

-- ── interactions: every call, voicemail, meeting, email, text, note and hosted event ───────────
create table interactions (
  id               bigint generated by default as identity primary key,
  contact_id       bigint not null references contacts (id),
  kind             text not null check (kind in ('call', 'voicemail', 'meeting', 'email', 'sms', 'note', 'hosted')),
  direction        text check (direction in ('in', 'out')),
  outcome          text,
  -- THE ONE COUNTING RULE (api-contract.md): only a live call, a meeting or a hosted event.
  -- Generated, so neither a client nor a router can set it.
  counts_as_touch  boolean generated always as (
                     kind in ('meeting', 'hosted')
                     or (kind = 'call' and coalesce(outcome, '') in ('answered', 'meeting_set'))) stored,
  occurred_at      timestamptz not null,
  duration_s       integer check (duration_s is null or duration_s >= 0),
  summary          text,
  transcript       text,
  recording_url    text,
  provider         text not null default 'manual',
  external_id      text,
  user_id          bigint references users (id),
  -- The missed-call card: 'sent' (a follow-up went out) or 'none' ("Nothing"), once.
  followup_status  text check (followup_status in ('sent', 'none')),
  followup_at      timestamptz,
  created_at       timestamptz not null default bd_now(),
  unique (provider, external_id),
  -- coalesce: a NULL outcome must FAIL the call/voicemail arms (NULL in (...) is not false).
  check (
    (kind = 'call' and coalesce(outcome, '') in ('answered', 'no_answer', 'meeting_set'))
    or (kind = 'voicemail' and coalesce(outcome, '') = 'voicemail')
    or (kind not in ('call', 'voicemail') and outcome is null))
);
create index interactions_contact_idx on interactions (contact_id, occurred_at desc);
create index interactions_occurred_idx on interactions (occurred_at);

-- ── the weekly 10 ─────────────────────────────────────────────────────────────────────────────
create table task_batches (
  id            bigint generated by default as identity primary key,
  owner_id      bigint not null references users (id),
  week_start    date not null check (extract(isodow from week_start) = 1),
  kind          text not null check (kind in ('friday', 'ten_more')),
  generated_at  timestamptz not null default bd_now()
);
create index task_batches_owner_week_idx on task_batches (owner_id, week_start);

create table tasks (
  id                bigint generated by default as identity primary key,
  batch_id          bigint not null references task_batches (id) on delete cascade,
  contact_id        bigint not null references contacts (id),
  kind              text not null check (kind in ('new', 'followup')),
  reason            text not null default '',
  reasons           text[] not null default '{}',
  score             integer not null default 0,
  status            text not null default 'open' check (status in ('open', 'done', 'snoozed')),
  done_at           timestamptz,
  snoozed_until     date,
  snooze_reason     text,
  -- True while the task is snoozed BECAUSE its contact was archived (a restore reopens it).
  closed_by_archive boolean not null default false,
  created_at        timestamptz not null default bd_now(),
  unique (batch_id, contact_id)
);
create index tasks_contact_idx on tasks (contact_id);

-- ── AI (or fallback) next actions: suggested, then decided by a person ─────────────────────────
create table ai_recommendations (
  id              bigint generated by default as identity primary key,
  contact_id      bigint not null references contacts (id),
  interaction_id  bigint references interactions (id) on delete set null,
  action          text not null,
  due_date        date,
  reason          text not null default '',
  source          text not null check (source in ('ai', 'fallback')),
  status          text not null default 'pending' check (status in ('pending', 'confirmed', 'changed', 'dismissed')),
  created_at      timestamptz not null default bd_now(),
  decided_at      timestamptz,
  decided_by      bigint references users (id)
);
create index ai_recommendations_contact_idx on ai_recommendations (contact_id, status);

-- ── missed-call follow-up drafts ──────────────────────────────────────────────────────────────
create table followup_drafts (
  id                   bigint generated by default as identity primary key,
  contact_id           bigint not null references contacts (id),
  interaction_id       bigint references interactions (id) on delete set null,
  channel              text not null check (channel in ('email', 'sms')),
  to_address           text,                 -- the contract's `to` (a reserved word in SQL)
  subject              text,
  body                 text not null default '',
  source               text not null check (source in ('ai', 'fallback')),
  status               text not null default 'draft' check (status in ('draft', 'sent', 'discarded')),
  sent_interaction_id  bigint references interactions (id) on delete set null,
  created_at           timestamptz not null default bd_now(),
  sent_at              timestamptz,
  check (channel = 'email' or subject is null)
);
create index followup_drafts_interaction_idx on followup_drafts (interaction_id);

-- ── Potential BD Contacts (quotes from the proposal tool) ──────────────────────────────────────
create table candidates (
  id                      bigint generated by default as identity primary key,
  project_id              text not null,     -- the proposal tool's draft uuid
  project_name            text,
  company                 text,              -- as the tool sent it (" Northvane Plastics Inc.")
  contact_name            text,
  email                   text,
  phone                   text,
  quote_total             numeric(14, 2),
  quote_date              date,
  status                  text not null default 'new' check (status in ('new', 'added', 'ignored')),
  possible_duplicate_id   bigint references contacts (id) on delete set null,
  contact_id              bigint references contacts (id) on delete set null,   -- once added
  origin                  text not null default 'pull' check (origin in ('push', 'pull')),
  payload                 jsonb not null default '{}'::jsonb,
  added_by                bigint references users (id),
  created_at              timestamptz not null default bd_now(),
  decided_at              timestamptz
);
-- Idempotent on (project_id, email) (POST /api/admin/bd-candidates).
create unique index candidates_project_email_key on candidates (project_id, (lower(coalesce(email, ''))));

-- ── telephony ─────────────────────────────────────────────────────────────────────────────────
create table integration_events (
  provider        text not null,
  event_id        text not null,
  event_type      text,
  received_at     timestamptz not null default bd_now(),
  payload         jsonb not null default '{}'::jsonb,
  result          text check (result in ('interaction_created', 'interaction_updated', 'unmatched', 'duplicate', 'ignored')),
  interaction_id  bigint references interactions (id) on delete set null,
  primary key (provider, event_id)
);

create table unmatched_calls (
  id                       bigint generated by default as identity primary key,
  provider                 text not null,
  external_id              text,
  kind                     text not null default 'call' check (kind in ('call', 'sms')),
  direction                text check (direction in ('in', 'out')),
  from_e164                text,
  occurred_at              timestamptz not null,
  duration_s               integer,
  summary                  text,
  transcript               text,
  recording_url            text,
  status                   text not null default 'open' check (status in ('open', 'attached', 'dismissed')),
  attached_interaction_id  bigint references interactions (id) on delete set null,
  handled_by               bigint references users (id),
  handled_at               timestamptz,
  created_at               timestamptz not null default bd_now(),
  unique (provider, external_id)
);

-- ── settings: one row per top-level Settings key (appsettings.py merges over its defaults) ──────
create table settings (
  key         text primary key,
  value       jsonb not null,
  updated_at  timestamptz not null default bd_now(),
  updated_by  bigint references users (id)
);

-- ── the audit log and the contact timeline's events ───────────────────────────────────────────
create table events (
  id          bigint generated by default as identity primary key,
  kind        text not null,                 -- the timeline's event.action ("created", "merged", ...)
  actor_id    bigint references users (id),
  contact_id  bigint references contacts (id) on delete cascade,
  detail      text,                          -- the timeline's event.detail
  data        jsonb not null default '{}'::jsonb,
  at          timestamptz not null default bd_now()
);
create index events_contact_idx on events (contact_id, at desc);

-- ── the import log (GET /api/admin/imports) ───────────────────────────────────────────────────
create table imports (
  id                   bigint generated by default as identity primary key,
  file_name            text not null,
  dry_run              boolean not null,
  started_at           timestamptz not null default bd_now(),
  finished_at          timestamptz,
  by_id                bigint references users (id),
  rows_read            integer not null default 0,
  created              integer not null default 0,
  updated              integer not null default 0,
  skipped              integer not null default 0,
  possible_duplicates  integer not null default 0,
  errors               jsonb not null default '[]'::jsonb
);

-- ── contacts_summary: the Contact object, with every derived field ─────────────────────────────
-- Mirrors BDCore.deriveContact (frontend/bd/js/bd-core.js) exactly:
--   * only interactions whose Central date is on or before bd_today() count;
--   * last_live_at        latest touch (counts_as_touch)
--   * last_attempt_at     latest call or voicemail, any outcome
--   * attempts_since_live calls/voicemails that were not touches, after last_live_at (all of them
--                         when there was never a live talk)
--   * touches_this_year   touches dated in bd_today()'s Central calendar year
--   * next_due_date       Central date of last_live_at + floor(365 / frequency) days; maintenance
--                         + 120 days (settings.maintenance_touch_days, read-only); null if never
--   * cadence_status      'never' (no touch) -> 'complete' (touches_this_year >= frequency;
--                         maintenance >= 3 whatever its frequency) -> 'behind' (next_due_date
--                         before today) -> 'on_track'; in that order.
-- A frequency that is missing or < 1 counts as the category default (4 bd / 3 maintenance);
-- the CHECK above already keeps it in 1..52.
create view contacts_summary with (security_invoker = on) as
select
  c.id,
  c.company_id,
  co.name                         as company_name,
  co.normalized_name              as company_normalized_name,
  c.name,
  c.title,
  c.email,
  c.email_lower,
  c.phone,
  c.phone_e164,
  c.city,
  c.industry,
  c.lead_source,
  c.stage,
  c.category,
  c.account_type,
  c.owner_id,
  ou.name                         as owner_name,
  c.co_owner_id,
  coalesce(cu.name, c.co_owner_name) as co_owner_name,
  c.frequency_per_year,
  c.confirmed,
  c.importance,
  c.next_step,
  c.next_step_date,
  c.promised_date,
  c.last_quote_date,
  c.duplicate_of,
  c.duplicate_reason,
  dc.name                         as duplicate_name,
  dco.name                        as duplicate_company,
  c.source,
  c.tags,
  c.notes,
  c.archived_at,
  c.created_at,
  d.last_live_at,
  d.last_attempt_at,
  coalesce(a.attempts_since_live, 0)::integer as attempts_since_live,
  coalesce(d.touches_this_year, 0)::integer   as touches_this_year,
  k.effective_frequency,
  k.touches_needed,
  k.cadence_interval_days,
  (bd_date(d.last_live_at) + k.cadence_interval_days) as next_due_date,
  case
    when d.last_live_at is null then 'never'
    when coalesce(d.touches_this_year, 0) >= k.touches_needed then 'complete'
    when bd_date(d.last_live_at) + k.cadence_interval_days < t.today then 'behind'
    else 'on_track'
  end                             as cadence_status,
  t.today                         as as_of
from contacts c
join companies co on co.id = c.company_id
left join users ou on ou.id = c.owner_id
left join users cu on cu.id = c.co_owner_id
left join contacts dc on dc.id = c.duplicate_of
left join companies dco on dco.id = dc.company_id
cross join lateral (select bd_today() as today) t
cross join lateral (
  select
    f.freq                                                       as effective_frequency,
    case when c.category = 'maintenance' then 3 else f.freq end  as touches_needed,
    case when c.category = 'maintenance' then 120 else 365 / f.freq end as cadence_interval_days
  from (select case when c.frequency_per_year >= 1 then c.frequency_per_year
                    when c.category = 'maintenance' then 3 else 4 end as freq) f
) k
left join lateral (
  select
    max(i.occurred_at) filter (where i.counts_as_touch)                 as last_live_at,
    max(i.occurred_at) filter (where i.kind in ('call', 'voicemail'))   as last_attempt_at,
    count(*) filter (where i.counts_as_touch
                       and bd_date(i.occurred_at) >= make_date(extract(year from t.today)::int, 1, 1)) as touches_this_year
  from interactions i
  where i.contact_id = c.id and bd_date(i.occurred_at) <= t.today
) d on true
left join lateral (
  select count(*) as attempts_since_live
  from interactions i
  where i.contact_id = c.id
    and bd_date(i.occurred_at) <= t.today
    and i.kind in ('call', 'voicemail')
    and not i.counts_as_touch
    and (d.last_live_at is null or i.occurred_at > d.last_live_at)
) a on true;
$bd_sql$;
    insert into bd.schema_migrations (name) values ('001_schema.sql');
    execute $bd_sql$
-- THE PRIVILEGE MODEL OF SCHEMA bd (#802, #805). Not a numbered migration: it is re-applied in
-- full after every run, by backend/bd/migrate.py (inside each migration's transaction and once
-- more at the end) and by the generated BD part of backend/staging/schema_pg.sql. So it is safe to
-- run any number of times, and it covers every object a LATER migration adds without being edited:
-- each step below walks the catalog of schema bd instead of naming objects.
--
-- Every grant or revoke that names a role other than public sits in a block that first checks the
-- role exists: staging has no anon or authenticated roles, and a plain revoke would fail every
-- staging deploy. bd_app itself is made by hand on prod and by the staging schema file on staging;
-- when it is missing, its part is skipped and the runner says so.
--
-- What this leaves:
--   public                          nothing on schema bd or anything in it
--   anon, authenticated, service_role   nothing on schema bd or anything in it (where they exist)
--   bd_app                          USAGE on the schema; select/insert/update/delete on the tables;
--                                   select only on the ledger and on the views; USAGE, SELECT and
--                                   UPDATE on every sequence (UPDATE so the copy tool can set them
--                                   past the highest id); execute on the functions. Nothing else,
--                                   and its search_path is bd, pg_catalog on the login itself.
--   every table                     row level security on, with one policy, bd_app_all, for bd_app
--   every view                      security_invoker on
--   every function                  search_path pinned to bd, pg_catalog

-- ── 1. public: nothing ──────────────────────────────────────────────────────────────────────────
revoke all on schema bd from public;
revoke all on all tables in schema bd from public;
revoke all on all sequences in schema bd from public;
revoke all on all functions in schema bd from public;

-- ── 2. Supabase's API roles: nothing, where they exist ──────────────────────────────────────────
do $bd_grants$
declare
  r text;
begin
  foreach r in array array['anon', 'authenticated', 'service_role'] loop
    if exists (select 1 from pg_catalog.pg_roles where rolname = r) then
      execute pg_catalog.format('revoke all on schema bd from %I', r);
      execute pg_catalog.format('revoke all on all tables in schema bd from %I', r);
      execute pg_catalog.format('revoke all on all sequences in schema bd from %I', r);
      execute pg_catalog.format('revoke all on all functions in schema bd from %I', r);
    end if;
  end loop;
end
$bd_grants$;

-- ── 3. functions: search_path pinned; views: security_invoker on ───────────────────────────────
do $bd_grants$
declare
  f regprocedure;
  v regclass;
begin
  for f in
    select p.oid::regprocedure from pg_catalog.pg_proc p
     where p.pronamespace = 'bd'::regnamespace
       and not coalesce('search_path=bd, pg_catalog' = any (p.proconfig), false)
  loop
    execute pg_catalog.format('alter function %s set search_path = bd, pg_catalog', f);
  end loop;
  for v in
    select c.oid::regclass from pg_catalog.pg_class c
     where c.relnamespace = 'bd'::regnamespace and c.relkind = 'v'
       and not coalesce('security_invoker=on' = any (c.reloptions), false)
  loop
    execute pg_catalog.format('alter view %s set (security_invoker = on)', v);
  end loop;
end
$bd_grants$;

-- ── 4. row level security on every table, one policy for bd_app ────────────────────────────────
do $bd_grants$
declare
  t regclass;
  has_app boolean := exists (select 1 from pg_catalog.pg_roles where rolname = 'bd_app');
begin
  for t in
    select c.oid::regclass from pg_catalog.pg_class c
     where c.relnamespace = 'bd'::regnamespace and c.relkind in ('r', 'p')
  loop
    if not (select c.relrowsecurity from pg_catalog.pg_class c where c.oid = t) then
      execute pg_catalog.format('alter table %s enable row level security', t);
    end if;
    if has_app and not exists (select 1 from pg_catalog.pg_policy
                                where polrelid = t and polname = 'bd_app_all') then
      execute pg_catalog.format(
        'create policy bd_app_all on %s as permissive for all to bd_app using (true) with check (true)', t);
    end if;
  end loop;
end
$bd_grants$;

-- ── 5. bd_app: the BD CRM's own login ───────────────────────────────────────────────────────────
do $bd_grants$
declare
  t regclass;
begin
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'bd_app') then
    return;
  end if;
  grant usage on schema bd to bd_app;
  for t in
    select c.oid::regclass from pg_catalog.pg_class c
     where c.relnamespace = 'bd'::regnamespace and c.relkind in ('r', 'p', 'v')
  loop
    if t = 'bd.schema_migrations'::regclass
       or (select c.relkind from pg_catalog.pg_class c where c.oid = t) = 'v' then
      -- The ledger is written only by the admin login, and a view is read-only.
      execute pg_catalog.format('revoke all on %s from bd_app', t);
      execute pg_catalog.format('grant select on %s to bd_app', t);
    else
      execute pg_catalog.format('revoke truncate, references, trigger on %s from bd_app', t);
      execute pg_catalog.format('grant select, insert, update, delete on %s to bd_app', t);
    end if;
  end loop;
  grant usage, select, update on all sequences in schema bd to bd_app;
  grant execute on all functions in schema bd to bd_app;
  -- Only when it is not already so: the setting is cluster-wide, and rewriting it on every run
  -- would make runs against two databases of one server collide.
  if not exists (select 1 from pg_catalog.pg_db_role_setting
                  where setrole = 'bd_app'::regrole and setdatabase = 0
                    and 'search_path=bd, pg_catalog' = any (setconfig)) then
    alter role bd_app set search_path = bd, pg_catalog;
  end if;
end
$bd_grants$;
$bd_sql$;
  end if;
end
$bd_migration$;

-- 002_import_values_and_event_history.sql
do $bd_migration$
begin
  if not exists (select 1 from bd.schema_migrations where name = '002_import_values_and_event_history.sql') then
    execute $bd_sql$
-- PLACED IN SCHEMA bd (#805). Ported from BD's backend/migrations at BD staging 14ff0d5.
-- Applied only by backend/bd/migrate.py or by the generated BD part of
-- backend/staging/schema_pg.sql, each inside ONE transaction, so the SET LOCAL below puts every
-- object this file creates in schema bd. Schema public is not on that path, so nothing here can
-- create in it or resolve a name to it by accident.
set local search_path = bd, pg_catalog;

-- 002: two review fixes on top of 001_schema.sql (an applied file is never edited).

-- Review finding DATA-4: a contact's audit trail is never deleted with it. events.contact_id
-- was ON DELETE CASCADE; it now blocks the delete (NO ACTION), as interactions, tasks,
-- ai_recommendations and followup_drafts already do. A contact leaves the app by archiving.
alter table events drop constraint events_contact_id_fkey;
alter table events add constraint events_contact_id_fkey
  foreign key (contact_id) references contacts (id);

-- Review finding DATA-1: what the workbook / CSV import last wrote for each field it may update
-- ({"title": "...", "next_step_date": "2026-11-03", ...}), so re-importing the same file
-- changes nothing and an edit made in the app wins until the file itself changes that field.
alter table contacts add column import_values jsonb not null default '{}'::jsonb;
$bd_sql$;
    insert into bd.schema_migrations (name) values ('002_import_values_and_event_history.sql');
    execute $bd_sql$
-- THE PRIVILEGE MODEL OF SCHEMA bd (#802, #805). Not a numbered migration: it is re-applied in
-- full after every run, by backend/bd/migrate.py (inside each migration's transaction and once
-- more at the end) and by the generated BD part of backend/staging/schema_pg.sql. So it is safe to
-- run any number of times, and it covers every object a LATER migration adds without being edited:
-- each step below walks the catalog of schema bd instead of naming objects.
--
-- Every grant or revoke that names a role other than public sits in a block that first checks the
-- role exists: staging has no anon or authenticated roles, and a plain revoke would fail every
-- staging deploy. bd_app itself is made by hand on prod and by the staging schema file on staging;
-- when it is missing, its part is skipped and the runner says so.
--
-- What this leaves:
--   public                          nothing on schema bd or anything in it
--   anon, authenticated, service_role   nothing on schema bd or anything in it (where they exist)
--   bd_app                          USAGE on the schema; select/insert/update/delete on the tables;
--                                   select only on the ledger and on the views; USAGE, SELECT and
--                                   UPDATE on every sequence (UPDATE so the copy tool can set them
--                                   past the highest id); execute on the functions. Nothing else,
--                                   and its search_path is bd, pg_catalog on the login itself.
--   every table                     row level security on, with one policy, bd_app_all, for bd_app
--   every view                      security_invoker on
--   every function                  search_path pinned to bd, pg_catalog

-- ── 1. public: nothing ──────────────────────────────────────────────────────────────────────────
revoke all on schema bd from public;
revoke all on all tables in schema bd from public;
revoke all on all sequences in schema bd from public;
revoke all on all functions in schema bd from public;

-- ── 2. Supabase's API roles: nothing, where they exist ──────────────────────────────────────────
do $bd_grants$
declare
  r text;
begin
  foreach r in array array['anon', 'authenticated', 'service_role'] loop
    if exists (select 1 from pg_catalog.pg_roles where rolname = r) then
      execute pg_catalog.format('revoke all on schema bd from %I', r);
      execute pg_catalog.format('revoke all on all tables in schema bd from %I', r);
      execute pg_catalog.format('revoke all on all sequences in schema bd from %I', r);
      execute pg_catalog.format('revoke all on all functions in schema bd from %I', r);
    end if;
  end loop;
end
$bd_grants$;

-- ── 3. functions: search_path pinned; views: security_invoker on ───────────────────────────────
do $bd_grants$
declare
  f regprocedure;
  v regclass;
begin
  for f in
    select p.oid::regprocedure from pg_catalog.pg_proc p
     where p.pronamespace = 'bd'::regnamespace
       and not coalesce('search_path=bd, pg_catalog' = any (p.proconfig), false)
  loop
    execute pg_catalog.format('alter function %s set search_path = bd, pg_catalog', f);
  end loop;
  for v in
    select c.oid::regclass from pg_catalog.pg_class c
     where c.relnamespace = 'bd'::regnamespace and c.relkind = 'v'
       and not coalesce('security_invoker=on' = any (c.reloptions), false)
  loop
    execute pg_catalog.format('alter view %s set (security_invoker = on)', v);
  end loop;
end
$bd_grants$;

-- ── 4. row level security on every table, one policy for bd_app ────────────────────────────────
do $bd_grants$
declare
  t regclass;
  has_app boolean := exists (select 1 from pg_catalog.pg_roles where rolname = 'bd_app');
begin
  for t in
    select c.oid::regclass from pg_catalog.pg_class c
     where c.relnamespace = 'bd'::regnamespace and c.relkind in ('r', 'p')
  loop
    if not (select c.relrowsecurity from pg_catalog.pg_class c where c.oid = t) then
      execute pg_catalog.format('alter table %s enable row level security', t);
    end if;
    if has_app and not exists (select 1 from pg_catalog.pg_policy
                                where polrelid = t and polname = 'bd_app_all') then
      execute pg_catalog.format(
        'create policy bd_app_all on %s as permissive for all to bd_app using (true) with check (true)', t);
    end if;
  end loop;
end
$bd_grants$;

-- ── 5. bd_app: the BD CRM's own login ───────────────────────────────────────────────────────────
do $bd_grants$
declare
  t regclass;
begin
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'bd_app') then
    return;
  end if;
  grant usage on schema bd to bd_app;
  for t in
    select c.oid::regclass from pg_catalog.pg_class c
     where c.relnamespace = 'bd'::regnamespace and c.relkind in ('r', 'p', 'v')
  loop
    if t = 'bd.schema_migrations'::regclass
       or (select c.relkind from pg_catalog.pg_class c where c.oid = t) = 'v' then
      -- The ledger is written only by the admin login, and a view is read-only.
      execute pg_catalog.format('revoke all on %s from bd_app', t);
      execute pg_catalog.format('grant select on %s to bd_app', t);
    else
      execute pg_catalog.format('revoke truncate, references, trigger on %s from bd_app', t);
      execute pg_catalog.format('grant select, insert, update, delete on %s to bd_app', t);
    end if;
  end loop;
  grant usage, select, update on all sequences in schema bd to bd_app;
  grant execute on all functions in schema bd to bd_app;
  -- Only when it is not already so: the setting is cluster-wide, and rewriting it on every run
  -- would make runs against two databases of one server collide.
  if not exists (select 1 from pg_catalog.pg_db_role_setting
                  where setrole = 'bd_app'::regrole and setdatabase = 0
                    and 'search_path=bd, pg_catalog' = any (setconfig)) then
    alter role bd_app set search_path = bd, pg_catalog;
  end if;
end
$bd_grants$;
$bd_sql$;
  end if;
end
$bd_migration$;

-- 003_one_friday_batch.sql
do $bd_migration$
begin
  if not exists (select 1 from bd.schema_migrations where name = '003_one_friday_batch.sql') then
    execute $bd_sql$
-- PLACED IN SCHEMA bd (#805). Ported from BD's backend/migrations at BD staging 14ff0d5.
-- Applied only by backend/bd/migrate.py or by the generated BD part of
-- backend/staging/schema_pg.sql, each inside ONE transaction, so the SET LOCAL below puts every
-- object this file creates in schema bd. Schema public is not on that path, so nothing here can
-- create in it or resolve a name to it by accident.
set local search_path = bd, pg_catalog;

-- 003: one live Friday batch per salesperson per week, enforced by the database (Phase 3).
--
-- The Friday batch is built by the background worker at Friday 16:00 Central AND by an admin's
-- "Run Friday batch now" (POST /api/admin/weekly/run). If both ran at once, two transactions
-- could each find no batch and each insert one. weekly.build_batch also takes a per-owner
-- advisory lock, but this index is the guarantee: the second insert fails, its transaction rolls
-- back (its rollover too), and the caller answers 409.
--
-- "force": true (api-contract.md) replaces the week's batch on purpose. The mock keeps the old
-- batch and its tasks (its open ones snoozed) and adds the new one, so the old row stays, marked
-- replaced_at, and only batches that are not replaced count for the index.
alter table task_batches add column replaced_at timestamptz;

-- A database that somehow already holds two live Friday batches for one owner and week keeps the
-- newest live and marks the older ones replaced, so the index below can be built.
update task_batches b
   set replaced_at = b.generated_at
 where b.kind = 'friday'
   and exists (select 1 from task_batches n
                where n.owner_id = b.owner_id and n.week_start = b.week_start
                  and n.kind = 'friday' and n.id > b.id);

create unique index task_batches_one_friday_key
  on task_batches (owner_id, week_start, kind)
  where kind = 'friday' and replaced_at is null;
$bd_sql$;
    insert into bd.schema_migrations (name) values ('003_one_friday_batch.sql');
    execute $bd_sql$
-- THE PRIVILEGE MODEL OF SCHEMA bd (#802, #805). Not a numbered migration: it is re-applied in
-- full after every run, by backend/bd/migrate.py (inside each migration's transaction and once
-- more at the end) and by the generated BD part of backend/staging/schema_pg.sql. So it is safe to
-- run any number of times, and it covers every object a LATER migration adds without being edited:
-- each step below walks the catalog of schema bd instead of naming objects.
--
-- Every grant or revoke that names a role other than public sits in a block that first checks the
-- role exists: staging has no anon or authenticated roles, and a plain revoke would fail every
-- staging deploy. bd_app itself is made by hand on prod and by the staging schema file on staging;
-- when it is missing, its part is skipped and the runner says so.
--
-- What this leaves:
--   public                          nothing on schema bd or anything in it
--   anon, authenticated, service_role   nothing on schema bd or anything in it (where they exist)
--   bd_app                          USAGE on the schema; select/insert/update/delete on the tables;
--                                   select only on the ledger and on the views; USAGE, SELECT and
--                                   UPDATE on every sequence (UPDATE so the copy tool can set them
--                                   past the highest id); execute on the functions. Nothing else,
--                                   and its search_path is bd, pg_catalog on the login itself.
--   every table                     row level security on, with one policy, bd_app_all, for bd_app
--   every view                      security_invoker on
--   every function                  search_path pinned to bd, pg_catalog

-- ── 1. public: nothing ──────────────────────────────────────────────────────────────────────────
revoke all on schema bd from public;
revoke all on all tables in schema bd from public;
revoke all on all sequences in schema bd from public;
revoke all on all functions in schema bd from public;

-- ── 2. Supabase's API roles: nothing, where they exist ──────────────────────────────────────────
do $bd_grants$
declare
  r text;
begin
  foreach r in array array['anon', 'authenticated', 'service_role'] loop
    if exists (select 1 from pg_catalog.pg_roles where rolname = r) then
      execute pg_catalog.format('revoke all on schema bd from %I', r);
      execute pg_catalog.format('revoke all on all tables in schema bd from %I', r);
      execute pg_catalog.format('revoke all on all sequences in schema bd from %I', r);
      execute pg_catalog.format('revoke all on all functions in schema bd from %I', r);
    end if;
  end loop;
end
$bd_grants$;

-- ── 3. functions: search_path pinned; views: security_invoker on ───────────────────────────────
do $bd_grants$
declare
  f regprocedure;
  v regclass;
begin
  for f in
    select p.oid::regprocedure from pg_catalog.pg_proc p
     where p.pronamespace = 'bd'::regnamespace
       and not coalesce('search_path=bd, pg_catalog' = any (p.proconfig), false)
  loop
    execute pg_catalog.format('alter function %s set search_path = bd, pg_catalog', f);
  end loop;
  for v in
    select c.oid::regclass from pg_catalog.pg_class c
     where c.relnamespace = 'bd'::regnamespace and c.relkind = 'v'
       and not coalesce('security_invoker=on' = any (c.reloptions), false)
  loop
    execute pg_catalog.format('alter view %s set (security_invoker = on)', v);
  end loop;
end
$bd_grants$;

-- ── 4. row level security on every table, one policy for bd_app ────────────────────────────────
do $bd_grants$
declare
  t regclass;
  has_app boolean := exists (select 1 from pg_catalog.pg_roles where rolname = 'bd_app');
begin
  for t in
    select c.oid::regclass from pg_catalog.pg_class c
     where c.relnamespace = 'bd'::regnamespace and c.relkind in ('r', 'p')
  loop
    if not (select c.relrowsecurity from pg_catalog.pg_class c where c.oid = t) then
      execute pg_catalog.format('alter table %s enable row level security', t);
    end if;
    if has_app and not exists (select 1 from pg_catalog.pg_policy
                                where polrelid = t and polname = 'bd_app_all') then
      execute pg_catalog.format(
        'create policy bd_app_all on %s as permissive for all to bd_app using (true) with check (true)', t);
    end if;
  end loop;
end
$bd_grants$;

-- ── 5. bd_app: the BD CRM's own login ───────────────────────────────────────────────────────────
do $bd_grants$
declare
  t regclass;
begin
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'bd_app') then
    return;
  end if;
  grant usage on schema bd to bd_app;
  for t in
    select c.oid::regclass from pg_catalog.pg_class c
     where c.relnamespace = 'bd'::regnamespace and c.relkind in ('r', 'p', 'v')
  loop
    if t = 'bd.schema_migrations'::regclass
       or (select c.relkind from pg_catalog.pg_class c where c.oid = t) = 'v' then
      -- The ledger is written only by the admin login, and a view is read-only.
      execute pg_catalog.format('revoke all on %s from bd_app', t);
      execute pg_catalog.format('grant select on %s to bd_app', t);
    else
      execute pg_catalog.format('revoke truncate, references, trigger on %s from bd_app', t);
      execute pg_catalog.format('grant select, insert, update, delete on %s to bd_app', t);
    end if;
  end loop;
  grant usage, select, update on all sequences in schema bd to bd_app;
  grant execute on all functions in schema bd to bd_app;
  -- Only when it is not already so: the setting is cluster-wide, and rewriting it on every run
  -- would make runs against two databases of one server collide.
  if not exists (select 1 from pg_catalog.pg_db_role_setting
                  where setrole = 'bd_app'::regrole and setdatabase = 0
                    and 'search_path=bd, pg_catalog' = any (setconfig)) then
    alter role bd_app set search_path = bd, pg_catalog;
  end if;
end
$bd_grants$;
$bd_sql$;
  end if;
end
$bd_migration$;

-- 004_cadence_rules.sql
do $bd_migration$
begin
  if not exists (select 1 from bd.schema_migrations where name = '004_cadence_rules.sql') then
    execute $bd_sql$
-- PLACED IN SCHEMA bd (#805). Ported from BD's backend/migrations at BD staging 14ff0d5.
-- Applied only by backend/bd/migrate.py or by the generated BD part of
-- backend/staging/schema_pg.sql, each inside ONE transaction, so the SET LOCAL below puts every
-- object this file creates in schema bd. Schema public is not on that path, so nothing here can
-- create in it or resolve a name to it by accident.
-- Changed in the move, and nothing else: bd_cadence_frequency pins its search_path to
-- bd, pg_catalog, and contacts_summary is re-created with security_invoker on.
set local search_path = bd, pg_catalog;

-- 004: the cadence rules (decided 2026-11-10).
--
--   * BD contacts follow ONE global cadence (settings.bd_cadence: weekly | monthly | quarterly),
--     which a person can override per contact: "follow up every [cadence] until [date]".
--     After the date the contact falls back to the global cadence. The override is active while
--     cadence_override_until >= today (Central), the last day included.
--   * A maintenance contact is "due" 120 days after its last follow-up (any logged call,
--     voicemail, meeting, hosted event, email or text; a note is not one), or at once when it
--     was never followed up. The view derives it; the weekly list (a later change) pins it.
--   * tasks.kind gains 'maintenance' (the pinned item).
--
-- Everything here is safe to apply twice: functions are `create or replace`, the columns and
-- constraints are dropped/added only when needed, the settings rows are touched only when they
-- need it, and the view is dropped and re-created (create or replace cannot insert columns).

-- ── the cadence word -> live touches a year (the one place SQL knows the table) ────────────────
-- weekly 52, monthly 12, quarterly 4. Anything else counts as quarterly (the default).
create or replace function bd_cadence_frequency(cadence text) returns integer
language sql immutable parallel safe
set search_path = bd, pg_catalog
as $$
  select case cadence when 'weekly' then 52 when 'monthly' then 12 else 4 end
$$;

-- ── tasks: the third kind ──────────────────────────────────────────────────────────────────────
alter table tasks drop constraint if exists tasks_kind_check;
alter table tasks add constraint tasks_kind_check check (kind in ('new', 'followup', 'maintenance'));

-- ── contacts: the per-contact override (both set or both empty) ────────────────────────────────
alter table contacts add column if not exists cadence_override text;
alter table contacts add column if not exists cadence_override_until date;
alter table contacts drop constraint if exists contacts_cadence_override_check;
alter table contacts add constraint contacts_cadence_override_check check (
  (cadence_override is null and cadence_override_until is null)
  or (cadence_override is not null and cadence_override in ('weekly', 'monthly', 'quarterly')
      and cadence_override_until is not null));

-- ── settings: bd_cadence from what the data already does, and default_frequency.bd retired ────
-- The mode of the BD contacts' stored frequency (52 -> weekly, 12 -> monthly, else quarterly), so
-- a database that was running at, say, 12 a year keeps that cadence. Only when there are BD
-- contacts and no bd_cadence row yet: an empty database just uses the default (quarterly).
insert into settings (key, value)
select 'bd_cadence', to_jsonb(case m.f when 52 then 'weekly' when 12 then 'monthly' else 'quarterly' end)
from (select mode() within group (order by frequency_per_year) as f
        from contacts where category = 'bd') m
where m.f is not null
  and not exists (select 1 from settings where key = 'bd_cadence');

update settings set value = value - 'bd'
 where key = 'default_frequency' and jsonb_typeof(value) = 'object' and value ? 'bd';

-- ── contacts_summary: the Contact object, with the cadence and follow-up fields ────────────────
-- What changes from 001 (every other column keeps its meaning):
--   * frequency_per_year is now DERIVED for a BD contact: bd_cadence_frequency(its cadence).
--     A maintenance contact keeps its stored number (3 when it is somehow below 1).
--     stored_frequency_per_year is the column as written.
--   * cadence / cadence_source: BD only. cadence = the active override, else settings.bd_cadence
--     (quarterly when the setting is missing or unreadable); cadence_source 'override' | 'global'.
--     Both null for maintenance.
--   * effective_frequency, touches_needed, cadence_interval_days (365 / frequency as INTEGER
--     division: 7 / 30 / 91; 120 for maintenance), next_due_date and cadence_status keep their
--     formulas; they read the derived frequency.
--   * last_followup_at: latest occurred_at over kinds call, voicemail, meeting, hosted, email,
--     sms (any outcome, never a note), dated on or before today.
--   * maintenance_due_date: Central date of last_followup_at + 120 days (maintenance only; null
--     when never followed up). maintenance_due: maintenance and (never followed up, or
--     maintenance_due_date <= today).
drop view if exists contacts_summary;
create view contacts_summary with (security_invoker = on) as
select
  c.id,
  c.company_id,
  co.name                         as company_name,
  co.normalized_name              as company_normalized_name,
  c.name,
  c.title,
  c.email,
  c.email_lower,
  c.phone,
  c.phone_e164,
  c.city,
  c.industry,
  c.lead_source,
  c.stage,
  c.category,
  c.account_type,
  c.owner_id,
  ou.name                         as owner_name,
  c.co_owner_id,
  coalesce(cu.name, c.co_owner_name) as co_owner_name,
  k.effective_frequency           as frequency_per_year,
  c.frequency_per_year            as stored_frequency_per_year,
  k.cadence,
  k.cadence_source,
  c.cadence_override,
  c.cadence_override_until,
  c.confirmed,
  c.importance,
  c.next_step,
  c.next_step_date,
  c.promised_date,
  c.last_quote_date,
  c.duplicate_of,
  c.duplicate_reason,
  dc.name                         as duplicate_name,
  dco.name                        as duplicate_company,
  c.source,
  c.tags,
  c.notes,
  c.archived_at,
  c.created_at,
  d.last_live_at,
  d.last_attempt_at,
  d.last_followup_at,
  case when c.category = 'maintenance' then bd_date(d.last_followup_at) + 120 end as maintenance_due_date,
  (c.category = 'maintenance'
     and (d.last_followup_at is null or bd_date(d.last_followup_at) + 120 <= t.today)) as maintenance_due,
  coalesce(a.attempts_since_live, 0)::integer as attempts_since_live,
  coalesce(d.touches_this_year, 0)::integer   as touches_this_year,
  k.effective_frequency,
  k.touches_needed,
  k.cadence_interval_days,
  (bd_date(d.last_live_at) + k.cadence_interval_days) as next_due_date,
  case
    when d.last_live_at is null then 'never'
    when coalesce(d.touches_this_year, 0) >= k.touches_needed then 'complete'
    when bd_date(d.last_live_at) + k.cadence_interval_days < t.today then 'behind'
    else 'on_track'
  end                             as cadence_status,
  t.today                         as as_of
from contacts c
join companies co on co.id = c.company_id
left join users ou on ou.id = c.owner_id
left join users cu on cu.id = c.co_owner_id
left join contacts dc on dc.id = c.duplicate_of
left join companies dco on dco.id = dc.company_id
cross join lateral (select bd_today() as today) t
cross join lateral (
  select case when s.v in ('weekly', 'monthly') then s.v else 'quarterly' end as bd_cadence
  from (select (select value #>> '{}' from settings where key = 'bd_cadence') as v) s
) g
cross join lateral (
  select
    case when c.category = 'maintenance' then null
         when c.cadence_override is not null and c.cadence_override_until >= t.today then c.cadence_override
         else g.bd_cadence end as cadence,
    case when c.category = 'maintenance' then null
         when c.cadence_override is not null and c.cadence_override_until >= t.today then 'override'
         else 'global' end as cadence_source
) cd
cross join lateral (
  select
    f.freq                                                       as effective_frequency,
    case when c.category = 'maintenance' then 3 else f.freq end  as touches_needed,
    case when c.category = 'maintenance' then 120 else 365 / f.freq end as cadence_interval_days,
    cd.cadence                                                   as cadence,
    cd.cadence_source                                            as cadence_source
  from (select case when c.category = 'maintenance'
                    then case when c.frequency_per_year >= 1 then c.frequency_per_year else 3 end
                    else bd_cadence_frequency(cd.cadence) end as freq) f
) k
left join lateral (
  select
    max(i.occurred_at) filter (where i.counts_as_touch)                 as last_live_at,
    max(i.occurred_at) filter (where i.kind in ('call', 'voicemail'))   as last_attempt_at,
    max(i.occurred_at) filter (where i.kind in ('call', 'voicemail', 'meeting', 'hosted', 'email', 'sms'))
                                                                        as last_followup_at,
    count(*) filter (where i.counts_as_touch
                       and bd_date(i.occurred_at) >= make_date(extract(year from t.today)::int, 1, 1)) as touches_this_year
  from interactions i
  where i.contact_id = c.id and bd_date(i.occurred_at) <= t.today
) d on true
left join lateral (
  select count(*) as attempts_since_live
  from interactions i
  where i.contact_id = c.id
    and bd_date(i.occurred_at) <= t.today
    and i.kind in ('call', 'voicemail')
    and not i.counts_as_touch
    and (d.last_live_at is null or i.occurred_at > d.last_live_at)
) a on true;
$bd_sql$;
    insert into bd.schema_migrations (name) values ('004_cadence_rules.sql');
    execute $bd_sql$
-- THE PRIVILEGE MODEL OF SCHEMA bd (#802, #805). Not a numbered migration: it is re-applied in
-- full after every run, by backend/bd/migrate.py (inside each migration's transaction and once
-- more at the end) and by the generated BD part of backend/staging/schema_pg.sql. So it is safe to
-- run any number of times, and it covers every object a LATER migration adds without being edited:
-- each step below walks the catalog of schema bd instead of naming objects.
--
-- Every grant or revoke that names a role other than public sits in a block that first checks the
-- role exists: staging has no anon or authenticated roles, and a plain revoke would fail every
-- staging deploy. bd_app itself is made by hand on prod and by the staging schema file on staging;
-- when it is missing, its part is skipped and the runner says so.
--
-- What this leaves:
--   public                          nothing on schema bd or anything in it
--   anon, authenticated, service_role   nothing on schema bd or anything in it (where they exist)
--   bd_app                          USAGE on the schema; select/insert/update/delete on the tables;
--                                   select only on the ledger and on the views; USAGE, SELECT and
--                                   UPDATE on every sequence (UPDATE so the copy tool can set them
--                                   past the highest id); execute on the functions. Nothing else,
--                                   and its search_path is bd, pg_catalog on the login itself.
--   every table                     row level security on, with one policy, bd_app_all, for bd_app
--   every view                      security_invoker on
--   every function                  search_path pinned to bd, pg_catalog

-- ── 1. public: nothing ──────────────────────────────────────────────────────────────────────────
revoke all on schema bd from public;
revoke all on all tables in schema bd from public;
revoke all on all sequences in schema bd from public;
revoke all on all functions in schema bd from public;

-- ── 2. Supabase's API roles: nothing, where they exist ──────────────────────────────────────────
do $bd_grants$
declare
  r text;
begin
  foreach r in array array['anon', 'authenticated', 'service_role'] loop
    if exists (select 1 from pg_catalog.pg_roles where rolname = r) then
      execute pg_catalog.format('revoke all on schema bd from %I', r);
      execute pg_catalog.format('revoke all on all tables in schema bd from %I', r);
      execute pg_catalog.format('revoke all on all sequences in schema bd from %I', r);
      execute pg_catalog.format('revoke all on all functions in schema bd from %I', r);
    end if;
  end loop;
end
$bd_grants$;

-- ── 3. functions: search_path pinned; views: security_invoker on ───────────────────────────────
do $bd_grants$
declare
  f regprocedure;
  v regclass;
begin
  for f in
    select p.oid::regprocedure from pg_catalog.pg_proc p
     where p.pronamespace = 'bd'::regnamespace
       and not coalesce('search_path=bd, pg_catalog' = any (p.proconfig), false)
  loop
    execute pg_catalog.format('alter function %s set search_path = bd, pg_catalog', f);
  end loop;
  for v in
    select c.oid::regclass from pg_catalog.pg_class c
     where c.relnamespace = 'bd'::regnamespace and c.relkind = 'v'
       and not coalesce('security_invoker=on' = any (c.reloptions), false)
  loop
    execute pg_catalog.format('alter view %s set (security_invoker = on)', v);
  end loop;
end
$bd_grants$;

-- ── 4. row level security on every table, one policy for bd_app ────────────────────────────────
do $bd_grants$
declare
  t regclass;
  has_app boolean := exists (select 1 from pg_catalog.pg_roles where rolname = 'bd_app');
begin
  for t in
    select c.oid::regclass from pg_catalog.pg_class c
     where c.relnamespace = 'bd'::regnamespace and c.relkind in ('r', 'p')
  loop
    if not (select c.relrowsecurity from pg_catalog.pg_class c where c.oid = t) then
      execute pg_catalog.format('alter table %s enable row level security', t);
    end if;
    if has_app and not exists (select 1 from pg_catalog.pg_policy
                                where polrelid = t and polname = 'bd_app_all') then
      execute pg_catalog.format(
        'create policy bd_app_all on %s as permissive for all to bd_app using (true) with check (true)', t);
    end if;
  end loop;
end
$bd_grants$;

-- ── 5. bd_app: the BD CRM's own login ───────────────────────────────────────────────────────────
do $bd_grants$
declare
  t regclass;
begin
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'bd_app') then
    return;
  end if;
  grant usage on schema bd to bd_app;
  for t in
    select c.oid::regclass from pg_catalog.pg_class c
     where c.relnamespace = 'bd'::regnamespace and c.relkind in ('r', 'p', 'v')
  loop
    if t = 'bd.schema_migrations'::regclass
       or (select c.relkind from pg_catalog.pg_class c where c.oid = t) = 'v' then
      -- The ledger is written only by the admin login, and a view is read-only.
      execute pg_catalog.format('revoke all on %s from bd_app', t);
      execute pg_catalog.format('grant select on %s to bd_app', t);
    else
      execute pg_catalog.format('revoke truncate, references, trigger on %s from bd_app', t);
      execute pg_catalog.format('grant select, insert, update, delete on %s to bd_app', t);
    end if;
  end loop;
  grant usage, select, update on all sequences in schema bd to bd_app;
  grant execute on all functions in schema bd to bd_app;
  -- Only when it is not already so: the setting is cluster-wide, and rewriting it on every run
  -- would make runs against two databases of one server collide.
  if not exists (select 1 from pg_catalog.pg_db_role_setting
                  where setrole = 'bd_app'::regrole and setdatabase = 0
                    and 'search_path=bd, pg_catalog' = any (setconfig)) then
    alter role bd_app set search_path = bd, pg_catalog;
  end if;
end
$bd_grants$;
$bd_sql$;
  end if;
end
$bd_migration$;

-- 005_account_merge.sql
do $bd_migration$
begin
  if not exists (select 1 from bd.schema_migrations where name = '005_account_merge.sql') then
    execute $bd_sql$
-- #811. Applied only by backend/bd/migrate.py or by the generated BD part of
-- backend/staging/schema_pg.sql, each inside ONE transaction, so the SET LOCAL below puts every
-- object this file creates in schema bd. Schema public is not on that path, so nothing here can
-- create in it or resolve a name to it by accident.
set local search_path = bd, pg_catalog;

-- 005: merging two BD accounts that are one company, and keeping a pair apart (#802 Q21, Q36).
--
-- ADDITIVE ONLY, so it applies to a database holding live rows and keeps every one: nullable
-- columns on companies (null on every account today), one new table, a check and indexes. No row is
-- written or changed. grants.sql walks the catalog, so bd_app gets the new table (row level
-- security, its policy, select/insert/update/delete) with no change to that file.

-- The soft merge's mark. The losing account is never deleted: it points at the account its people
-- moved to, with who and when, and is hidden from the account list, search and the type-ahead.
-- Undo clears all three. A live account has all three null.
alter table companies
  add column merged_into bigint references companies (id),
  add column merged_at   timestamptz,
  add column merged_by   bigint references users (id),
  add constraint companies_merged_check
    check (merged_into is null or (merged_into <> id and merged_at is not null));

create index companies_merged_into_idx on companies (merged_into) where merged_into is not null;

-- Keep separate: one row per pair a person decided are two companies, lower id first, so a pair
-- is stored once whichever way round it was chosen. A kept pair is never listed again.
create table account_pairs_kept (
  account_a   bigint not null references companies (id),
  account_b   bigint not null references companies (id),
  decided_by  bigint not null references users (id),
  decided_at  timestamptz not null default bd_now(),
  primary key (account_a, account_b),
  check (account_a < account_b)
);

create index account_pairs_kept_b_idx on account_pairs_kept (account_b);
$bd_sql$;
    insert into bd.schema_migrations (name) values ('005_account_merge.sql');
    execute $bd_sql$
-- THE PRIVILEGE MODEL OF SCHEMA bd (#802, #805). Not a numbered migration: it is re-applied in
-- full after every run, by backend/bd/migrate.py (inside each migration's transaction and once
-- more at the end) and by the generated BD part of backend/staging/schema_pg.sql. So it is safe to
-- run any number of times, and it covers every object a LATER migration adds without being edited:
-- each step below walks the catalog of schema bd instead of naming objects.
--
-- Every grant or revoke that names a role other than public sits in a block that first checks the
-- role exists: staging has no anon or authenticated roles, and a plain revoke would fail every
-- staging deploy. bd_app itself is made by hand on prod and by the staging schema file on staging;
-- when it is missing, its part is skipped and the runner says so.
--
-- What this leaves:
--   public                          nothing on schema bd or anything in it
--   anon, authenticated, service_role   nothing on schema bd or anything in it (where they exist)
--   bd_app                          USAGE on the schema; select/insert/update/delete on the tables;
--                                   select only on the ledger and on the views; USAGE, SELECT and
--                                   UPDATE on every sequence (UPDATE so the copy tool can set them
--                                   past the highest id); execute on the functions. Nothing else,
--                                   and its search_path is bd, pg_catalog on the login itself.
--   every table                     row level security on, with one policy, bd_app_all, for bd_app
--   every view                      security_invoker on
--   every function                  search_path pinned to bd, pg_catalog

-- ── 1. public: nothing ──────────────────────────────────────────────────────────────────────────
revoke all on schema bd from public;
revoke all on all tables in schema bd from public;
revoke all on all sequences in schema bd from public;
revoke all on all functions in schema bd from public;

-- ── 2. Supabase's API roles: nothing, where they exist ──────────────────────────────────────────
do $bd_grants$
declare
  r text;
begin
  foreach r in array array['anon', 'authenticated', 'service_role'] loop
    if exists (select 1 from pg_catalog.pg_roles where rolname = r) then
      execute pg_catalog.format('revoke all on schema bd from %I', r);
      execute pg_catalog.format('revoke all on all tables in schema bd from %I', r);
      execute pg_catalog.format('revoke all on all sequences in schema bd from %I', r);
      execute pg_catalog.format('revoke all on all functions in schema bd from %I', r);
    end if;
  end loop;
end
$bd_grants$;

-- ── 3. functions: search_path pinned; views: security_invoker on ───────────────────────────────
do $bd_grants$
declare
  f regprocedure;
  v regclass;
begin
  for f in
    select p.oid::regprocedure from pg_catalog.pg_proc p
     where p.pronamespace = 'bd'::regnamespace
       and not coalesce('search_path=bd, pg_catalog' = any (p.proconfig), false)
  loop
    execute pg_catalog.format('alter function %s set search_path = bd, pg_catalog', f);
  end loop;
  for v in
    select c.oid::regclass from pg_catalog.pg_class c
     where c.relnamespace = 'bd'::regnamespace and c.relkind = 'v'
       and not coalesce('security_invoker=on' = any (c.reloptions), false)
  loop
    execute pg_catalog.format('alter view %s set (security_invoker = on)', v);
  end loop;
end
$bd_grants$;

-- ── 4. row level security on every table, one policy for bd_app ────────────────────────────────
do $bd_grants$
declare
  t regclass;
  has_app boolean := exists (select 1 from pg_catalog.pg_roles where rolname = 'bd_app');
begin
  for t in
    select c.oid::regclass from pg_catalog.pg_class c
     where c.relnamespace = 'bd'::regnamespace and c.relkind in ('r', 'p')
  loop
    if not (select c.relrowsecurity from pg_catalog.pg_class c where c.oid = t) then
      execute pg_catalog.format('alter table %s enable row level security', t);
    end if;
    if has_app and not exists (select 1 from pg_catalog.pg_policy
                                where polrelid = t and polname = 'bd_app_all') then
      execute pg_catalog.format(
        'create policy bd_app_all on %s as permissive for all to bd_app using (true) with check (true)', t);
    end if;
  end loop;
end
$bd_grants$;

-- ── 5. bd_app: the BD CRM's own login ───────────────────────────────────────────────────────────
do $bd_grants$
declare
  t regclass;
begin
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'bd_app') then
    return;
  end if;
  grant usage on schema bd to bd_app;
  for t in
    select c.oid::regclass from pg_catalog.pg_class c
     where c.relnamespace = 'bd'::regnamespace and c.relkind in ('r', 'p', 'v')
  loop
    if t = 'bd.schema_migrations'::regclass
       or (select c.relkind from pg_catalog.pg_class c where c.oid = t) = 'v' then
      -- The ledger is written only by the admin login, and a view is read-only.
      execute pg_catalog.format('revoke all on %s from bd_app', t);
      execute pg_catalog.format('grant select on %s to bd_app', t);
    else
      execute pg_catalog.format('revoke truncate, references, trigger on %s from bd_app', t);
      execute pg_catalog.format('grant select, insert, update, delete on %s to bd_app', t);
    end if;
  end loop;
  grant usage, select, update on all sequences in schema bd to bd_app;
  grant execute on all functions in schema bd to bd_app;
  -- Only when it is not already so: the setting is cluster-wide, and rewriting it on every run
  -- would make runs against two databases of one server collide.
  if not exists (select 1 from pg_catalog.pg_db_role_setting
                  where setrole = 'bd_app'::regrole and setdatabase = 0
                    and 'search_path=bd, pg_catalog' = any (setconfig)) then
    alter role bd_app set search_path = bd, pg_catalog;
  end if;
end
$bd_grants$;
$bd_sql$;
  end if;
end
$bd_migration$;

-- grants.sql, re-applied on every deploy
-- THE PRIVILEGE MODEL OF SCHEMA bd (#802, #805). Not a numbered migration: it is re-applied in
-- full after every run, by backend/bd/migrate.py (inside each migration's transaction and once
-- more at the end) and by the generated BD part of backend/staging/schema_pg.sql. So it is safe to
-- run any number of times, and it covers every object a LATER migration adds without being edited:
-- each step below walks the catalog of schema bd instead of naming objects.
--
-- Every grant or revoke that names a role other than public sits in a block that first checks the
-- role exists: staging has no anon or authenticated roles, and a plain revoke would fail every
-- staging deploy. bd_app itself is made by hand on prod and by the staging schema file on staging;
-- when it is missing, its part is skipped and the runner says so.
--
-- What this leaves:
--   public                          nothing on schema bd or anything in it
--   anon, authenticated, service_role   nothing on schema bd or anything in it (where they exist)
--   bd_app                          USAGE on the schema; select/insert/update/delete on the tables;
--                                   select only on the ledger and on the views; USAGE, SELECT and
--                                   UPDATE on every sequence (UPDATE so the copy tool can set them
--                                   past the highest id); execute on the functions. Nothing else,
--                                   and its search_path is bd, pg_catalog on the login itself.
--   every table                     row level security on, with one policy, bd_app_all, for bd_app
--   every view                      security_invoker on
--   every function                  search_path pinned to bd, pg_catalog

-- ── 1. public: nothing ──────────────────────────────────────────────────────────────────────────
revoke all on schema bd from public;
revoke all on all tables in schema bd from public;
revoke all on all sequences in schema bd from public;
revoke all on all functions in schema bd from public;

-- ── 2. Supabase's API roles: nothing, where they exist ──────────────────────────────────────────
do $bd_grants$
declare
  r text;
begin
  foreach r in array array['anon', 'authenticated', 'service_role'] loop
    if exists (select 1 from pg_catalog.pg_roles where rolname = r) then
      execute pg_catalog.format('revoke all on schema bd from %I', r);
      execute pg_catalog.format('revoke all on all tables in schema bd from %I', r);
      execute pg_catalog.format('revoke all on all sequences in schema bd from %I', r);
      execute pg_catalog.format('revoke all on all functions in schema bd from %I', r);
    end if;
  end loop;
end
$bd_grants$;

-- ── 3. functions: search_path pinned; views: security_invoker on ───────────────────────────────
do $bd_grants$
declare
  f regprocedure;
  v regclass;
begin
  for f in
    select p.oid::regprocedure from pg_catalog.pg_proc p
     where p.pronamespace = 'bd'::regnamespace
       and not coalesce('search_path=bd, pg_catalog' = any (p.proconfig), false)
  loop
    execute pg_catalog.format('alter function %s set search_path = bd, pg_catalog', f);
  end loop;
  for v in
    select c.oid::regclass from pg_catalog.pg_class c
     where c.relnamespace = 'bd'::regnamespace and c.relkind = 'v'
       and not coalesce('security_invoker=on' = any (c.reloptions), false)
  loop
    execute pg_catalog.format('alter view %s set (security_invoker = on)', v);
  end loop;
end
$bd_grants$;

-- ── 4. row level security on every table, one policy for bd_app ────────────────────────────────
do $bd_grants$
declare
  t regclass;
  has_app boolean := exists (select 1 from pg_catalog.pg_roles where rolname = 'bd_app');
begin
  for t in
    select c.oid::regclass from pg_catalog.pg_class c
     where c.relnamespace = 'bd'::regnamespace and c.relkind in ('r', 'p')
  loop
    if not (select c.relrowsecurity from pg_catalog.pg_class c where c.oid = t) then
      execute pg_catalog.format('alter table %s enable row level security', t);
    end if;
    if has_app and not exists (select 1 from pg_catalog.pg_policy
                                where polrelid = t and polname = 'bd_app_all') then
      execute pg_catalog.format(
        'create policy bd_app_all on %s as permissive for all to bd_app using (true) with check (true)', t);
    end if;
  end loop;
end
$bd_grants$;

-- ── 5. bd_app: the BD CRM's own login ───────────────────────────────────────────────────────────
do $bd_grants$
declare
  t regclass;
begin
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'bd_app') then
    return;
  end if;
  grant usage on schema bd to bd_app;
  for t in
    select c.oid::regclass from pg_catalog.pg_class c
     where c.relnamespace = 'bd'::regnamespace and c.relkind in ('r', 'p', 'v')
  loop
    if t = 'bd.schema_migrations'::regclass
       or (select c.relkind from pg_catalog.pg_class c where c.oid = t) = 'v' then
      -- The ledger is written only by the admin login, and a view is read-only.
      execute pg_catalog.format('revoke all on %s from bd_app', t);
      execute pg_catalog.format('grant select on %s to bd_app', t);
    else
      execute pg_catalog.format('revoke truncate, references, trigger on %s from bd_app', t);
      execute pg_catalog.format('grant select, insert, update, delete on %s to bd_app', t);
    end if;
  end loop;
  grant usage, select, update on all sequences in schema bd to bd_app;
  grant execute on all functions in schema bd to bd_app;
  -- Only when it is not already so: the setting is cluster-wide, and rewriting it on every run
  -- would make runs against two databases of one server collide.
  if not exists (select 1 from pg_catalog.pg_db_role_setting
                  where setrole = 'bd_app'::regrole and setdatabase = 0
                    and 'search_path=bd, pg_catalog' = any (setconfig)) then
    alter role bd_app set search_path = bd, pg_catalog;
  end if;
end
$bd_grants$;

do $bd_lock$ begin perform pg_advisory_unlock(198967297); end $bd_lock$;
-- <<< BD CRM: end of the generated part <<<
