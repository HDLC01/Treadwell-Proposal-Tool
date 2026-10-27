"""The Items table's column headings stay on screen while the rows scroll (Hanz, 2026-10-27).

"Under Items when we scroll down the materials, divisions, order quantity etc. headers should be
sticky."

A sticky cell sticks inside its NEAREST scroll container, and any overflow other than `visible`
makes one. The Items table sits in `.tw`, which scrolls sideways so the pinned Save column has a
left edge to stick to; overflow-x:auto turns overflow-y to auto as well, so `.tw` is the box the
headings stick in, and it has to be the box that scrolls DOWN. These tests read library.html as
text: the heading rule, the wrapper that scrolls, and that nothing between the two clips.
"""
import pathlib
import re
from html.parser import HTMLParser

PAGE = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "library.html"


def _css() -> str:
    html = PAGE.read_text(encoding="utf-8")
    css = "\n".join(re.findall(r"<style>(.*?)</style>", html, re.S))
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _rules(css: str):
    """(selector, body) for every flat rule, media blocks flattened. Good enough for this page."""
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]


def _decls(body: str) -> dict:
    out = {}
    for part in body.split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out.setdefault(k.strip(), []).append(v.strip())
    return out


def _rule(selector: str) -> dict:
    found = [_decls(b) for s, b in _rules(_css()) if s == selector]
    assert found, "no rule for " + selector
    merged = {}
    for d in found:
        for k, v in d.items():
            merged.setdefault(k, []).extend(v)
    return merged


class _Chain(HTMLParser):
    """The open-element stack at the Items table's first <th>."""

    VOID = {"meta", "link", "img", "br", "input", "hr", "source", "path", "col", "wbr"}

    def __init__(self):
        super().__init__()
        self.stack, self.at_th, self._in_items = [], None, False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.VOID:
            return
        self.stack.append((tag, a.get("id"), (a.get("class") or "").split()))
        if a.get("id") == "pane-items":
            self._in_items = True
        if tag == "th" and self._in_items and self.at_th is None:
            self.at_th = list(self.stack)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def _chain():
    p = _Chain()
    p.feed(PAGE.read_text(encoding="utf-8"))
    assert p.at_th, "no <th> inside #pane-items"
    return p.at_th


def test_the_items_headings_are_sticky_and_opaque():
    """Mutation: drop position:sticky or top:0, make the fill translucent, or drop z-index."""
    r = _rule("#items-scroll thead th")
    assert r.get("position") == ["sticky"], r
    assert r.get("top") == ["0"], r
    # A token, the heading row's own solid colour. rgba() or `transparent` lets rows show through.
    assert r.get("background") == ["var(--surf-low)"], r
    assert "--surf-low:#" in _css().replace(" ", ""), "--surf-low is not a solid hex colour"
    assert r.get("border-bottom") and "var(--line)" in r["border-bottom"][0], r
    # Above every body cell: the pinned Save cell in each row is z-index 1.
    pinned = _rule("td.rowsave")
    assert int(r["z-index"][0]) > int(pinned["z-index"][0]), (r, pinned)
    # The Save heading is pinned both ways and sits over the headings it slides past.
    corner = _rule("#items-scroll thead th.rowsave")
    assert corner.get("left") == ["0"] and int(corner["z-index"][0]) > int(r["z-index"][0]), corner


def test_the_scroller_is_the_items_tables_own_wrapper_and_it_scrolls_down():
    """The table's direct parent is #items-scroll, and that box is held to the screen and scrolls
    both ways - so it is the box the headings stick in and the one the rows scroll in.

    Mutation: drop the id off the wrapper, drop its max-height, or set its overflow to hidden."""
    chain = _chain()
    tags = [t for t, _, _ in chain]
    i = tags.index("table")
    assert "items-table" in chain[i][2], chain[i]
    assert chain[i - 1][1] == "items-scroll", chain[i - 1]
    box = _rule("#items-scroll")
    assert box.get("overflow") == ["auto"], box
    assert box.get("max-height") and all("vh" in v for v in box["max-height"]), box


def test_the_box_leaves_room_for_the_topbar_and_what_sits_under_it():
    """With the page scrolled to its END, the box's top (and the headings on it) must stay below
    the fixed 52px #tw-topbar. The box is 100vh less its budget tall, so the budget has to cover the
    topbar plus everything under the box: the bottom pager (48px), the card's 1px border, the
    .foot note's top margin, up to four 12px lines at 1.55 and its 12px bottom margin, and the
    body's bottom padding. Measured in Chromium 2026-10-28: 226px under the box at 1366 wide,
    245px at 390; at 190 the headings sat 36-55px up under the topbar.

    Mutation: put the budget back to 190px, or raise the body's bottom padding past the slack."""
    def px(value: str) -> float:
        m = re.fullmatch(r"(\d+(?:\.\d+)?)px", value.strip())
        assert m, value
        return float(m.group(1))

    box = _rule("#items-scroll")
    budgets = [int(b) for v in box["max-height"]
               for b in re.findall(r"calc\(100d?vh\s*-\s*(\d+)px\)", v)]
    assert len(budgets) == len(box["max-height"]) == 2, box
    body_pad_bottom = px(_rule("body")["padding"][0].split()[2])
    foot = _rule(".foot")
    under = (48 + 1 + px(foot["margin-top"][0]) + 4 * 12 * 1.55 + 12 + body_pad_bottom)
    for b in budgets:
        assert b >= 52 + under, (b, 52 + under)


def test_nothing_between_the_headings_and_their_scroller_clips():
    """A clipping box between a sticky cell and the scroller becomes the box it sticks in, and
    that box never scrolls - the headings would scroll away with the rows.

    Mutation: give .items-table, thead or tr an overflow rule, or wrap the table in another div."""
    chain = _chain()
    i = next(n for n, (_, id_, _) in enumerate(chain) if id_ == "items-scroll")
    between = chain[i + 1:]
    assert [t for t, _, _ in between] == ["table", "thead", "tr", "th"], between
    names = {"table", "thead", "tr", "th"}
    for _, _, classes in between:
        names.update("." + c for c in classes)
    for sel, body in _rules(_css()):
        if not re.search(r"(^|;|\s)overflow(-[xy])?\s*:", body):
            continue
        for one in sel.split(","):
            last = one.strip().split()[-1] if one.strip() else ""
            parts = re.findall(r"^[a-z]+|\.[\w-]+", last)
            assert not (parts and all(p in names for p in parts)), (
                "an overflow rule lands between the headings and #items-scroll: " + one.strip())
