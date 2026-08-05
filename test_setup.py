#!/usr/bin/env python3
"""Test script to verify bot setup."""

import os
import sys
from pathlib import Path
import json


def check_env():
    """Check environment variables."""
    print("\n📋 Checking environment variables...")

    required = ["TELEGRAM_BOT_TOKEN", "CLAUDE_API_KEY"]
    optional = ["GOOGLE_SHEETS_ID", "GOOGLE_SERVICE_ACCOUNT_PATH"]

    all_good = True
    for var in required:
        value = os.getenv(var)
        if value:
            masked = value[:10] + "..." if len(value) > 10 else value
            print(f"  ✅ {var}: {masked}")
        else:
            print(f"  ❌ {var}: NOT SET")
            all_good = False

    print("\n  Optional:")
    for var in optional:
        value = os.getenv(var)
        if value:
            print(f"    ✅ {var}: {value}")
        else:
            print(f"    ⚪ {var}: not set (Sheets integration disabled)")

    return all_good


def check_dependencies():
    """Check if required packages are installed."""
    print("\n📦 Checking dependencies...")

    required = [
        "telegram",
        "anthropic",
        "gspread",
        "google.oauth2",
    ]

    all_good = True
    for package in required:
        try:
            __import__(package)
            print(f"  ✅ {package}")
        except ImportError:
            print(f"  ❌ {package}: NOT INSTALLED")
            all_good = False

    if not all_good:
        print("\n  Install dependencies:")
        print("    pip install -r requirements.txt")

    return all_good


def check_service_account():
    """Check if service account JSON exists."""
    print("\n🔐 Checking Google Sheets credentials...")

    path = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH", "service_account.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                data = json.load(f)
                email = data.get("client_email", "unknown")
                print(f"  ✅ {path} (email: {email})")
                return True
        except json.JSONDecodeError:
            print(f"  ❌ {path}: Invalid JSON")
            return False
    else:
        print(f"  ⚪ {path}: Not found (Sheets integration disabled)")
        return False


def test_claude():
    """Test Claude API connection."""
    print("\n🤖 Testing Claude API...")

    try:
        from anthropic import Anthropic

        api_key = os.getenv("CLAUDE_API_KEY")
        if not api_key:
            print("  ❌ CLAUDE_API_KEY not set")
            return False

        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[{"role": "user", "content": "Di 'Hola' en una palabra."}],
        )
        print(f"  ✅ Claude API working")
        return True
    except Exception as e:
        print(f"  ❌ Claude API error: {e}")
        return False


def test_telegram():
    """Test Telegram bot token."""
    print("\n📱 Testing Telegram bot token...")

    try:
        from telegram import Bot

        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            print("  ❌ TELEGRAM_BOT_TOKEN not set")
            return False

        bot = Bot(token=token)
        # This will fail if token is invalid, but we're just checking syntax
        print(f"  ⚠️  Token format looks valid")
        print(f"    (Full verification requires network access)")
        return True
    except Exception as e:
        print(f"  ❌ Telegram error: {e}")
        return False


def main():
    """Run all checks."""
    print("=" * 60)
    print("Expense Tracker Bot - Setup Verification")
    print("=" * 60)

    # Load .env if it exists
    if os.path.exists(".env"):
        from dotenv import load_dotenv

        load_dotenv()
        print("✅ Loaded .env file")
    else:
        print("⚠️  .env file not found. Using environment variables.")

    # Run checks
    env_ok = check_env()
    deps_ok = check_dependencies()
    sa_ok = check_service_account()

    # Only test APIs if minimal env is set
    claude_ok = test_claude() if env_ok else False
    telegram_ok = test_telegram() if env_ok else False

    # Summary
    print("\n" + "=" * 60)
    print("Summary:")
    print("=" * 60)
    print(f"  Environment: {'✅' if env_ok else '❌'}")
    print(f"  Dependencies: {'✅' if deps_ok else '❌'}")
    print(f"  Google Sheets: {'✅' if sa_ok else '⚪'}")
    print(f"  Claude API: {'✅' if claude_ok else '⚠️'}")
    print(f"  Telegram: {'✅' if telegram_ok else '⚠️'}")

    if env_ok and deps_ok:
        print("\n✅ Setup looks good!")
        print("\nNext steps:")
        if not (claude_ok and telegram_ok):
            print("  1. Verify API credentials in .env")
        print("  2. Test Claude parsing: python claude_agent.py")
        print("  3. Run bot: python main.py")
    else:
        print("\n❌ Setup incomplete. See above for issues.")
        sys.exit(1)

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
