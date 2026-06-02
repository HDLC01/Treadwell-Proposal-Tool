"""Autofill safeguards: idempotency (identical request runs the AI once) and a
per-project rate limit (3 per 5 min). The real `claude -p` CLI is stubbed so
these never make a paid call."""
import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _clear_state():
    """Each test starts with empty idempotency cache + rate counters."""
    main._AUTOFILL_IDEM.clear()
    main._AUTOFILL_HITS.clear()
    yield
    main._AUTOFILL_IDEM.clear()
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


def _post(idem_key, notes="some lead notes"):
    return client.post("/api/autofill", json={"notes": notes},
                       headers={"Idempotency-Key": idem_key})


def test_idempotent_replay_runs_ai_once(stub_cli):
    r1 = _post("draftA:abc")
    r2 = _post("draftA:abc")
    assert r1.status_code == 200 and r1.json()["ok"] is True
    assert r2.status_code == 200 and r2.json().get("idempotent_replay") is True
    assert r2.json()["cell_values"] == r1.json()["cell_values"]
    assert stub_cli["n"] == 1   # the AI ran exactly once despite two requests


def test_rate_limit_blocks_the_fourth(stub_cli):
    # 3 DISTINCT requests (different idem keys) in the same project bucket.
    for i in range(3):
        assert _post(f"draftA:c{i}").status_code == 200
    r4 = _post("draftA:c4")
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
    for i in range(5):
        r = _post(f"draftA:f{i}")
        assert r.status_code == 200          # never 429 — failures are refunded
        assert r.json()["ok"] is False


def test_projects_are_independent(stub_cli):
    for i in range(3):
        assert _post(f"draftA:x{i}").status_code == 200
    assert _post("draftA:x4").status_code == 429   # project A is capped
    assert _post("draftB:y0").status_code == 200    # project B is unaffected


def test_missing_idempotency_header_still_works(stub_cli):
    # Defensive path: no header -> derive a content-hash key, shared bucket.
    r = client.post("/api/autofill", json={"notes": "no header here"})
    assert r.status_code == 200 and r.json()["ok"] is True
    # identical body again -> replay (same derived key), AI not called twice
    r2 = client.post("/api/autofill", json={"notes": "no header here"})
    assert r2.json().get("idempotent_replay") is True
    assert stub_cli["n"] == 1
