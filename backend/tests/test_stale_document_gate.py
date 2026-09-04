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

EXECUTED, NOT GREPPED. `TW.publishDigest` mirrors the server's `_publish_digest`, and a
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
    """THE invariant that makes a client-side gate safe. `TW.publishDigest` is a copy of
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


# ── the Proposal step: why the estimator is standing there ───────────────────
# The Files page refuses the send and offers one button. That button lands on this step, and the
# coordinator's ruling on 2026-08-27 was explicit about what must NOT happen next: no auto-firing
# Continue. "Auto-firing Continue and bouncing the estimator back to Files gives them a
# regenerated document they never saw, which is the same failure wearing better clothes. The
# reason landing on the Proposal step is correct is that the document is on screen there."
@needs_node
def test_the_arrival_line_names_the_same_figures_as_the_refusal(ran):
    """Somebody who followed a control across a page boundary must not have to remember what the
    previous page told them. Same rows, same words, same numbers, from the same function."""
    sentence = ran["arrival"]["sentence"]
    assert "$13,265" in sentence and "$18,670" in sentence, sentence
    assert "Polish as the base bid, not Epoxy" in sentence, sentence


@needs_node
def test_the_arrival_line_NEVER_presses_continue(ran):
    """THE test on this half, and the one rule this whole defect exists to teach: never send a
    document nobody has looked at. Regenerating behind the estimator and returning them to Files
    would produce a correct PDF that no human had seen, which is the same bug with better
    numbers. Continue is focused and named. It is not fired."""
    assert ran["arrival"]["present"], "the arrival explanation is gone"
    assert ran["arrival"]["autoSubmits"] is False, (
        "something on arrival submits, clicks or rebinds Continue — the estimator never sees "
        "the document they are about to send")


@needs_node
def test_continue_is_made_unmissable_without_disabling_anything(ran):
    """Focused, so a keyboard user is already on it, and scrolled into view. The page is not
    hijacked: nothing else is disabled and no other control is moved."""
    assert ran["arrival"]["focusesContinue"]


@needs_node
def test_the_arrival_line_only_appears_when_the_files_page_sent_them(ran):
    """`resync=1` is the signal. An estimator who opened this step to edit the scope wording has
    no reason to be told about a document they were not warned about."""
    assert ran["arrival"]["readsTheFlag"]


@needs_node
def test_the_arrival_line_stays_quiet_on_a_project_already_fixed(ran):
    """Arriving with the flag on a project whose halves now agree (a second visit, a Back
    button) must say nothing. Telling somebody off for a problem they already fixed is how a
    warning gets ignored the next time it is real."""
    assert ran["arrival"]["silentWhenClean"]


@needs_node
def test_the_arrival_line_reads_fresh_state(ran):
    """`const state = TW.getState()` at the top of proposal-review.js is a ONE-SHOT snapshot,
    and a draft arriving from the server a moment later changes both halves. A figure painted
    from the snapshot could be a figure that is no longer true."""
    assert ran["arrival"]["readsFreshState"]


@needs_node
def test_both_pages_use_ONE_comparison(ran):
    """The Files page gates the send on it; the Proposal step explains it. A second copy on the
    second page is precisely the two-descriptions-of-one-truth mistake that produced this bug —
    the portal page and the PDF each describing the same pricing, drifting apart in silence."""
    assert ran["arrival"]["usesTheSharedComparison"]


def test_the_comparison_lives_in_shared_js_not_on_a_page():
    """It moved out of done.js the moment a second page needed the same answer. Two callers, one
    definition; and shared.js is where the draft blob already lives."""
    shared = (FRONTEND / "shared.js").read_text(encoding="utf-8")
    assert "function publishDigest(s)" in shared and "function docDrift(d)" in shared
    assert "publishDigest," in shared and "docDrift," in shared, (
        "the functions exist but are not exported on TW")
    done = (FRONTEND / "js" / "done.js").read_text(encoding="utf-8")
    assert "function docDriftRows" not in done and "function localPublishDigest" not in done, (
        "a second copy is still sitting on the Files page")


def test_the_arrival_note_is_pinned_chrome_and_announced():
    """A sibling of the formatting ribbon, so it sits in the permanently-visible chrome above the
    scrolling canvas instead of scrolling away while it is being read. `role="status"` so a
    screen reader hears it without the focus having to move."""
    html = (FRONTEND / "proposal-review.html").read_text(encoding="utf-8")
    i_ribbon = html.index('id="fmt-ribbon"')
    i_note = html.index('id="resync-note"')
    i_canvas = html.index('id="fields-panel"')
    assert i_ribbon < i_note < i_canvas, "the note is not in the chrome above the canvas"
    assert 'role="status"' in html[i_note - 120:i_note + 120]
    # Same trap as the Files panel: a class `display` outranks the `hidden` attribute.
    assert ".resync-note { display:flex" in html
    assert ".resync-note[hidden] { display:none; }" in html
    # One warning colour across the tool.
    assert "#fdf6e3" in html and "#7a5c00" in html


# ── the server's refusal, when it beats the gate to it ───────────────────────
# `POST /api/portal/publish` answers 409 with `code: "stale_document"` and writes nothing: no
# portal row, no email. Three layers now, and each one covers what the one before it cannot.
# The gate reads THIS browser's blob. The server reads the blob it is about to snapshot, which
# is the one that counts when an edit lands from a second tab, another device, or a colleague
# between the flush and the write. The post-send warning covers a send that somehow lands anyway.
#
# The numbers below are the real reported case: David Dyer Residence, revision 4. Live bid
# $27,721 with no options; the frozen document still held three systems at $29,104. The customer
# opened it nine minutes after the send.
@needs_node
def test_the_servers_refusal_is_recognised_by_its_CODE(ran):
    """`code`, never the sentence. The sentence in `error` is copy and may be reworded any day;
    branching on it would make a wording change silently stop handling refusals."""
    assert ran["refusal"]["recognised"], "a 409 stale_document is not recognised at all"
    assert ran["refusal"]["code"] == "stale_document"


@needs_node
def test_the_refusal_paints_the_same_panel_with_the_servers_numbers(ran):
    """The contract's `snapshot` is byte-identical in shape to a successful send's
    `sent_snapshot`, which is what makes this a mapping and not a second comparison: it drops
    into the same TW.docDrift the gate uses. One panel, whichever layer said no."""
    r = ran["refusal"]
    assert r["rows"] == ["Price:$29,104>$27,721", "Options:2>0"], r["rows"]
    assert "$29,104" in r["table"] and "$27,721" in r["table"], r["table"]


@needs_node
def test_a_refused_send_reads_as_NOTHING_WAS_SENT(ran):
    """The server wrote nothing and emailed nobody, so the estimator must not have to tell
    "the page stopped me" from "the server stopped me" — what they do about it is identical."""
    assert ran["refusal"]["lede"].startswith("Nothing was sent."), ran["refusal"]["lede"]


@needs_node
@pytest.mark.parametrize("case", ["serverError", "validation", "otherCode", "network",
                                  "empty", "notJson"])
def test_every_other_failure_falls_through_to_the_ordinary_error_line(ran, case):
    """A 500, a validation 400, a different 409, a dropped connection, an unparseable body. If
    any of these were read as a stale document the estimator would be sent to rebuild a PDF that
    was never the problem, while the real outage went unreported."""
    assert ran["refusal"]["others"][case] is None, case


@needs_node
def test_a_refusal_with_no_snapshot_still_says_something(ran):
    """An older server, or one that changes its mind about the payload. The panel cannot be
    built without the figures, so the server's own sentence has to carry it: a refusal the
    estimator cannot see is a Send button that does nothing when pressed."""
    n = ran["refusal"]["noSnapshot"]
    assert n["recognised"] and n["rows"] == 0
    assert "$29,104" in n["error"] and "not $27,721" in n["error"], n["error"]


@needs_node
def test_the_refusal_is_handled_before_the_generic_error_line(ran):
    """Inside the catch, and it leaves. Falling through would paint the panel and then overwrite
    the estimator's inline error with a raw "POST … → 409: {…}" status string."""
    assert ran["wiring"]["refusalHandledInCatch"]
    assert ran["wiring"]["refusalReusesTheSamePanel"], (
        "the refusal builds its own rows instead of reusing the shared comparison")


@needs_node
def test_a_reworded_refusal_is_still_recognised(ran):
    """`error` is copy and somebody will improve it; `code` is the contract. If recognition
    depended on a word in the sentence, a copy edit on the server would silently stop the panel
    from ever appearing again, and the estimator would be back to reading a raw status string."""
    r = ran["refusal"]["reworded"]
    assert r["recognised"], "recognition depends on the wording of the message"
    assert r["rows"] == 2, "the figures did not survive the reworded body"


@needs_node
def test_a_refusal_with_nothing_readable_still_reaches_the_estimator(ran):
    """Read off the source, and said so: this branch lives inside the click handler, which needs
    the whole page to run. What it guards is that a refusal the panel cannot render falls back to
    the server's own sentence instead of leaving a Send button that does nothing when pressed."""
    assert ran["wiring"]["refusalFallsBackToTheServersSentence"]


# ── RJ's loop, 2026-09-03 ────────────────────────────────────────────────────
# "I had to go back and revise and resend an estimate based on the job changes. I keep getting
#  the below error message. I go back to the PDF and hit continue as the message says and
#  everything appears to be correct but I keep getting the error message."
#
# Every word of that is accurate, and every part of the screen he was reading was telling the
# truth. The drift was real, the send was correctly refused, and the cure the panel named --
# press Continue on the Proposal step -- could not be carried out. TW.setState refuses a write
# when the local blob belongs to a different draft than the page is on (a second tab of this
# tool), and it refuses it SILENTLY, handing the caller back the unchanged blob. So Continue
# rebuilt the payload, wrote nothing, navigated anyway, and the Files page found the same drift
# and pointed him back at Continue. Deterministic, and with no exit.
#
# The gate above was necessary and is not the bug. What was missing is that neither end ever
# asked whether a save was possible before telling somebody to make one. Both now do, and both
# say the same words, from one function.


@needs_node
def test_a_send_blocked_by_a_refused_save_says_so_instead_of_blaming_the_document(ran):
    """The whole of RJ's report, executed. With the blob owned by another draft, the Files page
    must name THAT, not the drift -- and must not offer Update the PDF, because pressing it is
    the loop he was in."""
    b = ran["blockedSave"]["blocked"]
    assert b["painted"] is True, "the send was not stopped for the reason it could not succeed"
    assert b["reason"] == "foreign-blob"
    assert b["shown"] is True, "the panel never appeared"
    assert "another tab" in b["title"], b["title"]
    assert b["fixHidden"] is True, (
        "Update the PDF is still offered -- pressing it is the loop RJ was in")
    assert b["howNamesContinue"] is False, (
        "the cure still names Continue, which is the instruction that could not work")
    assert b["rows"] == "", (
        "the drift figures are still on screen, which reads as 'the document is the problem'")
    assert "Nothing was sent" in b["lede"], b["lede"]


@needs_node
def test_a_page_that_can_save_is_left_completely_alone(ran):
    """THE COUNTEREXAMPLE. If showSaveBlocked painted regardless, every assertion above would be
    just as green and every ordinary send in the building would be refused. Same lifted code,
    same panel, a blob this page owns."""
    c = ran["blockedSave"]["clean"]
    assert c["reason"] is None, "a page on its own draft was reported as blocked"
    assert c["painted"] is False
    assert c["stillHidden"] is True, "the panel was shown on a page with nothing wrong"
    assert c["title"] == "", "the panel's chrome was rewritten on a healthy page"


@needs_node
@pytest.mark.parametrize("reason,in_say,in_fix", [
    ("foreign-blob", "another tab", "Close the other tab"),
    ("no-draft", "lost track of which project", "Projects page"),
    ("unverified", "not reaching the server", "Reload"),
])
def test_each_refusal_gets_its_own_words_and_its_own_way_out(ran, reason, in_say, in_fix):
    """Three different problems with three different cures: close a tab, reopen the project,
    reload. One shared "something went wrong" would put the estimator back where RJ was --
    reading a true statement he cannot act on. Derived through the REAL saveBlocked, so the
    mapping under test is the shipped mapping."""
    w = ran["blockedSave"]["words"][reason]
    assert w["reason"] == reason
    assert in_say in w["say"], w["say"]
    assert in_fix in w["fix"], w["fix"]
    assert "Continue" not in w["fix"], (
        "%s tells them to press Continue, which is the loop" % reason)


@needs_node
def test_the_words_for_the_three_refusals_are_actually_different(ran):
    """A guard against the cheapest way to pass the test above: one sentence containing all
    three phrases."""
    says = {r["say"] for r in ran["blockedSave"]["words"].values()}
    fixes = {r["fix"] for r in ran["blockedSave"]["words"].values()}
    assert len(says) == 3 and len(fixes) == 3


@needs_node
def test_a_real_drift_shown_afterwards_gets_its_own_words_back(ran):
    """The two states share one panel. Without a restore, an estimator who closes the second tab
    and comes back to a genuine drift is told to close a tab he has already closed, with no
    Update the PDF button to press -- a second dead end built by the fix for the first."""
    r = ran["blockedSave"]["restored"]
    assert r["title"] == "The PDF has the old numbers", r["title"]
    assert "Update the PDF" in r["how"] and "Continue" in r["how"], r["how"]
    assert r["fixHidden"] is False, "the fix button never came back"
    assert "$13,265" in r["rows"] and "$18,670" in r["rows"], r["rows"]


@needs_node
def test_the_files_page_asks_before_it_blames_the_document(ran):
    """Order is the whole fix. "Is the document stale" was asked first and answered correctly;
    it is the wrong FIRST question when the reason it is stale is that this browser cannot save.
    Nothing may be posted either way -- no portal row, no email."""
    g = ran["gateOrder"]
    assert g["asksBeforeBlamingTheDocument"], (
        "showStaleDoc runs first, so the estimator is given the cure that cannot work")
    assert g["onlyWhenThereIsDrift"], (
        "the question is asked on every send, not only on a send that is being refused")
    assert g["bothBeforeThePost"] and g["returnsWithoutPosting"], (
        "a blocked send falls through to /api/portal/publish")
    assert g["restoresButton"], "a blocked send leaves a dead Sending… button"


@needs_node
def test_the_proposal_step_asks_BEFORE_it_writes(ran):
    """The other end. continueToDone composes a fresh payload and hands it to setState, which
    refuses a write it cannot own and returns the unchanged blob -- indistinguishable from
    success. Navigating on that is what closed the loop, so the question is asked before the
    write and the answer sends nobody anywhere."""
    p = ran["proposalGuard"]
    assert p["said"] is True, "the Proposal step still navigates on a save it cannot make"
    assert p["shown"] is True
    assert "another tab" in p["head"], p["head"]
    assert p["stillNamesContinue"] is False, (
        "the note still says press Continue -- the three parts are addressed separately so that "
        "the instruction can be replaced, not just prefixed")
    assert p["guardBeforeTheWrite"], "the guard sits after the payload is composed"


@needs_node
def test_a_save_that_fails_for_a_reason_nobody_can_ask_about_also_stops(ran):
    """saveBlocked knows three refusals. writeBlob returning false -- a full or locked
    localStorage, private mode, quota -- is a fourth, and setState ignores its return value. So
    presence of the payload is checked after the write, between it and the navigation, and that
    branch never falls through. A first draft of this fix said `if (!landed && blocked) return`,
    which would have navigated on exactly this case: the bug wearing a fix."""
    p = ran["proposalGuard"]
    assert p["landedBetweenWriteAndGo"], (
        "the check is not between the write and the navigation, so it proves nothing")
    assert p["landedReturns"], "it paints and then navigates anyway"
    assert p["landedRestoresButton"], (
        "the button is left on Generating… with no way forward")
