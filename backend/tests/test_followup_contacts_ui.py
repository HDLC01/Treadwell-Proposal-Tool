"""Choosing which contacts get chased — on the send page, and afterwards in the drawer.

Hanz, 2026-08-12:

    "just like the 25% deposit creat a checkbox for each contact if they will be able to receive
     the automated follow ups or no"
    "Then on this project container on the follow ups we must have the ability to add or remove
     COntacts who receive the follow ups."

UN-TICKING IS NOT REMOVING THE CONTACT. They keep the proposal, the invoice, milestone mail and
every reply; only the cadence skips them. The two acts are one click apart in the same panel and
only one is harmless, so both the copy and the absence of any delete are asserted here. Revoking
access is a different decision and is not offered from this screen.

An opt-OUT list rather than an opt-in one, throughout. The default — chase everybody — is how this
has always worked, so it needs no entry anywhere: an omitted field, an older client, or a
recipient row written before the migration all mean "chased". Every fallback in this feature
points the same way, because the failure worth avoiding is silently stopping the chase on a live
bid rather than sending one email too many.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"


def _src(name: str) -> str:
    return (FRONTEND / "js" / name).read_text(encoding="utf-8")


def _code(name: str) -> str:
    return "\n".join(l for l in _src(name).splitlines() if not l.strip().startswith("//"))


def _braced(src: str, i: int, what: str) -> str:
    i = src.index("{", i)
    depth, j = 0, i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
        j += 1
    pytest.fail("unbalanced braces reading %s" % what)


def _block(name: str, fn: str) -> str:
    code = _code(name)
    m = re.search(r"\n\s{0,8}(?:async\s+)?function " + re.escape(fn) + r"\s*\(", code)
    assert m, "%s() is gone from %s" % (fn, name)
    return _braced(code, m.end(), "%s() in %s" % (fn, name))


def _py(fn: str) -> str:
    """A top-level def from backend/main.py, by indentation."""
    lines = (ROOT / "backend" / "main.py").read_text(encoding="utf-8").splitlines()
    start = next(i for i, l in enumerate(lines) if re.match(r"def %s\s*\(" % re.escape(fn), l))
    end = start + 1
    while end < len(lines) and (not lines[end].strip() or lines[end].startswith((" ", ")", "]"))):
        end += 1
    return "\n".join(lines[start:end])


# ── the send page ────────────────────────────────────────────────────────────
def test_every_recipient_row_gets_a_follow_ups_checkbox():
    """The intake row too: the person the lead came from is exactly who somebody might not want
    chased four times."""
    body = _block("done.js", "mountPortalRecipients")
    assert "tw-em-fu" in body, "no per-contact follow-ups control"
    i = body.index("tw-em-fu")
    j = body.index("if (r.fixed) {", i - 3000 if i > 3000 else 0)
    assert i < body.index("if (r.fixed) {", i), (
        "the checkbox is inside the fixed/extra branch, so one kind of row does not get it")


def test_the_default_is_being_chased():
    """It is how this has always worked. A box that defaulted off would silently stop the cadence
    on every proposal sent after the change."""
    body = _block("done.js", "mountPortalRecipients")
    assert "noFollowups.indexOf(r.email) < 0" in body, (
        "the checkbox is not ticked-by-default from an opt-out list")


def test_the_copy_says_what_un_ticking_actually_does():
    """Somebody reading "Follow-ups" alone could reasonably think it removes the contact."""
    body = _block("done.js", "mountPortalRecipients")
    i = body.index("tw-em-fu")
    near = body[i:i + 700]
    assert "still gets the proposal" in near and "chasing" in near


def test_removing_a_contact_drops_its_opt_out_too():
    """Otherwise removing an address and adding it back gives a ticked box that is a lie — the
    stale entry would still suppress its follow-ups."""
    body = _block("done.js", "mountPortalRecipients")
    i = body.index("extras.splice(k, 1)")
    near = body[i:i + 400]
    assert "noFollowups.indexOf(r.email)" in near and "splice(f, 1)" in near


def test_only_contacts_actually_being_sent_to_can_be_opted_out():
    """An address removed after being un-ticked, or an intake edited to something else, must not
    travel as an opt-out for a recipient that no longer exists — the portal validates the list and
    would refuse the publish."""
    body = _block("done.js", "mountPortalRecipients")
    assert "noFollowupsToSend" in body
    i = body.index("noFollowupsToSend")
    assert "filter" in body[i:i + 300] and "allEmails()" in body[i:i + 300]


def test_the_publish_request_carries_it():
    code = _code("done.js")
    i = code.index("/api/portal/publish")
    body = code[i:i + 700]
    assert "no_followups: portalRecip.noFollowupsToSend()" in body, (
        "the send does not tell the portal who to leave out")
    for kept in ("emails", "require_deposit", "assigned_estimator"):
        assert kept in body, "the publish payload lost %s" % kept


def test_the_proxy_refuses_a_malformed_address_rather_than_dropping_it():
    """Silently ignoring one means somebody un-ticked a box and the contact is chased anyway,
    which nobody notices until a customer complains."""
    src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    assert "no_followups: list[str]" in src, "the proxy model has no field for it"
    assert "_clean_portal_emails(payload.no_followups" in src, (
        "no_followups is forwarded without the validation `emails` gets")


def test_the_proxy_omits_the_field_when_nothing_is_opted_out():
    """An absent key means "the caller said nothing", which the portal treats as leave-the-flags-
    alone. Sending an empty list on every publish would be a write with no intent behind it."""
    src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    i = src.index("_clean_portal_emails(payload.no_followups")
    assert re.search(r"if no_fu:\s*\n\s*body\[\"no_followups\"\]", src[i:i + 300]), (
        "the field is set unconditionally")


# ── the drawer ───────────────────────────────────────────────────────────────
def test_the_followup_tab_lists_who_is_being_chased():
    panel = _block("portal.js", "followupContactsHtml")
    assert "data-fu-contact" in panel, "the contacts are not tickable"
    assert "r.followups" in panel, "the tick state does not come from the server"
    assert "fu-add-contact" in panel, "there is no way to add a contact"


def test_it_renders_for_a_single_contact_too():
    """Unlike the Recipients card on the Proposal tab, which needs two people to be worth showing.
    "Is this person being chased" is worth answering for one."""
    panel = _block("portal.js", "followupContactsHtml")
    assert "length > 1" not in panel, "the follow-up contacts list is gated on having two"
    assert "if (!list.length) return" in panel, "an empty list should render nothing at all"


def test_the_drawer_copy_also_says_un_ticking_is_not_removing():
    panel = _block("portal.js", "followupContactsHtml")
    assert "still get the proposal" in panel and "stop being chased" in panel


def test_the_drawer_offers_no_way_to_delete_a_contact():
    """Revoking somebody's access to a customer proposal is a different act from stopping the
    nagging, and it is not what Hanz asked for here."""
    panel = _block("portal.js", "followupContactsHtml")
    for danger in ("remove", "delete", "revoke"):
        assert danger not in panel.lower(), (
            "the follow-up contacts list offers a %s control" % danger)


def test_the_checkbox_listener_is_delegated():
    """renderDetail rebuilds this panel on every 12s poll and after every action. Per-checkbox
    listeners would be re-bound continually and leak with each repaint."""
    wire = _block("portal.js", "wireFollowup")
    assert 'querySelector(".fu-clist")' in wire
    assert 'addEventListener("change"' in wire
    assert "closest(\"[data-fu-contact]\")" in wire


def test_a_toggle_posts_the_contact_and_its_new_state():
    wire = _block("portal.js", "wireFollowup")
    i = wire.index('closest("[data-fu-contact]")')
    near = wire[i:i + 600]
    assert "/followup-recipient" in near
    assert "box.dataset.fuContact" in near and "enabled: box.checked" in near


def test_adding_a_contact_asks_for_an_add_and_a_link():
    """`add: true` is what distinguishes adding from toggling. Without it the portal answers
    not_a_recipient and the button appears to do nothing."""
    wire = _block("portal.js", "wireFollowup")
    i = wire.index("fu-add-contact-btn")
    near = wire[i:i + 900]
    assert "add: true" in near and "enabled: true" in near
    assert "/followup-recipient" in near


def test_a_typo_is_caught_before_a_round_trip():
    wire = _block("portal.js", "wireFollowup")
    i = wire.index("fu-add-contact-btn")
    near = wire[i:i + 900]
    assert "doesn't look like an email" in near
    assert "return" in near


def test_enter_adds_the_contact():
    """The field is one input and a button; typing an address and pressing Enter is what people
    do, and a form that ignores it reads as broken."""
    wire = _block("portal.js", "wireFollowup")
    assert 'addCIn.addEventListener("keydown"' in wire
    i = wire.index('addCIn.addEventListener("keydown"')
    assert "addC.click()" in wire[i:i + 300]


def test_the_tool_proxy_validates_and_stamps_who_did_it():
    src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    assert "api_portal_followup_recipient" in src
    i = src.index("def api_portal_followup_recipient")
    body = src[i:i + 1600]
    assert "_PORTAL_EMAIL_RE.match(email)" in body, "the address is forwarded unchecked"
    assert '"by": _user_email(request)' in body, (
        "the portal cannot record who changed it — the service token identifies the app, not a "
        "person")
    assert "_safe_id(proposal_id)" in body, "the id is interpolated into a URL unchecked"


def test_toggling_defaults_to_ON_but_never_creates_a_contact():
    """Two separate flags on purpose. If `add` were inferred from a missing recipient, a typo in
    the toggle path would add a stranger to a customer's proposal and email them the link."""
    src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    i = src.index("class FollowupRecipientIn")
    model = src[i:i + 900]
    assert "enabled: bool = True" in model
    assert "add: bool = False" in model


def test_the_controls_are_styled():
    page = (FRONTEND / "portal.html").read_text(encoding="utf-8")
    assert ".fu-clist" in page and ".fu-c " in page or ".fu-c {" in page
    assert ".tw-input" in page, "the add-contact field has no styling"
    done = (FRONTEND / "done.html").read_text(encoding="utf-8")
    assert ".tw-em-fu" in done, "the send-page checkbox has no styling"
