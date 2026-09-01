"""The optional cover letter, on the estimator's side of it.

WHAT WAS ASKED FOR. A short letterhead page in front of the proposal, on the bids that want one.
Most bids do not. So the whole feature hangs off one checkbox in the Proposal step's ribbon, and
the first thing these tests pin is that with the checkbox alone the page behaves exactly as it did
before the feature existed: no request goes out, no field is added to the payload, and the
document tabs are not on screen at all. A feature nobody asked for should cost nothing to ignore.

WHY THE EDITOR IS ITS OWN FILE AND NOT MORE OF proposal-review.js. Six of that file's functions —
renderBlock, collectOverrides, schedulePersistOverrides, effectiveWorkType, setBlockContent,
serializeBlock — are regex-LIFTED out of it by the harnesses in js/, which compile them alone. A
lifted function that grows a call to a NEW function dies with a ReferenceError, and every scenario
in that harness dies with it; that has cost this repo six debugging sessions in a single day. So
the cover letter is a separate IIFE that publishes one object, borrows what it needs by
feature-detected lookup on `window`, and DUPLICATES the one inference it cannot borrow.

THE DUPLICATION IS THE RISKY PART, so it is tested directly. `clWorkType` is a second copy of
`effectiveWorkType` (which letter you get is decided the same way as which proposal you get: the
base-bid tab's ROLE wins over the intake work type, and `combo` short-circuits). A copy with
nothing watching it is a fork waiting to happen, so the harness LIFTS the proposal's own function
and runs both over the same table of draft states. If someone changes one rule and not the other,
that test says so by name.

THE PR #393 INVARIANT, restated because it is the one thing about this editor that is not
negotiable. ONE contenteditable host per section — the text box, or the flowing body — and never
one per paragraph. A browser selection cannot cross a contenteditable boundary, so per-paragraph
hosts break select-all, cross-paragraph drag and undo, and draw a box round every line. That was
the old proposal editor and it was replaced for exactly those reasons; a new editor that
reintroduced it would be the same bug with a new name.

WHY THE BEHAVIOUR HALF RUNS UNDER NODE, EXECUTED. `js/coverletter-editor-harness.js` runs the
WHOLE shipped file in a vm context with the smallest DOM it touches, and drives it through the
checkbox and the tabs rather than by calling its internals. Every claim below is several functions
agreeing — whether an edit under one audience survives a switch to another, whether a stale
template version is replayed, whether the fetch that failed left a way out — and a source-text
assertion sees none of it. This repo has already paid for that: on 2026-08-12 `STAGE_CREATED`
shipped unbound with every source assertion green and took the production board down.

THE CSS HALF IS A SOURCE READ, and has to be — no stubbed DOM applies a stylesheet, and the two
cascade traps this file has to clear are both invisible to "the rule is present":
  * a class `display` rule beats the `hidden` ATTRIBUTE, which is how four elements in this repo
    have shipped hidden and still on screen. `.doc-tabs` sets `display: flex`, so the tab strip's
    `hidden` needs a rule of its own that outranks it.
  * specificity beats source order, so `.cl-offstage` is resolved here rather than assumed.

ONE THING THIS FILE CANNOT PROVE, and it belongs in the report rather than in a skipped test: the
endpoint's real response. The backend half was being built in parallel while this was written, so
the fixtures are the agreed contract — `{work_type, template_name, template_version, geometry,
blocks}`, with the DATE anchored in `geometry.boxes[0]` and the body flowing — and not an observed
payload. If the shape lands differently, the fixtures at the top of the harness are the one place
to change.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "coverletter-editor-harness.js"
PR_PAGE = (FRONTEND / "proposal-review.html").read_text(encoding="utf-8")
DONE_PAGE = (FRONTEND / "done.html").read_text(encoding="utf-8")
PR_JS = (FRONTEND / "js" / "proposal-review.js").read_text(encoding="utf-8")
DONE_JS = (FRONTEND / "js" / "done.js").read_text(encoding="utf-8")
CL_JS = (FRONTEND / "js" / "coverletter-editor.js").read_text(encoding="utf-8")
# The editor's CODE, with the comments taken out. The comments in this codebase quote the incident
# that made each line necessary, so `blob:` and `createObjectURL` are written out in prose on
# purpose — a probe that could not tell prose from code would report the EXPLANATION of the CSP bug
# as the bug itself. LINE comments first, THEN block comments, and that order is load-bearing
# rather than tidy: done the other way round, a `/*` sitting inside a `//` comment reads as a block
# opener and pairs with the next real terminator, deleting everything between them.
CL_CODE = re.sub(r"/\*.*?\*/", "",
                 re.sub(r"(^|[^:\"'`\\])//[^\n]*", r"\1", CL_JS, flags=re.M), flags=re.S)


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ══ off is genuinely off ══════════════════════════════════════════════════════
def test_a_bid_that_does_not_want_a_cover_letter_pays_nothing_for_the_feature(ran):
    """The default, and the promise the whole design rests on. Not "the letter is hidden" — the
    letter does not exist: no template request goes out, the surface is empty, the document tabs
    are off the page, and the three payload fields say so rather than being absent (the backend
    reads `cover_letter_enabled`, and a missing key and a false key must not mean different
    things to it)."""
    d = ran["defaultOff"]
    assert d["checked"] is False, "the checkbox is on by default — most bids do not want a letter"
    assert d["tabsHidden"] is True, "the document tabs are on screen before there is a document"
    assert d["fetched"] == 0, "a template was fetched for a letter nobody asked for"
    assert d["surfaceEmpty"] is True
    assert d["payload"] == {"cover_letter_enabled": False,
                            "cover_letter_paragraph_overrides": {},
                            "cover_letter_template_version": ""}
    assert d["stored"] is False


def test_ticking_the_box_shows_the_letter_rather_than_a_tab_somewhere_else(ran):
    """A checkbox whose only visible effect is a tab strip appearing elsewhere in the chrome is a
    checkbox people press twice and then untick, because nothing happened. Ticking it is a request
    to SEE the thing, so the view switches to it."""
    t = ran["tabs"]
    assert t["before"]["cl"] is True and t["before"]["doc"] is False
    assert t["onCover"]["doc"] is True, "the proposal is still in front after asking for a letter"
    assert t["onCover"]["cl"] is False
    assert "active" in t["onCover"]["coverTab"] and "active" not in t["onCover"]["proposalTab"]
    # And the strip is wired, clicked rather than called.
    assert t["backOnProposal"]["doc"] is False and t["backOnProposal"]["cl"] is True
    assert t["clickedBack"]["doc"] is True and t["clickedBack"]["cl"] is False


def test_the_switch_aims_the_formatting_ribbon_at_nothing(ran):
    """THE SUBTLE ONE. The ribbon deliberately keeps its target after focus leaves the paragraph —
    that was the whole point of making it static (see test_fmt_ribbon) — and it is scoped to
    `#doc-surface`. So with the letter in front, a press on Bold would format a proposal paragraph
    that is not on screen, in a customer-facing document, with nothing to notice it by. `idleFmtBar`
    is the existing way to say "aimed at nothing", and the switch has to call it every time."""
    t = ran["tabs"]
    assert t["before"]["idled"] == 0, "something idled the ribbon before the letter was asked for"
    assert t["onCover"]["idled"] == 1, "the ribbon still points at a proposal paragraph off-screen"
    assert t["clickedBack"]["idled"] == 2, "only the first switch let go of the paragraph"


def test_reopening_a_draft_that_already_has_a_letter_opens_on_the_proposal(ran):
    """The other side of the reveal, and the reason it is a parameter rather than the rule. The
    step is called "3 · Proposal"; an estimator coming back to a saved draft came back for the
    bid. The letter is loaded anyway, off-stage, so the tab is instant when they want it."""
    r = ran["reopen"]
    assert r["checked"] is True and r["tabsHidden"] is False, "the saved choice was not restored"
    assert r["doc"] is False and r["cl"] is True, "a saved draft opened on the cover letter"
    assert r["idled"] == 0, "the ribbon was reset on a page load that never left the proposal"
    assert r["warmed"] is True, "the letter is not loaded until it is asked for, so the tab stalls"


# ══ the editing model ═════════════════════════════════════════════════════════
def test_no_paragraph_is_its_own_editing_host(ran):
    """THE PR #393 INVARIANT, and the reason this editor exists in the shape it does.

    A browser selection cannot cross a contenteditable boundary. Make each paragraph its own host
    and select-all stops at one line, a drag across two paragraphs selects neither, undo splits
    per box, and every line gets a focus ring round it. That was the editor this repo replaced.
    Asserted in both layouts, because the flow branch is where it would be easiest to slip back
    into: one host on the page, or one host per box, and never one per line."""
    for name in ("positioned", "flow"):
        assert ran[name]["blockHosts"] == 0, (
            "%s layout: a paragraph carries contentEditable of its own" % name)
    assert ran["positioned"]["boxEditable"] == "true", "the date box is not editable at all"
    assert ran["positioned"]["bodyEditable"] == "true", "the flowing body is not editable at all"
    assert ran["positioned"]["pageEditable"] != "true", (
        "the whole page is an editing host on top of the boxes — two hosts claim the same text")
    assert ran["flow"]["pageEditable"] == "true", (
        "with no boxes the page itself must be the host, or nothing is editable")


def test_the_date_is_drawn_where_the_letterhead_was_drawn_for_it(ran):
    """Kyle's letter anchors the date in a floating text box over the artwork. The box is rendered
    at the template's OWN coordinates, in points, converted from nothing — the geometry is read,
    never invented, and never adjusted.

    AND THERE ARE NO GRIPS. The proposal's boxes are Kyle's design surface and he drags them; this
    one is registered against baked artwork, so a handle offering to move it would only offer a
    way to get it wrong. Position is read, only text is written."""
    p = ran["positioned"]
    assert p["boxes"] == 1
    assert p["boxGeom"] == {"left": "396pt", "top": "158.4pt", "width": "144pt"}
    assert p["dateBlock"]["boxed"] is True, "the date fell out of its box into the flow"
    assert p["bodyBlock"]["boxed"] is False, "a body paragraph was swept into the date box"
    assert p["grips"] == 0, "a drag or resize handle was added to a box that must not move"


def test_a_template_with_no_boxes_is_a_layout_and_not_a_failure(ran):
    """The endpoint served exactly this before the date box was baked into the templates, and a
    plain letter is a perfectly good letter. So the flow branch renders the whole document with
    the page's own margins as padding — not an error card, and not an empty sheet."""
    f = ran["flow"]
    assert f["boxes"] == 0 and f["blocks"] == 3
    assert f["padded"] == "72pt 90pt 72pt 90pt", (
        "the flow layout ignored the template's margins, so the letter starts at the sheet edge")


def test_the_letterhead_arrives_as_a_data_uri_behind_the_text(ran):
    """`data:`, not `blob:`, and this is not a preference. The tool's CSP is an nginx `$host` map
    on the VPS and its `img-src` does not carry `blob:` on every host — a blob URL renders
    perfectly in local development and shows nothing in production. That is precisely how no
    attachment photo rendered on prod for weeks (2026-08-27). And it is PREPENDED, so the artwork
    lands under the text whichever of the two async loads resolves first."""
    p = ran["positioned"]
    assert p["art"] == "data:image/", "the letterhead is not a data: URI — the CSP will drop it"
    assert p["artBehindText"] == "tw-page-art", (
        "the artwork is not the first child, so it can cover the text it is meant to sit behind")
    assert "blob:" not in CL_CODE and "createObjectURL" not in CL_CODE, (
        "the artwork is handed to the page as a blob URL, which production's CSP will drop")


def test_the_body_is_appended_under_the_boxes_and_not_over_them(ran):
    """THE BUG THAT ONLY A CLICK FOUND. `.cl-body` and `.tw-txbx` both carry `z-index: 1`
    (`styles.css:898` and the page's own rule) and with equal z-index the LATER sibling paints on
    top. The body is a full-page click surface, so appending it after the boxes covers every one of
    them: the date box renders in the right place, looks editable, and swallows the click.

    Read out of the LIVE DOM, not out of the source. A source assertion cannot see paint order at
    all — which is the same reason `STAGE_CREATED` took the prod board down on 2026-08-12 with
    every source check green."""
    order = ran["positioned"]["pageOrder"]
    assert order, "the page rendered no children — the harness scenario is not exercising render()"
    body = [i for i, c in enumerate(order) if "cl-body" in c]
    boxes = [i for i, c in enumerate(order) if "tw-txbx" in c]
    assert body and boxes, "expected both a body surface and at least one box: %r" % (order,)
    assert max(body) < min(boxes), (
        "the body is painted OVER the boxes and will eat every click meant for the date: %r"
        % (order,))


# ══ what gets saved ═══════════════════════════════════════════════════════════
def test_an_edit_is_saved_in_the_shape_the_backend_reads(ran):
    """`{"<block id>": {"text": "..."}}` — the same shape as the proposal's `paragraph_overrides`,
    because it is read by the same kind of code on the other side. Only the paragraph that was
    TOUCHED is in there: the tokens are filled before the comparison, so a paragraph the estimator
    never opened does not arrive as an override that would freeze today's date into the file."""
    e = ran["edit"]
    assert e["beforeEmpty"] is True
    assert e["flat"] == {"2": {"text": "Thanks for the chance to bid this one."}}
    assert e["untouchedNotSent"] is True, (
        "an untouched paragraph was saved as an override — the fill is being compared wrong")
    assert e["dirty"] is True, "nothing on screen says the paragraph has been changed"
    assert e["version"] == "cl-epoxy-1"
    assert e["payload"]["cover_letter_enabled"] is True


def test_a_paste_out_of_word_is_saved_as_text_and_not_as_markup(ran):
    """Nobody types a cover letter from scratch — they paste a paragraph out of Word, and what
    lands in a contenteditable host is markup: a `<b>`, a `<br>` for the line break, a non-breaking
    space where Word had a space. The backend's field is `text`, a plain string that goes straight
    into a .docx run — so anything that survives as markup here is a literal `<b>` printed in a
    letter a customer reads. `<br>` becomes a real newline (the block renders `pre-wrap`, so the
    break the estimator made is the break they get) and the NBSP becomes an ordinary space, which
    is what stops a pasted line refusing to wrap in the generated document."""
    saved = ran["paste"]["saved"]
    assert saved == {"text": "We are pleased to bid\nthis project."}, (
        "a pasted paragraph was stored as %r" % (saved,))


def test_two_audiences_keep_two_letters(ran):
    """A Direct letter and a GC letter are different files with different wording, so the store is
    keyed `work_type:audience` exactly the way the proposal's per-template overrides are. Merge,
    never replace: writing the GC letter must not throw away what was written for Direct, and
    switching back has to bring it back. Getting this wrong is silent — the estimator only finds
    out when a customer reads the other audience's paragraph."""
    a = ran["audience"]
    assert a["keys"] == ["epoxy:Direct", "epoxy:GC"], "one audience's edits overwrote the other's"
    assert a["direct"]["items"] == {"2": {"text": "Direct wording."}}
    assert a["gc"]["items"] == {"2": {"text": "GC wording."}}
    assert a["backToDirect"] == "Direct wording.", (
        "coming back to Direct showed the GC wording — the wrong entry was replayed")
    assert a["urls"] == ["/api/coverletter-template?work_type=epoxy&audience=Direct",
                         "/api/coverletter-template?work_type=epoxy&audience=GC"], (
        "the audience is not reaching the endpoint, so both audiences get the same file")


def test_edits_are_dropped_rather_than_misapplied_when_the_template_changes(ran):
    """Overrides are keyed by BLOCK ID, and the ids come from walking the .docx. Edit a paragraph,
    let Kyle re-cut the template, and id 2 may now be a different sentence — replaying the old text
    onto it silently rewrites a paragraph nobody chose. So each entry carries the
    `template_version` it was captured against, and a mismatch drops it back to the template's own
    words. Both directions are asserted, so this stays a gate and does not quietly become a wall
    that discards every edit."""
    v = ran["versionGate"]
    assert v["storedUnder"] == ["epoxy:Direct"]
    assert v["staleReplayed"] == "Thank you for the opportunity to bid Olathe Fire Station 4.", (
        "a stale override was replayed onto a re-cut template")
    assert v["staleDirty"] is False
    assert v["matchingReplayed"] == "Wording from before the deploy.", (
        "the version gate is dropping edits even when the template has not changed")
    assert v["matchingDirty"] is True


def test_turning_the_letter_off_does_not_throw_the_words_away(ran):
    """Untick and the payload says no letter — flatly, so nothing downstream generates one. But the
    store keeps the wording, because "off" here means "not on this bid today", and a checkbox that
    destroys ten minutes of typing on a mis-click is a checkbox nobody will risk pressing."""
    o = ran["offKeepsEdits"]
    assert o["enabled"] is False
    assert o["payload"] == {"cover_letter_enabled": False,
                            "cover_letter_paragraph_overrides": {},
                            "cover_letter_template_version": ""}
    assert o["tabsHidden"] is True and o["docOffstage"] is False, (
        "turning the letter off left the proposal off-stage — the estimator sees a blank canvas")
    assert o["kept"]["items"] == {"2": {"text": "Wording worth keeping."}}
    assert o["backOn"] == "Wording worth keeping.", "the wording did not come back"


# ══ when it goes wrong ════════════════════════════════════════════════════════
def test_a_template_that_will_not_load_leaves_a_way_out_that_works(ran):
    """The proposal is unaffected and the bid can still go out today, so this is amber and not red
    — the same palette the page already uses for a correctable mistake. What matters is that both
    ways out are real: Try again, and an off switch that genuinely turns the feature off rather
    than just closing the message. A dead end here would strand an estimator on a step they cannot
    leave, on a bid that is due."""
    f = ran["failure"]
    assert f["warned"] is True and f["role"] == "alert"
    assert f["pages"] == 0, "half a letter was left on screen under the failure notice"
    assert f["buttons"] == ["Try again", "Turn the cover letter off"]
    assert f["afterTurnOff"] == {"enabled": False, "tabsHidden": True, "checked": False}, (
        "the way out closed the message without turning anything off")


# ══ the duplicated inference ══════════════════════════════════════════════════
def test_the_letters_work_type_inference_has_not_drifted_from_the_proposals(ran):
    """WHY THERE ARE TWO COPIES AT ALL: `effectiveWorkType` is lifted out of proposal-review.js by
    five harnesses, and a lifted function that grows a caller becomes a dependency any of them can
    break. So the letter carries its own copy — and this is what keeps it a copy rather than a
    fork. The harness lifts the proposal's function and runs both over the same draft states,
    including the three that are easy to get wrong: `combo` short-circuits before the tabs are
    consulted, a base tab's ROLE beats the intake work type, and a `base_tab_id` naming no tab
    falls back rather than throwing."""
    rows = ran["inference"]
    assert len(rows) == 7
    for r in rows:
        assert r["ours"] == r["theirs"], (
            "%s: the letter says %r, the proposal says %r — the copy has drifted"
            % (r["name"], r["ours"], r["theirs"]))
    got = {r["name"]: r["key"] for r in rows}
    assert got["combo wins outright"] == "combo:GC"
    assert got["base role beats intake"] == "polish:Direct"
    assert got["base id names no tab"] == "epoxy:Direct"


def test_both_pages_read_the_payload_fields_through_the_one_helper(ran):
    """The Proposal step's Continue and the Files page's "View files" rebuild both write the same
    three fields into `proposal_payload`, and if they ever disagreed about what "enabled" means, a
    regenerate would quietly produce a different document from the one the estimator checked. One
    exported function, read by both, and it answers the same on a page whose editor never ran."""
    p = ran["payload"]
    assert p["on"]["cover_letter_enabled"] is True
    assert p["coldRead"] == p["on"], (
        "the Files page reads a different answer than the Proposal step wrote")
    # And the fields are composed in exactly ONE place in the frontend.
    for name, src in (("proposal-review.js", PR_JS), ("done.js", DONE_JS)):
        assert "TWCoverLetter.payloadFields()" in src, name
        assert re.search(r'cover_letter_enabled\s*:', src) is None, (
            "%s builds the cover-letter fields by hand as well as through the helper" % name)


def test_the_fields_ride_the_frozen_payload_and_not_merely_the_request():
    """Inside `proposal_payload`, not alongside it. The payload is what gets FROZEN into a sent
    revision, and the portal re-renders a customer's letter from that pinned copy — so a letter
    that rode only the POST body would generate correctly once and then vanish the first time a
    customer re-opened their proposal."""
    m = re.search(r"proposal_payload:\s*\{(.*?)\n      \},", PR_JS, re.S)
    assert m, "the proposal_payload literal moved — rewrite this check, do not delete it"
    assert "TWCoverLetter.payloadFields()" in m.group(1), (
        "the cover-letter fields are outside proposal_payload, so a sent revision loses them")


# ══ the cascade ═══════════════════════════════════════════════════════════════
def _specificity(sel):
    """(ids, classes+attrs+pseudo-classes, elements) — enough for the handful of rules resolved
    here, none of which use `!important` or a pseudo-element."""
    ids = len(re.findall(r"#[\w-]+", sel))
    cls = len(re.findall(r"\.[\w-]+|\[[^\]]+\]|:(?!:)[\w-]+(?:\([^)]*\))?", sel))
    els = len(re.findall(r"(?:^|[\s>+~])([a-zA-Z][\w-]*)", sel))
    return (ids, cls, els)


def _rules(page):
    """(selector, body, index) for every rule in the page's <style>, at-rule wrappers stripped."""
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", page, re.S))
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"@media[^{]*\{", "", css)
    return [(m.group(1).strip(), m.group(2), i)
            for i, m in enumerate(re.finditer(r"([^{}]+)\{([^{}]*)\}", css))]


def _decl(page, selector, prop):
    for sel, body, _ in _rules(page):
        if selector in [s.strip() for s in sel.split(",")]:
            m = re.search(r"(?<![-\w])" + re.escape(prop) + r"\s*:\s*([^;]+)", body)
            if m:
                return m.group(1).strip()
    return None


def test_the_tab_strips_hidden_attribute_can_actually_hide_it():
    """THE TRAP THIS REPO KEEPS FALLING INTO, and it has shipped four times: a class `display` rule
    beats the `hidden` attribute, and the element stays on screen looking like a layout bug with no
    failing test anywhere near it. `.doc-tabs` sets `display: flex`, so `hidden` needs a rule that
    OUTRANKS it. Keyed on the CLASS rather than the id, which is what test_hidden_is_actually_hidden
    demands and what it caught here: an id guard rescues this one element and leaves the next
    `.doc-tabs` on the page broken in exactly the way it is meant to prevent."""
    assert 'id="doc-tabs"' in PR_PAGE and "hidden>" in PR_PAGE.split('id="doc-tabs"')[1][:400]
    # Every rule that puts a `display` on .doc-tabs — MINUS the guard itself, which of course
    # cannot be asked to outrank its own declaration.
    flex = [(s, i) for s, b, i in _rules(PR_PAGE)
            if ".doc-tabs" in s and "[hidden]" not in s
            and re.search(r"(?<![-\w])display\s*:", b)]
    assert flex, "nothing sets display on .doc-tabs — this test is watching the wrong rule"
    assert _decl(PR_PAGE, ".doc-tabs[hidden]", "display") == "none", (
        "the tab strip has no display:none for its hidden attribute, so `hidden` does nothing")
    mine = _specificity(".doc-tabs[hidden]")
    for sel, _ in flex:
        for one in (s.strip() for s in sel.split(",")):
            if ".doc-tabs" in one:
                assert mine > _specificity(one), (
                    ".doc-tabs[hidden] does not outrank %r — it is only winning on source order"
                    % one)


def test_the_document_that_is_not_in_front_goes_off_screen_not_to_display_none():
    """NOT A STYLE CHOICE. The proposal's Terms pages are paginated by measuring real element
    heights, and everything inside a `display: none` subtree measures zero — so a repagination that
    fired while the proposal was hidden would pack the Terms wrong, in a document with a signature
    line on it, and there would be nothing on screen to notice it by. Off-stage still lays out.

    And it wins on SPECIFICITY. The first version of this rule used `!important`, which is the
    house's other standing lesson: two rounds of "make it smaller" once changed a value that could
    never apply, because the fight was being settled by force instead of by rank."""
    off = _decl(PR_PAGE, "#doc-surface.cl-offstage", "position")
    assert off == "absolute", "the inactive document is not being moved off-stage"
    for sel, body, _ in _rules(PR_PAGE):
        if "cl-offstage" in sel:
            assert "display" not in body, (
                "the inactive document is display:none — the Terms will paginate against zero "
                "heights: %r" % body.strip())
            assert "!important" not in body, "cl-offstage is winning by force, not by rank"
    assert _specificity("#doc-surface.cl-offstage") > _specificity(".cl-offstage")


def test_the_tab_button_reset_comes_before_the_rule_it_is_resetting():
    """Source order, deliberately, and written down because it is the exception. `#doc-tabs`' tabs
    are `<button>`s — they switch a view, they do not navigate — and a button arrives with a border
    of its own, so `border: 0` is needed. But the shared `.word-ribbon .tab, .doc-tabs .tab` rule
    re-states `border-bottom` at the SAME specificity, which is what draws the active underline.
    Equal rank means later wins, so putting the reset after it silently removes the underline."""
    order = {}
    for sel, body, i in _rules(PR_PAGE):
        parts = [s.strip() for s in sel.split(",")]
        if ".doc-tabs .tab" in parts and "border: 0" in body:
            order["reset"] = i
        if ".doc-tabs .tab" in parts and "border-bottom" in body:
            order["shared"] = i
    assert "reset" in order and "shared" in order, (
        "the tab rules were restructured — re-derive this check rather than deleting it")
    assert order["reset"] < order["shared"], (
        "the button reset now comes after the shared tab rule and wipes the active underline")


# ══ the fourth download ═══════════════════════════════════════════════════════
def test_the_cover_letter_download_is_the_quiet_kind_and_starts_hidden():
    """A fourth SOLID button on that row would compete with Send, which is the one irreversible
    thing on the page — so it is `.secondary`, like the two downloads beside it. Hidden rather than
    absent because done.js decides from the generate RESPONSE: a project generated before the box
    was ticked has no letter in its result, and a button that 404s is worse than no button."""
    m = re.search(r'<button id="dl-cover"[^>]*>', DONE_PAGE, re.S)
    assert m, "the cover-letter download button is not on the Done page"
    tag = m.group(0)
    assert "download-link secondary" in tag, "the cover letter competes with Send for attention"
    assert "display:none" in tag.replace(" ", ""), "the button ships visible"
    assert "type=\"button\"" in tag, "a bare <button> in a form submits it"


def test_four_downloads_wrap_instead_of_being_crushed_into_one_line():
    """`flex: 1 1 140px`, not `1 1 0`. With three buttons a zero basis shared the row evenly; a
    fourth squeezed all of them onto one 380px line on a phone and wrapped "Cover letter" mid-word.
    A real basis lets `.fp-dl`'s own `flex-wrap` do the work — two per row, and one row on anything
    wider — rather than four unreadable columns."""
    val = _decl(DONE_PAGE, ".fp-dl .download-link", "flex")
    assert val is not None, "the download-row flex rule moved — re-derive this check"
    basis = val.split()[-1]
    assert basis not in ("0", "0px", "0%"), (
        "the download buttons still share a zero basis, so a fourth crushes all four: %r" % val)


def test_the_button_only_appears_when_there_is_a_file_behind_it():
    """TWO conditions, not one. An earlier revision of this test demanded only the response's own
    url, reasoning that `_generate` sets `cover_letter_download_url` from `cover_letter_token`,
    which only exists inside `if payload.cover_letter_enabled and want_cover_letter` -- so the url
    already means "asked for, and rendered", and a state check beside it looked like a second,
    disagreeing source of truth. That was true of the response `result` came from, but `result` is
    `state.generate_result`, which is persisted and NEVER cleared -- and `continueToDone` (the
    Proposal step's Continue) does not call /api/generate at all, so toggling the letter off and
    hitting Continue reaches this page with the OLD `result` from before the toggle. The url-only
    gate would then show a stale letter for a proposal that no longer has one queued to send.

    The fix is not the old nested `proposal_payload.cover_letter_enabled` copy (that was the
    original, different bug -- a copy only Continue ever wrote). It is the TOP-LEVEL flag
    (`coverletter-editor.js setEnabled`, also what `payloadFields()` reads), checked fresh."""
    m = re.search(r'const coverBtn = document\.getElementById\("dl-cover"\);(.*?)\n    \}\n',
                  DONE_JS, re.S)
    assert m, "the cover-letter wiring moved — re-derive this check"
    block = m.group(1)
    assert "result.cover_letter_download_url" in block, (
        "the button is no longer gated on the file the backend actually produced")
    assert "TW.getState()" in block and "cover_letter_enabled" in block, (
        "the button no longer re-checks the estimator's CURRENT choice — a stale generate_result "
        "from before a toggle-then-Continue can show or hide the wrong thing")
    assert "proposal_payload" not in block, (
        "back to the NESTED copy — that is the original bug (a copy only Continue ever writes), "
        "not the top-level flag payloadFields() actually reads")
    assert 'coverBtn.style.display = "none"' in block, "there is no else — the button never hides"


def test_the_download_helper_is_reused_and_not_forked():
    """`downloadAs` carries three things that took real incidents to get right: the bearer fetch,
    the `application/octet-stream` blob that stops Chrome's viewer swallowing the filename, and the
    re-generate-and-retry when a container restart has expired the token. A second copy pointed at
    a new url would start out identical and then not be."""
    assert DONE_JS.count("async function downloadAs") == 1, "downloadAs was forked"
    m = re.search(r'coverBtn\.addEventListener\("click",[^;]+;', DONE_JS, re.S)
    assert m, "the cover-letter button is not wired to a click"
    assert "downloadAs(" in m.group(0), "the cover letter has its own download path"
    assert "_cover_letter.docx" in m.group(0), (
        "the file would download under the same name as the proposal, or as a blob UUID")


def test_the_portal_is_told_the_proposal_has_a_letter():
    """The portal shows the letter only if it is TOLD there is one. `has_cover_letter` has been on
    `PortalPublishIn` and forwarded by /api/portal/publish since the field was added, and no real
    caller ever set it — so a customer whose bid had a letter got a portal that did not know.

    An earlier revision of this test derived the value from the GENERATE RESULT, on the reasoning
    that the question is "is there a letter in the package you just sent" and the generate response
    is the one thing that can't disagree with itself. That is true of the RESPONSE, but `result` is
    `state.generate_result` — persisted, never cleared — and `continueToDone` does not call
    /api/generate at all; it stashes a fresh `proposal_payload` and navigates straight to Done. So
    a toggle-then-Continue reaches this send with the OLD `generate_result` describing the
    PREVIOUS state of the letter, while `create_revision` (main.py) is about to pin the persisted
    `proposal_payload` — the exact blob /api/admin/cover-letter-pdf reads back later. Telling the
    portal what the generate response says, rather than what is about to be pinned, can disagree
    with the pinned snapshot in either direction.

    The correct source is `proposal_payload.cover_letter_enabled` — the same blob create_revision
    pins. Read FRESH out of TW.getState() at send time, not off the module-top `state`: this call
    site runs AFTER TW.flushState() (asserted below), which is what makes a fresh read race-free —
    the flush has just made the browser's copy and the server's copy identical."""
    m = re.search(r'TW\.postJSON\("/api/portal/publish\?draft_id=[^;]+;', DONE_JS, re.S)
    assert m, "the publish call moved — re-derive this check"
    body = m.group(0)
    assert "has_cover_letter" in body, (
        "the publish body never tells the portal about the letter — the field is a no-op again")
    assert "await TW.flushState()" in DONE_JS[max(0, m.start() - 4500):m.start()], (
        "the publish call moved ahead of the flush — a fresh TW.getState() read here would no "
        "longer be guaranteed to match what create_revision is about to pin")
    # The value, not just the key. `generate_result` / its download url would be the stale copy.
    src = re.search(r"const hasCoverLetter = [^;]+;", DONE_JS, re.S)
    assert src, "hasCoverLetter is not derived — the key may be hard-coded"
    ctx = DONE_JS[max(0, src.start() - 700):src.end()]
    assert "TW.getState()" in ctx, "hasCoverLetter is read off a snapshot rather than live state"
    assert "proposal_payload" in ctx and "cover_letter_enabled" in src.group(0), (
        "hasCoverLetter no longer follows the blob create_revision is about to pin — the portal "
        "can now disagree with the pinned snapshot in either direction")
    assert "cover_letter_download_url" not in ctx, (
        "back to the stale generate_result — continueToDone never calls /api/generate, so this "
        "can describe the state of the letter BEFORE the estimator's last toggle")


def test_the_files_page_rebuild_carries_the_letter_too():
    """"View files" regenerates from a payload it rebuilds itself. Leave the letter out of it and a
    project that had one comes back with the proposal alone — the second download disagreeing with
    the first one the estimator already checked."""
    m = re.search(r"async function viewFiles\(\)(.*?)\n  \}\n", DONE_JS, re.S)
    assert m, "viewFiles moved — re-derive this check"
    assert "TWCoverLetter.payloadFields()" in m.group(1)


# ══ how it is loaded ══════════════════════════════════════════════════════════
def test_the_editor_loads_after_the_script_it_borrows_from():
    """The letter borrows proposal-review.js's token resolver and its `idleFmtBar`, both top-level
    functions in the shared script scope. Loaded first it would find neither — and it would not
    throw, it would render raw `{{tokens}}` into a customer-facing preview and leave the ribbon
    pointing at a hidden paragraph. Every borrow is feature-detected so a thrown proposal script
    still leaves a working letter, which is exactly why the order cannot be checked at runtime."""
    assert PR_PAGE.index("coverletter-editor.js") > PR_PAGE.index("js/proposal-review.js"), (
        "coverletter-editor.js loads before proposal-review.js and will borrow nothing")
    assert DONE_PAGE.index("coverletter-editor.js") < DONE_PAGE.index("js/done.js"), (
        "done.js runs before TWCoverLetter exists, so the rebuild payload silently loses the "
        "cover-letter fields")


def test_the_editor_is_inert_on_every_other_page():
    """It is loaded on two pages and there will be more. It must do nothing at all on a page that
    has no toggle — not throw, not fetch, not write to the draft — which is what lets done.html
    load it purely for `payloadFields`."""
    m = re.search(r"function init\(\)\s*\{(.*?)\n  \}", CL_JS, re.S)
    assert m, "init moved — re-derive this check"
    assert re.search(r"if \(!toggleEl \|\| !tabsEl \|\| !surface\) return;", m.group(1)), (
        "init does not bail on a page without the cover-letter markup")


def test_a_click_on_the_error_panel_does_not_detach_itself_first():
    """`recheck` re-renders the letter on any `pointerdown`, capture-phase and document-wide,
    because the click that reveals a stale template is usually the click INTO the letter. But
    `load()` runs synchronously up to its first `await`, and it starts by calling `showLoading()`,
    which does `surface.textContent = ""` — synchronously, before anything the estimator clicked
    can fire its own handler.

    The amber error panel's own "Try again" and "Turn the cover letter off" buttons live INSIDE
    `surface`. A capture-phase `pointerdown` on either one used to run `recheck` first, which wiped
    `surface` out from under the pointer before `pointerup`. Per the UI Events spec, `click` is
    never dispatched when its target is detached between `pointerdown` and `pointerup` — so both
    buttons looked clickable and did nothing. "Turn the cover letter off" is the one that silently
    breaks worse: nothing else in the UI can flip that checkbox back off.

    There is no harness here that can drive a real pointerdown-vs-detach race under jsdom's timing
    — the same reason `pr-cover-letter.md` records two other DOM-click findings as source-scans
    rather than executed scenarios. This asserts the guard is present and reads the right flag,
    which is the same class of check already used for the DOM-order fix a few tests up."""
    m = re.search(r"const recheck = \(\) => \{[^}]+\};", CL_JS, re.S)
    assert m, "recheck moved — re-derive this check"
    assert 'surface.classList.contains("cl-error")' in m.group(0), (
        "recheck no longer checks for the error panel — a pointerdown on its own buttons will "
        "detach them before their click handlers run")
    assert re.search(r"!\s*surface\.classList\.contains\(\"cl-error\"\)", m.group(0)), (
        "the error-panel check is inverted — it should SKIP the recheck while the panel is up, "
        "not require it")


def test_no_emoji_reached_the_interface():
    """House rule, and it applies to the failure card as much as the buttons: icons are inline SVG,
    never emoji. Checked as a codepoint range rather than a list, because the list is always one
    character short."""
    emoji = re.compile("[\U0001F300-\U0001FAFF☀-➿️]")
    for name, src in (("coverletter-editor.js", CL_CODE),):
        found = emoji.findall(src)
        assert not found, "%s carries emoji in the UI: %r" % (name, found)
