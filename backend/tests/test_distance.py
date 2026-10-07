"""POST /api/distance -- driving miles from the Olathe office to the job (Google Routes).

Kyle's 9/18 notes: take the "70 mile slider" off intake and work the distance out from the address.
Hanz, 2026-10-05: driving miles, server-side, key in GOOGLE_MAPS_API_KEY, never guess, never block.

NO TEST HERE TOUCHES THE NETWORK. Google is an httpx.MockTransport plugged into distance._TRANSPORT,
so the REAL request-building and response-parsing code runs and nothing leaves the process.
"""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

import distance
import main
import nav_access

ADDR = {"address": "100 Main St", "city": "Wichita", "state": "ks", "zip": "67202"}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Fresh cache + rate buckets, a key set, and a transport that FAILS LOUDLY if used unmocked."""
    distance._cache.clear()
    distance._rate_hits.clear()
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key-not-real")

    def boom(request):
        raise AssertionError("a test reached the real network: %s" % request.url)
    monkeypatch.setattr(distance, "_TRANSPORT", httpx.MockTransport(boom))
    yield
    distance._cache.clear()
    distance._rate_hits.clear()


def _mock(monkeypatch, handler):
    calls = []

    def wrapped(request):
        calls.append(request)
        return handler(request)
    monkeypatch.setattr(distance, "_TRANSPORT", httpx.MockTransport(wrapped))
    return calls


def _ok(meters):
    return lambda request: httpx.Response(200, json={"routes": [{"distanceMeters": meters}]})


def test_a_real_answer_is_driving_miles_to_one_decimal(monkeypatch):
    calls = _mock(monkeypatch, _ok(160934))
    out = distance.lookup(**{"address": "100 Main St", "city": "Wichita", "state": "ks",
                             "zip_code": "67202"})
    assert out["ok"] is True and out["miles"] == 100.0 and out["reason"] == ""
    assert len(calls) == 1
    req = calls[0]
    body = json.loads(req.content)
    # FROM THE OFFICE, TO THE JOB, BY ROAD -- the three facts the price rests on.
    assert body["origin"] == {"address": "1707 E. 123rd Ter, Olathe, KS 66061"}
    assert body["destination"] == {"address": "100 Main St, Wichita, KS 67202"}
    assert body["travelMode"] == "DRIVE"
    # The key rides in a header (never the URL, so it cannot leak into a log line) and only the
    # distance is asked for, which keeps the request in Google's cheapest field-mask tier.
    assert req.headers["X-Goog-Api-Key"] == "test-key-not-real"
    assert req.headers["X-Goog-FieldMask"] == "routes.distanceMeters"
    assert "test-key" not in str(req.url)


def test_no_key_means_unknown_and_nothing_leaves_the_process(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    calls = _mock(monkeypatch, _ok(1000))
    out = distance.lookup(**{"address": "100 Main St", "city": "Wichita", "state": "KS",
                             "zip_code": ""})
    assert out["miles"] is None and out["reason"] == "no_key" and out["ok"] is False
    assert calls == [], "no key must mean no call"


@pytest.mark.parametrize("addr,city,state,zip_code", [
    ("", "Wichita", "KS", "67202"),            # no street
    ("100 Main St", "", "", ""),               # a street with nothing to place it by
    ("100 Main St", "Wichita", "", ""),        # city without a state
    ("   ", "  ", "", ""),
])
def test_a_thin_address_is_never_looked_up(monkeypatch, addr, city, state, zip_code):
    calls = _mock(monkeypatch, _ok(1000))
    out = distance.lookup(addr, city, state, zip_code)
    assert out["miles"] is None and out["reason"] == "incomplete"
    assert calls == []


def test_a_slow_or_dead_google_is_unknown_not_an_exception(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)
    _mock(monkeypatch, timeout)
    out = distance.lookup(**{"address": "1 A St", "city": "Topeka", "state": "KS", "zip_code": ""})
    assert out["miles"] is None and out["reason"] == "error"


@pytest.mark.parametrize("status,reason", [(400, "not_found"), (404, "not_found"),
                                           (403, "error"), (429, "error"), (500, "error")])
def test_google_refusals_are_unknown_with_a_reason(monkeypatch, status, reason):
    _mock(monkeypatch, lambda request: httpx.Response(status, json={"error": {"message": "x"}}))
    out = distance.lookup(**{"address": "1 A St", "city": "Topeka", "state": "KS", "zip_code": ""})
    assert out["miles"] is None and out["reason"] == reason


def test_a_200_with_no_route_is_not_found(monkeypatch):
    _mock(monkeypatch, lambda request: httpx.Response(200, json={}))
    out = distance.lookup(**{"address": "1 A St", "city": "Topeka", "state": "KS", "zip_code": ""})
    assert out["miles"] is None and out["reason"] == "not_found"


def test_a_repeat_address_costs_nothing_and_errors_are_never_kept(monkeypatch):
    calls = _mock(monkeypatch, _ok(80467))
    kw = {"address": "9 Elm St", "city": "Salina", "state": "KS", "zip_code": ""}
    a = distance.lookup(**kw)
    b = distance.lookup(**dict(kw, address="9  ELM st"))     # same address, different spelling
    assert a["miles"] == b["miles"] == 50.0 and len(calls) == 1
    # An error is not remembered: the next ask goes out again.
    distance._cache.clear()
    _mock(monkeypatch, lambda request: httpx.Response(500))
    assert distance.lookup(**kw)["reason"] == "error"
    calls2 = _mock(monkeypatch, _ok(80467))
    assert distance.lookup(**kw)["miles"] == 50.0 and len(calls2) == 1


# ── the route ───────────────────────────────────────────────────────────────────

def test_the_route_answers_200_with_miles(monkeypatch):
    _mock(monkeypatch, _ok(160934))
    r = TestClient(main.app).post("/api/distance", json=ADDR)
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True and j["miles"] == 100.0 and j["office"] == "Olathe office"


def test_the_route_is_200_even_when_unknown(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    r = TestClient(main.app).post("/api/distance", json=ADDR)
    assert r.status_code == 200
    assert r.json()["miles"] is None and r.json()["reason"] == "no_key"


def test_the_route_needs_a_sign_in(monkeypatch, real_verify_token):
    """Behind the auth gate like every /api route: a logged-out caller cannot spend the Google key."""
    monkeypatch.setattr(main.supabase_client, "verify_token", real_verify_token)
    r = TestClient(main.app).post("/api/distance", json=ADDR)
    assert r.status_code == 401, r.text
    assert main._auth_is_public("/api/distance", "POST") is False


def test_no_tab_owns_the_route_so_no_policy_can_blank_it_mid_bid():
    """Same reasoning nav_access records for /api/library/items: the estimate step that calls this
    is used by every estimator, and a per-tab gate would silently blank the distance halfway through
    a bid. Mutation: add "/api/distance" to a TABS entry's `api` and this fails."""
    for href, tab in nav_access.TABS.items():
        for prefix in tab["api"]:
            assert not nav_access.prefix_matches("/api/distance", prefix), (href, prefix)


def test_a_flood_is_cut_off_with_a_clear_answer_not_an_error(monkeypatch):
    _mock(monkeypatch, _ok(160934))
    c = TestClient(main.app)
    for i in range(distance._RATE_MAX):
        assert c.post("/api/distance", json=dict(ADDR, address="%d Main St" % i)).json()["ok"]
    j = c.post("/api/distance", json=ADDR).json()
    assert j["ok"] is False and j["miles"] is None and j["reason"] == "busy"
