"""Filing a project as test/demo by hand, so it leaves the Active list.

Hanz, looking at production: *"Can the projects at test not appear in active tab?"*

The Projects page already kept test projects out of Active / Inactive / All. What it could not
do is recognise them: `isTest()` was a name regex, so on the real prod list "Test Will 7/29"
and "Lock Test" were filed correctly while anything the regex missed sat in Active pretending
to be a customer bid. Widening the regex is the wrong lever in a construction tool — "demo"
lives inside "demolition", and a misfiled real bid is worse than a visible test one. So the
estimator files it by hand and the name stays a fallback for legacy rows.

The behaviour these tests exist to pin:

  * **`False` is not the same as absent.** Absent means nobody has said, so the name heuristic
    still gets a vote. `False` means somebody looked and said "real bid", and it has to BEAT
    the heuristic — otherwise un-filing a project called "Test Treadwell" would bounce it
    straight back into the Test tab on the next repaint, and there would be no way out.
  * The flag survives a rename, which is the whole reason it is a flag.
  * Legacy rows keep working: no flag, name decides, exactly as before.

Runs entirely against the in-memory Supabase fake (`fake_supabase` in conftest), like
test_archive.py and test_assign_draft.py. Not a style preference: the first version of this
file used the real client, and because `backend/.env` points SUPABASE_URL at the live cloud
project, it created and deleted rows in the PRODUCTION drafts table and left fake `events` on
the History page. conftest now refuses to run against that host at all.
"""
import uuid

import pytest

import drafts
import main
from main import app
from fastapi.testclient import TestClient

client = TestClient(app)

REAL_NAME = "Cedar Ridge Distribution Center"


@pytest.fixture()
def store(fake_supabase, monkeypatch):
    """One saved project, plus the fake wired into both drafts.py and the API layer."""
    st = {"drafts": [
        {"id": "p1", "data": {"project_name": REAL_NAME}, "owner_email": "u@x.com",
         "created_at": "2026-08-01", "updated_at": "2026-08-02", "deleted_at": None},
    ], "events": []}
    fake = fake_supabase(st)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    return st


def _row(store, pid="p1"):
    return next(r for r in store["drafts"] if r["id"] == pid)


def _blob(store, pid="p1"):
    return _row(store, pid)["data"]


def _summary(store, pid="p1"):
    """The card fields as the list builder produces them.

    Goes through `drafts._summary` (the full-blob path) rather than `list_drafts`, because the
    in-memory fake does not emulate PostgREST's `alias:data->>key` projection — the same reason
    test_archive.py tests `_summary` directly."""
    return drafts._summary(_row(store, pid))


# ── the data layer ────────────────────────────────────────────────────
def test_a_new_project_has_no_opinion_recorded(store):
    """Absent, not False. Coercing it to False would tell the page "confirmed real bid" about
    every legacy row and switch the name fallback off for the whole list."""
    assert _summary(store)["is_test"] is None


def test_filing_a_project_as_test_sticks(store):
    assert drafts.set_test_flag("p1", True) is True
    assert _blob(store)["is_test"] is True
    assert _summary(store)["is_test"] is True


def test_un_filing_writes_an_explicit_false_not_an_absence(store):
    """THE one that matters. `False` has to be recorded, because it is what outvotes the name
    heuristic for a project genuinely called "Test …"."""
    drafts.set_test_flag("p1", True)
    drafts.set_test_flag("p1", False)
    assert _blob(store)["is_test"] is False, "un-filing lost the decision"
    assert _summary(store)["is_test"] is False


def test_filing_does_not_reorder_the_projects_list(store):
    """Same posture as archive and assign: filing a project isn't work on the estimate, so it
    must not bump updated_at and shuffle it to the top of a date-sorted list."""
    before = _blob(store) and next(r for r in store["drafts"] if r["id"] == "p1")["updated_at"]
    drafts.set_test_flag("p1", True)
    assert next(r for r in store["drafts"] if r["id"] == "p1")["updated_at"] == before


def test_filing_leaves_the_rest_of_the_blob_alone(store):
    """Read-modify-write, not replace. The blob holds every edited grid cell."""
    _blob(store)["epoxy_sf"] = "1000"
    drafts.set_test_flag("p1", True)
    assert _blob(store)["epoxy_sf"] == "1000"
    assert _blob(store)["project_name"] == REAL_NAME


def test_filing_does_not_touch_the_archived_flag(store):
    drafts.set_archived("p1", True)
    drafts.set_test_flag("p1", True)
    row = _summary(store)
    assert row["archived"] is True and row["is_test"] is True


def test_filing_an_unknown_project_reports_that_it_did_not_exist(store):
    assert drafts.set_test_flag(str(uuid.uuid4()), True) is False


def test_the_flag_is_logged_so_history_can_show_who_filed_it(store):
    """History is how somebody later asks "who decided this wasn't a real bid"."""
    drafts.set_test_flag("p1", True, "hanz@wetreadwell.com")
    drafts.set_test_flag("p1", False, "hanz@wetreadwell.com")
    actions = [(e["action"], e["actor_email"]) for e in store["events"]]
    assert ("marked_test", "hanz@wetreadwell.com") in actions
    assert ("marked_real", "hanz@wetreadwell.com") in actions


# ── the tri-state coercion ────────────────────────────────────────────
@pytest.mark.parametrize("raw,expect", [
    (True, True), (False, False),
    ("true", True), ("false", False), ("t", True), ("f", False),
    ("1", True), ("0", False), ("yes", True), ("no", False),
    (None, None), ("null", None), ("", None), ("maybe", None),
])
def test_the_flag_is_read_as_three_states_not_two(raw, expect):
    """PostgREST hands back `data->>is_test` as TEXT, so "false" arrives as a string. Reading
    it with the existing `_truthy` would map both "false" and absent to False and destroy the
    distinction the page depends on."""
    assert drafts._tribool(raw) is expect


def test_archived_still_reads_as_a_plain_bool():
    """`archived` genuinely has two states — absent means active. The new tri-state helper must
    not have changed it."""
    assert drafts._truthy(None) is False
    assert drafts._truthy("true") is True


# ── the endpoint ──────────────────────────────────────────────────────
def test_the_endpoint_files_and_un_files(store):
    r = client.post("/api/draft/p1/test", json={"is_test": True})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True and r.json()["is_test"] is True
    assert _blob(store)["is_test"] is True

    r = client.post("/api/draft/p1/test", json={"is_test": False})
    assert r.status_code == 200, r.text
    assert _blob(store)["is_test"] is False


def test_the_endpoint_defaults_to_filing_as_test(store):
    r = client.post("/api/draft/p1/test", json={})
    assert r.status_code == 200, r.text
    assert _blob(store)["is_test"] is True


def test_a_bad_body_is_refused_rather_than_500(store):
    r = client.post("/api/draft/p1/test", json={"is_test": "banana"})
    assert r.status_code in (200, 422), r.text
    assert r.status_code != 500


def test_filing_an_unknown_id_is_not_an_error(store):
    """Mirrors the archive endpoint: a stale card in somebody's open tab reports
    `existed: false` rather than throwing."""
    r = client.post("/api/draft/%s/test" % uuid.uuid4(), json={"is_test": True})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True and r.json()["existed"] is False


# ── the page's own classifier, and the two call sites that must agree ──
def test_the_page_lets_the_flag_win_in_both_directions():
    """`isTest` in projects.js is the shipped predicate. Both branches matter: a flagged real
    bid must escape the Test tab even when its name says otherwise, and a flagged test must be
    filed even when its name looks like a customer."""
    import pathlib
    import re
    src = (pathlib.Path(__file__).resolve().parents[2]
           / "frontend" / "js" / "projects.js").read_text(encoding="utf-8")
    body = re.search(r"function isTest\(p\) \{(.*?)\n    \}", src, re.S)
    assert body, "isTest() moved or was renamed"
    inner = body.group(1)
    assert 'typeof p.is_test === "boolean"' in inner, (
        "the flag is not consulted as a boolean, so an explicit `false` cannot outvote the name")
    assert "return p.is_test" in inner, "the flag's value is not returned directly"
    assert "nameLooksLikeTest" in inner, "the name heuristic is no longer the fallback"


def test_the_grid_and_the_chip_counts_use_one_filter():
    """They were filtered by two separate `!isTest(p)` expressions, which let a tab's number
    disagree with what the tab actually showed."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[2]
           / "frontend" / "js" / "projects.js").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.split("\n") if not l.strip().startswith("//"))
    assert code.count("function realOnly(") == 1
    assert code.count("realOnly(") >= 3, "applyFilter and renderChips should both call it"
    # Exactly one — inside realOnly itself. A second occurrence means somebody hand-rolled
    # the filter again somewhere else, which is how the counts and the grid drifted before.
    assert code.count("filter(p => !isTest(p))") == 1, (
        "a second hand-rolled test filter is back; counts and grid can drift again")
    assert "function realOnly(list) { return list.filter(p => !isTest(p)); }" in code


def test_the_test_button_is_rendered_in_both_views():
    """Cards AND the table. A project misfiled by the heuristic is only reachable from the tab
    it was wrongly put in, so the way out has to exist in whichever view is open."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[2]
           / "frontend" / "js" / "projects.js").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.split("\n") if not l.strip().startswith("//"))
    assert code.count("${testBtn(p)}") == 2, "expected the button in the card and the table row"
    assert 'class="test-btn' in code


# ── an open tab must not erase what the server owns ───────────────────────────
# From the adversarial audit. The browser PUTs the whole `data` blob on every autosave, so a tab
# that loaded before somebody pressed "Mark as test" silently dropped the flag on its next save.
# `_tribool` reads the absence as "nobody has said", the name heuristic regains its vote, and a
# real bid named something like "Demo Only - Bldg C" disappears from Active with no explanation.
def test_an_autosave_from_a_stale_tab_keeps_the_test_flag(store):
    drafts.save_draft("p1", {"project_name": "Demo Only - Bldg C"})
    drafts.set_test_flag("p1", True)
    # A tab that loaded BEFORE the flag was set now autosaves its own view of the world.
    drafts.save_draft("p1", {"project_name": "Demo Only - Bldg C", "sqft": 2875})
    assert _blob(store).get("is_test") is True, (
        "the flag was erased, so this project silently returns to the Active tab")


def test_a_stale_tab_cannot_re_hide_a_project_marked_real(store):
    """The direction that actually loses work: False means "somebody looked and said this is a
    real bid", and it must beat the name heuristic. Dropping it re-hides a live customer bid."""
    drafts.save_draft("p2", {"project_name": "Test Treadwell"})
    drafts.set_test_flag("p2", False)
    drafts.save_draft("p2", {"project_name": "Test Treadwell", "sqft": 100})
    data = _blob(store, "p2")
    assert "is_test" in data and data["is_test"] is False, (
        "False was treated as unset, so the name heuristic hides a real bid again")


def test_archived_and_the_assigned_estimator_survive_the_same_way(store):
    """Same blob, same exposure. `archived` has had it since long before the test flag."""
    drafts.save_draft("p3", {"project_name": "Westport"})
    drafts.set_archived("p3", True)
    drafts.set_assigned_estimator("p3", "kyle@wetreadwell.com")
    drafts.save_draft("p3", {"project_name": "Westport", "sqft": 1})
    data = _blob(store, "p3")
    assert data.get("archived") is True
    assert data.get("assigned_estimator") == "kyle@wetreadwell.com"


def test_a_caller_that_MEANS_to_change_a_server_key_still_can(store):
    """Preserving must not become freezing — set_test_flag itself writes through save paths."""
    drafts.save_draft("p4", {"project_name": "X"})
    drafts.set_test_flag("p4", True)
    drafts.save_draft("p4", {"project_name": "X", "is_test": False})
    assert _blob(store, "p4")["is_test"] is False



# ── ...nor put back what the CRM changed ──────────────────────────────────────
# Review of fix 4, round 2. The carry-forward above only covers a blob that LEAVES a key out, and a
# browser's blob never does: a hydrate writes the server's copy into it, so it carries whatever that
# browser last read. A tab that read the project before Troy reassigned it to RJ and filed it as a
# test put Kyle's name and "real bid" back with its next save — and the Files page's door makes
# that save with nobody watching. The browser's save (PUT /api/draft/{id}) now keeps the stored
# values; the server's own writers (set_* above, the generate write-back) are unchanged.
def test_a_browser_save_cannot_put_back_what_the_crm_changed(store):
    """Mutation: drop `keep_server_owned=True` from api_save_draft — all three are reverted."""
    drafts.save_draft("p5", {"project_name": "Westport"})
    drafts.set_assigned_estimator("p5", "rj@wetreadwell.com")
    drafts.set_test_flag("p5", True)
    drafts.set_archived("p5", True)
    r = client.put("/api/draft/p5", json={"data": {
        "project_name": "Westport", "sqft": 2,
        "assigned_estimator": "kyle@wetreadwell.com", "is_test": False, "archived": False}})
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    data = _blob(store, "p5")
    assert data["sqft"] == 2, "the save itself did not land"
    assert data["assigned_estimator"] == "rj@wetreadwell.com"
    assert data["is_test"] is True
    assert data["archived"] is True


def test_a_browser_save_still_seeds_a_key_the_project_never_had(store):
    """The counterexample: a key the stored row has never had is the blob's to give — on a first
    save (an insert) and on a later one. Without this the test above passes for a save that
    drops every server-owned key.

    Mutation: pop the server-owned keys from the blob whenever the row exists — p6's
    assigned_estimator is gone."""
    r = client.put("/api/draft/p6", json={"data": {"project_name": "New", "is_test": True}})
    assert r.status_code == 200, r.text
    assert _blob(store, "p6")["is_test"] is True
    r = client.put("/api/draft/p6", json={"data": {"project_name": "New", "is_test": True,
                                                  "assigned_estimator": "kyle@wetreadwell.com"}})
    assert r.status_code == 200, r.text
    assert _blob(store, "p6")["assigned_estimator"] == "kyle@wetreadwell.com"
