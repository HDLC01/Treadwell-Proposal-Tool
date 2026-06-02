"""Treadwell file/folder naming convention (verified against the team's
real Dropbox files). These are pure string builders — no network."""
import dropbox_client as dc


# ── date prefixes ─────────────────────────────────────────────────────
def test_deadline_prefix_from_iso():
    assert dc._deadline_prefix("2026-09-15") == "26.09.15"


def test_deadline_prefix_accepts_us_format():
    assert dc._deadline_prefix("9/15/2026") == "26.09.15"


def test_deadline_prefix_falls_back_to_today_when_blank():
    # unparseable/empty -> some YY.MM.DD string (today); just assert shape
    out = dc._deadline_prefix("")
    assert len(out.split(".")) == 3


def test_proposal_date_mmdd():
    assert dc._proposal_date("2026-06-02") == "06.02"


# ── output filenames ──────────────────────────────────────────────────
def test_output_filenames_epoxy_direct():
    est, prop = dc._output_filenames("Acme Plant", "epoxy", "Direct", "2026-06-02")
    assert est == "$estimate sheet - Acme Plant.xlsx"
    assert prop == "06.02 TREADWELL EPOXY PROPOSAL - New Direct.docx"


def test_output_filenames_polish_gc():
    est, prop = dc._output_filenames("Olathe CTE", "polish", "GC", "2026-06-02")
    assert est == "$estimate sheet - Olathe CTE.xlsx"
    assert prop == "06.02 TREADWELL POLISH PROPOSAL - GC.docx"


# ── project folder path ───────────────────────────────────────────────
def test_folder_path_has_deadline_prefix_name_and_marker():
    path = dc._build_folder_path("Acme Plant", deadline="2026-09-15")
    leaf = path.rstrip("/").split("/")[-1]
    assert leaf.startswith("26.09.15 ")
    assert "Acme Plant" in leaf
    assert leaf.endswith("!")          # active-job status marker


def test_folder_path_marks_polish_combo():
    polish = dc._build_folder_path("X", deadline="2026-09-15", work_type="polish")
    combo = dc._build_folder_path("X", deadline="2026-09-15", work_type="combo")
    epoxy = dc._build_folder_path("X", deadline="2026-09-15", work_type="epoxy")
    assert "(Polish)" in polish
    assert "(Combo)" in combo
    assert "(Polish)" not in epoxy and "(Combo)" not in epoxy  # epoxy = default, unmarked


def test_sanitize_strips_illegal_chars():
    assert "/" not in dc._sanitize_folder_name("A/B:C*?")
