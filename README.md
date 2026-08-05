# Expense Tracker Bot

A Telegram bot that automatically logs expenses to a Google Sheet using Claude AI for intelligent categorization.

**Features:**
- 📱 Log expenses via Telegram in natural language (Spanish)
- 🤖 Claude AI automatically categorizes and parses expenses
- 💬 Asks follow-up questions when info is missing, and remembers your answers (multi-turn clarification)
- 📊 Saves directly to Google Sheets, organized into one tab per month (e.g. `August/2026`)
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

1. Create a new Google Sheet with columns: `Fecha | Categoría | Descripción | Monto (COP) | Notas`
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

The bot will start polling for messages. Send it expense entries like:
- `"Almuerzo en Starbucks, 25000"`
- `"Uber al trabajo, 28500 ayer"`
- `"Gasté 80000 en gasolina hace 2 días"`

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
├── expense_tracker_design_plan.md   # Design & architecture
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
   - Full chat history so far (not just the latest message) + categorization system prompt

3. **Claude responds with JSON:**
   ```json
   {
     "category": "Alimentación",
     "amount": 25000,
     "description": "Almuerzo en Starbucks",
     "date": "2026-07-25",
     "notes": "",
     "confirmation": "✅ Gasto guardado: Alimentación - $25,000 COP - Almuerzo en Starbucks"
   }
   ```

4. **Bot writes to the correct monthly sheet tab** (e.g. `July/2026`):
   - Appends row: `2026-07-25 | Alimentación | Almuerzo en Starbucks | 25000 | `

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

Once an expense is resolved (saved, or a hard error occurs), the bot forgets that thread — the next message you send starts a brand-new expense from scratch.

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
See `expense_tracker_design_plan.md` for deployment instructions.

---

## Future Features

- Monthly expense summaries
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

- **Design Plan:** See `expense_tracker_design_plan.md`
- **Original Plan:** See `expense_tracker_plan.md`
- **Telegram Bot API:** [python-telegram-bot docs](https://python-telegram-bot.readthedocs.io/)
- **Claude API:** [Anthropic docs](https://docs.anthropic.com/)
- **Google Sheets API:** [Google docs](https://developers.google.com/sheets)
