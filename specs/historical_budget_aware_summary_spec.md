# Historical Budget-Aware Summary Spec

**Date:** 2026-09-08
**Status:** Agreed upon, ready for implementation

---

## Overview

Extend the tool-calling agentic flow (`bot_tools.py` / `claude_agent_tools.py` / `system_prompt_tools.py` / `mcp_sheets_server.py`) so the agent can answer historical detail questions about past expenses and income, not just the current calendar month's budget status — e.g. "¿qué gastos tuve el 8 de agosto?" or "¿cuáles fueron mis ingresos en los últimos dos meses?"

This introduces a second read-only MCP tool, `get_historical_entries`, alongside the existing `get_budget_status`. It lives in `mcp_sheets_server.py`, reuses the same `SheetsReader` and `sheet_naming.py` helpers, and runs in the same stdio subprocess already wired up via `McpBudgetClient` — no new server process.

**Out of scope for this story:** aggregation. This tool returns raw rows only; it does not compute sums, totals, or extremes ("¿cuál fue el día que más gasté?"). That is intentionally deferred to a future story once a precomputed aggregation tool exists (see [Deferred: Aggregation Queries](#deferred-aggregation-queries) below) — the LLM must not attempt to sum or rank rows itself in the meantime, per this project's existing principle (see `get_budget_status`) that the LLM composes prose, never arithmetic.

---

## Scope

- Arbitrary date ranges, day-precision, potentially spanning multiple month-sheets (data is stored one sheet per calendar month).
- Covers **both** expenses and income, via a `types` filter — data lives in separate sheets (`August/2026` vs `Ingresos - August/2026`) with different category vocabularies, so results are returned as two separate arrays, never merged.
- No default range: if the user doesn't state a period, the agent asks a clarifying question rather than assuming "this month" or "all time."
- Capped at 12 months per query, to keep tool-result size and Sheets-read cost bounded as history grows.

---

## `get_historical_entries` MCP Tool

### Input schema

```json
{
  "start_date": "2026-07-01",
  "end_date": "2026-08-31",
  "types": ["gasto", "ingreso"]
}
```

- `start_date`, `end_date` — `YYYY-MM-DD`, inclusive on both ends. The calling agent resolves any relative phrasing ("los últimos dos meses", "el 8 de agosto") into concrete dates itself before calling, same as it already does for `save_entries`' `date` field.
- `types` — **required**, non-empty subset of `["gasto", "ingreso"]`. No default; the agent must explicitly decide scope from the question's wording (e.g. "gastos" → `["gasto"]`, "ingresos" → `["ingreso"]`, "movimientos"/"transacciones" → both).

### Output schema (success)

```json
{
  "start_date": "2026-07-01",
  "end_date": "2026-08-31",
  "requested_types": ["gasto", "ingreso"],
  "months_missing": ["Ingresos - August/2026"],
  "expenses": [
    {"date": "2026-08-08", "category": "Alimentación", "description": "Almuerzo", "amount": 25000, "notes": ""}
  ],
  "income": [
    {"date": "2026-07-15", "category": "Salario", "description": "Salario de julio", "amount": 3000000, "notes": ""}
  ]
}
```

- `expenses` / `income` — omit the array key's corresponding rows entirely (return `[]`) for any type not present in `requested_types`; never fabricate or infer rows for an unrequested type.
- `months_missing` — sheet names (not calendar months) with no sheet found at all, e.g. `"Ingresos - August/2026"`. Distinct from a sheet that exists but has zero matching rows in range — that case contributes no rows but is *not* listed here. This lets the agent tell the user "no tengo datos de agosto" honestly instead of silently implying "$0 gastado."

### Output schema (validation error)

Returned as a normal JSON tool result (never an MCP-level exception), same pattern as the existing `{"error": ...}` fallback in `claude_agent_tools.py`'s `_get_budget_summary` for a missing `mcp_client`:

```json
{"error": "invalid_range", "message": "start_date must be on or before end_date"}
```

```json
{"error": "range_too_large", "max_months": 12}
```

Validation checks, in order:
1. `start_date` and `end_date` are both parseable `YYYY-MM-DD`.
2. `start_date <= end_date`.
3. The inclusive range spans at most 12 distinct calendar months.

### Implementation notes

- Extract a pure function (mirroring `aggregate_budget_status`'s existing pattern) that resolves `(start_date, end_date, types)` into: the list of `(month, year)` pairs touched, the corresponding sheet names via `sheet_naming.py`, and either `None` or one of the validation errors above. Unit-test it directly (single-day range, a range spanning a Dec→Jan year boundary, exactly-12-months, 13-months rejection, `start_date > end_date`) without needing live Sheets or MCP transport.
- The `@server.tool()` wrapper (`get_historical_entries`) stays thin: call the pure resolver, read each resolved sheet via `SheetsReader.read_sheet_rows` (already returns `None` for a missing sheet), filter each sheet's rows to those whose `Fecha` falls within `[start_date, end_date]`, and assemble the response.
- Row field mapping from raw Sheets columns: `Fecha` → `date`, `Categoría` → `category`, `Descripción` → `description`, `Monto (COP)` → `amount`, `Notas` → `notes`.

---

## `ToolCallingExpenseAgent` / `claude_agent_tools.py` Changes

- New tool schema, `GET_HISTORICAL_ENTRIES_TOOL`, added to `TOOLS`:
  - `name: "get_historical_entries"`
  - `input_schema` requires `start_date`, `end_date`, `types` (array, enum `["gasto", "ingreso"]`, `minItems: 1`).
- New `AgentTurnResult.kind`, e.g. `"history"`, alongside `"saved" | "clarification" | "off_topic" | "error" | "summary"`.
- New handler method, e.g. `_get_historical_entries`, mirroring `_get_budget_summary`'s shape: call `self.mcp_client.get_historical_entries(...)` (or the same "service unavailable" `{"error": ...}` fallback when `mcp_client is None`), feed the JSON result back as a `tool_result`, and let Claude compose the final Spanish prose from it in a second turn.

## `McpBudgetClient` / `mcp_budget_client.py` Changes

- New method:
  ```python
  def get_historical_entries(self, start_date: str, end_date: str, types: list[str]) -> dict:
      future = asyncio.run_coroutine_threadsafe(
          self._session.call_tool(
              "get_historical_entries",
              {"start_date": start_date, "end_date": end_date, "types": types},
          ),
          self._loop,
      )
      result = future.result()
      return json.loads(result.content[0].text)
  ```

---

## `system_prompt_tools.py` Changes

New section, alongside the existing "Budget Queries vs. New Entries" section, covering:

1. **When to call `get_historical_entries`:** the user is asking to see/list past expenses or income for a stated period (a specific day, a named month, a relative range like "los últimos dos meses") — as opposed to `get_budget_summary` (current-month budget-vs-spend status) or `save_entries` (a new entry to log).
2. **No default period — always clarify:** if the question doesn't state or imply a period at all (e.g. a bare "¿qué gasté?"), call `ask_clarification` asking for the period rather than assuming a range. Reuses the existing `ask_clarification` tool and its `pending_tool_use_id` follow-up mechanism — no new clarification plumbing needed.
3. **Resolving `types`:** map "gastos" → `["gasto"]`, "ingresos" → `["ingreso"]`, "movimientos"/"transacciones"/no explicit type stated but clearly about both → `["gasto", "ingreso"]`.
4. **Resolving `start_date` / `end_date`:** same relative-date parsing rules already documented for `save_entries`' `date` field (specific dates, "hace N días", month names, etc.), applied to compute a concrete range instead of a single date. Today's date is available the same way (`__TODAY__`).
5. **Composing the response from a successful result:** list the returned `expenses`/`income` rows in Spanish prose (grouped by type if both are present), and explicitly mention any `months_missing` sheet so the user knows which part of their question has no data rather than reading silence as "$0". Never compute a sum, total, count-based ranking, or "the day you spent most" from the returned rows — if the numbers need to be combined that way, that's an aggregation query (see below).
6. **Declining aggregation/extremum questions:** if the user asks a ranking/max/sum-style question ("¿cuál fue el día que más gasté?", "¿cuánto gasté en total en julio?"), the agent must say this isn't supported yet (e.g. "Por ahora puedo mostrarte los gastos de un período, pero no puedo calcular el día de mayor gasto todavía") rather than calling `get_historical_entries` and estimating an answer from raw rows itself.
7. **Validation-error results:** compose a Spanish message asking the user to narrow the range when the tool returns `{"error": "range_too_large", ...}`, or to check the dates when it returns `{"error": "invalid_range", ...}`.

---

## Deferred: Aggregation Queries

A future story will add a precomputed aggregation tool (e.g. `get_spending_aggregate`) that returns server-side sums/totals/per-day breakdowns for ranking-style questions ("¿cuál fue el día que más gasté?", "¿cuánto gasté en total el trimestre pasado?"), following the same "LLM never does the arithmetic" principle `get_budget_status` already establishes. Until that ships, `get_historical_entries` intentionally does not attempt to answer those questions (see point 6 above).
