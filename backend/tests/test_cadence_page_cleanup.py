"""The cadence page after Hanz's 2026-08-10 cleanup: no send-window card, and the token chips
became a drag-and-drop bar.

WHAT HE ASKED FOR, in his words.

    "Remove this section in the Cadence and emails"   [screenshot of "When emails may go out"]
    "aalso make this a drag and drop bar iunstead of a brace"   [screenshot of the
     {first_name} {project} {need} {link} chips under the Message box]

THE TRAP IN THE FIRST HALF, which is the whole reason this file exists.

Taking the two hour selects off the page does NOT mean the send window stopped mattering. It is
still stored, and email_sender still holds customer mail to it. The obvious implementation, drop
the controls and drop the two payload keys with them, quietly changes when Treadwell emails
customers:

  * the PUT lands on the portal's /api/admin/settings/followups, which runs
    followup_settings.validate() (portal backend/main.py:1764);
  * validate() does `out[field] = _clamp_int(raw.get(field), field)` for EVERY field in DEFAULTS;
  * `_clamp_int(None, field)` returns `int(DEFAULTS[field])`.

So a window somebody had set to 9-17 snaps back to the shipped 8-18 the first time anybody edits
an email. The near miss is that followup_settings.merge() DOES skip absent keys
(`if field in stored`), so reading merge() alone says omitting is safe. merge() is the read path
and never sees the payload. The page therefore has to round-trip the loaded hours untouched, and
these tests fail if anybody "tidies up" the two keys that look unused.

THE TRAP IN THE SECOND HALF, measured in Chrome 151 rather than assumed.

A textarea is not a contenteditable, so "insert at the drop point" needs an offset that maps to
selectionStart, and the two APIs do not agree:

    document.caretPositionFromPoint   offsetNode is the TEXTAREA ITSELF, offset is a real index
                                      into .value (7, 17, 97, 103, 122, 140-of-140 all landed on
                                      the right character)
    document.caretRangeFromPoint      startContainer is BODY, startOffset is 1, and it does not
                                      resolve into the control at all

Taken at face value the WebKit fallback would drop every token at character 1 of the message,
which is why dropOffset checks the node it was handed and returns null rather than a number it
cannot stand behind. Verified end to end with a real trusted drag: the token landed at 129, the
exact offset the resolver had computed for that point beforehand, exactly once, with the caret
left at 135.

Source-level, like the other frontend guards in this suite: the behaviour lives in a browser page
and what is checkable from pytest is that the wiring is present and shaped correctly.
"""
import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
JS = FRONTEND / "js" / "followup-settings.js"
HTML = FRONTEND / "followup-settings.html"


def _code():
    """The JS with `//` comment lines stripped.

    This file explains the bug by quoting it. The note left where the card used to be names the
    section, and dropOffset spells out what each API returns, so a raw grep matches its own
    prose. That has caught me out repeatedly in this repo.
    """
    return "\n".join(l for l in JS.read_text(encoding="utf-8").splitlines()
                     if not l.strip().startswith("//"))


def _markup():
    """The HTML with <!-- --> comments stripped, for the same reason.

    The note standing in for the removed card contains the words "When emails may go out",
    "startH" and "endH". Grepping the raw file for those would find the gravestone and report the
    card as still present.
    """
    return re.sub(r"<!--.*?-->", "", HTML.read_text(encoding="utf-8"), flags=re.S)


def _block(fn):
    """The body of `function fn(...) {` in the JS.

    Brace-counted rather than regex'd so a nested brace cannot truncate the block and make an
    assertion vacuous. Same helper as test_no_blink_live_refresh.py.
    """
    src = _code()
    m = re.search(r"\n\s{2,6}(?:async\s+)?function " + re.escape(fn) + r"\s*\(", src)
    assert m, "%s() is gone from followup-settings.js. Rewrite these tests, don't delete" % fn
    return _braces(src, src.index("{", m.end()))


def _listener(target, event):
    """The body of one `<target>.addEventListener("<event>", function (…) {`.

    NEVER grep the whole file for a guard name. There are six listeners on two elements here and
    several of them mention the same variables, so an assertion that is not scoped to the handler
    that must contain it can pass while that handler is empty, which is exactly how an earlier
    test in this suite passed with a broken panel.
    """
    src = _code()
    m = re.search(re.escape(target) + r'\.addEventListener\("' + re.escape(event) + r'",', src)
    assert m, "no %s listener on %s any more" % (event, target)
    return _braces(src, src.index("{", src.index("function", m.end())))


def _braces(src, i):
    depth, j = 0, i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
        j += 1
    pytest.fail("unbalanced braces reading followup-settings.js from offset %d" % i)


# ── Change A: the send-window card is gone ────────────────────────────────────
def test_the_send_window_card_is_gone_from_the_page():
    """The literal thing he circled. Kills the mutation of hiding the card rather than removing
    it, which leaves the selects in the DOM and the wiring alive."""
    html = _markup()
    assert "When emails may go out" not in html, "the card is still on the page"
    assert 'id="startH"' not in html and 'id="endH"' not in html
    assert "<select" not in html, (
        "a select survived the removal; these were the only two on the page")
    assert "Earliest hour" not in html and "Latest hour" not in html


def test_the_removal_left_a_note_saying_the_window_is_still_enforced():
    """A card deleted without a trace reads as "the send window was dropped", and the next person
    to be asked "why did that email go out at 7am?" has nothing to go on. The window is still
    stored and still honoured; only the control went."""
    raw = HTML.read_text(encoding="utf-8")
    note = re.findall(r"<!--(.*?)-->", raw, flags=re.S)
    hit = [n for n in note if "When emails may go out" in n]
    assert hit, "nothing records that the card was ever there"
    body = hit[0]
    assert "2026-08-10" in body, "the note does not say when, or on whose say-so"
    assert "still" in body.lower() and "enforce" in body.lower(), (
        "the note does not say the window is still enforced, which is the one thing a reader "
        "needs to know before assuming it is gone")
    assert "startH" in body and "endH" in body, (
        "the note does not name what to put back, so reinstating it means re-deriving the ids")


def test_hour_options_and_the_select_fills_are_gone_from_the_js():
    """hourOptions() built 24 <option>s for controls that no longer exist. Leaving it is dead
    code that reads as though the feature is still half-wired."""
    code = _code()
    assert "hourOptions" not in code, "hourOptions() is still here with nothing to fill"
    assert '$("startH")' not in code and '$("endH")' not in code
    fill = _block("fillNumbers")
    assert "startH" not in fill and "endH" not in fill, (
        "fillNumbers still writes to the removed selects, which throws on a null element and "
        "takes the whole page down on load")


def test_nothing_still_listens_to_the_removed_selects():
    """This is the crash, not a tidiness point. The listener loop ran at IIFE time, so
    `$("startH").addEventListener` on a missing element throws before load() is ever called and
    the page never leaves "Loading…"."""
    code = _code()
    assert '["startH", "endH"]' not in code
    assert not re.search(r'"(startH|endH)"[^\n]*addEventListener', code)


def test_the_save_payload_still_carries_the_send_window():
    """The mutation this kills is the tempting one: the controls are gone, so delete the keys.
    validate() reads a missing key as the DEFAULT, so that silently resets the stored window."""
    collect = _block("collect")
    assert "send_start_hour" in collect and "send_end_hour" in collect, (
        "the payload no longer sends the send window, so saving an email edit resets it to the "
        "shipped 8-18")


def test_the_window_is_round_tripped_from_what_was_loaded_not_hardcoded():
    """It has to be the values the GET returned. A literal 8/18 on this side would be a second
    definition of the default, and it would overwrite whatever staff had chosen with the shipped
    numbers just as surely as omitting the keys."""
    collect = _block("collect")
    assert re.search(r"send_start_hour:\s*CFG\.send_start_hour", collect), (
        "send_start_hour is not round-tripped from the loaded settings")
    assert re.search(r"send_end_hour:\s*CFG\.send_end_hour", collect), (
        "send_end_hour is not round-tripped from the loaded settings")
    for bad in ("8", "18", "9", "17"):
        assert not re.search(r"send_(start|end)_hour:\s*" + bad + r"\b", collect), (
            "the send window is hardcoded to %s, so the page now decides the default" % bad)


def test_why_omitting_them_is_unsafe_is_written_down_next_to_the_keys():
    """Without this the two keys look like leftovers from the deleted card, and the next cleanup
    removes them. The comment has to name the function that makes omitting dangerous."""
    raw = JS.read_text(encoding="utf-8")
    i = raw.index("send_start_hour: CFG.send_start_hour")
    note = raw[max(0, i - 1500):i]
    assert "validate()" in note, "the note does not name validate(), which is where the risk is"
    assert "merge()" in note, (
        "the note does not mention merge(), which is the function that makes omitting LOOK safe")


def test_the_reset_dialog_says_the_send_window_goes_with_it():
    """Removing the card left the confirm dialog as the ONLY place this can be said.

    Reset PUTs `settings: {}` so the server refills every field, send_start_hour and send_end_hour
    included. That was always true, and while the card was on the page you watched 9-17 turn back
    into 8-18 in front of you. Now nothing on screen does, before or after, so the dialog has to
    name it or a reset silently changes when Treadwell emails customers.

    Scoped to the reset handler: "may go out" also appears in the note where the card used to be,
    and a whole-file grep would pass on the gravestone.
    """
    src = JS.read_text(encoding="utf-8")
    i = src.index('$("reset").addEventListener')
    block = _braces(src, src.index("{", src.index("TW.confirmDanger(", i)))
    assert "may go out" in block, (
        "the reset confirmation does not mention the send window, which it also resets")


# ── Change B: the chips became a drag-and-drop bar ────────────────────────────
def test_the_chips_are_draggable():
    """A <button> is not draggable by default, so without the attribute the dragstart handler
    below never fires and the whole feature is inert."""
    paint = _block("paintTabs")
    assert 'draggable="true"' in paint, "the token chips cannot be picked up"
    assert paint.index("draggable") > paint.index('"tokens"'), (
        "draggable was added to the email TABS, not to the token chips")


def test_dragstart_publishes_the_token_as_plain_text():
    """text/plain is what makes a chip work anywhere: dropped into the subject box, the heading
    box, or out into another application entirely."""
    body = _listener('$("tokens")', "dragstart")
    assert re.search(r'setData\(\s*"text/plain"\s*,\s*tok\s*\)', body), (
        "dragstart does not set text/plain, so dragging a chip anywhere else deposits nothing")
    assert "TOK_MIME" in body, (
        "dragstart does not mark the drag as ours, so the drop handler cannot tell a chip from "
        "any other dragged text")


def test_dragover_preventdefaults_or_the_drop_never_fires():
    """The classic way to ship this looking finished and doing nothing at all."""
    body = _listener("msg", "dragover")
    assert "preventDefault()" in body


def test_dragover_does_not_accept_a_drag_it_cannot_use():
    """Cancelling dragover means "I will take this". Doing it unconditionally makes the textarea
    claim a spreadsheet dragged onto the page, and the drop then goes nowhere instead of the
    browser doing its normal thing with it."""
    body = _listener("msg", "dragover")
    assert "carriesText(e)" in body
    assert body.index("carriesText(e)") < body.index("preventDefault()"), (
        "the gate is after preventDefault, so it gates nothing")


def test_the_drop_inserts_at_the_point_it_landed_on():
    """The whole request: not the old caret, and not appended at the end."""
    body = _listener("msg", "drop")
    assert re.search(r"dropOffset\(\s*msg\s*,\s*e\.clientX\s*,\s*e\.clientY\s*\)", body), (
        "the drop does not resolve the pointer position, so the token lands at the caret")
    assert "insertToken(tok, at, at)" in body


def test_an_unresolvable_drop_point_falls_back_to_the_caret():
    """dropOffset returns null whenever it cannot map the answer honestly, off-viewport points
    included, which is what caretPositionFromPoint does. Without a fallback `at` would be null and
    the token would silently land at the end of the message."""
    body = _listener("msg", "drop")
    m = re.search(r"if\s*\(\s*at\s*==\s*null\s*\)", body)
    assert m, "there is no fallback when the drop point cannot be resolved"
    assert "selectionStart" in body[m.start():], "the fallback is not the caret"


def test_a_resolved_position_is_checked_against_the_textarea_before_it_is_trusted():
    """MEASURED, not assumed. caretRangeFromPoint over a textarea in Chrome 151 answers BODY with
    startOffset 1. Trust that and every dragged token lands at character 1 of the message."""
    body = _block("dropOffset")
    assert "ownedBy(node, ta)" in body, (
        "dropOffset trusts whatever node it is handed, so a position resolved outside the "
        "textarea is used as an index into its value")
    assert re.search(r"if\s*\(\s*!ownedBy\(node, ta\)\s*\)\s*return null", body)


def test_both_caret_apis_are_tried_and_the_offset_is_bounded():
    """The bound has to be pinned ON THE RETURN, not merely somewhere in the function.

    The first version of this asserted `"ta.value.length" in body`, and deleting the bound left it
    green: the whole-value length test two lines above says `ta.value.length` too, so the substring
    was satisfied by a completely different check. Caught by hand-mutating
    `return off > ta.value.length ? null : off;` to `return off;` and watching all 28 tests pass.

    It is not a tidiness point. An out-of-range offset is not refused, so insertToken clamps it to
    the end of the value and the token lands after "Thanks, Troy" instead of falling back to the
    caret, which is the exact failure the sibling test below says must not happen.
    """
    body = _block("dropOffset")
    assert "caretPositionFromPoint" in body and "caretRangeFromPoint" in body, (
        "one of the two position APIs is missing; the WebKit fallback is the second")
    assert re.search(r"return\s+off\s*>\s*ta\.value\.length\s*\?\s*null\s*:\s*off", body), (
        "an offset past the end of the value is not refused on the way out, so a stale position "
        "gets clamped to the end of the message instead of falling back to the caret")


def test_the_element_and_the_whole_value_text_node_are_the_only_shapes_accepted():
    """The two shapes where `offset` really is an index into .value: the control itself (what
    Chrome returns), or a text node holding the entire value. An offset into ONE LINE of a value
    split across nodes is not an offset into the value, and there is no way to add up the lines in
    front of it from here."""
    body = _block("dropOffset")
    assert "node !== ta" in body
    assert "node.nodeValue.length === ta.value.length" in body, (
        "a per-line offset would be accepted as a whole-value offset")


# ── click has to survive, and both paths must agree ───────────────────────────
def test_click_to_insert_still_works():
    """It is the keyboard and touch path. Drag needs a pointer, and {link} is mandatory, the
    server refuses a body without it, so losing click would leave some estimators unable to save
    an email at all."""
    body = _listener('$("tokens")', "click")
    assert "insertToken(" in body, "clicking a chip no longer inserts anything"
    assert "selectionStart" in body, "the click no longer inserts at the caret"


def test_why_click_was_kept_is_written_down():
    """Otherwise the next reader sees two ways to do one thing and deletes the older one."""
    raw = JS.read_text(encoding="utf-8")
    i = raw.index('$("tokens").addEventListener("click"')
    note = raw[max(0, i - 900):i]
    assert "keyboard" in note.lower(), (
        "nothing records that click is the keyboard path, so it reads as redundant")


def test_both_ways_in_share_one_insert():
    """Two copies of the splice would drift, and only one of them would be the one anybody tests.
    setSelectionRange is written in exactly one place, which is what proves they share it."""
    code = _code()
    assert code.count("setSelectionRange") == 1, (
        "the insert is implemented more than once; the click and the drop will drift apart")
    assert code.count("insertToken(") >= 3, (
        "insertToken is not called from both the click and the drop path")
    insert = _block("insertToken")
    assert "schedulePreview()" in insert, (
        "an inserted token does not refresh the preview, so the one safety net on this page goes "
        "stale the moment you use the chips")


def test_the_inserted_token_leaves_the_caret_after_it():
    """Dropping {first_name} and then typing has to continue after the token, not select it."""
    insert = _block("insertToken")
    assert re.search(r"setSelectionRange\(from \+ tok\.length, from \+ tok\.length\)", insert)


# ── a drop we did not start must be left alone ────────────────────────────────
def test_a_drop_that_is_not_a_token_is_left_to_the_browser():
    """Two failure modes in one guard. preventDefault on every drop SWALLOWS text dragged in from
    elsewhere; handling it ourselves as well as the browser DUPLICATES it; and a selection dragged
    from inside this same box is a MOVE, which we would turn into a copy and leave the original
    behind."""
    body = _listener("msg", "drop")
    m = re.search(r"if\s*\(\s*!isTokenDrag\(e\)\s*\)\s*return", body)
    assert m, "the drop handler takes over every drop, not just its own chips"
    assert m.start() < body.index("preventDefault()"), (
        "preventDefault runs before the token check, so a foreign drop is already swallowed")


def test_the_token_is_identified_by_our_own_drag_type_not_by_its_text():
    """Matching on the text would mean somebody dragging the words "{link}" in from an email
    would be treated as a chip, and a chip whose text changed would stop being one."""
    code = _code()
    assert "application/x-treadwell-token" in code
    body = _block("isTokenDrag") if "function isTokenDrag" in code else None
    if body is None:
        i = code.index("var isTokenDrag")
        body = _braces(code, code.index("{", code.index("function", i)))
    assert "e.dataTransfer.types" in body, "the check does not read the drag's types"
    assert "for (" in body, (
        "types is a DOMStringList on older engines, so includes()/indexOf() is not safe here")
    # The comparison itself, not merely that the constant exists somewhere in the file. The first
    # version of this test asserted only that "application/x-treadwell-token" appeared and that
    # the loop was there, and it passed happily against a loop comparing every type to "x".
    assert re.search(r"===\s*TOK_MIME", body), (
        "the loop does not compare the drag's types against our own drag type, so it either "
        "matches nothing or matches every drag")


# ── the visible drop state ────────────────────────────────────────────────────
def test_the_textarea_shows_where_the_token_will_land():
    for event in ("dragenter", "dragleave"):
        body = _listener("msg", event)
        assert "dropping" in body, "%s does not toggle the drop state" % event
    assert "classList.add(\"dropping\")" in _listener("msg", "dragenter")
    assert "classList.remove(\"dropping\")" in _listener("msg", "dragleave")


def test_only_a_token_drag_lights_the_box_up():
    """The highlight must not promise something the dragover handler then refuses.

    dragover deliberately does NOT cancel a file drag, so the page never claims a spreadsheet
    dropped on the message box. If dragenter highlights anyway, the box turns red under the
    pointer, the drop does nothing, and Chrome navigates away to the file instead. Measured: with
    the gate in place a synthetic drag whose types are ["Files"] leaves .dropping off.

    Pinned because moving the gate below the highlight survived the first version of this file:
    the test above only looks for classList.add, which is still there either way.
    """
    body = _listener("msg", "dragenter")
    m = re.search(r"if\s*\(\s*!isTokenDrag\(e\)\s*\)\s*return", body)
    assert m, "dragenter highlights any drag at all, including a file the page will not accept"
    assert m.start() < body.index('classList.add("dropping")'), (
        "the gate is after the highlight, so it gates nothing")


def test_the_drop_state_class_is_actually_styled():
    """A typo'd class name is a silent no-op: every test above still passes and nothing lights up
    on screen. The page styles itself, so the rule has to be in this file's own <style>."""
    assert "textarea.dropping" in _markup(), (
        "nothing in the stylesheet matches the class the JS adds")


def test_the_highlight_is_counted_so_it_does_not_flicker():
    """Dragging across a textarea sends leave/enter pairs as the pointer crosses its own inner
    content. A bare remove blinked the highlight off and on while the pointer never left."""
    body = _listener("msg", "dragleave")
    assert "overDepth" in body
    assert re.search(r"--overDepth\s*<=\s*0", body), (
        "the dragleave clears the highlight unconditionally")


def test_the_highlight_is_cleared_when_the_drag_ends_somewhere_else():
    """Let go outside the box and the drop never fires, so the highlight would sit there lit up
    over a textarea that received nothing."""
    body = _listener('$("tokens")', "dragend")
    assert 'classList.remove("dropping")' in body
    drop = _listener("msg", "drop")
    assert 'classList.remove("dropping")' in drop, (
        "a successful drop leaves the box highlighted")


# ── the chips are rebuilt on every tab switch ────────────────────────────────
def test_the_chip_listeners_survive_the_strip_being_rebuilt():
    """paintTabs replaces #tokens.innerHTML on every email tab switch. Anything bound to the chips
    themselves works on the first email and silently stops on the second. The failure that reads
    as "drag and drop only works sometimes"."""
    code = _code()
    for event in ("click", "dragstart", "dragend"):
        assert '$("tokens").addEventListener("%s"' % event in code, (
            "the %s handler is not delegated on #tokens" % event)
    # Written as a quoted SELECTOR, not the bare string ".tok": that matched `j.tokens` on the
    # first run and failed against correct code, which is the same substring trap the helpers at
    # the top of this file exist for.
    assert not re.search(r"""querySelector(All)?\(\s*["'][^"']*\.tok\b""", code), (
        "something binds to the chips by class; those nodes are destroyed by the next paintTabs")


# ── the chips have to say they can be dragged ────────────────────────────────
def test_the_chips_advertise_both_ways_in():
    """This asserted a SENTENCE on the page ("Drag a placeholder into the message, or click one
    to drop it where the cursor is") until Hanz deleted that blurb on 2026-08-12. The claim it
    protects is unchanged — a draggable control that looks like a button teaches nobody — so it
    now reads the only place left that says so: the chip's own tooltip.

    Kept rather than dropped with the sentence, because `draggable="true"` is invisible. Lose
    both the prose and the title and drag-and-drop becomes a feature nobody finds."""
    js = _js()
    i = js.index('$("tokens").innerHTML')
    chip = js[i:i + 1400]
    assert 'draggable="true"' in chip, "the chips are no longer draggable"
    low = chip.lower()
    assert "drag" in low, "nothing tells the user the chips can be dragged"
    assert "click" in low, "nothing tells the user clicking works too"


# ── one editable subject for the whole project thread (2026-08-11) ────────────
def _page():
    return (pathlib.Path(__file__).resolve().parents[2]
            / "frontend" / "followup-settings.html").read_text(encoding="utf-8")


def _js():
    return (pathlib.Path(__file__).resolve().parents[2]
            / "frontend" / "js" / "followup-settings.js").read_text(encoding="utf-8")


def test_the_per_template_subject_field_is_gone():
    """Hanz asked for one email thread per project. Gmail groups by the References chain AND the
    subject, so four templates with four subjects meant four conversations about one job.

    The field could not simply be IGNORED. It was a labelled input on this page: somebody types
    a subject, saves, and nothing happens — worse than either alternative. So it moved up to
    project level instead of dying in place.
    """
    page, js = _page(), _js()
    assert 't-subject' not in page, "the per-template Subject input is still on the page"
    assert 't-subject' not in js, "the JS still reads or writes a per-template subject"
    assert 'id="thread-subject"' in page, "there is no project-level subject field"


def test_the_project_subject_is_above_the_per_email_tabs():
    """It applies to every email, so it must not sit inside the tabbed editor where it reads as
    a property of whichever email is selected."""
    page = _page()
    assert page.index('id="thread-subject"') < page.index('id="tabs"')


def test_the_heading_field_survived():
    """This is what still varies per email, and it is the only thing left carrying the event
    wording — the subject stopped naming it."""
    assert 'id="t-title"' in _page()
    assert '$("t-title")' in _js()


def test_the_subject_is_ROUND_TRIPPED_on_save():
    """The trap this page already documents for the send window, now applicable to one more
    field. The PUT runs followup_settings.validate(), which calls
    validate_thread_subject(raw.get("thread_subject")); an absent key is None, which that
    function reads as "cleared" and answers with the shipped wording. So omitting it from the
    payload would silently reset a customised subject the first time anybody edited an email.
    """
    js = _js()
    i = js.index("send_start_hour: CFG.send_start_hour")
    j = js.index("templates: CFG.templates", i)
    assert "thread_subject:" in js[i:j], (
        "thread_subject is not in the save payload, so saving any edit resets it")


def test_the_field_is_populated_from_the_stored_value():
    assert 'CFG.thread_subject' in _js(), "the field never loads what is saved"


def test_switching_email_tabs_does_not_touch_the_project_subject():
    """It belongs to the cadence, not to one email. Filling it in fillTemplate would reload or
    clear it every time somebody clicked a tab."""
    js = _js()
    i = js.index("function fillTemplate")
    j = js.index("function collect", i)
    assert "thread-subject" not in js[i:j], (
        "fillTemplate touches the project subject, so changing tabs would overwrite it")


def test_the_preview_shows_the_project_subject():
    """The server stopped rendering a per-template subject, so an unchanged preview would print
    "(no subject)" over every email and read as broken."""
    js = _js()
    i = js.index("function renderPreview")
    body = js[i:js.index("\n  function ", i + 1)]
    assert "thread-subject" in body, "the preview no longer shows a subject at all"
    assert "pv.subject" not in body, "the preview still reads a subject the server does not send"


# ── the timing hints and the emails blurb came off (Hanz, 2026-08-12) ─────────
def test_the_per_field_timing_hints_are_gone():
    """Hanz: "Delet these descriptions in the timing container in cadence and emails".

    Five one-liners under the five numeric inputs. The labels above them already say what each
    field is ("First reminder", "Then every", "Stop after") and the card keeps its one-sentence
    sub, so the hints were repeating the label in longer words — and one of them still quoted an
    hours figure after the fields moved to days, which is how explanatory copy rots.
    """
    page = _page()
    assert 'class="fhint"' not in page, "the per-field timing hints are back"
    for gone in ("After sending, and after the first view",
                 "Counted from the first view",
                 "on the flow chart",
                 "time to make it personal",
                 "nag forever"):
        assert gone not in page, "the hint %r is back" % gone


def test_the_dead_hint_style_went_with_them():
    """A rule for an element nobody renders reads as though the element is still there — the
    leftover that makes the next reader think the copy exists somewhere."""
    assert ".fhint" not in _page()


def test_the_timing_card_still_says_what_the_numbers_mean():
    """Deleting the per-field hints must not leave five bare boxes. The card's own sentence is
    what survives, and it is the thing that says the unit."""
    page = _page()
    assert "Days between reminders" in page
    assert page.count("<span>days</span>") == 4
    assert "<span>reminders</span>" in page, "Stop after N lost its unit"


def test_the_emails_card_blurb_is_gone():
    """Hanz: "Delete this in the email as well" — the "Plain text ... Drag a placeholder" line."""
    page = _page()
    for gone in ("Plain text", "laid into the Treadwell letterhead", "Drag a placeholder"):
        assert gone not in page, "the emails-card blurb is back: %r" % gone


def test_the_placeholder_chips_still_explain_themselves():
    """The removed blurb was the only prose saying the chips are draggable. Each chip keeps its
    own title, which is now the only explanation there is — so it has to stay."""
    js = (pathlib.Path(__file__).resolve().parents[2]
          / "frontend" / "js" / "followup-settings.js").read_text(encoding="utf-8")
    assert 'draggable="true"' in js, "the chips are no longer draggable"
    assert "title=" in js[js.index("$(\"tokens\").innerHTML"):js.index("$(\"tokens\").innerHTML") + 1200], (
        "the placeholder chips have no tooltip, and the sentence that explained them is gone")
