"""Telegram bot wiring for the tool-calling expense/income agent.

Alternate entry point to bot.py: dispatches on ToolCallingExpenseAgent's
AgentTurnResult instead of the NDJSON list bot.py's ExpenseAgent returns.
"""

import os
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
from claude_agent_tools import ToolCallingExpenseAgent
from mcp_budget_client import McpBudgetClient
from sheets_writer import SheetsWriter
from off_topic_responses import OFF_TOPIC_RESPONSES

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


class ToolCallingExpenseBot:
    """Telegram bot backed by the tool-calling agentic flow."""

    def __init__(
        self,
        bot_token: str,
        claude_api_key: str,
        sheets_writer: SheetsWriter = None,
        mcp_client: McpBudgetClient = None,
    ):
        self.agent = ToolCallingExpenseAgent(claude_api_key, sheets_writer, mcp_client)
        # Per-chat pending conversation state, so follow-up replies to a
        # clarification question (e.g. a bare amount) have context. Each
        # entry is {"history": [...], "pending_tool_use_id": str | None} -
        # pending_tool_use_id must be threaded back so the follow-up reply is
        # sent as that ask_clarification call's tool_result, per Anthropic's
        # requirement that every tool_use be immediately followed by one.
        self.conversations: dict[int, dict] = {}
        request = HTTPXRequest(connect_timeout=20, read_timeout=20)
        self.app = Application.builder().token(bot_token).request(request).build()

        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        await update.message.reply_text(
            "¡Hola! 👋 Soy tu asistente de gastos e ingresos (versión con tool calling).\n\n"
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
            "- 'Almuerzo 20000, Uber 15000' (múltiples gastos)\n\n"
            "**Ejemplos de ingresos:**\n"
            "- 'Me pagaron el salario, 3000000'\n"
            "- 'Rendimientos de la cuenta, 12000'\n\n"
            "Si hay alguna ambigüedad, te preguntaré antes de guardar."
        )

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming expense/income messages via the tool-calling agent."""
        user_message = update.message.text
        chat_id = update.effective_chat.id
        logger.info(f"Received message from {update.effective_user.id}: {user_message}")

        try:
            pending = self.conversations.get(chat_id, {})
            result = self.agent.handle_message(
                pending.get("history", []), user_message, pending.get("pending_tool_use_id")
            )

            if result.kind == "off_topic":
                self.conversations.pop(chat_id, None)
                await update.message.reply_text(random.choice(OFF_TOPIC_RESPONSES))
                return

            if result.kind == "clarification":
                self.conversations[chat_id] = {
                    "history": result.history,
                    "pending_tool_use_id": result.pending_tool_use_id,
                }
                await update.message.reply_text(result.text)
                return

            if result.kind == "error":
                # Internal failure (e.g. Claude didn't call a tool) - not a
                # pending clarification, start fresh next time.
                self.conversations.pop(chat_id, None)
                await update.message.reply_text(result.text)
                return

            self.conversations.pop(chat_id, None)
            await update.message.reply_text(result.text)
            logger.info(f"Turn resolved for chat {chat_id}: {result.text}")

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            self.conversations.pop(chat_id, None)
            await update.message.reply_text(
                "❌ Error al procesar el gasto. Por favor, intenta de nuevo."
            )

    def run(self):
        """Start the bot."""
        logger.info("Starting tool-calling bot...")
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

    sheets_writer = None
    if sheets_id and os.path.exists(service_account_path):
        try:
            sheets_writer = SheetsWriter(service_account_path, sheets_id)
            logger.info("Google Sheets integration enabled")
        except Exception as e:
            logger.warning(f"Google Sheets not available: {e}. Running without Sheets.")
    else:
        logger.info("Google Sheets credentials not configured. Running in test mode.")

    mcp_client = None
    if sheets_id and os.path.exists(service_account_path):
        mcp_client = McpBudgetClient()
        try:
            mcp_client.start()
            logger.info("MCP budget-summary integration enabled")
        except Exception as e:
            logger.warning(f"MCP sheets server not available: {e}. Running without budget summaries.")
            mcp_client = None
    else:
        logger.info("Google Sheets credentials not configured. Running without budget summaries.")

    bot = ToolCallingExpenseBot(bot_token, claude_api_key, sheets_writer, mcp_client)
    try:
        bot.run()
    finally:
        if mcp_client is not None:
            mcp_client.stop()


if __name__ == "__main__":
    main()
