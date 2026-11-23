"""docs/bd/api-contract.md <-> the proposal tool's app: the same /api/bd/ routes, both ways (#809).

BD's test_contract_routes, moved under /api/bd/:

  * every route heading in the contract is registered on main.app with that method and exactly that
    path (path parameters named as the contract names them, {id}), so a route reads in the code the
    way the document writes it;
  * no /api/bd/ route is registered that the contract does not document (BD's /api/bd/{rest:path}
    catch-all, the 404 envelope, is the one exception), and no BD module serves a route anywhere but
    under /api/bd/;
  * the routes that still answer 503 "not built yet" are exactly bd/routers/pending.py's PENDING
    table, and exactly the ones whose heading says "not built yet". A route built in a real router
    wins over its placeholder, and then its PENDING line and its heading's words must go. This is
    checked twice: by which module the app picks for the path, and by really calling every documented
    route as the super admin (the webhook with no sign-in).

The route walk and the contract parser live in tests/_bd_routes.py (shared with test_bd_authz_matrix.py
and test_bd_contract_json.py).
"""
from __future__ import annotations

import pytest

from _bd_routes import (
    CATCH_ALL,
    WEBHOOK,
    bd_modules_outside_the_prefix,
    concrete,
    documented,
    documented_not_built,
    registered,
    winner,
)
from bd.routers import pending

DOCS = documented()
FRANKIE = 6               # the fixture seed's super admin (bd/ops/fixture_seed.py)


def test_the_contract_lists_routes():
    # 47 today; a parse that finds a handful means the heading pattern broke, not the document.
    assert len(DOCS) >= 45, "the route heading pattern found only %d routes" % len(DOCS)
    assert len(set(DOCS)) == len(DOCS)


@pytest.mark.parametrize("method,path", DOCS, ids=["%s %s" % d for d in DOCS])
def test_every_documented_route_is_registered_with_that_path(method, path):
    paths = {(m, p) for m, p, _mod in registered()}
    assert (method, path) in paths, (
        "%s %s is in docs/bd/api-contract.md but no BD router declares it with that exact path "
        "(path parameters must be named as the contract names them)" % (method, path))


def test_no_registered_bd_route_is_undocumented():
    docs = set(DOCS)
    extra = sorted({(m, p) for m, p, _mod in registered() if p != CATCH_ALL} - docs)
    assert not extra, "BD routes the contract does not document: %r" % extra


def test_every_bd_route_is_under_api_bd():
    assert bd_modules_outside_the_prefix() == []
    assert all(p.startswith("/api/bd/") for _m, p in DOCS)


def test_each_route_is_declared_once():
    real = [(m, p) for m, p, mod in registered() if mod != pending.__name__ and p != CATCH_ALL]
    assert len(set(real)) == len(real), "a route is declared by two real routers"
    # A real route that is still also in PENDING is shadowed dead code: delete its PENDING line.
    assert not (set(real) & set(pending.PENDING)), (
        "built, but still listed in bd/routers/pending.py PENDING_ROUTES: %r" % sorted(set(real) & set(pending.PENDING)))
    seen = {(m, p) for m, p, _mod in registered() if p != CATCH_ALL}
    assert seen == set(DOCS)


def test_the_routes_served_by_the_placeholder_are_exactly_pending():
    served = {(m, p) for m, p in DOCS if winner(m, p) == pending.__name__}
    assert served == set(pending.PENDING)


def test_the_contract_says_not_built_yet_exactly_where_pending_answers():
    assert documented_not_built() == set(pending.PENDING)


def test_every_documented_route_is_answered_by_a_bd_router():
    """Not the tool's own routes declared before BD's, not BD's catch-all, not the static mount."""
    for m, p in DOCS:
        module = winner(m, p) or ""
        assert module.startswith("bd.routers."), (m, p, module)


# ── really calling them ───────────────────────────────────────────────────────────────────────
def test_only_pending_routes_answer_503_unavailable(bd_seeded, bd_client, bd_as_user):
    frankie = bd_as_user(FRANKIE)
    unavailable = set()
    for method, path in DOCS:
        kw = {} if method in ("GET", "DELETE") else {"json": {}}
        if (method, path) in WEBHOOK:
            r = bd_client.request(method, concrete(path), **kw)
        else:
            r = frankie.request(method, concrete(path), **kw)
        if r.status_code == 503:
            body = r.json()
            assert body.get("error") == "unavailable" and "not built yet" in body["message"], (method, path, body)
            unavailable.add((method, path))
        else:
            assert r.status_code < 500, (method, path, r.status_code, r.text[:300])
            assert r.status_code not in (401, 403), (method, path, r.status_code, r.text[:300])
    assert unavailable == set(pending.PENDING)
