"""How a polish estimator gets from Estimate Review into the polish beta.

THE HISTORY, BECAUSE BOTH HALVES OF IT ARE STILL TRUE AT THE SAME TIME.

A pink banner used to invite the estimator into the beta from the top of this page. It cost about
60px on the one screen that IS a spreadsheet, and Hanz killed it on 2026-08-07: "remove this
please I can barely see the sheet. The Estimate sheet is supposed to be the majority viewport."
test_polish_estimate_page.py::test_nothing_is_advertised_above_the_estimate_grid is what keeps
that space clear, and this file must not become the loophole in it.

Removing it left the sidebar as the only door, so the journey itself never reached the beta.
2026-08-11: "I have a question for the polish estimate in beta does why is it when I click intake
and then proceed to estimate it doesnt lead me to the Estimate sheet in beta? instead it leads me
to the excel sheet still" ... "The current polish excel sheet and the beta shuold be two different
workflows okay?"

So Continue keeps belonging to the spreadsheet workflow, and the beta gets a small link in the
toolbar row that already exists. Both constraints at once: reachable from this screen, zero
vertical space taken from the grid.

WHAT EACH TEST IS HERE FOR. Four separate defects were found in this beta in one day, every one
by opening it in a browser, every one green in CI first. These are the failure modes of a link
that cannot be seen from a test run:

  * It drifts above the toolbar and becomes the banner again.
  * It shows on epoxy jobs, where there is no beta page to send anyone to. `hidden` alone does
    not do it: .beta-link sets display:inline-flex, which outranks the attribute.
  * It loses the ?d= draft id and the beta opens with no project, looking broken. The banner
    shipped that exact bug in its first version, and shared.js's anchor rewriter does NOT cover
    /polish-estimate.html (_WIZARD_PATH is the four wizard pages only).
  * The copy implies the bid continues over there. It does not: on a real project the beta takes
    a TEST COPY, filed under the Test tab, per Hanz's "Make a test copy, leave the real bid
    alone" and his 2026-08-07 rule about never testing on a live Active project.
  * The door waits on the workbook. init() awaits /api/sheets plus every sheet before it reaches
    step 4b, where the banner used to be unhidden, so a failed load meant no door at all.
"""
import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"


@pytest.fixture()
def html():
    return (FRONTEND / "estimate-review.html").read_text(encoding="utf-8")


@pytest.fixture()
def anchor(html):
    """The whole <a id="polish-beta-link" ...>...</a> element, attributes and copy."""
    m = re.search(r'<a id="polish-beta-link".*?</a>', html, re.S)
    assert m, "the beta link is gone from estimate-review.html"
    return m.group(0)


def _code() -> str:
    """estimate-review.js with `//` comment lines stripped.

    The comments in that file quote the bug they describe (banner, viewport, withDraft), so a raw
    grep matches its own prose and passes on the story instead of the code.
    """
    src = (FRONTEND / "js" / "estimate-review.js").read_text(encoding="utf-8")
    return "\n".join(l for l in src.splitlines() if not l.strip().startswith("//"))


def _block(fn: str) -> str:
    """The body of the top-level `function fn(...)` in js/estimate-review.js.

    Brace-counted, not regex'd: this file is 3600 lines of template literals and a `{` inside one
    of them would truncate the block and make every assertion below it vacuous. Function-scoped
    because a whole-file grep for "withDraft" passes on any of the dozen other calls to it.
    """
    src = _code()
    m = re.search(r"\n(?:async\s+)?function " + re.escape(fn) + r"\s*\(", src)
    assert m, "%s() is gone from estimate-review.js. Rewrite these tests, do not delete them." % fn
    i = src.index("{", m.end())
    depth, j = 0, i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
        j += 1
    pytest.fail("unbalanced braces reading %s() in estimate-review.js" % fn)


def _text(markup: str) -> str:
    """Visible copy only: attributes and tags stripped, whitespace collapsed."""
    inner = markup[markup.index(">") + 1:]
    return " ".join(re.sub(r"<[^>]+>", " ", inner).split())


# ── where it sits ─────────────────────────────────────────────────────────────
def test_the_link_is_inline_in_the_toolbar_row(html, anchor):
    """Kills: moving the link out of .top-toolbar into a row of its own.

    Anywhere but this row costs the grid height, which is the one thing it was allowed to do.
    """
    toolbar = html.index('<div class="top-toolbar">')
    tabs = html.index('<div class="xl-tab-bar full"')
    at = html.index(anchor)
    assert toolbar < at < tabs, (
        "the beta link is outside the toolbar row; anywhere else on this page takes vertical "
        "space off the estimate grid")


def test_the_toolbar_is_still_the_first_thing_inside_main(html):
    """Kills: slipping any element between <main> and the toolbar.

    Stronger than the banner-name regex it backs up: it does not matter what the next feature
    calls its element, nothing gets to sit on top of the grid.
    """
    gap = html[html.index("<main>") + len("<main>"):html.index('<div class="top-toolbar">')]
    gap = re.sub(r"<!--.*?-->", "", gap, flags=re.S)
    assert not re.search(r"<\w", gap), (
        "something was inserted above the toolbar: %r" % gap.strip()[:120])


def test_the_no_banner_rule_still_holds():
    """Re-asserts test_polish_estimate_page's condition from this side.

    That test guards the space; this one exists so a future banner cannot arrive as part of the
    beta-link markup and be nobody's regression. Same shapes it looks for: a div/section/aside
    whose id reads like an advertisement, plus the removed banner being unhidden again.
    """
    html = (FRONTEND / "estimate-review.html").read_text(encoding="utf-8")
    body = html[html.index("<main>"):]
    banner = re.search(r'<(div|section|aside)[^>]*\bid="[^"]*(banner|promo|announce|beta)[^"]*"',
                       body, re.I)
    assert not banner, (
        "something is advertising itself above the grid again: %s" % (banner and banner.group(0)))
    assert "polish-beta-banner" not in _code(), "the removed banner is back"


# ── who sees it ───────────────────────────────────────────────────────────────
def test_the_link_ships_hidden_and_polish_is_what_unhides_it(html, anchor):
    """Kills: dropping the `hidden` attribute, and dropping the work_type check.

    Order matters as much as presence: the check has to come BEFORE hidden is cleared, or every
    epoxy bid gets a door to a page that cannot price it.
    """
    assert re.search(r"\bhidden\b", anchor.split(">")[0]), (
        "the beta link is not hidden in the markup, so it shows on epoxy and gyp jobs before any "
        "script runs")
    block = _block("offerPolishBeta")
    assert '"polish"' in block and "work_type" in block, (
        "offerPolishBeta() no longer looks at the work type")
    assert block.index('"polish"') < block.index("hidden = false"), (
        "the link is unhidden before the work type is checked")


def test_the_hidden_attribute_is_not_beaten_by_the_display_rule(html):
    """Kills: deleting `.top-toolbar .beta-link[hidden] { display: none; }`.

    .beta-link is display:inline-flex so the row can hold it; an explicit display beats the
    hidden attribute, and the link would be visible on every job in the app.
    """
    style = html[html.index("<style>"):html.index("</style>")]
    assert "display: inline-flex" in style[style.index(".top-toolbar .beta-link {"):], (
        "these assertions assume the link is laid out with an explicit display; re-check them")
    assert re.search(r"\.top-toolbar \.beta-link\[hidden\]\s*\{[^}]*display:\s*none",
                     style), (
        "nothing re-hides the link, so display:inline-flex overrides its hidden attribute")


# ── where it goes ─────────────────────────────────────────────────────────────
def test_the_link_carries_the_draft_id(anchor):
    """Kills: assigning link.href a bare path.

    shared.js appends ?d= only to /estimate-review, /proposal-review, /done, /dropbox and
    /info-sheet (_WIZARD_PATH). /polish-estimate.html is not on that list, so a literal href
    opens the beta with no project.
    """
    block = _block("offerPolishBeta")
    assert 'TW.withDraft("/polish-estimate.html")' in block, (
        "the beta link's href does not go through TW.withDraft, so it drops the draft id")
    assert not re.search(r'\.href\s*=\s*[\'"]', block), (
        "the href is being set to a literal string somewhere in offerPolishBeta()")
    assert 'href="/polish-estimate.html"' in anchor, (
        "the markup fallback href changed; it is what a no-JS/failed-script visit follows")


def test_the_door_does_not_wait_on_the_workbook_load():
    """Kills: moving the call back inside init(), where the banner was unhidden at step 4b.

    init() awaits /api/sheets and then every sheet in the workbook. That is seconds on a good day
    and never on a bad one, and this link needs none of it.
    """
    assert "offerPolishBeta()" not in _block("init"), (
        "the beta link is wired from init(), so it appears late or not at all when the workbook "
        "load is slow or fails")
    assert re.search(r"^offerPolishBeta\(\);", _code(), re.M), (
        "offerPolishBeta() is never called at the top level")


# ── what it says ──────────────────────────────────────────────────────────────
def test_the_copy_says_it_opens_a_test_copy(anchor):
    """Kills: "Try it" style copy, or anything reading as "continue this bid over there".

    The beta does not edit a real project, it copies it: "Make a test copy, leave the real bid
    alone." An estimator who thinks their numbers are going into this bid will lose an afternoon
    finding out they went into a test one.
    """
    copy = _text(anchor)
    assert "test copy" in copy.lower(), (
        "the link does not say it opens a test copy: %r" % copy)
    assert "continue" not in copy.lower(), (
        "the copy reads as continuing this bid in the beta, which is not what happens: %r" % copy)
    title = re.search(r'title="([^"]*)"', anchor).group(1)
    assert "TEST COPY" in title and "leaves this bid" in title, (
        "the title attribute does not explain what the test copy means for the real bid: %r" % title)
    assert "—" not in anchor, "em dash in UI copy (house rule)"


def test_the_link_is_marked_beta_the_way_the_sidebar_marks_its_own(anchor):
    """Kills: dropping the BETA tag.

    Polish Estimate and Item Library both carry it in auth.js's navItem, and both doors into the
    beta should read the same way. An unmarked link reads as a finished feature.

    The two doors go to different STEPS on purpose — the sidebar opens the beta intake (step 1),
    this one opens the calculator directly, because by the time somebody is looking at Estimate
    Review the project already exists. What they must agree on is the marking.
    """
    assert ">BETA<" in anchor, "the toolbar link is not marked BETA"
    auth = (FRONTEND / "auth.js").read_text(encoding="utf-8")
    i = auth.index('navItem("/polish-intake.html"')
    assert "BETA" in auth[i:i + 120], (
        "the sidebar entry lost its BETA tag; the two doors should agree")
