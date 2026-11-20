"""The BD CRM's chrome in a real Chromium, against the live app (#806; Q5 as changed by Hanz on 2026-11-19).

BD's test_e2e_chrome, rewritten. BD's own rail, phone tab bar, More sheet and top bar are gone: the
BD pages wear the proposal tool's sidebar, and BD's sections sit inside it, indented under a
collapsible "BD CRM" row. What a person sees:

  * Desktop: the BD CRM row (BETA) is the one lit row on every /bd/ page, its group is open, and the
    sections are exactly the ones the person's BD role may open, the current one lit by full path.
    That is This Week and Add contact (#808), each only for the roles BD's can() gives it to.
    On a laptop-height window (1280 by 800) the menu scrolls the lit section into sight.
  * The chevron is a real button (aria-expanded, aria-controls). On a tool page the group starts
    shut and asks BD nothing; on desktop the last choice is remembered (tw_bd_open), never on a
    phone. The sidebar's Hide menu hides the sections with everything else.
  * Phone: the sidebar is a drawer and the sections are inside it, at a finger's size.
  * No BD login (a proposal-tool admin nobody added on BD, or a turned-off login): the row is still
    there, and both the group and the page say the server's own sentence.
  * A signed-out visit to /bd/ (or to BD's old login page) goes through the tool's sign-in and comes
    back to /bd/.
  * At 390 and 820 wide This Week, /bd/, never scrolls sideways.

/bd/ is This Week since #807 (it was #806's greeting page): a salesperson is greeted and sees their
week, a manager or admin is greeted and asked whose week to look at, and the assistant, whose BD
home is Contacts, is sent to the Contacts page (until it moves, a page saying it is coming).

Runs in the browser job of ci.yml (tests/_bd_browser.py: the live app on a seeded BD test database,
sign-in faked only inside the test process). Expected values are the fixture seed's made-up people.
"""
import re

import pytest

from _bd_browser import DESKTOP, PHONE, TABLET, Page, browser, live_app

# A proposal-tool admin with no BD login. Everyone else is a plain tool "user".
TOOL_ADMIN_NO_BD = "pat.tool@example.com"

# The fixture seed's people who may open This Week: (email, first name, what This Week says under the
# greeting). Avery is a salesperson with one call to go on the seed's week; the others have no weekly
# list of their own and are asked whose week to look at.
CHOOSE = "Choose whose week to look at."
WEEK_PEOPLE = [
    ("avery.quill@example.com", "Avery", "1 call to go this week."),
    ("devon.hale@example.com", "Devon", CHOOSE),
    ("emery.stoll@example.com", "Emery", CHOOSE),
    ("frankie.oduya@example.com", "Frankie", CHOOSE),
]
# The sections each of them sees: Add contact is not the manager's (#808).
BOTH = ["This Week", "Add contact"]
SECTIONS = {"avery.quill@example.com": BOTH, "devon.hale@example.com": ["This Week"],
            "emery.stoll@example.com": BOTH, "frankie.oduya@example.com": BOTH}
SUPER = "frankie.oduya@example.com"
ASSISTANT = "casey.moret@example.com"
TURNED_OFF = "gale.ward@example.com"
TOOL_PAGE = "/history.html"


@pytest.fixture(scope="module")
def env():
    with live_app({TOOL_ADMIN_NO_BD: "admin"}) as base, browser() as b:
        yield base, b


def _page(env, email=None, viewport=DESKTOP, storage=None):
    base, b = env
    return Page(b, base, viewport, email=email, storage=storage)


def _sections(page):
    return [t.strip() for t in page.locator("#tw-bd-sections .tw-bd-sec").all_inner_texts()]


def _wait_sections(page):
    """The group's list is filled once /api/bd/me answers (until then it says it is loading)."""
    page.wait_for_function(
        "() => { const l = document.getElementById('tw-bd-sections');"
        " return l && !l.hidden && l.children.length > 0 && l.textContent.trim() !== 'Loading...'; }",
        timeout=10000)


def _bd_me_requests(p):
    seen = []
    p.page.on("request", lambda r: "/api/bd/me" in r.url and seen.append(r.url))
    return seen


def _sub_text(page):
    """What This Week says under its heading, once it has said something."""
    page.wait_for_function("() => document.getElementById('week-sub').textContent.trim() !== ''",
                           timeout=10000)
    return page.locator("#week-sub").inner_text().strip()


# ── desktop ──────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("email,first,sub", WEEK_PEOPLE)
def test_on_the_bd_home_the_bd_row_is_the_one_lit_row_and_its_group_is_open(env, email, first, sub):
    p = _page(env, email)
    try:
        page = p.open_signed_in("/bd/")
        _wait_sections(page)
        lit = page.locator("#tw-sidebar .tw-nav-item.active")
        assert lit.count() == 1, "exactly one sidebar row is lit"
        assert lit.get_attribute("href") == "/bd/"
        assert lit.locator(".tw-nav-label").inner_text() == "BD CRM"
        assert lit.locator(".tw-nav-tag").inner_text() == "BETA"
        chev = page.locator("#tw-bd-chev")
        assert chev.evaluate("e => e.tagName") == "BUTTON"
        assert chev.get_attribute("aria-expanded") == "true"
        assert chev.get_attribute("aria-controls") == "tw-bd-sections"
        assert page.locator("#tw-bd-sections").is_visible()
        assert _sections(page) == SECTIONS[email]
        current = page.locator('#tw-bd-sections [aria-current="page"]')
        assert current.count() == 1 and current.get_attribute("href") == "/bd/"
        assert _sub_text(page) == sub          # said once the week (or the choice of whose week) is drawn
        assert re.fullmatch(r"Good (morning|afternoon|evening), " + first,
                            page.locator("#wk-greeting").inner_text().strip())
        assert p.errors == [] and p.bd_errors() == [], (p.errors, p.bd_errors())
    finally:
        p.close()


def test_the_assistant_sees_add_contact_and_it_works(env):
    """This Week sends her to her BD home, Contacts; there, the BD CRM row is lit and her group is
    open with her one section, Add contact (#808; Contacts joins it when its page moves), which opens
    the form."""
    p = _page(env, ASSISTANT)
    try:
        page = p.open_signed_in("/bd/")
        page.wait_for_url(re.compile(r".*/bd/contacts\.html(\?.*)?$"), timeout=10000)
        page.wait_for_selector("#tw-bd-chev")
        _wait_sections(page)
        assert _sections(page) == ["Add contact"]
        assert page.locator('#tw-bd-sections [aria-current="page"]').count() == 0
        lit = page.locator("#tw-sidebar .tw-nav-item.active")
        assert lit.count() == 1 and lit.get_attribute("href") == "/bd/"
        page.locator('#tw-bd-sections a[href="/bd/add.html"]').click()
        page.locator("#add-form").wait_for(timeout=15000)
        _wait_sections(page)
        current = page.locator('#tw-bd-sections [aria-current="page"]')
        assert current.count() == 1 and current.get_attribute("href") == "/bd/add.html"
        # The redirect can land while /bd/ is still loading; the browser then cancels the rest of it.
        errors = [e for e in p.errors if e != "failed /bd/"]
        assert errors == [] and p.bd_errors() == [], (p.errors, p.bd_errors())
    finally:
        p.close()


@pytest.mark.parametrize("email,sentence", [
    (TOOL_ADMIN_NO_BD, "You don't have a BD role. Ask a BD admin to add you."),
    (TURNED_OFF, "Your BD login is turned off. Ask a BD admin to turn it back on."),
])
def test_without_a_bd_login_the_row_stays_and_the_server_says_why(env, email, sentence):
    p = _page(env, email)
    try:
        asked = _bd_me_requests(p)
        page = p.open_signed_in("/bd/")
        _wait_sections(page)
        assert page.locator('#tw-sidebar .tw-nav-item[href="/bd/"]').count() == 1
        assert _sections(page) == []
        assert page.locator("#tw-bd-sections").inner_text().strip() == sentence
        assert _sub_text(page) == sentence
        assert page.locator("#summary").is_hidden(), "no data"
        assert len(asked) == 1, "the group and the page share one /api/bd/me"
        assert p.bd_errors() == [(403, "/api/bd/me")]
        assert p.errors == [], p.errors
    finally:
        p.close()


def test_on_a_tool_page_the_group_starts_shut_asks_bd_nothing_and_the_chevron_opens_it(env):
    p = _page(env, SUPER)
    try:
        asked = _bd_me_requests(p)
        page = p.open_signed_in(TOOL_PAGE)
        chev = page.locator("#tw-bd-chev")
        assert chev.get_attribute("aria-expanded") == "false"
        assert page.locator("#tw-bd-sections").is_hidden()
        assert page.locator('#tw-sidebar .tw-nav-item[href="/bd/"]').get_attribute("class") == "tw-nav-item"
        page.wait_for_timeout(300)
        assert asked == [], "a shut group must not ask BD anything"

        chev.click()
        _wait_sections(page)
        assert chev.get_attribute("aria-expanded") == "true"
        assert _sections(page) == BOTH
        assert page.locator('#tw-bd-sections [aria-current="page"]').count() == 0, \
            "This Week is not the page you are on"
        assert page.evaluate("localStorage.getItem('tw_bd_open')") == "1"
        assert len(asked) == 1

        page.reload()
        page.wait_for_selector("#tw-bd-chev")
        _wait_sections(page)
        assert page.locator("#tw-bd-chev").get_attribute("aria-expanded") == "true", \
            "desktop remembers the group open"

        page.locator("#tw-bd-chev").click()
        assert page.locator("#tw-bd-chev").get_attribute("aria-expanded") == "false"
        assert page.locator("#tw-bd-sections").is_hidden()
        assert page.evaluate("localStorage.getItem('tw_bd_open')") == "0"
        assert p.errors == [], p.errors
    finally:
        p.close()


def test_a_bd_page_opens_the_group_whatever_was_remembered(env):
    p = _page(env, SUPER, storage={"tw_bd_open": "0"})
    try:
        page = p.open_signed_in("/bd/")
        _wait_sections(page)
        assert page.locator("#tw-bd-chev").get_attribute("aria-expanded") == "true"
        assert _sections(page) == BOTH
    finally:
        p.close()


def test_the_hide_menu_button_hides_the_bd_sections_with_the_sidebar(env):
    p = _page(env, SUPER)
    try:
        page = p.open_signed_in("/bd/")
        _wait_sections(page)
        assert page.locator('#tw-bd-sections a:has-text("This Week")').is_visible()
        page.locator("#tw-collapse").click()
        page.wait_for_function("() => !document.documentElement.classList.contains('tw-nav-open')")
        page.locator("#tw-sidebar").wait_for(state="hidden")
        assert not page.locator('#tw-bd-sections a:has-text("This Week")').is_visible()
        assert page.evaluate("localStorage.getItem('tw_nav_open')") == "0"
    finally:
        p.close()


def test_on_a_laptop_window_the_lit_section_is_scrolled_into_sight(env):
    """At 1280 by 800 the menu is taller than the window, so Add contact, BD's second section, lands
    below the menu's fold, behind the user card. On its own page the menu scrolls it into sight: the
    whole row sits inside the menu's visible box, and a tap at its middle reaches the row."""
    p = _page(env, "avery.quill@example.com")
    try:
        page = p.open_signed_in("/bd/add.html")
        page.locator("#add-form").wait_for(timeout=15000)
        _wait_sections(page)
        page.wait_for_timeout(200)
        row = page.locator('#tw-bd-sections [aria-current="page"]')
        assert row.inner_text().strip() == "Add contact"
        box = row.bounding_box()
        nav = page.locator("#tw-sidebar .tw-nav").bounding_box()
        assert box["y"] >= nav["y"] and box["y"] + box["height"] <= nav["y"] + nav["height"], (box, nav)
        hit = page.evaluate("([x, y]) => { const e = document.elementFromPoint(x, y);"
                            " return !!(e && e.closest('.tw-bd-sec.active')); }",
                            [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2])
        assert hit, "the user card covers the lit section"
        assert page.evaluate("window.scrollY") == 0, "only the menu scrolls, not the page"
    finally:
        p.close()


# ── phone ────────────────────────────────────────────────────────────────────────────────────────
def test_on_a_phone_the_bd_sections_are_inside_the_drawer(env):
    p = _page(env, SUPER, PHONE)
    try:
        page = p.open_signed_in("/bd/")
        burger = page.locator("#tw-burger")
        burger.wait_for(state="visible")
        assert not page.locator("#tw-sidebar").is_visible(), "the drawer starts shut on a phone"
        burger.click()
        page.locator("#tw-sidebar").wait_for(state="visible")
        _wait_sections(page)
        section = page.locator('#tw-sidebar #tw-bd-sections a:has-text("This Week")')
        assert section.is_visible()
        assert page.locator("#tw-bd-chev").get_attribute("aria-expanded") == "true"
        for target in [page.locator("#tw-bd-chev")] + page.locator("#tw-bd-sections .tw-bd-sec").all():
            box = target.bounding_box()
            assert box and box["height"] >= 43.5, (target, box)
        # Keep this page (the link's own navigation is cancelled before the sidebar sees the tap), so
        # what is seen is THIS page shutting its drawer, not the next page starting shut.
        page.evaluate("document.addEventListener('click', e => {"
                      " if (e.target.closest('.tw-bd-sec')) e.preventDefault(); }, true)")
        section.click()
        page.wait_for_function("() => !document.documentElement.classList.contains('tw-nav-open')",
                               timeout=5000)
        page.locator("#tw-sidebar").wait_for(state="hidden", timeout=3000)   # after its slide
        assert p.errors == [] and p.bd_errors() == [], (p.errors, p.bd_errors())
    finally:
        p.close()


def test_on_a_phone_a_tool_page_starts_shut_and_remembers_nothing(env):
    p = _page(env, SUPER, PHONE, storage={"tw_bd_open": "1"})
    try:
        page = p.open_signed_in(TOOL_PAGE)
        page.locator("#tw-burger").click()
        page.locator("#tw-sidebar").wait_for(state="visible")
        chev = page.locator("#tw-bd-chev")
        assert chev.get_attribute("aria-expanded") == "false", "a desktop choice never opens it on a phone"
        assert page.locator("#tw-bd-sections").is_hidden()
        chev.click()
        _wait_sections(page)
        assert _sections(page) == BOTH
        chev.click()
        assert chev.get_attribute("aria-expanded") == "false"
        assert page.locator("#tw-bd-sections").is_hidden()
        assert page.evaluate("localStorage.getItem('tw_bd_open')") == "1", "a phone writes nothing"
    finally:
        p.close()


@pytest.mark.parametrize("viewport", [PHONE, TABLET], ids=["390", "820"])
def test_the_bd_home_never_scrolls_sideways(env, viewport):
    p = _page(env, SUPER, viewport)
    try:
        page = p.open_signed_in("/bd/")
        _sub_text(page)
        page.wait_for_timeout(200)
        over = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
        assert over <= 1, "scrolls sideways by %dpx at %d wide" % (over, viewport["width"])
        if viewport is TABLET:
            assert page.locator("#tw-sidebar").is_visible(), "at 820 the sidebar is a rail beside the page"
    finally:
        p.close()


# ── signed out ───────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("start", ["/bd/", "/bd/login.html"])
def test_a_signed_out_visit_signs_in_and_comes_back_to_bd(env, start):
    p = _page(env)
    try:
        page = p.open(start)
        page.wait_for_url("**/login.html", timeout=10000)
        assert page.evaluate("new URL(location.href).pathname") == "/login.html"
        assert page.evaluate("sessionStorage.getItem('tw_return_to')") == "/bd/"
        p.sign_in(SUPER)
        # The login page sends a signed-in person straight on, which can abort the navigation goto
        # is still waiting on (net::ERR_ABORTED); "commit" returns as soon as the page starts loading.
        page.goto(p.base + "/login.html", wait_until="commit")
        page.wait_for_url(re.compile(r".*/bd/$"), timeout=10000)
        assert _sub_text(page) == CHOOSE, "back on This Week, signed in as the super admin"
        assert page.evaluate("sessionStorage.getItem('tw_return_to')") is None, "a return is used once"
    finally:
        p.close()
