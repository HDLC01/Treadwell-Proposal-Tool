"""The startup warm builds EVERY tab, and still does not hold the boot up.

WHAT IT USED TO DO. Three tabs of sixteen — Epoxy, Polish, and the USG 1-8" gypsum sheet.
Measured 2026-09-17 on the dev box in a cold process: building all sixteen grids costs 7,469 ms
and those three are 3,872 ms of it. So after every deploy the first estimator to open
estimate-review paid ~3.6 s of grid construction for tabs the warm had skipped, inside their
own request, and paid it again per tab as they clicked along the bar.

"THE TABS PEOPLE USE" WAS NEVER A USEFUL FILTER, which is the reasoning worth keeping. The tab
bar lists all sixteen; the page fetches whichever one is clicked. Warming a subset does not
make the others cheap, it just decides which estimator pays.

WHAT THIS MODULE WILL NOT LET DRIFT:

  * coverage — asserted against the workbook's OWN tab list, not a list typed in this file.
    The old three-name tuple is exactly the shape that goes stale when Kyle adds a tab, and
    a test that repeats the tuple would go stale with it.
  * it must not block startup. That is the entire reason this runs on a thread, and a
    refactor that awaits the warm would turn a deploy into a seven-second outage on a box
    running thirteen containers. Executed by parking the warm inside the first tab and timing
    how long the HOOK takes to return — see the long note on that test for why the obvious
    version of it could not fail.
  * a tab that cannot be built must not stop the others, and must not take the process down.
    Nothing joins this thread, so an escaping exception is logged by the interpreter and lost.
"""
import threading
import time

import pytest

import estimate_writer
import main


@pytest.fixture
def fake_warm(monkeypatch):
    """Replace the expensive part. This module is about WHICH tabs get warmed and WHEN, and
    building sixteen real grids to find out costs seven seconds per test."""
    built = []
    monkeypatch.setattr(estimate_writer, "read_sheet_grid",
                        lambda name, **kw: built.append(name) or {"sheet": name})
    return built


# ── coverage ─────────────────────────────────────────────────────────────────
def test_the_warm_builds_every_tab_in_the_workbook(fake_warm):
    """THE ONE THAT MATTERS, and the reason it reads the workbook rather than a list here: if
    this file named the tabs, adding a seventeenth would leave the test green and the tab cold."""
    main._warm_all_sheets()
    assert sorted(fake_warm) == sorted(estimate_writer.list_sheet_names()), (
        "warmed %d of %d tabs; missed %r"
        % (len(fake_warm), len(estimate_writer.list_sheet_names()),
           sorted(set(estimate_writer.list_sheet_names()) - set(fake_warm))))


def test_there_are_more_tabs_than_the_warm_used_to_cover(fake_warm):
    """The counterexample for the test above. If the workbook only ever had three tabs, warming
    "all of them" and warming _WARM_FIRST would be the same act and the coverage assertion
    would prove nothing about the change."""
    assert len(estimate_writer.list_sheet_names()) > len(main._WARM_FIRST), (
        "the template has no more tabs than _WARM_FIRST names, so 'warm them all' is not a "
        "change and the test above cannot fail")


def test_the_likely_tabs_are_built_first_even_when_the_workbook_lists_them_last(
        fake_warm, monkeypatch):
    """A grid built in the background only helps if it lands before somebody asks for it, and
    somebody opening estimate-review shortly after a deploy asks for Epoxy: it is the tab the
    page opens on. Order, not membership — everything gets built either way.

    THE TAB LIST IS REVERSED HERE ON PURPOSE, and this test was worthless until it was. The
    real workbook happens to list Epoxy, Polish and the USG 1-8" sheet as its first three tabs
    — the same three, in the same order, that _WARM_FIRST names. So against the real template,
    `ordered = list(names)` (no prioritisation at all) produces a byte-identical warm order,
    and this assertion passes just as happily with the whole mechanism deleted. Caught by
    mutation on 2026-09-17: replacing the ordering expression with `list(names)` left all eight
    tests in this file green.

    Reversing the list is the counterexample that makes the two disagree. Now the only way the
    warm can still start with Epoxy is if something actually prioritises it."""
    upside_down = list(reversed(estimate_writer.list_sheet_names()))
    assert upside_down[:len(main._WARM_FIRST)] != list(main._WARM_FIRST), (
        "the reversed tab list still leads with _WARM_FIRST, so this test is back to proving "
        "nothing")
    monkeypatch.setattr(estimate_writer, "list_sheet_names", lambda **kw: list(upside_down))

    main._warm_all_sheets()
    assert fake_warm[:len(main._WARM_FIRST)] == list(main._WARM_FIRST), (
        "the warm started with %r instead of %r — it is following the workbook's own tab order, "
        "so the tab estimate-review opens on is built last"
        % (fake_warm[:len(main._WARM_FIRST)], main._WARM_FIRST))
    assert sorted(fake_warm) == sorted(upside_down), "prioritising dropped or duplicated a tab"


def test_the_warm_leaves_the_tab_list_cached_for_the_request_that_gates_the_page(fake_warm):
    """`/api/sheets` is the first fetch estimate-review makes and everything queues behind it.
    The warm needs the tab names anyway, so calling list_sheet_names() here is what leaves that
    request answerable from memory — a free win that vanishes silently if the loop ever stops
    going through the cached accessor."""
    estimate_writer._SHEET_NAMES_CACHE.clear()
    main._warm_all_sheets()
    assert estimate_writer._SHEET_NAMES_CACHE, (
        "the warm finished without populating the tab-name cache, so the first /api/sheets "
        "after a deploy still opens the workbook")


# ── it must not block startup ────────────────────────────────────────────────
HANG = 3.0          # how long the fake warm parks inside the first tab
RETURNED_FAST = 1.5  # what "the hook did not wait for it" is allowed to cost


def test_the_startup_hook_returns_while_the_warm_is_still_running(monkeypatch):
    """EXECUTED, not argued. `/healthz` has to answer while sixteen grids are being built; a
    warm that ran inline would make every deploy a multi-second outage, and on a shared box
    that is how a deploy takes production down.

    THE SHAPE HERE IS NOT INCIDENTAL, and the obvious version of this test does not work. The
    first draft parked the warm on an Event and let the TEST release it afterwards — which is
    unfalsifiable, because if the hook runs inline the test never reaches the line that
    releases it, the wait times out, the exception is swallowed by the warm loop's per-tab
    except, and the hook returns and the test passes. Caught by mutation on 2026-09-17:
    replacing `threading.Thread(...).start()` with a direct call left this green (and the run
    162 seconds slower, which is the only thing that gave it away).

    So the release comes from a WATCHDOG started before the hook, and the assertion is on how
    long the HOOK ITSELF took. Off-thread it returns in microseconds. Inline it cannot return
    until the watchdog frees the first tab, which is HANG seconds away."""
    started = threading.Event()
    release = threading.Event()
    threading.Timer(HANG, release.set).start()

    def blocking(name, **kw):
        started.set()
        release.wait(30)
        return {"sheet": name}

    monkeypatch.setattr(estimate_writer, "read_sheet_grid", blocking)
    t0 = time.perf_counter()
    main._warm_sheet_cache()                       # the startup hook itself
    elapsed = time.perf_counter() - t0

    assert elapsed < RETURNED_FAST, (
        "the startup hook took %.1fs to return — it is waiting for the warm, so a deploy holds "
        "the container in startup while sixteen grids are built" % elapsed)
    assert started.wait(10), "the warm never started at all"
    release.set()                                  # let the thread finish if it has not


def test_the_hook_spawns_a_daemon_thread(monkeypatch):
    """Daemon, so a container stopping mid-warm is not held open by it. Asserted on the real
    Thread object the hook creates rather than on the source, because `daemon=True` is one
    keyword and losing it changes nothing visible until a shutdown hangs."""
    made = []
    real = threading.Thread

    def spy(*a, **k):
        t = real(*a, **k)
        made.append(t)
        return t

    monkeypatch.setattr(main.threading, "Thread", spy)
    monkeypatch.setattr(estimate_writer, "read_sheet_grid", lambda name, **kw: {"sheet": name})
    main._warm_sheet_cache()
    assert made, "the hook did not start a thread — the warm is running inline"
    assert made[0].daemon, "the warm thread is not a daemon; a stopping container waits for it"
    made[0].join(30)


# ── failure is survivable ────────────────────────────────────────────────────
def test_one_unbuildable_tab_does_not_stop_the_rest(monkeypatch):
    """A corrupt or renamed tab must cost that tab, not the other fifteen."""
    built = []
    names = estimate_writer.list_sheet_names()
    poison = names[5]

    def flaky(name, **kw):
        if name == poison:
            raise RuntimeError("boom")
        built.append(name)
        return {"sheet": name}

    monkeypatch.setattr(estimate_writer, "read_sheet_grid", flaky)
    main._warm_all_sheets()                            # must not raise
    assert sorted(built) == sorted(n for n in names if n != poison)


def test_an_unlistable_workbook_does_not_take_the_thread_down(monkeypatch):
    """Nothing joins this thread, so an escaping exception is printed by the interpreter and
    forgotten. The request path can still build any tab on demand — which is the whole reason
    swallowing this is the right call rather than a shrug."""
    def boom(**kw):
        raise OSError("template is gone")

    monkeypatch.setattr(estimate_writer, "list_sheet_names", boom)
    monkeypatch.setattr(estimate_writer, "read_sheet_grid",
                        lambda name, **kw: pytest.fail("built a grid with no tab list"))
    main._warm_all_sheets()
