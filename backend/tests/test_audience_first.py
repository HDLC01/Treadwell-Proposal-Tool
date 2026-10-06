"""Audience is the FIRST box on both intake forms, and it is the same box on both.

WHAT HANZ ASKED FOR.

2026-10-07, on the plan for the v2 estimating tool: "The Audience box moves to the top of both
intake forms." It sat LAST on each, under the job conditions, so an estimator answered a screenful
about the job before the one question that decides which proposal template the tool fills (Direct
customer or General contractor). Asked first, it frames the rest, and a bid that arrives from the
GC board's + New, already set to GC, shows that choice at the top of the form instead of out of
sight under it.

WHAT IS PINNED, AND WHAT IS NOT.

  * On both pages (frontend/index.html, the live intake, and frontend/polish-intake.html, the v2
    intake) the first box inside #intake-form is #audience-box, and it comes before Project Info.
  * It stays INSIDE the form. TW.readForm and the draft autosave only see form elements, and the
    v2 page has a box of its own, "Say it instead", that sits outside the form on purpose.
  * Direct is the checked default.
  * The two boxes are the same markup, indentation and attribute order aside.

  Not pinned here: the order of the boxes below it. Drawings & specs staying directly after
  Project Info is test_gc_template_tokens.py's job, and the other boxes answer to their own tests.

WHY PARSED, NOT GREPPED.

A claim about position is a claim about structure. A string index over the page text is fooled by
an id or a word in a comment, and these pages are full of comments. These tests run the real pages
through html.parser, which skips comments and tracks which tags are open the way a browser does,
and they carry their own counterexamples so a green run cannot be a reader that sees nothing.
"""
import functools
import pathlib
from html.parser import HTMLParser

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
PAGES = ["index.html", "polish-intake.html"]
FORM_ID = "intake-form"
BOX_ID = "audience-box"

# Void elements have no end tag, so a self-closing slash on one page must not make its box look
# different from the same box on the other.
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source",
         "track", "wbr"}


class _Intake(HTMLParser):
    """Reads one page and keeps only what these tests need.

    boxes        every fieldset inside #intake-form, in document order, as {"id", "legend"}. A box
                 outside the form (the v2 page's "Say it instead") is not listed, which is the
                 point: only form elements reach readForm and the autosave.
    radios       every input named audience on the page, as {"value", "checked", "in_form", "box"}.
    audience_box the audience box as a flat token list with whitespace collapsed and attributes
                 sorted, so the two pages compare without caring about indentation.
    """

    def __init__(self):
        super().__init__()
        self.in_form = False
        self.boxes = []
        self.radios = []
        self.audience_box = []
        self._open_boxes = []      # fieldsets inside the form that have not closed yet
        self._legend_of = None     # the box whose legend text is being read
        self._depth = 0            # fieldset depth while inside the audience box; 0 = not in it

    @staticmethod
    def _attr_key(attrs):
        return tuple(sorted((k, v or "") for k, v in attrs))

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form" and a.get("id") == FORM_ID:
            self.in_form = True
        if tag == "fieldset" and self.in_form:
            box = {"id": a.get("id"), "legend": ""}
            self.boxes.append(box)
            self._open_boxes.append(box)
        if tag == "legend" and self._open_boxes:
            self._legend_of = self._open_boxes[-1]
        if tag == "input" and a.get("name") == "audience":
            self.radios.append({
                "value": a.get("value"),
                "checked": "checked" in a,
                "in_form": self.in_form,
                "box": self._open_boxes[-1]["id"] if self._open_boxes else None,
            })
        if self._depth:
            if tag == "fieldset":
                self._depth += 1
            self.audience_box.append(("start", tag, self._attr_key(attrs)))
        elif tag == "fieldset" and a.get("id") == BOX_ID and not self.audience_box:
            self._depth = 1
            self.audience_box.append(("start", tag, self._attr_key(attrs)))

    def handle_endtag(self, tag):
        if self._depth and tag not in _VOID:
            self.audience_box.append(("end", tag))
            if tag == "fieldset":
                self._depth -= 1
        if tag == "legend":
            self._legend_of = None
        if tag == "fieldset" and self._open_boxes:
            self._open_boxes.pop()
        if tag == "form":
            self.in_form = False

    def handle_data(self, data):
        text = " ".join(data.split())
        if not text:
            return
        if self._legend_of is not None:
            self._legend_of["legend"] = (self._legend_of["legend"] + " " + text).strip()
        if self._depth:
            self.audience_box.append(("text", text))


def _parse_text(text):
    reader = _Intake()
    reader.feed(text)
    reader.close()
    return reader


@functools.lru_cache(maxsize=None)
def _parse(name):
    return _parse_text((FRONTEND / name).read_text(encoding="utf-8"))


def _inputs(tokens):
    return [t for t in tokens if t[:2] == ("start", "input")]


@pytest.mark.parametrize("name", PAGES)
def test_the_audience_box_is_the_first_box_on_both_intakes(name):
    """Hanz, 2026-10-07: Audience goes at the very top of BOTH intake forms. The first box in
    #intake-form is #audience-box, with the legend the estimator reads.

    Mutation: put the box back under the job conditions, or give another box the first place."""
    boxes = _parse(name).boxes
    assert boxes, name + ": no boxes were found inside #intake-form at all"
    first = boxes[0]
    assert (first["id"], first["legend"]) == (BOX_ID, "Audience"), (
        name + ": the first box in #intake-form is " + repr(first["legend"]) + ", not Audience. "
        "Audience picks the proposal template, so it is asked before the job itself.")


@pytest.mark.parametrize("name", PAGES)
def test_the_audience_box_comes_before_project_info(name):
    """The brief said "before Project Info" in so many words, and Project Info used to be first.

    Mutation: swap the two boxes, or drop the Audience box from the form."""
    legends = [b["legend"] for b in _parse(name).boxes]
    assert "Audience" in legends and "Project Info" in legends, legends
    assert legends.index("Audience") < legends.index("Project Info"), legends


@pytest.mark.parametrize("name", PAGES)
def test_the_audience_radios_stay_inside_the_form(name):
    """TW.readForm and the draft autosave walk the form's own elements. A box moved above the form
    tag (next to the v2 page's "Say it instead" box, say) would look right and save nothing, and
    every bid would quietly go out as Direct.

    Mutation: move the Audience box above the form tag."""
    radios = _parse(name).radios
    assert len(radios) == 2, name + ": expected the Direct and GC radios, found " + repr(radios)
    for r in radios:
        assert r["in_form"], name + ": the " + str(r["value"]) + " radio sits outside #intake-form"
        assert r["box"] == BOX_ID, (
            name + ": the " + str(r["value"]) + " radio is not in the audience box")


@pytest.mark.parametrize("name", PAGES)
def test_direct_is_the_checked_default_on_both_intakes(name):
    """A new bid is a Direct bid until somebody says otherwise. The GC board's + New is the one door
    that arrives with GC chosen, and it does that by writing the radio, not through the markup.
    Exactly one radio ships checked, or the browser picks for us.

    Mutation: ship GC checked, or ship both radios unchecked."""
    radios = _parse(name).radios
    assert [r["value"] for r in radios] == ["Direct", "GC"], radios
    assert [r["value"] for r in radios if r["checked"]] == ["Direct"], radios


def test_both_intakes_ask_the_audience_question_the_same_way():
    """One question, one wording, two pages: identical markup once whitespace and attribute order
    are set aside. Each side is checked for having a box at all first, because two empty lists are
    equal and would let a deleted box pass.

    Mutation: reword the hint on one page, or give one page a different class on the radio row."""
    live = _parse("index.html").audience_box
    beta = _parse("polish-intake.html").audience_box
    for label, tokens in (("index.html", live), ("polish-intake.html", beta)):
        assert ("text", "Audience") in tokens and len(_inputs(tokens)) == 2, (
            label + ": the audience box is missing or empty")
    assert live == beta, (
        "the two intakes ask the audience question differently, and Hanz wants the same box on "
        "both. Only on index.html: " + repr([t for t in live if t not in beta])
        + ". Only on polish-intake.html: " + repr([t for t in beta if t not in live]))


_FORM = '<form id="intake-form">'
_BOX = ('<fieldset id="audience-box"><legend>Audience</legend>'
        '<p class="hint">Picks which proposal template the tool fills.</p>'
        '<input type="radio" name="audience" value="Direct" checked>'
        '<input type="radio" name="audience" value="GC"></fieldset>')
_PROJECT = '<fieldset><legend>Project Info</legend></fieldset>'


def test_the_reader_tells_a_wrong_page_from_a_right_one():
    """The tests above are only worth their green if the reader can see each way a page goes wrong.
    These feed it small pages, one right and five wrong or merely respaced, and read back what it
    reports.

    Mutation: make the reader ignore the form tag, or stop it recording the box."""
    right = _parse_text(_FORM + _BOX + _PROJECT + "</form>")
    assert [b["legend"] for b in right.boxes] == ["Audience", "Project Info"]
    assert [r["value"] for r in right.radios if r["checked"]] == ["Direct"]
    assert all(r["in_form"] and r["box"] == BOX_ID for r in right.radios)

    last = _parse_text(_FORM + _PROJECT + _BOX + "</form>")
    assert [b["legend"] for b in last.boxes] == ["Project Info", "Audience"]

    outside = _parse_text(_BOX + _FORM + _PROJECT + "</form>")
    assert [b["legend"] for b in outside.boxes] == ["Project Info"]
    assert [r["in_form"] for r in outside.radios] == [False, False]

    gc_first = _parse_text((_FORM + _BOX + _PROJECT + "</form>")
                           .replace('value="Direct" checked', 'value="Direct"')
                           .replace('value="GC">', 'value="GC" checked>'))
    assert [r["value"] for r in gc_first.radios if r["checked"]] == ["GC"]

    reworded = _parse_text((_FORM + _BOX + _PROJECT + "</form>").replace("Picks which", "Chooses which"))
    assert reworded.audience_box != right.audience_box

    respaced = _parse_text((_FORM + _BOX + _PROJECT + "</form>")
                           .replace("><", ">\n      <")
                           .replace('name="audience" value="Direct"', 'value="Direct"   name="audience"'))
    assert respaced.audience_box == right.audience_box, "whitespace and attribute order must not count"
