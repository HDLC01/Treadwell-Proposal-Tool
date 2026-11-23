"""tests/js/bd/_lib.js, the helpers every BD node harness shares, run against inputs built to break them.

The BD harnesses live in their own folder, tests/js/bd/, beside the proposal tool's (whose
tests/js/_lib.js and lib-selftest-harness.js have the same names; test_harness_lib_js.py checks
those). Each BD harness lifts pieces out of a BD script (`frontend/bd/js/bd-core.js` first). A
lifter that grabs the wrong text, a brace matcher that stops at a `}` inside a string, or a tag
stripper that leaves a tag behind makes every one of those harnesses green for the wrong reason,
and nothing downstream would notice. So the helpers are executed here, against inputs built to
break them, and against a small fictional fixture (tests/js/bd/fixtures/sample.js) full of the
shapes that trip a lifter: every function declaration in it is lifted and compiled, and every
string in it is scanned. The fixture is deliberately NOT one of the BD pages, so a refactor of a
page can never move this test.

Run by tests/js/bd/lib-selftest-harness.js. A missing node FAILS under CI (tests/_node.py).
"""
import pathlib

import pytest

from _node import last_json_line, require_node, run_node

HERE = pathlib.Path(__file__).resolve().parent
FIXTURES = HERE / "js" / "bd" / "fixtures"
HARNESS = HERE / "js" / "bd" / "lib-selftest-harness.js"


@pytest.fixture(scope="module")
def lib():
    require_node()
    proc = run_node(HARNESS, FIXTURES)
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


# A floor, not an exact count: it only has to prove the sweep read the file. Half of today's 8.
SWEEP_FLOORS = {"sample.js": 4}


def test_every_function_in_the_fixture_lifts_and_compiles(lib):
    """The matcher is only trustworthy if it survives the awkward shapes: template literals, regex
    literals and braces inside strings. Each declaration the sweep finds is lifted by liftSource
    and handed to the JavaScript parser; a miscounted brace anywhere produces text that does not
    parse and fails here BY NAME."""
    swept = {s["file"]: s for s in lib["sweep"]}
    assert set(swept) == set(SWEEP_FLOORS)
    for rel, floor in SWEEP_FLOORS.items():
        s = swept[rel]
        assert s["failures"] == [], (rel, s["failures"][:3])
        assert s["lifted"] >= floor, (rel, s["lifted"], "the sweep found suspiciously few functions")
        assert s["lifted"] == s["declared"], (rel, "a declaration was skipped, not lifted")


def test_string_literals_finds_the_strings_and_only_the_strings(lib):
    """The comment that explains a rename quotes the old name, so a search of the FILE cannot say
    whether the old name still reaches a person. This reads the strings and nothing else."""
    s = lib["literals"]
    assert s["plain"] == ["x", "y"]
    assert s["escaped"] == ['he said \\"hi\\"']
    assert s["comments"] == ["kept"], "a comment (or the tail of a code line) was read as a string"
    # a quote inside a regular expression, and a division, do not open or close anything
    assert s["quoteInRegex"] == ["kept"] and s["division"] == ["kept"]
    assert s["template"] == ["a ", " b"]
    assert s["nested"] == ["a ", "in", "deep ", " b"], "a string inside ${ } was missed or misordered"
    assert s["braceInSubstitution"] == ["a ", "v", " b"]


def test_string_literals_reports_the_line_each_string_starts_on(lib):
    s = lib["literals"]
    assert s["lines"] == [2, 4]
    assert s["templateLines"] == [["one\ntwo ", 2], ["in", 3], [" three", 3]]


def test_string_literals_refuses_source_it_cannot_read_to_the_end(lib):
    s = lib["literals"]
    assert s["unterminatedString"].startswith("unterminated \" string starting at")
    assert s["unterminatedTemplate"].startswith("unterminated template literal starting at")
    assert s["unterminatedComment"].startswith("unterminated comment starting at")
    assert s["openBracket"] == "the source ends with 1 bracket(s) still open"
    assert s["strayCloser"].startswith("unbalanced } at")


# A floor, not an exact count: half of today's 24. It only has to prove the scan read the file.
LITERAL_FLOORS = {"sample.js": 12}


def test_string_literals_survives_the_fixture(lib):
    """Template literals, regular expressions and braces inside strings. The scan ends with a
    balance check, so a misread quote or regex fails the file here by name."""
    swept = {s["file"]: s for s in lib["literalSweep"]}
    assert set(swept) == set(LITERAL_FLOORS)
    for rel, floor in LITERAL_FLOORS.items():
        assert swept[rel]["error"] is None, (rel, swept[rel]["error"])
        assert swept[rel]["n"] >= floor, (rel, swept[rel]["n"], "suspiciously few strings")


def test_constants_are_lifted_out_of_the_source_not_retyped(lib):
    """The tables a later phase pins (cadence frequencies, the task kinds) are read off the page,
    so this proves each shape comes back as the value the source wrote: a Set, an object, an array
    spread over lines, and a string holding braces."""
    c = lib["fixtureConsts"]
    assert c["tags"] == ["followup", "new"]
    assert c["frequency"] == {"bd": 4, "maintenance": 3}
    assert c["weekdays"] == ["Mon", "Tue", "Wed", "Thu", "Fri"]
    assert c["separator"] == "}{"


def test_a_lifted_fixture_function_runs_with_only_what_it_was_handed(lib):
    r = lib["fixtureRuns"]
    assert r["labelMaintenance"] == "Maintenance" and r["labelBd"] == "Business development"
    assert r["half"] == 2
    assert r["split"] == {"first": "Pat", "rest": "Lee"}
    assert r["describeBoth"] == "<b>Pat</b> - <i>Acme</i>" and r["describeNone"] == "unknown"
