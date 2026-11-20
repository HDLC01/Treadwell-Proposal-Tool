"""contacts_summary (backend/bd/migrations/004_cadence_rules.sql): the BD cadence and the maintenance
follow-up clock. Moved from BD's tests/test_cadence_view.py with the contact page (#808).

The view is the server's one copy of these rules (the JS twin is frontend/bd/js/bd-core.js
deriveContact; tests/test_bd_core_js.py holds the two together). Each test here builds its own
contacts on the empty BD test database (bd_db, as the bd_app-like login) and moves today with
bd_today, so a rule that drifts names itself. The last two read the fixture seed
(bd/ops/fixture_seed.py) in place of BD's retired mock data. Everything is invented.

  * BD cadence: the active override (its last day included) else settings.bd_cadence; the cadence
    word gives the frequency (52 / 12 / 4), which feeds the interval (7 / 30 / 91), next_due_date
    and cadence_status. A missing or unreadable setting is quarterly. Maintenance has no cadence.
  * last_followup_at: call (any outcome), voicemail, meeting, hosted, email, sms; never a note;
    never one dated after today.
  * maintenance_due_date = Central date of last_followup_at + 120; maintenance_due = never
    followed up, or that date is today or earlier.
"""
from __future__ import annotations

import datetime as dt

import pytest

TODAY = dt.date(2026, 11, 4)


@pytest.fixture
def today_set(bd_today):
    bd_today(TODAY.isoformat())
    return TODAY


def _company(db):
    row = db.execute("select id from companies where name = 'Cadence Co'").fetchone()
    if row:
        return row["id"]
    return db.execute("insert into companies (name, normalized_name) values ('Cadence Co', 'cadence co')"
                      " returning id").fetchone()["id"]


def add_contact(db, category="bd", frequency=None, override=None, until=None, name="Pat Example"):
    return db.execute(
        "insert into contacts (company_id, name, category, frequency_per_year, cadence_override,"
        " cadence_override_until) values (%s, %s, %s, %s, %s, %s) returning id",
        (_company(db), name, category, frequency, override, until)).fetchone()["id"]


_OUTCOME = {"call": "answered", "voicemail": "voicemail"}


def add_interaction(db, contact_id, kind, day, outcome="default"):
    """An interaction at midday UTC of `day`: the same Central date, whatever the offset."""
    if outcome == "default":
        outcome = _OUTCOME.get(kind)
    db.execute("insert into interactions (contact_id, kind, outcome, occurred_at, provider)"
               " values (%s, %s, %s, %s, 'manual')",
               (contact_id, kind, outcome, "%sT18:00:00Z" % day))


def set_cadence(db, word):
    db.execute("insert into settings (key, value) values ('bd_cadence', to_jsonb(%s::text))"
               " on conflict (key) do update set value = excluded.value", (word,))


def row(db, contact_id):
    return db.execute("select * from contacts_summary where id = %s", (contact_id,)).fetchone()


def ago(days):
    return (TODAY - dt.timedelta(days=days)).isoformat()


# ── the BD cadence ────────────────────────────────────────────────────────────────────────────
def test_a_bd_contact_follows_the_global_cadence_and_quarterly_is_the_default(bd_db, today_set):
    cid = add_contact(bd_db)
    r = row(bd_db, cid)
    assert (r["cadence"], r["cadence_source"]) == ("quarterly", "global")
    assert (r["frequency_per_year"], r["effective_frequency"], r["touches_needed"],
            r["cadence_interval_days"]) == (4, 4, 4, 91)
    assert (r["cadence_override"], r["cadence_override_until"]) == (None, None)


@pytest.mark.parametrize("word,freq,interval", [("weekly", 52, 7), ("monthly", 12, 30), ("quarterly", 4, 91)])
def test_each_global_cadence_gives_its_frequency_and_interval(bd_db, today_set, word, freq, interval):
    set_cadence(bd_db, word)
    r = row(bd_db, add_contact(bd_db))
    assert (r["cadence"], r["frequency_per_year"], r["touches_needed"], r["cadence_interval_days"]) == \
        (word, freq, freq, interval)


@pytest.mark.parametrize("stored", ['"fortnightly"', '"Weekly"', '12', 'null', '["weekly"]', '""'])
def test_an_unreadable_setting_counts_as_quarterly(bd_db, today_set, stored):
    bd_db.execute("insert into settings (key, value) values ('bd_cadence', %s::jsonb)", (stored,))
    r = row(bd_db, add_contact(bd_db))
    assert (r["cadence"], r["frequency_per_year"]) == ("quarterly", 4)


def test_the_cadence_function(bd_db):
    got = {w: bd_db.execute("select bd_cadence_frequency(%s) as f", (w,)).fetchone()["f"]
           for w in ("weekly", "monthly", "quarterly", "daily", None)}
    assert got == {"weekly": 52, "monthly": 12, "quarterly": 4, "daily": 4, None: 4}


def test_the_stored_number_of_a_bd_contact_is_kept_but_not_used(bd_db, today_set):
    cid = add_contact(bd_db, frequency=2)
    r = row(bd_db, cid)
    assert (r["stored_frequency_per_year"], r["frequency_per_year"], r["cadence_interval_days"]) == (2, 4, 91)


def test_an_override_is_active_through_its_last_day_and_gone_the_day_after(bd_db, bd_today, today_set):
    cid = add_contact(bd_db, override="monthly", until=TODAY)
    r = row(bd_db, cid)
    assert (r["cadence"], r["cadence_source"], r["frequency_per_year"], r["cadence_interval_days"]) == \
        ("monthly", "override", 12, 30)
    bd_today("2026-11-05")
    r = row(bd_db, cid)
    assert (r["cadence"], r["cadence_source"], r["frequency_per_year"], r["cadence_interval_days"]) == \
        ("quarterly", "global", 4, 91)
    # The stored override is still reported once it has lapsed.
    assert (r["cadence_override"], r["cadence_override_until"]) == ("monthly", TODAY)
    bd_today("2026-11-03")                       # and an earlier day sees it active again
    assert row(bd_db, cid)["cadence_source"] == "override"


def test_an_override_beats_the_global_cadence_both_ways(bd_db, today_set):
    weekly = add_contact(bd_db, override="weekly", until=ago(-30), name="Weekly One")
    quarterly = add_contact(bd_db, override="quarterly", until=ago(-30), name="Quarterly One")
    set_cadence(bd_db, "monthly")
    assert (row(bd_db, weekly)["cadence"], row(bd_db, weekly)["frequency_per_year"]) == ("weekly", 52)
    assert (row(bd_db, quarterly)["cadence"], row(bd_db, quarterly)["frequency_per_year"]) == ("quarterly", 4)
    set_cadence(bd_db, "weekly")
    assert row(bd_db, quarterly)["cadence_source"] == "override"


def test_a_global_change_moves_frequency_next_due_date_and_status(bd_db, today_set):
    cid = add_contact(bd_db)
    add_interaction(bd_db, cid, "call", "2026-10-01")
    seen = {}
    for word in ("quarterly", "monthly", "weekly"):
        set_cadence(bd_db, word)
        r = row(bd_db, cid)
        seen[word] = (r["frequency_per_year"], r["next_due_date"].isoformat(), r["cadence_status"])
    assert seen == {
        "quarterly": (4, "2026-12-31", "on_track"),     # Oct 1 + 91
        "monthly": (12, "2026-10-31", "behind"),        # Oct 1 + 30, before today
        "weekly": (52, "2026-10-08", "behind"),         # Oct 1 + 7
    }


def test_complete_depends_on_the_cadences_touches(bd_db, today_set):
    cid = add_contact(bd_db)
    for d in ("2026-01-10", "2026-03-10", "2026-06-10", "2026-10-01"):
        add_interaction(bd_db, cid, "call", d)
    assert row(bd_db, cid)["cadence_status"] == "complete"       # 4 touches, quarterly needs 4
    set_cadence(bd_db, "monthly")
    assert row(bd_db, cid)["cadence_status"] == "behind"         # needs 12; Oct 1 + 30 is before today
    set_cadence(bd_db, "weekly")
    assert row(bd_db, cid)["cadence_status"] == "behind"         # needs 52; Oct 1 + 7 is before today
    add_interaction(bd_db, cid, "call", "2026-11-02")
    assert row(bd_db, cid)["cadence_status"] == "on_track"       # Nov 2 + 7 is not before today


def test_a_never_reached_contact_is_never_whatever_the_cadence(bd_db, today_set):
    cid = add_contact(bd_db)
    for word in ("weekly", "monthly", "quarterly"):
        set_cadence(bd_db, word)
        r = row(bd_db, cid)
        assert (r["cadence_status"], r["next_due_date"]) == ("never", None)


def test_a_maintenance_contact_has_no_cadence_and_keeps_its_stored_number(bd_db, today_set):
    set_cadence(bd_db, "weekly")
    r = row(bd_db, add_contact(bd_db, category="maintenance", frequency=6))
    assert (r["cadence"], r["cadence_source"]) == (None, None)
    assert (r["frequency_per_year"], r["stored_frequency_per_year"], r["touches_needed"],
            r["cadence_interval_days"]) == (6, 6, 3, 120)


def test_a_maintenance_contact_ignores_an_override(bd_db, today_set):
    r = row(bd_db, add_contact(bd_db, category="maintenance", frequency=3, override="weekly", until=ago(-30)))
    assert (r["cadence"], r["cadence_source"], r["frequency_per_year"]) == (None, None, 3)
    assert (r["cadence_override"], r["cadence_override_until"]) == ("weekly", TODAY + dt.timedelta(days=30))


def test_a_contact_that_becomes_bd_follows_the_cadence(bd_db, today_set):
    cid = add_contact(bd_db, category="maintenance", frequency=6)
    set_cadence(bd_db, "monthly")
    bd_db.execute("update contacts set category = 'bd' where id = %s", (cid,))
    r = row(bd_db, cid)
    assert (r["cadence"], r["frequency_per_year"], r["stored_frequency_per_year"]) == ("monthly", 12, 6)


def test_the_override_check_refuses_half_an_override(bd_db, today_set):
    import psycopg
    for kw in ({"override": "weekly"}, {"until": TODAY}, {"override": "daily", "until": TODAY}):
        with pytest.raises(psycopg.errors.CheckViolation):
            add_contact(bd_db, **kw)


# ── the maintenance follow-up clock ───────────────────────────────────────────────────────────
def test_a_maintenance_contact_never_followed_up_is_due_now(bd_db, today_set):
    r = row(bd_db, add_contact(bd_db, category="maintenance"))
    assert (r["maintenance_due"], r["maintenance_due_date"], r["last_followup_at"]) == (True, None, None)


@pytest.mark.parametrize("days,due,due_date_offset", [
    (0, False, 120), (30, False, 90), (119, False, 1), (120, True, 0), (121, True, -1), (400, True, -280),
])
def test_maintenance_is_due_on_the_120th_day_after_the_last_follow_up(bd_db, today_set, days, due, due_date_offset):
    cid = add_contact(bd_db, category="maintenance")
    add_interaction(bd_db, cid, "email", ago(days))
    r = row(bd_db, cid)
    assert r["maintenance_due"] is due
    assert r["maintenance_due_date"] == TODAY + dt.timedelta(days=due_date_offset)
    assert r["last_followup_at"] is not None


def test_the_due_day_follows_today(bd_db, bd_today, today_set):
    cid = add_contact(bd_db, category="maintenance")
    add_interaction(bd_db, cid, "email", ago(119))
    assert row(bd_db, cid)["maintenance_due"] is False
    bd_today("2026-11-05")
    assert row(bd_db, cid)["maintenance_due"] is True
    bd_today("2026-11-04")
    assert row(bd_db, cid)["maintenance_due"] is False


@pytest.mark.parametrize("kind,outcome", [
    ("call", "answered"), ("call", "no_answer"), ("call", "meeting_set"), ("voicemail", "voicemail"),
    ("meeting", None), ("hosted", None), ("email", None), ("sms", None),
])
def test_every_logged_action_but_a_note_clears_a_due_contact(bd_db, today_set, kind, outcome):
    cid = add_contact(bd_db, category="maintenance")
    add_interaction(bd_db, cid, kind, ago(200))
    assert row(bd_db, cid)["maintenance_due"] is True
    add_interaction(bd_db, cid, kind, ago(1), outcome)
    r = row(bd_db, cid)
    assert r["maintenance_due"] is False
    assert r["maintenance_due_date"] == TODAY - dt.timedelta(days=1) + dt.timedelta(days=120)


def test_a_note_does_not_clear_a_due_contact(bd_db, today_set):
    cid = add_contact(bd_db, category="maintenance")
    add_interaction(bd_db, cid, "call", ago(200))
    before = row(bd_db, cid)
    add_interaction(bd_db, cid, "note", ago(1))
    after = row(bd_db, cid)
    assert after["maintenance_due"] is True
    assert (after["last_followup_at"], after["maintenance_due_date"]) == \
        (before["last_followup_at"], before["maintenance_due_date"])


def test_a_note_alone_leaves_a_contact_never_followed_up(bd_db, today_set):
    cid = add_contact(bd_db, category="maintenance")
    add_interaction(bd_db, cid, "note", ago(1))
    r = row(bd_db, cid)
    assert (r["maintenance_due"], r["last_followup_at"], r["maintenance_due_date"]) == (True, None, None)


def test_an_email_clears_maintenance_due_but_not_the_touch_clock(bd_db, today_set):
    """Pace and next_due_date count live talks only: an email is a follow-up, not a touch."""
    cid = add_contact(bd_db, category="maintenance")
    add_interaction(bd_db, cid, "call", ago(150))
    before = row(bd_db, cid)
    assert (before["maintenance_due"], before["cadence_status"]) == (True, "behind")
    assert before["next_due_date"] == TODAY - dt.timedelta(days=30)
    add_interaction(bd_db, cid, "email", ago(2))
    after = row(bd_db, cid)
    assert after["maintenance_due"] is False
    assert after["maintenance_due_date"] == TODAY + dt.timedelta(days=118)
    assert (after["next_due_date"], after["cadence_status"], after["last_live_at"], after["touches_this_year"]) == \
        (before["next_due_date"], "behind", before["last_live_at"], before["touches_this_year"])
    assert after["last_followup_at"] > before["last_followup_at"]


def test_a_follow_up_is_not_a_live_touch_for_a_bd_contact_either(bd_db, today_set):
    cid = add_contact(bd_db)
    add_interaction(bd_db, cid, "email", ago(3))
    r = row(bd_db, cid)
    assert (r["cadence_status"], r["next_due_date"], r["touches_this_year"], r["last_live_at"]) == \
        ("never", None, 0, None)
    assert r["last_followup_at"] is not None


def test_interactions_dated_after_today_are_ignored(bd_db, today_set):
    cid = add_contact(bd_db, category="maintenance")
    add_interaction(bd_db, cid, "call", ago(200))
    add_interaction(bd_db, cid, "email", (TODAY + dt.timedelta(days=1)).isoformat())
    add_interaction(bd_db, cid, "meeting", (TODAY + dt.timedelta(days=30)).isoformat())
    r = row(bd_db, cid)
    assert r["maintenance_due"] is True
    assert r["maintenance_due_date"] == TODAY - dt.timedelta(days=80)
    # An interaction later today still counts (the date is what matters, not the time).
    add_interaction(bd_db, cid, "email", TODAY.isoformat())
    assert row(bd_db, cid)["maintenance_due"] is False


def test_the_follow_up_date_is_a_central_date(bd_db, today_set):
    """Late evening Central on day X is already day X+1 in UTC: the due date counts from X."""
    cid = add_contact(bd_db, category="maintenance")
    bd_db.execute("insert into interactions (contact_id, kind, occurred_at, provider)"
               " values (%s, 'email', '2026-07-08T03:30:00Z', 'manual')", (cid,))   # Jul 7, 22:30 Central
    r = row(bd_db, cid)
    assert r["maintenance_due_date"] == dt.date(2026, 7, 7) + dt.timedelta(days=120) == TODAY
    assert r["maintenance_due"] is True


def test_a_bd_contact_is_never_maintenance_due(bd_db, today_set):
    cid = add_contact(bd_db)
    r = row(bd_db, cid)
    assert (r["maintenance_due"], r["maintenance_due_date"]) == (False, None)
    add_interaction(bd_db, cid, "call", ago(400))
    r = row(bd_db, cid)
    assert (r["maintenance_due"], r["maintenance_due_date"]) == (False, None)
    assert r["last_followup_at"] is not None


def test_a_category_change_moves_the_due_rule_with_it(bd_db, today_set):
    cid = add_contact(bd_db)
    add_interaction(bd_db, cid, "call", ago(300))
    bd_db.execute("update contacts set category = 'maintenance' where id = %s", (cid,))
    r = row(bd_db, cid)
    assert (r["maintenance_due"], r["cadence"]) == (True, None)


# ── the fixture seed ──────────────────────────────────────────────────────────────────────────
def test_the_seeds_override_and_maintenance_contacts(bd_seeded, bd_db):
    """Today is 2026-11-04 and no bd_cadence is stored, so the global cadence is quarterly.
    Lena (27) is on a monthly override until Dec 31; Rory (22) follows the global one. Hal (30) was
    last followed up by the answered call of Aug 20 (10:00 CDT): due Aug 20 + 120 = Dec 18. Nora (31)
    has never been followed up, so she is due now."""
    got = {r["id"]: r for r in bd_db.execute("select * from contacts_summary where id in (22, 27, 30, 31)")}
    assert (got[27]["cadence"], got[27]["cadence_source"], got[27]["frequency_per_year"]) == ("monthly", "override", 12)
    assert got[27]["cadence_override_until"] == dt.date(2026, 12, 31)
    assert (got[22]["cadence"], got[22]["cadence_source"], got[22]["frequency_per_year"]) == ("quarterly", "global", 4)
    assert (got[30]["cadence"], got[30]["frequency_per_year"]) == (None, 3)
    assert (got[30]["maintenance_due"], got[30]["maintenance_due_date"]) == (False, dt.date(2026, 12, 18))
    assert (got[31]["maintenance_due"], got[31]["maintenance_due_date"], got[31]["frequency_per_year"]) == (True, None, 2)
    assert (got[22]["maintenance_due"], got[22]["maintenance_due_date"]) == (False, None)


def test_the_seeds_override_lapses_the_day_after_its_last_day(bd_seeded, bd_db, bd_today):
    def lena():
        return bd_db.execute("select cadence, cadence_source, frequency_per_year, cadence_override"
                             " from contacts_summary where id = 27").fetchone()

    bd_today("2026-12-31")
    assert lena() == {"cadence": "monthly", "cadence_source": "override", "frequency_per_year": 12,
                      "cadence_override": "monthly"}
    bd_today("2027-01-01")
    assert lena() == {"cadence": "quarterly", "cadence_source": "global", "frequency_per_year": 4,
                      "cadence_override": "monthly"}
    bd_today("2026-12-18")
    assert bd_db.execute("select maintenance_due from contacts_summary where id = 30").fetchone()["maintenance_due"] is True
