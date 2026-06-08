"""Backend value-alias safety net (_ensure_value_aliases).

Generation must fill the proposal's project-name token even if a caller sent
only one side of the project_name/job_name alias pair — a literal {{job_name}}
in a customer-facing proposal is unacceptable. These pin that behavior.
"""
import main


def test_job_name_backfilled_from_project_name():
    v = {"project_name": "Acme Mfg"}
    main._ensure_value_aliases(v)
    assert v["job_name"] == "Acme Mfg"


def test_project_name_backfilled_from_job_name():
    v = {"job_name": "Acme Mfg"}
    main._ensure_value_aliases(v)
    assert v["project_name"] == "Acme Mfg"


def test_existing_value_not_overwritten():
    v = {"job_name": "Real Name", "project_name": "Other Name"}
    main._ensure_value_aliases(v)
    assert v["job_name"] == "Real Name"
    assert v["project_name"] == "Other Name"


def test_blank_target_is_backfilled():
    v = {"job_name": "   ", "project_name": "Acme"}
    main._ensure_value_aliases(v)
    assert v["job_name"] == "Acme"


def test_no_names_leaves_both_absent():
    v = {}
    main._ensure_value_aliases(v)
    assert "job_name" not in v and "project_name" not in v
