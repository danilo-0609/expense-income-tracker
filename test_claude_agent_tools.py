"""Tests for ToolCallingExpenseAgent's tool dispatch and agentic loop."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from claude_agent_tools import AgentTurnResult, ToolCallingExpenseAgent


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_use_block(name, tool_input, tool_id="toolu_1"):
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=tool_input)


def response(*blocks):
    return SimpleNamespace(content=list(blocks))


def make_agent(sheets_writer=None):
    agent = ToolCallingExpenseAgent("fake-claude-key", sheets_writer=sheets_writer)
    agent.client = MagicMock()
    return agent


def make_entry(description="Almuerzo", entry_type="gasto", category="Alimentación", amount=25000):
    return {
        "type": entry_type,
        "category": category,
        "amount": amount,
        "description": description,
        "date": "2026-08-11",
        "notes": "",
    }


def test_save_entries_writes_each_entry_and_returns_saved_result():
    sheets_writer = MagicMock()
    sheets_writer.write_expense.return_value = True
    agent = make_agent(sheets_writer)
    entry = make_entry()
    agent.client.messages.create.side_effect = [
        response(tool_use_block("save_entries", {"entries": [entry]})),
        response(text_block("✅ Gasto guardado: Alimentación - $25,000 COP - Almuerzo")),
    ]

    result = agent.handle_message([], "Almuerzo, 25000")

    assert isinstance(result, AgentTurnResult)
    assert result.kind == "saved"
    assert result.text == "✅ Gasto guardado: Alimentación - $25,000 COP - Almuerzo"
    assert result.pending_tool_use_id is None
    sheets_writer.write_expense.assert_called_once_with(entry)
    assert agent.client.messages.create.call_count == 2


def test_save_entries_batches_multiple_entries_in_one_tool_call():
    sheets_writer = MagicMock()
    sheets_writer.write_expense.return_value = True
    agent = make_agent(sheets_writer)
    entries = [make_entry("Almuerzo", amount=20000), make_entry("Uber al trabajo", amount=15000, category="Transporte")]
    agent.client.messages.create.side_effect = [
        response(tool_use_block("save_entries", {"entries": entries})),
        response(text_block("✅ Gasto guardado x2")),
    ]

    agent.handle_message([], "Almuerzo 20000, Uber al trabajo 15000")

    assert sheets_writer.write_expense.call_count == 2
    # One save_entries call plus one confirmation call - never one Claude call per entry.
    assert agent.client.messages.create.call_count == 2


def test_save_entries_partial_failure_reports_per_row_breakdown_to_claude():
    sheets_writer = MagicMock()
    sheets_writer.write_expense.side_effect = [True, False]
    agent = make_agent(sheets_writer)
    entries = [make_entry("Almuerzo"), make_entry("Uber al trabajo", category="Transporte")]
    agent.client.messages.create.side_effect = [
        response(tool_use_block("save_entries", {"entries": entries})),
        response(text_block("✅ Gasto guardado: Almuerzo\n❌ No se pudo guardar: Uber al trabajo")),
    ]

    result = agent.handle_message([], "...")

    second_call_messages = agent.client.messages.create.call_args_list[1].kwargs["messages"]
    tool_result_message = second_call_messages[-1]
    tool_result_payload = json.loads(tool_result_message["content"][0]["content"])
    results = tool_result_payload["results"]
    assert results[0] == {"description": "Almuerzo", "success": True}
    assert results[1]["description"] == "Uber al trabajo"
    assert results[1]["success"] is False
    assert "error" in results[1]
    assert result.kind == "saved"


def test_save_entries_without_sheets_writer_reports_success_without_writing():
    agent = make_agent(sheets_writer=None)
    entry = make_entry()
    agent.client.messages.create.side_effect = [
        response(tool_use_block("save_entries", {"entries": [entry]})),
        response(text_block("✅ Gasto guardado")),
    ]

    result = agent.handle_message([], "Almuerzo, 25000")

    assert result.kind == "saved"


def test_ask_clarification_returns_question_without_writing_to_sheets():
    sheets_writer = MagicMock()
    agent = make_agent(sheets_writer)
    agent.client.messages.create.side_effect = [
        response(tool_use_block("ask_clarification", {"question": "¿Cuál fue el monto del gasto?"}, tool_id="toolu_q1")),
    ]

    result = agent.handle_message([], "Café en Starbucks ayer")

    assert result.kind == "clarification"
    assert result.text == "¿Cuál fue el monto del gasto?"
    assert result.pending_tool_use_id == "toolu_q1"
    sheets_writer.write_expense.assert_not_called()
    # No second turn needed - the clarification question IS the reply.
    assert agent.client.messages.create.call_count == 1


def test_missing_tool_use_returns_error_kind_not_off_topic():
    """Claude is instructed to always call exactly one tool; if it doesn't,
    that's an internal failure to surface as an error, not a real off_topic
    classification (which only flag_off_topic should produce)."""
    sheets_writer = MagicMock()
    agent = make_agent(sheets_writer)
    agent.client.messages.create.side_effect = [
        response(text_block("no sé qué hacer con esto")),
    ]

    result = agent.handle_message([], "algo raro")

    assert result.kind == "error"
    sheets_writer.write_expense.assert_not_called()


def test_flag_off_topic_returns_off_topic_kind_without_writing_to_sheets():
    sheets_writer = MagicMock()
    agent = make_agent(sheets_writer)
    agent.client.messages.create.side_effect = [
        response(tool_use_block("flag_off_topic", {})),
    ]

    result = agent.handle_message([], "¿Cuál es la población de Brasil?")

    assert result.kind == "off_topic"
    sheets_writer.write_expense.assert_not_called()
    assert agent.client.messages.create.call_count == 1


def test_clarification_history_includes_assistant_turn_for_followup_context():
    agent = make_agent()
    agent.client.messages.create.side_effect = [
        response(tool_use_block("ask_clarification", {"question": "¿Cuál fue el monto del gasto?"})),
    ]

    result = agent.handle_message([], "Café en Starbucks ayer")

    assert result.history[-1]["role"] == "assistant"


def test_followup_answering_a_pending_clarification_is_sent_as_a_tool_result():
    """Anthropic requires every tool_use block to be immediately followed by a
    tool_result block in the next message - the user's answer to
    ask_clarification must be wrapped as the tool_result for that tool_use id,
    not a fresh plain-text user turn, or the next API call is rejected."""
    agent = make_agent()
    agent.client.messages.create.side_effect = [
        response(tool_use_block("ask_clarification", {"question": "¿Cuál fue el monto del gasto?"}, tool_id="toolu_q1")),
    ]
    first = agent.handle_message([], "Café en Starbucks ayer")

    agent.client.messages.create.side_effect = [
        response(tool_use_block("save_entries", {"entries": [make_entry("Café en Starbucks", amount=6000)]})),
        response(text_block("✅ Gasto guardado: Alimentación - $6,000 COP - Café en Starbucks")),
    ]
    agent.handle_message(first.history, "6000", pending_tool_use_id=first.pending_tool_use_id)

    second_call_messages = agent.client.messages.create.call_args_list[1].kwargs["messages"]
    followup_message = second_call_messages[-1]
    assert followup_message["role"] == "user"
    assert followup_message["content"][0]["type"] == "tool_result"
    assert followup_message["content"][0]["tool_use_id"] == "toolu_q1"
    assert followup_message["content"][0]["content"] == "6000"


def test_multiturn_clarification_followup_resolves_into_save_entries():
    sheets_writer = MagicMock()
    sheets_writer.write_expense.return_value = True
    agent = make_agent(sheets_writer)
    agent.client.messages.create.side_effect = [
        response(tool_use_block("ask_clarification", {"question": "¿Cuál fue el monto del gasto?"}, tool_id="toolu_q1")),
    ]
    first = agent.handle_message([], "Café en Starbucks ayer")

    entry = make_entry("Café en Starbucks", amount=6000)
    agent.client.messages.create.side_effect = [
        response(tool_use_block("save_entries", {"entries": [entry]})),
        response(text_block("✅ Gasto guardado: Alimentación - $6,000 COP - Café en Starbucks")),
    ]
    second = agent.handle_message(first.history, "6000", pending_tool_use_id=first.pending_tool_use_id)

    assert second.kind == "saved"
    sheets_writer.write_expense.assert_called_once_with(entry)


def test_get_budget_summary_calls_mcp_client_and_returns_composed_text():
    mcp_client = MagicMock()
    budget_status = {
        "month": "August", "year": 2026, "budget_configured": True,
        "categories": [{"category": "Transporte", "spent": 220000, "budgeted": 200000, "pct_used": 110.0, "status": "over_budget"}],
        "total_spent": 220000, "total_budget": 200000, "total_pct_used": 110.0,
        "total_status": "over_budget", "total_income": 3000000,
    }
    mcp_client.get_budget_status.return_value = budget_status
    agent = ToolCallingExpenseAgent("fake-claude-key", mcp_client=mcp_client)
    agent.client = MagicMock()
    agent.client.messages.create.side_effect = [
        response(tool_use_block("get_budget_summary", {}, tool_id="toolu_b1")),
        response(text_block("Vas 110% en Transporte, por encima del presupuesto.")),
    ]

    result = agent.handle_message([], "¿cómo voy con el presupuesto?")

    assert isinstance(result, AgentTurnResult)
    assert result.kind == "summary"
    assert result.text == "Vas 110% en Transporte, por encima del presupuesto."
    mcp_client.get_budget_status.assert_called_once_with()

    second_call_messages = agent.client.messages.create.call_args_list[1].kwargs["messages"]
    tool_result_message = second_call_messages[-1]
    tool_result_payload = json.loads(tool_result_message["content"][0]["content"])
    assert tool_result_payload == budget_status
    assert tool_result_message["content"][0]["tool_use_id"] == "toolu_b1"


def test_get_budget_summary_without_mcp_client_still_composes_a_reply():
    agent = ToolCallingExpenseAgent("fake-claude-key", mcp_client=None)
    agent.client = MagicMock()
    agent.client.messages.create.side_effect = [
        response(tool_use_block("get_budget_summary", {})),
        response(text_block("No pude consultar el presupuesto en este momento.")),
    ]

    result = agent.handle_message([], "¿cómo voy con el presupuesto?")

    assert result.kind == "summary"
    assert result.text == "No pude consultar el presupuesto en este momento."


def test_get_budget_summary_does_not_write_to_sheets():
    sheets_writer = MagicMock()
    mcp_client = MagicMock()
    mcp_client.get_budget_status.return_value = {"budget_configured": False}
    agent = ToolCallingExpenseAgent("fake-claude-key", sheets_writer=sheets_writer, mcp_client=mcp_client)
    agent.client = MagicMock()
    agent.client.messages.create.side_effect = [
        response(tool_use_block("get_budget_summary", {})),
        response(text_block("Todavía no tienes un presupuesto configurado.")),
    ]

    agent.handle_message([], "¿en qué estoy gastando de más?")

    sheets_writer.write_expense.assert_not_called()


def test_get_historical_entries_calls_mcp_client_with_parsed_args_and_composes_reply():
    mcp_client = MagicMock()
    historical_result = {
        "start_date": "2026-08-01", "end_date": "2026-08-08",
        "requested_types": ["gasto"], "months_missing": [],
        "expenses": [{"date": "2026-08-08", "category": "Alimentación", "description": "Almuerzo", "amount": 25000, "notes": ""}],
        "income": [],
    }
    mcp_client.get_historical_entries.return_value = historical_result
    agent = ToolCallingExpenseAgent("fake-claude-key", mcp_client=mcp_client)
    agent.client = MagicMock()
    agent.client.messages.create.side_effect = [
        response(tool_use_block(
            "get_historical_entries",
            {"start_date": "2026-08-01", "end_date": "2026-08-08", "types": ["gasto"]},
            tool_id="toolu_h1",
        )),
        response(text_block("El 8 de agosto gastaste $25,000 COP en Alimentación (Almuerzo).")),
    ]

    result = agent.handle_message([], "¿qué gastos tuve el 8 de agosto?")

    assert isinstance(result, AgentTurnResult)
    assert result.kind == "history"
    assert result.text == "El 8 de agosto gastaste $25,000 COP en Alimentación (Almuerzo)."
    mcp_client.get_historical_entries.assert_called_once_with("2026-08-01", "2026-08-08", ["gasto"])

    second_call_messages = agent.client.messages.create.call_args_list[1].kwargs["messages"]
    tool_result_message = second_call_messages[-1]
    tool_result_payload = json.loads(tool_result_message["content"][0]["content"])
    assert tool_result_payload == historical_result
    assert tool_result_message["content"][0]["tool_use_id"] == "toolu_h1"


def test_get_historical_entries_without_mcp_client_still_composes_a_reply():
    agent = ToolCallingExpenseAgent("fake-claude-key", mcp_client=None)
    agent.client = MagicMock()
    agent.client.messages.create.side_effect = [
        response(tool_use_block(
            "get_historical_entries",
            {"start_date": "2026-08-01", "end_date": "2026-08-08", "types": ["gasto"]},
        )),
        response(text_block("No pude consultar el historial en este momento.")),
    ]

    result = agent.handle_message([], "¿qué gastos tuve el 8 de agosto?")

    assert result.kind == "history"
    assert result.text == "No pude consultar el historial en este momento."


def test_get_historical_entries_does_not_write_to_sheets():
    sheets_writer = MagicMock()
    mcp_client = MagicMock()
    mcp_client.get_historical_entries.return_value = {
        "start_date": "2026-08-01", "end_date": "2026-08-08",
        "requested_types": ["gasto"], "months_missing": [], "expenses": [], "income": [],
    }
    agent = ToolCallingExpenseAgent("fake-claude-key", sheets_writer=sheets_writer, mcp_client=mcp_client)
    agent.client = MagicMock()
    agent.client.messages.create.side_effect = [
        response(tool_use_block(
            "get_historical_entries",
            {"start_date": "2026-08-01", "end_date": "2026-08-08", "types": ["gasto"]},
        )),
        response(text_block("No tienes gastos registrados el 8 de agosto.")),
    ]

    agent.handle_message([], "¿qué gastos tuve el 8 de agosto?")

    sheets_writer.write_expense.assert_not_called()


def test_plain_followup_without_pending_clarification_is_sent_as_normal_text():
    agent = make_agent()
    agent.client.messages.create.side_effect = [
        response(tool_use_block("flag_off_topic", {})),
    ]

    agent.handle_message([], "hola")

    sent_messages = agent.client.messages.create.call_args.kwargs["messages"]
    assert sent_messages[-1] == {"role": "user", "content": "hola"}
