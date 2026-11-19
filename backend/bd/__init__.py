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
             startup). Nothing the app imports loads it
  ledger     the runner's read-only half: ledger_behind(), the routes' "database not up to date"
             check
  migrations/  the numbered files that make schema bd, and grants.sql, its privilege model
  db         the connection pool (lazy, only with BD_DATABASE_URL; 3 s checkouts, 8 request
             slots, UTC + search_path + the business clock on every checkout)
  ops/       BD's command-line scripts, apart from the tool's own ops scripts
             (staging_schema writes the BD part of backend/staging/schema_pg.sql;
             fixture_seed is the made-up data set; seed loads it into an empty staging or
             test bd schema: python -m bd.ops.seed --person EMAIL=ROLE ...)

THE API (#806), on the proposal tool's app, every route under /api/bd/:
  api        the BD router main.py includes: the BD switch first, the routers, the routes not
             built yet, BD's catch-all 404 last
  web        BDRoute (BD's error envelope and no-store, applied by the router itself, never
             app-wide), make_router(), the BD_ENABLED switch
  errors     the envelope ({"ok": false, "error", "message"}) and handle(), its one entry point
  auth       the BD login (bd.users) for the identity the tool's gate verified, the five BD roles,
             can(), and who may change a BD login (only a super admin changes an admin)
  appsettings  BD's Settings object (defaults merged with bd.settings)
  paging     limit / offset and other query-string numbers
  routers/   meta (me, settings, users), week (This Week and the task buttons), interactions
             (the timeline and logging), contacts (the list, the possible-duplicate person check,
             create, one contact's get, patch and confirm, archive), companies (the type-ahead,
             one company, create, patch), admin (the manual weekly run), pending (503 after the
             role check)
  events     the audit log, which is also a contact timeline's event rows
  contacts_service  what the contacts and companies routers share: the duplicate check, finding or
             making a company, a contact's field checks and size limits, making a contact
  interactions_service  logging an interaction and what follows (tasks closed, the touch
             clearing a promise, the fallback next step), shared by the routers
  weekly     the weekly 10: the ranking, the Friday batch with its rollover, Give Me 10 More
  weekly_worker  the Friday batch's thread, started from main.py's startup hooks only with
             BD_WEEKLY_ENABLED and BD_ENABLED on, never under pytest

The pure rules have a JavaScript twin, frontend/bd/js/bd-core.js; tests/test_bd_core_js.py is
the shared table both must answer.
"""
