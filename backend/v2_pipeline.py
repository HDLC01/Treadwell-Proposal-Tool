"""The v2 Estimates board's rows: Estimating Tool v2 bids, shaped like pipeline rows.

Hanz, 2026-10-13: "make the V2 have a pipeline like the ones we have for active projects", then
"make sure they are separate tho", then "the V2 pipeline is still in beta ... so do not merge it to
the existing". So this is its OWN module and its own route (main.py: GET /api/v2/pipeline). The real
boards' route, /api/portal/pipeline, and the page code behind it are not touched and never call
into this file.

WHAT IT RETURNS: every Estimating Tool v2 draft (`polish_beta`), from the moment it is created,
test copies included, and nothing else. A v2 bid that was never generated is still a row here (the
real board hides those, because a started intake form is not a proposal; on a beta board the
started bid IS the thing being watched).

THE ROWS ARE THE SAME SHAPE as pipeline rows, so the browser reads them with the shared, DOM-free
js/crm-core.js (stage, group, cardTotal) and the columns match the real board exactly. A v2 draft the
customer portal also knows (it was sent from the real flow) takes the portal's row, decorated with
our own facts; one the portal does not know is synthesised, `not_sent`, which stage() files under
"Created but not sent".

READ ONLY. Nothing here writes anywhere, and the page it feeds has no control that does.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pipelines

# How many drafts the summary list can hold (drafts.list_drafts(limit=300)). Stated to the page so
# the footnote names the real ceiling rather than a remembered one.
READ_CEILING = 300


def is_v2(summary: Dict[str, Any]) -> bool:
    """A live (not archived) Estimating Tool v2 draft. `polish_beta` is drafts._polish_beta's
    answer to "was this priced in v2", already coerced to a real boolean on both read paths."""
    return bool(summary.get("polish_beta")) and not summary.get("archived")


def _synth(s: Dict[str, Any], *, unknown: bool) -> Dict[str, Any]:
    """A row for a v2 draft the customer portal has no row for.

    `unknown` is the portal-down case for a bid we KNOW went out (it has a sent revision): it is
    drawn as "Sent" with no invented status, exactly as the real board treats the same outage."""
    row: Dict[str, Any] = {
        "proposal_id": s["id"],
        "project_name": s.get("project_name"),
        "customer_email": s.get("contact_email") or "",
        "is_test": s.get("is_test"),
        "assigned_estimator": s.get("assigned_estimator"),
        # estimatorOf falls back to this: with nobody assigned, whoever built it is who to ask.
        "estimator_email": s.get("owner_email"),
        "last_activity_at": s.get("updated_at"),
        # NOT approved_total: nobody has approved a draft. cardTotal() reads both fields.
        "bid_total": s.get("total"),
        "work_type": s.get("work_type"),
        "audience": s.get("audience"),
        "won_at": s.get("won_at"),
        "handed_off_at": s.get("handed_off_at"),
    }
    if unknown:
        row["portal_unknown"] = True
    else:
        row["not_sent"] = True
        row["drafted_at"] = s.get("updated_at")
    if s.get("closed_lost_reason"):
        row["proposal_status"] = "closed_lost"
        row["followup_state"] = {"closed_lost_reason": s["closed_lost_reason"],
                                 "closed_at": s.get("closed_lost_at")}
    elif s.get("on_hold_reason"):
        row["followup_state"] = {"paused_until": s.get("on_hold_until"),
                                 "on_hold_reason": s["on_hold_reason"]}
    return row


def _decorate(row: Dict[str, Any], s: Dict[str, Any]) -> Dict[str, Any]:
    """Our own facts onto a portal row, never overwriting a figure the portal already has."""
    out = dict(row)
    out["is_test"] = s.get("is_test")
    out["audience"] = s.get("audience")
    if out.get("bid_total") is None and s.get("total") is not None:
        out["bid_total"] = s["total"]
    if s.get("won_at"):
        out["won_at"] = s["won_at"]
    if s.get("handed_off_at"):
        out["handed_off_at"] = s["handed_off_at"]
    return out


def build_rows(summaries: List[Dict[str, Any]], portal_rows: List[Dict[str, Any]],
               portal_status: str) -> List[Dict[str, Any]]:
    """Every v2 draft as one pipeline-shaped row, newest-updated first (the summaries' own order).

    `portal_rows` is whatever the shared snapshot returned; only the ones whose id is a v2 draft are
    used, so a real project's portal row can never reach this board."""
    by_id = {r.get("proposal_id"): r for r in portal_rows or []}
    out: List[Dict[str, Any]] = []
    for s in summaries or []:
        if not is_v2(s):
            continue
        portal = by_id.get(s["id"])
        if portal is not None:
            row = _decorate(portal, s)
        else:
            # Only when the portal could not be asked: a bid with a sent revision certainly went
            # out, and filing it under "Created but not sent" would invite a re-send.
            unknown = portal_status == "offline" and int(s.get("sent_revision") or 0) > 0
            row = _synth(s, unknown=unknown)
        row["v2"] = True
        row["pipeline"] = pipelines.pipeline_of(row.get("audience"))
        out.append(row)
    return out
