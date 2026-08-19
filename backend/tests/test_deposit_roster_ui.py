"""The deposit half of the notification roster, visible and editable on screen.

WHAT WAS WRONG. `portal_notify_recipients` rows carry a `kind`: `general` or `deposit`. A general
alert resolves to the enabled general rows; a deposit alert resolves to those PLUS the enabled
deposit rows, deduped — additive, so adding the first deposit person cannot cut the team off the
three deposit moments. kylene@ went live as an enabled deposit row on 2026-08-19.

The Notification Sending page filtered the roster to `kind === "general"`. So her row existed,
worked, and appeared nowhere: nobody could see who was on it, nobody could turn her off, and the
next person like her needed SQL. Invisible configuration is configuration that rots — somebody
eventually "fixes" a mystery email by editing the wrong list.

WHAT THIS PINS. A second roster group, built from the SAME `rosterCardHtml`/`paintGroup` code as
the team group, so the deposit list is the same control (same chip, same green = receives / grey =
off, same Add field, same ×) rather than a second, subtly different one. And then the four things
a kind can get wrong:

  * the split — a deposit row in the deposit group and NOT in the team group, and vice versa;
  * the add — the field it was typed into decides the kind, because the proxy DEFAULTS a missing
    kind to `general` and would report success while creating the wrong sort of row;
  * the toggle and the remove — kind-agnostic endpoints keyed by ROW id, so each control has to
    target its own row and no other;
  * the same address on BOTH lists — legal (the row key is kind + email) and meaning "everything,
    deposits included". It must read as a choice, not a duplicate, and removing one row must
    visibly leave the other.

THE PER-PROJECT STRIP KEEPS PAINTING FROM THE TEAM LIST ONLY, and the card says so on screen. A
per-project chip is one on/off governing everything that project emails, and an override is stored
as (proposal_id, email, mode) with no kind at all — so turning a deposit-only person green there
would union their address into that project's general recipients too, quietly promoting somebody
who was added for three deposit emails into approvals, replies and questions. Rejected
alternative: show them with the chip disabled, which invites "why can't I click this" where a
sentence answers it.

THE PROXY WAS CHECKED AND ALREADY FORWARDS `kind` (main.py `api_portal_notify_add`, pinned by
test_portal_publish.py::test_notify_add_forwards_cleaned). No backend change was needed.

EVERYTHING BELOW IS EXECUTED. `js/deposit-roster-harness.js` lifts render(), load(), paintGroup(),
addEmail(), toggle(), removeOne() and peopleFor() out of notifications.js, runs them against the
real crm-core.js and a store that answers like the API, and reports what actually rendered and
what was actually sent. The house rule, bought on prod 2026-08-12: a source-text assertion cannot
see an unbound identifier.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "deposit-roster-harness.js"
PAGE_JS = FRONTEND / "js" / "notifications.js"
PAGE_HTML = FRONTEND / "notifications.html"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

KYLENE = "kylene@wetreadwell.com"
HANZ = "hanz@wetreadwell.com"
KYLE = "kyle.loseke@wetreadwell.com"


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _group(ran, kind):
    return next(g for g in ran["groups"] if g["kind"] == kind)


# ── both groups exist and both paint ─────────────────────────────────────────
@needs_node
def test_the_page_renders_a_deposit_group_as_well_as_the_team(ran):
    """The whole ask. Off render()'s real output, and off the ids it really wrote — the harness
    supplies its DOM by hand, so an id that never made it into the markup would still resolve
    there and every control on the card would be silently inert in a browser.

    Mutation this kills: dropping the deposit entry from GROUPS, or slicing it off in render()."""
    kinds = [g["kind"] for g in ran["groups"]]
    assert kinds == ["general", "deposit"], (
        "the roster groups are %r — the deposit group is gone or reordered" % kinds)
    ids = ran["render"]["ids"]
    for g in ran["groups"]:
        for field in ("chips", "input", "btn", "alert"):
            assert g[field] in ids, (
                "the %s group's %s node (%s) is looked up but never rendered, so its control "
                "resolves to null and does nothing" % (g["kind"], field, g[field]))
    assert len(set(ids)) == len(ids), "two nodes share an id: %r" % ids
    labels = ran["render"]["labels"]
    assert _group(ran, "general")["lbl"] in labels
    assert _group(ran, "deposit")["lbl"] in labels
    assert ran["render"]["cards"] == 3, (
        "expected the team card, the deposit card and the per-project card, got %d"
        % ran["render"]["cards"])


@needs_node
def test_the_deposit_card_says_it_is_an_addition_and_what_it_covers(ran):
    """The point of the card is that the rule is no longer hidden, so the wording is the feature.
    Two claims a reader needs: this list ADDS to the team above (it does not replace it), and it
    covers deposits ONLY."""
    dep = _group(ran, "deposit")
    assert "in addition to the team above" in dep["lbl"].lower()
    intro = dep["intro"].lower()
    assert "adds to the team above" in intro and "rather than replacing" in intro, (
        "the deposit card does not say it is additive, which is the one thing a reader cannot "
        "guess and the thing the server actually does")
    for moment in ("invoice", "payment details", "marked received"):
        assert moment in intro, "the deposit card does not name the %r moment" % moment
    assert "nothing else" in intro, "the card does not say these people get deposits ONLY"
    html = ran["render"]["html"]
    assert dep["intro"] in html and _group(ran, "general")["intro"] in html, (
        "the group copy is not on the page")


@needs_node
def test_the_team_card_says_it_gets_deposits_too(ran):
    """Read from the team card alone, "deposit alerts" below could easily mean the team stopped
    getting them. It is the same additive rule, said from the other side."""
    assert "deposits included" in _group(ran, "general")["intro"].lower()


# ── the split, which is the bug ──────────────────────────────────────────────
@needs_node
def test_a_deposit_row_paints_in_the_deposit_group_and_not_the_team_group(ran):
    """kylene@'s real row. Both directions, because either filter can be the broken one: a
    general row must not appear under deposits either.

    Mutations this kills: filtering both groups on the same kind, inverting one comparison, or
    dropping the filter so every row appears twice."""
    general = [c["email"] for c in ran["mixed"]["general"]]
    deposit = [c["email"] for c in ran["mixed"]["deposit"]]
    assert general == [HANZ, KYLE], "the team group renders %r" % general
    assert deposit == [KYLENE], "the deposit group renders %r" % deposit
    assert KYLENE not in general, "the deposit row leaked into the team list"
    assert not set(deposit) & {HANZ, KYLE}, "a team row leaked into the deposit list"


@needs_node
def test_one_fetch_feeds_both_groups(ran):
    """One GET returns every row and the page splits it. Two fetches would be two chances to
    disagree about the roster, and the endpoint has no kind filter to ask for anyway."""
    assert ran["mixed"]["getCalls"] == 1


@needs_node
def test_a_chip_carries_the_enabled_state_it_was_given(ran):
    """Green = receives, grey = off, in both groups. kyle@ is the off row."""
    by = {c["email"]: c["on"] for c in ran["mixed"]["general"] + ran["mixed"]["deposit"]}
    assert by == {HANZ: True, KYLE: False, KYLENE: True}


@needs_node
def test_a_row_whose_kind_we_do_not_recognise_shows_up_rather_than_vanishing(ran):
    """A missing or future `kind` falls to the team card, which is the same call the portal's own
    resolver makes when it buckets rows. The alternative is the bug this file exists for: a row
    that works, emails people, and appears on no card at all."""
    assert ran["unknownKind"]["general"] == ["nokind@wetreadwell.com", "future@wetreadwell.com"], (
        "a row with no kind, or an unrecognised one, is being filtered into invisibility again")
    assert ran["unknownKind"]["deposit"] == [KYLENE]


# ── adding: the field decides the kind ───────────────────────────────────────
@needs_node
def test_adding_from_the_deposit_field_sends_kind_deposit(ran):
    """THE assertion of this file. The proxy defaults a missing kind to "general" and 400s only an
    UNKNOWN one, so a dropped or hardcoded field here creates a general row, reports "Added", and
    signs somebody up for every notification the company sends. Only the request body says which.

    Mutations this kill: `kind: "general"` hardcoded, `kind: g.other`, or the field omitted."""
    post = ran["addDeposit"]["post"]
    assert post["path"] == "/api/portal/notify-recipients" and post["method"] == "POST"
    assert post["body"] == {"email": "newdep@wetreadwell.com", "kind": "deposit"}, (
        "the deposit field sent %r" % post["body"])


@needs_node
def test_adding_from_the_team_field_still_sends_kind_general(ran):
    post = ran["addGeneral"]["post"]
    assert post["body"] == {"email": "newteam@wetreadwell.com", "kind": "general"}, (
        "the team field sent %r" % post["body"])


@needs_node
def test_enter_in_the_deposit_field_is_the_same_path_as_its_add_button(ran):
    """Two fields, two keydown handlers, and a shared closure is exactly where the wrong group
    gets captured — the classic loop-variable mistake, which would send `general` from the
    deposit field's Enter key."""
    assert ran["addByEnter"]["body"] == {"email": "enter@wetreadwell.com", "kind": "deposit"}


@needs_node
def test_the_new_person_appears_in_the_group_they_were_added_to(ran):
    """Not just the request: the page reloads and repaints, and the reader has to see them land on
    the right card, off (grey) until somebody turns them green."""
    dep = [c["email"] for c in ran["addDeposit"]["deposit"]]
    assert dep == [KYLENE, "newdep@wetreadwell.com"]
    assert ran["addDeposit"]["deposit"][-1]["on"] is False, (
        "a freshly added person is green, so they start receiving before anyone chose that")
    assert "newdep@wetreadwell.com" not in [c["email"] for c in ran["addDeposit"]["general"]]
    gen = [c["email"] for c in ran["addGeneral"]["general"]]
    assert gen == [HANZ, KYLE, "newteam@wetreadwell.com"]
    assert "newteam@wetreadwell.com" not in [c["email"] for c in ran["addGeneral"]["deposit"]]
    assert ran["addDeposit"]["inputCleared"], "the field keeps the address it just submitted"


@needs_node
def test_each_card_reports_on_itself(ran):
    """Two cards, two alert regions. A shared one puts "Could not add" under the team list when
    the deposit field was the one that failed, which sends the reader to the wrong control."""
    assert "deposit alerts" in ran["addDeposit"]["alert"]
    assert ran["addDeposit"]["otherAlert"] == "", "the team card reported the deposit add"
    assert "the team" in ran["addGeneral"]["alert"]
    assert ran["addEmpty"] == {"posts": 0, "deposit": "Enter an email address.", "general": ""}, (
        "an empty deposit field either posted anyway or complained on the wrong card")
    assert ran["addFails"]["deposit"].startswith("Could not add:")
    assert ran["addFails"]["general"] == ""
    assert ran["addFails"]["btnLabel"] == "Add" and ran["addFails"]["btnDisabled"] is False, (
        "a failed add leaves the button stuck on 'Adding…'")


# ── toggling: same endpoint, own row ─────────────────────────────────────────
@needs_node
def test_a_toggle_on_a_deposit_row_hits_the_same_endpoint_as_a_team_row(ran):
    """The enable/disable route is keyed by ROW id and is kind-agnostic, so the deposit chip needs
    no second endpoint and must not invent one."""
    gen, dep = ran["generalToggle"], ran["depositToggle"]
    assert gen["method"] == dep["method"] == "PATCH"
    assert gen["path"] == "/api/portal/notify-recipients/2"
    assert dep["path"] == "/api/portal/notify-recipients/3"
    assert gen["path"].rsplit("/", 1)[0] == dep["path"].rsplit("/", 1)[0], (
        "the deposit toggle goes somewhere else entirely")
    assert gen["body"] == {"enabled": True}       # kyle@ was off
    assert dep["body"] == {"enabled": False}      # kylene@ was on


@needs_node
def test_each_toggle_targets_its_own_row_and_leaves_the_other_alone(ran):
    """Ids come out of freshly generated HTML and the handlers are re-wired on every paint, so a
    chip carrying its neighbour's `data-id` is a silent cross-wire: the click lands, the request
    succeeds, and the wrong person's state moves.

    Mutation this kills: painting one group with the other's rows, or reusing an index."""
    patches = ran["afterToggles"]["patches"]
    assert [p["path"] for p in patches] == ["/api/portal/notify-recipients/2",
                                            "/api/portal/notify-recipients/3"]
    after = {c["email"]: c["on"] for c in
             ran["afterToggles"]["general"] + ran["afterToggles"]["deposit"]}
    assert after == {HANZ: True, KYLE: True, KYLENE: False}, (
        "a toggle moved somebody it was not aimed at: %r" % after)


@needs_node
def test_a_roster_change_repaints_the_per_project_card(ran):
    """The per-project chips show an EFFECTIVE state derived from the team base, so a base that
    moved without a repaint leaves every row below showing yesterday's answer."""
    assert ran["afterToggles"]["projectRenders"] == 2, (
        "two roster toggles produced %d per-project repaints"
        % ran["afterToggles"]["projectRenders"])


# ── the same address on both lists ───────────────────────────────────────────
@needs_node
def test_the_same_address_on_both_lists_renders_once_per_group(ran):
    """Legal, and it means "everything, deposits included" — the row key is kind + email. Not a
    duplicate to be de-duplicated and not a conflict to be warned about."""
    assert [c["email"] for c in ran["both"]["general"]] == [HANZ, KYLE]
    assert [c["email"] for c in ran["both"]["deposit"]] == [HANZ]
    ids = {c["id"] for c in ran["both"]["general"] + ran["both"]["deposit"]}
    assert ids == {"1", "2", "9"}, "the two rows for the same person share an id: %r" % ids


@needs_node
def test_being_on_both_lists_is_labelled_as_a_choice(ran):
    """An unexplained twin reads as a bug, and the fix a reader reaches for is deleting one of
    them. Each chip says where the person's other row is, so the pair is legible from either
    card."""
    hanz_gen = next(c for c in ran["both"]["general"] if c["email"] == HANZ)
    hanz_dep = next(c for c in ran["both"]["deposit"] if c["email"] == HANZ)
    assert hanz_gen["also"] == "also on deposits"
    assert hanz_dep["also"] == "also on the team"
    kyle = next(c for c in ran["both"]["general"] if c["email"] == KYLE)
    assert kyle["also"] is None, (
        "somebody on one list only is labelled as being on both, which is worse than no label")
    assert ran["removeOnlyRow"]["general"][0]["also"] is None


@needs_node
def test_removing_one_row_removes_only_that_row(ran):
    """The reader's actual worry: "did I just take them off everything?" So the DELETE carries one
    id, and the reload shows the other row still standing.

    Mutation this kills: removing by EMAIL, or looking the id up in the wrong group's list."""
    d = ran["bothRemoveDeposit"]
    assert [c["path"] for c in d["deletes"]] == ["/api/portal/notify-recipients/9"]
    assert [c["email"] for c in d["general"]] == [HANZ, KYLE], (
        "removing the deposit row took the team row with it")
    assert d["deposit"] == []
    g = ran["bothRemoveGeneral"]
    assert [c["path"] for c in g["deletes"]] == ["/api/portal/notify-recipients/1"]
    assert [c["email"] for c in g["deposit"]] == [HANZ], (
        "removing the team row took the deposit row with it")
    assert [c["email"] for c in g["general"]] == [KYLE]


@needs_node
def test_the_remove_dialog_says_which_list_and_what_survives(ran):
    """A confirm that just says "Remove?" cannot tell the two rows apart, and the person clicking
    it is trying to make exactly that distinction."""
    d = ran["bothRemoveDeposit"]["dialog"]
    assert d["title"] == "Remove from deposit alerts?"
    assert "deposit alerts" in d["before"] and d["name"] == HANZ
    assert "stay on the team list above" in d["after"], (
        "the dialog does not say the team row survives: %r" % d["after"])
    g = ran["bothRemoveGeneral"]["dialog"]
    assert g["title"] == "Remove from notifications?"
    assert "deposit row stays" in g["after"], (
        "the dialog does not say the deposit row survives: %r" % g["after"])
    # Somebody on ONE list gets the plain question — a reassurance about a row that does not
    # exist is worse than none.
    assert ran["removeOnlyRow"]["dialog"]["after"] == "?"
    assert ran["removeOnlyRow"]["dialog"]["title"] == "Remove from deposit alerts?"


@needs_node
def test_declining_the_dialog_removes_nothing(ran):
    assert ran["declined"]["deletes"] == 0
    assert [c["email"] for c in ran["declined"]["deposit"]] == [HANZ]


@needs_node
def test_clicking_the_remove_x_does_not_also_toggle_the_chip(ran):
    """The × sits INSIDE the chip, so its click bubbles. Two guards keep them apart — the ×
    calls stopPropagation() and the chip's handler ignores a click whose target carries the `x`
    class — and with either one missing, removing somebody flips them on the way out."""
    assert ran["bothRemoveDeposit"]["patches"] == 0, (
        "removing a deposit person also PATCHed their enabled state")


# ── the empty states ─────────────────────────────────────────────────────────
@needs_node
def test_an_empty_deposit_list_reads_as_a_deliberate_state(ran):
    """"No one on the list yet" would say nobody is told about deposits, which is false and
    frightening — the team above is told. This is the difference between "nobody EXTRA" and "a
    panel that failed to load"."""
    copy = ran["emptyDeposit"]["deposit"]
    assert "Nobody extra is told about deposits" in copy, (
        "the empty deposit list reads as broken or as nobody being told: %r" % copy)
    assert "the team above still gets them" in copy, (
        "the empty state does not say who IS told, which is the whole reassurance")
    assert "Add someone below." in copy, "an admin is not told how to add anyone"
    assert ran["emptyDeposit"]["chips"] == 0
    # The team card is untouched by the deposit list being empty.
    assert [c["email"] for c in ran["emptyDeposit"]["general"]] == [HANZ, KYLE]
    # A non-admin gets the same reassurance without an instruction they cannot follow.
    assert "Nobody extra is told about deposits" in ran["emptyDepositStaff"]
    assert "Add someone below." not in ran["emptyDepositStaff"]


@needs_node
def test_an_empty_team_list_still_says_its_own_thing(ran):
    """Two empty states, two sentences: an empty team list means nobody is told anything, which
    is genuinely alarming and must not be softened into the deposit wording."""
    assert "No one on the list yet." in ran["emptyBoth"]["general"]
    assert "Nobody extra" not in ran["emptyBoth"]["general"]
    assert "Nobody extra is told about deposits" in ran["emptyBoth"]["deposit"]


@needs_node
def test_one_failed_fetch_fails_both_cards(ran):
    """One GET feeds both, so one card reading "Could not load" beside another still saying
    "Loading…" would look like half a working page instead of one failed request."""
    assert "Could not load" in ran["loadFails"]["general"]
    assert "Could not load" in ran["loadFails"]["deposit"]
    assert "Loading…" not in ran["loadFails"]["deposit"]


# ── the per-project strip, pinned to the decision ────────────────────────────
@needs_node
def test_the_per_project_chips_paint_from_the_team_list_only(ran):
    """THE DECISION, pinned by execution. A per-project chip is one on/off governing everything
    that project emails, and an override row is (proposal_id, email, mode) with NO kind — so a
    deposit-only person switched green there would be unioned into that project's general
    recipients as well, quietly promoting somebody who was added for three deposit emails into
    approvals, replies and questions.

    Mutation this kills: seeding peopleFor from ROSTER.concat(DEPOSIT_EXTRAS)."""
    assert ran["mixed"]["peopleFor"] == [HANZ, KYLE], (
        "the per-project strip is painting deposit-only people: %r" % ran["mixed"]["peopleFor"])
    assert KYLENE not in ran["mixed"]["peopleFor"]
    assert [m["email"] for m in ran["mixed"]["roster"]] == [HANZ, KYLE]
    assert [m["email"] for m in ran["mixed"]["deposits"]] == [KYLENE]


@needs_node
def test_the_per_project_card_says_so_on_screen(ran):
    """Whatever the decision, nobody should have to read peopleFor() to discover it."""
    html = ran["render"]["html"]
    assert "Only the team list is shown here — deposit-only people are not." in html, (
        "the per-project card does not say that deposit-only people are excluded from it")
    assert "no kind" in html and "approvals and replies" in html, (
        "the card states the exclusion without the reason, so the next person will 'fix' it")


# ── a non-admin ──────────────────────────────────────────────────────────────
@needs_node
def test_a_non_admin_can_read_both_lists_and_change_neither(ran):
    """Server-enforced either way (the roster routes are admin-only in main.py), but the deposit
    card must make the same call the team card does: readable, with no controls that 403."""
    assert [c["email"] for c in ran["staff"]["general"]] == [HANZ, KYLE]
    assert [c["email"] for c in ran["staff"]["deposit"]] == [KYLENE]
    assert not any(c["removable"] for c in ran["staff"]["general"] + ran["staff"]["deposit"]), (
        "a non-admin gets a × that will 403")
    assert ran["staff"]["generalListeners"] == [0, 0], "a non-admin's chips are still clickable"
    html = ran["staff"]["html"]
    assert _group(ran, "deposit")["input"] not in html, (
        "a non-admin gets the deposit Add field")
    assert html.count("Only admins can change this list") == 2, (
        "both cards should explain who can change them")


@needs_node
def test_the_roster_chips_keep_their_identity_colour(ran):
    """The opposite trade from the per-project chip: on the roster cards a chip's own colour is
    free, because nothing else on it competes with green. Both groups, so the deposit card looks
    like the team card rather than like a different app."""
    assert all(c["coloured"] for c in ran["mixed"]["general"] + ran["mixed"]["deposit"])


# ── the things a source read is the right tool for ───────────────────────────
def test_both_cards_come_out_of_one_builder():
    """Two hand-written cards would be two places to fix the same bug, and they drift: the first
    version of this page had one card whose copy nobody could compare against anything."""
    js = PAGE_JS.read_text(encoding="utf-8")
    assert "GROUPS.map(rosterCardHtml).join(" in js, (
        "the roster cards are no longer built from GROUPS through one builder")
    assert js.count("function paintGroup") == 1
    assert 'kind === "general"' not in js, (
        "the page is filtering the roster to general rows again — that is the bug this file is "
        "about, and kylene@'s row disappears with it")


def test_the_both_lists_label_is_styled_without_a_third_colour():
    """`.also` borrows the chip's own colour (currentColor). A tint of its own would read as a
    third state on a card where colour already means receives / off — and !important is forbidden
    on this page by test_page_boot.py anyway."""
    css = PAGE_HTML.read_text(encoding="utf-8")
    assert ".chip .also" in css, "the both-lists label is unstyled"
    rule = css.split(".chip .also")[1].split("}")[0]
    assert "currentColor" in rule, "the label carries its own colour and competes with green"
    assert "!important" not in css
