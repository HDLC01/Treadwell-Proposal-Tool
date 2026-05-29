"""
Walk every .docx template, extract all text nodes (both <w:t> in body
and <a:t> in DrawingML text boxes), and print the candidate placeholder
strings so we can annotate them properly with {{tokens}}.
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

# Make stdout UTF-8 so Windows console doesn't choke on bullet/arrow chars
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TEMPLATES_DIR = Path(__file__).parent / "templates"

# Patterns that look like placeholders Troy fills in by hand
PLACEHOLDER_PATTERNS = [
    r"\bxxx+\b",                          # xxx, xxxx, xxxxx
    r"\bName\b",                          # the literal word "Name"
    r"\bCity,\s*State\b",
    r"\bJob Specification\b",
    r"\bMacro Flake\b|\bStandard Sheen\b|\bSalt & Pepper\b",  # system names
    r"\bOrange[- ]Peel\b",                # texture
    r"\bdumpster provided by owner\b",
    r"\$x+\b",                            # $x, $xx, $xxx, $xxxx
    r"\$\s*xx\b",                         # $ xx (with space)
    r"\b1/1/2[0-9]\b",                    # date placeholders 1/1/26 etc
    r"\bxx/xx/2[0-9]\b",
    r"~?\d{1,3},?\d{3,}\s*sf\b",          # ~1,600 sf
    r"\b\d{1,3},?\d{3,}\s*lf\b",
    r"\bKansas\b(?=.*Remodel)",
    r"\bper site visit on\b\s*[^\s<]*",
]


def all_text_in_docx(path: Path) -> list[tuple[str, str]]:
    """Return list of (source_file, text_node_value) tuples for every
    <w:t>/<a:t> inside every XML part of the docx."""
    out = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not name.endswith(".xml"):
                continue
            xml = z.read(name).decode("utf-8", errors="replace")
            for m in re.finditer(r"<(?:w|a):t\b[^>]*>([^<]*)</(?:w|a):t>", xml):
                t = m.group(1)
                if t.strip():
                    out.append((name, t))
    return out


def find_placeholders(text_nodes: list[tuple[str, str]]) -> dict[str, list[tuple[str, str]]]:
    """For each placeholder pattern, find which (file, text) nodes contain it."""
    hits: dict[str, list[tuple[str, str]]] = {p: [] for p in PLACEHOLDER_PATTERNS}
    for fname, text in text_nodes:
        for pattern in PLACEHOLDER_PATTERNS:
            if re.search(pattern, text):
                hits[pattern].append((fname, text))
    return hits


def main() -> None:
    for tpl_dir in ["Direct", "GC", "Gyp"]:
        for path in sorted((TEMPLATES_DIR / tpl_dir).glob("*.docx")):
            print(f"\n========== {tpl_dir}/{path.name} ==========")
            nodes = all_text_in_docx(path)
            hits = find_placeholders(nodes)
            for pattern, found in hits.items():
                if not found:
                    continue
                # Distinct source files for this pattern
                src_files = sorted({f for f, _ in found})
                print(f"  Pattern {pattern!r}: {len(found)} hit(s) in {src_files}")
                # Show up to 4 sample text nodes
                seen = set()
                for f, t in found:
                    key = t.strip()[:80]
                    if key in seen:
                        continue
                    seen.add(key)
                    print(f"     - {t.strip()[:120]!r}")
                    if len(seen) >= 4:
                        break


if __name__ == "__main__":
    main()
