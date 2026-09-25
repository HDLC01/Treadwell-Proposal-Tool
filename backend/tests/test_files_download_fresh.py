"""The Files page's Download buttons build their file NOW, from the saved draft.

Hanz, 2026-09-25: "Sending out the proposal should be the same PDF from the download button in the
last page" and "Clicking to Done should regenerate and make the proposal correctly."

The page used to fetch the token kept in `generate_result` — files built from whatever payload the
last generate was handed, alive in server memory for an hour — and, on a 404, regenerate from the
module-top snapshot of the payload. Send pinned the SAVED payload. So an edit that moved no price
(texture, tax mode, a note) left Download and Send on two different documents. Every press now
flushes the page's pending save and asks /api/draft/{id}/documents, the server route that renders
the saved payload through the function Send uses (see test_send_equals_download.py for that half).

EXECUTED, NOT READ: the harness runs the shipped function bodies (see its header).
"""
import json
import pathlib
import shutil
import subprocess

import pytest

HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "files-download-harness.js"


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS)], capture_output=True, text=True,
                          encoding="utf-8", timeout=120)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_a_download_never_fetches_the_kept_token(ran):
    """THE DEFECT. State holds a build from before an edit (OLD) and a newer saved payload. The
    press must fetch the file minted for the saved payload (NEW) and never OLD.

    Mutation: fetch `TW.getState().generate_result[urlKey]` without calling freshDocuments — the
    old code path. OLD is fetched."""
    s = ran["stale"]
    assert s["fetched"] == ["https://tool/api/file/NEW/pdf"], s["fetched"]
    assert s["clicked"] == ["Niagara_proposal.pdf"]
    assert s["html"].endswith(" Downloaded"), s["html"]


def test_the_file_is_built_by_the_route_send_uses_after_the_save_lands(ran):
    """Flush FIRST — the server renders its own copy of the draft, which is what Send pins — then
    the saved-draft route, never a body the page built itself.

    Mutations: drop the flush (the order changes); post the page's payload to /api/generate (the
    path changes)."""
    s = ran["stale"]
    assert s["log"][:2] == ["flush", "post /api/draft/d1/documents"], s["log"]
    assert s["posted"] == ["/api/draft/d1/documents"]
    assert s["body"] == {}, "the page sent its own copy of the payload: %r" % (s["body"],)


def test_the_new_build_is_remembered_locally_and_never_written_to_the_draft(ran):
    """The press remembers its build in THIS browser (setLocalState) and never calls setState,
    which PUTs the page's whole blob — a blob that can be older than the server's copy (the proof
    against the real shared.js is in test_files_stale_page.py). The server records has_files itself.

    Mutation: record the build with TW.setState again — "setState" appears in the log."""
    s = ran["stale"]
    assert "setState" not in s["log"], s["log"]
    assert "setLocalState" in s["log"], s["log"]
    assert s["kept"]["pdf_download_url"] == "/api/file/NEW/pdf"
    assert s["painted"] == 1


def test_the_card_shows_the_total_the_server_rendered(ran):
    """The server rendered ITS copy of the payload, which is not always the page's. The card's
    figure is the one that copy printed ($44,000.00), not the page's own ($41,250.00).

    Mutation: stamp builtAt(the page's payload) — the page's figure comes back."""
    assert ran["stale"]["stamp"] == "$44,000.00"
    assert ran["generate"]["stamp"] == "$44,000.00"


def test_the_downloaded_file_is_the_document_send_will_be_checked_against(ran):
    """downloadAs keeps the render_id of the file it fetched, for Send to hand back.

    Mutation: drop the `checkedDocument.renderId =` line — it stays empty."""
    assert ran["stale"]["checked"] == "K-NEW"


def test_a_download_that_failed_checked_nothing(ran):
    """Recorded only after the file came back: a 404 is not a document anybody read.

    Mutation: record the id before the `resp.ok` check — the 404 scenario records it."""
    assert ran["notFound"]["checked"] == ""


def test_a_draft_with_no_document_builds_nothing_and_writes_nothing(ran):
    """No saved payload (or one with no values): the press flushes, then refuses — nothing is
    posted, nothing fetched, nothing written, and the button says it failed. The page's door sends
    such a draft through the Proposal step before the page ever shows a button
    (test_files_door.py), so this is the refusal behind it, not a route anybody walks.

    Mutation: restore the rebuild from the draft's own fields (post `st` to /api/generate) — a
    POST appears and a file is fetched."""
    for name, n in ran["noPayload"].items():
        assert n["log"] == ["flush"], (name, n["log"])
        assert n["posted"] == [] and n["fetched"] == [] and n["clicked"] == [], (name, n)
        assert n["button"] == "Failed — try again", (name, n["button"])


def test_a_save_that_cannot_land_builds_nothing(ran):
    """The server would render the copy it has, which is not what is on screen."""
    f = ran["flushFails"]
    assert f["log"] == ["flush"], f["log"]
    assert f["fetched"] == [] and f["button"] == "Failed — try again"


def test_a_404_is_reported_and_nothing_is_rebuilt_from_elsewhere(ran):
    """The old self-heal rebuilt from the module-top snapshot, a second payload. Gone.

    Mutation: restore the self-heal — a second POST appears."""
    n = ran["notFound"]
    assert n["posted"] == ["/api/draft/d1/documents"], n["posted"]
    assert len(n["fetched"]) == 1 and n["button"] == "Failed — try again"


def test_the_generate_button_renders_the_saved_payload(ran):
    """doGenerate posted the MODULE-TOP snapshot of the payload to /api/generate — whatever the
    page loaded with. It goes through the same route as the downloads now.

    Mutation: post `state.proposal_payload` to /api/generate again."""
    g = ran["generate"]
    assert g["posted"] == ["/api/draft/d1/documents"], g["posted"]
    assert g["log"][0] == "flush"
    assert g["shown"] and g["shown"][0]["pdf_download_url"] == "/api/file/NEW/pdf"
    assert g["pre"] == "none"
    assert "setState" not in g["log"], g["log"]


def test_no_draft_id_falls_back_to_the_pages_own_payload(ran):
    """Nothing to ask the server about; the page's payload itself is what gets built."""
    f = ran["noDraftId"]
    assert f["posted"] == ["/api/generate"] and f["sentSaved"] is True
