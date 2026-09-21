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

FOUR TABLES, AND NO LINES TABLE.

    library_items       one purchasable material, and the single source of truth for its price
    library_assemblies  a named system; its lines live in a `lines` JSONB column
    library_vendors     who Treadwell buys from — a list, so the Items tab can offer a dropdown
                        instead of a free-text box that grows three spellings of one supplier.
                        Managing the list is admin-only; picking from it is not.
    library_labor       the labor lines an estimator can add to a bid besides the built-in
                        ones — a rate typed once here instead of on every job. Travel is NOT
                        one of these rows and stays built in; see the section at the foot of
                        this file.

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

# THE WORK TYPES, IMPORTED FROM markup.py RATHER THAN RETYPED. markup.TABS is the closed
# list of the five sheet tabs a bid can sit on, and it is already the vocabulary the markup
# rules are filed under. A fourth hand-written copy is how a default ends up filed against a
# name nothing looks up -- which reads on screen exactly like a default that is simply off.
#
# `global` is deliberately NOT here: it is markup's word for a rule that applies to every
# tab, and a default already says that by naming no work types at all.
#
# COMBO IS NOT A WORK TYPE HERE EITHER. detect_work_type() returns epoxy/polish/combo for
# which PROPOSAL gets written; a combo job runs on the epoxy AND polish tabs, so it inherits
# both lists. A sixth entry would be a third list that has to agree with two others.
import markup

WORK_TYPES = markup.TABS

log = logging.getLogger(__name__)

ITEMS = "library_items"
ASSEMBLIES = "library_assemblies"
VENDORS = "library_vendors"
DIVISION_REFS = "library_divisions"
UNIT_REFS = "library_units"
LABOR = "library_labor"

# What a caller may set. Anything else in the payload is ignored rather than stored: an unknown
# key is a client bug, and persisting it makes the row shape unpredictable for later readers.
#
# THE SERVER-SET COLUMNS ARE DELIBERATELY ABSENT: `owner_email`, `updated_by`, `created_at`,
# `updated_at`, `cost_updated_at` and `deleted_at`. Authorship a client can type is authorship
# anybody can forge, and these rows are the answer to "who changed this price" — so who edited a
# row comes from the authenticated request, never from the body.
#
# These tuples DOCUMENT that contract; they do not enforce it. The enforcement is
# validate_item / validate_assembly, which build their output from an explicit key list and drop
# everything else — so an added column is safe by default and has to be opted IN to be writable.
ITEM_WRITABLE = ("name", "category", "divisions", "unit", "buy_qty", "unit_cost", "coverage",
                 "sku", "vendor", "notes", "default_work_types")
ASM_WRITABLE = ("name", "category", "description", "unit", "lines", "default_work_types")
VENDOR_WRITABLE = ("name", "notes")
REF_WRITABLE = ("name", "notes")
LABOR_WRITABLE = ("name", "rate", "unit", "guys_auto", "sort", "notes",
                  "default_work_types")

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

# What an ASSEMBLY is measured and priced per, and it is a different question from ITEM_UNITS.
# An item's unit is how you BUY it (a 5-gallon pail); an assembly's unit is what its coverage
# numbers divide into and what its price is quoted per.
#
# Two values, because those are the two things Treadwell measures: floor area in square feet and
# cove base / saw cuts / stripes in linear feet. Hanz, 2026-08-28: "Coverage per Unit — is there a
# way we can change it from SF and LF?"
#
# The field itself is not new — DEFAULT_ASM_UNIT has been persisted since the table was created and
# `polish-estimate.js` already reads it to stamp SF/LF onto a takeoff row. What was missing was a
# vocabulary and an editor: every assembly said "SF" because the create call hardcoded it, so the
# rail's "$1.497/SF" label was a guess that happened to be right.
#
# Offered, not enforced, exactly like DIVISIONS and ITEM_UNITS — a legacy row may hold "sqft" or
# "Each" and must stay loadable and correctable rather than uneditable.
ASM_UNITS = ("SF", "LF")

# What a DEFAULT LABOR LINE is billed by — and this is the ONE list in this module that
# is ENFORCED rather than merely offered.
#
# DIVISIONS, ITEM_UNITS and ASM_UNITS are all offered-not-enforced because they describe
# what somebody bought: a legacy row holds whatever was typed, and refusing to save it
# would make that row uneditable. This one is arithmetic. The estimate multiplies a rate
# by HOURS or by DAYS and has no third multiplier, so a labor line saying "weeks" would
# not price high or low — it would price as nothing, on a screen still showing the rate
# somebody typed.
#
# Lower-case because that is what `TWPolishBid.travelSeed()` already puts on an estimate's
# own labor row (`unit: "hours"`), and the two have to compare equal at the seam.
LABOR_UNITS = ("hours", "days")
DEFAULT_LABOR_UNIT = "hours"

_MAX_TEXT = 200
_MAX_NOTES = 4000
_MAX_LINES = 60                 # a system with 60 coats is a mistake, not a system
_MAX_UNIT_COST = 1e7            # $10M for one gallon is a typo
_MAX_COVERAGE = 1e6             # SF covered by one unit
_MAX_BUY_QTY = 1e5              # a 100,000-unit pack is a typo, not a pallet
_MAX_LABOR_RATE = 1e5           # $100,000 an hour is a typo (numeric(10,2) holds it)
_MAX_SORT = 10000               # a position in a short list, not a quantity


class ValidationError(ValueError):
    """A caller-fixable problem. The message is shown to the user, so it says what to do."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _actor(email: Optional[str]) -> Optional[str]:
    """The stored form of the person behind a write: lower-cased and trimmed, or None.

    One helper for both authorship columns so `owner_email` and `updated_by` are always
    comparable — the Items tab puts them side by side, and "Kyle@wetreadwell.com" created it /
    "kyle@wetreadwell.com" edited it would read as two different people.

    None when we cannot name them. That is a real state (an unauthenticated internal call) and it
    is stored as NULL rather than papered over, because the tab shows an unknown editor as "—" and
    a guess is worse than a dash."""
    return (email or "").strip().lower() or None


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


def _coerce_work_types(raw: Any) -> List[str]:
    """Which work types a default belongs to. EMPTY MEANS EVERY ONE.

    That is not a shortcut, it is what keeps this backwards compatible: every row that existed
    before this column did comes back [] and therefore still applies everywhere, exactly as it
    did when `favorite` was the whole story. No data migration, and no day where somebody's
    defaults quietly stop appearing because a column arrived empty.

    REFUSED, NOT DROPPED, for a name off the list -- unlike divisions, which are offered rather
    than enforced because legacy rows hold whatever somebody typed. Nothing legacy exists here,
    and a work type nothing looks up is a default that silently never applies: on screen that is
    indistinguishable from one that is simply switched off, which is the worst way for a
    pricing default to fail. markup.py refuses an off-list layout for the same reason.

    Order is not preserved and duplicates collapse: this is a set of tabs, and "epoxy, epoxy,
    polish" is the same answer as "epoxy, polish".
    """
    values: List[str] = []
    if isinstance(raw, (list, tuple)):
        values = list(raw)
    elif isinstance(raw, str) and raw.strip().startswith("["):
        try:
            parsed = json.loads(raw)
            values = parsed if isinstance(parsed, list) else []
        except (TypeError, ValueError):
            values = []
    elif raw not in (None, ""):
        values = [raw]
    seen: List[str] = []
    for v in values:
        text = str(v).strip().lower()
        if not text:
            continue
        if text not in WORK_TYPES:
            raise ValidationError(
                "%r is not a work type. Pick from: %s." % (text, ", ".join(WORK_TYPES)))
        if text not in seen:
            seen.append(text)
    return [t for t in WORK_TYPES if t in seen]


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

    # Shared/team-wide, not per-user: this is one library everybody reads from, so a starred
    # item reads starred for whoever opens the tab next, the same way an edited cost or a
    # renamed division already does. Coerced rather than validated -- any truthy/falsy value
    # in means exactly what it says, and there is no invalid value to reject.
    if "favorite" in payload or not partial:
        out["favorite"] = bool(payload.get("favorite"))
    if "default_work_types" in payload:
        out["default_work_types"] = _coerce_work_types(payload.get("default_work_types"))

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
        # A row written before this column existed has never been starred by anybody -- reads
        # False, same read-shaping every other column added to this table already gets.
        "favorite": bool(row.get("favorite")),
        "default_work_types": _coerce_work_types(row.get("default_work_types")),
        "owner_email": row.get("owner_email") or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        # WHO last changed the row, beside `owner_email`'s who first made it — Hanz, 2026-09-04:
        # "in the items tab we must put the name of who created it and who edited it".
        #
        # Read-shaped like buy_qty, and always present in the response even when the column is
        # absent from the row: every row typed before this existed was edited by somebody we
        # cannot name, so it reads back empty and the tab shows "—". Not backfilled to the
        # creator, which would have the row claim an edit that never happened.
        "updated_by": row.get("updated_by") or "",
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


def _item_key(name: Any) -> str:
    """The comparison form of a material name: "is this the same thing, typed differently".

    Case-folded with every non-alphanumeric character dropped, so "Concrete bar", "concretebar"
    and "Concrete-Bar" are one name. That pair is the specific gap Hanz hit: the on-screen hint
    (similarNames in library.js) is a bidirectional SUBSTRING match, and neither of those strings
    contains the other, so it stayed silent on the clearest duplicate there is.

    PLURALS ARE NOT FOLDED, and that is a decision rather than an omission. A trailing "s" is a
    real distinction in product names, and this check BLOCKS — refusing a name that is genuinely
    different is worse than letting a near-duplicate through, because the near-duplicate still
    gets the on-screen hint while a false block leaves the estimator unable to enter the material
    they have in front of them, with no way round it."""
    return "".join(ch for ch in str(name or "").casefold() if ch.isalnum())


def _match_key(name: Any) -> str:
    """`_item_key`, except that a name with no alphanumerics left still compares as itself.

    "---" normalises to "" under _item_key, and the empty key used to mean "nothing to compare,
    let it through" — so "---" was the one name that could be entered as many times as you liked,
    and validate_item accepts it because _clean_text leaves it non-empty. When the key comes out
    empty, fall back to the cleaned text: for those names the punctuation IS the name, and it is
    the only thing left that tells two of them apart.

    The \\x00 prefix keeps the two families of key from ever meeting. Without it a fallback key
    could in principle equal a real one and refuse an unrelated material, which is the expensive
    direction of a check that BLOCKS (see _item_key)."""
    key = _item_key(name)
    if key:
        return key
    text = _clean_text(name).casefold()
    return "\x00" + text if text else ""


def _clashing_item(name: Any, *, ignore_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """An existing live material whose name matches once case, spacing and punctuation are ignored.

    Compared in Python rather than with an `ilike` filter, for the reason _clashing_vendor gives
    in full: product names carry commas and parentheses, and those are PostgREST filter syntax.

    WHY THIS BLOCKS NOW, WHEN THE OLD CHECK DELIBERATELY DID NOT. similarNames was a hint on
    purpose, and its docstring gave the reason: "the same product legitimately appears twice at
    different coverages". THAT REASON EXPIRED when coverage left the Items tab — coverage is a
    property of an assembly LINE now, which test_coverage_left_the_items_tab pins. Two materials
    with one name no longer have anything to distinguish them, so Hanz's "dont allow" does not
    overrule his earlier "make it a hint"; the ground moved under it.

    A NAME MADE ENTIRELY OF PUNCTUATION still has to clash with itself — see _match_key."""
    target = _match_key(name)
    if not target:
        return None
    for it in list_items():
        if it.get("id") != ignore_id and _match_key(it.get("name")) == target:
            return it
    return None


def create_item(payload: Dict[str, Any], owner_email: Optional[str]) -> Dict[str, Any]:
    row = validate_item(payload)
    clash = _clashing_item(row.get("name"))
    if clash:
        raise ValidationError("\"%s\" is already in the library." % clash["name"])
    row["id"] = str(uuid.uuid4())
    row["owner_email"] = _actor(owner_email)
    # The create IS the row's first write, and `updated_at` is stamped on it below. So
    # `updated_by` names the same person, because two columns describing one write must not
    # disagree — a fresh row reading "changed just now, by nobody" looks like a bug in the tab.
    # NULL therefore means one thing only: this row predates the column.
    row["updated_by"] = row["owner_email"]
    row["created_at"] = row["updated_at"] = _now_iso()
    sb = get_client()
    sb.table(ITEMS).insert(row).execute()
    return _shape_item(row)


def update_item(item_id: str, payload: Dict[str, Any],
                editor_email: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Patch one material. `editor_email` is who the row will say last changed it.

    It comes from the authenticated request (`_user_email` at the route), never from the payload —
    see ITEM_WRITABLE. Optional because a script or an import is not an identity, and those write
    NULL: an edit by somebody we cannot name must not leave the PREVIOUS editor's name on the row,
    which would attribute a change to a person who did not make it."""
    patch = validate_item(payload, partial=True)
    if not patch:
        # Nothing changed, so nobody edited it — authorship is left exactly as it was rather than
        # reassigned by a PATCH that did nothing (the debounced save re-sends fields routinely).
        return get_item(item_id)
    patch["updated_at"] = _now_iso()
    patch["updated_by"] = _actor(editor_email)
    sb = get_client()
    cur = (sb.table(ITEMS).select("id,unit_cost")
           .eq("id", item_id).is_("deleted_at", "null").limit(1).execute())
    rows = cur.data or []
    if not rows:
        return None
    # Checked AFTER the row is known to exist, so renaming something already deleted stays a 404
    # rather than becoming a confusing 400 about a name clash.
    if "name" in patch:
        clash = _clashing_item(patch["name"], ignore_id=item_id)
        if clash:
            raise ValidationError("\"%s\" is already in the library." % clash["name"])
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
    editor unusable, so an empty line is simply not stored.

    THE CAP IS THE EXCEPTION, and it changed on 2026-08-28. This used to take `raw[:_MAX_LINES]`
    silently, which is the right posture for a hostile or buggy 500-line payload and the wrong one
    for the bulk picker Will asked for: a deliberate add of 40 onto an assembly holding 30 lost ten
    materials under a 200 OK, with nothing anywhere to say so. A count is not a malformed line — the
    caller knows exactly how many it sent — so an over-cap array is refused and named.

    The truncation stays as the shape defence behind it. The browser guards first
    (`bulkAddRoom` in library.js) so the button can explain itself while there is still something to
    change; this is what makes the rule true rather than merely displayed."""
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise ValidationError("Those lines aren't in a shape we can read.")
    if len(raw) > _MAX_LINES:
        raise ValidationError(
            "An assembly holds at most %d lines; that save had %d. Remove some and try again."
            % (_MAX_LINES, len(raw)))
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
        # Canonicalised against ASM_UNITS so "lf" typed anywhere becomes "LF" — the Polish beta
        # matches this value case-sensitively (`polish-estimate.js` compares an upper-cased copy
        # against "SF"/"LF"), so a lower-case row would silently fail to stamp a takeoff row's unit.
        out["unit"] = _canonical(_clean_text(payload.get("unit"), 24), ASM_UNITS) \
            or DEFAULT_ASM_UNIT

    for col, limit in (("category", _MAX_TEXT), ("description", _MAX_NOTES)):
        if col in payload or not partial:
            out[col] = _clean_text(payload.get(col), limit) or None

    if "lines" in payload or not partial:
        out["lines"] = _clean_lines(payload.get("lines"))

    # Same shared/team-wide flag the items table carries -- see validate_item's note.
    if "favorite" in payload or not partial:
        out["favorite"] = bool(payload.get("favorite"))
    if "default_work_types" in payload:
        out["default_work_types"] = _coerce_work_types(payload.get("default_work_types"))

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
        "favorite": bool(row.get("favorite")),
        "default_work_types": _coerce_work_types(row.get("default_work_types")),
        "owner_email": row.get("owner_email") or "",
        # Who last changed it, on the same terms as an item's — including a LINE change, which is
        # the edit that actually happens here. See _shape_item for why an absent column reads
        # empty rather than as the creator.
        "updated_by": row.get("updated_by") or "",
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
    row["owner_email"] = _actor(owner_email)
    row["updated_by"] = row["owner_email"]      # the create is the first write; see create_item
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


def update_assembly(asm_id: str, payload: Dict[str, Any],
                    editor_email: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Patch one assembly. `expected_updated_at`, when given, must match what is stored.

    `editor_email` is who the row will say last changed it, on the same terms as update_item's.
    A LINE edit comes through here too — it PATCHes the whole `lines` array — so changing a
    coverage or adding a coat is an edit and is stamped as one."""
    expected = payload.get("expected_updated_at") if isinstance(payload, dict) else None
    patch = validate_assembly(payload, partial=True)
    if not patch:
        return get_assembly(asm_id)
    patch["updated_at"] = _now_iso()
    patch["updated_by"] = _actor(editor_email)
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


# ── default labor lines ───────────────────────────────────────────────────────
# The labor rows the Defaults tab offers an estimator BESIDE the ones the estimate builds in —
# "Mobilization", "Night shift", a second crew rate — typed once here instead of into every bid.
#
# TRAVEL IS NOT A ROW IN THIS TABLE, is not migrated into it, and must not be written into it by
# anything. It stays `TWPolishBid.travelSeed()` in frontend/js/polish-bid-core.js and keeps
# rendering as "Built in" with no Edit and no Remove; a row here is an ADDITION beside it. The two
# shapes differ on purpose and the names differ with them — an estimate's labor row calls it
# `label` and carries the guys/days somebody typed for THAT job, while this table calls it `name`
# and carries only what is the same on every job. The mapping between the two lives in ONE place
# on the frontend, for the reason travelSeed's own comment records: two copies of it drifted
# within a day.
#
# THE TABLE MAY NOT EXIST, and that is the case this section is mostly written for. It was applied
# to the staging Postgres on 2026-09-17; production does not have it yet, by Hanz's decision that
# this ships staging first. So the READ degrades to "no custom labor lines" instead of raising —
# see list_labor — which is both the truth on a box where nobody has added one and the difference
# between a Library page that loads and a Library page that 500s over a section of a tab that
# mostly shows something else. The WRITES deliberately do NOT degrade; see create_labor.
def validate_labor(payload: Dict[str, Any], *, partial: bool = False) -> Dict[str, Any]:
    """Shape and check a labor payload; returns only the columns we intend to write.

    Same contract as validate_item and validate_ref: unknown keys are dropped rather than stored,
    and `partial=True` touches only the fields the caller actually named, so a debounced
    one-field PATCH cannot blank the rest of the row."""
    if not isinstance(payload, dict):
        raise ValidationError("Nothing to save.")

    out: Dict[str, Any] = {}

    if "name" in payload or not partial:
        name = _clean_text(payload.get("name"))
        if not name:
            raise ValidationError("Give the labor line a name so it can be found later.")
        out["name"] = name

    if "rate" in payload or not partial:
        # NOT NULLABLE, unlike an item's `unit_cost`. A blank rate means zero and the row says so
        # on screen; storing it as "not set" would let a line price a bid at nothing while looking
        # complete. `_number` is what refuses the negative, the NaN and the non-number, with the
        # readable message every other field in this module already uses.
        rate = _number(payload.get("rate"), field="A rate", maximum=_MAX_LABOR_RATE)
        out["rate"] = 0.0 if rate is None else rate

    if "unit" in payload or not partial:
        # The one CLOSED list here — see LABOR_UNITS for why this one is enforced when the others
        # are not. Case is folded first, so "Hours" saves rather than being refused for its shift
        # key; blank means the column default rather than an error, because a client clearing a
        # field is asking for the default, not proposing a third unit.
        unit = _canonical(_clean_text(payload.get("unit"), 24), LABOR_UNITS) or DEFAULT_LABOR_UNIT
        if unit not in LABOR_UNITS:
            raise ValidationError(
                "A labor line is billed by hours or by days — \"%s\" is neither." % unit)
        out["unit"] = unit

    if "guys_auto" in payload or not partial:
        # Coerced, not validated: any truthy/falsy value means exactly what it says and there is
        # no invalid value to reject. Same posture as an item's `favorite`.
        out["guys_auto"] = bool(payload.get("guys_auto"))

    if "sort" in payload or not partial:
        # A position, so a whole number. `_number` already refuses a negative and a NaN, and the
        # int() is what keeps a dragged "2.5" from becoming a fractional position the column
        # cannot hold.
        pos = _number(payload.get("sort"), field="Position", maximum=_MAX_SORT)
        out["sort"] = int(pos) if pos is not None else 0

    if "notes" in payload or not partial:
        out["notes"] = _clean_text(payload.get("notes"), _MAX_NOTES) or None

    if "default_work_types" in payload:
        out["default_work_types"] = _coerce_work_types(payload.get("default_work_types"))
    return out


def _shape_labor(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row.get("id"),
        "name": row.get("name") or "Untitled",
        # A float, not a string: the estimate multiplies by it. PostgREST returns numeric(10,2) as
        # a string, so the coercion happens here rather than in every caller — the same reason
        # _shape_item coerces unit_cost.
        "rate": _as_float(row.get("rate")) or 0.0,
        "unit": row.get("unit") or DEFAULT_LABOR_UNIT,
        "guys_auto": bool(row.get("guys_auto")),
        "default_work_types": _coerce_work_types(row.get("default_work_types")),
        "sort": int(_as_float(row.get("sort")) or 0),
        "notes": row.get("notes") or "",
        "owner_email": row.get("owner_email") or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _labor_order(row: Dict[str, Any]) -> tuple:
    """`sort` then `name`, which is the order the contract promises every reader.

    Case-folded on the name so "night shift" and "Night Shift" do not sit either side of
    "Overtime" purely because of a capital letter."""
    return (row.get("sort") or 0, str(row.get("name") or "").casefold())


def list_labor() -> List[Dict[str, Any]]:
    """Every live custom labor line, sorted by `sort` then `name`. NEVER RAISES.

    A missing `library_labor` reads as "no custom labor lines". That is the honest answer on
    production until Hanz promotes the table, and on any box where the DDL has not run — and the
    alternative is a Library page that 500s on load over a feature nobody there has used yet. It
    is the call `calendar_events.list_events()` already makes for the same reason: a broken read
    of one section must not take down a page that mostly shows something else.

    Deliberately broad, because "the table is absent" reaches Python as an ordinary APIError from
    PostgREST (PGRST205) and an unconfigured store reaches it as something else again; the caller
    can do nothing useful with either, and both mean the same thing to the page.

    Sorted HERE as well as in the query: the query's ORDER BY is what the database does, and this
    is what the contract says — a reader should not have to trust that those two agree."""
    try:
        sb = get_client()
        res = (sb.table(LABOR).select("*")
               .is_("deleted_at", "null")
               .order("sort")
               .limit(500).execute())
        rows = [_shape_labor(r) for r in (res.data or [])]
    except Exception as exc:  # noqa: BLE001
        log.warning("library_labor unreadable (table not promoted yet?): %s", exc)
        return []
    return sorted(rows, key=_labor_order)


def get_labor(labor_id: str) -> Optional[Dict[str, Any]]:
    sb = get_client()
    res = (sb.table(LABOR).select("*")
           .eq("id", labor_id).is_("deleted_at", "null").limit(1).execute())
    rows = res.data or []
    return _shape_labor(rows[0]) if rows else None


def create_labor(payload: Dict[str, Any], owner_email: Optional[str]) -> Dict[str, Any]:
    """Add a custom labor line.

    DOES NOT DEGRADE when the table is missing, and the asymmetry with list_labor is the whole
    point of both. A read of a table that is not there is honestly empty; a WRITE that quietly
    does nothing tells an admin they saved a rate they did not save, and they find out when a bid
    is short. So this one fails loudly.

    A DUPLICATE NAME IS ALLOWED, unlike a vendor or a division. Those lists exist to stop one
    supplier having three spellings. This one is a list of things to do, and two lines both called
    "Mobilization" at different rates is a real thing to want on a job with two crews — the DDL's
    index on the live name is not unique, so the store agrees."""
    row = validate_labor(payload)
    row["id"] = str(uuid.uuid4())
    row["owner_email"] = _actor(owner_email)
    row["created_at"] = row["updated_at"] = _now_iso()
    sb = get_client()
    sb.table(LABOR).insert(row).execute()
    # Read back rather than answering with the dict we just built. `rate` is numeric(10,2), so
    # a figure typed with more precision is rounded BY THE STORE — and a create that replies
    # with the number it wished for would show a rate that silently changes on the next reload.
    # update_labor already returns the stored row; this is create agreeing with it rather than
    # a new idea. The fallback covers a store that answers a read differently from a write.
    return get_labor(row["id"]) or _shape_labor(row)


def update_labor(labor_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Patch one labor line. Returns None when it is gone, so the caller can 404 rather than
    reporting a successful write to nothing — the row may have been removed in another tab."""
    patch = validate_labor(payload, partial=True)
    if not patch:
        return get_labor(labor_id)
    sb = get_client()
    cur = (sb.table(LABOR).select("id")
           .eq("id", labor_id).is_("deleted_at", "null").limit(1).execute())
    if not (cur.data or []):
        return None
    patch["updated_at"] = _now_iso()
    sb.table(LABOR).update(patch).eq("id", labor_id).execute()
    return get_labor(labor_id)


def delete_labor(labor_id: str) -> bool:
    """Soft-delete, as everywhere else in this module: `deleted_at` hides the row.

    A rate somebody typed by hand is reference data, and an estimate that already used this line
    carries its own copy of the number — so removing it from the list must not, and does not,
    reach back into a bid that was built with it."""
    sb = get_client()
    cur = (sb.table(LABOR).select("id")
           .eq("id", labor_id).is_("deleted_at", "null").limit(1).execute())
    if not (cur.data or []):
        return False
    sb.table(LABOR).update({"deleted_at": _now_iso()}).eq("id", labor_id).execute()
    return True
