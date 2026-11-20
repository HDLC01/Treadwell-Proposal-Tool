"""Real-browser helpers for the BD browser suites (tests/test_bd_e2e_*.py; #806, Q28).

BD's _browser.py, rewritten for the proposal tool: the pages are no longer served from disk on mock
data. They run against the LIVE APP, a real uvicorn serving main.app with BD switched on, on a BD
test database migrated by the runner and filled with the fixture seed (backend/bd/ops/fixture_seed.py).

THE RULE, same as tests/_node.py: a missing Playwright or Chromium FAILS the test when GitHub Actions
runs it (the browser job in ci.yml installs both) and SKIPS it anywhere else. BD_TEST_DATABASE_URL
follows tests/_bd_db.py: unset, SKIP locally and FAIL on CI.

SIGN-IN IS FAKED ONLY INSIDE THE TEST PROCESS, in two halves:
  * the server: live_app() starts tests/_bd_e2e_server.py, which overrides the tool's verify step in
    that process only (it accepts "Bearer test:<email>");
  * the browser: every request to another host is aborted, the Supabase script included, and an
    init script on the test's own browser context stands in for it (FAKE_SUPABASE_JS). The pinned
    script tag carries an integrity hash, so a fulfilled stand-in would be refused by the browser;
    aborting it and defining window.supabase first leaves every page byte as served.
  Nothing in the app reads a setting for either (tests/test_bd_fake_sign_in.py).

Who is signed in is one localStorage key on the test's origin (SIGNED_IN_KEY), set by Page(email=...)
before the first page loads, or by sign_in() during a test. The fixture seed's people sign in by
their example.com emails; the server allows example.com (AUTH_ALLOWED_DOMAIN), since its verify step
is the stand-in anyway.
"""
from __future__ import annotations

import contextlib
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import pytest

from _node import running_in_ci

TESTS = pathlib.Path(__file__).resolve().parent
BACKEND = TESTS.parent
SERVER = TESTS / "_bd_e2e_server.py"

DESKTOP = {"width": 1280, "height": 800}
PHONE = {"width": 390, "height": 844}
TABLET = {"width": 820, "height": 1180}

SIGNED_IN_KEY = "tw_e2e_signed_in_as"
TOKEN_PREFIX = "test:"
DOMAIN = "example.com"

# The stand-in for supabase-js, as the test's browser context sees it. Only what auth.js uses.
FAKE_SUPABASE_JS = r"""
(function () {
  var KEY = %s, PREFIX = %s;
  function session() {
    var email = null;
    try { email = localStorage.getItem(KEY); } catch (e) {}
    if (!email) return null;
    return { access_token: PREFIX + email, token_type: "bearer",
             user: { email: email, user_metadata: {} } };
  }
  var auth = {
    onAuthStateChange: function (cb) {
      setTimeout(function () { cb(session() ? "SIGNED_IN" : "SIGNED_OUT", session()); }, 0);
      return { data: { subscription: { unsubscribe: function () {} } } };
    },
    getSession: function () { return Promise.resolve({ data: { session: session() }, error: null }); },
    signOut: function () {
      try { localStorage.removeItem(KEY); } catch (e) {}
      return Promise.resolve({ error: null });
    },
    signInWithOAuth: function () { return Promise.resolve({ data: {}, error: null }); }
  };
  window.supabase = { createClient: function () { return { auth: auth }; } };
})();
""" % (json.dumps(SIGNED_IN_KEY), json.dumps(TOKEN_PREFIX))


def require_playwright():
    """sync_playwright, or the end of the test: FAIL under CI, SKIP anywhere else."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        if running_in_ci():
            pytest.fail("playwright is not installed, and CI must have it (requirements-dev.txt).",
                        pytrace=False)
        pytest.skip("playwright is not installed")
    return sync_playwright


@contextlib.contextmanager
def browser():
    sync_playwright = require_playwright()
    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # the library is there but its Chromium is not
            if running_in_ci():
                pytest.fail("Chromium for playwright is missing on CI: %s" % e, pytrace=False)
            pytest.skip("Chromium for playwright is not installed (python -m playwright install chromium)")
        try:
            yield b
        finally:
            b.close()


# ── the live app ───────────────────────────────────────────────────────────────────────────────
# The environment the server starts with: these names and nothing else from the developer's shell
# (a few the OS and Python need to start at all, and PYTHONPATH for a local dependency folder).
_PASS_THROUGH = ("PATH", "SYSTEMROOT", "SystemRoot", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE",
                 "LOCALAPPDATA", "APPDATA", "PYTHONPATH", "LANG", "LC_ALL")


def server_env(database_url: str, data_dir: str) -> dict:
    """What tests/_bd_e2e_server.py is given. Every outside service is off or unreachable."""
    env = {k: os.environ[k] for k in _PASS_THROUGH if k in os.environ}
    env.update({
        "BD_ENABLED": "on",
        "BD_DATABASE_URL": database_url,
        "BD_TODAY": _fixture_today(),
        "AUTH_ALLOWED_DOMAIN": DOMAIN,
        # /api/public-config must answer something for auth.js to start; nothing ever calls it.
        "SUPABASE_URL": "https://supabase.invalid",
        "SUPABASE_ANON_KEY": "e2e-not-a-key",
        "DRAFTS_DB_PATH": str(pathlib.Path(data_dir) / "drafts.db"),
        "DIGEST_ENABLED": "off",
        "PVA_REFRESH_ENABLED": "off",
        "LEADS_AUTOPILOT": "off",
        "PYTHONUNBUFFERED": "1",
    })
    return env


def _fixture_today() -> str:
    sys.path[:0] = [p for p in (str(BACKEND),) if p not in sys.path]
    from bd.ops import fixture_seed

    return fixture_seed.FIXTURE_TODAY


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _seed(url: str) -> None:
    import _bd_db
    from bd import db as dbmod
    from bd.ops import fixture_seed

    conn = dbmod.direct(_bd_db.app_login_url(url), autocommit=True)
    try:
        dbmod.prepare_session(conn)
        fixture_seed.seed(conn)
    finally:
        conn.close()


def reseed(url: str) -> None:
    """Put the live app's database back to the fixture seed (every BD table emptied, ids restarted,
    then seeded), as the app's own login. A suite whose tests change data calls it before each test,
    so every test starts from the same made-up week (#807)."""
    import _bd_db
    from bd import db as dbmod
    from bd.ops import fixture_seed

    conn = dbmod.direct(_bd_db.app_login_url(url), autocommit=True)
    try:
        fixture_seed.reset_data(conn)
        dbmod.prepare_session(conn)
        fixture_seed.seed(conn)
    finally:
        conn.close()


def run_sql(url: str, statement: str, params=None) -> list:
    """One statement on the live app's database, as the app's own login (a test's own arrangement,
    such as clearing a week so the admin's manual run has one to build). Returns the rows, if any."""
    import _bd_db
    from bd import db as dbmod

    conn = dbmod.direct(_bd_db.app_login_url(url), autocommit=True)
    try:
        dbmod.prepare_session(conn)
        cur = conn.execute(statement, params or ())
        return cur.fetchall() if cur.description else []
    finally:
        conn.close()


def _wait_until_up(proc, base: str, log_path: pathlib.Path, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break
        try:
            with urllib.request.urlopen(base + "/healthz", timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:  # noqa: BLE001 - not listening yet
            time.sleep(0.25)
    tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:] if log_path.exists() else ""
    pytest.fail("the BD browser suites' server did not start (exit %r):\n%s" % (proc.poll(), tail),
                pytrace=False)


@contextlib.contextmanager
def _scratch_dir():
    """A temporary folder for the server's data and log. Windows can hold a dead process's files for
    a moment after it exits, so removing it is retried briefly rather than left behind."""
    tmp = tempfile.mkdtemp(prefix="bd-e2e-")
    try:
        yield tmp
    finally:
        for _ in range(20):
            shutil.rmtree(tmp, ignore_errors=True)
            if not os.path.exists(tmp):
                break
            time.sleep(0.25)


@contextlib.contextmanager
def live_app(tool_roles: dict | None = None):
    """The live app on a fresh, seeded BD test database. Yields its base URL."""
    with live_app_db(tool_roles) as (base, _url):
        yield base


@contextlib.contextmanager
def live_app_db(tool_roles: dict | None = None):
    """live_app, yielding (base URL, the BD test database's admin URL) for reseed() and run_sql()."""
    import _bd_db

    admin = _bd_db.admin_url()
    _bd_db.ensure_app_login(admin)
    with _bd_db.new_database(admin) as url, _scratch_dir() as tmp:
        with _bd_db.cluster_lock(admin, exclusive=False):
            _bd_db.migrate(url)
        _seed(url)
        roles = pathlib.Path(tmp) / "tool-roles.json"
        roles.write_text(json.dumps({str(k).lower(): v for k, v in (tool_roles or {}).items()}),
                         encoding="utf-8")
        port = _free_port()
        log_path = pathlib.Path(tmp) / "server.log"
        with open(log_path, "w", encoding="utf-8") as log:
            proc = subprocess.Popen([sys.executable, str(SERVER), str(port), str(roles)],
                                    cwd=str(BACKEND), env=server_env(_bd_db.app_login_url(url), tmp),
                                    stdout=log, stderr=subprocess.STDOUT)
            try:
                base = "http://127.0.0.1:%d" % port
                _wait_until_up(proc, base, log_path)
                yield base, url
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=15)


# ── one page ───────────────────────────────────────────────────────────────────────────────────
class Page:
    """One fresh browser context (so storage never leaks between tests), signed in as `email` (or
    signed out), with page errors, console errors and failed same-origin requests collected."""

    def __init__(self, b, base, viewport=DESKTOP, email=None, storage=None):
        self.base = base
        state = {"cookies": [], "origins": []}
        items = [{"name": k, "value": v} for k, v in (storage or {}).items()]
        if email:
            items.append({"name": SIGNED_IN_KEY, "value": email})
        if items:
            state["origins"].append({"origin": base, "localStorage": items})
        self.ctx = b.new_context(viewport=viewport, storage_state=state)
        self.ctx.add_init_script(FAKE_SUPABASE_JS)
        self.page = self.ctx.new_page()
        self.errors = []      # page errors and console errors: always a failure
        self.http = []        # same-origin answers of 400 and up, as (status, path)
        self.blocked = []     # outside requests, aborted

        def on_console(m):
            # Chromium logs "Failed to load resource" for every aborted outside request (recorded in
            # self.blocked) and for every same-origin 4xx/5xx (recorded in self.http).
            if m.type == "error" and not m.text.startswith("Failed to load resource"):
                self.errors.append("console: " + m.text)
        self.page.on("console", on_console)
        self.page.on("pageerror", lambda e: self.errors.append("pageerror: %s" % e))

        def route(r):
            if r.request.url.startswith(base):
                r.continue_()
            else:
                self.blocked.append(r.request.url)
                r.abort()
        self.page.route("**/*", route)
        self.page.on("response", lambda resp: resp.url.startswith(base) and resp.status >= 400
                     and self.http.append((resp.status, resp.url[len(base):])))
        self.page.on("requestfailed", lambda req: req.url.startswith(base)
                     and self.errors.append("failed %s" % req.url[len(base):]))

    def sign_in(self, email):
        """Sign in for the next page load (the page must be on the app's origin)."""
        self.page.evaluate("([k, v]) => localStorage.setItem(k, v)", [SIGNED_IN_KEY, email])

    def open(self, path):
        self.page.goto(self.base + path)
        return self.page

    def open_signed_in(self, path):
        """Open an app page and wait until the tool's shell has drawn the sidebar."""
        self.open(path)
        self.page.wait_for_selector("#tw-sidebar", state="attached", timeout=15000)
        return self.page

    def bd_errors(self):
        """Same-origin answers of 400 and up from BD (its pages and /api/bd/)."""
        return [(s, p) for s, p in self.http if p.startswith("/bd/") or p.startswith("/api/bd/")]

    def close(self):
        self.ctx.close()


# ── what every BD browser suite reads off a page (#808: one copy for test_bd_e2e_week and
# test_bd_e2e_contact, and MOVED_PAGES for test_bd_assets' static scan too) ────────────────────────
# The BD pages that have moved into the tool so far (#807: This Week; #808: one contact and Add
# contact; #809: Admin, Potential BD Contacts and Analytics). Being served is not enough: /bd/contacts.html is there only as the page an assistant is
# sent to until Contacts moves, so a link to it, with or without ?company=, is a link to a page that
# has not moved. A page ticket adds its page here, and nowhere else.
MOVED_PAGES = frozenset({"/bd/", "/bd/index.html", "/bd/contact.html", "/bd/add.html", "/bd/admin.html",
                         "/bd/review.html", "/bd/analytics.html"})

# What each BD section's page shows once it has loaded, for a per-role check that clicks every section
# the sidebar offers (test_bd_e2e_contact, test_bd_e2e_mgmt). A page ticket adds its page here too.
SECTION_LANDED = {"/bd/": "#summary .wk-progress-in, [data-pick]", "/bd/add.html": "#add-form",
                  "/bd/review.html": "#rv-body .error-box", "/bd/analytics.html": "#an-body .error-box",
                  "/bd/admin.html": ".ad-sec:not([hidden])"}

# What a Phase 5 placeholder route's 503 says, wherever a page shows it.
NOT_BUILT = "This part is not built yet (Phase 5)."


def bd_links(pg) -> list:
    """Every page address under /bd/ the rendered page links to (the query and hash cut off), the
    tool's sidebar and any open menu included."""
    return pg.evaluate("() => [...new Set([...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href'))"
                       ".filter(h => h.startsWith('/bd/')).map(h => h.split(/[?#]/)[0]))]")


def api(pg, path):
    """GET a BD route through the page's own BDApi (signed in as the page is)."""
    return pg.evaluate("p => BDApi.get(p)", path)


def toasts(pg):
    return pg.locator("#bd-toasts")


def menu_acts(pg) -> list:
    """The data-act of each item in the open menu, in order."""
    pg.locator(".menu").wait_for()
    return pg.locator(".menu .menu-item").evaluate_all("els => els.map(e => e.dataset.act)")


def sideways(pg) -> int:
    """How many pixels the page scrolls sideways (1 or less is none)."""
    return pg.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")


def focus_is_on_the_page(pg) -> bool:
    """Focus is on something inside the page's own <main id="main">, not on <body> or a removed node."""
    return pg.evaluate("() => { const a = document.activeElement;"
                       " return !!a && a !== document.body && document.contains(a) && !!a.closest('#main'); }")
