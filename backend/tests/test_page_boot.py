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

from _frontend_tree import pages, rel, scripts, write_tree

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
SUPABASE_SDK = "@supabase/supabase-js"

# Pages that deliberately do not gate: the login page wires sign-in itself, and
# these are fragments/redirects with no API of their own. Keyed by the path under
# frontend/, like every page below (#804): a sub-folder's own login.html is not this one.
NOT_GATED = {"login.html"}


def app_pages(frontend=FRONTEND):
    """Every page, in every sub-folder, that loads auth.js and is not one of NOT_GATED."""
    return [p for p in pages(frontend)
            if rel(p, frontend) not in NOT_GATED and "auth.js" in p.read_text(encoding="utf-8")]


def test_there_are_app_pages_to_check():
    """A rename that empties the glob would make every test below vacuously pass."""
    names = {rel(p) for p in app_pages()}
    assert {"index.html", "projects.html", "done.html", "info-sheet.html", "generate.html"} <= names


@pytest.mark.parametrize("page", app_pages(), ids=rel)
def test_page_loads_the_supabase_sdk_before_auth(page):
    html = page.read_text(encoding="utf-8")
    assert SUPABASE_SDK in html, (
        f"{rel(page)} pulls in auth.js without the Supabase SDK — auth.js will "
        f"return early, never set window.__TW_TOKEN, and every API call 401s.")
    assert html.index(SUPABASE_SDK) < html.index("/auth.js"), (
        f"{rel(page)} loads the Supabase SDK after auth.js; auth.js reads "
        f"window.supabase as it runs, so the order matters.")


@pytest.mark.parametrize("page", app_pages(), ids=rel)
def test_page_loads_shared(page):
    """Every page script reaches for TW.* helpers. Order against auth.js does
    not matter — nothing calls across at load time — but the file has to be
    there."""
    assert "/shared.js" in page.read_text(encoding="utf-8"), \
        f"{rel(page)} is missing shared.js"


@pytest.mark.parametrize("page", app_pages(), ids=rel)
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
            f"{rel(page)} loads {src}, which does not exist"


# Names, initials and avatar colours all come from crm-core.js. Every page that renders a
# person reads `window.TWCrm` as its own script runs, so the order is load-bearing: get it
# wrong and the page throws on boot and renders nothing at all.
PERSON_PAGES = ["portal.html", "projects.html", "admin.html", "analytics.html", "crm.html",
                "notifications.html", "trash.html", "done.html", "proposal-review.html",
                "calendar.html", "polish-estimates.html"]


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
    assert ".tw-av{" in (FRONTEND / "auth.js").read_text(encoding="utf-8")
    dupes = chip_redefinitions()
    assert not dupes, f"these pages re-define the .tw-av chip: {dupes}"


def chip_redefinitions(frontend=FRONTEND):
    """Every page, in every sub-folder, whose own <style> defines the .tw-av chip."""
    import re as _re
    # A RULE, not a mention: both pages carry a comment pointing at auth.js, and that
    # comment is the thing telling the next person where the chip lives.
    rule = _re.compile(r"\.tw-av(-dim)?\s*(,[^{}]*)?\{")
    return [rel(p, frontend) for p in pages(frontend)
            if rule.search(p.read_text(encoding="utf-8"))]


def test_the_per_project_notify_chips_carry_no_identity_colour():
    """On a TOGGLE, green already means "receives", so a per-person avatar colour makes green
    ambiguous: is the chip on, or is that just Alejandro? State owns colour there; the initials
    say who it is. The plain LIST of people (the global roster chips) keeps the shared coloured
    avatar, because nothing there competes with it.

    Counted rather than line-matched. This used to read the one line holding
    `esc(nameOf(person.email))`, and the per-step matrix added a second place rendering a person
    inside a toggle, on markup split across lines — so the heuristic silently started checking a
    different control than the one it names. Two toggles now, and the rule is about both."""
    js = (FRONTEND / "js" / "notifications.js").read_text(encoding="utf-8")
    # The colourless avatar is used by BOTH toggles: the per-project chip and the matrix row.
    assert js.count("plainAvatar(person.email)") == 2, (
        "a toggle stopped using plainAvatar, or a third one appeared without it")
    # And the coloured one is used ONLY by the roster chips, which are a list and not a toggle.
    coloured = [ln.strip() for ln in js.splitlines()
                if "avatar(" in ln and "plainAvatar" not in ln and "const plainAvatar" not in ln
                and not ln.strip().startswith("*") and not ln.strip().startswith("//")]
    assert coloured == ["wrap.innerHTML = rows.map((x) => {"] or all(
        "avatar(x.email)" in ln for ln in coloured), coloured
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
    offenders = person_name_copies()
    assert not offenders, "re-implemented person naming: " + "; ".join(offenders)


# Local helpers that share the name but name something other than a person, so they are not a second
# copy of crm-core.js's. Keyed by script and by the start of the definition, so a person-naming copy
# added to the same file is still caught. The scan's pattern lost its raw string in #226 and matched
# nothing until #804 put it back; these three were in the tree all along.
NOT_A_PERSON = {
    ("js/bid-model.js", "var nameOf = function (id)"),       # a sheet's entry, by tab id
    ("js/generate.js", "function nameOf(m, data)"),          # a proposal's display name
    ("js/proposal-review.js", "const nameOf = (m)"),         # a base bid's label
}


def person_name_copies(frontend=FRONTEND):
    """'<path under frontend/>: <line>' for every script, in every sub-folder, that defines its own
    nameOf or initialsOf rather than aliasing crm-core.js's."""
    import re as _re
    offenders = []
    for js in scripts(frontend):
        name = rel(js, frontend)
        # crm-core.js is the one home; auth.js keeps a guarded fallback for login.html, which
        # loads no page modules.
        if name in ("js/crm-core.js", "auth.js"):
            continue
        body = js.read_text(encoding="utf-8")
        # A local definition, not a `const nameOf = window.TWCrm.nameOf` alias.
        for m in _re.finditer(r"(?:function|const|let|var)\s+(nameOf|initialsOf)\b(.*)", body):
            if "TWCrm" in m.group(2):
                continue
            if any(name == path and m.group(0).startswith(start) for path, start in NOT_A_PERSON):
                continue
            offenders.append(f"{name}: {m.group(0)[:60]}")
    return offenders


@pytest.mark.parametrize("page", app_pages(), ids=rel)
def test_page_has_no_inline_script(page):
    """The CSP blocks inline <script> and onclick=. An inline handler silently
    does nothing in production while working fine from a file:// preview."""
    html = page.read_text(encoding="utf-8")
    for chunk in html.split("<script")[1:]:
        head, _, body = chunk.partition(">")
        if "src=" in head:
            continue
        assert not body.split("</script>")[0].strip(), \
            f"{rel(page)} has an inline <script> block; the CSP will refuse it"
    assert "onclick=" not in html.lower(), f"{rel(page)} has an inline onclick handler"


# ── the scans reach sub-folders (#804) ───────────────────────────────────────
def test_every_scan_here_sees_a_page_or_script_in_a_sub_folder(tmp_path):
    """The BD CRM moves in under /bd/ with pages named like the root's. Each scan in this file walks
    the whole tree and keys what it finds by its path under frontend/, so bd/admin.html is neither
    skipped nor folded into admin.html."""
    gated = '<script src="/auth.js"></script>'
    write_tree(tmp_path, {
        "admin.html": gated,
        "login.html": gated,
        "bd/admin.html": gated + "<style>.tw-av{color:red}</style>",
        "bd/login.html": gated,
        "bd/js/people.js": "function nameOf(e) { return e; }\n",
    })
    assert [rel(p, tmp_path) for p in app_pages(tmp_path)] == ["admin.html", "bd/admin.html", "bd/login.html"]
    assert chip_redefinitions(tmp_path) == ["bd/admin.html"]
    assert [o.split(":")[0] for o in person_name_copies(tmp_path)] == ["bd/js/people.js"]
