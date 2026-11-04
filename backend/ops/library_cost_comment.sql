-- THE COST COMMENT, 2026-11-04: a free-text note on a material's price, typed in the Items tab's
-- Cost Comment column (between Vendor and History). Hanz: "a cost comment field that would be a notes
-- section so that we just have an idea, or we just want to put notes on that item."
--
--   cost_comment    text    Why the price is what it is: a quote number, who said so, when it runs out.
--                           NULL means "no comment". Trimmed by the server; blank is stored as NULL.
--
-- NOT the existing `notes` column. That one holds the seed's provenance ("Seeded from Kyle's estimate
-- workbook, Epoxy tab, price cell ...") and stays hidden from the tab.
--
-- NULLABLE WITH NO DEFAULT, so no existing row changes and nothing prices differently.
--
-- Safe to re-run (ADD COLUMN IF NOT EXISTS). No backfill, no data change.
-- Prod (Supabase SQL editor) and staging (psql -d treadwell) are separate databases: THIS MUST RUN ON
-- BOTH. Until it has run on a database, the code never writes the column there (library.validate_item
-- writes it only when the request carries it, and GET /api/library/items answers
-- cost_comment_writable: false, so the Items tab shows the comment read-only and sends none).
--
-- Same change lives in backend/supabase_schema.sql and backend/staging/schema_pg.sql, which is how a
-- fresh database gets it. Two databases, DDL twice, or one drifts.

alter table public.library_items add column if not exists cost_comment text;

-- PostgREST caches the schema; without this a write that carries the new column errors until the
-- cache refreshes. (Staging needs it; harmless on Supabase.)
notify pgrst, 'reload schema';
