"""POST /api/distance -- driving miles from the Olathe office to the job.

Kyle's 9/18 notes: take the "70 mile slider" off intake and work the distance out from the address.
Hanz, 2026-10-05: driving miles, server-side, never guess, never block.
Hanz, 2026-10-12: "find a free routes api without using google maps". With no GOOGLE_MAPS_API_KEY
(the state of prod and staging) the answer now comes from the US Census geocoder + the OSRM public
router. With a key set, Google Routes is tried first and the free pair is the fallback.

NO TEST HERE TOUCHES THE NETWORK. Every service is an httpx.MockTransport plugged into
distance._TRANSPORT, so the REAL request-building and response-parsing code runs and nothing leaves
the process. A request to a host a test did not expect is recorded and fails the test at teardown
(raising inside the transport would be swallowed by the module's own "any failure is unknown" catch).
One live smoke test exists and is skipped unless TW_LIVE_DISTANCE=1.
"""
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

import distance
import main
import nav_access

ADDR = {"address": "100 Main St", "city": "Wichita", "state": "ks", "zip": "67202"}
KW = {"address": "100 Main St", "city": "Wichita", "state": "ks", "zip_code": "67202"}

GOOGLE_HOST = "routes.googleapis.com"
CENSUS_HOST = "geocoding.geo.census.gov"
OSRM_HOST = "router.project-osrm.org"

_violations = []


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Fresh cache + rate buckets, NO key (the production default), and a transport that records
    any request nobody expected."""
    distance._cache.clear()
    distance._rate_hits.clear()
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    del _violations[:]

    def boom(request):
        _violations.append(str(request.url))
        raise AssertionError("a test reached the real network: %s" % request.url)
    monkeypatch.setattr(distance, "_TRANSPORT", httpx.MockTransport(boom))
    yield
    distance._cache.clear()
    distance._rate_hits.clear()
    assert not _violations, "unexpected requests: %s" % _violations


def _mock(monkeypatch, google=None, census=None, osrm=None):
    """Route each host to its handler; returns the list of requests seen, in order."""
    calls = []
    table = {GOOGLE_HOST: google, CENSUS_HOST: census, OSRM_HOST: osrm}

    def handler(request):
        calls.append(request)
        h = table.get(request.url.host)
        if h is None:
            _violations.append(str(request.url))
            raise AssertionError("unexpected host: %s" % request.url.host)
        return h(request)
    monkeypatch.setattr(distance, "_TRANSPORT", httpx.MockTransport(handler))
    return calls


def _hosts(calls):
    return [c.url.host for c in calls]


def _g_ok(meters):
    return lambda request: httpx.Response(200, json={"routes": [{"distanceMeters": meters}]})


def _c_match(lon=-97.33, lat=37.69, state="KS"):
    body = {"result": {"addressMatches": [{
        "matchedAddress": "100 MAIN ST, WICHITA, KS, 67202",
        "coordinates": {"x": lon, "y": lat},
        "addressComponents": {"state": state}}]}}
    return lambda request: httpx.Response(200, json=body)


def _c_none(request):
    return httpx.Response(200, json={"result": {"addressMatches": []}})


def _o_ok(meters):
    return lambda request: httpx.Response(200, json={"code": "Ok", "routes": [{"distance": meters}]})


def _raise(exc_cls):
    def h(request):
        raise exc_cls("slow", request=request)
    return h


# -- the free pair (the default: no key) ---------------------------------------------------------

def test_free_answer_is_driving_miles_to_one_decimal_with_one_call_each(monkeypatch):
    calls = _mock(monkeypatch, census=_c_match(-97.33, 37.69), osrm=_o_ok(285130.4))
    out = distance.lookup(**KW)
    assert out["ok"] is True and out["miles"] == 177.2 and out["reason"] == ""
    # ONE geocode and ONE route, never two of either, and nothing went to Google.
    assert _hosts(calls) == [CENSUS_HOST, OSRM_HOST]
    census, osrm = calls
    q = dict(census.url.params)
    assert q["address"] == "100 Main St, Wichita, KS 67202"
    assert q["benchmark"] == "Public_AR_Current" and q["format"] == "json"
    # OSRM takes lon,lat and wants the OFFICE first, then the JOB: driving distance office -> job.
    assert osrm.url.path == "/route/v1/driving/-94.790320,38.903910;-97.330000,37.690000"
    assert dict(osrm.url.params) == {"overview": "false"}
    # A descriptive User-Agent on both: the OSRM demo server's usage policy asks for one.
    for c in calls:
        assert c.headers["User-Agent"] == distance.USER_AGENT
        contact = c.headers["User-Agent"].split("(+")[1].rstrip(")")
        assert urlparse(contact).hostname == "proposals.wetreadwell.com"


def test_geocoder_no_match_is_not_found_and_osrm_is_never_asked(monkeypatch):
    calls = _mock(monkeypatch, census=_c_none, osrm=_o_ok(1000))
    out = distance.lookup(**KW)
    assert out["miles"] is None and out["ok"] is False and out["reason"] == "not_found"
    assert _hosts(calls) == [CENSUS_HOST]


def test_a_match_in_another_state_than_typed_is_not_found(monkeypatch):
    calls = _mock(monkeypatch, census=_c_match(state="MO"), osrm=_o_ok(1000))
    out = distance.lookup(**KW)
    assert out["miles"] is None and out["reason"] == "not_found"
    assert _hosts(calls) == [CENSUS_HOST]


def test_osrm_no_route_is_not_found(monkeypatch):
    _mock(monkeypatch, census=_c_match(),
          osrm=lambda r: httpx.Response(200, json={"code": "NoRoute", "message": "x"}))
    out = distance.lookup(**KW)
    assert out["miles"] is None and out["reason"] == "not_found"


@pytest.mark.parametrize("status,body", [(500, {}), (429, {"message": "slow down"}),
                                         (400, {"code": "InvalidUrl"}),
                                         (200, {"code": "Ok", "routes": []}),
                                         (200, {"code": "Ok", "routes": [{"distance": "x"}]})])
def test_osrm_trouble_is_unknown_with_an_error_reason(monkeypatch, status, body):
    _mock(monkeypatch, census=_c_match(), osrm=lambda r: httpx.Response(status, json=body))
    out = distance.lookup(**KW)
    assert out["miles"] is None and out["ok"] is False and out["reason"] == "error"


@pytest.mark.parametrize("which", ["census", "osrm"])
def test_a_timeout_in_either_service_is_unknown_not_an_exception(monkeypatch, which):
    census = _raise(httpx.ReadTimeout) if which == "census" else _c_match()
    osrm = _raise(httpx.ConnectTimeout) if which == "osrm" else _o_ok(1000)
    _mock(monkeypatch, census=census, osrm=osrm)
    out = distance.lookup(**KW)
    assert out["miles"] is None and out["reason"] == "error"


@pytest.mark.parametrize("resp", [httpx.Response(503), httpx.Response(200, text="<html>down</html>")])
def test_a_geocoder_outage_is_an_error_not_a_no_match(monkeypatch, resp):
    calls = _mock(monkeypatch, census=lambda r: resp, osrm=_o_ok(1000))
    out = distance.lookup(**KW)
    assert out["miles"] is None and out["reason"] == "error"
    assert _hosts(calls) == [CENSUS_HOST]


def test_timeouts_are_short():
    assert 0 < distance.TIMEOUT_SECONDS <= 8


# -- a 200 that is not the shape the service promised is "unknown", never a 500 -------------------

_ODD_BODIES = [[1], "x", 7, {"code": "Ok", "routes": ["x"]}, {"code": "Ok", "routes": {"a": 1}},
               {"code": "Ok", "routes": [[1]]}]


@pytest.mark.parametrize("body", _ODD_BODIES)
def test_an_odd_osrm_200_is_an_error_not_an_exception(monkeypatch, body):
    _mock(monkeypatch, census=_c_match(), osrm=lambda r: httpx.Response(200, json=body))
    out = distance.lookup(**KW)
    assert out["ok"] is False and out["miles"] is None and out["reason"] == "error"


@pytest.mark.parametrize("comps", [[1], "KS", 5])
def test_an_odd_census_match_is_not_an_exception(monkeypatch, comps):
    body = {"result": {"addressMatches": [{"coordinates": {"x": -97.3, "y": 37.7},
                                           "addressComponents": comps}]}}
    _mock(monkeypatch, census=lambda r: httpx.Response(200, json=body), osrm=_o_ok(1000))
    out = distance.lookup(**KW)           # must answer, whatever it answers
    assert out["ok"] in (True, False) and out["reason"] in ("", "error", "not_found")


@pytest.mark.parametrize("body", [[1], "x", {"result": []}, {"result": {"addressMatches": {"a": 1}}},
                                  {"result": {"addressMatches": ["x"]}}])
def test_an_odd_census_200_is_not_an_exception(monkeypatch, body):
    _mock(monkeypatch, census=lambda r: httpx.Response(200, json=body), osrm=_o_ok(1000))
    out = distance.lookup(**KW)
    assert out["ok"] is False and out["miles"] is None and out["reason"] in ("error", "not_found")


# -- one deadline for the whole lookup, shorter than the page's own abort ------------------------

class _Clock:
    t = 100.0


def _spy_client(monkeypatch):
    """Records the timeout each outgoing call was given, and lets a handler move the fake clock."""
    seen = []
    real = httpx.Client

    def spy(*a, **kw):
        seen.append(kw.get("timeout"))
        return real(*a, **kw)
    monkeypatch.setattr(distance.httpx, "Client", spy)
    clock = _Clock()
    clock.t = 100.0
    monkeypatch.setattr(distance, "_now", lambda: clock.t)
    return seen, clock


def test_the_second_call_only_gets_what_the_first_left(monkeypatch):
    seen, clock = _spy_client(monkeypatch)

    def slow_census(request):
        clock.t += distance.TOTAL_BUDGET_SECONDS - 1.0       # census ate all but one second
        return _c_match()(request)
    _mock(monkeypatch, census=slow_census, osrm=_o_ok(160934))
    out = distance.lookup(**KW)
    assert out["ok"] is True and out["miles"] == 100.0
    assert len(seen) == 2
    assert seen[0].read == distance.TIMEOUT_SECONDS          # full allowance while the budget is whole
    assert 0 < seen[1].read <= 1.0 + 1e-6 and seen[1].connect <= 1.0 + 1e-6


def test_a_spent_budget_skips_the_route_call_and_says_error(monkeypatch):
    seen, clock = _spy_client(monkeypatch)

    def slow_census(request):
        clock.t += distance.TOTAL_BUDGET_SECONDS + 0.5
        return _c_match()(request)
    calls = _mock(monkeypatch, census=slow_census, osrm=_o_ok(160934))
    out = distance.lookup(**KW)
    assert out["ok"] is False and out["reason"] == "error"
    assert _hosts(calls) == [CENSUS_HOST]


def test_the_page_waits_longer_than_the_server_ever_can():
    """A lookup that succeeds must never be shown as "did not answer": the page's abort (ms) has to
    sit past the server's worst case."""
    src = (Path(main.__file__).resolve().parent.parent / "frontend" / "js" / "polish-estimate.js"
           ).read_text(encoding="utf-8")
    marker = "AbortSignal.timeout("
    assert src.count(marker) >= 1
    after = src.split(marker, 1)[1]
    digits = ""
    for ch in after:
        if not ch.isdigit():
            break
        digits += ch
    assert digits, "AbortSignal.timeout() has no literal number"
    assert int(digits) / 1000.0 > distance.WORST_CASE_SECONDS


@pytest.mark.parametrize("addr,city,state,zip_code", [
    ("", "Wichita", "KS", "67202"),            # no street
    ("100 Main St", "", "", ""),               # a street with nothing to place it by
    ("100 Main St", "Wichita", "", ""),        # city without a state
    ("   ", "  ", "", ""),
])
def test_a_thin_address_is_never_looked_up(monkeypatch, addr, city, state, zip_code):
    calls = _mock(monkeypatch, google=_g_ok(1000), census=_c_match(), osrm=_o_ok(1000))
    out = distance.lookup(addr, city, state, zip_code)
    assert out["miles"] is None and out["reason"] == "incomplete"
    assert calls == []


def test_a_repeat_address_costs_nothing_and_errors_are_never_kept(monkeypatch):
    calls = _mock(monkeypatch, census=_c_match(), osrm=_o_ok(80467))
    kw = {"address": "9 Elm St", "city": "Salina", "state": "KS", "zip_code": ""}
    a = distance.lookup(**kw)
    b = distance.lookup(**dict(kw, address="9  ELM st"))     # same address, different spelling
    assert a["miles"] == b["miles"] == 50.0
    assert len(calls) == 2, "the second lookup must be served from the cache"
    # An error is not remembered: the next ask goes out again.
    distance._cache.clear()
    _mock(monkeypatch, census=_c_match(), osrm=lambda r: httpx.Response(500))
    assert distance.lookup(**kw)["reason"] == "error"
    calls2 = _mock(monkeypatch, census=_c_match(), osrm=_o_ok(80467))
    assert distance.lookup(**kw)["miles"] == 50.0 and len(calls2) == 2


def test_not_found_is_remembered_briefly_so_a_typo_is_not_re_asked(monkeypatch):
    calls = _mock(monkeypatch, census=_c_none)
    assert distance.lookup(**KW)["reason"] == "not_found"
    assert distance.lookup(**KW)["reason"] == "not_found"
    assert len(calls) == 1


def test_the_cache_is_bounded(monkeypatch):
    _mock(monkeypatch, census=_c_match(), osrm=_o_ok(1000))
    monkeypatch.setattr(distance, "_CACHE_MAX", 5)
    for i in range(20):
        distance.lookup("%d Main St" % i, "Wichita", "KS", "")
    assert len(distance._cache) <= 5


# -- Google first when a key is set, the free pair as the fallback --------------------------------

def test_with_a_key_google_answers_first_and_the_free_pair_is_never_asked(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key-not-real")
    calls = _mock(monkeypatch, google=_g_ok(160934), census=_c_match(), osrm=_o_ok(1))
    out = distance.lookup(**KW)
    assert out["ok"] is True and out["miles"] == 100.0
    assert _hosts(calls) == [GOOGLE_HOST]
    req = calls[0]
    body = json.loads(req.content)
    # FROM THE OFFICE, TO THE JOB, BY ROAD -- the three facts the price rests on.
    assert body["origin"] == {"address": "1707 E. 123rd Ter, Olathe, KS 66061"}
    assert body["destination"] == {"address": "100 Main St, Wichita, KS 67202"}
    assert body["travelMode"] == "DRIVE"
    # The key rides in a header (never the URL, so it cannot leak into a log line).
    assert req.headers["X-Goog-Api-Key"] == "test-key-not-real"
    assert req.headers["X-Goog-FieldMask"] == "routes.distanceMeters"
    assert "test-key" not in str(req.url)


@pytest.mark.parametrize("google", [
    lambda r: httpx.Response(403, json={"error": {"message": "key rejected"}}),
    lambda r: httpx.Response(500),
    lambda r: httpx.Response(429),
    _raise(httpx.ReadTimeout),
])
def test_when_google_fails_the_free_pair_answers(monkeypatch, google):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key-not-real")
    calls = _mock(monkeypatch, google=google, census=_c_match(), osrm=_o_ok(285130.4))
    out = distance.lookup(**KW)
    assert out["ok"] is True and out["miles"] == 177.2
    assert _hosts(calls) == [GOOGLE_HOST, CENSUS_HOST, OSRM_HOST]


def test_when_both_fail_the_answer_is_unknown(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key-not-real")
    _mock(monkeypatch, google=lambda r: httpx.Response(500), census=_c_none)
    out = distance.lookup(**KW)
    assert out["ok"] is False and out["miles"] is None and out["reason"] == "not_found"


def test_without_a_key_google_is_never_called(monkeypatch):
    calls = _mock(monkeypatch, google=_g_ok(1), census=_c_match(), osrm=_o_ok(160934))
    assert distance.lookup(**KW)["miles"] == 100.0
    assert GOOGLE_HOST not in _hosts(calls)


@pytest.mark.parametrize("status,reason", [(400, "not_found"), (404, "not_found"),
                                           (403, "error"), (429, "error"), (500, "error")])
def test_google_refusals_map_to_a_reason(monkeypatch, status, reason):
    _mock(monkeypatch, google=lambda r: httpx.Response(status, json={"error": {"message": "x"}}))
    assert distance._google("1 A St, Topeka, KS", "k") == (None, reason)


def test_a_google_200_with_no_route_is_not_found(monkeypatch):
    _mock(monkeypatch, google=lambda r: httpx.Response(200, json={}))
    assert distance._google("1 A St, Topeka, KS", "k") == (None, "not_found")


def test_a_google_timeout_is_an_error(monkeypatch):
    _mock(monkeypatch, google=_raise(httpx.ReadTimeout))
    assert distance._google("1 A St, Topeka, KS", "k") == (None, "error")


# -- the office coordinates -----------------------------------------------------------------------

def test_the_office_coordinates_are_the_pinned_census_result_for_the_office_address():
    # Computed once on 2026-10-12 from the Census geocoder for OFFICE_ADDRESS and pinned, so a
    # lookup never spends a second geocode on the office. Mutation: nudge either constant.
    assert (distance.OFFICE_LON, distance.OFFICE_LAT) == (-94.79032, 38.90391)
    # ... and they really are in Olathe, KS (a swapped lat/lon or a sign slip lands far outside).
    assert 38.8 < distance.OFFICE_LAT < 39.0
    assert -94.9 < distance.OFFICE_LON < -94.7


def test_the_office_address_is_the_one_used_elsewhere_in_the_repo():
    src = (Path(__file__).resolve().parents[1] / "prepare_cover_letter_templates.py").read_text(
        encoding="utf-8")
    assert distance.OFFICE_ADDRESS in src


@pytest.mark.skipif(not os.environ.get("TW_LIVE_DISTANCE"),
                    reason="live smoke test: set TW_LIVE_DISTANCE=1 to hit the real free services")
def test_live_smoke_olathe_to_wichita(monkeypatch):
    monkeypatch.setattr(distance, "_TRANSPORT", None)
    out = distance.lookup("455 N Main St", "Wichita", "KS", "67202")
    assert out["ok"] is True and 170 < out["miles"] < 185


# -- the route -------------------------------------------------------------------------------------

def test_the_route_answers_200_with_miles(monkeypatch):
    _mock(monkeypatch, census=_c_match(), osrm=_o_ok(160934))
    r = TestClient(main.app).post("/api/distance", json=ADDR)
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True and j["miles"] == 100.0 and j["office"] == "Olathe office"


def test_the_route_is_200_even_when_unknown(monkeypatch):
    _mock(monkeypatch, census=_c_none)
    r = TestClient(main.app).post("/api/distance", json=ADDR)
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is False and j["miles"] is None and j["reason"] == "not_found"
    assert set(j) >= {"ok", "miles", "reason", "office"}


def test_the_route_is_200_when_the_services_are_down(monkeypatch):
    _mock(monkeypatch, census=_raise(httpx.ConnectTimeout))
    r = TestClient(main.app).post("/api/distance", json=ADDR)
    assert r.status_code == 200
    assert r.json()["miles"] is None and r.json()["reason"] == "error"


def test_the_route_needs_a_sign_in(monkeypatch, real_verify_token):
    """Behind the auth gate like every /api route: a logged-out caller cannot spend the free
    services' goodwill."""
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
    _mock(monkeypatch, census=_c_match(), osrm=_o_ok(160934))
    c = TestClient(main.app)
    for i in range(distance._RATE_MAX):
        assert c.post("/api/distance", json=dict(ADDR, address="%d Main St" % i)).json()["ok"]
    j = c.post("/api/distance", json=ADDR).json()
    assert j["ok"] is False and j["miles"] is None and j["reason"] == "busy"
