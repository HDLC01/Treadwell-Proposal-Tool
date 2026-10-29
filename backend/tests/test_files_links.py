"""Step 5's Lump sums list opens another proposal on its draft READ AHEAD, so the page never reloads.

Hanz, 2026-10-29: "In the files page we should also look into it because when I transfer tabs with
multiple proposals it flashes white as well." The cross-fade (reveal.css, js/reveal.js) covers a
real page load, but a plain link to /done.html?d=<other> opened the other proposal's Files page on
THIS proposal's blob; shared.js initDraftSync then read the other draft and called
location.reload(), and a reload gets no fade, so the empty first frame flashed on exactly his path.
The Proposal step's tab strip already reads the other draft ahead (TW.prefetchDraft) so the page that
opens boots on it once (bootFromPrefetch). done.js wireFilesLinks / openFilesLink do the same for the
Files list: idle read-ahead of every other name, a read on hover / focus, and on a plain click a
read, a save (TW.flushState), a wait of 1.2 s at most, then location.assign. Still a real load.

Run, not read: js/files-links-harness.js executes done.js's own functions, from refreshFilesProposals
down. Each BREAK takes one part away in a scratch copy and requires its check to go red.
"""
from __future__ import annotations

import pathlib

import pytest

from _golden_support import FRONTEND, break_source
from _node import last_json_line, require_node, run_node

HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "files-links-harness.js"


def run(frontend=FRONTEND):
    proc = run_node(HARNESS, frontend)
    out = last_json_line(proc.stdout)
    assert "error" not in out, out.get("error")
    return out


@pytest.fixture(scope="module")
def out():
    require_node()
    return run()


EXPECTED = {
    "idle": ["linked", "queued", "nothingYet", "readsOthers", "once", "oneListener"],
    "click": ["prevented", "readFirst", "flushedFirst", "waitedForRead", "assigned", "onceOnly"],
    "cap": ["heldAt1199", "assignedAt1200", "secondClickIgnored"],
    "modifier": ["untouched"],
    "hover": ["reads"],
    "plain": ["linksStill", "notPrevented"],
}


@pytest.mark.parametrize("scenario", sorted(EXPECTED))
def test_a_files_list_switch_reads_the_other_draft_before_it_loads(out, scenario):
    got = out[scenario]
    assert set(got) == set(EXPECTED[scenario]), got
    assert all(got[k] is True for k in EXPECTED[scenario]), got


BREAKS = [
    # The list never wired: the plain link again, and the self-reload with it.
    ("    wireFilesLinks(id);   // each other proposal's name opens it on its draft read ahead", "",
     ("click", "prevented")),
    ("        openFilesLink(pid, a.getAttribute(\"href\"));", "", ("click", "assigned")),
    ("      try { await ahead; } catch {}", "", ("click", "waitedForRead")),
    ("      try { await TW.flushState(); } catch {}", "", ("click", "flushedFirst")),
    ("      const ahead = Promise.race([TW.prefetchDraft(pid), new Promise((r) => setTimeout(r, 1200))]);",
     "      const ahead = TW.prefetchDraft(pid);", ("cap", "assignedAt1200")),
    ("    if (filesLinks.going) return;", "", ("cap", "secondClickIgnored")),
    ("        if (e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;", "",
     ("modifier", "untouched")),
    ("    if (filesLinks.ahead) return;", "", ("idle", "once")),
    ("    const go = () => others.forEach((x) => TW.prefetchDraft(x));", "    const go = () => {};",
     ("idle", "readsOthers")),
    ('      el.addEventListener("pointerover", ahead);', "", ("hover", "reads")),
]


@pytest.mark.parametrize("old,new,where", BREAKS, ids=[f"{b[2][0]}.{b[2][1]}:{i}" for i, b in enumerate(BREAKS)])
def test_each_part_is_load_bearing(tmp_path, old, new, where):
    require_node()
    got = run(break_source(tmp_path, "js/done.js", old, new))
    scenario, key = where
    assert got[scenario][key] is False, (f"broke done.js ({old.strip()!r}) and {scenario}.{key} stayed green",
                                         got[scenario])


def test_the_scratch_copy_unbroken_is_green(tmp_path):
    """The control for the breaks: the same scratch path with a no-op replacement passes."""
    require_node()
    anchor = "    if (filesLinks.ahead) return;"
    got = run(break_source(tmp_path, "js/done.js", anchor, anchor))
    assert all(v is True for s in EXPECTED for v in got[s].values()), got
