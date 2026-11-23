"""What is true of a whole company (a BD account) for the weekly list: #828's company rules, each in ONE
place, so a different answer from Hanz is a small change here and nowhere else.

#828 made the Weekly 10 a list of companies: one slot per company a week, misses counted for the
company, the 3-day rest kept by the company, one row per company on This Week. A person's own facts
are still their contacts_summary row; this module adds the company's:

    load(conn, company_ids) -> {company_id: Facts}    ONE query, as of the session's bd_today()
    Facts = {"last_live_at", "last_attempt_at", "misses"}

over EVERY person at the company who is not archived, whoever owns them and whichever tab they are on
(BD or maintenance), dated on or before today (Central): the people #810's Contacts page counts for an
account's last live talk (LIVE_AT_COMPANY is that query; bd/routers/accounts.py lists the accounts
with it).

HANZ'S ANSWERS TO #828'S OPEN POINTS (2026-11-23), one name each:

  1. MISS_OUTCOMES          a miss is a call that reached nobody: a voicemail, or a call nobody
     (MISS_SQL, is_miss())  answered (outcome no_answer). It counts for the company, whoever was
                            called, by its Central date, since the last live talk with anyone there
                            (a live talk with anyone there sets it back to 0). MISS_SQL and is_miss()
                            are built from MISS_OUTCOMES; voicemails only would be
                            {"voicemail": ("voicemail",)}. The contact page's "Send follow-up" card
                            (routers/contacts.py _missed_call) reads MISS_SQL too. One separate
                            encoding must change with it: a person's own attempts_since_live in
                            contacts_summary (migration 004: calls and voicemails that are not
                            counts_as_touch), which the row's people show; changing that is a migration.
  2. score_facts()          the parts of the priority score counted for the whole company: the misses
                            (the score's "tries" part: attempts_since_live = the company's misses). The
                            cadence part ("last live talk", "never had a live talk") stays the
                            person's own: their last_live_at is never laid over.
  3. score_facts()          the 3-day rest is the company's: last_attempt_at = the latest try (TRY_SQL)
                            with anyone there, so a company where anyone was tried in the last 3 days
                            is left out of a new list and out of Give Me 10 More.
     (2 and 3 are for the BD picks only: a due maintenance person keeps their own facts, as before
     #828, until the maintenance ticket makes that cycle the company's.)
  4. ROW_CLOSE_KINDS        a company's row on the list closes when a call (any outcome), a
                            voicemail, a meeting or a hosted event is logged with anyone there.
     company_kind()         a company is "new" only when nobody there has had a live talk.
     (weekly.rank_companies) a company's place is its best person's score, with 2 and 3 applied.
     reason_words()         and its chip words the misses for the company: a follow-up company's best
                            person who never talked live reads "N tries since the last live talk"
                            (the row's misses line), not "Never reached after N tries".

WORDS. The page and the ticket call misses "tries" ("Never reached after 2 tries", "2 tries since the
last live talk"); this code says misses. TRY_SQL's "try" is any call or voicemail (answered or not),
which is what the 3-day rest counts.

And the row rules This Week and its buttons share:

     row_status(statuses, due)  a row of several tasks (a week built before #828, or after a #810
                            move or a #811 merge, can hold two people at one company). A BD row is done
                            once any task is done (someone there was reached, answer 4), else open
                            while any is open, else snoozed (taken off). A "Due now" row is open while
                            any task is open (the maintenance cycle is still per person).
     NRP_EVENT, flagged(),  "Not the right person" on a row: the event not-right-person logs, and who
     CALLABLE_SQL           was marked on which task; a row stays open while someone else on it can be
                            called: a phone number, and not marked not the right person there.

PURE apart from load(); no clock: bd_today() is the caller's business date.
"""
from __future__ import annotations

from typing import Any

# 1. A miss: a call that reached nobody. {kind: the outcomes of that kind that are a miss}; a
# voicemail's outcome is always "voicemail" (001_schema's check on interactions).
MISS_OUTCOMES = {"voicemail": ("voicemail",), "call": ("no_answer",)}
# MISS_OUTCOMES in SQL, over interactions `i`.
MISS_SQL = "(" + " or ".join(
    "(i.kind = '%s' and i.outcome in (%s))" % (k, ", ".join("'%s'" % o for o in outs))
    for k, outs in MISS_OUTCOMES.items()) + ")"
# A try, for the 3-day rest: a call (any outcome) or a voicemail (contacts_summary.last_attempt_at's rule).
TRY_SQL = "i.kind in ('call', 'voicemail')"
# 4. What closes a company's row (a person's new or follow-up task closed on the same kinds before #828).
ROW_CLOSE_KINDS = ("call", "voicemail", "meeting", "hosted")

# A live talk BD counts (interactions.counts_as_touch), dated on or before today, with someone at
# company `co` who is not archived (#810's account last_live_at).
LIVE_AT_COMPANY = (
    "select max(i.occurred_at) as last_live_at from contacts c2 join interactions i on i.contact_id = c2.id"
    " where c2.company_id = co.id and c2.archived_at is null and i.counts_as_touch"
    " and bd_date(i.occurred_at) <= bd_today()")

_FACTS_SQL = (
    "select co.id as company_id, live.last_live_at, tries.last_attempt_at, coalesce(tries.misses, 0)::integer as misses"
    " from companies co"
    " left join lateral (" + LIVE_AT_COMPANY + ") live on true"
    " left join lateral ("
    "   select max(i.occurred_at) filter (where " + TRY_SQL + ") as last_attempt_at,"
    "   count(*) filter (where " + MISS_SQL + " and (live.last_live_at is null or i.occurred_at > live.last_live_at))"
    "     as misses"
    "   from contacts c2 join interactions i on i.contact_id = c2.id"
    "   where c2.company_id = co.id and c2.archived_at is null and bd_date(i.occurred_at) <= bd_today()"
    " ) tries on true"
    " where co.id = any(%s)")

EMPTY = {"last_live_at": None, "last_attempt_at": None, "misses": 0}

# Marked "not the right person" on a task: the unconfirmed event not-right-person logs, which carries
# the task id (data->>'task_id', compared as TEXT, so no event's data is ever cast). Over events `e`.
NRP_EVENT = "e.kind = 'unconfirmed' and e.data->>'via' = 'not_right_person'"
# The person `p` (contacts) was marked not the right person on one of %(tasks)s (task ids as text).
NOT_RIGHT_PERSON_SQL = (
    "exists (select 1 from events e where " + NRP_EVENT + " and e.contact_id = p.id"
    " and e.data->>'task_id' = any(%(tasks)s::text[]))")
# Someone on a row who can still be called: a phone number, and not marked not the right person there.
CALLABLE_SQL = "coalesce(btrim(p.phone), '') <> '' and not " + NOT_RIGHT_PERSON_SQL


def load(conn: Any, company_ids: Any) -> dict:
    """{company_id: {"last_live_at", "last_attempt_at", "misses"}} for these companies, as of the
    connection's bd_today(). A company with nobody left, or no interactions, gets EMPTY's values."""
    ids = sorted({int(i) for i in (company_ids or []) if i is not None})
    if not ids:
        return {}
    out = {i: dict(EMPTY) for i in ids}
    for r in conn.execute(_FACTS_SQL, (ids,)).fetchall():
        out[int(r["company_id"])] = {"last_live_at": r["last_live_at"], "last_attempt_at": r["last_attempt_at"],
                                     "misses": int(r["misses"] or 0)}
    return out


def flagged(conn: Any, task_ids: Any) -> set:
    """{(contact_id, task_id)}: who was marked not the right person on which of these tasks."""
    ids = [str(i) for i in (task_ids or [])]
    if not ids:
        return set()
    return {(r["contact_id"], int(r["task_id"])) for r in conn.execute(
        "select e.contact_id, e.data->>'task_id' as task_id from events e where " + NRP_EVENT +
        " and e.data->>'task_id' = any(%s::text[])", (ids,)).fetchall()}


def is_miss(kind: Any, outcome: Any) -> bool:
    """1, for code that has not stored the row: MISS_OUTCOMES in Python."""
    return outcome in MISS_OUTCOMES.get(kind, ())


def score_facts(company: Any, kind: Any = None) -> dict:
    """2 and 3: the facts laid over a person at `company` when they are scored for a list
    (priority.score's `facts`). {} when the company's facts are unknown, or for a due maintenance
    person (`kind` "maintenance"), who keeps their own: the person's own facts are used."""
    if not company or kind == "maintenance":
        return {}
    return {"attempts_since_live": int(company.get("misses") or 0),
            "last_attempt_at": company.get("last_attempt_at")}


def reason_words(reasons: Any, person: Any, company: Any) -> list:
    """4, the chip: `reasons` (priority.score's, scored with score_facts) worded for the company. A
    follow-up company's person who never talked live had the company's misses read as "Never reached
    after N tries"; someone there did talk live, so it reads "N tries since the last live talk", as
    the row's misses line does. Anything else is returned as it is."""
    from .priority import plural

    n = int((company or {}).get("misses") or 0)
    if n <= 0 or company_kind(company) != "followup" or (person or {}).get("last_live_at") is not None:
        return list(reasons or [])
    never = "Never reached after " + plural(n, "try", "tries")
    return [plural(n, "try", "tries") + " since the last live talk" if r == never else r for r in reasons or []]


def company_kind(company: Any) -> str:
    """4: "new" when nobody at the company has had a live talk, else "followup"."""
    return "followup" if company and company.get("last_live_at") is not None else "new"


def row_status(statuses: Any, due: bool = False) -> str:
    """The status of a row of tasks. A BD row (due False): done once any task is done (anyone there
    was reached), else open while any is open, else snoozed. A "Due now" row (due True): open while
    any is open (someone there is still due), else done when any is done, else snoozed."""
    found = set(statuses or ())
    order = ("open", "done") if due else ("done", "open")
    return next((s for s in order if s in found), "snoozed")
