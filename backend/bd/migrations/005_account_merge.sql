-- #811. Applied only by backend/bd/migrate.py or by the generated BD part of
-- backend/staging/schema_pg.sql, each inside ONE transaction, so the SET LOCAL below puts every
-- object this file creates in schema bd. Schema public is not on that path, so nothing here can
-- create in it or resolve a name to it by accident.
set local search_path = bd, pg_catalog;

-- 005: merging two BD accounts that are one company, and keeping a pair apart (#802 Q21, Q36).
--
-- ADDITIVE ONLY, so it applies to a database holding live rows and keeps every one: nullable
-- columns on companies (null on every account today), one new table, a check and indexes. No row is
-- written or changed. grants.sql walks the catalog, so bd_app gets the new table (row level
-- security, its policy, select/insert/update/delete) with no change to that file.

-- The soft merge's mark. The losing account is never deleted: it points at the account its people
-- moved to, with who and when, and is hidden from the account list, search and the type-ahead.
-- Undo clears all three. A live account has all three null.
alter table companies
  add column merged_into bigint references companies (id),
  add column merged_at   timestamptz,
  add column merged_by   bigint references users (id),
  add constraint companies_merged_check
    check (merged_into is null or (merged_into <> id and merged_at is not null));

create index companies_merged_into_idx on companies (merged_into) where merged_into is not null;

-- Keep separate: one row per pair a person decided are two companies, lower id first, so a pair
-- is stored once whichever way round it was chosen. A kept pair is never listed again.
create table account_pairs_kept (
  account_a   bigint not null references companies (id),
  account_b   bigint not null references companies (id),
  decided_by  bigint not null references users (id),
  decided_at  timestamptz not null default bd_now(),
  primary key (account_a, account_b),
  check (account_a < account_b)
);

create index account_pairs_kept_b_idx on account_pairs_kept (account_b);
