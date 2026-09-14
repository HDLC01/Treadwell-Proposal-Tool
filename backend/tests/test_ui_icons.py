"""Icons are drawn, never typed.

THE HOUSE RULE, written first in frontend/js/markup.js and carried into frontend/js/icons.js:

    NEVER an emoji — an emoji is drawn by whatever font the machine has, cannot take the row's
    colour, and ignores every size token on the page.

Hanz asked on 2026-09-15 for every emoji that was doing an icon's job to be replaced. Before that
sweep the app carried about ninety of them: a wastebasket on five different Delete buttons, three
padlocks on the estimate grid, a brick in the sidebar, a party popper on the notification
empty-state, four coloured circles standing in for deadline severity. Each one was drawn by
whichever emoji font the machine had, none of them took the colour of the button it sat in, and the
stylesheets sized them with `font-size` — so a red Delete button had a grey-and-white wastebasket
on it and a 44px touch target had a 16px glyph.

WHAT THESE TESTS ARE FOR. The sweep is easy to undo one call site at a time: a new renderer, a
typed ✓ because it was quicker than looking up the name, and the page has one glyph nobody can
colour. So this file pins the three things that would let that back in.

WHY THE CHARACTER SET IS WHAT IT IS. `_UI_GLYPHS` is deliberately NOT "every non-ASCII character".
This codebase's comments are full of arrows and box-drawing rules, its money is full of typographic
punctuation, and the proposal document's own bullet is a filled square that has to match the .docx
it previews. What is banned is the pictographic set — the emoji blocks plus the dingbats and
geometric shapes that were actually being used as icons — and only in the places a user can see:
rendered markup, never a comment.

DELIBERATELY STILL TYPED — ten lines in all, listed exhaustively in _ALLOWED below with the reason
beside each. Three reasons cover them: a button whose own JS overwrites its label with textContent
(an <svg> there is deleted by the first click), a CSS `content:` pseudo-element (which cannot hold
an <svg> at all), and the proposal preview's own bullet (which has to be the .docx's bullet).

ONE KNOWN HOLE, recorded rather than papered over: a CSS unicode ESCAPE — `content: "\\25AA"` — is
invisible to a scan over characters, and the codebase has three of those (the document bullet in
styles.css, the ⚠ on an overridden line, the ☰ drag grip on the options panel). Decoding escapes
before scanning would flag exactly those three, all of which belong to reasons two and three above,
so the check would gain no coverage and grow a fourth allow-list. Somebody could still smuggle an
emoji in as `content: "\\1F5D1"`. That is not a mistake anybody makes by accident, which is the
only kind of regression this file is built to catch.
"""
import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"

# The pictographic ranges, the dingbats and geometric shapes this app had pressed into service as
# icons, and the arrows that were ONLY ever icons here.
#
# ARROWS, AND WHY THIS LIST IS NOT THE WHOLE BLOCK. The first draft of this test skipped arrows
# altogether, and it passed while a mutation put "↩ Restore" back on the Trash page — the exact
# regression it exists to catch. Taking the whole U+2190-U+21FF block instead flagged eighteen
# lines, and every one of them was running text: "the beginning → today", "A→Z · low→high",
# "Typed % → county table → 6.5% floor", "before → after" in the Items page's change summary. So
# the two arrows this codebase writes IN SENTENCES — ← and → — are out, and the nine it only ever
# used as pictures are in. Those nine each have an icons.js equivalent and no prose use anywhere in
# frontend/, which is what makes banning them outright exact rather than approximate.
#
# The ← and → that survive in UI are all in the wizard's own navigation and on the Files page's
# download buttons, where test_files_page_send_block.py forbids an <svg> outright — so they are
# covered by a test either way, just not by this one.
_UI_GLYPHS = re.compile(
    "["
    "\U0001F000-\U0001FAFF"      # emoji proper
    "↑↓↗↺↩⇄⇤⇥⟲"   # the arrows that were only ever icons here
    "☀-➿"              # misc symbols + dingbats (✓ ✕ ✎ ✉ ☰ ⚠ …)
    "⬀-⯿"
    "⏩-⏿"              # ⏱ ⏲ ⏸ ⏻
    "■-◿"              # ■ ▪ ▾ ▸ ◆ ◐ … the geometric pips
    "⧉‹›＋"        # ⧉ ‹ › ＋
    "️"                     # the variation selector that forces emoji presentation
    "]"
)

def _without_comments(text, suffix):
    """The same text with every comment blanked out, LINE COUNT AND ALL.

    Comments are not UI and are excluded on purpose: several of them name the glyph they replaced,
    which is how a reader finds out what changed and why. Blanking rather than deleting is what
    keeps the line numbers in a failure message pointing at the real line.

    `//` is only treated as a comment when it is not preceded by a colon, so the `https://` in a
    CDN src or a comment about a URL does not swallow the rest of its line.
    """
    def blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))

    if suffix in (".html", ".css"):
        text = re.sub(r"<!--.*?-->", blank, text, flags=re.S)
    text = re.sub(r"/\*.*?\*/", blank, text, flags=re.S)
    if suffix in (".js", ".html"):
        text = re.sub(r"(?<!:)//[^\n]*", blank, text)
    return text

# EVERY typed glyph still rendered anywhere in frontend/, and why it is still typed. Ten lines, and
# the list is exhaustive: emptying this dict and re-running prints exactly these ten and nothing
# else. Keyed by file, holding a substring that identifies the line.
#
# A new entry is a decision, not a formality. "It was quicker" is not one of the three reasons
# below; if a new case does not fit one of them, draw the icon.
_ALLOWED = {
    # ── 1. buttons whose own JS replaces the label with textContent on the first click ──────────
    # An <svg> in the static markup is deleted by that first click and never comes back — which is
    # not a styling choice but a bug with a delay on it. Asserted by
    # test_files_page_send_block.py::test_no_button_the_javascript_rewrites_carries_an_icon, which
    # forbids an <svg> inside these ids OUTRIGHT. Where the JS writes the label itself it now
    # writes a drawn glyph with it (done.js's "Downloaded", dropbox.js's "Filed to"); it is only
    # the resting label in the HTML that has to stay plain text.
    "done.html": ("dl-xlsx", "dl-docx", "dl-pdf", "portal-btn"),
    "js/dropbox.js": ("✓ Uploaded",),

    # ── 2. CSS `content:` pseudo-elements ──────────────────────────────────────────────────────
    # A pseudo-element cannot hold an <svg>. The alternatives are a data-URI mask (which the CSP
    # in nginx would have to be widened for) or a real DOM node per cell — and two of these four
    # sit on the estimate and info-sheet grids, which render tens of thousands of cells.
    "library.html": ('content:"✓"',),                 # the Divisions chip's tick
    "projects.html": ('content:"✓"',),                # the estimator picker's "chosen" tick
    "info-sheet.html": ('content: "▾"',),             # a grid cell that has a dropdown
    "estimate-review.html": ('content: "⟲"',),        # the canonical-mirror chain

    # ── 3. the proposal document's own glyph ───────────────────────────────────────────────────
    # proposal-review.html is a to-scale preview of the printed page, registered against baked
    # artwork, and the editor serialises these lines back into the .docx run by run. This square is
    # the bullet the Word template draws (see the numPr note in proposal_writer.py) — an <svg> node
    # here would both move the text and reach the customer's document.
    "proposal-review.html": ('content: "■"',),
}

_SKIP_FILES = {
    # The icon table itself, whose header quotes the rule and names what it replaced.
    "js/icons.js",
    # Hand-written reference tables in module docstrings, read by developers only.
    "js/library-core.js",
}


def _ui_files():
    for p in sorted(FRONTEND.rglob("*")):
        if p.suffix.lower() not in (".html", ".js", ".css"):
            continue
        rel = p.relative_to(FRONTEND).as_posix()
        if rel in _SKIP_FILES:
            continue
        yield rel, p


def _offending_lines(rel, path):
    """Every line in `path` that renders a banned glyph, minus comments and the allow-list."""
    allowed = _ALLOWED.get(rel, ())
    raw = path.read_text(encoding="utf-8").splitlines()
    stripped = _without_comments(path.read_text(encoding="utf-8"), path.suffix.lower()).splitlines()
    out = []
    for n, line in enumerate(stripped, 1):
        if not _UI_GLYPHS.search(line):
            continue
        if any(a and a in raw[n - 1] for a in allowed):
            continue
        out.append("%s:%d: %s" % (rel, n, raw[n - 1].strip()[:140]))
    return out


# ── 1. no page renders a typed glyph where an icon belongs ────────────────────
def test_no_frontend_file_renders_a_typed_glyph_as_an_icon():
    """The sweep, held. A new renderer that types "✓" instead of asking icons.js for "check" fails
    here with its own file and line number.

    If a NEW case genuinely cannot be drawn — another CSS pseudo-element, another button whose JS
    rewrites its label — add it to _ALLOWED with the reason, the way the existing entries record
    theirs. Widening `_UI_GLYPHS`'s exceptions instead would turn this test off for the whole app.
    """
    bad = []
    for rel, path in _ui_files():
        bad += _offending_lines(rel, path)
    assert not bad, (
        "a typed glyph is being rendered as a UI icon. Ask js/icons.js for it instead — "
        "TWIcon(name, size) — or add the case to _ALLOWED in this file with the reason:\n  "
        + "\n  ".join(bad))


# ── 2. the table is reachable everywhere it is used ───────────────────────────
def test_every_page_that_draws_the_sidebar_also_loads_the_icon_table():
    """auth.js draws the nav rail out of js/icons.js, so a page that loads auth.js without it gets
    a sidebar of empty boxes — and every page in this app loads auth.js.

    The failure is silent by design (icon() is guarded, so a missing table costs the pictures and
    not the render), which is exactly why it needs a test rather than a stack trace.
    """
    missing = []
    for p in sorted(FRONTEND.glob("*.html")):
        html = p.read_text(encoding="utf-8")
        if 'src="/auth.js"' not in html:
            continue
        if 'src="/js/icons.js"' not in html:
            missing.append(p.name)
    assert not missing, (
        "these pages load auth.js but not js/icons.js, so their sidebar draws no icons: %s"
        % ", ".join(missing))


def test_the_icon_table_loads_before_the_file_that_draws_the_sidebar():
    """Order, not just presence. auth.js reads window.TWIcon at render time rather than at parse
    time, so today a later icons.js would still work — and relying on that is how the load-order
    bug in test_polish_estimate_page.py got written. One rule, checkable: the table comes first.
    """
    wrong = []
    for p in sorted(FRONTEND.glob("*.html")):
        html = p.read_text(encoding="utf-8")
        if 'src="/auth.js"' not in html or 'src="/js/icons.js"' not in html:
            continue
        if html.index('src="/js/icons.js"') > html.index('src="/auth.js"'):
            wrong.append(p.name)
    assert not wrong, "js/icons.js is loaded after auth.js on: %s" % ", ".join(wrong)


# ── 3. the glyphs themselves keep the house geometry ──────────────────────────
@pytest.fixture(scope="module")
def icons_src():
    return (FRONTEND / "js" / "icons.js").read_text(encoding="utf-8")


def test_every_glyph_is_drawn_to_the_house_geometry(icons_src):
    """24x24 box, no fill, currentColor stroke, width 2, round caps and joins, and hidden from the
    accessibility tree because the control it sits in already carries the name.

    currentColor is the half that matters most and the half a rewrite loses first: it is what makes
    a danger button's icon red because the BUTTON is red, and what dims a disabled row's icon with
    the row. A hardcoded stroke would look identical on the page this was tested on and wrong
    everywhere else.
    """
    m = re.search(r"return '<svg.*?</svg>\";", icons_src, re.S)
    assert m, "icons.js no longer builds its <svg> in one place — re-derive this check"
    wrapper = m.group(0)
    for need in ('viewBox="0 0 24 24"', 'fill="none"', 'stroke="currentColor"',
                 'stroke-width="2"', 'stroke-linecap="round"', 'stroke-linejoin="round"',
                 'aria-hidden="true"', 'focusable="false"', 'tw-ico'):
        assert need in wrapper, "the shared <svg> wrapper lost %s" % need


def test_the_class_the_app_wide_icon_rules_hang_on_is_still_there():
    """`.tw-ico` carries two rules from auth.js's injected stylesheet — the one stylesheet every
    page gets — and both matter: the glyph must not swallow a click meant for the button around it,
    and it must sit on the text's optical centre. Drop the class from icons.js and both silently
    stop applying, on every page at once, with nothing visibly broken until somebody's press lands
    on the icon instead of the control.
    """
    auth = (FRONTEND / "auth.js").read_text(encoding="utf-8")
    m = re.search(r"\.tw-ico\{([^}]*)\}", auth)
    assert m, "auth.js's stylesheet no longer carries a .tw-ico rule"
    assert "pointer-events:none" in m.group(1), (
        "an icon can swallow the click meant for its own button")
    # And the class is not styled with an attribute selector, which the phone-shell resolver
    # refuses to parse — see the note in icons.js.
    assert 'svg[aria-hidden="true"][focusable="false"]{' not in auth, (
        "auth.js styles icons by attribute selector again; test_phone_shell.py's resolver cannot "
        "read one and fails rather than going blind")


def test_no_glyph_carries_its_own_colour(icons_src):
    """The path data is geometry and nothing else. A `fill="#c8102e"` or a `stroke="#1b1c1c"`
    smuggled into one entry would make that one glyph ignore the row's colour — the emoji problem
    this whole change was about, reintroduced in SVG and much harder to spot.

    `width`/`height` are NOT banned: a <rect> needs them, and they are in the 24-box's own
    coordinate space rather than in pixels, so they scale with the caller's size like everything
    else in the path.
    """
    paths = icons_src[icons_src.index("var PATHS = {"):icons_src.index("/** One glyph, as an SVG")]
    for bad in ("fill=", "stroke=", "style=", "#", "!important"):
        assert bad not in paths, (
            "a glyph's path data carries %r — presentation belongs to the wrapper, not the entry"
            % bad)


def test_an_unknown_name_draws_an_empty_box_rather_than_throwing(icons_src):
    """A renderer half-way through building a row must not take the page down over a typo, and an
    empty square is visible in review in a way a silent `undefined` is not.

    It is also what makes confirmDanger's `icon` option safe to pass a caller's string to: the name
    indexes a table and is never concatenated into the output. test_library_ui.py proves that end
    of it by running the real dialog with a hostile name.
    """
    assert "hasOwnProperty.call(PATHS, name) ? PATHS[name] : \"\"" in icons_src, (
        "icons.js no longer falls back to an empty glyph for an unknown name")
