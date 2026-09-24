"""The stamp that ties a saved editor edit to ONE template's paragraphs.

Every document-editor override (paragraph text, bullet/indent, box size, cover-letter paragraph)
is keyed by a POSITION in a walk over one specific .docx, so it is only safe to replay against the
same content. `/api/generate` drops the whole set when the stamp disagrees, and the editor refuses
to restore it.

That stamp used to be the file's `st_mtime_ns`. A deploy rewrites the mtime of every file in the
image without changing a byte, so each deploy made every saved edit look stale. The editor threw
Kyle's edits away when he reopened a proposal to revise it, and the portal re-rendered proposals
customers had already been sent WITHOUT them. Viracor rev 2 printed "System: 0" and "~0 sf" in
place of the joint-filler proposal he sent. Prod payloads carry about twenty different mtimes for
a template whose bytes last changed on 2026-07-16, each one a deploy.

The stamp is now a hash of the file's bytes: `sha256:<16 hex>`.

LEGACY STAMPS. Drafts and pinned revisions saved before this change hold the old all-digit mtime.
One is accepted when the file still has the content recorded in `LEGACY_MTIME_FLOOR_S` AND the
stamp was taken at or after the moment that content landed on `main`. A container cannot stamp an
mtime later than that while still holding older content, so an accepted stamp was captured against
these exact paragraphs. An earlier stamp described a different walk and is refused, as before.

Edit a template and its entry stops matching by itself, so every legacy stamp for it is refused,
which is right: they were all taken against the old paragraphs. `test_template_versions` names the
entry to delete. Never add one: from this change on, every new stamp is a hash.
"""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path

TEMPLATES_ROOT = Path(__file__).parent / "templates"

# Relative template path -> (content version, the commit time in whole seconds at which THAT
# content landed on origin/main, first-parent). Taken from `git log -1 --first-parent --format=%ct
# origin/main -- <path>` on 2026-09-25. Staging got each file a few minutes to an hour earlier, so
# a staging draft stamped in that gap is refused — conservative, and staging holds test data only.
LEGACY_MTIME_FLOOR_S: dict[str, tuple[str, int]] = {
    "Direct/XX.XX TREADWELL EPOXY PROPOSAL - New Direct.docx": ("sha256:b7864a02a9995101", 1784143397),
    "Direct/xx.xx TREADWELL POLISH PROPOSAL - NewDirect.docx": ("sha256:470ee25f9e935c70", 1784143397),
    "Direct/xx.xx.xx TREADWELL COMBO PROPOSAL - CUSTMOER NAME.docx": ("sha256:694b73e894ba14d6", 1784145619),
    "Direct/xx.xx TREADWELL BUDGET PRICING.docx": ("sha256:684e11d2ac9763a4", 1780072749),
    "GC/xx TREADWELL RESINOUS PROPOSAL - xx.docx": ("sha256:0696617b53934dba", 1788900501),
    "GC/xx TREADWELL POLISH PROPOSAL - xx.docx": ("sha256:a271253b8de2007d", 1788900501),
    "GC/xx TREADWELL SEALER PROPOSAL - xx.docx": ("sha256:e6bf38c537a7a95f", 1783698162),
    "Gyp/xx TREADWELL UNDERLAYMENT PROPOSAL - xx.docx": ("sha256:1267be9c540df48c", 1784325215),
    "CoverLetter/Direct/Epoxy.docx": ("sha256:c3ba4d5020100a98", 1789041976),
    "CoverLetter/Direct/Polish.docx": ("sha256:b26a2d8932dfaaf5", 1789041976),
    "CoverLetter/Direct/Combo.docx": ("sha256:456eb9e4931ed888", 1789041976),
    "CoverLetter/GC/Epoxy.docx": ("sha256:da8dfcb293dc98e5", 1789041976),
    "CoverLetter/GC/Polish.docx": ("sha256:f28a572432cc1a5b", 1789041976),
    "CoverLetter/GC/Combo.docx": ("sha256:7e6f0595c6a3bbc7", 1789041976),
    "CoverLetter/Gyp/Gyp.docx": ("sha256:c9b50951eb3617c9", 1789041976),
}

# Hashing a template is ~1 ms, and /api/proposal-template needs the version before it can answer a
# 304, so the digest is memoised on what `stat()` says. A file whose mtime or size moved is re-read;
# one that did not is not. Bounded by the handful of template files plus whatever a test copies.
_HASHES: dict[tuple[str, int, int], str] = {}
_HASHES_LOCK = threading.Lock()


def content_version(path: Path) -> str:
    """`sha256:<16 hex>` of the template's bytes, or "0" when it cannot be read."""
    try:
        st = path.stat()
    except OSError:
        return "0"
    key = (str(path), st.st_mtime_ns, st.st_size)
    with _HASHES_LOCK:
        hit = _HASHES.get(key)
    if hit is not None:
        return hit
    try:
        digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return "0"
    with _HASHES_LOCK:
        if len(_HASHES) > 256:
            _HASHES.clear()
        _HASHES[key] = digest
    return digest


def _relative(path: Path) -> str | None:
    try:
        return path.resolve().relative_to(TEMPLATES_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return None


def legacy_floor_s(path: Path) -> int:
    """The earliest legacy mtime stamp (whole seconds) still accepted for this file, or 0 when none
    can be: the file is not in the table, or its content has changed since the table was written."""
    rel = _relative(path)
    entry = LEGACY_MTIME_FLOOR_S.get(rel) if rel else None
    if not entry or content_version(path) != entry[0]:
        return 0
    return entry[1]


def accepts(pinned: str, path: Path) -> bool:
    """True when overrides stamped `pinned` were captured against this file's current content.

    The caller keeps its own rule for an EMPTY stamp ("legacy caller, apply"): this answers only
    for a stamp that is present."""
    pinned = str(pinned or "")
    current = content_version(path)
    if current != "0" and pinned == current:
        return True
    # A legacy stamp is a bare st_mtime_ns: nineteen digits today, never fewer than ten.
    if len(pinned) >= 10 and pinned.isdigit():
        floor = legacy_floor_s(path)
        return floor > 0 and int(pinned) >= floor * 10 ** 9
    return False


def accepts_prefixed(pinned: str, prefix: str, path: Path) -> bool:
    """`accepts` for a stamp of the form `"<prefix>@<stamp>"`, which is how the cover letter pins
    its overrides to one variant as well as one file (see `_cover_letter_template_version`). A
    stamp for a different variant is refused whatever follows the `@`."""
    pinned = str(pinned or "")
    head = prefix + "@"
    return pinned.startswith(head) and accepts(pinned[len(head):], path)
