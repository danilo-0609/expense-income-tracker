# Expense Tracker Bot

A Telegram bot that automatically logs expenses **and income** to a Google Sheet using Claude AI for intelligent categorization.

**Features:**
- 📱 Log expenses or income via Telegram in natural language (Spanish) — Claude decides which one each message is
- 🤖 Claude AI automatically categorizes and parses expenses and income
- 💬 Asks follow-up questions when info is missing (including whether a message is an expense or income), and remembers your answers (multi-turn clarification)
- 📊 Saves directly to Google Sheets, organized into one tab per month (e.g. `August/2026` for expenses, `Ingresos - August/2026` for income)
- 💾 No database needed — uses Google Sheets as storage
- 🔄 Polling-based bot (no webhooks required)

---

## Quick Start

### 1. Prerequisites

- Python 3.9+
- Telegram account
- Google Cloud project
- Claude API key (from Anthropic)

### 2. Installation

```bash
# Clone or download this project
cd expense-tracker

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env
```

### 3. Setup Telegram Bot

1. Open Telegram and message [@BotFather](https://t.me/botfather)
2. Use `/newbot` command to create a new bot
3. Copy the bot token (looks like `123456789:ABCdefGHIJKlmnoPQRstUVwxyzABC`)
4. Add to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=your_token_here
   ```

### 4. Setup Claude API

1. Get your API key from [console.anthropic.com](https://console.anthropic.com/)
2. Add to `.env`:
   ```
   CLAUDE_API_KEY=your_key_here
   ```

### 5. Setup Google Sheets (Optional for Phase 1)

Skip this for now if you want to test the bot without Sheets integration.

**To enable Sheets integration:**

1. Create a new Google Sheet. Expense and income rows use the same column shape: `Fecha | Categoría | Descripción | Monto (COP) | Notas`. Monthly tabs are created automatically — expenses in `<Month>/<Year>` (e.g. `August/2026`), income in `Ingresos - <Month>/<Year>` (e.g. `Ingresos - August/2026`).
2. Create a Google Cloud project:
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project
   - Enable "Google Sheets API"
3. Create a Service Account:
   - In Google Cloud Console: APIs & Services → Credentials → Create Credentials → Service Account
   - Download the JSON key file
   - Save as `service_account.json` in this project folder
   - Copy the service account email
4. Share the Google Sheet with the service account email (give it Editor access)
5. Add to `.env`:
   ```
   GOOGLE_SHEETS_ID=your_sheet_id_here
   GOOGLE_SERVICE_ACCOUNT_PATH=./service_account.json
   ```

---

## Usage

### Phase 1: Test Claude Parsing (No Sheets)

Test that Claude correctly parses expenses:

```bash
python claude_agent.py
```

This will run test cases and show Claude's responses.

### Phase 2: Run the Telegram Bot

With Telegram bot token and Claude API key:

```bash
python main.py
```

The bot will start polling for messages. Send it expense or income entries like:
- `"Almuerzo en Starbucks, 25000"`
- `"Uber al trabajo, 28500 ayer"`
- `"Gasté 80000 en gasolina hace 2 días"`
- `"Me pagaron el salario, 3000000"`
- `"Rendimientos de la cuenta, 12000"`

### Phase 3: Test Sheets Integration (Optional)

With Google Sheets configured:

```bash
python sheets_writer.py
```

This will test writing a sample expense to your sheet.

---

## File Structure

```
expense-tracker/
├── main.py                          # Entry point
├── bot.py                           # Telegram bot logic
├── claude_agent.py                  # Claude API integration
├── sheets_writer.py                 # Google Sheets integration
├── system_prompt.py                 # Claude system prompt
├── requirements.txt                 # Python dependencies
├── .env.example                     # Environment variables template
├── .env                             # Your actual environment variables (NEVER COMMIT)
├── service_account.json             # Google credentials (NEVER COMMIT)
├── specs/                           # Design plans (expense + income tracking)
└── README.md                        # This file
```

---

## Environment Variables

Required:
- `TELEGRAM_BOT_TOKEN` — Your Telegram bot token from BotFather
- `CLAUDE_API_KEY` — Your Claude API key from Anthropic

Optional (for Sheets integration):
- `GOOGLE_SHEETS_ID` — Your Google Sheet ID
- `GOOGLE_SERVICE_ACCOUNT_PATH` — Path to `service_account.json` (default: `./service_account.json`)

---

## How It Works

1. **User sends message to Telegram bot:**
   ```
   "Almuerzo en Starbucks, 25000 ayer"
   ```

2. **Bot forwards the conversation to Claude API:**
   - Full chat history so far (not just the latest message) + a single unified system prompt that handles both expenses and income

3. **Claude decides if it's an expense or income and responds with JSON**, including a `"type"` field (`"gasto"` or `"ingreso"`):
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
   Income entries look the same, with income categories and `"type": "ingreso"`:
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

4. **Bot writes to the correct monthly sheet tab based on `"type"`:**
   - Expense → `July/2026`: appends row `2026-07-25 | Alimentación | Almuerzo en Starbucks | 25000 | `
   - Income → `Ingresos - August/2026`: appends row `2026-08-09 | Salario | Salario de agosto | 3000000 | `

5. **Bot confirms to user:**
   ```
   ✅ Gasto guardado: Alimentación - $25,000 COP - Almuerzo en Starbucks
   ```

### Follow-up clarification (multi-turn)

If required info is missing, Claude asks for it instead of guessing, and the bot keeps the conversation's context so your reply is understood correctly:

```
User: "Refresco gimnasio"
Bot:  "¿Cuál fue el monto del gasto?"
User: "6000"
Bot:  "✅ Gasto guardado: Salud - $6,000 COP - Refresco gimnasio"
```

This also covers ambiguous intent — if Claude can't tell whether a message is an expense or income, it asks instead of guessing:

```
User: "Recibí 50000"
Bot:  "¿Este movimiento es un ingreso o un gasto?"
User: "Ingreso, me lo regalaron"
Bot:  "✅ Ingreso guardado: Otros ingresos - $50,000 COP - Regalo"
```

Once an entry is resolved (saved, or a hard error occurs), the bot forgets that thread — the next message you send starts a brand-new expense or income entry from scratch.

---

## Expense Format

### Simple Format
```
[Description], [Amount]
```
Examples:
- `"Almuerzo en Starbucks, 25000"`
- `"Café, 15000"`

### With Date
```
[Description], [Amount] [Date]
```
Examples:
- `"Almuerzo, 25000 ayer"` (yesterday)
- `"Gasolina, 80000 hace 2 días"` (2 days ago)
- `"Crema, 30000 el 24 de julio"` (specific date)

### Multiple Expenses
```
[Desc1], [Amount1], [Desc2], [Amount2]
```
Examples:
- `"Almuerzo 20000, Uber 15000"` (splits into 2 rows)

---

## Expense Categories

| Category | Examples |
|----------|----------|
| **Alimentación** | Restaurants, cafés, groceries |
| **Transporte** | Gas, Uber, bus, taxi, parking |
| **Trabajo** | Tools, software, books, materials |
| **Entretenimiento** | Movies, streaming, games, concerts |
| **Salud** | Pharmacy, doctor, gym, medicine |
| **Servicios** | Internet, electricity, phone, water |
| **Otros** | Everything else (fallback) |

---

## Income Format

Same format as expenses — Claude tells expenses and income apart from context, no special prefix or command needed.

### Simple Format
```
[Description], [Amount]
```
Examples:
- `"Me pagaron el salario, 3000000"`
- `"Rendimientos de la cuenta, 12000"`

### With Date
```
[Description], [Amount] [Date]
```
Examples:
- `"Recibí mi pago salarial el 1 de agosto, 3000000"`

### Multiple Income Entries
```
[Desc1], [Amount1], [Desc2], [Amount2]
```
Examples:
- `"Salario 3000000, bono 200000"` (splits into 2 rows)

Income logging is manual only — there's no automatic tracking of interest/yield accrual from a bank account. When you check your balance and want to record what you earned, just send it as a `Rendimientos` income entry (e.g. `"Rendimientos de la cuenta, 12000"`).

---

## Income Categories

| Category | Examples |
|----------|----------|
| **Salario** | Monthly/biweekly salary payments |
| **Rendimientos** | Yield/interest from a savings or deposit account (manually reported) |
| **Otros ingresos** | Freelance income, gifts, refunds, everything else (fallback) |

---

## Troubleshooting

### Bot doesn't respond
- Check `TELEGRAM_BOT_TOKEN` is correct
- Make sure bot is running: `python main.py`
- Check logs for errors

### Claude returns "error"
- Check `CLAUDE_API_KEY` is correct
- Verify message is in Spanish
- If it's a clarification question (e.g. "¿Cuál fue el monto del gasto?"), that's expected — just reply with the missing info and it'll complete the expense using the earlier context
- If it's "Error parsing response from Claude", check the bot's console logs — the raw Claude response is logged there for debugging

### Can't write to Sheets
- Verify `GOOGLE_SHEETS_ID` is correct
- Check service account email is shared to sheet (Editor access)
- Ensure `service_account.json` exists in project folder
- Check logs for authentication errors

### "Invalid JSON" errors
- Claude system prompt may have changed
- Try restarting bot: `python main.py`
- Check logs for exact error

---

## Security Notes

**NEVER COMMIT:**
- `.env` file (contains API keys)
- `service_account.json` (Google credentials)

These should be in `.gitignore`. Store them securely:
- Locally: Encrypted or environment variables
- Production: Azure Key Vault or environment variables

---

## Deployment

### Local Development
Run `python main.py` on your machine. Bot will poll Telegram continuously.

### Azure App Service (Production)
See `specs/expense_tracker_design_plan.md` for deployment instructions.

---

## Future Features

- Monthly expense/income summaries
- Budget alerts per category
- Recurring expense templates
- Export to PDF
- Analytics dashboard
- Multi-user support

---

## Development

### Test Claude parsing:
```bash
python claude_agent.py
```

### Test Sheets integration:
```bash
python sheets_writer.py
```

### Run bot in test mode (without Sheets):
```bash
python main.py
```
(Bot will still respond, but won't save to Sheets)

---

## References

- **Expense Design Plan:** See `specs/expense_tracker_design_plan.md`
- **Income Design Plan:** See `specs/income_tracker_design_plan.md`
- **Telegram Bot API:** [python-telegram-bot docs](https://python-telegram-bot.readthedocs.io/)
- **Claude API:** [Anthropic docs](https://docs.anthropic.com/)
- **Google Sheets API:** [Google docs](https://developers.google.com/sheets)
