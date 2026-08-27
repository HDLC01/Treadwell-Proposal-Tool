"""POST /api/polish/verbal-intake — the route, not the rules.

backend/tests/test_verbal_intake.py owns the RULES: which flags are allowed through and why a
price flag needs a verbatim quote. It is a pure-function file by design and says so. Nothing
tested the route it sits behind, and everything below is something that only exists at the route:

  * **What the model is sent.** The date comes from the SERVER in America/Chicago (this box runs
    ~13 hours ahead of Central), the system prompt is the verbal one and not autofill's — which is
    explicitly told never to abstain, the opposite of what this feature needs — and the transcript
    is bounded before it becomes a paid subprocess call.
  * **What the gate is run against.** The capped transcript, the one actually sent. A quote
    supported only by words that fell off the end is not supported.
  * **What a failure costs.** Three AI runs per five minutes is the entire budget the "ask ONCE"
    design is built on, so an error that keeps its slot means the estimator can spend two runs
    without ever reaching the model. `clean()` raising was that exact case: `{"missing": 3}` hit a
    TypeError OUTSIDE the try block, so the estimator got a 500 with a slot already gone.
  * **Whose budget it is.** The cap is keyed on the verified email alone. `_autofill_bucket` mixes
    in the client's own `X-Project-Id` header, which means a caller who wants a fresh budget only
    has to invent a project id — a limiter you can ask for more of.

The real `claude -p` CLI is replaced everywhere here, so none of this makes a paid call.
"""
import pytest
from fastapi.testclient import TestClient

import main
import verbal_intake

client = TestClient(main.app)

TRANSCRIPT = ("Blue Valley West High School, 16200 Antioch Road, Overland Park Kansas 66085. "
              "It's a hard bid. Bid is due the third of September.")


@pytest.fixture(autouse=True)
def _clear_limiter():
    main._AUTOFILL_HITS.clear()
    yield
    main._AUTOFILL_HITS.clear()


@pytest.fixture
def cli(monkeypatch):
    """The paid CLI, replaced by a recorder. `calls` is what the route sent; `reply` is what the
    model says back and each test rewrites it."""
    seen = {"calls": [], "reply": {}}

    def fake(user_input, system_prompt=None):
        seen["calls"].append({"input": user_input, "prompt": system_prompt})
        return seen["reply"]

    monkeypatch.setattr(main, "_autofill_via_cli", fake)
    return seen


def _post(transcript=TRANSCRIPT, headers=None):
    return client.post("/api/polish/verbal-intake", json={"transcript": transcript},
                       headers=headers or {})


# ── the happy path ───────────────────────────────────────────────────────────
def test_what_the_estimator_said_comes_back_as_fields_and_evidence(cli):
    """One pass end to end: the route sends the transcript, the gate checks the quote against the
    server's own copy of it, and the accepted flag comes back with the TRANSCRIPT's words around
    the match rather than the model's crop of them."""
    cli["reply"] = {
        "project_name": "Blue Valley West High School",
        "city": "Overland Park", "state": "ks", "bid_date": "2026-09-03",
        "conditions": {"hard_bid": {"value": True, "quote": "It's a hard bid"}},
        "missing": ["contact_email"],
        "question": "Who is the contact?",
    }
    r = _post()
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["fields"]["project_name"] == "Blue Valley West High School"
    assert body["fields"]["state"] == "KS"
    assert body["conditions"]["hard_bid"]["value"] is True
    assert "hard bid" in body["conditions"]["hard_bid"]["context"]
    assert "quote" not in body["conditions"]["hard_bid"], (
        "the model's crop is still on the wire, so the panel can print it instead of the "
        "transcript's own words")
    assert body["missing"] == ["contact_email"]
    assert body["question"] == "Who is the contact?"


def test_the_model_gets_the_verbal_prompt_and_a_central_date(cli):
    """TWO WAYS THIS GOES WRONG SILENTLY, both invisible in the response.

    The prompt: `_autofill_via_cli` defaults to `_AUTOFILL_SYSTEM_PROMPT`, which is told never to
    abstain and to apply conservative defaults. That is exactly backwards for a feature whose job
    is knowing what it does not have, and a dropped second argument would fall back to it.

    The date: it is GIVEN, not inferred. This dev box runs ~13 hours ahead of Central, so a model
    left to work out "the third of September" off its own clock puts a bid date a day out — and a
    bid is due when it is due."""
    import leads
    from datetime import datetime
    today = datetime.now(leads._biz_tz()).date().isoformat()

    _post()
    call = cli["calls"][0]
    assert call["prompt"] is verbal_intake.SYSTEM_PROMPT, (
        "the autofill prompt would be used instead — it never abstains, which is the one thing "
        "this feature must do")
    assert today in call["input"], "the model was not told what day it is in Central time"
    assert TRANSCRIPT in call["input"]


# ── not enough said yet ──────────────────────────────────────────────────────
def test_too_little_said_asks_for_more_without_spending_a_run(cli):
    """The estimator has simply not said enough yet, which is a prompt and not a failure — so it
    must not reach the paid CLI and must not cost one of the three runs. Checked through a fourth
    call succeeding: if a short one had recorded a slot, the budget would be gone."""
    r = _post("Blue Valley")
    assert r.status_code == 200
    assert r.json()["too_short"] is True
    assert cli["calls"] == [], "a transcript too short to read was sent to the AI anyway"
    for _ in range(3):
        assert _post().status_code == 200
    assert any(main._AUTOFILL_HITS.values()), (
        "the limiter recorded nothing at all, so the three calls above prove nothing about the "
        "short one")


# ── the budget ───────────────────────────────────────────────────────────────
def test_the_fourth_run_in_the_window_is_refused(cli):
    """Three per five minutes is the whole budget the "ask ONCE" design is built around: a first
    pass plus one re-ask already spends two."""
    for _ in range(3):
        assert _post().status_code == 200
    r = _post()
    assert r.status_code == 429
    assert r.json()["rate_limited"] is True
    assert r.json()["retry_after_seconds"] >= 1
    assert "retry-after" in {k.lower() for k in r.headers}
    assert len(cli["calls"]) == 3, "a refused call reached the AI"


def test_a_made_up_project_id_does_not_buy_a_fresh_budget(cli):
    """`_autofill_bucket` folds the client's own `X-Project-Id` header into the key, so on that
    limiter a caller who wants three more runs sends three more project ids. This route keys on
    the verified token's email and nothing else.

    Exercised through the ROUTE with real headers rather than by reading the bucket string,
    because the bug this defends against is a call to the wrong helper — which a source assertion
    about a header name would not see."""
    for i in range(3):
        assert _post(headers={"X-Project-Id": "draft-%d" % i}).status_code == 200
    assert _post(headers={"X-Project-Id": "draft-brand-new"}).status_code == 429, (
        "a new project id got a new budget, so the cap is worth nothing")


def test_a_failed_run_gives_its_slot_back(cli, monkeypatch):
    """An error must not cost the estimator part of a budget they never got to use. Five attempts
    in a row, none of them ever a 429."""
    monkeypatch.setattr(main, "_autofill_via_cli",
                        lambda _u, _p=None: (_ for _ in ()).throw(RuntimeError("claude down")))
    for _ in range(5):
        r = _post()
        assert r.status_code == 200
        assert r.json()["ok"] is False
        assert "try again" in r.json()["error"].lower()


def test_a_failure_in_the_cleaning_step_refunds_its_slot_too(cli, monkeypatch):
    """THE PLACEMENT THIS TEST EXISTS FOR. `clean()` used to be called AFTER the try/except, so
    anything it raised became a 500 — no message the page could show — with the slot already
    recorded. It is inside now, next to the CLI call, the way the lead path keeps
    apply_ai_overlay inside its own try.

    `clean()` is written not to raise and is tested for it; "written not to raise" is not a
    mechanism, which is why this forces one."""
    monkeypatch.setattr(verbal_intake, "clean",
                        lambda _ai, _t: (_ for _ in ()).throw(ValueError("boom")))
    for _ in range(5):
        r = _post()
        assert r.status_code == 200, "a cleaning failure is still a 500"
        assert r.json()["ok"] is False


def test_a_missing_list_that_is_not_a_list_is_not_a_500(cli):
    """The real shape that hit it: `{"missing": 3}` is truthy, so `or []` passed it straight into
    a comprehension that iterated it. TypeError, outside the try, 500 — and one of the three runs
    gone. Run through the real `clean()` here, not a stub: the point is that the shape no longer
    raises anywhere on the path."""
    cli["reply"] = {"missing": 3, "project_name": "Blue Valley West"}
    r = _post()
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["missing"] == []
    assert r.json()["fields"]["project_name"] == "Blue Valley West", (
        "one bad key took a good extraction with it")


# ── the cap ──────────────────────────────────────────────────────────────────
def test_a_huge_transcript_is_cut_before_it_becomes_a_paid_call(cli):
    """An unbounded request body on a route that spawns a paid subprocess is a way to spend real
    money by typing. 15,000 characters is leads._TEXT_CAP, and nothing past it makes the
    extraction better."""
    r = _post("Blah blah blah. " * 4000)
    assert r.status_code == 200
    sent = cli["calls"][0]["input"]
    assert "[truncated]" in sent, "the transcript went out at full length"
    assert len(sent) < main._VERBAL_TRANSCRIPT_CAP + 500, (
        "the prompt is still the size of the whole request body")


def test_the_gate_runs_on_the_transcript_that_was_actually_sent(cli):
    """The cap and the evidence gate have to agree about what the transcript IS. If the model is
    sent 15,000 characters and the gate checks against 40,000, a quote can be "supported" by
    words the model never saw — which is the one thing the gate exists to make impossible.

    So the truncation happens once, before either, and both use the result."""
    filler = "blah " * 3000                     # exactly the cap, so what follows is cut off
    cli["reply"] = {"conditions": {
        "hard_bid": {"value": True, "quote": "it is a hard bid"}}}
    r = _post(filler + "and it is a hard bid.")
    body = r.json()
    assert body["conditions"] == {}, (
        "a quote from past the cap was accepted, so the gate is reading a different transcript "
        "from the one the model was given")
    assert body["unsupported"] == ["hard_bid"]
    assert "hard_bid" in body["missing"], "the estimator is not asked about the flag that was lost"
