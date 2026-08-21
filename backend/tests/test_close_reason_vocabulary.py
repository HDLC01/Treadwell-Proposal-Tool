"""One close-out vocabulary, across two repositories and five places that spell it out.

WHY THIS FILE EXISTS. The reasons a bid can die were written down in five separate places:

  1. this tool's  frontend/js/crm-core.js   LOST_REASON        key -> label, drives the Lost tab
  2. this tool's  backend/main.py           LOST_REASONS       the keys the draft route accepts
  3. the portal's backend/main.py           _LOST_REASONS      the keys its status routes accept
  4. the portal's backend/main.py           _LOST_REASON_LABELS  key -> label, for the thread card
  5. the portal's frontend/index.html       the customer's own radio list

and NOTHING compared them. So they drifted, and the drift survived for weeks: this tool called
`another_contractor` "Another contractor" while the portal called it "Selected another contractor",
about the same key, on two screens the same person reads. Worse was possible and nearly happened
when the vocabulary was replaced on 2026-08-20 with Kyle's own list — a key accepted by one route
and unknown to the other files a bid under "Not recorded" and reads as though nobody said.

Hanz, 2026-08-20, deciding what the vocabulary IS: Kyle's eight answers verbatim, of which SIX
close the job and TWO ("Project on Hold", "Small Bid <$25k - Pending") put it on hold instead.
`other` stays even though it is not on his screenshot, because the dialog falls back to it when the
select has no value at all and both routes 422 an unknown reason.

WHY IT LIVES IN THE TOOL'S SUITE. It has to read both repositories, and this is the one whose CI
runs on every change to either half of the close-out family. It SKIPS rather than fails when the
portal is not checked out beside this repo, because a developer with one clone is not a broken
build.

BUT A SKIP THAT READS AS A PASS IS THE WHOLE DEFECT. Until 2026-08-21 the tool's CI checked out
this repo and nothing else, so the four cross-repo comparisons below skipped on every run and a
tool-only merge went green while the comparison that would have blocked it never ran. The guard
protected the dev box and nothing else. Two things fixed that and both matter:

  * .github/workflows/ci.yml now checks the portal out beside this repo (both repos are public, so
    the built-in GITHUB_TOKEN is enough and no new secret exists) and points TW_PORTAL_REPO at it.
  * test_the_cross_repo_comparison_is_not_quietly_skipped, at the bottom of this file, FAILS when
    the comparison did not run and CI says so. It is deliberately the last word rather than the
    workflow file: it asserts the OUTCOME (both portal files readable, node on PATH) rather than
    that a YAML step exists, so a renamed repo, a wrong path, a changed default branch or a
    deleted checkout step all come out red instead of green-with-four-skips.
"""
import json
import os
import pathlib
import re
import subprocess
import shutil
import warnings

import pytest

import main

HERE = pathlib.Path(__file__).resolve().parent
TOOL = HERE.parent.parent
FRONTEND = TOOL / "frontend"
# The sibling checkout. Both repos live in the same workspace folder on every machine that has
# them, and the deploy scripts already assume it. TW_PORTAL_REPO overrides that for the two callers
# that cannot use the convention: CI, where actions/checkout refuses a path outside the workspace,
# and the test that proves the loud skip fires by pointing this at nothing.
PORTAL = pathlib.Path(os.environ.get("TW_PORTAL_REPO") or (TOOL.parent / "treadwell-portal"))
PORTAL_MAIN = PORTAL / "backend" / "main.py"
PORTAL_INDEX = PORTAL / "frontend" / "index.html"

# The exact wording is load-bearing: the guard at the bottom finds the tests it speaks for by
# matching this string on their skipif mark, so a fifth comparison added later is named by the
# failure message without anyone remembering to add it to a list.
PORTAL_SKIP_REASON = ("the customer portal is not checked out beside this repo, so the cross-repo "
                      "halves of the close-out vocabulary cannot be compared")
NODE_SKIP_REASON = "node not installed"

# Both GitHub Actions and every other CI runner in common use set CI; Actions also sets
# GITHUB_ACTIONS. TW_REQUIRE_PORTAL=1 lets a developer opt into the same strictness locally.
_CI = (os.environ.get("CI", "").strip().lower() in ("1", "true", "yes")
       or bool(os.environ.get("GITHUB_ACTIONS"))
       or os.environ.get("TW_REQUIRE_PORTAL", "").strip() in ("1", "true", "yes"))

needs_portal = pytest.mark.skipif(not PORTAL_MAIN.exists(), reason=PORTAL_SKIP_REASON)
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason=NODE_SKIP_REASON)


# ── reading each of the five ─────────────────────────────────────────────────
@pytest.fixture(scope="module")
def core():
    """crm-core's own exports, evaluated. Not parsed: LOST_REASON is DERIVED from CLOSE_CHOICES,
    so a regex over the source would read an expression rather than the map the board uses."""
    src = "const m=require(%s);process.stdout.write(JSON.stringify({" \
          "lost:m.LOST_REASON,hold:m.HOLD_REASON,choices:m.CLOSE_CHOICES," \
          "customerOnly:m.CUSTOMER_ONLY_LOST_REASON}));" % json.dumps(
              str(FRONTEND / "js" / "crm-core.js"))
    r = subprocess.run(["node", "-e", src], capture_output=True, text=True,
                       encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _py_literal(path: pathlib.Path, name: str):
    """A module-level `NAME = <literal>` out of a Python file, without importing it.

    The portal's main.py cannot be imported from this suite — different dependencies, different
    settings, a FastAPI app that wants its own env — so its two declarations are read as source and
    evaluated as literals. `ast.literal_eval` and nothing else, so a file that has grown a call
    where the literal was fails loudly instead of being executed."""
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                try:
                    return ast.literal_eval(node.value)
                except ValueError:
                    # `_LOST_REASONS = tuple(_LOST_REASON_LABELS)` is deliberate — it is the fix
                    # for the drift this file hunts — so a derived declaration is not a failure.
                    return "DERIVED"
    pytest.fail("%s is gone from %s" % (name, path.name))


@pytest.fixture(scope="module")
def portal():
    p = PORTAL / "backend" / "main.py"
    return {
        "labels": _py_literal(p, "_LOST_REASON_LABELS"),
        "hold_labels": _py_literal(p, "_HOLD_REASON_LABELS"),
        "reasons": _py_literal(p, "_LOST_REASONS"),
        "hold_reasons": _py_literal(p, "_HOLD_REASONS"),
    }


@pytest.fixture(scope="module")
def customer_radios():
    """The keys and labels on the customer's own "what decided it?" radio list."""
    html = PORTAL_INDEX.read_text(encoding="utf-8")
    rows = re.findall(
        r'<input type="radio" name="sc-reason" value="([a-z_]+)">\s*([^<]+?)\s*</label>', html)
    assert rows, "the customer's reason radios are gone from the portal's index.html"
    return dict(rows)


# ── the comparisons ──────────────────────────────────────────────────────────
@needs_node
def test_the_tools_two_halves_agree_on_the_keys(core):
    """The route's accept-list against the map the board columns by. A key the route takes and the
    board has no column for files the bid under "Not recorded"; a key the board columns and the
    route refuses is a column nothing can ever land in."""
    assert set(main.LOST_REASONS) == set(core["lost"]), (
        "main.py accepts %s and crm-core columns %s"
        % (sorted(set(main.LOST_REASONS) - set(core["lost"])),
           sorted(set(core["lost"]) - set(main.LOST_REASONS))))
    assert set(main.HOLD_REASONS) == set(core["hold"]), (
        "the hold answers disagree: %s vs %s"
        % (sorted(main.HOLD_REASONS), sorted(core["hold"])))


@needs_node
@needs_portal
def test_both_repos_accept_the_same_keys(core, portal):
    """The failure this would have caused on 2026-08-20: staff close a sent bid under one of Kyle's
    new reasons, the portal 400s "invalid_reason", and the drawer says "Failed" about a bid that is
    genuinely dead. Compared in BOTH directions, so a key added to either side has to be added to
    the other before this goes green."""
    assert portal["reasons"] == "DERIVED", (
        "the portal's _LOST_REASONS is a literal again rather than tuple(_LOST_REASON_LABELS) — "
        "that second copy is what drifted from its own label map in the first place")
    assert set(portal["labels"]) == set(main.LOST_REASONS), (
        "the portal accepts %s and this tool accepts %s"
        % (sorted(set(portal["labels"]) - set(main.LOST_REASONS)),
           sorted(set(main.LOST_REASONS) - set(portal["labels"]))))
    assert set(portal["hold_labels"]) == set(main.HOLD_REASONS)


@needs_node
@needs_portal
def test_both_repos_print_the_same_words(core, portal):
    """THE ONE THAT WAS ALREADY FAILING SILENTLY. `another_contractor` read "Another contractor" in
    this repo and "Selected another contractor" in the portal, for weeks, because nothing compared
    them — the same reason on the same job, worded two ways in front of the same person. Labels are
    compared as whole maps rather than key by key, so a key with no label at all fails too."""
    assert core["lost"] == portal["labels"], (
        "the two repos disagree about how to say a reason:\n  tool:   %s\n  portal: %s"
        % (json.dumps({k: v for k, v in core["lost"].items() if portal["labels"].get(k) != v}),
           json.dumps({k: v for k, v in portal["labels"].items() if core["lost"].get(k) != v})))
    assert core["hold"] == portal["hold_labels"]


@needs_node
def test_kyles_list_is_what_the_dialog_offers_and_nothing_is_invented_beside_it(core):
    """Verbatim, in his order, and the outcome of each one declared next to it. This is the product
    decision, so it is asserted against the words on his screenshot rather than against another
    copy of the code."""
    assert [(c["label"], c["outcome"]) for c in core["choices"]] == [
        ("Not Low Bid", "lost"),
        ("No Response", "lost"),
        ("Project to Rebid", "lost"),
        ("Project on Hold", "hold"),
        ("Small Bid <$25k - Pending", "hold"),
        ("Went to Different GC", "lost"),
        ("Unable to meet GC schedule", "lost"),
        ("Project Cancelled", "lost"),
        ("Other", "lost"),
    ], core["choices"]


@needs_node
def test_a_hold_is_never_a_lost_reason_in_either_direction(core):
    """LOST_REASON drives the Lost tab's columns, so a hold key in it would put a column of live
    bids on the tab of dead ones — and a lost key in HOLD_REASON would pause a bid somebody meant
    to kill."""
    assert not (set(core["hold"]) & set(core["lost"])), (
        "these are both: %s" % sorted(set(core["hold"]) & set(core["lost"])))
    assert not (set(main.HOLD_REASONS) & set(main.LOST_REASONS))


@needs_node
@needs_portal
def test_the_customer_can_never_post_a_reason_the_portal_refuses(core, portal, customer_radios):
    """The fifth place, and the one that is not staff-facing. Kyle's list replaced the vocabulary
    for STAFF; the customer's own radios were left alone, which is right — "if you don't mind
    saying" is a different question asked of a different person. But every value they can post has
    to remain acceptable, or the customer's "Confirm" 400s and they cannot tell us they are out."""
    unknown = sorted(set(customer_radios) - set(portal["labels"]))
    assert not unknown, (
        "the customer's form offers %s, which the portal would refuse — their only way of saying "
        "they are not going ahead would fail" % unknown)


@needs_node
@needs_portal
def test_the_customers_own_reasons_still_have_a_column_on_the_lost_tab(core, customer_radios):
    """A customer closing a job themselves is the case the whole follow-up system was built for, so
    their reason must not land in "Not recorded". This is why LOST_REASON is a superset of Kyle's
    list rather than a replacement for the old one."""
    missing = sorted(set(customer_radios) - set(core["lost"]))
    assert not missing, (
        "%s can be stored by the customer's own form and has no Lost column, so those bids read as "
        "though nobody said why" % missing)


@needs_node
def test_the_customer_only_reasons_are_named_as_such_and_not_offered_to_staff(core):
    """The four that are in the map for the reader's sake and not for the dialog's. Kyle's list is
    what staff say; offering "Price" to an estimator closing a GC bid invites the wrong answer when
    "Not Low Bid" is the true one."""
    offered = {c["key"] for c in core["choices"]}
    for key in core["customerOnly"]:
        assert key in core["lost"], "%s is declared customer-only and has no label" % key
        assert key not in offered, "%s is offered to staff as well as to the customer" % key


# ── the guard on the guard ───────────────────────────────────────────────────
def _gated_comparisons(reasons):
    """The tests above that any of `reasons` switches off, read off their own marks.

    Off the marks and not out of a hand-written list, because a list is a second copy of the truth
    and this file exists because second copies drift. A fifth comparison added tomorrow is named by
    the failure message with nothing to remember."""
    names = []
    for name, obj in sorted(globals().items()):
        if not name.startswith("test_") or not callable(obj):
            continue
        for mark in getattr(obj, "pytestmark", ()):
            if mark.name == "skipif" and mark.kwargs.get("reason") in reasons:
                names.append(name)
                break
    return names


def test_the_cross_repo_comparison_is_not_quietly_skipped():
    """A skipped lockstep guard is worse than no guard, because it reads as a pass.

    THIS IS THE TEST THAT CANNOT SKIP. Everything above it can, and for a while everything above it
    did — on every CI run, invisibly, because the workflow checked out one repo. `-q` printed
    "8 passed" locally and "4 passed, 4 skipped" in CI, the exit code was 0 both times, and the
    merge gate reads the exit code.

    WHY A FAILING TEST RATHER THAN A WARNING, in CI. A warning is a line of text in a log nobody
    opens; only a non-zero exit stops a merge. And why the outcome rather than the workflow: a test
    that greps ci.yml for a checkout step passes when the step is there and pointed at the wrong
    ref, wrong path or a repo that has been renamed. This one reads the files the fixtures read, so
    the only way to satisfy it is for the comparison to have genuinely been possible.

    On a DEV BOX with one clone it warns instead, naming every comparison that did not happen.
    That is the compromise the module docstring argues for — a developer with one clone is not a
    broken build — and it is why the CI marker is part of the condition rather than the whole of it.
    Set TW_REQUIRE_PORTAL=1 to get the CI behaviour on your own machine."""
    missing = [str(p) for p in (PORTAL_MAIN, PORTAL_INDEX) if not p.exists()]
    node = shutil.which("node") is not None
    if not missing and node:
        return          # the comparison ran; there is nothing to be quiet about

    why, reasons = [], set()
    if missing:
        why.append("the customer portal checkout is missing %s (looked under %s; set "
                   "TW_PORTAL_REPO to point elsewhere)" % (", ".join(missing), PORTAL))
        reasons.add(PORTAL_SKIP_REASON)
    if not node:
        why.append("node is not on PATH, so crm-core.js could not be evaluated")
        reasons.add(NODE_SKIP_REASON)
    unchecked = _gated_comparisons(reasons)
    message = (
        "THE CROSS-REPO CLOSE-OUT GUARD DID NOT RUN, so this file proved nothing about the two "
        "repositories agreeing. %s. Unchecked: %s. Merging on this result can ship a close-out "
        "vocabulary that one repo accepts and the other 400s, which breaks every close in "
        "production until both halves are deployed - see \"Shipping a change that spans the tool "
        "and the portal\" in README.md for the order."
        % ("; ".join(why),
           ", ".join(unchecked) or "(no gated tests found - has this file been rewritten?)"))
    if _CI:
        pytest.fail(message)
    warnings.warn(message, RuntimeWarning, stacklevel=2)


def test_cis_two_halves_point_at_the_same_portal_checkout():
    """The workflow says WHERE the portal lands twice, and the two have to agree.

    NOT a substitute for the guard above, which is the thing that actually cannot be fooled. This
    one exists because the realistic way that arrangement breaks is somebody moving the checkout's
    `path:` and not the `TW_PORTAL_REPO:` beside it, or vice versa — and the guard only notices that
    on a CI run, i.e. after the push. This notices it on the dev box, before.

    Read as text rather than parsed, matching test_deploy_pipeline.py: the suite has no yaml
    dependency and the two values are on lines of their own."""
    ci = TOOL / ".github" / "workflows" / "ci.yml"
    assert ci.is_file(), "the CI workflow is gone, so nothing below means anything"
    text = ci.read_text(encoding="utf-8")
    repo = re.search(r"^\s*repository:\s*(\S+)\s*$", text, re.M)
    path = re.search(r"^\s*path:\s*(\S+)\s*$", text, re.M)
    # Not (\S+): the value is `${{ github.workspace }}/portal` and the expression has spaces in it.
    env = re.search(r"^\s*TW_PORTAL_REPO:\s*(.+?)\s*$", text, re.M)
    assert repo and path and env, (
        "CI no longer checks the portal out and points the suite at it, so the four cross-repo "
        "comparisons would skip on every run: repository=%s path=%s TW_PORTAL_REPO=%s"
        % (bool(repo), bool(path), bool(env)))
    assert repo.group(1).lower().endswith("/treadwell-portal"), repo.group(1)
    assert env.group(1).endswith("/" + path.group(1)), (
        "CI checks the portal out at %r and tells the suite to look in %r"
        % (path.group(1), env.group(1)))
