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
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

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

import dropbox_client
import drafts
import estimate_writer
import pricing
import proposal_writer
import reference_tax


# ─── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("proposal_tool")


# ─── App + middleware ─────────────────────────────────────────────────
app = FastAPI(title="Treadwell Proposal Generator")

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


class AutofillIn(BaseModel):
    """Inputs we send to Claude for the 'Autofill with AI' button."""

    project_name: str | None = None
    address:      str | None = None
    city_state:   str | None = None
    notes:        str | None = None


class GenerateOut(BaseModel):
    work_type: str
    audience: str
    dropbox: Dict[str, Any]    # see dropbox_client.upload_project_files()
    xlsx_download_url: str
    docx_download_url: str
    totals: Dict[str, Any]     # Python-computed preview totals


# ─── In-memory file cache for direct downloads ────────────────────────
# When Dropbox is configured we still keep a direct-download fallback so
# the Done screen always has a button that works. Keyed by random token,
# trimmed after first download or 1 hour, whichever comes first.
_FILE_CACHE: Dict[str, Dict[str, Any]] = {}


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
    return {
        "ok": True,
        "dropbox_configured": dropbox_client._is_configured(),
        # Surface the live output root so the Done-page review card can show
        # the real Dropbox target instead of a hardcoded (drift-prone) string.
        "dropbox_root": dropbox_client.get_root_folder(),
    }


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


@app.post("/api/price")
def api_price(payload: PriceIn) -> Dict[str, Any]:
    """Compute MATERIAL pricing from selections — the tool's own pricing
    engine (replaces the estimate sheet's named-range formulas the browser
    can't evaluate, which is what shows #NAME? in the live preview)."""
    material = 0.0
    systems = []
    for s in payload.systems:
        r = pricing.compute_system(s.get("name"), s.get("sf") or 0,
                                   bulk_discount=payload.bulk_discount)
        systems.append(r)
        material += r["material"]

    polish = None
    if payload.polish_sf:
        pf = payload.polish or {}
        polish = pricing.compute_polish(
            payload.polish_sf,
            reno=bool(pf.get("reno")), grout=bool(pf.get("grout")),
            dye=bool(pf.get("dye")), joint_filler=bool(pf.get("joint_filler")),
        )
        material += polish["material"]

    coves = []
    for c in payload.coves:
        r = pricing.compute_cove(c.get("option"), c.get("lf") or 0,
                                 quartz_system=bool(c.get("quartz")))
        coves.append(r)

    # Roll up to the sheet's Material Total (D40 sub -> +D42 shipping -> D43),
    # including the per-system patch line (epoxy SF * 0.10).
    patch_sf = sum((s.get("sf") or 0) for s in payload.systems)
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


@app.post("/api/autofill")
def api_autofill(payload: AutofillIn) -> Dict[str, Any]:
    """Infer Yes/No flags + system selections from lead notes via the
    local `claude -p` CLI. No Anthropic API key is used — the CLI
    handles auth via the user's logged-in Claude session."""
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
        return {
            "ok": False,
            "error": "`claude` CLI not on PATH. Install it from "
                     "https://claude.com/cli to enable Autofill.",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Autofill failed: {exc}"}


@app.post("/api/generate", response_model=GenerateOut)
def api_generate(payload: GenerateIn) -> GenerateOut:
    """Final generate: fill xlsx + docx, upload to Dropbox, return links."""
    values = payload.values

    # Fill estimate workbook
    try:
        xlsx_bytes = estimate_writer.fill_estimate(
            values,
            cell_values=payload.cell_values,
            extras=payload.extras,
        )
    except Exception as exc:
        log.exception("Estimate fill failed")
        raise HTTPException(500, f"Estimate fill failed: {exc}") from exc

    # Fill proposal document
    try:
        docx_bytes = proposal_writer.fill_proposal(
            work_type=payload.work_type,
            audience=payload.audience,
            values=values,
        )
    except FileNotFoundError as exc:
        raise HTTPException(500, str(exc)) from exc
    except Exception as exc:
        log.exception("Proposal fill failed")
        raise HTTPException(500, f"Proposal fill failed: {exc}") from exc

    # Try Dropbox upload (non-fatal on failure). Folder name follows
    # Treadwell's convention: "YY.NNN Project Name (Polish)? !?"
    project_name = (values.get("project_name") or "Untitled Project").strip()
    dropbox_result = dropbox_client.upload_project_files(
        project_name=project_name,
        xlsx_bytes=xlsx_bytes,
        docx_bytes=docx_bytes,
        deadline=values.get("deadline"),
        work_type=payload.work_type,
        status_marker=values.get("status_marker") or "!",
        bid_date=values.get("bid_date"),
        audience=payload.audience,
    )

    # Always cache files for direct download (Done screen always has working links)
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

    return GenerateOut(
        work_type=payload.work_type,
        audience=payload.audience,
        dropbox=dropbox_result,
        xlsx_download_url=f"/api/file/{xlsx_token}",
        docx_download_url=f"/api/file/{docx_token}",
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
    return Response(
        content=entry["content"],
        media_type=entry["content_type"],
        headers={
            "Content-Disposition": f'attachment; filename="{entry["filename"]}"',
        },
    )


# ─── Draft persistence (SQLite) ───────────────────────────────────────
# Multi-device draft autosave: the frontend POSTs the whole state blob
# here every few seconds, keyed by a UUID in the URL (?d=<uuid>). Opening
# that same URL on another device GETs the draft back. See drafts.py.
class DraftIn(BaseModel):
    data: Dict[str, Any] = Field(default_factory=dict)


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
def api_save_draft(draft_id: str, payload: DraftIn) -> Dict[str, Any]:
    """Upsert a draft's full state blob. Called on a debounce as the
    estimator types — so a tab close / device switch doesn't lose work."""
    try:
        return {"ok": True, **drafts.save_draft(draft_id, payload.data)}
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
def api_delete_draft(draft_id: str) -> Dict[str, Any]:
    """Remove a draft (Start-a-new-project)."""
    existed = drafts.delete_draft(draft_id)
    return {"ok": True, "existed": existed}


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
