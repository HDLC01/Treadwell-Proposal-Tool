"""Phase 9b: Estimating Tool v2's intake shows the four job types and mounts the shared county picker.

WHAT HANZ DECIDED. The v2 job types are the live four (polish, epoxy, combo, gyp). Seal and Leveling are options
on a bid and are never intake job types. A v2 bid stays a test copy until Kyle signs off each type, so a type that
is not priced yet is shown and DISABLED with a plain note, and Polish is the one that is ready. Which types are
ready is `ready` in js/work-types.js: a later phase enables one by flipping that data, not by editing a page.

WHAT IS PROVEN, BY EXECUTION. The real js/polish-intake.js runs against a DOM stub (tests/js/polish-intake-harness.js)
with the real js/work-types.js, js/intake-scope.js and js/county-picker.js. Nothing below greps the page for a word
and calls it proof, apart from the one check that the old county copy's functions are gone.

  * The choice is the vocabulary's: the four job types in its order, Polish checked, the other three disabled, and a
    vocabulary with Epoxy marked ready (the REAL file, edited by one flag) shows Epoxy enabled and saves it.
  * A disabled type cannot be picked by the mouse or by a click the keyboard makes, and nothing is saved.
  * A saved draft opens unchanged: no job type, or one v2 cannot price, reads as Polish, the saved county is shown,
    and opening writes nothing. A save never adds a quantity the bid did not already hold.
  * The county control is js/county-picker.js. fixtures/county_picker_golden.json was captured from the v2 intake's
    OWN copy before that copy was deleted: every row the box offers for a sample of searches and, for each row, the
    four keys a click writes, the note with Remodel tax off and on, and what the engine charges. The shared control
    must reproduce all of it.

Each mutation at the bottom breaks a scratch copy of one file in the way a careless change would, and the check it
belongs to must go red.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, run_node

TESTS = pathlib.Path(__file__).resolve().parent
BACKEND = TESTS.parents[1] / "backend"
HARNESS = TESTS / "js" / "polish-intake-harness.js"
GOLDEN = TESTS / "fixtures" / "county_picker_golden.json"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

NOTE_TEXT = "Epoxy, Combo and Gyp pricing in v2 is coming. Use the live estimate for now."
PAGE_FILES = ["polish-intake.html", "js/polish-intake.js", "js/bid-model.js", "js/work-types.js",
              "js/polish-sandbox.js", "js/intake-scope.js", "js/county-picker.js", "shared.js"]


def _run(frontend=FRONTEND):
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    return _run()


def _node(code):
    proc = subprocess.run(["node", "-e", code], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# ── the choice is the vocabulary's ──────────────────────────────────────────────────────────────

@needs_node
def test_the_four_job_types_are_drawn_from_the_vocabulary_in_its_order(ran):
    j = ran["jobTypes"]
    assert [r["value"] for r in j["radios"]] == [v["key"] for v in j["vocabulary"]] \
        == ["epoxy", "polish", "combo", "gyp"]
    assert [r["label"] for r in j["radios"]] == [v["label"] for v in j["vocabulary"]]
    # Seal and Leveling are options on a bid. They are never a job type, so they are never a choice.
    assert not {"seal", "leveling"} & {r["value"] for r in j["radios"]}


@needs_node
def test_polish_is_selected_and_the_other_three_are_disabled_with_a_plain_note(ran):
    j = ran["jobTypes"]
    state = {r["value"]: (r["checked"], r["disabled"]) for r in j["radios"]}
    assert state == {"epoxy": (False, True), "polish": (True, False),
                     "combo": (False, True), "gyp": (False, True)}, state
    assert j["current"] == "polish"
    assert j["note"] == {"text": NOTE_TEXT, "hidden": False}, j["note"]
    assert "—" not in NOTE_TEXT and "–" not in NOTE_TEXT, "plain words: no dashes"


@needs_node
def test_a_type_the_vocabulary_marks_ready_is_enabled_and_saved_with_no_page_change(ran):
    """The page is the same file; only the vocabulary differs, by one flag. Mutation: hard-code Polish as the one
    pickable type (see the mutations below) and this goes red."""
    f = ran["jobTypes"]["fakeReady"]
    assert {r["value"]: r["disabled"] for r in f["radios"]} == {
        "epoxy": False, "polish": False, "combo": True, "gyp": True}
    assert f["note"]["text"] == "Combo and Gyp pricing in v2 is coming. Use the live estimate for now."
    assert f["before"] == "polish"
    assert f["afterPick"]["current"] == "epoxy" and f["afterPick"]["armed"] == 1
    assert [r["value"] for r in f["afterPick"]["radios"] if r["checked"]] == ["epoxy"]
    assert f["afterPick"]["savedWorkType"] == "epoxy"
    assert f["comboStillDisabled"] == "epoxy", "a type that is still not ready was picked"


@needs_node
def test_a_disabled_type_cannot_be_picked_by_click_or_keyboard(ran):
    d = ran["jobTypes"]["disabledClicks"]
    for key, seen in d["attempts"].items():
        assert seen == {"current": "polish", "armed": 0, "saves": 0}, (key, seen)
    assert d["markupUnchanged"] is True
    # The browser half: the radio is disabled, so a real browser will not focus it, click it or reach it with
    # the arrow keys. The page's own refusal above is for a click that arrives some other way.
    assert all(r["disabled"] for r in ran["jobTypes"]["radios"] if r["value"] != "polish")


# ── saved drafts open unchanged ─────────────────────────────────────────────────────────────────

@needs_node
def test_a_saved_draft_with_no_job_type_or_one_v2_cannot_price_opens_as_polish(ran):
    s = ran["jobTypes"]["savedDrafts"]
    for name in ("absent", "combo"):
        assert s[name]["current"] == "polish" and s[name]["checked"] == ["polish"], (name, s[name])
        assert s[name]["savedOnOpen"] == 0, "opening a saved draft wrote to it: " + name
    assert s["combo"]["armedOnOpen"] == 0
    assert s["absent"]["saved"] == "polish", "a draft with no job type is saved as Polish"


@needs_node
def test_a_saved_county_is_still_shown_when_the_draft_opens(ran):
    s = ran["jobTypes"]["savedDrafts"]
    assert s["absent"]["county"] == s["combo"]["county"] == "Wyandotte County, KS"


@needs_node
def test_a_save_never_adds_a_quantity_the_bid_did_not_hold(ran):
    h = ran["jobTypes"]["hiddenQuantities"]
    assert h["freshKeys"] == [], "a polish save added quantities nobody typed: %r" % h["freshKeys"]
    assert h["heldKeys"] == ["cove_1_lf", "system_1_sf"], h["heldKeys"]
    assert h["heldValues"] == {"system_1_sf": "750", "cove_1_lf": "40"}, "a quantity the draft held was changed"


# ── the module that draws the choice ────────────────────────────────────────────────────────────

@needs_node
def test_the_module_reads_the_vocabulary_for_what_is_pickable_and_what_a_draft_opens_as():
    got = _node("""
      const S = require(%s);
      console.log(JSON.stringify({
        pick: ["polish", "epoxy", "combo", "gyp", "seal", "leveling", "", null, undefined].map((k) => S.isPickable(k)),
        open: [undefined, null, "", "polish", "epoxy", "combo", "gyp", "seal", "nonsense"].map((k) => S.chosenJobType(k)),
        hidden: S.hiddenNames("polish"),
        gypHidden: S.hiddenNames("gyp"),
        throws: (() => { try { S.hiddenNames(""); return false; } catch (e) { return true; } })(),
      }));
    """ % json.dumps(str(FRONTEND / "js" / "intake-scope.js")))
    assert got["pick"] == [True, False, False, False, False, False, False, False, False]
    assert got["open"] == ["polish"] * 9
    assert got["hidden"] == ["system_1_sf", "cove_1_lf", "system_2_sf", "cove_2_lf",
                             "gyp_soft_sf", "gyp_hard_sf", "gyp_corridor_sf"]
    assert got["gypHidden"] == ["system_1_sf", "polish_sf", "cove_1_lf", "system_2_sf", "polish_2_sf", "cove_2_lf"]
    assert got["throws"] is True, "a missing job type is a throw, not a guess"


# ── the county control is the shared one ────────────────────────────────────────────────────────

@needs_node
def test_the_shared_county_control_gives_the_old_copys_rows_keys_notes_and_rates(ran):
    """The golden was captured from this page's own copy before it was deleted. Equal means the same county list,
    the same rows and rates, the same four saved keys (`county`, `county_tax_rate`, `county_remodel_rate`,
    `county_notes`), the same note and the same engine rate for every county in the sample."""
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    got = json.loads(json.dumps(ran["countyGolden"]))
    assert len(got) == len(golden)
    for want, have in zip(golden, got):
        assert have == want, "county sample %r (remodel on: %s) differs from the old copy" % (
            want["query"], want["remodelOn"])
    # Not vacuous: the sample holds Kansas and Missouri rows, cities and counties, and a rate that is null.
    picks = [p for g in golden for p in g["picks"]]
    assert len(picks) >= 40
    assert any(p["keys"]["county_remodel_rate"] == 0.07975 for p in picks)
    assert any(p["keys"]["county_remodel_rate"] is None for p in picks)
    assert any(p["keys"]["county"].endswith(", MO") for p in picks)
    assert any("County," not in p["keys"]["county"] for p in picks), "no city row in the sample"


def test_the_old_copy_of_the_county_picker_is_gone_from_the_page():
    src = (FRONTEND / "js" / "polish-intake.js").read_text(encoding="utf-8")
    for name in ("loadCounties", "countyStateOf", "countyRowRate", "countyRowLabel", "filterCounties",
                 "closeCountyResults", "renderCountyResults", "paintCountyHighlight", "pickCounty", "clearCounty",
                 "countyNoteText", "hydrateCounty", "onCountyInput", "onCountyKeydown"):
        assert not re.search(r"function\s+" + re.escape(name) + r"\s*\(", src), name + " is back"
    assert "TWCounty.mount" in src, "the page does not mount the shared control"
    html = (FRONTEND / "polish-intake.html").read_text(encoding="utf-8")
    assert html.index("/js/county-picker.js") < html.index("/js/polish-intake.js"), (
        "the page script mounts the control as it boots, so the control loads first")
    assert html.index("/js/work-types.js") < html.index("/js/intake-scope.js") < html.index("/js/polish-intake.js")
    assert len(src.splitlines()) < 760, "the page grew back toward its old size"


# ── the checks go red when the code changes ─────────────────────────────────────────────────────

MUTATIONS = {
    "the shared control writes the wrong remodel rate": (
        "js/county-picker.js", "county_remodel_rate: c.remodel_rate == null ? null : c.remodel_rate,",
        "county_remodel_rate: 0.1,",
        lambda r: json.loads(json.dumps(r["countyGolden"])) != json.loads(GOLDEN.read_text(encoding="utf-8"))),
    "the shared control words a row differently": (
        "js/county-picker.js", ': "remodel labor exempt";', ': "no remodel tax";',
        lambda r: json.loads(json.dumps(r["countyGolden"])) != json.loads(GOLDEN.read_text(encoding="utf-8"))),
    "the page lets a script pick a type that is not ready": (
        "js/polish-intake.js", "if (!S.isPickable(key) || key === JOB) return;", "if (!T.isJobType(key) || key === JOB) return;",
        lambda r: r["jobTypes"]["disabledClicks"]["attempts"]["epoxy"]["current"] != "polish"),
    "the radios are not disabled": (
        "js/intake-scope.js", """(c.ready ? "" : ' disabled title="' + esc(note) + '"')""", '""',
        lambda r: not all(x["disabled"] for x in r["jobTypes"]["radios"] if x["value"] != "polish")),
    "the page hard-codes polish as the one pickable type": (
        "js/intake-scope.js", "return workTypes.isJobType(key) && workTypes.jobType(key).ready === true;",
        'return key === "polish";',
        lambda r: r["jobTypes"]["fakeReady"]["afterPick"]["current"] != "epoxy"),
    "a draft's own job type is trusted without asking the vocabulary": (
        "js/polish-intake.js", "JOB = S.chosenJobType(state.work_type);", 'JOB = state.work_type || "polish";',
        lambda r: r["jobTypes"]["savedDrafts"]["combo"]["current"] != "polish"),
    "a save adds the quantities the job type hides": (
        "js/polish-intake.js", "if (!Object.prototype.hasOwnProperty.call(cur, name)) delete values[name];", ";",
        lambda r: r["jobTypes"]["hiddenQuantities"]["freshKeys"] != []),
    "opening a draft saves it": (
        "js/polish-intake.js", "    JOB = S.chosenJobType(state.work_type);", "    JOB = S.chosenJobType(state.work_type); saveSoon();",
        lambda r: r["jobTypes"]["savedOnOpen"] != 0 or r["jobTypes"]["armedOnOpen"] != 0
        or r["jobTypes"]["savedDrafts"]["combo"]["armedOnOpen"] != 0),
}


@needs_node
@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_the_checks_go_red_when_the_code_changes(tmp_path, name):
    rel, old, new, noticed = MUTATIONS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, PAGE_FILES)
    # the harness reads the county table out of the backend module that serves it
    (tmp_path / "backend").mkdir(exist_ok=True)
    shutil.copyfile(BACKEND / "reference_tax.py", tmp_path / "backend" / "reference_tax.py")
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the mutation crashed the harness instead of changing an answer: " + proc.stderr
    assert noticed(last_json_line(proc.stdout)), "the checks did not notice: " + name
