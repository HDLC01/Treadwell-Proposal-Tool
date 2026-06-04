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

-- ── Grants so PostgREST (service_role) can read/write ───────────────────
grant usage on schema public to service_role;
grant all on all tables in schema public to service_role;
grant all on all sequences in schema public to service_role;
alter default privileges in schema public grant all on tables to service_role;
alter default privileges in schema public grant all on sequences to service_role;
