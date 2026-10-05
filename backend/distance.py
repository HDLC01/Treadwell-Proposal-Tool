"""Driving miles from the Olathe office to a job address (Google Routes API).

WHY THIS EXISTS. Kyle's 9/18 notes: take the "70 mile slider" off intake and work the distance out
from the job address, so the estimate knows whether Travel Labor, Lodging and Per Diem apply.
Hanz, 2026-10-05: driving miles, called SERVER-SIDE (the key never reaches a browser and the nginx
CSP needs no change), key from the environment as GOOGLE_MAPS_API_KEY.

NEVER GUESS. Every path that cannot produce a real figure answers `miles: None` with a `reason`
(no key, address not found, Google slow or down, address incomplete, rate limit). The page turns
that into "Distance unknown -- enter miles" and lets the estimator type the number. There is no
straight-line fallback and no default distance: a wrong answer near 70 miles moves a bid by
thousands of dollars in either direction.

NEVER SLOW THE PAGE. One short timeout, no retry, and the page calls this after it has painted.

NO KEY, NO CALL. With GOOGLE_MAPS_API_KEY unset nothing leaves this process.
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

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
METERS_PER_MILE = 1609.344

# Google answers in well under a second. Past this the estimator is better served by typing the
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


def lookup(address: Any, city: Any = "", state: Any = "", zip_code: Any = "") -> Dict[str, Any]:
    """`{ok, miles, reason, address}`. `miles` is a float (one decimal) or None; `reason` is
    "" on success, else one of incomplete | no_key | not_found | error."""
    addr = clean_address(address, city, state, zip_code)
    out: Dict[str, Any] = {"ok": False, "miles": None, "reason": "", "address": addr,
                           "office": OFFICE_LABEL}
    if not addr:
        out["reason"] = "incomplete"
        return out
    key = api_key()
    if not key:
        out["reason"] = "no_key"
        return out
    ck = _key(addr)
    hit = _cache_get(ck)
    if hit:
        out.update(ok=hit[1] is not None, miles=hit[1], reason=hit[2])
        return out
    try:
        resp = _routes_post(addr, key)
    except Exception as exc:  # noqa: BLE001 -- timeout, DNS, TLS: all the same answer, "unknown"
        # The message can carry the request URL; it never carries the key (header, not query).
        log.warning("distance lookup failed: %s", type(exc).__name__)
        out["reason"] = "error"
        return out
    if resp.status_code == 200:
        try:
            routes = (resp.json() or {}).get("routes") or []
            meters = float((routes[0] or {}).get("distanceMeters"))
        except Exception:  # noqa: BLE001 -- 200 with no route: Google could not place it
            _cache_put(ck, None, "not_found", _CACHE_TTL_MISS)
            out["reason"] = "not_found"
            return out
        if not (meters >= 0):          # NaN fails this too
            out["reason"] = "error"
            return out
        miles = round(meters / METERS_PER_MILE, 1)
        _cache_put(ck, miles, "", _CACHE_TTL_OK)
        out.update(ok=True, miles=miles)
        return out
    if resp.status_code in (400, 404):
        # An address Google cannot resolve is a 400/404 with a status body. Never retried.
        _cache_put(ck, None, "not_found", _CACHE_TTL_MISS)
        out["reason"] = "not_found"
        return out
    log.warning("distance lookup: Google answered %s", resp.status_code)
    out["reason"] = "error"
    return out
