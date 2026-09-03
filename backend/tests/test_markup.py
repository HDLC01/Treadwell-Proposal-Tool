"""Markup rules — the storage layer and its endpoints.

The markup chain's rates live as hardcoded constants in frontend/js/polish-bid-core.js today
(`RATES`, `GP_BANDS`, literals inside `hardBidPct`), transcribed by hand off Kyle's workbook.
`markup.py` is where an admin edits them instead. The engine that evaluates a formula and the
page that shows it are separate; these tests only pin the row.

What these tests are actually protecting:

  * **`applies=false` is not a zero.** The Gyp tabs have NO hard-bid rate — the workbook cell is
    EMPTY. "this tab has no such line" and "it has one and it prices to nothing" are different
    facts, and the chain treats them differently. Conflating them is the one mistake this table
    is shaped to prevent, so the source is mutated BOTH ways below (writer and reader) to prove
    the guard is real rather than incidental.
  * **A formula is text.** Gyp's soft-costs cell is a whole expression that returns the string
    "error" rather than guess a rate. A numeric column could not hold it, and the point of the
    text column is that it comes back byte-for-byte.
  * **The key is the TAB.** Seal, Epoxy blank and Leveling are tabs a bid sits on that no work
    type names. There is deliberately no 'combo' — a combo job is two option lines, each priced
    off its own tab — so 'combo' is refused BY NAME, not merely as an unknown value.
  * **An empty table is an empty list.** Day one has no rows and the caller falls back to its
    constants; an error there would blank the page and a typo'd layout answered with [] would
    look identical to "nothing configured yet".
  * **Writes are admin-only, reads are not.** Gated like the library's VENDORS, not its items:
    the page shows a non-admin the formulas read-only and the pricing path has to read them, so
    gating the read would stop a bid halfway through.
  * **A soft delete stays deleted.** Saving the same (layout, line_key) again must write a NEW
    row, not inherit a formula and a note somebody deliberately removed.

Runs against the in-memory Supabase fake, like test_library.py — conftest refuses to let the
suite reach the production data store.
"""
import logging
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

import main
import markup
import profiles

client = TestClient(main.app)

BACKEND = pathlib.Path(__file__).resolve().parents[1]

# Gyp's soft-costs cell, verbatim off estimate_sheet_5.7.xlsx (audited 2026-09-03). The single
# best argument for a text column, and the reason the round-trip test uses it rather than "0.16".
GYP_SOFT_COSTS = ('IF(OR(B5="Yes",B5="No"), IF(B5="Yes",.09,.1) '
                  '- IF(E69>334900,.05,IF(E69>234450,.035,0)), "error")')


@pytest.fixture()
def store(fake_supabase, monkeypatch):
    st = {"markup_rules": []}
    fake = fake_supabase(st)
    monkeypatch.setattr(markup, "get_client", lambda: fake)
    return st


@pytest.fixture()
def admin(monkeypatch):
    monkeypatch.setattr(profiles, "get_by_email",
                        lambda e: {"id": "a1", "email": e, "role": "admin"})


@pytest.fixture()
def member(monkeypatch):
    """A signed-in staff user who is NOT an admin.

    _SUPER_ADMIN_EMAIL is cleared as well as the profile role: the anti-lockout fallback matches
    on email, and with the env var set on the machine running this, tester@wetreadwell.com would
    sail through the gate and the 403 test would pass for the wrong reason."""
    monkeypatch.setattr(main, "_SUPER_ADMIN_EMAIL", "nobody@wetreadwell.com")
    monkeypatch.setattr(profiles, "get_by_email",
                        lambda e: {"id": "u1", "email": e, "role": "user"})


def _mk(**kw):
    body = {"layout": "polish", "line_key": "soft_costs", "formula": "0.16"}
    body.update(kw)
    return markup.upsert_rule(body, "hanz@wetreadwell.com")


# ── the vocabulary is closed, and 'combo' is closed out by name ───────────────
@pytest.mark.parametrize("layout", list(markup.LAYOUTS))
def test_every_tab_a_bid_can_sit_on_is_accepted(layout):
    """Five, and the three nobody would guess from a work type are the point: Seal, Epoxy blank
    and Leveling are tabs the workbook keys markup on that no work type names."""
    assert markup.validate_rule(
        {"layout": layout, "line_key": "gp", "formula": "0.3"})["layout"] == layout


@pytest.mark.parametrize("bad", ["", None, "epoxy blank", "Polish tab", "work_type", "gyp2",
                                 "'; drop table markup_rules; --"])
def test_a_layout_outside_the_five_is_refused(bad):
    with pytest.raises(markup.ValidationError) as e:
        markup.validate_rule({"layout": bad, "line_key": "gp", "formula": "0.3"})
    assert "layout" in str(e.value).lower(), str(e.value)


def test_combo_is_refused_by_name_and_says_why():
    """Not merely "unknown value". A combo job renders as two independent option lines, each
    priced off its own tab, so it has no markup of its own — and somebody WILL try to file one,
    because `combo` is a real work type everywhere else in this tool. The refusal has to send
    them to the right place rather than look like a typo."""
    with pytest.raises(markup.ValidationError) as e:
        markup.validate_rule({"layout": "combo", "line_key": "gp", "formula": "0.3"})
    msg = str(e.value)
    assert "combo" in msg.lower(), msg
    assert "own tab" in msg.lower(), "the refusal does not say where the rule should go: %s" % msg
    assert "combo" not in markup.LAYOUTS


def test_the_case_of_a_layout_is_forgiving_but_the_value_is_not():
    got = markup.validate_rule({"layout": "GYP", "line_key": "gp", "formula": "0.3"})
    assert got["layout"] == "gyp"


@pytest.mark.parametrize("line_key", list(markup.LINE_KEYS))
def test_every_line_of_the_chain_is_accepted(line_key):
    got = markup.validate_rule({"layout": "polish", "line_key": line_key, "formula": "0.1"})
    assert got["line_key"] == line_key


@pytest.mark.parametrize("bad", ["", None, "escalation", "sales_tax", "burden", "shipping"])
def test_a_line_key_outside_the_chain_is_refused(bad):
    """Escalation, burden, shipping and sales tax are all real lines on the sheet — they are just
    not markups, and a rule filed against one would never be read."""
    with pytest.raises(markup.ValidationError) as e:
        markup.validate_rule({"layout": "polish", "line_key": bad, "formula": "0.1"})
    assert "markup line" in str(e.value).lower(), str(e.value)


@pytest.mark.parametrize("line_key,fragment", [
    ("contingency", "typed per job"),
    ("remodel_tax", "county"),
])
def test_contingency_and_remodel_tax_are_refused_by_name_and_say_why(line_key, fragment):
    """These two stay IN the compounding chain (CHAIN, sort order) but are refused HERE by name,
    with a reason, the same posture as `combo` on the layout side: contingency is typed per job by
    the estimator, not a tab-wide formula; remodel tax already has its own resolution order (a typed
    percent, then the county table, then the 6.5% floor) with no separate admin formula to race it.

    Decided 2026-09-03 (AskUserQuestion): both show read-only on the Markup page.

    This is a literal, hand-authored fixture, not one derived from LINE_KEYS/CHAIN — a wrong
    definition of LINE_KEYS that still happened to exclude these two by accident would not be
    caught by re-deriving the expectation from the same constant."""
    with pytest.raises(markup.ValidationError) as e:
        markup.validate_rule({"layout": "polish", "line_key": line_key, "formula": "0.1"})
    assert fragment in str(e.value).lower(), str(e.value)


def test_contingency_and_remodel_tax_stay_in_the_compounding_chain_but_leave_the_editable_set():
    """The exclusion is from the ADMIN-EDITABLE vocabulary, not the chain itself — the money still
    compounds through both on the sheet; there is just no admin row for either."""
    assert "contingency" in markup.CHAIN
    assert "remodel_tax" in markup.CHAIN
    assert "contingency" not in markup.LINE_KEYS
    assert "remodel_tax" not in markup.LINE_KEYS
    assert len(markup.LINE_KEYS) == len(markup.CHAIN) - 2


def test_find_rule_refuses_the_two_excluded_keys_too():
    """The read path shares the write path's closed vocabulary. A lookup for a rule that can never
    exist is refused rather than answered None, which would look identical to "nobody has filed one
    yet" instead of "this can never be filed"."""
    with pytest.raises(markup.ValidationError):
        markup.find_rule("polish", "contingency")
    with pytest.raises(markup.ValidationError):
        markup.find_rule("polish", "remodel_tax")


def test_the_default_sort_is_the_order_the_chain_compounds():
    """Each line's base is the running sum ABOVE it, so the order is a price, not a preference."""
    got = [markup.validate_rule({"layout": "polish", "line_key": k, "formula": "0.1"})["sort"]
           for k in markup.LINE_KEYS]
    assert got == sorted(got), "the default sort does not follow the chain"
    assert len(set(got)) == len(markup.LINE_KEYS), "two lines default to the same position"


# ── applies=false vs formula='0' — THE distinction ────────────────────────────
def test_a_line_that_does_not_apply_stores_no_formula(store):
    """Gyp's hard-bid cell is EMPTY. Not 0 — absent."""
    row = _mk(layout="gyp", line_key="hard_bid", applies=False)
    assert row["applies"] is False
    assert row["formula"] is None, "an absent line was given a formula"
    stored = store["markup_rules"][0]
    assert stored["formula"] is None and stored["applies"] is False


def test_a_line_that_prices_to_nothing_keeps_its_zero(store):
    """Polish's bond line: B78 ships at zero, and it is a real line that really applies."""
    row = _mk(layout="polish", line_key="bond", formula="0")
    assert row["applies"] is True
    assert row["formula"] == "0", "a zero formula was thrown away"
    assert store["markup_rules"][0]["formula"] == "0"


def test_absent_and_zero_are_distinct_in_the_row_and_in_the_json(store, admin):
    """THE test. Both halves asserted, because the two ways to break this live in different
    places: the WRITER could store '0' for a line that does not apply, and the READER could
    re-derive `applies` from whether a formula is present. Either one loses Kyle's distinction
    between "this tab has no hard-bid rate" and "its hard-bid rate is nothing", and the second
    one loses it without touching the database, so a round-trip through the store cannot see it.

    Mutating the WRITER (store "0" for a line that does not apply) fails the first half. Mutating
    the READER is NOT caught here and cannot be: both rows below have `applies` agreeing with
    whether a formula is present, so `applies = formula is not None` satisfies every assertion in
    this test. The counterexample lives in
    test_a_hand_edited_row_is_served_as_stored_when_the_two_fields_disagree, which is the only
    fixture in this file where the two fields point in opposite directions."""
    absent = _mk(layout="gyp", line_key="hard_bid", applies=False)
    zero = _mk(layout="polish", line_key="hard_bid", applies=True, formula="0")

    # The stored shape.
    rows = {r["layout"]: r for r in store["markup_rules"]}
    assert rows["gyp"]["applies"] is False and rows["gyp"]["formula"] is None
    assert rows["polish"]["applies"] is True and rows["polish"]["formula"] == "0"
    assert rows["gyp"]["formula"] != rows["polish"]["formula"]
    assert rows["gyp"]["applies"] != rows["polish"]["applies"]

    # The JSON shape, straight off the endpoint the page and the pricing path both read.
    body = client.get("/api/markup/rules").json()
    served = {r["layout"]: r for r in body["rules"]}
    assert served["gyp"]["applies"] is False, "the absent line reads as applying"
    assert served["gyp"]["formula"] is None, "the absent line was served a formula"
    assert served["polish"]["applies"] is True, "the zero line reads as absent"
    assert served["polish"]["formula"] == "0", "the zero was served as %r" % (
        served["polish"]["formula"],)
    # And the two rows are not interchangeable on EITHER field, in either direction.
    assert (served["gyp"]["applies"], served["gyp"]["formula"]) \
        != (served["polish"]["applies"], served["polish"]["formula"])
    assert absent["id"] != zero["id"]


def test_a_reader_never_infers_applies_from_the_formula(store):
    """The reader-side conflation, isolated. A row stored applies=false is served applies=false
    even when the column beside it would suggest otherwise, and vice versa — because the pricing
    path decides whether to run a line off `applies`, and a formula of '0' is a line it must
    still run (it contributes nothing, which is not the same as being skipped)."""
    store["markup_rules"].append({
        "id": "r1", "layout": "polish", "line_key": "bond",
        "formula": "0", "applies": True, "sort": 60})
    store["markup_rules"].append({
        "id": "r2", "layout": "gyp", "line_key": "hard_bid",
        "formula": None, "applies": False, "sort": 10})
    served = {r["id"]: r for r in markup.list_rules()}
    assert served["r1"]["applies"] is True, "a '0' formula was read as a line that does not apply"
    assert served["r2"]["applies"] is False, "a null formula was read as a line that applies"


def test_a_hand_edited_row_is_served_as_stored_when_the_two_fields_disagree(store):
    """THE COUNTEREXAMPLE the two tests above cannot supply, and the reason this one exists.

    Every fixture in this file has `applies` AGREEING with whether a formula is present, so
    `applies = formula is not None` in _shape_rule satisfies all of them — measured, it left all
    81 tests green. An "X is never derived from Y" assertion proves nothing while no fixture can
    make X and Y disagree.

    Both shapes below are reachable and neither is a bug in this module: validate_rule cannot
    produce either, so a row like this was edited in a SQL console. markup.py's stated posture is
    to serve it AS STORED and log, rather than guess which of the two fields the person meant —
    repairing it quietly is how a rate changes without anybody deciding to change it.

    Mutation: `applies = formula is not None` in _shape_rule. Either direction fails."""
    store["markup_rules"].append({
        "id": "off-but-typed", "layout": "gyp", "line_key": "hard_bid",
        "formula": "-0.04", "applies": False, "sort": 10})
    store["markup_rules"].append({
        "id": "on-but-empty", "layout": "polish", "line_key": "bond",
        "formula": None, "applies": True, "sort": 60})

    served = {r["id"]: r for r in markup.list_rules()}
    assert served["off-but-typed"]["applies"] is False, (
        "a formula sitting on a switched-off line switched the line back on")
    assert served["off-but-typed"]["formula"] == "-0.04", (
        "the stored formula was dropped on the way out, so the row can't be seen to be wrong")
    assert served["on-but-empty"]["applies"] is True, (
        "an empty formula was read as a line that does not apply")
    assert served["on-but-empty"]["formula"] is None


def test_serving_a_contradictory_row_says_so_out_loud(store, caplog):
    """Serving it as stored is only defensible if somebody is told. The row prices a real bid and
    nothing in the editor can produce it, so the log line is the whole mechanism by which it gets
    noticed and fixed.

    Mutation: delete the log.warning call in _shape_rule."""
    store["markup_rules"].append({
        "id": "off-but-typed", "layout": "gyp", "line_key": "hard_bid",
        "formula": "-0.04", "applies": False, "sort": 10})
    with caplog.at_level(logging.WARNING, logger="markup"):
        markup.list_rules()
    said = [r.getMessage() for r in caplog.records]
    assert any("applies=false but carries a formula" in m for m in said), said
    assert any("off-but-typed" in m for m in said), (
        "the warning did not name the row, so nobody can find it: %r" % (said,))


@pytest.mark.parametrize("junk", ["maybe", "2", "null", "", {}])
def test_a_junk_applies_cell_does_not_take_the_markup_screen_down(store, junk):
    """The read path's asymmetry with the write path, and it is deliberate. `_boolean` REFUSES an
    unrecognised value while `_read_bool` falls back — because a list call that 500s over one
    hand-edited cell takes the markup screen AND the pricing read behind it down, and the rest of
    the chain was fine.

    It falls back to True, which is the safe direction: the line is shown and priced rather than
    silently skipped, and an admin can see it to fix it. A False fallback would remove a markup
    line from every job on that tab and look like nothing happened.

    Mutation: have _shape_rule call _boolean directly instead of _read_bool."""
    store["markup_rules"].append({
        "id": "r1", "layout": "polish", "line_key": "gp",
        "formula": "0.52", "applies": junk, "sort": 0})
    rows = markup.list_rules()
    assert rows[0]["applies"] is True, "a junk cell was read as a line that does not apply"
    assert rows[0]["formula"] == "0.52", "the rest of the row was lost with it"


def test_a_line_that_applies_must_carry_a_formula():
    """An empty formula on a line that applies has no defined price. Refused while the admin is
    still looking at the field, rather than stored for the chain to trip over on a live bid."""
    for blank in ("", "   ", None):
        with pytest.raises(markup.ValidationError) as e:
            markup.validate_rule({"layout": "polish", "line_key": "gp", "formula": blank})
        assert "switch it off" in str(e.value), str(e.value)


def test_switching_a_line_off_drops_the_formula_visibly(store):
    """Dropped rather than refused, so the toggle works without clearing the box by hand — and
    the returned row says so, which is the difference between visible and silent."""
    _mk(layout="polish", line_key="hard_bid", formula="-0.04")
    off = markup.upsert_rule({"layout": "polish", "line_key": "hard_bid",
                              "applies": False, "formula": "-0.04"}, None)
    assert off["applies"] is False and off["formula"] is None
    assert store["markup_rules"][0]["formula"] is None


@pytest.mark.parametrize("raw,expect", [
    (True, True), (False, False), ("true", True), ("false", False),
    ("Yes", True), ("no", False), ("on", True), ("off", False), (1, True), (0, False),
])
def test_applies_reads_the_string_a_form_actually_posts(raw, expect):
    """`bool("false")` is True. A checkbox posted as the string "false" read as True would switch
    a markup line back on for every job on that tab."""
    got = markup.validate_rule({"layout": "polish", "line_key": "gp",
                                "formula": "0.3", "applies": raw})
    assert got["applies"] is expect
    if not expect:
        assert got["formula"] is None


@pytest.mark.parametrize("bad", ["maybe", "nope!", "2", "null"])
def test_an_unrecognised_applies_is_refused_not_guessed(bad):
    with pytest.raises(markup.ValidationError) as e:
        markup.validate_rule({"layout": "polish", "line_key": "gp",
                              "formula": "0.3", "applies": bad})
    assert "yes or no" in str(e.value).lower(), str(e.value)


def test_applies_defaults_to_true_when_nobody_said():
    got = markup.validate_rule({"layout": "polish", "line_key": "gp", "formula": "0.3"})
    assert got["applies"] is True


# ── a formula is text, and comes back as typed ────────────────────────────────
def test_kyles_gyp_soft_costs_expression_round_trips_unmangled(store):
    """The single best argument for a text column. Nested IFs, an OR, doubled quotes, a
    subtraction, and a string result — Kyle's own refuse-to-price-rather-than-guess behaviour,
    which a numeric `rate` column could not hold at all."""
    row = _mk(layout="gyp", line_key="soft_costs", formula=GYP_SOFT_COSTS)
    assert row["formula"] == GYP_SOFT_COSTS
    assert markup.get_rule(row["id"])["formula"] == GYP_SOFT_COSTS
    assert '"error"' in markup.list_rules("gyp")[0]["formula"]


def test_a_formula_with_unbalanced_brackets_is_refused_and_counted():
    """The typo an expression this long actually collects. Refused with the counts, because
    "check your brackets" on a 120-character formula is not help."""
    with pytest.raises(markup.ValidationError) as e:
        markup.validate_rule({"layout": "gyp", "line_key": "soft_costs",
                              "formula": "IF(OR(B5=\"Yes\",.09,.1)"})
    assert "brackets" in str(e.value).lower(), str(e.value)


def test_a_formula_with_an_unclosed_quote_is_refused():
    with pytest.raises(markup.ValidationError) as e:
        markup.validate_rule({"layout": "gyp", "line_key": "soft_costs",
                              "formula": "IF(B5=\"Yes,.09,.1)"})
    assert "quote" in str(e.value).lower(), str(e.value)


def test_an_over_long_formula_is_refused_not_truncated():
    """The opposite of how `notes` is handled, deliberately. A clipped note is a clipped note; a
    clipped expression is a DIFFERENT expression that may still evaluate, and would price jobs
    quietly wrong."""
    long_one = "+".join(["0.01"] * 800)
    with pytest.raises(markup.ValidationError) as e:
        markup.validate_rule({"layout": "polish", "line_key": "gp", "formula": long_one})
    assert "longer than" in str(e.value).lower(), str(e.value)


def test_unknown_keys_are_ignored_not_stored():
    got = markup.validate_rule({"layout": "polish", "line_key": "gp", "formula": "0.3",
                                "rate": 0.3, "deleted_at": "now", "nonsense": 1})
    assert set(got) <= set(markup.RULE_WRITABLE), got
    assert "rate" not in got, "a numeric rate column is exactly what this table must not grow"


# ── round trip, uniqueness, and the soft delete ───────────────────────────────
def test_an_empty_table_is_an_empty_list_not_an_error(store):
    """Day one. The frontend falls back to its constants on [], so this must not raise and must
    not invent a default row the way library's reference lists do."""
    assert markup.list_rules() == []
    assert markup.list_rules("polish") == []
    r = client.get("/api/markup/rules")
    assert r.status_code == 200, r.text
    assert r.json()["rules"] == []


def test_saving_the_same_line_twice_updates_one_row(store):
    first = _mk(formula="0.16")
    second = _mk(formula="0.13")
    assert second["id"] == first["id"], "a second save made a shadow rule"
    assert len(markup.list_rules()) == 1
    assert markup.list_rules()[0]["formula"] == "0.13"


def test_the_same_line_on_two_layouts_is_two_rules(store):
    """The whole reason the key is a pair. Epoxy's soft costs is 0.13 and Polish's is 0.16."""
    a = _mk(layout="polish", formula="0.16")
    b = _mk(layout="epoxy", formula="0.13")
    assert a["id"] != b["id"]
    assert {r["layout"]: r["formula"] for r in markup.list_rules()} == {
        "polish": "0.16", "epoxy": "0.13"}


def test_a_layout_filter_returns_only_that_tab(store):
    _mk(layout="polish", formula="0.16")
    _mk(layout="gyp", line_key="soft_costs", formula=GYP_SOFT_COSTS)
    assert [r["layout"] for r in markup.list_rules("gyp")] == ["gyp"]


def test_a_soft_deleted_rule_disappears_from_the_list_but_keeps_its_row(store):
    row = _mk()
    assert markup.delete_rule(row["id"]) is True
    assert markup.list_rules() == []
    assert markup.get_rule(row["id"]) is None
    assert len(store["markup_rules"]) == 1, "the row was destroyed, not soft-deleted"
    assert store["markup_rules"][0]["deleted_at"]


def test_deleting_something_already_gone_is_false_not_a_crash(store):
    row = _mk()
    assert markup.delete_rule(row["id"]) is True
    assert markup.delete_rule(row["id"]) is False
    assert markup.delete_rule("nope") is False


def test_saving_the_same_line_after_a_delete_writes_a_new_row_not_a_resurrection(store):
    """A delete must not reserve the key, and a save must not inherit what somebody removed.
    Reviving the old row would hand the new rule the deleted formula's note and its owner — and
    on the databases, the partial unique index is what lets the new row exist beside it."""
    first = _mk(formula="0.16", notes="off Kyle's Polish tab")
    assert markup.delete_rule(first["id"]) is True
    again = markup.upsert_rule({"layout": "polish", "line_key": "soft_costs",
                                "formula": "0.19"}, "will@wetreadwell.com")
    assert again["id"] != first["id"], "the deleted rule was resurrected instead of replaced"
    assert again["notes"] == "", "the new rule inherited the deleted one's note"
    assert again["formula"] == "0.19"
    live = markup.list_rules()
    assert [r["id"] for r in live] == [again["id"]]
    assert len(store["markup_rules"]) == 2, "the deleted row stopped being a record"
    assert store["markup_rules"][0]["deleted_at"], "the old row came back to life"


def test_the_chain_comes_back_in_the_order_it_compounds(store):
    for key in reversed(markup.LINE_KEYS):
        _mk(line_key=key, formula="0.1")
    assert [r["line_key"] for r in markup.list_rules("polish")] == list(markup.LINE_KEYS)


def test_a_row_written_before_sort_existed_still_orders(store):
    """Read-shaped rather than backfilled, like library's buy_qty. A null sort falls back to the
    line's position in the chain, so the order stays the price it should be."""
    store["markup_rules"].append({"id": "r1", "layout": "polish", "line_key": "bond",
                                  "formula": "0", "applies": True, "sort": None})
    store["markup_rules"].append({"id": "r2", "layout": "polish", "line_key": "gp",
                                  "formula": "0.3", "applies": True, "sort": None})
    assert [r["line_key"] for r in markup.list_rules()] == ["gp", "bond"]


# ── endpoints, gated like VENDORS ─────────────────────────────────────────────
def test_a_non_admin_cannot_write_a_rule(store, member):
    """These rows decide what a bid sells for. Admin-only, exactly like the vendor list."""
    r = client.put("/api/markup/rules", json={"layout": "polish", "line_key": "gp",
                                              "formula": "0.99"})
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "Admin access required."
    assert store["markup_rules"] == [], "the refused write landed anyway"


def test_a_non_admin_cannot_delete_a_rule(store, member):
    row = _mk()
    r = client.delete("/api/markup/rules/" + row["id"])
    assert r.status_code == 403, r.text
    assert markup.list_rules(), "the refused delete landed anyway"


def test_a_non_admin_can_read_the_rules(store, member):
    """Reads stay open on purpose. The page shows a non-admin the formulas read-only, and the
    pricing path reads them too — a 403 here would stop a bid halfway through, which is the same
    reasoning nav_access.py records for the library's empty `api` tuple."""
    _mk(formula="0.16")
    r = client.get("/api/markup/rules")
    assert r.status_code == 200, r.text
    assert [x["formula"] for x in r.json()["rules"]] == ["0.16"]
    assert r.json()["ok"] is True


def test_the_endpoints_round_trip_for_an_admin(store, admin):
    r = client.put("/api/markup/rules", json={"layout": "gyp", "line_key": "soft_costs",
                                              "formula": GYP_SOFT_COSTS})
    assert r.status_code == 200, r.text
    rule_id = r.json()["rule"]["id"]
    assert r.json()["rule"]["formula"] == GYP_SOFT_COSTS

    r = client.get("/api/markup/rules?layout=gyp")
    assert [x["id"] for x in r.json()["rules"]] == [rule_id]

    r = client.put("/api/markup/rules", json={"layout": "gyp", "line_key": "soft_costs",
                                              "applies": "false"})
    assert r.status_code == 200 and r.json()["rule"]["applies"] is False
    assert r.json()["rule"]["formula"] is None

    r = client.delete("/api/markup/rules/" + rule_id)
    assert r.status_code == 200, r.text
    assert client.get("/api/markup/rules").json()["rules"] == []


def test_the_endpoint_carries_the_vocabulary_so_the_page_keeps_no_second_copy(store):
    body = client.get("/api/markup/rules").json()
    assert body["layouts"] == list(markup.LAYOUTS)
    assert body["line_keys"] == list(markup.LINE_KEYS)
    assert "combo" not in body["layouts"]
    # Hand-authored, not re-derived from LINE_KEYS: the editor must never be handed a key it
    # cannot actually file a rule against.
    assert "contingency" not in body["line_keys"]
    assert "remodel_tax" not in body["line_keys"]


def test_an_unknown_layout_filter_is_a_400_not_an_empty_list(store, admin):
    """The nastiest failure this API could have. [] means "nothing configured yet" and the caller
    answers it by pricing off its hardcoded constants — so a typo'd layout answered with []
    would silently bypass every rule an admin had typed for the real tab."""
    r = client.get("/api/markup/rules?layout=combo")
    assert r.status_code == 400, r.text
    assert "combo" in r.json()["detail"].lower()
    r = client.get("/api/markup/rules?layout=polsih")
    assert r.status_code == 400, r.text


def test_a_bad_payload_is_a_400_with_a_message_not_a_500(store, admin):
    r = client.put("/api/markup/rules", json={"layout": "polish", "line_key": "gp"})
    assert r.status_code == 400, r.text
    assert "switch it off" in r.json()["detail"]

    r = client.put("/api/markup/rules", json={"layout": "nope", "line_key": "gp",
                                              "formula": "0.3"})
    assert r.status_code == 400 and "layout" in r.json()["detail"].lower()


def test_deleting_a_rule_that_is_gone_is_a_404(store, admin):
    assert client.delete("/api/markup/rules/nope").status_code == 404


@pytest.mark.parametrize("payload", [
    {}, {"layout": None}, {"layout": "polish"}, {"layout": "polish", "line_key": "gp"},
    {"layout": "polish", "line_key": "gp", "formula": "0.3", "sort": "abc"},
    {"layout": "polish", "line_key": "gp", "formula": "0.3", "applies": {}},
    {"layout": ["polish"], "line_key": "gp", "formula": "0.3"},
])
def test_hostile_payloads_never_500(store, admin, payload):
    r = client.put("/api/markup/rules", json=payload)
    assert r.status_code in (200, 400, 422), (payload, r.status_code, r.text)


# ── the write gate is on the routes, not merely intended ──────────────────────
def test_the_write_routes_carry_the_admin_gate_and_the_read_does_not():
    """Derived from main.py rather than described, so it fails the day somebody adds a fourth
    route without the gate — or gates the read and breaks pricing mid-bid. The endpoint tests
    above prove the gate FIRES; this proves nobody has added a write beside it that skips it."""
    src = (BACKEND / "main.py").read_text(encoding="utf-8")
    routes = dict(re.findall(
        r'@app\.(get|put|post|patch|delete)\("(/api/markup/[^"]*)"\)', src))
    assert set(routes) >= {"get", "put", "delete"}, routes
    for verb, path in routes.items():
        i = src.index('@app.%s("%s")' % (verb, path))
        body = src[i:src.index("@app.", i + 10)]
        gated = "_require_admin(request)" in body
        assert gated == (verb != "get"), (
            "%s %s is %s" % (verb.upper(), path, "gated" if gated else "ungated"))


def test_no_nav_access_entry_claims_the_markup_routes():
    """Deliberate. /library.html carries an empty `api` tuple because its routes are read by more
    than one page and gating them would stop the Polish beta pricing halfway through a bid; the
    markup rules are read by the pricing path for the same reason. The write gate is
    _require_admin, on the routes."""
    import nav_access
    for href, tab in nav_access.TABS.items():
        for prefix in tab.get("api", ()):
            assert "markup" not in prefix, (href, prefix)


# ── both databases ────────────────────────────────────────────────────────────
def test_both_schema_files_declare_the_table_and_the_live_unique_key():
    """Prod is cloud Supabase, staging its own Postgres. A table added to one and not the other
    reads 200 and writes a bare 404 on whichever missed it — and the unique index has to be
    PARTIAL, or a soft-deleted rule would reserve its (layout, line_key) forever."""
    for path in (BACKEND / "supabase_schema.sql", BACKEND / "staging" / "schema_pg.sql"):
        sql = path.read_text(encoding="utf-8")
        assert "create table if not exists public.markup_rules" in sql, path.name
        flat = re.sub(r"\s+", " ", sql)
        assert ("create unique index if not exists markup_rules_live_key_idx "
                "on public.markup_rules (layout, line_key) where deleted_at is null") in flat, (
            "%s has no partial unique key on (layout, line_key)" % path.name)
        assert ("grant select, insert, update, delete on public.markup_rules to service_role"
                in flat), "%s: PostgREST connects as service_role; writes would all fail" % path.name
        assert "applies boolean not null default true" in flat, path.name
        # The column that must NOT exist: Gyp's soft costs is an expression, not a number.
        assert "rate numeric" not in flat, "%s grew a numeric rate column" % path.name
