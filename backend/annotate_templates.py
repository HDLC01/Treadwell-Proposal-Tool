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
    # Job header — left sidebar
    ("xxx, KS",                                                  "{{city_state}}"),
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
    ("xxx, KS",                                               "{{city_state}}"),
]

BUDGET_DIRECT_RULES: list[tuple[str, str]] = [
    ("xxx, KS",                                               "{{city_state}}"),
]

GC_POLISH_RULES: list[tuple[str, str]] = [
    ("Standard Sheen with Salt &amp; Pepper Aggregate Exposure", "{{system_name}}"),
    ("Standard Sheen with Salt & Pepper Aggregate Exposure",     "{{system_name}}"),
]

GC_RESINOUS_RULES: list[tuple[str, str]] = [
    ("Orange-Peel or Smooth or", "{{texture}}"),
    ("Treadwell Epoxy Flooring System", "{{system_name}}"),
]

GC_SEALER_RULES: list[tuple[str, str]] = [
    ("Treadwell Concrete Sealer System", "{{system_name}}"),
]

GYP_RULES: list[tuple[str, str]] = []   # mostly generic, no placeholders found

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
                data = xml.encode("utf-8")
            zout.writestr(item, data)

    shutil.move(str(tmp), str(path))
    return total


def main() -> int:
    print(f"Annotating templates in {TEMPLATES_DIR}")
    grand_total = 0
    for rel_path, rules in TEMPLATE_RULES.items():
        full = TEMPLATES_DIR / rel_path
        if not full.exists():
            print(f"\n!! Missing template: {rel_path}")
            continue
        grand_total += annotate_one(full, rules, rel_path)

    print(f"\nDone. {grand_total} total substitutions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
