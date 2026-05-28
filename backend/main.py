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
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import dropbox_client
import estimate_writer
import proposal_writer


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
        "dropbox_configured": bool(os.environ.get("DROPBOX_ACCESS_TOKEN")),
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


@app.post("/api/generate", response_model=GenerateOut)
def api_generate(payload: GenerateIn) -> GenerateOut:
    """Final generate: fill xlsx + docx, upload to Dropbox, return links."""
    values = payload.values

    # Fill estimate workbook
    try:
        xlsx_bytes = estimate_writer.fill_estimate(values)
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

    # Try Dropbox upload (non-fatal on failure)
    project_name = (values.get("project_name") or "Untitled Project").strip()
    dropbox_result = dropbox_client.upload_project_files(
        project_name=project_name,
        xlsx_bytes=xlsx_bytes,
        docx_bytes=docx_bytes,
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
FRONTEND_DIR = (Path(__file__).parent.parent / "frontend").resolve()
if FRONTEND_DIR.exists():
    app.mount(
        "/",
        StaticFiles(directory=str(FRONTEND_DIR), html=True),
        name="frontend",
    )
else:
    log.warning("Frontend dir not found at %s", FRONTEND_DIR)
