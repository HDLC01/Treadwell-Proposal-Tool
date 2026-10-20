"""THE FIXED TOTAL BAR STARTS WHERE THE PAGE STARTS, NOT UNDER THE STAFF SIDEBAR (the 2026-10-20 staging walk of #694, round 6, item B2).

WHAT WAS WRONG. `#bidbar` (polish-estimate.html, `.bid`) was `position: fixed; left: 0; right: 0`, so it ran UNDER the sidebar auth.js opens on a desktop window (`#tw-sidebar`, z-index 9998, 240px).
The page itself is not under it: while the sidebar is open at 768px and up, auth.js gives the body `margin-left: var(--tw-w)`, and a margin cannot move a fixed element. At a 916px window the bar's
first 240px, where its Material and Labor sums begin, were hidden: all the walk saw of "Polish copy $18,339 + Polish $18,339 option (not in the lump sum)" was "18 option (not in the lump sum)".
Anywhere the window is narrower than about 1436px (the bar's 1000px column is centred in the window and its text starts 22px inside that, so below it the text starts left of the sidebar's 240px
edge) the start of it is lost.

THE RULE IS THE APP'S OWN. styles.css moves its fixed "Proposal fields" panel with `html.tw-nav-open .fields-panel { left: calc(var(--tw-w, 240px) + 16px) }` and auth.js moves its own fixed top bar with
`@media (min-width:768px){ html.tw-nav-open #tw-topbar{left:var(--tw-w);} }`. The total bar takes the second form, because it is a bar that runs edge to edge (no 16px inset) and because the shell
only shifts the page at 768px and up. THREE STATES, as auth.js sets them:

  * open, 768px and up: the sidebar is a rail BESIDE the page and the body moves right by its width, so the bar starts at the rail's right edge too;
  * shut: nothing moves, the bar runs from the window's left edge;
  * under 768px: the sidebar is a SHEET laid over the page with a scrim (`#tw-backdrop`, shown at max-width 767px) and the body does NOT move, so the bar must not move either: the scrim and the sheet cover
    it exactly as they cover the page, and an offset there would slide the bar out from under the scrim while the page stayed put.

HOW IT IS CHECKED. A headless run lays nothing out, so this file resolves the CASCADE: it reads the page's CSS and the CSS auth.js injects, takes the declarations that apply to the bar (and to the body, and
to the sidebar) at a given window width and sidebar state, orders them as a browser does (importance, specificity, source order) and reads the winner. The one invariant that carries the fix is "the bar
starts where the page column starts, at every width, in every sidebar state"; that also ties the bar to auth.js's own breakpoint and width, so a shell that stops moving the body, without the page, goes red.
A regex for `left:var(--tw-w` would pass on a rule that sits in the wrong @media, or that offsets a shut sidebar. The resolver's own tests (toy stylesheets with known answers, and the refusal to skip a rule it
cannot read) stand in for a mutation of the page, as they do in test_phone_shell.py.

The last block puts the old rule (and each part of the new one, one at a time) back into a COPY of the page, and breaks a COPY of auth.js, and requires the check to find it: a check that has never failed
proves nothing.
"""
from __future__ import annotations

import re

import pytest

from _golden_support import FRONTEND, break_source

PAGE_PATH = FRONTEND / "polish-estimate.html"
AUTH_PATH = FRONTEND / "auth.js"

# the windows the check walks: phones, the pixel either side of the shell's 768px breakpoint, the walk's 916px, laptops, a desktop
WINDOWS = (360, 375, 390, 414, 600, 767, 768, 800, 916, 1024, 1280, 1440, 1920)
PHONES = (360, 375, 390, 414, 600, 767)

# elements, as (tag, id, classes)
BAR = ("div", "bidbar", ("bid",))
INNER = ("div", "", ("bid-in",))
SIDEBAR = ("aside", "tw-sidebar", ())
BODY = ("body", "", ())
BACKDROP = ("div", "tw-backdrop", ())


# ── a small cascade resolver ─────────────────────────────────────────────────────────────────────────────
def _strip(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def parse_rules(css: str) -> list[tuple[str, dict, str, int]]:
    """[(selector, {property: value}, media, order)] for every rule, comments removed; `media` is the prelude of the @media block the rule is in ("" at the top level), so a rule keeps the
    window it applies to. A selector LIST becomes one entry per selector. @keyframes and other at-rules are skipped whole."""
    css = _strip(css)
    out: list[tuple[str, dict, str, int]] = []
    order = [0]

    def read(text: str, media: str) -> None:
        i, n = 0, len(text)
        while i < n:
            j = text.find("{", i)
            if j < 0:
                break
            prelude, depth, k = text[i:j].strip(), 1, j + 1
            while k < n and depth:
                depth += {"{": 1, "}": -1}.get(text[k], 0)
                k += 1
            body = text[j + 1:k - 1]
            if prelude.startswith("@media"):
                read(body, re.sub(r"\s+", " ", prelude[len("@media"):].strip()))
            elif not prelude.startswith("@"):
                decls = {}
                for part in body.split(";"):
                    if ":" in part:
                        prop, value = part.split(":", 1)
                        decls[prop.strip()] = re.sub(r"\s+", " ", value.strip())
                for selector in prelude.split(","):
                    out.append((re.sub(r"\s+", " ", selector.strip()), decls, media, order[0]))
                    order[0] += 1
            i = k

    read(css, "")
    return out


def media_applies(media: str, width: int) -> bool:
    """A width query: `(min-width:768px)`, `(max-width:767px)`, joined by `and`, alternatives by a comma. Anything else (a height, a hover query) raises: a rule this resolver cannot place must not be skipped in silence."""
    if not media.strip():
        return True
    for alternative in media.split(","):
        verdict = True
        for part in re.split(r"\band\b", alternative):
            m = re.fullmatch(r"\s*\((min|max)-width:\s*(\d+)px\)\s*", part)
            if not m:
                raise ValueError("cannot evaluate @media %r" % media)
            n = int(m.group(2))
            verdict = verdict and (width >= n if m.group(1) == "min" else width <= n)
        if verdict:
            return True
    return False


def _compound(text: str):
    m = re.fullmatch(r"([a-z][\w-]*)?(#[\w-]+)?((?:\.[\w-]+)*)", text)
    if not text or not m:
        raise ValueError("cannot read the selector part %r" % text)
    return m.group(1) or "", (m.group(2) or "")[1:], [c for c in m.group(3).split(".") if c]


def _compound_matches(text: str, element) -> bool:
    tag, id_, classes = _compound(text)
    e_tag, e_id, e_classes = element
    return (not tag or tag == e_tag) and (not id_ or id_ == e_id) and all(c in e_classes for c in classes)


def could_match(selector: str, element) -> bool:
    """Could the LAST part of the selector (the one that names the element itself) be this element? A rule about some other element, whatever it says in front, is out of the way and need not be readable;
    a pseudo-class or an attribute only narrows a match, so it does not make a part impossible. A part this cannot read at all is answered True, and selector_matches then refuses it."""
    last = re.split(r"\s*[>+~]\s*|\s+", selector.strip())[-1]
    if "::" in last:
        return False
    last = re.sub(r"\[[^\]]*\]|:[\w-]+(?:\([^)]*\))?", "", last)
    m = re.fullmatch(r"([a-z][\w-]*)?(#[\w-]+)?((?:\.[\w-]+)*)", last)
    if not m or not last:
        return True
    tag, id_, classes = m.group(1) or "", (m.group(2) or "")[1:], [c for c in m.group(3).split(".") if c]
    e_tag, e_id, e_classes = element
    return (not tag or tag == e_tag) and (not id_ or id_ == e_id) and all(c in e_classes for c in classes)


def selector_matches(selector: str, element, ancestors) -> bool:
    """Descendant selectors over tag, #id and .class only, the shapes this page and the shell's sheet use for a bar, a body and a sidebar. A pseudo-ELEMENT (`::after`) is never the element itself.
    Anything else (a pseudo-class, an attribute, a child combinator) raises ValueError, so a rule that could apply is never ignored for being unreadable."""
    if "::" in selector:
        return False
    if any(ch in selector for ch in ">+~[]:()*"):
        raise ValueError("cannot read the selector %r" % selector)
    parts = selector.split()
    if not parts or not _compound_matches(parts[-1], element):
        for part in parts[:-1]:
            _compound(part)                       # an unreadable ancestor part is still reported
        return False
    remaining = list(ancestors)
    for part in parts[:-1]:                       # each ancestor part must be found, in order, among the element's ancestors
        while remaining and not _compound_matches(part, remaining[0]):
            remaining.pop(0)
        if not remaining:
            return False
        remaining.pop(0)
    return True


def specificity(selector: str) -> tuple[int, int, int]:
    ids = classes = tags = 0
    for part in selector.split():
        tag, id_, cls = _compound(part)
        ids += 1 if id_ else 0
        classes += len(cls)
        tags += 1 if tag else 0
    return ids, classes, tags


def resolve(rules, prop: str, element, width: int, nav_open: bool, parents=()):
    """The value a browser would use for `prop` on `element` (a (tag, id, classes) triple) in a window `width` px wide, with the sidebar's `tw-nav-open` class on <html> or not; None when no rule sets it.
    `parents` are the element's ancestors below <body>, outermost first. Only rules that DECLARE the property are examined, so a selector this resolver cannot read in a rule about something else is not in the way."""
    html = ("html", "", ("tw-nav-open",) if nav_open else ())
    ancestors = [html] if element[0] == "body" else [html, BODY, *parents]
    best, winner = None, None
    for selector, decls, media, order in rules:
        if prop not in decls or not could_match(selector, element):
            continue
        if not selector_matches(selector, element, ancestors) or not media_applies(media, width):
            continue
        value = decls[prop]
        important = "!important" in value
        key = (important, specificity(selector), order)
        if best is None or key > best:
            best, winner = key, value.replace("!important", "").strip()
    return winner


def root_variables(rules) -> dict:
    out = {}
    for selector, decls, _media, _order in rules:
        if selector == ":root":
            out.update({k: v for k, v in decls.items() if k.startswith("--")})
    return out


def length(value: str, variables: dict) -> float:
    """A length in px: `0`, `240px`, `var(--tw-w)`, `var(--tw-w,240px)`, `calc(var(--tw-w,240px) + 16px)`."""
    value = value.strip()
    m = re.fullmatch(r"var\(\s*(--[\w-]+)\s*(?:,\s*(.+))?\)", value)
    if m:
        if m.group(1) in variables:
            return length(variables[m.group(1)], variables)
        if m.group(2) is not None:
            return length(m.group(2), variables)
        raise ValueError("%s is not defined" % m.group(1))
    m = re.fullmatch(r"calc\((.+)\)", value)
    if m:
        terms = re.split(r"\s+([+-])\s+", m.group(1).strip())
        total = length(terms[0], variables)
        for i in range(1, len(terms), 2):
            total += (1 if terms[i] == "+" else -1) * length(terms[i + 1], variables)
        return total
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)(px)?", value)
    if m and (m.group(2) or float(m.group(1)) == 0):
        return float(m.group(1))
    raise ValueError("cannot read the length %r" % value)


# ── the page and the shell, as they ship ─────────────────────────────────────────────────────────────────
def page_rules(page: str):
    return parse_rules(page[page.index("<style>") + len("<style>"):page.index("</style>")])


def shell_of(source: str | None = None):
    """(rules, variables) of the one long template literal auth.js injects on every page (injectSidebarStyles): the sidebar, the burger, the scrim and the body's margin. `source` is auth.js's text
    (the repository's, unless a test has broken a copy)."""
    src = AUTH_PATH.read_text(encoding="utf-8") if source is None else source
    start = src.index("const css = `")
    rules = parse_rules(src[start + len("const css = `"):src.index("`;", start)])
    return rules, root_variables(rules)


SHELL = shell_of()


def bar_left(page: str, width: int, nav_open: bool, shell=SHELL) -> float:
    value = resolve(page_rules(page), "left", BAR, width, nav_open)
    return 0.0 if value is None else length(value, shell[1])


def page_left(width: int, nav_open: bool, shell=SHELL) -> float:
    """Where the page column starts: the body's left margin, which auth.js sets."""
    value = resolve(shell[0], "margin-left", BODY, width, nav_open)
    return 0.0 if value is None else length(value, shell[1])


def sidebar_right(width: int, nav_open: bool, shell=SHELL) -> float:
    """The right edge of the sidebar when it is a rail beside the page (open, 768px and up); 0 when there is none."""
    if not nav_open or media_applies("(max-width:767px)", width):
        return 0.0
    return length(resolve(shell[0], "width", SIDEBAR, width, nav_open), shell[1])


def text_start(page: str, width: int, nav_open: bool, shell=SHELL) -> float:
    """Where the first of the bar's text starts: the bar's left edge, plus the room `.bid-in` leaves when the bar is wider than its 1000px column (it is centred in it), plus its left padding.
    The scrollbar is ignored (it moves this by under 8px)."""
    rules = page_rules(page)
    left = bar_left(page, width, nav_open, shell)
    column = length(resolve(rules, "max-width", INNER, width, nav_open, parents=[BAR]), shell[1])
    sides = resolve(rules, "padding", INNER, width, nav_open, parents=[BAR]).split()
    pad = length(sides[1 if len(sides) > 1 else 0], shell[1])
    room = width - left
    return left + (room - min(room, column)) / 2 + pad


# ── the checks: each returns what is wrong, as sentences ─────────────────────────────────────────────────
def problems(page: str, shell=SHELL) -> list[str]:
    """Every way the bar and the page column disagree, over the windows and the two sidebar states."""
    found: list[str] = []
    for width in WINDOWS:
        for nav_open in (False, True):
            state = "open" if nav_open else "shut"
            left, column, rail = bar_left(page, width, nav_open, shell), page_left(width, nav_open, shell), sidebar_right(width, nav_open, shell)
            if left < rail:
                start = text_start(page, width, nav_open, shell)
                found.append("under the sidebar: at %dpx with the sidebar %s the bar starts at %dpx and the sidebar's right edge is at %dpx: %dpx of the bar lie under it, its text starts at %dpx, "
                             "so %dpx of its text are hidden" % (width, state, left, rail, rail - left, start, max(0, rail - start)))
            if left != column:
                found.append("not with the page: at %dpx with the sidebar %s the page column starts at %dpx and the bar at %dpx"
                             % (width, state, column, left))
    return sorted(set(found))


def walk_problems(page: str, shell=SHELL) -> list[str]:
    """The walk's own window, 916px: the sidebar is 240px; the bar starts at 240px when it is open, so its Material and Labor sums, the first of its text, are in view, and at the window's edge when it is shut."""
    found = []
    rail = sidebar_right(916, True, shell)
    if rail != 240.0:
        found.append("the walk's premise is gone: the sidebar is %dpx wide at 916px, not 240px" % rail)
    if bar_left(page, 916, True, shell) != rail:
        found.append("at 916px with the sidebar open the bar starts at %dpx under a %dpx sidebar" % (bar_left(page, 916, True, shell), rail))
    if bar_left(page, 916, False, shell) != 0.0:
        found.append("at 916px with the sidebar shut the bar starts at %dpx, not at the window's edge" % bar_left(page, 916, False, shell))
    return found


def phone_problems(page: str, shell=SHELL) -> list[str]:
    """Below 768px the sidebar is a modal sheet with a scrim and auth.js does not move the body: no state of the sidebar may move the bar."""
    found = []
    for width in PHONES:
        for nav_open in (False, True):
            if page_left(width, nav_open, shell) != 0.0:
                found.append("the shell moves the body at %dpx: this check's premise is gone" % width)
            elif bar_left(page, width, nav_open, shell) != 0.0:
                found.append("the bar moves at %dpx with the sidebar %s, to %dpx, while the body stays put under the scrim"
                             % (width, "open" if nav_open else "shut", bar_left(page, width, nav_open, shell)))
    return found


def slide_problems(page: str, shell=SHELL) -> list[str]:
    """The body slides over .2s when the sidebar opens or shuts (auth.js: `body{transition:margin-left .2s ease}`); the bar slides with it, in the same time and curve, rather than snapping."""
    body = resolve(shell[0], "transition", BODY, 1280, True) or ""
    m = re.search(r"margin-left\s+([\d.]+m?s)\s+([\w-]+)", body)
    assert m, "auth.js no longer slides the body's margin: %r" % body
    bar = resolve(page_rules(page), "transition", BAR, 1280, True) or ""
    n = re.search(r"\bleft\s+([\d.]+m?s)\s+([\w-]+)", bar)
    if not n:
        return ["no slide: the bar's transition is %r, so it snaps while the page slides" % bar]
    if n.groups() != m.groups():
        return ["the bar slides in %s %s and the page in %s %s" % (n.group(1), n.group(2), m.group(1), m.group(2))]
    return []


def rule_problems(page: str) -> list[str]:
    """The bar's own rule keeps what other tests read from it: test_v2_sheets_panel.py reads `.bid{...z-index:N}` to keep the sticky head over the bar and under every overlay."""
    style = page[page.index("<style>"):page.index("</style>")]
    found = []
    if not re.search(r"\.bid\{[^}]*z-index:9[;}]", style):
        found.append("the .bid rule no longer holds z-index:9, where the sticky head's test reads it")
    if not re.search(r"\.bid\{position:fixed;", style):
        found.append("the bar is not position:fixed")
    return found


# ── the assertions ───────────────────────────────────────────────────────────────────────────────────────
PAGE = PAGE_PATH.read_text(encoding="utf-8")


def test_the_bar_starts_where_the_page_column_starts_at_every_width_in_every_sidebar_state():
    """The invariant that carries the fix, over 13 window widths (the pixel either side of the shell's 768px breakpoint among them) and the sidebar open and shut: the sidebar is a rail beside the page
    from 768px up, and the bar starts exactly where the body does; a sheet over the page below it, and the bar stays at the window's edge like the body.

    Mutation: take the offset away; make it apply below 768px; make it apply with the sidebar shut; make it too small to clear the sidebar; start it one pixel late; stop the shell moving the body."""
    assert problems(PAGE) == []


def test_at_916px_with_the_sidebar_open_no_part_of_the_bar_is_under_the_sidebar():
    """The walk's own window. The sidebar is 240px; the bar starts at 240px, so its Material and Labor sums, the first of its text, are in view.

    Mutation: take the offset away."""
    assert walk_problems(PAGE) == []


def test_on_a_phone_the_bar_stays_put_because_the_drawer_is_a_sheet_over_the_page():
    """Below 768px the sidebar is a modal sheet with a scrim, and auth.js does not move the body: no state of the sidebar moves the bar.

    Mutation: let the offset apply on a phone too."""
    assert phone_problems(PAGE) == []


def test_the_bar_slides_with_the_page_when_the_sidebar_opens_and_shuts():
    """Mutation: take the bar's transition away; give it another duration."""
    assert slide_problems(PAGE) == []


def test_the_bars_own_rule_keeps_the_z_index_the_sticky_head_test_reads():
    """Mutation: take z-index out of the bar's rule."""
    assert rule_problems(PAGE) == []


def test_the_bar_follows_the_sidebars_width_it_does_not_copy_it(tmp_path):
    """The bar reads `--tw-w` as the shell defines it: make the sidebar 300px wide in a copy of auth.js and the bar, like the body, moves 300px, with nothing changed on the page."""
    frontend = break_source(tmp_path, "auth.js", "--tw-w:240px;}", "--tw-w:300px;}")
    shell = shell_of((frontend / "auth.js").read_text(encoding="utf-8"))
    assert bar_left(PAGE, 916, True, shell) == 300.0 and page_left(916, True, shell) == 300.0
    assert problems(PAGE, shell) == []


def test_a_shell_that_stops_moving_the_body_is_found(tmp_path):
    """The bar is tied to what the shell does to the page, not to a number of its own: in a copy of auth.js whose open sidebar no longer moves the body, the page's bar (which still moves) is found
    to start where the page does not."""
    frontend = break_source(tmp_path, "auth.js", "html.tw-nav-open body{margin-left:var(--tw-w);}", "html.tw-nav-open body{margin-left:0;}")
    shell = shell_of((frontend / "auth.js").read_text(encoding="utf-8"))
    found = problems(PAGE, shell)
    assert found and any(p.startswith("not with the page: at 916px with the sidebar open the page column starts at 0px and the bar at 240px") for p in found), found


# ── the resolver has to be worth believing ───────────────────────────────────────────────────────────────
def test_the_resolver_resolves_the_cascade_and_does_not_just_match_text():
    """Specificity beats source order; a media rule applies only inside its window; lengths are read through var() and calc(). Without this it could be a regex in a costume."""
    toy = ".bar{left:0}\nhtml.tw-nav-open .bar{left:240px}"
    elem = ("div", "x", ("bar",))
    html_on = ("html", "", ("tw-nav-open",))
    assert parse_rules(toy)[1][0] == "html.tw-nav-open .bar"
    rules = parse_rules(toy)
    assert [selector_matches(s, elem, [html_on, BODY]) for s, *_ in rules] == [True, True]
    assert [selector_matches(s, elem, [("html", "", ()), BODY]) for s, *_ in rules] == [True, False]
    assert specificity("html.tw-nav-open .bar") > specificity(".bar")
    # later and heavier wins; reversed in the source, the heavier one still wins
    for css in (toy, "html.tw-nav-open .bar{left:240px}\n.bar{left:0}"):
        got = resolve(parse_rules(css), "left", ("div", "x", ("bar",)), 1000, True)
        assert got == "240px", (css, got)
    # a media rule applies only in its window
    media = parse_rules(".bar{left:0}\n@media (min-width:768px){ html.tw-nav-open .bar{left:var(--w,240px)} }")
    assert resolve(media, "left", ("div", "x", ("bar",)), 767, True) == "0"
    assert resolve(media, "left", ("div", "x", ("bar",)), 768, True) == "var(--w,240px)"
    assert resolve(media, "left", ("div", "x", ("bar",)), 768, False) == "0"
    # lengths
    assert length("var(--w,240px)", {}) == 240 and length("var(--w,240px)", {"--w": "100px"}) == 100
    assert length("calc(var(--w,240px) + 16px)", {}) == 256 and length("calc(10px - 4px)", {}) == 6 and length("0", {}) == 0


def test_the_resolver_refuses_what_it_cannot_read():
    elem = ("div", "x", ("bar",))
    for unreadable in (".bar:hover", ".bar > .x", ".bar[data-x]", "div:not(.y)", "html:has(.x) .bar"):
        with pytest.raises(ValueError):
            selector_matches(unreadable, elem, [("html", "", ()), BODY])
    assert selector_matches(".mw-sw .track::after", elem, [("html", "", ()), BODY]) is False     # a pseudo-element is never the element itself
    with pytest.raises(ValueError):
        media_applies("(max-height:540px)", 800)
    with pytest.raises(ValueError):
        media_applies("(prefers-reduced-motion:reduce)", 800)
    assert media_applies("(max-width:820px),(min-width:2000px)", 800) is True and media_applies("(max-width:820px),(min-width:2000px)", 900) is False
    with pytest.raises(ValueError):
        resolve(parse_rules(".bar:hover{left:3px}"), "left", ("div", "x", ("bar",)), 800, False)
    # a rule about SOME OTHER element is out of the way even when its selector is one this reads badly; a rule that could be this element is refused
    other = parse_rules(".bulk-row > input{padding:1px}\n.tw-nav-item:hover{padding:3px}\n.bar{padding:2px}")
    assert resolve(other, "padding", ("div", "x", ("bar",)), 800, False) == "2px"
    with pytest.raises(ValueError):
        resolve(parse_rules(".foo .bar:hover{padding:1px}"), "padding", ("div", "x", ("bar",)), 800, False)
    with pytest.raises(ValueError):
        resolve(parse_rules(".foo > .bar{padding:1px}"), "padding", ("div", "x", ("bar",)), 800, False)


def test_the_resolver_finds_the_shells_own_numbers_in_authjs():
    """The premises this file stands on, read from the shell and not typed in: the rail is 240px, the body moves from 768px up while the sidebar is open, a phone gets a scrim."""
    assert SHELL[1].get("--tw-w") == "240px"
    assert page_left(767, True) == 0.0 and page_left(768, True) == 240.0 and page_left(1440, False) == 0.0
    assert resolve(SHELL[0], "display", BACKDROP, 375, True) == "block"
    assert resolve(SHELL[0], "display", BACKDROP, 1440, True) == "none"


# ── the check can see the bug: the old rule, and each part of the new one undone, are found ─────────────
OFFSET = "@media (min-width:768px){ html.tw-nav-open .bid{left:var(--tw-w,240px)} }"
SLIDE = "z-index:9;transition:left .2s ease}"
EDGE = ".bid{position:fixed;left:0;right:0;bottom:0;background:var(--card);"
CHECKS = {"problems": problems, "walk": walk_problems, "phone": phone_problems, "slide": slide_problems, "rule": rule_problems}

MUTATIONS = [
    # (what is undone, the page's own text, what stands there instead, the check that must find it, how its first finding starts)
    ("the old bar, with no offset at all", OFFSET, "", "problems",
     "under the sidebar: at 916px with the sidebar open the bar starts at 0px and the sidebar's right edge is at 240px: 240px of the bar lie under it, its text starts at 22px, so 218px of its text are hidden"),
    ("the old bar, at the walk's window", OFFSET, "", "walk", "at 916px with the sidebar open the bar starts at 0px under a 240px sidebar"),
    ("an offset that applies on a phone too", OFFSET, "@media (min-width:0px){ html.tw-nav-open .bid{left:var(--tw-w,240px)} }", "problems", "not with the page"),
    ("an offset that applies on a phone too, as the phone check sees it", OFFSET, "@media (min-width:0px){ html.tw-nav-open .bid{left:var(--tw-w,240px)} }", "phone", "the bar moves at 360px"),
    ("an offset that applies with the sidebar shut", OFFSET, "@media (min-width:768px){ .bid{left:var(--tw-w,240px)} }", "problems", "not with the page"),
    ("an offset that applies with the sidebar shut, as the walk sees it", OFFSET, "@media (min-width:768px){ .bid{left:var(--tw-w,240px)} }", "walk", "at 916px with the sidebar shut the bar starts at 240px"),
    ("an offset the sidebar still covers", OFFSET, "@media (min-width:768px){ html.tw-nav-open .bid{left:calc(var(--tw-w,240px) - 40px)} }", "problems", "under the sidebar"),
    ("an offset that starts one pixel after the shell's breakpoint", OFFSET, "@media (min-width:769px){ html.tw-nav-open .bid{left:var(--tw-w,240px)} }", "problems", "not with the page"),
    ("a bar that starts away from the edge while the sidebar is shut", EDGE, EDGE.replace("left:0", "left:12px"), "problems", "not with the page"),
    ("a bar that snaps instead of sliding", SLIDE, "z-index:9}", "slide", "no slide"),
    ("a bar that slides at another speed", SLIDE, "z-index:9;transition:left .6s ease}", "slide", "the bar slides in .6s ease and the page in .2s ease"),
    ("a z-index moved out of the bar's rule", SLIDE, "transition:left .2s ease}", "rule", "the .bid rule no longer holds z-index:9"),
    ("a bar that is not fixed", EDGE, EDGE.replace("position:fixed", "position:absolute"), "rule", "the bar is not position:fixed"),
]


@pytest.mark.parametrize("what,anchor,undone,check,starts", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_each_part_of_the_rule_is_needed(tmp_path, what, anchor, undone, check, starts):
    """Put the old behaviour back, or one part of the new rule undone, into a COPY of the page; the check must find it and say which kind of fault it is. break_source refuses an anchor that is not on the
    page exactly once, so none of these can pass by applying nowhere."""
    frontend = break_source(tmp_path, "polish-estimate.html", anchor, undone)
    found = CHECKS[check]((frontend / "polish-estimate.html").read_text(encoding="utf-8"))
    assert found, "the %s check did not notice: %s" % (check, what)
    assert found[0].startswith(starts) or any(p.startswith(starts) for p in found), (what, found)
