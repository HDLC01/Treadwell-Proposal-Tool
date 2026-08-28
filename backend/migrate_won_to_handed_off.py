"""One-off: move every project that was on the Won tab onto Handed Off.

WHY THIS EXISTS. Until 2026-08-28 a won job left the Active board by itself: `isWon` was the
question the board routed on, so the moment the numbers said won, the card moved to a Won tab.
Winning and leaving the board are now two different events — winning puts the card in the
Won/Approved COLUMN and leaves it on Active, and only a human pressing Hand it off takes it off.

That leaves the projects already sitting on the Won tab with nowhere to be. They were put there by
a rule, not by a person, and no `handed_off` stamp exists for any of them; without this script they
would all reappear on the Active board on deploy, in front of a sales meeting that stopped
discussing them weeks ago. Hanz, asked directly, chose to move ALL of them.

WHAT IT SELECTS, and why it is spelled out rather than reused. The predicate below is the OLD
`boardPool()` for `TAB === "won"`, character for character:

    !isLost(p) && !isTest(p) && isWon(p)

Test projects are excluded on purpose — a won test project lived on the TEST tab, never on Won, so
stamping it would hand off a project nobody ever won. Lost beats won for the same reason it does in
the browser: every reader asks `isLost` first.

The derived half of `isWon` is why this cannot be a SQL UPDATE over `data->won`. Most rows on that
tab were never marked by hand at all; they qualified because the portal approved them and the
deposit question was settled, and that state lives in the PORTAL's database, not in our draft blob.
So the script reads the same merged view the board reads and re-runs the rule in Python.

THE TIMESTAMP IS BACKDATED, not stamped now. `won_at || approved_at || now`, in that order: the
Handed Off tab sorts and reads by this field, and stamping every historical row with today's date
would tell the estimator that eleven jobs were handed off this afternoon. `by: "migration"` so the
history entry never claims a person pressed a button.

IDEMPOTENT. A row that already carries `handed_off_at` is skipped and counted, so a re-run after a
partial failure is safe and a second full run is a no-op.

    python -m backend.migrate_won_to_handed_off            # dry run: prints, writes nothing
    python -m backend.migrate_won_to_handed_off --apply     # writes

Run it INSIDE the container, which is where PORTAL_ADMIN_URL, SERVICE_TOKEN and the Supabase
credentials live. Staging first, and read the printed list before applying.
"""
from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List

import drafts
from main import api_portal_pipeline


def _approved_in_portal(p: Dict[str, Any]) -> bool:
    """crm-core.js approvedInPortal. The stamp as well as the status, because closed_lost REPLACES
    'approved' in the portal's one terminal column while `approved_at` survives it."""
    return str(p.get("proposal_status") or "") == "approved" or bool(p.get("approved_at"))


def _deposit_satisfied(p: Dict[str, Any]) -> bool:
    """crm-core.js depositSatisfied. A job that collects no deposit is settled — unless an invoice
    actually went out, which means money is outstanding whatever the flag says."""
    return p.get("deposit_status") == "received" or (
        p.get("deposit_required") is False and not p.get("deposit_requested_at"))


def _is_won(p: Dict[str, Any]) -> bool:
    """crm-core.js isWon: a human said so, or the customer approved AND the money is settled."""
    if p.get("won_at"):
        return True
    return _approved_in_portal(p) and _deposit_satisfied(p)


def _is_lost(p: Dict[str, Any]) -> bool:
    """crm-core.js isLost, and it really is only the status.

    No `closed_lost_at` half, deliberately, because a wider rule here would be a WORSE migration
    rather than a safer one: it would skip a row the Won tab was showing, and that row reappears on
    the Active board on deploy — the exact thing this script exists to prevent. The board's rule is
    the definition of what was on that tab, so anything but a character-for-character mirror is a
    guess. An unsent bid closed before it was ever sent is shaped as the portal's own closed_lost
    status by `_not_sent_rows`, not as a separate draft-side field, so this one check covers both.
    """
    return str(p.get("proposal_status") or "") == "closed_lost"


def _name_looks_like_test(p: Dict[str, Any]) -> bool:
    """crm-core.js nameLooksLikeTest. The regex stays narrow on purpose — "demo" lives inside
    "demolition", which is a live hazard in a construction tool."""
    import re
    n = str(p.get("project_name") or "")
    return bool(re.search(r"\b(sample|test|verify|demo|qa|bugtest)\b", n, re.I)
                or re.search(r"delete me", n, re.I)
                or re.search(r"^\s*zz", n, re.I))


def _is_test(p: Dict[str, Any]) -> bool:
    """crm-core.js isTest: the tri-state flag wins in BOTH directions, name only when unset."""
    v = p.get("is_test")
    if isinstance(v, bool):
        return v
    return _name_looks_like_test(p)


def _pick(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [p for p in rows if not _is_lost(p) and not _is_test(p) and _is_won(p)]


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="Move Won-tab projects onto Handed Off.")
    ap.add_argument("--apply", action="store_true",
                    help="actually write. Without it the script only prints what it would do.")
    args = ap.parse_args(argv)

    rows = (api_portal_pipeline() or {}).get("proposals") or []
    picked = _pick(rows)
    already = [p for p in picked if p.get("handed_off_at")]
    todo = [p for p in picked if not p.get("handed_off_at")]

    print("%d projects on the board; %d were on the Won tab; %d already handed off; %d to stamp."
          % (len(rows), len(picked), len(already), len(todo)))
    if not todo:
        print("Nothing to do.")
        return 0

    for p in todo:
        at = p.get("won_at") or p.get("approved_at") or drafts._now_iso()
        why = "marked by hand" if p.get("won_at") else "approved + deposit settled"
        print("  %-38s %-24s %s  (%s)" % (
            (p.get("project_name") or "(untitled)")[:38], p.get("proposal_id") or "?", at, why))

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply once the list above looks right.")
        return 0

    sb = drafts.get_client()
    ok = bad = 0
    for p in todo:
        pid = p.get("proposal_id")
        at = p.get("won_at") or p.get("approved_at") or drafts._now_iso()
        try:
            cur = sb.table("drafts").select("data").eq("id", pid).limit(1).execute()
            if not cur.data:
                # A portal row whose draft we no longer hold. Nothing to stamp and nothing to
                # invent: the board reads the flag off the draft blob, so there is no other place
                # this could be written.
                print("  SKIP (no draft) %s" % pid)
                bad += 1
                continue
            data = dict(cur.data[0].get("data") or {})
            data["handed_off"] = {"at": at, "by": "migration"}
            sb.table("drafts").update({"data": data}).eq("id", pid).execute()
            drafts.log_event(pid, "migration", "handed_off",
                             {"project_name": data.get("project_name"), "id": pid,
                              "note": "moved from the Won tab by the 2026-08-28 migration"})
            ok += 1
        except Exception as exc:  # noqa: BLE001 — one bad row must not strand the rest
            print("  FAILED %s: %s" % (pid, exc))
            bad += 1

    drafts._cache_clear()
    print("\nStamped %d, skipped/failed %d. Re-run to retry — already-stamped rows are skipped."
          % (ok, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
