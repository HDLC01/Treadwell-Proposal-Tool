"""The seed script (backend/ops/seed_library_from_workbook.py) and the workbook it reads, loaded ONCE per process.

Reading the 12 MB template takes several seconds and planning from it a tenth of one, and four test modules want the
plan (the seed's own tests, the takeoff pins, the v2 proof and the page harness). Each pytest worker imports this
once. A test that edits a cell of the loaded workbook does it through `edited`, which puts the cell back.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = BACKEND / "ops" / "seed_library_from_workbook.py"


def load_script(path: pathlib.Path = SCRIPT, name: str = "seed_library_from_workbook"):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


seed = load_script()
SHEETS = seed.load()
PLAN = seed.make_plan(sheets=SHEETS)


def plan_json(tmp: pathlib.Path) -> pathlib.Path:
    """The plan as the seed script's --json prints it, in a file a node harness can read."""
    path = tmp / "plan.json"
    path.write_text(json.dumps(PLAN.as_dict(), sort_keys=True), encoding="utf-8")
    return path


class edited:
    """Change one cell of the loaded workbook for the length of a `with`, then put it back."""

    def __init__(self, sheet, kind, addr, value):
        self.cell = getattr(SHEETS[sheet], kind)[addr]
        self.value = value

    def __enter__(self):
        self.was = self.cell.value
        self.cell.value = self.value

    def __exit__(self, *exc):
        self.cell.value = self.was
