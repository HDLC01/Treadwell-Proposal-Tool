"""_normalize_cell_value: how openpyxl date/time objects render in the grid.

Guards the "Bid Date shows 00:00:00" bug — a date-formatted `=Epoxy!B2` over an
empty source caches midnight 1899, which openpyxl reads back as time(0,0)/an
1899 date; both must render blank, while real dates render as M/D/YYYY.
"""
import datetime as dt

import estimate_writer as ew


def test_bare_time_is_blank():
    assert ew._normalize_cell_value(dt.time(0, 0)) is None
    assert ew._normalize_cell_value(dt.time(13, 30, 0)) is None


def test_excel_epoch_datetime_is_blank():
    assert ew._normalize_cell_value(dt.datetime(1899, 12, 30)) is None
    assert ew._normalize_cell_value(dt.datetime(1900, 1, 1)) is None


def test_real_datetime_renders_mdy():
    assert ew._normalize_cell_value(dt.datetime(2026, 6, 15, 9, 0)) == "6/15/2026"


def test_real_date_renders_mdy():
    assert ew._normalize_cell_value(dt.date(2026, 12, 1)) == "12/1/2026"


def test_numbers_and_strings_pass_through():
    assert ew._normalize_cell_value(0) == 0
    assert ew._normalize_cell_value(1234.5) == 1234.5
    assert ew._normalize_cell_value("QA Sheet Test") == "QA Sheet Test"
    assert ew._normalize_cell_value(None) is None
