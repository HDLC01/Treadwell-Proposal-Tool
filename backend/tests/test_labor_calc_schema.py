"""G5: library_labor_calc is in both schema files, the way default_on is, so a fresh database has it.

backend/ops/labor_calc.sql is how a RUNNING database gets the table; a database built from scratch
runs the schema files, and before this they did not know the table, so the Labor Calculator's save
returned an error on any rebuilt environment. Mutation: delete the create-table block from either
file -- the matching parametrised case fails. The columns are compared with the ops file's own, so
the three cannot drift apart.
"""
import pathlib
import re

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
_TBL = re.compile(r"create table if not exists public\.library_labor_calc\s*\((.*?)\n\);", re.S | re.I)


def _cols(sql):
    m = _TBL.search(sql.replace("\r\n", "\n"))
    assert m, "no create table for library_labor_calc"
    return [re.sub(r"\s+", " ", ln.strip().rstrip(",")) for ln in m.group(1).splitlines() if ln.strip()]


@pytest.mark.parametrize("rel", ["supabase_schema.sql", "staging/schema_pg.sql"])
def test_schema_files_carry_the_labor_calc_table_matching_the_ops_file(rel):
    ops = (BACKEND / "ops" / "labor_calc.sql").read_text(encoding="utf-8")
    sql = (BACKEND / rel).read_text(encoding="utf-8")
    assert _cols(sql) == _cols(ops)
    assert "grant select, insert, update, delete on public.library_labor_calc to service_role" in sql


def test_prod_schema_locks_the_table_with_rls():
    sql = (BACKEND / "supabase_schema.sql").read_text(encoding="utf-8")
    assert "alter table public.library_labor_calc enable row level security;" in sql
