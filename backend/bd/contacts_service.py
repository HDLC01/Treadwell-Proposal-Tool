"""What the contacts and companies routers share, and what the routers that move later will use (the
review "Add", the importer): the duplicate check, finding or making a company, a contact's field
checks, and making a contact (#808).

    from bd import contacts_service as cs
    cs.find_duplicates(conn, company, email, phone, except_id=None) -> [duplicate_match dicts]
    cs.resolve_company(conn, spec, extra=None) -> {"id", "name", "city", "industry"}
    cs.insert_company(conn, name, city=None, industry=None) -> the same, always a new row
    cs.live_company(conn, normalized_name) -> the account a person with that company name joins, or None
    cs.company_by_id(conn, id) -> the account a person given that id joins (404 when unknown)
    cs.lock_companies(conn, ids) -> {id: row}, locked FOR UPDATE in id order (404 when one is unknown)
    cs.create_contact(conn, actor, body, source="manual") -> (Contact dict, possible_duplicates)

Ported from BD's routers/contacts.py, where these lived; here because no BD router imports another
(tests/test_bd_app_shell.py), so bd/routers/companies.py cannot take them from the contacts router.
The words are BD's (docs/bd/api-contract.md "Contacts", "Companies"); where the contract is silent
they follow BD's retired mock API (api.js), as BD did. Every write runs on the caller's connection,
inside its transaction.
"""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from . import appsettings, bizdate, errors, paging, serialize
from .events import log_event
from .normalize import clean_name, lock_company_name, normalize_company
from .phone import to_e164

CONTACT_NOT_FOUND = "That contact does not exist."
COMPANY_NOT_FOUND = "That company does not exist."
ALREADY_MERGED = "This account is already merged into another."
FIX = "Some fields need fixing."

CATEGORIES = ("bd", "maintenance")
SOURCES = ("workbook", "manual", "proposal_tool", "import")

# Free-text columns a client may set (value: str or null). lead_source and notes are NOT NULL.
TEXT_FIELDS = ("title", "email", "phone", "city", "industry", "lead_source", "stage", "account_type",
               "next_step", "notes")
DATE_FIELDS = ("next_step_date", "promised_date")

# Size limits on stored text (Hanz, 2026-11-11: "do all"; chosen far above real use). A contact's
# notes match an interaction's summary (interactions_service.SUMMARY_MAX); every other short field,
# the name and the company name stop at 200 characters (an email at 254, the address standard).
TEXT_MAX = {"notes": 20000, "next_step": 500, "email": 254}
TEXT_DEFAULT_MAX = 200
NAME_MAX = 200
TAGS_MAX = 50   # tags on one contact
TAG_MAX = 60    # characters in one tag

BD_FREQUENCY_SENTENCE = "BD contacts follow the BD cadence. Set a follow-up override instead."

_CREATED_EVENT = {
    "manual": ("created", "Added by hand"),
    "workbook": ("created", "Added by hand"),
    "import": ("created", "Imported from a file"),
    "proposal_tool": ("added_from_quote", "Added from a quote"),
}


# ── small helpers ─────────────────────────────────────────────────────────────────────────────
def as_int(value):
    """An int from a JSON number (6 or 6.0); None for anything else (bools and strings too)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _round_half_up(value) -> int:
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def default_frequency(settings: dict, category: str) -> int:
    """The stored frequency a person takes in `category` when nobody gives one: a BD contact's comes
    from the one BD cadence (the view derives it again live, so this stored number is only a record),
    anyone else's from that category's default. Creating a contact, a contact's category flip and a
    company move (bd/routers/accounts.py) all use this one rule."""
    if category == "bd":
        return int(appsettings.CADENCE_FREQ.get(settings.get("bd_cadence") or "", 4))
    return int((settings.get("default_frequency") or {}).get(category) or 3)


def clamp_frequency(value, fallback: int) -> int:
    """api.js clampFrequency: 1-52, or the default when missing, 0 or negative."""
    if value is None:
        return int(fallback) if int(fallback or 0) > 0 else 4
    n = _round_half_up(value)
    if n <= 0:
        return int(fallback) if int(fallback or 0) > 0 else 4
    return min(52, n)


def _is_date(value) -> bool:
    try:
        bizdate.parse_date(value)
        return isinstance(value, str)
    except (TypeError, ValueError):
        return False


def too_long(limit: int) -> str:
    return "Keep this to %d characters or fewer." % limit


def check_text(body: dict, key: str, fields: dict) -> None:
    if key in body and body[key] is not None and not isinstance(body[key], str):
        fields[key] = "Use text."
    elif isinstance(body.get(key), str) and len(body[key]) > TEXT_MAX.get(key, TEXT_DEFAULT_MAX):
        fields[key] = too_long(TEXT_MAX.get(key, TEXT_DEFAULT_MAX))


def check_date(body: dict, key: str, fields: dict) -> None:
    v = body.get(key)
    if key in body and v is not None and v != "" and not _is_date(v):
        fields[key] = "Use a date (YYYY-MM-DD)."


def check_tags(body: dict, fields: dict) -> None:
    v = body.get("tags")
    if "tags" in body and v is not None and not (isinstance(v, list) and all(isinstance(t, str) for t in v)):
        fields["tags"] = "Use a list of words."
    elif isinstance(v, list) and (len(v) > TAGS_MAX or any(len(t) > TAG_MAX for t in v)):
        fields["tags"] = "Use at most %d tags of %d characters or fewer." % (TAGS_MAX, TAG_MAX)


def tags(value) -> list:
    """Tags as sent (the page trims and splits them), like the mock."""
    return list(value or [])


def user_exists(conn, user_id) -> dict | None:
    return conn.execute("select id, name from users where id = %s", (user_id,)).fetchone()


# ── duplicates and companies ──────────────────────────────────────────────────────────────────
def find_duplicates(conn, company=None, email=None, phone=None, except_id=None) -> list:
    """api.js findDuplicates: every active contact at the same normalized company, else with the
    same email, else the same phone, in id order. Each match carries its first reason.

    "The same company" is every account the name stands for: those with that normalized name, and
    the account each merged-away one was merged into, or, when no account has the name, the
    survivor a renaming merge took it from (#811). After a merge the warning still names the people
    at the account a person typing that name joins."""
    key = normalize_company(company) if company else ""
    mail = str(email).strip().lower() if email else ""
    tel = to_e164(phone) if phone else None
    tests = []
    if key:
        tests.append(("co.id = any(%s)", _accounts_named(conn, key), "Same company name"))
    if mail:
        tests.append(("c.email_lower = %s", mail, "Same email"))
    if tel:
        tests.append(("c.phone_e164 = %s", tel, "Same phone"))
    if not tests:
        return []
    case_sql = "case " + " ".join("when " + cond + " then %s::text" for cond, _v, _r in tests) + " end"
    params = []
    for _cond, value, reason in tests:
        params += [value, reason]
    where = ["c.archived_at is null"]
    params_where = []
    if except_id is not None:
        where.append("c.id <> %s")
        params_where.append(except_id)
    where.append("(" + " or ".join(cond for cond, _v, _r in tests) + ")")
    params_where += [v for _c, v, _r in tests]
    rows = conn.execute(
        "select c.id, c.name, co.name as company_name, c.city, " + case_sql + " as reason"
        " from contacts c join companies co on co.id = c.company_id"
        " where " + " and ".join(where) + " order by c.id",
        params + params_where).fetchall()
    return [serialize.duplicate_match(r, r["reason"]) for r in rows]


# A merged-away account (#811) is hidden, so nobody may join it: the find-or-create and an id both
# lead to the account it was merged into, followed to the end. A chain can never loop (nothing merges
# into a merged account), so the hop limit is only a guard.
#
# Every read that picks the account a person is written to takes the row FOR SHARE. A merge holds
# both accounts FOR UPDATE until it commits, so a person being added or moved at that moment waits
# for it, then reads the committed row, sees the mark and follows it; and a merge that starts after
# the read waits until the person is written, then moves them with everyone else. A plain read would
# hand back the losing account's id, and the person would land on a hidden account (review, #811).
# The duplicate warning (find_duplicates) is only a hint, so it reads without the lock.
#
# A merge that gives the survivor the other account's name (`name_from`) leaves the survivor's old
# name on no account. That name still leads to the survivor, through the merge's event, while the
# merge stands, so Add contact and the import do not make a new duplicate of it (verifier, #811).
# An account that really has the name always wins over that trail.
_COMPANY_COLUMNS = "id, name, city, industry, normalized_name, merged_into"
_MAX_HOPS = 100
MERGED_EVENT = "company_merged"
UNDONE_EVENT = "company_merge_undone"


def _company_row(conn, company_id, lock=True):
    return conn.execute("select " + _COMPANY_COLUMNS + " from companies where id = %s"
                        + (" for share" if lock else ""), (company_id,)).fetchone()


def _survivor(conn, row, lock=True):
    hops = 0
    while row is not None and row["merged_into"] is not None and hops < _MAX_HOPS:
        row = _company_row(conn, row["merged_into"], lock)
        hops += 1
    return row


def _renamed_into(conn, normalized_name: str):
    """The survivor's id of the newest merge, not undone, that renamed its survivor away from this
    normalized name; None when there is none."""
    rows = conn.execute(
        "select e.data->>'into' as into_id, e.data->>'name_before' as name_before from events e"
        " where e.kind = %s and e.data->>'name_before' is distinct from e.data->>'name_after'"
        " and not exists (select 1 from events x where x.kind = %s and (x.data->>'merge_id')::bigint = e.id)"
        " order by e.id desc", (MERGED_EVENT, UNDONE_EVENT)).fetchall()
    for r in rows:
        if normalize_company(r["name_before"]) == normalized_name and str(r["into_id"] or "").isdigit():
            return int(r["into_id"])
    return None


def _accounts_named(conn, normalized_name: str) -> list:
    """The ids of every account a company name stands for, read without a lock (find_duplicates)."""
    rows = conn.execute("select " + _COMPANY_COLUMNS + " from companies where normalized_name = %s",
                        (normalized_name,)).fetchall()
    if not rows:
        into = _renamed_into(conn, normalized_name)
        rows = [] if into is None else [_company_row(conn, into, lock=False)]
    ids = {r["id"] for r in (_survivor(conn, row, lock=False) for row in rows) if r is not None}
    return sorted(ids)


def lock_companies(conn, ids) -> dict:
    """Lock these companies FOR UPDATE, in id order (so two callers never wait on each other in a
    ring), and return them by id: {id, name, normalized_name, merged_into, merged_at}. 404 when one
    does not exist. A company move and a merge, Undo or Keep separate (#810, #811) take it first."""
    want = sorted(set(ids))
    rows = conn.execute("select id, name, normalized_name, merged_into, merged_at from companies"
                        " where id = any(%s) order by id for update", (want,)).fetchall()
    if len(rows) != len(want):
        raise errors.not_found(COMPANY_NOT_FOUND)
    return {r["id"]: r for r in rows}


def live_company(conn, normalized_name: str):
    """The oldest account with this normalized name that is not merged away; else, when only a
    merged-away account has the name, the account its merge leads to; else, when no account has it,
    the survivor a standing merge renamed away from it; else None.
    {id, name, city, industry, normalized_name}."""
    row = conn.execute("select " + _COMPANY_COLUMNS + " from companies where normalized_name = %s"
                       " order by merged_into is not null, id limit 1 for share", (normalized_name,)).fetchone()
    if row is None:
        into = _renamed_into(conn, normalized_name)
        row = None if into is None else _company_row(conn, into)
    row = _survivor(conn, row)
    return None if row is None else {k: row[k] for k in ("id", "name", "city", "industry", "normalized_name")}


def company_by_id(conn, company_id):
    cid = as_int(company_id)
    if paging.as_id(cid) is None:
        raise errors.not_found(COMPANY_NOT_FOUND)
    row = _survivor(conn, _company_row(conn, cid))
    if row is None:
        raise errors.not_found(COMPANY_NOT_FOUND)
    return {k: row[k] for k in ("id", "name", "city", "industry")}


def insert_company(conn, name: str, city=None, industry=None) -> dict:
    row = conn.execute(
        "insert into companies (name, normalized_name, city, industry) values (%s, %s, %s, %s)"
        " returning id, name, city, industry",
        (name, normalize_company(name), city or None, industry or None)).fetchone()
    return dict(row)


def resolve_company(conn, spec, extra=None) -> dict:
    """api.js resolveCompany: {"id": n} is that company (404 when unknown); {"name": "..."} is the
    company with the same normalized name, else a new one (city and industry from `extra`). A
    merged-away account is never the answer: either way leads to the account it was merged into."""
    if not isinstance(spec, dict):
        raise errors.bad_request("Pick or type a company.", {"company": "Required."})
    if spec.get("id") is not None:
        return company_by_id(conn, spec["id"])
    name = clean_name(spec.get("name")) if isinstance(spec.get("name"), str) else ""
    if not name:
        raise errors.bad_request("Pick or type a company.", {"company": "Required."})
    norm = normalize_company(name)
    # Find-or-create under a per-name lock, so concurrent adds never make two companies with one
    # normalized name (review finding DATA-2). The lock lasts until this transaction commits.
    lock_company_name(conn, norm)
    hit = live_company(conn, norm)
    if hit:
        return {k: hit[k] for k in ("id", "name", "city", "industry")}
    extra = extra or {}
    city = extra.get("city") if isinstance(extra.get("city"), str) else None
    industry = extra.get("industry") if isinstance(extra.get("industry"), str) else None
    return insert_company(conn, name, city, industry)


def company_spec_ok(spec) -> bool:
    if not isinstance(spec, dict):
        return False
    if spec.get("id") is not None:
        return as_int(spec["id"]) is not None
    return isinstance(spec.get("name"), str) and bool(clean_name(spec["name"]))


# ── create ────────────────────────────────────────────────────────────────────────────────────
def _default_owner(conn, actor):
    """api.js createContact: me when I am a salesperson, else the first salesperson, else me."""
    if actor and actor.get("role") == "salesperson":
        return actor["id"]
    row = conn.execute("select id from users where role = 'salesperson' and active order by id limit 1").fetchone()
    if row:
        return row["id"]
    return actor["id"] if actor else None


def validate_new(body: dict) -> dict:
    """The 400 fields of a new contact (POST /api/bd/contacts), {} when it is fine."""
    fields = {}
    if not isinstance(body.get("name"), str) or not body["name"].strip():
        fields["name"] = "Type the person's name."
    elif len(body["name"].strip()) > NAME_MAX:
        fields["name"] = too_long(NAME_MAX)
    if not company_spec_ok(body.get("company")):
        fields["company"] = "Pick or type a company."
    elif isinstance(body["company"].get("name"), str) and len(body["company"]["name"].strip()) > NAME_MAX:
        fields["company"] = too_long(NAME_MAX)
    cat = body.get("category") or "bd"
    if cat not in CATEGORIES:
        fields["category"] = "Use bd or maintenance."
    for key in TEXT_FIELDS:
        check_text(body, key, fields)
    for key in DATE_FIELDS + ("last_quote_date",):
        check_date(body, key, fields)
    check_tags(body, fields)
    f = body.get("frequency_per_year")
    if "frequency_per_year" in body and cat == "bd":
        # The key itself is refused, even as null (the mock reads it the same way).
        fields["frequency_per_year"] = BD_FREQUENCY_SENTENCE
    elif f is not None and (isinstance(f, bool) or not isinstance(f, (int, float))
                            or (isinstance(f, float) and not math.isfinite(f))):
        # 1e999 is a JSON number Python reads as infinity; the rounding below cannot take it.
        fields["frequency_per_year"] = "Use a number from 1 to 52."
    imp = body.get("importance")
    if imp not in (None, 0) and as_int(imp) not in (1, 2, 3):
        fields["importance"] = "Use 1, 2 or 3."
    if "confirmed" in body and body["confirmed"] is not None and not isinstance(body["confirmed"], bool):
        fields["confirmed"] = "Use true or false."
    for key in ("owner_id", "co_owner_id"):
        if body.get(key) is not None and as_int(body[key]) is None:
            fields[key] = "Pick a user."
    return fields


def create_contact(conn, actor, body: dict, source: str = "manual"):
    """Insert a contact the way POST /api/bd/contacts does (validation, the duplicate hint, the
    company found or created, settings defaults, the "created" event). Returns
    (Contact, possible_duplicates). `source` is set by the caller, never by the request."""
    fields = validate_new(body)
    if fields:
        raise errors.bad_request(FIX, fields)
    if source not in SOURCES:
        raise ValueError("unknown contact source %r" % (source,))
    spec = body["company"]
    dup_company = spec.get("name") if isinstance(spec.get("name"), str) and spec.get("name").strip() else None
    if dup_company is None:
        dup_company = company_by_id(conn, spec.get("id"))["name"]
    dups = find_duplicates(conn, dup_company, body.get("email"), body.get("phone"), None)
    co = resolve_company(conn, spec, body)

    owner_id = as_int(body.get("owner_id")) if body.get("owner_id") is not None else _default_owner(conn, actor)
    if body.get("owner_id") is not None and not user_exists(conn, owner_id):
        raise errors.bad_request("That owner does not exist.", {"owner_id": "Pick a user."})
    co_owner_id = as_int(body.get("co_owner_id")) if body.get("co_owner_id") is not None else None
    if co_owner_id is not None and not user_exists(conn, co_owner_id):
        raise errors.bad_request("That co-owner does not exist.", {"co_owner_id": "Pick a user."})

    cat = body.get("category") or "bd"
    settings = appsettings.load(conn)
    if cat == "bd":
        # A BD contact's number comes from the one BD cadence (the view derives it again live, so a
        # later change of the setting moves every BD contact; this stored value is only a record).
        freq = default_frequency(settings, "bd")
    else:
        freq = clamp_frequency(body.get("frequency_per_year"), default_frequency(settings, cat))
    dup_id, dup_reason = (dups[0]["contact_id"], dups[0]["reason"]) if dups else (None, None)
    raw_email = body.get("email")
    email = raw_email.strip() if raw_email else None

    row = conn.execute(
        "insert into contacts (company_id, name, title, email, phone, city, industry, lead_source, stage,"
        " category, account_type, owner_id, co_owner_id, frequency_per_year, confirmed, importance,"
        " next_step, next_step_date, promised_date, last_quote_date, duplicate_of, duplicate_reason,"
        " source, tags, notes)"
        " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
        " %s, %s, %s) returning id",
        (co["id"], body["name"].strip(), body.get("title") or None, email, body.get("phone") or None,
         body.get("city") or co.get("city") or None, body.get("industry") or co.get("industry") or None,
         body.get("lead_source") or "Other/Misc", body.get("stage") or None, cat,
         body.get("account_type") or None, owner_id, co_owner_id, freq, body.get("confirmed") is True,
         as_int(body.get("importance")) or 1, body.get("next_step") or None,
         body.get("next_step_date") or None, body.get("promised_date") or None,
         body.get("last_quote_date") or None, dup_id, dup_reason, source,
         tags(body.get("tags")), body.get("notes") or "")).fetchone()
    kind, detail = _CREATED_EVENT[source]
    log_event(conn, kind, actor=actor, contact_id=row["id"], detail=detail,
              data={"source": source, "company_id": co["id"]})
    return serialize.fetch_contact(conn, row["id"]), dups

