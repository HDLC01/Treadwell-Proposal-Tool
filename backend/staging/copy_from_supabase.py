"""Copy prod data (profiles → drafts → events) from cloud Supabase into the
staging DATA store (VPS Postgres via PostgREST). Idempotent.

Run inside the staging app container (it has supabase-py + both URLs in env):
    docker compose -f docker-compose.staging.yml exec app \
        python /app/staging/copy_from_supabase.py

Reads via the cloud service-role client (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY);
writes via the staging data client (SUPABASE_DATA_URL / SUPABASE_DATA_KEY → the
local PostgREST). profiles/drafts use upsert (keyed on their PK); events have an
identity PK so we drop 'id' and insert.
"""
import os
from supabase import create_client

src = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
dst = create_client(os.environ["SUPABASE_DATA_URL"], os.environ.get("SUPABASE_DATA_KEY") or "staging")


def _chunk(rows, n=200):
    for i in range(0, len(rows), n):
        yield rows[i:i + n]


def copy(table: str, *, upsert: bool, drop_id: bool = False) -> None:
    rows = src.table(table).select("*").execute().data or []
    print(f"{table}: read {len(rows)} row(s) from cloud Supabase")
    if not rows:
        return
    if drop_id:
        for r in rows:
            r.pop("id", None)
    written = 0
    for batch in _chunk(rows):
        if upsert:
            dst.table(table).upsert(batch).execute()
        else:
            dst.table(table).insert(batch).execute()
        written += len(batch)
    print(f"{table}: wrote {written} row(s) to staging")


if __name__ == "__main__":
    copy("profiles", upsert=True)
    copy("drafts", upsert=True)
    copy("events", upsert=False, drop_id=True)   # identity PK — let staging assign
    print("✓ copy complete")
