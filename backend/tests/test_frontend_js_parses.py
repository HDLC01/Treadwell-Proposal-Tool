"""Every frontend JavaScript file must actually parse.

This exists because of a real outage on staging, 2026-08-03. A CSS comment inside
`auth.js` was given backticks for emphasis:

    `middle`, not a pixel offset: ...

The whole injected stylesheet in that file is a JS **template literal** (`const css = ` +
backtick), so the first backtick in that comment ended the string and the rest of the file
became syntactic garbage. `auth.js` stopped parsing entirely.

The symptom was nothing like the cause. `auth.js` is what mints the bearer token, so every
page loaded, rendered its chrome, and then answered 401 on every single API call — which
reads exactly like an expired session or a broken backend. It cost a round of misdiagnosis
before the console's one-line "Unexpected identifier 'middle'" gave it away.

Nothing in the suite parsed the frontend JS, so 1,100 passing tests said nothing about it.
This closes that hole: a syntax error anywhere in the frontend now fails the build instead
of shipping.

Skipped when node isn't installed; it's on the dev box and in the Docker image.
"""
import pathlib
import shutil
import subprocess

import pytest

from _frontend_tree import pages, rel, scripts, write_tree

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                               reason="node is not installed")


def js_files(frontend=FRONTEND):
    """Every script, in every sub-folder (#804)."""
    return scripts(frontend)


def test_there_are_js_files_to_check():
    """A move or a rename that emptied the glob would make every check below vacuously
    pass — which is the failure mode this whole file exists to prevent."""
    names = {rel(p) for p in js_files()}
    assert {"auth.js", "shared.js", "js/crm-core.js"} <= names, names
    assert len(js_files()) >= 15


@pytest.mark.parametrize("path", js_files(), ids=rel)
def test_it_parses(path):
    """`node --check` parses without executing, so it needs no DOM and no browser.

    It catches the whole family this belongs to: an unterminated template literal, a stray
    backtick in a comment, an unbalanced brace, a trailing comma where one isn't allowed."""
    proc = subprocess.run(["node", "--check", str(path)],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, (
        f"{rel(path)} does not parse — every page that loads it will break:\n{proc.stderr}")


def test_the_injected_stylesheet_contains_no_backtick():
    """The specific trap, pinned at the exact spot it sprang.

    `auth.js` builds its stylesheet as a template literal, and that CSS is long, commented,
    and edited often — it is the natural place to reach for backticks when quoting a
    property name. One is enough to end the string. Checked as a rule rather than left to
    the parse test above, so the failure names the cause instead of pointing at line 439."""
    src = (FRONTEND / "auth.js").read_text(encoding="utf-8")
    marker = "const css = `"
    assert marker in src, "auth.js no longer builds its CSS as a template literal"
    start = src.index(marker) + len(marker)
    end = src.index("`", start)
    body = src[start:end]
    assert "`" not in body                      # true by construction; kept as intent
    # The literal has to reach the end of the stylesheet. If a stray backtick truncated it,
    # the "string" would stop early and this last selector would fall outside it.
    assert ".tw-av{" in body, (
        "the CSS template literal ends before the person chip is defined — something "
        "inside it terminated the string early (a backtick in a comment?)")
    assert body.count("{") == body.count("}"), "unbalanced braces in the injected CSS"


def test_no_frontend_js_uses_an_inline_script_or_handler():
    """Adjacent rule, same blast radius: the CSP forbids inline `<script>` and `onclick=`,
    and a violation fails silently in the browser rather than at build time."""
    offenders = inline_scripts()
    assert not offenders, offenders


def inline_scripts(frontend=FRONTEND):
    """'<path under frontend/>: inline <script>' for every page, in every sub-folder (#804), with one."""
    offenders = []
    for page in pages(frontend):
        html = page.read_text(encoding="utf-8")
        for chunk in html.split("<script")[1:]:
            head, _, rest = chunk.partition(">")
            if "src=" not in head and rest.strip()[:200].strip():
                offenders.append(f"{rel(page, frontend)}: inline <script>")
    return offenders


def test_both_scans_see_a_page_or_script_in_a_sub_folder(tmp_path):
    """#804: the BD CRM's pages and scripts live under /bd/, named like the root's. Both scans walk
    the whole tree and name what they find by its path under frontend/."""
    write_tree(tmp_path, {
        "shared.js": "", "js/app.js": "", "bd/js/app.js": "",
        "index.html": '<script src="/shared.js"></script>',
        "bd/index.html": "<script>alert(1)</script>",
    })
    assert [rel(p, tmp_path) for p in js_files(tmp_path)] == ["bd/js/app.js", "js/app.js", "shared.js"]
    assert inline_scripts(tmp_path) == ["bd/index.html: inline <script>"]
