"""Logging interactions and what follows from them: the one place that knows the rules, so the
interactions router, the week router, the importer and (Phase 4) the telephony webhook all do the
same thing (docs/bd/api-contract.md "Interactions"). Ported from BD's interactions_service.py (#807)
with package-relative imports; the rules are unchanged.

    from bd import interactions_service
    with db.connect() as conn:
        out = interactions_service.log_interaction(conn, contact_id, user, kind="call",
                                                   outcome="answered", occurred_at=ts)
        out["interaction"]      # the interactions row id ... see LoggedInteraction
        recompute_contact(conn, contact_id)   # the contacts_summary row after the change

What "recompute" means here
    The contact's derived fields (last_live_at, last_attempt_at, attempts_since_live,
    touches_this_year, next_due_date, cadence_status) are NOT stored: the contacts_summary view
    derives them from the interactions on every read, and interactions.counts_as_touch is a
    generated column (THE COUNTING RULE). So after an insert, update or delete in the same
    transaction, recompute_contact() simply reads the view again: nothing can go stale, and no
    caller can forget a step. What IS stored and changes on a log is done here, in the caller's
    transaction:
      * a touch on or after promised_date clears it; one on or after next_step_date clears
        next_step and next_step_date (the mock does both);
      * a call (any outcome), voicemail, meeting or hosted event closes the company's row on this
        week's lists (#828): every open new/followup task this week of anyone at the contact's
        company is marked done, so a second call to someone else there the same week moves nothing
        (company_facts.ROW_CLOSE_KINDS; a note, email or text never does: they are not touches);
      * a call, voicemail, meeting, hosted event, email or text closes the contact's open
        MAINTENANCE tasks on this week's list OR A LATER WEEK'S (the Friday build already made
        next week's) once that leaves the contact no longer due (settle_maintenance_tasks): the
        contract's "stays on the list until you log a call, meeting, email or text", and a pinned
        task never outlives the due state it is pinned for. A backdated or future-dated entry
        that leaves the contact still due closes nothing;
      * the same kinds get a pending fallback Recommendation (fallback_next_action).

Every date rule is Central (bizdate); "today" is bizdate.today_central(), which honours BD_TODAY.

"The mock" and "api.js X" below are BD's retired Phase 1 mock (frontend/js/api.js in the BD
repository), named only to trace a rule back; docs/bd/api-contract.md is the spec.
"""
from __future__ import annotations

import datetime as _dt
import re

from . import bizdate, company_facts, serialize
from .events import actor_id

KINDS = ("call", "voicemail", "meeting", "email", "sms", "note", "hosted")
CALL_OUTCOMES = ("answered", "no_answer", "meeting_set")
DIRECTIONS = ("in", "out")
NO_DIRECTION_KINDS = ("meeting", "hosted", "note")
# The work of a weekly task: these get a suggested next step, and close the company's row
# (company_facts.ROW_CLOSE_KINDS is the one place that says which close it).
TASK_KINDS = ("call", "voicemail", "meeting", "hosted")
# A maintenance task closes on any logged follow-up: everything but a note (api.js closesTask).
MAINTENANCE_CLOSE_KINDS = tuple(k for k in KINDS if k != "note")
MISSED_KINDS = ("voicemail",)

SUMMARY_MAX = 20000
TRANSCRIPT_MAX = 200000


class InteractionInputError(ValueError):
    """A bad kind/outcome. `message` and `fields` are the 400's words (the mock's)."""

    def __init__(self, message: str, fields: dict):
        super().__init__(message)
        self.message = message
        self.fields = fields


# ── the counting rule and kinds ──────────────────────────────────────────────────────────────
def is_touch(kind, outcome) -> bool:
    """THE ONE COUNTING RULE. The database computes counts_as_touch itself (a generated column);
    this mirror is for code that has not stored the row yet."""
    if kind in ("meeting", "hosted"):
        return True
    return kind == "call" and outcome in ("answered", "meeting_set")


def is_missed(kind, outcome) -> bool:
    """A voicemail or a no-answer call: the "Send follow-up" card's attempts, and a company's misses
    (#828: company_facts.is_miss is the one rule)."""
    return company_facts.is_miss(kind, outcome)


def normalize_kind(kind, outcome):
    """(kind, outcome) as stored. A call with outcome voicemail IS a voicemail; a non-call kind
    has no outcome. InteractionInputError for an unknown kind or a call without a valid outcome."""
    if kind not in KINDS:
        raise InteractionInputError("Pick what happened.",
                                    {"kind": "Use call, voicemail, meeting, email, sms, note or hosted."})
    if kind == "call" and outcome == "voicemail":
        return "voicemail", "voicemail"
    if kind == "voicemail":
        return "voicemail", "voicemail"
    if kind == "call":
        if outcome not in CALL_OUTCOMES:
            raise InteractionInputError("Pick how the call went.",
                                        {"outcome": "Answered, no answer, voicemail or meeting set."})
        return "call", outcome
    return kind, None


# ── the fallback next step (BDCore.fallbackNextAction, frontend/bd/js/bd-core.js) ─────────────────
LIVE_FOLLOWUP_DAYS = 105
RETRY_DAYS = 7
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december")
_MONTHS_SHORT = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_WEEKDAYS_SHORT = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")      # date.weekday() order
_NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                 "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "couple": 2}
# re.ASCII: \b means what it means in JavaScript (ASCII word characters).
_IN_N = re.compile(r"\bin (?:about |around )?([0-9]{1,2}|a couple of|a couple|an|a|one|two|three|four|five"
                   r"|six|seven|eight|nine|ten|eleven|twelve) (day|week|month)s?\b", re.ASCII)
_AFTER_MONTH = re.compile(r"\bafter (" + "|".join(_MONTHS) + r")\b", re.ASCII)
_NEXT_MONTH = re.compile(r"\bnext month\b", re.ASCII)
_NEXT_WEEK = re.compile(r"\bnext week\b", re.ASCII)


def short_date(d) -> str:
    """2026-11-06 -> "Fri, Nov 6" (BDCore.shortDate)."""
    d = bizdate.parse_date(d)
    return "%s, %s %d" % (_WEEKDAYS_SHORT[d.weekday()], _MONTHS_SHORT[d.month - 1], d.day)


def parse_asked_date(text, today):
    """A date the customer asked for in free text, as {"due_date": date, "phrase": str}, or None.
    The same patterns, in the same order, as BDCore.parseAskedDate."""
    said = re.sub(r"\s+", " ", str(text or ""))
    t = said.lower()
    if not t:
        return None
    today = bizdate.parse_date(today)
    m = _IN_N.search(t)
    if m:
        word = re.sub(r" of$", "", m.group(1))
        word = "couple" if word == "a couple" else word
        n = int(word) if word.isdigit() else _NUMBER_WORDS.get(word, 0)
        if n > 0:
            unit = m.group(2)
            if unit == "day":
                due = bizdate.add_days(today, n)
            elif unit == "week":
                due = bizdate.add_days(today, 7 * n)
            else:
                due = bizdate.add_months(today, n)
            return {"due_date": due, "phrase": said[m.start():m.start() + len(m.group(0))]}
    m = _AFTER_MONTH.search(t)
    if m:
        mi = _MONTHS.index(m.group(1))
        y = today.year
        if mi < today.month - 1:             # "after March" said in November = next March
            y += 1
        nxt = mi + 1
        if nxt > 11:
            nxt, y = 0, y + 1
        return {"due_date": _dt.date(y, nxt + 1, 1), "phrase": said[m.start():m.start() + len(m.group(0))]}
    if _NEXT_MONTH.search(t):
        return {"due_date": bizdate.add_months(today, 1), "phrase": "next month"}
    if _NEXT_WEEK.search(t):
        return {"due_date": bizdate.add_days(today, 7), "phrase": "next week"}
    return None


def fallback_next_action(outcome, text, today) -> dict:
    """The rule-based next step after an interaction: {action, due_date (date), reason, source}.
    `outcome` is the call outcome (answered | meeting_set | voicemail | no_answer) or the kind for
    a meeting/hosted event. A date the customer asked for in `text` wins over the outcome rule."""
    today = bizdate.parse_date(today)
    asked = parse_asked_date(text, today)
    if asked:
        return {"action": "Call back on the date they asked for", "due_date": asked["due_date"],
                "reason": "They said “%s”. Call on %s." % (asked["phrase"], short_date(asked["due_date"])),
                "source": "fallback"}
    if outcome in ("answered", "meeting_set", "meeting", "hosted"):
        lead = {"meeting_set": "Meeting set.", "answered": "Good live call."}.get(outcome, "Met in person.")
        return {"action": "Check in again in about 3–4 months",
                "due_date": bizdate.add_days(today, LIVE_FOLLOWUP_DAYS),
                "reason": lead + " Check in again in about 3–4 months.", "source": "fallback"}
    return {"action": "Try again next week", "due_date": bizdate.add_days(today, RETRY_DAYS),
            "reason": ("Voicemail." if outcome == "voicemail" else "No answer.") + " Try again in a week.",
            "source": "fallback"}


# ── the steps, each usable on its own ────────────────────────────────────────────────────────
def recompute_contact(conn, contact_id):
    """The contact's contacts_summary row as it is now in this transaction (None if missing).
    The derived fields are computed by the view, so this is all a "recompute" needs."""
    return conn.execute(serialize.CONTACT_SELECT + " where cs.id = %s", (contact_id,)).fetchone()


def apply_touch(conn, contact_id, occurred_at) -> None:
    """A touch on or after the contact's promised_date clears it; one on or after next_step_date
    clears next_step and next_step_date (both are met by that talk). Central dates."""
    day = bizdate.biz_date(occurred_at)
    conn.execute(
        "update contacts set promised_date = null"
        " where id = %s and promised_date is not null and promised_date <= %s",
        (contact_id, day))
    conn.execute(
        "update contacts set next_step = null, next_step_date = null"
        " where id = %s and next_step_date is not null and next_step_date <= %s",
        (contact_id, day))


def current_task(conn, contact_id, today=None):
    """This week's (Monday-Sunday, Central) task for the contact: the latest one, from the latest
    batch of the week, whatever its status, or None (api.js currentTask)."""
    ws = bizdate.week_start(today or bizdate.today_central())
    return conn.execute(
        "select t.* from tasks t join task_batches b on b.id = t.batch_id"
        " where t.contact_id = %s and b.week_start = %s"
        " order by b.id desc, t.id desc limit 1", (contact_id, ws)).fetchone()


def closes_task(task_kind, interaction_kind) -> bool:
    """Whether logging an interaction of `interaction_kind` closes a task of `task_kind`: a
    maintenance task on anything but a note, a new/followup task (a company's row) on
    company_facts.ROW_CLOSE_KINDS."""
    if task_kind == "maintenance":
        return interaction_kind in MAINTENANCE_CLOSE_KINDS
    return interaction_kind in company_facts.ROW_CLOSE_KINDS


def close_current_task(conn, contact_id, done_at, kind, today=None):
    """Close the company's row (#828): mark done every OPEN new/followup task on this week's lists
    (any batch, any owner) of anyone at the contact's company, when an interaction of `kind` closes
    it (closes_task). Returns the contact's own closed task (the latest: from the latest batch, as
    current_task picks), else the first one closed, or None when nothing was open: a second call to
    someone else there the same week closes nothing more. A maintenance task is not closed here but by settle_maintenance_tasks: it leaves
    the list when the contact stops being due, not merely because something was logged."""
    if not closes_task("followup", kind):
        return None
    ws = bizdate.week_start(today or bizdate.today_central())
    rows = conn.execute(
        "update tasks t set status = 'done', done_at = %(at)s from task_batches b, contacts c"
        " where b.id = t.batch_id and c.id = t.contact_id and b.week_start = %(ws)s and t.status = 'open'"
        " and t.kind <> 'maintenance'"
        " and c.company_id = (select company_id from contacts where id = %(cid)s) returning t.*",
        {"at": done_at, "ws": ws, "cid": contact_id}).fetchall()
    if not rows:
        return None
    own = [r for r in rows if r["contact_id"] == contact_id]
    if own:
        return max(own, key=lambda r: (r["batch_id"], r["id"]))
    return min(rows, key=lambda r: r["id"])


def settle_maintenance_tasks(conn, contact_id, done_at, kind, today=None) -> list:
    """Close the contact's open maintenance tasks on this week's list and on any LATER week's list
    (the Friday build makes next week's on Friday, so a follow-up logged that evening or on the
    weekend must reach it) when an interaction of `kind` can clear a follow-up (MAINTENANCE_CLOSE_KINDS)
    AND the contact is no longer maintenance_due afterwards. A backdated or future-dated entry that
    leaves the contact due closes nothing (the pin stays, as the due state says). Any owner's list:
    one contact has one pin. Returns the closed tasks rows, earliest week first (this week's before a later week's), then task id."""
    if kind not in MAINTENANCE_CLOSE_KINDS:
        return []
    ws = bizdate.week_start(today or bizdate.today_central())
    due = conn.execute("select maintenance_due from contacts_summary where id = %s", (contact_id,)).fetchone()
    if due is None or due["maintenance_due"]:
        return []
    rows = conn.execute(
        "update tasks t set status = 'done', done_at = %s from task_batches b"
        " where b.id = t.batch_id and t.contact_id = %s and t.kind = 'maintenance' and t.status = 'open'"
        " and b.week_start >= %s returning t.*, b.week_start as list_week", (done_at, contact_id, ws)).fetchall()
    rows = sorted(rows, key=lambda r: (r.pop("list_week"), r["id"]))
    return rows


def first_name(name) -> str:
    parts = str(name or "").split()
    return parts[0] if parts else ""


def make_recommendation(conn, contact_row, interaction_row, created_at=None, today=None):
    """A pending fallback Recommendation for this interaction (api.js makeRecommendation). Returns
    the RECOMMENDATION_SELECT row."""
    today = today or bizdate.today_central()
    f = fallback_next_action(interaction_row["outcome"] or interaction_row["kind"],
                             interaction_row.get("summary"), today)
    first = first_name(contact_row["name"])
    action = ("Try %s again" % first) if f["action"] == "Try again next week" and first else f["action"]
    created_at = created_at or bizdate.now_central()
    rid = conn.execute(
        "insert into ai_recommendations (contact_id, interaction_id, action, due_date, reason, source,"
        " status, created_at) values (%s, %s, %s, %s, %s, 'fallback', 'pending', %s) returning id",
        (contact_row["id"], interaction_row["id"], action, f["due_date"], f["reason"], created_at)).fetchone()["id"]
    return conn.execute(serialize.RECOMMENDATION_SELECT + " where r.id = %s", (rid,)).fetchone()


def fetch_interaction_row(conn, interaction_id):
    return conn.execute(serialize.INTERACTION_SELECT + " where i.id = %s", (interaction_id,)).fetchone()


def log_interaction(conn, contact_id, actor, *, kind, outcome=None, occurred_at=None, direction=None,
                    duration_s=None, summary="", transcript=None, recording_url=None,
                    provider="manual", external_id=None, close_task=True, recommend=True, now=None):
    """Insert one interaction and do everything that follows from it, in the caller's transaction.

    `kind`/`outcome` go through normalize_kind (InteractionInputError on bad input). `occurred_at`
    defaults to now (Central). `direction` defaults to "out", and is forced to None for a meeting,
    hosted event or note. The caller has already checked who may log it and that the contact
    exists (lock it first with `select ... for update` if it matters).

    Returns {"interaction": INTERACTION_SELECT row, "contact": contacts_summary row,
             "task": tasks row | None, "recommendation": RECOMMENDATION_SELECT row | None,
             "missed_call": bool}.
    """
    kind, outcome = normalize_kind(kind, outcome)
    now = now or bizdate.now_central().replace(microsecond=0)
    at = bizdate.parse_ts(occurred_at) if occurred_at is not None else now
    direction = direction_for(kind, direction)
    iid = conn.execute(
        "insert into interactions (contact_id, kind, direction, outcome, occurred_at, duration_s, summary,"
        " transcript, recording_url, provider, external_id, user_id)"
        " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id",
        (contact_id, kind, direction, outcome, at, duration_s, summary, transcript, recording_url,
         provider, external_id, actor_id(actor))).fetchone()["id"]
    if is_touch(kind, outcome):
        apply_touch(conn, contact_id, at)
    task = close_current_task(conn, contact_id, at, kind) if close_task else None
    # Housekeeping, whatever close_task says (the admin's attach passes False): a maintenance task
    # never outlives the follow-up that cleared it. `task` shows it only when the caller asked to close.
    settled = settle_maintenance_tasks(conn, contact_id, at, kind)
    if task is None and close_task and settled:
        task = settled[0]
    irow = fetch_interaction_row(conn, iid)
    crow = recompute_contact(conn, contact_id)
    rec = make_recommendation(conn, crow, irow, created_at=now) if recommend and kind in TASK_KINDS else None
    return {"interaction": irow, "contact": crow, "task": task, "recommendation": rec,
            "missed_call": is_missed(kind, outcome)}


def direction_for(kind, direction):
    """The stored direction: None for a meeting, hosted event or note (the contract's rule), else
    the given one, "out" when there is none."""
    return None if kind in NO_DIRECTION_KINDS else (direction or "out")


def update_interaction(conn, row, changes: dict):
    """Apply already-validated `changes` (any of kind, outcome, summary, occurred_at, duration_s,
    transcript) to the interactions row `row`. kind/outcome are normalised together. Returns the
    fresh INTERACTION_SELECT row; the contact's derived fields follow through the view.

    Two rules log_interaction applies hold here too:
      * a kind change sets the direction the contract allows for the new kind (null for a
        meeting, hosted event or note; the old one, else "out", otherwise). Review finding C2.
      * when the edit makes the row a touch, or moves a touch to another time, that touch meets
        the contact's promised_date / next step on or before its Central date (apply_touch), as
        a newly logged touch does. Review finding C1.
    """
    sets, params = [], []
    kind, outcome = row["kind"], row["outcome"]
    if "kind" in changes or "outcome" in changes:
        cur_kind = row["kind"]
        new_kind = changes.get("kind") or ("call" if cur_kind == "voicemail" and changes.get("outcome") else cur_kind)
        new_outcome = changes["outcome"] if "outcome" in changes else row["outcome"]
        kind, outcome = normalize_kind(new_kind, new_outcome)
        sets += ["kind = %s", "outcome = %s", "direction = %s"]
        params += [kind, outcome, direction_for(kind, row.get("direction"))]
    for col in ("summary", "occurred_at", "duration_s", "transcript"):
        if col in changes:
            sets.append(col + " = %s")
            params.append(changes[col])
    if sets:
        conn.execute("update interactions set " + ", ".join(sets) + " where id = %s", params + [row["id"]])
    was_touch = is_touch(row["kind"], row["outcome"])
    moved = "occurred_at" in changes and changes["occurred_at"] != row["occurred_at"]
    if is_touch(kind, outcome) and (not was_touch or moved):
        apply_touch(conn, row["contact_id"], changes.get("occurred_at") or row["occurred_at"])
    # An edit can make this row the follow-up that clears a due maintenance contact (a note turned
    # into an email): its pinned task goes with it, as a newly logged one would.
    settle_maintenance_tasks(conn, row["contact_id"], bizdate.now_central().replace(microsecond=0), kind)
    return fetch_interaction_row(conn, row["id"])


def delete_interaction(conn, interaction_id) -> bool:
    """Delete one interaction (recommendations, drafts and phone events that pointed at it keep
    their rows with the link set to null, by the schema's foreign keys)."""
    return conn.execute("delete from interactions where id = %s returning id",
                        (interaction_id,)).fetchone() is not None


# ── the contact timeline ─────────────────────────────────────────────────────────────────────
def timeline(conn, contact_row) -> list:
    """GET /api/bd/contacts/{id}/interactions items, newest first (api.js timeline): every
    interaction, every event row for the contact, and for a workbook contact with no logged
    "created" event, a synthetic "created ... Imported from the workbook" event at its created_at
    by whoever ran the latest import. Ties keep that order (interactions, events, created)."""
    cid = contact_row["id"]
    items = []
    for r in conn.execute(serialize.INTERACTION_SELECT + " where i.contact_id = %s order by i.id", (cid,)):
        items.append((r["occurred_at"], {"type": "interaction", "at": serialize.ts(r["occurred_at"]),
                                         "interaction": serialize.interaction(r)}))
    has_created = False
    for e in conn.execute(
            "select e.id, e.kind, e.at, e.detail, e.actor_id, u.name as actor_name"
            " from events e left join users u on u.id = e.actor_id"
            " where e.contact_id = %s order by e.id", (cid,)):
        has_created = has_created or e["kind"] == "created"
        by = serialize.user_ref(e["actor_id"], e["actor_name"]) if e["actor_id"] is not None else None
        items.append((e["at"], {"type": "event", "at": serialize.ts(e["at"]),
                                "event": {"action": e["kind"], "by": by, "detail": e["detail"]}}))
    if contact_row["source"] == "workbook" and contact_row.get("created_at") is not None and not has_created:
        imp = conn.execute(
            "select im.by_id, u.name as by_name from imports im left join users u on u.id = im.by_id"
            " order by im.id desc limit 1").fetchone()
        by = serialize.user_ref(imp["by_id"], imp["by_name"]) if imp and imp["by_id"] is not None else None
        items.append((contact_row["created_at"], {
            "type": "event", "at": serialize.ts(contact_row["created_at"]),
            "event": {"action": "created", "by": by, "detail": "Imported from the workbook"}}))
    # A stable sort on the moment, newest first (Python's sort is stable, as JavaScript's is).
    items.sort(key=lambda pair: pair[0].timestamp(), reverse=True)
    return [it for _, it in items]
