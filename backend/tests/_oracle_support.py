"""The Python half of the workbook oracle: what Kyle's template says, as data.

THE ORACLE ITSELF RUNS IN NODE. The answer key is Kyle's estimate workbook evaluated by the same
HyperFormula the Estimate Review page runs (see docs/excel-parity-audit/engine.js and
backend/tests/js/workbook-oracle.js). HyperFormula is a JavaScript engine and is deliberately not
installed in CI, so CI never recomputes anything: it COMPARES the recorded answers
(backend/tests/fixtures/oracle/*.json) with the template and the code. This module is what the
comparison, and the oracle's own loader, share:

  template_spec()       the whole workbook in the shape the engine loads, read through the live
                        readers in backend/estimate_writer.py (read_sheet_grid, list_sheet_names,
                        read_named_expressions). There is no second openpyxl reader to drift from
                        what the Estimate Review page actually receives.
  template_hash()       one sha256 over the NORMALISED (sheet, address, formula-or-constant) tuples of
                        the priced sheets: the guard that says "re-run the oracle" when Kyle changes a
                        formula or a number, and stays quiet when the file is merely re-saved.
  profiles()            frontend/js/bid-profiles.js (TWBidProfiles) dumped to JSON by node.

Run as a script it serves the node oracle:
    python backend/tests/_oracle_support.py --spec <file>             the engine spec ('-' for stdout)
    python backend/tests/_oracle_support.py --hash <file>              the template hash of the sheets a JSON file lists
"""
from __future__ import annotations

import functools
import hashlib
import json
import pathlib
import subprocess
import sys
import warnings

TESTS = pathlib.Path(__file__).resolve().parent
BACKEND = TESTS.parent
REPO = BACKEND.parent
FRONTEND = REPO / "frontend"
ORACLE = TESTS / "fixtures" / "oracle"
PROFILES_JS = FRONTEND / "js" / "bid-profiles.js"
ORACLE_JS = TESTS / "js" / "workbook-oracle.js"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import estimate_writer as ew  # noqa: E402  (the path above has to be in place first)

TEMPLATE_PATH = ew.TEMPLATE_PATH


# ── the workbook, in the shape the engine loads ──────────────────────────────
def _grid(sheet: str, path: pathlib.Path) -> dict:
    """read_sheet_grid for one sheet, with openpyxl's "extension is not supported" chatter muted.
    parse_x14=False skips the dropdown parser: the cell list does not depend on it."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ew.read_sheet_grid(sheet, path=path, parse_x14=False)


def sheet_names(path: pathlib.Path = TEMPLATE_PATH) -> list:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ew.list_sheet_names(path=path)


def template_spec(path: pathlib.Path = TEMPLATE_PATH) -> dict:
    """{order, sheets: {name: {cells: [...]}}, names: [...]} for every sheet of the workbook.

    A formula cell is {addr, row, col, isFormula, formula, cached}: the formula text, which is what
    the engine computes, and the value Excel last saved in the file, which only the oracle's
    self-check reads. A constant is {addr, row, col, value}. Cells that carry nothing but styling
    are left out (read_sheet_grid emits them for the page's borders and fills)."""
    order = sheet_names(path)
    sheets = {}
    for name in order:
        cells = []
        for c in _grid(name, path)["cells"]:
            if c.get("isFormula"):
                cells.append({"addr": c["addr"], "row": c["row"], "col": c["col"], "isFormula": True,
                              "formula": c["formula"], "cached": c.get("value")})
            elif c.get("value") is not None:
                cells.append({"addr": c["addr"], "row": c["row"], "col": c["col"], "value": c["value"]})
        sheets[name] = {"cells": cells}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        names = ew.read_named_expressions() if pathlib.Path(path) == pathlib.Path(TEMPLATE_PATH) else []
    return {"order": order, "sheets": sheets, "names": names}


# ── the guard: a hash of what Kyle wrote, not of how the file was saved ──────
def _canon(value) -> str:
    """One stable text for a constant. Text is quoted, so the number 33 and the text "33" differ; a
    float that is a whole number reads as the integer, so 33 and 33.0 do not."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(str(value), ensure_ascii=False)


def normalised_cells(sheets, path: pathlib.Path = TEMPLATE_PATH) -> list:
    """[(sheet, addr, kind, text)] for every cell of `sheets` that holds a formula (kind "f", the
    formula text as stored) or a constant (kind "c"), in sheet order then row then column.

    NOT in it, on purpose: the value Excel cached for a formula, styles, widths, validations, the
    calc chain, shared-string order, the zip: everything a save in Excel can change without the
    workbook computing anything differently."""
    out = []
    for order, sheet in enumerate(sheets):
        for c in _grid(sheet, path)["cells"]:
            if c.get("isFormula"):
                out.append((order, c["row"], c["col"], sheet, c["addr"], "f", str(c["formula"])))
            elif c.get("value") is not None:
                out.append((order, c["row"], c["col"], sheet, c["addr"], "c", _canon(c["value"])))
    out.sort(key=lambda t: t[:3])
    return [t[3:] for t in out]


def hash_cells(cells) -> str:
    text = "\n".join("\t".join(t) for t in cells)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@functools.lru_cache(maxsize=8)
def _template_hash_cached(sheets: tuple, path: str, mtime: float):
    cells = normalised_cells(list(sheets), pathlib.Path(path))
    return hash_cells(cells), len(cells)


def template_hash(sheets, path: pathlib.Path = TEMPLATE_PATH):
    """(sha256 hex, number of cells hashed) for the normalised cells of `sheets`."""
    p = pathlib.Path(path)
    return _template_hash_cached(tuple(sheets), str(p), p.stat().st_mtime)


# ── the profiles, dumped by node ─────────────────────────────────────────────
@functools.lru_cache(maxsize=1)
def profiles() -> dict:
    """frontend/js/bid-profiles.js as plain data. Run by node, never read as text: the module is
    code that builds data, and what a test must see is what a page would get."""
    from _node import require_node
    node = require_node()
    proc = subprocess.run(
        [node, "-e", "process.stdout.write(JSON.stringify(require(process.argv[1])))", str(PROFILES_JS)],
        capture_output=True, text=True, encoding="utf-8", timeout=60)
    if proc.returncode != 0:
        raise RuntimeError("could not load bid-profiles.js under node:\n" + proc.stderr)
    return json.loads(proc.stdout)


# ── the recorded answers ─────────────────────────────────────────────────────
def load_meta() -> dict:
    return json.loads((ORACLE / "meta.json").read_text(encoding="utf-8"))


def load_golden(slug: str) -> dict:
    return json.loads((ORACLE / (slug + ".json")).read_text(encoding="utf-8"))


def _main(argv) -> int:
    if len(argv) == 3 and argv[1] == "--spec":
        text = json.dumps(template_spec(), separators=(",", ":"), default=str)
        if argv[2] == "-":
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stdout.write(text)
        else:
            pathlib.Path(argv[2]).write_text(text, encoding="utf-8")
        return 0
    if len(argv) == 3 and argv[1] == "--hash":
        # argv[2] is a file holding a JSON list of sheet names (names carry quote marks, which a
        # command line mangles); prints {"hash": ..., "cells": ...}
        digest, count = template_hash(json.loads(pathlib.Path(argv[2]).read_text(encoding="utf-8")))
        sys.stdout.write(json.dumps({"hash": digest, "cells": count}))
        return 0
    sys.stderr.write(__doc__ + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
