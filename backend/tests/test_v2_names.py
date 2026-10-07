"""Estimating Tool v2 and v2 Estimates: the new names, and the proof that the old ones stay gone.

Phase 1b of the v2 estimating program (2026-10-07). The tool that was called the Polish beta is
"Estimating Tool v2", and its database page, the Polish Estimate Database, is "v2 Estimates". The
tool is being extended to every work type, so a name with "Polish" in it stops being true.

LABELS ONLY. File names and addresses (`polish-intake.html`, `polish-estimate.html`,
`polish-estimates.html`), element ids, the `polish_estimate` key, the `polish_beta` flag, the `beta`
tab key and the "(beta test)" ending on a test copy's name all keep their names: saved projects,
permissions and bookmarks are keyed on them. The last block here pins that, so a rename that
reaches too far fails as loudly as one that does not reach far enough.

WHAT IS RUN, NOT READ. The names reach a person through code, so the code is run.
`tests/js/v2-names-harness.js` executes the real sidebar, the Admin page's role matrix (handed the
server's own capability table), the whole v2 Estimates page against a stubbed list, the Proposals
Database's own chip and empty-state code, and every path where the sandbox stops and says so. This
file reads what those produced. The static pages are read with a real HTML parser, so a comment
that records the old name (every comment worth reading does) is not mistaken for a page that still
shows it.

THE SWEEPS. Three of them read every string a person can read: the JavaScript through
`_lib.stringLiterals`, the HTML through `html.parser` (text and attribute values, never comments,
scripts or styles) and the Python through `ast` (string constants, never comments or docstrings).
Each one is first shown a planted old name it must catch and a planted comment it must ignore. A
sweep that cannot see a string says "clean" about anything, and that is the failure these guard.

The one exemption is named: `[polish beta]` at the start of a string is a developer's console
prefix and not something a person reads.
"""
import ast
import json
import pathlib
from collections import defaultdict
from html.parser import HTMLParser

import pytest

import library
import nav_access
from _node import last_json_line, require_node, run_node

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parent
FRONTEND = BACKEND.parent / "frontend"
HARNESS = HERE / "js" / "v2-names-harness.js"

TOOL = "Estimating Tool v2"
DATABASE = "v2 Estimates"
TOTAL = "v2 total"

# Lower case, whitespace squashed: what the sweeps look for. Each is a way the old names were
# written where a person could read them.
BANNED = ["polish estimate", "polish beta", "beta polish", "beta calculator", "beta total",
          "beta estimate", "polish intake"]
EXEMPT_PREFIXES = ["[polish beta]"]

INTAKE_HREF = "/polish-intake.html"
ESTIMATE_HREF = "/polish-estimate.html"
DATABASE_HREF = "/polish-estimates.html"


def squash(text):
    """Whitespace collapsed to single spaces, lower case: a phrase wrapped over two lines is one."""
    return " ".join(str(text).split()).lower()


# ── reading a page the way a person does ─────────────────────────────────────
class Readable(HTMLParser):
    """The words in a page: text outside <script> and <style>, and every attribute value.
    Comments are never words, so handle_comment is not overridden."""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source",
            "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.words = []                    # (line, text)
        self.attrs = []                    # (line, tag, name, value)
        self.by_tag = defaultdict(list)    # "title", "h1" -> [text, ...]
        self.by_id = defaultdict(list)     # element id -> [text, ...]
        self.anchors = []                  # {"href", "id", "text"}
        self.elements = {}                 # element id -> its attributes, as a dict
        self._stack = []                   # (tag, id) of every element still open
        self._hidden = 0                   # inside <script> or <style>
        self._anchor = None

    def handle_starttag(self, tag, attrs):
        line = self.getpos()[0]
        for name, value in attrs:
            if value:
                self.attrs.append((line, tag, name, value))
        a = dict(attrs)
        if a.get("id"):
            self.elements[a["id"]] = a
        if tag in ("script", "style"):
            self._hidden += 1
        if tag == "a":
            self._anchor = {"href": a.get("href"), "id": a.get("id"), "text": []}
            self.anchors.append(self._anchor)
        if tag not in self.VOID:
            self._stack.append((tag, a.get("id")))

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._hidden:
            self._hidden -= 1
        if tag == "a":
            self._anchor = None
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                break

    def handle_data(self, data):
        if self._hidden or not data.strip():
            return
        self.words.append((self.getpos()[0], data))
        for tag, ident in self._stack:
            self.by_tag[tag].append(data)
            if ident:
                self.by_id[ident].append(data)
        if self._anchor is not None:
            self._anchor["text"].append(data)


def read_page(name):
    parser = Readable()
    parser.feed((FRONTEND / name).read_text(encoding="utf-8"))
    parser.close()
    return parser


def text_of(parts):
    return " ".join(" ".join(parts).split())


def html_offenders(html, where):
    """(where, line, phrase, text) for every banned phrase in a page's words or attribute values."""
    parser = Readable()
    parser.feed(html)
    parser.close()
    found = []
    seen = [(line, text) for line, text in parser.words] + \
           [(line, value) for line, _tag, _name, value in parser.attrs]
    for line, text in seen:
        for phrase in BANNED:
            if phrase in squash(text):
                found.append((where, line, phrase, text.strip()[:120]))
    return found


# ── reading Python the way a person meets it ─────────────────────────────────
def python_strings(source):
    """(line, text) for every string constant that is not a docstring. Comments are not in the
    syntax tree at all, which is the point."""
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    return sorted((n.lineno, n.value) for n in ast.walk(tree)
                  if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings)


def python_offenders(source, where):
    found = []
    for line, text in python_strings(source):
        norm = squash(text)
        if any(norm.startswith(p) for p in EXEMPT_PREFIXES):
            continue
        for phrase in BANNED:
            if phrase in norm:
                found.append((where, line, phrase, text.strip()[:120]))
    return found


# ── the harness, run once ────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def ran(tmp_path_factory):
    require_node()
    config = tmp_path_factory.mktemp("v2names") / "config.json"
    config.write_text(json.dumps({
        "capabilityTable": nav_access.capability_table(),
        "banned": BANNED,
        "exemptPrefixes": EXEMPT_PREFIXES,
    }), encoding="utf-8")
    proc = run_node(HARNESS, FRONTEND, config)
    assert proc.returncode == 0, "the harness itself failed, read this before assuming a product bug:\n" + proc.stderr
    return last_json_line(proc.stdout)


# ═════════════════════════════════════════════════════════════════════════════
# 1. the sidebar, and the Admin page that draws it
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("role", ["user", "admin", "super_admin"])
def test_the_sidebar_names_the_tool_and_its_database_for_every_role(ran, role):
    """Run through auth.js for each role. Both rows keep their addresses and their BETA tag, and
    both stay under the Beta heading, which is derived from that tag."""
    rows = {r["href"]: r for r in ran["sidebar"][role]}
    assert rows[INTAKE_HREF] == {"section": "Beta", "href": INTAKE_HREF, "label": TOOL, "tag": "BETA"}
    assert rows[DATABASE_HREF] == {"section": "Beta", "href": DATABASE_HREF, "label": DATABASE, "tag": "BETA"}


def test_no_sidebar_row_still_says_polish_estimate(ran):
    labels = [r["label"] for r in ran["sidebar"]["super_admin"]]
    assert not [l for l in labels if "polish" in l.lower()], labels


def test_the_sidebar_and_the_server_name_every_tab_the_same(ran):
    """The sidebar row is written in auth.js and the Admin page also receives a label from
    nav_access.py. They are two copies of one name, and a rename that reaches one shows two names
    for one tab on the Admin page. Compared over every tab both know, not only these two."""
    server = {href: tab["label"] for href, tab in nav_access.TABS.items()}
    compared = {}
    for row in ran["sidebar"]["super_admin"]:
        if row["href"] in server:
            compared[row["href"]] = (row["label"], server[row["href"]])
    assert {INTAKE_HREF, DATABASE_HREF} <= set(compared), "the two renamed tabs were not compared"
    assert len(compared) >= 15, "suspiciously few tabs compared: %s" % sorted(compared)
    disagree = {h: v for h, v in compared.items() if v[0] != v[1]}
    assert not disagree, "the sidebar and nav_access.py disagree about: %s" % disagree


def test_the_server_table_renames_the_two_tabs_and_moves_nothing_else():
    """LABELS ONLY. The table is keyed on href; what a denied role is refused, and which API routes
    the tab owns, are what a rename must not touch."""
    tabs = nav_access.TABS
    assert tabs[INTAKE_HREF]["label"] == TOOL
    assert tabs[DATABASE_HREF]["label"] == DATABASE
    assert tuple(tabs[INTAKE_HREF]["pages"]) == (INTAKE_HREF, ESTIMATE_HREF)
    assert tuple(tabs[DATABASE_HREF]["pages"]) == (DATABASE_HREF,)
    assert tuple(tabs[INTAKE_HREF]["api"]) == () and tuple(tabs[DATABASE_HREF]["api"]) == ()
    served = {t["href"]: t["label"] for t in nav_access.capability_table()}
    assert served[INTAKE_HREF] == TOOL and served[DATABASE_HREF] == DATABASE


def test_the_admin_matrix_draws_the_new_names_from_the_real_capability_table(ran):
    """admin.js's own roleMatrixHtml, handed nav_access.capability_table(). Every row it draws takes
    its label from the sidebar, and the paragraph under it names the tabs that can only be hidden
    from the server's table, so both sources meet in one rendered page."""
    labels = dict(map(tuple, ran["admin"]["rowLabels"]))
    assert labels[INTAKE_HREF] == TOOL and labels[DATABASE_HREF] == DATABASE
    hidden_only = [n for n in ran["admin"]["notes"] if "can only be hidden" in n]
    assert len(hidden_only) == 1, ran["admin"]["notes"]
    listed = hidden_only[0].split("not sealed:")[1].split(". Every API route")[0]
    names = [n.strip() for n in listed.split(",")]
    assert TOOL in names and DATABASE in names, names      # the server's labels, in the server's order
    assert "the Item Library's assemblies also price %s," % TOOL in hidden_only[0], hidden_only[0]
    assert "Polish" not in hidden_only[0]


# ═════════════════════════════════════════════════════════════════════════════
# 2. the pages, titles and headings
# ═════════════════════════════════════════════════════════════════════════════
def test_the_three_pages_are_titled_and_headed_with_the_new_names():
    intake, estimate, database = (read_page(n) for n in
                                  ("polish-intake.html", "polish-estimate.html", "polish-estimates.html"))
    assert text_of(intake.by_tag["title"]) == "%s · Intake · Treadwell Proposal Generator" % TOOL
    assert text_of(estimate.by_tag["title"]) == "%s · Estimate · Treadwell Proposal Generator" % TOOL
    assert text_of(database.by_tag["title"]) == "%s · Treadwell Proposal Generator" % DATABASE
    assert text_of(intake.by_tag["h1"]) == "%s BETA" % TOOL
    assert text_of(estimate.by_tag["h1"]) == TOOL
    assert text_of(database.by_tag["h1"]) == DATABASE


def test_every_page_a_sidebar_row_owns_is_headed_with_that_rows_label(ran):
    """The existing rename tests make the same claim for Proposals Database and Direct Projects:
    click a row and land on a page that calls itself something else, and it reads as the wrong
    page. Derived from nav_access (which pages a row owns) and from the sidebar run (its label), so
    a third page added to either row is held to it too."""
    labels = {r["href"]: r["label"] for r in ran["sidebar"]["super_admin"]}
    checked = []
    for href in (INTAKE_HREF, DATABASE_HREF):
        for page in nav_access.TABS[href]["pages"]:
            heading = text_of(read_page(page.lstrip("/")).by_tag["h1"])
            assert heading.startswith(labels[href]), (page, heading, labels[href])
            checked.append(page)
    assert checked == [INTAKE_HREF, ESTIMATE_HREF, DATABASE_HREF]


def test_the_intake_page_says_whose_intake_it_is():
    page = read_page("polish-intake.html")
    words = " ".join(text for _line, text in page.words)
    assert "This intake belongs to %s and is deliberately" % TOOL in " ".join(words.split())
    assert "They used to be step 2 of %s and" % TOOL in " ".join(words.split())


def test_the_v2_estimates_page_uses_the_new_names_for_its_controls():
    page = read_page("polish-estimates.html")
    attrs = [(t, n, v) for _l, t, n, v in page.attrs]
    assert ("input", "placeholder", "Search v2 estimates…") in attrs
    assert ("input", "aria-label", "Search v2 estimates") in attrs
    assert ("select", "aria-label", "Sort v2 estimates by") in attrs
    assert ("select", "aria-label", "Filter by month") in attrs, "the month filter is not a rename"
    options = [text_of([t]) for t in page.by_tag["option"]]
    assert options == ["Any month", "Date updated", "Name", "Deadline", TOTAL], options
    assert text_of(page.by_id["list"]) == "Loading v2 estimates…"
    door = [a for a in page.anchors if text_of(a["text"]) == "Open %s" % TOOL]
    assert len(door) == 1 and door[0]["href"] == INTAKE_HREF, page.anchors
    sentences = " ".join(text_of([text]) for _l, text in page.words)
    assert "Every estimate priced in %s, newest first. Open one to reopen it exactly as it was saved." % TOOL in sentences
    assert "%s is what %s priced. It is not the estimate sheet's lump sum" % (TOTAL, TOOL) in sentences


# ═════════════════════════════════════════════════════════════════════════════
# 3. the two doors into the tool
# ═════════════════════════════════════════════════════════════════════════════
def test_the_estimate_review_door_names_the_tool_and_still_says_it_opens_a_test_copy():
    page = read_page("estimate-review.html")
    door = page.elements["polish-beta-link"]
    text = text_of(page.by_id["polish-beta-link"])
    assert text == "%s BETA · opens a test copy" % TOOL, text
    assert door["href"] == ESTIMATE_HREF and "hidden" in door
    title = door["title"]
    assert title.startswith("Price this polish job in %s: the same numbers in three short steps" % TOOL), title
    assert "TEST COPY" in title and "leaves this bid" in title
    assert "—" not in title and "—" not in text, "em dash in UI copy (house rule)"


def test_the_live_intake_button_names_the_tool():
    page = read_page("index.html")
    button = page.elements["beta-continue"]
    assert text_of(page.by_id["beta-continue"]) == "Continue with %s → BETA" % TOOL
    assert button["title"] == ("Price this polish job in %s: the same intake, then three short "
                               "steps instead of the spreadsheet." % TOOL)


@pytest.mark.parametrize("name, phrase", [
    ("library.html", "Assemblies are priced by %s; no live bid reads them." % TOOL),
    ("library.html", "%s prices its takeoff from these assemblies. No live bid reads them yet." % TOOL),
    ("markup.html", "and %s is not wired to any of them: its engine still runs on its own hardcoded constants." % TOOL),
    ("markup.html", "%s is separate again: it still prices off the constants built into its own engine." % TOOL),
])
def test_the_pages_that_describe_the_tool_use_its_new_name(name, phrase):
    """A sentence is either inside one attribute (a hover title) or wrapped over several text nodes
    and tags (a paragraph), so each page is searched both ways."""
    page = read_page(name)
    in_an_attribute = [squash(v) for _l, _t, _n, v in page.attrs]
    as_text = squash(" ".join(text for _l, text in page.words))
    assert any(squash(phrase) in v for v in in_an_attribute) or squash(phrase) in as_text, phrase


# ═════════════════════════════════════════════════════════════════════════════
# 4. the v2 Estimates page, run
# ═════════════════════════════════════════════════════════════════════════════
def test_the_total_column_says_whose_figure_it_is(ran):
    """"Beta total" became "v2 total" and may not be tidied to a bare "Total": the engine behind this
    page can disagree with the estimate sheet, and the word in front is what says so. The column
    set is untouched, which is what makes this a rename."""
    loaded = ran["database"]["loaded"]
    assert loaded["heads"] == ["Project", "Flag", "Type", TOTAL, "Files", "Estimator", "Due", "Updated"]
    assert ran["database"]["atTheReadCeiling"]["heads"] == loaded["heads"]


def test_a_priced_row_and_a_test_badge_carry_the_new_name_in_their_hover_text(ran):
    loaded = ran["database"]["loaded"]
    html = loaded["listHtml"]
    assert 'title="Priced in %s. Not the estimate sheet\'s lump sum"' % TOOL in html
    assert 'title="Filed as a test project. %s files every copy it makes this way"' % TOOL in html
    assert "Polish" not in html, "the table says Polish with a capital P again"
    # the page lists v2 estimates only: the row whose polish_beta is false was left out
    assert loaded["count"] == "2 estimates" and "Not beta" not in loaded["listText"]


def test_the_empty_page_names_the_tool_and_both_ways_in(ran):
    empty = ran["database"]["empty"]
    assert empty["listText"].startswith("No v2 estimates yet. An estimate lands here the moment it is priced in %s," % TOOL)
    assert "or by pressing the %s link on a polish job's Estimate Review." % TOOL in empty["listText"]
    assert "so a v2 estimate older than that will not appear here." in empty["listText"]
    assert 'href="/polish-intake.html">Start a v2 estimate</a>' in empty["listHtml"]
    assert 'href="/projects.html">Proposals Database</a>' in empty["listHtml"]
    assert "&mdash;" not in empty["listHtml"], "em dash in UI copy (house rule)"
    assert empty["toolbarHidden"] is True


def test_a_search_that_matches_nothing_counts_v2_estimates(ran):
    """Reached by a search saved in the browser's session, so the page opens on it."""
    none = ran["database"]["emptyBecauseNoneMatch"]
    assert none["listText"] == ("Nothing matches that. 2 v2 estimates are saved, but none of them "
                                "match the search or month you have set.")
    assert none["count"] == "0 of 2"
    assert "&mdash;" not in none["listHtml"]


def test_a_failed_read_is_its_own_state_in_the_new_words(ran):
    failed = ran["database"]["failed"]
    assert failed["listText"].startswith("Could not load the v2 estimates. Nothing is lost")
    assert "Try again" in failed["listText"]
    assert failed["toolbarHidden"] is True


def test_the_read_ceiling_footnote_says_v2_estimate(ran):
    ceiling = ran["database"]["atTheReadCeiling"]
    assert ceiling["ceilingHidden"] is False
    assert ceiling["ceilingText"] == ("Showing the 300 most recently updated projects. A v2 estimate "
                                      "older than that is still saved, but will not appear here.")
    assert ran["database"]["loaded"]["ceilingHidden"] is True


# ═════════════════════════════════════════════════════════════════════════════
# 5. the Proposals Database tab
# ═════════════════════════════════════════════════════════════════════════════
def test_the_proposals_database_tab_is_called_v2_estimates_and_keeps_its_key(ran):
    """The chip KEY stays "beta": the page keeps it in sessionStorage and test_projects_beta_tab.py
    selects on it. Only the label moved, and only that one of the five."""
    chips = ran["projects"]["chips"]
    assert [(c["key"], c["label"]) for c in chips] == [
        ("active", "Active"), ("inactive", "Inactive"), ("all", "All"), ("test", "Test"),
        ("beta", DATABASE)]


def test_the_empty_v2_tab_says_so_in_the_new_words(ran):
    assert ran["projects"]["emptyBetaTab"] == {"className": "empty", "text": "No v2 estimates yet."}


# ═════════════════════════════════════════════════════════════════════════════
# 6. the sandbox, down each path where it stops and says so
# ═════════════════════════════════════════════════════════════════════════════
def test_the_sandbox_names_the_tool_wherever_it_stops(ran):
    s = ran["sandbox"]
    stops = {
        "firstReadFails": "Couldn't check whether this project is filed as a test, so %s stopped "
                          "rather than risk editing a real bid. Reload to try again." % TOOL,
        "copyReadFails": "Couldn't check for this project's test copy, so %s stopped rather than "
                         "risk editing the real bid. Reload to try again." % TOOL,
        "copyCannotBeMade": "Couldn't make the test copy, so %s stopped rather than edit the real "
                            "project itself. Reload to try again." % TOOL,
    }
    for case, message in stops.items():
        assert s[case]["settled"] is False, "%s let the page carry on after a failed read" % case
        assert " ".join(s[case]["loading"].split()) == message, (case, s[case]["loading"])


def test_the_sandbox_says_who_is_editing_a_project_filed_as_a_test(ran):
    s = ran["sandbox"]
    assert s["filedAsTest"]["settled"] is True
    assert s["filedAsTest"]["note"] == ("This project is filed as a test, so %s is editing it "
                                        "directly. No real bid is involved." % TOOL)
    # the note for a project nobody has priced yet names no tool, and is unchanged
    assert s["nothingPricedYet"]["note"] == ("Nothing has been priced here yet. Whatever you enter is "
                                             "saved as a NEW test project, under the Test tab. No "
                                             "real bid is involved.")


# ═════════════════════════════════════════════════════════════════════════════
# 7. the one message the server writes
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("item_id", library.RESERVED_ITEM_IDS)
def test_removing_a_reserved_condition_line_names_the_tool(item_id):
    """library.delete_item refuses before it touches the store, so this runs with no database."""
    with pytest.raises(library.ValidationError) as refused:
        library.delete_item(item_id)
    assert str(refused.value) == ('"%s" is one of %s\'s own condition lines, so it can\'t be removed. '
                                  "Edit it on the Items tab instead." % (item_id, TOOL))


# ═════════════════════════════════════════════════════════════════════════════
# 8. the sweeps: no old name in anything a person can read
# ═════════════════════════════════════════════════════════════════════════════
def test_the_html_sweep_sees_a_planted_name_and_ignores_a_planted_comment():
    page = ("<title>Polish Estimate Database</title><p>the <b>Beta Calculator</b> here</p>"
            "<input placeholder='Search beta estimates'><a title='Beta Polish' href='/polish-estimates.html'>x</a>"
            "<!-- Polish Estimate --><script>var a = 'Polish beta';</script><style>.polish-beta{}</style>"
            "<p>Polish\n   Estimate</p><p>Estimating Tool v2</p>")
    found = html_offenders(page, "planted")
    assert sorted(set(f[2] for f in found)) == ["beta calculator", "beta estimate", "beta polish", "polish estimate"]
    assert len(found) == 5, found           # title, paragraph, placeholder, title attribute, the wrapped one
    assert html_offenders("<!-- Polish Estimate --><script>x='Polish beta'</script>"
                          "<a href='/polish-estimates.html' id='polish-beta-link'>ok</a>", "planted") == []


def test_no_page_shows_an_old_name():
    found = []
    pages = sorted(FRONTEND.glob("*.html"))
    assert len(pages) >= 20, "the sweep found suspiciously few pages"
    for page in pages:
        found.extend(html_offenders(page.read_text(encoding="utf-8"), page.name))
    assert not found, "an old name is on a page again:\n" + "\n".join("%s:%s %r in %r" % f for f in found)


def test_the_python_sweep_sees_a_planted_name_and_ignores_comments_and_docstrings():
    planted = ('"""Polish Estimate module docstring."""\n'
               "x = 'The Polish estimate beta'\n"
               "# Polish Estimate in a comment\n"
               "def f():\n"
               '    """Polish beta in a docstring."""\n'
               "    return ['ok', 'a beta  calculator']\n"
               "label = '[polish beta] a console prefix'\n")
    found = python_offenders(planted, "planted")
    assert [(f[1], f[2]) for f in found] == [(2, "polish estimate"), (6, "beta calculator")], found


def test_no_server_string_shows_an_old_name():
    found = []
    modules = sorted(p for p in BACKEND.rglob("*.py")
                     if "tests" not in p.relative_to(BACKEND).parts and ".venv" not in p.parts
                     and "__pycache__" not in p.parts)
    assert len(modules) >= 40, "the sweep found suspiciously few modules"
    for module in modules:
        found.extend(python_offenders(module.read_text(encoding="utf-8"), str(module.relative_to(BACKEND))))
    assert not found, "an old name is in a server string again:\n" + "\n".join("%s:%s %r in %r" % f for f in found)


def test_the_javascript_sweep_sees_a_planted_name_and_ignores_comments_and_log_prefixes(ran):
    planted = ran["sweep"]["planted"]
    assert planted == {"inAString": 1, "inATemplate": 1, "wrappedOverTwoLines": 1,
                       "inACommentOnly": 0, "aLogPrefix": 0, "theNewName": 0}, planted


def test_no_script_string_shows_an_old_name(ran):
    sweep = ran["sweep"]
    assert sweep["failures"] == [], "a file could not be scanned to the end: %s" % sweep["failures"]
    assert sweep["files"] >= 40 and sweep["strings"] >= 10000, (
        "the sweep read suspiciously little: %d files, %d strings" % (sweep["files"], sweep["strings"]))
    assert sweep["offenders"] == [], "an old name is in a script string again:\n" + "\n".join(
        "%(file)s:%(line)s %(phrase)r in %(text)r" % o for o in sweep["offenders"])


# ═════════════════════════════════════════════════════════════════════════════
# 9. LABELS ONLY: what must not have moved
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("name", ["polish-intake.html", "polish-estimate.html", "polish-estimates.html",
                                  "js/polish-intake.js", "js/polish-estimate.js", "js/polish-estimates.js",
                                  "js/polish-sandbox.js", "js/bid-model.js"])
def test_the_files_keep_their_names(name):
    assert (FRONTEND / name).is_file(), "%s was renamed or removed: a rename of labels moves no file" % name


def test_the_ids_the_doors_and_notes_are_found_by_did_not_move():
    review, live = read_page("estimate-review.html"), read_page("index.html")
    assert review.elements["polish-beta-link"]["class"] == "beta-link"
    assert live.elements["beta-continue"]["class"] == "btn-secondary"
    for page in ("polish-intake.html", "polish-estimate.html"):
        assert "sandbox-note" in read_page(page).elements, page
    database = read_page("polish-estimates.html")
    assert {"list", "toolbar", "q", "month", "sort", "dir", "clear", "count", "ceiling"} <= set(database.elements)


def test_a_row_on_the_v2_estimates_page_still_opens_the_tools_intake(ran):
    """Pressed for real: the page's own click listener was handed a row, and the address it sent the
    browser to is recorded. The rename did not touch where a row goes."""
    assert ran["database"]["loaded"]["opened"] == ["/polish-intake.html?d=p1"]
    assert ran["database"]["empty"]["opened"] == []


def test_the_sort_options_keep_their_keys():
    """The labels moved ("Beta total" is "v2 total"); the keys the page sorts on and keeps in
    sessionStorage did not. The month option's empty value is the "any month" choice."""
    page = read_page("polish-estimates.html")
    keys = [v for _l, t, n, v in page.attrs if (t, n) == ("option", "value")]
    assert keys == ["updated", "name", "deadline", "total"], keys


def test_a_test_copy_is_still_named_the_way_the_sandbox_and_the_tab_find_it(ran):
    """"(beta test)" is saved on every copy and read back to tell a copy from a real bid, so it is
    data and not a label. Renaming it would orphan every copy already filed. Run through the
    sandbox's own betaName and sandboxIdFor."""
    assert ran["sandbox"]["naming"] == {
        "copyName": "Real job (beta test)",
        "renamedTwice": "Real job (beta test)",
        "nameless": "Untitled (beta test)",
        "copyId": "d1-beta",
    }
