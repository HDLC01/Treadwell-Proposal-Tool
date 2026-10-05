"""The Labor Calculator's per-line modes (Kyle's notes B7b, Hanz 2026-10-05).

Each default labor line gets a mode -- FROM SF (crew + production rate, days = ceil(SF / rate)) or
FIXED (guys + days), at 8 or 10 hours a day. This file holds the server half and the pure
arithmetic; the screens are EXECUTED in labor-calculator-harness.js (the Library tab and Try-it
box) and polish-estimate-harness.js (a new bid filling its rows, the "Default value" warnings).

THE TABLE MAY NOT EXIST (backend/ops/labor_calc.sql is applied by hand on two databases), so the
read answers [] rather than 500ing and the estimate opens exactly as it did before. A write must NOT
degrade the same way.
"""
import json
import pathlib
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

import library
import main
import profiles

client = TestClient(main.app)
REPO = pathlib.Path(__file__).resolve().parents[2]
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture()
def store(fake_supabase, monkeypatch):
    st = {"library_labor_calc": []}
    fake = fake_supabase(st)
    monkeypatch.setattr(library, "get_client", lambda: fake)
    return st


@pytest.fixture()
def as_admin(monkeypatch):
    monkeypatch.setattr(profiles, "get_by_email",
                        lambda e: {"id": "a1", "email": e, "role": "admin"})


@pytest.fixture()
def as_user(monkeypatch):
    monkeypatch.setattr(main, "_SUPER_ADMIN_EMAIL", "somebody-else@wetreadwell.com")
    monkeypatch.setattr(profiles, "get_by_email",
                        lambda e: {"id": "u1", "email": e, "role": "user"})


class _Gone(Exception):
    pass


class _NoTableClient:
    def table(self, name):
        raise _Gone("relation does not exist")


def test_an_absent_table_reads_as_no_modes_not_a_500(monkeypatch):
    """Mutation: drop the try/except in list_labor_calc -- this becomes a 500 on every box where the
    DDL has not run, and the estimate would not open."""
    monkeypatch.setattr(library, "get_client", lambda: _NoTableClient())
    r = client.get("/api/library/labor-calc")
    assert r.status_code == 200 and r.json() == {"ok": True, "calc": []}


def test_a_write_does_not_degrade_when_the_table_is_absent(monkeypatch):
    monkeypatch.setattr(library, "get_client", lambda: _NoTableClient())
    with pytest.raises(_Gone):
        library.save_labor_calc("polishing", {"mode": "fixed", "guys": 2, "days": 1})


def test_a_sf_mode_round_trips_and_is_read_back_shaped(store):
    row = library.save_labor_calc("polishing", {"mode": "sf", "crew": "3", "sf_per_day": "2,500",
                                                "hours_per_day": 10})
    assert row == {"line_id": "polishing", "mode": "sf", "crew": 3.0, "sf_per_day": 2500.0,
                   "hours_per_day": 10, "guys": None, "days": None, "rate": None}
    assert library.list_labor_calc() == [row]
    # saving again REPLACES the one row (no second row for the line) and can change the mode
    again = library.save_labor_calc("polishing", {"mode": "fixed", "guys": 2, "days": 1.5,
                                                  "rate": "$41"})
    assert again["mode"] == "fixed" and again["guys"] == 2.0 and again["rate"] == 41.0
    assert again["crew"] is None and again["sf_per_day"] is None
    assert len(store["library_labor_calc"]) == 1


def test_an_empty_mode_clears_the_line(store):
    library.save_labor_calc("mockup", {"mode": "fixed", "guys": 3, "days": 0.5})
    assert library.save_labor_calc("mockup", {"mode": "none"}) is None
    assert library.list_labor_calc() == []
    assert library.save_labor_calc("mockup", {"mode": ""}) is None    # clearing nothing is fine


@pytest.mark.parametrize("payload,fragment", [
    ({"mode": "weekly"}, "neither"),
    ({"mode": "sf", "sf_per_day": 2500}, "crew"),
    ({"mode": "sf", "crew": 3}, "square feet"),
    ({"mode": "sf", "crew": 3, "sf_per_day": 0}, "square feet"),
    ({"mode": "fixed", "days": 2}, "guys"),
    ({"mode": "fixed", "guys": 2}, "days"),
    ({"mode": "fixed", "guys": 2, "days": 1, "hours_per_day": 9}, "8 or 10"),
    ({"mode": "fixed", "guys": -2, "days": 1}, "negative"),
    ({"mode": "fixed", "guys": "abc", "days": 1}, "number"),
])
def test_an_incomplete_or_silly_mode_is_refused_in_words(store, payload, fragment):
    with pytest.raises(library.ValidationError) as e:
        library.save_labor_calc("polishing", payload)
    assert fragment in str(e.value)
    assert store["library_labor_calc"] == []


def test_the_routes_gate_the_write_to_admins_and_leave_the_read_open(store, as_user):
    assert client.get("/api/library/labor-calc").status_code == 200
    r = client.put("/api/library/labor-calc/polishing", json={"mode": "fixed", "guys": 2, "days": 1})
    assert r.status_code == 403
    assert store["library_labor_calc"] == []


def test_the_put_route_saves_and_refuses_with_a_400_in_words(store, as_admin):
    ok = client.put("/api/library/labor-calc/jointfill",
                    json={"mode": "sf", "crew": 3, "sf_per_day": 3000, "hours_per_day": 8})
    assert ok.status_code == 200 and ok.json()["row"]["line_id"] == "jointfill"
    bad = client.put("/api/library/labor-calc/jointfill", json={"mode": "sf", "crew": 3})
    assert bad.status_code == 400 and "square feet" in bad.json()["detail"]
    got = client.get("/api/library/labor-calc").json()["calc"]
    assert [g["line_id"] for g in got] == ["jointfill"]


# ── the one arithmetic both screens use ──────────────────────────────────────────────────────────
def _core(expr):
    script = ("const B=require(%s);console.log(JSON.stringify(%s))"
              % (json.dumps(str(REPO / "frontend" / "js" / "polish-bid-core.js")), expr))
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8",
                         timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@needs_node
def test_hostile_row_keys_never_reach_a_prototype():
    """Saved drafts and library rows are user data, so their KEYS are too. A row carrying
    "__proto__" / "constructor" / "prototype" must not pollute Object.prototype through any row
    copy, must not carry those keys into the copy, and every ordinary key must survive unchanged.

    Mutation: drop the guard in copyInto and `polluted` comes back 1 (JSON.parse makes "__proto__"
    an own key, and the old `copy[k] = r[k]` then re-points the copy's prototype)."""
    expr = """(function(){
      var hostile = JSON.parse('{"id":"x","label":"L","unit":"sf","rate":"50","days":"2","guys":"2",' +
        '"__proto__":{"polluted":1},"constructor":{"prototype":{"polluted":1}},"prototype":"p"}');
      var seen = [];
      seen.push(B.copyInto({}, hostile));
      seen.push(B.stampRateDefaults([hostile])[0]);
      B.applyLaborRate([hostile], 61);   // a row it leaves alone is handed back as is, not copied
      seen.push(B.followLaborDays([Object.assign(JSON.parse(JSON.stringify(hostile)), {calc_default:{sf_per_day:1000,days:2}})], 5000)[0]);
      var d = JSON.parse('{"sf_per_day":1000,"days":2,"__proto__":{"polluted":1}}');
      var row = JSON.parse('{"id":"y","days":2,"calc_default":null}');
      row.calc_default = d;
      seen.push(B.followLaborDays([row], 9000)[0]);
      return {
        polluted: ({}).polluted === undefined ? 0 : 1,
        leaked: seen.map(function (r) {
          return ["__proto__", "constructor", "prototype"].filter(function (k) {
            return Object.prototype.hasOwnProperty.call(r, k) ||
                   (r.calc_default && Object.prototype.hasOwnProperty.call(r.calc_default, k));
          }).length;
        }),
        protoOk: seen.every(function (r) { return Object.getPrototypeOf(r) === Object.prototype; }),
        kept: B.copyInto({}, {a: 1, label: "L"})
      };
    })()"""
    got = _core(expr)
    assert got["polluted"] == 0
    assert got["leaked"] == [0] * 4
    assert got["protoOk"] is True
    assert got["kept"] == {"a": 1, "label": "L"}


@needs_node
def test_days_are_the_job_sf_over_the_production_rate_rounded_up():
    """12,000 / 2,500 = 4.8 -> 5; exactly 10,000 -> 4 (not 5); 10,001 -> 5.
    Mutation: Math.floor/Math.round instead of Math.ceil, and 4.8 -> 4 or the 10,001 case -> 4."""
    got = _core("[10000,10001,12000].map(function(sf){return B.laborCalcValues("
                "{mode:'sf',crew:3,sf_per_day:2500,hours_per_day:10},sf,33).days})")
    assert got == [4, 5, 5]


@needs_node
def test_no_sf_means_blank_days_not_zero_and_a_blank_rate_is_the_company_rate():
    v = _core("B.laborCalcValues({mode:'sf',crew:3,sf_per_day:2500},0,41)")
    assert v == {"guys": 3, "days": "", "hours_per_day": 8, "rate": 41}
    own = _core("B.laborCalcValues({mode:'fixed',guys:2,days:1.5,rate:55,hours_per_day:10},999,41)")
    assert own == {"guys": 2, "days": 1.5, "hours_per_day": 10, "rate": 55}
    assert _core("B.laborCalcValues({mode:'',guys:2},100,33)") is None


@needs_node
def test_ten_hours_a_day_prices_ten_and_nothing_else_does_but_eight():
    """3 guys x 5 days x $40 x 10 h = $6,000. A row that says 9, or 'abc', prices as the sheet does
    (8). Travel (an hours row) is never multiplied by a day at all."""
    got = _core("[B.laborCost({guys:3,days:5,rate:40,hours_per_day:10}),"
                "B.laborCost({guys:3,days:5,rate:40,hours_per_day:'10'}),"
                "B.laborCost({guys:3,days:5,rate:40,hours_per_day:9}),"
                "B.laborCost({guys:3,days:5,rate:40}),"
                "B.laborCost({guys:3,days:5,rate:40,unit:'hours',hours_per_day:10})]")
    assert got == [6000, 6000, 4800, 4800, 600]


@needs_node
def test_the_calculator_never_touches_travel_or_unconfigured_rows_and_returns_new_rows():
    got = _core("(function(){var rows=[{id:'polishing',guys:3,days:'',rate:33},"
                "{id:'travel',unit:'hours',guys:0,days:'',rate:33},{id:'jointfill',guys:3,days:'',rate:33}];"
                "var out=B.applyLaborCalc(rows,[{line_id:'polishing',mode:'fixed',guys:4,days:2},"
                "{line_id:'travel',mode:'fixed',guys:9,days:9}],1000,33);"
                "return {out:out,untouched:JSON.stringify(rows)}})()")
    assert got["out"][0]["guys"] == 4 and got["out"][0]["days"] == 2
    assert got["out"][1] == {"id": "travel", "unit": "hours", "guys": 0, "days": "", "rate": 33}
    assert "calc_default" not in got["out"][2]
    assert '"guys":4' not in got["untouched"]            # the input rows were not mutated
