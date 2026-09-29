"""Data reaches the estimate and proposal pages as TEXT, never as markup.

The 2026-09-28 security review found six places that built page markup out of values that are not
ours and let them through as markup. Any one of them carrying `<img src=x onerror=...>`, or a `"`
that closes an attribute and opens `onfocus="..."`, would have run script inside a signed-in staff
session -- where the Supabase login token sits in localStorage, so one pasted value was enough to
take over the account.

  1. The AI-autofill banner joined the AI's answers straight into innerHTML.
  2. The texture <select> on both pages wrote an off-list texture (the AI's or a saved draft's)
     into option markup, escaping only the double quote.
  3. A manual price-line amount went into `value="..."` unescaped.
  4. A notification's link was followed whatever its scheme -- `javascript:` included.
  5. (test_editor_paste_and_save.py) pasted HTML was parsed by an element of the live page.
  6. Three escape helpers skipped the single quote.

Everything asserted below is read off a RUN: `tests/js/escape-page-text-harness.js` lifts each
function out of the shipped file by name and executes it against a small DOM whose innerHTML is a
real tokenizer, so an escape that is missing shows up as an element or an attribute the DATA made.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "escape-page-text-harness.js"

PAY = "<b>bold</b> & \"dq\" 'sq' <img src=x onerror=alert(1)>"
ATTR_PAY = '1" autofocus onfocus="alert(1)'


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, (
        "the harness itself failed -- read this before assuming a product bug:\n" + proc.stderr)
    got = json.loads(proc.stdout.strip().splitlines()[-1])
    # The payloads the harness used are the ones this file reasons about.
    assert got["PAY"] == PAY and got["ATTR_PAY"] == ATTR_PAY
    return got


# ═══ 1. the AI-autofill banner ═══════════════════════════════════════════════
def test_the_autofill_banner_shows_the_ais_answer_as_words(ran):
    """The AI answered the Local flag with markup. The banner shows the characters it sent and
    builds no element out of them: the only <b>s are the banner's own five (three headings and the
    two flag values), and nothing carries an attribute the banner did not write.

    Mutation: `${v}` for `${escHtml(v)}` in the filledFlags line. An IMG and a sixth B appear."""
    got = ran["autofill"]
    assert got is not None, "the banner was never shown -- the scenario is vacuous"
    assert "IMG" not in got["tags"]
    assert got["tags"].count("B") == 5
    assert set(got["tags"]) <= {"DIV", "B", "BR", "SPAN", "I", "BUTTON"}
    assert set(got["attrNames"]) <= {"class", "style"}
    assert "Local: " + PAY in got["text"]


# ═══ 2. the texture <select>, both pages ═════════════════════════════════════
@pytest.mark.parametrize("page", ["estimate", "proposal"])
def test_an_off_list_texture_is_an_option_not_markup(ran, page):
    """A texture that is not one of the five is kept as the first option, as before -- and it is
    whatever the AI or a saved draft left in state.texture. It is now an option whose text and value
    ARE that string; no element is made from it, and the select still shows it as chosen.

    Mutation: put the `sel.innerHTML = '<option ...>' + opts.map(...)` builder back. A B and an IMG
    are parsed inside the select, and its value no longer matches the saved texture."""
    got = ran["texture"][page]["hostile"]
    assert got["tag"] == "SELECT"
    assert got["tags"] == ["OPTION"] * 7
    assert got["options"][0] == {"value": "", "text": "—"}
    assert got["options"][1] == {"value": PAY, "text": PAY}
    assert got["value"] == PAY


@pytest.mark.parametrize("page,texture", [("estimate", "Orange Peel"), ("proposal", "Medium")])
def test_a_texture_on_the_list_is_still_selected_among_the_five(ran, page, texture):
    """The ordinary case, pinned so the rebuild cannot have changed what the estimator sees."""
    got = ran["texture"][page]["onList"]
    assert [o["value"] for o in got["options"]] == [
        "", "Smooth", "Orange Peel", "Light", "Medium", "Heavy"]
    assert [o["text"] for o in got["options"]][0] == "—"
    assert got["value"] == texture
    if page == "estimate":
        assert got["inPage"] is True
    else:
        assert got["className"] == "ro"


# ═══ 3. the manual price-line inputs ═════════════════════════════════════════
def test_a_price_line_amount_cannot_leave_its_attribute(ran):
    """The amount lands inside `value="..."`. Unescaped, its `"` closed the attribute and the rest
    became `autofocus onfocus="alert(1)"` -- script on the next render of the Estimate step. Now the
    input's value is the whole string and the input has no attribute the markup did not write.

    Mutation: `${p.amount ?? ""}` for `${escHtml(p.amount ?? "")}`. onfocus and autofocus appear."""
    row = ran["priceLines"][0]
    assert row["tags"] == ["INPUT", "INPUT", "BUTTON"]
    assert row["amount"] == ATTR_PAY
    assert row["amountAttrs"] == ["data-k", "placeholder", "style", "type", "value"]
    assert row["label"] == PAY


def test_an_ordinary_price_line_reads_back_as_typed(ran):
    row = ran["priceLines"][1]
    assert row["label"] == "Mockup"
    assert row["amount"] == "250"


# ═══ 4. notification links ═══════════════════════════════════════════════════
FOLLOWED = ["crm", "draft", "portal", "dropbox", "ownOrigin"]
REFUSED = ["js", "jsMixedCase", "jsLeadingSpace", "data", "protocolRelative", "backslash",
           "tabToSlashes", "offSite", "plainHttpOwnHost", "lookalikeDropbox",
           "jsOnDropboxHost", "httpDropbox", "ftpDropbox"]


@pytest.mark.parametrize("name", FOLLOWED)
def test_a_notification_link_on_our_own_site_is_followed(ran, name):
    """Every link notifications.py sends is a path from the root, plus the "Filed to Dropbox" item's
    folder share link on www.dropbox.com. The bell's <a> points at it and clicking the toast goes
    there, exactly as before."""
    got = ran["links"][name]
    assert got["toasted"] is True
    assert got["href"] == got["link"]
    assert got["navigated"] == [got["link"]]


@pytest.mark.parametrize("name", REFUSED)
def test_any_other_notification_link_goes_nowhere(ran, name):
    """A `javascript:` link in the bell ran in the page on click, and the toast handed ANY string to
    `location.href`. Now the <a> points at "#" and the toast click does nothing. The toast is still
    shown and still clicked -- `toasted` is checked so this cannot pass by never reaching the click.

    The tab case is the one a read of the string misses: the URL parser strips it, and "/\\t/host"
    becomes "//host", another site. The link is resolved before it is judged.

    The Dropbox exception keys on the hostname, and "javascript://www.dropbox.com/%0A..." parses
    to hostname "www.dropbox.com" with a `javascript:` scheme; setting location.href to it runs
    the code after the %0A. The https-scheme check is the only thing that refuses it (and the
    http/ftp Dropbox cases), so those three cases pin that line.

    Mutation: put `n.link` back at the two call sites. Every case here navigates.
    Mutation: delete `if (u.protocol !== "https:") return "";`. The three Dropbox-host cases
    navigate."""
    got = ran["links"][name]
    assert got["toasted"] is True
    assert got["safe"] == ""
    assert got["href"] == "#"
    assert got["navigated"] == []


# ═══ 6. the escape helpers that missed the single quote ═════════════════════
@pytest.mark.parametrize("fn", ["renderAddr", "renderBusinesses"])
def test_the_intake_address_lookup_escapes_all_five_characters(ran, fn):
    """The lookup service's answer is shown as text, the single quote included -- no `'` survives
    into the markup, so the helper is safe in a single-quoted attribute too, and the words still
    read "O'Fallon".

    Mutation: drop `'` from the esc in index.js. A raw `'` reaches the markup."""
    got = ran["intake"][fn]
    assert "'" not in got["markup"]
    assert "&#39;" in got["markup"]
    assert set(got["tags"]) == {"DIV"}
    assert PAY in got["text"] and "O'Fallon, MO, 63366" in got["text"]


def test_the_bid_bar_escape_covers_all_five_characters(ran):
    """Mutation: drop `'` from _escBB in estimate-review.js."""
    assert ran["escBB"] == (
        "&lt;b&gt;bold&lt;/b&gt; &amp; &quot;dq&quot; &#39;sq&#39; "
        "&lt;img src=x onerror=alert(1)&gt;")
