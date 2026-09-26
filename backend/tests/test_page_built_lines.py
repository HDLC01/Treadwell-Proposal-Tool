"""A price line the editor does not draw on a template never prints on it.

Review of the 2026-09-26 editor release. A base pick keeps the words typed into the base line
(TWPrice.applyBasePick, Hanz 2026-09-26: keep the words), so an Epoxy draft whose base line read
"$15,000 – Epoxy flooring as described above, warehouse only", with a note typed under it and its
bullet switched off, carried all of that onto a Polish base. Polish Direct writes its base line as a
plain template paragraph, not inside {{#single_bid}}, and the editor draws the page's own base line
(#base-bid-row) from the single_bid region only. So the Proposal step showed Polish's computed
"$9,860 – Polished Concrete Flooring as described above (...)", marked nothing and warned about
nothing, while the customer's PDF printed his "$15,000 – ..., warehouse only", his note and his
bullet. The "Base Bid" heading had the same gap on every template that writes it as a plain
paragraph (Polish Direct, the GC files, Gyp).

The rule, both halves:
  * the editor: REGION_MOUNTS (proposal-review.js) mounts #base-bid-row and #base-bid-heading from
    single_bid and from no other region, by each block's OUTERMOST region (annotateRegions). Both
    are EXECUTED here, in node, over every template's real block texts.
  * the writer: main.py asks proposal_writer.template_page_built_lines and hands the writer a
    page-built base line / heading, and the lines typed round them and their bullets, only where
    the answer is yes. They stay in the draft, and print again under a base whose template draws
    them.
"""
import io
import json
import pathlib
import re
import shutil
import subprocess

import docx
import pytest
from docx.oxml.ns import qn
from starlette.requests import Request

import main
import proposal_writer as pw

REVIEW_JS = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "js" / "proposal-review.js"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "price-lines-harness.js"
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
TAX = "⟦tax⟧"
PICKS = sorted(pw.TEMPLATE_PICKER, key=lambda k: (k[0], k[1] or ""))
ID = {"base": "base-bid-row", "heading_base": "base-bid-heading"}

# The editor's own two functions, lifted out of proposal-review.js the way the node harnesses lift
# them, and run over the block texts /api/proposal-template serves (iter_editable_blocks).
_EDITOR = r"""
const fs = require("fs");
const SRC = fs.readFileSync(process.argv[1], "utf8").replace(/\r\n/g, "\n");
function fnText(name) {
  const m = new RegExp("\\n  function " + name + "\\s*\\(").exec(SRC);
  if (!m) throw new Error(name + "() is gone from proposal-review.js");
  const open = SRC.indexOf("{", m.index + m[0].length - 1);
  for (let d = 0, j = open; j < SRC.length; j++) {
    if (SRC[j] === "{") d++; else if (SRC[j] === "}" && --d === 0) return SRC.slice(m.index, j + 1);
  }
  throw new Error("unbalanced " + name);
}
function constText(name) {
  const m = new RegExp("\\n  const " + name + " =").exec(SRC);
  if (!m) throw new Error("const " + name + " is gone from proposal-review.js");
  for (let d = 0, j = m.index + m[0].length; j < SRC.length; j++) {
    const ch = SRC[j];
    if ("([{".includes(ch)) d++; else if (")]}".includes(ch)) d--; else if (ch === ";" && d === 0) return SRC.slice(m.index, j + 1);
  }
  throw new Error("unterminated " + name);
}
const lib = new Function("document", "systemPreviewEl", "notesPreviewEl",
  constText("REGION_MOUNTS") + "\n" + fnText("annotateRegions") + "\nreturn { REGION_MOUNTS, annotateRegions };")(
  { getElementById: (id) => ({ id }) }, { id: "system-preview-block" }, { id: "notes-preview-block" });
const mounts = {};
for (const [name, f] of Object.entries(lib.REGION_MOUNTS)) mounts[name] = f().filter(Boolean).map((e) => e.id);
const docs = JSON.parse(fs.readFileSync(0, "utf8"));
const out = {};
for (const [name, texts] of Object.entries(docs)) {
  const blocks = texts.map((text) => ({ text }));
  lib.annotateRegions(blocks);
  out[name] = blocks.map((b) => b._region);
}
console.log(JSON.stringify({ mounts, regions: out }));
"""


def _blocks(work_type, audience):
    d = docx.Document(str(pw.pick_template(work_type, audience)))
    return [t or "" for _i, _k, _p, _b, t, _x in pw.iter_editable_blocks(d)]


@pytest.fixture(scope="module")
def editor():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    docs = {"%s|%s" % k: _blocks(*k) for k in PICKS}
    p = subprocess.run(["node", "-e", _EDITOR, str(REVIEW_JS)], input=json.dumps(docs),
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    got = json.loads(p.stdout)
    got["docs"] = docs
    return got


def _is_anchor(key, text):
    anchor = pw._PAGE_BUILT_ANCHORS[key]
    return (pw._heading_text_matches(text, anchor) if isinstance(anchor, str)
            else any(p.search(text) for p in anchor))


def test_only_the_single_bid_region_mounts_the_pages_base_line_and_heading(editor):
    """The table the writer's rule mirrors, run: #base-bid-row and #base-bid-heading are mounted by
    single_bid and by no other region. A new mount of either elsewhere has to reach
    proposal_writer.page_built_lines too, and this test fails until it does."""
    for key, el in ID.items():
        by = sorted(r for r, ids in editor["mounts"].items() if el in ids)
        assert by == ["single_bid"], (key, by)


@pytest.mark.parametrize("pick", PICKS, ids=lambda k: "%s-%s" % k)
def test_the_writer_prints_a_page_line_exactly_where_the_editor_draws_one(editor, pick):
    """For every template the picker can choose: the editor draws the page's own base line (and
    "Base Bid" heading) where the block holding the template's line has an outermost region whose
    mount holds that island -- annotateRegions and REGION_MOUNTS, executed -- and the writer's
    answer is the same. Epoxy and Combo Direct: yes. Polish Direct, Budget, every GC file, Gyp: no.
    Mutation: page_built_lines answering yes wherever the template holds the line at all (Polish
    Direct, the GC files and Gyp would count)."""
    texts = editor["docs"]["%s|%s" % pick]
    regions = editor["regions"]["%s|%s" % pick]
    want = {}
    for key, el in ID.items():
        hits = [i for i, t in enumerate(texts) if _is_anchor(key, t)]
        want[key] = any(regions[i] and el in editor["mounts"].get(regions[i], []) for i in hits)
    assert pw.template_page_built_lines(*pick) == want, (pick, want)
    if pick in (("epoxy", "Direct"), ("combo", "Direct")):
        assert want == {"base": True, "heading_base": True}
    if pick == ("polish", "Direct"):
        assert want == {"base": False, "heading_base": False}


def test_the_price_lines_harness_mounts_what_the_real_templates_do():
    """price-lines-harness.js models which islands a template mounts from TEMPLATE_REGIONS, each
    Direct template's outermost region names in order. Pinned against the real files, with
    annotateRegions' own stack (the harness is what the base-pick tests believe the page shows)."""
    src = HARNESS.read_text(encoding="utf-8")
    m = re.search(r"const TEMPLATE_REGIONS = \{(.*?)\n\};", src, re.S)
    assert m, "TEMPLATE_REGIONS is gone from price-lines-harness.js"
    table = {k: json.loads(v) for k, v in re.findall(r"^\s*(\w+): (\[[^\]]*\]),?$", m.group(1), re.M)}
    assert sorted(table) == ["combo", "epoxy", "polish"], table
    for wt, names in table.items():
        stack, seen = [], []
        for t in _blocks(wt, "Direct"):
            s = pw.BLOCK_START_RE.search(t)
            if s:
                stack.append(s.group(1))
            if stack and stack[0] not in seen:
                seen.append(stack[0])
            e = pw.BLOCK_END_RE.search(t)
            if e and stack and stack[-1] == e.group(1):
                stack.pop()
        assert names == seen, (wt, names, seen)


# ── the document ────────────────────────────────────────────────────────────────────────────────
_VALUES = {"project_name": "Hanz Fix", "job_name": "Hanz Fix", "city_state": "Iloilo City, KS",
           "texture": "Smooth", "system_name": "S", "scope_notes": "s", "schedule_notes": "s",
           "exclusions": "e", "estimator_name": "Hanz", "bid_date_formatted": "9/25/26",
           "total_formatted": "$9,860", "material_tax_formatted": "$110", "tax_amount_formatted": "$745",
           "base_bid_formatted": "$9,860"}
# What a base pick from an Epoxy tab carries onto the next base: his base line with his figure,
# the note under it and the line above it, the bullet he switched off and the indent under it, and
# a renamed "Base Bid" heading with a line typed under it.
_CARRIED = {
    "lines2": {"base": "$15,000 – Polished Concrete Flooring as described above, warehouse only " + TAX,
               "heading_base": "Base Bid – warehouse"},
    "before": {"base": ["above the base line"]},
    "after": {"base": ["", "THis is a test send to Hanz"], "heading_base": ["under the heading"]},
    "line_props": {"base": {"bullet": False, "indent": 576}},
    "after_props": {"base": [None, {"bullet": False, "indent": 864}]},
}
_HIS = ("$15,000", "warehouse only", "THis is a test send to Hanz", "above the base line",
        "Base Bid – warehouse", "under the heading")


def _render(work_type, audience, pov, layout):
    p = {"work_type": work_type, "audience": audience or "Direct", "values": dict(_VALUES, tax_layout=layout),
         "rooms": [], "price_lines": [], "remodel": [{"amount_formatted": "$745"}],
         "price_overrides": json.loads(json.dumps(pov))}
    req = Request({"type": "http", "method": "POST", "path": "/t", "headers": [], "query_string": b""})
    d = docx.Document(io.BytesIO(main._render_documents(p, req, want_estimate=False)["docx"]["content"]))
    out = []
    for q in d.element.xpath("//w:p"):
        if any(True for _ in q.iterancestors(f"{_MC}Fallback")) or q.find(".//" + qn("w:txbxContent")) is not None:
            continue
        ppr = q.find(qn("w:pPr"))
        num = ppr.find(qn("w:numPr")) if ppr is not None else None
        ind = ppr.find(qn("w:ind")) if ppr is not None else None
        out.append((pw._own_text(q), None if num is None else pw._para_num_ref(q),
                    None if ind is None else dict(ind.attrib)))
    return out


_NOT_DRAWN = [k for k in PICKS if not any(pw.template_page_built_lines(*k).values())]


@pytest.mark.parametrize("layout", ["ONE_LINE", "BROKEN_OUT"])
@pytest.mark.parametrize("pick", _NOT_DRAWN, ids=lambda k: "%s-%s" % k)
def test_what_the_editor_does_not_draw_changes_nothing_on_paper(pick, layout):
    """On a template that draws neither the page's base line nor its heading, everything a base
    pick carried in prints exactly nothing: the document is paragraph for paragraph (words, list,
    indent) the one the same payload builds with none of it. His words are still in the draft.
    Mutation: main.py handing the writer the page-built base line or heading, or the lines typed
    round them, on such a template (Polish Direct prints his $15,000; the GC files and Gyp print his
    heading and the line under it)."""
    bare = _render(*pick, {}, layout)
    carried = _render(*pick, _CARRIED, layout)
    assert carried == bare, [c for c in carried if c not in bare]
    assert not any(h in t for t, _n, _i in carried for h in _HIS)


@pytest.mark.parametrize("pick", [("epoxy", "Direct"), ("combo", "Direct")], ids=lambda k: "%s-%s" % k)
def test_where_the_editor_draws_them_they_print(pick):
    """The counterexample: on the templates that draw the page's base line and heading, the same
    carried edits print, every one (so the test above is not passing on a payload that prints
    nothing anywhere)."""
    texts = [t for t, _n, _i in _render(*pick, _CARRIED, "ONE_LINE")]
    for h in _HIS:
        assert any(h in t for t in texts), (h, pick)
