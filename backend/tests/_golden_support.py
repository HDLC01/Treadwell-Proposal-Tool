"""What the golden-master tests share: running a generator against a frontend, and breaking a
COPY of one source file on purpose to prove the golden notices.

A golden master that never fails proves nothing. test_polish_chain_golden.py and
test_library_pricing_golden.py each break a scratch copy of the module they record (a GP band, a
float guard, a negative zero, a NaN that becomes null) and require the comparison to go red with a
message that names the vector. `break_source` is how: it edits one line of one file in a temp
frontend directory, and it REFUSES to continue unless the line was there exactly once: a mutation
that silently applied nowhere (a line ending that does not match, a line that moved) would let
every one of those tests pass for the wrong reason.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil

from _node import run_node

TESTS = pathlib.Path(__file__).resolve().parent
JS = TESTS / "js"
FIXTURES = TESTS / "fixtures"
FRONTEND = TESTS.parents[1] / "frontend"


def compare(generator: str, golden: pathlib.Path, frontend: pathlib.Path = FRONTEND, *extra):
    """Run `node <generator> <frontend> --compare <golden> [extra...]`; returns the finished process."""
    return run_node(JS / generator, frontend, "--compare", golden, *extra)


def generate(generator: str, frontend: pathlib.Path = FRONTEND) -> str:
    """The golden the generator would write for this frontend, as text."""
    proc = run_node(JS / generator, frontend)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def load(golden: pathlib.Path) -> dict:
    return json.loads(golden.read_text(encoding="utf-8"))


# A core module says what must load before it in its header: `require("./excel-math.js")` for node and
# `root.TWExcelMath` for a page (docs/v2-architecture.md, section 4). A scratch frontend that holds only
# the file under test is not enough for such a module, because node cannot even load it. Reading the
# header, rather than keeping a list here, means a leaf added later (work-types, bid-profiles) needs no
# edit in this file or in any test that makes a scratch frontend.
_LOCAL_REQUIRE = re.compile(r"""require\(\s*["']\./([\w.-]+\.js)["']\s*\)""")
_HEADER_OPEN = "(function (root, factory)"
_HEADER_CLOSE = "})(typeof self"


def declared_dependencies(rel: str, frontend: pathlib.Path = FRONTEND) -> list[str]:
    """The files `rel` declares it needs loaded first, as paths under frontend/. Direct ones only.

    Read from the module's UMD header and nothing after it: a comment further down that names a file is
    not a dependency. A file with no such header declares none. `frontend` is the tree to read it from
    (the repository's, unless a test has built a small one of its own)."""
    text = (frontend / rel).read_bytes().decode("utf-8")
    start = text.find(_HEADER_OPEN)
    if start < 0:
        return []
    end = text.find(_HEADER_CLOSE, start)
    header = text[start:end if end > 0 else len(text)]
    folder = pathlib.PurePosixPath(rel).parent
    return [(folder / name).as_posix() for name in _LOCAL_REQUIRE.findall(header)]


def copy_unmodified(frontend: pathlib.Path, rels) -> None:
    """Put each of `rels` (paths under frontend/) into the scratch `frontend`, together with everything
    each one declares it needs, and what those need in turn. A file already there is left alone: it is
    the one under test."""
    todo, seen = list(rels), set()
    while todo:
        rel = todo.pop(0)
        if rel in seen:
            continue
        seen.add(rel)
        dest = frontend / rel
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(FRONTEND / rel, dest)
        todo.extend(declared_dependencies(rel))


def break_source(tmp_path: pathlib.Path, rel: str, old: str, new: str, also=()) -> pathlib.Path:
    """A frontend directory holding a copy of `rel` with `old` replaced by `new`.

    `old` must be a single line of text (no newline in it), so CRLF and LF checkouts both match.
    What `rel` declares it needs (js/excel-math.js for the model) is copied in beside it unmodified, and
    so is every file in `also` with what THAT needs: pass the dependents when `rel` is a leaf that a
    generator reaches only through them. Returns the directory to hand a generator as its
    <frontend-dir>."""
    assert "\n" not in old and "\r" not in old, "anchor mutations on one line"
    src = (FRONTEND / rel).read_bytes().decode("utf-8")
    seen = src.count(old)
    assert seen == 1, "the mutation anchor %r appears %d times in %s, not once: it would apply nowhere " \
        "or everywhere, and the test would prove nothing" % (old, seen, rel)
    target = tmp_path / "frontend" / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(src.replace(old, new).encode("utf-8"))
    copy_unmodified(tmp_path / "frontend", [rel, *also])
    return tmp_path / "frontend"
