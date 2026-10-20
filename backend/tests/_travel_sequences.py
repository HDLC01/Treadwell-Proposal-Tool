"""What the travel-sequence test files share: running tests/js/travel-sequence-harness.js, and saying what it found.

THE HARNESS walks every sequence of job-type switches and Sheets base changes on the REAL estimate page (js/polish-estimate.js over the real js/bid-model.js) and
judges the bid after every step against the one-drive rule. It prints ONE line of JSON:

    { mode, depth, runs, reopens, plain, violations: { CODE: count }, samples: { CODE: [[label, detail], ...] }, crashes: [...] }

A clean walk has `violations == {}`, no crash, and a `runs` that proves the walk was not empty (a slice that quietly shrank would pass for the wrong reason).
`explain` turns a dirty one into the shortest sequences that broke each rule, which is what a person reads first.
"""
from __future__ import annotations

import pathlib

from _golden_support import FRONTEND
from _node import last_json_line, run_node

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "travel-sequence-harness.js"
# What the page needs beside the two files under test (the same list test_polish_travel_switch.py copies for its own mutation runs).
PAGE_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js",
              "js/markup-core.js", "js/library-core.js", "js/library-picker.js", "js/work-types.js", "js/excel-math.js",
              "js/epoxy-takeoff.js", "js/gyp-takeoff.js", "js/seal-takeoff.js", "js/price-lines-core.js"]

RULES = {
    "ONE_DRIVE": "more than one priced Travel Labor row on the bases of the bid",
    "MAN_DAYS": "a Travel Labor row the tool filled is priced on the man-days",
    "FAR_CARRIER": "a far job's carrier has no Travel Labor row, or one that is not the crew's size x one round trip",
    "GYP_UNFILLED": "a Gyp carrier's Travel Labor row nobody touched was filled",
    "LOCAL": "a job under 70 miles (or with no distance) prices a Travel Labor row nobody touched",
    "OWNED": "what the estimator typed, cleared or switched off is not on the carrier as they left it (or was left on another section)",
    "STALE": "a Travel Labor row the distance filled is still on a section that does not carry the job's travel",
    "ONE_ROW": "a section holds two Travel Labor rows",
    "PLAIN_REOPEN": "a plain reopen armed a save, wrote something, or moved a row",
    "REOPEN_AGREES": "the price (or the rows) the draft saved is not what a plain reopen of it shows",
    "OPT_FOLLOWS": "after the miles were typed, an option's Travel Labor does not hold what the answer gives (the hours, its own crew, or the fill taken back whole under 70 miles)",
    "OPT_OWNED": "after the miles were typed, an option's switched-off row moved, or a box the estimator typed in or cleared on it changed",
    "CRASH": "the page threw",
}


def run(mode: str, depth: int = 0, frontend=FRONTEND, timeout: int = 900) -> dict:
    """The harness's report for one mode and depth, run against `frontend` (the repository's, unless a test has broken a copy of it)."""
    proc = run_node(HARNESS, frontend, mode, depth, timeout=timeout)
    assert proc.returncode == 0, "the sequence harness itself failed:\n" + proc.stderr[-1500:]
    return last_json_line(proc.stdout)


def explain(report: dict) -> str:
    """The rules a walk broke, how many times each, and the shortest sequences that broke them, one line each."""
    lines = []
    for code, count in sorted(report.get("violations", {}).items()):
        lines.append("%s x%d: %s" % (code, count, RULES.get(code, "?")))
        for label, detail in report.get("samples", {}).get(code, [])[:4]:
            lines.append("    %s  =>  %s" % (label, str(detail)[:220]))
    for label, why in report.get("crashes", [])[:3]:
        lines.append("CRASH %s: %s" % (label, why[:300]))
    return "\n".join(lines) or "(clean)"
