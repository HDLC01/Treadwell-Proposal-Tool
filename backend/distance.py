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

NEVER GUESS. Every path that cannot produce a real figure answers `miles: None` with a `reason`
(address not found, a service slow or down, address incomplete, rate limit). The page turns that
into "Distance unknown -- enter miles" and lets the estimator type the number. There is no
straight-line fallback, no city-centre guess and no default distance: a wrong answer near 70 miles
moves a bid by thousands of dollars in either direction.

NEVER SLOW THE PAGE. Short timeouts, no retry, and the page calls this after it has painted.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Any, Dict, Optional

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


def _routes_post(addr: str, key: str) -> httpx.Response:
    body = {
        "origin": {"address": OFFICE_ADDRESS},
        "destination": {"address": addr},
        "travelMode": "DRIVE",
        "units": "IMPERIAL",
    }
    headers = {"X-Goog-Api-Key": key, "X-Goog-FieldMask": "routes.distanceMeters"}
    with httpx.Client(timeout=TIMEOUT_SECONDS, transport=_TRANSPORT) as c:
        return c.post(ROUTES_URL, json=body, headers=headers)


def _census_get(addr: str) -> httpx.Response:
    params = {"address": addr, "benchmark": "Public_AR_Current", "format": "json"}
    with httpx.Client(timeout=TIMEOUT_SECONDS, transport=_TRANSPORT) as c:
        return c.get(CENSUS_URL, params=params, headers={"User-Agent": USER_AGENT})


def _osrm_get(lon: float, lat: float) -> httpx.Response:
    url = "%s%.6f,%.6f;%.6f,%.6f" % (OSRM_URL, OFFICE_LON, OFFICE_LAT, lon, lat)
    with httpx.Client(timeout=TIMEOUT_SECONDS, transport=_TRANSPORT) as c:
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


def _google(addr: str, key: str) -> tuple:
    """(miles | None, reason). reason is "" on success, else not_found | error."""
    try:
        resp = _routes_post(addr, key)
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


def _geocode(addr: str, state: str) -> tuple:
    """(lon, lat, reason) from the Census geocoder. No match is "not_found", never a guess."""
    try:
        resp = _census_get(addr)
    except Exception as exc:  # noqa: BLE001
        log.warning("census geocode failed: %s", type(exc).__name__)
        return None, None, "error"
    if resp.status_code != 200:
        log.warning("census geocode answered %s", resp.status_code)
        return None, None, "error"
    try:
        matches = ((resp.json() or {}).get("result") or {}).get("addressMatches") or []
    except Exception:  # noqa: BLE001 -- not JSON: the service is misbehaving, not "no match"
        return None, None, "error"
    if not matches:
        return None, None, "not_found"
    m = matches[0] or {}
    try:
        lon = float(m["coordinates"]["x"])
        lat = float(m["coordinates"]["y"])
    except Exception:  # noqa: BLE001
        return None, None, "not_found"
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None, None, "not_found"
    # A match in a different state than the one typed is a street the typed town does not have.
    got = str(((m.get("addressComponents") or {}).get("state")) or "").upper()
    if state and got and got != state.upper():
        return None, None, "not_found"
    return lon, lat, ""


def _osrm(lon: float, lat: float) -> tuple:
    """(miles | None, reason): driving distance office -> (lon, lat) from the OSRM public router."""
    try:
        resp = _osrm_get(lon, lat)
    except Exception as exc:  # noqa: BLE001
        log.warning("osrm route failed: %s", type(exc).__name__)
        return None, "error"
    try:
        body = resp.json() or {}
    except Exception:  # noqa: BLE001
        body = {}
    code = str(body.get("code") or "")
    if resp.status_code == 200 and code == "Ok":
        routes = body.get("routes") or []
        miles = _miles((routes[0] or {}).get("distance")) if routes else None
        return (miles, "") if miles is not None else (None, "error")
    if code in ("NoRoute", "NoSegment"):
        return None, "not_found"
    log.warning("osrm answered %s %s", resp.status_code, code)
    return None, "error"


def _free(addr: str, state: str) -> tuple:
    """Census geocode of the job, then ONE OSRM route from the pinned office coordinates."""
    lon, lat, why = _geocode(addr, state)
    if why:
        return None, why
    return _osrm(lon, lat)


def lookup(address: Any, city: Any = "", state: Any = "", zip_code: Any = "") -> Dict[str, Any]:
    """`{ok, miles, reason, address}`. `miles` is a float (one decimal) or None; `reason` is
    "" on success, else one of incomplete | not_found | error. (`no_key` is no longer produced: the
    free providers need none. The page still understands it.)"""
    addr = clean_address(address, city, state, zip_code)
    out: Dict[str, Any] = {"ok": False, "miles": None, "reason": "", "address": addr,
                           "office": OFFICE_LABEL}
    if not addr:
        out["reason"] = "incomplete"
        return out
    ck = _key(addr)
    hit = _cache_get(ck)
    if hit:
        out.update(ok=hit[1] is not None, miles=hit[1], reason=hit[2])
        return out
    miles: Optional[float] = None
    reason = "error"
    key = api_key()
    if key:
        miles, reason = _google(addr, key)
    if miles is None:
        # No key, or Google failed: the free pair. Its answer is the final one.
        st = str(state or "").strip()[:2]
        miles, reason = _free(addr, st)
    if miles is not None:
        _cache_put(ck, miles, "", _CACHE_TTL_OK)
        out.update(ok=True, miles=miles)
        return out
    if reason == "not_found":
        _cache_put(ck, None, "not_found", _CACHE_TTL_MISS)
    out["reason"] = reason
    return out
