-- THE THREE CREW LINES BECOME ROWS OF THE LABOR LIST, 2026-10-09 (Hanz: "Labor is like the Items
-- tab for pulling in data in the estimate sheet").
--
-- Polishing, Mock-up and Joint filler were hard-coded in js/bid-model.js. They are library_labor rows
-- now, with the SAME ids (`polishing`, `mockup`, `jointfill`) so a bid saved before and a bid opened
-- after read the same lines and seedLibraryLabor's id de-dup keeps them from doubling. Their starting
-- crew lives where every other default's does: a `fixed` row of library_labor_calc keyed by the line
-- id (3 guys; Mock-up half a day; days blank on the other two because the estimator judges them).
--
-- Rate 33.00 is the shipped rate nobody chose, so these follow the company labor rate until an admin
-- types one. default_work_types ["polish"], favorite true, sort after Travel (-1).
--
-- IDEMPOTENT AND NEVER OVERWRITES: `on conflict do nothing` on both tables, so re-running leaves any
-- row Kyle edited (a rate, a name, a removed default, a calculator change) exactly as he left it.
-- NO DDL: needs library_labor (+ favorite, default_work_types, default_on) and library_labor_calc to
-- exist already. Prod (Supabase SQL editor) and staging (psql -d treadwell) are separate databases:
-- run it on BOTH, the calculator table first if it is missing (backend/ops/labor_calc.sql).
-- js/bid-model.js SHIPPED_CREW is the fallback when a database has not had this run; the two are
-- pinned equal by test_crew_labor_library.py.

insert into public.library_labor (id, name, rate, unit, guys_auto, sort, favorite, default_work_types)
values
  ('polishing', 'Polishing',    33.00, 'days', false, 1, true, '["polish"]'::jsonb),
  ('mockup',    'Mock-up',      33.00, 'days', false, 2, true, '["polish"]'::jsonb),
  ('jointfill', 'Joint filler', 33.00, 'days', false, 3, true, '["polish"]'::jsonb)
on conflict (id) do nothing;

insert into public.library_labor_calc (line_id, mode, crew, sf_per_day, hours_per_day, guys, days, rate)
values
  ('polishing', 'fixed', null, null, 8, 3, null, null),
  ('mockup',    'fixed', null, null, 8, 3, 0.5,  null),
  ('jointfill', 'fixed', null, null, 8, 3, null, null)
on conflict (line_id) do nothing;
