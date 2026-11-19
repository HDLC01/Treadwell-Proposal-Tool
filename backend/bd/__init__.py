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
  ops/       BD's command-line scripts, apart from the tool's own ops scripts

The pure rules have a JavaScript twin, frontend/bd/js/bd-core.js; tests/test_bd_core_js.py is
the shared table both must answer.
"""
