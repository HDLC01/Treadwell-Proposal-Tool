"""What the travel-sequence test files share: running tests/js/travel-sequence-harness.js, and saying what it found.

THE HARNESS walks every sequence of job-type switches and Sheets base changes on the REAL estimate page (js/polish-estimate.js over the real js/bid-model.js) and
judges the bid after every step against the one-drive rule. It prints ONE line of JSON:

    { mode, depth, runs, reopens, plain, reloads, reordered, violations: { CODE: count }, priced: { CODE: count }, pricedSamples: [...], samples: { CODE: [[label, detail], ...] }, crashes: [...] }

A clean walk has `violations == {}`, no crash, and a `runs` that proves the walk was not empty (a slice that quietly shrank would pass for the wrong reason).
`explain` turns a dirty one into the shortest sequences that broke each rule, which is what a person reads first.

EVERY REOPEN IN A WALK IS THE SERVER'S (round 6, item C2): the draft is a jsonb column and jsonb keeps no key order, so a reopened blob has every object's keys sorted by length and
then by bytes (tests/js/_jsonb.js). `reloads` is how many reopens the walk made and `reordered` how many of them brought the bid's sheets back in another order than they were saved in;
`run` refuses a walk that made none that moved (a walk that stopped re-keying, or whose bids hold nothing jsonb moves, cannot pass as one held to the server's order). `priced` counts the
divergences of a report that changed a PRICE, and `pricedSamples` keeps the twenty shortest of them with the prices on each side.
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
    "NIGHTS": "a far job's Lodging or Per Diem quantity is not the man-days of every base section, each counted with its own tab's divisor (a Gyp crew's hours over 10), on auto and marked as following, or a job under 70 miles has one filled, or a quantity the estimator typed (or cleared) is not exactly as they left it",
    "RELOAD_AGREES": "the same distance answer typed in the session that made a Sheets change (or the x, or Add Travel Labor) and typed after a jsonb reload of what it saved leaves different prices or Travel Labor rows",
    "ANSWER_OWNER": "the job says it has no drive (no_travel_labor) while the section that carries the job's travel holds a Travel Labor line: the flag is the carrier's answer, and nobody else's",
    "DEMOTED_KEEPS": "a base the Sheets panel's pick demoted to an option lost the Travel Labor line it held (it keeps its own, and the new carrier takes a copy)",
    "ANSWER_HELD": "after the x on the carrier's Travel Labor line (until Add Travel Labor on the carrier, or a Sheets action) a job-type switch or a crew typed left the job a drive: the answer is gone, or the carrier holds a line",
    "SESSION_AGREES": "a session that made its changes without reloading and a reload of what it saved hold other prices, other sheets or sheets in another order, other Travel Labor rows, or leave other ones after a distance answer",
    "CRASH": "the page threw",
}


def run(mode: str, depth: int = 0, frontend=FRONTEND, timeout: int = 900) -> dict:
    """The harness's report for one mode and depth, run against `frontend` (the repository's, unless a test has broken a copy of it).

    A walk that is not held to the server's key order is refused: it must have reopened at least once, and at least one reopen must have brought the sheets back in another order."""
    proc = run_node(HARNESS, frontend, mode, depth, timeout=timeout)
    assert proc.returncode == 0, "the sequence harness itself failed:\n" + proc.stderr[-1500:]
    got = last_json_line(proc.stdout)
    assert got.get("reloads", 0) > 0 and got.get("reordered", 0) > 0, \
        "the walk was not held to the server's key order: %r" % ({k: got.get(k) for k in ("reloads", "reordered")},)
    return got


def session_walked(got: dict) -> None:
    """The `session` walk was not cut short (a slice that quietly shrank would pass for the wrong reason): every one of its paths ran, each was judged against a reload, and the reopens
    were the server's key order, a good share of them bringing the sheets back in another order than they were saved in."""
    seen = {k: got.get(k) for k in ("runs", "sessions", "reloads", "reordered")}
    assert got["runs"] >= 270 and got["sessions"] >= 270 and got["reloads"] >= 1300 and got["reordered"] >= 700, "the walk was cut short: %r" % (seen,)


def explain(report: dict) -> str:
    """The rules a walk broke, how many times each, and the shortest sequences that broke them, one line each."""
    lines = []
    for code, count in sorted(report.get("violations", {}).items()):
        lines.append("%s x%d: %s" % (code, count, RULES.get(code, "?")))
        for label, detail in report.get("samples", {}).get(code, [])[:4]:
            lines.append("    %s  =>  %s" % (label, str(detail)[:220]))
    for item in report.get("pricedSamples", [])[:6]:
        lines.append("PRICES %s %s  %s  =>  session/before %s  /  reload/after %s" % (item["code"], item["label"], item["when"], item["left"], item["right"]))
    for label, why in report.get("crashes", [])[:3]:
        lines.append("CRASH %s: %s" % (label, why[:300]))
    return "\n".join(lines) or "(clean)"
