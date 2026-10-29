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
    the server's copy is read (the question is asked of it, below), then the saved-draft route,
    never a body the page built itself: only when the copy it read was stored.

    Mutations: drop the flush (the order changes); post the page's payload to /api/generate (the
    path changes)."""
    s = ran["stale"]
    assert s["log"][:4] == ["flush", "read", "flush", "post /api/draft/d1/documents"], s["log"]
    assert s["posted"] == ["/api/draft/d1/documents"]
    assert s["body"] == {"draft_version": "v1"}, "the page sent its own copy of the payload: %r" % (s["body"],)


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


def test_a_download_repaints_the_list_of_every_proposal(ran):
    """Step 5's list of every proposal of the project (refreshFilesProposals, test_files_proposals.py)
    repaints where the single figure does: after the fresh build a download makes.

    Mutation: drop refreshFilesProposals() from downloadAs -- `listed` stays 0."""
    assert ran["stale"]["listed"] == 1


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
        assert n["log"] == ["flush", "read", "flush"], (name, n["log"])
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


# ── a price line with a figure of his own ────────────────────────────────────────────────────────
# Asked as the Treadwell pop-up (Hanz, 2026-09-28): the harness reads title | message | button.
_ASK = ("Download with a different price? | This line says $15,000 but the estimate says $9,860. "
        "This line says $9,999, typed by hand. | Download anyway")


@pytest.mark.parametrize("case", ["pdfCancel", "docxCancel"])
def test_download_asks_about_a_figure_of_his_own_and_cancel_does_nothing(ran, case):
    """Hanz, 2026-09-26: warn on all three. The document lists two price lines printing a figure of
    the estimator's own; the PDF and .docx buttons ask Send's question in their own verb BEFORE
    anything is built, and Cancel builds, fetches and saves nothing, the button as it was. What
    runs before the question is what the question needs: this page's pending save (it would go by
    itself within seconds) and a read of the server's copy, the one that would be built.

    Mutation: drop the check from downloadAs (the cancelled press builds and downloads)."""
    c = ran["ownFigure"][case]
    assert c["asked"] == [_ASK], c["asked"]
    assert c["log"] == ["flush", "read", "confirm"], c["log"]
    assert c["clicked"] == [] and c["checked"] == "" and c["bodies"] == [], c
    assert c["button"] == {"text": "Download PDF", "disabled": False}, c["button"]


def test_download_ok_proceeds_exactly_as_a_press_always_has(ran):
    """OK: the question first, then the same flush, build, fetch and save as any press -- the build
    naming the save the question was asked of."""
    c = ran["ownFigure"]["pdfOk"]
    assert c["asked"] == [_ASK]
    assert c["log"] == ["flush", "read", "confirm", "flush", "post /api/draft/d1/documents",
                        "setLocalState", "fetch https://tool/api/file/NEW/pdf"], c["log"]
    assert c["clicked"] == ["x.pdf"] and c["checked"] == "K-NEW"
    assert c["bodies"] == [{"draft_version": "v1"}], c["bodies"]


@pytest.mark.parametrize("case", ["xlsx", "clean"])
def test_no_question_for_the_estimate_sheet_or_a_document_that_follows_the_estimate(ran, case):
    """The estimate sheet prints no price line, and a document whose lines all follow the estimate
    has nothing to ask about: both download straight away, with no prompt at all.

    Mutation: ask on every button (the sheet's press asks); ask whether or not a line warns."""
    c = ran["ownFigure"][case]
    assert c["asked"] == [], c["asked"]
    built = c["log"][c["log"].index("post /api/draft/d1/documents") - 1:][:2]
    assert built == ["flush", "post /api/draft/d1/documents"], c["log"]
    assert len(c["clicked"]) == 1
    # The sheet is not asked, so it names no copy; a clean document was asked of the server's.
    assert c["bodies"] == ([{}] if case == "xlsx" else [{"draft_version": "v1"}]), c["bodies"]


# ── the copy that is built (review of dfcf589) ───────────────────────────────────────────────────
_RJ_ASK = ("Download with a different price? | This line says $15,000 but the estimate says $12,500."
           " | Download anyway")


def test_download_asks_about_the_copy_the_server_builds_not_this_pages(ran):
    """Kyle's Files page is current and clean; RJ, on another machine, typed $15,000 over the base
    amount and pressed Continue, so the SERVER's copy -- the one /documents renders -- lists it.
    Kyle's Download PDF used to ask about his own copy, find nothing, and download RJ's $15,000
    document unasked (Send refused in the same case). It asks about the server's copy now: Cancel
    builds nothing, OK builds naming the save it asked about.

    Mutation: ask confirmOwnFigures of this page's copy (TW.getState()) inside confirmSavedCopy --
    nothing is asked and RJ's document downloads."""
    s = ran["serverCopy"]
    assert s["serverWarns"]["asked"] == [_RJ_ASK], s["serverWarns"]
    assert s["serverWarns"]["log"] == ["flush", "read", "confirm"] and s["serverWarns"]["clicked"] == []
    assert s["serverWarns"]["bodies"] == []
    assert s["serverWarnsOk"]["asked"] == [_RJ_ASK]
    assert s["serverWarnsOk"]["clicked"] == ["x.pdf"]
    assert s["serverWarnsOk"]["bodies"] == [{"draft_version": "v1"}], s["serverWarnsOk"]


def test_a_figure_only_this_pages_copy_still_holds_is_not_asked_about(ran):
    """The counterexample: this page's copy lists a line the server's copy no longer has. The
    document built is the server's, which has nothing to ask about, so nothing is asked. Without
    this, the test above passes for a page that asks about either copy."""
    s = ran["serverCopy"]["onlyLocalWarns"]
    assert s["asked"] == [] and s["clicked"] == ["x.pdf"], s


def test_download_builds_nothing_when_the_servers_copy_cannot_be_read(ran):
    """Nothing can be asked, so nothing is built, and the button says it failed.

    Mutation: treat an unreadable server copy as nothing to ask (build anyway)."""
    s = ran["serverCopy"]["unreadable"]
    assert s["log"] == ["flush", "read"] and s["clicked"] == [], s
    assert s["button"] == "Failed — try again"


def _saved(names):
    """Each button's one saved file name ({button id: name})."""
    assert all(len(v) == 1 for v in names.values()), names
    return {k: v[0] for k, v in names.items()}


def test_one_proposal_downloads_under_the_project_name_as_always(ran):
    """A draft in no scope group keeps exactly the names it had: "<project>_estimate.xlsx" etc.,
    and a long project name is still cut at 60 characters."""
    assert _saved(ran["names"]["single"]) == {
        "dl-xlsx": "Multiple_proposals_estimate.xlsx",
        "dl-docx": "Multiple_proposals_proposal.docx",
        "dl-pdf": "Multiple_proposals_proposal.pdf"}
    long_single = "Kansas_State_University_Biosciences_Research_Facility_Phase_"
    assert len(long_single) == 60
    assert _saved(ran["names"]["longSingle"])["dl-pdf"] == long_single + "_proposal.pdf"


def test_one_of_several_proposals_downloads_under_the_project_and_its_sheet_name(ran):
    """Hanz, 2026-10-29: the proposal's name is its sheet's "in the files" too. A draft in a scope
    group (Create Multiple Proposals, or RJ's scopes) saves "<project>_<scope_group.label>_...",
    every button, so three proposals of one project no longer download under one name.

    Mutation: name the files from state.project_name only (the code before) -- every name here
    loses "_Polish_Room_2"."""
    assert _saved(ran["names"]["group"]) == {
        "dl-xlsx": "Multiple_proposals_Polish_Room_2_estimate.xlsx",
        "dl-docx": "Multiple_proposals_Polish_Room_2_proposal.docx",
        "dl-pdf": "Multiple_proposals_Polish_Room_2_proposal.pdf"}
    assert _saved(ran["names"]["groupNoPdf"]) == {
        "dl-xlsx": "Multiple_proposals_Polish_Room_2_estimate.xlsx",
        "dl-docx": "Multiple_proposals_Polish_Room_2_proposal.docx"}
    assert _saved(ran["names"]["noProject"])["dl-pdf"] == "proposal_Office_proposal.pdf"


def test_a_long_project_name_is_cut_and_the_sheet_name_survives(ran):
    """The project part is the one cut; the proposal's own name is kept whole, through the same
    filename-safe rule (anything but A-Z a-z 0-9 . _ - becomes one _)."""
    pdf = _saved(ran["names"]["longProject"])["dl-pdf"]
    assert pdf.endswith("_Epoxy_Lab_2_North_Wing__proposal.pdf"), pdf
    assert pdf.startswith("Kansas_State_University_"), pdf
    assert len(pdf) - len("_proposal.pdf") <= 80, pdf


def test_a_name_with_no_letter_or_digit_never_takes_the_one_proposal_name(ran):
    """A group whose name leaves no letter or digit (blank, all non-Latin, punctuation) would save
    under the one-proposal name, the collision this exists to remove: the draft's id stands in.

    Mutation: fall back to the project's name alone -- every name here loses "_1a2b3c4d"."""
    assert _saved(ran["names"]["blankLabel"]) == {
        "dl-xlsx": "Multiple_proposals_1a2b3c4d_estimate.xlsx",
        "dl-docx": "Multiple_proposals_1a2b3c4d_proposal.docx",
        "dl-pdf": "Multiple_proposals_1a2b3c4d_proposal.pdf"}
    assert _saved(ran["names"]["cjk"])["dl-pdf"] == "Proj_1a2b3c4d_proposal.pdf"
    assert _saved(ran["names"]["punct"])["dl-pdf"] == "Proj_1a2b3c4d_proposal.pdf"
    # A digit survives, so it is the name, and it is not the first one's.
    assert _saved(ran["names"]["cjk2"])["dl-pdf"] == "Proj__2_proposal.pdf"


def test_the_file_takes_the_name_the_header_shows_once_the_list_is_read(ran):
    """Step 5's header names the proposal by the list's display_label; the stored label can trail it
    until the estimate is saved again (sync_proposal_labels). Once the list is read the file says
    what the header says; a list that does not hold this draft leaves the stored label.

    Mutation: name from scope_group.label only -- "listRead" saves "Base_Bid_2"."""
    assert _saved(ran["names"]["listRead"]) == {
        "dl-xlsx": "Multiple_proposals_Room_2_estimate.xlsx",
        "dl-docx": "Multiple_proposals_Room_2_proposal.docx",
        "dl-pdf": "Multiple_proposals_Room_2_proposal.pdf"}
    assert _saved(ran["names"]["listOfOthers"])["dl-pdf"] == "Multiple_proposals_Base_Bid_2_proposal.pdf"


def test_a_scope_name_of_up_to_80_characters_survives_whole(ran):
    """A scope's name can be 80 characters (drafts.SCOPE_LABEL_MAX). It is never cut, so two that
    part after the 60th character still save apart; the project keeps its 20, so the stem is at
    most 20 + 1 + 80 characters.

    Mutation: cut the name at 60 (the code before) -- both save under one name."""
    from drafts import SCOPE_LABEL_MAX
    labels = ran["scopeLabels"]
    assert all(60 < len(x) <= SCOPE_LABEL_MAX for x in labels) and labels[0][:60] == labels[1][:60]
    a = _saved(ran["names"]["scopeA"])["dl-pdf"]
    b = _saved(ran["names"]["scopeB"])["dl-pdf"]
    assert a != b
    for name, label in zip((a, b), labels):
        stem = name[:-len("_proposal.pdf")]
        assert stem == "Kansas_State_Univers_" + label.replace(" ", "_"), name
        assert len(stem) <= 20 + 1 + SCOPE_LABEL_MAX


def test_sent_versions_carry_the_proposals_name_too(ran):
    """Sent versions (downloadRevision) on the same page: one of several proposals saves
    "<project>_<its name>_rev<N>_...", so every proposal's rev1 no longer saves under one name; one
    proposal keeps exactly the names it had.

    Mutation: name a revision from the project only (the code before) -- "group" and "listRead"
    lose their proposal's name."""
    r = ran["revisions"]
    assert r["single"]["pdf"] == ["Multiple_proposals_rev1_proposal.pdf"]
    assert r["single"]["xlsx"] == ["Multiple_proposals_rev1_estimate.xlsx"]
    assert r["single"]["docx"] == ["Multiple_proposals_rev3_proposal.docx"]
    assert r["group"]["pdf"] == ["Multiple_proposals_Polish_Room_2_rev1_proposal.pdf"]
    assert r["group"]["xlsx"] == ["Multiple_proposals_Polish_Room_2_rev1_estimate.xlsx"]
    assert r["group"]["docx"] == ["Multiple_proposals_Polish_Room_2_rev3_proposal.docx"]
    assert r["listRead"]["pdf"] == ["Multiple_proposals_Room_2_rev1_proposal.pdf"]
