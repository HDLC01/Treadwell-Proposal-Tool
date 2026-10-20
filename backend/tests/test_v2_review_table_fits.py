"""THE REVIEW'S TABLES HOLD WHAT THEY HOLD AT EVERY WIDTH THEY CAN HAVE (the 2026-10-20 fifth audit, finding H): nothing is cut off at 900 to 1000px.

At about 916px the Review's markup card cut off the Discount $ box, the Contingency and Fees boxes and the "margin on cost" / "of subtotal + markups" words beside them. The card's table
is `table-layout: fixed`, so its columns are whatever the header row says, and they said 20% / 12% / 19% / 14% of a table that is 592px wide when the sidebar is open at that
window width (916 less the 240px sidebar, the page's side padding and the card's own padding), or 815px when it is not: the Total column was 83px or 114px wide, and the 104px box in it
(plus the cell's own 12px either side) needs 128px; the Unit column was 71px or 98px and its words, which could not wrap, need 151px. The boxes ran past the column and the card's edge.

The fix (polish-estimate.html's CSS): Unit, Rate and Total are PIXELS, each as wide as the markup card needs them, Quantity is a share of the table, the Unit words may wrap, and the table keeps
a minimum width (640px) below which it scrolls INSIDE its own box (the `.tscroll` the page already has), as it does on a phone. Nothing here needs a browser to be checked: the layout of a fixed-width
table is arithmetic on the page's own CSS. The widths a column NEEDS were measured in a browser on the real Review (Chrome through Playwright, 2026-10-20, 916px with and without the sidebar,
and every width from 560 to 1000px: no cell of any of the five cards overflowed, and the table scrolled inside its box below 640px); they are the constants below, and every one that can be
read off the CSS (the boxes' widths, the cell padding) IS read off it, so a box made wider without a column made wider goes red.

The last block puts the old rules (and each new rule one at a time) back into a COPY of the page and requires the check to find the problem: a check that has never failed proves nothing.
"""
from __future__ import annotations

import re

import pytest

from _golden_support import FRONTEND, break_source

PAGE_PATH = FRONTEND / "polish-estimate.html"
AUTH_PATH = FRONTEND / "auth.js"

# What the cells hold, in pixels, measured on the real Review in a browser (see the docstring). The cell padding and the boxes' own widths are read off the CSS instead.
DOLLAR_AND_GAP = 12          # the "$" before the Discount dollar box, and the gap after it
PERCENT_AND_GAP = 16         # the "%" after a rate box, and the gap before it
LONGEST_UNIT_TEXT = 127      # "of subtotal + markups" at 13px: what a Unit cell needs if its words cannot wrap
LONGEST_UNIT_WORD = 70       # "escalation", the longest word a Unit cell holds: what it needs if they can
QUANTITY_HEADER = 62         # "QUANTITY" at 10.5px with its letter-spacing, before the header's own padding
ITEM_MIN = 150               # the Item column wraps; below this a label of two words stands on a line of its own


def _css(page: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"/\*.*?\*/", "", page, flags=re.S))


def _rule(css: str, selector: str) -> str:
    """The declarations of EVERY rule whose selector list is exactly `selector`, in the order the page has them (a later rule wins, as in the cascade)."""
    found = re.findall(r"(?:^|[}\s])" + re.escape(selector) + r" ?\{([^}]*)\}", css)
    assert found, "the page has no rule for %r" % selector
    return ";".join(found)


def _px(declarations: str, prop: str) -> int:
    found = re.findall(r"(?:^|[;\s])" + re.escape(prop) + r":\s*(\d+)px", declarations)
    assert found, "no %s in %r" % (prop, declarations)
    return int(found[-1])


def _column(css: str, n: int):
    """('%', 15) or ('px', 124): the width the header row gives column `n` of every Review table."""
    decl = _rule(css, ".rev-t th:nth-child(%d),.mk th:nth-child(%d)" % (n, n))
    found = re.findall(r"width:\s*(\d+)(%|px)", decl)
    assert found, "column %d has no width: %r" % (n, decl)
    return found[-1][1], int(found[-1][0])


def problems(page: str, sidebar: int = 240) -> list[str]:
    """What is cut off, as a list of sentences, for every table width the page can give the Review at a window 900 to 1000px wide (the sidebar open or shut) and below."""
    css = _css(page)
    min_width = _px(_rule(css, ".rev-t,.mk"), "min-width")   # two rules name both tables together: the minimum width, and table-layout
    pad = int(re.search(r"padding:\s*\d+px (\d+)px", _rule(css, ".mk td")).group(1))
    mk_box = _px(_rule(css, ".mk input"), "width")
    pct_box = _px(_rule(css, ".adjbox input,.mk .adjbox input"), "width")
    amt_box = _px(_rule(css, ".adjbox.adjamt input,.mk .adjbox.adjamt input"), "width")
    unit_wraps = _rule(css, ".rev-t td.u,.mk td.u").replace(" ", "").split("white-space:")[-1].startswith("normal")
    needs = {
        2: QUANTITY_HEADER + 2 * int(re.search(r"padding:\s*\d+px (\d+)px", _rule(css, ".rev-t th,.mk th")).group(1)),
        3: (LONGEST_UNIT_WORD if unit_wraps else LONGEST_UNIT_TEXT) + 2 * pad,
        4: pct_box + PERCENT_AND_GAP + 2 * pad,
        5: max(mk_box, amt_box + DOLLAR_AND_GAP) + 2 * pad,
    }
    names = {2: "Quantity", 3: "Unit", 4: "Rate", 5: "Total"}
    # The table's room: the window, less the page's side padding (22px a side), the card's border and padding (1px + 19px a side), and the sidebar when it is open.
    body_pad = int(re.search(r"body\{[^}]*padding:\s*0 (\d+)px", css).group(1)) * 2
    card = 2 + 2 * int(re.search(r"\.sec-b\{padding:\s*\d+px (\d+)px", css).group(1))
    problems_found: list[str] = []
    for window in range(900, 1001, 4):
        for open_ in (False, True):
            room = window - body_pad - card - (sidebar if open_ else 0)
            table = max(min_width, room)      # below the minimum the table scrolls inside its box, at its minimum width
            widths = {}
            for n in (2, 3, 4, 5):
                unit, value = _column(css, n)
                widths[n] = value if unit == "px" else table * value / 100.0
            for n, need in needs.items():
                if widths[n] + 1e-6 < need:
                    problems_found.append("%s column is %dpx and its contents need %dpx (window %dpx, sidebar %s)" % (names[n], widths[n], need, window, "open" if open_ else "shut"))
            item = table - sum(widths.values())
            if item < ITEM_MIN:
                problems_found.append("the Item column is %dpx, under %dpx (window %dpx, sidebar %s)" % (item, ITEM_MIN, window, "open" if open_ else "shut"))
    return sorted(set(problems_found))


def test_the_reviews_tables_hold_their_boxes_and_words_at_every_width_between_900_and_1000px():
    """Every column of every Review table is wide enough for what the markup card puts in it, at every table width a 900 to 1000px window can give (816 to 916px with the sidebar shut, 576 to
    676px with it open, which is the table's 640px minimum or less: it scrolls inside its box there). The Total column holds the 104px Contingency and Fees boxes and the $ box beside
    the Discount; Rate holds the % box; Unit holds its words (they wrap); Quantity holds its heading; Item is left 150px or more.

    Mutation: put the old percentage columns back; make the Unit words unable to wrap; lower the minimum width."""
    page = PAGE_PATH.read_text(encoding="utf-8")
    assert problems(page) == []


def test_the_table_still_scrolls_inside_its_own_box_below_its_minimum_width():
    css = _css(PAGE_PATH.read_text(encoding="utf-8"))
    assert re.search(r"\.tscroll\{[^}]*overflow-x:auto", css), "the table must scroll in its own box"
    assert _px(_rule(css, ".rev-t,.mk"), "min-width") >= 640
    # ...and every Review card is drawn in such a box, markup card included (the page never scrolls sideways for a table)
    js = (FRONTEND / "js" / "polish-estimate.js").read_text(encoding="utf-8")
    assert js.count('<div class="tscroll"><table class="rev-t">') == 1 and js.count('<div class="tscroll"><table class="mk">') == 1


# ── the check can see the bug: the old rules, and each new rule undone, are found ────────────────────────────────────────────────
OLD_RULES = """
    .rev-t,.mk{min-width:560px}
    .rev-t th:nth-child(2),.mk th:nth-child(2){width:20%}
    .rev-t th:nth-child(3),.mk th:nth-child(3){width:12%}
    .rev-t th:nth-child(4),.mk th:nth-child(4){width:19%}
    .rev-t th:nth-child(5),.mk th:nth-child(5){width:14%}
    .rev-t td.u,.mk td.u{color:var(--ink-3);white-space:nowrap}
"""
NEW = {
    "min": ".rev-t,.mk{min-width:640px}",
    "qty": ".rev-t th:nth-child(2),.mk th:nth-child(2){width:15%}",
    "unit": ".rev-t th:nth-child(3),.mk th:nth-child(3){width:124px}",
    "rate": ".rev-t th:nth-child(4),.mk th:nth-child(4){width:132px}",
    "total": ".rev-t th:nth-child(5),.mk th:nth-child(5){width:132px}",
    "words": ".rev-t td.u,.mk td.u{color:var(--ink-3);white-space:normal}",
}


def test_the_old_rules_are_found_to_cut_things_off():
    """The page as it was at b14bc98 (its rules for the columns, the minimum and the Unit words), run through the same check: the Total and Unit columns are too narrow at the widths a
    900 to 1000px window gives, which is the markup card's boxes and words the audit named."""
    page = PAGE_PATH.read_text(encoding="utf-8")
    old = page
    for key, line in NEW.items():
        old = old.replace(line, "") if line in old else old
    assert old != page
    old = old.replace("</style>", OLD_RULES + "</style>", 1)
    found = problems(old)
    assert any(p.startswith("Total column") for p in found), found
    assert any(p.startswith("Unit column") for p in found), found


@pytest.mark.parametrize("rule,undone,starts", [
    ("total", ".rev-t th:nth-child(5),.mk th:nth-child(5){width:14%}", "Total column"),
    ("unit", ".rev-t th:nth-child(3),.mk th:nth-child(3){width:12%}", "Unit column"),
    ("words", ".rev-t td.u,.mk td.u{color:var(--ink-3);white-space:nowrap}", "Unit column"),
    ("min", ".rev-t,.mk{min-width:560px}", None),
])
def test_each_rule_of_the_fix_is_needed(tmp_path, rule, undone, starts):
    """Put ONE of the new rules back as it was in a copy of the page: the check finds a column too narrow (the minimum width, undone alone, leaves the Item column or a box short at the
    narrowest table). break_source refuses a rule that is not on the page exactly once, so none of these can pass by applying nowhere."""
    frontend = break_source(tmp_path, "polish-estimate.html", NEW[rule], undone)
    found = problems((frontend / "polish-estimate.html").read_text(encoding="utf-8"))
    assert found, "the check did not notice %s undone" % rule
    if starts:
        assert any(p.startswith(starts) for p in found), found
