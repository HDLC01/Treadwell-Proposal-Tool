"""The order the estimate screen boots in, on the two axes where order is the whole feature.

WHY THIS FILE EXISTS. Both halves of this are ordering facts that no amount of running the page
locally would surface: on a fast LAN a serialised round trip is invisible, and a script that
happens to arrive in time looks identical to one that is guaranteed to.

── 1. THE PARSER-BLOCKING SCRIPTS ──
`estimate-review.html` and `info-sheet.html` load HyperFormula from a CDN. It sat in the <head>
as a classic script, so the parser stopped there and nothing painted until the whole 153 KB
(brotli; 705 KB unpacked) engine had arrived. Measured on a throttled cold load, Fast 4G + 4x
CPU: first contentful paint 994ms -> 840ms and domInteractive 1447ms -> 253ms on estimate-review,
982ms -> 808ms and 1276ms -> 263ms on info-sheet.

`defer` fixes that, but ONLY if every external script on the page has it. Deferred scripts run in
document order after parsing; classic ones run where they sit. Leave one of the bottom-of-body
tags classic and it runs BEFORE the engine, which means `xl-excel-rounding.js` never gets to
replace ROUNDUP and CEILING -- and that file's own header records what that costs: 98 cells wrong
across six audited estimates, Epoxy!D88 reading $15,219 where the workbook says $15,213. Always
upward. So "every tag, and in this order" is asserted rather than assumed.

── 2. THE TOKEN VERSUS THE PROFILE ──
`TWAuth.ready` settles after /api/me. /api/me is a round trip made AFTER the bearer token it
authenticates with is already in hand, so a page that only wants to start FETCHING waits out a
whole extra RTT -- ~250ms from Manila -- for a profile it will not read. `TWAuth.tokenReady` is
the earlier moment and nothing more.

The two things that must stay true of it, and are checked below: it resolves AFTER the
account-domain gate (so a non-Treadwell session never hands a token to a prefetch) and BEFORE
/api/me; and nothing in the page's init() moved out from behind `await TWAuth.ready` except the
two fetches. That second one is what keeps `showRefusal` working -- it deliberately never settles
`ready`, which is how a denied member's page module is stopped dead, and a prefetch that painted
would paint over the refusal card.
"""
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = REPO / "frontend"

SCRIPT_RE = re.compile(r"<script\b([^>]*)\bsrc=\"([^\"]+)\"", re.I)


def scripts(page):
    """(src, is_deferred) for every external script on a page, in document order."""
    html = (FRONTEND / page).read_text(encoding="utf-8")
    return [(m.group(2), " defer" in (" " + m.group(1).strip() + " "))
            for m in SCRIPT_RE.finditer(html)]


# ── 1. the parser-blocking scripts ───────────────────────────────────────────

@pytest.mark.parametrize("page", ["estimate-review.html", "info-sheet.html"])
def test_every_external_script_is_deferred(page):
    """One classic tag among deferred ones does not merely lose the speed-up — it REORDERS the
    page, because a classic script runs where it sits and a deferred one waits for the parser."""
    classic = [src for src, deferred in scripts(page) if not deferred]
    assert classic == [], "%s still has parser-blocking scripts: %s" % (page, classic)


@pytest.mark.parametrize("page,expected", [
    ("estimate-review.html", [
        "hyperformula", "/js/xl-excel-rounding.js", "supabase-js", "/js/icons.js",
        "/auth.js", "/shared.js", "/js/tab-memo.js", "/js/crm-core.js",
        "/js/estimate-review.js",
    ]),
    ("info-sheet.html", [
        "hyperformula", "/js/xl-excel-rounding.js", "supabase-js", "/shared.js",
        "/js/crm-core.js", "/js/icons.js", "/auth.js", "/js/xl-core.js", "/js/info-sheet.js",
    ]),
])
def test_the_script_order_is_the_one_every_file_assumes(page, expected):
    """`defer` preserves document order, so document order IS the contract now.

    xl-excel-rounding must follow HyperFormula (it calls `HyperFormula.registerFunctionPlugin`
    at load and refuses loudly if the global is absent) and must precede anything that builds an
    engine, because registration is global and one-time. supabase-js must precede auth.js, which
    mints no token without it. crm-core must precede the page's own script, which reads
    window.TWCrm as it runs.
    """
    got = [src for src, _ in scripts(page)]
    assert len(got) == len(expected), (page, got)
    for actual, want in zip(got, expected):
        assert want in actual, "%s: expected %r here, found %r" % (page, want, actual)


@pytest.mark.parametrize("page", ["estimate-review.html", "info-sheet.html"])
def test_the_cdn_connection_is_still_warmed_before_the_engine_tag(page):
    """`defer` moves EXECUTION, not discovery: the preload scanner still finds the tag in the
    <head> and starts the fetch there. The preconnect is what makes that fetch cheap, and it has
    to come first to be worth anything."""
    html = (FRONTEND / page).read_text(encoding="utf-8")
    pre = html.index('rel="preconnect" href="https://cdn.jsdelivr.net"')
    tag = html.index("cdn.jsdelivr.net/npm/hyperformula")
    assert pre < tag, page


# ── 2. the token versus the profile ──────────────────────────────────────────

@pytest.fixture(scope="module")
def auth_src():
    return (FRONTEND / "auth.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def er_init():
    src = (FRONTEND / "js" / "estimate-review.js").read_text(encoding="utf-8")
    return src[src.index("async function init()"):src.index("\nfunction renderTabs()")]


def test_the_token_gate_opens_after_the_domain_check_and_before_the_profile(auth_src):
    """Both sides matter. Resolve it before the @wetreadwell.com check and a personal Google
    account's token would be handed to a prefetch that then fires against the API; resolve it
    after /api/me and it is just `ready` with extra steps."""
    body = auth_src[auth_src.index("  async function init() {"):auth_src.index("  // ── Login page ──")]
    gate = body.index('LOGIN_PAGE + "?denied=1"')
    opened = body.index("_tokenIsReady(window.__TW_TOKEN)")
    me = body.index('fetch(apiBase() + "/api/me"')
    assert gate < opened < me, (
        "the token gate moved: domain-gate=%d opened=%d /api/me=%d" % (gate, opened, me))


def test_the_refusal_still_waits_for_the_profile(auth_src):
    """showRefusal is reached from the /api/me answer and never settles `ready` — that is the
    mechanism that stops a denied member's page module, not an oversight. Nothing about the
    earlier token gate may move it."""
    body = auth_src[auth_src.index("  async function init() {"):auth_src.index("  // ── Login page ──")]
    me = body.index('fetch(apiBase() + "/api/me"')
    refuse = body.index("return showRefusal(owner)")
    sidebar = body.index("renderSidebar();")
    assert me < refuse < sidebar, (
        "the refusal no longer sits between /api/me and the sidebar: %d %d %d"
        % (me, refuse, sidebar))
    assert "await new Promise(function () {});" in auth_src, (
        "showRefusal no longer parks forever — `ready` would settle on a refused page and every "
        "page module would boot against the emptied document")


def test_the_two_reads_are_fired_before_the_page_waits_on_the_profile(er_init):
    """The whole of the saving. Either call left below the await is a call that starts a full
    round trip after /api/me instead of alongside it."""
    sheets = er_init.index('bootFetch("/api/sheets")')
    names = er_init.index('bootFetch("/api/named-expressions")')
    wait = er_init.index("await window.TWAuth.ready")
    assert sheets < wait and names < wait, (
        "a prefetch slipped below the profile wait: sheets=%d names=%d wait=%d"
        % (sheets, names, wait))


def test_the_named_expressions_no_longer_queue_behind_the_sheet_list(er_init):
    """They depend on nothing /api/sheets returns. Fetching them at step 2b — after
    `await _sheetsReady` — is a second full round trip serialised behind the first for no reason.
    Only REGISTERING them needs the sheet ids, and that still happens at 2b."""
    assert '"/api/named-expressions"' not in er_init[er_init.index("HF.init(sheets)"):], (
        "/api/named-expressions is being fetched again after the sheet list lands")
    fired = er_init.index('bootFetch("/api/named-expressions")')
    consumed = er_init.index("await _namedReady")
    engine = er_init.index("HF.init(sheets)")
    assert fired < engine < consumed, (
        "registration must still happen after HF.init: fired=%d engine=%d consumed=%d"
        % (fired, engine, consumed))


def test_nothing_that_paints_or_saves_moved_above_the_profile_wait(er_init):
    """The safety half. `await TWAuth.ready` still gates the DOM, the state and the engine, so a
    refused page runs none of it — the prefetches cost two GETs the server answers or refuses on
    its own, and nothing reaches the document showRefusal just emptied."""
    above = er_init[:er_init.index("await window.TWAuth.ready")]
    for forbidden in ("buildTabs(", "renderTabs(", "HF.init(", "showSheet(", "TW.setState(",
                      "persistTabState(", "sheetGrid.textContent"):
        assert forbidden not in above, (
            "%r now runs before the profile is known, so it would also run on a refused page"
            % forbidden)


def test_a_prefetch_waits_for_the_token_and_parks_its_own_rejection(er_init):
    """Two separate hazards in four lines of helper.

    Without the tokenReady await the fetch can fire with no Authorization header at all — which
    is the /api/default-notes 401 race (#124) exactly, and it fails silently. Without the parked
    handler, a prefetch nobody gets to await (init() returns early on a sheet-list failure) is an
    unhandled rejection in the console of a page that is otherwise fine.
    """
    src = (FRONTEND / "js" / "estimate-review.js").read_text(encoding="utf-8")
    body = src[src.index("function bootFetch(path) {"):]
    body = body[:body.index("\n}\n")]
    token = body.index("await window.TWAuth.tokenReady")
    fetched = body.index("await fetch(path")
    assert token < fetched, "bootFetch fires before the token exists"
    assert "p.catch(() => {});" in src[src.index("function bootFetch(path) {"):
                                       src.index("const DEFERRABLE_TABS")], (
        "bootFetch no longer parks a handler on the prefetch")
