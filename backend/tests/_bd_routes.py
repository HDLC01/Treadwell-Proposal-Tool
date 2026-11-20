"""BD's routes on the proposal tool's app, and who may call each one: shared by the contract and
role-matrix tests (#809, BD's tests/_routes.py moved under /api/bd/).

    import _bd_routes
    _bd_routes.registered()      # [(METHOD, path, module)] every /api/bd/ route main.app serves, in order
    _bd_routes.documented()      # [(METHOD, path)] every route heading of docs/bd/api-contract.md
    _bd_routes.winner(m, p)      # the module of the route that answers METHOD p (what Starlette picks)
    _bd_routes.ROUTE_ROLES       # (METHOD, path) -> the BD roles that get past its role check
    _bd_routes.WEBHOOK           # the one /api/bd/ route that takes no sign-in

Used by tests/test_bd_contract_routes.py (contract <-> code, both ways), tests/test_bd_contract_json.py
(the pages call only documented routes) and tests/test_bd_authz_matrix.py (who may call what).

A ROUTE HEADING in the contract reads

    #### `METHOD /api/bd/path` (who)

`who` names the BD roles the route's role check lets in ("salesperson, assistant"), or "any BD role",
or "whoever logged it" (an ownership rule), or "public" (the telephony webhook). Words after a ";"
qualify the door without closing it ("salesperson; an assistant logs notes only" lets the assistant
in). A route that answers 503 says "not built yet" in its heading.

ADDING A ROUTE: write its heading in docs/bd/api-contract.md, then ONE line below, in ROUTE_ROLES (its
roles, or ANY) or in WEBHOOK. tests/test_bd_authz_matrix.py fails until both agree, and again if the
line names roles the heading does not, so a BD route never ships without its door written down twice.

HOW A ROLE SET READS. A route "marked salesperson is also open to admin" (the contract's Roles), and a
super admin is an admin, so `_open(...)` always adds both admin roles: write only the other roles. A
set is what the role check lets through (a request well formed enough to reach the handler is never
401/403 for a role in the set). Finer rules inside a handler (your own week, your own task, your own
entry, an assistant's notes only, a manager's cadence-only edit, only a super admin changes an admin)
are tested in test_bd_authz_matrix.py and the route's own test file.
"""
from __future__ import annotations

import pathlib
import re

from starlette.routing import Match

ROOT = pathlib.Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs" / "bd" / "api-contract.md"
PREFIX = "/api/bd/"
CATCH_ALL = "/api/bd/{rest:path}"
METHODS = ("GET", "POST", "PATCH", "PUT", "DELETE")
ROUTE_HEADING = re.compile(r"^#### `(GET|POST|PATCH|PUT|DELETE) (/api/bd/[^`\s]*)` \(([^()]+)\)$")
NOT_BUILT = "not built yet"

ROLES = ("salesperson", "assistant", "manager", "admin", "super_admin")
ADMINS = ("admin", "super_admin")
ALL_ROLES = frozenset(ROLES)


def _open(*roles) -> frozenset:
    """These roles and both admin roles (an admin passes every role check)."""
    bad = [r for r in roles if r not in ROLES]
    if bad:
        raise ValueError("unknown role %r" % (bad,))
    return frozenset(roles) | frozenset(ADMINS)


ANY = ALL_ROLES
ADMIN_ONLY = _open()

# ── the one door that takes no sign-in ───────────────────────────────────────────────────────────
WEBHOOK = frozenset({("POST", "/api/bd/webhooks/telephony/quo")})     # the provider's signature, once built

# ── every route that takes a sign-in and a BD login: who may call it ─────────────────────────────
ROUTE_ROLES = {
    # Meta
    ("GET", "/api/bd/me"): ANY,
    ("GET", "/api/bd/settings"): ANY,
    ("GET", "/api/bd/users"): ANY,
    # This Week
    ("GET", "/api/bd/week"): _open("salesperson", "manager"),
    ("POST", "/api/bd/week/ten-more"): _open("salesperson"),
    ("POST", "/api/bd/tasks/{id}/done"): _open("salesperson"),
    ("POST", "/api/bd/tasks/{id}/snooze"): _open("salesperson"),
    ("POST", "/api/bd/tasks/{id}/reopen"): _open("salesperson"),
    ("POST", "/api/bd/tasks/{id}/not-right-person"): _open("salesperson", "assistant"),
    ("POST", "/api/bd/admin/weekly/run"): ADMIN_ONLY,
    # Interactions
    ("GET", "/api/bd/contacts/{id}/interactions"): ANY,
    ("POST", "/api/bd/contacts/{id}/interactions"): _open("salesperson", "assistant"),   # assistant: notes only
    ("PATCH", "/api/bd/interactions/{id}"): ANY,                                       # whoever logged it, admin
    ("DELETE", "/api/bd/interactions/{id}"): ADMIN_ONLY,
    # Contacts
    ("GET", "/api/bd/contacts"): ANY,
    ("GET", "/api/bd/contacts/duplicates"): ANY,
    ("POST", "/api/bd/contacts"): _open("salesperson", "assistant"),
    ("GET", "/api/bd/contacts/{id}"): ANY,
    ("PATCH", "/api/bd/contacts/{id}"): _open("salesperson", "assistant", "manager"),    # manager: cadence only
    ("POST", "/api/bd/contacts/{id}/confirm"): _open("salesperson", "assistant"),
    ("POST", "/api/bd/contacts/{id}/archive"): _open("salesperson", "assistant"),
    ("POST", "/api/bd/contacts/{id}/merge"): _open("assistant"),                         # not built yet
    # BD accounts: the Contacts page's tabs, search and company moves (#810)
    ("GET", "/api/bd/contacts/accounts"): ANY,
    ("GET", "/api/bd/contacts/search"): ANY,
    ("POST", "/api/bd/contacts/accounts/{id}/move"): _open("salesperson", "manager"),
    ("POST", "/api/bd/contacts/accounts/moves/{id}/undo"): _open("salesperson", "manager"),  # your own move only
    # Likely duplicate BD accounts: the list, Merge, Undo, Keep separate (#811)
    ("GET", "/api/bd/contacts/accounts/duplicates"): _open("assistant"),
    ("POST", "/api/bd/contacts/accounts/{id}/merge"): _open("assistant"),
    ("POST", "/api/bd/contacts/accounts/merges/{id}/undo"): _open("assistant"),
    ("POST", "/api/bd/contacts/accounts/duplicates/keep"): _open("assistant"),
    # Companies
    ("GET", "/api/bd/companies"): ANY,
    ("GET", "/api/bd/companies/{id}"): ANY,
    ("POST", "/api/bd/companies"): _open("salesperson", "assistant"),
    ("PATCH", "/api/bd/companies/{id}"): _open("salesperson", "assistant"),
    # Admin
    ("GET", "/api/bd/admin/users"): ADMIN_ONLY,
    ("POST", "/api/bd/admin/users"): ADMIN_ONLY,                                          # a super admin adds an admin
    ("PATCH", "/api/bd/admin/users/{id}"): ADMIN_ONLY,                                    # a super admin changes an admin
    ("PUT", "/api/bd/admin/settings"): ADMIN_ONLY,
    ("GET", "/api/bd/admin/telephony"): ADMIN_ONLY,
    ("GET", "/api/bd/admin/unmatched-calls"): _open("assistant"),
    ("POST", "/api/bd/admin/unmatched-calls/{id}/attach"): _open("assistant"),
    ("POST", "/api/bd/admin/unmatched-calls/{id}/dismiss"): _open("assistant"),
    ("POST", "/api/bd/admin/import"): _open("salesperson", "assistant"),
    ("GET", "/api/bd/admin/imports"): _open("salesperson", "assistant"),
    # AI next action and missed-call follow-up (not built yet)
    ("POST", "/api/bd/interactions/{id}/recommend"): _open("salesperson"),
    ("POST", "/api/bd/recommendations/{id}/confirm"): _open("salesperson"),
    ("POST", "/api/bd/recommendations/{id}/dismiss"): _open("salesperson"),
    ("POST", "/api/bd/interactions/{id}/draft-followup"): _open("salesperson"),
    ("POST", "/api/bd/interactions/{id}/send-followup"): _open("salesperson"),
    # Potential BD Contacts (not built yet)
    ("GET", "/api/bd/review/candidates"): _open("salesperson", "assistant", "manager"),
    ("POST", "/api/bd/review/candidates/{id}/add"): _open("salesperson", "assistant"),
    ("POST", "/api/bd/review/candidates/{id}/ignore"): _open("salesperson", "assistant"),
    # Analytics (not built yet)
    ("GET", "/api/bd/analytics"): _open("manager"),
    ("GET", "/api/bd/analytics/export.csv"): _open("manager"),
}

# Routes whose heading names a person, not a role ("whoever logged it"): every role can be that
# person, so the door is ownership, tested in test_bd_authz_matrix.py (the entry's author).
OWNERSHIP_GATED = frozenset({("PATCH", "/api/bd/interactions/{id}")})


# ── the contract's route list ────────────────────────────────────────────────────────────────────
def contract_lines():
    return CONTRACT.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")


def headings():
    """[(METHOD, path, who, line)] for every route heading, in the contract's order."""
    out = []
    for no, ln in enumerate(contract_lines(), 1):
        m = ROUTE_HEADING.match(ln)
        if m:
            out.append((m.group(1), m.group(2), m.group(3).strip(), no))
    return out


def documented():
    """[(METHOD, path)] in the contract's order."""
    return [(m, p) for m, p, _who, _no in headings()]


def documented_who():
    """{(METHOD, path): the words inside the heading's brackets}."""
    return {(m, p): who for m, p, who, _no in headings()}


def documented_not_built():
    """{(METHOD, path)} whose heading says the route is not built yet (it answers 503)."""
    return {(m, p) for m, p, who, _no in headings() if NOT_BUILT in who.lower()}


_ROLE_WORD = re.compile(r"\b(salesperson|assistant|manager|admin)\b")


def heading_roles(who: str):
    """What a heading says about the door: ("roles", frozenset) | ("public",) | ("person",).
    Admin implies super admin. Every role word counts, after the ";" too: "a manager the cadence
    only" still means the manager gets past the role check."""
    text = who.strip().lower()
    if text.startswith("public"):
        return ("public",)
    if text.startswith("any bd role"):
        return ("roles", ANY)
    if text.startswith("whoever logged it"):
        return ("person",)
    words = set(_ROLE_WORD.findall(text))
    if not words:
        raise ValueError("no role words in the contract heading %r" % who)
    return ("roles", _open(*sorted(words - {"admin"})))


# ── the real app's routes ────────────────────────────────────────────────────────────────────────
def _walk(routes):
    for r in routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:            # a FastAPI that keeps an included router as one entry
            yield from _walk(inner.routes)
            continue
        yield r


def registered():
    """[(METHOD, path, module)] for every /api/bd/ route main.app serves, in the order it tries them."""
    import main

    out = []
    for r in _walk(main.app.router.routes):
        path = getattr(r, "path", None)
        if not path or not path.startswith(PREFIX):
            continue
        for m in sorted(getattr(r, "methods", None) or ()):
            if m in ("HEAD", "OPTIONS"):
                continue
            out.append((m, path, getattr(r.endpoint, "__module__", "")))
    return out


def bd_modules_outside_the_prefix():
    """[(path, module)] of any route a bd.* module serves somewhere other than /api/bd/."""
    import main

    out = []
    for r in _walk(main.app.router.routes):
        module = getattr(getattr(r, "endpoint", None), "__module__", "") or ""
        path = getattr(r, "path", "") or ""
        if module.startswith("bd.") and not path.startswith(PREFIX):
            out.append((path, module))
    return out


def real_routes():
    """{(METHOD, path)} the app serves under /api/bd/, without BD's catch-all."""
    return {(m, p) for m, p, _mod in registered() if p != CATCH_ALL}


def concrete(path):
    return re.sub(r"\{[^}]+\}", "1", path)


def winner(method, path):
    """The module of the route that answers METHOD path (the first full match, as Starlette does)."""
    import main

    scope = {"type": "http", "method": method, "path": concrete(path), "root_path": ""}
    for r in _walk(main.app.router.routes):
        match, _ = r.matches(scope)
        if match == Match.FULL:
            return getattr(getattr(r, "endpoint", None), "__module__", "") or "mount"
    return None


def classify(method, path):
    """"roles" | "webhook" | None for a route (None = not written down; "roles+webhook" = twice)."""
    key = (method, path)
    found = [name for name, table in (("roles", ROUTE_ROLES), ("webhook", WEBHOOK)) if key in table]
    return found[0] if len(found) == 1 else (None if not found else "+".join(found))


def unclassified(keys):
    """The routes among `keys` with no line in ROUTE_ROLES or WEBHOOK, sorted."""
    return sorted(k for k in keys if classify(*k) is None)
