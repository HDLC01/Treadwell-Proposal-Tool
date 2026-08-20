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

import difflib
import logging
import os
import re
from datetime import datetime
from typing import Any, Optional

log = logging.getLogger("proposal_tool.dropbox_client")


# Treadwell's Estimating category folders (the "To Dropbox" step-5 destinations).
# Paths are within the Team root namespace (the client rebinds to it in
# _build_client) and were verified against the live Dropbox via a read-only
# files_list_folder — including the `$` prefixes and spacing. Commercial files
# into the CATEGORY folder itself (Hanz 2026-07-14: not into the per-person
# `*Kyle` sub-folder).
ESTIMATING_DESTINATIONS: dict[str, str] = {
    "gyp":         "/2023 Treadwell Team Folder/Estimating/$Gyp Estimates",
    "plans_specs": "/2023 Treadwell Team Folder/Estimating/$Plans Specs Estimates",
    "commercial":  "/2023 Treadwell Team Folder/Estimating/$Commercial Sales Estimates",
}
DESTINATION_LABELS: dict[str, str] = {
    "gyp":         "Gyp Estimates",
    "plans_specs": "Plans & Specs Estimates",
    "commercial":  "Commercial Sales Estimates",
}

# Per-person sub-folders inside $Commercial Sales Estimates (verified live via a
# read-only files_list_folder 2026-07-24). A blank/unknown owner files into the
# category folder itself. Only Commercial Sales has these; Gyp / Plans & Specs
# always use their category folder.
# Fallback only — the live list comes from list_estimating_folders() below. Kept
# so step 5 still works when Dropbox is unreachable. Liz and Troy removed per Will.
COMMERCIAL_OWNER_SUBFOLDERS: dict[str, str] = {
    "kyle": "*Kyle",
    "hanz": "*Hanz",
    "rj":   "*RJ",
}

ESTIMATING_ROOT = "/2023 Treadwell Team Folder/Estimating"
_FOLDER_CACHE: dict[str, Any] = {"at": 0.0, "data": None}
_FOLDER_TTL_S = 300          # 5 min: new folders show up promptly without hammering Dropbox


# Folders that live under Estimating but are NOT filing destinations. "$$ Bid
# Template" is the template each project folder is COPIED FROM — offering it
# would let someone file a job into the template itself.
_NOT_DESTINATIONS = {"$$ bid template"}

# Owner folders Will asked to drop from the picker. The folders still exist in
# Dropbox (we don't delete anyone's files), so the live listing keeps returning
# them — hide them here rather than in Dropbox.
_HIDDEN_OWNERS = {"liz", "troy"}


def _slug(name: str) -> str:
    """'*Kyle' -> 'kyle', '$Gyp Estimates' -> 'gyp_estimates'. The value the UI
    posts back."""
    return name.lstrip("*$").strip().lower().replace(" ", "_").replace("&", "and")


def _legacy_key(path: str) -> Optional[str]:
    """The stable key an existing destination has always used. /api/to-dropbox
    looks paths up by these, so a live-listed folder MUST keep its old key or
    filing breaks."""
    for k, p in ESTIMATING_DESTINATIONS.items():
        if p == path:
            return k
    return None


def destination_path(key: str) -> Optional[str]:
    """Absolute path for a destination key. Checks the live listing first so a
    folder added in Dropbox is filable immediately, then the constants."""
    if not key:
        return None
    try:
        for d in (list_estimating_folders().get("destinations") or []):
            if d.get("key") == key:
                return d.get("path")
    except Exception:  # noqa: BLE001 — fall through to the constants
        pass
    return ESTIMATING_DESTINATIONS.get(key)


def list_estimating_folders() -> dict[str, Any]:
    """The live Estimating destinations + Commercial owner sub-folders, read from
    Dropbox so adding or removing a folder there is reflected without a deploy.

    Cached briefly. On any failure the caller falls back to the constants above —
    step 5 must never dead-end because Dropbox had a bad minute.
    """
    import time
    now = time.monotonic()
    if _FOLDER_CACHE["data"] is not None and (now - _FOLDER_CACHE["at"]) < _FOLDER_TTL_S:
        return _FOLDER_CACHE["data"]

    # _build_client() returns the client ALONE (see its other caller) — unpacking
    # it as a pair raised "cannot unpack non-iterable Dropbox object" live.
    from dropbox.files import FolderMetadata
    dbx = _build_client()

    def _subfolders(path: str) -> list[str]:
        out = []
        res = dbx.files_list_folder(path)
        while True:
            out += [e.name for e in res.entries if isinstance(e, FolderMetadata)]
            if not res.has_more:
                break
            res = dbx.files_list_folder_continue(res.cursor)
        return out

    destinations = []
    for n in sorted(_subfolders(ESTIMATING_ROOT)):
        if not n.startswith("$") or n.strip().lower() in _NOT_DESTINATIONS:
            continue
        path = f"{ESTIMATING_ROOT}/{n}"
        # Keep the legacy key where one exists — /api/to-dropbox resolves paths by
        # key, so renaming them would break filing for every existing destination.
        destinations.append({"key": _legacy_key(path) or _slug(n),
                             "label": n.lstrip("$").strip(), "path": path})
    commercial = next((d for d in destinations if "commercial" in d["key"]), None)
    owners = []
    if commercial:
        owners = [{"key": _slug(n), "label": n.lstrip("*").strip(), "folder": n}
                  for n in sorted(_subfolders(commercial["path"]))
                  if n.startswith("*") and _slug(n) not in _HIDDEN_OWNERS]
    data = {"destinations": destinations, "commercial_key": commercial["key"] if commercial else None,
            "owners": owners}
    _FOLDER_CACHE.update(at=now, data=data)
    return data


def commercial_owner_subfolder(owner: str | None) -> str:
    """Sub-folder under $Commercial Sales Estimates for the chosen owner.
    Blank/unknown owner → "" (file into the category folder itself).

    Checks the LIVE listing first so a folder added in Dropbox works immediately;
    falls back to the built-in map when the listing isn't available."""
    key = (owner or "").strip().lower()
    if not key:
        return ""
    try:
        for o in (list_estimating_folders().get("owners") or []):
            if o.get("key") == key:
                return o.get("folder") or ""
    except Exception:  # noqa: BLE001 — fall through to the constants
        pass
    return COMMERCIAL_OWNER_SUBFOLDERS.get(key, "")


# ── the project folders Kyle's team already made ───────────────────────
# Kyle 2026-08-19: "use specifically the folder of dropbox and not the folders we
# made. So there are duplicates there." His team files a job by hand before we
# ever see it, so step 5 has to offer THEIR folder as the destination instead of
# inventing a second one beside it.
#
# What the live Dropbox actually holds (read-only files_list_folder, 2026-08-19):
#   $Plans Specs Estimates   67 project folders, "YY.MM.DD Name", plus $Archive
#   $Gyp Estimates           80 project folders, same convention, plus
#                            "Greg- Archive" / "Liz- Archive" / "Not Bidding"
#   $Commercial Sales        NO project folders at all — only the per-person
#                            *Hanz *Kyle *Liz *RJ *Troy folders (and Dropbox's
#                            "_Name" Windows-sync twins of them), so the projects
#                            are ONE LEVEL DEEPER than the category folder.
#   .../*Kyle                27 folders incl. "26.06.12 Trabon Office Polish"
#   .../*RJ                  12 folders with NO date prefix ("Adler Pelzer",
#                            "2101 Broadway", "H&R Rep Restrooms")
# Hence: matching must survive a missing date prefix, a different date, and a
# differently-worded name.
_PROJECT_FOLDER_CACHE: dict[str, Any] = {}
_PROJECT_FOLDER_TTL_S = 120     # shorter than _FOLDER_TTL_S: a folder the estimator
                                # just made by hand has to show up in the picker


def list_project_folders(base_path: str, *,
                         include_owner_subfolders: bool = False) -> list[dict]:
    """The child FOLDERS of `base_path`, as [{"name", "path", "parent"}].

    `include_owner_subfolders` also descends ONE level into children whose name
    starts with "*" — the only way Kyle's commercial project folders are
    reachable, since $Commercial Sales Estimates holds only the per-person
    folders. "_"-prefixed children are never descended into: they are Dropbox's
    Windows-sync renames of the "*" folders ('*' is illegal in a Windows
    filename), so filing into one would be filing into a ghost.

    Cached briefly, keyed by base_path + the flag. Raises on a Dropbox failure —
    the caller decides (step 5 falls back to "create a new folder").
    """
    import time
    key = f"{(base_path or '').rstrip('/')}|{1 if include_owner_subfolders else 0}"
    now = time.monotonic()
    hit = _PROJECT_FOLDER_CACHE.get(key)
    if hit and (now - hit["at"]) < _PROJECT_FOLDER_TTL_S:
        return hit["data"]

    # _build_client() returns the client ALONE (see list_estimating_folders).
    from dropbox.files import FolderMetadata
    dbx = _build_client()

    def _child_folders(path: str) -> list[str]:
        out: list[str] = []
        res = dbx.files_list_folder(path)
        while True:
            out += [e.name for e in res.entries if isinstance(e, FolderMetadata)]
            if not res.has_more:
                break
            res = dbx.files_list_folder_continue(res.cursor)
        return out

    base = (base_path or "").rstrip("/")
    folders: list[dict] = []
    for name in _child_folders(base):
        folders.append({"name": name, "path": f"{base}/{name}", "parent": ""})
        if include_owner_subfolders and name.startswith("*"):
            owner_path = f"{base}/{name}"
            try:
                for child in _child_folders(owner_path):
                    folders.append({"name": child, "path": f"{owner_path}/{child}",
                                    "parent": name})
            except Exception as exc:  # noqa: BLE001 — one unreadable owner folder
                log.warning("dropbox: couldn't list %s: %s", owner_path, exc)
    _PROJECT_FOLDER_CACHE[key] = {"at": now, "data": folders}
    return folders


# A leading date prefix, in every form the team's folders use. The lookahead +
# the date PARSE below are what keep "2101 Broadway" and "8036 Metcalf Apts"
# intact: a bare number group is not a date, and 26.35.99 isn't either.
_DATE_PREFIX_RE = re.compile(
    r"""^\s*(
          \d{4}[-./]\d{1,2}[-./]\d{1,2}       # 2026-08-21 / 2026.08.21
        | \d{1,2}[-./]\d{1,2}[-./]\d{2,4}     # 26.08.21 (YY.MM.DD) or 08.21.26 (MM.DD.YY)
    )(?=[\s_.,-]|$)""",
    re.VERBOSE,
)
_DATE_PREFIX_FORMATS = ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d",
                        "%y-%m-%d", "%y.%m.%d", "%y/%m/%d",
                        "%m-%d-%y", "%m.%d.%y", "%m/%d/%y",
                        "%m-%d-%Y", "%m.%d.%Y", "%m/%d/%Y")

# Words too common in Treadwell folder names to count as a distinctive match.
_MATCH_STOPWORDS = {
    "the", "and", "for", "with", "project", "projects", "phase", "phases",
    "apartments", "apartment", "apts", "building", "buildings", "bldg",
    "center", "centre", "group", "company", "llc", "inc", "corp", "new",
    "remodel", "addition", "expansion", "estimate", "estimates", "bid",
}

# Folders that live beside the project folders but are not one. Kept SELECTABLE —
# filing into "Not Bidding" is a real thing somebody may want — just never first.
_NON_PROJECT_WORDS = re.compile(r"\b(archive|archives|not bidding|measuresquare|"
                                r"measure square|stack|template)\b")


def _parses_as_date(text: str) -> bool:
    for fmt in _DATE_PREFIX_FORMATS:
        try:
            datetime.strptime(text, fmt)
            return True
        except ValueError:
            continue
    return False


def folder_match_key(name: str) -> str:
    """A folder name reduced to the part worth comparing: date prefix off,
    lowercased, punctuation dropped, whitespace collapsed.

        "26.06.12 Trabon Office Polish" -> "trabon office polish"
        "2101 Broadway"                 -> "2101 broadway"   (NOT a date)
        "8036 Metcalf Apts"             -> "8036 metcalf apts"
    """
    s = (name or "").strip()
    m = _DATE_PREFIX_RE.match(s)
    if m and _parses_as_date(m.group(1)):
        s = s[m.end():]
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _non_project_rank(name: str) -> int:
    """1 for a folder that is plainly not a project (sorts last), else 0."""
    raw = (name or "").strip()
    # "$Archive", the "*Kyle" owner folders themselves, and their "_Kyle" twins.
    if raw[:1] in ("$", "*", "_"):
        return 1
    return 1 if _NON_PROJECT_WORDS.search(folder_match_key(raw)) else 0


def _match_score(project_key: str, folder_key: str) -> float:
    """0..1, higher = likelier the same job. Three signals, because no one of
    them is enough on the team's real names:

      * SequenceMatcher ratio — catches a re-worded name ("Trabon Group" vs
        "Trabon Office Polish").
      * word-set Jaccard — catches extra/missing words cheaply.
      * a distinctive-token hit — the one that actually matters. For "Trabon
        Group" the shared token "trabon" IS the whole signal; Jaccard alone
        scores that real pair 0.25, which loses to noise.
    """
    if not project_key or not folder_key:
        return 0.0
    ratio = difflib.SequenceMatcher(None, project_key, folder_key).ratio()
    p_words = set(project_key.split())
    f_words = set(folder_key.split())
    union = p_words | f_words
    jaccard = (len(p_words & f_words) / len(union)) if union else 0.0

    distinctive = {w for w in p_words if len(w) >= 4 and w not in _MATCH_STOPWORDS}
    if not distinctive:
        # Nothing distinctive to look for (e.g. "The Apartments") — spend the
        # token weight on the two similarity signals rather than scoring 0.
        return round(min(1.0, 0.55 * ratio + 0.45 * jaccard), 3)
    hits = sum(1 for w in distinctive if w in f_words)
    frac = hits / len(distinctive)
    score = 0.35 * ratio + 0.25 * jaccard + 0.30 * frac + (0.10 if hits else 0.0)
    return round(min(1.0, max(0.0, score)), 3)


def rank_project_folders(folders: list[dict], project_name: str) -> list[dict]:
    """`folders` (from list_project_folders) with a "score" added, best-first.

    The score orders the picker and feeds the "looks like this one" hint in the
    UI — it never files anything by itself; a human still clicks the folder.
    Non-project folders sort LAST whatever they score, and the sort is stable so
    equal scores keep Dropbox's order.
    """
    key = folder_match_key(project_name)
    out = []
    for f in folders:
        item = dict(f)
        item["score"] = _match_score(key, folder_match_key(f.get("name") or ""))
        out.append(item)
    return sorted(out, key=lambda f: (_non_project_rank(f.get("name") or ""),
                                      -f["score"]))


# Every project folder is a COPY of this bid template (Docs/ + Numbers 5.7.26/
# with the blank estimate sheet, proposal templates, disclaimer, terms + daf
# tool). The step-5 flow copies it, then files the filled estimate + proposal
# into the Numbers sub-folder. Paths verified via a read-only files_list_folder.
BID_TEMPLATE_PATH = "/2023 Treadwell Team Folder/Estimating/$$ Bid Template"
# The template's Numbers folder is versioned and Kyle re-dates it. Read live as
# "Numbers 8.10.26" on 2026-08-19 (was 5.7.26). Only a FALLBACK: the real name is
# found in the copied tree by _find_numbers_subfolder, and _file_into_existing_folder
# deliberately never falls back to it (see the note there).
NUMBERS_SUBFOLDER = "Numbers 8.10.26"
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
    copied = False
    try:
        dbx.files_copy_v2(BID_TEMPLATE_PATH, target, autorename=False)
        copied = True
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

    written = [est_path, docx_path]
    result = {
        "configured": True,
        "existing":    not copied,      # a conflict means the folder was already there
        "folder_path": target,
        "folder_url":  _share_link(dbx, ApiError, target),
        "xlsx_url":    _share_link(dbx, ApiError, est_path),
        "docx_url":    _share_link(dbx, ApiError, docx_path),
    }
    if pdf_bytes:
        pdf_path = f"{numbers}/{prop_base}.pdf"
        dbx.files_upload(pdf_bytes, pdf_path, mode=dropbox.files.WriteMode("overwrite"))
        result["pdf_url"] = _share_link(dbx, ApiError, pdf_path)
        written.append(pdf_path)
    result["written_paths"] = written
    result["renamed"] = []

    # Remove the template's blank estimate sheet (replaced by the named one) —
    # ONLY when this call actually copied the template. Before (Kyle 2026-08-19)
    # the delete ran regardless: a conflict on the copy means the folder was
    # already there, possibly one a HUMAN made from the same template, and that
    # blank "$ estimate sheet" may be the file Kyle has been typing into.
    if copied:
        try:
            dbx.files_delete_v2(f"{numbers}/{TEMPLATE_ESTIMATE_NAME}")
        except ApiError:
            pass   # a differently-versioned template names it something else

    return result


def _is_path_not_found(exc, ApiError) -> bool:
    """True ONLY for a genuine "there is nothing at that path".

    This is the question `_upload_beside`'s probe asks, and a wrong "yes"
    OVERWRITES a file a human wrote — the one outcome this whole path exists to
    prevent (review 2026-08-20: the probe used to read ANY exception as
    "the path is free", so a rate limit, a 5xx, an expired token or a dropped
    connection all downgraded the guarantee to a blind overwrite).

    Dropbox surfaces a real not-found as an ApiError carrying a `path` error
    union whose LookupError is `not_found`, so that is checked typed rather than
    by matching the message. Every other ApiError — and RateLimitError,
    AuthError, InternalServerError, HttpError, requests' transport errors — never
    carries that union, so it answers "unknown", which the caller must treat as
    occupied."""
    if isinstance(exc, ApiError):
        err = getattr(exc, "error", None)
        try:
            return bool(err.is_path() and err.get_path().is_not_found())
        except Exception:  # noqa: BLE001 — a different route's error union
            return False
    # Not an SDK ApiError at all: a wrapper somebody adds later, or a test
    # double. There is no union to read, so the text is all there is — and it
    # counts only when it says not_found outright. Anything unrecognised stays
    # "unknown" (= occupied).
    return "not_found" in str(exc)


def _upload_beside(dbx, dropbox, ApiError, path: str, data: bytes,
                   known: set[str], renamed: list[str]) -> str:
    """Upload `data` to `path` WITHOUT ever clobbering somebody else's file.

    `known` holds the paths a previous run of ours wrote (lowercased); those are
    ours to overwrite, which is what keeps a genuine re-file from piling up
    "… (1).xlsx". Anything else already sitting at `path` is a human's, so the
    upload goes in beside it with autorename and we report the name Dropbox gave
    it. Returns the path the bytes actually landed at.

    A probe that FAILS for any reason other than not-found counts as occupied:
    an extra "… (1).xlsx" is recoverable, an overwritten estimate is not."""
    occupied = False
    if path.lower() not in known:
        try:
            dbx.files_get_metadata(path)
            occupied = True
        except Exception as exc:  # noqa: BLE001 — not there is the normal case
            occupied = not _is_path_not_found(exc, ApiError)
    if not occupied:
        dbx.files_upload(data, path, mode=dropbox.files.WriteMode("overwrite"))
        return path
    meta = dbx.files_upload(data, path, mode=dropbox.files.WriteMode("add"),
                            autorename=True)
    real = getattr(meta, "path_display", None) or getattr(meta, "path_lower", None) or path
    if real != path:
        renamed.append(real)
    return real


def _existing_numbers_subfolder(dbx, FolderMetadata, target: str) -> str:
    """Same lookup as _find_numbers_subfolder, but with NO constant fallback:
    a folder a human made may have no "Numbers *" child at all (the *RJ folders
    don't follow the bid-template shape), and files_upload creates missing
    parents — so falling back to NUMBERS_SUBFOLDER here would silently invent a
    stray "Numbers 8.10.26" inside somebody's project folder. File into the
    folder root instead."""
    try:
        for e in dbx.files_list_folder(target).entries:
            if isinstance(e, FolderMetadata) and e.name.lower().startswith("numbers"):
                return f"{target}/{e.name}"
    except Exception:  # noqa: BLE001
        pass
    return target


def _file_into_existing_folder(dbx, dropbox, ApiError, FolderMetadata, *, folder_path,
                               project_name, xlsx_bytes, docx_bytes, pdf_bytes,
                               deadline, bid_date, work_type, known_paths=()) -> dict:
    """File the estimate + proposal (+ PDF) into a project folder that ALREADY
    exists — the one Kyle's team made by hand.

    The whole point is that this folder is somebody else's work, so this path is
    deliberately additive:
      * it never creates the folder, and refuses any path it can't verify;
      * it never calls files_delete_v2 — not even for the blank template sheet
        (Kyle 2026-08-19: in a folder a human copied from the bid template, that
        blank "$ estimate sheet" is very likely the one he has been typing into);
      * it never overwrites a file we didn't write ourselves.
    """
    path = (folder_path or "").strip().rstrip("/")
    root = ESTIMATING_ROOT + "/"
    if not path or ".." in path or not path.startswith(root):
        return {"configured": False,
                "error": "That folder isn't inside the Treadwell Estimating folder."}
    # ...and it has to be a PROJECT folder, i.e. genuinely below a category.
    # "$Gyp Estimates" cleared the test above on its own — it is one segment under
    # the Estimating root — and it holds 80 real project folders, so filing there
    # drops a customer's estimate loose in the folder the whole team shares
    # (review 2026-08-20). A "$"-prefixed leaf is refused for the same reason at
    # any depth: "$Archive" is a shared bucket, not one job's folder. The picker
    # only ever offers a category's CHILDREN, so a path this shallow is a stale
    # tab or a hand-rolled request, never a choice anybody made on screen.
    #
    # A "*"-prefixed leaf goes too, and it is NOT covered by the length test: a
    # person folder like "$Commercial Sales Estimates/*Kyle" is two segments deep
    # and clears it. That folder holds Kyle's 27 jobs, so filing into it drops one
    # customer's paperwork loose among all of them — the same mistake as the
    # category folder, one level down. "*Archive", "*MeasureSquare" and "*Stack"
    # sit in there too and are just as wrong a destination.
    segments = [s for s in path[len(root):].split("/") if s]
    if len(segments) < 2 or segments[-1].startswith(("$", "*")):
        return {"configured": False,
                "error": "That's a category or person folder, not a project folder."}
    try:
        meta = dbx.files_get_metadata(path)
    except Exception:  # noqa: BLE001
        return {"configured": False,
                "error": "Couldn't find that Dropbox folder — it may have been renamed or moved."}
    if not isinstance(meta, FolderMetadata):
        return {"configured": False, "error": "That Dropbox path is a file, not a folder."}

    numbers = _existing_numbers_subfolder(dbx, FolderMetadata, path)
    known = {str(p).strip().rstrip("/").lower() for p in (known_paths or ()) if p}
    renamed: list[str] = []

    name = _sanitize_folder_name(project_name)
    est_path = f"{numbers}/$ estimate sheet - {name}.xlsx"
    prop_base = _project_proposal_name(project_name, work_type, deadline, bid_date)
    docx_path = f"{numbers}/{prop_base}.docx"

    est_real = _upload_beside(dbx, dropbox, ApiError, est_path, xlsx_bytes, known, renamed)
    docx_real = _upload_beside(dbx, dropbox, ApiError, docx_path, docx_bytes, known, renamed)
    written = [est_real, docx_real]

    result = {
        "configured": True,
        "existing":    True,
        "folder_path": path,
        "folder_url":  _share_link(dbx, ApiError, path),
        "xlsx_url":    _share_link(dbx, ApiError, est_real),
        "docx_url":    _share_link(dbx, ApiError, docx_real),
    }
    if pdf_bytes:
        pdf_real = _upload_beside(dbx, dropbox, ApiError, f"{numbers}/{prop_base}.pdf",
                                  pdf_bytes, known, renamed)
        written.append(pdf_real)
        result["pdf_url"] = _share_link(dbx, ApiError, pdf_real)
    result["written_paths"] = written
    result["renamed"] = renamed
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
    existing_folder_path: str | None = None,
    known_paths: tuple | list = (),
) -> dict:
    """Create a project folder + upload the files. Returns links.

    When `base_path` is given (the step-5 "To Dropbox" flow), the project folder
    is created UNDER that destination with the simple `YY.MM.DD Project Name`
    convention, and `pdf_bytes` (if provided) is uploaded alongside the .docx.

    When `existing_folder_path` is given it WINS over `base_path`: the files go
    into that already-existing folder (the one Kyle's team made) and nothing new
    is created. `known_paths` are the paths a previous run of ours wrote there,
    so re-filing overwrites our own file instead of piling up "… (1).xlsx".

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

        # Kyle's own folder, chosen in the picker (or the one we filed into last
        # time) — file into it and create nothing. Checked BEFORE base_path so a
        # caller that passes both can't accidentally make a duplicate folder.
        if existing_folder_path:
            return _file_into_existing_folder(
                dbx, dropbox, ApiError, FolderMetadata,
                folder_path=existing_folder_path, project_name=project_name,
                xlsx_bytes=xlsx_bytes, docx_bytes=docx_bytes, pdf_bytes=pdf_bytes,
                deadline=deadline, bid_date=bid_date, work_type=work_type,
                known_paths=known_paths,
            )

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
