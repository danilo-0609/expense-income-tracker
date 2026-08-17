"""Tests for mcp_sheets_server's aggregation logic and MCP tool wiring."""

import asyncio
import json
from unittest.mock import MagicMock

import pytest

from mcp_sheets_server import aggregate_budget_status, build_server


def budget_row(category, amount):
    return {"Categoría": category, "Monto Presupuestado (COP)": amount}


def expense_row(category, amount):
    return {"Categoría": category, "Monto (COP)": amount}


def income_row(amount):
    return {"Monto (COP)": amount}


def test_all_categories_budgeted_computes_pct_used_and_status():
    budget_rows = [budget_row("Alimentación", 600000), budget_row("Transporte", 200000)]
    expense_rows = [expense_row("Alimentación", 480000), expense_row("Transporte", 220000)]

    result = aggregate_budget_status("August", 2026, budget_rows, expense_rows, [])

    by_category = {c["category"]: c for c in result["categories"]}
    assert by_category["Alimentación"]["status"] == "near_limit"
    assert by_category["Alimentación"]["pct_used"] == 80.0
    assert by_category["Transporte"]["status"] == "over_budget"
    assert round(by_category["Transporte"]["pct_used"], 2) == 110.0
    assert result["budget_configured"] is True


def test_unbudgeted_category_reported_as_sin_presupuesto():
    budget_rows = [budget_row("Alimentación", 600000)]
    expense_rows = [expense_row("Alimentación", 480000), expense_row("Salud", 30000)]

    result = aggregate_budget_status("August", 2026, budget_rows, expense_rows, [])

    by_category = {c["category"]: c for c in result["categories"]}
    assert by_category["Salud"] == {
        "category": "Salud",
        "spent": 30000.0,
        "budgeted": None,
        "pct_used": None,
        "status": "sin_presupuesto",
    }


def test_total_pct_used_uses_all_spend_including_unbudgeted():
    """Worked example from the spec: unbudgeted Salud spend still inflates
    total_pct_used even though it doesn't contribute to total_budget."""
    budget_rows = [budget_row("Alimentación", 600000), budget_row("Transporte", 200000)]
    expense_rows = [
        expense_row("Alimentación", 480000),
        expense_row("Transporte", 220000),
        expense_row("Salud", 30000),
    ]
    income_rows = [income_row(3000000)]

    result = aggregate_budget_status("August", 2026, budget_rows, expense_rows, income_rows)

    assert result["total_spent"] == 730000.0
    assert result["total_budget"] == 800000.0
    assert result["total_pct_used"] == 91.25
    assert result["total_status"] == "near_limit"
    assert result["total_income"] == 3000000.0


def test_no_presupuesto_tab_marks_budget_not_configured():
    expense_rows = [expense_row("Alimentación", 480000)]

    result = aggregate_budget_status("August", 2026, None, expense_rows, [])

    assert result["budget_configured"] is False
    assert result["total_budget"] is None
    assert result["total_pct_used"] is None
    assert result["total_status"] is None
    assert all(c["status"] == "sin_presupuesto" for c in result["categories"])


def test_no_expenses_yet_this_month_is_zero_spend_not_an_error():
    budget_rows = [budget_row("Alimentación", 600000)]

    result = aggregate_budget_status("August", 2026, budget_rows, [], [])

    by_category = {c["category"]: c for c in result["categories"]}
    assert by_category["Alimentación"]["spent"] == 0
    assert by_category["Alimentación"]["pct_used"] == 0.0
    assert by_category["Alimentación"]["status"] == "ok"
    assert result["total_spent"] == 0


def test_threshold_boundary_exactly_80_is_near_limit():
    budget_rows = [budget_row("Alimentación", 100000)]
    expense_rows = [expense_row("Alimentación", 80000)]

    result = aggregate_budget_status("August", 2026, budget_rows, expense_rows, [])

    assert result["categories"][0]["status"] == "near_limit"


def test_threshold_boundary_exactly_100_is_over_budget():
    budget_rows = [budget_row("Alimentación", 100000)]
    expense_rows = [expense_row("Alimentación", 100000)]

    result = aggregate_budget_status("August", 2026, budget_rows, expense_rows, [])

    assert result["categories"][0]["status"] == "over_budget"


def test_threshold_boundary_just_under_80_is_ok():
    budget_rows = [budget_row("Alimentación", 100000)]
    expense_rows = [expense_row("Alimentación", 79999)]

    result = aggregate_budget_status("August", 2026, budget_rows, expense_rows, [])

    assert result["categories"][0]["status"] == "ok"


def test_total_income_reported_as_sum_of_income_rows():
    result = aggregate_budget_status(
        "August", 2026, [budget_row("Alimentación", 100000)], [], [income_row(3000000), income_row(50000)]
    )

    assert result["total_income"] == 3050000.0


def _call_tool(server, name, arguments=None):
    """Invoke a registered MCPServer tool by name and return its payload as a dict."""
    result = asyncio.run(server.call_tool(name, arguments or {}))
    return json.loads(result.content[0].text)


def test_get_budget_status_tool_reads_sheets_and_returns_aggregate_shape():
    reader = MagicMock()
    reader.read_sheet_rows.side_effect = lambda name: {
        "Presupuesto": [budget_row("Alimentación", 600000)],
    }.get(name, [] if "Ingresos" in name or "/" in name else None)

    server = build_server(reader)

    payload = _call_tool(server, "get_budget_status")

    # Full documented shape from the spec's "Tools" section, not just a
    # handful of keys - a shape regression anywhere should fail this test.
    assert set(payload.keys()) == {
        "month", "year", "budget_configured", "categories",
        "total_spent", "total_budget", "total_pct_used", "total_status", "total_income",
    }
    assert payload["budget_configured"] is True
    assert payload["categories"] == [
        {
            "category": "Alimentación",
            "spent": 0,
            "budgeted": 600000.0,
            "pct_used": 0.0,
            "status": "ok",
        }
    ]
    assert payload["total_spent"] == 0
    assert payload["total_budget"] == 600000.0
    assert payload["total_pct_used"] == 0.0
    assert payload["total_status"] == "ok"
    assert payload["total_income"] == 0


def test_get_budget_status_tool_treats_missing_expense_tab_as_zero_spend():
    reader = MagicMock()
    reader.read_sheet_rows.side_effect = lambda name: (
        [budget_row("Alimentación", 600000)] if name == "Presupuesto" else None
    )

    server = build_server(reader)

    payload = _call_tool(server, "get_budget_status")

    by_category = {c["category"]: c for c in payload["categories"]}
    assert by_category["Alimentación"]["spent"] == 0
    assert payload["total_income"] == 0
