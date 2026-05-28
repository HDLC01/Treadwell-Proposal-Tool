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


def fill_proposal(
    *,
    work_type: str,
    audience: str | None,
    values: Mapping[str, Any],
) -> bytes:
    """Open the matching template, substitute tokens, return docx bytes.

    `values` is a flat dict keyed by token name (e.g. `job_name`,
    `lump_sum`, `scope_notes`). Tokens not present in `values` are left
    as-is in the doc, so Troy can see which fields were missing.
    """
    template_path = pick_template(work_type, audience)
    log.info("Filling proposal: work_type=%s audience=%s template=%s",
             work_type, audience, template_path.name)

    if not template_path.exists():
        raise FileNotFoundError(f"Proposal template not found: {template_path}")

    d = docx.Document(str(template_path))

    total_subs = 0
    for p in _iter_all_paragraphs(d):
        total_subs += _replace_in_paragraph(p, values)

    log.info("Substituted %d tokens", total_subs)
    if total_subs == 0:
        log.warning(
            "Template has no {{tokens}}: %s. Returning unmodified.",
            template_path.name,
        )

    buf = io.BytesIO()
    d.save(buf)
    buf.seek(0)
    return buf.read()
