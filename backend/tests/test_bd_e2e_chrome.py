"""The BD CRM's chrome in a real Chromium, against the live app (#806; Q5 as changed by Hanz on 2026-11-19).

BD's test_e2e_chrome, rewritten. BD's own rail, phone tab bar, More sheet and top bar are gone: the
BD pages wear the proposal tool's sidebar, and BD's sections sit inside it, indented under a
collapsible "BD CRM" row. What a person sees:

  * Desktop: the BD CRM row (BETA) is the one lit row on every /bd/ page, its group is open, and the
    sections are exactly the ones the person's BD role may open, the current one lit by full path.
    In this ticket that is This Week alone, and only for the roles BD's can() gives it to.
  * The chevron is a real button (aria-expanded, aria-controls). On a tool page the group starts
    shut and asks BD nothing; on desktop the last choice is remembered (tw_bd_open), never on a
    phone. The sidebar's Hide menu hides the sections with everything else.
  * Phone: the sidebar is a drawer and the sections are inside it, at a finger's size.
  * No BD login (a proposal-tool admin nobody added on BD, or a turned-off login): the row is still
    there, and both the group and the page say the server's own sentence.
  * A signed-out visit to /bd/ (or to BD's old login page) goes through the tool's sign-in and comes
    back to /bd/.
  * At 390 and 820 wide the BD home never scrolls sideways.

Runs in the browser job of ci.yml (tests/_bd_browser.py: the live app on a seeded BD test database,
sign-in faked only inside the test process). Expected values are the fixture seed's made-up people.
"""
import re

import pytest

from _bd_browser import DESKTOP, PHONE, TABLET, Page, browser, live_app

# A proposal-tool admin with no BD login. Everyone else is a plain tool "user".
TOOL_ADMIN_NO_BD = "pat.tool@example.com"

# The fixture seed's people who may open This Week: (email, first name, BD role as the page says it).
WEEK_PEOPLE = [
    ("avery.quill@example.com", "Avery", "Salesperson"),
    ("devon.hale@example.com", "Devon", "Manager"),
    ("emery.stoll@example.com", "Emery", "Admin"),
    ("frankie.oduya@example.com", "Frankie", "Super admin"),
]
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
    """The group's list is filled once /api/bd/me answers."""
    page.wait_for_function(
        "() => { const l = document.getElementById('tw-bd-sections');"
        " return l && !l.hidden && l.children.length > 0; }", timeout=10000)


def _bd_me_requests(p):
    seen = []
    p.page.on("request", lambda r: "/api/bd/me" in r.url and seen.append(r.url))
    return seen


def _role_text(page):
    page.wait_for_function("() => !/Loading/.test(document.getElementById('bd-role').textContent)",
                           timeout=10000)
    return page.locator("#bd-role").inner_text().strip()


# ── desktop ──────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("email,first,role", WEEK_PEOPLE)
def test_on_the_bd_home_the_bd_row_is_the_one_lit_row_and_its_group_is_open(env, email, first, role):
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
        assert _sections(page) == ["This Week"]
        current = page.locator('#tw-bd-sections [aria-current="page"]')
        assert current.count() == 1 and current.get_attribute("href") == "/bd/"
        assert re.fullmatch(r"Good (morning|afternoon|evening), " + first,
                            page.locator("#bd-greeting").inner_text().strip())
        assert _role_text(page) == "Your BD role: " + role
        assert p.errors == [] and p.bd_errors() == [], (p.errors, p.bd_errors())
    finally:
        p.close()


def test_the_assistant_has_no_section_until_her_pages_move(env):
    p = _page(env, ASSISTANT)
    try:
        page = p.open_signed_in("/bd/")
        _wait_sections(page)
        assert _sections(page) == []
        assert page.locator("#tw-bd-sections").inner_text().strip() == "Nothing here for your BD role yet."
        assert _role_text(page) == "Your BD role: Assistant"
        assert p.errors == [] and p.bd_errors() == [], (p.errors, p.bd_errors())
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
        assert _role_text(page) == sentence
        assert page.locator("#bd-home-note").is_hidden()
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
        assert _sections(page) == ["This Week"]
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
        assert _sections(page) == ["This Week"]
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
        for sel in ("#tw-bd-chev", "#tw-bd-sections .tw-bd-sec"):
            box = page.locator(sel).bounding_box()
            assert box and box["height"] >= 43.5, (sel, box)
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
        assert _sections(page) == ["This Week"]
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
        _role_text(page)
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
        page.goto(p.base + "/login.html")
        page.wait_for_url(re.compile(r".*/bd/$"), timeout=10000)
        _role_text(page)
        assert page.locator("#bd-role").inner_text().strip() == "Your BD role: Super admin"
        assert page.evaluate("sessionStorage.getItem('tw_return_to')") is None, "a return is used once"
    finally:
        p.close()
