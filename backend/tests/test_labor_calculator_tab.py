"""The Labor Calculator tab, and the Travel section it opens with (Kyle's notes, B7, 2026-10-05).

Hanz: "create another tab right beside Labor in Items & Assemblies ... where we would have the
calculations for the default containers in the Labor tab in the estimate sheet ... name it Labor
Calculator", and Travel goes in it. Today it holds Travel Labor and the per-line modes.

HOTEL AND PER DIEM ARE SET ON THE LABOR TAB (Hanz, 2026-10-09: "what about hotel and per diem? I
think they should be under this labor Tab but they have their own section"). They are still the
Global markup_rules lines travel_lodging / travel_per_diem, and the Labor tab's own section is the
only door -- so the behaviour is EXECUTED, not read: labor-calculator-harness.js runs the shipped
block out of library.js against a fake DOM and fetch.
(The Defaults tab's own "Markup" inputs carry a data-markup-formula attribute and NO save handler
anywhere in js/, which is the failure a source assertion cannot see.)
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = REPO / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "labor-calculator-harness.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def ran():
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def html():
    return (FRONTEND / "library.html").read_text(encoding="utf-8", errors="replace")


def test_the_tab_sits_right_after_labor_and_before_administration(html):
    """Mutation: move the button after tab-vendors, or drop the pane's `hidden` -- it would open
    showing on top of whichever tab was selected."""
    labor = html.index('id="tab-labor"')
    calc = html.index('id="tab-labcalc"')
    vendors = html.index('id="tab-vendors"')
    assert labor < calc < vendors, "the Labor Calculator tab is not right beside Labor"
    assert re.search(r'id="tab-labcalc"[^>]*aria-controls="pane-labcalc"', html)
    assert re.search(r'<section id="pane-labcalc"[^>]*\shidden', html), "the pane starts visible"
    assert ">Labor Calculator<" in html


def test_the_defaults_tab_points_at_the_calculator_and_the_labor_tab_for_travel(html):
    """One pointer on the Defaults tab: Travel Labor is worked out in the Labor Calculator (a link
    that goes there), and Hotel and Per Diem rates are set on the Labor tab.

    Mutation: delete the data-goto-labcalc anchor -- the pointer becomes plain text. Put "Travel is
    set in Labor Calculator" back -- an admin is sent to a tab with no Hotel or Per Diem box."""
    pane = html.split('id="pane-defaults"')[1].split("</section>")[0]
    assert "data-goto-labcalc" in pane
    assert "Travel is set in" not in pane
    assert "Hotel and Per Diem rates are set on the Labor tab" in pane


def test_the_new_tab_is_wired_into_the_view_switch():
    """A tab button with no entry in PANES switches nothing, and one with no TAB_OF entry throws on
    the first showView. Both lists carry it, in the page's own order.

    Mutation: drop "labcalc" from PANES in library.js."""
    js = (FRONTEND / "js" / "library.js").read_text(encoding="utf-8", errors="replace")
    assert re.search(r'var PANES = \["items", "asm", "labor", "labcalc", "vendors", "defaults"\];', js)
    assert 'labcalc: "tab-labcalc"' in js
    assert 'if (p === "labcalc") renderLabCalc();' in js, "opening the tab paints nothing"
    assert re.search(r'\$\("pane-labcalc"\)\.addEventListener\("change"', js), (
        "the rate boxes have no save handler")


@needs_node
def test_the_calculator_shows_the_travel_labor_rate_and_the_rule_but_no_hotel_or_per_diem_box(ran):
    """Mutation: put the TRAVEL_KEYS loop back into renderLabCalc -- two boxes (and a second door
    onto the same rows) come back."""
    a = ran["admin"]
    assert a["loadingFirst"].startswith('<p class="paneintro">Loading'), (
        "the tab painted before its figures arrived")
    assert a["readOnce"] == 1, "opening the tab made %r reads of the markup rules" % a["readOnce"]
    assert a["travelBoxes"] == 0, "the Labor Calculator still has a Hotel / Per Diem box"
    assert a["mentionsLodging"] is False, "the Labor Calculator still draws a Hotel / Per Diem row"
    assert a["pointsAtLabor"], "the tab does not say where the Hotel and Per Diem rates went"
    assert a["travelLaborRow"], "Travel Labor does not show the Labor tab's own rate"
    assert a["seventyMiles"], "the 70-mile rule is not stated on the tab"
    assert a["insideMarkups"], "the tab does not say Hotel and Per Diem price inside the markups"
    assert a["roHidden"] is True


@needs_node
def test_the_labor_tab_has_a_hotel_and_per_diem_section_with_the_filed_figures(ran):
    """Hanz 2026-10-09. Its own section below the labor lines: Hotel ($ a night) and Per Diem ($ a
    day), the filed figure in each box (the shipped 70 / 45 as the placeholder when none is filed),
    and one plain line on how it is worked out. Plain words, no em dash.

    Mutation: delete renderTravelRates (or the call from renderLaborRate) -- no section."""
    t = ran["travel"]
    assert t["section"], "no Hotel and Per Diem section on the Labor tab"
    assert t["hotelFiled"], "the filed $80 hotel figure is not in its box (placeholder 70)"
    assert t["perDiemEmptyWithShippedPlaceholder"], (
        "an unfiled per diem must show an empty box with Kyle's $45 as the placeholder")
    assert t["hotelAria"] and t["units"] and t["inMoneyBox"]
    assert t["how"], "the Hotel row does not say how nights are counted"
    assert t["startsOff"] == 2, "both rows say they start off on a new estimate"
    assert t["seventyMiles"], "the 70-mile rule is not stated"
    assert not t["emDash"]


@needs_node
def test_a_new_estimate_still_starts_hotel_and_per_diem_at_the_filed_figures(ran):
    """STORAGE DID NOT MOVE: the same markup_rules rows are read, so a new bid copies $80 / $52 when
    they are filed and the shipped $70 / $45 when nothing is.

    Mutation: read the rates from a different line key in travelRatesFromRules."""
    assert ran["newEstimate"] == {"filedLodging": 80, "filedPerDiem": 52,
                                  "shippedLodging": 70, "shippedPerDiem": 45}


@needs_node
def test_saving_a_rate_files_the_whole_global_row_and_keeps_its_note(ran):
    """A PUT states the whole markup row, so the filed note must ride along or a save from here
    silently clears one written on the Markup page. It files on the GLOBAL layout by line key, a
    `$` typed in front is accepted, and the Defaults tab's copy of the row is kept honest.

    Mutation: drop `notes: rule.notes || ""` from saveTravelRate -- the note comes back empty."""
    s = ran["saved"]
    assert s["puts"][0] == {"layout": "global", "line_key": "travel_per_diem", "applies": True,
                            "notes": "", "formula": "55"}
    assert s["puts"][1] == {"layout": "global", "line_key": "travel_lodging", "applies": True,
                            "notes": "kept note", "formula": "90"}, (
        "the lodging save did not carry the filed note: %r" % s["puts"][1])
    assert "Hotel saved: $90 per night" in s["alert"]
    assert s["cached"] == "55"
    assert s["defaultsTabCopy"] == [["travel_lodging", "90"]]


@needs_node
def test_a_blank_the_same_value_or_a_non_number_sends_nothing(ran):
    """Mutation: drop the `<= 0` / regex guard -- "7e1" or "-5" is filed as a rate."""
    assert ran["noops"]["sent"] == 0
    assert "shipped $45 stands" in ran["noops"]["alert"], ran["noops"]["alert"]
    for r in ran["refused"]:
        assert r["sent"] == 0, "%r was sent to the server" % r["v"]
        assert r["back"] == "90", "%r left the box holding the refused value" % r["v"]
        assert "dollar figure above zero" in r["alert"], r


@needs_node
def test_a_refused_save_puts_the_old_figure_back_and_says_why(ran):
    r = ran["refusedByServer"]
    assert r["back403"] == "80" and "admin-only" in r["alert403"]
    assert r["back400"] == "80" and r["alert400"] == "the server said no"
    assert r["cacheKept"] == "80", "the cached figure moved on a refused save"


@needs_node
def test_a_non_admin_reads_the_figures_but_gets_no_boxes(ran):
    n = ran["nonAdmin"]
    assert n["boxes"] == 0 and n["inputs"] == 0, "a non-admin was handed a box that can only 403"
    assert n["showsLodging"] and n["showsShippedPerDiem"]


@needs_node
def test_the_markup_read_failing_is_said_out_loud_and_invents_no_rate(ran):
    assert ran["readFails"]["said"] and ran["readFails"]["boxesEmpty"]
    assert ran["figure"] == ["70", "70.5", "", "", ""], (
        "a switched-off, non-numeric or absent rule must read as not filed: %r" % ran["figure"])


# ── B7b: the per-line modes, the Try-it box ──────────────────────────────────────────────────────
def test_the_calculator_lists_the_built_in_crew_and_favorited_day_lines_only(ran):
    """Not Travel (its own section), not an unfavorited row, not an hours row.
    Mutation: drop the favorite / unit filters in calcLines."""
    assert ran["calcLines"] == ["polishing", "mockup", "jointfill", "u1"]


def test_a_saved_mode_is_shown_and_the_company_rate_is_the_placeholder_figure(ran):
    assert ran["calcLoaded"] == {"mockupFixed": True, "companyRateShown": True}


def test_try_it_shows_each_default_lines_figures_and_the_total_and_changes_nothing(ran):
    """12,000 SF at 2,500 SF/day = 5 days; 3 guys x 5 x $40 x 10 h = $6,000 + mock-up $480.
    Mutation: Math.floor in laborCalcValues (4 days) or reading the draft not the saved row."""
    assert ran["tryFixed"] == {"hasMockup": True, "total": True}
    assert ran["trySf"] == {"days5": True, "total": True, "changedNothing": True}
    assert ran["tryRoundsUp"] is True


def test_an_incomplete_mode_is_said_in_words_and_sends_nothing_then_saves_when_complete(ran):
    assert ran["sfIncomplete"]["sent"] == 0
    assert "how many guys" in ran["sfIncomplete"]["alert"]
    puts = ran["sfSaved"]["puts"]
    assert puts[-1]["mode"] == "sf" and puts[-1]["hours_per_day"] == 10
    assert puts[-1]["crew"] == "3" and puts[-1]["sf_per_day"] == "2,500"
    assert ran["sfSaved"]["url"] == "/api/library/labor-calc/polishing"


def test_not_set_clears_the_line_a_refusal_puts_it_back_and_an_absent_table_still_draws(ran):
    assert ran["cleared"] == {"last": {"mode": "none"}, "savedGone": True}
    assert ran["calc403"] == {"alert": "Changing these is admin-only. Nothing was saved.",
                              "kept": False}
    assert ran["calcAbsent"] == {"drew": True, "notSet": True, "travelStill": True, "tryEmpty": True,
                                 "tryEmptyDesigned": True}
    assert ran["calcNonAdmin"]["controls"] == 0


# ── the layout Hanz screenshotted on staging, 2026-10-06: "fix these ui" ──────────────────────────
@needs_node
def test_each_section_is_a_heading_over_its_own_card_like_the_other_tabs(ran, html):
    """Travel had no heading at all and the three sections floated inside one card; the intro text
    ran at 80ch beside tables that ran the full 1660px page. Now: .admin-section x3 (the
    Administration and Defaults shape), and the pane shares the Defaults tab's 980px measure cap.

    Mutation: put the outer <div class="card"> back round #labcalc-body, or drop the h2 from the
    Travel section -- the section list comes back short."""
    lay = ran["layout"]
    assert lay["sections"] == ["Travel", "Default labor lines", "Try it"], lay["sections"]
    assert lay["cards"] == 3, "expected one card per section, found %r" % lay["cards"]
    pane = html.split('<section id="pane-labcalc"')[1].split("</section>")[0]
    assert '<div id="labcalc-body" class="admin-grid"></div>' in pane
    assert 'class="card"' not in pane, "a card wraps the whole tab again, so sections nest inside it"
    assert re.search(r"#pane-labcalc \.admin-grid[^{]*\{ max-width:980px; \}", html), (
        "the Labor Calculator lost the measure cap the Defaults tab uses")


@needs_node
def test_rates_sit_in_the_pages_money_box_and_nothing_wears_an_unruled_class(ran):
    """The rate boxes were class="mkin", which only markup.html styles: a bare 150px browser input
    with a "$" floating outside it. Edit rate was class="ghostlink", the same story. Both now use
    this page's own .money and .btn.ghost.sm; widths are classes, not style attributes.

    Mutation: put style="width:64px" back on the crew boxes, or class="mkin" on a rate box."""
    lay = ran["layout"]
    assert lay["inlineStyles"] == [], lay["inlineStyles"]
    assert lay["unruledClasses"] == [], lay["unruledClasses"]
    assert lay["itemsTable"] is False, ".items-table centres every header over left-aligned cells"
    assert lay["lineRateInMoneyBox"] and ran["travel"]["inMoneyBox"]
    assert lay["editRateIsGhostButton"]


@needs_node
def test_status_and_empty_cells_read_as_quiet_sentence_case_not_caps(ran):
    """"SAVED TO MARKUP" and "LEFT BLANK ON A NEW ESTIMATE" were .builtin -- the uppercase chip a
    read-only library row wears -- and the second sat under one header beside two empty columns.

    Mutation: render the not-set cell as <span class="builtin"> in its own <td> again."""
    lay = ran["layout"]
    assert lay["capsStatus"] == 0
    assert lay["notSetOnceAcross"], "a line with no mode does not say so once, across its empty columns"
    assert lay["tryBand"], "Job SF is not a labelled band inside the Try-it card"


@needs_node
def test_the_labor_tab_shows_the_company_labor_rate_and_an_admin_can_file_it(ran):
    """Hanz 2026-10-09: the labor rate moved from Markups -> Global to Items & Assemblies -> Labor.
    A box at the top of the tab: the filed figure (placeholder 33 when none), "an hour", and the one
    plain sentence. Saving PUTs the SAME markup_rules row (layout global, line_key labor_rate) with
    the filed note carried; the same figure, a blank, and a non-number send nothing.

    Mutation: make saveLaborRate a no-op, or PUT layout "labor" -- puts is empty / wrong."""
    r = ran["laborRate"]
    assert r["loadingFirst"].startswith('<p class="paneintro">Loading')
    assert r["box"] and r["anHour"] and r["sentence"], r
    assert not r["emDash"]
    assert ran["laborRateSaved"]["puts"] == [{"layout": "global", "line_key": "labor_rate",
                                              "applies": True, "notes": "kept note",
                                              "formula": "44.5"}]
    assert "Labor rate saved: $44.5 per hour" in ran["laborRateSaved"]["alert"]
    assert ran["laborRateSaved"]["cached"] == "44.5"
    assert ran["laborRateNoops"]["sent"] == 0
    assert ran["laborRateNoops"]["back"] == "44.5"
    assert "dollar figure above zero" in ran["laborRateNoops"]["alert"]


@needs_node
def test_the_labor_rate_box_shows_the_shipped_figure_when_unfiled_and_is_read_only_for_staff(ran):
    """No figure filed: an empty box with the shipped 33 as its placeholder (the one constant in
    bid-model). A 403 puts the old figure back. A non-admin gets text and no input, 33 when unfiled.

    Mutation: draw the input for a non-admin -- inputs == 1."""
    assert ran["laborRateUnfiled"] is True
    assert ran["laborRate403"]["back"] == "40"
    assert "admin-only" in ran["laborRate403"]["alert"]
    assert ran["laborRateNonAdmin"] == {"inputs": 0, "shows": True, "unfiledShows33": True}


@needs_node
def test_lodging_and_per_diem_still_save_through_the_shared_helper(ran):
    """The travel boxes and the labor-rate box share fileGlobalRate; this is the travel half, so a
    refactor that broke it goes red here."""
    assert ran["travelStillSaves"] == [{"layout": "global", "line_key": "travel_lodging",
                                        "applies": True, "notes": "n", "formula": "91"}]


def test_the_labor_tab_carries_the_box_and_nothing_still_says_markups_sets_the_rate(html):
    """The mount points exist, the change listener is wired, and no code comment or text still
    names Markups -> Global as the labor rate's home.

    Mutation: drop the pane-labor change listener -- the box draws and saves nothing."""
    pane = html.split('id="pane-labor"')[1].split("</section>")[0]
    assert 'id="labor-rate-box"' in pane and 'id="labor-rate-alert"' in pane
    assert 'id="travel-rates-box"' in pane and 'id="travel-rate-alert"' in pane
    labcalc = html.split('id="pane-labcalc"')[1].split("</section>")[0]
    assert "Markup page" not in labcalc, "the Labor Calculator still names the Markup page as a home"
    js = (FRONTEND / "js" / "library.js").read_text(encoding="utf-8", errors="replace")
    assert re.search(r'\$\("pane-labor"\)\.addEventListener\("change"', js)
    assert 'if (p === "labor") renderLaborRate();' in js
    for name in ("polish-estimate.js", "bid-model.js"):
        text = (FRONTEND / "js" / name).read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            assert not ("labor rate" in line.lower() and "markups -> global" in line.lower()), (name, line)


def test_the_defaults_tab_markup_list_no_longer_lists_hotel_or_per_diem():
    """One door: the Defaults tab's read-only Markup list leaves out every Global line that has its
    own home (fees_textura, labor_rate, travel_lodging, travel_per_diem).

    Mutation: drop the two travel_* clauses from the GLOBAL_MARKUP filter in load()."""
    js = (FRONTEND / "js" / "library.js").read_text(encoding="utf-8", errors="replace")
    block = js.split("GLOBAL_MARKUP = (mj.rules || []).filter(function (r) {")[1].split("}).map(")[0]
    for key in ("fees_textura", "labor_rate", "travel_lodging", "travel_per_diem"):
        assert 'r.line_key !== "%s"' % key in block, key
