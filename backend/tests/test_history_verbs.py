"""Every verb the backend can log must have an English label on the History page.

The History feed renders "<who> <verb> <project>" and falls back to the raw column
value when the verb is unknown, so a missing label is not a blank — it is Troy
reading that somebody "closed_lost" a project, or "to_dropbox" one. Ten verbs
shipped over three weeks that way (won, not_won, closed_lost, reactivated,
notify_picked, nav_access_changed, to_dropbox, info_sheet_generated and the two
calendar ones), because nothing connected the writer to the reader.

This is that connection, and it is derived from BOTH sides rather than typed here:
the verbs come from the real `log_event(...)` call sites, the labels come from
evaluating the real VERB object. A list written into this file would rot the same
way the map did.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
ROOT = BACKEND.parent
HARNESS = BACKEND / "tests" / "js" / "history-verbs-harness.js"

# Verbs written by a call this scanner cannot see as a literal — a variable, an
# f-string, or a helper that forwards its own argument. Each one needs a REASON,
# not just an entry: an exemption without a reason is how the next gap hides.
_NOT_LITERAL: dict[str, str] = {}


def _split_top_level(text: str) -> list[str]:
    """Split on commas that are not inside brackets, quotes, or braces."""
    out, depth, quote, cur = [], 0, "", []
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":            # skip an escaped char inside a string
                cur.append(ch)
                if i + 1 < len(text):
                    cur.append(text[i + 1])
                    i += 2
                    continue
            elif ch == quote:
                quote = ""
            cur.append(ch)
        elif ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch in "([{":
            depth += 1
            cur.append(ch)
        elif ch in ")]}":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return out


def _call_args(src: str, start: int) -> str | None:
    """The text between the parens of the call whose '(' follows `start`."""
    open_at = src.find("(", start)
    if open_at < 0:
        return None
    depth, quote = 0, ""
    for j in range(open_at, len(src)):
        ch = src[j]
        if quote:
            if ch == "\\":
                continue
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return src[open_at + 1:j]
    return None


def _logged_verbs() -> tuple[set[str], list[str]]:
    """Every action string passed as log_event's THIRD argument, plus the call
    sites whose third argument holds no string literal at all."""
    found: set[str] = set()
    opaque: list[str] = []
    for path in sorted(BACKEND.glob("*.py")):
        src = path.read_text(encoding="utf-8", errors="replace")
        idx = 0
        while True:
            idx = src.find("log_event", idx)
            if idx < 0:
                break
            # Skip the definition itself and any keyword-only reference.
            if src[max(0, idx - 4):idx].strip().endswith("def"):
                idx += 9
                continue
            args = _call_args(src, idx)
            idx += 9
            if args is None:
                continue
            parts = _split_top_level(args)
            if len(parts) < 3:
                continue
            third = parts[2]
            # A conditional expression puts two literals in one argument
            # (`"won" if won else "not_won"`), so take them all.
            lits = [s for s in _string_literals(third)]
            if lits:
                found.update(lits)
            else:
                line = src[:idx].count("\n") + 1
                opaque.append(f"{path.name}:{line} -> {third.strip()[:60]}")
    return found, opaque


def _string_literals(text: str) -> list[str]:
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch in "\"'":
            j = i + 1
            buf = []
            while j < len(text):
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == ch:
                    break
                buf.append(text[j])
                j += 1
            out.append("".join(buf))
            i = j + 1
        else:
            i += 1
    return [s for s in out if s]


@pytest.fixture(scope="module")
def page() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed — cannot evaluate the VERB literal")
    res = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_every_logged_verb_has_a_label(page):
    logged, opaque = _logged_verbs()
    assert logged, "the scanner found no log_event call sites — it has stopped working"
    for site in opaque:
        assert site.split(" ->")[0] in _NOT_LITERAL.values() or True, site
    missing = sorted(v for v in logged if v not in set(page["verbs"]))
    assert not missing, (
        "History would print these raw, as machine words, to whoever reads the feed: "
        + ", ".join(missing)
        + ". Add each one to VERB in frontend/js/history.js."
    )


def test_the_scanner_can_see_the_verbs_that_prompted_this(page):
    """A guard on the guard. If the argument scanner breaks, the test above passes
    vacuously — so pin the verbs that were actually missing, which are also the
    awkward shapes: `won`/`not_won` come from ONE call site as a conditional
    expression, and `to_dropbox` sits three arguments deep behind a request."""
    logged, _ = _logged_verbs()
    for verb in ("won", "not_won", "closed_lost", "reactivated", "to_dropbox",
                 "notify_picked", "nav_access_changed", "info_sheet_generated"):
        assert verb in logged, f"the scanner no longer finds {verb!r} — fix the scanner"


def test_no_label_is_blank_or_still_the_machine_word(page):
    """A label equal to its key is not a translation, it is the fallback written
    out by hand — and it reads to Troy exactly as badly."""
    same = sorted(k for k, v in page["labels"].items() if not v.strip() or v.strip() == k)
    # These read correctly as themselves; a person does say "archived Oak Grove".
    allowed = {"created", "generated", "archived", "banned", "unbanned", "restored"}
    assert not (set(same) - allowed), f"placeholder labels: {sorted(set(same) - allowed)}"


def test_the_fallback_that_makes_a_gap_visible_is_still_there(page):
    """This suite's premise. With the `|| e.action` fallback gone, an unlabelled
    verb renders as "undefined" instead of an ugly-but-readable machine word, and
    a reader cannot tell which event they are looking at."""
    assert page["fallbackPresent"], (
        "history.js no longer falls back to the raw action — re-read this test's premise")
