"""Kyle's last two complaints about the proposal document editor, 2026-08-20.

Verbatim:
    "I cant dletet the bullet points"
    "There is indentation in this but I cant remove tat if I want to to be aligned on the
     polished concrete?"

Both are Word PARAGRAPH properties. The editor could always rewrite a paragraph's RUNS — text,
bold/italic/underline, size — and could never touch the paragraph's own `w:numPr` (its bullet) or
`w:ind` (its indentation), which is where both complaints live. Three seams had to be joined for
one press of a toolbar button to reach a customer's .docx, and every one of them is a place this
project has already been burned:

  1. `main._sanitize_paragraph_overrides` emitted only {id, text[, runs]}. A `para` field the
     browser added would have been dropped one function before the writer. That is not a no-op:
     the editor shows the change and the draft remembers it, so the estimator gets positive
     confirmation of an edit the customer's document never received. The same failure the
     comment above `_SYSTEM_OVERRIDE_FIELDS` was written about.

  2. The browser could not READ the current state. Without `bullet` / `indent` / `locked` per
     block, the toolbar cannot draw a toggle that reflects reality — and cannot know to hide
     itself on a numbered TERMS AND CONDITIONS clause, where dropping one item's numbering
     silently renumbers every clause below it in legal boilerplate.

  3. `_BLOCK_SCHEMA_VERSION`. The block dict grew a field; the template ETag is otherwise keyed
     on the .docx mtime, so a browser would 304 and keep replaying a shape with no `locked` in
     it against code that now offers un-bulleting.

THE SUBTLE PART, and the reason these are XML assertions rather than "did it not crash": a WORK
row carries NO `w:ind` of its own. Its indentation comes from the numbering level (numId 4 ->
`w:ind w:left="288" w:hanging="288"`). Remove `w:numPr` alone and the level's indent leaves with
it and the line JUMPS. And the inverse, which is the defect this pass found: writing the
paragraph's own `w:left` while it is still bulleted drops the `w:hanging` with it and moves the
red square from in front of the words to inline with them. `apply_para_props` has to do neither.
"""
import io
import json
import pathlib
import shutil
import subprocess

import docx
import pytest
from docx.oxml.ns import qn
from fastapi.testclient import TestClient

import main
import proposal_writer as pw

client = TestClient(main.app)

TEMPLATE = pw.TEMPLATES_ROOT / "Direct" / "XX.XX TREADWELL EPOXY PROPOSAL - New Direct.docx"
FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "doc-editor-labels-harness.js"
CSS = (FRONTEND / "styles.css").read_text(encoding="utf-8")

BASE_VALUES = {
    "job_name": "Test Job", "project_name": "Test Job", "city_state": "Olathe, KS",
    "scope_notes": "surface prep and coat", "schedule_notes": "four working days",
    "exclusions": "striping", "work_notes": "keep off for 24 hours",
}


# ── reading paragraph XML ────────────────────────────────────────────────────
def _has_numpr(p_elem) -> bool:
    ppr = p_elem.find(qn("w:pPr"))
    return ppr is not None and ppr.find(qn("w:numPr")) is not None


def _ind(p_elem):
    """The paragraph's OWN `w:ind`, as a plain dict, or None when it states none. Deliberately
    not the resolved value: what these tests are about is which of the paragraph and its list
    level is doing the indenting."""
    ppr = p_elem.find(qn("w:pPr"))
    ind = ppr.find(qn("w:ind")) if ppr is not None else None
    if ind is None:
        return None
    return {k.split("}")[-1]: v for k, v in ind.attrib.items()}


def _template():
    return docx.Document(str(TEMPLATE))


def _by_id(d):
    return {idx: p_elem for idx, _k, p_elem, _ib, _t, _x in pw.iter_editable_blocks(d)}


def _walk(d):
    return list(pw.iter_editable_blocks(d))


def _free_row_id(prefix):
    """The id of the free (non-region) WORK row whose text starts with `prefix`. Looked up by
    text, never hardcoded, so a re-annotated template fails loudly instead of quietly editing
    the wrong paragraph."""
    for idx, _k, _p, in_block, text, _x in _walk(_template()):
        if in_block is None and text.strip().startswith(prefix):
            return idx
    raise AssertionError("no free paragraph starts with %r" % (prefix,))


def _numbered_terms_id():
    """A TERMS AND CONDITIONS clause: `in_block` None (so the override channel CAN reach it) and
    on a decimal list (so it must refuse)."""
    d = _template()
    for idx, _k, p_elem, in_block, _t, _x in pw.iter_editable_blocks(d):
        if in_block is None and pw._para_ordered_list(d, p_elem):
            return idx
    raise AssertionError("the numbered Terms list is gone from the template")


def _generate(overrides):
    return docx.Document(io.BytesIO(pw.fill_proposal(
        work_type="epoxy", audience="Direct", values=dict(BASE_VALUES),
        paragraph_overrides=overrides)))


def _rows(d):
    """Generated document as {stripped text: (has_numPr, own w:ind)} for the non-blank rows."""
    out = {}
    for _i, _k, p_elem, _ib, text, _x in pw.iter_editable_blocks(d):
        t = (text or "").strip()
        if t and t not in out:
            out[t] = (_has_numpr(p_elem), _ind(p_elem))
    return out


# ══ the fixture facts, re-derived from Kyle's file ═══════════════════════════
# If he re-authors the template these fail first and say what moved, instead of leaving the
# feature quietly wrong.
def test_the_work_rows_are_bulleted_by_a_numbering_level_that_owns_their_indent():
    """THE WHOLE SUBTLETY, stated as a fact about the file. The row has no `w:ind`; 288 twips of
    indent and a 288-twip hanging come from numId 4. That is why removing the bullet has to copy
    the level's indent onto the paragraph, and why writing an indent while the bullet is still on
    has to leave the level alone."""
    d = _template()
    ids = _by_id(d)
    level = pw._numbering_levels(d).get(("4", "0"))
    # `text` is the Wingdings private-use glyph the WORK level prints, which is why the preview
    # draws its own square rather than the level's character: no browser font has U+F0A7.
    assert level == {"fmt": "bullet", "text": "\uf0a7", "start": 1,
                     "ind": {"left": "288", "hanging": "288"}}, level
    for label in ("Scope:", "Schedule:", "Exclusions:", "Notes:"):
        p_elem = ids[_free_row_id(label)]
        assert _has_numpr(p_elem), label
        assert _ind(p_elem) is None, (label, _ind(p_elem))
        # `marker` is empty on a bullet row: the two fields are the two halves of "what shows in
        # front of the text" and are never both set.
        assert pw.para_props(d, p_elem) == {"bullet": True, "indent": 288, "locked": False,
                                            "marker": ""}


def test_the_terms_clauses_are_a_decimal_list_the_override_channel_can_reach():
    """Which is exactly why `locked` exists. These paragraphs are ordinary body paragraphs
    (`in_block` None), so nothing else in the pipeline would stop the editor renumbering the
    contract."""
    d = _template()
    p_elem = _by_id(d)[_numbered_terms_id()]
    assert pw._num_fmt(d, p_elem) == "decimal"
    props = pw.para_props(d, p_elem)
    assert props["locked"] is True
    assert props["bullet"] is False


# ══ the bullet ═══════════════════════════════════════════════════════════════
def test_one_bullet_removed_leaves_its_neighbours_bulleted():
    """Kyle's first complaint, end to end. The Schedule row loses its `w:numPr` in the generated
    .docx; Scope, Exclusions and Notes keep theirs."""
    sched = _free_row_id("Schedule:")
    rows = _rows(_generate([{"id": sched, "para": {"bullet": False, "indent": 288}}]))
    assert rows["Schedule:  four working days"][0] is False
    for other in ("Scope:  surface prep and coat", "Exclusions:  striping",
                  "Notes:  keep off for 24 hours"):
        assert rows[other][0] is True, other


def test_the_de_bulleted_row_does_not_move():
    """The one that cannot be checked by eye. The row inherited its 288-twip indent from the
    numbering level, so dropping `w:numPr` alone would drop the indent with it and the line
    would jump left. This is the payload the toolbar actually sends — the bullet off, and the
    indent it was already sitting at — and 288 twips has to survive it as a real `w:ind`."""
    sched = _free_row_id("Schedule:")
    rows = _rows(_generate([{"id": sched, "para": {"bullet": False, "indent": 288}}]))
    has_num, ind = rows["Schedule:  four working days"]
    assert has_num is False
    assert ind is not None, "the bullet went and took the indentation with it"
    assert ind.get("left") == "288", ind
    assert ind.get("start") == "288", ind
    # A hanging indent with no bullet in front of it prints as a first line further left than
    # the rest of its own paragraph.
    assert "hanging" not in ind, ind


def test_removing_only_the_bullet_copies_the_level_indent_by_itself():
    """The same guarantee with NO `indent` in the request, which is what `_remove_bullet_keep_indent`
    exists for and the only shape that isolates it: with an indent alongside, the indent branch
    would write 288 anyway and a broken bullet-removal would still look right."""
    d = _template()
    p_elem = _by_id(d)[_free_row_id("Schedule:")]
    assert _ind(p_elem) is None                       # the level owns the indent, not the row
    assert pw.apply_para_props(d, p_elem, {"bullet": False}) == 1
    assert _has_numpr(p_elem) is False
    assert _ind(p_elem) == {"left": "288", "start": "288"}, _ind(p_elem)
    assert pw._effective_left_tw(d, p_elem) == 288


def test_switching_the_bullet_back_on_hands_the_indent_back_to_the_list_level():
    """THE DEFECT THIS PASS FOUND. `_add_bullet` removes the explicit `w:ind` a de-bullet wrote,
    for a documented reason: the level's `w:left`/`w:hanging` pair is what puts the square ahead
    of the words. The `indent` arriving in the same request then wrote its own `w:left` straight
    back, with no hanging — printing the square inline with the text. `apply_para_props` now
    drops the paragraph's own left indent when the level already provides exactly that value."""
    d = _template()
    p_elem = _by_id(d)[_free_row_id("Schedule:")]
    pw.apply_para_props(d, p_elem, {"bullet": False, "indent": 288})
    assert _ind(p_elem) == {"left": "288", "start": "288"}
    pw.apply_para_props(d, p_elem, {"bullet": True, "indent": 288})
    assert _has_numpr(p_elem)
    assert _ind(p_elem) is None, (
        "the paragraph is stating its own left indent again, so it has no hanging indent and "
        "the red square prints in the middle of the line: %r" % (_ind(p_elem),))
    assert pw.para_props(d, p_elem) == {"bullet": True, "indent": 288, "locked": False,
                                        "marker": ""}


def test_an_unchanged_paragraph_state_changes_nothing_at_all():
    """The editor sends the state it is showing, which for most paragraphs is the template's own.
    That request has to be a no-op down to the XML — otherwise every bulleted row the estimator
    merely looked at would gain an explicit indent and lose its hanging one."""
    d = _template()
    p_elem = _by_id(d)[_free_row_id("Scope:")]
    assert pw.apply_para_props(d, p_elem, {"bullet": True, "indent": 288}) == 0
    assert _has_numpr(p_elem)
    assert _ind(p_elem) is None


# ══ the indent ═══════════════════════════════════════════════════════════════
def test_outdent_reaches_the_margin_and_indent_puts_it_back():
    """Kyle's second complaint, as the twips that actually travel. Zero really is zero — "aligned
    on the polished concrete" means flush with the rows around it, not one level in."""
    sched = _free_row_id("Schedule:")
    flush = _rows(_generate([{"id": sched, "para": {"bullet": False, "indent": 0}}]))
    has_num, ind = flush["Schedule:  four working days"]
    assert has_num is False
    assert (ind.get("left"), ind.get("start")) == ("0", "0"), ind

    back = _rows(_generate([{"id": sched, "para": {"bullet": False, "indent": 288}}]))
    assert back["Schedule:  four working days"][1].get("left") == "288"


def test_indent_steps_round_trip_through_apply_para_props():
    """The same arithmetic at unit level, one press at a time, so a failure says WHICH press."""
    d = _template()
    p_elem = _by_id(d)[_free_row_id("Schedule:")]
    seen = []
    for want in (0, 288, 576, 288, 0):
        pw.apply_para_props(d, p_elem, {"bullet": False, "indent": want})
        seen.append(pw._effective_left_tw(d, p_elem))
    assert seen == [0, 288, 576, 288, 0]


def test_an_out_of_range_indent_is_clamped_not_rejected():
    """A clamp still does what the estimator asked as far as the page can go; a rejection would
    silently do nothing. Negative values and junk cannot reach the XML either way."""
    assert pw.sanitize_para_props({"indent": 99999})["indent"] == pw._INDENT_MAX_TW
    assert pw.sanitize_para_props({"indent": -50})["indent"] == 0
    assert pw.sanitize_para_props({"indent": "288"})["indent"] == 288
    assert pw.sanitize_para_props({"indent": True}) == {}      # bool is an int subclass
    assert pw.sanitize_para_props({"indent": "banana"}) == {}
    assert pw.sanitize_para_props("nope") == {}


# ══ the contract ═════════════════════════════════════════════════════════════
def test_a_numbered_terms_clause_is_reported_locked_and_refused():
    """Prove the contract cannot be renumbered by this feature. `para_props` says `locked` so the
    editor never draws the controls, and `apply_para_props` refuses anyway — the editor is not
    the only caller, and a hand-built request must not get further than the UI would."""
    d = _template()
    p_elem = _by_id(d)[_numbered_terms_id()]
    assert pw.para_props(d, p_elem)["locked"] is True
    before_num, before_ind = _has_numpr(p_elem), _ind(p_elem)
    assert pw.apply_para_props(d, p_elem, {"bullet": False, "indent": 0}) == 0
    assert _has_numpr(p_elem) is before_num
    assert _ind(p_elem) == before_ind


def test_the_generated_contract_still_has_every_clause_on_its_numbered_list():
    """The whole-document version of the same claim: a generate carrying a para override aimed at
    a Terms clause leaves the clause count and their numbering untouched."""
    clause = _numbered_terms_id()

    def clause_count(d):
        return sum(1 for _i, _k, p, _b, _t, _x in pw.iter_editable_blocks(d)
                   if pw._para_num_ref(p) == ("5", "0"))

    plain = clause_count(_generate([]))
    attacked = clause_count(_generate([{"id": clause, "para": {"bullet": False, "indent": 0}}]))
    assert plain > 10, plain
    assert attacked == plain


# ══ an emptied row ═══════════════════════════════════════════════════════════
def test_an_emptied_bulleted_row_prints_no_orphan_bullet():
    """The on-screen half of this is a CSS rule (`.tw-block.tw-empty.tw-li::before`), and it can
    only be honest if the document agrees. A blank `{{#notes}}` item already dropped its bullet
    ("a lone empty bullet dot"); a WORK row emptied by hand came through the paragraph-override
    channel instead and kept its numbering, so the .docx printed a red square with nothing after
    it while the preview showed none."""
    sched = _free_row_id("Schedule:")
    d = _generate([{"id": sched, "text": ""}])
    blanks = [(idx, _has_numpr(p)) for idx, _k, p, ib, text, _x in pw.iter_editable_blocks(d)
    # SCOPED TO BULLET LISTS, and the scope is the point. The first version asserted that NO
    # blank in_block=None paragraph carried numbering anywhere - which was satisfied partly BY
    # a defect: the unguarded strip was also removing numbers from the numbered Terms clauses,
    # so a test written to protect the preview was quietly blessing a renumbered contract. A
    # guard-rail pointing the wrong way is worse than none: it certifies what it should catch.
              if ib is None and not (text or "").strip()
                 and not pw._para_ordered_list(d, p)]
    assert blanks, "no blank paragraph in the generated document"
    assert not any(has for _idx, has in blanks), \
        "a blank paragraph still carries numbering: %r" % (blanks,)


def test_an_explicit_bullet_on_outranks_the_emptied_row_tidy_up():
    """The estimator's own toggle wins, and the row stays on ITS OWN list.

    Not mutation-caught, and worth saying so: with the guard removed the row is stripped and
    then re-bulleted from a sibling's numbering, and in this template that sibling happens to be
    on numId 4 as well — so the outcome is the same here. What the guard buys is that the row is
    never re-homed onto a neighbouring list at all, which is a claim about the mechanism rather
    than about this one file."""
    sched = _free_row_id("Schedule:")
    d = _template()
    p_elem = _by_id(d)[sched]
    n = pw._apply_paragraph_overrides(
        d, [{"id": sched, "text": "", "para": {"bullet": True, "indent": 288}}])
    assert n == 1
    assert _has_numpr(p_elem), "an explicit bullet:true was overridden by the blank-row tidy-up"
    assert pw._para_num_ref(p_elem) == ("4", "0"), pw._para_num_ref(p_elem)


# ══ seam 1: main.py must not drop the field ══════════════════════════════════
def test_the_sanitizer_carries_para_through():
    out = main._sanitize_paragraph_overrides([
        {"id": 5, "text": "Scope: x", "para": {"bullet": False, "indent": 0}},
    ])
    assert out == [{"id": 5, "text": "Scope: x", "para": {"bullet": False, "indent": 0}}]


def test_a_para_only_entry_survives_the_sanitizer():
    """A bullet switched off is not an edit to the words, so the editor sends `para` with NO
    text. The sanitizer used to drop any entry without text — which would have made this whole
    feature a lie on screen. It must not send text either: a `text` override rebuilds the
    paragraph as one plain run and would throw away the template's bold lead-in."""
    out = main._sanitize_paragraph_overrides([{"id": 9, "para": {"bullet": False}}])
    assert out == [{"id": 9, "para": {"bullet": False}}]
    assert "text" not in out[0]


def test_the_sanitizer_still_drops_an_entry_with_neither_text_nor_para():
    """The pre-existing contract, unchanged: `{id: 7}` alone means nothing and is dropped."""
    assert main._sanitize_paragraph_overrides([{"id": 7}]) == []
    assert main._sanitize_paragraph_overrides([{"id": 7, "para": {}}]) == []
    assert main._sanitize_paragraph_overrides([{"id": 7, "para": "junk"}]) == []


def test_para_rides_along_with_run_formatting_too():
    """Both channels on one entry: the estimator bolded a word AND removed the bullet."""
    out = main._sanitize_paragraph_overrides([{
        "id": 4, "text": "Scope: x", "runs": [{"text": "Scope: x", "bold": True}],
        "para": {"bullet": False, "indent": 0},
    }])
    assert out[0]["runs"] == [{"text": "Scope: x", "bold": True}]
    assert out[0]["para"] == {"bullet": False, "indent": 0}


def test_an_override_saved_before_this_change_still_applies():
    """Every draft in flight has {id, text} entries with no `para`. They must keep working
    exactly as they did — same text in the document, same bullet, same indentation."""
    scope = _free_row_id("Scope:")
    rows = _rows(_generate([{"id": scope, "text": "Scope:  hand-typed value"}]))
    assert "Scope:  hand-typed value" in rows
    has_num, ind = rows["Scope:  hand-typed value"]
    assert has_num is True, "a legacy text-only override lost the paragraph's bullet"
    assert ind is None, "a legacy text-only override gained an indent it never asked for"


def test_generate_survives_malformed_para_values():
    """Untrusted request bodies reach this. Nothing here may raise."""
    scope = _free_row_id("Scope:")
    junk = [
        {"id": scope, "para": "nope"},
        {"id": scope, "para": []},
        {"id": scope, "para": {"bullet": "yes", "indent": {}}},
        {"id": scope, "para": {"indent": float("nan")}},
        {"id": scope, "text": "Scope:  fine", "para": {"bullet": False, "indent": 288}},
    ]
    rows = _rows(_generate(main._sanitize_paragraph_overrides(junk)))
    assert "Scope:  fine" in rows


# ══ seam 2: the browser has to be able to READ the state ═════════════════════
# The keys the frontend's paraBase() reads. Grown without the version bump, a browser replaying
# a cached response has no `locked` and would happily offer to un-bullet a contract clause.
_BLOCK_KEYS_AT_V6 = {
    "id", "kind", "text", "style", "in_block", "in_txbx", "txbx",
    "align", "list", "price_flat", "para", "runs",
}
# The keys INSIDE `para`. Asserted separately because the block dict's own key set does not move
# when a nested one grows, and v6 grew a nested one: `marker`. A browser holding a v5 response has
# every block's `para` without it, and the renderer's fallback for a marker-less list paragraph is
# the red square that was the bug.
_PARA_KEYS_AT_V6 = {"bullet", "indent", "locked", "marker"}


@pytest.fixture
def epoxy_blocks():
    # Function-scoped deliberately: conftest's `_bypass_auth` is autouse but rides
    # `monkeypatch`, which is function-scoped, so a module-scoped fixture runs BEFORE the
    # auth bypass exists and gets a 401.
    r = client.get("/api/proposal-template?work_type=epoxy&audience=Direct")
    assert r.status_code == 200, r.text
    return r.json()["blocks"]


def test_the_endpoint_reports_para_for_every_block(epoxy_blocks):
    assert epoxy_blocks
    for b in epoxy_blocks:
        p = b.get("para")
        assert isinstance(p, dict), b["id"]
        assert isinstance(p["bullet"], bool)
        assert isinstance(p["locked"], bool)
        assert isinstance(p["indent"], int) and p["indent"] >= 0


def test_the_endpoint_marks_the_work_rows_editable_and_the_terms_locked(epoxy_blocks):
    """The two answers the toolbar cannot function without."""
    by_id = {b["id"]: b for b in epoxy_blocks}
    sched = by_id[_free_row_id("Schedule:")]
    assert sched["para"] == {"bullet": True, "indent": 288, "locked": False, "marker": ""}
    clause = by_id[_numbered_terms_id()]
    assert clause["para"]["locked"] is True
    # `list` is True for the contract clauses too, so it could never have been the guard.
    assert clause["list"] is True
    # And it is not what the renderer reads any more: the clause reports the NUMBER it prints.
    assert clause["para"]["bullet"] is False
    assert clause["para"]["marker"] == "1."


def test_block_schema_version_was_bumped_for_the_new_field(epoxy_blocks):
    """`/api/proposal-template`'s ETag is keyed on the .docx mtime plus this constant, so a CODE
    change to the block dict is invisible to a browser's cache without a bump: it 304s and
    replays the old shape against the new frontend."""
    keys = set(epoxy_blocks[0])
    assert "para" in keys
    assert keys == _BLOCK_KEYS_AT_V6, (
        "the block dict shape changed — bump main._BLOCK_SCHEMA_VERSION and update "
        "_BLOCK_KEYS_AT_V6 in the same commit")
    for b in epoxy_blocks:
        assert set(b["para"]) == _PARA_KEYS_AT_V6, (b["id"], b["para"])
    assert main._BLOCK_SCHEMA_VERSION == "6", (
        "`para` includes `marker` but _BLOCK_SCHEMA_VERSION is %r; a browser holding a v5 "
        "response has no marker for any block, so it paints a red square in front of all 27 "
        "numbered contract clauses" % (main._BLOCK_SCHEMA_VERSION,))


def test_the_schema_version_is_in_the_template_etag():
    """Not just present as a constant — actually load-bearing for the cache key."""
    r = client.get("/api/proposal-template?work_type=epoxy&audience=Direct")
    etag = r.headers.get("etag") or ""
    assert etag
    assert client.get("/api/proposal-template?work_type=epoxy&audience=Direct",
                      headers={"if-none-match": etag}).status_code == 304
    stale = etag.replace("s%s" % main._BLOCK_SCHEMA_VERSION, "s4")
    if stale != etag:
        assert client.get("/api/proposal-template?work_type=epoxy&audience=Direct",
                          headers={"if-none-match": stale}).status_code == 200


# ══ the id space ═════════════════════════════════════════════════════════════
def test_the_block_id_space_and_count_are_unchanged_by_this_feature():
    """A saved paragraph_override is keyed by a POSITION in `iter_editable_blocks`. This feature
    reads paragraph properties and writes `w:pPr`; it must not add, remove or reorder a block, or
    every override on every draft in flight lands on a different paragraph."""
    walk = _walk(_template())
    ids = [i for i, _k, _p, _b, _t, _x in walk]
    assert ids == list(range(len(ids)))
    assert len(ids) == 172, (
        "the Direct epoxy template's block count changed to %d — every saved paragraph_override "
        "id is now suspect" % (len(ids),))
    starts = [i for i, _k, _p, _b, t, _x in walk if t.strip() == "{{#system}}"]
    assert starts == [110], starts


def test_applying_para_props_does_not_change_the_walk():
    """The strongest form: apply the controls to a real row, then re-walk the same document. Same
    count, same ids, same order — `w:pPr` surgery cannot be allowed to split or drop a
    paragraph."""
    d = _template()
    before = [(i, t) for i, _k, _p, _b, t, _x in pw.iter_editable_blocks(d)]
    p_elem = _by_id(d)[_free_row_id("Schedule:")]
    pw.apply_para_props(d, p_elem, {"bullet": False, "indent": 0})
    pw.apply_para_props(d, p_elem, {"bullet": True, "indent": 288})
    after = [(i, t) for i, _k, _p, _b, t, _x in pw.iter_editable_blocks(d)]
    assert after == before


# ══ seam 3: the toolbar, executed ════════════════════════════════════════════
# Under node, not asserted against source text. Whether the bullet button reads ON, whether a
# locked paragraph is offered anything, and whether the state survives a reload are behaviours of
# several functions agreeing — and this repo has already paid for the alternative: on 2026-08-12
# `STAGE_CREATED` shipped unbound with every source assertion green and took the board down.
@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_toolbar_offers_all_three_controls_on_a_work_row(ran):
    """And each one reflects the paragraph's REAL state: the bullet button reads pressed because
    the row is bulleted, and outdent is live because the row is genuinely indented."""
    bar = ran["paraBarWork"]
    assert ran["paraBarWorkNow"] == {"bullet": True, "indent": 288, "locked": False}
    assert bar["bullet"]["on"] is True
    assert bar["bullet"]["pressed"] == "true"
    for key in ("bullet", "outdent", "indent"):
        assert bar[key]["visibility"] == "", key
        assert bar[key]["disabled"] is False, key
        assert bar[key]["label"], key            # every control is named for a screen reader
    assert bar["outdent"]["title"] == "Less indent (moves left, all the way to the margin)"


def test_a_locked_paragraph_is_offered_nothing(ran):
    """A numbered TERMS clause. Not a button that merely looks disabled — that still invites the
    click and still says the feature applies here. It does not.

    `visibility: hidden` since 2026-08-24, where it used to be `display: none`. Kyle asked for the
    bar to become "static like a ribbon in a word document", and a row that reflowed every time
    the caret crossed from a WORK row to a contract clause would not be static — Reset would jump
    out from under the pointer. visibility keeps the space, and unlike `opacity: 0` it still takes
    the element out of hit-testing and out of the tab order. `disabled` is asserted alongside it
    because renderFmtBar sets both: if that rule ever loses a cascade the refusal has to survive
    anyway."""
    bar = ran["paraBarLocked"]
    for key in ("bullet", "outdent", "indent", "sep"):
        assert bar[key]["visibility"] == "hidden", key
        assert bar[key]["display"] == "", (
            "%s is hidden with `display`, so the ribbon reflows when the caret reaches a locked "
            "clause" % key)
    for key in ("bullet", "outdent", "indent"):
        assert bar[key]["disabled"] is True, key
    # And no stale pressed state waiting on the hidden button: the ribbon is one memoized element
    # that lives for the whole session, so "on" from the last WORK row would otherwise stay there.
    assert bar["bullet"]["on"] is False
    assert bar["bullet"]["pressed"] == "false"
    # Run formatting is untouched: bold on a contract clause is fine, renumbering is not.
    assert bar["bold"]["visibility"] == ""
    assert bar["bold"]["disabled"] is False
    acted = ran["paraLockedAction"]
    assert acted["bulletPressed"] is False and acted["outdentPressed"] is False
    assert acted["el"] == {"li": True, "marginLeft": "", "paddingLeft": "", "dirty": False}
    assert acted["patch"] is None


def test_a_block_with_no_para_metadata_is_offered_nothing_either(ran):
    """The pre-v5 cached-response case. With no `locked` we cannot tell a WORK row from a
    contract clause, so the honest degradation is no controls at all."""
    for key in ("bullet", "outdent", "indent", "sep"):
        assert ran["paraBarNoMeta"][key]["visibility"] == "hidden", key
    assert ran["paraNoMetaAction"] is False


def test_the_bullet_comes_off_one_row_and_its_neighbours_keep_theirs(ran):
    """Kyle's first complaint, in the browser. The row loses `.tw-li` (so the red square goes),
    keeps its 14.4pt of margin (288 twips — the text does NOT move), and the rows above and below
    are untouched."""
    got = ran["bulletOff"]
    assert got["target"]["li"] is False
    assert got["target"]["marginLeft"] == "14.4pt"
    assert got["target"]["paddingLeft"] == "0"
    assert got["before"] == {"li": True, "marginLeft": "", "paddingLeft": "", "dirty": False}
    assert got["after"] == {"li": True, "marginLeft": "", "paddingLeft": "", "dirty": False}
    assert got["now"] == {"bullet": False, "indent": 288, "locked": False}
    # `para` and NO text: the words were not touched, and a text override would flatten the
    # template's own bold lead-in into one plain run.
    assert got["payload"] == [{"id": 116, "para": {"bullet": False, "indent": 288}}]
    # A paragraph property is not a text edit, so the block does not go tw-dirty and
    # refreshDocumentFills keeps re-substituting its {{token}} values.
    assert got["target"]["dirty"] is False


def test_outdent_reaches_zero_in_the_browser_too_and_stops_there(ran):
    """Aligned on the polished concrete means flush, not one level in. And the floor holds: a
    second press cannot go negative, and the button says so."""
    steps = ran["indentSteps"]
    assert steps["zero"]["now"]["indent"] == 0
    assert steps["zero"]["el"]["marginLeft"] == "0pt"
    assert steps["zero"]["payload"] == [{"id": 116, "para": {"bullet": True, "indent": 0}}]
    assert steps["floored"]["now"]["indent"] == 0
    assert steps["floored"]["bar"]["outdent"]["disabled"] is True
    assert steps["floored"]["bar"]["indent"]["disabled"] is False
    # Back to where the template had it — and then the override disappears entirely, because it
    # matches the template again.
    assert steps["back"]["now"]["indent"] == 288
    assert steps["back"]["payload"] == []


def test_a_paragraph_nobody_changed_ships_nothing(ran):
    """Merely focusing a paragraph must not enrol it. The generated .docx for an untouched
    document has to be the file it was before this feature existed."""
    got = ran["untouched"]
    assert got["payload"] == []
    assert got["patches"] == [None, None, None]
    assert got["el"] == {"li": True, "marginLeft": "", "paddingLeft": "", "dirty": False}


def test_the_control_remembers_what_you_set_across_a_reload(ran):
    """Set, persist through the real schedulePersistOverrides, drop the live state the way a page
    reload does, restore. A control that forgets is worse than no control."""
    trip = ran["roundTrip"]
    assert trip["sent"] == [{"id": 116, "para": {"bullet": False, "indent": 0}}]
    assert trip["stored"] == trip["sent"], "the draft did not keep what the toolbar sent"
    assert trip["now"] == {"bullet": False, "indent": 0, "locked": False}
    assert trip["el"]["li"] is False and trip["el"]["marginLeft"] == "0pt"
    assert trip["bar"]["bullet"]["on"] is False
    assert trip["bar"]["bullet"]["pressed"] == "false"
    assert trip["bar"]["outdent"]["disabled"] is True
    # Still the same payload on the way back out, so a reload cannot lose it on the NEXT
    # generate either.
    assert trip["resent"] == trip["sent"]


def test_a_draft_saved_before_this_feature_restores_exactly_as_it_did(ran):
    """{id, text} with no `para`. The text comes back and goes dirty; the paragraph properties
    stay the template's, and nothing throws on the missing key."""
    got = ran["legacyOverride"]
    assert got["text"] == "Schedule:  legacy text"
    assert got["el"]["dirty"] is True
    assert got["el"]["li"] is True
    assert got["el"]["marginLeft"] == "", "a legacy override gained an inline indent"
    assert got["now"] == {"bullet": True, "indent": 288, "locked": False}
    assert got["patch"] is None


def test_a_text_edit_and_a_bullet_change_travel_in_one_entry(ran):
    """One paragraph, one override. `text` is present this time because this time they typed."""
    assert ran["textAndPara"]["payload"] == [
        {"id": 117, "text": "Exclusions:  striping", "para": {"bullet": False, "indent": 288}}]


# ══ the orphan red square in the preview ═════════════════════════════════════
def test_an_empty_bulleted_block_shows_no_red_square():
    """styles.css only reserved a line's height for `.tw-empty`, so an emptied WORK row left a
    lone red square floating in the preview. Asserted on the rule, because a `::before` content
    string is not reachable from a DOM shim — the DOCUMENT half of the same claim is
    `test_an_emptied_bulleted_row_prints_no_orphan_bullet`, which executes the writer."""
    marker = ".tw-block.tw-empty.tw-li::before"
    assert marker in CSS
    rule = CSS.split(marker, 1)[1].split("}", 1)[0]
    assert "content" in rule and "none" in rule, rule
    # And it has to come AFTER the rule it overrides, or equal specificity would not save it.
    assert CSS.index(".tw-li::before") < CSS.index(marker)


def test_the_toolbar_copy_has_no_em_dashes():
    """Repo rule for user-visible frontend copy. The three titles this pass added are the ones
    at risk; they are read out of the shipped file, not restated."""
    src = (FRONTEND / "js" / "proposal-review.js").read_text(encoding="utf-8")
    for title in ("Bullet point on or off",
                  "Less indent (moves left, all the way to the margin)",
                  "More indent (moves right)"):
        assert title in src, title
        assert "—" not in title



def test_a_blank_text_override_never_renumbers_the_terms_and_conditions():
    """THE REGRESSION THIS GUARD EXISTS FOR, and it was live on production for a day.

    numId 5 is the numbered Terms and Conditions. Every clause is in_block=None, so the
    paragraph-override channel reaches all of them by id. The blank-text tidy-up added on
    2026-08-20 stripped w:numPr without asking whether the list was ORDERED, so blanking one
    clause deleted its number and renumbered every clause after it. Measured at the time:
    blanking the first clause left 26 numbered clauses out of 27.

    A bullet carries no meaning that outlives its text. A clause number carries the identity
    of the clause, and whatever references "Section 7" does not move with it."""
    d0 = _template()
    total = len([1 for _i, _k, p, ib, _t, _x in pw.iter_editable_blocks(d0)
                 if ib is None and pw._para_ordered_list(d0, p)])
    assert total > 1, 'the numbered Terms list is gone - re-read this test'
    tid = _numbered_terms_id()
    for blank in ("", "\n", "   "):
        d = _generate([{'id': tid, 'text': blank}])
        left = len([1 for _i, _k, p, ib, _t, _x in pw.iter_editable_blocks(d)
                    if ib is None and pw._para_ordered_list(d, p)])
        assert left == total, (
            'a blank %r override renumbered the contract: %d of %d clauses still numbered'
            % (blank, left, total))
