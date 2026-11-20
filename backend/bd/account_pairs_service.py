"""The Likely duplicate accounts rule (#811, #802 Q21, Q36): which BD accounts may be one company.
Shared by its two readers; the Contacts page shows its pairs under the Possible duplicates filter.

    from bd import account_pairs_service as pairs
    found = pairs.likely_pairs(conn)          # [(cleaned name, a row, b row)], a.id < b.id
    hints = pairs.hints(conn, [ids])          # {company id: (phones, email domains)}
    phones, domains = pairs.shared(hints, a_id, b_id)

Its readers: GET /api/bd/contacts/accounts/duplicates (bd/routers/account_merge.py) and the cut-over
copy's one-time list for Hanz (bd/ops/cutover.py). It lives here, not in the router, so the command
uses the very same rule without importing a router (an ops module never does).

THE RULE (bd/normalize.py account_key). Two accounts that are not merged away are a likely pair when
their cleaned names are equal, at least one of them has a BD person who is not archived (they are
likely duplicate BD accounts: the BD tab shows that one), and the pair was not kept separate. A shared
phone, or a shared email domain that is not a free mail one, among their people who are not archived
is a HINT; a hint alone never makes a pair.

Reads only, with the connection's search_path (bd, pg_catalog), so it runs as bd_app. Rows are dict
rows (the pool's, and the cut-over command's).
"""
from __future__ import annotations

from . import normalize


def likely_pairs(conn) -> list:
    """Every likely pair, ordered by cleaned name, then the ids: [(key, a, b)], a["id"] < b["id"].
    a and b carry id, name, city, people_count (not archived) and on_bd."""
    rows = conn.execute(
        "select co.id, co.name, co.city,"
        " (select count(*) from contacts c where c.company_id = co.id and c.archived_at is null)::integer"
        " as people_count,"
        " exists (select 1 from contacts c where c.company_id = co.id and c.category = 'bd'"
        "   and c.archived_at is null) as on_bd"
        " from companies co where co.merged_into is null order by co.id").fetchall()
    groups: dict = {}
    for r in rows:
        key = normalize.account_key(r["name"])
        if key:
            groups.setdefault(key, []).append(r)
    kept = {(k["account_a"], k["account_b"]) for k in conn.execute(
        "select account_a, account_b from account_pairs_kept").fetchall()}
    found = [(key, a, b) for key, members in groups.items()
             for i, a in enumerate(members) for b in members[i + 1:]
             if (a["on_bd"] or b["on_bd"]) and (a["id"], b["id"]) not in kept]
    found.sort(key=lambda p: (p[0], p[1]["id"], p[2]["id"]))
    return found


def hints(conn, ids: list) -> dict:
    """{company id: (phones, email domains)} of the people who are not archived."""
    out: dict = {i: (set(), set()) for i in ids}
    if ids:
        for r in conn.execute("select company_id, phone_e164, email_lower from contacts"
                              " where company_id = any(%s) and archived_at is null", (ids,)).fetchall():
            phones, domains = out[r["company_id"]]
            if r["phone_e164"]:
                phones.add(r["phone_e164"])
            domain = normalize.email_domain(r["email_lower"])
            if domain and domain not in normalize.FREE_MAIL_DOMAINS:
                domains.add(domain)
    return out


def shared(found_hints: dict, a_id, b_id) -> tuple:
    """(phones, email domains) the two accounts share, from hints()."""
    return (found_hints[a_id][0] & found_hints[b_id][0], found_hints[a_id][1] & found_hints[b_id][1])
