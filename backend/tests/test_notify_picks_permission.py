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


def test_an_admin_is_not_charged_for_a_permission_read(route, monkeypatch):
    """The stored picks are read ONLY to authorise. An admin needs no delta, so the read must not
    happen at all — and if it did and threw, an admin's save would 502 for no reason."""
    post, state = route
    state["admin"] = True

    def boom(pid):
        raise RuntimeError("should not be called for an admin")
    monkeypatch.setattr(main.drafts, "get_notify_picks", boom)
    assert post(add=[OTHER], mute=[]).status_code == 200


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
