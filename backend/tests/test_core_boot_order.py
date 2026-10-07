"""Every page that loads a core module runs what that module declares it needs, before it.

A core module says what it needs in its header (docs/v2-architecture.md, section 4):

    math: isNode ? require("./excel-math.js") : root.TWExcelMath

Under node `require` finds the file. On a page nothing finds it: the module reads the global the other
script published, so the other script's tag has to RUN first. Get that wrong and the page is dead on
arrival. `bid-model.js` throws "needs excel-math.js loaded before it", `var B = window.TWBidModel` is
then `undefined`, and the screen sits on its loading message. The page tests that pin an exact script
list catch a change on the pages they know about. This test does not know about any page. It DISCOVERS:

  * every script whose header declares a dependency, read from the header itself, so a leaf added in
    Phase 7 or 8 (work-types, bid-profiles) is covered the day it exists, with no list to keep;
  * every page that loads one;

and then checks two things on each such page.

  STATIC    the page loads each declared dependency, and the browser RUNS it first. A `defer`red leaf
            under a plain module is too late, and a script tag inside a comment is no tag at all.
  EXECUTED  the page's modules and what they need, in the page's own order, are run the way a browser
            runs them (tests/js/core-boot-harness.js: one fresh context, no `require`), and none throws.
            That is the header's browser path, the one `require` hides from every other test.

Both checks are tested against pages built to be wrong (a missing leaf, a late one, a deferred one, a
commented-out one, a dependency of a dependency), so neither can pass by finding nothing.

Run under node; a missing node FAILS under CI (tests/_node.py).
"""
from __future__ import annotations

import pathlib

from _golden_support import FRONTEND, declared_dependencies
from _node import last_json_line, require_node, run_node
from _page_scripts import local_scripts

BOOT = pathlib.Path(__file__).resolve().parent / "js" / "core-boot-harness.js"


# ── discovery ────────────────────────────────────────────────────────────────
def modules_with_dependencies(frontend: pathlib.Path):
    """{path under frontend/: the paths it declares} for every script whose header declares any."""
    found = {}
    for path in sorted([*frontend.glob("*.js"), *(frontend / "js").glob("*.js")]):
        rel = path.relative_to(frontend).as_posix()
        deps = declared_dependencies(rel, frontend)
        if deps:
            found[rel] = deps
    return found


def needed_with_dependencies(rels, modules):
    """`rels`, everything they declare, and what those declare in turn."""
    seen, todo = set(), list(rels)
    while todo:
        rel = todo.pop()
        if rel not in seen:
            seen.add(rel)
            todo.extend(modules.get(rel, []))
    return seen


def pages_with_modules(frontend: pathlib.Path):
    """(modules, pages): the discovered modules, and for every page that loads at least one of them
    (page name, its own scripts in the order a browser runs them, the modules among those)."""
    modules = modules_with_dependencies(frontend)
    pages = []
    for page in sorted(frontend.glob("*.html")):
        order = local_scripts(page.read_text(encoding="utf-8"))
        loaded = [s for s in order if s in modules]
        if loaded:
            pages.append((page.name, order, loaded))
    return modules, pages


# ── the two checks ───────────────────────────────────────────────────────────
def order_problems(frontend: pathlib.Path):
    """(page, module, dependency, why) for every declared dependency a page does not run first."""
    modules, pages = pages_with_modules(frontend)
    problems = []
    for name, order, loaded in pages:
        for rel in loaded:
            before = order[:order.index(rel)]
            for dep in modules[rel]:
                if dep not in before:
                    problems.append((name, rel, dep, "is not loaded at all" if dep not in order else "runs after it"))
    return problems


def boot_problems(frontend: pathlib.Path):
    """(page, script, what it threw) from running each page's modules, and what they need, in the page's
    own order, the way a browser runs them. A dependency the page does not load is not in the run."""
    modules, pages = pages_with_modules(frontend)
    problems = []
    for name, order, loaded in pages:
        needed = needed_with_dependencies(loaded, modules)
        sequence = [s for s in order if s in needed]
        proc = run_node(BOOT, frontend, *sequence)
        assert proc.returncode == 0, proc.stderr
        for script in last_json_line(proc.stdout)["scripts"]:
            if script["threw"] is not None:
                problems.append((name, script["file"], script["threw"]))
    return problems


# ── the real frontend ────────────────────────────────────────────────────────
def test_every_page_runs_the_dependencies_of_every_core_module_it_loads_first():
    modules, pages = pages_with_modules(FRONTEND)
    assert modules.get("js/bid-model.js") == ["js/excel-math.js"], (
        "the discovery did not find the model's declared dependency: %r" % modules)
    assert {name for name, *_ in pages} >= {"library.html", "polish-estimate.html", "polish-intake.html"}, (
        "the discovery did not find the pages that load the model: %r" % [name for name, *_ in pages])
    assert order_problems(FRONTEND) == []


def test_the_modules_and_what_they_declare_boot_in_each_pages_own_order():
    require_node()
    assert boot_problems(FRONTEND) == []


# ── the checks can fail ──────────────────────────────────────────────────────
def _umd(own, global_name, needs=None):
    """A module in the repository's own header convention, optionally declaring one dependency."""
    if needs:
        dep_file, dep_global = needs
        head = ('  var isNode = typeof module !== "undefined" && module.exports;\n'
                '  var deps = { dep: isNode ? require("./%s") : root.%s };\n'
                '  if (!deps.dep) throw new Error("%s needs %s loaded before it");\n'
                '  var api = factory(deps);\n'
                '  root.%s = api;\n'
                '  if (isNode) module.exports = api;\n') % (dep_file, dep_global, own, dep_file, global_name)
    else:
        head = ('  var api = factory();\n'
                '  root.%s = api;\n'
                '  if (typeof module !== "undefined" && module.exports) module.exports = api;\n') % global_name
    return ('(function (root, factory) {\n' + head +
            '})(typeof self !== "undefined" ? self : this, function (deps) {\n'
            '  "use strict";\n  return { name: "%s" };\n});\n') % own


def _page(tags: str) -> str:
    return "<!DOCTYPE html><html><body>%s</body></html>" % tags


def _tag(name, defer=False):
    return '<script %ssrc="/js/%s.js?v=3"></script>' % ("defer " if defer else "", name)


def _wrong_pages(root: pathlib.Path):
    """leaf <- mid <- top, and a page for every way to get the order wrong."""
    files = {
        "js/leaf.js": _umd("leaf.js", "TWLeaf"),
        "js/mid.js": _umd("mid.js", "TWMid", ("leaf.js", "TWLeaf")),
        "js/top.js": _umd("top.js", "TWTop", ("mid.js", "TWMid")),
        "js/plain.js": "var page = 1;\n",
        "js/commenter.js": _umd("commenter.js", "TWCommenter") + '// not a dependency: require("./leaf.js")\n',
        "good.html": _page(_tag("leaf") + _tag("mid") + _tag("top") + _tag("plain")),
        "missing-leaf.html": _page(_tag("mid") + _tag("plain")),
        "late-leaf.html": _page(_tag("mid") + _tag("leaf")),
        "deferred-leaf.html": _page(_tag("leaf", defer=True) + _tag("mid")),
        "commented-out.html": _page("<!-- " + _tag("leaf") + " -->" + _tag("mid")),
        "transitive.html": _page(_tag("leaf") + _tag("top")),
        "top-before-mid.html": _page(_tag("leaf") + _tag("top") + _tag("mid")),
        "unrelated.html": _page(_tag("plain") + _tag("commenter")),
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


WHAT_IS_WRONG = [
    ("commented-out.html", "js/mid.js", "js/leaf.js", "is not loaded at all"),
    ("deferred-leaf.html", "js/mid.js", "js/leaf.js", "runs after it"),
    ("late-leaf.html", "js/mid.js", "js/leaf.js", "runs after it"),
    ("missing-leaf.html", "js/mid.js", "js/leaf.js", "is not loaded at all"),
    ("top-before-mid.html", "js/top.js", "js/mid.js", "runs after it"),
    ("transitive.html", "js/top.js", "js/mid.js", "is not loaded at all"),
]


def test_the_discovery_reads_headers_and_only_headers(tmp_path):
    _wrong_pages(tmp_path)
    modules, pages = pages_with_modules(tmp_path)
    assert modules == {"js/mid.js": ["js/leaf.js"], "js/top.js": ["js/mid.js"]}, (
        "a leaf, a plain script and a comment that names a file are not modules with a dependency")
    assert sorted(name for name, *_ in pages) == sorted(
        ["good.html", "missing-leaf.html", "late-leaf.html", "deferred-leaf.html", "commented-out.html",
         "transitive.html", "top-before-mid.html"])


def test_the_static_check_names_every_wrong_page_and_passes_the_right_one(tmp_path):
    _wrong_pages(tmp_path)
    assert sorted(order_problems(tmp_path)) == WHAT_IS_WRONG


def test_the_executed_check_makes_each_wrong_page_throw_by_name_and_boots_the_right_one(tmp_path):
    require_node()
    _wrong_pages(tmp_path)
    got = boot_problems(tmp_path)
    assert sorted((page, script) for page, script, _ in got) == sorted(
        (page, module) for page, module, _, _ in WHAT_IS_WRONG)
    for page, script, message in got:
        assert "loaded before it" in message, (page, script, message)
    assert not [g for g in got if g[0] == "good.html"]
