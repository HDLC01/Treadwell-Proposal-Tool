"""The numbers and bodies every BD route reads the same way: limit / offset, ids, a JSON object body.

    from bd.paging import page_params, query_int, as_id, path_id, json_object
    fields = {}
    limit, offset = page_params(request.query_params, fields)   # limit default 100, max 500
    if fields:
        raise errors.bad_request("Some fields need fixing.", fields)
    cid = path_id(id, "That contact does not exist.")             # 404 with the route's sentence
    body = json_object(body)                                      # {} when none; 400 when not an object

Ported from BD's routers/contacts.py (page_params, _query_int), so a router that lists something
does not have to import the contacts router to read its paging. as_id, path_id and json_object are
the one copy of what BD's routers each wrote for themselves (#807), so a router that moves later uses
these rather than writing another.
"""
from __future__ import annotations

from . import errors

MAX_ID = 2 ** 63 - 1
NOT_AN_OBJECT = "Send a JSON object."


def as_id(value):
    """A database id (1 to MAX_ID) from path text (ASCII digits, nothing around them) or a JSON whole
    number; None for anything else (a bool, "abc", "0", " 5", "1e0", past bigint)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        n = value
    else:
        text = str(value if value is not None else "")
        if not text.isascii() or not text.isdigit():
            return None
        n = int(text)
    return n if 1 <= n <= MAX_ID else None


def path_id(value, message: str) -> int:
    """A path id as an int. Anything that cannot name a row is a plain 404 with the route's sentence
    (path ids are taken as text, so "abc" is a 404 too, never FastAPI's 422 -> 400)."""
    n = as_id(value)
    if n is None:
        raise errors.not_found(message)
    return n


def json_object(body) -> dict:
    """An optional JSON object body: {} when none was sent, the object itself, else 400
    {"body": "Send a JSON object."}."""
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.bad_request("Some fields need fixing.", {"body": NOT_AN_OBJECT})
    return body


def query_int(params, key: str, fields: dict):
    """A whole number from 0 in the query string, or None (blank or absent). A bad value adds a
    sentence to `fields` and returns None."""
    v = params.get(key)
    if v is None or v == "":
        return None
    try:
        n = int(v)
    except ValueError:
        fields[key] = "Use a whole number."
        return None
    if n < 0 or n > MAX_ID:
        fields[key] = "Use a whole number from 0."
        return None
    return n


def page_params(params, fields: dict):
    """limit (default 100, max 500) and offset, as BD's api.js reads them (a 0 limit is the default)."""
    limit = query_int(params, "limit", fields)
    offset = query_int(params, "offset", fields)
    return min(500, limit or 100), offset or 0
