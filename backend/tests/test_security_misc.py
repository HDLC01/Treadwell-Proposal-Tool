"""Cross-cutting security units:
  - _auth_is_public: which paths skip the auth gate (and which must NOT)
  - _autofill_bucket: rate-limit key derives from the *verified* email, so a
    spoofed X-Project-Id header can't be used to dodge the cap
  - dropbox upload errors are generic (no internal detail leaks to the client)
"""
from types import SimpleNamespace

import main
import dropbox_client


# ── auth gate path classification ──────────────────────────────────────
def test_options_is_public():
    assert main._auth_is_public("/api/price", "OPTIONS") is True


def test_non_api_paths_public():
    assert main._auth_is_public("/index.html", "GET") is True
    assert main._auth_is_public("/", "GET") is True


def test_explicit_public_endpoints():
    assert main._auth_is_public("/healthz", "GET") is True
    assert main._auth_is_public("/api/public-config", "GET") is True


def test_file_downloads_require_auth():
    # AC-02/LOG-02: /api/file/* downloads are no longer public capability URLs —
    # the Done page holds a Supabase session and sends the bearer, so a leaked
    # link alone can't fetch a file.
    assert main._auth_is_public("/api/file/abc123", "GET") is False


def test_api_endpoints_are_gated():
    assert main._auth_is_public("/api/price", "POST") is False
    assert main._auth_is_public("/api/admin/users", "GET") is False
    assert main._auth_is_public("/api/me", "GET") is False
    assert main._auth_is_public("/api/generate", "POST") is False


# ── autofill rate-limit bucket ─────────────────────────────────────────
def _req(email, project_id=None):
    headers = {"x-project-id": project_id} if project_id is not None else {}
    return SimpleNamespace(state=SimpleNamespace(user_email=email),
                           headers=SimpleNamespace(get=headers.get))


def test_bucket_keys_on_email():
    assert main._autofill_bucket(_req("kyle@wetreadwell.com")) == "kyle@wetreadwell.com"


def test_bucket_includes_project():
    assert main._autofill_bucket(_req("kyle@wetreadwell.com", "proj-7")) == "kyle@wetreadwell.com|proj-7"


def test_bucket_same_email_shares_budget_across_spoofed_projects():
    # Same authed user, two different (attacker-chosen) project ids → still keyed
    # to the same email prefix, so the cap can't be sidestepped by header spoofing.
    a = main._autofill_bucket(_req("kyle@wetreadwell.com", "p1"))
    b = main._autofill_bucket(_req("kyle@wetreadwell.com", "p2"))
    assert a.split("|")[0] == b.split("|")[0] == "kyle@wetreadwell.com"


def test_bucket_anon_when_unauthenticated():
    req = SimpleNamespace(state=SimpleNamespace(user_email=None),
                          headers=SimpleNamespace(get=lambda k, d=None: None))
    assert main._autofill_bucket(req) == "anon"


# ── dropbox error non-leakage ──────────────────────────────────────────
def test_unconfigured_returns_safe_result(monkeypatch):
    for v in ("DROPBOX_ACCESS_TOKEN", "DROPBOX_APP_KEY", "DROPBOX_APP_SECRET",
              "DROPBOX_REFRESH_TOKEN"):
        monkeypatch.delenv(v, raising=False)
    out = dropbox_client.upload_project_files(
        project_name="X", xlsx_bytes=b"", docx_bytes=b"")
    assert out["configured"] is False
    assert "download" in out["error"].lower()


def test_upload_failure_message_is_generic(monkeypatch):
    monkeypatch.setenv("DROPBOX_APP_KEY", "k")
    monkeypatch.setenv("DROPBOX_APP_SECRET", "s")
    monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "r")
    secret_detail = "AUTH_TOKEN_abc123_should_never_surface"

    def boom():
        raise RuntimeError(secret_detail)

    monkeypatch.setattr(dropbox_client, "_build_client", boom)
    out = dropbox_client.upload_project_files(
        project_name="X", xlsx_bytes=b"", docx_bytes=b"")
    assert out["configured"] is False
    assert secret_detail not in out["error"]            # no internal leak
    assert out["error"] == "Dropbox upload failed — your files are available as direct downloads."
