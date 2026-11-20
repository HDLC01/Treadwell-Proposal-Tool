"""Every BD route not built yet, answering 503 after its access check.

    { "ok": false, "error": "unavailable", "message": "This part is not built yet (Phase 5)." }

The caller's access is checked FIRST, exactly as the finished route will check it: no sign-in is
401 (the proposal tool's gate), no BD login or the wrong BD role is 403, and only then the 503. So
every BD page already meets the real door in front of each unbuilt room, and no page meets a
missing route (#806).

THE TELEPHONY WEBHOOK is public at ONE exact path, WEBHOOK_PATH (main._AUTH_PUBLIC_PATHS lists it):
the provider proves itself with its signature once it is built. Nothing else under
/api/bd/webhooks/ is public. BD's service-token route (bd-candidates) is NOT carried over, nor any
service token or service-token check.

PENDING_ROUTES maps (method, path) -> the phase of BD's old build plan that builds it (an int, or
"later"), and who may call it. Tests read it.

BUILDING ONE OF THESE: implement it in its own router (a module listed in bd/routers/__init__.py).
bd/api.py includes this module after them, so the real route wins at once; then delete its line
here and "not built yet" from its heading in docs/bd/api-contract.md. tests/test_bd_app_shell.py
checks every entry that is still served from here, and tests/test_bd_contract_routes.py that the
contract says "not built yet" for exactly these routes.
"""
from __future__ import annotations

from fastapi import Depends

from .. import web
from ..auth import require_role
from ..errors import ApiError

router = web.make_router()

SALES = ("salesperson",)
PUBLIC = "public"     # no sign-in (the provider's signature is checked when it is built)

WEBHOOK_PATH = "/api/bd/webhooks/telephony/quo"

# (method, path, phase, who may call it)
PENDING_ROUTES = (
    ("POST", WEBHOOK_PATH, 4, PUBLIC),
    ("POST", "/api/bd/interactions/{id}/recommend", 5, SALES),
    ("POST", "/api/bd/recommendations/{id}/confirm", 5, SALES),
    ("POST", "/api/bd/recommendations/{id}/dismiss", 5, SALES),
    ("POST", "/api/bd/interactions/{id}/draft-followup", 5, SALES),
    ("POST", "/api/bd/interactions/{id}/send-followup", 5, SALES),
    ("GET", "/api/bd/review/candidates", 6, ("salesperson", "assistant", "manager")),
    ("POST", "/api/bd/review/candidates/{id}/add", 6, ("salesperson", "assistant")),
    ("POST", "/api/bd/review/candidates/{id}/ignore", 6, ("salesperson", "assistant")),
    ("GET", "/api/bd/analytics", 7, ("manager",)),
    ("GET", "/api/bd/analytics/export.csv", 7, ("manager",)),
    ("POST", "/api/bd/contacts/{id}/merge", "later", ("assistant",)),
)

PENDING = {(m, p): phase for m, p, phase, _who in PENDING_ROUTES}
ACCESS = {(m, p): who for m, p, _phase, who in PENDING_ROUTES}


def message_for(phase) -> str:
    if isinstance(phase, int):
        return "This part is not built yet (Phase %d)." % phase
    return "This part is not built yet (a later phase)."


def _endpoint(method: str, path: str, phase):
    text = message_for(phase)

    def not_built_yet():
        raise ApiError(503, text, code="unavailable")

    not_built_yet.__name__ = "pending_%s_%s" % (method.lower(), path.strip("/").replace("/", "_")
                                                .replace("{", "").replace("}", "").replace(".", "_")
                                                .replace("-", "_"))
    return not_built_yet


def _dependencies(who):
    if who == PUBLIC:
        return []
    return [Depends(require_role(*who))]


for _method, _path, _phase, _who in PENDING_ROUTES:
    router.add_api_route(_path, _endpoint(_method, _path, _phase), methods=[_method],
                         dependencies=_dependencies(_who), include_in_schema=False,
                         responses={503: {"description": "Not built yet"}})
