"""One-off: freeze the PDF of every portal proposal's CURRENT revision.

WHY THIS EXISTS. Since 2026-09-25 a send stores the .docx and PDF it was sent with
(draft_revision_documents), and /api/admin/proposal-pdf serves those bytes from then on, whatever
later code or template changes land. A revision sent BEFORE that has no stored files, so the portal
re-renders it on every view through whatever code is deployed that day. The next fixes change what
that code prints (tax lines, bullets, spacing, the header date), and each of them would quietly
rewrite a proposal a customer already holds. This stores the current pinned revision of every portal
proposal once, so those customers keep what they were sent.

WHEN TO RUN IT, and the order is the whole point. AFTER fix 1 (the template version became a content
hash) is live, because before it a re-render dropped Kyle's paragraph edits and freezing that would
freeze the damage. And BEFORE any later change to rendering deploys, so the render stored is the one
the customer was sent. Staging first, then prod with Hanz's go.

WHAT IT SELECTS. Every `portal_proposals` row with a `current_revision_no` — the revision the
customer's portal is pinned to. Older revisions keep re-rendering; nobody is shown them. Skipped,
and counted:

  * a revision that already has stored files (idempotent: a re-run after a partial failure is safe,
    and a second full run is a no-op);
  * a revision with no `proposal_payload.values`, which has no document at all (the PDF route
    answers "not generated yet" for it today, and still will);
  * a revision with a SIGNED CONTRACT (`portal_approvals.contract_sha256`). The portal stored the
    bytes the customer signed, and those are the authority for that revision. A second rendering
    frozen beside them could put in front of the customer a document that differs from the one they
    signed, so these are listed for a human to decide, never stored.

It also WARNS about a revision whose `template_version` the current template refuses: the render
would drop that revision's paragraph edits. Fix 1 accepts every stamp taken against today's
template content, so none is expected; read the dry run for them before applying.

And it WARNS about a revision on a template whose Remodel Tax row is a plain paragraph (the three
GC templates and the Gyp template) with Remodel off. Until 2026-09-25 those printed "$0 – Remodel
Tax" on a job with no remodel tax; since Hanz's rule ("If remodel tax is off then in the broken
out option in the Proposal, there is no remodel tax but there is material sales tax") the render
takes that row out. So the PDF this stores for such a revision has no $0 row, where the copy the
customer saw in their portal before that deploy had one. Nothing else differs (the row carried no
money), but the dry run lists them so that is known before anything is frozen. Freezing the old
row instead would mean running this from a build without the rule.

    docker exec -w /app treadwell-proposal-tool python backfill_revision_documents.py           # dry run
    docker exec -w /app treadwell-proposal-tool python backfill_revision_documents.py --apply   # writes

Run it INSIDE the container: that is where LibreOffice, the templates and the database credentials
live. Staging's container is `treadwell-staging`. The dry run renders nothing and writes nothing.
"""
from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

import drafts


def _pinned(sb) -> List[Tuple[str, int]]:
    """(proposal_id, current_revision_no) for every portal proposal pinned to a revision."""
    res = (sb.table("portal_proposals").select("proposal_id, current_revision_no")
           .not_.is_("current_revision_no", "null").execute())
    return sorted({(r["proposal_id"], int(r["current_revision_no"]))
                   for r in (res.data or []) if r.get("proposal_id") and r.get("current_revision_no")})


def _signed(sb) -> Set[Tuple[str, int]]:
    """(proposal_id, revision_no) of every approval carrying a signed contract."""
    res = (sb.table("portal_approvals").select("proposal_id, revision_no, contract_sha256")
           .not_.is_("contract_sha256", "null").execute())
    return {(r["proposal_id"], int(r["revision_no"]))
            for r in (res.data or []) if r.get("proposal_id") and r.get("revision_no")}


def _service_request():
    """A request with nobody signed in — which is what the customer's own PDF render has, and since
    2026-09-25 a render depends on nothing a request carries anyway."""
    from starlette.requests import Request
    return Request({"type": "http", "method": "POST", "path": "/backfill-revision-documents",
                    "headers": [], "query_string": b""})


def _stale_edits(main, payload: Dict[str, Any]) -> Optional[str]:
    """Why this revision's paragraph edits would be dropped by the render, or None."""
    stamp = str(payload.get("template_version") or "")
    if not stamp:
        return None
    gi = main.GenerateIn(**payload)
    path = main.proposal_writer.pick_template(gi.work_type, gi.audience or None)
    if main._template_version_accepts(stamp, path):
        return None
    return "template_version %r is refused by %s — its paragraph edits would be dropped" % (
        stamp, path.name)


def _remodel_row_while_off(main, payload: Dict[str, Any]) -> Optional[str]:
    """Why this revision's stored render differs from what its customer saw before 2026-09-25 —
    a template with a FREE Remodel Tax row, and Remodel off, so the row that used to print "$0" is
    now taken out — or None.

    Asked of the TEMPLATE, the same way the render asks it (`template_free_tax_rows`). No render
    needed, so the dry run can say it."""
    gi = main.GenerateIn(**payload)
    if gi.remodel:
        return None
    if not main.proposal_writer.template_free_tax_rows(gi.work_type, gi.audience)["remodel"]:
        return None
    if main._parse_usd((gi.values or {}).get("tax_amount_formatted")):
        return None                      # a real remodel figure: the row still prints, unchanged
    return ("its %s/%s template printed a $0 Remodel Tax row with Remodel off; the stored PDF "
            "leaves it out (Hanz's remodel rule)" % (gi.work_type, gi.audience))


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Store the PDF of every portal proposal's current revision.")
    ap.add_argument("--apply", action="store_true",
                    help="actually render and write. Without it the script only prints the plan.")
    args = ap.parse_args(argv)

    import main as app   # the renderer; imported here so --help needs no configuration

    sb = drafts.get_client()
    try:
        drafts.get_revision_documents("__probe__", 0)
    except Exception as exc:  # noqa: BLE001
        print("draft_revision_documents cannot be read — apply its DDL to this database first "
              "(supabase_schema.sql 6b / staging/schema_pg.sql): %s" % exc)
        return 1
    pinned = _pinned(sb)
    try:
        signed = _signed(sb)
    except Exception as exc:  # noqa: BLE001 — without this list nothing can be stored safely
        print("Could not read portal_approvals, so a signed revision cannot be told apart: %s" % exc)
        print("Nothing written.")
        return 1

    todo: List[Tuple[str, int, Dict[str, Any]]] = []
    for pid, rev_no in pinned:
        rev = drafts.get_revision(pid, rev_no)
        data = (rev or {}).get("data") or {}
        name = (data.get("project_name") or "(untitled)")[:38]
        pp = data.get("proposal_payload")
        if not rev:
            print("  SKIP  %-38s rev %-3d no such revision" % (name, rev_no))
            continue
        if drafts.get_revision_documents(pid, rev_no) is not None:
            print("  SKIP  %-38s rev %-3d already stored" % (name, rev_no))
            continue
        if not (isinstance(pp, dict) and pp.get("values")):
            print("  SKIP  %-38s rev %-3d has no document to store" % (name, rev_no))
            continue
        if (pid, rev_no) in signed:
            print("  SKIP  %-38s rev %-3d SIGNED — the portal's signed contract is the authority"
                  % (name, rev_no))
            continue
        why = "; ".join(r for r in (_stale_edits(app, pp), _remodel_row_while_off(app, pp)) if r)
        print("  %s %-38s rev %-3d %s" % ("WARN " if why else "STORE", name, rev_no, why))
        todo.append((pid, rev_no, pp))

    print("\n%d pinned revisions; %d to store." % (len(pinned), len(todo)))
    if not todo:
        print("Nothing to do.")
        return 0
    if not args.apply:
        print("DRY RUN — nothing rendered or written. Re-run with --apply once the list above "
              "looks right.")
        return 0

    req = _service_request()
    ok = bad = 0
    for pid, rev_no, pp in todo:
        try:
            docs = app._render_documents(pp, req, want_estimate=False)
            pdf = app._entry_pdf(docs["docx"])
            drafts.store_revision_documents(pid, rev_no, payload_sha256=docs["payload_sha256"],
                                            docx=docs["docx"]["content"], pdf=pdf,
                                            created_by="backfill")
            ok += 1
        except Exception as exc:  # noqa: BLE001 — one bad revision must not strand the rest
            print("  FAILED %s rev %d: %s: %s" % (pid, rev_no, type(exc).__name__, exc))
            bad += 1
    print("\nStored %d, failed %d. Re-run to retry — stored revisions are skipped." % (ok, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
