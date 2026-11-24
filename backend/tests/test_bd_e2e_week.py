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
  account" (one company, #828), "1 call to go this week.", meetings "0 of 5" (settings' weekly goal).
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
batch from This Week; a name opens the contact page (#808), and no role's view (menus included) links
to a BD page that has not moved (MOVED_PAGES, not "the server answers 200"); the assistant lands on the
Contacts-is-coming page, which links to Add contact; desktop and phone width, where a row with no phone
number keeps its More menu.

One row per company (#828): the Friday batch gives a company with two people one slot and one row;
a row opens by click, Enter or Space; a voicemail on one person closes the row and moves "N of 10
done" once, a second call the same week does not; Not this week, Done and Undo act on the whole row;
"Due now" is one row per maintenance company; Give Me 10 More never adds a company already on the
list in any state; a manager opens a row but cannot act on it; a long company name fits at 390 and
320. The second person at a company (Sue Marlow, Tess Rowan) is added inside each test, so the
fixture seed's own numbers stay as they are.

BD's own tests of This Week are carried over below the ones above, renamed only where the seed's
numbers differ from BD's mock week; the few that are not (the contact page has not moved, or the
recommendation and follow-up routes are Phase 5 placeholders) are listed, one reason each, in the
#807 PR's "Not carried over" table.

Runs in the browser job of ci.yml (tests/_bd_browser.py: the live app on a seeded BD test database,
sign-in faked only inside the test process).
"""
import re
import urllib.request

import pytest

from _bd_browser import (DESKTOP, MOVED_PAGES, NOT_BUILT, PHONE, TABLET, Page, api, bd_links, browser,
                         focus_is_on_the_page, live_app_db, menu_acts, require_playwright, reseed, run_sql, sideways,
                         toasts)

AVERY = "avery.quill@example.com"
CASEY = "casey.moret@example.com"         # assistant
DEVON = "devon.hale@example.com"          # manager
EMERY = "emery.stoll@example.com"         # admin

HAL, DANA, PRIYA = 301, 302, 303          # Avery's tasks
HAL_C, DANA_C, PRIYA_C = 30, 21, 25
NORA_C = 31                               # Avery's other maintenance contact (Give Me 10 More's)

MAINT_PILL = "Maintenance · due"
DUE_ONE = "Due now: 1 maintenance account"           # "Due now: N" counts companies (#828)
NEXT_CALL = '#wk-next .wk-next-acts [data-act="call"]'
NEXT_MORE = '#wk-next .wk-next-acts [data-act="more"]'
STAYS_LINE = "Stays on your list until you log a call, meeting, email or text."
STAYS_409 = "A maintenance follow-up stays on the list until you log a call, meeting, email or text."


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


def sheet(pg):
    return pg.locator("#call-sheet")


def node(pg, task_id):
    return pg.locator('[data-task="%s"]' % task_id)


def call(nd):
    nd.locator('[data-act="call"]').first.click()      # a tel: link; its handler opens the sheet


def choose(pg, nd, act):
    nd.locator('[data-act="more"]:visible').first.click()
    pg.locator('.menu [data-act="%s"]' % act).click()


def summary(pg):
    return re.sub(r"\s+", " ", pg.inner_text("#summary")).strip()


def week_json(pg, owner=None, week_start=None):
    q = "&".join(x for x in ("owner=%s" % owner if owner else "", "week_start=%s" % week_start if week_start else "") if x)
    return api(pg, "/api/bd/week" + ("?" + q if q else ""))["week"]


def post_status(pg, path, body=None):
    """POST through the page's own BDApi and report what came back: {ok: True} or {status, message}."""
    return pg.evaluate("async ([p, b]) => { try { await BDApi.post(p, b); return {ok: true}; }"
                       " catch (e) { return {status: e.status, message: e.message}; } }", [path, body or {}])


def log_by_api(pg, cid, kind, outcome=None):
    """Log an interaction now through the page's BDApi (the page shows it after a reload)."""
    body = {"kind": kind}
    if outcome:
        body["outcome"] = outcome
    return pg.evaluate("([cid, b]) => BDApi.post(BDApi.path('contacts', cid, 'interactions'), b)", [cid, body])


def reload_week(pg):
    pg.reload()
    wait_week(pg)


def settled(pg):
    """A layout is measured once it has settled: the page's own fonts loaded (a fallback font, drawn
    while they load, is wider) and the tool's sidebar done opening (its column grows as it does)."""
    pg.evaluate("() => document.fonts.ready.then(() => true)")
    pg.wait_for_function("() => document.getAnimations().every(a => a.playState !== 'running')", timeout=5000)


def visible_pills(nd):
    return [re.sub(r"\s+", " ", x).strip() for x in nd.locator(".pill:visible").all_inner_texts()]


def open_more(pg, nd):
    """Open this task's More menu; return (its acts, its text). The menu is closed again."""
    nd.locator('[data-act="more"]:visible').first.click()
    acts = menu_acts(pg)
    text = pg.locator(".menu").inner_text()
    pg.keyboard.press("Escape")
    pg.locator(".menu").wait_for(state="detached")
    return acts, text


def assert_no_take_off(pg, nd, who):
    """A due maintenance task has no "Not this week" and no "Done, nothing to log", as a button or in
    its More menu; logging a meeting and "Not the right person" stay."""
    for act in ("snooze", "done"):
        assert nd.locator('[data-act="%s"]' % act).count() == 0, "%s: a %s button" % (who, act)
    acts, text = open_more(pg, nd)
    assert "snooze" not in acts and "done" not in acts, "%s: take-off in the menu %r" % (who, acts)
    assert "Not this week" not in text and "Done, nothing to log" not in text, (who, text)
    assert "log-meeting" in acts and "nrp" in acts, (who, acts)


def dot_rows(pg):
    """Each tracker row as letters: d done, t to do, o taken off."""
    return pg.locator("#summary .dots-row").evaluate_all(
        "rs => rs.map(r => [...r.querySelectorAll('.dot')].map(d => d.classList.contains('is-done') ? 'd'"
        " : d.classList.contains('is-off') ? 'o' : 't').join(''))")


def nora_elsewhere(env):
    """Nora Lindqvist moved to Osage Plains Brewing (company 18, where Avery owns nobody else): a
    maintenance company of her own, so her pin is a "Due now" row and not part of Hal's Kaw Valley
    row (#828)."""
    run_sql(env[1], "update contacts set company_id = 18 where id = %s", (NORA_C,))


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
    for words in ("1 of 2 done", DUE_ONE, "Meetings this week: 0 of 5", "14%",
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


def test_names_open_the_contact_page_and_so_does_the_menu(page_as, expect):
    """#808: the contact page has moved, so a name, Next up's "Open <name>" and More's "Open contact"
    go there, with from=week (its Back is to This Week). Every other link is a phone number."""
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    links = pg.locator("#main a[href]").evaluate_all("els => els.map(e => e.getAttribute('href'))")
    pages = sorted({h for h in links if not h.startswith("tel:")})
    assert pages == ["/bd/contact.html?id=%d&from=week" % c for c in sorted((DANA_C, PRIYA_C, HAL_C, NORA_C))], pages
    expect(pg.locator("#wk-next .wk-next-open")).to_have_text("Open Hal Brecken")
    pg.locator('#wk-rest [data-task="%d"] .wk-co-head [data-act="more"]' % DANA).click()
    acts = menu_acts(pg)
    assert acts == ["snooze", "log-meeting", "nrp", "done", "open"], acts
    assert pg.locator(".menu a").get_attribute("href") == "/bd/contact.html?id=%d&from=week" % DANA_C
    pg.locator(".menu a").click()
    pg.wait_for_url(re.compile(r".*/bd/contact\.html\?id=%d&from=week$" % DANA_C))
    pg.locator("#cd-title").wait_for()
    expect(pg.locator("#cd-title")).to_have_text("Dana Whitlow")
    expect(pg.locator(".cd-back")).to_have_attribute("href", "/bd/")


@pytest.mark.parametrize("email, path", [(AVERY, "/bd/"), (DEVON, "/bd/"), (DEVON, "/bd/?owner=1"), (EMERY, "/bd/"),
                                         (EMERY, "/bd/?owner=1"), (EMERY, "/bd/?owner=2")],
                         ids=["salesperson", "manager-asked", "manager-week", "admin-asked", "admin-week", "admin-empty"])
def test_no_link_goes_to_a_bd_page_that_has_not_moved(env, page_as, email, path):
    """Spec #802, page links: a link to a BD page that has not moved is not drawn. Checked against
    the pages that HAVE moved (MOVED_PAGES, every BD page since Contacts moved in #810), not against
    what the server happens to serve. Every role's view, the admin's empty week (the manual run), and
    the open menus too."""
    _base, url, _b = env
    if path.endswith("owner=2"):
        run_sql(url, "delete from tasks where batch_id = 202")
        run_sql(url, "delete from task_batches where id = 202")
    _, pg = page_as(path, email)
    if "owner=" in path or email == AVERY:
        pg.wait_for_selector("#summary .wk-progress-in, .wk-empty", timeout=15000)
    else:
        pg.wait_for_selector("[data-pick]", timeout=15000)
    seen = set(bd_links(pg))
    assert "/bd/" in seen, "the sidebar's BD CRM row links to This Week"
    for more in pg.locator('#main [data-act="more"]:visible').all():
        more.click()
        pg.locator(".menu").wait_for()
        seen |= set(bd_links(pg))
        pg.keyboard.press("Escape")
        pg.locator(".menu").wait_for(state="detached")
    assert seen <= MOVED_PAGES, sorted(seen - MOVED_PAGES)


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
    link = pg.locator(NEXT_CALL)
    link.focus()
    call(pg.locator("#wk-next"))
    expect(sheet(pg)).to_be_visible()
    for _ in range(8):
        pg.keyboard.press("Tab")
        assert pg.evaluate("() => !!document.activeElement.closest('#call-sheet')"), "focus left the sheet"
    pg.keyboard.press("Escape")
    expect(sheet(pg)).to_be_hidden()
    assert pg.evaluate("() => document.activeElement === document.querySelector('#wk-next .wk-next-acts [data-act=\"call\"]')")


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
    assert focus_is_on_the_page(pg), "focus fell to <body> at %d wide" % viewport["width"]


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["1280", "390"])
def test_with_reduced_motion_the_call_sheet_takes_focus(page_as, expect, viewport):
    _, pg = page_as("/bd/", AVERY, viewport)
    wait_week(pg)
    pg.emulate_media(reduced_motion="reduce")
    pg.locator(NEXT_CALL).focus()
    pg.keyboard.press("Enter")
    expect(sheet(pg)).to_be_visible()
    assert pg.evaluate("() => !!document.activeElement.closest('#call-sheet')"), "focus is on <body>"


def test_a_menu_item_shows_a_real_focus_ring(page_as):
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    pg.locator(NEXT_MORE).click()
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
    # Two companies (Lena's Bluestem Logistics, Marisa's Cottonwood & Sons Paving); Nora's pin joins
    # Hal's Kaw Valley row (#828).
    expect(toasts(pg)).to_contain_text("2 more companies added below.")
    extra = pg.locator(".wk-extra")
    expect(extra).to_have_count(1)
    expect(extra.locator(".section-title")).to_have_text("2 more (to get ahead)")
    names = sorted(t.strip() for t in extra.locator(".wk-co-name").all_inner_texts())
    assert names == ["Bluestem Logistics", "Cottonwood & Sons Paving"], names
    firsts = sorted(t.strip() for t in extra.locator(".wk-co-first").all_inner_texts())
    assert firsts == ["Lena Ortiz · Facilities Director", "Marisa Cole · Owner"], firsts
    # Nora Lindqvist, a second due maintenance follow-up, is at Kaw Valley with Hal: one company, one
    # row (Next up), so no "Due now" group, and "Due now" counts it once.
    expect(pg.locator('#wk-next [data-task="%d"] [data-person="%d"]' % (HAL, NORA_C))).to_have_count(1)
    assert pg.locator("#wk-due").count() == 0
    s = summary(pg)
    assert "1 of 2 done" in s and DUE_ONE in s, s
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
    shown = {t.strip() for t in pg.locator("[data-task] [data-person] .wk-p-name").evaluate_all("els => els.map(e => e.textContent)")}
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


def test_the_assistant_lands_on_contacts(page_as, expect):
    """Her BD home (#810: the Contacts page itself, no longer a page saying it is coming)."""
    p, pg = page_as("/bd/", CASEY)
    pg.wait_for_url(re.compile(r".*/bd/contacts\.html(\?.*)?$"), timeout=10000)
    pg.locator("#ct-list .ct-acct").first.wait_for(timeout=15000)
    expect(pg.locator("main h1")).to_have_text("Contacts")
    assert "The Contacts page is coming." not in pg.locator("#main").inner_text()
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
    over = sideways(pg)
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
    over = sideways(pg)
    assert over <= 1, "scrolls sideways by %dpx at %d wide" % (over, viewport["width"])
    if viewport is DESKTOP:
        assert pg.locator("#wk-tray").is_visible(), "at 1280 the tray sits beside the list"
        tray, main = pg.locator("#wk-tray").bounding_box(), pg.locator("#wk-main").bounding_box()
        assert tray["x"] >= main["x"] + main["width"] - 1


# ── carried over from BD's test_e2e_week, on the fixture seed ───────────────────────────────────
# BD's fictional week pinned two maintenance contacts and held ten BD tasks; the seed's week pins one
# (Hal) and holds two (Dana open, Priya done), and Give Me 10 More pins a second (Nora). The rules are
# BD's; the numbers are the seed's, worked by hand.

def _add_tasks(url, *rows):
    """Extra tasks on Avery's Friday batch 201: (contact id, kind, status)."""
    for cid, kind, status in rows:
        run_sql(url, "insert into tasks (batch_id, contact_id, kind, score, reason, reasons, status, snoozed_until,"
                     " done_at) values (201, %s, %s, 10, 'Seeded for a test.', %s, %s, %s, %s)",
                (cid, kind, ["Seeded for a test"], status, "2026-11-09" if status == "snoozed" else None,
                 "2026-11-03T18:00:00+00:00" if status == "done" else None))


@pytest.mark.parametrize("email, path", [(AVERY, "/bd/"), (EMERY, "/bd/?owner=1")], ids=["salesperson", "admin"])
def test_the_tracker_fills_from_the_left(env, page_as, email, path):
    """Done dots first, then to do, then taken off, whatever order the server lists the tasks in.
    The New row is Priya (done, task 303), then Marisa (taken off) and Lena (to do) added after her:
    the server's order is d, o, t and the row must read d, t, o."""
    _base, url, _b = env
    _add_tasks(url, (23, "new", "snoozed"), (27, "new", "open"))
    _, pg = page_as(path, email)
    wait_week(pg)
    assert dot_rows(pg) == ["dto", "t"], dot_rows(pg)


def test_the_tracker_counts_only_the_10(page_as, expect):
    """"N of 10 done", the dots and their label are the BD tasks only; "Due now: N maintenance
    follow-up(s)" under the headline counts the open pinned tasks and goes when none is left."""
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    w = week_json(pg)
    assert (w["done_count"], w["total"], w["due_count"]) == (1, 2, 1)
    dots = pg.locator("[data-dot-task]").evaluate_all("els => els.map(e => e.dataset.dotTask)")
    assert sorted(dots) == [str(DANA), str(PRIYA)], "a pinned task has no dot"
    assert pg.locator(".wk-dots").get_attribute("aria-label") == "1 of 2 done: 1 of 1 new, 0 of 1 follow-ups"
    line = pg.locator("#summary #wk-due-line")
    expect(line).to_have_text(DUE_ONE)
    assert line.bounding_box()["y"] >= pg.locator("#week-count").bounding_box()["y"], "under the headline"
    # A voicemail on Next up (Hal) is a follow-up: the line goes, the headline does not move.
    call(pg.locator("#wk-next"))
    sheet(pg).locator('[data-outcome="voicemail"]').click()
    expect(pg.locator("#wk-due-line")).to_have_count(0)
    assert "1 of 2 done" in summary(pg) and pg.locator("[data-dot-task]").count() == 2
    sheet(pg).locator('[data-act="close"]').click()
    expect(sheet(pg)).to_be_hidden()
    nxt = pg.locator("#wk-next [data-task]")
    expect(nxt).to_have_attribute("data-task", str(DANA))
    assert nxt.locator("p.wk-next-stays").count() == 0, "the stays line belongs to a pinned task only"
    expect(nxt.locator('[data-act="snooze"]')).to_be_visible()
    nxt.locator('[data-act="more"]:visible').first.click()
    pg.locator('.menu [data-act="done"]').click()
    expect(pg.locator("#week-count")).to_have_text("All 2 done")


def test_the_due_line_follows_a_logged_follow_up_without_waiting_for_the_server(page_as, expect):
    """"Due now" follows from what the save returned, even when every later read of the week fails."""
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    pg.evaluate("() => { const get = BDApi.get; BDApi.get = (p, ...a) => p.indexOf('/api/bd/week') === 0"
                " ? Promise.reject(new Error('offline')) : get.call(BDApi, p, ...a); }")
    expect(pg.locator("#wk-due-line")).to_have_text(DUE_ONE)
    call(pg.locator("#wk-next"))
    sheet(pg).locator('[data-outcome="no_answer"]').click()
    expect(pg.locator("#wk-due-line")).to_have_count(0)
    assert "1 of 2 done" in summary(pg)


def test_the_tray_count_sits_beside_its_heading(page_as):
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    title = pg.locator("#wk-tray-h").bounding_box()
    count = pg.locator("#wk-tray .wk-tray-head .count").bounding_box()
    assert 0 <= count["x"] - (title["x"] + title["width"]) <= 24, "the count follows the title"


def test_the_admin_sees_priority_numbers_and_can_act(page_as):
    """Next up is the pinned maintenance follow-up (Hal): no "Priority N" on it. Dana's row shows
    the seed's score, 82. A salesperson never sees a score."""
    _, pg = page_as("/bd/?owner=1", EMERY)
    wait_week(pg)
    assert pg.locator(NEXT_CALL).count() == 1
    assert "Maintenance" in pg.inner_text("#wk-next")
    assert not re.search(r"Priority \d+", pg.inner_text("#wk-next")), "a pinned follow-up shows no priority"
    assert "Priority 82" in pg.inner_text("#wk-rest")
    _, pg2 = page_as("/bd/", AVERY)
    wait_week(pg2)
    assert pg2.locator(".wk-score").count() == 0, "a salesperson never sees the score"


def test_a_due_maintenance_contact_is_next_up_with_no_take_off(page_as, expect):
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    card = pg.locator("#wk-next [data-task]")
    expect(card).to_have_attribute("data-task", str(HAL))
    pills = visible_pills(card)
    assert MAINT_PILL in pills and "Maintenance" not in pills, pills
    assert card.locator("p.wk-next-stays").text_content().strip() == STAYS_LINE
    assert_no_take_off(pg, card, "Next up")
    acts, _ = open_more(pg, node(pg, DANA))
    assert "snooze" in acts and "done" in acts, "a BD task keeps both: %r" % acts


def test_a_maintenance_task_cannot_be_taken_off_even_when_forced(page_as, expect):
    """The page never offers them; forced, the server refuses both with one sentence while the contact
    is due, and the task stays open and pinned. A BD task through the same call still closes. The
    due contact is Nora, pinned by Give Me 10 More: she has never been followed up. (The seed's Hal
    task is a stale one: his last follow-up, Aug 20, is not due again yet, so it could be taken off.)"""
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    pg.locator("#ten-more-btn").click()
    expect(toasts(pg)).to_contain_text("added below.")
    expect(pg.locator('#wk-next [data-person="%d"]' % NORA_C)).to_have_count(1)   # Hal's Kaw Valley row (#828)
    expect(pg.locator("#wk-due-line")).to_have_text(DUE_ONE)
    nora = [t["id"] for t in week_json(pg)["tasks"] if t["contact"]["id"] == NORA_C]
    assert len(nora) == 1
    for act in ("snooze", "done"):
        r = post_status(pg, "/api/bd/tasks/%d/%s" % (nora[0], act))
        assert r == {"status": 409, "message": STAYS_409}, (act, r)
    w = week_json(pg)
    assert [t["status"] for t in w["tasks"] if t["id"] == nora[0]] == ["open"]
    assert (w["due_count"], w["done_count"]) == (1, 1)        # one company: Kaw Valley (#828)
    reload_week(pg)
    expect(pg.locator('#wk-next [data-task="%d"][data-status="open"] [data-person="%d"]' % (HAL, NORA_C))).to_have_count(1)
    assert post_status(pg, "/api/bd/tasks/%d/done" % DANA) == {"ok": True}, "a BD task still closes"


def test_logging_an_email_on_a_due_maintenance_contact_moves_it_to_done(page_as, expect):
    """The rule, through the real contact page (#808; #807 used the route until the page moved): a
    NOTE added in the History box does not clear Hal's due maintenance follow-up (task 301, pinned on
    Avery's week), an EMAIL (the Email button, then "Did you send something?") does. The task leaves
    Next up and shows in Done as "Emailed" with no Undo (reopening it would leave a pin nobody can
    clear), and "Due now" goes."""
    p, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    expect(pg.locator("#wk-next [data-task]")).to_have_attribute("data-task", str(HAL))
    # a note first: nothing moves
    pg = p.open("/bd/contact.html?id=%d" % HAL_C)
    pg.locator("#cd-title").wait_for(timeout=15000)
    pg.locator("#cd-note").click()
    pg.locator("#cd-note-text").fill("Looked up their last invoice.")
    pg.locator('[data-act="note-save"]').click()
    expect(pg.locator("#cd-history .cd-tl-item", has_text="Looked up their last invoice.")).to_have_count(1)
    pg = p.open("/bd/")
    wait_week(pg)
    expect(pg.locator("#wk-next [data-task]")).to_have_attribute("data-task", str(HAL))
    expect(pg.locator("#wk-due-line")).to_have_text(DUE_ONE)
    assert node(pg, HAL).first.get_attribute("data-status") == "open", "a note is not a follow-up"
    # then the email, from the page's Email button (the mail app itself is not opened in the test)
    pg = p.open("/bd/contact.html?id=%d" % HAL_C)
    pg.locator("#cd-title").wait_for(timeout=15000)
    pg.evaluate("() => document.querySelector('[data-act=\"mail-out\"]').addEventListener('click', e => e.preventDefault())")
    pg.locator('.cd-head [data-act="mail-out"]').click()
    pg.locator('.cd-ask [data-act="log-sent"]').click()
    expect(pg.locator(".cd-ask")).to_have_count(0)
    # Both are logged at the server's pinned "now", so which comes first is not the point.
    assert sorted(i["kind"] for i in history(pg, HAL_C)[:2]) == ["email", "note"], "the note and the email, on top"
    pg = p.open("/bd/")
    wait_week(pg)
    expect(pg.locator("#wk-next [data-task]")).to_have_attribute("data-task", str(DANA))
    row = pg.locator('#wk-done [data-task="%d"][data-status="done"]' % HAL)
    expect(row.locator(".wk-outcome")).to_have_text("Hal Brecken: Emailed · Wed, Nov 4")
    assert row.locator('[data-act="reopen"]').count() == 0, "no Undo on a done maintenance row"
    assert pg.locator("#wk-due-line").count() == 0 and pg.locator("#wk-due").count() == 0
    assert "1 of 2 done" in summary(pg), "the headline is the 10"


@pytest.mark.parametrize("kind, outcome, word", [
    ("email", None, "Emailed"), ("sms", None, "Texted"), ("call", "answered", "Talked"),
    ("call", "voicemail", "Voicemail"), ("meeting", None, "Meeting"), ("hosted", None, "Hosted event"),
])
def test_a_done_maintenance_row_says_how_it_was_followed_up(page_as, expect, kind, outcome, word):
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    log_by_api(pg, HAL_C, kind, outcome)
    reload_week(pg)
    row = pg.locator('#wk-done [data-task="%d"][data-status="done"]' % HAL)
    expect(row.locator(".wk-outcome")).to_have_text("Hal Brecken: " + word + " · Wed, Nov 4")   # Nora is on the row too
    assert row.locator('[data-act="reopen"]').count() == 0, "no Undo on a done maintenance row"


@pytest.mark.parametrize("email", [DEVON, EMERY], ids=["manager", "admin"])
def test_a_manager_and_the_admin_see_the_pin_on_a_salespersons_week(page_as, expect, email):
    _, pg = page_as("/bd/?owner=1", email)
    wait_week(pg)
    card = pg.locator("#wk-next [data-task]")
    expect(card).to_have_attribute("data-task", str(HAL))
    pills = visible_pills(card)
    assert MAINT_PILL in pills and "Maintenance" not in pills, pills
    expect(pg.locator("#wk-due-line")).to_have_text(DUE_ONE)
    assert "1 of 2 done" in summary(pg) and pg.locator("[data-dot-task]").count() == 2
    if email == DEVON:
        for sel in ['[data-act="call"]', '[data-act="more"]', '[data-act="snooze"]', '[data-act="done"]',
                    '[data-act="reopen"]', "#ten-more-btn"]:
            assert pg.locator(sel).count() == 0, sel
    else:
        expect(card.locator('.wk-next-acts [data-act="call"]')).to_be_visible()
        assert_no_take_off(pg, card, "Next up (admin)")


def test_the_week_with_every_bd_task_done_is_not_all_done_while_something_is_pinned(page_as, expect):
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    assert post_status(pg, "/api/bd/tasks/%d/done" % DANA) == {"ok": True}
    reload_week(pg)
    assert pg.inner_text("#week-count").strip() == "All 2 done"
    expect(pg.locator("#wk-next [data-task]")).to_have_attribute("data-task", str(HAL))
    assert pg.locator(".wk-end.is-all").count() == 0
    assert pg.locator("#wk-rest").count() == 0, "no empty Rest of your 10"
    expect(pg.locator("#wk-due-line")).to_have_text(DUE_ONE)
    log_by_api(pg, HAL_C, "sms")
    reload_week(pg)
    expect(pg.locator(".wk-end.is-all")).to_have_count(1)
    assert pg.locator("#wk-due-line").count() == 0 and pg.locator("#wk-due").count() == 0


def test_due_now_group_sits_above_the_rest_of_the_10(env, page_as, expect):
    """Give Me 10 More pins Nora: she is listed under "Due now", between Next up (Hal) and "Rest of
    your 10" (Dana only), with no take-off; once she is followed up the group is gone. Nora is moved
    to a company of her own first (Osage Plains Brewing): at Kaw Valley she would be on Hal's row."""
    nora_elsewhere(env)
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    pg.locator("#ten-more-btn").click()
    expect(pg.locator("#wk-due")).to_contain_text("Nora Lindqvist")
    assert pg.locator("#wk-due-h").text_content().strip() == "Due now"
    order = pg.evaluate("() => ['wk-next', 'wk-due', 'wk-rest'].map(id => document.getElementById(id))"
                        ".map((e, i, all) => i === 0 || !!(all[i - 1].compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING))")
    assert order == [True, True, True], "Next up, then Due now, then Rest of your 10"
    assert pg.locator("#wk-rest [data-task]").evaluate_all("els => els.map(e => e.dataset.task)") == [str(DANA)]
    nora = pg.locator("#wk-due [data-task]")
    expect(nora).to_have_count(1)
    assert_no_take_off(pg, nora, "Due now row")
    log_by_api(pg, NORA_C, "call", "no_answer")
    reload_week(pg)
    assert pg.locator("#wk-due").count() == 0 and pg.locator("#wk-due-h").count() == 0


def test_give_me_10_more_never_puts_a_pinned_task_in_the_extra_ten(env, page_as, expect):
    nora_elsewhere(env)
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    pg.locator("#ten-more-btn").click()
    expect(pg.locator(".wk-extra")).to_have_count(1)
    w = week_json(pg)
    extra = [b for b in w["batches"] if b["kind"] == "ten_more"][-1]["id"]
    pinned = [t for t in w["tasks"] if t["kind"] == "maintenance" and t["batch_id"] == extra]
    assert [t["contact"]["id"] for t in pinned] == [NORA_C]
    assert pg.locator("#wk-due [data-task]").evaluate_all("els => els.map(e => e.dataset.task)") == [str(pinned[0]["id"])]
    assert pg.locator('.wk-extra [data-task="%d"]' % pinned[0]["id"]).count() == 0
    expect(pg.locator("#wk-due-line")).to_have_text("Due now: 2 maintenance accounts")    # Kaw Valley, Osage
    pills = visible_pills(node(pg, pinned[0]["id"]))
    assert MAINT_PILL in pills and "Maintenance" not in pills, pills
    assert_no_take_off(pg, node(pg, pinned[0]["id"]), "the extra ten's pinned task")


def test_a_pinned_row_keeps_its_key_account_pill_beside_the_due_pill(env, page_as):
    """Only the neutral "Maintenance" pill gives way to "Maintenance · due"; Key account stays. Nora
    is made a confirmed key account (an unconfirmed contact's slot says "Needs confirming" first)."""
    _base, url, _b = env
    run_sql(url, "update contacts set importance = 3, confirmed = true where id = %s", (NORA_C,))
    nora_elsewhere(env)
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    pg.locator("#ten-more-btn").click()
    row = pg.locator("#wk-due [data-task]")
    row.wait_for()
    pills = visible_pills(row)
    assert MAINT_PILL in pills and "Key account" in pills and "Maintenance" not in pills, pills


@pytest.mark.parametrize("viewport", [PHONE, DESKTOP], ids=["390", "1280"])
def test_a_date_in_a_due_reason_does_not_break_across_lines(env, page_as, viewport):
    """"Follow-up was due <day>, <month> <date>" may wrap, never inside the date. Nora's last
    follow-up is put on Mar 2 so her reason has a date (a contact never followed up says so instead)."""
    _base, url, _b = env
    run_sql(url, "insert into interactions (contact_id, kind, occurred_at, summary, user_id)"
                 " values (%s, 'email', '2026-03-02 15:00:00+00', 'Sent the care sheet.', 1)", (NORA_C,))
    nora_elsewhere(env)
    _, pg = page_as("/bd/", AVERY, viewport)
    wait_week(pg)
    pg.locator("#ten-more-btn").click()
    reason = pg.locator("#wk-due [data-task] .wk-reason").first
    reason.wait_for()
    date = reason.locator(".wk-nowrap")
    assert re.match(r"^[A-Z][a-z]{2}, [A-Z][a-z]{2} \d{1,2}$", date.text_content().strip()), date.text_content()
    assert date.evaluate("el => el.getClientRects().length") == 1, "the date is split across lines"
    assert reason.inner_text().strip().startswith("Follow-up was due "), reason.inner_text()


def test_next_weeks_preview_marks_a_pinned_task(page_as, expect):
    """The admin builds Avery's next list (the Friday run closes what is left of this week), so the
    week reads as finished and offers "See next week's 10"; a pinned task there wears the due pill."""
    _, pg = page_as("/bd/?owner=1", EMERY)
    wait_week(pg)
    assert post_status(pg, "/api/bd/admin/weekly/run", {"owner": 1}) == {"ok": True}
    reload_week(pg)
    btn = pg.locator('[data-act="next-week"]')
    expect(btn).to_be_visible()
    btn.click()
    rows = pg.locator("#wk-preview [data-preview-task]")
    expect(rows.first).to_be_visible()
    kinds = [t["kind"] for t in week_json(pg, owner=1, week_start="2026-11-09")["tasks"]]
    assert kinds.count("maintenance") >= 1, "next week's list pins the due contacts first"
    assert rows.count() == len(kinds)
    for i, k in enumerate(kinds):
        pills = visible_pills(rows.nth(i))
        if k == "maintenance":
            assert MAINT_PILL in pills and "Maintenance" not in pills, pills
        else:
            assert MAINT_PILL not in pills, pills


# ── closing the sheet after a tap ───────────────────────────────────────────────────────────────
def test_closing_after_a_tap_keeps_the_call_and_the_step_waits(page_as, expect):
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    call(node(pg, DANA))
    sheet(pg).locator('[data-outcome="answered"]').click()
    expect(sheet(pg).locator("[data-saved]")).to_be_visible()
    sheet(pg).locator('[data-act="close"]').click()
    expect(toasts(pg)).to_contain_text("The next step waits in Next steps to confirm.")
    expect(pg.locator("#week-count")).to_have_text("All 2 done")
    assert api(pg, "/api/bd/contacts/%d" % DANA_C)["pending_recommendation"] is not None
    more = pg.locator('#wk-tray [data-act="tray-more"]')
    if more.count():
        more.click()
    expect(pg.locator('#wk-tray .wk-tray-item[data-contact="%d"]' % DANA_C)).to_be_visible()
    pg.locator("#bd-toasts .toast-act", has_text="Show the sheet").click()
    expect(sheet(pg)).to_be_visible()
    assert sheet(pg).locator("[data-outcome]").count() == 0, "decide mode has no tiles"
    expect(sheet(pg).locator("[data-rec]")).to_contain_text("Suggested next step")
    expect(sheet(pg)).to_contain_text("Talked on")


def test_picking_wrong_person_then_closing_marks_needs_confirming(page_as, expect):
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    assert api(pg, "/api/bd/contacts/%d" % DANA_C)["contact"]["confirmed"] is True
    call(node(pg, DANA))
    sheet(pg).locator('[data-outcome="wrong"]').click()
    expect(sheet(pg).locator('[data-field="nrp"]')).to_be_visible()
    expect(sheet(pg).locator('[data-act="rec-confirm"]')).to_have_text("Save")
    sheet(pg).locator('[data-act="close"]').click()
    expect(toasts(pg)).to_contain_text("Marked as needs confirming.")
    pg.wait_for_function("c => BDApi.get(BDApi.path('contacts', c)).then(r => r.contact.confirmed === false)", arg=DANA_C)


def test_a_new_date_in_the_step_editor_is_read_out(page_as, expect):
    """The editor redraws on a chip, so its preview line is new each time and a live region drawn
    with its words is often not read out: the words go to BD's one live region (#bd-live)."""
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    call(node(pg, DANA))
    sheet(pg).locator('[data-outcome="answered"]').click()
    sheet(pg).locator('[data-act="rec-change"]').first.click()
    sheet(pg).locator('[data-chip="week"]').click()
    expect(sheet(pg).locator(".call-editor-preview")).to_have_text("New date: Wed, Nov 11")
    expect(pg.locator("#bd-live")).to_have_text("New date: Wed, Nov 11")
    assert sheet(pg).locator(".call-editor-preview").get_attribute("aria-live") is None


# ── whose week ──────────────────────────────────────────────────────────────────────────────────
def test_the_admin_is_greeted_and_asked_whose_week(page_as, expect):
    _, pg = page_as("/bd/", EMERY)
    expect(pg.locator("#week-sub")).to_have_text("Choose whose week to look at.")
    assert re.fullmatch(r"Good (morning|afternoon|evening), Emery", pg.inner_text("#wk-greeting").strip())
    expect(pg.locator("#owner-pick")).to_be_visible()
    assert pg.locator("#owner-pick").input_value() == "", "nobody is preselected"
    assert pg.locator("[data-pick]").all_inner_texts() == ["Avery Quill", "Blair Fenn"]
    assert pg.locator("[data-task]").count() == 0 and pg.locator("#summary").is_hidden()
    assert pg.locator("#wk-tray").is_hidden()


def test_tapping_a_salesperson_opens_their_week_with_the_pace_card(page_as, expect):
    _, pg = page_as("/bd/", EMERY)
    pg.locator("[data-pick]", has_text="Avery Quill").click()
    expect(pg.locator("#wk-greeting")).to_have_text("Avery's week")
    wait_week(pg)
    expect(pg.locator("#summary")).to_be_visible()
    assert pg.locator("[data-task]").count() == 3 and pg.locator("[data-pick]").count() == 0
    expect(pg.locator("#owner-pick")).to_have_value("1")


def test_choosing_someone_shows_their_week_and_the_page_remembers_it(page_as, expect):
    _, pg = page_as("/bd/", EMERY)
    expect(pg.locator("#owner-pick")).to_be_visible()
    pg.select_option("#owner-pick", label="Blair Fenn")
    expect(pg.locator("#wk-greeting")).to_have_text("Blair's week")
    wait_week(pg)
    assert "owner=2" in pg.url
    assert pg.locator("[data-task]").count() == 2, "Rory open, Sam taken off"
    pg.reload()
    expect(pg.locator("#wk-greeting")).to_have_text("Blair's week")
    expect(pg.locator("#owner-pick")).to_have_value("2")


def test_a_link_with_an_owner_goes_straight_to_that_list(page_as, expect):
    _, pg = page_as("/bd/?owner=1", DEVON)
    expect(pg.locator("#wk-greeting")).to_have_text("Avery's week")
    expect(pg.locator("#owner-pick")).to_have_value("1")


# ── widths, carried over ────────────────────────────────────────────────────────────────────────
def test_at_1280_beside_the_tray_rows_stay_two_lines(page_as):
    """Beside the tray a row is name over company on the left and the pill over the reason on the
    right: never the four-line stack. On the pinned Next up, More sits beside Call. With nothing
    pinned, BD put Not this week beside Call too; beside the tool's sidebar and the tray the card is
    narrower, so Call has its own line and Not this week and More share the next (two lines, never
    three: a deviation from BD noted for Hanz in the PR). Measured in DejaVu Sans, the font CI's
    Linux falls back to and wider than Windows' or a Mac's: a company name that fits there fits
    everywhere (#838: "Prairie Ridge Builders LLC" wrapped on CI and passed on Windows)."""
    _, pg = page_as("/bd/", AVERY, DESKTOP)
    wait_week(pg)
    pg.add_style_tag(content='#main, #main * { font-family: "DejaVu Sans", sans-serif !important; }')
    settled(pg)
    heights = pg.locator("#wk-rest .wk-row").evaluate_all("rs => rs.map(r => r.getBoundingClientRect().height)")
    assert heights and max(heights) <= 96, heights
    call_box = pg.locator(NEXT_CALL).bounding_box()
    more = pg.locator(NEXT_MORE).bounding_box()
    assert abs(more["y"] - call_box["y"]) <= 24, "More sits beside Call"
    log_by_api(pg, HAL_C, "email")
    reload_week(pg)
    settled(pg)
    assert node(pg, DANA).evaluate("el => !!el.closest('#wk-next')")
    call_box = pg.locator(NEXT_CALL).bounding_box()
    snooze = pg.locator('#wk-next [data-act="snooze"]').bounding_box()
    more = pg.locator(NEXT_MORE).bounding_box()
    assert abs(more["y"] - snooze["y"]) <= 4, "Not this week and More share a line"
    assert snooze["y"] - call_box["y"] <= call_box["height"] + 16, "the buttons take two lines at most"
    card = pg.locator("#wk-next .wk-next").bounding_box()
    assert more["x"] + more["width"] <= card["x"] + card["width"], "nothing runs out of the card"


def test_on_a_phone_the_pin_fits_and_its_buttons_stay_tappable(page_as, expect):
    _, pg = page_as("/bd/", AVERY, PHONE)
    wait_week(pg)
    card = pg.locator("#wk-next [data-task]")
    expect(pg.locator("#wk-due-line")).to_have_text(DUE_ONE)
    expect(card.locator("p.wk-next-stays")).to_be_visible()
    assert MAINT_PILL in visible_pills(card)
    for name, sel in (("Call", NEXT_CALL), ("More", NEXT_MORE + ":visible")):
        b = pg.locator(sel).first.bounding_box()
        assert b["height"] >= 44 - 0.5 and b["width"] >= 44 - 0.5, "%s is %sx%s" % (name, b["width"], b["height"])
    for name, sel in (("stays line", "#wk-next p.wk-next-stays"), ("due line", "#wk-due-line")):
        b = pg.locator(sel).first.bounding_box()
        assert b["x"] >= -0.5 and b["x"] + b["width"] <= PHONE["width"] + 0.5, "%s is off screen: %r" % (name, b)
    acts, text = open_more(pg, card)
    assert "snooze" not in acts and "done" not in acts and "Not this week" not in text, (acts, text)


def test_on_a_phone_a_row_with_no_phone_number_can_still_be_taken_off(env, page_as, expect):
    """A row's More menu is hidden on a phone because tapping Call opens the call sheet. A contact
    with no phone number has no Call, so its row keeps More there, and a keyboard reaches it."""
    _base, url, _b = env
    run_sql(url, "update contacts set phone = null where id = %s", (DANA_C,))
    _, pg = page_as("/bd/", AVERY, PHONE)
    wait_week(pg)
    more = node(pg, DANA).locator('.wk-co-head [data-act="more"]')
    expect(more).to_be_visible()
    b = more.bounding_box()
    assert b["x"] + b["width"] <= PHONE["width"] + 0.5 and b["height"] >= 44 - 0.5, b
    more.focus()
    pg.keyboard.press("Enter")
    pg.locator(".menu").wait_for()
    assert "snooze" in menu_acts(pg)
    pg.locator('.menu [data-act="snooze"]').focus()
    pg.keyboard.press("Enter")
    expect(toasts(pg)).to_contain_text("Taken off this week.")
    expect(pg.locator('#wk-done [data-task="%d"][data-status="snoozed"]' % DANA)).to_have_count(1)


# ── one row per company (#828) ───────────────────────────────────────────────────────────────────
# Sue Marlow, a second BD person of Avery's at Prairie Ridge Builders LLC (Dana's company), added for
# these tests only: Dana's row (task 302) then holds Dana (to call first) and Sue.
LONG_NAME = "Prairie Ridge Builders and Industrial Flooring Contractors of Greater Kansas City LLC"


def add_sue(env, long_name=False):
    url = env[1]
    if long_name:
        run_sql(url, "update companies set name = %s where id = 10", (LONG_NAME,))
    return run_sql(url, "insert into contacts (company_id, name, title, phone, email, category, owner_id, source,"
                        " confirmed) values (10, 'Sue Marlow', 'Estimator', '913-555-0107', 'sue.marlow@example.com',"
                        " 'bd', 1, 'manual', true) returning id")[0]["id"]


def test_a_company_row_opens_with_a_click_enter_or_space_and_says_so(env, page_as, expect):
    sue = add_sue(env)
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    row = node(pg, DANA)
    toggle = row.locator('[data-act="toggle"]')
    people = row.locator(".wk-co-body")
    assert row.locator(".wk-co-name").inner_text().strip() == "Prairie Ridge Builders LLC"
    assert row.locator(".wk-co-first").inner_text().strip() == "Dana Whitlow · Project Manager · +1 more"
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(people).to_be_hidden()
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(row.locator('[data-person="%d"]' % sue)).to_be_visible()
    assert row.locator("[data-person]").evaluate_all("els => els.map(e => +e.dataset.person)") == [DANA_C, sue]
    expect(row.locator('[data-person="%d"]' % sue)).to_contain_text("Estimator · 913-555-0107")
    expect(row.locator('[data-person="%d"]' % sue)).to_contain_text("No live talk yet")
    pg.keyboard.press("Enter")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(people).to_be_hidden()
    pg.keyboard.press("Space")
    expect(toggle).to_have_attribute("aria-expanded", "true")
    assert toggle.evaluate("el => el === document.activeElement"), "the toggle keeps focus"
    # a click on the head's reason opens and closes it too
    row.locator(".wk-co-head .wk-reason").click()
    expect(toggle).to_have_attribute("aria-expanded", "false")
    assert pg.locator("[data-task]").count() == 3, "Hal's Kaw Valley row, Dana's company row and Priya's done row"


def test_calling_someone_else_there_logs_on_them_and_closes_the_row(env, page_as, expect):
    """The call sheet logs on the person called (Sue), not the person to call first (Dana); the row
    closes once (the 10 is all done), and its done line names Sue."""
    sue = add_sue(env)
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    dana_before = len(history(pg, DANA_C))
    node(pg, DANA).locator('[data-act="toggle"]').click()
    node(pg, DANA).locator('[data-person="%d"] [data-act="call"]' % sue).click()
    expect(sheet(pg)).to_be_visible()
    sheet(pg).locator('[data-outcome="voicemail"]').click()
    expect(sheet(pg).locator("[data-saved]")).to_contain_text("Saved as Voicemail")
    calls = history(pg, sue)
    assert [(c["kind"], c["outcome"]) for c in calls] == [("voicemail", "voicemail")], calls
    assert len(history(pg, DANA_C)) == dana_before, "nothing logged on Dana"
    done = pg.locator('#wk-done [data-task="%d"][data-status="done"]' % DANA)
    expect(done.locator(".wk-outcome")).to_have_text("Sue Marlow: Voicemail · Wed, Nov 4")
    expect(pg.locator("#week-count")).to_have_text("All 2 done")
    w = week_json(pg)
    assert (w["done_count"], w["total"]) == (2, 2)


def test_not_the_right_person_flags_that_person_and_the_row_stays_open(env, page_as, expect):
    """Sue is marked not the right person from her own menu inside the row: she needs confirming,
    Dana does not, and the row stays open because Dana can still be called."""
    sue = add_sue(env)
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    row = node(pg, DANA)
    row.locator('[data-act="toggle"]').click()
    row.locator('[data-person="%d"] [data-act="more"]' % sue).click()
    acts = menu_acts(pg)
    assert acts == ["log-meeting", "nrp", "open"], acts
    pg.locator('.menu [data-act="nrp"]').click()
    expect(sheet(pg).locator('[data-field="nrp"]')).to_be_visible()
    sheet(pg).locator('[data-act="rec-confirm"]').click()
    expect(toasts(pg)).to_contain_text("Marked as needs confirming.")
    assert api(pg, "/api/bd/contacts/%d" % sue)["contact"]["confirmed"] is False
    assert api(pg, "/api/bd/contacts/%d" % DANA_C)["contact"]["confirmed"] is True
    expect(pg.locator('#wk-rest [data-task="%d"][data-status="open"]' % DANA)).to_have_count(1)
    reload_week(pg)
    row = node(pg, DANA)
    row.locator('[data-act="toggle"]').click()
    expect(row.locator('[data-person="%d"]' % sue)).to_contain_text("Not the right person")
    assert "1 of 2 done" in summary(pg)


def test_after_not_the_right_person_the_rows_call_dials_someone_else_there(env, page_as, expect):
    """Dana is marked not the right person on her own row: the row stays open (Sue can be called),
    and the row's Call now dials Sue (913-555-0107), not the person just flagged."""
    sue = add_sue(env)
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    row = node(pg, DANA)
    expect(row.locator('.wk-row-call [data-act="call"]')).to_have_attribute("href", "tel:+19135550101")
    row.locator('[data-act="toggle"]').click()
    row.locator('[data-person="%d"] [data-act="more"]' % DANA_C).click()
    pg.locator('.menu [data-act="nrp"]').click()
    expect(sheet(pg).locator('[data-field="nrp"]')).to_be_visible()
    sheet(pg).locator('[data-act="rec-confirm"]').click()
    expect(toasts(pg)).to_contain_text("Marked as needs confirming.")
    row = pg.locator('#wk-rest [data-task="%d"][data-status="open"]' % DANA)
    expect(row.locator('.wk-row-call [data-act="call"]')).to_have_attribute("href", "tel:+19135550107")
    expect(row.locator(".wk-co-first")).to_have_text("Sue Marlow · Estimator · +1 more")
    assert row.locator("[data-person]").evaluate_all("els => els.map(e => +e.dataset.person)") == [sue, DANA_C]


@pytest.mark.parametrize("act", ["done", "snooze"])
def test_on_a_phone_a_row_button_leaves_focus_on_the_page(env, page_as, act):
    """On a phone the Done section starts closed, so the row's Undo is hidden after "Done, nothing to
    log": focus goes to the next thing on show (the Done toggle), never to <body>. The same for "Not
    this week" from the opened row."""
    add_sue(env)
    _, pg = page_as("/bd/", AVERY, PHONE)
    wait_week(pg)
    settled(pg)
    row = node(pg, DANA)
    row.locator('[data-act="toggle"]').click()
    row.locator('.wk-co-foot [data-act="%s"]' % act).click()
    pg.wait_for_selector('[data-task="%d"]:not([data-status="open"])' % DANA, state="attached", timeout=10000)
    pg.wait_for_timeout(300)
    assert focus_is_on_the_page(pg), "focus fell to <body> after %s at 390" % act


def test_done_on_the_opened_row_closes_the_whole_company(env, page_as, expect):
    add_sue(env)
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    row = node(pg, DANA)
    row.locator('[data-act="toggle"]').click()
    row.locator('.wk-co-foot [data-act="done"]').click()
    expect(toasts(pg)).to_contain_text("Done. Nothing logged.")
    expect(pg.locator('#wk-done [data-task="%d"][data-status="done"]' % DANA)).to_have_count(1)
    expect(pg.locator("#week-count")).to_have_text("All 2 done")
    w = week_json(pg)
    assert [r["status"] for r in w["rows"] if r["id"] == DANA] == ["done"]


@pytest.mark.parametrize("viewport", [PHONE, {"width": 320, "height": 700}], ids=["390", "320"])
def test_company_rows_fit_a_phone_with_a_long_name(env, page_as, expect, viewport):
    """Long labels wrap (a long company name, a title, a next step); nothing scrolls sideways, open or
    closed, and the toggle and every Call stay big enough to tap."""
    sue = add_sue(env, long_name=True)
    run_sql(env[1], "update contacts set next_step = 'Send the epoxy sample board and the cove base detail',"
                    " next_step_date = '2026-11-06' where id = %s", (DANA_C,))
    _, pg = page_as("/bd/", AVERY, viewport)
    wait_week(pg)
    settled(pg)
    assert sideways(pg) <= 1, "closed rows scroll sideways at %d" % viewport["width"]
    row = node(pg, DANA)
    toggle = row.locator('[data-act="toggle"]')
    toggle.click()
    expect(row.locator('[data-person="%d"]' % sue)).to_be_visible()
    assert sideways(pg) <= 1, "an opened row scrolls sideways at %d" % viewport["width"]
    for el in [toggle] + [row.locator('[data-person] [data-act="call"]').nth(i) for i in range(2)]:
        b = el.bounding_box()
        assert b["height"] >= 44 - 0.5 and b["x"] + b["width"] <= viewport["width"] + 0.5, b
    card = pg.locator("#wk-rest .card").bounding_box()
    for sel in (".wk-co-name", ".wk-p-facts", ".wk-p-who"):
        for b in [x.bounding_box() for x in row.locator(sel).all() if x.is_visible()]:
            assert b["x"] + b["width"] <= card["x"] + card["width"] + 0.5, (sel, b)



ONE_WORD = "Northwesternconstructionmanagementservices"   # one 42-letter word: nothing to break at


@pytest.mark.parametrize("viewport", [PHONE, {"width": 320, "height": 700}], ids=["390", "320"])
def test_the_next_up_card_fits_a_phone_with_a_one_word_company_name(env, page_as, expect, viewport):
    """The Next up card names its company twice on a phone: under the person, and as "Also at <company>"
    over the others there. A company name that is one long word must wrap inside the card: every line
    of text in it ends at or before the card's right edge, and nothing scrolls sideways."""
    run_sql(env[1], "update companies set name = %s where id = %s", (ONE_WORD, KAW))
    _, pg = page_as("/bd/", AVERY, viewport)
    wait_week(pg)
    pg.locator("#ten-more-btn").click()
    expect(toasts(pg)).to_contain_text("added below.")
    expect(pg.locator('#wk-next [data-person="%d"]' % NORA_C)).to_have_count(1)
    expect(pg.locator("#wk-next .wk-meta-narrow")).to_contain_text(ONE_WORD)
    expect(pg.locator("#wk-next .wk-next-also .wk-next-label2")).to_contain_text(ONE_WORD)
    settled(pg)
    assert sideways(pg) <= 1, "the page scrolls sideways at %d" % viewport["width"]
    over = pg.evaluate("""() => {
      const card = document.querySelector('#wk-next .wk-next').getBoundingClientRect();
      const walk = document.createTreeWalker(document.getElementById('wk-next'), NodeFilter.SHOW_TEXT);
      const out = [];
      for (let n = walk.nextNode(); n; n = walk.nextNode()) {
        if (!n.textContent.trim() || !n.parentElement.offsetParent) continue;
        const r = document.createRange();
        r.selectNodeContents(n);
        for (const b of r.getClientRects()) {
          if (b.width && b.right > card.right + 0.5) out.push([n.parentElement.className, n.textContent.trim(), b.right, card.right]);
        }
      }
      return out;
    }""")
    assert not over, "text runs past the Next up card at %d: %r" % (viewport["width"], over)

# ── the Weekly 10 is ten companies (#828, the browser half) ─────────────────────────────────────
# Worked from the seed by hand. Prairie Ridge Builders LLC (company 10): Dana's live talk Oct 20 (101,
# answered), then her voicemail Nov 2 (102): 1 miss since the last live talk, and a try two days
# before the seed's Wednesday, so the company rests (3 days) unless a test moves 102 back.
PRAIRIE, BLUESTEM, KAW, OSAGE = 10, 16, 17, 18


def rest_over(env):
    """Dana's voicemail (102) moved back to Sat, Oct 25: still Prairie Ridge's one miss since the
    Oct 20 live talk, but no longer inside the company's 3-day rest."""
    run_sql(env[1], "update interactions set occurred_at = '2026-10-25 16:00:00+00' where id = 102")


def add_tess(env):
    """Tess Rowan, a made-up maintenance person of Avery's at Osage Plains Brewing (company 18), never
    followed up: due, like Nora."""
    return run_sql(env[1], "insert into contacts (company_id, name, title, phone, email, category, owner_id, source)"
                           " values (18, 'Tess Rowan', 'Facilities Lead', '785-555-0115',"
                           " 'tess.rowan@osageplains.example.com', 'maintenance', 1, 'manual') returning id")[0]["id"]


def people_in(nd):
    return nd.locator("[data-person]").evaluate_all("els => els.map(e => +e.dataset.person)")


def row_status(w, company_id):
    return [r["status"] for r in w["rows"] if r["company"]["id"] == company_id]


def test_the_friday_batch_gives_a_company_with_two_people_one_row(env, page_as, expect):
    """Avery's week emptied, Sue added beside Dana and the rest moved off Prairie Ridge: both would
    make the 10 on their own (Avery owns five BD people, fewer than the 5 + 5), yet the batch the
    admin runs gives Prairie Ridge one task and the page one row, holding Dana and Sue. Of Kaw
    Valley's people only Nora is due on a fresh list (never followed up; Hal's live talk of Aug 20 is
    inside his 3-a-year cycle), so "Due now" counts one account."""
    sue = add_sue(env)
    rest_over(env)
    run_sql(env[1], "delete from tasks where batch_id = 201")
    run_sql(env[1], "delete from task_batches where id = 201")
    _, pg = page_as("/bd/?owner=1", EMERY)
    pg.locator('[data-act="run-weekly"]').click()
    expect(toasts(pg)).to_contain_text("This week's list is ready.")
    wait_week(pg)
    w = week_json(pg, owner=1)
    at_prairie = [t["contact"]["id"] for t in w["tasks"] if t["contact"]["id"] in (DANA_C, sue)]
    assert len(at_prairie) == 1, "Prairie Ridge took %d slots" % len(at_prairie)
    assert [t["contact"]["id"] for t in w["tasks"] if t["kind"] == "maintenance"] == [NORA_C]
    shown = pg.locator("[data-task][data-company]").evaluate_all("els => els.map(e => +e.dataset.company)")
    assert len(shown) == len(set(shown)), "two rows for one company: %r" % shown
    prairie = pg.locator('[data-task][data-company="%d"]' % PRAIRIE)
    expect(prairie).to_have_count(1)
    assert sorted(people_in(prairie)) == sorted([DANA_C, sue])
    assert people_in(prairie)[0] == at_prairie[0], "the person suggested first leads the row"
    expect(pg.locator('[data-task][data-company="%d"]' % KAW)).to_have_count(1)
    expect(pg.locator("#wk-due-line")).to_have_text(DUE_ONE)


def test_a_voicemail_on_one_person_closes_the_row_once(env, page_as, expect):
    """Lena (Bluestem) is added to the 10 so the count can move without filling up: 1 of 3 done
    (Priya). A voicemail on Dana from Prairie Ridge's closed row closes the row: 2 of 3. A call to
    Sue the same week (logged on her contact, as the Contacts page would) changes nothing: still 2 of
    3, and Bluestem's row stays open."""
    sue = add_sue(env)
    _add_tasks(env[1], (27, "new", "open"))
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    assert "1 of 3 done" in summary(pg), summary(pg)
    row = node(pg, DANA)
    expect(row.locator(".wk-co-misses")).to_have_text("1 try since the last live talk")
    call(row)
    sheet(pg).locator('[data-outcome="voicemail"]').click()
    expect(sheet(pg).locator("[data-saved]")).to_contain_text("Saved as Voicemail")
    sheet(pg).locator('[data-act="close"]').click()
    expect(sheet(pg)).to_be_hidden()
    done = pg.locator('#wk-done [data-task="%d"][data-status="done"]' % DANA)
    expect(done.locator(".wk-outcome")).to_have_text("Dana Whitlow: Voicemail · Wed, Nov 4")
    expect(pg.locator("#summary")).to_contain_text("2 of 3 done")
    assert [(c["kind"], c["outcome"]) for c in history(pg, DANA_C)][0] == ("voicemail", "voicemail")
    log_by_api(pg, sue, "call", "no_answer")
    reload_week(pg)
    assert "2 of 3 done" in summary(pg), summary(pg)
    w = week_json(pg)
    assert (w["done_count"], w["total"]) == (2, 3)
    assert row_status(w, PRAIRIE) == ["done"] and row_status(w, BLUESTEM) == ["open"]
    expect(pg.locator('#wk-done [data-task="%d"][data-status="done"]' % DANA)).to_have_count(1)


def test_not_this_week_and_undo_act_on_the_company_row(env, page_as, expect):
    """Not this week from the opened row takes Prairie Ridge off as one row (Dana and Sue under it);
    the list does not refill and nothing counts as done. Undo puts the whole row back."""
    add_sue(env)
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    total = pg.locator("[data-task]").count()
    row = node(pg, DANA)
    row.locator('[data-act="toggle"]').click()
    row.locator('.wk-co-foot [data-act="snooze"]').click()
    expect(toasts(pg)).to_contain_text("Taken off this week.")
    off = pg.locator('#wk-done [data-task="%d"][data-status="snoozed"]' % DANA)
    expect(off.locator(".who-name")).to_have_text("Prairie Ridge Builders LLC")
    expect(off.locator(".who-sub")).to_have_text("Dana Whitlow, Sue Marlow")
    expect(pg.locator(".dot.is-off")).to_have_count(1)
    pg.wait_for_timeout(400)
    assert pg.locator("[data-task]").count() == total, "taking a row off must not pull in a new one"
    assert "1 of 2 done" in summary(pg)
    assert row_status(week_json(pg), PRAIRIE) == ["snoozed"]
    off.locator('[data-act="reopen"]').click()
    back = pg.locator('#wk-rest [data-task="%d"][data-status="open"]' % DANA)
    expect(back).to_have_count(1)
    expect(back.locator(".wk-co-first")).to_have_text("Dana Whitlow · Project Manager · +1 more")
    assert "1 of 2 done" in summary(pg)
    assert row_status(week_json(pg), PRAIRIE) == ["open"]


def test_due_now_is_one_row_per_maintenance_company(env, page_as, expect):
    """Nora moved to Osage Plains and Tess added there: Give Me 10 More pins both, as ONE Osage row
    under "Due now" ("Due now: 2 maintenance accounts": Kaw Valley and Osage). Following Nora up
    leaves the row while Tess is still due; following Tess up clears it."""
    nora_elsewhere(env)
    tess = add_tess(env)
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    pg.locator("#ten-more-btn").click()
    expect(pg.locator("#wk-due-line")).to_have_text("Due now: 2 maintenance accounts")
    due = pg.locator("#wk-due [data-task]")
    expect(due).to_have_count(1)
    assert due.get_attribute("data-company") == str(OSAGE)
    assert sorted(people_in(due)) == sorted([NORA_C, tess])
    assert "1 of 2 done" in summary(pg), "Due now is not part of the 10"
    assert pg.locator("[data-dot-task]").count() == 2
    log_by_api(pg, NORA_C, "call", "answered")
    reload_week(pg)
    expect(pg.locator("#wk-due [data-task]")).to_have_count(1)
    expect(pg.locator("#wk-due-line")).to_have_text("Due now: 2 maintenance accounts")
    log_by_api(pg, tess, "meeting")
    reload_week(pg)
    assert pg.locator("#wk-due").count() == 0
    expect(pg.locator("#wk-due-line")).to_have_text(DUE_ONE)


@pytest.mark.parametrize("state", ["open", "snoozed"])
def test_give_me_10_more_never_adds_a_company_already_on_the_list(env, page_as, expect, state):
    """Sue is at Prairie Ridge, on the 10 through Dana's row (open, or taken off: "in any state"), and
    the rest is moved off Prairie Ridge so only the list keeps her out. Give Me 10 More adds Bluestem
    and Cottonwood, never Sue, and "1 of 2 done" does not move."""
    sue = add_sue(env)
    rest_over(env)
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    if state == "snoozed":
        assert post_status(pg, "/api/bd/tasks/%d/snooze" % DANA) == {"ok": True}
        reload_week(pg)
    pg.locator("#ten-more-btn").click()
    extra = pg.locator(".wk-extra")
    expect(extra.locator(".section-title")).to_have_text("2 more (to get ahead)")
    names = sorted(t.strip() for t in extra.locator(".wk-co-name").all_inner_texts())
    assert names == ["Bluestem Logistics", "Cottonwood & Sons Paving"], names
    w = week_json(pg)
    assert sue not in [t["contact"]["id"] for t in w["tasks"]], "Sue was added for Prairie Ridge again"
    assert [r["company"]["id"] for r in w["rows"]].count(PRAIRIE) == 1
    assert "1 of 2 done" in summary(pg)
    assert (w["done_count"], w["total"]) == (1, 2)



def test_a_menu_choice_made_while_the_week_refreshes_still_acts(page_as, expect):
    """The cause of a flaky run: after a save, This Week refreshes in the background and redraws its
    rows. A More menu opened before that redraw (it sits on <body>) used to send its choice from the
    old, removed button, so "Done, nothing to log" did nothing. The week read that closing the call
    sheet starts is held back here until the menu is open."""
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    pg.evaluate("() => { window.__hold = false; window.__gate = new Promise(r => { window.__open = r; });"
                " const get = BDApi.get; BDApi.get = (p, ...a) => window.__hold && p.indexOf('/api/bd/week') === 0"
                " ? window.__gate.then(() => get.call(BDApi, p, ...a)) : get.call(BDApi, p, ...a); }")
    call(pg.locator("#wk-next"))
    sheet(pg).locator('[data-outcome="voicemail"]').click()
    expect(pg.locator("#wk-due-line")).to_have_count(0)
    pg.evaluate("() => { window.__hold = true; }")
    sheet(pg).locator('[data-act="close"]').click()
    expect(sheet(pg)).to_be_hidden()
    nxt = pg.locator("#wk-next [data-task]")
    expect(nxt).to_have_attribute("data-task", str(DANA))
    nxt.locator('[data-act="more"]:visible').first.click()
    expect(pg.locator(".menu")).to_be_visible()
    pg.evaluate("() => { window.__anchor = document.querySelector('#wk-next [data-act=\"more\"][aria-expanded=\"true\"]');"
                " window.__open(); }")
    pg.wait_for_function("() => window.__anchor && !window.__anchor.isConnected", timeout=10000)
    pg.locator('.menu [data-act="done"]').click()
    expect(pg.locator("#week-count")).to_have_text("All 2 done")
    assert [r["status"] for r in week_json(pg)["rows"] if r["id"] == DANA] == ["done"]

def test_a_manager_opens_a_company_row_but_cannot_act_on_it(env, page_as, expect):
    """Devon (manager) looks at Avery's week: Prairie Ridge's row opens to Dana and Sue with their
    titles and phones, beside the company score, and has no Call, More, Not this week or Done. The
    server refuses him the row's buttons (403) and the row stays open."""
    sue = add_sue(env)
    _, pg = page_as("/bd/?owner=1", DEVON)
    wait_week(pg)
    row = node(pg, DANA)
    expect(row).to_contain_text("Priority 82")
    row.locator('[data-act="toggle"]').click()
    expect(row.locator('[data-person="%d"]' % sue)).to_contain_text("Estimator · 913-555-0107")
    expect(row.locator('[data-person="%d"]' % DANA_C)).to_contain_text("Project Manager · 913-555-0101")
    for sel in ('[data-act="call"]', '[data-act="more"]', '[data-act="snooze"]', '[data-act="done"]', 'a[href^="tel:"]'):
        assert row.locator(sel).count() == 0, sel
    for act in ("snooze", "done"):
        got = post_status(pg, "/api/bd/tasks/%d/%s" % (DANA, act))
        assert got.get("status") == 403, (act, got)
    assert row_status(week_json(pg, owner=1), PRAIRIE) == ["open"]


# ── the maintenance banner at the top of This Week ───────────────────────────────────────────────
# Hanz: "could we have a banner for maintenance accounts", at the top of This Week. The seed's week has
# one maintenance company due (Kaw Valley: Hal), so the banner says "1 maintenance account due this
# week"; Give Me 10 More pins Nora (moved to Osage Plains first: a company of her own), so it says 2.
BANNER = "#wk-due-banner"
BANNER_ONE = "1 maintenance account due this week"
BANNER_STAYS = "They stay on the list until you log a call, meeting, email or text."
DEJAVU = '#main, #main * { font-family: "DejaVu Sans", sans-serif !important; }'


def active_id(pg):
    return pg.evaluate("() => document.activeElement && document.activeElement.id")


def test_the_banner_shows_the_seeds_due_count_above_the_progress_card(page_as, expect):
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    banner = pg.locator(BANNER)
    expect(banner).to_be_visible()
    expect(banner.locator("#wk-due-banner-h")).to_have_text(BANNER_ONE)
    expect(banner).to_contain_text(BANNER_STAYS)
    assert banner.get_attribute("aria-labelledby") == "wk-due-banner-h"
    assert banner.evaluate("el => el.tagName") == "SECTION"
    assert banner.locator("svg").count() == 1, "one icon"
    head, box, card = (pg.locator(".wk-head").bounding_box(), banner.bounding_box(), pg.locator("#summary").bounding_box())
    assert head["y"] + head["height"] <= box["y"] + 1, "under the page header"
    assert box["y"] + box["height"] <= card["y"] + 1, "above the progress card"
    assert abs(box["x"] - card["x"]) <= 1 and abs(box["width"] - card["width"]) <= 1, "as wide as the progress card"
    expect(pg.locator("#summary #wk-due-line")).to_have_text(DUE_ONE)       # the card's own line stays


def test_show_moves_focus_to_next_up_and_changes_nothing(page_as, expect):
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    before = week_json(pg)
    pg.locator(BANNER + ' [data-act="show-due"]').click()
    pg.wait_for_function("() => document.activeElement && document.activeElement.id === 'wk-next'", timeout=5000)
    assert focus_is_on_the_page(pg)
    expect(pg.locator("#wk-next [data-task]")).to_have_attribute("data-task", str(HAL))
    expect(pg.locator("#wk-next")).to_be_in_viewport()
    # By keyboard as well: Tab to Show, Enter.
    pg.locator(BANNER + ' [data-act="show-due"]').focus()
    pg.keyboard.press("Enter")
    pg.wait_for_function("() => document.activeElement && document.activeElement.id === 'wk-next'", timeout=5000)
    after = week_json(pg)
    assert [(r["id"], r["status"]) for r in after["rows"]] == [(r["id"], r["status"]) for r in before["rows"]]
    assert after["due_count"] == before["due_count"] == 1


def test_a_redraw_keeps_focus_on_show(page_as, expect):
    """A background refresh (here the one a saved call on Dana starts, held until focus is on Show)
    redraws the banner: focus stays on Show, it does not drop to <body>."""
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    pg.evaluate("() => { window.__hold = false; window.__gate = new Promise(r => { window.__open = r; });"
                " const get = BDApi.get; BDApi.get = (p, ...a) => window.__hold && p.indexOf('/api/bd/week') === 0"
                " ? window.__gate.then(() => get.call(BDApi, p, ...a)) : get.call(BDApi, p, ...a); }")
    pg.evaluate("() => { window.__hold = true; }")
    call(node(pg, DANA))
    sheet(pg).locator('[data-outcome="voicemail"]').click()
    sheet(pg).locator('[data-act="close"]').click()
    expect(sheet(pg)).to_be_hidden()
    pg.locator(BANNER + ' [data-act="show-due"]').focus()
    pg.evaluate("() => { window.__shown = document.activeElement; window.__open(); }")
    pg.wait_for_function("() => !window.__shown.isConnected", timeout=10000)
    expect(pg.locator(BANNER + ' [data-act="show-due"]')).to_be_focused()


def test_the_banner_goes_at_once_when_the_last_due_row_is_followed_up(page_as, expect):
    """A voicemail on Hal follows up Kaw Valley: the banner goes from what the save returned, even when
    every later read of the week fails, and the change is said in the page's live region."""
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    expect(pg.locator(BANNER)).to_be_visible()
    assert "maintenance" not in pg.locator("#live").text_content(), "the first paint announces nothing"
    pg.evaluate("() => { const get = BDApi.get; BDApi.get = (p, ...a) => p.indexOf('/api/bd/week') === 0"
                " ? Promise.reject(new Error('offline')) : get.call(BDApi, p, ...a); }")
    call(pg.locator("#wk-next"))
    sheet(pg).locator('[data-outcome="voicemail"]').click()
    expect(pg.locator(BANNER)).to_be_hidden()
    expect(pg.locator("#live")).to_have_text("No maintenance accounts due this week.")
    assert pg.locator(BANNER + " *").count() == 0


def test_the_banner_counts_a_second_pin_and_says_so(env, page_as, expect):
    nora_elsewhere(env)
    _, pg = page_as("/bd/", AVERY)
    wait_week(pg)
    expect(pg.locator("#wk-due-banner-h")).to_have_text(BANNER_ONE)
    pg.locator("#ten-more-btn").click()
    expect(pg.locator("#wk-due-banner-h")).to_have_text("2 maintenance accounts due this week")
    expect(pg.locator("#live")).to_have_text("2 maintenance accounts due this week.")
    pg.locator(BANNER + ' [data-act="show-due"]').click()
    pg.wait_for_function("() => document.activeElement && document.activeElement.id === 'wk-next'", timeout=5000)


def test_switching_whose_list_redraws_the_banner_for_that_list(page_as, expect):
    """Devon (manager) on Avery's week sees her banner; Blair's list has nothing due, so none; back on
    Avery's it shows again. A switch is said as "Showing <name>'s list.", not as a count change."""
    _, pg = page_as("/bd/?owner=1", DEVON)
    wait_week(pg)
    expect(pg.locator("#wk-due-banner-h")).to_have_text(BANNER_ONE)
    pg.select_option("#owner-pick", "2")
    expect(pg.locator("#wk-greeting")).to_have_text("Blair's week")
    wait_week(pg)
    expect(pg.locator(BANNER)).to_be_hidden()
    expect(pg.locator("#live")).to_have_text("Showing Blair Fenn's list.")
    pg.select_option("#owner-pick", "1")
    expect(pg.locator("#wk-greeting")).to_have_text("Avery's week")
    wait_week(pg)
    expect(pg.locator("#wk-due-banner-h")).to_have_text(BANNER_ONE)
    expect(pg.locator("#live")).to_have_text("Showing Avery Quill's list.")
    pg.locator(BANNER + ' [data-act="show-due"]').click()
    pg.wait_for_function("() => document.activeElement && document.activeElement.id === 'wk-next'", timeout=5000)


@pytest.mark.parametrize("viewport", [PHONE, {"width": 320, "height": 700}], ids=["390", "320"])
def test_on_a_phone_the_banner_wraps_and_show_is_reachable(page_as, expect, viewport):
    _, pg = page_as("/bd/", AVERY, viewport)
    wait_week(pg)
    pg.add_style_tag(content=DEJAVU)
    settled(pg)
    banner = pg.locator(BANNER)
    expect(banner).to_be_visible()
    over = sideways(pg)
    assert over <= 1, "scrolls sideways by %dpx at %d wide" % (over, viewport["width"])
    box = banner.bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= viewport["width"] + 0.5, box
    for sel in ("#wk-due-banner-h", ".wk-due-banner-sub", '[data-act="show-due"]'):
        b = banner.locator(sel).bounding_box()
        assert b["x"] >= box["x"] - 0.5 and b["x"] + b["width"] <= box["x"] + box["width"] + 0.5, (sel, b, box)
    ico, h = banner.locator(".wk-due-banner-ico").bounding_box(), banner.locator("#wk-due-banner-h").bounding_box()
    assert ico["x"] + ico["width"] <= h["x"] and ico["y"] < h["y"] + h["height"], ("the icon sits beside the heading", ico, h)
    show = banner.locator('[data-act="show-due"]')
    assert show.bounding_box()["height"] >= 44, "a thumb-sized button"
    show.click()
    pg.wait_for_function("() => document.activeElement && document.activeElement.id === 'wk-next'", timeout=5000)
    assert sideways(pg) <= 1
