"""The private source material dropped in the repo root never reaches git.

Real contact lists arrive as a workbook (.xlsx), a CRM export (.csv), a printed sheet (.pdf) or a
process document (.docx). On 2026-11-16 a HubSpot export (.csv) sat untracked in the repo, one
`git add -A` away from GitHub, because .gitignore had no root CSV rule. These rules are anchored to
the root (leading /) so synthetic fixtures committed under backend/tests/ stay unaffected.
"""

import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
PRIVATE_ROOT_PATTERNS = ("/*.xlsx", "/*.csv", "/*.pdf", "/*.docx")


def gitignore_lines():
    return {ln.strip() for ln in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()}


@pytest.mark.parametrize("pattern", PRIVATE_ROOT_PATTERNS)
def test_gitignore_keeps_private_root_inputs_out(pattern):
    assert pattern in gitignore_lines(), f"{pattern} must stay in .gitignore (private source material)"


@pytest.mark.parametrize(
    "name",
    [
        "hubspot-crm-exports-my-companies.csv",
        "Some Workbook.xlsx",
        "Pipeline Summary - Google Sheets.pdf",
        "Process.docx",
    ],
)
def test_git_really_ignores_such_a_file_in_the_root(name):
    try:
        res = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", name], cwd=ROOT, capture_output=True, timeout=30
        )
    except FileNotFoundError:
        pytest.skip("git is not on PATH")
    assert res.returncode == 0, f"git would not ignore {name} in the repo root"


def test_no_private_type_file_is_tracked_in_the_root():
    try:
        res = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        pytest.skip("git is not on PATH")
    tracked = [
        p for p in res.stdout.splitlines() if "/" not in p and p.lower().endswith((".xlsx", ".csv", ".pdf", ".docx"))
    ]
    assert tracked == [], f"private-type files are tracked in the root: {tracked}"
