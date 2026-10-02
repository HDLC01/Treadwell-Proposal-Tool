#!/usr/bin/env python3
"""Real-render proof for the Terms & Conditions pages and the blank WORK lines.

NOT a test: pytest collects `backend/tests` only, and this needs Docker, the licensed Zetta fonts
and PyMuPDF on the host. CI cannot run it; a person runs it before shipping a change to the
proposal document and reads the table it prints.

WHAT IT DOES
  1. Fills every proposal template that has a Terms section through the app's own path
     (`POST /api/generate` on a TestClient, auth stubbed exactly as tests/conftest.py stubs it,
     no database) with realistic values, Texture and the WORK Notes left blank on purpose, plus
     a second "filled" render of page 1 with both present.
  2. Converts the .docx files to PDF with `soffice --headless` in a throwaway container built
     from the PRODUCTION base image and the Dockerfile's own LibreOffice/font packages (read out
     of the Dockerfile, so the proof follows it). The Zetta fonts are mounted read-only at
     runtime exactly as compose does; they never enter an image layer.
  3. Measures every page with PyMuPDF and prints, per template: pages, full-page artworks per
     Terms page (and where they sit), the red bottom bar per page, the Terms font, the largest
     gap between two text lines on a Terms page (a "hole"), the hand-split clauses still left in
     the .docx, and whether page 1 prints a bare "Texture:" / "Notes:" line.
  4. Writes a PNG of every Terms page (and page 1) to --out.

  python backend/ops/terms_render_proof.py --fonts <zetta dir> --out <dir> --label after
  python backend/ops/terms_render_proof.py --backend <other checkout>/backend --label before \
      --packages "libreoffice-writer fonts-crosextra-carlito fonts-liberation" ...

`--backend` fills with another checkout's code (a worktree of the parent commit gives the
"before" documents); `--packages` overrides the apt packages read from this checkout's Dockerfile
(the Dockerfile before Caladea was added gives the "before" fonts). Exit status 1 when any check
fails, so a scripted run can gate on it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[2]
DOCKERFILE = REPO / "Dockerfile"

# (slug, work_type, audience). Every template with a Terms section; Budget has none.
CASES = [
    ("direct-epoxy", "epoxy", "Direct"),
    ("direct-polish", "polish", "Direct"),
    ("direct-combo", "combo", "Direct"),
    ("gc-polish", "polish", "GC"),
    ("gc-resinous", "epoxy", "GC"),
    ("gc-sealer", "sealer", "GC"),
    ("gyp", "gyp", "Direct"),
]

# Templates whose WORK box carries a `Texture: {{token}}` / `Notes: {{work_notes}}` line that
# prints nothing but its label when the value is blank (the GC files' lines carry Kyle's own
# words after the label, so they always print).
LABEL_LINES = {
    "direct-epoxy": ("Texture:", "Notes:"),
    "direct-polish": ("Notes:",),
    "direct-combo": ("Texture:", "Notes:"),
    "gyp": ("Notes:",),
}

_SENTENCE_END = re.compile(r"""[.:;!?)"”’']\s*$""")


def values_for(work_type: str, texture: str, work_notes: str) -> dict:
    """What Screen 3 sends for a plain, single-system job (the shape tests/test_kyle_feedback.py
    and tests/test_customer_paper_is_clean.py use), varied by work type."""
    v = {
        "job_name": "Release Check Warehouse", "project_name": "Release Check Warehouse",
        "city_state": "Olathe, KS", "address": "1707 E. 123rd Terrace",
        "bid_date": "2026-09-26", "bid_date_formatted": "9/26/26",
        "site_visit_date": "9/26/26", "site_visit_phrase": "per site visit on 9/26/26",
        "estimator_name": "Kyle Loseke",
        "system_name": "Treadwell MACRO Flake Single Broadcast",
        "texture": texture, "work_notes": work_notes,
        "epoxy_sf": "1,000", "polish_sf": "1,000", "sqft": "1,000", "cove_lf": "50",
        "area_description": "~1,000 sf of epoxy flooring",
        "base_bid_formatted": "$5,569", "material_tax_formatted": "$11",
        "total_formatted": "$5,580", "lump_sum_formatted": "$5,580",
        "tax_amount_formatted": "$0", "state_name": "Kansas",
        "base_tax_phrase": "(material sales tax INCLUDED)",
    }
    if work_type == "polish":
        v["system_name"] = "Standard Sheen Cream Finish"
        v["area_description"] = "~1,000 sf of polished concrete flooring"
    if work_type == "gyp":
        v["area_description"] = "~1,000 sf of gypsum underlayment"
    return v


def fill_all(backend: Path, out: Path, variant: str) -> dict:
    """Fill every case through the app's own /api/generate. Returns {slug: docx path}."""
    sys.path.insert(0, str(backend))
    os.chdir(str(backend))
    import supabase_client  # noqa: E402

    supabase_client.verify_token = lambda authorization: "tester@wetreadwell.com"
    from fastapi.testclient import TestClient  # noqa: E402

    import main  # noqa: E402

    client = TestClient(main.app)
    texture, notes = ("", "") if variant == "blank" else ("Orange Peel", "Owner moves the racking")
    got = {}
    for slug, wt, aud in CASES:
        body = {"work_type": wt, "audience": aud, "values": values_for(wt, texture, notes)}
        r = client.post("/api/generate", json=body)
        if r.status_code != 200:
            raise SystemExit(f"{slug}: /api/generate answered {r.status_code}: {r.text[:300]}")
        f = client.get(r.json()["docx_download_url"])
        if f.status_code != 200:
            raise SystemExit(f"{slug}: download answered {f.status_code}")
        path = out / f"{slug}-{variant}.docx"
        path.write_bytes(f.content)
        got[slug] = path
    return got


# ── the image ────────────────────────────────────────────────────────────────
def dockerfile_font_layer(dockerfile: Path) -> tuple[str, list]:
    """(production base image, the apt packages of the LibreOffice layer), read off the
    Dockerfile so this proof renders with whatever it installs."""
    text = dockerfile.read_text(encoding="utf-8")
    bases = re.findall(r"^FROM\s+(python:\S+)", text, re.M)
    if not bases:
        raise SystemExit("no python base image in the Dockerfile")
    m = re.search(r"apt-get install[^\n]*\\\s*\n\s*(libreoffice-writer[^\\\n]*)", text)
    if not m:
        raise SystemExit("no LibreOffice apt layer in the Dockerfile")
    return bases[-1], m.group(1).split()


def build_image(base: str, packages: list) -> str:
    tag = "tw-terms-proof:" + hashlib.sha256((base + " " + " ".join(packages)).encode()).hexdigest()[:12]
    have = subprocess.run(["docker", "image", "inspect", tag], capture_output=True)
    if have.returncode == 0:
        return tag
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "Dockerfile").write_text(
            f"FROM {base}\n"
            "RUN apt-get update && apt-get install -y --no-install-recommends "
            + " ".join(packages) + " \\\n && apt-get clean && rm -rf /var/lib/apt/lists/*\n"
            "RUN mkdir -p /usr/share/fonts/truetype/treadwell && fc-cache -f\n", encoding="utf-8")
        subprocess.run(["docker", "build", "-q", "-t", tag, tmp], check=True)
    return tag


def convert(image: str, fonts: Path, work: Path) -> str:
    """soffice every .docx in `work` to PDF in one throwaway container; returns fc-match Cambria."""
    name = f"tw-terms-proof-{os.getpid()}"
    cmd = ["docker", "run", "--rm", "--name", name,
           "--mount", f"type=bind,source={work},target=/work",
           "--mount", f"type=bind,source={fonts},target=/usr/share/fonts/truetype/treadwell,readonly",
           image, "sh", "-c",
           "fc-match Cambria > /work/fc-match.txt; "
           "soffice --headless --norestore -env:UserInstallation=file:///tmp/lo "
           "--convert-to pdf --outdir /work /work/*.docx > /work/soffice.log 2>&1"]
    try:
        subprocess.run(cmd, check=True, timeout=900)
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    return (work / "fc-match.txt").read_text(encoding="utf-8", errors="replace").strip() if (work / "fc-match.txt").exists() else ""


# ── the measurements ─────────────────────────────────────────────────────────
def docx_splits(docx_path: Path) -> list:
    """Terms paragraphs that stop mid-sentence and continue in the next unnumbered paragraph:
    [(text tail, continuation head)]. Counted from the first numbered clause on, so the heading
    lines above it are not mistaken for one."""
    import docx  # noqa: E402
    from docx.oxml.ns import qn  # noqa: E402

    d = docx.Document(str(docx_path))
    tops = [c for c in d.element.body if c.tag == qn("w:p")]
    texts = ["".join(t.text or "" for t in p.iter(qn("w:t"))) for p in tops]
    heading = next((i for i, t in enumerate(texts) if t.strip().upper() == "TERMS AND CONDITIONS"), None)
    if heading is None:
        return []

    def numbered(p):
        ppr = p.find(qn("w:pPr"))
        return ppr is not None and ppr.find(qn("w:numPr")) is not None

    first = next((i for i in range(heading, len(tops)) if numbered(tops[i])), None)
    if first is None:
        return []
    filled = [i for i in range(first, len(tops)) if texts[i].strip()]
    out = []
    for a, b in zip(filled, filled[1:]):
        if not _SENTENCE_END.search(texts[a].strip().strip(" ")) and not numbered(tops[b]):
            out.append((texts[a].strip()[-30:], texts[b].strip()[:30]))
    return out


# Kyle's letterheads are 1275x1649 px (US Letter at 150 dpi) in every template; anything else
# drawn over the whole sheet is a stray (the Gyp form's page-1 footer carries an older letterhead
# as an EMF, which LibreOffice also draws, off the sheet, past the page it belongs to).
LETTERHEAD_PX = (1275, 1649)
HOLE_PT = 36.0          # half an inch; Kyle's own heading spacing (up to three 9pt lines) is under it


def _visible_px(doc, page_index: int, xref: int) -> int:
    """How many pixels of page `page_index` change when image `xref` is blanked: 0 = it draws
    nothing anybody can see there."""
    import fitz  # noqa: E402

    a = doc[page_index].get_pixmap(dpi=36)
    tmp = fitz.open(doc.name)                   # same xrefs: a fresh open of the same file
    tmp[page_index].delete_image(xref)          # swaps in a 1x1 fully transparent image
    b = tmp[page_index].get_pixmap(dpi=36)
    if (a.width, a.height) != (b.width, b.height):
        return a.width * a.height
    sa, sb, n = a.samples, b.samples, a.n
    return sum(1 for k in range(0, len(sa), n) if sa[k:k + 3] != sb[k:k + 3])


def measure(pdf_path: Path, png_dir: Path, slug: str, label: str, docx_path: Path) -> dict:
    import fitz  # noqa: E402

    doc = fitz.open(str(pdf_path))
    W, H = doc[0].rect.width, doc[0].rect.height
    terms_start = None
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text()
        if terms_start is None and "TERMS AND CONDITIONS" in text:
            terms_start = i
        arts, strays = [], []
        for info in page.get_image_info(xrefs=True):
            x0, y0, x1, y1 = info["bbox"]
            if (x1 - x0) < 0.95 * W or (y1 - y0) < 0.95 * H:
                continue
            if (info["width"], info["height"]) == LETTERHEAD_PX:
                arts.append([round(y0, 1), round(y1, 1)])
            else:
                strays.append({"xref": info["xref"], "px": [info["width"], info["height"]],
                               "y": [round(y0, 1), round(y1, 1)]})
        clip = fitz.Rect(0, 0.9 * H, W, H)
        pix = page.get_pixmap(clip=clip, dpi=72)
        red = 0
        s = pix.samples
        n = pix.n
        for k in range(0, len(s), n):
            if s[k] > 170 and s[k + 1] < 90 and s[k + 2] < 90:
                red += 1
        lines = []
        fonts = {}
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = [sp for sp in line["spans"] if sp["text"].strip()]
                if not spans:
                    continue
                lines.append((line["bbox"][1], line["bbox"][3], "".join(sp["text"] for sp in spans)))
                for sp in spans:
                    f = sp["font"].split("+", 1)[-1]
                    fonts[f] = fonts.get(f, 0) + len(sp["text"])
        lines.sort()
        pages.append({"index": i, "arts": arts, "strays": strays, "red_px": red, "lines": lines,
                      "fonts": fonts})
    terms = [p for p in pages if terms_start is not None and p["index"] >= terms_start]
    for p in terms:
        gaps = []
        prev = None
        for y0, y1, _t in p["lines"]:
            if prev is not None and y0 > prev:
                gaps.append(round(y0 - prev, 1))
            prev = max(prev or 0, y1)
        p["max_gap"] = max(gaps) if gaps else 0.0
        p["first_line_y"] = round(p["lines"][0][0], 1) if p["lines"] else None
        for st in p["strays"]:
            st["visible_px"] = _visible_px(doc, p["index"], st["xref"])
        page = doc[p["index"]]
        page.get_pixmap(dpi=100).save(str(png_dir / f"{slug}-{label}-p{p['index'] + 1}.png"))
    doc[0].get_pixmap(dpi=100).save(str(png_dir / f"{slug}-{label}-p1.png"))
    term_fonts = {}
    for p in terms:
        for f, n in p["fonts"].items():
            term_fonts[f] = term_fonts.get(f, 0) + n
    # A WORK row's bullet is a glyph of its own; compare the words only.
    words = [re.sub(r"^[^\w]+", "", t.strip()) for _y0, _y1, t in pages[0]["lines"]]
    bare = []
    for k, w in enumerate(words):
        if w in ("Texture:", "Notes:"):
            nxt = words[k + 1] if k + 1 < len(words) else ""
            bare.append({"label": w, "next": nxt[:40]})
    labelled = {lab: [w for w in words if w.startswith(lab) and w[len(lab):].strip()]
                for lab in ("Texture:", "Notes:")}
    return {
        "pages": len(doc),
        "terms_pages": [p["index"] + 1 for p in terms],
        "arts_per_terms_page": [len(p["arts"]) for p in terms],
        "art_y": [p["arts"] for p in terms],
        "strays": [p["strays"] for p in terms],
        "red_bar_per_page": [p["red_px"] > 2000 for p in pages],
        "max_gap_pt": [p.get("max_gap") for p in terms],
        "first_line_y": [p.get("first_line_y") for p in terms],
        "terms_font": max(term_fonts, key=term_fonts.get) if term_fonts else None,
        "terms_fonts": term_fonts,
        "splits": docx_splits(docx_path),
        "page1_bare_labels": bare,
        "page1_labelled": labelled,
    }


# A bare label that heads Kyle's own sub-item stays by design (proposal_writer._omit_bare_lines).
HEADS_SUB_ITEM = {("gyp", "Notes:"): "Floor Leveling is NOT included"}


def verdict(slug: str, m: dict, variant: str) -> list:
    """The failed checks, as sentences."""
    bad = []
    unexplained = [b for b in m["page1_bare_labels"]
                   if HEADS_SUB_ITEM.get((slug, b["label"]), "\0") not in b["next"]]
    if variant == "blank":
        if not m["terms_pages"]:
            bad.append("no Terms page found")
        if any(n != 1 for n in m["arts_per_terms_page"]):
            bad.append("a Terms page does not draw exactly one letterhead")
        for ys in m["art_y"]:
            for y0, y1 in ys:
                if y0 < -2 or y0 > 2 or y1 < 789 or y1 > 794:
                    bad.append(f"a letterhead sits at y={y0}..{y1}, not 0..792")
        for strays in m["strays"]:
            for st in strays:
                if st["visible_px"]:
                    bad.append(f"a stray full-page image ({st['px']}) shows {st['visible_px']} px")
        if not all(m["red_bar_per_page"]):
            bad.append("a page has no red bottom bar")
        if any(g is not None and g > HOLE_PT for g in m["max_gap_pt"]):
            bad.append(f"a Terms page has a hole (gap > {HOLE_PT:g}pt between two lines)")
        if m["splits"]:
            bad.append(f"{len(m['splits'])} hand-split clause(s) remain")
        if not str(m["terms_font"] or "").startswith("Caladea"):
            bad.append(f"the Terms print in {m['terms_font']}, not Caladea")
        if unexplained:
            bad.append(f"page 1 prints a bare {[b['label'] for b in unexplained]}")
    else:
        if unexplained:
            bad.append("a filled label line printed bare")
        for lab in LABEL_LINES.get(slug, ()):
            if not m["page1_labelled"].get(lab):
                bad.append(f"the filled {lab} line is missing from page 1")
    return bad


def main_(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--backend", type=Path, default=REPO / "backend")
    ap.add_argument("--fonts", type=Path, required=True, help="directory holding the Zetta fonts")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--label", default="after")
    ap.add_argument("--packages", default="", help="override the Dockerfile's apt packages")
    ap.add_argument("--image", default="", help="use this LibreOffice image instead of building")
    args = ap.parse_args(argv)

    out = args.out.resolve()
    work = out / ("work-" + args.label)
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    docs = {v: fill_all(args.backend.resolve(), work, v) for v in ("blank", "filled")}

    base, packages = dockerfile_font_layer(DOCKERFILE)
    if args.packages:
        packages = args.packages.split()
    image = args.image or build_image(base, packages)
    cambria = convert(image, args.fonts.resolve(), work)

    report = {"label": args.label, "image": image, "base": base, "packages": packages,
              "fc_match_cambria": cambria, "templates": {}}
    failed = False
    print(f"label={args.label} image={image}\npackages={' '.join(packages)}\nfc-match Cambria -> {cambria}")
    print(f"{'template':14s} pages  arts/terms-page  red-bar/page        max-gap  splits  "
          f"font             bare-on-p1  stray-visible-px")
    for slug, _wt, _aud in CASES:
        row = {}
        for variant in ("blank", "filled"):
            docx_path = docs[variant][slug]
            pdf = docx_path.with_suffix(".pdf")
            if not pdf.exists():
                raise SystemExit(f"{slug}: soffice produced no PDF (see {work / 'soffice.log'})")
            m = measure(pdf, out, slug, args.label if variant == "blank" else args.label + "-filled",
                        docx_path)
            m["failed"] = verdict(slug, m, variant)
            failed = failed or bool(m["failed"])
            row[variant] = m
        report["templates"][slug] = row
        b = row["blank"]
        print(f"{slug:14s} {b['pages']:5d}  {str(b['arts_per_terms_page']):15s}  "
              f"{''.join('Y' if r else 'n' for r in b['red_bar_per_page']):18s} "
              f"{max([g for g in b['max_gap_pt'] if g is not None] or [0]):7.1f}  {len(b['splits']):6d}  "
              f"{str(b['terms_font']):16s} {','.join(x['label'] for x in b['page1_bare_labels']) or '-':11s} "
              f"{sum(st['visible_px'] for page in b['strays'] for st in page)}")
        for variant in ("blank", "filled"):
            for msg in row[variant]["failed"]:
                print(f"    FAIL ({variant}): {msg}")
    (out / f"report-{args.label}.json").write_text(json.dumps(report, indent=2, default=str),
                                                     encoding="utf-8")
    print(f"report: {out / ('report-' + args.label + '.json')}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main_())
