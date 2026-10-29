"""3 · GENERATE FILES (Hanz, 2026-10-28; reworked 2026-10-29).

"The top navigation bar, before we go to proposal, we should add another step that says generate
files, so that every time we would have a backup or a safety net that it would generate the files
every time we change something in the estimate." The wizard is now

    1 Intake -> 2 Estimate -> 3 Generate Files -> 4 Proposal -> 5 Files

and every arrival at step 3 builds the .xlsx, .docx and PDF of every live proposal of the project
(frontend/js/generate.js), through the Files step's own route (/api/draft/{id}/documents).

"If we have multiple base bids why does it only generate one file and why does it go back and forth
from proposal to generate files" / "It should always generate the 3 proposals already" / "if we are
on the generate files it should stay on that page until I click continue" (2026-10-29). So step 3
never leaves: a stale or out-of-step child is caught up by the project's Refresh first, and a
document older than its draft, or one nobody wrote yet, is composed by the Proposal step's own door
in a hidden same-origin iframe that shared.js keeps off the tab's one localStorage blob (FRAME).

EXECUTED, NOT READ: js/generate-step-harness.js runs the real generate.js over the real shared.js,
and opens each frame as the real Proposal page in frame mode (files-door-harness.js's world: the
real continueToDone / composeForFiles). Each mutation test breaks ONE line in a scratch copy of one
file and requires the harness to go red; the mutation is asserted to have applied. The pills are
read off every wizard page's markup.
"""
import copy
import json
import pathlib
import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

import main
from test_scope_send_all import GC_HELD, World, _draft, _press, _three

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "generate-step-harness.js"
FRONTEND = TESTS.parents[1] / "frontend"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
client = TestClient(main.app)

DEFAULT_WORDING = "Built from the default wording; review it on its Proposal tab before sending."


def _run(front=None):
    args = ["node", str(HARNESS)] + ([str(front)] if front else [])
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=240)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    return _run()


def _mutant(tmp_path, rel, old, new):
    """A scratch frontend holding ONE file of the real one with `old` replaced by `new` once (line
    endings normalised first, so the replacement cannot silently miss on a CRLF checkout)."""
    src = (FRONTEND / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert src.count(old) == 1, "the mutation's target moved: %r" % old[:70]
    out = tmp_path / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(src.replace(old, new).encode("utf-8"))
    assert out.read_bytes().decode("utf-8") != src
    return tmp_path


def _row(rows, rid):
    return next(r for r in rows if r["id"] == rid)


# ── staging's project: three base bids, three proposals, one page ────────────────────────────
@needs_node
def test_staging_shape_builds_all_three_without_leaving_the_page(ran):
    """THE CASE (staging, 2026-10-29). Base Bid 1 Epoxy's document is older than the estimate, the
    Polish proposal's copy of the estimate is stale, and Room 2 was never opened. Before: 1 of 3
    built, the tab flipping between Proposal and Generate Files, and "press Refresh on its Proposal
    step" twice. Now all three are built, each at its own sheet's price, and the address bar never
    moved."""
    s = ran["staging"]
    assert [(r["id"], r["name"], r["status"], r["total"]) for r in s["rows"]] == [
        ("d1", "Epoxy", "built", "$12,500"), ("c2", "Polish", "built", "$8,000"),
        ("c3", "Room 2", "built", "$6,000")], s["rows"]
    assert s["nav"] == [] and s["urls"] == ["/generate.html?d=d1"] and s["url"] == "/generate.html?d=d1"
    assert s["frames"]["nav"] == [], "a frame navigated"
    assert s["frames"]["errors"] == []
    assert s["renders"] == [["d1", "$12,500"], ["c2", "$8,000"], ["c3", "$6,000"]]
    assert len(s["links"]) == 9
    assert s["note"] == "All 3 proposals are built."
    assert s["next"] == "/proposal-review.html?d=d1"


@needs_node
def test_one_steady_progress_line(ran):
    assert ran["staging"]["notes"] == [
        "Generating files…",
        "Generating files: copying the estimate into 1 proposal…",
        "Generating files: Epoxy (1 of 3)…",
        "Generating files: Polish (2 of 3)…",
        "Generating files: Room 2 (3 of 3)…",
        "All 3 proposals are built."]


@needs_node
def test_refresh_runs_once_first_with_the_saved_copys_version(ran):
    """The Proposal step's "Estimate changed" banner's own call, once, with the version of the saved
    copy it read (the server refuses a copy stored again since)."""
    s = ran["staging"]
    assert s["refreshCalls"] == 1
    assert s["refreshes"] == [{"id": "d1", "versioned": True}]


@needs_node
def test_two_hidden_frames_at_a_time_each_torn_down(ran):
    """"Why not generate them in parallel also" (Hanz, 2026-10-29): the Proposal pages compose two at
    a time (FRAME_LIMIT), never three (each is a 10k-line page), and none is left on the page."""
    f = ran["staging"]["frames"]
    assert f["opened"] == ["d1", "c2", "c3"]
    assert f["maxLive"] == 2 and f["live"] == 0, "not two at once, more than two, or one left on the page"
    assert ["c2", "d1"] in f["together"], "Epoxy and Polish were never composed at the same time"
    for rid in ("d1", "c2", "c3"):
        assert [p for p in f["phases"] if p.startswith(rid + ":")] == [rid + ":started", rid + ":saved"]
    assert f["targets"] == ["https://tool"], "a frame posted to an origin other than its own"
    assert ran["staging"]["listening"] == 0, "a message listener was left behind"
    for a in ran["staging"]["frameAttrs"]:
        assert a["className"] == "gen-frame" and a["inert"] == "" and a["hidden"] == "true" and a["tab"] == "-1"
        assert re.fullmatch(r"/proposal-review\.html\?d=(d1|c2|c3)&compose=frame&frame=TOK", a["src"]), a["src"]


@needs_node
def test_two_frames_at_once_each_save_only_their_own_draft(ran):
    """Epoxy's and Polish's frames ran together. Each saved its own proposal's document, at its own
    sheet's price, and nothing else: no child's document reached the project's own draft, and the
    tab's one localStorage slot is still the project's (each frame has its own window, token, seed
    and in-memory storage: shared.js FRAME)."""
    s = ran["staging"]
    assert s["framePuts"] == [["c2", "Polish", "$8,000"], ["c3", "Room 2", "$6,000"]], s["framePuts"]
    assert s["d1Puts"] and all(p == [None, None, "$12,500"] for p in s["d1Puts"]), s["d1Puts"]
    assert s["slotOwner"] == "d1" and s["slotTotal"] == "$12,500"


@needs_node
def test_the_never_opened_one_is_a_marked_backup(ran):
    """Room 2 nobody opened: its document is the template's default wording, built as a backup and
    said so. The door marks it `proposal_auto_built` (Send all still holds its placeholders), and its
    build is not refused by the hold the others ask for. The two a person composed stay unmarked."""
    s = ran["staging"]
    assert _row(s["rows"], "c3")["message"] == DEFAULT_WORDING
    assert _row(s["rows"], "d1")["message"] == "" and _row(s["rows"], "c2")["message"] == ""
    assert s["c3"]["mark"] is True
    assert s["d1Mark"] is None and s["c2Mark"] is None
    assert s["holds"] == {"d1": True, "c2": True, "c3": False}


@needs_node
def test_send_all_still_refuses_the_backup_while_it_prints_placeholders(ran, fake_supabase,
                                                                       monkeypatch):
    """The document the frame composed for Room 2 (a GC scope, its words blank), exactly as the
    harness saved it, put on Send all's project: the press holds it with Kyle's placeholders."""
    c3 = ran["staging"]["c3"]
    assert c3["mark"] is True and c3["audience"] == "GC"
    rows = _three()
    rows[1] = _draft("s2", "Room 2", "2026-10-02", files=False, audience="GC",
                     proposal_auto_built=c3["mark"])
    rows[1]["data"]["proposal_payload"] = copy.deepcopy(c3["payload"])
    w = World(fake_supabase, monkeypatch, rows)
    r = _press({"message": "All three."})
    assert r.status_code == 409, r.text
    j = r.json()
    assert [(b["id"], b["code"]) for b in j["blocked"]] == [("s2", "placeholders")]
    assert j["error"] == GC_HELD
    assert w.publishes == [] and w.sends == []


@needs_node
def test_this_browsers_copy_takes_the_document_its_frame_composed(ran):
    """The open proposal's document was composed in a frame and saved; this browser's copy was the
    saved copy until then, so it takes the new one, and no page here holds the one from before."""
    s = ran["staging"]
    assert s["slotOwner"] == "d1" and s["slotTotal"] == "$12,500" and s["slotIsServer"]


# ── one draft ───────────────────────────────────────────────────────────────────────────────
@needs_node
def test_a_changed_estimate_is_composed_in_a_frame_then_built_without_leaving(ran):
    """The last Continue built $10,000 / Smooth. The Estimate step then re-priced to $12,500 and
    picked Orange Peel. The document is composed again by the Proposal step's door, in a frame, and
    the files are built from THAT, at the new price; the tab never left step 3."""
    o = ran["oneDraft"]
    assert o["builtBefore"] == "$10,000"
    assert o["nav"] == [] and o["url"] == "/generate.html?d=d1"
    assert o["frames"]["opened"] == ["d1"] and o["frames"]["nav"] == []
    assert o["rendered"] == [{"id": "d1", "texture": "Orange Peel", "total": "$12,500"}], o["rendered"]
    assert o["rows"] == [{"id": "d1", "name": "Door Test", "sheet": "", "status": "built",
                          "total": "$12,500", "message": "", "current": True}]
    assert o["links"] == ["0:xlsx_download_url", "0:docx_download_url", "0:pdf_download_url"]
    assert o["note"] == "The files are built."
    assert o["mark"] is None, "a document a person composed was marked as built by nobody"
    assert o["slotTotal"] == "$12,500"
    assert o["chainLeft"] is None, "a walk record was written"
    assert o["next"] == "/proposal-review.html?d=d1"


@needs_node
def test_an_unchanged_arrival_is_up_to_date_and_builds_nothing(ran):
    """Nothing changed since the last visit built it: no frame, no build, no PDF, and the row says
    so with its price."""
    a = ran["again"]
    assert a["nav"] == [] and a["frames"] == 0
    assert a["posted"] == [] and a["newRenders"] == 0
    assert a["rows"][0]["status"] == "uptodate" and a["rows"][0]["total"] == "$12,500"
    assert a["pdfs"] == 1, "the PDF was made again"


# ── only what changed is rebuilt (Hanz, 2026-10-29) ─────────────────────────────────────────
@needs_node
def test_only_the_edited_proposal_is_rebuilt(ran):
    """"If we only edited one proposal then it should only regenerate that proposal." Three built on
    the first visit; RJ then rewrote Polish's scope. The next visit composes and builds Polish only;
    Epoxy and Room 2 are "Up to date" with their prices and their three links, each asked of the
    server with the version of the copy judged."""
    o = ran["onlyChanged"]
    assert [r["status"] for r in o["first"]["rows"]] == ["built"] * 3 and o["first"]["posted"] == ["d1", "c2", "c3"]
    assert [(r["id"], r["status"], r["total"]) for r in o["rows"]] == [
        ("d1", "uptodate", "$10,000"), ("c2", "built", "$8,000"), ("c3", "uptodate", "$6,000.00")], o["rows"]
    assert o["statusText"] == ["Up to date · $10,000", "Built · $8,000", "Up to date · $6,000.00"]
    assert o["posted"] == ["c2"] and o["frames"] == ["c2"] and o["rendered"] == ["c2"] and o["pdfs"] == ["c2"]
    assert o["c2Scope"] == "RJ's new scope for the polish"
    assert sorted(o["checked"]) == [["c3", True, True], ["d1", True, True]]
    assert len(o["links"]) == 9
    assert o["note"] == "1 rebuilt, 2 up to date."
    assert o["notes"][-1] == "1 rebuilt, 2 up to date."
    assert o["nav"] == [] and o["rebuildShown"] and not o["rebuildDisabled"]


@needs_node
def test_up_to_date_links_download_and_heal_after_a_restart(ran):
    """The links of an "Up to date" row download its files. After a restart (every token expired) a
    link builds the files of the saved document again (the render is still cached: no new render)
    and downloads, as the Files step does, instead of dead-ending."""
    e = ran["expired"]
    assert e["xlsx"] == {"name": "Epoxy_estimate.xlsx", "bytes": "X d1"}
    assert e["pdf"] == {"name": "Room_2_proposal.pdf", "bytes": "%PDF c3"}
    assert e["healed"] == {"name": "Epoxy_proposal.pdf", "bytes": "%PDF d1"}
    assert e["posted"] == [["d1", True, False]] and e["rendered"] == 0


@needs_node
def test_rebuild_all_builds_every_one_again(ran):
    """The safety net: "Rebuild all" builds all three again, past the cached renders, and asks
    nothing about what is up to date."""
    r = ran["rebuild"]
    assert [(x["id"], x["status"]) for x in r["rows"]] == [("d1", "built"), ("c2", "built"), ("c3", "built")]
    assert r["posted"] == [["d1", True], ["c2", True], ["c3", True]]
    assert r["rendered"] == [["d1", True], ["c2", True], ["c3", True]]
    assert r["pdfs"] == 3 and r["checks"] == 0 and r["frames"] == 0
    assert r["note"] == "All 3 proposals are built." and r["nav"] == []
    assert r["rebuildShown"] and not r["rebuildDisabled"] and len(r["links"]) == 9


@needs_node
def test_an_estimate_only_change_is_rebuilt(ran):
    """The Polish sheet re-priced on the estimate, no word of either proposal touched, and the server
    still holding each one's OLD document rendered with its PDF. Neither is "up to date": each
    document no longer holds for its draft, so each is composed again and built, Polish at $9,500."""
    e = ran["estimateOnly"]
    assert e["first"] == [["d1", "built", "$10,000"], ["c2", "built", "$8,000.00"]]
    assert e["rows"] == [["d1", "built", "$10,000"], ["c2", "built", "$9,500"]], e["rows"]
    assert e["rendered"] == [["d1", "$10,000"], ["c2", "$9,500"]]
    assert e["frames"] == ["d1", "c2"] and e["refreshCalls"] == 1
    assert e["note"] == "All 2 proposals are built."


@needs_node
def test_a_late_change_this_browser_holds_is_saved_first_then_built(ran):
    """"ahead": Kyle's note never reached the server and nobody has saved since. Saving it loses
    nothing of anyone's (the old door saved it too), so it is saved, and the document carries it."""
    a = ran["ahead"]
    assert a["nav"] == []
    assert a["serverNote"] == "Kyle's note, saved late"
    assert a["docNote"] == "Kyle's note, saved late"
    assert a["rows"][0]["status"] == "built"
    assert a["localNote"] == "Kyle's note, saved late"


# ── the frame and the tab's storage ──────────────────────────────────────────────────────────
@needs_node
@pytest.mark.parametrize("which", ["thisProject", "otherProject"])
def test_a_frame_leaves_the_tabs_storage_byte_identical(ran, which):
    """The Proposal page in frame mode composed and saved Room 2. localStorage (the one draft blob
    every tab shares, the synced record, the draft id, a sidebar key) and sessionStorage are byte for
    byte as they were, whether they held this project or another tab's."""
    i = ran["isolated_" + which]
    assert i["lsSame"], "the frame wrote the tab's localStorage"
    assert i["ssSame"], "the frame wrote the tab's sessionStorage"
    assert i["phases"] == ["started", "saved"] and set(i["targets"]) == {"https://tool"}
    assert i["nav"] == []
    assert i["saved"] and i["mark"] is True
    assert i["putsTo"] == ["c3"], "the frame saved something other than its own proposal"
    assert i["d1Puts"] == 1, "the frame saved the project open in the tab"
    assert i["seedTaken"] == 1


@needs_node
def test_a_frame_cannot_save_over_a_newer_server_copy(ran):
    """RJ saves Polish elsewhere right after its frame read it. The frame's save asks the server
    again, finds RJ's copy, and writes nothing; its row says so and the page stays."""
    n = ran["newer"]
    assert n["putsTo"] == [], "the frame saved over RJ's copy"
    assert n["c2Scope"] == "RJ's scope, saved elsewhere" and n["c2Doc"] == "$8,000.00"
    assert n["frames"]["phases"] == ["c2:started", "c2:stopped"]
    c2 = _row(n["rows"], "c2")
    assert c2["status"] == "failed"
    assert c2["message"].startswith("It was saved again somewhere else while it was being rebuilt")
    assert n["posted"] == ["d1"], "files were built from a document that was not composed"
    assert n["nav"] == [] and n["url"] == "/generate.html?d=d1"


@needs_node
def test_a_stopped_frame_says_why_and_the_page_stays(ran):
    s = ran["stopped"]
    c2 = _row(s["rows"], "c2")
    assert c2["status"] == "failed" and c2["message"] == "Its proposal template did not load."
    assert s["nav"] == [] and s["url"] == "/generate.html?d=d1" and s["frames"]["nav"] == []
    assert s["putsTo"] == []
    assert s["note"].startswith("1 of 2 built.") and "You can still continue" in s["note"]
    assert s["next"] == "/proposal-review.html?d=d1" and s["nextDisabled"] is False


@needs_node
def test_a_message_from_another_origin_is_ignored(ran):
    """A page of another origin posted "saved" with Polish's token, as the frame's own window, before
    the frame stopped. Taken, it would have built Polish's old document as if it were new."""
    s = ran["stopped"]
    assert _row(s["rows"], "c2")["status"] == "failed"
    assert s["posted"] == ["d1"]


# ── what is not refreshed or built ───────────────────────────────────────────────────────────
@needs_node
def test_no_auto_refresh_from_a_kept_copy(ran):
    """Kyle's tab holds an edit whose save never landed, and the saved copy has moved since ("kept").
    Refresh is not run (it can rewrite this project's own saved copy); the stale Polish says so; a
    sibling whose document holds is built, one whose document is old is composed in its frame; and
    Kyle's copy is exactly as it was."""
    k = ran["kept"]
    assert k["refreshes"] == 0 and k["refreshCalls"] == 0
    assert k["nav"] == []
    rows = k["rows"]
    assert _row(rows, "d1")["status"] == "failed"
    assert _row(rows, "d1")["message"].startswith("This browser's copy of the project doesn't match")
    assert _row(rows, "c2")["status"] == "skipped"
    assert _row(rows, "c2")["message"] == (
        "The estimate changed after this proposal was copied from it. Refresh was not run here: "
        "first choose which copy of the proposal open here to keep, on its Files step. Then come back.")
    assert _row(rows, "c4")["status"] == "built" and _row(rows, "c5")["status"] == "built"
    assert k["posted"] == ["c4", "c5"] and k["frames"]["opened"] == ["c5"]
    assert k["localNote"] == "Kyle's note, never saved" and k["slotSame"]


@needs_node
def test_a_sent_child_a_lost_sibling_and_failed_builds_say_why(ran):
    h = ran["held"]
    rows = h["rows"]
    assert h["refreshes"] == 1 and h["nav"] == []
    assert _row(rows, "d1")["status"] == "built"
    assert _row(rows, "c3")["status"] == "skipped"
    assert _row(rows, "c3")["message"] == "Seal: the customer already has this proposal, so it was not moved."
    assert _row(rows, "c5")["message"] == "It is closed as lost on the board."
    assert _row(rows, "c2")["status"] == "failed"
    assert _row(rows, "c2")["message"] == "Could not build the proposal document."
    assert _row(rows, "c4")["status"] == "failed"
    assert _row(rows, "c4")["message"] == ("The estimate and proposal were built, but the PDF could "
                                           "not be made: Failed to render the PDF. Please try again.")
    assert h["posted"] == ["d1", "c2", "c4"]
    assert h["links"] == ["0:xlsx_download_url", "0:docx_download_url", "0:pdf_download_url"]
    assert h["note"].startswith("1 of 5 built.") and "You can still continue" in h["note"]
    assert h["next"] == "/proposal-review.html?d=d1" and h["nextDisabled"] is False


@needs_node
def test_a_refused_refresh_says_the_servers_sentence(ran):
    r = ran["refused"]
    assert r["nav"] == [] and r["posted"] == ["d1"]
    assert _row(r["rows"], "c2")["message"] == (
        "The estimate changed after this proposal was copied from it. Refresh did not go through: "
        "Nothing changed. This project was saved again after this page read it.")


@needs_node
def test_a_childs_step_three_builds_the_same_list(ran):
    """Opened on a proposal child, step 3 builds the project's list from its parent's view; Back and
    the Intake and Estimate pills go to the PARENT's, Proposal and Files stay the child's own."""
    c = ran["fromChild"]
    assert c["nav"] == [] and c["url"] == "/generate.html?d=c2" and c["slotOwner"] == "c2"
    assert [(r["id"], r["status"], r["current"]) for r in c["rows"]] == [
        ("d1", "built", False), ("c2", "built", True), ("c3", "built", False)]
    assert _row(c["rows"], "c3")["message"] == DEFAULT_WORDING
    assert c["back"] == "/estimate-review.html?d=d1"
    assert c["pills"] == {"intake": "/?edit=1&d=d1", "estimate": "/estimate-review.html?d=d1",
                          "proposal": "/proposal-review.html?d=c2", "files": "/done.html?d=c2"}
    assert c["next"] == "/proposal-review.html?d=c2"


@needs_node
def test_a_walk_record_of_the_old_generate_kind_is_nobodys(ran):
    """A tab that was on the old walk as this deploys: a Files page never takes it (it would press
    Send), and a door never continues it."""
    assert ran["oldKind"] == {"took": None, "progress": None, "next": None}


@needs_node
def test_back_and_the_pills_follow_the_draft(ran):
    v1, v2 = ran["pillsV1"], ran["pillsV2"]
    assert v1 == {"pills": {"intake": "/?edit=1&d=d1", "estimate": "/estimate-review.html?d=d1",
                            "proposal": "/proposal-review.html?d=d1", "files": "/done.html?d=d1"},
                  "back": "/estimate-review.html?d=d1", "next": "/proposal-review.html?d=d1"}
    assert v2["pills"]["intake"] == "/polish-intake.html?d=d1"
    assert v2["pills"]["estimate"] == "/polish-estimate.html?d=d1"
    assert v2["back"] == "/polish-estimate.html?d=d1"


@needs_node
def test_no_project_builds_nothing(ran):
    assert ran["empty"] == {"emptyShown": True, "posted": 0, "nav": []}


# ── mutations: each scenario above goes red without the line it relies on ───────────────────
G = "js/generate.js"
P = "js/proposal-review.js"
MUTATIONS = [
    ("stays-on-page", G, "      var out = await composeInFrame(r, r.data);",
     '      window.location.assign("/proposal-review.html?d=" + r.id + "&compose=files");'
     ' var out = { ok: false, reason: "left" };',
     lambda o: o["staging"]["nav"] != []),
    ("frame-continue-stays", P, '      TW.frameReport({ phase: "saved" });\n      return true;\n', "",
     lambda o: o["staging"]["frames"]["nav"] != []
     and _row(o["staging"]["rows"], "c3")["status"] != "built"),
    ("frame-isolation", "shared.js",
     '  const localStorage = FRAME ? FRAME.local : hostStore("localStorage");',
     '  const localStorage = hostStore("localStorage");',
     lambda o: not o["isolated_otherProject"]["lsSame"]),
    ("frame-guard", P, '        ? "ok" : "not-the-saved-copy";', '        ? "ok" : "ok";',
     lambda o: o["newer"]["putsTo"] != []),
    ("origin-check", G,
     "        if (!e || e.origin !== origin() || e.source !== frame.contentWindow) return;",
     "        if (!e || e.source !== frame.contentWindow) return;",
     lambda o: _row(o["stopped"]["rows"], "c2")["status"] == "built"),
    ("refresh-first", G, "    if (behind.length && !NOT_SAVED[seen.status]) {", "    if (false) {",
     lambda o: o["staging"]["refreshCalls"] == 0
     and _row(o["staging"]["rows"], "c2")["status"] != "built"),
    ("kept-no-refresh", G, "    if (behind.length && !NOT_SAVED[seen.status]) {",
     "    if (behind.length) {",
     lambda o: o["kept"]["refreshes"] != 0),
    ("frames-in-parallel", G, "  var FRAME_LIMIT = 2;", "  var FRAME_LIMIT = 1;",
     lambda o: o["staging"]["frames"]["maxLive"] < 2),
    ("frames-capped-at-two", G, "  var FRAME_LIMIT = 2;", "  var FRAME_LIMIT = 99;",
     lambda o: o["staging"]["frames"]["maxLive"] > 2),
    ("frame-marks-backup", P,
     '    const _doorOpened = (!!_q0 && _q0.get("compose") === "files") || _framed0;',
     '    const _doorOpened = !!_q0 && _q0.get("compose") === "files";',
     lambda o: o["staging"]["c3"]["mark"] is not True),
    ("backup-not-held", G, "    var ask = { hold_placeholders: !row.auto };",
     "    var ask = { hold_placeholders: true };",
     lambda o: o["staging"]["holds"]["c3"] is not False),
    ("backup-said", G, '    row.message = row.auto ? AUTO_SAID : "";\n    paint();',
     '    row.message = "";\n    paint();',
     lambda o: _row(o["staging"]["rows"], "c3")["message"] != DEFAULT_WORDING),
    ("slot-takes-it", G,
     "    if (framedCurrent) { try { await TW.reconcileWithServer(); } catch (e) {"
     " /* the next page asks again */ } }",
     "", lambda o: o["oneDraft"]["slotTotal"] != "$12,500"),
    ("ahead-saved", G,
     "      TW.setState({});\n      if (await TW.flushState()) seen = await TW.reconcileWithServer();",
     "", lambda o: o["ahead"]["serverNote"] != "Kyle's note, saved late"),
    ("only-what-changed", G,
     '    var holding = force ? [] : rows.filter(function (r) { return r.plan === "build"; });',
     "    var holding = [];",
     lambda o: o["onlyChanged"]["posted"] != ["c2"] and o["again"]["posted"] == ["d1"]),
    ("up-to-date-needs-the-document-to-hold", G, '    return TW.documentHolds(data) ? "build" : "frame";',
     '    return "build";',
     lambda o: o["estimateOnly"]["rows"][1] != ["c2", "built", "$9,500"]),
    ("expired-link-heals", G, "      if (resp.status === 404) {", "      if (false) {",
     lambda o: o["expired"]["healed"] is None),
    ("rebuild-all-is-fresh", G, "    if (force) ask.rebuild = true;", "    if (false) ask.rebuild = true;",
     lambda o: o["rebuild"]["rendered"] == []),
    ("rebuild-all-asks-nothing", G,
     '    var holding = force ? [] : rows.filter(function (r) { return r.plan === "build"; });',
     '    var holding = rows.filter(function (r) { return r.plan === "build"; });',
     lambda o: [x["status"] for x in o["rebuild"]["rows"]] != ["built"] * 3),
    ("up-to-date-said", G, '    if (fresh) {\n      if (!built && !failed) {',
     '    if (false) {\n      if (!built && !failed) {',
     lambda o: o["onlyChanged"]["note"] != "1 rebuilt, 2 up to date."),
    ("failure-said", G, "    if (!r.ok) { fail(row, r.error); return; }", "    if (!r.ok) { return; }",
     lambda o: _row(o["held"]["rows"], "c2")["status"] != "failed"),
    ("stale-child", G, "    if (!m.is_parent && m.stale) {", "    if (false) {",
     lambda o: _row(o["refused"]["rows"], "c2")["status"] == "built"),
    ("sent-child", G, '    if (held) return { status: "skipped", message: held };', "",
     lambda o: _row(o["held"]["rows"], "c3")["message"]
     != "Seal: the customer already has this proposal, so it was not moved."),
    ("child-pills", G, "    return parent && TW.isThisDraft(st) ? parent : TW.getDraftId();",
     "    return TW.getDraftId();",
     lambda o: o["fromChild"]["back"] == "/estimate-review.html?d=c2"),
    ("old-kind-take", "js/send-all-chain.js", "    if (!isSendAll(r)) return null;\n", "",
     lambda o: o["oldKind"]["took"] is not None),
    ("old-kind-live", "js/send-all-chain.js",
     "    if (!r || r.token !== tok || r.done || !isSendAll(r)) return null;",
     "    if (!r || r.token !== tok || r.done) return null;",
     lambda o: o["oldKind"]["progress"] is not None),
]


@needs_node
@pytest.mark.parametrize("name, rel, old, new, red", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_each_scenario_goes_red_without_its_line(tmp_path, name, rel, old, new, red):
    assert red(_run(_mutant(tmp_path, rel, old, new))), "%s: the scenario did not notice" % name


# ── the step pills, on every wizard page ─────────────────────────────────────────────────────
STEPS = [("1 · Intake", ("/?edit=1", "/polish-intake.html")),
         ("2 · Estimate", ("/estimate-review.html", "/polish-estimate.html")),
         ("3 · Generate Files", ("/generate.html",)),
         ("4 · Proposal", ("/proposal-review.html",)),
         ("5 · Files", ("/done.html",))]
# Each wizard page, and the step it is.
WIZARD = {"index.html": 0, "polish-intake.html": 0, "estimate-review.html": 1, "polish-estimate.html": 1,
          "generate.html": 2, "proposal-review.html": 3, "done.html": 4}


def _pill_problems(front):
    """Every way a page's step row is not the five steps in order, as sentences ([] when all hold)."""
    problems = []
    found = sorted(p.name for p in front.glob("*.html")
                   if '<div class="progress"' in p.read_bytes().decode("utf-8", errors="replace"))
    if found != sorted(WIZARD):
        problems.append("the pages with a step row are %r, not %r" % (found, sorted(WIZARD)))
    for name, here in WIZARD.items():
        html = (front / name).read_bytes().decode("utf-8")
        a = html.find('<div class="progress"')
        row = html[a:html.find("</div>", a)]
        pills = re.findall(r'<(a|span) class="step( active)?"[^>]*?(?: href="([^"]+)")?>([^<]*)<', row)
        labels = [p[3].strip() for p in pills]
        if labels != [s[0] for s in STEPS]:
            problems.append("%s: steps %r" % (name, labels))
            continue
        for i, (tag, active, href, _label) in enumerate(pills):
            if i == here:
                if not (tag == "span" and active):
                    problems.append("%s: step %d is not the page's own, active" % (name, i + 1))
            elif tag != "a" or active or href not in STEPS[i][1]:
                problems.append("%s: step %d links to %r" % (name, i + 1, href))
    return problems


def test_every_wizard_page_shows_the_five_steps_in_order():
    """One test over all pages: Intake, Estimate, Generate Files, Proposal, Files, each a link to
    its page (the v2 pages' own Intake and Estimate on those), the page's own step the active one."""
    assert _pill_problems(FRONTEND) == []


def test_the_pill_check_sees_a_missing_step(tmp_path):
    """MUTATION. Drop the new pill from one page and the check above has to say so."""
    front = tmp_path / "frontend"
    shutil.copytree(FRONTEND, front, ignore=shutil.ignore_patterns("js", "img", "*.css"))
    page = front / "done.html"
    src = page.read_bytes().decode("utf-8")
    assert src.count('<a class="step" href="/generate.html">3 · Generate Files</a>') == 1
    page.write_bytes(src.replace('<a class="step" href="/generate.html">3 · Generate Files</a>', "")
                     .encode("utf-8"))
    assert any(p.startswith("done.html") for p in _pill_problems(front))


def test_the_estimate_steps_continue_and_the_proposal_steps_back_lead_to_step_three():
    """Continue on the spreadsheet estimate and on the v2 estimate goes to step 3; Back on the
    Proposal step comes back to it."""
    est = (FRONTEND / "js" / "estimate-review.js").read_bytes().decode("utf-8")
    m = re.search(r'getElementById\("continue-btn"\)\.addEventListener\("click", \(\) => \{(.*?)\n\}\);',
                  est, re.S)
    assert m and 'TW.withDraft("/generate.html")' in m.group(1)
    v2 = (FRONTEND / "js" / "polish-estimate.js").read_bytes().decode("utf-8")
    assert "Continue to generate files" in v2 and 'TW.withDraft("/generate.html")' in v2
    pr = (FRONTEND / "js" / "proposal-review.js").read_bytes().decode("utf-8")
    m = re.search(r'getElementById\("back-btn"\)\.addEventListener\("click", \(\) => \{(.*?)\n  \}\);',
                  pr, re.S)
    assert m and 'TW.withDraft("/generate.html")' in m.group(1) and "estimate" not in m.group(1)
    assert "Continue to Generate Files" in (FRONTEND / "estimate-review.html").read_bytes().decode("utf-8")
    assert "Back to Generate Files" in (FRONTEND / "proposal-review.html").read_bytes().decode("utf-8")


def test_the_page_loads_shared_before_its_own_script_and_no_walk():
    """No walk any more: generate.html loads no send-all-chain.js, and its frame is styled hidden."""
    html = (FRONTEND / "generate.html").read_bytes().decode("utf-8")
    order = ["/js/icons.js", "/auth.js", "/shared.js", "/js/generate.js"]
    at = [html.index(s) for s in order]
    assert at == sorted(at), order
    assert "send-all-chain.js" not in html
    css = re.search(r"\.gen-frame \{(.*?)\}", html, re.S)
    assert css and "opacity: 0" in css.group(1) and "pointer-events: none" in css.group(1)


# ── the server: an unattended document with placeholders is held, only when asked ────────────
def _walk_built_gc():
    row = _draft("s2", "Room 2", "2026-10-02", files=False, audience="GC", proposal_auto_built=True)
    row["data"]["proposal_payload"] = {"work_type": "epoxy", "audience": "GC", "values": {
        "scope_notes": "", "schedule_notes": "", "architect": "", "total_formatted": "$2,000"}}
    return row


def test_a_held_build_of_a_walk_built_document_with_placeholders_is_refused(fake_supabase,
                                                                            monkeypatch):
    w = World(fake_supabase, monkeypatch, [_walk_built_gc()])
    r = client.post("/api/draft/s2/documents", json={"hold_placeholders": True})
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == (
        "Not built — this proposal was put together automatically and still has template "
        "placeholders (xx gallons, xx kits, [ 1 mob/phase ], xx Architects). Open its Proposal "
        "step, fill them, and press Continue.")
    assert "generate_result" not in w.store["drafts"][0]["data"], "a held build recorded files"


def test_the_files_page_and_a_backup_build_it_as_before(fake_supabase, monkeypatch):
    """The control: the Files page, and step 3's default-wording backup, send no hold and build as
    they always have (Send all's own check holds the send)."""
    w = World(fake_supabase, monkeypatch, [_walk_built_gc()])
    r = client.post("/api/draft/s2/documents", json={"hold_placeholders": False})
    assert r.status_code == 200, r.text
    assert w.store["drafts"][0]["data"].get("generate_result")


def test_a_person_composed_document_is_built_with_the_flag(fake_supabase, monkeypatch):
    """A person composed it on the Proposal step (no `proposal_auto_built`): theirs, built as written."""
    row = _walk_built_gc()
    row["data"]["proposal_auto_built"] = False
    World(fake_supabase, monkeypatch, [row])
    assert client.post("/api/draft/s2/documents", json={"hold_placeholders": True}).status_code == 200


def test_the_wizard_page_is_never_denied():
    import nav_access
    assert "/generate.html" in nav_access.ALWAYS_OPEN_PAGES
    assert "/generate.html" not in nav_access.TABS
