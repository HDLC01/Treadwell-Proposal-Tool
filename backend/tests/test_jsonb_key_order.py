"""The harnesses reopen a saved draft the way the SERVER hands one back: tests/js/_jsonb.js (2026-10-20, round 6, item C2).

`drafts.data` is a jsonb column, in production (supabase_schema.sql) and on staging (staging/schema_pg.sql) alike, and the backend returns it as it reads it (load_draft, then FastAPI's
JSON, with no sort of its own). jsonb keeps no key order. It stores every object's keys sorted by length in BYTES and then by the bytes, at every depth, so a reopened draft is not the
object its session saved: the same values under other keys' order. A harness that "reopens" with a plain JSON copy keeps the session's order and can never see what depends on it
(test_v2_sheet_order.py is one such thing; test_polish_travel_sequences_reload.py's walks now go through the helper too).

This file holds the helper to PostgreSQL's order, on keys whose order is known (tests/js/jsonb-selftest-harness.js: the documentation's own example, the keys of a bid's sheets, and the
cases that tell the rule from the ones it is easily mistaken for, and fifteen documents a real PostgreSQL 18.2 answered), and to the two facts the rule rests on: the column is jsonb in both
databases (read from the schema files) and the backend hands the blob back in the order the database gave it (EXECUTED, not read: see the block that says what it does and does not prove).
The last block breaks a COPY of the helper one line at a time.
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


# ── what the backend does with the order: EXECUTED ───────────────────────────────────────────────
# WHAT THIS PROVES. GET /api/draft/{id} is called for real (FastAPI's TestClient, the real route, the real drafts.load_draft, FastAPI's own JSON encoding), over a store whose draft row holds
# `data` exactly as the data client would parse a real PostgreSQL's answer: the dicts json.loads makes of the TEXT a PostgreSQL 18.2 returned for `jsonb::text` (the fixture's `server`
# strings: the keys in jsonb's order, at every depth). The response BODY is then read back with every object as a list of pairs, and the pairs must be the server's, in the server's order.
# So nothing in this repository's path from the row to the bytes (load_draft, the route, the encoder) reorders a key: a sort_keys, a sorted() or a reordering encoder would fail it, and
# two such breaks are put in below to show it does.
# WHAT IT DOES NOT PROVE. The data client itself is not run: the fake hands over the dicts, so that supabase-py's HTTP read (httpx, Python's json, which keep an object's order) keeps the
# order is assumed, not shown. Nor is PostgREST run (staging's and Supabase's): that it emits a jsonb column in the order the server stores it is what the staging walk saw
# ([Polish 2, Gyp (base)] after a reload), not something this file executes. And the browser's half (JSON.parse, which keeps order except for keys that are array indexes) is
# tests/js/_jsonb.js's, held to the same recorded answers above.
def _pairs(text):
    """JSON text with every object as a list of [key, value] pairs in the order the text holds them (two dicts that differ only in key order are equal; two of these are not)."""
    return json.loads(text, object_pairs_hook=lambda kv: [list(p) for p in kv])


def _served(fake_supabase, monkeypatch, data, wrap_load=None, sorted_encoding=False):
    """The `data` member of what GET /api/draft/d1 answers, as pairs, for a stored draft whose `data` is the dict `data`.
    `wrap_load`: a function that is handed the real load_draft and returns the one to use. `sorted_encoding`: FastAPI's serialization of the response (routing.serialize_response, which
    every version calls by name for a route with a response type, and which hands back bytes or primitives according to the version) is made to sort every object's keys."""
    import drafts
    import main
    from fastapi.testclient import TestClient

    row = {"id": "d1", "data": data, "owner_email": "u@x.com", "created_at": "2026-10-20", "updated_at": "2026-10-20", "deleted_at": None}
    monkeypatch.setattr(drafts, "get_client", lambda: fake_supabase({"drafts": [row]}))
    if wrap_load is not None:
        monkeypatch.setattr(drafts, "load_draft", wrap_load(drafts.load_draft))
    if sorted_encoding:
        import fastapi.routing as routing
        real_serialize = routing.serialize_response

        async def sorting_serialize(**kwargs):
            out = await real_serialize(**kwargs)
            primitives = json.loads(out) if isinstance(out, (bytes, str)) else out
            ordered = json.loads(json.dumps(primitives), object_pairs_hook=lambda kv: dict(sorted(kv)))
            return json.dumps(ordered).encode("utf-8") if isinstance(out, (bytes, str)) else ordered

        monkeypatch.setattr(routing, "serialize_response", sorting_serialize)
    res = TestClient(main.app).get("/api/draft/d1")
    assert res.status_code == 200, res.text
    return dict(_pairs(res.text))["data"]


def _server_text(name):
    return [c for c in _recorded()["cases"] if c["name"] == name][0]["server"]


@pytest.mark.parametrize("name", [c["name"] for c in json.loads(RECORDED.read_text(encoding="utf-8"))["cases"]])
def test_the_backend_hands_back_the_order_a_real_postgres_returned_unchanged(fake_supabase, monkeypatch, name):
    server = _server_text(name)
    assert _served(fake_supabase, monkeypatch, json.loads(server)) == _pairs(server)


def _sorting_load(real):
    def load(draft_id):
        row = real(draft_id)
        return dict(row, data=json.loads(json.dumps(row["data"], sort_keys=True)))
    return load


def test_the_check_has_an_order_to_notice(fake_supabase, monkeypatch):
    """A comparison a sorting backend would pass proves nothing. The recorded sheets of a bid are in neither alphabetical order nor its reverse (Seal, Copy1, Copy2, Epoxy, Copy10, ...)."""
    keys = [k for k, _ in _pairs(_server_text("the sheets of a bid"))]
    assert keys != sorted(keys) and keys != sorted(keys, reverse=True), keys
    assert _served(fake_supabase, monkeypatch, json.loads(_server_text("the sheets of a bid"))) == _pairs(_server_text("the sheets of a bid"))


@pytest.mark.parametrize("variant", ["load_draft sorts the keys", "the response's serialization sorts the keys"])
def test_the_check_notices_a_backend_that_sorts_the_keys(fake_supabase, monkeypatch, variant):
    """The same comparison, with a sort put in the one place each layer could have it, must fail: the check is not one that any backend passes."""
    server = _server_text("the sheets of a bid")
    got = _served(fake_supabase, monkeypatch, json.loads(server),
                  wrap_load=_sorting_load if variant.startswith("load_draft") else None, sorted_encoding=variant.startswith("the response"))
    assert got != _pairs(server), variant
    assert [k for k, _ in got] == sorted(k for k, _ in got), "and what it hands back is the alphabetical order, so the break did what it says"


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
