"""US phone numbers, no library: the same rules as BD's page helpers (shared.js) `e164()` / `fmtPhone()`.

    to_e164("816.555.0110")      -> "+18165550110"
    to_e164("(913) 555-0117")    -> "+19135550117"
    to_e164("+1 816 555 0110")   -> "+18165550110"
    to_e164("555-0110")          -> None   (not 10 digits)
    last10("+1 (816) 555-0110")  -> "8165550110"   the key calls are matched on
    display("816.555.0110")      -> "816-555-0110"

Only ASCII digits count (a Unicode digit such as "٣" is not a phone digit). The database derives
`contacts.phone_e164` with the SQL function bd_e164(), which follows the same rule; both are
tested against the same table.
"""
from __future__ import annotations

import re
from typing import Any

_NOT_DIGIT = re.compile(r"[^0-9]")


def digits(phone: Any) -> str:
    return _NOT_DIGIT.sub("", "" if phone is None else str(phone))


def to_e164(phone: Any) -> str | None:
    """"+1XXXXXXXXXX", or None when it is not a 10-digit US number (an 11-digit one starting
    with 1 has the 1 dropped)."""
    d = digits(phone)
    if len(d) == 11 and d[0] == "1":
        d = d[1:]
    return "+1" + d if len(d) == 10 else None


def last10(phone: Any) -> str | None:
    """The last 10 digits (what a call is matched on), or None with fewer than 10."""
    d = digits(phone)
    return d[-10:] if len(d) >= 10 else None


def display(phone: Any) -> str:
    """"816-555-0110" for a US number; anything else as given ("" for nothing)."""
    e = to_e164(phone)
    if not e:
        return "" if phone is None else str(phone)
    return "%s-%s-%s" % (e[2:5], e[5:8], e[8:])
