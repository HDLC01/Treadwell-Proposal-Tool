"""A v2 Epoxy bid's proposal names the cove height its cove system has (2026-10-16).

Re-entering a real job on staging, the proposal said "562 LF of 6" epoxy cove base" for a 4" cove: the proposal reads
`cove_height`, which only the Proposal step's box fills, and falls back to 6. v2's save now writes `cove_height_v2` from the
base's cove system (bid-model coveHeightOf), and every reader falls back to it before 6. A height typed on the Proposal
step still wins.
"""
from __future__ import annotations

import main


def _lf_clause(values):
    systems = main._build_epoxy_systems({}, dict({"system_name": "Flake", "epoxy_sf": 5482, "cove_lf": 562}, **values), None)
    return systems[0]["lf_clause"]


def test_the_document_uses_the_v2_cove_height_when_nobody_typed_one():
    assert '4" epoxy cove base' in _lf_clause({"cove_height_v2": "4"})


def test_a_height_typed_on_the_proposal_step_wins():
    assert '6" epoxy cove base' in _lf_clause({"cove_height": "6", "cove_height_v2": "4"})


def test_no_height_anywhere_is_still_six():
    assert '6" epoxy cove base' in _lf_clause({})

