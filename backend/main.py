"""
Treadwell Proposal Generator — standalone FastAPI app.

Single-purpose: take a project's intake + estimate + proposal narrative
fields, produce a filled .xlsx estimate sheet and .docx proposal, optionally
push both to a new Dropbox folder, return links.

No auth, no DB. Each request is stateless.

Run locally:
    cd proposal-tool/backend
    pip install -r requirements.txt
    uvicorn main:app --host 127.0.0.1 --port 8888 --reload

Then open http://127.0.0.1:8888 in a browser.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import quote
from pathlib import Path
from typing import Any, Dict, Optional

import cachetools

# Auto-load .env from this folder so the user doesn't have to source it
# before running uvicorn. In production (Railway), the platform sets
# the env vars directly — load_dotenv is a no-op if .env doesn't exist.
# override=True so .env values win over any empty shell env vars that
# Windows might have pre-set during PowerShell startup.
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent / ".env"
    _loaded = load_dotenv(_env_path, override=True)
    print(f"[main] load_dotenv({_env_path}) = {_loaded}")
    print(f"[main] DROPBOX_APP_KEY set: {bool(os.environ.get('DROPBOX_APP_KEY'))}")
    print(f"[main] DROPBOX_REFRESH_TOKEN set: {bool(os.environ.get('DROPBOX_REFRESH_TOKEN'))}")
except ImportError:
    pass

import docx
from docx.text.paragraph import Paragraph
from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import audit
import basisboard_client
import drafts
import dropbox_client
import estimate_writer
import notifications
import pdf_writer
import pricing
import profiles
import proposal_writer
import reference_tax
import supabase_client

_SUPER_ADMIN_EMAIL = (os.environ.get("SUPER_ADMIN_EMAIL") or "").strip().lower()


# ─── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("proposal_tool")


# ─── App + middleware ─────────────────────────────────────────────────
# Expose interactive API docs only in dev; disable in prod to avoid leaking
# the full endpoint surface + schemas to anonymous visitors.
_docs = os.environ.get("ENVIRONMENT", "production").lower() in {"development", "dev", "local"}
app = FastAPI(
    title="Treadwell Proposal Generator",
    docs_url="/docs" if _docs else None,
    redoc_url="/redoc" if _docs else None,
    openapi_url="/openapi.json" if _docs else None,
)

# gzip every response over ~500 bytes. The estimate-sheet grid JSON is the
# heavy hitter (~2.1 MB raw for the Epoxy tab); gzip takes it to ~90 KB
# (-95%), turning a ~14 s first paint into ~1-2 s. Cheap and global.
app.add_middleware(GZipMiddleware, minimum_size=500)

app.add_middleware(
    CORSMiddleware,
    # Same-origin in production (frontend served by us); permissive for dev.
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Conditional-GET helper (ETag / 304) ──────────────────────────────
def _versioned_json(request: Request, payload: Any, *, version: str) -> Response:
    """Serve `payload` as JSON with an ETag derived from `version`, honoring
    `If-None-Match` so the browser revalidates cheaply (304, no body) instead
    of re-downloading static-ish data (sheet grids, named ranges, system list).

    `Cache-Control: no-cache` = the browser MAY cache but must revalidate every
    time. Because `version` embeds the source file's mtime, a deploy that
    changes the template/recipes changes the ETag and busts the cache safely.
    """
    etag = 'W/"' + hashlib.md5(version.encode()).hexdigest()[:16] + '"'
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if etag in (request.headers.get("if-none-match") or ""):
        return Response(status_code=304, headers=headers)
    return JSONResponse(content=jsonable_encoder(payload), headers=headers)


def _template_version() -> str:
    """Cache version token for template-derived endpoints — the .xlsx mtime
    (changes on deploy when the committed template changes)."""
    return str(estimate_writer.TEMPLATE_PATH.stat().st_mtime_ns)


# ─── Auth gate (Supabase Google login, @wetreadwell.com only) ──────────
# One middleware gates EVERY /api/* route so no endpoint can be forgotten.
# Public exceptions: /healthz (monitoring), /api/public-config (frontend needs
# it to init the login client), and OPTIONS (CORS preflight). Static frontend
# pages are served freely — they hold no data and gate themselves client-side;
# the protection is this API check. NOTE: /api/file/* downloads are NO LONGER
# public — the Done page holds a Supabase session and now sends the bearer on
# downloads, so a leaked capability-token URL alone can't fetch a file.
_AUTH_PUBLIC_PATHS = {"/healthz", "/api/public-config",
                      # server-to-server (the customer portal renders the proposal
                      # PDF on demand); gated by SERVICE_TOKEN inside the handler.
                      "/api/admin/proposal-pdf"}


def _auth_is_public(path: str, method: str) -> bool:
    if method == "OPTIONS":
        return True
    if not path.startswith("/api/"):
        return True
    if path in _AUTH_PUBLIC_PATHS:
        return True
    return False


# ─── Audit middleware (who did what) ──────────────────────────────────
# Records authenticated state-changing actions + sensitive-data reads so a later
# "who deleted this / who viewed these contacts" question is answerable. Runs
# INSIDE _auth_gate (registered BEFORE it → Starlette LIFO makes auth the outer
# layer), so reading request.state.user_email AFTER call_next sees what the auth
# gate set. Entire step is try/except — it can never alter a response or throw.
_AUDIT_SENSITIVE = ("/admin", "/contacts", "/export", "/file", "/download")
_AUDIT_STATE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _audit_path(path: str) -> str:
    """Redact the capability token from /api/file/<token>[/pdf] before logging."""
    if path.startswith("/api/file/"):
        rest = path[len("/api/file/"):]
        return "/api/file/<redacted>" + ("/pdf" if rest.endswith("/pdf") else "")
    return path


def _client_ip(request: Request) -> Optional[str]:
    """Client IP, honoring the first hop of X-Forwarded-For (nginx sits in front)."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


async def _audit_log(request: Request, call_next):
    response = await call_next(request)
    try:
        method = request.method
        path = request.url.path
        if method != "OPTIONS" and path != "/healthz" and (
            method in _AUDIT_STATE_METHODS
            or any(s in path for s in _AUDIT_SENSITIVE)
        ):
            audit.audit_log({
                "ts": datetime.now(timezone.utc).isoformat(),
                "evt": "audit",
                "user": getattr(request.state, "user_email", None) or "anon",
                "method": method,
                "path": _audit_path(path),
                "status": response.status_code,
                "ip": _client_ip(request),
            })
    except Exception:  # noqa: BLE001 — audit must never break the request
        pass
    return response


@app.middleware("http")
async def _auth_gate(request: Request, call_next):
    if _auth_is_public(request.url.path, request.method):
        return await call_next(request)
    try:
        request.state.user_email = supabase_client.verify_token(
            request.headers.get("authorization")
        )
    except supabase_client.AuthError as exc:
        return JSONResponse(status_code=exc.status, content={"ok": False, "error": exc.detail})
    return await call_next(request)


# Register the audit middleware LAST so it is the OUTERMOST layer: it wraps
# _auth_gate and therefore records even unauthenticated / 401 attempts too
# (consistent with the News Feed + Roadmap audit). It still reads
# request.state.user_email (set by _auth_gate) after call_next returns.
app.middleware("http")(_audit_log)


def _user_email(request: Request) -> Optional[str]:
    return getattr(request.state, "user_email", None)


@app.get("/api/public-config")
def api_public_config() -> Dict[str, Any]:
    """Publishable config the static frontend needs to init Supabase Auth.
    The anon key is safe to expose; the service-role key never leaves the server."""
    return {
        "supabase_url": supabase_client.supabase_url(),
        "supabase_anon_key": supabase_client.anon_key(),
        "allowed_domain": supabase_client.ALLOWED_DOMAIN,
    }


# ─── Schemas ──────────────────────────────────────────────────────────
class DetectWorkTypeIn(BaseModel):
    """Inputs for work-type auto-detection (Screen 1 → Screen 2 hop)."""

    system_1_sf: float = 0
    system_2_sf: float = 0
    polish_sf:   float = 0


class DetectWorkTypeOut(BaseModel):
    work_type: str  # "epoxy" | "polish" | "combo"


class GenerateIn(BaseModel):
    """Final payload from Screen 3's Generate button."""

    work_type: str = "epoxy"
    audience:  str = "Direct"  # "Direct" | "GC" | (other)
    # All intake + estimate + proposal fields flattened
    values: Dict[str, Any] = Field(default_factory=dict)
    # Direct cell-for-cell writes (Estimate Review verbatim mode):
    #   { "Epoxy!E20": 18000, "Polish!C20": 0.07, ... }
    cell_values: Dict[str, Any] = Field(default_factory=dict)
    # Custom material lines -> Epoxy spare "=B*C" rows:
    #   [{"label": "Super Stick", "qty": 2, "unit_price": 50}, ...]
    extras: list = Field(default_factory=list)
    # Authoritative bid from the 5.7-recipe engine (computed on Screen 2).
    # Echoed back in the response `totals` so nothing shows a stale number.
    computed_bid: Dict[str, Any] | None = None
    # Structured proposal price lines (options / unit prices): [{"label","amount"}].
    # Rendered as repeatable {{#price_line}} rows under PRICE; NOT priced into the bid.
    price_lines: list = Field(default_factory=list)
    # Combo per-option price breakout (pre-formatted): [{"amount_formatted","label"}]
    # e.g. "$28,400" / "Option 1: Epoxy flooring as described above (…INCLUDED)",
    # "$1,200" / "Kansas Remodel Tax", "$29,600" / "Total", then Option 2 (Polish).
    # When present, these render FIRST under PRICE and the combined single-bid line
    # is suppressed (the two option totals ARE the price).
    combo_options: list = Field(default_factory=list)
    # Recommended ALTERNATE system bid (the full /api/price response with an
    # `alternate_full_bid` + `alternate`), and its proposal label.
    alternate_computed_bid: Dict[str, Any] | None = None
    alternate_label: str = ""
    # Conditional {{#remodel}} line: [{"amount_formatted": "$x"}] when a remodel
    # tax applies, [] (the default) when the remodel toggle is off.
    remodel: list = Field(default_factory=list)
    # Per-room priced options (per-room jobs). Each: {id, name, role, bid:{total,
    # sales_tax, remodel}, notes_auto:[...], notes_manual:[...]}. Derived from the
    # epoxy-layout estimate tabs; drives the proposal {{#room}} options block.
    rooms: list = Field(default_factory=list)
    # Worksheets the user duplicated in the editor: [{id, source, role}]. The
    # backend clones `source` into a sheet titled `id` so the copy's
    # "<id>!<addr>" cell_values land.
    tab_copies: list = Field(default_factory=list)
    # Display labels for renamed tabs: {internal_id: label}. Applied to the .xlsx
    # worksheet titles (with cross-sheet formula refs rewritten) at the very end.
    tab_labels: Dict[str, Any] = Field(default_factory=dict)
    # Drag-to-reorder worksheet order, by internal id. Applied to the .xlsx tab order.
    tab_order: list = Field(default_factory=list)
    # Structural edits (insert/delete rows & columns), in the order made:
    # [{sheet, kind: insert_rows|delete_rows|insert_cols|delete_cols, at, count}].
    # Replayed onto the workbook with formula/merge/lock-map translation.
    tab_structs: list = Field(default_factory=list)
    # Per-sheet cell-lock overrides from the grid's "Lock cell" toolbar button:
    # {sheetId: {"lock": [addr...], "unlock": [addr...]}}, addresses in CURRENT
    # grid coordinates. Merged over the default rate/markup/tax locks in the
    # generated .xlsx (estimate_writer._resolve_ws_layouts). Normalized there
    # (_norm_lock_overrides) — never trusted raw.
    lock_overrides: Dict[str, Any] = Field(default_factory=dict)
    # Editable proposal NOTES (one string per bullet). Empty -> standard per-work-type
    # boilerplate is used (so the notes never vanish).
    notes: list = Field(default_factory=list)
    # Proposal Review's document editor: free-text edits to template paragraphs
    # OUTSIDE the priced/repeatable regions (see /api/proposal-template).
    # [{"id": <int, from that endpoint>, "text": "<resolved plain text>"}].
    # Sanitized in api_generate (cap 500, coerce id->int/text->str) before
    # reaching proposal_writer.fill_proposal — see _sanitize_paragraph_overrides.
    paragraph_overrides: list = Field(default_factory=list)
    # The proposal template version the paragraph_overrides ids were captured
    # against (echoed from /api/proposal-template). Since annotation shifts the
    # editable-block ids, api_generate DROPS paragraph_overrides when this is
    # non-empty AND doesn't match the current template's version (fail-safe so a
    # stale draft can't misapply ids). Empty = legacy caller = apply unchanged.
    template_version: str = ""
    # Proposal Review doc editor: per-option DISPLAY overrides for the WORK
    # {{#system}} rows — [{name?, texture?, sqft?}] positionally aligned with
    # _build_epoxy_systems() output (index i -> systems[i]). These edit only the
    # proposal's displayed text; they are NEVER written back to cell_values and
    # NEVER affect pricing. Applied for epoxy only (other work types pass
    # systems=None). Sanitized index-preserving — see _sanitize_system_overrides.
    system_overrides: list = Field(default_factory=list)
    # Proposal Review doc editor: per-line DISPLAY overrides for the PRICE
    # section — {"options": {<option id>: {label?, amount?}}, "manual":
    # [{label?, amount?}...] (index-aligned with `price_lines`), "single_bid":
    # {amount?, tax_phrase?}}. DISPLAY-ONLY: these override the shown label/amount
    # text on the proposal's PRICE lines; they NEVER touch cell_values, the .xlsx,
    # or GenerateOut totals. Sanitized in api_generate — see _sanitize_price_overrides.
    price_overrides: Dict[str, Any] = Field(default_factory=dict)
    # Proposal Review: the WORK {{#system}} picks resolved from the BASE tab's
    # sheet cells (name + SF + cove LF per system) so the docx Area matches the
    # on-screen preview even when the base is a copy tab. [{name?, sf, lf}].
    # Empty -> _build_epoxy_systems keeps its legacy Epoxy!-cell reads (stale
    # drafts / the To-Dropbox reconstruction path). Sanitized in api_generate.
    sheet_systems: list = Field(default_factory=list)


class AutofillIn(BaseModel):
    """Inputs we send to Claude for the 'Autofill with AI' button."""

    project_name: str | None = None
    address:      str | None = None
    city_state:   str | None = None
    notes:        str | None = None


class GenerateOut(BaseModel):
    work_type: str
    audience: str
    xlsx_download_url: str
    docx_download_url: str
    pdf_download_url: str       # on-demand LibreOffice render of the .docx
    totals: Dict[str, Any]     # Python-computed preview totals


# ─── In-memory file cache for downloads ───────────────────────────────
# Generate fills the xlsx + docx in memory and stashes the bytes here under a
# random token; the Done screen's download buttons hit /api/file/{token}.
# The docx entry also memoizes its rendered PDF (entry["_pdf"]) on first
# /api/file/{token}/pdf request. Cache lives for the process lifetime
# (single uvicorn worker), so a container restart invalidates old tokens.
# Bounded TTL cache (dict-like) caps memory + auto-expires stale tokens.
_FILE_CACHE = cachetools.TTLCache(maxsize=256, ttl=3600)

# Cap concurrent LibreOffice PDF renders (each spawns a heavy headless soffice
# process); without this, public /api/file/{token}/pdf hits can fork-bomb the box.
_PDF_RENDER_SEM = threading.Semaphore(2)


def _cache_file(content: bytes, filename: str, content_type: str) -> str:
    token = uuid.uuid4().hex
    _FILE_CACHE[token] = {
        "content": content,
        "filename": filename,
        "content_type": content_type,
    }
    return token


# ─── Work-type detection rule ─────────────────────────────────────────
def detect_work_type(epoxy_sf: float, polish_sf: float) -> str:
    """Deterministic rule. Troy can override on Screen 2 if needed."""
    e = (epoxy_sf or 0) > 0
    p = (polish_sf or 0) > 0
    if e and p:
        return "combo"
    if p:
        return "polish"
    return "epoxy"  # default; covers (e and not p) AND (neither, sane fallback)


# ─── Endpoints ────────────────────────────────────────────────────────
@app.get("/healthz")
def healthz() -> Dict[str, Any]:
    return {"ok": True}


# ─── Basisboard read-only pipeline (CRM view) ─────────────────────────
# Surfaces the bids/projects that already live in Basisboard. READ-ONLY — the
# API key stays server-side (never sent to the browser), so the frontend hits
# these JWT-gated proxy routes instead of Basisboard directly. Inert (configured
# = false) when BASISBOARD_API_KEY isn't set, so the app behaves exactly as
# before on a deploy without the key.
@app.get("/api/basisboard/status")
def api_basisboard_status() -> Dict[str, Any]:
    return {"ok": True, "configured": basisboard_client.is_configured()}


@app.get("/api/basisboard/projects")
def api_basisboard_projects() -> Dict[str, Any]:
    return basisboard_client.get_pipeline()


# ─── Customer Portal integration (server-side proxy to the portal admin API) ───
# The portal owns the portal_* tables; here we just call its SERVICE_TOKEN-gated
# admin API. PORTAL_ADMIN_URL + SERVICE_TOKEN live in the env (not committed).
def _portal(path: str, method: str = "GET", body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    import httpx
    base = (os.environ.get("PORTAL_ADMIN_URL") or "").rstrip("/")
    token = (os.environ.get("SERVICE_TOKEN") or "").strip()
    if not base or not token:
        raise HTTPException(503, "Customer portal isn't configured (PORTAL_ADMIN_URL / SERVICE_TOKEN).")
    try:
        with httpx.Client(timeout=20.0, headers={"X-Service-Token": token}) as c:
            resp = c.request(method, base + path, json=body)
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Could not reach the customer portal.") from exc
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("error")
        except Exception:  # noqa: BLE001
            detail = None
        raise HTTPException(resp.status_code if resp.status_code < 500 else 502, detail or "Portal error.")
    return resp.json()


_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _safe_id(value: str) -> str:
    """Constrain an id that's interpolated into an outbound URL path to a safe
    charset (no slashes / dots / query chars) — prevents the proxy request from
    being redirected to another path or host (partial SSRF) via a crafted id."""
    if not value or not _SAFE_ID.match(value):
        raise HTTPException(400, "Invalid id.")
    return value


# Linear-time email shape check: dot-separated domain labels that exclude '.',
# so there is no overlap between the label class and the '.' separator (the old
# [^@\s]+\.[^@\s]+ form backtracked polynomially — a ReDoS). The portal
# re-validates on its side; this is a cheap first-line guard.
_PORTAL_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$")
_MAX_PORTAL_EMAILS = 10


class PortalPublishIn(BaseModel):
    """Optional body for /api/portal/publish — extra portal recipients typed on
    the Files screen (the intake contact is always included by the portal)."""
    emails: list[str] = Field(default_factory=list)


def _clean_portal_emails(raw: list) -> list:
    """Trim / validate / case-insensitively dedupe (keep first casing) / cap.
    Raises HTTPException(400) on a malformed address. Empty list is fine (the
    portal falls back to the draft's contact_email)."""
    out, seen = [], set()
    for e in raw or []:
        e = (e or "").strip()
        if not e:
            continue
        if len(e) > 254 or not _PORTAL_EMAIL_RE.match(e):
            raise HTTPException(400, "invalid_email")
        key = e.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    if len(out) > _MAX_PORTAL_EMAILS:
        raise HTTPException(400, "too_many_emails")
    return out


@app.post("/api/portal/publish")
def api_portal_publish(draft_id: str, request: Request,
                       payload: Optional[PortalPublishIn] = None) -> Dict[str, Any]:
    """Send a proposal (draft) to the customer portal — mints a link + emails it.

    Backward compatible: the currently-deployed frontend sends no body → `payload`
    is None → we forward exactly `{draft_id, by}` (legacy). The new Files-screen
    modal sends `{emails: [...]}` (intake contact + extras); we validate + forward
    them so the portal emails/authorizes every recipient. Malformed JSON or a
    wrong-typed `emails` yields FastAPI's 422 — never a 500 — keeping the sync
    handler (threadpool) so the proxy's blocking httpx call doesn't stall the loop."""
    draft_id = _safe_id(draft_id)
    if not drafts.load_draft(draft_id):
        raise HTTPException(404, "Draft not found")
    body: Dict[str, Any] = {"draft_id": draft_id, "by": _user_email(request)}
    emails = _clean_portal_emails(payload.emails if payload else [])
    if emails:
        body["emails"] = emails
    return _portal("/api/admin/publish", "POST", body)


@app.get("/api/portal/pipeline")
def api_portal_pipeline() -> Dict[str, Any]:
    return _portal("/api/admin/pipeline", "GET")


@app.get("/api/portal/proposal/{proposal_id}")
def api_portal_proposal(proposal_id: str) -> Dict[str, Any]:
    return _portal(f"/api/admin/proposal/{_safe_id(proposal_id)}", "GET")


@app.post("/api/portal/proposal/{proposal_id}/reply")
async def api_portal_reply(proposal_id: str, request: Request) -> Dict[str, Any]:
    proposal_id = _safe_id(proposal_id)
    body = await request.json()
    return _portal(f"/api/admin/proposal/{proposal_id}/reply", "POST",
                   {"body": (body or {}).get("body") or "", "by": _user_email(request)})


@app.post("/api/portal/proposal/{proposal_id}/deposit-request")
async def api_portal_deposit_request(proposal_id: str, request: Request) -> Dict[str, Any]:
    """Staff-triggered: push a deposit request into the customer chat + email.
    Optional {amount} override; otherwise the portal uses its 25% auto-calc."""
    proposal_id = _safe_id(proposal_id)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — empty/malformed body is fine (amount optional)
        body = {}
    payload: Dict[str, Any] = {"by": _user_email(request)}
    if isinstance(body, dict) and body.get("amount") is not None:
        payload["amount"] = body["amount"]
    return _portal(f"/api/admin/proposal/{proposal_id}/deposit-request", "POST", payload)


@app.post("/api/portal/proposal/{proposal_id}/deposit-received")
def api_portal_deposit_received(proposal_id: str) -> Dict[str, Any]:
    return _portal(f"/api/admin/proposal/{_safe_id(proposal_id)}/deposit-received", "POST", {})


@app.post("/api/portal/proposal/{proposal_id}/scheduled")
def api_portal_scheduled(proposal_id: str) -> Dict[str, Any]:
    return _portal(f"/api/admin/proposal/{_safe_id(proposal_id)}/scheduled", "POST", {})


# ─── Notification Sending: roster + per-project overrides (proxied to the portal) ─
# Access (Hanz: "admins edit, staff self-serve"): the GLOBAL roster (add / remove /
# toggle) is ADMIN-only, enforced here server-side (not just hidden buttons); the
# per-project overrides allow ANY signed-in staff to toggle THEMSELVES for a project,
# and admins to toggle anyone. All routes are already bearer-gated by _auth_gate.
def _caller_is_admin(request: Request) -> bool:
    try:
        _require_admin(request)
        return True
    except HTTPException:
        return False


@app.get("/api/portal/notify-recipients")
def api_portal_notify_list() -> Dict[str, Any]:
    return _portal("/api/admin/notify-recipients", "GET")


@app.post("/api/portal/notify-recipients")
async def api_portal_notify_add(request: Request) -> Dict[str, Any]:
    _require_admin(request)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(400, "Invalid body.")
    email = (body.get("email") or "").strip().lower()
    kind = (body.get("kind") or "general").strip().lower()
    if kind not in ("general", "deposit"):
        raise HTTPException(400, "Choose a general or deposit recipient.")
    if len(email) > 254 or not _PORTAL_EMAIL_RE.match(email):
        raise HTTPException(400, "Enter a valid email address.")
    return _portal("/api/admin/notify-recipients", "POST",
                   {"email": email, "kind": kind, "by": _user_email(request)})


@app.patch("/api/portal/notify-recipients/{rid}")
async def api_portal_notify_toggle(rid: int, request: Request) -> Dict[str, Any]:
    _require_admin(request)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    enabled = bool(isinstance(body, dict) and body.get("enabled"))
    return _portal("/api/admin/notify-recipients/" + _safe_id(str(rid)), "PATCH", {"enabled": enabled})


@app.delete("/api/portal/notify-recipients/{rid}")
def api_portal_notify_delete(rid: int, request: Request) -> Dict[str, Any]:
    _require_admin(request)
    # rid is int-typed, but route it through the same id guard as every other
    # proxied path segment so the outbound URL is provably constrained.
    return _portal("/api/admin/notify-recipients/" + _safe_id(str(rid)), "DELETE")


@app.get("/api/portal/notify-overrides-all")
def api_portal_notify_overrides_all() -> Dict[str, Any]:
    # Every per-project override at once, for the Notification Sending page's
    # per-project view. Read-only (bearer-gated by _auth_gate; not admin-gated,
    # same as the roster + single-project GETs).
    return _portal("/api/admin/notify-overrides", "GET")


@app.get("/api/portal/proposal/{pid}/notify-overrides")
def api_portal_notify_overrides_get(pid: str) -> Dict[str, Any]:
    return _portal("/api/admin/proposal/" + _safe_id(pid) + "/notify-overrides", "GET")


@app.put("/api/portal/proposal/{pid}/notify-overrides")
async def api_portal_notify_overrides_set(pid: str, request: Request) -> Dict[str, Any]:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(400, "Invalid body.")
    email = (body.get("email") or "").strip().lower()
    mode = (body.get("mode") or "").strip().lower()
    if len(email) > 254 or not _PORTAL_EMAIL_RE.match(email):
        raise HTTPException(400, "Enter a valid email address.")
    if mode not in ("add", "mute", "clear"):
        raise HTTPException(400, "Invalid mode.")
    # Admin may toggle anyone; a non-admin may only toggle THEIR OWN address.
    me = (_user_email(request) or "").strip().lower()
    if not _caller_is_admin(request) and email != me:
        raise HTTPException(403, "You can only change your own notifications for a project.")
    return _portal("/api/admin/proposal/" + _safe_id(pid) + "/notify-overrides", "PUT",
                   {"email": email, "mode": mode})


@app.get("/api/admin/proposal-pdf")
def api_admin_proposal_pdf(draft_id: str, request: Request) -> Response:
    """Render a draft's proposal to its real Treadwell PDF, on demand. Called
    server-to-server by the customer portal (SERVICE_TOKEN-gated; this path is in
    _AUTH_PUBLIC_PATHS so it skips the Google gate). Reuses the full /api/generate
    pipeline + LibreOffice render, so the customer sees the exact branded document."""
    import hmac
    presented = request.headers.get("x-service-token") or ""
    token_env = (os.environ.get("SERVICE_TOKEN") or "").strip()
    if not token_env or not hmac.compare_digest(presented, token_env):
        raise HTTPException(401, "unauthorized")
    row = drafts.load_draft(draft_id)
    if not row:
        raise HTTPException(404, "Draft not found")
    pp = (row.get("data") or {}).get("proposal_payload")
    if not (isinstance(pp, dict) and pp.get("values")):
        raise HTTPException(422, "This proposal hasn't been generated yet.")
    out = api_generate(GenerateIn(**pp), request)         # reuse the full generate logic
    tok = (out.docx_download_url or "").rsplit("/", 1)[-1]
    entry = _FILE_CACHE.get(tok)
    if not entry:
        raise HTTPException(500, "Could not build the proposal document.")
    pdf_bytes = entry.get("_pdf")
    if pdf_bytes is None:
        try:
            with _PDF_RENDER_SEM:
                pdf_bytes = pdf_writer.docx_to_pdf(entry["content"])
            entry["_pdf"] = pdf_bytes
        except Exception as exc:  # noqa: BLE001
            log.exception("Portal PDF render failed")
            raise HTTPException(500, "Failed to render the proposal PDF.") from exc
    proj = re.sub(r"[^\x20-\x7e]", "_", str((row.get("data") or {}).get("project_name") or "Treadwell Proposal"))
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{proj} - Proposal.pdf"'})


@app.post("/api/detect-work-type", response_model=DetectWorkTypeOut)
def api_detect_work_type(payload: DetectWorkTypeIn) -> DetectWorkTypeOut:
    """Called between Screen 1 and Screen 2 to pick the right tab."""
    epoxy_sf = (payload.system_1_sf or 0) + (payload.system_2_sf or 0)
    return DetectWorkTypeOut(
        work_type=detect_work_type(epoxy_sf, payload.polish_sf),
    )


class PriceIn(BaseModel):
    """Selections + quantities to price via the extracted 5.7 recipes.

    systems: [{"name": "<epoxy system>", "sf": 12000}, ...]   (1..N systems)
    polish_sf + polish flags (reno/grout/dye/joint_filler)
    coves:   [{"option": "Epoxy 4\"", "lf": 250, "quartz": false}, ...]
    """
    systems: list = Field(default_factory=list)
    polish_sf: float = 0
    polish: Dict[str, Any] = Field(default_factory=dict)
    coves: list = Field(default_factory=list)
    extras: list = Field(default_factory=list)   # custom material lines: [{"label","qty","unit_price"}] or [{"label","amount"}]
    bulk_discount: bool = False   # Kyle's D41 toggle — swaps 6 materials to bulk rates
    sales_tax_rate: float = 0.09475   # combined sales-tax rate (on material) if taxable
    remodel_rate: float = 0       # KS remodel rate = state 6.5% + county (on labor/service)
    taxable: bool = True
    remodel: bool = False
    full_bid: bool = False        # also compute labor+markup+bond -> Total Base Bid
    labor: Dict[str, Any] = Field(default_factory=dict)   # crews/rate/markup overrides (manual)
    # Optional ALTERNATE (recommended) system — priced as a second, independent
    # bid with the SAME tax/labor params. Empty alternate_systems => no alternate.
    alternate_systems: list = Field(default_factory=list)
    alternate_coves: list = Field(default_factory=list)
    alternate_polish_sf: float = 0
    alternate_polish: Dict[str, Any] = Field(default_factory=dict)
    alternate_label: str = ""


def _price_bundle(payload: PriceIn, systems_in: list, coves_in: list,
                  polish_sf: float, polish_flags: Dict[str, Any]) -> Dict[str, Any]:
    """Price one bundle of selections (systems + polish + coves + extras) into the
    sheet's Material Total and (optionally) a Total Base Bid. Shared by the base
    bid and the alternate-system bid so both use identical tax/labor params."""
    material = 0.0
    systems = []
    for s in (systems_in or []):
        r = pricing.compute_system(s.get("name"), s.get("sf") or 0,
                                   bulk_discount=payload.bulk_discount)
        systems.append(r)
        material += r["material"]

    polish = None
    if polish_sf:
        pf = polish_flags or {}
        polish = pricing.compute_polish(
            polish_sf,
            reno=bool(pf.get("reno")), grout=bool(pf.get("grout")),
            dye=bool(pf.get("dye")), joint_filler=bool(pf.get("joint_filler")),
        )
        material += polish["material"]

    coves = []
    for c in (coves_in or []):
        r = pricing.compute_cove(c.get("option"), c.get("lf") or 0,
                                 quartz_system=bool(c.get("quartz")))
        coves.append(r)

    # Roll up to the sheet's Material Total (D40 sub -> +D42 shipping -> D43),
    # including the per-system patch line (epoxy SF * 0.10).
    patch_sf = sum((s.get("sf") or 0) for s in (systems_in or []))
    cove_total = sum(c["material"] for c in coves)
    polish_total = polish["material"] if polish else 0.0

    # Custom material lines ("Super Stick", "Floor Graphic", + edge-case adds):
    # amount = qty * unit_price (the sheet's =B*C spare rows), or a direct amount.
    extras = []
    extras_total = 0.0
    for e in (payload.extras or []):
        try:
            if e.get("amount") is not None:
                amt = float(e.get("amount") or 0)
                qty = e.get("qty"); up = e.get("unit_price")
            else:
                qty = float(e.get("qty") or 0)
                up = float(e.get("unit_price") or 0)
                amt = qty * up
        except (TypeError, ValueError):
            continue
        amt = round(amt, 2)
        if not amt:
            continue
        extras.append({"label": (e.get("label") or "").strip() or "Material",
                       "qty": qty, "unit_price": up, "amount": amt})
        extras_total += amt

    roll = pricing.roll_up(systems, cove_total=cove_total,
                           polish_total=polish_total, patch_sf=patch_sf,
                           extras_total=extras_total)
    mt = roll["material_total"]

    sales_tax = math.ceil(mt * payload.sales_tax_rate) if (payload.taxable and payload.sales_tax_rate) else 0

    resp = {
        "systems": systems, "polish": polish, "coves": coves,
        "extras": extras, "extras_total": round(extras_total, 2),
        "patch": round(patch_sf * pricing.EPOXY_PATCH_RATE, 2),
        **roll,
        "sales_tax": sales_tax,
    }

    if payload.full_bid:
        lb = payload.labor or {}
        crews = lb.get("crews")
        crews = [tuple(c) for c in crews] if crews else None
        resp["full_bid"] = pricing.compute_full_bid(
            mt, patch_sf,
            crews=crews, labor_rate=lb.get("labor_rate", 32.2),
            day_hours=lb.get("day_hours", 8), travel_hours=lb.get("travel_hours", 0),
            prevailing_wage=lb.get("prevailing_wage", False), demo_sf=lb.get("demo_sf", 0),
            local=lb.get("local", True), super_pct=lb.get("super_pct", 0.03),
            soft_pct=lb.get("soft_pct", 0.13), contingency=lb.get("contingency", 0),
            hard_bid=lb.get("hard_bid", False), taxable=payload.taxable,
            sales_tax_rate=payload.sales_tax_rate, remodel=payload.remodel,
            remodel_rate=payload.remodel_rate or 0.0,
            fees=lb.get("fees", 0), bond_pct=lb.get("bond_pct", 0),
        )
    else:
        resp["grand_total"] = round(mt + sales_tax, 2)
    return resp


@app.post("/api/price")
def api_price(payload: PriceIn) -> Dict[str, Any]:
    """Compute MATERIAL pricing from selections — the tool's own pricing
    engine (replaces the estimate sheet's named-range formulas the browser
    can't evaluate, which is what shows #NAME? in the live preview).

    When `alternate_systems` is supplied, a SECOND independent bid is computed
    (Kyle's recommended alternate) using the same tax/labor params, and returned
    under `alternate_full_bid` + `alternate`. Omitting it leaves the response
    byte-for-byte the same as before (back-compat)."""
    resp = _price_bundle(payload, payload.systems, payload.coves,
                         payload.polish_sf, payload.polish)

    if payload.alternate_systems:
        alt = _price_bundle(payload, payload.alternate_systems, payload.alternate_coves,
                           payload.alternate_polish_sf, payload.alternate_polish)
        resp["alternate_full_bid"] = alt.get("full_bid")
        alt_sf = sum((s.get("sf") or 0) for s in payload.alternate_systems)
        resp["alternate"] = {
            "systems": alt["systems"], "coves": alt["coves"], "polish": alt["polish"],
            "material_total": alt["material_total"],
            "material_sub": alt["material_sub"],   # pre-shipping; injected into the alt xlsx tab
            "sales_tax": alt["sales_tax"],
            "label": (payload.alternate_label or "").strip()
                     or (payload.alternate_systems[0].get("name") if payload.alternate_systems else ""),
            "sf": alt_sf,
        }
    return resp


@app.get("/api/pricing/systems")
def api_pricing_systems(request: Request) -> Response:
    """The epoxy systems + cove options the tool can price (for the UI)."""
    payload = {"systems": pricing.list_systems(), "coves": pricing.list_cove_options()}
    return _versioned_json(request, payload, version=pricing.recipes_version())


@app.get("/api/sheets")
def api_list_sheets(request: Request) -> Response:
    """List every tab in the estimate template (powers Screen 2's tab bar)."""
    return _versioned_json(request, {"sheets": estimate_writer.list_sheet_names()},
                           version=_template_version())


@app.get("/api/named-expressions")
def api_named_expressions(request: Request) -> Response:
    """Workbook-wide defined names that HyperFormula needs registered
    so formulas referencing them (e.g. =AT_Clear_Satin_w_Grit) resolve."""
    return _versioned_json(request, {"names": estimate_writer.read_named_expressions()},
                           version=_template_version())


@app.get("/api/reference/tax-rate")
def api_tax_rate(city_state: str = "") -> Dict[str, Any]:
    """Server-side reference lookup for sales-tax rates. NOT exposed
    as one of the visible 16 sheets — pure reference data."""
    return reference_tax.lookup(city_state)


@app.get("/api/reference/counties")
def api_counties(state: str = "") -> Dict[str, Any]:
    """Searchable county list for the Remodel-Tax dropdown.
    Optional ?state=MO|KS filter."""
    return {"counties": reference_tax.list_counties(state)}


@app.get("/api/sheet/{sheet_name}")
def api_get_sheet(sheet_name: str, request: Request) -> Response:
    """Return every used cell on `sheet_name` so the UI can render it
    cell-for-cell (values, formulas, fills, fonts, merges, dropdowns).

    This is the heaviest endpoint (~2.1 MB raw for Epoxy). gzip middleware
    shrinks it ~95% and the ETag lets repeat loads revalidate as a 304.
    """
    try:
        payload = estimate_writer.read_sheet_grid(sheet_name)
    except KeyError:
        raise HTTPException(404, f"Sheet {sheet_name!r} not found")
    return _versioned_json(request, payload, version=f"{sheet_name}:{_template_version()}")


_AUTOFILL_SYSTEM_PROMPT = (
    "You're an assistant for Treadwell, a Kansas City commercial epoxy/"
    "polish flooring contractor. Given a project's intake summary + lead "
    "notes, fill in EVERYTHING you can reasonably infer to save the "
    "estimator time. The estimator can override any value.\n\n"
    "Return STRICT JSON only (no markdown fences). Top-level shape:\n"
    "{\n"
    '  // ─── Estimate-sheet cells (Yes/No flags) ───────────\n'
    '  "Epoxy!B4":  "Yes|No",   // Local? Address within ~70mi of KC, MO\n'
    '  "Epoxy!B5":  "Yes|No",   // Hard Bid? (multiple contractors bidding)\n'
    '  "Epoxy!D5":  "Yes|No",   // Prevailing Wage? (public funding)\n'
    '  "Epoxy!B6":  "Yes|No",   // Taxable? (default Yes unless exempt cert mentioned)\n'
    '  "Epoxy!D6":  "Yes|No",   // Remodel tax (often Yes if user has remodel exemption)\n'
    '  "Epoxy!B9":  "<date M/D/YY>", // Drawings dated — ONLY if a drawing/spec date is in the notes\n'
    '  "Epoxy!B10": "New|Reno", // New construction vs renovation\n'
    "\n"
    '  // ─── Proposal narrative fields (free text for the docx) ───\n'
    '  "system_name":     "<one-line Treadwell system name>",   // e.g. "Treadwell Macro Flake Single Broadcast"\n'
    '  "texture":         "<one or two words>",                 // e.g. "Orange Peel"  or  "Smooth"\n'
    '  "scope_notes":     "<one paragraph, 2-4 sentences>",     // Demo plan + prep + install\n'
    '  "schedule_notes":  "<one short sentence>",               // "Assumes all areas available at one time, approx. N weeks to complete full scope"\n'
    '  "exclusions":      "<comma-separated list of standard exclusions>", // multi-layer demo, FF&E moving, etc.\n'
    "\n"
    '  // ─── Reasoning trail (auditability) ─────────────────\n'
    '  "reasoning": {"<key>": "<short why-this-value>", ...}\n'
    "}\n"
    "\n"
    "Rules:\n"
    "- ALWAYS fill all 7 flag cells (B4, B5, D5, B6, D6, B9, B10) unless\n"
    "  the value is truly indeterminate from BOTH the notes AND the\n"
    "  defaults below. For a flag, you should NEVER return null/empty\n"
    "  if the notes contain any signal at all.\n"
    "- Triggers for each flag — fill if you see ANY of these signals:\n"
    "    Epoxy!B5 (Hard Bid) = Yes if notes mention: 'hard bid',\n"
    "      'multiple contractors', 'N contractors bidding', 'getting bids',\n"
    "      'bid against', 'competitive bid'.\n"
    "    Epoxy!D5 (Prevailing Wage) = Yes if notes mention: 'prevailing\n"
    "      wage', 'public funded', 'state-funded', 'bond-funded',\n"
    "      'federal funds', 'school district', 'municipality', 'gov't'.\n"
    "    Epoxy!B6 (Taxable) = No if notes mention: 'tax exempt',\n"
    "      'sales tax exemption', 'exempt cert', 'nonprofit', 'school\n"
    "      district + exemption'. Else default Yes.\n"
    "    Epoxy!D6 (Remodel tax) = Yes if notes mention: 'remodel\n"
    "      exemption', 'capital improvement exempt'. Else No.\n"
    "    Epoxy!B9 (Drawings dated) = the M/D/YY date if notes mention\n"
    "      'drawings dated X', 'spec X', 'plans dated X'. Else OMIT.\n"
    "    Epoxy!B10 (New/Reno) = Reno if notes mention: 'renovation',\n"
    "      'redo', 'replace existing', 'remodel', 'demo existing',\n"
    "      'refurbish'. Else New.\n"
    "- Conservative DEFAULTS for when notes are silent on a flag:\n"
    "  Taxable=Yes, Hard Bid=No, Prevailing Wage=No, Remodel=No, B10=New.\n"
    "- DO NOT touch SF/LF quantities — the estimator types those in intake "
    "and those are authoritative.\n"
    "- For system_name + texture, infer from product mentions ('Macro "
    "Flake', 'Polish', 'Decorative Quartz', etc.). If the project is "
    "Polish, use 'Standard Sheen with Salt & Pepper Aggregate Exposure'.\n"
    "- scope_notes should reuse Treadwell's standard phrasing: "
    "'Demo (one layer of) existing flooring and place in dumpster provided "
    "by owner. Prepare substrate via mechanical means (grinding or shot "
    "blasting). Prep minor cracks and non-moving joints. Install <System>.'\n"
    "- exclusions should be the standard Treadwell list: 'Multiple layers "
    "of floor to be removed (change order required), Moving of "
    "Furniture/Fixtures, Touch-Up Paint, Excessive Patching (skim coating "
    "& more than 1 bag per 1,000 sf), Demo of Existing Floor/Glue/Etc., "
    "Weekend or night work, Credit for Unused mobilizations'.\n"
    "- schedule_notes: estimate duration from SF — ≤5k SF: 1 week, ≤15k: "
    "2 weeks, ≤30k: 3 weeks, >30k: 4+ weeks.\n"
    "- reasoning: one short phrase per filled key citing the source in notes."
)


def _autofill_via_cli(user_input: str) -> Dict[str, Any]:
    """Run the `claude -p` CLI subprocess and parse its JSON response.

    This is the ONLY autofill path. We deliberately don't call the
    Anthropic API directly — all Claude calls go through the CLI
    subprocess. The CLI uses the user's logged-in Pro/Max session
    (no API key needed).
    """
    import json
    import subprocess

    proc = subprocess.run(
        [
            "claude", "-p",
            # Pin the model so autofill is deterministic and doesn't drift with
            # CLI defaults. Sonnet = best accuracy/cost/latency for this
            # structured-extraction + short-drafting task (the flags it sets —
            # prevailing wage / remodel / taxable — affect price, so accuracy
            # matters; Opus is overkill for the 60s button, Haiku cheaper but
            # we keep Sonnet's extraction accuracy). Override via AUTOFILL_MODEL.
            "--model", os.environ.get("AUTOFILL_MODEL", "sonnet"),
            "--output-format", "text",
            "--append-system-prompt", _AUTOFILL_SYSTEM_PROMPT,
        ],
        input=user_input,
        capture_output=True,
        text=True,
        timeout=60,
        encoding="utf-8",
        errors="replace",
    )

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    log.info("Autofill CLI returncode=%s, stdout=%r, stderr=%r",
             proc.returncode, out[:300], err[:300])

    if proc.returncode != 0:
        raise RuntimeError(
            f"claude CLI exited with code {proc.returncode}. "
            f"stderr: {err[:200]}"
        )
    if not out:
        raise ValueError(f"claude CLI returned empty stdout. stderr: {err[:200]}")

    # Strip ```json fences
    if out.startswith("```"):
        out = out.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    # Sometimes Claude prefixes prose before the JSON; jump to first {
    brace = out.find("{")
    if brace > 0:
        out = out[brace:]
    return json.loads(out)


# ─── Autofill rate limit (per project) ────────────────────────────────
# `/api/autofill` runs the PAID Claude CLI (~20-30s). Cap it at N runs per
# window, counted per project (the client sends `X-Project-Id: <draftId>`).
# The button-disable on the client already stops ordinary double-clicks; this
# is the cost backstop. Single uvicorn worker (Dockerfile: --workers 1) → the
# in-memory dict is shared across requests, so no external store is needed.
_AUTOFILL_RATE_MAX    = 3
_AUTOFILL_RATE_WINDOW = 300   # seconds (5 minutes)
_AUTOFILL_HITS: Dict[str, list] = {}   # bucket(project id) -> [timestamps]


def _autofill_bucket(request: Request) -> str:
    """Rate bucket = authenticated email (+ project id). Keying on the email
    from the verified token (not just the client-controlled X-Project-Id header)
    stops a user from bypassing the cap by spoofing project ids, while still
    giving each project its own budget."""
    email = getattr(request.state, "user_email", None) or "anon"
    pid = (request.headers.get("x-project-id") or "").strip()
    return f"{email}|{pid}" if pid else email


def _autofill_rate_retry(bucket: str) -> int | None:
    """If `bucket` is at its limit, seconds until a slot frees up; else None."""
    now = time.time()
    hits = [t for t in _AUTOFILL_HITS.get(bucket, []) if now - t < _AUTOFILL_RATE_WINDOW]
    _AUTOFILL_HITS[bucket] = hits
    if len(hits) >= _AUTOFILL_RATE_MAX:
        return max(1, int(_AUTOFILL_RATE_WINDOW - (now - min(hits))))
    return None


def _autofill_rate_record(bucket: str) -> None:
    _AUTOFILL_HITS.setdefault(bucket, []).append(time.time())


def _autofill_rate_refund(bucket: str) -> None:
    """Give back the most recent slot — used when a run fails, so errors don't
    burn the project's budget."""
    if _AUTOFILL_HITS.get(bucket):
        _AUTOFILL_HITS[bucket].pop()


@app.post("/api/autofill")
def api_autofill(payload: AutofillIn, request: Request) -> Any:
    """Infer Yes/No flags + system selections from lead notes via the
    local `claude -p` CLI. No Anthropic API key is used — the CLI
    handles auth via the user's logged-in Claude session.

    Guarded by a per-project rate limit (see `_autofill_*` helpers above)."""
    bucket = _autofill_bucket(request)

    # Rate limit — at most N runs per window for this project.
    retry = _autofill_rate_retry(bucket)
    if retry is not None:
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(retry)},
            content={
                "ok": False, "rate_limited": True, "retry_after_seconds": retry,
                "error": f"Autofill limit reached (max {_AUTOFILL_RATE_MAX} per "
                         f"{_AUTOFILL_RATE_WINDOW // 60} min for this project). "
                         f"Try again in ~{math.ceil(retry / 60)} min.",
            },
        )

    # Reserve a slot up front so concurrent calls can't overshoot the cap.
    _autofill_rate_record(bucket)

    user_input = (
        f"Project name: {payload.project_name or '(none)'}\n"
        f"Address: {payload.address or '(none)'}\n"
        f"City/State: {payload.city_state or '(none)'}\n"
        f"Notes: {payload.notes or '(none)'}\n"
    )

    try:
        data = _autofill_via_cli(user_input)
        return {"ok": True, "cell_values": data, "via": "cli"}
    except FileNotFoundError:
        _autofill_rate_refund(bucket)   # error → don't consume the project's budget
        return {
            "ok": False,
            "error": "`claude` CLI not on PATH. Install it from "
                     "https://claude.com/cli to enable Autofill.",
        }
    except Exception as exc:  # noqa: BLE001
        _autofill_rate_refund(bucket)
        log.warning("Autofill failed: %s", exc)        # detail to server log, not the client
        return {"ok": False, "error": "Autofill failed. Please try again."}


def _fmt_usd(n, parens: bool = False) -> str:
    """Currency for proposal price lines: "$4,200" (drop trailing .00), "$4,200.50".
    Matches the frontend fmtUSD style so price-line/alternate text reads consistently.
    parens=True wraps the magnitude as a deduct/credit, e.g. "($4,200)" — Treadwell's
    "($x) – Deduct VE …" convention."""
    try:
        v = float(n)
    except (TypeError, ValueError):
        return ""
    s = f"${abs(v):,.2f}" if parens else f"${v:,.2f}"
    s = s[:-3] if s.endswith(".00") else s
    return f"({s})" if parens else s


def _ensure_state_name(values: Dict[str, Any]) -> None:
    """Default a blank state_name to "Kansas" in-place.

    The Direct-Epoxy proposal template has a "{{state_name}} Remodel Tax"
    line; a blank value would render "– Remodel Tax". The KS remodel tax is
    Kansas-specific and Treadwell is KC-based, so Kansas is the safe default.
    The frontend already resolves the real state from city_state/state; this
    is the server-side belt-and-suspenders.
    """
    if not str(values.get("state_name") or "").strip():
        values["state_name"] = "Kansas"


# Token aliases that mean the same value (see CLAUDE.md "Proposal template
# tokens"). Generation must NOT depend on the frontend having mapped these — a
# literal "{{job_name}}" in a customer-facing proposal is worse than anything
# this guards against. For each (target, source) pair, a blank/missing target
# is backfilled from a non-empty source, in-place. The real flow already sets
# both, so this is a no-op there; it only rescues callers/older payloads that
# sent just one side (e.g. project_name without job_name).
_VALUE_ALIASES = (
    ("job_name", "project_name"),
    ("project_name", "job_name"),
)

# A blank target is backfilled from the first non-empty source in the list; if
# none are present it's set to "" so the token renders empty rather than as a
# literal "{{token}}" in a customer-facing proposal. Mirrors the frontend's
# fallbacks (work_description -> address; site_visit_date -> bid date) so any
# caller / older payload still produces a clean doc.
_VALUE_FALLBACKS = (
    ("work_description", ("address", "city_state")),
    ("site_visit_date", ("bid_date_formatted", "bid_date")),
)


def _blank(v: Any) -> bool:
    return not str(v or "").strip()


def _build_epoxy_systems(cells: Dict[str, Any], values: Dict[str, Any],
                         sheet_systems: list | None = None) -> list:
    """WORK-section system list for an epoxy proposal. Preferred source is
    `sheet_systems` — the picks the frontend resolved from the BASE tab's sheet
    cells (name + SF + cove LF per system), so a copy-base's SF flows through.
    Falls back to the legacy Epoxy!A22/E20/E34 + A26/E24/E37 cell reads (stale
    drafts / the To-Dropbox reconstruction path) then to the flat values, so the
    {{#system}} block always has ≥1 row. One system → "System:   <name>";
    2+ → "Option 1: …" / "Option 2: …"."""
    def num(x) -> float:
        try:
            return float(str(x).replace(",", "").replace("$", "").strip() or 0)
        except (TypeError, ValueError):
            return 0.0
    def fmt(n: float) -> str:
        return f"{int(round(n)):,}"

    picks = []
    if sheet_systems:                              # frontend-resolved base-tab picks
        for s in sheet_systems:
            nm = str((s or {}).get("name") or "").strip()
            if not nm or "Options" in nm:
                nm = str(values.get("system_name") or "").strip() or "Epoxy System"
            picks.append({"name": nm, "sf": num((s or {}).get("sf")), "lf": num((s or {}).get("lf"))})
    if not picks:
        for na, sa, la in (("Epoxy!A22", "Epoxy!E20", "Epoxy!E34"),
                           ("Epoxy!A26", "Epoxy!E24", "Epoxy!E37")):
            name = str(cells.get(na) or "").strip()
            if name and "Options" not in name:     # skip the dropdown header placeholders
                picks.append({"name": name, "sf": num(cells.get(sa)), "lf": num(cells.get(la))})
    if not picks:                                  # no grid pick → single system from flat values
        picks = [{
            "name": str(values.get("system_name") or "").strip() or "Epoxy System",
            "sf": num(values.get("epoxy_sf") if values.get("epoxy_sf") is not None else cells.get("Epoxy!E20")),
            "lf": num(values.get("cove_lf") if values.get("cove_lf") is not None else cells.get("Epoxy!E34")),
        }]
    texture = str(values.get("texture") or "").strip()
    multi = len(picks) > 1
    # Cove base height (Kyle: note the cove height) — default 6", configurable per job.
    cove_h = str(values.get("cove_height") or "6").strip() or "6"
    # The template keeps the bold "System:"/"Option N:" label and a separate
    # regular value run, so we emit them as distinct tokens (prefix + name)
    # rather than one combined string — preserving the sheet's column alignment.
    out = []
    for i, s in enumerate(picks, 1):
        prefix = f"Option {i}:" if multi else "System:"
        lf_clause = f" and {fmt(s['lf'])} LF of {cove_h}\" epoxy cove base" if s["lf"] > 0 else ""
        out.append({"prefix": prefix, "name": s["name"], "texture": texture,
                    "sqft": fmt(s["sf"]), "lf_clause": lf_clause})
    return out


def _flooring_noun(work_type: str) -> str:
    """The generic flooring phrase for an option's PRICE line, by work type."""
    return {
        "epoxy":  "Epoxy flooring",
        "combo":  "Epoxy flooring",
        "polish": "Polished Concrete Flooring",
        "sealer": "Sealed Concrete",
        "gyp":    "Gypsum Underlayment System",
    }.get(str(work_type or "").lower(), "Flooring")


def _build_options(rooms_in: list, values: Dict[str, Any], work_type: str = "epoxy") -> list:
    """NON-base priced options for the proposal PRICE section ({{#room}} block).

    The base bid is rendered by {{#single_bid}}, so it is EXCLUDED here. Each input
    option (from the estimate/proposal side) is
    {name, is_base, base_total, deduct_amount, price_mode, show, option_desc,
     base_desc, system_desc, bid:{total, sales_tax, remodel}, notes_auto, notes_manual}.
    A shown option (show != False, positive total) renders in one of two modes:
      • total      → price_formatted "$8,310"; desc "<system> as described above (<tax>)"
      • add/deduct → diff = option_total − base_total (both tax-inclusive), and the
                     line SELF-LABELS by the sign (Will's spec):
                       diff < 0  → "Deduct ($3,200)" + "VE for <option>, in lieu of <base>."
                       diff ≥ 0  → "Add $2,232" + "<option>" (a costlier option is an ADD,
                                   not a silent fall-back to its own total as before)
    Returns [] when there are no shown options (the block then strips)."""
    def num(x) -> float:
        try:
            return float(str(x).replace(",", "").replace("$", "").strip() or 0)
        except (TypeError, ValueError):
            return 0.0

    noun = _flooring_noun(work_type)
    out = []
    for r in (rooms_in or []):
        if not isinstance(r, dict) or r.get("is_base"):
            continue                                  # base is rendered by single_bid
        if not r.get("show", True):
            continue                                  # estimator hid this option
        bid = r.get("bid") or {}
        total = num(bid.get("total"))
        if total <= 0:                                # un-snapshotted / empty sheet
            continue
        option_desc = str(r.get("option_desc") or r.get("system_desc") or r.get("name") or "").strip()
        diff = total - num(r.get("base_total"))       # option − base (Will's formula)

        if str(r.get("price_mode")) == "deduct":
            # Auto add/deduct by sign; the Add/Deduct word rides INSIDE the amount
            # island so the docx row reads "Add $2,232 – <label>" / "Deduct ($3,200) – <label>".
            if diff < 0:
                base_desc = str(r.get("base_desc") or "").strip() or "the base bid"
                price_formatted = "Deduct " + _fmt_usd(diff, parens=True)   # parens = abs magnitude
                price_desc = f"VE for {option_desc or noun}, in lieu of {base_desc}."
            else:
                price_formatted = "Add " + _fmt_usd(diff)
                price_desc = option_desc or noun
        else:                                         # total mode: the option's own price
            remodel = num(bid.get("remodel"))
            tax_phrase = ("(Remodel Tax AND material sales tax INCLUDED)"
                          if remodel > 0 else "(material sales tax INCLUDED)")
            price_formatted = _fmt_usd(total)
            price_desc = f"{option_desc or noun} as described above {tax_phrase}"

        lines = [str(n).strip()
                 for n in (list(r.get("notes_auto") or []) + list(r.get("notes_manual") or []))
                 if str(n).strip()]
        out.append({
            # Inert passthrough of the source room/tab id — lets api_generate map
            # a per-option price_overrides entry back to this line. Never affects
            # pricing or the option's rendered content on its own.
            "id": str(r.get("id") or ""),
            "heading": "",
            "price_formatted": price_formatted,
            "price_desc": price_desc,
            "notes_joined": "\n".join(lines),
        })
    return out


# Standard exclusions list — the boilerplate that used to be hardcoded in the
# template (now {{exclusions}}). Backfilled when the caller sends none so the
# token never renders literally and never prints blank.
try:
    _DEFAULT_NOTES = json.loads((Path(__file__).parent / "default_notes.json").read_text(encoding="utf-8"))
except Exception:  # noqa: BLE001 — missing/garbled file shouldn't crash startup
    _DEFAULT_NOTES = {}


def _phase_price_or_default(v) -> float:
    """Coerce the estimate's 'additional phase' price to a positive dollar amount;
    fall back to $4,500 on blank/garbage/out-of-range. Never raises."""
    try:
        n = float(str(v).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return 4500.0
    return n if 0 < n < 10_000_000 else 4500.0


def _phase_price_override_amount(v) -> Optional[str]:
    """The GC additional-phase amount to force into the proposal — but ONLY when
    the estimator actually CHANGED the cell. Returns a bare comma-grouped number
    string ("5,200"), or None to leave each GC template's own native default
    ($5,000 Resinous / $2,300 Polish/Sealer) in place.

    The estimate cell defaults to $4,500, so a value of exactly 4,500 (or
    blank/garbage/out-of-range) counts as 'unedited' → None. This encodes the
    product rule: a GC proposal keeps its native default until the cell changes,
    then follows the cell (Direct proposals already track the cell via the
    {{#notes}} bullet, independent of this). Never raises."""
    try:
        n = float(str(v).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    if not (0 < n < 10_000_000) or round(n) == 4500:
        return None
    return f"{int(round(n)):,}"


def _notes_for(work_type: str, notes_in: list, phase_price=None) -> list:
    """{{#notes}} items: the estimator's edited notes, else the standard
    per-work-type boilerplate (so the proposal's notes section never vanishes).

    Backstop for the "Add $xxxx for each additional phase…" bullet: substitute
    the literal ``$xxxx`` placeholder with the estimate's phase price (default
    $4,500). This covers the done.js "View files" fallback path (which ships no
    notes → the boilerplate default is used) and any legacy draft whose saved
    notes still carry the raw placeholder. A hand-typed numeric amount is left
    untouched — only the literal ``$xxxx`` anchor is replaced (the frontend
    handles live re-sync of numeric amounts against the cell).

    Blank lines are PRESERVED (Word-style spacing the estimator added in the
    editor) — each blank becomes a `{"text": ""}` item, which proposal_writer
    renders as a bullet-less blank line. Defaults kick in only when the caller
    sent NOTHING but blanks (so an all-empty notes box still gets boilerplate)."""
    lines = [str(n).rstrip() for n in (notes_in or [])]
    if not any(l.strip() for l in lines):
        wt = str(work_type or "epoxy").lower()
        lines = _DEFAULT_NOTES.get(wt) or _DEFAULT_NOTES.get("epoxy") or []
    amt = _fmt_usd(_phase_price_or_default(phase_price))
    lines = [ln.replace("$xxxx", amt) for ln in lines]   # list comp: never mutates _DEFAULT_NOTES
    return [{"text": ln} for ln in lines]


# Cap + coerce the document editor's paragraph_overrides before they reach
# proposal_writer.fill_proposal. Mirrors the combo_options sanitization above
# (str()-coerce before validating, cap the list) — a stale draft or hand-built
# request can send anything here, and this must never 500 /api/generate.
# proposal_writer._apply_paragraph_overrides re-validates independently (it's
# called directly by tests, bypassing this layer), so this is defense in depth,
# not the only guard.
_PARAGRAPH_OVERRIDES_MAX = 500


def _sanitize_paragraph_overrides(overrides_in: list) -> list:
    out = []
    for o in (overrides_in or [])[:_PARAGRAPH_OVERRIDES_MAX]:
        if not isinstance(o, dict):
            continue
        pid = o.get("id")
        if isinstance(pid, bool):   # bool is an int subclass — True would target id 1
            continue
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            continue
        text = o.get("text")
        if text is None:
            continue
        out.append({"id": pid, "text": str(text)})
    return out


# Cap + coerce the doc editor's per-option system_overrides. UNLIKE
# _sanitize_paragraph_overrides, this is INDEX-PRESERVING: a malformed entry
# coerces to {} in place rather than being dropped, because the list is
# positional (index i -> _build_epoxy_systems()[i]) and dropping an entry would
# shift every later override onto the wrong system. Values are str()-coerced,
# stripped, blanks dropped (a blank field = "revert this field to the computed
# value"), and length-capped. Never raises — a stale draft or hand-built request
# must not 500 /api/generate.
_SYSTEM_OVERRIDES_MAX = 12
_SYSTEM_OVERRIDE_FIELDS = ("name", "texture", "sqft")
_SYSTEM_OVERRIDE_FIELD_MAXLEN = 300


def _sanitize_system_overrides(overrides_in: list) -> list:
    out = []
    for o in (overrides_in or [])[:_SYSTEM_OVERRIDES_MAX]:
        entry: Dict[str, str] = {}
        if isinstance(o, dict):
            for k in _SYSTEM_OVERRIDE_FIELDS:
                v = o.get(k)
                if v is None or isinstance(v, (dict, list, bool)):
                    continue
                s = str(v).strip()
                if s:
                    entry[k] = s[:_SYSTEM_OVERRIDE_FIELD_MAXLEN]
        out.append(entry)
    return out


# Cap + coerce the frontend-resolved sheet_systems ([{name?, sf, lf}]) — the WORK
# picks sourced from the BASE tab's sheet cells. name is str()-coerced + capped;
# sf/lf coerced to a float >= 0; non-dict entries dropped. Never raises.
_SHEET_SYSTEMS_MAX = 4


def _sanitize_sheet_systems(systems_in: list) -> list:
    out = []
    for s in (systems_in or [])[:_SHEET_SYSTEMS_MAX]:
        if not isinstance(s, dict):
            continue
        def _f(x):
            try:
                return max(0.0, float(str(x).replace(",", "").replace("$", "").strip() or 0))
            except (TypeError, ValueError):
                return 0.0
        out.append({"name": str(s.get("name") or "").strip()[:_SYSTEM_OVERRIDE_FIELD_MAXLEN],
                    "sf": _f(s.get("sf")), "lf": _f(s.get("lf"))})
    return out


# Cap + coerce the doc editor's price_overrides. DISPLAY-ONLY: these override the
# TEXT shown on the proposal's PRICE lines (base bid, priced options, manual price
# lines) — they NEVER touch cell_values, the .xlsx, or GenerateOut totals. Mirrors
# _sanitize_system_overrides (str()-coerce, .strip(), drop a blank field = "revert
# to computed", per-field maxlen, never raises). Normalized shape:
#   {"options":    {<option id>: {label?, amount?}},
#    "manual":     [{label?, amount?}, ...],   # index-preserving, {} placeholders
#    "single_bid": {amount?, tax_phrase?}}
# `manual` is index-preserving (a malformed/blank entry -> {} in place) so a
# filtered-out price line can't shift a later override onto the wrong row — same
# rationale as _sanitize_system_overrides. An option entry that cleans to {} is
# dropped (a blank override = revert). Never raises: a stale draft or hand-built
# request must not 500 /api/generate.
_PRICE_OVERRIDES_MAX = 100
_PRICE_OVERRIDE_FIELD_MAXLEN = 500


def _sanitize_price_overrides(pov_in) -> dict:
    out: Dict[str, Any] = {"options": {}, "manual": [], "single_bid": {}}
    if not isinstance(pov_in, dict):
        return out

    def clean(o, fields) -> Dict[str, str]:
        entry: Dict[str, str] = {}
        if isinstance(o, dict):
            for k in fields:
                v = o.get(k)
                if v is None or isinstance(v, (dict, list, bool)):
                    continue
                s = str(v).strip()
                if s:
                    entry[k] = s[:_PRICE_OVERRIDE_FIELD_MAXLEN]
        return entry

    opts_in = pov_in.get("options")
    if isinstance(opts_in, dict):
        for oid, ov in list(opts_in.items())[:_PRICE_OVERRIDES_MAX]:
            entry = clean(ov, ("label", "amount"))
            if entry:                                 # blank/garbage entry = revert -> drop
                out["options"][str(oid)] = entry

    manual_in = pov_in.get("manual")
    if isinstance(manual_in, list):
        for m in manual_in[:_PRICE_OVERRIDES_MAX]:
            out["manual"].append(clean(m, ("label", "amount")))   # keep {} holes in place

    out["single_bid"] = clean(pov_in.get("single_bid"), ("amount", "tax_phrase", "desc"))
    return out


_DEFAULT_EXCLUSIONS = (
    "Multiple layers of floor to be removed (change order is necessary), Moving of "
    "Furniture/Fixtures, Touch-Up Paint, Excessive Patching (i.e., skim coating & more "
    "than 1 bag of patch material per 1,000 sf, see notes below), Demo of Existing "
    "Floor/Glue/Etc., Weekend or night work, Credit for Unused mobilizations"
)

# Standard narrative fallbacks — mirror the frontend's PROPOSAL_DEFAULTS
# (frontend/js/proposal-review.js). Backfilled ONLY when the caller sends a blank
# value so the proposal never renders a raw {{scope_notes}}/{{schedule_notes}}
# token (e.g. the "View files" rebuild path that posts raw state). The frontend
# normally fills these, so this is purely defensive.
_DEFAULT_SCHEDULE = "Assumes all areas available at one time, approx. 1 week to complete full scope"
_DEFAULT_SCOPE_EPOXY = (
    "Demo (one layer of) existing flooring and place in a dumpster provided by the owner. "
    "Prepare substrate surface profile utilizing mechanical means (grinding or shot blasting). "
    "Prep substrate cracks and non-moving joints (includes minor floor prep, patching of minor "
    "substrate defects, spalls and divots). Install Epoxy System. Assumes installation over: "
    "clean, sound & solid concrete substrate."
)
_DEFAULT_SCOPE_POLISH = (
    "Demo existing flooring and place in a dumpster. Fill concrete joints with backer rod and "
    "polyurea caulking. Patch minor divots. Grind and polish concrete with successive passes "
    "using finer grit pads for each pass. Apply hardener/densifier & topical sealer. Perform "
    "high-speed burnish. Assumes polish over: clean, sound & solid concrete substrate."
)
# Gyp underlayment (the {{scope_notes}} token isn't in the gyp template, so this is
# defensive/sidebar-coherence only; {{exclusions}} IS a gyp token — its default is
# the underlayment template's verbatim Exclusions line).
_DEFAULT_SCOPE_GYP = (
    "Pour USG Levelrock 2500 Gypsum Floor Topping at 2,500 psi over plywood subfloor / sound "
    "mat as described above, at a uniform thickness & finished to a smooth surface."
)
_DEFAULT_EXCLUSIONS_GYP = (
    "Sealer, Removal of ISO after pour, Credit for unused Mobs, water hook-up, form work, work "
    "on podium level or below, pour stops, pre-pours of tubs/showers or party walls, metal lath "
    "or mesh reinforcements, gyp under any thresholds, stair treads, lightweight conc., "
    "mechanical ventilation, any caulking, any leveling, P&P Bonds, traffic control (provided by "
    "others)."
)

# GC audience narrative fallbacks — the GC templates historically shipped their
# Scope/Schedule/Exclusions as STATIC text (no token), so sidebar edits never
# reached them. annotate_templates.py now tokenizes them ({{scope_notes}},
# {{schedule_notes}}, {{exclusions}}); these constants reproduce the templates'
# ORIGINAL wording verbatim so a blank sidebar re-seeds the exact GC boilerplate.
# Scope steps stack under the bold "Scope:" label via "\n" -> <w:br/>
# (_set_t_multiline in proposal_writer). GC combo has no dedicated template — it
# uses the GC Resinous doc (see proposal_writer.TEMPLATE_PICKER), so epoxy + combo
# both map to the Resinous defaults below.
#
# ⚠ BYTE-IDENTICAL to the frontend catalog in frontend/js/proposal-review.js
# (GC_NARRATIVE_DEFAULTS). Edit BOTH sides together or the mid-draft audience
# re-seed (which matches a field against the other audience's default) breaks.
_DEFAULT_SCOPE_GC_RESINOUS = (
    "Perform relative humidity test on concrete slab prior to installation (if required)\n"
    "Prepare substrate surface profile utilizing mechanical means (grinding or shot blasting)\n"
    "Prep substrate (includes patch of minor substrate defects i.e., cracks, non-moving joints, divots, & spalls*)\n"
    "Install Resinous System  ^Patch material included:  xx gallons/kits.\n"
    "Assumes installation over: clean, sound & solid concrete substrate"
)
_DEFAULT_SCOPE_GC_POLISH = (
    "Prep substrate (includes patching of minor substrate defects i.e., cracks, divots, & spalls*)\n"
    "Grind and polish concrete with successive passes using finer grit pads for each pass\n"
    "Apply hardener/densifier & topical sealer\n"
    "Apply joint filler\n"
    "Assumes polish over: clean, sound & solid NEW concrete substrate"
)
_DEFAULT_SCOPE_GC_SEALER = (
    "Prep substrate (includes patching of minor substrate defects i.e., cracks, divots, & spalls*)\n"
    "Clean Concrete; -or- Perform 1-2 passes with planetary grinder -or- auto scrubber\n"
    "Apply [1 coat -or- up to 2 coats of clear concrete sealer\n"
    "Assumes sealer over: clean, sound & solid concrete substrate"
)
_DEFAULT_SCHEDULE_GC = (
    "[ 1 mob/phase ] Assumes all areas available at one time, approx. 1week to complete full scope"
)
_DEFAULT_EXCLUSIONS_GC_RESINOUS = (
    "Epoxy Paint Walls, Wall Patching (as may be reqr’d for new base), Demo of Existing "
    "Floor/Glue/Etc. (new slab), Excessive Patching (see exclusion detail below*), Nights & Weekends"
)
_DEFAULT_EXCLUSIONS_GC_POLISH = (
    "Cove Base, Dye, Demo of Existing Floor/Glue/Etc. (new slab), Excessive Patching (no more than "
    "1 bag per 1,000 sf, see exclusion detail below*), Removal of Existing Joint Filler (if any), "
    "Nights & Weekends"
)
_DEFAULT_EXCLUSIONS_GC_SEALER = (
    "Patching, Grinding, Joint Filler (see option), Polishing of Concrete, Cove Base, Dye, Demo of "
    "Existing Floor/Glue/Etc. (new slab), Excessive Patching / Grinding (no more than 1 bag per "
    "1,000 sf, see exclusion detail below*), Mock-Up, Nights & Weekends, Removal of Existing Joint "
    "Filler (if any)"
)


def _ensure_value_aliases(values: Dict[str, Any], audience=None) -> None:
    """Backfill blank token aliases / fallbacks in-place so the proposal never
    emits a raw {{token}} (e.g. job_name <- project_name, work_description <-
    address, site_visit_date <- bid date)."""
    for target, source in _VALUE_ALIASES:
        if _blank(values.get(target)) and not _blank(values.get(source)):
            values[target] = values[source]
    for target, sources in _VALUE_FALLBACKS:
        if _blank(values.get(target)):
            values[target] = next(
                (values[s] for s in sources if not _blank(values.get(s))), ""
            )
    # Audience-aware narrative fallbacks. GC jobs get the GC templates' verbatim
    # Scope/Schedule/Exclusions (keyed by work_type, mirroring pick_template:
    # polish -> GC Polish, sealer -> GC Sealer, epoxy/combo/anything else -> GC
    # Resinous). Non-GC keeps today's Direct wording BYTE-IDENTICAL.
    is_gc = str(audience or values.get("audience") or "").strip().upper() == "GC"
    _wt = str(values.get("work_type") or "epoxy").lower()
    if _wt == "gyp":
        # Gyp uses ONE underlayment template regardless of audience.
        _scope_def, _excl_def, _sched_def = _DEFAULT_SCOPE_GYP, _DEFAULT_EXCLUSIONS_GYP, _DEFAULT_SCHEDULE
        # Gyp-only template tokens — backfill so generate never leaks a raw token
        # (frontend computeTokenValues normally supplies the SFs; these are the
        # defensive fallbacks + the fields the frontend doesn't compute).
        def _sf(v):
            s = str(v if v is not None else "").replace(",", "").strip()
            try:
                return f"{int(round(float(s))):,}" if s else "0"
            except (TypeError, ValueError):
                return s or "0"
        for _t in ("gyp_soft_sf", "gyp_hard_sf", "gyp_corridor_sf"):
            if _blank(values.get(_t)):
                values[_t] = _sf(values.get(_t))
        _thk = {"gyp_soft_thickness": '3/4"', "gyp_hard_thickness": '1"', "gyp_corridor_thickness": '3/4"'}
        for _t, _d in _thk.items():
            if _blank(values.get(_t)):
                values[_t] = _d
        if _blank(values.get("mobilizations_line")):
            values["mobilizations_line"] = "1 Mobilization to Site."
        # Gyp has no work_description input, so the generic address-alias (set
        # above) would leak the address into the spec line — force the gyp default
        # (the estimator refines the actual spec/drawings line in the doc editor).
        values["work_description"] = "per plans & specifications provided"
    elif is_gc:
        if _wt == "polish":
            _scope_def, _excl_def = _DEFAULT_SCOPE_GC_POLISH, _DEFAULT_EXCLUSIONS_GC_POLISH
        elif _wt == "sealer":
            _scope_def, _excl_def = _DEFAULT_SCOPE_GC_SEALER, _DEFAULT_EXCLUSIONS_GC_SEALER
        else:  # epoxy / combo / fallback -> GC Resinous (mirrors pick_template)
            _scope_def, _excl_def = _DEFAULT_SCOPE_GC_RESINOUS, _DEFAULT_EXCLUSIONS_GC_RESINOUS
        _sched_def = _DEFAULT_SCHEDULE_GC
    else:
        _scope_def = _DEFAULT_SCOPE_POLISH if _wt == "polish" else _DEFAULT_SCOPE_EPOXY
        _excl_def = _DEFAULT_EXCLUSIONS
        _sched_def = _DEFAULT_SCHEDULE
    if _blank(values.get("exclusions")):
        values["exclusions"] = _excl_def
    if _blank(values.get("schedule_notes")):
        values["schedule_notes"] = _sched_def
    if _blank(values.get("scope_notes")):
        values["scope_notes"] = _scope_def
    # WORK "Notes:" line ({{work_notes}} in the Direct epoxy/polish + gyp WORK
    # sections) — an editable per-job note (e.g. VCT "ghosting" warnings). Always
    # coerce to a string so the line renders "Notes:" with NO raw token even when
    # the estimator left it blank; they fill it from the fields sidebar.
    values["work_notes"] = str(values.get("work_notes") or "")
    # Header date token: M/D/YY from the ISO bid_date — backfilled so a caller that
    # omits the pre-formatted value (e.g. the "View files" rebuild path) can't leak
    # a raw {{bid_date_formatted}} into the customer-facing proposal.
    if _blank(values.get("bid_date_formatted")):
        _bd = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(values.get("bid_date") or "").strip())
        if _bd:
            _y, _mo, _d = _bd.groups()
            values["bid_date_formatted"] = f"{int(_mo)}/{int(_d)}/{_y[2:]}"


@app.get("/api/default-notes")
def api_default_notes(work_type: str = "epoxy") -> Dict[str, Any]:
    """Standard proposal NOTES for a work type — the frontend pre-fills the
    editable Notes box with these so the estimator can tweak them per job."""
    wt = str(work_type or "epoxy").lower()
    return {"work_type": wt, "notes": _DEFAULT_NOTES.get(wt) or _DEFAULT_NOTES.get("epoxy") or []}


@app.get("/api/proposal-template")
def api_proposal_template(request: Request, work_type: str = "epoxy", audience: str = "Direct") -> Response:
    """The REAL proposal template, as an ordered list of editable blocks, for
    Proposal Review's document editor (replaces the old hand-built HTML
    approximation — the estimator now edits the actual .docx text/layout).

    `id` is that paragraph's index in `proposal_writer.iter_editable_blocks` —
    the SAME walk `/api/generate` uses (via `_apply_paragraph_overrides`) to
    resolve `paragraph_overrides` back onto the pristine template, so an id
    from this response always lands on the exact right paragraph as long as
    the template file itself hasn't changed (see `_template_version`, echoed
    here as `template_version` so the frontend can detect a stale cached id
    set after a deploy).

    `in_block` marks paragraphs inside a repeatable/priced region
    (price_line, single_bid, remodel, tax_breakout, has_options, system,
    room, alternate, notes) — the frontend renders those read-only (driven by
    the pricing sidebar + engine), never as freely-editable text.

    Fidelity metadata (so the editor looks like the Word file, not an
    approximation): per-block `align`/`list` flags + `runs` (formatted
    segments — bold lead-ins, Zetta Serif sizes/colors; tokens isolated per
    segment, see proposal_writer._block_runs), per-block `txbx` (which
    floating text box it lives in), and a top-level `geometry` payload (page
    size/margins, each box's page position, and the anchored letterhead
    artwork — served by /api/proposal-template/media).
    """
    template_path = proposal_writer.pick_template(work_type, audience or None)
    if not template_path.exists():
        raise HTTPException(404, f"Proposal template not found: {template_path.name}")

    d = docx.Document(str(template_path))
    blocks = []
    for idx, kind, p_elem, in_block, text, txbx_idx in proposal_writer.iter_editable_blocks(d):
        p = Paragraph(p_elem, d)
        style_name = None
        try:
            style_name = p.style.name if p.style is not None else None
        except Exception:  # noqa: BLE001 — a style lookup failure is cosmetic only
            style_name = None
        bold = any(r.bold for r in p.runs if r.bold is not None)
        blocks.append({
            "id": idx,
            "kind": kind,
            "text": text,
            "style": {"name": style_name, "bold": bold},
            "in_block": in_block,
            # Floating-text-box membership: True/False kept for callers that
            # only care front-page-vs-body; `txbx` pairs the block with its
            # box's geometry. Display placement only — ids are unaffected.
            "in_txbx": txbx_idx is not None,
            "txbx": txbx_idx,
            "align": proposal_writer._para_align(p),
            "list": proposal_writer._para_is_list(p_elem),
            # PRICE-list rows (numId=3) get their bullets stripped at generate
            # time (_flatten_price_bullets); flag them so the on-screen editor
            # renders them flush/bullet-less to match the generated .docx.
            "price_flat": proposal_writer._para_price_list(p_elem),
            "runs": proposal_writer._block_runs(p_elem, p),
        })

    payload = {
        "work_type": work_type,
        "audience": audience,
        "template_name": template_path.name,
        "template_version": _template_proposal_version(template_path),
        "geometry": proposal_writer.template_geometry(d),
        "blocks": blocks,
    }
    return _versioned_json(request, payload,
                           version=f"{work_type}:{audience}:{payload['template_version']}:s{_BLOCK_SCHEMA_VERSION}")


# Media (letterhead artwork) served straight out of the template package.
# Kyle's templates bake the entire page design — buffalo logo, DATE:/JOB
# NAME: labels, the red PROPOSAL stamp, the bordered WORK/PRICE/NOTES/
# ACCEPTANCE frame with its rotated labels — into full-page PNGs under
# word/media/, so rendering these behind the text gives the editor the exact
# printed look with no hand-drawn approximation.
_MEDIA_CONTENT_TYPES = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "bmp": "image/bmp", "tiff": "image/tiff",
    "emf": "image/emf", "wmf": "image/wmf", "svg": "image/svg+xml",
}


@app.get("/api/proposal-template/media")
def api_proposal_template_media(request: Request, work_type: str = "epoxy",
                                audience: str = "Direct", name: str = "") -> Response:
    """One media part (by basename) from the picked template's package.
    Whitelisted against the package's own word/media/ listing — a crafted
    `name` can't reach any other part (no separators survive the basename
    match), and unknown names 404."""
    import zipfile
    template_path = proposal_writer.pick_template(work_type, audience or None)
    if not template_path.exists():
        raise HTTPException(404, f"Proposal template not found: {template_path.name}")
    try:
        with zipfile.ZipFile(str(template_path)) as z:
            allowed = {n.rsplit("/", 1)[-1]: n for n in z.namelist()
                       if n.startswith("word/media/") and "/" not in n[len("word/media/"):]}
            part = allowed.get(name)
            if not part:
                raise HTTPException(404, "No such media in this template")
            data = z.read(part)
    except zipfile.BadZipFile as exc:
        raise HTTPException(500, "Template package is unreadable.") from exc
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    ctype = _MEDIA_CONTENT_TYPES.get(ext, "application/octet-stream")
    version = f"{work_type}:{audience}:{name}:{_template_proposal_version(template_path)}"
    etag = 'W/"' + hashlib.md5(version.encode()).hexdigest()[:16] + '"'
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if etag in (request.headers.get("if-none-match") or ""):
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type=ctype, headers=headers)


# Block-model SCHEMA version for /api/proposal-template's ETag. The template
# ETag is otherwise keyed on the .docx mtime, so a CODE change to the block
# dict (new fields, changed semantics) wouldn't bust a browser's cached
# response — it would 304 and keep rendering stale blocks. BUMP THIS whenever
# the block shape changes. v2: added `price_flat` (flush/bullet-less PRICE rows).
_BLOCK_SCHEMA_VERSION = "2"


def _template_proposal_version(path: Path) -> str:
    """Cache-busting token for a proposal template file (mtime) — a deploy
    that changes the .docx changes this, matching `_template_version`'s
    pattern for the estimate sheet."""
    try:
        return str(path.stat().st_mtime_ns)
    except OSError:
        return "0"


@app.post("/api/generate", response_model=GenerateOut)
def api_generate(payload: GenerateIn, request: Request) -> GenerateOut:
    """Final generate: fill xlsx + docx, return download links (xlsx / docx /
    on-demand pdf). The estimator downloads + files them manually."""
    values = payload.values
    _ensure_state_name(values)
    # payload.work_type is authoritative; make sure it's in `values` so the
    # audience/work_type-keyed narrative fallback (_ensure_value_aliases) can't
    # mismatch the picked template when a caller omits work_type from values.
    values.setdefault("work_type", payload.work_type)
    _ensure_value_aliases(values, payload.audience)

    # The epoxy PRICE block itemizes Base Bid + Material Sales Tax. The frontend
    # fills these from the bid; backfill for any caller that doesn't so the
    # template never shows a raw token (Base Bid falls back to the flooring total,
    # Material Sales Tax to $0.00).
    if not str(values.get("base_bid_formatted") or "").strip():
        values["base_bid_formatted"] = (values.get("lump_sum_formatted")
                                        or values.get("total_formatted") or "")
    if not str(values.get("material_tax_formatted") or "").strip():
        values["material_tax_formatted"] = "$0.00"

    # Site-visit phrase (epoxy template uses {{site_visit_phrase}}): "per site visit
    # on <date>", or "per plans and specifications provided" when there was no site
    # visit — explicit toggle, or a blank / N/A date (Kyle: no more "per site visit on N/A").
    _sv = str(values.get("site_visit_date") or "").strip()
    if values.get("no_site_visit") or not _sv or _sv.upper() == "N/A":
        values["site_visit_phrase"] = "per plans and specifications provided"
    else:
        values["site_visit_phrase"] = f"per site visit on {_sv}"

    # When the estimator marked ≥1 shown option, the proposal shows the base via
    # {{#single_bid}} and each option relative to it. Force the displayed base total
    # from the base room so the printed base EQUALS the deduct denominator
    # (savings = base_total − option_total). Runs before the PRICE layout so the
    # tax block below derives base_bid_formatted from the corrected total.
    _base_room = next((r for r in (payload.rooms or [])
                       if isinstance(r, dict) and r.get("is_base")), None)
    _has_shown_options = any(
        isinstance(r, dict) and not r.get("is_base") and r.get("show", True)
        and float((r.get("bid") or {}).get("total") or 0) > 0
        for r in (payload.rooms or []))
    if _base_room and _has_shown_options:
        try:
            _btf = _fmt_usd(float((_base_room.get("bid") or {}).get("total")))
            if _btf:
                values["total_formatted"] = _btf
        except (TypeError, ValueError):
            pass

    # PRICE layout. Default ("INCLUDED") = a single all-in line:
    #   "$Total – … (material sales tax INCLUDED)"  (remodel folded into the total)
    # "Sales tax broken out" itemizes Base + Material Sales Tax + Remodel + Total
    # and drops the "(… INCLUDED)" label. "Tax exempt" = one line, "(tax exempt)".
    _incl = str(values.get("tax_inclusion") or "INCLUDED").strip().upper()
    _exempt = _incl in ("EXCLUDED", "EXEMPT", "NOT INCLUDED", "NONE", "NO", "N/A")
    _broken = _incl in ("BROKEN_OUT", "BROKEN OUT", "BROKENOUT", "ITEMIZED", "BREAKOUT")
    # Gyp always itemizes (its template shows Base + Material Sales Tax + Kansas
    # Remodel Tax + Total as flat rows), so never collapse base_bid_formatted to
    # the total for gyp — keep the pre-tax base the frontend computed.
    if str(values.get("work_type") or "").lower() == "gyp":
        _broken = True
    if _broken:
        # Itemized: keep the frontend's pre-tax base + Material Sales Tax + Total;
        # remodel shows as its own line; no "INCLUDED" label on the base line.
        values["base_tax_phrase"] = ""
        _tax_breakout = True
        _remodel_lines = list(payload.remodel or [])
    else:
        # One all-in line: the base line carries the FULL total; remodel folds in.
        if str(values.get("total_formatted") or "").strip():
            values["base_bid_formatted"] = values["total_formatted"]
        _tax_breakout = False
        _remodel_lines = []
        values["base_tax_phrase"] = (
            "(tax exempt)" if _exempt
            else "(Remodel Tax AND material sales tax INCLUDED)" if payload.remodel
            else "(material sales tax INCLUDED)"
        )

    # Combo WORK lists the real picked epoxy system as "Option 1: <name>" (from
    # the Epoxy!A22 dropdown), falling back to the generic label.
    if not str(values.get("epoxy_system_name") or "").strip():
        a22 = str(payload.cell_values.get("Epoxy!A22") or "").strip()
        values["epoxy_system_name"] = a22 if (a22 and "Options" not in a22) else "Epoxy System"

    # Sign the proposal with the logged-in estimator (the templates' old
    # hardcoded "Troy Holmes" is now the {{estimator_name}} token). The frontend
    # sets this from the signed-in user; backfill here so it's never blank or a
    # raw token if a caller (e.g. "View files") omits it.
    if not str(values.get("estimator_name") or "").strip():
        nm = ""
        try:
            claims = supabase_client.verify_token_claims(request.headers.get("authorization"))
            meta = claims.get("user_metadata") or {}
            nm = (meta.get("full_name") or meta.get("name") or "").strip()
        except Exception:  # noqa: BLE001
            nm = ""
        if not nm:
            em = (_user_email(request) or "").strip()
            if em:
                nm = em.split("@")[0].replace(".", " ").replace("_", " ").title()
        if nm:
            values["estimator_name"] = nm

    # Doc-editor per-line DISPLAY overrides for the PRICE section (display TEXT
    # only — never touches cell_values, the .xlsx, or the totals; see
    # _sanitize_price_overrides). Applied to the manual price lines + option lines
    # below, and to the single_bid base amount/tax phrase after the tax layout.
    _pov = _sanitize_price_overrides(payload.price_overrides)

    # Structured PRICE option lines -> repeatable {{#price_line}} rows.
    price_line_dicts = []
    for _i, pl in enumerate(payload.price_lines or []):
        label = str((pl or {}).get("label") or "").strip()
        try:
            amt = float((pl or {}).get("amount") or 0)
        except (TypeError, ValueError):
            amt = 0.0
        if label and amt:
            row = {"label": label, "amount_formatted": _fmt_usd(amt)}
            # DISPLAY override for this manual line, positional by the ORIGINAL
            # price_lines index (_i) so a filtered-out row can't shift it onto the
            # wrong line — the frontend stores overrides at that same raw index.
            _mov = _pov["manual"][_i] if _i < len(_pov["manual"]) else None
            if _mov:
                if _mov.get("label"):
                    row["label"] = _mov["label"]
                if _mov.get("amount"):
                    row["amount_formatted"] = _mov["amount"]
            price_line_dicts.append(row)

    # Recommended ALTERNATE system -> a 0/1-item {{#alternate}} block + a second
    # estimate tab. Tax-inclusive total; flooring = total − remodel tax.
    acb = payload.alternate_computed_bid or {}
    alt_fb = acb.get("alternate_full_bid") or {}
    alt_meta = acb.get("alternate") or {}
    alternates = []
    alternate_arg = None
    alt_total = None
    if alt_fb.get("total_base_bid"):
        alt_total = float(alt_fb["total_base_bid"])
        alt_remodel = float(alt_fb.get("remodel_tax") or 0)
        alt_label = (payload.alternate_label or alt_meta.get("label") or "Alternate System").strip()
        alternates = [{
            "system_name": alt_label,
            "lump_sum_formatted": _fmt_usd(alt_total - alt_remodel),
            "remodel_tax": _fmt_usd(alt_remodel),
            "total_formatted": _fmt_usd(alt_total),
        }]
        alternate_arg = {"sf": alt_meta.get("sf"),
                         "material_sub": alt_meta.get("material_sub"),
                         "label": alt_label}

    # Non-base priced options. Render them through the existing {{#price_line}}
    # block (which sits under the "Options:" heading, right after the base bid),
    # so the Direct templates need NO structural change: each option is
    # "$8,310 – <system> as described above (…)" or "($6,000) – Deduct VE … in
    # lieu of <base>". Any per-option notes fold inline. The base bid itself shows
    # via {{#single_bid}}. (GC/Gyp templates lack {{#price_line}} — Phase 2.)
    _options = _build_options(payload.rooms, values, payload.work_type)
    _option_lines = []
    for _o in _options:
        _label = _o["price_desc"]
        if _o.get("notes_joined"):
            _label += " — " + _o["notes_joined"].replace("\n", "; ")
        _amount = _o["price_formatted"]
        # DISPLAY override for this option line, keyed by the option's id.
        _oid = str(_o.get("id") or "")
        _oov = _pov["options"].get(_oid) if _oid else None
        if _oov:
            if _oov.get("label"):
                _label = _oov["label"]
            if _oov.get("amount"):
                _amount = _oov["amount"]
        _option_lines.append({"label": _label, "amount_formatted": _amount})
    # Options first, then the estimator's manual "Add for" price lines.
    price_line_dicts = _option_lines + price_line_dicts

    # Combo per-option breakout (pre-formatted on the frontend): Option 1 (Epoxy) +
    # Option 2 (Polish), each with its own flooring / Kansas Remodel Tax / Total.
    # When present these LEAD the PRICE section and the combined single-bid line is
    # suppressed — the two option totals ARE the base price (per Treadwell's combo
    # proposal format).
    # Coerce with str() BEFORE stripping — a caller can send {"label": 123} or
    # {"label": {"a": 1}} (bad client state, a stale draft, a hand-built request);
    # calling .strip() on the raw value first raised AttributeError and 500'd the
    # whole endpoint. Cap the list too: it drives one deep-copied paragraph set
    # per entry in the docx, and nothing legitimate ever sends more than a handful.
    _combo_lines = []
    for c in (payload.combo_options or [])[:50]:
        if not isinstance(c, dict):
            continue
        label = str(c.get("label") or "").strip()
        amount_formatted = str(c.get("amount_formatted") or "").strip()
        if label or amount_formatted:
            _combo_lines.append({"label": label, "amount_formatted": amount_formatted})
    if _combo_lines:
        # The combined single-bid line is suppressed below (single_bid=[]), but
        # the template's "Options:" heading is a {{#has_options}} block that
        # lives NESTED INSIDE {{#single_bid}} — suppressing single_bid also
        # deletes it. If there are extra option/manual price lines after the
        # combo breakout, restore the heading as a label-only price_line row
        # (empty amount_formatted, stripped of its dash separator in
        # proposal_writer._strip_leading_separator) so those lines aren't
        # visually indistinguishable from the combo base price. Skip it when
        # there's nothing after the breakout — an empty "Options:" would have
        # nothing to introduce.
        if price_line_dicts:
            _combo_lines = _combo_lines + [{"label": "Options:", "amount_formatted": ""}]
        price_line_dicts = _combo_lines + price_line_dicts

    # The {{#room}} block is unused now (options ride the price_line block) — strip it.
    rooms_arg = []

    # Base bid shows via {{#single_bid}} — EXCEPT when the combo breakout supplies its
    # own Option 1/Option 2 base lines, in which case suppress the combined line.
    _single_bid = [] if _combo_lines else None

    # "Options:" label prints when there ARE option lines; else it's stripped.
    _has_options = bool(price_line_dicts)

    # Doc-editor DISPLAY overrides for the base bid line (single_bid): the shown
    # base AMOUNT and the tax phrase. Applied last so they win over the tax-layout
    # defaults set above. The Total / Material Sales Tax / Remodel rows stay
    # engine-computed — only the base line's own display text is overridable.
    # (Combo suppresses single_bid, so these no-op there — combo stays read-only.)
    if _pov["single_bid"].get("amount"):
        values["base_bid_formatted"] = _pov["single_bid"]["amount"]
    if _pov["single_bid"].get("tax_phrase"):
        values["base_tax_phrase"] = _pov["single_bid"]["tax_phrase"]
    # The base line's DESCRIPTION (the noun between the amount and the tax phrase,
    # e.g. "Epoxy flooring as described above") is static text in each template,
    # not a token — so proposal_writer replaces it in place at fill time. Passed
    # via a private (underscore) key so the flat {{token}} pass ignores it. Only
    # set when overridden: absent → each template keeps its own wording (no
    # per-template default to drift, no regression for GC/Gyp variants).
    if _pov["single_bid"].get("desc"):
        values["_base_desc_override"] = _pov["single_bid"]["desc"]
    # GC additional-phase amount: force the estimator's cell value into the GC
    # Clarifications text ONLY when they changed it off the $4,500 default; else
    # each GC template keeps its native $5,000/$2,300 wording. Private (underscore)
    # key so the flat {{token}} pass ignores it (proposal_writer._apply_gc_phase_override
    # rewrites the static clause in place). Direct proposals are unaffected — they
    # track the cell through the {{#notes}} "$xxxx" bullet instead.
    _ppo = _phase_price_override_amount((payload.values or {}).get("phase_price"))
    if _ppo:
        values["_phase_price_override"] = _ppo

    # Fill estimate workbook
    try:
        xlsx_bytes = estimate_writer.fill_estimate(
            values,
            cell_values=payload.cell_values,
            extras=payload.extras,
            alternate=alternate_arg,
            tab_copies=payload.tab_copies,
            tab_labels=payload.tab_labels,
            tab_order=payload.tab_order,
            tab_structs=payload.tab_structs,
            lock_overrides=payload.lock_overrides,
        )
    except Exception as exc:
        log.exception("Estimate fill failed")
        raise HTTPException(500, "Failed to generate the estimate. Please try again.") from exc

    # Version guard for the document editor's paragraph_overrides. Their ids are
    # positions in iter_editable_blocks over a SPECIFIC template file; a re-annotation
    # (e.g. the GC Scope/Schedule/Exclusions tokenization) shifts those ids, so a
    # draft captured against the old template could land an edit on the wrong
    # paragraph. If the client echoed a template_version and it no longer matches the
    # current template, drop the overrides (fail-safe). Empty = legacy caller = apply.
    _cur_template_version = _template_proposal_version(
        proposal_writer.pick_template(payload.work_type, payload.audience or None))
    _para_overrides = payload.paragraph_overrides
    if payload.template_version and payload.template_version != _cur_template_version:
        log.warning(
            "Dropping %d paragraph_override(s): stale template_version %r != current %r",
            len(_para_overrides or []), payload.template_version, _cur_template_version)
        _para_overrides = []

    # Fill proposal document
    try:
        # Epoxy WORK section lists each picked system as its own row (1 system →
        # "System: …", 2+ → "Option 1/2: …") via the template's {{#system}} block.
        systems_arg = (_build_epoxy_systems(payload.cell_values, values,
                                             _sanitize_sheet_systems(payload.sheet_systems))
                       if str(payload.work_type or "").lower() == "epoxy" else None)
        # Doc-editor DISPLAY overrides for the WORK rows, applied by option index
        # over the computed systems. `prefix`/`lf_clause` stay computed; nothing
        # here touches cell_values or the price — display text only. Ignored for
        # non-epoxy (systems_arg is None there).
        if systems_arg:
            for i, ov in enumerate(_sanitize_system_overrides(payload.system_overrides)):
                if i >= len(systems_arg):
                    break
                systems_arg[i].update(ov)
        docx_bytes = proposal_writer.fill_proposal(
            work_type=payload.work_type,
            audience=payload.audience,
            values=values,
            price_lines=price_line_dicts,
            alternates=alternates,
            systems=systems_arg,
            remodel=_remodel_lines,
            rooms=rooms_arg,
            # Base shows via {{#single_bid}} normally; suppressed for the combo
            # breakout (its Option 1/Option 2 lines are the base price).
            single_bid=_single_bid,
            # Editable NOTES (estimator's edits, else standard boilerplate).
            notes=_notes_for(payload.work_type, payload.notes, (payload.values or {}).get("phase_price")),
            # PRICE layout: itemize tax lines only when "broken out"; show the
            # "Options:" label only when options exist.
            tax_breakout=_tax_breakout,
            has_options=_has_options,
            # Proposal Review's document editor: free-text paragraph edits
            # outside the priced/repeatable regions (see /api/proposal-template).
            # Version-guarded above (stale template_version -> dropped).
            paragraph_overrides=_sanitize_paragraph_overrides(_para_overrides),
        )
    except FileNotFoundError as exc:
        raise HTTPException(500, str(exc)) from exc
    except Exception as exc:
        log.exception("Proposal fill failed")
        raise HTTPException(500, "Failed to generate the proposal. Please try again.") from exc

    project_name = (values.get("project_name") or "Untitled Project").strip()

    # Cache files for download (Done screen download buttons hit /api/file/{token}).
    # The docx token doubles as the PDF source: /api/file/{docx_token}/pdf renders
    # it on demand via LibreOffice.
    safe_name = (project_name or "proposal").replace(" ", "_")[:80]
    xlsx_token = _cache_file(
        xlsx_bytes,
        f"{safe_name}_estimate.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    docx_token = _cache_file(
        docx_bytes,
        f"{safe_name}_proposal.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    # Audit trail: who generated this proposal, for what, and where it landed.
    fb = (payload.computed_bid or {}).get("full_bid") or {}
    drafts.log_event(
        request.headers.get("x-project-id"),
        _user_email(request),
        "generated",
        {
            "project_name": project_name,
            "total": fb.get("total_base_bid"),
            "alternate_total": alt_total,
            "alternate_label": (alternates[0]["system_name"] if alternates else None),
            "price_lines_count": len(price_line_dicts),
            "work_type": payload.work_type,
            "audience": payload.audience,
        },
    )

    # Persist the generated proposal as a SAVED PROJECT so it appears in the
    # unified, domain-wide Projects list for everyone (not just whoever was
    # mid-edit). Normal flow already autosaved the draft while editing; this is
    # belt-and-suspenders so a proposal is never generated without a visible
    # project. Keyed on the draft id (X-Project-Id); non-fatal on failure.
    draft_id = (request.headers.get("x-project-id") or "").strip()
    if draft_id and draft_id != "no-draft":
        try:
            # MERGE onto the existing draft data — never DROP fields the payload
            # doesn't carry. Critically preserves proposal_payload / generate_result
            # (the step-5 "To Dropbox" re-upload + the portal PDF read them back);
            # a plain replace here wiped them, breaking re-generation server-side.
            existing = (drafts.load_draft(draft_id) or {}).get("data") or {}
            proj_data = {**existing, **dict(values)}
            proj_data["work_type"] = payload.work_type
            proj_data.setdefault("project_name", project_name)
            if payload.computed_bid:
                proj_data["computed_bid"] = payload.computed_bid
            drafts.save_draft(draft_id, proj_data, owner_email=_user_email(request))
        except Exception as exc:  # noqa: BLE001 — never block the download
            log.warning("generate: project save failed: %s", exc)

    return GenerateOut(
        work_type=payload.work_type,
        audience=payload.audience,
        xlsx_download_url=f"/api/file/{xlsx_token}",
        docx_download_url=f"/api/file/{docx_token}",
        pdf_download_url=f"/api/file/{docx_token}/pdf",
        # Authoritative totals from the 5.7-recipe engine (computed on
        # Screen 2 and passed through). Falls back to an empty dict if a
        # caller generated without first running the pricing engine.
        totals=payload.computed_bid or {},
    )


@app.get("/api/file/{token}")
def api_get_file(token: str) -> Response:
    """One-time-ish file download (cached in-memory for the session)."""
    entry = _FILE_CACHE.get(token)
    if not entry:
        raise HTTPException(404, "File expired or already downloaded")
    # HTTP headers are latin-1 only, so a filename with non-ASCII chars (em-dash,
    # accents — common in project names) would 500 the response. Send an ASCII
    # fallback `filename=` plus an RFC 5987 UTF-8 `filename*` for real browsers.
    fname = entry["filename"]
    ascii_name = re.sub(r"[^\x20-\x7e]", "_", fname).replace('"', "'")
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(fname)}"
    return Response(
        content=entry["content"],
        media_type=entry["content_type"],
        headers={"Content-Disposition": disposition},
    )


@app.get("/api/file/{token}/pdf")
def api_get_file_pdf(token: str) -> Response:
    """Render a cached .docx proposal to PDF on demand (LibreOffice headless).

    Lazy by design: the PDF isn't built at generate time (keeps Generate fast),
    only when someone clicks "Download as PDF". The result is memoized on the
    cache entry so repeat clicks are instant. Public like /api/file/{token}
    (the token is the capability)."""
    entry = _FILE_CACHE.get(token)
    if not entry:
        raise HTTPException(404, "File expired or already downloaded")
    if not str(entry["filename"]).lower().endswith(".docx"):
        raise HTTPException(400, "Only .docx files can be converted to PDF")

    pdf_bytes = entry.get("_pdf")
    if pdf_bytes is None:
        try:
            with _PDF_RENDER_SEM:   # cap concurrent LibreOffice renders
                pdf_bytes = pdf_writer.docx_to_pdf(entry["content"])
        except Exception as exc:  # noqa: BLE001
            log.exception("PDF conversion failed")
            raise HTTPException(500, "Failed to render the PDF. Please try again.") from exc
        entry["_pdf"] = pdf_bytes   # memoize for repeat downloads

    fname = re.sub(r"\.docx$", ".pdf", str(entry["filename"]), flags=re.IGNORECASE)
    ascii_name = re.sub(r"[^\x20-\x7e]", "_", fname).replace('"', "'")
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(fname)}"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": disposition},
    )


# ─── Project persistence (Supabase) ───────────────────────────────────
# Multi-device autosave: the frontend POSTs the whole state blob here every
# few seconds, keyed by a UUID in the URL (?d=<uuid>). Stored in Supabase so
# every signed-in user shares one unified project list. See drafts.py.
class DraftIn(BaseModel):
    data: Dict[str, Any] = Field(default_factory=dict)


class ArchiveIn(BaseModel):
    archived: bool = True


@app.on_event("startup")
def _init_drafts_db() -> None:
    try:
        drafts.init_db()
        log.info("Drafts DB ready")
    except Exception as exc:  # noqa: BLE001
        log.warning("Drafts DB init failed (drafts disabled): %s", exc)


@app.on_event("startup")
def _warm_sheet_cache() -> None:
    """Pre-build + cache the heavy grids in a background thread so the first
    real user after a deploy doesn't pay the ~7 s cold serialization cost.
    Runs off-thread so it never blocks startup / the health check.
    """
    import threading

    def _warm() -> None:
        for name in ("Epoxy", "Polish", 'Gyp (USG 1-8")'):
            try:
                estimate_writer.read_sheet_grid(name)  # populates _SHEET_GRID_CACHE
                log.info("Warmed sheet cache: %s", name)
            except Exception as exc:  # noqa: BLE001
                log.warning("Sheet warm failed for %s: %s", name, exc)

    threading.Thread(target=_warm, daemon=True).start()


@app.put("/api/draft/{draft_id}")
@app.post("/api/draft/{draft_id}")
def api_save_draft(draft_id: str, payload: DraftIn, request: Request) -> Dict[str, Any]:
    """Upsert a draft's full state blob. Called on a debounce as the
    estimator types — so a tab close / device switch doesn't lose work.
    Stamps the signed-in user as the project owner on first save."""
    try:
        return {"ok": True, **drafts.save_draft(draft_id, payload.data,
                                                owner_email=_user_email(request))}
    except Exception as exc:  # noqa: BLE001
        log.warning("save_draft failed: %s", exc)
        return {"ok": False, "error": str(exc)}


@app.get("/api/draft/{draft_id}")
def api_load_draft(draft_id: str) -> Dict[str, Any]:
    """Fetch a draft by id. 404 if it doesn't exist (fresh draft id)."""
    row = drafts.load_draft(draft_id)
    if row is None:
        raise HTTPException(404, "Draft not found")
    return {"ok": True, **row}


@app.delete("/api/draft/{draft_id}")
def api_delete_draft(draft_id: str, request: Request, permanent: bool = False) -> Dict[str, Any]:
    """Delete a project. Default = soft-delete (moves it to Trash, restorable).
    `?permanent=true` = hard delete (used by 'Delete forever' from the Trash
    page). Any signed-in user can manage the shared list."""
    actor = _user_email(request)
    if permanent:
        existed = drafts.delete_draft(draft_id)
        if existed:
            drafts.log_event(draft_id, actor, "purged_project", {"id": draft_id})
        return {"ok": True, "existed": existed, "permanent": True}
    existed = drafts.trash_draft(draft_id, actor)
    return {"ok": True, "existed": existed, "trashed": True}


@app.post("/api/draft/{draft_id}/restore")
def api_restore_draft(draft_id: str, request: Request) -> Dict[str, Any]:
    """Restore a soft-deleted project from Trash back to the active list."""
    existed = drafts.restore_draft(draft_id, _user_email(request))
    return {"ok": True, "existed": existed}


@app.post("/api/draft/{draft_id}/archive")
def api_archive_draft(draft_id: str, payload: ArchiveIn, request: Request) -> Dict[str, Any]:
    """Mark a project active/inactive for the Projects-tab active/inactive
    filter. `{"archived": true}` = inactive; `false` = active. Any signed-in
    user can manage the shared list."""
    try:
        existed = drafts.set_archived(draft_id, payload.archived, _user_email(request))
        return {"ok": True, "existed": existed, "archived": payload.archived}
    except Exception as exc:  # noqa: BLE001
        log.warning("set_archived failed: %s", exc)
        return {"ok": False, "error": str(exc)}


@app.get("/api/drafts")
def api_list_drafts() -> Dict[str, Any]:
    """Unified ACTIVE project list (all users) for the Projects dashboard."""
    try:
        return {"ok": True, "projects": drafts.list_drafts()}
    except Exception as exc:  # noqa: BLE001
        log.warning("list_drafts failed: %s", exc)
        return {"ok": False, "error": str(exc), "projects": []}


@app.get("/api/trash")
def api_list_trash() -> Dict[str, Any]:
    """Soft-deleted projects for the Trash page (all users, newest-trashed first)."""
    try:
        return {"ok": True, "projects": drafts.list_trashed()}
    except Exception as exc:  # noqa: BLE001
        log.warning("list_trashed failed: %s", exc)
        return {"ok": False, "error": str(exc), "projects": []}


@app.get("/api/history")
def api_history() -> Dict[str, Any]:
    """Recent activity (who created / generated each proposal) for History."""
    try:
        return {"ok": True, "events": drafts.list_events()}
    except Exception as exc:  # noqa: BLE001
        log.warning("list_events failed: %s", exc)
        return {"ok": False, "error": str(exc), "events": []}


@app.get("/api/notifications")
def api_notifications() -> Dict[str, Any]:
    """Notification-bell feed: proposal deadlines (overdue / due today / due soon /
    no deadline) + Basisboard pipeline changes, with a global unread count."""
    try:
        return {"ok": True, **notifications.get_notifications()}
    except Exception as exc:  # noqa: BLE001
        log.warning("notifications failed: %s", exc)
        return {"ok": False, "error": str(exc), "notifications": [], "unread": 0}


@app.post("/api/notifications/seen")
def api_notifications_seen(request: Request) -> Dict[str, Any]:
    """Mark the whole feed as seen (global/shared last-seen) — clears the badge."""
    try:
        notifications.mark_seen(_user_email(request))
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        log.warning("notifications seen failed: %s", exc)
        return {"ok": False, "error": str(exc)}


class ToDropboxIn(BaseModel):
    draft_id: str
    destination: str   # "gyp" | "plans_specs" | "commercial"


@app.post("/api/to-dropbox")
def api_to_dropbox(payload: ToDropboxIn, request: Request) -> Dict[str, Any]:
    """Step 5 'To Dropbox': create the project folder in the chosen Treadwell
    Estimating folder and upload the estimate .xlsx + proposal .docx + PDF.

    Regenerates the files from the saved proposal_payload (same pipeline as the
    portal PDF path) so the Dropbox copy always matches the latest estimate +
    proposal. Best-effort — never raises to the user; degrades to a message."""
    base_path = dropbox_client.ESTIMATING_DESTINATIONS.get(payload.destination)
    if not base_path:
        return {"ok": False, "error": "Unknown destination folder."}
    row = drafts.load_draft(payload.draft_id)
    if not row:
        raise HTTPException(404, "Draft not found")
    data = row.get("data") or {}
    pp = data.get("proposal_payload")
    if isinstance(pp, dict) and pp.get("values"):
        gi = GenerateIn(**pp)
    else:
        # Existing/older projects may not carry a stored proposal_payload (never
        # generated through Screen 3, or a prior save dropped it). Reconstruct the
        # generate payload from the draft's saved intake/estimate data so
        # "To Dropbox" still works for them (this is the common existing-project case).
        _list = lambda x: x if isinstance(x, list) else []
        _dict = lambda x: x if isinstance(x, dict) else {}
        vals = {k: v for k, v in data.items() if k not in ("proposal_payload", "generate_result")}
        if not (data.get("cell_values") or vals.get("epoxy_sf") or vals.get("polish_sf") or vals.get("sqft")
                or vals.get("gyp_soft_sf") or vals.get("gyp_hard_sf") or vals.get("gyp_corridor_sf")):
            return {"ok": False, "error": "This project has no estimate yet — open it and generate first."}
        gi = GenerateIn(
            work_type=data.get("work_type") or "epoxy",
            audience=data.get("audience") or "Direct",
            values=vals,
            cell_values=_dict(data.get("cell_values")),
            extras=_list(data.get("extras")),
            computed_bid=(data.get("computed_bid") if isinstance(data.get("computed_bid"), dict) else None),
            rooms=_list(data.get("rooms")),
            tab_copies=_list(data.get("tab_copies")),
            tab_labels=_dict(data.get("tab_labels")),
            tab_order=_list(data.get("tab_order")),
            tab_structs=_list(data.get("tab_structs")),
            lock_overrides=_dict(data.get("lock_overrides")),
        )
    try:
        out = api_generate(gi, request)                    # reuse the full generate pipeline
        xlsx_entry = _FILE_CACHE.get((out.xlsx_download_url or "").rsplit("/", 1)[-1])
        docx_entry = _FILE_CACHE.get((out.docx_download_url or "").rsplit("/", 1)[-1])
        if not xlsx_entry or not docx_entry:
            return {"ok": False, "error": "Couldn't build the files to upload — please try again."}
        pdf_bytes = docx_entry.get("_pdf")
        if pdf_bytes is None:                              # render + memoize like the portal path
            with _PDF_RENDER_SEM:
                pdf_bytes = pdf_writer.docx_to_pdf(docx_entry["content"])
            docx_entry["_pdf"] = pdf_bytes
        vals = gi.values or {}
        result = dropbox_client.upload_project_files(
            project_name=vals.get("project_name") or vals.get("job_name") or "Untitled Project",
            xlsx_bytes=xlsx_entry["content"],
            docx_bytes=docx_entry["content"],
            pdf_bytes=pdf_bytes,
            deadline=vals.get("deadline"),
            bid_date=vals.get("bid_date"),
            work_type=gi.work_type,
            audience=gi.audience,
            base_path=base_path,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("to-dropbox failed: %s", exc)
        return {"ok": False, "error": "Upload failed — please try again."}
    if result.get("configured"):
        _vals = gi.values or {}
        drafts.log_event(payload.draft_id, _user_email(request), "to_dropbox",
                         {"destination": payload.destination,
                          "label": dropbox_client.DESTINATION_LABELS.get(payload.destination),
                          "project_name": _vals.get("project_name") or _vals.get("job_name"),
                          "folder": result.get("folder_path"),
                          "folder_url": result.get("folder_url")})
        # Persist the upload result on the draft so the To-Dropbox page shows the
        # "already filed" (green) state whenever the user comes back to it.
        try:
            cur = (drafts.load_draft(payload.draft_id) or {}).get("data") or {}
            cur["dropbox_result"] = {
                "destination": payload.destination,
                "folder_path": result.get("folder_path"),
                "folder_url": result.get("folder_url"),
                "xlsx_url": result.get("xlsx_url"),
                "docx_url": result.get("docx_url"),
                "pdf_url": result.get("pdf_url"),
            }
            drafts.save_draft(payload.draft_id, cur, owner_email=_user_email(request))
        except Exception as exc:  # noqa: BLE001 — never block the response
            log.warning("to-dropbox: result save failed: %s", exc)
        return {"ok": True, **result}
    return {"ok": False, "error": result.get("error") or "Dropbox isn't configured."}


# ─── Identity + admin (Supabase profiles / roles) ─────────────────────
@app.get("/api/me")
def api_me(request: Request) -> Dict[str, Any]:
    """Current signed-in user (drives the login indicator + Admin link).
    The DB trigger creates profiles on signup; this just reads it, with a
    safe fallback if the row isn't there yet."""
    email = _user_email(request) or ""
    prof = None
    try:
        claims = supabase_client.verify_token_claims(request.headers.get("authorization"))
        meta = claims.get("user_metadata") or {}
        name = meta.get("full_name") or meta.get("name")
        if claims.get("sub"):
            prof = profiles.ensure_profile(claims["sub"], email or claims.get("email"), name)
        else:
            prof = profiles.get_by_email(email)
    except Exception as exc:  # noqa: BLE001
        log.warning("api_me profile resolve failed: %s", exc)
        try:
            prof = profiles.get_by_email(email)
        except Exception:  # noqa: BLE001
            prof = None
    if prof:
        return {"ok": True, "email": prof.get("email"), "name": prof.get("full_name"),
                "role": prof.get("role", "user"), "status": prof.get("status", "active")}
    # Fallback (profile row not created yet) — bootstrap super admin by email.
    role = "super_admin" if email == _SUPER_ADMIN_EMAIL else "user"
    return {"ok": True, "email": email, "name": None, "role": role, "status": "active"}


def _require_admin(request: Request) -> Dict[str, Any]:
    """Resolve the caller's profile and require admin/super_admin; else 403."""
    email = _user_email(request) or ""
    prof = profiles.get_by_email(email)
    if not prof and email == _SUPER_ADMIN_EMAIL:
        prof = {"id": None, "email": email, "role": "super_admin"}
    if not prof or prof.get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin access required.")
    return prof


class RoleIn(BaseModel):
    role: str


class StatusIn(BaseModel):
    status: str


class BanIn(BaseModel):
    reason: str = ""


@app.get("/api/admin/users")
def api_admin_users(request: Request, search: str = "", role: str = "") -> Dict[str, Any]:
    _require_admin(request)
    return {"ok": True, "users": profiles.list_users(search=search, role=role)}


@app.get("/api/admin/stats")
def api_admin_stats(request: Request) -> Dict[str, Any]:
    _require_admin(request)
    return {"ok": True, "stats": profiles.stats()}


@app.patch("/api/admin/users/{user_id}/role")
def api_admin_set_role(user_id: str, payload: RoleIn, request: Request) -> Dict[str, Any]:
    actor = _require_admin(request)
    out = profiles.set_role(actor, user_id, payload.role)
    if out.get("ok"):
        drafts.log_event(None, actor.get("email"), "role_changed",
                         {"target": user_id, "role": payload.role})
    return out


@app.put("/api/admin/users/{user_id}/status")
def api_admin_set_status(user_id: str, payload: StatusIn, request: Request) -> Dict[str, Any]:
    actor = _require_admin(request)
    out = profiles.set_status(actor, user_id, payload.status)
    if out.get("ok"):
        drafts.log_event(None, actor.get("email"), "status_changed",
                         {"target": user_id, "status": payload.status})
    return out


@app.post("/api/admin/users/{user_id}/ban")
def api_admin_ban(user_id: str, payload: BanIn, request: Request) -> Dict[str, Any]:
    actor = _require_admin(request)
    out = profiles.ban_user(actor, user_id, reason=payload.reason)
    if out.get("ok"):
        drafts.log_event(None, actor.get("email"), "banned", {"target": user_id})
    return out


@app.post("/api/admin/users/{user_id}/unban")
def api_admin_unban(user_id: str, request: Request) -> Dict[str, Any]:
    actor = _require_admin(request)
    out = profiles.unban_user(actor, user_id)
    if out.get("ok"):
        drafts.log_event(None, actor.get("email"), "unbanned", {"target": user_id})
    return out


@app.delete("/api/admin/users/{user_id}")
def api_admin_delete(user_id: str, request: Request) -> Dict[str, Any]:
    actor = _require_admin(request)
    out = profiles.delete_user(actor, user_id)
    if out.get("ok"):
        drafts.log_event(None, actor.get("email"), "deleted_user",
                         {"target": user_id, "email": out.get("email")})
    return out


@app.delete("/api/admin/projects/{project_id}")
def api_admin_delete_project(project_id: str, request: Request) -> Dict[str, Any]:
    """Admin: move a project to Trash (soft-delete, audit-logged). It can be
    restored or permanently removed from the Trash page. Files already uploaded
    to Dropbox are NOT affected — this only touches the in-app draft/state."""
    actor = _require_admin(request)
    existed = drafts.trash_draft(project_id, actor.get("email"))
    return {"ok": True, "existed": existed, "trashed": True}


# ─── Static frontend ──────────────────────────────────────────────────
# Serve the 4 HTML pages from ../frontend. Mount AFTER the API routes
# so /api/* takes precedence.
#
# We intentionally disable HTTP caching on the static files because this
# tool is iterating frequently (filename fixes, layout tweaks). A
# browser sitting on a stale done.html would miss the fetch+Blob
# downloader and downloads would still come down with UUID names —
# don't make users hard-refresh every time.
# Frontend dir — handle BOTH layouts:
#   local dev:  backend/main.py + frontend/  → parent.parent/frontend
#   Docker:     /app/main.py   + /app/frontend/ → parent/frontend
_FRONTEND_CANDIDATES = [
    Path(__file__).parent.parent / "frontend",  # local dev
    Path(__file__).parent / "frontend",          # Docker (COPY frontend/ /app/frontend/)
]
FRONTEND_DIR = next(
    (p.resolve() for p in _FRONTEND_CANDIDATES if p.exists()),
    _FRONTEND_CANDIDATES[0].resolve(),
)


class NoCacheStaticFiles(StaticFiles):
    """Serve static files with `Cache-Control: no-store, must-revalidate`
    so the browser always re-fetches HTML/JS/CSS during dev + early
    production. Cheap because the files are tiny."""

    def is_not_modified(self, response_headers, request_headers) -> bool:
        # Disable If-Modified-Since / ETag short-circuit
        return False

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-store, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp


@app.get("/", include_in_schema=False)
def _root(request: Request) -> Response:
    """Home is the Projects dashboard. The intake ("New Project") screen is served
    only when a project is explicitly being created (?new) or edited (?edit) — so
    hitting the bare domain, or an old ?d=… link left in browser history, lands on
    Projects instead of a blank intake form. Must be declared BEFORE the "/" static
    mount so it wins for the exact root path (the mount still serves /index.html and
    every other asset)."""
    q = request.query_params
    if "new" in q or "edit" in q:
        return FileResponse(
            str(FRONTEND_DIR / "index.html"),
            headers={"Cache-Control": "no-store, must-revalidate, max-age=0"},
        )
    return RedirectResponse(url="/projects.html", status_code=307)


if FRONTEND_DIR.exists():
    app.mount(
        "/",
        NoCacheStaticFiles(directory=str(FRONTEND_DIR), html=True),
        name="frontend",
    )
else:
    log.warning("Frontend dir not found at %s", FRONTEND_DIR)
