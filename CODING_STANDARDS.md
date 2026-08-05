# Coding Standards

These standards apply to the C# components of this project (Telegram Bot, ASP.NET Core API). They exist to keep the codebase consistent, testable, and easy to change as the project grows. Business logic that lives in the Claude agent's system prompt (categorization rules, parsing) is governed separately by `CLAUDE.md` and files in the `/specs` folder not by this file.

---

## 1. Guiding Philosophy

- **Simplicity first.** Prefer the straightforward solution over the clever one. This is a small, single-purpose bot — resist over-engineering it into a framework.
- **Optimize for change.** The categorization rules and agent behavior will change often; the plumbing around them (bot, API, sheet writer) should not need to change when they do.
- **YAGNI.** Don't build abstractions, interfaces, or configuration options for requirements that don't exist yet.
- **Boy Scout Rule.** Leave code you touch slightly cleaner than you found it — but don't use a small fix as an excuse for an unrelated rewrite.

---

## 2. SOLID Principles

### Single Responsibility Principle (SRP)
Each class should have one reason to change.
- The Telegram bot's message handler should only translate Telegram updates into API calls and API responses back into Telegram messages — it should not contain expense parsing or categorization logic.
- The API's controller should only handle HTTP concerns (validation, status codes) and delegate the actual work to a service.
- A service that talks to the Claude API should not also know about Telegram-specific formatting.

### Open/Closed Principle (OCP)
Code should be open for extension, closed for modification.
- If new expense sources are added later (e.g., a web form in addition to Telegram), the core `ExpenseService` should not need to change — only a new adapter/entry point should be added.
- Avoid `switch` statements on type codes that will need a new case every time a feature is added; prefer polymorphism or strategy objects when the number of variants is expected to grow.

### Liskov Substitution Principle (LSP)
Subtypes must be substitutable for their base types without surprising callers.
- If you introduce an interface (e.g., `IExpenseSink`) with multiple implementations, every implementation must honor the same contract (e.g., idempotency, error behavior) — no implementation should throw for cases the interface's other implementations silently handle.

### Interface Segregation Principle (ISP)
Prefer small, focused interfaces over large general-purpose ones.
- Don't create one big `IExpenseTracker` interface with unrelated methods (parsing, persistence, notification). Split by responsibility so consumers only depend on what they use.

### Dependency Inversion Principle (DIP)
High-level modules should depend on abstractions, not concrete implementations.
- The API layer should depend on an `IClaudeAgentClient` abstraction, not directly on the Anthropic SDK client, so it can be tested with a fake/mock.
- Use ASP.NET Core's built-in DI container for wiring; avoid `new`-ing up dependencies (HTTP clients, SDK clients) inside business logic classes.

---

## 3. Clean Code

### Naming
- Use intention-revealing names. `expenseText`, not `s` or `input`.
- Class names are nouns (`ExpenseRequest`), method names are verbs (`ParseAmount`, `AppendRow`).
- Avoid abbreviations unless they're domain-standard (`COP` is fine; `exp` is not).
- Booleans read as predicates: `isValid`, `hasCategory`, not `valid`, `category_flag`.

### Functions
- Keep functions small and doing one thing. If you need a comment to separate sections of a function, split it into functions.
- Prefer few arguments (0–3). Bundle related parameters into a request/DTO object instead of adding more positional parameters.
- Avoid boolean flag arguments that change a function's behavior (`SendMessage(text, true)`); use separate methods or named options instead.
- No side effects hidden behind an innocuous-looking name — a function called `GetTotal()` should not also write to the database.

### Comments
- Code should explain itself through naming and structure. Only comment on the *why*, never the *what*.
- Delete commented-out code before committing — git history is the record, not the file.
- No TODO comments left unassigned/undated in committed code; open an issue instead if it's not being done now.

### Formatting & Structure
- Follow standard .NET conventions (`dotnet format` / the repo's `.editorconfig` if present) — don't hand-roll a different style.
- One class per file, file name matches class name.
- Keep related code close together (vertical proximity); unrelated concerns go in separate files.

### Error Handling
- Use exceptions for exceptional cases, not for normal control flow (e.g., "amount ambiguous" is a valid business outcome the agent should return as data, not throw).
- Don't swallow exceptions silently. If you catch, either handle meaningfully or log and rethrow.
- Fail fast on invalid input at system boundaries (the API endpoint), rather than letting bad data propagate deep into the call stack.
- Never expose internal exception details (stack traces, connection strings) in API responses to Telegram users.

### DRY, but not at the cost of clarity
- Remove real duplication (same logic, same reason to change).
- Don't force two coincidentally-similar pieces of code into one abstraction if they're likely to diverge for different reasons — that creates coupling, not reuse.

---

## 4. Clean Architecture

Keep a clear separation of layers so business logic doesn't depend on frameworks or I/O:

```
┌─────────────────────────────────────┐
│   Presentation (Telegram Bot,        │  ← depends on ↓
│   API Controllers)                   │
├─────────────────────────────────────┤
│   Application (Services, Use Cases)  │  ← depends on ↓
├─────────────────────────────────────┤
│   Domain (Expense, Category,         │  ← depends on nothing
│   validation rules)                  │
├─────────────────────────────────────┤
│   Infrastructure (Claude SDK client, │  ← implements Application's
│   Telegram.Bot client, HTTP)         │     interfaces
└─────────────────────────────────────┘
```

Rules:
- **Dependencies point inward.** The Domain layer must not reference ASP.NET Core, `Telegram.Bot`, or the Anthropic SDK.
- **Controllers are thin.** They validate the request shape, call an application service, and map the result to an HTTP response. No business logic in controllers.
- **Infrastructure is swappable.** The Claude API client and Telegram client should sit behind interfaces defined in the Application layer, so they can be mocked in tests and replaced without touching business logic.
- **DTOs at the boundary.** Don't leak internal domain models directly across the API boundary; map explicitly, even if the mapping looks redundant today — it decouples your public contract from internal refactors.

---

## 5. Testing

- Every application service (the part that orchestrates parsing → categorization → sheet append) should have unit tests covering the happy path and the documented edge cases from `CLAUDE.md` (multi-item desglose, ambiguous amount, unclear category → `Otros`).
- Mock external dependencies (Claude API, Google Sheets, Telegram) in unit tests — do not make real network calls.
- Prefer testing behavior (given this expense text, expect this row shape) over testing implementation details (internal method call counts).
- Integration tests, if added, should be clearly separated from unit tests (e.g., separate test project or trait/category) so they can be excluded from fast local runs.

---

## 6. Security & Configuration

- Never commit secrets. Telegram bot token and Claude API key come from environment variables / `.env` (already gitignored) — see `CLAUDE.md` Security Notes.
- Validate and sanitize the `telegramUserId` on every API request; don't trust client-supplied IDs without checking against an allowlist or session state.
- Log enough to debug production issues (request received, category assigned, row appended) but never log secrets, full API keys, or raw tokens.
- Consider basic rate limiting on `POST /api/expenses` since it's an inbound webhook-style surface (see `CLAUDE.md`).

---

## 7. Commits & Reviews

- Commit messages explain *why*, not just *what* (the diff already shows what changed).
- Keep commits and PRs scoped to one logical change — don't mix a refactor with a feature in the same commit.
- Before requesting review, self-review the diff: check for leftover debug code, commented-out blocks, and unused usings/imports.

---

## 8. When These Rules Conflict

If following a rule here would make the code harder to understand or the project harder to ship, favor clarity and pragmatism, and raise it for discussion rather than silently deviating. These are defaults, not laws — but deviations should be deliberate, not accidental.
