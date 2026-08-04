"""A template switch must not throw away the other template's hand edits.

Found while fixing the blank-Epoxy-preview bug, in the same switch path. There was exactly
one slot for saved paragraph edits — `paragraph_overrides` plus one `_meta` — and every save
overwrote it with the currently rendered template's edits. So:

    edit the Epoxy proposal  ->  switch base bid to Polish  ->  switch back to Epoxy
    = the Epoxy edits are gone

That is the estimator's own typing, discarded with no warning and no undo. It also meant
`restoreSavedOverrides` had nothing to restore from after a switch, so the edits looked like
they "never stuck".

Now each template gets its own entry keyed by work type + audience (the two things that pick
the file), each carrying the template version its paragraph ids were captured against.

TWO CONTRACTS THIS MUST NOT BREAK, both pinned below:
  * `/api/generate` reads the FLAT `paragraph_overrides` + `_meta` (backend/main.py:326), and
    so does collectOverrides()'s fallback for when the editor never loaded. Those keep being
    written for the current template — this adds a store, it does not replace one.
  * A draft saved BEFORE this change has edits only in the old shape. It has to keep
    restoring, and its legacy slot must never be handed to a different template, whose
    paragraph ids would not match.

The JS is exercised under node because this is pure state logic with no DOM in it; the
harness matches test_crm_core_js.py / test_calendar_core_js.py.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
JS = FRONTEND / "js" / "proposal-review.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                               reason="node is not installed")


@pytest.fixture(scope="module")
def src():
    return JS.read_text(encoding="utf-8")


def _extract(src: str, *names: str) -> str:
    """Lift named helpers out of the page script by brace-matching.

    Same approach as test_drawer_followup.py's `_block()`: the file is a big IIFE full of DOM
    references, so it cannot be required wholesale. Extracting the pure functions means the
    test runs the SHIPPED source rather than a copy that can drift."""
    out = []
    for name in names:
        m = re.search(r"^(  (?:const|function) " + re.escape(name) + r"\b)", src, re.M)
        assert m, f"{name} not found — it was renamed or removed"
        i = m.start()
        # An arrow const on one line ends at its newline; a function ends at its brace.
        if src[i:].lstrip().startswith("const"):
            out.append(src[i:src.index("\n", i)])
            continue
        depth, j = 0, src.index("{", i)
        for k in range(j, len(src)):
            if src[k] == "{":
                depth += 1
            elif src[k] == "}":
                depth -= 1
                if depth == 0:
                    out.append(src[i:k + 1])
                    break
    return "\n".join(out)


def run(src: str, script: str):
    """Run `script` against the extracted helpers, with `state` injectable."""
    # The MERGE is extracted too, not mirrored. An earlier draft of this file kept a local
    # copy of it — and when the shipped merge was deliberately broken, only the source-text
    # assertion noticed. A behavioural test that exercises a copy proves nothing about the
    # code that ships, so all three helpers come out of the real file.
    helpers = _extract(src, "overrideKey", "mergeOverrideEntry", "savedOverridesFor")
    # savedOverridesFor closes over the module-level `state`; give it a settable one.
    prelude = "let state = {};\n" + helpers + "\n"
    # persist() does only what schedulePersistOverrides does AROUND the shipped merge: call
    # it, and keep the flat field in lockstep for /api/generate.
    prelude += """
function persist(wt, audience, templateVersion, items) {
  state = Object.assign({}, state, {
    paragraph_overrides_all:
      mergeOverrideEntry(state.paragraph_overrides_all, wt, audience, templateVersion, items),
    paragraph_overrides: items,
    paragraph_overrides_meta: { template_version: templateVersion, work_type: wt, audience: audience },
  });
}
const out = (v) => console.log(JSON.stringify(v));
"""
    proc = subprocess.run(["node", "-e", prelude + script],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── the reported bug ──────────────────────────────────────────────────
def test_edits_survive_a_round_trip_through_another_template(src):
    """THE bug. Epoxy edits must still be there after visiting Polish and coming back."""
    got = run(src, """
      persist("epoxy", "Direct", "v1", [{id: 7, text: "EPOXY EDIT"}]);
      persist("polish", "Direct", "v1", []);
      out(savedOverridesFor("epoxy", "Direct").items);
    """)
    assert got == [{"id": 7, "text": "EPOXY EDIT"}]


def test_each_template_keeps_its_own_edits(src):
    got = run(src, """
      persist("epoxy", "Direct", "v1", [{id: 7, text: "E"}]);
      persist("polish", "Direct", "v1", [{id: 3, text: "P"}]);
      out([savedOverridesFor("epoxy","Direct").items[0].text,
           savedOverridesFor("polish","Direct").items[0].text]);
    """)
    assert got == ["E", "P"]


def test_audience_is_part_of_the_key(src):
    """Same work type, different audience, different FILE — and therefore different
    paragraph ids. A Direct edit must not be replayed into the GC template."""
    got = run(src, """
      persist("epoxy", "Direct", "v1", [{id: 7, text: "DIRECT"}]);
      persist("epoxy", "GC", "v1", [{id: 9, text: "GC"}]);
      out([savedOverridesFor("epoxy","Direct").items[0].text,
           savedOverridesFor("epoxy","GC").items[0].text]);
    """)
    assert got == ["DIRECT", "GC"]


# ── migration: drafts saved before this change ────────────────────────
def test_a_legacy_single_slot_draft_still_restores(src):
    """A draft in progress right now has its edits only in the old shape. Dropping that
    fallback would lose exactly the work this change exists to protect."""
    got = run(src, """
      state = { paragraph_overrides: [{id: 2, text: "OLD"}],
                paragraph_overrides_meta: {template_version: "v1", work_type: "epoxy", audience: "Direct"} };
      out(savedOverridesFor("epoxy", "Direct").items);
    """)
    assert got == [{"id": 2, "text": "OLD"}]


def test_the_legacy_slot_is_never_offered_to_a_different_template(src):
    """Its paragraph ids were captured against another file; replaying them would rewrite
    whichever paragraphs happen to share those numbers."""
    got = run(src, """
      state = { paragraph_overrides: [{id: 2, text: "OLD"}],
                paragraph_overrides_meta: {template_version: "v1", work_type: "epoxy", audience: "Direct"} };
      out(savedOverridesFor("polish", "Direct"));
    """)
    assert got is None


def test_the_keyed_store_wins_over_the_legacy_slot(src):
    """Once migrated, the per-template entry is authoritative — otherwise a stale flat field
    could shadow a newer edit."""
    got = run(src, """
      state = { paragraph_overrides: [{id: 2, text: "STALE"}],
                paragraph_overrides_meta: {template_version: "v1", work_type: "epoxy", audience: "Direct"},
                paragraph_overrides_all: {"epoxy:Direct": {template_version: "v1", items: [{id: 2, text: "FRESH"}]}} };
      out(savedOverridesFor("epoxy", "Direct").items[0].text);
    """)
    assert got == "FRESH"


def test_a_missing_entry_reads_as_nothing_saved(src):
    got = run(src, 'out([savedOverridesFor("gyp","Direct"), savedOverridesFor("","")]);')
    assert got == [None, None]


def test_a_malformed_entry_does_not_throw(src):
    """State is user data round-tripped through the draft store; a garbled entry must read as
    absent rather than break the page on load."""
    got = run(src, """
      state = { paragraph_overrides_all: {"epoxy:Direct": {template_version:"v1", items:"nope"}} };
      out(savedOverridesFor("epoxy","Direct"));
    """)
    assert got is None


# ── the contracts that must not break ─────────────────────────────────
def test_the_version_is_stored_per_entry(src):
    """Paragraph ids shift when the template is re-annotated, so each entry has to remember
    which version it was captured against — a single global version can't describe two."""
    got = run(src, """
      persist("epoxy","Direct","v1",[{id:1,text:"X"}]);
      persist("polish","Direct","v2",[{id:1,text:"Y"}]);
      out([savedOverridesFor("epoxy","Direct").template_version,
           savedOverridesFor("polish","Direct").template_version]);
    """)
    assert got == ["v1", "v2"]


def test_the_flat_field_still_describes_the_current_template(src):
    """/api/generate and collectOverrides()'s fallback read the FLAT field. After a switch it
    must describe what is on screen now, not what was there before."""
    got = run(src, """
      persist("epoxy","Direct","v1",[{id:1,text:"X"}]);
      persist("polish","Direct","v1",[]);
      out([state.paragraph_overrides.length, state.paragraph_overrides_meta.work_type]);
    """)
    assert got == [0, "polish"]


def test_restore_still_checks_the_template_version(src):
    """Guard against the fix loosening the invariant it inherited: an entry from another
    version of the same template must not be replayed."""
    body = _extract(src, "restoreSavedOverrides")
    assert "template_version" in body and "templateVersion" in body


def test_the_merge_keeps_siblings(src):
    """The behaviour the whole fix rests on, run against the SHIPPED merge function."""
    got = run(src, """
      let all = mergeOverrideEntry(null, "epoxy", "Direct", "v1", [{id:1,text:"E"}]);
      all = mergeOverrideEntry(all, "polish", "Direct", "v1", [{id:2,text:"P"}]);
      out(Object.keys(all).sort());
    """)
    assert got == ["epoxy:Direct", "polish:Direct"]


def test_the_merge_does_not_mutate_what_it_was_given(src):
    """It is handed `state.paragraph_overrides_all`. Mutating that in place would edit
    persisted state behind TW.setState's back, which is how two tabs end up disagreeing."""
    got = run(src, """
      const before = mergeOverrideEntry(null, "epoxy", "Direct", "v1", []);
      const after = mergeOverrideEntry(before, "polish", "Direct", "v1", []);
      out([Object.keys(before).length, Object.keys(after).length]);
    """)
    assert got == [1, 2]


def test_both_writers_go_through_the_one_merge(src):
    """Two places persist overrides — the debounced save and Continue. Both must use the
    shared merge, or one can quietly start replacing the store again."""
    for fn in ("function schedulePersistOverrides()",
               "const paragraphOverrides = collectOverrides();"):
        i = src.index(fn)
        assert "mergeOverrideEntry(" in src[i:i + 1400], f"{fn} does not use the shared merge"


def test_continue_also_files_the_current_template(src):
    """An edit made inside the 800 ms debounce would otherwise reach generation but never the
    store, and vanish at the next switch."""
    i = src.index("const paragraphOverrides = collectOverrides();")
    block = src[i:i + 1200]
    assert "paragraph_overrides_all" in block
