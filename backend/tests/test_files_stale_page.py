"""A Files page holding an older copy of the draft than the server's must not write it back.

Review of fix 3, 2026-09-25. initDraftSync does not re-read a localStorage blob already stamped for
this draft, so a Files page reopened on a machine that held the project before, or left open while
a colleague revised it elsewhere, holds an OLDER copy than the server's. Pressing Download recorded
the build with TW.setState, which PUTs the page's whole blob: RJ's newer revision was written away,
and the Send that followed froze Kyle's stale payload, a document nobody had downloaded.

Now the press writes nothing to the server (the server records has_files itself, see
test_send_equals_download.py), and Send carries the render_id of the file that was downloaded, so
the server can refuse to freeze anything else. And since the review of fix 4, Send itself refuses
on a page whose copy is not the server's, and the save it makes after a send is made only while
the server still holds the copy that was checked.

EXECUTED, NOT READ: the harness runs the REAL shared.js in a vm and the shipped done.js functions,
including the Send button's click handler (see its header).
"""
import json
import pathlib
import shutil
import subprocess

import pytest

HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "files-stale-page-harness.js"


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS)], capture_output=True, text=True,
                          encoding="utf-8", timeout=120)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_a_download_on_a_stale_page_writes_nothing_over_the_server(ran):
    """THE DEFECT. The download renders the server's copy (RJ's), and afterwards — the debounce
    elapsed and Send's flush run — the server still holds RJ's copy and not one PUT went out.

    Mutation: record the build with TW.setState in freshDocuments (the fix 3 commit) — one PUT,
    and the server's texture and rooms become the stale page's."""
    d = ran["download"]
    assert d["error"] is None, d["error"]
    assert d["rendered"] == "Smooth Finish", "the download did not render the server's copy"
    assert d["puts"] == 0, "the Download press PUT the page's stale blob over the draft"
    assert d["serverTexture"] == "Smooth Finish"
    assert d["serverRooms"] == [{"name": "RJ's revision", "is_base": True}]


def test_the_build_is_still_remembered_by_this_page(ran):
    """Locally: the page's own reload lands on its download buttons, and its card shows the figure
    the SERVER's copy was filled with ($12,500.00), not the stale page's own ($10,000.00)."""
    d = ran["download"]
    assert d["keptLocally"] is True
    assert d["stamp"] == "$12,500.00"


def test_a_stale_page_sends_nothing_and_writes_nothing(ran):
    """Review of fix 4, finding 2. This page's copy (Kyle's Orange Peel, keyed by his own Continue)
    and the server's (RJ's, keyed by RJ's) BOTH hold their keys, so the key checks passed: the
    publish froze RJ's document from a page showing Kyle's, and the save a send makes afterwards PUT
    Kyle's whole copy back over RJ's. Now Send refuses because the two copies differ — with or
    without a Download first — nothing is posted, nothing is PUT even once the debounce has run,
    and RJ's copy stands.

    Mutation: drop the one-copy check (`!TW.matchesServer(_saved)`) from the Send handler — one
    publish goes out and one PUT puts Kyle's texture and rooms back."""
    for name in ("staleSend", "staleDownloadThenSend"):
        s = ran[name]
        assert s["posted"] == 0, (name, s)
        assert s["puts"] == 0, (name, s)
        assert s["serverTexture"] == "Smooth Finish", (name, s)
        assert s["serverRooms"] == [{"name": "RJ's revision", "is_base": True}], (name, s)
        assert s["err"] and "Reload this page" in s["err"], (name, s)


def test_after_a_send_the_draft_remembers_the_message_in_one_save(ran):
    """A current page's send still remembers the message for a re-send, on the server, in one save.

    Mutation: remove the remember block, or its flush — the message never reaches the server."""
    r = ran["remembered"]
    assert r["posted"] == 1 and r["err"] is None, r
    assert r["puts"] == 1, r
    assert r["serverMessage"] == "See the attached."
    assert r["serverTexture"] == "Smooth Finish"


def test_a_colleagues_save_during_the_publish_is_not_put_back(ran):
    """The publish takes seconds. RJ's save landing inside them made this page's copy the older
    one, so the remember-the-message save is skipped: no PUT, and RJ's Knockdown stands.

    And the check before the send found the two copies equal, so that is recorded as the copy last
    seen on the server (TW.matchesServer): the next Files visit can then tell RJ's save is simply
    newer and take it, where a stale record would read both copies as moved and stop to ask.

    Mutations: remember unconditionally (drop the re-read) — one PUT, the server's texture is gone;
    record nothing in matchesServer — recordedAsSynced is False."""
    c = ran["colleagueDuringPublish"]
    assert c["posted"] == 1, c
    assert c["puts"] == 0, c
    assert c["serverTexture"] == "Knockdown"
    assert c["serverMessage"] is None
    assert c["recordedAsSynced"] is True


def test_send_hands_back_the_document_that_was_downloaded(ran):
    """The real Send handler posts the render_id of the file the estimator downloaded, so the
    server can refuse to freeze a different one.

    Mutation: drop `document_render_id` from the publish body, or stop downloadAs recording it."""
    s = ran["sendAfterDownload"]
    assert s["posted"] == 1, s
    assert s["renderId"] == s["checked"] == "K:Smooth Finish", s


def test_a_send_with_no_download_claims_nothing(ran):
    """Nothing was downloaded on this page view, so there is nothing to hold the send to; the key
    is left out and the server sends as it always has.

    Mutation: send `checkedDocument.renderId` even when empty — an empty key is posted."""
    s = ran["sendWithoutDownload"]
    assert s["posted"] == 1, s
    assert s["hasKey"] is False, s


def test_a_refused_send_says_why_in_the_servers_words(ran):
    """The 409 `document_changed` reaches the estimator as the server's sentence, through the
    handler's ordinary error path — it is not mistaken for the stale-document panel's refusal."""
    r = ran["refused"]
    assert r["posted"] == 1
    assert r["err"] and r["err"].startswith("Not sent — this proposal changed"), r


def test_a_draft_moved_in_another_tab_is_not_sent(ran):
    """The Files page opened on a current document; then another tab of this browser picked a new
    texture on the Estimate step and left without Continue. The document Send would freeze no
    longer matches the draft's key (TW.composeKey), and the price/base/options drift gate cannot
    see a texture — so nothing is posted, nothing is written, and the estimator is told to reload,
    which takes the page back through its door (test_files_door.py).

    Mutation: drop the key check and the one-copy check from the Send handler (either alone
    still refuses: this copy moved, so it is no longer the server's) — one publish goes out with
    the old texture."""
    m = ran["movedInAnotherTab"]
    assert m["posted"] == 0, m
    assert m["puts"] == 0, m
    assert m["err"] and "Reload this page" in m["err"], m


def test_a_draft_moved_on_another_machine_is_not_sent(ran):
    """Review finding 3. The Files page opened on a current document and it was downloaded; then RJ,
    on his own machine, picked Knockdown on the Estimate step and left without Continue. THIS page's
    copy still holds by its own key and the render-id gate sees the same payload, but the SERVER's
    copy, the one the publish freezes, no longer matches its document. Checking only this browser's
    copy sent the old texture; now nothing is posted and nothing is written.

    Mutation: drop the server's key check and the one-copy check in the Send handler (either
    alone still refuses) — one publish goes out."""
    m = ran["movedOnAnotherMachine"]
    assert m["posted"] == 0, m
    assert m["puts"] == 0, m
    assert m["err"] and "Reload this page" in m["err"], m


def test_a_send_that_cannot_read_the_saved_copy_is_not_sent(ran):
    """Nothing can be checked, so nothing goes: the saved copy is what the publish freezes.

    Mutation: treat an unreadable server copy as current — one publish goes out."""
    m = ran["serverUnreadable"]
    assert m["posted"] == 0, m
    assert m["err"] and m["err"].startswith("Couldn't check the saved proposal"), m
