"""Item categories: the headings a work type's materials are grouped under on the v2 estimate.

Hanz, 2026-10-27: "For the Items we must have another column which is category. The Categories will
be set in the Administration tab, so for example for epoxy we have Patch, Epoxy Liquids, Extras,
Cove, just like the sheet. Then we also need to separate these categories in the Estimates."

Kyle's sheet already has these headings: the Epoxy tab's "MATERIAL - Patch", "MATERIAL - Epoxy
Liquids", "MATERIAL - Extras", "MATERIAL - Cove", and the Polish tab's "MATERIAL - Patch",
"MATERIAL - Floor", "MATERIAL - Dye", "MATERIAL - Joint Filler". They are the seed.

ONE ORDERED LIST PER WORK TYPE, because the headings differ by sheet and so does their order: Patch is
first on both, but Epoxy has no Floor and Polish has no Cove. The work types are markup.TABS, the
closed vocabulary every other per-work-type setting in this tool is filed under.

A CATEGORY HAS AN ID AS WELL AS A NAME, and that is the whole design. A material stores the ID of its
category per work type (library_items.material_categories, {"epoxy": "epoxy-patch"}), never the
name. So:
  * RENAMING a category renames it for every material that uses it, with no write to any material:
    the material still points at the same id, and the id now reads "Patch and prep".
  * REMOVING a category leaves its materials UNCATEGORISED, also with no write: their id no longer
    resolves, and the estimate files them under "Other". Adding a category of the same name later
    mints a NEW id, so a removal is not silently undone by a re-add.
A cascade over library_items would be a multi-row write that can half-fail; a reference that is
resolved on read cannot.

SAME SHAPE AND POSTURE AS nav_access.py and special_permissions.py: a small JSON file on the data
volume, written through the one atomic writer (atomic_json). An ABSENT file reads as the seed (Kyle's
sheet headings), so a fresh box has categories without anybody typing them. A GARBLED file also reads
as the seed, with a warning: unlike a grant, a category list widens nothing, so the safe direction is
"what the sheet says", not "nothing". A failed WRITE raises (ItemCategoriesWriteError): an admin who
thinks they renamed a heading and did not has no other way to find out.

Recovery, should the file ever need resetting to the sheet's headings:

    docker exec treadwell-proposal-tool rm -f /app/data/item_categories.json
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import atomic_json
import markup

log = logging.getLogger("treadwell.item_categories")

_DATA_DIR = Path(os.environ.get("DRAFTS_DB_PATH", "/app/data/drafts.db")).parent
_FILE = _DATA_DIR / "item_categories.json"

_LOCK = threading.Lock()
_VERSION = 1

# In the order Hanz listed them ("Epoxy, Polish, Gyp, Seal, Leveling"), which is the order the Admin
# card draws them. The SET is markup.TABS; test_item_categories.py holds the two to each other.
WORK_TYPES = ("epoxy", "polish", "gyp", "seal", "leveling")
assert set(WORK_TYPES) == set(markup.TABS), "item_categories.WORK_TYPES drifted from markup.TABS"

LABELS = {"epoxy": "Epoxy", "polish": "Polish", "gyp": "Gyp", "seal": "Seal", "leveling": "Leveling"}

# Kyle's sheet headings, with stable ids so a material filed under one before anybody edited the list
# still finds it after the file is first saved.
SEED: Dict[str, List[Dict[str, str]]] = {
    "epoxy": [{"id": "epoxy-patch", "name": "Patch"},
              {"id": "epoxy-liquids", "name": "Epoxy Liquids"},
              {"id": "epoxy-extras", "name": "Extras"},
              {"id": "epoxy-cove", "name": "Cove"}],
    "polish": [{"id": "polish-patch", "name": "Patch"},
               {"id": "polish-floor", "name": "Floor"},
               {"id": "polish-dye", "name": "Dye"},
               {"id": "polish-joint-filler", "name": "Joint Filler"}],
    "gyp": [], "seal": [], "leveling": [],
}

MAX_NAME = 60
MAX_PER_WORK_TYPE = 40
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")


class ItemCategoriesWriteError(RuntimeError):
    """The list could not be persisted, so nothing may act as though it was."""


def _clean_name(value: Any) -> str:
    return " ".join(str(value if value is not None else "").split())[:MAX_NAME]


def _mint_id(wt: str, taken: set) -> str:
    while True:
        cid = "%s-%s" % (wt, uuid.uuid4().hex[:8])
        if cid not in taken:
            return cid


def sanitize(work_types: Any) -> Dict[str, List[Dict[str, str]]]:
    """The one authority on what the store may hold. Never raises; drops what it cannot use.

    Every work type is present (an empty list when it has none). An entry is {id, name} or a bare
    name; a blank name is dropped, a second entry with the same name (case and spacing ignored) in
    one work type is dropped, and an entry with no usable id - or an id already used in this store -
    is given a fresh one. Order is kept: it is the order the estimate draws the headings in.
    """
    src = work_types if isinstance(work_types, dict) else {}
    out: Dict[str, List[Dict[str, str]]] = {}
    taken: set = set()
    for wt in WORK_TYPES:
        rows = src.get(wt)
        rows = rows if isinstance(rows, list) else []
        seen_names: set = set()
        kept: List[Dict[str, str]] = []
        for row in rows:
            if isinstance(row, str):
                row = {"name": row}
            if not isinstance(row, dict):
                continue
            name = _clean_name(row.get("name"))
            key = name.casefold()
            if not name or key in seen_names:
                continue
            cid = str(row.get("id") or "").strip().lower()
            if not ID_RE.match(cid) or cid in taken:
                cid = _mint_id(wt, taken)
            taken.add(cid)
            seen_names.add(key)
            kept.append({"id": cid, "name": name})
            if len(kept) >= MAX_PER_WORK_TYPE:
                break
        out[wt] = kept
    return out


def _seed() -> Dict[str, Any]:
    return {"version": _VERSION, "work_types": sanitize(SEED), "updated_at": None,
            "updated_by": None, "seeded": True}


def _read() -> Dict[str, Any]:
    if not _FILE.is_file():
        return _seed()
    try:
        raw = json.loads(_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("work_types"), dict):
            raise ValueError("not a categories store")
        return {"version": _VERSION, "work_types": sanitize(raw.get("work_types")),
                "updated_at": raw.get("updated_at") or None,
                "updated_by": raw.get("updated_by") or None, "seeded": False}
    except Exception as exc:  # noqa: BLE001 - a bad file falls back to the sheet's headings
        log.warning("item categories unreadable (%s); using the sheet's headings", exc)
        return _seed()


def load() -> Dict[str, Any]:
    """The whole store. Always every work type; the sheet's headings when nothing has been saved."""
    with _LOCK:
        return _read()


def save(work_types: Any, by: str = "") -> Dict[str, Any]:
    """Persist the lists and return the stored copy. Raises ItemCategoriesWriteError."""
    clean = sanitize(work_types)
    out = {"version": _VERSION, "work_types": clean,
           "updated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "updated_by": (by or "").strip() or None}
    with _LOCK:
        try:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            atomic_json.write_json(_FILE, out, make_parent=False)
        except Exception as exc:  # noqa: BLE001
            raise ItemCategoriesWriteError(str(exc)) from exc
    log.info("item categories set by %s", out["updated_by"] or "?")
    return dict(out, seeded=False)


def categories_for(work_type: str, store: Optional[Dict[str, Any]] = None) -> List[Dict[str, str]]:
    """The ordered list for one work type ([] for an unknown one)."""
    st = store if store is not None else load()
    return list((st.get("work_types") or {}).get(str(work_type or "").lower(), []))


def name_of(work_type: str, category_id: Any,
            store: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """The current name of a category id in a work type, or None when it is not (or no longer) there."""
    for row in categories_for(work_type, store):
        if row["id"] == category_id:
            return row["name"]
    return None


def coerce_item_categories(raw: Any) -> Dict[str, str]:
    """A material's {work type: category id} map, as library.validate_item stores it.

    Unknown work types, blank values and anything that is not an id are dropped, so the stored map
    only ever holds keys a reader can look up. The id is NOT required to exist in the store today:
    a category removed between the page loading and the save reads back as uncategorised, which is
    what removing it means anyway.
    """
    out: Dict[str, str] = {}
    if not isinstance(raw, dict):
        return out
    for wt, cid in raw.items():
        key = str(wt or "").strip().lower()
        val = str(cid or "").strip().lower() if isinstance(cid, str) else ""
        if key in WORK_TYPES and val and ID_RE.match(val):
            out[key] = val
    return {wt: out[wt] for wt in WORK_TYPES if wt in out}


# Kyle's three divisions by the work type each is priced on. frontend/js/library.js DIVISION_WORK_TYPE is
# the page's copy, and test_item_categories_ui.py runs both over the same names.
DIVISION_WORK_TYPE = {"polished concrete": "polish", "epoxy": "epoxy", "gypsum underlayment": "gyp"}


def division_work_type(name: Any) -> str:
    """The work type a division is priced on, or "" when none answers to it.

    Kyle's three by name, then any work type whose label the division spells ("Seal", "Leveling")."""
    key = " ".join(str(name if name is not None else "").split()).lower()
    if key in DIVISION_WORK_TYPE:
        return DIVISION_WORK_TYPE[key]
    for wt in WORK_TYPES:
        if LABELS[wt].lower() == key:
            return wt
    return ""


def within_divisions(cats: Any, divisions: Any) -> Dict[str, str]:
    """A material's category map with every work type its divisions are not priced on taken out.

    Hanz, 2026-10-29: "Category and Division should always be tied together." A material keeps a
    heading only for a work type one of its divisions is priced on; no division, no category.
    """
    mine = {division_work_type(d) for d in (divisions or [])} - {""}
    return {wt: cid for wt, cid in coerce_item_categories(cats).items() if wt in mine}
