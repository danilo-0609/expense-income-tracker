# Income Tracker Design Plan

**Date:** 2026-08-09
**Status:** Agreed upon, ready for implementation

---

## Overview

Extend the existing Telegram expense bot so it can also log income (salary, yield from a yield-bearing deposit account, etc.). Income shares the bot's natural-language, Spanish-language, Claude-parsed pipeline, but is stored separately from expenses and uses its own category set.

**Currency:** Colombian Pesos (COP), same as expenses.

---

## Scope

- This feature logs income **events** only — it does not compute or project yield.
- The yield-bearing deposit account earns interest automatically and there is no API or clean way to pull that data programmatically.
- Yield accrual is tracked the same way any other income is: the user manually sends a message when they check their balance and want to record the interest earned (e.g., "Rendimientos de la cuenta, 12000"), and it's logged as an income row with category `Rendimientos`.
- No automatic balance tracking, no daily/weekly accrual computation, no principal-vs-yield reconciliation.

---

## Income Categories (Fixed)

| Category | Examples |
|----------|----------|
| **Salario** | Monthly/biweekly salary payments |
| **Rendimientos** | Yield/interest from the deposit account (manually logged) |
| **Otros ingresos** | Freelance income, gifts, refunds, everything else |

---

## Intent Detection: Income vs. Expense

A single unified Claude system prompt (one API call per message) determines the type of movement and extracts fields accordingly — no separate classification call, no bot command/prefix required.

- The response JSON includes a `"type"` field: `"gasto"` or `"ingreso"`.
- Expense messages use the existing expense category set; income messages use the income category set above.
- If the message is genuinely ambiguous (Claude cannot tell if it's income or an expense), return a clarification error instead of guessing:
  ```json
  {"error": true, "message": "¿Este movimiento es un ingreso o un gasto?"}
  ```
  This follows the same multi-turn clarification pattern already used for missing amounts (the bot appends the question to conversation history and resolves the next message in context).

---

## Parsing Rules for Income

Mirrors the expense parsing rules:

1. **Amount (Mandatory):** Always required — never save income without it. If missing/unclear, return a clarification error: `{"error": true, "message": "¿Cuál fue el monto del ingreso?"}`
2. **Date (Optional):** Same parsing rules as expenses (relative dates, month names, specific dates). Defaults to today if not provided. Always `YYYY-MM-DD`.
3. **Category (Intelligent matching):** Match to `Salario` / `Rendimientos` / `Otros ingresos`. Default to `Otros ingresos` with a note if unclear.
4. **Description (Required):** Concise summary of the income source.
5. **Notes (Optional):** Same as expenses — document any assumption or ambiguity.

### Multiple Items in One Message

Same as expenses: if a single message describes multiple income items with clear amounts (e.g., "Salario 3000000, bono 200000"), split into multiple income rows using newline-delimited JSON (one object per line). If ambiguous, add a note and ask for clarification.

---

## JSON Response Schema

Both expense and income responses share the same shape, extended with a `"type"` field so the caller can dispatch without inferring type from which keys are present.

### Income success:
```json
{
  "type": "ingreso",
  "category": "Salario",
  "amount": 3000000,
  "description": "Salario de agosto",
  "date": "2026-08-09",
  "notes": "",
  "confirmation": "✅ Ingreso guardado: Salario - $3,000,000 COP - Salario de agosto"
}
```

### Expense success (existing schema, now with `"type"` added):
```json
{
  "type": "gasto",
  "category": "Alimentación",
  "amount": 25000,
  "description": "Almuerzo en Starbucks",
  "date": "2026-07-25",
  "notes": "",
  "confirmation": "✅ Gasto guardado: Alimentación - $25,000 COP - Almuerzo en Starbucks"
}
```

### Error / clarification (shared shape, unchanged):
```json
{"error": true, "message": "¿Cuál fue el monto del ingreso?"}
```

## Confirmation Message Format

Mirrors the expense format exactly, swapping "Gasto" for "Ingreso":

```
✅ Ingreso guardado: [Categoría] - $[Monto con formato de miles] COP - [Descripción]
```

Examples:
- `✅ Ingreso guardado: Salario - $3,000,000 COP - Salario de agosto`
- `✅ Ingreso guardado: Rendimientos - $12,000 COP - Rendimientos cuenta de ahorros`
- `✅ Ingreso guardado: Otros ingresos - $150,000 COP - Reembolso de un amigo`

---

## Google Sheets Storage

- **Separate sheets per type, same spreadsheet.** Income does not share a sheet/tab with expenses.
- **Sheet naming:** `"Ingresos - <Month>/<Year>"` (e.g., `"Ingresos - August/2026"`), following the existing `"<Month>/<Year>"` convention used for expense sheets.
- **Columns (identical shape to expenses):** `Fecha | Categoría | Descripción | Monto (COP) | Notas`

---

## Code Changes

### `system_prompt.py`
- Extend the single system prompt with:
  - Income category list and keyword/matching guidance.
  - Intent-classification instructions (decide `gasto` vs `ingreso` before extracting fields).
  - Updated response format examples showing the `"type"` field for both success cases.
  - Updated error example for ambiguous intent.

### `claude_agent.py`
- `ExpenseAgent.parse_expense` continues to return a list of structured dicts (now including `"type"`) plus the raw response text — no interface change needed since dispatch happens downstream based on `"type"`.

### `sheets_writer.py`
- Extend `SheetsWriter` (not a separate class) to parameterize sheet-name prefix based on `type`:
  - `type == "gasto"` → existing `"<Month>/<Year>"` naming, unchanged.
  - `type == "ingreso"` → `"Ingresos - <Month>/<Year>"` naming.
- Reuses the same spreadsheet connection and `sheet_cache`.
- `write_expense`/`write_expenses` dispatch on the `"type"` field of each item to pick the sheet-name prefix; row shape stays the same for both.

### `bot.py`
- No new commands or message routing needed at the bot layer — every message still goes through the same single Claude call. The bot only needs to pass through whichever writer call `sheets_writer.py` exposes for dispatching by `type`.

---

## Key Behavioral Rules (Never Break These)

1. **Amount is mandatory** — Never save income without it. Always ask if missing.
2. **Currency is always COP** — Never assume another currency.
3. **All responses are in Spanish** — User-facing messages only in Spanish.
4. **Confirmation format is fixed** — Exactly as shown above, "Ingreso guardado" for income.
5. **Dates default to today** — Never leave date blank if not provided.
6. **Ambiguities are saved with notes** — Never silently guess category or intent; ask when intent (income vs. expense) is unclear, and document assumptions for category defaults.
7. **Income and expenses live in separate sheets** — Never mix the two category vocabularies in one `Categoría` column.
8. **No automatic yield computation** — Yield/interest is only ever logged when the user manually reports it as a `Rendimientos` income entry.
