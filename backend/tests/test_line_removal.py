"""Deleting a line removes the line, the way Word does -- in the generated document.

Hanz, 2026-09-26, deleting a line in the Proposal step's WORK box: "This is also weird when I delete
a line." His screenshot: under the Exclusions paragraph, two empty rows left behind, each with the
edit bar and the ribbon's wash. An emptied paragraph stayed a paragraph -- on screen, and in the
.docx, where it printed as a blank line. In Word, Backspace on an empty paragraph takes it away.

The editor now sends that as `{"id": n, "removed": true}` (proposal-review.js removeLine /
collectOverrides; executed in js/line-removal-harness.js). This file is the document half:

  * the writer takes the paragraph out of the PRISTINE template in Phase 0, collecting first and
    removing after the one walk, so every other id still lands on its own paragraph;
  * `paragraph_removable` is the one rule, served to the editor as `fit.removable`, and the writer
    honours exactly what it serves;
  * `text: ""` keeps meaning what it meant before: print the paragraph EMPTY;
  * a box keeps at least one paragraph, and nothing that anchors artwork, a region row, a numbered
    Terms clause or the Options heading can be removed.

Every document check goes through the real `main._generate`, the function Download, Send and the
customer PDF all render through. LibreOffice is not installed on the dev box, so the checks are made
on the .docx itself (the mc:Choice text boxes, which is what both Word and LibreOffice lay out).
"""
import io
import json

import pytest
from docx import Document
from docx.oxml.ns import qn
from starlette.requests import Request

import main
import proposal_writer as pw

_VALS = {
    "job_name": "Removal QA", "project_name": "Removal QA", "city_state": "Olathe, KS",
    "bid_date_formatted": "9/26/26", "total_formatted": "$36,763", "base_bid_formatted": "$36,763",
    "state_name": "Kansas", "system_name": "MACRO", "texture": "OP", "epoxy_sf": "12,000",
    "scope_notes": "Grind and coat.", "schedule_notes": "~5 days", "work_description": "Warehouse",
    "site_visit_date": "9/25", "disposal": "d", "exclusions": "Standard exclusions.",
    "work_notes": "Work note.", "estimator_name": "QA Estimator",
}

# Every template the Proposal step can put on screen.
TEMPLATES = [("epoxy", "Direct"), ("polish", "Direct"), ("combo", "Direct"), ("budget", "Direct"),
             ("epoxy", "GC"), ("polish", "GC"), ("sealer", "GC"), ("gyp", "Direct")]


def _template(work_type, audience):
    """The real /api/proposal-template body (blocks + version) for one template."""
    req = Request({"type": "http", "headers": [], "method": "GET",
                   "path": "/api/proposal-template", "query_string": b""})
    return json.loads(main.api_proposal_template(req, work_type, audience).body)


def _docx(work_type, audience, overrides=None, **extra):
    """The .docx the real generate path produces, read straight out of its file cache."""
    tv = _template(work_type, audience)["template_version"]
    body = {"work_type": work_type, "audience": audience, "values": dict(_VALS),
            "template_version": tv, "paragraph_overrides": list(overrides or [])}
    body.update(extra)
    req = Request({"type": "http", "headers": [], "method": "POST", "path": "/api/generate"})
    out = main._generate(main.GenerateIn(**body), req, persist=False, want_estimate=False)
    return main._FILE_CACHE[out.docx_download_url.rstrip("/").split("/")[-1]]["content"]


def _text(p):
    return "".join(t.text or "" for t in p.iter(qn("w:t")))


def _boxes(docx_bytes):
    """Per real text box (the writer's own box order): the list of its paragraph texts."""
    d = Document(io.BytesIO(docx_bytes))
    return [[_text(p) for p in tx if p.tag == qn("w:p")] for tx in pw._iter_txbx(d)]


def _box_blocks(tpl):
    return [b for b in tpl["blocks"] if b["txbx"] is not None]


# ── the rule the editor is served is the rule the writer applies ──────────────
@pytest.mark.parametrize("work_type,audience", TEMPLATES)
def test_fit_removable_is_the_writers_own_answer(work_type, audience):
    """Every text-box block the template endpoint marks `removable` really does come out of the
    document when the editor asks, and every one it does not mark stays. Two renders per template:
    one asking to remove every other line (none may go), one asking to remove every removable line.

    Three things are set aside from the second count, each for a reason the writer states:
      * the FREE Remodel Tax row (GC, Gyp), which the writer takes out itself on a job with no
        remodel tax, so asking changes nothing;
      * the blank lines directly above a free Options heading (GC), which the Options gap replaces
        with its own count whatever Phase 0 did to them;
      * the LAST free paragraph of a box, which stays when every one of them is asked for: block
        expansion can strip all of a box's region rows, and a text box with no paragraph is a file
        Word refuses (the editor keeps one `.tw-block` per box for the same reason)."""
    tpl = _template(work_type, audience)
    blocks = _box_blocks(tpl)
    by_id = {b["id"]: b for b in tpl["blocks"]}
    remodel = {b["id"] for b in blocks
               if "tax_amount_formatted" in b["text"] or "remodel.amount" in b["text"]}
    absorbed = set()
    for h in tpl["options_heading_ids"]:
        k = h - 1
        while k in by_id and by_id[k]["txbx"] == by_id[h]["txbx"] and not by_id[k]["in_block"] \
                and not by_id[k]["text"].strip():
            absorbed.add(k)
            k -= 1
    base = _boxes(_docx(work_type, audience))
    no = [b for b in blocks if not b["fit"]["removable"]]
    yes = [b for b in blocks if b["fit"]["removable"] and b["id"] not in remodel | absorbed]
    assert yes, "the template offers no removable line at all"

    kept = _boxes(_docx(work_type, audience, [{"id": b["id"], "removed": True} for b in no]))
    assert [len(x) for x in kept] == [len(x) for x in base], (
        "a paragraph the editor may not remove came out of the document anyway")

    gone = _boxes(_docx(work_type, audience, [{"id": b["id"], "removed": True} for b in yes]))
    for box_id, (before, after) in enumerate(zip(base, gone)):
        asked = {b["id"] for b in yes if b["txbx"] == box_id}
        # The Remodel row does not keep a box alive on this job: the writer takes it out anyway.
        free = {b["id"] for b in blocks if b["txbx"] == box_id and not b["in_block"]} - remodel
        keep = 1 if asked and asked == free else 0
        assert len(after) >= 1, "box %d was left with no paragraph at all" % box_id
        assert len(before) - len(after) == len(asked) - keep, (
            "box %d: asked to remove %d paragraph(s) (%d must stay), %d went"
            % (box_id, len(asked), keep, len(before) - len(after)))


def test_what_is_never_removable():
    """The four kinds `paragraph_removable` refuses, by name, on the templates that carry them: a
    {{#block}} region's row (priced, engine-owned), a numbered Terms clause (removing one renumbers
    the contract), the Terms flow on the body, and the GC Options heading the gap is counted from."""
    epoxy = {b["id"]: b for b in _template("epoxy", "Direct")["blocks"]}
    assert all(not b["fit"]["removable"] for b in epoxy.values() if b["in_block"]), (
        "a region row is offered for removal")
    assert all(not b["fit"]["removable"] for b in epoxy.values() if b["txbx"] is None), (
        "a body paragraph (the Terms flow) is offered for removal")
    clauses = [b for b in epoxy.values() if (b.get("para") or {}).get("marker")]
    assert clauses and all(not b["fit"]["removable"] for b in clauses), (
        "a numbered Terms clause is offered for removal")
    gc = _template("epoxy", "GC")
    heads = gc["options_heading_ids"]
    assert heads and all(not b["fit"]["removable"] for b in gc["blocks"] if b["id"] in heads)


# ── one removal, and every other id still lands ──────────────────────────────
def _pick(tpl, starts):
    return next(b for b in tpl["blocks"] if b["txbx"] is not None and b["text"].startswith(starts))


def test_a_removed_line_is_not_printed_and_every_other_id_still_lands():
    """The Phase 0 invariant, executed. Remove the Exclusions line out of the Direct epoxy WORK box
    and rewrite the lines on either side of it in the same payload: the Exclusions line is gone,
    the box is one paragraph shorter, and the two rewrites are on their own paragraphs -- not
    shifted by one, which is what removing inside the walk would do."""
    tpl = _template("epoxy", "Direct")
    excl = _pick(tpl, "Exclusions:")
    before, after = _pick(tpl, "Schedule:"), _pick(tpl, "Notes:")
    assert excl["fit"]["removable"]
    base = _boxes(_docx("epoxy", "Direct"))
    work = excl["txbx"]
    got = _boxes(_docx("epoxy", "Direct", [
        {"id": before["id"], "text": "Schedule:  BEFORE-QA"},
        {"id": excl["id"], "removed": True},
        {"id": after["id"], "text": "Notes:  AFTER-QA"},
    ]))
    assert len(got[work]) == len(base[work]) - 1
    assert not any(t.startswith("Exclusions:") for t in got[work]), "the removed line printed"
    i = base[work].index(next(t for t in base[work] if t.startswith("Schedule:")))
    assert got[work][i] == "Schedule:  BEFORE-QA", "the line above the removal moved"
    assert got[work][i + 1] == "Notes:  AFTER-QA", (
        "the line below the removal did not close up onto it, or landed on the wrong paragraph")
    # Every other box is exactly as it was.
    assert [b for k, b in enumerate(got) if k != work] == [b for k, b in enumerate(base) if k != work]


def test_an_empty_text_override_still_prints_the_line_empty():
    """Drafts saved before `removed` existed carry `text: ""` for every line the estimator emptied,
    and that has always meant "print this paragraph empty". It still does: same paragraph count,
    that paragraph empty."""
    tpl = _template("epoxy", "Direct")
    excl = _pick(tpl, "Exclusions:")
    base = _boxes(_docx("epoxy", "Direct"))
    got = _boxes(_docx("epoxy", "Direct", [{"id": excl["id"], "text": ""}]))
    work = excl["txbx"]
    assert len(got[work]) == len(base[work])
    i = base[work].index(next(t for t in base[work] if t.startswith("Exclusions:")))
    assert got[work][i] == ""


@pytest.mark.parametrize("flag", ["true", 1, "yes", False, None])
def test_removed_means_exactly_true(flag):
    """Nothing but a JSON `true` removes a line, in the sanitizer and in the writer both, so no
    stray value in a saved draft can delete customer-facing text."""
    tpl = _template("epoxy", "Direct")
    excl = _pick(tpl, "Exclusions:")
    assert main._sanitize_paragraph_overrides([{"id": excl["id"], "removed": flag}]) != [
        {"id": excl["id"], "removed": True}]
    base = _boxes(_docx("epoxy", "Direct"))
    got = _boxes(_docx("epoxy", "Direct", [{"id": excl["id"], "removed": flag}]))
    assert got == base
    # THE WRITER'S OWN RULE, not only the sanitizer's: `fill_proposal` is public, and a caller that
    # never went through `_sanitize_paragraph_overrides` gets the same answer. The True control
    # shows this direct path really removes, so the equality above it is not vacuous.
    def direct(overrides):
        return _boxes(pw.fill_proposal(work_type="epoxy", audience="Direct", values=dict(_VALS),
                                       paragraph_overrides=overrides))
    plain = direct([])
    assert direct([{"id": excl["id"], "removed": flag}]) == plain
    assert direct([{"id": excl["id"], "removed": True}]) != plain


def test_the_sanitizer_sends_a_removal_as_nothing_but_its_id():
    """A removed line has no words or bullet left to apply: whatever else the entry carries is
    dropped on the way in, so the writer cannot be asked to both remove and rewrite it."""
    assert main._sanitize_paragraph_overrides(
        [{"id": 117, "removed": True, "text": "x", "runs": [{"text": "x"}], "para": {"bullet": True}}]
    ) == [{"id": 117, "removed": True}]


def test_a_templates_own_blank_spacer_can_go_and_an_untouched_one_prints():
    """A blank line Kyle put in the template is a line like any other: removable the same way, and
    printed as it always was when nobody touches it."""
    tpl = _template("epoxy", "Direct")
    spacer = next(b for b in tpl["blocks"]
                  if b["txbx"] is not None and not b["text"] and b["fit"]["removable"]
                  and b["txbx"] == _pick(tpl, "Exclusions:")["txbx"])
    base = _boxes(_docx("epoxy", "Direct"))
    got = _boxes(_docx("epoxy", "Direct", [{"id": spacer["id"], "removed": True}]))
    box = spacer["txbx"]
    assert "" in base[box], "the untouched template spacer does not print"
    assert len(got[box]) == len(base[box]) - 1


def test_a_box_keeps_its_last_paragraph():
    """The DATE box holds one paragraph. Asking to remove it is refused: a text box with no
    paragraph is a file Word refuses to open, and the editor never offers it (it keeps the last line
    of every box)."""
    tpl = _template("epoxy", "Direct")
    date = _pick(tpl, "{{bid_date_formatted}}")
    base = _boxes(_docx("epoxy", "Direct"))
    assert len(base[date["txbx"]]) == 1
    got = _boxes(_docx("epoxy", "Direct", [{"id": date["id"], "removed": True}]))
    assert got[date["txbx"]] == base[date["txbx"]] == ["9/26/26"]


def test_a_removed_free_remodel_row_is_not_removed_twice():
    """The GC files author their Remodel Tax row as a free paragraph, which the writer takes out on
    its own when the job has no remodel tax (found on the pristine template before Phase 0). A
    removal of the same row in the same payload must not trip over it."""
    tpl = _template("epoxy", "GC")
    remodel = _pick(tpl, "{{tax_amount_formatted}}")
    assert remodel["fit"]["removable"]
    got = _boxes(_docx("epoxy", "GC", [{"id": remodel["id"], "removed": True}]))
    assert not any("Remodel Tax" in t for box in got for t in box)


# ══ the editor half, executed ═════════════════════════════════════════════════
# js/line-removal-harness.js lifts the page's REAL Backspace/Delete handler, its box-wide Delete,
# the whole undo section, spliceLines, collectOverrides and restoreSavedOverrides out of
# proposal-review.js and drives them with real keydown events through a capture-then-bubble
# dispatch. Each scenario reports every line of the box: still a `.tw-block`, taken out
# (`tw-block-removed`, hidden), and its text.
import pathlib as _pathlib
import re as _re
import shutil as _shutil
import subprocess as _subprocess

_FRONTEND = _pathlib.Path(__file__).resolve().parents[2] / "frontend"
_HARNESS = _pathlib.Path(__file__).resolve().parent / "js" / "line-removal-harness.js"
_CSS = (_FRONTEND / "styles.css").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ran():
    node = _shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    got = _subprocess.run([node, str(_HARNESS), str(_FRONTEND)], capture_output=True,
                          encoding="utf-8", errors="replace", timeout=120)
    assert got.returncode == 0, "the harness itself failed:\n" + got.stderr
    return json.loads(got.stdout)


def _states(lines):
    return [("kept" if ln["block"] else "removed" if ln["removed"] else "line") for ln in lines]


def test_backspace_on_an_empty_line_takes_it_out(ran):
    """The gesture Hanz made. The emptied line goes from the page -- hidden, its `tw-block` traded
    for `tw-block-removed`, so no walk over the page's lines sees it -- the caret lands at the end of
    the line above, the key is consumed, and the page persists through its own input event."""
    got = ran["backspaceEmpty"]
    assert _states(got["lines"]) == ["kept", "removed", "kept"]
    assert got["lines"][1]["display"] == "none"
    assert got["caret"] == {"line": "200", "at": 8}
    assert got["prevented"] is True
    assert got["inputs"] == ["200"], "the removal reached no save channel"
    assert got["boxLines"] == 2


def test_the_removal_is_saved_as_nothing_but_the_id_and_the_flag(ran):
    assert ran["backspaceEmpty"]["overrides"] == [{"id": 201, "removed": True}]


def test_ctrl_z_brings_the_line_back_and_ctrl_y_takes_it_out_again(ran):
    """An undo gives back the LINE, where it was. The line comes back empty (it was emptied before it
    was removed), so the next save says "print this empty" -- the state before the Backspace."""
    assert _states(ran["undoRemoval"]["lines"]) == ["kept", "kept", "kept"]
    assert ran["undoRemoval"]["lines"][1]["display"] == ""
    assert ran["undoRemoval"]["overrides"] == [{"id": 201, "text": "", "kept": True}]
    assert _states(ran["redoRemoval"]["lines"]) == ["kept", "removed", "kept"]
    assert ran["redoRemoval"]["overrides"] == [{"id": 201, "removed": True}]


def test_delete_on_an_empty_line_takes_it_out_and_moves_the_caret_down(ran):
    got = ran["deleteEmpty"]
    assert _states(got["lines"]) == ["kept", "removed", "kept"]
    assert got["caret"] == {"line": "202", "at": 0}
    assert got["prevented"] is True


def test_backspace_at_a_line_start_takes_out_the_empty_line_above(ran):
    """Word merges the two, and merging into an empty paragraph is the empty paragraph going. The
    caret stays where it was, at the start of the line the estimator was on."""
    got = ran["backspaceIntoEmpty"]
    assert _states(got["lines"]) == ["kept", "removed", "kept"]
    assert got["caret"] == {"line": "202", "at": 0}


def test_delete_at_a_line_end_takes_out_the_empty_line_below(ran):
    got = ran["deleteIntoEmpty"]
    assert _states(got["lines"]) == ["kept", "removed", "kept"]
    assert got["caret"] == {"line": "200", "at": 8}


def test_a_line_the_template_will_not_let_go_stays_and_nothing_merges(ran):
    """A numbered Terms clause, a region row: `fit.removable` is false, so the line stays and the key
    is still refused -- the old no-merge rule, untouched."""
    got = ran["notRemovable"]
    assert _states(got["lines"]) == ["kept", "kept", "kept"]
    assert got["prevented"] is True
    assert got["overrides"] == []


def test_a_box_keeps_its_last_line_and_its_last_template_line(ran):
    """The only line in a box stays under either key. So does the last TEMPLATE line beside a priced
    row -- the writer keeps one free paragraph per box, because the region rows can all be stripped
    at print time -- and a hidden line (the free Remodel row on a job with no remodel tax, which the
    writer takes out itself) does not count as the one that keeps it."""
    assert _states(ran["onlyLine"]["lines"]) == ["kept"]
    assert _states(ran["lastTemplateLine"]["lines"]) == ["line", "kept"]
    assert _states(ran["hiddenDoesNotCount"]["lines"]) == ["line", "kept", "kept"]


def test_ctrl_a_then_delete_takes_out_every_line_but_one(ran):
    """Like Ctrl+A then Delete in a Word text box: one empty line is left for the caret. The
    boundary handler stands down for the same keystroke (it was already taken), so nothing else goes;
    and one Ctrl+Z gives every line back, words and all."""
    got = ran["boxWideDelete"]
    assert _states(got["lines"]) == ["kept", "removed", "removed"]
    assert got["lines"][0]["text"] == "\n"
    assert got["removedCount"] == 2
    assert got["overrides"] == [{"id": 200, "text": "", "kept": True}, {"id": 201, "removed": True},
                                {"id": 202, "removed": True}]
    assert [ln["text"] for ln in ran["undoBoxWide"]["lines"]] == ["Scope: x", "Schedule: y", "Notes: z"]
    assert _states(ran["undoBoxWide"]["lines"]) == ["kept", "kept", "kept"]


def test_a_selection_across_lines_takes_out_what_it_covered_end_to_end(ran):
    """spliceLines, the path Enter, a paste and a typed character over a multi-line selection take:
    the first line keeps what is outside the selection, a line covered end to end goes, and the last
    line, only partly covered, keeps the rest of its words."""
    got = ran["splice"]
    assert _states(got["lines"]) == ["kept", "removed", "kept"]
    assert [got["lines"][0]["text"], got["lines"][2]["text"]] == ["Sco", "tes: z"]


def test_a_selection_from_a_lines_start_into_the_next_takes_that_line_whole(ran):
    """A triple-click, or Shift+Down from the start of a line, selects the line AND its paragraph
    mark: the selection starts at offset 0 and ends at offset 0 of the line below. Word deletes that
    paragraph whole. So does this editor now; it used to leave the line behind empty, the shape of
    the rows Hanz found under Exclusions. The line below keeps every word and takes the caret, and
    the one persist is dispatched from it."""
    got = ran["tripleClick"]
    assert _states(got["lines"]) == ["kept", "removed", "kept"]
    assert got["lines"][2]["text"] == "Notes: z"
    assert got["caret"] == {"line": "202", "at": 0}
    assert got["inputs"] == ["202"]
    assert got["overrides"] == [{"id": 201, "removed": True}]


def test_typing_over_that_selection_or_a_line_that_cannot_go_keeps_the_first_line(ran):
    """Typed text has to land somewhere, and it lands in the first line; a line the template will
    not let go (a clause, a region row) is emptied and kept, as before. Covering every line of a
    selection end to end leaves the first one for the caret, since no later line survives."""
    assert _states(ran["tripleClickTyped"]["lines"]) == ["kept", "kept", "kept"]
    assert [ln["text"] for ln in ran["tripleClickTyped"]["lines"]] == ["Scope: x", "Q", "Notes: z"]
    assert _states(ran["tripleClickKept"]["lines"]) == ["kept", "kept", "kept"]
    assert _states(ran["coverAll"]["lines"]) == ["kept", "removed", "removed"]


def test_an_emptied_line_is_saved_as_an_empty_paragraph_not_a_line_break(ran):
    """An emptied line holds the placeholder `<br>` the browser leaves so the line keeps its height,
    and serializeBlock reads it as a newline. Sent like that, the writer printed a `<w:br/>` and the
    line came out two lines tall in the PDF (see the document test below) while the page drew one.
    Now it goes as `text: ""`, with `runs: []` for a formatted line, and `kept: true`: the line is
    his, emptied and kept (see the Options-gap tests below). A newline that is real text -- a
    pre-change draft's saved entry, replayed as textContent -- goes exactly as it was, so that draft
    prints as it always did."""
    got = ran["emptiedIsEmpty"]
    assert got["placeholder"][1:] == [["BR"], ["BR"]], "the scenario did not build an emptied line"
    assert got["texts"][1:] == ["\n", "\n"], "serializeBlock no longer reads the placeholder as a break"
    assert got["emptied"] == [{"id": 201, "text": "", "kept": True},
                              {"id": 202, "text": "", "runs": [], "kept": True}]
    assert got["legacy"][0] == {"id": 201, "text": "\n"}


def test_the_writer_prints_a_line_break_two_lines_tall_and_an_empty_text_as_one():
    """The document half of the test above, through the real generate path: `text: ""` is the
    paragraph emptied (no break in it); a lone newline puts a `<w:br/>` into it, which Word and
    LibreOffice both lay out as a second line. The writer is unchanged; only what the editor sends
    for a newly emptied line is."""
    tpl = _template("epoxy", "Direct")
    excl = _pick(tpl, "Exclusions:")
    base = _boxes(_docx("epoxy", "Direct"))
    i = base[excl["txbx"]].index(next(t for t in base[excl["txbx"]] if t.startswith("Exclusions:")))

    def para(overrides):
        d = Document(io.BytesIO(_docx("epoxy", "Direct", overrides)))
        return [p for p in list(pw._iter_txbx(d))[excl["txbx"]] if p.tag == qn("w:p")][i]

    for sent in ([{"id": excl["id"], "text": ""}], [{"id": excl["id"], "text": "", "runs": []}]):
        p = para(sent)
        assert _text(p) == "" and next(p.iter(qn("w:br")), None) is None, sent
    legacy = para([{"id": excl["id"], "text": "\n"}])
    assert _text(legacy) == "" and len(list(legacy.iter(qn("w:br")))) == 1


def test_a_reload_shows_the_same_result(ran):
    """The saved `{id, removed: true}` hides the line again when the draft is reopened, and the next
    save sends it again; a saved removal for a line this template will not let go is ignored rather
    than drawn empty -- the same answer the writer gives it."""
    assert _states(ran["reload"]["lines"]) == ["kept", "removed", "kept"]
    assert ran["reload"]["overrides"] == [{"id": 201, "removed": True}]
    assert _states(ran["reloadRefused"]["lines"]) == ["kept", "kept", "kept"]
    assert ran["reloadRefused"]["lines"][1]["text"] == "Clause"


def test_the_ribbon_lets_go_of_a_line_that_is_taken_out(ran):
    assert ran["ribbon"]["idled"] == ["201"]
    assert ran["ribbon"]["stillMarked"] is False


def test_an_emptied_notes_bullet_goes_from_the_textarea(ran):
    """A NOTES bullet's only store is the #notes-text textarea, one line per note, and a blank note
    is a spacer the document prints. Backspace on it takes the line out of the textarea; the bullets
    below move up and are re-indexed; Ctrl+Z puts the blank note back."""
    assert ran["notes"]["textarea"] == "One\nThree"
    assert ran["notes"]["bullets"] == [["0", "One"], ["1", "Three"]]
    assert ran["notesUndo"]["textarea"] == "One\n\nThree"


def test_the_terms_flow_never_loses_a_line(ran):
    assert _states(ran["terms"]["lines"]) == ["kept", "kept", "kept"]


def _rule(selector):
    found = [m.group(1) for m in _re.finditer(r"(?m)^" + _re.escape(selector) + r"\s*\{([^}]*)\}", _CSS)]
    assert found, "%s has no rule in styles.css" % selector
    return "\n".join(found)


def test_an_empty_line_kept_on_the_page_wears_no_edit_bar_and_no_wash():
    """Hanz's screenshot: two empty rows with the red edit bar and the pale yellow wash. A line kept
    empty (a clause, the last line of a box, the one a box-wide Delete leaves) is a blank line, so it
    carries neither. The bar's exception outranks `.tw-block.tw-dirty` by class count, and the wash's
    own rule says `:not(.tw-empty)`, so neither depends on where it sits in the file."""
    assert "box-shadow: none" in _rule(".tw-block.tw-empty.tw-dirty:not(.tw-clause-kept)")
    assert "inset 2px" in _rule(".tw-block.tw-dirty")
    wash = [s for s in _re.findall(r"(?m)^([^{}\n]*tw-fmt-target[^{}\n]*)\{", _CSS)]
    assert [s.strip() for s in wash] == [".tw-block.tw-fmt-target:not(.tw-clause-kept):not(.tw-empty)"]
    assert "display: none !important" in _rule(".tw-block-removed")


def test_a_key_another_handler_already_took_removes_nothing(ran):
    """The Options gap's handler and the box-wide Delete both take Backspace first; the boundary
    handler reads `defaultPrevented` and stands down, so one keystroke is never two edits."""
    assert _states(ran["alreadyTaken"]["lines"]) == ["kept", "kept", "kept"]



# ── lines nobody can see (review of a1aae58, 2026-09-26) ──────────────────────
# A box holds lines the estimator cannot see: the PRICE rows a tax layout hides, the "Options:"
# heading on a bid with no options, the free Remodel row on a job with no remodel tax, the template
# spacer the Options gap replaces. Removing a line used to put the caret INTO the hidden line above
# it, and from there the browser's own Backspace merged paragraphs across it -- deleting the price
# region, the removed-line record and the rows after it.

def _caret(c):
    return (c["line"], c["at"], c["shown"]) if c else None


def test_backspace_under_a_price_block_puts_the_caret_on_the_line_shown_not_the_hidden_heading(ran):
    """Direct PRICE box, no options: base line, the hidden "Options:" heading, three blank lines.
    Backspace on the first blank line takes it out and the caret lands at the END of the base line,
    the line above that is on screen. The heading is not touched, and the next Backspace is the
    browser's own inside a line that shows."""
    got = ran["hiddenAbove"]
    assert got["first"]["prevented"] and got["first"]["removed"] == [202]
    assert _caret(got["first"]["caret"]) == ("base", 42, True)
    assert got["secondPrevented"] is False
    assert got["removedAfter"] == [202]
    assert got["heading"] == {"text": "Options:", "display": "none"}


def test_a_caret_in_a_hidden_line_edits_nothing_and_moves_to_a_line_shown(ran):
    """However it got there, a caret inside a hidden line takes no key: Backspace moves it to the end
    of the line shown above, Delete to the start of the line shown below, and nothing is removed."""
    got = ran["caretInHidden"]
    assert got["back"]["prevented"] and _caret(got["back"]["caret"]) == ("base", 42, True)
    assert got["del"]["prevented"] and _caret(got["del"]["caret"]) == ("202", 0, True)
    assert got["heading"] == "Options:" and got["removed"] == []


def test_the_hidden_remodel_row_and_a_hidden_container_are_stepped_over(ran):
    """GC, no remodel tax: the emptied Total goes on Backspace and the caret lands at the end of the
    Material Sales Tax row, over the hidden Remodel row, which stays as it was. And Delete on an
    empty line skips a line inside a hidden container (the way #options-gap hides its lines)."""
    g = ran["gcHiddenRemodel"]
    assert g["prevented"] and _caret(g["caret"]) == ("200", 27, True)
    assert _states(g["lines"]) == ["kept", "kept", "removed", "kept", "kept"]
    assert g["lines"][1]["display"] == "none" and g["lines"][1]["text"] == "$0 – Remodel Tax"
    h = ran["hiddenBelow"]
    assert h["prevented"] and _caret(h["caret"]) == ("203", 0, True)
    assert _states(h["lines"]) == ["kept", "removed", "kept", "kept"]
    assert h["lines"][2]["text"] == "Gap"


def test_ctrl_a_then_delete_leaves_a_hidden_tax_row_alone_and_undo_does_not_show_it(ran):
    """Ctrl+A in a GC PRICE box with no remodel tax selects the lines on screen: the hidden
    "$0 – Remodel Tax" row is not selected, not emptied, not taken out (no override is sent for it:
    the writer leaves it out by itself, and a saved removal would keep it out even once remodel tax
    applies), and Ctrl+Z does not bring it onto the screen."""
    got = ran["ctrlAHidden"]
    assert got["ctrlAPrevented"] and got["deletePrevented"]
    assert got["selected"] == [True, True, False, True, True]
    remodel = got["afterDelete"]["lines"][2]
    assert (remodel["block"], remodel["removed"], remodel["display"], remodel["text"]) == (
        True, False, "none", "$0 – Remodel Tax")
    assert 202 not in [o["id"] for o in got["afterDelete"]["overrides"]]
    undone = got["afterUndo"][2]
    assert (undone["block"], undone["display"], undone["text"]) == (True, "none", "$0 – Remodel Tax")
    assert [ln["text"] for ln in got["afterUndo"]] == [
        "Base Bid", "$1,200 – Material Sales Tax", "$0 – Remodel Tax", "$1,300 – Total", "\n"]


def test_undo_brings_a_tax_row_back_as_the_tax_rule_now_says(ran):
    """A Remodel row taken out while it showed, and the remodel tax switched off while it was out:
    Ctrl+Z brings it back hidden, as the document prints it. With the tax back on, it comes back
    shown."""
    got = ran["unremoveAsksTheRule"]
    assert got["gone"]["removed"] is True
    assert (got["backHidden"]["block"], got["backHidden"]["display"]) == (True, "none")
    assert (got["backShown"]["block"], got["backShown"]["display"]) == (True, "")


def test_a_kept_line_reloads_kept_and_an_old_empty_entry_as_it_was(ran):
    """`{text: "", kept: true}` is drawn with the placeholder break, so it is still a kept line and
    saves back the same. A `text: ""` saved before the flag reloads as it always did (an empty line
    with no break) and saves back without it -- so both the editor and the writer keep treating it
    the way they did."""
    k = ran["keptReload"]["kept"]
    assert k["children"] == ["BR"] and k["keptEmpty"] is True
    assert k["overrides"] == [{"id": 201, "text": "", "kept": True}]
    old = ran["keptReload"]["legacy"]
    assert old["children"] == [] and old["keptEmpty"] is False
    assert old["overrides"] == [{"id": 201, "text": ""}]


# What an editor line is, as a selector's last part names it: the template paragraphs, the computed
# rows, the notes bullets, the typed price lines, the gap's blank lines, the staging rows by id.
_LINE_MARKS = ("tw-block", "tw-line-edit", "tw-note-edit", "tw-priceline", "tw-po-extra", "tw-gap-line",
               "#options-", "-row")


def test_only_two_class_rules_hide_a_line():
    """lineShown knows a line is hidden by its inline `display: none`, the `hidden` attribute, and
    two classes. A new stylesheet rule that hides an editor line would slip past it, and the caret, a
    Ctrl+A and a Backspace could land on a line nobody can see again: add it to lineShown too."""
    css = _re.sub(r"/\*.*?\*/", "", _CSS, flags=_re.S)
    hiding = set()
    for sel, body in _re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if not _re.search(r"display\s*:\s*none", body):
            continue
        for one in sel.split(","):
            last = _re.split(r"[\s>+~]+", one.strip())[-1]
            if any(m in last for m in _LINE_MARKS):
                hiding.add(one.strip())
    assert hiding == {".tw-block-removed", ".tw-block.tw-gap-absorbed"}, sorted(hiding)


# ── a line emptied and KEPT above the Options gap prints as the editor draws it ──
def _above_heading(docx_bytes):
    """The PRICE box's lines from the last words above the Options heading down to the heading."""
    for box in _boxes(docx_bytes):
        for i, t in enumerate(box):
            if t.strip().lower().startswith("options"):
                j = i - 1
                while j >= 0 and not box[j].strip():
                    j -= 1
                return box[j:i + 1]
    raise AssertionError("no Options heading printed")


@pytest.mark.parametrize("work_type,audience,token,kept_prints,old_prints", [
    # Gyp: the free "1 Mobilization to Site." line, under the Total and the template spacer. Kept:
    # the spacer, the kept line, the gap's two. The editor draws the same four (keptAboveGap: the
    # line shown, the spacer below it absorbed, two gap lines, over the template's spacer above).
    ("gyp", "Direct", "mobilizations_line",
     ["$36,763 – Total", "", "", "", "", "Options:"], ["$36,763 – Total", "", "", "Options:"]),
    # GC Resinous: the free Total row, over the template spacer the gap replaces. Kept: the kept
    # line and the gap's two; the editor draws the same three (gcKept: the Total shown, the spacer
    # absorbed, two gap lines).
    ("epoxy", "GC", "total_formatted",
     ["$0.00 – Material Sales Tax", "", "", "", "Options & Unit Prices"],
     ["$0.00 – Material Sales Tax", "", "", "Options & Unit Prices"]),
])
def test_a_line_emptied_and_kept_above_the_gap_prints_and_is_not_taken_into_it(
        work_type, audience, token, kept_prints, old_prints):
    """The review's case: on Gyp the estimator deletes the words of "1 Mobilization to Site." and
    keeps the line. The editor draws that empty line (and the template spacer above it) over the
    gap's two lines; the writer took it into the gap, spacer and all, and printed two lines fewer.
    Sent `kept`, it stops the gap there, as the editor does: it prints as one empty line, the lines
    above it print, and the gap is still its count.

    `text: ""` without the flag -- a draft saved before it -- prints exactly as it did: taken in."""
    tpl = _template(work_type, audience)
    b = next(x for x in _box_blocks(tpl) if token in x["text"] and x["in_block"] is None)
    opts = {"price_lines": [{"label": "Add dye", "amount": 1500}]}
    kept = _above_heading(_docx(work_type, audience, [{"id": b["id"], "text": "", "kept": True}], **opts))
    old = _above_heading(_docx(work_type, audience, [{"id": b["id"], "text": ""}], **opts))
    assert kept == kept_prints
    assert old == old_prints


def test_the_sanitizer_carries_kept_only_when_it_is_true():
    """`kept` travels through the generate route's sanitizer to the writer (the document test above
    goes through it), strictly True: anything else leaves the entry as a plain `text: ""`."""
    got = main._sanitize_paragraph_overrides([
        {"id": 1, "text": "", "kept": True}, {"id": 2, "text": "", "kept": "yes"},
        {"id": 3, "text": "", "kept": 1}, {"id": 4, "text": ""}])
    assert got == [{"id": 1, "text": "", "kept": True}, {"id": 2, "text": ""},
                   {"id": 3, "text": ""}, {"id": 4, "text": ""}]


def test_one_undo_history_carries_a_removed_line_and_the_price_lines(ran):
    """The merge with #569 put two things on every undo entry of a PRICE box: the removed template
    lines (this branch) and the typed price lines' maps with the Options gap's count (#569). A line
    taken out, then the gap given one line more: the first Ctrl+Z puts the count back (and redraws
    the price block from it) and leaves the line out; the second brings the line back."""
    got = ran["undoBoth"]
    assert got["afterRemove"] == {"removed": [201], "gap": 2}
    assert got["first"]["gap"] == 2 and got["first"]["removed"] == [201]
    assert got["first"]["redraws"] == ["redraw", "save"]
    assert got["second"] == {"removed": [], "gap": 2}


def test_a_kept_line_leaves_no_mark_of_ours_in_either_file():
    """`kept` is remembered on the Document (proposal_writer._kept_lines), not written into the XML:
    a `w:` attribute of our own is invalid OOXML, and the cover letter fills through the same
    override pass without ever reaching the Options gap, which is where a mark would be taken out
    again -- the letter is then merged in front of the proposal, mark and all."""
    import zipfile
    import cover_letter_writer as clw
    tpl = _template("gyp", "Direct")
    b = next(x for x in _box_blocks(tpl) if "mobilizations_line" in x["text"] and x["in_block"] is None)
    blob = _docx("gyp", "Direct", [{"id": b["id"], "text": "", "kept": True}],
                 price_lines=[{"label": "Add dye", "amount": 1500}])
    xml = zipfile.ZipFile(io.BytesIO(blob)).read("word/document.xml").decode("utf-8")
    assert not _re.search(r"w:tw[A-Za-z]+=", xml)
    letter = clw.fill_cover_letter(work_type="epoxy", audience="Direct", values=dict(_VALS),
                                   paragraph_overrides=[{"id": i, "text": "", "kept": True}
                                                        for i in range(60)])
    xml = zipfile.ZipFile(io.BytesIO(letter)).read("word/document.xml").decode("utf-8")
    assert not _re.search(r"w:tw[A-Za-z]+=", xml)
