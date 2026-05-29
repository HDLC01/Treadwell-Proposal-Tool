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
import logging
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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import dropbox_client
import estimate_writer
import proposal_writer
import reference_tax


# ─── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("proposal_tool")


# ─── App + CORS ───────────────────────────────────────────────────────
app = FastAPI(title="Treadwell Proposal Generator")

app.add_middleware(
    CORSMiddleware,
    # Same-origin in production (frontend served by us); permissive for dev.
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Schemas ──────────────────────────────────────────────────────────
class DetectWorkTypeIn(BaseModel):
    """Inputs for work-type auto-detection (Screen 1 → Screen 2 hop)."""

    system_1_sf: float = 0
    system_2_sf: float = 0
    polish_sf:   float = 0


class DetectWorkTypeOut(BaseModel):
    work_type: str  # "epoxy" | "polish" | "combo"


class ComputeEstimateIn(BaseModel):
    """All estimate inputs Screen 2 sends for live total recomputes.

    Loose schema — we use a dict because the field set is large and
    evolves; backend just looks up what it needs.
    """

    values: Dict[str, Any] = Field(default_factory=dict)


class GenerateIn(BaseModel):
    """Final payload from Screen 3's Generate button."""

    work_type: str = "epoxy"
    audience:  str = "Direct"  # "Direct" | "GC" | (other)
    # All intake + estimate + proposal fields flattened
    values: Dict[str, Any] = Field(default_factory=dict)
    # Direct cell-for-cell writes (Estimate Review verbatim mode):
    #   { "Epoxy!E20": 18000, "Polish!C20": 0.07, ... }
    cell_values: Dict[str, Any] = Field(default_factory=dict)


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
    }


@app.post("/api/detect-work-type", response_model=DetectWorkTypeOut)
def api_detect_work_type(payload: DetectWorkTypeIn) -> DetectWorkTypeOut:
    """Called between Screen 1 and Screen 2 to pick the right tab."""
    epoxy_sf = (payload.system_1_sf or 0) + (payload.system_2_sf or 0)
    return DetectWorkTypeOut(
        work_type=detect_work_type(epoxy_sf, payload.polish_sf),
    )


@app.post("/api/compute-estimate")
def api_compute_estimate(payload: ComputeEstimateIn) -> Dict[str, Any]:
    """Live-totals endpoint for Screen 2. Pure Python — no Excel involved."""
    return estimate_writer.compute_estimate_totals(payload.values)


@app.get("/api/sheets")
def api_list_sheets() -> Dict[str, Any]:
    """List every tab in the estimate template (powers Screen 2's tab bar)."""
    return {"sheets": estimate_writer.list_sheet_names()}


@app.get("/api/named-expressions")
def api_named_expressions() -> Dict[str, Any]:
    """Workbook-wide defined names that HyperFormula needs registered
    so formulas referencing them (e.g. =AT_Clear_Satin_w_Grit) resolve."""
    return {"names": estimate_writer.read_named_expressions()}


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
def api_get_sheet(sheet_name: str) -> Dict[str, Any]:
    """Return every used cell on `sheet_name` so the UI can render it
    cell-for-cell (values, formulas, fills, fonts, merges, dropdowns)."""
    try:
        return estimate_writer.read_sheet_grid(sheet_name)
    except KeyError:
        raise HTTPException(404, f"Sheet {sheet_name!r} not found")


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
        job_number=values.get("job_number"),
        work_type=payload.work_type,
        status_marker=values.get("status_marker") or "!",
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
        totals=estimate_writer.compute_estimate_totals(values),
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


# ─── Static frontend ──────────────────────────────────────────────────
# Serve the 4 HTML pages from ../frontend. Mount AFTER the API routes
# so /api/* takes precedence.
#
# We intentionally disable HTTP caching on the static files because this
# tool is iterating frequently (filename fixes, layout tweaks). A
# browser sitting on a stale done.html would miss the fetch+Blob
# downloader and downloads would still come down with UUID names —
# don't make users hard-refresh every time.
FRONTEND_DIR = (Path(__file__).parent.parent / "frontend").resolve()


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
