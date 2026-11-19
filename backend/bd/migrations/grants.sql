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
