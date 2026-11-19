"""The BD CRM's files keep to their side of the line (#806, spec #802 Q6 and the Seam 3 checks).

  * no BD asset shares a path or a name with a tool asset (the tool has its own /shared.js,
    /js/icons.js, /js/admin.js, /js/analytics.js...); BD's scripts are in bd/js/ and its one
    stylesheet is bd/bd.css;
  * nothing under frontend/bd/ refers to a root tool page or a tool script, apart from the tool's
    shell scripts (/js/icons.js, /auth.js, /shared.js, and /js/crm-core.js, which names every person),
    its sign-in page and its favicon; BD's API
    calls go to /api/bd/ only; and no BD file links to a /bd/ page that has not moved yet;
  * no tool page loads the BD stylesheet, or any BD script;
  * every rule in bd.css is scoped under the BD root, .bd-app;
  * bd.css's colours are the tool's: a colour is written only in its tokens block, as one of
    DESIGN.md's colours (or one of the approved BD mock-up's two status grounds), and an rgba() is one
    of those colours (or a shadow base DESIGN.md names) with an alpha; the font stack is DESIGN.md's;
  * muted-ink is never a text colour (it fails WCAG AA for text), and the only black is a shadow
    DESIGN.md names, on something that floats clear of the page.

BD's glyphs are the tool's: they are in js/icons.js, the app's one icon set (DESIGN.md, Icons).
"""
from __future__ import annotations

import pathlib
import re

import pytest

from _bd_jstokens import tokenize
from _frontend_tree import rel

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
BD = FRONTEND / "bd"
CSS = BD / "bd.css"

# What a BD file may point at outside /bd/: the tool's shell scripts (crm-core.js among them: it names
# every person), its sign-in page and its favicon.
TOOL_SHELL_ALLOWED = {"/js/icons.js", "/auth.js", "/shared.js", "/js/crm-core.js", "/login.html",
                      "/img/treadwell-bison.svg"}
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
    ("/api/bd/me", True), ("/portal.html", False), ("/js/crm-core.js", True), ("/js/portal.js", False),
    ("/styles.css", False),
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
    """(at-rule context, selector list) for every style rule, @media/@supports/@container opened, @keyframes kept
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
            if head.startswith(("@media", "@supports", "@container")):
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
    # a container query is a condition like @media: the rules inside it are checked (#807, This Week)
    ("@container wk-main (min-width: 520px) { .bd-app .wk-row { a: b; } .wk-row { a: b; } }", [".wk-row"]),
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
# DESIGN.md's Menu and Overlay shadows, the only black: rgba(0,0,0,.18) and rgba(0,0,0,.30).
BLACK = (0, 0, 0)
OVERLAY_SHADOWS = {"0 6px 20px rgba(0, 0, 0, .18)", "0 16px 48px rgba(0, 0, 0, .30)",
                   "0 -16px 48px rgba(0, 0, 0, .30)", "-16px 0 48px rgba(0, 0, 0, .30)"}


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
    rgbs = {_rgb(h) for h in allowed} | {SHADOW_RGB, BLACK}
    for m in re.finditer(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", css):
        assert tuple(int(x) for x in m.groups()) in rgbs, "rgba(%s, %s, %s) is not a tool colour" % m.groups()
    blacks = re.findall(r"--bd-shadow-[\w-]+:\s*([^;]*rgba\(0, 0, 0[^;]*);", css)
    assert blacks and set(blacks) <= OVERLAY_SHADOWS, blacks
    assert css.count("rgba(0, 0, 0") == len(blacks), "a black written outside DESIGN.md's Menu and Overlay"
    for m in re.finditer(r"%23([0-9a-fA-F]{6})", css):
        assert "#" + m.group(1).lower() in allowed, "a data: image coloured %s" % m.group(1)


def test_muted_ink_is_never_text():
    """Muted-ink (#8a857c) is about 3.6:1 on the paper and the card: below WCAG AA's 4.5:1 for text.
    BD uses it for borders and the spinner only; captions, hints and placeholders are umber-ink."""
    css = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)
    muted = {m.group(1) for m in re.finditer(r"(--bd-[\w-]+):\s*#8a857c", css)}
    assert muted, "vacuity: no token holds muted-ink"
    text = [m.group(0) for t in muted for m in re.finditer(r"(?<![-\w])color:\s*var\(%s\)" % t, css)]
    assert text == [], text


def test_cards_lists_and_tables_are_flat_at_rest():
    """DESIGN.md's Flat-By-Default rule: a hairline, and no resting shadow."""
    css = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)
    for sel in (".bd-app .card {", ".bd-app .list {", ".bd-app .table-wrap {", ".bd-app .fatal-box {"):
        rule = css[css.index(sel):]
        rule = rule[:rule.index("}")]
        assert "box-shadow" not in rule and "border: 1px solid var(--bd-line)" in rule, (sel, rule)


def test_the_font_is_the_tools():
    css = CSS.read_text(encoding="utf-8")
    stacks = set(re.findall(r"--bd-font:\s*([^;]+);", css))
    assert stacks == {"'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"}, stacks
    design = (ROOT / "DESIGN.md").read_text(encoding="utf-8")
    assert "fontFamily: \"'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif\"" in design
    families = re.findall(r"font-family\s*:\s*([^;}]+)", re.sub(r"/\*.*?\*/", "", css, flags=re.S))
    assert all(f.strip() in ("var(--bd-font)", "inherit") for f in families), families
