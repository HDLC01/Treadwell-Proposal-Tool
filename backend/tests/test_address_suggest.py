"""POST /api/address-suggest -- the house numbers OpenStreetMap lacks, from the US Census geocoder.

Hanz, 2026-11-05: "there are some addresses that are missing". Photon (OSM) answers "8200 Nieman Road"
with the bare street; the Census knows 8200 NIEMAN RD, OVERLAND PARK, KS, 66214. The page
(js/address-lookup.js) asks this route when the text starts with a house number and Photon has no
row with it; the page half is tests/test_polish_intake_page.py (the address-lookup harness).

NO TEST HERE TOUCHES THE NETWORK. The Census is an httpx.MockTransport plugged into
distance._TRANSPORT (address_suggest goes through distance._census_get), so the real request-building
and parsing code runs. A request the test did not expect is recorded and fails the test at teardown.
"""
import copy
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

import address_suggest
import distance
import main
import nav_access

CENSUS_HOST = "geocoding.geo.census.gov"
FRONTEND = Path(__file__).resolve().parents[2] / "frontend"

# The real answer for "8200 Nieman Rd, KS", recorded 2026-11-05 (benchmark Public_AR_Current).
# fromAddress is the START of the block's range (8250 Nieman Rd answers fromAddress 8200 too), so the
# house number has to come from matchedAddress.
NIEMAN = {"result": {
    "input": {"address": {"address": "8200 Nieman Rd, KS"},
              "benchmark": {"isDefault": True, "id": "4", "benchmarkName": "Public_AR_Current",
                            "benchmarkDescription": "Public Address Ranges - Current Benchmark"}},
    "addressMatches": [{
        "tigerLine": {"side": "R", "tigerLineId": "91322416"},
        "coordinates": {"x": -94.714617025191, "y": 38.98102368563},
        "addressComponents": {"zip": "66214", "streetName": "NIEMAN", "preType": "",
                              "city": "OVERLAND PARK", "preDirection": "", "suffixDirection": "",
                              "fromAddress": "8200", "state": "KS", "suffixType": "RD",
                              "toAddress": "8298", "suffixQualifier": "", "preQualifier": ""},
        "matchedAddress": "8200 NIEMAN RD, OVERLAND PARK, KS, 66214"}]}}

NONE = {"result": {"addressMatches": []}}


def _match(matched, x, y, state):
    parts = [p.strip() for p in matched.split(",")]
    return {"coordinates": {"x": x, "y": y}, "matchedAddress": matched,
            "addressComponents": {"fromAddress": "100", "preDirection": "", "streetName": "MAIN",
                                  "suffixType": "ST", "suffixDirection": "", "city": parts[1],
                                  "state": state, "zip": parts[3]}}


_violations = []


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    address_suggest._cache.clear()
    distance._rate_hits.clear()
    del _violations[:]

    def boom(request):
        _violations.append(str(request.url))
        raise AssertionError("a test reached the real network: %s" % request.url)
    monkeypatch.setattr(distance, "_TRANSPORT", httpx.MockTransport(boom))
    yield
    address_suggest._cache.clear()
    distance._rate_hits.clear()
    assert not _violations, "unexpected requests: %s" % _violations


def _mock(monkeypatch, answer):
    """answer(asked_address) -> httpx.Response | dict (a 200 JSON body). Records every asked address."""
    asked = []

    def handler(request):
        if request.url.host != CENSUS_HOST:
            _violations.append(str(request.url))
            raise AssertionError("unexpected host: %s" % request.url.host)
        addr = parse_qs(urlparse(str(request.url)).query)["address"][0]
        asked.append(addr)
        got = answer(addr)
        return got if isinstance(got, httpx.Response) else httpx.Response(200, json=got)
    monkeypatch.setattr(distance, "_TRANSPORT", httpx.MockTransport(handler))
    return asked


def _kansas_only(addr):
    """Nieman Rd is in Kansas: every question but the Missouri one finds it."""
    return copy.deepcopy(NONE) if addr.endswith(", MO") else copy.deepcopy(NIEMAN)


# -- the parsing ----------------------------------------------------------------------------------

def test_the_recorded_census_answer_becomes_a_screen_row():
    rows = address_suggest.parse(NIEMAN, "KS")
    assert rows == [{"line1": "8200 Nieman Rd", "city": "Overland Park", "state": "KS",
                     "zip": "66214", "lat": 38.981024, "lon": -94.714617}]


def test_the_house_number_is_the_matched_one_never_the_range_start():
    body = copy.deepcopy(NIEMAN)
    m = body["result"]["addressMatches"][0]
    m["matchedAddress"] = "8250 NIEMAN RD, OVERLAND PARK, KS, 66214"     # fromAddress stays 8200
    assert address_suggest.parse(body)[0]["line1"] == "8250 Nieman Rd"


def test_title_case_keeps_directions_ordinals_and_apostrophes_readable():
    assert address_suggest.title("1707 E 123RD TER") == "1707 E 123rd Ter"
    assert address_suggest.title("LEE'S SUMMIT") == "Lee's Summit"
    assert address_suggest.title("O'FALLON") == "O'Fallon"
    assert address_suggest.title("100 NW BARRY RD") == "100 NW Barry Rd"


def test_a_match_in_another_state_or_without_a_point_is_skipped():
    assert address_suggest.parse(NIEMAN, "MO") == []
    body = copy.deepcopy(NIEMAN)
    del body["result"]["addressMatches"][0]["coordinates"]
    assert address_suggest.parse(body) == []
    for junk in (None, [], "x", {"result": None}, {"result": {"addressMatches": "nope"}}):
        assert address_suggest.parse(junk) == []


# -- which questions are asked ---------------------------------------------------------------------

def test_a_bare_street_is_asked_in_kansas_and_in_missouri_side_by_side(monkeypatch):
    asked = _mock(monkeypatch, _kansas_only)
    out = address_suggest.suggest("8200 Nieman Rd")
    assert sorted(asked) == ["8200 Nieman Rd, KS", "8200 Nieman Rd, MO"]
    assert out == {"ok": True, "reason": "",
                   "rows": [{"line1": "8200 Nieman Rd", "city": "Overland Park", "state": "KS",
                             "zip": "66214", "lat": 38.981024, "lon": -94.714617}]}


@pytest.mark.parametrize("q", ["8200 Nieman Rd, KS", "8200 Nieman Rd KS", "8200 Nieman Rd, Kansas",
                               "8200 Nieman Rd, Overland Park, KS 66214"])
def test_a_state_named_in_the_text_is_the_only_question(monkeypatch, q):
    asked = _mock(monkeypatch, _kansas_only)
    out = address_suggest.suggest(q)
    assert asked == [q]
    assert out["ok"] is True and out["rows"][0]["line1"] == "8200 Nieman Rd"


def test_a_zip_named_in_the_text_is_the_only_question(monkeypatch):
    asked = _mock(monkeypatch, lambda a: copy.deepcopy(NIEMAN))
    assert address_suggest.suggest("8200 Nieman Rd 66214")["ok"] is True
    assert asked == ["8200 Nieman Rd 66214"]


def test_court_is_not_connecticut_unless_after_a_comma():
    assert address_suggest.named_place("10 Oak Ct") == ("", False)
    assert address_suggest.named_place("10 Oak Ct, CT") == ("CT", False)


@pytest.mark.parametrize("q", ["Nieman Rd", "8200", "8200 N", "", None, "Treadwell office", 12345])
def test_no_house_number_and_street_means_no_question_at_all(q):
    # The autouse transport fails the test on any request.
    assert address_suggest.suggest(q) == {"ok": False, "rows": [], "reason": "thin"}


def test_the_nearest_three_come_first_across_both_states(monkeypatch):
    far = _match("100 MAIN ST, AGENCY, MO, 64401", -94.74, 39.69, "MO")       # ~55 mi
    near = _match("100 MAIN ST, BELTON, MO, 64012", -94.53, 38.81, "MO")      # ~15 mi
    farther = _match("100 MAIN ST, ALBA, MO, 64830", -94.42, 37.24, "MO")    # ~117 mi
    nearest = _match("100 MAIN ST, EDGERTON, KS, 66021", -94.95, 38.80, "KS")  # ~11 mi
    body_mo = {"result": {"addressMatches": [far, farther, near]}}
    body_ks = {"result": {"addressMatches": [nearest]}}
    _mock(monkeypatch, lambda a: body_ks if a.endswith(", KS") else body_mo)
    rows = address_suggest.suggest("100 Main St")["rows"]
    assert [r["city"] for r in rows] == ["Edgerton", "Belton", "Agency"]


# -- failure is no rows ------------------------------------------------------------------------------

@pytest.mark.parametrize("fail", [
    lambda a: (_ for _ in ()).throw(httpx.ReadTimeout("slow")),
    lambda a: (_ for _ in ()).throw(httpx.ConnectError("down")),
    lambda a: httpx.Response(500, text="oops"),
    lambda a: httpx.Response(200, text="<html>not json</html>"),
])
def test_a_slow_or_broken_census_is_ok_false_with_no_rows(monkeypatch, fail):
    _mock(monkeypatch, fail)
    assert address_suggest.suggest("8200 Nieman Rd") == {"ok": False, "rows": [], "reason": "error"}
    assert not address_suggest._cache, "an error must never be cached"


def test_no_match_anywhere_is_not_found_and_kept_briefly(monkeypatch):
    asked = _mock(monkeypatch, lambda a: copy.deepcopy(NONE))
    assert address_suggest.suggest("9999 Nowhere Rd") == {"ok": False, "rows": [], "reason": "not_found"}
    assert address_suggest.suggest("9999 Nowhere Rd")["reason"] == "not_found"
    assert len(asked) == 2, "the miss was asked again instead of read from the cache"


def test_the_answer_is_bounded_by_its_budget_and_inside_the_pages_wait():
    """The page aborts at CENSUS_TIMEOUT_MS; the server must answer first, or a good answer would be
    thrown away by the page. The server waits for its questions no longer than BUDGET_SECONDS plus
    WAIT_SLACK_SECONDS (a question still out by then is abandoned), whatever httpx's own phases add."""
    js = (FRONTEND / "js" / "address-lookup.js").read_text(encoding="utf-8")
    page_ms = int(re.search(r"CENSUS_TIMEOUT_MS = (\d+);", js).group(1))
    assert address_suggest.BUDGET_SECONDS + address_suggest.WAIT_SLACK_SECONDS + 1.0 < page_ms / 1000.0


# -- the cache ---------------------------------------------------------------------------------------

def test_a_cache_hit_makes_no_second_call(monkeypatch):
    asked = _mock(monkeypatch, _kansas_only)
    first = address_suggest.suggest("8200 Nieman Rd")
    second = address_suggest.suggest("8200  nieman rd")      # same words, other spacing and case
    assert first == second and len(asked) == 2


def test_a_half_answer_is_shown_but_never_cached(monkeypatch):
    """Kansas answers, the Missouri question times out. The Kansas row is shown now, and the next
    asking goes to the Census again: caching the half answer would hide the Missouri rows for a day.

    Mutation: make `if not errored:` in _suggest always true and the cache holds the Kansas row."""
    def answer(a):
        if a.endswith(", MO"):
            raise httpx.ReadTimeout("slow")
        return copy.deepcopy(NIEMAN)
    asked = _mock(monkeypatch, answer)
    out = address_suggest.suggest("8200 Nieman Rd")
    assert out["ok"] is True and [r["state"] for r in out["rows"]] == ["KS"]
    assert not address_suggest._cache, "a half answer was cached"
    address_suggest.suggest("8200 Nieman Rd")
    assert len(asked) == 4, asked


def test_the_same_match_twice_is_one_row(monkeypatch):
    """The Census can return one address twice in an answer (two TIGER lines for one block).

    Mutation: drop the `seen` check in _suggest and the row shows twice."""
    body = copy.deepcopy(NIEMAN)
    body["result"]["addressMatches"].append(copy.deepcopy(body["result"]["addressMatches"][0]))
    _mock(monkeypatch, lambda a: copy.deepcopy(body))
    rows = address_suggest.suggest("8200 Nieman Rd, KS")["rows"]
    assert [r["line1"] for r in rows] == ["8200 Nieman Rd"]


def test_court_and_connecticut_never_share_a_cache_entry(monkeypatch):
    """"123 Oak Ct" asks Kansas and Missouri; "123 Oak, CT" asks Connecticut. The comma is the only
    difference, so a key that drops punctuation answered the second from the first.

    Mutation: key the cache on distance._key(q) again and the second text asks nothing."""
    oak_ks = {"result": {"addressMatches": [_match("123 OAK CT, OLATHE, KS, 66061", -94.80, 38.89, "KS")]}}
    oak_ct = {"result": {"addressMatches": [_match("123 OAK CT, HARTFORD, CT, 06103", -72.68, 41.76, "CT")]}}
    asked = _mock(monkeypatch, lambda a: copy.deepcopy(oak_ct if a.endswith(", CT") else
                                                       oak_ks if a.endswith(", KS") else NONE))
    first = address_suggest.suggest("123 Oak Ct")
    second = address_suggest.suggest("123 Oak, CT")
    assert [r["city"] for r in first["rows"]] == ["Olathe"]
    assert [r["city"] for r in second["rows"]] == ["Hartford"], second
    assert sorted(asked) == ["123 Oak Ct, KS", "123 Oak Ct, MO", "123 Oak, CT"]


def test_the_cache_is_bounded(monkeypatch):
    _mock(monkeypatch, lambda a: copy.deepcopy(NIEMAN) if ", KS" in a else copy.deepcopy(NONE))
    for i in range(address_suggest._CACHE_MAX + 5):
        address_suggest.suggest("%d Nieman Rd, KS" % (i + 1))
    assert len(address_suggest._cache) <= address_suggest._CACHE_MAX


# -- the route ---------------------------------------------------------------------------------------

def test_the_route_answers_200_with_rows(monkeypatch):
    _mock(monkeypatch, _kansas_only)
    r = TestClient(main.app).post("/api/address-suggest", json={"q": "8200 Nieman Rd"})
    assert r.status_code == 200
    assert r.json()["ok"] is True and r.json()["rows"][0]["city"] == "Overland Park"


@pytest.mark.parametrize("body", [{}, {"q": None}, {"q": 8200}, {"q": ["8200 Nieman Rd"]}, {"q": "x" * 5000}])
def test_the_route_is_200_for_any_body_shape(body):
    r = TestClient(main.app).post("/api/address-suggest", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False and r.json()["rows"] == []


def test_the_route_is_200_when_the_census_is_down(monkeypatch):
    _mock(monkeypatch, lambda a: (_ for _ in ()).throw(httpx.ConnectTimeout("slow")))
    r = TestClient(main.app).post("/api/address-suggest", json={"q": "8200 Nieman Rd"})
    assert r.status_code == 200
    assert r.json() == {"ok": False, "rows": [], "reason": "error"}


def test_the_route_needs_a_sign_in(monkeypatch, real_verify_token):
    monkeypatch.setattr(main.supabase_client, "verify_token", real_verify_token)
    r = TestClient(main.app).post("/api/address-suggest", json={"q": "8200 Nieman Rd"})
    assert r.status_code == 401, r.text
    assert main._auth_is_public("/api/address-suggest", "POST") is False


def test_no_tab_owns_the_route_so_no_policy_can_blank_it_mid_bid():
    for href, tab in nav_access.TABS.items():
        for prefix in tab["api"]:
            assert not nav_access.prefix_matches("/api/address-suggest", prefix), (href, prefix)


def test_a_flood_is_busy_on_its_own_bucket_and_a_cached_answer_costs_nothing(monkeypatch):
    asked = _mock(monkeypatch, _kansas_only)
    c = TestClient(main.app)
    for i in range(distance._RATE_MAX):
        assert c.post("/api/address-suggest", json={"q": "%d Nieman Rd" % (i + 1)}).json()["reason"] != "busy"
    j = c.post("/api/address-suggest", json={"q": "9000 Nieman Rd"}).json()
    assert j == {"ok": False, "rows": [], "reason": "busy"}
    assert distance._rate_hits and all(k.startswith("addr:") for k in distance._rate_hits)
    # A question already answered is read from the cache, past the limit, without a request.
    n = len(asked)
    j = c.post("/api/address-suggest", json={"q": "1 Nieman Rd"}).json()
    assert j["ok"] is True and len(asked) == n


def test_a_question_still_out_at_the_budget_is_abandoned(monkeypatch):
    """The Census can hang past httpx's per-phase timeouts adding up; the answer still comes back by
    the budget, as "error", and nothing is cached."""
    import time as _time
    monkeypatch.setattr(address_suggest, "BUDGET_SECONDS", 0.2)
    _mock(monkeypatch, lambda a: (_time.sleep(1.0), copy.deepcopy(NIEMAN))[1])
    t0 = _time.monotonic()
    out = address_suggest.suggest("8200 Nieman Rd")
    took = _time.monotonic() - t0
    assert out == {"ok": False, "rows": [], "reason": "error"}
    assert took < 0.9, took
    assert not address_suggest._cache
    _time.sleep(1.1)       # let the abandoned questions finish inside this test's transport
