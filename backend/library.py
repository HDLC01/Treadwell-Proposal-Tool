"""Item Library — the materials Treadwell buys, and the assemblies built out of them.

WHAT THIS IS FOR. Kyle and Will want to compose their own systems instead of the fixed ones
baked into the estimate sheet: pick a primer, a body coat, a top coat, and see the cost per
square foot. On the sheet today a system's materials are fixed — the top coat is Armor Top and
nothing else — so this exists to make them interchangeable.

DELIBERATELY STANDALONE. Nothing in the intake / estimate / proposal path reads or writes these
tables, and this module imports nothing from `pricing.py`. That is Hanz's instruction and it is
also the safer order: the shape of an assembly is still being worked out, and a table the
estimator depends on cannot be changed freely.

TWO TABLES, NOT THREE.

    library_items       one purchasable material, and the single source of truth for its price
    library_assemblies  a named system; its lines live in a `lines` JSONB column

Lines are JSONB rather than their own table because they are ordered, always read and written
as a whole, and never queried across assemblies — the same call already made for
`paragraph_overrides`. The cost of that choice is that a line's `item_id` is not a foreign key,
so an item can be deleted while a line still points at it. That is handled rather than
prevented: the pricing layer reports such a line as broken and excludes it, which beats both a
delete that silently rewrites somebody's assembly and a foreign key that refuses to let a
mistyped material ever be removed.

WHERE THE PRICING LIVES. Not here. `frontend/js/library-core.js` holds it, because today the
only consumer is the screen and the area preview recalculates as you type. When this is wired
into estimating the maths moves to Python with the same test vectors; until then one
implementation beats two that can drift.

DELETES ARE SOFT, as in `calendar_events`: `deleted_at` non-NULL hides a row. A price list is
reference data somebody has typed by hand, and every other destructive action in this tool is
recoverable.
"""
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from supabase_client import get_client

log = logging.getLogger(__name__)

ITEMS = "library_items"
ASSEMBLIES = "library_assemblies"

# What a caller may set. Anything else in the payload is ignored rather than stored: an unknown
# key is a client bug, and persisting it makes the row shape unpredictable for later readers.
ITEM_WRITABLE = ("name", "category", "unit", "unit_cost", "coverage", "sku", "vendor", "notes")
ASM_WRITABLE = ("name", "category", "description", "unit", "lines")

DEFAULT_ITEM_UNIT = "Gal"       # what Kyle's sheet buys most things by
DEFAULT_ASM_UNIT = "SF"         # what a system is priced per

_MAX_TEXT = 200
_MAX_NOTES = 4000
_MAX_LINES = 60                 # a system with 60 coats is a mistake, not a system
_MAX_UNIT_COST = 1e7            # $10M for one gallon is a typo
_MAX_COVERAGE = 1e6             # SF covered by one unit


class ValidationError(ValueError):
    """A caller-fixable problem. The message is shown to the user, so it says what to do."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any, limit: int = _MAX_TEXT) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _number(raw: Any, *, field: str, maximum: float) -> Optional[float]:
    """A non-negative number, or None. Tolerates "$1,200" and " 275 ".

    These values get pasted straight out of a spreadsheet, so the currency symbol and the
    thousands separator arrive with them. Refusing a pasted price teaches people to retype it,
    which is how a digit gets dropped."""
    if raw in (None, ""):
        return None
    if isinstance(raw, bool):
        raise ValidationError("%s isn't a number." % field)
    if isinstance(raw, (int, float)):
        num = float(raw)
    else:
        stripped = re.sub(r"[$,\s]", "", str(raw))
        try:
            num = float(stripped)
        except ValueError:
            raise ValidationError("%s isn't a number." % field)
    if num != num or num in (float("inf"), float("-inf")):     # NaN / Infinity
        raise ValidationError("%s isn't a number." % field)
    if num < 0:
        raise ValidationError("%s can't be negative." % field)
    if num > maximum:
        raise ValidationError("%s is implausibly large — check the figure." % field)
    return num


# ── items ─────────────────────────────────────────────────────────────────────
def validate_item(payload: Dict[str, Any], *, partial: bool = False) -> Dict[str, Any]:
    """Shape and check an item payload; returns only the columns we intend to write."""
    if not isinstance(payload, dict):
        raise ValidationError("Nothing to save.")

    out: Dict[str, Any] = {}

    if "name" in payload or not partial:
        name = _clean_text(payload.get("name"))
        if not name:
            raise ValidationError("Give the material a name so it can be found later.")
        out["name"] = name

    if "unit" in payload or not partial:
        # Freeform on purpose. Kyle buys by Gal, Kit, Pint, Quart, Each, Bag, Roll — and the
        # next product will use a unit nobody has thought of. A closed list would block it.
        out["unit"] = _clean_text(payload.get("unit"), 24) or DEFAULT_ITEM_UNIT

    if "unit_cost" in payload or not partial:
        out["unit_cost"] = _number(payload.get("unit_cost"),
                                   field="A cost", maximum=_MAX_UNIT_COST)

    if "coverage" in payload or not partial:
        cov = _number(payload.get("coverage"), field="Coverage", maximum=_MAX_COVERAGE)
        # Zero coverage would mean one unit covers nothing, which prices every job as infinite
        # material. Treated as "not set" rather than accepted.
        out["coverage"] = cov if (cov is None or cov > 0) else None

    for col, limit in (("category", _MAX_TEXT), ("sku", 80),
                       ("vendor", _MAX_TEXT), ("notes", _MAX_NOTES)):
        if col in payload or not partial:
            out[col] = _clean_text(payload.get(col), limit) or None

    return out


def _shape_item(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row.get("id"),
        "name": row.get("name") or "Untitled",
        "category": row.get("category") or "",
        "unit": row.get("unit") or DEFAULT_ITEM_UNIT,
        # Floats, not strings: the page does arithmetic with these. PostgREST returns numerics
        # as strings, so the coercion happens here rather than in every caller.
        "unit_cost": _as_float(row.get("unit_cost")),
        "coverage": _as_float(row.get("coverage")),
        "sku": row.get("sku") or "",
        "vendor": row.get("vendor") or "",
        "notes": row.get("notes") or "",
        "owner_email": row.get("owner_email") or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _as_float(v: Any) -> Optional[float]:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def list_items() -> List[Dict[str, Any]]:
    sb = get_client()
    res = (sb.table(ITEMS).select("*")
           .is_("deleted_at", "null")
           .order("name")
           .limit(2000).execute())
    return [_shape_item(r) for r in (res.data or [])]


def get_item(item_id: str) -> Optional[Dict[str, Any]]:
    sb = get_client()
    res = (sb.table(ITEMS).select("*")
           .eq("id", item_id).is_("deleted_at", "null").limit(1).execute())
    rows = res.data or []
    return _shape_item(rows[0]) if rows else None


def create_item(payload: Dict[str, Any], owner_email: Optional[str]) -> Dict[str, Any]:
    row = validate_item(payload)
    row["id"] = str(uuid.uuid4())
    row["owner_email"] = (owner_email or "").lower() or None
    row["created_at"] = row["updated_at"] = _now_iso()
    sb = get_client()
    sb.table(ITEMS).insert(row).execute()
    return _shape_item(row)


def update_item(item_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    patch = validate_item(payload, partial=True)
    if not patch:
        return get_item(item_id)
    patch["updated_at"] = _now_iso()
    sb = get_client()
    cur = (sb.table(ITEMS).select("id")
           .eq("id", item_id).is_("deleted_at", "null").limit(1).execute())
    if not (cur.data or []):
        return None
    sb.table(ITEMS).update(patch).eq("id", item_id).execute()
    return get_item(item_id)


def delete_item(item_id: str) -> bool:
    """Soft-delete a material.

    Assemblies referencing it are deliberately left alone. Rewriting somebody else's assembly
    as a side effect of a delete is worse than a visible broken line they can repoint — and the
    pricing layer already reports exactly that."""
    sb = get_client()
    cur = (sb.table(ITEMS).select("id")
           .eq("id", item_id).is_("deleted_at", "null").limit(1).execute())
    if not (cur.data or []):
        return False
    sb.table(ITEMS).update({"deleted_at": _now_iso()}).eq("id", item_id).execute()
    return True


# ── assemblies ────────────────────────────────────────────────────────────────
def _clean_lines(raw: Any) -> List[Dict[str, Any]]:
    """Normalise the `lines` array. Never raises on a weird line — drops it.

    A half-built line is the normal state of this screen: somebody adds a row, then picks the
    material. Refusing the whole save because one line has no material yet would make the
    editor unusable, so an empty line is simply not stored."""
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise ValidationError("Those lines aren't in a shape we can read.")
    out: List[Dict[str, Any]] = []
    for entry in raw[:_MAX_LINES]:
        if not isinstance(entry, dict):
            continue
        item_id = _clean_text(entry.get("item_id"), 60)
        role = _clean_text(entry.get("role"), 80)
        note = _clean_text(entry.get("note"), 300)
        coverage = _number(entry.get("coverage"), field="Coverage", maximum=_MAX_COVERAGE)
        if coverage is not None and coverage <= 0:
            coverage = None
        # A line with neither a material nor a role is an empty row nobody filled in.
        if not item_id and not role:
            continue
        out.append({"role": role, "item_id": item_id or None,
                    "coverage": coverage, "note": note or None})
    return out


def validate_assembly(payload: Dict[str, Any], *, partial: bool = False) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValidationError("Nothing to save.")

    out: Dict[str, Any] = {}

    if "name" in payload or not partial:
        name = _clean_text(payload.get("name"))
        if not name:
            raise ValidationError("Give the assembly a name so it can be found later.")
        out["name"] = name

    if "unit" in payload or not partial:
        out["unit"] = _clean_text(payload.get("unit"), 24) or DEFAULT_ASM_UNIT

    for col, limit in (("category", _MAX_TEXT), ("description", _MAX_NOTES)):
        if col in payload or not partial:
            out[col] = _clean_text(payload.get(col), limit) or None

    if "lines" in payload or not partial:
        out["lines"] = _clean_lines(payload.get("lines"))

    return out


def _shape_assembly(row: Dict[str, Any]) -> Dict[str, Any]:
    lines = row.get("lines")
    if not isinstance(lines, list):
        lines = []
    return {
        "id": row.get("id"),
        "name": row.get("name") or "Untitled",
        "category": row.get("category") or "",
        "description": row.get("description") or "",
        "unit": row.get("unit") or DEFAULT_ASM_UNIT,
        "lines": [{
            "role": (ln or {}).get("role") or "",
            "item_id": (ln or {}).get("item_id") or "",
            "coverage": _as_float((ln or {}).get("coverage")),
            "note": (ln or {}).get("note") or "",
        } for ln in lines if isinstance(ln, dict)],
        "owner_email": row.get("owner_email") or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def list_assemblies() -> List[Dict[str, Any]]:
    sb = get_client()
    res = (sb.table(ASSEMBLIES).select("*")
           .is_("deleted_at", "null")
           .order("name")
           .limit(1000).execute())
    return [_shape_assembly(r) for r in (res.data or [])]


def get_assembly(asm_id: str) -> Optional[Dict[str, Any]]:
    sb = get_client()
    res = (sb.table(ASSEMBLIES).select("*")
           .eq("id", asm_id).is_("deleted_at", "null").limit(1).execute())
    rows = res.data or []
    return _shape_assembly(rows[0]) if rows else None


def create_assembly(payload: Dict[str, Any], owner_email: Optional[str]) -> Dict[str, Any]:
    row = validate_assembly(payload)
    row["id"] = str(uuid.uuid4())
    row["owner_email"] = (owner_email or "").lower() or None
    row["created_at"] = row["updated_at"] = _now_iso()
    sb = get_client()
    sb.table(ASSEMBLIES).insert(row).execute()
    return _shape_assembly(row)


class StaleWrite(Exception):
    """Somebody else changed this assembly since the page last read it.

    Every line edit PATCHes the WHOLE `lines` array, because that is how a JSONB column is
    written. Two people with the assembly open therefore overwrite each other completely: the
    second save replaces the first person's lines with a snapshot taken before they existed, and
    neither screen shows anything wrong. Hand-typed reference data, gone, with no error and
    nothing to recover from — soft-delete protects rows, not the contents of one.

    So a caller may declare the version it is editing, and a write against a stale one is refused
    with the current state attached, rather than silently winning.
    """

    def __init__(self, current: Optional[Dict[str, Any]]):
        super().__init__("This assembly changed while you were editing it.")
        self.current = current


def update_assembly(asm_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Patch one assembly. `expected_updated_at`, when given, must match what is stored."""
    expected = payload.get("expected_updated_at") if isinstance(payload, dict) else None
    patch = validate_assembly(payload, partial=True)
    if not patch:
        return get_assembly(asm_id)
    patch["updated_at"] = _now_iso()
    sb = get_client()
    cur = (sb.table(ASSEMBLIES).select("id,updated_at")
           .eq("id", asm_id).is_("deleted_at", "null").limit(1).execute())
    rows = cur.data or []
    if not rows:
        return None
    # Only checked when the caller supplies it, so an integration or a curl call is not forced to
    # play along — but the editor always does, which is where the conflict actually happens.
    if expected and str(rows[0].get("updated_at") or "") != str(expected):
        raise StaleWrite(get_assembly(asm_id))
    sb.table(ASSEMBLIES).update(patch).eq("id", asm_id).execute()
    return get_assembly(asm_id)


def delete_assembly(asm_id: str) -> bool:
    sb = get_client()
    cur = (sb.table(ASSEMBLIES).select("id")
           .eq("id", asm_id).is_("deleted_at", "null").limit(1).execute())
    if not (cur.data or []):
        return False
    sb.table(ASSEMBLIES).update({"deleted_at": _now_iso()}).eq("id", asm_id).execute()
    return True
