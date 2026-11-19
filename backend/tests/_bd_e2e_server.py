"""The live app for the BD browser suites (#806, Q28). Not a test file: tests/_bd_browser.py starts it.

    python tests/_bd_e2e_server.py <port> <tool-roles.json>

It runs the proposal tool's real app (main.app, BD switched on) under uvicorn on 127.0.0.1:<port>,
against a BD test database the browser fixture made, migrated and filled with the fixture seed.

SIGN-IN IS FAKED HERE AND NOWHERE ELSE. This process replaces the tool's verify step
(supabase_client.verify_identity, and the claims reader /api/me uses) with the test stand-in from
tests/_bd_conftest.py, which accepts "Bearer test:<email>". The browser half (the Supabase script)
is intercepted inside the test's own Playwright context (tests/_bd_browser.py). No environment
variable, file or flag turns either on: the override is code that runs only when this file is run,
and tests/test_bd_fake_sign_in.py proves the app itself refuses the test token whatever the
environment this file gives it.

IT REFUSES TO START (exit 2, before main is imported) unless:
  * BD_DATABASE_URL names a database the tests made (bd_test_*) on this machine. Staging's and
    prod's databases are neither, so this file cannot serve real BD data even if it were run there;
  * the address it binds is 127.0.0.1.
BD's pool adds its own lock: with pytest imported (as it is here) it opens only a bd_test_* database.

WHAT ELSE IS CUT OFF. backend/.env is never loaded (dotenv's loader is replaced before main is
imported), the environment comes from tests/_bd_browser.py's short list, and every module's data
store client raises: a tool route that needs the store fails here exactly as it would on a box
without one. The caller's tool profile comes from the roles file ({email: role}, default "user").
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1]
TESTS = BACKEND / "tests"
HOST = "127.0.0.1"


def refusal(database_url: str, host: str = HOST) -> str:
    """Why this server must not start ("" when it may). Never quotes the URL."""
    sys.path[:0] = [p for p in (str(BACKEND),) if p not in sys.path]
    from bd import db as dbmod

    if host != HOST:
        return "it binds 127.0.0.1 only"
    if not database_url:
        return "BD_DATABASE_URL is not set"
    if not dbmod.is_local_url(database_url):
        return "BD_DATABASE_URL does not point at this machine"
    if not dbmod.is_test_database(database_url):
        return "BD_DATABASE_URL does not name a test database (bd_test_*)"
    return ""


def fake_claims(authorization):
    """The claims reader's stand-in (/api/me): the identity of the test token, with no subject id,
    so /api/me reads the profile by email (the roles file) and never creates one."""
    from _bd_conftest import fake_verify_identity

    identity = fake_verify_identity(authorization)
    return {"email": identity["email"], "user_metadata": {}}


def _no_store(*_args, **_kw):
    raise RuntimeError("the BD browser suites' server has no data store")


def install_fakes(tool_roles: dict) -> object:
    """Load the app with the test sign-in and no data store. Returns main.app."""
    import dotenv

    dotenv.load_dotenv = lambda *a, **k: False          # backend/.env is never read here

    import supabase_client
    from _bd_conftest import fake_verify_identity

    supabase_client.verify_identity = fake_verify_identity
    supabase_client.verify_token_claims = fake_claims
    supabase_client.verify_token = lambda authorization: fake_verify_identity(authorization)["email"]

    import main
    import profiles

    real_get_client = supabase_client.get_client
    for mod in list(sys.modules.values()):
        f = getattr(mod, "__file__", None) or ""
        if f and pathlib.Path(f).resolve().is_relative_to(BACKEND) \
                and getattr(mod, "get_client", None) is real_get_client:
            mod.get_client = _no_store
    supabase_client.get_client = _no_store

    def get_by_email(email):
        email = str(email or "").strip().lower()
        return {"id": "p-" + email, "email": email, "full_name": None,
                "role": tool_roles.get(email, "user"), "status": "active"}

    profiles.get_by_email = get_by_email
    main._profile_cache_clear()
    return main.app


def main_(argv) -> int:
    if len(argv) != 3:
        print("usage: python tests/_bd_e2e_server.py <port> <tool-roles.json>", file=sys.stderr)
        return 2
    why = refusal(os.environ.get("BD_DATABASE_URL", ""))
    if why:
        print("refused: " + why, file=sys.stderr)
        return 2
    port = int(argv[1])
    roles = json.loads(pathlib.Path(argv[2]).read_text(encoding="utf-8") or "{}")
    sys.path[:0] = [str(BACKEND), str(TESTS)]
    os.chdir(BACKEND)
    app = install_fakes({str(k).lower(): str(v) for k, v in roles.items()})

    import uvicorn

    uvicorn.run(app, host=HOST, port=port, log_level="warning", access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main_(sys.argv))
