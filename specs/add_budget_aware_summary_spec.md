# Add Budget-Aware Spending Summary (Spec)

**Date:** 2026-08-13
**Status:** Agreed upon, ready for implementation

---

## Overview

Today the bot is write-only: users log gastos/ingresos and the bot appends rows to Google Sheets, but nothing ever reads that data back. This spec adds a **read-and-reason feature**: the user can ask, in natural language, how they're doing against their monthly budget (e.g. *"¿cómo voy con el presupuesto?"*, *"¿en qué estoy gastando de más?"*), and the bot responds with a category-by-category breakdown, flags for over/near-budget categories, and Claude-composed advice.

This is a genuine new capability, not a refinement of the existing write path — it introduces the project's first read access to Sheets, and its first use of MCP (Model Context Protocol), used specifically to demonstrate a real MCP server/client boundary rather than to solve a gap the direct `gspread` approach couldn't handle.

**Builds on `feature/add-tool-calling-agentic-approach`'s work (now merged to `main`).** This feature lands **only** on the tool-calling agent (`bot_tools.py` / `claude_agent_tools.py` / `system_prompt_tools.py`). The original NDJSON-based flow (`bot.py` / `claude_agent.py` / `system_prompt.py`) is left completely untouched — not extended, not retired. It continues to exist as a separate, simpler flow.

---

## Goals / Non-Goals

**Goals:**
- Let the user ask about their current-month budget status in natural language, with no new command required — consistent with this project's existing "no separate command flow" philosophy.
- Report spend per category, contrasted against a user-maintained budget, with deterministic over/near-limit flags.
- Have Claude turn those (already-correct) numbers into natural-language advice in Spanish — not compute the numbers itself.
- Introduce a real, self-hosted MCP server as the mechanism for reading Sheets data, run as a persistent subprocess of the bot.
- Report total income for the month as informational context alongside the budget breakdown.

**Non-Goals:**
- No historical/past-month queries (e.g. "¿cómo me fue en julio?") — current month only. Historical support is an explicit follow-up story.
- No netting income against the budget, no cash-flow modeling — income is reported, not used in the budget math.
- No changes to how expenses/income are *written* — `sheets_writer.py` and its `gspread` + service-account approach are unchanged. MCP is used for reads only.
- No changes to `bot.py` / `claude_agent.py` / `system_prompt.py`.
- No retiring or deprecating the NDJSON flow.
- No auto-estimation of budget values — the user maintains the `Presupuesto` tab by hand, same as they already do for corrections in the expense/income tabs.

---

## Data Model: the `Presupuesto` Tab

A single **evergreen** tab named `Presupuesto` in the same spreadsheet — not a monthly tab like `August/2026`. A budget is a standing target, not a dated event; making it monthly would require the user to remember to copy it forward every month, and a missing tab would silently make every category look unbudgeted.

Columns:

| Categoría | Monto Presupuestado (COP) |
|---|---|
| Alimentación | 600000 |
| Transporte | 200000 |
| Entretenimiento | 150000 |

Rules:
- One row per category the user wants to track a limit for. Categories are free-form text but should match the fixed expense category set (`Alimentación`, `Transporte`, `Trabajo`, `Entretenimiento`, `Salud`, `Servicios`, `Otros`) for the comparison to line up — mismatches simply won't match any actual spending category.
- **No total row.** The total budget is always derived as the sum of the category rows currently present. Two independently-maintained numbers (categories + a hand-entered total) can drift out of sync — exactly the kind of silent money error this spec avoids elsewhere by keeping math in Python instead of the LLM.
- A category with real spending but no row in `Presupuesto` is not an error — it's reported as spent-with-no-limit (see Aggregation Logic below). The tab is opt-in per category.
- If the `Presupuesto` tab doesn't exist at all, budget comparison is skipped entirely; the summary still reports raw spend per category and tells the user (via Claude, per a fact the tool result surfaces) that no budget is configured yet.

---

## Architecture

```
User (Telegram, NL) → bot_tools.py → ToolCallingExpenseAgent (claude_agent_tools.py)
                                            │
                                            ├─ save_entries / ask_clarification / flag_off_topic
                                            │     → sheets_writer.py (gspread, Service Account) [UNCHANGED]
                                            │
                                            └─ get_budget_summary (NEW)
                                                  → MCP client → mcp_sheets_server.py (NEW, subprocess, stdio)
                                                        → gspread (same Service Account credentials)
                                                        → Presupuesto / current month's expense & income tabs
```

- **`mcp_sheets_server.py`** (new) — a self-hosted MCP server, run as a **local stdio subprocess**, wrapping the *same* Service Account credentials `sheets_writer.py` already uses (`GOOGLE_SERVICE_ACCOUNT_PATH`, `GOOGLE_SHEETS_ID`). It exposes one MCP tool, `get_budget_status`, which reads the `Presupuesto` tab plus the current month's expense/income tabs and returns **precomputed aggregates** (see below).
- Deliberately **not** the public/official Google Sheets MCP connector: that requires an OAuth2 user-consent flow, which doesn't fit a bot that runs unattended with no browser session to click "Allow." Self-hosting means auth stays exactly as it is today.
- **Lifecycle:** the MCP server subprocess is spawned once when `bot_tools.py`'s `main()` starts, and the MCP client connection is held for the bot's entire lifetime — mirroring how `SheetsWriter` is already constructed once and passed into `ToolCallingExpenseBot`. Do not spawn a fresh subprocess per query; startup (subprocess spawn + service-account auth) is too slow to pay on every user message.
- The MCP client belongs to `ToolCallingExpenseAgent` (constructor-injected, like `sheets_writer` is today), not to `bot_tools.py` directly — `bot_tools.py` only owns starting/stopping the subprocess and wiring the client into the agent.

---

## Tools

### MCP server tool (called by the app, not directly by Claude)

**`get_budget_status`** — no arguments; always resolves to the current calendar month/year.

Returns:
```json
{
  "month": "August",
  "year": 2026,
  "budget_configured": true,
  "categories": [
    {"category": "Alimentación", "spent": 480000, "budgeted": 600000, "pct_used": 80.0, "status": "near_limit"},
    {"category": "Transporte", "spent": 220000, "budgeted": 200000, "pct_used": 110.0, "status": "over_budget"},
    {"category": "Salud", "spent": 30000, "budgeted": null, "pct_used": null, "status": "sin_presupuesto"}
  ],
  "total_spent": 730000,
  "total_budget": 800000,
  "total_pct_used": 91.25,
  "total_status": "near_limit",
  "total_income": 3000000
}
```

### Anthropic tool (Claude-facing, added to `claude_agent_tools.py`'s `TOOLS` list)

**`get_budget_summary`** — no arguments. Description instructs Claude to call this when the user is asking about their spending/budget status rather than logging a new gasto/ingreso (e.g. "¿cómo voy?", "¿en qué me estoy pasando?", "cuánto llevo gastado"), as opposed to a plain statement of a new expense/income.

Dispatch, mirroring `save_entries`'s existing two-turn pattern:
1. Claude calls `get_budget_summary`.
2. The app calls the MCP client's `get_budget_status` tool and gets back the aggregate JSON above.
3. The app sends that JSON back to Claude as the `tool_result`.
4. Claude's second turn composes the actual Spanish response: the breakdown, flags, and advice. This is the only place Claude does any reasoning about the numbers — never the arithmetic itself.

This adds a 4th branch to the existing `handle_message` dispatch in `claude_agent_tools.py` (alongside `save_entries` / `ask_clarification` / `flag_off_topic`), returning a new `AgentTurnResult.kind == "summary"` (or reuse `"saved"` if no bot-side behavior differs — decide during implementation; functionally it's just "relay `text`, don't keep pending clarification state").

---

## Aggregation Logic (deterministic, lives in `mcp_sheets_server.py`)

- **Thresholds:** `over_budget` at `pct_used >= 100`, `near_limit` at `pct_used >= 80`, else `ok`. A category with spending but no `Presupuesto` row is `sin_presupuesto` — reported with its spent amount, `budgeted: null`, `pct_used: null`, never counted as over/under anything.
- **Total budget** = sum of budgeted amounts across categories that *have* a `Presupuesto` row. Categories without one don't contribute to `total_budget` or `total_pct_used`, but their `spent` amount still counts toward... **decide explicitly during implementation**: total_spent includes *all* spending (budgeted or not), since it's a factual total; `total_pct_used` is `total_spent / total_budget` using only the budgeted categories' spend in the denominator's intent but the actual numerator convention (all spend vs. only-budgeted spend) must be picked and documented in code — recommend using **all spend** in `total_spent` for factual accuracy, so `total_pct_used` can exceed the sum of individual categories' contributions if unbudgeted categories are large. This should be called out plainly in the confirmation text logic/prompt so it isn't misleading.
- **Income:** `total_income` = sum of the current month's `Ingresos - <Month>/<Year>` tab, reported as-is, never subtracted from spend or compared to budget.
- **Missing tabs:** if the current month's expense tab doesn't exist yet, treat as zero spend (not an error). If `Presupuesto` doesn't exist at all, set `budget_configured: false`, `categories` reflects only actual spend with every entry `sin_presupuesto`, and `total_budget`/`total_pct_used`/`total_status` are `null`.
- **Reuse, don't duplicate, month/sheet-name resolution.** `sheets_writer.py` already has `MONTH_NAMES` and `_get_sheet_name`/prefix logic for routing to `August/2026` vs `Ingresos - August/2026`. Extract that into a small shared pure function (e.g. in `sheets_writer.py` or a new `sheet_naming.py`) that both `sheets_writer.py` and `mcp_sheets_server.py` import, rather than re-implementing the month-name table in the new server.

---

## System Prompt Changes (`system_prompt_tools.py`)

- Add instructions for when to call `get_budget_summary` vs. `save_entries` vs `ask_clarification`: a message asking about spending status, budget, or "how am I doing" is a query, not a new entry to log — never call `save_entries` for it, and don't ask a clarifying question about amount/date for a query.
- Add instructions for composing the response from the `get_budget_status` result:
  - Lead with the categories that are `over_budget`, then `near_limit`, before unremarkable `ok` ones.
  - State the overall `total_pct_used` plainly.
  - Mention `total_income` as brief context, not as an offset against the budget.
  - If `budget_configured` is `false`, tell the user no budget is set up yet and that they can add rows to the `Presupuesto` tab, rather than fabricating advice with no baseline.
  - Never recompute or "correct" any number from the tool result — treat every number in it as ground truth.

---

## File / Module Layout

New/changed files, all scoped to the tool-calling flow:

- `mcp_sheets_server.py` (new) — the MCP server: connects to Sheets via the existing Service Account credentials, exposes `get_budget_status`, contains the aggregation logic described above.
- `claude_agent_tools.py` (modified) — add `GET_BUDGET_SUMMARY_TOOL` to `TOOLS`, add the MCP client as a constructor dependency of `ToolCallingExpenseAgent`, add the dispatch branch and its (single, no-second-Sheets-write) tool-result round trip.
- `system_prompt_tools.py` (modified) — prompt additions described above.
- `bot_tools.py` (modified) — `main()` spawns the `mcp_sheets_server.py` subprocess and establishes the MCP client connection once at startup, passes it into `ToolCallingExpenseAgent`, and ensures clean shutdown of the subprocess when the bot stops.
- `sheets_writer.py` (small refactor) — extract the shared month/sheet-name-resolution helper so `mcp_sheets_server.py` can reuse it instead of duplicating `MONTH_NAMES`.
- `requirements.txt` (modified) — add the official `mcp` Python SDK package.
- `.env.example` (modified) — document that `GOOGLE_SERVICE_ACCOUNT_PATH`/`GOOGLE_SHEETS_ID` are now also consumed by the MCP server subprocess (no new env vars needed — same credentials, same spreadsheet).
- `CLAUDE.md` / `specs/` — after implementation, update `CLAUDE.md`'s architecture section to mention the MCP read path, and update `README.md`'s "possible future work" list to remove "budget alerts per category" now that it's built.

Untouched: `bot.py`, `claude_agent.py`, `system_prompt.py`, `off_topic_responses.py`.

---

## Testing (TDD)

Mirrors this repo's existing mocking conventions (`test_claude_agent_tools.py`, `test_sheets_writer.py`):

- **Aggregation logic** (`mcp_sheets_server.py`): pure-function unit tests over synthetic Sheets rows — no live Sheets, no live MCP transport. Cover: all-categories-budgeted, some-categories-unbudgeted (`sin_presupuesto`), no `Presupuesto` tab at all (`budget_configured: false`), no expenses yet this month (zero spend, not an error), threshold boundaries (exactly 80%, exactly 100%), and total income reporting.
- **MCP tool wiring**: a test that the `get_budget_status` MCP tool correctly calls the aggregation function with data read from the (mocked) `gspread` client and returns the documented JSON shape.
- **`claude_agent_tools.py` dispatch**: given a mocked `tool_use` for `get_budget_summary`, the app calls the (mocked) MCP client, sends the right `tool_result`, and returns the composed second-turn text — same pattern as the existing `save_entries` two-turn test coverage.
- **Query vs. log disambiguation**: smoke-test-style cases (like the existing off-topic smoke tests in `claude_agent.py`'s `main()`) confirming budget-status questions route to `get_budget_summary` and don't get misrouted to `save_entries` or `ask_clarification`.
- **Subprocess lifecycle**: a test that `bot_tools.py`'s startup/shutdown correctly spawns/tears down the MCP server subprocess (can be a lighter-weight integration-style test, clearly separated from the unit tests per `CODING_STANDARDS.md` §5).

---

## Follow-Up / Explicitly Out of Scope

- **Historical months** (e.g. "¿cómo me fue en julio?") — separate story; would need the MCP tool to accept a month/year argument and resolve arbitrary past sheets.
- **Reliability hooks on the numeric pipeline** — raised during design as worth exploring later: e.g. schema-validating the MCP tool's output (so a malformed aggregate can never reach Claude silently), or golden-file tests that pin the aggregation function's output for fixed inputs to catch future regressions in the math. Not required for v1, worth a dedicated follow-up.
- **Retiring `bot.py`/`claude_agent.py`** — explicitly deferred; both flows continue to coexist.
- **Netting income against budget / cash-flow modeling** — a materially different feature from "did I stay within planned spending," left for a future spec if wanted.
- **Multi-user support, budget change history, category renaming/aliasing** — none of these are needed for a single-user `Presupuesto` tab and are out of scope.
