-- 003: one live Friday batch per salesperson per week, enforced by the database (Phase 3).
--
-- The Friday batch is built by the background worker at Friday 16:00 Central AND by an admin's
-- "Run Friday batch now" (POST /api/admin/weekly/run). If both ran at once, two transactions
-- could each find no batch and each insert one. weekly.build_batch also takes a per-owner
-- advisory lock, but this index is the guarantee: the second insert fails, its transaction rolls
-- back (its rollover too), and the caller answers 409.
--
-- "force": true (api-contract.md) replaces the week's batch on purpose. The mock keeps the old
-- batch and its tasks (its open ones snoozed) and adds the new one, so the old row stays, marked
-- replaced_at, and only batches that are not replaced count for the index.
alter table task_batches add column replaced_at timestamptz;

-- A database that somehow already holds two live Friday batches for one owner and week keeps the
-- newest live and marks the older ones replaced, so the index below can be built.
update task_batches b
   set replaced_at = b.generated_at
 where b.kind = 'friday'
   and exists (select 1 from task_batches n
                where n.owner_id = b.owner_id and n.week_start = b.week_start
                  and n.kind = 'friday' and n.id > b.id);

create unique index task_batches_one_friday_key
  on task_batches (owner_id, week_start, kind)
  where kind = 'friday' and replaced_at is null;
