"""A proposal tab opens on its draft read ahead (Hanz, 2026-10-27: "can we make the switching of the proposals tabs more
efficient? like pre loading etc etc.").

A tab of the proposal strip opens another draft, and opening another draft was two page loads: the page ran on the old
draft's blob, initDraftSync waited for the sign-in and the profile, read the new draft, wrote it and reloaded, and the page
ran again. Now the strip reads its other tabs' drafts ahead (shared.js prefetchDraft: at idle once the strip is drawn, on a
pointer or the keyboard on a tab, and at the click), keeps each in sessionStorage with the server's `updated_at`, and the
page that opens runs ONCE on it (bootFromPrefetch). Until the server says the read is still its copy (the same
`updated_at` and the same whole copy, since the board's Won and the like are written without a new `updated_at`), every
server save is refused, exactly as for a draft adopted blind; a read that went stale is replaced by the
server's copy and the page reloads, so it costs what the old way did and is never saved over the newer copy.

Run, not read: js/tab-prefetch-harness.js runs shared.js WHOLE over one fake browser tab and server (each page load a fresh
run of the script over the same storages); js/multi-proposals-harness.js runs the strip (mountProposalTabs). The BREAKS at
the bottom prove each check goes red when the line it pins is taken out.
"""
from __future__ import annotations

import pathlib

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
BOOT = TESTS / "js" / "tab-prefetch-harness.js"
STRIP = TESTS / "js" / "multi-proposals-harness.js"
STRIP_FILES = ["js/proposal-review.js", "js/estimate-review.js", "js/price-lines-core.js", "shared.js", "js/bid-model.js",
               "js/bid-engine.js", "js/index.js", "js/polish-intake.js", "js/polish-estimate.js"]


def _run(harness, frontend=FRONTEND):
    proc = run_node(harness, frontend)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def boot():
    require_node()
    return _run(BOOT)


@pytest.fixture(scope="module")
def strip():
    require_node()
    return _run(STRIP)["page"]["ahead"]


# ── shared.js: the read, and the page that opens on it ──────────────────────────────────────────
def test_a_draft_is_read_ahead_once_per_page_and_never_this_pages_own(boot):
    o = boot["once"]
    assert o["kept"] is True and o["samePromise"] is True
    assert o["gets"] == ["B"], "one read of the other tab, none of this page's own draft"
    assert o["self"] is False
    assert o["keptVersion"] == o["rowVersion"], "kept with the server's updated_at"


def test_the_page_that_opens_runs_once_on_the_kept_read_without_asking_for_it_again(boot):
    h = boot["hit"]
    assert h["atLoad"]["snapshot"]["scope_notes"] == "B's words" and h["atLoad"]["snapshot"]["__draft_id"] == "B", \
        "the page's first snapshot is the tab's draft: no run on the old blob"
    assert h["reloads"] == 0 and h["loads"] == 1
    assert h["gets"] == ["B"], "one read, the confirmation, and nothing else"
    assert h["atLoad"]["keptLeft"] is False, "a kept read is used once"


def test_saves_are_held_until_the_server_confirms_the_kept_read_then_go(boot):
    h = boot["hit"]
    assert h["atLoad"]["blocked"] == "unverified", "a copy the server has not confirmed is not saved"
    assert h["putsWhileAsked"] == 0
    assert h["after"] == {"blocked": None, "unverified": None}, "the same updated_at lifts the hold"
    assert h["puts"] == ["typed while it was asked"] and h["server"] == "typed while it was asked", \
        "what was typed while it was asked is saved once it is confirmed"


def test_a_read_that_went_stale_is_replaced_by_the_servers_copy_and_never_saved_over_it(boot):
    s = boot["stale"]
    assert s["snapshot"] == "B's words", "the page opened on the old read"
    assert s["puts"] == 0 and s["server"] == "Kyle's newer words", "nothing typed on the old read reached the server"
    assert s["reloads"] == 1 and s["local"] == "Kyle's newer words" and s["stamp"] == "B"
    assert s["reopened"]["snapshot"] == "Kyle's newer words" and s["reopened"]["blocked"] is None


def test_a_blocked_session_storage_still_opens_the_tab_the_ordinary_way(boot):
    b = boot["blocked"]
    assert b["threw"] is False and b["kept"] is False
    assert b["reloads"] == 1 and b["snapshot"] == "B's words" and b["blocked"] is None


def test_a_blob_with_unsaved_work_is_not_given_up_for_a_kept_read(boot):
    u = boot["unsaved"]
    assert u["snapshot"] == "A", "the page did not run on the kept read"
    assert u["aSaved"] == "A, typed and not yet saved", "the ordinary open saved the other draft's work first"
    assert u["reloads"] == 1 and u["snapshotAfter"] == "B's words"


def test_an_old_kept_read_is_not_used(boot):
    assert boot["expired"] == {"snapshot": "A", "reloads": 1}


def test_a_copy_written_without_a_new_updated_at_is_never_saved_over(boot):
    """The board's Won, Lost, On hold and Hand off, and the Files page's build record, are written into the row without a
    new `updated_at` (drafts.set_won, record_generate_result ...). The same version is not the same copy."""
    u = boot["unbumped"]
    assert u["snapshotWon"] is False, "the page opened on the read made before the Won"
    assert u["putsWithoutWon"] == 0, "nothing was saved without the Won and the build record"
    assert u["reloads"] == 1 and u["reopenedWon"] is True
    assert u["serverWon"] is True and u["serverBuilt"] is True and u["serverWords"] == "typed after the reload"


def test_a_click_long_after_the_idle_read_reads_the_tab_again(boot):
    r = boot["reread"]
    assert r["getsSoon"] == 0, "an ask within seconds is the first read's"
    assert r["getsLate"] == 1 and r["kept"] is True, "minutes later it is read again"
    assert r["keptWhileReading"] is False, "the older read is not left to open the page while the new one is made"
    assert r["snapshot"] == "Kyle's newer words" and r["reloads"] == 0, "the page opens on the newer read, no reload"


def test_a_server_that_cannot_confirm_leaves_the_saves_refused(boot):
    u = boot["unreachable"]
    assert u["reloads"] == 0 and u["snapshot"] == "B's words"
    assert u["blocked"] == "unverified" and u["puts"] == 0


def test_a_tab_switch_is_one_page_load_and_four_round_trips_shorter(boot):
    t = boot["timing"]
    assert t["before"]["loads"] == 2 and t["after"]["loads"] == 1
    assert t["before"]["on"] == t["after"]["on"] == "B's words"
    # Before: token, profile, the read, the reload, token, profile. After: token, then the profile and the confirmation together.
    assert t["before"]["rts"] >= 6 and t["after"]["rts"] <= 3, t


# ── the strip ───────────────────────────────────────────────────────────────────────────────────
def test_the_strip_reads_each_other_tab_once_after_it_is_drawn_at_idle(strip):
    assert strip["beforeIdle"] == [], "nothing is read before the page is idle"
    assert strip["queued"] == 1
    assert strip["afterIdle"] == [["C2", True], ["C3", True]], "each other tab, after the strip is drawn, not this one"


def test_a_pointer_or_the_keyboard_on_another_tab_reads_it_and_on_this_one_nothing(strip):
    assert strip["hover"] == [["C2", True], ["C3", True]]


def test_a_draft_on_its_own_reads_nothing_ahead(strip):
    assert strip["alone"] == {"queued": 0, "reads": []}


def test_a_click_waits_for_its_tabs_read_then_leaves(strip):
    c = strip["click"]
    assert c["reads"] == [["C3", True]]
    assert c["waiting"] == ["prefetch", "flush"], "saved, and not gone while the read is in flight"
    assert c["after"] == ["prefetch", "flush", "assign", "/proposal-review.html?d=C3"]


# ── each check goes red without the line it pins ────────────────────────────────────────────────
BREAKS = {
    "the page does not open on the kept read": (
        BOOT, "shared.js", "  try { bootFromPrefetch(); } catch {}", "  void 0;",
        lambda r: r["hit"]["reloads"] != 0 or r["hit"]["atLoad"]["snapshot"].get("__draft_id") != "B"),
    "the kept read is never confirmed": (
        BOOT, "shared.js", "    if (_prefetchBoot) return confirmPrefetchedBoot(_prefetchBoot);", "    void 0;",
        lambda r: r["hit"]["reloads"] != 0 or r["timing"]["after"]["loads"] != 1),
    "saves are not held while it is asked": (
        BOOT, "shared.js", "    if (!isUnverified(urlId)) return;", "    clearUnverified();",
        lambda r: r["hit"]["putsWhileAsked"] != 0 or r["stale"]["server"] != "Kyle's newer words"),
    "a stale read is kept": (
        BOOT, "shared.js", "    if (row.version === boot.version && boot.whole && wholeCopy(row.data) === boot.whole) {",
        "    if (true) {",
        lambda r: r["stale"]["server"] != "Kyle's newer words" or r["stale"]["reloads"] != 1),
    "the version alone confirms the read": (
        BOOT, "shared.js", "    if (row.version === boot.version && boot.whole && wholeCopy(row.data) === boot.whole) {",
        "    if (row.version === boot.version) {",
        lambda r: r["unbumped"]["serverWon"] is not True or r["unbumped"]["putsWithoutWon"] != 0),
    "a later ask is the first read's": (
        BOOT, "shared.js", "    if (was && Date.now() - was.at < PREFETCH_FRESH_MS) return was.p;", "    if (was) return was.p;",
        lambda r: r["reread"]["getsLate"] != 1 or r["reread"]["snapshot"] != "Kyle's newer words"),
    "the older read stays while it is read again": (
        BOOT, "shared.js", '    if (was) { try { sessionStorage.removeItem(PREFETCH_KEY + ":" + id); } catch {} }', "    void 0;",
        lambda r: r["reread"]["keptWhileReading"] is not False),
    "a blob with unsaved work is given up": (
        BOOT, "shared.js", "      if (hasWork(blob) && syncedDigest(stamp) !== draftDigest(blob)) return;", "      void 0;",
        lambda r: r["unsaved"]["aSaved"] != "A, typed and not yet saved"),
    "an old read is used": (
        BOOT, "shared.js", "    if (!(Date.now() - hit.at < PREFETCH_MAX_AGE_MS)) return;", "    void 0;",
        lambda r: r["expired"]["snapshot"] != "A"),
    "a second ask reads again": (
        BOOT, "shared.js", "    if (was && Date.now() - was.at < PREFETCH_FRESH_MS) return was.p;", "    void 0;",
        lambda r: r["once"]["gets"] != ["B"] or not r["once"]["samePromise"]),
    "this page's own draft is read ahead": (
        BOOT, "shared.js", "    if (id === getDraftId() || _reloadPending || _leaving) return Promise.resolve(false);",
        "    if (_reloadPending || _leaving) return Promise.resolve(false);",
        lambda r: r["once"]["gets"] != ["B"]),
    "a kept read is used twice": (
        BOOT, "shared.js", '      sessionStorage.removeItem(PREFETCH_KEY + ":" + id);', "      void 0;",
        lambda r: r["hit"]["atLoad"]["keptLeft"] is not False),
    "what was typed while it was asked is dropped": (
        BOOT, "shared.js", "      if (cur[STAMP] === boot.id && draftDigest(cur) !== boot.digest) scheduleServerSave(cur);", "      void 0;",
        lambda r: r["hit"]["puts"] != ["typed while it was asked"]),
    "the strip reads nothing ahead": (
        STRIP, "js/proposal-review.js", "    readAhead();", "    void 0;",
        lambda r: r["page"]["ahead"]["afterIdle"] != [["C2", True], ["C3", True]]),
    "the strip reads ahead before the page is idle": (
        STRIP, "js/proposal-review.js",
        '      if (typeof window.requestIdleCallback === "function") window.requestIdleCallback(go, { timeout: 2000 });',
        "      if (true) go();",
        lambda r: r["page"]["ahead"]["beforeIdle"] != []),
    "the strip reads this tab too": (
        STRIP, "js/proposal-review.js", "      const others = ms.map((m) => m.id).filter((x) => x && x !== id);",
        "      const others = ms.map((m) => m.id).filter((x) => x);",
        lambda r: r["page"]["ahead"]["afterIdle"] != [["C2", True], ["C3", True]]),
    "a draft on its own reads ahead": (
        STRIP, "js/proposal-review.js", "      if (!TW.prefetchDraft || ms.length < 2) return;", "      if (!TW.prefetchDraft) return;",
        lambda r: r["page"]["ahead"]["alone"] != {"queued": 0, "reads": []}),
    "a pointer on a tab reads nothing": (
        STRIP, "js/proposal-review.js", '        b.addEventListener("pointerenter", ahead);', "        void 0;",
        lambda r: r["page"]["ahead"]["hover"] != [["C2", True], ["C3", True]]),
    "a pointer on the open tab reads it": (
        STRIP, "js/proposal-review.js", "if (b.dataset.ptOpen !== id && TW.prefetchDraft)", "if (TW.prefetchDraft)",
        lambda r: r["page"]["ahead"]["hover"] != [["C2", True], ["C3", True]]),
    "a click leaves before its read": (
        STRIP, "js/proposal-review.js", "      try { await ahead; } catch {}", "      void 0;",
        lambda r: r["page"]["ahead"]["click"]["waiting"] != ["prefetch", "flush"]),
    "a click does not read its tab": (
        STRIP, "js/proposal-review.js", "const ahead = TW.prefetchDraft", "const ahead = false && TW.prefetchDraft",
        lambda r: r["page"]["ahead"]["click"]["reads"] != [["C3", True]]),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_checks_go_red_when_the_code_changes(tmp_path, name):
    require_node()
    harness, rel, old, new, noticed = BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, STRIP_FILES if harness == STRIP else ["shared.js"])
    proc = run_node(harness, frontend)
    if proc.returncode != 0:
        return   # the break stopped the page outright: noticed
    assert noticed(last_json_line(proc.stdout)), "the checks did not notice: " + name
