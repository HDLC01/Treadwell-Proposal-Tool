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
    """Either a long-lived access token (legacy) OR the refresh-token
    triple (App Key + App Secret + Refresh Token, modern) counts as
    configured."""
    if os.environ.get("DROPBOX_ACCESS_TOKEN"):
        return True
    return bool(
        os.environ.get("DROPBOX_APP_KEY")
        and os.environ.get("DROPBOX_APP_SECRET")
        and os.environ.get("DROPBOX_REFRESH_TOKEN")
    )


def _build_client():
    """Construct a `dropbox.Dropbox` from whichever env-var combo is set,
    rebound to the team-root namespace so folder writes land in
    *Treadwell Dropbox*, not the signed-in user's personal namespace.

    Preference order:
      1. Refresh-token flow (App Key + App Secret + Refresh Token) — modern
      2. Long-lived access token — legacy fallback
    """
    import dropbox
    from dropbox.common import PathRoot

    if (
        os.environ.get("DROPBOX_APP_KEY")
        and os.environ.get("DROPBOX_APP_SECRET")
        and os.environ.get("DROPBOX_REFRESH_TOKEN")
    ):
        dbx = dropbox.Dropbox(
            app_key=os.environ["DROPBOX_APP_KEY"],
            app_secret=os.environ["DROPBOX_APP_SECRET"],
            oauth2_refresh_token=os.environ["DROPBOX_REFRESH_TOKEN"],
        )
    else:
        dbx = dropbox.Dropbox(os.environ["DROPBOX_ACCESS_TOKEN"])

    # Members of a Dropbox Team have two namespaces: their personal "home"
    # namespace and the team's "root" namespace. By default the SDK operates
    # in the home namespace, which means folders we create disappear from
    # everyone else on the team. Rebind to root so writes show up under
    # "Treadwell Dropbox" for the whole team.
    try:
        acct = dbx.users_get_current_account()
        root_ns = acct.root_info.root_namespace_id
        home_ns = acct.root_info.home_namespace_id
        if root_ns and root_ns != home_ns:
            dbx = dbx.with_path_root(PathRoot.root(root_ns))
    except Exception:
        # Personal accounts (no team) don't have a root namespace —
        # the default behavior is correct, so swallow.
        pass

    return dbx


def _sanitize_folder_name(name: str) -> str:
    """Strip / clean characters Dropbox dislikes in folder names."""
    # Replace illegal chars with a space; collapse repeats; trim.
    cleaned = re.sub(r"[\\/:*?\"<>|]", " ", name or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:120] or "Untitled Project"


def _build_folder_path(
    project_name: str,
    *,
    job_number: str | int | None = None,
    work_type: str | None = None,
    status_marker: str | None = "!",
) -> str:
    """Build a Treadwell-style project folder name.

    Matches Treadwell's existing Dropbox convention (verified against
    `Treadwell Dropbox/2023 Treadwell Team Folder/Projects/`):

        YY.NNN  Project Name  (work_type)?  status_marker?

    Production examples:
        24.117 Olathe CTE OSC (Polish) !
        24.162 FCI Leavenworth FBOP ! #
        25.104 SPX Crane Pads $

    `job_number` is the 3-digit sequence Troy assigns; if not supplied
    we fall back to the date so the folder still has a unique sortable
    prefix. `work_type` only renders when it's "polish" or "combo"
    (epoxy is the default and isn't called out, per Treadwell convention).
    `status_marker` defaults to '!' which appears on most active jobs.
    """
    root = os.environ.get("DROPBOX_ROOT_FOLDER", "/Proposals").rstrip("/")

    # Prefix
    yy = datetime.now().strftime("%y")
    if job_number not in (None, ""):
        raw = str(job_number).strip()
        if "." in raw:
            # User typed full YY.NNN — use as-is
            prefix = raw
        else:
            try:
                nnn = f"{int(raw):03d}"
            except (ValueError, TypeError):
                nnn = raw
            prefix = f"{yy}.{nnn}"
    else:
        prefix = datetime.now().strftime("%y.%m.%d")

    name = _sanitize_folder_name(project_name)

    # Optional (Polish) / (Combo) suffix per Treadwell convention
    suffix_parts: list[str] = []
    wt = (work_type or "").strip().lower()
    if wt == "polish":
        suffix_parts.append("(Polish)")
    elif wt == "combo":
        suffix_parts.append("(Combo)")
    if status_marker:
        suffix_parts.append(status_marker.strip())

    suffix = " " + " ".join(suffix_parts) if suffix_parts else ""
    return f"{root}/{prefix} {name}{suffix}"


def upload_project_files(
    *,
    project_name: str,
    xlsx_bytes: bytes,
    docx_bytes: bytes,
    job_number: str | int | None = None,
    work_type: str | None = None,
    status_marker: str | None = "!",
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

        # Pick the right auth flow — refresh-token if all 3 vars are set,
        # otherwise fall back to the legacy single-token constructor.
        dbx = _build_client()

        folder_path = _build_folder_path(
            project_name,
            job_number=job_number,
            work_type=work_type,
            status_marker=status_marker,
        )
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
