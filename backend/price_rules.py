"""THE PRICE RULE, the document's half. Its twin is frontend/js/price-lines-core.js (TWPrice).

Hanz, 2026-09-25, in his own words:

    "Remodel Tax should be triggered by remodel tax in the estimate form. Taxable is where base
     bid and other options are taxable or not."
    "If remodel and material sales tax is on then there should be both. If remodel is only the
     one on then only remodel tax."
    "if one of the taxes is set to yes then broken out should be the default option in the
     proposal tool."

So there are two questions and they have two different owners:

  * WHETHER there is tax is the ESTIMATE SHEET's answer, per priced tab: Taxable? (Epoxy!B6, a
    gyp tab's B8) decides material sales tax, Remodel Tax? (D6 / D8) decides remodel tax. The
    base bid and every option are asked separately, each off its own tab.
  * HOW it is shown is the proposal's TAX control, and it only has two answers: "One line" or
    "Broken out".

Broken out itemises: the pre-tax line with no bracket wording, a Material Sales Tax row only when
the tab is taxable, a Remodel Tax row only when remodel is on, then the Total. The rows add up —
Hanz's own example is "$6,767 – Epoxy flooring as described above / $72 – Material Sales Tax /
$6,839 – Total". The bid is TAX-INCLUSIVE (D88 already contains both taxes), so the taxes are
backed OUT of the total using the sheet's own tax cells (D80 / D81 per tab), never added on top
and never guessed as "total minus a rate": sales tax compounds through markup, so only the cell
knows what it is.

One line carries the whole bid and says which taxes are in it:
  taxable + remodel -> "(Remodel Tax AND material sales tax INCLUDED)"
  taxable only      -> "(material sales tax INCLUDED)"
  remodel only      -> "(Remodel Tax INCLUDED)"
  neither           -> "(tax exempt)"

WHY TWO FILES AND ONE TEST. The editor has to show the estimator this figure before anything is
generated, and the document has to print it from a payload that may have been frozen weeks ago;
neither side can borrow the other's code. So the rule is written once per language, kept
deliberately small and free of the template, and test_price_rules_parity.py EXECUTES both over the
same matrix and demands the same answer. A comment promising the two agree is worth nothing.

THE MARKERS. An edited price line keeps the estimator's words, but its dollar amount and tax
wording stay live: where the line still carried today's computed amount and tax phrase verbatim,
the editor stores them as the two markers below, and both halves substitute today's values when
they render (`resolve_line`). A line that carries a DIFFERENT dollar figure keeps it — the
estimator is warned in the editor and again at Send, and then it is his to send.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Optional

AMOUNT_MARK = "⟦amount⟧"   # ⟦amount⟧
TAX_MARK = "⟦tax⟧"         # ⟦tax⟧

PHRASE_BOTH = "(Remodel Tax AND material sales tax INCLUDED)"
PHRASE_MATERIAL = "(material sales tax INCLUDED)"
PHRASE_REMODEL = "(Remodel Tax INCLUDED)"
PHRASE_NONE = "(tax exempt)"
# Every wording this tool prints for the tax, longest first so a shorter one is never found inside
# a longer one (TWPrice.KNOWN_PHRASES, in the same order).
KNOWN_PHRASES = (PHRASE_BOTH, PHRASE_REMODEL, PHRASE_MATERIAL, PHRASE_NONE)

ONE_LINE = "ONE_LINE"
BROKEN_OUT = "BROKEN_OUT"

_BROKEN_ALIASES = {"BROKEN_OUT", "BROKEN OUT", "BROKENOUT", "ITEMIZED", "BREAKOUT"}

# ⟦tax⟧, with the one space or tab in front of it that belongs to it: a phrase that comes back
# empty (Broken out) takes that space with it, so the line does not end in a stray blank.
_TAX_MARK_RE = re.compile(r"([ \t]?)" + re.escape(TAX_MARK))


def _cents(v: Any) -> int:
    """A dollar figure as whole cents. Money is added and subtracted in integers: the document
    prints to the cent, and the rows have to sum at that precision, not within a float's error."""
    try:
        return int(round(float(str(v).replace(",", "").replace("$", "").strip() or 0) * 100))
    except (TypeError, ValueError):
        return 0


def flag(value: Any, fallback: bool) -> bool:
    """An estimate flag as a bool. A payload saved before the flags travelled has none, and the
    sheet's own figure answers for it: its sales tax cell is IF(Taxable?="no", 0, ...) and its
    remodel cell IF(Remodel?="yes", ...), so a non-zero figure IS a Yes."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip():
        s = value.strip().lower()
        if s in ("yes", "y", "true", "1"):
            return True
        if s in ("no", "n", "false", "0"):
            return False
    return bool(fallback)


def phrase_for(taxable: bool, remodel_on: bool) -> str:
    """The one-line wording, from the two flags."""
    if taxable and remodel_on:
        return PHRASE_BOTH
    if taxable:
        return PHRASE_MATERIAL
    if remodel_on:
        return PHRASE_REMODEL
    return PHRASE_NONE


def _known(v: Any) -> bool:
    return v is not None and not (isinstance(v, str) and not v.strip())


def tax_rule(total: Any, sales_tax: Any = None, remodel: Any = None, *,
             taxable: Any = None, remodel_on: Any = None, broken: bool = False) -> dict:
    """THE RULE for one priced system (the base, or one option), off its own tab's figures.

    Returns every figure in CENTS plus which rows print:
      base         the amount on the system's own line
      phrase       the bracket wording after it ("" when broken out)
      material     a Material Sales Tax row prints
      remodel      a Remodel Tax row prints
      total        a Total row prints

    With no flag, the figure answers (see `flag`). With no flag AND no sales-tax figure at all —
    a hand-built payload, a room from before the tab snapshot carried one — nothing says the job
    is exempt, so it is read as taxable, which is what every such document printed before.
    """
    t, s, r = _cents(total), _cents(sales_tax), _cents(remodel)
    tx = flag(taxable, (s > 0) if _known(sales_tax) else True)
    rm = flag(remodel_on, r > 0)
    out = {"broken": bool(broken), "taxable": tx, "remodel_on": rm,
           "total_cents": t, "sales_cents": s, "remodel_cents": r}
    if broken:
        base = t - (s if tx else 0) - (r if rm else 0)
        out.update(base_cents=max(0, base), phrase="", material=tx, remodel=rm, total=True)
    else:
        out.update(base_cents=t, phrase=phrase_for(tx, rm), material=False, remodel=False,
                   total=False)
    return out


def layout_is_broken(tax_layout: Any, tax_inclusion: Any, *, free_rows: bool,
                     taxable: bool, remodel_on: bool) -> bool:
    """Broken out or one line, for a payload.

    `tax_layout` is the new control's answer, and when present it is the answer. A payload
    composed before it existed carries only the old three-way `tax_inclusion`, which is read by
    what it PRINTED, so a re-render of an untouched payload keeps its layout:

      * "Sales tax broken out" itemised on every template -> Broken out.
      * "Included" and "Tax exempt" printed one line on the templates whose tax rows sit in a
        {{#tax_breakout}} region (the Direct files) -> One line; exempt now comes from the sheet.
      * The GC and Gyp files author their tax rows as plain paragraphs, so they itemised whatever
        that box said; the choice was never theirs, and the new default answers for it — Broken
        out when a tax applies, one line when none does.
    """
    lay = str(tax_layout or "").strip().upper()
    if lay == BROKEN_OUT:
        return True
    if lay == ONE_LINE:
        return False
    legacy = str(tax_inclusion if tax_inclusion is not None else "INCLUDED").strip().upper()
    if legacy in _BROKEN_ALIASES:
        return True
    if free_rows:
        return bool(taxable or remodel_on)
    return False


def resolve_line(text: Any, amount: Optional[str], phrase: Optional[str]) -> str:
    """An edited line with today's amount and tax wording put back where its markers are."""
    s = str(text if text is not None else "")
    if AMOUNT_MARK in s:
        s = s.replace(AMOUNT_MARK, str(amount or ""))
    if TAX_MARK in s:
        ph = str(phrase or "")
        s = _TAX_MARK_RE.sub(lambda m: (m.group(1) + ph) if ph else "", s)
    return s


_BASE_TAX_TOKEN_RE = re.compile(r"\{\{\s*base_tax_phrase\s*\}\}")


def alt_flooring_phrase(row_text: Any, base_phrase: Any = "") -> str:
    """The tax wording the ALTERNATE SYSTEM block's flooring row prints: whatever the TEMPLATE puts
    there. Epoxy Direct writes "(material sales tax INCLUDED)" in so many words; Polish and Combo
    Direct print the base's own {{base_tax_phrase}} in that place. `row_text` is the template's row
    ("{{alternate.lump_sum_formatted}} – Flooring as described above …"), `base_phrase` today's
    base wording.

    It is the line's PHRASE, the thing its ⟦tax⟧ marker resolves to. Undeclared, the box sweep
    turned the wording into a marker that resolved to nothing, and the customer's document lost
    "(material sales tax INCLUDED)" on any keystroke in the price box (review of fix 7, finding 1).
    Twin: TWPrice.altFlooringPhrase."""
    t = str(row_text if row_text is not None else "")
    if _BASE_TAX_TOKEN_RE.search(t):
        return str(base_phrase or "")
    for ph in KNOWN_PHRASES:
        if ph in t:
            return ph
    return ""


def extras_for(pov: Mapping[str, Any], key: str) -> tuple[list, list]:
    """The lines the estimator typed ABOVE and BELOW one price line, as two lists of strings.

    Their own lines, not text inside the line they sit next to: they print as separate
    paragraphs, and typing one never freezes the price line beside it."""
    def one(bucket):
        m = pov.get(bucket) if isinstance(pov, Mapping) else None
        v = m.get(key) if isinstance(m, Mapping) else None
        return [str(x) for x in v] if isinstance(v, list) else []
    return one("before"), one("after")


# ── THE PRICE BOX'S BULLETS: Kyle's REBID layout ─────────────────────────────────────────────
# Hanz, 2026-09-25, choosing it with the 2026-07-16 "no bullets in the pricing" rule in front of
# him: the price box reads like Kyle's hand-made "Nickell RC Sustainment REBID" proposal. Every
# money line (the base, its tax rows and Total, each option and its own tax rows and Total, the
# manual and combo lines, the alternate's amounts) carries the template's own red square (the
# PRICE list, numId 3, level 0); a line typed under or over one of them is its sub-line and
# carries the hollow "o" (level 1). Headings ("Base Bid", "Options:", the alternate's name) and
# blank lines carry nothing. Then: "fix the indents and the bullets now" (2026-09-26) — what the
# estimator sets with the ribbon on any of those lines beats the default, and prints.
#
# ONE RULE, TWO LANGUAGES, like the tax rule above: this half says what a line prints when the
# draft states nothing about it and how a stated override combines with that; its twin is
# TWPrice.lineDefault / resolveLineProps in price-lines-core.js, and test_price_bullets.py runs
# both over the same matrix.
#
# A RESOLVED line is {"bullet": True, "level": 0|1} or {"bullet": False, "indent": twips}. A
# bulleted line states no indent of its own: the list level places it, exactly as Kyle's numbering
# defines — square at 0 and text at 288 twips on level 0, "o" at 1080 and text at 1440 on level 1
# (every template defines numId 3 that way; test_price_bullets.py reads them to be sure). An
# unbulleted line states where its text starts. Switching a bullet off does not move the words
# (the same rule the WORK rows follow, proposal_writer rule 1).
LEVEL_LEFT_TW = (288, 1440)
LEVEL_HANG_TW = (288, 360)
LINE_INDENT_STEP_TW = 288
LINE_INDENT_MAX_TW = 2880
# Lines that are headings, never money: no bullet unless the estimator asks for one.
HEADING_LINE_KEYS = frozenset({"heading_base", "heading_options", "alt_name"})


def clean_line_props(raw: Any) -> dict:
    """One stored override as {bullet?: bool, level?: 0|1, indent?: 0..2880 twips}; anything else
    dropped. Never raises — a hand-built or stale draft must not 500 a render."""
    if not isinstance(raw, Mapping):
        return {}
    out: dict = {}
    b = raw.get("bullet")
    if isinstance(b, bool):
        out["bullet"] = b
    lv = raw.get("level")
    if isinstance(lv, int) and not isinstance(lv, bool) and lv in (0, 1):
        out["level"] = lv
    ind = raw.get("indent")
    if isinstance(ind, (int, float)) and not isinstance(ind, bool):
        try:
            out["indent"] = int(max(0, min(LINE_INDENT_MAX_TW, round(float(ind)))))
        except (TypeError, ValueError, OverflowError):
            pass
    return out


def line_default(key: Any, pos: Optional[str] = None) -> dict:
    """What one PRICE line prints when the draft states nothing about it (REBID).

    `pos` is None for the line itself and "before" / "after" for a line typed above / below it."""
    k = str(key or "")
    if k in HEADING_LINE_KEYS:
        return {"bullet": False, "indent": 0}
    if pos in ("before", "after"):
        return {"bullet": True, "level": 1}
    return {"bullet": True, "level": 0}


def line_intent(key: Any, pos: Optional[str] = None, override: Any = None) -> dict:
    """The line as the estimator has set it, blank or not: {bullet, level, indent} all filled in —
    `indent` is where the TEXT starts, so for a bulleted line the level's own left edge."""
    d = line_default(key, pos)
    o = clean_line_props(override)
    level = o.get("level", d.get("level", 0))
    bullet = o.get("bullet", d["bullet"])
    if bullet:
        return {"bullet": True, "level": level, "indent": LEVEL_LEFT_TW[level]}
    if "indent" in o:
        indent = o["indent"]
    elif d["bullet"]:
        indent = LEVEL_LEFT_TW[level]            # switched off: the words stay where they were
    else:
        indent = d.get("indent", 0)
    return {"bullet": False, "level": level, "indent": indent}


def resolve_line_props(key: Any, pos: Optional[str] = None, text: Any = "",
                       override: Any = None) -> dict:
    """What one PRICE line PRINTS: the default, the estimator's override on top, and a BLANK line
    never carries a bullet — Word would print a lone square on an empty list paragraph, and the
    editor draws none (Kyle's own test click under the options was exactly that, REBID hazard 2)."""
    it = line_intent(key, pos, override)
    if it["bullet"] and str(text if text is not None else "").strip():
        return {"bullet": True, "level": it["level"]}
    return {"bullet": False, "indent": it["indent"]}


def line_props_for(pov: Any, key: str, pos: Optional[str] = None,
                   index: Optional[int] = None) -> dict:
    """The estimator's stored override for one line, or {}: `line_props[key]` for the line itself,
    `before_props[key][i]` / `after_props[key][i]` for the i-th line typed above / below it."""
    if not isinstance(pov, Mapping):
        return {}
    if pos is None:
        m = pov.get("line_props")
        return clean_line_props(m.get(key)) if isinstance(m, Mapping) else {}
    m = pov.get(pos + "_props")
    rows = m.get(key) if isinstance(m, Mapping) else None
    if not isinstance(rows, list) or index is None or not (0 <= index < len(rows)):
        return {}
    return clean_line_props(rows[index])
