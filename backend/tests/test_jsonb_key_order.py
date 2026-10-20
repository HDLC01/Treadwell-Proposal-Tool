"""The harnesses reopen a saved draft the way the SERVER hands one back: tests/js/_jsonb.js (2026-10-20, round 6, item C2).

`drafts.data` is a jsonb column, in production (supabase_schema.sql) and on staging (staging/schema_pg.sql) alike, and the backend returns it as it reads it (load_draft, then FastAPI's
JSON, with no sort of its own). jsonb keeps no key order. It stores every object's keys sorted by length in BYTES and then by the bytes, at every depth, so a reopened draft is not the
object its session saved: the same values under other keys' order. A harness that "reopens" with a plain JSON copy keeps the session's order and can never see what depends on it
(test_v2_sheet_order.py is one such thing; test_polish_travel_sequences_reload.py's walks now go through the helper too).

This file holds the helper to PostgreSQL's order, on keys whose order is known (tests/js/jsonb-selftest-harness.js: the documentation's own example, the keys of a bid's sheets, and the
cases that tell the rule from the ones it is easily mistaken for), and to the three schema facts the rule rests on. The last block breaks a COPY of the helper one line at a time.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
BACKEND = TESTS.parent
HARNESS = TESTS / "js" / "jsonb-selftest-harness.js"
HELPER = TESTS / "js" / "_jsonb.js"
RECORDED = TESTS / "fixtures" / "jsonb_key_order_pg18.json"
SHEETS = ["Seal", "Copy1", "Copy2", "Epoxy", "Copy10", "Polish 2", "Gyp (base)", 'Gyp (USG 1-8")']
EXPECTED = {
    "documented": ["bar", "active", "balance"],
    "length": ["", "a", "aa", "bb", "ccc"],
    "bytes": ["A", "B", "_", "a", "b"],
    "multibyte": ["b", "ab", "zz", "é", "abc", "€"],
    "sheets": SHEETS,
    "indexKeys": ["2", "10", "a", "b"],
    "nested": {"top": ["a", "n", "t", "zz"], "list": [["a", "b"], 3, None, "s"], "deep": ["x", "yy"], "inner": ["a", "bb", "ccc"], "same": "1"},
    "pure": {"inputIntact": True, "independent": True},
    "reloaded": {"keys": ["b", "d"], "date": "1970-01-01T00:00:00.000Z"},
    "proto": {"keys": ["a", "zzzz", "__proto__"], "own": True, "polluted": False, "prototypeKept": True},
    "compare": [-1, 1, 0, -1, 1, -1],
}


def run(helper=HELPER):
    proc = run_node(HARNESS, helper, RECORDED)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr[-800:]
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    require_node()
    return run()


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_the_helper_orders_keys_as_postgres_jsonb_does(ran, name):
    assert ran[name] == EXPECTED[name]


# ── what a real PostgreSQL returned ─────────────────────────────────────────────────────────────
def _recorded():
    return json.loads(RECORDED.read_text(encoding="utf-8"))


def test_the_recorded_answers_are_a_real_servers_and_cover_the_cases_that_matter():
    """tests/fixtures/jsonb_key_order_pg18.json is `select '<input>'::jsonb::text` run on a PostgreSQL 18.2 started for the purpose (the SQL is in the file's `meta`). It holds the manual's own
    example, keys that differ in BYTES but not in characters, a four byte character, the sheets of a bid, the pair the staging walk saw, numbers as keys, __proto__, and a draft's own keys."""
    data = _recorded()
    assert data["meta"]["server"].startswith("PostgreSQL 18"), data["meta"]
    names = [c["name"] for c in data["cases"]]
    assert len(names) >= 15 and len(set(names)) == len(names)
    server = {c["name"]: c["server"] for c in data["cases"]}
    assert server["documented example (PostgreSQL manual, 8.14.1)"] == '{"bar": "baz", "active": false, "balance": 7.77}'
    assert server["the staging pair"] == '{"Polish 2": 2, "Gyp (base)": 1}', "the order the staging walk saw: Polish 2 before Gyp (base)"


@pytest.mark.parametrize("name", [c["name"] for c in json.loads(RECORDED.read_text(encoding="utf-8"))["cases"]])
def test_the_helper_puts_every_recorded_document_in_the_order_a_real_postgres_returned_it(ran, name):
    got = [r for r in ran["recorded"] if r["name"] == name]
    assert got and got[0]["same"] is True, "the helper's order is not the server's for %r" % name


def test_the_sheets_the_staging_walk_saw_flip_the_way_it_saw_them(ran):
    """'Polish 2' (eight bytes) comes before 'Gyp (base)' (ten), and 'Copy1' before 'Gyp (USG 1-8")' (five before fourteen): [Gyp (base), Polish 2] in a session, [Polish 2, Gyp (base)] after."""
    order = ran["sheets"]
    assert order.index("Polish 2") < order.index("Gyp (base)")
    assert order.index("Copy1") < order.index('Gyp (USG 1-8")') and order.index("Copy1") < order.index("Epoxy")


# ── the facts the order rests on ────────────────────────────────────────────────────────────────
def test_both_databases_store_the_draft_blob_as_jsonb():
    """production (Supabase) and staging (the VPS Postgres) both: `data jsonb`. If the column ever becomes json (text, key order kept) this whole round's premise changes."""
    for rel in ("supabase_schema.sql", "staging/schema_pg.sql"):
        sql = (BACKEND / rel).read_text(encoding="utf-8")
        table = re.search(r"create table if not exists public\.drafts \((.*?)\n\);", sql, re.S).group(1)
        assert re.search(r"^\s*data\s+jsonb\b", table, re.M), "%s: drafts.data is no longer jsonb:\n%s" % (rel, table)


def test_the_backend_hands_the_blob_back_in_the_order_it_read_it():
    """No sort_keys on the way out: drafts.load_draft returns row['data'] as the database gave it, and the route returns it in a dict (FastAPI's JSON keeps a dict's order)."""
    drafts = (BACKEND / "drafts.py").read_text(encoding="utf-8")
    body = re.search(r"def load_draft\(.*?\n\n\n", drafts, re.S).group(0)
    assert '"data": row.get("data") or {}' in body and "sort" not in body
    main = (BACKEND / "main.py").read_text(encoding="utf-8")
    route = re.search(r'@app\.get\("/api/draft/\{draft_id\}"\)\n(.*?)\n\n\n', main, re.S).group(1)
    assert "drafts.load_draft(draft_id)" in route and "sort" not in route


# ── red without the code: break a COPY of the helper one line at a time ────────────────────────
COMPARE_LENGTH = "  if (x.length !== y.length) return x.length < y.length ? -1 : 1;"
COMPARE_BYTES = "  return Buffer.compare(x, y);"
SORT = "    Object.keys(value).sort(compareKeys).forEach((k) => {"
ARRAYS = "  if (Array.isArray(value)) return value.map(jsonbOrder);"
OWN = "      Object.defineProperty(out, k, { value: jsonbOrder(value[k]), enumerable: true, writable: true, configurable: true });"
CLONE = "  return jsonbOrder(JSON.parse(JSON.stringify(blob)));"

# name -> (old, new, the facts that must change)
BREAKS = {
    "length is counted in characters, not bytes": (
        COMPARE_LENGTH, "  if (String(a).length !== String(b).length) return String(a).length < String(b).length ? -1 : 1;", {"multibyte", "compare", "recorded"}),
    "equal lengths keep the order they came in": (COMPARE_BYTES, "  return 0;", {"bytes", "multibyte", "compare", "recorded"}),
    "the keys are not sorted at all": (SORT, "    Object.keys(value).forEach((k) => {", {"documented", "length", "sheets", "nested", "recorded"}),
    "an array's objects are not re-keyed": (ARRAYS, "  if (Array.isArray(value)) return value;", {"nested", "recorded"}),
    "a key is assigned and not defined (__proto__ becomes the prototype)": (OWN, "      out[k] = jsonbOrder(value[k]);", {"proto", "recorded"}),
    "reloaded() does not clone": (CLONE, "  return jsonbOrder(blob);", {"reloaded"}),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_selftest_goes_red_when_the_line_that_keeps_the_order_is_broken(tmp_path, name):
    """The break must be SEEN: a fact the harness reports changes (and the line must be in the helper exactly once, or the break applies nowhere)."""
    require_node()
    old, new, facts = BREAKS[name]
    src = HELPER.read_bytes().decode("utf-8")
    assert src.count(old) == 1, "the anchor %r appears %d times in _jsonb.js, not once" % (old, src.count(old))
    broken = tmp_path / "_jsonb.js"
    broken.write_bytes(src.replace(old, new).encode("utf-8"))
    got = run(broken)
    changed = {k for k in EXPECTED if got.get(k) != EXPECTED[k]}
    if not all(r["same"] for r in got.get("recorded", [])):
        changed.add("recorded")
    assert facts & changed, "the self-test did not notice: %s (changed: %s)" % (name, sorted(changed))
