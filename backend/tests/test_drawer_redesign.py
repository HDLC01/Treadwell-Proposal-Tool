"""The drawer redesign: the collapses, the heading ranks, and the two behaviour changes.

Hanz approved the mockup on 2026-08-27 ("looks good", then "implement it"). Everything asserted
here is something the redesign is FOR, and every one of them is invisible to the kind of test this
repo already had.

WHY THE CSS ASSERTIONS RESOLVE THE CASCADE INSTEAD OF GREPPING FOR A DECLARATION. A regex over a
stylesheet finds a rule; it cannot tell you whether the browser uses it, and this codebase has been
bitten by exactly that four times: the `hidden` attribute defeated by a class `display` rule, an
invisible grip at `opacity:0` still taking the click, a badge overridden by an equal-specificity
rule written later, and two rounds of "make the download buttons smaller" spent changing a value
that could never apply. THE 57px REVISION ROW IS THAT LAST ONE. `.rev-row .rev-dl` overrode the
download button's padding and its font-size and said nothing about `min-height`, so an 11.5px inline
control inherited `.btn { min-height:42px }` and eight rows came to 456px. A test asserting
`font-size:11.5px` is present passed the whole time. So the tests below compute specificity and
source order and assert WHAT WINS, which is the only shape that fails when somebody adds a rule
later in the file.

WHY THE MARKUP ASSERTIONS EXECUTE THE RENDERER. On 2026-08-12 the board went down on production
with `ReferenceError: STAGE_CREATED is not defined` while every test was green, because every test
read the source of the renderer and none had run it. A COLLAPSE is doubly invisible to a source
read: what matters is how many rows and cards a real payload produces, which is a fact about the
loop and not about the template inside it. Eight sends have to make one open row and one fold;
eight replaced documents have to make one line. So the harness runs the real renderDetail and the
real paintRevisions over payloads shaped like production's, and these assertions count what came
out.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "drawer-render-harness.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def out():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    # encoding="utf-8" explicitly: this box's locale is cp1252 and the panel is full of ·, ↗ and
    # ••••, which bare text=True turns into mojibake or blows up on.
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        "the harness itself failed - read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── a small, honest cascade ───────────────────────────────────────────────────
# Borrowed wholesale from test_editor_overlap.py, which needed the same thing for the same reason
# and says so at length. Deliberately narrow: it understands only the selector shapes this
# stylesheet uses for the elements under test, and DECLINES anything else, so a new shape shows up
# as a test that stops constraining rather than one that silently passes.
def _rules():
    """[(selector, body)] in source order, with comments and @media wrappers flattened away.

    The comments have to go first, and not out of tidiness: this stylesheet explains a change by
    quoting the declaration it replaced, so the .rev-* block literally contains the words
    `min-height:42px` inside a comment saying why that was the bug. A raw scan matches the prose
    and passes for the wrong reason."""
    css = (FRONTEND / "portal.html").read_text(encoding="utf-8")
    css = css[css.index("<style>"):css.index("</style>")]
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"@media[^{]*\{", "", css)
    css = re.sub(r"@keyframes[^{]*\{(?:[^{}]|\{[^{}]*\})*\}", "", css)
    return [(m.group(1).strip(), m.group(2))
            for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)]


def _specificity(sel):
    """(ids, classes+attrs+pseudo-classes, elements). Enough for this stylesheet, which uses no
    !important on anything under test and no ids in the rules these tests resolve."""
    ids = len(re.findall(r"#[\w-]+", sel))
    cls = len(re.findall(r"\.[\w-]+|\[[^\]]+\]|:(?!:)[\w-]+(?:\([^)]*\))?", sel))
    els = len(re.findall(r"(?:^|[\s>+~])([a-zA-Z][\w-]*)", sel))
    return (ids, cls, els)


def _matches(sel, tag, classes, ancestors, states=frozenset()):
    """Does `sel` match an element of `tag` carrying `classes`, nested inside `ancestors`?

    `ancestors` is a list of class sets, nearest parent first. Descendant and child combinators
    are treated alike, which is safe for every selector these tests resolve (the two child
    combinators in play, `.sec > .lbl` and `.sec.sec-dang > .lbl`, have their .sec as the direct
    parent in the real markup) and is written down here rather than discovered later.

    A pseudo-element (`::after`) never matches: those rules paint a generated box, not this one.

    AN ATTRIBUTE SELECTOR COUNTS AS A STATE, on the target and on every ancestor, and it has to.
    The tab strip's selected rule is `.dtabs .step[aria-selected="true"] .lbl`, and a matcher that
    ignored the attribute would report every tab as selected: the first version of this did, and
    said the strip's headings had turned full-ink when nothing had touched them.
    """
    sel = sel.strip()
    if "::" in sel or not sel:
        return False
    parts = [p for p in re.split(r"\s+|>", sel) if p]
    if not parts:
        return False

    def wants(part):
        return (set(re.findall(r"\.([\w-]+)", part)),
                set(re.findall(r":(?!:)([\w-]+)", part)) | set(re.findall(r"\[[^\]]+\]", part)),
                re.match(r"^([a-zA-Z][\w-]*)", part))

    tcls, tstates, ttag = wants(parts[-1])
    if ttag and ttag.group(1).lower() != tag.lower():
        return False
    if not tcls and not ttag:
        return False                                   # a bare pseudo or attr selector: decline
    if not tcls <= classes or not tstates <= states:
        return False
    for anc in parts[:-1]:
        acls, astates, atag = wants(anc)
        # An ancestor part naming an element (`.dbody[data-sec="chat"] #thread` and friends) is
        # only satisfied by an ancestor we were told about, and we describe ancestors by class.
        if atag and not acls:
            return False
        if not any(acls <= a for a in ancestors) or not astates <= states:
            return False
    return True


def _resolved(prop, tag, classes, ancestors, states=frozenset()):
    """The value the browser would use: highest specificity, then last in the file."""
    best, key = None, None
    for i, (sel, body) in enumerate(_rules()):
        for one in (s.strip() for s in sel.split(",")):
            if not _matches(one, tag, classes, ancestors, states):
                continue
            m = re.search(r"(?<![-\w])" + re.escape(prop) + r"\s*:\s*([^;]+)", body)
            if not m:
                continue
            k = (_specificity(one), i)
            if key is None or k >= key:
                best, key = m.group(1).strip(), k
    return best


# ── the row height that was never a design decision ──────────────────────────
def test_a_download_button_in_a_revision_row_is_the_small_one():
    """THE test this file exists for, and the one that would have caught the original bug.

    Every download control in that card is `class="btn btn-s rev-dl"`. `.btn` sets a 42px floor
    because it is written for a primary action; `.rev-row .rev-dl` shrinks the padding and the font
    and, until 2026-08-27, left the floor alone. So a 11.5px inline download was 42px tall, and
    with 7px of row padding either side that is a 57px row, eight times over: 456px of one card.
    Resolved rather than grepped, because that is the difference between the two: the declaration
    was always in the file and it never applied."""
    got = _resolved("min-height", "button", {"btn", "btn-s", "rev-dl"}, [{"rev-row"}])
    assert got == "26px", (
        "a download button inside a revision row resolves min-height:%s. If that is 42px, the "
        "override is losing to .btn again: it has to be declared at a selector that outranks "
        "`.btn` (0,1,0), which `.rev-row .rev-dl` at (0,2,0) does." % got)


def test_the_same_button_outside_a_revision_row_keeps_the_full_button_height():
    """The other half, and the one a blunt fix breaks. Shrinking `.btn` itself would have taken
    26px off Send reply, Mark deposit received and every other real button in the drawer, which is
    below the 44px touch target those want. The override is scoped to the row on purpose."""
    assert _resolved("min-height", "button", {"btn", "btn-s"}, [{"row3"}]) == "42px"


def test_the_override_beats_the_button_floor_on_specificity_not_on_source_order():
    """Written as a comparison rather than a resolved value, because the resolved value would
    still be right if the two rules merely happened to be in the right order, and the next person
    to reorganise this stylesheet would silently reintroduce a 57px row."""
    rules = _rules()
    floor = [s for s, b in rules if s.strip() == ".btn" and "min-height" in b]
    override = [s for s, b in rules if ".rev-dl" in s and "min-height" in b]
    assert floor and override, (floor, override)
    assert _specificity(override[0]) > _specificity(floor[0]), (
        "%r at %s does not outrank %r at %s, so which one wins depends on the order they are "
        "written in" % (override[0], _specificity(override[0]), floor[0], _specificity(floor[0])))


@needs_node
def test_eight_sends_render_one_open_row_and_a_fold(out):
    """The collapse, counted off a real paint rather than read off the template.

    Eight rows times three formats is twenty-seven download controls in one card, and only the
    current version is downloaded in a meeting. The rest are downloaded when somebody is answering
    "what did we send them in July", which is a deliberate trip. So one row stays open and seven go
    behind a disclosure that says how many there are.

    NO INNER SCROLLER is asserted too, and it is not a style preference: the drawer body already
    scrolls and the chat thread owns a second, so a third nested scroll region inside a card is
    worse than the wall of rows it would hide."""
    assert not out["errors"], out["errors"]
    card = out["revisions"]["many"]["html"]
    assert card.count('class="rev-row') == 8, "the card did not render all eight sends"
    assert card.count("<details") == 1, "the earlier sends are not behind exactly one disclosure"
    open_row = card.index("is-current")
    fold = card.index("<details")
    assert open_row < fold, "the current version is inside the fold"
    folded = card[card.index('class="rev-folded"'):]
    assert folded.count('class="rev-row') == 7, (
        "the fold holds %s rows; seven earlier sends should be in it"
        % folded.count('class="rev-row'))
    assert "overflow-y" not in card and "max-height" not in card, (
        "the card grew a scroller of its own")


@needs_node
def test_the_fold_says_how_many_and_whether_the_price_moved(out):
    """A disclosure that says only "show more" is a disclosure nobody opens, and the point of
    opening this one is almost always a price. The fixture is the bid this redesign was measured
    against: eight sends where the figure moved exactly once."""
    card = out["revisions"]["many"]["html"]
    summary = card[card.index("<summary"):card.index("</summary>")]
    assert "7 earlier sends" in summary, summary
    assert "The price moved once." in summary, summary
    # And the answer line on the heading, which is what a rep reads without opening anything.
    assert out["revisions"]["many"]["answer"] == "8 sends, latest Rev 8", (
        out["revisions"]["many"]["answer"])


@needs_node
def test_an_unchanged_price_is_demoted_and_the_current_one_never_is(out):
    """The column becomes a change log. Seven of these eight rows carry the same figure as the send
    before them, so the two where the price actually moved are the two that read. Nothing is
    hidden: a repeated amount is still printed, at the same size, in the muted ink.

    THE CURRENT ROW IS NEVER DEMOTED whatever it repeats, and that is the assertion with teeth: it
    is the price this customer is holding and the one figure the card exists to state, so demoting
    it would be the whole change inverted. It happened on the first cut of this."""
    card = out["revisions"]["many"]["html"]
    current = card[card.index("is-current"):card.index("<details")]
    assert "same" not in current, "the current row is demoted to the muted weight"
    assert "<strong class=\"rev-amt\">" in current, "the current price lost its weight"
    folded = card[card.index('class="rev-folded"'):]
    rows = re.findall(r'<div class="rev-row([^"]*)"', folded)
    assert rows.count(" same") == 5, (
        "%s of the seven folded rows are demoted; five repeat the row below them and two are the "
        "rows where the price moved" % rows.count(" same"))
    # Demoted means regular weight, not hidden: the figure is still there.
    assert folded.count("$90,885.00") + folded.count("$84,200.00") == 7


@needs_node
def test_one_send_needs_no_fold_and_a_project_with_none_says_so(out):
    """The two ends. A single send has nothing to collapse, and a disclosure offering to reveal
    nothing is worse than no disclosure. A project sent before revisions existed is a fact about
    the record rather than an error, and its heading has to say something rather than nothing."""
    one = out["revisions"]["one"]
    assert one["answer"] == "1 send, latest Rev 1", one["answer"]
    assert "<details" not in one["html"], "one send is hiding something behind a fold"
    none = out["revisions"]["none"]
    assert none["answer"] == "No versions recorded", none["answer"]
    assert "No snapshots yet" in none["html"]


@needs_node
def test_the_intro_sentence_moved_into_the_fold_rather_than_being_deleted(out):
    """It explains what a snapshot IS, which is worth exactly one read, and it was sitting above
    the list every time anybody opened the tab. Behind the disclosure it reaches the only person
    who needs it: whoever is looking at the history."""
    card = out["revisions"]["many"]["html"]
    assert "pins the estimate as it was" in card, "the sentence was deleted, not moved"
    assert card.index("<details") < card.index("pins the estimate as it was"), (
        "the sentence is still above the list")


# ── three heading ranks, settled on specificity ──────────────────────────────
SEC = [{"sec"}, {"dpanel"}]


def test_a_section_heading_reads_as_a_heading():
    """RANK 1. The drawer had one rank, and it separated a card's title from the field keys inside
    it by COLOUR alone: both are 700 uppercase at 11px and 10px, so "APPROVED" and "AMOUNT" read as
    the same level and the card lost its top. Sentence case at 13px is what makes a heading a
    heading."""
    assert _resolved("font-size", "div", {"lbl"}, SEC) == "13px"
    assert _resolved("text-transform", "div", {"lbl"}, SEC) == "none"
    assert _resolved("color", "div", {"lbl"}, SEC) == "var(--ink)"


def test_a_heading_inside_a_card_drops_a_rank_and_wins_on_specificity():
    """RANK 2, and the reason it is written at (0,3,0).

    Six of the Follow-up tab's seven headings were direct children of .sec and therefore identical
    to the tab's own title, and so was the Deposit tab's "What the customer submitted", which is
    what made that tab read as two cards of equal weight. They label content INSIDE a card, so they
    take .fact-k's spec.

    Rank 1 is `.sec > .lbl` at (0,2,0). A rank-2 rule written as `.fu-lbl` (0,1,0) would LOSE, and
    one written as `.sec > .fu-lbl` (0,2,0) would win only by being later in the file. Both of
    those read perfectly well in a diff. So the resolved answer is asserted, and then the
    specificity itself, because the resolved answer alone would still pass on a rule that only
    happens to be in the right place."""
    for cls in ("fu-lbl", "dep-lbl"):
        assert _resolved("font-size", "div", {"lbl", cls}, SEC) == "10px", cls
        assert _resolved("text-transform", "div", {"lbl", cls}, SEC) == "uppercase", cls
        assert _resolved("color", "div", {"lbl", cls}, SEC) == "var(--ink-v)", cls
        # And it reads as a label rather than a two-column heading line.
        assert _resolved("display", "div", {"lbl", cls}, SEC) == "block", cls
    rules = _rules()
    rank1 = [s for s, b in rules if s.strip() == ".sec > .lbl"]
    rank2 = [s for s, b in rules if ".lbl.fu-lbl" in s]
    assert rank1 and rank2, (rank1, rank2)
    assert _specificity(rank2[0]) > _specificity(rank1[0]), (
        "rank 2 (%r at %s) does not outrank rank 1 (%r at %s), so which one applies depends on "
        "the order they are written in"
        % (rank2[0], _specificity(rank2[0]), rank1[0], _specificity(rank1[0])))


def test_the_destructive_heading_is_the_third_rank_and_carries_the_rule():
    """RANK 3. Four quiet signals stacked rather than one loud one: a red heading, a red left rule,
    an outlined button and one line of copy. The rule reuses .dep's own device instead of inventing
    a banner, which would shout louder than "Send deposit request" two tabs away."""
    dang = [{"sec", "sec-dang"}, {"dpanel"}]
    assert _resolved("color", "div", {"lbl"}, dang) == "var(--red-dark)"
    assert _resolved("border-left", "div", {"sec", "sec-dang"}, [{"dpanel"}]) == \
        "3px solid var(--red-dark)"
    # An ordinary card takes no rule at all, or the device stops meaning anything.
    assert _resolved("border-left", "div", {"sec"}, [{"dpanel"}]) is None


def test_the_new_ranks_do_not_reach_the_tab_strip():
    """The tab strip is the one part of the drawer that already worked, and it uses .lbl too. Rank
    1 is scoped with `>` under .sec precisely so the strip keeps its quieter 11px uppercase, which
    is what the selected state then brightens. A rank-1 rule written as a bare `.lbl` would repaint
    all five tabs and read as an improvement in the diff."""
    strip = [{"step"}, {"dtabs"}]
    assert _resolved("font-size", "span", {"lbl"}, strip) == "11px"
    assert _resolved("text-transform", "span", {"lbl"}, strip) == "uppercase"
    assert _resolved("color", "span", {"lbl"}, strip) == "var(--ink-v)"


@needs_node
def test_every_countable_card_answers_itself_on_its_heading(out):
    """The move, in one line: the number was always the only part of the paragraph anybody read,
    and it was printed third, underneath it. Executed, because each of these answers is derived
    from a payload and the derivation is where they go wrong."""
    html = out["scenarios"]["submitted"]["html"]
    answers = dict(re.findall(r'<div class="lbl">([A-Za-z][^<]*)<span class="sec-ans">([^<]*)<',
                              html))
    assert answers.get("Customer") == "Opened 3 times, last 2026-08-11", answers
    assert answers.get("Deposit") == "Submitted, waiting on you", answers
    assert answers.get("Project contacts") == "2 contacts", answers
    # Sent versions and Notifications are painted asynchronously into their own nodes, so they are
    # empty in the markup and covered by their own tests above and in test_drawer_renders.py.
    assert 'id="rev-count"' in html and 'id="nt-count"' in html


# ── the Customer card answers a question instead of repeating the head ───────
@needs_node
def test_the_customer_card_says_whether_they_have_opened_it(out):
    """Hanz approved this as a behaviour change, and it is also how the duplicated name resolves.

    The card used to be the customer's name in 15.5px bold with their email under it, 40px below
    the head, which carries the same name on every tab. A card whose whole content repeats the head
    is a card with no job. The head keeps the name (test_drawer_renders pins it, for a good reason)
    and the card answers the question a sales meeting actually asks about a quiet proposal.

    Off viewed_at / last_viewed_at and the per-contact view counts, all of which the drawer already
    held: the count is only kept per contact, so it is summed, which is the honest reading of "how
    many times has this been opened" on a proposal that went to three people."""
    html = out["scenarios"]["submitted"]["html"]
    card = html[html.index('id="dsec-customer"'):]
    card = card[:card.index('id="dsec-recipients"')]
    assert "Opened 3 times, last 2026-08-11" in card, card
    assert ">Email<" in card and "hdlcruz03@gmail.com" in card, "the address left with the name"
    assert ">First opened<" in card, "the card does not say when they first opened it"
    # The name is NOT here any more, and the head still has it.
    assert "HANZ URIEL A DE LA CRUZ" not in card, (
        "the customer's name is printed twice again, once in the head and once 40px under it")
    assert "idn-n" not in html, "the removed identity block is back"


@needs_node
def test_a_proposal_nobody_has_opened_says_so(out):
    """The most useful state the card has, and the one it never used to mention: a bid sent nine
    days ago that nobody has opened is the reason to pick the phone up."""
    html = out["scenarios"]["unviewed"]["html"]
    card = html[html.index('id="dsec-customer"'):]
    assert "Not opened yet" in card[:400], card[:400]
    assert "Opened " not in card[:400], "it claims an open it has no stamp for"


@needs_node
def test_an_approved_proposal_with_no_view_stamp_claims_nothing(out):
    """The one place "Not opened yet" would be a flat lie. Nobody approves a document they have not
    read, so on a row from before the portal recorded views that sentence would contradict the
    Approved card two rows down. Silence is the honest answer to "how many times", and the news is
    already on screen.

    ITS OWN FIXTURE, because the ordinary approved payload cannot reach this branch: it carries a
    per-contact viewed_at, which the card falls back to, so its answer line is a real "Opened"
    sentence. A row with no stamp anywhere is any proposal approved before the portal recorded
    views."""
    html = out["unseenApproved"]["html"]
    card = html[html.index('id="dsec-customer"'):]
    card = card[:card.index('id="dsec-approved"')]
    assert 'class="sec-ans"' in card, "the answer span went away instead of going quiet"
    assert "Not opened yet" not in card, (
        "it tells the estimator nobody opened a proposal that has been signed")
    assert "Opened" not in card, "it claims an open with no stamp to date it from"
    # And the approval it must not contradict is genuinely on screen.
    assert 'id="dsec-approved"' in html


# ── chat: three registers ────────────────────────────────────────────────────
@needs_node
def test_a_replaced_document_folds_to_a_line_and_the_live_one_keeps_its_card(out):
    """A revision or an invoice the customer has since been sent a replacement for is not news, and
    there is one of them per re-send: a bid sent eight times carried seven dimmed copies of the same
    card plus the replaced invoice, which is around 800px of thread saying the same thing eight
    times. They collapse into one line in the slot of the latest of them, which is where the
    conversation left them: immediately before whatever replaced them.

    Counted rather than read, because the count IS the claim. The template that renders a card was
    never wrong; what was wrong was how many times the loop ran it."""
    f = out["fold"]
    assert f["cards"] == 1, (
        "%s document cards in a thread with one live revision and eight replaced ones" % f["cards"])
    assert f["folds"] == 1, "the replaced documents did not fold into exactly one line"
    assert "Revision 8 of the proposal" in f["html"], "the live revision lost its card"
    fold = f["html"][f["html"].index('class="sup-list"'):]
    fold = fold[:fold.index("</details>")]
    # Nothing is LOST: opening the line lists every one of them with its date and its replacement.
    assert fold.count("<div class=\"note\">") == 8, fold
    assert "Revision 7 · 2026-08-14 · replaced by 8" in fold, fold
    assert "Deposit invoice 23.150-01" in fold, fold


@needs_node
def test_the_fold_counts_revisions_and_invoices_separately(out):
    """"7 replaced revisions and 1 replaced invoice" is a truer sentence than "8 replaced
    documents": one of those is a price and the other is a bill, and which of them was re-sent is
    the thing somebody opening this line wants to know."""
    html = out["fold"]["html"]
    summary = html[html.index('class="sup-list"') - 900:html.index('class="sup-list"')]
    assert "7 replaced revisions and 1 replaced invoice" in summary, summary
    assert "2026-07-02 to 2026-08-14" in summary, summary


@needs_node
def test_the_fold_sits_where_the_conversation_left_it(out):
    """Not pinned to the top or the bottom. A thread is chronological, and the replaced documents
    belong immediately before the one that replaced them, which is exactly where a rep scrolling
    back through the conversation would expect to find them."""
    html = out["fold"]["html"]
    thread = html[html.index('id="thread"'):html.index('id="chat-compose"')]
    first_msg = thread.index("Here is the bid for the cold line")
    fold = thread.index('class="sup-list"')
    live = thread.index("Revision 8 of the proposal")
    assert first_msg < fold < live, (
        "the fold is not between the message that opened the thread and the revision that "
        "replaced everything in it")


@needs_node
def test_what_the_system_says_is_a_line_and_not_a_card(out):
    """The third register. "Approved by Marcus, Polish, Epoxy" is neither speech nor a document: it
    is the thread telling you what happened, and it was a bordered card anchored to one side, which
    is the shape a MESSAGE has. Three of those in a row read as three people talking."""
    html = out["fold"]["html"]
    thread = html[html.index('id="thread"'):html.index('id="chat-compose"')]
    assert '<p class="note sys">Approved by Marcus Ellery · Polish, Epoxy</p>' in thread, thread
    assert "chat-card system" not in thread, "an event is still drawn as a card"


@needs_node
def test_the_thread_is_broken_up_by_day(out):
    """A conversation that ran from July to August was one unbroken column of bubbles whose only
    date was a timestamp inside each one. The marker is the same .note.sys line everything else the
    system says now uses, with no fill, so it divides rather than reports.

    Three markers for three days with something in them, and no marker for the fold's own day: the
    fold names its date range itself, and a day heading over a line that already says "Jul 2 to
    Aug 14" would be dating a range."""
    assert out["fold"]["days"] == 3, (
        "%s day markers for a thread spanning three days of live messages" % out["fold"]["days"])


def test_a_short_thread_sits_on_the_composer():
    """#thread is a flex column with room to spare on a two-message conversation, so the messages
    painted at the top and 400px of white sat between them and the box you reply in.

    Resolved rather than grepped, and asserted on the FIRST CHILD, because the fix is one
    `margin-top:auto` and the obvious wrong version of it (`justify-content:flex-end` on the
    thread) fights the scroll position applySecPanel restores."""
    css = "".join(b for s, b in _rules() if "#thread > :first-child" in s)
    assert "margin-top:auto" in css.replace(" ", ""), (
        "the first message in a short thread is not pushed down onto the composer")
    thread = "".join(b for s, b in _rules() if s.strip().endswith("#thread"))
    assert "justify-content" not in thread, (
        "the thread justifies its content, which overrides the scroll position on every tab switch")


# ── marking a project won now asks first ─────────────────────────────────────
# Hanz approved this as a behaviour change on 2026-08-27. Mark won was the only control in that
# group without a prompt, sitting between Mark delayed and Mark closed lost, which both have one.
# The comment in wireWon used to argue against it and the argument was sound while a won card
# stayed among the live ones. It stopped being sound the day the Won TAB took won jobs off the
# Active board: this press MOVES THE CARD, and a pointer landing one row high files a live bid as
# won and takes it off the board the estimator is about to look at.
@needs_node
def test_marking_a_project_won_asks_before_anything_is_sent(out):
    """Asked, and asked through the house helper. TW.confirmDanger is what confirmBringBack, Mark
    delayed and Delete project all go through: it traps focus between its two buttons and focuses
    Cancel. Never window.confirm, which cannot be styled, cannot be tested, and cannot say what it
    is about to do."""
    r = out["won"]["notSentMarked"]
    assert r["pressed"], "the button never rendered, so this proves nothing"
    assert len(r["asked"]) == 1, "it posted without asking, or asked twice"
    a = r["asked"][0]
    assert a["name"] == "Riverbend Logistics Hub", (
        "the dialog does not name the project: %r" % a.get("name"))
    assert "Won tab" in a["after"], a["after"]
    assert a["confirmText"] and a["confirmText"] != "OK", a["confirmText"]
    # warn, not danger. Winning a job is good news and it is reversible, so it takes the tone Mark
    # delayed has rather than the tone a delete has.
    assert a["tone"] == "warn", a["tone"]
    assert a["icon"] and a["icon"] != "🗑", (
        "confirmDanger's warn default is a wastebasket, which is the wrong picture on the one "
        "dialog here that is good news")


@needs_node
def test_the_ask_names_the_four_things_people_get_wrong_about_it(out):
    """That a dialog exists is not the feature; what it says is. Every one of these answers a
    question somebody would otherwise have to ask the person who built the tool, and three of them
    are the reasons an estimator hesitates over this button."""
    detail = out["won"]["notSentMarked"]["asked"][0]["detail"].lower()
    assert "does not wait" in detail and "approve" in detail, (
        "it does not say the mark runs ahead of the customer's own approval")
    assert "deposit" in detail, "it does not say it runs ahead of the money"
    assert "not emailed" in detail, "it does not say the customer hears nothing"
    assert "carry on" in detail or "carries on" in detail, (
        "it does not say the follow-ups keep going, which is the thing people assume stops")
    assert "undo" in detail, "it does not say the mark can be taken off"
    assert "—" not in detail, "an em dash reached the dialog copy"


@needs_node
def test_cancelling_the_mark_sends_nothing_and_claims_nothing(out):
    """The whole value of a confirmation, and the only assertion that can prove the ask happens
    BEFORE the write rather than beside it: it was asked, and nothing left the page.

    The board row matters as much as the request. This control patches the row optimistically (the
    Won mark is not in the portal payload the poll re-fetches, so the row is the client's one copy
    of it), which means a cancel that patched anyway would leave the card claiming a win nothing
    saved for as long as the tab stayed open."""
    r = out["won"]["markCancelled"]
    assert r["pressed"], "the button never rendered, so this proves nothing"
    assert len(r["asked"]) == 1, "cancelling was possible because nothing was ever asked"
    assert r["requests"] == [], "it posted anyway: %s" % r["requests"]
    assert not r["rowWonAt"], "the board row was patched, so the card will claim a win"
    assert 'id="won-mark"' in r["html"], "the control is gone, so there is no way to press it again"
    assert r["label"] == "Mark won" and r["disabled"] is False, (
        "the button is left %r/disabled=%s after a cancel" % (r["label"], r["disabled"]))


@needs_node
def test_the_mark_still_goes_through_once_it_is_confirmed(out):
    """The other half, and the one a too-careful guard breaks: a prompt that never resolves, or a
    handler that awaits it and then forgets to post, is indistinguishable from a broken button."""
    r = out["won"]["notSentMarked"]
    assert r["requests"], "confirming the dialog posted nothing at all"
    assert r["requests"][0]["body"] == {"status": "won"}, r["requests"]
    assert 'id="won-undo"' in r["html"], "the panel did not repaint into the won state"


# ── attachments: a reserved box ──────────────────────────────────────────────
def test_a_photo_gets_a_reserved_box_rather_than_reflowing_the_thread_when_it_lands():
    """attHtml renders the anchor with an empty <img> and hydrateAtts fills the src in afterwards
    through the authenticated helper, which is unavoidable: an <img> tag cannot send a bearer token.
    So for one round trip per photo the box has no content, and while it was sized off the image
    (`width:auto` under a 200px cap) the whole thread reflowed under the estimator's eye as each
    thumbnail landed.

    The JS half of this fix lives on fix/attachment-thumbnails-ui and is deliberately not touched
    here. What this asserts is that the box it lands in is the right shape: a fixed 160x120 that
    holds the space from the first paint, with the picture cropped into it rather than resizing it.
    """
    assert _resolved("width", "a", {"att-img"}, [{"att-list"}]) == "160px"
    assert _resolved("height", "a", {"att-img"}, [{"att-list"}]) == "120px"
    assert _resolved("object-fit", "img", set(), [{"att-img"}]) == "cover", (
        "the picture is not cropped into the reserved box, so it will resize it on arrival")
    assert _resolved("background", "a", {"att-img"}, [{"att-list"}]) == "var(--surf-high)", (
        "an empty box with no tint reads as a rendering failure rather than as a photo loading")
