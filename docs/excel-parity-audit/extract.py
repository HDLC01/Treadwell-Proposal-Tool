"""Dump a real estimate workbook into the shape /api/sheet serves, for the parity audit.

Read-only. The Dropbox originals are never opened by this script — only the copies in this
folder. Emits one JSON per workbook: every sheet's cells (formula text preferred over the cached
value, as xl-core's loadSheet does), the defined names, and the list of cells worth comparing.

"Worth comparing" = every cell whose formula uses a rounding function, plus the headline totals.
Those are where HyperFormula and Excel can legitimately disagree; comparing all 17,000 formula
cells would bury the finding in noise.
"""
import json
import re
import sys
import pathlib

import openpyxl

ROUNDING = re.compile(r"\b(ROUNDUP|ROUNDDOWN|ROUND|CEILING|FLOOR|INT|TRUNC|MROUND)\s*\(", re.I)

# The figures a human actually reads off the estimate.
HEADLINE = {
    "Polish": ["D31", "D45", "D55", "D61", "D64", "D76", "D79", "D82", "C82", "B15", "D15"],
    "Epoxy":  ["D43", "D53", "D62", "D68", "D70", "D88", "D16"],
}


def dump(path: pathlib.Path, out: pathlib.Path) -> dict:
    wb = openpyxl.load_workbook(path, data_only=False)
    sheets, compare = {}, []

    for ws in wb.worksheets:
        cells = []
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if v is None:
                    continue
                is_f = isinstance(v, str) and v.startswith("=")
                # Dates arrive as datetime and are not JSON-serialisable. They never feed a
                # money formula here (bid date, drawings date), so an ISO string is enough for
                # the engine to hold something in the cell.
                if not is_f and hasattr(v, "isoformat"):
                    v = v.isoformat()
                cells.append({
                    "addr": c.coordinate, "row": c.row, "col": c.column,
                    "isFormula": is_f,
                    "formula": v if is_f else None,
                    "value": None if is_f else v,
                })
                if is_f and ROUNDING.search(v):
                    compare.append({"sheet": ws.title, "addr": c.coordinate, "why": "rounding"})
        sheets[ws.title] = {"cells": cells}

    for sheet, addrs in HEADLINE.items():
        if sheet in sheets:
            for a in addrs:
                compare.append({"sheet": sheet, "addr": a, "why": "headline"})

    # De-duplicate, keeping the first reason seen.
    seen, uniq = set(), []
    for c in compare:
        k = (c["sheet"], c["addr"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(c)

    names = []
    try:
        for name, defn in wb.defined_names.items():
            names.append({"name": name, "expression": "=" + str(defn.value).lstrip("=")})
    except Exception:
        pass

    payload = {"order": list(sheets.keys()), "sheets": sheets,
               "names": names, "compare": uniq}
    out.write_text(json.dumps(payload), encoding="utf-8")
    return {"sheets": len(sheets),
            "cells": sum(len(s["cells"]) for s in sheets.values()),
            "compare": len(uniq), "names": len(names)}


if __name__ == "__main__":
    here = pathlib.Path(__file__).parent
    for xl in sorted(here.glob("job*.xlsx")):
        info = dump(xl, here / (xl.stem + ".json"))
        print("%-10s sheets=%-3d cells=%-7d names=%-4d compare=%d"
              % (xl.stem, info["sheets"], info["cells"], info["names"], info["compare"]))
