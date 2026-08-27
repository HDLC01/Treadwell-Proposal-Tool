"""A send whose PDF is older than the pricing must be refused BEFORE it goes out.

THE REPORT, 2026-08-26, 11:47pm. An estimator, on a proposal he had just re-priced:

    "I revised a proposal and am getting the error message in yellow below. I think it's
     sending an outdated proposal. Not sure what's happening."

He was right about all three things. It was sending an outdated proposal, the yellow message
did say so, and he could not tell what was happening.

WHY. One revision carries two descriptions of the same pricing. The portal page a customer
opens is rendered from the top-level `rooms`; the PDF beside it is re-rendered from
`proposal_payload`, and that sub-object is written by exactly ONE line of code, in the Proposal
step's Continue handler. Revise the pricing, go to Files, send: the customer gets today's page
and last week's document.

WHY THE OLD FIX WAS NOT A FIX. The warning was rendered from the publish RESPONSE. By the time
it appeared the portal row was written, the revision was pinned, and the email was in the
customer's inbox. It then read: "the customer's PDF is out of date ... Open the Proposal step,
press Continue, then re-send. Reload this page to see the sent version, then re-send if that's
wrong." That is an apology with a treasure hunt attached, addressed to somebody who reads bids
and not code.

WHAT THIS PINS. The verdict is now reached BEFORE the request: after `TW.flushState()`, which
is the moment this browser's blob and the server's copy are the same blob, and before
`/api/portal/publish`, which is the moment a portal row and an email exist. A drifted send
never starts, the estimator is shown the two sets of numbers, and one button takes them to the
step that rebuilds the document.

BOTH CHECKS SURVIVE ON PURPOSE. The gate cannot see drift that arrives from a second tab,
another device, or a colleague editing between the flush and the write. The post-send warning
(test_publish_race.py) reads the snapshot the server actually took, so it still speaks up in
those cases. Belt and braces: a send that lands drifted must never land silently.

EXECUTED, NOT GREPPED. `localPublishDigest` mirrors the server's `_publish_digest`, and a
mirror that disagrees with the original is worse than no mirror: it would clear a send the
server refuses, or refuse one the server would take. The mirror is run against the real blob
shapes from the incident. The 2026-08-12 outage settled what source-text assertions are worth:
the string was present, the identifier was unbound, and the board was dead.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "stale-document-harness.js"

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


# ── the verdict, before anything is sent ─────────────────────────────────────
@needs_node
def test_the_drift_is_visible_from_the_draft_alone(ran):
    """THE test. Every previous version of this check needed the publish RESPONSE, which is why
    the estimator only ever heard about it after the customer did. Both halves are in the blob
    the browser is already holding, so the answer is available with no request at all."""
    rows = ran["verdict"]["drifted"]
    assert rows, "a revised project with a frozen document reads as clean — the gate is blind"
    assert {r["k"] for r in rows} == {"Price", "Base bid"}, rows


@needs_node
def test_the_refusal_names_the_numbers(ran):
    """The numbers are the proof. "Something is out of date" is what the estimator could not
    act on; $13,265 against $18,670 is a fact he can check against his own sheet."""
    rows = {r["k"]: r for r in ran["verdict"]["drifted"]}
    assert rows["Price"]["pdf"].replace(",", "") == "$13265"
    assert rows["Price"]["now"].replace(",", "") == "$18670"
    assert (rows["Base bid"]["pdf"], rows["Base bid"]["now"]) == ("Polish", "Epoxy")


@needs_node
def test_the_words_read_as_english(ran):
    """The prose form is what the post-send warning quotes, and it has to survive being read
    once, at midnight, by somebody who did not write it."""
    say = ran["verdict"]["driftedSay"]
    assert "a price of $13,265, not $18,670" in say, say
    assert "Polish as the base bid, not Epoxy" in say, say
    for jargon in ("drift", "snapshot", "payload", "revision", "digest"):
        assert jargon not in say.lower(), "%r reached the estimator's screen: %s" % (jargon, say)


@needs_node
def test_a_clean_project_sends_with_no_interruption(ran):
    """A gate that fires on correct sends is a gate somebody switches off. This is the shape
    every send has after a Continue, which is nearly all of them."""
    assert ran["verdict"]["agreed"] == []


@needs_node
def test_a_project_with_no_document_yet_is_not_blocked(ran):
    """Nothing has been generated, so there is nothing to be stale. Blocking here would stop
    first sends on brand-new projects — the gate would break the normal path to fix the rare
    one."""
    assert ran["verdict"]["noPayload"] == []


@needs_node
def test_a_base_only_proposal_is_not_blocked(ran):
    """Single-system proposals carry no base ROOM in either half, so the base label is null on
    both sides and the price comes from the payload's own lump sum. This is the most common
    shape this tool produces; treating null as a difference would refuse all of them."""
    assert ran["verdict"]["baseOnly"] == []


@needs_node
def test_a_deliberately_hidden_option_is_not_a_difference(ran):
    """Both halves must count PICKABLE options the same way, the same `show !== false` rule the
    portal and the document use. Counting hidden ones would refuse every send carrying an option
    the estimator chose not to show."""
    assert ran["verdict"]["hiddenOption"] == []


@needs_node
def test_a_page_with_no_price_of_its_own_is_not_blocked(ran):
    """Both figures have to exist before they can disagree. A page that has lost its own lump
    sum tells us nothing about the document, and the refusal would have read "a price of
    $18,670, not $—" — which is the kind of message that started this whole report."""
    assert ran["verdict"]["pageLostItsPrice"] == []


@needs_node
def test_sub_cent_rounding_is_not_a_difference(ran):
    """Floating point must not refuse a send: 18670.004 and 18670 are the same money."""
    assert ran["verdict"]["subCent"] == []


@needs_node
def test_it_reads_the_field_the_DOCUMENT_RENDERER_reads(ran):
    """`proposal_payload.rooms` is what fills the PDF's price table. `values.rooms` is an inert
    echo of the page state travelling beside it, and it is usually correct — which is exactly
    what makes it dangerous. Following the echo would clear a send whose PDF prints the old base
    bid, the same class of mistake as the bug the gate exists to catch."""
    rows = ran["verdict"]["echoTrap"]
    assert rows, "the check followed values.rooms, not the field the renderer reads"
    assert "Base bid:Polish>Epoxy" in rows, rows


@needs_node
def test_a_malformed_draft_never_throws(ran):
    """This runs on the click of the Send button. An exception here would take Send out of
    service altogether and leave the estimator unable to send anything at all — a worse outage
    than the bug. Every unreadable shape has to fall through to "no evidence of a problem"."""
    for result in ran["verdict"]["junk"]:
        assert result == 0, result


# ── the mirror: the browser's verdict must be the server's verdict ───────────
# The keys the two sides share. `base_tab_id` is server-only: it is a worksheet id ("Copy1")
# and means nothing to a person, so the page has no use for it.
_SHARED = ("base_label", "lump_sum", "option_count",
           "has_document", "doc_base_label", "doc_lump_sum", "doc_option_count")


@needs_node
@pytest.mark.parametrize("case", [
    "drifted", "agreed", "noPayload", "baseOnly", "hiddenOption",
    "emptyDraft", "junkRooms", "junkPayload", "payloadNoValues",
])
def test_the_browser_reaches_the_same_verdict_as_the_server(ran, case):
    """THE invariant that makes a client-side gate safe. `localPublishDigest` is a copy of
    `_publish_digest`, and the two must read every field the same way: the same `show !== false`
    option rule, the same base-only fallback to the payload's own lump sum, the same "we cannot
    read this" answer on a malformed blob.

    A copy that disagrees is worse than no copy. Too strict and it refuses a send the server
    would have taken, leaving a proposal that cannot go out at all; too loose and it clears one
    the server refuses, which is a dead Send button with nothing on screen explaining it.

    The blob travels from the harness so both sides digest the identical input."""
    import main
    entry = next(e for e in ran["mirror"] if e["name"] == case)
    server = main._publish_digest(entry["blob"])
    browser = entry["digest"]
    for key in _SHARED:
        assert browser[key] == server[key], (
            "%s: the browser says %s=%r, the server says %r" % (case, key, browser[key], server[key]))


# ── the panel: what the estimator actually reads ─────────────────────────────
@needs_node
def test_the_blocked_message_says_nothing_was_sent(ran):
    """The first thing he needs to know. The old message arrived after the email had gone, so
    "what went to the customer" was the truth then and would be a lie now — and a person who
    thinks a wrong proposal has already gone out does something drastic about it."""
    lede = ran["panel"]["blocked"]["lede"]
    assert lede.startswith("Nothing was sent."), lede
    assert ran["panel"]["blocked"]["hidden"] is False


@needs_node
def test_the_panel_shows_both_columns_with_headings(ran):
    """Two numbers side by side with no labels is a riddle. The headings are what make the
    struck-through column mean "this is what the customer would get"."""
    table = ran["panel"]["blocked"]["table"]
    assert "The PDF says" in table and "It should say" in table, table
    assert "$13,265" in table and "$18,670" in table, table
    assert "Polish" in table and "Epoxy" in table, table


@needs_node
def test_the_opening_line_changes_with_what_happened(ran):
    """Same three numbers, three different situations: found on arrival, refused at the click,
    already gone. Telling them apart is the difference between "fix this before you send" and
    "the customer has this now", and the estimator must not have to work out which."""
    p = ran["panel"]
    assert p["mount"]["lede"] != p["blocked"]["lede"] != p["sent"]["lede"]
    assert "already gone to the customer" in p["sent"]["lede"], p["sent"]["lede"]
    assert "Sending now" in p["mount"]["lede"], p["mount"]["lede"]


@needs_node
def test_the_panel_takes_itself_away_when_there_is_nothing_wrong(ran):
    """A stop sign left standing after the thing it stopped is fixed is a stop sign nobody reads
    the next time it matters."""
    assert ran["panel"]["cleared"]["hidden"] is True


@needs_node
def test_the_blocked_panel_scrolls_itself_into_view(ran):
    """The Send button is at the bottom of a long column. A refusal painted above the fold is a
    click that appears to have done nothing, and the estimator clicks it again."""
    assert ran["panel"]["blocked"]["scrolled"] is True


@needs_node
def test_a_worksheet_name_arrives_as_TEXT(ran):
    """A base bid's name is a label the estimator typed into a worksheet, which makes it the one
    string in this panel that came from outside the page."""
    raw = ran["panel"]["rawName"]
    assert "<b>Polish</b>" in raw and "<img src=x>" in raw, raw
    assert ran["panel"]["usesInnerHtml"] is False, "the panel builds rows with innerHTML"


# ── the wiring: WHERE the gate sits ──────────────────────────────────────────
# Source order, and said out loud: the verdict above is executed against real blobs, but "no
# request went out" is a claim about a position inside a handler that needs the whole page to
# run. These indices are what make the executed verdict matter.
@needs_node
def test_the_gate_sits_between_the_save_and_the_publish(ran):
    """AFTER the flush, because that is the moment this browser's blob and the server's copy are
    the same blob, so the verdict is about what the publish would actually snapshot. BEFORE the
    publish, because that is the moment a portal row is written and an email leaves."""
    w = ran["wiring"]
    assert w["gateAfterFlush"], "the check runs before the save, so it judges a stale blob"
    assert w["gateBeforePublish"], "the check runs after the send — that is the old bug back"


@needs_node
def test_a_refused_send_leaves_the_handler(ran):
    """Showing the panel and falling through would send the stale document anyway, with a
    warning painted next to it."""
    assert ran["wiring"]["gateReturns"]


@needs_node
def test_a_refused_send_gives_the_button_back(ran):
    """Otherwise the refusal leaves a dead "Sending…" button and the only way out is a reload,
    which is how an estimator loses a typed customer message."""
    assert ran["wiring"]["gateRestoresButton"]


@needs_node
def test_the_problem_is_also_shown_on_arrival(ran):
    """Before recipients, before the message, before the deposit decision. The gate is what
    refuses; this is so the refusal is not the first the estimator hears of it."""
    assert ran["wiring"]["checkedOnMount"]


@needs_node
def test_the_post_send_warning_is_not_replaced_by_the_gate(ran):
    """Belt AND braces. The gate reads this browser's state; it cannot see an edit made in a
    second tab between the flush and the write. The post-send check reads the snapshot the
    server actually took, so it still catches those — and a drifted send must never be
    silent."""
    assert ran["wiring"]["keepsPostSendWarning"]


@needs_node
def test_the_one_button_goes_to_the_step_that_can_fix_it(ran):
    """The document payload is written by one line, in the Proposal step's Continue handler,
    from machinery that exists only on that page. Re-deriving the money on the Files page would
    be a second copy of the token mapping — which is how the two halves came apart to begin
    with."""
    assert ran["wiring"]["fixButtonGoesToTheProposalStep"]


# ── the markup the panel needs ───────────────────────────────────────────────
def test_the_panel_cannot_be_defeated_by_its_own_class():
    """`.stale-doc` sets `display:flex`, and a class `display` beats the plain `hidden`
    attribute on specificity. Without the `[hidden]` rule the stop sign is on screen for every
    project, on every send, forever. Four separate live instances of this exact bug have shipped
    in this repo."""
    done = (FRONTEND / "done.html").read_text(encoding="utf-8")
    assert ".stale-doc { display:flex" in done
    assert ".stale-doc[hidden] { display:none; }" in done


def test_the_panel_is_an_alert_and_sits_above_the_send_button():
    """Read out to a screen reader when it appears, and last on the page before the irreversible
    click. A warning below the button it is warning about is a warning nobody sees."""
    done = (FRONTEND / "done.html").read_text(encoding="utf-8")
    i_panel = done.index('id="stale-doc"')
    i_send = done.index('id="portal-btn"')
    assert i_panel < i_send, "the stop sign is below the Send button"
    assert 'role="alert"' in done[i_panel - 200:i_panel + 200]


def test_the_warning_family_is_still_amber():
    """Amber, not the grey hint colour it sits among, and the same amber as every other warning
    in this tool. A stop sign styled as one more piece of help text is one nobody acts on."""
    done = (FRONTEND / "done.html").read_text(encoding="utf-8")
    assert ".stale-doc" in done and "#fdf6e3" in done and "#7a5c00" in done


def test_the_fix_control_says_what_it_does():
    """"Update the PDF" is the same words the warning uses, so the sentence the estimator reads
    names the button he then presses. The old message named neither."""
    done = (FRONTEND / "done.html").read_text(encoding="utf-8")
    assert 'id="stale-doc-fix"' in done
    i = done.index('id="stale-doc-fix"')
    assert "Update the PDF" in done[i:i + 120]
