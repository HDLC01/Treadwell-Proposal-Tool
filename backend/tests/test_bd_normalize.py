"""normalize.py: the company duplicate key and trimmed names, the same answers as the frontend's
shared.js normalizeCompany() (the mock's duplicate checks)."""
from __future__ import annotations

import json
import pathlib
import tempfile

import pytest

from _node import last_json_line, run_node
from _bd_pages import SHARED_JS, needs_bd_page_helpers
from bd.normalize import clean_name, email_key, normalize_company


CASES = [
    (" Kestrelwood Gear Co. ", "kestrelwood gear"),
    ("Kestrelwood Gear Co", "kestrelwood gear"),
    ("KESTRELWOOD GEAR", "kestrelwood gear"),
    (" Northvane Plastics Inc.", "northvane plastics"),
    ("Northvane Plastics, Inc", "northvane plastics"),
    ("Northvane Plastics LLC", "northvane plastics"),
    ("Acme Co Inc", "acme"),                       # every trailing suffix goes
    ("Halvorsen & Pike Contractors", "halvorsen pike contractors"),
    ("Halvorsen and Pike Contractors", "halvorsen and pike contractors"),
    (" Prairiefold Foods ", "prairiefold foods"),     # no-break spaces
    ("Prairiefold Foods", "prairiefold foods"),           # narrow no-break space
    ("Prairiefold Foods", "prairiefold foods"),           # figure space
    ("Co", "co"),                                   # never drops the last word
    ("Inc Co", "inc"),
    ("The Company", "the"),
    ("St. Luke's Hospital", "st lukes hospital"),
    ("O'Brien-Smith Corp.", "obriensmith"),
    ("3M Company", "3m"),
    ("Café Olé", "caf ol"),                         # non-ASCII letters drop, as in JS
    ("", ""),
    (None, ""),
    ("   ", ""),
]


@pytest.mark.parametrize("raw,want", CASES)
def test_normalize_company(raw, want):
    assert normalize_company(raw) == want


@needs_bd_page_helpers
def test_python_and_the_frontend_agree():
    raws = [raw for raw, _ in CASES]
    script = """
const fs = require("fs"), vm = require("vm");
const ctx = {}; ctx.window = ctx; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
const raws = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
console.log(JSON.stringify(raws.map((r) => ctx.BD.normalizeCompany(r))));
"""
    with tempfile.TemporaryDirectory() as tmp:
        js = pathlib.Path(tmp) / "norm.js"
        data = pathlib.Path(tmp) / "raws.json"
        js.write_text(script, encoding="utf-8")
        data.write_text(json.dumps(raws), encoding="utf-8")
        proc = run_node(js, SHARED_JS, data)
    assert proc.returncode == 0, proc.stderr
    assert last_json_line(proc.stdout) == [normalize_company(r) for r in raws]


def test_clean_name_trims_and_collapses_but_keeps_the_words():
    assert clean_name("  Prairiefold   Foods ") == "Prairiefold Foods"
    assert clean_name(" Northvane Plastics Inc.") == "Northvane Plastics Inc."
    assert clean_name(None) == ""


def test_email_key():
    assert email_key(" Dana.Whitfield@Example.COM ") == "dana.whitfield@example.com"
    assert email_key("") is None
    assert email_key(None) is None
