"""Step 5's project-folder chooser: the estimator PICKS the folder the job already has.

Kyle, on the old step 5: "To Dropbox" asked only which CATEGORY to file into and then the server
invented a `YY.MM.DD Project name` folder inside it. His team already makes the job's folder — often
weeks before an estimate exists — so the destination ended up holding two folders for one job, and
the estimate was in the one nobody opens.

WHAT THE UI HAS TO GET RIGHT, and why each rule is here rather than "whatever is easiest":

  * NOTHING IS PRESELECTED unless the server's best candidate is BOTH strong on its own
    (>= DBX_MIN_SCORE) AND clear of the runner-up (>= DBX_MIN_LEAD). Filing an estimate into
    another customer's folder is far worse than one extra click, and "26.06.12 Trabon Office
    Polish" against "26.08.02 Trabon Group HQ" is exactly the pair a score cannot settle.
    When nothing is preselected the Upload button stays DISABLED — the guard, not a hint.
  * PREVIOUS_PATH WINS. Where this project was filed last time is a fact; a similarity score is
    a guess. A re-upload has to default to the same folder.
  * THE CREATE OPTION IS LAST AND UNFILTERABLE. Gyp Estimates returns ~80 folders, so there is a
    filter box — and a filter that can hide the only way forward turns step 5 into a dead end.
    Creating is still allowed, just never the accident.
  * A DEAD DROPBOX DEGRADES TO THE OLD BEHAVIOUR: create-only, button usable. Step 5 must never
    dead-end on somebody else's outage.
  * FOLDER NAMES ARE ESCAPED. A Dropbox folder is named by whoever made it, and that name is
    rendered into a radio group as an innerHTML string.

EVERYTHING BELOW IS EXECUTED. The house rule, bought the hard way on 2026-08-12: a source-text
assertion cannot see an unbound identifier, and that class of bug took the board down on prod with
every test green. `js/dropbox-picker-harness.js` lifts the real functions out of frontend/js/dropbox.js
— the ranking rule, the row markup, the filter, the button sync, and the page's own esc() — runs them
against a DOM stub, and reports what actually rendered.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "dropbox-picker-harness.js"
PAGE_HTML = FRONTEND / "done.html"
PICKER_CSS = FRONTEND / "dropbox-picker.css"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── the preselection rule ────────────────────────────────────────────────────
@needs_node
def test_a_clear_winner_is_preselected_and_the_button_says_file_into_it(ran):
    """0.90 against 0.40: strong, and nothing near it. This is the case where saving the estimator
    a click is safe, so the row arrives checked, wearing the badge, with an armed button."""
    s = ran["clearWinner"]
    assert s["checkedCount"] == 1, "exactly one row may be preselected"
    assert s["checked"] == [ran["clearTopPath"]]
    assert s["badges"] == ["closest match"], "the top-ranked row is the one that says so"
    assert s["goDisabled"] is False
    assert s["goLabel"] == "File into this folder"
    assert "26.06.12 Trabon Office Polish" in s["note"]


@needs_node
def test_two_close_matches_preselect_nothing_and_the_upload_button_is_disabled(ran):
    """0.90 against 0.80. Same top score as the case above and the same three folders — only the
    runner-up moved — so anything that reports the same verdict for both has stopped reading the
    lead at all. The button being DISABLED is the point: a nudge the estimator can click through
    is not a guard, and this is the mutation that files an estimate into the wrong job."""
    s = ran["contested"]
    assert s["choice"] is None, "a contested best guess must not be armed"
    assert s["checkedCount"] == 0, "no radio may arrive checked"
    assert s["goDisabled"] is True
    assert s["goLabel"] == "Choose a folder above"
    # Both candidates are still on screen, side by side — that IS the resolution mechanism.
    assert s["names"][:2] == ["26.06.12 Trabon Office Polish", "26.08.02 Trabon Group HQ"]


@needs_node
def test_picking_a_row_arms_the_button_through_the_pages_own_change_handler(ran):
    """Reached by checking the radio the page rendered and letting its own `change` listener run —
    not by poking state. `contestedAfterPick` is the same scope as `contested` one click later."""
    s = ran["contestedAfterPick"]
    assert s["choice"] == ran["contestedRadioValue"]
    assert s["goDisabled"] is False
    assert s["goLabel"] == "File into this folder"
    assert "26.08.02 Trabon Group HQ" in s["note"], "the note names the folder that was picked"


@needs_node
def test_a_lone_candidate_needs_no_lead_but_still_needs_the_score(ran):
    """One folder has no runner-up to be clear of, so the floor is the only test left. Getting this
    wrong in the generous direction arms every single-folder category; in the strict direction it
    never preselects anything at all."""
    assert ran["loneStrong"]["checkedCount"] == 1
    assert ran["loneStrong"]["goDisabled"] is False
    assert ran["loneWeak"]["choice"] is None, "0.55 alone is still a guess"
    assert ran["loneWeak"]["goDisabled"] is True


@needs_node
def test_a_wide_lead_between_two_weak_guesses_arms_nothing(ran):
    """0.71 over 0.10 is a runaway winner among candidates that both look wrong. The lead test
    passing does not excuse the floor — a rule written as `top - next >= LEAD` alone would arm this."""
    assert ran["underFloor"]["choice"] is None
    assert ran["underFloor"]["goDisabled"] is True


# ── previous_path ────────────────────────────────────────────────────────────
@needs_node
def test_previous_path_beats_the_score(ran):
    """The top row here scores 0.95 against 0.20 — a runaway the score rule would happily arm — so
    the selection landing on the previous folder is the only thing that can move it."""
    s = ran["previousWins"]
    assert s["checked"] == [ran["previousPath"]]
    assert s["choice"] != ran["topPath"], "last time's folder outranks this time's best guess"
    assert s["goDisabled"] is False


@needs_node
def test_a_previous_path_dropbox_no_longer_lists_falls_back_to_the_score(ran):
    """The folder was renamed or moved. Preselecting a path with no row would leave the button armed
    over an invisible choice, which is the worst of both answers."""
    s = ran["previousGone"]
    assert s["checkedCount"] == 1
    assert s["checked"] == [ran["clearTopPath"]]


@needs_node
def test_the_drafts_remembered_folder_is_honoured_on_a_revisit(ran):
    """dropbox_result.folder_path off the local state, restored before any response arrives. Same
    precedence as the server's previous_path, and it must beat a contested score that would
    otherwise arm nothing: revisiting a filed project should default to where it went."""
    s = ran["restoredFromDraft"]
    assert s["checked"] == [ran["restoredPath"]]
    assert s["goDisabled"] is False


# ── the filter ───────────────────────────────────────────────────────────────
@needs_node
def test_the_filter_narrows_the_list_on_the_text_the_row_shows(ran):
    """Name and parent both, because both are on screen and either is what a person types."""
    assert ran["filterNarrowed"]["names"][:-1] == ["26.06.12 Trabon Office Polish",
                                                   "26.08.02 Trabon Group HQ"]
    assert ran["filterByParent"]["names"][:-1] == ["25.11.20 Tribeca Lofts"], (
        "the parent folder is visible text, so it has to be searchable text")
    # Clearing the box restores every candidate: the filter narrows the VIEW, never the list.
    assert len(ran["filterCleared"]["names"]) == 4


@needs_node
def test_the_filter_cannot_hide_the_create_a_new_folder_option(ran):
    """Moving the create row inside the filtered array reads perfectly well and dead-ends step 5:
    a search that matches nothing would leave an empty box and a disabled button, with no way
    forward at all. It survives even the search that matches nothing."""
    for key in ("filterNarrowed", "filterByParent", "filterNoMatch", "filterCleared",
                "filterHidesChoice"):
        s = ran[key]
        assert s["newRowCount"] == 1, key + " lost the create option"
        assert s["names"][-1].endswith("Create a new folder"), (
            key + ": create must be the LAST row, so choosing it is deliberate")
    assert len(ran["filterNoMatch"]["radioValues"]) == 1, (
        "nothing matched, so create is all that is left — and it is still there")


@needs_node
def test_a_chosen_row_the_filter_hides_is_still_named_in_the_note(ran):
    """An armed button over a selection nobody can see is how an estimate goes to the wrong job.
    The note is read from the FULL list, not the filtered one, so the folder keeps its name on
    screen even while its row is hidden."""
    s = ran["filterHidesChoice"]
    assert s["choice"], "the choice survives typing in the filter box"
    assert "26.06.12 Trabon Office Polish" in s["note"]
    assert s["goDisabled"] is False


# ── the degraded paths: step 5 must never dead-end ───────────────────────────
@needs_node
def test_an_error_response_still_renders_a_usable_create_option(ran):
    """Dropbox was unreachable. This is exactly the old behaviour — one destination, one button —
    and it has to keep working when the new list cannot be fetched."""
    s = ran["errorResponse"]
    assert s["newRowCount"] == 1
    assert s["checkedCount"] == 1, "with nothing to choose between, create is safe to arm"
    assert s["choice"] == "", "an empty choice means create, not a path"
    assert s["goDisabled"] is False
    assert s["goLabel"] == "Create folder & upload"
    # ...and it SAYS the list is missing. An outage that silently renders "a new folder will be
    # created" reads as the tool's decision rather than as a failure the estimator should know about.
    assert "503" in s["note"] and ran["suggested"] in s["note"]


@needs_node
def test_an_empty_category_and_a_mangled_body_also_degrade_to_create(ran):
    """No folders and no error is a genuinely empty category; a body with no `folders` key at all
    is what a mangled response looks like. Neither may leave the estimator stuck."""
    for key in ("emptyCategory", "junkResponse"):
        s = ran[key]
        assert s["goDisabled"] is False, key + " dead-ends step 5"
        assert s["choice"] == ""
    assert "YY.MM.DD" in ran["junkResponse"]["note"], (
        "with no suggested name, say the shape of the name rather than nothing")


@needs_node
def test_no_destination_chosen_hides_the_field_and_keeps_upload_disabled(ran):
    s = ran["noDestination"]
    assert s["fieldShown"] is False
    assert s["radioValues"] == []
    assert s["note"] == ""
    assert s["goDisabled"] is True


# ── the rows themselves ──────────────────────────────────────────────────────
@needs_node
def test_choosing_create_names_the_exact_folder_that_would_be_created(ran):
    """"Create a new folder" with no name is a blind action. The server's suggested_new_name is on
    the row and in the note, so creating is a decision and not a shrug."""
    s = ran["pickedNew"]
    assert s["choice"] == ""
    assert s["goLabel"] == "Create folder & upload"
    assert ran["suggested"] in s["note"]
    assert any(ran["suggested"] in p for p in s["parents"]), (
        "the name is on the row too, not only in the note")


@needs_node
def test_only_the_top_ranked_row_wears_the_closest_match_badge(ran):
    for key in ("clearWinner", "contested", "filterCleared", "pickedNew"):
        assert ran[key]["badges"] == ["closest match"], key


@needs_node
def test_each_rows_full_path_is_its_title_so_a_hover_disambiguates(ran):
    """Two folders one word apart are told apart by their path, and the path is far too long to
    render on the row."""
    s = ran["clearWinner"]
    assert len(s["titles"]) == 4, "every row carries a title, create included"
    assert s["titles"][0].endswith("/*Kyle/26.06.12 Trabon Office Polish")
    assert s["titles"][0].startswith("/2023 Treadwell Team Folder/")


@needs_node
def test_the_parent_is_shown_only_when_it_differs_from_the_destination(ran):
    """"in *Kyle" is the whole reason the line exists; "in Gyp Estimates" repeated down 80 rows is
    noise on the destination the estimator just picked."""
    s = ran["parentSameAsDest"]
    parents = [p for p in s["parents"] if p.startswith("in ")]
    assert parents == ["in *Kyle"], (
        "the row whose parent IS the chosen destination must not repeat it")


# ── escaping ─────────────────────────────────────────────────────────────────
@needs_node
def test_a_folder_named_like_an_attack_is_escaped_not_rendered(ran):
    """A Dropbox folder is named by whoever made it, and the row is built as an innerHTML string.
    esc() existing in the file proves nothing about whether the NAME went through it."""
    s = ran["escaping"]
    html = s["html"]
    assert "<img" not in html, "the folder name became markup"
    assert "<script" not in html, "the parent folder name became markup"
    assert "&lt;img src=x onerror=alert(1)&gt;" in html, (
        "...and it is still readable, which is how the estimator recognises the folder")
    assert "onerror=alert(1)&gt;" in s["names"][0]
    # The suggested new name comes from the server too, and lands on the create row.
    assert "&lt;b&gt;26.08.20&lt;/b&gt;" in html
    # The value the POST would carry is the REAL path, unescaped — escaping is for display only.
    assert ran["nastyName"] in s["radioValues"][0]


# ── the markup and the sheet the JS renders into ─────────────────────────────
@needs_node
def test_done_html_has_the_nodes_the_chooser_writes_into():
    """The harness runs dropbox.js against a stub, so it cannot see a missing div. Without these
    ids the whole chooser renders into nothing and the button never arms."""
    html = PAGE_HTML.read_text(encoding="utf-8")
    for node_id in ("dbx-folder-field", "dbx-search", "dbx-folders", "dbx-folder-note"):
        assert 'id="' + node_id + '"' in html, node_id + " is missing from done.html"
    assert 'href="/dropbox-picker.css"' in html, "the chooser's stylesheet is not linked"
    assert 'role="radiogroup"' in html


@needs_node
def test_the_picker_stylesheet_styles_what_the_js_emits(ran):
    """Every class the rows carry needs a rule, or the list renders as unstyled radio soup. Read off
    the REAL rendered html rather than a list retyped here."""
    css = PICKER_CSS.read_text(encoding="utf-8")
    html = ran["clearWinner"]["html"] + ran["pickedNew"]["html"] + ran["filterNoMatch"]["html"]
    emitted = set()
    for chunk in html.split('class="')[1:]:
        for cls in chunk.split('"')[0].split():
            if cls.startswith("dbx-"):
                emitted.add(cls)
    assert emitted, "nothing rendered at all"
    missing = sorted(c for c in emitted if "." + c not in css)
    assert missing == [], "unstyled classes: " + ", ".join(missing)
