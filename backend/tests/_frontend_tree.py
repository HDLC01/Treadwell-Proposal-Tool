"""The frontend's pages and scripts, in every sub-folder, named by their path under frontend/.

WHY A SHARED HELPER. The page-structure tests (boot order, CDN preconnect, hidden-is-hidden, scripts
parse, static caching, icons, nav access...) used to look at frontend/*.html and frontend/js/*.js
and name what they found by its bare file name. The BD CRM is moving in under /bd/ (spec #802), with
pages named index.html, admin.html and analytics.html, the same names as pages at the root. A glob of
the top folder would skip those pages without a word, and a result keyed by file name would fold
bd/admin.html into admin.html. So every scan walks the whole tree and keys by the path relative to
frontend/, as a posix string: "admin.html", "js/admin.js", "bd/admin.html".

Each function takes the folder to walk, so a test can point it at a small tree of its own and prove
a page or script placed in a sub-folder is seen.
"""
from __future__ import annotations

import pathlib

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"


def files(*suffixes: str, frontend: pathlib.Path = FRONTEND) -> list[pathlib.Path]:
    """Every file under `frontend`, at any depth, whose suffix is one of `suffixes`, sorted by path."""
    wanted = {s.lower() for s in suffixes}
    return sorted(p for p in frontend.rglob("*") if p.is_file() and p.suffix.lower() in wanted)


def pages(frontend: pathlib.Path = FRONTEND) -> list[pathlib.Path]:
    """Every .html page under `frontend`, at any depth."""
    return files(".html", frontend=frontend)


def scripts(frontend: pathlib.Path = FRONTEND) -> list[pathlib.Path]:
    """Every .js file under `frontend`, at any depth."""
    return files(".js", frontend=frontend)


def rel(path: pathlib.Path, frontend: pathlib.Path = FRONTEND) -> str:
    """`path` named the way every scan keys it: relative to `frontend`, with forward slashes."""
    return pathlib.Path(path).relative_to(frontend).as_posix()


def write_tree(root: pathlib.Path, files: dict) -> pathlib.Path:
    """Write {path under root: text} into `root`, making folders as needed, and return `root`. For the
    tests that prove a scan sees a page or script placed in a sub-folder."""
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root
