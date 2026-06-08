"""
docx → PDF rendering via LibreOffice (headless).

The proposal templates are Word .docx files. To offer a "Download as PDF"
button we render the *filled* .docx to PDF with LibreOffice in headless mode
(`soffice --headless --convert-to pdf`). LibreOffice is baked into the Docker
image (see Dockerfile); on a box without it, `docx_to_pdf` raises a clear
RuntimeError that the API surfaces as a 500.

Why LibreOffice and not python-docx / docx2pdf:
  - python-docx can't render layout to PDF (it has no rendering engine).
  - docx2pdf shells out to Microsoft Word — Windows/Mac only, not the Linux
    container we deploy to.
LibreOffice renders the real Word layout, so the PDF matches the .docx.

Fidelity: the image installs Carlito (metric-compatible with Calibri) and
Liberation (Arial/Times/Courier), so font substitution keeps the same metrics
and the PDF lays out like Word.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger("proposal_tool.pdf_writer")


def _soffice() -> str:
    """Locate the LibreOffice binary, or raise a clear error."""
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        raise RuntimeError(
            "LibreOffice (soffice) not found on PATH — PDF export needs it. "
            "The Docker image bakes it in (apt: libreoffice-writer); for local "
            "dev install LibreOffice."
        )
    return exe


def docx_to_pdf(docx_bytes: bytes, *, timeout: int = 120) -> bytes:
    """Render `docx_bytes` to a PDF and return the PDF bytes.

    Each call gets its own temp dir AND a private LibreOffice user profile
    (`-env:UserInstallation`) so concurrent conversions don't deadlock on the
    shared ~/.config/libreoffice profile lock (one uvicorn worker today, but
    cheap insurance and safe if a future thread pool runs conversions)."""
    exe = _soffice()
    with tempfile.TemporaryDirectory(prefix="tw_pdf_") as tmp:
        tmp_path = Path(tmp)
        in_path = tmp_path / "proposal.docx"
        in_path.write_bytes(docx_bytes)
        # LibreOffice wants a file:// URI for the user-profile dir.
        profile_uri = (tmp_path / "lo_profile").as_uri()

        proc = subprocess.run(
            [
                exe,
                "--headless", "--nologo", "--nofirststartwizard",
                f"-env:UserInstallation={profile_uri}",
                "--convert-to", "pdf",
                "--outdir", str(tmp_path),
                str(in_path),
            ],
            capture_output=True,
            timeout=timeout,
        )

        out_path = tmp_path / "proposal.pdf"
        if not out_path.exists():
            raise RuntimeError(
                "LibreOffice produced no PDF (rc={rc}). stderr: {err} | stdout: {out}".format(
                    rc=proc.returncode,
                    err=(proc.stderr or b"").decode("utf-8", "replace")[:300],
                    out=(proc.stdout or b"").decode("utf-8", "replace")[:300],
                )
            )
        return out_path.read_bytes()
