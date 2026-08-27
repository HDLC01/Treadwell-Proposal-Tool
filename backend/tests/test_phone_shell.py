"""The shut drawer must be unable to take a tap, and a phone must never inherit a desktop's rail.

Hanz, 2026-08-27: "Sidebar makes every page unusable at phone width."

WHAT WAS ACTUALLY BROKEN, because the drawer was not missing. `#tw-sidebar` already had
`transform: translateX(-100%)`, a burger, a scrim and a `@media (max-width:767px)` block; all of it
worked. What decided the starting state was this line:

    setOpen(persisted !== null ? persisted === "1" : wide);

`tw_nav_open` was restored at ANY width and the desktop default is open, so one visit on a laptop
wrote "1" and every later phone visit inherited it. Measured on staging at 375px: the 240px rail
covered 64% of the screen, `documentElement.scrollWidth` read 931 against a clientWidth of 375, and
clicking the Items tab timed out with the drawer's own `<a class="tw-nav-item" href="/calendar.html">`
reported as the element intercepting pointer events.

WHY THIS FILE RESOLVES THE CASCADE INSTEAD OF GREPPING. This is the third time this repo has shipped
an element that looked hidden and was not: a class `display` rule beating the `hidden` attribute
(test_hidden_is_actually_hidden.py), `opacity: 0` still taking clicks, and the chat tab whose tint
was written with an id so it outweighed every state class (test_chat_tab_cascade.py). Every one of
those passed a source-text assertion. So the checks below build the declarations that actually apply
to `#tw-sidebar` at a given viewport width and open/shut state, order them by (important,
specificity, source position) the way a browser does, and read the WINNER. A regex for
"visibility:hidden" would still pass if a later rule with more weight put it back.

The resolver refuses to skip a rule it does not understand (test_the_resolver_is_not_quietly_blind).
A detector that silently matches nothing is worse than no detector, and the first version of the
`hidden` scan in this repo found nineteen ids and neither real bug.
"""

import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
AUTH = FRONTEND / "auth.js"

SIDEBAR = "tw-sidebar"
BACKDROP = "tw-backdrop"
OPEN_CLASS = "tw-nav-open"
# Widths this pass supports. 360 is the narrowest common phone still in service (Galaxy S8/S9,
# Pixel 4a); 375 is every iPhone from the SE 2 up; 767 is the last pixel before the desktop rail.
PHONE_WIDTHS = (360, 375, 414, 767)

# Where each piece of chrome really sits, as (ancestor id, ancestor classes) pairs. The resolver
# needs a COMPLETE ancestor description to answer a descendant selector exactly rather than guess:
# `.tw-nav-item.active .tw-nav-ico` must not be read as a rule about the nav item itself.
IN_DRAWER = (("tw-sidebar", ()),)
IN_NAV = (("", ("tw-nav",)),) + IN_DRAWER
IN_BRAND = (("", ("tw-brand",)),) + IN_DRAWER
IN_USER = (("", ("tw-user",)),) + IN_DRAWER
# The bell lives in the fixed top bar on the board pages and folded into the wizard header on the
# rest; both, because one rule has to cover the pages it appears on.
IN_HEADER = (("tw-topbar", ()), ("", ("tw-hdr-right",)))


# ── the stylesheet auth.js injects ────────────────────────────────────────────────────────────
def sidebar_css(src=None):
    """The one long template literal inside injectSidebarStyles.

    Read out of auth.js rather than from a .css file because this stylesheet has no file: it is
    built in JS and injected on every page, which is exactly what makes it the only place a rule
    can reach all twenty-two pages. (Note for anyone editing it: no backticks in its comments —
    one ends the literal and takes the whole file, and the bearer token with it.)
    """
    src = src if src is not None else AUTH.read_text(encoding="utf-8")
    start = src.index("const css = `")
    end = src.index("`;", start + 13)
    return src[start + 13:end]


def _strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def rules(css):
    """[(selector, declarations, media_condition, order)] with @media conditions KEPT.

    Flattening @media away — which the older scans in this repo do, deliberately, for their own
    question — would make every assertion here meaningless: the whole point is which rule applies at
    375px and which at 1440px. `#tw-backdrop { display: none !important }` lives inside
    `@media (min-width:768px)`, so a parser that loses the condition reports the scrim as
    permanently gone and every check about it passes for the wrong reason.
    """
    css = _strip_comments(css)
    out, order, stack, buf, i, n = [], 0, [], "", 0, len(css)
    while i < n:
        ch = css[i]
        if ch == "{":
            head, buf = buf.strip(), ""
            if head.startswith("@media"):
                stack.append(head[len("@media"):].strip())
                i += 1
                continue
            if head.startswith("@"):
                i = _matching_brace(css, i) + 1        # @keyframes, @supports: skip the body whole
                continue
            close = css.find("}", i)
            assert close != -1, "unbalanced braces after %r" % head[:60]
            if head:
                out.append((head, css[i + 1:close], " and ".join(stack), order))
                order += 1
            i = close + 1
            continue
        if ch == "}":
            # Only ever a media block's closing brace: a declaration block's was consumed above.
            if stack:
                stack.pop()
            buf, i = "", i + 1
            continue
        buf += ch
        i += 1
    return out


def _matching_brace(css, open_at):
    depth = 0
    for j in range(open_at, len(css)):
        if css[j] == "{":
            depth += 1
        elif css[j] == "}":
            depth -= 1
            if depth == 0:
                return j
    raise AssertionError("unbalanced braces in the stylesheet")


# ── does this rule apply, and how much does it weigh ──────────────────────────────────────────
_WIDTH = re.compile(r"\((min|max)-width\s*:\s*(\d+)px\)")


def media_applies(cond, width):
    """True/False for a width query; None for a condition this resolver cannot evaluate."""
    if not cond.strip():
        return True
    parts = [p.strip() for p in cond.replace("and", "&").split("&") if p.strip()]
    verdict = True
    for p in parts:
        m = _WIDTH.fullmatch(p)
        if not m:
            return None
        n = int(m.group(2))
        verdict = verdict and (width >= n if m.group(1) == "min" else width <= n)
    return verdict


def phone_only(cond):
    """True only for a condition that provably applies at 375px and provably does not at 1440px.

    `not media_applies(cond, 1440)` on its own would call a `prefers-reduced-motion` block
    phone-only, because an unevaluable condition comes back None and `not None` is True.
    """
    return media_applies(cond, 375) is True and media_applies(cond, 1440) is False


def specificity(sel):
    ids = len(re.findall(r"#[\w-]+", sel))
    classes = len(re.findall(r"\.[\w-]+|\[[^\]]+\]|:[\w-]+(?!\()", sel))
    types = len(re.findall(r"(?:^|[\s>+~])([a-z][\w-]*)", sel))
    return (ids, classes, types)


_COMPOUND = re.compile(r"([#.]?)([\w-]+)|(:[\w-]+)|(\*)")


def _compound_matches(one, el_id, el_classes):
    """Does one COMPOUND simple selector (`#id.class:hover`, `.a.b`, `div`) match the element?

    A COMPOUND, not a single token, and that is the whole point of this function existing. The
    first version compared `one == "#" + el_id`, so `#tw-burger.tw-burger-inline` — the 34px in-row
    burger, the exact rule a phone rule written as `#tw-burger` alone is outweighed by — matched
    nothing and became invisible to the resolver. The mutation that reverted the phone rule to the
    losing form therefore survived. Comparing a compound to a bare id is the same class of mistake
    as comparing selectors by source order.
    """
    if ":" in one and not one.startswith(":"):
        one = one[:one.index(":")]            # a state pseudo-class; the element can be in it
    ids, classes, types = [], [], []
    pos = 0
    for m in _COMPOUND.finditer(one):
        if m.start() != pos:
            raise ValueError(one)              # something between tokens this parser cannot read
        pos = m.end()
        if m.group(4):
            continue                           # `*`
        if m.group(3):
            continue                           # a pseudo-class, handled above
        (ids if m.group(1) == "#" else classes if m.group(1) == "." else types).append(m.group(2))
    if pos != len(one):
        raise ValueError(one)
    if len(ids) > 1:
        raise ValueError(one)
    if ids and ids[0] != el_id:
        return False
    if any(c not in el_classes for c in classes):
        return False
    if types:
        return False                           # no rule in these stylesheets types the drawer
    return bool(ids or classes)


def _selector_matches(sel, el_id, el_classes, root_open, ancestors=()):
    """Match one descendant selector against the element, or raise if it cannot be PARSED.

    `ancestors` is a COMPLETE description of the ids and classes on the element's ancestors, so a
    descendant selector is answered exactly rather than guessed at or refused. That completeness is
    the contract: a compound naming something not in the set genuinely does not match. The earlier
    version raised on any descendant selector whose last compound matched, which is honest but
    useless - `.fb-head .shell-x` sets no size and still stopped the resolver dead.
    """
    sel = sel.strip()
    if any(c in sel for c in ">+~") or "::" in sel:
        raise ValueError(sel)
    parts = sel.split()
    if not parts:
        raise ValueError(sel)
    if parts[0].startswith("html"):
        rest = parts[0][len("html"):]
        if rest and rest != "." + OPEN_CLASS:
            raise ValueError(sel)
        if rest and not root_open:
            return False
        parts = parts[1:]
        if not parts:
            return False                        # a rule about <html> itself, not this element
    if not parts:
        return False
    if not _compound_matches(parts[-1], el_id, el_classes):
        # Parse the ancestor compounds anyway, so an unreadable one is still reported.
        for p in parts[:-1]:
            _compound_matches(p, "", ())
        return False
    for p in parts[:-1]:
        if not any(_compound_matches(p, a_id, a_cls) for a_id, a_cls in ancestors):
            return False
    return True


def resolve(css, prop, el_id, width, root_open, el_classes=(), ancestors=()):
    """The declaration a browser would use for `prop` on this element, or None.

    (important, specificity, source order) — the real order of the cascade among author rules,
    which is the ordering that catches an id quietly outweighing a class.
    """
    winner, best = None, None
    for sel, body, cond, order in rules(css):
        applies = media_applies(cond, width)
        assert applies is not None, (
            "the resolver cannot evaluate `@media %s`, so it would silently ignore every rule "
            "inside it. Teach media_applies() this condition or move the drawer's rules out of it."
            % cond)
        if not applies:
            continue
        for one in (s.strip() for s in sel.split(",")):
            if not _selector_matches(one, el_id, el_classes, root_open, ancestors):
                continue
            for decl in body.split(";"):
                if ":" not in decl:
                    continue
                name, _, value = decl.partition(":")
                if name.strip() != prop:
                    continue
                important = "!important" in value
                key = (important, specificity(one), order)
                if best is None or key > best:
                    best, winner = key, value.replace("!important", "").strip()
    return winner


# ── the assertions ────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("width", PHONE_WIDTHS + (1024, 1440))
def test_a_shut_drawer_cannot_be_the_click_target(width):
    """The bug, stated as the property that makes it impossible.

    `visibility: hidden` takes the whole subtree out of hit-testing AND out of the tab order;
    `pointer-events: none` says the first half again in a property that reads plainly. Either alone
    would do for the pointer, but the pair is what stops a keyboard reaching thirteen links nobody
    can see, so both are required and both are resolved through the cascade rather than matched.

    Checked at desktop widths too: the drawer is shut there whenever the estimator has collapsed it,
    and a rail that is merely translated off-screen still holds the tab order.
    """
    css = sidebar_css()
    vis = resolve(css, "visibility", SIDEBAR, width, root_open=False)
    pe = resolve(css, "pointer-events", SIDEBAR, width, root_open=False)
    assert vis == "hidden", (
        "at %dpx a SHUT #%s resolves visibility:%s. Off-screen is not inert: transform animates, so "
        "mid-slide the rail is over the page, and its links stay in the tab order the whole time."
        % (width, SIDEBAR, vis))
    assert pe == "none", (
        "at %dpx a SHUT #%s resolves pointer-events:%s, so it can still take a tap meant for the "
        "page underneath — the staging failure exactly." % (width, SIDEBAR, pe))


@pytest.mark.parametrize("width", PHONE_WIDTHS + (1024, 1440))
def test_an_open_drawer_is_visible_and_clickable_again(width):
    """The other half. A test that only asserts the shut state passes on a drawer that never opens."""
    css = sidebar_css()
    assert resolve(css, "visibility", SIDEBAR, width, root_open=True) == "visible"
    assert resolve(css, "pointer-events", SIDEBAR, width, root_open=True) == "auto"
    assert resolve(css, "transform", SIDEBAR, width, root_open=True) == "translateX(0)"


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_shut_scrim_is_the_other_half_of_the_guarantee(width):
    """A full-viewport scrim is the one element that can eat every tap on the page by itself.

    `display:none` was already there. `pointer-events:none` is added because display is the property
    most likely to be put back by something else — that is the whole content of
    test_hidden_is_actually_hidden.py — and the scrim has no business taking a click in either state
    it is not visible in.
    """
    css = sidebar_css()
    assert resolve(css, "display", BACKDROP, width, root_open=False) == "none"
    assert resolve(css, "pointer-events", BACKDROP, width, root_open=False) == "none"
    # And it is a real scrim when the drawer is open on a phone, or tapping away does nothing.
    assert resolve(css, "display", BACKDROP, width, root_open=True) == "block"
    assert resolve(css, "pointer-events", BACKDROP, width, root_open=True) == "auto"


def test_the_desktop_rail_is_not_a_scrim():
    """At >=768px the drawer sits BESIDE the page (body gets margin-left), so a scrim there would
    dim and block a page the user is still working in."""
    css = sidebar_css()
    assert resolve(css, "display", BACKDROP, 1440, root_open=True) == "none"


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_chrome_is_reachable_with_a_thumb(width):
    """44px is Apple's floor and 48 is Material's. A menu row is a full-width target either way, so
    it takes the larger; the lone glyphs take 44.

    The 40x40 burger and the ~28x30 bell were the two an estimator actually misses, and both were
    under the floor at every width. The DESKTOP sizes are deliberately untouched: a mouse does not
    need this and the 240px rail has no room for it.
    """
    css = sidebar_css()

    def px(prop, el_id="", classes=(), anc=()):
        v = resolve(css, prop, el_id, width, root_open=True, el_classes=classes, ancestors=anc)
        return float(re.sub(r"[^\d.]", "", v)) if v and v.endswith("px") else None

    row = px("min-height", classes=("tw-nav-item",), anc=IN_NAV)
    assert row and row >= 48, "a menu row resolves min-height %s at %dpx" % (row, width)
    burger = px("height", el_id="tw-burger")
    assert burger and burger >= 44, "#tw-burger resolves height %s at %dpx" % (burger, width)
    assert px("width", el_id="tw-burger") >= 44
    for cls, anc in (("tw-bell", IN_HEADER), ("tw-collapse", IN_BRAND), ("tw-signout", IN_USER)):
        h = px("min-height", classes=(cls,), anc=anc)
        assert h and h >= 44, ".%s resolves min-height %s at %dpx" % (cls, h, width)

    # The in-row burger on the wizard pages is a SECOND rule at (1,1,0); a phone rule written only
    # as `#tw-burger` (1,0,0) would lose to it and leave those five pages at 34px.
    inline = resolve(css, "height", "tw-burger", width, root_open=True,
                     el_classes=("tw-burger-inline",), ancestors=IN_HEADER)
    assert inline and float(re.sub(r"[^\d.]", "", inline)) >= 44, (
        "the in-row burger on the wizard pages resolves height %s at %dpx — the phone rule has to "
        "name .tw-burger-inline too, or it is outweighed" % (inline, width))


def test_the_sheet_leaves_a_strip_of_the_page_showing():
    """It is a modal sheet on a phone, not a rail, and it has to read as one.

    240px of 375 truncates the long labels ("Notification Sending", "Items and Assemblies") on the
    one screen where the label is all there is, so the phone width goes UP, not down — but bounded,
    or a full-bleed drawer reads as having navigated somewhere.
    """
    css = sidebar_css()
    for width in PHONE_WIDTHS:
        v = resolve(css, "width", SIDEBAR, width, root_open=True)
        assert v and v.startswith("min("), (
            "#%s resolves width %r at %dpx; a phone sheet needs a bounded fluid width" % (
                SIDEBAR, v, width))


# ── the JS half: who decides the starting state ───────────────────────────────────────────────
def _render_sidebar_body(src=None):
    src = src if src is not None else AUTH.read_text(encoding="utf-8")
    i = src.index("function renderSidebar(")
    j = src.index("\n  // ── A page this account may not open ──", i)
    return src[i:j]


def test_the_remembered_flag_is_never_read_or_written_at_phone_width():
    """The actual defect, banned by shape rather than by the one line it appeared on.

    Any `localStorage.setItem("tw_nav_open", ...)` that is not inside a width guard puts the bug
    back: a phone toggle writes the flag, and the next desktop visit — or the next phone visit —
    reads it. Likewise the restore.
    """
    body = _render_sidebar_body()
    writes = [m for m in re.finditer(r'localStorage\.setItem\(\s*"tw_nav_open"', body)]
    assert writes, "nothing writes tw_nav_open any more, so this test grades nothing"
    for m in writes:
        line = body[body.rfind("\n", 0, m.start()) + 1:body.find("\n", m.start())]
        assert re.search(r"if\s*\(\s*wide\(\)\s*\)", line), (
            "tw_nav_open is written outside a wide() guard:\n  %s\nA phone toggle that persists is "
            "how a desktop rail ended up across a 375px screen." % line.strip())

    restore = re.search(r"setOpen\(([^;]*?)\);", body)
    assert restore, "renderSidebar no longer sets an initial state"
    assert "wide()" in restore.group(1), (
        "the initial state is decided without asking the width: setOpen(%s). That is the staging "
        "bug verbatim — the flag defaults to open on a desktop and was restored on a phone."
        % restore.group(1).strip())


def test_the_width_is_asked_every_time_not_once_at_sign_in():
    """`const wide = window.matchMedia(...).matches` answers for whichever the page was when the
    sidebar was built. The same page is a phone in portrait and a small tablet in landscape, and the
    drawer has to shut when it crosses down — which needs a live query and a change listener."""
    body = _render_sidebar_body()
    assert re.search(r"const wide = \(\) =>", body), (
        "wide is a one-shot boolean again, so a rotate leaves a desktop rail across a phone")
    assert re.search(r"mql\.(addEventListener|addListener)", body), (
        "nothing listens for the viewport crossing 768px, so a resize cannot shut the drawer")
    assert re.search(r"if \(!wide\(\)\) setOpen\(false\)", body), (
        "the width listener does not shut the drawer on the way down")


def test_the_drawer_is_escapable_and_gives_the_focus_back():
    """Open, close, tap-away and Escape all have to work, and the caret must not be left inside a
    subtree the CSS has just made invisible.

    Escape is gated on !wide() on purpose: at desktop the drawer is a rail beside the page, and
    closing it on Escape would fight every dialog and every Escape-to-cancel behind it.
    """
    body = _render_sidebar_body()
    esc = re.search(r'e\.key === "Escape"[^\n]*', body)
    assert esc, "Escape does not close the drawer"
    assert "!wide()" in esc.group(0), (
        "Escape closes the desktop rail too, which fights the dialogs on the page behind it: %s"
        % esc.group(0).strip())
    assert "burger.focus()" in body, "focus is never returned to the burger when the drawer closes"
    assert "collapse.focus()" in body, "focus never enters the drawer when it opens"
    assert re.search(r'burger\.setAttribute\("aria-expanded"', body) or \
        re.search(r'setAttribute\("aria-expanded", open', body), (
            "the burger never says whether the drawer is open")
    assert re.search(r'aria-hidden", open \? "false" : "true"', body), (
        "the assistive tree does not follow the cascade, so a screen reader still walks a menu the "
        "CSS has made inert")


# ── the two pages that really did scroll the body sideways ────────────────────────────────────
@pytest.mark.parametrize("page,selector,why", [
    ("analytics.html", r"\.tabs", "five tabs measured 486px against a 375px viewport"),
    ("calendar.html", r"\.top", "bison + a 29px title + three view links measured 457px"),
])
def test_the_two_rows_that_overflowed_the_body_now_wrap(page, selector, why):
    """Measured in Brave at 375px before the change: analytics scrollWidth 486, calendar 457.

    Both were a flex row with no flex-wrap, and flex does not wrap by default — so the tabs and the
    Pipeline/Analytics links simply ran off the right edge, which for a link means it is not there.
    Every other page's wide content (six tables, the board, the notification matrix) already had its
    own overflow-x box and measured clean.
    """
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>",
                               (FRONTEND / page).read_text(encoding="utf-8"), re.S))
    phone = [(s, b) for s, b, cond, _ in rules(css) if phone_only(cond)]
    assert phone, "%s has no phone-only rules at all" % page
    hit = [b for s, b in phone if re.fullmatch(selector, s.strip())]
    assert hit and any("flex-wrap" in b and "wrap" in b for b in hit), (
        "%s: %s has no phone-width flex-wrap. %s" % (page, selector, why))


def test_wide_content_keeps_its_swipe_out_of_the_browsers_back_gesture():
    """Every scroll box in this app already had overflow-x:auto; what it lacked is the second half.

    A swipe that runs off the end of a table used to hand the gesture to the browser's back
    navigation, which on the Bid Pipeline means losing the board rather than reaching the last
    column. This is one shared rule in the injected stylesheet because there is no other stylesheet
    every page loads — only five of the twenty-two link /styles.css.
    """
    css = sidebar_css()
    contained = {one.strip() for sel, b, cond, _ in rules(css)
                 if phone_only(cond) and "overscroll-behavior-x" in b
                 for one in sel.split(",")}
    for box in (".tablewrap", ".board", ".mx-scroll", ".t12-wrap", ".boardwrap"):
        assert box in contained, (
            "%s can still pass a horizontal swipe to the browser's back gesture" % box)


def test_the_board_gives_a_phone_one_pipeline_column_at_a_time():
    """WHICH COLUMN A JOB SITS IN IS THE INFORMATION on this page, so the columns stay.

    The obvious way to fit a five-column kanban board on 375px is to flatten it into one list of
    cards, and that throws away the only thing the board says which the Proposals Database does not.
    The columns stay and the phone gets one at a time, snapped, at 86% — which leaves the next
    stage's edge showing, and that sliver is the affordance the horizontal scrollbar used to be
    before touch hid it.

    Not applied to .board.as-table: the Table view is one wide table and snapping its columns to the
    viewport would fight reading a row across.
    """
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>",
                               (FRONTEND / "portal.html").read_text(encoding="utf-8"), re.S))
    phone = [(s.strip(), b) for s, b, cond, _ in rules(css) if phone_only(cond)]
    snap = [b for s, b in phone if s.startswith(".board") and "scroll-snap-type" in b]
    assert snap, "the board does not snap at phone width, so a swipe lands between two stages"
    assert all(":not(.as-table)" in s for s, b in phone
               if s.startswith(".board") and "scroll-snap-type" in b), (
        "the snap also applies to the Table view, where it fights reading a row across")
    col = [b for s, b in phone if ".col" in s and "scroll-snap-align" in b]
    assert col, "the columns do not declare a snap position"
    assert any(re.search(r"flex:\s*0 0 \d+%", b) for b in col), (
        "the columns keep a fixed pixel width on a phone, so nothing tells the rep the board "
        "continues past the right edge")


# ── the resolver has to be worth believing ────────────────────────────────────────────────────
def test_the_resolver_is_not_quietly_blind():
    """Every selector and every @media in this stylesheet is understood, or the checks above are
    grading a subset and cannot say which.

    This is the assertion the first `hidden` scan in this repo was missing: it found nineteen ids,
    neither real bug, and reported success.
    """
    css = sidebar_css()
    all_rules = rules(css)
    assert len(all_rules) > 40, "only %d rules parsed out of the injected stylesheet" % len(all_rules)
    unknown_media, unknown_sel = set(), set()
    for sel, _body, cond, _order in all_rules:
        if media_applies(cond, 375) is None:
            unknown_media.add(cond)
        for one in (s.strip() for s in sel.split(",")):
            try:
                _selector_matches(one, SIDEBAR, ("tw-nav-item",), True, IN_NAV)
            except ValueError:
                unknown_sel.add(one)
    assert not unknown_media, "unevaluable @media conditions: %r" % sorted(unknown_media)
    assert not unknown_sel, (
        "selectors this resolver would silently ignore: %r. Every one of them could carry a "
        "visibility or pointer-events declaration for the drawer." % sorted(unknown_sel))

    # AND THE REFUSAL REALLY FIRES. The clean run above is also what a resolver that answers False
    # to everything it cannot read would produce, so the shapes it must refuse are named here. A
    # mutation turning either raise into `return False` survives every other check in this file:
    # nothing in today's stylesheet uses these shapes, which is exactly why the guard has to be
    # tested directly rather than inferred from the scan.
    for unreadable in ("#tw-sidebar[data-x]", "#a > #b", "#tw-sidebar::after", "#a#b",
                       "#tw-sidebar%bad", "#tw-sidebar["):
        with pytest.raises(ValueError):
            _selector_matches(unreadable, SIDEBAR, ("tw-nav-item",), True, IN_NAV)


def test_the_resolver_really_does_resolve_rather_than_match():
    """A live proof, on this stylesheet, that a later heavier rule beats an earlier one.

    Without this the resolver could be a dressed-up regex and every assertion above would still
    pass. `#tw-sidebar` at (1,0,0) sets visibility:hidden; `html.tw-nav-open #tw-sidebar` at (1,1,0)
    sets visible. Reading the same property in both states and getting two answers is the whole
    mechanism under test.
    """
    css = sidebar_css()
    assert resolve(css, "visibility", SIDEBAR, 375, root_open=False) == "hidden"
    assert resolve(css, "visibility", SIDEBAR, 375, root_open=True) == "visible"
    # And weight really is beating source order, not the other way round: the hidden declaration is
    # written FIRST in the file, so a resolver that only took the last match would answer "hidden"
    # in both states.
    src = sidebar_css()
    assert src.index("visibility:hidden") < src.index("visibility:visible")
    # A synthetic pair, so the ordering rule is exercised rather than inferred from one real case.
    toy = "#tw-sidebar{pointer-events:none;}\nhtml.tw-nav-open #tw-sidebar{pointer-events:auto;}"
    assert resolve(toy, "pointer-events", SIDEBAR, 375, root_open=False) == "none"
    assert resolve(toy, "pointer-events", SIDEBAR, 375, root_open=True) == "auto"
    reversed_order = ("html.tw-nav-open #tw-sidebar{pointer-events:auto;}\n"
                      "#tw-sidebar{pointer-events:none;}")
    assert resolve(reversed_order, "pointer-events", SIDEBAR, 375, root_open=True) == "auto", (
        "source order is beating specificity, which is not how the cascade works and is exactly the "
        "mistake test_chat_tab_cascade.py exists to record")
