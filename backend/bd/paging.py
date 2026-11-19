"""Query-string numbers every BD list route reads the same way (limit / offset, ids).

    from bd.paging import page_params, query_int
    fields = {}
    limit, offset = page_params(request.query_params, fields)   # limit default 100, max 500
    if fields:
        raise errors.bad_request("Some fields need fixing.", fields)

Ported from BD's routers/contacts.py (page_params, _query_int), so a router that lists something
does not have to import the contacts router to read its paging.
"""
from __future__ import annotations

MAX_ID = 2 ** 63 - 1


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
