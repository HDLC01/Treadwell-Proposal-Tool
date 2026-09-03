"""Markup rules — the markup chain's rates, as editable expressions, per sheet LAYOUT.

WHAT THIS IS FOR. The Polish beta's on-screen price comes out of one choke point,
`markupChain()` in frontend/js/polish-bid-core.js, which walks a chain of markup lines over a
subtotal — gp → hard_bid → contingency → super_pto → soft_costs → remodel_tax → bond — each
line's base being the running sum ABOVE it. It compounds; it does not add. Those rates are
hardcoded constants in that file (`RATES`, `GP_BANDS`, and literals inside `hardBidPct`),
transcribed by hand off Kyle's workbook. This table is where an admin edits them instead.

STORAGE AND API ONLY. Nothing here evaluates a formula — the expression grammar and the engine
that runs it are somebody else's module, and the page is somebody else's too. What this owns is
the row: its identity, what a valid one looks like, and getting it in and out of two different
databases unchanged.

KEYED ON `layout`, NOT ON A WORK TYPE. Audited against estimate_sheet_5.7.xlsx on 2026-09-03:
the markup column keys on the TAB. Seal, Seal (+Jnts), Epoxy blank and Leveling are tabs a bid
can sit on that no work type names, and the differences are real —

    polish              super/PTO 0.027, soft 0.16, 5 GP tiers .52/.45/.35/.32/.30
    seal                the same rates but a SIXTH GP tier, top rate 0.28
    epoxy / leveling    super 0.03, soft 0.13, Polish's 5 tiers
    gyp                 a different species: 7 GP tiers on different edges, super 0.041,
                        NO hard-bid rate at all, and soft costs is an EXPRESSION

Same call the shipped remodel-rate fix made when it moved to layout-keyed targets.

THERE IS DELIBERATELY NO `combo`. A combo job renders as two independent option lines, each
priced off its own tab; the word is a document-composition label and has no markup of its own.
A 'combo' layout is refused by name so nobody stores a rate that could never be read.

TWO CHAIN LINES ARE NOT HERE, EITHER — same posture as `combo`, for a different reason. They stay
IN `CHAIN` (the compounding order is real for both) but are excluded from `LINE_KEYS`, the subset
this table actually stores rows for, and refused by name if asked for:

    contingency     typed per job by the estimator on the bid itself, not a tab-wide rate — there
                    is no "the polish contingency", only whatever a given bid needed
    remodel_tax     already has its own resolution order (a typed percent, then the county table,
                    then the 6.5% floor) with no separate admin formula to race it; the county
                    table is the only thing that moves this rate

Decided 2026-09-03 (AskUserQuestion): both show read-only on the Markup page.

`applies` IS NOT A ZERO. The Gyp tabs have no hard-bid rate — the workbook cell is EMPTY, not 0.
"this line does not exist on this tab" and "this line prices to nothing" are different facts and
the chain treats them differently, so they are stored differently: `applies=false, formula=NULL`
against `applies=true, formula='0'`. Collapsing them is the one mistake this module is shaped to
prevent, and test_markup.py mutates the source both ways to prove the guard is real.

`formula` IS TEXT, NOT A RATE. Gyp's soft-costs cell is a whole expression:

    IF(OR(B5="Yes",B5="No"), IF(B5="Yes",.09,.1) - IF(E69>334900,.05,IF(E69>234450,.035,0)),
       "error")

A numeric `rate` column could not hold that, and the `"error"` string is Kyle's own
refuse-to-price-rather-than-guess behaviour, which is worth keeping verbatim. So the column is
text and this module stores exactly what was typed.

WHAT IS NOT CHECKED HERE, said out loud because a 200 that stores an unparseable formula is a
failure deferred to the moment somebody is pricing a job: this module checks a formula's SHAPE
(non-empty, balanced parentheses, paired double quotes) and nothing about its grammar. When the
engine lands it should expose a `validate(expression)` and `validate_rule` should call it, so a
formula is refused while the admin is still looking at it.

ONE LIVE ROW PER (layout, line_key). Enforced two ways, following local precedent: a partial
unique index in both schema files, and a lookup-then-update here (the way `_clashing_vendor`
compares in Python rather than trusting a PostgREST filter with user text in it).

DELETES ARE SOFT, as in library.py and calendar_events: `deleted_at` non-NULL hides a row. These
are hand-typed pricing rules; a destroyed one could move money on the next bid. A delete does NOT
reserve the key — a later upsert of the same (layout, line_key) writes a NEW row and leaves the
deleted one deleted, so "undelete" never happens by accident as a side effect of saving.
"""
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from supabase_client import get_client

log = logging.getLogger(__name__)

RULES = "markup_rules"

# The five tabs a bid can sit on. CLOSED, unlike library.py's DIVISIONS/ITEM_UNITS — those are
# offered-not-enforced because legacy rows hold whatever somebody typed and refusing them would
# make them uneditable. Nothing legacy exists here, and an off-list layout is unreadable by
# definition: the chain looks its rules up BY layout, so a rule filed under a name no tab has is a
# rule that silently never applies. Refused instead.
LAYOUTS = ("polish", "seal", "epoxy", "leveling", "gyp")

# The chain, in the order it compounds. The order is load-bearing — each line's base is the
# running sum above it — so it is also the default `sort`, and a caller that does not care about
# ordering still gets rows in the order the money is actually applied.
CHAIN = ("gp", "hard_bid", "contingency", "super_pto", "soft_costs", "remodel_tax", "bond")

# The subset of CHAIN an admin can actually file a rule against. `contingency` and `remodel_tax`
# stay in CHAIN (their place in the compounding order is real) but are refused here BY NAME, not
# just left off — see the module docstring for why each one has nowhere to be filed.
_NOT_EDITABLE = {
    "contingency": (
        "Contingency isn't a markup rule — it's typed per job by the estimator, not a tab-wide "
        "formula. There's nothing to file here."
    ),
    "remodel_tax": (
        "Remodel tax isn't a markup rule here — it's already set by a typed percent, then the "
        "county table, then the 6.5% floor. File a county rate instead of a formula."
    ),
}
LINE_KEYS = tuple(k for k in CHAIN if k not in _NOT_EDITABLE)

# What a caller may set. Anything else in the payload is ignored rather than stored: an unknown
# key is a client bug, and persisting it makes the row shape unpredictable for later readers.
RULE_WRITABLE = ("layout", "line_key", "formula", "applies", "notes", "sort")

_MAX_FORMULA = 2000
_MAX_NOTES = 4000
_MAX_SORT = 10000

_TRUE_WORDS = ("true", "t", "yes", "y", "on", "1")
_FALSE_WORDS = ("false", "f", "no", "n", "off", "0")


class ValidationError(ValueError):
    """A caller-fixable problem. The message is shown to the user, so it says what to do."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any, limit: int = _MAX_NOTES) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _boolean(raw: Any, *, field: str, default: bool) -> bool:
    """A real boolean, or `default` when the caller said nothing.

    NOT `bool(raw)`. `bool("false")` is True, and a checkbox posted as the string "false" is the
    normal shape of this field arriving from a form — reading it as True would switch a markup
    line back on for every job on that tab. Anything unrecognised is refused rather than guessed,
    because the wrong guess here is the expensive direction."""
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    text = str(raw).strip().casefold()
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    raise ValidationError("%s has to be yes or no, not \"%s\"." % (field, _clean_text(raw, 40)))


def _read_bool(raw: Any, *, default: bool) -> bool:
    """`_boolean` for a row coming OUT of the database, where nothing may raise.

    A list call that 500s because one hand-edited row holds a junk value would take the whole
    markup screen — and the pricing read behind it — down over a single cell."""
    try:
        return _boolean(raw, field="Applies", default=default)
    except ValidationError:
        return default


def _integer(raw: Any, *, field: str, default: int) -> int:
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool):
        raise ValidationError("%s isn't a number." % field)
    try:
        num = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        raise ValidationError("%s isn't a number." % field)
    if abs(num) > _MAX_SORT:
        raise ValidationError("%s is out of range." % field)
    return num


def _check_layout(value: Any, *, field: str = "layout") -> str:
    """One of the five tabs, lower-cased. `combo` is refused by name and with its reason."""
    text = _clean_text(value, 40).casefold()
    if not text:
        raise ValidationError("Say which sheet layout this rule belongs to (%s)."
                              % ", ".join(LAYOUTS))
    if text == "combo":
        raise ValidationError(
            "There is no markup for \"combo\": a combo job is two option lines, each priced off "
            "its own tab. File the rule under that tab instead (%s)." % ", ".join(LAYOUTS))
    if text not in LAYOUTS:
        raise ValidationError("\"%s\" isn't a sheet layout. Use one of: %s."
                              % (_clean_text(value, 40), ", ".join(LAYOUTS)))
    return text


def _check_line_key(value: Any) -> str:
    text = _clean_text(value, 40).casefold().replace("-", "_").replace(" ", "_")
    if not text:
        raise ValidationError("Say which markup line this rule is for (%s)."
                              % ", ".join(LINE_KEYS))
    if text in _NOT_EDITABLE:
        raise ValidationError(_NOT_EDITABLE[text])
    if text not in LINE_KEYS:
        raise ValidationError("\"%s\" isn't a markup line. Use one of: %s."
                              % (_clean_text(value, 40), ", ".join(LINE_KEYS)))
    return text


def _check_formula(raw: Any) -> str:
    """A formula's SHAPE. Not its grammar — see the module docstring.

    Length is REFUSED rather than truncated, which is the opposite of how `notes` is handled and
    deliberately so: a clipped note is a clipped note, but a clipped expression is a DIFFERENT
    expression that may well still evaluate, and it would price jobs quietly wrong.

    The two balance checks are the typos that a formula this long actually collects, and neither
    can false-positive on a valid expression: a correct one has matched parentheses, and Excel
    escapes a quote inside a string as "" so the double-quote count stays even."""
    text = _clean_text(raw, _MAX_FORMULA + 1)
    if not text:
        raise ValidationError(
            "Give the line a formula, or switch it off — an empty formula on a line that applies "
            "would price the job to nothing without saying so.")
    if len(text) > _MAX_FORMULA:
        raise ValidationError("That formula is longer than %d characters — check it."
                              % _MAX_FORMULA)
    if text.count("(") != text.count(")"):
        raise ValidationError("That formula has %d \"(\" and %d \")\" — the brackets don't match."
                              % (text.count("("), text.count(")")))
    if text.count("\"") % 2:
        raise ValidationError("That formula has an unclosed \" quote.")
    return text


def validate_rule(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Shape and check one rule; returns only the columns we intend to write.

    NOT PARTIAL, and that is the design. A rule is identified by (layout, line_key) and is four
    small fields; the editor states the whole line every time. A partial patch would let a save
    that names only `notes` leave `applies` and `formula` at whatever a previous save happened to
    put there, which is how the two of them drift apart."""
    if not isinstance(payload, dict):
        raise ValidationError("Nothing to save.")

    out: Dict[str, Any] = {}
    out["layout"] = _check_layout(payload.get("layout"))
    out["line_key"] = _check_line_key(payload.get("line_key"))

    # THE DISTINCTION THIS TABLE EXISTS TO KEEP. `applies=false` is "this tab has no such line"
    # (Gyp's hard-bid cell is empty); `formula='0'` is "it has one and it prices to nothing".
    # A line that does not apply stores NO formula, so the two states cannot be confused by a
    # later reader — and a line that DOES apply must carry one, or the chain has nothing to run.
    out["applies"] = _boolean(payload.get("applies"), field="Applies", default=True)
    if out["applies"]:
        out["formula"] = _check_formula(payload.get("formula"))
    else:
        # Dropped, not refused: the editor keeps the last expression in the box while the toggle
        # is off, and refusing the save would mean clearing the field by hand first. Visible
        # rather than silent — the response carries formula=null, so the screen shows what
        # happened. Anything typed is gone, so keep it in `notes` if it matters.
        out["formula"] = None

    out["notes"] = _clean_text(payload.get("notes"), _MAX_NOTES) or None
    out["sort"] = _integer(payload.get("sort"), field="Sort",
                           default=CHAIN.index(out["line_key"]) * 10)
    return out


def _shape_rule(row: Dict[str, Any]) -> Dict[str, Any]:
    """One row as JSON.

    `applies` is READ FROM THE COLUMN. It is never re-derived from whether a formula is present —
    that inference is exactly the conflation the table is built to avoid, and it would report
    Gyp's absent hard-bid line and a genuine 0% line as the same thing."""
    raw_formula = row.get("formula")
    formula = None if raw_formula in (None, "") else str(raw_formula)
    applies = _read_bool(row.get("applies"), default=True)
    if not applies and formula is not None:
        # Unreachable through validate_rule, so this row was hand-edited in a SQL console.
        # Reported as stored rather than quietly repaired: guessing which of the two fields the
        # person meant is how a rate changes without anybody deciding to change it.
        log.warning("markup_rules row %s (%s/%s) says applies=false but carries a formula; "
                    "serving it as stored", row.get("id"), row.get("layout"), row.get("line_key"))
    return {
        "id": row.get("id"),
        "layout": row.get("layout") or "",
        "line_key": row.get("line_key") or "",
        "formula": formula,
        "applies": applies,
        "notes": row.get("notes") or "",
        "sort": _integer(row.get("sort"), field="Sort", default=0),
        "owner_email": row.get("owner_email") or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _chain_order(rule: Dict[str, Any]) -> tuple:
    line_key = rule.get("line_key") or ""
    fallback = CHAIN.index(line_key) if line_key in CHAIN else len(CHAIN)
    return (rule.get("layout") or "", rule.get("sort", 0), fallback, line_key)


def list_rules(layout: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every live rule, or one layout's.

    An unrecognised `layout` is REFUSED, not answered with an empty list. Day one has no rows and
    the caller is expected to fall back to its constants on an empty list — so a typo'd layout
    that returned [] would look exactly like "nothing configured yet" and quietly price the whole
    tab off the hardcoded numbers this table was built to replace.

    Sorted in Python as well as in the query. PostgREST and the staging Postgres agree on
    ordering, but `sort` is caller-settable and can tie, and the chain COMPOUNDS — a chain read in
    two different orders is two different prices."""
    sb = get_client()
    q = sb.table(RULES).select("*").is_("deleted_at", "null")
    if layout not in (None, ""):
        q = q.eq("layout", _check_layout(layout))
    res = q.order("sort").limit(500).execute()
    return sorted([_shape_rule(r) for r in (res.data or [])], key=_chain_order)


def get_rule(rule_id: str) -> Optional[Dict[str, Any]]:
    sb = get_client()
    res = (sb.table(RULES).select("*")
           .eq("id", rule_id).is_("deleted_at", "null").limit(1).execute())
    rows = res.data or []
    return _shape_rule(rows[0]) if rows else None


def find_rule(layout: str, line_key: str) -> Optional[Dict[str, Any]]:
    """The one live rule for a (layout, line_key), or None.

    Both halves are validated first, so only values from the closed vocabularies ever reach a
    PostgREST filter — the same posture `_clashing_vendor` takes about user text in a filter
    string, arrived at from the other end. Validating before touching the client also means a
    lookup for a name that can never exist is refused without a data store configured at all."""
    layout = _check_layout(layout)
    line_key = _check_line_key(line_key)
    sb = get_client()
    res = (sb.table(RULES).select("*")
           .eq("layout", layout)
           .eq("line_key", line_key)
           .is_("deleted_at", "null").limit(1).execute())
    rows = res.data or []
    return _shape_rule(rows[0]) if rows else None


def upsert_rule(payload: Dict[str, Any], owner_email: Optional[str]) -> Dict[str, Any]:
    """Save one rule, by (layout, line_key). Validated in full BEFORE anything is written.

    Upsert rather than create-plus-update because the identity is the pair, not an id the page
    has to keep: there is exactly one gp rule for the polish tab, and the editor should not be
    able to make a second one that shadows it.

    A soft-deleted row with the same key is NOT revived — a new row is written and the old one
    stays deleted. Reviving it would mean a save silently inheriting a formula and a note that
    somebody deliberately removed."""
    row = validate_rule(payload)
    existing = find_rule(row["layout"], row["line_key"])
    sb = get_client()
    if existing:
        patch = dict(row)
        patch["updated_at"] = _now_iso()
        sb.table(RULES).update(patch).eq("id", existing["id"]).execute()
        saved = get_rule(existing["id"])
        if saved is None:
            # The row was deleted between the lookup and the write. Loud, because the caller is
            # about to tell an admin their rule was saved.
            raise ValidationError(
                "That %s / %s rule was removed while you were editing it. Save it again to "
                "recreate it." % (row["layout"], row["line_key"]))
        return saved
    row["id"] = str(uuid.uuid4())
    row["owner_email"] = (owner_email or "").lower() or None
    row["created_at"] = row["updated_at"] = _now_iso()
    sb.table(RULES).insert(row).execute()
    return _shape_rule(row)


def delete_rule(rule_id: str) -> bool:
    """Soft-delete one rule. False when there was nothing live to delete.

    The chain falls back to its hardcoded constant for a line with no rule, so removing a rule is
    "stop overriding this", not "charge nothing" — which is why it needs to be recoverable."""
    sb = get_client()
    cur = (sb.table(RULES).select("id")
           .eq("id", rule_id).is_("deleted_at", "null").limit(1).execute())
    if not (cur.data or []):
        return False
    sb.table(RULES).update({"deleted_at": _now_iso()}).eq("id", rule_id).execute()
    return True
