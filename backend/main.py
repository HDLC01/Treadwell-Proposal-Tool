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

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import audit
import drafts
import estimate_writer
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
_AUTH_PUBLIC_PATHS = {"/healthz", "/api/public-config"}


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
        return {"ok": False, "error": f"Autofill failed: {exc}"}


def _fmt_usd(n) -> str:
    """Currency for proposal price lines: "$4,200" (drop trailing .00), "$4,200.50".
    Matches the frontend fmtUSD style so price-line/alternate text reads consistently."""
    try:
        v = float(n)
    except (TypeError, ValueError):
        return ""
    s = f"${v:,.2f}"
    return s[:-3] if s.endswith(".00") else s


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


def _build_epoxy_systems(cells: Dict[str, Any], values: Dict[str, Any]) -> list:
    """WORK-section system list for an epoxy proposal, from the picked System 1/2
    cells (Epoxy!A22/E20/E34 and A26/E24/E37). One system → "System:   <name>"
    (no Option label); 2+ → "Option 1: …" / "Option 2: …". Falls back to a single
    system from the flat values so the {{#system}} block always has ≥1 row."""
    def num(x) -> float:
        try:
            return float(str(x).replace(",", "").replace("$", "").strip() or 0)
        except (TypeError, ValueError):
            return 0.0
    def fmt(n: float) -> str:
        return f"{int(round(n)):,}"

    picks = []
    for na, sa, la in (("Epoxy!A22", "Epoxy!E20", "Epoxy!E34"),
                       ("Epoxy!A26", "Epoxy!E24", "Epoxy!E37")):
        name = str(cells.get(na) or "").strip()
        if name and "Options" not in name:        # skip the dropdown header placeholders
            picks.append({"name": name, "sf": num(cells.get(sa)), "lf": num(cells.get(la))})
    if not picks:                                  # no grid pick → single system from flat values
        picks = [{
            "name": str(values.get("system_name") or "").strip() or "Epoxy System",
            "sf": num(values.get("epoxy_sf") if values.get("epoxy_sf") is not None else cells.get("Epoxy!E20")),
            "lf": num(values.get("cove_lf") if values.get("cove_lf") is not None else cells.get("Epoxy!E34")),
        }]
    texture = str(values.get("texture") or "").strip()
    multi = len(picks) > 1
    # The template keeps the bold "System:"/"Option N:" label and a separate
    # regular value run, so we emit them as distinct tokens (prefix + name)
    # rather than one combined string — preserving the sheet's column alignment.
    out = []
    for i, s in enumerate(picks, 1):
        prefix = f"Option {i}:" if multi else "System:"
        lf_clause = f" and {fmt(s['lf'])} LF of epoxy base" if s["lf"] > 0 else ""
        out.append({"prefix": prefix, "name": s["name"], "texture": texture,
                    "sqft": fmt(s["sf"]), "lf_clause": lf_clause})
    return out


def _build_options(rooms_in: list, values: Dict[str, Any]) -> list:
    """Per-sheet priced options for the proposal PRICE section ({{#room}} block).

    Each input option (from the estimate side) is
    {name, is_base, base_total, system_desc, show_system, show_diff,
     bid:{total, sales_tax, remodel}, notes_auto:[...], notes_manual:[...]}.
    Builds, per option with a positive total (base bid first):
      heading:         "Grooming:"
      price_formatted: "$8,310"  (the sheet's all-in D88 — tax-inclusive)
      price_desc:      "Epoxy flooring as described above (<tax phrase>)"
      notes_joined:    stacked lines = [system/scope if show_system] +
                       [signed difference vs base bid if show_diff & not base] +
                       auto notes + manual notes
    The tax phrase names the Kansas Remodel Tax only when that option's remodel
    tax > 0. Returns [] when there are no priced options (block then strips)."""
    def num(x) -> float:
        try:
            return float(str(x).replace(",", "").replace("$", "").strip() or 0)
        except (TypeError, ValueError):
            return 0.0

    state = str(values.get("state_name") or "Kansas").strip() or "Kansas"
    out = []
    for r in (rooms_in or []):
        if not isinstance(r, dict):
            continue
        bid = r.get("bid") or {}
        total = num(bid.get("total"))
        if total <= 0:                              # un-snapshotted / empty sheet
            continue
        is_base = bool(r.get("is_base"))
        remodel = num(bid.get("remodel"))
        tax_phrase = (f"({state} Remodel Tax AND material sales tax INCLUDED)"
                      if remodel > 0 else "(material sales tax INCLUDED)")
        name = str(r.get("name") or "").strip().rstrip(": ").strip()

        lines: list[str] = []
        # System / scope line (each room can carry its own system) — toggleable.
        system_desc = str(r.get("system_desc") or "").strip()
        if r.get("show_system", True) and system_desc:
            lines.append(system_desc)
        # Signed difference vs. the base bid (copies only) — toggleable.
        if not is_base and r.get("show_diff"):
            diff = total - num(r.get("base_total"))
            if diff > 0:
                lines.append(f"+{_fmt_usd(diff)} more than the base bid")
            elif diff < 0:
                lines.append(f"{_fmt_usd(-diff)} less than the base bid")
        lines += [str(n).strip()
                  for n in (list(r.get("notes_auto") or []) + list(r.get("notes_manual") or []))
                  if str(n).strip()]

        out.append({
            "heading": (name + ":") if name else "",
            "price_formatted": _fmt_usd(total),
            "price_desc": "Epoxy flooring as described above " + tax_phrase,
            "notes_joined": "\n".join(lines),
        })
    return out


def _ensure_value_aliases(values: Dict[str, Any]) -> None:
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


@app.post("/api/generate", response_model=GenerateOut)
def api_generate(payload: GenerateIn, request: Request) -> GenerateOut:
    """Final generate: fill xlsx + docx, return download links (xlsx / docx /
    on-demand pdf). The estimator downloads + files them manually."""
    values = payload.values
    _ensure_state_name(values)
    _ensure_value_aliases(values)

    # The epoxy PRICE block itemizes Base Bid + Material Sales Tax. The frontend
    # fills these from the bid; backfill for any caller that doesn't so the
    # template never shows a raw token (Base Bid falls back to the flooring total,
    # Material Sales Tax to $0.00).
    if not str(values.get("base_bid_formatted") or "").strip():
        values["base_bid_formatted"] = (values.get("lump_sum_formatted")
                                        or values.get("total_formatted") or "")
    if not str(values.get("material_tax_formatted") or "").strip():
        values["material_tax_formatted"] = "$0.00"

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

    # Structured PRICE option lines -> repeatable {{#price_line}} rows.
    price_line_dicts = []
    for pl in (payload.price_lines or []):
        label = str((pl or {}).get("label") or "").strip()
        try:
            amt = float((pl or {}).get("amount") or 0)
        except (TypeError, ValueError):
            amt = 0.0
        if label and amt:
            price_line_dicts.append({"label": label, "amount_formatted": _fmt_usd(amt)})

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

    # Per-sheet priced options -> {{#room}} proposal block (base bid + each copy,
    # with toggleable system line + signed difference vs. the base bid).
    rooms_arg = _build_options(payload.rooms, values)

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
        )
    except Exception as exc:
        log.exception("Estimate fill failed")
        raise HTTPException(500, f"Estimate fill failed: {exc}") from exc

    # Fill proposal document
    try:
        # Epoxy WORK section lists each picked system as its own row (1 system →
        # "System: …", 2+ → "Option 1/2: …") via the template's {{#system}} block.
        systems_arg = (_build_epoxy_systems(payload.cell_values, values)
                       if str(payload.work_type or "").lower() == "epoxy" else None)
        docx_bytes = proposal_writer.fill_proposal(
            work_type=payload.work_type,
            audience=payload.audience,
            values=values,
            price_lines=price_line_dicts,
            alternates=alternates,
            systems=systems_arg,
            remodel=payload.remodel,
            rooms=rooms_arg,
            # rooms present → suppress the single Base-Bid/Total layout (the room
            # options ARE the price); absent → default (single-bid layout shown).
            single_bid=([] if rooms_arg else None),
        )
    except FileNotFoundError as exc:
        raise HTTPException(500, str(exc)) from exc
    except Exception as exc:
        log.exception("Proposal fill failed")
        raise HTTPException(500, f"Proposal fill failed: {exc}") from exc

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
            proj_data = dict(values)
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
            raise HTTPException(500, f"PDF conversion failed: {exc}") from exc
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
        for name in ("Epoxy", "Polish"):
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


if FRONTEND_DIR.exists():
    app.mount(
        "/",
        NoCacheStaticFiles(directory=str(FRONTEND_DIR), html=True),
        name="frontend",
    )
else:
    log.warning("Frontend dir not found at %s", FRONTEND_DIR)
