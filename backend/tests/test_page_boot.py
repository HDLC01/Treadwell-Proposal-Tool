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
