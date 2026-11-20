"""BD's Admin (/bd/admin.html), Potential BD Contacts (/bd/review.html) and Analytics (/bd/analytics.html)
in a real Chromium, against the live app (#809).

BD's test_e2e_mgmt, moved with the pages and rewritten for the live app: BD's mock data is gone, so
every test starts from the FIXTURE SEED (backend/bd/ops/fixture_seed.py), put back before each test,
on a server whose business day is pinned to the seed's Wednesday, 2026-11-04. The expected values are
worked by hand from the seed, never read back from the page's own rules:

  People   1 Avery Quill and 2 Blair Fenn (salespeople), 3 Casey Moret (assistant), 4 Devon Hale
           (manager), 5 Emery Stoll (admin), 6 Frankie Oduya (super admin), 7 Gale Ward (salesperson,
           sign-in off). No settings rows: every setting is its default (Friday 4 PM, quarterly).
  Calls    801, an unmatched call from 913-555-0199, in, 95 s ("2 min"), Tue, Nov 3, 4:42 PM CST,
           "Caller asked about a quote for a shop floor."
  Imports  701, bd-fixture-import.csv, a practice run by Emery on Oct 1, 10:00 AM CDT: 3 rows read,
           2 created, 0 updated, 1 skipped, 1 possible duplicate, one problem "CSV, row 4: No company name."
  Owners   of contacts: Avery Quill, Blair Fenn, Devon Hale (Ines Varga's).
  Weeks    Avery has a Friday batch for the week of Mon, Nov 2.

What it proves, for the ticket:
  * Admin: each section is shown only to the BD roles allowed it (can, never a role name), and a role
    with no part of Admin is told so and asks for nothing; the People table sets a person's BD role and
    sign-in, shows the super-admin-only rule to a plain admin (Q29) and lets the super admin change an
    admin; BD settings (the Friday run day and hour, the goals and cadence, the pick lists) save; the
    phone status; unmatched calls are attached to a contact through the contacts search, or dismissed;
    the workbook import (a practice run, then Import now) and past imports, for the salesperson too;
  * Potential BD Contacts and Analytics open restyled and say the server's "not built yet";
  * each BD section a role can use works and the others are not shown, and no role's view of these
    pages links to a BD page that has not moved; desktop and phone width.

BD's own management-page tests are carried over below where their page is; the ones that are not
(Potential BD Contacts' Add / Undo and Analytics' numbers: their routes are not built) are listed,
one reason each, in the #809 PR.

Runs in the browser job of ci.yml (tests/_bd_browser.py: the live app on a seeded BD test database,
sign-in faked only inside the test process).
"""
import pytest

from _bd_browser import (DESKTOP, MOVED_PAGES, PHONE, SECTION_LANDED, Page, api, bd_links, browser,
                         live_app_db, require_playwright, reseed, sideways, toasts)

AVERY = "avery.quill@example.com"         # salesperson
CASEY = "casey.moret@example.com"         # assistant
DEVON = "devon.hale@example.com"          # manager
EMERY = "emery.stoll@example.com"         # admin
FRANKIE = "frankie.oduya@example.com"     # super admin

REVIEW_NOT_BUILT = "This part is not built yet (Phase 6)."
ANALYTICS_NOT_BUILT = "This part is not built yet (Phase 7)."
ADMIN_ONLY_ROUTES = ("/api/bd/admin/users", "/api/bd/admin/telephony", "/api/bd/settings")

CAD_HINT = "Every BD contact follows this unless you give one an override."
MAINT_HINT = ("A maintenance follow-up comes due 120 days after the last call, meeting, email or text, "
              "and stays on the list until one is logged.")
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

    def _open(path, email, viewport=DESKTOP, wait="#main"):
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


def admin(page_as, email, viewport=DESKTOP, wait=None):
    """Open Admin signed in as `email`, waiting for the first section the role is shown."""
    return page_as("/bd/admin.html", email, viewport,
                   wait=wait or "#ad-s-users tr.ad-user, #ad-s-phone .ad-call, #ad-s-imports tbody tr, #ad-note .ad-note")


def nav_names(pg):
    return [t.strip() for t in pg.locator("#ad-nav a").all_inner_texts()]


def settings(pg):
    return api(pg, "/api/bd/settings")["settings"]


def user(pg, uid):
    return [u for u in api(pg, "/api/bd/admin/users")["items"] if u["id"] == uid][0]


def role_options(pg, uid):
    return pg.locator("#ad-role-%d option" % uid).evaluate_all("els => els.map(e => e.value)")


# ── Admin: who sees what ──────────────────────────────────────────────────────────────────────────
def test_admin_nav_lists_every_section_for_an_admin(page_as, expect):
    _, pg = admin(page_as, EMERY)
    expect(pg.locator("#ad-nav a")).to_have_count(6)
    assert nav_names(pg) == ["People", "Friday list", "Goals", "Pick lists", "Phone", "Imports"]
    expect(pg.locator("#ad-nav a[aria-current]")).to_have_count(1)
    expect(pg.locator("#ad-s-users tr.ad-user")).to_have_count(7)
    pg.click('#ad-nav a[data-sec="ad-s-imports"]')
    expect(pg.locator('#ad-nav a[data-sec="ad-s-imports"]')).to_have_attribute("aria-current", "true")
    expect(pg.locator("main h1")).to_have_text("Admin")
    expect(pg.locator("main")).to_contain_text("The proposal tool's own Admin page is unchanged.")


def test_admin_nav_on_a_phone_shows_every_section(page_as, expect):
    _, pg = admin(page_as, EMERY, PHONE)
    links = pg.locator("#ad-nav a")
    expect(links).to_have_count(6)
    for i in range(6):
        bb = links.nth(i).bounding_box()
        assert bb["x"] >= 0 and bb["x"] + bb["width"] <= PHONE["width"] + 0.5, "a section is off screen"


def test_the_assistant_keeps_admin_with_her_two_sections(page_as, expect):
    p, pg = admin(page_as, CASEY)
    expect(pg.locator("#ad-s-imports tbody tr")).to_have_count(1)
    assert nav_names(pg) == ["Phone", "Imports"]
    for sec in ("#ad-s-users", "#ad-s-friday", "#ad-s-rules", "#ad-s-lists"):
        expect(pg.locator(sec)).to_be_hidden()
    expect(pg.locator("#ad-h-phone")).to_have_text("Unknown calls")
    expect(pg.locator("#ad-phone-line")).to_have_count(0)      # the phone status is the admins'
    asked = [r for r in p.requests if any(r.split("?")[0].endswith(x) for x in ADMIN_ONLY_ROUTES)]
    assert asked == [], "nothing admin-only is even asked for her: %r" % asked


def test_a_salesperson_sees_only_imports(page_as, expect):
    p, pg = admin(page_as, AVERY)
    expect(pg.locator("#ad-s-imports")).to_be_visible()
    for sec in ("#ad-s-users", "#ad-s-friday", "#ad-s-rules", "#ad-s-lists", "#ad-s-phone"):
        expect(pg.locator(sec)).to_be_hidden()
    expect(pg.locator("#ad-navbar")).to_be_hidden()       # one section needs no nav
    expect(pg.get_by_role("button", name="Import a workbook")).to_be_visible()
    asked = [r for r in p.requests if "/api/bd/admin/" in r and "/api/bd/admin/imports" not in r]
    assert asked == [], asked


def test_a_manager_is_told_admin_is_not_part_of_the_role(page_as, expect):
    p, pg = admin(page_as, DEVON)
    expect(pg.locator("#ad-note")).to_contain_text("Admin isn't part of your BD role.")
    assert pg.locator(".ad-sec:visible").count() == 0
    assert [r for r in p.requests if "/api/bd/admin/" in r] == []


# ── Admin: People ─────────────────────────────────────────────────────────────────────────────────
def test_a_plain_admin_is_shown_the_super_admin_rule(page_as, expect):
    """Q29, shown and not only enforced: the super admin's row is locked and says why, her own row
    says why, and no admin role is offered to her, in the table or the add form."""
    _, pg = admin(page_as, EMERY)
    expect(pg.locator("#ad-role-6")).to_be_disabled()
    expect(pg.locator("#ad-why-6")).to_have_text("Only a super admin can change an admin.")
    expect(pg.locator("#ad-active-6")).to_be_disabled()
    expect(pg.locator("#ad-role-5")).to_be_disabled()
    expect(pg.locator("#ad-why-5")).to_have_text("You can't change your own role or sign-in.")
    assert role_options(pg, 1) == ["salesperson", "assistant", "manager"]
    assert pg.locator("#ad-new-role option").evaluate_all("els => els.map(e => e.value)") == \
        ["salesperson", "assistant", "manager"]
    expect(pg.locator("#ad-new-role-hint")).to_have_text("Only a super admin can add an admin.")
    expect(pg.locator("#ad-s-users")).to_contain_text("Who can open the BD CRM is set on the proposal tool's Admin page.")


def test_the_super_admin_changes_an_admin(page_as, expect):
    _, pg = admin(page_as, FRANKIE)
    expect(pg.locator("#ad-role-5")).to_be_enabled()
    assert role_options(pg, 5) == ["salesperson", "assistant", "manager", "admin", "super_admin"]
    expect(pg.locator("#ad-new-role-hint")).to_have_count(0)
    pg.select_option("#ad-role-5", "manager")
    expect(toasts(pg)).to_contain_text("Emery Stoll is now manager.")
    assert user(pg, 5)["role"] == "manager"
    expect(pg.locator("#ad-role-5")).to_be_focused()


def test_moving_someone_off_salesperson_asks_first(page_as, expect):
    _, pg = admin(page_as, EMERY)
    pg.select_option("#ad-role-2", "assistant")
    dlg = pg.locator(".dialog.is-open")
    expect(dlg).to_contain_text("Make Blair Fenn assistant?")
    expect(dlg).to_contain_text("Blair Fenn stops getting a weekly list of 10.")
    dlg.get_by_role("button", name="Cancel").click()
    expect(pg.locator("#ad-role-2")).to_have_value("salesperson")
    assert user(pg, 2)["role"] == "salesperson"
    pg.select_option("#ad-role-2", "assistant")
    pg.locator(".dialog.is-open").get_by_role("button", name="Yes, make assistant").click()
    expect(toasts(pg)).to_contain_text("Blair Fenn is now assistant.")
    assert user(pg, 2)["role"] == "assistant"


def test_turning_off_sign_in_asks_and_saves(page_as, expect):
    _, pg = admin(page_as, EMERY)
    # The switch's name starts with the word it shows, so "click Active" finds it (WCAG 2.5.3).
    expect(pg.get_by_role("switch", name="Active, sign-in for Blair Fenn", exact=True)).to_have_attribute("id", "ad-active-2")
    pg.click("#ad-active-2")
    dlg = pg.locator(".dialog.is-open")
    expect(dlg).to_contain_text("Turn off sign-in for Blair Fenn?")
    dlg.get_by_role("button", name="Turn off sign-in").click()
    expect(toasts(pg)).to_contain_text("Blair Fenn can no longer sign in.")
    assert user(pg, 2)["active"] is False
    expect(pg.locator('tr.ad-user[data-id="2"]')).to_contain_text("Cannot sign in")
    expect(pg.get_by_role("switch", name="Off, sign-in for Blair Fenn", exact=True)).to_have_attribute("id", "ad-active-2")
    pg.click("#ad-active-2")                          # back on: no question
    expect(toasts(pg)).to_contain_text("Blair Fenn can sign in again.")
    assert user(pg, 2)["active"] is True


def test_adding_a_person(page_as, expect):
    _, pg = admin(page_as, EMERY)
    pg.fill("#ad-new-email", "nell.ash@other.example.org")
    pg.fill("#ad-new-name", "Nell")
    pg.click('#ad-add-user button[type="submit"]')
    expect(pg.locator("#ad-add-user .field-error")).to_have_text("Use a @example.com address.")
    assert len(api(pg, "/api/bd/admin/users")["items"]) == 7
    pg.fill("#ad-new-email", "nell.ash@example.com")
    pg.select_option("#ad-new-role", "assistant")
    pg.click('#ad-add-user button[type="submit"]')
    expect(toasts(pg)).to_contain_text("Nell was added as assistant.")
    expect(pg.locator("#ad-s-users tr.ad-user")).to_have_count(8)
    new = api(pg, "/api/bd/admin/users")["items"][-1]
    assert (new["email"], new["name"], new["role"], new["active"]) == ("nell.ash@example.com", "Nell", "assistant", True)


# ── Admin: the Friday list, goals and pick lists ──────────────────────────────────────────────────
def test_the_friday_list_saves_its_day_and_hour(page_as, expect):
    _, pg = admin(page_as, EMERY, wait="#ad-weekly-form")
    # BD_WEEKLY_ENABLED is off on this server, as on staging: the list is not made on its own.
    expect(pg.locator("#ad-weekly-hint")).to_have_text("Off. Nothing is made on its own.")
    expect(pg.locator("#ad-fu-count")).to_have_text("5 (always 10 in all)")
    pg.click("#ad-weekly-on")
    expect(pg.locator("#ad-weekly-on")).to_have_attribute("aria-checked", "true")
    expect(pg.locator("#ad-weekly-hint")).to_have_text("Runs Fri 4:00 PM Central, for the next week.")
    pg.select_option("#ad-run-day", "saturday")
    pg.select_option("#ad-run-hour", "9")
    expect(pg.locator("#ad-weekly-hint")).to_have_text("Runs Sat 9:00 AM Central, for the next week.")
    pg.fill("#ad-new-count", "7")
    expect(pg.locator("#ad-fu-count")).to_have_text("3 (always 10 in all)")
    pg.get_by_role("button", name="Save", exact=True).click()
    expect(toasts(pg)).to_contain_text("Friday list settings saved.")
    w = settings(pg)["weekly"]
    assert (w["run_day"], w["run_hour"], w["new_count"], w["followup_count"], w["enabled"]) == ("saturday", 9, 7, 3, True)


def test_making_a_list_again_asks_first(page_as, expect):
    """Avery already has this week's batch (Mon, Nov 2): the server's 409 becomes a question."""
    _, pg = admin(page_as, EMERY, wait="#ad-run-btn")
    expect(pg.locator("#ad-run-owner")).to_have_value("1")
    expect(pg.locator("#ad-run-text")).to_have_text("Avery Quill, week of Mon, Nov 2.")
    assert pg.locator("#ad-run-owner option").all_inner_texts() == ["Avery Quill", "Blair Fenn"]
    pg.click("#ad-run-btn")
    dlg = pg.locator(".dialog.is-open")
    expect(dlg).to_contain_text("Make the list again?")
    expect(dlg).to_contain_text("Avery Quill already has a list for the week of Mon, Nov 2.")
    dlg.get_by_role("button", name="Cancel").click()
    expect(dlg).to_have_count(0)


def cad_radio(pg, word):
    return pg.locator('#ad-freq-bd input[type="radio"][name="bd_cadence"][value="%s"]' % word)


def checked_cadence(pg):
    return pg.evaluate("() => { const r = document.querySelector('#ad-freq-bd input[name=\"bd_cadence\"]:checked');"
                       " return r ? r.value : null; }")


def test_goals_has_the_bd_cadence_as_a_segmented_radio_group(page_as, expect):
    _, pg = admin(page_as, EMERY, wait="#ad-freq-bd")
    group = pg.locator("#ad-freq-bd")
    assert group.get_attribute("role") == "radiogroup"
    assert group.get_attribute("aria-label") == "BD follow-up cadence"
    assert group.get_attribute("aria-describedby") == "ad-freq-bd-hint"
    expect(pg.locator("#ad-freq-bd-hint")).to_have_text(CAD_HINT)
    assert group.locator('input[type="radio"]').evaluate_all("els => els.map(e => [e.name, e.value])") == \
        [["bd_cadence", "weekly"], ["bd_cadence", "monthly"], ["bd_cadence", "quarterly"]]
    assert [t.strip() for t in group.locator("label").all_inner_texts()] == ["Weekly", "Monthly", "Quarterly"]
    assert checked_cadence(pg) == "quarterly" == settings(pg)["bd_cadence"]
    expect(pg.locator("#ad-s-rules")).to_contain_text(MAINT_HINT)
    expect(pg.get_by_label("Live talks a year, maintenance")).to_have_value("3")
    card = pg.locator("#ad-s-rules .ad-kv")
    expect(card.locator("dt", has_text="Counts as a live talk")).to_have_count(1)
    expect(card.locator("dt", has_text="Does not count as a live talk")).to_have_count(1)
    maint = card.locator("div", has=pg.locator("dt", has_text="Maintenance follow-ups")).locator("dd")
    for word in ("call", "voicemail", "meeting", "event", "email", "text"):
        expect(maint).to_contain_text(word)
    expect(maint).to_contain_text("A note does not count.")


def test_goals_save_the_bd_cadence_as_a_word_and_the_numbers(page_as, expect):
    _, pg = admin(page_as, EMERY, wait="#ad-freq-bd")
    pg.locator("#ad-freq-bd label", has_text="Monthly").click()
    pg.fill("#ad-meet-goal", "4")
    pg.fill("#ad-meet-min", "5")
    pg.get_by_role("button", name="Save goals").click()
    expect(pg.locator("#ad-goals-form .field-error")).to_have_text("Use a whole number from 0 up to the meeting goal.")
    pg.fill("#ad-meet-min", "2")
    pg.get_by_role("button", name="Save goals").click()
    expect(toasts(pg)).to_contain_text("Goals saved.")
    s = settings(pg)
    assert (s["bd_cadence"], s["weekly_meeting_goal"], s["non_dsbc_website_min"]) == ("monthly", 4, 2)
    pg.reload()
    pg.locator("#ad-freq-bd").wait_for(timeout=15000)
    expect(cad_radio(pg, "monthly")).to_be_checked()


def test_the_arrow_keys_move_the_cadence_selection(page_as, expect):
    _, pg = admin(page_as, EMERY, wait="#ad-freq-bd")
    cad_radio(pg, "quarterly").focus()
    pg.keyboard.press("ArrowLeft")
    expect(cad_radio(pg, "monthly")).to_be_checked()
    expect(cad_radio(pg, "monthly")).to_be_focused()
    pg.keyboard.press("ArrowRight")
    pg.keyboard.press("ArrowRight")
    expect(cad_radio(pg, "weekly")).to_be_checked()      # wrapped round
    pg.get_by_role("button", name="Save goals").click()
    expect(toasts(pg)).to_contain_text("Goals saved.")
    assert settings(pg)["bd_cadence"] == "weekly"


def test_the_segmented_cadence_fits_a_phone_with_full_size_targets(page_as, expect):
    _, pg = admin(page_as, EMERY, PHONE, wait="#ad-freq-bd")
    group = pg.locator("#ad-freq-bd")
    group.scroll_into_view_if_needed()
    labels = group.locator("label")
    assert labels.count() == 3
    for i in range(3):
        bb = labels.nth(i).bounding_box()
        assert bb["height"] >= 47.5, bb
        assert bb["x"] >= 0 and bb["x"] + bb["width"] <= PHONE["width"] + 0.5, bb
    assert sideways(pg) <= 1


def test_a_pick_list_adds_and_saves_and_a_used_value_asks_before_it_goes(page_as, expect):
    """Dana Whitlow's industry is "General contractor", so taking it out of the list asks first."""
    _, pg = admin(page_as, EMERY, wait="#ad-add-industries")
    expect(pg.locator('.ad-list[data-key="lead_sources"] .ad-chip.is-locked')).to_have_count(2)   # DSBC Sales, Website Lead
    pg.fill("#ad-add-industries", "General contractor")
    pg.locator('.ad-list[data-key="industries"] [data-add]').click()
    expect(pg.locator('.ad-list[data-key="industries"] [data-save]')).to_be_enabled()
    pg.locator('.ad-list[data-key="industries"] [data-save]').click()
    expect(toasts(pg)).to_contain_text("Industries saved.")
    assert settings(pg)["industries"][-1] == "General contractor"
    pg.get_by_role("button", name="Remove General contractor").click()
    dlg = pg.locator(".dialog.is-open")
    expect(dlg).to_contain_text("1 contact uses General contractor.")
    dlg.get_by_role("button", name="Cancel").click()
    expect(pg.get_by_role("button", name="Remove General contractor")).to_be_visible()
    pg.fill("#ad-add-industries", "manufacturing")
    pg.locator('.ad-list[data-key="industries"] [data-add]').click()
    expect(pg.locator('.ad-list[data-key="industries"] .field-error')).to_have_text("That one is already in the list.")


def test_admin_chip_remove_buttons_have_a_full_tap_area(page_as, expect):
    for vp, reach in ((DESKTOP, 20), (PHONE, 22)):
        _, pg = admin(page_as, EMERY, vp, wait=".ad-chip-x")
        x = pg.locator(".ad-chip-x").first
        x.scroll_into_view_if_needed()
        bb = x.bounding_box()
        cx, cy = bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2
        hit = pg.evaluate("([x, y, id]) => { const e = document.elementFromPoint(x, y); return !!e && !!e.closest('#' + id); }",
                          [cx + reach, cy, x.get_attribute("id")])
        assert hit, "the tap area reaches %dpx from the centre" % reach


# ── Admin: the phone system and unmatched calls ───────────────────────────────────────────────────
def test_the_phone_status_says_nothing_is_connected(page_as, expect):
    _, pg = admin(page_as, EMERY, wait="#ad-phone-line")
    expect(pg.locator("#ad-phone-status")).to_have_text("Not connected")
    expect(pg.locator("#ad-phone-line")).to_have_text("No phone system connected yet.")
    expect(pg.locator(".ad-call")).to_have_count(1)
    expect(pg.locator(".ad-call")).to_contain_text("913-555-0199")
    expect(pg.locator(".ad-call")).to_contain_text("Called us · 2 min · Tue, Nov 3, 4:42 PM")
    expect(pg.locator(".ad-call")).to_contain_text("Caller asked about a quote for a shop floor.")


def test_attach_a_call_opens_a_dialog_and_escape_closes_it(page_as, expect):
    _, pg = admin(page_as, EMERY, wait=".ad-call")
    btn = pg.locator("[data-attach]").first
    btn.click()
    dlg = pg.locator("#ad-attach")
    expect(dlg).to_be_visible()
    expect(pg.locator("#ad-attach-q")).to_be_focused()
    expect(pg.locator("#ad-attach-call")).to_contain_text("913-555-0199 · Called us on Tue, Nov 3, 4:42 PM · 2 min")
    expect(pg.locator("#ad-attach-outcome")).to_have_value("answered")      # 95 s: a talk
    pg.keyboard.press("Escape")
    expect(dlg).to_be_hidden()
    expect(btn).to_be_focused()


def test_the_assistant_attaches_a_call_to_a_contact(page_as, expect):
    _, pg = admin(page_as, CASEY, wait=".ad-call")
    pg.locator("[data-attach]").first.click()
    pg.get_by_role("button", name="Attach call").click()
    expect(pg.locator("#ad-attach .field-error")).to_have_text("Pick the contact this call was with.")
    pg.fill("#ad-attach-q", "wes")
    pick = pg.locator('#ad-attach-results input[name="contact_id"][value="32"]')
    pick.wait_for(timeout=10000)
    pick.check()
    expect(pg.locator("#ad-attach-save")).not_to_be_checked()      # Wes has a number: replacing it is a tick
    expect(pg.locator("#ad-attach-save-hint")).to_have_text("Wes Calder already has 913-555-0112. Tick this to replace it.")
    pg.get_by_role("button", name="Attach call").click()
    expect(toasts(pg)).to_contain_text("Call attached to Wes Calder. It counts as a live talk.")
    expect(pg.locator(".ad-call")).to_have_count(0)
    expect(pg.locator("#ad-phone")).to_contain_text("No unknown calls.")
    calls = [i["interaction"] for i in api(pg, "/api/bd/contacts/32/interactions")["items"] if i.get("type") == "interaction"]
    assert [(c["kind"], c["outcome"], c["duration_s"]) for c in calls] == [("call", "answered", 95)]
    assert api(pg, "/api/bd/contacts/32")["contact"]["phone"] == "913-555-0112"
    assert toasts(pg).get_by_role("button", name="Open contact").count() == 1


def test_an_admin_dismisses_a_call(page_as, expect):
    _, pg = admin(page_as, EMERY, wait=".ad-call")
    pg.get_by_role("button", name="Dismiss the call from 913-555-0199").click()
    dlg = pg.locator(".dialog.is-open")
    expect(dlg).to_contain_text("The call from 913-555-0199 on Tue, Nov 3, 4:42 PM leaves this list for good.")
    dlg.get_by_role("button", name="Dismiss call").click()
    expect(toasts(pg)).to_contain_text("Call dismissed.")
    expect(pg.locator("#ad-phone")).to_contain_text("No unknown calls.")
    items = api(pg, "/api/bd/admin/unmatched-calls?status=all")["items"]
    assert [(c["id"], c["status"]) for c in items] == [(801, "dismissed")]


# ── Admin: the workbook import and past imports ───────────────────────────────────────────────────
def test_past_imports_show_the_seeds_practice_run(page_as, expect):
    _, pg = admin(page_as, CASEY, wait="#ad-s-imports tbody tr")
    row = pg.locator("#ad-s-imports tbody tr")
    expect(row).to_have_count(1)
    expect(row).to_contain_text("bd-fixture-import.csv")
    expect(row).to_contain_text("Practice run")
    expect(row).to_contain_text("Oct 1, 2026, 10:00 AM CDT · Emery Stoll")
    assert [t.strip() for t in row.locator("td.num").all_inner_texts()] == ["3", "2", "0", "1", "1"]
    row.locator("summary").click()
    expect(row.locator(".ad-errors li")).to_have_text("CSV, row 4: No company name.")


@pytest.mark.parametrize("email", [AVERY, EMERY], ids=["salesperson", "admin"])
def test_a_workbook_is_imported_after_a_practice_run(page_as, expect, email, tmp_path):
    csv = tmp_path / "made up contacts.csv"
    csv.write_text(CSV, encoding="utf-8")
    _, pg = admin(page_as, email, wait="#ad-s-imports tbody tr")
    pg.set_input_files("#ad-import-file", str(csv))
    dlg = pg.locator(".dialog.is-open")
    expect(dlg).to_contain_text("1 contact read, 0 possible duplicates.")
    expect(dlg).to_contain_text("This was a practice run. Nothing has been imported yet.")
    # The redraw keeps focus in the dialog (on Close, where it opened) and says what came back.
    expect(pg.locator("#ad-import-body")).to_have_attribute("aria-busy", "false")
    expect(pg.locator("#bd-live")).to_have_text(
        "1 contact read, 1 would be added, 0 would be updated. This was a practice run.")
    focus = pg.evaluate("() => { var a = document.activeElement;"
                        " return a && a.closest('.dialog.is-open') ? a.textContent.trim() : null; }")
    assert focus == "Close", "focus left the import dialog: %r" % focus
    assert api(pg, "/api/bd/contacts?q=Rae%20Lindgren")["total"] == 0, "a practice run adds no one"
    dlg.get_by_role("button", name="Import now").click()
    expect(toasts(pg)).to_contain_text("Imported: 1 added, 0 updated.")
    expect(pg.locator(".dialog.is-open")).to_have_count(0)
    expect(pg.locator("#ad-s-imports tbody tr")).to_have_count(3)
    names = pg.locator("#ad-s-imports tbody tr .who-name").all_inner_texts()
    assert [n.strip() for n in names] == ["made up contacts.csv", "made up contacts.csv Practice run",
                                          "bd-fixture-import.csv Practice run"]
    assert api(pg, "/api/bd/contacts?q=Rae%20Lindgren")["total"] == 1


def test_past_imports_on_a_phone_are_one_card_per_run(page_as, expect):
    _, pg = admin(page_as, CASEY, PHONE, wait="#ad-s-imports .ad-imports-cards > li")
    expect(pg.locator("#ad-s-imports table")).to_be_hidden()
    card = pg.locator("#ad-s-imports .ad-imports-cards > li")
    expect(card).to_contain_text("3 rows read · 2 added · 0 updated · 1 skipped · 1 maybe duplicate")
    assert sideways(pg) <= 1


# ── Potential BD Contacts ─────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("email", [AVERY, CASEY, DEVON, EMERY], ids=["salesperson", "assistant", "manager", "admin"])
def test_potential_bd_contacts_opens_and_says_not_built_yet(page_as, expect, email):
    p, pg = page_as("/bd/review.html", email, wait="#rv-body .error-box")
    expect(pg.locator("main h1")).to_have_text("Potential BD Contacts")
    expect(pg.locator("#rv-body .error-box")).to_contain_text(REVIEW_NOT_BUILT)
    assert [" ".join(t.split()) for t in pg.locator("#rv-views button").all_inner_texts()] == \
        ["To review 0", "Added 0", "Not added 0"]
    assert p.bd_errors() == [(503, "/api/bd/review/candidates?status=all")]
    pg.get_by_role("button", name="Try again").click()
    expect(pg.locator("#rv-body .error-box")).to_contain_text(REVIEW_NOT_BUILT)
    assert len(p.bd_errors()) == 2, "Try again asked again"
    pg.click('#rv-views [data-view="added"]')
    expect(pg.locator('#rv-views [data-view="added"]')).to_have_attribute("aria-pressed", "true")
    expect(pg.locator("#rv-body .error-box")).to_contain_text(REVIEW_NOT_BUILT)


def test_potential_bd_contacts_on_a_phone_fits(page_as, expect):
    _, pg = page_as("/bd/review.html", AVERY, PHONE, wait="#rv-body .error-box")
    assert sideways(pg) <= 1
    for i in range(3):
        bb = pg.locator("#rv-views button").nth(i).bounding_box()
        assert bb["x"] >= 0 and bb["x"] + bb["width"] <= PHONE["width"] + 0.5


# ── Analytics ─────────────────────────────────────────────────────────────────────────────────────
def test_analytics_opens_for_the_manager_and_says_not_built_yet(page_as, expect):
    p, pg = page_as("/bd/analytics.html", DEVON, wait="#an-body .error-box")
    expect(pg.locator("#an-body .error-box")).to_contain_text(ANALYTICS_NOT_BUILT)
    expect(pg.locator("#an-sub")).to_have_text("Jan 1 - Wed, Nov 4, 2026")
    assert pg.locator('label[for="an-owner"]').inner_text().strip() == "Owner"
    assert pg.locator("#an-owner option").all_inner_texts() == ["Everyone", "Avery Quill", "Blair Fenn", "Devon Hale"]
    assert pg.locator("main .btn-primary").count() == 0, "Analytics is read-only: no red button"
    with pg.expect_response(lambda r: "/api/bd/analytics?" in r.url) as answer:
        pg.select_option("#an-owner", "1")
    assert answer.value.url.endswith("/api/bd/analytics?from=2026-01-01&to=2026-11-04&owner=1")
    assert answer.value.status == 503
    expect(pg.locator("#an-body .error-box")).to_contain_text(ANALYTICS_NOT_BUILT)
    pg.get_by_role("button", name="Download CSV").click()
    expect(toasts(pg)).to_contain_text(ANALYTICS_NOT_BUILT)


def test_the_quarter_tab_and_the_dates_change_the_range(page_as, expect):
    p, pg = page_as("/bd/analytics.html", EMERY, wait="#an-body .error-box")
    pg.click('#an-period [data-period="quarter"]')
    expect(pg.locator('#an-period [data-period="quarter"]')).to_have_attribute("aria-pressed", "true")
    expect(pg.locator("#an-sub")).to_have_text("Oct 1 - Wed, Nov 4, 2026")
    pg.click('#an-period [data-period="custom"]')
    expect(pg.locator("#an-custom")).to_be_visible()
    expect(pg.locator("#an-from")).to_have_value("2026-01-01")
    pg.fill("#an-from", "2026-11-01")
    pg.fill("#an-to", "2026-10-01")
    expect(pg.locator("#an-range-error")).to_have_text("The first date is after the last date.")
    expect(pg.locator("#an-export")).to_be_disabled()
    expect(pg.locator("#an-sub")).to_have_text("Pick the dates")
    pg.fill("#an-to", "2026-11-03")
    expect(pg.locator("#an-sub")).to_have_text("Nov 1 - Tue, Nov 3, 2026")
    expect(pg.locator("#an-body .error-box")).to_contain_text(ANALYTICS_NOT_BUILT)


@pytest.mark.parametrize("email", [AVERY, CASEY], ids=["salesperson", "assistant"])
def test_analytics_is_not_part_of_the_other_roles(page_as, expect, email):
    p, pg = page_as("/bd/analytics.html", email, wait="#an-body .an-note")
    expect(pg.locator("#an-body")).to_contain_text("Analytics isn't part of your BD role.")
    expect(pg.locator("#an-tools")).to_be_hidden()
    assert [r for r in p.requests if "/api/bd/analytics" in r] == []


def test_analytics_on_a_phone_keeps_all_five_periods_on_screen(page_as, expect):
    _, pg = page_as("/bd/analytics.html", DEVON, PHONE, wait="#an-body .error-box")
    per = pg.locator("#an-period")
    assert per.evaluate("e => e.scrollWidth - e.clientWidth") <= 1
    for i in range(per.locator("[data-period]").count()):
        bb = per.locator("[data-period]").nth(i).bounding_box()
        assert bb["x"] >= 0 and bb["x"] + bb["width"] <= PHONE["width"] + 0.5
    assert sideways(pg) <= 1


# ── the sidebar's BD sections, and links ─────────────────────────────────────────────────────────
SECTIONS = {
    AVERY: ["/bd/", "/bd/add.html", "/bd/review.html", "/bd/admin.html"],
    CASEY: ["/bd/add.html", "/bd/review.html", "/bd/admin.html"],
    DEVON: ["/bd/", "/bd/review.html", "/bd/analytics.html"],
    EMERY: ["/bd/", "/bd/add.html", "/bd/review.html", "/bd/analytics.html", "/bd/admin.html"],
    FRANKIE: ["/bd/", "/bd/add.html", "/bd/review.html", "/bd/analytics.html", "/bd/admin.html"],
}


@pytest.mark.parametrize("email", list(SECTIONS), ids=["salesperson", "assistant", "manager", "admin", "super_admin"])
def test_each_section_a_role_can_use_works_and_no_other_shows(page_as, expect, email):
    _, pg = page_as("/bd/review.html", email, wait="#rv-body .error-box")
    group = pg.locator("#tw-bd-sections")
    group.locator("a").first.wait_for(timeout=15000)
    hrefs = group.locator("a").evaluate_all("els => els.map(e => e.getAttribute('href'))")
    assert hrefs == SECTIONS[email], hrefs
    for href in hrefs:
        pg.locator('#tw-bd-sections a[href="%s"]' % href).first.click()
        pg.locator(SECTION_LANDED[href]).first.wait_for(timeout=15000)
        expect(pg.locator('#tw-bd-sections a[aria-current="page"]')).to_have_attribute("href", href)
        # only the BD CRM row is lit: never the tool's own Admin or Analytics row (spec #802)
        lit = pg.locator("#tw-sidebar .tw-nav-item.active").evaluate_all("els => els.map(e => e.getAttribute('href'))")
        assert lit == ["/bd/"], (href, lit)
        pg.goto(pg.url.split("/bd/")[0] + "/bd/review.html")
        pg.locator("#rv-body .error-box").wait_for(timeout=15000)


@pytest.mark.parametrize("email, path, wait", [
    (EMERY, "/bd/admin.html", "#ad-s-users tr.ad-user"), (CASEY, "/bd/admin.html", ".ad-call"),
    (AVERY, "/bd/admin.html", "#ad-s-imports tbody tr"), (DEVON, "/bd/admin.html", "#ad-note .ad-note"),
    (AVERY, "/bd/review.html", "#rv-body .error-box"), (DEVON, "/bd/analytics.html", "#an-body .error-box"),
], ids=["admin-admin", "admin-assistant", "admin-salesperson", "admin-manager", "review", "analytics"])
def test_no_link_goes_to_a_bd_page_that_has_not_moved(page_as, email, path, wait):
    """Spec #802, page links: checked against the pages that HAVE moved (MOVED_PAGES). Contacts has not."""
    _, pg = page_as(path, email, wait=wait)
    pg.locator("#tw-bd-sections a").first.wait_for(timeout=15000)
    seen = set(bd_links(pg))
    assert seen and seen <= MOVED_PAGES, sorted(seen - MOVED_PAGES)
    assert "/bd/contacts.html" not in seen


# ── widths ───────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["1280", "390"])
def test_nothing_scrolls_sideways(page_as, viewport):
    for path, email, wait in (("/bd/admin.html", EMERY, "#ad-s-users tr.ad-user"),
                              ("/bd/admin.html", CASEY, ".ad-call"),
                              ("/bd/review.html", AVERY, "#rv-body .error-box"),
                              ("/bd/analytics.html", DEVON, "#an-body .error-box")):
        _, pg = page_as(path, email, viewport, wait=wait)
        pg.evaluate("() => document.fonts.ready.then(() => true)")
        assert sideways(pg) <= 1, (path, email, viewport)
