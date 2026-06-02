"""Autofill rate limit: max 3 runs per 5 minutes, counted per project
(the `X-Project-Id` header). The real `claude -p` CLI is stubbed so these
never make a paid call."""
import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _clear_state():
    main._AUTOFILL_HITS.clear()
    yield
    main._AUTOFILL_HITS.clear()


@pytest.fixture
def stub_cli(monkeypatch):
    """Replace the paid CLI with a counter that returns a fixed cell map."""
    calls = {"n": 0}

    def fake(user_input):
        calls["n"] += 1
        return {"Epoxy!B4": "Yes"}

    monkeypatch.setattr(main, "_autofill_via_cli", fake)
    return calls


def _post(project_id="draftA", notes="some lead notes"):
    headers = {"X-Project-Id": project_id} if project_id is not None else {}
    return client.post("/api/autofill", json={"notes": notes}, headers=headers)


def test_rate_limit_blocks_the_fourth(stub_cli):
    for _ in range(3):
        assert _post("draftA").status_code == 200
    r4 = _post("draftA")
    assert r4.status_code == 429
    body = r4.json()
    assert body["rate_limited"] is True
    assert body["retry_after_seconds"] >= 1
    assert "retry-after" in {k.lower() for k in r4.headers}
    assert stub_cli["n"] == 3   # only the 3 allowed runs hit the AI


def test_failure_refunds_the_slot(monkeypatch):
    # If the AI errors, that attempt must NOT consume the project's budget.
    monkeypatch.setattr(main, "_autofill_via_cli",
                        lambda _u: (_ for _ in ()).throw(RuntimeError("claude down")))
    for _ in range(5):
        r = _post("draftA")
        assert r.status_code == 200          # never 429 — failures are refunded
        assert r.json()["ok"] is False


def test_projects_are_independent(stub_cli):
    for _ in range(3):
        assert _post("draftA").status_code == 200
    assert _post("draftA").status_code == 429   # project A is capped
    assert _post("draftB").status_code == 200    # project B is unaffected


def test_missing_project_header_uses_shared_bucket(stub_cli):
    # No header -> a shared "anon" bucket still enforces the cap.
    for _ in range(3):
        assert _post(project_id=None).status_code == 200
    assert _post(project_id=None).status_code == 429
