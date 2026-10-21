"""THE PAGE KEEPS ITS LAST ROW CLEAR OF THE FIXED TOTAL BAR, WHATEVER THE BAR'S HEIGHT (the 2026-10-20 audit of the sixth round, item U2).

WHAT WAS WRONG. `#bidbar` (polish-estimate.html, `.bid`) is `position: fixed; bottom: 0`, so it takes no room in the page. The page keeps its last row, the step's Back / Next row, above it with the
body's `padding-bottom`, which was a fixed 132px. The bar is not a fixed height: with the staff sidebar open it is narrower than the window by the rail's width, and its sums, its note and its total
wrap onto a second row. Measured in Chrome driving the real page on 2026-10-21 (one copied sheet, so the sums are a long line; the sidebar open): the bar was 84px tall from 1100px up, 120px from
770 to 900px, 154px at 1000px, and 189px at 700px (below the 768px at which the rail appears: the bar has the whole window and still wraps). Scrolled to its end, the page left the Back / Next row 21px UNDER the bar at 1000px and 56px under it at 700px.

THE FIX, two halves that have to agree on one property:
  * js/polish-estimate.js reads the bar's height off the bar and writes it onto the html element as `--bid-h`, as the sticky head's is written as `--v2head-h`: a ResizeObserver says when it changes (an
    open sidebar changes the bar's width and fires no window resize), a browser without one is told by every repaint of the bar and by the window's resize, a page with no layout (the harnesses'
    stand-in DOM) has no box to measure and nothing happens, and a bar with no height (hidden, or not laid out yet) leaves the last good figure.
  * polish-estimate.html: `body { padding-bottom: calc(var(--bid-h, 132px) + 24px) }`, the bar's height and 24px of air above it, and the old 132px plus the air until the bar has been measured.

HOW IT IS CHECKED. The CSS is read: the body's bottom padding must be the bar's height and a margin, for every height the bar has been seen at and one more row than any of them, and it must read the
property the page script writes. The script is EXECUTED (tests/js/bid-bar-height-harness.js boots the whole of js/polish-estimate.js on a stand-in DOM and gives the bar a box): what is read back is the
custom property the page wrote, with a ResizeObserver, without one, and with no layout at all. A headless run lays nothing out, so how tall the bar really is at a given width is not checked here; the
heights above are what a browser measured, and the walk on staging checks the rest.

The last blocks put each rule and each line of the script back as it was, or make it wrong, in a COPY of the page, and require the check to find it: a check that has never failed proves nothing.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "bid-bar-height-harness.js"
PAGE_PATH = FRONTEND / "polish-estimate.html"
JS_PATH = FRONTEND / "js" / "polish-estimate.js"
PAGE_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js",
              "js/markup-core.js", "js/library-core.js", "js/library-picker.js", "js/work-types.js", "js/excel-math.js",
              "js/epoxy-takeoff.js", "js/gyp-takeoff.js", "js/seal-takeoff.js", "js/price-lines-core.js"]

PROPERTY = "--bid-h"            # what the CSS reads and the script writes
OLD_RESERVE = 132               # the fixed bottom padding the page had: until the bar is measured it must reserve at least this much
AIR = 16                        # at least this much of the page must show between its last row and the bar
# The bar's height in px: one row (84), what Chrome measured on the real page (120, 154, 189), the audit's two ends (123, 157), and a row taller than any of them.
BAR_HEIGHTS = (84, 120, 123, 154, 157, 189, 260)


# ── reading the page's CSS ───────────────────────────────────────────────────────────────────────────────
def length(value: str, variables: dict) -> float:
    """A length in px: `132px`, `var(--x,40px)`, `calc(var(--x,40px) + 24px)`; var() takes its fallback when the property is not in `variables`."""
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


def body_bottom_padding(page: str) -> str:
    """The body's bottom padding as the page's own CSS declares it: the third value of a `padding` shorthand, or a `padding-bottom`, whichever comes last."""
    style = page[page.index("<style>") + len("<style>"):page.index("</style>")]
    css = re.sub(r"\s+", " ", re.sub(r"/\*.*?\*/", "", style, flags=re.S))
    value = None
    for rule in re.findall(r"(?:^|[}\s])body ?\{([^}]*)\}", css):
        for decl in rule.split(";"):
            if ":" not in decl:
                continue
            prop, val = (s.strip() for s in decl.split(":", 1))
            if prop == "padding":
                parts = re.findall(r"calc\((?:[^()]|\([^()]*\))*\)|\S+", val)
                value = parts[2] if len(parts) >= 3 else parts[0]
            elif prop == "padding-bottom":
                value = val
    assert value is not None, "the body has no bottom padding"
    return value


def reserve(value: str, bar_height) -> float:
    """What the body's bottom padding comes to when the page has written `--bid-h` as `bar_height` px (None: it has not measured the bar yet)."""
    return length(value, {} if bar_height is None else {PROPERTY: "%spx" % bar_height})


def css_problems(page: str, js: str) -> list[str]:
    """Does the page reserve the bar's height and some air, following the bar one for one, in the property the script writes, and no less than it did before until the bar is measured?"""
    value = body_bottom_padding(page)
    names = re.findall(r"var\(\s*(--[\w-]+)", value)
    found = []
    if names != [PROPERTY]:
        found.append("css: the body's bottom padding is %r, which reads %s, not %s: it cannot follow the bar's height" % (value, names or "no custom property", PROPERTY))
        return found
    for h in BAR_HEIGHTS:
        room = reserve(value, h) - h
        if room < AIR:
            found.append("css: with the bar %dpx tall the page reserves %dpx, which leaves %dpx above the bar, under the %dpx of air its last row needs" % (h, reserve(value, h), room, AIR))
    if reserve(value, 200) - reserve(value, 100) != 100:
        found.append("css: the reserve does not follow the bar's height one for one (%dpx at 100px, %dpx at 200px)" % (reserve(value, 100), reserve(value, 200)))
    if reserve(value, None) < OLD_RESERVE:
        found.append("css: until the page has measured the bar it reserves %dpx, under the %dpx it reserved before" % (reserve(value, None), OLD_RESERVE))
    if 'setProperty("%s"' % PROPERTY not in js:
        found.append("js: nothing in the page script writes %s" % PROPERTY)
    return found


# ── running the page ─────────────────────────────────────────────────────────────────────────────────────
def run_page(frontend=FRONTEND):
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    require_node()
    return run_page()


def fact(r, *path):
    """r[path...], or None when any step is missing: a scenario that failed outright leaves no such fact, and a mutation's check must read that as 'noticed', not as an error of its own."""
    for key in path:
        if not isinstance(r, dict) or key not in r:
            return None
        r = r[key]
    return r


# ── the assertions ───────────────────────────────────────────────────────────────────────────────────────
def test_the_resolver_reads_the_pages_own_padding_rule():
    """The check is only worth believing if it reads what the page says: the old shorthand, the new one with a calc() and a fallback, and a padding-bottom that comes later and wins."""
    old = "<style>body{margin:0;padding:0 22px 132px}</style>"
    new = "<style>body{margin:0;font:400 14px/1.55 var(--sans);\n  padding:0 22px calc(var(--bid-h,132px) + 24px)}</style>"
    later = "<style>body{padding:0 22px 132px}\nbody{padding-bottom:calc(var(--bid-h,10px) + 5px)}</style>"
    assert body_bottom_padding(old) == "132px" and reserve("132px", 400) == 132
    assert body_bottom_padding(new) == "calc(var(--bid-h,132px) + 24px)"
    assert reserve(body_bottom_padding(new), 154) == 178 and reserve(body_bottom_padding(new), None) == 156
    assert reserve(body_bottom_padding(later), 100) == 105 and reserve(body_bottom_padding(later), None) == 15


def test_the_page_reserves_the_bars_height_and_some_air_in_the_property_the_script_writes():
    """The body's bottom padding is `calc(var(--bid-h, 132px) + 24px)`: at every height the bar has been seen at (84px for a row, 120, 154 and 189px as Chrome measured them, the audit's 123 and 157) and
    one row taller, it leaves the Back / Next row at least 16px clear above the bar; it follows the bar one for one; and until the bar has been measured it reserves no less than the 132px it did.

    Mutation: the old fixed 132px; a fixed 300px; the bar's height and no air, and less air than the row needs; a reserve that reads another property; a fallback of nothing."""
    assert css_problems(PAGE_PATH.read_text(encoding="utf-8"), JS_PATH.read_text(encoding="utf-8")) == []


def test_a_resize_observer_on_the_bar_writes_its_height_rounded_up_to_the_property_the_padding_reads(ran):
    """With a ResizeObserver the page watches #bidbar (and only the observer measures: the page's own drawing of the bar, and a repaint, leave the property alone), writes the height rounded up, and
    leaves the last good figure when the bar has no height. No window resize listener of the bar's own alongside the observer.

    Mutation: the bar is not observed; its height is never written; rounded down; a bar with no height wipes the last figure; the window's resize is listened to as well; a repaint measures too."""
    o = ran["observed"]
    assert o["watched"] == {"observers": 1, "targets": [["bidbar"]], "resizeListeners": 0}
    assert o["heights"] == {"idle": "", "afterRepaint": "", "first": "120px", "second": "151px", "none": "151px"}


def test_a_browser_with_no_resize_observer_is_told_by_every_repaint_of_the_bar_and_by_the_windows_resize(ran):
    """The bar's first drawing writes the height, and so does a repaint through the job bid (a bid of several sheets draws the bar another way, after an early return), each AFTER the words are in
    the bar: the stand-in bar is 60px and a pixel for every character it says, so a bar measured before it is painted reads 60px. The window's resize writes it too, from one resize listener
    of the bar's own; a bar with no height leaves it; a document with no html element is no error.

    Mutation: a repaint does not tell the page; the bar is measured before its words are written; a resize is never listened to; no html element throws."""
    p = ran["plain"]
    assert p["single"]["painted"] == "%dpx" % (60 + p["single"]["mathsLen"]) and p["single"]["mathsLen"] > 0
    assert p["job"]["mathsLen"] > p["single"]["mathsLen"], "the job bid says more than the single sheet's, which is what makes this a different branch"
    assert p["job"]["painted"] == "%dpx" % (60 + p["job"]["mathsLen"])
    assert p["resized"] == "189px" and p["none"] == "189px"
    assert p["listeners"] == 1
    assert p["noRoot"] is True


def test_a_page_with_no_layout_writes_nothing_and_breaks_nothing(ran):
    """The stand-in DOM every other harness has gives the bar no box: opening the bid, repainting it and a window resize write no property and throw nothing."""
    assert ran["noLayout"] == {"value": "", "threw": False}


# ── red without the code ─────────────────────────────────────────────────────────────────────────────────
OBSERVE = "      try { barObserver = new RO(syncBarHeight); barObserver.observe(bar); } catch (err) { barObserver = null; }"
WRITE = '    if (bh > 0) root.style.setProperty("--bid-h", bh + "px");'
CEIL = '    var bh = box && typeof box.height === "number" ? Math.ceil(box.height) : 0;'
LISTEN = '    if (!barObserver) window.addEventListener("resize", syncBarHeight);'
REPAINT = "    if (!barObserver) syncBarHeight();"
GUARD = '    if (!bar || !root || !root.style || typeof root.style.setProperty !== "function" || typeof bar.getBoundingClientRect !== "function") return;'

BREAKS = {
    "the bar is not observed": (
        "js/polish-estimate.js", OBSERVE, "      barObserver = null;",
        lambda r: fact(r, "observed", "watched", "observers") != 1 or fact(r, "observed", "heights", "first") != "120px"),
    "the bar's height is never written": (
        "js/polish-estimate.js", WRITE, "    void bh;",
        lambda r: fact(r, "observed", "heights", "first") != "120px" or fact(r, "plain", "single", "painted") != "%dpx" % (60 + (fact(r, "plain", "single", "mathsLen") or 0))),
    "the bar's height is rounded down": (
        "js/polish-estimate.js", CEIL, '    var bh = box && typeof box.height === "number" ? Math.floor(box.height) : 0;',
        lambda r: fact(r, "observed", "heights", "second") != "151px"),
    "a bar with no height wipes the last one": (
        "js/polish-estimate.js", WRITE, '    root.style.setProperty("--bid-h", bh + "px");',
        lambda r: fact(r, "observed", "heights", "none") != "151px" or fact(r, "plain", "none") != "189px"),
    "the window's resize is listened to even with an observer": (
        "js/polish-estimate.js", LISTEN, '    window.addEventListener("resize", syncBarHeight);',
        lambda r: fact(r, "observed", "watched", "resizeListeners") != 0),
    "a browser without an observer is never told of a resize": (
        "js/polish-estimate.js", LISTEN, "    void 0;",
        lambda r: fact(r, "plain", "resized") != "189px" or fact(r, "plain", "listeners") != 1),
    "a repaint does not tell a browser without an observer": (
        "js/polish-estimate.js", REPAINT, "    void 0;",
        lambda r: fact(r, "plain", "single", "painted") != "%dpx" % (60 + (fact(r, "plain", "single", "mathsLen") or 0)) or fact(r, "plain", "job", "painted") != "%dpx" % (60 + (fact(r, "plain", "job", "mathsLen") or 0))),
    "a repaint measures the bar even with an observer": (
        "js/polish-estimate.js", REPAINT, "    syncBarHeight();",
        lambda r: fact(r, "observed", "heights", "idle") != "" or fact(r, "observed", "heights", "afterRepaint") != ""),
    "a document with no html element throws": (
        "js/polish-estimate.js", GUARD, '    if (!bar || typeof bar.getBoundingClientRect !== "function") return;',
        lambda r: fact(r, "plain", "noRoot") is not True),
    "a bar with no box throws": (
        "js/polish-estimate.js", GUARD, '    if (!bar || !root || !root.style || typeof root.style.setProperty !== "function") return;',
        lambda r: fact(r, "noLayout") != {"value": "", "threw": False}),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_checks_go_red_when_the_script_changes(tmp_path, name):
    """Make one line of the page script wrong in a COPY of the page (break_source refuses an anchor that is not on the page exactly once) and require a fact of the run to notice."""
    require_node()
    rel, old, new, noticed = BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, PAGE_FILES)
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the harness itself crashed on the copy, which proves nothing about what it noticed:\n" + proc.stderr
    assert noticed(last_json_line(proc.stdout)), "the checks did not notice: " + name


def test_the_bar_is_measured_after_its_words_are_written_not_before(tmp_path):
    """The two lines of paintBid swapped (the bar measured, then painted): the stand-in bar is as tall as the words it holds, so the first drawing is measured while the bar is empty and the property
    reads 60px, and the job bid's repaint is measured with the single sheet's words in it."""
    require_node()
    frontend = break_source(tmp_path, "js/polish-estimate.js", "    paintBidFigures();", "    if (!barObserver) syncBarHeight();\n    paintBidFigures();")
    page = (frontend / "js" / "polish-estimate.js").read_bytes().decode("utf-8")
    assert page.count(REPAINT) == 2, "the swap needs the measuring line to be on the page once more, after the painting line"
    first = page.index(REPAINT) + len(REPAINT)
    page = page[:first] + page[first:].replace(REPAINT, "    void 0;", 1)
    (frontend / "js" / "polish-estimate.js").write_bytes(page.encode("utf-8"))
    copy_unmodified(frontend, PAGE_FILES)
    p = run_page(frontend)["plain"]
    assert p["single"]["painted"] != "%dpx" % (60 + p["single"]["mathsLen"]), p
    assert p["job"]["painted"] != "%dpx" % (60 + p["job"]["mathsLen"]), p


# ── the CSS: each rule undone ────────────────────────────────────────────────────────────────────────────
NEW_PADDING = "padding:0 22px calc(var(--bid-h,132px) + 24px)}"
OLD_PADDING = "padding:0 22px 132px}"

CSS_MUTATIONS = [
    # (what is undone, the page's own text, what stands there instead, how the first finding starts)
    ("the old fixed 132px is back", NEW_PADDING, OLD_PADDING, "css: the body's bottom padding is '132px'"),
    ("a fixed reserve bigger than the tallest bar seen", NEW_PADDING, "padding:0 22px 300px}", "css: the body's bottom padding is '300px'"),
    ("the bar's height and no air", NEW_PADDING, NEW_PADDING.replace("+ 24px", "+ 0px"), "css: with the bar 84px tall"),
    ("less air than the last row needs", NEW_PADDING, NEW_PADDING.replace("+ 24px", "+ 8px"), "css: with the bar 84px tall"),
    ("a reserve that reads another property", NEW_PADDING, NEW_PADDING.replace("--bid-h", "--bar-h"), "css: the body's bottom padding"),
    ("a reserve of nothing until the bar is measured", NEW_PADDING, NEW_PADDING.replace("132px", "0px"), "css: until the page has measured the bar it reserves 24px"),
]


@pytest.mark.parametrize("what,anchor,undone,starts", CSS_MUTATIONS, ids=[m[0] for m in CSS_MUTATIONS])
def test_each_part_of_the_padding_rule_is_needed(tmp_path, what, anchor, undone, starts):
    """Put the old padding back, or make one part of the new one wrong, in a COPY of the page: the check finds it and says which kind of fault it is."""
    frontend = break_source(tmp_path, "polish-estimate.html", anchor, undone)
    found = css_problems((frontend / "polish-estimate.html").read_text(encoding="utf-8"), JS_PATH.read_text(encoding="utf-8"))
    assert found, "the check did not notice: %s" % what
    assert found[0].startswith(starts), (what, found)


def test_a_script_that_never_writes_the_property_is_found(tmp_path):
    """The CSS reads --bid-h, so the script must write it: in a copy with the write taken out of the source, the check names the missing writer."""
    frontend = break_source(tmp_path, "js/polish-estimate.js", WRITE, '    root.style.setProperty("--bid-height", bh + "px");')
    found = css_problems(PAGE_PATH.read_text(encoding="utf-8"), (frontend / "js" / "polish-estimate.js").read_text(encoding="utf-8"))
    assert found == ["js: nothing in the page script writes --bid-h"], found
