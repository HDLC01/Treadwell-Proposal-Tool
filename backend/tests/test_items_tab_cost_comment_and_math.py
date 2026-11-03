"""The Items tab, 2026-11-04: Cost per Unit ($), a Cost Comment, no Order Quantity, and the math shown.

Hanz: "remove the order quantity. Then round up would be to just the nearest single unit ... relabel cost
to cost per unit. Let's also add the dollar sign on that cost header. And then between the vendor and
history headers, we put a cost comment field that would be a notes section ... Let's also add a way to
see how the logic is being solved to come up with a cost in the items tab."

  * THE HEADERS, read off library.html's own <thead>s with the comments taken out: "Cost per Unit ($)",
    "Cost Comment" between Vendor and History, and no Order Quantity or Order Amount anywhere on the page.
  * THE COST COMMENT, through the real routes on the fake database: trimmed, blank stored as NULL, too
    long refused, written only when the request carries it, and GET /api/library/items says whether the
    database has the column (cost_comment_writable) so the page can show it read-only instead.
  * THE MATH, library-core's itemWorking executed in node, and the real renderItems / paintItemMath out of
    library.js through library-ui-harness.js (out.itemsMath): one line under each Cost per Unit, repainted
    in place when the area changes, never by rebuilding the table.

Each test here fails on the code before the change (checked: the headers said "Order Quantity" and
"Cost", there was no cost_comment, no itemWorking, no working line).
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

import library
import main
import profiles

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
HTML = FRONTEND / "library.html"
CORE = FRONTEND / "js" / "library-core.js"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "library-ui-harness.js"

client = TestClient(main.app)


def _no_comments(text: str) -> str:
    out, at = "", 0
    while True:
        i = text.find("<!--", at)
        if i == -1:
            return out + text[at:]
        out += text[at:i]
        j = text.find("-->", i + 4)
        if j == -1:
            return out
        at = j + 3


def _page() -> str:
    """The page as a browser draws it: HTML comments and stylesheet comments out (one of the latter quotes
    Hanz's "order quantity etc. headers should be sticky" from 2026-10, which names nothing on screen)."""
    return re.sub(r"/\*.*?\*/", "", _no_comments(HTML.read_text(encoding="utf-8")), flags=re.S)


def _headers(table_class: str):
    page = _page()
    start = page.index('<table class="%s">' % table_class)
    head = page[start:page.index("</thead>", start)]
    cells = re.findall(r"<th[^>]*>(.*?)</th>", head, re.S)
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip() for c in cells]


# ── the headers ───────────────────────────────────────────────────────────────
def test_the_items_headers_read_exactly_as_asked():
    assert _headers("items-table") == [
        "", "Materials (how the manufacturer names it)", "Division", "Category", "Unit", "Coverage per Unit",
        "Waste Factor (%)", "Roundup?", "Cost per Unit ($)", "Vendor", "Cost Comment", "History", ""]


def test_the_cost_comment_sits_between_vendor_and_history():
    h = _headers("items-table")
    assert h.index("Vendor") + 1 == h.index("Cost Comment") == h.index("History") - 1


def test_the_assembly_lines_lost_the_order_amount_column():
    assert _headers("lines") == ["Items", "Coverage per Unit", "Waste Factor (%)", "Roundup?", "Quantity",
                                 "Cost ($)", ""]


def test_no_order_quantity_or_order_amount_anywhere_on_the_page():
    page = _page()
    assert not re.search(r"Order\s+(Quantity|Amount)", page, re.I), "the page still names an order quantity"
    assert "w-order" not in page and "cell-qty" not in page


def test_the_help_says_one_unit_and_whole_units():
    page = _page()
    cost = re.search(r'title="([^"]*)" aria-label="Cost per Unit, in dollars\.', page)
    assert cost and "ONE unit" in cost.group(1) and "not of a pack" in cost.group(1)
    roundups = re.findall(r'title="([^"]*)" aria-label="Roundup\.', page)
    assert len(roundups) == 2, "both Roundup headers (Items and the assembly lines)"
    for t in roundups:
        assert "whole unit" in t and "no decimals" in t and "pack" not in t, t


def test_the_empty_library_says_one_unit_not_a_purchase():
    page = _page()
    start = page.index('<div id="items-empty"')
    empty = re.sub(r"\s+", " ", page[start:page.index("</div>", start)])
    assert "the price of one unit (one gallon, one bag, one pound)" in empty
    assert "purchase" not in empty, "the empty state still describes buying by the pack"


# ── the cost comment, on the server ───────────────────────────────────────────
@pytest.fixture()
def store(fake_supabase, monkeypatch):
    st = {"library_items": [], "library_assemblies": [], "library_vendors": []}
    fake = fake_supabase(st)
    monkeypatch.setattr(library, "get_client", lambda: fake)
    monkeypatch.setattr(main, "_SUPER_ADMIN_EMAIL", "somebody-else@wetreadwell.com")
    monkeypatch.setattr(profiles, "get_by_email", lambda e: {"id": "u1", "email": e, "role": "user"})
    return st


def _mk(**kw):
    body = {"name": "OPF", "unit": "Gallon", "unit_cost": 42, "coverage": 275}
    body.update(kw)
    return library.create_item(body, "hanz@wetreadwell.com")


def test_a_cost_comment_round_trips_trimmed(store):
    it = _mk()
    r = client.patch("/api/library/items/%s" % it["id"], json={"cost_comment": "  Quote 4471, Sika rep  "})
    assert r.status_code == 200, r.text
    assert r.json()["item"]["cost_comment"] == "Quote 4471, Sika rep"
    assert store["library_items"][0]["cost_comment"] == "Quote 4471, Sika rep"
    listed = client.get("/api/library/items").json()
    assert listed["items"][0]["cost_comment"] == "Quote 4471, Sika rep"
    assert listed["cost_comment_writable"] is True


def test_a_blank_comment_is_stored_as_null(store):
    it = _mk()
    client.patch("/api/library/items/%s" % it["id"], json={"cost_comment": "Quote 1"})
    r = client.patch("/api/library/items/%s" % it["id"], json={"cost_comment": "   "})
    assert r.status_code == 200 and r.json()["item"]["cost_comment"] == ""
    assert store["library_items"][0]["cost_comment"] is None


def test_a_comment_longer_than_a_note_is_refused_not_cut(store):
    it = _mk()
    r = client.patch("/api/library/items/%s" % it["id"], json={"cost_comment": "x" * 4001})
    assert r.status_code == 400 and "too long" in r.json()["detail"]
    assert "cost_comment" not in store["library_items"][0]
    assert client.patch("/api/library/items/%s" % it["id"], json={"cost_comment": "x" * 4000}).status_code == 200


def test_the_comment_is_written_only_when_the_request_carries_it(store):
    """A database without backend/ops/library_cost_comment.sql must never be sent the column."""
    it = _mk()
    assert "cost_comment" not in store["library_items"][0], "a create named a column it was not given"
    client.patch("/api/library/items/%s" % it["id"], json={"unit_cost": 44})
    assert "cost_comment" not in store["library_items"][0]
    assert "cost_comment" not in library.validate_item({"name": "OPF"})
    assert "cost_comment" not in library.validate_item({"name": "OPF"}, partial=True)
    # ...and when it does carry it, it lands (the counterexample that keeps the lines above from being vacuous).
    client.patch("/api/library/items/%s" % it["id"], json={"cost_comment": "Quote 9"})
    assert store["library_items"][0]["cost_comment"] == "Quote 9"


def test_a_comment_moves_no_price_date(store):
    it = _mk()
    r = client.patch("/api/library/items/%s" % it["id"], json={"cost_comment": "Quote 4471"})
    assert r.json()["item"]["cost_comment"] == "Quote 4471", "the comment did not save, so this proves nothing"
    assert store["library_items"][0].get("cost_updated_at") is None


def test_the_items_read_says_whether_the_database_has_the_column(store):
    assert client.get("/api/library/items").json()["cost_comment_writable"] is True, "an empty library"
    _mk()                                   # the fake store, like a database without the column, has no key
    body = client.get("/api/library/items").json()
    assert body["cost_comment_writable"] is False and body["items"][0]["cost_comment"] == ""
    store["library_items"][0]["cost_comment"] = None            # the column applied: NULL is still a key
    assert client.get("/api/library/items").json()["cost_comment_writable"] is True


def test_a_database_without_the_column_answers_a_readable_400(store, monkeypatch):
    it = _mk()
    real = library.get_client()

    class Missing:
        def __init__(self, inner):
            self.inner = inner

        def table(self, name):
            t = self.inner.table(name)
            update = t.update

            def refusing(patch):
                if "cost_comment" in patch:
                    raise RuntimeError("Could not find the 'cost_comment' column of 'library_items'")
                return update(patch)
            t.update = refusing
            return t
    monkeypatch.setattr(library, "get_client", lambda: Missing(real))
    r = client.patch("/api/library/items/%s" % it["id"], json={"cost_comment": "Quote 1"})
    assert r.status_code == 400 and "library_cost_comment.sql" in r.json()["detail"]
    assert client.patch("/api/library/items/%s" % it["id"], json={"unit_cost": 90}).status_code == 200


def test_a_create_naming_the_missing_column_answers_a_readable_400_too(store, monkeypatch):
    """An empty library reads as "writable" (no row to judge by), and a stale or scripted client can POST a
    comment. The insert is refused by a database without the column; the answer must be the same 400 the
    PATCH gives, not a raw 500. The same create without a comment still saves."""
    real = library.get_client()

    class Missing:
        def __init__(self, inner):
            self.inner = inner

        def table(self, name):
            t = self.inner.table(name)
            insert = t.insert

            def refusing(row):
                if "cost_comment" in row:
                    raise RuntimeError("Could not find the 'cost_comment' column of 'library_items'")
                return insert(row)
            t.insert = refusing
            return t
    monkeypatch.setattr(library, "get_client", lambda: Missing(real))
    r = client.post("/api/library/items", json={"name": "OPF", "unit": "Gallon", "cost_comment": "Quote 1"})
    assert r.status_code == 400 and "library_cost_comment.sql" in r.json()["detail"]
    assert client.post("/api/library/items", json={"name": "OPF 2", "unit": "Gallon"}).status_code == 200


def test_the_column_is_on_both_databases_and_in_the_ops_file():
    ddl = "alter table public.library_items add column if not exists cost_comment text;"
    for path in ("backend/supabase_schema.sql", "backend/staging/schema_pg.sql",
                 "backend/ops/library_cost_comment.sql"):
        assert ddl in (ROOT / path).read_text(encoding="utf-8"), path
    ops = (ROOT / "backend/ops/library_cost_comment.sql").read_text(encoding="utf-8")
    assert "BOTH" in ops and ops.rstrip().endswith("notify pgrst, 'reload schema';")


# ── the math: library-core's itemWorking ──────────────────────────────────────
def _working(cases):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", "-e", """
      const L = require(%s);
      console.log(JSON.stringify(%s.map((c) => L.itemWorking(c[0], c[1]))));
    """ % (json.dumps(str(CORE)), json.dumps(cases))], capture_output=True, text=True, encoding="utf-8",
        timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


PRIMER = {"id": "p", "unit": "Gallon", "unit_cost": 42, "coverage": 275, "waste_pct": 5, "roundup": True,
          "buy_qty": 1}


def test_roundup_on_buys_whole_units_and_says_so():
    assert _working([[PRIMER, 1000]]) == [
        "1,000 SF ÷ 275 + 5% = 3.8182 → 4 Gallon × $42.00 = $168.00 ($0.168/SF)"]


def test_roundup_off_prices_the_exact_amount():
    assert _working([[dict(PRIMER, roundup=False), 1000]]) == [
        "1,000 SF ÷ 275 + 5% = 3.8182 Gallon × $42.00 = $160.36 ($0.160/SF)"]


def test_a_need_that_lands_on_a_whole_unit_has_no_arrow():
    assert _working([[dict(PRIMER, waste_pct=0), 1100]]) == [
        "1,100 SF ÷ 275 = 4 Gallon × $42.00 = $168.00 ($0.153/SF)"]


def test_a_material_that_cannot_price_says_what_it_needs():
    assert _working([[dict(PRIMER, coverage=None), 1000], [dict(PRIMER, unit_cost=None), 1000],
                     [dict(PRIMER, coverage=0), 1000]]) == ["Needs a coverage", "Needs a cost", "Needs a coverage"]


def test_a_cost_of_zero_needs_a_cost_like_the_rest_of_the_tab_says():
    """priceLine prices a 0 cost, but the Items tab files 0 under "No price set" (materialPriceText), so the
    working line must not show "x $0.00 = $0.00" for a material a bid would charge nothing for."""
    assert _working([[dict(PRIMER, unit_cost=0), 1000], [dict(PRIMER, unit_cost="0"), 1000]]) == [
        "Needs a cost", "Needs a cost"]


def test_no_area_is_no_line():
    assert _working([[PRIMER, ""], [PRIMER, 0], [PRIMER, None]]) == ["", "", ""]


def test_the_area_is_read_in_the_materials_own_measure():
    cove = dict(PRIMER, coverage=100, waste_pct=0, coverage_basis="lf")
    each = dict(PRIMER, unit="Each", coverage=1, waste_pct=0, coverage_basis="each", unit_cost=3.5)
    assert _working([[cove, 1000], [each, 12]]) == [
        "1,000 LF ÷ 100 = 10 Gallon × $42.00 = $420.00 ($0.420/LF)",
        "12 each ÷ 1 = 12 Each × $3.50 = $42.00 ($3.500/each)"]


def test_a_price_break_that_applies_is_the_price_shown():
    flake = {"id": "f", "unit": "lb", "unit_cost": 2.3, "coverage": 1, "waste_pct": 0, "roundup": True,
             "price_breaks": [{"min_qty": 240, "unit_cost": 2.25}]}
    assert _working([[flake, 239], [flake, 300]]) == [
        "239 SF ÷ 1 = 239 lb × $2.30 = $549.70 ($2.300/SF)",
        "300 SF ÷ 1 = 300 lb × $2.25 (price break from 240 lb) = $675.00 ($2.250/SF)"]


def test_the_working_multiplies_out_to_the_cost_priceLine_gives():
    """Not a second formula: the $ at the end of the line is priceLine's own cost at that area."""
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", "-e", """
      const L = require(%s);
      const it = %s, out = [];
      [1, 137, 1000, 2875, 40000].forEach((a) => [true, false].forEach((ru) => {
        const m = Object.assign({}, it, { roundup: ru });
        out.push([L.itemWorking(m, a), L.money(L.priceLine({ item_id: "p" }, [m], a).cost)]);
      }));
      console.log(JSON.stringify(out));
    """ % (json.dumps(str(CORE)), json.dumps(PRIMER))], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    for line, money in json.loads(proc.stdout):
        assert (" = " + money + " (") in line, (line, money)


# ── the page: the real renderItems and paintItemMath ──────────────────────────
@pytest.fixture(scope="module")
def harness():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)], capture_output=True, text=True,
                          encoding="utf-8", timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def ran(harness):
    return harness["itemsMath"]


def test_a_comment_saves_without_asking_the_price_question(harness):
    """"Save this change? ... is priced into every assembly that uses it" would be false about a note. The
    same row's cost edit still asks, which is the control that keeps this from passing on a dialog that
    never opens."""
    q = harness["commentSave"]["quiet"]
    assert q["asked"] == 0 and q["saved"] and q["body"] == '{"cost_comment":"Quote 4471"}'
    assert q["costAsks"] == 1
    assert harness["commentSave"]["noErrors"]


def test_a_comment_the_database_cannot_hold_is_dropped_not_requeued(harness):
    a, m = harness["commentSave"]["alone"], harness["commentSave"]["mixed"]
    assert a["stillUnsaved"] is False and a["pending"] == 0 and not a["marked"]
    assert a["writable"] is False and a["model"] == "", "the boxes stay offered over a column that is not there"
    assert m["pending"] == 1 and m["resentBody"] == '{"unit_cost":"61"}', "the cost edit beside it was lost"


def test_the_row_draws_the_comment_box_between_vendor_and_history(ran):
    assert ran["vendorIdx"] + 1 == ran["commentIdx"] == ran["historyIdx"] - 1
    assert ran["commentBox"], "the comment is not an escaped, editable box with data-f=cost_comment"


def test_the_working_line_sits_under_the_cost_per_unit(ran):
    assert ran["firstMathInCostCell"]
    assert ran["firstMath"] == ran["expectedFirst"] == \
        "1,000 SF ÷ 275 + 5% = 3.8182 → 4 Gal × $85.3827 = $341.53 ($0.342/SF)"


def test_a_new_area_repaints_the_lines_and_nothing_else(ran):
    """A rebuild while somebody types in the area box would throw the caret out (the refreshNumbers rule)."""
    assert ran["after2875"]["i1"] == ran["expected2875"] == \
        "2,875 SF ÷ 275 + 5% = 10.9773 → 11 Gal × $85.3827 = $939.21 ($0.327/SF)"
    assert ran["tableUntouched"] and ran["focusUntouched"]


def test_an_area_that_is_not_a_positive_number_says_so_in_grey(ran):
    """A blank box, or a bad value restored from localStorage, must not empty every line silently."""
    assert ran["afterBlank"] == ran["afterBad"] == "Enter an area above"
    assert ran["afterBlankGrey"]


def test_only_a_price_field_repaints_the_lines(ran):
    """Typing a name or a comment changes no price, so it costs no recompute of every visible row."""
    assert ran["afterNameEdit"] == "untouched"
    assert ran["afterCostEdit"] == ran["expectedFirst"]


def test_a_material_missing_a_number_says_so_in_grey(ran):
    assert ran["needsCoverage"] and ran["needsCost"]


def test_a_database_without_the_column_shows_the_comment_read_only(ran):
    assert ran["readOnly"]["noBox"] and ran["readOnly"]["showsText"]
