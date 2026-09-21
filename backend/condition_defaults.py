"""Takeoff conditions — what a new estimate opens ANSWERED, as an edited row instead of a constant.

WHAT THIS IS FOR. The Polish beta's Takeoff step carries three Yes/No questions — joint filler,
remove existing joint filler, and dye. Their answers are not priced by the beta engine; each one
writes a Yes/No literal into a cell of Kyle's workbook (Polish!E29, Polish!F29, Polish!E25) and
Kyle's own formulas do the rest. Which answer a BRAND NEW bid opens holding is today a literal
inside `freshModel()` in frontend/js/polish-bid-core.js, and the Library page's Defaults tab
listed all three with a "Built in" chip beside them. Hanz, twice: "I told you to remove the
built-in and keep and make everything editable in the takeoff." This table is where that answer
is edited instead.

AN OVERRIDE, NOT THE ANSWER ITSELF. A row here says "the shipped default for this one key is
wrong for us". No row means the shipped literal stands. That is deliberate and it is the reason
this module does NOT carry its own copy of "joint filler ships on": that fact lives once, in
`freshModel()`, and a second statement of it in Python is a thing that drifts the first time
somebody changes one and not the other — exactly what the note above `travelSeed` records
happening within a day. So the API answers with the rows an admin has SET, and the page merges
them over the one place the shipped answer lives.

A CLOSED VOCABULARY, ENFORCED HERE. `KEYS` is the three takeoff conditions and nothing else.
This is markup.py's posture for `layout`, and for the same measured reason: a condition filed
under a name nothing looks up is not stored-but-unused, it is a row that saves with a green tick
and changes nothing at all. The five conditions answered on the Intake step (local, hard bid,
prevailing wage, taxable, remodel tax) are deliberately NOT here — they are answered per job from
the lead notes and by the AI autofill, so "what they open as" is not a setting anybody sets; the
estimator is told the answer by the job. Adding one later is this tuple plus a row on the page.

WHAT IS NOT EDITABLE, AND WHY IT IS NOT A HARDCODED LINE ITEM. The workbook CELL each condition
writes to. Polish!E29 is a fact about the file Kyle maintains, not a preference — pointing the
joint-filler answer at a different cell would put a Yes/No literal over one of his formulas, and
nothing on either screen would say so. The answer is the editable thing; where it lands is not.

DELIBERATELY NO SOFT DELETE, unlike every other table this project owns. Everywhere else
`deleted_at` protects something that cannot be retyped: a hand-entered price, a markup formula, a
calendar event. A row here is ONE BOOLEAN standing in front of a constant that is still in the
source — putting it back is one click on the same switch, and there is nothing to recover. So the
unique index is plain rather than partial, and an upsert writes the one live row for that key.

DDL LANDS ON TWO DATABASES OR IT IS BROKEN. Production is cloud Supabase; staging is a separate
Postgres behind PostgREST. `condition_defaults` is declared in backend/supabase_schema.sql and
backend/staging/schema_pg.sql and, as of this commit, is APPLIED TO NEITHER — it needs Hanz's go.
Until it exists, `list_defaults()` answers with an empty list on purpose (see its docstring) and
every estimate opens exactly as it does today.
"""
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from supabase_client import get_client

log = logging.getLogger(__name__)

TABLE = "condition_defaults"

# The three conditions the Takeoff step carries, in the order that step asks them. These are the
# keys of `CONDITION_CELLS` in frontend/js/polish-bid-core.js — the mapping that decides which
# workbook cell each answer writes — and test_condition_defaults.py reads that file and pins the
# two lists together, so a key renamed on one side cannot quietly stop being written on the other.
KEYS = ("joint_filler", "remove_existing_jf", "dye")

_MAX_KEY = 64


class ValidationError(ValueError):
    """A refusal a person can act on. main.py turns it into a 400 carrying the message."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any, limit: int = 200) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _actor(email: Optional[str]) -> Optional[str]:
    text = _clean_text(email, 320)
    return text or None


_TRUE_WORDS = {"true", "yes", "y", "on", "1"}
_FALSE_WORDS = {"false", "no", "n", "off", "0"}


def _boolean(raw: Any, *, field: str) -> bool:
    """A real boolean, and never `bool(raw)`.

    `bool("false")` is True, and the string "false" is the ordinary shape of a checkbox arriving
    from a form — read as True it would switch joint filler back on for every new bid. This is
    markup.py's `_boolean` with the same reasoning; anything unrecognised is refused rather than
    guessed, because the wrong guess is the expensive direction."""
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    text = str(raw or "").strip().casefold()
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    raise ValidationError("%s has to be yes or no, not \"%s\"." % (field, _clean_text(raw, 40)))


def check_key(value: Any) -> str:
    """One of the three takeoff conditions, or a refusal that names them.

    Refused BY NAME rather than stored, the same call `_check_layout` makes: a condition filed
    under a key no reader knows is read by nothing, so it would save successfully and change
    nothing an estimator ever sees."""
    text = _clean_text(value, _MAX_KEY)
    if not text:
        raise ValidationError("Say which condition this is (%s)." % ", ".join(KEYS))
    if text not in KEYS:
        raise ValidationError(
            "\"%s\" isn't a takeoff condition. Use one of: %s." % (text, ", ".join(KEYS)))
    return text


def _shape(row: Dict[str, Any]) -> Dict[str, Any]:
    """One row as JSON. `on` is read from the column and never inferred from anything else."""
    try:
        on = _boolean(row.get("on_by_default"), field="Default answer")
    except ValidationError:
        # A hand-edited row holding junk must not 500 a read that the ESTIMATE page makes mid-bid.
        # False is the conservative direction for all three: two of them ship off, and the one
        # that ships on is restored by the page's own fallback when this row is absent — which is
        # what a caller does with a value it cannot trust either way.
        log.warning("condition_defaults row %s has an unreadable on_by_default; reading it as no",
                    row.get("id"))
        on = False
    return {
        "id": row.get("id"),
        "key": row.get("condition_key") or "",
        "on": on,
        "owner_email": row.get("owner_email") or "",
        "updated_by": row.get("updated_by") or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def list_defaults() -> List[Dict[str, Any]]:
    """Every condition an admin has set an answer for. NEVER RAISES.

    A missing `condition_defaults` reads as "nobody has overridden anything", which is the honest
    answer on both databases until Hanz applies the DDL — and the only safe one, because there are
    TWO readers and one of them is the estimate. `list_labor()` makes this call for the Library
    page alone; here a raise would stop an estimator mid-bid over a list that is legitimately
    empty, which is a strictly worse outcome than a bid that opens with the shipped answers.

    Deliberately broad on the exception: an absent table reaches Python as an ordinary PostgREST
    APIError (PGRST205) and an unconfigured store as something else again, and the caller can do
    nothing useful with either — both mean the same thing to the page.

    OFF-VOCABULARY ROWS ARE DROPPED, not served. A row whose key is not one of KEYS reaches no
    reader anyway; serving it would put a switch on the Defaults tab for a condition that writes
    to no cell."""
    try:
        sb = get_client()
        res = sb.table(TABLE).select("*").limit(50).execute()
        rows = [_shape(r) for r in (res.data or [])]
    except Exception as exc:  # noqa: BLE001
        log.warning("condition_defaults unreadable (table not applied yet?): %s", exc)
        return []
    order = {k: i for i, k in enumerate(KEYS)}
    return sorted([r for r in rows if r["key"] in order], key=lambda r: order[r["key"]])


def get_default(key: str) -> Optional[Dict[str, Any]]:
    sb = get_client()
    res = sb.table(TABLE).select("*").eq("condition_key", key).limit(1).execute()
    rows = res.data or []
    return _shape(rows[0]) if rows else None


def set_default(key: Any, payload: Dict[str, Any],
                actor_email: Optional[str]) -> Dict[str, Any]:
    """Set what a new estimate opens answering for one condition. One live row per key.

    FAILS LOUDLY when the table is missing, and the asymmetry with `list_defaults` is the point of
    both. A read of a table that is not there is honestly empty; a WRITE that quietly does nothing
    tells an admin they changed what every new bid opens with when they changed nothing, and they
    find out from a bid. `create_labor` takes the same pair of positions for the same reason.

    LOOKUP-THEN-WRITE rather than a PostgREST upsert, following `_clashing_vendor` and
    `upsert_rule`: the comparison happens in Python, where the vocabulary check has already run,
    instead of trusting a filter built out of a caller's text."""
    if not isinstance(payload, dict):
        raise ValidationError("Nothing to save.")
    condition_key = check_key(key)
    on = _boolean(payload.get("on"), field="Default answer")

    sb = get_client()
    cur = sb.table(TABLE).select("id").eq("condition_key", condition_key).limit(1).execute()
    rows = cur.data or []
    now = _now_iso()
    if rows:
        sb.table(TABLE).update({
            "on_by_default": on,
            "updated_by": _actor(actor_email),
            "updated_at": now,
        }).eq("id", rows[0]["id"]).execute()
    else:
        sb.table(TABLE).insert({
            "id": str(uuid.uuid4()),
            "condition_key": condition_key,
            "on_by_default": on,
            "owner_email": _actor(actor_email),
            "updated_by": _actor(actor_email),
            "created_at": now,
            "updated_at": now,
        }).execute()
    # Read back rather than answering with the dict just written, the same call `create_labor`
    # makes: the store is what decides what was stored, and a reply that agreed with itself rather
    # than with the table would show an answer that changes on the next reload.
    stored = get_default(condition_key)
    if stored is not None:
        return stored
    return {"id": None, "key": condition_key, "on": on, "owner_email": _actor(actor_email) or "",
            "updated_by": _actor(actor_email) or "", "created_at": now, "updated_at": now}
