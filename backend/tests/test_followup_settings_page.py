"""The follow-up cadence editor — the tool's side.

The portal owns the storage and every guard rail (its own test_followup_settings.py has 88 tests on
those). This file covers the two things that live here: the proxy endpoints, and the page's
promises about how it behaves when somebody edits an email a customer will receive.

The preview is the reason this page exists rather than a form. Everything edited here lands in a
customer's inbox and repeats every few days, and a text box gives no feedback: an unfilled
placeholder, a deleted button or a sentence that reads oddly inside the letterhead are all
invisible until a customer has it. So the preview is rendered BY THE SERVER, through the same code
the worker uses — a client-side approximation could flatter the real thing and that is exactly the
failure this page is meant to prevent.
"""
import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
JS = FRONTEND / "js" / "followup-settings.js"
HTML = FRONTEND / "followup-settings.html"


@pytest.fixture(scope="module")
def js():
    return JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def html():
    return HTML.read_text(encoding="utf-8")


# ── the proxies ───────────────────────────────────────────────────────
def test_the_tool_proxies_all_three_endpoints():
    src = (pathlib.Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert '@app.get("/api/followup-settings")' in src
    assert '@app.put("/api/followup-settings")' in src
    assert '@app.post("/api/followup-settings/preview")' in src
    for path in ('"/api/admin/settings/followups", "GET"',
                 '"/api/admin/settings/followups", "PUT"',
                 '"/api/admin/settings/followups/preview", "POST"'):
        assert path in src, path


def test_the_server_stamps_who_changed_it_not_the_browser():
    """These settings send email to CUSTOMERS, so "who and when" has to be answerable later — and
    the browser must not be the thing that decides whose name goes on it."""
    src = (pathlib.Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    i = src.index('@app.put("/api/followup-settings")')
    block = src[i:i + 900]
    assert 'payload["by"] = _user_email(request)' in block


# ── the page ──────────────────────────────────────────────────────────
def test_the_page_loads_its_script_and_the_shell(html):
    assert "/js/followup-settings.js" in html
    assert "auth.js" in html and "shared.js" in html
    assert "<script>" not in html.replace('<script src=', ''), "no inline scripts (CSP)"


def test_every_request_waits_for_the_token_in_one_place(js):
    """The Bid Calendar shipped a 401 that hid data because one fetch waited for the bearer token
    and its sibling did not."""
    code = "\n".join(l for l in js.split("\n") if not l.strip().startswith("//"))
    assert code.count("await window.TWAuth.ready") == 1
    assert code.count("fetch(") == 1, "a fetch outside api() would skip the token wait"


def test_the_preview_is_rendered_by_the_server(js):
    """A client-side approximation could flatter the real email, which is the one failure this page
    exists to prevent."""
    assert '"/api/followup-settings/preview"' in js
    i = js.index("function schedulePreview(")
    block = js[i:i + 1200]
    assert "collect()" in block, "the preview must reflect what is currently typed"


def test_the_preview_is_debounced(js):
    """One request per keystroke would be a request per keystroke against the portal."""
    i = js.index("function schedulePreview(")
    block = js[i:i + 400]
    assert "clearTimeout" in block and "setTimeout" in block


def test_a_template_that_will_not_send_says_so_next_to_the_wording(js):
    """Not as a surprise when Save is pressed — the author is looking at the text, so the problem
    belongs there."""
    assert "function previewFailed(" in js
    i = js.index("function previewFailed(")
    assert '$("pv-bad")' in js[i:i + 400]
    # and the failure path is actually wired to it
    j = js.index("function schedulePreview(")
    assert "previewFailed(" in js[j:j + 1200]


def test_switching_email_keeps_what_was_typed(js):
    """Four templates share one set of fields, so switching tabs without collecting first would
    silently discard an edit."""
    i = js.index('$("tabs").addEventListener')
    block = js[i:i + 500]
    assert "collect();" in block
    assert block.index("collect();") < block.index("KEY ="), (
        "the current tab must be collected BEFORE the key changes")


def test_clamped_numbers_are_read_back_after_saving(js):
    """Numbers are pulled into range on the way in. Somebody who typed 2 hours has to see they got
    4, rather than believing their edit took."""
    i = js.index('$("save").addEventListener')
    block = js[i:i + 2000]
    assert "fillNumbers();" in block, "the form is not refreshed from what was stored"
    assert "adjusted" in block, "nothing tells the user their value was changed"


def test_a_reset_is_an_empty_payload_not_a_second_copy_of_the_defaults(js):
    """Otherwise "default" is defined in two places and they drift."""
    i = js.index('$("reset").addEventListener')
    block = js[i:i + 1400]
    assert "settings: {}" in block
    assert "24" not in block and "72" not in block, (
        "the page appears to hardcode default numbers; the server owns those")


def test_a_reset_asks_first(js):
    i = js.index('$("reset").addEventListener')
    block = js[i:i + 800]
    assert "confirmDanger" in block


def test_the_page_says_whether_anybody_has_ever_changed_it(js):
    """A fresh install and an edited one otherwise look identical, and "did someone change this?"
    is the first question when the cadence surprises somebody."""
    assert "Never changed" in js
    assert "j.saved" in js
    # Written in ONE place. The first version of this test asserted only that the two strings
    # appeared somewhere in the file, which they did — inside load() — while save() and reset()
    # never touched the line. It passed, and the page told a lie on staging.
    #
    # Counting the STRING would count the comment above showWhoChanged() that quotes it, which is
    # how a test ends up measuring its own prose. Count the write to the element instead.
    assert js.count('$("meta").textContent') == 1, (
        "the audit line is written in more than one place; they will drift")


@pytest.mark.parametrize("handler", ['$("save").addEventListener',
                                     '$("reset").addEventListener'])
def test_saving_or_resetting_refreshes_who_changed_it(js, handler):
    """Found by using the page, not by the tests above.

    Saving stored the edit correctly and left "Never changed — this is the cadence as shipped" on
    screen underneath it, until somebody reloaded. That line exists to answer exactly one question
    and was answering it wrongly at the only moment anybody had reason to look."""
    block = js[js.index(handler):][:2400]
    assert "showWhoChanged(j)" in block, (
        "this path changes who last edited the cadence but does not update the line that says so")


def test_the_audit_line_and_the_previews_refresh_together(js):
    """Both come from the same response; refreshing one and not the other is how it broke."""
    for handler in ('$("save").addEventListener', '$("reset").addEventListener'):
        block = js[js.index(handler):][:2400]
        assert "renderPreview(" in block and "showWhoChanged(" in block


def test_the_server_owns_what_each_email_is_called(js):
    """The refusal messages quote these names ("the “Second reminder” email needs {link}"). If the
    page kept its own copy, a message could name a tab that does not exist."""
    assert "LABELS[k] = j.labels[k]" in js, "the page ignores the labels the server sends"
    # Asserting only that "j.labels" appears somewhere is not enough: disabling the block with
    # `if (false)` left the text in the file, inside code that can never run, and the test passed.
    # Nor is it enough to look at the NEAREST `if` — that is the inner one, which still mentions
    # j.labels while the outer one has been switched off. Check every condition on the way in.
    i = js.index("LABELS[k] = j.labels[k]")
    # From the guard that opens the block to the assignment — not a fixed window, which swept in
    # the unrelated j.tokens check next door and failed on correct code.
    start = js.rindex("if (", 0, js.index("Object.keys(LABELS)"))
    conditions = re.findall(r"if \(([^)]*)\)", js[start:i])
    assert conditions, "no conditional guards the adoption at all"
    for cond in conditions:
        assert "j.labels" in cond, (
            "a condition gating the labels does not depend on them (%r) — the block is "
            "unreachable or gated on the wrong thing" % cond)
    i = js.index("var LABELS")
    assert "fall back" in js[max(0, i - 400):i + 200], (
        "the local copy needs to be marked as a fallback, or it reads as the source of truth")


def test_the_tokens_are_offered_with_an_explanation(js):
    """{need} in particular is not self-explanatory — it is the deposit-conditional phrase."""
    i = js.index("function paintTabs(")
    block = js[i:i + 1400]
    assert "{need}" in block and "deposit" in block
    assert "required" in block, "{link} being mandatory is not explained"


def test_a_token_is_inserted_at_the_caret(js):
    """Appending to the end would make the buttons useless for anything but a first draft."""
    i = js.index('$("tokens").addEventListener')
    block = js[i:i + 800]
    assert "selectionStart" in block and "setSelectionRange" in block


def test_the_page_explains_that_changes_are_not_retroactive(html):
    """The first worry on reading "changes apply to every proposal" is whether it re-sends
    anything."""
    assert "retroactively" in html or "nothing is re-sent" in html


def test_the_send_window_explains_why_it_exists(html):
    """A 3am reminder reads as a robot and invites a spam complaint — worth saying, or somebody
    will widen it to 24 hours."""
    assert "3am" in html or "robot" in html


def test_the_sidebar_links_to_it_without_a_duplicate_glyph():
    auth = (FRONTEND / "auth.js").read_text(encoding="utf-8")
    assert 'navItem("/followup-settings.html"' in auth
    glyphs = re.findall(r'navItem\("[^"]+", "([^"]+)"', auth)
    assert len(glyphs) == len(set(glyphs)), "two sidebar items share a glyph: %s" % glyphs


def test_a_failed_read_disables_saving_rather_than_offering_the_defaults(js):
    """From the adversarial audit of this batch, and the worst thing it found.

    Saving REPLACES the whole row — five intervals, the send window and the wording of all four
    customer emails — on a single-row table with no history. If a failed read is shown as an empty
    one, the page displays the shipped defaults under the words "Never changed" and one press of
    Save destroys wording somebody may have written by hand months ago, with that estimator's name
    on the change."""
    assert "read_failed" in js, "the page ignores the flag that says the read failed"
    i = js.index("function lockForFailedRead")
    block = js[i:i + 1200]
    assert '$("save").disabled' in block and '$("reset").disabled' in block, (
        "a page that cannot see the current settings must not be able to overwrite them")
    # And it must be called on load, not merely defined.
    assert "lockForFailedRead(" in js[js.index("async function load("):]


def test_a_failed_read_does_not_claim_the_cadence_has_never_been_changed(js):
    """"Never changed — this is the cadence as shipped" is a factual claim. Printed over a row we
    could not read, it is both wrong and the exact reason somebody would feel safe pressing Save."""
    i = js.index("function showWhoChanged")
    block = js[i:i + 500]
    assert "read_failed" in block, "the audit line does not know the read failed"
    assert block.index("read_failed") < block.index("Never changed"), (
        "the never-changed branch is reached before the failed-read one is considered")


def test_the_reason_saving_is_off_survives_the_first_keystroke(js):
    """A greyed-out Save with no explanation is a bug report. The inputs clear a stale "Saved."
    line, so they must not also clear the warning that explains the dead button."""
    assert "clearUnlessLocked" in js
    i = js.index("var clearUnlessLocked")
    assert "if (!locked)" in js[i:i + 120]
