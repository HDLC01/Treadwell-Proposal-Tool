"""The workbook oracle, as CI sees it: recorded answers, and the guards that say when they are stale.

THE ORACLE is Kyle's estimate workbook evaluated by the HyperFormula the Estimate Review page runs, with
numbers typed into the boundary cells of each priced tab (backend/tests/js/workbook-oracle.js). Its
answers are recorded in backend/tests/fixtures/oracle/<tab>.json, one file per priced tab, plus
meta.json. Later phases of the v2 program check every v2 tab against them.

CI HAS NO HYPERFORMULA, ON PURPOSE (the repository has no package.json and no node_modules), so CI cannot
recompute anything. What it can do, and what this module does, is refuse to trust the recorded answers
when what they were recorded FROM has moved:

  - Kyle's template has a different formula or constant in a priced tab  -> "re-run the oracle"
  - the page now pins a different HyperFormula                           -> "re-run the oracle"
  - frontend/js/xl-excel-rounding.js changed                             -> "re-run the oracle"
  - the oracle's engine options are no longer the page's                 -> fails
  - a recorded file is missing, short of a case it must hold, or does not add up

and it checks that the guards themselves work: the template guard is run on edited copies of the
template (a formula, a constant), on a copy that is merely re-saved, and on an edit to a tab it does not
cover, and it must go red, green, green, green.

Where HyperFormula IS installed (a developer's machine with NODE_PATH set), one more test recomputes
everything and requires it to match the recorded files byte for byte.
"""
import base64
import copy
import hashlib
import html.parser
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
    expected = {s + ".json" for s in slugs} | {"meta.json", "departures.json", "odd_rules.json"}
    assert {p.name for p in S.ORACLE.glob("*.json")} == expected, "an unexpected or missing file in fixtures/oracle"


def test_every_tab_was_tried_at_every_kind_of_case(goldens):
    for tab, g in goldens.items():
        kinds = {v["id"].split("/")[0] for v in g["vectors"]}
        assert kinds >= {"base", "size", "scale", "sf", "flags", "remodel", "money", "bond", "edge", "lodging"}, tab
        assert len([v for v in g["vectors"] if v["id"].startswith("flags/")]) == 96, tab + ": 32 settings at 3 sizes"


# ── the guards: the answers are only good while what they came from stands ───
def test_the_template_has_not_changed_since_the_oracle_ran(profiles, meta):
    digest, count = S.template_hash(profiles["priced"])
    assert (digest, count) == (meta["template"]["hash"], meta["template"]["cells"]), (
        "Kyle's template now has a different formula or constant in a priced tab than the one the oracle "
        "recorded its answers from, so those answers may no longer be his workbook's. " + REGEN)


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
    """This repository is public. `npm install hyperformula` leaves node_modules behind, and the Excel parity audit
    reads real customers' estimate workbooks copied out of Dropbox (job01.xlsx and what it dumps from them). None
    of it may ever be added, and the oracle's own files must not be swallowed by those patterns."""
    git = shutil.which("git")
    inside = git and subprocess.run([git, "rev-parse", "--is-inside-work-tree"], cwd=S.REPO, capture_output=True, text=True)
    if not inside or inside.stdout.strip() != "true":
        pytest.skip("not a git checkout")

    def ignored(path):
        return subprocess.run([git, "check-ignore", "-q", path], cwd=S.REPO, capture_output=True).returncode == 0

    for path in ("node_modules/hyperformula/package.json", "docs/excel-parity-audit/node_modules/hyperformula/package.json",
                 "docs/excel-parity-audit/job01.xlsx", "docs/excel-parity-audit/job01.json", "docs/excel-parity-audit/job07.excel.json"):
        assert ignored(path), path + " must be gitignored: this repository is public"
    for path in ("docs/excel-parity-audit/engine.js", "docs/excel-parity-audit/one-config.js", "docs/excel-parity-audit/README.md",
                 "docs/excel-parity-audit/last-report.json", "backend/tests/fixtures/oracle/polish.json",
                 "backend/tests/fixtures/oracle/meta.json", "frontend/js/bid-profiles.js"):
        assert not ignored(path), path + " belongs to the repository and must not be ignored"


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
