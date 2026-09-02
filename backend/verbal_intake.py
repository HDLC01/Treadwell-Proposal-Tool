"""Verbal intake for the Polish beta: an estimator talks, and the form fills in.

Hanz, 2026-08-25: the estimator says or types what they have, a cheat sheet tells them what is
needed, the AI fills what it can and asks ONCE for what is missing, and if they still do not have
it they carry on. Reaching the normal intake form stays optional.

WHY THIS IS ITS OWN MODULE AND NOT ANOTHER BLOCK IN main.py. Everything below is a pure function
over a transcript and a dict — no request, no subprocess, no Supabase — so the rules that decide
whether a price flag is allowed to move can be tested directly, thousands of times, without a
Claude call. main.py keeps the one line that runs the CLI.

THE THREE RULES THAT MATTER, in the order they cost money if broken:

  1. **A MONEY FLAG NEEDS EVIDENCE, AND THE ESTIMATOR SEES THE TRANSCRIPT'S OWN WORDS.** The five
     condition toggles — local, hard_bid, prevailing_wage, taxable, remodel_tax — each change what
     the job is priced at. An extraction model asked "is this prevailing wage?" will happily infer
     one from a school district in the project name. So a flag is only accepted when the model
     returns a VERBATIM QUOTE and the server can still find that quote, as a consecutive run of
     WORDS, in the transcript it sent.

     What comes back with the accepted flag is `context` — the transcript's own text around where
     the match landed — and NOT the model's quote. That difference is the whole of the second
     half of this gate, and it was bought with a live defect: a transcript saying "it is not a
     hard bid" plus a model quoting the three words "a hard bid" passed the old substring check,
     and the panel then printed the model's crop next to the word "because". The estimator read
     back the inverted claim as their own words. Widening the display to the surrounding sentence
     puts "…it is not a hard bid…" beside the flag, where a human catches it in one glance.

     Machine-judging RELEVANCE is out of scope and always was — a keyword rule would reject real
     evidence phrased unexpectedly. What is in scope is that the words on screen are the
     transcript's, complete enough to read, and never the model's selection of them.

  2. **NOTHING HERE MAY WRITE A COUNTY.** `county_remodel_rate` carries a live hazard the rest of
     the app depends on: null means "nobody said which county" and falls back to the Kansas state
     rate, while an explicit 0 means "we know, and it is nothing" (Missouri exempts remodel
     labour). A guessed 0 is indistinguishable from a researched one and silently underprices the
     job. The county picker on the intake form is the only thing allowed to set those four keys.

     THE MECHANISM IS THE WHITELIST: `fields` is built by walking TEXT_FIELDS, so a key that is
     not on that tuple has no way to reach the output at all — a county key included. There used
     to be an explicit `pop` of BANNED_KEYS after that loop, which read like the enforcement and
     could never fire, because the two tuples do not intersect. It is gone; BANNED_KEYS stays as
     the list the test parametrises over, so the ban is still asserted, just against the
     mechanism that actually implements it.

  3. **OMIT, NEVER NULL-FILL.** Copied from leads.py's extraction prompt rather than main.py's
     autofill one. `_AUTOFILL_SYSTEM_PROMPT` is explicitly told never to abstain and to apply
     conservative defaults, which is exactly backwards for a feature whose whole job is knowing
     what it does not have.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

# The plain text the estimator can dictate into. Everything else on the intake form is either
# derived (city_state), picked from a curated list (county), or a takeoff number nobody says out
# loud accurately enough to price from.
TEXT_FIELDS = (
    "project_name", "address", "city", "state", "zip",
    "contact_name", "contact_email", "bid_date",
)

# The five toggles that move money. Each needs a quote — see rule 1 above.
MONEY_CONDITIONS = ("local", "hard_bid", "prevailing_wage", "taxable", "remodel_tax")

# Never written from AI, at any confidence, for any reason. See rule 2. Not enforced by a pop —
# TEXT_FIELDS is the whitelist and none of these is on it. This tuple is what the test asserts
# against, so the ban has a name and a failing case.
BANNED_KEYS = ("county", "county_tax_rate", "county_remodel_rate", "county_notes")

# A quote has to be long enough to actually be evidence. "yes" appears in almost every transcript
# and would unlock any flag; two words and eight characters is the smallest thing that can carry a
# claim ("hard bid", "no sales tax").
_MIN_QUOTE_WORDS = 2
_MIN_QUOTE_CHARS = 8

# How much of the transcript comes back around a match. Eight words either side is enough to carry
# the negation that inverts a claim ("it is NOT a hard bid", "no prevailing wage on this one") and
# short enough to read on one line of the panel without being scrolled past.
_CONTEXT_TOKENS = 8

# The longest a free-text field may be, matching how `question` is bounded. A project name the
# length of a paragraph is a model that has pasted the transcript into the box.
_MAX_FIELD_CHARS = 300

# Fields whose shape is checked by a pattern. Over the cap these are DROPPED rather than
# truncated: a clipped project name is visible and fixable on screen, a clipped email is a
# plausible-looking address for somebody who does not exist.
_STRUCTURED_FIELDS = ("state", "zip", "bid_date", "contact_email")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")
_ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")


def _txt(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _fold(word: str) -> str:
    return unicodedata.normalize("NFKC", word).casefold()


def tokenise(text: Any) -> List[Tuple[str, int, int]]:
    """The text as words, each remembering where in the ORIGINAL string it came from.

    Case, punctuation and run-length of whitespace are all dropped from the comparison form,
    because dictation and the model disagree about every one of them: the Web Speech API
    punctuates by guesswork, and a model asked to quote will normally re-punctuate what it read.
    What survives is the sequence of words, which is what actually makes a quote evidence.

    The (start, end) offsets are the point of returning tuples rather than a joined string. They
    are indices into the text exactly as it was passed in, so a match found on the normalised
    words can be shown back to the estimator in their own punctuation and capitals — see
    `quote_context`. Normalisation happens per token, never over the whole string, because NFKC
    can change a string's LENGTH and that would silently shift every offset.

    This deliberately does NOT stem, fold plurals, or match approximately. A gate that accepts a
    paraphrase is not a gate — the model would be free to write down what it inferred and have it
    accepted as what it heard."""
    s = _txt(text)
    out: List[Tuple[str, int, int]] = []
    buf: List[str] = []
    start: Optional[int] = None
    for i, ch in enumerate(s):
        # A combining mark belongs to the letter in front of it; splitting there would turn a
        # decomposed "é" into a word boundary.
        if ch.isalnum() or unicodedata.combining(ch):
            if start is None:
                start = i
            buf.append(ch)
            continue
        if start is not None:
            out.append((_fold("".join(buf)), start, i))
            buf, start = [], None
    if start is not None:
        out.append((_fold("".join(buf)), start, len(s)))
    return [t for t in out if t[0]]


def evidence_key(text: Any) -> str:
    """The words of `text`, normalised and space-joined. The comparison form, kept as one function
    so the quote and the transcript can never be normalised two different ways."""
    return " ".join(w for w, _s, _e in tokenise(text))


def _find_span(q_words: List[str], hay_words: List[str]) -> Optional[Tuple[int, int]]:
    """The token range of `hay_words` occupied by the whole of `q_words`, or None.

    A CONSECUTIVE TOKEN SEQUENCE, not a substring, and that closes a hole the old `in` check had:
    with punctuation stripped, "hard bid" was found inside "a shard bidding floor" — words nobody
    said, offered as proof of a flag that moves money. Comparing whole words in sequence anchors
    both ends of every word for free, which is why this is a tokeniser and not a regex with \\b in
    it: \\b would still have to be built out of the same normalisation, twice.

    What it does NOT close is a quote stitched across a full stop — "It is not local. Hard bid
    though." really does contain those words consecutively, and no matcher can tell that they were
    two claims. That is what `quote_context` is for: the estimator sees both sentences."""
    if len(q_words) < _MIN_QUOTE_WORDS or len(" ".join(q_words)) < _MIN_QUOTE_CHARS:
        return None
    n = len(q_words)
    for i in range(len(hay_words) - n + 1):
        if hay_words[i:i + n] == q_words:
            return (i, i + n)
    return None


def quote_context(quote: Any, transcript: Any) -> Optional[str]:
    """The transcript's own text around where `quote` was said — or None if it was not.

    THIS IS WHAT THE ESTIMATOR READS, and the reason it is the transcript's text and not the
    model's: a model that crops "a hard bid" out of "it is not a hard bid" clears the gate
    honestly — every word really was said — and the old panel then printed the crop as if the
    estimator had said it. Widening to eight words either side puts the negation back on screen
    next to the flag.

    Whitespace is collapsed (dictation arrives with newlines mid-sentence) but nothing else is
    touched: the punctuation and capitals are the estimator's own, which is what makes it readable
    as something they said."""
    hay = tokenise(transcript)
    span = _find_span([w for w, _s, _e in tokenise(quote)], [w for w, _s, _e in hay])
    if span is None:
        return None
    lo = max(0, span[0] - _CONTEXT_TOKENS)
    hi = min(len(hay), span[1] + _CONTEXT_TOKENS)
    s = _txt(transcript)
    return " ".join(s[hay[lo][1]:hay[hi - 1][2]].split())


def quote_is_supported(quote: Any, transcript: Any) -> bool:
    """True when the transcript really contains this quote, as consecutive whole words."""
    return quote_context(quote, transcript) is not None


def _clean_state(v: Any) -> str:
    s = _txt(v).upper()
    return s if len(s) == 2 and s.isalpha() else ""


def _clean_field(key: str, raw: Any) -> str:
    """One field's value, or "" for anything the form must not receive.

    A NON-STRING IS NOT A VALUE ANYBODY SAID. `str()` on a list yields its repr, so a model that
    returned ["Blue", "Valley"] for project_name put the literal text "['Blue', 'Valley']" into
    the box, looking every bit as deliberate as a real answer. On a number it yields a form that
    has already lost information — a zip of 06085 arrives as 6085 — so strings only, for every
    field, and the estimator types the odd one the model got wrong."""
    if not isinstance(raw, str):
        return ""
    v = raw.strip()
    if not v:
        return ""
    if len(v) > _MAX_FIELD_CHARS:
        if key in _STRUCTURED_FIELDS:
            return ""
        v = v[:_MAX_FIELD_CHARS]
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
    about.

    An accepted condition comes back as {"value": bool, "context": str}. `context` is the
    transcript's own words around the match and is what the panel prints; the model's `quote` is
    deliberately NOT carried through, because a crop that inverts its own sentence is exactly the
    thing this gate now defends against and there is no second place it should be readable
    from."""
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
        context = quote_context(quote, transcript)
        if context is None:
            # Named, not silently dropped. The estimator is about to be asked about it.
            unsupported.append(key)
            continue
        # `context`, NOT `quote`. The model's crop of a sentence can invert that sentence's
        # meaning and still be word-for-word true; what goes on screen is the transcript's own
        # text around the match. See rule 1.
        conditions[key] = {"value": item["value"], "context": context}

    # `isinstance`, not `or []`: `{"missing": 3}` is falsy-safe but not iterable, and the old
    # `or []` let an int, a bool or a string through to a comprehension that then raised
    # TypeError — outside the route's try block, so it reached the estimator as a 500 AND burned
    # one of their three AI runs per five minutes.
    raw_missing = ai.get("missing")
    raw_missing = raw_missing if isinstance(raw_missing, list) else []
    missing = [m for m in (_txt(x) for x in raw_missing)
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


# There was a `merge_conditions()` here. It was written for a server-side merge into
# `polish_estimate` that never happened and had no caller in any repo — the route RETURNS and does
# not write, and the merge that does happen lives in applyVerbal on the page, where
# frontend/js/polish-verbal.js sets each switch through toggleCondition (pinned by
# backend/tests/test_verbal_apply.py). Two merge rules for one decision is how they drift apart,
# so the one nothing called is gone.


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
