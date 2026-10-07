"""The odd rules of Kyle's workbook: verified against what the oracle recorded, and against the list Kyle is sent.

docs/kyle-workbook-odd-rules.md names the rules in Kyle's estimate workbook that the v2 estimating tool
will reproduce on purpose (Hanz, 2026-10-07: match Kyle's sheet exactly). A list like that rots in two
ways: a rule is described wrongly, or the workbook moves and nobody notices. So each rule here has

  - CELLS and pieces of FORMULA TEXT (backend/tests/fixtures/oracle/odd_rules.json) that are read back
    out of the template: the rule is in those cells, written that way;
  - EVIDENCE: a check that reads the oracle's recorded cases and probes and decides whether the workbook
    really does what the rule says, arithmetic only, never a second copy of the sheet. The checks return
    the dollar figures the document quotes;
  - a place in the DOCUMENT: a heading with the rule's title, every one of its cells, every figure.

And each check is shown to be able to fail: the same check is run on evidence that has been falsified, and
must refuse it. A check that cannot go red is a sentence, not a test.

The checks use the recorded files only, so this runs in CI without HyperFormula.
"""
import copy
import json
import math
import re

import pytest

import _oracle_support as S
from _node import require_node
from test_workbook_formula_pins import _index

DOC = S.REPO / "docs" / "kyle-workbook-odd-rules.md"
GYP = ["Gyp (USG 1-8\")", "Gyp (USG N12ULTRA)", "Gyp (USG N25 1-4\")", "Gyp (GWorx SC190)", "Gyp (FR)"]
PRICED = ["Epoxy", "Polish", "Seal", "Seal (+Jnts)", "Epoxy blank", "Leveling"] + GYP


def roundup(x: float) -> int:
    """Excel's ROUNDUP(x, 0): away from zero, after twelve significant figures (what the page's plugin does)."""
    g = float("%.12g" % x)
    return math.ceil(g) if g >= 0 else -math.ceil(-g)


def usd(n) -> str:
    return "${:,.0f}".format(n) if float(n).is_integer() else "${:,.2f}".format(n)


def pct(n) -> str:
    return ("%.4f" % (n * 100)).rstrip("0").rstrip(".") + "%"


def num(n, places=2) -> str:
    return ("%.*f" % (places, n)).rstrip("0").rstrip(".")


class Ctx:
    """The recorded goldens, with the lookups the checks share."""

    def __init__(self, goldens, meta, profiles):
        self.g, self.meta, self.profiles = goldens, meta, profiles
        self._by = {tab: {v["id"]: v for v in g["vectors"]} for tab, g in goldens.items()}

    def vec(self, tab, vid):
        return self._by[tab][vid]

    def probe(self, tab, pid):
        found = [p for p in self.g[tab]["probes"] if p["id"] == pid]
        assert len(found) == 1, (tab, pid, "expected exactly one probe")
        return found[0]


# ── the checks: each returns the figures the document must quote ─────────────
def _bond_base(v):
    o, i = v["out"], v["in"]
    return (o["subTotal"] + o["gp"] + o["hardBid"] + o["superPto"] + o["softCosts"] + i.get("contingency", 0)
            + o["salesTax"] + o["remodelTax"] + o["taxes"] + i.get("fees", 0))


def check_bond_twice(c):
    for tab in PRICED:
        differing = 0
        for v in c.g[tab]["vectors"]:
            if not v["id"].startswith("bond/"):
                continue
            o, i = v["out"], v["in"]
            base = _bond_base(v)
            twice, once = roundup(base * i["bondPct"]), roundup((base - o["taxes"]) * i["bondPct"])
            assert o["bond"] == twice, (tab, v["id"], "the bond is not rate x a base that holds the taxes twice")
            differing += once != twice
        assert differing >= 6, (tab, "the cases must include ones where counting the taxes once gives another bond")
    v = c.vec("Polish", "bond/0.02/T1/R1")
    base = _bond_base(v)
    return {"bond": usd(v["out"]["bond"]), "once": usd(roundup((base - v["out"]["taxes"]) * 0.02)),
            "taxes": usd(v["out"]["taxes"])}


def check_leveling_lodging_eight(c):
    lev, gyp, pol = (c.vec(t, "lodging/one/local0") for t in ("Leveling", "Gyp (USG 1-8\")", "Polish"))
    people_days = sum(r["guys"] * r["days"] for r in lev["rows"])
    rate = lev["rows"][0]["rate"]
    assert lev["hoursPerDay"] == 10 and gyp["hoursPerDay"] == 10 and pol["hoursPerDay"] == 8
    nights = lev["out"]["lodgingQty"]
    assert nights == pytest.approx((lev["in"]["labor"] - lev["in"]["travelLabor"]) / rate / 8)
    assert nights == pytest.approx(people_days * 10 / 8), "ten hour days counted as eight: a quarter too many nights"
    assert gyp["out"]["lodgingQty"] == pytest.approx(people_days) and pol["out"]["lodgingQty"] == pytest.approx(people_days)
    first, second = c.probe("Leveling", "lodging-divisor")["steps"]
    assert first["got"]["E42"] == "10 hour days" and second["got"]["E42"] == "8 hour days"
    assert first["got"]["B61"] == second["got"]["B61"], "the divisor does not read the day-length cell"
    return {"nights": num(nights), "people-days": num(people_days)}


def check_leveling_escalation_left_out(c):
    v = c.vec("Leveling", "flags/mid/L1T1P1R0H0")
    o, i = v["out"], v["in"]
    parts = o["materialTotal"] + i["labor"] + i["tooling"] + i["travel"] + o["burden"]
    assert o["escalation"] > 0 and o["escPct"] == 0.05
    assert o["subTotal"] == parts and o["subTotal"] != parts + o["escalation"]
    assert o["burden"] == roundup((i["labor"] + o["escalation"]) * 0.12), "the escalation does reach the bid, through the burden"
    p = c.vec("Polish", "flags/mid/L1T1P1R0H0")
    po, pi = p["out"], p["in"]
    assert po["subTotal"] == po["materialTotal"] + pi["labor"] + po["escalation"] + po["burden"] + pi["tooling"] + pi["travel"]
    return {"escalation": usd(o["escalation"]), "without": usd(o["subTotal"]), "with": usd(o["subTotal"] + o["escalation"])}


def check_epoxy_gp_without_fees(c):
    def variants(tab, fees):
        o = c.vec(tab, "money/fees%d/cont0" % fees)["out"]
        top = roundup((o["subTotal"] + o["salesTax"] + fees) / (1 - o["gpPct"]))
        return o["gp"], top - roundup(o["subTotal"] + o["salesTax"]), top - roundup(o["subTotal"] + o["salesTax"] + fees)
    for fees in (1, 250, 1200, 5000):
        gp, without, with_ = variants("Epoxy", fees)
        assert gp == without and without != with_, ("Epoxy", fees)
        # every other tab takes the fees out of the subtraction as well, and says so in the same formula
        for tab in ("Polish", "Seal", "Seal (+Jnts)", "Epoxy blank", "Leveling") + tuple(GYP):
            gp, without, with_ = variants(tab, fees)
            assert gp == with_ and without != with_, (tab, fees)
    o = c.vec("Epoxy", "money/fees1200/cont0")["out"]
    top = roundup((o["subTotal"] + o["salesTax"] + 1200) / (1 - o["gpPct"]))
    return {"gp": usd(o["gp"]), "other": usd(top - roundup(o["subTotal"] + o["salesTax"] + 1200)), "fees": usd(1200)}


def check_gyp_escalation_always_five(c):
    for tab in GYP:
        for size in ("small", "mid", "big"):
            no = c.vec(tab, "flags/%s/L1T1P0R0H0" % size)
            yes = c.vec(tab, "flags/%s/L1T1P1R0H0" % size)
            labor = no["in"]["labor"]
            assert no["out"]["escalation"] == yes["out"]["escalation"] == roundup(labor * 0.05) > 0, (tab, size)
            assert no["out"]["subTotal"] == yes["out"]["subTotal"]
    for size in ("mid", "big"):
        no, yes = c.vec("Polish", "flags/%s/L1T1P0R0H0" % size), c.vec("Polish", "flags/%s/L1T1P1R0H0" % size)
        assert no["out"]["escalation"] == 0 and yes["out"]["escalation"] == roundup(no["in"]["labor"] * 0.05)
    mid = c.vec("Gyp (USG 1-8\")", "flags/mid/L1T1P0R0H0")
    return {"escalation": usd(mid["out"]["escalation"]), "labor": usd(mid["in"]["labor"])}


def check_gyp_mat_shipping_truckload(c):
    for tab in GYP:
        below, at, above = c.probe(tab, "sound-mat-truckload")["steps"]
        truck = below["got"]["H36"] + 0
        assert below["got"]["B36"] == truck - 1 and at["got"]["B36"] == truck and above["got"]["B36"] == truck + 1
        assert below["got"]["E40"] == roundup(below["got"]["E36"] * 0.1) > 0, tab
        assert at["got"]["E40"] == above["got"]["E40"] == 0, (tab, "waived at a truckload, not only above it")
    below, at, _ = c.probe("Gyp (USG 1-8\")", "sound-mat-truckload")["steps"]
    return {"charged": usd(below["got"]["E40"]), "rolls below": str(below["got"]["B36"]), "truckload": str(at["got"]["B36"]),
            "mat": usd(below["got"]["E36"])}


def check_gyp_bags_fractional(c):
    for tab in GYP:
        (step,) = c.probe(tab, "bags-fractional-sand-follows")["steps"]
        g = step["got"]
        sand_lbs = g["P52" if tab == "Gyp (FR)" else "Q52"]
        for sf, yield_, bags in ((g["F23"], g["J23"], g["B23"]), (g["F24"], g["J24"], g["B24"]), (g["F25"], g["J25"], g["B25"])):
            assert bags == pytest.approx(sf / yield_ * (1 + g["G18"])) and bags != int(bags), (tab, "bags are never rounded")
        assert g["H33"] == pytest.approx(g["B23"] + g["B24"] + g["B25"])
        assert g["B33"] == pytest.approx((sand_lbs * g["H33"] / 2000) * (1 + g["G19"])), (tab, "sand follows the fractional bags")
    g = c.probe("Gyp (USG 1-8\")", "bags-fractional-sand-follows")["steps"][0]["got"]
    return {"bags": num(g["B23"]), "sf": "1,000", "tons": num(g["B33"])}


def check_leveling_travel_hour(c):
    yes, no = c.probe("Leveling", "travel-hour-when-local")["steps"]
    assert yes["got"]["B4"] == "Yes" and no["got"]["B4"] == "No"
    assert yes["got"]["B48"] == no["got"]["B48"] == 1 and yes["got"]["D48"] == no["got"]["D48"] > 0
    assert yes["got"]["D48"] == pytest.approx(yes["got"]["A48"] * yes["got"]["B48"] * yes["got"]["C48"])
    (epoxy,), (polish,) = (c.probe(t, "travel-hours-when-local")["steps"] for t in ("Epoxy", "Polish"))
    assert epoxy["got"]["B4"] == polish["got"]["B4"] == "Yes" and epoxy["got"]["D52"] == 0 and polish["got"]["D44"] == 0
    return {"charge": usd(yes["got"]["D48"]), "people": num(yes["got"]["A48"]), "rate": usd(yes["got"]["C48"])}


def check_leveling_overage_powders(c):
    none, powder, sand = c.probe("Leveling", "overage-powders-only")["steps"]
    assert none["got"]["D38"] == 0 and powder["got"]["D38"] == 100 and sand["got"]["D38"] == 0
    assert powder["got"]["D37"] - none["got"]["D37"] == 1000 and sand["got"]["D37"] - none["got"]["D37"] == 1000
    _, liquids, cove = c.probe("Epoxy blank", "overage-all-rows")["steps"]
    assert liquids["got"]["D38"] == cove["got"]["D38"] == 60, "Epoxy blank takes it on every row"
    return {"powder": usd(powder["got"]["D38"]), "sand": usd(sand["got"]["D38"]), "blank": usd(liquids["got"]["D38"])}


def check_ship_tiers_inclusive_gp_strict(c):
    for tab in ("Epoxy", "Epoxy blank", "Leveling"):
        for edge in (5000, 10000):
            below, at, above = (c.vec(tab, "edge/shipPct/%d/%s" % (edge, off))["out"]["shipPct"] for off in ("-1", "0", "+1"))
            assert at == below != above, (tab, edge, "a material total ON the edge is charged the tier below it")
        for edge in (6500, 15000, 22500, 32500):
            below, at, above = (c.vec(tab, "edge/gpPct/%d/%s" % (edge, off))["out"]["gpPct"] for off in ("-1", "0", "+1"))
            assert at == above != below, (tab, edge, "a sub-total ON the edge is on the next band")
    def e(ladder, key, edge, off):
        return c.vec("Epoxy", "edge/%s/%d/%s" % (ladder, edge, off))["out"][key]
    return {"ship at": pct(e("shipPct", "shipPct", 5000, "0")), "ship above": pct(e("shipPct", "shipPct", 5000, "+1")),
            "dollars at": usd(e("shipPct", "shipping", 5000, "0")), "dollars above": usd(e("shipPct", "shipping", 5000, "+1")),
            "gp at": pct(e("gpPct", "gpPct", 6500, "0")), "gp below": pct(e("gpPct", "gpPct", 6500, "-1"))}


def check_cove_aggregate_system_1(c):
    one, two, both = c.probe("Epoxy", "cove-aggregate-system-1")["steps"]
    quartz, silica = one["got"]["AF126"], two["got"]["AF126"]
    assert one["got"]["A22"] == two["got"]["A26"] == both["got"]["A22"] == both["got"]["A26"]
    assert quartz == 300 and silica == 100 and both["got"]["AF126"] == quartz
    assert two["set"]["W145"] == 1 and two["set"]["W148"] == 3 and two["got"]["AE126"] == 100
    return {"follows System 1": usd(silica), "if System 2": usd(quartz)}


CHECKS = {
    "bond-twice": check_bond_twice,
    "leveling-lodging-eight": check_leveling_lodging_eight,
    "leveling-escalation-left-out": check_leveling_escalation_left_out,
    "epoxy-gp-without-fees": check_epoxy_gp_without_fees,
    "gyp-escalation-always-five": check_gyp_escalation_always_five,
    "gyp-mat-shipping-truckload": check_gyp_mat_shipping_truckload,
    "gyp-bags-fractional": check_gyp_bags_fractional,
    "leveling-travel-hour": check_leveling_travel_hour,
    "leveling-overage-powders": check_leveling_overage_powders,
    "ship-tiers-inclusive-gp-strict": check_ship_tiers_inclusive_gp_strict,
    "cove-aggregate-system-1": check_cove_aggregate_system_1,
}


def check_saved_values_are_old(c):
    sc = c.meta["selfCheck"]["sheets"]
    assert "Polish!C37: 33 -> 32.2" in sc["Polish"]["laborRatesPutBack"]
    assert "Leveling!C44: 33.66 -> 32.52" in sc["Leveling"]["laborRatesPutBack"]
    assert sc["Polish"]["matchedAsSaved"] < sc["Polish"]["compared"] == sc["Polish"]["matched"]
    return {"polish rate": usd(33), "polish saved": "$32.20", "leveling rate": "$33.66", "leveling saved": "$32.52"}


def check_gyp_hard_bid_unwired(c):
    assert c.profiles["sheets"]["Gyp (USG 1-8\")"]["fixed"]["hardBidPct"]["value"] is None, "B73 is empty"
    pairs = 0
    for tab in GYP:
        for size in ("small", "mid", "big"):
            for n in range(16):                       # every setting of the other four questions
                local, taxable, wage, remodel = ((n >> i) & 1 for i in range(4))
                stem = "flags/%s/L%dT%dP%dR%dH" % (size, local, taxable, wage, remodel)
                off, on = dict(c.vec(tab, stem + "0")["out"]), dict(c.vec(tab, stem + "1")["out"])
                assert off.pop("answers")["hardBid"] is False and on.pop("answers")["hardBid"] is True
                assert off == on, (tab, stem, "Hard Bid? changed an answer on a Gyp tab")
                pairs += 1
    assert pairs == 5 * 3 * 16
    return {}


def check_gyp_fr_own_answers(c):
    sheets = c.profiles["sheets"]
    for flag in ("local", "taxable"):
        assert "value" in sheets["Gyp (FR)"]["flags"][flag], "FR holds its own answer"
        for tab in GYP[1:4]:
            assert sheets[tab]["flags"][flag]["formula"].endswith("!" + sheets[tab]["flags"][flag]["addr"]), tab
    return {}


def check_seal_extra_rung(c):
    seal = [e["at"] for l in c.meta["ladders"]["Seal"] if l["cell"] == "gpPct" for e in l["edges"]]
    polish = [e["at"] for l in c.meta["ladders"]["Polish"] if l["cell"] == "gpPct" for e in l["edges"]]
    assert seal == polish + [42500]
    at, above = (c.vec("Seal", "edge/gpPct/42500/%s" % off)["out"]["gpPct"] for off in ("0", "+1"))
    assert at == above == 0.28 and c.vec("Seal", "edge/gpPct/42500/-1")["out"]["gpPct"] == 0.3
    return {"edge": usd(42500), "below": pct(0.3), "above": pct(0.28)}


ALSO = {
    "saved-values-are-old": check_saved_values_are_old,
    "gyp-hard-bid-unwired": check_gyp_hard_bid_unwired,
    "gyp-fr-own-answers": check_gyp_fr_own_answers,
    "seal-extra-rung": check_seal_extra_rung,
}


# ── fixtures ─────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def rules():
    return json.loads((S.ORACLE / "odd_rules.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ctx():
    require_node()
    profiles = S.profiles()
    return Ctx({t: S.load_golden(profiles["sheets"][t]["slug"]) for t in profiles["priced"]}, S.load_meta(), profiles)


@pytest.fixture(scope="module")
def doc():
    return DOC.read_text(encoding="utf-8")


def sections(text):
    """{title: section text} for every `### N. Title` heading of the document."""
    out, title, buf = {}, None, []
    for line in text.splitlines():
        m = re.match(r"^###\s+(?:\d+\.\s+)?(.+?)\s*$", line)
        if m or line.startswith("## "):
            if title is not None:
                out[title] = "\n".join(buf)
            title, buf = (m.group(1) if m else None), []
        elif title is not None:
            buf.append(line)
    if title is not None:
        out[title] = "\n".join(buf)
    return out


EXPECTED = ["bond-twice", "leveling-lodging-eight", "leveling-escalation-left-out", "epoxy-gp-without-fees",
            "gyp-escalation-always-five", "gyp-mat-shipping-truckload", "gyp-bags-fractional", "leveling-travel-hour",
            "leveling-overage-powders", "ship-tiers-inclusive-gp-strict", "cove-aggregate-system-1"]


# ── the tests ────────────────────────────────────────────────────────────────
def test_the_list_holds_the_eleven_rules_kyle_is_to_be_sent(rules):
    assert [r["id"] for r in rules["rules"]] == EXPECTED
    assert set(CHECKS) == set(EXPECTED)
    assert [r["id"] for r in rules["also"]] == list(ALSO)
    titles = [r["title"] for r in rules["rules"]] + [r["title"] for r in rules["also"]]
    assert len(set(titles)) == len(titles)


def test_every_cell_a_rule_names_exists_and_the_formula_says_what_the_rule_says(rules):
    claims = 0
    empty_on_purpose = {"Gyp (USG 1-8\")!B73"}          # the Hard Bid rate nobody ever typed
    for rule in rules["rules"] + rules["also"]:
        for ref in rule["cells"]:
            tab, addr = ref.rsplit("!", 1)
            kind = _index(tab).get(addr, ("empty", None))[0]
            assert kind != "empty" or ref in empty_on_purpose, (rule["id"], ref, "names an empty cell")
        for claim in rule.get("claims", []):
            kind, text = _index(claim["tab"]).get(claim["cell"], ("empty", None))
            assert kind == "formula", (rule["id"], claim)
            for piece in claim.get("contains", []):
                assert piece in text, (rule["id"], claim["tab"], claim["cell"], "the formula no longer holds", piece, text)
            for piece in claim.get("notContains", []):
                assert piece not in text, (rule["id"], claim["tab"], claim["cell"], "the formula now holds", piece, text)
            claims += 1
    assert claims >= 25


def test_the_cove_cells_all_key_on_system_1_and_none_on_system_2(rules):
    rule = next(r for r in rules["rules"] if r["id"] == "cove-aggregate-system-1")
    for ref in rule["cells"]:
        tab, addr = ref.rsplit("!", 1)
        text = _index(tab)[addr][1]
        assert "$A$22" in text and "$A$26" not in text, ref


@pytest.mark.parametrize("rule_id", EXPECTED)
def test_the_workbook_really_does_what_the_rule_says(ctx, rule_id):
    figures = CHECKS[rule_id](ctx)
    assert figures, "a rule that quotes no figure is not shown to Kyle by a number he can check"


@pytest.mark.parametrize("rule_id", list(ALSO))
def test_the_things_also_found_hold_too(ctx, rule_id):
    ALSO[rule_id](ctx)


def _falsified(ctx, rule_id):
    """A copy of the recorded evidence in which the rule is NOT true."""
    bad = Ctx(copy.deepcopy(ctx.g), ctx.meta, ctx.profiles)

    def vec_edit(tab, vid, fn):
        fn(bad.vec(tab, vid))

    def probe_edit(tab, pid, fn):
        fn(bad.probe(tab, pid))

    if rule_id == "bond-twice":
        for tab in PRICED:
            for v in bad.g[tab]["vectors"]:
                if v["id"].startswith("bond/"):
                    v["out"]["bond"] -= 7
    elif rule_id == "leveling-lodging-eight":
        vec_edit("Leveling", "lodging/one/local0", lambda v: v["out"].__setitem__("lodgingQty", v["out"]["lodgingQty"] * 0.8))
    elif rule_id == "leveling-escalation-left-out":
        vec_edit("Leveling", "flags/mid/L1T1P1R0H0", lambda v: v["out"].__setitem__("subTotal", v["out"]["subTotal"] + v["out"]["escalation"]))
    elif rule_id == "epoxy-gp-without-fees":
        vec_edit("Epoxy", "money/fees1200/cont0", lambda v: v["out"].__setitem__("gp", v["out"]["gp"] - 1200))
    elif rule_id == "gyp-escalation-always-five":
        vec_edit("Gyp (USG N25 1-4\")", "flags/mid/L1T1P0R0H0", lambda v: v["out"].__setitem__("escalation", 0))
    elif rule_id == "gyp-mat-shipping-truckload":
        probe_edit("Gyp (USG 1-8\")", "sound-mat-truckload", lambda p: p["steps"][1]["got"].__setitem__("E40", 1000))
    elif rule_id == "gyp-bags-fractional":
        probe_edit("Gyp (FR)", "bags-fractional-sand-follows", lambda p: p["steps"][0]["got"].__setitem__("B23", 26))
    elif rule_id == "leveling-travel-hour":
        probe_edit("Leveling", "travel-hour-when-local", lambda p: p["steps"][0]["got"].__setitem__("D48", 0))
    elif rule_id == "leveling-overage-powders":
        probe_edit("Leveling", "overage-powders-only", lambda p: p["steps"][2]["got"].__setitem__("D38", 100))
    elif rule_id == "ship-tiers-inclusive-gp-strict":
        vec_edit("Epoxy", "edge/shipPct/5000/0", lambda v: v["out"].__setitem__("shipPct", v["out"]["shipPct"] - 0.04))
    elif rule_id == "cove-aggregate-system-1":
        probe_edit("Epoxy", "cove-aggregate-system-1", lambda p: p["steps"][1]["got"].__setitem__("AF126", 300))
    else:
        raise AssertionError("no falsification written for " + rule_id)
    return bad


@pytest.mark.parametrize("rule_id", EXPECTED)
def test_each_check_refuses_evidence_that_says_otherwise(ctx, rule_id):
    with pytest.raises(AssertionError):
        CHECKS[rule_id](_falsified(ctx, rule_id))


def test_the_document_carries_every_rule_with_its_cells_and_its_figures(rules, ctx, doc):
    found = sections(doc)
    for rule in rules["rules"]:
        assert rule["title"] in found, "docs/kyle-workbook-odd-rules.md has no heading '%s'" % rule["title"]
        text = found[rule["title"]]
        for ref in rule["cells"]:
            assert "`" + ref + "`" in text or ref in text, (rule["id"], "the document does not mention", ref)
        for label, figure in CHECKS[rule["id"]](ctx).items():
            assert figure in text, (rule["id"], "the document must quote %r (%s)" % (figure, label))
    for rule in rules["also"]:
        assert rule["title"] in found, rule["title"]
        text = found[rule["title"]]
        for ref in rule["cells"]:
            assert ref in text, (rule["id"], ref)
        for label, figure in ALSO[rule["id"]](ctx).items():
            assert figure in text, (rule["id"], "the document must quote %r (%s)" % (figure, label))


def test_the_document_keeps_to_plain_words(doc):
    assert "—" not in doc and "–" not in doc, "no em or en dashes in words people read"
