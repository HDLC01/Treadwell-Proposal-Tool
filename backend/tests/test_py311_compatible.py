"""Every backend module has to parse on Python 3.11 — what the container runs.

The dev box is on a much newer interpreter, and PEP 701 (3.12) relaxed f-strings: a
backslash inside a `{...}` expression, and reusing the outer quote character, both
became legal. Write either one and the whole test suite passes locally while the
container dies on `import` with a SyntaxError — which is exactly how the digest email
took the portal's staging down.

CI runs 3.11, and for this repo a merge is genuinely in the path — but the identical
mistake took the portal's staging down on 2026-08-01, and waiting for a CI job to tell
you your f-string is invalid is a slow way to learn it. Same guard, both repos.
"""
import ast
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
MODULES = sorted(p for p in BACKEND.glob("*.py"))


def test_there_are_modules_to_check():
    """A layout change that empties the glob would make the test below vacuous."""
    names = {p.name for p in MODULES}
    assert {"main.py", "drafts.py", "digest_worker.py"} <= names


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_no_backslash_inside_an_f_string_expression(path):
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FormattedValue):
            continue
        # The expression's own source text, not the surrounding literal — a
        # backslash elsewhere in the f-string is fine.
        seg = ast.get_source_segment(src, node.value)
        if seg and "\\" in seg:
            bad.append((node.lineno, seg[:80]))
    assert not bad, (
        f"{path.name} has a backslash inside an f-string expression at "
        + ", ".join(f"line {ln}: {s!r}" for ln, s in bad)
        + " — legal on this interpreter, a SyntaxError on the container's 3.11. "
        "Build the fragment into a variable first."
    )
