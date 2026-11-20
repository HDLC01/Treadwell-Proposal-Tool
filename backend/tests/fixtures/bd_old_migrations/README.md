# BD's original four migrations (test fixtures, #812)

These four files are BD CRM's own `backend/migrations/001` to `004`, copied **unchanged** from the
clean export of the BD repo that prod BD runs (the same files the tool ported into schema `bd` at
BD staging 14ff0d5, before it added a header and pinned search paths). They are not migrations of
this repo and nothing applies them except the cut-over copy's tests: `tests/_bd_old_source.py`
builds an **old BD database** from them (schema public, ledger `public.schema_migrations`, the way
BD's own runner applied them) so `bd/ops/cutover.py` can be tested against the real old shape.

Never edit them. If the old BD database ever gained a later migration, the cut-over copy's
preflight would refuse it, and the map in `bd/ops/cutover.py` would need the change first.
