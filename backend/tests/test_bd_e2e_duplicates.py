"""Likely duplicate BD accounts on Contacts (/bd/contacts.html?filter=dupes) in a real Chromium, against
the live app (#811).

Every test starts from the FIXTURE SEED (backend/bd/ops/fixture_seed.py), put back before each test, on
a server whose business day is pinned to the seed's Wednesday, 2026-11-04. The expected values are
worked by hand from the seed, never read back from the page's own rules:

  The two likely pairs (cleaned names equal), Cottonwood first (cleaned-name order), lower id first:
    12 Cottonwood & Sons Paving      Marisa 23 (Avery's), a meeting Mon, Jun 15
    13 Cottonwood Sons Paving Co.    Theo 24 (Blair's)
        both have email at cottonwoodpaving.example.com (the hint)
    10 Prairie Ridge Builders LLC    Dana 21 (Avery's): an answered call Tue, Oct 20 (calls 101, 102),
                                     her open follow-up 302 on Avery's list
    11 Prairie Ridge Builders, Inc.  D. Whitlow 33 (flagged a possible duplicate of Dana, #810) and
                                     Rory 22, both Blair's
        both have email at prairieridge.example.com (the hint)
  The near miss: 14 Cedar Creek Concrete and 15 Cedar Crest Concrete share a phone (785-555-0105) and an
  email domain, but their names differ, so they are never a pair (a hint is never a pair alone).
  Merge offers to keep the account with more people, the first on a tie: Cottonwood & Sons Paving, and
  Prairie Ridge Builders, Inc. To tidy's Duplicates card: 1 flagged person + 2 pairs = 3.
  The filter's list: both accounts of each pair, and D. Whitlow's (11, already one of them).

What it proves, for the ticket: the assistant, the BD admin and the super admin see the seed's two
likely pairs and not the near miss; Merge with the name the merger picked; the survivor holds everyone,
each with their own owner, and a moved person's calls and follow-up go with them; the merged-away
account is gone from the list, search and Add contact's type-ahead; Undo (from the toast, and from
Recently merged after a reload) puts every answer back exactly, and a refused Undo leaves focus on the
merge's Undo in Recently merged; Keep separate asks first, then hides the pair after a reload; a salesperson and a manager see no filter, no notes and no buttons, and never ask the route;
phone width.

Runs in the browser job of ci.yml (tests/_bd_browser.py: the live app on a seeded BD test database,
sign-in faked only inside the test process).
"""
import re

import pytest

from _bd_browser import (DESKTOP, PHONE, Page, api, browser, focus_is_on_the_page, live_app_db, require_playwright,
                         reseed, sideways, toasts)

AVERY = "avery.quill@example.com"         # salesperson
CASEY = "casey.moret@example.com"         # assistant
DEVON = "devon.hale@example.com"          # manager
EMERY = "emery.stoll@example.com"         # admin
FRANKIE = "frankie.oduya@example.com"     # super admin

BD_NAMES = ["Bluestem Logistics", "Cedar Creek Concrete", "Cedar Crest Concrete", "Cottonwood & Sons Paving",
            "Cottonwood Sons Paving Co.", "Osage Plains Brewing", "Prairie Ridge Builders LLC",
            "Prairie Ridge Builders, Inc."]
PAIR_NOTES = [
    "Same account? “Cottonwood & Sons Paving” (1 person) and “Cottonwood Sons Paving Co.” (1 person). "
    "Both use the email domain cottonwoodpaving.example.com.",
    "Same account? “Prairie Ridge Builders LLC” (1 person) and “Prairie Ridge Builders, Inc.” (2 people). "
    "Both use the email domain prairieridge.example.com.",
]
FILTER_NAMES = ["Cottonwood & Sons Paving", "Cottonwood Sons Paving Co.", "Prairie Ridge Builders LLC",
                "Prairie Ridge Builders, Inc."]
DUPES_ROUTE = "/api/bd/contacts/accounts/duplicates"


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
        assert p.bd_errors() == [], p.bd_errors()
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


def pairs(pg):
    return pg.locator("#ct-dupes .ct-pair")


def notes(pg):
    return [" ".join(t.split()) for t in pg.locator("#ct-dupes .ct-pair-text").all_inner_texts()]


def dialog(pg):
    return pg.locator(".ct-merge-dlg")


def live_toast(pg):
    """The newest toast still on show (a toast that is leaving keeps its node for a moment)."""
    return pg.locator("#bd-toasts .toast:not(.toast-out)").last


def snapshot(pg):
    """Every answer a merge touches and Undo must put back: both tabs, the pairs and recent merges, the
    company list the type-ahead reads, and the moved people's own records."""
    return {
        "accounts": api(pg, "/api/bd/contacts/accounts"),
        "maintenance": api(pg, "/api/bd/contacts/accounts?category=maintenance"),
        "duplicates": api(pg, DUPES_ROUTE),
        "companies": api(pg, "/api/bd/companies"),
        "people": [api(pg, "/api/bd/contacts/%d" % cid) for cid in (21, 22, 23, 24, 33)],
    }


def open_filter(page_as, email, viewport=DESKTOP):
    p, pg = page_as("/bd/contacts.html?filter=dupes", email, viewport, wait="#ct-dupes .ct-pair")
    return p, pg


def merge(pg, expect, pair, keep_id=None):
    """Press the pair's Merge, pick the name of `keep_id` (the offer when None), and confirm."""
    pg.locator("#ct-merge-" + pair).click()
    expect(dialog(pg)).to_be_visible()
    if keep_id is not None:
        dialog(pg).locator('input[value="%d"]' % keep_id).check()
    dialog(pg).locator('[data-act="yes"]').click()


def type_ahead(pg, words):
    pg.locator("#add-company").fill(words)
    opts = pg.locator("#add-company-list .add-option")
    opts.last.wait_for()
    return opts


# ── who sees it ───────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("email", [CASEY, EMERY, FRANKIE], ids=["assistant", "admin", "super-admin"])
def test_the_two_likely_pairs_show_and_the_near_miss_does_not(page_as, expect, email):
    _, pg = page_as("/bd/contacts.html", email)
    expect(pg.locator('[data-tidy="dupes"] .ct-tidy-n')).to_have_text("3")
    pg.locator('#ct-chips [data-chip="dupes"]').click()
    expect(pairs(pg)).to_have_count(2)
    assert notes(pg) == PAIR_NOTES
    expect(pg.locator("#ct-merge-12-13")).to_have_text("Merge into Cottonwood & Sons Paving")
    expect(pg.locator("#ct-merge-10-11")).to_have_text("Merge into Prairie Ridge Builders, Inc.")
    expect(pg.locator("#ct-keep-12-13")).to_contain_text("Keep separate")
    assert names(pg) == FILTER_NAMES, "the near miss (Cedar Creek, Cedar Crest) is no pair"
    expect(pg.locator("#ct-dupes")).not_to_contain_text("Cedar")
    assert "filter=dupes" in pg.url


@pytest.mark.parametrize("email", [AVERY, DEVON], ids=["salesperson", "manager"])
def test_a_salesperson_and_a_manager_see_no_filter_no_notes_and_no_buttons(page_as, expect, email):
    """Even from a link that names the filter: every BD account, and the route is never asked."""
    p, pg = page_as("/bd/contacts.html?filter=dupes", email)
    expect(accounts(pg)).to_have_count(8)
    assert names(pg) == BD_NAMES
    expect(pg.locator('#ct-chips [data-chip="dupes"]')).to_have_count(0)
    expect(pg.locator("#ct-tidy")).to_be_hidden()
    expect(pg.locator("#ct-dupes")).to_be_hidden()
    expect(pg.locator('[data-act="merge"], [data-act="keep"], [data-act="unmerge"]')).to_have_count(0)
    assert pg.locator("#ct-dupes").inner_html() == ""
    assert not [r for r in p.requests if "/api/bd/contacts/accounts/duplicates" in r or "/merge" in r], p.requests


# ── Merge ─────────────────────────────────────────────────────────────────────────────────────────
def test_merge_into_the_offered_name_moves_the_people_with_their_owner_calls_and_follow_up(page_as, expect):
    """Prairie Ridge: the offer keeps Prairie Ridge Builders, Inc. (2 people), so Dana moves there. She
    stays Avery's, with her calls 101 and 102 and her open follow-up 302; the account now has 3 people,
    2 of them Blair's: "Blair Fenn +1", last live talk Dana's call, Tue, Oct 20."""
    _, pg = open_filter(page_as, CASEY)
    pg.locator("#ct-merge-10-11").click()
    expect(dialog(pg)).to_be_visible()
    expect(dialog(pg).locator('input[value="11"]')).to_be_checked()
    expect(dialog(pg).locator('input[value="11"]')).to_be_focused()
    expect(pg.locator("#ct-merge-line")).to_have_text("Move 1 person from Prairie Ridge Builders LLC into Prairie Ridge Builders, Inc.?")
    dialog(pg).locator('[data-act="yes"]').click()
    expect(live_toast(pg)).to_contain_text("Merged. Prairie Ridge Builders, Inc. now has 3 people.")
    expect(live_toast(pg).locator(".toast-act")).to_have_text("Undo")
    expect(pg.locator("#bd-live")).to_have_text("Merged. Prairie Ridge Builders, Inc. now has 3 people. Undo is available.")
    expect(acct(pg, 10)).to_have_count(0)
    expect(acct(pg, 11)).to_have_class(re.compile(r"\bis-open\b"))
    assert opened_people(acct(pg, 11)) == ["D. Whitlow", "Dana Whitlow", "Rory Sandell"]
    assert cells(acct(pg, 11)) == ["3 people", "Blair Fenn +1", "Tue, Oct 20"]
    expect(pairs(pg)).to_have_count(1)
    expect(pg.locator("#ct-merged-h")).to_have_text("Recently merged")
    expect(pg.locator("#ct-dupes .ct-merged-what")).to_have_text(["Prairie Ridge Builders LLC into Prairie Ridge Builders, Inc."])
    expect(pg.locator("#ct-dupes .ct-merged-sub")).to_have_text([re.compile(r"^1 person moved · .+ by Casey Moret$")])
    expect(pg.locator("#ct-dupes .ct-unmerge")).to_be_focused()
    dana = api(pg, "/api/bd/contacts/21")
    assert (dana["contact"]["company"]["id"], dana["contact"]["owner"]["id"], dana["open_task"]["id"]) == (11, 1, 302)
    history = api(pg, "/api/bd/contacts/21/interactions")["items"]
    assert sorted(i["interaction"]["id"] for i in history if i["type"] == "interaction") == [101, 102]
    # the merged-away account is gone from the BD tab with the filter off too
    pg.locator('#ct-chips [data-chip="all"]').click()
    expect(accounts(pg)).to_have_count(7)
    assert names(pg) == [n for n in BD_NAMES if n != "Prairie Ridge Builders LLC"]


def test_merge_keeps_the_name_the_merger_picked(page_as, expect):
    """Cottonwood: the offer is Cottonwood & Sons Paving (a tie, the first); Casey picks the other name,
    so Cottonwood Sons Paving Co. stays and Marisa moves to it. Avery and Blair have one person each;
    Marisa's meeting Mon, Jun 15 is the live talk, so "Avery Quill +1"."""
    _, pg = open_filter(page_as, CASEY)
    pg.locator("#ct-merge-12-13").click()
    expect(dialog(pg).locator('input[value="12"]')).to_be_checked()
    expect(pg.locator("#ct-merge-line")).to_have_text("Move 1 person from Cottonwood Sons Paving Co. into Cottonwood & Sons Paving?")
    dialog(pg).locator('input[value="13"]').check()
    expect(pg.locator("#ct-merge-line")).to_have_text("Move 1 person from Cottonwood & Sons Paving into Cottonwood Sons Paving Co.?")
    dialog(pg).locator('[data-act="yes"]').click()
    expect(live_toast(pg)).to_contain_text("Merged. Cottonwood Sons Paving Co. now has 2 people.")
    expect(acct(pg, 12)).to_have_count(0)
    assert opened_people(acct(pg, 13)) == ["Marisa Cole", "Theo Banks"]
    assert cells(acct(pg, 13)) == ["2 people", "Avery Quill +1", "Mon, Jun 15"]
    assert [a["name"] for a in api(pg, "/api/bd/contacts/accounts")["items"] if a["id"] in (12, 13)] == [
        "Cottonwood Sons Paving Co."]
    marisa = api(pg, "/api/bd/contacts/23")["contact"]
    assert (marisa["company"]["id"], marisa["owner"]["id"]) == (13, 1)


def test_the_merged_away_account_leaves_search_and_the_type_ahead(page_as, expect):
    p, pg = page_as("/bd/add.html", CASEY, wait="#add-form")
    expect(type_ahead(pg, "cottonwood")).to_have_count(3)          # both accounts and "Add ... as a new company"
    p.close()
    _, pg = open_filter(page_as, CASEY)
    merge(pg, expect, "12-13")
    expect(live_toast(pg)).to_contain_text("Merged. Cottonwood & Sons Paving now has 2 people.")
    # search: the name finds the survivor alone, with both people (their emails hold "cottonwood" too),
    # and Theo is found at it
    pg.locator('#ct-chips [data-chip="all"]').click()
    pg.fill("#ct-q", "cottonwood")
    expect(pg.locator("#ct-count")).to_contain_text("1 account and 2 people match.")
    assert names(pg) == ["Cottonwood & Sons Paving"]
    pg.fill("#ct-q", "theo")
    expect(pg.locator("#ct-count")).to_contain_text("Theo Banks at Cottonwood & Sons Paving.")
    expect(pg.locator(".ct-person.is-match")).to_have_count(1)
    expect(pg.locator(".ct-person.is-match")).to_have_attribute("data-contact", "24")
    # Add contact's type-ahead offers the survivor alone
    pg.goto(pg.url.split("/bd/")[0] + "/bd/add.html")
    pg.locator("#add-form").wait_for()
    opts = type_ahead(pg, "cottonwood")
    expect(opts).to_have_count(2)
    expect(opts.nth(0)).to_contain_text("Cottonwood & Sons Paving")
    expect(opts.nth(0)).to_contain_text("Olathe · 2 people")
    expect(opts.nth(1)).to_have_text("Add “cottonwood” as a new company")


# ── Undo ──────────────────────────────────────────────────────────────────────────────────────────
def test_undo_from_the_toast_puts_everything_back_exactly(page_as, expect):
    _, pg = open_filter(page_as, CASEY)
    before = snapshot(pg)
    merge(pg, expect, "10-11", keep_id=10)
    expect(live_toast(pg)).to_contain_text("Merged. Prairie Ridge Builders LLC now has 3 people.")
    assert opened_people(acct(pg, 10)) == ["D. Whitlow", "Dana Whitlow", "Rory Sandell"]
    live_toast(pg).locator(".toast-act").click()
    expect(live_toast(pg)).to_contain_text(
        "Put back: Prairie Ridge Builders, Inc. and Prairie Ridge Builders LLC are two accounts again.")
    expect(pairs(pg)).to_have_count(2)
    expect(pg.locator("#ct-dupes .ct-merged-row")).to_have_count(0)
    expect(pg.locator("#ct-merge-10-11")).to_be_focused()
    assert notes(pg) == PAIR_NOTES
    assert names(pg) == FILTER_NAMES
    assert snapshot(pg) == before


def test_undo_from_recently_merged_after_a_reload(page_as, expect):
    """No time limit: the toast is long gone after a reload, and Recently merged still offers Undo. Its
    button is busy while the request runs."""
    _, pg = open_filter(page_as, EMERY)
    before = snapshot(pg)
    merge(pg, expect, "12-13")
    expect(live_toast(pg)).to_contain_text("Merged. Cottonwood & Sons Paving now has 2 people.")
    pg.reload()
    pg.locator("#ct-dupes .ct-merged-row").wait_for(timeout=15000)
    expect(pg.locator("#bd-toasts .toast:not(.toast-out)")).to_have_count(0)
    expect(pairs(pg)).to_have_count(1)
    expect(pg.locator("#ct-dupes .ct-merged-what")).to_have_text(["Cottonwood Sons Paving Co. into Cottonwood & Sons Paving"])
    pg.evaluate("""() => { const b = document.querySelector('#ct-dupes .ct-unmerge'); window.__busy = [];
        new MutationObserver(() => window.__busy.push(b.disabled && b.getAttribute('aria-busy')))
          .observe(b, { attributes: true }); }""")
    pg.locator("#ct-dupes .ct-unmerge").click()
    expect(live_toast(pg)).to_contain_text(
        "Put back: Cottonwood Sons Paving Co. and Cottonwood & Sons Paving are two accounts again.")
    expect(pairs(pg)).to_have_count(2)
    expect(pg.locator("#ct-merged-h")).to_have_count(0)
    assert names(pg) == FILTER_NAMES
    assert snapshot(pg) == before
    assert "true" in pg.evaluate("() => window.__busy"), "Undo in Recently merged was never busy"


def test_a_refused_undo_from_the_toast_leaves_focus_on_the_merges_undo(page_as, expect):
    """Cottonwood merged with the offer kept (Theo moves to 12); Theo is then moved to Bluestem (16), so
    Undo can no longer put him back. The toast's Undo is refused (409) and nothing changes; focus
    lands on that merge's Undo in Recently merged, which is free to press again, never on the page."""
    p, pg = open_filter(page_as, CASEY)
    merge(pg, expect, "12-13")
    expect(live_toast(pg)).to_contain_text("Merged. Cottonwood & Sons Paving now has 2 people.")
    moved = pg.evaluate("() => BDApi.patch('/api/bd/contacts/24', { company: { id: 16 } })"
                        ".then(r => r.contact.company.id)")
    assert moved == 16
    unmerge = pg.locator("#ct-dupes .ct-unmerge")
    expect(unmerge).to_have_count(1)
    merge_id = unmerge.get_attribute("data-id")
    live_toast(pg).locator(".toast-act").click()
    expect(live_toast(pg)).to_contain_text("Something changed since this merge, so it can't be undone.")
    expect(pg.locator("#ct-unmerge-" + merge_id)).to_be_focused()
    expect(pg.locator("#ct-unmerge-" + merge_id)).to_be_enabled()
    assert not pg.locator("#ct-unmerge-" + merge_id).get_attribute("aria-busy")
    assert focus_is_on_the_page(pg)
    assert [a["id"] for a in api(pg, "/api/bd/contacts/accounts")["items"] if a["id"] in (12, 13)] == [12]
    assert p.bd_errors() == [(409, "/api/bd/contacts/accounts/merges/%s/undo" % merge_id)]
    p.http.clear()                                                 # the one refusal this test asked for


def test_one_undo_closes_the_other(page_as, expect):
    """Undo from Recently merged takes the toast's Undo away, so the merge cannot be undone twice."""
    _, pg = open_filter(page_as, CASEY)
    merge(pg, expect, "12-13")
    toast = live_toast(pg)
    expect(toast).to_contain_text("Merged. Cottonwood & Sons Paving now has 2 people.")
    pg.locator("#ct-dupes .ct-unmerge").click()
    expect(live_toast(pg)).to_contain_text("are two accounts again.")
    expect(pg.locator("#bd-toasts .toast:not(.toast-out) .toast-act")).to_have_count(0)


# ── Keep separate ─────────────────────────────────────────────────────────────────────────────────
def test_keep_separate_asks_first_and_cancel_changes_nothing(page_as, expect):
    """Keep separate cannot be undone on the page, so it asks; Cancel (or Escape) keeps both notes and
    sends nothing, and focus goes back to the button."""
    p, pg = open_filter(page_as, CASEY)
    pg.locator("#ct-keep-10-11").click()
    box = pg.locator(".dialog[role=alertdialog]")
    expect(box).to_be_visible()
    expect(box.locator(".dialog-title")).to_have_text("Keep as two accounts?")
    expect(box.locator(".dialog-text")).to_have_text(
        "Prairie Ridge Builders LLC and Prairie Ridge Builders, Inc. won't be suggested as one account again.")
    expect(box.locator('[data-act="yes"]')).to_have_text("Keep separate")
    box.locator('[data-act="no"]').click()
    expect(box).to_have_count(0, timeout=3000)
    expect(pg.locator("#ct-keep-10-11")).to_be_focused()
    pg.locator("#ct-keep-10-11").click()
    expect(box).to_be_visible()
    pg.keyboard.press("Escape")
    expect(box).to_have_count(0, timeout=3000)
    expect(pairs(pg)).to_have_count(2)
    assert not [r for r in p.requests if r.endswith("/duplicates/keep")], p.requests
    assert len(api(pg, DUPES_ROUTE)["items"]) == 2


def test_keep_separate_hides_the_pair_for_good(page_as, expect):
    """Prairie Ridge kept as two: one pair left, To tidy's card 1 + 1 = 2, and the filter still lists
    Prairie Ridge Builders, Inc. for D. Whitlow (a flagged person, #810), not Prairie Ridge Builders LLC."""
    _, pg = open_filter(page_as, CASEY)
    pg.locator("#ct-keep-10-11").click()
    pg.locator(".dialog[role=alertdialog] [data-act='yes']").click()
    expect(live_toast(pg)).to_contain_text("Kept as two accounts: Prairie Ridge Builders LLC and Prairie Ridge Builders, Inc.")
    expect(live_toast(pg).locator(".toast-act")).to_have_count(0)
    expect(pairs(pg)).to_have_count(1)
    expect(pg.locator("#ct-merge-12-13")).to_be_focused()
    pg.reload()
    pg.locator("#ct-dupes .ct-pair").first.wait_for(timeout=15000)
    expect(pairs(pg)).to_have_count(1)
    assert notes(pg) == PAIR_NOTES[:1]
    expect(pg.locator('[data-tidy="dupes"] .ct-tidy-n')).to_have_text("2")
    assert names(pg) == ["Cottonwood & Sons Paving", "Cottonwood Sons Paving Co.", "Prairie Ridge Builders, Inc."]
    expect(accounts(pg)).to_have_count(3)
    pg.locator('#ct-chips [data-chip="all"]').click()
    expect(accounts(pg)).to_have_count(8)                          # nothing merged: both accounts stay


# ── widths ────────────────────────────────────────────────────────────────────────────────────────
def test_on_a_phone_merge_is_a_bottom_sheet_and_nothing_scrolls_sideways(page_as, expect):
    _, pg = open_filter(page_as, CASEY, PHONE)
    pg.evaluate("() => document.fonts.ready.then(() => true)")
    assert sideways(pg) <= 1, "the notes scroll sideways"
    for b in (pg.locator("#ct-merge-12-13"), pg.locator("#ct-keep-12-13")):
        box = b.bounding_box()
        assert box["height"] >= 44, box                            # a finger-sized target
    pg.locator("#ct-merge-12-13").click()
    expect(dialog(pg)).to_be_visible()
    pg.wait_for_timeout(300)                                       # the sheet's slide-in
    box = dialog(pg).bounding_box()
    assert abs(box["y"] + box["height"] - PHONE["height"]) <= 1 and box["width"] >= PHONE["width"] - 1, box
    pg.keyboard.press("Escape")
    expect(dialog(pg)).to_have_count(0, timeout=3000)
    expect(pg.locator("#ct-merge-12-13")).to_be_focused()
    expect(pairs(pg)).to_have_count(2)                             # Cancel changes nothing
    merge(pg, expect, "12-13", keep_id=13)
    expect(toasts(pg)).to_contain_text("Merged. Cottonwood Sons Paving Co. now has 2 people.")
    expect(acct(pg, 13).locator(".ct-phone-only")).to_contain_text("2 people")
    assert sideways(pg) <= 1, "Recently merged scrolls sideways"
    live_toast(pg).locator(".toast-act").click()
    expect(pairs(pg)).to_have_count(2)
    assert names(pg) == FILTER_NAMES
