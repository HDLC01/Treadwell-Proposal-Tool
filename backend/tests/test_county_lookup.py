"""POST /api/county -- the county (and incorporated city) a job address sits in.

Hanz, 2026-10-13, looking at the empty County remodel tax box on intake: "shouldn't this autofill
based on the address?" The server answers the county from the same free US Census geocoder the
distance lookup already uses (its geographies endpoint, no key), and the intake pages fill the box
from it (js/county-autofill.js, see tests/test_county_autofill.py for the page side).

NO TEST HERE TOUCHES THE NETWORK. Census is an httpx.MockTransport plugged into distance._TRANSPORT,
so the REAL request-building and response-parsing code runs. A request to a host the test did not
expect is recorded and fails the test at teardown (raising inside the transport would be swallowed
by the module's own "any failure is unknown" catch).
"""
import httpx
import pytest
from fastapi.testclient import TestClient

import distance
import main
import nav_access

ADDR = {"address": "455 N Main St", "city": "Wichita", "state": "ks", "zip": "67202"}
KW = {"address": "455 N Main St", "city": "Wichita", "state": "ks", "zip_code": "67202"}
CENSUS_HOST = "geocoding.geo.census.gov"

_violations = []


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    distance._county_cache.clear()
    distance._rate_hits.clear()
    del _violations[:]

    def boom(request):
        _violations.append(str(request.url))
        raise AssertionError("a test reached the real network: %s" % request.url)
    monkeypatch.setattr(distance, "_TRANSPORT", httpx.MockTransport(boom))
    yield
    distance._county_cache.clear()
    distance._rate_hits.clear()
    assert not _violations, "unexpected requests: %s" % _violations


def _mock(monkeypatch, census):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host != CENSUS_HOST:
            _violations.append(str(request.url))
            raise AssertionError("unexpected host: %s" % request.url.host)
        return census(request)
    monkeypatch.setattr(distance, "_TRANSPORT", httpx.MockTransport(handler))
    return calls


def _geo(county="Sedgwick County", fips="20173", place=None, state="KS", comps=True, zip_code=None):
    """A Census geographies answer shaped like the real one (verified 2026-10-13 against 455 N Main
    St, Wichita KS): Counties[0].NAME is the full name, Incorporated Places[0].BASENAME the city."""
    geos = {"Counties": [{"NAME": county, "BASENAME": county.replace(" County", ""), "GEOID": fips,
                          "STATE": "20"}]}
    if place:
        geos["Incorporated Places"] = [{"NAME": place + " city", "BASENAME": place}]
    m = {"matchedAddress": "455 N MAIN ST, WICHITA, KS, 67202", "geographies": geos}
    if comps:
        m["addressComponents"] = {"state": state}
        if zip_code:
            m["addressComponents"]["zip"] = zip_code
    body = {"result": {"addressMatches": [m]}}
    return lambda request: httpx.Response(200, json=body)


def _none(request):
    return httpx.Response(200, json={"result": {"addressMatches": []}})


def _raise(exc_cls):
    def h(request):
        raise exc_cls("slow", request=request)
    return h


# -- a match -------------------------------------------------------------------------------------

def test_a_match_names_the_county_with_one_call_and_the_right_request(monkeypatch):
    calls = _mock(monkeypatch, _geo(place="Wichita"))
    out = distance.county_lookup(**KW)
    assert out["ok"] is True and out["reason"] == ""
    assert out["county"] == "Sedgwick County" and out["state"] == "KS"
    assert out["fips"] == "20173" and out["place"] == "Wichita"
    assert len(calls) == 1
    req = calls[0]
    assert req.url.path == "/geocoder/geographies/onelineaddress"
    q = dict(req.url.params)
    assert q["address"] == "455 N Main St, Wichita, KS 67202"
    assert q["benchmark"] == "Public_AR_Current" and q["vintage"] == "Current_Current"
    assert q["format"] == "json"
    # Both layers in the one call: the county, and the city the picker may prefer.
    assert set(q["layers"].split(",")) == {"Counties", "Incorporated Places"}
    assert req.headers["User-Agent"] == distance.USER_AGENT


def test_a_match_in_another_zip_than_typed_keeps_the_county_but_distrusts_the_city(monkeypatch):
    """Real, 2026-10-13: 701 N 7th St, Kansas City KS 66101 came back as the same street in 66111,
    in Edwardsville. The county is still right (Wyandotte); the city is not, so the page is told not
    to trust it and uses the city the estimator typed."""
    _mock(monkeypatch, _geo(county="Wyandotte County", fips="20209", place="Edwardsville", zip_code="66111"))
    out = distance.county_lookup("701 N 7th St", "Kansas City", "KS", "66101")
    assert out["ok"] is True and out["county"] == "Wyandotte County"
    assert out["place_sure"] is False


def test_the_same_zip_or_no_zip_typed_trusts_the_city(monkeypatch):
    _mock(monkeypatch, _geo(place="Wichita", zip_code="67202"))
    assert distance.county_lookup("455 N Main St", "Wichita", "KS", "67202-1234")["place_sure"] is True
    distance._county_cache.clear()
    assert distance.county_lookup("455 N Main St", "Wichita", "KS", "")["place_sure"] is True


def test_an_address_in_no_incorporated_place_has_an_empty_place(monkeypatch):
    _mock(monkeypatch, _geo(county="Johnson County", fips="20091"))
    out = distance.county_lookup(**KW)
    assert out["ok"] is True and out["county"] == "Johnson County" and out["place"] == ""


# -- no answer, and never a guess ----------------------------------------------------------------

def test_no_match_is_not_found(monkeypatch):
    _mock(monkeypatch, _none)
    out = distance.county_lookup(**KW)
    assert out["ok"] is False and out["reason"] == "not_found" and out["county"] == ""


def test_a_match_with_no_county_layer_is_not_found(monkeypatch):
    def census(request):
        return httpx.Response(200, json={"result": {"addressMatches": [
            {"geographies": {"Counties": []}, "addressComponents": {"state": "KS"}}]}})
    _mock(monkeypatch, census)
    out = distance.county_lookup(**KW)
    assert out["ok"] is False and out["reason"] == "not_found"


def test_a_match_in_another_state_than_typed_is_not_found(monkeypatch):
    _mock(monkeypatch, _geo(state="MO"))
    out = distance.county_lookup(**KW)
    assert out["ok"] is False and out["reason"] == "not_found" and out["county"] == ""


@pytest.mark.parametrize("body", [
    "not json at all",
    "[]",
    '{"result": "nope"}',
    '{"result": {"addressMatches": "x"}}',
    '{"result": {"addressMatches": [null]}}',
    '{"result": {"addressMatches": [{"geographies": []}]}}',
    '{"result": {"addressMatches": [{"geographies": {"Counties": "x"}}]}}',
    '{"result": {"addressMatches": [{"geographies": {"Counties": [{"NAME": 7}]}}]}}',
])
def test_an_odd_200_is_never_an_exception_and_never_a_fill(monkeypatch, body):
    _mock(monkeypatch, lambda request: httpx.Response(200, content=body.encode()))
    out = distance.county_lookup(**KW)
    assert out["ok"] is False and out["county"] == ""
    assert out["reason"] in ("error", "not_found")


@pytest.mark.parametrize("handler", [
    lambda request: httpx.Response(500),
    lambda request: httpx.Response(429),
    _raise(httpx.ConnectTimeout),
    _raise(httpx.ReadTimeout),
])
def test_an_outage_or_a_timeout_is_ok_false_with_an_error_reason(monkeypatch, handler):
    _mock(monkeypatch, handler)
    out = distance.county_lookup(**KW)
    assert out["ok"] is False and out["reason"] == "error" and out["county"] == ""


@pytest.mark.parametrize("addr, city, state, zip_code", [
    ("", "Wichita", "KS", "67202"),          # no street
    ("455 N Main St", "", "", ""),           # nothing to place it
    ("455 N Main St", "Wichita", "", ""),    # a city with no state
    ("   ", "Wichita", "KS", "67202"),
])
def test_a_thin_address_is_never_looked_up(monkeypatch, addr, city, state, zip_code):
    calls = _mock(monkeypatch, _geo())
    out = distance.county_lookup(addr, city, state, zip_code)
    assert out["ok"] is False and out["reason"] == "incomplete"
    assert calls == []


# -- the cache -----------------------------------------------------------------------------------

def test_a_repeat_address_costs_nothing_and_errors_are_never_kept(monkeypatch):
    calls = _mock(monkeypatch, _raise(httpx.ReadTimeout))
    assert distance.county_lookup(**KW)["reason"] == "error"
    assert distance.county_lookup(**KW)["reason"] == "error"
    assert len(calls) == 2, "an error was cached"
    calls = _mock(monkeypatch, _geo(place="Wichita"))
    first = distance.county_lookup(**KW)
    again = distance.county_lookup(**dict(KW, address="455  N MAIN ST"))   # same address, spelled loosely
    assert len(calls) == 1, "the repeat went back to the network"
    assert first["ok"] and again["ok"] and again["county"] == "Sedgwick County"
    assert again["place"] == "Wichita" and again["fips"] == "20173"


def test_not_found_is_remembered_briefly(monkeypatch):
    calls = _mock(monkeypatch, _none)
    assert distance.county_lookup(**KW)["reason"] == "not_found"
    assert distance.county_lookup(**KW)["reason"] == "not_found"
    assert len(calls) == 1


def test_the_county_cache_is_separate_from_the_distance_cache(monkeypatch):
    """A cached distance for an address must not answer a county question (or the reverse): the two
    caches hold different things under the same key."""
    distance._cache_put(distance._key("455 N Main St, Wichita, KS 67202"), 12.3, "", 3600)
    calls = _mock(monkeypatch, _geo())
    out = distance.county_lookup(**KW)
    assert len(calls) == 1 and out["county"] == "Sedgwick County"
    distance._cache.clear()


def test_the_county_cache_is_bounded(monkeypatch):
    _mock(monkeypatch, _geo())
    for i in range(distance._CACHE_MAX + 5):
        distance.county_lookup(**dict(KW, address="%d Main St" % i))
    assert len(distance._county_cache) <= distance._CACHE_MAX


# -- the route -------------------------------------------------------------------------------------

def test_the_route_answers_200_with_the_county(monkeypatch):
    _mock(monkeypatch, _geo(place="Wichita"))
    r = TestClient(main.app).post("/api/county", json=ADDR)
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True and j["county"] == "Sedgwick County" and j["state"] == "KS"
    assert j["place"] == "Wichita" and j["fips"] == "20173"


def test_the_route_is_200_even_when_unknown(monkeypatch):
    _mock(monkeypatch, _none)
    r = TestClient(main.app).post("/api/county", json=ADDR)
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is False and j["county"] == "" and j["reason"] == "not_found"


def test_the_route_is_200_when_the_service_is_down(monkeypatch):
    _mock(monkeypatch, _raise(httpx.ConnectTimeout))
    r = TestClient(main.app).post("/api/county", json=ADDR)
    assert r.status_code == 200
    assert r.json()["ok"] is False and r.json()["reason"] == "error"


def test_the_route_needs_a_sign_in(monkeypatch, real_verify_token):
    """Behind the auth gate like /api/distance: a logged-out caller cannot spend the geocoder's
    goodwill."""
    monkeypatch.setattr(main.supabase_client, "verify_token", real_verify_token)
    r = TestClient(main.app).post("/api/county", json=ADDR)
    assert r.status_code == 401, r.text
    assert main._auth_is_public("/api/county", "POST") is False


def test_no_tab_owns_the_route_so_no_policy_can_blank_it_mid_bid():
    for href, tab in nav_access.TABS.items():
        for prefix in tab["api"]:
            assert not nav_access.prefix_matches("/api/county", prefix), (href, prefix)


def test_a_flood_is_cut_off_with_a_clear_answer_and_never_spends_the_distance_allowance(monkeypatch):
    _mock(monkeypatch, _geo())
    c = TestClient(main.app)
    for i in range(distance._RATE_MAX):
        assert c.post("/api/county", json=dict(ADDR, address="%d Main St" % i)).json()["ok"]
    j = c.post("/api/county", json=ADDR).json()
    assert j["ok"] is False and j["reason"] == "busy"
    # The distance route has its own counter: a county flood does not blank the Labor step's miles.
    assert distance._rate_hits and all(k.startswith("county:") for k in distance._rate_hits)
