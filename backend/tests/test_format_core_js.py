"""The proposal editor's run algebra, exercised under node.

Hanz asked for the Proposals tab to "act like a microsoft word": select some words, change
their size or weight, and have that reach the customer's .docx. Phase 1 made formatting
survive the trip. This is Phase 2 — the controls — and the arithmetic underneath them is
where a quiet wrong answer does the most damage, because every failure still *looks* like
something happened:

  * Off-by-one offsets format the wrong words. The estimator selects "Base Bid" and the bold
    lands on "ase Bid " — visible, but only if you look closely at a document you have
    already decided is correct.
  * `absent` vs `false`. An absent key means "inherit the template"; `false` means
    "explicitly off". Collapsing the two either strips Kyle's design from every untouched run
    or makes "turn italic off" impossible on a paragraph whose style is italic. The backend's
    `_set_paragraph_runs` reads them as different instructions, so this file has to keep them
    different too.
  * Toggling on a mixed selection. Dragging across a partly-bold line and pressing B has to
    bold all of it. If "some is bold" reads as "it is bold", the button un-bolds instead —
    the opposite of what was asked.
  * Token boundaries. A `.tw-fill` span is a live estimate value. Merging runs across one
    dissolves it on the next render, freezing a computed price into hand-typed text.
  * Word's own paste markup. Word writes `font-weight:bold` as a WORD. `Number("bold")` is
    NaN, so a numeric-only test reads Word's bold as NOT bold — losing exactly the formatting
    somebody copied in on purpose.

The functions live in frontend/js/proposal-format-core.js rather than inside the page's
IIFE for one specific reason: the per-template override tests taught that a test exercising
a *mirror* of the shipped logic proves nothing (13 passed while only 1 caught a deliberate
break). proposal-review.js calls these same functions, so a break here is a break there.

Skipped when node isn't installed; it's on the dev box and in the Docker image.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
CORE = FRONTEND / "js" / "proposal-format-core.js"
PAGE = FRONTEND / "js" / "proposal-review.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is not installed")


def run(script: str):
    """Run `script` with `F` bound to the module; returns its printed JSON."""
    prelude = (
        "const F = require(%s);\n"
        "const out = (v) => console.log(JSON.stringify(v === undefined ? '<undefined>' : v)"
        ".replace(/[\\u0080-\\uffff]/g,"
        " (c) => '\\\\u' + c.charCodeAt(0).toString(16).padStart(4, '0')));\n"
        % json.dumps(str(CORE))
    )
    proc = subprocess.run(["node", "-e", prelude + script],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


PLAIN = "[{text:'Hello world',tok:null}]"


def test_the_module_loads():
    """A syntax error would make every test below fail with the same opaque message."""
    assert run("out(typeof F.patchRuns)") == "function"


# ── offsets: format exactly the selected characters ───────────────────
def test_a_patch_lands_on_exactly_the_selected_characters():
    got = run("out(F.patchRuns(%s, 6, 11, {bold:true}))" % PLAIN)
    assert [r["text"] for r in got] == ["Hello ", "world"]
    assert got[0].get("bold") is None, "the unselected half was formatted"
    assert got[1]["bold"] is True


def test_a_patch_in_the_middle_of_a_run_splits_it_into_three():
    got = run("out(F.patchRuns(%s, 6, 8, {bold:true}))" % PLAIN)
    assert [r["text"] for r in got] == ["Hello ", "wo", "rld"]
    assert [r.get("bold") for r in got] == [None, True, None]


def test_the_whole_block_is_a_valid_selection():
    got = run("out(F.patchRuns(%s, 0, 11, {size_pt:11}))" % PLAIN)
    assert len(got) == 1 and got[0]["size_pt"] == 11
    assert got[0]["text"] == "Hello world", "text must never change when only format does"


def test_a_patch_never_alters_the_text():
    """The single most damaging possible bug: the arithmetic drops or duplicates characters in
    a document that then goes to a customer."""
    for a, b in ((0, 0), (0, 1), (3, 3), (5, 6), (0, 11), (11, 11), (4, 99)):
        got = run("out(F.patchRuns(%s, %d, %d, {bold:true}))" % (PLAIN, a, b))
        assert "".join(r["text"] for r in got) == "Hello world", (a, b)


def test_a_patch_spanning_several_runs_covers_all_of_them():
    runs = "[{text:'aa',tok:null},{text:'bb',tok:null,italic:true},{text:'cc',tok:null}]"
    got = run("out(F.patchRuns(%s, 1, 5, {bold:true}))" % runs)
    assert "".join(r["text"] for r in got) == "aabbcc"
    bolded = "".join(r["text"] for r in got if r.get("bold") is True)
    assert bolded == "abbc"


# ── absent vs false vs null ───────────────────────────────────────────
def test_an_untouched_run_keeps_no_key_at_all():
    """Absent means "inherit". If a patch wrote `bold: false` onto neighbours, every edit
    would strip the template's own weight from the rest of the paragraph."""
    got = run("out(F.patchRuns(%s, 0, 5, {bold:true}))" % PLAIN)
    tail = [r for r in got if r["text"] == " world"][0]
    assert "bold" not in tail


def test_an_explicit_false_is_kept_as_false():
    got = run("out(F.patchRuns(%s, 0, 5, {italic:false}))" % PLAIN)
    assert got[0]["italic"] is False, "explicit off collapsed into inherit"


def test_a_null_patch_deletes_the_key_rather_than_writing_null():
    """This is what Reset and "Template size" mean: go back to inheriting. Writing an explicit
    `false`/`0` instead would pin the paragraph away from the template forever."""
    runs = "[{text:'abc',tok:null,bold:true,size_pt:14}]"
    got = run("out(F.patchRuns(%s, 0, 3, {bold:null, size_pt:null}))" % runs)
    assert "bold" not in got[0] and "size_pt" not in got[0]


# ── merging ───────────────────────────────────────────────────────────
def test_identical_neighbours_merge_back_into_one_run():
    """Formatting and then un-formatting has to leave ONE run, or repeated edits would grow the
    override payload past the 500-override cap for no reason."""
    got = run("out(F.patchRuns(F.patchRuns(%s, 0, 5, {bold:true}), 0, 5, {bold:null}))" % PLAIN)
    assert len(got) == 1 and got[0]["text"] == "Hello world"


def test_runs_never_merge_across_a_token_fill():
    """A `.tw-fill` span is a live estimate value. Merging across one dissolves it on the next
    render, turning a computed price into frozen hand-typed text."""
    runs = "[{text:'Total ',tok:null},{text:'$1,000',tok:'lump_sum'}]"
    got = run("out(F.coalesce(%s))" % runs)
    assert len(got) == 2, "the fill was merged into the plain text beside it"
    assert got[1]["tok"] == "lump_sum"


def test_a_patch_across_a_fill_keeps_the_fill_separate():
    runs = "[{text:'Total ',tok:null},{text:'$1,000',tok:'lump_sum'}]"
    got = run("out(F.patchRuns(%s, 0, 12, {bold:true}))" % runs)
    assert [r["tok"] for r in got] == [None, "lump_sum"]
    assert all(r["bold"] is True for r in got)


# ── the toggle decision ───────────────────────────────────────────────
def test_a_mixed_selection_reports_mixed_not_a_value():
    runs = "[{text:'aa',tok:null,bold:true},{text:'bb',tok:null}]"
    assert run("out(F.summarize(%s, 0, 4).bold)" % runs) == "<undefined>"
    assert run("out(F.summarize(%s, 0, 2).bold)" % runs) is True
    assert run("out(F.summarize(%s, 2, 4).bold)" % runs) is None


def test_toggling_a_mixed_selection_turns_it_on():
    """Dragging across a partly-bold line and pressing B must bold all of it. Reading "some is
    bold" as "it is bold" would un-bold instead — the opposite of the ask."""
    assert run("out(F.nextToggle(undefined))") is True
    assert run("out(F.nextToggle(null))") is True, "inherited is not 'on'"
    assert run("out(F.nextToggle(false))") is True
    assert run("out(F.nextToggle(true))") is False


def test_summarize_ignores_runs_outside_the_selection():
    runs = "[{text:'aa',tok:null,bold:true},{text:'bb',tok:null,size_pt:8}]"
    assert run("out(F.summarize(%s, 0, 2).size_pt)" % runs) is None
    assert run("out(F.summarize(%s, 2, 4).size_pt)" % runs) == 8


# ── sizes ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("css,expect", [
    ("12pt", 12), ("9.5pt", 9.5), ("16px", 12), ("13.333px", 10),
    ("1.2em", None), ("larger", None), ("", None), ("0pt", None), ("-4pt", None),
])
def test_a_pasted_size_is_read_in_points(css, expect):
    """Word pastes pt, browsers px. Anything else has no answer without a computed context, so
    it must inherit rather than guess."""
    assert run("out(F.parseSizePt(%s))" % json.dumps(css)) == expect


def test_absurd_sizes_are_clamped_not_passed_through():
    assert run("out(F.parseSizePt('900pt'))") == 72
    assert run("out(F.parseSizePt('0.5pt'))") == 4


# ── Word's paste markup ───────────────────────────────────────────────
def test_words_literal_font_weight_bold_is_read_as_bold():
    """THE paste regression. Word writes `font-weight:bold`, not a number, and
    `Number("bold")` is NaN — so a numeric-only comparison reads Word's own bold as NOT
    bold, silently dropping the formatting somebody copied in on purpose."""
    assert run("out(F.fmtFromPasted('SPAN', {fontWeight:'bold'}, {}).bold)") is True
    assert run("out(F.fmtFromPasted('SPAN', {fontWeight:'700'}, {}).bold)") is True
    assert run("out(F.fmtFromPasted('SPAN', {fontWeight:'400'}, {}).bold)") is False
    assert run("out(F.fmtFromPasted('SPAN', {fontWeight:'normal'}, {}).bold)") is False


@pytest.mark.parametrize("tag,key", [
    ("B", "bold"), ("STRONG", "bold"), ("I", "italic"), ("EM", "italic"), ("U", "underline"),
])
def test_the_formatting_tags_map_to_switches(tag, key):
    assert run("out(F.fmtFromPasted(%s, {}, {}).%s)" % (json.dumps(tag), key)) is True


def test_an_inline_style_overrides_the_tag_it_sits_on():
    """`<b style="font-weight:normal">` is Word's way of cancelling a wrapper. The more
    specific statement has to win, or pasted text comes in bold that isn't."""
    assert run("out(F.fmtFromPasted('B', {fontWeight:'normal'}, {}).bold)") is False


def test_pasted_formatting_is_inherited_by_children():
    got = run("out(F.fmtFromPasted('SPAN', {}, {bold:true, size_pt:9}))")
    assert got["bold"] is True and got["size_pt"] == 9


def test_only_the_four_supported_switches_come_out():
    """The point of the sanitiser: colours, fonts, backgrounds, mso-* junk and classes must not
    ride along into the .docx, because nothing downstream carries them."""
    got = run("out(F.fmtFromPasted('SPAN', {fontWeight:'bold', color:'red', "
              "backgroundColor:'yellow', fontFamily:'Comic Sans MS', letterSpacing:'2px'}, {}))")
    assert set(got) <= {"bold", "italic", "underline", "size_pt"}, got


def test_underline_is_read_from_either_decoration_property():
    assert run("out(F.fmtFromPasted('SPAN', {textDecorationLine:'underline'}, {}).underline)") is True
    assert run("out(F.fmtFromPasted('SPAN', {textDecoration:'underline'}, {}).underline)") is True
    assert run("out(F.fmtFromPasted('SPAN', {textDecorationLine:'none'}, {}).underline)") is False


# ── splice, for paste ─────────────────────────────────────────────────
def test_a_paste_replaces_the_selection():
    got = run("out(F.spliceRuns(%s, 6, 11, [{text:'there',tok:null,bold:true}]))" % PLAIN)
    assert "".join(r["text"] for r in got) == "Hello there"
    assert [r["text"] for r in got if r.get("bold")] == ["there"]


def test_a_paste_at_the_caret_inserts_without_deleting():
    got = run("out(F.spliceRuns(%s, 5, 5, [{text:',',tok:null}]))" % PLAIN)
    assert "".join(r["text"] for r in got) == "Hello, world"


# ── the page really uses this module ──────────────────────────────────
def test_the_page_calls_the_core_rather_than_its_own_copy():
    """The whole value of the tests above depends on proposal-review.js calling THESE
    functions. If the page kept private copies, every test here could pass while the shipped
    editor did something else — which is exactly how the per-template override tests managed
    to be green and useless."""
    src = PAGE.read_text(encoding="utf-8")
    body = "\n".join(l for l in src.split("\n") if not l.strip().startswith(("//", "*", "/*")))
    for name in ("coalesce", "sliceRuns", "patchRuns", "runsLength", "parseSizePt"):
        assert ("function %s(" % name) not in body, (
            "proposal-review.js defines its own %s; the tests would stop guarding the page" % name)
    assert "window.TWFmt" in body, "the page never reaches for the shared module"
    for call in ("F.summarize(", "F.nextToggle(", "F.fmtFromPasted(", "F.spliceRuns("):
        assert call in body, "the page does not call %s" % call


def test_the_core_is_loaded_before_the_page():
    """`const F = window.TWFmt` runs at parse time, so a missing or late script tag is an
    immediate TypeError and the whole editor fails to initialise."""
    html = (FRONTEND / "proposal-review.html").read_text(encoding="utf-8")
    i = html.find("proposal-format-core.js")
    j = html.find("proposal-review.js?")
    assert i != -1, "proposal-review.html never loads proposal-format-core.js"
    assert i < j, "the core must be loaded BEFORE proposal-review.js"
