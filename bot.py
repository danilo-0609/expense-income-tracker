"""Telegram bot for expense tracking."""

import os
import sys
import asyncio
import logging
import random
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.request import HTTPXRequest
from claude_agent import ExpenseAgent
from sheets_writer import SheetsWriter
from off_topic_responses import OFF_TOPIC_RESPONSES

# Load environment variables from .env file
load_dotenv()


# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


class ExpenseBot:
    """Telegram bot for expense tracking."""

    def __init__(self, bot_token: str, claude_api_key: str, sheets_writer: SheetsWriter = None):
        """Initialize bot with credentials."""
        self.bot_token = bot_token
        self.agent = ExpenseAgent(claude_api_key)
        self.sheets_writer = sheets_writer
        # Per-chat conversation history, so follow-up replies to a
        # clarification question (e.g. a bare amount) have context.
        self.conversations: dict[int, list[dict]] = {}
        request = HTTPXRequest(connect_timeout=20, read_timeout=20)
        self.app = Application.builder().token(bot_token).request(request).build()

        # Add handlers
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        await update.message.reply_text(
            "¡Hola! 👋 Soy tu asistente de gastos e ingresos.\n\n"
            "Envíame un gasto o un ingreso en español y lo registraré automáticamente. Ejemplos:\n"
            "- 'Almuerzo en Starbucks, 25000'\n"
            "- 'Uber al trabajo, 28500'\n"
            "- 'Me pagaron el salario, 3000000'\n"
            "- 'Rendimientos de la cuenta, 12000'\n\n"
            "Usa /help para más información."
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        await update.message.reply_text(
            "📝 **Cómo usar este bot:**\n\n"
            "Escribe un gasto o un ingreso en español con el formato:\n"
            "`<descripción>, <monto>` o `<descripción>, <monto>, <fecha>`\n\n"
            "**Ejemplos de gastos:**\n"
            "- 'Almuerzo en Starbucks, 25000'\n"
            "- 'Café, 15000 ayer'\n"
            "- 'Gasolina, 80000 hace 2 días'\n"
            "- 'Almuerzo 20000, Uber 15000' (múltiples gastos)\n"
            "- 'Crema para mamá, 30000 el 24 de julio'\n\n"
            "**Ejemplos de ingresos:**\n"
            "- 'Me pagaron el salario, 3000000'\n"
            "- 'Rendimientos de la cuenta, 12000'\n"
            "- 'Recibí mi pago salarial el 1 de agosto, 3000000'\n\n"
            "El bot:\n"
            "1. Identifica si es un gasto o un ingreso, y su categoría\n"
            "2. Extrae la cantidad y la fecha\n"
            "3. Guarda el movimiento en la hoja de cálculo correspondiente\n\n"
            "Si hay alguna ambigüedad, se guardará con una nota para que revises después."
        )

    # Internal failure messages that mean "something broke", as opposed to a
    # genuine clarification question Claude is asking the user.
    INTERNAL_ERROR_MESSAGES = {
        "Error parsing response from Claude",
        "No response from Claude",
    }

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming expense messages."""
        user_message = update.message.text
        chat_id = update.effective_chat.id
        logger.info(f"Received message from {update.effective_user.id}: {user_message}")

        try:
            # Continue any pending clarification conversation for this chat
            history = self.conversations.get(chat_id, [])
            history.append({"role": "user", "content": user_message})

            expenses, response_text = self.agent.parse_expense(history)

            if any(expense.get("off_topic") for expense in expenses):
                # Off-topic input (or a prompt-injection attempt) is a dead
                # end, not a pending clarification - start fresh next time.
                self.conversations.pop(chat_id, None)
                await update.message.reply_text(random.choice(OFF_TOPIC_RESPONSES))
                return

            is_clarification = any(
                expense.get("error") and expense.get("message") not in self.INTERNAL_ERROR_MESSAGES
                for expense in expenses
            )

            if is_clarification:
                # Keep the conversation so the next reply has context
                history.append({"role": "assistant", "content": response_text})
                self.conversations[chat_id] = history
            else:
                # Expense resolved (saved) or hit an internal error - start fresh next time
                self.conversations.pop(chat_id, None)

            # Handle response
            for expense in expenses:
                if expense.get("error"):
                    # Error response (e.g., missing amount, or internal failure)
                    await update.message.reply_text(expense["message"])
                else:
                    # Success response
                    confirmation = expense.get(
                        "confirmation",
                        "✅ Gasto guardado"
                    )

                    # Write to Sheets if writer is available
                    if self.sheets_writer:
                        self.sheets_writer.write_expense(expense)

                    await update.message.reply_text(confirmation)
                    logger.info(f"Expense saved: {expense}")

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            self.conversations.pop(chat_id, None)
            await update.message.reply_text(
                "❌ Error al procesar el gasto. Por favor, intenta de nuevo."
            )

    def run(self):
        """Start the bot."""
        logger.info("Starting bot...")
        # Python 3.14 no longer auto-creates an event loop for the main thread;
        # run_polling() internally calls asyncio.get_event_loop(), so create
        # and register one explicitly before calling it.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.app.run_polling()


def main():
    """Main entry point."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    claude_api_key = os.getenv("CLAUDE_API_KEY")
    sheets_id = os.getenv("GOOGLE_SHEETS_ID")
    service_account_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH", "service_account.json")

    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")
    if not claude_api_key:
        raise ValueError("CLAUDE_API_KEY environment variable not set")

    # Initialize Sheets writer if credentials are available
    sheets_writer = None
    if sheets_id and os.path.exists(service_account_path):
        try:
            sheets_writer = SheetsWriter(service_account_path, sheets_id)
            logger.info("Google Sheets integration enabled")
        except Exception as e:
            logger.warning(f"Google Sheets not available: {e}. Running without Sheets.")
    else:
        logger.info("Google Sheets credentials not configured. Running in test mode.")

    bot = ExpenseBot(bot_token, claude_api_key, sheets_writer)
    bot.run()


if __name__ == "__main__":
    main()
