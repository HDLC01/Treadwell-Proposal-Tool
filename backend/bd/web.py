"""What every BD route shares: the route class that applies BD's envelope, and the BD switch.

    from bd import web
    router = web.make_router()                # a BD sub-router (bd/routers/*.py)
    @router.get("/api/bd/contacts")           # FULL paths, no prefix: a route reads as the contract
    def list_contacts(...): ...               #   writes it, with /api/bd in front

BDRoute is the whole of "BD's error envelope is applied by the BD router itself" (#806): every
exception a BD route (or one of its dependencies) raises is answered by errors.handle(), and every
BD response is marked Cache-Control: no-store (it carries people's contact details). Nothing is
registered on the app, so a proposal-tool route's 404, 422 and 500 keep their own shapes.

require_enabled is the BD switch (BD_ENABLED, bd/config.py). bd/api.py puts it on the BD router as
its FIRST dependency, so with the switch off every /api/bd/ path answers 503 "not turned on" before
anything else runs: no sign-in lookup, no ledger check, no database connection.

not_turned_on_page is the same switch for the pages: main._bd_pages answers it for every address
under /bd/ while the switch is off.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute

from . import config, errors

NOT_TURNED_ON = "The BD CRM is not turned on."
NO_STORE = "no-store"

# What every address under /bd/ answers while the switch is off (main._bd_pages): BD's pages, its
# scripts and its stylesheet alike, so nothing of BD reaches a browser. Plain: no script (the CSP), no
# BD stylesheet, nothing under /bd/ linked, a way back to the proposal tool. 503 and never stored, so
# the page a browser shows the day the switch goes on is the real one.
NOT_TURNED_ON_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="color-scheme" content="only light" />
  <title>BD CRM · Treadwell</title>
  <link rel="icon" type="image/svg+xml" href="/img/treadwell-bison.svg" />
  <style>
    body { margin:0; background:#fbf9f8; color:#1b1c1c;
      font:400 14px/1.55 'Inter',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif; }
    main { max-width:520px; margin:12vh auto 0; padding:0 16px; }
    h1 { font-size:24px; font-weight:700; letter-spacing:-.01em; margin:0 0 6px; }
    p { color:#5c403f; margin:0 0 18px; }
    a { color:#9e001f; font-weight:600; }
  </style>
</head>
<body>
  <main>
    <h1>The BD CRM is not turned on</h1>
    <p>It isn't open yet. The proposal tool works as usual.</p>
    <a href="/">Back to the proposal tool</a>
  </main>
</body>
</html>
"""


class BDRoute(APIRoute):
    """An APIRoute whose failures are BD envelopes and whose responses are never cached."""

    def get_route_handler(self) -> Any:
        handler = super().get_route_handler()

        async def bd_handler(request: Request) -> Any:
            try:
                response = await handler(request)
            except Exception as exc:  # noqa: BLE001  every failure becomes the envelope
                response = errors.handle(request, exc)
            response.headers["Cache-Control"] = NO_STORE
            return response

        return bd_handler


def make_router(**kwargs: Any) -> APIRouter:
    """An APIRouter whose routes are BDRoutes. Every BD router is made here (an included router
    keeps its own route class, so a plain APIRouter would answer FastAPI's shapes)."""
    return APIRouter(route_class=BDRoute, **kwargs)


def is_enabled() -> bool:
    return bool(config.BD_ENABLED)


def require_enabled() -> None:
    """The BD switch. Off: 503 "not turned on", before any other check and any database work."""
    if not is_enabled():
        raise errors.ApiError(503, NOT_TURNED_ON, code="unavailable")


def not_turned_on_page() -> HTMLResponse:
    """The page every /bd/ address answers while the switch is off."""
    return HTMLResponse(NOT_TURNED_ON_PAGE, status_code=503, headers={"Cache-Control": NO_STORE})
