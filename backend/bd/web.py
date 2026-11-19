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
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.routing import APIRoute

from . import config, errors

NOT_TURNED_ON = "The BD CRM is not turned on."
NO_STORE = "no-store"


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
