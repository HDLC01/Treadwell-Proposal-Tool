"""A Files page holding an older copy of the draft than the server's must not write it back.

Review of fix 3, 2026-09-25. initDraftSync does not re-read a localStorage blob already stamped for
this draft, so a Files page reopened on a machine that held the project before, or left open while
a colleague revised it elsewhere, holds an OLDER copy than the server's. Pressing Download recorded
the build with TW.setState, which PUTs the page's whole blob: RJ's newer revision was written away,
and the Send that followed froze Kyle's stale payload, a document nobody had downloaded.

Now the press writes nothing to the server (the server records has_files itself, see
test_send_equals_download.py), and Send carries the render_id of the file that was downloaded, so
the server can refuse to freeze anything else.

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


def test_send_hands_back_the_document_that_was_downloaded(ran):
    """The real Send handler posts the render_id of the file the estimator downloaded, so the
    server can refuse to freeze a different one.

    Mutation: drop `document_render_id` from the publish body, or stop downloadAs recording it."""
    d = ran["download"]
    s = ran["sendAfterDownload"]
    assert s["posted"] == 1, s
    assert s["renderId"] == d["checked"] == "K:Smooth Finish", s


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

