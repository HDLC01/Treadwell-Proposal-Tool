-- Coverage, waste and roundup now live on the MATERIAL (library_items), not on each assembly line.
-- Run this on a database BEFORE the code that prices from the material reaches it. It copies a
-- line's value onto its material only where the material has none and every live line that uses the
-- material agrees. Anything that disagrees is listed by STEP 1 and left alone for a person to decide
-- (split the material into two, as was done for Diamonds and Plastic on 2026-09-21).
--
-- Safe to re-run: STEP 2 only fills NULLs, so a second run changes nothing.
-- Prod (Supabase SQL editor) and staging (psql -d treadwell) are separate databases: run it on both.
--
-- Old engine: coverage = line ?? item; waste = line ?? 5; roundup = line ?? true.
-- New engine: coverage = item;         waste = item ?? 5; roundup = item ?? true.

-- STEP 1 (read-only): every live line whose price the new engine would change. Expect 0 rows after
-- STEP 2, except for conflicts, which need a split.
with l as (
  select a.name as assembly, ln->>'item_id' as item_id,
         nullif(ln->>'coverage', '')::numeric as l_cov,
         nullif(ln->>'waste_pct', '')::numeric as l_waste,
         case when ln ? 'roundup' and ln->>'roundup' is not null then (ln->>'roundup')::boolean end as l_ru
  from public.library_assemblies a, jsonb_array_elements(coalesce(a.lines, '[]'::jsonb)) ln
  where a.deleted_at is null
)
select l.assembly, i.name as material,
       coalesce(l.l_cov, i.coverage) as old_coverage, i.coverage as new_coverage,
       coalesce(l.l_waste, 5) as old_waste, coalesce(i.waste_pct, 5) as new_waste,
       coalesce(l.l_ru, true) as old_roundup, coalesce(i.roundup, true) as new_roundup
from l left join public.library_items i on i.id = l.item_id
where coalesce(l.l_cov, i.coverage) is distinct from i.coverage
   or coalesce(l.l_waste, 5) <> coalesce(i.waste_pct, 5)
   or coalesce(l.l_ru, true) <> coalesce(i.roundup, true)
order by 1, 2;

-- STEP 2: fill each material's missing value from its lines, only where every live line agrees.
begin;

with l as (
  select ln->>'item_id' as item_id,
         nullif(ln->>'coverage', '')::numeric as l_cov,
         coalesce(nullif(ln->>'waste_pct', '')::numeric, 5) as l_waste,
         coalesce(case when ln ? 'roundup' and ln->>'roundup' is not null
                       then (ln->>'roundup')::boolean end, true) as l_ru
  from public.library_assemblies a, jsonb_array_elements(coalesce(a.lines, '[]'::jsonb)) ln
  where a.deleted_at is null
), agreed as (
  select item_id,
         case when count(distinct l_cov) = 1 and count(*) = count(l_cov) then min(l_cov) end as cov,
         case when count(distinct l_waste) = 1 then min(l_waste) end as waste,
         case when count(distinct l_ru) = 1 then bool_and(l_ru) end as ru
  from l group by item_id
)
update public.library_items i
   set coverage  = coalesce(i.coverage, g.cov),
       waste_pct = case when i.waste_pct is null and g.waste is not null and g.waste <> 5
                        then g.waste else i.waste_pct end,
       roundup   = case when i.roundup is null and g.ru is false then false else i.roundup end
  from agreed g
 where g.item_id = i.id
   and ((i.coverage is null and g.cov is not null)
        or (i.waste_pct is null and g.waste is not null and g.waste <> 5)
        or (i.roundup is null and g.ru is false));

commit;

-- Then run STEP 1 again. Whatever it still lists is a real conflict (one material used at two
-- different coverages, wastes or roundups): split that material into two with distinct names and
-- repoint one assembly's line, then run STEP 1 once more until it lists nothing.
