"""Per-process memo for the suite's two expensive openpyxl calls, so asking for the same thing twice
costs once.

WHY THIS EXISTS. Most of a full run was two calls. `estimate_writer.fill_estimate` parses Kyle's
800 KB workbook, rewrites ~9 cells and zips it again (about 3 s), and the `/api/generate` route calls
it on every request whether or not the test reads the .xlsx. Then `load_workbook` re-parses what came
back (about 2 s) so a test can look at a few cells. Both are pure: same arguments, same bytes.
Dozens of tests asked for the very same fill, once per test, to look at something else in the .docx.

WHAT IT IS NOT. It is not a mock, and it never decides what a test asserts. The first caller of any
distinct input runs the REAL writer, and every later caller of that same input is handed the bytes
the real writer produced. Break the writer and the first build is wrong, so is every test that
shares it. Nothing is stubbed, nothing is skipped, and no assertion sees a different object.

WHEN IT STEPS ASIDE. The key is (the call's arguments) + (the identity of every attribute of
`estimate_writer`) + (the contents of every map and list in it that ships non-empty) + (the template
file's mtime and size). So the moment a test monkeypatches anything inside the writer
(`_fresh_template`, `load_workbook`, the template path) or edits one of its maps in place
(`HARD_BID_FLAG_CELLS.clear()` in test_no_hard_bid.py does exactly that) the key no longer matches
and the real code runs, exactly as it did before this file existed. The module's own caches start
empty, so they are not part of the key.
`TW_TEST_NO_MEMO=1` turns all of it off, for a run that wants every build real:

    TW_TEST_NO_MEMO=1 python -m pytest tests/ -q -n 4 --dist loadfile

THE ONE RULE FOR `workbook()`. What it returns is SHARED, so it is READ-ONLY: read cells, styles and
sheet protection; never assign to a cell, never `.save()` it, never rename or remove a sheet. A test
that wants to change a workbook loads its own with `load_workbook(io.BytesIO(data))`. (Reading
`ws["J50"]` materialises an empty cell on the shared sheet; that changes no value and no style, so
nothing another test can read.) `fill_estimate` itself returns `bytes`, which nobody can mutate.

Per process, never persisted, so under `pytest -n N --dist loadfile` each worker builds what its own
files need and no worker reads another's. Both caches are bounded: a loaded workbook is ~40 MB of
Python objects.
"""
from __future__ import annotations

import functools
import hashlib
import io
import json
import os
from collections import OrderedDict
from typing import Any

_DISABLED = os.environ.get("TW_TEST_NO_MEMO") == "1"
_FILL_ENTRIES = 48          # ~0.65 MB of bytes each
_WORKBOOK_ENTRIES = 4       # ~40 MB of objects each


def canon(*parts: Any) -> str:
    """A stable key for arguments: canonical JSON, falling back to repr for anything exotic.
    An object whose repr carries its identity just never hits, which is the safe direction."""
    return hashlib.sha1(
        json.dumps(parts, sort_keys=True, default=repr, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _lru_get(cache: OrderedDict, key: Any):
    value = cache.get(key)
    if value is not None:
        cache.move_to_end(key)
    return value


def _lru_put(cache: OrderedDict, key: Any, value: Any, limit: int) -> None:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > limit:
        cache.popitem(last=False)


def install_fill_memo() -> None:
    """Wrap `estimate_writer.fill_estimate` once per process. Called from conftest at import, so
    the route (`main` calls `estimate_writer.fill_estimate` by attribute) and every test that calls
    it directly get the same behaviour."""
    if _DISABLED:
        return
    import estimate_writer as ew
    real = ew.fill_estimate
    if getattr(real, "_tw_memoised", False):
        return
    built: OrderedDict = OrderedDict()
    # The module's constants (cell maps, lock maps, flag cells). Anything empty at install is a
    # cache (`_WB_CACHE`, `_TEMPLATE_BYTES` ...), which fills as a side effect of a build and must
    # not change the key.
    constants = [name for name, v in vars(ew).items()
                 if isinstance(v, (dict, list, set, tuple, frozenset)) and len(v) > 0
                 and not name.startswith("__")]

    @functools.wraps(real)
    def memoised(*args: Any, **kwargs: Any) -> bytes:
        try:
            st = ew.TEMPLATE_PATH.stat()
            g = vars(ew)
            key = (canon(args, kwargs), tuple(map(id, g.values())),
                   hash(tuple(repr(g.get(name)) for name in constants)),
                   st.st_mtime_ns, st.st_size)
        except Exception:                       # noqa: BLE001 — anything odd: just run the real one
            return real(*args, **kwargs)
        hit = _lru_get(built, key)
        if hit is not None:
            return hit
        out = real(*args, **kwargs)
        if isinstance(out, bytes):
            _lru_put(built, key, out, _FILL_ENTRIES)
        return out

    memoised._tw_memoised = True                # type: ignore[attr-defined]
    ew.fill_estimate = memoised


_WORKBOOKS: OrderedDict = OrderedDict()


def workbook(data: bytes, **load_kwargs: Any):
    """`openpyxl.load_workbook` on `data`, loaded once per distinct file. READ-ONLY (see above)."""
    from openpyxl import load_workbook
    if _DISABLED:
        return load_workbook(io.BytesIO(data), **load_kwargs)
    key = (hashlib.sha1(data).hexdigest(), canon(load_kwargs))
    wb = _lru_get(_WORKBOOKS, key)
    if wb is None:
        wb = load_workbook(io.BytesIO(data), **load_kwargs)
        _lru_put(_WORKBOOKS, key, wb, _WORKBOOK_ENTRIES)
    return wb
