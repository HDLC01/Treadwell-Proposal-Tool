"""Every app page has to boot the same way, and getting it wrong fails quietly.

`auth.js` mints the bearer token the whole API depends on. Its `init()` gives up
at the first check if `window.supabase` is absent — no throw, no redirect, just
a page that renders and then 401s on its first fetch. A new page that forgets
the SDK script looks fine until you click something.

That is exactly how the Project Info Sheet shipped to staging the first time, so
the rule is pinned here rather than left to whoever adds the next page.
"""
import pathlib

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
SUPABASE_SDK = "@supabase/supabase-js"

# Pages that deliberately do not gate: the login page wires sign-in itself, and
# these are fragments/redirects with no API of their own.
NOT_GATED = {"login.html"}


def app_pages():
    return sorted(p for p in FRONTEND.glob("*.html")
                  if p.name not in NOT_GATED and "auth.js" in p.read_text(encoding="utf-8"))


def test_there_are_app_pages_to_check():
    """A rename that empties the glob would make every test below vacuously pass."""
    names = {p.name for p in app_pages()}
    assert {"index.html", "projects.html", "done.html", "info-sheet.html"} <= names


@pytest.mark.parametrize("page", app_pages(), ids=lambda p: p.name)
def test_page_loads_the_supabase_sdk_before_auth(page):
    html = page.read_text(encoding="utf-8")
    assert SUPABASE_SDK in html, (
        f"{page.name} pulls in auth.js without the Supabase SDK — auth.js will "
        f"return early, never set window.__TW_TOKEN, and every API call 401s.")
    assert html.index(SUPABASE_SDK) < html.index("/auth.js"), (
        f"{page.name} loads the Supabase SDK after auth.js; auth.js reads "
        f"window.supabase as it runs, so the order matters.")


@pytest.mark.parametrize("page", app_pages(), ids=lambda p: p.name)
def test_page_loads_shared(page):
    """Every page script reaches for TW.* helpers. Order against auth.js does
    not matter — nothing calls across at load time — but the file has to be
    there."""
    assert "/shared.js" in page.read_text(encoding="utf-8"), \
        f"{page.name} is missing shared.js"


@pytest.mark.parametrize("page", app_pages(), ids=lambda p: p.name)
def test_every_local_script_it_pulls_in_exists(page):
    """A typo'd src is a silent 404 — the page renders and then the first click does
    nothing, which is indistinguishable from a logic bug."""
    html = page.read_text(encoding="utf-8")
    for chunk in html.split("<script")[1:]:
        head = chunk.partition(">")[0]
        if 'src="/' not in head:
            continue
        src = head.split('src="', 1)[1].split('"', 1)[0]
        path = src.split("?", 1)[0]        # some pages cache-bust with ?v=<date>
        assert (FRONTEND / path.lstrip("/")).is_file(), \
            f"{page.name} loads {src}, which does not exist"


# Names, initials and avatar colours all come from crm-core.js. Every page that renders a
# person reads `window.TWCrm` as its own script runs, so the order is load-bearing: get it
# wrong and the page throws on boot and renders nothing at all.
PERSON_PAGES = ["portal.html", "projects.html", "admin.html", "analytics.html", "crm.html",
                "notifications.html", "trash.html", "done.html", "proposal-review.html",
                "calendar.html"]


@pytest.mark.parametrize("name", PERSON_PAGES)
def test_a_page_that_names_a_person_loads_crm_core_first(name):
    html = (FRONTEND / name).read_text(encoding="utf-8")
    assert "/js/crm-core.js" in html, (
        f"{name} renders a person but never loads crm-core.js — window.TWCrm will be "
        f"undefined and the page's own script will throw as it runs.")
    page_js = "/js/" + name.replace(".html", ".js")
    if page_js in html:
        assert html.index("/js/crm-core.js") < html.index(page_js), (
            f"{name} loads crm-core.js AFTER {page_js}; the page reads window.TWCrm as it runs.")


def test_the_person_chip_is_styled_in_exactly_one_place():
    """`.tw-av` lives in auth.js's injected stylesheet, which every page loads. A second
    copy in a page's own <style> is how one person ends up a different size or a
    different shape on one screen."""
    import re as _re
    assert ".tw-av{" in (FRONTEND / "auth.js").read_text(encoding="utf-8")
    # A RULE, not a mention: both pages carry a comment pointing at auth.js, and that
    # comment is the thing telling the next person where the chip lives.
    rule = _re.compile(r"\.tw-av(-dim)?\s*(,[^{}]*)?\{")
    dupes = [p.name for p in FRONTEND.glob("*.html")
             if rule.search(p.read_text(encoding="utf-8"))]
    assert not dupes, f"these pages re-define the .tw-av chip: {dupes}"


def test_the_per_project_notify_chips_carry_no_identity_colour():
    """On that control green already means "receives this project's email", so a
    per-person avatar colour makes green ambiguous — is the chip on, or is that just
    Alejandro? State owns colour there; the initials say who it is. The rest of the page
    (the global roster) keeps the shared coloured chip."""
    js = (FRONTEND / "js" / "notifications.js").read_text(encoding="utf-8")
    chip = next(ln for ln in js.splitlines() if "esc(nameOf(person.email))" in ln)
    assert "plainAvatar(" in chip and "avatar(" not in chip.replace("plainAvatar(", ""), (
        "the per-project chip is back on TWCrm.avatarHtml — its identity colour fights the "
        "green/not-green state the chip is there to show")
    assert "avatar(x.email)" in js, "the global roster chips should still be colour-coded"
    # Neutral by construction, not by overriding the shared class: .tw-av rides an inline
    # background, so re-tinting it would take an !important a page must not own — and
    # test_the_person_chip_is_styled_in_exactly_one_place forbids the rule outright.
    css = (FRONTEND / "notifications.html").read_text(encoding="utf-8")
    assert ".nt-chip .nt-av" in css
    assert "!important" not in css


def test_the_drawer_notify_chips_carry_no_identity_colour():
    """The CRM drawer hosts the per-project half of the same control, with the same help
    text ("Green = receives this project's emails"), so it has to make the same trade:
    state owns colour, the initials say who. Every OTHER person on that page — the board
    cards, the table, the follow-up assignee — keeps their identity colour."""
    js = (FRONTEND / "js" / "portal.js").read_text(encoding="utf-8")
    chip = next(ln for ln in js.splitlines() if "esc(nameOf(p.email))" in ln)
    assert "plainAvatar(" in chip and "avatar(" not in chip.replace("plainAvatar(", ""), (
        "the drawer's notification chip is back on TWCrm.avatarHtml — its identity colour "
        "fights the green/not-green state the chip exists to show")
    # The board still colour-codes people; only this one control opts out.
    assert "avatar(email, !isAssigned(p))" in js
    css = (FRONTEND / "portal.html").read_text(encoding="utf-8")
    assert ".nt-chip .nt-av" in css
    # Neutral by construction, not by re-tinting the shared chip: .tw-av's colour rides an
    # inline background, so overriding it would take an !important on a class this page
    # does not own — and test_the_person_chip_is_styled_in_exactly_one_place forbids the
    # rule outright.
    av = [rule for rule in css.split("}") if ".nt-av" in rule]
    assert av and not any("!important" in rule for rule in av)


def test_the_person_chip_aligns_against_its_own_line():
    """`vertical-align` in px is an absolute shift, so one tuned value is correct at one
    font-size only — a 20px chip nudged -4px sat ~5px low in the 12px "Estimator:" line on
    the portal cards while looking fine in a 13px table. `middle` is measured against the
    parent's x-height, so it re-centres itself everywhere the chip is used."""
    css = (FRONTEND / "auth.js").read_text(encoding="utf-8")
    rule = css[css.index(".tw-av{"):]
    rule = rule[:rule.index("}")]
    assert "vertical-align:middle" in rule, (
        "the shared person chip is back on a pixel baseline offset; it can only be right "
        "at one font-size and the app renders it at 11, 12, 12.5, 13 and 14px")


def test_there_is_one_implementation_of_a_person_name():
    """Four separate copies of email-to-display-name existed, and three of initials —
    including one in auth.js whose paren placement made it return a SINGLE letter for
    every two-word name. One source of truth or the app disagrees with itself."""
    import re as _re
    offenders = []
    for js in sorted(FRONTEND.glob("*.js")) + sorted((FRONTEND / "js").glob("*.js")):
        if js.name == "crm-core.js":
            continue
        body = js.read_text(encoding="utf-8")
        # A local definition, not a `const nameOf = window.TWCrm.nameOf` alias.
        for m in _re.finditer(r"(?:function|const|let|var)\s+(nameOf|initialsOf)(.*)", body):
            if "TWCrm" not in m.group(2):
                offenders.append(f"{js.name}: {m.group(0)[:60]}")
    # auth.js keeps a guarded fallback for login.html, which loads no page modules.
    offenders = [o for o in offenders if not o.startswith("auth.js")]
    assert not offenders, "re-implemented person naming: " + "; ".join(offenders)


@pytest.mark.parametrize("page", app_pages(), ids=lambda p: p.name)
def test_page_has_no_inline_script(page):
    """The CSP blocks inline <script> and onclick=. An inline handler silently
    does nothing in production while working fine from a file:// preview."""
    html = page.read_text(encoding="utf-8")
    for chunk in html.split("<script")[1:]:
        head, _, body = chunk.partition(">")
        if "src=" in head:
            continue
        assert not body.split("</script>")[0].strip(), \
            f"{page.name} has an inline <script> block; the CSP will refuse it"
    assert "onclick=" not in html.lower(), f"{page.name} has an inline onclick handler"
