"""THE REVIEW'S TABLES FIT THEIR BOX, AND THE TOTAL COLUMN IS NEVER OUT OF VIEW (round 5 finding H, 2026-10-20; round 6 item B1, the staging walk of #694).

ROUND 5. At about 916px the Review's markup card cut off the Discount $ box, the Contingency and Fees boxes and the "margin on cost" / "of subtotal + markups" words beside them. The card's table
is `table-layout: fixed`, so its columns are whatever the header row says, and they said 20% / 12% / 19% / 14% of the table: the Total column was too narrow for the 104px box in it, the Unit column
too narrow for its words. The fix made Unit, Rate and Total PIXELS, each as wide as the markup card needs, let the Unit words wrap, and gave the table a minimum width, below which it scrolls
INSIDE its own box (the `.tscroll` the page already has), as it does on a phone.

ROUND 6. A real browser at 916px with the staff sidebar open showed what round 5's arithmetic had not: the table's box there is 575px, not 592 (916, less the 15px scrollbar, the 240px sidebar,
the page's 22px a side, and 1px + 19px + 1px a side for the section, its padding and the card), and the 640px minimum, chosen for the boxes with columns wider than their contents need (Unit 124 for
words that need 94, Rate 132 for a box that needs 104, Total 132 for 128), left 65px of every Review card out of view: the TOTAL header and every row's total were off to the right until the box
was scrolled. It fit only from 981px (980 hid 1px, 821 hid 160, 800 hid 181).

THE FIX (polish-estimate.html's CSS), two parts:

  1. The four fixed columns are as narrow as their contents allow (Quantity 82px, Unit 90, Rate 108, Total 126) with 8px of cell padding between columns and 14px at the card's two edges (the card
     title's own inset), so the table's minimum is 550px: the four columns and 144px for Item, which is the 122px of content round 5 chose as Item's floor. A box of 575px (916, sidebar open) or
     559px (900, sidebar open) holds that with nothing to scroll; Item and the Unit words wrap as before.
  2. Below that the box scrolls, and the Total column is PINNED to its right edge (`position: sticky; right: 0`, opaque) so the total is in view at every width down to a phone, with the working
     (Quantity, Unit, Rate) scrolling beneath it. `scroll-padding-right` keeps a box that is tabbed into clear of the pinned column, and the borders are the CELLS' (`border-collapse: separate`)
     because a collapsed border belongs to the table and would not travel with a pinned cell.

WHAT THIS FILE VERIFIES, AND WHAT IT DOES NOT. It verifies CSS ARITHMETIC: what a column HAS (its width, the cells' padding, the table's minimum) and the box a table sits in are read off the page's own CSS and the shell's
(auth.js's `--tw-w`, and its 768px breakpoint for moving the body), and what a column NEEDS is a set of CONTENT WIDTHS TYPED BELOW. The box formula is CALIBRATED against a real browser: test_the_model_reproduces_what_the_staging_walk_measured
runs it on the old 640px minimum and gets the walk's own five numbers (981px: nothing hidden; 980: 1px; 916: 65px; 821: 160px; 800: 181px), so the box formula is the browser's and not a guess. The typed content widths are not all
measurements: the "$" and "%" with their gaps, the longest Unit text and word, and the QUANTITY heading were measured by Chrome on ROUND 5's Review (2026-10-20: a 640px table whose columns were wider than their contents needed, and in which no
cell of any of the five cards overflowed at any width from 560 to 1000px), the working line and the widest rate are worked out at 0.6em a character, and Item's 122px of room is the floor round 5 chose. ROUND 6'S OWN WIDTHS (the 82, 90, 108
and 126px columns, the 8px cell padding, the 550px minimum and the pinned Total column) WERE NEVER MEASURED IN A BROWSER when they were written, and this file still checks them only as typed content widths that fit the widths the CSS gives them.
ONE OFF, WHICH THIS FILE CANNOT REPEAT (a headless run lays nothing out): on 2026-10-21 Chrome driven over the real page, a Polish bid and an Epoxy bid on a small stub library, the sidebar open and shut, 13 windows from 360 to 1920px, found no
cell whose content overflowed it, the Total column inside its box at every width, no table scrolling where its box was 550px or more (the 575px of 916px with the sidebar open, the 559px of 900px), every table scrolling inside its own box where the box was narrower, and no
sideways scroll of the page; the same scan on a copy with the Total column squeezed to 70px flagged overflow in every configuration, so a clean result is not vacuous. THE STAGING WALK CHECKS THE REST: the real library's names and figures, and
that the pinned column paints over what scrolls under it. Everything that can be read off the CSS IS read off it, so a box made wider without a column made wider goes red. That every row of every card has the Total as its fifth cell (a band row in
the markup card is one cell, colspan 5) is checked by executing the page in test_v2_review_working.py.

ROUND 6 AUDIT, U1: THE WARNING BESIDE A TYPED % BOX. With the Total column pinned and opaque, the red refusal beside a box typed with something unusable ("not a number, so it is not used":
`.adjwarn` inside `.adjbox`, in the Rate cell) was CUT OFF under it. The box was a one-line `inline-flex; white-space: nowrap` row, so it was no narrower than its three parts side by side at their narrowest (the 64px
box, the "%", and the warning's longest word), which is more than the 92px a Rate cell holds: the warning stood in a column of its own that began inside the cell and ended under the next one, whose
opaque background painted over it. The fix gives the warning a LINE OF ITS OWN INSIDE ITS CELL: `.adjbox` wraps, `.adjwarn` takes the whole line (`flex: 1 0 100%`) so it wraps within the cell's
width, may break a long word, and the box keeps its place on the first line. `warning_problems` reads that off the CSS. The markup it relies on (the warning is the last child of the .adjbox of
its own box, in the Rate cell, or in the Total cell for the dollar box) is checked by EXECUTING the page on a Review drawn with every box invalid, in test_v2_review_working.py.
MEASURED ONCE IN A BROWSER, which this file cannot repeat (a headless run lays nothing out): Chrome driven over the real page on 2026-10-21, 916px wide with the sidebar open, the audit's figures typed.
On the old rules the five % warnings were a column 35 to 46px wide that began 21px short of the Rate cell's right edge and ran 14 to 25px past it, every line of it under the Total cell. With the fix each is
92px wide, the room a Rate cell has (104px in the Total cell, for the dollar box), and nothing paints over it: a Polish bid at 916 and 800px, an Epoxy bid at 916, 800 and 390px.

ROUND 7, PART 2 (2026-10-21, the round-6 lows, L4): THE % BOX'S WHOLE LINE COMES CLEAR OF THE PINNED COLUMN, NOT ONLY THE BOX. The box's scroll padding was the pinned Total column's width (126px), so a %
box tabbed or typed into was brought just clear of the column and what its Rate cell holds to the right of it, the "%" and its gap and the end of the refusal's line under the box, stayed under the
column's opaque cells. Measured in Chrome on the real page (2026-10-21, the sidebar open, a % box typed "abc" so its refusal shows): at 880px (a 539px box, the table 11px wider) the box was left 8px
clear and the "%" ran 3px under the column; at 850, 820 and 600px (boxes of 509, 479 and 499px) the browser scrolled the box's right edge to the column's edge exactly, and the "%", its gap and the
refusal's line ran 11px under it; from 916px up the table fits and at 390px the table is scrolled to its end anyway. The padding is now the column's width and what a Rate cell holds to the right of a
box (the "%" and its gap, and the cell's own padding), so the browser scrolls the table to its end for a box in that column: at 880, 850, 820, 600 and 390px the "%" and the refusal's line ended 8px
clear of the column (688 against 696 at 880px). `refusal_line_problems` does that arithmetic on the CSS, and requires the padding to leave a % box's line room at the narrowest phone.

ROUND 7, PART 4 (2026-10-21, P8: the round-6 staging walk's X2, a regression of #697): A RATE TOO WIDE FOR ITS CELL. On a Gyp bid the Takeoff card's Primer row prints its rate worked to four places,
"$16.8113 / gallon" (the library's $891 drum over its 53 gallons), and Chrome measured that text at 116.8px in a Rate cell that holds 92px (108 less its 8px a side): with the cell `white-space: nowrap`
the end ran under the pinned Total column and read "$16.8113 / gall" at 916px with the sidebar open. The arithmetic had typed the widest rate as twelve characters ("$0.0987 / SF"). The fix lets a Rate
cell of the Review's cards break between its figure and its unit, balanced (`.rev-t td.rt{white-space:normal;text-wrap:balance}`: "$16.8113" over "/ gallon"), so what the cell needs is its widest piece,
never the whole line, and no column or minimum moves (the table still fits from 900px with the sidebar open). WIDEST_RATE is that string, the real widest one: test_the_widest_rate_a_gyp_review_prints_is_the_one_the_arithmetic_holds
runs the Gyp page (tests/js/gyp-page-harness.js) on the seeded library and reads every Rate cell it draws. The markup card's Rate cells do not wrap and hold the % boxes and twelve characters at most.
MEASURED ONCE IN A BROWSER, which this file cannot repeat: on 2026-10-21 Chromium (Playwright) laid out the page's own stylesheet over a Gyp Takeoff card's rows in the 575px box of 916px with the sidebar
open. With the old rule "$16.8113 / gallon" was 116.8px in its 92px content box and ran 16.8px under the Total column, and "$237.12 / roll" 4.2px past its content box; with the fix the Primer
rate read "$16.8113" over "/ gallon" (55px), "$237.12" over "/ roll", no cell's content overflowed, and the table was exactly its 575px box.

The last block puts the old rules (and each new rule, one at a time) back into a COPY of the page and requires the check to find the problem: a check that has never failed proves nothing.
"""
from __future__ import annotations

import re

import pytest

from _golden_support import FRONTEND, break_source
from _node import last_json_line, require_node, run_node
from _seed_support import plan_json

PAGE_PATH = FRONTEND / "polish-estimate.html"
GYP_HARNESS = FRONTEND.parent / "backend" / "tests" / "js" / "gyp-page-harness.js"
AUTH_PATH = FRONTEND / "auth.js"
JS_PATH = FRONTEND / "js" / "polish-estimate.js"

# What the cells hold, in pixels of CONTENT, TYPED here: the first five were measured in a browser on ROUND 5's Review, the next two are worked out, and the last is the floor round 5 chose for Item (see the docstring). The cell padding and the boxes' own widths are read off the CSS instead.
DOLLAR_AND_GAP = 12          # the "$" before the Discount dollar box, and the gap after it
PERCENT_AND_GAP = 16         # the "%" after a rate box, and the gap before it
LONGEST_UNIT_TEXT = 127      # "of subtotal + markups" at 13px: what a Unit cell needs if its words cannot wrap
LONGEST_UNIT_WORD = 70       # "escalation", the longest word a Unit cell holds: what it needs if they can
QUANTITY_HEADER = 62         # "QUANTITY" at 10.5px with its letter-spacing, before the header's own padding
# Two more, by arithmetic and not by measurement (the audit measured the boxes and the words, which were what overflowed): the widest figure a card prints in each of these columns, at
# 0.6em a character, the widest monospace face a browser falls back to.
QUANTITY_WORKING = 66        # "4 × 12 × 8", the working under a labor line's hours: ten characters of 11px monospace
MK_RATE_FIGURE = 90          # the markup card's Rate cells do not wrap: "$123.45 / SF", the lump sum a square foot, twelve characters of 12.5px monospace
ITEM_CONTENT_MIN = 122       # the Item column wraps; below this much room for its words a label of two words stands on a line of its own (round 5's 150px column less its 28px of padding)
# THE WIDEST RATE THE REVIEW'S CARDS PRINT (round 7, part 4, P8: the round-6 staging walk's X2). The Gyp Primer row's rate on the seeded library, read off the page by
# test_the_widest_rate_a_gyp_review_prints_is_the_one_the_arithmetic_holds. Chrome measured it at 116.8px on the walk (12.5px Consolas, 0.55em a character); at the 0.6em a character this file
# takes for the widest monospace face a browser falls back to, it is 127.5px. A Rate cell holds 92px.
WIDEST_RATE = "$16.8113 / gallon"
WIDEST_RATE_MEASURED = 116.8
RATE_CHAR = 0.6 * 12.5       # a character of the Review's 12.5px monospace, at 0.6em


def rate_text_width(text: str) -> float:
    """What a rate's text needs to stand on one line: the walk's measurement for the widest string, and 0.6em a character for any text (the larger of the two)."""
    return max(len(text) * RATE_CHAR, WIDEST_RATE_MEASURED if text == WIDEST_RATE else 0)


def widest_piece(text: str) -> str:
    """The widest piece a cell that may wrap can break `text` into: its longest run between spaces (a no-break space holds its neighbours together)."""
    return max(text.split(" "), key=len)

# The staging walk of #694 (a real browser): the table's box at 916px with the sidebar open was 575px. A classic vertical scrollbar of 15px is the one value for which every number below holds.
SCROLLBAR = 15
SCROLLBARS = (0, SCROLLBAR, 17)              # an overlay scrollbar, the walk's, and a wider classic one
OLD_MIN_WIDTH = 640                          # the minimum width of 619f092, which the walk measured
WALK = {981: 0, 980: 1, 916: 65, 821: 160, 800: 181}     # window width with the sidebar open -> px of the 640px table out of view, as the walk measured them
# The layout of the page the walk measured (619f092), typed in so the calibration below stays what it is, a check of the FORMULA against the browser's numbers, if the page's padding changes later.
WALK_LAYOUT = {"body_pad": 44, "wrap_max": 1000, "sec_border": 1, "sec_pad": 19, "rev_border": 1, "rail": 240, "rail_from": 768}
FIT_FROM, FIT_TO = 900, 1500                 # from here up a Review table must need no scrolling at all
PIN_FROM = 360                               # the narrowest phone the shell supports (test_phone_shell.py); between here and FIT_FROM the box may scroll
REST_OF_THE_BOX = 100                        # what the pinned Total column must leave of the box for the working to scroll in

NAMES = {1: "Item", 2: "Quantity", 3: "Unit", 4: "Rate", 5: "Total"}


# ── reading the page's CSS ───────────────────────────────────────────────────────────────────────────────
def _css(page: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"/\*.*?\*/", "", page, flags=re.S))


def _rule(css: str, selector: str) -> str:
    """The declarations of EVERY rule whose selector list is exactly `selector`, in the order the page has them (a later rule wins, as in the cascade)."""
    found = re.findall(r"(?:^|[}\s])" + re.escape(selector) + r" ?\{([^}]*)\}", css)
    assert found, "the page has no rule for %r" % selector
    return ";".join(found)


def _rules(css: str):
    """(selector list, declarations) for every rule of the page's style block, a rule inside an @media block included (its prelude is dropped: nothing read this way is conditional)."""
    if "<style>" in css:
        css = css[css.index("<style>") + len("<style>"):css.index("</style>")]
    for chunk in css.split("}"):
        if "{" not in chunk:
            continue
        head, body = chunk.rsplit("{", 1)
        yield head.rsplit("{", 1)[-1].strip(), body


def _decls_for(css: str, selector: str) -> dict:
    """Every declaration of every rule whose selector LIST holds `selector`, merged in the order the page has them (a later rule wins)."""
    merged: dict = {}
    for selectors, body in _rules(css):
        if selector in [s.strip() for s in selectors.split(",")]:
            for decl in body.split(";"):
                if ":" in decl:
                    prop, value = decl.split(":", 1)
                    merged[prop.strip()] = value.strip()
    return merged


def _px(declarations: str, prop: str) -> int:
    found = re.findall(r"(?:^|[;\s])" + re.escape(prop) + r":\s*(\d+)px", declarations)
    assert found, "no %s in %r" % (prop, declarations)
    return int(found[-1])


def _px_value(token: str) -> int:
    return 0 if token.strip() == "0" else int(token.strip().rstrip("px"))


def _padding_lr(value: str) -> tuple[int, int]:
    parts = [_px_value(t) for t in value.split()]
    if len(parts) == 1:
        return parts[0], parts[0]
    if len(parts) in (2, 3):
        return parts[1], parts[1]
    return parts[3], parts[1]


def _column(css: str, n: int):
    """('%', 15) or ('px', 124): the width the header row gives column `n` of every Review table."""
    decl = _rule(css, ".rev-t th:nth-child(%d),.mk th:nth-child(%d)" % (n, n))
    found = re.findall(r"width:\s*(\d+)(%|px)", decl)
    assert found, "column %d has no width: %r" % (n, decl)
    return found[-1][1], int(found[-1][0])


def _cell_pads(css: str, kind: str) -> dict:
    """{table: [(left, right) for each of the five columns]} for the `th` or `td` cells: the table's own padding, and the card's edges (`:first-child`, `:last-child`) where the page gives them their own."""
    out = {}
    for table in (".rev-t", ".mk"):
        base = _decls_for(css, "%s %s" % (table, kind))
        assert "padding" in base, "%s %s has no padding" % (table, kind)
        left, right = _padding_lr(base["padding"])
        first = _decls_for(css, "%s %s:first-child" % (table, kind))
        last = _decls_for(css, "%s %s:last-child" % (table, kind))
        pads = []
        for n in range(1, 6):
            l, r = left, right
            if n == 1 and "padding-left" in first:
                l = _px_value(first["padding-left"])
            if n == 5 and "padding-right" in last:
                r = _px_value(last["padding-right"])
            pads.append((l, r))
        out[table] = pads
    return out


def _variables(css: str) -> dict:
    return {k: v for k, v in _decls_for(css, ":root").items() if k.startswith("--")}


def _color(value: str, variables: dict):
    """The colour a declaration comes to, following var(--x, fallback) through the tokens; None when it cannot be told."""
    value = (value or "").strip()
    m = re.fullmatch(r"var\((--[\w-]+)(?:,\s*(.+))?\)", value)
    if m:
        if m.group(1) in variables:
            return _color(variables[m.group(1)], variables)
        return _color(m.group(2), variables) if m.group(2) else None
    return value or None


def _opaque(value: str, variables: dict) -> bool:
    color = _color(value, variables)
    if not color or color in ("transparent", "none", "inherit", "initial", "unset"):
        return False
    if re.fullmatch(r"#[0-9a-fA-F]{3}|#[0-9a-fA-F]{6}", color):
        return True
    m = re.fullmatch(r"rgba?\(([^)]*)\)", color)
    if m:
        parts = [p.strip() for p in m.group(1).replace("/", ",").split(",")]
        return len(parts) < 4 or float(parts[3]) >= 1
    return False                      # a value this cannot read is not proof of an opaque one


# ── the geometry: the box a table sits in ────────────────────────────────────────────────────────────────
def layout(page: str) -> dict:
    """What decides the width of the box a table sits in, read off the page's CSS and the shell's: the body's side padding (both sides), the page column's maximum, the section's border, the section
    body's side padding, the card's border, and the sidebar's width and the window width from which it moves the body."""
    css = _css(page)
    shell = AUTH_PATH.read_text(encoding="utf-8")
    rail = re.search(r"--tw-w:\s*(\d+)px", shell)
    breakpoint_ = re.search(r"@media\s*\(min-width:\s*(\d+)px\)\s*\{\s*html\.tw-nav-open body\{\s*margin-left:\s*var\(--tw-w\)", shell)
    assert rail and breakpoint_, "auth.js no longer says how wide the sidebar is, or from what width it moves the body"
    return {
        "body_pad": 2 * int(re.search(r"body\{[^}]*padding:\s*0 (\d+)px", css).group(1)),
        "wrap_max": _px(_rule(css, ".wrap"), "max-width"),
        "sec_border": int(re.search(r"border:\s*(\d+)px", _rule(css, ".sec")).group(1)),
        "sec_pad": int(re.search(r"padding:\s*\d+px (\d+)px", _rule(css, ".sec-b")).group(1)),
        "rev_border": int(re.search(r"border:\s*(\d+)px", _rule(css, ".rev")).group(1)),
        "rail": int(rail.group(1)),
        "rail_from": int(breakpoint_.group(1)),
    }


def facts(page: str) -> dict:
    """Everything the arithmetic needs: the layout, and the tables' own rules."""
    css = _css(page)
    return {
        "css": css,
        "min_width": _px(_rule(css, ".rev-t,.mk"), "min-width"),   # two rules name both tables together: the minimum width, and table-layout
        "columns": {n: _column(css, n) for n in (2, 3, 4, 5)},
        **layout(page),
    }


def box_width(f: dict, window: int, rail_open: bool, scrollbar: int = SCROLLBAR) -> int:
    """The width of the `.tscroll` box a Review table sits in, in a window `window`px wide. The page column is the viewport (less the scrollbar), less the body margin the open sidebar gives it at
    768px and up (a sheet over the page below that, which moves nothing), less the body's side padding, at most 1000px; the box is that less the section's border, its padding and the card's border."""
    viewport = window - scrollbar
    shifted = f["rail"] if rail_open and window >= f["rail_from"] else 0
    column = min(f["wrap_max"], viewport - shifted - f["body_pad"])
    return column - 2 * f["sec_border"] - 2 * f["sec_pad"] - 2 * f["rev_border"]


def out_of_view(f: dict, window: int, rail_open: bool, scrollbar: int = SCROLLBAR, min_width: int | None = None) -> int:
    """How many px of the table lie beyond its box: a table is as wide as its box but never narrower than its minimum, and what does not fit scrolls."""
    table = f["min_width"] if min_width is None else min_width
    return max(0, table - box_width(f, window, rail_open, scrollbar))


# ── what each column needs, and what it has ─────────────────────────────────────────────────────────────
def rate_cell_wraps(css: str) -> bool:
    """May a Rate cell of the Review's cards (`.rev-t td.rt`) break its text over lines? Every rule whose selector list names it, merged in the page's order (a later one wins): white-space normal (or a
    pre-wrap kind), and no text-wrap or text-wrap-mode that says nowrap."""
    d = _decls_for(css, ".rev-t td.rt")
    ws = d.get("white-space", "normal")
    return ws in ("normal", "pre-wrap", "pre-line", "break-spaces") and d.get("text-wrap", "").split(" ")[0] != "nowrap" and d.get("text-wrap-mode", "wrap") != "nowrap"


def needs(f: dict) -> dict:
    """{column: px} the column must be, from what the cards put in it plus the cell's own padding (the stricter of the two tables, and of the header and the body cells)."""
    css = f["css"]
    pads_td, pads_th = _cell_pads(css, "td"), _cell_pads(css, "th")
    mk_box = _px(_rule(css, ".mk input"), "width")
    pct_box = _px(_rule(css, ".adjbox input,.mk .adjbox input"), "width")
    amt_box = _px(_rule(css, ".adjbox.adjamt input,.mk .adjbox.adjamt input"), "width")
    unit_wraps = _rule(css, ".rev-t td.u,.mk td.u").replace(" ", "").split("white-space:")[-1].startswith("normal")
    # A Rate cell of the Review's cards that may wrap needs its widest piece; one that may not needs the whole text (round 7, part 4, P8). Every rule naming `.rev-t td.rt` counts, the later winning.
    rate_wraps = rate_cell_wraps(css)
    rev_rate = rate_text_width(widest_piece(WIDEST_RATE)) if rate_wraps else rate_text_width(WIDEST_RATE)
    content = {                                   # column: (what the header holds, what a body cell holds)
        1: (0, ITEM_CONTENT_MIN),
        2: (QUANTITY_HEADER, QUANTITY_WORKING),
        3: (0, LONGEST_UNIT_WORD if unit_wraps else LONGEST_UNIT_TEXT),
        4: (0, max(pct_box + PERCENT_AND_GAP, MK_RATE_FIGURE, rev_rate)),
        5: (0, max(mk_box, amt_box + DOLLAR_AND_GAP)),
    }
    out = {}
    for n, (head, cell) in content.items():
        out[n] = max(max(head + l + r for l, r in (pads_th[t][n - 1] for t in pads_th)),
                     max(cell + l + r for l, r in (pads_td[t][n - 1] for t in pads_td)))
    return out


def widths_at(f: dict, table: float) -> dict:
    """{column: px}: the header row's widths, a share of the table where the page says a share, and Item (no width of its own) with what is left."""
    out = {}
    for n, (unit, value) in f["columns"].items():
        out[n] = value if unit == "px" else table * value / 100.0
    out[1] = table - sum(out.values())
    return out


def fit_problems(page: str) -> list[str]:
    """Is every column wide enough for what it holds, at the narrowest table the page allows (a share of the table is at its narrowest there, and so is Item)?"""
    f = facts(page)
    table = f["min_width"]
    need, have = needs(f), widths_at(f, table)
    found = []
    for n in (2, 3, 4, 5):
        if have[n] + 1e-6 < need[n]:
            found.append("%s column is %dpx and its contents need %dpx (table %dpx)" % (NAMES[n], have[n], need[n], table))
    if have[1] + 1e-6 < need[1]:
        found.append("Item column is %dpx, under the %dpx its words need (table %dpx)" % (have[1], need[1], table))
    return found


# ── the Total column in view ─────────────────────────────────────────────────────────────────────────────
def pin_problems(page: str) -> list[str]:
    """Is the Total column PINNED to the right edge of the box the table scrolls in, so it stays in view when the table is wider than the box?"""
    css = _css(page)
    variables = _variables(css)
    found = []
    for kind in ("th", "td"):
        for table in (".rev-t", ".mk"):
            d = _decls_for(css, "%s %s:nth-child(5)" % (table, kind))
            if d.get("position") != "sticky":
                found.append("pin: the Total %s cell of the %s table is %r, not position:sticky" % (kind, table, d.get("position")))
            elif d.get("right") not in ("0", "0px"):
                found.append("pin: the Total %s cell of the %s table is pinned with right:%s, not to the box's right edge" % (kind, table, d.get("right")))
    for table in (".rev-t", ".mk"):
        bg = _decls_for(css, "%s td:nth-child(5)" % table).get("background")
        if not _opaque(bg, variables):
            found.append("pin: a pinned Total cell of the %s table has background %r, so the cells scrolling under it would show through" % (table, bg))
    th_bg = _decls_for(css, ".rev-t th").get("background")
    if not _opaque(th_bg, variables):
        found.append("pin: the pinned TOTAL header has background %r, so the cells scrolling under it would show through" % th_bg)
    # a row that wears the card's tint has to wear an opaque one: every card the page draws names its tint
    js = JS_PATH.read_text(encoding="utf-8")
    keys = set(re.findall(r'card\("[^"]*", \d+, "(\w+)"', js)) | set(re.findall(r'data-rev="(\w+)" class="rev"', js))
    assert {"takeoff", "labor", "travel", "markup"} <= keys, "the cards the page draws are no longer the ones this check knows: %r" % sorted(keys)
    for key in sorted(keys):
        card = _decls_for(css, '.rev[data-rev="%s"]' % key)
        if not _opaque("var(--rev-tot)", {**variables, **{k: v for k, v in card.items() if k.startswith("--")}}):
            found.append("pin: the %s card has no opaque --rev-tot, so its total row would be see-through under a pinned cell" % key)
    columns = {n: _column(css, n) for n in (5,)}
    total_width = columns[5][1] if columns[5][0] == "px" else None
    padding = _decls_for(css, ".tscroll").get("scroll-padding-right", "")
    if total_width is not None and (not re.fullmatch(r"\d+px", padding) or int(padding[:-2]) < total_width):
        found.append("pin: the .tscroll box has scroll-padding-right %r, under the pinned Total column's %spx, so a box tabbed into could stay under it" % (padding, total_width))
    # ...but not while focus is IN the pinned column: its boxes sit in the padded-off band, and a focus or a keystroke in one would scroll the table to put it clear of itself (the sticky head found
    # the same cost in a browser, see .v2head: its zero padding while focus is inside it)
    zero = _decls_for(css, ".tscroll:has(td:nth-child(5):focus-within)").get("scroll-padding-right")
    if zero not in ("0", "0px"):
        found.append("pin: the .tscroll box keeps scroll-padding-right %r while focus is in the pinned column, so a focus or a keystroke in one of its boxes would scroll the table to put it clear of itself" % zero)
    for table in (".rev-t", ".mk"):
        d = _decls_for(css, table)
        if d.get("border-collapse") != "separate" or d.get("border-spacing") not in ("0", "0px"):
            found.append("pin: the %s table has border-collapse:%s: a collapsed border belongs to the table and would not travel with a pinned cell" % (table, d.get("border-collapse")))
    return found


def view_problems(page: str) -> list[str]:
    """From 900px up no Review table may need scrolling, in any sidebar state and with any scrollbar; below it the Total column must be pinned wherever the table scrolls, and leave room."""
    f = facts(page)
    found = []
    for scrollbar in SCROLLBARS:
        for rail_open in (False, True):
            hidden, window = max((out_of_view(f, w, rail_open, scrollbar), w) for w in range(FIT_FROM, FIT_TO + 1))
            if hidden:
                found.append("the Total column is %dpx out of view at a window %dpx wide (sidebar %s, scrollbar %dpx): from %dpx up a Review table must fit its box without scrolling"
                             % (hidden, window, "open" if rail_open else "shut", scrollbar, FIT_FROM))
    pinned = not pin_problems(page)
    total = f["columns"][5]
    for scrollbar in SCROLLBARS:
        for rail_open in (False, True):
            below = [(out_of_view(f, w, rail_open, scrollbar), w) for w in range(PIN_FROM, FIT_FROM)]
            hidden, window = max(below)
            if hidden and not pinned:
                found.append("the table scrolls (%dpx at a window %dpx wide, sidebar %s, scrollbar %dpx) and the Total column is not pinned, so it scrolls out of view with it"
                             % (hidden, window, "open" if rail_open else "shut", scrollbar))
            if hidden and total[0] == "px":
                narrowest = min((box_width(f, w, rail_open, scrollbar), w) for _h, w in below)
                if narrowest[0] - total[1] < REST_OF_THE_BOX:
                    found.append("the pinned Total column leaves %dpx of the box at a window %dpx wide (sidebar %s, scrollbar %dpx), under the %dpx the working needs to scroll in"
                                 % (narrowest[0] - total[1], narrowest[1], "open" if rail_open else "shut", scrollbar, REST_OF_THE_BOX))
    return sorted(set(found))


def at_916_problems(page: str) -> list[str]:
    """The staging walk's own window: 916px wide with the sidebar open, where the box is 575px. The table must fit it, so the TOTAL header and every row's total need no scrolling to be seen."""
    f = facts(page)
    hidden = out_of_view(f, 916, True)
    if not hidden:
        return []
    return ["the table is %dpx wide in a %dpx box: the last %dpx of it, the TOTAL column, are out of view until the box is scrolled (916px, sidebar open)" % (f["min_width"], box_width(f, 916, True), hidden)]


def refusal_line_problems(page: str) -> list[str]:
    """ROUND 7, PART 2 (L4): does a % box tabbed or typed into come clear of the pinned Total column WITH THE REST OF ITS LINE? The browser scrolls a focused box (and a caret) clear of the box's
    scroll padding, and no further: a padding as wide as the pinned column alone brings the box to the column's edge and leaves the "%" after it, its gap and the refusal's line under the box
    (which is as wide as the box's line) under the column. So the padding must be the pinned column's width and what the Rate cell holds to the right of a box: the "%" and its gap, and the cell's
    own right padding (the wider of the two tables'). And it must leave a % box's line room in the box at the narrowest phone, or the browser cannot honour it."""
    f = facts(page)
    css = f["css"]
    found = []
    total = f["columns"][5]
    padding = _decls_for(css, ".tscroll").get("scroll-padding-right", "")
    if total[0] != "px" or not re.fullmatch(r"\d+px", padding):
        return found                       # pin_problems names a padding that is not a plain figure, and a Total column that is a share
    pads = _cell_pads(css, "td")
    rate_right = max(r for _l, r in (pads[tbl][3] for tbl in pads))
    need = total[1] + PERCENT_AND_GAP + rate_right
    have = int(padding[:-2])
    if have < need:
        found.append("refusal: the .tscroll box has scroll-padding-right %dpx, which brings a %% box typed into clear of the pinned Total column (%dpx) but leaves what its Rate cell holds to the right "
                     "of it under the column: the %% and its gap (%dpx) and the cell's padding (%dpx), the refusal's line with them. It needs %dpx" % (have, total[1], PERCENT_AND_GAP, rate_right, need))
    pct_box = _px(_rule(css, ".adjbox input,.mk .adjbox input"), "width")
    line = pct_box + PERCENT_AND_GAP
    for scrollbar in SCROLLBARS:
        for rail_open in (False, True):
            narrowest = min((box_width(f, w, rail_open, scrollbar), w) for w in range(PIN_FROM, FIT_FROM))
            if narrowest[0] - have < line:
                found.append("refusal: at a window %dpx wide (sidebar %s, scrollbar %dpx) the box is %dpx and its scroll padding %dpx leaves %dpx, under the %dpx a %% box's line needs"
                             % (narrowest[1], "open" if rail_open else "shut", scrollbar, narrowest[0], have, narrowest[0] - have, line))
    return sorted(set(found))


def problems(page: str) -> list[str]:
    return sorted(set(fit_problems(page) + pin_problems(page) + view_problems(page) + scroll_problems(page) + at_916_problems(page) + refusal_line_problems(page)))


# ── the assertions ───────────────────────────────────────────────────────────────────────────────────────
def test_the_model_reproduces_what_the_staging_walk_measured():
    """The arithmetic is only worth believing if it gives the browser's numbers. For the layout the walk measured, on the 640px minimum it measured, the box and what stuck out of it are the walk's
    own at all five windows it recorded with the sidebar open: 981px fits exactly, 980 hides 1px, 916 hides 65, 821 hides 160, 800 hides 181; the box at 916px is 575px. A 15px scrollbar is the only
    value for which that holds, GIVEN the layout's other terms, which the CSS states: the five windows fix only the SUM of what is taken from the box (a 15px scrollbar and 2px of border are told
    apart by the CSS, not by the walk). Below the shell's breakpoint the sidebar is a sheet over the page and takes nothing from the box.

    Mutation: test_each_term_of_the_box_formula_is_needed_to_reproduce_the_walk drops each term of the formula in turn."""
    assert box_width(WALK_LAYOUT, 916, True) == 575
    for window, hidden in sorted(WALK.items()):
        assert out_of_view(WALK_LAYOUT, window, True, SCROLLBAR, min_width=OLD_MIN_WIDTH) == hidden, (window, box_width(WALK_LAYOUT, window, True))
    assert [sb for sb in range(0, 31) if _reproduces_the_walk(WALK_LAYOUT, sb)] == [SCROLLBAR]
    assert box_width(WALK_LAYOUT, 767, True) == box_width(WALK_LAYOUT, 767, False)
    assert box_width(WALK_LAYOUT, 768, True) == box_width(WALK_LAYOUT, 768, False) - WALK_LAYOUT["rail"]


def _reproduces_the_walk(layout_: dict, scrollbar: int) -> bool:
    return all(out_of_view(layout_, w, True, scrollbar, min_width=OLD_MIN_WIDTH) == hidden for w, hidden in WALK.items())


@pytest.mark.parametrize("term", ["body_pad", "sec_pad", "rail"])
def test_each_term_of_the_box_formula_is_needed_to_reproduce_the_walk(term):
    """Take one term out of the box formula (the body's padding, the section's padding, the sidebar) and the walk's five numbers are no longer reproduced at any scrollbar width: the calibration can
    tell a right formula from a wrong one. (The 1px borders are not here: a border of 2px and a scrollbar 2px narrower are the same to the walk, so it cannot tell them apart; the CSS can, and says 1px.)"""
    broken = dict(WALK_LAYOUT, **{term: 0})
    assert not any(_reproduces_the_walk(broken, sb) for sb in range(0, 31)), term


def test_the_layout_is_read_off_the_pages_css_and_the_shell():
    """The synthetic page says 10px of body padding a side, a 900px column, a 2px section border, 7px of section padding a side and a 3px card border; the shell says how wide its rail is and from what
    width it moves the body, and the arithmetic follows both (a sheet over the page, below that width, moves nothing)."""
    page = ("<style>body{margin:0;padding:0 10px 99px}.wrap{max-width:900px;margin:0 auto}.sec{border:2px solid red}.sec-b{padding:5px 7px}.rev{border:3px solid blue}</style>")
    got = layout(page)
    assert {k: got[k] for k in ("body_pad", "wrap_max", "sec_border", "sec_pad", "rev_border")} == {"body_pad": 20, "wrap_max": 900, "sec_border": 2, "sec_pad": 7, "rev_border": 3}
    assert got["rail"] > 0 and got["rail_from"] > 0
    assert box_width(got, 1000, False, 0) == 900 - 2 * 2 - 2 * 7 - 2 * 3
    edge = got["rail_from"]
    assert box_width(got, edge, True, 15) == (edge - 15 - got["rail"] - 20) - 4 - 14 - 6
    assert box_width(got, edge - 1, True, 15) == (edge - 1 - 15 - 20) - 4 - 14 - 6


def test_the_total_column_is_in_view_at_916px_with_the_sidebar_open():
    """The walk's own window: the box is 575px and the table must fit it, so the TOTAL header and every row's total need no scrolling to be seen.

    Mutation: put the 640px minimum back."""
    assert at_916_problems(PAGE_PATH.read_text(encoding="utf-8")) == []


def test_no_review_table_needs_scrolling_from_900px_up_whatever_the_sidebar_or_the_scrollbar():
    """From 900px up (the sidebar open or shut; no scrollbar, the walk's 15px, or a wider 17px one) every Review table fits its box. At 900px with the sidebar open and a 17px scrollbar the box is 557px.

    Mutation: put the 640px minimum back; a minimum above the box at 900px."""
    page = PAGE_PATH.read_text(encoding="utf-8")
    assert [p for p in view_problems(page) if p.startswith("the Total column is")] == []


def test_below_that_the_total_column_stays_in_view_down_to_a_phone_and_leaves_room():
    """A box narrower than the table's minimum scrolls, and the Total column is PINNED to its right edge, so it is in view at every window from a 360px phone up, and leaves 100px or more of the box for
    the working to scroll in.

    Mutation: unpin the cells; a Total column 200px wide."""
    page = PAGE_PATH.read_text(encoding="utf-8")
    assert [p for p in view_problems(page) if not p.startswith("the Total column is")] == []


def test_the_pinned_total_cells_are_opaque_pinned_to_the_right_edge_and_keep_their_own_borders():
    """`position: sticky; right: 0` on the header and body cells of both tables; an opaque background on each (and an opaque tint on every card's total row); a scroll padding as wide as the pinned column
    so a box tabbed into is not left under it; and borders that are the cells' own, which a collapsed border is not.

    Mutation: static cells; the other edge; no background; a see-through card tint; no scroll padding, and one too small; collapsed borders."""
    assert pin_problems(PAGE_PATH.read_text(encoding="utf-8")) == []


def test_a_box_tabbed_or_typed_into_comes_clear_of_the_pinned_column_with_the_rest_of_its_line():
    """ROUND 7, PART 2 (L4): the box's scroll padding is the pinned Total column's width (126px) and what a Rate cell holds to the right of a % box (the "%" and its gap, 16px, and the cell's padding, 8px):
    150px. With 126px Chrome left the "%" and the refusal's last 11px under the column at 850, 820 and 600px (sidebar open); with 150px the table scrolls to its end and they end 8px clear. The padding
    still leaves a % box's line room at a 360px phone.

    Mutation: the round-6 padding (the column's width alone); a padding that eats a phone's box."""
    assert refusal_line_problems(PAGE_PATH.read_text(encoding="utf-8")) == []


def test_every_column_holds_what_the_cards_put_in_it():
    """Every column of every Review table is wide enough for what the markup card puts in it, at the narrowest table the page allows (550px): Total holds the 104px Contingency and Fees boxes and
    the $ box beside the Discount; Rate holds the % box and a twelve-character figure; Unit holds its words (they wrap); Quantity holds its heading and a working line; Item keeps 122px of room.

    Mutation: percentage columns; Unit words that cannot wrap; wider cell padding between columns, and at the card's two edges; a minimum width under what the columns and Item need."""
    assert fit_problems(PAGE_PATH.read_text(encoding="utf-8")) == []


def test_a_rate_too_wide_for_its_cell_wraps_its_unit_under_its_figure_and_the_total_stays_in_view():
    """ROUND 7, PART 4 (P8: the walk's X2). The widest rate the Review prints, "$16.8113 / gallon" (116.8px measured, 127.5px at 0.6em), is wider than the 92px a Rate cell holds, so the cell may
    break it between its figure and its unit: its widest piece, "$16.8113", needs 60px, and the % box's line (80px) is what the column is sized for. No width or minimum moved: the table fits its 575px
    box at 916px with the sidebar open, the Total column in view, and from 900px up.

    Mutation: the Rate cell's rule taken away (nowrap again), which the check names as the Rate column too narrow for what it holds."""
    page = PAGE_PATH.read_text(encoding="utf-8")
    css = _css(page)
    assert rate_cell_wraps(css)
    assert widest_piece(WIDEST_RATE) == "$16.8113" and rate_text_width(widest_piece(WIDEST_RATE)) == 60
    f = facts(page)
    room = f["columns"][4][1] - max(l + r for l, r in (_cell_pads(css, "td")[".rev-t"][3],))
    assert room == 92 and rate_text_width(WIDEST_RATE) > room >= rate_text_width(widest_piece(WIDEST_RATE)), "the whole line does not fit a Rate cell, its widest piece does"
    assert fit_problems(page) == [] and at_916_problems(page) == []


def test_the_widest_rate_a_gyp_review_prints_is_the_one_the_arithmetic_holds(tmp_path):
    """EXECUTED: the Gyp page on the seeded library, taken to its Review (tests/js/gyp-page-harness.js), and every Rate cell it draws read back. "$16.8113 / gallon" (the Primer row) is among them and no
    rate is longer, so the content width above is the real widest string, not a guess; and every rate's widest piece fits the 92px of a Rate cell at 0.6em a character, which is what lets the cell
    wrap instead of running under the pinned Total column."""
    require_node()
    proc = run_node(GYP_HARNESS, FRONTEND, plan_json(tmp_path))
    assert proc.returncode == 0, "the Gyp page harness failed:\n" + proc.stderr[-1500:]
    rates = last_json_line(proc.stdout)["review"]["rates"]
    assert WIDEST_RATE in rates and max(len(t) for t in rates) == len(WIDEST_RATE), rates
    css = _css(PAGE_PATH.read_text(encoding="utf-8"))
    room = facts(PAGE_PATH.read_text(encoding="utf-8"))["columns"][4][1] - max(l + r for l, r in (_cell_pads(css, "td")[".rev-t"][3],))
    assert [t for t in rates if rate_text_width(widest_piece(t)) > room] == [], "a rate has a piece wider than its cell"


def scroll_problems(page: str) -> list[str]:
    """Does a table wider than its box scroll INSIDE its own box (the page never scrolls sideways for a table), and is every Review card drawn in such a box?"""
    css = _css(page)
    found = []
    if not re.search(r"\.tscroll\{[^}]*overflow-x:auto", css):
        found.append("the .tscroll box does not scroll sideways, so a table wider than it would push the page sideways")
    js = JS_PATH.read_text(encoding="utf-8")
    if js.count('<div class="tscroll"><table class="rev-t">') != 1 or js.count('<div class="tscroll"><table class="mk">') != 1:
        found.append("a Review card is not drawn in a .tscroll box")
    return found


def test_the_table_still_scrolls_inside_its_own_box_below_its_minimum_width():
    """Mutation: a box that does not scroll."""
    assert scroll_problems(PAGE_PATH.read_text(encoding="utf-8")) == []


# ── the warning beside a typed % box stays in its cell (round 6 audit, U1) ──────────────────────────────────────────────
def _flex_basis(decls: dict):
    """The flex-basis a set of declarations gives: `flex-basis`, or the basis in the `flex` shorthand (`1 0 100%`, `1 100%`; a bare number is a grow factor and the basis is then 0%); None when it says none."""
    if "flex-basis" in decls:
        return decls["flex-basis"].strip()
    parts = decls.get("flex", "").split()
    if not parts:
        return None
    for part in parts:
        if part in ("auto", "content") or re.fullmatch(r"-?\d*\.?\d+(?:px|%|em|rem)", part):
            return part
    return "auto" if parts == ["none"] else "0%"


def warning_problems(page: str) -> list[str]:
    """Is the warning beside a typed % box a flex item that WRAPS onto a line of its own inside its cell? `.adjbox` must be a wrapping flex row that keeps its first line (the box and its %) at the right
    of the cell, where it sits with no warning; `.adjwarn` must take the whole line, wrap its words (and a long word) inside it, and not be capped narrower than the cell it is in."""
    css = _css(page)
    box, warn = _decls_for(css, ".adjbox"), _decls_for(css, ".adjwarn")
    found = []
    if "flex" not in box.get("display", ""):
        found.append("warning: .adjbox is display:%s, not a flex row, so the warning is not an item of it" % box.get("display"))
    elif box.get("flex-wrap") not in ("wrap", "wrap-reverse"):
        found.append("warning: .adjbox does not wrap (flex-wrap:%s), so its warning stays on the line of the box and is as wide as the box and the words add up to, which runs out of the cell and under the pinned Total column"
                     % box.get("flex-wrap", "nowrap"))
    if box.get("justify-content") not in ("flex-end", "end", "right"):
        found.append("warning: .adjbox does not keep its first line at the right of the cell (justify-content:%s), so the %% box jumps left of where it sits when a warning appears" % box.get("justify-content", "flex-start"))
    basis = _flex_basis(warn) or "auto"                  # no flex-basis at all is auto: the width of the words
    if basis != "100%":
        found.append("warning: .adjwarn has a flex-basis of %s, not 100%%, so it can share a line with the box and does not wrap inside its cell" % basis)
    if warn.get("white-space") != "normal":
        found.append("warning: .adjwarn has white-space:%s, so its words cannot wrap inside the cell" % warn.get("white-space"))
    if warn.get("overflow-wrap") != "anywhere" and warn.get("word-break") not in ("break-all", "break-word"):
        found.append("warning: .adjwarn may not break a long word (overflow-wrap:%s), so one could run out of the cell" % warn.get("overflow-wrap", "normal"))
    # a cap is harmless while it is wider than the narrowest cell a warning sits in (the Rate cell's room, or the Total cell's for the dollar box): narrower, it leaves the words in a column the box's line is not
    cap = warn.get("max-width", "none").strip()
    f = facts(page)
    pads = _cell_pads(css, "td")

    def cell_room(n):             # what a cell of column n has for content: the column's width less the wider of the two tables' padding
        return f["columns"][n][1] - max(l + r for l, r in (pads[t][n - 1] for t in pads))
    room = min(cell_room(n) for n in (4, 5) if f["columns"][n][0] == "px")
    if cap != "none" and not (re.fullmatch(r"\d+px", cap) and int(cap[:-2]) >= room):
        found.append("warning: .adjwarn is capped at %s, narrower than the %dpx of the narrowest cell it sits in" % (cap, room))
    return found


def test_a_warning_beside_a_typed_box_gets_a_line_of_its_own_inside_its_cell():
    """Round 6 audit, U1: the refusal beside a typed % box was cut off under the pinned Total column because the box was a nowrap row. `.adjbox` wraps, keeps its box at the right, and `.adjwarn` takes the
    whole line, wraps its words and a long word, and is not capped narrower than its cell.

    Mutation: the old `.adjbox` rule; the old `.adjwarn` rule; a row that does not wrap, one that is not a flex row, one that lets the box jump left, a warning that shares the box's line, one that cannot
    wrap, one that may not break a long word, one capped narrower than its cell."""
    assert warning_problems(PAGE_PATH.read_text(encoding="utf-8")) == []


# ── the check can see the bug: the old rules, and each new rule undone, are found ────────────────────────────────────────────────
# The page as it was at b14bc98 (round 4): percentage columns and a 560px minimum.
OLD_RULES = """
    .rev-t,.mk{min-width:560px}
    .rev-t th:nth-child(2),.mk th:nth-child(2){width:20%}
    .rev-t th:nth-child(3),.mk th:nth-child(3){width:12%}
    .rev-t th:nth-child(4),.mk th:nth-child(4){width:19%}
    .rev-t th:nth-child(5),.mk th:nth-child(5){width:14%}
    .rev-t td.u,.mk td.u{color:var(--ink-3);white-space:nowrap}
"""
NEW = {
    "min": ".rev-t,.mk{min-width:550px}",
    "qty": ".rev-t th:nth-child(2),.mk th:nth-child(2){width:82px}",
    "unit": ".rev-t th:nth-child(3),.mk th:nth-child(3){width:90px}",
    "rate": ".rev-t th:nth-child(4),.mk th:nth-child(4){width:108px}",
    "total": ".rev-t th:nth-child(5),.mk th:nth-child(5){width:126px}",
    "words": ".rev-t td.u,.mk td.u{color:var(--ink-3);white-space:normal}",
}
# The rules round 6 added or changed, exactly as the page has them, and what each was at 619f092 ("" where there was nothing).
ROUND_6 = {
    "rev_cells": (".rev-t td{padding:7px 8px;border-top:1px solid var(--line-2);color:var(--ink-v)}", ".rev-t td{padding:7px 14px;border-top:1px solid var(--line-2);color:var(--ink-v)}"),
    "mk_cells": (".mk td{padding:7px 8px;border-top:1px solid var(--line-2)}", ".mk td{padding:7px 12px;border-top:1px solid var(--line-2)}"),
    "heads": (".rev-t th,.mk th{padding:6px 8px;text-align:left;font:700 10.5px var(--sans);letter-spacing:.06em;",
              ".rev-t th,.mk th{padding:6px 14px;text-align:left;font:700 10.5px var(--sans);letter-spacing:.06em;"),
    "first": (".rev-t th:first-child,.mk th:first-child,.rev-t td:first-child,.mk td:first-child{padding-left:14px}", ""),
    "last": (".rev-t th:last-child,.mk th:last-child,.rev-t td:last-child,.mk td:last-child{padding-right:14px}", ""),
    "pin": (".rev-t th:nth-child(5),.mk th:nth-child(5),.rev-t td:nth-child(5),.mk td:nth-child(5){position:sticky;right:0}", ""),
    "fill": (".rev-t td:nth-child(5),.mk td:nth-child(5){background:var(--card)}", ""),
    # (150px since round 7, part 2, L4: the pinned column and what a Rate cell holds to the right of a box; round 6 made it the column's 126px)
    "box": (".tscroll{overflow-x:auto;-webkit-overflow-scrolling:touch;max-width:100%;scroll-padding-right:150px}",
            ".tscroll{overflow-x:auto;-webkit-overflow-scrolling:touch;max-width:100%}"),
    "focus": (".tscroll:has(td:nth-child(5):focus-within){scroll-padding-right:0}", ""),
    "rev_table": (".rev-t{width:100%;border-collapse:separate;border-spacing:0;font-size:12.5px}", ".rev-t{width:100%;border-collapse:collapse;font-size:12.5px}"),
    "mk_table": (".mk{width:100%;border-collapse:separate;border-spacing:0;font-size:13px;margin:0}", ".mk{width:100%;border-collapse:collapse;font-size:13px;margin:0}"),
}
AT_619F092 = {
    "min": ".rev-t,.mk{min-width:640px}",
    "qty": ".rev-t th:nth-child(2),.mk th:nth-child(2){width:15%}",
    "unit": ".rev-t th:nth-child(3),.mk th:nth-child(3){width:124px}",
    "rate": ".rev-t th:nth-child(4),.mk th:nth-child(4){width:132px}",
    "total": ".rev-t th:nth-child(5),.mk th:nth-child(5){width:132px}",
    "words": NEW["words"],
}


def _once(page: str, old: str, new: str) -> str:
    assert page.count(old) == 1, "%r appears %d times on the page, not once" % (old, page.count(old))
    return page.replace(old, new)


def page_at_619f092() -> str:
    """The page with every rule round 6 touched put back as it was at 619f092 (the staging walk's page), each anchor required to be on the page exactly once."""
    page = PAGE_PATH.read_text(encoding="utf-8")
    for key, old in NEW.items():
        page = _once(page, old, AT_619F092[key])
    for old, new in ROUND_6.values():
        page = _once(page, old, new)
    return page


def test_the_old_rules_are_found_to_cut_things_off():
    """The page as it was at b14bc98 (its rules for the columns, the minimum and the Unit words), run through the same check: the Total and Unit columns are too narrow at the narrowest table, which is
    the markup card's boxes and words round 5's audit named."""
    page = PAGE_PATH.read_text(encoding="utf-8")
    old = page
    for key, line in NEW.items():
        old = _once(old, line, "")
    old = old.replace("</style>", OLD_RULES + "</style>", 1)
    found = problems(old)
    assert any(p.startswith("Total column") for p in found), found
    assert any(p.startswith("Unit column") for p in found), found


def test_the_page_as_it_was_at_619f092_hides_the_total_column_at_916px_with_the_sidebar_open():
    """The walk's finding, as a permanent test: with every rule round 6 touched put back, the table is 640px in a 575px box, 65px of it (the TOTAL column) are out of view at 916px with the sidebar open,
    and the other four windows the walk recorded hide what it measured. The check names it, and says the Total column is not pinned."""
    old = page_at_619f092()
    f = facts(old)
    assert f["min_width"] == OLD_MIN_WIDTH
    for window, hidden in sorted(WALK.items()):
        assert out_of_view(f, window, True) == hidden, window
    found = problems(old)
    assert any(p.startswith("the Total column is 81px out of view at a window 900px wide (sidebar open, scrollbar 15px)") for p in found), found
    assert any(p.startswith("the table scrolls") and "not pinned" in p for p in found), found
    assert any(p.startswith("pin: ") for p in found), found


MUTATIONS = [
    # (what is undone, the page's own line, what stands there instead, how the problem starts)
    ("the 640px minimum is back", NEW["min"], ".rev-t,.mk{min-width:640px}", "the Total column is"),
    ("the 640px minimum is back, at the walk's window", NEW["min"], ".rev-t,.mk{min-width:640px}", "the table is 640px wide in a 575px box: the last 65px of it, the TOTAL column"),
    ("a minimum under what the columns and Item need", NEW["min"], ".rev-t,.mk{min-width:500px}", "Item column"),
    ("a Quantity column too narrow for its heading", NEW["qty"], ".rev-t th:nth-child(2),.mk th:nth-child(2){width:70px}", "Quantity column"),
    ("the old Unit share", NEW["unit"], ".rev-t th:nth-child(3),.mk th:nth-child(3){width:12%}", "Unit column"),
    ("a Rate column too narrow for its box", NEW["rate"], ".rev-t th:nth-child(4),.mk th:nth-child(4){width:96px}", "Rate column"),
    # round 7, part 4 (P8: the walk's X2): a Rate cell that may not wrap holds "$16.8113 / gallon" on one line, wider than the cell, which runs under the pinned Total column
    ("a Rate cell that may not wrap its unit under its figure", ".rev-t td.rt{white-space:normal;text-wrap:balance}", "", "Rate column is 108px and its contents need 143px"),
    ("a Rate cell told not to wrap after all", ".rev-t td.rt{white-space:normal;text-wrap:balance}", ".rev-t td.rt{white-space:normal;text-wrap:nowrap}", "Rate column"),
    ("the old Total share", NEW["total"], ".rev-t th:nth-child(5),.mk th:nth-child(5){width:14%}", "Total column"),
    ("Unit words that cannot wrap", NEW["words"], ".rev-t td.u,.mk td.u{color:var(--ink-3);white-space:nowrap}", "Unit column"),
    ("the old padding between the Review cells", ROUND_6["rev_cells"][0], ROUND_6["rev_cells"][1], "Unit column"),
    ("the old padding between the markup cells", ROUND_6["mk_cells"][0], ROUND_6["mk_cells"][1], "Unit column"),
    ("the old padding in the headers", ROUND_6["heads"][0], ROUND_6["heads"][1], "Quantity column"),
    ("a wide inset at the card's right edge", ROUND_6["last"][0], ROUND_6["last"][0].replace("padding-right:14px", "padding-right:30px"), "Total column"),
    ("a wide inset at the card's left edge", ROUND_6["first"][0], ROUND_6["first"][0].replace("padding-left:14px", "padding-left:40px"), "Item column"),
    ("the Total cells are not pinned", ROUND_6["pin"][0], ROUND_6["pin"][0].replace("position:sticky", "position:static"), "pin: the Total"),
    ("the Total cells are not pinned, so the Total scrolls out of view below 900px", ROUND_6["pin"][0], ROUND_6["pin"][0].replace("position:sticky", "position:static"), "the table scrolls"),
    ("the Total cells are pinned to the other edge", ROUND_6["pin"][0], ROUND_6["pin"][0].replace("right:0", "left:0"), "pin: the Total"),
    ("the pinned Total cells have no background", ROUND_6["fill"][0], ROUND_6["fill"][0].replace("background:var(--card)", "background:transparent"), "pin: a pinned Total cell"),
    ("no scroll padding for the pinned column", ROUND_6["box"][0], ROUND_6["box"][1], "pin: the .tscroll box"),
    ("a scroll padding narrower than the pinned column", ROUND_6["box"][0], ROUND_6["box"][0].replace("scroll-padding-right:150px", "scroll-padding-right:60px"), "pin: the .tscroll box"),
    # round 7, part 2 (L4): the round-6 padding, as wide as the pinned column alone, leaves the % after a box and the refusal's line under the column
    ("the round-6 scroll padding, the pinned column's width alone", ROUND_6["box"][0], ROUND_6["box"][0].replace("scroll-padding-right:150px", "scroll-padding-right:126px"),
     "refusal: the .tscroll box has scroll-padding-right 126px"),
    ("a scroll padding that leaves a phone's box no room for a % box's line", ROUND_6["box"][0], ROUND_6["box"][0].replace("scroll-padding-right:150px", "scroll-padding-right:260px"),
     "refusal: at a window"),
    ("scroll padding while focus is in the pinned column", ROUND_6["focus"][0], ROUND_6["focus"][0].replace("scroll-padding-right:0", "scroll-padding-right:126px"), "pin: the .tscroll box keeps"),
    ("collapsed borders on the Review tables", ROUND_6["rev_table"][0], ROUND_6["rev_table"][1], "pin: the .rev-t table"),
    ("collapsed borders on the markup table", ROUND_6["mk_table"][0], ROUND_6["mk_table"][1], "pin: the .mk table"),
    ("a card with no tint of its own", '.rev[data-rev="travel"]{--rev-band:var(--rev-travel-band);--rev-tot:var(--rev-travel-tot)}',
     '.rev[data-rev="travel"]{--rev-band:var(--rev-travel-band)}', "pin: the travel card"),
    ("a pinned Total column that eats the box", NEW["total"], ".rev-t th:nth-child(5),.mk th:nth-child(5){width:200px}", "the pinned Total column leaves"),
    ("a box that does not scroll", ROUND_6["box"][0], ROUND_6["box"][0].replace("overflow-x:auto", "overflow-x:visible"), "the .tscroll box does not scroll sideways"),
    # the box's width is read off the page's own layout: change the layout and the arithmetic moves with it
    ("a section body padded 40px a side", ".sec-b{padding:18px 19px}", ".sec-b{padding:18px 40px}", "the Total column is"),
    ("a page padded 50px a side", "padding:0 22px calc(var(--bid-h,132px) + 24px)}", "padding:0 50px calc(var(--bid-h,132px) + 24px)}", "the Total column is"),
    ("a page column capped at 560px", ".wrap{max-width:1000px;margin:0 auto}", ".wrap{max-width:560px;margin:0 auto}", "the Total column is"),
]


@pytest.mark.parametrize("what,anchor,undone,starts", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_each_rule_of_the_fix_is_needed(tmp_path, what, anchor, undone, starts):
    """Put ONE rule back as it was (or make it wrong) in a copy of the page: the check finds it, and says which kind of fault it is. break_source refuses an anchor that is not on the page exactly once,
    so none of these can pass by applying nowhere."""
    frontend = break_source(tmp_path, "polish-estimate.html", anchor, undone)
    found = problems((frontend / "polish-estimate.html").read_text(encoding="utf-8"))
    assert found, "the check did not notice: %s" % what
    assert any(p.startswith(starts) for p in found), (what, found)


# ── the warning rules, and what each one undone is found to do (round 6 audit, U1) ───────────────────────────────────────────
WARN_BOX = ".adjbox{display:inline-flex;flex-wrap:wrap;justify-content:flex-end;align-items:center;gap:4px;white-space:nowrap}"
WARN_TEXT = ".adjwarn{display:block;flex:1 0 100%;white-space:normal;overflow-wrap:anywhere;color:var(--red);font:600 11.5px var(--sans);text-align:right;max-width:none}"
# the two rules as they stood until round 6's audit: a nowrap row with the warning in it, and a warning capped at 220px
OLD_WARN_BOX = ".adjbox{display:inline-flex;align-items:center;gap:4px;white-space:nowrap}"
OLD_WARN_TEXT = ".adjwarn{display:block;white-space:normal;color:var(--red);font:600 11.5px var(--sans);text-align:right;max-width:220px}"

WARNING_MUTATIONS = [
    # (what is undone, the page's own line, what stands there instead, how the first finding starts)
    ("the old .adjbox rule is back: one nowrap row", WARN_BOX, OLD_WARN_BOX, "warning: .adjbox does not wrap"),
    ("the old .adjwarn rule is back: no line of its own", WARN_TEXT, OLD_WARN_TEXT, "warning: .adjwarn has a flex-basis"),
    ("a row that is told not to wrap", WARN_BOX, WARN_BOX.replace("flex-wrap:wrap", "flex-wrap:nowrap"), "warning: .adjbox does not wrap"),
    ("a box that is not a flex row at all", WARN_BOX, WARN_BOX.replace("inline-flex", "inline-block"), "warning: .adjbox is display:inline-block"),
    ("a box that jumps left when a warning appears", WARN_BOX, WARN_BOX.replace("justify-content:flex-end;", ""), "warning: .adjbox does not keep its first line"),
    ("a warning that shares the box's line", WARN_TEXT, WARN_TEXT.replace("flex:1 0 100%", "flex:0 1 auto"), "warning: .adjwarn has a flex-basis of auto"),
    ("a warning with a basis of a fraction of the line", WARN_TEXT, WARN_TEXT.replace("flex:1 0 100%", "flex-basis:50%"), "warning: .adjwarn has a flex-basis of 50%"),
    ("a warning that cannot wrap", WARN_TEXT, WARN_TEXT.replace("white-space:normal", "white-space:nowrap"), "warning: .adjwarn has white-space:nowrap"),
    ("a warning that may not break a long word", WARN_TEXT, WARN_TEXT.replace("overflow-wrap:anywhere;", ""), "warning: .adjwarn may not break a long word"),
    ("a warning capped narrower than its cell", WARN_TEXT, WARN_TEXT.replace("max-width:none", "max-width:60px"), "warning: .adjwarn is capped at 60px"),
]


def test_the_old_warning_rules_are_found_to_run_under_the_pinned_column():
    """Both rules as they stood together (the nowrap row and the 220px warning): the check names the row that does not wrap AND the warning that has no line of its own."""
    page = PAGE_PATH.read_text(encoding="utf-8")
    old = _once(_once(page, WARN_BOX, OLD_WARN_BOX), WARN_TEXT, OLD_WARN_TEXT)
    found = warning_problems(old)
    assert any(p.startswith("warning: .adjbox does not wrap") for p in found), found
    assert any(p.startswith("warning: .adjwarn has a flex-basis of auto") for p in found), found
    assert any(p.startswith("warning: .adjwarn may not break") for p in found), found


@pytest.mark.parametrize("what,anchor,undone,starts", WARNING_MUTATIONS, ids=[m[0] for m in WARNING_MUTATIONS])
def test_each_rule_of_the_warning_fix_is_needed(tmp_path, what, anchor, undone, starts):
    """Put ONE of the two warning rules back as it was (or make one declaration of it wrong) in a copy of the page: warning_problems finds it and says which kind of fault it is. break_source refuses an
    anchor that is not on the page exactly once, so none of these can pass by applying nowhere."""
    frontend = break_source(tmp_path, "polish-estimate.html", anchor, undone)
    found = warning_problems((frontend / "polish-estimate.html").read_text(encoding="utf-8"))
    assert found, "the check did not notice: %s" % what
    assert any(p.startswith(starts) for p in found), (what, found)
