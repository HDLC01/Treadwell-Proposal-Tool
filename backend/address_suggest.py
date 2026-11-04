"""House-numbered address suggestions from the US Census geocoder, for the intake's Address box.

Hanz, 2026-11-05: "there are some addresses that are missing". The box suggests from Photon
(OpenStreetMap, asked straight from the browser, js/address-lookup.js), and OSM lacks many house
numbers: "8200 Nieman Road" comes back as the bare street. The Census geocoder this server already
uses for the distance and the county (backend/distance.py) does know them, measured live that day:

    "8200 Nieman Rd, KS"   -> 8200 NIEMAN RD, OVERLAND PARK, KS, 66214
    "1707 E 123rd Ter, KS" -> 1707 E 123RD TER, OLATHE, KS, 66061
    "8200 Nieman Rd, MO"   -> no match

A state alone, no city, is enough. So when the person has typed a house number and a street and
Photon has no row with that number, the page asks POST /api/address-suggest {q}, and this module asks
the Census for "<q>, KS" and "<q>, MO" side by side (the office is in Olathe; nearly every job is in
one of the two), or just the one question when the text already names a state or a zip.

ALWAYS an answer, never an exception: {ok, rows, reason}. reason is "" | thin (not a house number and a
street) | not_found | error. Up to MAX_ROWS rows, nearest the office first, each
{line1, city, state, zip, lat, lon}, title-cased for the screen ("8200 Nieman Rd", "Overland Park").

The requests go through distance._census_get, unchanged, so the tests' httpx.MockTransport on
distance._TRANSPORT covers this module too and nothing here can reach the network in a test.
"""
from __future__ import annotations

import concurrent.futures
import logging
import math
import re
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

import distance

log = logging.getLogger("treadwell.address_suggest")

# The whole answer, both questions included, within this. The page gives up at 8 s
# (js/address-lookup.js CENSUS_TIMEOUT_MS); a Census answer takes about 1.6 s.
BUDGET_SECONDS = 5.0
WAIT_SLACK_SECONDS = 0.25
MAX_ROWS = 3
MAX_QUERY = 120

# A small LRU. Real answers are kept a day, "no such address" ten minutes, errors never.
_CACHE_MAX = 200
_TTL_OK = 24 * 3600
_TTL_MISS = 10 * 60
_cache: "OrderedDict[str, Tuple[float, List[Dict[str, Any]], str]]" = OrderedDict()
_lock = threading.Lock()

_STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA",
    "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}
_ABBRS = frozenset(_STATE_NAMES.values())
# Two state codes that are also street words ("Ct" Court, "Wy" Way): a state only after a comma.
_ABBR_NEEDS_COMMA = frozenset({"CT", "WY"})
_DIRECTIONS = frozenset({"N", "S", "E", "W", "NE", "NW", "SE", "SW"})

_HOUSE = re.compile(r"\d{1,6}[A-Za-z]?")
_ZIP = re.compile(r"\d{5}(?:-\d{4})?")
_LETTERS2 = re.compile(r"[A-Za-z]{2}")
_ORDINAL = re.compile(r"(\d+)(ST|ND|RD|TH)", re.I)


def clean(q: Any) -> str:
    """The query on one line, capped. Every pattern below runs over at most MAX_QUERY characters."""
    return re.sub(r"\s+", " ", str(q if q is not None else "")).strip()[:MAX_QUERY]


def has_house_number(q: str) -> bool:
    """A house number first, then a street (a later word with two letters in it). Token checks, not
    one regex over the free text."""
    words = q.replace(",", " ").split()
    if len(words) < 2 or not _HOUSE.fullmatch(words[0]):
        return False
    return any(_LETTERS2.search(w) for w in words[1:])


def named_place(q: str) -> Tuple[str, bool]:
    """(state code or "", has a zip) the text already names. "8200 Nieman Rd, KS" -> ("KS", False);
    "8200 Nieman Rd 66214" -> ("", True); "8200 Nieman Rd" -> ("", False). Token checks only."""
    words: List[Tuple[str, bool]] = []          # (word, a comma came right before it)
    comma = False
    for raw in q.split():
        if raw.startswith(","):
            comma = True
        w = raw.strip(",")
        if w:
            words.append((w, comma))
            comma = False
        if raw.endswith(","):
            comma = True
    tail = words[1:]                              # the house number is never the state or the zip
    zip_found = any(_ZIP.fullmatch(w) for w, _c in tail)
    if tail and _ZIP.fullmatch(tail[-1][0]):      # "..., KS 66214": the state sits before the zip
        tail = tail[:-1]
    # The state is the last word, or the last two ("New York"), and a street word must come before it.
    for n in (2, 1):
        if len(tail) > n:
            name = " ".join(w for w, _c in tail[-n:]).lower().rstrip(".")
            if name in _STATE_NAMES:
                return _STATE_NAMES[name], zip_found
    if len(tail) > 1:
        last, after_comma = tail[-1][0].rstrip(".").upper(), tail[-1][1]
        if last in _ABBRS and (after_comma or last not in _ABBR_NEEDS_COMMA):
            return last, zip_found
    return "", zip_found


def questions(q: str) -> List[Tuple[str, str]]:
    """[(one-line address, the state its answers must be in or "")]: the text as typed when it names a
    state or a zip, else the text in Kansas and in Missouri."""
    st, has_zip = named_place(q)
    if st or has_zip:
        return [(q, st)]
    return [(q + ", KS", "KS"), (q + ", MO", "MO")]


def _word(w: str) -> str:
    """One word of a Census address for the screen: N/E/S/W stay capitals, 123RD is 123rd,
    LEE'S is Lee's, O'FALLON is O'Fallon."""
    up = w.upper()
    if up in _DIRECTIONS:
        return up
    if _ORDINAL.fullmatch(w):
        return w.lower()
    out = re.sub(r"[A-Za-z]+", lambda m: m.group(0).capitalize(), w.lower())
    return re.sub(r"'S\b", "'s", out)


def title(s: Any) -> str:
    return " ".join(_word(w) for w in str(s or "").split())


def _miles(lat: float, lon: float) -> float:
    """Straight-line miles from the office (the same haversine the page ranks Photon's rows with)."""
    r = math.pi / 180
    d_lat = (lat - distance.OFFICE_LAT) * r
    d_lon = (lon - distance.OFFICE_LON) * r
    a = (math.sin(d_lat / 2) ** 2 +
         math.cos(distance.OFFICE_LAT * r) * math.cos(lat * r) * math.sin(d_lon / 2) ** 2)
    return 2 * 3958.8 * math.asin(min(1.0, math.sqrt(a)))


def parse(body: Any, want_state: str = "") -> List[Dict[str, Any]]:
    """Rows from one Census onelineaddress answer. matchedAddress ("8200 NIEMAN RD, OVERLAND PARK,
    KS, 66214") carries the house number as matched; addressComponents.fromAddress is only the start
    of the block's range, so it is never used for the number. City, state and zip fall back to the
    components. A row without a usable point, a number, or a state, or in another state than the
    one asked, is skipped. Raises nothing."""
    rows: List[Dict[str, Any]] = []
    try:
        matches = ((body or {}).get("result") or {}).get("addressMatches") or []
    except Exception:  # noqa: BLE001 -- not an object
        return rows
    if not isinstance(matches, list):
        return rows
    for m in matches:
        try:
            if not isinstance(m, dict):
                continue
            comps = m.get("addressComponents") if isinstance(m.get("addressComponents"), dict) else {}
            parts = [p.strip() for p in str(m.get("matchedAddress") or "").split(",")]
            line1 = parts[0] if parts else ""
            city = parts[1] if len(parts) == 4 else str(comps.get("city") or "")
            st = (parts[2] if len(parts) == 4 else str(comps.get("state") or "")).strip().upper()
            zip5 = (parts[3] if len(parts) == 4 else str(comps.get("zip") or "")).strip()[:10]
            coords = m.get("coordinates") or {}
            lon, lat = float(coords["x"]), float(coords["y"])
        except Exception:  # noqa: BLE001 -- one malformed match: skip it
            continue
        if not (-180 <= lon <= 180 and -90 <= lat <= 90) or math.isnan(lon) or math.isnan(lat):
            continue
        if not line1 or not line1[0].isdigit() or len(st) != 2 or not st.isalpha():
            continue
        if want_state and st != want_state:
            continue
        rows.append({"line1": title(line1), "city": title(city), "state": st, "zip": zip5,
                     "lat": round(lat, 6), "lon": round(lon, 6)})
    return rows


def _ask(addr: str, want_state: str, deadline: float) -> Tuple[List[Dict[str, Any]], str]:
    """(rows, reason) for one question. reason "" | not_found | error."""
    timeout = distance._timeout(deadline)
    if timeout is None:
        return [], "error"
    try:
        resp = distance._census_get(addr, timeout)
    except Exception as exc:  # noqa: BLE001 -- timeout, DNS, TLS: all "no answer"
        log.warning("address suggest: census failed: %s", type(exc).__name__)
        return [], "error"
    if resp.status_code != 200:
        log.warning("address suggest: census answered %s", resp.status_code)
        return [], "error"
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001 -- not JSON
        return [], "error"
    rows = parse(body, want_state)
    return rows, ("" if rows else "not_found")


def _cache_key(q: str) -> str:
    """The questions the Census is asked for `q`, lower-cased: two texts share an answer only when they
    ask the same questions. NOT distance._key, which drops the punctuation: "123 Oak Ct" (Court, asked in
    KS and MO) and "123 Oak, CT" (Connecticut, asked once) would have shared one entry for a day.
    Spacing and case are already folded (clean, lower), so "8200  nieman rd" still hits."""
    if not q:
        return ""
    return "|".join(addr.lower() for addr, _st in questions(q))


def cached(q: Any) -> Optional[Dict[str, Any]]:
    """The cached answer for `q`, or None. The route asks this BEFORE the rate limit, so a repeat
    costs nothing."""
    k = _cache_key(clean(q))
    if not k:
        return None
    with _lock:
        hit = _cache.get(k)
        if not hit:
            return None
        if hit[0] <= time.time():
            _cache.pop(k, None)
            return None
        _cache.move_to_end(k)
        rows, reason = hit[1], hit[2]
    return {"ok": bool(rows), "rows": [dict(r) for r in rows], "reason": reason}


def _put(q: str, rows: List[Dict[str, Any]], reason: str, ttl: int) -> None:
    k = _cache_key(q)
    if not k:
        return
    with _lock:
        _cache[k] = (time.time() + ttl, [dict(r) for r in rows], reason)
        _cache.move_to_end(k)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)


def suggest(q: Any) -> Dict[str, Any]:
    """{ok, rows, reason}. See the module docstring. Never raises."""
    try:
        return _suggest(clean(q))
    except Exception as exc:  # noqa: BLE001 -- a convenience: any surprise is "no rows"
        log.warning("address suggest failed: %s", type(exc).__name__)
        return {"ok": False, "rows": [], "reason": "error"}


def _suggest(q: str) -> Dict[str, Any]:
    if not has_house_number(q):
        return {"ok": False, "rows": [], "reason": "thin"}
    hit = cached(q)
    if hit is not None:
        return hit
    asks = questions(q)
    deadline = distance._now() + BUDGET_SECONDS
    results: List[Tuple[List[Dict[str, Any]], str]] = []
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(asks), thread_name_prefix="addr-suggest")
    try:
        futs = [pool.submit(_ask, addr, st, deadline) for addr, st in asks]
        # The questions run side by side; the answer waits for them no longer than the budget. A
        # question still out by then is abandoned (its own httpx timeout ends it) and counts as "error".
        done, _ = concurrent.futures.wait(futs, timeout=max(0.0, deadline - distance._now()) + WAIT_SLACK_SECONDS)
        for f in futs:
            results.append(f.result() if f in done else ([], "error"))
    finally:
        pool.shutdown(wait=False)
    rows: List[Dict[str, Any]] = []
    seen = set()
    for got, _reason in results:
        for r in got:
            key = (r["line1"].lower(), r["city"].lower(), r["state"], r["zip"])
            if key in seen:
                continue
            seen.add(key)
            rows.append(r)
    rows.sort(key=lambda r: _miles(r["lat"], r["lon"]))
    rows = rows[:MAX_ROWS]
    errored = any(reason == "error" for _got, reason in results)
    if rows:
        if not errored:
            _put(q, rows, "", _TTL_OK)
        return {"ok": True, "rows": rows, "reason": ""}
    if errored:
        return {"ok": False, "rows": [], "reason": "error"}
    _put(q, [], "not_found", _TTL_MISS)
    return {"ok": False, "rows": [], "reason": "not_found"}
