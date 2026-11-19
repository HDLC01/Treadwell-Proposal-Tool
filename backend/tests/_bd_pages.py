"""Where BD's page helpers file lives, for the Python-vs-JS parity tests (#805). Not a test file.

BD's shared.js (normalizeCompany, e164, fmtPhone) moved in with the first BD page (#806) as
frontend/bd/js/bd-shared.js: renamed, because no BD asset shares a name with one of the tool's, and
the tool has its own /shared.js. The frontend half of the parity tests in test_bd_normalize.py,
test_bd_phone.py, test_bd_props_normalize.py and test_bd_props_phone.py runs it. They carry
`needs_bd_page_helpers`, which skips them, saying why, only if the file is missing.
"""
from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SHARED_JS = ROOT / "frontend" / "bd" / "js" / "bd-shared.js"
# The tool's people helpers (window.TWCrm), which bd-shared.js names every person through.
CRM_CORE_JS = ROOT / "frontend" / "js" / "crm-core.js"

needs_bd_page_helpers = pytest.mark.skipif(
    not SHARED_JS.exists(),
    reason="BD's page helpers (frontend/bd/js/bd-shared.js) are missing")
