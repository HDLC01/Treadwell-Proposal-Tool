"""The BD router: every BD route, on the proposal tool's app, under /api/bd/ (#806).

    main.py:  app.include_router(bd.api.router)      # once, after the tool's own routes

What it holds, in order:
  1. the BD switch, as the router's FIRST dependency (web.require_enabled): BD_ENABLED off ->
     every /api/bd/ path answers 503 "not turned on" before anything touches the database;
  2. the routers listed in bd/routers/__init__.py (ROUTER_MODULES);
  3. bd/routers/pending.py (the routes not built yet, 503 after their access check);
  4. LAST, BD's catch-all: any other /api/bd/ path is BD's 404 envelope, or the 400
     "<METHOD> is not allowed on <path>." when a BD route serves that path with another method.
     It covers /api/bd/* only; every other /api path is the proposal tool's.

Every route is a web.BDRoute, so BD's envelope and Cache-Control: no-store come from the router
itself and nothing is registered on the app. Sign-in is the tool's gate (main._auth_gate); each BD
route then checks the BD role (bd/auth.py), which also checks the migrations ledger and answers
503 "database not up to date" when the database is behind the code.
"""
from __future__ import annotations

import importlib

from fastapi import Depends, Request
from fastapi.routing import APIRoute
from starlette.routing import Match

from . import errors, web
from .routers import ROUTER_MODULES

PREFIX = "/api/bd"

router = web.make_router(dependencies=[Depends(web.require_enabled)])

_MODULES = [importlib.import_module("bd.routers." + name) for name in ROUTER_MODULES]
_MODULES.append(importlib.import_module("bd.routers.pending"))
for _module in _MODULES:
    router.include_router(_module.router)


def bd_routes() -> list:
    """Every BD route but the catch-all, in the order they match."""
    return [r for m in _MODULES for r in m.router.routes if isinstance(r, APIRoute)]


@router.api_route(PREFIX + "/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                  include_in_schema=False)
def bd_not_found(rest: str, request: Request):
    """Any /api/bd/ path no BD route answers: the envelope. A path a BD route serves with another
    method is 400 "<METHOD> is not allowed on <path>.", never a 404 or a 405."""
    for route in bd_routes():
        if route.matches(request.scope)[0] == Match.PARTIAL:
            raise errors.bad_request("%s is not allowed on %s." % (errors.reflect(request.method),
                                                                   errors.reflect(request.url.path.rstrip("/"))))
    raise errors.not_found("There is no such API route.")
