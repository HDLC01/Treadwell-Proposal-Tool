"""The workbook / CSV import (#809): bd/ops/import_workbook.py, POST /api/bd/admin/import, GET /api/bd/admin/imports.

BD's test_import_workbook, ported. Every workbook here is MADE UP, built with openpyxl in the test
(fictional people, 555-01xx phones, example.com emails) in the shape BD's product brief describes.
A real Treadwell workbook is never opened. BD compared a record with its contract example through
its mock helpers (retired in #806); the example is read from docs/bd/api-contract.md here.

The team (inserted into an empty BD database): Avery Quill (salesperson), Casey Moret (assistant),
Devon Hale (manager), Frankie Oduya (super admin), Emery Stoll (admin). The workbook's Owner column
names "Avery" and "Avery/Greg" (Greg has no login).

THE LIMITS (BD's, unchanged): a 10 MB upload (MAX_BYTES), refused while it streams once it passes
the limit plus the envelope's slack; and an .xlsx is a zip, so before openpyxl opens it the zip's
own directory must show at most 200 MB unpacked in all (MAX_UNPACKED), at most 20 MB in any one part
(MAX_PART_UNPACKED) and, for a part over 1 MB (RATIO_FLOOR), at most 100 times its packed size
(MAX_PART_RATIO). The streaming cap itself is in test_bd_review_fixes.py (SEC-1).
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import pathlib
import re
import zipfile

import openpyxl
import pytest

from bd import serialize
from bd.ops import import_workbook as iw

D = dt.date
TODAY = "2026-11-04"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CONTRACT = (pathlib.Path(__file__).resolve().parents[2] / "docs" / "bd" / "api-contract.md").read_text(encoding="utf-8")

BD_HEADER = ["Company Name", "Contact Name", "Title", "Phone", "Email", "City / Location", "Industry",
             "Lead Source", "Stage", "Last Activity Date", "Next Step", "Next Step Date", "Meeting Date",
             "Notes", "Owner"]
MAINT_HEADER = ["Account Name", "Primary Contact", "Title", "Phone", "Email", "Address / Location",
                "Account Type", "Notes", "Touch 1 Date", "Touch 2 Date", "Touch 3 Date", "(auto) Last Touch",
                "Next Touch Due", "Touches YTD", "Status", "Owner"]

# The made-up workbook: every quirk BD's brief lists, a bad row, a duplicate, a Maintenance sheet.
BD_ROWS = [
    {   # row 6: NBSP + leading spaces + "Inc."; dotted phone; past meeting + later last activity
        "Company Name": "\u00a0 Kestrel Ridge Plastics Inc.", "Contact Name": "Dana Whitfield",
        "Title": "Plant Manager", "Phone": "816.555.0141", "Email": "Dana.Whitfield@KestrelRidge.example.com",
        "City / Location": "Lenexa, KS", "Industry": "manufacturing", "Lead Source": "DSBC Sales",
        "Stage": "Met", "Last Activity Date": D(2026, 10, 20), "Next Step": "Send the epoxy quote",
        "Next Step Date": D(2026, 11, 10), "Meeting Date": D(2026, 10, 14), "Notes": "Two floors.",
        "Owner": "Avery"},
    {   # row 7: same company, another person -> possible duplicate; Avery/Greg; a FUTURE meeting
        "Company Name": "Kestrel Ridge Plastics", "Contact Name": "Omar Feld", "Phone": "913-555-0142",
        "Email": "omar.feld@kestrelridge.example.com", "Lead Source": "Website Lead",
        "Stage": "Meeting Set", "Meeting Date": D(2026, 11, 20), "Owner": "Avery/Greg"},
    {   # row 8: numeric phone cell, mixed-case email, an unknown lead source, no owner
        "Company Name": "  Bluefen Cold Storage", "Contact Name": "Rita Okafor", "Phone": 8165550143,
        "Email": "Rita.Okafor@Bluefen.example.com", "Lead Source": "Trade show", "Owner": ""},
    {   # row 9: no company
        "Contact Name": "Nobody Atall", "Email": "nobody@example.com", "Owner": "Avery"},
    {   # row 10: a date that is not a date (row still imports)
        "Company Name": "Harrow Lane Foods", "Contact Name": "Ben Ruiz", "Next Step Date": "soon",
        "Owner": "Avery"},
    {   # row 11: no contact name
        "Company Name": "Orphan Fixtures", "Phone": "816-555-0149"},
    {},  # row 12: blank
]
MAINT_ROWS = [
    {   # row 6: two past touches and a future one; parenthesised phone
        "Account Name": "Larkspur Pharma LLC", "Primary Contact": "Ivy Chen", "Title": "EHS Lead",
        "Phone": "(913) 555-0151", "Email": "ivy.chen@larkspur.example.com",
        "Address / Location": "Olathe, KS", "Account Type": "pharma", "Notes": "Quarterly walk.",
        "Touch 1 Date": D(2026, 2, 3), "Touch 2 Date": D(2026, 6, 9), "Touch 3 Date": D(2026, 12, 1),
        "(auto) Last Touch": D(2026, 6, 9), "Next Touch Due": D(2026, 10, 7), "Touches YTD": 2,
        "Status": "Behind", "Owner": "Avery"},
    {   # row 7: only the sheet's own formulas filled in: a blank row
        "Touches YTD": 0, "Status": "On Track"},
]


def workbook_bytes(bd=BD_ROWS, maint=MAINT_ROWS, bd_header=BD_HEADER, maint_header=MAINT_HEADER,
                   header_row=5, bd_title=iw.BD_SHEET, maint_title=iw.MAINT_SHEET):
    wb = openpyxl.Workbook()
    sheets = []
    ws = wb.active
    if bd is not None:
        ws.title = bd_title
        sheets.append((ws, bd_header, bd))
        ws = wb.create_sheet()
    if maint is not None:
        ws.title = maint_title
        sheets.append((ws, maint_header, maint))
    elif bd is not None:
        wb.remove(ws)
    else:
        ws.title = "Notes"
    for ws, header, rows in sheets:
        # The top summary (rows 1-4), as in the real workbook.
        ws["A1"] = "BD tracker (made up)"
        ws["A2"], ws["B2"] = "Week", "Mon-Sun"
        ws["A3"], ws["B3"], ws["C3"], ws["D3"] = "Meetings This Week", 2, "Goal", 5
        ws["A4"], ws["B4"] = "Non-DSBC/Website Leads", 1
        for c, h in enumerate(header, start=1):
            ws.cell(row=header_row, column=c, value=h)
        for r, row in enumerate(rows, start=header_row + 1):
            for c, h in enumerate(header, start=1):
                if h in row:
                    ws.cell(row=r, column=c, value=row[h])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── fixtures ─────────────────────────────────────────────────────────────────────────────────
TEAM = [("avery.quill@example.com", "Avery Quill", "salesperson"), ("casey.moret@example.com", "Casey Moret", "assistant"),
        ("devon.hale@example.com", "Devon Hale", "manager"), ("frankie.oduya@example.com", "Frankie Oduya", "super_admin"),
        ("emery.stoll@example.com", "Emery Stoll", "admin")]


@pytest.fixture
def users(bd_db, bd_today):
    bd_today(TODAY)
    for email, name, role in TEAM:
        bd_db.execute("insert into bd.users (email, name, role) values (%s, %s, %s)", (email, name, role))
    return {r["name"].split()[0].lower(): r for r in bd_db.execute("select * from bd.users order by id").fetchall()}


@pytest.fixture
def casey(users, bd_as_user):
    return bd_as_user("casey.moret@example.com")


def upload(c, data, name="BD workbook.xlsx", dry_run="true", mime=XLSX):
    form = {} if dry_run is None else {"dry_run": dry_run}
    return c.post("/api/bd/admin/import", files={"file": (name, data, mime)}, data=form)


def ok_import(res):
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    return body["import"]


def counts(db):
    from psycopg import sql
    return {t: db.execute(sql.SQL("select count(*) as n from {}").format(sql.Identifier("bd", t))).fetchone()["n"]
            for t in ("companies", "contacts", "interactions", "events", "imports")}


def contact_by_name(db, name):
    row = db.execute("select id from bd.contacts where name = %s", (name,)).fetchone()
    assert row, name
    return serialize.fetch_contact(db, row["id"])


def jtype(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    return type(v).__name__


def assert_shape(expected, actual, where="import"):
    """Every key of the contract's example is present with the same JSON type (null matches)."""
    assert isinstance(actual, dict), where
    for k, v in expected.items():
        assert k in actual, "%s.%s missing" % (where, k)
        if v is None or actual[k] is None:
            continue
        assert jtype(v) == jtype(actual[k]), "%s.%s: %s vs %s" % (where, k, jtype(v), jtype(actual[k]))
        if isinstance(v, dict):
            assert_shape(v, actual[k], where + "." + k)
        if isinstance(v, list) and v and actual[k] and isinstance(v[0], dict):
            for item in actual[k]:
                assert_shape(v[0], item, where + "." + k + "[]")


def contract_import_example():
    """The Import example in docs/bd/api-contract.md: the first JSON block that holds an "import"."""
    for m in re.finditer(r"```json\n(.*?)\n```", CONTRACT, re.S):
        block = json.loads(m.group(1))
        if isinstance(block, dict) and block.get("ok") is True and "import" in block:
            return block
    raise AssertionError("no import example in the contract")


# ── pure parsing (no database) ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("value,want", [
    (None, None), ("", None), ("  ", None),
    (dt.datetime(2026, 3, 14, 0, 0), D(2026, 3, 14)), (D(2026, 3, 14), D(2026, 3, 14)),
    ("2026-03-14", D(2026, 3, 14)), ("3/14/2026", D(2026, 3, 14)), ("3/14/26", D(2026, 3, 14)),
    ("03-14-2026", D(2026, 3, 14)), ("Mar 14, 2026", D(2026, 3, 14)), ("2026-03-14 00:00:00", D(2026, 3, 14)),
    (46095, D(2026, 3, 14)),                      # an Excel serial left unformatted
])
def test_cell_date_reads_every_spelling_the_workbook_uses(value, want):
    assert iw.cell_date(value) == want


@pytest.mark.parametrize("value", ["soon", "TBD", "13/45/2026", 12, "1850-01-01", True])
def test_cell_date_refuses_what_is_not_a_date(value):
    with pytest.raises(ValueError):
        iw.cell_date(value)


def test_cell_text_trims_odd_spaces_and_numbers():
    assert iw.cell_text("\u00a0 Kestrel\u00a0\u00a0Ridge  ") == "Kestrel Ridge"
    assert iw.cell_text(8165550143.0) == "8165550143"
    assert iw.cell_text(8165550143) == "8165550143"
    assert iw.cell_text(None) == ""
    assert iw.cell_notes(" Line one \r\n  line two\u00a0 ") == "Line one\nline two"


@pytest.mark.parametrize("value,want", [
    (" Dana@Example.COM ", "dana@example.com"), ("mailto:x@example.com", "x@example.com"),
    ("n/a", None), ("not an email", None), ("", None), (None, None), ("a@b", None),
])
def test_clean_email(value, want):
    assert iw.clean_email(value) == want


@pytest.mark.parametrize("name,want", [
    ("BD workbook.xlsx", "BD workbook.xlsx"), ("C:\\fake\\folder\\BD workbook.xlsx", "BD workbook.xlsx"),
    ("../../etc/x.csv", "x.csv"), ("bad\x00name.csv", "badname.csv"), ("a" * 300 + ".csv", "a" * 200),
])
def test_safe_file_name(name, want):
    assert iw.safe_file_name(name) == want


def test_read_xlsx_finds_both_sheets_and_every_quirk():
    parsed = iw.read_xlsx(workbook_bytes(), today=D(2026, 11, 4))
    assert parsed.rows_read == 7                  # 6 BD rows + 1 Maintenance row; blanks are not rows
    assert parsed.errors == []
    by = {(r.sheet, r.row): r for r in parsed.rows}
    dana = by[(iw.BD_SHEET, 6)]
    assert dana.company == "Kestrel Ridge Plastics Inc." and dana.name == "Dana Whitfield"
    assert dana.email == "dana.whitfield@kestrelridge.example.com"
    assert dana.phone == "816.555.0141" and dana.category == "bd"
    assert dana.meeting_date == D(2026, 10, 14) and dana.last_activity == D(2026, 10, 20)
    assert dana.next_step_date == D(2026, 11, 10)
    omar = by[(iw.BD_SHEET, 7)]
    assert omar.meeting_date is None              # 2026-11-20 has not happened
    assert omar.next_step == "Meeting" and omar.next_step_date == D(2026, 11, 20)
    assert omar.owner == "Avery/Greg"
    assert by[(iw.BD_SHEET, 8)].phone == "8165550143"
    assert by[(iw.BD_SHEET, 10)].problems == ["Next Step Date is not a date; left blank."]
    ivy = by[(iw.MAINT_SHEET, 6)]
    assert ivy.category == "maintenance" and ivy.city == "Olathe, KS" and ivy.account_type == "pharma"
    assert ivy.touches == [(1, D(2026, 2, 3)), (2, D(2026, 6, 9))]
    assert ivy.problems == ["Touch 3 Date is after today, so it was left out."]
    assert (iw.MAINT_SHEET, 7) not in by          # formula-only row


def test_header_row_is_found_when_it_moved_and_columns_are_found_by_name():
    shuffled = list(reversed(BD_HEADER))
    parsed = iw.read_xlsx(workbook_bytes(bd_header=shuffled, maint=None, header_row=3), today=D(2026, 11, 4))
    names = sorted(r.name for r in parsed.rows if r.name)
    assert names == ["Ben Ruiz", "Dana Whitfield", "Nobody Atall", "Omar Feld", "Rita Okafor"]


def test_sheet_names_match_ignoring_case_and_spaces():
    parsed = iw.read_xlsx(workbook_bytes(bd_title=" business development accounts", maint=None),
                          today=D(2026, 11, 4))
    assert parsed.rows_read == 6


def test_a_sheet_without_headers_is_reported():
    parsed = iw.read_xlsx(workbook_bytes(bd_header=["Foo", "Bar"], maint=None), today=D(2026, 11, 4))
    assert parsed.rows == []
    assert parsed.errors == [{"sheet": iw.BD_SHEET, "row": 5,
                              "message": "Row 5 should name the columns (the company and the contact)."}]


def test_a_workbook_with_neither_sheet_is_reported():
    parsed = iw.read_xlsx(workbook_bytes(bd=None, maint=None), today=D(2026, 11, 4))
    assert parsed.rows_read == 0
    assert parsed.errors == [{"sheet": "Workbook", "row": 1, "message":
                              'This workbook has no "Business Development Accounts" or "Maintenance Accounts" sheet.'}]


@pytest.mark.parametrize("name,data", [
    ("BD.pdf", b"%PDF-1.4"), ("BD", b"x"), ("BD.xls", b"\xd0\xcf\x11\xe0"),
    ("BD.xlsx", b""), ("BD.xlsx", b"this is text, not a zip"),
])
def test_check_file_refuses_what_it_cannot_read(name, data):
    with pytest.raises(iw.ImportFileError) as exc:
        iw.parse_file(name, data)
    assert exc.value.status == 400


def test_read_csv_uses_bds_columns():
    text = ("\ufeffCompany Name,Full Name,E-mail,Mobile,Job Title,Location,Category\r\n"
            "\u00a0Acme Floors Inc.,Pat Lee,Pat@Acme.example.com,816-555-0161,Owner,Kansas City,\r\n"
            ",,,,,,\r\n"
            "Acme Floors,Sam Roe,,816.555.0162,,,Maintenance\r\n"
            ",Nobody,,,,,\r\n")
    parsed = iw.read_csv(text.encode("utf-8"))
    assert parsed.rows_read == 3 and parsed.errors == [] and parsed.source == "import"
    pat, sam, nobody = parsed.rows
    assert (pat.company, pat.name, pat.email, pat.phone, pat.title, pat.city, pat.category) == \
        ("Acme Floors Inc.", "Pat Lee", "pat@acme.example.com", "816-555-0161", "Owner", "Kansas City", "bd")
    assert sam.category == "maintenance" and sam.email is None and sam.row == 4
    assert nobody.company == "" and nobody.row == 5


def test_read_csv_without_company_and_name_columns():
    parsed = iw.read_csv(b"Email,Phone\nx@example.com,816-555-0100\n")
    assert parsed.errors == [{"sheet": "CSV", "row": 1, "message": "The first row needs Company and Name columns."}]
    assert iw.read_csv(b"").errors == [{"sheet": "CSV", "row": 1, "message": "The file is empty."}]
    assert iw.read_csv("Company,Name\nCaf\xe9 Uno,Ana\n".encode("cp1252")).rows[0].company == "Caf\xe9 Uno"


# ── the API: roles (the full role table is test_bd_admin_roles.py) ───────────────────────────
@pytest.mark.parametrize("who,allowed", [("avery", True), ("devon", False), ("casey", True),
                                         ("frankie", True), ("emery", True)])
def test_roles(users, bd_as_user, who, allowed):
    c = bd_as_user(users[who]["id"])
    for res in (upload(c, workbook_bytes()), c.get("/api/bd/admin/imports")):
        if allowed:
            assert res.status_code == 200, res.text
        else:
            assert res.status_code == 403
            assert res.json() == {"ok": False, "error": "forbidden", "message": "Your role can't do that."}


def test_no_sign_in_is_401(users, bd_client):
    res = bd_client.post("/api/bd/admin/import", files={"file": ("BD.xlsx", workbook_bytes(), XLSX)})
    assert res.status_code == 401
    assert bd_client.get("/api/bd/admin/imports").status_code == 401


def test_a_refused_role_writes_nothing(users, bd_as_user, bd_db):
    upload(bd_as_user(users["devon"]["id"]), workbook_bytes(), dry_run="false")
    assert counts(bd_db) == {"companies": 0, "contacts": 0, "interactions": 0, "events": 0, "imports": 0}


# ── a salesperson's upload: every contact it adds is theirs (Hanz, 2026-11-16) ──────────────
@pytest.fixture
def pat(users, bd_db, bd_as_user):
    """A second salesperson, so "the uploader" and "the first salesperson" (Avery) differ."""
    bd_db.execute("insert into bd.users (email, name, role) values ('pat.lowe@example.com', 'Pat Lowe', 'salesperson')")
    return bd_as_user("pat.lowe@example.com")


def test_a_salesperson_can_preview_and_import(pat, bd_db):
    preview = ok_import(upload(pat, workbook_bytes()))
    assert preview["dry_run"] is True and counts(bd_db)["contacts"] == 0
    rec = ok_import(upload(pat, workbook_bytes(), dry_run="false"))
    assert rec["dry_run"] is False and rec["created"] == preview["created"] == 5
    assert rec["by"]["name"] == "Pat Lowe"


def test_a_salespersons_upload_gives_every_new_contact_to_them(pat, bd_db):
    ok_import(upload(pat, workbook_bytes(), dry_run="false"))
    rows = bd_db.execute("select name, owner_id, co_owner_id, co_owner_name from bd.contacts order by id").fetchall()
    assert len(rows) == 5
    # Rows that say "Avery", "Avery/Greg" or nothing: all Pat's, and nobody is made a co-owner.
    assert {r["owner_id"] for r in rows} == {pat.user["id"]}
    assert all(r["co_owner_id"] is None and r["co_owner_name"] is None for r in rows)


def test_a_salespersons_upload_never_takes_a_contact_from_its_owner(casey, pat, bd_db):
    ok_import(upload(casey, workbook_bytes(maint=None), dry_run="false"))      # Dana is Avery's
    bd_db.execute("update bd.contacts set owner_id = null where name = 'Rita Okafor'")
    bd = [dict(BD_ROWS[0], Title="Plant Director"), BD_ROWS[2]]
    ok_import(upload(pat, workbook_bytes(bd=bd, maint=None), dry_run="false"))
    dana = contact_by_name(bd_db, "Dana Whitfield")
    assert dana["title"] == "Plant Director" and dana["owner"]["name"] == "Avery Quill"   # updated, still Avery's
    assert contact_by_name(bd_db, "Rita Okafor")["owner"]["id"] == pat.user["id"]       # an empty owner is filled


def test_a_salespersons_file_logs_its_meetings_as_theirs_not_the_owners(casey, pat, bd_db):
    ok_import(upload(casey, workbook_bytes(bd=[dict(BD_ROWS[0], **{"Meeting Date": None})], maint=None),
                     dry_run="false"))
    ok_import(upload(pat, workbook_bytes(bd=[BD_ROWS[0]], maint=None), dry_run="false"))
    dana = contact_by_name(bd_db, "Dana Whitfield")
    assert dana["owner"]["name"] == "Avery Quill"
    meetings = bd_db.execute("select user_id from bd.interactions where contact_id = %s and kind = 'meeting'",
                             (dana["id"],)).fetchall()
    assert [m["user_id"] for m in meetings] == [pat.user["id"]]


def test_an_assistants_upload_still_follows_the_owner_column(casey, pat, bd_db):
    ok_import(upload(casey, workbook_bytes(maint=None), dry_run="false"))
    assert contact_by_name(bd_db, "Dana Whitfield")["owner"]["name"] == "Avery Quill"
    assert contact_by_name(bd_db, "Rita Okafor")["owner"]["name"] == "Avery Quill"   # empty -> first salesperson


# ── the API: the dry run and the real run ────────────────────────────────────────────────────
EXPECTED_ERRORS = [
    {"sheet": iw.BD_SHEET, "row": 9, "message": "No company name."},
    {"sheet": iw.BD_SHEET, "row": 10, "message": "Next Step Date is not a date; left blank."},
    {"sheet": iw.BD_SHEET, "row": 11, "message": "No contact name."},
    {"sheet": iw.MAINT_SHEET, "row": 6, "message": "Touch 3 Date is after today, so it was left out."},
]


def test_a_dry_run_previews_and_writes_nothing(casey, bd_db, users):
    rec = ok_import(upload(casey, workbook_bytes()))
    assert rec["dry_run"] is True and rec["file_name"] == "BD workbook.xlsx"
    assert rec["by"] == {"id": users["casey"]["id"], "name": "Casey Moret"}
    assert (rec["rows_read"], rec["created"], rec["updated"], rec["skipped"], rec["possible_duplicates"]) == \
        (7, 5, 0, 0, 1)
    assert rec["errors"] == EXPECTED_ERRORS
    assert counts(bd_db) == {"companies": 0, "contacts": 0, "interactions": 0, "events": 0, "imports": 1}
    assert rec["started_at"].startswith(TODAY + "T") and rec["started_at"].endswith("-06:00")


def test_the_real_run_does_exactly_what_the_preview_said(casey, bd_db):
    preview = ok_import(upload(casey, workbook_bytes()))
    rec = ok_import(upload(casey, workbook_bytes(), dry_run="false"))
    assert rec["dry_run"] is False
    for k in ("rows_read", "created", "updated", "skipped", "possible_duplicates", "errors"):
        assert rec[k] == preview[k], k
    n = counts(bd_db)
    assert (n["companies"], n["contacts"], n["interactions"], n["imports"]) == (4, 5, 4, 2)
    assert rec["id"] == preview["id"] + 1


def test_the_answer_has_the_contracts_shape(casey):
    rec = ok_import(upload(casey, workbook_bytes()))
    assert_shape(contract_import_example(), {"ok": True, "import": rec})
    assert set(rec) == {"id", "file_name", "dry_run", "started_at", "by", "rows_read", "created", "updated",
                        "skipped", "possible_duplicates", "errors"}


@pytest.mark.parametrize("raw,dry", [("true", True), ("false", False), ("FALSE", False), ("0", False),
                                     ("no", False), ("off", False), (None, True), ("yes", True), ("", True)])
def test_the_dry_run_flag_defaults_to_a_practice_run(casey, bd_db, raw, dry):
    rec = ok_import(upload(casey, workbook_bytes(), dry_run=raw))
    assert rec["dry_run"] is dry
    assert counts(bd_db)["contacts"] == (0 if dry else 5)


@pytest.mark.parametrize("cadence,expected", [("weekly", 52), ("monthly", 12), ("quarterly", 4), (None, 4)])
def test_an_imported_bd_contact_gets_the_bd_cadence_number(casey, bd_db, cadence, expected):
    """A BD row is stored with the number of the BD cadence setting, as POST /api/bd/contacts does; a
    maintenance row keeps the maintenance default whatever the BD cadence is."""
    if cadence is not None:
        bd_db.execute("insert into bd.settings (key, value) values ('bd_cadence', to_jsonb(%s::text))"
                      " on conflict (key) do update set value = excluded.value", (cadence,))
    ok_import(upload(casey, workbook_bytes(), dry_run="false"))
    rows = bd_db.execute("select category, frequency_per_year from bd.contacts").fetchall()
    assert {r["frequency_per_year"] for r in rows if r["category"] == "bd"} == {expected}
    assert {r["frequency_per_year"] for r in rows if r["category"] == "maintenance"} == {3}
    assert {r["category"] for r in rows} == {"bd", "maintenance"}, "both sheets were imported"


def test_the_workbook_quirks_land_as_the_contract_says(casey, bd_db, users):
    ok_import(upload(casey, workbook_bytes(), dry_run="false"))
    avery = {"id": users["avery"]["id"], "name": "Avery Quill"}

    dana = contact_by_name(bd_db, "Dana Whitfield")
    assert dana["company"]["name"] == "Kestrel Ridge Plastics Inc."          # NBSP and spaces trimmed
    assert dana["phone"] == "816.555.0141" and dana["phone_e164"] == "+18165550141"
    assert dana["email"] == "dana.whitfield@kestrelridge.example.com"
    assert (dana["industry"], dana["lead_source"], dana["stage"]) == ("Manufacturing", "DSBC Sales", "Met")
    assert dana["owner"] == avery and dana["co_owner"] is None
    assert (dana["category"], dana["frequency_per_year"], dana["source"]) == ("bd", 4, "workbook")
    assert dana["next_step"] == "Send the epoxy quote" and dana["next_step_date"] == "2026-11-10"
    assert dana["notes"] == "Two floors." and dana["confirmed"] is False and dana["duplicate_of"] is None
    assert dana["last_live_at"] == "2026-10-14T12:00:00-05:00"                 # the meeting, noon CDT
    assert dana["touches_this_year"] == 1 and dana["cadence_status"] == "on_track"
    assert dana["next_due_date"] == "2027-01-13"

    omar = contact_by_name(bd_db, "Omar Feld")
    assert omar["company"]["id"] == dana["company"]["id"]                    # one company, "Inc." or not
    assert omar["co_owner"] == {"id": None, "name": "Greg"}                   # Greg has no login
    assert omar["owner"] == avery
    assert omar["duplicate_of"] == {"contact_id": dana["id"], "name": "Dana Whitfield",
                                    "company": "Kestrel Ridge Plastics Inc.", "reason": "Same company name"}
    assert omar["next_step"] == "Meeting" and omar["next_step_date"] == "2026-11-20"
    assert omar["cadence_status"] == "never" and omar["stage"] == "Meeting Set"

    rita = contact_by_name(bd_db, "Rita Okafor")
    assert rita["phone"] == "8165550143" and rita["phone_e164"] == "+18165550143"
    assert rita["email"] == "rita.okafor@bluefen.example.com"
    assert rita["lead_source"] == "Other/Misc"                               # an unknown source
    assert rita["owner"] == avery                                            # empty owner -> first salesperson
    assert rita["company"]["name"] == "Bluefen Cold Storage"

    assert contact_by_name(bd_db, "Ben Ruiz")["next_step_date"] is None

    ivy = contact_by_name(bd_db, "Ivy Chen")
    assert (ivy["category"], ivy["frequency_per_year"], ivy["account_type"]) == ("maintenance", 3, "Pharma")
    assert ivy["city"] == "Olathe, KS" and ivy["lead_source"] == "Current Account"
    assert ivy["phone_e164"] == "+19135550151"
    assert ivy["touches_this_year"] == 2
    assert ivy["next_due_date"] == "2026-10-07" and ivy["cadence_status"] == "behind"   # + 120 days
    assert ivy["company"]["name"] == "Larkspur Pharma LLC"


def test_touch_and_meeting_dates_become_meeting_interactions(casey, bd_db, users):
    ok_import(upload(casey, workbook_bytes(), dry_run="false"))
    rows = bd_db.execute(
        "select c.name, i.kind, i.outcome, i.direction, i.counts_as_touch, bd_date(i.occurred_at) as d,"
        " i.provider, i.external_id, i.user_id, i.summary from bd.interactions i join bd.contacts c on c.id = i.contact_id"
        " order by c.name, i.occurred_at").fetchall()
    got = [(r["name"], r["kind"], r["counts_as_touch"], r["d"].isoformat(), r["summary"]) for r in rows]
    assert got == [
        ("Dana Whitfield", "meeting", True, "2026-10-14", "Meeting (from the workbook)."),
        ("Dana Whitfield", "note", False, "2026-10-20", "Last activity in the workbook."),
        ("Ivy Chen", "meeting", True, "2026-02-03", "Touch 1 (from the workbook)."),
        ("Ivy Chen", "meeting", True, "2026-06-09", "Touch 2 (from the workbook)."),
    ]
    for r in rows:
        assert r["provider"] == "workbook" and r["outcome"] is None and r["direction"] is None
        assert r["external_id"].startswith("workbook:") and r["user_id"] == users["avery"]["id"]


def test_created_events_feed_the_timeline_and_the_run_is_audited(casey, bd_db, users):
    ok_import(upload(casey, workbook_bytes()))
    assert counts(bd_db)["events"] == 0                                       # dry run: none
    ok_import(upload(casey, workbook_bytes(), dry_run="false"))
    created = bd_db.execute("select * from bd.events where kind = 'created' order by id").fetchall()
    assert len(created) == 5
    assert {e["detail"] for e in created} == {"Imported from the workbook"}
    assert {e["actor_id"] for e in created} == {users["casey"]["id"]}
    run = bd_db.execute("select * from bd.events where kind = 'import_run'").fetchall()
    assert len(run) == 1 and run[0]["contact_id"] is None and run[0]["data"]["created"] == 5


# ── idempotency and duplicates ───────────────────────────────────────────────────────────────
def test_a_second_import_updates_instead_of_duplicating(casey, bd_db):
    ok_import(upload(casey, workbook_bytes(), dry_run="false"))
    before = counts(bd_db)
    again = ok_import(upload(casey, workbook_bytes(), dry_run="false"))
    assert (again["created"], again["updated"], again["skipped"], again["possible_duplicates"]) == (0, 0, 5, 0)
    after = counts(bd_db)
    for t in ("companies", "contacts", "interactions"):
        assert after[t] == before[t], t


def test_a_changed_row_is_updated_and_a_new_touch_added(casey, bd_db):
    ok_import(upload(casey, workbook_bytes(), dry_run="false"))
    bd = [dict(r) for r in BD_ROWS]
    bd[0]["Phone"] = "816-555-0199"
    bd[0]["Title"] = "Operations Director"
    bd[0]["Lead Source"] = "Nonsense source"            # unknown: an update leaves it alone
    bd[0]["Company Name"] = "KESTREL RIDGE PLASTICS, LLC"   # the same company, spelled differently
    bd[0]["Email"] = "DANA.WHITFIELD@kestrelridge.example.com"
    bd[1]["Phone"] = "(913) 555-0142"                    # the same number: not a change
    maint = [dict(MAINT_ROWS[0], **{"Touch 3 Date": D(2026, 10, 30)})]
    rec = ok_import(upload(casey, workbook_bytes(bd=bd, maint=maint), dry_run="false"))
    assert (rec["created"], rec["updated"], rec["skipped"]) == (0, 2, 3)
    dana = contact_by_name(bd_db, "Dana Whitfield")
    assert dana["phone"] == "816-555-0199" and dana["title"] == "Operations Director"
    assert dana["lead_source"] == "DSBC Sales" and dana["company"]["name"] == "Kestrel Ridge Plastics Inc."
    assert contact_by_name(bd_db, "Omar Feld")["phone"] == "913-555-0142"
    ivy = contact_by_name(bd_db, "Ivy Chen")
    assert ivy["touches_this_year"] == 3 and ivy["cadence_status"] == "complete"
    assert counts(bd_db)["contacts"] == 5


def test_an_update_never_overwrites_app_notes_or_owner(casey, bd_db, users):
    ok_import(upload(casey, workbook_bytes(), dry_run="false"))
    bd_db.execute("update bd.contacts set notes = 'Typed in the app.', owner_id = %s where name = 'Dana Whitfield'",
                  (users["devon"]["id"],))
    bd_db.execute("update bd.contacts set notes = '' where name = 'Ivy Chen'")
    bd = [dict(BD_ROWS[0], Notes="Workbook notes changed.")]
    maint = [dict(MAINT_ROWS[0], Notes="Workbook maintenance notes.")]
    rec = ok_import(upload(casey, workbook_bytes(bd=bd, maint=maint), dry_run="false"))
    assert (rec["updated"], rec["skipped"]) == (1, 1)
    dana = contact_by_name(bd_db, "Dana Whitfield")
    assert dana["notes"] == "Typed in the app." and dana["owner"]["name"] == "Devon Hale"
    assert contact_by_name(bd_db, "Ivy Chen")["notes"] == "Workbook maintenance notes."


def test_a_co_owner_with_a_login_is_linked(casey, bd_db):
    greg = bd_db.execute("insert into bd.users (email, name, role) values ('greg.vance@example.com', 'Greg Vance',"
                         " 'salesperson') returning id").fetchone()["id"]
    ok_import(upload(casey, workbook_bytes(maint=None), dry_run="false"))
    omar = contact_by_name(bd_db, "Omar Feld")
    assert omar["co_owner"] == {"id": greg, "name": "Greg Vance"}            # matched on the first name
    assert omar["owner"]["name"] == "Avery Quill"


def test_the_same_person_twice_in_one_file_is_one_contact(casey, bd_db):
    bd = [BD_ROWS[0], dict(BD_ROWS[0], Title="Plant Director")]
    rec = ok_import(upload(casey, workbook_bytes(bd=bd, maint=None), dry_run="false"))
    assert (rec["created"], rec["updated"], rec["possible_duplicates"]) == (1, 1, 0)
    assert contact_by_name(bd_db, "Dana Whitfield")["title"] == "Plant Director"


def test_people_without_email_match_on_name_within_the_company(casey, bd_db):
    bd = [{"Company Name": "Harrow Lane Foods", "Contact Name": "Ben Ruiz", "Owner": "Avery"},
          {"Company Name": "Harrow Lane Foods", "Contact Name": "Cara Ruiz", "Owner": "Avery"}]
    first = ok_import(upload(casey, workbook_bytes(bd=bd, maint=None), dry_run="false"))
    assert (first["created"], first["possible_duplicates"]) == (2, 1)
    again = ok_import(upload(casey, workbook_bytes(bd=bd, maint=None), dry_run="false"))
    assert (again["created"], again["skipped"]) == (0, 2)


def test_an_archived_contact_is_not_brought_back(casey, bd_db):
    ok_import(upload(casey, workbook_bytes(maint=None), dry_run="false"))
    bd_db.execute("update bd.contacts set archived_at = bd_now() where name = 'Rita Okafor'")
    rec = ok_import(upload(casey, workbook_bytes(maint=None), dry_run="false"))
    assert rec["created"] == 0
    assert bd_db.execute("select count(*) as n from bd.contacts where name = 'Rita Okafor'").fetchone()["n"] == 1


def test_the_same_email_or_phone_elsewhere_is_flagged(casey, bd_db):
    bd = [{"Company Name": "Ashgrove Mills", "Contact Name": "Lena Park", "Email": "lena@ashgrove.example.com",
           "Phone": "816-555-0170"},
          {"Company Name": "Ashgrove Holdings West", "Contact Name": "Lena Park", "Email": "lena@ashgrove.example.com"},
          {"Company Name": "Brightwater Dairy", "Contact Name": "Moe Tran", "Phone": "816.555.0170"}]
    rec = ok_import(upload(casey, workbook_bytes(bd=bd, maint=None), dry_run="false"))
    assert (rec["created"], rec["possible_duplicates"]) == (3, 2)
    lena = bd_db.execute("select id from bd.contacts where name = 'Lena Park' order by id").fetchall()
    moe = contact_by_name(bd_db, "Moe Tran")
    assert moe["duplicate_of"]["reason"] == "Same phone" and moe["duplicate_of"]["contact_id"] == lena[0]["id"]
    assert serialize.fetch_contact(bd_db, lena[1]["id"])["duplicate_of"]["reason"] == "Same email"


def test_a_csv_finds_a_seeded_contact_across_spellings(bd_seeded, bd_as_user, bd_db):
    """Priya Nandan (25) at Cedar Creek Concrete, spelled in capitals with "LLC" and a leading NBSP."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Company", "Name", "Email", "Phone", "Title"])
    w.writerow(["\u00a0CEDAR CREEK CONCRETE LLC", "Priya Nandan", "PRIYA@CEDARCREEK.EXAMPLE.COM", "785-555-0105",
                "A brand new title"])
    before = counts(bd_db)
    rec = ok_import(upload(bd_as_user(3), buf.getvalue().encode("utf-8"), name="people.csv", dry_run="false",
                           mime="text/csv"))
    assert (rec["created"], rec["updated"], rec["skipped"]) == (0, 1, 0)
    assert counts(bd_db)["contacts"] == before["contacts"]
    assert serialize.fetch_contact(bd_db, 25)["title"] == "A brand new title"


# ── Central time ─────────────────────────────────────────────────────────────────────────────
def test_today_is_central_for_touch_dates(casey, bd_db, bd_today):
    bd_today("2026-11-05")
    maint = [dict(MAINT_ROWS[0], **{"Touch 3 Date": D(2026, 11, 5)})]       # today: kept
    rec = ok_import(upload(casey, workbook_bytes(bd=None, maint=maint), dry_run="false"))
    assert rec["errors"] == []
    assert contact_by_name(bd_db, "Ivy Chen")["touches_this_year"] == 3
    bd_today("2026-11-04")
    maint = [dict(MAINT_ROWS[0], **{"Account Name": "Other Pharma", "Touch 3 Date": D(2026, 11, 5)})]
    rec = ok_import(upload(casey, workbook_bytes(bd=None, maint=maint), dry_run="false"))
    assert rec["errors"] == [{"sheet": iw.MAINT_SHEET, "row": 6,
                              "message": "Touch 3 Date is after today, so it was left out."}]


def test_a_touch_last_year_is_live_but_not_this_years(casey, bd_db, bd_today):
    bd_today("2027-01-02")
    maint = [{"Account Name": "Larkspur Pharma", "Primary Contact": "Ivy Chen", "Touch 1 Date": D(2026, 12, 31),
              "Owner": "Avery"}]
    ok_import(upload(casey, workbook_bytes(bd=None, maint=maint), dry_run="false"))
    ivy = contact_by_name(bd_db, "Ivy Chen")
    assert ivy["last_live_at"] == "2026-12-31T12:00:00-06:00"
    assert ivy["touches_this_year"] == 0 and ivy["next_due_date"] == "2027-04-30"


def test_a_meeting_already_logged_that_day_is_not_doubled(casey, bd_db):
    ok_import(upload(casey, workbook_bytes(bd=[BD_ROWS[0]], maint=None), dry_run="false"))
    cid = contact_by_name(bd_db, "Dana Whitfield")["id"]
    bd_db.execute("delete from bd.interactions where contact_id = %s", (cid,))
    # A meeting typed in the app late that evening (Central), in UTC the next day.
    bd_db.execute("insert into bd.interactions (contact_id, kind, occurred_at, provider) values"
                  " (%s, 'meeting', '2026-10-15T03:30:00Z', 'manual')", (cid,))
    rec = ok_import(upload(casey, workbook_bytes(bd=[BD_ROWS[0]], maint=None), dry_run="false"))
    kinds = [r["kind"] for r in bd_db.execute("select kind from bd.interactions where contact_id = %s"
                                              " order by occurred_at", (cid,)).fetchall()]
    assert kinds == ["meeting", "note"]                  # the note was new; the meeting was not doubled
    assert rec["updated"] == 1


# ── CSV, as BD reads it ──────────────────────────────────────────────────────────────────────
CSV = ("Company,Name,Email,Phone,Title,City,Industry,Lead Source,Category\n"
       "\u00a0Acme Floors Inc.,Pat Lee,pat@acme.example.com,816-555-0161,Owner,Kansas City,Retail,Website Lead,\n"
       "Acme Floors,Sam Roe,,816.555.0162,,,,,maintenance\n"
       ",Nobody,,,,,,,\n"
       "Zenith Labs,,z@zenith.example.com,,,,,,\n")


def test_a_csv_import(casey, bd_db):
    preview = ok_import(upload(casey, CSV.encode("utf-8"), name="people.csv", mime="text/csv"))
    assert (preview["rows_read"], preview["created"], preview["possible_duplicates"]) == (4, 2, 1)
    assert preview["errors"] == [{"sheet": "CSV", "row": 4, "message": "No company name."},
                                 {"sheet": "CSV", "row": 5, "message": "No contact name."}]
    assert counts(bd_db)["contacts"] == 0
    ok_import(upload(casey, CSV.encode("utf-8"), name="people.csv", dry_run="false", mime="text/csv"))
    pat = contact_by_name(bd_db, "Pat Lee")
    assert (pat["source"], pat["lead_source"], pat["industry"], pat["category"]) == \
        ("import", "Website Lead", "Retail", "bd")
    sam = contact_by_name(bd_db, "Sam Roe")
    assert (sam["category"], sam["frequency_per_year"], sam["lead_source"]) == ("maintenance", 3, "Other/Misc")
    assert sam["duplicate_of"]["reason"] == "Same company name"
    assert bd_db.execute("select detail from bd.events where kind = 'created' limit 1").fetchone()["detail"] == \
        "Imported from a file"
    changed = CSV.replace("816-555-0161", "816-555-0168")
    rec = ok_import(upload(casey, changed.encode("utf-8"), name="people.csv", dry_run="false", mime="text/csv"))
    assert (rec["created"], rec["updated"], rec["skipped"]) == (0, 1, 1)


def test_an_empty_csv_is_a_record_with_an_error(casey):
    rec = ok_import(upload(casey, b"", name="empty.csv", mime="text/csv"))
    assert rec["rows_read"] == 0 and rec["errors"] == [{"sheet": "CSV", "row": 1, "message": "The file is empty."}]


# ── bad uploads ──────────────────────────────────────────────────────────────────────────────
def test_a_file_that_is_not_xlsx_or_csv_is_refused_politely(casey, bd_db):
    res = upload(casey, b"%PDF-1.4 made up", name="BD workbook.pdf", mime="application/pdf")
    assert res.status_code == 400
    assert res.json() == {"ok": False, "error": "bad_request", "message": "Pick an .xlsx or .csv file.",
                          "fields": {"file": "Use the workbook or a CSV."}}
    assert counts(bd_db)["imports"] == 0


@pytest.mark.parametrize("data", [b"plain text pretending", b"", b"PK\x03\x04broken"])
def test_an_unreadable_workbook_is_400(casey, bd_db, data):
    res = upload(casey, data)
    assert res.status_code == 400, res.text
    body = res.json()
    assert body["error"] == "bad_request" and "file" in body["fields"]
    assert counts(bd_db)["imports"] == 0


def test_no_file_is_400(casey):
    res = casey.post("/api/bd/admin/import", data={"dry_run": "true"})
    assert res.status_code == 400
    assert res.json()["message"] == "Pick a file to import." and "file" in res.json()["fields"]
    res = casey.post("/api/bd/admin/import", json={"file_name": "BD workbook.xlsx", "dry_run": True})
    assert res.status_code == 400 and res.json()["fields"]["file"]


def test_a_real_run_that_fails_keeps_nothing(casey, bd_db, monkeypatch):
    orig = iw._Importer.create

    def boom(self, r, norm):
        if r.name == "Rita Okafor":
            raise RuntimeError("made-up failure")
        return orig(self, r, norm)

    monkeypatch.setattr(iw._Importer, "create", boom)
    res = upload(casey, workbook_bytes(), dry_run="false")
    assert res.status_code == 500 and res.json()["error"] == "error"
    assert "made-up failure" not in res.text
    assert counts(bd_db) == {"companies": 0, "contacts": 0, "interactions": 0, "events": 0, "imports": 0}


# ── the 10 MB cap ────────────────────────────────────────────────────────────────────────────
TOO_BIG = {"ok": False, "error": "bad_request", "message": "That file is too big. The limit is 10 MB.",
           "fields": {"file": "Pick a smaller file."}}


def _csv_of(size):
    """A CSV of exactly `size` bytes: one made-up person, then lines of spaces (blank rows)."""
    head = b"Company,Name\nTallgrass Dental,Rae Lindgren\n"
    line = b" " * 99_999 + b"\n"
    body = head + line * ((size - len(head)) // len(line))
    return body + b" " * (size - len(body))


def test_the_cap_is_10_mb():
    assert iw.MAX_BYTES == 10 * 1024 * 1024


def test_a_file_of_exactly_10_mb_is_accepted(casey, bd_db):
    data = _csv_of(iw.MAX_BYTES)
    assert len(data) == 10 * 1024 * 1024
    rec = ok_import(upload(casey, data, name="big.csv", mime="text/csv"))
    assert (rec["rows_read"], rec["created"], rec["dry_run"]) == (1, 1, True)


def test_a_file_one_byte_over_10_mb_is_refused_with_bds_envelope(casey, bd_db, monkeypatch):
    parsed = []
    monkeypatch.setattr(iw, "parse_file", lambda *a, **k: parsed.append(a) or pytest.fail("parsed"))
    res = upload(casey, _csv_of(iw.MAX_BYTES + 1), name="big.csv", mime="text/csv")
    assert (res.status_code, res.json()) == (413, TOO_BIG)
    assert parsed == []                                   # refused as it was read, never parsed
    assert res.headers["cache-control"] == "no-store"
    assert counts(bd_db)["imports"] == 0


def test_a_body_over_the_limit_is_refused_from_its_length_alone(casey, monkeypatch, bd_db):
    from bd.routers import imports as router_mod

    monkeypatch.setattr(iw, "MAX_BYTES", 2000)
    res = upload(casey, workbook_bytes())
    assert res.status_code == 413
    assert res.json()["error"] == "bad_request" and res.json()["message"].startswith("That file is too big.")
    monkeypatch.setattr(router_mod, "_ENVELOPE_SLACK", 0)
    res = upload(casey, b"x" * 5000, name="big.csv", mime="text/csv")
    assert res.status_code == 413
    assert counts(bd_db)["imports"] == 0


# ── the zip-bomb limits (an .xlsx is a zip; checked before openpyxl opens it) ──────────────────
TOO_BIG_TO_READ = {"ok": False, "error": "bad_request", "message": "That workbook is too big to read.",
                   "fields": {"file": "Pick a smaller file."}}
UNREADABLE = {"ok": False, "error": "bad_request", "message": iw.UNREADABLE_MESSAGE,
              "fields": {"file": "Use the workbook or a CSV."}}


def _zip(parts):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in parts.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _answer(casey, data):
    """What the import says about this .xlsx: TOO_BIG_TO_READ when a zip limit refused it, else
    UNREADABLE (it passed the zip checks, and openpyxl found no workbook in it)."""
    res = upload(casey, data)
    assert res.status_code in (400, 413), res.text
    return res.json()


def test_the_zip_limits_are_bds():
    assert (iw.MAX_UNPACKED, iw.MAX_PART_UNPACKED, iw.MAX_PART_RATIO, iw.RATIO_FLOOR) == (
        200 * 1024 * 1024, 20 * 1024 * 1024, 100, 1024 * 1024)


def test_the_total_unpacked_size_stops_at_its_limit(casey, monkeypatch):
    monkeypatch.setattr(iw, "MAX_UNPACKED", 3000)
    a, b = os.urandom(1500), os.urandom(1500)
    assert _answer(casey, _zip({"a.xml": a, "b.xml": b})) == UNREADABLE                 # exactly 3000
    assert _answer(casey, _zip({"a.xml": a, "b.xml": b + b"x"})) == TOO_BIG_TO_READ     # 3001


def test_one_part_stops_at_its_limit(casey, monkeypatch):
    monkeypatch.setattr(iw, "MAX_PART_UNPACKED", 2000)
    assert _answer(casey, _zip({"xl/sharedStrings.xml": os.urandom(2000)})) == UNREADABLE
    assert _answer(casey, _zip({"xl/sharedStrings.xml": os.urandom(2001)})) == TOO_BIG_TO_READ


def test_a_part_over_the_floor_stops_at_100_times_its_packed_size(casey, monkeypatch):
    monkeypatch.setattr(iw, "RATIO_FLOOR", 50_000)
    zeros = _zip({"xl/worksheets/sheet1.xml": b"\0" * 50_000})
    with zipfile.ZipFile(io.BytesIO(zeros)) as zf:
        assert zf.infolist()[0].compress_size * 100 < 50_000                                 # far over 100x
    assert _answer(casey, _zip({"xl/worksheets/sheet1.xml": os.urandom(60_000)})) == UNREADABLE    # ~1x
    assert _answer(casey, zeros) == UNREADABLE                                                     # at the floor
    assert _answer(casey, _zip({"xl/worksheets/sheet1.xml": b"\0" * 50_001})) == TOO_BIG_TO_READ  # just over it


def test_a_real_sized_bomb_is_refused_before_it_is_opened(casey):
    """At BD's own limits: 5 MB of zeros packs about 1000 times (under 20 MB, over 100x)."""
    data = _zip({"xl/worksheets/sheet1.xml": b"\0" * (5 * 1024 * 1024)})
    assert len(data) < 100 * 1024
    assert _answer(casey, data) == TOO_BIG_TO_READ


# ── GET /api/bd/admin/imports ────────────────────────────────────────────────────────────────
def test_the_history_is_newest_first_and_pages(casey, users):
    ids = [ok_import(upload(casey, workbook_bytes(), dry_run=d))["id"] for d in ("true", "false", "true")]
    body = casey.get("/api/bd/admin/imports").json()
    assert body["ok"] is True and body["total"] == 3
    assert [i["id"] for i in body["items"]] == list(reversed(ids))
    assert [i["dry_run"] for i in body["items"]] == [True, False, True]
    page = casey.get("/api/bd/admin/imports", params={"limit": 1, "offset": 1}).json()
    assert [i["id"] for i in page["items"]] == [ids[1]] and page["total"] == 3
    assert len(casey.get("/api/bd/admin/imports", params={"limit": 9999}).json()["items"]) == 3
    assert len(casey.get("/api/bd/admin/imports", params={"limit": 0}).json()["items"]) == 3
    for bad in ({"offset": -1}, {"limit": "many"}):
        r = casey.get("/api/bd/admin/imports", params=bad)
        assert r.status_code == 400 and r.json()["error"] == "bad_request" and r.json()["fields"]


def test_the_history_on_the_fixture_seed(bd_seeded, bd_as_user):
    c = bd_as_user(3)
    first = c.get("/api/bd/admin/imports").json()
    # The seed's import 701: 15:00 UTC on 1 Oct is 10:00 CDT; run by Emery Stoll (5).
    assert first == {"ok": True, "total": 1, "items": [{
        "id": 701, "file_name": "bd-fixture-import.csv", "dry_run": True, "started_at": "2026-10-01T10:00:00-05:00",
        "by": {"id": 5, "name": "Emery Stoll"}, "rows_read": 3, "created": 2, "updated": 0, "skipped": 1,
        "possible_duplicates": 1, "errors": [{"row": 4, "error": "No company name"}]}]}
    rec = ok_import(upload(c, b"Company,Name\nNorthvane Plastics,Lou Kim\n", name="BD workbook.csv", mime="text/csv"))
    assert rec["id"] == 702 and rec["by"] == {"id": 3, "name": "Casey Moret"}
    assert_shape(contract_import_example(), {"ok": True, "import": rec})
    assert [i["id"] for i in c.get("/api/bd/admin/imports").json()["items"]] == [702, 701]


# ── the command line (python -m bd.ops.import_workbook) ────────────────────────────────────────
def test_the_command_line_dry_run_then_real_run(users, bd_db, bd_db_url, tmp_path, capsys):
    import _bd_db

    url = _bd_db.app_login_url(bd_db_url)
    path = tmp_path / "made up workbook.xlsx"
    path.write_bytes(workbook_bytes())
    assert iw.main([str(path), "--dry-run", "--url", url, "--by", "casey.moret@example.com"]) == 0
    out = capsys.readouterr().out
    assert "Practice run" in out and "5 added" in out and "No company name." in out
    assert "Dana" not in out and "example.com" not in out          # no personal data on the console
    assert counts(bd_db)["contacts"] == 0 and counts(bd_db)["imports"] == 1
    assert iw.main([str(path), "--url", url]) == 0
    assert "Imported: 7 rows read, 5 added" in capsys.readouterr().out
    assert counts(bd_db)["contacts"] == 5
    rows = bd_db.execute("select by_id, dry_run from bd.imports order by id").fetchall()
    assert [(r["by_id"], r["dry_run"]) for r in rows] == [(users["casey"]["id"], True), (None, False)]


def test_the_command_line_refuses_a_bad_file(users, bd_db_url, tmp_path, capsys):
    import _bd_db

    url = _bd_db.app_login_url(bd_db_url)
    bad = tmp_path / "notes.txt"
    bad.write_text("made up", encoding="utf-8")
    assert iw.main([str(bad), "--url", url]) == 2
    assert "Pick an .xlsx or .csv file." in capsys.readouterr().err
    assert iw.main([str(tmp_path / "missing.xlsx"), "--url", url]) == 2
    good = tmp_path / "x.csv"
    good.write_text("Company,Name\nA,B\n", encoding="utf-8")
    assert iw.main([str(good), "--url", url, "--by", "nobody@example.com"]) == 2


def test_the_command_line_refuses_a_database_behind_the_code(users, bd_db_url, tmp_path, capsys, monkeypatch):
    import _bd_db
    from bd import ledger

    monkeypatch.setattr(ledger, "ledger_behind", lambda conn, *a, **k: True)
    good = tmp_path / "x.csv"
    good.write_text("Company,Name\nA,B\n", encoding="utf-8")
    assert iw.main([str(good), "--url", _bd_db.app_login_url(bd_db_url)]) == 2
    assert "not up to date" in capsys.readouterr().err
