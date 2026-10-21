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
    "DOUBLE": "a base section prices more than one Travel Labor row: a crew's drive priced twice (since round 7 a far Combo prices one drive per base crew, a single-base job one; it was ONE_DRIVE, one for all the bases together)",
    "MAN_DAYS": "a Travel Labor row the tool filled is priced on the man-days",
    "FAR_BASES": "on a far job a base has no Travel Labor row though neither the job nor the sheet said it has no drive, or holds one nobody touched that is not its own crew's size x its round trips (a Gyp base too, since round 7, and since round 7, part 4 a round trip for each mobilization on its Gyp card)",
    "LOCAL": "a job under 70 miles (or with no distance) prices a Travel Labor row nobody touched",
    "OWNED": "what the estimator typed, cleared or switched off was lost: it is no longer on the sheet it was said on, and did not go with the job's drive to the new base of a single-base job whose base moved (or stayed behind when it had to go)",
    "STALE": "a Travel Labor row the distance filled is still on a section that is neither a base nor an option (off)",
    "ONE_ROW": "a section holds two Travel Labor rows",
    "PLAIN_REOPEN": "a plain reopen armed a save, wrote something, or moved a row",
    "REOPEN_AGREES": "the price (or the rows) the draft saved is not what a plain reopen of it shows",
    "OPT_FOLLOWS": "after the miles were typed, an option's Travel Labor does not hold what the answer gives (the hours, its own crew, or the fill taken back whole under 70 miles)",
    "OPT_OWNED": "after the miles were typed, an option's switched-off row moved, or a box the estimator typed in or cleared on it changed",
    "NIGHTS": "a far job's Lodging or Per Diem quantity is not the man-days of every base section, each counted with its own tab's divisor (a Gyp crew's hours over 10), on auto and marked as following, or a job under 70 miles has one filled, or a quantity the estimator typed (or cleared) is not exactly as they left it",
    "RELOAD_AGREES": "the same distance answer typed in the session that made a Sheets change (or the x, or Add Travel Labor) and typed after a jsonb reload of what it saved leaves different prices or Travel Labor rows",
    "ANSWER_OWNER": "an answer is said over a line (the job's no_travel_labor while a base holds one, a sheet's sheet_no_travel_labor while it holds one), or was set by a step that may not set it (only the x on a single-base job's drive, or on the last base's drive of a job of several, sets the job's; only the x on a Combo base's drive sets that sheet's), or the x on the last base's drive left the job without its answer (round 7, part 4, P3)",
    "DEMOTED_KEEPS": "a base the Sheets panel's pick demoted to an option lost the Travel Labor line it held (it keeps its own, and the new carrier takes a copy)",
    "ANSWER_HELD": "an answer said was taken back by a step that may not (the job's goes only with Add Travel Labor on a base, or a base an option became bringing the estimator's line, and then every other base that holds none says it as its own; a sheet's only with Add on that sheet)",
    "PROMOTED": "an option a job-type switch or a base pick made a base lost a line the estimator added or typed, kept a line the tool filled while the job says it has no drive, lost one the tool filled while it does not, or was given no line though nothing said it has none (the round-6 audit's F-C)",
    "SAID_TWICE": "what the estimator said ONCE of one crew on a Travel Labor row (the guys typed, a cleared box, switched off) is on TWO bases: the tool's copy of it (the job's one drive following a base pick, or a Sheets copy of the sheet) was not given back when its sheet became a base beside the one holding it, so one crew's figure is priced on two crews' drives (round 7, part 3: the round-7 audit's F1; the trip, its hours and rate, is meant to be on both since part 4: COPY_TRIP)",
    "COPY_TRIP": "the tool's copy given back when its sheet became a base beside the one holding its say did not keep the trip it held (the hours the estimator typed, the rate they typed), or its guys are not its own crew's, or it is still the tool's copy or switched off (round 7, part 4, P1: Kyle's sheets carry the same trip on both crews, each its own guys)",
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
