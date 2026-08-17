"""Pure helpers for resolving Sheets tab names from a date and entry type.

Shared by sheets_writer.py (writes) and mcp_sheets_server.py (reads) so the
month-name table and sheet-name convention live in exactly one place.
"""

from datetime import datetime

MONTH_NAMES = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December"
}

SHEET_NAME_PREFIXES = {"gasto": "", "ingreso": "Ingresos - "}


def get_sheet_name(date_str: str, entry_type: str = "gasto") -> str:
    """
    Convert a date string to a sheet name.

    Args:
        date_str: Date in format "YYYY-MM-DD"
        entry_type: "gasto" (default) or "ingreso" - selects the sheet prefix

    Returns:
        Sheet name like "August/2026" or "Ingresos - August/2026"
    """
    prefix = SHEET_NAME_PREFIXES.get(entry_type, "")
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        month_name = MONTH_NAMES[date_obj.month]
        year = date_obj.year
        return f"{prefix}{month_name}/{year}"
    except (ValueError, KeyError):
        return f"{prefix}Other"


def get_month_sheet_names(month: int, year: int) -> tuple[str, str]:
    """
    Resolve the (expense, income) sheet names for a given month/year, without
    needing a date string - used by mcp_sheets_server.py to look up the
    current month's tabs directly.

    Returns:
        (expense_sheet_name, income_sheet_name)
    """
    month_name = MONTH_NAMES[month]
    return f"{month_name}/{year}", f"Ingresos - {month_name}/{year}"
