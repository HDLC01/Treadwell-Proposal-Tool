"""Polish estimating: the form-to-worksheet mapping, exercised under node.

The Polish worksheet stays the calculation engine — nothing in polish-estimate-core.js prices
anything. So these tests are not about arithmetic; they are about the mapping, and every way a
wrong mapping produces a plausible number instead of an error:

  * **A system string the sheet does not recognise.** Q10 is
    `=IF(F36="cream",Q14,IF(F36="S&P",Q15,IF(F36="full",Q16,0)))`. Write "Salt & Pepper" instead
    of "S&P" and every rate lookup falls through to its ZERO branch. The bid does not error, it
    comes out impossibly cheap — the single most dangerous thing this file can get wrong.
  * **A blank written as "" instead of null.** Excel ranks any text above any number, so
    `"" > 149000` is true and the sheet's comparisons quietly invert.
  * **An added line landing on a section header.** Rows 19, 24 and 28 are empty but they are
    the "MATERIAL - Floor / Dye / Joint Filler" headings. A cost there prints money against a
    heading in Kyle's file, and is still summed.
  * **An added line landing outside SUM(D17:D30).** It would appear in the file and contribute
    nothing — worse than being rejected, because it looks right.
  * **Conditions written as booleans.** The sheet stores the literal words Yes/No.
  * **Reading the wrong total.** D88 is the EPOXY tab's total; polish is D82.

Skipped when node isn't installed; it's on the dev box and in the Docker image.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
CORE = FRONTEND / "js" / "polish-estimate-core.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is not installed")

# A two-area job: several areas MEASURE, one system prices (the sheet has one selector).
STATE = """{
  areas: [ {name:'Main sales floor', sf:9000}, {name:'Back of house', sf:3500} ],
  system: 'S&P',
  tooling: 'traditional',
  conditions: { local:true, hard_bid:false, prevailing_wage:false, taxable:true, remodel_tax:false },
  materials: { 17:{qty:12500,cost:0.07}, 20:{qty:12500,cost:0.07}, 21:{qty:12500,cost:0.10},
               22:{qty:12500,cost:0.11}, 25:{qty:12500,cost:0.14}, 29:{qty:4,cost:385} },
  added: [ {name:'Stair nosing infill', qty:46, cost:12.50} ],
  labour: { polishing:{crew:4,days:6,rate:520}, mockup:{crew:2,days:1},
            joint_filler:{crew:2,days:2} },
  adds: { ram_board:240, stripe_4:310 },
  options: { salt_pepper:true }
}"""


def run(script: str):
    prelude = (
        "const P = require(%s);\n"
        "const S = %s;\n"
        "const out = (v) => console.log(JSON.stringify(v === undefined ? '<undefined>' : v));\n"
        % (json.dumps(str(CORE)), STATE)
    )
    proc = subprocess.run(["node", "-e", prelude + script],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_module_loads():
    assert run("out(typeof P.cellWrites)") == "function"


# ── the system strings the worksheet compares against ─────────────────────────
def test_the_system_values_are_exactly_what_the_sheet_compares_against():
    """Q10/R10/V10 compare F36 against these literals. A prettier label here means every rate
    lookup silently takes its zero branch."""
    assert run("out(P.SYSTEMS.map(s => s.value))") == ["cream", "S&P", "full"]


def test_a_label_change_cannot_leak_into_the_cell():
    """The label is for humans; the value goes in the cell. They must not be the same field."""
    got = run("out(P.SYSTEMS.map(s => [s.value, s.label]))")
    assert ["S&P", "Salt & Pepper"] in got, got


def test_an_unknown_system_is_not_written_at_all():
    """Better a sheet keeping its own default than one told 'Polished' and pricing at zero."""
    w = run("out(P.cellWrites({areas:[{sf:100}], system:'Polished Concrete'}))")
    assert "Polish!F36" not in w


def test_a_known_system_is_written_verbatim():
    assert run("out(P.cellWrites(S)['Polish!F36'])") == "S&P"


# ── areas measure, one system prices ─────────────────────────────────────────
def test_several_areas_sum_into_the_single_area_cell():
    """The sheet has one area cell and one system selector, so several areas are a measurement,
    not several prices. 9,000 + 3,500."""
    assert run("out(P.totalArea(S.areas))") == 12500
    assert run("out(P.cellWrites(S)['Polish!E18'])") == 12500


def test_an_area_with_no_figure_contributes_nothing_rather_than_NaN():
    assert run("out(P.totalArea([{name:'x'},{sf:''},{sf:'2,000'},{sf:null}]))") == 2000


def test_no_area_writes_null_not_zero_or_blank_string():
    """A zero area would drive the sheet's rate bands as if it were a real measurement."""
    assert run("out(P.cellWrites({areas:[]})['Polish!E18'])") is None


# ── blanks must be null, never "" ────────────────────────────────────────────
def test_every_blank_is_null_and_never_an_empty_string():
    """Excel ranks text above numbers: "" > 149000 is true, so a blank string inverts the
    sheet's comparisons. xl-core's loadSheet learned this the hard way."""
    writes = run("out(P.cellWrites({areas:[{sf:1000}], materials:{17:{qty:'',cost:''}}, "
                 "adds:{ram_board:''}}))")
    assert "" not in writes.values(), [k for k, v in writes.items() if v == ""]


# ── added lines: the right rows, and only four ────────────────────────────────
def test_added_lines_take_only_rows_a_sum_already_reads():
    """SUM(D17:D30) covers these, and each has a live =B*C with blank inputs."""
    assert run("out(P.LINE_SLOTS)") == [18, 23, 27, 30]


def test_no_added_line_can_land_on_a_section_header():
    """19, 24 and 28 are 'MATERIAL - Floor / Dye / Joint Filler'. A cost there prints money
    against a heading — and still gets summed, so it looks deliberate."""
    for header_row in (19, 24, 28):
        assert header_row not in run("out(P.LINE_SLOTS)")


def test_no_added_line_escapes_the_summed_range():
    """Outside SUM(D17:D30) a line appears in the file and bills nothing."""
    for row in run("out(P.LINE_SLOTS)"):
        assert 17 <= row <= 30, row


def test_an_added_line_writes_name_quantity_and_rate():
    """The sheet's own =B*C then extends it, and D31 sums it. That is what makes an added line
    bill rather than merely appear."""
    w = run("out(P.cellWrites(S))")
    assert w["Polish!A18"] == "Stair nosing infill"
    assert w["Polish!B18"] == 46
    assert w["Polish!C18"] == 12.5


def test_the_fifth_added_line_is_dropped_from_the_sheet_not_silently_mispriced():
    """Four slots exist. The page keeps a fifth on screen and says there is no room; what must
    never happen is writing it somewhere that does not bill."""
    w = run("out(P.cellWrites({areas:[{sf:1}], added:["
            "{name:'a',qty:1,cost:1},{name:'b',qty:1,cost:1},"
            "{name:'c',qty:1,cost:1},{name:'d',qty:1,cost:1},{name:'e',qty:1,cost:1}]}))")
    names = [v for k, v in w.items() if k.startswith("Polish!A")]
    assert "e" not in names
    assert sorted(n for n in names if n) == ["a", "b", "c", "d"]


def test_slot_allocation_reports_when_it_is_full():
    assert run("out(P.slotForAdded(0))") == 18
    assert run("out(P.slotForAdded(3))") == 30
    assert run("out(P.slotForAdded(4))") is None
    assert run("out([P.slotsLeft(0), P.slotsLeft(3), P.slotsLeft(4), P.slotsLeft(9)])") == [4, 1, 0, 0]


# ── conditions are words, not booleans ───────────────────────────────────────
def test_conditions_are_written_as_the_words_the_sheet_stores():
    """Two of the five live on Polish; three MIRROR the epoxy tab (Polish!B6 is "=Epoxy!B6"),
    so the value belongs on Epoxy and Polish pulls it. See test_polish_derived_cells.py."""
    w = run("out(P.cellWrites(S))")
    assert w["Polish!B4"] == "Yes"      # local          — Polish's own constant
    assert w["Polish!B5"] == "No"       # hard bid       — Polish's own constant
    assert w["Epoxy!B6"] == "Yes"       # taxable        — Polish!B6 is =Epoxy!B6
    assert w["Epoxy!D5"] == "No"        # prevailing wage — Polish!D5 is =Epoxy!D5


def test_an_unset_condition_is_No_rather_than_missing():
    """A missing flag would leave whatever the template shipped with, which for B4 is "Yes" —
    so an out-of-town job would price as local."""
    w = run("out(P.cellWrites({areas:[{sf:1}]}))")
    assert w["Polish!B4"] == "No" and w["Epoxy!B6"] == "No"


# ── the cells we read back ───────────────────────────────────────────────────
def test_the_total_is_the_polish_cell_not_the_epoxy_one():
    """D88 is the Epoxy tab's total. Reading it here would show an unrelated number that still
    looks like a bid."""
    cells = run("out(P.CELLS)")
    assert cells["total"] == "D82"
    assert cells["per_sf"] == "C82"
    assert cells["total"] != "D88"


def test_the_section_subtotals_match_the_worksheet():
    cells = run("out(P.CELLS)")
    assert (cells["material_total"], cells["labour_total"], cells["tooling_total"]) == \
        ("D31", "D45", "D55")


# ── the rail ─────────────────────────────────────────────────────────────────
def test_no_area_flags_the_first_step_rather_than_looking_finished():
    st = run("out(P.stepStatus({}))")
    assert st["areas"] == "att"
    assert st["review"] != "ok"


def test_a_filled_bid_reads_as_complete():
    st = run("out(P.stepStatus(S))")
    assert st["areas"] == "ok" and st["materials"] == "ok" and st["labour"] == "ok"
    assert st["review"] == "ok"


def test_empty_adds_and_options_are_blank_not_a_warning():
    """Most polish jobs have neither. Flagging them would train people to ignore the rail."""
    st = run("out(P.stepStatus({areas:[{sf:1000}]}))")
    assert st["adds"] == "" and st["options"] == ""


def test_blockers_name_what_is_missing():
    b = run("out(P.blockers({}))")
    assert any("area" in x.lower() for x in b)
    assert any("system" in x.lower() for x in b)
    assert run("out(P.blockers(S))") == []


# ── nothing in here prices anything ──────────────────────────────────────────
def test_the_core_module_holds_no_rates_of_its_own():
    """The whole reason the screen can match the file is that every rate stays in the workbook.
    A number here is a second opinion waiting to drift."""
    src = CORE.read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines()
                     if not l.strip().startswith("//") and not l.strip().startswith("*"))
    for rate in ("3.5", "4.5", "0.07", "0.14", "385", "32.20", "48.00", "1.2", "0.9", "1.02"):
        assert rate not in body, (
            "%r looks like a rate copied out of the worksheet; the sheet must stay the only "
            "place a price lives" % rate)


# ── a blank field must not wipe what the template already holds ───────────────
# Found by opening the page on a real staging project. The template arrives with Kyle's own
# figures in it - the material rates in C20, C21, C29 and the rest - and cellWrites emitted null
# for every field nobody had typed. The bid fell from $17,431 to $6,194 the instant the page
# opened, and it saved. Every test above passed, because they all feed it a POPULATED model.
def test_an_untouched_material_row_is_not_written_at_all():
    """Not null, not zero: absent from the payload, so the worksheet keeps Kyle's rate."""
    w = run("out(P.cellWrites({areas:[{sf:1000}], materials:{}}))")
    for row in (17, 20, 21, 22, 25, 26, 29):
        assert "Polish!B%d" % row not in w, "row %d quantity clobbered" % row
        assert "Polish!C%d" % row not in w, "row %d COST clobbered - that is Kyle's rate" % row


def test_an_untouched_labour_line_is_not_written():
    w = run("out(P.cellWrites({areas:[{sf:1000}], labour:{}}))")
    for cell in ("A37", "B37", "C37", "A40", "B40", "A44"):
        assert "Polish!" + cell not in w, "%s clobbered" % cell


def test_an_untouched_add_is_not_written():
    w = run("out(P.cellWrites({areas:[{sf:1000}], adds:{}}))")
    for cell in ("J17", "J18", "J19", "J20", "J21", "J22"):
        assert "Polish!" + cell not in w


def test_a_half_typed_added_line_does_not_blank_its_slot():
    """A name with no numbers yet must not write nulls over the spare row's inputs."""
    w = run("out(P.cellWrites({areas:[{sf:1}], added:[{name:'Stair nosing'}]}))")
    assert w.get("Polish!A18") == "Stair nosing"
    assert "Polish!B18" not in w and "Polish!C18" not in w


def test_a_typed_value_IS_written():
    """The other half: leaving blanks alone must not stop real edits reaching the sheet.

    Every cell asserted here is a genuine INPUT in the template. The quantities and days that
    used to be checked (B20, B37, J17) are formulas the worksheet computes off the area, so
    writing them is the bug test_polish_derived_cells.py exists to catch — they are not a
    weaker version of this assertion, they are the opposite of it."""
    w = run("out(P.cellWrites({areas:[{sf:1000}], materials:{20:{qty:1000,cost:0.09}}, "
            "labour:{polishing:{crew:4,days:6}}, adds:{stripe_4:240}}))")
    assert w["Polish!C20"] == 0.09          # densifier rate — a constant Kyle maintains
    assert w["Polish!A37"] == 4             # crew size      — a constant
    assert w["Polish!J21"] == 240           # 4" striping    — a constant
    assert w["Polish!E18"] == 1000          # the area
    assert "Polish!B20" not in w            # "=E18"
    assert "Polish!B37" not in w            # "=E37"


def test_zero_is_a_real_value_and_does_get_written():
    """Blank means "leave it alone", so typing 0 has to be how a line is deliberately zeroed.
    If 0 were ignored too, there would be no way to remove a cost."""
    w = run("out(P.cellWrites({areas:[{sf:1000}], materials:{20:{qty:0,cost:0}}, "
            "adds:{stripe_4:0, stripe_6:0}}))")
    assert w["Polish!C20"] == 0             # the rate zeroed on purpose
    assert w["Polish!J21"] == 0 and w["Polish!J22"] == 0
    # A zero aimed at a computed cell is still refused. Zero is a real value, but B20 is "=E18"
    # and freezing it at 0 is exactly the failure that put materials at $0 on a 1,632 SF job.
    assert "Polish!B20" not in w
