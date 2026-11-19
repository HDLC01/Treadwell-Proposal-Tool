"""Companies: GET/POST /api/bd/companies, GET/PATCH /api/bd/companies/{id}.

BD's companies routes, moved under /api/bd/ with the contact page and Add contact (#808), with the
same checks, answers and words. The type-ahead (GET /api/bd/companies?q=) is the one Add contact
uses, and keeps its behaviour and answer exactly.

docs/bd/api-contract.md "Companies" is the spec; where it is silent this follows BD's mock (api.js
listCompanies, getCompany, createCompany, patchCompany), as BD did. The name is stored trimmed
(clean_name) and `normalized_name` is set on every insert and rename; it never goes out. The
duplicate check and the insert are bd/contacts_service.py's, shared with the contacts router.

Who:
    GET (list, one)   any BD role
    POST, PATCH       salesperson, assistant, admin
"""
from __future__ import annotations

from typing import Any

from fastapi import Body, Depends, Request

from .. import auth, db, errors, paging, serialize, web
from ..contacts_service import COMPANY_NOT_FOUND, FIX, find_duplicates, insert_company
from ..normalize import clean_name, normalize_company

router = web.make_router()

# Like api.js: name trimmed and lower-cased, compared as JavaScript compares strings; ties by id.
_ORDER = 'lower(btrim(co.name)) collate "C", co.id'


def _text_fields(body: dict, fields: dict) -> None:
    for key in ("city", "industry"):
        if key in body and body[key] is not None and not isinstance(body[key], str):
            fields[key] = "Use text."


@router.get("/api/bd/companies")
def list_companies(request: Request, user: dict = Depends(auth.current_user)):
    """Type-ahead: a company matches when its normalized name starts with the normalized `q`,
    or one of its later words does (api.js listCompanies)."""
    q = request.query_params
    fields: dict = {}
    limit, offset = paging.page_params(q, fields)
    if fields:
        raise errors.bad_request(FIX, fields)
    needle = normalize_company(q.get("q")) if q.get("q") else ""
    where, params = "true", []
    if needle:
        where = "(starts_with(co.normalized_name, %s) or strpos(co.normalized_name, %s) > 0)"
        params = [needle, " " + needle]
    with db.connect() as conn:
        total = conn.execute("select count(*) as n from companies co where " + where, params).fetchone()["n"]
        rows = conn.execute(serialize.COMPANY_SELECT + " where " + where + " order by " + _ORDER
                            + " limit %s offset %s", params + [limit, offset]).fetchall()
    return {"ok": True, "total": int(total), "items": [serialize.company(r) for r in rows]}


@router.get("/api/bd/companies/{id}")
def get_company(id: str, user: dict = Depends(auth.current_user)):
    cid = paging.path_id(id, COMPANY_NOT_FOUND)
    with db.connect() as conn:
        company = serialize.fetch_company(conn, cid)
        if company is None:
            raise errors.not_found(COMPANY_NOT_FOUND)
        rows = conn.execute(serialize.CONTACT_SELECT + " where cs.company_id = %s and cs.archived_at is null"
                            " order by cs.id", (cid,)).fetchall()
    return {"ok": True, "company": company, "contacts": [serialize.contact_compact(r) for r in rows]}


@router.post("/api/bd/companies", status_code=201)
def post_company(body: Any = Body(None), user: dict = Depends(auth.require_role("salesperson", "assistant"))):
    """A new company, always (as the mock does); `possible_duplicates` lists the contacts already
    at a company with the same normalized name, as a hint."""
    body = paging.json_object(body)
    fields: dict = {}
    name = clean_name(body.get("name")) if isinstance(body.get("name"), str) else ""
    if not name:
        raise errors.bad_request("Type the company name.", {"name": "Required."})
    _text_fields(body, fields)
    if fields:
        raise errors.bad_request(FIX, fields)
    with db.connect() as conn:
        dups = find_duplicates(conn, name, None, None, None)
        co = insert_company(conn, name, body.get("city") or None, body.get("industry") or None)
        company = serialize.fetch_company(conn, co["id"])
    return {"ok": True, "company": company, "possible_duplicates": dups}


@router.patch("/api/bd/companies/{id}")
def patch_company(id: str, body: Any = Body(None), user: dict = Depends(auth.require_role("salesperson", "assistant"))):
    body = paging.json_object(body)
    fields: dict = {}
    name = None
    if "name" in body:
        name = clean_name(body["name"]) if isinstance(body["name"], str) else ""
        if not name:
            raise errors.bad_request("A company needs a name.", {"name": "Required."})
    _text_fields(body, fields)
    if fields:
        raise errors.bad_request(FIX, fields)
    cid = paging.path_id(id, COMPANY_NOT_FOUND)
    with db.connect() as conn:
        if conn.execute("select id from companies where id = %s", (cid,)).fetchone() is None:
            raise errors.not_found(COMPANY_NOT_FOUND)
        sets, params = [], []
        if name is not None:
            sets += ["name = %s", "normalized_name = %s"]
            params += [name, normalize_company(name)]
        for key in ("city", "industry"):
            if key in body:
                sets.append(key + " = %s")
                params.append(body[key])
        if sets:
            conn.execute("update companies set " + ", ".join(sets) + " where id = %s", params + [cid])
        company = serialize.fetch_company(conn, cid)
    return {"ok": True, "company": company}
