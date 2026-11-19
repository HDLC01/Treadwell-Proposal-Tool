"""The BD CRM (Troy's weekly 10), moved into the proposal tool (#802).

One package with package-relative imports, so nothing here can collide with the tool's own
modules (`bd.config` is never the tool's config). Ported from a clean export of BD's staging
branch, never from a working folder.

  config     every BD_ setting (python-dotenv is not used; the tool's settings are never read)
  bizdate    Central dates and timestamps, Monday weeks, the BD_TODAY / BD_NOW overrides
  normalize  the company duplicate key and trimmed names
  phone      US numbers to E.164, the last-10 match key, the display form
  pace       the annual pace bar and the week's progress
  priority   the priority score and its reasons
  serialize  database rows -> the contract's JSON objects (docs/bd/api-contract.md)
  migrate    the schema runner (python -m bd.migrate, by hand, as the admin login; never at
             startup) and ledger_behind(), the routes' "database not up to date" check
  migrations/  the numbered files that make schema bd, and grants.sql, its privilege model
  db         the connection pool (lazy, only with BD_DATABASE_URL; 3 s checkouts, 8 request
             slots, UTC + search_path + the business clock on every checkout)
  ops/       BD's command-line scripts, apart from the tool's own ops scripts
             (staging_schema writes the BD part of backend/staging/schema_pg.sql;
             fixture_seed is the made-up data set; seed loads it into an empty staging or
             test bd schema: python -m bd.ops.seed --person EMAIL=ROLE ...)

The pure rules have a JavaScript twin, frontend/bd/js/bd-core.js; tests/test_bd_core_js.py is
the shared table both must answer.
"""
