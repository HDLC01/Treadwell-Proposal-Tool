"""tests/js/_golden.js, the toolkit the golden masters are made and checked with.

A golden master is only worth having if it cannot be fooled by what JSON hides. The comparison
behind test_polish_chain_golden.py and test_library_pricing_golden.py has to tell 0 from -0, has to
treat NaN as equal to itself, has to see a field that is `undefined` where the golden has none, has
to notice a function that starts writing into its argument, and has to say WHERE two answers part
in words a reviewer can act on. Each of those is a case here, run through
tests/js/golden-selftest-harness.js, including the command line (the exit codes are what CI reads)
driven through a throwaway generator.

Run under node; a missing node FAILS under CI (tests/_node.py).
"""
import pathlib

import pytest

from _node import last_json_line, require_node, run_node

HERE = pathlib.Path(__file__).resolve().parent
HARNESS = HERE / "js" / "golden-selftest-harness.js"


@pytest.fixture(scope="module")
def ran():
    require_node()
    proc = run_node(HARNESS)
    assert proc.returncode == 0, "the self-test harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


def test_the_codec_keeps_what_json_throws_away(ran):
    c = ran["codec"]
    assert c["negativeZeroSurvives"] and c["positiveZeroStaysPositive"]
    assert c["nan"] and c["infinities"] and c["undefinedInAnArray"] and c["undefinedKeyKept"]
    assert c["smallAndHuge"] and c["plain"] and c["nested"]
    # the reason it exists: JSON.stringify alone turns -0, NaN, Infinity and undefined into 0 and null
    assert c["jsonAloneHides"] == "[0,null,null,null,{}]"
    assert c["encodedZero"] == '{"$":"-0"}'


def test_the_codec_refuses_what_a_golden_cannot_hold(ran):
    c = ran["codec"]
    assert c["reservedKey"] == "value has a key named $, which the codec reserves"
    assert c["aFunction"] == "value.f is a function, which a golden cannot hold"
    assert c["aClassInstance"] == "value.d is a Date, not plain data"
    # it would come back from the file as an ordinary object, which deepStrictEqual tells apart
    assert c["aNullPrototypeObject"] == "value.o is an object with no prototype, not plain data"
    assert c["aHole"] == "value[1] is a hole in a sparse array"
    assert c["unknownTag"] == 'unknown codec tag "bogus"'


def test_equality_is_deep_strict_equality(ran):
    s = ran["same"]
    assert s["zeroVsNegativeZero"] is False, "0 and -0 must NOT compare equal"
    assert s["nanVsNan"] is True, "NaN must equal itself"
    assert s["undefinedVsMissing"] is False, "a field that is undefined is not a missing field"
    assert s["arrayLength"] is False and s["stringVsNumber"] is False
    assert s["keyOrderDoesNotMatter"] is True and s["identical"] is True


def test_the_first_difference_is_worded_for_a_person(ran):
    d = ran["firstDifference"]
    assert d["none"] is None and d["nanBothSides"] is None
    assert d["nested"] == {"path": ".out.gp_pct", "want": "0.45", "got": "0.52"}
    assert d["zero"] == {"path": ".out.cost", "want": "0", "got": "-0"}
    assert d["nan"] == {"path": ".v", "want": "NaN", "got": "0"}
    assert d["missingKey"] == {"path": ".b", "want": "2", "got": "(absent)"}
    assert d["extraKey"] == {"path": ".z", "want": "(absent)", "got": "9"}
    assert d["shorterArray"] == {"path": "[2]", "want": "3", "got": "(absent)"}
    assert d["type"] == {"path": ".v", "want": "'1'", "got": "1"}
    assert d["undefinedVsAbsent"] == {"path": ".a", "want": "undefined", "got": "(absent)"}
    assert d["firstOfSeveral"]["path"] == ".b"


def test_the_recorder_runs_on_a_clone_and_notes_what_happened(ran):
    r = ran["recorder"]
    assert r["argsKeptOriginal"] is True
    assert r["mutatedFlagOnlyWhenTrue"] == [False, True, False, False, False]
    assert r["threwHoldsTheNameOnly"] is True, "an error's message differs per node version; only its name is stored"
    assert r["undefinedOutKept"] is True
    assert r["duplicateId"] == "duplicate vector id double"
    assert r["vectors"][1] == "{ id: 'mutates', fn: 'mutates', args: [ { n: 2 } ], out: 99, mut: true }"
    assert r["vectors"][3] == "{ id: 'returnsNegativeZero', fn: 'negz', args: [ 3, -0 ], out: -0 }"


def test_a_comparison_names_every_way_a_golden_can_go_stale(ran):
    c = ran["compare"]
    assert c["identical"] == []
    assert c["moved"] == ["1 of 4 vectors answer differently now:",
                          "  t/1   f(1)\n      at .out.gp: golden 0.45, now 0.52"]
    # the two a JSON-based comparison would let through
    assert c["zeroBecameNegativeZero"][1] == "  t/2   f(5)\n      at .out: golden 0, now -0"
    assert c["nanBecameZero"][1] == "  t/3   f(NaN)\n      at .out: golden NaN, now 0"
    # the same answer as before that now writes into its own argument
    assert c["startedMutating"][1] == "  t/4   f({ k: 1 })\n      at .mut: golden (absent), now true"
    assert c["lostAVector"] == ["1 vector(s) in the golden are no longer made, first: t/4"]
    assert c["gainedAVector"] == ["1 vector(s) are made now that the golden does not hold, first: t/5"]
    assert c["versionBumped"] == ["recipe_version is 1 in the golden but 2 in the generator: "
                                  "the INPUTS changed, so regenerate the golden."]
    # a wall of failures stays readable: three shown, the rest counted
    assert c["limited"][0] == "12 of 12 vectors answer differently now:"
    assert len(c["limited"]) == 5 and c["limited"][-1] == "  ... and 9 more"


def test_the_file_is_one_vector_per_line(ran):
    # four vectors: the header line, one line each, the footer line, and the empty tail after the
    # final newline
    assert ran["serializedShape"] == 4 + 3


def test_the_command_line_is_what_ci_reads(ran):
    c = ran["cli"]
    assert c["writeNeedsACommit"] == 2, "a golden with no provenance must not be writable"
    assert c["wroteStatus"] == 0 and c["fileStartsWith"] == '{"meta":{"co'
    assert c["fileMeta"] == {"commit": "0123456789abcdef0123456789abcdef01234567", "recipe_version": 1,
                             "n": 2, "generator": "demo"}
    assert c["negativeZeroOnDisk"] is True
    assert c["compareOkStatus"] == 0 and c["compareOkLine"] == '{"ok":true,"n":2}'
    assert c["compareBadStatus"] == 1
    assert c["compareBadFirstLines"][0].startswith("GOLDEN MASTER MISMATCH against demo")
    assert c["compareBadFirstLines"][2:] == ["  a   f(3)", "      at .out: golden 6, now 7"]
    assert c["compareBadSaysHowToRegenerate"] is True
    assert c["usageStatus"] == 2
