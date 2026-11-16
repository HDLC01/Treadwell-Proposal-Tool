"""The "Connect Raken" control on the Project Analytics page (frontend/js/raken-connect.js, #781).

Run under node with a small fake document, fetch and auth standing in for the browser, the same way
the page's other scripts are tested. What it must get right: a member who is not an admin sees
nothing and nothing is asked of the server; an admin sees the status line and the button; a sign-in
coming back from Raken leaves the address at once and is handed to the server; only Raken's own
Allow page is ever followed.

Made-up numbers and codes only; this repo is public. Skipped when node isn't installed.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
SCRIPT = FRONTEND / "js" / "raken-connect.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

HARNESS = r"""
const R = require(%s);
function el(tag) {
  const e = { tag, children: [], style: {}, className: "", textContent: "", disabled: false,
              listeners: {}, type: "" };
  e.appendChild = (c) => { e.children.push(c); return c; };
  e.addEventListener = (n, f) => { e.listeners[n] = f; };
  return e;
}
function world(opts) {
  const top = el("div");
  const body = el("body");
  body.firstChild = null;
  body.insertBefore = (c) => { body.children.unshift(c); return c; };
  const calls = [];
  const went = [];
  const replaced = [];
  const responses = opts.responses || {};
  const env = {
    auth: { ready: Promise.resolve(), user: () => opts.user },
    document: { createElement: el, querySelector: (s) => (s === ".top" && !opts.noTop ? top : null), body },
    location: { search: opts.search || "", pathname: "/project-calendar.html", hash: "" },
    history: { replaceState: (a, b, url) => replaced.push(url) },
    fetch: async (url, o) => {
      calls.push({ url, method: (o && o.method) || "GET", headers: (o && o.headers) || {},
                   body: o && o.body ? JSON.parse(o.body) : null });
      const path = url.replace(/\?.*$/, "");
      const key = ((o && o.method) || "GET") + " " + path;
      const r = responses[key] || { status: 200, body: {} };
      return { ok: r.status >= 200 && r.status < 300, status: r.status, json: async () => r.body };
    },
    base: () => "",
    authHeaders: () => ({ Authorization: "Bearer made-up" }),
    go: (u) => went.push(u),
  };
  return { env, top, body, calls, went, replaced };
}
const out = (v) => console.log(JSON.stringify(v));
"""

CONNECTED = {"ok": True, "state": "connected", "configured": True, "projects": 5, "with_number": 3,
             "examples": ["26.901", "G26.902"],
             "message": "Connected: 5 Raken projects, 3 with Raken's Project Number filled in"}


def run(script: str):
    proc = subprocess.run(["node", "-e", (HARNESS % json.dumps(str(SCRIPT))) + script],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _texts(box_var="box"):
    return "%s ? %s.children.map((c) => c.textContent) : null" % (box_var, box_var)


def test_a_member_who_is_not_an_admin_sees_nothing_and_nothing_is_asked():
    got = run("""
(async () => {
  const w = world({ user: { role: "user" }, search: "?raken_code=c&raken_state=s" });
  const box = await R.boot(w.env);
  out({ box, calls: w.calls.length, top: w.top.children.length, body: w.body.children.length });
})();
""")
    assert got == {"box": None, "calls": 0, "top": 0, "body": 0}


def test_signed_out_or_unknown_shows_nothing():
    got = run("""
(async () => {
  const w = world({ user: null });
  out({ box: await R.boot(w.env), calls: w.calls.length });
})();
""")
    assert got == {"box": None, "calls": 0}


@pytest.mark.parametrize("role", ["admin", "super_admin"])
def test_an_admin_sees_the_status_and_the_button(role):
    got = run("""
(async () => {
  const w = world({ user: { role: %s }, responses: { "GET /api/raken/status": { status: 200, body: %s } } });
  const box = await R.boot(w.env);
  out({ in_top: w.top.children[0] === box, texts: %s, calls: w.calls });
})();
""" % (json.dumps(role), json.dumps(CONNECTED), _texts()))
    assert got["in_top"] is True
    assert got["texts"] == [
        "Connected: 5 Raken projects, 3 with Raken's Project Number filled in (for example 26.901, G26.902)",
        "Connect Raken"]
    assert [(c["method"], c["url"]) for c in got["calls"]] == [("GET", "/api/raken/status")]
    assert got["calls"][0]["headers"]["Authorization"] == "Bearer made-up"


def test_the_tone_is_a_class_from_the_pages_stylesheet_never_a_style_set_in_script():
    got = run("""
(async () => {
  const results = [];
  for (const [status, body] of [[200, %s], [200, { state: "expired", message: "x" }],
                                [200, { state: "not_connected", message: "y" }]]) {
    const w = world({ user: { role: "admin" }, responses: { "GET /api/raken/status": { status, body } } });
    const box = await R.boot(w.env);
    results.push({ box: box.className, line: box.children[0].className,
                   styles: [box, ...box.children].map((e) => Object.keys(e.style).length) });
  }
  out(results);
})();
""" % json.dumps(CONNECTED))
    assert [r["line"] for r in got] == ["raken-status raken-ok", "raken-status raken-warn",
                                        "raken-status raken-muted"]
    assert all(r["box"] == "raken-connect" for r in got)
    assert all(r["styles"] == [0, 0, 0] for r in got)
    html = (FRONTEND / "project-calendar.html").read_text(encoding="utf-8")
    for cls in (".raken-connect", ".raken-status", ".raken-ok", ".raken-warn", ".raken-muted"):
        assert cls in html, cls


def test_without_a_header_it_makes_its_own_row():
    got = run("""
(async () => {
  const w = world({ user: { role: "admin" }, noTop: true });
  const box = await R.boot(w.env);
  out({ row: w.body.children.length === 1 && w.body.children[0].children[0] === box });
})();
""")
    assert got == {"row": True}


def test_a_sign_in_back_from_raken_leaves_the_address_then_is_handed_to_the_server():
    got = run("""
(async () => {
  const w = world({ user: { role: "admin" },
                    search: "?tab=schedule&raken_code=made-up-code&raken_state=made-up-state",
                    responses: { "GET /api/raken/status": { status: 200, body: %s } } });
  const box = await R.boot(w.env);
  out({ replaced: w.replaced, calls: w.calls.map((c) => [c.method, c.url, c.body]), texts: %s });
})();
""" % (json.dumps(CONNECTED), _texts()))
    assert got["replaced"] == ["/project-calendar.html?tab=schedule"]
    assert got["calls"] == [
        ["POST", "/api/raken/callback", {"code": "made-up-code", "state": "made-up-state"}],
        ["GET", "/api/raken/status", None]]
    assert got["texts"][0].startswith("Connected: 5 Raken projects")


def test_a_refused_sign_in_shows_the_servers_plain_reason():
    got = run("""
(async () => {
  const w = world({ user: { role: "admin" }, search: "?raken_code=c&raken_state=s",
    responses: { "POST /api/raken/callback": { status: 400,
      body: { detail: "That Raken sign-in did not start here, or took too long. Press Connect Raken again." } } } });
  const box = await R.boot(w.env);
  out({ texts: %s, calls: w.calls.length });
})();
""" % _texts())
    assert got["texts"][0] == ("That Raken sign-in did not start here, or took too long. "
                               "Press Connect Raken again.")
    assert got["calls"] == 1


def test_a_cancelled_sign_in_sends_nothing():
    got = run("""
(async () => {
  const w = world({ user: { role: "admin" }, search: "?raken_error=access_denied&raken_state=s" });
  const box = await R.boot(w.env);
  out({ texts: %s, calls: w.calls.length, replaced: w.replaced });
})();
""" % _texts())
    assert got["calls"] == 0
    assert got["replaced"] == ["/project-calendar.html"]
    assert "cancelled" in got["texts"][0]


def test_connect_follows_only_rakens_own_allow_page():
    got = run("""
(async () => {
  const good = "https://app.rakenapp.com/oauth/authorize?response_type=code&state=x";
  const results = [];
  for (const url of [good, "https://evil.example/oauth/authorize", "javascript:alert(1)",
                     "http://app.rakenapp.com/oauth/authorize"]) {
    const w = world({ user: { role: "admin" },
                      responses: { "GET /api/raken/connect": { status: 200, body: { ok: true, url } } } });
    const box = await R.boot(w.env);
    await box.children[1].listeners.click();
    results.push({ went: w.went, asked: w.calls.map((c) => c.method + " " + c.url) });
  }
  out(results);
})();
""")
    assert got[0]["went"] == ["https://app.rakenapp.com/oauth/authorize?response_type=code&state=x"]
    assert got[0]["asked"] == ["GET /api/raken/status", "GET /api/raken/connect"]
    assert [r["went"] for r in got[1:]] == [[], [], []]


def test_status_lines_in_plain_words():
    got = run("""
out([
  R.statusLine({ state: "expired", message: "Raken sign-in has expired. An admin must Connect Raken again." }),
  R.statusLine({ state: "not_connected", message: "Raken is not connected." }),
  R.statusLine({ state: "connected", message: "Connected.", error: "Raken is limiting requests right now. Try again later." }),
  R.statusLine(null),
]);
""")
    assert got[0] == {"text": "Raken sign-in has expired. An admin must Connect Raken again.", "tone": "warn"}
    assert got[1] == {"text": "Raken is not connected.", "tone": "muted"}
    assert got[2]["text"] == "Raken is connected. Raken is limiting requests right now. Try again later."
    assert got[3]["tone"] == "warn"


NOT_PROVISIONED_LINE = ("Raken has not turned on its Public API for Treadwell's account yet. "
                        "Raken has to enable it; nothing needs to change here.")


def test_an_account_without_the_public_api_shows_that_one_line_as_a_warning():
    got = run("""
(async () => {
  const w = world({ user: { role: "admin" }, responses: { "GET /api/raken/status": { status: 200,
    body: { ok: true, configured: true, state: "not_provisioned", message: %s } } } });
  const box = await R.boot(w.env);
  out({ texts: %s, line: box.children[0].className });
})();
""" % (json.dumps(NOT_PROVISIONED_LINE), _texts()))
    assert got["texts"][0] == NOT_PROVISIONED_LINE
    assert got["line"] == "raken-status raken-warn"
    assert "could not be reached" not in got["texts"][0]


def test_the_page_loads_it_last_and_it_writes_no_style_attribute():
    html = (FRONTEND / "project-calendar.html").read_text(encoding="utf-8")
    assert html.index('src="/js/project-calendar.js"') < html.index('src="/js/raken-connect.js"')
    js = SCRIPT.read_text(encoding="utf-8")
    assert 'style="' not in js and "style='" not in js
    assert "innerHTML" not in js, "server values are shown with textContent only"
