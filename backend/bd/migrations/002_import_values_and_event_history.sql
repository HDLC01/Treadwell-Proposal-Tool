-- PLACED IN SCHEMA bd (#805). Ported from BD's backend/migrations at BD staging 14ff0d5.
-- Applied only by backend/bd/migrate.py or by the generated BD part of
-- backend/staging/schema_pg.sql, each inside ONE transaction, so the SET LOCAL below puts every
-- object this file creates in schema bd. Schema public is not on that path, so nothing here can
-- create in it or resolve a name to it by accident.
set local search_path = bd, pg_catalog;

-- 002: two review fixes on top of 001_schema.sql (an applied file is never edited).

-- Review finding DATA-4: a contact's audit trail is never deleted with it. events.contact_id
-- was ON DELETE CASCADE; it now blocks the delete (NO ACTION), as interactions, tasks,
-- ai_recommendations and followup_drafts already do. A contact leaves the app by archiving.
alter table events drop constraint events_contact_id_fkey;
alter table events add constraint events_contact_id_fkey
  foreign key (contact_id) references contacts (id);

-- Review finding DATA-1: what the workbook / CSV import last wrote for each field it may update
-- ({"title": "...", "next_step_date": "2026-11-03", ...}), so re-importing the same file
-- changes nothing and an edit made in the app wins until the file itself changes that field.
alter table contacts add column import_values jsonb not null default '{}'::jsonb;
