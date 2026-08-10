# CLAUDE.md

## What This Project Is

A Telegram bot that lets a user log expenses **and income** in natural language (in Spanish) and have them automatically categorized and appended to a Google Sheet via a Claude agent. Currency is fixed to Colombian Pesos (COP); all user-facing responses are in Spanish. A single unified Claude call classifies each message as an expense (`gasto`) or income (`ingreso`) and extracts the right fields for whichever it is — there is no separate command or bot flow for income.

## Planned Architecture

```
User (Telegram) → Telegram Bot → C# API Endpoint → Claude Agent → Google Sheets (via MCP)
```

- **Telegram Bot** — C# using the `Telegram.Bot` library. Listens for messages, forwards expense text to the API, and relays the confirmation/error back to the user.
- **C# API** — ASP.NET Core (.NET 10). Single primary endpoint `POST /api/expenses` accepting `{ telegramUserId, expenseText }`. Calls the Claude API (Anthropic SDK for C#) with the expense text and the categorization system prompt, and returns the result to the bot.
- **Claude Agent** — Receives the raw message (expense or income) plus a single unified system prompt encoding both expense and income categorization rules, decides the entry's `type` (`gasto` or `ingreso`), extracts structured fields (amount, description, category, date), and calls the Google Sheets MCP tool to append a row to the sheet for that type. It also composes the user-facing confirmation message.
- **Google Sheets (via MCP)** — Persistence layer. No manual API key/credential handling — auth is OAuth2, managed by the MCP connector configured in Claude.ai settings. The agent appends rows to a monthly sheet with columns: `Fecha | Categoría | Descripción | Monto (COP) | Notas`. Expenses and income live in **separate** monthly sheets (e.g. `August/2026` for expenses, `Ingresos - August/2026` for income) — never mixed into the same tab or `Categoría` column, since the two use different category vocabularies.

Because the domain logic (categorization, parsing, desglose of multi-item messages, expense-vs-income classification) lives in the Claude agent's system prompt rather than in C# code, most "business logic" changes for this project mean editing the agent's system prompt, not application code. See the full prompt templates in [specs/expense_tracker_design_plan.md](specs/expense_tracker_design_plan.md) and [specs/income_tracker_design_plan.md](specs/income_tracker_design_plan.md).

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

## Security Notes (from plan)

- Telegram bot token and Claude API key belong in environment variables (`.env`), never committed.
- Google Sheets auth is handled entirely by the MCP OAuth2 flow — do not add manual credential/service-account handling for Sheets.
- The API endpoint should validate the Telegram user ID and consider rate limiting, since it's an inbound webhook-style surface.
