"""This Week and the after-a-call sheet in a real Chromium, against the live app (#807).

BD's test_e2e_week, moved with the page and rewritten for the live app: BD's mock data is gone, so
every test starts from the FIXTURE SEED (backend/bd/ops/fixture_seed.py), put back before each test,
on a server whose business day is pinned to the seed's Wednesday, 2026-11-04. The expected values
are worked by hand from the seed, never read back from the page's own rules:

  Avery Quill (salesperson, id 1), the week of Mon, Nov 2 - Sun, Nov 8, Friday batch 201:
    301 Hal Brecken, Kaw Valley Cold Storage  maintenance, open   -> Next up, "Maintenance . due"
    302 Dana Whitlow, Prairie Ridge Builders  follow-up, open     -> "Rest of your 10"; Key account
                                                                     (importance 3); first other
                                                                     reason "Quote out 3 weeks"
    303 Priya Nandan, Cedar Creek Concrete    new, done Nov 3     -> Done; her newest call since
                                                                     Monday is 104, no answer, Nov 3
  So: "1 of 2 done" (the maintenance task is not one of the 10), "Due now: 1 maintenance
  follow-up", "1 call to go this week.", meetings "0 of 5" (settings' weekly goal).
  Pace: 4 of 29 touches this year, 24.5 due by today -> 14%, 20 behind (half up), 8 weeks left ->
  "About 3 extra calls a week" (20 / 8 rounded up).
  Give Me 10 More adds Lena Ortiz and Marisa Cole (Avery's, not on the week) as "2 more (to get
  ahead)", and Nora Lindqvist as a second due maintenance follow-up; asked again: 409.
  Blair Fenn (salesperson, id 2): Rory Sandell open, Sam Achebe taken off.

What it proves, for the ticket: the week draws and acts (done, Not this week, reopen, not the right
person, ten more); a call logged from the call sheet shows in that contact's history; a call's
outcome changed after a touch saves; the wrong-person fallback with no task confirms the contact;
each task's contact detail loads (the done line's outcome and the tray); the recommendation and
follow-up buttons meet the 503 placeholders and say "not built yet"; a BD admin runs the weekly
batch from This Week; names are not links and no BD page links to a page that has not moved; the
assistant lands on the Contacts-is-coming page; desktop and phone width.

Runs in the browser job of ci.yml (tests/_bd_browser.py: the live app on a seeded BD test database,
sign-in faked only inside the test process).
"""
import re
import urllib.request

import pytest

from _bd_browser import DESKTOP, PHONE, TABLET, Page, browser, live_app_db, require_playwright, reseed, run_sql

AVERY = "avery.quill@example.com"
CASEY = "casey.moret@example.com"         # assistant
DEVON = "devon.hale@example.com"          # manager
EMERY = "emery.stoll@example.com"         # admin

HAL, DANA, PRIYA = 301, 302, 303          # Avery's tasks
HAL_C, DANA_C, PRIYA_C = 30, 21, 25

NOT_BUILT = "This part is not built yet (Phase 5)."
MAINT_PILL = "Maintenance · due"
STAYS_LINE = "Stays on your list until you log a call, meeting, email or text."


@pytest.fixture(scope="module")
def env():
    with live_app_db() as (base, url), browser() as b:
        yield base, url, b


@pytest.fixture
def page_as(env):
    base, url, b = env
    reseed(url)
    opened = []

    def _open(path, email, viewport=DESKTOP):
        p = Page(b, base, viewport, email=email)
        opened.append(p)
        pg = p.open_signed_in(path)
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


# ── helpers ──────────────────────────────────────────────────────────────────────────────────────
def wait_week(pg):
    """The week is drawn and every contact detail it asked for has landed (no skeleton left)."""
    pg.wait_for_selector("#summary .wk-progress-in", timeout=15000)
    pg.wait_for_function("() => !document.querySelector('#main .skeleton')", timeout=15000)


def api(pg, path):
    return pg.evaluate("p => BDApi.get(p)", path)


def sheet(pg):
    return pg.locator("#call-sheet")


def toasts(pg):
    return pg.locator("#bd-toasts")


def node(pg, task_id):
    return pg.locator('[data-task="%s"]' % task_id)


def call(nd):
    nd.locator('[data-act="call"]').first.click()      # a tel: link; its handler opens the sheet


def menu_acts(pg):
    pg.locator(".menu").wait_for()
    return pg.locator(".menu .menu-item").evaluate_all("els => els.map(e => e.dataset.act)")


def choose(pg, nd, act):
    nd.locator('[data-act="more"]:visible').first.click()
    pg.locator('.menu [data-act="%s"]' % act).click()


def summary(pg):
    return re.sub(r"\s+", " ", pg.inner_text("#summary")).strip()


def history(pg, cid):
    """The contact's logged interactions, newest first, from the interactions route."""
    items = api(pg, "/api/bd/contacts/%d/interactions" % cid)["items"]
    return [x["interaction"] for x in items if x["type"] == "interaction"]


# ── the week as the seed makes it ───────────────────────────────────────────────────────────────
def test_the_week_reads_like_the_fixture_seed(page_as, expect):
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    assert re.fullmatch(r"Good (morning|afternoon|evening), Avery", pg.inner_text("#wk-greeting").strip())
    assert pg.locator("#wk-eyebrow .hide-phone").text_content() == "This Week · Mon, Nov 2 - Sun, Nov 8"
    assert pg.inner_text("#week-sub") == "1 call to go this week."
    s = summary(pg)
    for words in ("1 of 2 done", "Due now: 1 maintenance follow-up", "Meetings this week: 0 of 5", "14%",
                  "of the way to 29", "20 behind. About 3 extra calls a week catches up.",
                  "4 of 29 this year · 8 weeks left"):
        assert words in s, (words, s)
    assert pg.locator("[data-dot-task]").count() == 2, "the maintenance task is not one of the 10"
    # Next up: the pinned maintenance follow-up, which cannot be taken off by hand.
    nxt = pg.locator("#wk-next")
    assert nxt.locator("[data-task]").get_attribute("data-task") == str(HAL)
    assert pg.inner_text("#wk-next-name") == "Hal Brecken"
    expect(nxt).to_contain_text(MAINT_PILL)
    expect(nxt).to_contain_text(STAYS_LINE)
    assert nxt.locator('[data-act="snooze"], [data-act="done"]').count() == 0
    # The rest of the 10, and what is done, with the done line read from Priya's own history.
    dana = pg.locator('#wk-rest [data-task="%d"]' % DANA)
    assert dana.get_attribute("data-status") == "open"
    assert re.sub(r"\s+", " ", dana.inner_text()).count("Key account") == 1
    expect(dana.locator(".wk-reason")).to_have_text("Quote out 3 weeks")
    priya = pg.locator('#wk-done [data-task="%d"][data-status="done"]' % PRIYA)
    expect(priya.locator(".wk-outcome")).to_have_text("No answer · Tue, Nov 3")
    assert priya.locator('[data-act="reopen"]').count() == 0, "Undo is offered only on the day it was done"
    # Priya's missed call is waiting for a decision in the tray (her contact detail has loaded).
    expect(pg.locator("#wk-tray .wk-tray-head .count")).to_have_text(re.compile(r"^1"))
    expect(pg.locator('#wk-tray .wk-tray-item[data-contact="%d"]' % PRIYA_C)).to_contain_text("Send a follow-up?")
    assert pg.locator("#owner-field").is_hidden(), "a salesperson has no picker"


def test_names_are_not_links_and_no_link_goes_to_a_bd_page_that_has_not_moved(page_as):
    p, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    links = pg.locator("#main a[href]").evaluate_all("els => els.map(e => e.getAttribute('href'))")
    assert links and all(h.startswith("tel:") for h in links), links
    choose_menu = pg.locator('#wk-rest [data-task="%d"] [data-act="more"]' % DANA)
    choose_menu.click()
    acts = menu_acts(pg)
    assert acts == ["snooze", "log-meeting", "nrp", "done"], acts
    assert pg.locator(".menu a").count() == 0, "no menu item links to a contact page that has not moved"
    pg.keyboard.press("Escape")
    # Every address under /bd/ the rendered page links to (the sidebar included) is a page that is here.
    bd = pg.evaluate("() => [...new Set([...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href'))"
                     ".filter(h => h.startsWith('/bd/')))]")
    assert bd, "the sidebar's BD CRM row links to /bd/"
    for href in bd:
        with urllib.request.urlopen(p.base + href, timeout=10) as r:      # pages need no sign-in to be served
            assert r.status == 200, (href, r.status)


# ── a call from the call sheet ──────────────────────────────────────────────────────────────────
def test_a_call_logged_from_this_week_shows_in_the_contacts_history(page_as, expect):
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    before = len(history(pg, DANA_C))
    url = pg.url
    call(node(pg, DANA))
    expect(sheet(pg)).to_be_visible()
    assert pg.url == url, "a tel: link must not navigate the page"
    assert sheet(pg).locator('[data-outcome][aria-pressed="true"]').count() == 0, "nothing is preselected"
    sheet(pg).locator('[data-outcome="answered"]').click()
    expect(sheet(pg).locator("[data-saved]")).to_contain_text("Saved as Talked. This one is done.")
    calls = history(pg, DANA_C)
    assert len(calls) == before + 1
    assert (calls[0]["kind"], calls[0]["outcome"]) == ("call", "answered")
    assert calls[0]["occurred_at"].startswith("2026-11-04")
    # The week follows: Dana is done (a live talk), the 10 are all done, and the pace counts one more.
    done = pg.locator('#wk-done [data-task="%d"][data-status="done"]' % DANA)
    expect(done.locator(".wk-outcome")).to_have_text("Talked · Wed, Nov 4")
    expect(pg.locator("#week-count")).to_have_text("All 2 done")
    expect(pg.locator("#pace-caption")).to_have_text("5 of 29 this year · 8 weeks left")
    # The suggested step's Confirm meets the 503 placeholder and says so, as BD does today.
    expect(sheet(pg).locator("[data-rec]")).to_contain_text("Usual rule")
    sheet(pg).locator('.call-bar [data-act="rec-confirm"]').click()
    expect(sheet(pg).locator(".call-bar-err")).to_have_text(NOT_BUILT)
    expect(sheet(pg)).to_be_visible()


def test_changing_a_calls_outcome_after_a_touch_saves(page_as, expect):
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    kept = api(pg, "/api/bd/contacts/%d" % DANA_C)["contact"]
    assert (kept["next_step"], kept["next_step_date"]) == ("Send the epoxy sample board", "2026-11-06")
    call(node(pg, DANA))
    sheet(pg).locator('[data-outcome="answered"]').click()
    expect(sheet(pg).locator("[data-saved]")).to_contain_text("Talked")
    expect(pg.locator("#pace-caption")).to_have_text("5 of 29 this year · 8 weeks left")
    sheet(pg).locator('[data-act="change-outcome"]').click()
    sheet(pg).locator('[data-outcome="no_answer"]').click()
    expect(sheet(pg).locator("[data-saved]")).to_contain_text("Saved as No answer.")
    # Saved: the same call, now no answer; no longer a touch; the contact's step is as it was.
    calls = history(pg, DANA_C)
    assert (calls[0]["kind"], calls[0]["outcome"]) == ("call", "no_answer")
    back = api(pg, "/api/bd/contacts/%d" % DANA_C)["contact"]
    assert (back["next_step"], back["next_step_date"], back["promised_date"]) == \
        ("Send the epoxy sample board", "2026-11-06", "2026-11-05")
    expect(pg.locator("#pace-caption")).to_have_text("4 of 29 this year · 8 weeks left")
    expect(pg.locator('#wk-done [data-task="%d"] .wk-outcome' % DANA)).to_have_text("No answer · Wed, Nov 4")
    # Swapping the suggested step is the part not built yet: said, and the outcome stays saved.
    expect(sheet(pg).locator(".call-bar-err")).to_have_text(NOT_BUILT)


def test_a_voicemail_offers_a_follow_up_whose_draft_is_not_built_yet(page_as, expect):
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    call(node(pg, DANA))
    sheet(pg).locator('[data-outcome="voicemail"]').click()
    expect(sheet(pg).locator("[data-saved]")).to_contain_text("Saved as Voicemail.")
    sms = sheet(pg).locator('[data-act="fu-pick"][data-ch="sms"]')
    expect(sms).to_be_visible()
    sms.click()
    expect(sheet(pg).locator("[data-fu] .field-error")).to_have_text(NOT_BUILT)
    expect(pg.locator("#pace-caption")).to_have_text("4 of 29 this year · 8 weeks left")
    calls = history(pg, DANA_C)
    assert (calls[0]["kind"], calls[0]["outcome"]) == ("voicemail", "voicemail"), "a voicemail is its own kind"


def test_not_now_before_a_tap_saves_nothing(page_as, expect):
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    before = len(history(pg, HAL_C))
    call(pg.locator("#wk-next"))
    expect(sheet(pg)).to_be_visible()
    sheet(pg).locator('[data-act="not-now"]').click()
    expect(toasts(pg)).to_contain_text("Nothing saved.")
    expect(sheet(pg)).to_be_hidden()
    assert len(history(pg, HAL_C)) == before
    assert node(pg, HAL).get_attribute("data-status") == "open"


def test_the_sheet_keeps_focus_inside_and_gives_it_back(page_as, expect):
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    link = pg.locator('#wk-next [data-act="call"]')
    link.focus()
    call(pg.locator("#wk-next"))
    expect(sheet(pg)).to_be_visible()
    for _ in range(8):
        pg.keyboard.press("Tab")
        assert pg.evaluate("() => !!document.activeElement.closest('#call-sheet')"), "focus left the sheet"
    pg.keyboard.press("Escape")
    expect(sheet(pg)).to_be_hidden()
    assert pg.evaluate("() => document.activeElement === document.querySelector('#wk-next [data-act=\"call\"]')")


def _focus_is_on_the_page(pg):
    return pg.evaluate("() => { const a = document.activeElement;"
                       " return !!a && a !== document.body && document.contains(a) && !!a.closest('#main'); }")


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["1280", "390"])
def test_after_a_saved_call_focus_lands_on_the_page_not_the_body(page_as, expect, viewport):
    _, pg = page_as("/bd/", AVERY, viewport)
    wait_week(pg)
    call(pg.locator("#wk-next"))
    expect(sheet(pg)).to_be_visible()
    sheet(pg).locator('[data-outcome="voicemail"]').click()
    expect(sheet(pg).locator('[data-act="change-outcome"]')).to_be_visible()
    pg.keyboard.press("Escape")
    expect(sheet(pg)).to_be_hidden()
    wait_week(pg)
    pg.wait_for_timeout(300)
    assert _focus_is_on_the_page(pg), "focus fell to <body> at %d wide" % viewport["width"]


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["1280", "390"])
def test_with_reduced_motion_the_call_sheet_takes_focus(page_as, expect, viewport):
    _, pg = page_as("/bd/", AVERY, viewport)
    wait_week(pg)
    pg.emulate_media(reduced_motion="reduce")
    pg.locator('#wk-next [data-act="call"]').focus()
    pg.keyboard.press("Enter")
    expect(sheet(pg)).to_be_visible()
    assert pg.evaluate("() => !!document.activeElement.closest('#call-sheet')"), "focus is on <body>"


def test_a_menu_item_shows_a_real_focus_ring(page_as):
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    pg.locator('#wk-next [data-act="more"]').click()
    pg.locator(".menu").wait_for()
    pg.keyboard.press("ArrowDown")
    style = pg.evaluate("() => { const e = document.activeElement; const c = getComputedStyle(e);"
                        " return {item: e.classList.contains('menu-item'), style: c.outlineStyle, width: c.outlineWidth}; }")
    assert style["item"] and style["style"] == "solid" and style["width"] == "2px", style


# ── the task buttons ─────────────────────────────────────────────────────────────────────────────
def test_done_then_undo(page_as, expect):
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    choose(pg, node(pg, DANA), "done")
    done = pg.locator('#wk-done [data-task="%d"][data-status="done"]' % DANA)
    expect(done).to_be_visible()
    expect(toasts(pg)).to_contain_text("Done. Nothing logged.")
    expect(pg.locator("#week-count")).to_have_text("All 2 done")
    assert pg.locator('[data-task="%d"]' % DANA).count() == 1, "one node per task"
    done.locator('[data-act="reopen"]').click()                 # shown: it was done today
    expect(pg.locator('#wk-rest [data-task="%d"][data-status="open"]' % DANA)).to_be_visible()
    expect(pg.locator("#summary")).to_contain_text("1 of 2 done")
    w = api(pg, "/api/bd/week")["week"]
    assert [t["status"] for t in w["tasks"] if t["id"] == DANA] == ["open"]


def test_not_this_week_takes_one_off_and_the_list_never_refills(page_as, expect):
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    total = pg.locator("[data-task]").count()
    choose(pg, node(pg, DANA), "snooze")
    expect(toasts(pg)).to_contain_text("Taken off this week.")
    expect(pg.locator('#wk-done [data-task="%d"][data-status="snoozed"]' % DANA)).to_contain_text("Not this week")
    expect(pg.locator(".dot.is-off")).to_have_count(1)
    pg.wait_for_timeout(400)
    assert pg.locator("[data-task]").count() == total, "taking one off must not pull in a new one"
    assert "1 of 2 done" in summary(pg), "taking one off is not done"
    pg.locator('#wk-done [data-task="%d"] [data-act="reopen"]' % DANA).click()
    expect(pg.locator('#wk-rest [data-task="%d"][data-status="open"]' % DANA)).to_be_visible()


def test_not_the_right_person_from_the_menu_closes_the_task_and_flags_the_contact(page_as, expect):
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    assert api(pg, "/api/bd/contacts/%d" % DANA_C)["contact"]["confirmed"] is True
    choose(pg, node(pg, DANA), "nrp")
    expect(sheet(pg).locator('[data-field="nrp"]')).to_be_visible()
    expect(sheet(pg)).to_contain_text("An assistant will check. This counts as done this week.")
    sheet(pg).locator('[data-field="nrp"]').fill("Ask for the estimator, Jo Pell.")
    expect(sheet(pg).locator('[data-act="rec-confirm"]')).to_have_text("Save")
    sheet(pg).locator('[data-act="rec-confirm"]').click()
    expect(toasts(pg)).to_contain_text("Marked as needs confirming.")
    done = pg.locator('#wk-done [data-task="%d"][data-status="done"]' % DANA)
    expect(done.locator(".wk-outcome")).to_have_text("Not the right person · Wed, Nov 4")
    c = api(pg, "/api/bd/contacts/%d" % DANA_C)["contact"]
    assert c["confirmed"] is False
    assert "Ask for the estimator, Jo Pell." in (c["notes"] or "")


def test_the_wrong_person_fallback_with_no_task_confirms_the_contact(page_as, expect):
    """The call sheet opened with no task (Dana Whitlow, the seed's one confirmed contact): Wrong
    person marks her as needs confirming through the confirm route, keeps the note as a note, and
    leaves her task alone (the task route is not used)."""
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    assert api(pg, "/api/bd/contacts/%d" % DANA_C)["contact"]["confirmed"] is True
    pg.evaluate("() => BDCall.open({contact: {id: %d, name: 'Dana Whitlow', phone: '913-555-0101'}, mode: 'nrp'})" % DANA_C)
    expect(sheet(pg).locator('[data-field="nrp"]')).to_be_visible()
    expect(sheet(pg)).to_contain_text("An assistant will check.")
    sheet(pg).locator('[data-field="nrp"]').fill("She moved to the Lenexa office.")
    sheet(pg).locator('[data-act="rec-confirm"]').click()
    expect(toasts(pg)).to_contain_text("Marked as needs confirming.")
    assert api(pg, "/api/bd/contacts/%d" % DANA_C)["contact"]["confirmed"] is False
    notes = [i for i in history(pg, DANA_C) if i["kind"] == "note"]
    assert [n["summary"] for n in notes] == ["She moved to the Lenexa office."]
    w = api(pg, "/api/bd/week")["week"]
    assert [t["status"] for t in w["tasks"] if t["id"] == DANA] == ["open"], "no task, so no task closed"


def test_give_me_ten_more_adds_the_rest_and_never_moves_the_10(page_as, expect):
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    pg.locator("#ten-more-btn").click()
    expect(toasts(pg)).to_contain_text("3 more names added below.")
    extra = pg.locator(".wk-extra")
    expect(extra).to_have_count(1)
    expect(extra.locator(".section-title")).to_have_text("2 more (to get ahead)")
    names = sorted(t.strip() for t in extra.locator(".who-name").all_inner_texts())
    assert names == ["Lena Ortiz", "Marisa Cole"], names
    # Nora Lindqvist, a second due maintenance follow-up, sits under "Due now", not in the extra 10.
    expect(pg.locator("#wk-due")).to_contain_text("Nora Lindqvist")
    s = summary(pg)
    assert "1 of 2 done" in s and "Due now: 2 maintenance follow-ups" in s, s
    pg.locator("#ten-more-btn").click()
    expect(pg.locator(".wk-ten-msg")).to_have_text("Everyone on your list is already covered this week.")


def test_the_tray_follow_up_meets_not_built_yet(page_as, expect):
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    item = pg.locator('#wk-tray .wk-tray-item[data-contact="%d"]' % PRIYA_C)
    item.locator('[data-act="tray-open"]').click()
    body = item.locator(".wk-tray-body")
    expect(body).to_contain_text("Send a follow-up?")
    body.locator('[data-act="fu-pick"][data-ch="email"]').click()
    expect(body.locator(".field-error")).to_have_text(NOT_BUILT)
    assert pg.locator("#call-sheet").count() == 0 or pg.locator("#call-sheet").is_hidden()


# ── who sees what ────────────────────────────────────────────────────────────────────────────────
def test_a_manager_is_asked_whose_week_then_sees_it_read_only(page_as, expect):
    _, pg = page_as("/bd/", DEVON)
    expect(pg.locator("#week-sub")).to_have_text("Choose whose week to look at.")
    assert re.fullmatch(r"Good (morning|afternoon|evening), Devon", pg.inner_text("#wk-greeting").strip())
    expect(pg.locator("[data-pick]")).to_have_count(2)
    assert pg.locator("[data-pick]").all_inner_texts() == ["Avery Quill", "Blair Fenn"], "the active salespeople"
    assert pg.locator("#summary").is_hidden() and pg.locator("[data-task]").count() == 0
    pg.locator("[data-pick]", has_text="Avery Quill").click()
    expect(pg.locator("#wk-greeting")).to_have_text("Avery's week")
    wait_week(pg)
    assert "owner=1" in pg.url
    for sel in ['[data-act="call"]', '[data-act="more"]', '[data-act="snooze"]', '[data-act="done"]',
                '[data-act="reopen"]', "#ten-more-btn", '[data-act="tray-confirm"]', '[data-act="run-weekly"]']:
        assert pg.locator(sel).count() == 0, sel
    assert pg.locator('#main a[href^="tel:"]').count() == 0, "no call links for a manager"
    expect(pg.locator('#wk-rest [data-task="%d"]' % DANA)).to_contain_text("Priority 82")
    assert pg.locator("#owner-pick").input_value() == "1"


def test_the_admin_runs_the_weekly_batch_from_this_week(env, page_as, expect):
    """Blair's week emptied first, so This Week shows the admin its manual run (POST
    /api/bd/admin/weekly/run). The batch it builds is Blair's own people: in the seed she owns Rory
    Sandell, Theo Banks, Owen Pratt, Sam Achebe and D. Whitlow (a flagged duplicate)."""
    _base, url, _b = env
    run_sql(url, "delete from tasks where batch_id = 202")
    run_sql(url, "delete from task_batches where id = 202")
    _, pg = page_as("/bd/?owner=2", EMERY)
    run = pg.locator('[data-act="run-weekly"]')
    expect(run).to_have_text("Make this week's list now")
    expect(pg.locator(".wk-empty")).to_contain_text("Nothing on the list this week.")
    run.click()
    expect(toasts(pg)).to_contain_text("This week's list is ready.")
    wait_week(pg)
    pg.wait_for_selector("[data-task]")
    shown = {t.strip() for t in pg.locator("[data-task] .who-name").all_inner_texts()}
    if pg.locator("#wk-next-name").count():
        shown.add(pg.inner_text("#wk-next-name").strip())
    blairs = {"Rory Sandell", "Theo Banks", "Owen Pratt", "Sam Achebe", "D. Whitlow"}
    assert shown and shown <= blairs, shown
    w = api(pg, "/api/bd/week?owner=2")["week"]
    assert [b["kind"] for b in w["batches"]] == ["friday"]
    assert w["week_start"] == "2026-11-02"


def test_a_manager_never_sees_the_manual_run(env, page_as, expect):
    _base, url, _b = env
    run_sql(url, "delete from tasks where batch_id = 202")
    run_sql(url, "delete from task_batches where id = 202")
    _, pg = page_as("/bd/?owner=2", DEVON)
    expect(pg.locator(".wk-empty")).to_contain_text("Nothing on the list this week.")
    assert pg.locator('[data-act="run-weekly"]').count() == 0


def test_the_assistant_lands_on_the_contacts_is_coming_page(page_as, expect):
    p, pg = page_as("/bd/", CASEY)
    pg.wait_for_url(re.compile(r".*/bd/contacts\.html(\?.*)?$"), timeout=10000)
    expect(pg.locator("#main")).to_contain_text("The Contacts page is coming.")
    assert pg.locator("#main a").count() == 0, "no link to a page that has not moved"
    # This Week was replaced in the history, so Back goes to where the tab was before (here the
    # browser's blank page), never back to /bd/ and its redirect.
    pg.go_back()
    assert "/bd/" not in pg.url, pg.url
    # When the redirect lands while /bd/ is still loading, the browser cancels the rest of that load:
    # the one request that may be reported as failed, and it is the redirect itself, not an error.
    p.errors[:] = [e for e in p.errors if e != "failed /bd/"]


# ── widths ───────────────────────────────────────────────────────────────────────────────────────
def test_on_a_phone_the_week_fits_and_the_call_sheet_is_a_bottom_sheet(page_as, expect):
    _, pg = page_as("/bd/", AVERY, PHONE)
    wait_week(pg)
    over = pg.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
    assert over <= 1, "scrolls sideways by %dpx" % over
    assert pg.locator("#wk-tray").is_hidden(), "on a phone the tray is a banner"
    expect(pg.locator("#wk-tray-banner")).to_contain_text("1 next step to confirm")
    pg.locator("#wk-next .wk-call").click()
    expect(sheet(pg)).to_be_visible()
    pg.wait_for_timeout(400)                                    # the slide in
    box = sheet(pg).bounding_box()
    assert abs(box["y"] + box["height"] - PHONE["height"]) <= 2, "a bottom sheet sits on the bottom edge"
    assert box["width"] >= PHONE["width"] - 1
    for k in ("answered", "voicemail", "no_answer", "wrong"):
        b = sheet(pg).locator('[data-outcome="%s"]' % k).bounding_box()
        assert b["y"] >= 0 and b["y"] + b["height"] <= PHONE["height"], "%s is off screen" % k


@pytest.mark.parametrize("viewport", [TABLET, DESKTOP], ids=["820", "1280"])
def test_nothing_scrolls_sideways(page_as, viewport):
    _, pg = page_as("/bd/", AVERY, viewport)
    wait_week(pg)
    over = pg.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
    assert over <= 1, "scrolls sideways by %dpx at %d wide" % (over, viewport["width"])
    if viewport is DESKTOP:
        assert pg.locator("#wk-tray").is_visible(), "at 1280 the tray sits beside the list"
        tray, main = pg.locator("#wk-tray").bounding_box(), pg.locator("#wk-main").bounding_box()
        assert tray["x"] >= main["x"] + main["width"] - 1
