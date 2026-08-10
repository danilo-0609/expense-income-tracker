"""Google Sheets integration for expense tracking."""

import json
import logging
import os
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

# Load environment variables from .env file
load_dotenv()


logger = logging.getLogger(__name__)


class SheetsWriter:
    """Handles writing expenses to Google Sheets."""

    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
    HEADERS = ["Fecha", "Categoría", "Descripción", "Monto (COP)", "Notas"]
    SHEET_NAME_PREFIXES = {"gasto": "", "ingreso": "Ingresos - "}
    MONTH_NAMES = {
        1: "January", 2: "February", 3: "March", 4: "April",
        5: "May", 6: "June", 7: "July", 8: "August",
        9: "September", 10: "October", 11: "November", 12: "December"
    }

    def __init__(self, service_account_json_path: str, spreadsheet_id: str):
        """
        Initialize Google Sheets client.

        Args:
            service_account_json_path: Path to service account JSON key
            spreadsheet_id: Google Sheets spreadsheet ID
        """
        try:
            credentials = Credentials.from_service_account_file(
                service_account_json_path, scopes=self.SCOPES
            )
            self.client = gspread.authorize(credentials)
            self.spreadsheet = self.client.open_by_key(spreadsheet_id)
            self.sheet_cache = {}  # Cache sheet objects by name
            logger.info(f"Connected to spreadsheet: {spreadsheet_id}")
        except Exception as e:
            logger.error(f"Failed to connect to Google Sheets: {e}")
            raise

    def _get_sheet_name(self, date_str: str, entry_type: str = "gasto") -> str:
        """
        Convert date string to sheet name.

        Args:
            date_str: Date in format "YYYY-MM-DD"
            entry_type: "gasto" (default) or "ingreso" - selects the sheet prefix

        Returns:
            Sheet name like "August/2026" or "Ingresos - August/2026"
        """
        prefix = self.SHEET_NAME_PREFIXES.get(entry_type, "")
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            month_name = self.MONTH_NAMES[date_obj.month]
            year = date_obj.year
            return f"{prefix}{month_name}/{year}"
        except (ValueError, KeyError):
            logger.error(f"Invalid date format: {date_str}. Using default sheet.")
            return f"{prefix}Other"

    def _get_or_create_sheet(self, sheet_name: str) -> gspread.Worksheet:
        """
        Get existing sheet or create new one with headers.

        Args:
            sheet_name: Name of the sheet (e.g., "August/2026")

        Returns:
            gspread.Worksheet object
        """
        # Check cache first
        if sheet_name in self.sheet_cache:
            return self.sheet_cache[sheet_name]

        # Try to find existing sheet
        try:
            worksheet = self.spreadsheet.worksheet(sheet_name)
            self.sheet_cache[sheet_name] = worksheet
            logger.info(f"Using existing sheet: {sheet_name}")
            return worksheet
        except gspread.exceptions.WorksheetNotFound:
            # Sheet doesn't exist, create it
            logger.info(f"Creating new sheet: {sheet_name}")
            worksheet = self.spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=5)
            # Add headers
            worksheet.append_row(self.HEADERS)
            self.sheet_cache[sheet_name] = worksheet
            logger.info(f"Sheet created with headers: {sheet_name}")
            return worksheet

    def write_expense(self, expense: dict) -> bool:
        """
        Write expense to Google Sheets in the appropriate monthly sheet.

        Args:
            expense: Expense dict with keys: category, amount, description, date, notes

        Returns:
            True if successful, False otherwise
        """
        if expense.get("error"):
            logger.warning(f"Skipping error expense: {expense}")
            return False

        try:
            # Get the sheet for this entry's month, routed by type (gasto/ingreso)
            date_str = expense.get("date", "")
            entry_type = expense.get("type", "gasto")
            sheet_name = self._get_sheet_name(date_str, entry_type)
            worksheet = self._get_or_create_sheet(sheet_name)

            # Prepare row data
            row = [
                date_str,
                expense.get("category", ""),
                expense.get("description", ""),
                expense.get("amount", ""),
                expense.get("notes", ""),
            ]

            # Write to the appropriate sheet
            worksheet.append_row(row)
            logger.info(f"Expense written to sheet '{sheet_name}': {expense}")
            return True
        except Exception as e:
            logger.error(f"Failed to write expense to Sheets: {e}")
            return False

    def write_expenses(self, expenses: list[dict]) -> int:
        """
        Write multiple expenses to Google Sheets.

        Args:
            expenses: List of expense dicts

        Returns:
            Number of expenses successfully written
        """
        success_count = 0
        for expense in expenses:
            if self.write_expense(expense):
                success_count += 1
        return success_count


def main():
    """Test the Sheets writer."""
    import os

    service_account_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH", "service_account.json")
    spreadsheet_id = os.getenv("GOOGLE_SHEETS_ID")

    if not spreadsheet_id:
        print("Error: GOOGLE_SHEETS_ID environment variable not set")
        return

    if not os.path.exists(service_account_path):
        print(f"Error: Service account file not found at {service_account_path}")
        return

    try:
        writer = SheetsWriter(service_account_path, spreadsheet_id)

        # Test expenses from different months
        test_expenses = [
            {
                "category": "Alimentación",
                "amount": 25000,
                "description": "Almuerzo en Starbucks",
                "date": "2026-07-25",
                "notes": "",
            },
            {
                "category": "Transporte",
                "amount": 28500,
                "description": "Uber al trabajo",
                "date": "2026-08-05",
                "notes": "",
            },
            {
                "category": "Salud",
                "amount": 30000,
                "description": "Farmacia",
                "date": "2026-08-10",
                "notes": "",
            },
            {
                "category": "Entretenimiento",
                "amount": 54900,
                "description": "Suscripción Netflix",
                "date": "2026-09-01",
                "notes": "",
            },
        ]

        print("\n📝 Testing monthly sheet organization...")
        print("-" * 60)
        success_count = writer.write_expenses(test_expenses)
        print("-" * 60)

        if success_count == len(test_expenses):
            print(f"✅ All {success_count} expenses written successfully!")
            print("\nSheets created:")
            print("  • July/2026 (1 expense)")
            print("  • August/2026 (2 expenses)")
            print("  • September/2026 (1 expense)")
        else:
            print(f"⚠️  {success_count}/{len(test_expenses)} expenses written")

    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    main()
