"""Sign-in returns a person to the page they asked for (#806, spec #802).

When the tool sends a signed-out person to sign in, it remembers the page they asked for in the
browser tab (sessionStorage) and returns them there after sign-in. A return address is followed only
if it is a same-origin relative path: one leading slash, not two, no backslash after the first slash,
no scheme. Anything else lands on the home page. The redirect address given to Supabase does not
change (no Supabase setting moves), so the return rides in the tab: Google lands the person on the
home page, which sends them on.

BD's old login page, /bd/login.html, sends the person to the tool's sign-in with a return to /bd/.

Executed: js/sign-in-return-harness.js runs the real auth.js init() (or the BD login page's script)
with a Supabase session or none, and records every location.replace().
"""
from __future__ import annotations

import json
import pathlib

import pytest

from _node import last_json_line, require_node, run_node

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "sign-in-return-harness.js"
HOME = "/portal.html"
KEY = "tw_return_to"


def run(tmp_path, pathname, session, stored=None, search="", script="auth", sign_in=False, name="s"):
    require_node()
    f = tmp_path / ("%s.json" % name)
    f.write_text(json.dumps({"script": script, "pathname": pathname, "search": search,
                             "session": session, "stored": stored, "signIn": sign_in}),
                 encoding="utf-8")
    proc = run_node(HARNESS, FRONTEND, f)
    assert proc.returncode == 0, "the harness failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


# ── signed out: the asked-for page is remembered ─────────────────────────────
@pytest.mark.parametrize("pathname,search,remembered", [
    ("/bd/", "", "/bd/"),
    ("/bd/contacts.html", "?q=ostrander", "/bd/contacts.html?q=ostrander"),
    ("/projects.html", "", "/projects.html"),
    ("/estimate-review.html", "?d=0b6e4f2a-1111-4222-8333-944455556666",
     "/estimate-review.html?d=0b6e4f2a-1111-4222-8333-944455556666"),
])
def test_a_signed_out_person_is_sent_to_sign_in_and_the_page_is_remembered(
        tmp_path, pathname, search, remembered):
    out = run(tmp_path, pathname, session=False, search=search)
    assert out["replaced"] == ["/login.html"]
    assert out["stored"] == remembered


# ── signed in: the home page sends them on ───────────────────────────────────
@pytest.mark.parametrize("stored", ["/bd/", "/bd/contacts.html?q=ostrander", "/projects.html"])
def test_after_sign_in_the_home_page_returns_to_the_remembered_page(tmp_path, stored):
    out = run(tmp_path, HOME, session=True, stored=stored)
    assert out["replaced"] == [stored]
    assert out["stored"] is None, "a return is used once"


# Refused: each lands on the home page, and none is followed.
REFUSED = [
    "//evil.example/bd/",            # two slashes: another host
    "/\\evil.example",               # a backslash after the first slash: browsers read it as "//"
    "/bd\\..\\x",                    # a backslash anywhere after the first slash
    "https://evil.example/",         # a scheme
    "javascript:alert(1)",           # a scheme
    "HTTPS://example.test/bd/",      # a scheme, even naming this very site
    "bd/",                           # not from the root
    "/\t/evil.example",              # a tab the URL parser strips back into "//"
    "/\n/evil.example",              # a newline, the same
    " /bd/",                         # leading space
    "",                              # nothing
    "/login.html",                   # back to sign-in: a loop
]


@pytest.mark.parametrize("stored", REFUSED)
def test_a_signed_in_person_on_sign_in_lands_home_for_a_refused_return(tmp_path, stored):
    out = run(tmp_path, "/login.html", session=True, stored=stored, name="r%d" % REFUSED.index(stored))
    assert out["replaced"] == [HOME], (stored, out["replaced"])
    assert out["stored"] is None


@pytest.mark.parametrize("stored", REFUSED)
def test_the_home_page_follows_no_refused_return(tmp_path, stored):
    out = run(tmp_path, HOME, session=True, stored=stored, name="h%d" % REFUSED.index(stored))
    assert out["replaced"] == [], (stored, out["replaced"])
    assert out["painted"] is True, "the home page carries on and draws itself"
    assert out["stored"] is None


def test_a_signed_in_person_on_sign_in_with_a_return_goes_there(tmp_path):
    out = run(tmp_path, "/login.html", session=True, stored="/bd/")
    assert out["replaced"] == ["/bd/"]


def test_a_signed_in_person_on_sign_in_with_no_return_goes_home(tmp_path):
    out = run(tmp_path, "/login.html", session=True, stored=None)
    assert out["replaced"] == [HOME]


def test_a_signed_in_person_on_any_other_page_stays_there(tmp_path):
    """The return is taken where sign-in lands (the home page, or sign-in itself), so an open tab
    elsewhere is never pulled away by a stale value."""
    out = run(tmp_path, "/projects.html", session=True, stored="/bd/")
    assert out["replaced"] == [] and out["painted"] is True


def test_the_address_given_to_supabase_does_not_change(tmp_path):
    out = run(tmp_path, "/login.html", session=False, stored="/bd/", sign_in=True)
    assert out["redirectTo"] == "https://example.test" + HOME
    assert out["stored"] == "/bd/", "the return waits in the tab while Google signs them in"


# ── BD's old login page ──────────────────────────────────────────────────────
def test_bd_s_login_page_lands_on_sign_in_and_returns_to_bd(tmp_path):
    out = run(tmp_path, "/bd/login.html", session=False, script="bd-login")
    assert out["replaced"] == ["/login.html"]
    assert out["stored"] == "/bd/"
    then = run(tmp_path, HOME, session=True, stored=out["stored"], name="then")
    assert then["replaced"] == ["/bd/"]


def test_bd_s_login_page_loads_only_its_own_script():
    html = (FRONTEND / "bd" / "login.html").read_text(encoding="utf-8")
    import re
    srcs = re.findall(r'<script[^>]*src="([^"]+)"', html)
    assert srcs == ["/bd/js/login-return.js"], srcs
    assert "<script>" not in html, "CSP: no inline script"
    assert 'href="/login.html"' in html, "a link to sign-in for a browser that runs no script"
