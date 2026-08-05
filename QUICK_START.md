# Quick Start (5 minutes)

**TL;DR:** Get your bot running in 5 minutes.

## 1. Install (1 min)

```bash
pip install -r requirements.txt
```

## 2. Get Credentials (2 min)

### Telegram Bot Token
1. Message [@BotFather](https://t.me/botfather) on Telegram
2. Type `/newbot`
3. Follow instructions → get token like `123456789:ABCdefGHIJKlmnoPQRstUVwxyzABC`

### Claude API Key
1. Go to [console.anthropic.com](https://console.anthropic.com/)
2. Create API key
3. Copy key like `sk-ant-xxx...`

## 3. Configure (1 min)

```bash
cp .env.example .env
```

Edit `.env` and add your keys:
```
TELEGRAM_BOT_TOKEN=your_bot_token_here
CLAUDE_API_KEY=your_claude_key_here
```

## 4. Run (1 min)

```bash
python main.py
```

Bot is now running. Send it a message in Telegram:
```
"Almuerzo en Starbucks, 25000"
```

Bot replies:
```
✅ Gasto guardado: Alimentación - $25,000 COP - Almuerzo en Starbucks
```

---

## Done! ✅

Your bot is working. Try more messages:
- `"Café, 15000"`
- `"Uber al trabajo, 28500 ayer"`
- `"Gasté 80000 en gasolina hace 2 días"`

If you leave something out (like the amount), the bot will ask for it — just reply with the missing piece and it'll remember the rest of the conversation:
```
User: "Refresco gimnasio"
Bot:  "¿Cuál fue el monto del gasto?"
User: "6000"
Bot:  "✅ Gasto guardado: Salud - $6,000 COP - Refresco gimnasio"
```

---

## Next: Add Google Sheets (Optional)

Once bot is working, add automatic saving to Google Sheets:

1. Create a Google Sheet with columns: `Fecha | Categoría | Descripción | Monto (COP) | Notas`
2. Set up Google Cloud Service Account (see `README.md`)
3. Add to `.env`:
   ```
   GOOGLE_SHEETS_ID=your_sheet_id
   GOOGLE_SERVICE_ACCOUNT_PATH=./service_account.json
   ```
4. Run `python main.py` again

Done! Expenses now save automatically.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Bot doesn't respond | Check `.env` has correct tokens |
| Claude returns error | Make sure message is in Spanish & includes amount |
| Can't get bot token | Message [@BotFather](https://t.me/botfather) on Telegram |
| API key doesn't work | Verify key from [console.anthropic.com](https://console.anthropic.com/) |

---

## Full Guide

See `README.md` for complete setup and troubleshooting.
