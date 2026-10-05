"""Which board a project lives on: Direct Projects, or General Contractor.

Hanz, 2026-09-29: "we actually have two pipelines now. We will need to separate pipelines for
Direct and General Contractors. We relabel Active projects to Direct Projects and we add a new
pipeline named 'General Contractor' as a new sidebar. This is where General Contractor projects
will live; it will have the same steps but just on a different webpage."

THE RULE, and the only one. A project belongs on the General Contractor board when its `audience`
is "GC", compared trimmed and case-insensitively. EVERYTHING ELSE IS DIRECT: "Direct", a missing
audience, an empty one, a typo, a value that is not a string at all. Direct is where every project
lived before this split, so it is the only safe answer for anything that has not clearly said GC.

`audience` is the New Project form's own radio (frontend/index.html, name="audience"), saved at the
top of the draft blob. It is the ESTIMATOR'S LIVE CHOICE, which is why the board reads it rather
than `proposal_payload.audience` (what the last Generate rendered): flip the radio and the project
moves boards on the next poll, with no re-generate.

THE SAME RULE LIVES IN frontend/js/crm-core.js as `pipelineOf`, and has to stay character for
character the same. test_gc_pipeline.py runs both on one fixture list, so a change to either one
alone fails there. The two traps it pins:

  * WHITESPACE is the six ASCII characters below, spelled out rather than left to each language's
    idea of it. Python's str.strip() and JavaScript's trim() disagree about exotic whitespace
    (U+FEFF is whitespace to one and not the other), and a project must not sit on one board in
    the payload and on the other one on the page.
  * ONLY A STRING COUNTS. String(["GC"]) is "GC" in JavaScript and str(["GC"]) is "['GC']" here,
    so coercing first would file the same malformed value on two different boards.

main.py stamps every card on the board with `pipeline_of` (api_portal_pipeline), and builds the
General Contractor page out of portal.html with `board_page` below.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

DIRECT = "direct"
GC = "gc"
PIPELINES: Tuple[str, ...] = (DIRECT, GC)

# Where each board is served. /portal.html stays the Direct board, because every link that already
# exists points there: the notification bell, the Follow-ups board, the portal's staff emails
# ("Reply in Portal"), bookmarks, and the bare domain, which serves portal.html's bytes (main.py
# _root). A link to /portal.html for a GC project is sent on to /gc-projects.html by the page
# itself (portal.js load), with the query kept, so none of those links had to change.
BOARD_PAGE: Dict[str, str] = {DIRECT: "/portal.html", GC: "/gc-projects.html"}
# "GC Projects" since 2026-10-02 (Hanz: "change on the sidebar ... from general contractor to GC
# projects"); the board's heading and tab title below say the same.
BOARD_LABEL: Dict[str, str] = {DIRECT: "Direct Projects", GC: "GC Projects"}

# Space, tab, newline, carriage return, form feed, vertical tab. crm-core.js strips the same six.
_WHITESPACE = " \t\n\r\f\v"


def pipeline_of(audience: Any) -> str:
    """"gc" for a General Contractor project, "direct" for everything else. Never raises."""
    if not isinstance(audience, str):
        return DIRECT
    return GC if audience.strip(_WHITESPACE).lower() == "gc" else DIRECT


# ─── the General Contractor page ──────────────────────────────────────────────
# ONE PAGE, SERVED AT TWO ADDRESSES. The GC board is portal.html's own bytes with these four
# strings swapped, not a copy of the file: portal.html is ~900 lines, most of them the board's and
# the drawer's stylesheet, and a copy is a second stylesheet that stops matching the first the next
# time somebody touches either. Everything else — the tabs, the columns, the filters, the drawer,
# the scripts — is literally the same file, and portal.js reads `data-pipeline` off <body> to know
# which board it is drawing.
#
# The swaps are done server-side (main.py serves /gc-projects.html) rather than by portal.js after
# load, because the page would otherwise paint "Direct Projects" and then correct itself: a flash
# of the wrong board's name on every visit.
#
# EACH STRING MUST OCCUR EXACTLY ONCE. board_page raises otherwise, and test_gc_pipeline.py runs it
# against the real portal.html, so an edit that renames the heading fails the suite instead of
# quietly serving the Direct page's name — or worse, `data-pipeline="direct"` — at the GC address.
_GC_PAGE_SWAPS: Tuple[Tuple[str, str], ...] = (
    ('<body data-pipeline="direct">', '<body data-pipeline="gc">'),
    ("<title>Direct Projects · ", "<title>GC Projects · "),
    ("<h1>Direct Projects</h1>", "<h1>GC Projects</h1>"),
    ('<p class="sub">Proposals sent to direct customers',
     '<p class="sub">Proposals sent to general contractors'),
)


class BoardPageError(RuntimeError):
    """portal.html no longer carries a string the General Contractor page is built from."""


def board_page(html: str, pipeline: str) -> str:
    """The board page for `pipeline`, built from portal.html's text. Direct is portal.html itself."""
    if pipeline != GC:
        return html
    out = html
    for old, new in _GC_PAGE_SWAPS:
        found = out.count(old)
        if found != 1:
            raise BoardPageError("portal.html has %d copies of %r; the General Contractor page "
                                 "is built by replacing exactly one" % (found, old))
        out = out.replace(old, new)
    return out
