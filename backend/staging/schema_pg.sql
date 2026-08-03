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

-- ── Grants so PostgREST (service_role) can read/write ───────────────────
grant usage on schema public to service_role;
grant all on all tables in schema public to service_role;
grant all on all sequences in schema public to service_role;
alter default privileges in schema public grant all on tables to service_role;
alter default privileges in schema public grant all on sequences to service_role;
