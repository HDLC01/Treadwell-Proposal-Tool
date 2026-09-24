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

The stamp is now a hash of the file's bytes (and of the id walk's version, below):
`sha256:<16 hex>`.

LEGACY STAMPS. Drafts and pinned revisions saved before this change hold the old all-digit mtime.
One is accepted when the file still has the content recorded in `LEGACY_MTIME_FLOOR_S` AND the
stamp was taken at or after the moment that content landed on `main`. A container cannot stamp an
mtime later than that while still holding older content, so an accepted stamp was captured against
these exact paragraphs. An earlier stamp described a different walk and is refused, as before.

Edit a template and its entry stops matching by itself, so every legacy stamp for it is refused,
which is right: they were all taken against the old paragraphs.
`test_template_version_is_content.py` names the entry to delete. Never add one: from this change
on, every new stamp is a hash.

A LEGACY STAMP NAMES NO FILE. Every template in one image shared the same mtime, so the number
cannot say whether it was taken on Epoxy or on Polish. Nothing may pair a legacy stamp with
overrides captured on a different template than the one being rendered: syncPayloadPricing and
the Done page's rebuild clear or withhold them when the template changed (checked against prod on
2026-09-25: no draft carried such a pairing).

THE ID WALK. An override id is a position in `proposal_writer.iter_editable_blocks`, so the
numbering code is part of what a stamp describes. `WALK_VERSION` is folded into every hash: bump
it when the walk changes, and every saved stamp, legacy or hash, is refused. A test fingerprints
the walk's source so a change cannot land without the bump.
"""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path

TEMPLATES_ROOT = Path(__file__).parent / "templates"

# The id walk's own version (see THE ID WALK above). Bumping it refuses every saved stamp, so do it
# only when `iter_editable_blocks` or what it calls would number a template's paragraphs
# differently — and then delete every LEGACY_MTIME_FLOOR_S entry too, which the tests will demand.
WALK_VERSION = "1"

# Relative template path -> (content version, the commit time in whole seconds at which THAT
# content landed on origin/main, first-parent). Taken from `git log -1 --first-parent --format=%ct
# origin/main -- <path>` on 2026-09-25. Staging got each file a few minutes to an hour earlier, so
# a staging draft stamped in that gap is refused — conservative, and staging holds test data only.
LEGACY_MTIME_FLOOR_S: dict[str, tuple[str, int]] = {
    "Direct/XX.XX TREADWELL EPOXY PROPOSAL - New Direct.docx": ("sha256:0dd6b2768e2fe68b", 1784143397),
    "Direct/xx.xx TREADWELL POLISH PROPOSAL - NewDirect.docx": ("sha256:1d5dd2991cdde3a7", 1784143397),
    "Direct/xx.xx.xx TREADWELL COMBO PROPOSAL - CUSTMOER NAME.docx": ("sha256:c5081c2a2119724d", 1784145619),
    "Direct/xx.xx TREADWELL BUDGET PRICING.docx": ("sha256:ddc026f7c1fe3969", 1780072749),
    "GC/xx TREADWELL RESINOUS PROPOSAL - xx.docx": ("sha256:efce3be0bb01b30b", 1788900501),
    "GC/xx TREADWELL POLISH PROPOSAL - xx.docx": ("sha256:1718cfc8beccd7fc", 1788900501),
    "GC/xx TREADWELL SEALER PROPOSAL - xx.docx": ("sha256:b6314baffaa0f725", 1783698162),
    "Gyp/xx TREADWELL UNDERLAYMENT PROPOSAL - xx.docx": ("sha256:be7b89913c90dc7f", 1784325215),
    "CoverLetter/Direct/Epoxy.docx": ("sha256:7c18890584362022", 1789041976),
    "CoverLetter/Direct/Polish.docx": ("sha256:6c2a87ace1615e49", 1789041976),
    "CoverLetter/Direct/Combo.docx": ("sha256:b8bf7aefcfe97e7e", 1789041976),
    "CoverLetter/GC/Epoxy.docx": ("sha256:f6808d5482ae662c", 1789041976),
    "CoverLetter/GC/Polish.docx": ("sha256:0b158cc6339ff031", 1789041976),
    "CoverLetter/GC/Combo.docx": ("sha256:20d9ec5cb737bd12", 1789041976),
    "CoverLetter/Gyp/Gyp.docx": ("sha256:19d3006f06a45b82", 1789041976),
}

# Hashing a template is ~1 ms, and /api/proposal-template needs the version before it can answer a
# 304, so the digest is memoised on what `stat()` says. A file whose mtime or size moved is re-read;
# one that did not is not. Bounded by the handful of template files plus whatever a test copies.
_HASHES: dict[tuple[str, int, int], str] = {}
_HASHES_LOCK = threading.Lock()


def _digest(path: Path, salt: bytes) -> str:
    try:
        st = path.stat()
    except OSError:
        return "0"
    key = (str(path), st.st_mtime_ns, st.st_size, salt)
    with _HASHES_LOCK:
        hit = _HASHES.get(key)
    if hit is not None:
        return hit
    try:
        digest = "sha256:" + hashlib.sha256(salt + path.read_bytes()).hexdigest()[:16]
    except OSError:
        return "0"
    with _HASHES_LOCK:
        if len(_HASHES) > 256:
            _HASHES.clear()
        _HASHES[key] = digest
    return digest


def content_version(path: Path) -> str:
    """`sha256:<16 hex>` of a .docx template's bytes and the id walk's version, or "0" when the
    file cannot be read. For a document whose overrides are keyed by the walk."""
    return _digest(path, b"walk:" + WALK_VERSION.encode() + b"\0")


def file_version(path: Path) -> str:
    """`sha256:<16 hex>` of the file's bytes alone, for a template whose saved edits do not use
    the paragraph walk (the Info Sheet workbook), so a WALK_VERSION bump cannot discard them."""
    return _digest(path, b"")


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
    # A legacy stamp is a bare st_mtime_ns: nineteen digits today, never fewer than ten. ASCII
    # digits only: str.isdigit() also accepts superscripts, which int() then refuses with a 500.
    if len(pinned) >= 10 and pinned.isascii() and pinned.isdigit():
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
