"""Matching keys, the same rules as BD's page helpers (shared.js).

    normalize_company(" Kestrelwood Gear Co. ")  -> "kestrelwood gear"
    clean_name(" Prairiefold  Foods ")          -> "Prairiefold Foods"
    email_key(" Dana@Example.COM ")             -> "dana@example.com"

normalize_company is the duplicate-check key (`companies.normalized_name`): non-breaking spaces
made spaces, lower case, "&" and punctuation dropped, spaces collapsed, and trailing
Inc/LLC/Co/Corp/... removed (never the last word). The company NAME itself is stored trimmed with
clean_name, never in this form. Every router that inserts or renames a company must set
`normalized_name = normalize_company(name)` (the column is NOT NULL so a forgotten one fails).
"""
from __future__ import annotations

import re
from typing import Any

# The same list as shared.js COMPANY_SUFFIXES.
COMPANY_SUFFIXES = ("inc", "incorporated", "llc", "co", "corp", "corporation", "company", "ltd", "lc", "pllc")

# shared.js replaces U+00A0 (no-break space), U+2007 (figure space) and U+202F (narrow no-break).
_ODD_SPACES = re.compile("[   ]")
_NOT_WORD = re.compile(r"[^a-z0-9\s]")
_SPACES = re.compile(r"\s+")


def normalize_company(name: Any) -> str:
    s = _ODD_SPACES.sub(" ", "" if name is None else str(name)).lower()
    s = _SPACES.sub(" ", _NOT_WORD.sub("", s.replace("&", " "))).strip()
    words = s.split(" ") if s else []
    while len(words) > 1 and words[-1] in COMPANY_SUFFIXES:
        words.pop()
    return " ".join(words)


def clean_name(name: Any) -> str:
    """A company or person name as stored: odd spaces made spaces, runs collapsed, trimmed
    (api.js resolveCompany / createCompany)."""
    s = _ODD_SPACES.sub(" ", "" if name is None else str(name))
    return _SPACES.sub(" ", s).strip()


# The advisory-lock namespace for "find the company with this normalized name, else create it"
# (pg_advisory_xact_lock(namespace, hashtext(normalized_name))). Review finding DATA-2.
COMPANY_LOCK_NS = 728_100_302


def lock_company_name(conn: Any, normalized_name: str) -> None:
    """Hold, until the caller's transaction ends, the lock every find-or-create of a company by
    `normalized_name` takes first (routers.contacts.resolve_company and the importer), so two
    adds of the same new company at once make ONE row: the second waits, then finds the first's.
    POST /api/companies always creates (as the mock does) and does not take it."""
    conn.execute("select pg_advisory_xact_lock(%s::integer, hashtext(%s::text))", (COMPANY_LOCK_NS, normalized_name))


def email_key(email: Any) -> str | None:
    """Lower-case, trimmed email, or None for nothing (`contacts.email_lower`)."""
    s = ("" if email is None else str(email)).strip().lower()
    return s or None
