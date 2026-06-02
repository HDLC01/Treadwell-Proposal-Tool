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
import re
from pathlib import Path
from typing import Any, Mapping

import docx
from docx.document import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph


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
    """Replace `{{token}}` in a paragraph, preserving run-level formatting.

    Word splits text across multiple <w:r> runs whenever formatting
    changes mid-word, which breaks naive .text replacement. We rebuild
    the paragraph's full text, do the substitution on the joined string,
    and write the result back into the first run while zeroing the rest.
    Formatting on the first run is preserved; mid-token formatting
    differences are lost (acceptable — tokens shouldn't have mid-token
    bold/italic).
    """
    if "{{" not in p.text:
        return 0

    full_text = p.text
    new_text, n_subs = TOKEN_RE.subn(
        lambda m: str(values.get(m.group(1), m.group(0))),
        full_text,
    )
    if n_subs == 0:
        return 0

    # Collapse all runs into the first one with the substituted text.
    if p.runs:
        p.runs[0].text = new_text
        for run in p.runs[1:]:
            run.text = ""
    return n_subs


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
BLOCK_START_RE = re.compile(r"\{\{\s*#\s*system\s*\}\}")
BLOCK_END_RE = re.compile(r"\{\{\s*/\s*system\s*\}\}")
# `{{system.field}}` — dotted per-system token.
SYS_TOKEN_RE = re.compile(
    r"\{\{\s*system\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}"
)


def _p_text(p_elem) -> str:
    """Joined text of a raw <w:p> element (across all its <w:t> runs)."""
    return "".join(t.text or "" for t in p_elem.iter(qn("w:t")))


def _substitute_system_tokens(p_elem, system: Mapping[str, Any]) -> None:
    """Replace `{{system.field}}` / bare `{{field}}` in one <w:p> element.

    Mirrors `_replace_in_paragraph`'s run-collapsing strategy but works on
    a raw lxml element (the cloned block paragraphs aren't attached to a
    python-docx parent). Only system-scoped tokens are touched; foreign
    `{{tokens}}` are left for the later flat pass.
    """
    full = _p_text(p_elem)
    if "{{" not in full:
        return

    def repl(m: re.Match) -> str:
        # `{{system.field}}` always resolves against the system dict.
        return str(system.get(m.group(1), m.group(0)))

    new_text = SYS_TOKEN_RE.sub(repl, full)

    # Bare `{{field}}` resolves against the system dict ONLY when the key
    # exists there — otherwise it's left for the flat pass against `values`.
    def repl_bare(m: re.Match) -> str:
        key = m.group(1)
        return str(system[key]) if key in system else m.group(0)

    new_text = TOKEN_RE.sub(repl_bare, new_text)

    if new_text == full:
        return

    runs = [r for r in p_elem.iter(qn("w:r"))]
    # Write the whole new text into the first run's first <w:t>; clear rest.
    placed = False
    for r in runs:
        t = r.find(qn("w:t"))
        if t is None:
            continue
        if not placed:
            t.text = new_text
            t.set(qn("xml:space"), "preserve")
            placed = True
        else:
            t.text = ""


def _expand_system_blocks(container, systems: list[Mapping[str, Any]]) -> int:
    """Expand one `{{#system}}…{{/system}}` block within a parent element.

    `container` is any element whose direct <w:p> children may hold the
    markers (a <w:body>, <w:tc>, or <w:txbxContent>). Returns the number
    of blocks expanded (0 or 1 per container per call — we handle the
    first block found; templates ship with a single repeatable block).
    """
    children = list(container)
    start_idx = end_idx = None
    for i, child in enumerate(children):
        if child.tag != qn("w:p"):
            continue
        txt = _p_text(child)
        if start_idx is None and BLOCK_START_RE.search(txt):
            start_idx = i
        elif start_idx is not None and BLOCK_END_RE.search(txt):
            end_idx = i
            break

    if start_idx is None or end_idx is None:
        return 0

    # Template paragraphs strictly between the two markers.
    template_elems = children[start_idx + 1:end_idx]
    start_elem = children[start_idx]
    end_elem = children[end_idx]

    # Build the expansion: for each system, a fresh deep copy of every
    # template paragraph with per-system tokens substituted.
    new_elems = []
    for system in systems:
        for tmpl in template_elems:
            clone = copy.deepcopy(tmpl)
            _substitute_system_tokens(clone, system)
            new_elems.append(clone)

    # Insert all clones right before the start marker, then drop the
    # markers and the original (un-substituted) template paragraphs.
    for clone in new_elems:
        start_elem.addprevious(clone)
    for stale in [start_elem, end_elem, *template_elems]:
        container.remove(stale)
    return 1


def _expand_all_system_blocks(d: Document, systems: list[Mapping[str, Any]]) -> int:
    """Find every block-bearing container in the doc and expand it.

    Walks the body, every table cell (recursively), and every text box
    (<w:txbxContent>, including the VML-fallback duplicate) so a block
    annotated in any of those locations is expanded consistently.
    """
    blocks = 0
    body = d.element.body

    # Body itself.
    blocks += _expand_system_blocks(body, systems)

    # Table cells (recursive — body.iter walks nested tables too).
    for tc in body.iter(qn("w:tc")):
        blocks += _expand_system_blocks(tc, systems)

    # Text boxes — both the DrawingML <mc:Choice> copy and the VML
    # <mc:Fallback> copy each contain their own <w:txbxContent>, so this
    # keeps the two renderings of the same box in sync.
    for txbx in body.iter(qn("w:txbxContent")):
        blocks += _expand_system_blocks(txbx, systems)

    return blocks


def fill_proposal(
    *,
    work_type: str,
    audience: str | None,
    values: Mapping[str, Any],
    systems: list[Mapping[str, Any]] | None = None,
) -> bytes:
    """Open the matching template, substitute tokens, return docx bytes.

    `values` is a flat dict keyed by token name (e.g. `job_name`,
    `lump_sum`, `scope_notes`). Tokens not present in `values` are left
    as-is in the doc, so Troy can see which fields were missing.

    `systems` (optional) is a list of per-system dicts. When given AND the
    template contains a `{{#system}}…{{/system}}` block, that block is
    cloned once per system with `{{system.field}}` substitution BEFORE the
    flat pass. Passing `systems=None` (the default), or a template with no
    block marker, is 100% backward-compatible with v1 single-system fills.
    """
    template_path = pick_template(work_type, audience)
    log.info("Filling proposal: work_type=%s audience=%s template=%s systems=%d",
             work_type, audience, template_path.name,
             len(systems) if systems else 0)

    if not template_path.exists():
        raise FileNotFoundError(f"Proposal template not found: {template_path}")

    d = docx.Document(str(template_path))

    # Phase 1 — expand repeatable per-system blocks (no-op unless BOTH a
    # non-empty `systems` list is supplied AND the template has a marker).
    if systems:
        n_blocks = _expand_all_system_blocks(d, list(systems))
        if n_blocks:
            log.info("Expanded %d system block(s) for %d system(s)",
                     n_blocks, len(systems))
        else:
            log.info("systems supplied but template has no {{#system}} block; "
                     "falling back to flat single-system fill")

    # Phase 2 — flat {{token}} substitution against `values`. This runs
    # unchanged from v1 and also fills any non-system tokens left inside
    # the expanded block paragraphs.
    total_subs = 0
    for p in _iter_all_paragraphs(d):
        total_subs += _replace_in_paragraph(p, values)

    log.info("Substituted %d tokens", total_subs)
    if total_subs == 0 and not systems:
        log.warning(
            "Template has no {{tokens}}: %s. Returning unmodified.",
            template_path.name,
        )

    buf = io.BytesIO()
    d.save(buf)
    buf.seek(0)
    return buf.read()
