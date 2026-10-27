"""THE PAGE ASKS EXACTLY WHEN THE SERVER CAN ANSWER: js/bid-model.js distanceKey and distance.can_place, over one table.

The page decides whether to ask /api/distance from B.distanceKey ("" means "do not ask, and say what is missing"); the server decides whether
an address is too thin from distance.can_place. Since 2026-10-22 (Hanz: a city, a state and a county with no street should be measured) the rule
is: a street that can be placed (a city + state, or a zip), OR a zip, OR a city + state, OR a county with a state (its own ", KS" or the state
box). If the two drift, the page either asks for what the server calls incomplete or never asks for what it could measure, which is the bug
this rule was written for. Run through the REAL bid-model.js with node.
"""
from __future__ import annotations

import json
import subprocess

import pytest

import distance
from _golden_support import FRONTEND
from _node import require_node

CASES = [
    # address, city, state, zip, county
    ("", "", "", "", ""),
    ("", "Wichita", "KS", "", ""),
    ("", "Wichita", "KS", "", "Sedgwick County, KS"),
    ("", "Wichita", "", "", ""),
    ("", "", "KS", "", ""),
    ("", "", "", "67202", ""),
    ("", "", "", "", "Sedgwick County, KS"),
    ("", "", "", "", "Sedgwick County"),
    ("", "", "KS", "", "Sedgwick County"),
    ("", "", "", "", "sedgwick county,ks"),
    ("", "", "", "", "Overland Park, KS"),
    ("100 Main St", "", "", "", ""),
    ("100 Main St", "Wichita", "", "", ""),
    ("100 Main St", "Wichita", "KS", "", ""),
    ("100 Main St", "", "", "67202", ""),
    ("100 Main St", "", "", "", "Sedgwick County, KS"),
    ("100 Main St", "", "KS", "", "Sedgwick"),
    ("   ", "  ", " ", " ", "  "),
    ("", "  Wichita ", " ks ", "", ""),
    ("", "", "", "", " , KS"),
]

JS = r"""
const B = require(process.argv[1]);
const cases = JSON.parse(process.argv[2]);
process.stdout.write(JSON.stringify(cases.map((c) => B.distanceKey(c[0], c[1], c[2], c[3], c[4]))));
"""


@pytest.fixture(scope="module")
def js_keys():
    node = require_node()
    proc = subprocess.run([node, "-e", JS, str(FRONTEND / "js" / "bid-model.js"), json.dumps(CASES)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, proc.stderr[-1500:]
    return json.loads(proc.stdout)


@pytest.mark.parametrize("i", range(len(CASES)))
def test_the_page_and_the_server_agree_on_what_is_enough_to_ask(js_keys, i):
    case = CASES[i]
    assert bool(js_keys[i]) == distance.can_place(*case), (case, js_keys[i])


def test_the_table_holds_both_answers():
    """A parity table of one answer proves nothing (the vacuous-invariant rule)."""
    answers = {distance.can_place(*c) for c in CASES}
    assert answers == {True, False}


def test_a_street_key_is_the_four_parts_it_always_was(js_keys):
    """Every street figure saved before 2026-10-22 carries "street|city|st|zip"; the county is no part of a street's key, so those still match."""
    i = CASES.index(("100 Main St", "Wichita", "KS", "", ""))
    assert js_keys[i] == "100 main st|wichita|ks|"
    j = CASES.index(("", "Wichita", "KS", "", "Sedgwick County, KS"))
    assert js_keys[j] == "|wichita|ks||sedgwick county, ks"
