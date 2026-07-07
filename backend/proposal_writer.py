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


def _write_t_text(t, text: str) -> None:
    """Set a <w:t>'s text, preserving whitespace and rendering \\n as <w:br/>."""
    if "\n" in text:
        _set_t_multiline(t, text)
    else:
        t.text = text
        t.set(qn("xml:space"), "preserve")


def _sub_runs_preserving(p_elem, pattern, repl) -> int:
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
        if "{{" not in joined:
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
    tax_breakout: bool = False,
    has_options: bool = False,
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
