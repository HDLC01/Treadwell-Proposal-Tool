"""Page 1 of the Proposal step, laid out the way it prints -- the editor half of the 2026-10-02 audit.

Audit (staging, Direct epoxy Test project "Release check 9-26", the editor against its 4-page PDF):
  #9  the REGARDS name drew in Zetta Serif. Its run carries no font of its own, and Word prints such
      a run in the document default -- docDefaults -> theme1.xml's minor latin face, Cambria.
  #10 the Options heading sat ~16pt lower than the PDF prints it, because the PRICE lines the page
      composes carried 2pt / 4pt / 1pt margins and the page's 1.32 line height, where the document
      prints each as the paragraph it is cloned from: no space before or after, 1.25 of the face's
      own single line.
  #11 "Longer than this box" and Fit to text on a PRICE box whose words ended two thirds of the
      way down it: the test counted the blank spacer paragraphs every template ends its boxes with.
  #12 a second red rule a few px under the PRICE/NOTES frame line: the over-long marker, drawn at
      the bottom of the ELEMENT (as tall as its content), not where the printed box ends.
  #13 yellow ticks under the Job Name and after "Notes:": the highlight's padding around an empty
      value.

RUN, NOT READ, where the claim is about behaviour: js/editor-layout-harness.js lifts the shipped
functions and lays page 1 out with a stated model of the browser's block layout (see its header).
What no harness can show is a real browser's paint; the browser walk each item still needs is
listed in the commit and the report.
"""
import io
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import zipfile

import pytest
from starlette.requests import Request

import main

BACKEND = pathlib.Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "editor-layout-harness.js"
JS = (FRONTEND / "js" / "proposal-review.js").read_text(encoding="utf-8")
CSS = (FRONTEND / "styles.css").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

TEMPLATES = [("epoxy", "Direct"), ("combo", "Direct"), ("polish", "Direct"), ("gyp", "Direct"),
             ("epoxy", "GC")]

# THE PDF, measured. The audited job's .docx built by the real _generate (values off the audit:
# $5,569 base, $11 material tax, $5,580 total, one $5,283 option, broken out) and rendered by
# LibreOffice headless in the production base image (python:3.11-slim@sha256:e416...b41e, the
# Dockerfile's apt fonts, Zetta Serif mounted), read back with PyMuPDF: each line's baseline in pt,
# minus the PRICE box's top (320.95pt, /api/proposal-template geometry). The staging PDF the audit
# downloaded agrees to the pixel at 220 dpi.
PDF_PRICE_BASELINES = {"heading_base": 9.55, "base": 21.65, "sales_tax": 33.80, "total": 45.95,
                       "options": 81.25, "option": 93.35}
# What the editor drew before this fix, measured off the audit's screenshot at 1440 wide
# (k = 1.1728): the Options heading 97.5pt below the box top. The harness's model gives 96.7 for
# the code before the fix, which is how the model is known to describe the browser.
EDITOR_OPTIONS_BEFORE = 97.5


def _req(path, method="GET"):
    return Request({"type": "http", "headers": [], "method": method, "path": path, "query_string": b""})


def _payload(wt, aud):
    return json.loads(main.api_proposal_template(_req("/api/proposal-template"), wt, aud).body)


def _run(payloads, frontend=FRONTEND):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(payloads, fh)
        name = fh.name
    try:
        proc = subprocess.run(["node", str(HARNESS), str(frontend), name], capture_output=True,
                              text=True, encoding="utf-8", timeout=180)
    finally:
        pathlib.Path(name).unlink(missing_ok=True)
    assert proc.returncode == 0, (
        "the harness itself failed; read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def ran():
    return _run({"%s:%s" % (wt, aud): _payload(wt, aud) for wt, aud in TEMPLATES})


# ═══ #9: the face a run with no font of its own prints in ═════════════════════════════════════
def _theme_default_face(docx_path):
    """What Word prints a run with no w:rFonts in: docDefaults' rFonts, through theme1.xml."""
    z = zipfile.ZipFile(docx_path)
    styles = z.read("word/styles.xml").decode("utf-8")
    dd = re.search(r"<w:docDefaults>.*?</w:docDefaults>", styles, re.S).group(0)
    rf = re.search(r"<w:rFonts [^>]*/>", dd).group(0)
    direct = re.search(r'w:ascii="([^"]+)"', rf)
    if direct:
        return direct.group(1)
    theme = re.search(r'w:asciiTheme="(major|minor)', rf).group(1)
    xml = z.read("word/theme/theme1.xml").decode("utf-8")
    block = re.search(r"<a:%sFont>(.*?)</a:%sFont>" % (theme, theme), xml, re.S).group(1)
    return re.search(r'<a:latin typeface="([^"]*)"', block).group(1)


def _proposal_templates():
    root = BACKEND / "templates"
    return sorted(p for sub in ("Direct", "GC", "Gyp") for p in (root / sub).glob("*.docx"))


def test_every_template_prints_an_unstated_run_in_the_face_the_editor_uses():
    """The editor's DOC_DEFAULT_FONT is the resolution of every template's own default, so a run the
    server reports with `font: null` is drawn in the face the document prints it in."""
    face = re.search(r'\n  const DOC_DEFAULT_FONT = "([^"]+)";', JS).group(1)
    for path in _proposal_templates():
        assert _theme_default_face(path) == face, path.name


def test_null_only_ever_means_that_default():
    """No template run, and no style, names a THEME font of its own (asciiTheme / hAnsiTheme), so a
    run the server finds no font for -- it reads w:ascii on the run and its style chain -- takes
    docDefaults and nothing else. If a template ever does, the server has to resolve it (the field
    the report names), because this page cannot see the theme."""
    for path in _proposal_templates():
        z = zipfile.ZipFile(path)
        doc = z.read("word/document.xml").decode("utf-8")
        assert not re.search(r"<w:rFonts [^>]*w:(ascii|hAnsi)Theme=", doc), path.name
        styles = re.sub(r"<w:docDefaults>.*?</w:docDefaults>", "",
                        z.read("word/styles.xml").decode("utf-8"), flags=re.S)
        assert not re.search(r"<w:rFonts [^>]*w:(ascii|hAnsi)Theme=", styles), path.name


def test_the_regards_name_is_drawn_in_cambria_and_zetta_runs_keep_zetta(ran):
    got = ran["fonts"]
    assert got["face"] == "Cambria"
    assert got["estimator"]["text"] == "Hanz de la Cruz"
    assert got["estimator"]["fonts"] == ["'Cambria', Georgia, 'Times New Roman', serif"], got
    assert set(got["zetta"]["fonts"]) == {"'Zetta Serif Book', Georgia, 'Times New Roman', serif"}
    assert got["nullRunsLeft"] == 0


def test_words_typed_into_a_runless_line_are_drawn_in_the_face_they_print_in(ran):
    """A text-box paragraph with no run prints typed words as a bare run: the document default, the
    same as the REGARDS name. The Terms flow is left alone this round."""
    got = ran["fonts"]
    assert got["runless"]["typed"] == "Cambria"
    assert got["runless"]["blockFont"] == "'Cambria', Georgia, 'Times New Roman', serif"
    assert got["termsRunless"]["blockFont"] == ""


def test_a_face_the_server_names_is_the_one_used(ran):
    """When /api/proposal-template sends `default_font`, the page uses it instead of its own
    resolution."""
    assert ran["fonts"]["named"]["fonts"] == ["'Caladea', Georgia, 'Times New Roman', serif"]


# ═══ #10: the PRICE lines are as tall as they print ═════════════════════════════════════════════
def test_the_options_heading_sits_where_the_pdf_prints_it(ran):
    got = ran["price:epoxy:Direct"]["baselines"]
    assert abs(got["options"] - PDF_PRICE_BASELINES["options"]) <= 1.5, (got, PDF_PRICE_BASELINES)
    assert EDITOR_OPTIONS_BEFORE - got["options"] > 14, "the audited gap is not what this fixed"
    for k, pdf in PDF_PRICE_BASELINES.items():
        assert abs(got[k] - pdf) <= 2.5, (k, got[k], pdf)


def test_the_gap_above_options_is_two_lines_as_tall_as_the_row_above_it(ran):
    """#568's real, editable blank lines stay -- two of them by default -- and each is as tall as
    the PDF's: the Total row's own 1.25 line, no margin."""
    got = ran["price:epoxy:Direct"]
    assert got["gapLines"] == 2
    for g in got["styles"]["gap"]:
        assert (g["mt"], g["mb"]) == ("0", "0"), g
        assert float(g["lh"]) == pytest.approx(300 / 240 * 1.045, abs=1e-5), g
    gap = got["baselines"]["options"] - got["baselines"]["total"]
    pdf = PDF_PRICE_BASELINES["options"] - PDF_PRICE_BASELINES["total"]
    assert abs(gap - pdf) <= 1.0, (gap, pdf)


def test_the_gap_copies_the_row_above_it_never_a_line_typed_on_it(ran):
    """The writer models every blank line of the gap, and every line typed on it, on the price row
    above the heading (_apply_options_gap). On the Polish file that row (the Total, 1.15) and the
    heading (1.25) are spaced differently, so a gap that copied the typed line -- whose own key is
    the heading's -- would draw 1.25 lines the document prints at 1.15."""
    got = ran["polishGap"]
    one15 = "%g" % round(276 / 240 * 1.045, 5)
    assert got["total"] == one15 and got["heading"] == "%g" % round(300 / 240 * 1.045, 5), got
    assert got["gap"] == [one15, one15], got
    assert [t["text"] for t in got["typed"]] == ["A line typed on the gap"], got
    assert all((t["lh"], t["mt"], t["mb"]) == (one15, "0", "0") for t in got["typed"]), got


def test_a_gap_line_carries_no_margin_of_its_own():
    """The stylesheet's default for a blank line, which is what it has until paintOptionsGap puts the
    row's spacing on it -- and all it has when the row above has no record to read: no margin, as
    the writer's blank paragraph has none (it used to be the 2pt the price rows carried)."""
    body = re.sub(r"/\*.*?\*/", "", _rule(".tw-gap-line"), flags=re.S)
    assert re.search(r"(?m)^\s*margin:\s*0;", body) or re.search(r"\bmargin:\s*0;", body), body


@pytest.mark.parametrize("key", ["epoxy:Direct", "combo:Direct"])
def test_every_composed_price_line_takes_its_paragraphs_spacing(ran, key):
    """No margin the document does not print, and the paragraph's own line: on these two files every
    PRICE paragraph is `line=300 lineRule=auto`, no space before or after."""
    styles = ran["price:" + key]["styles"]
    for name in ("heading_base", "base", "total", "options", "option"):
        s = styles[name]
        assert (s["mt"], s["mb"]) == ("0", "0"), (name, s)
        assert float(s["lh"]) == pytest.approx(1.30625, abs=1e-5), (name, s)


def test_the_line_height_is_the_files_multiple_of_the_faces_single_line():
    """1.045em: Zetta Serif's hhea ascender (760) + descender (240) + lineGap (45) on a 1000-unit
    em, the figure LibreOffice multiplies (8pt rows at 1.15 print 9.61pt apart, 1.25 ones 10.45pt).
    Only an AUTO line is scaled, and no template's Terms and Conditions paragraph has one."""
    assert re.search(r"\n  const SINGLE_LINE_EM = 1\.045;", JS)
    for wt, aud in TEMPLATES:
        for b in _payload(wt, aud)["blocks"]:
            if b["txbx"] is None:
                sp = (b.get("para") or {}).get("spacing") or {}
                assert not sp.get("line"), (wt, aud, b["id"], sp)


def _real_font():
    import proposal_fonts
    for folder in proposal_fonts.FONT_DIRS:
        f = folder / proposal_fonts.FONTS["zetta-serif-book"]
        if f.is_file():
            return f
    return None


@pytest.mark.skipif(_real_font() is None, reason="the licensed Zetta Serif files are not on this "
                    "machine (CI never has them)")
def test_the_constant_is_the_fonts_own_single_line():
    import struct
    data = _real_font().read_bytes()
    n = struct.unpack(">H", data[4:6])[0]
    tables = {data[12 + 16 * i:16 + 16 * i].decode("latin-1"):
              struct.unpack(">I", data[20 + 16 * i:24 + 16 * i])[0] for i in range(n)}
    upm = struct.unpack(">H", data[tables["head"] + 18:tables["head"] + 20])[0]
    asc, desc, gap = struct.unpack(">hhh", data[tables["hhea"] + 4:tables["hhea"] + 10])
    assert (asc - desc + gap) / upm == pytest.approx(1.045)


# ═══ #11: only words past the bottom edge are "longer than this box" ═══════════════════════════
def test_blank_spacers_under_the_words_are_not_an_overflow(ran):
    """The audited job, and the same box with four options: the box's content (spacers included)
    runs past the printed height on the second, the words do not -- so neither says it is too long
    or offers to grow."""
    got = ran["overflow"]
    for case in ("audited", "longer"):
        c = got[case]
        assert c["inkPx"] < c["designPx"], c
        assert not c["overflow"] and not c["canGrow"] and not c["blocked"], c
    assert got["longer"]["contentPx"] > got["longer"]["designPx"], (
        "the case no longer has spacers past the bottom; it no longer tests the bug")


def test_words_past_the_bottom_edge_still_say_so(ran):
    over = ran["overflow"]["over"]
    assert over["inkPx"] > over["designPx"] and over["overflow"] and over["blocked"], over


def test_fit_to_text_grows_to_the_words_not_the_spacers(ran):
    fit = ran["overflow"]["fit"]
    assert fit["overflow"] and fit["canGrow"], fit
    assert fit["grew"] is True
    # Exactly the words' reach (rounded up to 0.01pt), not the 224pt the spacers under them reach.
    assert fit["grownHPt"] == pytest.approx(fit["inkPt"], abs=0.02), fit
    assert fit["grownHPt"] < fit["contentPx"] * 72 / 96 - 20, fit


def test_a_box_whose_lines_are_not_laid_out_is_measured_as_before(ran):
    """The fallback the other harnesses' boxes (and any line the page cannot read) take."""
    assert ran["overflow"]["unmeasured"] == {"ink": None, "content": 321}


# ═══ #12: the marker sits where the printed box ends ═══════════════════════════════════════════
def _rule(selector):
    found = [m.group(1) for m in re.finditer(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS)]
    assert found, "%s has no top-level rule in styles.css" % selector
    return "\n".join(found)


def test_the_over_long_marker_is_drawn_at_the_printed_height(ran):
    body = re.sub(r"/\*.*?\*/", "", _rule(".tw-txbx.tw-notes-overflow"), flags=re.S)
    assert "box-shadow" not in body, "the marker is back at the element's own bottom edge"
    assert re.search(r"background-position:\s*0 var\(--tw-box-end, 100%\)", body), body
    assert re.search(r"background-size:\s*100% 2px", body), body
    # applyBoxGeom keeps the variable on the printed height -- the design's, and a grown one's.
    assert ran["overflow"]["over"]["boxEnd"] == "calc(164.5pt - 2px)"
    assert ran["overflow"]["fit"]["boxEndAfter"] == "calc(%spt - 2px)" % ran["overflow"]["fit"]["grownHPt"]


# ═══ #13: a blank value draws no highlight ═════════════════════════════════════════════════════
def _specificity(sel):
    s = re.sub(r"::[a-z-]+", "", sel)
    return (len(re.findall(r"#[\w-]+", s)),
            len(re.findall(r"\.[\w-]+|\[[^\]]+\]|:(?!:)[\w-]+", s)),
            len(re.findall(r"(?:^|[\s>+~])[a-z][\w-]*", s)))


def test_an_empty_fill_paints_no_tick():
    """The highlight's background and its 1px of padding are taken off an EMPTY fill, by a rule no
    other `.tw-fill` rule outranks; a fill with a value keeps both."""
    empty = re.sub(r"/\*.*?\*/", "", _rule(".tw-fill:empty"), flags=re.S)
    assert re.search(r"background:\s*none", empty) and re.search(r"padding:\s*0", empty), empty
    base = _rule(".tw-fill")
    assert "background: #ffe975" in base and "padding: 0 1px" in base
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    mine = _specificity(".tw-fill:empty")
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", re.sub(r"@media[^{]*\{", "", css)):
        for sel in (s.strip() for s in m.group(1).split(",")):
            if ".tw-fill" not in sel or sel == ".tw-fill:empty":
                continue
            if re.search(r"(?m)^\s*(background|padding)[\w-]*\s*:", m.group(2)):
                assert _specificity(sel) < mine and "!important" not in m.group(2), (sel, m.group(2))
