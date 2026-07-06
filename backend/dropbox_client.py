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


# Treadwell's Estimating category folders (the "To Dropbox" step-5 destinations).
# Paths are within the Team root namespace (the client rebinds to it in
# _build_client) and were verified against the live Dropbox via a read-only
# files_list_folder — including the `$` prefixes, spacing, and the `*Kyle`
# sub-folder under Commercial Sales (asterisk, not underscore).
ESTIMATING_DESTINATIONS: dict[str, str] = {
    "gyp":         "/2023 Treadwell Team Folder/Estimating/$Gyp Estimates",
    "plans_specs": "/2023 Treadwell Team Folder/Estimating/$Plans Specs Estimates",
    "commercial":  "/2023 Treadwell Team Folder/Estimating/$Commercial Sales Estimates/*Kyle",
}
DESTINATION_LABELS: dict[str, str] = {
    "gyp":         "Gyp Estimates",
    "plans_specs": "Plans & Specs Estimates",
    "commercial":  "Commercial Sales Estimates",
}

# Every project folder is a COPY of this bid template (Docs/ + Numbers 5.7.26/
# with the blank estimate sheet, proposal templates, disclaimer, terms + daf
# tool). The step-5 flow copies it, then files the filled estimate + proposal
# into the Numbers sub-folder. Paths verified via a read-only files_list_folder.
BID_TEMPLATE_PATH = "/2023 Treadwell Team Folder/Estimating/$$ Bid Template"
NUMBERS_SUBFOLDER = "Numbers 5.7.26"
TEMPLATE_ESTIMATE_NAME = "$ estimate sheet - 5.7.xlsx"   # blank; replaced per project


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


def get_root_folder() -> str:
    """The Dropbox folder that new project folders are created under.

    Single source of truth for the output root — used by both
    `_build_folder_path` (where files actually land) and the `/healthz`
    endpoint (so the UI's "Dropbox target" label can't drift from reality).
    Defaults to "/Proposals" when DROPBOX_ROOT_FOLDER is unset.
    """
    return os.environ.get("DROPBOX_ROOT_FOLDER", "/Proposals").rstrip("/")


def _sanitize_folder_name(name: str) -> str:
    """Strip / clean characters Dropbox dislikes in folder names."""
    # Replace illegal chars with a space; collapse repeats; trim.
    cleaned = re.sub(r"[\\/:*?\"<>|]", " ", name or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:120] or "Untitled Project"


def _deadline_prefix(deadline: str | None) -> str:
    """Format the project deadline as a YY.MM.DD folder prefix.

    Accepts the date input's ISO form ('YYYY-MM-DD'), an already-formatted
    'YY.MM.DD', or common US date strings. Falls back to today's date so the
    folder always has a sortable prefix.
    """
    if deadline:
        s = str(deadline).strip()
        for fmt in ("%Y-%m-%d", "%y.%m.%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d"):
            try:
                return datetime.strptime(s, fmt).strftime("%y.%m.%d")
            except ValueError:
                continue
    return datetime.now().strftime("%y.%m.%d")


def _build_folder_path(
    project_name: str,
    *,
    deadline: str | None = None,
    work_type: str | None = None,
    status_marker: str | None = "!",
) -> str:
    """Build a Treadwell-style project folder name.

    Folder convention (prefix is the project DEADLINE so folders sort by
    due date):

        YY.MM.DD  Project Name  (work_type)?  status_marker?

    Examples:
        26.08.15 Olathe CTE OSC (Polish) !
        26.09.01 FCI Leavenworth FBOP !

    `deadline` is the date the estimator picks on intake; if missing/
    unparseable we fall back to today. `work_type` only renders when it's
    "polish" or "combo" (epoxy is the default and isn't called out, per
    Treadwell convention). `status_marker` defaults to '!' (active jobs).
    """
    root = get_root_folder()
    prefix = _deadline_prefix(deadline)

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


def _simple_folder_path(base_path: str, project_name: str, deadline: str | None) -> str:
    """`{base}/{YY.MM.DD deadline} {Project Name}` — the Estimating-folder
    convention used by the step-5 "To Dropbox" destinations: date + name only,
    with NO status marker and NO (Polish)/(Combo) suffix (differs from
    _build_folder_path). `base_path` is the chosen destination category folder."""
    return f"{base_path.rstrip('/')}/{_deadline_prefix(deadline)} {_sanitize_folder_name(project_name)}"


def _proposal_date(value: str | None) -> str:
    """MM.DD for the proposal filename (from bid date / deadline / today)."""
    if value:
        s = str(value).strip()
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%y.%m.%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(s, fmt).strftime("%m.%d")
            except ValueError:
                continue
    return datetime.now().strftime("%m.%d")


def _output_filenames(project_name: str, work_type: str | None,
                      audience: str | None, bid_date: str | None) -> tuple[str, str]:
    """Treadwell file-naming convention (verified against the team's files):
        estimate:  $estimate sheet - <Project Name>.xlsx
        proposal:  MM.DD TREADWELL <TYPE> PROPOSAL - <audience>.docx
    """
    name = _sanitize_folder_name(project_name)
    est = _sanitize_folder_name(f"$estimate sheet - {name}") + ".xlsx"
    wt = {"epoxy": "EPOXY", "polish": "POLISH", "combo": "COMBO"}.get(
        (work_type or "").strip().lower(), (work_type or "EPOXY").upper())
    aud = "New Direct" if (audience or "Direct").strip().lower() in ("direct", "new direct") else (audience or "GC")
    prop = _sanitize_folder_name(f"{_proposal_date(bid_date)} TREADWELL {wt} PROPOSAL - {aud}") + ".docx"
    return est, prop


# ── step-5 (copy $$ Bid Template + file into Numbers) helpers ──────────
# Proposal TYPE word by work type — the tool's words for epoxy/polish/combo, and
# "GYP UNDERLAYMENT" for gyp (per Kyle + the team's folders).
_PROPOSAL_TYPE_WORDS = {
    "epoxy":  "EPOXY",
    "polish": "POLISH",
    "combo":  "COMBO",
    "gyp":    "GYP UNDERLAYMENT",
}


def _share_link(dbx, ApiError, path: str) -> str:
    """Create (or re-fetch on conflict) a shared link for a Dropbox path."""
    try:
        return dbx.sharing_create_shared_link_with_settings(path).url
    except ApiError:
        links = dbx.sharing_list_shared_links(path=path).links
        return links[0].url if links else ""


def _proposal_date_yy(deadline: str | None, bid_date: str | None) -> str:
    """MM.DD.YY for the proposal filename — prefer the deadline (matches the
    project folder's date prefix), then the bid date, then today."""
    for value in (deadline, bid_date):
        if value:
            s = str(value).strip()
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%y.%m.%d", "%Y/%m/%d"):
                try:
                    return datetime.strptime(s, fmt).strftime("%m.%d.%y")
                except ValueError:
                    continue
    return datetime.now().strftime("%m.%d.%y")


def _project_proposal_name(project_name: str, work_type: str | None,
                           deadline: str | None, bid_date: str | None) -> str:
    """Treadwell project-folder proposal name, NO extension:
        MM.DD.YY TREADWELL <TYPE> PROPOSAL - <Project Name>
    TYPE per _PROPOSAL_TYPE_WORDS; the part after the dash is the project name."""
    typ = _PROPOSAL_TYPE_WORDS.get((work_type or "").strip().lower(), "EPOXY")
    return _sanitize_folder_name(
        f"{_proposal_date_yy(deadline, bid_date)} TREADWELL {typ} PROPOSAL - {project_name}"
    )


def _find_numbers_subfolder(dbx, FolderMetadata, target: str) -> str:
    """The estimate/proposal live in a 'Numbers X.Y.Z' subfolder whose version
    tracks the bid template (1.20.26 / 2.14.25 / 5.7.26 …). Locate it in the
    freshly-copied tree; fall back to the current template's name."""
    try:
        for e in dbx.files_list_folder(target).entries:
            if isinstance(e, FolderMetadata) and e.name.lower().startswith("numbers"):
                return f"{target}/{e.name}"
    except Exception:  # noqa: BLE001
        pass
    return f"{target}/{NUMBERS_SUBFOLDER}"


def _file_into_bid_template(dbx, dropbox, ApiError, FolderMetadata, *, base_path,
                            project_name, xlsx_bytes, docx_bytes, pdf_bytes,
                            deadline, bid_date, work_type) -> dict:
    """Copy the $$ Bid Template into <base>/YY.MM.DD <Project Name>, then file the
    filled estimate + proposal (+ PDF) into its Numbers sub-folder, replacing the
    template's blank estimate sheet. Idempotent on re-run (overwrites the files)."""
    # Destination category must exist (read-only guard) so a bad path can't
    # create a stray tree in the live Treadwell Dropbox.
    try:
        dbx.files_get_metadata(base_path)
    except Exception:  # noqa: BLE001
        return {"configured": False,
                "error": "Couldn't find that Estimating destination folder in Dropbox."}

    target = _simple_folder_path(base_path, project_name, deadline)   # <base>/YY.MM.DD Name

    # Copy the whole template tree (Docs/ + Numbers X.Y.Z/ + contents). On a
    # re-run the target already exists → skip the copy, just refresh the files.
    try:
        dbx.files_copy_v2(BID_TEMPLATE_PATH, target, autorename=False)
    except ApiError as exc:
        if "conflict" not in str(exc):
            raise

    numbers = _find_numbers_subfolder(dbx, FolderMetadata, target)
    name = _sanitize_folder_name(project_name)
    est_path = f"{numbers}/$ estimate sheet - {name}.xlsx"
    prop_base = _project_proposal_name(project_name, work_type, deadline, bid_date)
    docx_path = f"{numbers}/{prop_base}.docx"

    dbx.files_upload(xlsx_bytes, est_path, mode=dropbox.files.WriteMode("overwrite"))
    dbx.files_upload(docx_bytes, docx_path, mode=dropbox.files.WriteMode("overwrite"))

    result = {
        "configured": True,
        "folder_path": target,
        "folder_url":  _share_link(dbx, ApiError, target),
        "xlsx_url":    _share_link(dbx, ApiError, est_path),
        "docx_url":    _share_link(dbx, ApiError, docx_path),
    }
    if pdf_bytes:
        pdf_path = f"{numbers}/{prop_base}.pdf"
        dbx.files_upload(pdf_bytes, pdf_path, mode=dropbox.files.WriteMode("overwrite"))
        result["pdf_url"] = _share_link(dbx, ApiError, pdf_path)

    # Remove the template's blank estimate sheet (replaced by the named one).
    try:
        dbx.files_delete_v2(f"{numbers}/{TEMPLATE_ESTIMATE_NAME}")
    except ApiError:
        pass   # already gone on a re-run, or a differently-versioned template

    return result


def upload_project_files(
    *,
    project_name: str,
    xlsx_bytes: bytes,
    docx_bytes: bytes,
    deadline: str | None = None,
    work_type: str | None = None,
    status_marker: str | None = "!",
    bid_date: str | None = None,
    audience: str | None = None,
    base_path: str | None = None,
    pdf_bytes: bytes | None = None,
) -> dict:
    """Create a project folder + upload the files. Returns links.

    When `base_path` is given (the step-5 "To Dropbox" flow), the project folder
    is created UNDER that destination with the simple `YY.MM.DD Project Name`
    convention, and `pdf_bytes` (if provided) is uploaded alongside the .docx.

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
        from dropbox.files import FolderMetadata

        # Pick the right auth flow — refresh-token if all 3 vars are set,
        # otherwise fall back to the legacy single-token constructor.
        dbx = _build_client()

        # Step-5 flow: copy the $$ Bid Template into the chosen Estimating folder
        # and file the estimate + proposal (+ PDF) into its Numbers sub-folder.
        if base_path:
            return _file_into_bid_template(
                dbx, dropbox, ApiError, FolderMetadata,
                base_path=base_path, project_name=project_name,
                xlsx_bytes=xlsx_bytes, docx_bytes=docx_bytes, pdf_bytes=pdf_bytes,
                deadline=deadline, bid_date=bid_date, work_type=work_type,
            )

        # ── Legacy flat-folder flow (no base_path) — kept for compatibility ──
        folder_path = _build_folder_path(
            project_name, deadline=deadline, work_type=work_type, status_marker=status_marker,
        )
        try:
            dbx.files_create_folder_v2(folder_path)
        except ApiError as exc:
            if "path/conflict/folder" not in str(exc):
                raise
        est_name, prop_name = _output_filenames(project_name, work_type, audience, bid_date)
        xlsx_path = f"{folder_path}/{est_name}"
        docx_path = f"{folder_path}/{prop_name}"
        dbx.files_upload(xlsx_bytes, xlsx_path, mode=dropbox.files.WriteMode("overwrite"))
        dbx.files_upload(docx_bytes, docx_path, mode=dropbox.files.WriteMode("overwrite"))

        result = {
            "configured": True,
            "folder_path": folder_path,
            "folder_url":  _share_link(dbx, ApiError, folder_path),
            "xlsx_url":    _share_link(dbx, ApiError, xlsx_path),
            "docx_url":    _share_link(dbx, ApiError, docx_path),
        }
        if pdf_bytes:
            pdf_name = (prop_name[:-5] if prop_name.lower().endswith(".docx") else prop_name) + ".pdf"
            pdf_path = f"{folder_path}/{pdf_name}"
            dbx.files_upload(pdf_bytes, pdf_path, mode=dropbox.files.WriteMode("overwrite"))
            result["pdf_url"] = _share_link(dbx, ApiError, pdf_path)

        return result

    except Exception as exc:  # noqa: BLE001 — translate to graceful degradation
        log.warning("Dropbox upload failed: %s", exc)   # full detail server-side only
        return {
            "configured": False,
            "error": "Dropbox upload failed — your files are available as direct downloads.",
        }
