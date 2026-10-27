-- ITEM CATEGORIES, 2026-10-28 (Hanz, 2026-10-27: "For the Items we must have another column which is
-- category. The Categories will be set in the Administration tab ... Then we also need to separate these
-- categories in the Estimates.")
--
--   material_categories  jsonb  {"epoxy": "epoxy-patch", "polish": "polish-patch"}  The heading this
--                               material sits under on the v2 estimate's Material step, PER WORK TYPE,
--                               as the id of an entry in the Admin page's list (backend/item_categories.py,
--                               a JSON file on the data volume, not a table). One id per work type
--                               because the same material can be "Patch" on the Epoxy sheet and
--                               something else on the Polish one.
--
-- NULLABLE WITH NO DEFAULT, so no existing row changes. NULL reads as "uncategorised everywhere", which is
-- what every material is today, and the estimate files such a row under "Other". The code reads an absent
-- column the same way, and writes it ONLY when the Items tab sends a category (library.validate_item), so
-- the code can ship before this file runs: until then, choosing a category answers a plain message saying
-- this column is missing, and nothing else is affected. Grouping is display only; no price moves.
--
-- NOT APPLIED ANYWHERE. Safe to re-run (ADD COLUMN IF NOT EXISTS). No backfill, no data change.
-- Prod (Supabase SQL editor) and staging (psql -d treadwell) are separate databases: run it on BOTH, and
-- add the same line to backend/supabase_schema.sql and backend/staging/schema_pg.sql when it is approved
-- (two databases, DDL twice, or one drifts).

alter table public.library_items add column if not exists material_categories jsonb;

-- PostgREST caches the schema; without this a write that carries the new column errors until the cache
-- refreshes. (Staging needs it; harmless on Supabase.)
notify pgrst, 'reload schema';
