"""The frontend the container serves must be the same program as the frontend in git.

`docker build` runs tools/strip-comments.js over /app/frontend, so the bytes a browser
downloads are not the bytes in this repo. That is the exact shape of defect this project
has been bitten by before — a suite that is green about source it is no longer shipping —
so the difference is not taken on trust here. It is re-derived from the actual output of
the actual tool on every run.

WHY THE TOOL ONLY REMOVES COMMENTS. Measured on this tree: point the suite at a
terser-minified frontend and 1,797 of its 2,786 assertions stop working (164 fail, 1,633
error), because the harnesses under tests/js/ lift functions out of the real files with
line-anchored regexes and a mangled one-line file has nothing for them to match. Comment
removal keeps every line, so they still match, and 37 of the 52 harnesses produce
byte-identical output from either tree — which is what test_the_harnesses_read_the_stripped
_tree_the_same_way_they_read_the_source below actually checks, rather than assumes.

WHAT MAKES THE TRANSFORM SAFE, and which test carries each half:

  only comment spans leave        test_only_comment_spans_were_removed walks source and
                                  output character by character and refuses any difference
                                  that does not begin "//" or "/*"
  no string is mistaken for one   test_a_url_inside_a_string_is_not_mistaken_for_a_comment
                                  compares every string literal in both files — frontend JS
                                  is full of https:// inside quotes
  no token can be glued to the    a block comment spanning no newline becomes a SPACE, so
  next one                        a/*x*/b is a b and never ab
  ASI cannot shift                test_every_line_and_every_line_ending_survives — no
                                  newline is ever added or removed, CRLF included
  it still parses                 test_every_stripped_file_still_parses (node --check)
  the 304s survive                test_the_mtime_survives_so_the_etag_does — Starlette's
                                  ETag is md5("<st_mtime>-<st_size>") and
                                  NoCacheStaticFiles in main.py is built on it

Skipped when node or acorn is missing; CI installs both.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
TOOL = ROOT / "tools" / "strip-comments.js"
DOCKERFILE = ROOT / "Dockerfile"
CI = ROOT / ".github" / "workflows" / "ci.yml"
ACORN_PIN = "acorn@8.18.0"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is not installed")


def _served(tree):
    """Every file the stripper touches, relative to a frontend dir."""
    return sorted((p.relative_to(tree) for p in tree.rglob("*")
                   if p.suffix in (".js", ".css")), key=str)


# ── the wiring, checked without running anything ────────────────────────────────

def test_the_dockerfile_runs_the_stripper_over_the_served_frontend():
    """A tool nothing invokes is a tool that saves nothing, and this whole file would then
    be testing a transform production never applies."""
    df = DOCKERFILE.read_text(encoding="utf-8")
    assert "COPY tools/strip-comments.js" in df, "the image never receives the stripper"
    assert re.search(r"node\s+/tmp/strip-comments\.js\s+/app/frontend", df), (
        "the stripper is copied in but never run over /app/frontend")
    assert TOOL.exists(), "the Dockerfile references a tool that is not in the repo"


def test_the_acorn_pin_is_the_same_in_the_build_and_in_ci():
    """The image and CI must strip with the same parser. Two pins that drift would mean CI
    proving something about a transform the build no longer performs."""
    assert ACORN_PIN in DOCKERFILE.read_text(encoding="utf-8")
    assert ACORN_PIN in CI.read_text(encoding="utf-8"), (
        "CI does not install the pinned acorn, so every test below would skip there")


def test_the_repo_source_still_has_its_comments():
    """The tool must never be pointed at this working tree. If it ever is, the comments that
    carry this codebase's reasoning are gone from git, and this is the tripwire."""
    src = (FRONTEND / "js" / "crm-core.js").read_text(encoding="utf-8")
    assert src.count("//") > 50, "frontend/js/crm-core.js has lost its comments"
    assert len(_served(FRONTEND)) >= 15


# ── run the real tool over a copy of the real frontend ──────────────────────────

@pytest.fixture(scope="module")
def stripped(tmp_path_factory):
    probe = subprocess.run(["node", "-e", "require.resolve('acorn')"],
                           cwd=str(TOOL.parent), capture_output=True, text=True, timeout=60)
    if probe.returncode != 0:
        pytest.skip("acorn is not installed - run `npm install --no-save %s` in the repo "
                    "root (CI does this)" % ACORN_PIN)
    base = tmp_path_factory.mktemp("served")
    tree = base / "frontend"
    shutil.copytree(FRONTEND, tree)              # copytree uses copy2, so mtimes come too
    # polish-intake-harness.js reads ../backend/reference_tax.py, so give the copy the
    # sibling it expects; without it that harness fails on one tree and not the other for
    # a reason that has nothing to do with stripping.
    (base / "backend").mkdir()
    shutil.copy2(ROOT / "backend" / "reference_tax.py", base / "backend" / "reference_tax.py")
    proc = subprocess.run(["node", str(TOOL), str(tree)],
                          capture_output=True, text=True, encoding="utf-8", timeout=600)
    assert proc.returncode == 0, (
        "the stripper itself failed - this is what the docker build would do:\n"
        + proc.stderr)
    return tree


def test_there_is_something_to_strip(stripped):
    """Guards every assertion below against passing because the glob came back empty."""
    assert _served(stripped) == _served(FRONTEND)
    assert len(_served(stripped)) >= 15
    assert pathlib.Path("styles.css") in _served(stripped)


def test_it_removes_most_of_the_comment_bytes(stripped):
    """The point of the exercise. Measured at the time of writing: 2,494,014 raw bytes of
    JS+CSS down to 1,355,351, which is 817,605 gzipped bytes down to 355,992 on the wire.
    The floor here is deliberately well below that — it is a tripwire for the transform
    silently becoming a no-op, not a target to tune against."""
    before = sum((FRONTEND / f).stat().st_size for f in _served(FRONTEND))
    after = sum((stripped / f).stat().st_size for f in _served(stripped))
    assert before > 2_000_000, before
    assert after < before * 0.75, (
        "stripping removed only %d of %d bytes - has it stopped working?" % (before - after,
                                                                             before))


def test_every_line_and_every_line_ending_survives(stripped):
    """Two things at once. The harnesses match line-anchored patterns against these files,
    and automatic semicolon insertion is decided by where the newlines are — so adding or
    removing even one would change the program. CRLF is checked as well as the count,
    because this repo is CRLF throughout and half the harnesses say so in their comments."""
    for f in _served(FRONTEND):
        a = (FRONTEND / f).read_bytes()
        b = (stripped / f).read_bytes()
        assert a.count(b"\n") == b.count(b"\n"), "%s changed line count" % f
        assert a.count(b"\r\n") == b.count(b"\r\n"), "%s changed line endings" % f


def test_the_mtime_survives_so_the_etag_does(stripped):
    """NoCacheStaticFiles in main.py serves the frontend `no-cache, must-revalidate` and
    relies on Starlette's ETag, which is md5("<st_mtime>-<st_size>"), to answer 304 for a
    file a deploy did not change. Writing a file gives it a fresh mtime. If the stripper
    did not put the original back, every deploy would re-send every asset to every browser
    — a regression bigger than the saving this whole change buys."""
    for f in _served(FRONTEND):
        a = int((FRONTEND / f).stat().st_mtime)
        b = int((stripped / f).stat().st_mtime)
        assert a == b, "%s came out with a different mtime (%s vs %s)" % (f, a, b)


def test_only_comment_spans_were_removed(stripped):
    """The core proof, and it is a proof rather than a sample: walk the two files together
    and refuse any divergence that is not a comment starting exactly where the source
    diverges. Everything else this file asserts is a consequence of this one holding."""
    total_removed = 0
    for f in _served(FRONTEND):
        src = (FRONTEND / f).read_text(encoding="utf-8")
        out = (stripped / f).read_text(encoding="utf-8")
        i = j = 0
        while i < len(src):
            if j < len(out) and src[i] == out[j]:
                i += 1
                j += 1
                continue
            if src.startswith("//", i) and not f.suffix == ".css":
                k = i
                while k < len(src) and src[k] not in "\r\n":
                    k += 1
                repl = ""
            elif src.startswith("/*", i):
                k = src.find("*/", i + 2)
                k = len(src) if k < 0 else k + 2
                nl = "".join(c for c in src[i:k] if c in "\r\n")
                repl = nl if nl else " "
            else:
                pytest.fail(
                    "%s diverges at offset %d and it is not the start of a comment - the "
                    "stripper changed something it is not allowed to change.\n"
                    "  source  : %r\n  stripped: %r" % (f, i, src[i:i + 90], out[j:j + 90]))
            assert out[j:j + len(repl)] == repl, (
                "%s: the comment at offset %d was replaced by %r, not by %r" % (
                    f, i, out[j:j + len(repl)], repl))
            total_removed += k - i
            i = k
            j += len(repl)
        assert j == len(out), "%s has trailing bytes the source does not explain" % f
    assert total_removed > 900_000, (
        "only %d bytes of comment were accounted for - the walk is not seeing the real "
        "transform" % total_removed)


def test_every_stripped_file_still_parses(stripped):
    """`node --check` on what actually ships. tests/test_frontend_js_parses.py does this for
    the repo's copy; a syntax error introduced by the build would be invisible to it."""
    checked = 0
    for f in _served(stripped):
        if f.suffix != ".js":
            continue
        proc = subprocess.run(["node", "--check", str(stripped / f)],
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        assert proc.returncode == 0, "%s does not parse after stripping:\n%s" % (f, proc.stderr)
        checked += 1
    assert checked >= 15, checked


def test_a_url_inside_a_string_is_not_mistaken_for_a_comment(stripped, tmp_path):
    """The one way a comment stripper corrupts a file quietly. The frontend is full of
    "https://..." inside quotes, and a scanner that treated that // as a comment would eat
    the rest of the line and leave something that might still parse. Compared literal by
    literal rather than by counting: acorn reports every string and template in a file, so
    the two lists have to be equal."""
    # `require` resolves from the SCRIPT's directory and this one lives in a tmp dir, so
    # acorn is handed over by absolute path -- the same copy the stripper itself used.
    where = subprocess.run(["node", "-e", "process.stdout.write(require.resolve('acorn'))"],
                           cwd=str(TOOL.parent), capture_output=True, text=True, timeout=60)
    assert where.returncode == 0, where.stderr
    script = tmp_path / "literals.js"
    script.write_text(
        "const fs=require('fs'),acorn=require(%s),out=[];\n" % json.dumps(where.stdout) +
        "acorn.parse(fs.readFileSync(process.argv[2],'utf8'),{ecmaVersion:'latest',\n"
        "  allowReturnOutsideFunction:true,onToken:(t)=>{\n"
        "    if(t.type.label==='string'||t.type.label==='template')out.push(String(t.value));\n"
        "  }});\n"
        "process.stdout.write(JSON.stringify(out));\n", encoding="utf-8")

    def literals(path):
        p = subprocess.run(["node", str(script), str(path)], capture_output=True, text=True,
                           encoding="utf-8", timeout=120, cwd=str(TOOL.parent))
        assert p.returncode == 0, p.stderr
        return p.stdout

    compared = 0
    with_scheme = 0
    for f in _served(FRONTEND):
        if f.suffix != ".js":
            continue
        a = literals(FRONTEND / f)
        assert literals(stripped / f) == a, (
            "%s lost or changed a string literal - something inside quotes was treated as "
            "a comment" % f)
        compared += a.count(",") + 1
        with_scheme += a.count("://")
    # Non-vacuity, pinned to what is actually in the tree: ~16,370 literals, of which
    # exactly 3 carry a URL scheme (calendar.js's BasisBoard link and index.js's two
    # Photon lookups -- the CDN tags live in the HTML, not the JS). The floors are below
    # those so an ordinary edit does not trip them, but a comparison that had quietly
    # stopped reading anything would.
    assert compared > 5_000, "only %d literals were compared" % compared
    assert with_scheme >= 3, (
        "no URL survived inside a string literal, so the specific hazard this test exists "
        "for was never exercised")


def test_the_harnesses_read_the_stripped_tree_the_same_way_they_read_the_source(stripped):
    """The empirical half, and the reason this change is shippable at all.

    Each harness under tests/js/ loads the real frontend, executes real product code and
    prints its result. Run every one of them against both trees: if stripping changed the
    program, the JSON changes. 37 of the 52 agree byte for byte and 5 more fail identically
    on both (they need argv this test does not supply).

    Two kinds of disagreement are expected and are NOT the product behaving differently:

      * a handful of harnesses stamp `new Date()` into their output, so two runs of the
        SAME tree already differ. Those are detected here by re-running the source, not by
        pattern-matching timestamps, so the exemption cannot go stale.

      * the seven named below locate code by matching COMMENT TEXT — "the listener anchored
        on '  // Mark blocks dirty as they're edited'", or in library-ui's case a regex with
        `\\/\\/[^\\n]*` in the middle of it. They are asserting something about the source
        file, which is unchanged in git; the code they anchor is still there in the image.
        Read that as a coupling worth knowing about, not as a defect in the stripper.
    """
    comment_anchored = {
        "doc-editor-harness.js", "doc-editor-fidelity-harness.js",
        "doc-editor-labels-harness.js", "editor-paste-and-save-harness.js",
        "editor-undo-harness.js", "fmt-ribbon-harness.js", "library-ui-harness.js",
    }
    harnesses = sorted((ROOT / "backend" / "tests" / "js").glob("*-harness.js"))
    assert len(harnesses) >= 45, len(harnesses)

    def run(h, tree):
        p = subprocess.run(["node", str(h), str(tree)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300)
        scrub = lambda s: (s or "").replace(str(tree), "<TREE>").replace(
            str(tree).replace("\\", "/"), "<TREE>").replace(str(tree).replace("\\", "\\\\"),
                                                            "<TREE>")
        return p.returncode, scrub(p.stdout), scrub(p.stderr)

    agreed = 0
    disagreed = []
    for h in harnesses:
        first = run(h, FRONTEND)
        if run(h, stripped) == first:
            if first[0] == 0:
                agreed += 1
            continue
        if run(h, FRONTEND) != first:
            continue                              # non-deterministic on its own, exempt
        if h.name in comment_anchored:
            continue
        disagreed.append(h.name)

    assert not disagreed, (
        "these harnesses execute the real frontend and got a DIFFERENT answer from the "
        "stripped tree - the transform changed the program: %s" % disagreed)
    assert agreed >= 30, (
        "only %d harnesses ran clean on both trees; this test is not proving much any "
        "more" % agreed)
