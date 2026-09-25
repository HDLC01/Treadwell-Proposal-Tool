"""The one-off that freezes every portal proposal's CURRENT revision (backfill_revision_documents).

It will be run once, on prod, against the documents fifteen customers already hold, so what it
selects is the whole of what it does. EXECUTED against the conftest FakeClient behind the real
drafts.py functions, with the real renderer and LibreOffice replaced by a stamp. Never against a
real database.
"""
import copy

import pytest

import backfill_revision_documents as backfill
import drafts
import main

PAYLOAD = {"work_type": "epoxy", "audience": "Direct",
           "values": {"project_name": "Backfill", "city_state": "Lenexa, KS",
                      "total_formatted": "$1,000.00", "estimator_name": "Kyle Loseke"}}


def _rev(pid, no, payload=PAYLOAD):
    data = {"project_name": pid}
    if payload is not None:
        data["proposal_payload"] = copy.deepcopy(payload)
    return {"project_id": pid, "revision_no": no, "data": data, "created_by": "kyle@wetreadwell.com"}


@pytest.fixture
def db(monkeypatch, fake_supabase):
    store = {
        "portal_proposals": [
            {"proposal_id": "cur", "current_revision_no": 2},      # stored: rev 2, never rev 1
            {"proposal_id": "done", "current_revision_no": 1},     # already stored: skipped
            {"proposal_id": "signed", "current_revision_no": 1},   # signed contract: listed only
            {"proposal_id": "empty", "current_revision_no": 1},    # no document to store
            {"proposal_id": "legacy", "current_revision_no": None},  # never pinned: not selected
        ],
        "portal_approvals": [
            {"proposal_id": "signed", "revision_no": 1, "contract_sha256": "abc"},
            {"proposal_id": "cur", "revision_no": 1, "contract_sha256": None},
        ],
        "draft_revisions": [_rev("cur", 1), _rev("cur", 2), _rev("done", 1), _rev("signed", 1),
                            _rev("empty", 1, payload=None)],
        "draft_revision_documents": [],
    }
    fake = fake_supabase(store)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    monkeypatch.setattr(drafts, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(main.pdf_writer, "docx_to_pdf", lambda b: b"%PDF-1.4 backfilled")
    drafts.store_revision_documents("done", 1, payload_sha256="x", docx=b"d", pdf=b"sent before")
    return store


def _stored(store):
    return sorted((r["project_id"], r["revision_no"]) for r in store["draft_revision_documents"])


def test_the_dry_run_writes_nothing(db, capsys):
    assert backfill.main([]) == 0
    assert _stored(db) == [("done", 1)]
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "1 to store" in out, out


def test_apply_stores_only_the_CURRENT_revision_that_has_no_row(db, capsys):
    """rev 2 of `cur` is what its customer is pinned to; rev 1 is not shown to anyone.

    Mutation: select every revision of a pinned proposal, or the first one — `cur` rev 1 appears."""
    assert backfill.main(["--apply"]) == 0
    assert _stored(db) == [("cur", 2), ("done", 1)]
    got = drafts.get_revision_documents("cur", 2)
    assert got["pdf"] == b"%PDF-1.4 backfilled" and got["docx"].startswith(b"PK")
    assert got["payload_sha256"] == main._canonical_sha256(PAYLOAD)


def test_a_revision_already_stored_is_never_rewritten(db):
    """Idempotent, and more than that: a row stored by a SEND is the PDF that customer was sent.

    Mutation: drop the already-stored skip — `done` is overwritten with a fresh render."""
    backfill.main(["--apply"])
    assert drafts.get_revision_documents("done", 1)["pdf"] == b"sent before"
    backfill.main(["--apply"])
    assert _stored(db) == [("cur", 2), ("done", 1)]


def test_a_signed_revision_is_listed_and_never_stored(db, capsys):
    """The portal's signed contract is the authority for that revision.

    Mutation: drop the signed skip — `signed` gets a row."""
    backfill.main(["--apply"])
    assert ("signed", 1) not in _stored(db)
    assert "SIGNED" in capsys.readouterr().out


def test_no_approvals_list_means_nothing_is_written(db, monkeypatch, capsys):
    """Without the list a signed revision cannot be told apart, so the script stops."""
    def unreadable(sb):
        raise RuntimeError("permission denied for table portal_approvals")

    monkeypatch.setattr(backfill, "_signed", unreadable)
    assert backfill.main(["--apply"]) == 1
    assert _stored(db) == [("done", 1)]


def test_a_database_without_the_table_is_refused_up_front(db, monkeypatch, capsys):
    def missing(*a, **k):
        raise RuntimeError('relation "public.draft_revision_documents" does not exist')

    monkeypatch.setattr(drafts, "get_revision_documents", missing)
    assert backfill.main(["--apply"]) == 1
    assert "apply its DDL" in capsys.readouterr().out
