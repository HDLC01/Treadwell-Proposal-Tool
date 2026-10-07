"""docs/v2-architecture.md is a ledger, and a ledger that nobody checks is wrong within a month.

Its section 7 lists every place the same fact is written down today and what each phase does about
it. The program's first rule is "replace, do not run in parallel": the phase that removes a copy
updates that table in the same change. This test is what makes that real. It does NOT pin line
numbers (the document says they drift, and they do). It pins what does not drift:

  * every `path:line` citation names a file that exists and is at least that long;
  * every named copy (`SCOPE_BY_WORK_TYPE`, `TEMPLATE_PICKER`, `CONDITION_CELLS` ...) is still
    defined in the file the document puts it in, and the document still names it. When a phase
    deletes one of these on purpose, this test goes red until the table is updated, which is the
    point: the table is the record of what is left to remove;
  * the vector counts the document quotes are the golden files' own;
  * the document stays in plain words (no em dashes), and holds nothing the repository's
    infrastructure scan objects to.
"""
import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "v2-architecture.md"
FRONTEND = ROOT / "frontend"
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"

# (file under the repo root, a name the document uses for a copy that lives there)
NAMED_COPIES = [
    ("frontend/js/index.js", "SCOPE_BY_WORK_TYPE"),
    ("frontend/js/index.js", "CONDITIONS"),
    ("frontend/js/library.js", "WORK_TYPES"),
    ("frontend/js/estimate-review.js", "BASE_ROLE"),
    ("frontend/js/proposal-review.js", "effectiveWorkType"),
    ("backend/markup.py", "TABS"),
    ("backend/library.py", "WORK_TYPES"),
    ("backend/leads.py", "_WORK_TYPES"),
    ("backend/proposal_writer.py", "TEMPLATE_PICKER"),
    ("backend/cover_letter_writer.py", "TEMPLATE_PICKER"),
    ("backend/info_sheet_writer.py", "_SF_KEYS"),
    ("backend/info_sheet_writer.py", "_LF_KEYS"),
    ("backend/info_sheet_writer.py", "_COVE_ROLES"),
    ("backend/main.py", "detect_work_type"),
    ("frontend/js/polish-intake.js", "CONDITIONS"),
    ("frontend/js/bid-model.js", "CONDITION_CELLS"),
    ("frontend/js/polish-estimate.js", "CONDITION_CARDS"),
    ("backend/condition_defaults.py", "KEYS"),
    ("frontend/js/estimate-review.js", "JOB_FLAG_ADDR"),
    ("frontend/js/estimate-review.js", "JOB_FLAG_LITERAL_LAYOUTS"),
    ("frontend/js/estimate-review.js", "JOB_FLAG_LAYOUTS"),
    ("frontend/js/estimate-review.js", "JOB_FLAG_TEMPLATE"),
    ("backend/estimate_writer.py", "POLISH_CELL_MAP"),
    ("frontend/js/bid-model.js", "RATES"),
    ("frontend/js/bid-model.js", "GP_BANDS"),
    ("frontend/js/markup.js", "GP_5_BANDS"),
    ("frontend/js/markup.js", "BUILTIN"),
    ("backend/pricing.py", "_gp_pct"),
    ("backend/pricing.py", "compute_full_bid"),
    ("frontend/js/bid-model.js", "roundUp"),
    ("frontend/js/markup-core.js", "excelRoundUp"),
    ("backend/pricing.py", "_roundup"),
    ("frontend/js/markup.js", "round12"),
    ("frontend/js/estimate-review.js", "GYP_SF_CELLS"),
    ("frontend/js/estimate-review.js", "AREA_SF_CELLS"),
    ("frontend/js/estimate-review.js", "sfFieldsFor"),
    ("frontend/js/estimate-review.js", "PRICED_ROLES"),
    ("frontend/js/estimate-review.js", "OPTION_ONLY_ROLES"),
    ("frontend/js/estimate-review.js", "COMBINED_BASE_ROLES"),
    ("frontend/js/proposal-review.js", "OPTION_ONLY_ROLES"),
    ("frontend/js/proposal-review.js", "COMBINED_BASE_ROLES"),
    ("frontend/js/estimate-review.js", "baseFlagSheets"),
    ("frontend/js/estimate-review.js", "_areaBaseIds"),
    ("frontend/js/proposal-review.js", "_areaBaseIds"),
    ("frontend/js/polish-intake.js", "pickCounty"),
    ("frontend/js/polish-intake.js", "filterCounties"),
    ("frontend/js/county-picker.js", "county"),
    ("frontend/js/polish-estimate.js", "saveSoon"),
    ("frontend/js/polish-estimate.js", "pagehide"),
    # Phase 2: the test copy's cell list (7.3), and the browser's twin of the server's v2 test (7.11).
    ("frontend/js/polish-sandbox.js", "COPYABLE_CELLS"),
    ("backend/drafts.py", "_polish_beta"),
    ("frontend/shared.js", "isV2Draft"),
]


@pytest.fixture(scope="module")
def doc():
    return DOC.read_text(encoding="utf-8")


def test_the_document_exists_and_has_the_sections_the_program_relies_on(doc):
    for heading in ("## 3. The modules and their layers", "## 4. The header every module carries",
                    "## 5. The rules every change follows", "## 6. How we know a change did not move a price",
                    "## 7. Every concept, where it is copied today"):
        assert heading in doc, heading
    for sub in ("7.1", "7.2", "7.3", "7.4", "7.5", "7.6", "7.7", "7.8", "7.9", "7.10"):
        assert "### %s " % sub in doc, sub
    for module in ("js/excel-math.js", "js/work-types.js", "js/bid-profiles.js", "js/bid-model.js",
                   "js/bid-engine.js", "js/intake-scope.js"):
        assert module in doc, module


def _resolve(path: str) -> pathlib.Path:
    return (FRONTEND / path) if path.startswith("js/") else (ROOT / path)


def test_every_citation_names_a_real_file_that_is_long_enough(doc):
    cites = re.findall(r"`((?:js|backend)/[\w./-]+\.(?:js|py)):(\d+)(?:-(\d+))?`", doc)
    assert len(cites) >= 40, "the table lost its citations"
    for path, first, last in cites:
        f = _resolve(path)
        assert f.is_file(), "%s is cited and does not exist" % path
        n = len(f.read_text(encoding="utf-8").splitlines())
        assert int(last or first) <= n, "%s:%s is past the end of the file (%d lines)" % (path, last or first, n)


@pytest.mark.parametrize("path, name", NAMED_COPIES)
def test_every_named_copy_is_still_where_the_document_says(doc, path, name):
    """A phase that deletes a copy on purpose must update the table. Until it does, this is red."""
    src = (ROOT / path).read_text(encoding="utf-8")
    assert name in src, "%s no longer mentions %s: update docs/v2-architecture.md section 7" % (path, name)
    if path != "frontend/js/county-picker.js":
        assert "`%s`" % name in doc or ("`%s" % name) in doc, "the document no longer names %s" % name


def test_the_vector_counts_the_document_quotes_are_the_golden_files_own(doc):
    chain = json.loads((FIXTURES / "polish_chain_golden.json").read_text(encoding="utf-8"))["meta"]["n"]
    library = json.loads((FIXTURES / "library_pricing_golden.json").read_text(encoding="utf-8"))["meta"]["n"]
    assert "%s vectors over the Polish maths" % format(chain, ",") in doc, \
        "regenerated the chain golden? update the count in docs/v2-architecture.md section 6"
    assert "%s vectors over `priceLine` and `priceAssembly`" % format(library, ",") in doc, \
        "regenerated the library golden? update the count in docs/v2-architecture.md section 6"


def test_the_document_is_in_plain_words(doc):
    assert "—" not in doc and "–" not in doc, "no em dashes or en dashes: plain words"
    assert "TODO" not in doc and "FIXME" not in doc


def test_the_document_names_the_commit_its_line_numbers_are_on(doc):
    assert re.search(r"`origin/staging` at (?:commit )?`[0-9a-f]{7}`", doc)
