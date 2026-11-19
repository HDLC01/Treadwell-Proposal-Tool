"""Where BD's page helpers file lands, for the Python-vs-JS parity tests (#805). Not a test file.

BD's shared.js (normalizeCompany, e164, fmtPhone) moves with the BD pages: #806, the first BD page,
brings it to frontend/bd/js/shared.js. Until then the frontend half of the parity tests in
test_bd_normalize.py, test_bd_phone.py, test_bd_props_normalize.py and test_bd_props_phone.py has
no file to run, so those tests carry `needs_bd_page_helpers` and skip, saying why. Once #806 puts
the file at SHARED_JS they run with no edit; if #806 puts it elsewhere it changes SHARED_JS here,
once.
"""
from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SHARED_JS = ROOT / "frontend" / "bd" / "js" / "shared.js"

needs_bd_page_helpers = pytest.mark.skipif(
    not SHARED_JS.exists(),
    reason="BD's page helpers (frontend/bd/js/shared.js) arrive with the first BD page, #806")
