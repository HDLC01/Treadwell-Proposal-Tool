"""Item Library — the materials Treadwell buys, and the assemblies built out of them.

WHAT THIS IS FOR. Kyle and Will want to compose their own systems instead of the fixed ones
baked into the estimate sheet: pick a primer, a body coat, a top coat, and see the cost per
square foot. On the sheet today a system's materials are fixed — the top coat is Armor Top and
nothing else — so this exists to make them interchangeable.

ONE READER, AND IT IS ALSO A BETA. From 2026-08-18 the Polish Estimate BETA prices its takeoff
from these assemblies (`GET /api/library/assemblies` → `priceAssembly` in
frontend/js/library-core.js). That page only ever edits test projects, so the shape of an assembly
is still free to change — but it is no longer true that nothing depends on it, and a change here
can now move a number on a screen somebody is reading.

Still standalone in the direction that matters: this module imports nothing from `pricing.py`, and
nothing on the LIVE intake / estimate / proposal path reads these tables.

THREE TABLES, AND NO LINES TABLE.

    library_items       one purchasable material, and the single source of truth for its price
    library_assemblies  a named system; its lines live in a `lines` JSONB column
    library_vendors     who Treadwell buys from — a list, so the Items tab can offer a dropdown
                        instead of a free-text box that grows three spellings of one supplier.
                        Managing the list is admin-only; picking from it is not.

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
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from supabase_client import get_client

log = logging.getLogger(__name__)

ITEMS = "library_items"
ASSEMBLIES = "library_assemblies"
VENDORS = "library_vendors"
DIVISION_REFS = "library_divisions"
UNIT_REFS = "library_units"

# What a caller may set. Anything else in the payload is ignored rather than stored: an unknown
# key is a client bug, and persisting it makes the row shape unpredictable for later readers.
ITEM_WRITABLE = ("name", "category", "divisions", "unit", "buy_qty", "unit_cost", "coverage",
                 "sku", "vendor", "notes")
ASM_WRITABLE = ("name", "category", "description", "unit", "lines")
VENDOR_WRITABLE = ("name", "notes")
REF_WRITABLE = ("name", "notes")

DEFAULT_ITEM_UNIT = "Gallon"    # what Kyle's sheet buys most things by
DEFAULT_ASM_UNIT = "SF"         # what a system is priced per
DEFAULT_WASTE_PCT = 5.0         # Hanz, 2026-08-15: "by default is 5%"

# The three divisions Treadwell estimates in (Hanz, 2026-08-15 — this replaced a free-text
# "Category"). NOT enforced: a legacy row already holds whatever somebody typed, and refusing to
# save it would make those rows uneditable. The dropdown offers these three and shows an
# off-list value as its own option, so a legacy category stays visible and correctable.
DIVISIONS = ("Polished Concrete", "Epoxy", "Gypsum Underlayment")

# What the Unit dropdown offers. Same posture as DIVISIONS: offered, not enforced. Kyle's earlier
# rows say "Gal", "Kit", "Pint", "Roll", and the next product will use a unit nobody has thought
# of — a check constraint would block the purchase, not the typo.
ITEM_UNITS = ("Gallon", "Kit", "Bag")

_MAX_TEXT = 200
_MAX_NOTES = 4000
_MAX_LINES = 60                 # a system with 60 coats is a mistake, not a system
_MAX_UNIT_COST = 1e7            # $10M for one gallon is a typo
_MAX_COVERAGE = 1e6             # SF covered by one unit
_MAX_BUY_QTY = 1e5              # a 100,000-unit pack is a typo, not a pallet


class ValidationError(ValueError):
    """A caller-fixable problem. The message is shown to the user, so it says what to do."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any, limit: int = _MAX_TEXT) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _canonical(value: str, offered: tuple) -> str:
    """The offered spelling when `value` is one of them in any case; otherwise `value` untouched.

    Case only, and never a rejection. Both lists are OFFERED, not enforced — a legacy row holds
    whatever somebody typed, and refusing to save it would make that row uneditable."""
    for known in offered:
        if value.casefold() == known.casefold():
            return known
    return value


def _canonical_from(value: str, offered: List[str] | tuple) -> str:
    """Canonical spelling from a dynamic offered list; otherwise keep the user's spelling."""
    for known in offered:
        if value.casefold() == str(known).casefold():
            return str(known)
    return value


def _dedup_names(values: List[str], offered: List[str] | tuple) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in values:
        name = _canonical_from(_clean_text(raw), offered)
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def _coerce_divisions(raw: Any, fallback: Any = None) -> List[str]:
    values: List[str] = []
    if isinstance(raw, list):
        values = raw
    elif isinstance(raw, tuple):
        values = list(raw)
    elif isinstance(raw, str) and raw.strip().startswith("["):
        try:
            parsed = json.loads(raw)
            values = parsed if isinstance(parsed, list) else []
        except (TypeError, ValueError):
            values = []
    elif raw not in (None, ""):
        values = [raw]
    elif fallback not in (None, ""):
        values = [fallback]
    return _dedup_names([str(v) for v in values], DIVISIONS)


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


# ── administration reference lists ───────────────────────────────────────────
def _ref_defaults(table: str) -> tuple:
    if table == DIVISION_REFS:
        return DIVISIONS
    if table == UNIT_REFS:
        return ITEM_UNITS
    return ()


def _shape_ref(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row.get("id"),
        "name": row.get("name") or "Untitled",
        "notes": row.get("notes") or "",
        "owner_email": row.get("owner_email") or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _list_refs(table: str) -> List[Dict[str, Any]]:
    sb = get_client()
    res = (sb.table(table).select("*")
           .is_("deleted_at", "null")
           .order("name")
           .limit(500).execute())
    rows = [_shape_ref(r) for r in (res.data or [])]
    if rows:
        return rows
    any_row = sb.table(table).select("id").limit(1).execute()
    if any_row.data:
        return []
    return [{"id": "", "name": name, "notes": "", "owner_email": "",
             "created_at": None, "updated_at": None} for name in _ref_defaults(table)]


def _live_refs_only(table: str) -> List[Dict[str, Any]]:
    sb = get_client()
    res = (sb.table(table).select("*")
           .is_("deleted_at", "null")
           .order("name")
           .limit(500).execute())
    return [_shape_ref(r) for r in (res.data or [])]


def _list_ref_names(table: str) -> List[str]:
    return [r["name"] for r in _list_refs(table)]


def list_divisions() -> List[Dict[str, Any]]:
    return _list_refs(DIVISION_REFS)


def list_units() -> List[Dict[str, Any]]:
    return _list_refs(UNIT_REFS)


def list_division_names() -> List[str]:
    return _list_ref_names(DIVISION_REFS)


def list_unit_names() -> List[str]:
    return _list_ref_names(UNIT_REFS)


def _get_ref(table: str, ref_id: str) -> Optional[Dict[str, Any]]:
    sb = get_client()
    res = (sb.table(table).select("*")
           .eq("id", ref_id).is_("deleted_at", "null").limit(1).execute())
    rows = res.data or []
    return _shape_ref(rows[0]) if rows else None


def validate_ref(payload: Dict[str, Any], *, label: str, partial: bool = False) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValidationError("Nothing to save.")
    out: Dict[str, Any] = {}
    if "name" in payload or not partial:
        name = _clean_text(payload.get("name"))
        if not name:
            raise ValidationError("Give the %s a name." % label)
        out["name"] = name
    if "notes" in payload or not partial:
        out["notes"] = _clean_text(payload.get("notes"), _MAX_NOTES) or None
    return out


def _clashing_ref(table: str, name: str, *, ignore_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    target = name.casefold()
    for row in _live_refs_only(table):
        if row.get("id") != ignore_id and str(row.get("name") or "").casefold() == target:
            return row
    return None


def create_ref(table: str, payload: Dict[str, Any], owner_email: Optional[str], *, label: str) -> Dict[str, Any]:
    row = validate_ref(payload, label=label)
    clash = _clashing_ref(table, row["name"])
    if clash:
        raise ValidationError("\"%s\" is already on the list." % clash["name"])
    row["id"] = str(uuid.uuid4())
    row["owner_email"] = (owner_email or "").lower() or None
    row["created_at"] = row["updated_at"] = _now_iso()
    sb = get_client()
    sb.table(table).insert(row).execute()
    return _shape_ref(row)


def update_ref(table: str, ref_id: str, payload: Dict[str, Any], *, label: str) -> Optional[Dict[str, Any]]:
    patch = validate_ref(payload, label=label, partial=True)
    if not patch:
        return _get_ref(table, ref_id)
    sb = get_client()
    cur = (sb.table(table).select("id")
           .eq("id", ref_id).is_("deleted_at", "null").limit(1).execute())
    if not (cur.data or []):
        return None
    if patch.get("name"):
        clash = _clashing_ref(table, patch["name"], ignore_id=ref_id)
        if clash:
            raise ValidationError("\"%s\" is already on the list." % clash["name"])
    patch["updated_at"] = _now_iso()
    sb.table(table).update(patch).eq("id", ref_id).execute()
    return _get_ref(table, ref_id)


def delete_ref(table: str, ref_id: str) -> bool:
    sb = get_client()
    cur = (sb.table(table).select("id")
           .eq("id", ref_id).is_("deleted_at", "null").limit(1).execute())
    if not (cur.data or []):
        return False
    sb.table(table).update({"deleted_at": _now_iso()}).eq("id", ref_id).execute()
    return True


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
        # Freeform on purpose. The page offers Gallon / Kit / Bag, but Kyle's earlier rows say
        # Gal, Pint, Quart, Each, Roll — and the next product will use a unit nobody has thought
        # of. A closed list would block the purchase rather than the typo.
        out["unit"] = _canonical(_clean_text(payload.get("unit"), 24), ITEM_UNITS) \
            or DEFAULT_ITEM_UNIT

    if "divisions" in payload or ("category" in payload and partial) or not partial:
        divisions = _coerce_divisions(payload.get("divisions"), payload.get("category"))
        out["divisions"] = divisions
        out["category"] = divisions[0] if divisions else None

    if "buy_qty" in payload or not partial:
        # How many units come in the purchase — the "5" of "5 Gal". `unit_cost` is what that pack
        # costs, so this is what turns a needed 16.8 gallons into four pails.
        #
        # Zero or blank means 1, not "free": a pack of nothing would divide the cost by zero, and
        # every row written before this column existed is genuinely a pack of one.
        qty = _number(payload.get("buy_qty"), field="Qty", maximum=_MAX_BUY_QTY)
        out["buy_qty"] = qty if (qty is not None and qty > 0) else 1.0

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
        if col == "category" and "divisions" in out:
            continue
        if col in payload or not partial:
            out[col] = _clean_text(payload.get(col), limit) or None

    # "epoxy" pasted from somewhere becomes the Division the dropdown offers, so the row reads as a
    # known value instead of an off-list one. Case only — a division we don't recognise is left
    # exactly as typed, because this is a rename of a free-text column and old rows hold anything.
    if out.get("category"):
        out["category"] = _canonical(out["category"], DIVISIONS)
        if "divisions" in out:
            out["divisions"] = _coerce_divisions(out["divisions"], out["category"])
            out["category"] = out["divisions"][0] if out["divisions"] else None

    return out


def _shape_item(row: Dict[str, Any]) -> Dict[str, Any]:
    divisions = _coerce_divisions(row.get("divisions"), row.get("category"))
    return {
        "id": row.get("id"),
        "name": row.get("name") or "Untitled",
        "category": divisions[0] if divisions else (row.get("category") or ""),
        "divisions": divisions,
        "unit": row.get("unit") or DEFAULT_ITEM_UNIT,
        # Floats, not strings: the page does arithmetic with these. PostgREST returns numerics
        # as strings, so the coercion happens here rather than in every caller.
        "unit_cost": _as_float(row.get("unit_cost")),
        "coverage": _as_float(row.get("coverage")),
        # A row written before this column existed reads as a pack of one, which prices exactly as
        # it did then. Read-shaped rather than backfilled: rewriting somebody's hand-typed rows to
        # add a column is a migration that can go wrong, and this cannot.
        "buy_qty": _as_float(row.get("buy_qty")) or 1.0,
        "sku": row.get("sku") or "",
        "vendor": row.get("vendor") or "",
        "notes": row.get("notes") or "",
        "owner_email": row.get("owner_email") or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        # When the PRICE last moved, which is not when the row last changed — fixing a spelling
        # does not make a cost newer. None means "not since we started recording it".
        "cost_updated_at": row.get("cost_updated_at"),
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
    cur = (sb.table(ITEMS).select("id,unit_cost")
           .eq("id", item_id).is_("deleted_at", "null").limit(1).execute())
    rows = cur.data or []
    if not rows:
        return None
    # A PRICE REVISION, which is what Hanz asked to be able to see: "Date modified update should
    # only trigger when cost is modified". So the stamp moves when the number actually changes —
    # not when the name is corrected, and not when the same cost is saved again by the debounced
    # PATCH that fires as somebody tabs out of the field.
    if "unit_cost" in patch and _as_float(patch["unit_cost"]) != _as_float(rows[0].get("unit_cost")):
        patch["cost_updated_at"] = patch["updated_at"]
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
        # How much extra to buy over what the area needs: 5% by default, per Hanz. A line that
        # arrives without it is either legacy or a client bug, and either way 5 is the number the
        # screen shows — reading it as 0 would make the row lie about its own arithmetic.
        waste = _number(entry.get("waste_pct"), field="Waste factor", maximum=100)
        if waste is None:
            waste = DEFAULT_WASTE_PCT
        # Whole packs, or a fraction of one. True for a legacy line because CEIL is what it was
        # priced with — the screen has promised "you cannot buy 3.7 kits" since this page shipped.
        roundup = entry.get("roundup")
        roundup = True if roundup is None else bool(roundup)
        # A line with neither a material nor a role is an empty row nobody filled in. (Role left
        # the UI on 2026-08-15 but stays in the data, so an older line keeps its label.)
        if not item_id and not role:
            continue
        out.append({"role": role, "item_id": item_id or None, "coverage": coverage,
                    "waste_pct": waste, "roundup": roundup, "note": note or None})
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


def _waste_of(line: Any) -> float:
    """A line's waste factor, defaulting to 5% and clamped to something sane.

    Read-shaping rather than a migration: a legacy line has no waste factor at all, and the
    alternative to defaulting here is a row whose visible 5% is not the 5% it was priced with."""
    v = _as_float((line or {}).get("waste_pct"))
    if v is None or v < 0:
        return DEFAULT_WASTE_PCT
    return min(v, 100.0)


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
            # Both read-shaped with the same defaults the writer applies, so a line stored before
            # these columns existed prices identically whether or not it has been re-saved since.
            "waste_pct": _waste_of(ln),
            "roundup": bool((ln or {}).get("roundup", True)),
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


# ── vendors ───────────────────────────────────────────────────────────────────
# Who Treadwell buys from. A list rather than a free-text box on each item, because typing the
# supplier per row is how one company becomes "Sherwin", "Sherwin Williams" and "SW" — and then
# nobody can total what they spend with them.
#
# The item still stores the vendor NAME, not an id (see the schema comment). So this table governs
# what the dropdown OFFERS; it does not own what past items say. Renaming a vendor here therefore
# does not retitle old items, which is the safer of the two behaviours: an item records what it was
# bought from at the time.
def _shape_vendor(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row.get("id"),
        "name": row.get("name") or "Untitled",
        "notes": row.get("notes") or "",
        "owner_email": row.get("owner_email") or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def validate_vendor(payload: Dict[str, Any], *, partial: bool = False) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValidationError("Nothing to save.")
    out: Dict[str, Any] = {}
    if "name" in payload or not partial:
        name = _clean_text(payload.get("name"))
        if not name:
            raise ValidationError("Give the vendor a name.")
        out["name"] = name
    if "notes" in payload or not partial:
        out["notes"] = _clean_text(payload.get("notes"), _MAX_NOTES) or None
    return out


def list_vendors() -> List[Dict[str, Any]]:
    sb = get_client()
    res = (sb.table(VENDORS).select("*")
           .is_("deleted_at", "null")
           .order("name")
           .limit(500).execute())
    return [_shape_vendor(r) for r in (res.data or [])]


def get_vendor(vendor_id: str) -> Optional[Dict[str, Any]]:
    sb = get_client()
    res = (sb.table(VENDORS).select("*")
           .eq("id", vendor_id).is_("deleted_at", "null").limit(1).execute())
    rows = res.data or []
    return _shape_vendor(rows[0]) if rows else None


def _clashing_vendor(name: str, *, ignore_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """An existing live vendor with the same name, ignoring case and surrounding space.

    Compared in Python rather than with an `ilike` filter on purpose: vendor names contain commas
    and parentheses ("Sherwin-Williams, Inc."), and those are PostgREST filter syntax — a raw value
    would either error or silently match the wrong rows. The list is a few dozen names."""
    target = name.casefold()
    for v in list_vendors():
        if v.get("id") != ignore_id and str(v.get("name") or "").casefold() == target:
            return v
    return None


def create_vendor(payload: Dict[str, Any], owner_email: Optional[str]) -> Dict[str, Any]:
    row = validate_vendor(payload)
    clash = _clashing_vendor(row["name"])
    if clash:
        # Refused, not silently merged: this table exists to stop one supplier having three
        # spellings, and a second "Sherwin Williams" defeats the whole point of it.
        raise ValidationError("“%s” is already on the list." % clash["name"])
    row["id"] = str(uuid.uuid4())
    row["owner_email"] = (owner_email or "").lower() or None
    row["created_at"] = row["updated_at"] = _now_iso()
    sb = get_client()
    sb.table(VENDORS).insert(row).execute()
    return _shape_vendor(row)


def update_vendor(vendor_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    patch = validate_vendor(payload, partial=True)
    if not patch:
        return get_vendor(vendor_id)
    sb = get_client()
    cur = (sb.table(VENDORS).select("id")
           .eq("id", vendor_id).is_("deleted_at", "null").limit(1).execute())
    if not (cur.data or []):
        return None
    if patch.get("name"):
        clash = _clashing_vendor(patch["name"], ignore_id=vendor_id)
        if clash:
            raise ValidationError("“%s” is already on the list." % clash["name"])
    patch["updated_at"] = _now_iso()
    sb.table(VENDORS).update(patch).eq("id", vendor_id).execute()
    return get_vendor(vendor_id)


def delete_vendor(vendor_id: str) -> bool:
    """Soft-delete a vendor.

    Items naming it keep saying so — they store the name, and rewriting somebody's purchase record
    because the supplier left the list would be a lie about where the material came from. The
    dropdown stops offering it; an item that already carries it shows it as its own option."""
    sb = get_client()
    cur = (sb.table(VENDORS).select("id")
           .eq("id", vendor_id).is_("deleted_at", "null").limit(1).execute())
    if not (cur.data or []):
        return False
    sb.table(VENDORS).update({"deleted_at": _now_iso()}).eq("id", vendor_id).execute()
    return True


def vendor_usage() -> Dict[str, int]:
    """How many live items name each vendor, keyed by casefolded name.

    So the Vendors tab can say what a delete affects before it happens, the same way removing a
    material says how many assemblies use it."""
    counts: Dict[str, int] = {}
    for it in list_items():
        key = str(it.get("vendor") or "").casefold()
        if key:
            counts[key] = counts.get(key, 0) + 1
    return counts


def division_usage() -> Dict[str, int]:
    """How many live items name each division, keyed by casefolded division name."""
    counts: Dict[str, int] = {}
    for it in list_items():
        for div in _coerce_divisions(it.get("divisions"), it.get("category")):
            key = div.casefold()
            if key:
                counts[key] = counts.get(key, 0) + 1
    return counts


def unit_usage() -> Dict[str, int]:
    """How many live items use each purchase unit, keyed by casefolded unit name."""
    counts: Dict[str, int] = {}
    for it in list_items():
        key = str(it.get("unit") or "").casefold()
        if key:
            counts[key] = counts.get(key, 0) + 1
    return counts
