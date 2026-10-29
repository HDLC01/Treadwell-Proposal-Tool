"""The wizard pages cross-fade from one to the next instead of flashing an empty page.

Hanz, 2026-10-29: "In the files page we should also look into it because when I transfer tabs with
multiple proposals it flashes white as well." Switching proposals (the Files page's Lump sums list,
the Proposal page's tab strip) and every step pill is a real page load, and stays one: the single
localStorage draft slot and each page's one-shot state snapshot depend on it. What changed is how the
load looks:

  * reveal.css opts the seven wizard pages (and only them) into a cross-document view transition;
  * js/reveal.js, loaded in <head>, holds the fade on the old page until the new one has drawn its
    content (TWReveal.done, or the page's `data-tw-drawn` rule) AND its sidebar, capped at 1.5 s,
    and keeps the sidebar from sliding in on arrival.

EXECUTED: tests/js/reveal-harness.js runs the real reveal.js and the pages' own "drawn" calls lifted
from done.js and proposal-review.js. Each part is then broken in a scratch copy and a scenario is
required to go red, so none of these can pass by checking nothing.
"""
from __future__ import annotations

import html.parser
import pathlib
import re
import shutil

import pytest

from _node import last_json_line, run_node

TESTS = pathlib.Path(__file__).resolve().parent
FRONTEND = TESTS.parents[1] / "frontend"
HARNESS = TESTS / "js" / "reveal-harness.js"

WIZARD = ["index.html", "polish-intake.html", "estimate-review.html", "polish-estimate.html",
          "generate.html", "proposal-review.html", "done.html"]


def run(frontend=None):
    proc = run_node(HARNESS, *([frontend] if frontend else []))
    out = last_json_line(proc.stdout)
    return out


# ── the hold, run ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def ran():
    out = run()
    assert "error" not in out, out.get("error")
    return out


EXPECTED = {
    "hold": ["pausedAtStart", "bootingAtStart", "stillHeldWithoutSidebar", "playedOnceReady", "unbooted"],
    "onlyVt": ["vtPaused", "otherRunning"],
    "cap": ["heldAt1499", "releasedAt1500"],
    "rule": ["heldWhileHidden", "releasedOnceShown"],
    "waits": ["heldOnOne", "releasedOnBoth"],
    "noVt": ["booting", "unbootedOnDraw"],
    "early": ["notPaused"],
    "skipped": ["ok"],
    "filesList": ["heldWhileReading", "paintedBeforeRelease", "releasedAfterPaint"],
    "readyList": ["heldWhileReading", "painted", "released"],
    "proposal": ["heldOnTabsAlone", "releasedOnBoth"],
}


@pytest.mark.parametrize("scenario", sorted(EXPECTED))
def test_the_hold(ran, scenario):
    got = ran[scenario]
    assert set(got) == set(EXPECTED[scenario]), got
    assert all(got[k] is True for k in EXPECTED[scenario]), got


# Each break, in a scratch copy, and the scenario value it must turn false. Single-line targets, so a
# checkout with CRLF line endings breaks the same text as one with LF.
BREAKS = [
    ("js/reveal.js", "if (drawn && sidebarUp()) { release(); return; }", "if (drawn) { release(); return; }",
     ("hold", "stillHeldWithoutSidebar")),
    ("js/reveal.js", "for (var i = 0; i < held.length; i++) held[i].pause();", "",
     ("hold", "pausedAtStart")),
    ("js/reveal.js", 'if (root && root.classList) root.classList.remove("tw-booting");', "",
     ("hold", "unbooted")),
    ("js/reveal.js", "setTimeout(release, HOLD_MS);", "",
     ("cap", "releasedAt1500")),
    ("js/reveal.js", "el.getClientRects().length", "el.getClientRects()",
     ("rule", "heldWhileHidden")),
    ("js/reveal.js", 'return typeof pe === "string" && pe.indexOf("::view-transition") === 0;', "return true;",
     ("onlyVt", "otherRunning")),
    ("js/reveal.js", "if (--left === 0) drawn = true;", "drawn = true;",
     ("waits", "heldOnOne")),
    # The call taken out (a `return` in place of the comment above it, so the paint still runs)...
    ("js/done.js", "// The page is drawn: js/reveal.js may now play the fade from the page before (a no-op after).",
     "return;", ("filesList", "releasedAfterPaint")),
    # ...and made before the list is read rather than once it is painted.
    ("js/done.js", "const seq = ++filesProposals.seq;",
     'if (typeof TWReveal !== "undefined") TWReveal.done(); const seq = ++filesProposals.seq;',
     ("filesList", "heldWhileReading")),
    ("js/done.js", 'if (typeof TWReveal !== "undefined") TWReveal.done();   // drawn (js/reveal.js)', "",
     ("readyList", "released")),
    ("js/proposal-review.js", "TWReveal.done(_tabsMounted, _firstDocLoad);", "TWReveal.done(_tabsMounted);",
     ("proposal", "heldOnTabsAlone")),
]


@pytest.mark.parametrize("rel,old,new,where", BREAKS, ids=[f"{b[0]}:{b[3][0]}.{b[3][1]}" for b in BREAKS])
def test_each_part_is_load_bearing(tmp_path, rel, old, new, where):
    src = (FRONTEND / rel).read_bytes().decode("utf-8")
    assert src.count(old) == 1, f"the text this break targets is not in {rel} exactly once: {old!r}"
    broken = src.replace(old, new)
    assert broken != src
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(broken.encode("utf-8"))
    assert target.read_bytes() != (FRONTEND / rel).read_bytes(), "the break did not reach the scratch copy"
    out = run(tmp_path)
    scenario, key = where
    assert "error" not in out, out.get("error")
    assert out[scenario][key] is False, (f"broke {rel} ({old!r}) and {scenario}.{key} stayed green", out[scenario])


def test_the_fixed_files_pass_from_a_scratch_copy_too(tmp_path):
    """The control for the breaks above: the same scratch-directory path, unbroken, is all green."""
    for rel in ("js/reveal.js", "js/done.js", "js/proposal-review.js"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FRONTEND / rel, tmp_path / rel)
    out = run(tmp_path)
    assert "error" not in out, out.get("error")
    assert all(v is True for s in EXPECTED for v in out[s].values()), out


# ── the pages ─────────────────────────────────────────────────────────────────────────────────
class _Head(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_head = False
        self.html_attrs = {}
        self.head_links, self.head_scripts, self.styles = [], [], []
        self._style = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.html_attrs = a
        elif tag == "head":
            self.in_head = True
        elif tag == "link" and self.in_head and a.get("rel") == "stylesheet":
            self.head_links.append(a.get("href", ""))
        elif tag == "script" and self.in_head and a.get("src"):
            self.head_scripts.append(a)
        elif tag == "style" and self.in_head:
            self._style = []

    def handle_data(self, data):
        if self._style is not None:
            self._style.append(data)

    def handle_endtag(self, tag):
        if tag == "head":
            self.in_head = False
        elif tag == "style" and self._style is not None:
            self.styles.append("".join(self._style))
            self._style = None


def head(name):
    p = _Head()
    p.feed((FRONTEND / name).read_text(encoding="utf-8"))
    p.close()
    return p


@pytest.mark.parametrize("name", WIZARD)
def test_a_wizard_page_loads_the_fade_and_its_hold_in_head(name):
    h = head(name)
    assert "/reveal.css" in h.head_links, f"{name} does not opt into the cross-fade"
    tag = [s for s in h.head_scripts if s["src"].split("?")[0] == "/js/reveal.js"]
    assert tag, f"{name} has the fade but not its hold: it would fade to an empty page"
    # Synchronous and in <head>: `pagereveal` fires before the first frame, and a deferred or
    # late listener never hears it. A same-origin file, never inline (the CSP refuses inline script).
    assert "defer" not in tag[0] and "async" not in tag[0] and tag[0].get("type") in (None, "text/javascript")


def test_only_the_wizard_pages_opt_in():
    """A transition runs only when both pages opt in. A page with the fade and no hold would fade to
    its own empty first frame; a page with neither keeps loading the way it always has."""
    opted = sorted(p.name for p in FRONTEND.glob("*.html") if "/reveal.css" in head(p.name).head_links)
    assert opted == sorted(WIZARD)
    held = sorted(p.name for p in FRONTEND.glob("*.html") if "/js/reveal.js" in p.read_text(encoding="utf-8"))
    assert held == sorted(WIZARD)


DRAWN_BY_SCRIPT = {"done.html": "js/done.js", "proposal-review.html": "js/proposal-review.js"}


@pytest.mark.parametrize("name", WIZARD)
def test_every_wizard_page_says_when_it_has_drawn(name):
    """Without either, every load waits out the whole 1.5 s cap on the old page."""
    rule = head(name).html_attrs.get("data-tw-drawn")
    script = DRAWN_BY_SCRIPT.get(name)
    assert rule or script, f"{name} never says it has drawn"
    if script:
        assert "TWReveal.done(" in (FRONTEND / script).read_text(encoding="utf-8")
    if rule:
        markup = (FRONTEND / name).read_text(encoding="utf-8")
        for ident in re.findall(r"#([\w-]+)", rule):
            assert f'id="{ident}"' in markup, f"{name}'s drawn rule names #{ident}, which is not on the page"
        if not re.findall(r"#([\w-]+)", rule):
            assert f"<{rule}" in markup


def _strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def test_the_fade_is_on_and_reduced_motion_turns_it_off():
    css = _strip_comments((FRONTEND / "reveal.css").read_text(encoding="utf-8"))
    flat = re.sub(r"\s+", " ", css)
    assert "@view-transition { navigation: auto; }" in flat
    reduced = flat[flat.index("@media (prefers-reduced-motion: reduce)"):]
    assert reduced.split("}")[0].strip().endswith("@view-transition { navigation: none;")


@pytest.mark.parametrize("name", WIZARD + ["reveal.css", "styles.css"])
def test_nothing_is_named(name):
    """A name pairs the two pages only if its element is in the new page's FIRST frame; the sidebar
    and the proposal tab strip are not, and the header is not sticky. See reveal.css."""
    if name.endswith(".css"):
        css = (FRONTEND / name).read_text(encoding="utf-8")
    else:
        css = "\n".join(head(name).styles)
    assert "view-transition-name" not in _strip_comments(css)


def test_the_sidebar_does_not_slide_in_while_the_page_boots():
    """auth.js gives body and #tw-sidebar a transition; while `html.tw-booting` is on, reveal.css
    turns both off so the open rail is drawn open. The child combinator needs the rail on <body>."""
    css = _strip_comments((FRONTEND / "reveal.css").read_text(encoding="utf-8"))
    rule = re.search(r"html\.tw-booting body,\s*html\.tw-booting body > #tw-sidebar\s*\{([^}]*)\}", css)
    assert rule and "transition: none" in rule.group(1)
    auth = (FRONTEND / "auth.js").read_text(encoding="utf-8")
    assert "document.body.appendChild(aside);" in auth
    assert "body{transition:margin-left .2s ease;}" in auth


def _page_background(name):
    """The background the page's own head CSS gives <body>, with one level of var() resolved."""
    h = head(name)
    css = "\n".join(h.styles)
    if "/styles.css" in h.head_links:
        css = (FRONTEND / "styles.css").read_text(encoding="utf-8") + "\n" + css
    css = _strip_comments(css)
    found = None
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        names = [s.strip() for s in sel.split(",")]
        m = re.search(r"background(?:-color)?\s*:\s*([^;]+)", body)
        if m and "body" in names:
            found = m.group(1).strip()
    assert found, f"{name} sets no body background"
    var = re.match(r"var\((--[\w-]+)(?:,\s*([^)]+))?\)", found)
    if var:
        decl = re.findall(re.escape(var.group(1)) + r"\s*:\s*([^;]+);", css)
        found = decl[0].strip() if decl else (var.group(2) or "").strip()
    return found.lower()


@pytest.mark.parametrize("name", WIZARD)
def test_the_page_behind_the_content_is_never_white(name):
    """What shows between the fade and the content is the app's surface, not a white page."""
    assert _page_background(name) not in ("", "#fff", "#ffffff", "white", "transparent")
