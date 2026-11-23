"""One contact (/bd/contact.html) and Add a contact (/bd/add.html) in a real Chromium, against the live
app (#808).

BD's test_e2e_contact, moved with the page and rewritten for the live app: BD's mock data is gone, so
every test starts from the FIXTURE SEED (backend/bd/ops/fixture_seed.py), put back before each test,
on a server whose business day is pinned to the seed's Wednesday, 2026-11-04. The expected values are
worked by hand from the seed, never read back from the page's own rules:

  21 Dana Whitlow, Prairie Ridge Builders LLC (Avery's). Phone 913-555-0101. Next step "Send the
     epoxy sample board" Fri, Nov 6, promised Nov 5. Open task 302 (follow-up, priority 82). Calls:
     101 talked Tue, Oct 20, 7 min (her one live talk this year) and 102 a voicemail Mon, Nov 2, 35 s,
     both logged by Avery. A pending AI suggestion (401, "Send the spring schedule"). The BD cadence
     is quarterly: her next live talk is due 13 weeks after Oct 20, Tue, Jan 19, 2027.
  23 Marisa Cole, Cottonwood & Sons Paving (Avery's). Phone 816.555.0103, no city. A meeting Jun 15:
     1 of 4 live talks, behind. No task, no step, no suggestion.
  25 Priya Nandan: a missed call (104, the phone system's) waiting for a follow-up.
  27 Lena Ortiz, Bluestem Logistics (Avery's), with Sam Achebe (28) and Ines Varga (29). An override:
     monthly until Dec 31. One email (105), logged by Blair.
  30 Hal Brecken, Kaw Valley Cold Storage, maintenance: pinned on Avery's week (task 301). Last
     follow-up Aug 20, so the next is due 120 days on, Dec 18.
  31 Nora Lindqvist, maintenance, 2 live talks a year, never followed up: due now.
  32 Wes Calder, Osage Plains Brewing: nobody else there, never reached, no owner.
  33 D. Whitlow, Prairie Ridge Builders, Inc. (Blair's): a possible duplicate of Dana (Same email),
     no phone. Rory Sandell (22) works there too.

  Avery Quill (salesperson), Casey Moret (assistant), Devon Hale (manager), Emery Stoll (admin).

What it proves, for the ticket: the contact page logs each kind of entry, edits the person's own
entry and lets a BD admin delete one; confirm and archive work for the roles allowed; an assistant
adds a contact and a note and has no way to log a call; Add contact's company type-ahead and its
possible-duplicate warning; each BD section a role can use works and the others are not shown; no
role's view of either page links to a BD page that has not moved; desktop and phone width.

BD's own contact-page tests are carried over below, renamed where the seed's people differ from BD's
mock. The few that are not (the suggestion and follow-up routes are Phase 5 placeholders, and BD's own
phone top bar and tab bar are gone) are listed, one reason each, in the #808 PR.

Runs in the browser job of ci.yml (tests/_bd_browser.py: the live app on a seeded BD test database,
sign-in faked only inside the test process).
"""
import re

import pytest

from _bd_browser import (DESKTOP, MOVED_PAGES, NOT_BUILT, PHONE, SECTION_LANDED, Page, api, bd_links, browser,
                         focus_is_on_the_page, live_app_db, menu_acts, require_playwright, reseed, run_sql,
                         sideways, toasts)

AVERY = "avery.quill@example.com"         # salesperson
CASEY = "casey.moret@example.com"         # assistant
DEVON = "devon.hale@example.com"          # manager
EMERY = "emery.stoll@example.com"         # admin

DANA, MARISA, PRIYA, LENA, HAL, NORA, WES, DUPE = 21, 23, 25, 27, 30, 31, 32, 33

MAINT_RULE = "A follow-up comes due 120 days after the last call, meeting, email or text."


@pytest.fixture(scope="module")
def env():
    with live_app_db() as (base, url), browser() as b:
        yield base, url, b


@pytest.fixture
def page_as(env):
    base, url, b = env
    reseed(url)
    opened = []

    def _open(path, email, viewport=DESKTOP, wait="#cd-title"):
        p = Page(b, base, viewport, email=email)
        opened.append(p)
        pg = p.open_signed_in(path)
        if wait:
            pg.locator(wait).wait_for(timeout=15000)
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
def contact_path(cid, extra=""):
    return "/bd/contact.html?id=%d%s" % (cid, extra)


def contact(pg, cid):
    return api(pg, "/api/bd/contacts/%d" % cid)


def interactions(pg, cid):
    items = api(pg, "/api/bd/contacts/%d/interactions" % cid)["items"]
    return [it["interaction"] for it in items if it.get("type") == "interaction"]


def cad_card(pg):
    return pg.locator("#cd-cadence")


def cad_sheet(pg):
    """The cadence sheet: the one sheet that holds the override fields (BD) or the number (maintenance)."""
    return pg.locator(".sheet", has=pg.locator("#cd-f-cadence_override, #cd-f-frequency_per_year"))


def save_cadence(sheet):
    sheet.get_by_role("button", name="Save", exact=True).click()


def record_patches(pg):
    """Remember every PATCH body the page sends, in window.__patches as [path, body]."""
    pg.evaluate("""() => { window.__patches = []; const o = BDApi.patch;
        BDApi.patch = function (p, b) { window.__patches.push([p, b]); return o.apply(this, arguments); }; }""")


def patches(pg):
    return pg.evaluate("window.__patches")


def history_item(pg, words):
    return pg.locator("#cd-history .cd-tl-item", has_text=words)


def dismiss_suggestion(url):
    """Dana's pending AI suggestion put aside (as a decided one), so her card shows the step itself.
    Deciding a suggestion from the page is a Phase 5 placeholder, so the test arranges it."""
    run_sql(url, "update ai_recommendations set status = 'dismissed' where id = 401")


# ── confirm, and Call ────────────────────────────────────────────────────────────────────────────
def test_the_still_the_right_person_switch_lives_in_details(page_as, expect):
    _, pg = page_as(contact_path(DANA), AVERY)
    sw = pg.locator('#cd-details [data-act="confirm-toggle"]')
    assert pg.locator('[data-act="confirm-toggle"]').count() == 1, "one switch on the page"
    expect(sw).to_have_attribute("aria-checked", "true")
    sw.click()
    expect(sw).to_have_attribute("aria-checked", "false")
    assert contact(pg, DANA)["contact"]["confirmed"] is False
    expect(pg.locator("#cd-title")).to_have_text("Dana Whitlow")
    expect(pg.locator(".cd-head")).to_contain_text("Needs confirming")
    expect(toasts(pg)).to_contain_text("Marked as needs confirming.")
    sw.click()
    expect(sw).to_have_attribute("aria-checked", "true")
    assert contact(pg, DANA)["contact"]["confirmed"] is True


def test_call_is_a_tel_link_that_opens_the_call_sheet_with_this_weeks_task(page_as):
    """The page hands BDCall.open the contact and its task (BDCall.open is replaced to record it)."""
    _, pg = page_as(contact_path(DANA), AVERY)
    pg.evaluate("""() => { window.__opened = [];
        BDCall.open = o => window.__opened.push({id: o.contact.id, task: o.task && o.task.id, mode: o.mode,
                                                 started: !!o.startedAt, send: o.canSend}); }""")
    url = pg.url
    link = pg.locator('#cd-next [data-act="call"]')
    assert link.get_attribute("href") == "tel:+19135550101"
    assert link.inner_text().strip() == "Call 913-555-0101"
    link.click()
    pg.wait_for_timeout(200)
    assert pg.url == url, "a tel: link keeps the page (D14)"
    assert pg.evaluate("window.__opened") == [{"id": DANA, "task": 302, "mode": "call", "started": True, "send": True}]


def test_talked_from_the_contact_page_adds_a_live_talk_on_top(page_as, expect):
    _, pg = page_as(contact_path(MARISA), AVERY)
    assert contact(pg, MARISA)["contact"]["touches_this_year"] == 1
    pg.locator('#cd-next [data-act="call"]').click()
    sheet = pg.locator("#call-sheet")
    expect(sheet).to_be_visible()
    sheet.locator('[data-outcome="answered"]').click()
    expect(sheet.locator("[data-saved]")).to_contain_text("Talked")
    pg.keyboard.press("Escape")
    expect(sheet).to_be_hidden()
    # (History is newest first; the seed's "Added" line is stamped with the real clock, so entries are
    # found by their words, never by position.)
    top = history_item(pg, "Today")
    expect(top).to_have_count(1)
    expect(top.locator(".cd-tl-word")).to_have_text("Call")
    expect(top).to_contain_text("Live talk")
    assert contact(pg, MARISA)["contact"]["touches_this_year"] == 2
    expect(pg.locator("#cd-year .cd-big")).to_have_text("2 of 4")


# ── the next step ────────────────────────────────────────────────────────────────────────────────
def test_change_with_in_a_month_saves_the_same_day_next_month(env, page_as, expect):
    dismiss_suggestion(env[1])
    _, pg = page_as(contact_path(DANA), AVERY)
    card = pg.locator("#cd-next")
    expect(card.locator(".cd-step-title")).to_have_text("Send the epoxy sample board")
    expect(card).to_contain_text("Fri, Nov 6")
    card.locator('[data-act="step-change"]').click()
    action = card.locator('[data-field="recaction"]')
    expect(action).to_be_focused()
    expect(card.locator('[data-field="recpromised"]')).not_to_be_checked()
    action.fill("Send the sample board")
    card.locator('[data-chip="month"]').click()
    expect(card.locator('[data-chip="month"]')).to_have_attribute("aria-pressed", "true")
    expect(card).to_contain_text("New date: Fri, Dec 4")
    card.locator('[data-act="rec-save"]').click()
    expect(card.locator(".cd-step-title")).to_have_text("Send the sample board")
    expect(card).to_contain_text("Fri, Dec 4")
    expect(toasts(pg)).to_contain_text("Next step saved")
    c = contact(pg, DANA)["contact"]
    assert (c["next_step"], c["next_step_date"], c["promised_date"]) == ("Send the sample board", "2026-12-04", None)


def test_change_can_be_cancelled_and_a_past_day_is_refused(env, page_as, expect):
    dismiss_suggestion(env[1])
    _, pg = page_as(contact_path(DANA), AVERY)
    card = pg.locator("#cd-next")
    card.locator('[data-act="step-change"]').click()
    card.locator('[data-chip="pick"]').click()
    date = card.locator('[data-field="recdate"]')
    expect(date).to_be_visible()
    assert date.get_attribute("min") == "2026-11-04"
    date.fill("2026-11-01")
    card.locator('[data-act="rec-save"]').click()
    expect(card.locator(".field-error")).to_have_text("Pick today or a later day.")
    card.locator('[data-act="rec-cancel"]').click()
    expect(card.locator(".cd-step-title")).to_have_text("Send the epoxy sample board")
    assert contact(pg, DANA)["contact"]["next_step_date"] == "2026-11-06"


def test_clear_empties_the_step_and_undo_puts_it_back(env, page_as, expect):
    dismiss_suggestion(env[1])
    _, pg = page_as(contact_path(DANA), AVERY)
    card = pg.locator("#cd-next")
    card.locator('[data-act="step-clear"]').click()
    expect(card.locator(".cd-none")).to_have_text("No next step yet.")
    c = contact(pg, DANA)["contact"]
    assert (c["next_step"], c["next_step_date"], c["promised_date"]) == (None, None, None)
    toast = toasts(pg)
    expect(toast).to_contain_text("Next step cleared.")
    toast.get_by_role("button", name="Undo").click()
    expect(card.locator(".cd-step-title")).to_have_text("Send the epoxy sample board")
    c = contact(pg, DANA)["contact"]
    assert (c["next_step"], c["next_step_date"], c["promised_date"]) == \
        ("Send the epoxy sample board", "2026-11-06", "2026-11-05")


def test_suggest_one_offers_the_cadence_date_and_a_person_confirms_it(env, page_as, expect):
    """D13: rule based, from the contact's own next due date (13 weeks after Oct 20, quarterly), and
    only a suggestion until Confirm."""
    dismiss_suggestion(env[1])
    _, pg = page_as(contact_path(DANA), AVERY)
    card = pg.locator("#cd-next")
    card.locator('[data-act="step-clear"]').click()
    expect(card.locator(".cd-none")).to_be_visible()
    card.locator('[data-act="suggest"]').click()
    panel = card.locator("[data-suggest]")
    expect(panel).to_contain_text("Call Dana again")
    expect(panel).to_contain_text("Tue, Jan 19, 2027")
    expect(panel).to_contain_text("Suggested: 4 live talks a year")
    assert contact(pg, DANA)["contact"]["next_step"] is None, "a suggestion is not saved until a person confirms it"
    panel.locator('[data-act="suggest-confirm"]').click()
    expect(card.locator("[data-suggest]")).to_have_count(0)
    expect(card.locator(".cd-step-title")).to_have_text("Call Dana again")
    expect(toasts(pg)).to_contain_text("Next step saved: Call Dana again, Tue, Jan 19, 2027.")
    c = contact(pg, DANA)["contact"]
    assert (c["next_step"], c["next_step_date"]) == ("Call Dana again", "2027-01-19")


def test_a_never_reached_contact_gets_no_suggest_one(page_as, expect):
    _, pg = page_as(contact_path(WES), AVERY)
    card = pg.locator("#cd-next")
    expect(card.locator(".cd-none")).to_have_text("No next step yet.")
    assert card.locator('[data-act="suggest"]').count() == 0
    expect(card.locator('[data-act="call"]')).to_be_visible()
    expect(pg.locator("#cd-year")).to_contain_text("Never reached")
    expect(pg.locator("#cd-year")).to_contain_text("No live talk yet.")


def test_a_pending_suggestion_shows_and_deciding_it_meets_not_built_yet(page_as, expect):
    """The suggestion reads as BD's (AI and the usual rule only suggest). Confirm and Dismiss are the
    recommendation routes, Phase 5 placeholders: the page says so and the step stays as it was."""
    _, pg = page_as(contact_path(DANA), AVERY)
    card = pg.locator("#cd-next")
    panel = card.locator("[data-rec]")
    expect(panel).to_contain_text("Send the spring schedule")
    expect(panel).to_contain_text("AI suggestion")
    expect(panel).to_contain_text("Asked for it on the call.")
    for act in ("rec-confirm", "rec-change", "rec-dismiss"):
        expect(panel.locator('[data-act="%s"]' % act)).to_be_visible()
    expect(card.locator('[data-act="call"]')).to_have_count(1)
    panel.locator('[data-act="rec-confirm"]').click()
    expect(card).to_contain_text(NOT_BUILT)
    d = contact(pg, DANA)
    assert d["pending_recommendation"]["id"] == 401
    assert d["contact"]["next_step"] == "Send the epoxy sample board"


def test_a_missed_call_follow_up_meets_not_built_yet_and_is_never_a_live_talk(page_as, expect):
    _, pg = page_as(contact_path(PRIYA), AVERY)
    assert contact(pg, PRIYA)["missed_call"]["interaction_id"] == 104
    fu = pg.locator("#cd-fu-slot")
    expect(fu).to_contain_text("Send a follow-up?")
    fu.locator('[data-act="fu-pick"][data-ch="sms"]').click()
    expect(fu.locator(".field-error")).to_have_text(NOT_BUILT)
    assert [i["kind"] for i in interactions(pg, PRIYA)] == ["call"], "nothing is sent"
    assert contact(pg, PRIYA)["contact"]["touches_this_year"] == 0


# ── the Log menu and the Email / Text links ──────────────────────────────────────────────────────
def test_the_log_menu_lists_every_way_to_log(page_as, expect):
    _, pg = page_as(contact_path(DANA), AVERY)
    pg.locator('.cd-head [data-act="log-menu"]').click()
    assert menu_acts(pg) == ["log-call", "log-meeting", "log-hosted", "log-note", "snooze", "nrp"]
    expect(pg.locator(".menu")).to_contain_text("Log a hosted event")
    pg.keyboard.press("Escape")
    expect(pg.locator(".menu")).to_have_count(0)


@pytest.mark.parametrize("act, tiles, focused", [
    ("log-call", ["answered", "voicemail", "no_answer", "wrong"], '[data-outcome="answered"]'),
    ("log-meeting", ["meeting", "hosted"], '[data-outcome="meeting"]'),
    ("log-hosted", ["meeting", "hosted"], '[data-outcome="hosted"]'),
    ("nrp", [], '[data-field="nrp"]'),
], ids=["call", "meeting", "hosted", "nrp"])
def test_log_a_hosted_event_opens_the_sheet_in_meeting_mode_on_the_hosted_tile(page_as, expect, act, tiles, focused):
    """What a person sees: each Log menu item opens the one call sheet with its own tiles, and Log a
    hosted event lands on the hosted tile (the meeting sheet's second)."""
    _, pg = page_as(contact_path(DANA), AVERY)
    pg.locator('.cd-head [data-act="log-menu"]').click()
    pg.locator('.menu [data-act="%s"]' % act).click()
    sheet = pg.locator("#call-sheet")
    expect(sheet).to_be_visible()
    expect(sheet.locator(focused)).to_be_focused()
    if tiles:
        assert sheet.locator("[data-outcome]").evaluate_all("els => els.map(e => e.dataset.outcome)") == tiles


def test_a_meeting_can_be_logged_for_an_earlier_day(page_as, expect):
    _, pg = page_as(contact_path(MARISA), AVERY)
    n0 = len(interactions(pg, MARISA))
    pg.locator('.cd-head [data-act="log-menu"]').click()
    pg.locator('.menu [data-act="log-meeting"]').click()
    sh = pg.locator("#call-sheet")
    expect(sh.locator("#call-day")).to_have_value("2026-11-04")
    assert sh.locator("#call-day").get_attribute("max") == "2026-11-04"
    assert sh.locator("#call-min").count() == 0, "a meeting has no minutes"
    sh.locator("#call-day").fill("2026-11-09")
    sh.locator('[data-outcome="meeting"]').click()
    expect(sh.locator("#call-day-err")).to_contain_text("already happened")
    assert len(interactions(pg, MARISA)) == n0
    sh.locator("#call-day").fill("2026-10-30")
    sh.locator('[data-outcome="meeting"]').click()
    expect(sh.locator('[data-act="change-outcome"]')).to_be_visible()
    new = [i for i in interactions(pg, MARISA) if i["kind"] == "meeting"]
    assert len(interactions(pg, MARISA)) == n0 + 1 and new
    assert new[0]["occurred_at"].startswith("2026-10-30T12:00:00"), new[0]["occurred_at"]
    assert contact(pg, MARISA)["contact"]["last_live_at"].startswith("2026-10-30"), "the meeting is the last live talk"


def test_a_call_logged_later_keeps_its_day_and_minutes(page_as, expect):
    _, pg = page_as(contact_path(MARISA), AVERY)
    pg.locator('.cd-head [data-act="log-menu"]').click()
    pg.locator('.menu [data-act="log-call"]').click()
    sh = pg.locator("#call-sheet")
    sh.locator("#call-day").fill("2026-11-02")
    sh.locator("#call-min").fill("-3")
    sh.locator('[data-outcome="answered"]').click()
    expect(sh.locator("#call-min-err")).to_contain_text("number of minutes")
    sh.locator("#call-min").fill("7")
    sh.locator('[data-outcome="answered"]').click()
    expect(sh.locator('[data-act="change-outcome"]')).to_be_visible()
    calls = [i for i in interactions(pg, MARISA) if i["kind"] == "call" and i.get("duration_s") == 420]
    assert calls, "the minutes reached the call"
    assert calls[0]["occurred_at"].startswith("2026-11-02T12:00:00"), calls[0]["occurred_at"]


def test_the_call_button_sheet_has_no_day_field(page_as, expect):
    """A call made now (the Call button) is stamped now: Day and Minutes are for the Log menu only."""
    _, pg = page_as(contact_path(DANA), AVERY)
    pg.locator('#cd-next [data-act="call"]').click()
    expect(pg.locator("#call-sheet")).to_be_visible()
    assert pg.locator("#call-day").count() == 0 and pg.locator("#call-min").count() == 0


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["1280", "390"])
def test_focus_comes_back_to_the_page_after_a_saved_call(page_as, expect, viewport):
    _, pg = page_as(contact_path(MARISA), AVERY, viewport)
    pg.locator('[data-act="call"]:visible').first.click()
    sh = pg.locator("#call-sheet")
    expect(sh).to_be_visible()
    sh.locator('[data-outcome="voicemail"]').click()
    expect(sh.locator('[data-act="change-outcome"]')).to_be_visible()
    pg.keyboard.press("Escape")
    expect(sh).to_be_hidden()
    pg.wait_for_timeout(300)                     # the reload after the close
    assert focus_is_on_the_page(pg), "focus fell to <body> at %d wide" % viewport["width"]


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["1280", "390"])
def test_with_reduced_motion_every_sheet_and_dialog_takes_focus(page_as, expect, viewport):
    inside = "sel => !!document.activeElement.closest(sel)"
    _, pg = page_as(contact_path(MARISA), AVERY, viewport)
    pg.emulate_media(reduced_motion="reduce")
    pg.locator('[data-act="call"]:visible').first.focus()
    pg.keyboard.press("Enter")
    expect(pg.locator("#call-sheet")).to_be_visible()
    assert pg.evaluate(inside, "#call-sheet"), "the call sheet"
    pg.keyboard.press("Escape")
    expect(pg.locator("#call-sheet")).to_be_hidden()
    if viewport is DESKTOP:
        pg.locator('#cd-details [data-act="edit"]').click()
        expect(pg.locator("#cd-edit-sheet")).to_be_visible()
        assert pg.evaluate(inside, "#cd-edit-sheet"), "Edit details"
        pg.keyboard.press("Escape")
        expect(pg.locator("#cd-edit-sheet")).to_have_count(0)
    pg.locator('[data-act="archive"]').click()
    expect(pg.locator(".dialog")).to_be_visible()
    assert pg.evaluate(inside, ".dialog"), "the archive dialog"
    pg.keyboard.press("Escape")


def test_not_this_week_takes_the_task_off_with_undo(page_as, expect):
    _, pg = page_as(contact_path(DANA), AVERY)
    pg.locator('.cd-head [data-act="log-menu"]').click()
    pg.locator('.menu [data-act="snooze"]').click()
    off = pg.locator(".cd-off")
    expect(off).to_contain_text("Taken off this week.")
    assert contact(pg, DANA)["open_task"]["status"] == "snoozed"
    expect(pg.locator(".cd-head")).not_to_contain_text("On this week's list")
    off.locator('[data-act="snooze-undo"]').click()
    expect(pg.locator(".cd-head")).to_contain_text("On this week's list")
    assert contact(pg, DANA)["open_task"]["status"] == "open"


def test_an_email_out_can_be_logged_and_is_not_a_live_talk(page_as, expect):
    _, pg = page_as(contact_path(DANA), AVERY)
    link = pg.locator('.cd-head [data-act="mail-out"]')
    assert link.get_attribute("href") == "mailto:dana.whitlow@prairieridge.example.com"
    pg.evaluate("() => document.querySelector('[data-act=\"mail-out\"]').addEventListener('click', e => e.preventDefault())")
    link.click()
    ask = pg.locator(".cd-ask")
    expect(ask).to_contain_text("Did you send something?")
    ask.locator('[data-act="log-sent"]').click()
    top = history_item(pg, "Logged by Avery Quill.")
    expect(top).to_have_count(1)
    expect(top.locator(".cd-tl-word")).to_have_text("Email")
    expect(top).to_contain_text("Not a live talk")
    expect(top).to_contain_text("Today")
    expect(pg.locator(".cd-ask")).to_have_count(0)
    assert contact(pg, DANA)["contact"]["touches_this_year"] == 1


# ── an entry: edited by the one who logged it, deleted by a BD admin ─────────────────────────────
def test_a_salesperson_edits_her_own_entry_and_never_someone_elses(page_as, expect):
    """On Lena's page Avery may not change Blair's email; she logs a note and fixes its typo."""
    _, pg = page_as(contact_path(LENA), AVERY)
    email = history_item(pg, "Sent the coating options.")
    expect(email).to_have_count(1)
    assert email.locator('[data-act="entry-edit"], [data-act="entry-delete"]').count() == 0
    pg.locator("#cd-note").click()
    pg.locator("#cd-note-text").fill("Asked about the dock flor.")
    pg.locator('[data-act="note-save"]').click()
    note = history_item(pg, "Asked about the dock flor.")
    expect(note).to_have_count(1)
    assert note.locator('[data-act="entry-delete"]').count() == 0, "Delete is a BD admin's"
    note.locator('[data-act="entry-edit"]').click()
    box = pg.locator("#cd-entry-text")
    expect(box).to_be_focused()
    expect(box).to_have_value("Asked about the dock flor.")
    box.fill("Asked about the dock floor.")
    pg.locator('[data-act="entry-save"]').click()
    expect(toasts(pg)).to_contain_text("Entry saved.")
    expect(history_item(pg, "Asked about the dock floor.")).to_have_count(1)
    notes = [i for i in interactions(pg, LENA) if i["kind"] == "note"]
    assert [n["summary"] for n in notes] == ["Asked about the dock floor."]
    # Escape leaves an edit without saving
    history_item(pg, "Asked about the dock floor.").locator('[data-act="entry-edit"]').click()
    pg.locator("#cd-entry-text").fill("Something else")
    pg.keyboard.press("Escape")
    expect(pg.locator("#cd-entry-text")).to_have_count(0)
    assert [i["summary"] for i in interactions(pg, LENA) if i["kind"] == "note"] == ["Asked about the dock floor."]


def test_a_bd_admin_deletes_a_wrong_entry_after_asking(page_as, expect):
    _, pg = page_as(contact_path(LENA), EMERY)
    email = history_item(pg, "Sent the coating options.")
    email.locator('[data-act="entry-delete"]').click()
    dlg = pg.locator(".dialog")
    expect(dlg).to_contain_text("Delete this email?")
    expect(dlg).to_contain_text("It comes off Lena's history for good.")
    dlg.locator('[data-act="no"]').click()
    expect(pg.locator(".dialog")).to_have_count(0)
    assert [i["id"] for i in interactions(pg, LENA)] == [105]
    history_item(pg, "Sent the coating options.").locator('[data-act="entry-delete"]').click()
    pg.locator('.dialog [data-act="yes"]').click()
    expect(toasts(pg)).to_contain_text("Entry deleted.")
    expect(history_item(pg, "Sent the coating options.")).to_have_count(0)
    assert interactions(pg, LENA) == []


def test_only_a_bd_admin_sees_delete(page_as, expect):
    for email in (AVERY, CASEY, DEVON):
        _, pg = page_as(contact_path(DANA), email)
        expect(pg.locator("#cd-history .cd-tl-item").first).to_be_visible()
        assert pg.locator('[data-act="entry-delete"]').count() == 0, email
    _, pg = page_as(contact_path(DANA), EMERY)
    assert pg.locator('[data-act="entry-delete"]').count() == 2, "both of Dana's calls"


# ── roles ────────────────────────────────────────────────────────────────────────────────────────
def test_the_assistant_notes_edits_and_clears_a_flag_but_never_calls(page_as, expect):
    _, pg = page_as(contact_path(DUPE), CASEY)
    assert pg.locator('[data-act="call"]').count() == 0
    assert pg.locator('a[href^="tel:"]').count() == 0, "no Call button, and this contact has no number"
    expect(pg.locator("#cd-note")).to_be_visible()
    expect(pg.locator('#cd-details [data-act="edit"]')).to_be_visible()
    pg.locator('.cd-head [data-act="log-menu"]').click()
    assert menu_acts(pg) == ["log-note", "nrp"]
    pg.keyboard.press("Escape")
    # a note, saved on top of History
    pg.locator("#cd-note").click()
    pg.locator("#cd-note-text").fill("Front desk says this is Dana's old address.")
    pg.locator('[data-act="note-save"]').click()
    top = history_item(pg, "Front desk says this is Dana's old address.")
    expect(top.locator(".cd-tl-word")).to_have_text("Note")
    # the duplicate flag: shown, never blocking, cleared by the assistant
    dupe = pg.locator(".cd-dupe")
    expect(dupe).to_contain_text("Possible duplicate of Dana Whitlow (Same email).")
    assert dupe.locator("a").get_attribute("href") == "/bd/contact.html?id=21"
    dupe.locator('[data-act="dup-clear"]').click()
    expect(pg.locator(".cd-dupe")).to_have_count(0)
    assert contact(pg, DUPE)["contact"]["duplicate_of"] is None
    expect(pg.locator("#cd-others")).to_contain_text("Rory Sandell")


def test_an_assistant_has_no_way_to_log_a_call_anywhere_on_the_page(page_as, expect):
    """Not as a button, not in a menu, not from the phone bar, not after an Email link."""
    for viewport in (DESKTOP, PHONE):
        _, pg = page_as(contact_path(DANA), CASEY, viewport)
        assert pg.locator('[data-act="call"]').count() == 0
        pg.locator('[data-act="log-menu"]:visible').first.click()
        acts = menu_acts(pg)
        assert "log-call" not in acts and "log-meeting" not in acts and "log-hosted" not in acts, acts
        pg.keyboard.press("Escape")
        pg.evaluate("() => document.querySelector('[data-act=\"mail-out\"]').addEventListener('click', e => e.preventDefault())")
        pg.locator('[data-act="mail-out"]').click()
        pg.wait_for_timeout(200)
        assert pg.locator(".cd-ask").count() == 0


def test_the_assistant_sets_a_next_step_in_edit_details(page_as, expect):
    """The assistant has no Change / Clear, but Edit details is every field: she can fill a missing
    next step and its date in the Friday cleanup."""
    _, pg = page_as(contact_path(MARISA), CASEY)
    assert pg.locator('[data-act="step-change"]').count() == 0
    pg.locator('#cd-details [data-act="edit"]').click()
    sheet = pg.locator("#cd-edit-sheet")
    expect(sheet).to_be_visible()
    sheet.locator("#cd-f-next_step").fill("Send the paving price sheet")
    sheet.locator("#cd-f-next_step_date").fill("2026-10-01")
    sheet.locator('[data-act="edit-save"]').click()
    expect(sheet.locator("#cd-f-next_step_date-err")).to_contain_text("today or a later day")
    sheet.locator("#cd-f-next_step_date").fill("2026-11-12")
    sheet.locator("#cd-f-promised_date").fill("2026-11-13")
    sheet.locator('[data-act="edit-save"]').click()
    expect(toasts(pg)).to_contain_text("Saved.")
    c = contact(pg, MARISA)["contact"]
    assert c["next_step"] == "Send the paving price sheet"
    assert c["next_step_date"] == "2026-11-12" and c["promised_date"] == "2026-11-13"
    expect(pg.locator("#cd-next")).to_contain_text("Send the paving price sheet")


def test_a_salesperson_cannot_clear_a_duplicate_flag(page_as, expect):
    _, pg = page_as(contact_path(DUPE), AVERY)
    expect(pg.locator(".cd-dupe")).to_be_visible()
    assert pg.locator('[data-act="dup-clear"]').count() == 0


def test_the_manager_reads_and_changes_only_live_talks_a_year(page_as, expect):
    """A manager edits only how often to follow up. A maintenance contact has a number to edit
    (the cadence sheet); the full details form is never his."""
    _, pg = page_as(contact_path(NORA), DEVON)
    for hook in ('[data-act="call"]', '[data-act="log-menu"]', "#cd-note", '[data-act="archive"]',
                 '[data-act="step-change"]', '[data-act="step-clear"]', '[data-act="confirm-toggle"]',
                 '[data-act="suggest"]', ".cd-callbar", '[data-act="entry-edit"]'):
        assert pg.locator(hook).count() == 0, hook
    pg.locator("#cd-details").get_by_role("button", name="Edit follow-up cadence").click()
    sheet = cad_sheet(pg)
    expect(sheet).to_be_visible()
    fields = sheet.locator("input, select, textarea").evaluate_all("els => els.map(e => e.id)")
    assert fields == ["cd-f-frequency_per_year"]
    sheet.locator("#cd-f-frequency_per_year").fill("6")
    save_cadence(sheet)
    expect(toasts(pg)).to_contain_text("Saved.")
    expect(cad_sheet(pg)).to_have_count(0)
    assert contact(pg, NORA)["contact"]["frequency_per_year"] == 6
    expect(pg.locator("#cd-year .cd-big")).to_have_text("0 of 6")


def test_the_manager_still_sees_the_priority_score(page_as, expect):
    _, pg = page_as(contact_path(DANA), DEVON)
    expect(pg.locator(".cd-score")).to_have_text("Priority 82 this week")
    _, pg = page_as(contact_path(DANA), EMERY)          # a BD admin too, as on This Week (can.pick_owner)
    expect(pg.locator(".cd-score")).to_have_text("Priority 82 this week")
    _, pg = page_as(contact_path(DANA), AVERY)
    assert pg.locator(".cd-score").count() == 0, "the score is the manager's"


# ── details, others, archive ─────────────────────────────────────────────────────────────────────
def test_edit_details_checks_the_phone_and_saves_one_patch(page_as, expect):
    _, pg = page_as(contact_path(MARISA), AVERY)
    pg.locator('#cd-details [data-act="edit"]').click()
    sheet = pg.locator("#cd-edit-sheet")
    expect(sheet.locator("#cd-f-name")).to_be_focused()
    sheet.locator("#cd-f-phone").fill("555-01")
    sheet.locator("#cd-f-city").fill("Lenexa, KS")
    sheet.locator('[data-act="edit-save"]').click()
    expect(sheet.locator("#cd-f-phone-err")).to_contain_text("Enter a 10-digit phone number")
    assert contact(pg, MARISA)["contact"]["city"] is None, "nothing is saved while a field is wrong"
    sheet.locator("#cd-f-phone").fill("816-555-0113")
    sheet.locator('[data-act="edit-save"]').click()
    expect(toasts(pg)).to_contain_text("Saved.")
    expect(pg.locator(".cd-sub")).to_contain_text("Lenexa, KS")
    c = contact(pg, MARISA)["contact"]
    assert c["city"] == "Lenexa, KS" and c["phone_e164"] == "+18165550113"
    # tags: comma separated in the drawer, pills in Details (the closed sheet has gone first)
    expect(pg.locator("#cd-edit-sheet")).to_have_count(0)
    pg.locator('#cd-details [data-act="edit"]').click()
    sheet = pg.locator("#cd-edit-sheet")
    sheet.locator("#cd-f-tags").fill("paving, lot two ,")
    sheet.locator('[data-act="edit-save"]').click()
    expect(pg.locator("#cd-edit-sheet")).to_have_count(0)
    assert contact(pg, MARISA)["contact"]["tags"] == ["paving", "lot two"]
    expect(pg.locator("#cd-details .cd-tags .pill")).to_have_count(2)


def test_others_at_the_company_and_add_someone(page_as, expect):
    _, pg = page_as(contact_path(WES), AVERY)
    others = pg.locator("#cd-others")
    expect(others).to_contain_text("Others at Osage Plains Brewing")
    expect(others).to_contain_text("No one else here yet.")
    assert others.locator("a.btn").get_attribute("href") == "/bd/add.html?company=18"
    _, pg2 = page_as(contact_path(LENA), DEVON)
    others2 = pg2.locator("#cd-others")
    expect(others2.locator('a[href="/bd/contact.html?id=28"]')).to_have_text("Sam Achebe")
    expect(others2.locator('a[href="/bd/contact.html?id=29"]')).to_have_text("Ines Varga")
    assert others2.locator("a.btn").count() == 0, "a manager adds no one"


def test_archive_asks_first_then_restore_brings_them_back(page_as, expect):
    _, pg = page_as(contact_path(MARISA), AVERY)
    pg.locator('[data-act="archive"]').click()
    dlg = pg.locator(".dialog")
    expect(dlg).to_contain_text("Archive Marisa Cole?")
    expect(dlg).to_contain_text("Their history is kept.")
    dlg.locator('[data-act="no"]').click()
    expect(pg.locator(".dialog")).to_have_count(0)
    assert contact(pg, MARISA)["contact"].get("archived_at") in (None, "")
    pg.locator('[data-act="archive"]').click()
    expect(pg.locator(".dialog input")).to_be_focused()
    pg.locator(".dialog input").fill("Company closed")
    pg.locator('.dialog [data-act="yes"]').click()
    notice = pg.locator(".panel-info.cd-notice")
    expect(notice).to_contain_text("Archived on Nov 4, 2026.")
    assert contact(pg, MARISA)["contact"].get("archived_at")
    expect(pg.locator("#cd-history")).to_contain_text("Company closed")
    assert pg.locator('#cd-next [data-act="call"]').count() == 0, "an archived contact is off every list"
    notice.locator('[data-act="restore"]').click()
    expect(pg.locator(".panel-info.cd-notice")).to_have_count(0)
    assert not contact(pg, MARISA)["contact"].get("archived_at"), "the server leaves archived_at out once restored"


def test_the_manager_cannot_archive_or_confirm(page_as, expect):
    _, pg = page_as(contact_path(MARISA), DEVON)
    assert pg.locator('[data-act="archive"], [data-act="confirm-toggle"]').count() == 0
    expect(pg.locator("#cd-details")).to_contain_text("Still the right person?")


def test_a_missing_contact_says_so(env, expect):
    base, _url, b = env
    p = Page(b, base, email=AVERY)
    try:
        pg = p.open_signed_in(contact_path(999))
        expect(pg.locator("main")).to_contain_text("That contact isn't here")
        expect(pg.locator('main a[href="/bd/contacts.html"]')).to_have_text("Back to Contacts")
        assert p.errors == [], p.errors
    finally:
        p.close()


def test_history_icons_and_live_talk_pills(page_as, expect):
    _, pg = page_as(contact_path(DANA), AVERY)
    items = pg.locator("#cd-history .cd-tl-item")
    expect(items).to_have_count(3)
    call = history_item(pg, "Talked through the spring floor schedule.")
    expect(call.locator(".cd-tl-word")).to_have_text("Call")
    expect(call.locator(".pill-ok")).to_have_text("Live talk")
    expect(call).to_contain_text("Tue, Oct 20 · 7 min")
    assert "is-touch" in call.locator(".cd-tl-ico").get_attribute("class")
    vm = history_item(pg, "Left a message.")
    expect(vm.locator(".cd-tl-word")).to_have_text("Voicemail")
    expect(vm).to_contain_text("Mon, Nov 2 · 35 s")
    assert vm.locator(".pill-ok").count() == 0, "a voicemail is never a live talk"
    added = history_item(pg, "Imported from the workbook")
    expect(added.locator(".cd-tl-word")).to_have_text("Added")
    expect(added).to_contain_text("Imported from the workbook by Emery Stoll.")
    assert added.locator(".pill").count() == 0


def test_the_company_opens_its_account_and_back_goes_where_you_came_from(page_as, expect):
    """#810: Contacts has moved, so BD's links are back. The company opens its account on Contacts, and
    Back is This Week's when you came from it, else Contacts."""
    _, pg = page_as(contact_path(DANA, "&from=week"), AVERY)
    expect(pg.locator(".cd-sub")).to_contain_text("Project Manager at Prairie Ridge Builders LLC")
    back = pg.locator(".cd-back")
    expect(back).to_have_text("This Week")
    assert back.get_attribute("href") == "/bd/"
    back.click()
    pg.locator("#summary .wk-progress-in").wait_for(timeout=15000)
    _, pg = page_as(contact_path(DANA), AVERY)
    expect(pg.locator(".cd-back")).to_have_text("Contacts")
    company = pg.locator(".cd-sub a")
    expect(company).to_have_text("Prairie Ridge Builders LLC")
    assert company.get_attribute("href") == "/bd/contacts.html?company=10"
    company.click()
    opened = pg.locator('.ct-acct.is-open[data-acct="10"]')
    opened.wait_for(timeout=15000)
    expect(opened.locator(".ct-p-name")).to_have_text(["Dana Whitlow"])


# ── phone ────────────────────────────────────────────────────────────────────────────────────────
def test_phone_call_bar_and_folded_details(page_as, expect):
    _, pg = page_as(contact_path(DANA, "&from=week"), AVERY, PHONE)
    callbar = pg.locator(".cd-callbar")
    expect(callbar).to_be_visible()
    call = callbar.locator('[data-act="call"]')
    expect(call).to_have_text(re.compile(r"^\s*Call 913-555-0101\s*$"))
    expect(callbar.locator('[data-act="log-menu"]')).to_be_visible()
    expect(pg.locator('#cd-next [data-act="call"]')).to_be_hidden()
    cb = callbar.bounding_box()
    assert abs(cb["y"] + cb["height"] - PHONE["height"]) <= 1, "the call bar sits at the bottom of the screen"
    fold = pg.locator("#cd-details-fold")
    assert fold.evaluate("d => d.open") is False
    expect(pg.locator("#cd-details .cd-kv")).to_be_hidden()
    pg.locator("#cd-details summary").click()
    expect(pg.locator("#cd-details .cd-kv")).to_be_visible()
    assert sideways(pg) <= 1, "scrolls sideways at 390 wide"
    callbar.locator('[data-act="log-menu"]').click()
    assert menu_acts(pg)[0] == "log-call"


def test_desktop_keeps_details_open_and_has_no_call_bar(page_as, expect):
    _, pg = page_as(contact_path(DANA), AVERY)
    assert pg.locator("#cd-details-fold").evaluate("d => d.open") is True
    expect(pg.locator(".cd-callbar")).to_be_hidden()
    assert sideways(pg) <= 1


# ── follow-up cadence (the cadence rules, PR D) ──────────────────────────────────────────────────
def test_the_cadence_card_shows_the_global_cadence_in_words(page_as, expect):
    """A BD contact with no override follows the one BD cadence (quarterly), said in a plain sentence:
    no pill, the card sits between This year and Details, and the Details row names the cadence."""
    _, pg = page_as(contact_path(MARISA), AVERY)
    card = cad_card(pg)
    expect(card).to_be_visible()
    assert card.get_attribute("aria-labelledby") == "cd-cad-h"
    expect(card.locator("h2#cd-cad-h")).to_have_text("Follow-up cadence")
    expect(card.locator("p.cd-cad-line")).to_have_text("Follow up quarterly.")
    assert card.locator(".pill").count() == 0, "a global cadence has no pill"
    order = pg.evaluate("""() => { const q = s => document.querySelector(s);
        const before = (a, b) => !!(q(a).compareDocumentPosition(q(b)) & Node.DOCUMENT_POSITION_FOLLOWING);
        return [before('#cd-year', '#cd-cadence'), before('#cd-cadence', '#cd-details')]; }""")
    assert order == [True, True], "the card goes after This year and before Details"
    labels = pg.locator("#cd-details dt").all_inner_texts()
    assert "Follow-up cadence" in labels and "Live talks a year" not in labels, labels
    row = pg.locator("#cd-details .cd-kv-item", has=pg.locator("dt", has_text="Follow-up cadence"))
    expect(row.locator("dd")).to_have_text("Quarterly")


def test_the_cadence_card_shows_the_override_and_clear_puts_the_global_back(page_as, expect):
    """Lena has an override (monthly until Dec 31): the card says so with an Override pill. A new
    override is ONE patch with the word and its last day; Use the BD cadence sends only
    {cadence_override: null} and puts the global cadence back."""
    _, pg = page_as(contact_path(LENA), AVERY)
    card = cad_card(pg)
    expect(card.locator("p.cd-cad-line")).to_have_text("Follow up monthly until Dec 31, then back to quarterly.")
    pill = card.locator(".pill")
    expect(pill).to_have_count(1)
    expect(pill).to_have_text("Override")
    assert "pill-info" in pill.get_attribute("class")
    assert contact(pg, LENA)["contact"]["frequency_per_year"] == 12
    record_patches(pg)
    card.locator('[data-act="cadence"]').click()
    sheet = cad_sheet(pg)
    expect(sheet).to_be_visible()
    expect(sheet.locator("#cd-f-cadence_override")).to_have_value("monthly")
    expect(sheet.get_by_label("Until (last day)")).to_have_value("2026-12-31")
    opts = sheet.locator("#cd-f-cadence_override option").evaluate_all("els => els.map(e => [e.value, e.textContent.trim()])")
    assert opts == [["", "Use the BD cadence"], ["weekly", "Weekly"], ["monthly", "Monthly"], ["quarterly", "Quarterly"]]
    sheet.locator("#cd-f-cadence_override").select_option("weekly")
    sheet.locator("#cd-f-cadence_override_until").fill("2026-12-15")
    save_cadence(sheet)
    expect(toasts(pg)).to_contain_text("Saved.")
    expect(cad_sheet(pg)).to_have_count(0)
    assert patches(pg) == [["/api/bd/contacts/27", {"cadence_override": "weekly", "cadence_override_until": "2026-12-15"}]]
    expect(card.locator("p.cd-cad-line")).to_have_text("Follow up weekly until Dec 15, then back to quarterly.")
    c = contact(pg, LENA)["contact"]
    assert (c["cadence"], c["cadence_override"], c["cadence_override_until"], c["frequency_per_year"]) == \
        ("weekly", "weekly", "2026-12-15", 52)
    expect(pg.locator("#cd-history .cd-tl-item", has=pg.locator(".cd-tl-word", has_text="Cadence changed")).first).to_be_visible()
    card.locator('[data-act="cadence"]').click()
    sheet = cad_sheet(pg)
    expect(sheet).to_be_visible()
    clear = sheet.locator('[data-act="clear-override"]')
    expect(clear).to_have_text("Use the BD cadence")
    clear.click()
    expect(toasts(pg)).to_contain_text("Saved.")
    expect(cad_sheet(pg)).to_have_count(0)
    assert patches(pg)[-1] == ["/api/bd/contacts/27", {"cadence_override": None}]
    expect(card.locator("p.cd-cad-line")).to_have_text("Follow up quarterly.")
    assert card.locator(".pill").count() == 0
    c = contact(pg, LENA)["contact"]
    assert (c["cadence"], c["cadence_source"], c["cadence_override"], c["cadence_override_until"], c["frequency_per_year"]) == \
        ("quarterly", "global", None, None, 4)
    card.locator('[data-act="cadence"]').click()
    sheet = cad_sheet(pg)
    expect(sheet).to_be_visible()
    assert sheet.locator('[data-act="clear-override"]').count() == 0, "no override, nothing to clear"


def test_choosing_use_the_bd_cadence_and_saving_sends_a_null(page_as, expect):
    _, pg = page_as(contact_path(LENA), AVERY)
    record_patches(pg)
    cad_card(pg).locator('[data-act="cadence"]').click()
    sheet = cad_sheet(pg)
    sheet.locator("#cd-f-cadence_override").select_option("")
    save_cadence(sheet)
    expect(toasts(pg)).to_contain_text("Saved.")
    assert patches(pg) == [["/api/bd/contacts/27", {"cadence_override": None}]]
    assert contact(pg, LENA)["contact"]["cadence_override"] is None
    expect(cad_card(pg).locator("p.cd-cad-line")).to_have_text("Follow up quarterly.")


def test_an_expired_override_shows_the_global_cadence(env, page_as, expect):
    """An override whose last day has passed (Nov 3, the day before the seed's today) reads as the global
    cadence with no Override pill: the server derives it and the page reads cadence_source."""
    run_sql(env[1], "update contacts set cadence_override_until = '2026-11-03' where id = %s", (LENA,))
    _, pg = page_as(contact_path(LENA), AVERY)
    c = contact(pg, LENA)["contact"]
    assert (c["cadence_source"], c["cadence"]) == ("global", "quarterly")
    card = cad_card(pg)
    expect(card.locator("p.cd-cad-line")).to_have_text("Follow up quarterly.")
    assert card.locator(".pill").count() == 0
    expect(card.locator('[data-act="cadence"]')).to_have_text("Change cadence")


def test_a_maintenance_contact_shows_due_now_then_the_next_due_date(page_as, expect):
    """Nora was never followed up: due now, with the Due now pill and "No follow-up logged yet." An
    email logged from the page is a follow-up: the next is due 120 days on, Thu, Mar 4, 2027."""
    _, pg = page_as(contact_path(NORA), AVERY)
    card = cad_card(pg)
    expect(card.locator("p.cd-cad-line")).to_have_text("Follow-up due now.")
    pill = card.locator(".pill")
    expect(pill).to_have_count(1)
    expect(pill).to_have_text("Due now")
    assert "pill-warn" in pill.get_attribute("class")
    expect(card.locator("p.cd-cad-sub")).to_have_text("No follow-up logged yet. " + MAINT_RULE)
    expect(card.locator('[data-act="cadence"]')).to_have_text("Change live talks a year")
    pg.evaluate("() => document.querySelector('[data-act=\"mail-out\"]').addEventListener('click', e => e.preventDefault())")
    pg.locator('.cd-head [data-act="mail-out"]').click()
    pg.locator('.cd-ask [data-act="log-sent"]').click()
    expect(card.locator("p.cd-cad-line")).to_have_text("Next follow-up due Mar 4, 2027.")
    assert card.locator(".pill").count() == 0
    expect(card.locator("p.cd-cad-sub")).to_have_text(MAINT_RULE)
    assert contact(pg, NORA)["contact"]["maintenance_due_date"] == "2027-03-04"
    # Hal: followed up Aug 20, so not due until Dec 18
    _, pg2 = page_as(contact_path(HAL), AVERY)
    expect(cad_card(pg2).locator("p.cd-cad-line")).to_have_text("Next follow-up due Dec 18.")
    assert cad_card(pg2).locator(".pill").count() == 0


def test_a_pinned_maintenance_contact_has_one_maintenance_pill_and_no_take_off(env, page_as, expect):
    """Hal is pinned on Avery's week: the header says "Maintenance · due" once (the neutral Maintenance
    pill gives way, a Key account pill stays), and the Log menu cannot take him off this week. He is
    made a confirmed key account here, so his status pill is Key account, not Needs confirming."""
    run_sql(env[1], "update contacts set importance = 3, confirmed = true where id = %s", (HAL,))
    _, pg = page_as(contact_path(HAL), AVERY)
    pills = [re.sub(r"\s+", " ", t).strip() for t in pg.locator(".cd-head .pill").all_inner_texts()]
    assert pills.count("Maintenance · due") == 1 and "Maintenance" not in pills and "Key account" in pills, pills
    pg.locator('.cd-head [data-act="log-menu"]').click()
    assert "snooze" not in menu_acts(pg)


def test_the_override_sheet_shows_the_server_words_for_a_bad_date(page_as, expect):
    _, pg = page_as(contact_path(MARISA), AVERY)
    cad_card(pg).locator('[data-act="cadence"]').click()
    sheet = cad_sheet(pg)
    select, until = sheet.locator("#cd-f-cadence_override"), sheet.locator("#cd-f-cadence_override_until")
    expect(select).to_have_value("")
    assert until.get_attribute("min") == "2026-11-04", "the native picker greys out the days before today"
    select.select_option("weekly")
    save_cadence(sheet)
    expect(sheet.locator("#cd-f-cadence_override_until-err")).to_have_text("Pick the last day of the override.")
    assert until.get_attribute("aria-invalid") == "true"
    assert contact(pg, MARISA)["contact"]["cadence_override"] is None, "nothing is saved while a field is wrong"
    until.fill("2026-11-01")
    save_cadence(sheet)
    expect(sheet.locator("#cd-f-cadence_override_until-err")).to_have_text("Pick a day from today on.")
    assert contact(pg, MARISA)["contact"]["cadence_override"] is None
    until.fill("2026-12-31")
    save_cadence(sheet)
    expect(toasts(pg)).to_contain_text("Saved.")
    c = contact(pg, MARISA)["contact"]
    assert (c["cadence_override"], c["cadence_override_until"]) == ("weekly", "2026-12-31")


def test_the_last_day_is_locked_while_the_bd_cadence_is_chosen(page_as, expect):
    _, pg = page_as(contact_path(MARISA), AVERY)
    cad_card(pg).locator('[data-act="cadence"]').click()
    sheet = cad_sheet(pg)
    select, until = sheet.locator("#cd-f-cadence_override"), sheet.locator("#cd-f-cadence_override_until")
    expect(until).to_be_disabled()
    select.select_option("monthly")
    expect(until).to_be_enabled()
    until.fill("2026-12-31")
    select.select_option("")
    expect(until).to_be_disabled()
    expect(until).to_have_value("")
    save_cadence(sheet)
    expect(sheet.locator("#cd-f-cadence_override-err")).to_have_count(0)
    assert contact(pg, MARISA)["contact"]["cadence_override"] is None


def test_an_active_override_opens_with_its_last_day_unlocked(page_as, expect):
    _, pg = page_as(contact_path(LENA), AVERY)
    cad_card(pg).locator('[data-act="cadence"]').click()
    sheet = cad_sheet(pg)
    expect(sheet.locator("#cd-f-cadence_override")).to_have_value("monthly")
    until = sheet.locator("#cd-f-cadence_override_until")
    expect(until).to_be_enabled()
    expect(until).to_have_value("2026-12-31")


def test_the_last_day_of_an_override_can_be_today(page_as, expect):
    _, pg = page_as(contact_path(MARISA), AVERY)
    cad_card(pg).locator('[data-act="cadence"]').click()
    sheet = cad_sheet(pg)
    sheet.locator("#cd-f-cadence_override").select_option("monthly")
    sheet.locator("#cd-f-cadence_override_until").fill("2026-11-04")
    save_cadence(sheet)
    expect(toasts(pg)).to_contain_text("Saved.")
    expect(cad_card(pg).locator("p.cd-cad-line")).to_have_text("Follow up monthly until Nov 4, then back to quarterly.")


def test_a_bd_contact_has_no_live_talks_field_in_details_edit(page_as, expect):
    _, pg = page_as(contact_path(MARISA), AVERY)
    record_patches(pg)
    pg.locator('#cd-details [data-act="edit"]').click()
    sheet = pg.locator("#cd-edit-sheet")
    expect(sheet.locator("#cd-f-name")).to_be_visible()
    assert sheet.locator("#cd-f-frequency_per_year").count() == 0
    sheet.locator("#cd-f-city").fill("Olathe")
    sheet.locator('[data-act="edit-save"]').click()
    expect(toasts(pg)).to_contain_text("Saved.")
    assert patches(pg) == [["/api/bd/contacts/23", {"city": "Olathe"}]]
    _, pg2 = page_as(contact_path(NORA), AVERY)
    labels = pg2.locator("#cd-details dt").all_inner_texts()
    assert "Live talks a year" in labels and "Follow-up cadence" not in labels, labels
    pg2.locator('#cd-details [data-act="edit"]').click()
    sheet2 = pg2.locator("#cd-edit-sheet")
    expect(sheet2.locator("#cd-f-frequency_per_year")).to_have_value("2")


def test_the_details_row_says_the_override_in_words(page_as, expect):
    _, pg = page_as(contact_path(LENA), AVERY)
    row = pg.locator("#cd-details .cd-kv-item", has=pg.locator("dt", has_text="Follow-up cadence"))
    expect(row.locator("dd")).to_have_text("Monthly until Dec 31")
    assert "cd-kv-full" in row.get_attribute("class")
    _, pg2 = page_as(contact_path(MARISA), AVERY)
    plain_row = pg2.locator("#cd-details .cd-kv-item", has=pg2.locator("dt", has_text="Follow-up cadence"))
    expect(plain_row.locator("dd")).to_have_text("Quarterly")
    assert "cd-kv-full" not in plain_row.get_attribute("class")


def test_a_contact_switched_to_bd_in_details_sends_no_number(page_as, expect):
    _, pg = page_as(contact_path(NORA), AVERY)
    record_patches(pg)
    pg.locator('#cd-details [data-act="edit"]').click()
    sheet = pg.locator("#cd-edit-sheet")
    number = sheet.locator("#cd-f-frequency_per_year")
    expect(number).to_be_visible()
    number.fill("5")
    sheet.locator("#cd-f-category").select_option("bd")
    expect(number).to_be_hidden()
    sheet.locator("#cd-f-category").select_option("maintenance")
    expect(number).to_be_visible()
    expect(number).to_have_value("5")
    sheet.locator("#cd-f-category").select_option("bd")
    sheet.locator('[data-act="edit-save"]').click()
    expect(toasts(pg)).to_contain_text("Saved.")
    assert patches(pg) == [["/api/bd/contacts/31", {"category": "bd"}]], patches(pg)
    assert contact(pg, NORA)["contact"]["category"] == "bd"


def test_the_cadence_sheet_sends_one_patch_while_one_is_in_flight(page_as, expect):
    _, pg = page_as(contact_path(LENA), AVERY)
    pg.evaluate("""() => { window.__patches = []; const o = BDApi.patch;
        BDApi.patch = function (p, b) { window.__patches.push([p, b]); const a = arguments, t = this;
          return new Promise(function (r) { setTimeout(r, 1500); }).then(function () { return o.apply(t, a); }); }; }""")
    cad_card(pg).locator('[data-act="cadence"]').click()
    sheet = cad_sheet(pg)
    sheet.locator('[data-act="clear-override"]').click()
    save = sheet.locator('[data-act="edit-save"]')
    expect(save).to_be_disabled()
    expect(sheet.locator('[data-act="clear-override"]')).to_be_disabled()
    pg.evaluate("() => document.getElementById('cd-edit').requestSubmit()")
    expect(toasts(pg)).to_contain_text("Saved.")
    expect(cad_sheet(pg)).to_have_count(0)
    assert patches(pg) == [["/api/bd/contacts/27", {"cadence_override": None}]], patches(pg)


def test_a_maintenance_contact_changes_the_number_in_the_cadence_sheet(page_as, expect):
    _, pg = page_as(contact_path(NORA), AVERY)
    cad_card(pg).locator('[data-act="cadence"]').click()
    sheet = cad_sheet(pg)
    expect(sheet.locator("#cd-f-frequency_per_year")).to_have_value("2")
    assert sheet.locator("#cd-f-cadence_override").count() == 0, "a maintenance contact has no override"
    sheet.locator("#cd-f-frequency_per_year").fill("0")
    save_cadence(sheet)
    expect(sheet.locator("#cd-f-frequency_per_year-err")).to_have_text("Use a whole number from 1 to 52.")
    sheet.locator("#cd-f-frequency_per_year").fill("4")
    save_cadence(sheet)
    expect(toasts(pg)).to_contain_text("Saved.")
    assert contact(pg, NORA)["contact"]["frequency_per_year"] == 4
    expect(pg.locator("#cd-year .cd-big")).to_have_text("0 of 4")


def test_a_fields_hint_is_read_with_it_and_an_error_joins_the_hint(page_as, expect):
    """An Edit details field's hint is its description, so a screen reader reads it with the field,
    and an error is added beside the hint rather than in its place."""
    _, pg = page_as(contact_path(NORA), AVERY)
    cad_card(pg).locator('[data-act="cadence"]').click()
    sheet = cad_sheet(pg)
    n = sheet.locator("#cd-f-frequency_per_year")
    expect(n).to_have_attribute("aria-describedby", "cd-f-frequency_per_year-hint")
    expect(sheet.locator("#cd-f-frequency_per_year-hint")).to_have_text("Answered calls, meetings and hosted events count.")
    n.fill("0")
    save_cadence(sheet)
    expect(n).to_have_attribute("aria-describedby", "cd-f-frequency_per_year-hint cd-f-frequency_per_year-err")
    expect(n).to_have_attribute("aria-invalid", "true")


def test_the_manager_changes_only_the_follow_up_cadence(page_as, expect):
    _, pg = page_as(contact_path(MARISA), DEVON)
    assert pg.locator("button", has_text="Edit details").count() == 0
    assert pg.locator("#cd-details").get_by_role("button", name="Edit follow-up cadence").count() == 1
    expect(cad_card(pg).locator('[data-act="cadence"]')).to_have_text("Change cadence")
    for open_it in (lambda: cad_card(pg).locator('[data-act="cadence"]').click(),
                    lambda: pg.locator("#cd-details").get_by_role("button", name="Edit follow-up cadence").click()):
        open_it()
        sheet = cad_sheet(pg)
        expect(sheet).to_be_visible()
        assert pg.locator("#cd-f-name, #cd-f-city, #cd-f-owner, #cd-f-notes").count() == 0, "the full form is unreachable"
        fields = sheet.locator("input, select, textarea").evaluate_all("els => els.map(e => e.id)")
        assert fields == ["cd-f-cadence_override", "cd-f-cadence_override_until"], fields
        pg.keyboard.press("Escape")
        expect(cad_sheet(pg)).to_have_count(0)
    record_patches(pg)
    cad_card(pg).locator('[data-act="cadence"]').click()
    sheet = cad_sheet(pg)
    sheet.locator("#cd-f-cadence_override").select_option("monthly")
    sheet.locator("#cd-f-cadence_override_until").fill("2027-01-31")
    save_cadence(sheet)
    expect(toasts(pg)).to_contain_text("Saved.")
    assert patches(pg) == [["/api/bd/contacts/23", {"cadence_override": "monthly", "cadence_override_until": "2027-01-31"}]]
    expect(cad_card(pg).locator("p.cd-cad-line")).to_have_text("Follow up monthly until Jan 31, 2027, then back to quarterly.")
    c = contact(pg, MARISA)["contact"]
    assert (c["cadence_override"], c["cadence_override_until"], c["frequency_per_year"]) == ("monthly", "2027-01-31", 12)
    _, pg2 = page_as(contact_path(NORA), DEVON)
    expect(cad_card(pg2).locator('[data-act="cadence"]')).to_have_text("Change live talks a year")
    assert pg2.locator("button", has_text="Edit details").count() == 0


@pytest.mark.parametrize("email", [AVERY, CASEY, EMERY], ids=["owner", "assistant", "admin"])
def test_the_assistant_the_owner_and_an_admin_can_set_an_override(page_as, expect, email):
    _, pg = page_as(contact_path(MARISA), email)
    record_patches(pg)
    cad_card(pg).locator('[data-act="cadence"]').click()
    sheet = cad_sheet(pg)
    expect(sheet).to_be_visible()
    sheet.locator("#cd-f-cadence_override").select_option("monthly")
    sheet.locator("#cd-f-cadence_override_until").fill("2027-01-31")
    save_cadence(sheet)
    expect(toasts(pg)).to_contain_text("Saved.")
    assert patches(pg) == [["/api/bd/contacts/23", {"cadence_override": "monthly", "cadence_override_until": "2027-01-31"}]]
    c = contact(pg, MARISA)["contact"]
    assert (c["cadence"], c["cadence_source"]) == ("monthly", "override")


def test_an_archived_contact_has_no_cadence_button(page_as, expect):
    _, pg = page_as(contact_path(MARISA), AVERY)
    pg.locator('[data-act="archive"]').click()
    pg.locator('.dialog [data-act="yes"]').click()
    expect(pg.locator(".panel-info.cd-notice")).to_be_visible()
    expect(cad_card(pg).locator("p.cd-cad-line")).to_have_text("Follow up quarterly.")
    assert pg.locator('[data-act="cadence"]').count() == 0


def test_the_cadence_card_on_a_phone_fits_and_the_sheet_has_full_size_targets(page_as, expect):
    _, pg = page_as(contact_path(LENA), AVERY, PHONE)
    card = cad_card(pg)
    expect(card.locator("p.cd-cad-line")).to_have_text("Follow up monthly until Dec 31, then back to quarterly.")
    btn = card.locator('[data-act="cadence"]')
    assert btn.bounding_box()["height"] >= 43.5, btn.bounding_box()
    cb = card.bounding_box()
    assert cb["x"] >= 0 and cb["x"] + cb["width"] <= PHONE["width"] + 0.5
    assert sideways(pg) <= 1
    btn.click()
    sheet = cad_sheet(pg)
    expect(sheet).to_be_visible()
    pg.wait_for_timeout(400)                          # the slide-up
    sb = sheet.bounding_box()
    assert sb["x"] >= -0.5 and sb["x"] + sb["width"] <= PHONE["width"] + 0.5, sb
    for t in (sheet.locator("#cd-f-cadence_override"), sheet.locator("#cd-f-cadence_override_until"),
              sheet.get_by_role("button", name="Save", exact=True), sheet.get_by_role("button", name="Cancel", exact=True),
              sheet.locator('[data-act="clear-override"]')):
        expect(t).to_be_visible()
        bb = t.bounding_box()
        assert bb["height"] >= 43.5, (t, bb)
        assert bb["x"] >= 0 and bb["x"] + bb["width"] <= PHONE["width"] + 0.5, (t, bb)
    sheet.locator("#cd-f-cadence_override_until").fill("2026-11-01")
    save_cadence(sheet)
    err = sheet.locator("#cd-f-cadence_override_until-err")
    expect(err).to_have_text("Pick a day from today on.")
    eb = err.bounding_box()
    assert eb["x"] >= 0 and eb["x"] + eb["width"] <= PHONE["width"] + 0.5, "the sentence is read, not cut off"


def test_escape_closes_the_cadence_sheet_and_focus_returns_to_its_button(page_as, expect):
    _, pg = page_as(contact_path(LENA), AVERY)
    btn = cad_card(pg).locator('[data-act="cadence"]')
    btn.focus()
    pg.keyboard.press("Enter")
    sheet = cad_sheet(pg)
    expect(sheet).to_be_visible()
    inside = "() => !!document.activeElement.closest('.sheet')"
    assert pg.evaluate(inside), "focus moves into the sheet"
    for _ in range(14):
        pg.keyboard.press("Tab")
        assert pg.evaluate(inside), "Tab leaves the sheet"
    pg.keyboard.press("Escape")
    expect(cad_sheet(pg)).to_have_count(0)
    expect(btn).to_be_focused()
    assert contact(pg, LENA)["contact"]["cadence_override"] == "monthly", "Escape saves nothing"
    _, pg2 = page_as(contact_path(MARISA), DEVON)
    opener = pg2.locator("#cd-details").get_by_role("button", name="Edit follow-up cadence")
    opener.focus()
    pg2.keyboard.press("Enter")
    expect(cad_sheet(pg2)).to_be_visible()
    assert pg2.evaluate(inside)
    pg2.keyboard.press("Escape")
    expect(cad_sheet(pg2)).to_have_count(0)
    expect(opener).to_be_focused()


# ── Add a contact ────────────────────────────────────────────────────────────────────────────────
def open_add(page_as, email, path="/bd/add.html", viewport=DESKTOP):
    return page_as(path, email, viewport, wait="#add-form")


def test_the_company_type_ahead_and_the_possible_duplicate_person(page_as, expect):
    """Typing "blue" offers Bluestem Logistics (Lenexa, 3 people) and the new-company line; picking it
    says who already works there and asks whether this is someone new."""
    _, pg = open_add(page_as, AVERY)
    expect(pg.locator("#add-company")).to_be_focused()
    pg.locator("#add-company").fill("blue")
    opts = pg.locator("#add-company-list .add-option")
    expect(opts).to_have_count(2)
    expect(opts.nth(0)).to_contain_text("Bluestem Logistics")
    expect(opts.nth(0)).to_contain_text("Lenexa · 3 people")
    expect(opts.nth(1)).to_have_text("Add “blue” as a new company")
    opts.nth(0).click()
    expect(pg.locator("#add-company")).to_have_value("Bluestem Logistics")
    expect(pg.locator("#add-company-check")).to_be_visible()
    pg.locator("#add-name").fill("Rae Lindgren")
    pg.locator("#add-name").dispatch_event("input")
    dupe = pg.locator("#add-dupe")
    expect(dupe).to_contain_text("Lena Ortiz, Sam Achebe and Ines Varga already work at Bluestem Logistics. Is Rae someone new?")
    expect(dupe.locator('[data-dup="new"]')).to_have_attribute("aria-checked", "true")
    expect(dupe.locator('[data-dup="same"]')).to_have_text("Maybe one of them, check Friday")
    expect(pg.locator("#add-city")).to_have_value("Lenexa")


def test_a_screen_reader_hears_each_possible_duplicate_warning(page_as, expect):
    """Spec #802's possible-duplicate warning, for a person who cannot see it: who already works at the
    picked company is said in BD's live region (#bd-live) when it appears, and so is whose phone this
    already is. The phone box is the phone input's description, beside its hint and error, so tabbing
    back to the input reads it again; the city's "From the company" hint is the city's description."""
    _, pg = open_add(page_as, AVERY)
    pg.locator("#add-company").fill("bluestem")
    pg.locator("#add-company-list .add-option").first.click()
    expect(pg.locator("#add-dupe")).to_be_visible()
    expect(pg.locator("#bd-live")).to_have_text(
        "Lena Ortiz, Sam Achebe and Ines Varga already work at Bluestem Logistics. Is this person someone new?")
    expect(pg.locator("#add-city")).to_have_attribute("aria-describedby", "add-city-hint")
    expect(pg.locator("#add-city-hint")).to_have_text("From the company")
    phone = pg.locator("#add-phone")
    phone.fill("913-555-01")
    pg.locator("#add-email").focus()
    expect(phone).to_have_attribute("aria-describedby", "add-phone-err")
    phone.fill("913-555-0107")
    pg.locator("#add-email").focus()
    expect(pg.locator("#bd-live")).to_have_text("This phone belongs to Lena Ortiz.")
    expect(phone).to_have_attribute("aria-describedby", "add-phone-match")
    assert phone.get_attribute("aria-invalid") is None


def test_a_phone_already_on_a_contact_is_named_and_adding_still_goes_through(page_as, expect):
    """Adding is never blocked: the contact is saved under its company, and the server flags it."""
    _, pg = open_add(page_as, AVERY)
    pg.locator("#add-company").fill("Bluestem")
    pg.locator("#add-company-list .add-option").first.click()
    pg.locator("#add-name").fill("Rae Lindgren")
    pg.locator("#add-phone").fill("913-555-0107")
    pg.locator("#add-email").focus()
    match = pg.locator("#add-phone-match")
    expect(match).to_contain_text("This phone belongs to Lena Ortiz.")
    assert match.locator("a").get_attribute("href") == "/bd/contact.html?id=27"
    expect(pg.locator("#add-pills")).to_contain_text("Possible duplicate")
    pg.locator("#add-submit").click()
    expect(toasts(pg)).to_contain_text("Rae Lindgren added.")
    made = pg.evaluate("() => BDApi.get('/api/bd/companies/16')")["contacts"]
    rae = [c for c in made if c["name"] == "Rae Lindgren"]
    assert len(rae) == 1 and rae[0]["phone_e164"] == "+19135550107"
    full = contact(pg, rae[0]["id"])["contact"]
    assert full["owner"]["id"] == 1, "a salesperson's new contact is hers"
    assert full["duplicate_of"]["contact_id"] == 27
    toasts(pg).get_by_role("button", name="Open").click()
    pg.wait_for_url(re.compile(r".*/bd/contact\.html\?id=%d$" % rae[0]["id"]))
    pg.locator("#cd-title").wait_for()
    expect(pg.locator("#cd-title")).to_have_text("Rae Lindgren")


def test_a_new_company_is_made_on_save(page_as, expect):
    _, pg = open_add(page_as, AVERY)
    pg.locator("#add-company").fill("Tallgrass Dental")
    expect(pg.locator("#add-company-list .add-option.is-new")).to_have_text("Add “Tallgrass Dental” as a new company")
    pg.locator("#add-company-list .add-option.is-new").click()
    expect(pg.locator("#add-company-hint")).to_have_text("New company")
    pg.locator("#add-name").fill("Ari Mendel")
    pg.locator("#add-submit").click()
    expect(toasts(pg)).to_contain_text("Ari Mendel added.")
    found = pg.evaluate("() => BDApi.get('/api/bd/companies?q=tallgrass')")["items"]
    assert [c["name"] for c in found] == ["Tallgrass Dental"]


def test_the_form_says_what_is_missing(page_as, expect):
    _, pg = open_add(page_as, AVERY)
    pg.locator("#add-submit").click()
    expect(pg.locator("#add-company-err")).to_have_text("Pick or type a company.")
    expect(pg.locator("#add-name-err")).to_have_text("Type the person's name.")
    expect(pg.locator("#add-company")).to_be_focused()


def test_an_assistant_adds_a_contact_and_a_note_but_cannot_log_a_call(page_as, expect):
    """The ticket's case, end to end: Casey adds Rae under Bluestem from Add contact, opens her page,
    adds a note, and nowhere on the page can log a call."""
    _, pg = open_add(page_as, CASEY, "/bd/add.html?company=16")
    expect(pg.locator("#add-company")).to_have_value("Bluestem Logistics")
    expect(pg.locator("#add-name")).to_be_focused()
    pg.locator("#add-name").fill("Rae Lindgren")
    pg.locator("#add-submit").click()
    expect(toasts(pg)).to_contain_text("Rae Lindgren added.")
    toasts(pg).get_by_role("button", name="Open").click()
    pg.locator("#cd-title").wait_for(timeout=15000)
    expect(pg.locator("#cd-title")).to_have_text("Rae Lindgren")
    assert pg.locator('[data-act="call"]').count() == 0
    pg.locator('.cd-head [data-act="log-menu"]').click()
    assert menu_acts(pg) == ["log-note", "nrp"]
    pg.keyboard.press("Escape")
    pg.locator("#cd-note").click()
    pg.locator("#cd-note-text").fill("Front desk gave her name.")
    pg.locator('[data-act="note-save"]').click()
    expect(history_item(pg, "Front desk gave her name.")).to_have_count(1)
    cid = int(re.search(r"id=(\d+)", pg.url).group(1))
    assert [i["kind"] for i in interactions(pg, cid)] == ["note"]


def test_the_manager_is_told_adding_is_not_part_of_the_role(page_as, expect):
    _, pg = page_as("/bd/add.html", DEVON, wait=".add-note")
    expect(pg.locator("#add-root")).to_contain_text("Adding contacts isn't part of your BD role.")
    assert pg.locator("#add-form").count() == 0


# ── the sidebar's BD sections, and links ─────────────────────────────────────────────────────────
SECTIONS = {AVERY: ["/bd/", "/bd/contacts.html", "/bd/add.html", "/bd/review.html"],
            CASEY: ["/bd/contacts.html", "/bd/add.html", "/bd/review.html"],
            DEVON: ["/bd/", "/bd/contacts.html", "/bd/review.html", "/bd/analytics.html"],
            EMERY: ["/bd/", "/bd/contacts.html", "/bd/add.html", "/bd/review.html", "/bd/analytics.html",
                    "/bd/admin.html"]}


@pytest.mark.parametrize("email", list(SECTIONS), ids=["salesperson", "assistant", "manager", "admin"])
def test_each_section_a_role_can_use_works_and_no_other_shows(page_as, expect, email):
    _, pg = page_as(contact_path(DANA), email)
    group = pg.locator("#tw-bd-sections")
    group.locator("a").first.wait_for(timeout=15000)
    hrefs = group.locator("a").evaluate_all("els => els.map(e => e.getAttribute('href'))")
    assert hrefs == SECTIONS[email], hrefs
    for href in hrefs:
        pg.locator('#tw-bd-sections a[href="%s"]' % href).first.click()
        pg.locator(SECTION_LANDED[href]).first.wait_for(timeout=15000)
        expect(pg.locator('#tw-bd-sections a[aria-current="page"]')).to_have_attribute("href", href)
        pg.goto(pg.url.split("/bd/")[0] + contact_path(DANA))
        pg.locator("#cd-title").wait_for(timeout=15000)


@pytest.mark.parametrize("email, path", [(AVERY, contact_path(DANA, "&from=week")), (CASEY, contact_path(DUPE)),
                                         (DEVON, contact_path(LENA)), (EMERY, contact_path(WES)),
                                         (AVERY, "/bd/add.html"), (CASEY, "/bd/add.html?company=16")],
                         ids=["salesperson", "assistant", "manager", "admin", "add-salesperson", "add-assistant"])
def test_no_link_goes_to_a_bd_page_that_has_not_moved(page_as, email, path):
    """Spec #802, page links: checked against the pages that HAVE moved (MOVED_PAGES). The Log menu too."""
    wait = "#add-form" if "add.html" in path else "#cd-title"
    _, pg = page_as(path, email, wait=wait)
    pg.locator("#tw-bd-sections a").first.wait_for(timeout=15000)
    if "company=" in path:
        pg.locator("#add-dupe").wait_for()          # the company came with the address
    elif "add.html" in path:
        pg.locator("#add-company").fill("bluestem")
        pg.locator("#add-company-list .add-option").first.wait_for()
        pg.locator("#add-company-list .add-option").first.click()
        pg.locator("#add-dupe").wait_for()
    else:
        pg.locator("#cd-others .who-name, #cd-others .cd-empty-line").first.wait_for()
    seen = set(bd_links(pg))
    for log in pg.locator('[data-act="log-menu"]:visible').all():
        log.click()
        pg.locator(".menu").wait_for()
        seen |= set(bd_links(pg))
        pg.keyboard.press("Escape")
        pg.locator(".menu").wait_for(state="detached")
    assert seen and seen <= MOVED_PAGES, sorted(seen - MOVED_PAGES)


# ── widths ───────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["1280", "390"])
def test_nothing_scrolls_sideways(page_as, viewport):
    for path, wait in ((contact_path(DANA), "#cd-title"), ("/bd/add.html", "#add-form")):
        _, pg = page_as(path, AVERY, viewport, wait=wait)
        pg.evaluate("() => document.fonts.ready.then(() => true)")
        assert sideways(pg) <= 1, (path, viewport)
