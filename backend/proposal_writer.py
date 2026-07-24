"""
Proposal Word-doc writer.

Takes a dict of values + a work_type + an audience, picks the right
Treadwell proposal template, runs `{{token}}` Jinja-style substitution,
returns the filled .docx as bytes.

Kyle's templates in `templates/Direct/`, `templates/GC/`,
`templates/Gyp/` were copied straight from his Numbers 5.7.26 folder.
For v1 they need to be **annotated** with `{{token}}` placeholders
before this writer can fill them — see TEMPLATE_PREP.md (or the
"template prep" Phase in the plan file).

If a template has zero `{{tokens}}`, the writer still returns the file
unchanged with a logged warning — the user gets a usable starter
document; they just have to copy values manually for that template
until tokens are added.

Multi-system support (v2, added 2026-06):
    `fill_proposal` accepts an optional `systems` list. Each item is a
    per-system dict (e.g. system_name, texture, scope_notes, sqft,
    lump_sum). When a template contains a repeatable BLOCK delimited by
    a `{{#system}}` paragraph and a `{{/system}}` paragraph that are
    SIBLINGS in the same container (body, one table cell, or one text
    box), the writer clones the paragraphs between those markers once
    per system, substituting `{{system.field}}` (or bare `{{field}}`)
    tokens against each system dict.

    This is 100% backward-compatible: a template with no `{{#system}}`
    marker, called with `systems=None` (the default), behaves exactly
    like v1 — flat `{{token}}` substitution against `values` only.
    See docs/MULTI-SYSTEM-PROPOSAL.md for the annotation workflow.
"""
from __future__ import annotations

import copy
import io
import logging
import math
import re
from pathlib import Path
from typing import Any, Mapping

import docx
from docx.document import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.text.run import Run


log = logging.getLogger("proposal_tool.proposal_writer")

TEMPLATES_ROOT = Path(__file__).parent / "templates"


# ─── Template selection ───────────────────────────────────────────────
# (work_type, audience) → relative template path. None audience means
# the template is audience-agnostic (e.g. gypsum, budget).
TEMPLATE_PICKER: dict[tuple[str, str | None], str] = {
    ("epoxy",   "Direct"): "Direct/XX.XX TREADWELL EPOXY PROPOSAL - New Direct.docx",
    ("epoxy",   "GC"):     "GC/xx TREADWELL RESINOUS PROPOSAL - xx.docx",
    ("polish",  "Direct"): "Direct/xx.xx TREADWELL POLISH PROPOSAL - NewDirect.docx",
    ("polish",  "GC"):     "GC/xx TREADWELL POLISH PROPOSAL - xx.docx",
    ("combo",   "Direct"): "Direct/xx.xx.xx TREADWELL COMBO PROPOSAL - CUSTMOER NAME.docx",
    # No dedicated GC combo template — use the GC Resinous (covers the
    # epoxy/resinous side in GC format) instead of falling back to a Direct doc.
    ("combo",   "GC"):     "GC/xx TREADWELL RESINOUS PROPOSAL - xx.docx",
    ("sealer",  "GC"):     "GC/xx TREADWELL SEALER PROPOSAL - xx.docx",
    ("gyp",     None):     "Gyp/xx TREADWELL UNDERLAYMENT PROPOSAL - xx.docx",
    ("budget",  "Direct"): "Direct/xx.xx TREADWELL BUDGET PRICING.docx",
}


def pick_template(work_type: str, audience: str | None) -> Path:
    """Resolve (work_type, audience) → absolute template path.

    Falls back to ('epoxy', 'Direct') if the combination isn't mapped,
    so the tool never hard-fails on an unmapped audience.
    """
    key = (work_type, audience)
    if key not in TEMPLATE_PICKER:
        # Try audience-agnostic fallback (e.g. gyp ignores audience).
        if (work_type, None) in TEMPLATE_PICKER:
            key = (work_type, None)
        else:
            log.warning(
                "No template for (%s, %s); falling back to (epoxy, Direct)",
                work_type, audience,
            )
            key = ("epoxy", "Direct")
    return TEMPLATES_ROOT / TEMPLATE_PICKER[key]


# ─── Token substitution ───────────────────────────────────────────────
TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def _replace_in_paragraph(p: Paragraph, values: Mapping[str, Any]) -> int:
    """Replace `{{token}}` in a paragraph, preserving EACH run's formatting.

    Word splits text across multiple <w:r> runs whenever formatting changes —
    e.g. a BOLD "Scope:" label run followed by a NORMAL-weight
    "{{scope_notes}}" value run. The substituted value must keep its OWN run's
    formatting (font, size, bold), not inherit the leading run's. The old code
    collapsed the whole paragraph into run[0], which made every value bold like
    its label. We now rewrite the token's text in place across only the runs it
    actually spans (see `_sub_runs_preserving`).
    """
    if "{{" not in p.text:
        return 0
    return _sub_runs_preserving(
        p._p, TOKEN_RE,
        lambda m: str(values[m.group(1)]) if m.group(1) in values else None,
    )


def _iter_all_paragraphs(d: Document):
    """Yield every paragraph in the doc — body + tables + headers/footers + text boxes.

    python-docx's default `d.paragraphs` skips text in tables, headers,
    footers, and floating text boxes (shapes). For proposal templates
    where the project info often lives in a text box at the top of the
    page, we need to walk the document XML and yield every <w:p>.
    """
    yield from d.paragraphs

    # Tables (recursive — table cells can contain nested tables)
    def walk_table(t):
        for row in t.rows:
            for cell in row.cells:
                yield from cell.paragraphs
                for nested in cell.tables:
                    yield from walk_table(nested)

    for table in d.tables:
        yield from walk_table(table)

    # Headers / footers
    for section in d.sections:
        for hp in section.header.paragraphs:
            yield hp
        for fp in section.footer.paragraphs:
            yield fp

    # Text boxes / shapes — these live in w:txbxContent inside the body XML.
    # Wrap each <w:p> we find there as a Paragraph object.
    body = d.element.body
    for txbx in body.iter(qn("w:txbxContent")):
        for p_elem in txbx.iter(qn("w:p")):
            yield Paragraph(p_elem, d)


# ─── Repeatable per-system blocks ─────────────────────────────────────
# A block is delimited by two marker paragraphs that are SIBLINGS in the
# same parent <w:txbxContent> / <w:tc> / <w:body>:
#
#     {{#system}}      ← start marker paragraph (whole paragraph is removed)
#     ... template ... ← cloned once per system
#     {{/system}}      ← end marker paragraph (whole paragraph is removed)
#
# Inside a block, `{{system.field}}` (and bare `{{field}}` as a fallback)
# resolve against each system dict; any other `{{token}}` is left alone
# here and picked up later by the normal flat pass against `values`.
#
# Cloning operates on plain <w:p> elements only — never on the enclosing
# drawing/shape — so it is safe inside floating text boxes (no drawing-id
# or VML-fallback duplication problems). The whole block must therefore
# live inside ONE container (one text box, one table cell, or the body).
# Name-capturing block markers — `{{#<name>}}` / `{{/<name>}}` — so any named
# list can drive a repeatable block (`system`, `price_line`, `alternate`, …).
_WORK_ANCHOR_RE = re.compile(r"^\s*(?:scope|schedule|exclusions)\s*:", re.I)


def _set_run_bold(run_elem, value: bool) -> None:
    """Set an explicit bold value without disturbing the run's other styling."""
    rpr = run_elem.find(qn("w:rPr"))
    if rpr is None:
        rpr = OxmlElement("w:rPr")
        run_elem.insert(0, rpr)
    bold = rpr.find(qn("w:b"))
    if bold is None:
        bold = OxmlElement("w:b")
        rpr.append(bold)
    if value:
        bold.attrib.pop(qn("w:val"), None)
    else:
        bold.set(qn("w:val"), "0")


def _set_direct_run_text(run_elem, text: str) -> None:
    """Replace one run's visible text/break children, retaining its rPr."""
    for child in list(run_elem):
        if child.tag in (qn("w:t"), qn("w:br"), qn("w:tab")):
            run_elem.remove(child)
    t = OxmlElement("w:t")
    run_elem.append(t)
    _write_t_text(t, text)


def _normalize_work_label_formatting(d: Document) -> int:
    """Make WORK-box labels bold through their first colon, values normal."""
    changed = 0
    for txbx in d.element.body.iter(qn("w:txbxContent")):
        paragraphs = list(txbx.iter(qn("w:p")))
        if not any(_WORK_ANCHOR_RE.match(_own_text(p).strip()) for p in paragraphs):
            continue
        for p_elem in paragraphs:
            text = _own_text(p_elem)
            colon = text.find(":")
            if colon < 0:
                continue
            # A colon occurring later in prose (for example the Gyp terms'
            # "following: access to …") is not a label/value row.
            label = text[:colon].strip()
            if not label or len(label) > 48 or any(ch in label for ch in ".?!"):
                continue
            offset = 0
            passed_colon = False
            for run_elem in list(p_elem.findall(qn("w:r"))):
                # Drawing/object runs only anchor artwork or nested text boxes.
                run_text = "".join(t.text or "" for t in run_elem.iter(qn("w:t")))
                if not run_text:
                    continue
                start, end = offset, offset + len(run_text)
                offset = end
                if passed_colon or start > colon:
                    _set_run_bold(run_elem, False)
                    changed += 1
                    continue
                if start <= colon < end:
                    split_at = colon - start + 1
                    if split_at < len(run_text):
                        suffix = copy.deepcopy(run_elem)
                        _set_direct_run_text(run_elem, run_text[:split_at])
                        _set_direct_run_text(suffix, run_text[split_at:])
                        _set_run_bold(suffix, False)
                        run_elem.addnext(suffix)
                    _set_run_bold(run_elem, True)
                    changed += 1
                    passed_colon = True
                else:
                    _set_run_bold(run_elem, True)
                    changed += 1
    return changed


BLOCK_START_RE = re.compile(r"\{\{\s*#\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
BLOCK_END_RE = re.compile(r"\{\{\s*/\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def _dotted_token_re(name: str) -> "re.Pattern":
    """`{{<name>.field}}` — dotted per-item token for a given block name."""
    return re.compile(r"\{\{\s*" + re.escape(name) + r"\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def _p_text(p_elem) -> str:
    """Joined text of a raw <w:p> element (across all its <w:t> runs)."""
    return "".join(t.text or "" for t in p_elem.iter(qn("w:t")))


def _own_text(p_elem) -> str:
    """Like `_p_text`, but STOPS at a nested `<w:txbxContent>` — a paragraph
    that merely anchors a floating text box (the drawing lives in one of its
    runs) must not report that box's entire contents as its own text, since
    the box's inner paragraphs are walked and reported independently (see
    `_iter_body_editable`). Without this, a top-level anchor paragraph's
    `_p_text` would recurse into every nested `<w:t>` — including the whole
    text box's worth of paragraphs concatenated into one string — corrupting
    both the editor's `text` field for that paragraph and any block-marker
    detection run against it. A paragraph with no nested text box behaves
    identically to `_p_text`.
    """
    out = []
    txbx_tag = qn("w:txbxContent")
    for t in p_elem.iter(qn("w:t")):
        nested = False
        anc = t.getparent()
        while anc is not None and anc is not p_elem:
            if anc.tag == txbx_tag:
                nested = True
                break
            anc = anc.getparent()
        if not nested:
            out.append(t.text or "")
    return "".join(out)


def _set_t_multiline(t, text: str) -> None:
    """Write `text` into a <w:t>, rendering embedded newlines as <w:br/> line
    breaks within the same run (so stacked per-item notes share one bullet).
    The raw-lxml item path doesn't go through python-docx's run.text setter,
    which would otherwise convert \\n → <w:br/> for us — so we do it here."""
    parts = text.split("\n")
    t.text = parts[0]
    t.set(qn("xml:space"), "preserve")
    anchor = t
    for part in parts[1:]:
        br = OxmlElement("w:br")
        anchor.addnext(br)
        nt = OxmlElement("w:t")
        nt.set(qn("xml:space"), "preserve")
        nt.text = part
        br.addnext(nt)
        anchor = nt


def _write_t_text(t, text: str) -> None:
    """Set a <w:t>'s text, preserving whitespace and rendering \\n as <w:br/>."""
    if "\n" in text:
        _set_t_multiline(t, text)
    else:
        t.text = text
        t.set(qn("xml:space"), "preserve")


def _sub_runs_preserving(p_elem, pattern, repl, require_braces: bool = True) -> int:
    """Substitute `pattern` matches across a paragraph's runs WITHOUT collapsing
    run formatting.

    The replacement text lands in the run where the match STARTS, and any text
    before/after the match stays in its own run — so a normal-weight value run
    keeps its weight even when an earlier label run is bold (the fix for values
    inheriting the bold "Scope:" label). `repl(match) -> str | None`; returning
    None leaves that match untouched (e.g. a token not in this scope's values),
    so later/known tokens still resolve.

    Works on any element with <w:t> descendants (a python-docx paragraph's `_p`
    or a raw cloned block <w:p>), so both substitution phases share one engine.

    `require_braces` (default True) short-circuits paragraphs with no `{{` — the
    right optimization for the `{{token}}` passes. Pass False to substitute a
    plain-text pattern that isn't a token (e.g. rewriting a hardcoded amount that
    spans runs); the caller's `repl` must then return None once the match already
    equals the replacement, or the loop would rewrite it forever.
    """
    n = 0
    guard = 0
    while guard < 2000:
        guard += 1
        tnodes = list(p_elem.iter(qn("w:t")))
        if not tnodes:
            break
        texts = [(t.text or "") for t in tnodes]
        joined = "".join(texts)
        if require_braces and "{{" not in joined:
            break
        chosen = None
        for m in pattern.finditer(joined):
            r = repl(m)
            if r is not None:
                chosen = (m, r)
                break
        if chosen is None:
            break
        m, value = chosen
        s, e = m.start(), m.end()
        spans = []
        pos = 0
        for txt in texts:
            spans.append((pos, pos + len(txt)))
            pos += len(txt)
        si = so = ei = eo = None
        for i, (a, b) in enumerate(spans):
            if si is None and a <= s < b:
                si, so = i, s - a
            if a < e <= b:
                ei, eo = i, e - a
        if si is None:
            break
        if ei is None:                      # match runs to the very end
            ei, eo = len(tnodes) - 1, len(texts[-1])
        before, after = texts[si][:so], texts[ei][eo:]
        if si == ei:
            _write_t_text(tnodes[si], before + value + after)
        else:
            _write_t_text(tnodes[si], before + value)   # value keeps si's format
            for j in range(si + 1, ei):
                tnodes[j].text = ""
            tnodes[ei].text = after                      # 'after' keeps ei's format
            tnodes[ei].set(qn("xml:space"), "preserve")
        n += 1
    return n


def _substitute_item_tokens(p_elem, item: Mapping[str, Any], block_name: str) -> None:
    """Replace `{{<block>.field}}` / bare `{{field}}` in one cloned <w:p>,
    preserving each run's formatting (see `_sub_runs_preserving`).

    `{{<block>.field}}` always resolves against `item`; bare `{{field}}`
    resolves against `item` ONLY when the key exists there — any other
    `{{token}}` (e.g. {{state_name}}) is left for the flat pass.
    """
    if "{{" not in _p_text(p_elem):
        return
    dotted = _dotted_token_re(block_name)
    _sub_runs_preserving(
        p_elem, dotted,
        lambda m: str(item[m.group(1)]) if m.group(1) in item else None,
    )
    _sub_runs_preserving(
        p_elem, TOKEN_RE,
        lambda m: str(item[m.group(1)]) if m.group(1) in item else None,
    )


# A `{{#price_line}}` row whose amount is empty is a label-only heading row
# (e.g. the combo breakout's restored "Options:" separator — see main.py's
# `_combo_lines` handling). The template paragraph hardcodes the separator as
# literal text between the two tokens —
# `{{price_line.amount_formatted}} – {{price_line.label}}` — not a token
# itself, so once `amount_formatted` substitutes to "" the rendered text
# starts with a bare "– " before the label. Match hyphen, en dash, or em
# dash so this isn't brittle to which one a given template uses.
_LEADING_SEP_RE = re.compile(r"^\s*[-–—]\s*")


def _strip_leading_separator(p_elem) -> None:
    """Strip a leading `<amount> <dash> ` separator off an already-substituted
    price_line paragraph whose amount was empty.

    Operates on the rendered text across all of the paragraph's `<w:t>` runs
    (the separator may land in the same run as the tokens, as it currently
    does, or in a run of its own if a template is authored differently) and
    trims exactly the matched leading characters off the front run(s), so any
    remaining text keeps its own run/formatting untouched. No-op if the
    paragraph doesn't start with a separator (e.g. a normal priced row).
    """
    tnodes = list(p_elem.iter(qn("w:t")))
    if not tnodes:
        return
    joined = "".join(t.text or "" for t in tnodes)
    m = _LEADING_SEP_RE.match(joined)
    if not m or m.end() == 0:
        return
    remaining = m.end()
    for t in tnodes:
        if remaining <= 0:
            break
        cur = t.text or ""
        if len(cur) <= remaining:
            remaining -= len(cur)
            t.text = ""
        else:
            t.text = cur[remaining:]
            t.set(qn("xml:space"), "preserve")
            remaining = 0


def _strip_bullet(p_elem) -> None:
    """Remove list/bullet formatting (`<w:numPr>`) from a paragraph so a blank
    NOTES item renders as clean vertical spacing — a genuinely empty line —
    rather than a lone empty bullet dot. No-op if the paragraph isn't a list
    item. (The empty `<w:t>` from the substitution already makes the line
    blank; this just drops its bullet glyph.)"""
    ppr = p_elem.find(qn("w:pPr"))
    if ppr is None:
        return
    numpr = ppr.find(qn("w:numPr"))
    if numpr is not None:
        ppr.remove(numpr)


_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
# Default text-box insets when <a:bodyPr> omits them (OOXML defaults): 0.1" L/R,
# 0.05" T/B. In points.
_TXBX_INSET_LR_PT = 0.1 * 72 * 2      # left + right
_TXBX_INSET_TB_PT = 0.05 * 72 * 2     # top + bottom
# Rough proportional-font metrics for Carlito/Calibri body text: average glyph
# advance ≈ 0.5·fontSize, single line height ≈ 1.2·fontSize. Biased slightly
# toward OVER-estimating height (wider glyph, taller line) so we err on the side
# of shrinking a hair MORE rather than clipping. The floor mirrors the editor's
# on-screen fitTxbx (0.60).
_TXBX_GLYPH_W = 0.50
_TXBX_LINE_H = 1.20
_TXBX_SCALE_FLOOR = 0.60


def _estimate_txbx_scale(txbx, box: dict | None) -> float:
    """Estimate the font scale (0.60–1.0) needed for a text box's content to fit
    its fixed design height. Returns 1.0 when it already fits or geometry is
    unknown. Pure estimate (no renderer) — see the metric constants above."""
    if not box:
        return 1.0
    w_pt, h_pt = box.get("w_pt"), box.get("h_pt")
    if not w_pt or not h_pt or w_pt <= 0 or h_pt <= 0:
        return 1.0
    lIns, rIns, tIns, bIns = _txbx_insets(txbx)   # actual box insets (padding must reduce usable height)
    usable_w = w_pt - (lIns + rIns) / _EMU_PER_PT
    usable_h = h_pt - (tIns + bIns) / _EMU_PER_PT
    if usable_w <= 0 or usable_h <= 0:
        return 1.0
    content_h = 0.0
    for p in txbx.iter(qn("w:p")):
        text = "".join(t.text or "" for t in p.iter(qn("w:t")))
        sz = p.find(".//" + qn("w:sz"))
        try:
            font_pt = int(sz.get(qn("w:val"))) / 2.0 if sz is not None else 9.0
        except (TypeError, ValueError):
            font_pt = 9.0
        if font_pt <= 0:
            font_pt = 9.0
        chars_per_line = max(1.0, usable_w / (_TXBX_GLYPH_W * font_pt))
        lines = max(1, math.ceil(len(text) / chars_per_line))   # empty para → 1 line of height
        content_h += lines * _TXBX_LINE_H * font_pt
    if content_h <= usable_h or content_h <= 0:
        return 1.0
    return max(_TXBX_SCALE_FLOOR, usable_h / content_h)


def _shape_of_txbx(txbx):
    el = txbx.getparent()
    for _ in range(4):
        if el is None:
            return None
        if el.tag.endswith("}wsp"):
            return el
        el = el.getparent()
    return None


# OOXML default text-box insets (EMU) when <a:bodyPr> omits them.
_DEF_TXBX_INS = {"lIns": 91440, "rIns": 91440, "tIns": 45720, "bIns": 45720}


def _txbx_insets(txbx):
    """(lIns, rIns, tIns, bIns) in EMU for a text box, reading its <bodyPr> and
    falling back to the OOXML defaults."""
    ins = dict(_DEF_TXBX_INS)
    shape = _shape_of_txbx(txbx)
    if shape is not None:
        for bp in shape.iter():
            if bp.tag.endswith("}bodyPr"):
                for k in ins:
                    v = bp.get(k)
                    if v is not None:
                        try:
                            ins[k] = int(v)
                        except (TypeError, ValueError):
                            pass
                break
    return ins["lIns"], ins["rIns"], ins["tIns"], ins["bIns"]


def _scale_txbx_runs(txbx, scale: float) -> None:
    """Directly shrink every run's font size in a text box by `scale`.

    Why not autofit: LibreOffice-headless (our docx→PDF engine) does NOT apply
    DrawingML text autofit — neither an empty <a:normAutofit/> nor one with an
    explicit fontScale shrinks the render (verified on staging: the last WORK line
    still clipped). It DOES always honor explicit run sizes (<w:sz>), so we scale
    those directly. Size-less runs inherit — we give them the box's most common
    size so they shrink too. Floored at 4pt so nothing vanishes."""
    sizes = [int(v) for sz in txbx.iter(qn("w:sz"))
             if (v := sz.get(qn("w:val"))) and v.isdigit()]
    default_hp = max(set(sizes), key=sizes.count) if sizes else 18   # half-points; 18 = 9pt
    for r in txbx.iter(qn("w:r")):
        rpr = r.find(qn("w:rPr"))
        cur = None
        if rpr is not None:
            sz = rpr.find(qn("w:sz"))
            v = sz.get(qn("w:val")) if sz is not None else None
            if v and v.isdigit():
                cur = int(v)
        new_hp = max(8, int(round((cur if cur is not None else default_hp) * scale)))
        if rpr is None:
            rpr = OxmlElement("w:rPr")
            r.insert(0, rpr)
        for tag in ("w:sz", "w:szCs"):
            el = rpr.find(qn(tag))
            if el is None:
                el = OxmlElement(tag)
                rpr.append(el)
            el.set(qn("w:val"), str(new_hp))


def _shrink_overflowing_text_boxes(d: Document) -> int:
    """Keep long text-box content from spilling past its fixed box (over the next
    box / the baked page-frame art) — e.g. a combo's two options + exclusions,
    whose last line ("*Assumes installation over…") was overdrawn by the PRICE
    frame (the "cut-off last line" bug).

    Kyle's boxes are fixed-size (<a:noAutofit/>). The obvious fix — flip to
    <a:normAutofit/> "shrink text on overflow" — is a NO-OP under LibreOffice-
    headless (it doesn't compute/apply DrawingML autofit, with or without an
    explicit fontScale). So for boxes we estimate to overflow, we shrink the RUN
    sizes directly (which LibreOffice always honors), mirroring the editor's
    on-screen `fitTxbx` so preview == generated doc. We still flip noAutofit→
    normAutofit (harmless; lets Word re-fit if the doc is opened there). Boxes
    that already fit are untouched (byte-identical output)."""
    NO, NORM = f"{{{_A_NS}}}noAutofit", f"{{{_A_NS}}}normAutofit"
    try:
        boxes = template_geometry(d).get("boxes", [])
    except Exception:                       # geometry is best-effort; never block generation
        boxes = []
    n = 0
    for i, txbx in enumerate(_iter_txbx(d)):
        shape = _shape_of_txbx(txbx)
        af = None
        if shape is not None:
            af = shape.find(f".//{NO}")
            if af is None:
                af = shape.find(f".//{NORM}")
        if af is None:
            continue
        af.tag = NORM
        af.attrib.pop("fontScale", None)    # empty normAutofit; we shrink runs directly below
        af.attrib.pop("lnSpcReduction", None)
        scale = _estimate_txbx_scale(txbx, boxes[i] if i < len(boxes) else None)
        if scale < 0.999:
            _scale_txbx_runs(txbx, scale)
        n += 1
    # Straggler noAutofit not paired to a geometry box: preserve the old intent.
    for na in list(d.element.iter(NO)):
        na.tag = NORM
        n += 1
    return n


def _force_terms_on_new_page(d: Document) -> bool:
    """Make the "TERMS AND CONDITIONS" section start on a fresh page.

    Kyle's templates have NO forced break before the T&C heading — they rely on
    the body flowing onto a later page, which fails for the combo (its body is
    short): the heading + its terms-page letterhead land on the bottom of page 1,
    over the ACCEPTANCE frame. We set <w:pageBreakBefore/> on the terms
    letterhead's host paragraph — the empty paragraph that anchors the terms-page
    PNG (positionV relative to that paragraph), immediately before the heading —
    so the letterhead AND heading move to the new page together. pageBreakBefore
    never inserts a blank page, so templates whose T&C already starts a page are
    unaffected. Budget pricing has no T&C section → no-op."""
    tops = [c for c in d.element.body if c.tag == qn("w:p")]
    h = None
    for i, p in enumerate(tops):
        if "".join(t.text or "" for t in p.iter(qn("w:t"))).strip().upper() == "TERMS AND CONDITIONS":
            h = i
            break
    if h is None:
        return False
    target = tops[h]
    for j in range(h, max(-1, h - 4), -1):          # heading + up to 3 paras before it
        if list(tops[j].iter(qn("wp:anchor"))):      # the terms-page letterhead's host paragraph
            target = tops[j]
            break
    ppr = target.find(qn("w:pPr"))
    if ppr is None:
        ppr = OxmlElement("w:pPr")
        target.insert(0, ppr)
    if ppr.find(qn("w:pageBreakBefore")) is None:
        ppr.insert(0, OxmlElement("w:pageBreakBefore"))
    return True


# Some templates position a framed box's top edge at/above its red frame border
# with zero top-inset, so the first line hugs / rides over the border. Which boxes
# are affected varies PER TEMPLATE (Kyle positioned each individually; verified by
# rendering): the NOTES box crosses on the Polish + Gyp templates (Combo + Epoxy
# are fine); Gyp additionally has its WORK + PRICE boxes touching ("Base Bid" on
# the PRICE border). Give the affected boxes a top inset so the first line clears
# the border. EMU (1pt = 12700). MUST run BEFORE _shrink_overflowing_text_boxes so
# the shrink estimate (which reads the actual inset) accounts for the reduced
# usable height and can't push the WORK box into overflow.
_FRAME_BOX_TOP_INSET_EMU = 114300   # ~9pt
# The gyp template's NOTES content box sits ~0.54" further LEFT than its WORK/PRICE
# boxes (column-relative posH 0.451" vs 0.991"/1.000"), all with a zero left inset,
# so its bullets render on top of the baked-in rotated red "NOTES" gutter label
# (the labels are fixed raster art in the page PNGs — only the content box can move).
# Left-inset the gyp NOTES box so its text clears the label and left-aligns with the
# WORK/PRICE text. EMU (1pt=12700); 39pt ~= the 0.54" posH delta. ONLY the gyp NOTES
# box needs it — polish's NOTES box and gyp's WORK/PRICE already start at the right x.
_GYP_NOTES_LEFT_INSET_EMU = 495300   # ~39pt (~0.54")


def _pad_frame_boxes(d: Document, notes, work_type) -> int:
    """Inset the framed boxes whose text rides over the baked frame art. TOP-inset
    (first line hugs the border): NOTES on polish + gyp, WORK + PRICE additionally on
    gyp. LEFT-inset (bullets overlap the "NOTES" gutter label): the gyp NOTES box
    only. Boxes identified by content markers so the DATE/JOB-NAME/estimator header
    boxes are never touched; the left inset is guarded to the NOTES box (a note
    marker present, no WORK/PRICE marker) so WORK/PRICE are never shifted."""
    wt = str(work_type or "").lower()
    pad_notes = wt in ("polish", "gyp")     # these templates' NOTES box crosses its border
    pad_work_price = wt == "gyp"            # gyp also has WORK + PRICE touching
    left_inset_notes = wt == "gyp"          # gyp NOTES box also overlaps the left gutter label
    if not (pad_notes or pad_work_price):
        return 0
    note_markers, work_price_markers = [], []
    if pad_notes:
        note_keys = [str((n or {}).get("text") or "").strip()[:20] for n in (notes or [])]
        note_markers = [k for k in note_keys if len(k) >= 8][:4]
    if pad_work_price:
        # WORK has "Exclusions:"/"Assumptions:"/"per plans"; PRICE has "Base Bid".
        work_price_markers = ["Base Bid", "Exclusions", "Assumptions", "per plans"]
    if not (note_markers or work_price_markers):
        return 0
    n = 0
    for txbx in _iter_txbx(d):
        txt = "".join(t.text or "" for t in txbx.iter(qn("w:t")))
        is_notes = any(m in txt for m in note_markers)
        is_work_price = any(m in txt for m in work_price_markers)
        if not (is_notes or is_work_price):
            continue
        shape = _shape_of_txbx(txbx)
        if shape is None:
            continue
        for bp in shape.iter():
            if bp.tag.endswith("}bodyPr"):
                try:
                    cur_t = int(bp.get("tIns") or 0)
                except (TypeError, ValueError):
                    cur_t = 0
                if cur_t < _FRAME_BOX_TOP_INSET_EMU:
                    bp.set("tIns", str(_FRAME_BOX_TOP_INSET_EMU))
                    n += 1
                if left_inset_notes and is_notes and not is_work_price:
                    try:
                        cur_l = int(bp.get("lIns") or 0)
                    except (TypeError, ValueError):
                        cur_l = 0
                    if cur_l < _GYP_NOTES_LEFT_INSET_EMU:
                        bp.set("lIns", str(_GYP_NOTES_LEFT_INSET_EMU))
                        n += 1
                break
    return n


def _flatten_price_bullets(d: Document) -> int:
    """Remove list/bullet formatting from the PRICE section so amounts read as
    clean flush-left lines (Kyle: no bullet points in the pricing). Every price
    template puts its PRICE rows — base bid, Material Sales Tax, Remodel, Total,
    {{#price_line}} options, {{#room}}, {{#alternate}} — on list numId=3 (verified
    across all Direct/GC/Gyp templates); NOTES (numId 1), the WORK section
    (numId 4) and Terms (numId 5) keep their bullets. Runs AFTER block expansion
    (so cloned option/room/tax rows are covered) over body + text-box paragraphs.
    Supersedes the older per-row _zero_list_indent hide-the-bullet trick."""
    n = 0
    for p in d.element.body.iter(qn("w:p")):
        ppr = p.find(qn("w:pPr"))
        if ppr is None:
            continue
        numpr = ppr.find(qn("w:numPr"))
        if numpr is None:
            continue
        numid = numpr.find(qn("w:numId"))
        if numid is None or numid.get(qn("w:val")) != "3":
            continue
        ppr.remove(numpr)
        # No longer a list item — pin flush-left so no orphaned hanging indent remains.
        ind = ppr.find(qn("w:ind"))
        if ind is None:
            ind = OxmlElement("w:ind")
            ppr.append(ind)
        ind.set(qn("w:left"), "0")
        ind.set(qn("w:start"), "0")
        n += 1
    return n


def _space_before_options(d: Document, n: int = 2) -> int:
    """Insert `n` blank paragraphs before the PRICE "Options" heading so the
    base-bid Total isn't cramped against the Options section (Kyle: double
    spacing after the Total). Runs AFTER block expansion + substitution over
    body + text-box paragraphs; targets the first standalone "Options" heading.
    No-op for a bid with no options (no heading to anchor to). Blank paragraphs
    inherit the document default height — enough to read as clean line breaks."""
    # Insert before EVERY standalone "Options" heading — a floating text box is
    # duplicated across mc:Choice (DrawingML) + mc:Fallback (VML), and different
    # renderers (Word vs LibreOffice→PDF) pick different copies, so both need the
    # spacing to stay consistent.
    targets = [p for p in d.element.body.iter(qn("w:p"))
               if "".join(t.text or "" for t in p.iter(qn("w:t"))).strip() == "Options"]
    for target in targets:
        for _ in range(n):
            target.addprevious(OxmlElement("w:p"))
    return len(targets)


def _is_total_row(p_elem) -> bool:
    """True for the PRICE block's Total row — the `{{#tax_breakout}}` paragraph
    carrying the `{{total_label}}` / `{{total_formatted}}` token (as opposed to
    the sibling Material Sales Tax row that shares the same block name)."""
    txt = _p_text(p_elem)
    return "{{total_label}}" in txt or "{{total_formatted}}" in txt


def _zero_list_indent(p_elem) -> None:
    """Zero a list paragraph's left indent (`<w:ind w:left="0" w:start="0"/>`) so
    the numbering level's hanging bullet tucks into the margin and doesn't print —
    the same trick Kyle's other PRICE rows use to hide their bullet while keeping
    the text flush left. Keeps `<w:numPr>` intact so spacing/style are unchanged.
    Appended last (after `<w:rPr>`) to match the sibling rows' element order.
    No-op without a pPr; idempotent where the indent is already zeroed."""
    ppr = p_elem.find(qn("w:pPr"))
    if ppr is None:
        return
    ind = ppr.find(qn("w:ind"))
    if ind is None:
        ind = OxmlElement("w:ind")
        ppr.append(ind)
    ind.set(qn("w:left"), "0")
    ind.set(qn("w:start"), "0")


# Base-bid line: `{{base_bid_formatted}} – <description> as described above {{base_tax_phrase}}`.
# The <description> is static text in every template (each work type / audience
# has its own wording, e.g. "Epoxy flooring", "Polished Concrete & Joint Filler"),
# NOT a token — so a display override swaps just the text BETWEEN the two tokens,
# leaving the amount + tax-phrase tokens (and each template's default wording when
# there's no override) untouched. Matches hyphen / en dash / em dash separators.
_BASE_DESC_RE = re.compile(
    r"(\{\{\s*base_bid_formatted\s*\}\}\s*[-–—]\s*).*?(\s*\{\{\s*base_tax_phrase\s*\}\})",
    re.DOTALL,
)


def _apply_base_desc_override(d: Document, desc: str) -> int:
    """Replace the base-bid line's description with `desc`, preserving the
    `{{base_bid_formatted}}`/`{{base_tax_phrase}}` tokens + their separators.

    Operates per `<w:t>` run across the whole document (body + text boxes,
    including the VML-fallback duplicate). The base line is authored as a single
    run in every template, so a template whose base line were split across runs
    simply wouldn't match — a safe no-op that keeps the default wording. Runs
    BEFORE the flat `{{token}}` pass so the anchor tokens are still present.
    """
    if not desc:
        return 0
    n = 0
    for t in d.element.body.iter(qn("w:t")):
        txt = t.text or ""
        if "base_bid_formatted" in txt and "base_tax_phrase" in txt:
            new = _BASE_DESC_RE.sub(lambda m: m.group(1) + desc + m.group(2), txt)
            if new != txt:
                t.text = new
                t.set(qn("xml:space"), "preserve")
                n += 1
    return n


# The GC proposal templates (Resinous/Polish/Sealer) hardcode an additional-phase
# surcharge amount in their Clarifications text — e.g. "Add $5,000 for each
# additional required phase beyond above stated schedule." — each with its OWN
# native default ($5,000 Resinous, $2,300 Polish/Sealer). It is static body text
# in a text box, NOT a {{token}}, and the digits span many single-char runs. When
# the estimator changes the "Add for additional phase" estimate cell, main.py sets
# `_phase_price_override`; we then rewrite JUST the digits in place, keeping "Add $"
# + the clause wording + every run's formatting. Absent → each template keeps its
# own literal default (mirrors `_base_desc_override`: no per-template default to
# drift). Matches only the phase clause (the trailing lookahead), never the "$500"
# mobilization figures elsewhere in the same paragraph.
_GC_PHASE_RE = re.compile(r"(?<=Add \$)[\d,]+(?= for each additional required phase)")
_TXBX_CONTENT = qn("w:txbxContent")


def _apply_gc_phase_override(d: Document, amount: str) -> int:
    """Replace the GC additional-phase amount with `amount` (a bare number string
    like "5,200") across runs, everywhere the clause appears (incl. the VML
    fallback duplicate). No-op if `amount` is falsy or no clause matches.
    """
    if not amount:
        return 0
    n = 0
    for p in d.element.body.iter(qn("w:p")):
        # Skip anchor paragraphs that merely CONTAIN a text box — the box's own
        # <w:p> children (where the clause text actually lives) are visited
        # separately, so processing the anchor too would rewrite runs across the
        # nesting boundary. Leaf paragraphs (incl. the ones inside the box) match.
        if p.find(".//" + _TXBX_CONTENT) is not None:
            continue
        n += _sub_runs_preserving(
            p, _GC_PHASE_RE,
            lambda m: None if m.group(0) == amount else amount,
            require_braces=False,
        )
    return n


# PRICE tax-row + ALTERNATE labels ("Material Sales Tax", "Remodel Tax", "Total",
# "Flooring as described above (…)") are STATIC text trailing their amount token,
# not tokens themselves. When the estimator overrides a label in the doc editor,
# main.py sets a private `_*_label_override` value; we rewrite the text that
# trails the anchor token IN PLACE, preserving runs. Each anchor maps a private
# key to the {{token}} that immediately precedes the label. MUST run in Phase 0.5
# (before block expansion) so the {{#remodel}} / {{#alternate}} ITEM tokens are
# still present as anchors — expansion consumes them.
_PRICE_LABEL_ANCHORS = (
    ("_sales_tax_label_override",    "material_tax_formatted"),
    ("_remodel_label_override",      "remodel.amount_formatted"),
    ("_total_label_override",        "total_formatted"),
    ("_alt_flooring_label_override", "alternate.lump_sum_formatted"),
    ("_alt_remodel_label_override",  "alternate.remodel_tax"),
    ("_alt_total_label_override",    "alternate.total_formatted"),
)


def _apply_price_label_overrides(d: Document, values) -> int:
    """Rewrite each PRICE/ALTERNATE row's static LABEL (the text after its amount
    token) to the estimator's override, preserving runs. Anchored on the amount
    token + separator so the token stays for the flat pass to fill. No-op for any
    label not set; never touches a row whose anchor token isn't present."""
    n = 0
    for key, anchor in _PRICE_LABEL_ANCHORS:
        label = values.get(key)
        if not label:
            continue
        label = str(label)
        # "{{ anchor }} <sep> <rest-of-line>" → keep the token+separator, replace the
        # trailing label. repl returns None once the tail already equals the label
        # (stops the loop) — the token keeps `{{`, so require_braces stays satisfied.
        pat = re.compile(r"(\{\{\s*" + re.escape(anchor) + r"\s*\}\}\s*[–—-]\s*)(.*)$", re.DOTALL)
        def _repl(m, _lbl=label):
            return None if m.group(2) == _lbl else m.group(1) + _lbl
        for p in d.element.body.iter(qn("w:p")):
            # Skip text-box anchor paragraphs (their inner <w:p> are visited on
            # their own) — same nesting guard as _apply_gc_phase_override.
            if p.find(".//" + _TXBX_CONTENT) is not None:
                continue
            n += _sub_runs_preserving(p, pat, _repl)
    return n


# Cove-only WORK rows: after the flat {{token}} fill, an epoxy system with 0 SF
# but a cove clause reads "Area: ~0 SF of epoxy flooring and <n> LF …". Drop the
# meaningless "~0 SF of epoxy flooring and " prefix so it reads "Area: <n> LF …"
# (mirrors the on-screen renderSystemPreview). A 0-SF row with NO cove has no
# " and " after "flooring", so the pattern can't match — it keeps today's line.
_AREA_ZERO_RE = re.compile(r"Area:\s*~0 SF of epoxy flooring and ")


def _drop_zero_sf_prefix(d: Document) -> int:
    n = 0
    for p in d.element.body.iter(qn("w:p")):
        # Skip text-box anchor paragraphs (their <w:p> children are visited on
        # their own) — same nesting guard as _apply_gc_phase_override.
        if p.find(".//" + _TXBX_CONTENT) is not None:
            continue
        # repl returns a fixed "Area: " (never equal to the matched span, and the
        # result no longer contains the pattern) so the require_braces=False loop
        # can't rewrite forever.
        n += _sub_runs_preserving(p, _AREA_ZERO_RE, lambda m: "Area: ", require_braces=False)
    return n


def _expand_named_block(container, block_name: str, items: list[Mapping[str, Any]]) -> int:
    """Expand EVERY `{{#<block_name>}}…{{/<block_name>}}` block in `container`.

    `container` is any element whose direct <w:p> children may hold the markers
    (a <w:body>, <w:tc>, or <w:txbxContent>). One container may hold several
    blocks of different names (e.g. the PRICE cell has {{#price_line}} AND
    {{#alternate}}) — this expands only the blocks whose name matches
    `block_name`, re-scanning after each so element indices stay valid.
    `items==[]` still removes the markers + template body (renders zero rows).
    Returns how many blocks were expanded.
    """
    expanded = 0
    while True:
        children = list(container)
        start_idx = end_idx = None
        for i, child in enumerate(children):
            if child.tag != qn("w:p"):
                continue
            txt = _p_text(child)
            if start_idx is None:
                m = BLOCK_START_RE.search(txt)
                if m and m.group(1) == block_name:
                    start_idx = i
            else:
                m = BLOCK_END_RE.search(txt)
                if m and m.group(1) == block_name:
                    end_idx = i
                    break
        if start_idx is None or end_idx is None:
            break

        # Template paragraphs strictly between the two markers.
        template_elems = children[start_idx + 1:end_idx]
        start_elem = children[start_idx]
        end_elem = children[end_idx]

        # For each item, a fresh deep copy of every template paragraph with
        # per-item tokens substituted.
        new_elems = []
        for item in items:
            for tmpl in template_elems:
                clone = copy.deepcopy(tmpl)
                _substitute_item_tokens(clone, item, block_name)
                # Label-only price_line row (empty amount) — drop the now-bare
                # leading "– " separator so it reads as just the label. Scoped
                # to price_line/empty-amount only; every other row/block is
                # untouched.
                if block_name == "price_line" and not str(item.get("amount_formatted") or "").strip():
                    _strip_leading_separator(clone)
                # Blank NOTES line — estimator's Word-style spacing. Drop the
                # bullet so it renders as an empty line, not an empty bullet dot.
                if block_name == "notes" and not str(item.get("text") or "").strip():
                    _strip_bullet(clone)
                # PRICE Total row: the sibling rows (base bid / Material Sales Tax /
                # Remodel) zero their list indent so the numbering's hanging bullet
                # tucks into the margin and doesn't print; the Polish template's
                # Total row was missed and so shows a lone stray bullet. Match the
                # siblings so the whole PRICE block formats consistently (no-op where
                # the template already zeros it — e.g. the Epoxy template).
                if block_name == "tax_breakout" and _is_total_row(clone):
                    _zero_list_indent(clone)
                new_elems.append(clone)

        for clone in new_elems:
            start_elem.addprevious(clone)
        for stale in [start_elem, end_elem, *template_elems]:
            container.remove(stale)
        expanded += 1
    return expanded


def _expand_all_blocks(d: Document, block_lists: Mapping[str, list]) -> int:
    """Expand every named block in `block_lists` across the whole document.

    Walks the body, every table cell, and every text box (<w:txbxContent>,
    including the VML-fallback duplicate) for each block name — so a block
    authored in any of those locations expands consistently. A block whose
    list is empty is still processed: its markers + template body are stripped
    (zero rows) rather than left as literal `{{#name}}` text in the output.
    """
    total = 0
    body = d.element.body
    containers = [body]
    containers += list(body.iter(qn("w:tc")))
    containers += list(body.iter(qn("w:txbxContent")))
    for block_name, items in block_lists.items():
        for container in containers:
            total += _expand_named_block(container, block_name, list(items or []))
    return total


# ─── Paragraph-editor id mapping (Proposal Review's document editor) ──────
# The web editor shows the estimator the REAL template — every paragraph, in
# document order, as an editable block — instead of the old hand-built HTML
# approximation. `iter_editable_blocks` is the ONE walk shared by:
#   1. `GET /api/proposal-template` (main.py)      — builds the JSON the
#      editor renders.
#   2. `_apply_paragraph_overrides` (below)         — maps an edited block's
#      `id` back to its paragraph when generating.
# Both MUST see the exact same ids for the exact same document, or an edit
# could silently land on the wrong paragraph. That's only guaranteed if both
# walk the PRISTINE template (before Phase 1's block expansion inserts/
# removes paragraphs and shifts every id after it) — see the call site in
# `fill_proposal` for where overrides are applied for that reason.
_MC_FALLBACK_TAG = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"


def _is_fallback_paragraph(p_elem) -> bool:
    """True for a <w:p> living inside the legacy VML `mc:Fallback` branch of a
    floating text box/shape — a byte-for-byte duplicate of the modern
    DrawingML version that `_iter_all_paragraphs` also visits (so old-Word/
    VML readers get filled tokens too). The editor must show ONE copy of each
    paragraph, not two, so every id-based walk below skips these."""
    return any(True for _ in p_elem.iterancestors(_MC_FALLBACK_TAG))


def _iter_body_editable(d: Document):
    """Yield `(p_elem, kind, txbx_idx)` for every REAL (non-Fallback)
    paragraph in the document BODY — top-level paragraphs (`kind="p"`),
    table-cell paragraphs (`kind="cell"`, recursing into nested tables), and
    floating text-box paragraphs (`kind="p"`, `txbx_idx` = the 0-based index
    of the enclosing text box in this walk's box order; `None` outside a
    box). Headers/footers are intentionally excluded (the editor is scoped
    to the body; none of Kyle's templates put tokens there today — see
    `_iter_all_paragraphs`, which still covers them for the flat fill pass).

    Text boxes carry almost all of the customer-facing proposal copy (job
    name, WORK, PRICE, NOTES, SIGN) — Kyle's templates lay the whole front
    page out as floating shapes over blank body paragraphs — so skipping
    them would leave the editor showing nothing but the Terms & Conditions
    boilerplate at the bottom of the document. `txbx_idx` pairs each block
    with its box's page geometry (`template_geometry` enumerates the SAME
    non-Fallback boxes in the SAME order), so the editor can place the
    content exactly where the printed page puts it — even though this walk,
    which defines the ids and therefore can never be reordered, visits body
    paragraphs before text boxes.
    """
    for p in d.paragraphs:
        if not _is_fallback_paragraph(p._p):
            yield p._p, "p", None

    def walk_table(t):
        for row in t.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    if not _is_fallback_paragraph(p._p):
                        yield p._p, "cell", None
                for nested in cell.tables:
                    yield from walk_table(nested)

    for table in d.tables:
        yield from walk_table(table)

    for bi, txbx in enumerate(_iter_txbx(d)):
        for p_elem in txbx.iter(qn("w:p")):
            if not _is_fallback_paragraph(p_elem):
                yield p_elem, "p", bi


def _iter_txbx(d: Document):
    """The document body's REAL (non-Fallback) text boxes, in the one
    canonical order shared by `_iter_body_editable` (block → box pairing)
    and `template_geometry` (box → page position)."""
    for txbx in d.element.body.iter(qn("w:txbxContent")):
        if not _is_fallback_paragraph(txbx):
            yield txbx


def iter_editable_blocks(d: Document):
    """THE shared id-mapping walk (see module note above). Yields
    `(id, kind, p_elem, in_block, text, in_txbx)` for every editable
    paragraph in `d`:

      - `id`       — 0-based index in THIS walk's order (stable as long as
                     the document hasn't been mutated by block expansion).
      - `kind`     — "p" or "cell" (see `_iter_body_editable`).
      - `p_elem`   — the raw `<w:p>` lxml element.
      - `in_block` — the name of the innermost `{{#name}}…{{/name}}` region
                     this paragraph currently sits in (the start/end marker
                     paragraphs themselves count as "in" that block), else
                     `None`. Blocks nest lexically as flat marker pairs among
                     SIBLING paragraphs within one container (see the block-
                     engine docstring above `_expand_named_block`) — e.g.
                     `{{#tax_breakout}}`/`{{#remodel}}` sit inside
                     `{{#single_bid}}` — so a simple stack reproduces it.
      - `text`     — this paragraph's OWN text (`_own_text`, NOT `_p_text` —
                     see that helper for why a naive recursive join would
                     duplicate a nested text box's content onto its anchor
                     paragraph). Block-marker detection uses this same value,
                     so it's computed once and handed to the caller instead
                     of making every caller re-derive it (and risk using the
                     wrong helper).
      - `txbx_idx` — index of the enclosing floating text box (pairs the
                     block with `template_geometry`'s box positions), `None`
                     for plain-body/table paragraphs. Display placement
                     only, never id math.
    """
    stack: list[str] = []
    idx = 0
    for p_elem, kind, txbx_idx in _iter_body_editable(d):
        txt = _own_text(p_elem)
        start_m = BLOCK_START_RE.search(txt)
        if start_m:
            stack.append(start_m.group(1))
        in_block = stack[-1] if stack else None
        end_m = BLOCK_END_RE.search(txt)
        if end_m and stack and stack[-1] == end_m.group(1):
            stack.pop()
        yield idx, kind, p_elem, in_block, txt, txbx_idx
        idx += 1


# ─── Formatting + page-geometry extraction (fidelity rendering) ──────────
# The editor renders the REAL page: run-level formatting (bold lead-ins,
# Zetta Serif sizes/colors), true bullet flags, and the floating text boxes
# placed on the page over the template's baked-in letterhead artwork (Kyle's
# templates draw the DATE:/JOB NAME: labels, the buffalo logo, the red
# PROPOSAL stamp and the bordered WORK/PRICE/NOTES/ACCEPTANCE frame as
# full-page background PNGs — word/media/image1.png etc.).

# Empty body paragraphs are the vertical ruler Word hangs the floating
# anchors off ('paragraph'-relative positionV). Their rendered line height
# isn't in the XML (it's a layout result), so we use a constant calibrated
# against the Direct Epoxy artwork: with 14pt/line the WORK box lands at
# y≈153pt (art: ≈152pt), PRICE at ≈321pt (art: ≈318pt), NOTES at ≈495pt
# (art: ≈490pt). The spec accepts approximate anchoring.
_ANCHOR_LINE_H_PT = 14.0
_EMU_PER_PT = 12700.0


def _fmt_of_run(run: Run, para: Paragraph) -> dict:
    """Resolved character formatting for one run: the run's own font first,
    then up the paragraph-style chain (style.font → base_style.font …, max 4
    hops — cheap, no full Word style resolution). `None` = unresolved; the
    frontend falls back to the page default (Zetta Serif 9pt #404040)."""
    fonts = [run.font]
    st = para.style
    hops = 0
    while st is not None and hops < 4:
        try:
            fonts.append(st.font)
        except Exception:  # noqa: BLE001
            break
        st = getattr(st, "base_style", None)
        hops += 1

    def resolve(attr):
        for f in fonts:
            try:
                v = getattr(f, attr)
            except Exception:  # noqa: BLE001
                v = None
            if v is not None:
                return v
        return None

    color = None
    for f in fonts:
        try:
            c = f.color
            if c is not None and c.type is not None and c.rgb is not None:
                color = str(c.rgb)
                break
        except Exception:  # noqa: BLE001
            pass

    bold, italic, under = resolve("bold"), resolve("italic"), resolve("underline")
    size = resolve("size")
    return {
        "bold": bool(bold) if bold is not None else None,
        "italic": bool(italic) if italic is not None else None,
        "underline": bool(under) if under is not None else None,
        "size_pt": size.pt if size is not None else None,
        "font": resolve("name"),
        "color": color,
    }


def _block_runs(p_elem, para: Paragraph) -> list:
    """The paragraph's own text as formatted segments
    `[{text, bold, italic, underline, size_pt, font, color}]`, with two
    invariants the editor depends on:

      1. `"".join(seg.text) == _own_text(p_elem)` — the frontend verifies
         this and falls back to flat rendering if it ever doesn't hold
         (e.g. hyperlink runs, which aren't direct <w:r> children).
      2. No flat `{{token}}` straddles a segment boundary: each token is its
         own segment carrying the formatting of the run where the match
         STARTS — the same rule `_sub_runs_preserving` applies when actually
         filling the docx, so the preview shows a value with the exact
         formatting the generated document will give it.
    """
    txbx_tag = qn("w:txbxContent")

    def own_run_text(r_elem):
        out = []
        for t in r_elem.iter(qn("w:t")):
            anc, nested = t.getparent(), False
            while anc is not None and anc is not r_elem:
                if anc.tag == txbx_tag:
                    nested = True
                    break
                anc = anc.getparent()
            if not nested:
                out.append(t.text or "")
        return "".join(out)

    raw = []
    for r_elem in p_elem.findall(qn("w:r")):
        txt = own_run_text(r_elem)
        if txt:
            raw.append({"text": txt, **_fmt_of_run(Run(r_elem, para), para)})
    if not raw:
        return []

    joined = "".join(s["text"] for s in raw)
    spans = []
    pos = 0
    for s in raw:
        spans.append((pos, pos + len(s["text"]), s))
        pos += len(s["text"])

    def fmt_at(i):
        for a, b, s in spans:
            if a <= i < b:
                return s
        return spans[-1][2]

    fmt_keys = ("bold", "italic", "underline", "size_pt", "font", "color")

    def seg(a, b, src):
        return {"text": joined[a:b], **{k: src.get(k) for k in fmt_keys}}

    out = []
    cursor = 0
    for m in TOKEN_RE.finditer(joined):
        # non-token stretch before the match: split at run boundaries so a
        # bold lead-in ("Scope:") keeps its weight next to a normal value run
        for a, b, s in spans:
            lo, hi = max(a, cursor), min(b, m.start())
            if lo < hi:
                out.append(seg(lo, hi, s))
        out.append(seg(m.start(), m.end(), fmt_at(m.start())))
        cursor = m.end()
    for a, b, s in spans:
        lo, hi = max(a, cursor), min(b, len(joined))
        if lo < hi:
            out.append(seg(lo, hi, s))
    return out


_ALIGN_NAMES = {0: "left", 1: "center", 2: "right", 3: "justify"}


def _para_align(para: Paragraph):
    """Paragraph alignment as a CSS-friendly name, or None (inherit/left)."""
    try:
        a = para.alignment
        return _ALIGN_NAMES.get(int(a)) if a is not None else None
    except (TypeError, ValueError):
        return None


def _para_is_list(p_elem) -> bool:
    """True when the paragraph carries real Word numbering (<w:numPr>) — the
    template's bullet rows. Style name alone ("List Paragraph") is NOT enough:
    Kyle uses it for indent-only headings like "Base Bid" too."""
    ppr = p_elem.find(qn("w:pPr"))
    return ppr is not None and ppr.find(qn("w:numPr")) is not None


def _para_price_list(p_elem) -> bool:
    """True when the paragraph is on the PRICE list (numId=3) that
    _flatten_price_bullets strips at generate time. The on-screen document
    editor uses this to render those rows flush/bullet-less so the preview
    matches the generated .docx (Kyle: no bullet points in the pricing)."""
    ppr = p_elem.find(qn("w:pPr"))
    if ppr is None:
        return False
    numpr = ppr.find(qn("w:numPr"))
    if numpr is None:
        return False
    numid = numpr.find(qn("w:numId"))
    return numid is not None and numid.get(qn("w:val")) == "3"


def _pos_of_anchor(anchor, page: dict, top_ps: list, body) -> tuple:
    """(x_pt, y_pt, w_pt, h_pt) of a floating drawing on its page.

    Word stores positionH/positionV relative to page/margin/column/paragraph;
    the paragraph-relative vertical (what these templates use) is resolved
    against the anchor's enclosing top-level paragraph index at the
    calibrated `_ANCHOR_LINE_H_PT` per empty line (see the constant's note).
    """
    ext = anchor.find(qn("wp:extent"))
    w = int(ext.get("cx")) / _EMU_PER_PT if ext is not None else 0.0
    h = int(ext.get("cy")) / _EMU_PER_PT if ext is not None else 0.0

    def offset(tag):
        p = anchor.find(qn("wp:" + tag))
        if p is None:
            return 0.0, "page"
        o = p.find(qn("wp:posOffset"))
        return (int(o.text) / _EMU_PER_PT if o is not None and o.text else 0.0,
                p.get("relativeFrom") or "page")

    ox, rfx = offset("positionH")
    oy, rfy = offset("positionV")

    x = ox + (page["margin"]["left"] if rfx in ("column", "margin") else 0.0)

    anc = anchor
    while anc is not None and anc.getparent() is not body:
        anc = anc.getparent()
    try:
        pidx = top_ps.index(anc)
    except ValueError:
        pidx = 0
    if rfy in ("paragraph", "line"):
        y = page["margin"]["top"] + pidx * _ANCHOR_LINE_H_PT + oy
    elif rfy == "margin":
        y = page["margin"]["top"] + oy
    else:                                     # "page" and anything unmapped
        y = oy
    return x, y, w, h


def template_geometry(d: Document) -> dict:
    """Page metrics + floating-object placement for the editor's page view:

      page   — {w_pt, h_pt, margin:{top,left,right,bottom}} from sectPr.
      boxes  — one {id, x_pt, y_pt, w_pt, h_pt} per REAL text box, in the
               SAME order `_iter_body_editable` numbers them (`txbx_idx`).
      images — the anchored artwork {name, x_pt, y_pt, w_pt, h_pt,
               para_index}; `name` is served by /api/proposal-template/media.
               For Kyle's templates these are the full-page letterhead PNGs
               (page 1's labeled/bordered art, then the plain terms-page
               letterhead — `para_index` orders them by where they anchor).
    """
    sec = d.sections[0]
    page = {
        "w_pt": sec.page_width.pt, "h_pt": sec.page_height.pt,
        "margin": {"top": sec.top_margin.pt, "left": sec.left_margin.pt,
                   "right": sec.right_margin.pt, "bottom": sec.bottom_margin.pt},
    }
    body = d.element.body
    top_ps = [c for c in body if c.tag == qn("w:p")]

    def enclosing_anchor(el):
        anc = el.getparent()
        want = (qn("wp:anchor"), qn("wp:inline"))
        while anc is not None and anc.tag not in want:
            anc = anc.getparent()
        return anc

    boxes = []
    for bi, txbx in enumerate(_iter_txbx(d)):
        anchor = enclosing_anchor(txbx)
        if anchor is not None:
            x, y, w, h = _pos_of_anchor(anchor, page, top_ps, body)
        else:
            x = y = w = h = None
        boxes.append({"id": bi, "x_pt": x, "y_pt": y, "w_pt": w, "h_pt": h})

    images = []
    for anchor in body.iter(qn("wp:anchor"), qn("wp:inline")):
        if _is_fallback_paragraph(anchor):
            continue
        blip = anchor.find(".//" + qn("a:blip"))
        if blip is None:
            continue
        rid = blip.get(qn("r:embed"))
        try:
            target = d.part.rels[rid].target_ref
        except (KeyError, AttributeError):
            continue
        x, y, w, h = _pos_of_anchor(anchor, page, top_ps, body)
        anc = anchor
        while anc is not None and anc.getparent() is not body:
            anc = anc.getparent()
        try:
            pidx = top_ps.index(anc)
        except ValueError:
            pidx = 0
        images.append({"name": target.rsplit("/", 1)[-1],
                       "x_pt": x, "y_pt": y, "w_pt": w, "h_pt": h,
                       "para_index": pidx})
    return {"page": page, "boxes": boxes, "images": images}


def _set_paragraph_text(p_elem, text: str) -> None:
    """Replace a paragraph's visible text with `text` IN PLACE, preserving the
    paragraph's formatting by keeping its FIRST text run (and that run's
    `<w:rPr>` — font/bold/size/color) and writing the new text into it; every
    other text run is dropped. Embedded newlines render as `<w:br/>` (via
    `_write_t_text`, the same helper the block engine uses for multi-line
    item notes).

    Runs that carry a drawing/picture/object are NEVER removed — Kyle's
    templates anchor the page letterhead artwork AND every floating text box
    in runs of otherwise-blank body paragraphs, so dropping those runs on an
    override would silently delete the letterhead (or an entire text box)
    from the customer document.

    A paragraph with no text runs (a blank spacer line, or one holding only
    a drawing) gets a fresh run appended so non-empty override text still
    renders. An override that blanks a paragraph (`text == ""`) is honored —
    the paragraph keeps its (now textless) run so its formatting/paragraph-
    mark survives.
    """
    # Descendant (not direct-child) search: Word wraps floating drawings in
    # mc:AlternateContent inside the run, so w:drawing is a grandchild.
    _MEDIA_TAGS = (qn("w:drawing"), qn("w:pict"), qn("w:object"))
    runs = p_elem.findall(qn("w:r"))
    text_runs = [r for r in runs
                 if not any(next(r.iter(tag), None) is not None for tag in _MEDIA_TAGS)]
    if not text_runs:
        r = OxmlElement("w:r")
        # Match the paragraph's look: clone rPr off an existing (media) run.
        if runs:
            rpr = runs[0].find(qn("w:rPr"))
            if rpr is not None:
                r.append(copy.deepcopy(rpr))
        p_elem.append(r)
        text_runs = [r]
    first = text_runs[0]
    for extra in text_runs[1:]:
        p_elem.remove(extra)
    # A run can hold several <w:t>/<w:br>/<w:tab> children (e.g. a value we
    # previously wrote with embedded line breaks) — collapse to a single
    # fresh <w:t> so re-overriding a multi-line paragraph doesn't leave stale
    # break/text nodes behind.
    for child in list(first):
        if child.tag in (qn("w:t"), qn("w:br"), qn("w:tab")):
            first.remove(child)
    t = OxmlElement("w:t")
    first.append(t)
    _write_t_text(t, text)


def _apply_paragraph_overrides(d: Document, overrides: list) -> int:
    """Apply the web editor's `paragraph_overrides` to the PRISTINE template —
    i.e. this MUST run before Phase 1 (block expansion) in `fill_proposal`,
    because block expansion inserts/removes paragraphs and would shift every
    id after the touched block, desyncing them from what the editor showed.

    Each override's `text` is whatever the estimator left in that block on
    the page — already-resolved values, not `{{tokens}}` — EXCEPT any
    `{{token}}` they deliberately left in place, which still gets filled by
    the normal flat substitution pass that runs after this (Phase 2), since
    that pass re-scans every paragraph regardless of whether it was just
    overridden.

    Defensive by design — never raises on bad input, so a malformed payload
    can't 500 `/api/generate`:
      - non-dict entries, non-int ids, or non-str text are skipped;
      - an id that doesn't exist in this document is skipped (no-op);
      - an id whose paragraph is inside a repeatable block (`in_block` is not
        None) is skipped — that content is pricing-engine/template owned and
        is never user-overridable, regardless of what the client sends.

    Returns the number of overrides actually applied.
    """
    by_id: dict[int, str] = {}
    for o in overrides or []:
        if not isinstance(o, dict):
            continue
        pid = o.get("id")
        if isinstance(pid, bool) or not isinstance(pid, int):
            continue
        text = o.get("text")
        if not isinstance(text, str):
            continue
        by_id[pid] = text   # last one wins on a duplicate id

    if not by_id:
        return 0

    applied = 0
    for idx, _kind, p_elem, in_block, _text, _txbx in iter_editable_blocks(d):
        if idx not in by_id or in_block is not None:
            continue
        _set_paragraph_text(p_elem, by_id[idx])
        applied += 1
    return applied


def fill_proposal(
    *,
    work_type: str,
    audience: str | None,
    values: Mapping[str, Any],
    systems: list[Mapping[str, Any]] | None = None,
    price_lines: list[Mapping[str, Any]] | None = None,
    alternates: list[Mapping[str, Any]] | None = None,
    remodel: list[Mapping[str, Any]] | None = None,
    rooms: list[Mapping[str, Any]] | None = None,
    single_bid: list[Mapping[str, Any]] | None = None,
    notes: list[Mapping[str, Any]] | None = None,
    tax_breakout: bool = False,
    has_options: bool = False,
    paragraph_overrides: list[Mapping[str, Any]] | None = None,
) -> bytes:
    """Open the matching template, substitute tokens, return docx bytes.

    `values` is a flat dict keyed by token name (e.g. `job_name`,
    `lump_sum`, `scope_notes`). Tokens not present in `values` are left
    as-is in the doc, so Troy can see which fields were missing.

    Repeatable blocks (Phase 1), each cloned once per list item before the
    flat pass:
      - `systems`     → `{{#system}}…{{/system}}`     (only when supplied)
      - `price_lines` → `{{#price_line}}…{{/price_line}}` (option/unit-price lines)
      - `alternates`  → `{{#alternate}}…{{/alternate}}`   (0/1 recommended system)
    `price_line`/`alternate` always run so their markers are stripped (zero
    rows) when empty — never left as literal text. A template with no marker,
    and the default args, is 100% backward-compatible with v1 fills.

    `paragraph_overrides` — free-text edits from the Proposal Review document
    editor (Phase 0, runs BEFORE block expansion — see `_apply_paragraph_overrides`
    for why ids must be resolved against the pristine template).
    """
    template_path = pick_template(work_type, audience)
    log.info("Filling proposal: work_type=%s audience=%s template=%s systems=%d price_lines=%d alt=%d",
             work_type, audience, template_path.name,
             len(systems) if systems else 0,
             len(price_lines) if price_lines else 0,
             len(alternates) if alternates else 0)

    if not template_path.exists():
        raise FileNotFoundError(f"Proposal template not found: {template_path}")

    d = docx.Document(str(template_path))

    # Phase 0 — apply the document editor's paragraph overrides FIRST, against
    # the pristine (just-opened, unexpanded) template — the same document
    # `iter_editable_blocks` walked to hand the editor its ids. Doing this
    # before Phase 1 is load-bearing: block expansion inserts/removes
    # paragraphs, which would shift ids computed afterward out from under the
    # editor's.
    if paragraph_overrides:
        n_over = _apply_paragraph_overrides(d, paragraph_overrides)
        if n_over:
            log.info("Applied %d paragraph override(s)", n_over)

    # Phase 1 — expand repeatable blocks. All three always run so their markers
    # are stripped (zero rows when empty) rather than left as literal {{#…}} text
    # in the output. A template with no marker for a block is unaffected (no-op),
    # so this stays byte-identical for templates that don't use a given block.
    block_lists: dict[str, list] = {
        "price_line": list(price_lines or []),
        "alternate": list(alternates or []),
        "system": list(systems or []),
        # {{#remodel}} line — present (1 row) only when a remodel tax applies,
        # stripped otherwise so the proposal hides "Kansas Remodel Tax" entirely.
        "remodel": list(remodel or []),
        # {{#tax_breakout}} — the itemized Material Sales Tax + Total lines. Shown
        # (1 row) only when the estimator chooses "sales tax broken out"; stripped
        # by DEFAULT so the price collapses to a single all-in line
        # ("$Total – … (material sales tax INCLUDED)") per Kyle's preferred layout.
        "tax_breakout": [{}] if tax_breakout else [],
        # {{#has_options}} — the "Options:" label. Shown only when there are
        # actual options (price lines or a recommended alternate); stripped
        # otherwise so an empty "Options:" never prints.
        "has_options": [{}] if has_options else [],
        # {{#room}} — per-room priced options (per-room jobs); stripped when empty.
        "room": list(rooms or []),
        # {{#single_bid}} — the single Base-Bid/Total layout. Shown by DEFAULT
        # (single_bid is None → one row) so existing callers are unaffected;
        # callers pass single_bid=[] to SUPPRESS it when room options replace it.
        "single_bid": [{}] if single_bid is None else list(single_bid),
        # {{#notes}} — editable boilerplate notes (one bullet per item).
        "notes": list(notes or []),
    }
    # Phase 0.5 — rewrite PRICE/ALTERNATE row LABELS (static text trailing an amount
    # token) from the doc editor's display overrides. BEFORE block expansion so the
    # {{#remodel}} / {{#alternate}} item-token anchors still exist (expansion
    # consumes them). No-op unless a `_*_label_override` private key is set.
    _n_lbl = _apply_price_label_overrides(d, values)
    if _n_lbl:
        log.info("Applied %d PRICE/ALTERNATE label override(s)", _n_lbl)
    n_blocks = _expand_all_blocks(d, block_lists)
    if n_blocks:
        log.info("Expanded %d repeatable block(s)", n_blocks)

    # Base-bid line DISPLAY override (single_bid.desc): swap the static
    # description noun between {{base_bid_formatted}} and {{base_tax_phrase}}
    # BEFORE the flat pass fills those tokens. No-op unless the caller set
    # `_base_desc_override` (private key — the flat pass never emits it).
    _bdo = values.get("_base_desc_override")
    if _bdo and _apply_base_desc_override(d, str(_bdo)):
        log.info("Applied base-bid description override")

    # GC additional-phase amount (static Clarifications text, not a token) — only
    # rewritten when the estimator changed the phase cell (main.py sets
    # `_phase_price_override`). Absent → each GC template keeps its native default.
    _ppo = values.get("_phase_price_override")
    if _ppo and _apply_gc_phase_override(d, str(_ppo)):
        log.info("Applied GC additional-phase override (%s)", _ppo)

    # Phase 2 — flat {{token}} substitution against `values`. This runs
    # unchanged from v1 and also fills any non-system tokens left inside
    # the expanded block paragraphs.
    total_subs = 0
    for p in _iter_all_paragraphs(d):
        total_subs += _replace_in_paragraph(p, values)

    log.info("Substituted %d tokens", total_subs)
    # Cove-only WORK rows: drop the "~0 SF of epoxy flooring and " prefix now that
    # the sqft/lf_clause tokens are filled (matches the on-screen preview).
    if _drop_zero_sf_prefix(d):
        log.info("Dropped ~0 SF prefix on cove-only WORK row(s)")
    _n_work_format = _normalize_work_label_formatting(d)
    if _n_work_format:
        log.info("Normalized %d WORK label/value run(s)", _n_work_format)
    # PRICE section reads as clean flush-left lines — Kyle wants NO bullets in the
    # pricing (confirmed by Hanz 2026-07-16, reversing the earlier "keep the red
    # squares" read). _flatten_price_bullets strips the numId=3 list formatting off
    # every PRICE row (base bid, Material Sales Tax, Remodel, Total, {{#price_line}}
    # options, {{#room}}, {{#alternate}}) across all Direct/GC/Gyp templates; the
    # WORK (numId 4), NOTES (numId 1) and Terms (numId 5) lists keep their bullets.
    _n_flat = _flatten_price_bullets(d)
    if _n_flat:
        log.info("Flattened %d PRICE bullet row(s)", _n_flat)
    # Double spacing after the base-bid Total, before the Options section (Kyle).
    if _space_before_options(d, 2):
        log.info("Added double spacing before the PRICE Options heading")
    # Pad affected framed boxes' top inset (so the first NOTES bullet / "Base Bid"
    # clear their red borders) BEFORE the shrink, so the shrink estimate sees the
    # reduced usable height and can't push the WORK box into overflow.
    _padded = _pad_frame_boxes(d, notes, work_type)
    if _padded:
        log.info("Padded %d framed box(es) top inset (clears the frame border)", _padded)
    # Shrink-to-fit: long content (esp. gyp's verbose WORK scope) would otherwise
    # overflow its fixed box and overlap the next box / frame art.
    _shrunk = _shrink_overflowing_text_boxes(d)
    if _shrunk:
        log.info("Set %d text box(es) to shrink-on-overflow (normAutofit)", _shrunk)
    # Force the Terms & Conditions onto their own page (templates ship without a
    # forced break, so a short body — e.g. combo — spills T&C over the acceptance).
    if _force_terms_on_new_page(d):
        log.info("Forced a page break before the Terms & Conditions section")
    if total_subs == 0 and not systems:
        log.warning(
            "Template has no {{tokens}}: %s. Returning unmodified.",
            template_path.name,
        )

    buf = io.BytesIO()
    d.save(buf)
    buf.seek(0)
    return buf.read()
