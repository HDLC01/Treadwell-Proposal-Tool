"""Takeoff condition defaults — the storage layer and its two endpoints.

The three Yes/No questions the Takeoff step carries (joint filler, remove existing joint filler,
dye) used to render a "Built in" chip on the Library page's Defaults tab. Hanz, twice: "don't put
in a hard coded or built in line items", then "I told you to remove the built-in and keep and make
everything editable in the takeoff." `condition_defaults.py` is where that answer is edited now.

What these tests are actually protecting:

  * **A row is an OVERRIDE, not the answer.** What the tool SHIPS answering lives once, in
    `freshModel()` in frontend/js/polish-bid-core.js. A row here says somebody changed one key.
    So this module deliberately holds no copy of "joint filler ships on" — two statements of one
    fact is what the note above `travelSeed` records drifting within a day — and these tests pin
    that it stays that way.
  * **The vocabulary is closed and refused BY NAME.** A condition filed under a key no reader
    knows is not stored-but-unused: it saves with a green tick and changes nothing an estimator
    ever sees. Same posture `markup._check_layout` takes, for the same measured reason.
  * **A missing table reads as empty and NEVER raises.** `condition_defaults` is applied to
    neither database as of 2026-09-18. There are two readers and one of them is the ESTIMATE, so
    a raise here would stop an estimator mid-bid over a list that is legitimately empty.
  * **…but a WRITE fails loudly.** The asymmetry is the point of both. A write that quietly does
    nothing tells an admin they changed what every new bid opens with when they changed nothing,
    and they find out from a bid.
  * **"false" is not True.** A checkbox posts the STRING "false", and `bool("false")` is True —
    read that way, joint filler switches back on for every new bid.
  * **One live row per condition.** Pressing the switch twice must move the same row, not stack
    two answers whose winner is decided by whichever the reader happens to see first.
  * **Writes are admin-only, reads are not.** Gated like markup and the library's vendors: this
    decides what every new bid in the company opens holding, but the estimate has to READ it to
    seed a blank bid, and a gate on the read would stop a bid halfway through.

Runs against the in-memory Supabase fake, like test_markup.py — conftest refuses to let the suite
reach the production data store.
"""
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

import condition_defaults as cd
import main
import profiles

client = TestClient(main.app)

BACKEND = pathlib.Path(__file__).resolve().parents[1]
FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"


@pytest.fixture()
def store(fake_supabase, monkeypatch):
    st = {"condition_defaults": []}
    fake = fake_supabase(st)
    monkeypatch.setattr(cd, "get_client", lambda: fake)
    return st


@pytest.fixture()
def admin(monkeypatch):
    monkeypatch.setattr(profiles, "get_by_email",
                        lambda e: {"id": "a1", "email": e, "role": "admin"})


@pytest.fixture()
def member(monkeypatch):
    """A signed-in staff user who is NOT an admin.

    _SUPER_ADMIN_EMAIL is cleared as well as the profile role: the anti-lockout fallback matches
    on email, so without this the 403 test would pass for the wrong reason on a machine that has
    the env var set."""
    monkeypatch.setattr(main, "_SUPER_ADMIN_EMAIL", "nobody@wetreadwell.com")
    monkeypatch.setattr(profiles, "get_by_email",
                        lambda e: {"id": "u1", "email": e, "role": "user"})


# ── the vocabulary is closed ──────────────────────────────────────────────────
@pytest.mark.parametrize("key", list(cd.KEYS))
def test_every_takeoff_condition_is_accepted(key):
    assert cd.check_key(key) == key


@pytest.mark.parametrize("bad", ["", None, "taxable", "local", "reno", "joint filler",
                                 "JOINT_FILLER_2", "'; drop table condition_defaults; --"])
def test_a_key_outside_the_three_is_refused_by_name(bad):
    """Refused rather than stored, and the message NAMES the three.

    A condition filed under a key no reader knows is read by nothing, so it would save with a
    green tick and change nothing an estimator ever sees — which is strictly worse than a refusal
    somebody can act on. `taxable` and `local` are in the list on purpose: they are real condition
    keys, answered per job on the Intake step from the lead notes, and they are deliberately NOT
    settings anybody sets a company-wide default for.

    Mutation: drop the `text not in KEYS` branch from check_key. Every one of these then saves,
    and the Defaults tab never shows any of them again."""
    with pytest.raises(cd.ValidationError) as e:
        cd.check_key(bad)
    msg = str(e.value)
    assert "joint_filler" in msg, msg


def test_the_key_vocabulary_is_the_same_three_the_workbook_writes():
    """THE KEYS ARE AN AGREEMENT ACROSS TWO LANGUAGES, and a mismatch is silent in the worst way:
    the endpoint 400s a save the page makes, or worse, accepts one that reaches no cell.

    `CONDITION_CELLS` in polish-bid-core.js is what decides the workbook cell each answer writes.
    Every key this module accepts has to be in it, or the answer lands nowhere in Kyle's file.

    Mutation: add a fourth key to KEYS. Nothing in the product would say which of the two files
    was wrong."""
    core = (FRONTEND / "js" / "polish-bid-core.js").read_text(encoding="utf-8", errors="replace")
    for key in cd.KEYS:
        assert re.search(r"^\s*%s:\s*\{ cells: \[" % key, core, re.M), (
            "%s is accepted here but CONDITION_CELLS does not write it, so the answer reaches no "
            "cell in the workbook" % key)
    assert set(cd.KEYS) == {"joint_filler", "remove_existing_jf", "dye"}


def test_this_module_holds_no_copy_of_the_shipped_answer():
    """THE ONE THING THAT MUST NOT DRIFT. What a new estimate SHIPS answering lives once, in
    freshModel(). A row here is an override of one key; a second statement of the shipped answer
    in Python would be a fact in two places, and the note above `travelSeed` records exactly that
    shape of duplication drifting within a day — the migration's copy still handing out the old
    version after the seed had moved on.

    The column default is `false` in both schema files, which is not a claim about any condition:
    it is what an INSERT falls back to when no answer was given, and set_default always gives one.

    Mutation: add `SHIPPED = {"joint_filler": True, ...}` to condition_defaults.py and have
    list_defaults fill the gaps from it. The two files then disagree the first time freshModel
    changes, and the Defaults tab shows an answer no bid opens with."""
    src = (BACKEND / "condition_defaults.py").read_text(encoding="utf-8", errors="replace")
    body = src[src.index("KEYS = ("):]
    assert "joint_filler\": True" not in body and "joint_filler': True" not in body, (
        "this module states the shipped answer for joint filler; freshModel() is the one place "
        "that may")
    # No mapping of key to a shipped boolean, in either quote style.
    assert not re.search(r'["\'](?:joint_filler|dye|remove_existing_jf)["\']\s*:\s*(True|False)',
                         body), (
        "this module carries a key-to-answer map, which is the copy that drifts from freshModel")


# ── "false" is not True ───────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,expect", [
    (True, True), (False, False), (1, True), (0, False),
    ("true", True), ("yes", True), ("on", True), ("1", True),
    ("false", False), ("no", False), ("off", False), ("0", False),
    ("FALSE", False), (" No ", False),
])
def test_yes_and_no_are_read_as_written(raw, expect):
    """`bool("false")` is True, and the string "false" is the ordinary shape of this field
    arriving from a form.

    Mutation: replace `_boolean(payload.get("on"), ...)` with `bool(payload.get("on"))` in
    set_default. Every "false" the page sends switches the condition ON instead."""
    assert cd._boolean(raw, field="Default answer") is expect


@pytest.mark.parametrize("bad", ["maybe", "sometimes", "Y E S", "2.5.1"])
def test_an_answer_that_is_neither_is_refused_rather_than_guessed(bad):
    with pytest.raises(cd.ValidationError):
        cd._boolean(bad, field="Default answer")


# ── the round trip ────────────────────────────────────────────────────────────
def test_setting_an_answer_stores_it_and_reads_it_back(store):
    row = cd.set_default("joint_filler", {"on": False}, "hanz@wetreadwell.com")
    assert row["key"] == "joint_filler" and row["on"] is False
    assert row["owner_email"] == "hanz@wetreadwell.com"
    assert [r["key"] for r in cd.list_defaults()] == ["joint_filler"]
    assert cd.list_defaults()[0]["on"] is False


def test_pressing_the_switch_again_moves_the_same_row(store):
    """ONE LIVE ROW PER CONDITION. Two rows for one condition is a question about which one wins,
    and the answer to that question is what every new bid opens with.

    Mutation: make set_default always insert. The second press stores a second row, and which
    answer the Defaults tab shows depends on the order the store happens to return them in.

    `updated_by` moves and `owner_email` does not: the first press is who set it up, every press
    after it is who last changed it."""
    cd.set_default("dye", {"on": True}, "kyle@wetreadwell.com")
    cd.set_default("dye", {"on": False}, "hanz@wetreadwell.com")
    rows = cd.list_defaults()
    assert len(rows) == 1 and len(store["condition_defaults"]) == 1, (
        "the second press stored a second row for the same condition: %r" % rows)
    assert rows[0]["on"] is False
    assert rows[0]["owner_email"] == "kyle@wetreadwell.com"
    assert rows[0]["updated_by"] == "hanz@wetreadwell.com"


def test_the_three_come_back_in_the_order_the_takeoff_step_asks_them(store):
    """Sorted HERE, not trusted to the store. The Defaults tab renders them in the order this list
    arrives in, and a list whose order depends on which one an admin happened to press first reads
    as the page shuffling itself."""
    cd.set_default("dye", {"on": True}, None)
    cd.set_default("remove_existing_jf", {"on": True}, None)
    cd.set_default("joint_filler", {"on": False}, None)
    assert [r["key"] for r in cd.list_defaults()] == list(cd.KEYS)


def test_a_row_filed_under_an_unknown_key_is_not_served(store):
    """Unreachable through set_default, so such a row was hand-edited into the database. Dropped
    rather than served: it reaches no reader anyway, and putting it on the Defaults tab would give
    an admin a switch for a condition that writes to no cell.

    Mutation: drop the `if r["key"] in order` filter from list_defaults. The stranger appears on
    the tab, and pressing it 400s."""
    store["condition_defaults"].append(
        {"id": "x1", "condition_key": "reno", "on_by_default": True})
    cd.set_default("dye", {"on": True}, None)
    assert [r["key"] for r in cd.list_defaults()] == ["dye"]


def test_a_junk_answer_in_the_database_does_not_take_the_read_down(store, caplog):
    """A hand-edited row holding something that is neither yes nor no must not 500 a read the
    ESTIMATE makes mid-bid. Read as `no` and logged, which is the conservative direction: two of
    the three ship off, and the one that ships on is restored by the page's own fallback whenever
    no row is present.

    Mutation: call `_boolean` directly in _shape instead of catching. One junk row then takes down
    the Library page AND every new estimate's boot read."""
    store["condition_defaults"].append(
        {"id": "x1", "condition_key": "dye", "on_by_default": "maybe"})
    rows = cd.list_defaults()
    assert rows[0]["on"] is False


def test_a_missing_table_reads_as_nobody_having_overridden_anything(monkeypatch):
    """NEVER RAISES. `condition_defaults` is applied to neither database yet, and there are TWO
    readers — one of them is the estimate, mid-bid. `list_labor()` makes this same call for the
    Library page alone; here a raise would stop an estimator over a list that is legitimately
    empty, and the caller falls back to the shipped literals, which is what every bid does today.

    Mutation: let the exception out of list_defaults. Both the Library page and the beta estimate
    500 on boot on production, over a feature nobody there has used yet."""
    def boom():
        raise RuntimeError("PGRST205: Could not find the table 'public.condition_defaults'")
    monkeypatch.setattr(cd, "get_client", boom)
    assert cd.list_defaults() == []


def test_a_write_against_a_missing_table_fails_loudly(monkeypatch):
    """THE ASYMMETRY WITH THE READ IS THE POINT OF BOTH. A read of a table that is not there is
    honestly empty. A WRITE that quietly did nothing would tell an admin they changed what every
    new bid opens with when they changed nothing, and they would find out from a bid.

    Mutation: wrap set_default's body in the same try/except list_defaults has. Every save on
    production answers 200 and stores nothing."""
    def boom():
        raise RuntimeError("PGRST205: Could not find the table 'public.condition_defaults'")
    monkeypatch.setattr(cd, "get_client", boom)
    with pytest.raises(RuntimeError):
        cd.set_default("dye", {"on": True}, None)


# ── the endpoints ─────────────────────────────────────────────────────────────
def test_reading_the_defaults_is_open_to_any_signed_in_user(store, member):
    """Gated like markup and the library's vendors, not like an admin-only screen: the ESTIMATE
    reads this to seed a blank bid, so a gate on the read would stop an estimator halfway through.

    Mutation: add _require_admin to the GET. Every non-admin estimator's new bid then opens with
    an empty condition list — which is survivable — and a 403 in the console nobody sees."""
    cd.set_default("joint_filler", {"on": False}, None)
    r = client.get("/api/condition-defaults", headers={"X-User-Email": "kyle@wetreadwell.com"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["conditions"][0]["key"] == "joint_filler"
    assert body["conditions"][0]["on"] is False
    # The vocabulary rides along so the page does not keep a second copy of it to drift.
    assert body["keys"] == list(cd.KEYS)


def test_only_an_admin_may_change_what_every_new_bid_opens_with(store, member):
    r = client.put("/api/condition-defaults/joint_filler", json={"on": False},
                   headers={"X-User-Email": "kyle@wetreadwell.com"})
    assert r.status_code == 403, r.text
    assert store["condition_defaults"] == []


def test_an_admin_can_set_one_through_the_endpoint(store, admin):
    r = client.put("/api/condition-defaults/joint_filler", json={"on": False},
                   headers={"X-User-Email": "hanz@wetreadwell.com"})
    assert r.status_code == 200, r.text
    assert r.json()["condition"]["on"] is False
    assert len(store["condition_defaults"]) == 1


def test_a_key_the_endpoint_does_not_know_is_a_400_that_names_the_three(store, admin):
    """A 400 carrying the words, not a bare 422 and not a cheerful 200. A caller naming a
    condition nothing reads has made a mistake it can only fix if it is told which three exist.

    Mutation: catch ValidationError and return `{"ok": True}`. The page then reports a saved
    answer it did not save."""
    r = client.put("/api/condition-defaults/taxable", json={"on": True},
                   headers={"X-User-Email": "hanz@wetreadwell.com"})
    assert r.status_code == 400, r.text
    assert "joint_filler" in r.json()["detail"]
    assert store["condition_defaults"] == []


def test_the_string_false_from_a_form_is_stored_as_off(store, admin):
    """End to end, because the Pydantic model is the place this is most likely to be quietly
    'fixed': `on` is typed Any precisely so that coercing "false" to True is impossible before
    `_boolean` ever sees it.

    Mutation: type `on` as `Optional[bool]` on ConditionDefaultIn. Pydantic then hands
    `_boolean` a real True and the condition is stored ON."""
    r = client.put("/api/condition-defaults/dye", json={"on": "false"},
                   headers={"X-User-Email": "hanz@wetreadwell.com"})
    assert r.status_code == 200, r.text
    assert r.json()["condition"]["on"] is False
    assert cd.list_defaults()[0]["on"] is False


# ── the DDL is declared on BOTH databases ─────────────────────────────────────
def test_the_table_is_declared_in_both_schema_files():
    """TWO DATABASES OR IT IS BROKEN. Production is cloud Supabase; staging is a separate Postgres
    behind PostgREST. A table that exists on only one of them is how a feature looks fine on
    staging and 500s on every save in production — this repo's documented way of shipping a 502.

    Neither file has been RUN as of 2026-09-18; both are waiting on Hanz. What this pins is that
    when they are, they are run against the same table.

    Mutation: delete the block from either file."""
    for name in ("supabase_schema.sql", "staging/schema_pg.sql"):
        sql = (BACKEND / name).read_text(encoding="utf-8", errors="replace")
        # The trailing " (" is load-bearing: without it a table renamed to
        # `condition_defaults_typo` still satisfies the substring, and this test passed
        # against exactly that mutation before it was added.
        assert "create table if not exists public.condition_defaults (" in sql, name
        assert "condition_key" in sql and "on_by_default" in sql, name
        # The grant goes BESIDE the table, not in a shared block: a blanket grant only covers the
        # tables that existed when it ran, so a table added later reads fine and every write fails.
        assert "grant select, insert, update, delete on public.condition_defaults to service_role" \
            in sql, name
        # One row per condition, and PLAIN rather than partial — there is deliberately no
        # deleted_at here, because a row is one boolean in front of a constant still in the
        # source. A partial index would imply a soft delete nothing writes.
        assert "create unique index if not exists condition_defaults_key_idx" in sql, name
        start = sql.index("create table if not exists public.condition_defaults (")
        columns = sql[start:sql.index(");", start)]
        # The COLUMN list only -- the comment above it explains at length why there is
        # no deleted_at, and matching on the prose would make that explanation illegal.
        declared = [ln.strip() for ln in columns.splitlines()
                    if ln.strip() and not ln.strip().startswith("--")]
        assert not any("deleted_at" in ln for ln in declared), (
            "%s declares a deleted_at nothing writes: %r" % (name, declared))
