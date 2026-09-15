"""The price on the Files page's generated card, and the guarantee that it is the right one.

Hanz, 2026-09-15: "In the Files can we put the Lump sum total in this Proposal generated as well?
Just to give them an idea of how much it costs before sending out."

The pre-generate card has always carried the figure. The generated one never did — so the last
thing an estimator saw before pressing Generate was the price, and the first thing after it was
three download buttons and no number at all.

WHY THIS IS MORE THAN ONE ASSERTION ABOUT A `<span>`.

`state.generate_result` is persisted on the draft and never cleared, and done.js's mode decider is
`else if (res) showPostGenerate(res)` — so a project generated once lands straight back on the
PREVIOUS downloads and never rebuilds. proposal-review.js's Continue drops the result only when the
cover letter changed, and says so in its own comment: "The same staleness still applies to a price
or a note edited after a generate; that is pre-existing, wider than this fix, and worth its own
round."

This is that round, because the ask turns the latent bug into a stated one. A card that names a
price beside files built from a different price is the same sentence that has burned this page
twice already — GenerateOut's own comment spells it out: "the warning's input was not the input the
document is built from", and every one of those five defects failed in the under-reporting
direction, which is the one that reaches a customer.

So the figure the document was ACTUALLY filled with is stamped beside the result at generate time,
and a disagreement routes the estimator to a live Generate button instead of to downloads that are
quietly out of date. That also fixes the pre-existing half: before this, an estimator could edit a
price, return to Files, and download and send a proposal carrying the old one.

EXECUTED, NOT READ. Every assertion below runs the shipped function bodies — see the harness
header. Source-text assertions cannot tell a working page from one that throws on an unbound
identifier, and this file exists because that distinction once took prod down.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "files-lump-sum-harness.js"
DONE_HTML = (FRONTEND / "done.html").read_text(encoding="utf-8")

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── reading money ────────────────────────────────────────────────────────────
@needs_node
def test_a_dash_is_not_a_price_of_zero(ran):
    """THE DEFECT THIS CAUGHT, before it shipped. Stripping non-numerics out of "—" leaves the
    empty string, and `Number("")` is 0 — finite, and completely wrong. The first version of this
    parser returned that 0, which meant the card rendered an em dash as "$0.00" and the staleness
    check read an unpriced draft as a price that had moved to zero.

    Both failure modes are the expensive direction: a $0.00 on the one card an estimator checks a
    price on, and a spurious "regenerate" on every unpriced draft.

    Mutation: drop the digit test and return `Number(cleaned)`. `dash` and `junk` both come back
    as 0 and every other assertion in this file still passes."""
    m = ran["money"]
    assert m["dash"] is None, "an em dash parsed as a number: %r" % m["dash"]
    assert m["junk"] is None, "arbitrary text parsed as a number: %r" % m["junk"]
    assert m["empty"] is None and m["nul"] is None and m["undef"] is None


@needs_node
def test_money_reads_the_formats_this_page_actually_produces(ran):
    """`#tb-total`'s own text on one side, `fmtUSDdoc` on the other. Both carry a currency symbol
    and thousands separators, and a negative is reachable — a credit-heavy option line.

    Mutation: parse with `parseFloat` and "$1,234,567.89" becomes 1, because parseFloat stops at
    the first comma. A million-dollar bid then reads as a dollar."""
    m = ran["money"]
    assert m["plain"] == 36700
    assert m["commas"] == 1234567.89, "thousands separators are not being stripped: %r" % m["commas"]
    assert m["bare"] == 36700
    assert m["negative"] == -500


# ── the stamp ────────────────────────────────────────────────────────────────
@needs_node
def test_the_stamp_is_the_figure_the_document_was_filled_with(ran):
    """`values.total_formatted` — the tax-inclusive Total Base Bid the proposal's own Total line
    prints — and never the draft's `proposal_lump_sum`.

    This is the whole premise. The stamp exists to answer "is the price on screen the price in
    these files", so it has to record what the FILES got. Stamping the draft's own number would
    record the thing being checked instead of the thing to check it against, and the comparison
    would then be true by construction on every project forever — a green check that can never
    fail is worse than none, because it reads as proof.

    Mutation: `return v.proposal_lump_sum`. `ignoresDraftNumber` starts returning a figure, and
    the staleness test below goes green for the wrong reason."""
    b = ran["builtAt"]
    assert b["fromValues"] == "$36,700.00"
    assert b["ignoresDraftNumber"] is None, (
        "the draft's own number was stamped instead of the document's: %r" % b["ignoresDraftNumber"])
    assert b["noValues"] is None and b["nothing"] is None
    assert b["notAString"] is None, "a non-string total was stamped and would not compare"


# ── has the price moved ──────────────────────────────────────────────────────
@needs_node
def test_the_same_price_formatted_two_ways_is_not_drift(ran):
    """The stamp comes from `fmtUSDdoc(lumpSumNumber)` and the current figure is `#tb-total`'s own
    text. They are the same quantity through two different formatters, so they can legitimately
    differ as STRINGS on a project where nothing changed.

    Mutation: compare the two strings. Every project on the estimator's board starts demanding a
    regenerate it does not need, and the feature becomes an obstacle."""
    m = ran["moved"]
    assert m["same"] is False
    assert m["sameNumberOtherFormat"] is False, (
        "the same number formatted differently was reported as a price change")
    # A cent is a real edit; anything under it is the float noise publishDrift already tolerates.
    assert m["aHalfCent"] is False
    assert m["aWholeCent"] is True


@needs_node
def test_a_changed_price_is_caught_in_both_directions(ran):
    """Up and down. A discount applied after generating is exactly as wrong to show beside the old
    files as an increase, and it is the likelier edit.

    Mutation: `built - now >= 0.01` without the absolute value. A price that came DOWN sails
    through, and the card shows the customer's new lower number beside a document quoting the
    higher one."""
    assert ran["moved"]["changed"] is True
    assert ran["moved"]["changedDown"] is True, "a price that came down was not caught"


@needs_node
def test_a_draft_generated_before_the_stamp_existed_keeps_its_files(ran):
    """Unknown is not the same as changed.

    Every project already generated on prod carries a `generate_result` and no stamp. Treating a
    missing stamp as drift would make every one of them demand a regenerate on the day this lands
    — a self-inflicted outage of the download buttons across the whole board, for projects that
    are almost certainly fine.

    Mutation: `if (built == null) return true`. The suite still passes everything about the new
    path, and every existing project loses its downloads."""
    m = ran["moved"]
    assert m["noStamp"] is False, "an unstamped draft was treated as having a moved price"
    assert m["noDisplay"] is False and m["neither"] is False


# ── the mode decider ─────────────────────────────────────────────────────────
@needs_node
def test_a_moved_price_sends_the_estimator_back_to_generate(ran):
    """THE CASE THE FEATURE EXISTS FOR. Change a price on Proposal Review, come back to Files: the
    downloads sitting there were built from the old number. Before this they were offered anyway,
    with nothing on screen to say so — an estimator could download that .docx and send it.

    Decided HERE rather than in proposal-review's Continue, where the cover-letter version lives,
    because every route into this page has to be covered: the Files step pill, "View files" off the
    Projects list, a reload, a second tab. Only the decider is on all of them.

    Mutation: drop `&& !stale` from the branch. Every assertion about the row still passes and the
    card goes back to naming a price the files do not contain."""
    d = ran["decider"]
    assert d["agrees"]["calls"] == ["showPostGenerate"], (
        "a project whose price matches its files was denied its downloads")
    assert d["priceMoved"]["calls"] == ["showPreGenerate"], (
        "a project whose price moved was still offered the old files: %r"
        % d["priceMoved"]["calls"])


@needs_node
def test_the_other_routes_into_the_page_are_unchanged(ran):
    """The staleness branch is an insertion, not a rewrite, and the three existing outcomes have to
    survive it intact.

    `movedButNoPayload` is the one worth naming: a moved price with nothing to regenerate FROM has
    to land somewhere useful, and the stale files beat the empty state — "no project in flight" on
    a project that plainly has one is a worse answer than downloads that may be a revision behind.

    Mutation: let that case fall through to `emptyEl`. A project with files and no payload shows
    an empty page and the estimator has no way back to their documents."""
    d = ran["decider"]
    assert d["filesMode"]["calls"] == ["viewFiles"], (
        "files-mode stopped regenerating — it is the one route that always rebuilds")
    assert d["notGeneratedYet"]["calls"] == ["showPreGenerate"]
    assert d["nothingInFlight"]["calls"] == [] and d["nothingInFlight"]["emptyShown"] == ""
    assert d["unstamped"]["calls"] == ["showPostGenerate"]
    assert d["movedButNoPayload"]["calls"] == ["showPostGenerate"], (
        "a project with files but no payload was left on the empty state")


# ── the row ──────────────────────────────────────────────────────────────────
@needs_node
def test_the_card_shows_the_price_that_is_in_the_files(ran):
    """The stamp wins over the draft's display figure. In the fixture the two disagree on purpose:
    reaching for `lump_sum_display` first would put the newer number on the card, which is the
    defect this whole file is about, arriving through the back door.

    `lump_sum_display` is the fallback for a project generated before the stamp existed — and by
    the time this runs the decider has already established the two agree.

    Mutation: swap the `||` operands. The decider still routes correctly and the card still shows
    a price; it is simply the wrong one on the one project where it matters."""
    r = ran["row"]
    assert r["showsTheStamp"] == {"text": "$36,700.00", "hidden": False}, (
        "the card showed the draft's price rather than the document's: %r" % (r["showsTheStamp"],))
    assert r["fallsBackToDisplay"] == {"text": "$36,700.00", "hidden": False}


@needs_node
def test_no_figure_means_no_row_rather_than_a_dash(ran):
    """A "—" where money belongs invites being read as zero, on the one card whose job is to let
    somebody check a price. So the row goes away instead.

    A real $0.00 is a figure and stays — it is a legitimate, if alarming, state, and hiding it
    would be hiding the very thing worth seeing.

    Mutation: `row.hidden = !lump`. The em-dash case comes back, because "—" is truthy."""
    r = ran["row"]
    assert r["noFigure"]["hidden"] is True
    assert r["noFigure"]["text"] == "<untouched>", "a row that is hidden still wrote a figure"
    assert r["dashIsNot"]["hidden"] is True, "an em dash was rendered as the price"
    assert r["zeroIsAFigure"] == {"text": "$0.00", "hidden": False}, (
        "a real zero was hidden — that is the figure most worth seeing")


@needs_node
def test_the_row_is_shown_by_the_attribute_and_never_a_style_write(ran):
    """`.fp-money` carries its own `[hidden] { display: none }` beside it, because a class `display`
    beats the plain attribute's UA rule — the trap this page already documents on `.stale-doc` and
    `.fp-field`. A `style.display` write here would be a second opinion that beats both and the two
    would drift.

    Mutation: `row.style.display = "none"` instead of `row.hidden = true`. The row stays visible,
    because the class rule wins, and no DOM test that reads `hidden` notices."""
    assert ran["row"]["touchedNoStyle"] == "<untouched>", (
        "the row's visibility was set through style.display")
    assert ran["row"]["survivesAMissingRow"] is True, (
        "a page without the row throws on the way past: %r" % ran["row"]["survivesAMissingRow"])


def test_the_markup_pairs_the_class_with_its_own_hidden_rule():
    """The CSS half of the assertion above, and it has to be checked in the stylesheet because no
    DOM harness renders a cascade.

    Mutation: delete the `.fp-money[hidden]` line. Every JavaScript test above still passes and the
    row is permanently visible on screen, showing "—" on projects with no price."""
    assert ".fp-money[hidden]" in DONE_HTML, (
        "`.fp-money` sets `display` with no [hidden] rule beside it, so the attribute cannot hide "
        "it — the cascade trap this page documents twice elsewhere")
    assert 'id="lump-row"' in DONE_HTML and 'id="lump-sum"' in DONE_HTML
