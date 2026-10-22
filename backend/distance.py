"""Driving miles from the Olathe office to a job address.

WHY THIS EXISTS. Kyle's 9/18 notes: take the "70 mile slider" off intake and work the distance out
from the job address, so the estimate knows whether Travel Labor, Lodging and Per Diem apply.
Hanz, 2026-10-05: driving miles, called SERVER-SIDE (nothing reaches a browser and the nginx CSP
needs no change). Hanz, 2026-10-12: "find a free routes api without using google maps".

TWO PROVIDERS, in this order.
  1. Google Routes, ONLY when GOOGLE_MAPS_API_KEY is set (it is set on neither prod nor staging).
  2. The free pair, the default whenever there is no key, and the fallback when Google fails:
       - US Census Geocoder (geocoding.geo.census.gov): street address to lon/lat. Free, no key,
         US addresses only. A US government service with no stated rate limit; one call per lookup.
       - OSRM public router (router.project-osrm.org): lon/lat pair to driving meters. Free, no key.
         It is a DEMO server run by the OSRM project: light use only, a descriptive User-Agent is
         required, and it can be slowed or withdrawn at any time. One call per lookup, and repeat
         addresses are served from the cache here. When it fails the page already falls back to its
         "type the miles" box, which is the designed answer, not a bug.

NO STREET? THE CENTRE OF THE ZIP, THE CITY OR THE COUNTY (Hanz, 2026-10-22: a bid with City
"Wichita", State "KS", County "Sedgwick County, KS" and no street was called local; "based on the
county and city and state it should have calculated it already"). The street geocoder needs a
street, so without one the job is placed at the US Census Gazetteer's internal point of, in this
order, its ZIP (the tightest), its CITY + state, or its COUNTY (+ state): public-domain tables,
trimmed and bundled in backend/geodata/ (rebuilt by backend/tools/build_gazetteer.py), so no extra
network call. A zip whose centre lies far from the typed city (or county) is a typo and is set
aside for that one. A street the geocoder answers "no match" for falls back the same way and says so
(`street_not_found`). The point is then ROUTED through the same OSRM call from the office, so the
figure is still driving miles. Every answer says how precise it is (`precision`: street | zip |
city | county) and what it was measured to (`measured_to`), and the page words an approximate
figure as one ("About 190 miles to Wichita, KS (city center)").

NEVER GUESS BEYOND THAT. Every path that cannot produce a real figure answers `miles: None` with a
`reason` (address not found, a service slow or down, address incomplete, rate limit). The page
turns that into "Distance unknown -- enter miles" and lets the estimator type the number. There is
no straight-line fallback and no default distance, a city name is matched exactly (case, spacing,
"St."/"Saint" and a trailing ", KS" aside) and never fuzzily, and a geocoder OUTAGE is not a
reason to fall back to a centre: a wrong answer near 70 miles moves a bid by thousands of dollars
in either direction.

NEVER SLOW THE PAGE. Short timeouts, no retry, and the page calls this after it has painted.
"""
from __future__ import annotations

import csv
import logging
import math
import os
import re
import threading
import time
import unicodedata
from typing import Any, Dict, List, Optional

import httpx

log = logging.getLogger("treadwell.distance")

# The only office address in the repo (backend/prepare_cover_letter_templates.py). Hanz, 2026-10-05.
OFFICE_ADDRESS = "1707 E. 123rd Ter, Olathe, KS 66061"
OFFICE_LABEL = "Olathe office"

# The office, geocoded ONCE with the Census geocoder (2026-10-12) and pinned, so a lookup spends one
# geocode (the job) and not two. A test pins these to OFFICE_ADDRESS and to the cover-letter text.
OFFICE_LON = -94.79032
OFFICE_LAT = 38.90391

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving/"
METERS_PER_MILE = 1609.344
USER_AGENT = "Treadwell-proposal-tool/1.0 (+https://proposals.wetreadwell.com)"

# Each service answers in well under a second. Past this the estimator is better served by typing the
# number than by waiting on a map service.
TIMEOUT_SECONDS = 6.0
CONNECT_SECONDS = 3.0

# ONE deadline for the whole lookup (geocode + route, or Google + both). httpx's timeout applies to
# each phase of each call separately, so two calls could add up to 12 s or more; each call is instead
# given only what is left of this budget, and a spent budget skips the next call. The page's own
# abort (polish-estimate.js lookupDistance) must sit past WORST_CASE_SECONDS, or a lookup that did
# succeed would be shown as "did not answer". A test pins that.
TOTAL_BUDGET_SECONDS = 8.0
WORST_CASE_SECONDS = TOTAL_BUDGET_SECONDS + CONNECT_SECONDS
_now = time.monotonic

# A repeated address costs nothing. Only real answers are kept; "not found" is kept briefly so a
# typo is not re-billed on every keystroke-driven re-open, and errors are never kept.
_CACHE_TTL_OK = 24 * 3600
_CACHE_TTL_MISS = 10 * 60
_CACHE_MAX = 500
_cache: Dict[str, tuple] = {}          # key -> (expires_at, miles | None, reason)
_cache_lock = threading.Lock()

# Cost backstop per signed-in user. A person re-opening bids does not come close.
_RATE_MAX = 30
_RATE_WINDOW = 300
_rate_hits: Dict[str, list] = {}

# Tests point this at an httpx.MockTransport; production leaves it None (the real network).
_TRANSPORT: Optional[httpx.BaseTransport] = None


def api_key() -> str:
    return (os.environ.get("GOOGLE_MAPS_API_KEY") or "").strip()


def clean_address(address: Any, city: Any, state: Any, zip_code: Any) -> str:
    """One line "street, city, ST zip", or "" when too little is given to look anything up.

    A street AND a way to place it (city+state, or a zip) are both required: "Main St" alone would
    be answered by Google with SOME Main St, and a confident wrong number is worse than none."""
    def one(v: Any, cap: int) -> str:
        return re.sub(r"\s+", " ", str(v or "")).strip()[:cap]
    street, c, st, z = one(address, 160), one(city, 80), one(state, 2).upper(), one(zip_code, 10)
    if not street:
        return ""
    if not ((c and st) or z):
        return ""
    tail = " ".join(p for p in (st, z) if p)
    return ", ".join(p for p in (street, c, tail) if p)


# ---------------------------------------------------------------------------------------------
# THE CENTRES (no street). See the module docstring. The three tables are read once, on the first
# lookup that needs one, and kept: about 70k rows, a few MB of memory.
# ---------------------------------------------------------------------------------------------
GEODATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "geodata")
_gaz: Optional[Dict[str, Any]] = None
_gaz_lock = threading.Lock()

# The Census's own descriptor at the end of a place NAME ("Wichita city", "Abanda CDP"). Matched
# CASE-SENSITIVELY, because the Census writes them in lower case and a capital is part of the name:
# "Kansas City city" is Kansas City, while "Carson City" keeps its "City". Longest first.
_PLACE_SUFFIXES = (" city and borough", " consolidated government", " metropolitan government",
                   " metro government", " unified government", " metro township", " urban county",
                   " municipality", " zona urbana", " comunidad", " corporation", " borough",
                   " village", " town", " city", " CDP")
# The same for a county NAME, so "Sedgwick" finds "Sedgwick County".
_COUNTY_SUFFIXES = (" City and Borough", " Census Area", " Municipality", " Municipio", " County",
                    " Parish", " Borough")
_COUNTY_WORDS = re.compile(r" (county|parish|borough|census area|municipio|municipality)$")


def _norm(v: Any) -> str:
    """A name as it is compared: accents, case, dots, apostrophes and spacing taken out, and
    "St."/"Ste." spelled out. Nothing else: this is matching, not guessing."""
    s = unicodedata.normalize("NFKD", str(v or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower().replace("’", "'")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\bste\b\.?\s*", "sainte ", s)
    s = re.sub(r"\bst\b\.?\s*", "saint ", s)
    s = re.sub(r"[.']", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _strip(name: str, suffixes) -> str:
    name = re.sub(r"\s*\(balance\)$", "", name)
    for suf in suffixes:
        if name.endswith(suf) and len(name) > len(suf):
            return name[:-len(suf)]
    return name


def _load_gazetteer() -> Dict[str, Any]:
    places: Dict[tuple, List[tuple]] = {}
    counties: Dict[tuple, List[tuple]] = {}
    zcta: Dict[str, tuple] = {}

    def rows(name):
        with open(os.path.join(GEODATA_DIR, name), encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    for r in rows("gaz_places.csv"):
        base = _strip(r["name"], _PLACE_SUFFIXES)
        places.setdefault((r["usps"], _norm(base)), []).append(
            (r["kind"], base, float(r["lon"]), float(r["lat"])))
    for r in rows("gaz_counties.csv"):
        pt = (r["name"], float(r["lon"]), float(r["lat"]))
        full, bare = _norm(r["name"]), _norm(_strip(r["name"], _COUNTY_SUFFIXES))
        counties.setdefault((r["usps"], full), []).append(pt)
        if bare != full:
            counties.setdefault((r["usps"], "~" + bare), []).append(pt)
    for r in rows("gaz_zcta.csv"):
        zcta[r["zcta"]] = (float(r["lon"]), float(r["lat"]))
    return {"places": places, "counties": counties, "zcta": zcta}


def _gazetteer() -> Dict[str, Any]:
    global _gaz
    if _gaz is None:
        with _gaz_lock:
            if _gaz is None:
                _gaz = _load_gazetteer()
    return _gaz


def _state_code(v: Any) -> str:
    s = re.sub(r"\s+", " ", str(v or "")).strip()
    return s[:2].upper() if re.fullmatch(r"[A-Za-z]{2}", s) else ""


def _split_state(text: Any) -> tuple:
    """("Sedgwick County", "KS") from "Sedgwick County, KS"; (text, "") when it carries no state."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    # rpartition, not a regex: the box is free text from the request, and a backtracking pattern over it is a ReDoS.
    head, comma, tail = s.rpartition(",")
    tail = tail.strip()
    if comma and len(tail) == 2 and tail.isascii() and tail.isalpha():
        return head.strip(), tail.upper()
    return s, ""


def _place(city: Any, st: str) -> Optional[Dict[str, Any]]:
    """The one place in state `st` called `city`, or None: a real town before a CDP, and two of
    the same kind and name (Ohio's three Oakwoods) are not picked between."""
    name = re.sub(r"\s+", " ", str(city or "")).strip()
    name = name.split(",")[0].strip()              # "Wichita, KS" typed in the city box
    if not (name and st):
        return None
    hits = _gazetteer()["places"].get((st, _norm(name))) or []
    for kind in ("inc", "cdp"):
        same = [h for h in hits if h[0] == kind]
        if len(same) == 1:
            _, base, lon, lat = same[0]
            return {"precision": "city", "label": "%s, %s" % (base, st), "lon": lon, "lat": lat}
        if len(same) > 1:
            return None
    return None


def _county(text: Any, state: Any) -> Optional[Dict[str, Any]]:
    """The county (or, for the tax picker's city rows, the city) the `county` box names, or None.
    "Sedgwick County, KS", "Sedgwick County" + KS, "Sedgwick Co." and "Sedgwick" all find
    Sedgwick County; "Overland Park, KS" is a city row and finds the city."""
    name, st = _split_state(text)
    st = st or _state_code(state)
    if not (name and st):
        return None
    n = re.sub(r" co$", " county", _norm(name))
    table = _gazetteer()["counties"]

    def one(key):
        hits = table.get((st, key)) or []
        if len(hits) != 1:
            return None
        full, lon, lat = hits[0]
        return {"precision": "county", "label": "%s, %s" % (full, st), "lon": lon, "lat": lat}
    if _COUNTY_WORDS.search(n):
        return one(n)
    # A bare name: the picker's city row first ("Overland Park, KS"), then a county without "County".
    return _place(name, st) or one("~" + n)


# A ZIP THAT LIES THIS FAR (straight line) FROM THE TYPED CITY'S, OR COUNTY'S, CENTRE IS A TYPO, NOT THE JOB (the 2026-10-22 audit's
# finding 3: "Wichita", "KS", zip 10001 measured to New York). The zip table has no state column, so where its centre lies is the
# check. Generous on purpose: a real zip of a big city, or of a big western county, stays well inside these.
_ZIP_AGREES_MILES = {"city": 40.0, "county": 150.0}


def _straight_miles(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """Great-circle miles between two `{lon, lat}` points. Used ONLY to check a zip against the typed
    city or county; never as a distance answer (that is always OSRM's driving figure)."""
    lon1, lat1, lon2, lat2 = map(math.radians, (a["lon"], a["lat"], b["lon"], b["lat"]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 3958.8 * math.asin(min(1.0, math.sqrt(h)))


def approx_point(city: Any = "", state: Any = "", zip_code: Any = "", county: Any = "") -> Optional[Dict[str, Any]]:
    """`{precision, label, lon, lat}` for a job with no usable street, or None: the ZIP's centre
    (tightest), else the CITY's (within the typed state), else the COUNTY's. A zip whose centre is
    far from the typed city's (or, with no city found, the county's) is set aside for that one."""
    zip_pt = None
    digits = re.sub(r"\D", "", str(zip_code or ""))
    if len(digits) >= 5:
        hit = _gazetteer()["zcta"].get(digits[:5])
        if hit:
            zip_pt = {"precision": "zip", "label": "zip " + digits[:5], "lon": hit[0], "lat": hit[1]}
    st = _state_code(state)
    named = _place(city, st) if st else None
    if named is None and str(county or "").strip():
        named = _county(county, state)
    if zip_pt is not None and (named is None or
                               _straight_miles(zip_pt, named) <= _ZIP_AGREES_MILES[named["precision"]]):
        return zip_pt
    return named


def can_place(address: Any = "", city: Any = "", state: Any = "", zip_code: Any = "", county: Any = "") -> bool:
    """IS THERE ENOUGH TO ASK? A street that can be placed (city+state or a zip), OR a zip, OR a city
    with its state, OR a county with a state (its own ", KS" or the state box). js/bid-model.js
    distanceKey applies the same rule, so the page never asks for what this would call incomplete
    (tests/test_distance_key_parity.py runs the two over one table)."""
    def one(v: Any) -> str:
        return re.sub(r"\s+", " ", str(v or "")).strip()
    c, st, z, k = one(city), one(state), one(zip_code), one(county)
    if clean_address(address, city, state, zip_code):
        return True
    if z or (c and st):
        return True
    return bool(k and (st or _split_state(k)[1]))


def _key(addr: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", addr.lower()).strip()


def _cache_get(k: str):
    with _cache_lock:
        hit = _cache.get(k)
        if hit and hit[0] > time.time():
            return hit
        _cache.pop(k, None)
    return None


def _cache_put(k: str, miles: Optional[float], reason: str, ttl: int) -> None:
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            _cache.clear()
        _cache[k] = (time.time() + ttl, miles, reason)


def _centre_key(pt: Dict[str, Any]) -> str:
    """A centre's cache key. "@" keeps it apart from every street key (_key never emits one)."""
    return "@%s %.4f %.4f" % (pt["precision"], pt["lon"], pt["lat"])


def rate_limited(bucket: str) -> bool:
    """True when `bucket` has used its calls for the window. Counts this call when it is not."""
    now = time.time()
    hits = [t for t in _rate_hits.get(bucket, []) if now - t < _RATE_WINDOW]
    if len(hits) >= _RATE_MAX:
        _rate_hits[bucket] = hits
        return True
    hits.append(now)
    _rate_hits[bucket] = hits
    return False


def _timeout(deadline: float) -> Optional[httpx.Timeout]:
    """What one call may spend: the usual allowance, cut to what is left of the budget. None when
    nothing is left (the caller then skips the call)."""
    left = deadline - _now()
    if left <= 0.05:
        return None
    return httpx.Timeout(min(TIMEOUT_SECONDS, left), connect=min(CONNECT_SECONDS, left))


def _routes_post(addr: str, key: str, timeout: httpx.Timeout) -> httpx.Response:
    body = {
        "origin": {"address": OFFICE_ADDRESS},
        "destination": {"address": addr},
        "travelMode": "DRIVE",
        "units": "IMPERIAL",
    }
    headers = {"X-Goog-Api-Key": key, "X-Goog-FieldMask": "routes.distanceMeters"}
    with httpx.Client(timeout=timeout, transport=_TRANSPORT) as c:
        return c.post(ROUTES_URL, json=body, headers=headers)


def _census_get(addr: str, timeout: httpx.Timeout) -> httpx.Response:
    params = {"address": addr, "benchmark": "Public_AR_Current", "format": "json"}
    with httpx.Client(timeout=timeout, transport=_TRANSPORT) as c:
        return c.get(CENSUS_URL, params=params, headers={"User-Agent": USER_AGENT})


def _osrm_get(lon: float, lat: float, timeout: httpx.Timeout) -> httpx.Response:
    url = "%s%.6f,%.6f;%.6f,%.6f" % (OSRM_URL, OFFICE_LON, OFFICE_LAT, lon, lat)
    with httpx.Client(timeout=timeout, transport=_TRANSPORT) as c:
        return c.get(url, params={"overview": "false"}, headers={"User-Agent": USER_AGENT})


def _miles(meters: Any) -> Optional[float]:
    """Meters to miles, one decimal, or None for anything that is not a real distance."""
    try:
        m = float(meters)
    except (TypeError, ValueError):
        return None
    if not (m >= 0) or m == float("inf"):      # NaN fails the first test too
        return None
    return round(m / METERS_PER_MILE, 1)


def _google(addr: str, key: str, deadline: Optional[float] = None) -> tuple:
    """(miles | None, reason). reason is "" on success, else not_found | error. `deadline` is the
    lookup's shared budget; called on its own it gets a fresh one."""
    if deadline is None:
        deadline = _now() + TOTAL_BUDGET_SECONDS
    timeout = _timeout(deadline)
    if timeout is None:
        return None, "error"
    try:
        resp = _routes_post(addr, key, timeout)
    except Exception as exc:  # noqa: BLE001 -- timeout, DNS, TLS: all the same answer, "unknown"
        # The message can carry the request URL; it never carries the key (header, not query).
        log.warning("distance lookup failed: %s", type(exc).__name__)
        return None, "error"
    if resp.status_code == 200:
        try:
            routes = (resp.json() or {}).get("routes") or []
            meters = (routes[0] or {}).get("distanceMeters")
            float(meters)
        except Exception:  # noqa: BLE001 -- 200 with no route: Google could not place it
            return None, "not_found"
        miles = _miles(meters)
        return (miles, "") if miles is not None else (None, "error")
    if resp.status_code in (400, 404):
        # An address Google cannot resolve is a 400/404 with a status body. Never retried.
        return None, "not_found"
    log.warning("distance lookup: Google answered %s", resp.status_code)
    return None, "error"


def _geocode(addr: str, state: str, deadline: float) -> tuple:
    """(lon, lat, reason) from the Census geocoder. No match is "not_found", never a guess."""
    timeout = _timeout(deadline)
    if timeout is None:
        return None, None, "error"
    try:
        resp = _census_get(addr, timeout)
    except Exception as exc:  # noqa: BLE001
        log.warning("census geocode failed: %s", type(exc).__name__)
        return None, None, "error"
    if resp.status_code != 200:
        log.warning("census geocode answered %s", resp.status_code)
        return None, None, "error"
    try:
        matches = ((resp.json() or {}).get("result") or {}).get("addressMatches") or []
    except Exception:  # noqa: BLE001 -- not JSON / not an object: the service is misbehaving
        return None, None, "error"
    if not matches:
        return None, None, "not_found"
    try:
        m = matches[0] or {}
        coords = m["coordinates"]
        lon = float(coords["x"])
        lat = float(coords["y"])
    except Exception:  # noqa: BLE001
        return None, None, "not_found"
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None, None, "not_found"
    # A match in a different state than the one typed is a street the typed town does not have.
    try:
        got = str(((m.get("addressComponents") or {}).get("state")) or "").upper()
    except Exception:  # noqa: BLE001 -- components that are not an object: no state to compare
        got = ""
    if state and got and got != state.upper():
        return None, None, "not_found"
    return lon, lat, ""


def _osrm(lon: float, lat: float, deadline: float) -> tuple:
    """(miles | None, reason): driving distance office -> (lon, lat) from the OSRM public router."""
    timeout = _timeout(deadline)
    if timeout is None:
        return None, "error"
    try:
        resp = _osrm_get(lon, lat, timeout)
    except Exception as exc:  # noqa: BLE001
        log.warning("osrm route failed: %s", type(exc).__name__)
        return None, "error"
    try:
        body = resp.json()
        code = str(body.get("code") or "")
        if resp.status_code == 200 and code == "Ok":
            routes = body.get("routes") or []
            miles = _miles((routes[0] or {}).get("distance")) if routes else None
            return (miles, "") if miles is not None else (None, "error")
        if code in ("NoRoute", "NoSegment"):
            return None, "not_found"
    except Exception:  # noqa: BLE001 -- 200 with a body that is not the promised shape: unknown
        log.warning("osrm answered %s with an unexpected body", resp.status_code)
        return None, "error"
    log.warning("osrm answered %s %s", resp.status_code, code)
    return None, "error"


def _free(addr: str, state: str, deadline: float) -> tuple:
    """Census geocode of the job, then ONE OSRM route from the pinned office coordinates.
    (miles | None, reason, missed): `missed` is True only when the GEOCODER said "no such street"
    (not an outage, and not a route OSRM could not find), the one case that falls back to a centre."""
    lon, lat, why = _geocode(addr, state, deadline)
    if why:
        return None, why, why == "not_found"
    miles, reason = _osrm(lon, lat, deadline)
    return miles, reason, False


def _street(addr: str, state: Any, deadline: float) -> tuple:
    """(miles | None, reason, missed) for a street line, through the cache. A street the geocoder
    could not find is kept as a short miss, so a re-ask goes straight to the fallback. `deadline`
    is the whole lookup's (lookup), which a fallback to a centre then spends what is left of."""
    ck = _key(addr)
    hit = _cache_get(ck)
    if hit:
        return hit[1], hit[2], hit[1] is None and hit[2] == "not_found_street"
    miles: Optional[float] = None
    reason = "error"
    missed = False
    key = api_key()
    if key:
        miles, reason = _google(addr, key, deadline)
    if miles is None:
        # No key, or Google failed: the free pair. Its answer is the final one.
        st = str(state or "").strip()[:2]
        miles, reason, missed = _free(addr, st, deadline)
    if miles is not None:
        _cache_put(ck, miles, "", _CACHE_TTL_OK)
        return miles, "", False
    if reason == "not_found":
        _cache_put(ck, None, "not_found_street" if missed else "not_found", _CACHE_TTL_MISS)
    return None, reason, missed


def _centre(pt: Dict[str, Any], deadline: float) -> tuple:
    """(miles | None, reason): driving miles to a centre, the same OSRM call a street gets, inside
    the lookup's one `deadline`: after a street the geocoder missed it gets only what that left
    (the 2026-10-22 audit's finding 2: a fresh budget here ran past the page's abort)."""
    ck = _centre_key(pt)
    hit = _cache_get(ck)
    if hit:
        return hit[1], hit[2]
    miles, reason = _osrm(pt["lon"], pt["lat"], deadline)
    if miles is not None:
        _cache_put(ck, miles, "", _CACHE_TTL_OK)
        return miles, ""
    if reason == "not_found":
        _cache_put(ck, None, "not_found", _CACHE_TTL_MISS)
    return None, reason


def lookup(address: Any, city: Any = "", state: Any = "", zip_code: Any = "", county: Any = "") -> Dict[str, Any]:
    """`{ok, miles, reason, address, office, precision, measured_to, street_not_found}`. `miles` is
    a float (one decimal) or None; `reason` is "" on success, else one of incomplete | not_found |
    error. `precision` says what was measured to: "street" (the address), "zip", "city" or "county"
    (that one's centre: no street, or a street the geocoder could not find, which also sets
    `street_not_found`), "" with no figure. `measured_to` names it ("Wichita, KS"). (`no_key` is no
    longer produced: the free providers need none. The page still understands it.)"""
    addr = clean_address(address, city, state, zip_code)
    out: Dict[str, Any] = {"ok": False, "miles": None, "reason": "", "address": addr,
                           "office": OFFICE_LABEL, "precision": "", "measured_to": "",
                           "street_not_found": False}
    if not can_place(address, city, state, zip_code, county):
        out["reason"] = "incomplete"
        return out
    # ONE budget for the whole lookup, the street's calls and a centre's route together (WORST_CASE_SECONDS).
    deadline = _now() + TOTAL_BUDGET_SECONDS
    if addr:
        miles, reason, missed = _street(addr, state, deadline)
        if miles is not None:
            out.update(ok=True, miles=miles, precision="street", measured_to=addr)
            return out
        if not missed:
            out["reason"] = "not_found" if reason == "not_found_street" else reason
            return out
        out["street_not_found"] = True
    pt = approx_point(city, state, zip_code, county)
    if pt is None:
        out["reason"] = "not_found"
        return out
    miles, reason = _centre(pt, deadline)
    if miles is None:
        out["reason"] = reason or "error"
        return out
    out.update(ok=True, miles=miles, precision=pt["precision"], measured_to=pt["label"])
    return out


# ---------------------------------------------------------------------------------------------
# COUNTY FROM THE ADDRESS (Hanz, 2026-10-13: "shouldn't this autofill based on the address?").
#
# The intake's "County remodel tax" box was picked by hand. The Census geocoder that already
# places the job for the distance lookup also answers "which county, and which city" from the
# SAME address, through its geographies endpoint (free, no key). Same rules as the distance
# lookup: server-side, short timeouts, one shared time budget, a 24 h cache, an answer that is
# ALWAYS a plain dict, and never a guess. A failure is `ok: false` with a reason and the page
# leaves the box exactly as it was.
#
# Two layers are asked for in the one call: Counties, and Incorporated Places. The picker's own
# list says a county row is the county-only FLOOR rate, correct for unincorporated land, and that
# a job inside a city's limits needs that city's full rate (js/county-picker.js, reference_tax.py).
# So the answer carries the city as `place` too and the page prefers a verified city row when the
# picker has one; Overland Park filled as "Johnson County" would under-tax the bid by 1.5 points.
# ---------------------------------------------------------------------------------------------
GEOGRAPHIES_URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
_county_cache: Dict[str, tuple] = {}   # key -> (expires_at, result dict | None, reason)


def _census_geographies_get(addr: str, timeout: httpx.Timeout) -> httpx.Response:
    params = {"address": addr, "benchmark": "Public_AR_Current", "vintage": "Current_Current",
              "layers": "Counties,Incorporated Places", "format": "json"}
    with httpx.Client(timeout=timeout, transport=_TRANSPORT) as c:
        return c.get(GEOGRAPHIES_URL, params=params, headers={"User-Agent": USER_AGENT})


def _county_cache_get(k: str):
    with _cache_lock:
        hit = _county_cache.get(k)
        if hit and hit[0] > time.time():
            return hit
        _county_cache.pop(k, None)
    return None


def _county_cache_put(k: str, found: Optional[dict], reason: str, ttl: int) -> None:
    with _cache_lock:
        if len(_county_cache) >= _CACHE_MAX:
            _county_cache.clear()
        _county_cache[k] = (time.time() + ttl, found, reason)


def _first_name(rows: Any, key: str) -> str:
    """The `key` of the first row of a geographies layer, or "" for anything else."""
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return ""
    v = rows[0].get(key)
    return re.sub(r"\s+", " ", v).strip() if isinstance(v, str) else ""


def _geography(addr: str, state: str, zip5: str, deadline: float) -> tuple:
    """({county, state, fips, place, place_sure} | None, reason). reason is "" on success, else
    not_found | error. `place_sure` is False when a zip was typed and the Census matched the street in
    a DIFFERENT zip: the geocoder then found another stretch of the same street name (it put
    701 N 7th St, Kansas City KS 66101 in Edwardsville, 66111). The county is still right, but the
    city is not to be trusted, and the page falls back to the city the estimator typed.

    No match, a match in another state than the one typed, or no county layer is "not_found";
    anything that is not the promised JSON shape is "error"."""
    timeout = _timeout(deadline)
    if timeout is None:
        return None, "error"
    try:
        resp = _census_geographies_get(addr, timeout)
    except Exception as exc:  # noqa: BLE001
        log.warning("census geographies failed: %s", type(exc).__name__)
        return None, "error"
    if resp.status_code != 200:
        log.warning("census geographies answered %s", resp.status_code)
        return None, "error"
    try:
        matches = ((resp.json() or {}).get("result") or {}).get("addressMatches") or []
        if not matches:
            return None, "not_found"
        m = matches[0] or {}
        geos = m.get("geographies") or {}
        counties = geos.get("Counties")
        county = _first_name(counties, "NAME")
        fips = _first_name(counties, "GEOID")
        place_row = _first_name(geos.get("Incorporated Places"), "BASENAME")
        comps = m.get("addressComponents") or {}
        got = str(comps.get("state") or "").upper()
        got_zip = re.sub(r"\D", "", str(comps.get("zip") or ""))[:5]
    except Exception:  # noqa: BLE001 -- not JSON / not an object: the service is misbehaving
        return None, "error"
    if not county:
        return None, "not_found"
    if state and got and got != state.upper():
        return None, "not_found"          # a street the typed town does not have
    sure = not (zip5 and got_zip and got_zip != zip5)
    return {"county": county, "state": got or state.upper(), "fips": fips, "place": place_row,
            "place_sure": sure}, ""


def county_lookup(address: Any, city: Any = "", state: Any = "", zip_code: Any = "") -> Dict[str, Any]:
    """`{ok, county, state, fips, place, reason, address}`. `county` is the Census name as it
    stands ("Sedgwick County"); `place` is the incorporated city ("" when the address is in none);
    `place_sure` is False when the Census matched the street in another zip than the one typed;
    `reason` is "" on success, else incomplete | not_found | error. Never raises."""
    addr = clean_address(address, city, state, zip_code)
    out: Dict[str, Any] = {"ok": False, "county": "", "state": "", "fips": "", "place": "",
                           "place_sure": True, "reason": "", "address": addr}
    if not addr:
        out["reason"] = "incomplete"
        return out
    ck = _key(addr)
    hit = _county_cache_get(ck)
    if hit:
        if hit[1]:
            out.update(hit[1])
            out["ok"] = True
        else:
            out["reason"] = hit[2]
        return out
    st = str(state or "").strip()[:2]
    zip5 = re.sub(r"\D", "", str(zip_code or ""))[:5]
    found, reason = _geography(addr, st, zip5, _now() + TOTAL_BUDGET_SECONDS)
    if found:
        _county_cache_put(ck, found, "", _CACHE_TTL_OK)
        out.update(found)
        out["ok"] = True
        return out
    if reason == "not_found":
        _county_cache_put(ck, None, "not_found", _CACHE_TTL_MISS)
    out["reason"] = reason or "error"
    return out
