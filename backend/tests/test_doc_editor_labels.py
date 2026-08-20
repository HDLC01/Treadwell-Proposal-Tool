"""The last locked labels on the proposal page, and a text box that grows instead of clipping.

Kyle, 2026-08-19, on the proposal document editor:
    "Some of the labels are not editable why not make it like a word document??"
    "Everything on that page must be editable like a word doc"
    "instead of it being a textbox why not make it editable like a word document?"

WHAT WAS ACTUALLY LOCKED, measured against the template files rather than assumed. Every label
in every proposal template is real docx text — only the page frame, the rotated WORK/PRICE rail
captions and the logo are pictures. "Scope:", "Schedule:", "Exclusions:" and "Notes:" were
already inside contenteditable paragraphs. The genuinely locked ones were the three inside the
Direct epoxy template's `{{#system}}` region:

    {{system.prefix}}   {{system.name}}          ← "System:" / "Option N:", a COMPUTED token
    Texture:  {{system.texture}}                 ← static template text
    Area: ~{{system.sqft}} SF of epoxy flooring… ← static template text

The editor cannot make that region editable paragraph-by-paragraph: a `{{#block}}` region is
expanded once per priced system at generate time, so its paragraph ids stop describing anything
the estimator saw. `_apply_paragraph_overrides` refuses any id with `in_block` set for exactly
that reason. So the labels ride the row's own item dict instead, on the per-index
`system_overrides` channel the values already used — `prefix` (whitelisted in main.py) plus two
new keys, `texture_label` / `area_label`, consumed by `_apply_system_row_labels`.

THE ID SPACE IS UNTOUCHED, which is the load-bearing part. `iter_editable_blocks` yields the same
blocks in the same order as before, so every `paragraph_overrides` entry saved against a draft in
flight still lands on the paragraph it was captured from.

THE NUMBERING RULE. One system renders "System:", two or more render "Option 1:" / "Option 2:".
Renaming one row does NOT switch numbering off for the rows the estimator did not touch: each
row's computed label is a default for that index only. Asserted below for one system and for
three.

THE BOX GROWTH. Over-long content used to shrink its own font and then be clipped behind a
"Too long for this box" badge. It now grows into whatever room the page has, and that height goes
to the writer through the same `box_overrides` channel a manual drag uses. Room is real geometry,
not optimism: on Kyle's Direct epoxy sheet PRICE starts 2.7pt ABOVE the bottom of WORK, so WORK
cannot grow by a single point and keeps the clip — with a badge that now says so.

The browser half RUNS in `js/doc-editor-labels-harness.js` rather than being read: whether a
label came out as an editable island, and whether a box may get taller given where the other five
boxes are, are both properties of executed code. The precedent is expensive — on 2026-08-12 an
unbound identifier shipped with every source-text assertion green and took the production board
down.
"""
import io
import json
import pathlib
import re
import shutil
import subprocess

import docx
import pytest

import main
import proposal_writer as pw

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "doc-editor-labels-harness.js"
CSS = (FRONTEND / "styles.css").read_text(encoding="utf-8")

DIRECT_EPOXY = (pathlib.Path(__file__).resolve().parents[1] / "templates" / "Direct"
                / "XX.XX TREADWELL EPOXY PROPOSAL - New Direct.docx")

_A = "{%s}" % pw._A_NS
_WPS = "{%s}" % pw._WPS_NS
EMU_PER_PT = 12700.0


# ══ the fixture facts, re-derived from the template ═══════════════════════════
# Everything below is only meaningful if the template still looks like this. If Kyle re-authors
# it, these fail first and say what changed instead of leaving the feature quietly broken.
def _blocks(path):
    d = docx.Document(str(path))
    return [(i, in_block, text) for i, _k, _p, in_block, text, _t
            in pw.iter_editable_blocks(d)]


def test_the_system_labels_really_do_live_in_a_repeatable_region():
    """The whole reason a per-row channel had to exist. These three rows are inside
    `{{#system}}`, and `_apply_paragraph_overrides` skips anything with `in_block` set."""
    rows = {text: in_block for _i, in_block, text in _blocks(DIRECT_EPOXY)}
    assert rows.get("{{system.prefix}}   {{system.name}}") == "system"
    assert rows.get("Texture:  {{system.texture}}") == "system"
    assert rows.get("Area: ~{{system.sqft}} SF of epoxy flooring{{system.lf_clause}}") == "system"


def test_the_other_labels_were_already_editable():
    """Kyle said "some of the labels", and this is which. Scope/Schedule/Exclusions sit in
    ordinary paragraphs (`in_block is None`), so they were always reachable through
    paragraph_overrides — the fix for those was an affordance, not a channel."""
    free = [text for _i, in_block, text in _blocks(DIRECT_EPOXY)
            if in_block is None and re.match(r"^(Scope|Schedule|Exclusions):", text.strip())]
    assert len(free) >= 3, "the free-text labels moved into a block: %r" % (free,)


def test_the_block_id_space_is_unchanged_by_this_feature():
    """A saved paragraph_override is keyed by a POSITION in this walk. The label channel had to
    avoid adding, removing or reordering a block, or every override on every draft in flight
    would land on the wrong paragraph. The walk is index-dense and the region still starts where
    it did, so an id captured before this change still means the same paragraph."""
    ids = [i for i, _b, _t in _blocks(DIRECT_EPOXY)]
    assert ids == list(range(len(ids)))
    starts = [i for i, b, t in _blocks(DIRECT_EPOXY) if t.strip() == "{{#system}}"]
    assert starts == [110], (
        "the {{#system}} region moved to %r — every saved paragraph_override id after it is now "
        "pointing at a different paragraph" % (starts,))


# ══ the Python half: what actually reaches the customer's document ═══════════
BASE_VALUES = {"job_name": "Test Job", "texture": "Light Broadcast"}


def _fill(systems, **kw):
    return docx.Document(io.BytesIO(pw.fill_proposal(
        work_type="epoxy", audience="Direct", values=dict(BASE_VALUES), systems=systems, **kw)))


def _texts(d):
    return [p.text for p in pw._iter_all_paragraphs(d) if p.text.strip()]


def _row(name="Broadcast Quartz", **extra):
    row = {"prefix": "System:", "name": name, "texture": "Light Broadcast",
           "sqft": "5,000", "lf_clause": ""}
    row.update(extra)
    return row


def test_a_renamed_system_label_reaches_the_document():
    got = _texts(_fill([_row(prefix="Base System:")]))
    assert any(t.startswith("Base System:") for t in got), got
    assert not any(t.startswith("System:") for t in got)


def test_a_renamed_label_keeps_its_bold_run():
    """The label is a bold run and the value is not. Rewriting the text must not flatten that —
    Kyle's page design is the bold lead-in."""
    d = _fill([_row(prefix="Base System:", texture_label="Surface texture:")])
    rows = {}
    for p in pw._iter_all_paragraphs(d):
        if p.text.startswith(("Base System:", "Surface texture:")):
            rows[p.text.split(":")[0]] = [(r.text, r.bold) for r in p.runs if r.text]
    assert rows["Base System"][0] == ("Base System:", True)
    assert rows["Surface texture"][0] == ("Surface texture:", True)
    assert rows["Surface texture"][-1][1] is False, "the value ran into the label's bold"


def test_the_static_texture_and_area_labels_can_be_renamed():
    got = _texts(_fill([_row(texture_label="Surface texture:", area_label="Coverage:")]))
    assert "Surface texture:  Light Broadcast" in got, got
    assert any(t.startswith("Coverage: ~5,000 SF") for t in got), got
    assert not any(t.startswith("Texture:") for t in got)
    assert not any(t.startswith("Area:") for t in got)


def test_a_rename_is_per_row():
    """Row 2 keeps the template's wording and its own number. A label channel that leaked across
    rows would rewrite a row the estimator never opened, in a document a customer receives."""
    got = _texts(_fill([
        _row("Broadcast Quartz", prefix="Base System:", texture_label="Surface texture:",
             area_label="Coverage:"),
        _row("Decorative Flake", prefix="Option 2:", sqft="1,800"),
    ]))
    assert "Surface texture:  Light Broadcast" in got
    assert "Texture:  Light Broadcast" in got, "row 2 lost the template's own label"
    assert any(t.startswith("Coverage: ~5,000 SF") for t in got)
    assert any(t.startswith("Area: ~1,800 SF") for t in got)


def test_an_absent_label_leaves_the_template_wording():
    """"Emptied" is how the editor spells "revert": the input handler deletes the key, so the
    writer never sees it. Nothing here may emit a bare token or a lone colon."""
    got = _texts(_fill([_row()]))
    assert "Texture:  Light Broadcast" in got
    assert any(t.startswith("Area: ~5,000 SF") for t in got)


@pytest.mark.parametrize("blank", ["", "   ", "{{system.texture}}", "{{", "}}"])
def test_a_blank_or_brace_only_label_cannot_reach_the_document(blank):
    """Defence in depth. main._sanitize_system_overrides already drops a blank, but
    proposal_writer is also called directly (the To-Dropbox reconstruction path, and tests), and
    a literal "{{token}}" printed to a customer is the exact failure the writer exists to
    prevent. A brace-only override is stripped to nothing and therefore reverts."""
    got = _texts(_fill([_row(texture_label=blank, area_label=blank)]))
    body = "\n".join(got)
    assert "{{system." not in body, body
    # A brace-only override strips to nothing, so the template's own wording comes back. The
    # "{{system.texture}}" case is the interesting one: stripped it reads "system.texture", which
    # is not a token and cannot be mistaken for one by a reader of the printed page.
    if blank.strip() in ("", "{{", "}}"):
        assert "Texture:  Light Broadcast" in got, got
    else:
        assert "system.texture  Light Broadcast" in got, got


def test_no_work_row_carries_a_raw_token():
    """Whatever the estimator typed into a label, the WORK rows the customer reads must not show
    a `{{token}}`. Every `{{system.…}}` in the document has to be consumed by the expansion —
    checked document-wide, so the VML fallback copies are included. (The bare `{{job_name}}`-style
    front-page tokens ARE still present here: `values` is deliberately minimal in this file, and
    main._ensure_value_aliases is what backfills them on the live path.)"""
    d = _fill([_row(prefix="Base System:", texture_label="Surface texture:",
                    area_label="Coverage:", lf_clause=" and 240 LF of 6\" epoxy cove base")])
    body = "\n".join(_texts(d))
    assert "{{system." not in body and "{{#system" not in body and "{{/system" not in body
    rows = [t for t in body.split("\n")
            if t.startswith(("Base System:", "Surface texture:", "Coverage:"))]
    assert len(rows) == 6, rows          # three rows x (shape + VML fallback twin)
    assert not [t for t in rows if "{{" in t or "}}" in t]


def test_both_the_modern_and_the_legacy_copy_of_a_row_are_rewritten():
    """A floating text box is stored twice — the DrawingML shape and its VML `mc:Fallback` twin.
    Which one a renderer believes is version-dependent, so a label rewritten in only one of them
    would make Word and the customer's PDF disagree about what the proposal says."""
    d = _fill([_row(texture_label="Surface texture:")])
    hits = [p.text for p in pw._iter_all_paragraphs(d) if p.text.startswith("Surface texture:")]
    assert len(hits) == 2, "expected the shape and its fallback twin, got %r" % (hits,)


# ── the numbering rule, at both ends of the range ─────────────────────────────
def test_one_system_is_labelled_system():
    rows = main._build_epoxy_systems({}, dict(BASE_VALUES),
                                     [{"name": "Broadcast Quartz", "sf": 5000, "lf": 0}])
    assert [r["prefix"] for r in rows] == ["System:"]


def test_three_systems_are_numbered():
    rows = main._build_epoxy_systems({}, dict(BASE_VALUES), [
        {"name": "Quartz", "sf": 5000, "lf": 0},
        {"name": "Flake", "sf": 1800, "lf": 0},
        {"name": "Urethane", "sf": 900, "lf": 0},
    ])
    assert [r["prefix"] for r in rows] == ["Option 1:", "Option 2:", "Option 3:"]


def test_renaming_row_one_leaves_the_other_rows_numbered():
    """THE RULE, stated as a test. The computed prefix is a per-index default, so an override on
    row 1 changes row 1. The alternative — one manual label suppressing numbering for the whole
    list — would silently rewrite rows nobody edited."""
    rows = main._build_epoxy_systems({}, dict(BASE_VALUES), [
        {"name": "Quartz", "sf": 5000, "lf": 0},
        {"name": "Flake", "sf": 1800, "lf": 0},
        {"name": "Urethane", "sf": 900, "lf": 0},
    ])
    for i, ov in enumerate(main._sanitize_system_overrides([{"prefix": "Base System:"}])):
        rows[i].update(ov)
    assert [r["prefix"] for r in rows] == ["Base System:", "Option 2:", "Option 3:"]
    got = _texts(_fill(rows))
    assert any(t.startswith("Base System:") for t in got)
    assert any(t.startswith("Option 2:") for t in got)
    assert any(t.startswith("Option 3:") for t in got)


# ── the payload gate in main.py ───────────────────────────────────────────────
def test_the_label_fields_are_on_the_override_whitelist():
    """`_sanitize_system_overrides` drops anything not named here, so the whitelist IS the
    channel. Without `prefix` the "System:" label could be typed but never printed."""
    for field in ("prefix", "texture_label", "area_label"):
        assert field in main._SYSTEM_OVERRIDE_FIELDS, field


def test_the_sanitizer_keeps_a_label_and_drops_a_blank_one():
    got = main._sanitize_system_overrides([
        {"prefix": " Base System: ", "texture_label": "", "area_label": "Coverage:",
         "junk": "dropped"},
        {},
    ])
    assert got == [{"prefix": "Base System:", "area_label": "Coverage:"}, {}]


def test_the_sanitizer_stays_index_preserving():
    """The list is positional. Dropping a malformed entry would shift every later override onto
    the wrong system — a renamed row 2 landing on row 3's label."""
    got = main._sanitize_system_overrides(["junk", {"name": "Decorative Flake"}])
    assert got == [{}, {"name": "Decorative Flake"}]


# ══ the grown height, once it leaves the browser ══════════════════════════════
def _box_heights(d, idx):
    """(anchor extent pt, shape transform pt, VML twin pt) for one box — the three places a
    box's size is recorded, in two unit systems."""
    txbx = list(pw._iter_txbx(d))[idx]
    anchor = pw._txbx_anchor(txbx)
    ext = anchor.find(pw.qn("wp:extent")) if anchor is not None else None
    extent = round(int(ext.get("cy")) / EMU_PER_PT, 2) if ext is not None else None
    xfrm = None
    for wsp in txbx.iterancestors(_WPS + "wsp"):
        x = next(iter(wsp.iter(_A + "xfrm")), None)
        e = x.find(_A + "ext") if x is not None else None
        if e is not None:
            xfrm = round(int(e.get("cy")) / EMU_PER_PT, 2)
        break
    vml = None
    for shape in pw._txbx_vml_twins(txbx):
        for part in (shape.get("style") or "").split(";"):
            k, _, v = part.partition(":")
            if k.strip().lower() == "height":
                vml = pw._vml_len_pt(v)
        break
    return extent, xfrm, vml


def test_an_auto_grown_height_reaches_all_three_places_in_the_docx():
    """The height the preview grew to is written through the ordinary box_overrides path, so the
    generated file has to agree with the screen in every branch a renderer might read."""
    grown = _fill([_row()], box_overrides={"3": {"h_pt": 219.75}})
    assert _box_heights(grown, 3) == (219.75, 219.75, 219.75)


def test_a_box_that_fits_is_left_byte_identical():
    """The constraint that protects every existing job: growth writes nothing for a box whose
    text already fits, so its bytes are the bytes it always had."""
    plain = pw.fill_proposal(work_type="epoxy", audience="Direct", values=dict(BASE_VALUES),
                             systems=[_row()])
    empty = pw.fill_proposal(work_type="epoxy", audience="Direct", values=dict(BASE_VALUES),
                             systems=[_row()], box_overrides={})
    assert _box_heights(docx.Document(io.BytesIO(plain)), 3) == \
           _box_heights(docx.Document(io.BytesIO(empty)), 3)
    assert _box_heights(docx.Document(io.BytesIO(plain)), 3)[0] == 162.0, (
        "the NOTES box is no longer 162pt — the growth-room numbers below need re-deriving")


def test_the_page_geometry_the_growth_rule_is_built_on():
    """The measurement that makes the WORK box's clip honest rather than lazy. PRICE's top is
    ABOVE the bottom of WORK, so WORK has 168.3pt of room for a 171pt shape: it cannot grow at
    all, and the code that decides that must not be reading "is it below my bottom edge"."""
    geo = pw.template_geometry(docx.Document(str(DIRECT_EPOXY)))
    by_id = {b["id"]: b for b in geo["boxes"]}
    work, price, notes = by_id[2], by_id[4], by_id[3]
    assert round(work["y_pt"] + work["h_pt"], 2) == 323.65
    assert round(price["y_pt"], 2) == 320.95, "the overlap this rule exists for is gone"
    assert round(price["y_pt"] - work["y_pt"], 2) == 168.3 < work["h_pt"]
    assert round(notes["y_pt"] + notes["h_pt"], 2) == 656.6
    assert geo["page"]["h_pt"] - geo["page"]["margin"]["bottom"] == 720.0


# ══ the browser half, executed ════════════════════════════════════════════════
@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _fields(islands):
    return [(s["i"], s["field"]) for s in islands]


def test_every_work_row_label_is_rendered_as_an_editable_island(ran):
    """The (a) answer. Before this, "System:", "Texture:" and "Area:" were escaped HTML inside a
    read-only region — there was no element to put a caret in."""
    got = ran["oneSystem"]["islands"]
    assert _fields(got) == [(0, "prefix"), (0, "name"), (0, "texture_label"), (0, "texture"),
                            (0, "area_label"), (0, "sqft")]
    assert all(s["editable"] for s in got), got
    labels = {s["field"]: s["text"] for s in got}
    assert labels["prefix"] == "System:"
    assert labels["texture_label"] == "Texture:"
    assert labels["area_label"] == "Area:"


def test_the_rendered_rows_still_read_like_the_template(ran):
    """Making the labels editable must not change what the page says. These are the template's
    own three lines, with the estimate's values in them."""
    assert ran["oneSystem"]["lines"] == [
        "System:   Broadcast Quartz",
        "Texture:  Light Broadcast",
        'Area: ~5,000 SF of epoxy flooring and 240 LF of 6" epoxy cove base']


def test_two_systems_number_themselves(ran):
    labels = [s["text"] for s in ran["twoSystems"]["islands"] if s["field"] == "prefix"]
    assert labels == ["Option 1:", "Option 2:"]


def test_renaming_one_row_leaves_the_next_row_numbered(ran):
    """The browser half of the rule. The store holds one entry, for row 1 only, and the re-render
    shows row 2 still carrying its own number."""
    assert ran["renamedRow1"]["stored"] == [{"prefix": "Base System:"}]
    assert ran["renamedRow1"]["persisted"] == [{"prefix": "Base System:"}]
    assert ran["renamedRow1"]["lines"][0] == "Base System:   Broadcast Quartz"
    assert ran["renamedRow1"]["lines"][3] == "Option 2:   Decorative Flake"
    row1 = next(s for s in ran["renamedRow1"]["islands"]
                if s["i"] == 0 and s["field"] == "prefix")
    assert (row1["text"], row1["computed"]) == ("Base System:", "Option 1:"), (
        "the island lost the computed value it reverts to")


def test_emptying_a_label_reverts_it_instead_of_printing_a_token(ran):
    """The one outcome that would be visible to a customer. Clearing the label deletes the
    override, so the computed text comes back — never a bare "{{system.prefix}}", never a lone
    colon left where the label was."""
    assert ran["emptiedLabel"]["stored"] == [{}]
    assert ran["emptiedLabel"]["lines"][0] == "Option 1:   Broadcast Quartz"
    body = " ".join(ran["emptiedLabel"]["lines"])
    assert "{{" not in body and "}}" not in body


def test_the_static_labels_round_trip_per_row(ran):
    """"Texture:" and "Area:" are the two that were genuinely locked. Renaming them on row 1
    writes the new per-row channel and leaves row 2 on the template's wording."""
    assert ran["staticLabels"]["stored"] == [
        {"texture_label": "Surface texture:", "area_label": "Coverage:"}]
    assert ran["staticLabels"]["lines"][1] == "Surface texture:  Light Broadcast"
    assert ran["staticLabels"]["lines"][2].startswith("Coverage: ~5,000 SF")
    assert ran["staticLabels"]["lines"][4] == "Texture:  Light Broadcast"
    assert ran["staticLabels"]["lines"][5].startswith("Area: ~1,800 SF")


def test_a_renamed_label_is_not_flagged_as_a_pricing_edit(ran):
    """The ⚠ marker means "this differs from the estimate", which is a review risk for a NUMBER.
    A renamed label carries no number, so it gets the highlight and a plain tooltip instead —
    otherwise every job with a reworded label would look like it had been re-priced by hand."""
    by_field = {s["field"]: s for s in ran["warnings"]}
    assert by_field["prefix"]["warned"] is False
    assert "Renamed" in by_field["prefix"]["title"]
    assert by_field["sqft"]["warned"] is True
    assert "differs from the computed estimate" in by_field["sqft"]["title"]


# ── growth, run against the template's real geometry ─────────────────────────
def test_the_growth_room_matches_the_page(ran):
    """Room is the distance to the next box below with a horizontal overlap — and ZERO when there
    is no such box. Restated here independently of the harness, off the real template geometry:

        box 0 header  36.00 → box 2 at 152.65   = 116.65
        box 1 date    36.00 → box 5 at 501.95   = 465.95
        box 2 WORK   152.65 → box 4 at 320.95   = 168.30   (its shape is 171pt: no room at all)
        box 3 NOTES  494.60 → NOTHING BELOW IT  =   0.00
        box 4 PRICE  320.95 → box 3 at 494.60   = 173.65
        box 5 logo   501.95 → NOTHING BELOW IT  =   0.00   (NOTES is beside it, not below it)

    THE TWO ZEROS ARE THE POINT, and they used to be 225.40 and 218.05 — the distance to the
    page's bottom margin. The margin is not a measurement of empty space. What sits under NOTES
    is the ACCEPTANCE and signature frame, and under the logo the rest of the letterhead, both
    baked into a full-page PNG: there is no element, so there is no rect, so the DOM cannot see
    them. Bounding by the margin let NOTES grow its bottom edge from 656.6pt to 714.35pt, over
    that frame — and a grown box disarms the server-side shrink, so nothing downstream caught it
    and the customer received a proposal with the terms printed across the artwork
    (review 2026-08-20).

    The honest consequence, which this test also pins: on this template growth is available on
    four boxes and not on two. Reading these zeros as a bug and restoring the margin fallback
    would reintroduce exactly that. Growing into artwork needs the artwork measured — see
    measureTermsBand for the precedent — and that is a separate piece of work.
    """
    assert ran["roomBoxCount"] == 6
    assert ran["room"] == {"0": 116.65, "1": 465.95, "2": 168.3,
                           "3": 0, "4": 173.65, "5": 0}


def test_the_last_box_on_the_page_is_never_offered_growth(ran):
    """The artwork case, end to end rather than as an arithmetic claim: NOTES overflows by 58pt,
    has 225pt of blank page beneath it, and is still refused — no button, no geometry, and a
    warning that says why. This is the test that fails if anyone reinstates the margin fallback."""
    got = ran["artBlocked"]
    assert got["offered"] is False, "offered to grow a box over the baked letterhead artwork"
    assert got["payload"] == {}, "wrote geometry for a box it must not resize"
    assert got["geom"]["boxHPt"] == "162", "the box left the template's height"
    assert got["geom"]["overflow"] is True and got["geom"]["blocked"] is True
    assert "part of the letterhead picture" in got["geom"]["title"], (
        "the estimator is told it cannot grow but not that artwork is the reason")


def test_a_box_that_fits_is_not_touched(ran):
    """Byte-identical output for every job that was already fine — the payload stays empty, so
    the writer has nothing to apply and nothing to persist."""
    got = ran["fitsUntouched"]
    assert got["before"] == got["after"]
    assert got["payload"] == {}
    assert got["persisted"] == 0, "a box that fits triggered a draft save"
    assert got["after"]["minHeight"] == "162pt" and got["after"]["boxHPt"] == "162"
    assert got["after"]["overflow"] is False and got["after"]["grown"] is False


def test_an_overflowing_box_with_room_grows_and_the_height_is_persisted(ran):
    """170pt of content in the 164.5pt PRICE box, and the estimator PRESSES Fit to text. PRICE has
    NOTES below it, so its room (173.65pt) is bounded by a real box and growing it is provably
    safe — which is why this scenario is PRICE and not NOTES. The box becomes 170.25pt (the
    content height rounded up to the template's own 2dp) and that number is in the box_overrides
    the generate payload carries, which is what makes the .docx match the preview.

    A press, not a repaint: growth used to happen inside fitNotesBox, i.e. on first paint and on
    every keystroke, writing document geometry with no gesture behind it."""
    got = ran["grows"]
    assert got["geom"]["minHeight"] == "170.25pt"
    assert got["geom"]["boxHPt"] == "170.25"
    assert got["geom"]["overflow"] is False, "it grew and still claims its text is cut off"
    assert got["geom"]["fontSize"] == "", "it grew AND shrank the type"
    assert got["geom"]["grown"] is True and got["geom"]["moved"] is True
    assert got["payload"] == {"4": {"h_pt": 170.25}}
    assert got["stored"] == {"4": {"h_pt": 170.25}}
    assert got["persistCalls"] == 1
    assert got["autoGrown"] is True


def test_a_box_with_nowhere_to_go_still_clips_and_says_so(ran):
    """WORK is 171pt and has 168.3pt of room, so growing it would print over the PRICE frame —
    which is baked into the letterhead PNG and cannot move. Clipping is the honest outcome, and
    the tooltip has to explain why the box was not simply made bigger."""
    got = ran["blocked"]
    assert got["payload"] == {}, "it moved a box it had just decided it could not move"
    assert got["geom"]["minHeight"] == "171pt" and got["geom"]["boxHPt"] == "171"
    assert got["geom"]["overflow"] is True
    assert got["geom"]["blocked"] is True
    assert "the next box on the page starts where this one ends" in got["geom"]["title"]


def test_the_blocked_badge_is_on_screen_and_not_only_in_a_tooltip():
    """A tooltip is not a warning if nobody hovers. The clipped-and-cannot-grow badge is its own
    CSS rule, more specific than the generic one so it wins wherever they are written, and it
    stands down while the box is expanded (that state has its own message)."""
    sel = r"\.tw-txbx\.tw-notes-overflow\.tw-grow-blocked:not\(\.tw-notes-open\)::after"
    m = re.search(r"(?m)^" + sel + r"\s*\{([^}]*)\}", CSS)
    assert m, "the grow-blocked badge has no top-level rule in styles.css"
    assert "cannot grow" in m.group(1)


def test_the_grown_note_says_what_happened(ran):
    """The geometry of a customer-facing document changed, so the page has to admit it. The note
    is a labelled word in the tools layer — not a grip, which is what confused Kyle already — and
    adding it must not have displaced the resize handles."""
    got = ran["grownNote"]
    assert got["present"] and got["label"] == "Grown to fit"
    assert got["isNotAGrip"], "the note reads as a drag handle"
    assert "Reset box puts it back" in got["title"]
    grips = [c.split()[-1] for c in got["order"] if c.startswith("tw-grip ")]
    assert grips == ["tw-grip-move", "tw-grip-e", "tw-grip-s", "tw-grip-se"], (
        "adding the note reordered the grips test_box_drag_ui.py pins")


def test_the_grown_note_adds_no_height_to_the_box():
    """fitTxbx decides what overflows from the box's offsetHeight, so a control in the normal
    flow would make every box measure taller than its text — i.e. would break the very notice
    this feature reads."""
    m = re.search(r"(?m)^\.tw-box-grown-note\s*\{([^}]*)\}", CSS)
    assert m, ".tw-box-grown-note has no top-level rule in styles.css"
    assert "position: absolute" in m.group(1)


def test_trimming_the_text_gives_the_space_back(ran):
    """The height we added is recomputed from the template each pass, not accumulated. Otherwise
    one long paste would enlarge a box permanently and the estimator would have to know that
    "Reset box" was the cure."""
    got = ran["trimGivesItBack"]
    assert got["grown"]["boxHPt"] == "170.25"
    assert got["after"]["boxHPt"] == "164.5"
    assert got["after"]["grown"] is False and got["after"]["moved"] is False
    assert got["payload"] == {}


def test_a_height_the_estimator_dragged_is_never_auto_grown_over(ran):
    """They dragged the box SHORTER than its text needs. That is a deliberate instruction, so it
    stands — with the overflow warning, which is the honest report — rather than being quietly
    undone by the auto-fit."""
    got = ran["manualHeightWins"]
    assert got["dragged"]["boxHPt"] == "122"
    assert got["after"]["boxHPt"] == "122", "auto-grow overrode a deliberate resize"
    assert got["after"]["overflow"] is True
    assert got["payload"] == {"3": {"h_pt": 122}}


def test_reset_box_stays_reset(ran):
    """"Put this box back where the template has it" has to survive the next repaint. Without the
    suppression the auto-fit would re-grow it immediately and the button would look broken."""
    got = ran["resetSticks"]
    assert got["grown"]["boxHPt"] == "170.25"
    assert got["reset"]["boxHPt"] == "164.5"
    assert got["afterRefit"]["boxHPt"] == "164.5", "the box re-grew itself after Reset"
    # And the text is still handled honestly at that size rather than silently spilling: 170pt of
    # content in a 164.5pt box is only 3% over, so fitTxbx's first step — stepping the type down —
    # absorbs it, which is exactly what it is for. (The older version of this test asserted the
    # overflow BADGE instead, using a box 36% over capacity where shrinking cannot save it. That
    # box was NOTES, which is now correctly refused growth altogether, so the scenario moved to
    # PRICE and the observable moved with it.)
    assert got["afterRefit"]["fontSize"] == "95%", (
        "reset to a size its text does not fit, and neither shrank the type nor warned")
    assert got["payload"] == {}
