"""SEND ALL BUILDS WHAT WAS NEVER BUILT (Hanz, 2026-10-28), on the pages.

"When I add a new base bid, and add a new proposal in this set of proposals, I'm not able to send
it." The project's one press answers `needs_build` for a proposal with no document
(test_scope_send_all.py), and the page that pressed walks the tab through each such proposal's own
Proposal-step door, then back, and presses again (frontend/js/send-all-chain.js).

EXECUTED, NOT READ: js/send-all-chain-harness.js runs files-door-harness.js's world (the real
shared.js per page load, the real continueToDone and composeForFiles over the page's own form, the
real Files-page decider and freshDocuments). Each mutation test breaks ONE line in a scratch copy of
one file and requires the harness to go red; the mutation is asserted to have applied.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "send-all-chain-harness.js"
FRONTEND = TESTS.parents[1] / "frontend"
FIXTURES = ["epoxyDirect", "polishGC", "remodelTaxed", "phasePrice"]

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _run(front=None):
    args = ["node", str(HARNESS)] + ([str(front)] if front else [])
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=240)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def ran():
    return _run()


def _mutant(tmp_path, rel, old, new):
    """A scratch frontend holding ONE file of the real one with `old` replaced by `new` once (line
    endings normalised first, so the replacement cannot silently miss on a CRLF checkout)."""
    src = (FRONTEND / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert src.count(old) == 1, "the mutation's target moved: %r" % old[:60]
    out = tmp_path / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(src.replace(old, new).encode("utf-8"))
    assert out.read_bytes().decode("utf-8") != src
    return tmp_path


# ── parity: the walk builds the manual path's document ──────────────────────────────────────
@pytest.mark.parametrize("name", FIXTURES)
def test_the_walks_document_is_the_manual_paths(ran, name):
    """A proposal that was never built, composed by the Files page's door, by a door on Send all's
    walk, and by the estimator opening its tab and pressing Continue, saves the SAME draft (every
    field, the document and its composeKey stamp), and the walk's document is what the Files page's
    Generate then renders."""
    p = ran["parity"][name]
    assert p["composed"] == {"a": True, "b": True, "c": True}
    assert p["doorVsWalk"] is None, p["doorVsWalk"]
    assert p["walkVsManual"] is None, p["walkVsManual"]
    assert p["payloadWalkVsGenerated"] is None, p["payloadWalkVsGenerated"]
    assert p["keyed"] is True, "the walk's document carries no composeKey: its Files page would rebuild it"
    assert p["total"], "no price reached the document"


@pytest.mark.parametrize("name", FIXTURES)
def test_only_the_destination_differs(ran, name):
    p = ran["parity"][name]
    assert p["navA"] == [["replace", "/done.html?composed=1&d=d1"]]
    assert p["navB"] == [["replace", "/done.html?d=d0&files=1&sendall_resume=" + p["token"]]]
    assert p["recordAfter"]["done"] is True and p["recordAfter"]["built"] == ["d1"]


# ── the walk ────────────────────────────────────────────────────────────────────────────────
def test_the_walk_goes_member_by_member_then_back(ran):
    w = ran["walk"]
    tok = w["tok"]
    assert w["started"] is True
    assert w["firstDoor"] == "/proposal-review.html?d=d1&compose=files&sendall=" + tok
    assert w["firstNav"] == [["replace", "/proposal-review.html?d=d2&compose=files&sendall=" + tok]]
    assert w["progress2"] == {"label": "Room 3", "i": 2, "n": 2}
    assert w["last"] == "/done.html?d=d0&files=1&sendall_resume=" + tok
    assert w["replay"] is None, "a finished walk sent a door somewhere"
    assert w["recordDone"] is True


def test_the_door_says_it_is_building_for_send_all(ran):
    assert ran["walk"]["firstSaid"][0] == "Building Room 2 for Send all (1 of 2)…"


def test_the_page_that_pressed_takes_the_finished_walk_once(ran):
    t = ran["take"]
    assert t["own"] == {"stash": {"message": "All three.", "emails": ["buyer@acme.test"],
                                  "attachments": 0},
                        "built": ["d1", "d2"], "labels": {"d1": "Room 2", "d2": "Room 3"}}
    assert t["addressBar"][0] == "/done.html?d=d0&files=1", "the resume token stayed in the address bar"
    assert t["again"] is None, "a walk was taken twice: a reload would email the customer again"
    assert t["restartRefused"] is True, "a page that resumed could start another walk (a loop)"
    assert t["recordAfterRefusal"] is None


@pytest.mark.parametrize("case", ["otherGroup", "expired", "forged", "unfinished"])
def test_nothing_else_is_taken(ran, case):
    assert ran["take"][case] is None, case


def test_a_walk_never_starts_on_an_id_that_is_not_one(ran):
    assert ran["take"]["badId"] is False


# ── a door that stops ends the walk, and nothing is sent ───────────────────────────────────
def test_a_door_whose_template_did_not_load_stops_send_all_and_says_so(ran):
    s = ran["stops"]["noTemplate"]
    assert s["nav"] == [], "the stopped door left the page"
    assert s["note"].startswith("Send all stopped while building Room 2, so nothing was sent to the "
                                "customer. ")
    assert s["record"] is None, "the walk outlived its stop"
    assert s["resume"] is None, "the page that pressed could still resume and send"
    assert s["composed"] is False


def test_a_door_on_a_copy_saved_elsewhere_stops_send_all(ran):
    s = ran["stops"]["notTheSavedCopy"]
    assert s["nav"] == [["replace", "/done.html?d=d1"]]
    assert s["record"] is None and s["resume"] is None


# ── each new test fails without its change ─────────────────────────────────────────────────
def test_mutation_continue_ignores_the_walk(tmp_path):
    """proposal-review.js goes to its own Files page as before: no hop, no resume."""
    out = _run(_mutant(tmp_path, "js/proposal-review.js",
                       "const _files = _walk || TW.withDraft(", "const _files = TW.withDraft("))
    assert out["walk"]["firstNav"] != [["replace", "/proposal-review.html?d=d2&compose=files&sendall="
                                        + out["walk"]["tok"]]]
    assert out["parity"]["epoxyDirect"]["navB"] == [["replace", "/done.html?composed=1&d=d1"]]


def test_mutation_next_hop_broken(tmp_path):
    out = _run(_mutant(tmp_path, "js/send-all-chain.js",
                       "  function nextHop(params) {\n    var r = live(params);",
                       "  function nextHop(params) {\n    return null; var r = live(params);"))
    assert out["walk"]["last"] is None
    assert out["take"]["own"] is None


def test_mutation_abandon_keeps_the_walk(tmp_path):
    out = _run(_mutant(tmp_path, "js/send-all-chain.js",
                       "    var p = progressOf(r, get(params, \"d\"));\n    clear();",
                       "    var p = progressOf(r, get(params, \"d\"));"))
    assert out["stops"]["noTemplate"]["record"] is not None
    assert out["stops"]["notTheSavedCopy"]["record"] is not None


def test_mutation_handover_does_not_end_the_walk(tmp_path):
    out = _run(_mutant(tmp_path, "js/proposal-review.js",
                       "      stopped = true;\n      const ended = endWalk();",
                       "      stopped = true;\n      const ended = null;"))
    s = out["stops"]["noTemplate"]
    assert s["record"] is not None and not s["note"].startswith("Send all stopped")


def test_mutation_take_is_not_single_use(tmp_path):
    out = _run(_mutant(tmp_path, "js/send-all-chain.js",
                       "    if (!r || r.token !== tok) return null;\n    clear();\n    if (!r.done",
                       "    if (!r || r.token !== tok) return null;\n    if (!r.done"))
    assert out["take"]["again"] is not None
