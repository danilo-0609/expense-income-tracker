# Expense Tracker Design Plan

**Date:** 2026-07-26  
**Status:** Agreed upon, ready for implementation

---

## Overview

A personal expense tracker: user sends messages to a Telegram bot in natural language (Spanish), Claude AI intelligently categorizes and parses the expense, and the bot automatically saves it to a Google Sheet.

**Currency:** Colombian Pesos (COP)

---

## Final Architecture

```
User (Telegram)
    ↓
Python Telegram Bot (Polling)
    ├─ Call Claude API
    │
    ├─ Parse response (structured JSON)
    │
    └─ Write to Google Sheets (API direct)
         ↓
      Google Sheets Spreadsheet
```

### Why this design

- **No separate API layer** — Bot talks directly to Claude and Sheets; simpler to build and deploy.
- **Polling, not webhooks** — Bot periodically checks Telegram; no public URL required.
- **Direct Sheets API** — Service Account credentials; no MCP complexity.
- **Claude handles parsing** — All intelligence (categorization, date parsing, validation) lives in the Claude system prompt.
- **Notes for fixes** — Ambiguities are saved with explanatory notes; user fixes in spreadsheet later.

---

## Components

### 1. Python Telegram Bot
- **Responsibility:**
  - Poll Telegram for new messages
  - Forward expense text to Claude API
  - Parse Claude's response (JSON + confirmation)
  - Write structured expense to Google Sheets
  - Send confirmation back to user in Telegram
  
- **Tech:** Python, `python-telegram-bot` library
- **Deployment:** Azure App Service free tier (always-on)

### 2. Claude Agent
- **Responsibility:**
  - Parse natural language expense entry (Spanish)
  - Extract: amount, description, category, date
  - Validate data
  - Return structured JSON + confirmation message (Spanish)
  
- **Model:** Claude (latest available)
- **Integration:** Anthropic SDK for Python

### 3. Google Sheets
- **Columns:** `Fecha | Categoría | Descripción | Monto (COP) | Notas`
- **Auth:** Service Account (JSON key)
- **Integration:** Python `gspread` library
- **Access:** Bot appends new rows in real-time

---

## Data Flow

**User sends message:**
```
User → Telegram: "Almuerzo en Starbucks, 25000 ayer"
```

**Bot receives and processes:**
```
Bot polls Telegram
Bot calls Claude API with:
  - User message: "Almuerzo en Starbucks, 25000 ayer"
  - System prompt (categorization rules, date parsing rules, validation)

Claude responds:
{
  "category": "Alimentación",
  "amount": 25000,
  "description": "Almuerzo en Starbucks",
  "date": "2026-07-25",
  "notes": "",
  "confirmation": "✅ Gasto guardado: Alimentación - $25,000 COP - Almuerzo en Starbucks"
}

Bot parses JSON
Bot appends row to Google Sheets
Bot sends confirmation to user in Telegram
```

---

## Expense Categorization Rules

### Categories (Fixed for MVP)

| Category | Examples | Keywords |
|----------|----------|----------|
| **Alimentación** | Restaurant, café, groceries | "almuerzo", "cena", "café", "comida", "restaurante", "supermercado" |
| **Transporte** | Gas, Uber, bus, taxi, parking | "gasolina", "uber", "taxi", "bus", "transporte", "estacionamiento" |
| **Trabajo** | Tools, software, books, materials | "trabajo", "proyecto", "herramienta", "software", "cliente" |
| **Entretenimiento** | Movies, streaming, games, concerts | "cine", "netflix", "película", "juego", "concierto", "entretenimiento" |
| **Salud** | Pharmacy, doctor, gym, medicine | "farmacia", "doctor", "médico", "gym", "medicina", "salud" |
| **Servicios** | Internet, electricity, phone, water | "internet", "luz", "teléfono", "agua", "servicio" |
| **Otros** | Everything else | Default fallback |

### Parsing Rules

1. **Amount (Mandatory):**
   - Extract numeric value from message
   - If missing → Ask user for clarification in Telegram
   - Assume COP; never assume another currency

2. **Date (Optional):**
   - Parse date from message if provided (e.g., "29 de junio", "ayer", "hace 2 días")
   - If not provided → Use today's date
   - Always format as `YYYY-MM-DD`

3. **Category (Intelligent guess):**
   - Match keywords in message to categories
   - If unclear → Default to `Otros`
   - Add note explaining ambiguity

4. **Description (Required):**
   - Extract/summarize what was bought
   - Keep concise but descriptive

5. **Notes (Optional):**
   - Flag any uncertainties or assumptions
   - User can review and fix in spreadsheet
   - Example: "Categoría ambigua - revisar después"

### Special Cases

- **Multiple items in one message** (e.g., "Almuerzo 20000, Uber 15000"):
  - Attempt to split into separate expenses
  - Create multiple rows if amounts are clear
  - If ambiguous, add a note and ask user to clarify

- **Ambiguous category** (e.g., "Gasté en la tienda"):
  - Use `Otros` with note: "Categoría ambigua - especificar tipo de gasto"

- **Missing amount:**
  - **Cannot save** — Ask user: "¿Cuál fue el monto del gasto?"

- **No date provided:**
  - Use today's date automatically

---

## Google Sheets Setup

### Sheet Structure

```
Fecha          Categoría       Descripción              Monto (COP)   Notas
2026-07-25     Alimentación    Almuerzo en Starbucks    25000         
2026-07-26     Transporte      Uber al trabajo          28500         
2026-07-26     Salud           Crema para mi madre      30000         
```

### Service Account Auth

1. Create Google Cloud project
2. Enable Google Sheets API
3. Create Service Account → Download JSON key
4. Share spreadsheet with service account email
5. Store JSON key in `.env.json` (never commit)
6. Bot loads key and authenticates

---

## System Prompt Template

The Claude system prompt encodes the categorization rules, parsing logic, and validation. Key sections:

```markdown
# Expense Categorization Agent

You are a Spanish-language expense tracker assistant.

## Your Job
1. Read natural language expense entries in Spanish
2. Extract: amount, description, category, date
3. Validate data (amount is mandatory)
4. Return structured JSON + confirmation message

## Categories & Keywords
[Category table from above]

## Parsing Rules
[Rules from above]

## Response Format
Return JSON:
{
  "category": "string",
  "amount": number,
  "description": "string",
  "date": "YYYY-MM-DD",
  "notes": "string or empty",
  "confirmation": "✅ Gasto guardado: [Categoría] - $[Monto] COP - [Descripción]"
}

If amount is missing, respond with:
{
  "error": true,
  "message": "¿Cuál fue el monto del gasto?"
}

## Error Handling
- If amount missing → Ask for it
- If category unclear → Use "Otros" with note
- If multiple items → Try to split into separate expenses
- For any assumption → Add explanatory note
```

---

## Deployment

### Local Development
- Python 3.9+
- `python-telegram-bot`, `anthropic`, `gspread`, `google-auth` libraries
- `.env` file with:
  - `TELEGRAM_BOT_TOKEN`
  - `CLAUDE_API_KEY`
  - `GOOGLE_SHEETS_ID`
  - Path to `service_account.json`

### Production
- **Host:** Azure App Service (free tier)
- **Runtime:** Python 3.11+
- **Always-on:** Yes (required for polling bot)
- **Secrets:** Store in Azure Key Vault or App Service environment variables

---

## Implementation Phases

### Phase 1: Core Bot + Claude (No Sheets yet)
- [ ] Set up Python Telegram bot (polling)
- [ ] Define Claude system prompt
- [ ] Test parsing with sample messages
- [ ] Verify JSON responses

### Phase 2: Google Sheets Integration
- [ ] Create Google Sheet with columns
- [ ] Set up Service Account credentials
- [ ] Implement Sheets write logic in bot
- [ ] Test end-to-end: Telegram → Claude → Sheets

### Phase 3: Error Handling & Polish
- [ ] Handle missing amounts (ask in Telegram)
- [ ] Test date parsing edge cases
- [ ] Test multi-item splitting
- [ ] Verify notes are saved correctly

### Phase 4: Deployment
- [ ] Deploy bot to Azure App Service
- [ ] Test production flow
- [ ] Set up logging/monitoring
- [ ] Document setup for future reference

---

## Future Enhancements

- Multi-user support (track by Telegram user ID)
- Monthly summary reports
- Budget alerts per category
- Recurring expense templates
- Export to CSV/PDF
- Add/remove categories dynamically
- Analytics dashboard

---

## Key Behavioral Rules (Never Break These)

1. **Amount is mandatory** — Never save without it.
2. **All currency is COP** — Never assume another currency.
3. **All responses are in Spanish** — User-facing messages only in Spanish.
4. **Confirmation format is fixed** — Always `"✅ Gasto guardado: [Categoría] - $[Monto] COP - [Descripción]"`
5. **Dates default to today** — Never leave date blank if not provided.
6. **Ambiguities are saved with notes** — Never silently guess; document assumptions.
