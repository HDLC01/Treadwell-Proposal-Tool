"""POST /api/distance WITHOUT A STREET: the miles to the centre of the zip, the city or the county.

Hanz, 2026-10-22, testing staging: a v2 bid with City "Wichita", State "KS", County "Sedgwick County, KS"
and no street said "This job is marked local, so no travel is expected" and filled no travel. Wichita is
about 190 driving miles from the Olathe office. "based on the county and city and state it should have
calculated it already".

THE RULE NOW (distance.lookup):
  * WITH a street the lookup is exactly what it was (Census street geocode, or Google with a key), and
    the answer says `precision: "street"`.
  * WITHOUT one, the job is placed at the Census Gazetteer's internal point of, in this order, its ZIP
    (the tightest), its CITY + state, or its COUNTY (+ state), bundled in backend/geodata/. A street the
    geocoder cannot find falls back the same way and says so (`street_not_found`).
  * The point is ROUTED, through the same OSRM call from the pinned office coordinates: driving miles,
    never straight-line. OSRM down is `reason: "error"` exactly as before.
  * A city is matched by its name with the Census suffix taken off ("Wichita city" -> "Wichita"), within
    the typed state, a real town before a CDP; "St."/"Saint", spacing, case and a trailing ", KS" are
    tolerated and nothing else is guessed: no match, or two towns of that name, is the next fallback.

NO TEST HERE TOUCHES THE NETWORK: the same MockTransport discipline as test_distance.py.
"""
import pathlib
import re

import httpx
import pytest
from fastapi.testclient import TestClient

import distance
import main

BACKEND = pathlib.Path(distance.__file__).resolve().parent
REPO = BACKEND.parent
CENSUS_HOST = "geocoding.geo.census.gov"
OSRM_HOST = "router.project-osrm.org"
_violations = []


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
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


def _mock(monkeypatch, census=None, osrm=None):
    calls = []
    table = {CENSUS_HOST: census, OSRM_HOST: osrm}

    def handler(request):
        calls.append(request)
        h = table.get(request.url.host)
        if h is None:
            _violations.append(str(request.url))
            raise AssertionError("unexpected host: %s" % request.url.host)
        return h(request)
    monkeypatch.setattr(distance, "_TRANSPORT", httpx.MockTransport(handler))
    return calls


def _o_ok(meters):
    return lambda request: httpx.Response(200, json={"code": "Ok", "routes": [{"distance": meters}]})


def _c_none(request):
    return httpx.Response(200, json={"result": {"addressMatches": []}})


def _c_match(lon=-97.33, lat=37.69, state="KS"):
    body = {"result": {"addressMatches": [{"coordinates": {"x": lon, "y": lat},
                                           "addressComponents": {"state": state}}]}}
    return lambda request: httpx.Response(200, json=body)


def _routed_to(call):
    """The (lon, lat) of the JOB end of an OSRM request (office first, then the job)."""
    tail = call.url.path.rsplit("/", 1)[1]
    office, job = tail.split(";")
    assert office == "%.6f,%.6f" % (distance.OFFICE_LON, distance.OFFICE_LAT)
    lon, lat = job.split(",")
    return float(lon), float(lat)


WICHITA = (-97.3458, 37.6906)          # "KS,Wichita city" in gaz_places.csv
SEDGWICK = (-97.4611, 37.6810)         # "KS,Sedgwick County" in gaz_counties.csv
ZIP_67202 = (-97.3349, 37.6870)        # gaz_zcta.csv


def _pt(**kw):
    p = distance.approx_point(kw.get("city", ""), kw.get("state", ""), kw.get("zip", ""), kw.get("county", ""))
    return None if p is None else (p["precision"], p["label"], round(p["lon"], 4), round(p["lat"], 4))


# ── the bundled data ────────────────────────────────────────────────────────────────────────────────
def test_the_centres_are_bundled_where_the_image_copies_them_and_no_volume_hides_them():
    """COPY backend/ /app/ carries backend/geodata into the image. NOT backend/data: both compose files
    mount a volume over /app/data, which would hide anything the image put there."""
    for name in ("gaz_places.csv", "gaz_counties.csv", "gaz_zcta.csv"):
        f = BACKEND / "geodata" / name
        assert f.is_file(), f
        assert f.stat().st_size < 2_000_000, "%s grew past 2 MB" % name
    assert distance.GEODATA_DIR == str(BACKEND / "geodata")
    assert "COPY backend/ /app/" in (REPO / "Dockerfile").read_text(encoding="utf-8")
    for compose in ("docker-compose.yml", "docker-compose.staging.yml"):
        text = (REPO / compose).read_text(encoding="utf-8")
        assert "/app/geodata" not in text, "%s mounts a volume over the bundled centres" % compose
    ignored = (REPO / ".dockerignore").read_text(encoding="utf-8").split()
    assert not any(p in ignored for p in ("*.csv", "**/*.csv", "geodata", "backend/geodata")), ignored
    assert (BACKEND / "tools" / "build_gazetteer.py").is_file(), "the data must be reproducible"


def test_the_bundled_tables_load_and_hold_the_whole_country():
    g = distance._gazetteer()
    assert len(g["zcta"]) > 30000
    assert sum(len(v) for v in g["places"].values()) > 30000
    assert sum(len(v) for v in g["counties"].values()) > 3000


# ── matching a city ─────────────────────────────────────────────────────────────────────────────────
def test_wichita_ks_is_the_census_place_with_its_suffix_taken_off():
    assert _pt(city="Wichita", state="KS") == ("city", "Wichita, KS") + WICHITA


@pytest.mark.parametrize("city,state", [
    ("wichita", "ks"), ("  WICHITA  ", "KS"), ("Wichita, KS", "KS"), ("Wichita,KS", "ks"), ("Wichita, Kansas", "KS"),
])
def test_case_spacing_and_a_trailing_state_are_tolerated(city, state):
    assert _pt(city=city, state=state) == ("city", "Wichita, KS") + WICHITA


def test_the_typed_state_decides_which_kansas_city():
    assert _pt(city="Kansas City", state="MO")[2:] == (-94.5503, 39.1252)
    assert _pt(city="Kansas City", state="KS")[2:] == (-94.7418, 39.1225)


@pytest.mark.parametrize("city", ["St. Joseph", "St Joseph", "Saint Joseph", "saint  joseph", "ST. JOSEPH"])
def test_st_and_saint_are_the_same_word(city):
    assert _pt(city=city, state="MO") == ("city", "St. Joseph, MO", -94.8211, 39.7595)


def test_sainte_and_an_apostrophe():
    assert _pt(city="Sainte Genevieve", state="MO")[:2] == ("city", "Ste. Genevieve, MO")
    assert _pt(city="Ste Genevieve", state="MO")[:2] == ("city", "Ste. Genevieve, MO")
    assert _pt(city="Lee's Summit", state="MO")[:2] == ("city", "Lee's Summit, MO")
    assert _pt(city="Lees Summit", state="MO")[:2] == ("city", "Lee's Summit, MO")


def test_a_town_is_preferred_over_a_cdp_of_the_same_name():
    """OK has a Marietta city (by the Red River) and a Marietta CDP (by the Arkansas line). The town wins."""
    assert _pt(city="Marietta", state="OK") == ("city", "Marietta, OK", -97.1247, 33.9362)


def test_a_cdp_alone_is_still_a_place():
    assert _pt(city="Marietta", state="IN")[:2] == ("city", "Marietta, IN")


def test_two_towns_of_one_name_are_not_guessed_between():
    """Ohio has an Oakwood city and two Oakwood villages, far apart: no pick, the next fallback (none here)."""
    assert _pt(city="Oakwood", state="OH") is None


@pytest.mark.parametrize("city,state", [
    ("Wichta", "KS"),          # a typo is not corrected
    ("Wichita", "MO"),         # not in that state
    ("Wichita", ""),           # a city needs its state
    ("Wich", "KS"),            # no prefix match
    ("Kansas", "KS"),          # no partial match
])
def test_no_fuzzy_guessing(city, state):
    assert _pt(city=city, state=state) is None


# ── matching a county ───────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("county,state", [
    ("Sedgwick County, KS", ""),       # the picker's own shape, the state inside it
    ("Sedgwick County, KS", "KS"),
    ("Sedgwick County", "KS"),
    ("sedgwick county, ks", ""),
    ("Sedgwick Co., KS", ""),
    ("Sedgwick Co", "KS"),
])
def test_the_county_forms_the_intake_can_hold(county, state):
    assert _pt(county=county, state=state) == ("county", "Sedgwick County, KS") + SEDGWICK


def test_a_county_without_the_word_county_when_no_town_has_that_name():
    assert _pt(county="Johnson", state="KS")[:2] == ("county", "Johnson County, KS")
    assert _pt(county="Johnson, KS")[:2] == ("county", "Johnson County, KS")


def test_a_bare_name_that_is_also_a_town_is_the_town_because_the_picker_writes_counties_with_county():
    """js/county-picker.js writes a county row as "<Name> County, ST" and a city row as "<Name>, ST". So
    "Shawnee, KS" is the city of Shawnee (Johnson County, by Olathe), not Shawnee County (Topeka, 60 miles
    on): the picker's own city row (reference_tax.py). The same reading makes "Sedgwick, KS" the town."""
    assert _pt(county="Shawnee, KS")[:2] == ("city", "Shawnee, KS")
    assert _pt(county="Shawnee County, KS")[:2] == ("county", "Shawnee County, KS")
    assert _pt(county="Sedgwick, KS")[:2] == ("city", "Sedgwick, KS")


def test_the_state_inside_the_county_wins_over_the_state_field():
    assert _pt(county="Sedgwick County, CO", state="KS")[:2] == ("county", "Sedgwick County, CO")


def test_a_parish_and_an_accent():
    assert _pt(county="Orleans Parish, LA")[:2] == ("county", "Orleans Parish, LA")
    assert _pt(county="Dona Ana County, NM")[:2] == ("county", "Doña Ana County, NM")


def test_a_city_row_in_the_county_box_is_that_city():
    """The tax picker writes a CITY row as "Overland Park, KS" into the same `county` key."""
    assert _pt(county="Overland Park, KS")[:2] == ("city", "Overland Park, KS")


@pytest.mark.parametrize("county,state", [("Sedgwick County", ""), ("Nowhere County, KS", ""), ("", "KS")])
def test_a_county_needs_a_state_and_a_real_name(county, state):
    assert _pt(county=county, state=state) is None


# ── the order: zip, then city, then county ──────────────────────────────────────────────────────────
def test_a_zip_is_the_tightest_and_comes_first():
    assert _pt(zip="67202", city="Wichita", state="KS", county="Sedgwick County, KS") == \
        ("zip", "zip 67202") + ZIP_67202
    assert _pt(zip="67202-1234")[:2] == ("zip", "zip 67202")


def test_an_unknown_zip_falls_to_the_city_and_an_unknown_city_to_the_county():
    assert _pt(zip="00000", city="Wichita", state="KS")[:2] == ("city", "Wichita, KS")
    assert _pt(zip="12", city="Wichita", state="KS")[:2] == ("city", "Wichita, KS")
    assert _pt(city="Smallville", state="KS", county="Sedgwick County, KS")[:2] == ("county", "Sedgwick County, KS")



# ── a zip that disagrees with the typed city or county is a typo, not the job (the 2026-10-22 audit's finding 3) ────────────────────
def test_a_zip_far_from_the_typed_city_is_set_aside_for_the_city():
    """lookup('', 'Wichita', 'KS', '10001') measured to a New York zip and filled the travel lines with it. The zip table has no state
    column, so the check is where the zip's centre lies: far from the typed city (or county), the city (or county) is what is meant."""
    assert _pt(zip="10001", city="Wichita", state="KS")[:2] == ("city", "Wichita, KS")
    assert _pt(zip="10001", city="Wichita", state="KS", county="Sedgwick County, KS")[:2] == ("city", "Wichita, KS")


def test_a_zip_far_from_the_typed_county_is_set_aside_for_the_county():
    assert _pt(zip="10001", county="Sedgwick County, KS")[:2] == ("county", "Sedgwick County, KS")
    assert _pt(zip="10001", city="Smallville", state="KS", county="Sedgwick County, KS")[:2] == ("county", "Sedgwick County, KS")


def test_a_zip_near_the_typed_city_is_still_the_tightest():
    assert _pt(zip="67037", city="Wichita", state="KS")[:2] == ("zip", "zip 67037")      # Derby, next to Wichita
    assert _pt(zip="66061", city="Olathe", state="KS", county="Johnson County, KS")[:2] == ("zip", "zip 66061")


def test_a_zip_with_nothing_to_check_it_against_is_used():
    assert _pt(zip="10001")[:2] == ("zip", "zip 10001")
    assert _pt(zip="10001", city="Smallville", state="KS")[:2] == ("zip", "zip 10001")


def test_the_lookup_with_a_typod_zip_measures_to_the_city(monkeypatch):
    calls = _mock(monkeypatch, census=_c_none, osrm=_o_ok(306000))
    out = distance.lookup("", "Wichita", "KS", "10001")
    assert out["ok"] and out["precision"] == "city" and out["measured_to"] == "Wichita, KS"
    assert _routed_to(calls[0]) == pytest.approx(WICHITA, abs=1e-4)

# ── the lookup ──────────────────────────────────────────────────────────────────────────────────────
def test_hanzs_bid_city_state_and_county_with_no_street_is_measured(monkeypatch):
    """The bid from the report: no street. One OSRM call to the centre of Wichita, no geocode at all."""
    calls = _mock(monkeypatch, census=_c_none, osrm=_o_ok(306000))
    out = distance.lookup("", "Wichita", "KS", "", county="Sedgwick County, KS")
    assert out["ok"] is True and out["miles"] == 190.1 and out["reason"] == ""
    assert out["precision"] == "city" and out["measured_to"] == "Wichita, KS"
    assert out["street_not_found"] is False and out["office"] == "Olathe office"
    assert [c.url.host for c in calls] == [OSRM_HOST]
    assert _routed_to(calls[0]) == pytest.approx(WICHITA, abs=1e-4)


def test_county_alone_is_measured_to_the_county(monkeypatch):
    calls = _mock(monkeypatch, osrm=_o_ok(300000))
    out = distance.lookup("", "", "", "", county="Sedgwick County, KS")
    assert out["ok"] and out["precision"] == "county" and out["measured_to"] == "Sedgwick County, KS"
    assert _routed_to(calls[0]) == pytest.approx(SEDGWICK, abs=1e-4)


def test_a_zip_alone_is_measured_to_the_zip(monkeypatch):
    calls = _mock(monkeypatch, osrm=_o_ok(300000))
    out = distance.lookup("", "", "", "67202")
    assert out["ok"] and out["precision"] == "zip" and out["measured_to"] == "zip 67202"
    assert _routed_to(calls[0]) == pytest.approx(ZIP_67202, abs=1e-4)


def test_with_a_street_the_lookup_is_exactly_what_it_was(monkeypatch):
    calls = _mock(monkeypatch, census=_c_match(-97.33, 37.69), osrm=_o_ok(285130.4))
    out = distance.lookup("100 Main St", "Wichita", "KS", "67202", county="Sedgwick County, KS")
    assert out["ok"] and out["miles"] == 177.2 and out["precision"] == "street"
    assert out["measured_to"] == "100 Main St, Wichita, KS 67202" == out["address"]
    assert [c.url.host for c in calls] == [CENSUS_HOST, OSRM_HOST]
    assert dict(calls[0].url.params)["address"] == "100 Main St, Wichita, KS 67202"
    assert _routed_to(calls[1]) == pytest.approx((-97.33, 37.69), abs=1e-6)


def test_a_street_the_geocoder_cannot_find_falls_back_to_the_centre_and_says_so(monkeypatch):
    calls = _mock(monkeypatch, census=_c_none, osrm=_o_ok(306000))
    out = distance.lookup("1 Nowhere Ln", "Wichita", "KS", "", county="Sedgwick County, KS")
    assert out["ok"] and out["miles"] == 190.1
    assert out["precision"] == "city" and out["measured_to"] == "Wichita, KS"
    assert out["street_not_found"] is True
    assert [c.url.host for c in calls] == [CENSUS_HOST, OSRM_HOST]
    assert _routed_to(calls[1]) == pytest.approx(WICHITA, abs=1e-4)



class _Clock:
    t = 100.0


def _spy_timeouts(monkeypatch):
    """Records the timeout each outgoing call was given, and lets a handler move a fake clock."""
    seen = []
    real = httpx.Client

    def spy(*a, **kw):
        seen.append(kw.get("timeout"))
        return real(*a, **kw)
    monkeypatch.setattr(distance.httpx, "Client", spy)
    clock = _Clock()
    monkeypatch.setattr(distance, "_now", lambda: clock.t)
    return seen, clock


def test_a_street_miss_and_its_centre_share_one_time_budget(monkeypatch):
    """The audit's finding 2: the centre's route was given a FRESH budget after the street geocode had spent part of
    its own, so a miss could take about twice the budget and run past the page's abort (WORST_CASE_SECONDS)."""
    seen, clock = _spy_timeouts(monkeypatch)

    def slow_miss(request):
        clock.t += distance.TOTAL_BUDGET_SECONDS - 1.0        # the geocoder ate all but one second
        return _c_none(request)
    calls = _mock(monkeypatch, census=slow_miss, osrm=_o_ok(306000))
    out = distance.lookup("1 Nowhere Ln", "Wichita", "KS", "", county="Sedgwick County, KS")
    assert out["ok"] and out["precision"] == "city" and out["street_not_found"] is True
    assert [c.url.host for c in calls] == [CENSUS_HOST, OSRM_HOST]
    assert seen[0].read == distance.TIMEOUT_SECONDS
    assert 0 < seen[1].read <= 1.0 + 1e-6 and seen[1].connect <= 1.0 + 1e-6, "the route got a fresh budget"


def test_a_street_miss_that_spent_the_budget_routes_nothing_and_says_error(monkeypatch):
    seen, clock = _spy_timeouts(monkeypatch)

    def spent(request):
        clock.t += distance.TOTAL_BUDGET_SECONDS + 0.5
        return _c_none(request)
    calls = _mock(monkeypatch, census=spent, osrm=_o_ok(306000))
    out = distance.lookup("1 Nowhere Ln", "Wichita", "KS", "", county="Sedgwick County, KS")
    assert out["ok"] is False and out["miles"] is None and out["reason"] == "error"
    assert [c.url.host for c in calls] == [CENSUS_HOST]

def test_a_street_not_found_with_nothing_to_fall_back_to_is_still_not_found(monkeypatch):
    calls = _mock(monkeypatch, census=_c_none, osrm=_o_ok(1))
    out = distance.lookup("1 Nowhere Ln", "Smallville", "KS", "")
    assert out["ok"] is False and out["miles"] is None and out["reason"] == "not_found"
    assert [c.url.host for c in calls] == [CENSUS_HOST]


def test_a_geocoder_outage_is_not_a_reason_to_guess_a_centre(monkeypatch):
    """Only a clean "no such street" falls back. A Census outage stays "error": the street may be real."""
    calls = _mock(monkeypatch, census=lambda r: httpx.Response(503), osrm=_o_ok(1))
    out = distance.lookup("100 Main St", "Wichita", "KS", "")
    assert out["miles"] is None and out["reason"] == "error"
    assert [c.url.host for c in calls] == [CENSUS_HOST]


def test_osrm_down_on_a_centre_is_an_error_not_a_straight_line(monkeypatch):
    _mock(monkeypatch, osrm=lambda r: httpx.Response(502, json={"code": "Error"}))
    out = distance.lookup("", "Wichita", "KS", "")
    assert out["ok"] is False and out["miles"] is None and out["reason"] == "error"
    assert out["precision"] == ""


def test_an_unknown_place_is_not_found_and_routes_nothing(monkeypatch):
    calls = _mock(monkeypatch, osrm=_o_ok(1))
    out = distance.lookup("", "Smallville", "KS", "")
    assert out["miles"] is None and out["reason"] == "not_found" and calls == []


@pytest.mark.parametrize("addr,city,state,zip_code,county", [
    ("", "", "", "", ""),
    ("", "Wichita", "", "", ""),                  # a city needs its state
    ("", "", "KS", "", ""),                       # a state alone places nothing
    ("", "", "", "", "Sedgwick County"),          # a county needs a state
    ("100 Main St", "Wichita", "", "", ""),       # a street with nothing to place it
])
def test_too_little_is_incomplete_and_asks_nothing(monkeypatch, addr, city, state, zip_code, county):
    calls = _mock(monkeypatch, census=_c_match(), osrm=_o_ok(1))
    out = distance.lookup(addr, city, state, zip_code, county=county)
    assert out["miles"] is None and out["reason"] == "incomplete" and calls == []
    assert distance.can_place(addr, city, state, zip_code, county) is False


def test_a_centre_is_cached_like_a_street(monkeypatch):
    calls = _mock(monkeypatch, osrm=_o_ok(306000))
    a = distance.lookup("", "Wichita", "KS", "")
    b = distance.lookup("", "wichita ", "ks", "", county="")
    assert a["miles"] == b["miles"] == 190.1 and b["precision"] == "city"
    assert len(calls) == 1


def test_a_street_miss_is_remembered_and_the_fallback_still_answers(monkeypatch):
    calls = _mock(monkeypatch, census=_c_none, osrm=_o_ok(306000))
    distance.lookup("1 Nowhere Ln", "Wichita", "KS", "")
    again = distance.lookup("1 Nowhere Ln", "Wichita", "KS", "")
    assert again["ok"] and again["precision"] == "city" and again["street_not_found"] is True
    assert [c.url.host for c in calls] == [CENSUS_HOST, OSRM_HOST], "the second ask costs nothing"


# ── the route ──────────────────────────────────────────────────────────────────────────────────────
def test_the_route_takes_a_county_and_answers_with_the_precision(monkeypatch):
    _mock(monkeypatch, osrm=_o_ok(306000))
    r = TestClient(main.app).post("/api/distance", json={"address": "", "city": "", "state": "",
                                                         "zip": "", "county": "Sedgwick County, KS"})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True and j["precision"] == "county" and j["measured_to"] == "Sedgwick County, KS"
    assert set(j) >= {"ok", "miles", "reason", "office", "address", "precision", "measured_to", "street_not_found"}


def test_the_route_still_takes_a_body_without_a_county(monkeypatch):
    _mock(monkeypatch, osrm=_o_ok(306000))
    r = TestClient(main.app).post("/api/distance", json={"city": "Wichita", "state": "KS"})
    assert r.status_code == 200 and r.json()["precision"] == "city"


def test_the_route_is_200_and_incomplete_for_an_empty_body(monkeypatch):
    r = TestClient(main.app).post("/api/distance", json={})
    assert r.status_code == 200 and r.json()["reason"] == "incomplete" and r.json()["precision"] == ""


def test_the_county_route_is_unchanged_by_the_new_field(monkeypatch):
    """/api/county (the tax county) shares DistanceIn; a county in the body changes nothing there."""
    r = TestClient(main.app).post("/api/county", json={"city": "Wichita", "state": "KS", "county": "Sedgwick County, KS"})
    assert r.status_code == 200 and r.json()["reason"] == "incomplete"


def test_the_module_says_what_it_does_now():
    """The docstring said "no city-centre guess"; it must not contradict the code."""
    doc = distance.__doc__
    assert "no city-centre guess" not in doc
    assert re.search(r"centre|center", doc) and "Gazetteer" in doc
