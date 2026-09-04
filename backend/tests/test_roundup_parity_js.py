"""Excel's ROUNDUP exists THREE times in this repo, in two languages. They must agree.

  * `backend/pricing.py`             `_roundup`      -- Python, guards via "%.12g"
  * `frontend/js/polish-bid-core.js` `roundUp`       -- JS, guards via toPrecision(12)
  * `frontend/js/markup-core.js`     `excelRoundUp`  -- JS, same guard, plus a digits argument.
                                                       NOT exported, so this file reaches it the
                                                       only way anything can: run("ROUNDUP(v,0)"),
                                                       which is also the door markup_rules uses.

Each rounds AWAY FROM ZERO and each first snaps its input to twelve significant figures, because
Excel keeps fifteen and IEEE-754 keeps seventeen: a value sitting a hair above an integer only as
a binary artefact IS that integer to Excel, and an unguarded ceil buys a spurious dollar off it.

WHY A TEST AND NOT A COMMENT. All three already say in prose that they must match each other --
markup-core.js's own header says its excelRoundUp "must match it, not re-derive it and drift" --
and prose has never once stopped a drift. The Python side is the proof: it drifted on BOTH
properties and neither comment noticed. It rounded toward zero on the negative hard-bid give-back
(fixed 2026-09-03, PR #450) and it had no float guard at all on the material figures (PR #451),
which is the half that was actually being paid -- a sweep found the guard changing compute_polish's
answer on 4.5% of realistic inputs, all of it traceable to dye being priced as two rows of
sf x $0.14 and 0.14 not being exact in binary.

So this file compares the implementations against EACH OTHER on the same vectors, in the same run.
It is the only thing in the repo that would notice if one of them changed and the others did not.

Skipped when node isn't installed; it's on the dev box and in the Docker image.
"""
import json
import math
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pricing  # noqa: E402

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
BID_CORE = FRONTEND / "js" / "polish-bid-core.js"
MARKUP_CORE = FRONTEND / "js" / "markup-core.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is not installed")


def _vectors():
    """The shapes real money actually takes in this engine, not arbitrary floats.

    Every generator here is a line off Kyle's Polish or Epoxy tab: dye at $0.14 across two coats,
    densifier at $0.07, the 1.37 material markup, joint-filler kits at one per 3,500 sq ft, 2%
    shipping, and the hard-bid give-back, which is the one NEGATIVE in the whole chain and so the
    only place the away-from-zero half of the contract can be caught.
    """
    out = []
    for i in range(1, 4001):
        out.append(i * 0.14 * 2)      # Polish D25+D26, the dye -- the original defect
        out.append(i * 0.07)          # Polish D19, densifier
        out.append(i * 1.37)          # the material markup into D43
        out.append(i / 3500.0)        # Polish B29, joint-filler kits
        out.append(i * 0.02)          # D32/D42, shipping
        out.append(-i * 0.025)        # D68, the hard-bid give-back: NEGATIVE
    out += [0.0, 110.00000000000001, 362.00000000000006, 220.22000000000003]
    return out


VECTORS = _vectors()


def _node(script, module):
    prelude = ("const M = require(%s);\n"
               "const out = (v) => console.log(JSON.stringify(v));\n"
               % json.dumps(str(module)))
    proc = subprocess.run(["node", "-e", prelude + script],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _js_answers(module, call):
    """Run `call` (a JS expression in `v`) over every vector, inside node.

    The vectors cross the language boundary as their exact 17-significant-figure decimal form and
    are parsed back by node, so both sides work on the identical double. Regenerating them in JS
    from the same arithmetic would let a difference in the VECTORS masquerade as agreement between
    the implementations.

    They travel in a FILE, not on the command line. Inlining 24,004 of them into `node -e` is
    WinError 206 ("the filename or extension is too long") on Windows, and the tempting way out --
    fewer vectors -- would quietly weaken the test to suit a shell limit.
    """
    fd, path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(["%.17e" % v for v in VECTORS], fh)
        return _node(
            "const vs = JSON.parse(require('fs').readFileSync(%s, 'utf8')).map(parseFloat);\n"
            "out(vs.map(function (v) { return %s; }));" % (json.dumps(path), call),
            module,
        )
    finally:
        os.unlink(path)


@pytest.fixture(scope="module")
def bid_core():
    return _js_answers(BID_CORE, "M.roundUp(v)")


@pytest.fixture(scope="module")
def markup_core():
    """markup-core.js does NOT export excelRoundUp -- the only way in is the formula engine.

    That is the better door anyway: `markup_rules` reaches ROUNDUP through run(), so this exercises
    the path the money actually takes. The value goes in through the CONTEXT rather than as a
    literal in the formula text, because a literal would be re-parsed by the tokenizer first and a
    precision loss THERE would surface here as a rounding disagreement, blaming the wrong function.
    """
    return _js_answers(MARKUP_CORE, 'M.run("ROUNDUP(v,0)", {v: v})')


def test_the_vectors_actually_exercise_the_guard():
    """THE SELF-CHECK, and without it the rest of this file proves nothing.

    A guarded and an unguarded implementation agree on almost every number. If no vector landed on
    binary dust, all the parity tests below would pass against an implementation with its guard
    ripped out -- green, and defending nothing. So count the vectors where a bare ceil actually
    disagrees, and fail loudly if either set ever empties out.
    """
    biting = [v for v in VECTORS if v > 0 and math.ceil(v) != pricing._roundup(v)]
    assert len(biting) >= 50, (
        "only %d vectors land on float dust -- the parity tests would pass against an "
        "unguarded ceil and would be proving nothing" % len(biting)
    )
    # The negative half is a different property -- away from zero, not the float guard.
    away = [v for v in VECTORS if v < 0 and math.ceil(v) != pricing._roundup(v)]
    assert len(away) >= 50, "no vector exercises rounding away from zero on a negative"


def test_python_and_the_bid_engine_round_identically(bid_core):
    """pricing.py vs polish-bid-core.js -- the two that price the same job on the two paths."""
    bad = [(v, pricing._roundup(v), js) for v, js in zip(VECTORS, bid_core)
           if pricing._roundup(v) != js]
    assert not bad, "%d of %d disagree, first few: %r" % (len(bad), len(VECTORS), bad[:5])


def test_python_and_the_formula_engine_round_identically(markup_core):
    """pricing.py vs markup-core.js's excelRoundUp at digits=0 -- the engine that evaluates the
    free-text formulas out of the markup_rules table."""
    bad = [(v, pricing._roundup(v), js) for v, js in zip(VECTORS, markup_core)
           if pricing._roundup(v) != js]
    assert not bad, "%d of %d disagree, first few: %r" % (len(bad), len(VECTORS), bad[:5])


def test_the_two_javascript_engines_round_identically(bid_core, markup_core):
    """And the pair markup-core.js's own header already promises will not drift."""
    bad = [(v, a, b) for v, a, b in zip(VECTORS, bid_core, markup_core) if a != b]
    assert not bad, "%d disagree, first few: %r" % (len(bad), bad[:5])


@pytest.mark.parametrize("value,want", [
    (110.00000000000001, 110),      # 27,500 x 1.10 -- polish-bid-core's own documented case
    (362.00000000000006, 362),      # 724 sq ft of polish with dye -- PR #451's case
    (220.22000000000003, 221),      # a REAL fraction: rounds all the way up, guard or no guard
    (-1234.2, -1235),               # the hard-bid give-back: away from zero, not toward it
    (-856.8, -857),                 # PR #450's case; a bare ceil gives -856 and bids the job high
    (0.0, 0),
])
def test_the_named_cases_agree_across_all_three(value, want):
    """The specific numbers each fix was written against, asserted on every implementation at once
    so a future change cannot quietly fix one and leave the others behind."""
    assert pricing._roundup(value) == want
    assert _node("out(M.roundUp(%r));" % value, BID_CORE) == want
    assert _node('out(M.run("ROUNDUP(v,0)", {v: %r}));' % value, MARKUP_CORE) == want
