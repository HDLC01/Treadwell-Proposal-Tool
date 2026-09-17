"""A reload puts you back on the tab you were on.

Hanz, on staging: "when I reload the page, why does it automatically land on assemblies? and not on
the tab that I have under items and assemblies also find any functionality that does that when I
refresh the page it should stay on the same page that I was on or editing".

Five screens answered that question the same way, and every one of them answered it wrong: the open
tab was a module variable with a literal default (`var view = "asm"`, `LAYOUT = LAYOUTS[0]`,
`var KEY = "not_viewed"`, `var at = 0`, `defaultBaseSheet()`), so F5 threw the estimator back to
whatever the code picked. The CRM board, the Follow-ups board, the Lead Inbox, the Proposals
Database and Analytics already remembered theirs in sessionStorage; these five did not remember
theirs at all.

WHERE THE STATE GOES decides whether the fix is right, so it is asserted rather than assumed:

  * THE URL. `frontend/js/tab-memo.js` writes `#tab=…` with `history.replaceState`. That survives a
    reload, it is what a bookmark keeps, it is what a colleague gets when the link is pasted into a
    message, and Back from another page lands on it. `pushState` would make Back walk through four
    tabs before it left the page, so its absence is pinned below.
  * NOT STORAGE. localStorage and sessionStorage THROW in a private window or with site data
    blocked, and neither travels with a link. tab-memo.js touches neither, which is pinned below —
    the point being that there is no storage access here that could need a try/catch.
  * NOT THE DRAFT BLOB. Every save PUTs the whole blob, so two tabs clobber each other, and which
    pane somebody is looking at is not project data. Also pinned below.

THE TWO THINGS THAT MUST NOT BREAK, both executed rather than read:

  * A REMEMBERED TAB THAT NO LONGER EXISTS FALLS BACK. A deleted worksheet copy, a markup layout
    the API stopped serving, a cadence email the portal retired, a pane name from some later shape
    of the page — each has to land on the default rather than on an empty pane or a failed load.
  * RESTORING ONE TAB DOES NOT LOAD THE OTHERS. The pages that fetch per pane still fetch per pane;
    restoring is the same single request a click would have made.

The behaviour lives in js/tab-memo-harness.js, which runs the shipped functions. What cannot be
executed is the `<script>` tag — the pages guard on `typeof window !== "undefined" &&
window.TWTabMemo` and degrade SILENTLY to their old behaviour without it — so the tags are read out
of the markup here. That split is the one library.js already takes for its own script ordering.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = REPO / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "tab-memo-harness.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def fn_body(src, decl):
    """One function's source, braces balanced.

    The two source-read assertions below are about WHERE a call sits inside one function, so the
    slice has to end where that function does. Bounding it on "the next declaration that looks
    like this one" is how a slice quietly grows to ten times the function and starts answering
    about somebody else's code."""
    start = src.index(decl)
    depth = 0
    for i in range(src.index("{", start), len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    raise AssertionError("unbalanced braces reading %s" % decl)

# Every page that now remembers its tab, and the script it remembers it from.
PAGES = {
    "library.html": "/js/library.js",
    "markup.html": "/js/markup.js",
    "followup-settings.html": "/js/followup-settings.js",
    "polish-estimate.html": "/js/polish-estimate.js",
    "estimate-review.html": "/js/estimate-review.js",
}


@pytest.fixture(scope="module")
def result():
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def memo_src():
    """tab-memo.js with its comments taken out.

    The comments are where the file EXPLAINS that it does not touch localStorage and does not use
    pushState, so a raw read would match its own reasoning and the two tests below would pass
    whatever the code did. This file has no `//` inside a string literal, which is the one case a
    stripper this simple gets wrong."""
    src = (FRONTEND / "js" / "tab-memo.js").read_text(encoding="utf-8")
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


# ── 1. where the state goes ──────────────────────────────────────────────────

def test_the_tab_lives_in_the_url_and_nowhere_else(memo_src):
    """The three homes this could have had, and why only one of them is right.

    Storage does not travel with a link and THROWS when site data is blocked. The draft blob is
    PUT whole on every save, so two tabs clobber each other — and which pane somebody is looking
    at is not project data. The fragment is neither, and it is also never sent to the server.

    Mutation: add `localStorage.setItem("tw_tab", hash)` to write()."""
    for forbidden in ("localStorage", "sessionStorage", "indexedDB", "TW.setState", "cookie"):
        assert forbidden not in memo_src, (
            "tab-memo.js reaches for %s — the tab belongs in the URL" % forbidden)
    assert "location.hash" in memo_src


def test_a_tab_click_replaces_the_history_entry_rather_than_pushing_one(memo_src):
    """pushState would make the Back button walk backwards through every tab somebody looked at
    before it left the page — on the estimate screen that is a strip of sixteen worksheets.

    Mutation: swap replaceState for pushState."""
    assert "replaceState" in memo_src
    assert "pushState" not in memo_src, "a tab click must not be a history entry"


@pytest.mark.parametrize("page,script", sorted(PAGES.items()))
def test_every_remembering_page_actually_loads_the_module(page, script):
    """The one thing no executed test can see. Each page guards on `typeof window !== "undefined"
    && window.TWTabMemo` so a missing module degrades to the old behaviour SILENTLY — no error, no
    console line, just a page that forgets its tab again.

    Order matters too: the page script reads window.TWTabMemo as it restores the open tab.

    Mutation: delete the <script src="/js/tab-memo.js"> tag from any one page."""
    html = (FRONTEND / page).read_text(encoding="utf-8")
    srcs = re.findall(r'<script[^>]*\bsrc="([^"]+)"', html)
    assert "/js/tab-memo.js" in srcs, "%s never loads the tab memory" % page
    assert srcs.index("/js/tab-memo.js") < srcs.index(script), (
        "%s loads tab-memo.js after its own page script" % page)


def test_the_module_survives_a_window_that_refuses_to_be_read(result):
    """A sandboxed frame throws SecurityError on location and on replaceState. A tab that switches
    without being remembered is still a tab that switched, so neither may reach the page.

    Mutation: drop the try/catch in read()."""
    assert result["hostile"] == {"read": "", "write": False}
    assert result["throwingWrite"] is False


def test_a_fragment_nobody_generated_is_read_without_throwing(result):
    """Hand-typed, truncated by a chat client, or written by an older shape of the page.
    `decodeURIComponent("%E0%A4%A")` is a URIError, and one bad pair must not cost the other its
    value.

    Mutation: remove the try/catch around decodeURIComponent."""
    assert result["parse"]["broken"] == {"tab": "", "wt": "gyp"}
    assert result["parse"]["bare"] == {}
    assert result["parse"]["empty"] == {}
    assert result["parse"]["noEquals"] == {"tab": ""}
    # A worksheet name has spaces and brackets in it, so the round trip has to be encoded.
    assert result["parse"]["encoded"] == {"sheet": "Gyp (GWorx SC190)"}
    assert result["stringify"]["spaces"] == "#sheet=Epoxy%20blank"


def test_an_empty_memory_is_no_fragment_rather_than_a_bare_hash(result):
    """"#" on its own is a scroll target, and it leaves a stub in the address bar saying nothing.

    Mutation: return "#" + parts.join("&") unconditionally."""
    assert result["stringify"]["nothing"] == ""
    assert result["stringify"]["dropsEmpty"] == "#tab=items"


def test_the_fragment_merges_and_does_not_rewrite_itself_for_nothing(result):
    """Two controls on one page write two keys, and the second must not wipe the first. The no-op
    matters as much: these renderers re-run after every unrelated edit, so a write that always
    replaced the entry would rewrite the URL on every repaint.

    And the draft id survives, because `?d=<uuid>` is what says which project this is.

    Mutation: make write() replace the fragment instead of merging it."""
    m = result["merge"]
    assert m["afterTwo"] == "#tab=defaults&wt=gyp"
    assert m["noopWrites"] == 0, "writing the same value again rewrote the URL"
    assert m["afterDrop"] == "#tab=defaults", "an emptied key was not removed"
    assert m["keptSearch"] == "?d=abc-123", "the draft id was dropped from the URL"
    assert m["keptPath"] == "/library.html"


# ── 2. Items and Assemblies — the screen that was reported ───────────────────

def test_items_and_assemblies_opens_on_the_tab_you_were_on(result):
    """The bug as reported: reloaded on Default Items & Assemblies, landed on Assemblies.

    Mutation: make restoreView() ignore the URL and call showView(view)."""
    r = result["libRestored"]
    assert r["view"] == "defaults"
    assert r["shown"] == ["defaults"], "another pane is on screen with it"
    assert r["selected"] == ["defaults"], "the tab strip disagrees with the pane"


def test_the_defaults_tab_comes_back_on_the_right_work_type(result):
    """Landing on the right tab and the wrong one of the five work types is the same bug one level
    down — the Defaults tab is five lists, not one.

    Mutation: drop the `wt` line from restoreView()."""
    r = result["libWorkType"]
    assert r["view"] == "defaults"
    assert r["wt"] == "gyp"
    assert r["strip"] == ["gyp"], "the work-type strip does not show which one is on"


def test_a_tab_or_a_work_type_that_no_longer_exists_falls_back(result):
    """A link from a later shape of this page, or one somebody edited by hand. Showing it anyway
    is an empty pane; showing nothing is worse.

    Mutation: return `wanted` from pick() regardless of `allowed`."""
    r = result["libUnknown"]
    assert r["view"] == "asm", "an unknown tab was honoured"
    assert r["wt"] == "polish", "an unknown work type was honoured"
    assert r["shown"] == ["asm"], "no pane is on screen"


def test_a_fresh_open_still_lands_on_assemblies_and_says_so(result):
    """Nothing remembered is the page's own default, unchanged — and the fragment is stamped, so
    the URL in the address bar is a link that opens what is on screen.

    Mutation: have restoreView() skip showView when the fragment is empty."""
    r = result["libFresh"]
    assert r["view"] == "asm"
    assert r["shown"] == ["asm"] and r["selected"] == ["asm"]
    assert r["hash"] == "#tab=asm"


def test_switching_a_tab_is_what_records_it(result):
    """Restoring is half the feature; the other half is that anything which switches tabs writes
    the fragment. showView is the funnel — the Defaults tab's Edit buttons switch tabs too, and a
    reload after one of those has to come back to the material it opened. That write is afterTab.

    afterWt is a SEPARATE write, inside document's own delegated click listener rather than
    inside a named function, so tab-memo-harness.js drives the REAL listener for it (onWtClick,
    the shipped callback lifted whole) instead of calling M.write() by hand. Calling M.write()
    ourselves would prove M.write() works, which four other tests already prove, and nothing
    about whether the page's own listener still calls it — which is exactly the mutation that
    left this scenario green before the harness drove the real listener.

    Mutation: remove the write from showView(), or the window.TWTabMemo.write() call from the
    work-type block of document's click listener."""
    assert result["libWrites"]["afterTab"] == "#tab=vendors"
    assert result["libWrites"]["afterWt"] == "#tab=vendors&wt=epoxy"


def test_restoreview_is_actually_invoked_when_the_page_loads():
    """restoreView() is a pure decision, proven directly above in every scenario — the harness
    lifts the function and calls it by hand, which proves it works and nothing about whether
    library.js's own module code still calls it once, on load. This is the bug as it actually
    shipped in the review that found it: the function stayed correct, the one statement that
    invoked it went missing, and every scenario above stayed green, because none of them can see
    a module-scope statement that was never there to call.

    Read out of the source for that reason — there is no return value a deleted top-level
    statement changes. Bounded at the next section comment so this cannot match some unrelated
    mention of restoreView() elsewhere in the file (there is one, in a comment), and checked for
    brace depth so a call moved INSIDE the tab-click listener just above it — which would run it
    only on a click, never on load — is caught too.

    Mutation: delete the top-level `restoreView();` statement below the tab-strip listeners."""
    src = (FRONTEND / "js" / "library.js").read_text(encoding="utf-8")
    restore_fn = fn_body(src, "function restoreView(")
    tail_start = src.index(restore_fn) + len(restore_fn)
    end = src.index("\n  // ── add from library", tail_start)
    wiring = src[tail_start:end]
    assert re.search(r"(^|\n)\s*restoreView\(\);", wiring), (
        "restoreView() is defined but nothing at module scope calls it")
    before = wiring[:wiring.index("restoreView();")]
    assert before.count("{") == before.count("}"), (
        "restoreView() is called from inside another block (e.g. the click listener), not "
        "unconditionally at module scope")


def test_without_the_module_the_page_behaves_exactly_as_it_did_before(result):
    """The degradation is deliberate and it is why the script tag is asserted separately: no throw,
    no half-applied state, just the old default.

    Mutation: drop the `window.TWTabMemo` half of the guard in restoreView()."""
    assert result["libNoModule"] == {"view": "asm", "hash": "#tab=defaults"}


# ── 3. the Markup page ───────────────────────────────────────────────────────

def test_the_markup_page_opens_on_the_layout_you_were_reading(result):
    """Its tabs come from /api/markup/rules, so the answer is checked against the set THIS load
    received. `combo` is refused by markup.py by name and can only arrive from an old link.

    Mutation: make openingLayout() return layouts[0] unconditionally."""
    assert result["markup"]["fresh"] == "epoxy"
    assert result["markup"]["remembered"] == "gyp"
    assert result["markup"]["refused"] == "epoxy", "a layout the API refuses was honoured"
    assert result["markup"]["noneAtAll"] == "", "an empty tab list invented one"
    assert result["markup"]["noModule"] == "epoxy"


def test_reload_actually_asks_openinglayout_for_the_tab_to_open():
    """openingLayout() is proven directly above against the tab set THIS load received — proven
    by calling it by hand, which says nothing about whether reload() still asks it. A neutered
    `LAYOUT = LAYOUTS[0]` decides the same thing as the real call on a fresh page (nothing is
    remembered yet) and leaves every scenario above green.

    Read out of the source because reload() is async and fetches — the same reason
    test_opening_a_drawer_is_what_records_it below reads openDetail's call site rather than
    running it.

    Mutation: replace `LAYOUT = openingLayout(LAYOUTS)` with `LAYOUT = LAYOUTS[0]`."""
    src = (FRONTEND / "js" / "markup.js").read_text(encoding="utf-8")
    body = fn_body(src, "async function reload(")
    assert "LAYOUT = openingLayout(LAYOUTS)" in body, (
        "reload() no longer asks openingLayout() for the tab to open")
    # GUARDED, not unconditional: a retry after a failed fetch must leave the tab somebody is
    # already standing on alone, which is what `LAYOUTS.indexOf(LAYOUT) < 0` is for.
    assert "if (LAYOUTS.indexOf(LAYOUT) < 0)" in body
    assert body.index("LAYOUT = openingLayout(LAYOUTS)") < body.index("LOADED = true")


def test_the_markup_tab_strip_click_is_what_records_it(result):
    """The opening-tab tests above prove openingLayout() works; neither runs the #mk-tabs click
    listener that is supposed to write the fragment on every switch, so a deleted write there —
    exactly the shape of bug already proven for library.js's work-type strip — would leave them
    all green. Driven through the REAL listener, lifted whole, not through window.TWTabMemo.write()
    called by hand.

    Mutation: remove the window.TWTabMemo.write() call from the #mk-tabs click listener."""
    assert result["markupWrites"]["afterTab"] == "#tab=gyp"
    assert result["markupWrites"]["layout"] == "gyp"


# ── 4. the cadence editor ────────────────────────────────────────────────────

def test_the_cadence_editor_opens_on_the_email_you_were_writing(result):
    """This is a page somebody sits on retyping a sentence and watching the preview redraw, so a
    reload costs more here than anywhere else. The keys come off the portal's own response, so an
    email it stopped serving falls back rather than opening an editor writing into a template
    nobody can see.

    Mutation: make openingEmail() return `fallback` unconditionally."""
    assert result["cadence"]["fresh"] == "not_viewed"
    assert result["cadence"]["remembered"] == "deposit_nudge"
    assert result["cadence"]["retired"] == "not_viewed"
    assert result["cadence"]["noModule"] == "not_viewed"


def test_load_actually_asks_openingemail_for_the_tab_to_open():
    """Same gap as markup's reload(): openingEmail() is proven directly above with the keys THIS
    response served, never through load()'s own call to it. A neutered `KEY = KEY` leaves KEY
    exactly where the guard above it already put it on a fresh load and every scenario above
    stays green.

    Read out of the source for the same reason as reload() — load() is async and fetches.

    Mutation: replace `KEY = openingEmail(Object.keys(LABELS), KEY)` with `KEY = KEY`."""
    src = (FRONTEND / "js" / "followup-settings.js").read_text(encoding="utf-8")
    body = fn_body(src, "async function load(")
    assert "KEY = openingEmail(Object.keys(LABELS), KEY)" in body, (
        "load() no longer asks openingEmail() for the tab to open")
    # AFTER the guard for a server that stopped serving the remembered default — otherwise a bad
    # link could land ahead of the fallback meant to catch a server that dropped `not_viewed`.
    assert body.index("if (!LABELS[KEY])") < body.index("KEY = openingEmail(")
    assert body.index("KEY = openingEmail(") < body.index("paintTabs()")


def test_the_cadence_tab_click_is_what_records_it(result):
    """Same gap as the markup tab strip: openingEmail() is proven above; nothing runs the #tabs
    click listener that is supposed to write the fragment on every switch. Driven through the
    REAL listener, lifted whole, not through window.TWTabMemo.write() called by hand.

    Mutation: remove the window.TWTabMemo.write() call from the #tabs click listener."""
    assert result["cadenceWrites"]["afterTab"] == "#tab=deposit_nudge"
    assert result["cadenceWrites"]["key"] == "deposit_nudge"


# ── 5. the Polish beta ───────────────────────────────────────────────────────

def test_the_polish_beta_opens_on_the_step_you_were_on(result):
    """BY KEY, NEVER BY NUMBER. "Step 2" means Labor today and something else the day a step is
    added or reordered, so a link sent last week would open the wrong screen — and a removed step
    would leave `at` pointing past the end of PANELS, which renders nothing at all.

    Mutation: make openingStep() read the fragment as an index."""
    assert result["polish"]["fresh"] == 0
    assert result["polish"]["remembered"] == 2, "#step=review did not open the Review step"
    assert result["polish"]["retired"] == 0, "a step that no longer exists was honoured"
    assert result["polish"]["numeric"] == 0, "a bare number was read as a step index"
    assert result["polish"]["noModule"] == 0


def test_the_polish_step_recorded_is_the_one_on_screen(result):
    """`go` clamps, so what the URL says has to be written after the clamp — otherwise a reload
    asks for a step the rail never showed. The draft id survives the write.

    Mutation: move the write above the clamp in go()."""
    w = result["polishWrites"]
    assert w["afterGo"] == "#step=review"
    # go(-1) from Review: the rail shows Takeoff, so that is what a reload has to come back to.
    assert w["afterClamp"] == "#step=takeoff", (
        "the step asked for was recorded rather than the step shown")
    assert w["at"] == 0
    assert w["keptDraft"] == "?d=proj-1"


def test_init_actually_asks_openingstep_for_the_step_to_open():
    """openingStep() is proven directly above against a fabricated step list; `go()` is proven
    directly above too. Neither runs init()'s own `at = openingStep(at)` — a neutered
    `at = at` would leave `at` at its own literal default (0) on every scenario above, which is
    indistinguishable from the correct answer on a fresh load.

    Read out of the source because init() fetches the whole library and the estimate. Position
    matters as much as presence: decided BEFORE paintRail()/renderPanel() paint, or the rail and
    the panel light two different steps on the same first paint.

    Mutation: replace `at = openingStep(at)` with `at = at`, or move it after paintRail()."""
    src = (FRONTEND / "js" / "polish-estimate.js").read_text(encoding="utf-8")
    body = fn_body(src, "async function init(")
    assert "at = openingStep(at)" in body, (
        "init() no longer asks openingStep() for the step to open")
    assert body.index("paintBid()") < body.index("at = openingStep(at)")
    assert body.index("at = openingStep(at)") < body.index("paintRail()")
    assert body.index("at = openingStep(at)") < body.index("renderPanel()")


# ── 6. the estimate sheet ────────────────────────────────────────────────────

def test_the_estimate_sheet_opens_on_the_worksheet_tab_you_were_on(result):
    """Including a COPY, which is a real tab with a copy id — an estimator on a priced option is
    exactly the person a reload costs most.

    Mutation: check the remembered id against the template sheet names instead of `tabs`."""
    assert result["sheet"]["fresh"] == "Epoxy"
    assert result["sheet"]["freshPolish"] == "Polish"
    assert result["sheet"]["remembered"] == "Leveling"
    assert result["sheet"]["copy"] == "Copy1"


def test_a_worksheet_tab_that_has_been_deleted_opens_the_base_bid(result):
    """`GET /api/sheet/Copy1` 404s once the copy is gone, and showSheet paints "Failed to load
    Copy1" over an empty grid. An old link must not be able to do that.

    Mutation: return the remembered sheet without checking `tabs`."""
    assert result["sheet"]["deletedCopy"] == "Epoxy"
    assert result["sheet"]["gypFallback"] == 'Gyp (USG 1-8")', (
        "a gyp bid with an unknown remembered tab did not fall back to the gyp base")
    assert result["sheet"]["noModule"] == "Epoxy"


def test_restoring_a_worksheet_tab_loads_that_one_and_not_the_others():
    """Four of the sixteen worksheets are deliberately not fetched at load
    (test_deferred_workbook_tabs). Restoring a remembered tab must not turn that saving into
    sixteen requests: showSheet fetches the single tab it opens, exactly as a click does.

    Read out of the source because the claim is about what init() does NOT do — there is no call
    to observe. `openingSheet` picks a name; nothing around it fetches.

    Mutation: make openingSheet() call loadDeferredIntoEngine for every tab."""
    src = (FRONTEND / "js" / "estimate-review.js").read_text(encoding="utf-8")
    body = src[src.index("function openingSheet()"):]
    body = body[:body.index("\n}") + 2]
    for forbidden in ("fetch(", "loadDeferredIntoEngine", "showSheet(", "HF.loadSheet"):
        assert forbidden not in body, (
            "openingSheet() does more than pick a name — it calls %s" % forbidden)


def test_the_opening_tab_is_still_decided_after_the_copies_are_rehydrated():
    """`openingSheet` asks `tabs`, and `tabs` is already filled by buildTabs() at step 1 of
    init() — before this file's own tab_copies loop (step 3b) ever runs. What step 3b actually
    gates is HyperFormula: it rehydrates each copy's CELLS into the engine, and asking before
    that finishes would pick a copy id `tabs` already names but HF cannot yet compute — showSheet
    would have nothing to paint.

    Mutation: move `const initialSheet = openingSheet()` above the tab_copies loop."""
    src = (FRONTEND / "js" / "estimate-review.js").read_text(encoding="utf-8")
    body = src[src.index("async function init()"):src.index("\nfunction renderTabs()")]
    assert body.index("tab_copies.filter") < body.index("openingSheet()"), (
        "the opening tab is decided before the copies are rehydrated into HyperFormula")
    assert body.index("openingSheet()") < body.index("showSheet(initialSheet)")


def test_showsheet_actually_writes_the_remembered_tab():
    """openingSheet() picks a name, proven above; showSheet() is what is supposed to record it —
    every way of opening a tab funnels through this one function, so its write is the ONLY write
    for the whole screen's sixteen-plus tabs. A deleted write here means the estimate sheet never
    remembers a reload again, on any tab, and nothing above can see it: the sheet-opening tests
    call `openingSheet()` directly, never `showSheet()`.

    Read out of the source because showSheet is async and fetches the sheet over the network —
    the same reason reload() and load() are read rather than run above.

    Mutation: remove the `window.TWTabMemo.write(window, { sheet: name })` call from showSheet()."""
    src = (FRONTEND / "js" / "estimate-review.js").read_text(encoding="utf-8")
    body = fn_body(src, "async function showSheet(")
    assert 'window.TWTabMemo.write(window, { sheet: name })' in body, (
        "showSheet() no longer records the tab it just opened")
    # Written from `name`, the argument just given, not from a module variable read back later —
    # and before the tab bar repaints, so a mutation reordering the two cannot pass by accident.
    assert body.index("activeSheet = name;") < body.index("window.TWTabMemo.write")
    assert body.index("window.TWTabMemo.write") < body.index("for (const btn of tabBar")


# ── 7. the CRM board's drawer ────────────────────────────────────────────────

def test_the_open_project_is_in_the_url_so_a_reload_comes_back_to_it(result):
    """The board's own tab, filters and sort already survive a reload; the drawer did not, so F5
    on a project you were reading put you back on the bare board.

    It reuses `?open=<pid>` — the deep link staff notification emails already send — rather than
    inventing a second way to say the same thing, which also makes the address bar a link a rep
    can paste to a colleague.

    Mutation: change `q.set("open", pid)` to `q.set("proposal", pid)`."""
    assert result["drawer"]["opened"]["search"] == "?open=p-42"
    assert result["drawer"]["opened"]["path"] == "/portal.html"
    assert result["drawer"]["keepsOthers"]["search"] == "?est=kyle%40wetreadwell.com&open=p-42", (
        "opening a drawer dropped the rest of the query string")


def test_opening_a_drawer_does_not_drop_an_existing_fragment(result):
    """Every scenario above starts from an empty `location.hash`, so a mutation dropping
    `+ location.hash` from markDrawerInUrl's replaceState call would leave every one of them
    green — the fragment it would have dropped was already empty. This is the one library.js,
    markup.js and estimate-review.js all rely on: whichever of their own tabs is open lives in
    that same fragment, and opening a project's drawer must not wipe it out from under them.

    Mutation: drop `+ location.hash` from the `next` string markDrawerInUrl builds."""
    assert result["drawer"]["keepsTheFragment"]["hash"] == "#sheet=Copy1", (
        "opening the drawer dropped the page's own tab fragment")
    assert result["drawer"]["keepsTheFragment"]["search"] == "?open=p-77"


def test_opening_a_drawer_is_what_records_it():
    """The wiring half, and the only claim in this file read out of the source rather than run.

    openDetail is async and its first act is a portal fetch, so running it is drawer-render-
    harness.js's job, not this one's — and that harness binds no history, so what it proves is
    that openDetail still RUNS with the call in it, not what the call did. What can go wrong here
    is a wiring mistake (the call deleted, or moved below one of the three early returns for a
    not-sent row, a portal-unknown row or a cached render), and position in the source is exactly
    what a wiring mistake shows up as.

    It has to sit ABOVE the early returns, and after the ?sec deep-link read that sets
    DEEPLINK_USED — otherwise load()'s own `?open` read would re-open the drawer on every poll.

    Mutation: move the markDrawerInUrl(pid) call below `if (row && row.not_sent)`."""
    src = (FRONTEND / "js" / "portal.js").read_text(encoding="utf-8")
    body = fn_body(src, "async function openDetail(")
    call = body.index("markDrawerInUrl(pid)")
    assert body.index("DEEPLINK_USED = true") < call, (
        "the URL is stamped before the ?sec deep link is consumed")
    assert call < body.index("row.not_sent"), (
        "a not-sent project's drawer is opened without the URL recording it")
    assert call < body.index("row.portal_unknown"), (
        "a drawer opened during a portal outage is not recorded")


def test_closing_the_drawer_takes_it_back_out(result):
    """Otherwise a reload after closing one reopens it, and load()'s own 25s poll has an `?open`
    to find for the rest of the session.

    Driven through the REAL closeDrawer rather than through the helper, because this one IS
    runnable: it clears three module variables, drops a class and asks syncScrim. Calling the
    helper by hand would pass whatever closeDrawer did.

    Mutation: drop the markDrawerInUrl(null) call from closeDrawer()."""
    assert result["drawerClose"]["search"] == "", (
        "closing the drawer left ?open in the URL, so a reload reopens it")
    # The three things closeDrawer has always done, so this scenario cannot be passing because it
    # ran something that is no longer the close path.
    assert result["drawerClose"]["pid"] is None
    assert result["drawerClose"]["sec"] is None
    assert result["drawerClose"]["sig"] == ""
    assert result["drawer"]["closedTwice"]["writes"] == 0, (
        "closing a drawer that was never in the URL still rewrote it")


def test_which_drawer_tab_is_open_is_deliberately_not_remembered(result):
    """The five tabs inside the drawer are routed by what needs a human — unread first, then a
    submitted deposit, then the conversation (defaultSection). Hanz asked for that routing, and
    remembering the last tab would permanently defeat it, because the board is one session a rep
    keeps open all day. So `sec` is never WRITTEN here — and a deep link that carries one is left
    alone, because a notification asking for a tab is a different thing from a memory.

    Mutation: add `sec` to what markDrawerInUrl writes."""
    src = (FRONTEND / "js" / "portal.js").read_text(encoding="utf-8")
    body = fn_body(src, "function markDrawerInUrl(")
    assert '"sec"' not in body and "'sec'" not in body, (
        "the drawer now records which tab was open, which defeats defaultSection's routing")
    assert result["drawer"]["leavesSecAlone"]["search"] == "?open=p-42&sec=chat"
