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
  * `_normalize_work_label_formatting`. The proposal keeps a WORK label bold
    through its colon with a pass over `w:txbxContent` — which a boxless letter
    has none of — driven by heuristics on the TEXT that misread Will's Direct
    copy. `_split_label_overrides` below does the letter's half of that job off
    the template's run structure instead. Same goal, different mechanism, and
    the reasoning is written out there.

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
import re
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


def _log_safe(value: Any, limit: int = 40) -> str:
    """One log field, with no way to forge a second line out of it.

    Strips everything that is not a plain printable character and truncates, so a
    `work_type` arriving from a query string cannot inject a newline (a forged
    entry), a carriage return (an overwritten one) or a megabyte of padding.
    Returns `repr`-style quoting so an empty or whitespace value is still visible
    in the log rather than reading as a missing field."""
    text = "" if value is None else str(value)
    clean = "".join(ch for ch in text if ch.isprintable())
    if len(clean) > limit:
        clean = clean[:limit] + "..."
    return repr(clean)


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
    # SANITIZED, because this line is now reachable from a QUERY STRING.
    # `/api/cover-letter/placeholders?work_type=...` passes its parameters
    # straight down to here, so an unmapped value carrying newlines could forge
    # log entries -- and these logs are the record of what actually went out on a
    # customer's page 1, which is the one thing they are for. `%r` does escape
    # newlines, so the practical risk was small, but a sanitizer at the log site
    # covers every caller (including `_generate`, whose values are also
    # user-influenced) rather than trusting each one to pick the right verb.
    log.warning("No cover-letter template for (%s, %s); falling back to %s",
                _log_safe(work_type), _log_safe(audience), _FALLBACK_KEY)
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
# `bid_date_formatted` leads (after an explicit short override) because it is what the
# PROPOSAL's own header prints (`{{bid_date_formatted}}`, in all 8 real templates), and the
# letterhead date box must match it. `proposal_date` is NOT a stand-in for the bid date here:
# the Proposal Review screen stamps it fresh with `new Date().toLocaleDateString(...)` on every
# generate (`proposal-review.js`), so it is "today", not the bid date, and trails as a last
# resort — a bid entered 2026-08-20 and finalized 2026-08-27 must letterhead itself 8/20/26,
# not the day someone happened to click Generate.
_SHORT_DATE_SOURCES = ("proposal_date_short", "bid_date_formatted", "bid_date",
                       "site_visit_date", "proposal_date")

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

    # ── The signature's contact line ─────────────────────────────────────────
    # `{{estimator_contact_line}}` replaced the literal "[ESTIMATOR EMAIL]" that
    # every one of these templates used to print at the customer (2026-09-09).
    # THE WHOLE LINE IS ONE TOKEN so the separator can be dropped with the value:
    # a template that said "{{estimator_email}} | wetreadwell.com" would show a
    # customer " | wetreadwell.com" whenever the address was unresolvable, and a
    # dangling pipe in a signature reads as a broken document.
    #
    # Resolved here as well as in main.py's backfill for the usual reason: a
    # SERVER-SIDE REPLAY of a payload frozen before this token existed has no
    # `estimator_email` at all, and the site alone is a true, complete line.
    if _blank(out.get("estimator_contact_line")):
        email = str(out.get("estimator_email") or "").strip()
        out["estimator_contact_line"] = (f"{email} | wetreadwell.com"
                                         if email else "wetreadwell.com")

    # And the name on the line above it. NOT derived -- inventing a signatory for
    # a customer's contract is worse than leaving the line short -- but forced to
    # EXIST, so the token is substituted with nothing rather than left standing.
    #
    # The hole is only reachable on the customer's copy, which is what makes it
    # worth closing here. main.py backfills `estimator_name` from the signed-in
    # user, and /api/admin/proposal-pdf is service-token gated and in
    # _AUTH_PUBLIC_PATHS -- so it has no bearer, `verify_token_claims` raises,
    # `_user_email` returns None, and both halves of that backfill no-op. A
    # payload frozen before {{estimator_name}} existed would then print the
    # literal token on page 1 of the document the CUSTOMER opens while the
    # estimator's own authenticated download looked perfect.
    if _blank(out.get("estimator_name")):
        log.warning("Cover letter has no estimator name for %r; the signature "
                    "line will print without one",
                    out.get("project_name") or out.get("job_name") or "(unnamed)")
        out["estimator_name"] = ""

    # ── Will Buchanan's Direct wording, 2026-09-03 ───────────────────────────
    # THE OTHER HALF OF A DUAL RESOLUTION. `computeTokenValues` in
    # proposal-review.js resolves these same three for the editor's on-screen
    # preview; this side serves generate AND the portal's server-side replay of
    # a pinned revision. A token filled on only one side previews as a raw
    # {{token}} over a correct PDF -- the bug PR #431 fixed for
    # {{proposal_date_short}}. Same rules on both sides, deliberately.
    #
    # A replay is why these are backfilled rather than assumed: a payload pinned
    # before these fields existed carries none of them, and the customer can ask
    # for that PDF at any time.
    if _blank(out.get("greeting")):
        # The letter opens on the contact's first name and nothing else:
        # "Brandon,". A blank contact box would leave a bare comma at the top of
        # a customer document, so fall back to a real greeting.
        first = re.split(r"[\s,]+", str(out.get("contact_name") or "").strip())[0]
        # Measure the name with an initial's own punctuation removed: "B." is one letter and must
        # not greet a customer as "B.,", while "J.R." is two and is what that person is called.
        # Stripping rather than counting A-Za-z keeps accented names working.
        if len(re.sub(r"[.'-]", "", first)) < 2 or "@" in first:
            out["greeting"] = "Hello,"          # an email or a lone initial is not a name
        else:
            # "brandon" -> "Brandon"; "McDonald" kept exactly as typed.
            shown = first[0].upper() + first[1:] if first == first.lower() else first
            out["greeting"] = shown + ","

    # Area -- the estimator's words for what the floor covers. `area_description`
    # is the frontend's SF line ("~4,200 sf of epoxy flooring"), which is a worse
    # answer than the estimator's own and a much better one than an empty "Area:".
    if _blank(out.get("work_areas")):
        out["work_areas"] = str(out.get("area_description") or "")

    # Materials / System: '1/4" MACRO Flake Single Broadcast with 6" Integral
    # Cove Base'.
    if _blank(out.get("cover_system_line")):
        name = str(out.get("system_name") or "").strip()
        thick = str(out.get("system_thickness") or "").strip()
        # Three of Kyle's fifteen system names already state a thickness
        # ('3/16" Urethne Cement With Color Fast (SLB)'). Prepending there prints
        # two, and where the estimator's pick disagrees with the name, two
        # CONTRADICTORY ones. An inch fraction already in the name wins: it is
        # Kyle's spec, not ours.
        line = name
        if thick and not re.search(r'\d\s*/\s*\d+\s*"', name):
            line = (thick + " " + name) if name else thick
        # No cove, no cove clause. The proposal body has always printed "with 0 LF
        # of integral cove base" on a no-cove job; the letter does not inherit it.
        try:
            cove_lf = float(re.sub(r"[^0-9.]", "", str(out.get("cove_lf") or "0")) or 0)
        except ValueError:
            cove_lf = 0.0
        if cove_lf > 0:
            height = str(out.get("cove_height") or "6").strip() or "6"
            line = (line + " with " if line else "") + height + '" Integral Cove Base'
        out["cover_system_line"] = line

    return out


# ─── The label bullets keep their own weight through an edit ──────────
# Every numbered bullet in these letters is written as a BOLD label run ending in
# a colon followed by NON-bold detail — `Materials / System: `, `Area: `,
# `Schedule: `, `Options: `, `System: ` (Hanz, 2026-09-04: "Only those words
# before and including the colon should be default bold. The other details should
# not be."). `prepare_cover_letter_templates._add` writes that split explicitly
# (`r.bold = bool(seg.get("bold"))`, so the detail carries `w:b val="0"`, not an
# inherit), and an unedited letter renders exactly right.
#
# An EDITED one did not. A plain-text override arrives as one string and
# `proposal_writer._set_paragraph_text` keeps the paragraph's FIRST text run and
# drops the rest — and here the first run is the bold label, so the estimator's
# whole line came out bold in the customer's PDF (measured on Direct/Epoxy: the
# rendered span was `Cambria-Bold` across `Schedule: edited by the estimator`).
#
# The PROPOSAL never had this bug: `_normalize_work_label_formatting` re-bolds a
# label through its first colon and normalises the tail after every fill. It
# cannot be reused here — it only walks `w:txbxContent`, and a cover letter has
# been pure flow with no text boxes since PR #453 — and its heuristics do not
# transfer either. It decides what a label is from the TEXT, and Will's Direct
# copy opens "A few things to note:", which is a sentence, is short, carries no
# `.?!`, and would therefore have been bolded whole.
#
# So the rule here reads the TEMPLATE'S OWN RUN STRUCTURE instead of the words: a
# paragraph is a label bullet only if the file already writes it as one. That is
# what keeps "A few things to note:" (a single run) and the Combo group headings
# (bold with no non-bold tail) out of it, without a list of phrases to maintain.
# ── Unresolved editor instructions ───────────────────────────────────────────
# The copy in these templates is a DRAFT (templates/CoverLetter/README.md: "The
# copy is a draft. It needs Hanz's review"), and several paragraphs carry
# bracketed instructions to the estimator rather than finished sentences —
# "[OPTIONS - keep the lines that apply: ...]", "[SHEEN - pick one: ...]". They
# are square brackets and not `{{braces}}` on purpose: a token would be
# substituted or silently dropped, whereas this prints as itself and reads as an
# instruction (see prepare_cover_letter_templates._ph).
#
# WHY THIS FUNCTION EXISTS AT ALL. Those words used to reach nobody: the letter
# was a separate document the customer portal never rendered. Since the letter
# became page 1 of the proposal .docx (2026-09-09) they are customer-facing, and
# the editor that was the documented way to remove them is gone. So generate
# REPORTS them — the Done page shows the estimator exactly what is still
# unresolved on the page they are about to send. It does not refuse and it does
# not rewrite: nobody has approved replacement wording, and inventing it is what
# templates/CoverLetter/README.md tells us not to do.
#
# The pattern requires an UPPERCASE first letter inside the brackets, which is
# what every placeholder in the set has and what ordinary prose in brackets
# (an aside, a "[sic]") would not.
_PLACEHOLDER_RE = re.compile(r"\[[A-Z][^\]]{2,}\]")


def template_placeholders(work_type: str | None,
                          audience: str | None = None) -> list:
    """Every "[INSTRUCTION ...]" the TEMPLATE for this variant still carries, in
    template order, de-duplicated.

    THE TEMPLATE, NOT THE FILLED LETTER, and that is the whole design of this
    function. A filled letter also contains the estimator's own free text --
    `work_areas`, `schedule_notes`, `job_name`, `system_name`, `estimator_name`
    -- and construction estimators write bracketed uppercase shorthand as a
    matter of course: "[TBD] pending GC schedule", "Amazon DFW7 [PHASE 2]",
    "Bays 1-4 [SEE PLAN A1.1]", "[NIC]", "[ALT 1]". Scanning the filled document
    reported all of those as unfinished template copy and told the estimator to
    untick a page they wanted -- crying wolf about their own correct job name.
    A latent trap, too: while every template still ships real instructions the
    banner is up anyway, so the false positives would only become the SOLE
    trigger once the copy pass lands and somebody is relying on it.

    Reading the template instead is strictly better in both directions: no
    estimator text can reach it, and a placeholder added by a future
    `prepare_cover_letter_templates.py` run is still found without anyone
    maintaining a list of known prefixes here.

    The cost, stated: a placeholder whose brackets are only assembled AFTER
    substitution -- a token whose value is itself bracketed uppercase, sitting
    where the template has no brackets -- is invisible to this. No token in these
    seven files is positioned to do that, and the alternative reports the
    estimator's own words back at them as an error."""
    path = pick_template(work_type, audience)
    try:
        d = docx.Document(str(path))
    except Exception as exc:  # noqa: BLE001 — a warning must never fail a generate
        log.warning("Could not scan %s for placeholders: %s: %s",
                    path.name, type(exc).__name__, exc)
        return []
    seen, out = set(), []
    for para in proposal_writer._iter_all_paragraphs(d):
        for hit in _PLACEHOLDER_RE.findall(para.text or ""):
            text = " ".join(hit.split())
            if text not in seen:
                seen.add(text)
                out.append(text)
    return out


def _label_paragraphs(d) -> dict:
    """`{block id: label text}` for every paragraph THE TEMPLATE writes as a bold
    label run ending in a colon plus a non-bold remainder.

    Read off the pristine template, so the answer describes Kyle's file rather
    than the estimator's edit. Ids are positions in
    `proposal_writer.iter_editable_blocks` — the same walk the overrides resolve
    against, so an id from here means the same paragraph there.
    """
    out: dict[int, str] = {}
    for idx, _kind, p_elem, in_block, _text, _txbx in \
            proposal_writer.iter_editable_blocks(d):
        if in_block is not None:
            continue
        segs = proposal_writer._block_runs(p_elem, Paragraph(p_elem, d))
        if len(segs) < 2:
            continue                      # one uniform run is not a label row
        head = segs[0]
        if not head.get("bold"):
            continue                      # the label must already be bold
        if not str(head.get("text") or "").rstrip().endswith(":"):
            continue                      # ...and must BE a label, colon and all
        if any(s.get("bold") for s in segs[1:]):
            continue                      # a fully bold heading has no detail half
        out[idx] = str(head["text"])
    return out


def _split_label_overrides(overrides: list, labels: Mapping[int, str]) -> list:
    """`overrides` with every PLAIN-TEXT edit of a label bullet re-expressed as
    two runs: bold through the first colon, explicitly not bold after it.

    Only plain text is rewritten. An override that already carries `runs` is the
    estimator having pressed Bold/Italic/Underline themselves, and their stated
    weight outranks this — the same rule `proposal_writer._user_bolded_runs`
    enforces for the proposal's WORK rows.

    Total, so the edge cases are not left to `_set_paragraph_text`'s "keep run
    zero" default:
      * `"Schedule: two phases"` → bold `"Schedule:"` + normal `" two phases"`;
      * `"Schedule:"`            → all label, so all bold;
      * text with no colon       → no label words at all, so nothing is bold;
      * `""`                     → left alone, so the blank-override path
                                   (numbered-clause refusal, `_strip_bullet`)
                                   still sees the shape it expects.
    The split is at the FIRST colon, matching `_normalize_work_label_formatting`.

    THE NO-COLON CASE DIVERGES FROM THE PROPOSAL, deliberately. There, the
    normalizer stands down and the row keeps its template weight — so a
    colon-less `Base System` row stays bold
    (`test_a_line_with_no_colon_keeps_the_row_weight_the_page_shows`). That is
    right for the proposal because a WORK row's template run IS the label: the
    whole row is three or four words. A cover-letter label bullet is the other
    shape — a two-word label in front of a two-line sentence — so falling back
    to run zero's weight bolds a paragraph that is almost entirely detail, which
    is the thing Hanz reported. The fallback here is therefore the DETAIL half's
    weight, which is also his sentence read literally. It is a judgement call in
    a customer document, so it is asserted from both sides below rather than
    left to be rediscovered.
    """
    out = []
    for o in overrides:
        if not isinstance(o, dict):
            out.append(o)
            continue
        pid = o.get("id")
        text = o.get("text")
        runs = o.get("runs")
        already_formatted = isinstance(runs, list) and bool(runs)
        if (isinstance(pid, int) and not isinstance(pid, bool) and pid in labels
                and isinstance(text, str) and text.strip()
                and not already_formatted):
            colon = text.find(":")
            head, tail = (text[:colon + 1], text[colon + 1:]) if colon > 0 else ("", text)
            split = []
            if head:
                split.append({"text": head, "bold": True})
            if tail:
                split.append({"text": tail, "bold": False})
            if split:
                o = dict(o, runs=split)
        out.append(o)
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

    A plain-text override of a LABEL BULLET is split at its first colon on the way
    in, so an edited `Schedule:` line keeps its bold label and normal detail
    instead of going bold end to end — see `_split_label_overrides`.

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
        # Split before applying, and read the labels off `d` while it is still
        # pristine: `_label_paragraphs` describes the TEMPLATE'S run structure,
        # which the first applied override would overwrite.
        overrides = _split_label_overrides(list(paragraph_overrides),
                                           _label_paragraphs(d))
        n_over = proposal_writer._apply_paragraph_overrides(d, overrides)
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
    """`(template_path, blocks, geometry)` for `(work_type, audience)`.

    INTROSPECTION ONLY SINCE 2026-09-09. This described what
    `/api/coverletter-template` served the letter's own editor tab, and that
    endpoint and that tab are both gone — the letter is now generated from the
    template plus the proposal's own values and prepended onto the proposal
    .docx, with nothing rendering it on screen. What remains is a reader the
    tests use to assert the shipped templates' shape (block ids, the single
    anchored date box, the letterhead artwork), which is worth keeping precisely
    because nobody looks at these documents until a customer does.

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
