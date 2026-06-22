"""Read-only Basisboard client.

Scope (deliberately): READ the projects/bids that already exist in Basisboard so
the proposal tool can show a simple pipeline CRM. No writes — nothing here
creates, updates, or deletes anything in Basisboard.

Conventions (mirrors dropbox_client.py): env-gated `is_configured()`, public
`get_pipeline()` returns a dict and never raises, generic client-facing errors
(detail goes to the server log only), inert when `BASISBOARD_API_KEY` is unset.

Architecture / performance:
  - One pooled `httpx.Client` per build (keep-alive connection reuse) shared
    across a small thread pool, so the ~13 calls a cold build needs run
    CONCURRENTLY instead of serially (measured ~13s -> ~4s).
  - Layered: transport (`_get`, retry/backoff) -> resource fetchers
    (`_fetch_stages/_users/_project_ids/_projects`) -> assembler (`_build_pipeline`)
    -> cached, coalesced entry point (`get_pipeline`). Each layer is reusable on
    its own (e.g. a future webhook handler can call a single resource fetcher).
  - Caches: stages/users (rarely change) 5 min; the assembled pipeline 60 s.
    A build lock coalesces concurrent cold requests into one fetch.

Read contract (https://api.basisboard.com/v1, `Authorization: Bearer <key>`):
  GET /stages                            -> {"stages":[{id,name,color,order}]}
  GET /users                             -> {"users":[{id,firstName,lastName,email}]}
  GET /projects/ids?limit&offset&sort[bidDeadline]=DESC
                                         -> {"projectIds":[...], "paging":{"total"}}
  GET /projects?filter[projectIds][]=... -> {"projects":[{id,name,location,quote,
                                              stageId,estimatorIds,awardedAt,archivedAt,deletedAt}]}
"""
from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import cachetools

log = logging.getLogger("proposal_tool.basisboard")

_DEFAULT_BASE = "https://api.basisboard.com/v1"
_TIMEOUT = 15.0
_PAGE = 50                # ids per /projects/ids page AND ids per /projects fetch
_CONCURRENCY = 8          # max parallel requests per build
_RETRIES = 1              # extra attempts on a transient (429 / 5xx / transport) error
_TRANSIENT = {429, 500, 502, 503, 504}

# stages/users change rarely; the assembled pipeline is cached briefly so a page
# refresh doesn't re-fetch everything. _BUILD_LOCK coalesces concurrent cold
# builds so 10 simultaneous loads trigger ONE fetch, not 10.
_meta_cache = cachetools.TTLCache(maxsize=4, ttl=300)
_pipeline_cache = cachetools.TTLCache(maxsize=1, ttl=60)
_BUILD_LOCK = threading.Lock()


# ── config ────────────────────────────────────────────────────────────
def _api_key() -> str:
    return (os.environ.get("BASISBOARD_API_KEY") or "").strip()


def _api_base() -> str:
    return (os.environ.get("BASISBOARD_API_BASE") or _DEFAULT_BASE).rstrip("/")


def _max_projects() -> int:
    """How many (most-recent) projects to pull for the board. The org has
    thousands of all-time bids; the pipeline view shows a recent, capped window."""
    try:
        return max(1, min(500, int(os.environ.get("BASISBOARD_MAX_PROJECTS") or 300)))
    except (TypeError, ValueError):
        return 300


def is_configured() -> bool:
    return bool(_api_key())


# ── transport ─────────────────────────────────────────────────────────
@contextmanager
def _session():
    """A pooled httpx.Client carrying auth; reused across the build's threads."""
    import httpx
    client = httpx.Client(
        timeout=_TIMEOUT,
        headers={"Authorization": f"Bearer {_api_key()}", "Accept": "application/json"},
        limits=httpx.Limits(max_connections=_CONCURRENCY, max_keepalive_connections=_CONCURRENCY),
    )
    try:
        yield client
    finally:
        client.close()


def _get(client, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Authenticated GET with a small retry on transient errors. Raises otherwise
    (the assembler wraps everything). `client` is a pooled httpx.Client."""
    import httpx
    last: Exception = RuntimeError("no attempt")
    for attempt in range(_RETRIES + 1):
        try:
            resp = client.get(_api_base() + path, params=params)
        except httpx.TransportError as exc:                 # network blip / timeout
            last = exc
        else:
            if resp.status_code not in _TRANSIENT:
                resp.raise_for_status()
                return resp.json()
            last = httpx.HTTPStatusError(f"transient {resp.status_code}",
                                         request=resp.request, response=resp)
        if attempt < _RETRIES:
            time.sleep(0.4 * (attempt + 1))
    raise last


# ── resource fetchers (each reusable on its own) ──────────────────────
def _fetch_stages(client) -> Dict[str, Dict[str, Any]]:
    cached = _meta_cache.get("stages")
    if cached is None:
        cached = {s["id"]: s for s in (_get(client, "/stages").get("stages") or []) if s.get("id")}
        _meta_cache["stages"] = cached
    return cached


def _fetch_users(client) -> Dict[str, str]:
    cached = _meta_cache.get("users")
    if cached is None:
        cached = {}
        for u in (_get(client, "/users").get("users") or []):
            if not u.get("id"):
                continue
            name = " ".join(p for p in (u.get("firstName"), u.get("lastName")) if p).strip()
            cached[u["id"]] = name or (u.get("email") or "")
        _meta_cache["users"] = cached
    return cached


def _ids_page(client, offset: int, sort: bool) -> Dict[str, Any]:
    params: Dict[str, Any] = {"limit": _PAGE, "offset": offset}
    if sort:
        params["sort[bidDeadline]"] = "DESC"
    return _get(client, "/projects/ids", params)


def _fetch_project_ids(client, cap: int, ex: Optional[ThreadPoolExecutor] = None):
    """Most-recent project ids up to `cap`. The first page (needed for `total`)
    is sequential; the rest fetch in parallel. Falls back to unsorted if the
    sort param is rejected. Returns (ids, total)."""
    sort = True
    try:
        first = _ids_page(client, 0, True)
    except Exception:                                   # noqa: BLE001 — retry unsorted
        sort, first = False, _ids_page(client, 0, False)
    ids: List[str] = list(first.get("projectIds") or first.get("ids") or [])
    total = (first.get("paging") or {}).get("total", len(ids))
    offsets = list(range(_PAGE, min(cap, total), _PAGE))
    if offsets:
        if ex is not None:
            pages = [f.result() for f in [ex.submit(_ids_page, client, o, sort) for o in offsets]]
        else:
            pages = [_ids_page(client, o, sort) for o in offsets]
        for pg in pages:
            ids.extend(pg.get("projectIds") or pg.get("ids") or [])
    return ids[:cap], total


def _fetch_projects(client, ids: List[str], ex: Optional[ThreadPoolExecutor] = None) -> List[Dict[str, Any]]:
    """Batch-fetch project details by id (50/req), in parallel when an executor
    is given."""
    chunks = [ids[i:i + _PAGE] for i in range(0, len(ids), _PAGE)]

    def fetch(chunk):
        return _get(client, "/projects", {"filter[projectIds][]": chunk}).get("projects") or []

    if ex is not None:
        results = [f.result() for f in [ex.submit(fetch, c) for c in chunks]]
    else:
        results = [fetch(c) for c in chunks]
    out: List[Dict[str, Any]] = []
    for r in results:
        out.extend(r)
    return out


# ── shaping + assembly ────────────────────────────────────────────────
def _shape_project(p: Dict[str, Any], stages: Dict[str, Dict[str, Any]],
                   users: Dict[str, str]) -> Dict[str, Any]:
    st = stages.get(p.get("stageId")) or {}
    return {
        "id": p.get("id"),
        "name": p.get("name") or "Untitled",
        "location": p.get("location") if (p.get("location") and p.get("location") != "N/A") else "",
        "value": p.get("quote"),
        "stage_id": p.get("stageId"),
        "stage_name": st.get("name") or "Unstaged",
        "stage_color": st.get("color") or "#5c403f",
        "stage_order": st.get("order", 9999),
        "estimators": [users.get(uid) for uid in (p.get("estimatorIds") or []) if users.get(uid)],
        "awarded": bool(p.get("awardedAt")),
        "archived": bool(p.get("archivedAt")),
    }


def _build_pipeline() -> Dict[str, Any]:
    """Fetch everything concurrently over one pooled client, then shape + sort."""
    with _session() as client, ThreadPoolExecutor(max_workers=_CONCURRENCY) as ex:
        f_stages = ex.submit(_fetch_stages, client)
        f_users = ex.submit(_fetch_users, client)
        pids, total = _fetch_project_ids(client, _max_projects(), ex)
        raw = _fetch_projects(client, pids, ex)
        stages, users = f_stages.result(), f_users.result()

    # Pipeline view = active bids: drop deleted + archived.
    shaped = [_shape_project(p, stages, users) for p in raw
              if not p.get("deletedAt") and not p.get("archivedAt")]
    shaped.sort(key=lambda x: (x["stage_order"], x["name"].lower()))
    stage_cols = sorted(
        ({"id": s.get("id"), "name": s.get("name"), "color": s.get("color"),
          "order": s.get("order", 9999)} for s in stages.values()),
        key=lambda s: s["order"],
    )
    return {"ok": True, "configured": True, "projects": shaped, "stages": stage_cols,
            "shown": len(shaped), "total": total}


def get_pipeline() -> Dict[str, Any]:
    """Read-only pipeline: active projects with stage + estimator names, plus the
    ordered stage columns. Cached 60 s; concurrent cold builds are coalesced.
    Returns {"ok": True, ...} or {"ok": False, "error": "<generic>"} — never raises."""
    if not is_configured():
        return {"ok": False, "configured": False, "error": "Basisboard is not configured"}
    cached = _pipeline_cache.get("pipeline")
    if cached is not None:
        return cached
    with _BUILD_LOCK:
        cached = _pipeline_cache.get("pipeline")        # another thread may have built it
        if cached is not None:
            return cached
        try:
            result = _build_pipeline()
        except Exception as exc:  # noqa: BLE001 — read view must never 500 the page
            log.warning("Basisboard get_pipeline failed: %s", exc)
            return {"ok": False, "configured": True, "error": "Couldn't reach Basisboard"}
        _pipeline_cache["pipeline"] = result
        return result
