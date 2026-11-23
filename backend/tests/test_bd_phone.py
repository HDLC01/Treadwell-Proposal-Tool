"""phone.py: US numbers to E.164 and the last-10 match key, the same answers as the frontend's
shared.js e164() and the database's bd_e164() (which derives contacts.phone_e164)."""
from __future__ import annotations

import json
import pathlib
import tempfile

import pytest

from bd import phone
from _node import last_json_line, run_node
from _bd_pages import SHARED_JS, needs_bd_page_helpers


CASES = [
    ("816.555.0110", "+18165550110"),
    ("816-555-0110", "+18165550110"),
    ("(913) 555-0117", "+19135550117"),
    ("913 555 0117", "+19135550117"),
    ("+1 816 555 0110", "+18165550110"),
    ("+1 (816) 555-0110", "+18165550110"),
    ("1-816-555-0110", "+18165550110"),
    ("18165550110", "+18165550110"),
    ("8165550110", "+18165550110"),
    ("816.555.0110 ext. 4", None),         # 11 digits not starting with 1
    ("555-0110", None),                    # 7 digits
    ("2-816-555-0110", None),              # 11 digits starting with 2
    ("+44 20 7946 0958", None),
    ("", None),
    (None, None),
    ("call the office", None),
    ("٨١٦٥٥٥٠١١٠", None),                  # Arabic-Indic digits are not phone digits
]


@pytest.mark.parametrize("raw,want", CASES)
def test_to_e164(raw, want):
    assert phone.to_e164(raw) == want


def test_last10_is_the_match_key():
    assert phone.last10("+1 (816) 555-0110") == "8165550110"
    assert phone.last10("816.555.0110") == "8165550110"
    assert phone.last10("+18165550110") == "8165550110"
    assert phone.last10("555-0110") is None
    assert phone.last10(None) is None


def test_display_matches_fmtPhone():
    assert phone.display("816.555.0110") == "816-555-0110"
    assert phone.display("+1 913 555 0117") == "913-555-0117"
    assert phone.display("555-0110") == "555-0110"
    assert phone.display(None) == ""


@needs_bd_page_helpers
def test_python_and_the_frontend_agree():
    raws = [raw for raw, _ in CASES]
    script = """
const fs = require("fs"), vm = require("vm");
const ctx = {}; ctx.window = ctx; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
const raws = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
console.log(JSON.stringify(raws.map((r) => ctx.BD.e164(r))));
"""
    with tempfile.TemporaryDirectory() as tmp:
        js = pathlib.Path(tmp) / "e164.js"
        data = pathlib.Path(tmp) / "raws.json"
        js.write_text(script, encoding="utf-8")
        data.write_text(json.dumps(raws), encoding="utf-8")
        proc = run_node(js, SHARED_JS, data)
    assert proc.returncode == 0, proc.stderr
    assert last_json_line(proc.stdout) == [phone.to_e164(r) for r in raws]


def test_the_database_derives_the_same_e164(bd_db):
    for raw, want in CASES:
        got = bd_db.execute("select bd_e164(%s) as e", (raw,)).fetchone()["e"]
        assert got == want, (raw, got)
