"""BD's API routers. bd/api.py includes every module listed in ROUTER_MODULES, in this order, then
`pending`, then BD's catch-all 404 LAST, so a real route always wins over its "not built yet"
placeholder and over the 404.

Each module exposes `router = web.make_router()` (BD's route class: the envelope and no-store) and
declares FULL paths ("/api/bd/contacts/{id}"): no prefix, so a route reads exactly as
docs/bd/api-contract.md writes it with /api/bd in front. A new module is added here (and only here);
nobody needs to touch bd/api.py or main.py. A new ROUTE gets its heading in docs/bd/api-contract.md
and its line in tests/_bd_routes.py (who may call it): tests/test_bd_authz_matrix.py fails until both
are written.

Conventions every router follows (see bd/auth.py, bd/errors.py, bd/serialize.py, bd/db.py):
  * routes are plain `def`, never `async def` (bd/db.py says why).
  * who:     `user = Depends(current_user)` (any BD role) or `Depends(require_role("salesperson", ...))`;
             admins pass every require_role.
  * errors:  raise errors.not_found / bad_request(message, fields) / forbidden / conflict; never
             return an {"ok": false} dict by hand.
  * data:    `with db.connect() as conn:` (one transaction), plain SQL with parameters only.
  * output:  serialize.* for every object; lists are {"ok": true, "items": [...], "total": N}.
  * time:    bizdate.today_central() / now_central(); in SQL bd_today() / bd_now().
"""
ROUTER_MODULES = ("meta", "week", "interactions", "contacts", "companies", "admin", "imports")
