"""The Notification Sending page's per-step matrix: people down the side, CRM steps across the top.

Hanz, 2026-08-21: "So kylene is automatically toggled on notif send when customer approve proposal
right? Is there a way like a UI/UX that to implemeent toggle on and off who gets automatically
toggled on for the notif sending for each step of the CRM?"

THE PREMISE WAS WRONG, AND THAT IS WHY THIS EXISTS. Kylene is not tied to approval. She sat on the
`deposit` bucket, and approving is simply what triggers a deposit request, so the two looked
connected. `portal_notify_recipients.kind` held exactly ('general','deposit'), and of the nine
notify_team() call sites in the portal only two named a kind. The other seven took the default. So
every moment except the deposit shared one list, and the only settings anyone had were "the whole
team" and "the whole team plus the money people".

WHAT REPLACED IT. `kind` now holds a CRM STEP, derived from those nine call sites and named after
what actually happened (email_sender.NOTIFY_STEPS, served to this page so its columns cannot
drift). Resolution, widest rule first:

    the team floor  ->  this step's opt-ins and suppressions  ->  this project's adds and mutes

FOUR CELL STATES, NOT TWO, and that is the design decision this file spends most of its length on.
A green cell that came from the team list is not a decision anybody made about that step, and
reading it as one is the main risk the feature carries: somebody sees green under "Proposal
opened", believes it was chosen, and never asks again. So an INHERITED cell is drawn hollow and
dashed AND carries the word "team" inside it AND says so in its aria-label, while an EXPLICIT on
is solid and says "set here".

AN EXPLICIT OFF REALLY STOPS THE EMAIL. Chosen over the alternative (make a per-step off a no-op
and let the floor win) because it is what keeps the screen honest: every green cell receives and
every grey cell does not, one rule, readable straight off the grid. Otherwise the only way to take
one moment off somebody is removing them from the team, which takes the other eight with it. The
floor's real job survives: it decides when nothing has been SAID about this person and this step.
The honest consequence, a column switched off reaching nobody, is printed ON that column rather
than left for Hanz to discover.

THE DEPOSIT CARD IS GONE, deliberately. It was a card for one `kind`; that kind is now two matrix
columns (Deposit sent, Deposit received). Keeping it as well would have meant two controls writing
one row, which is how they come to disagree. Nothing became unreachable: kylene@, the row that was
live and invisible until 2026-08-20, is a matrix row with two explicit green cells and an x.

EVERYTHING BELOW IS EXECUTED. The house rule, bought on prod 2026-08-12: a source-text assertion
cannot see an unbound identifier, and that class of bug took the board down with every test green.
`js/notify-matrix-harness.js` lifts render(), load(), paintGroup(), paintMatrix(), mxCell(),
mxNext(), mxColumn(), toggleCell(), addEmail(), toggle() and removeOne() out of notifications.js,
runs them against the real crm-core.js and a store that answers like the API, and reports what
actually rendered and what was actually sent.

IT ALREADY EARNED ITS KEEP. `const cols = STEPS.map(mxColumn)` reads perfectly well and is wrong:
map hands the callback the step OBJECT, so every lookup missed, `silent` could never be true while
anybody sat on the floor, and the "nobody is told" warning would simply never have appeared. No
source assertion would have seen it.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "notify-matrix-harness.js"
PAGE_JS = FRONTEND / "js" / "notifications.js"
PAGE_HTML = FRONTEND / "notifications.html"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=90)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── the page has three cards, and the deposit card is not one of them ─────────
@needs_node
def test_the_page_renders_the_team_card_the_matrix_and_the_per_project_card(ran):
    r = ran["render"]
    assert r["cards"] == 3
    assert "Per step" in r["labels"][2]
    ids = r["ids"]
    for want in ("nn-chips", "nn-email", "nn-add", "nn-alert", "mx-grid", "mx-legend",
                 "mx-alert", "pp-list", "pp-tabs"):
        assert want in ids, want


@needs_node
def test_there_is_exactly_one_roster_group_and_it_is_the_floor(ran):
    """The deposit group is gone because its kind became two columns. Two controls writing one row
    is how they come to disagree, and the row it wrote is reachable here."""
    assert [g["kind"] for g in ran["groups"]] == ["general"]
    g = ran["groups"][0]
    assert "floor" in g["lbl"].lower()
    # The card has to SAY what the floor means, because the rule is invisible otherwise.
    assert "still reaches" in g["intro"]


@needs_node
def test_the_matrix_card_says_what_an_inherited_cell_is_and_what_an_off_cell_does(ran):
    """The two sentences the screen cannot ship without. The floor is invisible in the grid, and
    "I switched everyone off for viewed" has a consequence Hanz should read here rather than
    discover."""
    html = ran["render"]["html"]
    assert "inherited from the team list" in html
    assert "really does stop that one email" in html
    assert "nobody is told" in html
    assert "leaves their other steps alone" in html


@needs_node
def test_no_em_dash_reaches_the_matrix_copy(ran):
    """House rule for UI copy."""
    card = ran["render"]["html"]
    start = card.index("Per step")
    body = card[start:card.index("Per-project", start)]
    assert "—" not in body, "em dash in the matrix card copy"


# ── the columns come from the API, never from this page ──────────────────────
@needs_node
def test_the_columns_are_the_step_list_the_api_served(ran):
    assert ran["loaded"]["steps"] == [
        "sent", "viewed", "question", "status_change", "approved",
        "deposit_submitted", "deposit_received", "contacts", "feedback"]
    heads = [h["label"] for h in ran["beforeSilence"]["heads"]]
    assert heads == ["Proposal sent", "Proposal opened", "Customer question", "Customer status",
                     "Proposal approved", "Deposit sent", "Deposit received", "Project contacts",
                     "Portal feedback"]


@needs_node
def test_a_step_list_this_page_has_never_seen_renders_and_toggles(ran):
    """THE ASSERTION THAT PROVES THE LIST IS NOT HARDCODED. Feed the page two steps, one of them
    invented, and it draws two columns and PUTs the invented id.

    Mutation: replace `STEPS = (j.steps || [])...` with a literal array of the nine, and this
    fails."""
    alt = ran["altSteps"]
    assert alt["steps"] == ["sent", "invoice_issued"]
    assert alt["heads"] == ["Proposal sent", "Invoice issued"]
    assert alt["cellsPerRow"] == 2
    assert ran["altStepPut"]["body"] == {"email": "hanz@wetreadwell.com",
                                        "step": "invoice_issued", "state": "off"}


@needs_node
def test_nobody_disappears_when_their_step_is_not_on_the_list(ran):
    """kylene@'s rows name steps the short list does not carry, so they are not step rows there.
    She must still be visible SOMEWHERE, because a row that exists, works and appears nowhere is
    the original bug this page was fixed for on 2026-08-20."""
    alt = ran["altSteps"]
    assert "kylene@wetreadwell.com" in alt["chips"]
    assert "kylene@wetreadwell.com" in alt["people"]
    # ONCE IN THE GRID, because a grid row is a PERSON. The team card can show her twice here,
    # and that is right for what a chip is: a chip is a ROW, its x deletes that row by id, and
    # she genuinely holds two unrecognised rows in this fixture. Hiding one would leave a row
    # nothing on screen could remove, which is the failure this page exists to end. The grid
    # cannot do the same, because two rows for one person would give one person two answers to
    # every column.
    assert alt["people"].count("kylene@wetreadwell.com") == 1
    assert alt["chips"].count("kylene@wetreadwell.com") == 2


@needs_node
def test_a_missing_step_list_says_so_rather_than_drawing_an_empty_grid(ran):
    """An empty grid reads as "nobody is notified about anything", which is the most alarming
    possible way to render a failed fetch."""
    assert ran["noSteps"]["cells"] == 0
    assert "Could not load the step list" in ran["noSteps"]["grid"]


# ── the four states, and telling inherited from explicit ─────────────────────
@needs_node
def test_the_four_cell_states_render_differently_from_each_other(ran):
    """THE POINT OF THE FILE. One column, four people, four states, and no two of them share a
    class, a word or a spoken label.

    hanz: on the team, nothing set          -> inherited
    kyle: on the team, an explicit off row  -> off
    will: on the team but switched off      -> none
    kylene: not on the team at all          -> none, and her deposit cells are explicit on

    Mutation: draw the cell from `c.on` instead of `c.state` and this fails, because inherited and
    on collapse into one appearance."""
    cells = {c["email"].split("@")[0]: c for c in ran["fourStates"]["viewed"]}
    assert cells["hanz"]["state"] == "inherited"
    assert cells["kyle.loseke"]["state"] == "off"
    assert cells["will"]["state"] == "none"

    classes = {k: c["cls"] for k, c in cells.items()}
    assert classes["hanz"] == "mx-cell mx-inherited"
    assert classes["kyle.loseke"] == "mx-cell mx-off"
    assert classes["will"] == "mx-cell mx-none"
    # No two states share an appearance, which is the property, not the specific class names.
    assert len(set(classes.values())) == 3


@needs_node
def test_an_inherited_cell_says_where_it_came_from(ran):
    """Colour is not enough. The inherited cell is the only one carrying the word "team", and its
    aria-label names the team list, because the visual difference (hollow, dashed) reaches nobody
    using a screen reader."""
    assert ran["labelMap"]["inherited"] == "team"
    cells = {c["email"].split("@")[0]: c for c in ran["fourStates"]["viewed"]}
    assert cells["hanz"]["glyph"] == "team"
    assert cells["hanz"]["label"].endswith("on, inherited from the team list")
    # An explicit on says the opposite: it was chosen here.
    on = [c for c in ran["fourStates"]["depositReceived"] if c["state"] == "on"][0]
    assert on["glyph"] == "on" and on["label"].endswith("on, set here")
    # Both are ON, so aria-pressed alone cannot tell them apart. That is exactly why the label
    # carries the provenance.
    assert cells["hanz"]["pressed"] == "true" and on["pressed"] == "true"


@needs_node
def test_off_and_not_on_the_team_are_told_apart(ran):
    """Both are grey and both mean no email, but one is a decision and one is an absence. An off
    cell somebody set must not read as an untouched one, or nobody can see what has been done."""
    cells = {c["email"].split("@")[0]: c for c in ran["fourStates"]["viewed"]}
    assert cells["kyle.loseke"]["glyph"] == "off"
    assert cells["kyle.loseke"]["label"].endswith("off, switched off here")
    assert cells["will"]["glyph"] == ""
    # Will IS on the team, switched off there; Kylene is not on it at all. The row header says
    # which, so the cell must not contradict it.
    assert cells["will"]["label"].endswith("off, following the team list")
    kylene = [c for c in ran["fourStates"]["viewed"]
              if c["email"].startswith("kylene")][0]
    assert kylene["label"].endswith("off, not on the team")


@needs_node
def test_the_legend_names_all_four_states(ran):
    """A grid whose states are only decodable by clicking them is a puzzle. The legend is built
    from the same MX_LABEL the cells use, so a renamed state cannot label one and not the other."""
    legend = ran["loaded"]["legend"]
    for cls in ("mx-on", "mx-inherited", "mx-off", "mx-none"):
        assert cls in legend, cls
    assert "on, from the team list" in legend
    assert "switched off here" in legend
    assert set(ran["labelMap"]) == {"on", "off", "inherited", "none"}


# ── what one click writes ───────────────────────────────────────────────────
@needs_node
def test_clicking_an_inherited_cell_stores_an_explicit_off(ran):
    """It has to STORE a row, not delete one: an off must outrank the floor, and only a stored row
    can. Deleting would leave it inheriting on again, so the click would look like it did nothing.

    Mutation: send "inherit" here and this fails."""
    c = ran["clickInherited"]
    assert c["put"]["path"] == "/api/portal/notify-recipients/step"
    assert c["put"]["method"] == "PUT"
    assert c["put"]["body"] == {"email": "hanz@wetreadwell.com", "step": "approved",
                               "state": "off"}
    assert c["after"]["state"] == "off"
    assert c["rows"] == [{"id": 100, "email": "hanz@wetreadwell.com", "kind": "approved",
                          "enabled": False}]


@needs_node
def test_a_suppression_touches_one_step_and_leaves_the_rest_of_the_row_alone(ran):
    """The difference between a knob and a cliff. Hanz is off "approved" and still inherited
    everywhere else."""
    assert ran["clickInherited"]["elsewhere"]["state"] == "inherited"
    assert ran["clickInherited"]["cells"]["hanz@wetreadwell.com"] == {"approved": False}


@needs_node
def test_clicking_an_explicit_off_clears_the_row_rather_than_flipping_it_on(ran):
    """Back to following the team list, NOT an explicit on. An accumulated row that happens to
    agree with the floor is a row that stops agreeing the day somebody leaves the team.

    Mutation: `return wantOn ? "on" : "off";` in mxNext, so nothing can ever be cleared. Fails
    here."""
    c = ran["clickOff"]
    assert c["put"]["body"]["state"] == "inherit"
    assert c["after"]["state"] == "inherited"
    assert c["rows"] == [], "the row survived a clear"
    assert "kyle.loseke@wetreadwell.com" not in c["cells"]


@needs_node
def test_clicking_an_empty_cell_opts_that_person_into_one_step(ran):
    """How a deposit-only person is created: somebody off the floor given exactly one moment."""
    c = ran["clickNone"]
    assert c["put"]["body"] == {"email": "will@wetreadwell.com", "step": "contacts",
                               "state": "on"}
    assert c["after"]["state"] == "on"
    assert c["cells"]["will@wetreadwell.com"] == {"contacts": True}


@needs_node
def test_clicking_an_explicit_on_clears_it_and_leaves_the_other_step_standing(ran):
    """kylene@ holds TWO rows, one per money step. Clearing one must not touch the other, which is
    the whole reason the legacy single 'deposit' row was split."""
    c = ran["clickOn"]
    assert c["put"]["body"]["state"] == "inherit"
    assert c["after"]["state"] == "none"
    assert c["other"]["state"] == "on"
    assert c["cells"]["kylene@wetreadwell.com"] == {"deposit_submitted": True}
    # She still has a row, so she does not vanish from the grid mid-edit.
    assert "kylene@wetreadwell.com" in c["people"]


@needs_node
def test_every_state_carries_the_next_state_it_would_write(ran):
    """Four states, and the click from each is decided by mxNext rather than by the handler, so the
    grid and the request cannot disagree about what a click means."""
    nxt = {c["state"]: c["next"] for c in ran["fourStates"]["viewed"]}
    assert nxt["inherited"] == "off"
    assert nxt["off"] == "inherit"
    assert nxt["none"] == "on"
    on = [c for c in ran["fourStates"]["depositReceived"] if c["state"] == "on"][0]
    assert on["next"] == "inherit"


# ── the honest consequence, printed on the column ───────────────────────────
@needs_node
def test_a_column_nobody_hears_about_says_nobody_is_told(ran):
    """The other half of choosing suppression over a no-op: switch a whole column off and it says
    so, on the column, rather than leaving Hanz to find out from a customer.

    Mutation: `silent: false` in mxColumn, and this fails."""
    assert ran["beforeSilence"]["warns"] == 0, "the warning is noise until it is true"
    assert ran["beforeSilence"]["columns"] == [False] * 9
    after = ran["afterSilence"]
    assert after["column"] == {"step": "viewed", "reach": [], "silent": True}
    assert after["warns"] == 1
    assert after["warned"] == ["Proposal opened"], "the warning landed on the wrong column"
    assert after["quiet"] == ["Proposal opened"]
    assert after["others"] == [False] * 8, "one column went quiet and took the others with it"


@needs_node
def test_the_columns_reach_is_the_resolver_rule_not_a_count_of_green(ran):
    """The floor plus this step's opt-ins minus its suppressions. Kyle's suppression removes him
    from `viewed` only; kylene@'s two rows add her to the money steps only."""
    by = {c["step"]: c["reach"] for c in ran["columns"]}
    assert by["sent"] == ["hanz@wetreadwell.com", "kyle.loseke@wetreadwell.com"]
    assert by["viewed"] == ["hanz@wetreadwell.com"]
    assert by["deposit_received"] == ["hanz@wetreadwell.com", "kyle.loseke@wetreadwell.com",
                                      "kylene@wetreadwell.com"]
    assert by["approved"] == ["hanz@wetreadwell.com", "kyle.loseke@wetreadwell.com"]
    # will@ is on the roster but switched off, so he is on no column at all.
    assert not any("will@wetreadwell.com" in r for r in by.values())


# ── the floor and the matrix move together ──────────────────────────────────
@needs_node
def test_switching_somebody_on_in_the_team_card_lights_their_inherited_cells(ran):
    """The floor is what every inherited cell inherits FROM, so a chip toggle has to repaint the
    grid. Otherwise the grid keeps showing a state that is no longer true.

    Mutation: drop the load()/paint after a toggle and this fails."""
    m = ran["floorMove"]
    assert m["before"]["state"] == "none"
    assert m["after"]["state"] == "inherited"
    assert m["patch"]["body"] == {"enabled": True}
    # And somebody else's explicit off is not disturbed by it.
    assert m["kyle"]["state"] == "off"


@needs_node
def test_the_team_chip_says_when_a_person_carries_step_exceptions(ran):
    """A team row and a step row are separate rows. Somebody looking at the team card has to be
    able to see that this person is not simply "on"."""
    chips = {c["email"].split("@")[0]: c for c in ran["exceptionLabel"]["chips"]}
    assert chips["kyle.loseke"]["also"] == "has step exceptions"
    assert chips["hanz"]["also"] is None
    on = ran["exceptionLabel"]["onList"]
    assert on == {"kyleGeneral": True, "kyleSteps": True, "hanzSteps": False,
                  "kyleneGeneral": False}


@needs_node
def test_removing_somebody_from_the_team_warns_that_their_step_rows_survive(ran):
    """Two rows, two ids: the DELETE takes the team row and leaves the step rows. Somebody who
    believes they removed everything stops looking, so the dialog has to say it."""
    r = ran["removeWarns"]
    assert "per-step settings stay" in r["dialog"]["after"]
    assert [d["path"] for d in r["deletes"]] == ["/api/portal/notify-recipients/2"]
    assert "kyle.loseke@wetreadwell.com" not in r["chips"]
    # Still on the grid, because his suppression row still exists and must stay reachable.
    assert "kyle.loseke@wetreadwell.com" in r["people"]
    assert r["viewed"]["state"] == "off"
    # Removing must not also toggle: the x calls stopPropagation and the chip guards on the class.
    assert r["patches"] == 0


@needs_node
def test_removing_somebody_with_no_step_rows_gets_the_plain_question(ran):
    assert ran["removePlain"]["dialog"]["after"] == "?"


@needs_node
def test_adding_somebody_still_lands_on_the_team_switched_off(ran):
    """Adding a colleague must never start sending. Their whole matrix row is empty until somebody
    turns them on, so a new hire cannot silently begin receiving nine kinds of email."""
    a = ran["add"]
    assert a["post"]["body"] == {"email": "newteam@wetreadwell.com", "kind": "general"}
    assert a["row"] == ["none"] * 9
    assert [c for c in a["chips"] if c["email"] == "newteam@wetreadwell.com"][0]["on"] is False


# ── the legacy 'deposit' row, and rows from the future ──────────────────────
@needs_node
def test_a_legacy_deposit_row_lights_both_money_cells(ran):
    """kylene@ was live on prod as a single `kind='deposit'` row. The portal fans it out to both
    money steps at resolve time, so the grid has to as well: showing her switched off for emails
    she is in fact receiving is the screen lying about the resolver.

    Mutation: return `[k]` from stepsOfRow for the legacy kind and this fails."""
    lg = ran["legacy"]
    assert lg["cells"]["kylene@wetreadwell.com"] == {"deposit_submitted": True,
                                                     "deposit_received": True}
    assert lg["submitted"]["state"] == "on" and lg["received"]["state"] == "on"
    assert lg["approved"]["state"] == "none", "a deposit row must not imply the other steps"
    # And she is NOT on the team card, because a legacy deposit row is not floor membership. That
    # is the difference between the grid explaining the resolver and contradicting it.
    assert lg["chips"] == ["hanz@wetreadwell.com"]


@needs_node
def test_a_row_whose_kind_nothing_recognises_stays_visible_on_the_team_card(ran):
    """The portal's resolver buckets anything it does not know as the floor, and a row this page
    silently dropped is the original bug. So: visible, removable, on the card that can do it."""
    u = ran["unknownKind"]
    assert u["chips"] == ["nokind@wetreadwell.com", "future@wetreadwell.com"]
    assert u["cells"] == {"kylene@wetreadwell.com": {"deposit_received": True}}
    assert sorted(u["people"]) == ["future@wetreadwell.com", "kylene@wetreadwell.com",
                                   "nokind@wetreadwell.com"]


# ── permissions, failures, and the empty roster ─────────────────────────────
@needs_node
def test_a_non_admin_can_read_the_grid_and_change_nothing(ran):
    """Unlike the per-project chips, where anyone may silence their own address on one job. This is
    the org-wide roster: one estimator quietly taking the team off "proposal approved" is the sort
    of change nobody notices until a deal goes cold."""
    s = ran["staff"]
    assert all(s["cellsDisabled"]), "a cell was clickable for a non-admin"
    assert set(s["cellListeners"]) == {0}, "handlers were wired for a non-admin"
    assert s["fired"] is False and s["puts"] == 0
    assert "Only admins can change this grid" in s["html"]
    # They still SEE it. A blank card would leave them unable to check who is notified.
    assert "mx-cell" in s["grid"]


@needs_node
def test_a_failed_write_says_so_and_leaves_the_grid_telling_the_truth(ran):
    """The cell must snap back to what the server still holds. A cell that stays where the click
    put it is a screen claiming a change that never landed."""
    f = ran["putFails"]
    assert "Could not update" in f["alert"]
    assert f["cell"]["state"] == "inherited"
    assert "hanz@wetreadwell.com" not in f["cells"]
    assert f["groupAlert"] == "", "the roster card reported somebody else's failure"


@needs_node
def test_one_failed_fetch_does_not_look_like_half_a_working_page(ran):
    f = ran["loadFails"]
    assert "Could not load" in f["general"]
    assert "Could not load" in f["grid"], "the grid was left saying Loading"


@needs_node
def test_an_empty_roster_says_what_to_do_next(ran):
    e = ran["empty"]
    assert e["cells"] == 0
    assert "Nobody on the roster yet" in e["grid"] and "Add someone above" in e["grid"]
    assert "No one on the list yet" in e["general"]


# ── the size this has to survive ───────────────────────────────────────────
@needs_node
def test_thirteen_people_by_nine_steps_renders_one_cell_each(ran):
    """The size Hanz's roster actually reaches. 117 cells, 13 rows plus a header, 9 column heads,
    and every cell in one of the four states rather than blank."""
    t = ran["thirteen"]
    assert t["people"] == 13
    assert t["cells"] == 117 == 13 * 9
    assert t["rows"] == 14
    assert t["heads"] == 9
    assert sum(t["states"].values()) == 117
    # 9 of the 13 are on the floor (every third is off), so 81 inherited and 36 none.
    assert t["states"] == {"inherited": 81, "none": 36}


@needs_node
def test_the_grid_scrolls_inside_its_own_box_with_the_name_column_pinned(ran):
    """A 9-column grid on a laptop must not scroll the PAGE sideways, and a row of unlabelled
    toggles is not a grid, so the person column stays put while the steps scroll."""
    assert ran["thirteenScroll"] is True
    assert ran["thirteen"]["sticky"] is True
    css = PAGE_HTML.read_text(encoding="utf-8")
    assert ".mx-scroll { overflow-x:auto" in css
    assert ".mx-who { position:sticky" in css


@needs_node
def test_the_four_states_have_four_different_css_rules(ran):
    """The classes the grid emits have to be the classes the stylesheet styles, and each of the
    four has to look different. An inherited cell is the one with a DASHED border, which is the
    difference that survives being printed in greyscale or read by somebody colour-blind."""
    css = PAGE_HTML.read_text(encoding="utf-8")
    for cls in (".mx-on", ".mx-inherited", ".mx-off", ".mx-none"):
        assert cls + " {" in css, cls
    dashed = css[css.index(".mx-inherited {"):]
    assert "dashed" in dashed[:dashed.index("\n")]
    solid = css[css.index(".mx-on {"):]
    assert "dashed" not in solid[:solid.index("\n")]


@needs_node
def test_the_page_loads_the_script_and_keeps_its_own_step_list_nowhere(ran):
    """One source of truth for the vocabulary: the portal. A literal step id in the page would be
    a copy waiting to drift, and the drift would be silent."""
    js = PAGE_JS.read_text(encoding="utf-8")
    # The two money steps are named once each, in stepsOfRow's legacy fan-out, and nowhere else.
    assert js.count('"deposit_submitted"') == 1
    assert js.count('"deposit_received"') == 1
    for sid in ("sent", "viewed", "question", "status_change", "approved", "contacts", "feedback"):
        assert ('"%s"' % sid) not in js, sid


# ── claims carried over from the deposit-roster card this matrix replaced ────
# test_deposit_roster_ui.py and js/deposit-roster-harness.js were retired with this change: the
# card they tested existed to make ONE `kind` visible, and that kind is now two matrix columns.
# Every claim it made either moved above (the split by kind, the add's kind, per-row toggle and
# remove, the unknown kind, the failed fetch, the non-admin) or is restated here, so nothing that
# file protected is unprotected now.
@needs_node
def test_a_roster_chip_carries_its_enabled_state_and_the_shared_identity_colour(ran):
    """A person looks the same here as on a CRM card, because the avatar comes from crm-core. The
    matrix cells deliberately do NOT carry it: colour there is the state, and a purple Alejandro
    beside a green Hanz would leave green ambiguous."""
    chips = {c["email"].split("@")[0]: c for c in ran["chipState"]}
    assert chips["hanz"]["on"] is True
    assert chips["will"]["on"] is False
    assert all(c["coloured"] for c in ran["chipState"])
    assert all(c["removable"] for c in ran["chipState"])
    # And no matrix cell carries an identity colour.
    assert "tw-av" not in ran["loaded"]["grid"]


@needs_node
def test_each_roster_toggle_targets_its_own_row(ran):
    """Ids come out of freshly generated HTML and the handlers are re-wired on every paint, so a
    data-id on the wrong chip is a silent cross-wire: you switch Hanz off and Will stops being
    notified."""
    o = ran["ownRow"]
    assert o["first"]["path"].endswith("/1") and o["first"]["body"] == {"enabled": False}
    assert o["second"]["path"].endswith("/3") and o["second"]["body"] == {"enabled": True}
    chips = {c["email"].split("@")[0]: c["on"] for c in o["chips"]}
    assert chips == {"hanz": False, "kyle.loseke": True, "will": True}


@needs_node
def test_a_roster_change_repaints_the_per_project_card(ran):
    """The effective per-project state is the floor plus that project's overrides, so moving the
    floor moves every chip down there too."""
    assert ran["ownRow"]["projectRenders"] == 2


@needs_node
def test_the_per_project_strip_paints_from_the_team_list_only(ran):
    """kylene@ holds two step rows and no team row, so she is absent. A per-project override is
    stored as (proposal_id, email, mode) with no step attached, so switching her green there would
    union her address into that project's whole recipient list, quietly promoting somebody set up
    for two deposit emails into approvals, replies and questions."""
    assert ran["perProject"]["people"] == ["hanz@wetreadwell.com", "kyle.loseke@wetreadwell.com",
                                          "will@wetreadwell.com"]
    # And the card says so, rather than leaving somebody to read peopleFor() to find out.
    assert "set for one step only" in ran["perProject"]["copy"]


@needs_node
def test_enter_in_the_add_field_is_the_same_path_as_its_button(ran):
    assert ran["addByEnter"]["body"] == {"email": "enter@wetreadwell.com", "kind": "general"}


@needs_node
def test_an_empty_add_field_asks_for_an_address_and_sends_nothing(ran):
    e = ran["addEmpty"]
    assert e["posts"] == 0 and e["alert"] == "Enter an email address."
    assert e["mx"] == "", "the matrix reported the roster card's problem"


@needs_node
def test_a_failed_add_reports_on_its_own_card_and_leaves_the_button_usable(ran):
    f = ran["addFails"]
    assert "Could not add" in f["alert"]
    assert f["mx"] == ""
    assert f["btnLabel"] == "Add" and f["btnDisabled"] is False


@needs_node
def test_declining_the_remove_dialog_sends_nothing(ran):
    d = ran["declined"]
    assert d["deletes"] == 0
    assert len(d["chips"]) == 3


# THE DORMANT LEGACY ROW, which is the shape that reaches live data on deploy
@needs_node
def test_a_dormant_legacy_deposit_row_draws_no_suppression(ran):
    """kylene@ holds a single `kind='deposit'` row that is switched OFF. Under the old vocabulary
    that meant "an address typed into the Deposit-alerts card and never turned green" and nothing
    more, because there WAS no such thing as a suppression: `kind` held exactly
    ('general','deposit'). Adding a recipient has always created the row off, so every address
    ever typed there and left grey is exactly this.

    The portal's resolver skips such a row (email_sender.bucket_notify_rows), so the grid must draw
    NOTHING explicit for it. Two grey OFF cells would be this screen claiming a suppression that
    stops no email, which is the one lie it must not tell.

    Mutation: return the two money steps from stepsOfRow regardless of `enabled`, and this fails
    on all four assertions below."""
    lg = ran["legacyOff"]
    assert lg["cells"] == {}, "a dormant row was read as an explicit setting"
    assert lg["submitted"]["state"] == "none" and lg["received"]["state"] == "none"
    assert lg["submitted"]["glyph"] == "" and lg["received"]["glyph"] == ""
    # And the column agrees with the resolver: she is not counted, and hanz still is.
    assert lg["column"] == {"step": "deposit_received", "reach": ["hanz@wetreadwell.com"],
                           "silent": False}


@needs_node
def test_a_dormant_legacy_row_still_keeps_its_person_on_the_grid(ran):
    """Skipping the row must not hide the PERSON. A row the roster holds and the page cannot show
    is the failure this card was rebuilt to end, and the cure for one lie must not be the other.

    Mutation: drop INERT from mxPeople and she disappears from the page entirely."""
    lg = ran["legacyOff"]
    assert "kylene@wetreadwell.com" in lg["people"]
    # Not on the team card, because a legacy deposit row is not floor membership either way.
    assert lg["chips"] == ["hanz@wetreadwell.com"]


@needs_node
def test_clicking_one_of_those_grey_cells_opts_her_in_for_real(ran):
    """The row being inert is not the same as the cell being dead. Clicking it writes a proper step
    row, which is how a dormant legacy entry gets turned into a live one from the UI rather than
    from SQL."""
    c = ran["legacyOffClick"]
    assert c["put"]["body"] == {"email": "kylene@wetreadwell.com", "step": "deposit_received",
                               "state": "on"}
    assert c["cell"]["state"] == "on"


# THE COLUMN THAT MAY NOT BE EMPTIED
@needs_node
def test_only_the_required_column_says_one_person_minimum(ran):
    """`sent` is the only step whose email is also a WARNING: the portal sends it on a delivery
    FAILURE too ("That customer has not received the proposal"). So it is the only column that may
    not be left reaching nobody, and the server refuses the click that would do it.

    The badge is the EXPLANATION, not the check, and it comes off the portal's `required` flag
    rather than a step id typed here. Mutation: hardcode the badge onto every column, or drop the
    flag, and this fails."""
    heads = ran["required"]["heads"]
    assert [h["label"] for h in heads if h["req"]] == ["Proposal sent"]
    assert not any(h["warn"] for h in heads), "the louder warning is noise until it is true"
    # And the card says the rule in a sentence, including the way out of it.
    assert ran["required"]["copy"], "the matrix card never explains the one locked column"


@needs_node
def test_a_refused_click_says_what_to_do_instead_of_printing_the_error_code(ran):
    """The refusal is an answer, not a failure. "Could not update: would_silence_step" tells the
    reader nothing and suggests retrying, which cannot work.

    Mutation: fall through to the generic `throw new Error(code)` and the alert reads
    "Could not update: would_silence_step"."""
    r = ran["refused"]
    assert "Somebody has to hear about Proposal sent" in r["alert"]
    assert "did not reach the customer" in r["alert"]
    assert "Turn another person on for it first" in r["alert"], "no way out is offered"
    assert "Could not update" not in r["alert"]


@needs_node
def test_a_refused_click_leaves_the_grid_telling_the_truth(ran):
    """The cell has to snap back to what the server still holds, exactly like any other failed
    write: a cell that stays where the click put it is a screen claiming a change that never
    landed."""
    r = ran["refused"]
    assert r["before"]["state"] == "inherited"
    assert r["after"]["state"] == "inherited", "the cell kept the refused state"
    assert "hanz@wetreadwell.com" not in r["cells"], "a refused write was cached locally"
    assert r["groupAlert"] == "", "the roster card reported the matrix's refusal"
