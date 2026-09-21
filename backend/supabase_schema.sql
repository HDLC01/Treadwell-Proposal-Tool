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

-- ── Item Library ──────────────────────────────────────────────────────────
-- Materials Treadwell buys, and the assemblies built out of them. STANDALONE: nothing in the
-- intake / estimate / proposal path reads these tables. See backend/library.py for why.
create table if not exists public.library_items (
  id           text primary key,
  name         text not null,
  category     text,
  -- Freeform. Kyle buys by Gal, Kit, Pint, Quart, Each, Bag, Roll — and the next product will
  -- use a unit nobody has thought of yet. A check constraint would block it.
  unit         text not null default 'Gal',
  -- FOUR decimal places, not two. Kyle's per-gallon prices back-solve to $85.3827 and
  -- $79.7574; holding them at two cents drifts by dollars over a large floor.
  unit_cost    numeric(12,4),
  -- Square feet one unit covers. The default a line inherits; a line may override it, because
  -- the same product is used at different coverages in different systems.
  coverage     numeric(12,3),
  sku          text,
  vendor       text,
  notes        text,
  owner_email  text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  -- Soft delete, as everywhere else here. A price list is typed by hand and every other
  -- destructive action in this tool is recoverable.
  deleted_at   timestamptz
);
-- The library's only real query: live materials in name order.
create index if not exists library_items_live_name_idx
  on public.library_items (name) where deleted_at is null;
create index if not exists library_items_category_idx
  on public.library_items (category) where deleted_at is null;

create table if not exists public.library_assemblies (
  id           text primary key,
  name         text not null,
  category     text,
  description  text,
  -- What the assembly's price is expressed per — SF for a floor system.
  unit         text not null default 'SF',
  -- [{role, item_id, coverage, note}], ordered. JSONB rather than a third table because the
  -- lines are always read and written as a whole and never queried across assemblies — the
  -- same call made for drafts.paragraph_overrides.
  --
  -- `item_id` is NOT a foreign key on purpose. A material has to be deletable even while an
  -- assembly still points at it; the pricing layer reports such a line as broken and excludes
  -- it. An FK would instead refuse the delete forever, and a cascade would silently rewrite
  -- somebody else's assembly.
  lines        jsonb not null default '[]'::jsonb,
  owner_email  text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  deleted_at   timestamptz
);
create index if not exists library_assemblies_live_name_idx
  on public.library_assemblies (name) where deleted_at is null;

-- Vendors Treadwell buys from. Its own table so the Items tab can offer a dropdown instead of a
-- free-text box that accumulates "Sherwin", "Sherwin Williams" and "SW" as three vendors.
--
-- The item still stores `vendor` as TEXT, not a foreign key. Two reasons: the BETA rows already
-- hold typed names, and a renamed vendor should not silently rewrite what a past item said it was
-- bought from. Managing this LIST is admin-only (Hanz, 2026-08-15); picking from it is not.
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

-- ── Items and Assemblies, 2026-08-15 (Hanz) ───────────────────────────────
-- Additive only, and safe to run against a database that already holds BETA rows.
--
-- `buy_qty` is the "5" of "5 Gal": Kyle buys a five-gallon pail, and pricing needs the pack size
-- separately from the unit so `unit_cost` can mean what the pail costs. Existing rows get 1,
-- which reproduces exactly what they priced before this column existed.
alter table public.library_items add column if not exists buy_qty numeric(10,3) not null default 1;
alter table public.library_items add column if not exists divisions jsonb not null default '[]'::jsonb;
-- Distinct from updated_at, which moves on every patch and is the assemblies' concurrency token.
-- This one marks a PRICE REVISION, so it moves only when the cost changes — that is the date an
-- estimator wants when they ask how old a number is.
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

-- ── Who edited it, 2026-09-04 (Hanz) ──────────────────────────────────────
-- "In the items tab we must put the name of who created it and who edited it." `owner_email`
-- already answered the first half on every table here; this is the second half.
--
-- NULLABLE, and never backfilled. Every row that predates this column was last changed by
-- somebody nobody recorded, and a `not null default` naming the creator would be a lie about who
-- touched it — the tab renders an empty one as "—". library.py read-shapes an absent column to
-- empty, so an old row needs no UPDATE to be readable (the same posture as buy_qty).
--
-- SERVER-SET, like owner_email: stamped in library.py from the authenticated request and never
-- from the request body, because authorship a client can type is authorship anybody can forge.
-- Distinct from `cost_updated_at`, which marks a PRICE revision only — this one moves on any edit,
-- including an assembly LINE change (a line edit PATCHes the whole `lines` array through the same
-- update path).
alter table public.library_items add column if not exists updated_by text;
alter table public.library_assemblies add column if not exists updated_by text;

-- ── Markup rules ──────────────────────────────────────────────────────────
-- The markup chain's rates, as editable expressions, one row per line per sheet LAYOUT. Today
-- those rates are hardcoded constants in frontend/js/polish-bid-core.js (RATES, GP_BANDS, and
-- literals inside hardBidPct), transcribed by hand off Kyle's workbook. See backend/markup.py.
--
-- KEYED ON THE TAB, not on a work type: audited 2026-09-03, the workbook's markup column keys on
-- the tab, and Seal / Epoxy blank / Leveling are tabs a bid can sit on that no work type names.
-- There is deliberately no 'combo' — a combo job is two option lines, each priced off its own
-- tab, so it has no markup of its own.
--
-- …EXCEPT for the four lines that do NOT differ per tab, which is what the 'global' layout is:
-- bond is 0 on every priced sheet, the hard-bid rule is one formula on all six sheets that carry
-- one, and travel lodging/food are $70 a night and $45 a day on all eleven. Filed once.
create table if not exists public.markup_rules (
  id           text primary key,
  -- polish | seal | epoxy | leveling | gyp | global. The five are sheet TABS; `global` is not a
  -- tab at all but the one home for the lines that are the same rule on every sheet, and its rows
  -- are read BY every tab. Checked in markup.py rather than by a CHECK constraint, for the reason
  -- the two-databases rule gives: an unapplied CHECK surfaces as a 502 on whichever database
  -- missed it, and this list grew exactly that way when `global` was added.
  layout       text not null,
  -- gp | hard_bid | contingency | super_pto | soft_costs | remodel_tax | bond, in the order the
  -- chain compounds — each line's base is the running sum above it — plus travel_lodging and
  -- travel_per_diem, which are `global` lines and not chain lines at all ($70 a night, $45 a day).
  --
  -- ONE HOME PER LINE, enforced in markup.py and not here: gp / super_pto / soft_costs are filed
  -- per tab, hard_bid / bond / travel_lodging / travel_per_diem once on `global`. A row filed
  -- under the other one is read by nothing. One such row predates the split on production
  -- (polish / bond / 1%); it is shown on the page as misfiled rather than migrated, because
  -- moving it would change its meaning from one tab to every tab.
  line_key     text not null,
  -- AN EXPRESSION, not a rate, and NULL when the line does not apply. Gyp's soft-costs cell is
  --   IF(OR(B5="Yes",B5="No"), IF(B5="Yes",.09,.1) - IF(E69>334900,.05,IF(E69>234450,.035,0)),
  --      "error")
  -- so a numeric column could not hold it. The "error" string is Kyle's own
  -- refuse-to-price-rather-than-guess behaviour and is kept verbatim.
  formula      text,
  -- NOT the same as a zero formula, and the difference is load-bearing. The Gyp tabs have NO
  -- hard-bid rate — the cell is EMPTY. "this tab has no such line" (applies=false, formula null)
  -- and "it has one and it prices to nothing" (applies=true, formula '0') are different facts and
  -- the chain treats them differently.
  applies      boolean not null default true,
  notes        text,
  -- The chain order. It compounds, so a chain read in a different order is a different price.
  sort         integer not null default 0,
  owner_email  text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz,
  -- Soft delete, as everywhere else here. Removing a rule means "stop overriding this line", so
  -- the chain falls back to its hardcoded constant — recoverable, because these are hand-typed
  -- rules that move what a bid sells for.
  deleted_at   timestamptz
);
-- ONE LIVE RULE PER (layout, line_key). Partial, so a soft-deleted row does not reserve the key —
-- markup.py writes a NEW row on a later upsert rather than reviving a formula somebody removed.
create unique index if not exists markup_rules_live_key_idx
  on public.markup_rules (layout, line_key) where deleted_at is null;
-- The module's only other query: one layout's chain, in order.
create index if not exists markup_rules_live_layout_idx
  on public.markup_rules (layout, sort) where deleted_at is null;

-- Same posture as drafts/events/calendar_events: RLS on, no policies here; the proposal tool
-- holds the service-role key.
--
-- library_labor WAS MISSING FROM THIS BLOCK until 2026-09-19, and the reason is worth keeping:
-- the table is created ~130 lines ABOVE here, so it read as already handled, and the only
-- database anyone had run it against was staging -- self-hosted Postgres, connected to as the
-- owner, where RLS is off for every table and the omission is invisible. On PROD it is Supabase,
-- every other table has RLS on, and a table without it is reachable through the REST API by anon
-- and authenticated. It was caught before the table existed on production at all, so nothing was
-- ever exposed. test_schema_rls.py now fails if a new public table is added without both lines.
alter table public.library_items enable row level security;
alter table public.library_assemblies enable row level security;
alter table public.library_vendors enable row level security;
alter table public.library_divisions enable row level security;
alter table public.library_units enable row level security;
alter table public.library_labor enable row level security;
alter table public.markup_rules enable row level security;
grant select, insert, update, delete on public.library_items to service_role;
grant select, insert, update, delete on public.library_assemblies to service_role;
grant select, insert, update, delete on public.library_vendors to service_role;
grant select, insert, update, delete on public.library_divisions to service_role;
grant select, insert, update, delete on public.library_units to service_role;
grant select, insert, update, delete on public.library_labor to service_role;
grant select, insert, update, delete on public.markup_rules to service_role;

-- ── Takeoff condition defaults ────────────────────────────────────────────
-- What a NEW Polish estimate opens ANSWERED, for the three Yes/No questions the Takeoff step
-- carries: joint filler, remove existing joint filler, and dye. See backend/condition_defaults.py.
--
-- NOT APPLIED. Written 2026-09-18 and deliberately left unrun on both databases until Hanz says
-- go. Until then backend/condition_defaults.list_defaults() answers with an empty list by design
-- and every estimate opens with the literals in frontend/js/polish-bid-core.js, exactly as today.
-- BOTH databases or neither: the one that misses this answers 502 on the first save.
--
-- AN OVERRIDE, NOT THE ANSWER. A row here says "the shipped default for this key is wrong for
-- us"; no row means the shipped literal in freshModel() stands. That is why this table carries no
-- copy of "joint filler ships on" — that fact lives once, in the JavaScript, and a second
-- statement of it here is a thing that drifts.
--
-- IT REACHES A BRAND-NEW BID AND NOTHING ELSE. An estimate that has already been saved keeps the
-- answers it was saved with, forever, whatever this table later says — the seeding is gated on
-- there being no saved estimate at all (conditionsUnstated in polish-bid-core.js). An estimator's
-- answers are their work; a default is what the next blank bid starts from.
create table if not exists public.condition_defaults (
  id            text primary key,
  -- joint_filler | remove_existing_jf | dye. The keys of CONDITION_CELLS in
  -- frontend/js/polish-bid-core.js, which is what decides the workbook cell each answer writes
  -- (Polish!E29 / Polish!F29 / Polish!E25). Checked in condition_defaults.py rather than by a
  -- CHECK constraint, for the reason this project has already paid for twice: an unapplied CHECK
  -- surfaces as a 502 on whichever database missed it, and this vocabulary will grow.
  condition_key text not null,
  -- The whole of what is editable. The CELL is not: Polish!E29 is a fact about the workbook Kyle
  -- maintains, and re-pointing an answer would put a Yes/No literal over one of his formulas.
  on_by_default boolean not null default false,
  owner_email   text,
  updated_by    text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz
);
-- ONE ROW PER CONDITION, and PLAIN rather than partial because there is deliberately no
-- deleted_at here. Everywhere else in this schema a soft delete protects something that cannot be
-- retyped — a hand-entered price, a markup formula. A row here is one boolean standing in front of
-- a constant that is still in the source: putting it back is one click on the same switch.
create unique index if not exists condition_defaults_key_idx
  on public.condition_defaults (condition_key);

-- Same posture as drafts/events/library_*: RLS on, no policies here; the proposal tool holds the
-- service-role key. Beside the table rather than in a shared block at the foot of the file — a
-- blanket grant only covers the tables that exist when it runs.
alter table public.condition_defaults enable row level security;
grant select, insert, update, delete on public.condition_defaults to service_role;
