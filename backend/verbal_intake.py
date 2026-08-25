"""Verbal intake for the Polish beta: an estimator talks, and the form fills in.

Hanz, 2026-08-25: the estimator says or types what they have, a cheat sheet tells them what is
needed, the AI fills what it can and asks ONCE for what is missing, and if they still do not have
it they carry on. Reaching the normal intake form stays optional.

WHY THIS IS ITS OWN MODULE AND NOT ANOTHER BLOCK IN main.py. Everything below is a pure function
over a transcript and a dict — no request, no subprocess, no Supabase — so the rules that decide
whether a price flag is allowed to move can be tested directly, thousands of times, without a
Claude call. main.py keeps the one line that runs the CLI.

THE THREE RULES THAT MATTER, in the order they cost money if broken:

  1. **A MONEY FLAG NEEDS EVIDENCE.** The five condition toggles — local, hard_bid,
     prevailing_wage, taxable, remodel_tax — each change what the job is priced at. An extraction
     model asked "is this prevailing wage?" will happily infer one from a school district in the
     project name. So a flag is only accepted when the model returns a VERBATIM QUOTE and the
     server can still find that quote in the transcript it sent. The model cannot manufacture
     evidence it did not receive; anything it cannot quote is dropped and reported as unsupported,
     which is the estimator's cue to answer it themselves.

  2. **NOTHING HERE MAY WRITE A COUNTY.** `county_remodel_rate` carries a live hazard the rest of
     the app depends on: null means "nobody said which county" and falls back to the Kansas state
     rate, while an explicit 0 means "we know, and it is nothing" (Missouri exempts remodel
     labour). A guessed 0 is indistinguishable from a researched one and silently underprices the
     job. The county picker on the intake form is the only thing allowed to set those four keys,
     so they are stripped here unconditionally rather than merely left out of the prompt.

  3. **OMIT, NEVER NULL-FILL.** Copied from leads.py's extraction prompt rather than main.py's
     autofill one. `_AUTOFILL_SYSTEM_PROMPT` is explicitly told never to abstain and to apply
     conservative defaults, which is exactly backwards for a feature whose whole job is knowing
     what it does not have.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional

# The plain text the estimator can dictate into. Everything else on the intake form is either
# derived (city_state), picked from a curated list (county), or a takeoff number nobody says out
# loud accurately enough to price from.
TEXT_FIELDS = (
    "project_name", "address", "city", "state", "zip",
    "contact_name", "contact_email", "bid_date",
)

# The five toggles that move money. Each needs a quote — see rule 1 above.
MONEY_CONDITIONS = ("local", "hard_bid", "prevailing_wage", "taxable", "remodel_tax")

# Never written from AI, at any confidence, for any reason. See rule 2.
BANNED_KEYS = ("county", "county_tax_rate", "county_remodel_rate", "county_notes")

# A quote has to be long enough to actually be evidence. "yes" appears in almost every transcript
# and would unlock any flag; two words and eight characters is the smallest thing that can carry a
# claim ("hard bid", "no sales tax").
_MIN_QUOTE_WORDS = 2
_MIN_QUOTE_CHARS = 8

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")
_ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")


def _txt(v: Any) -> str:
    return "" if v is None else str(v).strip()


def evidence_key(text: Any) -> str:
    """The form a quote and the transcript are compared in.

    Case, punctuation and run-length of whitespace are all dropped, because dictation and the
    model disagree about every one of them: the Web Speech API punctuates by guesswork, and a
    model asked to quote will normally re-punctuate what it read. What survives is the sequence of
    words, which is what actually makes a quote evidence.

    This deliberately does NOT stem, fold plurals, or match approximately. A gate that accepts a
    paraphrase is not a gate — the model would be free to write down what it inferred and have it
    accepted as what it heard."""
    t = unicodedata.normalize("NFKC", _txt(text)).casefold()
    t = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in t)
    return " ".join(t.split())


def quote_is_supported(quote: Any, transcript: Any) -> bool:
    """True when the transcript really contains this quote."""
    q = evidence_key(quote)
    if len(q) < _MIN_QUOTE_CHARS or len(q.split()) < _MIN_QUOTE_WORDS:
        return False
    return q in evidence_key(transcript)


def _clean_state(v: Any) -> str:
    s = _txt(v).upper()
    return s if len(s) == 2 and s.isalpha() else ""


def _clean_field(key: str, raw: Any) -> str:
    v = _txt(raw)
    if not v:
        return ""
    if key == "state":
        return _clean_state(v)
    if key == "bid_date":
        # A date the estimator cannot see is worse than no date: it lands in a date input, looks
        # deliberate, and the bid is due when it is due.
        return v if _DATE_RE.match(v) else ""
    if key == "contact_email":
        return v if _EMAIL_RE.match(v) else ""
    if key == "zip":
        return v if _ZIP_RE.match(v) else ""
    return v


def clean(ai: Any, transcript: Any) -> Dict[str, Any]:
    """Turn one model response into what the intake form is allowed to receive.

    Never raises on a malformed response and never trusts a type: a dead or confused AI costs the
    estimator some typing, and it must never cost them the draft. Everything unrecognised is
    dropped silently; everything recognised but unsupported is dropped LOUDLY, in `unsupported`,
    because a price flag that quietly did not apply is the one failure the estimator needs to know
    about."""
    ai = ai if isinstance(ai, dict) else {}

    fields: Dict[str, str] = {}
    for key in TEXT_FIELDS:
        value = _clean_field(key, ai.get(key))
        if value:
            fields[key] = value

    conditions: Dict[str, Any] = {}
    unsupported: List[str] = []
    raw = ai.get("conditions")
    raw = raw if isinstance(raw, dict) else {}
    for key in MONEY_CONDITIONS:
        item = raw.get(key)
        if not isinstance(item, dict) or not isinstance(item.get("value"), bool):
            continue
        quote = _txt(item.get("quote"))
        if not quote_is_supported(quote, transcript):
            # Named, not silently dropped. The estimator is about to be asked about it.
            unsupported.append(key)
            continue
        conditions[key] = {"value": item["value"], "quote": quote}

    # Rule 2, enforced here rather than trusted to the prompt. A model that returns a county key
    # anyway must not be able to reach the draft with it.
    for banned in BANNED_KEYS:
        fields.pop(banned, None)

    missing = [m for m in (_txt(x) for x in (ai.get("missing") or []))
               if m and m in TEXT_FIELDS + MONEY_CONDITIONS]
    # Everything the model could not support is missing too, whatever it thought.
    for key in unsupported:
        if key not in missing:
            missing.append(key)

    reasoning = ai.get("reasoning")
    return {
        "fields": fields,
        "conditions": conditions,
        "unsupported": unsupported,
        "missing": missing,
        "question": _txt(ai.get("question"))[:400],
        "reasoning": reasoning if isinstance(reasoning, dict) else {},
    }


def merge_conditions(existing: Any, incoming: Dict[str, Any]) -> Dict[str, Any]:
    """Layer the accepted flags onto whatever the project already had.

    MERGES, NEVER REPLACES. `polish_estimate` carries every area, material and crew line of a
    takeoff; the intake owns only `conditions` inside it, and replacing that object would delete
    a finished takeoff's settings on the strength of a sentence somebody spoke. Returns a new
    dict — the caller's is never mutated."""
    out = dict(existing or {}) if isinstance(existing, dict) else {}
    for key, item in (incoming or {}).items():
        if key in MONEY_CONDITIONS and isinstance(item, dict) and isinstance(item.get("value"), bool):
            out[key] = item["value"]
    return out


SYSTEM_PROMPT = (
    "You're an intake assistant for Treadwell, a commercial polished-concrete and epoxy flooring "
    "contractor in Olathe, Kansas. An estimator has just spoken or typed everything they know "
    "about a job. Turn it into intake fields.\n\n"
    "Return STRICT JSON only (no markdown fences, no prose before or after). Include ONLY the "
    "keys you actually found — OMIT anything unknown, never null-fill and never guess. Shape:\n"
    "{\n"
    '  "project_name":   "<job or business name>",\n'
    '  "address":        "<street address only>",\n'
    '  "city":           "<city>",\n'
    '  "state":          "<2-letter, e.g. KS>",\n'
    '  "zip":            "<5-digit>",\n'
    '  "contact_name":   "<person to reply to>",\n'
    '  "contact_email":  "<their email>",\n'
    '  "bid_date":       "YYYY-MM-DD",\n'
    '  "conditions": {\n'
    '     "local":            {"value": true|false, "quote": "<verbatim words from the '
    'transcript>"},\n'
    '     "hard_bid":         {"value": true|false, "quote": "<verbatim>"},\n'
    '     "prevailing_wage":  {"value": true|false, "quote": "<verbatim>"},\n'
    '     "taxable":          {"value": true|false, "quote": "<verbatim>"},\n'
    '     "remodel_tax":      {"value": true|false, "quote": "<verbatim>"}\n'
    "  },\n"
    '  "missing":   ["<field or condition name the estimator still needs to give>", ...],\n'
    '  "question":  "<ONE short question asking for the most important missing thing>",\n'
    '  "reasoning": {"<key>": "<short why-this-value>", ...}\n'
    "}\n"
    "\n"
    "Rules:\n"
    "- EVERY condition needs a `quote` copied WORD FOR WORD out of the transcript. The server "
    "searches the transcript for it and throws the flag away if it is not there, so a paraphrase, "
    "a summary, or a sentence you composed yourself is the same as omitting the condition. If the "
    "estimator did not say it, leave the condition out and put its name in `missing`.\n"
    "- These five conditions change what the customer is charged. Never infer one from context — "
    "not from a school or government name for prevailing_wage, not from the word 'renovation' for "
    "remodel_tax, not from a city name for local. Only from words that were actually said.\n"
    "- NEVER return a county, a tax rate or a remodel rate, under any key name. The estimator "
    "picks the county from a list on the form; a guessed rate is indistinguishable from a "
    "researched one and silently misprices the job.\n"
    "- Quantities, square footages and takeoff numbers are NOT intake fields. The estimator takes "
    "those off the drawings. Ignore any number spoken as an area.\n"
    "- Dates must be YYYY-MM-DD. Convert \"a week from Thursday\" only if the transcript gives you "
    "enough to pin a real day; otherwise omit bid_date and list it in `missing`.\n"
    "- `question` asks for ONE thing — the one that matters most and is missing. The estimator is "
    "asked once and may not have the answer, so make it the question worth spending.\n"
    "- Any key not listed above is ignored. Don't invent fields and don't wrap the object in an "
    "envelope.\n"
)
