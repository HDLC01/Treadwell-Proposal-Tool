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


def break_source(tmp_path: pathlib.Path, rel: str, old: str, new: str) -> pathlib.Path:
    """A frontend directory holding a copy of `rel` with `old` replaced by `new`.

    `old` must be a single line of text (no newline in it), so CRLF and LF checkouts both match.
    Returns the directory to hand a generator as its <frontend-dir>."""
    assert "\n" not in old and "\r" not in old, "anchor mutations on one line"
    src = (FRONTEND / rel).read_bytes().decode("utf-8")
    seen = src.count(old)
    assert seen == 1, "the mutation anchor %r appears %d times in %s, not once: it would apply nowhere " \
        "or everywhere, and the test would prove nothing" % (old, seen, rel)
    target = tmp_path / "frontend" / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(src.replace(old, new).encode("utf-8"))
    return tmp_path / "frontend"
