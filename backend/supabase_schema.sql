-- Treadwell Proposal Tool — Supabase schema
-- Run in Supabase → SQL Editor (or via the Supabase MCP once authenticated).
-- Safe to re-run (idempotent).

-- 1) Projects (unified across all users) ------------------------------
create table if not exists public.drafts (
  id           text primary key,                 -- client UUID from ?d=<uuid>
  data         jsonb not null default '{}'::jsonb,-- full project state blob
  owner_email  text,                              -- who created it
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  deleted_at   timestamptz                        -- NULL = active; set = in Trash
);
-- Soft-delete column for existing deployments (idempotent).
alter table public.drafts add column if not exists deleted_at timestamptz;
create index if not exists drafts_updated_idx on public.drafts (updated_at desc);
-- Partial index: the active-list query filters on deleted_at IS NULL.
create index if not exists drafts_active_idx on public.drafts (updated_at desc) where deleted_at is null;
create index if not exists drafts_trashed_idx on public.drafts (deleted_at desc) where deleted_at is not null;

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

-- ── Who can be assigned a proposal ───────────────────────────────────────────
-- A separate flag rather than a `role` value, because `role` is single-valued and a
-- Treadwell employee can be a member, an admin AND an estimator at the same time.
-- Grants nothing: it only decides who appears in the assign pickers.
--
-- Defaults FALSE, and profiles.list_estimators() falls back to every active profile
-- while nobody is flagged — publishing requires an estimator, so an empty picker would
-- block every send. Ticking the first person switches the list over.
alter table public.profiles add column if not exists is_estimator boolean not null default false;

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

-- 4) Lead inbox -------------------------------------------------------
-- BasisBoard owns the messages and is READ-ONLY to us (we never PATCH, link,
-- or delete over there). This table is OUR state for each of their messages:
-- how we triaged it, what the AI made of it, and which estimate it became.
-- Rows are created lazily on first action, so a message we've never touched
-- simply isn't here and reads as 'new'.
create table if not exists public.leads (
  id           text primary key,                  -- BasisBoard message id
  lead_status  text not null default 'new'
               check (lead_status in ('new','qualified','passed','estimate_created','trash')),
  category     text,                              -- work-type guess: epoxy|polish|combo|gyp|other
  ai           jsonb not null default '{}'::jsonb,-- cached prequalification (run once per lead)
  extract      jsonb not null default '{}'::jsonb,-- cached intake extraction
  draft_id     text,                              -- the estimate this lead became (drafts.id)
  notes        text,                              -- estimator notes
  meta         jsonb not null default '{}'::jsonb,-- BasisBoard fields snapshotted at decision time
  status_by    text,                              -- who last moved it
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create index if not exists leads_status_idx  on public.leads (lead_status);
create index if not exists leads_updated_idx on public.leads (updated_at desc);
-- One estimate per lead: the autopilot checks this before creating another.
create index if not exists leads_draft_idx   on public.leads (draft_id) where draft_id is not null;

drop trigger if exists leads_updated_at on public.leads;
create trigger leads_updated_at before update on public.leads
  for each row execute function public.set_updated_at();

-- Same posture as drafts/events: RLS on, no policies. The backend holds the
-- service-role key; browsers can never reach this table directly.
alter table public.leads enable row level security;
grant select, insert, update, delete on public.leads to service_role;

-- ── 6) draft_revisions: what was actually SENT, and when ─────────────────────
-- A project keeps ONE id for life (drafts.id == portal_proposals.proposal_id ==
-- the ?d= URL param), so a revised estimate must reuse it rather than spawning a
-- duplicate project. Each send snapshots the whole `data` blob here.
--
-- Two problems this solves at once:
--   1. Staff can produce a changed estimate on the same project and still show the
--      customer (and each other) exactly what the earlier version said.
--   2. The portal renders the customer's proposal LIVE from drafts.data, so any
--      mid-edit save silently rewrote a proposal that had already been sent —
--      including, after approval, the numbers they agreed to. The portal now pins
--      to the snapshot it sent (portal_proposals.current_revision_no).
--
-- `data` is a full copy on purpose: 5-35 kB per row measured on production, which
-- is smaller than a single generated PDF. No diffing, no partial state to rebuild.
create table if not exists public.draft_revisions (
  id           uuid primary key default gen_random_uuid(),
  project_id   text not null references public.drafts(id) on delete cascade,
  revision_no  int  not null,
  data         jsonb not null,
  created_by   text,
  created_at   timestamptz not null default now(),
  -- Makes a concurrent double-send collide instead of quietly sharing a number.
  unique (project_id, revision_no)
);
-- Serves both "latest revision for this project" and the Files-page history list.
create index if not exists draft_revisions_project_idx
  on public.draft_revisions (project_id, revision_no desc);

-- Same posture as drafts/events/leads: RLS on, no policies here. The proposal
-- tool holds the service-role key. The PORTAL reads this table as its own
-- least-privilege role, so prod also needs the grant + policy in the portal's
-- security_prod.sql (portal_app_read_draft_revisions).
alter table public.draft_revisions enable row level security;
grant select, insert, update, delete on public.draft_revisions to service_role;

-- 7) Bid Calendar — Treadwell's own entries ---------------------------
-- The calendar draws two sources on one grid. Basisboard bids are a READ-ONLY mirror:
-- our integration never writes upstream, so an edit there could not be pushed and would
-- silently revert on the next 5-minute sync. This table is the other half — entries
-- created in the tool, fully editable, and the only ones left once Treadwell moves off
-- Basisboard. There is deliberately no route that edits a mirrored bid.
create table if not exists public.calendar_events (
  id               text primary key,
  title            text not null,
  -- A full timestamp, not a date: the cut-off TIME is most of what a bid deadline is.
  -- Stored UTC, rendered in America/Chicago by the frontend — the same contract the
  -- Basisboard rows use, so one render path serves both.
  deadline_at      timestamptz,
  kind             text not null default 'bid',
  customer         text,
  location         text,
  -- Dollars, not cents. The Basisboard client converts at its boundary, and two money
  -- units in one codebase is how a bid ends up 100x too big.
  value            numeric(14,2),
  estimator_email  text,
  stage            text,
  notes            text,
  -- Optional link to a project in `drafts`. Deliberately NOT a foreign key: a deadline is
  -- often on the calendar before anyone has started the estimate, and an FK forbids
  -- exactly that.
  project_id       text,
  owner_email      text,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  -- Soft delete. A calendar is a work queue; a delete that truly destroyed a bid deadline
  -- could cost a job, and every other destructive action here is recoverable.
  deleted_at       timestamptz
);
-- The calendar's only real query: live rows in deadline order.
create index if not exists calendar_events_live_deadline_idx
  on public.calendar_events (deadline_at) where deleted_at is null;
-- "What's on Kyle's plate" — the estimator filter, over live rows only.
create index if not exists calendar_events_estimator_idx
  on public.calendar_events (estimator_email) where deleted_at is null;
-- Jumping from a project to its calendar entries.
create index if not exists calendar_events_project_idx
  on public.calendar_events (project_id)
  where deleted_at is null and project_id is not null;

-- Same posture as drafts/events/leads: RLS on, no policies here; the proposal tool holds
-- the service-role key.
alter table public.calendar_events enable row level security;
grant select, insert, update, delete on public.calendar_events to service_role;
