"""Live-refreshing screens must repaint only when something changed.

WHAT WENT WRONG, AND WHERE HANZ SAW IT.

2026-08-08, with a screenshot of a small white box reading "Loading…" in the middle of a greyed
out board: "Why does this keep blinking? For example the chat in the Customer portal CRM."

Every one of these pages polls, and every one of them replaced its container's whole innerHTML on
each tick whether or not the data had moved. Rebuilding identical DOM destroys scroll position,
closes an open <select>, and reads to the eye as a blink.

    portal.js     board 25s, open drawer 12s   the shortest intervals in the app
    followups.js  45s
    projects.js   60s, and it paints twice per visit by design (cache, then fetch)

The Customer Portal CRM was worse than a blink. `openDetail` began with an unconditional
`d.innerHTML = 'Loading…'`, and `#drawer` is a fixed, centred white card over a dark scrim
(portal.html:105-110) — so every 12s poll collapsed the open drawer to one line, waited on an
uncached proxy hop to the portal (20s timeout), and rebuilt it. That white card IS the screenshot.
The chat thread lives inside that innerHTML, so the whole message list was destroyed and recreated
every 12s, and `applySecPanel` then yanked it back to the newest message even if the rep was
reading history.

Two more, found while reading the same code:

  * `load()` re-fired the `?open=<pid>` deep link on EVERY poll. Reps arrive that way as a matter
    of course (notifications.py builds the link, and the Follow-ups board links with
    &sec=followup), so the board timer re-opened a drawer they had closed, and refreshLive fired a
    second, un-awaited openDetail — two blanks and two racing fetches per tick.
  * `loadNotifyChips` keyed its cache on `pid + "|" + gen` where gen increments per render, so it
    never hit across a poll: the chip strip flashed its own "Loading…" every 12s and the cache
    grew an entry per render forever.

WHY SOURCE ASSERTIONS. The bug is structural — a missing guard, a wrong cache key, an ordering
between a capture and a teardown. The house already had the fix in four other files (crm.js,
leads.js, calendar.js, and the comment in crm.js:61 literally describes this symptom); what these
tests protect is that it is present, and that the signatures are wide enough to keep filtering
and searching working.
"""
import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"


def _src(name: str) -> str:
    return (FRONTEND / "js" / name).read_text(encoding="utf-8")


def _code(name: str) -> str:
    """Source with // comment lines stripped.

    These files explain the bug by describing it, so a raw grep matches its own prose. That has
    caught me out repeatedly in this repo.
    """
    return "\n".join(l for l in _src(name).splitlines() if not l.strip().startswith("//"))


def _block(name: str, fn: str) -> str:
    """The body of a top-level `function fn(...) {` in js/<name>.

    Brace-counted rather than regex'd, so a nested template literal containing a brace cannot
    truncate the block and make the assertion vacuous. Same helper as test_drawer_followup.py.
    """
    src = _code(name)
    m = re.search(r"\n\s{2,6}(?:async\s+)?function " + re.escape(fn) + r"\s*\(", src)
    assert m, "%s() is gone from %s — these tests need rewriting, not deleting" % (fn, name)
    i = src.index("{", m.end())
    depth, j = 0, i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
        j += 1
    pytest.fail("unbalanced braces reading %s() in %s" % (fn, name))


# ── the guard exists on every page that polls ─────────────────────────────────
#
# The three that were missing it. crm.js / leads.js / calendar.js already had it and are checked
# here too, so removing one of those is a failure rather than a silent regression.
POLLING_PAGES = [
    ("portal.js", "renderBoard", "BOARD_SIG"),
    ("followups.js", "paint", "LAST_SIG"),
    ("projects.js", "paint", "LAST_SIG"),
    ("crm.js", "paint", "LAST_SIG"),
    ("leads.js", "paint", "LAST_SIG"),
]


@pytest.mark.parametrize("page,fn,var", POLLING_PAGES)
def test_the_paint_is_signature_guarded(page, fn, var):
    """A compare-and-return before any innerHTML, or the poll rebuilds identical DOM."""
    body = _block(page, fn)
    assert var in body, "%s has no signature variable" % page
    m = re.search(r"if\s*\(\s*sig\s*===\s*" + var + r"\s*\)\s*return", body)
    assert m, "%s does not bail out when the signature is unchanged" % page
    inner = body.find("innerHTML")
    if inner != -1:
        assert m.start() < inner, (
            "%s paints before it checks the signature, so the guard does nothing" % page)


@pytest.mark.parametrize("page,fn,var", POLLING_PAGES)
def test_the_signature_is_assigned_not_just_compared(page, fn, var):
    """Comparing without storing means every paint looks like a change."""
    body = _block(page, fn)
    assert re.search(var + r"\s*=\s*sig", body), "%s never stores the new signature" % page


# ── the signatures have to be WIDE enough ─────────────────────────────────────
#
# Too narrow is the failure mode that looks like a fix. Guard on the data alone and the board
# stops responding to its own filters: typing in the search box, switching tab, re-sorting or
# flipping to the table view all leave the DOM untouched.
#
# portal.js lost SHOW_LOST on 2026-08-10: closed-lost proposals came off the live board, so there
# is no toggle left to guard. TAB took its place (Active / Test, and Lost since 2026-08-12), and
# the lost COUNT joined the list because it is painted outside the board's innerHTML — it is a tab
# badge. See test_active_projects_board.py, which owns both of those.
@pytest.mark.parametrize("page,fn,names", [
    # PERIOD, not MONTH: portal.js's filter grew weeks alongside months on 2026-08-12 and the
    # variable was renamed with it. projects.js below still has a month-only filter.
    ("portal.js", "renderBoard", ["ALL", "EST", "PERIOD", "SORTFIELD", "SORTDIR", "TAB", "VIEW"]),
    ("followups.js", "paint", ["ALL", "TAB", "EST", "SORT", "DIR", "Q", "VIEW"]),
    ("projects.js", "paint", ["ALL_PROJECTS", "CURRENT_FILTER", "SEARCH", "MONTH",
                              "SORTFIELD", "SORTDIR", "VIEW"]),
])
def test_the_signature_covers_the_data_and_every_filter(page, fn, names):
    body = _block(page, fn)
    sig = body[body.index("JSON.stringify"):body.index("\n", body.index("JSON.stringify"))]
    # multi-line signatures: take up to the closing bracket
    end = body.index("])", body.index("JSON.stringify"))
    sig = body[body.index("JSON.stringify"):end + 2]
    for n in names:
        assert re.search(r"\b" + re.escape(n) + r"\b", sig), (
            "%s's signature omits %s, so changing it would not repaint" % (page, n))


def test_the_portal_board_signature_includes_the_search_box():
    """Portal keeps its search term in the DOM rather than a variable, so it has to be read out
    of the input or typing filters nothing."""
    body = _block("portal.js", "renderBoard")
    end = body.index("])", body.index("JSON.stringify"))
    sig = body[body.index("JSON.stringify"):end + 2]
    assert "search" in sig, "the portal board ignores its own search box"


def test_the_portal_guard_runs_before_the_filter_selects_are_rebuilt():
    """populateEstimators/populatePeriods rebuild <select> options. Rebuilding a <select> closes it
    under the cursor of anyone who had it open, so an unchanged poll must not reach them."""
    body = _block("portal.js", "renderBoard")
    guard = body.index("BOARD_SIG) return")
    for fn in ("populateEstimators()", "populatePeriods()"):
        assert guard < body.index(fn), "%s runs before the signature guard" % fn


# ── a failed poll must not throw away a populated screen ──────────────────────
@pytest.mark.parametrize("page,fn,var,data", [
    ("portal.js", "load", "BOARD_SIG", "ALL"),
    ("followups.js", "load", "LAST_SIG", "ALL"),
])
def test_a_failed_poll_never_blanks_a_populated_board(page, fn, var, data):
    """These run on a timer all day. One blip used to replace a board somebody was working from
    with an error message."""
    body = _block(page, fn)
    cat = body.index("catch")
    tail = body[cat:]
    assert re.search(r"if\s*\(\s*!" + data + r"\.length\s*\)", tail), (
        "%s paints its load error unconditionally" % page)


@pytest.mark.parametrize("page,fn,var", [
    ("portal.js", "load", "BOARD_SIG"),
    ("followups.js", "load", "LAST_SIG"),
])
def test_a_repeated_identical_error_does_not_repaint_either(page, fn, var):
    """The error is part of what is on screen, so it belongs IN the signature.

    Caught in a browser, on staging, where the portal backend is genuinely unreachable. The first
    version of this fix CLEARED the signature when it painted the error — which repainted the
    identical message every 25s. A MutationObserver counted three rebuilds in sixty seconds: the
    same blink, in the one situation where a blink is least useful.

    Holding the message keeps an unchanged error silent. A recovery produces a data signature,
    which differs, so it repaints — that is what clearing was reaching for, without the flashing.
    """
    body = _block(page, fn)
    tail = body[body.index("catch"):]
    assert re.search(r'"error:"', tail), (
        "%s does not put the error message into the signature" % page)
    assert re.search(r"if\s*\(\s*esig\s*!==\s*" + var + r"\s*\)", tail), (
        "%s repaints the error even when it is identical to the one already showing" % page)
    assert re.search(var + r"\s*=\s*esig", tail), (
        "%s never stores the error signature, so the comparison can never match" % page)
    assert not re.search(var + r'\s*=\s*""', tail), (
        "%s clears the signature on error, which repaints the same message on every poll" % page)


# ── the drawer: the actual white box in the screenshot ────────────────────────
def test_the_open_drawer_is_never_blanked_to_a_loading_box():
    """The reported bug. The blank has to be the ELSE of a cached render, not the first thing the
    function does."""
    body = _block("portal.js", "openDetail")
    assert "DETAIL_CACHE[pid]" in body, "there is no cached render to fall back on"
    m = re.search(r"if\s*\(\s*DETAIL_CACHE\[pid\]\s*\)\s*renderDetail", body)
    assert m, "openDetail does not render the cached payload first"
    blank = body.index("Loading…")
    assert m.start() < blank, "the drawer is blanked before the cache is consulted"
    between = body[m.end():blank]
    assert "else" in between, (
        "the Loading blank is unconditional; it must only happen when there is nothing cached")


def test_the_drawer_repaint_is_signature_guarded():
    body = _block("portal.js", "renderDetail")
    m = re.search(r"if\s*\(\s*sig\s*===\s*DRAWER_SIG\s*\)\s*return", body)
    assert m, "renderDetail repaints unconditionally, so the 12s poll rebuilds the whole drawer"
    assert m.start() < body.index("innerHTML"), "it paints before checking"


def test_the_drawer_signature_tracks_unread_as_well_as_the_payload():
    """The Chat badge is read off the BOARD row, not this payload, so it can change while the
    proposal is untouched. Leave it out and the badge goes stale under a correct-looking guard."""
    body = _block("portal.js", "renderDetail")
    end = body.index("])", body.index("JSON.stringify"))
    sig = body[body.index("JSON.stringify"):end + 2]
    assert "unread" in sig
    assert "pid" in sig, "two projects with identical payloads would not repaint"


def test_the_active_tab_is_NOT_in_the_drawer_signature():
    """Switching tab only toggles classes — it never re-renders. Putting ACTIVE_SEC in the
    signature would repaint the entire drawer on every tab click, which is the bug again."""
    body = _block("portal.js", "renderDetail")
    end = body.index("])", body.index("JSON.stringify"))
    sig = body[body.index("JSON.stringify"):end + 2]
    assert "ACTIVE_SEC" not in sig


def test_closing_the_drawer_clears_its_signature():
    """Otherwise reopening the same proposal with unchanged data is skipped as "already showing
    that" — an empty drawer, and defaultSection's routing never runs."""
    assert "DRAWER_SIG" in _block("portal.js", "closeDrawer")


def test_a_stale_detail_response_cannot_paint_a_closed_or_switched_drawer():
    """Two fetches can be in flight: a poll and a click, or two clicks. The slower one must not
    paint over the newer one, or repopulate a drawer the rep has closed."""
    body = _block("portal.js", "openDetail")
    assert "++DETAIL_GEN" in body, "there is no generation counter"
    assert body.index("++DETAIL_GEN") < body.index("await api("), (
        "the generation is taken after the fetch, which proves nothing")
    checks = re.findall(r"gen\s*!==\s*DETAIL_GEN", body)
    assert len(checks) >= 2, (
        "the generation is not re-checked after every await — the success and error paths both "
        "need it")
    assert "pid !== CUR_PID" in body, "a response can still paint into a closed drawer"


def test_a_failed_refresh_keeps_the_last_good_drawer():
    body = _block("portal.js", "openDetail")
    tail = body[body.index("catch"):]
    assert "DETAIL_CACHE[pid]" in tail, (
        "a poll that fails replaces the drawer with an error instead of leaving what was there")


# ── the deep link ─────────────────────────────────────────────────────────────
def test_the_deep_link_is_consumed_once_not_on_every_poll():
    """load() re-runs every 25s. Unguarded, ?open= re-opened a drawer the rep had closed and
    doubled up with refreshLive's own openDetail."""
    body = _block("portal.js", "load")
    m = re.search(r'get\("open"\)', body)
    assert m, "the deep link read has moved; rewrite this test"
    tail = body[m.end():]
    assert "DEEPLINK_USED" in tail, "the ?open= deep link still fires on every poll"
    assert re.search(r"if\s*\(\s*openId\s*&&\s*!DEEPLINK_USED\s*\)", tail)


# ── chat scroll ───────────────────────────────────────────────────────────────
def test_the_chat_position_is_captured_before_the_thread_is_destroyed():
    """renderDetail is the only place that destroys #thread, so the capture belongs there — every
    path through it (poll, action, reply, chip) needs the position kept, not just the poll."""
    body = _block("portal.js", "renderDetail")
    assert "THREAD_SCROLL" in body, "nothing records where the chat was scrolled to"
    assert body.index("THREAD_SCROLL") < body.index("innerHTML"), (
        "the capture happens after the thread has already been replaced, so it reads the new node")
    assert "atBottom" in body


def test_reading_older_messages_is_not_yanked_to_the_newest():
    """The rAF used to set scrollTop = scrollHeight unconditionally, every 12s."""
    body = _block("portal.js", "applySecPanel")
    raf = body[body.index("requestAnimationFrame"):]
    assert "atBottom" in raf, "the chat snaps to the bottom regardless of where the rep was"
    assert "THREAD_SCROLL = null" in raf, (
        "the capture is not consumed, so a later tab switch would restore a stale position "
        "instead of landing on the newest message")


def test_refresh_live_no_longer_juggles_the_scroll_itself():
    """It read a #thread that a concurrent openDetail had already replaced. The capture moved into
    renderDetail; leaving both in place means they fight."""
    body = _block("portal.js", "refreshLive")
    assert "scrollTop" not in body, "refreshLive still moves the chat scroll behind renderDetail"


def test_refresh_live_keeps_the_board_in_step_and_respects_typing():
    """Order matters: the board carries the unread count the Chat badge shows, and the busy check
    has to sit between it and the drawer repaint."""
    body = _block("portal.js", "refreshLive")
    assert body.index("await load()") < body.index("drawerBusy()") < body.index("openDetail(CUR_PID)")


# ── notify chips ──────────────────────────────────────────────────────────────
def test_the_chip_cache_is_keyed_by_project_not_by_render():
    """`pid + "|" + gen` never hit across a poll: the strip refetched and flashed its own
    "Loading…" every 12s, and the cache grew an entry per render forever."""
    body = _block("portal.js", "loadNotifyChips")
    assert '"|" + gen' not in body and "'|' + gen" not in body, (
        "the chip cache is still keyed per render")
    assert "NT_CACHE[pid]" in body


def test_a_chip_cache_hit_paints_synchronously():
    """It has to land in the same frame as the drawer's innerHTML. Storing a bare marker instead
    of the payload would return early and strand the static "Loading…" markup on screen."""
    body = _block("portal.js", "loadNotifyChips")
    hit = re.search(r"if\s*\(\s*NT_CACHE\[pid\]\s*\)\s*\{[^}]*paintNtChips", body)
    assert hit, "a cache hit does not paint"
    assert body.index("paintNtChips") < body.index("await api("), (
        "the cached paint happens after a network call, which is the flash again")
    assert re.search(r"NT_CACHE\[pid\]\s*=\s*j", body), (
        "the fetched payload is not cached, so the next poll refetches")


def test_toggling_a_chip_repaints_the_chips_not_the_whole_drawer():
    """This is a correctness fix as well as a blink one: the overrides are NOT part of the
    proposal payload, so the drawer signature would find nothing changed, skip the repaint, and
    the toggle would never appear to take effect."""
    body = _block("portal.js", "paintNtChips")
    assert "delete NT_CACHE[pid]" in body, "the stale chip payload is not invalidated"
    assert "loadNotifyChips(pid" in body
    assert "openDetail(pid)" not in body, (
        "toggling a chip still rebuilds the entire drawer, and now silently does nothing")


def test_the_stale_chip_write_guard_survives():
    """A re-render mid-fetch would otherwise write chips into a detached node."""
    body = _block("portal.js", "paintNtChips")
    assert "gen !== RENDER_GEN" in body
    assert 'wrap = $("nt-chips")' in body, "the node is not re-read after the await"


# ── liveness was the point; don't let a "fix" delete it ───────────────────────
def test_the_polls_are_still_there_at_the_same_cadence():
    """The blink had an easy wrong fix: stop polling, or poll rarely. Live updates were an
    explicit feature ("no more F5"). The refresh is meant to be silent, not absent."""
    portal = _code("portal.js")
    assert "BOARD_POLL_MS = 25000" in portal
    assert "DRAWER_POLL_MS = 12000" in portal
    assert "setInterval" in portal
    assert "45000" in _code("followups.js")
    assert "60000" in _code("projects.js")
