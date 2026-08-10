"""Tests for SheetsWriter's sheet-name routing between expenses and income."""

from unittest.mock import MagicMock

import gspread
import pytest

from sheets_writer import SheetsWriter


def make_writer():
    """Build a SheetsWriter without touching real Google credentials."""
    writer = object.__new__(SheetsWriter)
    writer.client = MagicMock()
    writer.spreadsheet = MagicMock()
    writer.sheet_cache = {}
    return writer


def test_expense_sheet_name_has_no_prefix():
    writer = make_writer()
    assert writer._get_sheet_name("2026-08-09", "gasto") == "August/2026"


def test_income_sheet_name_has_ingresos_prefix():
    writer = make_writer()
    assert writer._get_sheet_name("2026-08-09", "ingreso") == "Ingresos - August/2026"


def test_sheet_name_defaults_to_expense_when_type_missing():
    writer = make_writer()
    assert writer._get_sheet_name("2026-08-09") == "August/2026"


def test_invalid_date_falls_back_to_type_specific_other_sheet():
    writer = make_writer()
    assert writer._get_sheet_name("not-a-date", "ingreso") == "Ingresos - Other"
    assert writer._get_sheet_name("not-a-date", "gasto") == "Other"


def test_expense_and_income_for_same_month_use_separate_cached_sheets():
    writer = make_writer()
    expense_sheet = MagicMock()
    income_sheet = MagicMock()
    writer.spreadsheet.worksheet.side_effect = lambda name: (
        income_sheet if name == "Ingresos - August/2026" else expense_sheet
    )

    writer.write_expense(
        {"type": "gasto", "category": "Alimentación", "amount": 1000,
         "description": "Café", "date": "2026-08-09", "notes": ""}
    )
    writer.write_expense(
        {"type": "ingreso", "category": "Salario", "amount": 3000000,
         "description": "Salario", "date": "2026-08-09", "notes": ""}
    )

    assert writer.sheet_cache["August/2026"] is expense_sheet
    assert writer.sheet_cache["Ingresos - August/2026"] is income_sheet
    expense_sheet.append_row.assert_called_once()
    income_sheet.append_row.assert_called_once()


def test_write_expense_routes_to_expense_sheet():
    writer = make_writer()
    worksheet = MagicMock()
    writer.spreadsheet.worksheet.return_value = worksheet

    expense = {
        "type": "gasto",
        "category": "Alimentación",
        "amount": 25000,
        "description": "Almuerzo",
        "date": "2026-08-09",
        "notes": "",
    }
    assert writer.write_expense(expense) is True

    writer.spreadsheet.worksheet.assert_called_once_with("August/2026")
    worksheet.append_row.assert_called_once_with(
        ["2026-08-09", "Alimentación", "Almuerzo", 25000, ""]
    )


def test_write_expense_routes_income_to_ingresos_sheet():
    writer = make_writer()
    worksheet = MagicMock()
    writer.spreadsheet.worksheet.return_value = worksheet

    income = {
        "type": "ingreso",
        "category": "Salario",
        "amount": 3000000,
        "description": "Salario de agosto",
        "date": "2026-08-09",
        "notes": "",
    }
    assert writer.write_expense(income) is True

    writer.spreadsheet.worksheet.assert_called_once_with("Ingresos - August/2026")
    worksheet.append_row.assert_called_once_with(
        ["2026-08-09", "Salario", "Salario de agosto", 3000000, ""]
    )


def test_write_expense_creates_ingresos_sheet_with_headers_if_missing():
    writer = make_writer()
    writer.spreadsheet.worksheet.side_effect = gspread.exceptions.WorksheetNotFound()
    created = MagicMock()
    writer.spreadsheet.add_worksheet.return_value = created

    income = {
        "type": "ingreso",
        "category": "Rendimientos",
        "amount": 12000,
        "description": "Rendimientos cuenta de ahorros",
        "date": "2026-08-09",
        "notes": "",
    }
    assert writer.write_expense(income) is True

    writer.spreadsheet.add_worksheet.assert_called_once_with(
        title="Ingresos - August/2026", rows=1000, cols=5
    )
    created.append_row.assert_any_call(SheetsWriter.HEADERS)
