-- PHASE 11 OF THE ESTIMATING PROGRAM, 2026-10-12: three more things a material can say about its price.
--
--   price_breaks    jsonb   [{"min_qty": 240, "unit_cost": 90}, ...]  From this many units bought, the pack
--                           costs this instead. Smallest quantity first, each one larger than the last.
--                           Kyle's flake: 2.30 a pound under 240 lb, 2.25 a pound from 240 lb up.
--   bulk_cost       numeric The pack cost when the bid has "Bulk Discount ON" (Kyle's D41). Four decimals,
--                           like unit_cost: his bulk prices back-solve to figures like 58.1846.
--   coverage_basis  text    What the coverage is quoted per: 'sf' (floor area), 'lf' (length, as cove is)
--                           or 'each' (a count). NULL means "use the area the caller measured".
--
-- ALL THREE ARE NULLABLE WITH NO DEFAULT, so no existing row changes and every existing bid prices
-- exactly as it did. library-core.js reads an empty value as "this material has none".
--
-- Safe to re-run (ADD COLUMN IF NOT EXISTS). No backfill, no data change.
-- Prod (Supabase SQL editor) and staging (psql -d treadwell) are separate databases. APPLIED TO STAGING
-- ONLY, 2026-10-12. Production needs Hanz's go before this runs there; until then the code never writes
-- these columns to a database that lacks them (library.validate_item writes one only when the request
-- carries it) and reads an absent column as empty.
--
-- Same change lives in backend/supabase_schema.sql and backend/staging/schema_pg.sql, which is how a
-- fresh database gets it. Two databases, DDL twice, or one drifts.

alter table public.library_items add column if not exists price_breaks    jsonb;
alter table public.library_items add column if not exists bulk_cost       numeric(12,4);
alter table public.library_items add column if not exists coverage_basis  text
  check (coverage_basis in ('sf', 'lf', 'each'));

-- PostgREST caches the schema; without this a write that carries a new column errors until the
-- cache refreshes. (Staging needs it; harmless on Supabase.)
notify pgrst, 'reload schema';
