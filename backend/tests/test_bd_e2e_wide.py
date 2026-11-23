"""The BD pages fill the window beside the tool's sidebar, in a real Chromium against the live app.

Hanz, 2026-11-23: "can we redesign the dashboard of the BD CRM to fill up the whole page? Because it's
filling up mostly on the left side only." Every BD page sat in a 1180px column on the left of a wide
monitor. Now a BD page's <main> runs to the window's right edge, like the tool's own CRM board, and its
content (the This Week columns, the Contacts list, a contact's two columns, Admin's cards) runs with it,
less the page's 28px gutter. The side column (This Week's tray, a contact's side cards) grows on a wide
window rather than staying 320px, so the width is used, not just stretched.

Phone width does not change: at 390 and 320 nothing scrolls sideways.

Runs in the browser job of ci.yml (tests/_bd_browser.py: the live app on a seeded BD test database,
sign-in faked only inside the test process). Nothing here changes data.
"""
import pytest

from _bd_browser import PHONE, Page, browser, live_app_db, sideways

AVERY = "avery.quill@example.com"         # salesperson: This Week has her own week
CASEY = "casey.moret@example.com"         # assistant
EMERY = "emery.stoll@example.com"         # admin

WIDE = {"width": 1920, "height": 1080}
NARROWEST = {"width": 320, "height": 640}
NEAR = 32       # px: how close to the window's right edge "fills the page" means
GUTTER = 28     # px: the page's side gutter at desktop width (bd.css --bd-gutter)

# (path, who, what has loaded, the content that must reach the right edge)
PAGES = [
    ("/bd/", AVERY, "#summary .wk-progress-in", "#wk-layout"),
    ("/bd/contacts.html?company=16", CASEY, '.ct-acct.is-open[data-acct="16"] .ct-person', "#ct-list"),
    ("/bd/contact.html?id=21", AVERY, ".cd-layout .cd-side", ".cd-layout"),
    ("/bd/admin.html", EMERY, ".ad-sec:not([hidden])", ".ad-sec:not([hidden])"),
]
IDS = ["this-week", "contacts", "contact", "admin"]


@pytest.fixture(scope="module")
def env():
    with live_app_db() as (base, _url), browser() as b:
        yield base, b


@pytest.fixture
def open_page(env):
    base, b = env
    opened = []

    def _open(path, email, viewport, ready):
        p = Page(b, base, viewport, email=email)
        opened.append(p)
        pg = p.open_signed_in(path)
        pg.locator(ready).first.wait_for(timeout=15000)
        pg.evaluate("() => document.fonts.ready.then(() => true)")
        return pg
    yield _open
    for p in opened:
        assert p.errors == [], p.errors
        p.close()


def _gap_right(pg, selector):
    """Pixels between the element's right edge and the window's (its scrollbar left out)."""
    return pg.evaluate("s => document.documentElement.clientWidth"
                       " - document.querySelector(s).getBoundingClientRect().right", selector)


@pytest.mark.parametrize("path,email,ready,content", PAGES, ids=IDS)
def test_at_1920_the_page_fills_the_main_area(open_page, path, email, ready, content):
    pg = open_page(path, email, WIDE, ready)
    main_gap = _gap_right(pg, "#main")
    assert main_gap <= NEAR, "the page stops %dpx short of the window's right edge" % main_gap
    # the content runs to the page's own gutter (28px), not to a column on the left
    gap = _gap_right(pg, content) - main_gap
    assert gap <= GUTTER + 1, "%s stops %dpx short of the page's right edge" % (content, gap)
    assert sideways(pg) <= 1


def test_at_1920_a_contacts_side_column_grows(open_page):
    """The extra width is used: the side column is wider than the 320px it is up to a laptop's width."""
    pg = open_page("/bd/contact.html?id=21", AVERY, WIDE, ".cd-layout .cd-side")
    side = pg.locator(".cd-layout .cd-side").bounding_box()["width"]
    assert side > 360, side


HEAD_NEAR = 16  # px: how close a contact row's cell must sit to the heading above it


@pytest.mark.parametrize("width", [1920, 2560])
def test_on_a_wide_window_contact_rows_sit_under_their_headings(open_page, width):
    """The heading row filling the width is not enough: an open account's contact rows are a different
    box, so their Status and Last live talk cells must still start under Owner and Last live talk."""
    pg = open_page("/bd/contacts.html?company=16", CASEY, {"width": width, "height": 1080},
                   '.ct-acct.is-open[data-acct="16"] .ct-person')
    left = pg.evaluate("""() => {
      const x = e => e.getBoundingClientRect().left;
      const head = {};
      document.querySelectorAll('.ct-colhead > span').forEach(s => { head[s.textContent] = x(s); });
      const rows = [...document.querySelectorAll('.ct-acct.is-open .ct-person')];
      return {owner: head['Owner'], last: head['Last live talk'],
              status: rows.map(r => x(r.querySelector('.ct-p-status'))),
              talk: rows.map(r => x(r.querySelector('.ct-p-last')))};
    }""")
    assert left["talk"], "the open account shows no contact rows"
    for talk in left["talk"]:
        assert abs(talk - left["last"]) <= HEAD_NEAR, (talk, left["last"])
    for status in left["status"]:
        assert abs(status - left["owner"]) <= HEAD_NEAR, (status, left["owner"])


def test_at_1920_a_contacts_controls_and_history_keep_their_measure(open_page):
    """A wide card does not stretch the follow-up choice into a bar, or put History's dates a card's
    width from the words they belong to."""
    pg = open_page("/bd/contact.html?id=21", AVERY, WIDE, ".cd-layout .cd-side")
    pg.locator(".cd-tl-when").first.wait_for(timeout=15000)
    seg = pg.locator(".call-seg").first.bounding_box()["width"]
    assert seg <= 520, "the follow-up choice is %dpx wide" % seg
    # The measure is 72 characters of the page's own font, so it is read from the page: 72ch is about
    # 540px in Windows fonts and 641px in CI's DejaVu Sans. The card itself is over 1300px wide here.
    got = pg.evaluate("""() => {
      const main = document.querySelector('.cd-tl-main');
      const probe = document.createElement('div');
      probe.style.cssText = 'width:72ch;height:0;position:absolute;visibility:hidden';
      main.appendChild(probe);
      const measure = probe.getBoundingClientRect().width;
      probe.remove();
      const card = main.closest('.card, section, .cd-main') || main.parentElement;
      const gaps = [...document.querySelectorAll('.cd-tl-item')].map(it => {
        const when = it.querySelector('.cd-tl-when'), word = it.querySelector('.cd-tl-word');
        return when && word ? when.getBoundingClientRect().right - word.getBoundingClientRect().left : 0; });
      return {measure, gaps, card: card.getBoundingClientRect().width};
    }""")
    assert got["gaps"] and max(got["gaps"]) <= got["measure"] + 2, got
    assert max(got["gaps"]) < 0.7 * got["card"], got


@pytest.mark.parametrize("viewport", [PHONE, NARROWEST], ids=["390", "320"])
@pytest.mark.parametrize("path,email,ready,content", PAGES, ids=IDS)
def test_on_a_phone_nothing_scrolls_sideways(open_page, path, email, ready, content, viewport):
    pg = open_page(path, email, viewport, ready)
    over = sideways(pg)
    assert over <= 1, "scrolls sideways by %dpx" % over
