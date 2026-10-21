"""The browser walk of the v2 sheet tabs on staging (2026-10-20) found what the unit tests had not:

  * the base tab's red edge read as a second selected tab, so the open tab alone wears the edge and the base says "Base";
  * "+ Add sheet" vanished while its own list was open;
  * an option's Review line named the sheet by its key ("Copy1 is priced on its own") rather than its tab's name;
  * the Proposal and Files pages' step pills sent a v2 draft to the spreadsheet pages, which bounce it on and log an error;
  * each Review card sized its own columns, so Quantity and Unit wandered from card to card.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from _golden_support import FRONTEND
from _node import last_json_line, require_node, run_node

HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "tabs-walk-fixes-harness.js"
PAGE = (FRONTEND / "polish-estimate.html").read_text(encoding="utf-8")
JS = (FRONTEND / "js" / "polish-estimate.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ran():
    require_node()
    proc = run_node(HARNESS, FRONTEND)
    assert proc.returncode == 0, proc.stderr
    return last_json_line(proc.stdout)


def test_the_add_button_stays_while_its_list_is_open_and_closes_it(ran):
    assert 'data-sh-act="add-menu"' in ran["addShut"] and 'aria-expanded="false"' in ran["addShut"]
    assert ran["addOpen"], "the + Add sheet button vanished while its list was open"
    assert 'data-sh-act="add-close"' in ran["addOpen"] and 'aria-expanded="true"' in ran["addOpen"]


def test_the_base_says_base_in_words_and_only_the_open_tab_wears_the_red_edge(ran):
    assert ran["other"] not in ran["base"], "the fixture has no tab other than the base"
    assert '<span class="sh-basetag">Base</span>' in ran["baseTab"]
    assert "sh-basetag" not in ran["otherTab"]
    css = re.sub(r"\s+", " ", PAGE)
    assert re.search(r"\.sheets \.sh-tab\.open\{[^}]*box-shadow:inset 0 3px 0 var\(--red\)", css)
    assert not re.search(r"\.sheets \.sh-tab\.base\{[^}]*box-shadow", css), "the base tab still wears a red edge"


def test_an_options_review_line_names_the_sheet_by_its_tab_name():
    assert "esc(onShow.label || onShow.tab)" in JS


@pytest.mark.parametrize("page", ["proposal-review.js", "done.js"])
def test_the_step_pills_of_a_v2_draft_go_to_the_v2_pages(page):
    src = (FRONTEND / "js" / page).read_text(encoding="utf-8")
    assert 'TW.isV2Draft(state)' in src and 'TW.withDraft("/polish-estimate.html")' in src
    assert 'TW.withDraft("/polish-intake.html")' in src


def test_every_review_card_shares_one_set_of_columns():
    css = re.sub(r"\s+", " ", PAGE)
    assert ".rev-t,.mk{table-layout:fixed}" in css
    # Quantity is a share of the table; Unit, Rate and Total are pixels, each wide enough for what the markup card puts in it (the 2026-10-20 fifth audit: a
    # share of a narrow table cut the boxes off at about 916px, see test_v2_review_table_fits.py). Either way ONE rule gives a column to BOTH tables.
    for n in (2, 3, 4, 5):
        assert re.search(r"\.rev-t th:nth-child\(%d\),\.mk th:nth-child\(%d\)\{width:\d+(?:%%|px)\}" % (n, n), css), n
