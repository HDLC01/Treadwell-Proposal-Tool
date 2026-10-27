"""3 · GENERATE FILES (Hanz, 2026-10-28).

"The top navigation bar, before we go to proposal, we should add another step that says generate
files, so that every time we would have a backup or a safety net that it would generate the files
every time we change something in the estimate." The wizard is now

    1 Intake -> 2 Estimate -> 3 Generate Files -> 4 Proposal -> 5 Files

and every arrival at step 3 builds the .xlsx, .docx and PDF of every live proposal of the project
(frontend/js/generate.js), through the Files step's own route (/api/draft/{id}/documents).

EXECUTED, NOT READ: js/generate-step-harness.js runs the real generate.js over the real shared.js and
send-all-chain.js, and walks the real Proposal-step door (files-door-harness.js's world). Each
mutation test breaks ONE line in a scratch copy of one file and requires the harness to go red; the
mutation is asserted to have applied. The pills are read off every wizard page's markup.
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
from test_scope_send_all import World, _draft

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "generate-step-harness.js"
FRONTEND = TESTS.parents[1] / "frontend"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
client = TestClient(main.app)


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


# ── one draft: the estimate changed, so the document is rebuilt first ──────────────────────
@needs_node
def test_a_changed_estimate_is_rebuilt_through_the_proposal_door_then_built(ran):
    """THE CASE. The last Continue built $10,000 / Smooth. The Estimate step then re-priced to $12,500
    and picked Orange Peel, and Continue led to step 3. Rendering the saved document would hand out
    the old price; the page walks the tab through the Proposal step's own door instead, which composes
    the document from the estimate as it stands and comes back, and the files are built from THAT."""
    o = ran["oneDraft"]
    assert o["builtBefore"] == "$10,000"
    pages = [s["page"] for s in o["stops"]]
    assert pages == ["generate", "proposal", "generate"], o["stops"]
    assert "compose=files" in o["stops"][0]["nav"][0][1] and "sendall=" in o["stops"][0]["nav"][0][1]
    assert o["stops"][1]["said"][0] == "Building Door Test for Generate Files (1 of 1)…"
    assert o["stops"][1]["nav"][0][1].startswith("/generate.html?d=d1&sendall_resume=")
    assert o["stops"][2]["nav"] == [], "the page walked again after it came back"
    assert o["rendered"] == [{"id": "d1", "texture": "Orange Peel", "total": "$12,500"}], o["rendered"]
    assert o["rows"] == [{"id": "d1", "name": "Door Test", "sheet": "", "status": "built",
                          "total": "$12,500", "message": "", "current": True}]
    assert o["links"] == ["0:xlsx_download_url", "0:docx_download_url", "0:pdf_download_url"]
    assert o["note"] == "The files are built."
    assert o["url"] == "/generate.html?d=d1", "the resume token stayed in the address bar"
    assert o["chainLeft"] is None, "the finished walk was left in sessionStorage"
    assert o["next"] == "/proposal-review.html?d=d1"


@needs_node
def test_a_generate_walk_does_not_mark_the_document_auto_built(ran):
    """A document a person composed, rebuilt after an estimate change, is not "built by nobody":
    Send all's placeholder hold (proposal_auto_built) stays as it was, as the Files page's door
    leaves it."""
    assert ran["oneDraft"]["mark"] is None


@needs_node
def test_every_arrival_builds_again(ran):
    """Nothing changed since the last visit: no walk, and the files are built again (the backup is the
    latest build, not one kept from an earlier visit)."""
    a = ran["again"]
    assert a["nav"] == []
    assert a["posted"] == ["d1"] and a["newRenders"] == 1
    assert a["rows"][0]["status"] == "built" and a["rows"][0]["total"] == "$12,500"
    assert a["pdfs"] == 2, "the PDF was not made on each visit"


@needs_node
def test_a_files_page_never_takes_a_generate_walk(ran):
    """The walk's record is one sessionStorage slot shared with Send all. A Files page that took a
    finished generate walk would press Send for the estimator."""
    k = ran["kinds"]
    assert k["door"] == "/proposal-review.html?d=d1&compose=files&sendall=TOK"
    assert k["doorNav"][0][1].startswith("/generate.html?d=d1&sendall_resume=")
    assert k["filesTook"] is None


@needs_node
def test_a_page_that_came_back_never_walks_again(ran):
    """A forged or expired resume: the document still does not match, and the page says so rather
    than walking (a loop guard, like the Files page's `composed=1`). Nothing is built from the old
    document either."""
    f = ran["forgedResume"]
    assert f["nav"] == [] and f["posted"] == []
    assert f["rows"][0]["status"] == "failed"
    assert f["rows"][0]["message"].startswith("It could not be rebuilt from the latest estimate here.")


# ── three proposals, one never opened ────────────────────────────────────────────────────────
@needs_node
def test_three_proposals_each_built_at_its_own_price_and_the_unopened_one_waits(ran):
    """Base Bid 1 (Epoxy, $10,000) and a child that was opened (Polish, $14,000) are both built, each
    from its own saved document at its own sheet's price. The child nobody opened has no document:
    composing it here would put Kyle's placeholders into a customer-facing file nobody read, so it is
    not built and says its files come from its Proposal step. Nothing walks, and Continue is open."""
    t = ran["three"]
    assert t["nav"] == [], "a walk started for a proposal that was never opened"
    assert t["posted"] == ["d1", "c2"], t["posted"]
    assert t["renders"] == [["d1", "$10,000"], ["c2", "$14,000.00"]]
    assert t["holdAsked"], "the build did not ask the server to hold an unattended placeholder document"
    rows = t["rows"]
    assert [(r["id"], r["name"], r["status"]) for r in rows] == [
        ("d1", "Epoxy", "built"), ("c2", "Polish", "built"), ("c3", "Seal", "later")]
    assert _row(rows, "d1")["total"] == "$10,000" and _row(rows, "c2")["total"] == "$14,000.00"
    assert "built when you open it on the Proposal step" in _row(rows, "c3")["message"]
    assert [l.split(":")[0] for l in t["links"]] == ["0", "0", "0", "1", "1", "1"], "a link for an unbuilt row"
    assert t["next"] == "/proposal-review.html?d=d1" and t["nextDisabled"] is False


@needs_node
def test_a_childs_step_three_builds_the_same_list(ran):
    """Opened on a proposal child, step 3 builds the project's list from its parent's view; Back and
    the Intake and Estimate pills go to the PARENT's, Proposal and Files stay the child's own."""
    c = ran["fromChild"]
    assert [(r["id"], r["status"], r["current"]) for r in c["rows"]] == [
        ("d1", "built", False), ("c2", "built", True), ("c3", "later", False)]
    assert c["back"] == "/estimate-review.html?d=d1"
    assert c["pills"] == {"intake": "/?edit=1&d=d1", "estimate": "/estimate-review.html?d=d1",
                          "proposal": "/proposal-review.html?d=c2", "files": "/done.html?d=c2"}
    assert c["next"] == "/proposal-review.html?d=c2"


@needs_node
def test_a_failed_build_says_why_and_never_blocks_continue(ran):
    f = ran["failed"]
    rows = f["rows"]
    assert _row(rows, "d1")["status"] == "built"
    assert _row(rows, "c2")["status"] == "failed"
    assert _row(rows, "c2")["message"] == "Could not build the proposal document."
    assert _row(rows, "c4")["status"] == "failed"
    assert _row(rows, "c4")["message"] == ("The estimate and proposal were built, but the PDF could "
                                           "not be made: Failed to render the PDF. Please try again.")
    assert f["links"] == ["0:xlsx_download_url", "0:docx_download_url", "0:pdf_download_url"]
    assert f["note"].startswith("1 of 3 built.") and "You can still continue" in f["note"]
    assert f["next"] == "/proposal-review.html?d=d1" and f["nextDisabled"] is False


@needs_node
def test_a_stale_out_of_step_or_lost_child_is_not_built(ran):
    """The Proposal step's tab strip warns about a stale or out-of-step child; nobody reads that
    warning here, so the row says it in the same words and nothing is built from the old copy. A
    sibling closed lost on the board is left alone."""
    h = ran["held"]
    assert h["posted"] == ["d1"] and h["nav"] == []
    rows = h["rows"]
    assert _row(rows, "c2")["status"] == "skipped"
    assert _row(rows, "c2")["message"].startswith("The estimate changed after this proposal was copied")
    assert _row(rows, "c3")["message"] == ("It prices no base bid of its own (same sheet as Base Bid "
                                           "1). Press Refresh on its Proposal step, then come back.")
    assert _row(rows, "c5")["message"] == "It is closed as lost on the board."


@needs_node
def test_a_copy_that_is_not_the_saved_one_starts_no_walk(ran):
    """Review, 2026-10-28. This browser's copy of the open proposal holds an unsaved edit and the
    saved one has moved since ("kept"). A sibling whose document no longer matches would need its
    door, and walking there hands the one copy slot to the sibling: the edit is gone before the
    Files step's "choose which copy to keep" card could offer it. So nothing walks, the sibling
    says why, a sibling that needs no door is still built, and the edit is still in this browser."""
    k = ran["kept"]
    assert k["nav"] == [], "a walk started and left this browser's unsaved copy behind"
    assert k["walk"] is None
    rows = k["rows"]
    assert _row(rows, "d1")["status"] == "failed"
    assert _row(rows, "c2")["status"] == "failed"
    assert _row(rows, "c2")["message"] == ("Not rebuilt: first choose which copy of the proposal open "
                                           "here to keep, on its Files step. Then come back.")
    assert _row(rows, "c4")["status"] == "built" and k["posted"] == ["c4"]
    assert k["localNote"] == "Kyle's note, never saved"


@needs_node
def test_back_and_the_pills_follow_the_draft(ran):
    """Back from step 3 goes to the estimate: the spreadsheet's, or the v2 page for a v2 draft."""
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
MUTATIONS = [
    ("compose", G, '    if ((isCurrent && seen.status === "ahead") || !TW.documentHolds(data)) return "compose";',
     '    if (false) return "compose";',
     lambda o: o["oneDraft"]["rendered"] and o["oneDraft"]["rendered"][0]["total"] == "$10,000"),
    ("loop-guard", G, "      if (!cameBack && window.TWSendAll) {", "      if (window.TWSendAll) {",
     lambda o: o["forgedResume"]["nav"] != []),
    ("never-opened", G,
     '    if (!(pp && typeof pp === "object" && pp.values && typeof pp.values === "object")) {',
     "    if (false) {",
     lambda o: o["three"]["nav"] != []),
    ("failure-said", G, "    if (!r.ok) { fail(row, r.error); return; }", "    if (!r.ok) { return; }",
     lambda o: _row(o["failed"]["rows"], "c2")["status"] != "failed"),
    ("every-arrival", G, "               plan: sort(m, data, m.id === id, seen, walked) };",
     '               plan: data && data.generate_result ? { status: "built", message: "" }'
     " : sort(m, data, m.id === id, seen, walked) };",
     lambda o: o["again"]["posted"] == []),
    ("stale-child", G, "    if (!m.is_parent && m.stale) {", "    if (false) {",
     lambda o: "c2" in o["held"]["posted"]),
    ("child-pills", G, "    return parent && TW.isThisDraft(st) ? parent : TW.getDraftId();",
     "    return TW.getDraftId();",
     lambda o: o["fromChild"]["back"] == "/estimate-review.html?d=c2"),
    ("no-auto-mark", "js/proposal-review.js",
     '    const _sendAllBuild = (!!_walk0 && _walk0.kind !== "generate") || (_doorOpened && !_hadDoc0);',
     "    const _sendAllBuild = !!_walk0;",
     lambda o: o["oneDraft"]["mark"] is True),
    ("kept-no-walk", G, "    if (compose.length && unsure) {", "    if (false) {",
     lambda o: o["kept"]["nav"] != []),
    ("take-kind", "js/send-all-chain.js", "    if (kindOf(r.kind) !== kindOf(kind)) return null;\n", "",
     lambda o: o["kinds"]["filesTook"] is not None),
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


def test_the_page_loads_the_walk_before_its_own_script():
    html = (FRONTEND / "generate.html").read_bytes().decode("utf-8")
    order = ["/js/icons.js", "/auth.js", "/shared.js", "/js/send-all-chain.js", "/js/generate.js"]
    at = [html.index(s) for s in order]
    assert at == sorted(at), order


# ── the server: an unattended document with placeholders is held, only when asked ────────────
def _walk_built_gc():
    row = _draft("s2", "Room 2", "2026-10-02", files=False, audience="GC", proposal_auto_built=True)
    row["data"]["proposal_payload"] = {"work_type": "epoxy", "audience": "GC", "values": {
        "scope_notes": "", "schedule_notes": "", "architect": "", "total_formatted": "$2,000"}}
    return row


def test_the_generate_step_is_refused_a_walk_built_document_with_placeholders(fake_supabase,
                                                                              monkeypatch):
    w = World(fake_supabase, monkeypatch, [_walk_built_gc()])
    r = client.post("/api/draft/s2/documents", json={"hold_placeholders": True})
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == (
        "Not built — this proposal was put together automatically and still has template "
        "placeholders (xx gallons, xx kits, [ 1 mob/phase ], xx Architects). Open its Proposal "
        "step, fill them, and press Continue.")
    assert "generate_result" not in w.store["drafts"][0]["data"], "a held build recorded files"


def test_the_files_page_still_builds_it_as_before(fake_supabase, monkeypatch):
    """The control: the Files page sends no flag and builds as it always has (its own Send is held
    by Send all's check); so the hold is the new flag's, not a change to Download."""
    w = World(fake_supabase, monkeypatch, [_walk_built_gc()])
    r = client.post("/api/draft/s2/documents", json={})
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
