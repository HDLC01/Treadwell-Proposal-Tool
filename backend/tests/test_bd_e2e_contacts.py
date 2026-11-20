"""Contacts (/bd/contacts.html) in a real Chromium, against the live app (#810).

BD's test_e2e_contacts, moved with the page and rewritten for the live app and for the page as #810
rebuilt it: a list of BD accounts (companies) that open to their people, on two tabs, instead of BD's
flat list of people. Every test starts from the FIXTURE SEED (backend/bd/ops/fixture_seed.py), put back
before each test, on a server whose business day is pinned to the seed's Wednesday, 2026-11-04. The
expected values are worked by hand from the seed, never read back from the page's own rules:

  BD tab, by name (8 accounts, 11 people):
    16 Bluestem Logistics            Ines 29 (Devon's), Lena 27 (Avery's), Sam 28 (Blair's): a 1-1-1 tie
                                     with no live talk, so the first by name, Avery, "+2"; "Never"
    14 Cedar Creek Concrete          Priya (Avery's)
    15 Cedar Crest Concrete          Owen (Blair's)
    12 Cottonwood & Sons Paving      Marisa (Avery's), a meeting Mon, Jun 15
    13 Cottonwood Sons Paving Co.    Theo (Blair's)
    18 Osage Plains Brewing          Wes, nobody's: "No owner"
    10 Prairie Ridge Builders LLC    Dana (Avery's), an answered call Tue, Oct 20; her open follow-up 302 is
                                     on Avery's list this week; last follow-up Nov 2, so not due
    11 Prairie Ridge Builders, Inc.  D. Whitlow 33 (a possible duplicate of Dana) and Rory 22, both Blair's
  Maintenance tab: 17 Kaw Valley Cold Storage, Hal 30 and Nora 31 (Avery's); Nora never followed up, so
    her follow-up is due ("Due now"); Hal's answered call Thu, Aug 20 is its last live talk.
  Every BD person but Dana needs confirming (the column's default): To confirm 10. One possible
  duplicate (D. Whitlow). One unknown call, 801, from 913-555-0199, Tue, Nov 3, 4:42 PM. One past import,
  a practice run on Thu, Oct 1.
  Avery Quill (salesperson), Casey Moret (assistant), Devon Hale (manager), Emery Stoll (admin).

What it proves, for the ticket: the BD tab's rows (people, owner and "+N", last live talk); a row opens
to its people, each linking to their contact page; the Maintenance tab is grouped by company (Q6);
?company= opens that account; search by name, phone in any format and email in any case opens the
account on the right tab with the person highlighted, and says so; the "..." menu and a right-click open
the same menu, by keyboard too, only for move_company; the one-line confirm; Make maintenance account
and Undo, and Move back to BD; the workbook import and the unknown calls are back on Contacts as BD had
them; each role's chips, sorts and buttons; no link goes to a BD page that is not there; desktop and
phone width.

BD's own Contacts tests are carried over below where their behaviour still exists on the rebuilt page;
the rest (BD's flat list of people: Show all, More filters, the row that is itself a link, "Not a
duplicate" on a row) are listed, one reason each, in the #810 PR. The second half of BD's file, Add a
contact, is carried over too (the parts #808's test_bd_e2e_contact did not already have), on the seed.

Runs in the browser job of ci.yml (tests/_bd_browser.py: the live app on a seeded BD test database,
sign-in faked only inside the test process).
"""
import re

import pytest

from _bd_browser import (DESKTOP, MOVED_PAGES, PHONE, TABLET, Page, api, bd_links, browser, live_app_db,
                         menu_acts, require_playwright, reseed, run_sql, sideways, toasts)

AVERY = "avery.quill@example.com"         # salesperson
CASEY = "casey.moret@example.com"         # assistant
DEVON = "devon.hale@example.com"          # manager
EMERY = "emery.stoll@example.com"         # admin

BD_NAMES = ["Bluestem Logistics", "Cedar Creek Concrete", "Cedar Crest Concrete", "Cottonwood & Sons Paving",
            "Cottonwood Sons Paving Co.", "Osage Plains Brewing", "Prairie Ridge Builders LLC",
            "Prairie Ridge Builders, Inc."]
CSV = "Company,Name,Email\nTallgrass Dental,Rae Lindgren,rae.lindgren@tallgrass.example.com\n"


@pytest.fixture(scope="module")
def env():
    with live_app_db() as (base, url), browser() as b:
        yield base, url, b


@pytest.fixture
def page_as(env):
    base, url, b = env
    reseed(url)
    opened = []

    def _open(path, email, viewport=DESKTOP, wait="#ct-list .ct-acct"):
        p = Page(b, base, viewport, email=email)
        p.requests = []
        p.page.on("request", lambda r: r.url.startswith(base) and p.requests.append(r.method + " " + r.url[len(base):]))
        opened.append(p)
        pg = p.open_signed_in(path)
        if wait:
            pg.locator(wait).first.wait_for(timeout=15000)
        return p, pg
    yield _open
    for p in opened:
        assert p.errors == [], p.errors
        p.close()


@pytest.fixture(scope="module")
def expect():
    require_playwright()
    from playwright.sync_api import expect
    return expect


def accounts(pg):
    return pg.locator("#ct-list .ct-acct")


def acct(pg, cid):
    return pg.locator('#ct-list .ct-acct[data-acct="%d"]' % cid)


def names(pg):
    return [t.strip() for t in pg.locator("#ct-list .ct-acct-name").all_inner_texts()]


def cells(row):
    return [" ".join(row.locator(sel).inner_text().split()) for sel in (".ct-c-people", ".ct-owner", ".ct-c-last")]


def opened_people(row):
    return [t.strip() for t in row.locator(".ct-p-name").all_inner_texts()]


def search(pg, words):
    pg.fill("#ct-q", words)


# ── the BD tab ────────────────────────────────────────────────────────────────────────────────────
def test_the_bd_tab_lists_each_account_with_its_people_owner_and_last_live_talk(page_as, expect):
    _, pg = page_as("/bd/contacts.html", CASEY)
    expect(accounts(pg)).to_have_count(8)
    assert names(pg) == BD_NAMES
    expect(pg.locator("#ct-sub")).to_have_text("11 people at 8 BD accounts · 2 maintenance contacts")
    expect(pg.locator("#ct-tab-bd")).to_have_text(re.compile(r"BD accounts\s*8"))
    expect(pg.locator("#ct-tab-maintenance")).to_have_text(re.compile(r"Maintenance\s*1"))
    assert cells(acct(pg, 16)) == ["3 people", "Avery Quill +2", "Never"]
    assert cells(acct(pg, 10)) == ["1 person", "Avery Quill", "Tue, Oct 20"]
    assert cells(acct(pg, 12)) == ["1 person", "Avery Quill", "Mon, Jun 15"]
    assert cells(acct(pg, 11)) == ["2 people", "Blair Fenn", "Never"]
    assert cells(acct(pg, 18)) == ["1 person", "No owner", "Never"]
    assert pg.locator("#ct-list .ct-person").count() == 0, "every account starts shut"


def test_an_account_opens_to_its_people_and_a_name_opens_the_contact(page_as, expect):
    """Q19: name, title, phone, email and status; each person opens their contact page."""
    _, pg = page_as("/bd/contacts.html", AVERY)
    toggle = acct(pg, 16).locator(".ct-acct-toggle")
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    row = acct(pg, 16)
    assert opened_people(row) == ["Ines Varga", "Lena Ortiz", "Sam Achebe"]
    sam = row.locator('.ct-person[data-contact="28"]')
    expect(sam.locator(".ct-p-phone a")).to_have_attribute("href", "tel:+19135550108")
    expect(sam.locator(".ct-p-phone")).to_have_text("913-555-0108")
    expect(sam.locator(".ct-p-email a")).to_have_attribute("href", "mailto:sam.achebe@bluestem.example.com")
    expect(sam.locator(".ct-p-status")).to_have_text("Needs confirming")
    expect(row.locator('.ct-person[data-contact="27"] .ct-p-status')).to_contain_text("Monthly until Dec 31")
    expect(row.locator(".ct-people-foot")).to_contain_text("3 people at Bluestem Logistics")
    expect(row.get_by_role("link", name="Add someone here")).to_have_attribute("href", "/bd/add.html?company=16")
    expect(toggle).to_be_focused()
    sam.locator(".ct-p-name").click()
    pg.wait_for_url(re.compile(r".*/bd/contact\.html\?id=28$"))
    expect(pg.locator("#cd-title")).to_have_text("Sam Achebe")
    # back on Contacts, a second click shuts the account again
    pg.go_back()
    acct(pg, 16).locator(".ct-acct-toggle").click()
    acct(pg, 16).locator(".ct-acct-toggle").click()
    expect(acct(pg, 16).locator(".ct-acct-toggle")).to_have_attribute("aria-expanded", "false")
    expect(acct(pg, 16).locator(".ct-person")).to_have_count(0)


def test_the_maintenance_tab_lists_companies_with_their_people(page_as, expect):
    """Q6 (replaces Q20): the same company rows as the BD tab."""
    _, pg = page_as("/bd/contacts.html", DEVON)
    pg.get_by_role("tab", name=re.compile("Maintenance")).click()
    expect(pg.locator("#ct-tab-maintenance")).to_have_attribute("aria-selected", "true")
    expect(accounts(pg)).to_have_count(1)
    assert names(pg) == ["Kaw Valley Cold Storage"]
    assert cells(acct(pg, 17)) == ["2 people", "Avery Quill", "Thu, Aug 20"]
    expect(acct(pg, 17).locator(".ct-flags")).to_contain_text("Due now")
    acct(pg, 17).locator(".ct-acct-toggle").click()
    assert opened_people(acct(pg, 17)) == ["Hal Brecken", "Nora Lindqvist"]
    expect(acct(pg, 17).locator('.ct-person[data-contact="31"] .ct-p-status')).to_contain_text("Due now")
    # Hal: not due (next on Dec 18), and, like everyone the seed did not confirm, "Needs confirming",
    # which outranks the plain "Maintenance" pill (BD's one status pill)
    assert acct(pg, 17).locator('.ct-person[data-contact="30"] .ct-p-status').inner_text().strip() == "Needs confirming"
    assert "tab=maintenance" in pg.url
    # arrow keys move between the tabs
    pg.locator("#ct-tab-maintenance").press("ArrowLeft")
    expect(pg.locator("#ct-tab-bd")).to_be_focused()
    expect(accounts(pg)).to_have_count(8)


def test_a_company_link_opens_that_account(page_as, expect):
    _, pg = page_as("/bd/contacts.html?company=11", EMERY, wait='.ct-acct.is-open[data-acct="11"]')
    assert opened_people(acct(pg, 11)) == ["D. Whitlow", "Rory Sandell"]
    expect(acct(pg, 11).locator('.ct-person[data-contact="33"] .ct-p-status')).to_have_text("Possible duplicate")
    assert pg.locator("#ct-list .ct-acct.is-open").count() == 1
    _, pg = page_as("/bd/contacts.html?company=17", EMERY, wait='.ct-acct.is-open[data-acct="17"]')
    expect(pg.locator("#ct-tab-maintenance")).to_have_attribute("aria-selected", "true")


# ── search (Q22, Q35) ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("words", ["(913) 555-0108", "+1 913 555 0108", "9135550108", "SAM.ACHEBE@Bluestem.Example.com",
                                   "sam ach"], ids=["dashed", "plus-one", "digits", "email-case", "name"])
def test_a_search_opens_the_account_and_highlights_the_person(page_as, expect, words):
    p, pg = page_as("/bd/contacts.html", AVERY)
    search(pg, words)
    expect(pg.locator("#ct-list .ct-person.is-match")).to_have_count(1)
    expect(accounts(pg)).to_have_count(1)
    expect(acct(pg, 16)).to_have_class(re.compile(r"\bis-open\b"))
    expect(pg.locator(".ct-person.is-match")).to_have_attribute("data-contact", "28")
    expect(pg.locator("#ct-count")).to_contain_text("Sam Achebe at Bluestem Logistics.")
    expect(pg.locator("#bd-live")).to_have_text("Sam Achebe at Bluestem Logistics.")
    sent = [r for r in p.requests if r.startswith("GET /api/bd/contacts/search")]
    assert sent and all(r.split("?")[0] == "GET /api/bd/contacts/search" for r in sent), "the term rides ?q= alone"
    assert "q=" in pg.url, "Back from a contact comes back to the search"


def test_a_maintenance_hit_opens_the_maintenance_tab(page_as, expect):
    _, pg = page_as("/bd/contacts.html", CASEY)
    search(pg, "785.555.0111")
    expect(pg.locator("#ct-tab-maintenance")).to_have_attribute("aria-selected", "true")
    expect(pg.locator(".ct-person.is-match")).to_have_attribute("data-contact", "31")
    expect(pg.locator("#ct-count")).to_contain_text("Nora Lindqvist at Kaw Valley Cold Storage.")


def test_an_account_name_search_shows_both_tabs_hits(page_as, expect):
    """"prairie ridge": both Prairie Ridge accounts on the BD tab, open, nobody highlighted."""
    _, pg = page_as("/bd/contacts.html", EMERY)
    search(pg, "prairie ridge")
    expect(accounts(pg)).to_have_count(2)
    assert names(pg) == ["Prairie Ridge Builders LLC", "Prairie Ridge Builders, Inc."]
    expect(pg.locator(".ct-person.is-match")).to_have_count(0)
    expect(pg.locator("#ct-count")).to_contain_text("2 accounts match.")
    pg.locator("#ct-count").get_by_role("button", name="Clear search").click()
    expect(accounts(pg)).to_have_count(8)
    expect(pg.locator("#ct-q")).to_have_value("")
    expect(pg.locator("#ct-q")).to_be_focused()


def test_no_hit_says_so_and_clear_brings_everyone_back(page_as, expect):
    _, pg = page_as("/bd/contacts.html", CASEY)
    search(pg, "kestrel wood zzz")
    expect(pg.locator("#ct-list .empty")).to_contain_text("No account or person matches “kestrel wood zzz”.")
    pg.locator('#ct-list [data-act="clear-search"]').click()
    expect(accounts(pg)).to_have_count(8)


def test_a_search_in_the_address_is_run_on_arrival(page_as, expect):
    _, pg = page_as("/bd/contacts.html?q=lena", DEVON, wait=".ct-person.is-match")
    expect(pg.locator(".ct-person.is-match")).to_have_attribute("data-contact", "27")
    expect(pg.locator("#ct-q")).to_have_value("lena")


# ── the "..." menu: make a maintenance account, move back to BD (2026-11-20) ──────────────────────
def test_the_menu_opens_from_the_button_by_keyboard_and_from_a_right_click(page_as, expect):
    _, pg = page_as("/bd/contacts.html", AVERY)
    more = acct(pg, 10).locator("[data-more]")
    expect(more).to_have_attribute("aria-label", "More for Prairie Ridge Builders LLC")
    more.focus()
    pg.keyboard.press("Enter")
    assert menu_acts(pg) == ["to-maintenance"]
    expect(pg.locator(".menu .menu-item")).to_have_text("Make maintenance account")
    expect(pg.locator(".menu .menu-item")).to_be_focused()
    pg.keyboard.press("Escape")
    expect(pg.locator(".menu")).to_have_count(0)
    expect(more).to_be_focused()
    pg.keyboard.press(" ")
    assert menu_acts(pg) == ["to-maintenance"]
    pg.keyboard.press("Escape")
    acct(pg, 10).locator(".ct-acct-name").click(button="right")
    assert menu_acts(pg) == ["to-maintenance"], "a right-click opens the same menu"
    pg.keyboard.press("Escape")
    expect(more).to_be_focused()
    pg.get_by_role("tab", name=re.compile("Maintenance")).click()
    acct(pg, 17).locator("[data-more]").click()
    assert menu_acts(pg) == ["to-bd"]
    expect(pg.locator(".menu .menu-item")).to_have_text("Move back to BD")


def test_make_maintenance_account_then_undo(page_as, expect):
    """Prairie Ridge Builders LLC: Dana moves; her open follow-up 302 comes off Avery's list (snoozed),
    nothing is pinned (her last follow-up was Nov 2). Undo puts the account and the call back."""
    _, pg = page_as("/bd/contacts.html", AVERY)
    acct(pg, 10).locator("[data-more]").click()
    pg.locator('.menu [data-act="to-maintenance"]').click()
    dlg = pg.locator(".dialog.is-open")
    expect(dlg.locator(".dialog-title")).to_have_text("Make Prairie Ridge Builders LLC a maintenance account?")
    expect(dlg.locator(".dialog-text")).to_have_text("1 person moves to the Maintenance tab.")
    dlg.get_by_role("button", name="Make maintenance account").click()
    expect(toasts(pg)).to_contain_text("Prairie Ridge Builders LLC is a maintenance account. 1 call came off this week's list.")
    expect(accounts(pg)).to_have_count(7)
    expect(pg.locator("#ct-tab-maintenance")).to_have_text(re.compile(r"Maintenance\s*2"))
    expect(pg.locator("#ct-tab-bd")).to_be_focused()
    week = api(pg, "/api/bd/week")["week"]
    assert [t["status"] for t in week["tasks"] if t["id"] == 302] == ["snoozed"]
    toasts(pg).get_by_role("button", name="Undo").click()
    expect(toasts(pg)).to_contain_text("Put back: Prairie Ridge Builders LLC is on the BD tab again.")
    expect(accounts(pg)).to_have_count(8)
    expect(pg.locator("#ct-tab-maintenance")).to_have_text(re.compile(r"Maintenance\s*1"))
    week = api(pg, "/api/bd/week")["week"]
    assert [t["status"] for t in week["tasks"] if t["id"] == 302] == ["open"]


def test_cancel_changes_nothing(page_as, expect):
    p, pg = page_as("/bd/contacts.html", EMERY)
    acct(pg, 16).locator("[data-more]").click()
    pg.locator('.menu [data-act="to-maintenance"]').click()
    dlg = pg.locator(".dialog.is-open")
    expect(dlg.locator(".dialog-title")).to_have_text("Make Bluestem Logistics a maintenance account?")
    expect(dlg.locator(".dialog-text")).to_have_text("3 people move to the Maintenance tab.")
    dlg.get_by_role("button", name="Cancel").click()
    expect(pg.locator(".dialog.is-open")).to_have_count(0)
    expect(acct(pg, 16).locator("[data-more]")).to_be_focused()
    assert not [r for r in p.requests if r.startswith("POST ")]


def test_a_manager_moves_a_company_back_to_bd(page_as, expect):
    _, pg = page_as("/bd/contacts.html?tab=maintenance", DEVON)
    expect(pg.locator("#ct-tab-maintenance")).to_have_attribute("aria-selected", "true")
    acct(pg, 17).locator("[data-more]").click()
    pg.locator('.menu [data-act="to-bd"]').click()
    dlg = pg.locator(".dialog.is-open")
    expect(dlg.locator(".dialog-title")).to_have_text("Move Kaw Valley Cold Storage back to BD?")
    expect(dlg.locator(".dialog-text")).to_have_text("2 people move to the BD tab.")
    dlg.get_by_role("button", name="Move back to BD").click()
    expect(toasts(pg)).to_contain_text("Kaw Valley Cold Storage is back on the BD tab.")
    expect(pg.locator("#ct-list .empty")).to_contain_text("No maintenance accounts yet.")
    expect(pg.locator("#ct-tab-bd")).to_have_text(re.compile(r"BD accounts\s*9"))


def test_the_assistant_has_no_menu_and_a_right_click_is_the_browsers(page_as, expect):
    """Q5: never the assistant. No "..." on any row, and a right-click opens no BD menu."""
    _, pg = page_as("/bd/contacts.html", CASEY)
    assert pg.locator("#ct-list [data-more]").count() == 0
    acct(pg, 10).locator(".ct-acct-name").click(button="right")
    pg.wait_for_timeout(200)
    assert pg.locator(".menu").count() == 0


# ── the import and the unknown calls, back on Contacts as BD had them ─────────────────────────────
def test_a_salesperson_imports_a_workbook_from_contacts(page_as, expect, tmp_path):
    """No menu for them (Past imports are on Admin, which is not theirs): Import goes to the file."""
    csv = tmp_path / "made up contacts.csv"
    csv.write_text(CSV, encoding="utf-8")
    _, pg = page_as("/bd/contacts.html", AVERY)
    expect(pg.locator("#ct-import")).to_be_visible()
    with pg.expect_file_chooser() as chooser:
        pg.locator("#ct-import").click()
    chooser.value.set_files(str(csv))
    dlg = pg.locator(".dialog.is-open")
    expect(dlg).to_contain_text("1 contact read, 0 possible duplicates.")
    expect(dlg).to_contain_text("This was a practice run. Nothing has been imported yet.")
    assert api(pg, "/api/bd/contacts?q=Rae%20Lindgren")["total"] == 0, "a practice run adds no one"
    dlg.get_by_role("button", name="Import now").click()
    expect(toasts(pg)).to_contain_text("Imported: 1 added, 0 updated.")
    expect(pg.locator(".dialog.is-open")).to_have_count(0)
    expect(accounts(pg)).to_have_count(9)
    assert "Tallgrass Dental" in names(pg)
    expect(pg.locator("#ct-import")).to_be_focused()


def test_the_import_menu_lists_upload_and_past_imports(page_as, expect):
    _, pg = page_as("/bd/contacts.html", CASEY)
    pg.locator("#ct-import").click()
    assert menu_acts(pg) == ["import-file", "imports"]
    menu = pg.locator(".menu")
    expect(menu.locator('[data-act="import-file"]')).to_contain_text("Upload a workbook")
    expect(menu.locator('[data-act="imports"]')).to_contain_text("Last one Thu, Oct 1")
    expect(menu.locator('[data-act="imports"]')).to_have_attribute("href", "/bd/admin.html#ad-s-imports")
    pg.keyboard.press("Escape")
    expect(pg.locator(".menu")).to_have_count(0)


def test_to_tidy_counts_and_its_cards_filter_the_list(page_as, expect):
    _, pg = page_as("/bd/contacts.html", CASEY)
    expect(pg.locator("#ct-tidy")).to_be_visible()
    expect(pg.locator('[data-tidy="dupes"] .ct-tidy-n')).to_have_text("1")
    expect(pg.locator('[data-tidy="confirm"] .ct-tidy-n')).to_have_text("10")
    expect(pg.locator('[data-tidy="unknown"] .ct-tidy-n')).to_have_text("1")
    pg.locator('[data-tidy="dupes"]').click()
    expect(pg.locator('[data-tidy="dupes"]')).to_have_attribute("aria-pressed", "true")
    expect(pg.locator('#ct-chips [data-chip="dupes"]')).to_have_attribute("aria-pressed", "true")
    assert names(pg) == ["Prairie Ridge Builders, Inc."]
    pg.locator('[data-tidy="dupes"]').click()                       # pressed again: lets go
    expect(accounts(pg)).to_have_count(8)
    pg.locator('[data-tidy="confirm"]').click()
    expect(accounts(pg)).to_have_count(7)                          # every BD account but Dana's


def test_the_unknown_call_card_opens_its_calls_with_attach_and_dismiss(page_as, expect):
    _, pg = page_as("/bd/contacts.html", CASEY)
    card = pg.locator('[data-tidy="unknown"]')
    card.click()
    expect(card).to_have_attribute("aria-expanded", "true")
    panel = pg.locator("#ct-unknown")
    expect(panel).to_be_visible()
    expect(panel).to_contain_text("913-555-0199 called us Tue, Nov 3, 4:42 PM")
    expect(panel).to_contain_text("“Caller asked about a quote for a shop floor.” · 2 min")
    attach = panel.get_by_role("link", name=re.compile("Attach to a contact"))
    expect(attach).to_have_attribute("href", "/bd/admin.html#ad-s-phone")
    panel.get_by_role("button", name=re.compile("Not a contact")).click()
    dlg = pg.locator(".dialog.is-open")
    expect(dlg).to_contain_text("The call from 913-555-0199 on Tue, Nov 3, 4:42 PM leaves this list for good.")
    dlg.get_by_role("button", name="Dismiss call").click()
    expect(toasts(pg)).to_contain_text("Call dismissed.")
    expect(pg.locator('[data-tidy="unknown"] .ct-tidy-n')).to_have_text("0")
    items = api(pg, "/api/bd/admin/unmatched-calls?status=all")["items"]
    assert [(c["id"], c["status"]) for c in items] == [(801, "dismissed")]


def test_to_tidy_shows_the_newest_three_calls_and_sends_the_rest_to_admin(env, page_as, expect):
    """BD's rule: three calls here, newest first; "See all 4 in Admin" for the rest."""
    _base, url, _b = env
    _, pg = page_as("/bd/contacts.html", EMERY, wait=None)
    for i, at in enumerate(("2026-11-02 15:00:00", "2026-11-04 14:00:00", "2026-11-01 15:00:00"), start=1):
        run_sql(url, "insert into unmatched_calls (provider, kind, direction, from_e164, occurred_at, duration_s, status)"
                     " values ('quo', 'call', 'in', %s, %s, 30, 'open')", ("+1913555015%d" % i, at + "+00:00"))
    pg.reload()
    card = pg.locator('[data-tidy="unknown"]')
    expect(card.locator(".ct-tidy-n")).to_have_text("4")
    card.click()
    calls = pg.locator("#ct-unknown .ct-call .ct-call-tel")
    expect(calls).to_have_text(["913-555-0152", "913-555-0199", "913-555-0151"])
    more = pg.locator("#ct-unknown").get_by_role("link", name=re.compile("See all 4 in Admin"))
    expect(more).to_have_attribute("href", "/bd/admin.html#ad-s-phone")


def test_attach_to_a_contact_lands_on_admins_unknown_calls(page_as, expect):
    """The assistant's way to her unknown calls now that Admin is not in her sidebar (#810)."""
    _, pg = page_as("/bd/contacts.html", CASEY)
    pg.locator('[data-tidy="unknown"]').click()
    pg.locator("#ct-unknown").get_by_role("link", name=re.compile("Attach to a contact")).click()
    pg.wait_for_url(re.compile(r".*/bd/admin\.html#ad-s-phone$"))
    expect(pg.locator("#ad-s-phone .ad-call")).to_have_count(1)
    expect(pg.locator("#ad-s-phone")).to_be_in_viewport()


# ── the cadence pill on a person (BD's "cadence pills on the rows", on the account's people) ──────
def test_a_person_carries_one_cadence_pill_and_only_when_it_says_something(page_as, expect):
    """Lena: an active override ("Monthly until Dec 31"); Nora: a due follow-up ("Due now"); Ines, Sam
    and Hal: none. One cadence pill at most per person."""
    _, pg = page_as("/bd/contacts.html?company=16", CASEY, wait='.ct-acct.is-open[data-acct="16"]')
    statuses = {int(pid): " ".join(t.split()) for pid, t in zip(
        acct(pg, 16).locator(".ct-person").evaluate_all("els => els.map(e => e.dataset.contact)"),
        acct(pg, 16).locator(".ct-p-status").all_inner_texts())}
    assert statuses == {29: "Needs confirming", 27: "Needs confirming Monthly until Dec 31", 28: "Needs confirming"}
    _, pg = page_as("/bd/contacts.html?company=17", CASEY, wait='.ct-acct.is-open[data-acct="17"]')
    statuses = [" ".join(t.split()) for t in acct(pg, 17).locator(".ct-p-status").all_inner_texts()]
    assert statuses == ["Needs confirming", "Needs confirming Due now"]


def test_a_cadence_change_on_the_contact_shows_on_its_row(page_as, expect):
    """Clearing Lena's override takes her pill off; an email logged for Nora (a follow-up) takes her
    Due now off."""
    _, pg = page_as("/bd/contacts.html", AVERY)
    pg.evaluate("""() => BDApi.patch("/api/bd/contacts/27", { cadence_override: null })""")
    pg.evaluate("""() => BDApi.post("/api/bd/contacts/31/interactions", { kind: "email", summary: "Sent the price sheet." })""")
    pg.goto(pg.url.split("/bd/")[0] + "/bd/contacts.html?company=16")
    acct(pg, 16).locator(".ct-person").first.wait_for(timeout=15000)
    expect(acct(pg, 16).locator('.ct-person[data-contact="27"] .ct-p-status')).to_have_text("Needs confirming")
    pg.goto(pg.url.split("/bd/")[0] + "/bd/contacts.html?company=17")
    acct(pg, 17).locator(".ct-person").first.wait_for(timeout=15000)
    expect(acct(pg, 17).locator('.ct-person[data-contact="31"] .ct-p-status')).to_have_text("Needs confirming")
    expect(acct(pg, 17).locator(".ct-flags")).not_to_contain_text("Due now")


# ── Add a contact (the second half of BD's test_e2e_contacts) ─────────────────────────────────────
# #808 moved Add contact and its own tests (test_bd_e2e_contact: the type-ahead, the duplicate warning,
# a phone already on a contact, a new company, what is missing, the assistant, the manager). These are
# the rest of BD's, on the seed: Bluestem Logistics has Lena, Sam and Ines; Dana's phone is
# 913-555-0101 (Prairie Ridge Builders LLC). The page's own link back is Contacts again (#810).
def open_add(page_as, email, path="/bd/add.html"):
    return page_as(path, email, wait="#add-form")


def pick_bluestem(pg, expect):
    pg.fill("#add-company", "Blue")
    opt = pg.locator("#add-company-list .add-option", has_text="Bluestem Logistics").first
    expect(opt).to_be_visible()
    opt.click()
    expect(pg.locator("#add-company")).to_have_value("Bluestem Logistics")
    expect(pg.locator("#add-company-check")).to_be_visible()


def added(pg, name):
    found = api(pg, "/api/bd/contacts?q=" + name.replace(" ", "%20"))
    assert found["total"] == 1, found
    return api(pg, "/api/bd/contacts/%d" % found["items"][0]["id"])["contact"]


def test_the_assistant_adds_someone_new_at_a_company_with_people(page_as, expect):
    _, pg = open_add(page_as, CASEY)
    expect(pg.locator(".add-back")).to_have_attribute("href", "/bd/contacts.html")
    pick_bluestem(pg, expect)
    dupe = pg.locator("#add-dupe")
    expect(dupe).to_contain_text("Lena Ortiz, Sam Achebe and Ines Varga already work at Bluestem Logistics. "
                                 "Is this person someone new?")
    expect(dupe.locator('[data-dup="new"]')).to_have_attribute("aria-checked", "true")
    pg.fill("#add-name", "Mia Thornton")
    expect(dupe).to_contain_text("Is Mia someone new?")
    pg.fill("#add-phone", "913-555-0182")
    expect(pg.locator("#add-city")).to_have_value("Lenexa")       # the company's city
    expect(pg.locator("#add-pills")).to_contain_text("Owner Avery Quill")
    pg.click("#add-submit")
    expect(toasts(pg)).to_contain_text("Mia Thornton added.")
    assert added(pg, "Mia")["duplicate_of"] is None, "Yes, someone new clears a same-company flag for the assistant"
    # the form is ready for the next person at the same company
    expect(pg.locator("#add-name")).to_have_value("")
    expect(pg.locator("#add-name")).to_be_focused()
    expect(pg.locator("#add-company")).to_have_value("Bluestem Logistics")
    expect(dupe).to_contain_text("Mia Thornton")


def test_maybe_keeps_the_flag_for_friday(page_as, expect):
    _, pg = open_add(page_as, CASEY)
    pick_bluestem(pg, expect)
    pg.click('#add-dupe [data-dup="same"]')
    expect(pg.locator("#add-pills")).to_contain_text("Possible duplicate")
    pg.fill("#add-name", "Mia Thornton")
    pg.click("#add-submit")
    expect(toasts(pg)).to_contain_text("Mia Thornton added.")
    assert added(pg, "Mia")["duplicate_of"] is not None


def test_a_known_phone_keeps_the_flag_whatever_the_choice(page_as, expect):
    """BD's 09 M7: the choice only answers the company question; a same phone is always kept."""
    _, pg = open_add(page_as, CASEY)
    pick_bluestem(pg, expect)
    pg.fill("#add-name", "Mia Thornton")
    pg.fill("#add-phone", "913.555.0101")                   # Dana Whitlow's, at another company
    pg.locator("#add-email").focus()
    expect(pg.locator("#add-phone-match")).to_contain_text("This phone belongs to Dana Whitlow.")
    expect(pg.locator('#add-dupe [data-dup="new"]')).to_have_attribute("aria-checked", "true")
    pg.click("#add-submit")
    expect(toasts(pg)).to_contain_text("Mia Thornton added.")
    assert added(pg, "Mia")["duplicate_of"]["contact_id"] == 21


def test_stage_set_under_change_lands_on_the_contact(page_as, expect):
    _, pg = open_add(page_as, CASEY)
    pg.fill("#add-company", "Brightwater Cider House")
    pg.locator("#add-name").focus()                  # leaving the box: a new company
    expect(pg.locator("#add-company-hint")).to_have_text("New company")
    expect(pg.locator("#add-dupe")).to_be_hidden()
    pg.fill("#add-name", "Eli Marchetti")
    pg.click('[data-act="defaults"]')
    expect(pg.locator("#add-more")).to_be_visible()
    pg.select_option("#add-stage", "Met")
    expect(pg.locator("#add-pills")).to_contain_text("Met")
    pg.click("#add-submit")
    expect(toasts(pg)).to_contain_text("Eli Marchetti added.")
    c = added(pg, "Eli")
    assert c["stage"] == "Met"
    assert c["company"]["name"] == "Brightwater Cider House"


def test_a_bad_phone_is_caught_and_nothing_is_saved(page_as, expect):
    _, pg = open_add(page_as, CASEY)
    pg.fill("#add-phone", "555-01")
    pg.locator("#add-email").focus()
    expect(pg.locator("#add-phone-err")).to_have_text("Enter a 10-digit phone number")
    pg.fill("#add-company", "Brightwater Cider House")
    pg.fill("#add-name", "Test Person")
    pg.click("#add-submit")
    expect(pg.locator("#add-phone")).to_be_focused()
    assert api(pg, "/api/bd/contacts?q=Test%20Person")["total"] == 0


def test_a_salespersons_add_keeps_the_same_company_flag(page_as, expect):
    """The server flags every same-company add; only the assistant or an admin may clear it."""
    _, pg = open_add(page_as, AVERY)
    pick_bluestem(pg, expect)
    pg.fill("#add-name", "Mia Thornton")
    pg.click("#add-submit")
    expect(toasts(pg)).to_contain_text("Mia Thornton added.")
    assert added(pg, "Mia")["duplicate_of"] is not None


def test_add_marks_company_as_required(page_as, expect):
    _, pg = open_add(page_as, CASEY)
    assert pg.locator("#add-name").get_attribute("required") is not None
    assert pg.locator("#add-company").get_attribute("aria-required") == "true"


def test_add_someone_here_opens_add_contact_on_that_company(page_as, expect):
    """BD's test_add_opens_with_a_company_from_the_link, from where the link now is: an opened account."""
    _, pg = page_as("/bd/contacts.html?company=16", CASEY, wait='.ct-acct.is-open[data-acct="16"]')
    acct(pg, 16).get_by_role("link", name="Add someone here").click()
    pg.locator("#add-form").wait_for(timeout=15000)
    expect(pg.locator("#add-company")).to_have_value("Bluestem Logistics")
    expect(pg.locator("#add-dupe")).to_contain_text("Lena Ortiz")
    expect(pg.locator("#add-name")).to_be_focused()


def open_more(pg, expect):
    pg.click('[data-act="defaults"]')
    expect(pg.locator("#add-more")).to_be_visible()


def record_posts(pg):
    pg.evaluate("""() => { window.__posts = []; const o = BDApi.post;
        BDApi.post = function (p, b) { window.__posts.push([p, b]); return o.apply(this, arguments); }; }""")


def contact_posts(pg):
    return [b for p, b in pg.evaluate("window.__posts") if p == "/api/bd/contacts"]


def test_a_bd_contact_has_the_cadence_note_and_no_number_a_maintenance_one_has_the_number(page_as, expect):
    """BD (the default): "Follows the BD cadence (quarterly)." and no live-talks field. Maintenance: the
    number field, starting at the maintenance default (3), and no note. Switching swaps them."""
    _, pg = open_add(page_as, CASEY)
    open_more(pg, expect)
    cad = pg.locator('#add-more [data-field="cadence"]')
    expect(cad.locator(".label")).to_have_text("Follow-up cadence")
    note = cad.locator("#add-freq-note")
    expect(note).to_have_text("Follows the BD cadence (quarterly).")
    expect(note).to_be_visible()
    expect(pg.locator("#add-freq")).to_be_hidden()
    pg.select_option("#add-category", "maintenance")
    expect(pg.locator("#add-freq")).to_be_visible()
    expect(pg.locator("#add-freq")).to_have_value("3")
    expect(pg.get_by_label("Live talks a year")).to_be_visible()
    expect(note).to_be_hidden()
    pg.select_option("#add-category", "bd")
    expect(note).to_be_visible()
    expect(pg.locator("#add-freq")).to_be_hidden()


def test_the_note_names_the_current_bd_cadence(page_as, expect):
    p, pg = open_add(page_as, EMERY)
    pg.evaluate("""() => BDApi.put("/api/bd/admin/settings", { bd_cadence: "monthly" })""")
    pg.reload()
    pg.locator("#add-form").wait_for(timeout=15000)
    open_more(pg, expect)
    expect(pg.locator("#add-more").get_by_text("Follows the BD cadence (monthly).", exact=True)).to_be_visible()


def test_switching_the_category_keeps_what_was_typed(page_as, expect):
    _, pg = open_add(page_as, CASEY)
    pick_bluestem(pg, expect)
    pg.fill("#add-name", "Mia Thornton")
    pg.fill("#add-phone", "913-555-0182")
    pg.fill("#add-city", "Lenexa, KS")
    open_more(pg, expect)
    pg.fill("#add-notes", "Met at the trade show.")
    pg.select_option("#add-stage", "Met")
    pg.select_option("#add-category", "maintenance")
    pg.fill("#add-freq", "8")
    pg.select_option("#add-category", "bd")
    pg.select_option("#add-category", "maintenance")
    for sel, want in (("#add-company", "Bluestem Logistics"), ("#add-name", "Mia Thornton"),
                      ("#add-phone", "913-555-0182"), ("#add-city", "Lenexa, KS"),
                      ("#add-notes", "Met at the trade show."), ("#add-stage", "Met"), ("#add-freq", "8")):
        expect(pg.locator(sel)).to_have_value(want)


def test_a_created_bd_contact_follows_the_bd_cadence_and_sends_no_number(page_as, expect):
    """No frequency_per_year is sent for a BD contact (the server refuses one); it is 4 (quarterly)."""
    p, pg = open_add(page_as, AVERY)
    record_posts(pg)
    pg.fill("#add-company", "Brightwater Cider House")
    pg.locator("#add-name").focus()
    pg.fill("#add-name", "Eli Marchetti")
    pg.click("#add-submit")
    expect(toasts(pg)).to_contain_text("Eli Marchetti added.")
    posts = contact_posts(pg)
    assert len(posts) == 1 and "frequency_per_year" not in posts[0], posts
    assert posts[0]["category"] == "bd"
    c = added(pg, "Eli")
    assert c["category"] == "bd" and c["frequency_per_year"] == 4
    pg.goto("%s/bd/contact.html?id=%d" % (p.base, c["id"]))
    pg.locator("#cd-title").wait_for()
    expect(pg.locator("#cd-cadence p.cd-cad-line")).to_have_text("Follow up quarterly.")


def test_a_created_maintenance_contact_keeps_the_number_typed(page_as, expect):
    p, pg = open_add(page_as, CASEY)
    record_posts(pg)
    pg.fill("#add-company", "Brightwater Cider House")
    pg.locator("#add-name").focus()
    pg.fill("#add-name", "Pat Newcomer")
    open_more(pg, expect)
    pg.select_option("#add-category", "maintenance")
    pg.click("#add-submit")
    expect(toasts(pg)).to_contain_text("Pat Newcomer added.")
    assert contact_posts(pg)[-1]["frequency_per_year"] == 3
    assert added(pg, "Pat")["frequency_per_year"] == 3
    pg.fill("#add-name", "Quinn Rowe")
    pg.select_option("#add-category", "maintenance")
    pg.fill("#add-freq", "6")
    pg.click("#add-submit")
    expect(toasts(pg)).to_contain_text("Quinn Rowe added.")
    assert contact_posts(pg)[-1]["frequency_per_year"] == 6
    c = added(pg, "Quinn")
    assert (c["category"], c["frequency_per_year"]) == ("maintenance", 6)
    pg.goto("%s/bd/contact.html?id=%d" % (p.base, c["id"]))
    pg.locator("#cd-title").wait_for()
    expect(pg.locator('#cd-cadence [data-act="cadence"]')).to_have_text("Change live talks a year")


# ── each role ─────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("email, chips, sorts, add, imp, tidy", [
    (AVERY, ["all", "mine"], ["name", "people"], True, True, False),
    (CASEY, ["all", "mine", "confirm", "never", "dupes"], ["name", "people", "last"], True, True, True),
    (DEVON, ["all", "mine", "confirm", "never"], ["name", "people", "last"], False, False, False),
    (EMERY, ["all", "mine", "confirm", "never", "dupes"], ["name", "people", "last"], True, True, True),
], ids=["salesperson", "assistant", "manager", "admin"])
def test_each_role_gets_its_chips_sorts_and_buttons(page_as, expect, email, chips, sorts, add, imp, tidy):
    """BD's rules, read from can: a salesperson working their own list gets All and Mine and no "Last
    live talk" sort (BD's no-overdue-pile rule); Possible duplicates for whoever clears one."""
    _, pg = page_as("/bd/contacts.html", email)
    assert pg.locator("#ct-chips [data-chip]").evaluate_all("els => els.map(e => e.dataset.chip)") == chips
    assert pg.locator("#ct-sort option").evaluate_all("els => els.map(e => e.value)") == sorts
    for sel, on in (("#ct-add", add), ("#ct-import", imp), ("#ct-tidy", tidy)):
        assert pg.locator(sel).is_visible() is on, sel


def test_mine_and_never_reached_and_the_sorts(page_as, expect):
    _, pg = page_as("/bd/contacts.html", EMERY)
    pg.locator('#ct-chips [data-chip="never"]').click()
    assert names(pg) == ["Bluestem Logistics", "Cedar Creek Concrete", "Cedar Crest Concrete",
                         "Cottonwood Sons Paving Co.", "Osage Plains Brewing", "Prairie Ridge Builders, Inc."]
    pg.locator('#ct-chips [data-chip="all"]').click()
    pg.select_option("#ct-sort", "people")
    assert names(pg)[:2] == ["Bluestem Logistics", "Prairie Ridge Builders, Inc."]
    pg.select_option("#ct-sort", "last")
    assert names(pg)[:2] == ["Prairie Ridge Builders LLC", "Cottonwood & Sons Paving"]
    _, pg = page_as("/bd/contacts.html", AVERY)
    pg.locator('#ct-chips [data-chip="mine"]').click()
    assert names(pg) == ["Bluestem Logistics", "Cedar Creek Concrete", "Cottonwood & Sons Paving",
                         "Prairie Ridge Builders LLC"]


@pytest.mark.parametrize("email", [AVERY, CASEY, DEVON, EMERY], ids=["salesperson", "assistant", "manager", "admin"])
def test_no_link_goes_to_a_bd_page_that_is_not_there(page_as, email):
    """Spec #802, page links, with an account open and the menus open too."""
    _, pg = page_as("/bd/contacts.html?company=16", email, wait='.ct-acct.is-open[data-acct="16"]')
    pg.locator("#tw-bd-sections a").first.wait_for(timeout=15000)
    seen = set(bd_links(pg))
    if pg.locator("#ct-import").is_visible():
        pg.locator("#ct-import").click()
        if pg.locator(".menu").count():
            seen |= set(bd_links(pg))
            pg.keyboard.press("Escape")
    assert "/bd/contact.html" in seen and "/bd/contacts.html" in seen
    assert seen <= MOVED_PAGES, sorted(seen - MOVED_PAGES)


# ── widths ────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("viewport", [PHONE, TABLET], ids=["390", "820"])
def test_the_list_stacks_on_a_narrow_screen(page_as, expect, viewport):
    _, pg = page_as("/bd/contacts.html?company=16", AVERY, viewport, wait='.ct-acct.is-open[data-acct="16"]')
    if viewport is PHONE:
        expect(pg.locator(".ct-colhead")).to_be_hidden()
        expect(acct(pg, 16).locator(".ct-c-owner")).to_be_hidden()
        expect(acct(pg, 16).locator(".ct-phone-only")).to_contain_text("3 people")
        sam = acct(pg, 16).locator('.ct-person[data-contact="28"]')
        expect(sam.locator(".ct-p-email")).to_be_hidden()
        call = sam.locator(".ct-p-call a.btn-call")
        expect(call).to_be_visible()
        assert call.get_attribute("aria-label") == "Call Sam Achebe, 913-555-0108"
        # on touch, the "..." button is the way in: a bottom sheet of one item
        acct(pg, 16).locator("[data-more]").click()
        expect(pg.locator(".menu.is-sheet")).to_be_visible()
        bb = acct(pg, 16).locator("[data-more]").bounding_box()
        assert bb["width"] >= 44 and bb["height"] >= 44, bb
        pg.keyboard.press("Escape")
    over = sideways(pg)
    assert over <= 1, "scrolls sideways by %dpx" % over


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["1280", "390"])
def test_nothing_scrolls_sideways(page_as, viewport):
    for email in (CASEY, EMERY):
        _, pg = page_as("/bd/contacts.html?company=11", email, viewport, wait='.ct-acct.is-open[data-acct="11"]')
        pg.locator('[data-tidy="unknown"]').click()
        pg.evaluate("() => document.fonts.ready.then(() => true)")
        assert sideways(pg) <= 1, (email, viewport)
