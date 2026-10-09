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
                        the priced sheets AND the workbook's defined names (the named ranges the page
                        registers in HyperFormula, such as Silica): the guard that says "re-run the
                        oracle" when Kyle changes a formula, a number or what a name points at, and
                        stays quiet when the file is merely re-saved.
  profiles()            frontend/js/bid-profiles.js (TWBidProfiles) dumped to JSON by node.
  integrity_problems()  the other half of the guard: the recorded answers are the files the oracle
                        wrote. meta.json holds a sha256 of every recorded sheet file and of the cell-map
                        data they were recorded from; this recomputes both. A golden edited by hand so
                        that it still adds up is caught here and nowhere else.

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
INTEGRITY_JS = TESTS / "js" / "oracle-integrity.js"
# The files in fixtures/oracle that are written by hand and checked by their own tests, so the oracle
# neither records nor hashes them. Every other *.json there is a recorded answer.
NOT_ANSWER_FILES = frozenset({"meta.json", "departures.json", "odd_rules.json"})

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import estimate_writer as ew  # noqa: E402  (the path above has to be in place first)

TEMPLATE_PATH = ew.TEMPLATE_PATH


# ── the workbook, in the shape the engine loads ──────────────────────────────
def _grid(sheet: str, path: pathlib.Path) -> dict:
    """read_sheet_grid for one sheet, with openpyxl's "extension is not supported" chatter muted.

    On the LIVE template this is the app's own call, dropdown parser included. read_sheet_grid keeps
    one cached result per (path, sheet, mtime) for the whole process, and parse_x14 is not part of
    that key, so a read without the parser would leave the Polish tab with no Yes/No pickers for
    every later reader in the same worker (test_taxable_flag_reaches_every_sheet failed exactly that
    way on the first full run). A copy has a key of its own and nothing else reads it, so it skips
    the parser: the cell list, which is all the oracle reads, does not depend on it."""
    live = pathlib.Path(path) == pathlib.Path(TEMPLATE_PATH)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ew.read_sheet_grid(sheet, path=path, parse_x14=live)


def sheet_names(path: pathlib.Path = TEMPLATE_PATH) -> list:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ew.list_sheet_names(path=path)


def named_expressions(path: pathlib.Path = TEMPLATE_PATH) -> list:
    """The workbook's defined names, [{name, expression, scope}], read by the function the page's
    names come from (estimate_writer.read_named_expressions) and not by a second reader.

    That function takes no path: it always opens the live template. For a copy (the tests edit
    copies of the template) the module's loader is pointed at the copy for the length of the call
    and put back afterwards, so the copy is read by exactly the code the page is served by."""
    path = pathlib.Path(path)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if path == pathlib.Path(TEMPLATE_PATH):
            return ew.read_named_expressions()
        real = ew._load_template
        copy = path

        def load_the_copy(*, data_only, path=None):          # the signature of _load_template
            return real(data_only=data_only, path=copy)

        ew._load_template = load_the_copy
        try:
            return ew.read_named_expressions()
        finally:
            ew._load_template = real


def sheet_scoped_names(path: pathlib.Path = TEMPLATE_PATH) -> list:
    """The defined names that belong to ONE sheet, [{name, expression, scope}] with `scope` the sheet's name.

    openpyxl keeps a workbook-wide name in `wb.defined_names` and a name scoped to a sheet (a `definedName` with a
    `localSheetId`) in that sheet's `ws.defined_names`. estimate_writer.read_named_expressions reads only the first, so the
    page registers no sheet-scoped name with HyperFormula, and a guard built on that function alone could not see one.
    Excel could: a sheet-scoped `Silica` shadows the workbook's own on that sheet, and a formula that says `Silica` keeps
    its text and changes its price. The guard hashes these too, with their scope, so such a name is a change to the
    answer key like any other. Read through the app's own loader, pointed at the copy when there is one."""
    path = pathlib.Path(path)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = ew._load_template(data_only=False, path=path)
    out = []
    for ws in wb.worksheets:
        for name, dn in ws.defined_names.items():
            expression = getattr(dn, "value", None) or getattr(dn, "attr_text", None)
            if not expression or str(name).startswith("_xlnm."):
                continue
            out.append({"name": str(name), "expression": expression if str(expression).startswith("=") else "=" + str(expression),
                        "scope": ws.title})
    return out


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
    return {"order": order, "sheets": sheets, "names": named_expressions(path)}


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


def normalised_names(path: pathlib.Path = TEMPLATE_PATH) -> list:
    """[(scope, name, "n", expression)] for every defined name the page registers in HyperFormula AND every name that
    belongs to one sheet (sheet_scoped_names, which the page does not register), sorted by scope and then name. `scope` is the sheet's name for a name that belongs to one sheet and "" for a
    workbook-wide one; `expression` is what it points at, as read_named_expressions returns it
    (`=Epoxy!$W$145` for Silica).

    WHY THEY ARE IN THE GUARD. A formula such as `IF($A$22=$R$189,Q28_40s,...,Silica)` is the same text
    whatever Silica means. Point Silica at another cell and Epoxy prices its aggregate differently while
    every cell of every tab hashes exactly as before. The names are part of the workbook, and the
    engine registers every one of them (meta.json: engine.namesRegistered), so a change to one is a
    change to the answer key.

    The order Excel writes them in is not part of what a name is, so they are sorted. The kind "n" cannot
    be mistaken for a cell's "f" or "c", so a name and a cell never produce the same line."""
    every = named_expressions(path) + sheet_scoped_names(path)
    out = sorted({(n.get("scope") or "", str(n["name"]), "n", str(n["expression"])) for n in every},
                 key=lambda t: (t[0], t[1], t[3]))
    return out


def hash_cells(cells) -> str:
    """sha256 of lines of (a, b, kind, text): the normalised cells, the defined names, or both."""
    text = "\n".join("\t".join(t) for t in cells)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@functools.lru_cache(maxsize=8)
def _template_hash_cached(sheets: tuple, path: str, mtime: float):
    cells = normalised_cells(list(sheets), pathlib.Path(path))
    names = normalised_names(pathlib.Path(path))
    return hash_cells(cells + names), len(cells), len(names)


def template_hash(sheets, path: pathlib.Path = TEMPLATE_PATH):
    """(sha256 hex, cells hashed, names hashed): one hash over the normalised cells of `sheets` followed by
    every defined name of the workbook."""
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


# ── the recorded answers are the files the oracle wrote ──────────────────────
def text_sha256(raw: bytes) -> str:
    """sha256 of a file's text with every CRLF read as LF.

    The recorded files are LF in git and CRLF in a Windows checkout (core.autocrlf), and the oracle compares them
    with the line endings fixed, so the hash has to be the same on both. Only "\\r\\n" is folded, exactly what
    backend/tests/js/oracle-integrity.js does (Path.read_text would also turn a lone "\\r" into "\\n", which node does
    not), and a byte-order mark is left in: a file that gained one is a changed file."""
    return hashlib.sha256(raw.decode("utf-8").replace("\r\n", "\n").encode("utf-8")).hexdigest()


def profiles_sha256(path: pathlib.Path = PROFILES_JS) -> str:
    """The hash of the cell-map data in bid-profiles.js that the oracle read to record its answers.

    Computed by node, by the module the oracle writes the recorded value with (oracle-integrity.js
    holds the one definition of which fields are hashed and how data becomes text), so the two sides
    cannot disagree about a number's spelling. Comments, and everything in the file the oracle does not
    read (`families`, `version`), are not part of it."""
    from _node import require_node
    node = require_node()
    proc = subprocess.run([node, str(INTEGRITY_JS), str(path)], capture_output=True, text=True,
                          encoding="utf-8", timeout=60)
    if proc.returncode != 0:
        raise RuntimeError("could not hash the cell maps of %s under node:\n%s" % (path, proc.stderr))
    return json.loads(proc.stdout)["profiles"]


def integrity_problems(meta: dict, directory: pathlib.Path = ORACLE, profiles_js: pathlib.Path = PROFILES_JS) -> list:
    """What is wrong with the recorded answers, as sentences. [] when every recorded file is byte for byte (line
    endings aside) the one the oracle wrote, and the cell maps are the ones it read.

    meta.json carries, under `integrity`, a sha256 of every recorded sheet file and of the cell-map data
    (written by the oracle when it regenerates). The other checks on the recorded answers are arithmetic: the
    total is the sum of its parts, every edge straddles. A recorded value edited by hand together with the figures
    that must add up to it (gp and total both raised by 1,000) passes every one of them. The hash is the only
    check that sees it, and it asks for the one honest remedy: run the oracle again."""
    block = meta.get("integrity")
    if not block or "files" not in block or "profiles" not in block:
        return ["meta.json has no `integrity` block, so nothing says the recorded files are the ones the oracle wrote"]
    problems = []
    directory = pathlib.Path(directory)
    recorded = block["files"]
    for name, want in sorted(recorded.items()):
        f = directory / name
        if not f.is_file():
            problems.append("%s is recorded in meta.json and is missing" % name)
            continue
        got = text_sha256(f.read_bytes())
        if got != want:
            problems.append("%s is not the file the oracle wrote (sha256 %s, recorded %s)" % (name, got[:12], want[:12]))
    for f in sorted(directory.glob("*.json")):
        if f.name not in NOT_ANSWER_FILES and f.name not in recorded:
            problems.append("%s is a recorded-answer file that meta.json holds no hash for" % f.name)
    got = profiles_sha256(profiles_js)
    if got != block["profiles"]["sha256"]:
        problems.append("the cell maps in %s are not the ones the answers were recorded from (sha256 %s, recorded %s)"
                        % (pathlib.Path(profiles_js).name, got[:12], block["profiles"]["sha256"][:12]))
    return problems


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
        # command line mangles); prints {"hash": ..., "cells": ..., "names": ...}
        digest, cells, names = template_hash(json.loads(pathlib.Path(argv[2]).read_text(encoding="utf-8")))
        sys.stdout.write(json.dumps({"hash": digest, "cells": cells, "names": names}))
        return 0
    sys.stderr.write(__doc__ + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
