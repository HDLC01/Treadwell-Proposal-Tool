"""The BD pages' shell (#806: BD's test_pages_shell, rewritten for the proposal tool's shell).

BD's pages live under frontend/bd/ and boot inside the tool. The rules every BD page is held to:

  * `lang`, a charset, the phone viewport, and a title "<Page> · BD CRM · Treadwell", each one its own;
  * the one BD stylesheet, /bd/bd.css, and no other local stylesheet (BD's sign-in redirect page, which
    shows nothing, loads none);
  * the scripts in the tool's shell order (Supabase SDK, /js/icons.js, /auth.js, /shared.js,
    /js/crm-core.js), then BD's shell (bd-api, bd-shared, bd-core), then the page's own; every file exists. BD's own
    auth.js, top bar, rail, mock data and sign-in shell are gone. /bd/login.html runs only its redirect;
  * the only external script is the Supabase SDK, the very tag the tool's pages use (pinned, with
    Subresource Integrity), and the CDN connection is warmed first;
  * no inline <script>, no on*= attribute, no javascript: URL, in a page or in the markup BD's scripts
    build (the CSP);
  * one <main id="main"> on every app page, on a <body class="bd-app"> (the BD root);
  * no emoji anywhere under frontend/bd/ (BD's glyphs come from the tool's js/icons.js);
  * bd.css: its section markers once each and in order, a page section styles only its own prefix,
    the BD root has the tool's paper ground, and there is no @font-face and no font file.
"""
from __future__ import annotations

import html.parser
import pathlib
import re
import urllib.parse

import pytest

from _bd_jstokens import string_literals
from _frontend_tree import rel

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
BD = FRONTEND / "bd"
CSS = BD / "bd.css"

PAGES = sorted(BD.rglob("*.html"))
LOGIN = "bd/login.html"
APP_PAGES = [p for p in PAGES if rel(p) != LOGIN]

SUPABASE_SRC = re.compile(r"^https://cdn\.jsdelivr\.net/npm/@supabase/supabase-js@\d+\.\d+\.\d+(/[\w./-]+)?$")
SUPABASE = "supabase-js"
# crm-core.js names every person (window.TWCrm): BD's people helpers are its, so it is part of the shell.
TOOL_SHELL = [SUPABASE, "/js/icons.js", "/auth.js", "/shared.js", "/js/crm-core.js"]
BD_SHELL = ["/bd/js/bd-api.js", "/bd/js/bd-shared.js", "/bd/js/bd-core.js"]
# Each BD page's own scripts after the BD shell, listed explicitly: a page missing here fails
# test_script_order (no silent default). A ticket that moves a page adds its row.
PAGE_SCRIPT = {
    # This Week (#807): the after-a-call sheet, then the page.
    "bd/index.html": ["/bd/js/bd-call.js", "/bd/js/bd-week.js"],
    # The Contacts page's place (#807): plain words and a link to Add contact until Contacts moves, no
    # script of its own.
    "bd/contacts.html": [],
    # One contact (#808): This Week's call sheet (the one copy), then the page.
    "bd/contact.html": ["/bd/js/bd-call.js", "/bd/js/bd-contact.js"],
    # Add a contact (#808).
    "bd/add.html": ["/bd/js/bd-add.js"],
}
LOGIN_ORDER = ["/bd/js/login-return.js"]
TITLE = re.compile(r"^\S.* · BD CRM · Treadwell$")

ON_ATTR_IN_MARKUP = re.compile(r"(?:^|[\s\"'/])on[a-z]{3,}\s*=", re.I)
JS_URL = re.compile(r"javascript\s*:", re.I)

# Emoji and pictographs. Plain punctuation the UI uses (· — … “ ”) is outside these ranges on purpose.
EMOJI_RANGES = [
    (0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF), (0x2300, 0x23FF),
    (0xFE0F, 0xFE0F), (0x20E3, 0x20E3), (0xE0020, 0xE007F),
]


def is_emoji(ch: str) -> bool:
    o = ord(ch)
    return any(a <= o <= b for a, b in EMOJI_RANGES)


class Shell(html.parser.HTMLParser):
    """What the tests look at. Comments never reach handle_starttag."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lang = None
        self.charset = False
        self.viewport = None
        self.title = None
        self._in_title = False
        self.stylesheets = []
        self.preconnects = []
        self.scripts = []
        self._script = None
        self.on_attrs = []
        self.js_urls = []
        self.main_ids = []
        self.body_class = None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v if v is not None else "") for k, v in attrs}
        line = self.getpos()[0]
        for k, v in a.items():
            if k.startswith("on"):
                self.on_attrs.append((line, tag, k))
            if JS_URL.match(v.strip()):
                self.js_urls.append((line, tag, k, v))
        if tag == "html":
            self.lang = a.get("lang")
        elif tag == "meta":
            if "charset" in a:
                self.charset = True
            if a.get("name", "").lower() == "viewport":
                self.viewport = a.get("content", "")
        elif tag == "title":
            self._in_title = True
            self.title = ""
        elif tag == "link":
            rels = a.get("rel", "").lower().split()
            if "stylesheet" in rels:
                self.stylesheets.append(a.get("href", ""))
            if "preconnect" in rels:
                self.preconnects.append(a.get("href", ""))
        elif tag == "script":
            self._script = dict(a, _body="", _line=line)
        elif tag == "main":
            self.main_ids.append(a.get("id"))
        elif tag == "body":
            self.body_class = a.get("class", "")

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "script" and self._script is not None:
            self.scripts.append(self._script)
            self._script = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._script is not None:
            self._script["_body"] += data


def shell(path: pathlib.Path) -> Shell:
    s = Shell()
    s.feed(path.read_text(encoding="utf-8"))
    s.close()
    return s


def script_names(s: Shell):
    return [SUPABASE if SUPABASE_SRC.match(sc.get("src", "")) else sc.get("src", "") for sc in s.scripts]


def test_pages_found():
    names = {rel(p) for p in PAGES}
    assert {"bd/index.html", "bd/contacts.html", "bd/login.html"} <= names, names


# ── head ─────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("page", PAGES, ids=rel)
def test_head(page):
    s = shell(page)
    assert s.lang, "<html> needs a lang attribute"
    assert s.charset, "<meta charset> is missing"
    assert s.viewport and "width=device-width" in s.viewport, "the phone viewport meta is missing"
    assert s.title and TITLE.match(s.title.strip()), \
        "the title must read '<Page> · BD CRM · Treadwell', got %r" % s.title


def test_titles_are_distinct():
    titles = [shell(p).title.strip() for p in PAGES]
    assert len(set(titles)) == len(titles), titles


@pytest.mark.parametrize("page", APP_PAGES, ids=rel)
def test_one_stylesheet(page):
    s = shell(page)
    local = [h for h in s.stylesheets if not h.startswith(("http://", "https://", "//"))]
    assert local == ["/bd/bd.css"], "link /bd/bd.css once and no other local stylesheet: %r" % s.stylesheets


def test_the_sign_in_redirect_loads_no_stylesheet():
    assert shell(BD / "login.html").stylesheets == []


def test_one_bd_css_file():
    css = sorted(rel(p) for p in BD.rglob("*.css"))
    assert css == ["bd/bd.css"], "the BD CRM has one stylesheet: %r" % css


# ── scripts ──────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("page", PAGES, ids=rel)
def test_script_order(page):
    names = script_names(shell(page))
    if rel(page) == LOGIN:
        assert names == LOGIN_ORDER, "bd/login.html scripts: %r" % names
        return
    assert rel(page) in PAGE_SCRIPT, "%s is not in PAGE_SCRIPT: list its page scripts there" % rel(page)
    want = TOOL_SHELL + BD_SHELL + PAGE_SCRIPT[rel(page)]
    assert names == want, "%s scripts are out of the shell order:\n got  %r\n want %r" % (rel(page), names, want)
    for src in names[1:]:
        assert (FRONTEND / src.lstrip("/")).is_file(), "%s loads %s, which does not exist" % (rel(page), src)


@pytest.mark.parametrize("page", APP_PAGES, ids=rel)
def test_the_supabase_tag_is_the_tools(page):
    """The same pinned build, with the same integrity hash, as the tool's own pages."""
    tool = [sc for sc in shell(FRONTEND / "trash.html").scripts if SUPABASE_SRC.match(sc.get("src", ""))][0]
    ours = [sc for sc in shell(page).scripts if sc.get("src", "").startswith(("http:", "https:", "//"))]
    assert len(ours) == 1, "the only external script is the Supabase SDK: %r" % ours
    sc = ours[0]
    assert (sc["src"], sc.get("integrity"), sc.get("crossorigin")) == \
        (tool["src"], tool.get("integrity"), "anonymous")
    hosts = [urllib.parse.urlsplit(href) for href in shell(page).preconnects]
    warm = any(u.scheme == "https" and u.hostname == "cdn.jsdelivr.net" for u in hosts)
    assert warm, "warm the CDN connection first"


@pytest.mark.parametrize("page", PAGES, ids=rel)
def test_no_inline_scripts(page):
    for sc in shell(page).scripts:
        assert sc.get("src"), "%s line %d: an inline <script> (the CSP will forbid it)" % (rel(page), sc["_line"])
        assert not sc["_body"].strip(), "%s line %d: a <script src> with a body" % (rel(page), sc["_line"])


@pytest.mark.parametrize("page", PAGES, ids=rel)
def test_no_inline_handlers_or_js_urls(page):
    s = shell(page)
    assert not s.on_attrs, "%s: inline event handlers %r (wire events in the page script)" % (rel(page), s.on_attrs)
    assert not s.js_urls, "%s: javascript: URLs %r" % (rel(page), s.js_urls)


@pytest.mark.parametrize("page", APP_PAGES, ids=rel)
def test_main_landmark_on_the_bd_root(page):
    s = shell(page)
    assert s.main_ids == ["main"], "keep one <main id=\"main\">"
    assert "bd-app" in (s.body_class or "").split(), "the BD root class goes on <body>: every BD rule hangs on it"


JS_FILES = sorted(BD.rglob("*.js"))


@pytest.mark.parametrize("js", JS_FILES, ids=rel)
def test_no_inline_handlers_in_built_markup(js):
    bad = []
    for t in string_literals(js.read_text(encoding="utf-8")):
        if "<" in t.value or "=" in t.value:
            if ON_ATTR_IN_MARKUP.search(t.value) or JS_URL.search(t.value):
                bad.append("line %d: %r" % (t.line, t.value[:80]))
    assert not bad, "%s builds markup with an on*= handler or a javascript: URL:\n%s" % (rel(js), "\n".join(bad))


def test_bds_own_shell_is_gone():
    """BD's top bar, rail, phone tab bar, sign-in shell and mock mode do not come over."""
    names = {rel(p) for p in BD.rglob("*")}
    for gone in ("bd/auth.js", "bd/js/auth.js", "bd/js/mock-data.js", "bd/js/api.js", "bd/js/icons.js",
                 "bd/js/bd-icons.js", "bd/js/shared.js", "bd/styles.css", "bd/fonts"):
        assert gone not in names, "%s came over from BD's own shell" % gone
    for js in JS_FILES:
        code = re.sub(r"/\*.*?\*/|//[^\n]*", "", js.read_text(encoding="utf-8"), flags=re.S)
        for word in ("BDAuth", "BD_MOCK", "BDMock", "BDIcon", "bd-sidebar", "bd-tabbar", "bd-topbar",
                     "renderSidebar"):
            assert word not in code, "%s still reaches for %s" % (rel(js), word)


# ── no emoji ─────────────────────────────────────────────────────────────────────────────────
BD_TEXT = sorted(p for p in BD.rglob("*") if p.suffix in (".html", ".js", ".css"))


@pytest.mark.parametrize("f", BD_TEXT, ids=rel)
def test_no_emoji(f):
    bad = ["line %d: U+%04X" % (no, ord(ch))
           for no, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1) for ch in line if is_emoji(ch)]
    assert not bad, "%s has emoji code points (glyphs come from js/icons.js):\n%s" % (rel(f), "\n".join(bad))


def test_emoji_ranges():
    assert is_emoji("\U0001F5D1") and is_emoji("✅") and is_emoji("⭐") and is_emoji("️")
    assert not any(is_emoji(c) for c in "·—…“”–─═ Aa1")


# ── bd.css: the section contract ─────────────────────────────────────────────────────────────
CSS_MARKERS = [
    "/* == tokens == */", "/* == end: tokens == */",
    "/* == base == */", "/* == end: base == */",
    "/* == components == */", "/* == end: components == */",
    "/* == page: week == */", "/* == end: week == */",
    "/* == page: contacts == */", "/* == end: contacts == */",
    "/* == page: contact == */", "/* == end: contact == */",
    "/* == print, reduced motion == */",
]
# Each page section's own class prefixes; a rule in one section may not use another's. A ticket that
# moves a page adds its section (week: wk- call-, contacts: ct- add-, contact: cd-, mgmt: rv- an- ad-).
PAGE_PREFIXES = {
    "week": ["wk-", "call-"],
    # #808: Add a contact and the Contacts page's place (the Contacts list's ct- rules come with it)
    "contacts": ["ct-", "add-"],
    "contact": ["cd-"],
}


def css_src():
    return CSS.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_css_section_markers_appear_once_and_in_order():
    css = css_src()
    at = []
    for m in CSS_MARKERS:
        n = css.count(m)
        assert n == 1, "bd.css must hold %r exactly once (found %d)" % (m, n)
        at.append(css.index(m))
    assert at == sorted(at), "bd.css sections are out of order"
    for gone in ("/* == chrome", "/* == login", "/* == legacy"):
        assert gone not in css, "BD's own chrome and sign-in shell do not come over: %s" % gone


def _section(css, name):
    start = css.index("/* == page: %s == */" % name)
    return css[start:css.index("/* == end: %s == */" % name, start)]


@pytest.mark.parametrize("name", sorted(PAGE_PREFIXES))
def test_a_page_section_uses_only_its_own_prefixes(name):
    body = re.sub(r"/\*.*?\*/", "", _section(css_src(), name), flags=re.S)
    others = [p for k, ps in PAGE_PREFIXES.items() if k != name for p in ps]
    bad = sorted({m.group(0) for p in others for m in re.finditer(r"\.%s[\w-]*" % re.escape(p), body)})
    assert not bad, "the %s section styles another page's classes: %r" % (name, bad)
    mine = PAGE_PREFIXES[name]
    stray = sorted({m.group(1) for m in re.finditer(r"\.bd-app \.([\w-]+)", body)
                    if not any(m.group(1).startswith(p) for p in mine)})
    assert not stray, "the %s section styles classes that are not its own: %r" % (name, stray)


def test_the_bd_root_has_the_tools_paper_ground():
    css = css_src()
    assert re.search(r"(?m)^\.bd-app \{[^}]*background: var\(--bd-paper\)", css)
    assert re.search(r"--bd-paper: #fbf9f8;", css), "warm-paper, DESIGN.md's ground"


def test_no_font_files_and_no_font_face():
    css = css_src()
    assert "@font-face" not in css and "/fonts/" not in css, "BD's bundled Inter is not carried over"
    fonts = [rel(p) for p in BD.rglob("*") if p.suffix.lower() in (".woff", ".woff2", ".ttf", ".otf", ".eot")]
    assert fonts == [], fonts
