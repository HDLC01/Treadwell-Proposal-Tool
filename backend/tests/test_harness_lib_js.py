"""tests/js/_lib.js, the helpers every NEW node harness shares, run against inputs built to break them.

The v2 estimating program writes a harness per phase, and each one lifts pieces out of a page that
is about to be refactored. A lifter that grabs the wrong text, a brace matcher that stops at a `}`
inside a string, or a tag stripper that leaves a tag behind makes every one of those harnesses
green for the wrong reason, and nothing downstream would notice. So the helpers are executed here,
against the inputs the hand-written copies in the older harnesses get wrong, and against the real
page files (every function declaration in seven of them is lifted and compiled).

The older harnesses are NOT converted to this file. They are pinned by tests that read them as
they are.

Run by tests/js/lib-selftest-harness.js. A missing node FAILS under CI (tests/_node.py).
"""
import pathlib

import pytest

from _node import last_json_line, require_node, run_node

HERE = pathlib.Path(__file__).resolve().parent
FRONTEND = HERE.parents[1] / "frontend"
HARNESS = HERE / "js" / "lib-selftest-harness.js"


@pytest.fixture(scope="module")
def lib():
    require_node()
    proc = run_node(HARNESS, FRONTEND)
    assert proc.returncode == 0, "the self-test harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


def test_read_normalises_line_endings_and_drops_the_bom(lib):
    """The whole reason read() exists: a CRLF checkout must look like the LF one CI sees."""
    assert lib["read"] == "one\ntwo\n\nthree\n"


@pytest.mark.parametrize("case, expected", [
    ("plain", "{ a { b } c }"),
    ("inDoubleQuote", '{ s = "}"; }'),
    ("inSingleQuote", "{ s = '}{'; }"),
    ("escapedQuote", '{ s = "a\\"}"; }'),
    ("inTemplate", "{ s = `}`; }"),
    ("templateSubstitution", "{ s = `a${ {k: 1}.k }b}`; }"),
    ("nestedTemplate", "{ s = `a${ `b${ 1 }}` }c`; }"),
    ("inLineComment", "{ // }\n a }"),
    ("inBlockComment", "{ /* } */ a }"),
    ("inRegexLiteral", "{ r = /[}]/g; }"),
    ("slashInRegexClass", "{ r = /[/}]/; }"),
    ("afterReturn", "{ return /}/.test(s); }"),
    ("division", "{ n = (a + b) / 2 / 3; }"),
    ("divisionAfterNumber", "{ n = 4 / 2; /* } */ }"),
    ("parens", "(a, (b), [c])"),
    ("brackets", "[1, [2, 3], {a: 4}]"),
])
def test_balanced_finds_the_real_closing_bracket(lib, case, expected):
    """A brace inside a string, a template literal, a comment or a regex literal is not a brace.
    Counting them is what the older hand-written matchers do, and it shifts the lifted slice."""
    assert lib["balanced"][case] == expected


def test_balanced_says_so_when_the_source_is_not_balanced(lib):
    b = lib["balanced"]
    assert b["mismatched"] == "expected ) but found } at 4"
    assert b["notAnOpener"].startswith("balanced() needs an opening bracket")
    assert b["runsOff"] == "ran off the end of the source looking for }"


def test_lift_binds_by_name_and_refuses_to_guess(lib):
    lf = lib["lift"]
    # the dep handed in is what the lifted function sees: K=10, so 1 + 2 + 10
    assert lf["addWithDep"] == 13
    assert lf["sourceOfAdd"] == "function add(a, b) { return a + b + K; }"
    # the same name nested deeper is picked only when the indent says so
    assert lf["nestedPicked"] == "function add(a, b) { return 'nested'; }"
    assert lf["ambiguous"] == "add() is declared 2 times in synthetic.js -- pass { indent } to say which one"
    assert lf["gone"] == "nothing() is gone from synthetic.js -- rewrite this harness, don't stub it"
    # a name that is only a PREFIX of another function's is not a match
    assert lf["prefixIsNotAMatch"] == "function add() { return 2; }"
    # async, default parameter holding a brace, and a body full of brackets inside strings
    assert lf["asyncDefault"] == "async function load(x = { y: 1 }) { return x.y; }"
    assert lf["braceInside"] == "function brace() { return '}' + `{${K}}` + /}/.source; }"


def test_a_callee_left_out_of_deps_is_unbound_in_the_lifted_copy(lib):
    """The failure that took the board down on prod: lift() must NOT paper over it."""
    assert lib["lift"]["unbound"] == "helper is not defined"
    assert lib["lift"]["bound"] == 42


def test_grab_const_returns_the_whole_statement(lib):
    lf = lib["lift"]
    assert lf["constSet"] == 'const ROLES = new Set(["a", "b;"]);'      # the ; inside a string is not the end
    assert lf["constObject"] == "const TABLE = { one: function () { return 1; }, two: 2 };"
    assert lf["constArray"] == "var LONG = [\n    1, 2,\n  ];"
    assert lf["constGone"].startswith("NOPE is gone from the source")
    assert lf["grab"] == "beta"
    assert lf["grabMissing"] == "could not lift zzz -- rewrite this harness, don't stub it"


def test_strip_tags_loops_until_nothing_changes(lib):
    st = lib["stripTags"]
    assert st["plain"] == "One two"
    assert st["comment"] == "ab"
    assert st["quotedGreaterThan"] == "link" and st["singleQuoted"] == "link"
    # Stripping once turns `<<b>script>` into `<script>`. These are the inputs a single pass fails.
    assert st["buildsATag"] == "alert(1)"
    assert st["buildsAComment"] == "y"
    assert st["nestedDeep"] == "script>x"
    assert st["noTagSurvives"] == [True, True, True, True]
    # text that only looks like markup stays text
    assert st["loneLessThan"] == "1 < 2 and 3 > 2"
    # an unterminated tag or comment runs to the end, as a browser reads it
    assert st["unterminatedTag"] == "keep " and st["unterminatedComment"] == "keep "
    assert st["empty"] == "" and st["nullish"] == ""


def test_escape_reg_exp_makes_text_match_only_itself(lib):
    e = lib["escape"]
    assert e["escaped"] == "\\.\\*\\+\\?\\^\\$\\{\\}\\(\\)\\|\\[\\]\\\\/-"
    assert all(e["everyMetaMatchesItself"]) and len(e["everyMetaMatchesItself"]) == 16
    assert e["wholeStringMatchesItself"] is True
    assert e["doesNotMatchTheWildcardMeaning"] is False and e["matchesTheLiteral"] is True
    assert e["flags"] is True and e["number"] == "12\\.5"


# A floor, not an exact count: it only has to prove the sweep read real files. Half of today's.
SWEEP_FLOORS = {"js/polish-estimate.js": 50, "js/estimate-review.js": 75, "js/proposal-review.js": 135,
                "js/library.js": 80, "js/polish-bid-core.js": 35, "js/index.js": 9, "js/portal.js": 45}


def test_every_function_in_seven_real_pages_lifts_and_compiles(lib):
    """The matcher is only trustworthy if it survives the real thing: thousands of lines of
    template literals, regex literals and braces inside strings. Each declaration the sweep finds
    is lifted by liftSource and handed to the JavaScript parser; a miscounted brace anywhere
    produces text that does not parse and fails here BY NAME."""
    swept = {s["file"]: s for s in lib["sweep"]}
    assert set(swept) == set(SWEEP_FLOORS)
    for rel, floor in SWEEP_FLOORS.items():
        s = swept[rel]
        assert s["failures"] == [], (rel, s["failures"][:3])
        assert s["lifted"] >= floor, (rel, s["lifted"], "the sweep found suspiciously few functions")
        assert s["lifted"] == s["declared"], (rel, "a declaration was skipped, not lifted")


def test_constants_are_lifted_out_of_the_page_not_retyped(lib):
    """The role sets and tables later phases pin to work-types.js are read off estimate-review.js."""
    assert lib["realConsts"]["pricedRoles"] == ["epoxy", "gyp", "polish", "seal"]
    assert lib["realConsts"]["baseRoleIsObject"] is True
