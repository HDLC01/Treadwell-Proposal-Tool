"""What `_versioned_json` puts on the wire, now that `jsonable_encoder` is off the hot path.

THE CHANGE THIS GUARDS. `_versioned_json` used to serialize as
`JSONResponse(content=jsonable_encoder(payload))`. On these payloads that call was a pure
no-op — `estimate_writer._normalize_cell_value` has already turned openpyxl's dates into
"M/D/YYYY" strings by the time a grid reaches a response — but it still walked and rebuilt
every dict and list in a 1.2 MB grid before `json.dumps` walked them again. Measured
2026-09-17 through the real ASGI stack with the grids already cached: 385 ms of a 634 ms
sixteen-tab load, 61%, for byte-identical output.

So this module asserts two different things, and they fail for different reasons:

  * THE OUTPUT DID NOT MOVE — every endpoint that goes through `_versioned_json` produces
    exactly the bytes the old expression produced. Compared byte-for-byte, against
    `JSONResponse(jsonable_encoder(...))` built right here, so it is a comparison with the
    real previous behaviour rather than with a snapshot somebody typed.
  * THE ENCODER IS NOT BEING CALLED — because "byte-identical" stays true if somebody
    puts the eager pass back, and the whole change is that it is gone.

And three guards that an adversarial review asked for BEFORE this shipped, because each one
is a way to be fast and wrong:

  (a) a type `json.dumps` has no encoder for must not 500. `datetime.timedelta` is the real
      one: openpyxl returns it for a duration-formatted cell ([h]:mm), no cell in today's
      template carries that format, and Kyle edits the template.
  (b) an identity client — one that did not ask for gzip — must still get plain JSON it can
      read. This is only a live question if the handler compresses for itself; it does not,
      and this test is what says so if that ever changes.
  (c) `Vary: Accept-Encoding` must be on the response, or a shared cache can hand a gzipped
      body to a client that cannot decode it.

(b) and (c) are Starlette's GZipMiddleware's job today and it does them. They are asserted
anyway: the reason the handler is allowed to leave them to the middleware is that it hands
over an UNCOMPRESSED body, and `GZipMiddleware`'s skip branch — the one taken when the
response already carries a `Content-Encoding` — sends the initial message through untouched,
never reaching `add_vary_header`. Anyone who pre-compresses here to save the last 70 ms
loses both at once, silently, and these two tests are the trap that catches it.
"""
import datetime as dt
import json
import pathlib

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import estimate_writer
import main
import pricing

client = TestClient(main.app)

SHEETS = estimate_writer.list_sheet_names()


def _old_way(payload):
    """Exactly the expression `_versioned_json` used to end with."""
    return JSONResponse(content=jsonable_encoder(payload)).body


def _new_way(payload):
    return main._CompactJSONResponse(content=payload).body


# ── the output did not move ──────────────────────────────────────────────────
def test_the_sheet_list_is_not_empty():
    """Read first: every parametrized test below is vacuous if SHEETS is empty, and an empty
    list is what a broken template path produces — quietly, at import time."""
    assert len(SHEETS) >= 16, "only %d tabs found: %r" % (len(SHEETS), SHEETS)


@pytest.mark.parametrize("sheet", SHEETS)
def test_every_grid_serializes_to_the_same_bytes_as_before(sheet):
    """THE ONE THAT LICENSES THE CHANGE. Not "parses to the same object" — the same bytes, so
    a difference in key order, float formatting or escaping would fail here too."""
    grid = estimate_writer.read_sheet_grid(sheet)
    assert _new_way(grid) == _old_way(grid), (
        "the %r grid serializes differently without jsonable_encoder — it was NOT a no-op on "
        "this payload, and dropping it changed what the browser receives" % sheet)


@pytest.mark.parametrize("payload_name", ["systems", "named_expressions"])
def test_the_other_template_endpoints_serialize_unchanged_too(payload_name):
    """`_versioned_json` serves more than grids. The pricing recipes and the workbook's defined
    names go through the same call, and both contain types (Decimal, tuples) that
    `jsonable_encoder` DOES convert — so this is where the no-op claim could have been false."""
    payload = {
        "systems": lambda: {"systems": pricing.list_systems(),
                            "coves": pricing.list_cove_options()},
        "named_expressions": lambda: {"names": estimate_writer.read_named_expressions()},
    }[payload_name]()
    assert _new_way(payload) == _old_way(payload)


# Every URL that reaches `_versioned_json`. The grids and the two payloads above are checked
# in isolation; this list exists so the SAME claim is checked through the real handler for the
# callers whose payload cannot easily be rebuilt here — the document editor's two template
# descriptions, which are the ones carrying block geometry and run properties rather than
# cells, and so the ones most likely to hold a type json.dumps has never met.
VERSIONED_ENDPOINTS = [
    "/api/sheets",
    "/api/named-expressions",
    "/api/pricing/systems",
    "/api/sheet/Epoxy",
    # NOT /api/proposal-template. It stopped calling _versioned_json when the template cache
    # landed (#534): it computes its version first and answers If-None-Match before opening
    # anything, through its own _etag_of. Its byte-identity is proven in
    # test_proposal_template_cache.py instead -- 99 response records and 12 generated
    # documents. The count assertion below is what caught the drift, which is its job.
    "/api/coverletter-template?work_type=epoxy&audience=Direct",
]


def test_the_endpoint_list_covers_every_caller_of_the_helper():
    """A list of URLs in a test file is exactly the kind of thing that outlives the code it
    names. Count the call sites in main.py and require one URL each, so a seventh caller fails
    here instead of quietly going unchecked."""
    src = pathlib.Path(main.__file__).read_text(encoding="utf-8")
    call_sites = src.count("_versioned_json(") - src.count("def _versioned_json(")
    assert call_sites == len(VERSIONED_ENDPOINTS), (
        "main.py calls _versioned_json from %d places and this file names %d URLs"
        % (call_sites, len(VERSIONED_ENDPOINTS)))


@pytest.mark.parametrize("url", VERSIONED_ENDPOINTS)
def test_every_versioned_json_endpoint_is_byte_identical_through_the_real_handler(url, monkeypatch):
    """The same byte-for-byte claim, but made by running each endpoint twice: once as it ships,
    once with `_CompactJSONResponse` swapped for a subclass that does exactly what the old
    expression did. `_versioned_json` looks the class up as a module global, which is what makes
    the swap reach it.

    `Accept-Encoding: identity` so `.content` is the body rather than its gzip."""
    live = client.get(url, headers={"Accept-Encoding": "identity"})
    assert live.status_code == 200, "%s answered %s — this comparison proves nothing" % (
        url, live.status_code)
    assert live.content, "%s returned an empty body" % url

    class _TheOldWay(main._CompactJSONResponse):
        def render(self, content):
            return super().render(jsonable_encoder(content))

    monkeypatch.setattr(main, "_CompactJSONResponse", _TheOldWay)
    before = client.get(url, headers={"Accept-Encoding": "identity"})
    assert before.status_code == 200
    assert live.content == before.content, (
        "%s serializes differently without the eager jsonable_encoder pass" % url)


def test_the_byte_identity_comparison_is_capable_of_failing():
    """THE COUNTEREXAMPLE for every comparison above, and the one honest difference between the
    two paths.

    `json.dumps` calls `default=` for VALUES only. A dict key that is not str/int/float/bool/
    None is a TypeError it never offers to anybody, while the eager encoder used to stringify
    it on the way past — so here the old path produces JSON and the new one refuses. That is
    what makes `_new_way(x) == _old_way(x)` a real claim about the payloads rather than an
    identity that could not have come out any other way.

    It is also the reason the byte-identity tests are parametrized over every grid and every
    endpoint instead of one sample: nothing served today is keyed by anything but a name or a
    row number, and this is the assertion that will change colour if that stops being true."""
    exotic = {dt.date(2026, 9, 17): "a date used as a dict KEY"}
    assert _old_way(exotic), "jsonable_encoder no longer stringifies exotic keys"
    with pytest.raises(TypeError):
        _new_way(exotic)


def test_no_payload_we_serve_is_keyed_by_anything_json_cannot_key_on():
    """The other half: the difference above is only acceptable while nothing hits it. Walk the
    heaviest real payload and check every key, so this is a statement about the data rather
    than a hope."""
    def keys(node):
        if isinstance(node, dict):
            for k, v in node.items():
                yield k
                yield from keys(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                yield from keys(v)

    for sheet in ("Epoxy", "Takeoff"):
        bad = [k for k in keys(estimate_writer.read_sheet_grid(sheet))
               if not isinstance(k, (str, int, float, bool, type(None)))]
        assert not bad, "%s is keyed by %r, which json.dumps cannot write" % (sheet, bad[:3])


def test_the_live_sheet_endpoint_returns_what_the_old_encoder_would_have():
    """End to end, through the real app, rather than against the helper in isolation.

    BYTES, not `r.json()`. `row_heights` is keyed by row NUMBER, so the Python dict the old
    expression produced holds ints and the parsed response holds the strings `json.dumps`
    turned them into — the two compare unequal while the wire format is character for
    character the same. Asking the response for identity encoding is what makes `r.content`
    the body itself rather than its gzip."""
    r = client.get("/api/sheet/Epoxy", headers={"Accept-Encoding": "identity"})
    assert r.status_code == 200
    assert r.content == _old_way(estimate_writer.read_sheet_grid("Epoxy"))


# ── the encoder is not being called ──────────────────────────────────────────
def test_serving_a_grid_never_walks_it_with_jsonable_encoder(monkeypatch):
    """THE PERFORMANCE ASSERTION, EXECUTED. Every byte-identity test above stays green if the
    eager pass comes back — that is precisely what "no-op" means — so the saving needs its own
    guard. `_json_fallback` looks the name up on the module at call time, which is what makes
    this patch reach the only caller left."""
    calls = []
    monkeypatch.setattr(main, "jsonable_encoder",
                        lambda o, *a, **k: calls.append(o) or jsonable_encoder(o, *a, **k))
    r = client.get("/api/sheet/Epoxy")
    assert r.status_code == 200
    assert calls == [], (
        "jsonable_encoder ran %d times while serving one grid; the eager walk is back and the "
        "385 ms it cost is back with it" % len(calls))


# ── guard (a): an unknown type must not 500 ──────────────────────────────────
def test_a_duration_cell_renders_instead_of_500ing():
    """openpyxl hands back a `timedelta` for a cell formatted as a duration. `json.dumps` has
    no encoder for one, so without `default=` this is a TypeError inside the response — a 500
    on a sheet that opened fine yesterday, caused by a number format changed in Excel."""
    payload = {"sheet": "Epoxy", "cells": [{"addr": "A1", "value": dt.timedelta(hours=2)}]}
    body = _new_way(payload)
    assert json.loads(body)["cells"][0]["value"] == 7200.0


def test_a_duration_cell_renders_the_way_the_old_encoder_rendered_it():
    """And renders it the SAME way — `total_seconds()`, a number, not `str(timedelta)`. The
    fallback defers to `jsonable_encoder` for exactly this reason: whatever it used to convert
    still converts identically, so the grid the frontend parses cannot change shape."""
    payload = {"v": dt.timedelta(hours=2, minutes=30)}
    assert _new_way(payload) == _old_way(payload)


def test_a_value_neither_encoder_understands_degrades_to_text_rather_than_a_500():
    """STRICTLY SAFER THAN WHAT SHIPPED BEFORE, which is the point. The old eager pass raised
    out of the handler, so one unconvertible value anywhere in a grid took the whole sheet
    down. Now the worst case is one cell reading as its repr."""

    class Opaque:
        __slots__ = ()                      # no __dict__, not iterable: jsonable_encoder fails too

    with pytest.raises(Exception):
        jsonable_encoder(Opaque())          # the counterexample: this really is unconvertible

    out = json.loads(_new_way({"v": Opaque()}))
    assert isinstance(out["v"], str) and "Opaque" in out["v"]


def test_nan_is_still_refused():
    """`allow_nan=False` is not decoration carried over for symmetry. `NaN` is not JSON, and
    `JSON.parse` in the browser throws on it — a silently-emitted NaN would break the grid at
    parse time, which is much harder to trace than a 500 here."""
    with pytest.raises(ValueError):
        main._CompactJSONResponse(content={"v": float("nan")}).body


# ── guards (b) and (c): content negotiation ──────────────────────────────────
def test_a_client_that_did_not_ask_for_gzip_gets_readable_json():
    """GUARD (b). The handler hands the middleware an uncompressed body, so an identity client
    gets identity. If this ever starts failing it will be because somebody compressed in the
    handler without gating on Accept-Encoding, and the symptom in the wild is a client reading
    gzip bytes as text."""
    r = client.get("/api/sheet/Polish", headers={"Accept-Encoding": "identity"})
    assert r.status_code == 200
    assert not r.headers.get("content-encoding"), (
        "an identity client was sent Content-Encoding: %r" % r.headers.get("content-encoding"))
    assert r.json()["sheet"] == "Polish"


def test_the_gzip_client_still_gets_gzip():
    """The counterexample for the test above: it is only worth anything if compression happens
    at all on the other branch."""
    r = client.get("/api/sheet/Polish", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"
    assert r.json()["sheet"] == "Polish"


@pytest.mark.parametrize("encoding", ["gzip", "identity"])
def test_the_response_varies_on_accept_encoding(encoding):
    """GUARD (c). Without it a shared cache may store the gzipped body under the bare URL and
    serve it to a client that never asked for gzip. Starlette adds this — on the branch that
    compresses. The branch it does NOT add it on is the one taken when the response already
    carries a Content-Encoding, which is exactly what pre-compressing here would produce."""
    r = client.get("/api/sheet/Polish", headers={"Accept-Encoding": encoding})
    assert "accept-encoding" in (r.headers.get("vary") or "").lower(), (
        "no Vary on the %s response: %r" % (encoding, r.headers.get("vary")))


# ── the 304 path is untouched ────────────────────────────────────────────────
def test_the_conditional_get_still_short_circuits_before_any_serialization():
    """The saving is on COLD loads only, and this says why: a revalidation returns above the
    encoder entirely, so the warm steady state never paid the 385 ms and does not get faster."""
    first = client.get("/api/sheet/Epoxy")
    etag = first.headers["etag"]
    second = client.get("/api/sheet/Epoxy", headers={"If-None-Match": etag})
    assert second.status_code == 304 and second.content == b""
    assert second.headers["etag"] == etag
