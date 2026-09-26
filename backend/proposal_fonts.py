"""Treadwell's licensed proposal typeface: where the server finds it, and the route that hands it
to signed-in staff.

Hanz, 2026-09-26: "why are the fonts and font sizes still not fixed?" The proposal templates are
typeset in Zetta Serif, and the PDF prints in it (LibreOffice in the container, which finds fonts
through fontconfig). The Proposal Review editor named the same family in its CSS but never LOADED
it, so on every machine without the font installed it drew Georgia instead. Georgia is wider, so
the editor also wrapped, shrank and clipped boxes that the PDF does not.

WHERE THE FILES COME FROM. Zetta Serif is a LICENSED font. Hanz, 2026-09-26: "Move font off
GitHub." Since then neither the repository (public) nor the image (pushed to GHCR) carries it: the
SERVER supplies it at runtime.
  * On the VPS the two files sit in /opt/treadwell-fonts (HOST_DIR), and both compose files
    bind-mount that directory read-only onto MOUNT_DIR, which the Dockerfile leaves empty for it.
    MOUNT_DIR is under /usr/share/fonts, so LibreOffice's fontconfig finds the same files this
    route serves. fontconfig rescans a directory whose mtime no longer matches its cache, and the
    image's cache records MOUNT_DIR empty at build time, so nothing has to run fc-cache at start.
  * On a dev box they sit in backend/fonts/, which .gitignore keeps out of git and .dockerignore
    keeps out of any image built from the working tree (deploy/ship.sh builds from it). In the
    image that directory is /app/fonts and holds only its README.
  * The lasting copy is neither of those: it is the team Dropbox folder that backend/fonts/README.md
    names, with the sha256 of each file. Git deletes the files from every checkout that moves past
    the commit that untracked them, so each deploy path copies them from its own VPS checkout into
    HOST_DIR before its first such pull, and a new box or dev checkout copies them from Dropbox.

A MISSING FILE IS NOT AN ERROR ANYWHERE, and that is the danger. Docker creates a missing host
directory as an EMPTY one, so a box without the files boots, passes its healthcheck and prints
every PDF in a substitute font. So `report_once` says so, loudly, once per process, from a startup
hook in main.py. /healthz does not look: a liveness probe has to stay cheap and must never flap on
a font. The deploy workflow refuses to deploy while either file is missing from HOST_DIR, and the
route below answers 404 for a file that is not there, which the editor takes quietly (it keeps its
fallback serif). A file placed after start is picked up without a restart: only a hit is cached.

THE ROUTE. Hanz approved serving the font to staff from the app on the condition that it stays
behind the login. GET /api/proposal-font/{name} (main.py) is the only way the app hands the files
out, and it keeps to that condition:
  * it is served from an /api route, which puts it behind the Supabase auth middleware every other
    staff route sits behind (`_auth_gate` in main.py) -- an unauthenticated request is refused
    before routing, so no URL of THIS APP returns these bytes to a signed-out caller;
  * neither directory it reads is under the frontend/ directory the static mount serves;
  * the request names a font by a fixed PUBLIC NAME, and that name is looked up in `FONTS` below.
    Nothing a request carries is ever joined onto a path: a name that is not a key there resolves
    to nothing and the filesystem is never touched.

The browser side is frontend/js/proposal-fonts.js, which fetches both files with the staff bearer
token and registers them through the FontFace API.

WHAT THIS DOES NOT UNDO. The files were tracked in git until 2026-09-26, so the public
repository's HISTORY still holds them, and every image built before that date carries
them (at /usr/share/fonts/truetype/treadwell and /app/fonts) in GHCR. Making the GHCR package
private and rewriting the history are repository and registry decisions for Hanz; nothing in this
file can do either.
"""
import hashlib
import logging
import pathlib
import threading
from typing import Dict, List, Optional, Tuple

# Public name -> file name. The ONLY route from a request to a file.
FONTS: Dict[str, str] = {
    "zetta-serif-book": "Zetta Serif-Book.otf",
    "zetta-serif": "Zetta Serif.otf",
}

MEDIA_TYPE = "font/otf"

# `private` because the response is for one signed-in user: no shared cache (a proxy, a CDN) may
# keep a copy and hand it to somebody who is not signed in. A year and `immutable` because the file
# never changes under a given URL -- frontend/js/proposal-fonts.js puts a VERSION in the query string
# and bumps it when a file changes (test_proposal_fonts.py pins the hashes to catch that).
CACHE_CONTROL = "private, max-age=31536000, immutable"

_HERE = pathlib.Path(__file__).resolve().parent

# The runtime mount point inside the container. Both compose files mount HOST_DIR here read-only.
MOUNT_DIR = pathlib.Path("/usr/share/fonts/truetype/treadwell")
# Where the files go on the VPS. The app never reads it (it is outside the container); it is here
# so the startup warning can say where to put them.
HOST_DIR = "/opt/treadwell-fonts"

# Where the files are read from, in order: the mount, then backend/fonts/ for local dev.
FONT_DIRS: Tuple[pathlib.Path, ...] = (
    MOUNT_DIR,
    _HERE / "fonts",
)

_cache: Dict[str, Tuple[bytes, str]] = {}
_lock = threading.Lock()
_reported = False


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


def missing() -> List[str]:
    """The file names in `FONTS` found in none of `FONT_DIRS`, in `FONTS` order."""
    return [filename for filename in FONTS.values()
            if not any((folder / filename).is_file() for folder in FONT_DIRS)]


def report_once(logger: logging.Logger) -> bool:
    """Log whether the proposal font is installed, once per process. True if this call logged.

    One INFO line when both files are there. Otherwise one WARNING that names what is missing,
    where the app looked, what that costs and where the files go -- written to be found by
    `docker compose logs | grep -i font` on a box that looks perfectly healthy."""
    global _reported
    with _lock:
        if _reported:
            return False
        _reported = True
    gone = missing()
    looked = " and ".join(folder.as_posix() for folder in FONT_DIRS)
    if not gone:
        logger.info("Proposal font: Zetta Serif is installed (%s).",
                    ", ".join(sorted(FONTS.values())))
        return True
    which = ("neither Zetta Serif file (%s) is" % ", ".join(gone)
             if len(gone) == len(FONTS) else "%s is" % ", ".join(gone))
    logger.warning(
        "PROPOSAL FONT MISSING: %s in %s. Proposal PDFs will print in a substitute font and the "
        "editor falls back to Georgia. Put %s in %s on the host (compose mounts it read-only at "
        "%s), then restart the container.",
        which, looked, " and ".join('"%s"' % f for f in FONTS.values()), HOST_DIR,
        MOUNT_DIR.as_posix())
    return True
