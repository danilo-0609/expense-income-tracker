# Coding Standards

These standards apply to the Python components of this project (Telegram bot, Claude agent client, Sheets writer). They exist to keep the codebase consistent, testable, and easy to change as the project grows. Business logic that lives in the Claude agent's system prompt (categorization rules, parsing) is governed separately by `CLAUDE.md` and files in the `/specs` folder, not by this file.

---

## 1. Guiding Philosophy

- **Simplicity first.** Prefer the straightforward solution over the clever one. This is a small, single-purpose bot — resist over-engineering it into a framework.
- **Optimize for change.** The categorization rules and agent behavior will change often; the plumbing around them (bot, agent client, sheet writer) should not need to change when they do.
- **YAGNI.** Don't build abstractions, base classes, or configuration options for requirements that don't exist yet.
- **Boy Scout Rule.** Leave code you touch slightly cleaner than you found it — but don't use a small fix as an excuse for an unrelated rewrite.

---

## 2. SOLID Principles

### Single Responsibility Principle (SRP)
Each module/class should have one reason to change.
- `bot.py`'s message handler should only translate Telegram updates into agent calls and agent responses back into Telegram messages — it should not contain expense parsing or categorization logic.
- `claude_agent.py` should only know how to call Claude and parse its NDJSON response — it should not know about Telegram-specific formatting or Sheets I/O.
- `sheets_writer.py` should only know how to write rows to the correct sheet — it should not know how a row was parsed or classified.

### Open/Closed Principle (OCP)
Code should be open for extension, closed for modification.
- If new expense sources are added later (e.g., a web form in addition to Telegram), `ExpenseAgent` and `SheetsWriter` should not need to change — only a new entry point should be added that calls them.
- Avoid `if/elif` chains on type codes that will need a new branch every time a feature is added; prefer a dict-based dispatch or small strategy functions when the number of variants is expected to grow (e.g. `SHEET_NAME_PREFIXES` in `sheets_writer.py` is the right pattern for this).

### Liskov Substitution Principle (LSP)
Substitutable components must honor the same contract.
- If you introduce multiple implementations of a component (e.g., an alternate `SheetsWriter` backed by a different store), every implementation must honor the same contract (idempotency, error behavior) — no implementation should raise for cases another implementation silently handles.

### Interface Segregation Principle (ISP)
Prefer small, focused modules over large general-purpose ones.
- Don't create one big class with unrelated methods (parsing, persistence, notification). Split by responsibility so consumers only depend on what they use — mirrored today by the `bot.py` / `claude_agent.py` / `sheets_writer.py` split.

### Dependency Inversion Principle (DIP)
High-level modules should depend on abstractions, not concrete implementations.
- `ExpenseBot` takes its `SheetsWriter` and API keys via constructor injection rather than constructing them internally — keep this pattern so components can be swapped for fakes/mocks in tests.
- Don't reach for a DI framework here; plain constructor injection is enough at this project's size.

---

## 3. Clean Code

### Naming
- Use intention-revealing names. `expense_text`, not `s` or `input`.
- Class names are nouns (`SheetsWriter`), function/method names are verbs (`parse_expense`, `write_expense`).
- Avoid abbreviations unless they're domain-standard (`COP` is fine; `exp` is not).
- Booleans read as predicates: `is_valid`, `has_category`, not `valid`, `category_flag`.
- Follow PEP 8 naming: `snake_case` for functions/variables/modules, `PascalCase` for classes, `UPPER_SNAKE_CASE` for module-level constants.

### Functions
- Keep functions small and doing one thing. If you need a comment to separate sections of a function, split it into functions.
- Prefer few arguments (0–3). Bundle related parameters into a dict/dataclass instead of adding more positional parameters.
- Avoid boolean flag arguments that change a function's behavior (`send_message(text, True)`); use separate functions or named/keyword-only options instead.
- No side effects hidden behind an innocuous-looking name — a function called `get_total()` should not also write to the sheet.

### Comments
- Code should explain itself through naming and structure. Only comment on the *why*, never the *what* (see the Python 3.14 event-loop comment in `bot.py:run()` for the right level of detail).
- Delete commented-out code before committing — git history is the record, not the file.
- No TODO comments left unassigned/undated in committed code; open an issue instead if it's not being done now.

### Formatting & Structure
- Follow PEP 8. Use type hints on public function signatures (already the convention in this codebase — see `claude_agent.py`, `sheets_writer.py`).
- One class per file where practical; file name reflects its primary responsibility (`bot.py`, `claude_agent.py`, `sheets_writer.py`).
- Keep related code close together (vertical proximity); unrelated concerns go in separate modules.

### Error Handling
- Use exceptions for exceptional cases, not for normal control flow — "amount ambiguous" is a valid business outcome the agent should return as data (`{"error": True, "message": ...}`), not raise.
- Don't swallow exceptions silently. If you catch, either handle meaningfully or log and re-raise.
- Fail fast on missing configuration at startup (see `main()` in `bot.py` raising `ValueError` for missing env vars) rather than letting `None` propagate deep into the call stack.
- Never expose internal exception details (stack traces, credentials, raw API errors) in messages sent back to Telegram users — log them, send a generic Spanish error message instead.

### DRY, but not at the cost of clarity
- Remove real duplication (same logic, same reason to change).
- Don't force two coincidentally-similar pieces of code into one abstraction if they're likely to diverge for different reasons — that creates coupling, not reuse.

---

## 4. Architecture

Keep a clear separation of responsibilities so business logic doesn't get tangled with I/O:

```
┌─────────────────────────────────────┐
│   Presentation (bot.py)              │  ← depends on ↓
│   Telegram polling, message routing  │
├─────────────────────────────────────┤
│   Agent (claude_agent.py)            │  ← depends on ↓
│   Calls Claude, parses NDJSON        │
├─────────────────────────────────────┤
│   Domain (system_prompt.py)          │  ← depends on nothing
│   Categorization/parsing rules       │
├─────────────────────────────────────┤
│   Infrastructure (sheets_writer.py)  │  ← called by Presentation,
│   gspread client, sheet routing      │     independent of Agent
└─────────────────────────────────────┘
```

Rules:
- **`bot.py` stays thin.** It translates Telegram updates into agent calls, routes clarification vs. success vs. off-topic responses, and formats replies. No parsing or categorization logic belongs here.
- **The agent is swappable.** `ExpenseAgent` and `SheetsWriter` are both passed into `ExpenseBot` at construction, so either can be replaced with a fake in tests without touching the other.
- **No premature API layer.** Per `specs/expense_tracker_design_plan.md`, the bot talks to Claude and Sheets directly — don't introduce a web framework/API layer unless a second client (beyond Telegram) actually needs to reuse this logic.

---

## 5. Testing

- Every module with non-trivial logic (`claude_agent.py`'s response parsing, `sheets_writer.py`'s sheet routing, `bot.py`'s message handling) should have `pytest` tests covering the happy path and the documented edge cases from `CLAUDE.md` (multi-item desglose, ambiguous amount, unclear category → `Otros`, expense-vs-income ambiguity, off-topic/prompt-injection input).
- Mock external dependencies (Anthropic client, `gspread`/Google Sheets, Telegram) in unit tests — do not make real network calls. Use `unittest.mock` (`Mock`, `patch`) as done in the existing test suite.
- Prefer testing behavior (given this expense text, expect this row shape) over testing implementation details (internal call counts).
- Async handlers (`bot.py`'s `handle_message`, etc.) are tested with `pytest-asyncio` (`asyncio_mode = auto` in `pytest.ini`) — no need to manually manage event loops in tests.
- Manual/smoke tests that hit the real Claude API (like `claude_agent.py`'s `main()`) are useful for exploration but are not a substitute for mocked unit tests, and shouldn't be treated as part of the automated suite.

---

## 6. Security & Configuration

- Never commit secrets. Telegram bot token, Claude API key, and the Google Service Account JSON path come from environment variables / `.env` (already gitignored) — see `CLAUDE.md` Security Notes.
- The Google Service Account JSON key file itself must never be committed; keep it outside version control and reference it only via `GOOGLE_SERVICE_ACCOUNT_PATH`.
- Log enough to debug production issues (message received, category assigned, row appended) but never log secrets, full API keys, or raw credential contents.
- Since the bot uses polling rather than a webhook, there's no inbound HTTP surface to rate-limit — but treat all message text as untrusted input (see the off-topic/prompt-injection guardrail in `off_topic_responses.py` and the system prompt).

---

## 7. Commits & Reviews

- Commit messages explain *why*, not just *what* (the diff already shows what changed).
- Keep commits and PRs scoped to one logical change — don't mix a refactor with a feature in the same commit.
- Before requesting review, self-review the diff: check for leftover debug code, commented-out blocks, and unused imports.

---

## 8. When These Rules Conflict

If following a rule here would make the code harder to understand or the project harder to ship, favor clarity and pragmatism, and raise it for discussion rather than silently deviating. These are defaults, not laws — but deviations should be deliberate, not accidental.
