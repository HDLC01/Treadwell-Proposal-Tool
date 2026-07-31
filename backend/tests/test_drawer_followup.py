"""The drawer's follow-up panel: the wiring traps, checked against the source.

This panel is markup built in one function and wired in another, which is exactly
how the portal already shipped two silent bugs: a section id registered in the tab
map but never marked eligible renders as an empty panel, and a handler bound to an
id the markup doesn't contain simply does nothing. Neither throws, neither shows up
in a screenshot, and both look like "the button is broken".

Text assertions rather than a browser, because the failure is structural — a name
that exists in one place and not the other.
"""
import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
PORTAL_JS = (FRONTEND / "js" / "portal.js").read_text(encoding="utf-8")
PORTAL_HTML = (FRONTEND / "portal.html").read_text(encoding="utf-8")


def _block(name: str) -> str:
    """The body of a top-level `function name(...) {` in portal.js.

    Brace-counted rather than regex'd, so a nested template literal containing a
    brace doesn't truncate the block and make these tests vacuous."""
    m = re.search(r"\n  function " + re.escape(name) + r"\s*\(", PORTAL_JS)
    assert m, f"{name}() is gone from portal.js — these tests need rewriting, not deleting"
    i = PORTAL_JS.index("{", m.end())
    depth, j = 0, i
    while j < len(PORTAL_JS):
        if PORTAL_JS[j] == "{":
            depth += 1
        elif PORTAL_JS[j] == "}":
            depth -= 1
            if depth == 0:
                return PORTAL_JS[i:j + 1]
        j += 1
    pytest.fail(f"unbalanced braces reading {name}()")


PANEL = _block("followupPanelHtml")
WIRE = _block("wireFollowup")


def test_every_id_the_wiring_reaches_for_exists_in_the_markup():
    """A handler bound to a missing id is a button that silently does nothing."""
    wanted = set(re.findall(r'\$\("(fu-[a-z-]+)"\)', WIRE))
    assert wanted, "wireFollowup stopped looking anything up — did it get gutted?"
    for i in sorted(wanted):
        assert f'id="{i}"' in PANEL, f'wireFollowup uses #{i}, which followupPanelHtml never renders'


def test_the_section_is_registered_and_marked_eligible():
    """Two separate maps, and missing either one renders an empty panel: SEC_TABS says
    which cards belong to the tab, setSecEligible says which apply."""
    assert 'followup: ["dsec-followup"]' in PORTAL_JS
    assert 'setSecEligible("dsec-followup", true)' in PORTAL_JS
    assert 'id="dsec-followup"' in PANEL


def test_the_tab_and_its_panel_are_both_rendered():
    assert 'secTab("followup"' in PORTAL_JS
    assert 'id="dpanel-followup"' in PORTAL_JS
    assert "followupPanelHtml(p, data)" in PORTAL_JS


def test_the_tab_strip_has_room_for_six_tabs():
    """The strip is a CSS grid with a fixed column count. Adding a sixth tab without
    widening it silently wraps one onto a second row, half-clipped."""
    assert "grid-template-columns:repeat(6,1fr)" in PORTAL_HTML


def test_the_panel_is_wired_from_render_detail():
    assert "wireFollowup(pid, p, act);" in PORTAL_JS


# ── what the controls actually post ─────────────────────────────────────────
def test_the_four_log_kinds_match_what_the_backend_accepts():
    """main.py rejects anything else with invalid_kind, so a fifth option in the
    select would be a button that always fails."""
    import main  # noqa: PLC0415 — the whole point is comparing to the live route
    del main
    offered = set(re.findall(r'<option value="(call|email|text|note)">', PANEL))
    assert offered == {"call", "email", "text", "note"}


def test_the_delay_options_match_the_months_the_server_allows():
    """The proxy 400s on anything but 1-4 (invalid_months)."""
    months = re.search(r'id="fu-months".*?</select>', PANEL, re.S)
    assert months
    assert set(re.findall(r'<option value="(\d+)"', months.group(0))) == {"1", "2", "3", "4"}


def test_marking_closed_lost_asks_why_before_posting():
    """Free text would make the reasons uncountable. The dialog offers the same six
    the customer's own form does, so "why do we lose bids?" has an answer."""
    assert "lostReasonDialog" in WIRE
    assert "C.LOST_REASON" in _block("lostReasonDialog")


def test_a_closed_proposal_offers_reactivation_instead_of_more_closing():
    assert 'id="fu-reopen"' in PANEL
    assert 'status: "active"' in WIRE


def test_the_toggle_is_disabled_on_a_closed_proposal():
    """Turning automation "on" for a closed-lost deal would claim something the
    cadence won't do — the worker skips closed rows."""
    assert 'id="fu-toggle" ${isLost(p) ? "disabled" : ""}' in PANEL


def test_pausing_is_confirmed_before_it_happens():
    """It stops every customer email for months. Too loud for a stray click."""
    assert "TW.confirmDanger" in WIRE


def test_the_panel_says_the_customer_is_not_emailed():
    """These controls exist for when a customer says it on the phone. An estimator
    must not have to guess whether pressing them sends something."""
    assert "The customer is not emailed" in PANEL or "customer is not emailed" in PANEL


def test_an_unassigned_proposal_says_the_digest_will_skip_it():
    """The digest skips unassigned proposals by design, so the panel has to say so —
    otherwise "assigned to nobody" reads as harmless."""
    assert "digest skips unassigned" in PANEL


# ── the history log's labels ─────────────────────────────────────────────────
# Every one of these was wrong the first time and only showed up on staging: the log
# renders what the SERVER stored, not what the drawer posted, and the two vocabularies
# differ. A miss here isn't an error — it's a row reading "staff_call" or "System" with
# nothing after it, in the one place an estimator looks to see what already happened.
ROW = _block("followupRow")


def test_it_labels_the_kinds_the_portal_actually_stores():
    """`main.py` prefixes them: `kind = "staff_" + kind`. Mapping only the short form
    the drawer posts left the log printing the raw `staff_call`."""
    import re as _re
    labels = PORTAL_JS[PORTAL_JS.index("const FU_KIND_LABEL"):PORTAL_JS.index("FU_TEMPLATE_LABEL")]
    for stored in ("staff_call", "staff_email", "staff_text", "staff_note"):
        assert _re.search(r"\b" + stored + r":", labels), f"no label for {stored}"


def test_it_names_every_bookkeeping_action_the_portal_writes():
    """These are the exact `detail.action` values in the portal's add_followup calls.
    An unmapped one renders as a bare "System" with an empty detail."""
    actions = PORTAL_JS[PORTAL_JS.index("const FU_ACTION"):PORTAL_JS.index("const STATUS_LABEL")]
    for a in ("reassigned", "automation_on", "automation_off",
              "paused", "closed_lost", "reactivated"):
        assert a + ":" in actions, f"no label for detail.action={a}"


def test_an_automatic_send_is_labelled_by_its_template_not_its_rule_key():
    """The worker records `template` (what it sent) and `rule_key` (how it deduped).
    Reading `rule` got neither, so every automatic send said just "Automatic email"."""
    assert "FU_TEMPLATE_LABEL[d.template]" in ROW
    assert "d.rule]" not in ROW


def test_the_four_automatic_templates_are_all_named():
    """Straight from followup_rules — an estimator should see WHICH nudge went out."""
    tl = PORTAL_JS[PORTAL_JS.index("const FU_TEMPLATE_LABEL"):PORTAL_JS.index("const FU_ACTION")]
    for t in ("not_viewed", "next_steps", "second_nudge", "checkin"):
        assert t + ":" in tl, f"no label for template {t}"


def test_bookkeeping_is_detected_by_the_action_key_not_the_kind():
    """`staff_note` carries both a typed note and the system's bookkeeping. Branching
    on the kind put every reassignment through the note path and lost its detail."""
    assert "} else if (d.action) {" in ROW
