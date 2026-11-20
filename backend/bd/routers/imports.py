"""The workbook import: POST /api/bd/admin/import (.xlsx or .csv, a dry run first) and GET /api/bd/admin/imports.

BD's routers/imports.py, moved under /api/bd/ (#809) with the same checks, limits, answers and words.
Both routes are salesperson + assistant + admin (IMPORT_ROLES); a manager gets 403 "Your role can't do
that." and /api/bd/me's can.import is false for them. A salesperson's upload gives every contact it
adds to that salesperson, whatever the Owner column says (Hanz, 2026-11-16). The work is
bd/ops/import_workbook.py, which the command line shares, so the page's "Import now" and
`python -m bd.ops.import_workbook` do the same thing.

POST takes multipart/form-data: `file` and `dry_run` ("true" first, then "false" for "Import now";
anything but "false", "0", "no" or "off" is a dry run, so a forgotten flag never writes).

THE LIMITS (BD's, unchanged). The file is at most 10 MB (import_workbook.MAX_BYTES). The body is
capped WHILE IT STREAMS (BD's review finding SEC-1): a Content-Length over the limit is refused before
anything is read, and every body (a chunked one with no Content-Length too) goes through a receive
wrapper that counts its bytes and stops with the 413 the moment they pass the limit plus the
envelope's slack, so an oversized body is never parsed or spooled in full. The file itself is then
read up to the limit + 1 byte. An .xlsx is a zip: its own directory is checked before openpyxl opens
it (import_workbook.check_zip: 200 MB unpacked in all, 20 MB in one part, 100 times its packed size
for a part over 1 MB). The proposals site's nginx allows 25 MB on these routes, above the 10 MB.

WHY ONE PART OF THIS IS ASYNC. Every BD endpoint is a plain `def` (bd/db.py), and so are both of
these. Reading a streamed body has to await, so read_upload, the dependency that reads it, is async
(with its counting wrapper, capped). It runs AFTER the role check, takes no database connection and no
request slot, and hands the endpoint plain bytes; tests/test_bd_pool.py allows exactly these two.
The endpoint then parses the file in the threadpool BEFORE a database connection is taken (BD's
review finding SEC-2): a slow parse never holds a pooled connection; only the import and its
`imports` row do. A dry run and a real run both record an `imports` row and answer
{"ok": true, "import": Import}; only a real run keeps the contacts it adds or updates.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request
from starlette.types import Message, Receive

from .. import db, errors, serialize, web
from ..auth import require_role
from ..ops import import_workbook as importer
from ..paging import page_or_400

router = web.make_router()

# The multipart envelope around the file (boundaries, the dry_run field) is small.
_ENVELOPE_SLACK = 64 * 1024
# Who may import and read the import history (auth.can()["import"] says the same for /api/bd/me).
IMPORT_ROLES = ("salesperson", "assistant")
_FALSE = ("false", "0", "no", "off")


@dataclass(frozen=True)
class Upload:
    file_name: str
    data: bytes
    dry_run: bool


def _too_big() -> errors.ApiError:
    mb = importer.MAX_BYTES // (1024 * 1024)
    return errors.ApiError(413, "That file is too big. The limit is %d MB." % mb, code="bad_request",
                           fields={"file": "Pick a smaller file."})


def _capped_receive(receive: Receive, limit: int) -> Receive:
    """`receive`, counting the request body's bytes: past `limit` it raises the 413 (SEC-1)."""
    seen = 0

    async def capped() -> Message:
        nonlocal seen
        message = await receive()
        if message.get("type") == "http.request":
            seen += len(message.get("body") or b"")
            if seen > limit:
                raise _too_big()
        return message

    return capped


async def read_upload(request: Request) -> Upload:
    """The uploaded file and the dry_run flag, read under the cap. No database work here."""
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > importer.MAX_BYTES + _ENVELOPE_SLACK:
        raise _too_big()
    ctype = (request.headers.get("content-type") or "").lower()
    if not ctype.startswith("multipart/form-data"):
        raise errors.bad_request("Pick a file to import.", {"file": "Send the workbook or a CSV as a file upload."})
    capped = Request(request.scope, _capped_receive(request.receive, importer.MAX_BYTES + _ENVELOPE_SLACK))
    form = await capped.form(max_files=1, max_fields=10)
    try:
        upload = form.get("file")
        if upload is None or isinstance(upload, str) or not getattr(upload, "filename", None):
            raise errors.bad_request("Pick a file to import.", {"file": "Pick the workbook or a CSV."})
        file_name = importer.safe_file_name(upload.filename)
        if not file_name.lower().endswith(importer.ALLOWED_EXT):
            raise errors.bad_request(importer.BAD_TYPE_MESSAGE, {"file": importer.BAD_TYPE_FIELD})
        data = await upload.read(importer.MAX_BYTES + 1)
        if len(data) > importer.MAX_BYTES:
            raise _too_big()
        raw = form.get("dry_run")
        dry_run = not (isinstance(raw, str) and raw.strip().lower() in _FALSE)
    finally:
        await form.close()
    return Upload(file_name, data, dry_run)


def _file_error(exc: importer.ImportFileError) -> errors.ApiError:
    return errors.ApiError(exc.status, exc.message, code="bad_request", fields={"file": exc.field})


@router.post("/api/bd/admin/import")
def post_import(user: dict = Depends(require_role(*IMPORT_ROLES)), upload: Upload = Depends(read_upload)):
    # The role is checked first (the dependencies run in this order), so a refused caller's body is
    # never read. Then parse with no connection held (SEC-2): a slow or hostile workbook costs a
    # worker thread, never one of the pool's connections.
    try:
        parsed = importer.parse_file(upload.file_name, upload.data)
    except importer.ImportFileError as exc:
        raise _file_error(exc) from None
    with db.connect() as conn:
        import_id = importer.import_parsed(conn, upload.file_name, parsed, user, dry_run=upload.dry_run)
        row = conn.execute(serialize.IMPORT_SELECT + " where im.id = %s", (import_id,)).fetchone()
        return {"ok": True, "import": serialize.import_record(row)}


@router.get("/api/bd/admin/imports")
def list_imports(request: Request, user: dict = Depends(require_role(*IMPORT_ROLES))):
    """Every import, newest first, everyone's (a salesperson's too). The one paging rule: a 0 or
    missing limit is 100, a larger one is capped at 500."""
    limit, offset = page_or_400(request.query_params)
    with db.connect() as conn:
        total = conn.execute("select count(*) as n from imports").fetchone()["n"]
        rows = conn.execute(serialize.IMPORT_SELECT + " order by im.id desc limit %s offset %s",
                            (limit, offset)).fetchall()
    return {"ok": True, "items": [serialize.import_record(r) for r in rows], "total": int(total)}
