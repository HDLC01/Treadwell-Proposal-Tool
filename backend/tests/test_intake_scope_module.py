"""Phase 9a: js/intake-scope.js is the ONE renderer of the intake's quantity fields, and the live intake uses it.

PROVEN BY EXECUTION. fixtures/intake_scope_golden.json was captured from the live intake BEFORE its
rendering moved into the module: the markup of the systems block and the show/hide state of every field,
row, the gypsum box, the beta button and the thickness row, for every job type (and none picked) and both
audiences, once as the page loads with a saved draft and once after the radio is clicked. The real page
script runs against a DOM stub (tests/js/beta-routing-harness.js, `scopeSnapshots`) and its output must equal
the fixture byte for byte. Mutation: change a label, a row, a scope or a display value in the module and the
comparison fails for the job type that moved.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

TESTS = pathlib.Path(__file__).resolve().parent
FRONTEND = TESTS.parents[1] / "frontend"
HARNESS = TESTS / "js" / "beta-routing-harness.js"
GOLDEN = TESTS / "fixtures" / "intake_scope_golden.json"
MODULE = FRONTEND / "js" / "intake-scope.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def run_harness(frontend):
    proc = subprocess.run(["node", str(HARNESS), str(frontend)], capture_output=True, text=True,
                          encoding="utf-8", timeout=120)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])["scopeSnapshots"]


@pytest.fixture(scope="module")
def golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def live():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    return run_harness(FRONTEND)


def test_the_golden_covers_every_job_type_and_both_audiences(golden):
    assert sorted(golden) == sorted(a + "/" + j for a in ("Direct", "GC")
                                    for j in ("polish", "epoxy", "combo", "gyp", "blank"))
    # Not vacuous: the states differ between job types, so a renderer that showed everything would not match.
    shown = {j: [l["display"] for l in golden["Direct/" + j]["atLoad"]["labels"]]
             for j in ("polish", "epoxy", "combo", "gyp")}
    assert len({tuple(v) for v in shown.values()}) == 4


@needs_node
@pytest.mark.parametrize("audience", ["Direct", "GC"])
@pytest.mark.parametrize("job", ["polish", "epoxy", "combo", "gyp", "blank"])
def test_the_live_intake_renders_byte_identical_to_the_golden(live, golden, audience, job):
    key = audience + "/" + job
    for when in ("atLoad", "afterClick"):
        assert live[key][when] == golden[key][when], "%s %s differs from the golden" % (key, when)


# -- one renderer: the page delegates and holds no copy ---------------------------------------------
def test_the_page_holds_no_second_renderer():
    page = (FRONTEND / "js" / "index.js").read_text(encoding="utf-8")
    for gone in ("SCOPE_BY_WORK_TYPE", "function renderSystems", "function systemFieldNames",
                 "Epoxy floor SF", "Polish floor SF", "Cove LF"):
        assert gone not in page, "index.js still carries its own copy: %s" % gone
    assert "intakeScope.renderSystems(" in page and "intakeScope.applyScope(" in page


def test_the_script_tag_follows_the_vocabulary_and_precedes_the_page():
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    order = re.findall(r'<script src="(/js/[^"]+)"', html)
    assert order.index("/js/work-types.js") < order.index("/js/intake-scope.js") < order.index("/js/index.js")


# -- the module's contract ---------------------------------------------------------------------------
def node(expr):
    return subprocess.run(["node", "-e", "const m=require(process.argv[1]);" + expr, str(MODULE)],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)


@needs_node
@pytest.mark.parametrize("call", ["m.scopesFor()", "m.scopesFor('')", "m.applyScope(undefined, {})",
                                  "m.applyScope(null, {})"])
def test_a_missing_job_type_throws_by_name(call):
    proc = node("try{%s;console.log('no throw')}catch(e){console.log(e.message)}" % call)
    assert "needs the job type" in proc.stdout, proc.stdout


@needs_node
def test_an_unknown_job_type_throws_the_vocabularys_error():
    proc = node("try{m.applyScope('seal',{});console.log('no throw')}catch(e){console.log(e.message)}")
    assert "not a job type" in proc.stdout, proc.stdout


@needs_node
def test_the_scopes_are_the_vocabularys():
    proc = node("const t=require(require('path').join(require('path').dirname(process.argv[1]),'work-types.js'));"
                "console.log(JSON.stringify(t.jobTypeKeys().map(k=>[m.scopesFor(k),t.scopesFor(k)])))")
    pairs = json.loads(proc.stdout)
    assert len(pairs) == 4 and all(a == b for a, b in pairs)
