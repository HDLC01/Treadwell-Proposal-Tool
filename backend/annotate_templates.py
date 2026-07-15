"""
Per-template annotator (v2) — converts Kyle's plain-text placeholders
into `{{tokens}}` python-docx can substitute.

Each template uses its OWN placeholder convention:
- Direct/Epoxy: "Name", "City, State", "Job Specification", "$xx", "xxx"
- Direct/Polish: "xxx", "xxx, KS", "$xx", "~1,600 sf", "Standard Sheen…"
- Combo / GC variants / Gyp: various mixes

Strategy:
1. Walk `word/document.xml` as raw text (covers all paragraph + table runs).
2. For ambiguous placeholders like "$xx" that appear multiple times for
   DIFFERENT meanings, we match the FULL paragraph text around the
   placeholder so we can disambiguate by the label nearby (e.g.
   "$xx – Polished Concrete Flooring" → {{lump_sum}}; "$xx – Total" →
   {{total}}; "$xx – Kansas Remodel Tax" → {{tax_amount}}).
3. Replacements are ordered: most specific (longest with context) first,
   generic (bare placeholder) last.
"""
from __future__ import annotations

import io
import re
import shutil
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TEMPLATES_DIR = Path(__file__).parent / "templates"


# ─── Per-template replacement rules ───────────────────────────────────
# Each rule: (search_text, token_or_replacement)
# Rules are applied IN ORDER. Put more specific patterns first.

EPOXY_DIRECT_RULES: list[tuple[str, str]] = [
    # Long-form placeholders (most specific first)
    ("Orange-Peel or Smooth or Light or Medium or Heavy or with added texture",
                                                              "{{texture}}"),
    ("Treadwell Epoxy Flooring System ",                      "{{system_name}}"),
    ("Treadwell Epoxy Flooring System",                       "{{system_name}}"),
    ("Job Specification ",                                    "{{work_description}}"),
    ("Job Specification",                                     "{{work_description}}"),
    ("City, State",                                           "{{city_state}}"),
    ("dumpster provided by owner",                            "{{disposal}}"),

    # Price + scope details. Order matters — longer/more-specific patterns
    # MUST come before shorter ones since once a $xxxx is replaced inside a
    # longer template phrase, that paragraph can't match a shorter pattern.
    ("~xxx SF",                                               "~{{epoxy_sf}} SF"),
    ("xxx LF",                                                "{{cove_lf}} LF"),
    ("xx/xx/26",                                              "{{site_visit_date}}"),
    ("1/1/26",                                                "{{bid_date_formatted}}"),
    ("Assumes all areas available at one time, approx. 1 week to complete full scope",
                                                              "{{schedule_notes}}"),
    ("$    xx – Kansas Remodel Tax",                          "{{tax_amount_formatted}} – {{state_name}} Remodel Tax"),
    ("$xxxx – ",                                              "{{lump_sum_formatted}} – "),
    ("$xx – Total",                                           "{{total_formatted}} – Total"),

    ("Name",                                                  "{{job_name}}"),
]

POLISH_DIRECT_RULES: list[tuple[str, str]] = [
    # Long-form text — most specific first
    ("Standard Sheen with Salt &amp; Pepper Aggregate Exposure", "{{system_name}}"),
    ("Standard Sheen with Salt & Pepper Aggregate Exposure",     "{{system_name}}"),
    ("~1,600 sf of polished concrete flooring",                  "{{area_description}}"),
    ("dumpster provided by owner",                               "{{disposal}}"),
    # Schedule line shipped as STATIC boilerplate (no token) — so estimator edits
    # to Schedule never reached the polish proposal. Tokenize it like Epoxy does.
    ("Assumes all areas available at one time, approx. 1 week to complete full scope",
                                                                 "{{schedule_notes}}"),
    # Job header — left sidebar
    ("xxx, KS",                                                  "{{city_state}}"),
    # Header date (hardcoded by Kyle as 1/1/26)
    ("01/1/26",                                                  "{{bid_date_formatted}}"),
    ("1/1/26",                                                   "{{bid_date_formatted}}"),
    # Money placeholders — match with context labels so the right value lands
    ("$xx – Polished Concrete Flooring as described above",      "{{lump_sum_label}}"),
    ("$xx – Polished Concrete Flooring as described above", "{{lump_sum_label}}"),
    ("$xx – Total",                                              "{{total_label}}"),
    ("$xx – Total",                                         "{{total_label}}"),
    # Bare "xxx" - the FIRST occurrence in the doc is the job name.
    # We handle "xxx" via a one-shot replacement later (see _replace_xxx_once)
]

COMBO_DIRECT_RULES: list[tuple[str, str]] = [
    ("Orange-Peel or Smooth or Light or Medium or Heavy or with added texture",
                                                              "{{texture}}"),
    ("Standard Sheen with Salt &amp; Pepper Aggregate Exposure", "{{system_name_polish}}"),
    ("Standard Sheen with Salt & Pepper Aggregate Exposure",     "{{system_name_polish}}"),
    ("Treadwell Epoxy Flooring System ",                      "{{system_name_epoxy}}"),
    ("Treadwell Epoxy Flooring System",                       "{{system_name_epoxy}}"),
    ("dumpster provided by owner",                            "{{disposal}}"),
    # Schedule line shipped as STATIC boilerplate (split across 7 runs, no token)
    # — estimator edits to Schedule never reached the combo proposal. Tokenize it.
    ("Assumes all areas available at one time, approx. 1 week to complete full scope",
                                                              "{{schedule_notes}}"),
    ("xxx, KS",                                               "{{city_state}}"),
    ("01/1/26",                                               "{{bid_date_formatted}}"),
    ("1/1/26",                                                "{{bid_date_formatted}}"),
]

BUDGET_DIRECT_RULES: list[tuple[str, str]] = [
    ("xxx, KS",                                               "{{city_state}}"),
    ("01/1/26",                                               "{{bid_date_formatted}}"),
    ("1/1/26",                                                "{{bid_date_formatted}}"),
]

# GC templates: tokenize the fields the tool actually fills — estimator, bid
# date, area SF, and the Base Bid / tax / Total price block. The GC-specific
# system menu, scope, exclusions, notes, and the GC/project addresses stay as
# boilerplate the estimator finishes in Word (that's the GC format). The "–" is
# an en dash; "&amp;" matches the escaped ampersand in the docx XML.
GC_POLISH_RULES: list[tuple[str, str]] = [
    ("Greg Ingebretson",                            "{{estimator_name}}"),
    ("5/1/26",                                      "{{bid_date_formatted}}"),
    ("~1,600 sf",                                   "~{{sqft}} sf"),
    ("$x – Polished Concrete &amp; Joint Filler as described above (material sales tax INCLUDED)",
     "{{base_bid_formatted}} – Polished Concrete &amp; Joint Filler as described above {{base_tax_phrase}}"),
    ("$  x – Material Sales Tax",                    "{{material_tax_formatted}} – Material Sales Tax"),
    ("$  x – Kansas Remodel Tax",                    "{{tax_amount_formatted}} – Remodel Tax"),
    ("$x – Total",                                   "{{total_formatted}} – Total"),
]

GC_RESINOUS_RULES: list[tuple[str, str]] = [
    ("Greg Ingebretson",                            "{{estimator_name}}"),
    ("5/1/26",                                      "{{bid_date_formatted}}"),
    ("~1,600 sf",                                   "~{{sqft}} sf"),
    ("&amp; 500 lf of integral base",               "&amp; {{cove_lf}} lf of integral base"),
    ("$x – Resinous floor &amp; integral cove base as described above (material sales tax INCLUDED)",
     "{{base_bid_formatted}} – Resinous floor &amp; integral cove base as described above {{base_tax_phrase}}"),
    ("$  x – Material Sales Tax",                    "{{material_tax_formatted}} – Material Sales Tax"),
    ("$  x – Kansas Remodel Tax",                    "{{tax_amount_formatted}} – Remodel Tax"),
    ("$x – Total",                                   "{{total_formatted}} – Total"),
    # ({{texture}} is already present in this template's System block.)
]

GC_SEALER_RULES: list[tuple[str, str]] = [
    ("Greg Ingebretson",                            "{{estimator_name}}"),
    ("5/1/26",                                      "{{bid_date_formatted}}"),
    ("~1,600 sf",                                   "~{{sqft}} sf"),
    ("$x – Sealed Concrete as described above (material sales tax INCLUDED)",
     "{{base_bid_formatted}} – Sealed Concrete as described above {{base_tax_phrase}}"),
    ("$  x – Material Sales Tax",                    "{{material_tax_formatted}} – Material Sales Tax"),
    ("$  x – Kansas Remodel Tax",                    "{{tax_amount_formatted}} – Remodel Tax"),
    ("$x – Total",                                   "{{total_formatted}} – Total"),
]

_GYP_REL = "Gyp/xx TREADWELL UNDERLAYMENT PROPOSAL - xx.docx"

# Gyp underlayment: static-boilerplate template with `xx` / `$x` placeholders,
# laid out in floating text boxes over letterhead art (choice + VML fallback, so
# every op hits 2 copies). Search strings are the XML-ESCAPED joined paragraph
# text (verified byte-exact against the 2026-07-03 docx: NBSP=\xa0, en dash=–,
# "&gt;"/"&amp;" escaped); replacements are plain (the engine xml_escapes them, so
# ">" -> "&gt;"). Gyp shows its 4 price rows natively (base + material tax +
# remodel + total), so those are FLAT tokens (always render); the backend fills
# broken-out values for gyp. Options integrate via {{#price_line}} (the tool's
# option tabs / add-deduct); the Clarifications box becomes {{#notes}}.
GYP_RULES: list[tuple[str, str]] = [
    ("Greg Ingebretson",                                          "{{estimator_name}}"),
    ("7/1/26",                                                    "{{bid_date_formatted}}"),
    ("xx, KS ",                                                   "{{city_state}}"),
    ("xx, MO ",                                                   ""),
    # Spec / drawings line value (keeps the bold "Gypsum Underlayment:" label — see LABEL_TOKENS)
    ("per Spec 035413 &amp; Drawings by xx Architects dated 6/1/26 (NO spec)",
                                                                  "{{work_description}}"),
    # System & Scope — the 3 "Based on xx sf of x/x\" ..." sentences. L1/L2/L3 differ
    # only by NBSP placement + the sound-mat clause; each full string is unique.
    ("Based on\xa0xx sf\xa0of x/x\"\xa0USG Levelrock 2500 Gypsum Floor Topping at 2,500 psi over &gt;3/4\" plywood ",
     "Based on {{gyp_soft_sf}} sf of {{gyp_soft_thickness}} USG Levelrock 2500 Gypsum Floor Topping at 2,500 psi over >3/4\" plywood "),
    ("Based on\xa0xx sf\xa0of\xa0x/x\"\xa0USG Levelrock 2500 Gypsum Floor Topping at 2,500 psi over 1/8\" – SAM-N12 ",
     "Based on {{gyp_hard_sf}} sf of {{gyp_hard_thickness}} USG Levelrock 2500 Gypsum Floor Topping at 2,500 psi over 1/8\" – SAM-N12 "),
    ("Based on\xa0xx sf\xa0of\xa0x/x\" USG Levelrock 2500 Gypsum Floor Topping at 2,500 psi over &gt;3/4\" plywood ",
     "Based on {{gyp_corridor_sf}} sf of {{gyp_corridor_thickness}} USG Levelrock 2500 Gypsum Floor Topping at 2,500 psi over >3/4\" plywood "),
    # PRICE — flat tokens (gyp always itemizes; backend forces broken-out values)
    ("$x – Gypsum Underlayment System as described above (material sales tax INCLUDED)",
     "{{base_bid_formatted}} – Gypsum Underlayment System as described above (material sales tax INCLUDED)"),
    ("$  x – Material Sales Tax",                            "{{material_tax_formatted}} – Material Sales Tax"),
    ("$  x – Kansas Remodel Tax",                           "{{tax_amount_formatted}} – Kansas Remodel Tax"),
    ("$x – Total",                                          "{{total_formatted}} – Total"),
    ("xx Mobilizations to Site (x per building = x total).",     "{{mobilizations_line}}"),
    # Options — the GrassWorx VE row becomes the {{#price_line}} row template
    ("($x) – Deduct VE for GrassWorx SC 190 Sound Mat, in lieu of USG’s sound mat described above.",
     "{{price_line.amount_formatted}} – {{price_line.label}}"),
    # NOTES box — first paragraph becomes the block start (can't insert-before a
    # box's first paragraph); second becomes the row template.
    ("Excludes Union Labor/Prevailing Wage Labor (unless otherwise noted), bond &amp; liquidated damages ",
     "{{#notes}}"),
    ("Excludes hoisting or lifting of equipment to elevated slabs if elevator is unavailable",
     "{{notes.text}}"),
]

# Bold-label paragraphs whose value spans following runs (kept label + tokenized value).
GYP_LABEL_TOKENS: list[tuple[str, str]] = [
    ("Exclusions:", "{{exclusions}}"),
]

# Marker paragraphs inserted relative to an anchor paragraph (post-replacement,
# stripped, XML-escaped text). Anchors are all mid-box (never a box's first para).
# Ordered: each pass re-scans the (updated) XML, so {{/has_options}} anchors on the
# already-inserted {{/price_line}} para → correct nesting
# {{#has_options}} / Options: / {{#price_line}} / row / {{/price_line}} / {{/has_options}}.
GYP_MARKER_INSERTS: list[tuple[str, str, str]] = [
    ("Options:",                                                   "{{#has_options}}", "before"),
    ("{{price_line.amount_formatted}} – {{price_line.label}}", "{{#price_line}}",  "before"),
    ("{{price_line.amount_formatted}} – {{price_line.label}}", "{{/price_line}}",  "after"),
    ("{{/price_line}}",                                            "{{/has_options}}", "after"),
    ("{{notes.text}}",                                             "{{/notes}}",       "after"),
]

# Static paragraphs removed (XML-escaped joined text, exact). The 7 leftover option/
# footnote rows in PRICE + the 13 remaining Clarifications rows (preserved verbatim
# as default_notes.json["gyp"]). None is a box-first paragraph.
GYP_DELETE_PARAS: list[str] = [
    "Note: ^ Limited Warranty applies.",
    "($x) – Deduct to reduce Gypsum to 3/4\" thickness and Sound Mat to 3/16” for SAM-N12 ULTRA*.",
    "*ULTRA mat will provide a better sound rating than the 1/4\" called for, while using less gyp. material.",
    "$x – Add for Offsite Storage (if onsite storage of 500 sf not provided by GC).",
    "$x – Add for Gypsum Sealer Material ONLY* (to be install by others).",
    "* Consult your floor coverings expert for compatibility &amp; application.",
    "* Treadwell not responsible for mis-use or improper storage of material.",
    "Excludes temporary/permanent lighting &amp; HVAC as required by the manufacturer for system installation.",
    "Excludes .03% Textura Fees",
    "A FRESH water supply of at least 40 GPM with a 2\" hook-up must be provided, by others [must be Legal + Permitted].",
    "Add $4,800 $8,600 for each additional mobilization, Add $5,600 $10,800 for each Pre-Pour mobilization.",
    "Add $500/crew hour for “show up time” if crew mobilizes at agreed upon start date &amp; time but the job site is not ready.",
    "Add $500/crew hour for “stand down time” if working, onsite crew is stopped for a reason outside of Treadwell’s control.",
    "Addenda Acknowledged: 0",
    "Treadwell typically requires 5 weeks of notice when scheduling new work",
    "Treadwell includes the following insurance coverage: GL: 1M/2M, WC: 1M, Auto: 1M, Umb: 5M. Additional Coverage can be",
    "provided at an additional cost.",
    "Treadwell reserves the right to terminate the contract for customers not meeting Treadwell's pre-qual. requirements.",
    "Up to 8% material escalation for 12 months from the date of this quote is included.  Any material escalation over 8% will be",
    "added.  Any material ordered 12 months after the date of this quote will be repriced &amp; added to our contract.",
    "Proposal valid for 60 days. The attached “Terms and Conditions” are part of this proposal/contract.",
]

# Map relative path → rule list
TEMPLATE_RULES: dict[str, list[tuple[str, str]]] = {
    "Direct/XX.XX TREADWELL EPOXY PROPOSAL - New Direct.docx":            EPOXY_DIRECT_RULES,
    "Direct/xx.xx TREADWELL POLISH PROPOSAL - NewDirect.docx":            POLISH_DIRECT_RULES,
    "Direct/xx.xx.xx TREADWELL COMBO PROPOSAL - CUSTMOER NAME.docx":      COMBO_DIRECT_RULES,
    "Direct/xx.xx TREADWELL BUDGET PRICING.docx":                         BUDGET_DIRECT_RULES,
    "GC/xx TREADWELL POLISH PROPOSAL - xx.docx":                          GC_POLISH_RULES,
    "GC/xx TREADWELL RESINOUS PROPOSAL - xx.docx":                        GC_RESINOUS_RULES,
    "GC/xx TREADWELL SEALER PROPOSAL - xx.docx":                          GC_SEALER_RULES,
    "Gyp/xx TREADWELL UNDERLAYMENT PROPOSAL - xx.docx":                   GYP_RULES,
}

# Templates where the bare "xxx" alone (whole text node) is the job name.
# In Polish/Combo/Budget, the left sidebar has "xxx" as the job-name placeholder.
JOB_NAME_BARE_XXX_TEMPLATES = {
    "Direct/xx.xx TREADWELL POLISH PROPOSAL - NewDirect.docx",
    "Direct/xx.xx.xx TREADWELL COMBO PROPOSAL - CUSTMOER NAME.docx",
    "Direct/xx.xx TREADWELL BUDGET PRICING.docx",
}


# ─── GC audience-aware narrative (Scope / Schedule / Exclusions) ──────────
# Unlike the Direct templates (which already carry {{scope_notes}} etc.), the 3
# GC templates ship their Scope/Schedule/Exclusions as STATIC text, so the
# estimator's sidebar edits never reached the GC doc. We tokenize them here:
#   - Scope/Schedule/Exclusions each live in ONE <w:p> whose FIRST <w:t> run is
#     the bold label ("Scope:" / "Schedule:" / "Exclusions:"); the value is
#     fragmented across the following runs. `_tokenize_label_paragraph` keeps
#     the bold label, collapses the value into a single {{token}} run.
#   - Scope's label paragraph holds only step 1; the remaining scope steps are
#     SEPARATE <w:p> paragraphs after it. Those continuation paragraphs are
#     deleted (their wording is preserved as the backend/frontend GC scope
#     default, joined with "\n", so a blank sidebar re-seeds the full list).
# Everything else in the GC templates (system menu, GC/project addresses, price
# block, notes) stays as boilerplate. Each block appears TWICE (mc:Choice +
# mc:Fallback VML copy), so every op below hits both copies.
#
# The continuation strings are the XML-ESCAPED joined text of each paragraph
# (read straight from the pristine word/document.xml — "&amp;" not "&"), so
# `_delete_paragraphs` can match them exactly.
GC_SCOPE_CONTINUATIONS: dict[str, list[str]] = {
    "GC/xx TREADWELL RESINOUS PROPOSAL - xx.docx": [
        "Prepare substrate surface profile utilizing mechanical means (grinding or shot blasting)",
        "Prep substrate (includes patch of minor substrate defects i.e., cracks, non-moving joints, divots, &amp; spalls*)",
        "Install Resinous System  ^Patch material included:  xx gallons/kits.",
        "Assumes installation over: clean, sound &amp; solid concrete substrate",
    ],
    "GC/xx TREADWELL POLISH PROPOSAL - xx.docx": [
        "Grind and polish concrete with successive passes using finer grit pads for each pass",
        "Apply hardener/densifier &amp; topical sealer",
        "Apply joint filler",
        "Assumes polish over: clean, sound &amp; solid NEW concrete substrate",
    ],
    "GC/xx TREADWELL SEALER PROPOSAL - xx.docx": [
        "Clean Concrete; -or- Perform 1-2 passes with planetary grinder -or- auto scrubber",
        "Apply [1 coat -or- up to 2 coats of clear concrete sealer",
        "Assumes sealer over: clean, sound &amp; solid concrete substrate",
    ],
}

# Label → token for the GC Scope/Schedule/Exclusions paragraphs (same for all 3).
GC_NARRATIVE_LABELS: list[tuple[str, str]] = [
    ("Scope:",      "{{scope_notes}}"),
    ("Schedule:",   "{{schedule_notes}}"),
    ("Exclusions:", "{{exclusions}}"),
]

GC_NARRATIVE_TEMPLATES = set(GC_SCOPE_CONTINUATIONS.keys())


# ─── Replacement engine (raw-XML aware) ──────────────────────────────
WT_NODE_RE = re.compile(r"(<w:t\b[^>]*>)([^<]*)(</w:t>)")
AT_NODE_RE = re.compile(r"(<a:t\b[^>]*>)([^<]*)(</a:t>)")
WP_BLOCK_RE = re.compile(r"<w:p\b[^>]*>.*?</w:p>", re.DOTALL)


def _ensure_xml_space_preserve(opening: str) -> str:
    if "xml:space" in opening:
        return opening
    return opening.replace("<w:t", '<w:t xml:space="preserve"', 1).replace(
        "<a:t", '<a:t xml:space="preserve"', 1
    )


def _replace_text_in_xml(xml: str, search: str, replacement: str) -> tuple[str, int]:
    """Replace `search` -> `replacement` inside <w:t> / <a:t> text nodes.

    Handles BOTH single-run (text fits in one node) AND multi-run (text
    split across nodes due to formatting changes) cases.

    Returns (new_xml, n_subs).
    """
    n_subs = 0

    # Pass 1 — single-run inside <w:t>
    def _single_w(m):
        nonlocal n_subs
        opn, inner, cls = m.group(1), m.group(2), m.group(3)
        if search not in inner:
            return m.group(0)
        new_inner = inner.replace(search, xml_escape(replacement))
        n_subs += inner.count(search)
        return f"{_ensure_xml_space_preserve(opn)}{new_inner}{cls}"

    xml = WT_NODE_RE.sub(_single_w, xml)
    if n_subs > 0:
        return xml, n_subs

    # Pass 2 — single-run inside <a:t> (DrawingML text boxes)
    def _single_a(m):
        nonlocal n_subs
        opn, inner, cls = m.group(1), m.group(2), m.group(3)
        if search not in inner:
            return m.group(0)
        new_inner = inner.replace(search, xml_escape(replacement))
        n_subs += inner.count(search)
        return f"{_ensure_xml_space_preserve(opn)}{new_inner}{cls}"

    xml = AT_NODE_RE.sub(_single_a, xml)
    if n_subs > 0:
        return xml, n_subs

    # Pass 3 — multi-run in <w:p> paragraph (join all w:t runs, replace,
    # write back to first run).
    def _multi_p(p_match):
        nonlocal n_subs
        p_xml = p_match.group(0)
        nodes = list(WT_NODE_RE.finditer(p_xml))
        if not nodes:
            return p_xml
        joined = "".join(n.group(2) for n in nodes)
        if search not in joined:
            return p_xml
        new_joined = joined.replace(search, xml_escape(replacement))
        count = joined.count(search)
        n_subs += count

        # Write new_joined into the first <w:t>; empty subsequent ones
        rebuilt: list[str] = []
        cursor = 0
        for i, n in enumerate(nodes):
            rebuilt.append(p_xml[cursor:n.start()])
            opn, _, cls = n.group(1), n.group(2), n.group(3)
            if i == 0:
                rebuilt.append(f"{_ensure_xml_space_preserve(opn)}{new_joined}{cls}")
            else:
                rebuilt.append(f"{opn}{cls}")
            cursor = n.end()
        rebuilt.append(p_xml[cursor:])
        return "".join(rebuilt)

    xml = WP_BLOCK_RE.sub(_multi_p, xml)
    return xml, n_subs


def _replace_bare_xxx_with_token(xml: str, token: str) -> tuple[str, int]:
    """Replace every '<w:t>xxx</w:t>' (whole-node bare match) with
    '<w:t>{{token}}</w:t>'. Templates often have two header blocks
    (top of page 1 + repeating header on subsequent pages) and BOTH
    need the job name filled."""
    pattern = re.compile(r"(<w:t\b[^>]*>)xxx(</w:t>)")
    count = [0]

    def _sub(m):
        count[0] += 1
        opn = _ensure_xml_space_preserve(m.group(1))
        return f"{opn}{{{{{token}}}}}{m.group(2)}"

    xml_new = pattern.sub(_sub, xml)
    return xml_new, count[0]


def _tokenize_label_paragraph(xml: str, label: str, token_text: str) -> tuple[str, int]:
    """Tokenize a static "Label: <fragmented value>" paragraph.

    For EVERY <w:p> whose FIRST <w:t> text (stripped) exactly equals `label`,
    keep run[0] (the bold label) verbatim, rewrite run[1]'s text to
    `" " + token_text` (single leading space so it reads "Label: {{token}}"),
    and BLANK runs[2:] — collapsing the fragmented static value into one token
    run while leaving the bold label (and every run's own formatting) intact.
    Adds xml:space="preserve" to run[1] so the leading space survives.

    Hits BOTH the modern (mc:Choice) and legacy VML (mc:Fallback) copies of the
    paragraph, so `n >= 2` when a label is present. Returns (new_xml, n).
    """
    count = [0]

    def _sub(m):
        p_xml = m.group(0)
        tnodes = list(WT_NODE_RE.finditer(p_xml))
        if len(tnodes) < 2:
            return p_xml
        if (tnodes[0].group(2) or "").strip() != label:
            return p_xml
        count[0] += 1
        rebuilt: list[str] = []
        cursor = 0
        for i, n in enumerate(tnodes):
            rebuilt.append(p_xml[cursor:n.start()])
            opn, inner, cls = n.group(1), n.group(2), n.group(3)
            if i == 0:                       # bold label — verbatim
                rebuilt.append(f"{opn}{inner}{cls}")
            elif i == 1:                     # value run -> single token run
                new_inner = xml_escape(" " + token_text)
                rebuilt.append(f"{_ensure_xml_space_preserve(opn)}{new_inner}{cls}")
            else:                            # blank every trailing value fragment
                rebuilt.append(f"{opn}{cls}")
            cursor = n.end()
        rebuilt.append(p_xml[cursor:])
        return "".join(rebuilt)

    xml_new = WP_BLOCK_RE.sub(_sub, xml)
    return xml_new, count[0]


def _delete_paragraphs(xml: str, escaped_texts) -> tuple[str, int]:
    """Delete every <w:p> whose joined <w:t> text (stripped) exactly matches one
    of `escaped_texts` — given in XML-ESCAPED form ("&amp;" not "&") so they
    compare directly against the raw <w:t> contents. Removes both the mc:Choice
    and mc:Fallback copies. Returns (new_xml, n_deleted)."""
    wanted = set(escaped_texts)
    count = [0]

    def _sub(m):
        p_xml = m.group(0)
        joined = "".join(n.group(2) for n in WT_NODE_RE.finditer(p_xml))
        if joined.strip() in wanted:
            count[0] += 1
            return ""
        return p_xml

    xml_new = WP_BLOCK_RE.sub(_sub, xml)
    return xml_new, count[0]


def _insert_marker_paragraph(xml: str, anchor_text: str, marker: str, where: str) -> tuple[str, int]:
    """Insert a bare marker paragraph (`<w:p>…{marker}…</w:p>`) immediately
    before/after EVERY <w:p> whose joined <w:t> text (stripped) equals
    `anchor_text` (XML-escaped form). Used to wrap {{#block}}…{{/block}} markers
    around already-tokenized rows. `anchor_text` must never be a text box's FIRST
    paragraph (WP_BLOCK_RE would match a bogus span incl. the outer anchor).
    Returns (new_xml, n_inserted)."""
    count = [0]
    para = f'<w:p><w:r><w:t xml:space="preserve">{marker}</w:t></w:r></w:p>'

    def _sub(m):
        p_xml = m.group(0)
        joined = "".join(n.group(2) for n in WT_NODE_RE.finditer(p_xml))
        if joined.strip() != anchor_text:
            return p_xml
        count[0] += 1
        return (para + p_xml) if where == "before" else (p_xml + para)

    return WP_BLOCK_RE.sub(_sub, xml), count[0]


def annotate_one(path: Path, rules: list[tuple[str, str]], rel_path: str) -> int:
    print(f"\n=== {rel_path} ===")

    tmp = path.with_suffix(path.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()

    total = 0
    with zipfile.ZipFile(path, "r") as zin, zipfile.ZipFile(
        tmp, "w", zipfile.ZIP_DEFLATED
    ) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename in {"word/document.xml"} or item.filename.startswith("word/header") or item.filename.startswith("word/footer"):
                xml = data.decode("utf-8")
                for search, token in rules:
                    xml, n = _replace_text_in_xml(xml, search, token)
                    if n:
                        print(f"  [OK]  {search[:60]!r} -> {token}  ({n} subs)")
                        total += n
                # Bare-xxx job-name treatment for Polish/Combo/Budget
                if rel_path.replace("\\", "/") in JOB_NAME_BARE_XXX_TEMPLATES and item.filename == "word/document.xml":
                    xml, n = _replace_bare_xxx_with_token(xml, "job_name")
                    if n:
                        print(f"  [OK]  bare 'xxx' (first only) -> {{{{job_name}}}}  ({n} subs)")
                        total += n
                # GC audience-aware narrative: tokenize the static Scope/Schedule/
                # Exclusions labels + delete the extra scope-step paragraphs (both
                # the mc:Choice + mc:Fallback copies). document.xml only.
                _rel = rel_path.replace("\\", "/")
                if _rel in GC_NARRATIVE_TEMPLATES and item.filename == "word/document.xml":
                    for label, token in GC_NARRATIVE_LABELS:
                        xml, n = _tokenize_label_paragraph(xml, label, token)
                        if n:
                            print(f"  [OK]  label {label!r} -> {token}  ({n} paras)")
                            total += n
                    xml, n = _delete_paragraphs(xml, GC_SCOPE_CONTINUATIONS[_rel])
                    if n:
                        print(f"  [OK]  deleted {n} scope-continuation paragraph(s)")
                # Gyp underlayment: label-token Exclusions, delete leftover static
                # option/clarification rows, then wrap {{#block}} markers + bare-xx
                # job name. Order matters (delete before marker inserts).
                if _rel == _GYP_REL and item.filename == "word/document.xml":
                    for label, token in GYP_LABEL_TOKENS:
                        xml, n = _tokenize_label_paragraph(xml, label, token)
                        print(f"  [{'OK' if n else '--'}]  gyp label {label!r} -> {token}  ({n})")
                        total += n
                    xml, n = _delete_paragraphs(xml, GYP_DELETE_PARAS)
                    print(f"  [{'OK' if n else '--'}]  gyp deleted {n} static paragraph(s) (expect 42)")
                    for anchor, marker, where in GYP_MARKER_INSERTS:
                        xml, n = _insert_marker_paragraph(xml, anchor, marker, where)
                        print(f"  [{'OK' if n else '--'}]  gyp insert {marker} {where} {anchor[:34]!r}  ({n})")
                    # bare 'xx' (whole-node) = the job name (BOX0); only whole-node
                    # 'xx' remains after the rules above, so this is unambiguous.
                    _pat = re.compile(r"(<w:t\b[^>]*>)xx(</w:t>)")
                    _c = [0]
                    def _jn(mm):
                        _c[0] += 1
                        return f"{_ensure_xml_space_preserve(mm.group(1))}{{{{job_name}}}}{mm.group(2)}"
                    xml = _pat.sub(_jn, xml)
                    print(f"  [{'OK' if _c[0] else '--'}]  gyp bare 'xx' -> {{{{job_name}}}}  ({_c[0]})")
                data = xml.encode("utf-8")
            zout.writestr(item, data)

    shutil.move(str(tmp), str(path))
    return total


def main() -> int:
    # Optional argv filter: only (re-)annotate the named template(s). CRITICAL —
    # re-running the rules over an ALREADY-annotated template corrupts it, so pass
    # the target when adding/fixing ONE template (e.g. the Gyp file) and leave the
    # rest untouched. No args = annotate all (fresh-checkout bootstrap only).
    targets = {a.replace("\\", "/") for a in sys.argv[1:]}
    print(f"Annotating templates in {TEMPLATES_DIR}" + (f" (targets: {sorted(targets)})" if targets else " (ALL)"))
    grand_total = 0
    for rel_path, rules in TEMPLATE_RULES.items():
        if targets and rel_path.replace("\\", "/") not in targets:
            continue
        full = TEMPLATES_DIR / rel_path
        if not full.exists():
            print(f"\n!! Missing template: {rel_path}")
            continue
        grand_total += annotate_one(full, rules, rel_path)

    print(f"\nDone. {grand_total} total substitutions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
