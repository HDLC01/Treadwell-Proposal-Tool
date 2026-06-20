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
from docx.oxml import OxmlElement
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
# Name-capturing block markers — `{{#<name>}}` / `{{/<name>}}` — so any named
# list can drive a repeatable block (`system`, `price_line`, `alternate`, …).
BLOCK_START_RE = re.compile(r"\{\{\s*#\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
BLOCK_END_RE = re.compile(r"\{\{\s*/\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def _dotted_token_re(name: str) -> "re.Pattern":
    """`{{<name>.field}}` — dotted per-item token for a given block name."""
    return re.compile(r"\{\{\s*" + re.escape(name) + r"\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def _p_text(p_elem) -> str:
    """Joined text of a raw <w:p> element (across all its <w:t> runs)."""
    return "".join(t.text or "" for t in p_elem.iter(qn("w:t")))


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


def _substitute_item_tokens(p_elem, item: Mapping[str, Any], block_name: str) -> None:
    """Replace `{{<block>.field}}` / bare `{{field}}` in one cloned <w:p>.

    Mirrors `_replace_in_paragraph`'s run-collapsing strategy but works on a raw
    lxml element (cloned block paragraphs aren't attached to a python-docx
    parent). `{{<block>.field}}` always resolves against `item`; bare
    `{{field}}` resolves against `item` ONLY when the key exists there — any
    other `{{token}}` (e.g. {{state_name}}) is left for the flat pass.
    """
    full = _p_text(p_elem)
    if "{{" not in full:
        return

    dotted = _dotted_token_re(block_name)
    new_text = dotted.sub(lambda m: str(item.get(m.group(1), m.group(0))), full)

    # Bare `{{field}}` resolves against `item` ONLY when the key exists there —
    # otherwise it's left for the flat pass against `values`.
    def repl_bare(m: re.Match) -> str:
        key = m.group(1)
        return str(item[key]) if key in item else m.group(0)

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
            if "\n" in new_text:
                _set_t_multiline(t, new_text)
            else:
                t.text = new_text
                t.set(qn("xml:space"), "preserve")
            placed = True
        else:
            t.text = ""


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
        # {{#room}} — per-room priced options (per-room jobs); stripped when empty.
        "room": list(rooms or []),
        # {{#single_bid}} — the single Base-Bid/Total layout. Shown by DEFAULT
        # (single_bid is None → one row) so existing callers are unaffected;
        # callers pass single_bid=[] to SUPPRESS it when room options replace it.
        "single_bid": [{}] if single_bid is None else list(single_bid),
        # {{#notes}} — editable boilerplate notes (one bullet per item).
        "notes": list(notes or []),
    }
    n_blocks = _expand_all_blocks(d, block_lists)
    if n_blocks:
        log.info("Expanded %d repeatable block(s)", n_blocks)

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
