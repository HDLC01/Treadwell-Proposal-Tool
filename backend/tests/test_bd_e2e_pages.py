"""Every BD page, as every BD role, at desktop and phone width, in a real Chromium against the live app
(#810: BD's test_e2e_pages, moved once the last of BD's pages, Contacts, had moved in).

The sweep a reviewer would do by hand before Hanz walks the screens: each of the 7 BD pages under /bd/
(This Week, Contacts, one contact, Add contact, Potential BD Contacts, Analytics, Admin) opens for each of
the fixture seed's five BD roles (Avery Quill salesperson, Casey Moret assistant, Devon Hale manager,
Emery Stoll admin, Frankie Oduya super admin) at 1280 and 390 wide, and must
  * finish loading: nothing on the page is still busy (aria-busy) or a skeleton;
  * raise no JavaScript error, no console error and no failed same-origin request (an answer of 400 or
    more is not a failed request: Potential BD Contacts and Analytics show the server's 503 "not built
    yet", and a page a role may not use says so);
  * on a phone, never scroll sideways;
  * link to no BD page that is not there (spec #802, page links: MOVED_PAGES, every BD page since
    Contacts moved), and link to Contacts from the sidebar, which every BD role has.
A role a page refuses is fine: it must refuse with words on a page, not a crash. The assistant who opens
This Week lands on Contacts, her BD home. BD's login page is not here: the tool's sign-in replaced it
(tests/test_bd_pages_off.py and test_sign_in_return.py have its redirect).

Plus BD's two sweeps over the pages' words: no emoji anywhere (the tool's icons are its js/icons.js), and
every phone number reads 913-555-0101 whatever way it was typed into the workbook, in words or in a call
button's label.

Runs in the browser job of ci.yml (tests/_bd_browser.py: the live app on a seeded BD test database,
sign-in faked only inside the test process). Nothing here changes data.
"""
import re

import pytest

from _bd_browser import DESKTOP, MOVED_PAGES, PHONE, Page, bd_links, browser, live_app_db, sideways

ROLES = {"salesperson": "avery.quill@example.com", "assistant": "casey.moret@example.com",
         "manager": "devon.hale@example.com", "admin": "emery.stoll@example.com",
         "super_admin": "frankie.oduya@example.com"}
PAGES = ["/bd/", "/bd/contacts.html", "/bd/contact.html?id=21", "/bd/add.html", "/bd/review.html",
         "/bd/analytics.html", "/bd/admin.html"]


@pytest.fixture(scope="module")
def env():
    with live_app_db() as (base, _url), browser() as b:
        yield base, b


def settled(pg):
    """Wait until the page has stopped loading: no request in flight, nothing shown in <main> busy (a
    section a role is not shown may keep the skeleton it was never filled over)."""
    pg.wait_for_load_state("networkidle", timeout=20000)
    pg.wait_for_function("() => ![...document.querySelectorAll('#main [aria-busy=\"true\"], #main .skeleton')]"
                         ".some(e => e.offsetParent !== null)", timeout=15000)
    pg.wait_for_timeout(300)        # late paints: toasts, deferred panels


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
@pytest.mark.parametrize("role", list(ROLES))
@pytest.mark.parametrize("path", PAGES)
def test_page_loads_cleanly(env, path, role, viewport):
    base, b = env
    p = Page(b, base, viewport, email=ROLES[role])
    try:
        pg = p.open_signed_in(path)
        if path == "/bd/" and role == "assistant":
            pg.wait_for_function("() => location.pathname === '/bd/contacts.html'", timeout=10000)
            # the redirect can land while /bd/ is still loading; the browser then cancels the rest of it
            p.errors[:] = [e for e in p.errors if e != "failed /bd/"]
        settled(pg)
        assert p.errors == [], p.errors
        assert pg.title().strip().endswith("· BD CRM · Treadwell"), pg.title()
        assert pg.locator("#main").count() == 1, "one <main id=\"main\">"
        assert pg.locator("#main").inner_text().strip(), "a blank page"
        refused = [x for x in p.bd_errors() if x[0] not in (403, 503)]
        assert refused == [], "only a refusal or a not-built-yet answer: %r" % refused
        pg.locator("#tw-bd-sections a").first.wait_for(state="attached", timeout=15000)
        seen = set(bd_links(pg))
        assert seen <= MOVED_PAGES, sorted(seen - MOVED_PAGES)
        assert "/bd/contacts.html" in seen, "Contacts is in every BD role's sidebar"
        if viewport is PHONE:
            over = sideways(pg)
            assert over <= 1, "scrolls sideways by %dpx at 390 wide" % over
    finally:
        p.close()


def is_emoji(ch):
    o = ord(ch)
    return 0x1F300 <= o <= 0x1FAFF or 0x2600 <= o <= 0x27BF


@pytest.mark.parametrize("path", PAGES)
def test_no_page_shows_an_emoji(env, path):
    """House rule: no emoji in the UI; glyphs come from js/icons.js."""
    base, b = env
    p = Page(b, base, email=ROLES["admin"])
    try:
        pg = p.open_signed_in(path)
        settled(pg)
        emoji = [ch for ch in pg.locator("body").inner_text() if is_emoji(ch)]
        assert not emoji, emoji[:10]
    finally:
        p.close()


# The seed's phones are typed every way the workbook mixes them (913-555-0101, (913) 555-0102,
# 816.555.0103, 816 555 0104, +1 785 555 0105). This Week holds Dana's, Contacts opens Bluestem (three
# people) and Prairie Ridge Builders, Inc. (Rory's "(913) 555-0102"), and Dana's own page has hers.
@pytest.mark.parametrize("path", ["/bd/", "/bd/contacts.html?company=11", "/bd/contacts.html?company=16",
                                  "/bd/contact.html?id=21"])
def test_phone_numbers_read_the_same_everywhere(env, path):
    """A tel: link with words reads "913-555-0101" (or "Call 913-555-0101"); a round call button with no
    words carries the dashed number in its aria-label ("Call Dana Whitlow, 913-555-0101")."""
    base, b = env
    p = Page(b, base, email=ROLES["salesperson"])
    try:
        pg = p.open_signed_in(path)
        settled(pg)
        links = pg.locator('#main a[href^="tel:"]')
        links.first.wait_for(state="attached", timeout=15000)
        seen = links.evaluate_all(
            "els => els.map(e => ({text: e.textContent.trim(), label: e.getAttribute('aria-label') || ''}))")
        assert seen, "no phone links on %s" % path
        bad = [s for s in seen if s["text"] and not re.fullmatch(r"(Call )?\d{3}-\d{3}-\d{4}", s["text"])]
        assert not bad, bad
        silent = [s for s in seen if not s["text"] and not re.search(r"\d{3}-\d{3}-\d{4}", s["label"])]
        assert not silent, "a call button with no words must say the dashed number in its aria-label: %r" % silent
        if "company=11" in path:
            assert {"text": "913-555-0102", "label": ""} in seen, "Rory's (913) 555-0102, dashed"
        assert any(s["text"] for s in seen), "at least one phone link shows the number in words"
        assert p.errors == [], p.errors
    finally:
        p.close()
