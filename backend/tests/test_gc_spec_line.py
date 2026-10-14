"""The GC proposal's spec line, and the Drawings & specs box that feeds it.

Reported by Will through Hanz, 2026-10-12: typing a Spec section on the intake did not make the
proposal say so. The spec was not "replaced", or the line still said "(NO spec)" next to it. And:
"the drawings and specs should only be for the general contractor".

WHAT WAS FOUND, by running the code rather than reading it:

  * The spec section DID reach the proposal. Both intakes save it as typed, the v2 test copy carries
    it, and the writer and the editor both put it on the line. What printed beside it was Kyle's
    trailing "(NO spec)", which was plain words in the template and so printed whatever the spec
    said: "per Spec 033543-A & Drawings by Gould dated 10/1/26 (NO spec)". That is the bug.
  * An estimator who sees that and edits the paragraph to take the words out freezes everything on
    the line at that moment: a placeholder spec ("033543") stays, and a spec typed later never
    replaces it. That is the second half of "it doesn't get replaced", and it goes away with the
    first, because there is nothing left to edit out.
  * Will's own recent GC draft on prod holds a blank spec section, and its editor state is keyed to
    the Direct template because the editor was opened while the Audience box still said Direct. The
    editor asks for `audience=state.audience` on every load (pinned below), so reopening it as GC
    gets the GC template and its own keyed edits; nothing in the page pairs one audience's edits
    with the other's file.
  * The Drawings & specs box showed for every audience. Direct proposals have no such lines.

WHAT THIS FILE PINS.

  1. A filled spec prints without "(NO spec)" on all three GC files, through the writer and through
     /api/generate. A blank one prints Kyle's own paragraph, character for character.
  2. The editor draws the same words (its real withTokenDefaults, lifted from proposal-review.js,
     against the writer's rule, over every kind of blank).
  3. A GC audience picks the GC template in the editor; a Direct proposal never prints the fields.
  4. The Drawings & specs box is shown for a GC and hidden for Direct on BOTH intakes, hidden and
     never removed, so what was typed is still there.
  5. A typed spec reaches the saved draft from the v2 intake (through the real readForm) and the
     v2 intake repaints the box once it has filled the radios.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

import main
import proposal_writer as pw
import test_gc_template_tokens as gct

client = TestClient(main.app)

BACKEND = gct.BACKEND
FRONTEND = BACKEND.parent / "frontend"
FRONTEND_JS = FRONTEND / "js"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "audience-box-harness.js"

POLISH, RESINOUS, SEALER, GC_FILES = gct.POLISH, gct.RESINOUS, gct.SEALER, gct.GC_FILES
WORK_TYPE = gct.WORK_TYPE
NO_SPEC = "(NO spec)"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

# Every way a field can be "blank" on the wire: missing, null, empty, spaces.
BLANKS = [None, "", "   ", "\t"]
# A spec section is text: a leading zero stays, spaces are fine, a lone "0" is a value.
SPECS = ["033543-A", "09 67 23", "03", "0", "Section 3"]


def _spec_line(out):
    got = [t for t in gct._rendered_lines(out) if "Drawings by" in t]
    assert len(got) == 1, got
    return got[0]


def _raw_spec_line(rel):
    raw = [b["text"] for b in gct._walk(gct.RAW_DIR / pathlib.Path(rel).name) if "Drawings by" in b["text"]]
    assert len(raw) == 1, raw
    return raw[0]


# ── 1. the document ───────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("spec", SPECS)
@pytest.mark.parametrize("rel", GC_FILES)
def test_a_typed_spec_prints_without_the_no_spec_caveat(rel, spec):
    """THE BUG. Mutation: put the words back as plain text in the template (drop the
    no_spec_note rule from annotate_templates.GC_SPAN_RULES) and every case goes red."""
    out = pw.fill_proposal(work_type=WORK_TYPE[rel], audience="GC", values={
        "sqft": "1,600", "cove_lf": "500", "spec_section": spec, "architect": "Gould Evans",
        "drawings_dated_formatted": "8/15/26"})
    line = _spec_line(out)
    assert NO_SPEC not in line, line
    assert line.endswith(f"per Spec {spec} & Drawings by Gould Evans dated 8/15/26"), line
    assert line == line.rstrip(), "a space was left where the caveat was"
    assert "{{" not in line
    assert not [t for t in gct._rendered_lines(out) if NO_SPEC in t]


@pytest.mark.parametrize("blank", BLANKS)
@pytest.mark.parametrize("rel", GC_FILES)
def test_a_blank_spec_prints_kyles_paragraph_exactly(rel, blank):
    """With the spec blank the line is Kyle's own: his placeholder spec number, the architect and
    date placeholders, and "(NO spec)", character for character. Nothing is invented."""
    out = pw.fill_proposal(work_type=WORK_TYPE[rel], audience="GC", values={
        "sqft": "1,600", "cove_lf": "500", "spec_section": blank, "architect": None,
        "drawings_dated_formatted": None})
    assert _spec_line(out) == _raw_spec_line(rel)
    assert _spec_line(out).endswith(" " + NO_SPEC), "the caveat lost its space"


def test_a_missing_spec_key_is_blank_too():
    out = pw.fill_proposal(work_type="polish", audience="GC", values={"sqft": "1,600"})
    assert _spec_line(out) == _raw_spec_line(POLISH)


def test_the_other_fields_do_not_take_the_caveat_off():
    """Only the SPEC section decides it: an architect and a date typed with no spec still say there
    is no spec, which is what the estimator typed."""
    out = pw.fill_proposal(work_type="polish", audience="GC", values={
        "sqft": "1,600", "architect": "Gould Evans", "drawings_dated_formatted": "8/15/26"})
    assert _spec_line(out) == "Polished Concrete: per Spec 033543 & Drawings by Gould Evans dated 8/15/26 (NO spec)"


@pytest.mark.parametrize("work_type", ["polish", "epoxy", "combo"])
def test_the_route_prints_a_typed_spec_without_the_caveat(work_type):
    """/api/generate with what the browser sends: spec_section as typed, drawings_dated as the
    date input's ISO string. The same two answers as the writer, through the route."""
    base = {"project_name": "Spec QA", "bid_date": "2026-10-12", "city_state": "Olathe, KS",
            "sqft": "1,600", "cove_lf": "500", "texture": "", "total_formatted": "$6,307"}
    filled = gct._generate({"work_type": work_type, "audience": "GC", "values": dict(
        base, spec_section="033543-A", architect="Gould Evans", drawings_dated="2026-10-01")})
    assert _spec_line(filled).endswith("per Spec 033543-A & Drawings by Gould Evans dated 10/1/26")
    blank = gct._generate({"work_type": work_type, "audience": "GC", "values": dict(base, spec_section="")})
    rel = POLISH if work_type == "polish" else RESINOUS
    assert _spec_line(blank) == _raw_spec_line(rel)


def test_the_defaults_and_the_callers_values_are_untouched_by_the_rule():
    """The rule works on fill_proposal's own copy: /api/generate writes `values` back onto the draft
    and fills the estimate sheet from them, so neither "(NO spec)" nor "" may land in the caller's."""
    values = {"sqft": "1,600", "spec_section": "033543-A"}
    snapshot = dict(values)
    pw.fill_proposal(work_type="polish", audience="GC", values=values)
    assert values == snapshot and "no_spec_note" not in values


@pytest.mark.parametrize("spec,filled", [(None, False), ("", False), ("  ", False), ("0", True),
                                         (0, True), ("033543", True), (" x ", True)])
def test_the_rule_in_the_writer(spec, filled):
    defaults = {"spec_section": "033543", "no_spec_note": " (NO spec)"}
    got = pw._with_token_defaults({"spec_section": spec}, defaults)
    assert got["no_spec_note"] == ("" if filled else " (NO spec)")
    assert got["spec_section"] == (spec if filled else "033543")


def test_a_template_without_the_token_gets_no_rule():
    """A Direct file has no defaults at all, so nothing is added to the values it is filled with."""
    assert pw._with_token_defaults({"spec_section": "x"}, {}) == {"spec_section": "x"}


# ── 2. Direct proposals never print any of it ─────────────────────────────────────────────────
@pytest.mark.parametrize("work_type", ["polish", "epoxy", "combo"])
def test_a_direct_proposal_never_prints_the_drawings_and_specs_fields(work_type):
    out = gct._generate({"work_type": work_type, "audience": "Direct", "values": {
        "project_name": "Direct QA", "bid_date": "2026-10-12", "city_state": "Olathe, KS",
        "sqft": "1,600", "cove_lf": "500", "texture": "", "total_formatted": "$6,307",
        "spec_section": "ZZ-SPEC-9", "architect": "ZZ Architects", "drawings_dated": "2026-10-01",
        "finish_tag": "ZZ-FIN", "plan_sheet": "ZZ-A1", "addenda_count": 7}})
    text = "\n".join(gct._rendered_lines(out))
    for needle in ("ZZ-SPEC-9", "ZZ Architects", "ZZ-FIN", "ZZ-A1", "10/1/26", NO_SPEC, "Addenda Acknowledged"):
        assert needle not in text, needle


# ── 3. the editor ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("work_type,rel", [("polish", POLISH), ("epoxy", RESINOUS), ("combo", RESINOUS),
                                           ("sealer", SEALER)])
def test_the_editor_is_served_the_token_and_the_default(work_type, rel):
    j = client.get(f"/api/proposal-template?work_type={work_type}&audience=GC").json()
    spec = [b for b in j["blocks"] if "Drawings by" in b["text"]]
    assert len(spec) == 1
    assert spec[0]["text"].endswith("dated {{drawings_dated_formatted}}{{no_spec_note}}"), spec[0]["text"]
    assert j["token_defaults"]["no_spec_note"] == " (NO spec)"
    assert j["token_defaults"] == pw.TEMPLATE_TOKEN_DEFAULTS[rel]


@pytest.mark.parametrize("work_type", ["polish", "epoxy", "combo"])
def test_a_direct_template_has_no_spec_line_and_no_defaults(work_type):
    j = client.get(f"/api/proposal-template?work_type={work_type}&audience=Direct").json()
    assert j["token_defaults"] == {}
    assert not [b for b in j["blocks"] if "Drawings by" in b["text"] or "no_spec_note" in b["text"]]


@needs_node
def test_a_gc_draft_asks_the_editor_for_the_gc_template():
    """The editor's REAL request line, run for a GC draft and a Direct one (initDocumentEditor
    builds it from state.audience on every load), and each answer is the matching file: the GC draft
    gets the GC template whose spec line carries the token. Without this a GC draft whose audience
    the page read as Direct would show Kyle's Direct text, and no spec box would ever fill."""
    src = (FRONTEND_JS / "proposal-review.js").read_text(encoding="utf-8").replace("\r\n", "\n")
    m = re.search(r"async function initDocumentEditor\(\) \{\n(.*?)\n    // The endpoint is auth-gated", src, re.S)
    assert m, "initDocumentEditor no longer starts by reading the work type and audience"
    lit = re.search(r"`(/api/proposal-template\?[^`]*)`", src)
    assert lit, "the editor no longer fetches /api/proposal-template"
    body = m.group(1).replace("effectiveWorkType()", "'polish'")
    urls = {}
    for aud in ({"audience": "GC"}, {"audience": "Direct"}, {}):
        got = gct._node("const state = %s;\nconst wt = 'polish';\n%s\nconsole.log(JSON.stringify(`%s`));"
                        % (json.dumps(aud), body.replace("const wt = 'polish';", "").strip(), lit.group(1)))
        urls[aud.get("audience", "none")] = got
    assert urls["GC"].endswith("work_type=polish&audience=GC"), urls
    assert urls["Direct"].endswith("audience=Direct") and urls["none"].endswith("audience=Direct")
    gc = client.get(urls["GC"]).json()
    direct = client.get(urls["Direct"]).json()
    assert [b["text"] for b in gc["blocks"] if "Drawings by" in b["text"]] != []
    assert [b["text"] for b in direct["blocks"] if "Drawings by" in b["text"]] == []
    assert gc["template_version"] != direct["template_version"]


@needs_node
@pytest.mark.parametrize("rel", GC_FILES)
def test_the_editor_applies_the_same_rule_as_the_writer(rel):
    """The SHIPPED withTokenDefaults, over every kind of blank and of value, against the writer's
    own _with_token_defaults on the same table the editor is served. They have to agree token by
    token, or the page and the PDF say different things on the spec line.

    Mutation: delete the no_spec_note branch from withTokenDefaults (the filled rows go red)."""
    defaults = pw.TEMPLATE_TOKEN_DEFAULTS[rel]
    cases = [{}, {"spec_section": None}, {"spec_section": ""}, {"spec_section": "  "},
             {"spec_section": "033543-A"}, {"spec_section": 0}, {"spec_section": "0"},
             {"spec_section": "", "architect": "Gould Evans"}]
    js = FRONTEND_JS / "proposal-review.js"
    got = gct._node(
        gct._lift(js, "withTokenDefaults") + "\n"
        + "let templateTokenDefaults = %s;\n" % json.dumps(defaults)
        + "console.log(JSON.stringify(%s.map(withTokenDefaults)));" % json.dumps(cases))
    want = [pw._with_token_defaults(c, defaults) for c in cases]
    assert got == want
    assert [g["no_spec_note"] for g in got] == [" (NO spec)"] * 4 + ["", "", "", " (NO spec)"]


@needs_node
def test_a_template_without_the_token_gets_no_note_in_the_editor():
    js = FRONTEND_JS / "proposal-review.js"
    got = gct._node(gct._lift(js, "withTokenDefaults") + "\nlet templateTokenDefaults = {};\n"
                    "console.log(JSON.stringify(withTokenDefaults({spec_section: 'x'})));")
    assert got == {"spec_section": "x"}


# ── 4. the template files and what saved edits do across the swap ─────────────────────────────
@pytest.mark.parametrize("rel", GC_FILES)
def test_the_caveat_is_one_token_and_the_words_are_gone_from_the_file(rel):
    walk = gct._walk(BACKEND / "templates" / rel)
    line = [b["text"] for b in walk if "Drawings by" in b["text"]]
    assert len(line) == 1 and NO_SPEC not in line[0] and line[0].endswith("{{no_spec_note}}"), line
    assert gct._tokens(BACKEND / "templates" / rel)["no_spec_note"] == 2     # mc:Choice + mc:Fallback


@pytest.mark.parametrize("rel", GC_FILES)
def test_an_edit_saved_against_the_previous_install_still_prints(rel):
    """Edits stamped with the 2026-10-02 hash (the hash of the file this change replaces) are still
    replayed, like the original predecessor's. A paragraph the estimator edited keeps his words."""
    import template_versions as tv
    prev = tv.PREDECESSOR_VERSIONS[rel][1][-1]
    assert prev == tv.content_version(gct.PREDECESSORS_1002 / pathlib.Path(rel).name)
    assert tv.accepts(prev, BACKEND / "templates" / rel)
    work_type = {POLISH: "polish", RESINOUS: "epoxy", SEALER: "sealer"}[rel]
    body = {"work_type": work_type, "audience": "GC", "template_version": prev,
            "values": {"project_name": "Prev QA", "sqft": "1,600", "cove_lf": "500"},
            "paragraph_overrides": [{"id": 99, "text": "PREV-HEADER-EDIT"}]}
    assert "PREV-HEADER-EDIT" in gct._rendered_lines(gct._generate(body))


# ── 5. the Drawings & specs box follows the audience, on both intakes ─────────────────────────
@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, (
        "the harness itself failed, read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


PAGES = ["index.html", "polish-intake.html"]


@needs_node
def test_the_module_rule(ran):
    assert ran["unit"]["gc"] == [True] * 4
    assert ran["unit"]["notGc"] == [False] * 7
    assert ran["unit"]["noBox"] == "ok"


@needs_node
@pytest.mark.parametrize("page", PAGES)
def test_the_box_is_hidden_for_direct_and_shown_for_gc(ran, page):
    """Mutation: make applyAudience always show (or drop the change listener) and this goes red."""
    r = ran["pages"][page]
    assert r["defaultChecked"] == ["Direct"] and r["opensAs"] == "none", "a new bid shows the box"
    assert (r["afterGC"], r["afterDirect"], r["afterGCAgain"]) == ("", "none", "")


@needs_node
@pytest.mark.parametrize("page", PAGES)
def test_hiding_the_box_keeps_what_was_typed(ran, page):
    """Hide, never remove: the box and its inputs stay in the form, so the draft keeps the values
    and a Direct proposal simply does not print them."""
    r = ran["pages"][page]
    assert r["boxStillThere"] is True and r["valueKept"] == "033543-A"
    assert r["boxInForm"] is True
    assert r["boxInputs"] == ["drawings_dated", "addenda_count", "spec_section", "finish_tag", "plan_sheet"]


@needs_node
@pytest.mark.parametrize("page", PAGES)
def test_a_hidden_box_cannot_cancel_continue_with_a_value_nobody_can_see(ran, page):
    """The form is checked natively on Continue. A 2.5 or -1 typed in Addenda under GC, then Audience
    switched to Direct, would cancel the submit on a hidden field with no message. So the number
    box's limits are set aside while the box is hidden and restored exactly when it shows.
    Mutation: drop paintLimits from applyAudience and the hidden list is not empty."""
    r = ran["pages"][page]
    assert r["limitsDrawn"] == ["min=0", "step=1"], "the page's own limits changed: " + str(r["limitsDrawn"])
    assert r["limitsOpenHidden"] == [] and r["limitsHidden"] == [], "a hidden box still carries limits"
    assert r["limitsShown"] == r["limitsBack"] == r["limitsDrawn"], "the limits did not come back"


@needs_node
@pytest.mark.parametrize("page", PAGES)
def test_a_draft_saved_as_gc_opens_with_the_box_showing(ran, page):
    """index.js fills the radios as it loads, so audience-box.js must run after it; the v2 intake
    fills them later and calls sync() (pinned below). pageshow covers Back."""
    r = ran["pages"][page]
    assert r["opensRestoredGC"] == "" and r["afterPageshow"] == ""
    assert (r["beforeSync"], r["afterSync"]) == ("none", "")
    assert r["nothingTicked"] == "none", "no radio ticked reads as Direct"
    assert r["afterOtherChange"] == "none", "a change on another field toggled the box"


@needs_node
@pytest.mark.parametrize("page", PAGES)
def test_a_page_without_the_box_or_form_is_left_alone(ran, page):
    r = ran["pages"][page]
    assert r["noBoxThrew"] is False and r["noFormThrew"] is False


@needs_node
def test_the_script_order_on_each_page(ran):
    live = ran["pages"]["index.html"]["scripts"]
    assert live.index("/js/intake-scope.js") < live.index("/js/index.js") < live.index("/js/audience-box.js"), live
    v2 = ran["pages"]["polish-intake.html"]["scripts"]
    assert v2.index("/js/intake-scope.js") < v2.index("/js/audience-box.js") < v2.index("/js/polish-intake.js"), v2


def test_both_intakes_draw_the_same_five_fields_in_the_same_box():
    """The two pages ask the same thing the same way, so the box that hides is the same box."""
    def box(name):
        html = (FRONTEND / name).read_text(encoding="utf-8")
        i = html.index('<fieldset id="drawings-specs-box">')
        part = html[i:html.index("</fieldset>", i)]
        return re.findall(r'name="(\w+)"', part)
    assert box("index.html") == box("polish-intake.html") == [
        "drawings_dated", "addenda_count", "spec_section", "finish_tag", "plan_sheet"]
