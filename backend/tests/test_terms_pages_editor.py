"""The Proposal step shows the Terms pages and the WORK lines the way the fixed document prints them.

THE DOCUMENT (2026-10-02, proposal_writer._rebuild_terms_pages / _omit_bare_lines): the Terms are a
section of their own whose header carries Kyle's letterhead on every page; the per-page art he
anchored to empty page-top paragraphs is gone, and so are those paragraphs and the padding round
them; the clauses he split by hand at Word's page breaks are joined back; a WORK "Texture:" /
"Notes:" line with nothing after its label is left out. The writer serves its own plan to the
editor as /api/proposal-template's `render_adjustments` (test_terms_pages_and_bare_work_lines.py).

THE PAGE, executed (js/terms-pages-harness.js: the real initDocumentEditor over the real payload,
renderPositioned, repaginateTerms, applyTermsArt, applyTermsPlan, showTermsJoins,
applyBareWorkLines, renderSystemPreview, refreshDocumentFills, restoreSavedOverrides,
collectOverrides), and compared with the .docx the real fill_proposal writes:

  * the Terms start a page of their own; every Terms page paints ONE letterhead, the plan's art at
    the plan's size and place, and never the art Kyle anchored to a page-top paragraph; the pages
    are the plan's size and margins, and nothing is measured off the art any more;
  * the paragraphs the page shows in the Terms, joined where it joins them, are word for word the
    paragraphs the document prints -- on every template, and after the edits that change what
    the writer joins (a line typed between two halves, a full stop ending a head, a reworded
    continuation);
  * a join is a DISPLAY join: each half stays its own line, and an edit to either saves under its
    own id, which is what the writer applies before it joins;
  * a WORK line prints, on the page, exactly when it prints in the document;
  * a browser holding the older response, with no `render_adjustments`, draws what it always drew.

The pager measures, so the harness models layout (see its header): a greedy wrap over the Terms
face's advance widths (Cambria, read off the font when this machine has it) at the line heights
styles.css gives. The page-count check needs the real font and is skipped without it.
"""
import copy
import io
import json
import pathlib
import re
import shutil
import subprocess
import tempfile

import docx
import pytest
from starlette.requests import Request

import main
import proposal_writer as pw

HERE = pathlib.Path(__file__).resolve().parent
FRONTEND = HERE.parents[1] / "frontend"
HARNESS = HERE / "js" / "terms-pages-harness.js"
CSS = (FRONTEND / "styles.css").read_text(encoding="utf-8")
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Every template with a Terms section (Budget has none).
TERMS = [("epoxy", "Direct"), ("polish", "Direct"), ("combo", "Direct"), ("polish", "GC"),
         ("epoxy", "GC"), ("sealer", "GC"), ("gyp", "Direct")]
IDS = ["%s-%s" % t for t in TERMS]

VALUES = {
    "job_name": "Release Check Warehouse", "project_name": "Release Check Warehouse",
    "city_state": "Olathe, KS", "bid_date_formatted": "9/26/26",
    "site_visit_phrase": "per site visit on 9/26/26", "estimator_name": "Kyle Loseke",
    "system_name": "Treadwell MACRO Flake Single Broadcast", "epoxy_system_name": "Epoxy System",
    "texture": "", "work_notes": "",
    "epoxy_sf": "1,000", "polish_sf": "1,000", "sqft": "1,000", "cove_lf": "50",
    "area_description": "~1,000 sf of epoxy flooring",
    "scope_notes": "Prep and coat.", "schedule_notes": "One week.", "exclusions": "Moving furniture.",
    "base_bid_formatted": "$5,569", "material_tax_formatted": "$11", "total_formatted": "$5,580",
    "lump_sum_formatted": "$5,580", "tax_amount_formatted": "$0", "state_name": "Kansas",
    "base_tax_phrase": "(material sales tax INCLUDED)",
}
SYSTEM = {"prefix": "System:", "name": "Epoxy System", "texture": "", "sqft": "1,000",
          "lf_clause": " and 50 LF of 6\" epoxy cove base"}


# ── the inputs ───────────────────────────────────────────────────────────────────────────────
def _req():
    return Request({"type": "http", "headers": [], "method": "GET", "path": "/api/proposal-template",
                    "query_string": b""})


_PAYLOADS = {}


def _payload(wt, aud):
    if (wt, aud) not in _PAYLOADS:
        _PAYLOADS[(wt, aud)] = json.loads(main.api_proposal_template(_req(), wt, aud).body)
    return copy.deepcopy(_PAYLOADS[(wt, aud)])


def _rule(selector):
    """The declarations of the stylesheet rule whose selector list is exactly `selector`."""
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if [s.strip() for s in sel.split(",")] == [selector]:
            return dict((k.strip(), v.strip()) for k, v in
                        (d.split(":", 1) for d in body.split(";") if ":" in d))
    return {}


def _css_model():
    """What the stylesheet says about the lines the pager measures, read out of styles.css -- the
    harness's layout model draws every line with these, so removing a rule changes the model."""
    page = _rule(".tw-page")
    block, empty = _rule(".tw-block"), _rule(".tw-block.tw-empty")
    terms = _rule(".tw-page.tw-terms-section")
    t_block, t_empty = _rule(".tw-terms-section .tw-block"), _rule(".tw-terms-section .tw-block.tw-empty")
    return {
        "page_font_pt": float(page["font-size"].rstrip("pt")),
        "page_line_height": page["line-height"],
        "terms_line_height": terms.get("line-height"),
        "block_min": block.get("min-height", "0"),
        "empty_min": empty.get("min-height", "0"),
        # A Terms-section line falls back to the ordinary rule when the section has none.
        "terms_block_min": t_block.get("min-height", block.get("min-height", "0")),
        "terms_empty_min": t_empty.get("min-height", empty.get("min-height", "0")),
    }


def _cambria():
    """(regular, bold) PIL fonts of the Terms face at 2048px, or None on a machine without it."""
    try:
        from PIL import ImageFont
    except ImportError:
        return None
    for reg, bold in ((r"C:/Windows/Fonts/cambria.ttc", r"C:/Windows/Fonts/cambriab.ttf"),):
        try:
            return ImageFont.truetype(reg, 2048, index=0), ImageFont.truetype(bold, 2048)
        except OSError:
            continue
    return None


CAMBRIA = _cambria()


def _model(texts):
    """Advance widths (em) for every character the scenarios draw, and the face's single line."""
    chars = sorted(set("".join(texts)) | set(" "))
    if CAMBRIA is None:
        return {"widths": {"regular": {}, "bold": {}, "fallback": 0.5}, "normal_em": 1.2,
                "css": _css_model(), "real_font": False}
    reg, bold = CAMBRIA
    asc, desc = reg.getmetrics()
    return {"widths": {"regular": {c: reg.getlength(c) / 2048.0 for c in chars},
                       "bold": {c: bold.getlength(c) / 2048.0 for c in chars},
                       "fallback": reg.getlength("n") / 2048.0},
            "normal_em": (asc + desc) / 2048.0, "css": _css_model(), "real_font": True}


def _tokens():
    return dict(VALUES)


def _scenario(name, wt, aud, steps=None, state=None, form=None, payload=None, band=None):
    st = {"work_type": wt, "audience": aud}
    st.update(state or {})
    return {"name": name, "payload": payload if payload is not None else _payload(wt, aud),
            "state": st, "form": dict({"texture": "", "work_notes": ""}, **(form or {})),
            "tokens": _tokens(), "steps": steps or [], "band": band}


def _saved(wt, aud, items):
    """A draft that already holds paragraph edits for this template, as the page stores them."""
    return {"paragraph_overrides_all": {"%s:%s" % (wt, aud): {
        "template_version": _payload(wt, aud)["template_version"], "items": items}}}


def _plan(wt="epoxy", aud="Direct"):
    return _payload(wt, aud)["render_adjustments"]["terms"]


def _texts(wt, aud):
    return {b["id"]: b["text"] for b in _payload(wt, aud)["blocks"]}


def _old(wt, aud):
    p = _payload(wt, aud)
    del p["render_adjustments"]
    return p


def _renamed_hosts(wt, aud, keep_plan=True):
    """The payload with the art Kyle anchored to each Terms page-top paragraph renamed, so a page
    that paints it can be told from one that paints the plan's art (they are the same PNG)."""
    p = _payload(wt, aud) if keep_plan else _old(wt, aud)
    hosts = set(_plan(wt, aud)["art_host_ids"])
    for im in p["geometry"]["images"]:
        if im["para_index"] in hosts:
            im["name"] = "host-%d.png" % im["para_index"]
    return p


def _bad_regex():
    p = _payload("epoxy", "Direct")
    p["render_adjustments"]["terms"]["sentence_end"] = "[unclosed"
    return p


def _bad_first_id():
    p = _payload("epoxy", "Direct")
    p["render_adjustments"]["terms"]["first_id"] = 99999
    return p


def _words_before_terms():
    """A body paragraph with words ahead of the Terms. None of Kyle's files has one; the page shows
    it, and the Terms still start a page of their own."""
    p = _payload("epoxy", "Direct")
    first = p["render_adjustments"]["terms"]["first_id"]
    b = next(b for b in p["blocks"] if b["id"] == first - 2)
    b["text"], b["runs"] = "Page one words.", []
    return p


# Long enough to be taller than a Terms page on its own (about 56 lines of 95 characters).
HUGE = "A heading Kyle rewrote at great length. " * 220


def _scenarios():
    out = []
    for wt, aud in TERMS:
        out.append(_scenario("plan:%s:%s" % (wt, aud), wt, aud))
        out.append(_scenario("old:%s:%s" % (wt, aud), wt, aud, payload=_old(wt, aud)))
    out.append(_scenario("hosts-renamed", "epoxy", "Direct", payload=_renamed_hosts("epoxy", "Direct")))
    out.append(_scenario("hosts-renamed-old", "epoxy", "Direct",
                         payload=_renamed_hosts("epoxy", "Direct", keep_plan=False)))
    out.append(_scenario("budget", "budget", "Direct"))
    out.append(_scenario("bad-regex", "epoxy", "Direct", payload=_bad_regex()))
    out.append(_scenario("bad-first-id", "epoxy", "Direct", payload=_bad_first_id()))
    out.append(_scenario("words-before-terms", "epoxy", "Direct", payload=_words_before_terms()))
    for name, items in _edits().items():
        out.append(_scenario("edit:" + name, "epoxy", "Direct", state=_saved("epoxy", "Direct", items)))
    # Typing in either half of a join, then collecting what the page would save.
    a, b = _plan()["join_pairs"][0]
    tx = _texts("epoxy", "Direct")
    out.append(_scenario("type-both-halves", "epoxy", "Direct", steps=[
        {"op": "type", "id": a, "text": tx[a] + " promptly"},
        {"op": "type", "id": b, "text": "inspect the work first."},
        {"op": "collect"}, {"op": "repaginate"}]))
    # The WORK lines.
    for key, kw in _work().items():
        wt, aud = key.split(":")[:2]
        out.append(_scenario("work:" + key, wt, aud, **kw))
    out.append(_scenario("work-old:epoxy:Direct", "epoxy", "Direct", payload=_old("epoxy", "Direct")))
    out.append(_scenario("work-refresh:epoxy:Direct", "epoxy", "Direct", steps=[
        {"op": "snap", "label": "blank"},
        {"op": "form", "values": {"texture": "Orange Peel", "work_notes": "Owner moves the racking"}},
        {"op": "refresh"}, {"op": "snap", "label": "filled"},
        {"op": "form", "values": {"texture": "", "work_notes": ""}},
        {"op": "refresh"}, {"op": "snap", "label": "emptied"}]))
    # The same refresh with the caret in a WORK {{#system}} row: renderSystemPreview does not
    # repaint under a caret, so the Notes line must come back without it.
    out.append(_scenario("work-refresh-in-system:epoxy:Direct", "epoxy", "Direct", steps=[
        {"op": "caret", "sys": "name_line"},
        {"op": "form", "values": {"work_notes": "Owner moves the racking"}},
        {"op": "refresh"}, {"op": "snap", "label": "filled"}]))
    out.append(_scenario("work-caret:epoxy:Direct", "epoxy", "Direct",
                         form={"work_notes": "Owner moves the racking"}, steps=[
        {"op": "caret", "id": 118}, {"op": "type", "id": 118, "text": "Notes: "}, {"op": "bare"},
        {"op": "snap", "label": "caret in it"},
        {"op": "caret", "id": None}, {"op": "bare"}, {"op": "snap", "label": "caret gone"}]))
    return out


def _edits():
    """Saved edits on Direct Epoxy that change what the writer joins or drops."""
    plan = _plan()
    tx = _texts("epoxy", "Direct")
    a0, b0 = plan["join_pairs"][0]
    a2, b2 = plan["join_pairs"][2]
    typed = next(i for i in plan["drop_if_blank_ids"] if a2 < i < b2)
    return {
        # Kyle types into one of his padding lines inside clause 18's split.
        "typed-between": [{"id": typed, "text": "Typed by Kyle."}],
        # The first half ends a sentence now: the two print apart.
        "full-stop": [{"id": a0, "text": tx[a0] + " it."}],
        # A reworded continuation still joins its head.
        "reworded-continuation": [{"id": b0, "text": "inspect the work first."}],
        # A line break typed into a padding line keeps it (a w:br is something).
        "break-in-padding": [{"id": plan["drop_if_blank_ids"][1], "text": "\n"}],
        # A bullet put on a continuation: the writer has no bullet list beside it in the Terms to
        # put it on (_sibling_bullet_ref), so it prints as it was, joined.
        "bulleted-continuation": [{"id": b0, "para": {"bullet": True, "indent": 540}}],
        # The heading rewritten taller than a page: it starts the first Terms page, which grows,
        # and no page is left holding only the hidden padding above it.
        "huge-heading": [{"id": plan["first_id"] + 1, "text": HUGE}],
    }


def _work():
    """The WORK-line scenarios: template, then what the sidebar and the draft hold."""
    return {
        "epoxy:Direct:blank": {},
        "epoxy:Direct:filled": {"form": {"texture": "Orange Peel", "work_notes": "Owner moves the racking"}},
        "epoxy:Direct:texture-line": {"state": {"system_overrides": [{"texture_line": "Texture:  Owner's pick"}]}},
        "epoxy:Direct:relabelled": {"state": {"system_overrides": [{"texture_label": "Finish:"}]}},
        "epoxy:Direct:notes-typed": {"state": _saved("epoxy", "Direct",
                                                     [{"id": 118, "text": "Notes:  Bring the long ladder"}])},
        "polish:Direct:blank": {},
        "polish:Direct:filled": {"form": {"work_notes": "Owner moves the racking"}},
        "combo:Direct:blank": {},
        "combo:Direct:filled": {"form": {"texture": "Orange Peel", "work_notes": "Owner moves the racking"}},
        "gyp:Direct:blank": {},
        "gyp:Direct:sub-emptied": {"state": _saved("gyp", "Direct", [{"id": 140, "text": ""}])},
        "epoxy:GC:blank": {},
    }


_RAN = {}


@pytest.fixture(scope="module")
def ran():
    if not _RAN:
        scenarios = _scenarios()
        texts = [b["text"] for sc in scenarios for b in sc["payload"]["blocks"]]
        texts += [o.get("text", "") for items in _edits().values() for o in items]
        cases = {"model": _model(texts), "scenarios": scenarios}
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "cases.json"
            path.write_text(json.dumps(cases), encoding="utf-8")
            got = subprocess.run([NODE, str(HARNESS), str(FRONTEND), str(path)], capture_output=True,
                                 text=True, encoding="utf-8", timeout=600)
        assert got.returncode == 0, got.stderr[-4000:]
        _RAN.update(json.loads(got.stdout))
        _RAN["_model"] = cases["model"]
    for name, res in _RAN.items():
        if isinstance(res, dict) and "error" in res:
            raise AssertionError("%s: %s" % (name, res["error"]))
    return _RAN


# ── the document side ────────────────────────────────────────────────────────────────────────
def _fill(wt, aud, values=None, **kw):
    v = dict(VALUES)
    v.update(values or {})
    if wt == "epoxy" and aud == "Direct" and "systems" not in kw:
        kw["systems"] = [dict(SYSTEM, texture=v["texture"])]
    return pw.fill_proposal(work_type=wt, audience=aud, values=v, **kw)


def _printed_terms(raw):
    """The Terms paragraphs the document prints: every body paragraph after page 1's section."""
    tops = [c for c in docx.Document(io.BytesIO(raw)).element.body if c.tag == W + "p"]
    brk = next(i for i, p in enumerate(tops) if p.find(W + "pPr/" + W + "sectPr") is not None)
    return [pw._own_text(p) for p in tops[brk + 1:]]


def _box_lines(raw):
    """Every text-box paragraph's text, the mc:Choice copy only (the one the editor's ids name)."""
    d = docx.Document(io.BytesIO(raw))
    return [pw._own_text(p) for t in d.element.body.iter(W + "txbxContent") for p in t.iter(W + "p")
            if not pw._is_fallback_paragraph(p)]


def _final(ran, name):
    res = ran[name]
    assert not res["final"]["errors"], (name, res["final"]["errors"])
    return res["final"]


# ══ the Terms pages ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("wt,aud", TERMS, ids=IDS)
def test_every_terms_page_is_a_page_of_the_section_with_the_plans_one_letterhead(ran, wt, aud):
    """The plan's page size and margins (the top one clears the logo, so no band is measured off the
    art), the Terms face, and ONE letterhead per page: the plan's art, at its own size and place,
    painted by the page -- no picture element a Ctrl+A could take out."""
    got = _final(ran, "plan:%s:%s" % (wt, aud))
    plan = _plan(wt, aud)
    m, art = plan["page"]["margin"], plan["art"]
    assert got["plan"] and got["pages"]
    for pg in got["pages"]:
        assert "tw-terms-section" in pg["cls"].split(), pg["cls"]
        assert pg["width"] == "%gpt" % plan["page"]["w_pt"] and pg["height"] == "%gpt" % plan["page"]["h_pt"]
        assert pg["padding"] == "%gpt %gpt %gpt %gpt" % (m["top"], m["right"], m["bottom"], m["left"])
        assert pg["bg"] == 'url("data:%s")' % art["name"]
        assert pg["bgSize"] == "%gpt %gpt" % (art["w_pt"], art["h_pt"])
        assert pg["bgPos"] == "%gpt %gpt" % (art["x_pt"], art["y_pt"])
        assert pg["bgRepeat"] == "no-repeat" and pg["imgs"] == 0
        assert pg["font"].startswith("'Cambria'"), pg["font"]
    assert got["band"] == [], "a logo band was measured off the art"
    # Page 1 keeps its own letterhead; the Terms ask for the plan's, and nothing else.
    first_art = next(i["name"] for i in _payload(wt, aud)["geometry"]["images"] if i["para_index"] == 0)
    assert got["page1Art"] == ["data:" + first_art]
    assert sorted(set(got["art"])) == sorted({first_art, art["name"]})


@pytest.mark.parametrize("wt,aud", TERMS, ids=IDS)
def test_the_terms_start_a_page_of_their_own_at_the_plans_first_block(ran, wt, aud):
    got = _final(ran, "plan:%s:%s" % (wt, aud))
    first = got["pages"][0]
    assert first["units"][0]["ids"][0] == _plan(wt, aud)["first_id"]
    assert first["shown"][0].strip().upper() == "TERMS AND CONDITIONS"


def test_no_terms_page_paints_the_art_kyle_anchored_to_a_paragraph(ran):
    """Kyle's per-page anchors are renamed in the payload, so they can be told from the plan's
    art: the page never asks for one. The old page, given the same payload, does -- which is what
    shows the scenario can tell the two apart."""
    got = _final(ran, "hosts-renamed")
    assert not [a for a in got["art"] if a.startswith("host-")], got["art"]
    assert {pg["bg"] for pg in got["pages"]} == {'url("data:image2.png")'}
    old = _final(ran, "hosts-renamed-old")
    assert "host-46.png" in old["art"] and old["band"] == ["host-46.png"]


@pytest.mark.parametrize("wt,aud", TERMS, ids=IDS)
def test_the_page_shows_the_terms_paragraphs_the_document_prints(ran, wt, aud):
    """THE PARITY: Kyle's padding lines hidden, his hand splits shown joined, with the writer's
    space between two halves -- the paragraphs the page shows in the Terms, in order, are word for
    word the ones the filled .docx prints after page 1's section."""
    got = _final(ran, "plan:%s:%s" % (wt, aud))
    assert got["terms"] == _printed_terms(_fill(wt, aud))


@pytest.mark.parametrize("name", ["typed-between", "full-stop", "reworded-continuation",
                                  "break-in-padding", "bulleted-continuation", "huge-heading"])
def test_an_edit_that_changes_a_join_or_a_drop_shows_what_the_document_prints(ran, name):
    """A line typed between two halves keeps them apart and itself in place; a full stop on a head
    ends the join; a reworded continuation still joins; a line break keeps a padding line; a bullet
    on a continuation, which the writer cannot print in the Terms, leaves it joined. Replayed from
    the draft, as a reload does."""
    got = _final(ran, "edit:" + name)
    items = _edits()[name]
    assert got["terms"] == _printed_terms(_fill("epoxy", "Direct", paragraph_overrides=items))


def test_the_edits_split_and_keep_what_they_should(ran):
    plan = _plan()
    pairs = plan["join_pairs"]
    a2, b2 = pairs[2]
    typed = next(i for i in plan["drop_if_blank_ids"] if a2 < i < b2)
    got = _final(ran, "edit:typed-between")
    assert typed not in got["hidden"] and "Typed by Kyle." in got["terms"]
    assert [j["ids"] for j in got["joins"]] == [pairs[0], pairs[1], [pairs[2][1], pairs[3][1]]]
    assert pairs[0] not in [j["ids"] for j in _final(ran, "edit:full-stop")["joins"]]
    assert pairs[0] in [j["ids"] for j in _final(ran, "edit:bulleted-continuation")["joins"]]
    assert plan["drop_if_blank_ids"][1] not in _final(ran, "edit:break-in-padding")["hidden"]


def test_a_join_is_a_display_join_each_half_keeps_its_own_line_and_saved_edit(ran):
    """The head and its continuation are separate lines inside the join, each with its own id;
    typing in either one saves under that id, and the page then shows what the document prints for
    those two edits. The wrapper carries the head's paragraph geometry; the space between the
    halves is the continuation's generated content, not a character in either."""
    a, b = _plan()["join_pairs"][0]
    tx = _texts("epoxy", "Direct")
    res = ran["type-both-halves"]
    collected = {o["id"]: o for o in res["collect"]}
    assert collected[a]["text"] == tx[a] + " promptly"
    assert collected[b]["text"] == "inspect the work first."
    got = res["final"]
    assert got["terms"] == _printed_terms(_fill("epoxy", "Direct", paragraph_overrides=[
        {"id": a, "text": tx[a] + " promptly"}, {"id": b, "text": "inspect the work first."}]))
    j = next(j for j in got["joins"] if j["ids"][0] == a)
    assert j["ids"] == [a, b] and j["head"] and j["tails"] == [True] and j["seps"] == [True]
    assert (j["padding"], j["hang"]) == ("27pt", "18pt")       # w:ind left=540 hanging=360
    assert got["blockText"][str(b)] == "inspect the work first."   # no separator in the line itself


def test_padding_lines_are_hidden_while_they_print_nothing_and_only_those(ran):
    plan = _plan()
    tx = _texts("epoxy", "Direct")
    got = _final(ran, "plan:epoxy:Direct")
    blank = {i for i in plan["drop_if_blank_ids"] if not tx[i].strip()}
    assert set(got["planHidden"]) - {118} == blank


@pytest.mark.parametrize("wt,aud", TERMS, ids=IDS)
def test_a_response_without_the_plan_draws_the_page_it_always_drew(ran, wt, aud):
    """The older /api/proposal-template body: the Terms start at the first paragraph with words,
    tile the art Kyle anchored to his Terms pages with the logo band measured off it, keep every
    padding line and every hand split, and no WORK line is hidden."""
    got = _final(ran, "old:%s:%s" % (wt, aud))
    assert not got["plan"] and got["pages"]
    body = [b for b in _payload(wt, aud)["blocks"] if b["txbx"] is None]
    first_real = next(b["id"] for b in body if b["text"].strip())
    assert got["pages"][0]["units"][0]["ids"] == [first_real]
    assert got["joins"] == [] and got["planHidden"] == []
    for pg in got["pages"]:
        assert "tw-terms-section" not in pg["cls"].split() and pg["font"] == ""
        assert pg["bgSize"] == "612pt 792pt" and pg["padding"] == "%gpt 90pt 72pt 90pt" % (72 + 54)
    assert got["band"] == ["image2.png"]
    # Every block from the first with words on is shown, the hand splits as written.
    shown = [t for pg in got["pages"] for t in pg["shown"]]
    assert len(shown) == len([b for b in body if b["id"] >= first_real and b["id"] not in got["hidden"]])


def test_a_plan_that_does_not_read_right_is_dropped_part_by_part(ran):
    """A `sentence_end` that does not compile joins nothing (a join cannot be told from a sentence
    without it) while the padding still goes; a first block the template does not have is no Terms
    plan at all, and the old page is drawn."""
    got = _final(ran, "bad-regex")
    assert got["plan"] and got["joins"] == []
    assert set(_plan()["drop_if_blank_ids"]) & set(got["planHidden"])
    got = _final(ran, "bad-first-id")
    assert not got["plan"] and got["joins"] == [] and got["band"] == ["image2.png"]


def test_words_before_the_terms_stay_on_their_own_page(ran):
    got = _final(ran, "words-before-terms")
    first = _plan()["first_id"]
    assert got["pages"][0]["shown"][0] == "Page one words."
    assert all(i < first for u in got["pages"][0]["units"] for i in u["ids"])
    assert got["pages"][1]["units"][0]["ids"] == [first]
    assert got["pages"][1]["shown"][0] == "TERMS AND CONDITIONS"


def test_no_terms_page_is_drawn_holding_nothing_anybody_can_see(ran):
    """A page whose every line is hidden is not one to leave behind -- the case is the heading
    rewritten taller than a page, which follows nothing but the hidden padding above it."""
    for name, res in ran.items():
        if name.startswith("_"):
            continue
        for i, pg in enumerate(res["final"]["pages"]):
            assert pg["shown"], (name, i)
    first = _final(ran, "edit:huge-heading")["pages"][0]
    assert first["shown"][0] == HUGE and first["height"] == "auto"


def test_budget_has_no_terms_pages(ran):
    got = _final(ran, "budget")
    assert got["pages"] == [] and not got["plan"]


def test_every_scenario_ran_without_an_error(ran):
    for name, res in ran.items():
        if name.startswith("_"):
            continue
        assert not res["final"]["errors"], (name, res["final"]["errors"])


# ══ the pages the Terms take ════════════════════════════════════════════════════════════════════
# THE FIXED PDF IS FOUR PAGES on every template (page 1 and three Terms pages; terms_render_proof.py
# in the production image). The editor packs whole paragraphs where the PDF breaks mid-paragraph,
# and it draws the Terms in Cambria where the PDF's LibreOffice substitutes Caladea, which sets the
# same words about 4% narrower. With the plan applied the six 27-clause templates come out at three
# Terms pages like the PDF; Gyp's longer Terms (28 clauses and its own closing pages) take four in
# Cambria. Without the plan every template took one page more than that.
EDITOR_TERMS_PAGES = {"epoxy-Direct": 3, "polish-Direct": 3, "combo-Direct": 3, "polish-GC": 3,
                      "epoxy-GC": 3, "sealer-GC": 3, "gyp-Direct": 4}


@pytest.mark.skipif(CAMBRIA is None, reason="the Terms face (Cambria) is not on this machine")
@pytest.mark.parametrize("wt,aud", TERMS, ids=IDS)
def test_the_terms_take_the_pages_the_document_takes(ran, wt, aud):
    assert ran["_model"]["real_font"]
    plan_pages = len(_final(ran, "plan:%s:%s" % (wt, aud))["pages"])
    old_pages = len(_final(ran, "old:%s:%s" % (wt, aud))["pages"])
    assert plan_pages == EDITOR_TERMS_PAGES["%s-%s" % (wt, aud)], (plan_pages, old_pages)
    assert old_pages == plan_pages + 1


@pytest.mark.parametrize("wt,aud", TERMS, ids=IDS)
def test_no_terms_page_overflows_its_text_area(ran, wt, aud):
    """Every unit the pager put on a page ends above the page's bottom margin (or is a paragraph
    taller than a page, which grows its page), so nothing is clipped behind the footer art."""
    got = _final(ran, "plan:%s:%s" % (wt, aud))
    m = _plan(wt, aud)["page"]["margin"]
    bottom_px = (_plan(wt, aud)["page"]["h_pt"] - m["bottom"]) * 96 / 72
    for pg in got["pages"]:
        for u in pg["units"]:
            if u["shown"]:
                assert u["top"] + u["h"] <= bottom_px + 0.5 or pg["height"] == "auto", (u, pg["height"])


# ══ the WORK lines ══════════════════════════════════════════════════════════════════════════════
def _work_fill(key):
    """The .docx for one WORK scenario: the same fields, system rows and saved edits."""
    wt, aud, _case = key.split(":")
    kw = _work()[key]
    values = dict(kw.get("form") or {})
    state = kw.get("state") or {}
    args = {}
    items = (state.get("paragraph_overrides_all") or {}).get("%s:%s" % (wt, aud), {}).get("items")
    if items:
        args["paragraph_overrides"] = items
    if wt == "epoxy" and aud == "Direct":
        sysd = dict(SYSTEM, texture=values.get("texture", ""))
        sysd.update((state.get("system_overrides") or [{}])[0])
        args["systems"] = [sysd]
    return _fill(wt, aud, values, **args)


def _printed(lines, label):
    return any(t.strip().startswith(label) for t in lines)


@pytest.mark.parametrize("key", list(_work()), ids=lambda k: k)
def test_a_work_line_shows_exactly_when_the_document_prints_it(ran, key):
    wt, aud, _case = key.split(":")
    got = _final(ran, "work:" + key)
    lines = _payload(wt, aud)["render_adjustments"]["lines"]
    printed = _box_lines(_work_fill(key))
    if not lines:
        # The GC forms carry Kyle's words after every label: nothing is a candidate, nothing goes.
        assert set(got["planHidden"]) <= set(_plan(wt, aud)["drop_if_blank_ids"])
        return
    for ln in lines:
        if ln["in_block"] is None:
            shown = [ln["id"] not in got["hidden"]]
        else:
            shown = [not r["hidden"] for r in got["sys"] if r["line"] == ln["line_key"]]
        assert shown, ln
        assert shown == [_printed(printed, ln["label"])] * len(shown), (ln, shown, printed)


def test_the_texture_row_and_the_notes_line_go_when_blank_on_direct_epoxy(ran):
    """The audit's two bare lines, named: page 1's "Texture:" and "Notes:"."""
    got = _final(ran, "work:epoxy:Direct:blank")
    assert [r["hidden"] for r in got["sys"] if r["line"] == "texture_line"] == [True]
    assert [r["hidden"] for r in got["sys"] if r["line"] != "texture_line"] == [False, False]
    assert 118 in got["hidden"]
    got = _final(ran, "work:epoxy:Direct:filled")
    assert [r["text"] for r in got["sys"] if r["line"] == "texture_line"] == ["Texture:  Orange Peel"]
    assert 118 not in got["hidden"] and got["blockText"]["118"].strip().endswith("Owner moves the racking")


def test_a_field_filled_in_the_sidebar_brings_its_line_back_and_emptied_takes_it_out(ran):
    snaps = {s["label"]: s for s in ran["work-refresh:epoxy:Direct"]["steps"]}

    def tex(s):
        return [r["hidden"] for r in s["sys"] if r["line"] == "texture_line"]

    assert tex(snaps["blank"]) == [True] and 118 in snaps["blank"]["hidden"]
    assert tex(snaps["filled"]) == [False] and 118 not in snaps["filled"]["hidden"]
    assert tex(snaps["emptied"]) == [True] and 118 in snaps["emptied"]["hidden"]


def test_a_filled_field_brings_its_line_back_with_the_caret_in_a_system_row(ran):
    """renderSystemPreview does not repaint under a caret in one of its rows, so the refresh asks the
    WORK lines itself."""
    snap = ran["work-refresh-in-system:epoxy:Direct"]["steps"][0]
    assert 118 not in snap["hidden"], snap["hidden"]


def test_the_line_with_the_caret_in_it_is_not_taken_out_from_under_it(ran):
    snaps = {s["label"]: s for s in ran["work-caret:epoxy:Direct"]["steps"]}
    assert 118 not in snaps["caret in it"]["hidden"]
    assert 118 in snaps["caret gone"]["hidden"]


def test_a_response_without_the_plan_hides_no_work_line(ran):
    got = _final(ran, "work-old:epoxy:Direct")
    assert not any(r["hidden"] for r in got["sys"]) and 118 not in got["hidden"]
