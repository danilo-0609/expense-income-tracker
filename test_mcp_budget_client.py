"""Integration-style test for McpBudgetClient's subprocess lifecycle.

Deliberately lighter-weight and separated from the unit-test suite (see
CODING_STANDARDS.md Sec.5): it spawns a real subprocess and speaks real MCP
stdio, but against a tiny throwaway server fixture instead of
mcp_sheets_server.py, so it doesn't need real Google Sheets credentials.
"""

import textwrap

import pytest

from mcp_budget_client import McpBudgetClient

FAKE_SERVER_SOURCE = textwrap.dedent(
    """
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("fake-budget-server")

    @server.tool()
    def get_budget_status() -> dict:
        return {"budget_configured": True, "total_income": 1}

    @server.tool()
    def get_historical_entries(start_date: str, end_date: str, types: list) -> dict:
        return {
            "start_date": start_date,
            "end_date": end_date,
            "requested_types": types,
            "months_missing": [],
            "expenses": [],
            "income": [],
        }

    if __name__ == "__main__":
        server.run(transport="stdio")
    """
)


@pytest.fixture
def fake_server_script(tmp_path):
    script_path = tmp_path / "fake_mcp_server.py"
    script_path.write_text(FAKE_SERVER_SOURCE)
    return str(script_path)


def test_start_connects_and_get_budget_status_round_trips(fake_server_script):
    client = McpBudgetClient(server_script=fake_server_script)
    client.start()
    try:
        result = client.get_budget_status()
        assert result == {"budget_configured": True, "total_income": 1}
    finally:
        client.stop()


def test_get_historical_entries_round_trips(fake_server_script):
    client = McpBudgetClient(server_script=fake_server_script)
    client.start()
    try:
        result = client.get_historical_entries("2026-08-01", "2026-08-31", ["gasto"])
        assert result == {
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "requested_types": ["gasto"],
            "months_missing": [],
            "expenses": [],
            "income": [],
        }
    finally:
        client.stop()


def test_stop_terminates_the_subprocess_cleanly(fake_server_script):
    client = McpBudgetClient(server_script=fake_server_script)
    client.start()
    assert client._thread.is_alive()

    client.stop()

    assert not client._thread.is_alive()
