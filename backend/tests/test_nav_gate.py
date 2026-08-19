"""The server half of per-role sidebar permissions: the middleware, /api/me, and the admin routes.

The store and its capability table are tested in test_nav_access.py. This file is about what
actually happens to a request, and there are four claims worth stating up front:

  * WITH NO POLICY FILE EVERY ROUTE ANSWERS EXACTLY AS IT DID. Hanz has not chosen which tabs to
    restrict, so this ships as a no-op and the first section proves it through the real middleware
    rather than through the store.
  * ONE MIDDLEWARE, NOT DECORATORS. api_history, api_list_trash and api_followup_settings take no
    `request` parameter at all — decorators would have meant editing every signature, and a route
    added later under an owned prefix would be ungated until somebody remembered.
  * FAIL OPEN, both halves. An unreadable policy AND an unresolvable role mean everybody gets
    everything. Three accounts use this tool; a lockout is an outage the affected person cannot fix,
    and the data is still behind the _require_admin gates it was always behind.
  * THE ROLE COMES FROM THE PROFILE. The browser sends a bearer token and nothing else about itself.

The static .html is deliberately NOT gated — see test_the_static_page_still_serves_and_that_is_the
_design at the bottom for why, before filing it as a hole.
"""
import json

import pytest
from fastapi.testclient import TestClient

import main
import nav_access


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """A policy file per test, and no profile cached across tests."""
    monkeypatch.setattr(nav_access, "_FILE", tmp_path / "nav_access.json")
    monkeypatch.setattr(nav_access, "_DATA_DIR", tmp_path)
    main._profile_cache_clear()
    yield
    main._profile_cache_clear()


def _as(monkeypatch, role, email="staffer@wetreadwell.com"):
    """A client signed in as `role`, resolved the way the app resolves it — through the profile."""
    monkeypatch.setattr(main, "_user_email", lambda request: email)
    monkeypatch.setattr(main.profiles, "get_by_email",
                        lambda e: {"id": "u1", "email": email, "role": role, "status": "active"})
    main._profile_cache_clear()
    return TestClient(main.app)


def _refused(call):
    """Did OUR nav gate refuse this, as opposed to whatever the handler would have said anyway?

    Takes a CALLABLE rather than a response because several of these handlers raise when the data
    store is unconfigured, which is how this suite runs by default (see conftest's prod-write guard).
    An exception coming out of the handler is proof the gate let the request THROUGH, which is
    exactly the claim being made — so it reads as "not refused" rather than masking a failure.
    """
    try:
        response = call()
    except Exception:  # noqa: BLE001 — the handler ran; the gate is what is under test
        return False
    if response.status_code != 403:
        return False
    try:
        return bool(response.json().get("nav_denied"))
    except ValueError:
        return False


# ── the no-op promise ─────────────────────────────────────────────────────────
def test_with_no_policy_file_every_gateable_route_answers_as_it_did(monkeypatch):
    """A member calling every route any tab could ever own, with nothing denied anywhere."""
    assert not nav_access._FILE.exists()
    client = _as(monkeypatch, "user")
    checked = 0
    for tab in nav_access.TABS.values():
        for prefix in tab["api"]:
            for path in ({prefix.rstrip("/"), prefix + "probe"} if prefix.endswith("/")
                         else {prefix, prefix + "/probe"}):
                assert not _refused(lambda: client.get(path)), path
                assert not _refused(lambda: client.post(path, json={})), path
                checked += 1
    assert checked >= 16, "only %d paths exercised — the capability table has emptied" % checked


def test_with_no_policy_file_api_me_reports_nothing_denied(monkeypatch):
    for role in nav_access.ROLES:
        assert _as(monkeypatch, role).get("/api/me").json()["nav_denied"] == []


# ── the middleware ────────────────────────────────────────────────────────────
def test_an_owned_prefix_403s_a_denied_role(monkeypatch):
    nav_access.save({"user": ["/history.html"]}, "k@x.com")
    r = _as(monkeypatch, "user").get("/api/history")
    assert r.status_code == 403
    body = r.json()
    assert body["ok"] is False and body["nav_denied"] is True
    assert "Admin page" in body["error"], "the refusal does not say who can turn it back on"


def test_the_same_prefix_passes_an_admin_who_is_not_denied(monkeypatch):
    nav_access.save({"user": ["/history.html"]}, "k@x.com")
    assert not _refused(lambda: _as(monkeypatch, "admin").get("/api/history"))


def test_a_route_that_takes_no_request_parameter_is_still_gated(monkeypatch):
    """Why this is middleware. api_history, api_list_trash and api_followup_settings have no
    `request` in their signatures, so a decorator would have had to change each one."""
    import inspect
    for fn in (main.api_history, main.api_list_trash, main.api_followup_settings):
        assert "request" not in inspect.signature(fn).parameters, (
            "%s grew a request parameter; the middleware is still right but this note is stale"
            % fn.__name__)
    nav_access.save({"user": ["/history.html", "/trash.html", "/followup-settings.html"]}, "k@x.com")
    client = _as(monkeypatch, "user")
    for path in ("/api/history", "/api/trash", "/api/followup-settings"):
        assert _refused(lambda: client.get(path)), path


def test_the_gate_reads_the_role_from_the_profile_not_from_the_caller(monkeypatch):
    """A request that claims to be an admin in a header or a query string is still a member."""
    nav_access.save({"user": ["/history.html"]}, "k@x.com")
    client = _as(monkeypatch, "user")
    for kwargs in ({"headers": {"X-Role": "admin", "X-TW-Role": "super_admin"}},
                   {"params": {"role": "admin", "as": "super_admin"}}):
        assert _refused(lambda: client.get("/api/history", **kwargs)), kwargs


def test_a_shared_prefix_is_never_gated_even_with_every_tab_denied(monkeypatch):
    """The bell polls /api/notifications from every page and it is what boots the lead autopilot;
    /api/drafts and /api/draft/* are the wizard's; bare /api/analytics feeds the Bid Calendar."""
    nav_access.save({"user": list(nav_access.TABS)}, "k@x.com")
    client = _as(monkeypatch, "user")
    for path in ("/api/notifications", "/api/analytics", "/api/library/items",
                 "/api/library/assemblies", "/api/estimators", "/api/drafts",
                 "/api/portal/notify-recipients", "/api/portal/notify-overrides-all"):
        assert not _refused(lambda: client.get(path)), path


def test_a_child_is_gated_and_the_bare_route_is_not(monkeypatch):
    """/api/analytics/ is children only. The bare route is also the Bid Calendar's data source, so
    gating it would blank a page nobody restricted."""
    nav_access.save({"user": ["/analytics.html"]}, "k@x.com")
    client = _as(monkeypatch, "user")
    assert _refused(lambda: client.post("/api/analytics/export", json={}))
    assert _refused(lambda: client.put("/api/analytics/pull-window", json={"from": None}))
    assert not _refused(lambda: client.get("/api/analytics"))


def test_denying_the_lead_inbox_covers_the_bare_route_and_its_children(monkeypatch):
    nav_access.save({"user": ["/leads.html"]}, "k@x.com")
    client = _as(monkeypatch, "user")
    assert _refused(lambda: client.get("/api/leads"))
    assert _refused(lambda: client.get("/api/leads/m1/body"))
    assert _refused(lambda: client.post("/api/leads/m1/create-estimate", json={}))


def test_every_method_on_an_owned_prefix_is_refused(monkeypatch):
    """A gate on GET only would leave the writes open, which is the half that matters on the Auto
    Followups tab: its PUT rewrites four customer emails with no history."""
    nav_access.save({"user": ["/followup-settings.html"]}, "k@x.com")
    client = _as(monkeypatch, "user")
    assert _refused(lambda: client.get("/api/followup-settings"))
    assert _refused(lambda: client.put("/api/followup-settings", json={"a": 1}))
    assert _refused(lambda: client.post("/api/followup-settings/preview", json={}))


def test_the_gate_fails_open_when_the_policy_cannot_be_read(monkeypatch):
    """A bad byte on the volume must not become an outage: the data is still behind the gates it was
    always behind."""
    nav_access.save({"user": ["/history.html"]}, "k@x.com")
    client = _as(monkeypatch, "user")
    assert _refused(lambda: client.get("/api/history")), "the policy was not in force to begin with"
    monkeypatch.setattr(nav_access, "is_api_denied",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("volume gone")))
    assert not _refused(lambda: client.get("/api/history"))


def test_the_gate_fails_open_when_the_ROLE_cannot_be_resolved(monkeypatch):
    """The other half: PostgREST down means nobody's role is known, so everybody gets everything."""
    nav_access.save({"user": ["/history.html"]}, "k@x.com")
    monkeypatch.setattr(main, "_user_email", lambda request: "staffer@wetreadwell.com")
    monkeypatch.setattr(main.profiles, "get_by_email",
                        lambda e: (_ for _ in ()).throw(RuntimeError("PostgREST unreachable")))
    main._profile_cache_clear()
    assert not _refused(lambda: TestClient(main.app).get("/api/history"))


def test_a_role_the_policy_does_not_mention_keeps_everything(monkeypatch):
    """A profile row carrying something profiles.py cannot store must not be read as "deny all"."""
    nav_access.save({"user": ["/history.html"]}, "k@x.com")
    assert not _refused(lambda: _as(monkeypatch, "estimator").get("/api/history"))


def test_a_public_route_is_never_nav_gated(monkeypatch):
    """/healthz and /api/public-config carry no identity at all — the gate runs inside the auth gate,
    so there is no role to read and nothing to decide."""
    nav_access.save({"user": list(nav_access.TABS)}, "k@x.com")
    client = _as(monkeypatch, "user")
    assert client.get("/healthz").status_code == 200
    assert client.get("/api/public-config").status_code == 200


def test_the_gate_runs_inside_the_auth_gate(monkeypatch, real_verify_token):
    """Order matters: this one reads the ROLE, which needs the identity _auth_gate establishes. An
    unauthenticated call must still be the auth gate's 401, not a nav 403 built on role "user"."""
    nav_access.save({"user": ["/history.html"]}, "k@x.com")
    monkeypatch.setattr(main.supabase_client, "verify_token", real_verify_token)
    r = TestClient(main.app).get("/api/history")          # no Authorization header
    assert r.status_code == 401, r.text


def test_the_static_page_still_serves_and_that_is_the_design(monkeypatch):
    """There is NO cookie in this codebase — the Supabase session is in localStorage and the only
    credential is the Authorization header — so a browser NAVIGATING to a page carries no identity to
    judge. Every .html is an inert shell with no server-side templating whose content arrives over
    /api/*, so serving it is harmless: a denied member gets a page that paints a refusal card and
    whose data calls 403. Session cookies were the alternative and were rejected — they need an
    interstitial plus a token refresh on every navigation, which turns a 30-second Supabase blip into
    everybody bounced to sign-in."""
    nav_access.save({"user": ["/history.html"]}, "k@x.com")
    r = _as(monkeypatch, "user").get("/history.html")
    assert r.status_code == 200


# ── /api/me ───────────────────────────────────────────────────────────────────
def test_api_me_carries_the_callers_denied_paths(monkeypatch):
    nav_access.save({"user": ["/leads.html", "/trash.html"], "admin": ["/history.html"]}, "k@x.com")
    body = _as(monkeypatch, "user").get("/api/me").json()
    assert body["role"] == "user" and body["nav_denied"] == ["/leads.html", "/trash.html"]
    assert _as(monkeypatch, "admin").get("/api/me").json()["nav_denied"] == ["/history.html"]
    assert _as(monkeypatch, "super_admin").get("/api/me").json()["nav_denied"] == [], (
        "the super admin cannot be denied anything")


def test_api_me_still_answers_when_the_policy_read_throws(monkeypatch):
    """The sidebar is drawn from this response. A policy blip must cost a menu item, never a page."""
    monkeypatch.setattr(nav_access, "denied_paths",
                        lambda role, policy=None: (_ for _ in ()).throw(RuntimeError("boom")))
    body = _as(monkeypatch, "user").get("/api/me").json()
    assert body["ok"] is True and body["nav_denied"] == []


def test_api_me_carries_the_list_on_the_no_profile_fallback_too(monkeypatch):
    """The bootstrap path — a signed-in account whose profile row does not exist yet. It reads as a
    member, and a member's menu has to be filtered like anybody else's."""
    nav_access.save({"user": ["/leads.html"]}, "k@x.com")
    monkeypatch.setattr(main, "_user_email", lambda request: "brand.new@wetreadwell.com")
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: None)
    monkeypatch.setattr(main.supabase_client, "verify_token_claims",
                        lambda auth: {"email": "brand.new@wetreadwell.com"})
    main._profile_cache_clear()
    body = TestClient(main.app).get("/api/me").json()
    assert body["role"] == "user" and body["nav_denied"] == ["/leads.html"]


# ── the admin endpoints ───────────────────────────────────────────────────────
def test_reading_the_policy_needs_admin(monkeypatch):
    assert _as(monkeypatch, "user").get("/api/admin/nav-access").status_code == 403
    r = _as(monkeypatch, "admin").get("/api/admin/nav-access")
    assert r.status_code == 200
    body = r.json()
    assert body["deny"] == {}
    assert body["roles"] == list(nav_access.ROLES)
    assert body["locked_pages"] == list(nav_access.LOCKED)
    assert body["locked_roles"] == list(nav_access.LOCKED_ROLES)
    assert {row["href"] for row in body["tabs"]} == set(nav_access.TABS)


def test_the_capability_table_tells_the_page_which_tabs_only_hide(monkeypatch):
    """The Admin page has to say on screen that switching those five off leaves their data reachable,
    and it needs `api` per tab to know which they are rather than a hardcoded list."""
    tabs = {t["href"]: t for t in
            _as(monkeypatch, "admin").get("/api/admin/nav-access").json()["tabs"]}
    assert tabs["/notifications.html"]["api"] == []
    assert tabs["/history.html"]["api"] == ["/api/history"]
    assert tabs["/polish-intake.html"]["pages"] == ["/polish-intake.html", "/polish-estimate.html"]


def test_writing_the_policy_needs_admin(monkeypatch):
    r = _as(monkeypatch, "user").put("/api/admin/nav-access",
                                     json={"deny": {"user": ["/leads.html"]}})
    assert r.status_code == 403
    assert nav_access.denied_paths("user") == [], "a member edited the policy"


def test_an_admin_saves_and_it_takes_effect_on_the_next_request(monkeypatch):
    client = _as(monkeypatch, "admin")
    r = client.put("/api/admin/nav-access", json={"deny": {"user": ["/history.html"]}})
    assert r.status_code == 200, r.text
    assert r.json()["deny"] == {"user": ["/history.html"]}
    assert nav_access.denied_paths("user") == ["/history.html"]
    # And the gate is now refusing, with no restart in between.
    assert _refused(lambda: _as(monkeypatch, "user").get("/api/history"))


def test_the_save_stamps_the_signed_in_user_and_the_body_cannot_say_otherwise(monkeypatch):
    client = _as(monkeypatch, "admin", email="kyle@wetreadwell.com")
    assert client.put("/api/admin/nav-access",
                      json={"deny": {"user": ["/leads.html"]}}).status_code == 200
    assert nav_access.get()["updated_by"] == "kyle@wetreadwell.com"
    # `extra="forbid"` is what makes the stamp unspoofable rather than merely un-read.
    assert client.put("/api/admin/nav-access",
                      json={"deny": {}, "by": "somebody.else@wetreadwell.com"}).status_code == 422


def test_a_caller_cannot_deny_their_own_role(monkeypatch):
    """Every self-lockout starts with somebody testing the toggle on themselves, and there may be
    nobody else awake to undo it."""
    client = _as(monkeypatch, "admin")
    r = client.put("/api/admin/nav-access", json={"deny": {"admin": ["/leads.html"]}})
    assert r.status_code == 400, r.text
    assert "own role" in r.json()["detail"]
    assert nav_access.denied_paths("admin") == [], "the refusal saved anyway"
    # And the members half of the same request does not sneak through on the way past.
    r = client.put("/api/admin/nav-access",
                   json={"deny": {"admin": ["/leads.html"], "user": ["/trash.html"]}})
    assert r.status_code == 400
    assert nav_access.get()["deny"] == {}


def test_a_caller_may_lift_a_denial_on_their_own_role(monkeypatch):
    """Widening is always safe, so the rule is one-directional rather than "hands off your role"."""
    nav_access.save({"admin": ["/leads.html"]}, "hanz@wetreadwell.com")
    r = _as(monkeypatch, "admin").put("/api/admin/nav-access", json={"deny": {"admin": []}})
    assert r.status_code == 200, r.text
    assert nav_access.denied_paths("admin") == []


def test_an_admin_may_still_restrict_members(monkeypatch):
    """The self-role rule must not quietly become "an admin can change nothing"."""
    assert _as(monkeypatch, "admin").put(
        "/api/admin/nav-access", json={"deny": {"user": ["/leads.html"]}}).status_code == 200


def test_a_super_admin_may_restrict_admins(monkeypatch):
    """His own role is unrestrictable, so this is not a self-lockout — and it is the only way a
    denial on `admin` can be set at all."""
    r = _as(monkeypatch, "super_admin").put("/api/admin/nav-access",
                                            json={"deny": {"admin": ["/leads.html"]}})
    assert r.status_code == 200, r.text
    assert nav_access.denied_paths("admin") == ["/leads.html"]


def test_a_locked_page_in_the_request_is_refused_rather_than_quietly_dropped(monkeypatch):
    """save() strips it either way, but a switch that appears to have worked and did not is the worst
    of the three outcomes."""
    client = _as(monkeypatch, "admin")
    r = client.put("/api/admin/nav-access", json={"deny": {"user": ["/admin.html"]}})
    assert r.status_code == 400 and "/admin.html" in r.json()["detail"]
    r = client.put("/api/admin/nav-access", json={"deny": {"user": ["/portal.html"]}})
    assert r.status_code == 400 and "/portal.html" in r.json()["detail"]
    r = client.put("/api/admin/nav-access", json={"deny": {"super_admin": ["/leads.html"]}})
    assert r.status_code == 400 and "super_admin" in r.json()["detail"]


def test_a_failed_save_is_a_500_and_changes_nothing(monkeypatch):
    nav_access.save({"user": ["/leads.html"]}, "k@x.com")
    monkeypatch.setattr(nav_access, "save",
                        lambda *a, **k: (_ for _ in ()).throw(
                            nav_access.NavAccessWriteError("read-only volume")))
    r = _as(monkeypatch, "admin").put("/api/admin/nav-access", json={"deny": {}})
    assert r.status_code == 500


def test_a_typo_in_a_key_is_a_422_not_a_silent_no_op(monkeypatch):
    """Without `extra="forbid"`, {"denies": …} would save an empty policy and report success while
    lifting every restriction that was in force."""
    nav_access.save({"user": ["/leads.html"]}, "k@x.com")
    r = _as(monkeypatch, "admin").put("/api/admin/nav-access",
                                      json={"denies": {"user": ["/trash.html"]}})
    assert r.status_code == 422
    assert nav_access.denied_paths("user") == ["/leads.html"]


def test_saving_an_empty_deny_map_is_the_way_back(monkeypatch):
    nav_access.save({"user": ["/leads.html"]}, "k@x.com")
    r = _as(monkeypatch, "admin").put("/api/admin/nav-access", json={"deny": {}})
    assert r.status_code == 200
    assert not _refused(lambda: _as(monkeypatch, "user").get("/api/leads"))


# ── the profile cache ─────────────────────────────────────────────────────────
def test_the_role_is_read_once_and_cached(monkeypatch):
    """The gate needs the role on every /api/* request, which would otherwise be a PostgREST round
    trip per request instead of per admin route."""
    calls = []
    monkeypatch.setattr(main, "_user_email", lambda request: "staffer@wetreadwell.com")

    def counted(email):
        calls.append(email)
        return {"id": "u1", "email": email, "role": "user", "status": "active"}

    monkeypatch.setattr(main.profiles, "get_by_email", counted)
    main._profile_cache_clear()
    client = TestClient(main.app)
    for _ in range(4):
        client.get("/api/notifications")
    assert len(calls) == 1, "the profile was resolved %d times for four requests" % len(calls)
    main._profile_cache_clear()
    client.get("/api/notifications")
    assert len(calls) == 2, "clearing the cache did not force a re-read"


def test_a_miss_is_not_cached(monkeypatch):
    """/api/me creates the profile row moments after a first-ever sign-in. A cached miss would 403 a
    brand-new admin for the length of the TTL, which looks exactly like a broken account."""
    calls = []
    monkeypatch.setattr(main, "_user_email", lambda request: "brand.new@wetreadwell.com")
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: calls.append(e) or None)
    main._profile_cache_clear()
    client = TestClient(main.app)
    client.get("/api/notifications")
    client.get("/api/notifications")
    assert len(calls) == 2, "a profile that does not exist yet was cached as absent"


def test_the_super_admin_fallback_survives_the_refactor(monkeypatch):
    """_require_admin's SUPER_ADMIN_EMAIL fallback is what gets the owner into a box where his
    profile row does not exist yet. A second role reader that forgot it would lock him out of his own
    tool, so it is asserted through the NEW reader."""
    monkeypatch.setattr(main, "_SUPER_ADMIN_EMAIL", "hanz@wetreadwell.com")
    monkeypatch.setattr(main, "_user_email", lambda request: "hanz@wetreadwell.com")
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: None)
    main._profile_cache_clear()
    client = TestClient(main.app)
    assert client.get("/api/admin/nav-access").status_code == 200
    # And it is not a blanket "no row means admin".
    monkeypatch.setattr(main, "_user_email", lambda request: "somebody@wetreadwell.com")
    main._profile_cache_clear()
    assert client.get("/api/admin/nav-access").status_code == 403


def test_a_role_change_clears_the_cache(monkeypatch):
    """Otherwise a promotion leaves somebody a member for the TTL — and a demotion leaves them an
    admin for the TTL, which is the direction that matters."""
    monkeypatch.setattr(main, "_user_email", lambda request: "boss@wetreadwell.com")
    monkeypatch.setattr(main, "_SUPER_ADMIN_EMAIL", "boss@wetreadwell.com")
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: None)
    monkeypatch.setattr(main.profiles, "set_role", lambda actor, uid, role: {"ok": True})
    monkeypatch.setattr(main.drafts, "log_event", lambda *a, **k: None)
    main._profile_cache_clear()
    client = TestClient(main.app)
    client.get("/api/admin/nav-access")
    assert main._PROFILE_CACHE, "nothing was cached to begin with"
    client.patch("/api/admin/users/u9/role", json={"role": "admin"})
    assert not main._PROFILE_CACHE, "a role change left the old roles cached"


@pytest.mark.parametrize("call", [
    ("patch", "/api/admin/users/u9/role", {"role": "user"}),
    ("put", "/api/admin/users/u9/status", {"status": "paused"}),
    ("post", "/api/admin/users/u9/ban", {"reason": ""}),
    ("post", "/api/admin/users/u9/unban", {}),
    ("delete", "/api/admin/users/u9", None),
])
def test_every_membership_write_clears_the_cache(monkeypatch, call):
    method, path, body = call
    monkeypatch.setattr(main, "_user_email", lambda request: "boss@wetreadwell.com")
    monkeypatch.setattr(main, "_SUPER_ADMIN_EMAIL", "boss@wetreadwell.com")
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: None)
    for name in ("set_role", "set_status", "ban_user", "unban_user", "delete_user"):
        monkeypatch.setattr(main.profiles, name, lambda *a, **k: {"ok": True})
    monkeypatch.setattr(main.drafts, "log_event", lambda *a, **k: None)
    main._profile_cache_clear()
    client = TestClient(main.app)
    client.get("/api/admin/nav-access")
    assert main._PROFILE_CACHE
    kwargs = {"json": body} if body is not None else {}
    getattr(client, method)(path, **kwargs)
    assert not main._PROFILE_CACHE, "%s %s left the old roles cached" % (method.upper(), path)


# ── the change is audited ─────────────────────────────────────────────────────
def test_the_change_is_logged_with_who_and_what(monkeypatch):
    """Somebody losing a tab will ask why, and "who took it away and when" has to be answerable."""
    events = []
    monkeypatch.setattr(main.drafts, "log_event",
                        lambda pid, actor, action, detail=None: events.append((actor, action, detail)))
    _as(monkeypatch, "admin", email="kyle@wetreadwell.com").put(
        "/api/admin/nav-access", json={"deny": {"user": ["/leads.html"]}})
    assert ("kyle@wetreadwell.com", "nav_access_changed",
            {"deny": {"user": ["/leads.html"]}}) in events


def test_the_stored_file_is_what_the_route_reported(monkeypatch):
    """A response that agreed while nothing reached the volume is the failure this catches."""
    r = _as(monkeypatch, "admin").put("/api/admin/nav-access",
                                      json={"deny": {"user": ["/leads.html"]}})
    on_disk = json.loads(nav_access._FILE.read_text(encoding="utf-8"))
    assert on_disk["deny"] == r.json()["deny"]
