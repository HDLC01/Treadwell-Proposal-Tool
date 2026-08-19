"""Who may change who hears about a project.

`POST /api/draft/{id}/notify` shipped without the check its sibling has. The per-project override
route (`api_portal_notify_overrides_set`, main.py) has always enforced "an admin may toggle anyone; a
non-admin may only toggle their own address" — and the draft route, which reaches the same override
table by a different door, enforced nothing.

WHY IT MATTERS, concretely. An `add` is not cosmetic: the portal's notify_team then emails that
address the proposal-sent and approval notifications, project name and customer detail included. So
any signed-in staff member could route a customer's proposal activity to an arbitrary outside address
on any project, with no admin involved and nothing on screen to show it.

WHY THE CHECK IS A DELTA, not "every address must be mine". This route and its two controls submit
the WHOLE set of deviations, not one toggle. A flat rule would refuse a non-admin on any project
where an admin had already muted somebody — the legitimate case — which would have made the control
useless rather than safe. So the rule is: every address whose membership CHANGED must be the caller's
own.
"""
import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

ME = "kylene@wetreadwell.com"
OTHER = "kyle@wetreadwell.com"
OUTSIDE = "attacker@gmail.com"


@pytest.fixture
def route(monkeypatch):
    """The draft notify route with the store stubbed. `admin` and `prior` are per-test knobs."""
    state = {"admin": False, "prior": {"add": [], "mute": []}, "written": []}
    monkeypatch.setattr(main, "_user_email", lambda request: ME)
    monkeypatch.setattr(main, "_caller_is_admin", lambda request: state["admin"])
    monkeypatch.setattr(main.drafts, "get_notify_picks", lambda pid: dict(state["prior"]))
    monkeypatch.setattr(main.drafts, "set_notify_picks",
                        lambda pid, add, mute, actor: (
                            state["written"].append({"add": list(add), "mute": list(mute)}), True)[1])
    # Never sent, so the route returns before any portal round-trip.
    monkeypatch.setattr(main.drafts, "latest_revision_no", lambda pid: 0)

    def post(**body):
        return client.post("/api/draft/d-1/notify", json=body)

    return post, state


# ── a non-admin ──────────────────────────────────────────────────────────────
def test_a_non_admin_may_change_their_own(route):
    post, state = route
    r = post(add=[ME], mute=[])
    assert r.status_code == 200, r.text
    assert state["written"] == [{"add": [ME], "mute": []}]


def test_a_non_admin_may_mute_themselves(route):
    post, state = route
    r = post(add=[], mute=[ME])
    assert r.status_code == 200, r.text
    assert state["written"][0]["mute"] == [ME]


def test_a_non_admin_cannot_add_a_colleague(route):
    post, state = route
    r = post(add=[OTHER], mute=[])
    assert r.status_code == 403, r.text
    assert state["written"] == [], "it wrote a pick the caller was not allowed to make"


def test_a_non_admin_cannot_add_an_outside_address(route):
    """THE one. This is how a customer's proposal activity would reach a personal inbox."""
    post, state = route
    r = post(add=[OUTSIDE], mute=[])
    assert r.status_code == 403
    assert state["written"] == []


def test_a_non_admin_cannot_mute_a_colleague(route):
    """Muting is as damaging as adding, in the other direction: the person who should have been told
    about a send quietly stops being told, and nothing says so."""
    post, state = route
    r = post(add=[], mute=[OTHER])
    assert r.status_code == 403
    assert state["written"] == []


def test_smuggling_a_colleague_alongside_their_own_change_is_refused(route):
    """The obvious bypass: make a legitimate self-change and ride somebody else along with it."""
    post, state = route
    r = post(add=[ME, OUTSIDE], mute=[])
    assert r.status_code == 403
    assert state["written"] == []


def test_case_and_padding_do_not_get_round_the_check(route):
    post, state = route
    for value in ("KYLE@WETREADWELL.COM", "  kyle@wetreadwell.com  ", "Kyle@WeTreadwell.com"):
        r = post(add=[value], mute=[])
        assert r.status_code == 403, "%r got through" % value
    assert state["written"] == []


@pytest.mark.parametrize("mine", ["KYLENE@WETREADWELL.COM", "Kylene@WeTreadwell.com",
                                  "  kylene@wetreadwell.com  "])
def test_your_own_address_is_recognised_whatever_its_casing(route, mine):
    """The direction the test above does NOT cover, and the one the normalisation is actually for.
    `_clean_portal_emails` trims but deliberately KEEPS the caller's casing, and the roster may hold
    a different one — so without folding case here a non-admin would be refused permission to toggle
    their OWN chip. That is a false refusal, not a bypass, which is why the refusal-side test passes
    with or without the fold and this one does not.

    Mutation: drop `.lower()` from the comparison. Only this test fails."""
    post, state = route
    r = post(add=[mine], mute=[])
    assert r.status_code == 200, r.text
    assert state["written"], "the caller was refused permission to change their own notification"


# ── the delta, which is what keeps the control usable ────────────────────────
def test_an_untouched_colleague_entry_is_carried_through_not_refused(route):
    """An admin muted Troy on this project. A non-admin now adds themselves, and the payload still
    carries Troy's mute because the control submits the whole set. That must SUCCEED — refusing it is
    what a naive "every address must be mine" rule would do, and it would make the chips unusable on
    exactly the projects that have overrides.

    Mutation: replace the delta with a flat membership test. Only this test and the next fail."""
    post, state = route
    state["prior"] = {"add": [], "mute": [OTHER]}
    r = post(add=[ME], mute=[OTHER])
    assert r.status_code == 200, r.text
    assert state["written"] == [{"add": [ME], "mute": [OTHER]}]


def test_removing_a_colleagues_existing_entry_is_still_refused(route):
    """The other side of the delta: carrying an entry through is fine, DROPPING somebody else's is a
    change and must be refused. Without this, a non-admin could un-mute anyone by omission."""
    post, state = route
    state["prior"] = {"add": [], "mute": [OTHER]}
    r = post(add=[], mute=[])
    assert r.status_code == 403
    assert state["written"] == []


def test_resubmitting_the_stored_set_unchanged_is_allowed(route):
    """Idempotent save: the drawer repaints and re-posts what is already there. No change, no
    permission needed."""
    post, state = route
    state["prior"] = {"add": [OTHER], "mute": []}
    r = post(add=[OTHER], mute=[])
    assert r.status_code == 200, r.text


def test_moving_a_colleague_between_add_and_mute_is_refused(route):
    """Two changes at once, and neither is the caller's."""
    post, state = route
    state["prior"] = {"add": [OTHER], "mute": []}
    r = post(add=[], mute=[OTHER])
    assert r.status_code == 403


# ── an admin ─────────────────────────────────────────────────────────────────
def test_an_admin_may_change_anyone(route):
    post, state = route
    state["admin"] = True
    r = post(add=[OTHER, OUTSIDE], mute=[ME])
    assert r.status_code == 200, r.text
    assert state["written"] == [{"add": [OTHER, OUTSIDE], "mute": [ME]}]


def test_the_stored_picks_are_read_for_an_admin_too(route, monkeypatch):
    """An earlier version of this test asserted the opposite — that an admin skips the read, because
    the read existed only to authorise. That stopped being true when the reconcile loop started
    needing the project's OWNER from the same row in order to spare them from its clearing pass, and
    the loop runs for admins as much as anyone. So the read is unconditional now, deliberately, and
    this pins that rather than the old claim.

    Mutation: put the read back behind `if not _caller_is_admin(request)`. The owner exclusion then
    applies to nobody who actually uses the control, and test_the_owner_is_never_cleared fails."""
    post, state = route
    state["admin"] = True
    seen = []
    real = main.drafts.get_notify_picks
    monkeypatch.setattr(main.drafts, "get_notify_picks",
                        lambda pid: (seen.append(pid), real(pid))[1])
    assert post(add=[OTHER], mute=[]).status_code == 200
    assert seen == ["d-1"], "the owner is no longer read, so the reconcile loop cannot spare them"


# ── failing closed ───────────────────────────────────────────────────────────
def test_an_unreadable_prior_set_refuses_rather_than_guesses(route, monkeypatch):
    """Without the stored set there is no delta, so there is no way to tell an allowed change from a
    forbidden one. Failing OPEN here would turn a database blip into the hole this whole file exists
    to close."""
    post, state = route

    def boom(pid):
        raise RuntimeError("postgrest down")
    monkeypatch.setattr(main.drafts, "get_notify_picks", boom)
    r = post(add=[ME], mute=[])
    assert r.status_code == 502, r.text
    assert state["written"] == []


def test_a_caller_with_no_identity_cannot_change_anybody(route, monkeypatch):
    """`_user_email` returning nothing must not make every address "not mine, therefore fine" — or,
    worse, match an empty entry."""
    post, state = route
    monkeypatch.setattr(main, "_user_email", lambda request: None)
    assert post(add=[OTHER], mute=[]).status_code == 403
    assert post(add=[ME], mute=[]).status_code == 403
    assert state["written"] == []


def test_clearing_everything_when_only_your_own_was_set_is_allowed(route):
    post, state = route
    state["prior"] = {"add": [ME], "mute": []}
    r = post(add=[], mute=[])
    assert r.status_code == 200, r.text
    assert state["written"] == [{"add": [], "mute": []}]


# ── the two controls must not offer what the server refuses ──────────────────
def test_both_pickers_gate_their_chips_on_the_same_rule():
    """A chip that 403s is a worse bug than a chip that is plainly read-only. Both new controls read
    the role off TWAuth the way notifications.js does, and render a non-toggleable person as a span
    rather than a disabled button."""
    import pathlib
    fe = pathlib.Path(main.__file__).resolve().parents[1] / "frontend"
    for name in ("js/done.js", "js/portal.js"):
        js = (fe / name).read_text(encoding="utf-8")
        assert 'role === "admin"' in js and 'role === "super_admin"' in js, (
            "%s does not read the caller's role, so it cannot gate the chips" % name)
        assert "mayToggle" in js, "%s has no per-chip permission decision" % name
        assert "nt-chip-ro" in js, "%s renders no read-only chip state" % name
    # And the read-only chip has to be styled, or it renders as an unstyled pill.
    for page in ("done.html", "portal.html"):
        assert "span.nt-chip" in (fe / page).read_text(encoding="utf-8"), (
            "%s does not style the read-only chip" % page)


def test_the_drawers_click_wiring_skips_the_read_only_chips():
    """paintNotSentNotify's read-only chips are spans that carry the SAME `nt-chip` class. Wiring the
    click on `.nt-chip` would attach a handler to them and let a non-admin fire a request the server
    refuses — a 403 toast instead of a control that simply does not invite the click."""
    import pathlib
    js = (pathlib.Path(main.__file__).resolve().parents[1]
          / "frontend" / "js" / "portal.js").read_text(encoding="utf-8")
    body = js[js.index("function paintNotSentNotify("):]
    body = body[:body.index("\n  /** The estimator picker")]
    assert 'querySelectorAll(".nt-chip")' not in body, (
        "the not-sent picker still wires clicks by class, which now matches its read-only spans")
    assert 'querySelectorAll("[data-ns-notify]")' in body


# ── the LIVE path: the picks travel in the publish body ──────────────────────
# The gate went on /api/draft/{id}/notify first, and that was the secondary door. The Files screen
# sends its choices with the PUBLISH, because portal_notify_overrides.proposal_id has a foreign key
# onto a row that does not exist until that request creates it. So the route people actually use to
# tell the portal who hears about a send was still ungated after the "fix". Both call one helper now.
PUBLISH = "/api/portal/publish?draft_id=d1"


@pytest.fixture
def publish(monkeypatch):
    state = {"admin": False, "prior": {}, "body": {}}

    def fake_portal(path, method="GET", body=None):
        state["body"] = body or {}
        return {"ok": True, "token": "t", "url": "u"}

    monkeypatch.setattr(main, "_portal", fake_portal)
    monkeypatch.setattr(main, "_user_email", lambda request: ME)
    monkeypatch.setattr(main, "_caller_is_admin", lambda request: state["admin"])
    monkeypatch.setattr(main.drafts, "load_draft",
                        lambda pid: {"data": {"notify_picks": dict(state["prior"])},
                                     "owner_email": "rj@wetreadwell.com"})
    monkeypatch.setattr(main.drafts, "create_revision", lambda *a, **k: 1)
    monkeypatch.setattr(main.drafts, "delete_revision", lambda *a, **k: None)
    monkeypatch.setattr(main.drafts, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: None)

    def go(**body):
        # The route requires an estimator before it looks at anything else, so every call carries one
        # — otherwise these tests would pass on a 400 that has nothing to do with permissions.
        body.setdefault("assigned_estimator", OTHER)
        return client.post(PUBLISH, json=body)

    return go, state


def test_a_non_admin_cannot_smuggle_an_outside_address_into_a_real_send(publish):
    """THE hole the first fix missed. This is a send: the portal applies these picks to the override
    table and then emails everyone it resolves. An outside address added here receives the
    proposal-sent notification for a real customer's job."""
    go, state = publish
    r = go(notify_add=[OUTSIDE])
    assert r.status_code == 403, r.text
    assert "notify_add" not in state["body"], "the pick was forwarded to the portal anyway"


def test_a_non_admin_cannot_mute_the_team_on_a_real_send(publish):
    go, state = publish
    r = go(notify_mute=[OTHER])
    assert r.status_code == 403
    assert "notify_mute" not in state["body"]


def test_a_non_admin_may_still_change_their_own_on_a_send(publish):
    go, state = publish
    r = go(notify_add=[ME])
    assert r.status_code == 200, r.text
    assert state["body"]["notify_add"] == [ME]


def test_an_admin_may_pick_anyone_on_a_send(publish):
    go, state = publish
    state["admin"] = True
    r = go(notify_add=[OTHER, OUTSIDE], notify_mute=[ME])
    assert r.status_code == 200, r.text
    assert state["body"]["notify_add"] == [OTHER, OUTSIDE]


def test_an_untouched_send_needs_no_permission_at_all(publish):
    """A send that carries no picks must not be gated — every estimator sends proposals, and most
    never touch the control. Checked because the guard is only called when something was picked."""
    go, state = publish
    r = go(assigned_estimator=OTHER)
    assert r.status_code == 200, r.text
    assert "notify_add" not in state["body"] and "notify_mute" not in state["body"]


def test_a_send_that_carries_the_stored_picks_unchanged_is_allowed(publish):
    """The Files chips are seeded from the draft's stored picks, so a non-admin who opens the screen
    and presses Send forwards exactly what is already there. That is a no-op change and must pass, or
    a non-admin could not send a proposal on any project with an override on it."""
    go, state = publish
    state["prior"] = {"add": [OTHER], "mute": []}
    r = go(notify_add=[OTHER])
    assert r.status_code == 200, r.text
    assert state["body"]["notify_add"] == [OTHER]


def test_both_doors_share_one_check():
    """A rule enforced in two places drifts. The publish path and the draft route must both reach
    _guard_notify_picks — if either grows its own copy, this is the test that says so."""
    import inspect
    import re
    src = inspect.getsource(main)
    assert src.count("def _guard_notify_picks(") == 1, "the guard has been duplicated"
    # CALLS only — `def _guard_notify_picks(request, ...` matches a naive substring count too, which
    # is why the first version of this test read 3 and looked like a duplicate.
    calls = re.findall(r"^\s+_guard_notify_picks\(request", src, re.M)
    assert len(calls) == 2, (
        "expected exactly two call sites (the publish path and the draft route); found %d. A third "
        "door into the override table needs the same guard, not its own copy." % len(calls))


# ── the reconcile loop must not strip the estimate's author ──────────────────
def test_the_owner_is_never_cleared(route, monkeypatch):
    """The publish path forwards `created_by`, and the portal records the estimate's author as a
    recipient on purpose — Will, via Hanz, 2026-08-13: the estimator who built it should hear back.
    The portal's own clearing loop spares them. Without the same exclusion here, one save from this
    drawer strips an override the portal deliberately set, and the person who built the estimate
    quietly stops hearing about their own job.

    Mutation: clear against `chosen` instead of `spared`. Only this test fails."""
    post, state = route
    state["admin"] = True
    owner = "rj@wetreadwell.com"
    monkeypatch.setattr(main.drafts, "get_notify_picks",
                        lambda pid: {"add": [], "mute": [], "owner_email": owner})
    monkeypatch.setattr(main.drafts, "latest_revision_no", lambda pid: 3)   # sent, so it reconciles
    cleared = []

    def fake_portal(path, method="GET", body=None):
        if method == "GET":
            return {"overrides": [{"email": owner}, {"email": "troy@wetreadwell.com"}]}
        if (body or {}).get("mode") == "clear":
            cleared.append(body["email"])
        return {"ok": True}
    monkeypatch.setattr(main, "_portal", fake_portal)

    r = post(add=[ME], mute=[])
    assert r.status_code == 200, r.text
    assert owner not in cleared, "the estimate's author was stripped from their own job"
    assert "troy@wetreadwell.com" in cleared, (
        "nothing was cleared at all, so this proves nothing about the exclusion")
