"""Who am I, the settings and the people list: what every BD page reads first.

    GET /api/bd/me        any BD role   {ok, user, can, today, timezone}
    GET /api/bd/settings  any BD role   {ok, settings}
    GET /api/bd/users     any BD role   the ACTIVE BD logins, compact, for owner pickers (paged)

BD's /api/me, /api/settings and /api/users, moved under /api/bd/ (#806) with the same shapes.
"""
from __future__ import annotations

from fastapi import Depends, Request

from .. import appsettings, auth, bizdate, db, errors, serialize, web
from ..paging import page_params

router = web.make_router()


@router.get("/api/bd/me")
def api_me(user: dict = Depends(auth.current_user)):
    return {
        "ok": True,
        "user": serialize.user(user),
        "today": bizdate.today_central().isoformat(),
        "timezone": bizdate.BIZ_TZ_NAME,
        "can": auth.can(user),
    }


@router.get("/api/bd/settings")
def api_settings(user: dict = Depends(auth.current_user)):
    with db.connect() as conn:
        return {"ok": True, "settings": appsettings.load(conn)}


@router.get("/api/bd/users")
def api_users(request: Request, user: dict = Depends(auth.current_user)):
    """The compact list of ACTIVE BD logins for owner pickers (any role). Paged by limit/offset like
    every list; `total` counts them all."""
    fields: dict = {}
    limit, offset = page_params(request.query_params, fields)
    if fields:
        raise errors.bad_request("Some fields need fixing.", fields)
    with db.connect() as conn:
        total = conn.execute("select count(*)::integer as n from users where active").fetchone()["n"]
        rows = conn.execute("select id, name, role from users where active order by id limit %s offset %s",
                            (limit, offset)).fetchall()
    return {"ok": True, "items": [serialize.user_compact(r) for r in rows], "total": total}
