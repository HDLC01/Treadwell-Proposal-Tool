"""`sent_revision` on the projects list — the card's "Sent · Rev N" badge.

Without it every project looks like a fresh draft and nobody can tell which ones are
live with a customer, which is exactly the confusion that made "where do I revise a
sent bid?" hard to answer.
"""
import drafts


def test_sent_revisions_takes_the_highest_per_project(monkeypatch):
    class _Res:
        data = [
            {"project_id": "a", "revision_no": 1},
            {"project_id": "a", "revision_no": 3},
            {"project_id": "a", "revision_no": 2},
            {"project_id": "b", "revision_no": 1},
        ]

    class _Q:
        def select(self, *a, **k): return self
        def in_(self, *a, **k): return self
        def execute(self): return _Res()

    monkeypatch.setattr(drafts, "get_client", lambda: type("C", (), {"table": lambda s, n: _Q()})())
    assert drafts._sent_revisions(["a", "b"]) == {"a": 3, "b": 1}


def test_no_ids_makes_no_query(monkeypatch):
    def boom():
        raise AssertionError("must not query for an empty page")

    monkeypatch.setattr(drafts, "get_client", lambda: boom())
    assert drafts._sent_revisions([]) == {}


def test_missing_table_degrades_to_no_badges(monkeypatch):
    """A database without the revisions DDL applied yet must still render the
    projects list — the badge simply doesn't appear."""
    class _Q:
        def select(self, *a, **k): return self
        def in_(self, *a, **k): return self
        def execute(self): raise RuntimeError('relation "draft_revisions" does not exist')

    monkeypatch.setattr(drafts, "get_client", lambda: type("C", (), {"table": lambda s, n: _Q()})())
    assert drafts._sent_revisions(["a"]) == {}


def test_never_sent_projects_report_zero(monkeypatch):
    class _Res:
        data = [{"project_id": "a", "revision_no": 2}]

    class _Q:
        def select(self, *a, **k): return self
        def in_(self, *a, **k): return self
        def execute(self): return _Res()

    monkeypatch.setattr(drafts, "get_client", lambda: type("C", (), {"table": lambda s, n: _Q()})())
    got = drafts._sent_revisions(["a", "never-sent"])
    assert got.get("a") == 2
    assert got.get("never-sent", 0) == 0      # the card falls back to "Open / Edit"
