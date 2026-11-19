"""BD's page helpers in frontend/bd/js/bd-shared.js (window.BD), run in node (#806: BD's
test_shared_helpers_js, moved with the file).

bd-shared.js is loaded the way test_bd_normalize.py loads it: a bare `vm` context (`ctx.window = ctx`,
no document, no storage, no matchMedia), which is itself the proof that the file touches the DOM
only inside function bodies. Every date helper takes `today` as an argument (on a page, the `today`
of /api/bd/me) and never reads a clock.
"""
from __future__ import annotations

import json
import pathlib
import tempfile

import pytest

from _bd_pages import SHARED_JS
from _node import last_json_line, require_node, run_node


RUNNER = """
const fs = require("fs"), vm = require("vm");
const ctx = {}; ctx.window = ctx; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
const calls = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const out = calls.map(([name, args]) => {
  try {
    const fn = name.split(".").reduce((o, k) => o[k], ctx.BD);
    return { ok: fn.apply(ctx.BD, args) };
  } catch (e) { return { error: String(e) }; }
});
console.log(JSON.stringify(out));
"""

TODAY = "2026-11-04"


def call(*calls):
    """Run BD.<name>(*args) for each (name, args) in one node process; returns the results."""
    require_node()
    with tempfile.TemporaryDirectory() as tmp:
        js = pathlib.Path(tmp) / "run.js"
        data = pathlib.Path(tmp) / "calls.json"
        js.write_text(RUNNER, encoding="utf-8")
        data.write_text(json.dumps([[n, list(a)] for n, a in calls]), encoding="utf-8")
        proc = run_node(js, SHARED_JS, data)
    assert proc.returncode == 0, proc.stderr[-3000:]
    res = last_json_line(proc.stdout)
    errors = [r["error"] for r in res if "error" in r]
    assert not errors, errors
    return [r["ok"] for r in res]


def one(name, *args):
    return call((name, args))[0]


def plus_days(n):
    import datetime
    return (datetime.date(2026, 11, 4) + datetime.timedelta(days=n)).isoformat()


@pytest.mark.parametrize("days,want", [
    (0, "today"), (1, "tomorrow"), (2, "in 2 days"), (6, "in 6 days"), (7, "in a week"), (13, "in a week"),
    (14, "in 2 weeks"), (20, "in 2 weeks"), (21, "in 3 weeks"), (29, "in 3 weeks"), (30, "in about a month"),
    (44, "in about a month"), (45, "about a month"), (105, "about 3 months"), (364, "about 11 months"),
    (365, "about a year"), (730, "about 2 years"), (-3, ""),
])
def test_fmt_rel(days, want):
    assert one("fmtRel", plus_days(days), TODAY) == want


def test_fmt_day_shows_the_year_only_across_a_year_boundary():
    assert call(("fmtDay", ["2026-11-09", TODAY]), ("fmtDay", ["2027-01-11", TODAY]),
                ("fmtDay", ["2026-11-09T23:30:00-06:00", TODAY])) == \
        ["Mon, Nov 9", "Mon, Jan 11, 2027", "Mon, Nov 9"]


def test_chip_dates():
    assert call(("chipDate", ["week", TODAY]), ("chipDate", ["month", TODAY]), ("chipDate", ["3months", TODAY]),
                ("chipDate", ["month", "2027-01-31"]), ("chipDate", ["month", "2028-01-31"]),
                ("chipDate", ["3months", "2026-11-30"])) == \
        ["2026-11-11", "2026-12-04", "2027-02-04", "2027-02-28", "2028-02-29", "2027-02-28"]


def test_weeks_left():
    assert call(("weeksLeft", [TODAY]), ("weeksLeft", ["2026-12-31"]), ("weeksLeft", ["2027-01-01"])) == [8, 1, 52]


def test_pace_words_on_the_mocks_week_pace():
    # docs/api-contract.md, WeekView.pace: 61 done, 75.9 due by today, 90 a year.
    p = one("paceWords", {"completed": 61, "required_to_date": 75.9, "target_total": 90}, TODAY)
    assert p["pct"] == 68 and p["delta"] == -15 and p["dueToday"] == 76 and p["state"] == "behind"
    assert p["short"] == "15 behind"
    assert p["sentence"] == "15 behind. About 2 extra calls a week catches up."
    assert p["caption"] == "61 of 90 this year · 8 weeks left"


def test_pace_words_ahead_on_and_the_half_up_rule():
    ahead, on, half, empty = call(
        ("paceWords", [{"completed": 84, "required_to_date": 76, "target_total": 90}, TODAY]),
        ("paceWords", [{"completed": 76, "required_to_date": 76.2, "target_total": 90}, TODAY]),
        ("paceWords", [{"completed": 61, "required_to_date": 75.5, "target_total": 90}, TODAY]),
        ("paceWords", [{"completed": 0, "required_to_date": 0, "target_total": 0}, TODAY]))
    assert (ahead["state"], ahead["short"], ahead["sentence"]) == ("ahead", "8 ahead", "8 ahead. Nice work.")
    assert (on["state"], on["short"], on["sentence"]) == ("on", "On pace", "Right on pace.")
    assert half["delta"] == -14, "the contract rounds half up: -14.5 -> -14"
    assert empty["pct"] == 0 and empty["state"] == "on"


def test_one_extra_call_is_singular():
    p = one("paceWords", {"completed": 70, "required_to_date": 72, "target_total": 90}, TODAY)
    assert p["sentence"] == "2 behind. About 1 extra call a week catches up."


@pytest.mark.parametrize("iso,want", [
    ("2026-11-04T11:59:00-06:00", "Good morning"), ("2026-11-04T12:00:00-06:00", "Good afternoon"),
    ("2026-11-04T16:59:00-06:00", "Good afternoon"), ("2026-11-04T17:00:00-06:00", "Good evening"),
])
def test_greeting(iso, want):
    assert one("greeting", iso) == want


def test_status_pill_precedence():
    dup, nc, key, key_reason, maint, none = call(
        ("statusPill", [{"duplicate_of": {"contact_id": 3}, "confirmed": False, "importance": 3}, []]),
        ("statusPill", [{"confirmed": False, "importance": 3, "category": "maintenance"}, []]),
        ("statusPill", [{"importance": 3, "category": "maintenance"}, []]),
        ("statusPill", [{"importance": 1}, ["Key account."]]),
        ("statusPill", [{"category": "maintenance"}, []]),
        ("statusPill", [{"category": "bd", "confirmed": True}, []]))
    assert "pill-warn" in dup and "Possible duplicate" in dup
    assert "pill-warn" in nc and "Needs confirming" in nc
    assert "pill-info" in key and "Key account" in key and "Key account" in key_reason
    assert "pill-neutral" in maint and "Maintenance" in maint
    assert none == ""


def test_status_pill_for_a_pinned_task_drops_only_the_neutral_maintenance_pill():
    dup, nc, key, maint, plain = call(
        ("statusPill", [{"duplicate_of": {"contact_id": 3}, "category": "maintenance"}, [], True]),
        ("statusPill", [{"confirmed": False, "category": "maintenance"}, [], True]),
        ("statusPill", [{"importance": 3, "category": "maintenance"}, [], True]),
        ("statusPill", [{"category": "maintenance"}, [], True]),
        ("statusPill", [{"category": "maintenance"}, [], False]))
    assert "Possible duplicate" in dup and "Needs confirming" in nc and "Key account" in key
    assert maint == "", "the neutral pill would repeat Maintenance . due"
    assert "pill-neutral" in plain


def test_kind_pill_and_first_reason():
    fu, new, reason, none = call(
        ("kindPill", [{"kind": "followup"}]), ("kindPill", [{"kind": "new"}]),
        ("firstReason", [{"reasons": ["Key account", "Needs confirming the person", "Promised a call by Fri, Nov 6."]}]),
        ("firstReason", [{"reasons": ["Key account"]}]))
    assert "pill-outline" in fu and "Follow-up" in fu and "New" in new
    assert reason == "Promised a call by Fri, Nov 6"
    assert none == ""


def test_tint_plural_count_duration_tel():
    t1, t2, t3, p1, p2, c, d1, d2, d3, tel, tel2 = call(
        ("tintOf", ["Marcus Ebner"]), ("tintOf", ["marcus ebner"]), ("tintOf", ["Victor Almeida"]),
        ("plural", [1, "call"]), ("plural", [1234, "call"]), ("fmtCount", [1234567]),
        ("fmtDuration", [360]), ("fmtDuration", [95]), ("fmtDuration", [45]),
        ("telHref", [{"phone": "816.555.0102"}]), ("telHref", ["(913) 555-0117"]))
    assert t1 == t2 and 1 <= t1 <= 5 and 1 <= t3 <= 5
    assert (p1, p2, c) == ("1 call", "1,234 calls", "1,234,567")
    assert (d1, d2, d3) == ("6 min", "1 min 35 s", "45 s")
    assert (tel, tel2) == ("tel:+18165550102", "tel:+19135550117")


def test_avatar_escapes_its_text_and_hides_from_screen_readers():
    html = one("avatarHTML", "<b>Bo</b> X", "sm", "done")
    assert "<b>" not in html and "&lt;" in html
    assert 'aria-hidden="true"' in html and "avatar avatar-sm" in html and "avatar-badge" in html
    assert 'data-tint="' in html


def test_initials_leave_out_titles_and_suffixes():
    got = call(("initialsOf", ["Dr. Ian Pruitt"]), ("initialsOf", ["Dana Whitfield"]),
               ("initialsOf", ["avery@example.com"]), ("initialsOf", ["Ray Duchene Jr."]),
               ("initialsOf", ["Mrs Ana de la Cruz"]), ("initialsOf", ["Dr."]), ("initialsOf", [""]),
               ("initialsOf", ["Drew Penn"]))
    assert got == ["IP", "DW", "A", "RD", "AC", "D", "", "DP"]
    # the avatar shows the same letters
    assert ">IP<" in one("avatarHTML", "Dr. Ian Pruitt").replace(" ", "")


def test_pill_is_shared_and_escapes_its_text():
    ok, plain = call(("pill", ["ok", "Added to BD", "check"]), ("pill", ["neutral", "<i>x</i>"]))
    assert ok.startswith('<span class="pill pill-ok">') and "Added to BD" in ok
    assert plain == '<span class="pill pill-neutral">&lt;i&gt;x&lt;/i&gt;</span>'


def test_store_without_storage_reads_null_and_never_throws():
    got, wrote = call(("store.get", ["x"]), ("store.set", ["x", 1]))
    assert got is None and wrote is False
