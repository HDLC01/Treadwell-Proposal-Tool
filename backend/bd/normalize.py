"""Matching keys, the same rules as BD's page helpers (shared.js).

    normalize_company(" Kestrelwood Gear Co. ")  -> "kestrelwood gear"
    clean_name(" Prairiefold  Foods ")          -> "Prairiefold Foods"
    email_key(" Dana@Example.COM ")             -> "dana@example.com"

normalize_company is the duplicate-check key (`companies.normalized_name`): non-breaking spaces
made spaces, lower case, "&" and punctuation dropped, spaces collapsed, and trailing
Inc/LLC/Co/Corp/... removed (never the last word). The company NAME itself is stored trimmed with
clean_name, never in this form. Every router that inserts or renames a company must set
`normalized_name = normalize_company(name)` (the column is NOT NULL so a forgotten one fails).

account_key is the likely-duplicate BD accounts rule (#811, #802 Q21): two accounts whose keys are
equal are a likely pair. It goes further than normalize_company, which Add contact's find-or-create
keeps using unchanged: short forms are spelled out ("Const." is "Construction"), "and" between words
goes as "&" does, more endings go, and the spaces go, so "Kaw-Point" and "Kaw Point" are one name.
email_domain and FREE_MAIL_DOMAINS give the pair's email-domain hint (a free mail domain is never one).

    account_key("Tallgrass Const. LLC")          -> "tallgrassconstruction"
    account_key("Smith and Sons Roofing Corp")   -> "smithsonsroofing"
    email_domain(" Rae@BisonFlooring.Example.com ") -> "bisonflooring.example.com"
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
    `normalized_name` takes first (contacts_service.resolve_company and the importer), so two
    adds of the same new company at once make ONE row: the second waits, then finds the first's.
    POST /api/bd/companies always creates (as the mock does) and does not take it."""
    conn.execute("select pg_advisory_xact_lock(%s::integer, hashtext(%s::text))", (COMPANY_LOCK_NS, normalized_name))


def email_key(email: Any) -> str | None:
    """Lower-case, trimmed email, or None for nothing (`contacts.email_lower`)."""
    s = ("" if email is None else str(email)).strip().lower()
    return s or None


# ── likely duplicate BD accounts (#811) ──────────────────────────────────────────────────────────
# Endings dropped from the end of a name, beyond COMPANY_SUFFIXES ("and the like", the ticket).
ACCOUNT_ENDINGS = COMPANY_SUFFIXES + ("limited", "llp", "lp", "pc", "plc")

# Short forms spelled out, word by word, after the punctuation is gone ("Const." is "const").
SHORT_FORMS = {
    "const": "construction", "constr": "construction", "cnst": "construction",
    "bros": "brothers", "mfg": "manufacturing", "mech": "mechanical", "elec": "electric",
    "engr": "engineering", "eng": "engineering", "intl": "international", "natl": "national",
    "mgmt": "management", "mgt": "management", "svcs": "services", "dev": "development",
    "dist": "distribution", "assoc": "associates", "assn": "association", "contr": "contractors",
    "contrs": "contractors", "bldrs": "builders", "bldg": "building", "grp": "group", "inds": "industries",
    "hldgs": "holdings", "props": "properties", "sys": "systems", "ctr": "center",
}

# Free mail domains: a shared one says nothing about a company, so it is never a hint. Fixed here, on
# purpose: the big free providers and the internet providers people in Kansas and Missouri use.
FREE_MAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "rocketmail.com", "hotmail.com", "outlook.com",
    "live.com", "msn.com", "aol.com", "icloud.com", "me.com", "mac.com", "protonmail.com", "proton.me",
    "gmx.com", "mail.com", "zoho.com", "yandex.com", "fastmail.com", "hey.com",
    "comcast.net", "att.net", "sbcglobal.net", "swbell.net", "bellsouth.net", "verizon.net", "cox.net",
    "charter.net", "spectrum.net", "kc.rr.com", "everestkc.net", "embarqmail.com", "centurylink.net",
    "q.com", "windstream.net", "earthlink.net", "juno.com", "netzero.net", "frontier.com", "suddenlink.net",
})


def account_key(name: Any) -> str:
    """The cleaned name two BD accounts must share to be a likely pair; "" never pairs."""
    words = [SHORT_FORMS.get(w, w) for w in normalize_company(name).split(" ") if w and w != "and"]
    while len(words) > 1 and words[-1] in ACCOUNT_ENDINGS:
        words.pop()
    return "".join(words)


def email_domain(email: Any) -> str | None:
    """The part after the last "@" of a trimmed, lower-case email, or None."""
    s = email_key(email) or ""
    at = s.rfind("@")
    return s[at + 1:] if 0 < at < len(s) - 1 else None
