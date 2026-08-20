"""Chat opens first, the customer's view shows up as a bubble, and both drawers reach the paperwork.

THREE THINGS HANZ ASKED FOR ON 2026-08-20, all in the project drawer:

  1. "In the opening of a project, Chat should be the tab thats the first to appear."
  2. "If the customer views it why is there no chat bubble like The customer has viewed it in this
      chatbox?"
  3. "Move the info sheet button inside proposals tab."

WHAT (1) TURNED OUT TO MEAN. "Chat first" was first shipped as an unconditional Chat, and that put
the two drawers with no conversation on the only tab they cannot fill: a bid nobody has sent has no
portal row, so its Chat panel is one paragraph saying the conversation opens when the customer can
see the proposal. Landing there is landing on an empty box, which is not what was asked for. So the
resting tab is Chat WHEN THERE IS A THREAD and Proposal when there is not, decided off the thread as
rendered rather than off which renderer is painting, so a sent project whose customer has never
written behaves the same way. The three precedence rules above it are untouched.

WHY (2) NEEDED A CODE CHANGE AND NOT A FILTER FIX. The staff drawer already asks the portal for
internal messages (its detail route passes include_internal=True), and the portal already writes a
staff-only view card. But it writes it only on a literal sent -> viewed transition — db.mark_viewed
returns True for that one row state — so a project the customer opened BEFORE that card shipped has
none, and can never get one without a re-send. The row Hanz was looking at: sent 2026-08-18 20:33:55,
viewed 20:36:04, card shipped 2026-08-19. So the DISPLAY now comes from the timestamps, which every
view writes and nothing can miss, and the stored card still wins when there is one.

EXECUTED, NOT GREPPED. Everything here runs the real renderDetail / renderNotSent / openDetail out
of the real portal.js through backend/tests/js/drawer-render-harness.js. A source-text assertion
cannot see an unbound identifier, and one of those took the production board down on 2026-08-12
with every test green.

WHAT THE HARNESS CANNOT SAY: it answers querySelector out of the markup the renderer just wrote, so
this proves what was rendered, wired and clicked — not layout or the cascade.
"""
import json
import pathlib
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
    # encoding="utf-8" explicitly: this box's locale is cp1252 and the drawer is full of ·, ↗ and
    # —, which bare text=True turns into mojibake or an outright decode error.
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── 1. Chat opens first, when there is a chat ────────────────────────────────
@needs_node
def test_a_sent_project_with_a_conversation_opens_on_chat(out):
    """The resting tab. Every payload with a thread and nothing waiting on a human lands on Chat:
    sent, approved-and-invoiced, viewed, and one nobody has opened yet."""
    assert not out["errors"], out["errors"]
    for name in ("sent", "approved", "viewed", "unviewed"):
        assert out["scenarios"][name]["openedOn"] == "chat", (
            "the %s drawer opened on %s" % (name, out["scenarios"][name]["openedOn"]))


@needs_node
def test_a_project_with_nothing_in_its_thread_opens_on_proposal(out):
    """The other half of the same rule, and the reason it is a rule rather than a constant. The
    "bare" payload is a row stripped to almost nothing: no messages, no questions, nobody has
    opened it, so its Chat panel is the words "No messages yet." above an empty reply box.

    Landing there is landing on the one tab with nothing on it, which is the opposite of what
    "Chat should be the tab thats the first to appear" was asking for. Proposal at least carries
    the customer, the money and the way to the files.

    Read together with the test above, this pair is what makes the fallback a decision: delete the
    thread test from restingSection in either direction and exactly one of the two fails."""
    assert out["scenarios"]["bare"]["openedOn"] == "proposal", (
        "an empty-thread drawer opened on %s" % out["scenarios"]["bare"]["openedOn"])


@needs_node
def test_an_unsent_project_opens_on_proposal(out):
    """The drawer with no portal row at all, which is where the unconditional version of this bit.
    There is no conversation on an unsent bid and there cannot be one until somebody sends it, so
    its Chat panel is a single explanatory paragraph.

    AND IT IS THE SAME ANSWER THE SENT DRAWER'S RULE GIVES for a project with nothing in its
    thread, which is the second assertion here and the one that matters in a year. This panel writes
    its landing tab out as a literal (two other harnesses lift renderNotSent alone, so a call to
    restingSection would be a ReferenceError for the whole panel), so nothing in the code stops the
    two drifting apart. This does: change restingSection's empty-thread answer without changing
    this line, or the reverse, and it fails naming both."""
    assert out["notSent"]["openedOn"] == "proposal", (
        "the not-sent drawer opened on %s" % out["notSent"]["openedOn"])
    assert out["notSent"]["openedOn"] == out["route"]["quietNoThread"], (
        "the two drawers have drifted: an unsent bid lands on %r while the shared rule answers %r "
        "for a project with nothing in its thread"
        % (out["notSent"]["openedOn"], out["route"]["quietNoThread"]))


@needs_node
def test_the_precedence_above_the_fallback_survived(out):
    """The three rules that beat the resting tab, each put against the tab it has to BEAT.

    That framing is the point. Now that Chat is also the fallback, "the drawer opened on Chat"
    no longer distinguishes "a customer is waiting" from "nothing matched" — so deleting the
    unread rule would leave a naive assertion green. Pairing it with an unconfirmed payment is
    the shape that still fails."""
    r = out["route"]
    assert r["unreadBeatsDeposit"] == "chat", "a waiting customer message no longer wins"
    assert r["depositSubmitted"] == "deposit", "money in and unconfirmed no longer wins"
    assert r["approvedNoRequest"] == "deposit", "approved with nothing invoiced no longer wins"
    # And the two that deliberately do NOT claim the Deposit tab: there is nothing to action on it.
    assert r["approvedRequested"] == "chat"
    assert r["approvedNoDeposit"] == "chat"
    assert r["quiet"] == "chat"
    # The fallback, with nothing to fall back ON.
    assert r["quietNoThread"] == "proposal", "an empty thread still claimed the Chat tab"
    # Both top rules against an EMPTY thread, which is the second way this could go wrong: a rule
    # that only wins when there happens to be a conversation is not above the fallback at all, and
    # an unread message with nothing rendered under it would be the shape that proves it.
    assert r["unreadNoThread"] == "chat", "a waiting message lost to the empty-thread fallback"
    assert r["depositNoThread"] == "deposit", "money in and unconfirmed lost to the fallback"


@needs_node
def test_the_tab_is_sticky_within_one_open(out):
    """renderDetail re-runs after every action and on every 12s poll. Without the sticky read a
    rep who walked to Follow-up would be thrown back to Chat four times a minute."""
    assert out["route"]["sticky"] == "followup", (
        "the tab the rep is on was replaced by the routing")
    # Including a rep standing on an EMPTY Chat tab, which is where somebody is when they are about
    # to type the first message. The fallback must not walk them to Proposal on the next poll.
    assert out["route"]["stickyChatNoThread"] == "chat", (
        "a rep on an empty Chat tab was moved off it by the fallback")


@needs_node
def test_the_sec_deep_link_still_overrides_the_routing(out):
    """A notification links straight to a tab (?open=<id>&sec=deposit). It is the one thing above
    the routing, and it lives in openDetail — which this runs for real, query string and all."""
    assert out["deepLink"]["openedOn"] == "deposit", (
        "?sec=deposit did not win; the drawer opened on %s" % out["deepLink"]["openedOn"])
    # Consumed ONCE. openDetail re-runs after every action, so an unguarded read would pin the rep
    # to that tab for the rest of the session.
    assert out["deepLink"]["secondProject"] == "chat", (
        "the deep link stuck to the next project opened")


@needs_node
def test_a_sec_naming_a_tab_that_does_not_exist_is_ignored(out):
    """?sec= arrives from a notification email, and a stale or hand-edited one can name anything.
    The whitelist is `if (want && SEC_TABS[want])` in openDetail, so this drives a genuinely
    unknown value (`?sec=nonsense`) through the real openDetail and asserts the drawer lands on a
    REAL tab, by the ordinary routing, as if the parameter had not been there.

    THIS TEST WAS VACUOUS UNTIL 2026-08-21 and is the reason the rule about tests advertising
    coverage they do not have is worth writing down. It set location.search and then called
    renderDetail, which never reads the query string, so the whitelist could be deleted from
    portal.js and all 128 tests stayed green. The reviewer proved exactly that, and this version was
    checked the same way: remove SEC_TABS[want] and the first assertion below reports 'nonsense'.

    Two claims, because the ungated value fails them differently. It survives as ACTIVE_SEC, so the
    routing is defeated for the rest of the open; and applySecPanel quietly falls back to Proposal,
    so the panel on screen is not the tab the state believes in."""
    dl = out["deepLink"]
    assert dl["junkSec"] in out["tabs"], (
        "?sec=nonsense survived the whitelist: the drawer's active tab is %r" % dl["junkSec"])
    assert dl["junkSec"] == "chat", (
        "the junk value was dropped but the routing did not run; landed on %r" % dl["junkSec"])
    # The paint and the state agree, which is the "rather than blanking the panel" half.
    assert dl["junkPanels"] == [dl["junkSec"]], (
        "the drawer shows %s while its active tab is %r" % (dl["junkPanels"], dl["junkSec"]))
    assert dl["junkSelected"] == [dl["junkSec"]], (
        "the tab strip reads %s as selected" % dl["junkSelected"])


# ── 2. the "customer opened it" bubble ───────────────────────────────────────
@needs_node
def test_an_already_viewed_project_renders_exactly_one_viewed_bubble(out):
    """The project shape that had NO bubble and could never get one: opened before the portal's
    view card shipped, so there is no stored row to render and no transition left to catch."""
    html = out["scenarios"]["viewed"]["html"]
    assert html.count("opened the proposal") == 1, (
        "expected one viewed bubble, found %s" % html.count("opened the proposal"))
    assert "The customer opened the proposal" in html


@needs_node
def test_the_bubble_says_when_in_the_business_timezone(out):
    """Central, not the viewer's clock: "opened 8/18 8:36 PM" has to mean the same evening to Kyle
    in Kansas and to anyone testing from another timezone. The harness's TW.fmtBizDateTime stands
    in for shared.js, so the assertion is that the card went THROUGH it — a raw ISO string or a
    `new Date().toLocaleString()` would not look like this."""
    html = out["scenarios"]["viewed"]["html"]
    assert "2026-08-18 20:36" in html, "the first view is not dated"
    assert "2026-08-18T20:36:04Z" not in html, "the raw timestamp reached the markup"


@needs_node
def test_a_second_opening_is_a_footnote_on_the_same_card(out):
    """First view is the newsworthy one, so it dates the card and decides its slot. A re-read is a
    hint on the same bubble — a card per view would push a fresh bubble into the thread every time
    a customer left the tab open."""
    assert "· last opened 2026-08-19 14:02" in out["scenarios"]["viewed"]["html"]
    once = out["scenarios"]["viewedOnce"]["html"]
    assert once.count("opened the proposal") == 1
    assert "last opened" not in once, (
        "a project opened once grew a hint repeating the date beside it")


@needs_node
def test_a_customer_re_reading_it_does_not_repaint_an_open_drawer(out):
    """The cost of rendering from the stamps, and the reason `last_viewed_at` is excluded from the
    drawer signature.

    Every customer view stamps it, and renderDetail reads it off the board row a few lines before it
    takes that signature. It used to be MERGED onto the payload there, which is what put it in the
    signature: a customer reloading the page they were already sent moved it, and the next 12s poll
    then rebuilt the entire drawer, the thread and the tab strip and the reply box with whatever a
    rep was half way through typing in it. The signature exists precisely to make that poll
    invisible. It is now a local, so the render still has it and the signature does not.

    THE CONTROL MATTERS AS MUCH AS THE CLAIM. A drawer that never repaints passes the first
    assertion, so a real change (money in, unconfirmed) has to still get through, and the excluded
    stamp has to still be READ: the repaint it did not earn carries its new footnote."""
    r = out["reread"]
    assert r["opened"] == 1, "the first paint did not happen, so this proves nothing"
    assert not r["repaintedOnReread"], (
        "a customer re-reading the proposal repainted the open drawer")
    assert r["repaintedOnRealChange"], (
        "nothing repaints any more: the exclusion froze the drawer instead of quieting it")
    assert r["footnote"], "the new last-opened date never reached the markup"


@needs_node
def test_the_first_view_still_repaints_the_drawer(out):
    """The other side of that exclusion. The first open is what draws the bubble, so `viewed_at`
    stays in the signature: a rep with the drawer open when the customer first opens the proposal
    watches the bubble appear, which is the whole feature Hanz asked for.

    It is written once and coalesced, so unlike its neighbour it cannot churn."""
    r = out["reread"]
    assert not r["bubbleBefore"], "the fixture already had a bubble, so this proves nothing"
    assert r["repaintedOnFirstView"], (
        "the first view was excluded too, so the bubble only appears on the next unrelated change")
    assert r["bubbleAfter"], "the repaint happened but no bubble was drawn"


@needs_node
def test_a_stored_view_card_is_not_doubled_by_a_synthesised_one(out):
    """A send after 2026-08-19 has BOTH a stored card and the stamps. One bubble, and it is the
    stored one — it names who opened it, which the timestamps cannot."""
    html = out["scenarios"]["viewedStoredCard"]["html"]
    assert html.count("opened the proposal") == 1, (
        "two viewed bubbles: %s" % html.count("opened the proposal"))
    assert "Dave opened the proposal." in html, "the portal's own card was replaced"
    assert "The customer opened the proposal" not in html, "the synthetic card doubled it"
    assert out["insertion"]["syntheticCount"] == 0
    assert out["insertion"]["storedWins"] == ["A", "B", "Dave opened the proposal."]


@needs_node
def test_a_project_nobody_has_opened_renders_no_bubble(out):
    assert "opened the proposal" not in out["scenarios"]["unviewed"]["html"]
    assert out["insertion"]["never"] == ["A", "B"]


@needs_node
def test_the_bubble_sits_in_its_chronological_slot(out):
    """Hanz asked for a bubble in the conversation. One pinned to the top or the bottom regardless
    of its date is not part of the conversation — so the slot moves with the stamp."""
    ins = out["insertion"]
    assert ins["middle"] == ["A", "VIEW", "B"], ins["middle"]
    assert ins["earliest"] == ["VIEW", "A", "B"], ins["earliest"]
    assert ins["latest"] == ["A", "B", "VIEW"], ins["latest"]
    # And in the MARKUP, not only in the array: the thread is what a rep reads.
    html = out["scenarios"]["viewed"]["html"]
    first = html.index("Sending this over for the cold storage build.")
    card = html.index("The customer opened the proposal")
    later = html.index("Looks good, we will review it internally.")
    assert first < card < later, "the viewed bubble is not between the two messages it dates between"


@needs_node
def test_the_slot_is_decided_by_the_instant_not_by_the_string(out):
    """Postgres isoformat() hands us both "…Z" and "…+00:00", and a string compare orders those
    two wrongly while reading perfectly well. An unparseable stamp must also not throw or jump the
    card to the top of the thread."""
    assert out["insertion"]["offsetForm"] == ["VIEW", "B"], out["insertion"]["offsetForm"]
    assert out["insertion"]["junkStamp"] == ["A", "VIEW"], out["insertion"]["junkStamp"]


@needs_node
def test_the_synthesised_card_cannot_move_the_unread_badge(out):
    """It is not a customer message and must not be counted as one. The Chat badge and the board's
    unread count come off the raw payload, which is why the thread is built after them."""
    for name in ("viewed", "viewedOnce", "unviewed"):
        assert out["scenarios"][name]["openedOn"] == "chat"
    # The tab strip's own badge markup: a project with no unread messages carries none.
    assert "tab-badge" not in out["scenarios"]["viewed"]["html"], (
        "the viewed bubble was counted as an unread customer message")


# ── 3. the files and the info sheet, in BOTH drawers ─────────────────────────
@needs_node
def test_both_drawers_offer_the_info_sheet(out):
    """"Move the info sheet button inside proposals tab." Both, because a sent project's Proposal
    panel had NO files or info-sheet control at all — the board card was its only route to its own
    paperwork, and the card's buttons are on their way out."""
    assert out["paperwork"]["sent"]["info"], "the sent drawer has no Info sheet button"
    assert out["paperwork"]["notSent"]["info"], "the not-sent drawer has no Info sheet button"
    assert out["paperwork"]["sent"]["files"], "the sent drawer has no Open the files button"
    assert out["paperwork"]["notSent"]["files"]


@needs_node
def test_the_buttons_navigate_to_the_urls_the_rest_of_the_app_uses(out):
    """Fired, not read: these are <button>s that call window.location.assign, so the URL exists
    only at click time and an href assertion would prove nothing.

    The exact strings the board card and the Proposals Database use. Two spellings of one route is
    how one of them rots — test_board_is_the_main_tab.py holds the other end of the pair."""
    assert out["paperwork"]["sent"]["nav"] == ["/done.html?d=viewed&files=1",
                                              "/info-sheet.html?d=viewed"]
    assert out["paperwork"]["notSent"]["nav"] == ["/done.html?d=notsent&files=1",
                                                 "/info-sheet.html?d=notsent",
                                                 "/?d=notsent&edit=1"]


@needs_node
def test_the_files_card_is_on_the_proposal_tab_and_visible(out):
    """A card can be rendered and still hidden: applySecPanel hides anything that is not in the
    active tab's list AND eligible, and a new card that nobody registers as eligible is invisible
    for ever. That is not hypothetical: it is what had happened to dsec-revisions, tested below."""
    s = out["scenarios"]["viewed"]
    assert "dsec-files" in out["secMap"]["proposal"], "the card is not on the Proposal tab"
    assert "dsec-files" in s["eligible"], "the card is rendered but never eligible, so it is hidden"
    assert "dsec-files" in s["tabs"]["proposal"]["shown"], (
        "the Proposal tab does not show the files card")
    # And it is NOT on any other tab.
    for sec, state in s["tabs"].items():
        if sec != "proposal":
            assert "dsec-files" not in state["shown"], (
                "the files card is also on the %s tab" % sec)


@needs_node
def test_the_sent_versions_card_is_actually_reachable(out):
    """The card nobody had ever seen. "Sent versions" shipped on 2026-08-19 complete: an id in
    SEC_TABS.proposal, markup in the Proposal panel, a fetch fired by applySecPanel, a paint
    function and a per-project cache. The one thing missing was setSecEligible, and applySecPanel
    ANDs the two, so it was hidden on every render since.

    Nothing greps for a missing call. This asserts the card off the classList the real applySecPanel
    toggled, which is what "reachable" means: rendered, eligible, and on screen when the tab it
    belongs to is."""
    s = out["scenarios"]["viewed"]
    assert "dsec-revisions" in out["secMap"]["proposal"], "the card is not on the Proposal tab"
    assert "dsec-revisions" in s["eligible"], (
        "the card renders but is never eligible, so applySecPanel hides it on every render")
    assert "dsec-revisions" in s["tabs"]["proposal"]["shown"], (
        "the Proposal tab does not show the sent versions card")
    for sec, state in s["tabs"].items():
        if sec != "proposal":
            assert "dsec-revisions" not in state["shown"], (
                "the sent versions card is also on the %s tab" % sec)
