-- 004: the cadence rules (decided 2026-11-10).
--
--   * BD contacts follow ONE global cadence (settings.bd_cadence: weekly | monthly | quarterly),
--     which a person can override per contact: "follow up every [cadence] until [date]".
--     After the date the contact falls back to the global cadence. The override is active while
--     cadence_override_until >= today (Central), the last day included.
--   * A maintenance contact is "due" 120 days after its last follow-up (any logged call,
--     voicemail, meeting, hosted event, email or text; a note is not one), or at once when it
--     was never followed up. The view derives it; the weekly list (a later change) pins it.
--   * tasks.kind gains 'maintenance' (the pinned item).
--
-- Everything here is safe to apply twice: functions are `create or replace`, the columns and
-- constraints are dropped/added only when needed, the settings rows are touched only when they
-- need it, and the view is dropped and re-created (create or replace cannot insert columns).

-- ── the cadence word -> live touches a year (the one place SQL knows the table) ────────────────
-- weekly 52, monthly 12, quarterly 4. Anything else counts as quarterly (the default).
create or replace function bd_cadence_frequency(cadence text) returns integer
language sql immutable parallel safe as $$
  select case cadence when 'weekly' then 52 when 'monthly' then 12 else 4 end
$$;

-- ── tasks: the third kind ──────────────────────────────────────────────────────────────────────
alter table tasks drop constraint if exists tasks_kind_check;
alter table tasks add constraint tasks_kind_check check (kind in ('new', 'followup', 'maintenance'));

-- ── contacts: the per-contact override (both set or both empty) ────────────────────────────────
alter table contacts add column if not exists cadence_override text;
alter table contacts add column if not exists cadence_override_until date;
alter table contacts drop constraint if exists contacts_cadence_override_check;
alter table contacts add constraint contacts_cadence_override_check check (
  (cadence_override is null and cadence_override_until is null)
  or (cadence_override is not null and cadence_override in ('weekly', 'monthly', 'quarterly')
      and cadence_override_until is not null));

-- ── settings: bd_cadence from what the data already does, and default_frequency.bd retired ────
-- The mode of the BD contacts' stored frequency (52 -> weekly, 12 -> monthly, else quarterly), so
-- a database that was running at, say, 12 a year keeps that cadence. Only when there are BD
-- contacts and no bd_cadence row yet: an empty database just uses the default (quarterly).
insert into settings (key, value)
select 'bd_cadence', to_jsonb(case m.f when 52 then 'weekly' when 12 then 'monthly' else 'quarterly' end)
from (select mode() within group (order by frequency_per_year) as f
        from contacts where category = 'bd') m
where m.f is not null
  and not exists (select 1 from settings where key = 'bd_cadence');

update settings set value = value - 'bd'
 where key = 'default_frequency' and jsonb_typeof(value) = 'object' and value ? 'bd';

-- ── contacts_summary: the Contact object, with the cadence and follow-up fields ────────────────
-- What changes from 001 (every other column keeps its meaning):
--   * frequency_per_year is now DERIVED for a BD contact: bd_cadence_frequency(its cadence).
--     A maintenance contact keeps its stored number (3 when it is somehow below 1).
--     stored_frequency_per_year is the column as written.
--   * cadence / cadence_source: BD only. cadence = the active override, else settings.bd_cadence
--     (quarterly when the setting is missing or unreadable); cadence_source 'override' | 'global'.
--     Both null for maintenance.
--   * effective_frequency, touches_needed, cadence_interval_days (365 / frequency as INTEGER
--     division: 7 / 30 / 91; 120 for maintenance), next_due_date and cadence_status keep their
--     formulas; they read the derived frequency.
--   * last_followup_at: latest occurred_at over kinds call, voicemail, meeting, hosted, email,
--     sms (any outcome, never a note), dated on or before today.
--   * maintenance_due_date: Central date of last_followup_at + 120 days (maintenance only; null
--     when never followed up). maintenance_due: maintenance and (never followed up, or
--     maintenance_due_date <= today).
drop view if exists contacts_summary;
create view contacts_summary as
select
  c.id,
  c.company_id,
  co.name                         as company_name,
  co.normalized_name              as company_normalized_name,
  c.name,
  c.title,
  c.email,
  c.email_lower,
  c.phone,
  c.phone_e164,
  c.city,
  c.industry,
  c.lead_source,
  c.stage,
  c.category,
  c.account_type,
  c.owner_id,
  ou.name                         as owner_name,
  c.co_owner_id,
  coalesce(cu.name, c.co_owner_name) as co_owner_name,
  k.effective_frequency           as frequency_per_year,
  c.frequency_per_year            as stored_frequency_per_year,
  k.cadence,
  k.cadence_source,
  c.cadence_override,
  c.cadence_override_until,
  c.confirmed,
  c.importance,
  c.next_step,
  c.next_step_date,
  c.promised_date,
  c.last_quote_date,
  c.duplicate_of,
  c.duplicate_reason,
  dc.name                         as duplicate_name,
  dco.name                        as duplicate_company,
  c.source,
  c.tags,
  c.notes,
  c.archived_at,
  c.created_at,
  d.last_live_at,
  d.last_attempt_at,
  d.last_followup_at,
  case when c.category = 'maintenance' then bd_date(d.last_followup_at) + 120 end as maintenance_due_date,
  (c.category = 'maintenance'
     and (d.last_followup_at is null or bd_date(d.last_followup_at) + 120 <= t.today)) as maintenance_due,
  coalesce(a.attempts_since_live, 0)::integer as attempts_since_live,
  coalesce(d.touches_this_year, 0)::integer   as touches_this_year,
  k.effective_frequency,
  k.touches_needed,
  k.cadence_interval_days,
  (bd_date(d.last_live_at) + k.cadence_interval_days) as next_due_date,
  case
    when d.last_live_at is null then 'never'
    when coalesce(d.touches_this_year, 0) >= k.touches_needed then 'complete'
    when bd_date(d.last_live_at) + k.cadence_interval_days < t.today then 'behind'
    else 'on_track'
  end                             as cadence_status,
  t.today                         as as_of
from contacts c
join companies co on co.id = c.company_id
left join users ou on ou.id = c.owner_id
left join users cu on cu.id = c.co_owner_id
left join contacts dc on dc.id = c.duplicate_of
left join companies dco on dco.id = dc.company_id
cross join lateral (select bd_today() as today) t
cross join lateral (
  select case when s.v in ('weekly', 'monthly') then s.v else 'quarterly' end as bd_cadence
  from (select (select value #>> '{}' from settings where key = 'bd_cadence') as v) s
) g
cross join lateral (
  select
    case when c.category = 'maintenance' then null
         when c.cadence_override is not null and c.cadence_override_until >= t.today then c.cadence_override
         else g.bd_cadence end as cadence,
    case when c.category = 'maintenance' then null
         when c.cadence_override is not null and c.cadence_override_until >= t.today then 'override'
         else 'global' end as cadence_source
) cd
cross join lateral (
  select
    f.freq                                                       as effective_frequency,
    case when c.category = 'maintenance' then 3 else f.freq end  as touches_needed,
    case when c.category = 'maintenance' then 120 else 365 / f.freq end as cadence_interval_days,
    cd.cadence                                                   as cadence,
    cd.cadence_source                                            as cadence_source
  from (select case when c.category = 'maintenance'
                    then case when c.frequency_per_year >= 1 then c.frequency_per_year else 3 end
                    else bd_cadence_frequency(cd.cadence) end as freq) f
) k
left join lateral (
  select
    max(i.occurred_at) filter (where i.counts_as_touch)                 as last_live_at,
    max(i.occurred_at) filter (where i.kind in ('call', 'voicemail'))   as last_attempt_at,
    max(i.occurred_at) filter (where i.kind in ('call', 'voicemail', 'meeting', 'hosted', 'email', 'sms'))
                                                                        as last_followup_at,
    count(*) filter (where i.counts_as_touch
                       and bd_date(i.occurred_at) >= make_date(extract(year from t.today)::int, 1, 1)) as touches_this_year
  from interactions i
  where i.contact_id = c.id and bd_date(i.occurred_at) <= t.today
) d on true
left join lateral (
  select count(*) as attempts_since_live
  from interactions i
  where i.contact_id = c.id
    and bd_date(i.occurred_at) <= t.today
    and i.kind in ('call', 'voicemail')
    and not i.counts_as_touch
    and (d.last_live_at is null or i.occurred_at > d.last_live_at)
) a on true;
