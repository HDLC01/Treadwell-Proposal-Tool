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

  1. MISS_SQL / is_miss()   a miss is a call that reached nobody: a voicemail, or a call nobody
                            answered (outcome no_answer). It counts for the company, whoever was
                            called, by its Central date, since the last live talk with anyone there
                            (a live talk with anyone there sets it back to 0). Voicemails only would
                            be: "i.kind = 'voicemail'" and kind == "voicemail".
  2. score_facts()          the parts of the priority score counted for the whole company: the tries
                            part (attempts_since_live = the company's misses). The cadence part ("last
                            live talk", "never had a live talk") stays the person's own: their
                            last_live_at is never laid over.
  3. score_facts()          the 3-day rest is the company's: last_attempt_at = the latest try with
                            anyone there, so a company where anyone was tried in the last 3 days is
                            left out of a new list and out of Give Me 10 More.
  4. ROW_CLOSE_KINDS        a company's row on the list closes when a call (any outcome), a
                            voicemail, a meeting or a hosted event is logged with anyone there.
     company_kind()         a company is "new" only when nobody there has had a live talk.
     (weekly.rank_companies) a company's place is its best person's score, with 2 and 3 applied.

And the row rules This Week and its buttons share:

     row_status(statuses)   a row of several tasks (a week built before #828 can hold two people at
                            one company) is open while any task is open, else done when any is done,
                            else snoozed (taken off).
     CALLABLE_SQL           "Not the right person" keeps a row open while someone else on it can be
                            called: a person on the row with a phone number who has not been marked
                            not the right person on this row.

PURE apart from load(); no clock: bd_today() is the caller's business date.
"""
from __future__ import annotations

from typing import Any

# 1. A miss: a call that reached nobody.
MISS_SQL = "(i.kind = 'voicemail' or (i.kind = 'call' and i.outcome = 'no_answer'))"
MISS_OUTCOMES = {"voicemail": ("voicemail",), "call": ("no_answer",)}
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

# Marked "not the right person" on one of a row's tasks: the unconfirmed events not-right-person logs
# carry the task id. `p` is the person (contacts); %(tasks)s the row's task ids AS TEXT (compared as
# text, so no event's data is ever cast).
NOT_RIGHT_PERSON_SQL = (
    "exists (select 1 from events e where e.kind = 'unconfirmed' and e.contact_id = p.id"
    " and e.data->>'via' = 'not_right_person' and e.data->>'task_id' = any(%(tasks)s::text[]))")
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


def is_miss(kind: Any, outcome: Any) -> bool:
    """1, for code that has not stored the row: MISS_SQL in Python."""
    return outcome in MISS_OUTCOMES.get(kind, ())


def score_facts(company: Any) -> dict:
    """2 and 3: the facts laid over each of the company's people when they are scored for a list
    (priority.score's `facts`). {} when the company's facts are unknown (the person's own are used)."""
    if not company:
        return {}
    return {"attempts_since_live": int(company.get("misses") or 0),
            "last_attempt_at": company.get("last_attempt_at")}


def company_kind(company: Any) -> str:
    """4: "new" when nobody at the company has had a live talk, else "followup"."""
    return "followup" if company and company.get("last_live_at") is not None else "new"


def row_status(statuses: Any) -> str:
    """The status of a row of tasks: open while any is open, else done when any is done, else snoozed."""
    found = set(statuses or ())
    if "open" in found:
        return "open"
    return "done" if "done" in found else "snoozed"
