"""The drawer's Follow-up tab in remind mode: the task card, its email, and the reminder schedule.

Remind mode (portal, 2026-10): a follow-up that falls due is no longer emailed to the customer by
the portal. It is parked as a TASK for the ASSIGNED ESTIMATOR, and the drawer is where that person
reads the AI-drafted email, edits it, and sends it, skips it, puts it off, or says they already
rang. The schedule (next reminder, every N days, stop after N) is editable per proposal.

Everything here is EXECUTED, through drawer-render-harness.js: the real renderDetail paints the
panel, the real focusSection opens the tab (which is what fetches the draft), and the real
wireFollowup's handlers are pressed. A source read cannot say which route a button reaches with
which body, or what a 409 does to the card.

ONE DISTINCTION IS PINNED ON PURPOSE: the person who gets these reminders is the assigned estimator,
and the "Tell the team" chips on the Files page (and the per-project notification chips in this same
drawer) are a different list for a different event. The two must not share a data path.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "drawer-render-harness.js"
PORTAL_JS = (FRONTEND / "js" / "portal.js").read_text(encoding="utf-8")

XSS_TITLE = 'Re: <script>alert(1)</script> & "the slab"'
XSS_BODY = "Hi Dave &amp; team,\n<img src=x onerror=alert(1)> any news? {link}"


@pytest.fixture(scope="module")
def out():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    assert "fuTask" not in data["errors"], data["errors"].get("fuTask")
    return data


@pytest.fixture(scope="module")
def fu(out):
    return out["fuTask"]


def _decode(s: str) -> str:
    """Entity-decode what the markup carries, `&amp;` LAST, so `&amp;lt;` reads back as the four
    characters `&lt;` that were written rather than as `<`."""
    for ent, ch in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")):
        s = s.replace(ent, ch)
    return s.replace("&amp;", "&")


def _strip_tags(s: str) -> str:
    """Tags removed to a FIXED POINT: one pass over `<<b>script>` leaves a `<script>` behind."""
    while True:
        nxt = re.sub(r"<[^<>]*>", " ", s)
        if nxt == s:
            return s
        s = nxt


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", _decode(_strip_tags(html))).strip()


def _value_of(html: str, el_id: str) -> str:
    m = re.search(r'id="%s"[^>]*\svalue="([^"]*)"' % re.escape(el_id), html)
    assert m, "#%s carries no value attribute" % el_id
    return _decode(m.group(1))


def _textarea(html: str, el_id: str) -> str:
    m = re.search(r'<textarea id="%s"[^>]*>(.*?)</textarea>' % re.escape(el_id), html, re.S)
    assert m, "#%s is not a textarea in this markup" % el_id
    return _decode(m.group(1))


def _block(name: str) -> str:
    m = re.search(r"\n\s{2,6}(?:async\s+)?function " + re.escape(name) + r"\s*\(", PORTAL_JS)
    assert m, "%s() is gone from portal.js" % name
    i = PORTAL_JS.index("{", m.end())
    depth = 0
    for j in range(i, len(PORTAL_JS)):
        if PORTAL_JS[j] == "{":
            depth += 1
        elif PORTAL_JS[j] == "}":
            depth -= 1
            if depth == 0:
                return PORTAL_JS[i:j + 1]
    pytest.fail("unbalanced braces reading %s" % name)


# ── the draft ────────────────────────────────────────────────────────────────
def test_the_card_renders_with_a_loading_line_and_no_sendable_box(fu):
    d = fu["draft"]
    assert 'id="fu-task"' in d["before"]["html"]
    assert d["before"]["sendDisabled"] is True, "Send is live before there is anything to send"
    # Nothing fetched until somebody looks at the tab: the draft is a paid AI call.
    assert d["before"]["aiRequests"] == 0
    loading = d["loading"]["compose"]
    assert "Writing a first draft" in loading
    assert "<textarea" not in loading and "<input" not in loading, (
        "an empty compose box is on screen while the draft loads, which somebody could send")
    assert d["loading"]["sendDisabled"] is True


def test_the_draft_is_asked_for_once_per_task(fu):
    d = fu["draft"]
    assert d["loading"]["aiRequests"] == [
        {"path": "/api/portal/followup-task/t-1/ai-draft", "method": "POST", "body": None}]
    # A tab switch back and a repaint of a changed payload must not run the AI again.
    assert d["afterRepaint"]["aiRequests"] == 1


def test_the_draft_lands_in_the_box_and_send_comes_on(fu):
    ready = fu["draft"]["ready"]
    assert ready["sendDisabled"] is False
    assert ready["draft"]["state"] == "ready" and ready["draft"]["source"] == "ai"
    assert "Drafted by AI" in _text(ready["compose"])


def test_ai_authored_text_round_trips_escaped_and_never_executes(fu):
    """The draft is customer conversation reflected through a model: markup in it must reach the
    box as the characters it is, and an entity in it must not be decoded a second time."""
    for html in (fu["draft"]["ready"]["compose"], fu["draft"]["afterRepaint"]["html"]):
        assert _value_of(html, "fu-title") == XSS_TITLE
        assert _textarea(html, "fu-body") == XSS_BODY
        assert "<script>" not in html and "<img src=x" not in html, "AI text reached the DOM raw"


def test_the_recipient_sentence_names_exactly_the_ticked_contacts(fu):
    """"Goes to everyone ticked under Who gets chased: ..." and the ticks under it are one fact
    said twice. A contact whose row has no `followups` flag is unticked below, so the sentence must
    leave him out too, or the card names somebody the estimator can see is not being chased."""
    html = fu["who"]["html"]
    m = re.search(r"Goes to everyone ticked under Who gets chased: ([^<.]*)\.", html)
    assert m, "the recipient sentence is missing: " + _text(html)[:400]
    named = {n.strip() for n in _decode(m.group(1)).split(",")}
    ticked = set()
    for tag in re.findall(r"<input[^>]*data-fu-contact=[^>]*>", html):
        email = _decode(re.search(r'data-fu-contact="([^"]*)"', tag).group(1))
        if re.search(r"\schecked\b", tag):
            ticked.add(email)
    names = {"dave@x.com": "Dave Nunn", "ap@x.com": "Ann Boyle", "joe@x.com": "Joe Park"}
    assert ticked == {"dave@x.com"}, ticked
    assert named == {names[e] for e in ticked}, (named, ticked)


def test_a_spent_ai_budget_still_opens_a_sendable_draft_and_says_why(fu):
    rl = fu["rateLimited"]
    assert rl["sendDisabled"] is False, "a spent AI budget left nothing to send"
    assert _value_of(rl["compose"], "fu-title") == "Following up"
    text = _text(rl["compose"])
    assert "standard wording" in text and "a lot of drafts" in text
    assert "not usable" not in text, "a spent budget is not the AI failing"


def test_the_fallback_says_it_is_the_standard_wording(fu):
    assert "standard wording" in _text(fu["gone"]["compose"])
    assert "not usable" in _text(fu["gone"]["compose"])


# ── the button in the email ──────────────────────────────────────────────────
# {link} is the button to the customer's portal page. It used to be a bare word in the textarea that
# an edit could delete with no sign until Send refused. Hanz: "There should still be a button that
# leads to the portal when sending out that email so its not just an email."
OWN_LINE = ("Hi Dave,\n\nJust checking the slab plan still works for you.\n\n{link}\n\n"
            "Thanks,\nKyle")


def _preview_label(html: str) -> str:
    m = re.search(r'<span[^>]*id="fu-cta-preview"[^>]*>(.*?)</span>', html, re.S)
    assert m, "no button preview in the compose box"
    return _decode(m.group(1))


def _is_hidden(html: str, el_id: str) -> bool:
    m = re.search(r'<[a-z]+[^>]*\bid="%s"[^>]*>' % re.escape(el_id), html)
    assert m, "#%s is not rendered" % el_id
    return re.search(r"\shidden(?=[\s>])", m.group(0)) is not None


def test_a_draft_with_its_link_draws_the_real_button(fu):
    html = fu["button"]["compose"]
    assert _preview_label(html) == "Review and approve"
    tag = re.search(r'<span[^>]*id="fu-cta-preview"[^>]*>', html).group(0)
    # The drawer's own primary button, not a lookalike: the same classes Send wears.
    assert "btn" in tag.split('class="')[1].split('"')[0].split()
    assert "btn-p" in tag
    assert _value_of(html, "fu-cta") == "Review and approve"
    assert _is_hidden(html, "fu-link-ok") is False
    assert _is_hidden(html, "fu-link-gone") is True
    assert _is_hidden(html, "fu-link-many") is True
    # The message is still the AI's words, {link} included, exactly as drafted.
    assert _textarea(html, "fu-body") == OWN_LINE


def test_deleting_the_link_says_so_at_once_not_at_send(fu):
    a = fu["button"]["afterDelete"]
    assert a["gone"] is True and a["ok"] is False and a["many"] is False
    assert "Your portal link was removed" in a["goneText"]
    assert a["fixLabel"] == "Add the portal link back"


def test_send_still_refuses_a_message_with_no_link(fu):
    i = fu["button"]["ignored"]
    assert i["sends"] == 0
    assert i["alert"]["err"] is True and "{link}" in i["alert"]["text"]
    assert "Add the portal link back" in i["alert"]["text"]
    assert i["still"]["gone"] is True


def test_the_fix_puts_the_link_back_where_it_was_and_send_goes(fu):
    f = fu["button"]["fixed"]
    assert f["value"] == OWN_LINE, "the fix moved the button or changed the wording"
    assert f["draft"] == OWN_LINE
    assert f["link"]["gone"] is False and f["link"]["ok"] is True
    assert f["focused"] == "#fu-body"
    assert f["alert"]["text"] == "", "the stale Send refusal stayed up after the fix"
    sent = fu["button"]["sent"]
    assert len(sent) == 1
    assert sent[0]["body"]["body"] == OWN_LINE
    assert sent[0]["body"]["body"].count("{link}") == 1


def test_the_link_twice_is_refused_with_its_own_sentence(fu):
    t = fu["button"]["twice"]
    assert t["many"] is True and t["gone"] is False and t["ok"] is False
    r = fu["button"]["twiceRefused"]
    assert r["sends"] == 0 and r["alert"]["err"] is True and "once" in r["alert"]["text"]


def test_the_button_label_is_editable_and_is_what_gets_sent(fu):
    r = fu["button"]["relabelled"]
    assert r["preview"] == "See the price" and r["draftCta"] == "See the price"
    assert fu["button"]["sent"][0]["body"] == {"title": "Checking in", "body": OWN_LINE,
                                               "cta": "See the price"}


def test_the_button_label_round_trips_escaped(fu):
    c = fu["ctaEscape"]
    xss = '<script>alert(1)</script> &amp; "go"'
    assert _preview_label(c["compose"]) == xss
    assert _value_of(c["compose"], "fu-cta") == xss
    assert "<script>" not in c["compose"], "an AI-written button label reached the DOM raw"
    # An empty label is the portal's default, and the preview says so.
    assert c["emptyPreview"] == "View your proposal"
    # Typed text is shown as text: written through textContent, never innerHTML.
    assert c["typedPreview"] == "Tom &amp; <b>Jerry</b>"
    assert c["previewWroteHtml"] is False
    assert c["sent"][0]["body"]["cta"] == "Tom &amp; <b>Jerry</b>"


def test_an_inline_link_is_flagged_as_not_the_button(fu):
    """The portal draws the red button only for a paragraph that is {link} alone; inside a
    sentence it becomes a plain underlined link. The AI fixture writes it inline."""
    text = _text(fu["draft"]["ready"]["compose"])
    assert "inside a sentence" in text and "line of its own" in text


def test_a_blank_page_offers_the_link_without_saying_it_was_removed(fu):
    b = fu["blankLink"]
    assert _is_hidden(b["compose"], "fu-link-gone") is False
    assert "removed" not in b["before"]["goneText"]
    assert b["before"]["fixLabel"] == "Add the portal link"
    assert b["value"] == "Any news on the pour?\n\n{link}"
    assert b["after"]["ok"] is True and b["after"]["gone"] is False


def test_every_id_the_compose_wiring_reaches_for_is_rendered_by_it():
    wanted = set()
    for fn in ("wireFuCompose", "paintFuLink", "fuLinkBack"):
        wanted |= set(re.findall(r'\$\("(fu-[a-z-]+)"\)', _block(fn)))
    assert {"fu-cta", "fu-cta-preview", "fu-link-fix", "fu-link-gone"} <= wanted
    compose = _block("followupComposeHtml") + _block("followupTaskHtml")
    for i in sorted(wanted):
        assert 'id="%s"' % i in compose, "#%s is wired but never rendered" % i


# ── the four decisions ───────────────────────────────────────────────────────
def test_send_posts_the_edited_words_and_takes_the_card_away(fu):
    s = fu["send"]
    assert s["requests"] == [{"path": "/api/portal/followup-task/t-1/send", "method": "POST",
                              "body": {"title": "Edited subject", "body": "Edited body {link}",
                                       "cta": "Open your proposal"}}]
    assert s["rowTask"] is None and 'id="fu-task"' not in s["html"]
    assert s["draftAfter"] is None


def test_warnings_on_a_200_are_a_soft_notice_not_an_error(fu):
    html = fu["send"]["html"]
    m = re.search(r'<p class="note fu-notice([^"]*)"[^>]*>(.*?)</p>', html, re.S)
    assert m, "no notice after sending"
    assert "is-warn" in m.group(1)
    assert "Sent." in m.group(2) and "not in the History" in m.group(2)
    assert "Failed" not in _text(html)


def test_skip_called_and_snooze_reach_their_own_routes(fu):
    assert fu["skip"]["requests"] == [
        {"path": "/api/portal/followup-task/t-2/skip", "method": "POST", "body": {}}]
    assert "Skipped. Nothing was sent." in _text(fu["skip"]["html"])
    assert fu["called"]["requests"] == [
        {"path": "/api/portal/followup-task/t-3/called", "method": "POST",
         "body": {"kind": "text", "note": "Spoke Friday"}}]
    # TW.bizToday() is 2026-08-13 in the harness: "In a week" is the 20th.
    assert fu["snoozeQuick"]["requests"] == [
        {"path": "/api/portal/followup-task/t-4/snooze", "method": "POST",
         "body": {"until": "2026-08-20"}}]
    assert fu["snoozePicked"]["requests"][0]["body"] == {"until": "2026-09-01"}


def test_a_snooze_moves_the_schedule_it_shows(fu):
    assert fu["snoozeQuick"]["plan"]["next_at"] == "2026-08-20"
    assert fu["snoozeQuick"]["plan"]["interval_days"] == 5, "the snooze rewrote the rest of the plan"
    assert "Snoozed until" in _text(fu["snoozeQuick"]["html"])


def test_a_past_snooze_date_never_leaves_the_page(fu):
    p = fu["snoozePast"]
    assert p["requests"] == []
    assert p["alert"] == {"text": "Pick a date after today.", "err": True}
    assert p["stillThere"] is True


# ── when the task is gone from under you ─────────────────────────────────────
def test_a_409_is_a_plain_sentence_and_the_card_goes(fu):
    g = fu["gone"]
    assert len(g["requests"]) == 1
    text = _text(g["html"])
    assert "moved on" in text and "nothing was sent" in text
    assert "Failed" not in text, "a 409 read as a generic failure"
    assert 'id="fu-task"' not in g["html"] and g["rowTask"] is None
    assert "Somebody already dealt with this reminder" in _text(fu["decided"]["html"])
    assert fu["decided"]["rowTask"] is None


def test_a_failed_send_keeps_the_card_and_says_it_is_safe_to_retry(fu):
    f = fu["sendFailed"]
    assert f["alert"]["err"] is True and "safe to try again" in f["alert"]["text"]
    assert f["disabled"] is False and f["label"] != "Working…"
    assert f["stillThere"] is True and f["rowTask"]["id"] == "t-9"


def test_no_draft_offers_a_retry_or_a_blank_page_and_send_guards_the_email(fu):
    n = fu["noDraft"]
    assert 'id="fu-draft-retry"' in n["failedCompose"] and 'id="fu-draft-blank"' in n["failedCompose"]
    assert "<textarea" not in n["failedCompose"]
    assert n["sendWhileFailed"] is True
    assert n["aiAfterRetry"] == 2, "Try again did not ask again"
    # The blank page is genuinely blank, the caret is in it, and Send is now on.
    assert _value_of(n["blankCompose"], "fu-title") == ""
    assert _textarea(n["blankCompose"], "fu-body") == ""
    assert n["focusAfterBlank"] == "#fu-title"
    assert n["blankSendDisabled"] is False
    assert n["alertEmpty"] == {"text": "Write a subject and a message first.", "err": True}
    assert "{link}" in n["alertNoLink"]["text"] and n["alertNoLink"]["err"] is True
    assert n["sends"] == 0


def test_somebody_elses_send_in_flight_is_not_pressable(fu):
    s = fu["sending"]
    assert "Sending now" in _text(s["html"])
    assert s["sendDisabled"] is True and s["skipDisabled"] is True
    assert s["aiRequests"] == 0


def test_escape_closes_the_open_disclosure_and_stops_there(fu):
    for box, r in fu["escape"].items():
        assert r["open"] is False, box
        assert r["stopped"] is True and r["prevented"] is True, (
            "Escape fell through to the drawer and closed the project: %s" % box)
        assert r["focused"] == r["wantFocus"], box
        # Already closed: left for the drawer's own Escape.
        assert r["closedStopped"] is False, box


# ── the schedule ─────────────────────────────────────────────────────────────
def test_the_schedule_shows_the_plan(fu):
    html = fu["schedule"]["html"]
    assert _value_of(html, "fu-next") == "2026-10-27"
    assert _value_of(html, "fu-every") == "5"
    assert _value_of(html, "fu-stop") == "", "a default stop count rendered as a number"
    assert 'id="fu-task"' not in html, "a task card without a task"


def test_the_schedule_saves_one_field_on_change_and_never_per_keystroke(fu):
    s = fu["schedule"]
    assert s["typed"]["bodies"] == [], "a keystroke saved"
    assert s["every"]["bodies"] == [{"interval_days": 7}]
    assert s["every"]["paths"] == ["/api/portal/proposal/futask/followup-plan"]
    assert s["every"]["msg"] == "Saved."
    assert s["planAfter"]["interval_days"] == 7, "the board row did not take the saved plan"
    assert s["cleared"]["bodies"] == [{"interval_days": None}]
    assert s["cleared"]["msg"] == "Back on the default."
    assert s["stop"]["bodies"] == [{"stop_after": 3}]
    assert s["next"]["bodies"] == [{"next_at": "2026-08-20"}]
    assert s["repaintedBySave"] is False, "a save repainted the drawer and took the caret with it"


def test_the_schedule_refuses_bad_values_before_a_round_trip(fu):
    s = fu["schedule"]
    for k in ("tooBig", "fraction", "pastNext"):
        assert s[k]["bodies"] == [] and s[k]["err"] is True, k
    assert s["refused"]["err"] is True
    assert s["refused"]["msg"] == "Not saved: That interval is not allowed."


def test_a_closed_lost_proposal_has_no_schedule(out):
    assert 'id="fu-sched"' not in out["scenarios"]["bare"]["html"]
    for name in ("approved", "sent"):
        assert 'id="fu-sched"' in out["scenarios"][name]["html"], name
        assert 'id="fu-task"' not in out["scenarios"][name]["html"], name


def test_every_class_the_task_card_emits_is_styled(fu):
    css = (FRONTEND / "portal.html").read_text(encoding="utf-8")
    css = css[css.index("<style>"):css.index("</style>")]
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    auth = re.sub(r"/\*.*?\*/", "", (FRONTEND / "auth.js").read_text(encoding="utf-8"), flags=re.S)
    defined = set(re.findall(r"\.(-?[_a-zA-Z][\w-]*)", css + auth))
    html = (fu["draft"]["before"]["html"] + fu["draft"]["ready"]["compose"]
            + fu["noDraft"]["failedCompose"] + fu["send"]["html"] + fu["schedule"]["html"])
    emitted = {c for g in re.findall(r'class="([^"]*)"', html) for c in g.split() if c}
    assert not sorted(emitted - defined), sorted(emitted - defined)


# ── the assigned estimator is NOT the "Tell the team" list ───────────────────
def test_no_follow_up_action_touches_the_notification_lists(fu):
    """Every request every task button and every schedule save made, executed."""
    paths = fu["allPaths"]
    assert any("/followup-task/" in p for p in paths) and any("/followup-plan" in p for p in paths)
    assert not [p for p in paths if "notify" in p], paths


def test_the_follow_up_code_and_the_notification_code_share_nothing():
    """Two lists, two meanings. The follow-up reminders go to the ASSIGNED ESTIMATOR (one person,
    the "Assigned to" picker, posted to /assign). The notification chips in this drawer and the
    "Tell the team" chips on the Files page decide who hears about replies, approvals and a send.
    Neither side of this file may read the other's list."""
    fu_fns = ("followupTaskHtml", "followupScheduleHtml", "followupComposeHtml", "wireFuCompose",
              "paintFuCompose", "loadFuDraft", "fuTaskAct", "fuSettle", "saveFuPlan")
    for fn in fu_fns:
        body = _block(fn)
        for word in ("notify", "nt-chip", "NT_CACHE", "notify_picks", "Tell the team"):
            assert word not in body, "%s() reaches into the notification list (%s)" % (fn, word)
    for fn in ("loadNotifyChips", "paintNtChips"):
        body = _block(fn)
        assert "followup" not in body.lower(), "%s() reaches into the follow-up schedule" % fn
    # The recipient of the reminders is changed by the Assigned to picker, and only there.
    wire = _block("wireFollowup")
    assert 'path("/assign")' in wire and "notify" not in wire
    # And the schedule tells the estimator who that is.
    sched = _block("followupScheduleHtml")
    assert "assigned estimator" in sched and "Assigned to" in sched


def test_the_backend_follow_up_routes_do_not_read_the_notification_roster():
    src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    start = src.index("# ── follow-up TASKS")
    end = src.index('@app.get("/api/admin/health")')
    block = src[start:end]
    assert "notify" not in block.lower().replace("tell the team", ""), (
        "a follow-up task route reads the notification roster")


def test_the_files_page_keeps_the_estimator_and_the_team_list_apart():
    """On the send page the assigned estimator is its own select and the Tell the team chips are
    their own strip; the estimator is read from the select alone."""
    html = (FRONTEND / "done.html").read_text(encoding="utf-8")
    assert 'id="portal-estimator"' in html and 'id="notify-pick-chips"' in html
    done = (FRONTEND / "js" / "done.js").read_text(encoding="utf-8")
    m = re.search(r"const readAssignedEstimator = \(\) =>\s*\n?\s*(.*?);", done, re.S)
    assert m and "portal-estimator" in m.group(1) and "notify" not in m.group(1)
