"""The per-role sidebar policy STORE — nothing wired to a route yet (see test_nav_gate.py for that).

Hanz, 2026-08-19, on the Admin page's read-only "What each role can see" matrix: "I cant toggle
these on and off?" He chose real blocking over cosmetic hiding, and has NOT chosen which tabs to
restrict — so this has to go out doing nothing at all, and the first section below is the test that
says so. It is the thing to read first if this ever needs debugging on a live box.

Two other claims, both of which cost somebody an outage if taken the wrong way round:

  * FAIL OPEN. An unreadable, half-written or hand-mangled policy means everybody gets everything.
    Three accounts use this tool; a lockout is an outage the affected person cannot fix, and the
    data is still behind the _require_admin gates it was always behind.
  * ONLY SINGLE-CALLER PREFIXES MAY BE OWNED. Five of the fourteen tabs read routes that other
    pages read too, so gating "their" API would blank a page nobody restricted. That list is
    measured from frontend/ and re-asserted here by name, because nothing else re-measures it.
"""
import json
import pathlib
import re

import pytest

import nav_access


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """A policy file per test. The real one lives on the data volume."""
    monkeypatch.setattr(nav_access, "_FILE", tmp_path / "nav_access.json")
    monkeypatch.setattr(nav_access, "_DATA_DIR", tmp_path)


# ── the no-op promise ─────────────────────────────────────────────────────────
def test_with_no_policy_file_nothing_is_denied_to_anybody():
    """THE test. Shipping this before Hanz has picked any tabs must not change one response."""
    assert not nav_access._FILE.exists()
    assert nav_access.get() == {"version": 1, "deny": {}, "updated_at": None, "updated_by": None}
    for role in nav_access.ROLES:
        assert nav_access.denied_paths(role) == []
        assert nav_access.denied_pages(role) == []
        assert nav_access.denied_api_prefixes(role) == []
        # Every prefix any tab owns, checked against the policy that does not exist.
        for tab in nav_access.TABS.values():
            for prefix in tab["api"]:
                probe = prefix + "x" if prefix.endswith("/") else prefix
                assert nav_access.is_api_denied(role, probe) is False
        for href in nav_access.TABS:
            assert nav_access.page_denied(role, href) is None


def test_an_absent_role_an_absent_path_and_an_empty_file_all_deny_nothing():
    nav_access._FILE.write_text("{}", encoding="utf-8")
    assert nav_access.get()["deny"] == {}
    nav_access._FILE.write_text(json.dumps({"version": 1, "deny": {}}), encoding="utf-8")
    assert nav_access.denied_paths("user") == []
    nav_access.save({"user": ["/leads.html"]}, "kyle@wetreadwell.com")
    assert nav_access.denied_paths("admin") == [], "a role the file never mentions loses nothing"
    assert nav_access.denied_paths("nobody") == []
    assert nav_access.page_denied("user", "/crm.html") is None


def test_a_garbled_file_denies_nothing():
    """FAIL OPEN. A half-written or hand-mangled file must cost nothing, because the alternative is
    a company-wide lockout that only somebody with SSH can undo."""
    for junk in ('{not json', '["a", "list"]', '', 'null', '{"deny": "everything"}',
                 '{"deny": {"user": "/leads.html"}}', '{"deny": {"user": null}}',
                 '{"deny": {"user": [17, {}, null]}}'):
        nav_access._FILE.write_text(junk, encoding="utf-8")
        assert nav_access.get()["deny"] == {}, junk
        assert nav_access.denied_paths("user") == [], junk


def test_a_file_naming_a_page_that_no_longer_exists_denies_nothing():
    """A policy written before a page was deleted must read as "nothing to deny" — not as an
    exception on the way to rendering a menu."""
    nav_access._FILE.write_text(json.dumps({"deny": {"user": ["/gone.html", "/leads.html"]}}),
                               encoding="utf-8")
    assert nav_access.denied_paths("user") == ["/leads.html"]


# ── the round trip ────────────────────────────────────────────────────────────
def test_a_policy_round_trips_with_who_and_when():
    out = nav_access.save({"user": ["/leads.html", "/history.html"]}, "kyle@wetreadwell.com")
    assert out["deny"]["user"] == ["/leads.html", "/history.html"]
    assert out["updated_by"] == "kyle@wetreadwell.com"
    assert out["updated_at"], "a policy with no timestamp cannot be explained later"
    again = nav_access.get()
    assert again["deny"] == {"user": ["/leads.html", "/history.html"]}
    assert again["updated_by"] == "kyle@wetreadwell.com"


def test_saving_an_empty_map_is_the_way_back_to_nothing_denied():
    nav_access.save({"user": ["/leads.html"]}, "k@x.com")
    nav_access.save({}, "k@x.com")
    assert nav_access.get()["deny"] == {}
    assert nav_access.denied_paths("user") == []


def test_a_failed_write_is_raised_not_swallowed():
    """A policy that "saved" into one container's memory is worse than one that refused."""
    def boom(*a, **k):
        raise OSError("read-only volume")

    orig = type(nav_access._FILE).write_text
    try:
        type(nav_access._FILE).write_text = boom
        with pytest.raises(nav_access.NavAccessWriteError):
            nav_access.save({"user": ["/leads.html"]}, "k@x.com")
    finally:
        type(nav_access._FILE).write_text = orig
    assert nav_access.denied_paths("user") == [], "a failed save must not appear to have taken effect"


def test_the_write_is_atomic(monkeypatch):
    """A write that dies halfway must leave the PREVIOUS policy intact. Written as the failure and
    not as "a .tmp file is used": a direct write truncates the real file first, so a full disk turns
    the policy into a corrupt file — which reads as nothing denied, i.e. it silently UNDOES a
    restriction somebody set on purpose."""
    nav_access.save({"user": ["/leads.html"]}, "kyle@wetreadwell.com")

    def half_then_die(self, data, encoding=None, **kw):
        self.write_bytes(b'{"version": 1, "deny": {"user": ["/hist')
        raise OSError("disk full")

    # A context, not monkeypatch.undo(): undo() reverts every patch on this test item, including the
    # autouse fixture's redirect of _FILE — which would send the assertion below to the real volume.
    with monkeypatch.context() as m:
        m.setattr(type(nav_access._FILE), "write_text", half_then_die)
        with pytest.raises(nav_access.NavAccessWriteError):
            nav_access.save({"user": ["/history.html"]}, "k@x.com")
    assert nav_access.denied_paths("user") == ["/leads.html"], (
        "a failed write destroyed the policy that was already stored")


# ── what can never be denied ──────────────────────────────────────────────────
def test_the_locked_pages_are_stripped_ON_WRITE_so_they_never_reach_the_file():
    """/admin.html is where this policy is edited and /portal.html is where signing in lands.

    ONE normaliser (sanitize) serves both directions, so this and the read-side test below are the
    same code checked from both ends — asserted against the BYTES ON DISK here, so a policy cannot
    "have been saved" carrying something that only the read path would have dropped."""
    nav_access.save({"user": ["/admin.html", "/portal.html", "/leads.html"]}, "k@x.com")
    raw = json.loads(nav_access._FILE.read_text(encoding="utf-8"))
    assert raw["deny"] == {"user": ["/leads.html"]}, raw


def test_the_locked_pages_are_stripped_ON_READ_so_a_hand_edited_file_cannot_lock_anybody_out():
    """The other end of the same guarantee, and the end that matters on a live box: the file sits on
    a Docker volume, is editable with a text editor, and the middleware reads it — not the browser.
    The API refusing a locked page (test_nav_gate.py) is a courtesy on top of this, not the guard."""
    nav_access._FILE.write_text(
        json.dumps({"deny": {"user": ["/admin.html", "/portal.html", "/trash.html"]}}),
        encoding="utf-8")
    assert nav_access.denied_paths("user") == ["/trash.html"]
    assert nav_access.page_denied("user", "/admin.html") is None
    assert nav_access.page_denied("user", "/portal.html") is None


def test_the_super_admin_is_stripped_ON_WRITE():
    """His role is bootstrapped from SUPER_ADMIN_EMAIL and cannot be granted from the UI — it is
    the account that always has a way in. A policy that can deny it can lock the owner out."""
    nav_access.save({"super_admin": ["/leads.html"], "user": ["/leads.html"]}, "k@x.com")
    raw = json.loads(nav_access._FILE.read_text(encoding="utf-8"))
    assert "super_admin" not in raw["deny"], raw


def test_the_super_admin_is_stripped_ON_READ():
    nav_access._FILE.write_text(json.dumps({"deny": {"super_admin": ["/leads.html"]}}),
                               encoding="utf-8")
    assert nav_access.denied_paths("super_admin") == []
    assert nav_access.is_api_denied("super_admin", "/api/leads") is False


def test_a_locked_page_still_appears_in_the_capability_table_flagged():
    """The Admin page needs the row in order to render it permanently on and not clickable. Dropping
    it from the table would make the switch missing rather than obviously fixed."""
    table = {row["href"]: row for row in nav_access.capability_table()}
    for href in nav_access.LOCKED:
        assert table[href]["locked"] is True
    assert table["/leads.html"]["locked"] is False


def test_case_and_a_missing_slash_do_not_smuggle_a_locked_page_through():
    """The strip compares normalised hrefs, so "ADMIN.HTML" is the same page as "/admin.html"."""
    nav_access.save({"user": ["ADMIN.html", "/Portal.HTML"]}, "k@x.com")
    assert nav_access.get()["deny"] == {}


# ── prefix matching ───────────────────────────────────────────────────────────
def test_a_trailing_slash_matches_children_only():
    """THE analytics case. /api/analytics/ owns export and pull-window; the BARE /api/analytics is
    also the Bid Calendar's data source, so a startswith() on a slashless prefix would blank a page
    nobody restricted."""
    assert nav_access.prefix_matches("/api/analytics/export", "/api/analytics/") is True
    assert nav_access.prefix_matches("/api/analytics/pull-window", "/api/analytics/") is True
    assert nav_access.prefix_matches("/api/analytics", "/api/analytics/") is False


def test_a_slashless_prefix_is_an_exact_match_only():
    """/api/history has no children today. If it grows one, that route is not silently gated by a
    prefix written when it did not exist."""
    assert nav_access.prefix_matches("/api/history", "/api/history") is True
    assert nav_access.prefix_matches("/api/history/detail", "/api/history") is False
    assert nav_access.prefix_matches("/api/historyx", "/api/history") is False


def test_the_lead_inbox_owns_the_bare_route_and_its_children():
    nav_access.save({"user": ["/leads.html"]}, "k@x.com")
    for path in ("/api/leads", "/api/leads/abc/body", "/api/leads/abc/status"):
        assert nav_access.is_api_denied("user", path) is True, path
    assert nav_access.is_api_denied("user", "/api/leadsomething") is False


def test_denying_the_bid_calendar_leaves_the_analytics_payload_alone():
    nav_access.save({"user": ["/calendar.html"]}, "k@x.com")
    assert nav_access.is_api_denied("user", "/api/calendar/events") is True
    assert nav_access.is_api_denied("user", "/api/calendar/events/e1") is True
    assert nav_access.is_api_denied("user", "/api/analytics") is False, (
        "the calendar and the Analytics page read the same payload")


# ── the shared prefixes are never gated ───────────────────────────────────────
# Measured by grepping frontend/ for every /api/ string: each of these is read by more than one
# sidebar tab, or by the wizard, which has no sidebar row. Gating any of them breaks a page nobody
# restricted, so no tab may claim one.
SHARED = ["/api/analytics", "/api/library/items", "/api/library/assemblies",
          "/api/portal/pipeline", "/api/notifications", "/api/notifications/seen",
          "/api/drafts", "/api/draft/abc", "/api/estimators", "/api/generate",
          "/api/file/tok", "/api/portal/notify-recipients", "/api/portal/notify-overrides-all",
          "/api/me", "/api/price", "/api/reference/counties", "/api/dropbox/folders"]


def test_no_tab_claims_a_shared_prefix():
    """The claim is about the TABLE, not about one policy: if a shared prefix is ever added to a tab,
    this fails whether or not anybody has denied that tab yet."""
    for href, tab in nav_access.TABS.items():
        for prefix in tab["api"]:
            for shared in SHARED:
                assert not nav_access.prefix_matches(shared, prefix), (
                    "%s claims %r, which also matches the shared route %s"
                    % (href, prefix, shared))


def test_denying_every_single_tab_still_leaves_every_shared_route_open():
    """The worst case somebody can build in the UI: every switch off for members. The wizard must
    still make proposals and the bell must still ring."""
    nav_access.save({"user": list(nav_access.TABS)}, "k@x.com")
    for shared in SHARED:
        assert nav_access.is_api_denied("user", shared) is False, shared


def test_the_page_refusal_only_tabs_own_no_api():
    """Named individually. These read only routes that other pages read too, so switching them off
    hides the tab and blocks the page and leaves the data reachable — and the Admin page says so on
    screen. If one of them ever gains a private route, this fails and the wording changes with it."""
    assert [h for h, t in nav_access.TABS.items() if not t["api"]] == [
        "/portal.html", "/polish-intake.html", "/projects.html", "/library.html",
        "/notifications.html", "/admin.html"], (
        "the set of tabs that own no private endpoint has changed; the Admin page's on-screen "
        "wording about them is derived from this and needs re-reading")


def test_the_polish_beta_row_covers_both_of_its_pages():
    """Step 2 is opened directly from the Estimate Review toolbar and from step 1's own tab strip,
    neither of which is this sidebar row — so denying the row has to cover both pages or the door is
    simply the other one."""
    nav_access.save({"user": ["/polish-intake.html"]}, "k@x.com")
    assert nav_access.page_denied("user", "/polish-intake.html") == "/polish-intake.html"
    assert nav_access.page_denied("user", "/polish-estimate.html") == "/polish-intake.html"


def test_the_two_doors_into_polish_step_two_are_still_the_two_this_assumes():
    """The reason that row owns two pages. Executed nowhere else, so it is read out of the source:
    if a third door appears, the second page is reachable past a denial and this says so."""
    frontend = pathlib.Path(__file__).resolve().parents[2] / "frontend"
    doors = sorted(p.name for p in list(frontend.glob("*.html")) + list((frontend / "js").glob("*.js"))
                   if p.name not in ("auth.js", "polish-estimate.js", "polish-sandbox.js")
                   and re.search(r'["\']/polish-estimate\.html', p.read_text(encoding="utf-8")))
    assert doors == ["estimate-review.html", "estimate-review.js", "polish-intake.html",
                     "polish-intake.js"], doors


def test_the_pages_with_no_sidebar_row_are_never_denied():
    """The wizard and the three unlinked pages. Every proposal goes through the wizard, so a policy
    that could reach it would stop the tool doing its job."""
    nav_access.save({"user": list(nav_access.TABS)}, "k@x.com")
    denied = nav_access.denied_pages("user")
    for page in nav_access.ALWAYS_OPEN_PAGES:
        assert page not in denied, page
        assert nav_access.page_denied("user", page) is None, page


FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"


def _sidebar_hrefs():
    """Every href the sidebar draws a row for, read out of auth.js's navItem() calls."""
    return set(re.findall(r'navItem\("([^"]+)"', (FRONTEND / "auth.js").read_text(encoding="utf-8")))


def test_every_tab_in_the_table_is_a_real_page_and_every_sidebar_href_is_in_the_table():
    """The table is keyed on href because href is the only identity the Admin matrix has — auth.js's
    navMatrix keys its rows byHref and admin.js stamps data-href. A typo there is a switch that
    silently governs nothing.

    Compared against the NAV-VISIBLE tabs, not against all of TABS: a tab may be governed without
    being drawn (NO_SIDEBAR_TABS), and the test below is what stops that becoming an accident."""
    for href, tab in nav_access.TABS.items():
        for page in tab["pages"]:
            assert (FRONTEND / page.lstrip("/")).is_file(), "%s claims %s" % (href, page)
    hrefs = _sidebar_hrefs()
    visible = set(nav_access.TABS) - set(nav_access.NO_SIDEBAR_TABS)
    assert hrefs == visible, (
        "the sidebar and the capability table disagree: only in sidebar %s / only in table %s"
        % (sorted(hrefs - visible), sorted(visible - hrefs)))


def test_every_tab_is_either_in_the_sidebar_or_DELIBERATELY_hidden():
    """A tab cannot fall out of the sidebar by accident and take its gate with it.

    This is the guard the 2026-08-20 Info Sheet move needed. The test above used to compare the
    sidebar against ALL of TABS, so the cheap way to keep it green when a row is deleted is to
    delete the tab's TABS entry — which removes the per-role gate on its API and makes the page
    undeniable. Nothing failed when that happened, because the only assertion was that the two lists
    matched, and deleting from both matches.

    So the pair is asserted in both directions: a tab out of the sidebar has to be named in
    NO_SIDEBAR_TABS on purpose, and NO_SIDEBAR_TABS may only name a real tab that really has no
    row."""
    hrefs = _sidebar_hrefs()
    for href in nav_access.TABS:
        assert href in hrefs or href in nav_access.NO_SIDEBAR_TABS, (
            "%s is in the capability table but has no sidebar row and is not in NO_SIDEBAR_TABS. "
            "Either give it a row back or name it there — do NOT delete its table entry, which is "
            "what gates %s." % (href, nav_access.TABS[href]["api"] or "its page"))
    for href in nav_access.NO_SIDEBAR_TABS:
        assert href in nav_access.TABS, (
            "%s is listed as a hidden TAB but is not a tab; nothing gates it" % href)
        assert href not in hrefs, (
            "%s is back in the sidebar, so it should come out of NO_SIDEBAR_TABS" % href)
        assert href not in nav_access.LOCKED, (
            "%s is both hidden and undeniable, which makes its entry decoration" % href)


def test_the_hidden_set_is_the_same_list_auth_js_keeps():
    """auth.js has to name these too — it has no navItem() call to reflect, so navMatrix appends
    their rows from its own NO_SIDEBAR_TABS list, which is what keeps the Admin page's switch on
    screen. Two copies of one list is how one of them rots, so they are diffed here.

    The consequence of drift is specific: a tab in this module and not in auth.js is a tab that can
    be denied with no switch to see or undo it, and the recovery is `rm` on the volume."""
    src = (FRONTEND / "auth.js").read_text(encoding="utf-8")
    block = src[src.index("const NO_SIDEBAR_TABS = ["):]
    block = block[:block.index("];")]
    assert set(re.findall(r'href:\s*"([^"]+)"', block)) == set(nav_access.NO_SIDEBAR_TABS), (
        "auth.js's NO_SIDEBAR_TABS and nav_access.NO_SIDEBAR_TABS have drifted: auth.js has %s, "
        "this module has %s" % (block, sorted(nav_access.NO_SIDEBAR_TABS)))


def test_a_hidden_tab_STILL_GATES_ITS_API_which_is_why_its_entry_survived_the_move():
    """THE test for NO_SIDEBAR_TABS, and the loudest claim in this file after the no-op promise.

    Info Sheet left the sidebar on 2026-08-20 for the project drawer's Proposal tab. Its capability
    entry did NOT leave with it, and this is what that buys: a role denied the Info Sheet tab is
    still refused /api/info-sheet/* by the middleware and still gets a refusal card instead of the
    page — even though there is no menu row anywhere to hide.

    The reversal to watch fail: dropping "/info-sheet.html" from TABS. It keeps the sidebar/table
    comparison above green and turns every assertion here into "nothing is denied", which is a page
    with no permission at all and an API anybody can read by URL."""
    hidden = "/info-sheet.html"
    assert hidden in nav_access.NO_SIDEBAR_TABS
    assert hidden not in _sidebar_hrefs(), "this test is about a tab with NO sidebar row"
    assert hidden in nav_access.TABS, "the tab lost its entry, so nothing below can gate anything"

    nav_access.save({"user": [hidden]}, "kyle@wetreadwell.com")
    assert nav_access.denied_paths("user") == [hidden], (
        "a tab with no sidebar row could not even be stored as denied")
    # The API. Both children the page calls, and the bare prefix's neighbours left alone.
    for path in ("/api/info-sheet/d1", "/api/info-sheet/generate",
                 "/api/info-sheet/" + "x" * 40):
        assert nav_access.is_api_denied("user", path) is True, path
    assert nav_access.denied_api_prefixes("user") == ["/api/info-sheet/"]
    # The page itself, and the tab named back so the refusal card can say which one.
    assert nav_access.page_denied("user", hidden) == hidden
    assert nav_access.denied_page_map("user") == {hidden: hidden}
    # And only for the role that was denied it.
    assert nav_access.is_api_denied("admin", "/api/info-sheet/d1") is False
    assert nav_access.page_denied("admin", hidden) is None
    assert nav_access.is_api_denied("super_admin", "/api/info-sheet/d1") is False


def test_a_hidden_tab_still_has_a_row_in_the_capability_table_flagged_as_hidden():
    """The Admin page builds its switches from this table plus auth.js's matrix. Dropping the row
    would make the switch missing rather than obviously present-but-different, which is the state
    where somebody denied it and cannot take it back."""
    table = {row["href"]: row for row in nav_access.capability_table()}
    for href in nav_access.NO_SIDEBAR_TABS:
        assert href in table, "%s has no row for the Admin page to draw" % href
        assert table[href]["no_sidebar"] is True
        assert table[href]["locked"] is False
        assert table[href]["api"], (
            "%s owns no private route, so hiding the tab is now all a switch there does — the "
            "Admin page's wording is derived from `api` and needs re-reading" % href)
    assert table["/leads.html"]["no_sidebar"] is False, "a drawn tab is not flagged hidden"


def test_the_recovery_command_is_written_down_where_somebody_locked_out_would_look():
    """The whole reason this is a file and not a table. If the module docstring stops naming the
    one-command recovery, the next person needing it is reading source under pressure."""
    doc = nav_access.__doc__ or ""
    assert "rm -f /app/data/nav_access.json" in doc, (
        "the module no longer documents how to recover from a policy that locked the wrong person "
        "out; that command is the reason this is a file on the volume and not a database table")
    assert "nav_access.json" in nav_access._FILE.name, (
        "the file has been renamed but the documented recovery command still names the old one")


# ── self-lockout arithmetic ───────────────────────────────────────────────────
def test_newly_denied_reports_only_what_a_change_takes_away():
    was = {"user": ["/leads.html"]}
    assert nav_access.newly_denied(was, {"user": ["/leads.html", "/trash.html"]}, "user") == \
        ["/trash.html"]
    assert nav_access.newly_denied(was, {"user": []}, "user") == [], "removing a denial is widening"
    assert nav_access.newly_denied(was, {"user": ["/leads.html"]}, "user") == []
    assert nav_access.newly_denied(was, {"admin": ["/trash.html"]}, "user") == []
    assert nav_access.newly_denied(None, {"user": ["/trash.html"]}, "user") == ["/trash.html"]


def test_the_store_is_safe_across_threads():
    """Two admins saving at once must leave one whole policy on disk, not a mix of two."""
    import threading
    errors = []

    def worker(i):
        try:
            for _ in range(20):
                nav_access.save({"user": [list(nav_access.TABS)[i + 1]]}, "u%d@x.com" % i)
                nav_access.get()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors, errors
    assert len(nav_access.get()["deny"].get("user", [])) == 1
