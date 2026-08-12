"""The CRM project drawer RENDERS, and it no longer prints the customer's portal token.

WHAT HANZ ASKED FOR, 2026-08-13, with a screenshot of the drawer on a sent project:

    "Improve this Container for better UI UX remove the URL for active projects. Redesign using
    claude design."

The URL is the named part, and it was the worst part: `dsec-customer` printed
`https://portal.wetreadwell.com/p/<60-character token>` in full, underlined, wrapped over two
lines, directly under the customer's email address. Nobody reads a token. It pushed the identity
it belongs to out of the way, and `a.link { word-break:break-all }` existed for that one element.

WHY THIS FILE EXECUTES THE PANEL INSTEAD OF GREPPING IT.

On 2026-08-12 the board went down on production with `ReferenceError: STAGE_CREATED is not
defined` while every test was green, because every test asserted the source TEXT of the renderer
and none had ever run it. The drawer is the biggest block of markup in this app — five tab
panels, eight cards, a chat thread, about thirty ids a handler binds to — and until now nothing
executed a line of it. So the harness lifts the real renderDetail out of the real portal.js, binds
only the names the page itself binds, and renders four payloads shaped like production's. An
identifier the page uses without importing is an immediate ReferenceError; a card that stops
rendering shows up as a missing id in the wiring; a template that assumes a field prints the word
"undefined" and gets caught.

WHAT IT CANNOT TELL YOU. The stub answers `querySelector` out of the markup the code just wrote,
so this proves what was rendered and what was wired. It says nothing about layout or the cascade
— for those the CSS checks at the bottom assert that every class the panel emits has a rule
somewhere, which is the failure that actually happens (a renamed class rendering as bare text).
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "drawer-render-harness.js"
PORTAL_HTML = (FRONTEND / "portal.html").read_text(encoding="utf-8")


def _css(path: pathlib.Path = None) -> str:
    """A stylesheet with its comments stripped.

    Not optional politeness: this page's CSS explains a change by quoting the declaration it
    replaced — the .dtabs rule contains the words `grid-template-columns:repeat(6,1fr)` inside a
    comment saying why that is gone — so a raw grep matches the prose and passes for the wrong
    reason. It did, once, while writing these tests. Same hazard `_code()` guards against in
    test_active_projects_board.py.
    """
    src = (path or (FRONTEND / "portal.html")).read_text(encoding="utf-8")
    # Both markers, because auth.js mentions <style> while building its element and has no closing
    # tag to find. A JS file is taken whole; only a page gets narrowed to its stylesheet.
    if "<style>" in src and "</style>" in src:
        src = src[src.index("<style>"):src.index("</style>")]
    return re.sub(r"/\*.*?\*/", "", src, flags=re.S)


CSS = _css()

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

# The token in the harness's fixture URL. Kept here so the assertions can name the exact string
# that must not appear, rather than looking for "http" and hoping.
TOKEN = "gZ3liSuON-bK-jR37bxIb0psjkXmAKp8"
PORTAL_URL = "https://portal.wetreadwell.com/p/" + TOKEN

SCENARIOS = ["approved", "submitted", "sent", "bare"]
WITH_LINK = ["approved", "submitted", "sent"]          # `bare` has no customer url at all


@pytest.fixture(scope="module")
def out():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    # encoding="utf-8" explicitly: this box's locale is cp1252 and the panel is full of ·, ↗ and
    # •••• — bare text=True decodes those into mojibake or blows up outright.
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def text_of(html: str) -> str:
    """The markup with every tag removed: what a human actually reads on screen."""
    return re.sub(r"<[^>]*>", " ", html)


def attrs_named(html: str, name: str) -> list:
    return re.findall(name + r'="([^"]*)"', html)


def panel(html: str, key: str) -> str:
    """One tab panel out of the drawer's markup."""
    i = html.index('id="dpanel-%s"' % key)
    j = html.find('class="dpanel"', i)
    return html[i:j if j != -1 else len(html)]


# ── it renders at all ────────────────────────────────────────────────────────
@needs_node
@pytest.mark.parametrize("name", SCENARIOS)
def test_the_drawer_renders_without_throwing(out, name):
    """THE test. Four payloads — approved, deposit submitted with two recipients, sent and
    unapproved, and one stripped to almost nothing — executed. An unbound identifier anywhere in
    the render path lands here as a ReferenceError naming itself, which is the failure that took
    this board down on 2026-08-12 with every source assertion passing."""
    assert name not in out["errors"], out["errors"].get(name)
    assert out["scenarios"][name]["paints"] == 1, (
        "the drawer painted %s times for one render" % out["scenarios"][name]["paints"])


@needs_node
def test_every_name_the_drawer_takes_off_crm_core_really_exists(out):
    """The reverse direction of the 2026-08-12 outage: renaming an export in crm-core must fail
    here rather than in a browser. The harness raises while building its scope if portal.js asks
    for something crm-core lacks, so reaching this assertion at all is most of the proof —
    `cardTotal` is named because the drawer's head money is a new caller of it."""
    assert "cardTotal" in out["imported"], out["imported"]
    assert len(out["imported"]) >= 10, out["imported"]


@needs_node
def test_the_harness_covers_every_tab_the_drawer_has(out):
    """If somebody adds a sixth tab, these assertions have to walk it too. SEC_TABS is read out of
    the running module rather than counted here, so this cannot silently stop covering a tab."""
    assert out["tabs"] == ["proposal", "deposit", "contacts", "chat", "followup"], out["tabs"]


@needs_node
@pytest.mark.parametrize("name", SCENARIOS)
def test_no_raw_template_token_reaches_the_panel(out, name):
    """A `${…}` in the output means a template literal was built as a plain string somewhere."""
    assert "${" not in out["scenarios"][name]["html"]


@needs_node
@pytest.mark.parametrize("name", SCENARIOS)
def test_the_word_undefined_never_reaches_the_panel(out, name):
    """The `bare` fixture carries almost no fields on purpose. A template that assumes one prints
    the literal "undefined" to a rep rather than throwing, so nothing catches it except looking."""
    assert "undefined" not in out["scenarios"][name]["html"], (
        "the %s drawer printed \"undefined\" — a payload is missing a field a template assumes"
        % name)


# ── the URL, which is what he asked for ──────────────────────────────────────
@needs_node
@pytest.mark.parametrize("name", WITH_LINK)
def test_the_customer_token_is_never_printed_as_text(out, name):
    """THE ask, asserted the strict way: strip every tag and the token must not survive anywhere
    in what a human reads.

    Mutations this kills: putting the URL back as the anchor's own label; "shortening" it to
    `…/p/gZ3liSu…`, which is still a token and still unreadable; printing it inside the note that
    explains the link."""
    html = out["scenarios"][name]["html"]
    body = text_of(html)
    assert TOKEN not in body, "the customer's portal token is printed as text in the %s drawer" % name
    # Not a truncated one either — six characters of it is enough to prove a fragment leaked.
    assert TOKEN[:8] not in body


@needs_node
@pytest.mark.parametrize("name", WITH_LINK)
def test_the_token_lives_in_exactly_one_place_in_the_markup(out, name):
    """The href, and nothing else. A second copy — a data attribute holding the same string, a
    title, an aria-label — is a second thing to leak and a second thing to keep in step, and the
    copy button reads the href precisely so there is only one."""
    html = out["scenarios"][name]["html"]
    assert html.count(TOKEN) == 1, (
        "the token appears %d times in the %s drawer; it belongs in the anchor's href alone"
        % (html.count(TOKEN), name))
    for attr in ("title", "aria-label", "aria-describedby", "alt"):
        assert not any(TOKEN in v for v in attrs_named(html, attr)), (
            "the token is in a %s, which a browser prints on hover or reads aloud" % attr)


@needs_node
@pytest.mark.parametrize("name", WITH_LINK)
def test_the_customer_view_is_still_reachable(out, name):
    """Removing the URL must not remove the link. A real <a> so middle-click and open-in-new-tab
    behave, `target=_blank` because the rep is mid-task in the drawer, and `rel=noopener` because
    that tab is the customer's own view of our proposal."""
    html = out["scenarios"][name]["html"]
    m = re.search(r"<a[^>]*data-portal-link[^>]*>", html)
    assert m, "there is no link to the customer's view in the %s drawer" % name
    tag = m.group(0)
    assert 'href="%s"' % PORTAL_URL in tag, tag
    assert 'target="_blank"' in tag and "noopener" in tag, tag
    label = text_of(html[m.end():html.index("</a>", m.end())])
    assert "Open the customer" in label, (
        "the link's label is %r — it has to read as an action, which is the whole trade for "
        "dropping the URL" % label)
    assert "data-copy-portal" in html, "there is no way to copy the link"


@needs_node
def test_a_proposal_with_no_usable_customer_link_says_so_rather_than_offering_a_dead_control(out):
    """Rendering the two controls anyway would give a button that copies an empty string and a link
    to nowhere, which is worse than saying there isn't one yet."""
    html = out["scenarios"]["bare"]["html"]
    assert "data-portal-link" not in html and "data-copy-portal" not in html
    assert "no customer link yet" in html


@needs_node
def test_only_an_http_url_is_ever_put_in_the_href(out):
    """`bare`'s fixture url is `javascript:alert(document.cookie)`.

    esc() makes a value safe INSIDE an attribute and says nothing about the scheme, so without the
    scheme test that string becomes an href, and a staff click runs it against a page holding a
    bearer token. The payload comes from our own portal over a service token, so this is a belt on
    top of braces rather than a live hole — but it is one condition, and the alternative is trusting
    an upstream absolutely."""
    for name in SCENARIOS:
        html = out["scenarios"][name]["html"]
        assert "javascript:" not in html, (
            "the %s drawer put a javascript: URL in the markup" % name)
    for name in WITH_LINK:
        for href in attrs_named(out["scenarios"][name]["html"], "href"):
            assert href.startswith("http://") or href.startswith("https://"), href


# ── copy to clipboard ────────────────────────────────────────────────────────
@needs_node
def test_the_copy_button_is_wired_and_sends_the_href(out):
    """End to end: render, then fire the click the page itself bound. copyPortalLink can be
    perfect while nothing calls it, and the value it sends has to come off the anchor rather than
    from a second copy of the token kept somewhere in the markup."""
    c = out["clipboard"]["wiredClick"]
    assert c["fired"], "the copy button was never rendered"
    assert c["sent"] == PORTAL_URL, "the clipboard got %r" % (c["sent"],)
    assert c["label"] == "Link copied", c["label"]
    assert c["said"], "nothing told the rep it worked"


@needs_node
def test_a_successful_copy_puts_its_label_back(out):
    """The confirmation is temporary on purpose: a button permanently reading "Link copied" is a
    button that looks disabled. So both states are asserted — what it says when the copy lands,
    and what it says after the one timer runs."""
    c = out["clipboard"]["works"]
    assert c["ok"] is True
    assert c["label"] == "Link copied", (
        "the button says %r on success, so nothing on screen confirms the copy" % c["label"])
    assert c["timers"] == 1
    assert c["afterTimers"] == "Copy the link", c["afterTimers"]


@needs_node
@pytest.mark.parametrize("case", ["absent", "noWriteText", "rejects", "throwsSync"])
def test_a_blocked_clipboard_never_leaves_a_dead_button(out, case):
    """navigator.clipboard is absent on an insecure origin, `{}` in a browser that exposes the
    object without the method, and rejects outright on a denied permission. All three used to be
    reachable ways to strand the one control that replaced the URL.

    What this pins: the promise is caught, the label goes back to something clickable, and the
    message names the way out that always works. Mutation it kills: dropping the try/catch, or
    setting a "Copying…" label that the failure path never clears."""
    c = out["clipboard"][case]
    assert c["ok"] is False
    assert c["label"] == "Copy the link", (
        "the button is left reading %r after a failed copy" % c["label"])
    assert "Open the customer" in c["said"], (
        "the failure says %r, which does not tell the rep what to do instead" % c["said"])
    assert c["timers"] == 0, "a failure scheduled a label reset it does not need"


# ── the wiring, and the cards ────────────────────────────────────────────────
# Ids the panel deliberately does not always render, with the state that decides. wireFollowup
# and applySecPanel both look these up unconditionally and guard on the result, which is correct
# — what must not happen is a NEW name joining this list by accident.
CONDITIONAL_IDS = {
    "dsec-recipients": "only rendered for two or more recipients",
    "dsec-approved": "only rendered once somebody has approved",
    "fu-reopen": "only rendered on a closed-lost proposal",
    "fu-delay": "not rendered on a closed-lost proposal",
    "fu-lost": "not rendered on a closed-lost proposal",
    "fu-add-contact": "only rendered when the portal knows a recipient",
    "fu-add-contact-btn": "only rendered when the portal knows a recipient",
}


@needs_node
@pytest.mark.parametrize("name", SCENARIOS)
def test_every_id_the_wiring_reaches_for_was_rendered_by_that_paint(out, name):
    """A handler bound to an id nobody rendered is a control that silently does nothing. Two
    versions of that bug have shipped from this file, and both were found by grep — which cannot
    see a lookup inside a conditional branch. This sees the real lookups from the real render.

    The allowlist is the point: anything else missing is a genuine mismatch. `cust-copy-say`
    joining it would mean the copy status line stopped rendering while the code still writes into
    it, which is how a message goes silently nowhere."""
    missing = set(out["scenarios"][name]["missing"])
    unexpected = missing - set(CONDITIONAL_IDS)
    assert not unexpected, (
        "the %s drawer wires ids it never rendered: %s" % (name, sorted(unexpected)))


@needs_node
@pytest.mark.parametrize("name", SCENARIOS)
def test_every_card_marked_eligible_actually_exists(out, name):
    """SEC_ELIGIBLE says which cards apply; SEC_TABS says which tab shows them. A card in one and
    not the other renders an empty panel, and the portal has shipped that twice. Executed, so it
    covers the eligibility calls as the payload actually drives them."""
    s = out["scenarios"][name]
    for sec in s["eligible"]:
        assert 'id="%s"' % sec in s["html"], (
            "%s is marked eligible on the %s drawer but nothing renders it" % (sec, name))


@needs_node
def test_the_two_conditional_cards_appear_exactly_when_they_should(out):
    """The other direction: eligibility must track the payload, not be hardcoded on. Recipients is
    for two or more contacts; Approved needs an approval."""
    assert "dsec-recipients" in out["scenarios"]["submitted"]["eligible"], (
        "the two-recipient payload did not get the Recipients card")
    for one in ("approved", "sent", "bare"):
        assert "dsec-recipients" not in out["scenarios"][one]["eligible"]
    assert "dsec-approved" in out["scenarios"]["approved"]["eligible"]
    for none in ("sent", "bare"):
        assert "dsec-approved" not in out["scenarios"][none]["eligible"]


# ── the tab strip ────────────────────────────────────────────────────────────
@needs_node
@pytest.mark.parametrize("name", SCENARIOS)
def test_each_tab_shows_its_own_cards_and_hides_the_rest(out, name):
    """applySecPanel is the ONLY thing allowed to touch visibility, and this is the claim that
    makes it worth the rule: switching tab shows exactly the eligible cards of THAT tab and
    nothing from any other. Run per tab, per payload, off the classList the real function toggled.

    Asserted as set EQUALITY, and that is the whole strength of it. The first version of this test
    only checked that every visible card was eligible, and a mutation dropping the SEC_TABS
    membership test — `toggle("hidden", !SEC_ELIGIBLE.has(id))`, which puts the chat thread, the
    deposit buttons and the follow-up log on the Proposal tab all at once — sailed through it,
    because every one of those cards is perfectly eligible. Equality is what notices."""
    s = out["scenarios"][name]
    eligible = set(s["eligible"])
    for sec, state in s["tabs"].items():
        assert state["panels"] == [sec], (
            "the %s tab shows panels %s" % (sec, state["panels"]))
        expect = set(out["secMap"][sec]) & eligible
        assert set(state["shown"]) == expect, (
            "the %s tab of the %s drawer shows %s; it should show exactly %s"
            % (sec, name, sorted(state["shown"]), sorted(expect)))
        assert state["shown"], "the %s tab of the %s drawer shows nothing at all" % (sec, name)


@needs_node
@pytest.mark.parametrize("name", SCENARIOS)
def test_exactly_one_step_reads_as_selected(out, name):
    """aria-selected is set in the same loop as the class precisely so a screen reader can never
    disagree with what is painted. Two selected steps, or none, is that promise broken."""
    for sec, state in out["scenarios"][name]["tabs"].items():
        assert state["selectedSteps"] == 1, (
            "the %s tab has %s selected steps" % (sec, state["selectedSteps"]))


@needs_node
def test_the_drawer_opens_on_the_tab_that_needs_a_human(out):
    """defaultSection answers "why is this drawer open?". A customer message beats everything, an
    unconfirmed payment comes next, and everything else lands on Proposal. Executed rather than
    read, because the routing is four conditions over three fields and the wrong order reads
    perfectly well in source."""
    assert out["scenarios"]["sent"]["openedOn"] == "chat", "two unread messages did not win"
    assert out["scenarios"]["submitted"]["openedOn"] == "deposit", (
        "money in and unconfirmed did not win")
    assert out["scenarios"]["approved"]["openedOn"] == "proposal"
    assert out["scenarios"]["bare"]["openedOn"] == "proposal"


# ── the redesign's information design ────────────────────────────────────────
@needs_node
def test_the_head_carries_the_customer_and_the_money(out):
    """New on 2026-08-13. Both facts used to live on the Proposal tab only, so answering "whose
    job is this and what is it worth" while replying on the Chat tab meant a tab change and a tab
    change back."""
    html = out["scenarios"]["approved"]["html"]
    head = html[:html.index('class="dtabs"')]
    assert "HANZ URIEL A DE LA CRUZ" in head, "the head does not say who it is for"
    assert "$22,763.00" in head, "the head does not say what it is worth"
    assert 'class="dh-amt amt"' in head, (
        "the head's money is not marked as money, so it loses tabular figures")


@needs_node
def test_the_head_calls_it_approved_only_when_somebody_approved_it(out):
    """The portal names the field `approved_total` on every row, sent ones included, so the lazy
    version of this line calls a live bid "Approved" and puts a word on it nobody has earned."""
    approved = out["scenarios"]["approved"]["html"]
    sent = out["scenarios"]["sent"]["html"]
    assert "Approved $22,763.00" in approved
    assert "Bid $41,250.00" in sent, "an unapproved proposal's total is not labelled as a bid"
    assert "Approved $" not in sent[:sent.index('class="dtabs"')]


@needs_node
def test_the_approval_is_labelled_facts_rather_than_a_sentence(out):
    """It used to read "HANZ URIEL A DE LA CRUZ on 2026-08-10 — Polish, Epoxy at $22,763.00",
    which buries the money and the date mid-sentence inside a name in capitals. The signed-in
    address stays, because it is the one thing here that can differ from the typed name."""
    card = out["scenarios"]["approved"]["html"]
    card = card[card.index('id="dsec-approved"'):]
    card = card[:card.index('id="dsec-notify"')]
    for key in ("Amount", "What they took", "Date", "Signed by"):
        assert ">%s<" % key in card, "the approval card lost its %s cell" % key
    assert 'class="amt amt-lg">$22,763.00' in card, "the approved total is not the card's figure"
    assert "signed in as hdlcruz03@gmail.com" in card


@needs_node
def test_the_deposit_says_the_amount_the_reference_and_when_it_went_out(out):
    """One run-on line of middots became three labelled cells. "Match on the statement" is the
    phrasing a bookkeeper uses; `match ref` was ours."""
    card = panel(out["scenarios"]["approved"]["html"], "deposit")
    for key in ("Deposit at 25%", "Match on the statement", "Invoice sent"):
        assert ">%s<" % key in card, "the deposit card lost its %s cell" % key
    assert 'class="amt">$5,690.75' in card
    assert "TW-4821" in card
    # The two actions are what the tab is FOR, so they stay buttons and stay side by side.
    assert 'id="send-deposit-req"' in card and 'id="mark-deposit"' in card


@needs_node
def test_the_contacts_lead_with_the_role(out):
    """"Who do I call about access" is the question this card gets opened for. It was three grey
    paragraphs of "Primary: Dave Smith · dave@x.com · (913) 555-0134"."""
    card = panel(out["scenarios"]["approved"]["html"], "contacts")
    assert card.count('class="ct"') == 2, "the two contacts did not both render"
    assert '<div class="ct-role">Primary</div>' in card
    assert '<div class="ct-role">Accounts payable</div>' in card, (
        "the role label came out raw instead of through ROLE_LABEL")
    assert "(913) 555-0134" in card


@needs_node
def test_an_empty_contacts_card_says_who_has_not_sent_them(out):
    card = panel(out["scenarios"]["sent"]["html"], "contacts")
    assert "customer has not sent" in card


@needs_node
@pytest.mark.parametrize("name", SCENARIOS)
@pytest.mark.parametrize("sec", ["proposal", "deposit", "contacts", "followup"])
def test_no_em_dash_in_the_panels_copy(out, name, sec):
    """House rule for UI copy. Chat is excluded and only Chat: the portal writes its own system
    lines as "Heading — detail" and splitSystem splits on exactly that separator, so those dashes
    are inbound data rather than our words."""
    assert "—" not in panel(out["scenarios"][name]["html"], sec), (
        "an em dash reached the %s panel of the %s drawer" % (sec, name))


# ── the poll must stay invisible ─────────────────────────────────────────────
@needs_node
@pytest.mark.parametrize("name", SCENARIOS)
def test_an_identical_repaint_is_skipped(out, name):
    """The 12s drawer poll re-renders this panel. Unguarded, it destroys and rebuilds the thread,
    the tab strip and every card four times a minute, which is the blink Hanz reported on
    2026-08-08 ("Why does this keep blinking?").

    EXECUTED, not read. test_no_blink_live_refresh.py asserts the guard is present in the source;
    this asserts it actually stops the paint — which a signature over the wrong value would pass
    the first check and fail the second."""
    assert out["scenarios"][name]["repaintedOnIdenticalPayload"] is False, (
        "the %s drawer repaints on an unchanged payload" % name)


@needs_node
@pytest.mark.parametrize("name", SCENARIOS)
def test_a_changed_payload_still_repaints(out, name):
    """The other half, and the one a too-clever guard breaks: a frozen drawer looks exactly like a
    working one until the customer does something."""
    assert out["scenarios"][name]["repaintedOnChange"] is True, (
        "the %s drawer did not repaint after the payload changed" % name)


@needs_node
def test_the_not_sent_panel_keeps_its_actions_and_its_guard(out):
    """The Created-but-not-sent drawer shares the head, the fact cells and the layout column with
    the real one, so a rep does not re-learn the panel. What it must not grow is a tab strip: six
    of the seven tabs would be empty."""
    ns = out["notSent"]
    assert ns["chars"] > 400, "the not-sent panel rendered almost nothing"
    assert not ns["missing"], "it wires ids it never rendered: %s" % ns["missing"]
    assert ns["repaintedOnIdenticalPayload"] is False, "the not-sent panel repaints on every poll"
    assert "dtabs" not in ns["html"], "the tab strip is rendered for a project with no portal row"
    assert "data-go-files" in ns["html"] and "data-go-edit" in ns["html"]
    assert 'class="dclose"' in ns["html"]
    assert 'class="amt">$88,000.00' in ns["html"], "the bid is not rendered as money"


# ── the bank numbers ─────────────────────────────────────────────────────────
@needs_node
def test_the_account_number_reaches_the_dom_only_when_a_human_asks(out):
    """Unchanged behaviour, asserted for the first time by running it. The markup ships masked and
    the full value lives in a closure array; Show swaps it in and a second press puts it back."""
    r = out["scenarios"]["submitted"]["reveal"]
    assert r, "the deposit submission card did not render its Show control"
    assert r["inMarkup"] is False, "the full account number is in the markup before anyone asks"
    assert r["shown"] == "12345678901", "Show did not reveal the number"
    assert r["remasked"] == "••••8901", "a second press did not re-mask it"
    assert r["label"] == "Show" and r["pressed"] == "false", (
        "the control does not go back to its unpressed state")


# ── the notification chips: presentation changed, behaviour did not ──────────
@needs_node
def test_the_chips_are_still_every_person_with_only_some_on(out):
    """Hanz confirmed the partly-off roster is deliberate, so this is a guard against a "tidy-up"
    that hides the off ones or turns them on. Nine people, four receiving."""
    n = out["scenarios"]["approved"]["notify"]
    assert n["count"] == 9, "the strip drew %s chips for a roster of nine" % n["count"]
    assert n["on"] == 4, (
        "%s chips read as on; the fixture is three enabled on the roster, two added for this "
        "project and one muted, so the effective answer is four" % n["on"])


@needs_node
def test_the_chips_say_how_many_are_on_before_you_count_them(out):
    """New on 2026-08-13, and derived: nine chips of which some are green is a thing you have to
    count. It names you when you are one of them, because "am I on this one?" is the question
    people ask about their own name."""
    n = out["scenarios"]["approved"]["notify"]
    assert n["summary"].startswith("4 of 9 people get"), n["summary"]
    assert n["summary"].endswith("including you."), n["summary"]


@needs_node
def test_the_notify_help_still_promises_that_toggling_sends_nothing(out):
    """The sentence people act on. Somebody has to be able to turn themselves off a noisy project
    without wondering whether the customer just got an email."""
    card = out["scenarios"]["approved"]["html"]
    card = card[card.index('id="nt-help"'):]
    card = card[:card.index("</p>")]
    assert "never sends" in card, card
    assert "Green" in card, "the colour is no longer explained, and it is the only state signal"


# ── the CSS side: a class with no rule renders as bare text ──────────────────
def _defined_classes() -> set:
    """Every class name portal.html's stylesheet or auth.js's injected sheet declares a rule for.

    Comments stripped from both, or a class mentioned only in prose would count as styled — and
    these files talk about their own classes constantly."""
    return set(re.findall(r"\.(-?[_a-zA-Z][\w-]*)",
                          CSS + _css(FRONTEND / "auth.js")))


@needs_node
@pytest.mark.parametrize("name", SCENARIOS)
def test_every_class_the_drawer_emits_has_a_rule_somewhere(out, name):
    """The failure this catches is mundane and invisible in a diff: markup naming a class the
    stylesheet does not have. It does not throw, it does not warn, it renders as unstyled text in
    the middle of a styled panel — which is precisely what `.rc-b`'s `var(--surf-dim)` was doing,
    a token defined nowhere, silently voiding the border on every recipient badge.

    Both files, because the person chip (.tw-av) is styled once in auth.js on purpose."""
    s = out["scenarios"][name]
    emitted = set()
    for group in re.findall(r'class="([^"]*)"', s["html"] + s["written"]):
        emitted.update(c for c in group.split() if c)
    missing = sorted(emitted - _defined_classes())
    assert not missing, "the %s drawer uses classes nothing styles: %s" % (name, missing)


def test_the_customer_cards_link_button_is_styled_for_an_anchor():
    """`.btn` is written for <button>: no display, no text-decoration reset. An <a class="btn">
    renders as underlined inline text, which is why the toolbar's own link carries three inline
    style properties to compensate. The rule exists so this one does not have to."""
    assert re.search(r"\.btn\.is-link\s*\{[^}]*text-decoration:\s*none", CSS), (
        "an anchor styled as a button has no rule, so it renders underlined and inline")


def test_the_money_class_actually_asks_for_tabular_figures():
    assert re.search(r"\.amt\s*\{[^}]*font-variant-numeric:\s*tabular-nums", CSS)


def test_the_removed_url_took_its_styling_with_it():
    """`a.link { word-break:break-all }` existed for one element: the portal URL. Leaving the rule
    behind is how the next person concludes there is a link class to reuse."""
    assert not re.search(r"^\s*a\.link\s*\{", CSS, re.M), (
        "the rule written for the printed URL is still in the stylesheet")


def test_the_panel_spaces_itself_by_layout_rather_than_per_element_margins():
    """A card is hidden by class (applySecPanel toggles .hidden), so spacing carried by each
    card's own bottom margin leaves a hole where a hidden one was. The gap belongs to the
    container. This also pins the reason .sec no longer carries margin-bottom:20px."""
    assert re.search(r"\.dpanel\s*\{[^}]*display:flex[^}]*gap:", CSS)
    assert re.search(r"\.sec\s*\{[^}]*gap:", CSS)
    assert not re.search(r"\.sec\s*\{[^}]*margin-bottom:\s*20px", CSS)
    # .row3 has to state its direction, or `class="sec row3"` (the not-sent panel's button row)
    # inherits column and stacks the two buttons.
    assert re.search(r"\.row3\s*\{[^}]*flex-direction:row", CSS)
