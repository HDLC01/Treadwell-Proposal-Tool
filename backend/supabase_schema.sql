-- Treadwell Proposal Tool — Supabase schema
-- Run in Supabase → SQL Editor (or via the Supabase MCP once authenticated).
-- Safe to re-run (idempotent).

-- 1) Projects (unified across all users) ------------------------------
create table if not exists public.drafts (
  id           text primary key,                 -- client UUID from ?d=<uuid>
  data         jsonb not null default '{}'::jsonb,-- full project state blob
  owner_email  text,                              -- who created it
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create index if not exists drafts_updated_idx on public.drafts (updated_at desc);

-- 2) Activity / history log -------------------------------------------
create table if not exists public.events (
  id           bigint generated always as identity primary key,
  project_id   text,
  actor_email  text,
  action       text not null,                     -- 'created' | 'generated' | admin actions
  detail       jsonb not null default '{}'::jsonb,
  created_at   timestamptz not null default now()
);
create index if not exists events_created_idx on public.events (created_at desc);

-- 3) Profiles — roles + status for the admin dashboard ----------------
create table if not exists public.profiles (
  id           uuid primary key references auth.users(id) on delete cascade,
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

-- updated_at auto-bump --------------------------------------------------
create or replace function public.set_updated_at() returns trigger as $$
begin new.updated_at = now(); return new; end; $$ language plpgsql;

drop trigger if exists drafts_updated_at on public.drafts;
create trigger drafts_updated_at before update on public.drafts
  for each row execute function public.set_updated_at();

drop trigger if exists profiles_updated_at on public.profiles;
create trigger profiles_updated_at before update on public.profiles
  for each row execute function public.set_updated_at();

-- Auto-create a profile on signup; bootstrap the super admin -----------
create or replace function public.handle_new_user() returns trigger as $$
begin
  insert into public.profiles (id, email, full_name, role)
  values (
    new.id,
    new.email,
    coalesce(new.raw_user_meta_data->>'full_name', new.raw_user_meta_data->>'name'),
    case when lower(new.email) = 'hanz@wetreadwell.com' then 'super_admin' else 'user' end
  )
  on conflict (id) do update
    set email = excluded.email,
        full_name = coalesce(excluded.full_name, public.profiles.full_name);
  return new;
end; $$ language plpgsql security definer;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- RLS: enable on all three. The backend uses the SERVICE-ROLE key (bypasses
-- RLS); with no permissive policies, anon/authenticated clients can't touch
-- these tables directly — every read/write goes through our gated API.
alter table public.drafts   enable row level security;
alter table public.events   enable row level security;
alter table public.profiles enable row level security;
