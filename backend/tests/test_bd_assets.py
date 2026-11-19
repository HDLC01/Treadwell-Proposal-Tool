"""The BD CRM's files keep to their side of the line (#806, spec #802 Q6 and the Seam 3 checks).

  * no BD asset shares a path or a name with a tool asset (the tool has its own /shared.js,
    /js/icons.js, /js/admin.js, /js/analytics.js...); BD's scripts are in bd/js/ and its one
    stylesheet is bd/bd.css;
  * nothing under frontend/bd/ refers to a root tool page or a tool script, apart from the tool's
    shell scripts (/js/icons.js, /auth.js, /shared.js), its sign-in page and its favicon; BD's API
    calls go to /api/bd/ only; and no BD file links to a /bd/ page that has not moved yet;
  * no tool page loads the BD stylesheet, or any BD script;
  * every rule in bd.css is scoped under the BD root, .bd-app;
  * bd.css's colours are the tool's: a colour is written only in its tokens block, as one of
    DESIGN.md's colours (or one of the approved BD mock-up's two status grounds), and an rgba() is one
    of those colours (or the tool's warm shadow) with an alpha; the font stack is DESIGN.md's;
  * BD's glyphs never touch the tool's icon global: bd-icons.js run after the tool's js/icons.js
    leaves window.TWIcon exactly as it was, and no BD script mentions TWIcon apart from bd-icons.js,
    which only reads it.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from _bd_jstokens import tokenize
from _frontend_tree import rel
from _node import last_json_line, require_node, run_node

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
BD = FRONTEND / "bd"
CSS = BD / "bd.css"

# What a BD file may point at outside /bd/: the tool's shell scripts, its sign-in page and its favicon.
TOOL_SHELL_ALLOWED = {"/js/icons.js", "/auth.js", "/shared.js", "/login.html", "/img/treadwell-bison.svg"}
SUPABASE = re.compile(r"^https://cdn\.jsdelivr\.net/npm/@supabase/supabase-js@\d+\.\d+\.\d+$")
PRECONNECT = "https://cdn.jsdelivr.net"


def bd_files():
    return sorted(p for p in BD.rglob("*") if p.is_file())


def tool_files():
    return sorted(p for p in FRONTEND.rglob("*") if p.is_file() and BD not in p.parents)


def assets(files):
    return [p for p in files if p.suffix.lower() != ".html"]


# ── names and places ─────────────────────────────────────────────────────────────────────────
def test_no_bd_asset_shares_a_path_or_a_name_with_a_tool_asset():
    tool_names = {p.name.lower() for p in assets(tool_files())}
    tool_paths = {"/" + rel(p) for p in assets(tool_files())}
    clash = sorted(rel(p) for p in assets(bd_files()) if p.name.lower() in tool_names or "/" + rel(p) in tool_paths)
    assert clash == [], "BD assets named like a tool asset: %r" % clash


def test_the_check_would_see_a_clash():
    """The shared.js the BD CRM brought with it is the case the rule exists for."""
    assert "shared.js" in {p.name for p in assets(tool_files())}
    assert "icons.js" in {p.name for p in assets(tool_files())}


def test_bd_scripts_are_in_bd_js_and_its_styles_in_one_file():
    for p in assets(bd_files()):
        r = rel(p)
        if p.suffix == ".js":
            assert r.startswith("bd/js/"), "%s: BD scripts live in bd/js/" % r
        elif p.suffix == ".css":
            assert r == "bd/bd.css", "%s: BD has one stylesheet, bd/bd.css" % r
        else:
            raise AssertionError("%s: an asset of a kind the BD CRM does not ship" % r)


# ── what a BD file points at ─────────────────────────────────────────────────────────────────
ATTR = re.compile(r'\b(src|href|action|formaction|poster|data)\s*=\s*"([^"]*)"', re.I)


def _html_refs(text):
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return [m.group(2) for m in ATTR.finditer(text)]


def _js_refs(text):
    """Every string or template literal in a script that reads as a site path."""
    out = []
    for t in tokenize(text):
        if t.kind in ("str", "template") and re.match(r"^/(?![/*])[\w.~-]", t.value or ""):
            out.append(t.value)
    return out


def _css_refs(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return [m.group(2) for m in re.finditer(r"url\(\s*(['\"]?)(.*?)\1\s*\)", text)]


def refs_of(path):
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".html":
        return _html_refs(text)
    if path.suffix == ".js":
        return _js_refs(text)
    if path.suffix == ".css":
        return _css_refs(text)
    return []


def bad_ref(value):
    """Why `value` may not appear in a BD file, or None."""
    v = value.split("?", 1)[0].split("#", 1)[0]
    if v.startswith("data:"):
        return None
    if v.startswith(("http:", "https:", "//")):
        return None if (SUPABASE.match(v) or v == PRECONNECT) else "an outside address"
    if not v.startswith("/"):
        return "a relative address (write it from the site root)"
    if v.startswith("/api/"):
        return None if v.startswith("/api/bd/") else "a tool API route"
    if v == "/bd/" or v.startswith("/bd/"):
        return None
    return None if v in TOOL_SHELL_ALLOWED else "a root tool page or tool file"


@pytest.mark.parametrize("path", [p for p in bd_files() if p.suffix in (".html", ".js", ".css")], ids=rel)
def test_nothing_under_bd_refers_to_a_tool_page_or_script(path):
    bad = ["%s (%s)" % (v, bad_ref(v)) for v in refs_of(path) if bad_ref(v)]
    assert not bad, "%s refers outside the BD CRM:\n%s" % (rel(path), "\n".join(bad))


@pytest.mark.parametrize("value,ok", [
    ("/bd/js/bd-api.js", True), ("/bd/", True), ("/js/icons.js", True), ("/login.html", True),
    ("/api/bd/me", True), ("/portal.html", False), ("/js/crm-core.js", False), ("/styles.css", False),
    ("/api/me", False), ("/index.html", False), ("js/x.js", False), ("https://example.com/x.js", False),
    ("/admin.html", False), ("data:image/svg+xml,%3Csvg%3E", True),
])
def test_the_rule_itself(value, ok):
    assert (bad_ref(value) is None) is ok, (value, bad_ref(value))


def test_the_js_scan_sees_a_path_and_skips_comments():
    src = 'var a = "/portal.html"; // "/admin.html"\n/* "/x.js" */ var b = `/api/bd/me`; var c = "a/b";'
    assert _js_refs(src) == ["/portal.html", "/api/bd/me"]


def missing_bd_targets(frontend=FRONTEND):
    """'<file>: <address>' for every /bd/ address a BD file points at that is not there: a page that
    has not moved yet. /bd/x/ means its index.html."""
    out = []
    for path in sorted(p for p in (frontend / "bd").rglob("*") if p.suffix in (".html", ".js", ".css")):
        for v in refs_of(path):
            v = v.split("?", 1)[0].split("#", 1)[0]
            if not v.startswith("/bd/"):
                continue
            target = frontend / v.lstrip("/")
            if v.endswith("/"):
                target = target / "index.html"
            if not target.is_file():
                out.append("%s: %s" % (rel(path, frontend), v))
    return out


def test_no_bd_file_links_to_a_bd_page_that_has_not_moved_yet():
    """Spec #802, page links: a link to a BD page that is not here yet is hidden until it moves."""
    assert missing_bd_targets() == []


def test_the_link_check_sees_a_page_that_is_not_there(tmp_path):
    (tmp_path / "bd" / "js").mkdir(parents=True)
    (tmp_path / "bd" / "index.html").write_text('<a href="/bd/contacts.html">Contacts</a>', encoding="utf-8")
    (tmp_path / "bd" / "js" / "x.js").write_text('go("/bd/");', encoding="utf-8")
    assert missing_bd_targets(tmp_path) == ["bd/index.html: /bd/contacts.html"]


def test_no_tool_page_loads_the_bd_stylesheet_or_a_bd_script():
    bad = []
    for page in (p for p in tool_files() if p.suffix == ".html"):
        for v in _html_refs(page.read_text(encoding="utf-8")):
            if v.startswith("/bd/") and (v.endswith((".css", ".js")) or "/bd/js/" in v):
                bad.append("%s loads %s" % (rel(page), v))
    assert not bad, bad


# ── bd.css: scoped, and the tool's colours ───────────────────────────────────────────────────
def css_rules(css):
    """(at-rule context, selector list) for every style rule, @media/@supports opened, @keyframes kept
    whole (their from/to/% steps are not selectors)."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = []

    def walk(text, ctx):
        i = 0
        while True:
            j = text.find("{", i)
            if j == -1:
                return
            head = text[i:j].strip()
            depth, k = 1, j + 1
            while depth:
                depth += {"{": 1, "}": -1}.get(text[k], 0)
                k += 1
            inner = text[j + 1:k - 1]
            if head.startswith(("@media", "@supports")):
                walk(inner, ctx + [head])
            elif head.startswith("@"):
                out.append((ctx + [head], None))
            else:
                out.append((ctx, head))
            i = k

    walk(css, [])
    return out


def split_selectors(sel):
    parts, depth, cur = [], 0, ""
    for ch in sel:
        depth += {"(": 1, "[": 1, ")": -1, "]": -1}.get(ch, 0)
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    parts.append(cur.strip())
    return parts


ROOTED = re.compile(r"^\.bd-app(?![\w-])")


def unscoped(css):
    bad = []
    for ctx, sel in css_rules(css):
        if sel is None:
            if not any(c.startswith("@keyframes bd-") for c in ctx[-1:]):
                bad.append(" ".join(ctx))
            continue
        bad.extend(s for s in split_selectors(sel) if not ROOTED.match(s))
    return bad


def test_every_bd_rule_is_scoped_under_the_bd_root():
    assert unscoped(CSS.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("css,bad", [
    (".card { color: red; }", [".card"]),
    (".bd-app .card, .btn { x: y; }", [".btn"]),
    ("@media (max-width: 1px) { h1 { margin: 0; } }", ["h1"]),
    ("body { padding: 0; }", ["body"]),
    (".bd-apps .x { a: b; }", [".bd-apps .x"]),
    ("@font-face { font-family: X; }", ["@font-face"]),
    ("@keyframes spin { to { transform: none; } }", ["@keyframes spin"]),
    (".bd-app .x:where(a, b) { a: b; } @keyframes bd-spin { from { a: b; } }", []),
])
def test_the_scope_check_itself(css, bad):
    assert unscoped(css) == bad


def design_palette():
    """DESIGN.md's colours, from its front matter, lower case."""
    text = (ROOT / "DESIGN.md").read_text(encoding="utf-8")
    front = text.split("---", 2)[1]
    block = front.split("colors:", 1)[1].split("\ntypography:", 1)[0]
    return {m.group(1).lower() for m in re.finditer(r'"(#[0-9a-fA-F]{6})"', block)}


# The approved BD mock-up's two status grounds (https://claude.ai/artifact/CjyYgA7J2EPKZs32H7LH4Q,
# --ok-bg and --info-bg). Every other colour in bd.css is one of DESIGN.md's.
MOCKUP_EXTRAS = {"#e8f4ec", "#edf2f7"}
# The tool's warm shadow base (DESIGN.md: shadows mixed from rgba(60,50,40)).
SHADOW_RGB = (60, 50, 40)


def _rgb(hex6):
    return tuple(int(hex6[i:i + 2], 16) for i in (1, 3, 5))


def test_bd_colours_are_the_tools():
    css = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8").replace("\r\n", "\n"), flags=re.S)
    start, end = css.index(".bd-app {"), css.index("@media", css.index(".bd-app {"))
    tokens, rest = css[start:end], css[:start] + css[end:]
    allowed = design_palette() | MOCKUP_EXTRAS
    assert len(design_palette()) > 20, "DESIGN.md's palette was not read"
    hexes = re.findall(r"#[0-9a-fA-F]{3,8}\b", tokens)
    assert hexes, "the tokens block holds the colours"
    assert sorted({h.lower() for h in hexes} - allowed) == [], "colours that are not the tool's"
    stray = [h for h in re.findall(r"(?<![%\w])#[0-9a-fA-F]{3,8}\b", rest)]
    assert stray == [], "a colour written outside the tokens block: %r" % stray
    rgbs = {_rgb(h) for h in allowed} | {SHADOW_RGB}
    for m in re.finditer(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", css):
        assert tuple(int(x) for x in m.groups()) in rgbs, "rgba(%s, %s, %s) is not a tool colour" % m.groups()
    for m in re.finditer(r"%23([0-9a-fA-F]{6})", css):
        assert "#" + m.group(1).lower() in allowed, "a data: image coloured %s" % m.group(1)


def test_the_font_is_the_tools():
    css = CSS.read_text(encoding="utf-8")
    stacks = set(re.findall(r"--bd-font:\s*([^;]+);", css))
    assert stacks == {"'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"}, stacks
    design = (ROOT / "DESIGN.md").read_text(encoding="utf-8")
    assert "fontFamily: \"'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif\"" in design
    families = re.findall(r"font-family\s*:\s*([^;}]+)", re.sub(r"/\*.*?\*/", "", css, flags=re.S))
    assert all(f.strip() in ("var(--bd-font)", "inherit") for f in families), families


# ── BD glyphs never touch the tool's icon global ─────────────────────────────────────────────
RUNNER = r"""
const fs = require("fs"), vm = require("vm");
const [toolIcons, bdIcons, withTool] = process.argv.slice(2);
const ctx = {}; ctx.window = ctx; vm.createContext(ctx);
let before = null, names = [], drawn = {};
if (withTool === "1") {
  vm.runInContext(fs.readFileSync(toolIcons, "utf8"), ctx);
  before = ctx.TWIcon; names = ctx.TWIcon.names();
  names.forEach((n) => { drawn[n] = ctx.TWIcon(n, 18); });
}
vm.runInContext(fs.readFileSync(bdIcons, "utf8"), ctx);
const out = { hasTool: typeof ctx.TWIcon, hasBd: typeof ctx.BDIcon };
if (withTool === "1") {
  out.same = ctx.TWIcon === before;
  out.namesSame = JSON.stringify(ctx.TWIcon.names()) === JSON.stringify(names);
  out.drawsSame = names.every((n) => ctx.TWIcon(n, 18) === drawn[n]);
  out.bdDrawsToolNames = names.every((n) => ctx.BDIcon(n, 18) === drawn[n]);
  out.ownKeys = Object.keys(ctx.TWIcon).sort();
}
out.bdNames = ctx.BDIcon.names();
out.toolNames = names;
out.phone = ctx.BDIcon("phone", 14);
out.filter = ctx.BDIcon("filter", 16);
out.funnel = withTool === "1" ? ctx.TWIcon("funnel", 16) : "";
out.unknown = ctx.BDIcon("no-such-glyph", 16);
console.log(JSON.stringify(out));
"""


def run_icons(tmp_path, with_tool):
    require_node()
    js = tmp_path / "icons-run.js"
    js.write_text(RUNNER, encoding="utf-8")
    proc = run_node(js, FRONTEND / "js" / "icons.js", BD / "js" / "bd-icons.js", "1" if with_tool else "0")
    assert proc.returncode == 0, proc.stderr[-3000:]
    return last_json_line(proc.stdout)


def test_bd_glyphs_leave_the_tools_icon_global_alone(tmp_path):
    out = run_icons(tmp_path, True)
    assert out["hasBd"] == "function"
    assert out["same"] and out["namesSame"] and out["drawsSame"], "bd-icons.js changed window.TWIcon"
    assert out["ownKeys"] == ["has", "names"], "something was hung on TWIcon: %r" % out["ownKeys"]
    assert out["bdDrawsToolNames"], "a name the tool has must be drawn by the tool's own table"
    assert out["filter"] == out["funnel"], "the alias draws the tool's glyph"
    bd_only = sorted(set(out["bdNames"]) - set(out["toolNames"]))
    assert {"phone", "building", "calendar-check", "voicemail", "chevron-right", "filter"} <= set(bd_only)
    assert 'class="tw-ico"' in out["phone"] and "<path" in out["phone"] and 'width="14"' in out["phone"]
    assert "<path" not in out["unknown"] and "<circle" not in out["unknown"], "an unknown name is an empty box"


def test_bd_glyphs_without_the_tools_table_create_no_tool_global(tmp_path):
    out = run_icons(tmp_path, False)
    assert out["hasTool"] == "undefined" and out["hasBd"] == "function"
    assert "<path" in out["phone"]


def test_no_bd_script_writes_or_reads_the_tools_icon_global():
    for js in sorted(BD.rglob("*.js")):
        code = re.sub(r"/\*.*?\*/|//[^\n]*", "", js.read_text(encoding="utf-8"), flags=re.S)
        if rel(js) == "bd/js/bd-icons.js":
            assert not re.search(r"\bTWIcon\b\s*(\.[\w$]+|\[[^\]]*\])?\s*=(?!=)", code), \
                "bd-icons.js assigns to the tool's TWIcon"
            assert "window.BDIcon = BDIcon" in code
            continue
        assert "TWIcon" not in code, "%s uses the tool's icon global; BD glyphs are BDIcon" % rel(js)


def test_a_bd_glyph_name_never_shadows_a_tool_glyph(tmp_path):
    """A BD-only table entry with a tool glyph's name would draw that name two ways on one page."""
    require_node()
    js = tmp_path / "keys.js"
    js.write_text(r"""
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const body = src.slice(src.indexOf("var BD_PATHS = {"), src.indexOf("var ALIASES"));
const keys = [...body.matchAll(/^\s{4}("?)([\w-]+)\1\s*:/gm)].map((m) => m[2]);
console.log(JSON.stringify(keys));
""", encoding="utf-8")
    proc = run_node(js, BD / "js" / "bd-icons.js")
    assert proc.returncode == 0, proc.stderr
    keys = json.loads(proc.stdout.strip().splitlines()[-1])
    tool = run_icons(tmp_path, True)["toolNames"]
    assert keys and not (set(keys) & set(tool)), sorted(set(keys) & set(tool))
