"""Self-hosted MCP server exposing read-only budget-status aggregation over
Google Sheets.

Run as a local stdio subprocess by bot_tools.py. Uses the same Service
Account credentials sheets_writer.py already uses (GOOGLE_SERVICE_ACCOUNT_PATH,
GOOGLE_SHEETS_ID) - this server only ever reads, never writes.

The aggregation logic (aggregate_budget_status) is a pure function so it can
be unit-tested without any live Sheets or MCP transport; the MCP tool wrapper
(get_budget_status) just reads raw rows via gspread and hands them to it.
"""

import logging
import os
from datetime import date, datetime

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from mcp.server.mcpserver import MCPServer

from sheet_naming import get_month_sheet_names

load_dotenv()

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

PRESUPUESTO_SHEET_NAME = "Presupuesto"

OVER_BUDGET_THRESHOLD = 100.0
NEAR_LIMIT_THRESHOLD = 80.0

MAX_HISTORICAL_RANGE_MONTHS = 12

HISTORICAL_ROW_FIELD_MAP = {
    "Fecha": "date",
    "Categoría": "category",
    "Descripción": "description",
    "Monto (COP)": "amount",
    "Notas": "notes",
}


def _status_for(pct_used: float) -> str:
    if pct_used >= OVER_BUDGET_THRESHOLD:
        return "over_budget"
    if pct_used >= NEAR_LIMIT_THRESHOLD:
        return "near_limit"
    return "ok"


def aggregate_budget_status(
    month_name: str,
    year: int,
    budget_rows: list[dict] | None,
    expense_rows: list[dict],
    income_rows: list[dict],
) -> dict:
    """
    Compute the budget-status aggregate for one month from raw Sheets rows.

    Args:
        month_name: e.g. "August"
        year: e.g. 2026
        budget_rows: rows from the Presupuesto tab (each a dict with
            "Categoría" and "Monto Presupuestado (COP)"), or None if the
            Presupuesto tab doesn't exist at all.
        expense_rows: rows from the current month's expense tab (each a dict
            with "Categoría" and "Monto (COP)"), or [] if the tab doesn't
            exist yet / has no rows.
        income_rows: rows from the current month's income tab (each a dict
            with "Monto (COP)"), or [] if the tab doesn't exist yet.

    Returns:
        The aggregate dict documented in the spec (see get_budget_status).
    """
    budget_configured = budget_rows is not None

    budgeted_amounts: dict[str, float] = {}
    if budget_configured:
        for row in budget_rows:
            category = row.get("Categoría", "").strip()
            if not category:
                continue
            budgeted_amounts[category] = float(row.get("Monto Presupuestado (COP)", 0) or 0)

    spent_by_category: dict[str, float] = {}
    for row in expense_rows:
        category = row.get("Categoría", "Otros")
        amount = float(row.get("Monto (COP)", 0) or 0)
        spent_by_category[category] = spent_by_category.get(category, 0) + amount

    all_categories = list(budgeted_amounts.keys())
    for category in spent_by_category:
        if category not in all_categories:
            all_categories.append(category)

    categories = []
    for category in all_categories:
        spent = spent_by_category.get(category, 0)
        budgeted = budgeted_amounts.get(category) if budget_configured else None
        if budgeted is None:
            categories.append(
                {
                    "category": category,
                    "spent": spent,
                    "budgeted": None,
                    "pct_used": None,
                    "status": "sin_presupuesto",
                }
            )
        else:
            pct_used = (spent / budgeted * 100) if budgeted > 0 else 0.0
            categories.append(
                {
                    "category": category,
                    "spent": spent,
                    "budgeted": budgeted,
                    "pct_used": pct_used,
                    "status": _status_for(pct_used),
                }
            )

    total_spent = sum(spent_by_category.values())
    total_income = sum(float(row.get("Monto (COP)", 0) or 0) for row in income_rows)

    if budget_configured:
        total_budget = sum(budgeted_amounts.values())
        # Numerator is ALL spend (budgeted or not) for factual accuracy, not
        # just the budgeted categories' spend - so total_pct_used can exceed
        # what the individual budgeted categories alone would suggest
        # whenever unbudgeted categories account for meaningful spend.
        total_pct_used = (total_spent / total_budget * 100) if total_budget > 0 else 0.0
        total_status = _status_for(total_pct_used)
    else:
        total_budget = None
        total_pct_used = None
        total_status = None

    return {
        "month": month_name,
        "year": year,
        "budget_configured": budget_configured,
        "categories": categories,
        "total_spent": total_spent,
        "total_budget": total_budget,
        "total_pct_used": total_pct_used,
        "total_status": total_status,
        "total_income": total_income,
    }


def _months_between(start: date, end: date) -> list[tuple[int, int]]:
    """Inclusive list of (year, month) pairs touched by [start, end]."""
    months = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def resolve_historical_range(
    start_date: str, end_date: str, types: list[str]
) -> tuple[dict | None, list[tuple[int, int]]]:
    """
    Validate a historical query's date range and resolve it to the calendar
    months it touches, without doing any Sheets I/O.

    Returns:
        (error, months) - error is None on success (months then holds the
        list of (year, month) pairs to read), or a JSON-serializable error
        dict per the spec's documented error shapes (months is [] in that
        case).
    """
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        return {
            "error": "invalid_range",
            "message": "start_date and end_date must be valid YYYY-MM-DD dates",
        }, []

    if start > end:
        return {
            "error": "invalid_range",
            "message": "start_date must be on or before end_date",
        }, []

    months = _months_between(start, end)
    if len(months) > MAX_HISTORICAL_RANGE_MONTHS:
        return {"error": "range_too_large", "max_months": MAX_HISTORICAL_RANGE_MONTHS}, []

    return None, months


def _rows_in_range(rows: list[dict], start_date: str, end_date: str) -> list[dict]:
    """Filter raw sheet rows to those dated within [start_date, end_date]
    (both YYYY-MM-DD, safe to compare lexicographically) and remap their
    Spanish column headers to the historical-entries output shape."""
    matched = []
    for row in rows:
        row_date = row.get("Fecha", "")
        if start_date <= row_date <= end_date:
            matched.append({field: row.get(header, "") for header, field in HISTORICAL_ROW_FIELD_MAP.items()})
    return matched


class SheetsReader:
    """Thin gspread wrapper for the reads this server needs."""

    def __init__(self, service_account_json_path: str, spreadsheet_id: str):
        credentials = Credentials.from_service_account_file(
            service_account_json_path, scopes=SCOPES
        )
        self.client = gspread.authorize(credentials)
        self.spreadsheet = self.client.open_by_key(spreadsheet_id)

    def read_sheet_rows(self, sheet_name: str) -> list[dict] | None:
        """Return a sheet's rows as dicts keyed by header, or None if the
        sheet doesn't exist."""
        try:
            worksheet = self.spreadsheet.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            return None
        return worksheet.get_all_records()


def build_server(reader: SheetsReader) -> MCPServer:
    server = MCPServer("expense-tracker-sheets")

    @server.tool()
    def get_budget_status() -> dict:
        """Return the current calendar month's budget-vs-spend breakdown,
        computed from the Presupuesto tab plus this month's expense/income
        tabs. Takes no arguments - always resolves to today's month/year."""
        today = date.today()
        expense_sheet_name, income_sheet_name = get_month_sheet_names(today.month, today.year)

        budget_rows = reader.read_sheet_rows(PRESUPUESTO_SHEET_NAME)
        expense_rows = reader.read_sheet_rows(expense_sheet_name) or []
        income_rows = reader.read_sheet_rows(income_sheet_name) or []

        month_name = expense_sheet_name.split("/")[0]
        return aggregate_budget_status(
            month_name, today.year, budget_rows, expense_rows, income_rows
        )

    @server.tool()
    def get_historical_entries(start_date: str, end_date: str, types: list[str]) -> dict:
        """Return raw expense/income rows (no aggregation) whose date falls
        within [start_date, end_date], for the requested types. Ranges
        spanning more than 12 calendar months are rejected."""
        error, months = resolve_historical_range(start_date, end_date, types)
        if error:
            return error

        months_missing = []
        expenses = []
        income = []
        for year, month in months:
            expense_sheet_name, income_sheet_name = get_month_sheet_names(month, year)

            if "gasto" in types:
                rows = reader.read_sheet_rows(expense_sheet_name)
                if rows is None:
                    months_missing.append(expense_sheet_name)
                else:
                    expenses.extend(_rows_in_range(rows, start_date, end_date))

            if "ingreso" in types:
                rows = reader.read_sheet_rows(income_sheet_name)
                if rows is None:
                    months_missing.append(income_sheet_name)
                else:
                    income.extend(_rows_in_range(rows, start_date, end_date))

        return {
            "start_date": start_date,
            "end_date": end_date,
            "requested_types": types,
            "months_missing": months_missing,
            "expenses": expenses,
            "income": income,
        }

    return server


def main():
    """Entry point for running this module as a stdio MCP server subprocess."""
    logging.basicConfig(level=logging.INFO)

    service_account_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH", "service_account.json")
    spreadsheet_id = os.getenv("GOOGLE_SHEETS_ID")

    if not spreadsheet_id:
        raise ValueError("GOOGLE_SHEETS_ID environment variable not set")

    reader = SheetsReader(service_account_path, spreadsheet_id)
    server = build_server(reader)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
