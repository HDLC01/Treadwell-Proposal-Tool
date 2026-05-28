"""
Thin Dropbox wrapper.

One function: `upload_project_files(project_name, xlsx_bytes, docx_bytes)`
creates a project folder under DROPBOX_ROOT_FOLDER and uploads both
files into it. Returns a dict with the folder + file links.

If DROPBOX_ACCESS_TOKEN isn't set, returns a "fake" result so the rest
of the app degrades to direct-download mode. Treadwell can ship the
tool without Dropbox configured, then add the token later.

Auth: app-level long-lived access token (no per-user OAuth). Generate
the token once at https://www.dropbox.com/developers/apps and drop it
in `.env`.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Optional

log = logging.getLogger("proposal_tool.dropbox_client")


class DropboxNotConfigured(RuntimeError):
    """Raised when DROPBOX_ACCESS_TOKEN isn't set."""


def _is_configured() -> bool:
    return bool(os.environ.get("DROPBOX_ACCESS_TOKEN"))


def _sanitize_folder_name(name: str) -> str:
    """Strip / clean characters Dropbox dislikes in folder names."""
    # Replace illegal chars with a space; collapse repeats; trim.
    cleaned = re.sub(r"[\\/:*?\"<>|]", " ", name or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:120] or "Untitled Project"


def _build_folder_path(project_name: str) -> str:
    root = os.environ.get("DROPBOX_ROOT_FOLDER", "/Proposals").rstrip("/")
    date_prefix = datetime.now().strftime("%y.%m.%d")
    name = _sanitize_folder_name(project_name)
    return f"{root}/{date_prefix} {name}"


def upload_project_files(
    *,
    project_name: str,
    xlsx_bytes: bytes,
    docx_bytes: bytes,
) -> dict:
    """Create a project folder + upload both files. Returns links.

    Result shape:
        {
          "configured": True,
          "folder_path": "/Proposals/26.05.29 Acme Mfg",
          "folder_url":  "https://www.dropbox.com/...",
          "xlsx_url":    "https://www.dropbox.com/...",
          "docx_url":    "https://www.dropbox.com/...",
        }

    When Dropbox isn't configured OR the API call fails, returns:
        { "configured": False, "error": "..." }
    The caller falls back to direct-download mode in that case.
    """
    if not _is_configured():
        return {
            "configured": False,
            "error": "DROPBOX_ACCESS_TOKEN not set; files available as direct downloads only.",
        }

    try:
        # Import here so the module loads even when dropbox isn't installed.
        import dropbox
        from dropbox.exceptions import ApiError

        dbx = dropbox.Dropbox(os.environ["DROPBOX_ACCESS_TOKEN"])

        folder_path = _build_folder_path(project_name)
        try:
            dbx.files_create_folder_v2(folder_path)
        except ApiError as exc:
            # If folder already exists, Dropbox returns a conflict — keep going.
            if "path/conflict/folder" not in str(exc):
                raise

        # Upload both files.
        xlsx_path = f"{folder_path}/Estimate.xlsx"
        docx_path = f"{folder_path}/Proposal.docx"
        dbx.files_upload(
            xlsx_bytes, xlsx_path,
            mode=dropbox.files.WriteMode("overwrite"),
        )
        dbx.files_upload(
            docx_bytes, docx_path,
            mode=dropbox.files.WriteMode("overwrite"),
        )

        # Generate share links (one-time creation; reuse on conflict).
        def _share(path: str) -> str:
            try:
                link = dbx.sharing_create_shared_link_with_settings(path)
                return link.url
            except ApiError:
                # Link already exists — fetch it.
                links = dbx.sharing_list_shared_links(path=path).links
                return links[0].url if links else ""

        return {
            "configured": True,
            "folder_path": folder_path,
            "folder_url":  _share(folder_path),
            "xlsx_url":    _share(xlsx_path),
            "docx_url":    _share(docx_path),
        }

    except Exception as exc:  # noqa: BLE001 — translate to graceful degradation
        log.warning("Dropbox upload failed: %s", exc)
        return {
            "configured": False,
            "error": f"Dropbox upload failed: {exc}",
        }
