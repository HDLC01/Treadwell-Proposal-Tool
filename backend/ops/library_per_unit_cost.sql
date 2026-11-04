-- EVERY MATERIAL PRICED PER SINGLE UNIT, 2026-11-04. Hanz: "remove the order quantity. Then round up
-- would be to just the nearest single unit." The Items tab no longer has an Order Quantity column and
-- the server stores buy_qty = 1 on every write, so `unit_cost` must mean the price of ONE unit (one
-- gallon, one bag, one pound). This rewrites the rows that still hold a pack price.
--
-- THE ARITHMETIC, mirrored line for line by library.per_unit_conversion (backend/library.py) and held
-- to it by backend/tests/test_library_per_unit_cost.py, which reads this file:
--
--   unit_cost                 round(unit_cost / buy_qty, 4)   the pack price becomes the unit price
--   bulk_cost                 round(bulk_cost / buy_qty, 4)   a bulk cost was a pack cost too (priceLine
--                                                             swaps it in for unit_cost)
--   price_breaks[].unit_cost  round(cost / buy_qty, 4)        a break's cost was a pack cost too
--   price_breaks[].min_qty    unchanged                       already counted in UNITS bought (breakAt
--                                                             judges packs * buy_qty), so it still means
--                                                             the same amount
--   buy_qty                   1
--
-- Four places because unit_cost is numeric(12,4). Every row on staging today divides exactly except the
-- USG primer drum (891 / 53 = 16.81132...), which lands on 16.8113: two thousandths of a cent a gallon.
-- ACCEPTED, and the one price this file does not keep exact: the Gyp takeoff's own fallback
-- (js/gyp-takeoff.js USG_PRIMER) stays 891/53, so the Gyp workbook proof (tests/test_gyp_v2_proof.py)
-- is no longer exact on the four USG tabs' unrounded extras figure (PRIMER_SHORT states the allowance);
-- every dollar figure across the 401 recorded jobs still equals the workbook.
--
-- WHAT IT DOES TO A BID. Roundup OFF: the same price per unit, so the same cost. Roundup ON: the line
-- now buys whole UNITS instead of whole PACKS (a 5 gallon pail line needing 16.8 gallons bought 4 pails =
-- 20 gallons; it now buys 17 gallons). That is the change Hanz asked for. Usually cheaper or equal, but
-- NOT ALWAYS: on a row with a price break, whole-pack rounding could overshoot into the break (235 lb
-- needed, six 40 lb bags = 240 lb, break from 240) where whole-unit rounding stops short of it (235 lb
-- at the dearer price), so such a line can cost a little MORE than before.
--
-- THE TWO COVE AGGREGATES (wb-epoxy-cove-q28, wb-epoxy-cove-silica) are "50 lb bag" rows the cove
-- formula reads per POUND (js/epoxy-takeoff.js falls back to 0.47 and 0.44 a pound), so their unit
-- becomes 'lb' along with their price, and their seeded names stop saying "50 lb bag" (a "50 lb bag" at
-- $0.44 invites somebody to "correct" it to $22, 50 times too dear). A name somebody already changed by
-- hand is left alone.
--
-- COLUMNS THIS NEEDS: bulk_cost and price_breaks come from backend/ops/library_price_breaks.sql. They are
-- added here too (if not exists, so a no-op where they exist) so a database that missed that file does
-- not fail this one with "column does not exist".
--
-- TIMESTAMPS ARE LEFT ALONE. This is not a price revision (nothing costs more or less) and nobody edited
-- the row, so cost_updated_at, updated_at and updated_by keep saying what they said.
--
-- IDEMPOTENT: a second run matches no row (buy_qty is 1 everywhere and the two units already 'lb').
-- Prod (Supabase SQL editor) and staging (psql -d treadwell) are separate databases: THIS MUST RUN ON
-- BOTH, and before (or with) the deploy that removes the Order Quantity column, because the page stops
-- showing the pack size the day it ships.

begin;

alter table public.library_items add column if not exists price_breaks    jsonb;
alter table public.library_items add column if not exists bulk_cost       numeric(12,4);

update public.library_items li
set unit_cost    = case when li.unit_cost is null then null else round(li.unit_cost / li.buy_qty, 4) end,
    bulk_cost    = case when li.bulk_cost is null then null else round(li.bulk_cost / li.buy_qty, 4) end,
    price_breaks = case
      when jsonb_typeof(li.price_breaks) = 'array' then (
        select coalesce(jsonb_agg(
                 case when jsonb_typeof(e) = 'object'
                           and (e->>'unit_cost') ~ '^\s*-?[0-9]*\.?[0-9]+\s*$'
                      then jsonb_set(e, '{unit_cost}',
                                     to_jsonb(round((e->>'unit_cost')::numeric / li.buy_qty, 4)))
                      else e end
                 order by ord), '[]'::jsonb)
        from jsonb_array_elements(li.price_breaks) with ordinality as t(e, ord))
      else li.price_breaks end,
    buy_qty      = 1
where li.deleted_at is null
  and coalesce(li.buy_qty, 1) <> 1
  and li.buy_qty > 0;

update public.library_items
set unit = 'lb'
where id in ('wb-epoxy-cove-q28', 'wb-epoxy-cove-silica')
  and deleted_at is null
  and unit is distinct from 'lb';

update public.library_items set name = 'Silica for cove, per lb'
where id = 'wb-epoxy-cove-silica' and deleted_at is null and name = 'Silica for cove, 50 lb bag';

update public.library_items set name = 'Q28 / 40-S quartz for cove, per lb'
where id = 'wb-epoxy-cove-q28' and deleted_at is null and name = 'Q28 / 40-S quartz for cove, 50 lb bag';

commit;

-- PostgREST caches the schema: the two guarded columns above may be new on this database.
notify pgrst, 'reload schema';
