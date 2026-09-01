"""Cover Letter Word-doc writer.

The cover letter is an OPTIONAL one-page letter, on Treadwell's letterhead, that
the customer portal shows AHEAD of the proposal. It is not an email: there is no
subject line and no attachment, just a page the customer reads first (Hanz,
2026-08-28).

One template per work type under `templates/CoverLetter/`, built by
`prepare_cover_letter_templates.py` from Kyle's letterhead. Read that module's
docstring before changing a template — the copy is generated, so hand-edits to
the .docx files are lost on the next regeneration.

WHAT THIS SHARES WITH `proposal_writer`, AND WHAT IT DELIBERATELY DOES NOT.

Shared, by import rather than by copy: the template-agnostic walk
(`iter_editable_blocks`), the formatting/geometry readers the document editor
renders from (`template_geometry`, `_block_runs`, `para_props`, `_para_align`,
`_para_is_list`, `_para_price_list`), the `{{token}}` substitution
(`_replace_in_paragraph` over `_iter_all_paragraphs`), and the editor's free-text
edits (`_apply_paragraph_overrides`). A second copy of any of those would drift
from the one the proposal uses, and the two documents are edited in the same UI.

NOT shared, and not ported:

  * Repeatable `{{#block}}` expansion. A letter has no priced/repeatable region —
    no systems list, no price lines, no notes bullets. Every block in these
    templates comes back from `iter_editable_blocks` with `in_block=None`, so
    every paragraph is freely editable and nothing is engine-owned.
  * Box OVERRIDES (`box_overrides`, drag-to-move, resize, shrink-to-fit, frame
    padding), PRICE-bullet flattening, the forced Terms page break. Those all
    exist because Kyle's proposal templates lay a fixed FORM out as a dozen
    floating text boxes over full-page artwork, and the estimator rearranges it.

THE ONE FLOATING BOX: THE DATE.

There is exactly one text box in a cover letter, and it holds the date. Hanz's
own `Treadwell Cover Letter - Example1.docx` floats "8/26/26" in a small centred
box anchored over the letterhead artwork instead of typing it on a line, and the
generated templates copy that box verbatim (see
`prepare_cover_letter_templates._install_date_box`).

It needs no special case in the WALKS, and that is the point of sharing them
rather than reimplementing them: `_iter_all_paragraphs` (the token fill) and
`_iter_body_editable` / `_iter_txbx` (the block ids and `template_geometry`) both
descend into `w:txbxContent` already. So the token inside the box is substituted
by the same pass as everything else, the block surfaces from `template_blocks`
honestly marked `in_txbx: True` with a `txbx` index that indexes
`geometry["boxes"]`, and `geometry["boxes"]` has exactly one entry.

It does need a special case in the VALUE. The box is 63.0pt x 18.0pt because
Kyle drew it around `8/26/26`, and Word clips an anchored box at its edge instead
of growing it — clipped text never reaches the PDF at all. So the box prints
`{{proposal_date_short}}` (`M/D/YY`, see `_short_date`), not the long-form
`{{proposal_date}}` the proposal's own header prints.

What is still absent is the machinery for MOVING it. The estimator never
repositions or resizes the date, so there is no `box_overrides` channel on the
cover letter and no geometry is ever written back — the editor renders the box
where the template puts it, and that is the only place it can be.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import docx
from docx.text.paragraph import Paragraph

import proposal_writer


log = logging.getLogger("proposal_tool.cover_letter_writer")

TEMPLATES_ROOT = proposal_writer.TEMPLATES_ROOT


# ─── Template selection ───────────────────────────────────────────────
# (work_type, audience) → relative template path, keyed and foldered exactly like
# `proposal_writer.TEMPLATE_PICKER`: audience-first directories, `None` for the
# work type that ignores audience. The proposal's table is not a clean grid and
# neither is this one — mirroring its SHAPE is what lets one document editor,
# one picker call and one override channel serve both documents.
#
# Two deliberate differences from the proposal's table, both explained at length
# in `prepare_cover_letter_templates`: GC combo gets its own file (the proposal
# reuses GC resinous only because Kyle never made a GC combo document, and a
# LETTER that did the same would describe half the job), and there is no sealer
# or budget letter (no source copy exists, so those fall back — see below).
TEMPLATE_PICKER: dict[tuple[str, str | None], str] = {
    ("epoxy",  "Direct"): "CoverLetter/Direct/Epoxy.docx",
    ("epoxy",  "GC"):     "CoverLetter/GC/Epoxy.docx",
    ("polish", "Direct"): "CoverLetter/Direct/Polish.docx",
    ("polish", "GC"):     "CoverLetter/GC/Polish.docx",
    ("combo",  "Direct"): "CoverLetter/Direct/Combo.docx",
    ("combo",  "GC"):     "CoverLetter/GC/Combo.docx",
    ("gyp",    None):     "CoverLetter/Gyp/Gyp.docx",
}

_FALLBACK_KEY = ("epoxy", "Direct")


def _norm(work_type: str | None, audience: str | None) -> tuple[str, str | None]:
    return (str(work_type or "").strip().lower(),
            (str(audience).strip() or None) if audience is not None else None)


def resolve(work_type: str | None, audience: str | None) -> tuple[str, str | None]:
    """The `(work_type, audience)` key `pick_template` will actually use.

    Same three-step ladder as `proposal_writer.pick_template`: the exact pair,
    then the audience-agnostic `(work_type, None)` entry (that is how gyp is
    reached from either audience), then `(epoxy, Direct)` — so an unmapped
    combination still produces a letter instead of hard-failing a generate.

    Exposed separately from `pick_template` because the ANSWER, not the path, is
    what identifies the template variant: `variant_key` stamps it into the
    version string that guards the paragraph-override ids."""
    key = _norm(work_type, audience)
    if key in TEMPLATE_PICKER:
        return key
    if (key[0], None) in TEMPLATE_PICKER:
        return (key[0], None)
    log.warning("No cover-letter template for (%r, %r); falling back to %s",
                work_type, audience, _FALLBACK_KEY)
    return _FALLBACK_KEY


def pick_template(work_type: str | None, audience: str | None = None) -> Path:
    """Resolve `(work_type, audience)` → absolute cover-letter template path."""
    return TEMPLATES_ROOT / TEMPLATE_PICKER[resolve(work_type, audience)]


def has_template(work_type: str | None, audience: str | None = None) -> bool:
    """True when this combination has its OWN cover-letter template on disk (no
    fallback). Callers that must not silently send an epoxy letter for a gyp job
    check this first."""
    key = _norm(work_type, audience)
    if key not in TEMPLATE_PICKER:
        key = (key[0], None)
        if key not in TEMPLATE_PICKER:
            return False
    return (TEMPLATES_ROOT / TEMPLATE_PICKER[key]).is_file()


def variant_key(work_type: str | None, audience: str | None = None) -> str:
    """`"<work_type>:<audience>"` for the template this combination RESOLVES to.

    This is the server-side half of the frontend's per-template override store
    (`proposal-review.js`'s `overrideKey(wt, audience)`), and it exists because
    the mtime alone cannot do the job here. A cover-letter override id is a
    position in a walk over ONE file, and these seven files are written by one
    generator in one run — so two variants can carry the same mtime to the
    nanosecond, and a version string built from mtime alone would happily replay
    a Direct/Combo edit onto GC/Epoxy and rewrite whichever sentence happened to
    sit at that index.

    Built from the RESOLVED key, not the requested one, so the epoxy fallback and
    the audience-agnostic gyp entry both stamp the file they actually opened."""
    wt, aud = resolve(work_type, audience)
    return wt + ":" + (aud or "")


# ─── Values ───────────────────────────────────────────────────────────
def _blank(v: Any) -> bool:
    return not str(v if v is not None else "").strip()


# The letterhead date box is 63pt x 18pt — Kyle drew it around HIS date format,
# which `Treadwell Cover Letter - Example1.docx` shows as `8/26/26`. Word CLIPS an
# anchored text box at its edge rather than growing it, and clipped text never
# reaches the PDF at all, so "August 27, 2026" printed as the single word
# "August" on every letter. The box is his design and stays; the date matches it.
#
# `proposal_date` leads (after an explicit short override) because the short date
# must be the SAME DAY as the long one — this letter would otherwise letterhead
# itself with the bid date while its own body, and the proposal behind it, print
# another. `_ensure_cover_letter_values` has already backfilled `proposal_date`
# from the bid date by the time this ladder runs, so in the common case the whole
# list collapses to "whatever date the letter is dated".
_SHORT_DATE_SOURCES = ("proposal_date_short", "proposal_date", "bid_date_formatted",
                       "bid_date", "site_visit_date")

# `%y` before `%Y` so "8/26/26" is read as 2026 rather than the year 26; a
# four-digit "8/26/2026" fails `%y` and falls through to `%Y` on the next pass.
_SHORT_DATE_FORMATS = ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%m/%d/%y", "%m/%d/%Y")


def _short_date(raw: Any) -> str | None:
    """`M/D/YY` for the letterhead box, or None if `raw` is not a date we know.

    Parsed, never clocked: `datetime.strptime` reads the value it is given and
    this box runs ~13 hours ahead of Central, so a `now()` here would date a
    letter sent Tuesday evening as Wednesday.
    """
    text = str(raw or "").strip()
    if not text:
        return None
    for fmt in _SHORT_DATE_FORMATS:
        try:
            got = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return "%d/%d/%02d" % (got.month, got.day, got.year % 100)
    return None


def _ensure_cover_letter_values(values: Mapping[str, Any]) -> dict:
    """A COPY of `values` with the letter-only tokens backfilled.

    A copy, not an in-place edit: the same dict is handed to
    `proposal_writer.fill_proposal` in the same request, and a writer that
    quietly grows keys on its caller's data is how the proposal starts printing
    something the estimator never typed.

    Two tokens need it, and they are the same date in two shapes:

    `{{proposal_date}}` — long form, for anywhere the letter sets the date on a
    text line. The Proposal Review screen stamps it when the estimator generates,
    but a SERVER-SIDE REPLAY (the portal's on-demand PDF from a pinned revision)
    runs a payload that may predate the field, and a raw "{{proposal_date}}" at
    the top of a customer-facing letter is exactly the class of leak
    `_ensure_value_aliases` exists to prevent.

    `{{proposal_date_short}}` — `M/D/YY`, and the ONLY thing the letterhead date
    box prints. See `_short_date`: the box is 63pt wide and Word clips rather
    than grows, so a long-form date reached the customer as the single word
    "August". Deliberately a second token rather than a narrowing of the first:
    the proposal's own header prints long form and must keep doing so, and the
    two documents are filled from one `values` dict in one request.

    Backfilled from the BID DATE, never from a clock. This box runs ~13 hours
    ahead of Central; `datetime.now()` here would date a letter sent on Tuesday
    evening as Wednesday. The bid date is also the more honest date for a
    proposal cover letter, and it is what the proposal's own header prints."""
    out = dict(values or {})
    if _blank(out.get("proposal_date")):
        for src in ("bid_date_formatted", "site_visit_date", "bid_date"):
            if not _blank(out.get(src)):
                out["proposal_date"] = out[src]
                break
        else:
            # Nothing to date it with. Empty beats a literal token on the page,
            # but it is a hole in a customer document, so say which draft it was.
            log.warning("Cover letter has no date: proposal_date, bid_date_formatted, "
                        "site_visit_date and bid_date are all blank for %r",
                        out.get("project_name") or out.get("job_name") or "(unnamed)")
            out["proposal_date"] = ""

    # Always DERIVED, even when the caller supplied `proposal_date_short`: a
    # caller that passes the long string through under the short name is the
    # exact failure this token exists to stop, and `_short_date` normalises it
    # instead of trusting the key's name.
    for src in _SHORT_DATE_SOURCES:
        short = _short_date(out.get(src))
        if short:
            out["proposal_date_short"] = short
            break
    else:
        # An empty box beats half a date, but the letterhead is then undated —
        # name the value that failed to parse so this is one log line, not an
        # SSH session and a container probe.
        first = next((out.get(s) for s in _SHORT_DATE_SOURCES if not _blank(out.get(s))), None)
        if first is None:
            log.warning("Cover letter letterhead has no date: %s are all blank for %r",
                        ", ".join(_SHORT_DATE_SOURCES),
                        out.get("project_name") or out.get("job_name") or "(unnamed)")
        else:
            log.warning("Cover letter letterhead date left blank: none of %s parsed as a "
                        "date (first non-blank was %r) for %r",
                        ", ".join(_SHORT_DATE_SOURCES), first,
                        out.get("project_name") or out.get("job_name") or "(unnamed)")
        out["proposal_date_short"] = ""
    return out


# ─── Fill ─────────────────────────────────────────────────────────────
def fill_cover_letter(
    *,
    work_type: str,
    audience: str | None = None,
    values: Mapping[str, Any],
    paragraph_overrides: list[Mapping[str, Any]] | None = None,
) -> bytes:
    """Open the matching cover-letter template, substitute `{{tokens}}`, return
    the filled .docx as bytes.

    `paragraph_overrides` are the document editor's free-text edits, resolved
    against the PRISTINE template exactly as they are for the proposal — their
    ids are positions in `iter_editable_blocks` over this file, so they are
    applied first, before anything else touches the paragraph list. (Nothing else
    here inserts or removes paragraphs, so there is no ordering hazard the way
    block expansion creates one in `fill_proposal`; applying them first keeps the
    two writers reading the same, and leaves room for that to stay true.)

    Raises `FileNotFoundError` naming the missing template — a caller that
    promised the customer a cover letter must fail loudly rather than send the
    proposal on its own and report success.
    """
    template_path = pick_template(work_type, audience)
    if not template_path.exists():
        raise FileNotFoundError(
            "Cover letter template not found: %s"
            % template_path.relative_to(TEMPLATES_ROOT).as_posix())

    log.info("Filling cover letter: work_type=%s audience=%s template=%s",
             work_type, audience, template_path.name)
    d = docx.Document(str(template_path))

    if paragraph_overrides:
        n_over = proposal_writer._apply_paragraph_overrides(d, list(paragraph_overrides))
        if n_over:
            log.info("Applied %d cover-letter paragraph override(s)", n_over)

    filled = _ensure_cover_letter_values(values)
    total_subs = 0
    for p in proposal_writer._iter_all_paragraphs(d):
        total_subs += proposal_writer._replace_in_paragraph(p, filled)
    log.info("Cover letter: substituted %d token(s)", total_subs)

    leftover = unfilled_tokens(d)
    if leftover:
        # Not fatal — the letter is still readable and the estimator can fix the
        # wording — but a raw {{token}} is customer-visible, so NAME the tokens.
        # "some tokens were left" costs an SSH session to turn into this list.
        log.warning("Cover letter (%s) still shows raw token(s): %s",
                    template_path.relative_to(TEMPLATES_ROOT).as_posix(),
                    ", ".join(sorted(leftover)))

    buf = io.BytesIO()
    d.save(buf)
    buf.seek(0)
    return buf.read()


def unfilled_tokens(d) -> set:
    """Every `{{token}}` still literally present in `d` after a fill. Used for
    the warning above and asserted by the tests, so a template that grows a token
    nothing supplies is caught here instead of on a customer's screen."""
    out = set()
    for p in proposal_writer._iter_all_paragraphs(d):
        for m in proposal_writer.TOKEN_RE.finditer(p.text):
            out.add(m.group(1))
    return out


# ─── Editor block model ───────────────────────────────────────────────
def template_blocks(d) -> list:
    """The template as the ordered, id-keyed block list the document editor
    renders — the SAME shape `/api/proposal-template` returns, built by the same
    helpers, so one editor can render either document.

    `id` is the paragraph's index in `proposal_writer.iter_editable_blocks`, the
    walk `fill_cover_letter` resolves `paragraph_overrides` against. An id from
    here therefore lands on that exact paragraph for as long as the template file
    is unchanged — which is what the `template_version` echoed alongside it (the
    file's mtime) lets the caller detect.
    """
    blocks = []
    for idx, kind, p_elem, in_block, text, txbx_idx in proposal_writer.iter_editable_blocks(d):
        p = Paragraph(p_elem, d)
        try:
            style_name = p.style.name if p.style is not None else None
        except Exception:  # noqa: BLE001 — a style lookup failure is cosmetic only
            style_name = None
        blocks.append({
            "id": idx,
            "kind": kind,
            "text": text,
            "style": {"name": style_name,
                      "bold": any(r.bold for r in p.runs if r.bold is not None)},
            # Always None here: the letter has no repeatable regions. Carried so
            # the editor's "is this row engine-owned" check reads the same field
            # on both documents rather than special-casing this one.
            "in_block": in_block,
            # Truthful, not hard-coded: exactly one block in a cover letter — the
            # floating DATE box — comes back with `in_txbx: True` and a `txbx`
            # index into `geometry["boxes"]`, and everything else is flow text.
            # The editor needs that distinction to know it cannot place the date
            # like a paragraph. `_iter_body_editable` visits body paragraphs
            # before boxes, so the date is the LAST id in the walk.
            "in_txbx": txbx_idx is not None,
            "txbx": txbx_idx,
            "align": proposal_writer._para_align(p),
            "list": proposal_writer._para_is_list(p_elem),
            "price_flat": proposal_writer._para_price_list(p_elem),
            "para": proposal_writer.para_props(d, p_elem),
            "runs": proposal_writer._block_runs(p_elem, p),
        })
    return blocks


def describe_template(work_type: str, audience: str | None = None) -> tuple:
    """`(template_path, blocks, geometry)` for `(work_type, audience)` —
    everything `/api/coverletter-template` serves except the cache version, which
    is the file's mtime and belongs to the endpoint that sets the ETag.

    `geometry` comes from the same `proposal_writer.template_geometry` the
    proposal editor uses: page size, margins, the anchored letterhead artwork
    (`word/media/image1.png`, the buffalo + footer bar) so the editor draws the
    real page, and `boxes` — which for a cover letter holds exactly ONE entry,
    the floating date box, paired with the single block whose `txbx` is 0.

    Raises `FileNotFoundError` naming the file — the endpoint turns that into a
    404 that says which template is missing, rather than an empty editor."""
    path = pick_template(work_type, audience)
    if not path.exists():
        raise FileNotFoundError(
            "Cover letter template not found: %s"
            % path.relative_to(TEMPLATES_ROOT).as_posix())
    d = docx.Document(str(path))
    return path, template_blocks(d), proposal_writer.template_geometry(d)
