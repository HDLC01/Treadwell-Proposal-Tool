"""Treadwell's licensed proposal typeface, served to signed-in staff and to nobody else.

Hanz, 2026-09-26: "why are the fonts and font sizes still not fixed?" The proposal templates are
typeset in Zetta Serif, and the PDF prints in it (LibreOffice in the container, fonts installed from
backend/fonts/ by the Dockerfile). The Proposal Review editor named the same family in its CSS but
never LOADED it, so on every machine without the font installed it drew Georgia instead. Georgia is
wider, so the editor also wrapped, shrank and clipped boxes that the PDF does not.

Zetta Serif is a LICENSED font. Hanz approved serving it to staff from the app on the condition that
it stays behind the login, so:

  * it is served from an /api route, which puts it behind the Supabase auth middleware every other
    staff route sits behind (`_auth_gate` in main.py) -- an unauthenticated request is refused
    before routing, so no public URL returns these bytes;
  * the files live in backend/fonts/, outside the frontend/ directory the static mount serves;
  * the request names a font by a fixed PUBLIC NAME, and that name is looked up in `FONTS` below.
    Nothing a request carries is ever joined onto a path: a name that is not a key there resolves
    to nothing and the filesystem is never touched.

The browser side is frontend/js/proposal-fonts.js, which fetches both files with the staff bearer
token and registers them through the FontFace API.
"""
import hashlib
import pathlib
import threading
from typing import Dict, Optional, Tuple

# Public name -> file in backend/fonts/. The ONLY route from a request to a file.
FONTS: Dict[str, str] = {
    "zetta-serif-book": "Zetta Serif-Book.otf",
    "zetta-serif": "Zetta Serif.otf",
}

MEDIA_TYPE = "font/otf"

# `private` because the response is for one signed-in user: no shared cache (a proxy, a CDN) may
# keep a copy and hand it to somebody who is not signed in. A year and `immutable` because the file
# never changes under a given URL -- frontend/js/proposal-fonts.js puts a VERSION in the query string
# and bumps it when a file here changes (test_proposal_fonts.py pins the hashes to catch that).
CACHE_CONTROL = "private, max-age=31536000, immutable"

_HERE = pathlib.Path(__file__).resolve().parent

# Where the files are read from, in order:
#   1. backend/fonts/ next to this module. In the image that is /app/fonts, because the Dockerfile
#      does `COPY backend/ /app/` with WORKDIR /app and .dockerignore excludes nothing under it.
#   2. The system copy the Dockerfile installs for LibreOffice. Only a fallback, in case a later
#      image stops shipping the app-tree copy.
FONT_DIRS: Tuple[pathlib.Path, ...] = (
    _HERE / "fonts",
    pathlib.Path("/usr/share/fonts/truetype/treadwell"),
)

_cache: Dict[str, Tuple[bytes, str]] = {}
_lock = threading.Lock()


def load(name: object) -> Optional[Tuple[bytes, str]]:
    """(bytes, etag) for a whitelisted public font name, or None.

    None for a name that is not in `FONTS` -- decided before any path is built -- and for a
    whitelisted font whose file is missing from every directory in `FONT_DIRS`. The bytes are read
    once per process and kept: two files, about 190 KB between them."""
    if not isinstance(name, str):
        return None
    filename = FONTS.get(name)
    if filename is None:
        return None
    with _lock:
        hit = _cache.get(name)
        if hit is not None:
            return hit
        for folder in FONT_DIRS:
            try:
                data = (folder / filename).read_bytes()
            except OSError:
                continue
            etag = '"' + hashlib.sha256(data).hexdigest()[:32] + '"'
            _cache[name] = (data, etag)
            return _cache[name]
    return None


def cache_clear() -> None:
    """Forget what has been read (tests that move the files use this)."""
    with _lock:
        _cache.clear()
