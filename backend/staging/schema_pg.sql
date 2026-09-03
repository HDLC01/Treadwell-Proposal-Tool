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

-- Items and Assemblies, 2026-08-15. Additive, and safe against a volume already holding BETA
-- rows. buy_qty is the "5" of "5 Gal" (so unit_cost can mean what the pail costs); existing rows
-- get 1, which prices exactly as they did before the column existed. cost_updated_at marks a
-- price revision, unlike updated_at which moves on every patch.
alter table public.library_items add column if not exists buy_qty numeric(10,3) not null default 1;
alter table public.library_items add column if not exists divisions jsonb not null default '[]'::jsonb;
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

-- ── Markup rules ────────────────────────────────────────────────────────
-- The markup chain's rates as editable expressions, one row per line per sheet LAYOUT. Mirrors
-- supabase_schema.sql; see backend/markup.py for why the key is the TAB (Seal / Epoxy blank /
-- Leveling are tabs no work type names), why there is no 'combo', and why `applies` is not the
-- same as a zero formula (the Gyp tabs have NO hard-bid rate — the cell is empty).
create table if not exists public.markup_rules (
  id           text primary key,
  layout       text not null,                 -- polish | seal | epoxy | leveling | gyp
  line_key     text not null,                 -- gp | hard_bid | contingency | super_pto | …
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
