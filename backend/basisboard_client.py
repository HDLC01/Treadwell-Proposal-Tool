"""Read-only Basisboard client.

Scope (deliberately): READ the projects/bids that already exist in Basisboard so
the proposal tool can show a simple pipeline CRM. No writes — nothing here
creates, updates, or deletes anything in Basisboard.

Mirrors the dropbox_client.py conventions: lazy `import httpx`, env-gated
`is_configured()`, public functions return a dict and never raise, generic
client-facing errors (details go to the server log only), and the whole thing is
inert when `BASISBOARD_API_KEY` is unset.

Basisboard read contract (api.basisboard.com/v1, `Authorization: Bearer <key>`):
  - GET /stages                          -> {"stages":[{id,name,color,order,code}]}
  - GET /users                           -> {"users":[{id,firstName,lastName,email}]}
  - GET /companies?limit=N               -> {"companies":[{id,name,projectIds:[...]}]}
  - GET /projects?filter[projectIds][]=  -> {"projects":[{id,name,location,quote,
                                              stageId,estimatorIds,awardedAt,archivedAt,deletedAt}]}
Projects aren't listable wholesale; each Company carries `projectIds`, so we page
Companies, gather the ids, then batch-fetch the Projects by id.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

import cachetools

log = logging.getLogger("proposal_tool.basisboard")

_DEFAULT_BASE = "https://api.basisboard.com/v1"
_TIMEOUT = 15.0
_PROJECT_ID_CHUNK = 50          # ids per /projects fetch (keeps the URL short)

# Short-lived caches. Stages/users change rarely; the assembled pipeline is
# cached briefly so a page refresh doesn't re-page the whole API every time.
_meta_cache = cachetools.TTLCache(maxsize=4, ttl=300)
_pipeline_cache = cachetools.TTLCache(maxsize=1, ttl=60)


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


def _get(path: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Authenticated GET. Raises on transport/HTTP error (callers wrap)."""
    import httpx
    headers = {"Authorization": f"Bearer {_api_key()}", "Accept": "application/json"}
    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.get(f"{_api_base()}{path}", params=params, headers=headers)
    resp.raise_for_status()
    return resp.json()


def _chunks(seq: List[Any], n: int):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _stages_by_id() -> Dict[str, Dict[str, Any]]:
    cached = _meta_cache.get("stages")
    if cached is None:
        cached = {s["id"]: s for s in (_get("/stages").get("stages") or []) if s.get("id")}
        _meta_cache["stages"] = cached
    return cached


def _users_by_id() -> Dict[str, str]:
    cached = _meta_cache.get("users")
    if cached is None:
        cached = {}
        for u in (_get("/users").get("users") or []):
            if not u.get("id"):
                continue
            name = " ".join(p for p in (u.get("firstName"), u.get("lastName")) if p).strip()
            cached[u["id"]] = name or (u.get("email") or "")
        _meta_cache["users"] = cached
    return cached


def _list_project_ids(cap: int):
    """Page GET /v1/projects/ids (most-recent bid deadline first) up to `cap`.
    Returns (ids, total). Falls back to unsorted if the sort param is rejected."""
    ids: List[str] = []
    offset, total, sort = 0, None, True
    while len(ids) < cap:
        params: Dict[str, Any] = {"limit": 50, "offset": offset}
        if sort:
            params["sort[bidDeadline]"] = "DESC"
        try:
            resp = _get("/projects/ids", params)
        except Exception:                       # noqa: BLE001 — retry once without sort
            if sort:
                ids, offset, total, sort = [], 0, None, False
                continue
            raise
        batch = resp.get("projectIds") or resp.get("ids") or []
        if not batch:
            break
        ids.extend(batch)
        offset += len(batch)
        total = (resp.get("paging") or {}).get("total", total)
        if total is not None and offset >= total:
            break
    return ids[:cap], (total if total is not None else len(ids))


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


def get_pipeline() -> Dict[str, Any]:
    """Assemble the read-only pipeline: every (non-deleted) project with its stage
    + estimator names, plus the ordered stage list for the board columns.
    Returns {"ok": True, "projects": [...], "stages": [...]} or
    {"ok": False, "error": "<generic>"} — never raises."""
    if not is_configured():
        return {"ok": False, "configured": False, "error": "Basisboard is not configured"}
    cached = _pipeline_cache.get("pipeline")
    if cached is not None:
        return cached
    try:
        stages = _stages_by_id()
        users = _users_by_id()
        cap = _max_projects()
        pids, total = _list_project_ids(cap)
        projects: List[Dict[str, Any]] = []
        for chunk in _chunks(pids, _PROJECT_ID_CHUNK):
            resp = _get("/projects", {"filter[projectIds][]": chunk})
            projects.extend(resp.get("projects") or [])
        # Pipeline view = active bids: drop deleted + archived.
        shaped = [_shape_project(p, stages, users) for p in projects
                  if not p.get("deletedAt") and not p.get("archivedAt")]
        shaped.sort(key=lambda x: (x["stage_order"], x["name"].lower()))
        stage_cols = sorted(
            ({"id": s.get("id"), "name": s.get("name"), "color": s.get("color"),
              "order": s.get("order", 9999)} for s in stages.values()),
            key=lambda s: s["order"],
        )
        result = {"ok": True, "configured": True, "projects": shaped, "stages": stage_cols,
                  "shown": len(shaped), "total": total}
        _pipeline_cache["pipeline"] = result
        return result
    except Exception as exc:  # noqa: BLE001 — read view must never 500 the page
        log.warning("Basisboard get_pipeline failed: %s", exc)
        return {"ok": False, "configured": True, "error": "Couldn't reach Basisboard"}
