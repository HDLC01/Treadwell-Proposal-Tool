"""The sidebar lights a row by the page's FULL path, not by the end of it (#804, spec #802).

Until this ticket navItem() lit a row when location.pathname ENDED WITH the row's href. Every page
sat at the root, so that was the same thing as matching the whole path. The BD CRM moves in under
/bd/, with its own admin.html and analytics.html, and an ends-with match would light the proposal
tool's Admin row on /bd/admin.html and its Analytics row on /bd/analytics.html.

Executed, not grepped: js/sidebar-active-harness.js runs the real auth.js with location.pathname
set to each address and reads which rows the markup marks active.

Two halves:
  * the BD addresses light no tool row at all, only the BD CRM row (#806);
  * every address the app serves today lights exactly the row it lit before, written out as a table
    below. The table must name every page in the frontend, so a new page is a decision about its row
    rather than a silent "nothing".

BEFORE is typed out, not recorded. It was checked once, by hand, by running this harness against
origin/staging's auth.js, icons.js and root-path.js (the code before this ticket): every entry
matched, and that old code did light Admin on /bd/admin.html and Analytics on /bd/analytics.html.
"""
from __future__ import annotations

import pathlib

import pytest

from _frontend_tree import FRONTEND, pages, rel
from _node import last_json_line, require_node, run_node

HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "sidebar-active-harness.js"

# What each address the app serves lit BEFORE this ticket, and must still light. Keyed by the
# address in the browser. "|root-path" means the page served there runs js/root-path.js before
# auth.js, which is how "/" (portal.html's bytes) reads as /portal.html.
BEFORE = {
    # the home page: the bare domain serves the board, and its guard makes it read as /portal.html
    "/|root-path": ["/portal.html"],
    # "/?new=1" serves the intake form (index.html) at "/", which runs no guard: no row, as before
    "/": [],
    # the board's second address, served by main.py from portal.html's bytes
    "/gc-projects.html": ["/gc-projects.html"],
    # every page with a row lights its own row
    "/portal.html": ["/portal.html"],
    "/followups.html": ["/followups.html"],
    "/leads.html": ["/leads.html"],
    "/crm.html": ["/crm.html"],
    "/calendar.html": ["/calendar.html"],
    "/project-calendar.html": ["/project-calendar.html"],
    "/analytics.html": ["/analytics.html"],
    "/projects.html": ["/projects.html"],
    "/history.html": ["/history.html"],
    "/trash.html": ["/trash.html"],
    "/v2-board.html": ["/v2-board.html"],
    "/polish-estimates.html": ["/polish-estimates.html"],
    "/library.html": ["/library.html"],
    "/markup.html": ["/markup.html"],
    "/notifications.html": ["/notifications.html"],
    "/followup-settings.html": ["/followup-settings.html"],
    "/admin.html": ["/admin.html"],
    # the v2 tool's two steps light its board's row (ALSO_ACTIVE_ON)
    "/polish-intake.html": ["/v2-board.html"],
    "/polish-estimate.html": ["/v2-board.html"],
    # pages with no row of their own: the wizard, the drawer's info sheet, sign-in, the stubs
    "/index.html": [],
    "/estimate-review.html": [],
    "/proposal-review.html": [],
    "/generate.html": [],
    "/done.html": [],
    "/info-sheet.html": [],
    "/login.html": [],
    "/dropbox.html": [],
    # the browser lower-cases nothing, but the rule always did
    "/Portal.html": ["/portal.html"],
    # THE BD CRM (#806): its row is lit on every page under /bd/, and only its row. BD's old login
    # page draws no sidebar (it only sends the person to sign-in), but the rule still reads it as BD.
    "/bd/": ["/bd/"],
    "/bd/index.html": ["/bd/"],
    "/bd/login.html": ["/bd/"],
    # The Contacts page's place (#807): where This Week sends the assistant; plain words until it moves.
    "/bd/contacts.html": ["/bd/"],
    # One contact and Add contact (#808): BD pages like the rest, so the BD CRM row and nothing else.
    "/bd/contact.html": ["/bd/"],
    "/bd/add.html": ["/bd/"],
    # Admin, Potential BD Contacts and Analytics (#809): the BD CRM row, never the tool's own Admin or
    # Analytics row, whose pages share their file names.
    "/bd/admin.html": ["/bd/"],
    "/bd/review.html": ["/bd/"],
    "/bd/analytics.html": ["/bd/"],
}

# Addresses under /bd/ whose file names are the same as a tool page's. Under an ends-with match each
# would light that tool row. Each lights the BD CRM row (#806) and no tool row.
BD_SUB_FOLDER = [
    "/bd/admin.html", "/bd/analytics.html", "/bd/index.html", "/bd/", "/bd/portal.html",
    "/bd/projects.html", "/bd/history.html", "/bd/v2-board.html", "/bd/polish-intake.html",
    "/bd/polish-estimate.html", "/BD/Admin.html",
]
# Another sub-folder: no row at all.
OTHER_SUB_FOLDER = ["/other/leads.html"]
SUB_FOLDER = BD_SUB_FOLDER + OTHER_SUB_FOLDER


@pytest.fixture(scope="module")
def lit():
    require_node()
    proc = run_node(HARNESS, FRONTEND, *BEFORE, *SUB_FOLDER)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    out = last_json_line(proc.stdout)
    keys = list(BEFORE) + SUB_FOLDER
    return out, {k: c for k, c in zip(keys, out["cases"])}


def test_the_harness_reads_a_real_sidebar(lit):
    """Vacuity guard: every check below compares lists of rows, and an empty menu would agree with
    an empty expectation."""
    out, cases = lit
    assert len(out["hrefs"]) >= 18, out["hrefs"]
    assert "/admin.html" in out["hrefs"] and "/analytics.html" in out["hrefs"]
    assert cases["/|root-path"]["seen"] == "/portal.html", "the home guard did not run"


@pytest.mark.parametrize("address", BD_SUB_FOLDER)
def test_a_bd_page_lights_the_bd_crm_row_and_no_tool_row(lit, address):
    _, cases = lit
    assert cases[address]["lit"] == ["/bd/"], (
        "%s lights %s: it must light the BD CRM row alone, and an ends-with match would light the "
        "tool row of the same file name" % (address, cases[address]["lit"]))


@pytest.mark.parametrize("address", OTHER_SUB_FOLDER)
def test_a_page_in_another_sub_folder_lights_no_row(lit, address):
    _, cases = lit
    assert cases[address]["lit"] == [], (
        "%s lights %s: the sidebar is matching the end of the path, not the whole of it"
        % (address, cases[address]["lit"]))


@pytest.mark.parametrize("address", list(BEFORE))
def test_every_page_lights_exactly_the_row_it_lit_before(lit, address):
    _, cases = lit
    assert cases[address]["lit"] == BEFORE[address], (
        "%s lights %s, and lit %s before" % (address, cases[address]["lit"], BEFORE[address]))


def test_the_home_page_lights_direct_projects(lit):
    """Named on its own because it is the page staff open the app on (HOME_PAGE, main.py _root). It
    overlaps BEFORE["/|root-path"] above on purpose, so a failure names the home page outright."""
    _, cases = lit
    assert cases["/|root-path"]["lit"] == ["/portal.html"]


def test_the_table_names_every_page_the_frontend_has():
    """A page added later has to say which row it lights, here, rather than pass by default."""
    served = {"/" + rel(p) for p in pages()}
    named = {k.split("|")[0] for k in BEFORE}
    assert served - named == set(), "these pages are missing from BEFORE: %s" % sorted(served - named)


def test_every_row_is_in_the_table(lit):
    """And the other way: a row added to the sidebar is a row whose page must be listed."""
    out, _ = lit
    assert set(out["hrefs"]) <= set(BEFORE), set(out["hrefs"]) - set(BEFORE)
