# CLAUDE.md

## What This Project Is

A Telegram bot that lets a user log expenses **and income** in natural language (in Spanish) and have them automatically categorized and appended to a Google Sheet via a Claude agent. Currency is fixed to Colombian Pesos (COP); all user-facing responses are in Spanish. A single unified Claude call classifies each message as an expense (`gasto`) or income (`ingreso`) and extracts the right fields for whichever it is — there is no separate command or bot flow for income.

## Architecture

```
User (Telegram) → Python Telegram Bot (Polling) → Claude Agent (Anthropic SDK) → Google Sheets (gspread, Service Account)
```

- **Telegram Bot** (`bot.py`, `main.py`) — Python, using `python-telegram-bot`. Polls Telegram for messages (no public URL/webhook needed), maintains a per-chat conversation history for clarification follow-ups, forwards message text to the Claude agent, and relays the confirmation/error back to the user. No separate API layer — the bot talks to Claude and Sheets directly in-process.
- **Claude Agent** (`claude_agent.py`, `system_prompt.py`) — Calls the Anthropic API directly with the conversation history plus a single unified system prompt encoding both expense and income categorization rules. Decides each entry's `type` (`gasto` or `ingreso`), extracts structured fields (amount, description, category, date, notes), and returns NDJSON. It also composes the user-facing confirmation message. Off-topic input and prompt-injection attempts are flagged and short-circuited by the bot rather than saved.
- **Google Sheets** (`sheets_writer.py`) — Persistence layer via `gspread` using a Service Account JSON key (`GOOGLE_SERVICE_ACCOUNT_PATH`) — no MCP, no OAuth2 flow. `SheetsWriter` appends rows to a monthly sheet with columns: `Fecha | Categoría | Descripción | Monto (COP) | Notas`. Expenses and income live in **separate** monthly sheets (e.g. `August/2026` for expenses, `Ingresos - August/2026` for income) — never mixed into the same tab or `Categoría` column, since the two use different category vocabularies. Sheets are created on demand if they don't exist yet.

Because the domain logic (categorization, parsing, desglose of multi-item messages, expense-vs-income classification) lives in the Claude agent's system prompt rather than in application code, most "business logic" changes for this project mean editing `system_prompt.py`, not the bot/writer code. See the full prompt templates in [specs/expense_tracker_design_plan.md](specs/expense_tracker_design_plan.md) and [specs/income_tracker_design_plan.md](specs/income_tracker_design_plan.md).

### Categorization rules

**Expenses** (`type: gasto`) — fixed category set: `Alimentación`, `Transporte`, `Trabajo`, `Entretenimiento`, `Salud`, `Servicios`, `Otros` (default fallback).

**Income** (`type: ingreso`) — fixed category set: `Salario`, `Rendimientos` (yield/interest from a savings or deposit account), `Otros ingresos` (default fallback).

Keyword-driven categorization rules and worked examples are documented in the plans — keep the system prompt and the plans' rules tables in sync if either changes.

### Income tracking scope

Income logging only covers discrete income **events** the user reports (salary payments, refunds, etc.) — there is no automatic balance tracking or yield/interest computation. The user's savings sit in a yield-bearing deposit account that earns interest automatically with no API to read it; when they want to record interest earned, they manually send it as a `Rendimientos` income entry (e.g. "Rendimientos de la cuenta, 12000"). Never attempt to estimate, project, or auto-compute yield — only log it when the user explicitly states an amount.

### Key behavioral rules to preserve

- If a single message describes multiple items, the agent should attempt to desglose (split) them into separate rows rather than merging into one entry. This applies to both expenses and income, and a single message may contain both types.
- If the amount is ambiguous, the agent should ask for clarification rather than guessing. This is mandatory for both expenses and income — never save either without an amount.
- If the category is unclear, default to `Otros` (expenses) or `Otros ingresos` (income) with a descriptive note rather than forcing a bad match.
- If it's unclear whether a message is an expense or income, the agent should ask for clarification rather than guessing the type.
- Default to today's date when no date is specified; always format as `YYYY-MM-DD`.
- All amounts are COP; never assume another currency.
- Confirmation responses to the user follow a fixed format per type:
  - Expenses: `"✅ Gasto guardado: [Categoría] - $[Monto] COP - [Descripción]"`
  - Income: `"✅ Ingreso guardado: [Categoría] - $[Monto] COP - [Descripción]"`

## Security Notes

- Telegram bot token, Claude API key, and the Google Service Account JSON path belong in environment variables (`.env`), never committed.
- Google Sheets auth is a Service Account JSON key (`GOOGLE_SERVICE_ACCOUNT_PATH`), scoped to `spreadsheets` — no OAuth2/MCP flow, no manual token refresh needed.
- The bot polls Telegram rather than exposing a webhook endpoint, so there's no inbound HTTP surface to validate/rate-limit; input trust boundary is the message text itself (see off-topic/prompt-injection guardrail in `off_topic_responses.py`).
