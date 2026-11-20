"""Import the BD workbook (or a CSV) into the BD CRM: POST /api/bd/admin/import and a command line.

    cd backend
    python -m bd.ops.import_workbook path/to/workbook.xlsx --dry-run     # the preview, writes nothing
    python -m bd.ops.import_workbook path/to/workbook.xlsx               # import for real
    python -m bd.ops.import_workbook contacts.csv --by person@example.com

Ported from BD's ops/import_workbook.py (#809) with package-relative imports. The command line
connects to BD_DATABASE_URL (or --url) as BD's own login and never changes the schema: a database
behind the code is refused ("not up to date"), as the routes refuse it. The schema runner
(python -m bd.migrate) is run by hand, by the admin login.

THE WORKBOOK SHAPE (BD's product brief, "Workbook shape"; a real workbook is never committed):
  * "Business Development Accounts": header row 5, data from row 6. Company Name, Contact Name,
    Title, Phone, Email, City / Location, Industry, Lead Source, Stage, Last Activity Date,
    Next Step, Next Step Date, Meeting Date, Notes, Owner.
  * "Maintenance Accounts": header row 5. Account Name, Primary Contact, Title, Phone, Email,
    Address / Location, Account Type, Notes, Touch 1-3 Date, then the sheet's own formulas
    (Last Touch, Next Touch Due, Touches YTD, Status: ignored, the CRM derives them), Owner.
Columns are found by their header text, so their order does not matter. If row 5 does not hold
the headers, the first of rows 1-15 that names both the company and the contact column is used.

WHAT A ROW BECOMES
  * company: trimmed (leading spaces and non-breaking spaces dropped, runs collapsed), found by
    normalize_company() or created once per import (Atomic CRM's company resolver idea).
  * owner: "Avery" -> the active user named Avery; "Avery/Greg" -> owner Avery, co-owner Greg (a user
    when Greg has a login, else the stored name: UserRef {"id": null, "name": "Greg"}). An empty
    or unknown owner falls back to the first active salesperson, as BD's retired mock did. A SALESPERSON's
    upload is the exception (Hanz, 2026-11-16): every contact it adds is the uploader's and nobody
    is made a co-owner, whatever the Owner column says, so a salesperson can never hand contacts to
    someone else. A known contact that already has an owner keeps it (one with no owner is filled
    with the uploader, as an admin's import fills it from the column), and the meetings the file
    logs are in the uploader's name, never credited to the contact's owner (the code review,
    2026-11-16).
  * category bd (BD sheet) or maintenance (Maintenance sheet); frequency: a BD contact from the BD
    cadence setting (settings.bd_cadence: weekly 52, monthly 12, quarterly 4, the same number
    POST /api/bd/contacts stores; the view derives a BD number from the cadence anyway), a maintenance
    contact from settings.default_frequency.maintenance (3 by default); source "workbook" (a CSV:
    "import").
  * lead source, industry, stage, account type: matched to the settings lists ignoring case; an
    unknown lead source becomes "Other/Misc" (BD's retired mock's rule), other unknown values are kept.
  * Meeting Date (BD) on or before today -> a `meeting` interaction (a touch, the counting rule);
    a LATER Meeting Date has not happened, so it becomes the next step date when the row has none.
  * Touch 1/2/3 Date (Maintenance) on or before today -> a `meeting` interaction each; a later one
    is left out and reported.
  * Last Activity Date (BD) -> a `note` interaction "Last activity in the workbook." (the kind of
    activity is unknown, so it never counts as a touch), unless it is the meeting's day.
  Imported interactions have provider "workbook", noon Central on their date, and the external id
  "workbook:<contact>:<kind>:<date>", and are skipped when the contact already has one of that
  kind on that Central date: re-importing never double-counts a touch.

IDEMPOTENT on (normalized company, lower-case email): a known person is UPDATED or SKIPPED when
nothing changes. Review finding DATA-1: what an import wrote for each field is kept in
contacts.import_values, and a field is updated only when it is non-empty in the file, differs
from the contact, and EITHER the import never wrote that field (the first import of the person
writes what differs, as BD's retired mock's CSV import does) OR the file now says something other than
what the import last wrote (the file changed). So re-importing the same file changes nothing,
and an edit made in the app wins until the file itself changes that field. A next step / next
step date is never brought back when a touch on or after that date has met it (as logging the
touch cleared it). App-side notes, owner and co-owner are filled only when empty. A row without an email matches a contact at the same
company with no email and the same name. A match that is archived is skipped (re-importing must
not bring back a contact someone archived). A NEW person at a company that already has someone
is created with a duplicate FLAG (duplicate_of, "Same company name"), never blocked; the same
email or phone elsewhere flags too, as POST /api/bd/contacts does.

DRY RUN: the very same code runs inside a savepoint that is rolled back, so the preview's counts
are exactly what "Import now" will do. Both runs record an `imports` row (the history the Admin
page shows, as BD's retired mock did); only a real one keeps contacts, interactions and events.

Errors are per row ({"sheet", "row", "message"}): a row with no company or no contact name is not
imported; a value that cannot be read (a date that is not a date) is left blank and reported, the
rest of the row still imports. Messages never quote cell contents (they are real people).
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as _dt
import io
import json
import pathlib
import re
import sys
import zipfile
from typing import Any

from .. import appsettings, bizdate, events
from .. import phone as phonemod
from ..normalize import clean_name, email_key, lock_company_name, normalize_company

BD_SHEET = "Business Development Accounts"
MAINT_SHEET = "Maintenance Accounts"
HEADER_ROW = 5
HEADER_SCAN_ROWS = 15
CSV_SHEET = "CSV"

MAX_BYTES = 10 * 1024 * 1024            # the upload limit (the workbook is a few hundred KB)
MAX_UNPACKED = 200 * 1024 * 1024        # an .xlsx is a zip: refuse a zip bomb before opening it
# Per part (review finding SEC-2): openpyxl reads all of xl/sharedStrings.xml and each worksheet
# it opens, so a small, highly compressed part could take minutes to parse. The real workbook's
# parts are a few hundred KB, compressed 5-15 times.
MAX_PART_UNPACKED = 20 * 1024 * 1024    # any one part of the .xlsx, unpacked
MAX_PART_RATIO = 100                    # unpacked / packed, for a part over RATIO_FLOOR
RATIO_FLOOR = 1024 * 1024               # tiny parts (styles, rels) may compress far better
MAX_ROWS_PER_SHEET = 5000               # data rows read per sheet (the workbook has ~100)
MAX_BLANK_RUN = 500                     # stop reading a sheet after this many blank rows in a row
MAX_TEXT = 2000                         # a single-line value is cut to this many characters
MAX_NOTES = 20000

SOURCE_WORKBOOK = "workbook"
SOURCE_CSV = "import"
PROVIDER = "workbook"
IMPORT_LOCK_KEY = 728_100_301           # pg_advisory_xact_lock: one import at a time

ALLOWED_EXT = (".xlsx", ".csv")
BAD_TYPE_MESSAGE = "Pick an .xlsx or .csv file."
BAD_TYPE_FIELD = "Use the workbook or a CSV."
UNREADABLE_MESSAGE = "That file could not be read. Save it as an .xlsx workbook or a .csv and try again."

# Header text (lower case, letters and digits only) -> our field. Shared by both sheets; a CSV
# uses CSV_COLUMNS (BD's retired mock's list) instead.
WORKBOOK_COLUMNS = {
    "company": ("companyname", "company", "accountname", "account"),
    "name": ("contactname", "contact", "primarycontact", "name"),
    "title": ("title", "jobtitle"),
    "phone": ("phone", "phonenumber"),
    "email": ("email", "emailaddress"),
    "city": ("citylocation", "city", "location", "addresslocation", "address"),
    "industry": ("industry",),
    "lead_source": ("leadsource",),
    "stage": ("stage",),
    "last_activity": ("lastactivitydate", "lastactivity"),
    "next_step": ("nextstep",),
    "next_step_date": ("nextstepdate",),
    "meeting_date": ("meetingdate",),
    "notes": ("notes",),
    "owner": ("owner",),
    "account_type": ("accounttype",),
}
TOUCH_HEADER = re.compile(r"^touch(\d)(?:date)?$")

# BD's CSV columns (its retired mock's frontend/js/api.js CSV_COLUMNS).
CSV_COLUMNS = {
    "company": ("company", "companyname", "account", "accountname"),
    "name": ("name", "contact", "contactname", "fullname"),
    "email": ("email", "emailaddress"),
    "phone": ("phone", "phonenumber", "mobile"),
    "title": ("title", "jobtitle"),
    "city": ("city", "location"),
    "industry": ("industry",),
    "lead_source": ("leadsource",),
    "category": ("category",),
}

# What an update may change, per source. A CSV changes what BD's retired mock's CSV import changes.
WORKBOOK_UPDATE_FIELDS = ("title", "phone", "city", "industry", "lead_source", "stage", "account_type",
                          "next_step", "next_step_date")
CSV_UPDATE_FIELDS = ("phone", "title", "city")

_ODD_SPACES = re.compile("[   ﻿]")
_HEADER_KEY = re.compile(r"[^a-z0-9]")
_OWNER_SPLIT = re.compile(r"\s*(?:/|&|\+|,|\band\b)\s*", re.I)
_EMAIL_OK = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y", "%Y/%m/%d",
                 "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y", "%d-%b-%y", "%b %d %Y", "%B %d %Y")


class ImportFileError(Exception):
    """The upload itself is unusable (wrong type, too big, not a workbook): a 400, no record."""

    def __init__(self, message: str, field: str | None = None, status: int = 400):
        super().__init__(message)
        self.message = message
        self.field = field or "That file could not be used."
        self.status = status


@dataclasses.dataclass
class Row:
    """One spreadsheet row, read and cleaned (nothing looked up yet)."""
    sheet: str
    row: int
    category: str = "bd"
    company: str = ""
    name: str = ""
    title: str | None = None
    phone: str | None = None
    email: str | None = None
    city: str | None = None
    industry: str | None = None
    lead_source: str | None = None
    stage: str | None = None
    account_type: str | None = None
    next_step: str | None = None
    next_step_date: _dt.date | None = None
    meeting_date: _dt.date | None = None
    last_activity: _dt.date | None = None
    touches: list = dataclasses.field(default_factory=list)       # [(n, date)]
    notes: str = ""
    owner: str = ""
    problems: list = dataclasses.field(default_factory=list)      # non-fatal messages
    update_fields: tuple = WORKBOOK_UPDATE_FIELDS


@dataclasses.dataclass
class Parsed:
    rows: list
    errors: list            # file/sheet level problems ({"sheet", "row", "message"})
    rows_read: int
    source: str


# ── cell values ──────────────────────────────────────────────────────────────────────────────
def header_key(v) -> str:
    return _HEADER_KEY.sub("", _ODD_SPACES.sub(" ", "" if v is None else str(v)).lower())


def cell_text(v, limit: int = MAX_TEXT) -> str:
    """A single-line value: odd spaces made spaces, runs collapsed, trimmed. 816.0 -> "816"."""
    if v is None:
        return ""
    if isinstance(v, bool):
        v = "TRUE" if v else "FALSE"
    elif isinstance(v, float) and v.is_integer():
        v = int(v)
    elif isinstance(v, _dt.datetime):
        v = v.date().isoformat() if v.time() == _dt.time(0) else v.isoformat(sep=" ")
    elif isinstance(v, _dt.date):
        v = v.isoformat()
    return clean_name(v)[:limit]


def cell_notes(v) -> str:
    """Notes keep their line breaks; each line is trimmed."""
    if v is None:
        return ""
    text = _ODD_SPACES.sub(" ", str(v)).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join(lines).strip()[:MAX_NOTES]


def cell_date(v):
    """A date from a date cell, an Excel serial number or typed text; None for nothing.
    ValueError when there is something that is not a date."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, _dt.datetime):
        d = v.date()
    elif isinstance(v, _dt.date):
        d = v
    elif isinstance(v, (int, float)) and not isinstance(v, bool):
        if not 20000 <= float(v) <= 80000:
            raise ValueError("not an Excel date serial")
        from openpyxl.utils.datetime import from_excel
        d = from_excel(v).date()
    else:
        text = _ODD_SPACES.sub(" ", str(v)).strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}[ T]", text):
            text = text[:10]
        parsed: _dt.date | None = None
        for fmt in _DATE_FORMATS:
            try:
                parsed = _dt.datetime.strptime(text, fmt).date()
                break
            except ValueError:
                continue
        if parsed is None:
            raise ValueError("not a date")
        d = parsed
    if not 1990 <= d.year <= 2100:
        raise ValueError("date out of range")
    return d


def clean_email(v):
    s = cell_text(v).replace(" ", "").lower()
    if s.lower().startswith("mailto:"):
        s = s[7:]
    return s if _EMAIL_OK.match(s) else None


def safe_file_name(name) -> str:
    """The upload's base name: no folders, no control characters, at most 200 characters."""
    base = re.split(r"[\\/]", str(name or ""))[-1]
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
    return base[:200]


def check_file(file_name: str, data: bytes) -> str:
    """Raise ImportFileError for an upload we will not read; returns ".xlsx" or ".csv"."""
    lower = (file_name or "").lower()
    ext = next((e for e in ALLOWED_EXT if lower.endswith(e)), None)
    if not ext:
        raise ImportFileError(BAD_TYPE_MESSAGE, BAD_TYPE_FIELD)
    if len(data) > MAX_BYTES:
        raise ImportFileError("That file is too big. The limit is %d MB." % (MAX_BYTES // (1024 * 1024)),
                              "Pick a smaller file.", status=413)
    if ext == ".xlsx":
        if not data:
            raise ImportFileError("That file is empty.", "Pick the workbook again.")
        if not data.startswith(b"PK\x03\x04"):
            raise ImportFileError(UNREADABLE_MESSAGE, BAD_TYPE_FIELD)
    return ext


# ── reading a workbook ───────────────────────────────────────────────────────────────────────
def _columns(header_cells, table):
    col: dict[str, int] = {}
    touches: dict[int, int] = {}
    for idx, h in enumerate(header_cells):
        key = header_key(h)
        if not key:
            continue
        m = TOUCH_HEADER.match(key)
        if m:
            touches.setdefault(int(m.group(1)), idx)
            continue
        for field, names in table.items():
            if field not in col and key in names:
                col[field] = idx
                break
    return col, touches


def _find_header(rows_head):
    """(row number, cells) of the header: row 5 when it names the company and contact columns,
    else the first such row in the first HEADER_SCAN_ROWS rows."""
    def good(cells):
        col, _ = _columns(cells, WORKBOOK_COLUMNS)
        return "company" in col and "name" in col
    by_num = dict(rows_head)
    if HEADER_ROW in by_num and good(by_num[HEADER_ROW]):
        return HEADER_ROW, by_num[HEADER_ROW]
    for num, cells in rows_head:
        if good(cells):
            return num, cells
    return None, None


def _row_from_cells(sheet, num, cells, col, touches, category, today):
    def get(field):
        i = col.get(field)
        return cells[i] if i is not None and i < len(cells) else None

    r = Row(sheet=sheet, row=num, category=category)
    r.company = cell_text(get("company"))
    r.name = cell_text(get("name"))
    r.title = cell_text(get("title")) or None
    r.phone = cell_text(get("phone"), 40) or None
    raw_email = cell_text(get("email"))
    r.email = clean_email(raw_email)
    if raw_email and not r.email and raw_email.lower() not in ("n/a", "na", "none", "-", "--"):
        r.problems.append("Email is not an email address; left blank.")
    r.city = cell_text(get("city")) or None
    r.industry = cell_text(get("industry")) or None
    r.lead_source = cell_text(get("lead_source")) or None
    r.stage = cell_text(get("stage")) or None
    r.account_type = cell_text(get("account_type")) or None
    r.next_step = cell_text(get("next_step")) or None
    r.notes = cell_notes(get("notes"))
    r.owner = cell_text(get("owner"))

    def date_of(field, label):
        try:
            return cell_date(get(field))
        except ValueError:
            r.problems.append("%s is not a date; left blank." % label)
            return None

    r.next_step_date = date_of("next_step_date", "Next Step Date")
    r.last_activity = date_of("last_activity", "Last Activity Date")
    meeting = date_of("meeting_date", "Meeting Date")
    if meeting is not None and meeting > today:
        # A meeting that has not happened yet is not a touch: it is the next step.
        if r.next_step_date is None:
            r.next_step_date = meeting
            r.next_step = r.next_step or "Meeting"
        meeting = None
    r.meeting_date = meeting
    for n in sorted(touches):
        i = touches[n]
        label = "Touch %d Date" % n
        try:
            d = cell_date(cells[i] if i < len(cells) else None)
        except ValueError:
            r.problems.append("%s is not a date; left blank." % label)
            continue
        if d is None:
            continue
        if d > today:
            r.problems.append("%s is after today, so it was left out." % label)
            continue
        r.touches.append((n, d))
    return r


def _blank(r: Row) -> bool:
    return not (r.company or r.name or r.title or r.phone or r.email or r.notes)


def check_zip(data: bytes) -> None:
    """Refuse an .xlsx whose parts would take too long to unpack and parse, from the zip's own
    directory, before openpyxl opens it: the total unpacked size, each part's unpacked size and
    each sizeable part's compression ratio (review finding SEC-2)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
    except (zipfile.BadZipFile, ValueError, OSError):
        raise ImportFileError(UNREADABLE_MESSAGE, BAD_TYPE_FIELD) from None
    too_big = ImportFileError("That workbook is too big to read.", "Pick a smaller file.", status=413)
    if sum(i.file_size for i in infos) > MAX_UNPACKED:
        raise too_big
    for i in infos:
        if i.file_size > MAX_PART_UNPACKED:
            raise too_big
        if i.file_size > RATIO_FLOOR and i.file_size > MAX_PART_RATIO * max(1, i.compress_size):
            raise too_big


def read_xlsx(data: bytes, today=None) -> Parsed:
    today = today or bizdate.today_central()
    check_zip(data)

    import openpyxl
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:  # openpyxl raises many kinds for a file that is not a workbook
        raise ImportFileError(UNREADABLE_MESSAGE, BAD_TYPE_FIELD) from None

    rows: list[Row] = []
    errors: list[dict] = []
    read = 0
    try:
        by_key: dict[str, Any] = {}
        for ws in wb.worksheets:
            by_key.setdefault(header_key(ws.title), ws)
        found = False
        for sheet_name, category in ((BD_SHEET, "bd"), (MAINT_SHEET, "maintenance")):
            sheet = by_key.get(header_key(sheet_name))
            if sheet is None:
                continue
            found = True
            got, errs, n = _read_sheet(sheet, sheet_name, category, today)
            rows.extend(got)
            errors.extend(errs)
            read += n
        if not found:
            errors.append({"sheet": "Workbook", "row": 1,
                           "message": 'This workbook has no "%s" or "%s" sheet.' % (BD_SHEET, MAINT_SHEET)})
    except ImportFileError:
        raise
    except Exception:  # a damaged sheet part
        raise ImportFileError(UNREADABLE_MESSAGE, BAD_TYPE_FIELD) from None
    finally:
        wb.close()
    return Parsed(rows=rows, errors=errors, rows_read=read, source=SOURCE_WORKBOOK)


def _read_sheet(ws, sheet_name, category, today):
    it = ws.iter_rows(values_only=True)
    head = []
    for num, cells in enumerate(it, start=1):
        head.append((num, tuple(cells)))
        if num >= HEADER_SCAN_ROWS:
            break
    hnum, hcells = _find_header(head)
    if hnum is None:
        return [], [{"sheet": sheet_name, "row": HEADER_ROW,
                     "message": "Row %d should name the columns (the company and the contact)." % HEADER_ROW}], 0
    col, touches = _columns(hcells, WORKBOOK_COLUMNS)
    if category == "bd":
        touches = {}            # only the Maintenance sheet has touch dates
    else:
        for f in ("lead_source", "stage", "next_step", "next_step_date", "meeting_date", "last_activity"):
            col.pop(f, None)

    def data_rows():
        for num, cells in head:
            if num > hnum:
                yield num, cells
        for num, cells in enumerate(it, start=len(head) + 1):
            yield num, tuple(cells)

    rows, errors, read, blank_run = [], [], 0, 0
    for num, cells in data_rows():
        r = _row_from_cells(sheet_name, num, cells, col, touches, category, today)
        if _blank(r):
            blank_run += 1
            if blank_run >= MAX_BLANK_RUN:
                break
            continue
        blank_run = 0
        if read >= MAX_ROWS_PER_SHEET:
            errors.append({"sheet": sheet_name, "row": num,
                           "message": "Only the first %d rows of this sheet were read." % MAX_ROWS_PER_SHEET})
            break
        read += 1
        rows.append(r)
    return rows, errors, read


# ── reading a CSV ────────────────────────────────────────────────────────────────────────────
def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ImportFileError(UNREADABLE_MESSAGE, BAD_TYPE_FIELD)


def read_csv(data: bytes, today=None) -> Parsed:
    """BD's retired mock's CSV import: a header row with at least Company and Name; Email, Phone, Title,
    City, Industry, Lead Source, Category optional. Row numbers are the spreadsheet's."""
    text = _decode(data)
    try:
        records = list(csv.reader(io.StringIO(text, newline="")))
    except csv.Error:
        raise ImportFileError(UNREADABLE_MESSAGE, BAD_TYPE_FIELD) from None
    numbered = [(n, rec) for n, rec in enumerate(records, start=1) if any(str(x).strip() for x in rec)]
    if not numbered:
        return Parsed(rows=[], errors=[{"sheet": CSV_SHEET, "row": 1, "message": "The file is empty."}],
                      rows_read=0, source=SOURCE_CSV)
    hnum, header = numbered[0]
    col, _ = _columns(header, CSV_COLUMNS)
    body = numbered[1:]
    if "company" not in col or "name" not in col:
        return Parsed(rows=[], errors=[{"sheet": CSV_SHEET, "row": hnum,
                                        "message": "The first row needs Company and Name columns."}],
                      rows_read=len(body), source=SOURCE_CSV)
    rows, errors = [], []
    for num, rec in body[:MAX_ROWS_PER_SHEET]:
        def get(field, rec=rec):
            i = col.get(field)
            return rec[i] if i is not None and i < len(rec) else None
        cat = cell_text(get("category")).lower()
        r = Row(sheet=CSV_SHEET, row=num, category="maintenance" if cat == "maintenance" else "bd",
                update_fields=CSV_UPDATE_FIELDS)
        r.company = cell_text(get("company"))
        r.name = cell_text(get("name"))
        r.email = clean_email(get("email"))
        if cell_text(get("email")) and not r.email:
            r.problems.append("Email is not an email address; left blank.")
        r.phone = cell_text(get("phone"), 40) or None
        r.title = cell_text(get("title")) or None
        r.city = cell_text(get("city")) or None
        r.industry = cell_text(get("industry")) or None
        r.lead_source = cell_text(get("lead_source")) or None
        rows.append(r)
    if len(body) > MAX_ROWS_PER_SHEET:
        errors.append({"sheet": CSV_SHEET, "row": body[MAX_ROWS_PER_SHEET][0],
                       "message": "Only the first %d rows of this file were read." % MAX_ROWS_PER_SHEET})
    return Parsed(rows=rows, errors=errors, rows_read=min(len(body), MAX_ROWS_PER_SHEET), source=SOURCE_CSV)


def parse_file(file_name: str, data: bytes, today=None) -> Parsed:
    ext = check_file(file_name, data)
    return read_xlsx(data, today) if ext == ".xlsx" else read_csv(data, today)


# ── writing ──────────────────────────────────────────────────────────────────────────────────
def _pick(value, options):
    """The settings spelling of `value` (ignoring case and spacing), else None."""
    key = header_key(value)
    for o in options or []:
        if header_key(o) == key:
            return o
    return None


def _canon(value, options):
    if not value:
        return None
    return _pick(value, options) or value


def _noon(d: _dt.date) -> _dt.datetime:
    return _dt.datetime.combine(d, _dt.time(12, 0)).replace(tzinfo=bizdate.BIZ_TZ)


class _Importer:
    """One import run over an open connection (inside the caller's transaction)."""

    def __init__(self, conn, source: str, actor):
        self.conn = conn
        self.source = source
        self.actor = actor
        self.today = bizdate.today_central()
        self.settings = appsettings.load(conn)
        self.counts = {"created": 0, "updated": 0, "skipped": 0, "possible_duplicates": 0}
        self.errors: list[dict] = []
        # A salesperson's upload: every contact it adds is theirs and every meeting it logs is in
        # their name (Hanz, 2026-11-16). None for an assistant's or admin's upload (the Owner column).
        self.salesperson_uploader_id = (actor.get("id") if isinstance(actor, dict)
                                        and actor.get("role") == "salesperson" else None)

        users = conn.execute("select id, name, role from users where active order by id").fetchall()
        self.user_by_name: dict[str, dict] = {}
        firsts: dict[str, list[dict]] = {}
        for u in users:
            self.user_by_name.setdefault(clean_name(u["name"]).lower(), u)
            first = clean_name(u["name"]).lower().split(" ")[0]
            firsts.setdefault(first, []).append(u)
        for first, us in firsts.items():
            if len(us) == 1:
                self.user_by_name.setdefault(first, us[0])
        sales = [u for u in users if u["role"] == "salesperson"]
        self.default_owner = sales[0] if sales else None

        self.companies: dict[str, dict] = {}
        for co in conn.execute("select id, name, normalized_name from companies order by id").fetchall():
            self.companies.setdefault(co["normalized_name"], co)

        # (company_norm, email) or (company_norm, None, name) -> contact
        self.by_key: dict[tuple, dict] = {}
        # company_norm -> [contact id] (not archived), oldest first
        self.live_by_company: dict[str, list[int]] = {}
        self.live_by_email: dict[str, list[int]] = {}
        self.live_by_phone: dict[str, list[int]] = {}
        rows = conn.execute(
            "select c.*, co.normalized_name as company_norm from contacts c"
            " join companies co on co.id = c.company_id order by c.id").fetchall()
        for c in rows:
            self._index(dict(c))

    # the in-memory index (kept up to date as rows are created, so a file that names a person
    # twice updates the first one instead of creating two)
    def _key(self, company_norm, email, name):
        return (company_norm, email) if email else (company_norm, None, clean_name(name).lower())

    def _index(self, c):
        self.by_key.setdefault(self._key(c["company_norm"], c["email_lower"], c["name"]), c)
        if c.get("archived_at") is None:
            self.live_by_company.setdefault(c["company_norm"], []).append(c["id"])
            if c.get("email_lower"):
                self.live_by_email.setdefault(c["email_lower"], []).append(c["id"])
            if c.get("phone_e164"):
                self.live_by_phone.setdefault(c["phone_e164"], []).append(c["id"])

    def problem(self, r: Row, message: str):
        self.errors.append({"sheet": r.sheet, "row": r.row, "message": message})

    def owner_of(self, text):
        if self.salesperson_uploader_id is not None:
            return self.salesperson_uploader_id, None, None
        parts = [p for p in _OWNER_SPLIT.split(text or "") if p.strip()]
        owner = self.user_by_name.get(parts[0].lower()) if parts else None
        owner = owner or self.default_owner
        co_id, co_name = None, None
        if len(parts) > 1:
            co = self.user_by_name.get(parts[1].lower())
            if co is not None:
                if owner is None or co["id"] != owner["id"]:
                    co_id = co["id"]
            elif clean_name(parts[1]).lower() != clean_name(parts[0]).lower():
                co_name = clean_name(parts[1])[:120]
        return (owner["id"] if owner else None), co_id, co_name

    def lead_source_of(self, r: Row):
        """(value for a new contact, value an update may set or None)."""
        known = _pick(r.lead_source, self.settings.get("lead_sources")) if r.lead_source else None
        if known:
            return known, known
        if r.lead_source is None and r.category == "maintenance" and r.sheet != CSV_SHEET:
            default = _pick("Current Account", self.settings.get("lead_sources"))
            return default or "Other/Misc", None
        return "Other/Misc", None

    def company_for(self, r: Row, norm: str):
        co = self.companies.get(norm)
        if co is None:
            # The lock the app's find-or-create takes too (review DATA-2), then a fresh look: a
            # person added in the app since this run started may have made the company already.
            lock_company_name(self.conn, norm)
            co = self.conn.execute("select id, name, normalized_name from companies where normalized_name = %s"
                                   " order by id limit 1", (norm,)).fetchone()
        if co is None:
            co = self.conn.execute(
                "insert into companies (name, normalized_name, city, industry) values (%s, %s, %s, %s)"
                " returning id, name, normalized_name",
                (r.company, norm, r.city, _canon(r.industry, self.settings.get("industries")))).fetchone()
            self.companies[norm] = co
        return co

    def duplicate_of(self, norm, email, e164):
        for ids, reason in ((self.live_by_company.get(norm), "Same company name"),
                            (self.live_by_email.get(email) if email else None, "Same email"),
                            (self.live_by_phone.get(e164) if e164 else None, "Same phone")):
            if ids:
                return ids[0], reason
        return None, None

    def run(self, rows):
        for r in rows:
            for msg in r.problems:
                self.problem(r, msg)
            if not r.company:
                self.problem(r, "No company name.")
                continue
            if not r.name:
                self.problem(r, "No contact name.")
                continue
            norm = normalize_company(r.company)
            if not norm:
                self.problem(r, "No company name.")
                continue
            hit = self.by_key.get(self._key(norm, email_key(r.email), r.name))
            if hit is None:
                self.create(r, norm)
            elif hit.get("archived_at") is not None:
                self.counts["skipped"] += 1
            elif self.update(r, hit):
                self.counts["updated"] += 1
            else:
                self.counts["skipped"] += 1
        return self.counts, self.errors

    def create(self, r: Row, norm: str):
        s = self.settings
        co = self.company_for(r, norm)
        owner_id, co_id, co_name = self.owner_of(r.owner)
        lead_source, _ = self.lead_source_of(r)
        if r.category == "maintenance":
            freq = (s.get("default_frequency") or {}).get("maintenance") or 3
        else:
            freq = appsettings.CADENCE_FREQ.get(s.get("bd_cadence") or "", 4)
        freq = min(52, max(1, int(freq)))
        e164 = phonemod.to_e164(r.phone)
        dup_id, dup_reason = self.duplicate_of(norm, email_key(r.email), e164)
        c = self.conn.execute(
            "insert into contacts (company_id, name, title, email, phone, city, industry, lead_source,"
            " stage, category, account_type, owner_id, co_owner_id, co_owner_name, frequency_per_year,"
            " confirmed, importance, next_step, next_step_date, duplicate_of, duplicate_reason, source,"
            " notes, import_values) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
            " false, 1, %s, %s, %s, %s, %s, %s, %s::jsonb) returning *",
            (co["id"], r.name, r.title, r.email, r.phone, r.city,
             _canon(r.industry, s.get("industries")), lead_source,
             _canon(r.stage, s.get("stages")), r.category,
             _canon(r.account_type, s.get("account_types")), owner_id, co_id, co_name, freq,
             r.next_step, r.next_step_date, dup_id, dup_reason, self.source, r.notes,
             json.dumps(self.import_values(r)))).fetchone()
        c = dict(c)
        c["company_norm"] = norm
        events.log_event(self.conn, "created", self.actor, c["id"],
                         {"source": self.source},
                         detail="Imported from the workbook" if self.source == SOURCE_WORKBOOK
                         else "Imported from a file")
        self._index(c)
        self.add_interactions(r, c, existing=False)
        self.counts["created"] += 1
        if dup_id is not None:
            self.counts["possible_duplicates"] += 1

    def update_values(self, r: Row) -> dict:
        """The values this row offers an update, per field (None or "" offers nothing)."""
        s = self.settings
        _, update_lead = self.lead_source_of(r)
        return {
            "title": r.title, "phone": r.phone, "city": r.city,
            "industry": _canon(r.industry, s.get("industries")),
            "lead_source": update_lead,
            "stage": _canon(r.stage, s.get("stages")),
            "account_type": _canon(r.account_type, s.get("account_types")),
            "next_step": r.next_step, "next_step_date": r.next_step_date,
        }

    def import_values(self, r: Row, values: dict | None = None) -> dict:
        """What this row says for each field an update may change, as JSON (dates ISO): the
        contacts.import_values the next import compares the file with (review DATA-1)."""
        values = self.update_values(r) if values is None else values
        out = {}
        for f in r.update_fields:
            v = values.get(f)
            if v is None or v == "":
                continue
            out[f] = v.isoformat() if isinstance(v, _dt.date) else v
        return out

    @staticmethod
    def _same(field, a, b) -> bool:
        if field == "phone":
            x, y = phonemod.to_e164(a), phonemod.to_e164(b)
            return (x == y) if (x and y) else (str(a or "") == str(b or ""))
        if isinstance(a, _dt.date):
            a = a.isoformat()
        if isinstance(b, _dt.date):
            b = b.isoformat()
        return a == b

    def step_met(self, c: dict, step_date) -> bool:
        """True when a touch on or after `step_date` (Central) has met that next step, so the
        import must not bring it back (apply_touch's rule; review DATA-1)."""
        if step_date is None:
            return False
        row = self.conn.execute(
            "select 1 from interactions where contact_id = %s and counts_as_touch"
            " and bd_date(occurred_at) >= %s and bd_date(occurred_at) <= bd_today() limit 1",
            (c["id"], step_date)).fetchone()
        return row is not None

    def update(self, r: Row, c: dict) -> bool:
        new = {}
        values = self.update_values(r)
        last = c.get("import_values") or {}
        record = {**last, **self.import_values(r, values)}
        step_date = values.get("next_step_date") or c.get("next_step_date")
        for f in r.update_fields:
            v = values.get(f)
            if v is None or v == "":
                continue
            if f in last and self._same(f, v, last[f]):
                continue        # the file still says what the import last wrote: the app's value wins
            if f in ("next_step", "next_step_date") and self.step_met(c, step_date):
                continue        # a touch on or after that date met the step (DATA-1)
            if not self._same(f, v, c.get(f)):
                new[f] = v
        if r.sheet != CSV_SHEET:
            if r.notes and not (c.get("notes") or "").strip():
                new["notes"] = r.notes
            owner_id, co_id, co_name = self.owner_of(r.owner)
            if c.get("owner_id") is None and owner_id is not None:
                new["owner_id"] = owner_id
            if c.get("co_owner_id") is None and not c.get("co_owner_name") and (co_id or co_name):
                if co_id is not None and co_id != (new.get("owner_id") or c.get("owner_id")):
                    new["co_owner_id"] = co_id
                elif co_name:
                    new["co_owner_name"] = co_name
        if new:
            # Column names are this function's own constants; every value is a parameter.
            from psycopg import sql

            assigns = sql.SQL(", ").join(
                sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder()) for k in new)
            self.conn.execute(sql.SQL("update contacts set {} where id = {}").format(assigns, sql.Placeholder()),
                              (*new.values(), c["id"]))
            c.update(new)
        if record != last:
            # Bookkeeping only (not an "update" on its own): what the file said this time.
            self.conn.execute("update contacts set import_values = %s::jsonb where id = %s",
                              (json.dumps(record), c["id"]))
            c["import_values"] = record
        added = self.add_interactions(r, c, existing=True)
        return bool(new) or added > 0

    def add_interactions(self, r: Row, c: dict, existing: bool) -> int:
        """Meeting and touch dates as `meeting` interactions, the last activity as a `note`."""
        wanted = []
        if r.meeting_date is not None:
            wanted.append(("meeting", r.meeting_date, "Meeting (from the workbook)."))
        for n, d in r.touches:
            wanted.append(("meeting", d, "Touch %d (from the workbook)." % n))
        if r.last_activity is not None and r.last_activity <= self.today and r.last_activity != r.meeting_date:
            wanted.append(("note", r.last_activity, "Last activity in the workbook."))
        added, seen = 0, set()
        for kind, d, summary in wanted:
            if (kind, d) in seen:
                continue
            seen.add((kind, d))
            if kind == "note" and any(k == "meeting" and dd == d for k, dd, _ in wanted):
                continue
            if existing:
                dup = self.conn.execute(
                    "select 1 from interactions where contact_id = %s and kind = %s"
                    " and bd_date(occurred_at) = %s limit 1", (c["id"], kind, d)).fetchone()
                if dup:
                    continue
            row = self.conn.execute(
                "insert into interactions (contact_id, kind, direction, outcome, occurred_at, summary,"
                " provider, external_id, user_id) values (%s, %s, null, null, %s, %s, %s, %s, %s)"
                " on conflict (provider, external_id) do nothing returning id",
                (c["id"], kind, _noon(d), summary, PROVIDER,
                 "workbook:%d:%s:%s" % (c["id"], kind, d.isoformat()),
                 self.salesperson_uploader_id or c.get("owner_id"))).fetchone()
            if row:
                added += 1
        return added


def import_rows(conn, parsed: Parsed, actor=None, dry_run: bool = True):
    """Apply `parsed` on `conn` (in a savepoint that a dry run rolls back). Returns
    (counts, errors): counts has created / updated / skipped / possible_duplicates."""
    import psycopg

    result = {}
    with conn.transaction():
        # Held until the caller's transaction ends (a savepoint rollback does not drop it when it
        # was taken outside the savepoint), so two imports never create the same company twice.
        conn.execute("select pg_advisory_xact_lock(%s)", (IMPORT_LOCK_KEY,))
        with conn.transaction():
            imp = _Importer(conn, parsed.source, actor)
            counts, errs = imp.run(parsed.rows)
            result = {"counts": counts, "errors": errs}
            if dry_run:
                raise psycopg.Rollback()
    return result["counts"], list(parsed.errors) + result["errors"]


def import_file(conn, file_name: str, data: bytes, actor=None, dry_run: bool = True) -> int:
    """Parse, import (or preview) and record the run. Returns the new imports row's id.
    Raises ImportFileError for an upload that cannot be read. The caller commits. (The API
    parses first with no connection held and then calls import_parsed: review SEC-2.)"""
    file_name = safe_file_name(file_name)
    return import_parsed(conn, file_name, parse_file(file_name, data), actor, dry_run)


def import_parsed(conn, file_name: str, parsed: Parsed, actor=None, dry_run: bool = True) -> int:
    """Import (or preview) an already parsed file and record the run in `imports`. Returns the
    new imports row's id. The caller commits."""
    file_name = safe_file_name(file_name)
    with conn.transaction():
        counts, errs = import_rows(conn, parsed, actor, dry_run)
        actor_id = actor.get("id") if isinstance(actor, dict) else actor
        row = conn.execute(
            "insert into imports (file_name, dry_run, finished_at, by_id, rows_read, created, updated,"
            " skipped, possible_duplicates, errors) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)"
            " returning id",
            (file_name, bool(dry_run), bizdate.now_central(), actor_id, parsed.rows_read,
             counts["created"], counts["updated"], counts["skipped"], counts["possible_duplicates"],
             json.dumps(errs))).fetchone()
        import_id = row["id"] if isinstance(row, dict) else row[0]
        if not dry_run:
            events.log_event(conn, "import_run", actor, None,
                             {"import_id": import_id, "file_name": file_name, **counts})
    return import_id


# ── the command line ─────────────────────────────────────────────────────────────────────────
NOT_UP_TO_DATE = "the BD database is not up to date: run python -m bd.migrate first"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Import the BD workbook (.xlsx) or a CSV into the BD CRM.")
    ap.add_argument("file", help="the .xlsx workbook or a .csv")
    ap.add_argument("--dry-run", action="store_true", help="preview only: count what would change, write nothing")
    ap.add_argument("--url", default=None, help="database URL (default: BD_DATABASE_URL)")
    ap.add_argument("--by", default=None, help="email of the BD user to record as running the import")
    args = ap.parse_args(argv)

    from .. import db, ledger, serialize

    path = pathlib.Path(args.file)
    try:
        size = path.stat().st_size
    except OSError:
        print("cannot read %s" % path.name, file=sys.stderr)
        return 2
    if size > MAX_BYTES:
        print("that file is too big (the limit is %d MB)" % (MAX_BYTES // (1024 * 1024)), file=sys.stderr)
        return 2
    data = path.read_bytes()
    conn = db.direct(args.url or db.database_url(), autocommit=False)
    try:
        if ledger.ledger_behind(conn):
            print(NOT_UP_TO_DATE, file=sys.stderr)
            return 2
        actor = None
        if args.by:
            actor = conn.execute("select * from users where email = %s", (args.by.strip().lower(),)).fetchone()
            if actor is None:
                print("no BD user with that email", file=sys.stderr)
                return 2
        try:
            import_id = import_file(conn, path.name, data, actor, dry_run=args.dry_run)
        except ImportFileError as exc:
            conn.rollback()
            print(exc.message, file=sys.stderr)
            return 2
        rec_row = conn.execute(serialize.IMPORT_SELECT + " where im.id = %s", (import_id,)).fetchone()
        if rec_row is None:
            raise RuntimeError("the import record was not written")
        rec = serialize.import_record(rec_row)
        conn.commit()
    finally:
        conn.close()
    print(("Practice run (nothing imported): " if rec["dry_run"] else "Imported: ")
          + "%(rows_read)d rows read, %(created)d added, %(updated)d updated, %(skipped)d unchanged,"
            " %(possible_duplicates)d possible duplicates" % rec)
    for e in rec["errors"]:
        print("  %s, row %s: %s" % (e["sheet"], e["row"], e["message"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
