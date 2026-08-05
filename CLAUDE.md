# CLAUDE.md

## What This Project Is

A Telegram bot that lets a user log expenses in natural language (in Spanish) and have them automatically categorized and appended to a Google Sheet via a Claude agent. Currency is fixed to Colombian Pesos (COP); all user-facing responses are in Spanish.

## Planned Architecture

```
User (Telegram) → Telegram Bot → C# API Endpoint → Claude Agent → Google Sheets (via MCP)
```

- **Telegram Bot** — C# using the `Telegram.Bot` library. Listens for messages, forwards expense text to the API, and relays the confirmation/error back to the user.
- **C# API** — ASP.NET Core (.NET 10). Single primary endpoint `POST /api/expenses` accepting `{ telegramUserId, expenseText }`. Calls the Claude API (Anthropic SDK for C#) with the expense text and the categorization system prompt, and returns the result to the bot.
- **Claude Agent** — Receives the raw expense text plus a system prompt encoding the categorization rules, extracts structured fields (amount, description, category, date), and calls the Google Sheets MCP tool to append a row. It also composes the user-facing confirmation message.
- **Google Sheets (via MCP)** — Persistence layer. No manual API key/credential handling — auth is OAuth2, managed by the MCP connector configured in Claude.ai settings. The agent appends rows to a sheet with columns: `Fecha | Categoría | Descripción | Monto (COP) | Notas`.

Because the domain logic (categorization, parsing, desglose of multi-item messages) lives in the Claude agent's system prompt rather than in C# code, most "business logic" changes for this project mean editing the agent's system prompt, not application code. See the full prompt template in [expense_tracker_plan.md](expense_tracker_plan.md) under "Agent System Prompt Template".

### Categorization rules

Fixed category set: `Alimentación`, `Transporte`, `Trabajo`, `Entretenimiento`, `Salud`, `Servicios`, `Otros` (default fallback). Keyword-driven categorization rules and worked examples are documented in the plan — keep the system prompt and the plan's rules table in sync if either changes.

### Key behavioral rules to preserve

- If a single message describes multiple items, the agent should attempt to desglose (split) them into separate rows rather than merging into one expense.
- If the amount is ambiguous, the agent should ask for clarification rather than guessing.
- If the category is unclear, default to `Otros` with a descriptive text rather than forcing a bad match.
- Default to today's date when no date is specified; always format as `YYYY-MM-DD`.
- All amounts are COP; never assume another currency.
- Confirmation responses to the user follow the fixed format: `"✅ Gasto guardado: [Categoría] - $[Monto] COP - [Descripción]"`.

## Security Notes (from plan)

- Telegram bot token and Claude API key belong in environment variables (`.env`), never committed.
- Google Sheets auth is handled entirely by the MCP OAuth2 flow — do not add manual credential/service-account handling for Sheets.
- The API endpoint should validate the Telegram user ID and consider rate limiting, since it's an inbound webhook-style surface.
