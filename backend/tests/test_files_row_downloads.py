"""Each line of step 5's Lump sums list downloads its own proposal (Hanz, 2026-10-29).

"each lump sum should have a download button can that be possible? it should be aligned to the
row". He chose three small buttons per line, PDF / .docx / .xlsx, the same three files as the big
buttons at the top, for THAT line's proposal:

  * this one's line presses the big buttons' own downloadAs (same requests, same file names);
  * another one's line builds THAT proposal's files from ITS saved document: GET /api/draft/{its id},
    then POST /api/draft/{its id}/documents with the draft_version read, so the server builds the
    copy read and nothing of this page's draft; saved as "<project>_<its name>_proposal.pdf" etc.;
  * the file prints the figure the line shows, or nothing is saved and the list is read again;
  * a proposal never built has its buttons off and says "Not built yet. Open it to build its files.";
  * a failure says so on the line, survives the repaint, and the button comes back;
  * a one-proposal project has no list and no line buttons.

Run, not read: js/files-row-downloads-harness.js executes done.js's own functions and
showPostGenerate's download wiring over a small DOM. The BREAKS prove each check goes red when its
line goes. The server half drives the real route and the real renderer.
"""
from __future__ import annotations

import copy
import io
import pathlib
import re
import zipfile

import pytest
from fastapi.testclient import TestClient

import drafts
import main
from _golden_support import FRONTEND, break_source
from _node import last_json_line, require_node, run_node

HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "files-row-downloads-harness.js"
ALSO = ("js/price-lines-core.js",)


def run(frontend=FRONTEND):
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def out():
    require_node()
    return run()


LABELS = ["PDF", ".docx", ".xlsx"]
REASON = "Not built yet. Open it to build its files."
CHANGED = ("Not downloaded: Its price changed since this page read it. The line shows the new figure "
           "now; press again to download it.")


def test_every_line_carries_three_buttons_after_its_name_and_figure(out):
    lines = out["lines"]
    assert [ln["name"] for ln in lines] == ["Breakroom", "Polish Room 2", "Kitchen"]
    for ln in lines:
        assert [b["label"] for b in ln["buttons"]] == LABELS
        assert all(b["type"] == "button" and b["cls"] == "btn-secondary rv-prop-dl-b" for b in ln["buttons"])
        assert [b["aria"] for b in ln["buttons"]] == [lab + " of " + ln["name"] for lab in LABELS]
        assert ln["last"], "the buttons and the line's message come after the name and the figure"
    assert [b["disabled"] for b in lines[0]["buttons"] + lines[1]["buttons"]] == [False] * 6
    assert lines[0]["msg"] is None and lines[1]["msg"] is None


def test_a_proposal_never_built_has_its_buttons_off_and_says_why(out):
    k = out["lines"][2]
    assert [(b["disabled"], b["wired"]) for b in k["buttons"]] == [(True, 0)] * 3
    assert k["msg"] == REASON
    assert out["neverBuilt"]["reqs"] == [] and out["neverBuilt"]["saved"] == []


@pytest.mark.parametrize("label,name", [("PDF", "Acme_Plant_Polish_Room_2_proposal.pdf"),
                                        (".docx", "Acme_Plant_Polish_Room_2_proposal.docx"),
                                        (".xlsx", "Acme_Plant_Polish_Room_2_estimate.xlsx")])
def test_this_ones_line_is_the_big_buttons_press(out, label, name):
    s = out["same"][label]
    assert s["row"] == s["big"], "the same requests, the same name, the same busy state"
    assert s["row"]["saved"] == [name]
    assert [q for q in s["row"]["reqs"] if q.startswith("post ")] == [
        "post /api/draft/C2/documents " + ("{}" if label == ".xlsx" else '{"draft_version":"v-C2"}')]


def test_this_ones_line_builds_nothing_before_the_card_is_wired(out):
    assert out["unwired"]["reqs"] == [] and out["unwired"]["saved"] == []


@pytest.mark.parametrize("label,file,name", [
    ("PDF", "/api/file/P1/pdf", "Acme_Plant_Breakroom_proposal.pdf"),
    (".docx", "/api/file/P1", "Acme_Plant_Breakroom_proposal.docx"),
    (".xlsx", "/api/file/P1X", "Acme_Plant_Breakroom_estimate.xlsx")])
def test_another_line_builds_its_own_proposal_from_its_saved_document(out, label, file, name):
    o = out["other"][label]
    assert o["reqs"] == ["get /api/draft/P1",
                         "post /api/draft/P1/documents {\"draft_version\":\"v-P1\"}",
                         "get " + file], "its own row, its own id, the copy read; no flush of this page"
    assert o["saved"] == [name]
    assert o["busy"] == [["Downloading…", True]]
    assert o["pressed"] == [label, False], "the button comes back once the file is saved"
    assert o["asked"] == [] and o["after"]["msg"] is None


def test_a_document_saved_again_at_another_figure_builds_nothing(out):
    m = out["moved"]
    assert m["reqs"] == ["get /api/draft/P1"] and m["saved"] == []
    assert m["asked"] == ["C2"], "the list is read again"
    assert m["after"]["msg"] == CHANGED and m["pressed"] == ["PDF", False]


def test_the_file_must_print_the_lines_figure(out):
    r = out["renderMoved"]
    assert r["saved"] == [], "the render answered $19,000.00 against the line's $20,000.00"
    assert r["after"]["msg"] == CHANGED and r["asked"] == ["C2"]


def test_the_own_figure_question_is_asked_of_its_document_and_cancel_builds_nothing(out):
    c = out["cancel"]
    assert c["confirms"] == ["Download with a different price?"]
    assert c["reqs"] == ["get /api/draft/P1"] and c["saved"] == []
    assert c["after"]["msg"] is None and c["pressed"] == ["PDF", False]
    assert out["xlsxNotAsked"]["confirms"] == [] and out["xlsxNotAsked"]["saved"] == [
        "Acme_Plant_Breakroom_estimate.xlsx"], "the estimate carries no price line, as at the top"


def test_failures_say_so_on_the_line_and_the_button_comes_back(out):
    f = out["fileFails"]
    assert f["saved"] == [] and f["pressed"] == ["PDF", False]
    assert f["after"]["msg"] == "Not downloaded: The file didn't come back (Internal Server Error). Try again."
    assert out["fileFailsRepainted"]["msg"] == f["after"]["msg"], "a repaint keeps what the line said"
    p = out["postFails"]
    assert p["after"]["msg"] == "Not downloaded: Not built — this proposal was saved again."
    assert p["asked"] == ["C2"] and p["pressed"] == [".docx", False]
    r = out["readFails"]
    assert r["reqs"] == ["get /api/draft/P1"] and r["saved"] == []
    assert r["after"]["msg"] == "Not downloaded: Couldn't read Breakroom. Check your connection and try again."


def test_a_one_proposal_project_is_unchanged(out):
    s = out["single"]
    assert s == {"lines": [], "text": "$7,447.00", "key": "Lump sum", "children": 0}


BREAKS = {
    "no buttons on the lines": (
        "      if (opts && opts.files) opts.files(li, m, mine);", "",
        lambda r: r["lines"][0]["buttons"] is not None),
    "this line is not handed the big buttons' press": (
        "    rowFiles.mine = downloadAs;", "",
        lambda r: r["same"]["PDF"]["row"] == r["same"]["PDF"]["big"]),
    "another line builds this page's draft": (
        '        out = await TW.postJSON("/api/draft/" + encodeURIComponent(m.id) + "/documents",',
        '        out = await TW.postJSON("/api/draft/" + encodeURIComponent(TW.getDraftId()) + "/documents",',
        lambda r: r["other"]["PDF"]["saved"] == ["Acme_Plant_Breakroom_proposal.pdf"]),
    "the copy read is not named to the server": (
        "                                version ? { draft_version: version } : {});",
        "                                {});",
        lambda r: 'post /api/draft/P1/documents {"draft_version":"v-P1"}' in r["other"]["PDF"]["reqs"]),
    "the read document's figure is not checked": (
        "      if (money(pp.values.total_formatted) !== shown) { moved = true; throw new Error(changed); }", "",
        lambda r: r["moved"]["reqs"] == ["get /api/draft/P1"]),
    "the render's figure is not checked": (
        "      if (!out || money(out.document_total) !== shown) { moved = true; throw new Error(changed); }", "",
        lambda r: r["renderMoved"]["saved"] == []),
    "a never-built line's buttons are live": (
        "      if (!built) b.disabled = true;", "      if (false) b.disabled = true;",
        lambda r: r["lines"][2]["buttons"][0]["disabled"] is True),
    "a never-built line says nothing": (
        '    msg.textContent = built ? (rowFiles.said[m.id] || "") : "Not built yet. Open it to build its files.";',
        '    msg.textContent = built ? (rowFiles.said[m.id] || "") : "";',
        lambda r: r["lines"][2]["msg"] == REASON),
    "a repaint wipes what the line said": (
        '    msg.textContent = built ? (rowFiles.said[m.id] || "") : "Not built yet. Open it to build its files.";',
        '    msg.textContent = built ? "" : "Not built yet. Open it to build its files.";',
        lambda r: r["fileFailsRepainted"]["msg"] is not None),
    "the button stays off after a press": (
        "      button.textContent = orig;", "      return;",
        lambda r: r["fileFails"]["pressed"] == ["PDF", False]),
    "the own-figure question is not asked": (
        "      if (f.key !== \"xlsx_download_url\"", "      if (false",
        lambda r: r["cancel"]["saved"] == []),
    "the file is named after this page's proposal": (
        "      a.download = fileStem(project, { id: m.id, name: name }) + f.tail;",
        "      a.download = fileStem(project) + f.tail;",
        lambda r: r["other"]["PDF"]["saved"] == ["Acme_Plant_Breakroom_proposal.pdf"]),
    "a failure says nothing": (
        '      msg.textContent = rowFiles.said[m.id] = "Not downloaded: " + portalErrMsg(err);', "",
        lambda r: r["fileFails"]["after"]["msg"] == "Not downloaded: The file didn't come back "
                                                    "(Internal Server Error). Try again."),
    "a moved price does not read the list again": (
        "      if (moved) refreshFilesProposals();", "",
        lambda r: r["moved"]["asked"] == ["C2"]),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_checks_go_red_when_the_code_changes(tmp_path, name):
    require_node()
    old, new, holds = BREAKS[name]
    frontend = break_source(tmp_path, "js/done.js", old, new, also=ALSO)
    proc = run_node(HARNESS, frontend)
    if proc.returncode != 0:
        return   # the break stopped the page outright: noticed
    assert not holds(last_json_line(proc.stdout)), "the checks did not notice: " + name


# ── the server's half: another proposal's files are ITS document ─────────────────────────────────

client = TestClient(main.app)
EST = "kyle@wetreadwell.com"


def _payload(name, total):
    return {"work_type": "epoxy", "audience": "Direct",
            "values": {"project_name": name, "job_name": name, "city_state": "Lenexa, KS",
                       "epoxy_sf": "1000", "total_formatted": total, "lump_sum_formatted": total,
                       "estimator_name": "Kyle Loseke", "estimator_email": EST,
                       "texture": "Orange Peel"}}


@pytest.fixture
def two(monkeypatch, fake_supabase):
    store = {"drafts": [
        {"id": "c2", "owner_email": EST, "updated_at": "2026-10-29T10:00:00+00:00",
         "data": {"project_name": "Row Downloads", "proposal_payload": _payload("Row Downloads", "$15,000.50")}},
        {"id": "p1", "owner_email": EST, "updated_at": "2026-10-29T09:00:00+00:00",
         "data": {"project_name": "Row Downloads", "proposal_payload": _payload("Row Downloads", "$20,000.00")}},
    ]}
    monkeypatch.setattr(drafts, "get_client", lambda: fake_supabase(store))
    monkeypatch.setattr(drafts, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: {"email": e, "role": "admin"})
    monkeypatch.setattr(main.pdf_writer, "docx_to_pdf", lambda b: b"%PDF-1.4 " + b[:16])
    return store


def _text(docx_bytes):
    xml = zipfile.ZipFile(io.BytesIO(docx_bytes)).read("word/document.xml").decode("utf-8")
    return re.sub(r"<[^>]+>", "", xml)


def test_another_proposals_files_print_its_own_figure(two):
    """What the line's button asks of the server: P1's row, then P1's documents with the version
    read. The answer and the document print P1's $20,000.00, never this page's $15,000.50.

    Mutation: build /api/draft/{id}/documents from another draft's payload -- the figure moves."""
    row = client.get("/api/draft/p1").json()
    assert row["data"]["proposal_payload"]["values"]["total_formatted"] == "$20,000.00"
    r = client.post("/api/draft/p1/documents", json={"draft_version": row["updated_at"]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["document_total"] == "$20,000.00"
    docx = client.get(out["docx_download_url"])
    assert docx.status_code == 200
    text = _text(docx.content)
    assert "20,000" in text and "15,000.50" not in text
    assert client.get(out["xlsx_download_url"]).status_code == 200
    assert client.get(out["pdf_download_url"]).status_code == 200


def test_another_proposal_saved_again_after_the_read_is_not_built(two):
    """The version the line read is the copy built: a save landing between the read and the press
    is refused (409), so the file can never carry a figure the line did not show."""
    row = client.get("/api/draft/p1").json()
    p1 = [d for d in two["drafts"] if d["id"] == "p1"][0]
    p1["data"] = copy.deepcopy(p1["data"])
    p1["data"]["proposal_payload"]["values"]["total_formatted"] = "$21,000.00"
    p1["updated_at"] = "2026-10-29T11:00:00+00:00"
    r = client.post("/api/draft/p1/documents", json={"draft_version": row["updated_at"]})
    assert r.status_code == 409, r.text
