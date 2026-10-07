"""The workbook oracle, as CI sees it: recorded answers, and the guards that say when they are stale.

THE ORACLE is Kyle's estimate workbook evaluated by the HyperFormula the Estimate Review page runs, with
numbers typed into the boundary cells of each priced tab (backend/tests/js/workbook-oracle.js). Its
answers are recorded in backend/tests/fixtures/oracle/<tab>.json, one file per priced tab, plus
meta.json. Later phases of the v2 program check every v2 tab against them.

CI HAS NO HYPERFORMULA, ON PURPOSE (the repository has no package.json and no node_modules), so CI cannot
recompute anything. What it can do, and what this module does, is refuse to trust the recorded answers
when what they were recorded FROM has moved:

  - Kyle's template has a different formula or constant in a priced tab  -> "re-run the oracle"
  - Kyle's template defines a name (Silica, Glaze4) differently          -> "re-run the oracle"
  - the page now pins a different HyperFormula                           -> "re-run the oracle"
  - frontend/js/xl-excel-rounding.js changed                             -> "re-run the oracle"
  - a recorded file, or the cell maps in bid-profiles.js, is not the one
    the oracle hashed when it wrote them (meta.json `integrity`)          -> "re-run the oracle"
  - the oracle's engine setup is no longer the page's (options, alias rule, the named-expression block,
    HF.loadSheet and the order they run in)                              -> fails
  - a recorded file is missing, short of a case it must hold, or does not add up

and it checks that the guards themselves work. The template guard is run on edited copies of the
template, and must go red on a changed formula, a changed constant and a defined name (Silica) pointed at another
cell, and stay green on a copy that is merely re-saved, on an edit to a tab it does not cover, and on the same
names written in another order. The integrity guard is run on a recorded file edited by hand in a way every
other check here accepts (gp and total both raised by 1,000), and stays green on the same files with Windows line
endings. The engine guard is run on scratch copies of the page and of engine.js with one line changed each.

Where HyperFormula IS installed (a developer's machine with NODE_PATH set), one more test recomputes
everything and requires it to match the recorded files byte for byte.
"""
import base64
import copy
import hashlib
import html.parser
import json
import re
import shutil
import subprocess
import zipfile

import pytest

import _oracle_support as S
from _node import last_json_line, require_node, run_node

REGEN = ("re-run the oracle: node backend/tests/js/workbook-oracle.js --write  (it needs hyperformula@2.7.1 "
         "installed outside the repo, see the header of that file), then review the fixture diff")


@pytest.fixture(scope="module")
def profiles():
    require_node()
    return S.profiles()


@pytest.fixture(scope="module")
def meta():
    return S.load_meta()


@pytest.fixture(scope="module")
def goldens(profiles):
    return {tab: S.load_golden(profiles["sheets"][tab]["slug"]) for tab in profiles["priced"]}


class _Scripts(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.tags.append(dict(attrs))


def page_pin() -> dict:
    """The HyperFormula <script> of frontend/estimate-review.html: version, src and integrity."""
    scripts = _Scripts()
    scripts.feed((S.FRONTEND / "estimate-review.html").read_text(encoding="utf-8"))
    scripts.close()
    hits = [t for t in scripts.tags if "hyperformula@" in (t.get("src") or "")]
    assert len(hits) == 1, "estimate-review.html must load hyperformula from exactly one <script>"
    src = hits[0]["src"]
    return {"version": src.split("hyperformula@")[1].split("/")[0], "src": src, "sri": hits[0]["integrity"]}


# ── the recorded set is all there ────────────────────────────────────────────
def test_the_recorded_set_is_complete(profiles, meta, goldens):
    priced = profiles["priced"]
    assert len(priced) == 11, "the eleven priced tabs: Epoxy, Polish, Seal, Seal (+Jnts), Epoxy blank, Leveling, five Gyp"
    assert meta["schema"] == 1 and meta["template"]["sheets"] == priced
    assert set(meta["sheets"]) == set(priced)
    slugs = [profiles["sheets"][t]["slug"] for t in priced]
    assert len(set(slugs)) == len(slugs)
    for tab in priced:
        g, m = goldens[tab], profiles["sheets"][tab]
        assert (g["sheet"], g["slug"], g["family"]) == (tab, m["slug"], m["family"]), tab
        assert meta["sheets"][tab] == {"slug": m["slug"], "family": m["family"],
                                       "vectors": len(g["vectors"]), "probes": len(g["probes"])}, tab
        ids = [v["id"] for v in g["vectors"]]
        assert len(ids) == len(set(ids)), tab + ": two cases share an id"
        names = set(m["flags"]) | set(m["inputs"]) | set(m["rates"])
        for v in g["vectors"]:
            assert set(v["in"]) <= names, (tab, v["id"], set(v["in"]) - names)
            assert set(m["outputs"]) <= set(v["out"]), (tab, v["id"], "an output is missing")
        assert set(g["fixed"]) == set(m["fixed"]), tab
    expected = {s + ".json" for s in slugs} | S.NOT_ANSWER_FILES
    assert {p.name for p in S.ORACLE.glob("*.json")} == expected, "an unexpected or missing file in fixtures/oracle"
    assert set(meta["integrity"]["files"]) == {s + ".json" for s in slugs}, "meta.json must hash every recorded sheet file, and only those"


def test_every_tab_was_tried_at_every_kind_of_case(goldens):
    for tab, g in goldens.items():
        kinds = {v["id"].split("/")[0] for v in g["vectors"]}
        assert kinds >= {"base", "size", "scale", "sf", "flags", "remodel", "money", "bond", "edge", "lodging"}, tab
        assert len([v for v in g["vectors"] if v["id"].startswith("flags/")]) == 96, tab + ": 32 settings at 3 sizes"


# ── the guards: the answers are only good while what they came from stands ───
def test_the_template_has_not_changed_since_the_oracle_ran(profiles, meta):
    digest, cells, names = S.template_hash(profiles["priced"])
    rec = meta["template"]
    assert (digest, cells, names) == (rec["hash"], rec["cells"], rec["names"]), (
        "Kyle's template now has a different formula or constant in a priced tab, or defines a name differently "
        "(cells hashed: %d now, %d recorded; defined names: %d now, %d recorded), than the template the oracle "
        "recorded its answers from, so those answers may no longer be his workbook's. " % (cells, rec["cells"], names, rec["names"])
        + REGEN)


@pytest.fixture(scope="module")
def edits(tmp_path_factory):
    """Copies of the template: re-zipped (new bytes, same workbook), re-saved through openpyxl with an unpriced
    tab edited (every cached value dropped), a formula edited, and a constant edited."""
    from openpyxl import load_workbook
    root = tmp_path_factory.mktemp("template_copies")
    out = {"original": S.TEMPLATE_PATH}

    rezip = root / "rezipped.xlsx"
    with zipfile.ZipFile(S.TEMPLATE_PATH) as src, zipfile.ZipFile(rezip, "w", zipfile.ZIP_STORED) as dst:
        for name in reversed(src.namelist()):
            dst.writestr(name, src.read(name))
    out["rezipped"] = rezip

    def saved(name, edit):
        wb = load_workbook(S.TEMPLATE_PATH, keep_vba=False)
        edit(wb)
        path = root / (name + ".xlsx")
        wb.save(path)
        return path

    # openpyxl writes formulas with no saved value, so this is a re-save that drops every cached figure; it
    # also edits a tab the guard does not cover, which has to be as invisible to it as the re-save is.
    out["openpyxl re-save with an unpriced tab edited"] = saved(
        "resaved", lambda wb: wb["Takeoff"].__setitem__("A1", "changed"))
    out["a formula"] = saved("formula", lambda wb: wb["Polish"].__setitem__("D31", "=ROUNDUP(SUM(D17:D30),1)"))
    out["a constant"] = saved("constant", lambda wb: wb["Polish"].__setitem__("B32", 0.03))
    return out


def test_the_guard_ignores_a_resave_and_an_unpriced_tab_and_catches_a_real_edit(edits):
    """Run the guard's own hash on edited copies of the template. Only Polish is hashed here: the
    guard is the same function for every tab, and one tab keeps this fast."""
    sheets = ["Polish"]
    base = S.template_hash(sheets, edits["original"])
    for name in ("rezipped", "openpyxl re-save with an unpriced tab edited"):
        assert S.template_hash(sheets, edits[name]) == base, (
            name + " changes nothing the workbook computes in a priced tab, and the guard must not fire on it")
    for name in ("a formula", "a constant"):
        assert S.template_hash(sheets, edits[name]) != base, (
            "an edited " + name + " in a priced tab must move the hash, or the guard guards nothing")


def test_the_resaved_copy_really_dropped_what_a_resave_may_change(edits):
    """The re-save above is only a fair test if it changed something a save can change: the cached
    values. openpyxl writes formulas with no saved value, so the copy has none."""
    values = S.ew._load_template
    cached = values(data_only=True, path=S.TEMPLATE_PATH)["Polish"]["D64"].value
    after = values(data_only=True, path=edits["openpyxl re-save with an unpriced tab edited"])["Polish"]["D64"].value
    assert cached is not None and after is None


# ── the workbook's defined names are part of what the answers came from ──────
SILICA = '<definedName name="Silica">Epoxy!$W$145</definedName>'
QUARTZ = '<definedName name="Q28_40s">Epoxy!$W$148</definedName>'


def _once(text, old, new):
    """`text` with `old` replaced by `new`, and a refusal to go on unless `old` was there exactly once: an edit that
    applied nowhere, or everywhere, would let the tests below pass for the wrong reason."""
    assert text.count(old) == 1, "the anchor %r is in xl/workbook.xml %d times, not once" % (old, text.count(old))
    return text.replace(old, new)


@pytest.fixture(scope="module")
def name_edits(tmp_path_factory):
    """Copies of the template whose xl/workbook.xml differs in its defined names, and in nothing else: every other
    part of the file is copied across byte for byte, so no cell of any tab has changed."""
    root = tmp_path_factory.mktemp("template_names")
    out = {}

    def rewrite(label, edit):
        path = root / ("names%d.xlsx" % len(out))
        with zipfile.ZipFile(S.TEMPLATE_PATH) as src, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                data = src.read(item.filename)
                if item.filename == "xl/workbook.xml":
                    data = edit(data.decode("utf-8")).encode("utf-8")
                dst.writestr(item, data)
        out[label] = path

    rewrite("Silica pointed at another cell", lambda xml: _once(xml, SILICA, SILICA.replace("$W$145", "$W$146")))
    rewrite("a name added", lambda xml: _once(xml, "</definedNames>", '<definedName name="Extra_Name">Epoxy!$A$1</definedName></definedNames>'))
    rewrite("a name removed", lambda xml: _once(xml, SILICA, ""))
    rewrite("a name renamed", lambda xml: _once(xml, SILICA, SILICA.replace('"Silica"', '"Silica2"')))
    # the same two definitions swapped in the file: nothing is defined differently
    rewrite("two names swapped in the file", lambda xml: _once(_once(_once(xml, SILICA, "@@SILICA@@"), QUARTZ, SILICA), "@@SILICA@@", QUARTZ))
    return out


def _cells_only_hash(path):
    """The material the guard hashed BEFORE defined names were added to it: the normalised cells and nothing else."""
    return S.hash_cells(S.normalised_cells(["Polish"], path))


NAME_CHANGES = ["Silica pointed at another cell", "a name added", "a name removed", "a name renamed"]


@pytest.mark.parametrize("label", NAME_CHANGES)
def test_a_name_defined_differently_moves_the_template_hash_though_no_cell_changed(name_edits, label):
    """Silica is used by the Epoxy tab's aggregate prices (`IF($A$22=$R$189,Q28_40s,...,Silica)`). Point it at another
    cell and Epoxy prices differently while every cell of every tab reads exactly as before. The guard that hashed
    cells only was blind to that: the first assert shows the copy IS invisible to a cells-only hash (so the test is not
    vacuous), the second that the hash now sees it, in a tab (Polish) that never mentions the name."""
    copy = name_edits[label]
    assert _cells_only_hash(copy) == _cells_only_hash(S.TEMPLATE_PATH), (
        label + ": the copy must differ in a name only, or this test proves nothing about names")
    # the DIGEST is compared, not the whole tuple: it also carries how many names there are, and a guard that hashed no names at
    # all would still notice an added or a removed one by that count alone
    assert S.template_hash(["Polish"], copy)[0] != S.template_hash(["Polish"])[0], (
        label + ": the template guard did not notice a changed defined name, so it guards the cells and not the workbook")


def test_the_same_names_in_another_order_do_not_move_the_template_hash(name_edits):
    """Excel writes the names in an order of its own choosing and a re-save may change it; nothing is defined differently."""
    assert S.template_hash(["Polish"], name_edits["two names swapped in the file"]) == S.template_hash(["Polish"])


def test_the_names_the_guard_hashes_are_the_ones_the_engine_registers(meta):
    """meta.json records how many names the engine registered when the oracle ran (engine.namesRegistered) and how many the
    guard hashes: they are the same list, read by the same function the page's names come from."""
    assert meta["engine"]["namesRegistered"] == meta["template"]["names"] == len(S.named_expressions())
    assert [n["name"] for n in S.named_expressions()].count("Silica") == 1, "the name this section is about is in the list"
    assert S.named_expressions(S.TEMPLATE_PATH) == S.named_expressions(S.TEMPLATE_PATH.parent / ".." / "templates" / S.TEMPLATE_PATH.name)


def test_reading_a_copys_names_leaves_the_apps_loader_in_place(name_edits):
    """A copy is read by pointing estimate_writer's loader at it for the length of one call; it has to be put back,
    including when the read fails."""
    real = S.ew._load_template
    S.named_expressions(name_edits["a name added"])
    assert S.ew._load_template is real
    with pytest.raises(Exception):
        S.named_expressions(S.TEMPLATE_PATH.parent / "no-such-template.xlsx")
    assert S.ew._load_template is real


def test_the_page_still_ships_the_hyperformula_the_oracle_ran_on(meta):
    pin = page_pin()
    rec = meta["engine"]["hyperformula"]
    assert (pin["version"], pin["sri"]) == (rec["version"], rec["sri"]), (
        "estimate-review.html pins a different HyperFormula than the oracle's answers were computed on. " + REGEN)


def test_the_shipped_rounding_plugin_is_the_one_the_answers_were_computed_with(meta):
    text = (S.FRONTEND / "js" / "xl-excel-rounding.js").read_text(encoding="utf-8").lstrip("﻿")
    digest = hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()
    assert digest == meta["engine"]["plugin"]["sha256"], (
        "frontend/js/xl-excel-rounding.js changed since the oracle ran: ROUNDUP and CEILING may round differently. " + REGEN)


@pytest.fixture(scope="module")
def engine_harness():
    require_node()
    proc = run_node(S.TESTS / "js" / "oracle-engine-harness.js")
    assert proc.returncode == 0, proc.stderr
    return last_json_line(proc.stdout)


def test_the_engine_options_are_the_pages_own(engine_harness, meta):
    """HF.init is lifted out of estimate-review.js and run against a stand-in that records what
    buildEmpty was given. That, docs/excel-parity-audit/engine.js and the recorded meta must agree."""
    page, engine = engine_harness["page"], engine_harness["engine"]
    assert page["options"] == engine["options"] == meta["engine"]["options"] == {"licenseKey": "gpl-v3", "smartRounding": False}


def test_the_alias_rule_and_the_formula_rewrite_are_the_pages_own(engine_harness):
    page, engine = engine_harness["page"], engine_harness["engine"]
    assert page["alias"] == engine["alias"]
    assert page["rewrite"] == engine["rewrite"]
    assert page["alias"][0] == "Glaze_4" and page["rewrite"][1] == "=Glaze_4*2+Glaze45", "the table is not vacuous"


def test_the_node_side_reads_the_same_pin_and_hashes_the_same_way(engine_harness):
    assert engine_harness["pin"] == page_pin()
    assert engine_harness["sriOfAbc"] == "sha384-" + base64.b64encode(hashlib.sha384(b"abc").digest()).decode()
    assert "exactly one" in engine_harness["twoTagsError"]


# ── the page's own loading of the workbook, run beside engine.js's ───────────
def load_problems(result) -> list:
    """How the page's way of building the workbook differs from engine.js's, as sentences ([] when they agree).

    oracle-engine-harness.js ran the page's HF.init, its named-expression block and its HF.loadSheet, and
    engine.build(), each against a recorder that kept every call made to HyperFormula in order. The two
    lists have to be equal, the aliases they ended with and the number of names they registered too, and the
    page's boot function has to add the sheets, register the names and only then load cells. Returns what is
    wrong instead of asserting, so the tests below can be run on a copy of the page or of engine.js with one
    line changed and shown to notice."""
    load = result["load"]
    page, engine = load["page"], load["engine"]
    problems = []
    if page["calls"] != engine["calls"]:
        n = next((i for i, (a, b) in enumerate(zip(page["calls"], engine["calls"])) if a != b),
                 min(len(page["calls"]), len(engine["calls"])))
        problems.append("HyperFormula is called differently from call %d on: the page made %s, engine.js made %s"
                        % (n, page["calls"][n:n + 1], engine["calls"][n:n + 1]))
    if page["aliases"] != engine["aliases"]:
        problems.append("the page ends with the aliases %s, engine.js with %s" % (page["aliases"], engine["aliases"]))
    if page["registered"] != engine["registered"]:
        problems.append("the page registered %s of its names, engine.js %s" % (page["registered"], engine["registered"]))
    if not load["order"]["ok"]:
        problems.append("the page's boot function no longer runs HF.init, then the named expressions, and only then "
                        "HF.loadSheet (positions %s)" % load["order"])
    return problems


def test_the_page_builds_the_workbook_the_way_engine_js_does(engine_harness):
    assert load_problems(engine_harness) == []


def test_that_comparison_takes_every_branch_of_the_pages_name_block_and_loads_every_shape_of_sheet(engine_harness):
    """The two lists would be equal if both were empty. They are not: the fixture drives a name that is refused and
    aliased, one that is refused for another reason, one scoped to the first sheet (id 0, which is falsy), one scoped
    to a tab that does not exist, one that throws, and one whose alias throws too, then loads a sheet with gaps, one
    with no cells at all, and one whose formula holds an aliased name inside a string."""
    load = engine_harness["load"]
    page, engine = load["page"], load["engine"]
    assert page["aliases"] == {"Glaze4": "Glaze_4", "AB12": "AB_12", "Reserved": "Reserved_n"}, "Zed9's alias threw, so it is not kept"
    assert page["registered"] == [6, 8] and engine["warnings"] == 2
    adds = {c[1]: c for c in page["calls"] if c[0] == "addNamedExpression"}
    assert adds["Local_Rate"][3] == 0, "a name scoped to the first sheet is added with its scope, id 0"
    assert len(adds["Orphan"]) == 3 and len(adds["Silica"]) == 3, "no scope, or a scope the workbook lacks, is added without one"
    assert {"Glaze_4", "AB_12", "Reserved_n", "Zed_9", "Refused"} <= set(adds)
    grids = {c[1]: c[2] for c in page["calls"] if c[0] == "setSheetContent"}
    assert grids[1] == [], "a sheet with no cells is loaded as an empty grid"
    assert len(grids[0]) == 5 and all(len(row) == 7 for row in grids[0]), "the grid is as big as the furthest cell"
    assert grids[0][1][1].startswith("=SUM(Glaze_4)+Glaze_4*2+Glaze45+AB_12"), "formulas are rewritten to the aliases, whole tokens only"
    assert grids[0][4][6] == "=Glaze4", "a constant is not a formula and is not rewritten"
    assert load["fixture"] == {"names": 8, "sheets": 3} and len(page["calls"]) == len(engine["calls"]) > 20


def _scratch_root(tmp_path, *edits):
    """A directory laid out like the repository, holding only what the harness reads, with one line of the page or of
    engine.js changed. An edit is (path under the repo root, one line of text that is there exactly once, its replacement)."""
    root = tmp_path / "repo"
    for rel in ("docs/excel-parity-audit/engine.js", "frontend/js/estimate-review.js", "frontend/estimate-review.html"):
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((S.REPO / rel).read_bytes())
    for rel, old, new in edits:
        assert "\n" not in old and "\r" not in old, "anchor an edit on one line, so CRLF and LF checkouts both match"
        text = (root / rel).read_bytes().decode("utf-8")
        assert text.count(old) == 1, "%r is in %s %d times, not once: the edit would prove nothing" % (old, rel, text.count(old))
        (root / rel).write_bytes(text.replace(old, new).encode("utf-8"))
    return root


def _harness_on(root):
    proc = run_node(S.TESTS / "js" / "oracle-engine-harness.js", root)
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-3000:]
    return last_json_line(proc.stdout)


PAGE_JS = "frontend/js/estimate-review.js"
ENGINE_JS = "docs/excel-parity-audit/engine.js"
LOAD_BREAKS = {
    "page: the suffix of an alias with no digits": (PAGE_JS, 'if (a === name) a = name + "_n";', 'if (a === name) a = name + "_x";'),
    "page: a scope test that drops sheet id 0": (
        PAGE_JS, "if (scopeId !== undefined) HF.instance.addNamedExpression(regName, n.expression, scopeId);",
        "if (scopeId) HF.instance.addNamedExpression(regName, n.expression, scopeId);"),
    "page: loadSheet gives an empty sheet a row": (
        PAGE_JS, "const maxRow = Math.max(...cells.map(c => c.row), 0);", "const maxRow = Math.max(...cells.map(c => c.row), 1);"),
    "page: loadSheet puts a cell one column over": (
        PAGE_JS, "data[c.row - 1][c.col - 1] = cellInput;", "data[c.row - 1][c.col] = cellInput;"),
    "page: a sheet is loaded before the names": (
        PAGE_JS, "const nameData = await _namedReady;",
        'HF.loadSheet("Epoxy", [{ addr: "A1", row: 1, col: 1, value: 1 }]); const nameData = await _namedReady;'),
    "page: an alias that would not register is kept": (PAGE_JS, "delete HF.nameAliases[n.name];", "void 0;"),
    "engine.js: an alias that would not register is kept": (ENGINE_JS, "aliases.delete(n.name);", "void 0;"),
    "engine.js: every name registered without its scope": (
        ENGINE_JS, "const scopeId = (n.scope && ids.has(n.scope)) ? ids.get(n.scope) : undefined;", "const scopeId = undefined;"),
    "engine.js: formulas loaded without the alias rewrite": (
        ENGINE_JS, "data[c.row - 1][c.col - 1] = c.formula != null ? rewrite(c.formula) : (c.value === undefined ? null : c.value);",
        "data[c.row - 1][c.col - 1] = c.formula != null ? c.formula : (c.value === undefined ? null : c.value);"),
    "engine.js: the suffix of an alias with no digits": (ENGINE_JS, 'return a === name ? name + "_n" : a;', 'return a === name ? name + "_x" : a;'),
}


def test_the_unbroken_scratch_copy_passes_so_the_breaks_below_are_the_only_difference(tmp_path):
    assert load_problems(_harness_on(_scratch_root(tmp_path))) == []


@pytest.mark.parametrize("label", list(LOAD_BREAKS))
def test_changing_one_line_of_the_page_or_of_engine_js_turns_the_comparison_red(tmp_path, label):
    rel, old, new = LOAD_BREAKS[label]
    problems = load_problems(_harness_on(_scratch_root(tmp_path, (rel, old, new))))
    assert problems, label + ": the page and engine.js now build the workbook differently and nothing noticed"


# ── what is recorded adds up, and holds the cases it exists for ──────────────
def _thresholds(formula):
    seen = {}
    for m in re.finditer(r"([<>]=?)\s*(\d+(?:\.\d+)?)", formula):
        seen[m.group(2)] = {"op": m.group(1), "at": float(m.group(2)) if "." in m.group(2) else int(m.group(2))}
    return sorted(seen.values(), key=lambda t: t["at"])


def test_the_ladder_edges_on_record_are_the_ones_in_the_template(profiles, meta):
    """The edges are read out of the formula text, so a rung added to a ladder shows up here as well as
    in the template guard."""
    for tab in profiles["priced"]:
        m = profiles["sheets"][tab]
        recorded = meta["ladders"][tab]
        assert [(l["cell"], l["on"], l.get("needs")) for l in recorded] == [(l["cell"], l["on"], l.get("needs")) for l in m["ladders"]], tab
        for l in recorded:
            assert l["edges"] == _thresholds(m["outputs"][l["cell"]]["formula"]), (tab, l["cell"])
            assert l["edges"], (tab, l["cell"], "a ladder with no edges is not a ladder")


# The side of an edge a value ON it falls on: `<` and `>=` put it with the values above, `<=` and `>` with those below.
ON_EDGE_IS_ABOVE = {"<": True, ">=": True, "<=": False, ">": False}


def edge_problems(profiles, meta, goldens):
    """(problems, checked): every edge of every ladder needs a dollar below, on and above, they must land
    where their ids say, a value ON the edge must fall on the side the operator puts it, and the rung must
    really change across the edge. Returns what is wrong instead of asserting, so the test below can be run on
    evidence that has been doctored and shown to notice."""
    problems, checked = [], 0
    for tab in profiles["priced"]:
        by = {v["id"]: v for v in goldens[tab]["vectors"]}
        for ladder in meta["ladders"][tab]:
            for edge in ladder["edges"]:
                variants = ["/local1", "/local0"] if ladder.get("needs") else [""]
                moved = []
                for variant in variants:
                    got = {}
                    for off in (-1, 0, 1):
                        vid = "edge/%s/%s/%s%s" % (ladder["cell"], edge["at"], ("+%d" % off) if off > 0 else str(off), variant)
                        v = by.get(vid)
                        if v is None:
                            problems.append((tab, vid, "is missing"))
                            continue
                        landed = v["in"]["material"] if ladder["on"] == "material" else v["out"]["subTotal"]
                        if landed != edge["at"] + off:
                            problems.append((tab, vid, "lands on %r, not %r" % (landed, edge["at"] + off)))
                        got[off] = v["out"][ladder["cell"]]
                    if len(got) < 3:
                        continue
                    on_edge = got[1] if ON_EDGE_IS_ABOVE[edge["op"]] else got[-1]
                    if got[0] != on_edge:
                        problems.append((tab, ladder["cell"], edge, variant, "a value ON the edge falls on the other side of it", got))
                    moved.append(got[-1] != got[1])
                    checked += 1
                if not any(moved):
                    problems.append((tab, ladder["cell"], edge, "the rung does not change across this edge in any variant: vacuous"))
    return problems, checked


def test_every_edge_of_every_ladder_has_a_dollar_below_on_and_above_and_they_straddle_it(profiles, meta, goldens):
    problems, checked = edge_problems(profiles, meta, goldens)
    assert not problems, problems[:5]
    assert checked >= 90, "11 tabs, 96 edge settings today"


def _doctored(goldens, tab, vid, edit):
    bad = copy.deepcopy(goldens)
    edit(next(v for v in bad[tab]["vectors"] if v["id"] == vid))
    return bad


def test_the_edge_check_notices_a_golden_that_has_been_tampered_with(profiles, meta, goldens):
    """The same check, on recorded answers that have been altered, has to find something wrong each time."""
    cases = [
        # a value ON a `<` edge put on the wrong side of it
        ("Polish", "edge/gpPct/6500/0", lambda v: v["out"].__setitem__("gpPct", 0.52)),
        # a case that no longer lands on its edge
        ("Epoxy", "edge/gpPct/15000/-1", lambda v: v["out"].__setitem__("subTotal", 14000)),
        # an edge across which nothing changes: the rung above made the same as the rung below
        ("Leveling", "edge/gpPct/22500/+1", lambda v: v["out"].__setitem__("gpPct", 0.45)),
        # an inclusive (`<=`) shipping edge put on the wrong side of it
        ("Epoxy", "edge/shipPct/5000/0", lambda v: v["out"].__setitem__("shipPct", 0.11)),
    ]
    for tab, vid, edit in cases:
        problems, _ = edge_problems(profiles, meta, _doctored(goldens, tab, vid, edit))
        assert problems, (tab, vid, "the edge check did not notice")
    gone = copy.deepcopy(goldens)
    gone["Gyp (FR)"]["vectors"] = [v for v in gone["Gyp (FR)"]["vectors"] if not v["id"].startswith("edge/softPct/334900/")]
    assert edge_problems(profiles, meta, gone)[0], "a missing edge case must be noticed"


def test_every_question_is_answered_both_ways_and_the_money_inputs_are_all_exercised(profiles, goldens):
    for tab, g in goldens.items():
        m = profiles["sheets"][tab]
        for flag in m["flags"]:
            values = {v["in"][flag] for v in g["vectors"] if flag in v["in"]}
            assert values == {True, False}, (tab, flag)
        rates = sorted({v["in"]["remodelPct"] for v in g["vectors"] if "remodelPct" in v["in"]})
        assert len(rates) >= 6 and 0 in rates and 0.07975 in rates, (tab, rates)
        assert {v["in"].get("fees", 0) for v in g["vectors"]} >= {0, 1, 250, 1200, 5000}, tab
        assert {v["in"].get("contingency", 0) for v in g["vectors"]} >= {0, 250, 500, 2500}, tab
        assert {v["in"]["bondPct"] for v in g["vectors"] if "bondPct" in v["in"]} == {0.01, 0.0125, 0.02}, tab
        totals = [v["out"]["subTotal"] for v in g["vectors"]]
        assert min(totals) <= 100 and max(totals) >= 1_000_000, (tab, "small and big jobs")


def total_problems(goldens):
    """Every tab's total is SUM(sub-total, GP, hard bid, super/PTO, soft costs, contingency, taxes, fees and
    bond): the one identity all eleven tabs share. A recorded file that was edited by hand, or recorded from a
    broken load, would not add up."""
    problems, n = [], 0
    for tab, g in goldens.items():
        for v in g["vectors"]:
            o, i = v["out"], v["in"]
            ident = (tab, v["id"])
            if o["total"] != (o["subTotal"] + o["gp"] + o["hardBid"] + o["superPto"] + o["softCosts"]
                              + i.get("contingency", 0) + o["taxes"] + o["feesAndBond"]):
                problems.append(ident + ("total",))
            if o["taxes"] != o["salesTax"] + o["remodelTax"]:
                problems.append(ident + ("taxes",))
            if o["feesAndBond"] != i.get("fees", 0) + o["bond"]:
                problems.append(ident + ("fees and bond",))
            if abs(o["perSf"] - o["total"] / i["sf"]) > 1e-9:
                problems.append(ident + ("per SF",))
            for flag, answer in o["answers"].items():
                if flag in i and i[flag] != answer:
                    problems.append(ident + ("the answer the sheet holds is not the one typed", flag))
            n += 1
    return problems, n


def test_each_recorded_bid_adds_up_the_way_the_sheets_own_total_does(goldens):
    problems, n = total_problems(goldens)
    assert not problems, problems[:5]
    assert n >= 1900


def test_the_total_check_notices_a_changed_number(goldens):
    for key in ("total", "taxes", "feesAndBond", "perSf"):
        bad = _doctored(goldens, "Seal", "size/mid", lambda v, key=key: v["out"].__setitem__(key, v["out"][key] + 1))
        assert total_problems(bad)[0], key
    bad = _doctored(goldens, "Polish", "flags/mid/L1T1P1R0H0", lambda v: v["out"]["answers"].__setitem__("prevailingWage", False))
    assert total_problems(bad)[0], "an answer the sheet did not take must be noticed"


# ── the recorded files are the ones the oracle wrote ─────────────────────────
def assert_recorded_files_are_the_oracles(meta, directory=S.ORACLE, profiles_js=S.PROFILES_JS):
    """What CI asks of the recorded answers: every sheet file and the cell maps hash to what the oracle recorded in
    meta.json when it wrote them. A function and not a test body, so the proofs below can hand it a doctored
    directory and see it refuse."""
    problems = S.integrity_problems(meta, directory, profiles_js)
    assert not problems, "; ".join(problems) + ". " + REGEN


def test_the_recorded_files_and_the_cell_maps_are_the_ones_the_oracle_hashed(meta):
    assert_recorded_files_are_the_oracles(meta)


def test_the_hash_of_every_file_is_the_same_in_node_and_in_python(meta):
    """The oracle (node) writes the hash and CI (python) recomputes it: two implementations, so a disagreement about
    line endings or text shows up here and not as a mysterious red on someone else's checkout. A Windows checkout holds
    these files with CRLF (core.autocrlf), which is the realistic case, so it is checked too."""
    for name, recorded in meta["integrity"]["files"].items():
        raw = (S.ORACLE / name).read_bytes()
        assert S.text_sha256(raw) == recorded, name
        assert S.text_sha256(raw.decode("utf-8").replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")) == recorded, name + " as a CRLF checkout"


def _number_span(line, key):
    """(start, end) of the number written after `"key":` in one line of a recorded file; the key has to be there once."""
    marker = '"%s":' % key
    assert line.count(marker) == 1, (key, "is not in the line exactly once")
    start = line.index(marker) + len(marker)
    end = start
    while line[end] in "+-0123456789.eE":
        end += 1
    return start, end


def hand_edited(text, case_id, bumps):
    """`text`, a recorded sheet file, with the figures of ONE case raised by the amounts in `bumps` ({key: amount}).
    Text surgery on that case's line alone: not a parse and a re-write, so the one thing that differs from the
    original is what a person with an editor would have changed."""
    lines = text.split("\n")
    at = [i for i, line in enumerate(lines) if line.startswith('{"id":"%s",' % case_id)]
    assert len(at) == 1, (case_id, "is not on exactly one line")
    line = lines[at[0]]
    for key, amount in bumps.items():
        start, end = _number_span(line, key)
        old = line[start:end]
        new = int(old) + amount if old.lstrip("-").isdigit() else repr(float(old) + amount)
        line = line[:start] + str(new) + line[end:]
    lines[at[0]] = line
    return "\n".join(lines)


def _oracle_copy(tmp_path):
    """A scratch copy of fixtures/oracle with the LF text of every file, i.e. what a Linux checkout has."""
    target = tmp_path / "oracle"
    target.mkdir()
    for f in S.ORACLE.glob("*.json"):
        target.joinpath(f.name).write_bytes(f.read_bytes().decode("utf-8").replace("\r\n", "\n").encode("utf-8"))
    return target


def test_a_golden_edited_by_hand_so_that_it_still_adds_up_is_caught_by_the_hash_and_by_nothing_else(profiles, meta, goldens, tmp_path):
    """The gap this guard closes. One Seal case has its gross profit and its total both raised by 1,000 (and its per-SF
    figure with them): the sheet's own identity still holds, so every arithmetic check on the recorded answers passes.
    Only the recorded hash sees it."""
    original = (S.ORACLE / "seal.json").read_bytes().decode("utf-8").replace("\r\n", "\n")
    before = next(v for v in goldens["Seal"]["vectors"] if v["id"] == "size/mid")
    edited = hand_edited(original, "size/mid", {"gp": 1000, "total": 1000, "perSf": 1000 / before["in"]["sf"]})
    assert edited != original

    # the edit is the one meant, and a valid recorded file
    doctored = json.loads(edited)
    after = next(v for v in doctored["vectors"] if v["id"] == "size/mid")
    assert (after["out"]["gp"], after["out"]["total"]) == (before["out"]["gp"] + 1000, before["out"]["total"] + 1000)
    assert [v["id"] for v in doctored["vectors"]] == [v["id"] for v in goldens["Seal"]["vectors"]]

    # 1. every check that reads the recorded answers is satisfied by it
    bad = copy.deepcopy(goldens)
    bad["Seal"] = doctored
    assert total_problems(bad)[0] == [], "the doctored case must still add up, or this test is not about the hash"
    assert edge_problems(profiles, meta, bad)[0] == []

    # 2. the hash is the only thing that is not: a control first (the untouched LF text passes), then the doctored file
    scratch = _oracle_copy(tmp_path)
    assert_recorded_files_are_the_oracles(meta, scratch)
    (scratch / "seal.json").write_bytes(edited.encode("utf-8"))
    with pytest.raises(AssertionError, match="re-run the oracle") as refused:
        assert_recorded_files_are_the_oracles(meta, scratch)
    assert "seal.json is not the file the oracle wrote" in str(refused.value)
    assert S.integrity_problems(meta, scratch)[0].startswith("seal.json"), "and it names the file"


@pytest.mark.parametrize("kind", ["a case deleted", "a trailing newline added", "a byte-order mark added", "a recorded file missing",
                                  "an unrecorded answer file added"])
def test_other_ways_a_recorded_file_can_change_are_refused_too(meta, tmp_path, kind):
    scratch = _oracle_copy(tmp_path)
    path = scratch / "polish.json"
    text = path.read_bytes().decode("utf-8")
    if kind == "a case deleted":
        lines = text.split("\n")
        gone = [i for i, line in enumerate(lines) if line.startswith('{"id":"size/small",')]
        assert len(gone) == 1, "the case to delete is on exactly one line"
        del lines[gone[0]]                                   # a middle line of the list: the file stays valid JSON
        assert len(json.loads("\n".join(lines))["vectors"]) == len(json.loads(text)["vectors"]) - 1
        path.write_bytes("\n".join(lines).encode("utf-8"))
    elif kind == "a trailing newline added":
        path.write_bytes((text + "\n").encode("utf-8"))
    elif kind == "a byte-order mark added":
        path.write_bytes(("﻿" + text).encode("utf-8"))
    elif kind == "a recorded file missing":
        path.unlink()
    else:
        scratch.joinpath("polish-copy.json").write_bytes(text.encode("utf-8"))
    assert S.integrity_problems(meta, scratch), kind + ": nothing noticed"


def test_a_windows_checkout_of_the_same_files_is_not_refused(meta, tmp_path):
    """core.autocrlf turns every LF in these files into CRLF on checkout. That is the same recorded answer."""
    scratch = _oracle_copy(tmp_path)
    for f in scratch.glob("*.json"):
        f.write_bytes(f.read_bytes().replace(b"\n", b"\r\n"))
    assert_recorded_files_are_the_oracles(meta, scratch)


def _profiles_copy(tmp_path, old=None, new=None):
    """A scratch copy of bid-profiles.js, with the one line `old` (there exactly once) replaced by `new`."""
    text = S.PROFILES_JS.read_bytes().decode("utf-8")
    if old is not None:
        assert "\n" not in old and text.count(old) == 1, "%r is in bid-profiles.js %d times, not once" % (old, text.count(old))
        text = text.replace(old, new)
    path = tmp_path / "bid-profiles.js"
    path.write_bytes(text.encode("utf-8"))
    return path


CELL_MAP_CHANGES = {
    "a rate the oracle may type, changed": ('laborRate:   c("C47", 33),', 'laborRate:   c("C47", 34),'),
    "an output pointed at another cell": (
        'gp:            f("D73", "=ROUNDUP(SUM(D70,D80,D83)/(1-B73),0)-ROUNDUP(SUM(D70,D80),0)"),',
        'gp:            f("D74", "=ROUNDUP(SUM(D70,D80,D83)/(1-B73),0)-ROUNDUP(SUM(D70,D80),0)"),'),
    "a job question's cell, changed": ('remodel:        c("D6", "No"),', 'remodel:        c("D7", "No"),'),
}
NOT_CELL_MAP_CHANGES = {
    "a comment reworded": ("// THE CELL MAPS OF KYLE'S ESTIMATE WORKBOOK. Data only: no arithmetic, no DOM, no fetch.",
                           "// THE CELL MAPS OF KYLE'S ESTIMATE WORKBOOK. Data only: no arithmetic, no DOM, no fetch. (reworded)"),
    "the reason a copy differs, reworded": (
        "the 5% labor escalation is typed once, on the first Gyp tab; the other four read it from there",
        "the 5% labor escalation is typed once, on the first Gyp tab; the other four read it from there (reworded)"),
    "the version number": ("version: 1,", "version: 2,"),
}


def test_the_cell_map_hash_is_over_the_data_the_oracle_read_and_nothing_else(meta, tmp_path):
    """The recorded cell-map hash is the live file's, and it moves for a change to what the oracle reads (a rate, an output cell,
    a question cell) and stays put for what it does not (a comment, `families`, `version`): a reworded note must not ask
    anybody to run the oracle."""
    base = S.profiles_sha256(_profiles_copy(tmp_path))
    assert base == meta["integrity"]["profiles"]["sha256"] == S.profiles_sha256()
    for label, (old, new) in CELL_MAP_CHANGES.items():
        assert S.profiles_sha256(_profiles_copy(tmp_path, old, new)) != base, label + ": the hash did not move"
    for label, (old, new) in NOT_CELL_MAP_CHANGES.items():
        assert S.profiles_sha256(_profiles_copy(tmp_path, old, new)) == base, label + ": the hash moved for something the oracle never reads"


def test_a_changed_cell_map_is_refused_with_the_oracle_to_rerun(meta, tmp_path):
    changed = _profiles_copy(tmp_path, *CELL_MAP_CHANGES["a rate the oracle may type, changed"])
    with pytest.raises(AssertionError, match="re-run the oracle") as refused:
        assert_recorded_files_are_the_oracles(meta, S.ORACLE, changed)
    assert "cell maps" in str(refused.value)


def test_the_cell_map_hash_covers_every_field_the_oracle_reads(meta):
    """workbook-oracle.js reads a tab's map through `map.<field>`. A field it starts to read that the hash leaves out
    would let that field change without the answers being declared stale; one the hash covers and the oracle never reads
    would ask for oracle runs for nothing. The list the hash uses is the one recorded in meta.json and the one in the
    module."""
    node = require_node()
    listed = json.loads(subprocess.run([node, "-e", "process.stdout.write(JSON.stringify(require(process.argv[1]).SHEET_FIELDS))",
                                        str(S.INTEGRITY_JS)], capture_output=True, text=True, timeout=60).stdout)
    assert listed == meta["integrity"]["profiles"]["sheetFields"], "oracle-integrity.js SHEET_FIELDS changed: " + REGEN
    read = set(re.findall(r"\bmap\.([A-Za-z]+)", S.ORACLE_JS.read_text(encoding="utf-8")))
    assert read == set(listed), (
        "the oracle reads %s off a tab's map and the hash covers %s; they must be the same set" % (sorted(read), sorted(listed)))


def test_the_self_check_is_recorded_and_it_passed_on_every_cell(profiles, meta):
    sc = meta["selfCheck"]
    assert sc["compared"] >= 15000 and sc["matched"] == sc["compared"]
    assert sum(r["compared"] for r in sc["sheets"].values()) == sc["compared"]
    for tab, r in sc["sheets"].items():
        assert r["matched"] == r["compared"], tab
        if r["matchedAsSaved"] < r["matched"]:
            assert r.get("laborRatesPutBack") or tab == "Seal (+Jnts)", (
                tab + ": the file disagreed with itself and no labor rate was put back to explain it")
    # Whatever was put back is named, so a reader can see what the check had to do. (Today ten tabs: the template as
    # committed carries saved values from an older labor rate. When Excel re-saves it after a recalculation the list
    # is empty and the check is the plain one; nothing here needs to change.)
    for r in sc["sheets"].values():
        for line in r.get("laborRatesPutBack", []):
            assert " -> " in line and "!" in line, line


def test_the_public_repo_never_gets_node_modules_or_a_real_job_workbook():
    """This repository is public. `npm install hyperformula` leaves node_modules behind (and, run inside
    docs/excel-parity-audit, a package.json and a package-lock.json: the repository has none on purpose), and the
    Excel parity audit reads real customers' estimate workbooks copied out of Dropbox (job01.xlsx and what it dumps from
    them). None of it may ever be added, and the oracle's own files must not be swallowed by those patterns."""
    git = shutil.which("git")
    inside = git and subprocess.run([git, "rev-parse", "--is-inside-work-tree"], cwd=S.REPO, capture_output=True, text=True)
    if not inside or inside.stdout.strip() != "true":
        pytest.skip("not a git checkout")

    def ignored(path):
        return subprocess.run([git, "check-ignore", "-q", path], cwd=S.REPO, capture_output=True).returncode == 0

    for path in ("node_modules/hyperformula/package.json", "docs/excel-parity-audit/node_modules/hyperformula/package.json",
                 "docs/excel-parity-audit/package.json", "docs/excel-parity-audit/package-lock.json",
                 "docs/excel-parity-audit/job01.xlsx", "docs/excel-parity-audit/job01.json", "docs/excel-parity-audit/job07.excel.json"):
        assert ignored(path), path + " must be gitignored: this repository is public"
    for path in ("docs/excel-parity-audit/engine.js", "docs/excel-parity-audit/one-config.js", "docs/excel-parity-audit/README.md",
                 "docs/excel-parity-audit/last-report.json", "backend/tests/fixtures/oracle/polish.json",
                 "backend/tests/fixtures/oracle/meta.json", "frontend/js/bid-profiles.js"):
        assert not ignored(path), path + " belongs to the repository and must not be ignored"


# ── reading the template for the oracle must not change what the app reads next ─
def _dropdowns_left_by(read, monkeypatch, sheet="Polish"):
    """What the NEXT caller of read_sheet_grid(sheet) gets, after `read()` has had its turn at the live
    template. read_sheet_grid keeps one result per (path, sheet, mtime) for the whole process and hands the
    same dict to everyone, so what one test caches is what a later test in that worker sees. The cache is
    swapped for an empty scratch one (and put back when the test ends), so this neither depends on nor
    disturbs what the rest of the suite has already cached."""
    monkeypatch.setattr(S.ew, "_SHEET_GRID_CACHE", {})
    read()
    return S.ew.read_sheet_grid(sheet)["dropdowns"]


def test_the_oracles_readers_leave_the_apps_sheet_cache_as_the_app_would_have_it(monkeypatch):
    """The first full run of this phase failed test_taxable_flag_reaches_every_sheet. The oracle had read the
    live template with the dropdown parser off, that result went into the process-wide cache under the key
    every normal read uses, and the next test in the same worker to ask for the Polish tab found no Yes/No
    pickers. Every way the oracle reads the live template has to leave behind exactly what the app's own
    read would have."""
    app = _dropdowns_left_by(lambda: S.ew.read_sheet_grid("Polish"), monkeypatch)
    assert app.get("B6") == ["Yes", "No"], (
        "the Polish tab keeps its Yes/No pickers in x14 validations; a fresh read has to find them or this "
        "test proves nothing")
    readers = {
        "_grid": lambda: S._grid("Polish", S.TEMPLATE_PATH),
        "normalised_cells": lambda: S.normalised_cells(["Polish"]),
        "template_spec": lambda: S.template_spec(),
    }
    for name, read in readers.items():
        assert _dropdowns_left_by(read, monkeypatch) == app, (
            name + " left the sheet cache different from what the app's own read would have put there")


def test_that_check_can_fail_a_read_without_the_dropdown_parser_does_poison_the_cache(monkeypatch):
    """Proof the comparison above is not vacuous: the OLD oracle read (parse_x14 off, on the live template)
    leaves the Polish tab with no pickers in the shared cache. If this ever goes red because
    read_sheet_grid's cache key now includes parse_x14, the cause is fixed at its root: delete this test
    and the one above."""
    app = _dropdowns_left_by(lambda: S.ew.read_sheet_grid("Polish"), monkeypatch)

    def old_read():
        S.ew.read_sheet_grid("Polish", path=S.TEMPLATE_PATH, parse_x14=False)

    left = _dropdowns_left_by(old_read, monkeypatch)
    assert left != app and not left, "a read without the parser should have left no dropdowns behind"


# ── where HyperFormula is installed, the recorded files are re-derived ───────
def _hyperformula_installed() -> bool:
    """Can docs/excel-parity-audit/engine.js find hyperformula? (A node_modules beside it, or NODE_PATH.)"""
    node = shutil.which("node")
    if not node:
        return False
    proc = subprocess.run([node, "-e", "require(process.argv[1]).hyperformulaPath()",
                           str(S.REPO / "docs" / "excel-parity-audit" / "engine.js")], capture_output=True, text=True)
    return proc.returncode == 0


@pytest.mark.skipif(not _hyperformula_installed(),
                    reason="hyperformula@2.7.1 is not installed (the repo does not depend on it); CI compares, a developer machine recomputes")
def test_the_oracle_recomputes_exactly_what_is_recorded():
    proc = run_node(S.ORACLE_JS, timeout=900)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-4000:]
    assert "reproduces 12 recorded file(s) exactly" in proc.stdout
