"""Starting dictation when the microphone is refused — the "verbal intake not working" report.

The estimator pressed the mic button on the polish intake page and nothing happened. No permission
prompt, no message, no words in the box. It reads as a dead feature, and it was reported as one.

It was two faults stacked, and only one of them is in this repo.

THE ONE OUTSIDE. nginx sends `Permissions-Policy: microphone=()` on the proposal hosts. That is an
EMPTY allowlist rather than a default, so the browser forbids the mic for the whole origin and
refuses to even ask. Fixing that is an ops change to the `$treadwell_permissions` map, not a code
change, and no test here can cover it.

THE ONE IN HERE, WHICH THIS FILE OWNS. When the policy blocks the origin, `rec.start()` throws
SYNCHRONOUSLY — it does not fire the async `onerror` the panel already handles, because there is no
attempt to fail. The old code was `try { rec.start(); } catch (err) { return; }`: it caught the one
error that explains everything and threw it away. So even once the header is fixed, any browser or
extension that blocks the mic produces the same silent nothing, and the estimator has no way to tell
a blocked policy from a broken feature.

RUN, NOT READ. The bug was a silent `return`, and there is no source-text assertion about silence —
the old line parsed and linted and shipped. The harness hands `startDictation` a recognizer whose
`.start()` throws and reads what reached the screen. See
[backend/tests/js/verbal-dictation-harness.js](js/verbal-dictation-harness.js).
"""

import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "verbal-dictation-harness.js"


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_a_blocked_microphone_says_so_instead_of_returning_silently(ran):
    """The reported bug, pinned. A thrown .start() has to reach the estimator as a sentence.

    Restoring the old `catch (err) { return; }` empties `said` and fails on the first assertion,
    which is the check that matters: the failure mode was the ABSENCE of output, so the test has to
    assert presence, not shape.
    """
    b = ran["blocked"]
    assert b["startAttempted"] == 1                  # it really did try, so the throw is the real path
    assert len(b["said"]) == 1, "a blocked mic said nothing — this is the original bug"
    msg = b["said"][0]["msg"]
    assert b["said"][0]["kind"] == "warn"
    # The two things they can act on. Telling them to grant permission would be worse than silence:
    # they would go hunting a prompt the browser has already decided never to show.
    assert "no permission prompt will appear" in msg
    assert "Type into the box instead" in msg


def test_a_blocked_microphone_leaves_no_half_started_state(ran):
    """Nothing below the throw may run: no "listening", no held recognizer, no repainted button.

    A stuck `listening = true` would leave the mic button drawn as live over a recognizer that never
    started, so the next press would call stop() on nothing and the estimator would be toggling a
    control that has never once worked.
    """
    s = ran["blocked"]["state"]
    assert s["listening"] is False
    assert s["recHeld"] is False
    assert ran["blocked"]["micPainted"] == 0


def test_a_working_microphone_is_untouched(ran):
    """The happy path pays nothing for the new branch: still silent, still listening, still painted."""
    w = ran["working"]
    assert w["said"] == [], "a working mic should say nothing at all"
    assert w["state"] == {"listening": True, "recHeld": True}
    assert w["micPainted"] == [True]


def test_declining_the_prompt_keeps_its_own_gentler_wording(ran):
    """The two refusals are different events and must not collapse into one message.

    A person clicking Block chose that, and the advice is "type instead" with no implication that
    anything is wrong. The browser refusing to ask is nobody's choice, and its message has to say
    that no prompt is coming — otherwise the estimator waits for one. Both arrive as `warn` with
    `listening` cleared; only the sentence differs, and this is what holds them apart.
    """
    d = ran["declined"]
    assert len(d["said"]) == 1
    assert "No microphone, no problem" in d["said"][0]["msg"]
    assert "no permission prompt will appear" not in d["said"][0]["msg"]
    assert d["state"] == {"listening": False, "recHeld": False}


def test_a_browser_with_no_speech_api_stays_quiet(ran):
    """Guards the guard: `if (!Rec) return` fires first, so nothing is attempted and nothing is said.

    Silence is correct here and wrong in the blocked case, because the button is hidden when the API
    is missing — there is no control to explain.
    """
    n = ran["noSupport"]
    assert n["startAttempted"] == 0
    assert n["said"] == []
    assert n["state"] == {"listening": False, "recHeld": False}

def test_every_error_code_gets_a_message_that_names_what_to_do(ran):
    """The reported symptom, and the one that had no useful words: Brave.

    "I am able to speak in the microphone but it does not write it." Brave ships without a speech
    service — the Web Speech API does not transcribe locally, it streams to the vendor's own
    service — so the recognizer connects to nothing and fails with `network` AFTER the estimator has
    spoken a whole job description. Every visible sign said it was working until the text failed to
    appear, and the message they got was the same "Dictation stopped. You can keep typing." that a
    deliberate Stop produces. That is true and useless: it does not say the browser cannot do this.

    So the assertion is about the words, not the branch. `network` has to name Brave and offer the
    two real ways forward — type it, or use Chrome or Edge.
    """
    m = ran["messages"]

    for code in ("network", "service-not-allowed"):
        assert "Brave" in m[code], code
        assert "no speech service" in m[code], code
        assert "Chrome or Edge" in m[code], code

    # A declined prompt is a CHOICE, and must not be dressed up as a failure or sent browser-hunting.
    assert "No microphone, no problem" in m["not-allowed"]
    assert "Brave" not in m["not-allowed"]

    assert "No microphone was found" in m["audio-capture"]
    assert "Did not catch anything" in m["no-speech"]
    # Their own Stop: the plain sentence is right, and an unrecognised code keeps it too — but the
    # code is printed so a stranger in the wild can be reported rather than guessed at.
    assert m["aborted"] == "Dictation stopped. You can keep typing."
    assert m["language-not-supported"] == (
        "Dictation stopped (language-not-supported). You can keep typing.")
    assert m["undefined"] == "Dictation stopped. You can keep typing."


def test_the_message_table_is_actually_wired_to_onerror(ran):
    """The table being right and the table being REACHED are two claims, and one test cannot make both.

    A correct table wired to nothing leaves the product exactly as broken as it was. So this fires a
    real `network` error through the lifted `onerror` and reads what landed on screen.
    """
    n = ran["networkAtRuntime"]
    assert len(n["said"]) == 1
    assert "Brave" in n["said"][0]["msg"]
    assert n["said"][0]["kind"] == "warn"
    # And it still tears down: a failed recognizer must not leave the button drawn as listening.
    assert n["state"] == {"listening": False, "recHeld": False}
