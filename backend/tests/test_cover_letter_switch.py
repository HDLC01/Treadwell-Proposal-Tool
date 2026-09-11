"""The optional cover letter, on the estimator's side of it — one checkbox, and that is all.

WHAT IS LEFT, AFTER 2026-09-09. The letter used to be a SECOND document with an editor of its own:
a `#doc-tabs` strip in the formatting ribbon, a `#cl-surface` the template was drawn on, a
paragraph-override channel, a `template_version` to pin those override ids against, a
`/api/coverletter-template` endpoint to feed it, a `/api/admin/cover-letter-pdf` to render it and a
fourth download button on the Files page. Hanz removed the lot. The letter is now generated from
its template plus the values the proposal already resolved, and `docx_merge.prepend_cover_letter`
puts it on the front of the proposal .docx — so it is page 1 of one document rather than a file of
its own. `test_cover_letter_ui.py` (1275 lines) and its harness tested that editor and were
deleted with it; the three tests in it that were about behaviour which SURVIVED are here.

SO WHAT IS WORTH TESTING IS THE JOURNEY OF ONE BOOLEAN, and it is a longer journey than it looks.
`cover_letter_enabled` has to be written onto the draft by the checkbox, read back onto the
checkbox when the project is reopened, carried INSIDE `proposal_payload` (not merely on the POST
body) so that a sent revision freezes it, and read out of that pinned blob months later by
/api/admin/proposal-pdf when a customer opens their link. Every one of those four is a place the
flag can be dropped, and dropping it is silent: the estimator ticked a box, the document generated
without complaint, and the customer got a proposal starting on page 2's content.

WHY THE WIRING RUNS UNDER NODE, EXECUTED. The two halves of the boolean travel in opposite
directions — painted from the draft on load, written to the draft on change — and a source read
sees `TW.getState()` and `TW.setState` present without being able to tell which way round they are
wired, or that an identifier in between is unbound. This repo has paid for that once already: on
2026-08-12 `STAGE_CREATED` shipped unbound with every source assertion green and took the
production board down. `js/cover-letter-switch-harness.js` lifts the shipped IIFE and drives it.

AND THE PAYLOAD READ RUNS TOO, BECAUSE A REGEX ON THAT LINE IS WHAT LET THE BUG SHIP. The first
version of this feature built the payload with `!!state.cover_letter_enabled`. Every source
assertion passed — including one right here checking that `cover_letter_enabled` appears inside
the `proposal_payload` literal — and the VALUE was wrong: `state` is the module-top one-shot
`TW.getState()`, and the switch writes a top-level key, which `TW.setState` replaces on a freshly
parsed blob rather than mutating in place. Tick the box, press Continue in the same visit, and the
payload shipped `false`; `create_revision` pinned `false`; the customer's document had no page 1;
and the box was still ticked after a reload, because localStorage had been right all along and
only that one read was wrong. Untick-then-Continue failed the same way in reverse. Fixed by
routing it through `liveKey`, like the twelve other keys on that page that had already been
caught by it. `test_ticking_the_box_then_continuing_freezes_a_letter_into_the_payload` is the test
that would have stopped it: the payload line is lifted verbatim and EVALUATED, in a scope holding
the same three bindings the browser gives it.

THE REST IS A SOURCE READ, and has to be. "This key is inside that object literal" and "no
reference to the deleted editor survives anywhere under frontend/" are both claims about the files
themselves; there is no runtime at which they could be observed.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "cover-letter-switch-harness.js"
BANNER_HARNESS = (pathlib.Path(__file__).resolve().parent / "js"
                  / "cover-letter-banner-harness.js")

PR_PAGE = (FRONTEND / "proposal-review.html").read_text(encoding="utf-8")
PR_JS = (FRONTEND / "js" / "proposal-review.js").read_text(encoding="utf-8")
DONE_PAGE = (FRONTEND / "done.html").read_text(encoding="utf-8")
DONE_JS = (FRONTEND / "js" / "done.js").read_text(encoding="utf-8")

# The DISCARDED HALF of the old editor, still gone on purpose after the 2026-09-11 restore.
# `coverletter-editor.js`, `TWCoverLetter` and `cl-surface` came BACK that day (Hanz: bring the
# editing back, on the same page as the proposal) and are no longer in this list. What did not
# come back is the part that made the letter a SEPARATE document rather than page 1 of one: the
# tab strip that switched between two surfaces, the off-stage class that parked whichever one was
# not in front, and the Files page's fourth download button.
GONE = ("doc-tabs", "cl-offstage", "dl-cover")


def _node(harness):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(harness)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=180)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def wired():
    return _node(HARNESS)


@pytest.fixture(scope="module")
def banner():
    """The real `showCoverLetterPlaceholders` from done.js, run over eighteen input states."""
    return _node(BANNER_HARNESS)


# ══ the switch, executed ══════════════════════════════════════════════════════
def test_a_reopened_draft_shows_the_box_as_the_estimator_left_it(wired):
    """The half that is easiest to forget, because forgetting it looks like nothing. A checkbox
    that always renders unticked reads as "this project has no cover letter" on every visit after
    the first — so an estimator who ticked it last week, reopens the project to change a price, and
    presses Continue, ships a proposal whose first page they have no way of knowing is there. (Or,
    if they untick the already-unticked box to "make sure", ships one whose first page they have
    just removed by accident.)

    Painted through `!!`, so a flag that came back off the wire as `"1"` — JSON round-trips do that
    — reaches the DOM as a real boolean. `checked = "1"` is truthy in the browser and un-round-
    trippable back out."""
    assert wired["paintedFromTrueDraft"] is True, (
        "a saved project with a cover letter opens with the box unticked")
    assert wired["paintedFromFalseDraft"] is False
    assert wired["paintedFromEmptyDraft"] is False, (
        "a brand-new draft with no key at all opens with the letter ON")
    assert wired["paintedFromTruthyString"] is True, (
        "a stored truthy non-boolean did not reach the DOM as a boolean")
    assert wired["paintedThrew"] is None, wired["paintedThrew"]
    # `TW.getState()` returns {} on a parse failure today, but it is a function on a shared file and
    # `|| {}` is there for a reason. Nothing else on this page would run if this threw.
    assert wired["paintedFromNoState"] is False and wired["noStateThrew"] is None, (
        "an empty state blob throws on the way past the cover-letter switch")


def test_ticking_the_box_is_what_puts_it_on_the_draft(wired):
    """The other direction, and the only writer there is: nothing else in the product can set this
    flag. It has to land on the draft rather than in a variable, because the draft is what
    `continueToDone` freezes into `proposal_payload` and what the server pins on send.

    UNTICKING WRITES `false`, it does not delete the key. The backend defaults a missing key to
    False so both would generate the same document today — but a draft that once had a letter has
    to be able to say out loud that it no longer does, or the next reader has to guess whether the
    absence means "never asked" or "changed their mind"."""
    assert wired["changeListeners"] == 1, (
        "the switch is wired %d times; two listeners means two writes per press"
        % wired["changeListeners"])
    assert wired["writes"] == [{"cover_letter_enabled": True},
                               {"cover_letter_enabled": False}], (
        "ticking and unticking the box did not write the flag onto the draft: %r"
        % (wired["writes"],))


def test_a_failed_write_does_not_take_the_rest_of_the_page_with_it(wired):
    """`TW.setState` writes localStorage, which throws on quota and in some private modes. An
    unguarded throw out of a `change` handler is not contained to this control — it aborts the
    handler, and the estimator gets a checkbox that visibly moved and a draft that did not change,
    with a console error nobody is looking at. Same `try {} catch {}` every other choice on this
    page uses. The write is still ATTEMPTED, which is the difference between guarded and skipped."""
    assert wired["attemptedWriteAnyway"] == 1, (
        "the write is guarded by not being made — the flag can never reach the draft")
    assert wired["handlerThrewOnFailedWrite"] is None, (
        "a failed state write escapes the change handler: %s"
        % wired["handlerThrewOnFailedWrite"])


def test_the_switch_is_inert_where_the_checkbox_is_not(wired):
    """proposal-review.js is one file for one page today, but the IIFE runs at load and the guard
    is what keeps a restructured ribbon from turning into a console error on a page that has no
    letter to offer. Nothing written, nothing thrown."""
    assert wired["absentBoxThrew"] is None, wired["absentBoxThrew"]
    assert wired["absentBoxWrote"] == 0, (
        "the switch wrote to the draft on a page with no checkbox on it")


def test_ticking_the_box_then_continuing_freezes_a_letter_into_the_payload(wired):
    """THE ONE THAT WOULD HAVE CAUGHT IT. Written after the bug, and the bug is worth stating in
    full because the shape of it is what decides how this has to be tested.

    The switch wrote `cover_letter_enabled` correctly. `continueToDone` then built
    `proposal_payload` with `!!state.cover_letter_enabled` — and `state` is the module-top
    `TW.getState()`, taken once at page load. `TW.setState` re-parses localStorage into a NEW
    object, merges the partial onto that, and writes it back; it never touches an earlier caller's
    snapshot. Every other `state.*` read in that literal survives this because it is an object or
    an array whose writers mutate the very thing the snapshot points at and then persist the same
    reference. A boolean cannot be mutated in place, so this key's writer had no choice but to
    replace it — which makes `cover_letter_enabled` the one field in that literal that had to go
    through `liveKey`, and the reason it was the one that broke.

    WHAT THE ESTIMATOR SAW: nothing. Tick the box, press Continue, send. The payload said `false`,
    `create_revision` pinned `false`, /api/admin/proposal-pdf read `false` off the pinned blob and
    rendered the customer a proposal with no letterhead page — and the box was still ticked on the
    next visit, because localStorage was right the whole time and only that one read was wrong.

    SO THE LINE IS EXECUTED, NOT MATCHED. A source assertion is what let this ship: the check a
    few tests down, that `cover_letter_enabled` appears inside the `proposal_payload` literal,
    passed against the broken line and would pass against `false` hardcoded. The harness lifts
    that line verbatim and evaluates it in a scope holding the real snapshot binding, the real
    `liveKey`, and the real wired checkbox, in the page's own order. Its docstring lists exactly
    what does and does not run — the rest of `continueToDone` does not, so this cannot see the key
    being deleted from the literal, which is what the source check is still for.

    BOTH HALVES ARE ASSERTED SEPARATELY, on purpose: `stored` is what reached the draft and
    `payload` is what Continue would freeze. The bug had a correct write and a stale read, and a
    single combined assertion would not have said which."""
    tick = wired["tickThenContinue"]
    assert tick["paintedOnLoad"] is False, (
        "the fixture no longer starts from an unticked box, so the press below is not a change")
    assert tick["stored"] is True, (
        "ticking the box did not reach the draft at all — this is the WRITE half, and "
        "test_ticking_the_box_is_what_puts_it_on_the_draft covers it in isolation")
    assert tick["payload"] is True, (
        "the estimator ticked Cover letter, pressed Continue, and the payload that gets frozen "
        "into the sent revision says there is no letter. The customer's document will be missing "
        "its first page and nothing on screen will say so. This is the load-time `state` snapshot "
        "being read instead of `liveKey` — see this test's docstring.")


def test_unticking_the_box_then_continuing_takes_the_letter_back_off(wired):
    """The mirror, which failed the mirror way and is the more expensive direction: an estimator
    who changes their mind and unticks the box, then Continues, would have shipped a proposal with
    a letterhead page they had just removed — a customer-facing page nobody proofread, which is
    the exact thing the checkbox defaults to off to avoid.

    Present as its own test rather than a second pair of asserts because the two directions fail
    for the same reason and mean opposite things, and a report that says "the letter is wrong"
    without saying which way round costs a session."""
    untick = wired["untickThenContinue"]
    assert untick["paintedOnLoad"] is True, (
        "the fixture no longer opens with the box ticked, so unticking it is not a change")
    assert untick["stored"] is False, (
        "unticking the box did not reach the draft — the WRITE half again")
    assert untick["payload"] is False, (
        "the estimator unticked Cover letter and the frozen payload still asks for one, so a "
        "letterhead page they removed goes to the customer anyway")


def test_continuing_without_touching_the_box_still_says_what_the_draft_says(wired):
    """THE COUNTEREXAMPLE FOR THE TWO ABOVE, and they need one. Both press the box and then read
    the payload, so both would pass against a line that ignored the draft entirely and answered
    from the checkbox — or from a constant matching whichever way it was pressed. This drives no
    press at all and asserts the payload follows the STORED draft in both directions, which no
    such line can do.

    It is also the real journey it names: reopening a saved project to change a price and pressing
    Continue without going near the ribbon must not silently add or drop the letter."""
    assert wired["untouchedFromTrueDraft"] is True, (
        "a saved project that HAS a cover letter lost it by being reopened and continued")
    assert wired["untouchedFromEmptyDraft"] is False, (
        "a project that never asked for a cover letter acquired one by being continued")
    assert wired["untouchedFromTrueDraft"] != wired["untouchedFromEmptyDraft"], (
        "the payload answers the same thing for both drafts, so it is not reading the draft")


def test_the_payload_line_under_test_is_the_shipped_one(wired):
    """What the harness lifted, echoed back and checked here, because the lift is the load-bearing
    part of the three tests above. If it silently picked up the wrong line — the switch's own
    `setState({ cover_letter_enabled: … })` is the other occurrence in that file — they would be
    testing the write twice and the read not at all.

    Anchored on the mechanism rather than the exact text: it must read through `liveKey`, and it
    must not read through the module-top `state` snapshot. A future refactor is free to reword it
    as long as it does not go back to the snapshot.

    This is the one place a source-shaped assertion is right, and only because it is a claim about
    the harness rather than about the product: the three tests above are what say the line
    BEHAVES, and this says they are pointed at it."""
    field = wired["liftedPayloadField"]
    assert field.startswith("cover_letter_enabled:"), (
        "the harness lifted something that is not the payload field: %r" % field)
    assert 'liveKey("cover_letter_enabled")' in field, (
        "the payload no longer reads the flag out of the CURRENT draft blob: %r. If this is a "
        "deliberate change to a different live reader, update this assertion; if it is back to "
        "`state.cover_letter_enabled`, the three tests above are already red and this says why."
        % field)
    assert not re.search(r"\bstate\.cover_letter_enabled\b", field), (
        "the payload is reading the page's load-time snapshot again: %r" % field)


def test_the_checkbox_is_actually_in_the_page_the_harness_lifts_the_wiring_from():
    """The premise of every executed test above. The harness supplies its own `#cl-toggle`, so all
    four of them stay green if the real element is deleted from the ribbon — which is precisely
    the vacuum this asserts out of existence. The id, in the page, next to a label that says what
    it does."""
    assert 'id="cl-toggle"' in PR_PAGE, (
        "#cl-toggle is gone from proposal-review.html — the whole cover-letter feature is now "
        "unreachable, and the harness above would not have noticed")
    label = re.search(r'<label class="ribbon-cl".*?</label>', PR_PAGE, re.S)
    assert label and 'id="cl-toggle"' in label.group(0), (
        "the checkbox is not inside its own label any more, so its text is not a click target")
    assert "Cover letter" in label.group(0), "the checkbox has lost its visible name"


# ══ the cover-letter check, and the two surfaces that render it ═══════════════
# WHY ANY OF THIS EXISTS. The letter's copy is a draft (templates/CoverLetter/README.md) and every
# one of the seven templates still carries bracketed instructions written TO the estimator —
# "[SHEEN - pick one: ...]". They reached nobody while the letter was a separate document the
# portal never rendered. They are page 1 of a customer's proposal now, and the document editor the
# README named as the way to delete them is gone. Two surfaces are all that stand between that and
# a customer: the review row before Generate, and the banner after it.
#
# IT SHIPPED WRONG SEVEN TIMES. Every one was the same sentence — the warning's input was not the
# input the document is built from — and five of the seven UNDER-reported, the direction that
# reaches a customer:
#   1. `Array.isArray(result.cover_letter_placeholders)` before the field existed: key absent, so
#      tick-then-Continue hid the banner;
#   2. `hasOwnProperty`: TRUE, because the field had arrived as `default_factory=list` and a
#      letter-off generate answered `[]`, read as "scanned, clean";
#   3. the cached list described epoxy/Direct while a GC letter was being pinned: 1 shown, 4 sent;
#   4. the gate read the TOP-LEVEL flag while the document was built from `proposal_payload`;
#   5. the same mistake surviving in the review row after the banner was fixed;
#   6. an unbounded fetch: a hung request left the banner absent with Send live, indefinitely;
#   7. `has_letter` returned by the endpoint and read by nothing, so a sealer bid promised a
#      letterhead page 1 and then met a 400.
#
# THERE IS ONE READER NOW, and that is what these tests defend. `coverLetterCheck` owns the source
# (`proposal_payload`, with viewFiles' own fallback), the variant in the query, the bearer wait,
# the status check, the body-shape guard and the 8-second bound. Both surfaces delegate to it, so
# they CANNOT disagree — defect 5 stated as a property instead of patched in two places. So the
# structural claims are asserted ONCE, on the reader; what is left of the callers is that each
# renders every answer it can be handed, and that the two never contradict each other about
# whether a letter is coming.
def test_the_reader_gates_on_the_blob_the_document_is_built_from(banner):
    """DEFECT 4 AND 5, RULED OUT IN ONE PLACE. The flag used to be read off the TOP-LEVEL
    `cover_letter_enabled` while the document was built from `proposal_payload` — `viewFiles` uses
    `pp` wholesale when it has values, `create_revision` pins `pp`, and the portal is told
    `_pp.cover_letter_enabled`. Untick without pressing Continue and the two diverge: the letter
    is still in the document and the page is silent about it.

    `const src = (pp && pp.values) ? pp : st` is exactly `viewFiles`' own rule, which is what
    makes them agree by construction rather than by coincidence. Both directions asserted, and
    the no-payload fallback too — a draft that has not been through Continue yet has only the
    top-level flag, and must still be able to warn."""
    r = banner["reader"]
    on = r["flagOnInPayloadOffOnTop"]
    assert on["enabled"] is True, (
        "the payload says the document gets a letter and the reader says it does not, because it "
        "is reading the top-level flag — untick-without-Continue is exactly this state, and the "
        "customer receives the instructions unwarned")
    assert on["fetches"] == 1, (
        "the reader did not ask about a bid whose payload says a letter is coming")
    off = banner["reader"]["flagOffInPayloadOnOnTop"]
    assert off["enabled"] is False, (
        "the payload says no letter and the reader says there is one, which is the same misread "
        "in the direction that cries wolf")
    assert off["fetches"] == 0, (
        "the endpoint was called for a bid with no cover letter — a request whose answer cannot "
        "change the outcome")
    assert banner["reader"]["noPayloadTopOn"]["enabled"] is True, (
        "a draft with no frozen payload yet cannot warn at all")
    assert banner["reader"]["noPayloadTopOff"]["enabled"] is False, (
        "with no frozen payload and the top-level flag off, the reader still thinks a letter "
        "is coming")


def test_the_reader_asks_about_the_variant_being_sent(banner):
    """DEFECT 3, RULED OUT BY CONSTRUCTION. The list is per `(work_type, audience)`: the
    epoxy/Direct letter carries 1 instruction and the epoxy/GC letter 4. A cached list from an
    earlier generate showed the estimator 1 line while the customer received 4, three of which
    nobody had ever seen — and `generate_result` was never cleared, so changing the audience on
    Intake and pressing Continue (which does not regenerate) was enough to do it.

    So the query carries the variant out of `proposal_payload`. Asserted with the top-level
    work_type/audience set to a DIFFERENT variant, both ways round, because reading the wrong
    source is a wrong answer in either direction and a test that checked one could pass on a read
    of whichever happened to match."""
    got = banner["reader"]["variantFromPayload"]
    assert got["fetches"] == 1, "the reader did not ask at all"
    assert got["q"].get("work_type") == "polish", (
        "the reader asked about %r when the payload about to be pinned says polish. It is "
        "describing a different document's page 1 — the defect that showed 1 instruction and "
        "sent 4." % got["q"].get("work_type"))
    assert got["q"].get("audience") == "GC", got["q"]
    rev = banner["reader"]["variantFromPayloadReversed"]
    assert rev["q"].get("work_type") == "epoxy" and rev["q"].get("audience") == "Direct", (
        "with the two sources swapped the reader followed the other one, so it is not reading "
        "the payload — it is reading whichever agrees: %r" % (rev["q"],))
    assert got["q"] != rev["q"], (
        "the query is identical for two states whose payloads name different variants, so it is "
        "not derived from the payload at all")
    assert banner["reader"]["variantDefaults"]["q"] == {"work_type": "epoxy",
                                                        "audience": "Direct"}


def test_a_check_that_could_not_be_made_is_never_reported_as_clean(banner):
    """`placeholders: null` is the reader's fourth answer and the whole reason it has one. Asking
    a server means the answer can fail to arrive: offline, a 500, a 401 because the bearer was not
    ready, an HTML error page where JSON was expected, a body whose `placeholders` is not a list,
    a hung request. Every one means the page does not know what is on page 1 — and reporting that
    as an empty list would be defect 2 with a new cause.

    ELEVEN failure shapes, not one, because a guard that special-cased the throw would pass the
    first and leak the rest. TWO of them are a FAILED REQUEST WHOSE BODY LOOKS LIKE A GOOD ANSWER
    — a 502 or 401 from a gateway or auth proxy answering with its own JSON envelope, or a stale
    cached error body. Those are what make the `if (r.ok)` check load-bearing instead of
    belt-and-braces, and they were added after a mutation that dropped it survived: every other
    shape happened to be caught by the inner Array.isArray guard, so the status check was
    untested rather than unneeded."""
    for name in ("fetchRejects", "notOk", "unauthorized", "notOkWithCleanBody",
                 "notOkWithLines", "jsonThrows", "placeholdersNull", "placeholdersString",
                 "placeholdersObject", "placeholdersMissing", "apiBaseThrows",
                 "hungFetchAborted"):
        got = banner["reader"][name]
        assert got["threw"] is None, (
            "%s escaped the reader and would take the caller with it: %s" % (name, got["threw"]))
        assert got["enabled"] is True, (name, got["enabled"])
        assert got["placeholders"] is None, (
            "%s answered %r rather than null. The page could not find out what is on the "
            "customer's first page and is about to report it as nothing to worry about."
            % (name, got["placeholders"]))
    # And the three answerable states are genuinely different values, or the null above is not a
    # distinct answer at all.
    assert banner["reader"]["clean"]["placeholders"] == [], (
        "a clean scan no longer answers an empty list, so `null` above is not a distinct "
        "answer and every assertion in this test is about one indistinguishable state")
    assert len(banner["reader"]["lines"]["placeholders"]) == 2, (
        "a scan that found instructions no longer answers them")
    assert banner["reader"]["noLetter"]["hasLetter"] is False, (
        "has_letter: false from the endpoint did not reach the caller, so the review row "
        "cannot report a work type that Generate will refuse")


def test_the_reader_waits_for_the_bearer_and_sends_it(banner):
    """PR #124, the /api/default-notes 401 race, applied here. This endpoint is NOT in
    `_AUTH_PUBLIC_PATHS`, so a fetch that goes out before auth.js has set the token gets a 401 —
    which now surfaces as "could not be checked" on every single load, a warning that is always up
    and therefore worthless.

    The harness resolves `TWAuth.ready` on a later microtask and records whether it HAD resolved
    when the fetch went out, so this is a real ordering assertion and not a source read. The
    feature-detection is asserted too: a page without TWAuth must still ask rather than hang."""
    got = banner["reader"]["lines"]
    assert got["authWasReadyAtFetch"] is True, (
        "the fetch went out before TWAuth.ready resolved, so it will 401 and both surfaces will "
        "report 'could not be checked' on every load")
    assert got["headers"] == {"Authorization": "Bearer test-token"}, (
        "the request carries no auth header, so it will 401: %r" % (got["headers"],))
    no_auth = banner["reader"]["noAuthObject"]
    assert no_auth["fetches"] == 1 and no_auth["placeholders"] is not None, (
        "a page without window.TWAuth never got an answer — the await is not feature-detected "
        "and the reader hangs instead of asking")


def test_the_check_is_bounded_and_the_timer_is_cleared(banner):
    """DEFECT 6. The fetch had no timeout, so a hung request left the banner absent — not wrong,
    ABSENT — with Send fully usable, for as long as the socket stayed open. "Silent forever" is
    the worst of the seven, because every other defect at least rendered something.

    DRIVEN, NOT INSPECTED. The harness binds a fake clock: `setTimeout` records `(fn, delay)` and
    fires the callback at once, so the AbortController really aborts and the shipped `catch` really
    runs. `hungFetchAborted` is a fetch that resolves ONLY on abort, exactly as a real one does —
    so a version without the abort would never settle, and this assertion would time out rather
    than pass. That is the strongest form available here: the harness cannot wait 8 real seconds,
    but it does not have to, because the abort is what settles the promise.

    The delay itself is pinned because the bound is the point: an absurd value is the same defect
    with a longer fuse. And `clearTimeout` must run on BOTH paths — the shipped code puts it in a
    `finally` around the fetch, so a request that fails still cancels its own alarm rather than
    leaving a timer to abort a controller nobody is listening to."""
    hung = banner["reader"]["hungFetchAborted"]
    assert hung["threw"] is None, hung["threw"]
    assert hung["placeholders"] is None, (
        "a hung request did not land in could-not-be-checked: %r" % (hung["placeholders"],))
    assert hung["hadSignal"] is True, (
        "the fetch was made without an AbortSignal, so the AbortController is decorative and "
        "nothing can interrupt a hung request")
    delays = [t["delay"] for t in hung["timersSet"]]
    assert delays == [8000], (
        "expected exactly one 8s alarm on the check; got %r. No alarm is 'silent forever'; a "
        "much longer one is the same thing with a longer fuse." % (delays,))
    assert hung["timersCleared"] == [t["id"] for t in hung["timersSet"]], (
        "the alarm was not cleared on the abort path: set %r, cleared %r"
        % (hung["timersSet"], hung["timersCleared"]))
    # And on the SUCCESS path, which is the one the `finally` is easy to get wrong.
    ok = banner["reader"]["lines"]
    assert [t["delay"] for t in ok["timersSet"]] == [8000], ok["timersSet"]
    assert ok["timersCleared"] == [t["id"] for t in ok["timersSet"]], (
        "a successful check left its abort timer running, so an 8s-late abort fires against a "
        "controller nobody is watching: set %r, cleared %r"
        % (ok["timersSet"], ok["timersCleared"]))


def test_both_surfaces_read_the_same_answer_and_never_contradict_it(banner):
    """THE CASE-6 GUARD, and the reason the reader was extracted at all. The banner was fixed to
    read `proposal_payload` and the review row a screen earlier was not, so for one build the row
    promised a letterhead page 1 for a document that would not have one. Two readers is two sets
    of decisions; one reader cannot disagree with itself.

    So this drives BOTH callers over the SAME five answers and asserts the pair is consistent:
      * `enabled: false` -> both silent. Neither surface may mention a letter that is not coming.
      * `enabled: true`  -> the ROW always says something, because it is the pre-generate summary
        and an omitted page 1 is not a summary. The BANNER speaks only when there is something to
        report, because a warning that is always up is one nobody reads.
      * and each calls the reader exactly ONCE — zero would mean it went back to its own source,
        two would mean two answers to reconcile.

    Not a description of each surface separately: the assertions below are relations between
    them, computed from one shared answer, which is what makes "they cannot disagree" testable."""
    for name in ("disabled", "noLetterForWorkType", "couldNotCheck", "clean", "lines", "oneLine"):
        b, r = banner["banner"][name], banner["row"][name]
        assert b["threw"] is None and r["threw"] is None, (name, b["threw"], r["threw"])
        assert b["checkCalls"] == 1, (
            "the banner consulted the shared reader %d times on %r — not once, which is either "
            "its own source again or two answers to reconcile" % (b["checkCalls"], name))
        assert r["checkCalls"] == 1, (
            "the row consulted the shared reader %d times on %r" % (r["checkCalls"], name))
    # No letter coming: both silent.
    assert banner["banner"]["disabled"]["shown"] is False, (
        "the banner warns about page 1 of a document that has no page 1")
    assert banner["row"]["disabled"]["shown"] is False, (
        "the review row mentions a cover letter for a bid that has none — the row and the banner "
        "have come apart again, which is what one shared reader is for")
    # A letter coming, in any of its four shapes: the row always speaks.
    for name in ("noLetterForWorkType", "couldNotCheck", "clean", "lines", "oneLine"):
        assert banner["row"][name]["shown"] is True, (
            "the review row is silent on %r — the estimator reads the whole pre-generate summary "
            "and page 1 is not in it" % name)
    # The banner speaks only when there is something to report.
    assert banner["banner"]["clean"]["shown"] is False, (
        "a letter with no unfinished wording still raises the banner, so the banner is really "
        "just 'this bid has a cover letter' and will be ignored within a week")
    assert banner["banner"]["noLetterForWorkType"]["shown"] is False, (
        "the banner warns about unfinished wording on a letter that is not going to be built; "
        "that is the ROW's message, and duplicating it here means two places to keep in step")
    for name in ("couldNotCheck", "lines", "oneLine"):
        assert banner["banner"][name]["shown"] is True, name
    # The row's four messages are four different sentences. Two that read the same would make one
    # of the states unreportable while every individual assertion above still passed.
    texts = {n: banner["row"][n]["text"] for n in
             ("noLetterForWorkType", "couldNotCheck", "clean", "lines")}
    assert len(set(texts.values())) == 4, (
        "two of the row's states print the same sentence, so one of them cannot be told from the "
        "other on screen: %r" % (texts,))


def test_one_defect_in_the_shared_reader_now_fails_both_surfaces(banner):
    """THE IMPROVEMENT OF EXTRACTING THE READER, asserted as a property. The tests above check the
    reader's decisions and the callers' rendering separately, which is the right factoring but
    leaves the point unsaid: a defect in the shared reader must reach BOTH surfaces. That is what
    makes defect 5 unrepeatable — the row and the banner used to have a source each, so fixing the
    banner left the row wrong for a build, and nothing failed twice to say so.

    So this runs both surfaces over ONE real reader and ONE state blob, with no stub between them.
    The blob's payload says a letter IS coming and its top-level flag says it is not, which is
    exactly the untick-without-Continue state; `src = st` in the reader now takes both surfaces
    down at once instead of one of them quietly.

    The `state` bound to the row is deliberate nonsense, so a reintroduced snapshot read is a
    wrong answer here rather than an unbound identifier."""
    coming = banner["pair"]["payloadOnTopOff"]
    assert coming["threw"] is None, coming["threw"]
    assert coming["rowShown"] is True and coming["bannerShown"] is True, (
        "the payload says the document gets a letter with unfinished wording on it, and %s said "
        "nothing. Both surfaces read one reader, so this is that reader looking at the wrong "
        "source — the state that used to leave the customer with the instructions unwarned."
        % ("neither surface" if not coming["rowShown"] and not coming["bannerShown"]
           else ("the review row" if not coming["rowShown"] else "the banner")))
    assert coming["bannerItems"] == [
        "[SHEEN - pick one: Level 2 (400 grit) / Level 3 (800 grit).]",
        '[COVE HEIGHT - pick one: 4" / 6" / 8".]'], coming["bannerItems"]
    assert "2 lines" in coming["rowText"], coming["rowText"]

    not_coming = banner["pair"]["payloadOffTopOn"]
    assert not_coming["rowShown"] is False and not_coming["bannerShown"] is False, (
        "the payload says no letter and a surface mentions one anyway: row=%s banner=%s"
        % (not_coming["rowShown"], not_coming["bannerShown"]))
    assert not_coming["fetches"] == 0, (
        "the endpoint was called twice for a bid with no cover letter")

    # And the three remaining answers, end to end, with the pair consistent in each.
    no_letter = banner["pair"]["noLetterForWorkType"]
    assert no_letter["rowShown"] is True and "refuse" in no_letter["rowText"], no_letter
    assert no_letter["bannerShown"] is False, (
        "the banner warns about unfinished wording on a letter that will not be built")
    stale = banner["pair"]["couldNotCheck"]
    assert stale["rowShown"] is True and stale["bannerShown"] is True, stale
    assert "could not be" in stale["rowText"], stale["rowText"]
    assert "could not be checked" in stale["bannerHead"], stale["bannerHead"]
    clean = banner["pair"]["clean"]
    assert clean["rowShown"] is True and clean["bannerShown"] is False, clean
    # Each surface asks once — two surfaces, two requests, no caching between them. Pinned so a
    # future shared cache is a deliberate change rather than a silent one, and so a surface that
    # stopped asking shows up here.
    assert clean["fetches"] == 2, (
        "expected one request per surface, got %d — a surface that stopped asking is a surface "
        "reading something else" % clean["fetches"])


def test_a_work_type_with_no_letter_is_said_so_before_the_refusal(banner):
    """DEFECT 7, and the row is the ONLY place this can be said. `/api/generate` refuses a sealer
    or budget bid with the letter ticked (400) rather than sending the epoxy fallback — the right
    call, since the fallback would open a GC sealer contract in the owner's voice and name
    Treadwell Epoxy as the system. But until this row read `has_letter`, the estimator ticked the
    box, read "Yes — Treadwell letterhead prints as page 1", pressed Generate and met the 400.
    `has_letter` was returned by the endpoint and consumed by nothing.

    The message has to name the consequence AND the way out, because it is the whole of what the
    estimator gets before the refusal. And it must not be the ordinary yes: the branch order in
    the shipped code puts `hasLetter === false` first, ahead of the could-not-check and
    unfinished-wording branches, so a bid with no letter never reads as a bid with a clean one."""
    got = banner["row"]["noLetterForWorkType"]
    assert got["shown"] is True, (
        "a work type with no cover letter says nothing on the review card, so the estimator "
        "learns it from a 400 after pressing Generate")
    text = got["text"]
    assert "No letter" in text or "no letter" in text, text
    assert "refuse" in text, (
        "the row does not say that Generate will refuse, so the estimator cannot tell this from "
        "an ordinary warning: %r" % text)
    assert "untick" in text.lower(), (
        "the row does not say how to proceed: %r" % text)
    # NOT the ordinary yes. This is the branch-order assertion: `hasLetter === false` has to win
    # over the placeholder branches, and it arrives here WITH `placeholders: []`, which is exactly
    # the shape the clean branch renders as "prints as page 1 of the proposal".
    assert text != banner["row"]["clean"]["text"], (
        "a work type with no letter reads exactly like a finished one — the hasLetter branch is "
        "being reached after the placeholder branches, or not at all")
    assert "prints as page 1 of the proposal" not in text, (
        "the row promises a letterhead page for a bid whose generate will refuse: %r" % text)


def test_the_row_counts_the_lines_it_was_handed(banner):
    """The row does not list the instructions — that is the banner's job, post-generate, with room
    for them — but it does say how many, because "and 3 lines on it still need your wording" is
    what makes an estimator go and look. Singular and plural both, since "1 lines" in a warning is
    the kind of thing that makes people distrust it."""
    two = banner["row"]["lines"]["text"]
    assert "2 lines" in two, two
    one = banner["row"]["oneLine"]["text"]
    assert "1 line " in one and "1 lines" not in one, (
        "the row does not agree with itself in the singular: %r" % one)


def test_the_banner_lists_what_page_one_still_says(banner):
    """The state the feature is for: these lines will print to the customer exactly as shown.
    VERBATIM is the point — the tool must not summarise or rewrite them, because nobody has
    approved replacement wording and the README says not to invent it, so what the estimator reads
    here has to be what the .docx says."""
    two = banner["banner"]["lines"]
    assert two["items"] == ["[SHEEN - pick one: Level 2 (400 grit) / Level 3 (800 grit).]",
                            '[COVE HEIGHT - pick one: 4" / 6" / 8".]'], (
        "the lines were not passed through verbatim: %r" % (two["items"],))
    assert two["itemTags"] == ["LI", "LI"], "the lines are not list items"
    assert "2 lines" in two["head"], two["head"]
    one = banner["banner"]["oneLine"]
    assert "1 line of" in one["head"] and "1 lines" not in one["head"], one["head"]
    assert "Untick" in two["note"] and "Cover letter" in two["note"], two["note"]
    # The could-not-check state must not borrow the fresh headline, or it claims to have read a
    # page it never saw.
    stale = banner["banner"]["couldNotCheck"]
    assert "could not be checked" in stale["head"], stale["head"]
    assert stale["items"] == [], (
        "lines were listed for a check that never completed — invented detail is worse than none")
    assert "Reload" in stale["note"] or "reload" in stale["note"], stale["note"]
    assert stale["head"] != two["head"], (
        "'could not check' and 'here are the lines' print the same headline, so the estimator "
        "cannot tell a read page from an unread one")


def test_the_template_copy_is_written_as_text_and_never_as_markup(banner):
    """These lines come out of Kyle's .docx, over the network, into a page staff read.
    `textContent`, not `innerHTML` — a template edit is not a code review, and a bracketed
    instruction containing a tag would otherwise be markup running in the staff tool."""
    got = banner["banner"]["markupAsText"]
    assert got["items"] == ['[NOTE - <img src=x onerror="alert(1)"> pick one.]'], (
        "the line did not survive as text: %r" % (got["items"],))
    for name in ("lines", "oneLine", "couldNotCheck", "markupAsText"):
        assert banner["banner"][name]["innerHTMLWrites"] == 0, (
            "%s assigned innerHTML, so template copy is parsed as markup" % name)


def test_a_blank_line_never_reaches_either_surface(banner):
    """Filtered in the READER, which is the right place now that two callers share it — the row's
    count and the banner's list would otherwise disagree with each other about how many lines
    there are, one counting a blank the other did not print."""
    got = banner["reader"]["blanksFiltered"]
    assert got["placeholders"] == ["[SHEEN - pick one: Level 2 (400 grit) / Level 3 (800 grit).]"], (
        "blank and null entries were not filtered by the reader: %r" % (got["placeholders"],))
    rendered = banner["banner"]["blanksAlreadyFiltered"]
    assert len(rendered["items"]) == 1 and rendered["items"][0].strip(), rendered["items"]
    assert "1 line of" in rendered["head"], rendered["head"]


def test_both_surfaces_are_inert_where_their_markup_is_absent(banner):
    """Each is reached on paths that also serve projects saved before these elements existed, and
    each guards its two elements separately in the shipped code. Nothing thrown, nothing shown."""
    for name in ("noBoxAtAll", "noListElement"):
        assert banner["banner"][name]["threw"] is None, (name, banner["banner"][name]["threw"])
        assert banner["banner"][name]["shown"] is False, name
        assert banner["banner"][name]["checkCalls"] == 0, (
            "%s consulted the reader — and therefore the network — for a banner it cannot "
            "render" % name)
    partial = banner["banner"]["noHeadOrNote"]
    assert partial["threw"] is None and partial["shown"] is True, partial
    assert len(partial["items"]) == 2, "a missing headline took the whole banner down with it"
    for name in ("noMarkup", "noValue"):
        assert banner["row"][name]["threw"] is None, (name, banner["row"][name]["threw"])
        assert banner["row"][name]["shown"] is False, name
        assert banner["row"][name]["checkCalls"] == 0, (
            "the row consulted the reader for a row it cannot render (%s)" % name)


def test_the_surfaces_are_actually_in_the_page():
    """The premise of every test above: the harness supplies its own DOM, its own fetch and its
    own reader, so all of them would pass against a done.html that had neither surface in it.

    The banner's placement is asserted too — it lived inside `.success-card.fp-ready` first, which
    is `display: flex` in ROW direction until 820px, so it rendered as a fourth COLUMN beside the
    downloads and crushed the headline instead of sitting above the panel."""
    for node_id in ("cl-placeholders", "cl-ph-head", "cl-ph-text", "cl-ph-list",
                    "rv-cover-row", "rv-cover"):
        assert 'id="%s"' % node_id in DONE_PAGE, (
            "#%s is gone from done.html; that surface cannot render and the harness above would "
            "not have noticed" % node_id)
    post = DONE_PAGE.index('id="post-generate"')
    banner_at = DONE_PAGE.index('id="cl-placeholders"')
    ready = DONE_PAGE.index('class="success-card fp-panel fp-ready"')
    assert post < banner_at < ready, (
        "the banner is no longer the first thing inside #post-generate, above the downloads "
        "panel: post-generate at %d, banner at %d, panel at %d" % (post, banner_at, ready))
    between = DONE_PAGE[post:banner_at]
    assert between.count("<div") - between.count("</div>") == 1, (
        "#cl-placeholders is nested deeper than a direct child of #post-generate, so its width "
        "and its position both depend on whatever box was put around it")
    assert "display:none" in DONE_PAGE[banner_at:banner_at + 200], (
        "the banner does not start hidden, so every project shows it for a moment")
    # The row belongs to the review list, between the lump sum and the card's buttons.
    row_at = DONE_PAGE.index('id="rv-cover-row"')
    assert 'class="review-row" id="rv-cover-row"' in DONE_PAGE, (
        "the row is not a `.review-row` any more, so it will not line up with Work type, "
        "Audience and Lump Sum above it")
    assert "display:none" in DONE_PAGE[row_at:row_at + 120], (
        "the row does not start hidden, so every bid shows it until the script runs")
    assert (DONE_PAGE.index('id="rv-lump"') < row_at
            < DONE_PAGE.index('class="review-actions"')), (
        "the cover-letter row is outside the review list it belongs to")


def test_the_reader_asks_the_endpoint_that_exists():
    """The other half of the premise: the harness stubs `fetch`, so every test above would pass
    against a path the server does not serve. The path is checked against the route table in
    main.py rather than against a string in done.js, so a rename on either side is caught.

    ONE READER, ONE FETCH is asserted here as well as in the harness (which refuses to run
    otherwise) — two readers is defect 5 waiting to happen, and this says so with a message about
    the product rather than about a lift."""
    import main                                        # noqa: PLC0415 — heavy, only needed here
    m = re.search(r'fetch\(\s*TW\.resolveApiBase\(\)\s*\+\s*"([^"]+)"', DONE_JS)
    assert m, "the check's fetch is no longer a resolveApiBase() + literal path — re-derive this"
    path = m.group(1)
    paths = {getattr(r, "path", None) for r in main.app.routes}
    assert path in paths, (
        "the check fetches %r, which is not a route this server serves. It would fail on every "
        "load and both surfaces would say 'could not be checked' forever." % path)
    route = next(r for r in main.app.routes if getattr(r, "path", None) == path)
    assert set(route.methods) == {"GET"}, route.methods
    assert DONE_JS.count("function coverLetterCheck") == 1, (
        "there is more than one cover-letter reader in done.js, so the review row and the banner "
        "can drift apart again — which they did, for one build")
    assert DONE_JS.count("cover-letter/placeholders") == 1, (
        "a second caller of the placeholder endpoint means a second decision about which variant "
        "to ask about, which is the defect that showed 1 instruction and sent 4")
    assert DONE_JS.count("await coverLetterCheck()") == 2, (
        "expected exactly the two surfaces to consult the shared reader, found %d"
        % DONE_JS.count("await coverLetterCheck()"))


# ══ the flag's journey off this page ══════════════════════════════════════════
def test_the_fields_ride_the_frozen_payload_and_not_merely_the_request():
    """Inside `proposal_payload`, not alongside it. The payload is what gets FROZEN into a sent
    revision, and /api/admin/proposal-pdf re-renders a customer's document from that pinned copy —
    it reads `cover_letter_enabled` straight out of the blob to decide whether to build page 1. So
    a flag that rode only the POST body would generate correctly once, on the estimator's screen,
    and then vanish the first time the customer re-opened their proposal: same link, same prices,
    one page shorter.

    Ported from test_cover_letter_ui.py, which asserted `TWCoverLetter.payloadFields()` here. That
    helper is gone with the editor; the key is written directly now."""
    m = re.search(r"proposal_payload:\s*\{(.*?)\n      \},", PR_JS, re.S)
    assert m, "the proposal_payload literal moved — rewrite this check, do not delete it"
    assert "cover_letter_enabled" in m.group(1), (
        "cover_letter_enabled is outside proposal_payload, so a sent revision loses it and the "
        "customer's re-rendered PDF loses page 1")


def test_the_portal_is_told_the_proposal_has_a_letter():
    """The portal shows the letter only if it is TOLD there is one. `has_cover_letter` has been on
    `PortalPublishIn` and forwarded by /api/portal/publish since the field was added, and no real
    caller ever set it — so a customer whose bid had a letter got a portal that did not know.

    An earlier revision of this test derived the value from the GENERATE RESULT, on the reasoning
    that the question is "is there a letter in the package you just sent" and the generate response
    is the one thing that can't disagree with itself. That is true of the RESPONSE, but `result` is
    `state.generate_result` — persisted, never cleared — and `continueToDone` does not call
    /api/generate at all; it stashes a fresh `proposal_payload` and navigates straight to Done. So
    a toggle-then-Continue reaches this send with the OLD `generate_result` describing the
    PREVIOUS state of the letter, while `create_revision` (main.py) is about to pin the persisted
    `proposal_payload` — the exact blob /api/admin/proposal-pdf reads back later. Telling the
    portal what the generate response says, rather than what is about to be pinned, can disagree
    with the pinned snapshot in either direction.

    The correct source is `proposal_payload.cover_letter_enabled` — the same blob create_revision
    pins. Read FRESH out of TW.getState() at send time, not off the module-top `state`: this call
    site runs AFTER TW.flushState() (asserted below), which is what makes a fresh read race-free —
    the flush has just made the browser's copy and the server's copy identical."""
    m = re.search(r'TW\.postJSON\("/api/portal/publish\?draft_id=[^;]+;', DONE_JS, re.S)
    assert m, "the publish call moved — re-derive this check"
    body = m.group(0)
    assert "has_cover_letter" in body, (
        "the publish body never tells the portal about the letter — the field is a no-op again")
    # ORDER, not distance. This was a 4500-character lookback, which is a proxy for "the flush
    # comes first" that shrinks every time a line is added between the two — and RJ's
    # refused-save gate sits in exactly that gap, pushing it to 4572 and failing a test whose
    # CLAIM was still true. Both strings are unique in the file, so comparing their positions says
    # precisely what is meant and nothing more.
    assert DONE_JS.count("await TW.flushState()") == 1, (
        "a second flush site appeared — position alone no longer says which one runs first")
    assert DONE_JS.count("/api/portal/publish") == 1, (
        "a second publish site appeared — this test is now checking the wrong one")
    assert DONE_JS.index("await TW.flushState()") < m.start(), (
        "the publish call moved ahead of the flush — a fresh TW.getState() read here would no "
        "longer be guaranteed to match what create_revision is about to pin")
    # The value, not just the key. `generate_result` / its download url would be the stale copy.
    src = re.search(r"const hasCoverLetter = [^;]+;", DONE_JS, re.S)
    assert src, "hasCoverLetter is not derived — the key may be hard-coded"
    ctx = DONE_JS[max(0, src.start() - 700):src.end()]
    assert "TW.getState()" in ctx, "hasCoverLetter is read off a snapshot rather than live state"
    assert "proposal_payload" in ctx and "cover_letter_enabled" in src.group(0), (
        "hasCoverLetter no longer follows the blob create_revision is about to pin — the portal "
        "can now disagree with the pinned snapshot in either direction")
    # STRENGTHENED, because the original claim has stopped being able to fail. It read
    # `"cover_letter_download_url" not in ctx` — 700 characters around one statement — and that
    # url no longer exists on `GenerateOut` at all, so it could not appear in those 700 characters
    # however wrong the derivation became. Asserted over the WHOLE file instead: the stale
    # `generate_result` is still on this page and still tempting, and the name reappearing
    # anywhere in it means somebody has gone back to asking the previous generate what the next
    # send contains.
    assert "cover_letter_download_url" not in DONE_JS, (
        "cover_letter_download_url is back in done.js. It was removed from GenerateOut when the "
        "letter became page 1 of the proposal, so this reads undefined off a stale "
        "generate_result — which is how the portal came to disagree with the pinned snapshot")


def test_the_files_page_rebuild_carries_the_letter_too():
    """"View files" regenerates from a payload it rebuilds itself. Leave the letter out of it and a
    project that had one comes back with page 1 missing — the second download disagreeing with the
    first one the estimator already checked, and no way to see which is right without opening both.

    Ported from test_cover_letter_ui.py, which asserted `TWCoverLetter.payloadFields()` here."""
    m = re.search(r"async function viewFiles\(\)(.*?)\n  \}\n", DONE_JS, re.S)
    assert m, "viewFiles moved — re-derive this check"
    assert "cover_letter_enabled" in m.group(1), (
        "the Files-page rebuild drops cover_letter_enabled, so regenerating a project that has a "
        "letter hands back a proposal without its first page")


# ══ the editor is gone, and stays gone ════════════════════════════════════════
# Comments stripped before the scan below, in the order that matters: LINE comments first, THEN
# block comments. Done the other way round, a `/*` sitting inside a `//` comment reads as a block
# opener and pairs with the next real terminator, deleting everything between them — which in this
# repo has silently removed 590 lines from a probe and made an unrelated test claim a live feature
# had been deleted.
_LINE_COMMENT = re.compile(r'(^|[^:"\'`\\])//[^\n]*', re.M)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _code_only(suffix: str, text: str) -> str:
    """`text` with its comments removed, by file type.

    WHY PROSE IS EXEMPT, since the exemption is the arguable part. Every failure the guard below
    is for is a failure of CODE: a `<script src>` for a file that no longer exists, an element id
    with no script behind it, a stylesheet rule for a surface nobody mounts, an identifier that
    evaluates to `undefined`. None of those can be written in a comment. Meanwhile the house style
    in this repo is that comments quote the history that made each change necessary — so
    proposal-review.js's cover-letter switch says, correctly, that the wiring "used to belong to
    coverletter-editor.js". A probe that could not tell prose from code would report that sentence
    as the resurrection it is explaining, which is the same mistake test_fmt_ribbon.py and the
    deleted test_cover_letter_ui.py both had to be written around."""
    if suffix == ".js":
        return _BLOCK_COMMENT.sub("", _LINE_COMMENT.sub(r"\1", text))
    if suffix == ".css":
        return _BLOCK_COMMENT.sub("", text)
    return _HTML_COMMENT.sub("", text)


def _frontend_files():
    files = sorted(p for p in FRONTEND.rglob("*")
                   if p.is_file() and p.suffix.lower() in (".js", ".html", ".css"))
    assert len(files) > 20, (
        "only %d frontend files found under %s — this scan is not reaching the app"
        % (len(files), FRONTEND))
    return files


def test_no_trace_of_the_discarded_tab_and_download_survives_in_the_frontend():
    """A regression guard over the part of the old editor that stayed discarded when the rest of
    it came back on 2026-09-11: the tab strip, the off-stage parking class, and the Files page's
    fourth download button. Each fails QUIETLY if it comes back alone. A `#doc-tabs` div with no
    tab-click wiring behind it is a dead strip in the ribbon nobody built. A `cl-offstage` class
    reintroduced on either surface brings back the old two-tab visibility model that this restore
    deliberately does not have — `#cl-surface` is shown/hidden with the ordinary `hidden`
    attribute now, not moved off-screen, because there is no second "must still lay out" state to
    protect once the letter is either present or absent rather than mid switch. A `dl-cover`
    button implies a document that is downloadable on its own again, which the letter has not
    been since it became page 1 of the proposal.

    Scanned over every .js/.html/.css under frontend/, not just the files this module reads,
    because the way a name like this comes back is a merge that resurrects the page but not the
    script, or a stylesheet rule kept "in case"."""
    offenders = {}
    for path in _frontend_files():
        text = _code_only(path.suffix.lower(),
                          path.read_text(encoding="utf-8", errors="replace"))
        hits = sorted(name for name in GONE if name in text)
        if hits:
            offenders[path.relative_to(FRONTEND).as_posix()] = hits
    assert offenders == {}, (
        "the discarded half of the old cover-letter editor is referenced again: %r. Each of "
        "these fails silently on its own — see this test's docstring." % offenders)


def test_the_scan_above_is_looking_for_things_that_could_have_been_there():
    """The counterexample for the guard, which would otherwise be the easiest kind of green there
    is: three strings that never appear anywhere pass whether or not the scan reads the right
    directory, strips the right comments, or spells the names the way the product spelled them.

    So every entry in `GONE` is checked against the CODE of the tree that had the discarded half
    of the editor still in it. If one of them was never really there — a typo, or a name invented
    while writing the test — the guard above is vacuous for that name while the other two carry
    it, and vacuous is exactly what this repo has been caught by. Reported per name, not as a
    total, so the fix is obvious.

    PINNED TO A COMMIT, NOT A BRANCH TIP. This read `origin/staging` until 2026-09-11, when the
    editor's restoration (same day) moved staging's tip forward and `git show origin/staging:...`
    started returning the RESTORED files — which legitimately no longer carry `doc-tabs` or
    `cl-offstage`, so this test started failing about code that was never wrong. A branch pointer
    answers "what is there today", and today is exactly what this test must not read: it wants
    the tree from the one moment the discarded half still existed, which only a fixed commit
    keeps meaning after the branch moves again. `cf3e455^` is that moment — the commit
    immediately before the editor's original 2026-09-09 removal.

    Skips rather than fails without that commit: a shallow checkout cannot answer the question,
    and a skip says so where a failure would blame the product."""
    proc = subprocess.run(
        ["git", "show"] + ["cf3e455^:" + p for p in (
            "frontend/proposal-review.html", "frontend/done.html",
            "frontend/js/done.js", "frontend/js/coverletter-editor.js",
            "frontend/styles.css", "frontend/js/proposal-review.js")],
        cwd=str(FRONTEND.parent), capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    if proc.returncode != 0:
        pytest.skip("cf3e455^ is not readable in this checkout: "
                    + (proc.stderr or "").strip())
    # One `git show` of six blobs concatenates them, so the comment strippers are applied
    # per-language over the whole thing: `.js` is the superset (it strips both // and /* */), and
    # the html/css comment forms are stripped as well so a name that only ever lived in prose
    # cannot sneak through as evidence that it lived in code.
    was_there = _HTML_COMMENT.sub("", _code_only(".js", proc.stdout))
    missing = [name for name in GONE if name not in was_there]
    assert missing == [], (
        "these names in GONE were never in the pre-removal frontend CODE, so the scan that looks "
        "for them cannot fail: %r. Fix the spelling or drop the entry." % missing)
