"""The Auto Followups editor shows a tab for every email the portal says is editable.

THE BUG THIS EXISTS FOR, found 2026-08-12 while adding the deposit reminder. The editor kept its
own list of email keys and used the served labels only to RENAME the ones it already knew:

    Object.keys(LABELS).forEach(function (k) { if (j.labels[k]) LABELS[k] = j.labels[k]; })

and then painted its tabs from `Object.keys(LABELS)`. The portal had grown a fifth editable
template the day before — the "Proposal sent" email, which Hanz asked for by name — and served it
in `labels`. The editor never rendered a tab for it. The whole feature was unreachable on the page
while every backend test for it passed, because the portal's half was complete and correct.

Two pages, one vocabulary, and the SERVER owns it: its validation refusals quote these names
("the Deposit reminder email needs {link}"), so a tab that disagrees points somebody at a form that
does not exist. Taking the server's key set wholesale is also what makes the next template a
one-repo change.

Asserted against the JS source rather than a browser, because the failure is structural — a name
present in one file and absent from another — and that is exactly the shape a screenshot hides.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
EDITOR = FRONTEND / "js" / "followup-settings.js"
SRC = EDITOR.read_text(encoding="utf-8")
CODE = "\n".join(l for l in SRC.splitlines() if not l.strip().startswith("//"))

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

# What the portal serves today, in its order (followup_settings.LABELS). Not imported — the portal
# is a separate repo and a separate container; this is the contract between them, and writing it out
# is what makes a drift visible here rather than on the page.
SERVED = {
    "sent": "Proposal sent",
    "not_viewed": "Not opened yet",
    "next_steps": "After they open it",
    "second_nudge": "Second reminder",
    "checkin": "Recurring check-in",
    "deposit_nudge": "Deposit reminder",
}


def test_the_served_labels_replace_the_local_list_rather_than_renaming_it():
    """THE regression. `LABELS = served` versus copying into the keys already known: the second
    form silently cannot grow a tab, which is how the Proposal sent email shipped invisible."""
    assert "LABELS = served" in CODE, (
        "the editor is filtering the served labels through its own key list again, so a template "
        "the portal adds can never grow a tab")
    assert not re.search(r"Object\.keys\(LABELS\)\.forEach", CODE), (
        "the old rename-only loop is back")


def test_the_tabs_are_painted_from_that_set():
    assert "Object.keys(LABELS).map" in CODE, "the tab strip no longer comes from LABELS"


def test_an_empty_or_missing_labels_response_keeps_the_shipped_names():
    """A failed GET must not leave a tab strip with no tabs. The local map is the fallback, which
    is the only job it still has."""
    assert re.search(r"if \(Object\.keys\(served\)\.length\) LABELS = served", CODE), (
        "an empty labels object would wipe the tab strip")


def test_the_open_tab_is_always_one_that_exists():
    """KEY defaults to not_viewed. If the served set ever lacked it, nothing would read as
    selected and the form would edit a template with no tab."""
    assert "if (!LABELS[KEY]) KEY = Object.keys(LABELS)[0];" in CODE


def test_the_fallback_map_covers_everything_the_portal_serves():
    """It is only reached when the GET gives nothing, but that is precisely when somebody is
    already having a bad time — a strip missing two tabs would look like the page had broken."""
    for key in SERVED:
        assert re.search(r"^\s+%s:" % re.escape(key), CODE, re.M), (
            "the fallback tab list has no entry for %s" % key)


def test_every_tab_has_a_when_it_fires_heading():
    """The heading under the tabs is the only thing saying WHEN an email goes out. A missing entry
    falls back to the short tab name, which reads as a heading that failed to load."""
    titles = CODE[CODE.index("var EDITOR_TITLES"):CODE.index("var TOKENS")]
    for key in SERVED:
        assert re.search(r"\b%s:" % re.escape(key), titles), (
            "%s has no editor title, so its heading would be the bare tab name" % key)


@needs_node
def test_the_deposit_reminder_and_the_sent_email_both_get_a_tab():
    """Runs the merge FOR REAL against the payload the portal sends. Source assertions prove the
    shape; only executing it proves six tabs come out, in the order the portal listed them."""
    script = """
    const src = require("fs").readFileSync(%s, "utf8");
    // The two declarations and the merge block, lifted out of the IIFE.
    const decl = src.slice(src.indexOf("var LABELS = {"), src.indexOf("var TOKENS"));
    const merge = src.slice(src.indexOf("if (j.labels &&"), src.indexOf("$(\\"loading\\")"));
    const j = %s;
    let KEY = "not_viewed";
    const run = new Function("j", "KEY",
      decl + "\\n" + merge + "\\nreturn { keys: Object.keys(LABELS), labels: LABELS, KEY: KEY };");
    console.log(JSON.stringify(run(j, KEY)));
    """ % (json.dumps(str(EDITOR)), json.dumps({"labels": SERVED, "editor_titles": {}}))
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout.strip().splitlines()[-1])
    assert got["keys"] == list(SERVED), (
        "the editor paints %s, not the six the portal serves in its order" % got["keys"])
    assert got["labels"]["deposit_nudge"] == "Deposit reminder"
    assert got["labels"]["sent"] == "Proposal sent"


@needs_node
def test_a_template_the_editor_has_never_heard_of_still_gets_a_tab():
    """The point of the fix, stated as the next template rather than this one: adding an email to
    followup_settings.py must not need a second deploy of this page."""
    script = """
    const src = require("fs").readFileSync(%s, "utf8");
    const decl = src.slice(src.indexOf("var LABELS = {"), src.indexOf("var TOKENS"));
    const merge = src.slice(src.indexOf("if (j.labels &&"), src.indexOf("$(\\"loading\\")"));
    const j = { labels: { not_viewed: "Not opened yet", brand_new: "Something added later" } };
    let KEY = "not_viewed";
    const run = new Function("j", "KEY",
      decl + "\\n" + merge + "\\nreturn Object.keys(LABELS);");
    console.log(JSON.stringify(run(j, KEY)));
    """ % json.dumps(str(EDITOR))
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    keys = json.loads(proc.stdout.strip().splitlines()[-1])
    assert "brand_new" in keys, "a template added on the portal side still cannot grow a tab"
    assert "checkin" not in keys, (
        "the local list is being merged in, so the page would show a tab the server did not offer")
