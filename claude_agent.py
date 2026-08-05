"""Claude agent for expense parsing and categorization."""

import json
import logging
import os
from dotenv import load_dotenv
from anthropic import Anthropic
from system_prompt import SYSTEM_PROMPT

# Load environment variables from .env file
load_dotenv()


class ExpenseAgent:
    """Handles expense parsing via Claude API."""

    def __init__(self, api_key: str):
        """Initialize Claude client."""
        self.client = Anthropic(api_key=api_key)
        self.system_prompt = SYSTEM_PROMPT

    def parse_expense(self, history: list[dict]) -> tuple[list[dict], str]:
        """
        Parse expense conversation and return structured data.

        Args:
            history: Conversation so far as a list of Anthropic-style messages
                ({"role": "user"|"assistant", "content": str}). Includes any
                prior clarification questions/answers so follow-up replies
                (e.g. a bare amount answering "¿Cuál fue el monto?") have
                context.

        Returns:
            A tuple of:
            - List of expense dictionaries. Each can have:
              - "error": true + "message" (for errors/clarification requests)
              - Or: "category", "amount", "description", "date", "notes", "confirmation"
            - The raw assistant response text, so the caller can append it to
              the conversation history for the next turn.
        """
        response = self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=self.system_prompt,
            messages=history,
        )

        response_text = response.content[0].text.strip()

        # Strip markdown code fences in case the model wraps its output
        # (e.g. ```json ... ```) despite being told to return raw JSON.
        parsed_text = response_text
        if parsed_text.startswith("```"):
            parsed_text = parsed_text.strip("`")
            if parsed_text.startswith("json"):
                parsed_text = parsed_text[4:]
            parsed_text = parsed_text.strip()

        # Parse the response as NDJSON (newline-delimited JSON)
        # Each line is a separate JSON object
        expenses = []
        for line in parsed_text.split("\n"):
            line = line.strip()
            if not line or line == "```":
                continue
            try:
                expense = json.loads(line)
                expenses.append(expense)
            except json.JSONDecodeError:
                logging.error(f"Failed to parse Claude response as JSON. Raw response:\n{response_text}")
                return [{"error": True, "message": "Error parsing response from Claude"}], response_text

        if not expenses:
            return [{"error": True, "message": "No response from Claude"}], response_text

        return expenses, response_text


def main():
    """Test the agent with sample inputs."""
    import os

    api_key = os.getenv("CLAUDE_API_KEY")
    if not api_key:
        print("Error: CLAUDE_API_KEY environment variable not set")
        return

    agent = ExpenseAgent(api_key)

    # Test cases from the design plan
    test_cases = [
        "Almuerzo en Starbucks, 25000 ayer",
        "Café en Starbucks ayer",
        "Gasté 30000 en la tienda el 24 de julio",
        "Almuerzo 20000, Uber al trabajo 15000",
        "Gasté 80000 en gasolina ayer",
    ]

    for test in test_cases:
        print(f"\n{'=' * 60}")
        print(f"Input: {test}")
        print("-" * 60)
        expenses, _ = agent.parse_expense([{"role": "user", "content": test}])
        for expense in expenses:
            print(json.dumps(expense, indent=2, ensure_ascii=False))

    # Multi-turn clarification: a message missing the amount should prompt a
    # follow-up question, and a bare reply to that question should resolve
    # into a single expense using context from the earlier turn.
    print(f"\n{'=' * 60}")
    print("Multi-turn: 'Refresco gimnasio' -> '6000'")
    print("-" * 60)
    history = [{"role": "user", "content": "Refresco gimnasio"}]
    expenses, response_text = agent.parse_expense(history)
    for expense in expenses:
        print(json.dumps(expense, indent=2, ensure_ascii=False))
    assert any(e.get("error") for e in expenses), "Expected a clarification question when amount is missing"

    history.append({"role": "assistant", "content": response_text})
    history.append({"role": "user", "content": "6000"})
    expenses, _ = agent.parse_expense(history)
    for expense in expenses:
        print(json.dumps(expense, indent=2, ensure_ascii=False))
    assert not any(e.get("error") for e in expenses), "Expected the follow-up reply to resolve into a saved expense"


if __name__ == "__main__":
    main()
