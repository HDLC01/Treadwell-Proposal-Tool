"""A pricing option carries its OWN long description, and it prints as the option line.

Hanz: options "would want to have it where you could put a long description instead of just the
title of the worksheet". Until now an option printed ONE line, "<amount> – <system name> as described
above <tax phrase>", and the system name is the tab's system dropdown ("Treadwell micro Flake Double
Broadcast"): two epoxy tabs on the same system read identically but for the price. Kyle words his
option rows as "$4,200 – Add for onsite/in place mockup, if required."

THE FIELD. state.tab_opts[<tab>].desc, typed in the Proposal step's Pricing options sidebar (a
"Description" box above Notes). It rides the draft blob the option's other settings already ride,
becomes rooms[].custom_desc, and prints in place of the system name -- WITHOUT "as described above",
a phrase that only makes sense after a system name:

    total      "$4,200 – <desc> <tax phrase>"           (+ " — note1; note2")
    add        "Add $8,292 – <desc>"                    (+ notes)
    deduct     "Deduct ($3,200) – VE for <desc>, in lieu of <base>."   (+ notes)

An empty description is exactly the line this has always printed. A retyped line
(price_overrides.lines2["option:<tab>"]) still wins over it, as it always has.

WHAT IS PROVEN HERE, and how it is run rather than read:
  * the document (the real `_generate`, both copies of the text box) on Direct epoxy, Gyp and GC
    resinous, in total, add and deduct modes, with and without notes;
  * the editor's preview of the same lines (price-bullets-harness.js runs the page's own
    renderOptionLinesPreview over the real template's blocks) -- the editor and the document read the
    same words, in every mode; and the editor now shows an Add/Deduct line's notes, which the
    document always printed (js/price-bullets-harness.js; the old preview left them off);
  * an empty description is byte-identical to a payload that never heard of the field;
  * the two mkRoom copies -- proposal-review.js rebuildPricing and estimate-review.js
    snapshotLumpSumsToState -- are EXECUTED over the same tabs and agree (option-desc-harness.js);
  * the sidebar field, run through the page's own handlers (price-lines-harness.js): placeholder,
    typing, the save, the reload, the cap, and that the box he is typing in is never rebuilt (the
    page repaints only the preview, so the caret and the focus stay);
  * the length cap, on the page and in the document;
  * a 400-character description in the GC PRICE box does not clip Kyle's own rows (or the fit report
    says at_floor, which is the editor's overflow warning).

THE PORTAL (read, not edited -- treadwell-portal/backend/proposals.py pricing_options): it lists each
room as label = rooms[].name (the tab's name, the key a customer's selection is matched on, so it is
left alone) and a grey line under it = rooms[].system_desc. mkRoom sets system_desc and option_desc to
the description when there is one, so the portal's grey line reads the same words the proposal prints.
test_the_room_carries_the_words_the_portal_shows pins the field it reads.
"""
import copy
import json
import pathlib
import re
import shutil
import subprocess

import pytest
from docx import Document
from docx.oxml.ns import qn
import io
from starlette.requests import Request

import main
import proposal_writer as pw
import test_gc_option_lines as gc

BACKEND = pathlib.Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend"
JS = BACKEND / "tests" / "js"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

WORDS = "Add for onsite/in place mockup, if required."
LONG_WORDS = ("Treadwell MACRO Flake Double Broadcast with a metallic pigment upgrade, two extra "
              "coats of polyaspartic topcoat and a 6 inch integral cove base, all in the colour "
              "Kyle approved on site, to be scheduled ahead of the main pour. ") * 3   # > 400
NOTES = ["Includes 2 mobilizations", "Colour: Gray Blend only"]
BASE = gc.BASE

# (id, mode name, total, price_mode)
MODES = {
    "total": ("Copy1", "EPOXY 2", 36157, "total"),
    "add": ("Copy3", "UPGRADE", 36157, "deduct"),       # dearer than the 27,865 base: an Add
    "deduct": ("Copy2", "GRIND", 24665, "deduct"),      # cheaper: a Deduct
}


def _room(mode, *, custom=None, notes=(), old_desc="Treadwell MACRO Flake", key=True, own=False):
    """An option room as rebuildPricing makes it: with a description the page sets system_desc and
    option_desc to it and adds custom_desc; without one it is the room this has always been (and,
    with key=False, a room that never heard of custom_desc at all). `own=True`: ONLY custom_desc
    carries the words, system_desc and option_desc stay the system name -- the document must read the
    field itself."""
    rid, name, total, price_mode = MODES[mode]
    r = gc._room(rid, name, total, desc=old_desc, mode=price_mode, notes=notes)
    if custom and not own:
        r["system_desc"] = r["option_desc"] = custom
    if key:
        r["custom_desc"] = custom or ""
    return r


def _tail(notes):
    return " — " + "; ".join(notes) if notes else ""


def _line(mode, words, notes=()):
    """The line the option prints with the estimator's own words in it."""
    if mode == "total":
        return f"$36,157 – {words} (tax exempt)" + _tail(notes)
    if mode == "add":
        return f"Add $8,292 – {words}" + _tail(notes)
    return f"Deduct ($3,200) – VE for {words}, in lieu of {gc.BASE_DESC}." + _tail(notes)


def _old_line(mode, notes=(), old_desc="Treadwell MACRO Flake"):
    """The line the same option printed before the field existed (the system name)."""
    if mode == "total":
        return f"$36,157 – {old_desc} as described above (tax exempt)" + _tail(notes)
    if mode == "add":
        return f"Add $8,292 – {old_desc}" + _tail(notes)
    return f"Deduct ($3,200) – VE for {old_desc}, in lieu of {gc.BASE_DESC}." + _tail(notes)


CONFIGS = [("epoxy", "Direct"), ("gyp", "Direct"), ("epoxy", "GC")]
CASES = [pytest.param(wt, aud, mode, bool(notes), id=f"{wt}-{aud}-{mode}{'-notes' if notes else ''}")
         for wt, aud in CONFIGS for mode in MODES for notes in ((), NOTES)]


def _texts(content):
    d = Document(io.BytesIO(content))
    return [pw._own_text(p) for p in d.element.body.iter(qn("w:p"))]


# ── 1. the document ──────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("wt,aud,mode,with_notes", CASES)
def test_the_document_prints_the_description_as_the_option_line(wt, aud, mode, with_notes):
    """Direct epoxy, Gyp and GC resinous; total, add and deduct; with and without notes. The line
    carries the estimator's words in place of the system name -- no "as described above" -- and
    appears in EVERY copy of the PRICE box the template has (the mc:Choice one Word reads and the
    mc:Fallback one LibreOffice renders)."""
    notes = NOTES if with_notes else ()
    new = _line(mode, WORDS, notes)
    old = _old_line(mode, notes)
    got = _texts(gc._generate(wt, aud, rooms=[BASE, _room(mode, custom=WORDS, notes=notes)]))
    was = _texts(gc._generate(wt, aud, rooms=[BASE, _room(mode, notes=notes)]))
    assert new in got, f"{wt}/{aud}/{mode}: {new!r} not printed; got {[t for t in got if '$' in t][:8]}"
    assert old not in got, "the system-name line printed beside the description"
    # What the system name printed before is what the description prints now: as many copies of it.
    assert old in was and got.count(new) == was.count(old) >= 1, (got.count(new), was.count(old))
    assert "as described above" not in new


@pytest.mark.parametrize("wt,aud,mode,with_notes", CASES)
def test_the_document_reads_custom_desc_on_its_own(wt, aud, mode, with_notes):
    """The document does not lean on the page also overwriting system_desc / option_desc: a room
    whose ONLY change is custom_desc prints the words, in every mode, on every template."""
    notes = NOTES if with_notes else ()
    got = _texts(gc._generate(wt, aud, rooms=[BASE, _room(mode, custom=WORDS, notes=notes, own=True)]))
    assert _line(mode, WORDS, notes) in got
    assert _old_line(mode, notes) not in got


@pytest.mark.parametrize("wt,aud", CONFIGS)
def test_an_empty_description_is_byte_identical_to_today(wt, aud):
    """The description is optional and its absence changes nothing. The same bid generated three
    ways -- a room that never heard of custom_desc (the draft of a project saved before this
    shipped), one with custom_desc "", one holding only whitespace -- is the same .docx, part for
    part, and prints the lines the system name has always printed."""
    def parts(rooms):
        import zipfile
        z = zipfile.ZipFile(io.BytesIO(gc._generate(wt, aud, rooms=rooms)))
        return {n: z.read(n) for n in z.namelist()}
    rooms = lambda **k: [BASE] + [_room(m, notes=NOTES, **k) for m in MODES]
    legacy = parts(rooms(key=False))
    empty = parts(rooms())
    assert sorted(empty) == sorted(legacy)
    for n in legacy:
        assert empty[n] == legacy[n], f"{n} differs"
    blank = []
    for m in MODES:
        r = _room(m, notes=NOTES)
        r["custom_desc"] = "  \n\t "
        blank.append(r)
    spaced = parts([BASE] + blank)
    for n in legacy:
        assert spaced[n] == legacy[n], f"{n} differs for a whitespace-only description"
    got = _texts(gc._generate(wt, aud, rooms=[BASE] + [_room(m, notes=NOTES) for m in MODES]))
    for m in MODES:
        assert _old_line(m, NOTES) in got, (wt, aud, m)


def test_a_retyped_option_line_still_wins_over_the_description():
    """price_overrides.lines2["option:<tab>"] is the estimator re-wording the whole line in the
    editor; it has always outranked what the tool would write, and still does."""
    pov = {"lines2": {"option:Copy1": "⟦amount⟧ – My reworded option ⟦tax⟧"}}
    got = _texts(gc._generate("epoxy", "Direct", price_overrides=pov,
                              rooms=[BASE, _room("total", custom=WORDS)]))
    assert "$36,157 – My reworded option (tax exempt)" in got
    assert not any(WORDS in t for t in got)


# ── 2. the cap and the clean-up, in the document ─────────────────────────────────────────────────
def test_the_document_caps_and_tidies_a_description():
    """main._option_custom_desc: one line, at most 400 characters, control characters gone. The page
    does the same before it sends (and its box stops at 400); the document does not trust that."""
    assert main.OPTION_DESC_MAX == 400
    assert main._option_custom_desc(None) == "" and main._option_custom_desc("   \n ") == ""
    assert main._option_custom_desc("a\n\n  b\tc ") == "a b c"
    assert main._option_custom_desc("bell\x07and null\x00gone") == "bell and null gone"
    assert len(main._option_custom_desc("x" * 900)) == 400
    got = _texts(gc._generate("epoxy", "Direct", rooms=[BASE, _room("total", custom=LONG_WORDS)]))
    capped = " ".join(LONG_WORDS.split())[:400].strip()
    assert f"$36,157 – {capped} (tax exempt)" in got
    assert not any(LONG_WORDS.strip() in t for t in got)


def test_a_description_with_control_characters_still_builds_a_document():
    """A NUL or a bell is not legal in a .docx. Left in, it would fail the whole generate."""
    got = _texts(gc._generate("epoxy", "Direct", rooms=[BASE, _room("total", custom="Mock\x00up\x07 x")]))
    assert "$36,157 – Mock up x (tax exempt)" in got


# ── 3. the editor, run: the same words in every mode ─────────────────────────────────────────────
HARNESS = JS / "price-bullets-harness.js"


def _tj(wt, aud):
    req = Request({"type": "http", "method": "GET", "path": "/api/proposal-template", "headers": [],
                   "query_string": b""})
    return json.loads(main.api_proposal_template(req, work_type=wt, audience=aud).body)


def _ed_case(wt, aud, rooms, name):
    tj = _tj(wt, aud)
    box = next(b["txbx"] for b in tj["blocks"] if b.get("txbx") is not None
               and "base_bid_formatted" in (b["text"] or ""))
    st = gc._editor_state(wt, rooms)
    st["audience"] = aud
    return {"name": name, "work_type": wt, "audience": aud,
            "blocks": [b for b in tj["blocks"] if b.get("txbx") == box],
            "options_heading_ids": tj.get("options_heading_ids") or [],
            "price_lines_anchor": tj.get("price_lines_anchor"), "state": st, "actions": []}


@pytest.fixture(scope="module")
def editor_runs():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    cases, order = [], []
    for wt, aud in CONFIGS:
        for mode in MODES:
            for notes in ((), NOTES):
                for custom in (WORDS, None):
                    rooms = [BASE, _room(mode, custom=custom, notes=notes)]
                    cases.append(_ed_case(wt, aud, rooms, f"{wt}/{aud}/{mode}/{bool(notes)}/{bool(custom)}"))
                    order.append((wt, aud, mode, bool(notes), bool(custom)))
    p = subprocess.run(["node", str(HARNESS), str(FRONTEND)], input=json.dumps(cases),
                       capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, "the harness itself failed:\n" + p.stderr
    return dict(zip(order, json.loads(p.stdout)))


def _editor_option_line(run, rid):
    mine = [ln["text"] for ln in run["lines"] if ln.get("key") == "option:" + rid]
    assert len(mine) == 1, mine
    return mine[0]


@needs_node
@pytest.mark.parametrize("wt,aud,mode,with_notes", CASES)
def test_the_editor_shows_the_same_line_the_document_prints(editor_runs, wt, aud, mode, with_notes):
    """The page's own renderOptionLinesPreview, over the real template: with a description the line
    is the description (no "as described above"), without one it is today's line -- and in every
    mode the editor's line is the document's, notes included. (An Add/Deduct line's notes were
    printed by the document and left off the preview; the notes cases are that parity.)"""
    notes = NOTES if with_notes else ()
    rid = MODES[mode][0]
    with_desc = _editor_option_line(editor_runs[(wt, aud, mode, with_notes, True)], rid)
    without = _editor_option_line(editor_runs[(wt, aud, mode, with_notes, False)], rid)
    assert with_desc == _line(mode, WORDS, notes)
    assert without == _old_line(mode, notes)
    doc = _texts(gc._generate(wt, aud, rooms=[BASE, _room(mode, custom=WORDS, notes=notes)]))
    assert with_desc in doc


# ── 4. the two mkRoom copies, EXECUTED ───────────────────────────────────────────────────────────
def _tab(**kw):
    t = {"id": "Copy1", "name": "EPOXY 2", "total": 36157, "sales_tax": 400, "remodel": 0,
         "system_desc": "Treadwell micro Flake Double Broadcast", "notes_auto": ["Auto note"],
         "taxable": False, "remodel_on": False}
    t.update(kw)
    return t


SCENARIOS = [
    {"name": "no description", "tab": _tab(), "opt": {"is_option": True, "show": True}, "base_total": 27865},
    {"name": "no opt entry at all", "tab": _tab(), "opt": None, "base_total": 27865},
    {"name": "a description", "tab": _tab(), "opt": {"is_option": True, "desc": WORDS}, "base_total": 27865},
    {"name": "untidy", "tab": _tab(), "opt": {"is_option": True, "desc": "  one \n\n two\t three  "},
     "base_total": 27865},
    {"name": "too long", "tab": _tab(), "opt": {"is_option": True, "desc": LONG_WORDS}, "base_total": 27865},
    {"name": "whitespace only", "tab": _tab(), "opt": {"is_option": True, "desc": " \n "}, "base_total": 27865},
    {"name": "deduct mode", "tab": _tab(), "base_total": 27865,
     "opt": {"is_option": True, "desc": WORDS, "price_mode": "deduct"}},
    {"name": "tab with no system", "tab": _tab(system_desc=""), "base_total": 27865,
     "opt": {"is_option": True, "desc": WORDS}},
    {"name": "tab with no system and no description", "tab": _tab(system_desc=""), "base_total": 27865,
     "opt": {"is_option": True}},
    {"name": "manual notes ride along", "tab": _tab(), "base_total": 27865, "notes_manual": NOTES,
     "opt": {"is_option": True, "desc": WORDS}},
    {"name": "the base row ignores one", "tab": _tab(id="Epoxy", name="Epoxy"), "is_base": True,
     "base_total": 27865, "opt": {"desc": "SHOULD NOT SHOW"}},
]


@pytest.fixture(scope="module")
def mkrooms():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    p = subprocess.run(["node", str(JS / "option-desc-harness.js"), str(FRONTEND)],
                       input=json.dumps(SCENARIOS), capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, "the harness itself failed:\n" + p.stderr
    return {r["name"]: r for r in json.loads(p.stdout)}


@needs_node
@pytest.mark.parametrize("sc", SCENARIOS, ids=[s["name"] for s in SCENARIOS])
def test_the_two_mkroom_copies_agree(mkrooms, sc):
    """proposal-review.js rebuildPricing.mkRoom and estimate-review.js snapshotLumpSumsToState.mkRoom,
    run over the same tab: the same room, field for field. They are two builds of one thing; the
    Estimate step saves the rooms the Proposal step then rebuilds, and the words must not depend on
    which page saved last."""
    r = mkrooms[sc["name"]]
    assert r["proposal"] == r["estimate"], {k: (r["proposal"].get(k), r["estimate"].get(k))
                                            for k in set(r["proposal"]) | set(r["estimate"])
                                            if r["proposal"].get(k) != r["estimate"].get(k)}


@needs_node
def test_the_room_carries_the_words_the_portal_shows(mkrooms):
    """The portal (treadwell-portal/backend/proposals.py pricing_options, not edited) shows each room's
    `name` as the option's title and `system_desc` as the grey line under it. With a description the
    room's system_desc IS the description, so the customer reads the proposal's words; its `name` (the
    key the customer's selection is matched on) is untouched; without one it is what it always was."""
    for copy_ in ("proposal", "estimate"):
        r = mkrooms["a description"][copy_]
        assert r["name"] == "EPOXY 2" and r["id"] == "Copy1"
        assert r["system_desc"] == r["option_desc"] == r["custom_desc"] == WORDS
        o = mkrooms["no description"][copy_]
        assert o["system_desc"] == o["option_desc"] == "Treadwell micro Flake Double Broadcast"
        assert o["custom_desc"] == ""
        assert mkrooms["no opt entry at all"][copy_] == o
        n = mkrooms["tab with no system and no description"][copy_]
        assert n["system_desc"] == n["option_desc"] == "EPOXY 2"      # the tab's name, as ever
        assert mkrooms["manual notes ride along"][copy_]["notes_manual"] == NOTES


@needs_node
def test_the_room_cleans_and_caps_the_description_and_the_base_has_none(mkrooms):
    for copy_ in ("proposal", "estimate"):
        assert mkrooms["untidy"][copy_]["custom_desc"] == "one two three"
        assert mkrooms["too long"][copy_]["custom_desc"] == " ".join(LONG_WORDS.split())[:400].strip()
        assert len(mkrooms["too long"][copy_]["custom_desc"]) <= 400
        assert mkrooms["whitespace only"][copy_]["custom_desc"] == ""
        assert mkrooms["whitespace only"][copy_]["system_desc"] == "Treadwell micro Flake Double Broadcast"
        assert mkrooms["deduct mode"][copy_]["price_mode"] == "deduct"
        assert mkrooms["deduct mode"][copy_]["custom_desc"] == WORDS
        base = mkrooms["the base row ignores one"][copy_]
        assert base["custom_desc"] == "" and base["is_base"] is True
        assert "SHOULD NOT SHOW" not in json.dumps(base)


@needs_node
def test_a_room_built_by_either_page_prints_the_description_in_the_document(mkrooms):
    """Not just the same fields: the room each page builds, handed to the real generate path, prints
    the words. (The base is the Proposal step's own.)"""
    for copy_ in ("proposal", "estimate"):
        room = mkrooms["a description"][copy_]
        room["base_total"] = gc.BASE_TOTAL
        got = _texts(gc._generate("epoxy", "Direct", rooms=[BASE, room]))
        assert any(t.startswith("$36,157 – " + WORDS) for t in got), copy_
        assert not any("as described above" in t and "Treadwell micro" in t for t in got)


# ── 5. the sidebar field, run through the page's own handlers ────────────────────────────────────
@pytest.fixture(scope="module")
def sidebar():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    p = subprocess.run(["node", str(JS / "price-lines-harness.js"), str(FRONTEND)], capture_output=True,
                       text=True, encoding="utf-8", timeout=120)
    assert p.returncode == 0, "the harness itself failed:\n" + p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])["optionDesc"]


SYSTEM = 'Treadwell 3/16" Urethne Cement With Shop Floor'
DASH = "$15,149 – "
TAXED = " (material sales tax INCLUDED)"


@needs_node
def test_the_sidebar_offers_a_description_above_notes_and_shows_what_prints_when_empty(sidebar):
    """A "Description" box in each option's row, above Notes, with the hint "Prints as the option
    line." and, as its placeholder, what the option prints while it is empty: the tab's system name."""
    e = sidebar["empty"]
    assert e["box"]["placeholder"] == SYSTEM and e["box"]["text"] == "" and e["box"]["maxlength"] == "400"
    assert e["hint"] is True
    assert sidebar["order"] == ["room-desc", "room-notes"]
    assert e["room"]["custom_desc"] == "" and e["room"]["system_desc"] == SYSTEM
    assert e["line"] == DASH + SYSTEM + " as described above" + TAXED


@needs_node
def test_typing_a_description_updates_the_room_the_preview_and_the_save(sidebar):
    t = sidebar["typed"]
    assert t["room"]["custom_desc"] == WORDS == t["room"]["system_desc"] == t["room"]["option_desc"]
    assert t["line"] == DASH + WORDS + TAXED              # the preview moved with the keystroke
    assert t["opt"]["desc"] == WORDS                      # the draft's own field
    assert t["saved"]["desc"] == WORDS                    # ...reaches the save the page makes
    assert t["savedRoom"]["custom_desc"] == WORDS         # ...and so do the rooms the portal reads


@needs_node
def test_focus_is_kept_while_typing(sidebar):
    """THE KNOWN TRAP: a re-render on input steals the focus just given. Typing must repaint only
    the preview: the textarea he is in is the same node, still attached, and the panel's markup was
    never rewritten -- through one edit and through a keystroke at a time."""
    t = sidebar["typed"]
    assert t["sameRow"] and t["sameBox"] and t["attached"] and t["panelRewritten"] is False
    assert sidebar["keystrokes"] == {"same": True, "panelRewritten": False}


@needs_node
def test_the_description_round_trips_through_save_and_reload(sidebar):
    r = sidebar["reload"]
    assert r["box"]["text"] == WORDS                      # the box opens holding it
    assert r["room"]["custom_desc"] == WORDS and r["line"] == DASH + WORDS + TAXED
    o = sidebar["opens"]
    assert o["box"]["text"] == "Kyle's own words" and o["line"] == DASH + "Kyle's own words" + TAXED


@needs_node
def test_the_sidebar_caps_and_tidies_what_is_typed_and_clearing_it_restores_the_system_name(sidebar):
    assert sidebar["long"]["stored"] == 400 and sidebar["long"]["room"] == 400
    assert sidebar["long"]["line"] == DASH + "x" * 400 + TAXED
    assert sidebar["newline"]["room"] == "first line second line"
    assert sidebar["newline"]["line"] == DASH + "first line second line" + TAXED
    for k in ("blank", "cleared"):
        assert sidebar[k]["room"]["custom_desc"] == ""
        assert sidebar[k]["line"] == DASH + SYSTEM + " as described above" + TAXED


@needs_node
def test_in_add_deduct_mode_the_sidebar_preview_uses_the_description_and_shows_the_notes(sidebar):
    """Add/Deduct through the sidebar's own Price-as select, then a note typed: the editor's line is
    the Add line with the description, and the notes follow it as the document prints them."""
    assert sidebar["addMode"] == {"room": "deduct", "line": "Add $7,702 – Upgrade to a metallic pigment"}
    assert sidebar["addNotes"] == "Add $7,702 – Upgrade to a metallic pigment — Colour: Gray Blend only"


# ── 6. a long description in the GC PRICE box does not clip Kyle's rows ──────────────────────────
GC_FILES = [("epoxy", gc.RESINOUS), ("polish", gc.POLISH), ("sealer", gc.SEALER), ("combo", gc.RESINOUS)]


def _long_rooms(n):
    out = [BASE]
    for i in range(1, n + 1):
        r = gc._room(f"Copy{i}", f"OPTION {i}", 30000 + 1000 * i, desc="x", notes=NOTES)
        r["system_desc"] = r["option_desc"] = r["custom_desc"] = " ".join(LONG_WORDS.split())[:400].strip()
        out.append(r)
    return out


@pytest.mark.parametrize("wt,rel", GC_FILES, ids=[g[0] for g in GC_FILES])
@pytest.mark.parametrize("n", [1, 2, 3])
def test_a_long_description_in_the_gc_price_box_fits_or_the_report_says_it_cannot(wt, rel, n):
    """Four hundred characters is five lines of a 9pt row. The box shrinks to hold it (the same fit
    the system-name lines get): in the printed document it does not run past its frame, unless the
    fit report says at_floor -- the editor's overflow warning. Never both quiet and too tall."""
    extra = dict(rooms=_long_rooms(n))
    if wt == "combo":
        extra["combo_options"] = gc.COMBO_LINES
    report, content = gc._fit_and_docx(wt, **extra)
    d, tx, geo, i = gc._price_box(content)
    rec = report[i]
    assert rec["at_floor"] or not pw._bullets_overflow_when_loose(d, tx, geo, 1.0), (
        f"{wt}+{n} long descriptions: scale {rec['scale']} said it fits, at_floor False, "
        "but the printed box is taller than its frame")
    # Every long line is in the box, in both copies, whole.
    capped = " ".join(LONG_WORDS.split())[:400].strip()
    lines = [t for t in _texts(content) if t.startswith("$") and capped in t]
    assert len(lines) == 2 * n, (len(lines), n)


@pytest.mark.skipif(shutil.which("soffice") is None and shutil.which("libreoffice") is None,
                    reason="LibreOffice is not installed (it is in the Docker image)")
@pytest.mark.parametrize("wt,rel", GC_FILES, ids=[g[0] for g in GC_FILES])
@pytest.mark.parametrize("n", [1, 2, 3])
def test_every_row_of_kyles_box_prints_in_the_pdf_with_long_descriptions(wt, rel, n):
    """LibreOffice clips a text box's overflow without a word, so this renders the PDF: each of
    Kyle's own unit-price rows is on page 1 unless the fit report says the box is at its floor."""
    import pdf_writer
    extra = dict(rooms=_long_rooms(n))
    if wt == "combo":
        extra["combo_options"] = gc.COMBO_LINES
    report, content = gc._fit_and_docx(wt, **extra)
    _d, _tx, _geo, i = gc._price_box(content)
    missing = gc._missing_rows(pdf_writer.docx_to_pdf(content), rel)
    assert not missing or report[i]["at_floor"], (wt, n, missing, report[i])
