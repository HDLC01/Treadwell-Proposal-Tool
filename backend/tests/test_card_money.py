"""The money on a project card — which figure, and whether it survives the trip out of Postgres.

Kyle, 2026-08-19: "why not all containers have the dollar amount?" Hanz: "every project should
show the basebid total lump sum."

The answer was worse than the question. `_bid_total` read ONLY
`computed_bid.full_bid.total_base_bid`, the removed Reference Bid engine, which
estimate-review.js nulls on the way out of step 2. Counted against the live database that day:

    31 active drafts · 27 with proposal_lump_sum · 6 with computed_bid

So 21 priced projects showed no money at all, and the 6 that showed some showed the ENGINE's
figure, which disagrees with the sheet in both directions on every row where both exist:

    draft 17117b50   card $30,960   real bid $45,629
    draft 23b89a10   card $43,098   real bid $60,012
    draft 89b3498b   card $11,573   real bid  $7,861

Those three pairs are used as fixtures below rather than invented numbers, so the test fails for
the reason the bug existed.
"""
import importlib
import re

import pytest

drafts = importlib.import_module("drafts")


def _draft(lump=None, engine=None, beta_version=None, grand_total=None):
    """A draft blob carrying only the keys under test."""
    d = {}
    if lump is not None:
        d["proposal_lump_sum"] = lump
    cb = {}
    if engine is not None:
        cb["full_bid"] = {"total_base_bid": engine}
    if grand_total is not None:
        cb["grand_total"] = grand_total
    if cb:
        d["computed_bid"] = cb
    if beta_version is not None:
        d["polish_estimate"] = {"version": beta_version}
    return d


# ── A. the figure itself ─────────────────────────────────────────────────────
def test_a_priced_draft_has_money_on_it():
    """The 21. Priced on the sheet, no engine object, and the card said nothing."""
    assert drafts._bid_total(_draft(lump=17345)) == 17345.0


@pytest.mark.parametrize("engine,lump", [(30960, 45629), (43098, 60012), (11573, 7861)])
def test_the_sheets_lump_sum_beats_the_removed_engine(engine, lump):
    """Real pairs off the live database. Note the third: the engine reads HIGH there and low on
    the other two, so "always the larger" would pass two of these and is not the rule. The rule is
    that the sheet is what the estimator is looking at and what the document prints."""
    assert drafts._bid_total(_draft(lump=lump, engine=engine)) == float(lump)


def test_an_old_draft_still_shows_its_engine_figure():
    """One 2026-06 draft has an engine total and no lump sum. proposal-review.js falls back to the
    engine for exactly these, so the card has to as well — otherwise it names no price on a project
    whose proposal would print $214,471."""
    assert drafts._bid_total(_draft(engine=214471)) == 214471.0


def test_material_only_mode_is_not_dropped():
    """The third branch of proposal-review.js's own chain. Omitting it here would blank the card
    for a draft the proposal prices fine."""
    assert drafts._bid_total(_draft(grand_total=8250)) == 8250.0


def test_no_figure_at_all_is_none_not_zero():
    """A brand-new draft has no price yet. `0.0` would render as "$0" — a quoted price of nothing,
    which is a lie rather than a blank. cardTotal in crm-core.js keys the card's whole money block
    on `!= null`, so None is what makes it disappear."""
    assert drafts._bid_total(_draft()) is None
    assert drafts._bid_total({}) is None
    assert drafts._bid_total(None) is None


# ── B. the polish beta inverts the order ─────────────────────────────────────
def test_a_beta_project_prefers_its_own_engine_object():
    """polish-estimate.js writes computed_bid on every save and never touches proposal_lump_sum.
    On a project first priced on the spreadsheet and then re-priced in the beta, the lump sum is
    the STALE number. Preferring it would quote a bid nobody stands behind.

    Mutation to prove this test earns its place: drop the beta branch from _bid_total and this is
    the only case that fails."""
    d = _draft(lump=7861, engine=11573, beta_version=2)
    assert drafts._bid_total(d) == 11573.0


def test_a_beta_project_with_no_engine_object_still_falls_back():
    """Ordering, not exclusion. A v2 project whose calculator has not saved yet must not lose a
    lump sum it already had."""
    assert drafts._bid_total(_draft(lump=6400, beta_version=2)) == 6400.0


def test_only_version_2_inverts():
    """`polish_estimate` exists on pre-beta polish drafts too. Treating any of them as beta would
    hand the old engine figure to a project the sheet priced."""
    assert drafts._bid_total(_draft(lump=7861, engine=11573, beta_version=1)) == 7861.0
    assert drafts._bid_total(_draft(lump=7861, engine=11573)) == 7861.0


# ── C. what a `->>` projection actually hands back ───────────────────────────
def test_a_string_lump_sum_is_a_number():
    """`data->>proposal_lump_sum` is a TEXT extraction — the fast path receives "17345", not
    17345. Comparing that to 0 raises in Python 3, and returning it unconverted would send a
    string to money() on the card."""
    assert drafts._bid_total(_draft(lump="17345")) == 17345.0
    assert drafts._bid_total(_draft(lump="17345.50")) == 17345.5


@pytest.mark.parametrize("junk", ["", "null", "None", "  ", "abc", None, True, False, [], {}])
def test_junk_never_becomes_a_price(junk):
    """Postgres hands back "null" as text for a JSON null, and a hand-edited blob can hold
    anything. Every one of these has to fall THROUGH to the engine, not blank the card and not
    raise on the way."""
    assert drafts._bid_total(_draft(lump=junk, engine=41250)) == 41250.0


@pytest.mark.parametrize("zeroish", [0, 0.0, "0", "0.00", -1, "-250"])
def test_zero_and_negative_fall_through(zeroish):
    """proposal-review.js guards its own lump sum with `> 0`, because an unpriced tab totals 0 and
    the engine figure is the better answer there. Same guard, or the card shows $0 for a project
    that has a real number one field over."""
    assert drafts._bid_total(_draft(lump=zeroish, engine=41250)) == 41250.0
    assert drafts._bid_total(_draft(lump=zeroish)) is None


# ── D. the column has to be SELECTED, or none of the above reaches a card ────
# conftest's FakeTable ignores select() and returns whole rows, so it cannot see a missing
# projection — the resolver would be right and every card still blank. This fake honours the
# column list the way PostgREST does: a key absent from `cols` is absent from the row.
_ALIAS = re.compile(r"([A-Za-z_]\w*):data->>?([\w>'\-]+)")


class ProjectingTable:
    def __init__(self, store, name):
        self.store, self.name, self.cols = store, name, None
        self._filters = []
        self._negate = False

    def select(self, cols, *a, **k):
        self.cols = cols
        return self

    @property
    def not_(self):
        self._negate = True
        return self

    def is_(self, key, _v):
        self._filters.append((key, self._negate))
        self._negate = False
        return self

    def in_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        rows = self.store.get(self.name, [])
        for key, neg in self._filters:
            rows = [r for r in rows if (r.get(key) is not None) == bool(neg)]
        if self.name != "drafts":
            return type("R", (), {"data": list(rows), "count": len(rows)})()
        out = []
        for r in rows:
            proj = {}
            for part in (self.cols or "").split(","):
                part = part.strip()
                m = _ALIAS.match(part)
                if m:
                    alias, path = m.group(1), m.group(2)
                    node = r.get("data") or {}
                    for step in path.replace("'", "").split("->>"):
                        for leg in step.split("->"):
                            node = (node or {}).get(leg) if isinstance(node, dict) else None
                    # A `->>` extraction is TEXT. Reproducing that is the whole point: it is what
                    # makes a str reach _bid_total, and str > 0 raises.
                    proj[alias] = None if node is None else (
                        node if isinstance(node, (dict, list)) or "->>" not in part else str(node))
                elif part in r:
                    proj[part] = r[part]
            out.append(proj)
        return type("R", (), {"data": out, "count": len(out)})()


class ProjectingClient:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return ProjectingTable(self.store, name)


@pytest.fixture
def projected(monkeypatch):
    """_build_summaries against a client that only returns what was asked for."""
    def _run(blobs):
        store = {"drafts": [
            {"id": "d%d" % i, "owner_email": "kyle@wetreadwell.com", "deleted_at": None,
             "created_at": "2026-08-19", "updated_at": "2026-08-19", "data": b}
            for i, b in enumerate(blobs)], "draft_revisions": []}
        monkeypatch.setattr(drafts, "get_client", lambda: ProjectingClient(store))
        return drafts._build_summaries(trashed=False, limit=300)
    return _run


def test_the_fast_path_asks_postgres_for_the_lump_sum(projected):
    """THE regression. The list endpoint selects named JSON paths rather than the whole blob, so a
    resolver that reads a key nobody selected returns None for every row — the bug, restored, with
    every unit test above still green."""
    rows = projected([_draft(lump=17345)])
    assert rows[0]["total"] == 17345.0, (
        "the card is still blank: proposal_lump_sum is not in the select list")


def test_the_fast_path_and_the_full_read_agree(projected):
    """Two code paths build these cards — the JSON projection above, and _summary() on the whole
    blob when PostgREST does something unexpected. A project must not change price because the
    fast path fell over."""
    blobs = [_draft(lump=17345), _draft(lump=45629, engine=30960),
             _draft(engine=214471), _draft(lump=7861, engine=11573, beta_version=2), _draft()]
    fast = [r["total"] for r in projected(blobs)]
    slow = [drafts._summary({"id": "x", "data": b})["total"] for b in blobs]
    assert fast == slow, "fast path %r, full read %r" % (fast, slow)
    assert fast == [17345.0, 45629.0, 214471.0, 11573.0, None]


def test_the_beta_flag_survives_the_projection(projected):
    """The inversion needs polish_estimate.version, which the fast path only has as the scalar it
    already selects for the beta badge. Forgetting to pass it would silently take every beta
    project down the spreadsheet branch."""
    rows = projected([_draft(lump=7861, engine=11573, beta_version=2)])
    assert rows[0]["total"] == 11573.0, "the beta project is being priced off its stale lump sum"
    assert rows[0]["polish_beta"] is True
