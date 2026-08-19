"""`hidden` has to actually hide the element.

The `hidden` attribute works through one UA rule — `[hidden] { display: none }` — and its specificity
is the lowest there is. ANY author rule that sets `display` on the same element beats it. So this is
correct code that does nothing:

    .pp-pager { display: flex; }              /* in the page's <style>          */
    nav.hidden = pages < 2;                   /* in the page's JS              */

Found on staging, 2026-08-19, walking the Notification Sending page: the pager read
"Page 1 of 1 · 10 projects" with both arrows greyed out, under a list that fit on one page. The JS was
right — it set `.hidden` — which is exactly why nothing in this suite could see it. A DOM-level
harness asserts `node.hidden === true` and passes; the browser renders the element anyway.

The same walk turned up a second one in projects.html, where projects.js hides the search / month /
sort toolbar on an empty list. calendar.html and followups.html already carried the guard, each with
a comment explaining this trap — so the fix was already known here and two pages had simply been
missed. That is the argument for checking every page rather than the two somebody remembered.

WHAT THE DETECTOR KEYS ON, and why it is not `.hidden =`. The first version of this file looked for
`$("id").hidden =`, which found nineteen ids and neither bug: the real idiom is
`someVariable.hidden = …`, and the pager's markup is built inside a JS string, so it is not in any
.html file at all. The honest signal is the `hidden` ATTRIBUTE in markup — an author writing it is
declaring the element hideable — wherever that markup lives, template literals included.

WHY THIS IS A SOURCE READ. It is a claim about the cascade, which no stubbed DOM reproduces: jsdom
applies no UA stylesheet and these harnesses do not parse CSS at all. Reading the stylesheet is the
closest thing to the browser that does not mean shipping one.
"""
import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
PAGES = sorted(FRONTEND.glob("*.html"))

# display values that leave the element on screen. `none` and `contents` do not.
_ON_SCREEN = re.compile(r"display\s*:\s*(?!none\b|contents\b)([a-z-]+)")
# A BARE `hidden` attribute. `aria-hidden="true"` is a different thing entirely and must not count,
# nor may `data-hidden` or a `hidden` inside some other attribute's value.
_HIDDEN_ATTR = re.compile(r'(?<![-\w])hidden(?=[\s>/"\']|\\?"|$)')


def _rules(css):
    """[(selector, body)] for every rule in a stylesheet, @media blocks flattened away."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"@media[^{]*\{", "", css)          # keep the inner rules, drop the wrapper
    return [(m.group(1), m.group(2)) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)]


def _guarded(css):
    """Classes the page re-asserts display:none for when hidden. "*" = a blanket [hidden] rule."""
    out = set()
    for sel, body in _rules(css):
        if not re.search(r"display\s*:\s*none", body):
            continue
        for one in (s.strip() for s in sel.split(",")):
            m = re.fullmatch(r"\.?([\w-]*)\[hidden\]", one)
            if m:
                out.add(m.group(1) or "*")
    return out


def _on_screen_classes(css):
    """{class: display} for single-class rules that put the element on screen."""
    out = {}
    for sel, body in _rules(css):
        d = _ON_SCREEN.search(body)
        if not d:
            continue
        for one in (s.strip() for s in sel.split(",")):
            m = re.fullmatch(r"\.([\w-]+)", one)
            if m:
                out.setdefault(m.group(1), d.group(1))
    return out


def _hideable(text):
    """[(id_or_'', classes)] for every element in `text` carrying a bare `hidden` attribute.

    Runs over .html AND .js, because markup in this codebase is as likely to live in a template
    literal as in a file — the pager that prompted all this is built in notifications.js."""
    out = []
    for tag in re.finditer(r"<[a-zA-Z][^<>]*>", text):
        t = tag.group(0)
        # Ignore the attribute VALUES when looking for a bare `hidden`, so aria-hidden="true" and
        # title="…hidden…" cannot be mistaken for it.
        bare = re.sub(r'=\s*(\\?"[^"]*\\?"|\'[^\']*\'|[^\s>]+)', "=X", t)
        if not _HIDDEN_ATTR.search(bare):
            continue
        c = re.search(r'class=\\?"([^"]*)', t)
        i = re.search(r'id=\\?"([\w-]+)', t)
        if c:
            out.append((i.group(1) if i else "", c.group(1).split()))
    return out


def _scripts_of(page_text):
    """The js/*.js files a page loads, so JS-built markup is checked against THIS page's CSS."""
    return [FRONTEND / s for s in re.findall(r'src="(js/[\w.-]+\.js)"', page_text)]


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_everything_marked_hidden_can_actually_be_hidden(page):
    text = page.read_text(encoding="utf-8", errors="replace")
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", text, re.S))
    if not css.strip():
        pytest.skip("no author CSS on this page")
    guarded = _guarded(css)
    if "*" in guarded:
        return                              # a blanket [hidden]{display:none} covers the page
    on_screen = _on_screen_classes(css)

    candidates = [("markup", e) for e in _hideable(text)]
    for js in _scripts_of(text):
        if js.exists():
            candidates += [(js.name, e) for e in _hideable(js.read_text(encoding="utf-8",
                                                                       errors="replace"))]

    broken = []
    for where, (el_id, classes) in candidates:
        for cls in classes:
            if cls in on_screen and cls not in guarded:
                broken.append((where, el_id or "(no id)", cls, on_screen[cls]))

    seen, uniq = set(), []
    for b in broken:
        if b[1:] not in seen:
            seen.add(b[1:])
            uniq.append(b)

    assert not uniq, "%s:\n%s" % (page.name, "\n".join(
        '  #%s ships `hidden` and carries .%s (display:%s, from %s) — a class rule beats the UA '
        '`[hidden]` rule, so hiding it does nothing. Add `.%s[hidden] { display:none; }`.'
        % (i, c, d, w, c) for w, i, c, d in uniq))


def test_the_pager_and_the_toolbar_stay_fixed():
    """The two the walk actually found, named individually so a rename cannot leave the scan above
    satisfied while the bug returns under a new class."""
    notif = (FRONTEND / "notifications.html").read_text(encoding="utf-8")
    assert re.search(r"\.pp-pager\[hidden\]\s*\{[^}]*display\s*:\s*none", notif), (
        "the Notification Sending pager can render at 'Page 1 of 1' again")
    projects = (FRONTEND / "projects.html").read_text(encoding="utf-8")
    assert re.search(r"\.toolbar\[hidden\]\s*\{[^}]*display\s*:\s*none", projects), (
        "the Proposals Database toolbar shows on an empty list again")


def test_the_scan_is_actually_looking_at_something():
    """A detector that silently matches nothing is worse than no test. The first version of this file
    found nineteen ids and neither real bug; these floors are what would have said so."""
    assert PAGES, "no pages found to scan"
    total = 0
    for page in PAGES:
        text = page.read_text(encoding="utf-8", errors="replace")
        total += len(_hideable(text))
        for js in _scripts_of(text):
            if js.exists():
                total += len(_hideable(js.read_text(encoding="utf-8", errors="replace")))
    assert total >= 30, (
        "only %d hideable elements found across %d pages — the `hidden` attribute pattern has "
        "stopped matching how this codebase declares things hideable" % (total, len(PAGES)))
    # And the CSS side is really being read, or every page would pass by finding no display rules.
    notif = (FRONTEND / "notifications.html").read_text(encoding="utf-8")
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", notif, re.S))
    assert "pp-pager" in _on_screen_classes(css), (
        "the stylesheet parser no longer sees .pp-pager's display, so this page passes vacuously")
    assert "pp-pager" in _guarded(css)
