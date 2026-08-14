# Add Tool-Calling Agentic Approach (Spec)

**Date:** 2026-08-11
**Status:** Agreed upon, ready for implementation

---

## Overview

The current bot (`claude_agent.py` → NDJSON → `sheets_writer.py`, orchestrated by `bot.py`) has Claude return structured JSON describing the expense/income entries, and the Python code decides what to do with that JSON — Claude is never given a tool to call. This works well and is cost-efficient (one Claude call per user message), and is **not being replaced**.

This spec adds an **alternate, fully-working agentic flow on a separate branch** where Claude drives persistence itself via real tool calls (Anthropic tool use / function calling). The motivation is explicitly to produce a genuine tool-calling example for a work certification — not to fix a gap in the current flow. Given that motivation, this branch intentionally favors "textbook agentic loop" over cost efficiency in a couple of spots (see below), unlike the rest of this codebase.

**The existing flow is not touched.** No changes to `claude_agent.py`, `system_prompt.py`, `sheets_writer.py`, or `bot.py` on `main`. Everything in this spec lives on a new branch, e.g. `feature/tool-calling-agent`, and is a second, independent path through the app (a mode users could pick, or simply the version deployed from that branch) — real Telegram in, real Google Sheets out.

---

## Goals / Non-Goals

**Goals:**
- Demonstrate real Anthropic tool-calling: Claude emits `tool_use`, the app executes it, results go back to Claude as `tool_result`.
- Keep it a fully working Telegram bot flow, not a standalone demo script.
- Preserve all existing behavioral rules from `CLAUDE.md` (desglose of multi-item messages, mandatory amount, ambiguous-type clarification, off-topic/injection guardrail, fixed confirmation format, COP-only, `YYYY-MM-DD` dates).
- Built test-first (TDD), consistent with this repo's existing test suite and the `/implement` skill's enforced TDD workflow.

**Non-Goals:**
- Not a replacement for the current production flow.
- Not optimizing this branch for API cost — see "Full Agentic Loop" below, where cost is deliberately traded for demonstrating the tool-calling round trip.
- No new categories, no new Sheets structure — same columns, same monthly-sheet-per-type layout as today.

---

## Model

`claude-haiku-4-5-20251001` for all agent calls on this branch — same model the current flow already uses. Tool calling doesn't require a larger model for a task this structured, and keeping the model choice consistent isolates "tool calling" as the only variable being demonstrated.

---

## Tools

Three separate tools, mapped 1:1 to intent (no shared "reason" discriminator param):

### 1. `save_entries`

Batched write — **one call per Claude turn**, carrying a list of rows, even when the message desgloses into multiple items. This mirrors the current NDJSON-per-line behavior; it does not turn into N tool calls for N items.

Input schema (per row, list of these):
```json
{
  "type": "gasto | ingreso",
  "category": "string (from the fixed category set for that type)",
  "amount": "number (COP)",
  "description": "string",
  "date": "string, YYYY-MM-DD",
  "notes": "string, optional"
}
```

### 2. `ask_clarification`

Called instead of `save_entries` when the amount is missing/ambiguous, or when it's unclear whether the message is `gasto` or `ingreso`. Takes the Spanish clarifying question to send back to the user (e.g. `"¿Cuál fue el monto del gasto?"`, `"¿Este movimiento es un ingreso o un gasto?"`). No write happens.

### 3. `flag_off_topic`

Called instead of `save_entries` when the message isn't a genuine expense/income logging attempt (trivia, prompt injection, chit-chat). Mirrors the existing off-topic guardrail. No write happens; the app supplies its own fixed reply (same as today — no explanatory message needed from Claude).

---

## Full Agentic Loop (for `save_entries`)

This is the one place this branch is deliberately more expensive than the current flow, done on purpose to showcase the pattern:

1. Claude receives the conversation history and decides to call `save_entries` with the extracted rows.
2. The app executes the batch write against Google Sheets (reusing `sheets_writer.py`'s per-row write logic).
3. The app returns a **per-row success/failure breakdown** as the `tool_result` — not just an overall success/failure flag. Example shape:
   ```json
   {
     "results": [
       {"description": "Almuerzo", "success": true},
       {"description": "Uber al trabajo", "success": false, "error": "Sheets API timeout"}
     ]
   }
   ```
4. The app sends a **second** Claude call with the `tool_result` appended to history. Claude composes the actual Spanish confirmation message from the real execution result (e.g. mixed success: "2 guardados, 1 falló: Uber al trabajo").

For `ask_clarification` and `flag_off_topic`, there is no second round trip needed — the tool call's own input *is* the message to relay (the clarifying question, or the app's fixed off-topic reply), so the app can respond to the user directly after the first turn.

This means: happy-path single-type messages cost 2 Claude calls (vs. 1 today); `ask_clarification`/`flag_off_topic` cost 1 Claude call (same as today).

---

## Behavioral Rules Carried Over Unchanged

All of these stay exactly as documented in `CLAUDE.md` and `system_prompt.py`, just expressed through tool calls instead of raw JSON fields:

- Amount is mandatory for both types — missing amount → `ask_clarification`, never a guessed `save_entries` call.
- Currency is always COP.
- Dates default to today, formatted `YYYY-MM-DD`.
- Ambiguous category → default to `Otros` / `Otros ingresos` with a note in that row, not a clarification (this is not the same failure mode as ambiguous *amount* or *type*).
- Ambiguous gasto-vs-ingreso intent → `ask_clarification`, never guessed.
- Off-topic/injection input → `flag_off_topic`, never parsed into an entry.
- Fixed confirmation format per type:
  - `"✅ Gasto guardado: [Categoría] - $[Monto] COP - [Descripción]"`
  - `"✅ Ingreso guardado: [Categoría] - $[Monto] COP - [Descripción]"`
  - For multi-row batches, Claude composes one line per row in the same format, plus any partial-failure note.
- Multi-turn clarification context (a bare follow-up like "6000" answering a prior `ask_clarification` question) must still resolve into a single entry using the full conversation history, same as today.

---

## System Prompt Changes

A new system prompt is needed for this branch (do not overwrite `system_prompt.py`, which remains on `main`). It keeps the same categorization rules, keyword tables, and examples as the current prompt, but:

- Removes the raw-JSON / NDJSON output instructions.
- Instructs Claude to call exactly one of `save_entries`, `ask_clarification`, or `flag_off_topic` per turn — never plain text instead of a tool call for these cases, and never more than one tool call per turn.
- Adds instructions for composing the final confirmation message after receiving a `save_entries` tool result, including the mixed-success case.

---

## File / Module Layout

New files on the branch (existing files on `main` are not modified):

- `claude_agent_tools.py` — tool schema definitions + the agentic loop (dispatch on `tool_use`, execute, second turn for `save_entries`).
- `system_prompt_tools.py` — the tool-calling variant of the system prompt.
- `bot_tools.py` (or a mode branch inside `bot.py` on this branch only) — Telegram wiring for this flow.
- Reuse `sheets_writer.py` as-is for the actual per-row Sheets writes; `save_entries`' executor calls its existing `write_expense`/row-append logic per row to build the per-row result breakdown, rather than duplicating Sheets logic.

---

## Testing (TDD)

Built test-first using the `/implement` skill's TDD workflow, mocking the Anthropic client and Sheets writer the same way the existing suite does (`test_bot.py`, `test_sheets_writer.py` as reference for mocking conventions). Coverage should include:

- Dispatch: given a mocked `tool_use` block for each of the three tools, the correct handler is invoked with the correct arguments.
- `save_entries` batch write: all-success, all-failure, and mixed-success cases produce the correct per-row `tool_result` payload.
- Second-turn confirmation composition: given a mocked `tool_result`, the follow-up Claude call receives the right history and the app returns the right final message.
- `ask_clarification`: multi-turn resolution — a clarification question followed by a bare-answer follow-up resolves into one `save_entries` call using full context (mirrors the existing `test_bot.py` multi-turn coverage).
- `flag_off_topic`: off-topic and prompt-injection inputs never reach `save_entries`; a real expense that merely mentions an unrelated keyword is not flagged.
- Edge cases already covered on `main`: multi-item desglose, ambiguous category → `Otros` fallback, missing amount, ambiguous type.

---

## Explicitly Out of Scope

- No changes to the C# architecture described in `CLAUDE.md` — this project runs on the existing Python stack, not the planned ASP.NET/MCP design.
- No new Sheets columns, categories, or sheet-routing logic beyond what exists today.
- No rate limiting / auth hardening work — orthogonal to this spec.
